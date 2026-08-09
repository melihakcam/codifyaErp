"""Emniyet stoğu, ROP, EOQ+MOQ, ABC/XYZ, ölü stok, tedarikçi skoru. Saf fonksiyonlar.

Sahip: Kişi A · Faz 2 A2.2-A2.5

Bu modüldeki her fonksiyon saf ve deterministiktir: aynı girdi her zaman aynı
çıktıyı verir, yan etkisi yoktur. `decide.py` (A2.6) bu fonksiyonları
`StockFeatures` üzerinde çağırıp `FiredRule` + `DecisionCandidate` üretir.
"""

from __future__ import annotations

import math

import pandas as pd
from scipy.stats import norm

from app.contracts import ABCSinifi, StockFeatures, XYZSinifi
from app.domain.siniflandirma import (
    ABC_KESIM_A,
    ABC_KESIM_B,
    XYZ_KESIM_X,
    XYZ_KESIM_Y,
    abc_sinif_ata,
    xyz_sinif_ata,
)

# ---------------------------------------------------------------------------
# A2.2 — Emniyet stoğu + ROP
# ---------------------------------------------------------------------------


def emniyet_stogu_hesapla(
    hedef_servis_seviyesi: float,
    tedarik_suresi_gun: float,
    talep_std: float,
    ort_gunluk_talep: float,
    tedarik_suresi_std: float,
) -> float:
    """Emniyet stoğu = Z(servis_seviyesi) x sqrt(tedarik_süresi x talep_std^2
    + ort_talep^2 x tedarik_süresi_std^2).

    Karekökün içindeki ikinci terim çoğu kaynakta atlanır — yalnızca talep
    belirsizliğini hesaba katarlar. Ama tedarikçi bazen 12 gün bazen 17 günde
    getiriyorsa bu da emniyet stoğu gerektirir; ikinci terimi atlayan bir
    sistem simülasyonda sistematik olarak stok tükenmesi yaşar (bkz.
    `simulator/run.py`'deki kasıtlı vasat taban politika — o da bu terimi
    hesaba katmıyor, tam olarak bu yüzden kötü performans gösteriyor).
    """
    z = norm.ppf(hedef_servis_seviyesi)
    varyans = tedarik_suresi_gun * talep_std**2 + ort_gunluk_talep**2 * tedarik_suresi_std**2
    return float(z * math.sqrt(max(varyans, 0.0)))


def yeniden_siparis_noktasi_hesapla(
    ort_gunluk_talep: float, tedarik_suresi_gun: float, emniyet_stogu: float
) -> float:
    """ROP = ort_günlük_talep x tedarik_süresi + emniyet_stoğu."""
    return ort_gunluk_talep * tedarik_suresi_gun + emniyet_stogu


def rop_ve_emniyet_stogu(ozellik: StockFeatures) -> tuple[float, float]:
    """`StockFeatures`'tan doğrudan (rop, emniyet_stogu) çifti üretir — `decide.py`'nin
    kullanacağı üst seviye giriş noktası."""
    emniyet = emniyet_stogu_hesapla(
        hedef_servis_seviyesi=ozellik.hedef_servis_seviyesi,
        tedarik_suresi_gun=ozellik.tedarik_suresi_gun,
        talep_std=ozellik.talep_std,
        ort_gunluk_talep=ozellik.ort_gunluk_talep,
        tedarik_suresi_std=ozellik.tedarik_suresi_std,
    )
    rop = yeniden_siparis_noktasi_hesapla(
        ozellik.ort_gunluk_talep, ozellik.tedarik_suresi_gun, emniyet
    )
    return rop, emniyet


# ---------------------------------------------------------------------------
# A2.3 — Sipariş miktarı: EOQ + MOQ/paket yuvarlaması
# ---------------------------------------------------------------------------

VARSAYILAN_SIPARIS_MALIYETI_TL = 150.0
"""Bir sipariş açmanın sabit maliyeti (nakliye/idari) — simülatörde modellenmiyor,
iş varsayımı olarak sabitlenir. Gerçek ERP entegrasyonunda konfigüre edilecek."""

