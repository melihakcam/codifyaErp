"""Ham veri → `UretimOzellikleri`.

Sahip: Kişi A · Faz 10 A10.2

Stoktaki `features.py` ile aynı iş: tabloları okuyup kural motorunun gördüğü
tek nesneyi kurmak. İki fark var.

**1. Tahmin burada üretilmiyor, çağrılıyor.** `app/forecast` talep serisini
alıp `TalepTahmini` döndürüyor; bu modül onu düzleştirip sözleşmeye koyuyor.
Tahmin mantığı buraya sızarsa iki yerde iki farklı tahmin olur ve hangisinin
ölçüldüğü belirsizleşir.

**2. Girdi tablosu üretim ana verisi.** Satın alınan kalemlerin bu tabloda
satırı yok; onlar için `UretimOzellikleri` **üretilmiyor**. "Üretim süresi
NULL" bir satır döndürmek, çağıran tarafın her yerde NULL kontrolü yapmasını
gerektirirdi ve bir yerde unutulurdu.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from app.contracts import ABCSinifi, UretimOzellikleri, XYZSinifi
from app.core.isletme_profili import UretimProfili, profil
from app.forecast.aralikli import croston

VARSAYILAN_ABC_SINIFI = ABCSinifi.C
VARSAYILAN_XYZ_SINIFI = XYZSinifi.Z
VARSAYILAN_HEDEF_SERVIS_SEVIYESI = 0.90


def talep_serisi_cikar(talep: pd.DataFrame, sku_id: str, olcum_tarihi: dt.date) -> list[float]:
    """SKU'nun ölçüm tarihine kadarki günlük talep serisi.

    ⚠️ Seri **ölçüm tarihinde bitiyor** ve bu bir sızıntı koruması: bir gün
    bile ileri almak, tahmine tahmin edeceği günü göstermek olur. Tahmin
    ölçümünde aynı tuzağın testi ayrıca yazıldı
    (`tests/test_forecast.py::test_olcum_egitim_penceresini_asmiyor`); burada
    da aynı disiplin geçerli.

    Satış olmayan günler seride **sıfır olarak** duruyor, atlanmıyor.
    Aralıklı talep modelinin tüm bilgisi o sıfırların nerede olduğunda.
    """
    kalem = talep[talep["sku_id"] == sku_id]
    kalem = kalem[kalem["tarih"] <= pd.Timestamp(olcum_tarihi)]
    if kalem.empty:
        return []
    seri = kalem.set_index("tarih")["talep_miktari"].sort_index()
    # Eksik günleri sıfırla doldur: simülatör her gün satır yazıyor ama
    # gerçek ERP hareket tablosunda satış olmayan günün satırı olmaz.
    tam = seri.reindex(pd.date_range(seri.index.min(), seri.index.max(), freq="D"), fill_value=0.0)
    return [float(d) for d in tam]


def kalem_ozelliklerini_hesapla(
    sku_id: str,
    olcum_tarihi: dt.date,
    talep: pd.DataFrame,
    envanter_gunluk: pd.DataFrame,
    sku_df: pd.DataFrame,
    uretim_df: pd.DataFrame,
    siniflandirma: pd.DataFrame | None = None,
    uretim_profili: UretimProfili | None = None,
    acik_emir_miktari: int = 0,
) -> UretimOzellikleri:
    """Tek bir üretilen kalem için `UretimOzellikleri`.

    `acik_emir_miktari` dışarıdan veriliyor: açık üretim emirleri kural
    motorunun değil, emir tablosunun bilgisi. Simülasyonda henüz emir
    tablosu yok (Adım 3'ün kapsamı karar üretmek, emri koşturmak değil), o
    yüzden varsayılan 0.

    ⚠️ 0 varsayımı **iyimser yönde değil, kötümser yönde** hata yapar:
    açık emir sayılmazsa sistem gereğinden fazla emir önerir. Gerçek
    kurulumda bu alan boş bırakılırsa fazla üretim olur; sessizce yanlış
    davranmasın diye burada yazılı.
    """
    p = uretim_profili or profil().uretim

    uretim_satiri = uretim_df[uretim_df["sku_id"] == sku_id]
    if uretim_satiri.empty:
        raise ValueError(
            f"{sku_id} üretim ana verisinde yok — satın alınan kalem için üretim kararı üretilemez."
        )
    u = uretim_satiri.iloc[0]

    sku_satiri = sku_df[sku_df["sku_id"] == sku_id]
    if sku_satiri.empty:
        raise ValueError(f"{sku_id} katalogda yok.")
    s = sku_satiri.iloc[0]

    envanter = envanter_gunluk[
        (envanter_gunluk["sku_id"] == sku_id)
        & (envanter_gunluk["tarih"] == pd.Timestamp(olcum_tarihi))
    ]
    if envanter.empty:
        raise ValueError(f"{sku_id} için {olcum_tarihi} envanter kaydı yok.")
    eldeki_stok = round(float(envanter.iloc[0]["eldeki_stok"]))

    gecmis = talep_serisi_cikar(talep, sku_id, olcum_tarihi)
    tahmin = croston(gecmis, sku_id, olcum_tarihi, p.planlama_ufku_gun)
    alt_band, ust_band = tahmin.toplam_bandi()

    if siniflandirma is not None and sku_id in siniflandirma.index:
        sinif = siniflandirma.loc[sku_id]
        abc_sinifi = sinif["abc_sinifi"]
        xyz_sinifi = sinif["xyz_sinifi"]
        hedef_servis = float(sinif["hedef_servis_seviyesi"])
    else:
        abc_sinifi = VARSAYILAN_ABC_SINIFI
        xyz_sinifi = VARSAYILAN_XYZ_SINIFI
        hedef_servis = VARSAYILAN_HEDEF_SERVIS_SEVIYESI

    return UretimOzellikleri(
        kalem_id=sku_id,
        kalem_adi=s["sku_adi"],
        kategori=s["kategori"],
        eldeki_stok=eldeki_stok,
        rezerve_stok=0,  # simülatör aynı gün sevk ediyor, rezervasyon kuyruğu yok
        acik_emir_miktari=acik_emir_miktari,
        tahmin_toplam=round(tahmin.toplam(), 2),
        tahmin_alt_band=round(alt_band, 2),
        tahmin_ust_band=round(ust_band, 2),
        tahmin_yontemi=tahmin.yontem,
        tahmin_ufuk_gun=tahmin.ufuk_gun,
        veri_gun_sayisi=len(gecmis),
        hat_id=u["hat_id"],
        hat_adi=u["hat_adi"],
        parti_buyuklugu=int(u["parti_buyuklugu"]),
        asgari_parti=int(u["asgari_parti"]),
        hazirlik_suresi_saat=float(u["hazirlik_suresi_saat"]),
        birim_islem_suresi_saat=float(u["birim_islem_suresi_saat"]),
        uretim_suresi_gun=float(u["uretim_suresi_gun"]),
        hat_gunluk_kapasite_saat=float(u["gunluk_kapasite_saat"]),
        abc_sinifi=abc_sinifi,
        xyz_sinifi=xyz_sinifi,
        hedef_servis_seviyesi=hedef_servis,
        birim_maliyet_tl=float(s["birim_maliyet_tl"]),
        satis_fiyati_tl=float(s["satis_fiyati_tl"]),
        olcum_tarihi=olcum_tarihi,
    )


__all__ = ["kalem_ozelliklerini_hesapla", "talep_serisi_cikar"]
