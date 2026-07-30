"""SKU başına günlük talep süreci: trend x sezon x haftalık desen x promo x gürültü.

Sahip: Kişi A · Faz 1 A1.2

Projenin en belirleyici parçası — kural motorunun emniyet stoğu hesabı burada
üretilen varyansı doğru yakalayabilirse anlamlıdır. İki tasarım kararı özellikle
kritik:

1. **Poisson yeterli değil.** Poisson'da varyans = ortalama; gerçek talep aşırı
   yayılımlıdır (overdispersed). Hızlı hareket eden ürünler için negatif binom
   kullanılır (`_hizli_hareket_talep_uret`) — varyans ortalamadan büyük tutulur.
2. **Aralıklı talep, ortalamayla modellenemez.** Yavaş hareket eden ürünler çoğu
   gün 0 satar, arada bir toplu miktar satar. Bernoulli(gün) × miktar modeli
   kullanılır (`_aralikli_talep_uret`) — sürekli küçük bir ortalama yerine.

Ortalama günlük talep formülü:

    talep = temel_hiz x trend x yillik_sezon x haftalik_desen x bayram_etkisi x promo

`temel_hiz`, katalogdaki `yillik_ciro_payi` ve şirketin hedef yıllık cirosundan
türetilir (`CompanyProfile.toplam_yillik_hedef_ciro_tl`) — Pareto dağılımlı ciro
payı böylece gerçek satış hacmine yansır.
"""

from __future__ import annotations

import datetime as dt
import math

import numpy as np
import pandas as pd

from simulator.company import CompanyProfile, KategoriProfili

GUNLUK_HIZLI_HAREKET_ESIGI = 1.0
"""Ortalama günlük talep bu değerin altındaysa 'aralıklı talep' modeli kullanılır."""

ASIRI_YAYILMA_ORANI = 2.2
"""Negatif binom varyans/ortalama oranı (phi). phi=1 Poisson'a denk gelir; phi>1
gerçek talebin aşırı yayılımını (overdispersion) modeller."""

ARALIKLI_TALEP_POZITIF_GUN_MIKTARI = 6.0
"""Aralıklı talepli bir SKU'nun talebin sıfırdan farklı olduğu bir gündeki
beklenen miktarı (Poisson ortalaması). Bernoulli olasılığı bu sabite göre
`ortalama_talep / bu_sabit` olarak çözülür."""

# Yaklaşık dini bayram başlangıç tarihleri (± birkaç gün) — hicri takvim yıl
# içinde kaydığından hesaplama yerine kısa bir arama tablosu kullanılır.
# Simülasyon amaçlı yeterli hassasiyette; kaynak: yaygın bilinen resmi tatil takvimleri.
_DINI_BAYRAM_BASLANGICLARI: dict[int, tuple[dt.date, dt.date]] = {
    2022: (dt.date(2022, 5, 2), dt.date(2022, 7, 9)),
    2023: (dt.date(2023, 4, 21), dt.date(2023, 6, 28)),
    2024: (dt.date(2024, 4, 10), dt.date(2024, 6, 16)),
    2025: (dt.date(2025, 3, 30), dt.date(2025, 6, 6)),
    2026: (dt.date(2026, 3, 20), dt.date(2026, 5, 27)),
    2027: (dt.date(2027, 3, 9), dt.date(2027, 5, 16)),
}
_BAYRAM_SURESI_GUN = 4
_BAYRAM_ONCESI_ETKI_GUN = 3
_BAYRAM_ONCESI_ETKI_CARPANI = 1.20
_BAYRAM_TATIL_ETKI_CARPANI = 0.35


def temel_gunluk_hiz(
    yillik_ciro_payi: float, satis_fiyati_tl: float, profile: CompanyProfile
) -> float:
    """SKU'nun ortalama günlük satış adedi (birim).

    Katalogdaki ciro payı, şirketin hedef yıllık cirosuna ölçeklenip fiyata
    bölünür. `satis_fiyati_tl` <= 0 olamaz (contracts.py ge=0 kısıtı fiyat için
    0'a izin verse de burada bölme güvenliği için ayrıca korunur).
    """
    if satis_fiyati_tl <= 0:
        return 0.0
    yillik_hedef_ciro = yillik_ciro_payi * profile.toplam_yillik_hedef_ciro_tl
    return (yillik_hedef_ciro / satis_fiyati_tl) / 365.0


def trend_carpani(gun_index: np.ndarray, yillik_trend_orani: float) -> np.ndarray:
    """Yıllık yavaş büyüme/küçülme. `yillik_trend_orani=0.10` → yılda %10 büyüme."""
    return (1.0 + yillik_trend_orani) ** (gun_index / 365.0)


def yillik_sezon_carpani(gun_index: np.ndarray, kategori: KategoriProfili) -> np.ndarray:
    """Sinüs bileşenli yıllık sezon: 1 + genlik * sin(2*pi*(gun/365 - faz))."""
    return 1.0 + kategori.sezonsallik_genligi * np.sin(
        2 * math.pi * (gun_index / 365.0 - kategori.sezon_fazi)
    )


def haftalik_desen_carpani(tarihler: pd.DatetimeIndex) -> np.ndarray:
    """Pazar kapalı (0.0), cumartesi yarım gün (0.5), hafta içi normal (1.0)."""
    haftanin_gunu = tarihler.dayofweek.to_numpy()  # Pazartesi=0 ... Pazar=6
    carpan = np.ones(len(tarihler))
    carpan[haftanin_gunu == 5] = 0.5  # cumartesi
    carpan[haftanin_gunu == 6] = 0.0  # pazar
    return carpan