VARSAYILAN_YILLIK_ELDE_TUTMA_ORANI = 0.22
"""Yıllık elde tutma maliyeti, birim maliyetin bu oranı kadar (depolama + sermaye
maliyeti + bozulma riski). Türkiye KOBİ'lerinde tipik aralık %18-%28."""


def ekonomik_siparis_miktari(
    yillik_talep_adet: float,
    birim_maliyet_tl: float,
    siparis_maliyeti_tl: float = VARSAYILAN_SIPARIS_MALIYETI_TL,
    yillik_elde_tutma_orani: float = VARSAYILAN_YILLIK_ELDE_TUTMA_ORANI,
) -> float:
    """EOQ = sqrt(2 x D x S / H), D=yıllık talep, S=sipariş maliyeti, H=elde tutma maliyeti."""
    elde_tutma_maliyeti = birim_maliyet_tl * yillik_elde_tutma_orani
    if elde_tutma_maliyeti <= 0 or yillik_talep_adet <= 0:
        return 0.0
    return math.sqrt(2 * yillik_talep_adet * siparis_maliyeti_tl / elde_tutma_maliyeti)


def siparis_miktarini_yuvarla(miktar: float, moq: int, paket_adedi: int) -> int:
    """Çıktı her zaman MOQ'dan büyük/eşit **ve** paket adedinin tam katı olur.

    Gerçek dünyada 1.187 adet tuğla sipariş edilmez — 1.200 edilir (paket
    100'lük). Bu yuvarlamayı atlayan bir sistem kağıt üzerinde doğru, sahada
    kullanılamaz çıktı üretir.
    """
    if paket_adedi <= 0:
        raise ValueError("paket_adedi > 0 olmalı")
    paket_kati = max(1, math.ceil(miktar / paket_adedi))
    yuvarlanmis = paket_kati * paket_adedi
    if yuvarlanmis < moq:
        yuvarlanmis = math.ceil(moq / paket_adedi) * paket_adedi
    return int(yuvarlanmis)


def siparis_miktari_hesapla(ozellik: StockFeatures) -> int:
    """`StockFeatures`'tan doğrudan yuvarlanmış sipariş miktarı üretir."""
    yillik_talep = ozellik.ort_gunluk_talep * 365
    eoq = ekonomik_siparis_miktari(yillik_talep, ozellik.birim_maliyet_tl)
    return siparis_miktarini_yuvarla(eoq, ozellik.moq, ozellik.paket_adedi)


# ---------------------------------------------------------------------------
# A2.4 — ABC/XYZ sınıflandırma + hedef servis seviyesi matrisi
# ---------------------------------------------------------------------------

# ⚠️ Kesimler ve sınıf atama fonksiyonları Faz 6'da `app/domain/siniflandirma.py`'ye
# TAŞINDI — finans alanı da aynı soruyu soruyor ("bu kalem ciroya ne katıyor,
# ne kadar düzenli?") ve iki eşdüzey alandan birinin diğerine bağlanması
# yanlış olurdu. Buradan yeniden ihraç ediliyorlar: mevcut import'lar ve
# testler bozulmasın diye.

HEDEF_SERVIS_SEVIYESI_MATRISI: dict[tuple[ABCSinifi, XYZSinifi], float] = {
    (ABCSinifi.A, XYZSinifi.X): 0.99,
    (ABCSinifi.A, XYZSinifi.Y): 0.97,
    (ABCSinifi.A, XYZSinifi.Z): 0.95,
    (ABCSinifi.B, XYZSinifi.X): 0.97,
    (ABCSinifi.B, XYZSinifi.Y): 0.95,
    (ABCSinifi.B, XYZSinifi.Z): 0.90,
    (ABCSinifi.C, XYZSinifi.X): 0.95,
    (ABCSinifi.C, XYZSinifi.Y): 0.90,
    (ABCSinifi.C, XYZSinifi.Z): 0.85,
}
"""Mantık: cirosu yüksek + talebi düzenli (AX) ürünün stoğu tükenmesin — pahalıya
gelir, kolay tahmin edilir. Cirosu düşük + talebi kaotik (CZ) üründe yüksek
servis seviyesi tutmak boşa para bağlamaktır."""


