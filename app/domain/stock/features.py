"""Ham veri (Parquet/DB) -> StockFeatures. Kayan pencereyle talep istatistikleri.

Sahip: Kişi A · Faz 2 A2.1

Bu modül, `simulator.run.simulasyon_calistir` çıktısındaki ham tabloları
(`talep`, `envanter_gunluk`, `sku`, `tedarikci`) alıp sözleşmedeki
`StockFeatures` (`app/contracts.py`) nesnesine dönüştürür. `decide.py`
(A2.6) bu nesneyi kural motoruna verir.

**Kayan pencere tasarımı:** Ortalama günlük talep ve standart sapma hem 30
hem 90 günlük pencereyle hesaplanır. Nihai `StockFeatures.ort_gunluk_talep` /
`talep_std` **90 günlük pencereden** gelir — `rules.py`'deki emniyet stoğu
formülü varyansa karşı hassastır, kısa bir pencere gürültüyü olduğundan büyük
gösterip emniyet stoğunu yanlış kalibre eder. 30 günlük pencere ayrıca
hesaplanıp döndürülür (kısa vadeli sinyal, ileride ML özelliği olarak
kullanılabilir). İki pencere de `pandas.rolling(min_periods=1)` kullandığı
için `veri_gun_sayisi < pencere` olan erken günlerde otomatik olarak mevcut
tüm geçmişe daralır — ayrı bir "yetersiz veri" dalı yazmaya gerek kalmaz.

**Bilinçli sınırlamalar (henüz yazılmamış modüllere bağımlılık):**
`abc_sinifi`, `xyz_sinifi`, `hedef_servis_seviyesi` (A2.4) ve `tedarikci_skoru`
(A2.5) bu modülün sorumluluğunda değildir — parametre olarak alınır, makul
varsayılanlarla. `decide.py` gerçek sınıflandırma/skorlama fonksiyonlarını
zaten kullanıyor (`siniflandirma` argümanı) — buradaki varsayılanlar yalnızca
`siniflandirma` verilmediğinde (ör. `decide.py` dışında doğrudan çağrılırsa)
devreye girer.

**`StockFeatures`'ın üç alanı hakkında kesinleşmiş kararlar** (B'nin SP1
incelemesinde kaynağı sorulmuştu — üçü de simülatörün mevcut tasarımının
doğal sonucu, Kişi A tarafında kesinleştirildi):

- `tedarikci_onayli` — yukarıda `TEDARIKCI_ONAY_ESIGI` docstring'inde detaylı.
- `raf_omru_kalan_gun` — simülatör parti/lot bazlı stok yaşlandırması
  tutmuyor (yalnızca toplam eldeki stok, hangi partiden geldiği izlenmiyor),
  bu yüzden gerçek "kalan" süre hesaplanamaz. Katalogdaki statik
  `raf_omru_gun` (kategori tipik raf ömrü) doğrudan kullanılıyor. Bu ölü
  stok tespitini bozmuyor çünkü `rules.py::olu_stok_degerlendir` asıl
  sinyali `son_hareket_gun_once`'tan alıyor (gerçek, ölçülen bir alan);
  `raf_omru_kalan_gun` yalnızca raf ömrü kritikse (≤30 gün) iskonto oranını
  artıran ikincil bir düzeltme.
- `rezerve_stok` — simülatörün olay döngüsü siparişi aynı gün stoktan
  düşüp sevk ediyor (bkz. `simulator/run.py`), ayrı bir "sipariş alındı ama
  henüz sevk edilmedi" kuyruğu modellenmiyor. Bu yüzden yapısal olarak her
  zaman 0 — `kullanilabilir_stok` pratikte `eldeki_stok`'a eşit. Lot bazlı
  rezervasyon eklemek gerçek bir B2B/B2C ayrımı gerektirir, mevcut
  simülatörün kapsamı dışında tutuldu.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from app.contracts import ABCSinifi, StockFeatures, XYZSinifi

KISA_PENCERE_GUN = 30
UZUN_PENCERE_GUN = 90

VARSAYILAN_ABC_SINIFI = ABCSinifi.C
VARSAYILAN_XYZ_SINIFI = XYZSinifi.Z
VARSAYILAN_HEDEF_SERVIS_SEVIYESI = 0.90
TEDARIKCI_ONAY_ESIGI = 70.0
"""Bu eşiğin üstü 'onaylı' sayılır — gerçek `tedarikci_skoru_hesapla()` (A2.5)
skoru mevcutsa o kullanılır (bkz. aşağıda `siniflandirma` dalı); yalnızca
`siniflandirma` verilmediğinde `guvenilirlik * 100` geri düşülür.