def bayram_etkisi_carpani(tarihler: pd.DatetimeIndex) -> np.ndarray:
    """Ramazan/Kurban Bayramı öncesi toparlanma + tatil süresince durgunluk."""
    carpan = np.ones(len(tarihler))
    for i, tarih in enumerate(tarihler):
        yil_bayramlari = _DINI_BAYRAM_BASLANGICLARI.get(tarih.year)
        if yil_bayramlari is None:
            continue
        gun = tarih.date()
        for baslangic in yil_bayramlari:
            bitis = baslangic + dt.timedelta(days=_BAYRAM_SURESI_GUN)
            oncesi_baslangic = baslangic - dt.timedelta(days=_BAYRAM_ONCESI_ETKI_GUN)
            if baslangic <= gun < bitis:
                carpan[i] = _BAYRAM_TATIL_ETKI_CARPANI
            elif oncesi_baslangic <= gun < baslangic:
                carpan[i] = _BAYRAM_ONCESI_ETKI_CARPANI
    return carpan


def promo_etkisi_uret(
    rng: np.random.Generator,
    gun_sayisi: int,
    gunluk_promo_olasiligi: float = 0.01,
    sure_araligi: tuple[int, int] = (2, 5),
    carpan_araligi: tuple[float, float] = (1.3, 2.0),
) -> np.ndarray:
    """Seyrek, kısa süreli promosyon sıçramaları. Çoğu gün çarpan 1.0'dır."""
    carpan = np.ones(gun_sayisi)
    gun = 0
    while gun < gun_sayisi:
        if rng.random() < gunluk_promo_olasiligi:
            sure = int(rng.integers(sure_araligi[0], sure_araligi[1] + 1))
            etki = rng.uniform(*carpan_araligi)
            bitis = min(gun + sure, gun_sayisi)
            carpan[gun:bitis] = etki
            gun = bitis
        else:
            gun += 1
    return carpan


def _hizli_hareket_talep_uret(ortalama: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Negatif binom örneklemesi: varyans = ortalama * ASIRI_YAYILMA_ORANI."""
    talep = np.zeros(len(ortalama), dtype=int)
    pozitif = ortalama > 1e-9
    p = 1.0 / ASIRI_YAYILMA_ORANI
    n = ortalama[pozitif] / (ASIRI_YAYILMA_ORANI - 1.0)
    talep[pozitif] = rng.negative_binomial(n, p)
    return talep


def _aralikli_talep_uret(ortalama: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Bernoulli(gün) x miktar: çoğu gün 0, arada bir toplu satış."""
    pozitif_gun_olasiligi = np.clip(ortalama / ARALIKLI_TALEP_POZITIF_GUN_MIKTARI, 0.0, 1.0)
    pozitif_gun = rng.random(len(ortalama)) < pozitif_gun_olasiligi
    miktar = rng.poisson(ARALIKLI_TALEP_POZITIF_GUN_MIKTARI, size=len(ortalama))
    return np.where(pozitif_gun, miktar, 0)


def sku_gunluk_talep_uret(
    sku_id: str,
    kategori: KategoriProfili,
    yillik_ciro_payi: float,
    satis_fiyati_tl: float,
    profile: CompanyProfile,
    baslangic_tarihi: dt.date,
    gun_sayisi: int,
    rng: np.random.Generator,
    yillik_trend_orani: float = 0.0,
) -> pd.DataFrame:
    """Tek bir SKU için `gun_sayisi` günlük talep serisi üretir.

    Dönen DataFrame kolonları: `tarih`, `sku_id`, `talep_miktari` (tam sayı, >= 0).
    """
    tarihler = pd.date_range(baslangic_tarihi, periods=gun_sayisi, freq="D")
    gun_index = np.arange(gun_sayisi)

    temel_hiz = temel_gunluk_hiz(yillik_ciro_payi, satis_fiyati_tl, profile)
    ortalama = (
        temel_hiz
        * trend_carpani(gun_index, yillik_trend_orani)
        * yillik_sezon_carpani(gun_index, kategori)
        * haftalik_desen_carpani(tarihler)
        * bayram_etkisi_carpani(tarihler)
        * promo_etkisi_uret(rng, gun_sayisi)
    )
    ortalama = np.clip(ortalama, 0.0, None)

    if temel_hiz >= GUNLUK_HIZLI_HAREKET_ESIGI:
        talep = _hizli_hareket_talep_uret(ortalama, rng)
    else:
        talep = _aralikli_talep_uret(ortalama, rng)

    return pd.DataFrame(
        {
            "tarih": tarihler,
            "sku_id": sku_id,
            "talep_miktari": talep,
        }
    )


def katalog_icin_talep_uret(
    sku_katalogu: pd.DataFrame,
    profile: CompanyProfile,
    baslangic_tarihi: dt.date,
    gun_sayisi: int,
    rng: np.random.Generator,
    yillik_trend_orani: float = 0.0,
) -> pd.DataFrame:
    """Katalogdaki her SKU için `sku_gunluk_talep_uret`'i çağırıp birleştirir."""
    kategori_index = {k.ad: k for k in profile.kategoriler}
    parcalar = [
        sku_gunluk_talep_uret(
            sku_id=satir.sku_id,
            kategori=kategori_index[satir.kategori],
            yillik_ciro_payi=satir.yillik_ciro_payi,
            satis_fiyati_tl=satir.satis_fiyati_tl,
            profile=profile,
            baslangic_tarihi=baslangic_tarihi,
            gun_sayisi=gun_sayisi,
            rng=rng,
            yillik_trend_orani=yillik_trend_orani,
        )
        for satir in sku_katalogu.itertuples(index=False)
    ]
    return pd.concat(parcalar, ignore_index=True)