def abc_xyz_siniflandir(ozellik_listesi: list[StockFeatures]) -> pd.DataFrame:
    """`StockFeatures` listesinden ABC/XYZ sınıfı + hedef servis seviyesi üretir.

    ABC, **gözlemlenen** yıllık ciroya göre hesaplanır (`ort_gunluk_talep x
    satis_fiyati_tl x 365`) — katalogdaki sentetik `yillik_ciro_payi` değil,
    çünkü gerçek bir ERP'de yalnızca gözlemlenen satış bilinir. XYZ, talep
    varyasyon katsayısına (`talep_std / ort_gunluk_talep`) göre hesaplanır.

    Dönen DataFrame index'i `sku_id`, kolonları `abc_sinifi`, `xyz_sinifi`,
    `hedef_servis_seviyesi`, `yillik_ciro_tl`, `varyasyon_katsayisi`.
    """
    df = pd.DataFrame(
        {
            "sku_id": [o.sku_id for o in ozellik_listesi],
            "yillik_ciro_tl": [
                o.ort_gunluk_talep * o.satis_fiyati_tl * 365 for o in ozellik_listesi
            ],
            "varyasyon_katsayisi": [o.talep_varyasyon_katsayisi for o in ozellik_listesi],
        }
    ).set_index("sku_id")

    toplam_ciro = df["yillik_ciro_tl"].sum()
    df = df.sort_values("yillik_ciro_tl", ascending=False)
    if toplam_ciro > 0:
        df["kumulatif_ciro_orani"] = df["yillik_ciro_tl"].cumsum() / toplam_ciro
    else:
        df["kumulatif_ciro_orani"] = 1.0

    df["abc_sinifi"] = df["kumulatif_ciro_orani"].apply(abc_sinif_ata)
    df["xyz_sinifi"] = df["varyasyon_katsayisi"].apply(xyz_sinif_ata)
    df["hedef_servis_seviyesi"] = [
        HEDEF_SERVIS_SEVIYESI_MATRISI[(satir.abc_sinifi, satir.xyz_sinifi)]
        for satir in df.itertuples()
    ]

    return df.drop(columns="kumulatif_ciro_orani")


# ---------------------------------------------------------------------------
# A2.5 — Ölü stok + tedarikçi skoru
# ---------------------------------------------------------------------------

OLU_STOK_MUTLAK_ESIK_GUN = 90
"""Hiçbir SKU bunun altında 'ölü' sayılmaz — çok yavaş hareket eden ama sağlıklı
ürünler için bile makul bir sessizlik payı tanır."""

OLU_STOK_GORECELI_CARPAN = 6.0
"""Asıl eşik: ürünün kendi tipik satış aralığının (`1/ort_gunluk_talep`) kaç katı
sessizlik 'ölü' sayılır. Sabit bir gün eşiği (ör. 60) günde 0.05 birim satan bir
C-sınıfı ürünü de yakalar — o ürün için 60 gün sessizlik zaten normaldir.
Göreceli eşik, aralıklı talebi olan ama sağlıklı ürünleri yanlışlıkla 'ölü'
etiketlemekten kaçınır."""


def _olu_stok_esigi(ort_gunluk_talep: float) -> float:
    if ort_gunluk_talep <= 0:
        return OLU_STOK_MUTLAK_ESIK_GUN
    tipik_satis_araligi_gun = 1.0 / ort_gunluk_talep
    return max(OLU_STOK_MUTLAK_ESIK_GUN, OLU_STOK_GORECELI_CARPAN * tipik_satis_araligi_gun)