Eşik gerçek veriyle kalibre edildi (karar: Kişi A, sonuç kesinleşti):
sağlıklı (patolojisiz) 3 yıllık koşuda 60 tedarikçinin skoru 89,6-93,2
aralığında — hiçbiri 70'in altına düşmüyor. Tedarikçi gecikmesi patolojisi
enjekte edilince en kötü tedarikçiler 42-52'ye düşüyor, medyan ~76'ya
iniyor. Yani 70.0 "sağlıklı" ile "gerçekten kötü" arasında anlamlı bir
yerde duruyor — ama şu anki A3.1 eğitim verisi patolojisiz üretildiği için
`tedarikci_onayli=False` durumu training setinde HİÇ görülmüyor. Bu, kural
motorunun bir hatası değil, eğitim verisinin kapsamındaki bilinen bir sınır
— ölü stok tespitindeki demand-spike sınırlamasıyla aynı kategoride
(bkz. aciklama.md, A2.8)."""


def _talep_penceresi_istatistikleri(
    talep: pd.DataFrame, olcum_tarihi: dt.date, sku_ids: np.ndarray
) -> dict[str, pd.Series]:
    """Talep tablosundan 30/90 günlük kayan ortalama + std + veri günü + son
    hareket gününü, tüm katalog için tek seferde (vektörize) hesaplar."""
    talep_wide = (
        talep.pivot(index="tarih", columns="sku_id", values="talep_miktari")
        .reindex(columns=sku_ids)
        .sort_index()
    )
    olcum_ts = pd.Timestamp(olcum_tarihi)
    talep_upto = talep_wide.loc[:olcum_ts]
    if talep_upto.empty:
        raise ValueError(f"{olcum_tarihi} tarihinde/öncesinde hiç talep verisi yok.")

    kisa_ort = talep_upto.rolling(KISA_PENCERE_GUN, min_periods=1).mean().loc[olcum_ts]
    kisa_std = talep_upto.rolling(KISA_PENCERE_GUN, min_periods=1).std().loc[olcum_ts].fillna(0.0)
    uzun_ort = talep_upto.rolling(UZUN_PENCERE_GUN, min_periods=1).mean().loc[olcum_ts]
    uzun_std = talep_upto.rolling(UZUN_PENCERE_GUN, min_periods=1).std().loc[olcum_ts].fillna(0.0)

    veri_gun_sayisi = pd.Series(len(talep_upto), index=sku_ids)

    talep_matrisi = talep_upto.to_numpy()
    gun_index = np.arange(len(talep_upto))
    son_indeksler = np.full(talep_matrisi.shape[1], -1)
    for j in range(talep_matrisi.shape[1]):
        hareketli_gunler = gun_index[talep_matrisi[:, j] > 0]
        if len(hareketli_gunler) > 0:
            son_indeksler[j] = hareketli_gunler[-1]
    # Hiç hareket olmayan SKU için "son hareket" = veri geçmişinin tamamı kadar önce.
    son_hareket_gun_once = np.where(
        son_indeksler >= 0, (len(talep_upto) - 1) - son_indeksler, len(talep_upto)
    )

    return {
        "kisa_ort_gunluk_talep": kisa_ort,
        "kisa_talep_std": kisa_std,
        "ort_gunluk_talep": uzun_ort,
        "talep_std": uzun_std,
        "veri_gun_sayisi": veri_gun_sayisi,
        "son_hareket_gun_once": pd.Series(son_hareket_gun_once, index=sku_ids),
    }


def katalog_ozelliklerini_hesapla(
    olcum_tarihi: dt.date,
    talep: pd.DataFrame,
    envanter_gunluk: pd.DataFrame,
    sku_df: pd.DataFrame,
    tedarikci_df: pd.DataFrame,
    siniflandirma: pd.DataFrame | None = None,
) -> list[StockFeatures]:
    """Tüm katalog için `olcum_tarihi` anındaki `StockFeatures` listesini üretir.

    `siniflandirma` verilirse (index: sku_id, kolonlar: abc_sinifi, xyz_sinifi,
    hedef_servis_seviyesi, tedarikci_skoru) A2.4/A2.5'in gerçek çıktısı kullanılır;
    verilmezse modül başındaki dokümante edilmiş varsayılanlara düşülür.
    """
    sku_ids = sku_df["sku_id"].to_numpy()
    istatistik = _talep_penceresi_istatistikleri(talep, olcum_tarihi, sku_ids)

    envanter_bugun = (
        envanter_gunluk[envanter_gunluk["tarih"] == pd.Timestamp(olcum_tarihi)]
        .set_index("sku_id")
        .reindex(sku_ids)
    )
    if envanter_bugun["eldeki_stok"].isna().any():
        eksik = envanter_bugun[envanter_bugun["eldeki_stok"].isna()].index.tolist()
        raise ValueError(f"{olcum_tarihi} için envanter kaydı eksik: {eksik[:5]}...")

    sku_indeksli = sku_df.set_index("sku_id").reindex(sku_ids)
    tedarikci_indeksli = tedarikci_df.set_index("tedarikci_id")

    tum_ozellikler: list[StockFeatures] = []
    for sku_id in sku_ids:
        sku_satiri = sku_indeksli.loc[sku_id]
        tedarikci_id = sku_satiri["tedarikci_id"]
        tedarikci_satiri = tedarikci_indeksli.loc[tedarikci_id]

        if siniflandirma is not None and sku_id in siniflandirma.index:
            sinif_satiri = siniflandirma.loc[sku_id]
            abc_sinifi = sinif_satiri["abc_sinifi"]
            xyz_sinifi = sinif_satiri["xyz_sinifi"]
            hedef_servis_seviyesi = float(sinif_satiri["hedef_servis_seviyesi"])
            tedarikci_skoru = float(sinif_satiri["tedarikci_skoru"])
            # Tedarikçi hakkındaki kanıtın miktarı. `tedarikci_skoru_hesapla`
            # bu sayıyı zaten üretiyor; buraya kadar taşınmıyordu ve kural
            # motoru vekil bir ölçüye (talep geçmişi uzunluğu) mecburdu.
            siparis_sayisi = int(sinif_satiri.get("siparis_sayisi", 0) or 0)
        else:
            abc_sinifi = VARSAYILAN_ABC_SINIFI
            xyz_sinifi = VARSAYILAN_XYZ_SINIFI
            hedef_servis_seviyesi = VARSAYILAN_HEDEF_SERVIS_SEVIYESI
            tedarikci_skoru = float(tedarikci_satiri["guvenilirlik"]) * 100.0
            siparis_sayisi = 0  # bilinmiyor

        raf_omru = sku_satiri["raf_omru_gun"]

        tum_ozellikler.append(
            StockFeatures(
                sku_id=sku_id,
                sku_adi=sku_satiri["sku_adi"],
                kategori=sku_satiri["kategori"],
                eldeki_stok=round(float(envanter_bugun.loc[sku_id, "eldeki_stok"])),
                rezerve_stok=0,  # simülatör aynı gün sevkiyat yapar, rezervasyon kuyruğu yok
                yoldaki_stok=round(float(envanter_bugun.loc[sku_id, "yoldaki_stok"])),
                ort_gunluk_talep=float(istatistik["ort_gunluk_talep"][sku_id]),
                talep_std=float(istatistik["talep_std"][sku_id]),
                veri_gun_sayisi=int(istatistik["veri_gun_sayisi"][sku_id]),
                tedarik_suresi_gun=float(tedarikci_satiri["ort_tedarik_suresi_gun"]),
                tedarik_suresi_std=float(tedarikci_satiri["tedarik_suresi_std_gun"]),
                abc_sinifi=abc_sinifi,
                xyz_sinifi=xyz_sinifi,
                hedef_servis_seviyesi=hedef_servis_seviyesi,
                son_hareket_gun_once=int(istatistik["son_hareket_gun_once"][sku_id]),
                raf_omru_kalan_gun=None if pd.isna(raf_omru) else int(raf_omru),
                birim_maliyet_tl=float(sku_satiri["birim_maliyet_tl"]),
                satis_fiyati_tl=float(sku_satiri["satis_fiyati_tl"]),
                tedarikci_id=tedarikci_id,
                tedarikci_adi=tedarikci_satiri["tedarikci_adi"],
                tedarikci_skoru=tedarikci_skoru,
                tedarikci_zamaninda_teslim_orani=float(tedarikci_satiri["guvenilirlik"]),
                tedarikci_onayli=tedarikci_skoru >= TEDARIKCI_ONAY_ESIGI,
                tedarikci_siparis_sayisi=siparis_sayisi,
                moq=int(sku_satiri["moq"]),
                paket_adedi=int(sku_satiri["paket_adedi"]),
                olcum_tarihi=olcum_tarihi,
            )
        )

    return tum_ozellikler


def sku_ozelliklerini_hesapla(
    sku_id: str,
    olcum_tarihi: dt.date,
    talep: pd.DataFrame,
    envanter_gunluk: pd.DataFrame,
    sku_df: pd.DataFrame,
    tedarikci_df: pd.DataFrame,
    siniflandirma: pd.DataFrame | None = None,
) -> StockFeatures:
    """Tek bir SKU için `StockFeatures`. `katalog_ozelliklerini_hesapla`'nın
    filtrelenmiş girdiyle çağrılan ince bir sarmalayıcısıdır."""
    sonuc = katalog_ozelliklerini_hesapla(
        olcum_tarihi=olcum_tarihi,
        talep=talep[talep["sku_id"] == sku_id],
        envanter_gunluk=envanter_gunluk[envanter_gunluk["sku_id"] == sku_id],
        sku_df=sku_df[sku_df["sku_id"] == sku_id],
        tedarikci_df=tedarikci_df,
        siniflandirma=siniflandirma,
    )
    return sonuc[0]
