"""Fatura + tahsilat geçmişinden `FinansOzellikleri` — Faz 6.

`app/domain/stock/features.py::katalog_ozelliklerini_hesapla`'nın karşılığı:
ham hareket geçmişinden, belirli bir **ölçüm tarihindeki** karar girdilerini
üretir.

## ⚠️ Geleceği görmeme kuralı

Stok tarafında bu kural `talep_upto = talep_wide.loc[:olcum_ts]` satırıyla
sağlanıyordu. Burada iki yerde birden geçerli:

1. **Açık alacak**: bir fatura, ölçüm tarihinde ödenmemişse VEYA ödemesi o
   tarihten sonraysa açıktır. İkinci koşul kritik — "yarın ödenecek"
   bilgisini bugün kullanmak geriye dönük testi geçersiz kılar.
2. **Ödeme profili**: ortalama gecikme ve sapma yalnızca ölçüm tarihinden
   **önce tahsil edilmiş** faturalardan hesaplanır.

Bu kural olmasa sistem her müşteriyi mükemmel tanır ve sonuçlar gerçekte
ulaşılamayacak kadar iyi çıkar.

## Simülatörde olmayan iki alan

`kredi_limiti_tl` ve `musteri_kredi_onayli` ERP'de tanımlı ticari
parametrelerdir; simülatör onları üretmiyor. Burada gözlemlenen ciro ve
tahsilat geçmişinden **türetiliyorlar** — gerçek veride ERP'den okunacak,
o yüzden türetme tek bir yerde ve açıkça işaretli.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from app.contracts import FinansOzellikleri
from app.domain.finance.rules import HEDEF_TAHSILAT_ORANI_MATRISI
from app.domain.siniflandirma import abc_xyz_hesapla, matris_degeri

# Kredi limiti, gözlemlenen aylık cironun bu katı olarak türetilir.
# ⚠️ Gerçek veride bu alan ERP'den okunur; burada yalnızca simülasyon için.
LIMIT_AYLIK_CIRO_CARPANI = 2.0

# Bu tahsilat oranının altındaki müşteri "kredisi onaysız" sayılır —
# oto-uygulamayı engeller (bkz. `FinansOzellikleri.oto_uygulama_engeli`).
KREDI_ONAY_TAHSILAT_ESIGI = 0.60

# Ödeme profili için asgari gözlem. Altındaysa sapma güvenilmez ve katalog
# ortalaması kullanılır — `csv_erp.py`'deki `ASGARI_SIPARIS_SAYISI` ile aynı
# gerekçe: tek gözlemden sapma 0 çıkar, o da riski yok saymak olur.
ASGARI_ODEME_SAYISI = 3


def _odeme_profili(
    odenmis: pd.DataFrame, musteri_ids: np.ndarray
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Tahsil edilmiş faturalardan (ortalama gecikme, sapma, son ödeme)."""
    grup = odenmis.groupby("musteri_id")["gecikme_gun"]
    ort = grup.mean().reindex(musteri_ids)
    std = grup.std().reindex(musteri_ids)
    sayi = grup.count().reindex(musteri_ids).fillna(0)

    katalog_ort = float(odenmis["gecikme_gun"].mean()) if len(odenmis) else 0.0
    katalog_std = float(odenmis["gecikme_gun"].std()) if len(odenmis) > 1 else 0.0

    # Az gözlemli müşteride kendi sapması güvenilmez.
    std = std.where(sayi >= ASGARI_ODEME_SAYISI, katalog_std)
    return (
        ort.fillna(katalog_ort).clip(lower=0.0),
        std.fillna(katalog_std).clip(lower=0.0),
        sayi,
    )