def olu_stok_degerlendir(ozellik: StockFeatures) -> dict:
    """N gündür hareketsiz + kalan raf ömrü + bağlı sermaye -> tasfiye/iskonto önerisi.

    Eşik, ürünün kendi tipik satış hızına göre normalize edilir (bkz.
    `_olu_stok_esigi`) — sabit bir gün sayısı, doğası gereği aralıklı satan
    ürünleri yanlışlıkla "ölü" damgalar. Ne kadar uzun süredir hareketsizse
    iskonto o kadar agresifleşir; raf ömrü azalıyorsa (kritik eşiğin altındaysa)
    iskonto ayrıca artırılır — bozulacak bir ürünü elde tutmanın maliyeti,
    satamamanın maliyetinden daha kötüdür.
    """
    esik_gun = _olu_stok_esigi(ozellik.ort_gunluk_talep)
    olu_mu = ozellik.eldeki_stok > 0 and ozellik.son_hareket_gun_once >= esik_gun
    bagli_sermaye_tl = ozellik.eldeki_stok * ozellik.birim_maliyet_tl

    onerilen_iskonto_orani = 0.0
    if olu_mu:
        if ozellik.son_hareket_gun_once >= esik_gun * 3:
            onerilen_iskonto_orani = 0.50
        elif ozellik.son_hareket_gun_once >= esik_gun * 2:
            onerilen_iskonto_orani = 0.30
        else:
            onerilen_iskonto_orani = 0.15

        raf_kritik_gun = 30
        if (
            ozellik.raf_omru_kalan_gun is not None
            and ozellik.raf_omru_kalan_gun <= raf_kritik_gun
        ):
            onerilen_iskonto_orani = max(onerilen_iskonto_orani, 0.60)

    return {
        "sku_id": ozellik.sku_id,
        "olu_stok_mu": olu_mu,
        "son_hareket_gun_once": ozellik.son_hareket_gun_once,
        "kullanilan_esik_gun": esik_gun,
        "bagli_sermaye_tl": bagli_sermaye_tl,
        "onerilen_iskonto_orani": onerilen_iskonto_orani,
    }


TEDARIKCI_SKOR_AGIRLIK_ZAMANINDA = 0.6
TEDARIKCI_SKOR_AGIRLIK_TUTARLILIK = 0.4


def _tedarikci_id_indeksli(tedarikci_df: pd.DataFrame) -> pd.DataFrame:
    """`tedarikci_df`'yi `tedarikci_id` index'iyle döndürür — gelen DataFrame ister
    ham simülatör çıktısı (tedarikci_id kolon), ister zaten indekslenmiş olsun."""
    if tedarikci_df.index.name == "tedarikci_id":
        return tedarikci_df
    return tedarikci_df.set_index("tedarikci_id")


def tedarikci_performans_ozeti(
    siparisler: pd.DataFrame, tedarikci_df: pd.DataFrame
) -> pd.DataFrame:
    """Sipariş geçmişinden tedarikçi başına **gerçekleşen** ortalama/std tedarik
    süresini çıkarır. Simülatörde 'beklenen' ile 'gerçekleşen' ayrımı yoktur —
    `siparisler.beklenen_tedarik_suresi_gun` o siparişte fiilen uygulanan
    süredir (rastgele gecikme + varsa patoloji dahil), bu yüzden doğrudan
    gerçekleşen performans olarak kullanılabilir."""
    tedarikci_df = _tedarikci_id_indeksli(tedarikci_df)
    if siparisler.empty:
        ozet = pd.DataFrame(
            index=tedarikci_df.index,
            columns=[
                "gerceklesen_ort_tedarik_suresi_gun",
                "gerceklesen_tedarik_suresi_std_gun",
                "siparis_sayisi",
            ],
        ).fillna(0.0)
    else:
        ozet = siparisler.groupby("tedarikci_id")["beklenen_tedarik_suresi_gun"].agg(
            gerceklesen_ort_tedarik_suresi_gun="mean",
            gerceklesen_tedarik_suresi_std_gun="std",
            siparis_sayisi="count",
        )
        ozet = ozet.reindex(tedarikci_df.index)
        ozet["gerceklesen_tedarik_suresi_std_gun"] = ozet[
            "gerceklesen_tedarik_suresi_std_gun"
        ].fillna(0.0)
        ozet["siparis_sayisi"] = ozet["siparis_sayisi"].fillna(0)
    return ozet


