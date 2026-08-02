"""~2.000 SKU, ~60 tedarikçi, ~800 müşteri. Deterministik seed.

Sahip: Kişi A · Faz 1 A1.1

Üç üretim fonksiyonu tek bir seed'den beslenir (`np.random.default_rng(seed)`):
`tedarikciler_uret`, `musteriler_uret`, `sku_katalogu_uret`. Hepsi aynı seed ve
aynı `CompanyProfile` ile çağrıldığında **bit bit aynı** DataFrame'i üretir —
bu determinizm, hem eğitim verisinin tekrarlanabilirliği hem de "gerçeği
bildiğimiz dünya" ölçümü için zorunludur.

Ciro dağılımı Pareto ilkesine (üst %20 SKU → cironun ~%80'i) göre üretilir:
her SKU'ya bir `yillik_ciro_payi` atanır (toplamı 1). Ham bir Pareto/Lomax
örneklemesi (`rng.pareto`) n=2.000 gibi sonlu bir örneklemde bu oranı büyük
sapmayla tutturur — tek bir aşırı çekiliş toplamın çok üstüne çıkarabilir.
Bunun yerine **rank tabanlı Zipf ağırlıkları** kullanılır: hedef oranı (üst
%20 → %80) tam tutturan üs parametresi ikili aramayla bulunur, ranklar SKU'lara
rastgele (seed'li) atanır. Böylece toplam pay her zaman hedefe yakın kalır,
rastgelelik yalnızca *hangi* SKU'nun hangi rankı aldığını belirler.
`demand.py` bu payı SKU'nun temel talep hızını ölçeklemek için kullanacak.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from simulator.company import CompanyProfile, yapi_malzemesi_toptancisi

# Üst %20 SKU'nun cironun ~%80'ini taşıması hedeflenir (klasik Pareto ilkesi).
HEDEF_PARETO_ORANI = 0.20
HEDEF_PARETO_PAYI = 0.80


def _zipf_ciro_agirliklari(n: int) -> np.ndarray:
    """Rank 1 (en yüksek pay) .. n (en düşük pay) için Zipf ağırlıkları.

    Üs parametresi `s`, üst %20'lik dilimin payının `HEDEF_PARETO_PAYI`'na
    en yakın olacağı değere ikili arama ile ayarlanır. Dönen dizi rank
    sırasına göredir (`sonuc[0]` en yüksek paylı SKU'ya karşılık gelir);
    SKU'lara atanması ayrı bir adımdır.
    """
    ranklar = np.arange(1, n + 1, dtype=float)
    ust_dilim_sayisi = max(1, round(n * HEDEF_PARETO_ORANI))

    def ust_dilim_payi(s: float) -> float:
        agirlik = ranklar ** (-s)
        agirlik /= agirlik.sum()
        return float(agirlik[:ust_dilim_sayisi].sum())

    lo, hi = 0.01, 5.0
    for _ in range(60):
        orta = (lo + hi) / 2
        if ust_dilim_payi(orta) < HEDEF_PARETO_PAYI:
            lo = orta
        else:
            hi = orta
    s = (lo + hi) / 2

    agirlik = ranklar ** (-s)
    return agirlik / agirlik.sum()

_TEDARIKCI_BOLGE = (
    "Marmara", "Ege", "Akdeniz", "İç Anadolu", "Karadeniz", "Trakya", "Çukurova", "Anadolu",
)
_TEDARIKCI_SEKTOR = ("Yapı Malzemeleri", "İnşaat", "Yapı Ticaret", "Yapı Sanayi", "Toptan Ticaret")
_TEDARIKCI_UNVAN = ("A.Ş.", "Ltd. Şti.")

_MUSTERI_SEHIR = (
    "İstanbul", "Ankara", "İzmir", "Bursa", "Antalya", "Konya", "Gaziantep", "Kayseri",
    "Mersin", "Kocaeli", "Samsun", "Denizli", "Eskişehir", "Şanlıurfa", "Adana",
)

_KATEGORI_URUN_ADLARI: dict[str, tuple[str, ...]] = {
    "cimento": (
        "Portland Çimento 32.5 R", "Portland Çimento 42.5 R", "Beyaz Çimento",
        "Hazır Sıva Harcı", "Şap Harcı", "Yalıtım Harcı",
    ),
    "demir": (
        "İnşaat Demiri 8mm", "İnşaat Demiri 10mm", "İnşaat Demiri 12mm",
        "İnşaat Demiri 14mm", "İnşaat Demiri 16mm", "Hasır Çelik Q188", "Profil Demir",
    ),
    "tugla": (
        "Delikli Tuğla 8.5x19x19", "Delikli Tuğla 13.5x19x19", "Yatay Delikli Tuğla",
        "Gazbeton Blok 10cm", "Gazbeton Blok 20cm", "Gazbeton Blok 25cm",
    ),
    "alci": (
        "Alçı Sıva", "Saten Alçı", "Alçıpan 12.5mm", "Alçıpan 15mm", "Kartonpiyer",
    ),
    "boya": (
        "İç Cephe Boyası", "Dış Cephe Boyası", "Astar Boya", "Sentetik Boya",
        "Silikonlu Dış Cephe Boyası", "Ahşap Vernik",
    ),
    "seramik": (
        "Zemin Seramiği 30x30", "Zemin Seramiği 60x60", "Duvar Seramiği 20x25",
        "Granit Seramik 60x60", "Porselen Karo",
    ),
    "izolasyon": (
        "Su Yalıtım Membranı", "Isı Yalıtım Levhası 5cm", "Isı Yalıtım Levhası 10cm",
        "Cam Yünü Rulo", "Taş Yünü Levha",
    ),
    "hirdavat": (
        "Vida Seti", "Çivi Kutusu", "Menteşe", "Kilit Takımı", "El Aleti Seti", "Zımba Teli",
    ),
}

_KATEGORI_MARKA = {
    "cimento": ("Baticim", "Çimsa", "Akçansa", "Nuh Çimento"),
    "demir": ("Kardemir", "İçdaş", "Kroman Çelik", "Çolakoğlu"),
    "tugla": ("Wienerberger", "Tuğlas", "Ege Tuğla"),
    "alci": ("Knauf", "Alçıpan", "Baumit"),
    "boya": ("Filli Boya", "Marshall", "Dyo", "Polisan"),
    "seramik": ("Kale Seramik", "Vitra", "Çanakkale Seramik"),
    "izolasyon": ("İzocam", "Rockwool", "Knauf Insulation"),
    "hirdavat": ("Bosch", "Makita", "Yerli Hırdavat"),
}


def tedarikciler_uret(profile: CompanyProfile, rng: np.random.Generator) -> pd.DataFrame:
    """~n_tedarikci tedarikçi üretir: tedarik süresi profili + güvenilirlik."""
    n = profile.n_tedarikci
    ort_tedarik_suresi = rng.uniform(
        profile.tedarikci_ort_tedarik_suresi_min,
        profile.tedarikci_ort_tedarik_suresi_max,
        size=n,
    )
    tedarik_suresi_std = ort_tedarik_suresi * profile.tedarikci_tedarik_suresi_std_orani
    guvenilirlik = rng.uniform(
        profile.tedarikci_guvenilirlik_min, profile.tedarikci_guvenilirlik_max, size=n
    )

    bolgeler = rng.choice(_TEDARIKCI_BOLGE, size=n)
    sektorler = rng.choice(_TEDARIKCI_SEKTOR, size=n)
    unvanlar = rng.choice(_TEDARIKCI_UNVAN, size=n)
    adlar = [f"{b} {s} {u}" for b, s, u in zip(bolgeler, sektorler, unvanlar, strict=True)]

    return pd.DataFrame(
        {
            "tedarikci_id": [f"T-{i:04d}" for i in range(1, n + 1)],
            "tedarikci_adi": adlar,
            "ort_tedarik_suresi_gun": ort_tedarik_suresi,
            "tedarik_suresi_std_gun": tedarik_suresi_std,
            "guvenilirlik": guvenilirlik,
        }
    )


def musteriler_uret(profile: CompanyProfile, rng: np.random.Generator) -> pd.DataFrame:
    """~n_musteri müşteri üretir: segment + ödeme vadesi."""
    n = profile.n_musteri
    segmentler = rng.choice(
        profile.musteri_segmentleri, size=n, p=profile.musteri_segment_agirliklari
    )
    sehirler = rng.choice(_MUSTERI_SEHIR, size=n)
    odeme_vadesi = [profile.musteri_odeme_vadesi_gun[s] for s in segmentler]

    return pd.DataFrame(
        {
            "musteri_id": [f"M-{i:04d}" for i in range(1, n + 1)],
            "musteri_adi": [
                f"{sehir} {segment.capitalize()} Müşterisi {i}"
                for i, (sehir, segment) in enumerate(zip(sehirler, segmentler, strict=True), 1)
            ],
            "segment": segmentler,
            "sehir": sehirler,
            "odeme_vadesi_gun": odeme_vadesi,
        }
    )


def sku_katalogu_uret(
    profile: CompanyProfile, rng: np.random.Generator, tedarikciler: pd.DataFrame
) -> pd.DataFrame:
    """~n_sku SKU üretir: kategori, maliyet/fiyat, tedarikçi, paket/MOQ, ciro payı."""
    n = profile.n_sku
    kategori_adlari = [k.ad for k in profile.kategoriler]
    kategori_index = {k.ad: k for k in profile.kategoriler}

    kategoriler = rng.choice(kategori_adlari, size=n)

    birim_maliyet = np.empty(n)
    marj = np.empty(n)
    paket_adedi = np.empty(n, dtype=int)
    raf_omru = np.full(n, np.nan)
    urun_adlari = []

    for i, kat_adi in enumerate(kategoriler):
        kat = kategori_index[kat_adi]
        birim_maliyet[i] = rng.uniform(kat.birim_maliyet_min, kat.birim_maliyet_max)
        marj[i] = rng.uniform(kat.marj_min, kat.marj_max)
        paket_adedi[i] = rng.choice(kat.paket_adedi_secenekleri)
        if kat.raf_omru_gun is not None:
            raf_omru[i] = kat.raf_omru_gun

        urun_ad = rng.choice(_KATEGORI_URUN_ADLARI[kat_adi])
        marka = rng.choice(_KATEGORI_MARKA[kat_adi])
        urun_adlari.append(f"{urun_ad} - {marka}")

    satis_fiyati = birim_maliyet * (1 + marj)
    moq = paket_adedi * rng.integers(1, 6, size=n)

    tedarikci_id = rng.choice(tedarikciler["tedarikci_id"].to_numpy(), size=n)

    # Zipf ağırlıklarını (rank sırasına göre) SKU'lara rastgele ata — hangi
    # SKU'nun hangi rankı aldığı seed'e bağlı, toplam pay dağılımı sabit.
    agirlik_sirali = _zipf_ciro_agirliklari(n)
    rank_atamasi = rng.permutation(n)
    yillik_ciro_payi = np.empty(n)
    yillik_ciro_payi[rank_atamasi] = agirlik_sirali

    return pd.DataFrame(
        {
            "sku_id": [f"S-{i:05d}" for i in range(1, n + 1)],
            "sku_adi": urun_adlari,
            "kategori": kategoriler,
            "birim_maliyet_tl": birim_maliyet,
            "satis_fiyati_tl": satis_fiyati,
            "tedarikci_id": tedarikci_id,
            "paket_adedi": paket_adedi,
            "moq": moq,
            "raf_omru_gun": raf_omru,
            "yillik_ciro_payi": yillik_ciro_payi,
        }
    )


def katalog_uret(
    profile: CompanyProfile | None = None, seed: int = 42
) -> dict[str, pd.DataFrame]:
    """Tüm katalog tablolarını tek seed'den üretir. Ana giriş noktası.

    Aynı `profile` ve `seed` ile çağrıldığında bit bit aynı sonucu verir —
    üç DataFrame de tek bir `np.random.default_rng(seed)` örneğinden sırayla
    (tedarikçi → müşteri → SKU) beslenir, bu yüzden çağrı sırası değişmez.
    """
    profile = profile or yapi_malzemesi_toptancisi()
    rng = np.random.default_rng(seed)

    tedarikciler = tedarikciler_uret(profile, rng)
    musteriler = musteriler_uret(profile, rng)
    sku = sku_katalogu_uret(profile, rng, tedarikciler)

    return {"sku": sku, "tedarikci": tedarikciler, "musteri": musteriler}