def musteri_ozelliklerini_hesapla(
    faturalar: pd.DataFrame,
    musteri_df: pd.DataFrame,
    olcum_tarihi: dt.date,
) -> list[FinansOzellikleri]:
    """Tüm müşteriler için `olcum_tarihi` anındaki `FinansOzellikleri` listesi.

    `faturalar` `simulator/tahsilat.py::tahsilat_uret` çıktısı olmalı —
    yani `musteri_id`, `gercek_odeme_tarihi`, `gecikme_gun` kolonlarını
    taşımalı.

    ⚠️ Hiç faturası olmayan müşteri listeye **girmez**: alacağı olmayan biri
    için "tahsilat kararı" üretmek anlamsız. Stok tarafında hiç hareketi
    olmayan SKU'nun elenmesiyle aynı gerekçe.
    """
    ts = pd.Timestamp(olcum_tarihi)
    f = faturalar.copy()
    f["tarih"] = pd.to_datetime(f["tarih"])
    f["odeme_tarihi"] = pd.to_datetime(f["odeme_tarihi"])
    f["gercek_odeme_tarihi"] = pd.to_datetime(f["gercek_odeme_tarihi"])

    kesilmis = f[f["tarih"] <= ts]
    if kesilmis.empty:
        return []

    odendi_ve_gecmis = kesilmis["gercek_odeme_tarihi"].notna() & (
        kesilmis["gercek_odeme_tarihi"] <= ts
    )
    odenmis = kesilmis[odendi_ve_gecmis]
    acik = kesilmis[
        kesilmis["gercek_odeme_tarihi"].isna() | (kesilmis["gercek_odeme_tarihi"] > ts)
    ].copy()
    acik["gecikme_bugun"] = (ts - acik["odeme_tarihi"]).dt.days

    ilgili = musteri_df[musteri_df["musteri_id"].isin(set(kesilmis["musteri_id"]))]
    musteri_ids = ilgili["musteri_id"].to_numpy()
    if len(musteri_ids) == 0:
        return []

    ort_gecikme, std_gecikme, odeme_sayisi = _odeme_profili(odenmis, musteri_ids)

    toplam_alacak = acik.groupby("musteri_id")["tutar_tl"].sum().reindex(musteri_ids).fillna(0.0)
    gecikmis = acik[acik["gecikme_bugun"] > 0]
    vadesi_gecen = gecikmis.groupby("musteri_id")["tutar_tl"].sum().reindex(musteri_ids).fillna(0.0)
    en_eski = (
        gecikmis.groupby("musteri_id")["gecikme_bugun"].max().reindex(musteri_ids).fillna(0)
    )

    faturalanan = kesilmis.groupby("musteri_id")["tutar_tl"].sum().reindex(musteri_ids).fillna(0.0)

    # ⚠️ Tahsilat oranının paydası **vadesi gelmiş** faturalar — kesilmiş
    # faturalar değil. Faz 7'de para metriği bunu ortaya çıkardı: payda tüm
    # kesilmiş faturalar iken, 30 günlük geçmişi olan bir müşterinin
    # faturalarının hiçbirinin vadesi dolmamış oluyor, oran 0,00 çıkıyor ve
    # müşteri "hiç ödemeyen" gibi görünüyordu. Ölçülen sonuç: simülasyonun
    # 30. gününde 150 müşterinin 102'sinin risk skoru eşiğin altına düşüyor
    # ve hepsine kredi limiti düşürme kararı üretiliyordu — hiçbiri geç
    # kalmamışken.
    #
    # Doğru soru "ne kadarını ödedi" değil, **"ödemesi gereken ne kadarını
    # ödedi"**. Vadesi gelmemiş alacak bir tahsilat başarısızlığı değil,
    # normal ticari akış.
    vadesi_gelmis = kesilmis[kesilmis["odeme_tarihi"] <= ts]
    vadesi_gelmis_tutar = (
        vadesi_gelmis.groupby("musteri_id")["tutar_tl"].sum().reindex(musteri_ids).fillna(0.0)
    )
    vadesi_gelmis_tahsil = (
        vadesi_gelmis[vadesi_gelmis["gercek_odeme_tarihi"].notna()
                      & (vadesi_gelmis["gercek_odeme_tarihi"] <= ts)]
        .groupby("musteri_id")["tutar_tl"]
        .sum()
        .reindex(musteri_ids)
        .fillna(0.0)
    )
    # Hiç vadesi gelmemiş müşteride oran tanımsız. 0 yazmak "hiç ödemedi"
    # demek olurdu (yukarıdaki kusurun ta kendisi); 1 yazmak kanıtsız
    # güvenmek. Portföy ortalamasına düşülüyor — `_odeme_profili`'nin az
    # gözlemli müşteride katalog sapmasına düşmesiyle aynı gerekçe.
    portfoy_orani = (
        float(vadesi_gelmis_tahsil.sum() / vadesi_gelmis_tutar.sum())
        if vadesi_gelmis_tutar.sum() > 0
        else 1.0
    )
    tahsilat_orani = (
        (vadesi_gelmis_tahsil / vadesi_gelmis_tutar.replace(0.0, np.nan))
        .fillna(portfoy_orani)
        .clip(0.0, 1.0)
    )

    son_odeme = odenmis.groupby("musteri_id")["gercek_odeme_tarihi"].max().reindex(musteri_ids)
    son_odeme_gun_once = (ts - son_odeme).dt.days

    ilk_fatura = kesilmis.groupby("musteri_id")["tarih"].min().reindex(musteri_ids)
    veri_gun = (ts - ilk_fatura).dt.days.fillna(0).clip(lower=0)

    # Hiç ödeme yapmamış müşteride "son ödeme" = veri geçmişinin tamamı kadar
    # önce. `son_hareket_gun_once`'ın stok tarafındaki davranışıyla aynı.
    son_odeme_gun_once = son_odeme_gun_once.fillna(veri_gun)

    # ABC/XYZ: büyüklük = faturalanan ciro, oynaklık = ödeme gecikmesi σ/μ.
    varyasyon = (std_gecikme / ort_gecikme.replace(0.0, np.nan)).fillna(0.0)
    sinif = abc_xyz_hesapla(
        list(musteri_ids),
        faturalanan.to_numpy(),
        varyasyon.to_numpy(),
        kimlik_adi="musteri_id",
        deger_adi="faturalanan_tl",
    )

    ay_sayisi = (veri_gun / 30.0).clip(lower=1.0)
    kredi_limiti = (faturalanan / ay_sayisi) * LIMIT_AYLIK_CIRO_CARPANI

    ilgili_idx = ilgili.set_index("musteri_id")
    ozellikler: list[FinansOzellikleri] = []
    for mid in musteri_ids:
        satir = sinif.loc[mid]
        ozellikler.append(
            FinansOzellikleri(
                musteri_id=str(mid),
                musteri_adi=str(ilgili_idx.loc[mid, "musteri_adi"]),
                segment=str(ilgili_idx.loc[mid, "segment"]),
                toplam_alacak_tl=round(float(toplam_alacak[mid]), 2),
                vadesi_gecen_tl=round(float(vadesi_gecen[mid]), 2),
                en_eski_gecikme_gun=int(en_eski[mid]),
                ort_odeme_gecikmesi_gun=round(float(ort_gecikme[mid]), 2),
                odeme_gecikmesi_std=round(float(std_gecikme[mid]), 2),
                veri_gun_sayisi=int(veri_gun[mid]),
                kredi_limiti_tl=round(float(kredi_limiti[mid]), 2),
                abc_sinifi=satir.abc_sinifi,
                xyz_sinifi=satir.xyz_sinifi,
                hedef_tahsilat_orani=matris_degeri(
                    HEDEF_TAHSILAT_ORANI_MATRISI, satir.abc_sinifi, satir.xyz_sinifi
                ),
                son_odeme_gun_once=int(son_odeme_gun_once[mid]),
                tahsilat_orani=round(float(tahsilat_orani[mid]), 4),
                musteri_kredi_onayli=bool(
                    tahsilat_orani[mid] >= KREDI_ONAY_TAHSILAT_ESIGI
                    or odeme_sayisi[mid] < ASGARI_ODEME_SAYISI
                ),
                olcum_tarihi=olcum_tarihi,
            )
        )

    return ozellikler


__all__ = [
    "ASGARI_ODEME_SAYISI",
    "KREDI_ONAY_TAHSILAT_ESIGI",
    "LIMIT_AYLIK_CIRO_CARPANI",
    "musteri_ozelliklerini_hesapla",
]