def tedarikci_skoru_hesapla(siparisler: pd.DataFrame, tedarikci_df: pd.DataFrame) -> pd.DataFrame:
    """0-100 tedarikçi skoru: gerçekleşen teslim performansının ağırlıklı toplamı.

    İki sinyal kullanılır (fiyat sapması / iade-red oranı simülatörde
    modellenmediği için dahil edilmiyor — gerçek ERP entegrasyonunda eklenir):
      - **zamanında teslim**: gerçekleşen ort. tedarik süresi, katalogdaki
        beklenen süreye ne kadar yakın (sapma arttıkça puan düşer; erken teslim
        cezalandırılmaz)
      - **tutarlılık**: gerçekleşen tedarik süresinin kendi ortalamasına oranla
        değişkenliği (düşük varyans = yüksek puan)
    """
    tedarikci_df = _tedarikci_id_indeksli(tedarikci_df)
    ozet = tedarikci_performans_ozeti(siparisler, tedarikci_df)
    beklenen_sure = tedarikci_df["ort_tedarik_suresi_gun"]

    sapma_orani = (ozet["gerceklesen_ort_tedarik_suresi_gun"] / beklenen_sure).fillna(1.0)
    zamaninda_puan = (1.0 / sapma_orani.clip(lower=1.0)).clip(lower=0.0, upper=1.0)

    tutarlilik_orani = (
        ozet["gerceklesen_tedarik_suresi_std_gun"] / ozet["gerceklesen_ort_tedarik_suresi_gun"]
    ).fillna(0.0)
    tutarlilik_puan = (1.0 - tutarlilik_orani.clip(lower=0.0, upper=1.0)).clip(lower=0.0)

    skor = (
        TEDARIKCI_SKOR_AGIRLIK_ZAMANINDA * zamaninda_puan
        + TEDARIKCI_SKOR_AGIRLIK_TUTARLILIK * tutarlilik_puan
    ) * 100.0

    return pd.DataFrame(
        {
            "tedarikci_skoru": skor,
            "gerceklesen_ort_tedarik_suresi_gun": ozet["gerceklesen_ort_tedarik_suresi_gun"],
            "siparis_sayisi": ozet["siparis_sayisi"],
        },
        index=tedarikci_df.index,
    )


# ⚠️ Faz 6'da ABC/XYZ çekirdeği `app/domain/siniflandirma.py`'ye taşındı
# (finans da aynı sınıflandırmayı kullanıyor, iki alan birbirine bağlanmasın
# diye). Aşağıdakiler oradan geliyor ve buradan yeniden ihraç ediliyor —
# `from app.domain.stock.rules import abc_sinif_ata` yazan mevcut kod ve
# testler bozulmasın diye.
__all__ = [
    "ABC_KESIM_A",
    "ABC_KESIM_B",
    "HEDEF_SERVIS_SEVIYESI_MATRISI",
    "OLU_STOK_GORECELI_CARPAN",
    "OLU_STOK_MUTLAK_ESIK_GUN",
    "VARSAYILAN_SIPARIS_MALIYETI_TL",
    "VARSAYILAN_YILLIK_ELDE_TUTMA_ORANI",
    "XYZ_KESIM_X",
    "XYZ_KESIM_Y",
    "abc_sinif_ata",
    "abc_xyz_siniflandir",
    "ekonomik_siparis_miktari",
    "emniyet_stogu_hesapla",
    "olu_stok_degerlendir",
    "rop_ve_emniyet_stogu",
    "siparis_miktari_hesapla",
    "siparis_miktarini_yuvarla",
    "tedarikci_performans_ozeti",
    "tedarikci_skoru_hesapla",
    "xyz_sinif_ata",
    "yeniden_siparis_noktasi_hesapla",
]
