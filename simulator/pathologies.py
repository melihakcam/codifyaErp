"""Enjekte edilen patolojiler: tedarik gecikmesi, talep patlaması, ölü stok,
fiyat zammı, sezon sonu fazlası, sayım farkı. Her biri loglanır.

Sahip: Kişi A · Faz 1 A1.4

Her patoloji `PatolojiKonfigurasyonu` üzerinden bağımsız açılıp kapanabilir
(hepsi varsayılan kapalı — config verilmezse `run.py` tamamen "sağlıklı" veri
üretir, A1.3'teki davranışla bit bit aynıdır). Açık olan her patoloji, *ne
zaman* enjekte edildiğini `olay_logu` DataFrame'ine yazar — bu log olmadan
"modelimiz bu olayı yakaladı mı?" sorusu ölçülemez (Faz 5 değerlendirmesinin
dayanağı budur).

Üç patoloji doğrudan sayısal çarpan/gecikme matrisi olarak üretilir (talep
patlaması, ölü stok, tedarikçi gecikmesi, fiyat zammı, sezon sonu fazlası) ve
`run.py`'nin günlük döngüsüne çarpan/toplama olarak enjekte edilir. Sayım farkı
farklıdır: gerçek zamanlı eldeki stoğa bağlı olduğu için (örn. "stoğun %8'i
kadar fark") burada yalnızca *hangi SKU'nun hangi tarihte ne oranda* denetime
tabi olacağı üretilir — gerçek miktar farkı `run.py` çalışırken o anki eldeki
stoktan hesaplanır.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from simulator.company import CompanyProfile
from simulator.demand import GUNLUK_HIZLI_HAREKET_ESIGI, temel_gunluk_hiz


@dataclass(frozen=True)
class PatolojiKonfigurasyonu:
    """Hangi patolojilerin açık olduğu + parametreleri. Hepsi varsayılan kapalı."""

    tedarikci_gecikmesi_aktif: bool = False
    tedarikci_gecikmesi_gunluk_baslama_olasiligi: float = 0.003
    tedarikci_gecikmesi_sure_araligi: tuple[int, int] = (10, 30)
    tedarikci_gecikmesi_ek_gun_araligi: tuple[int, int] = (5, 15)

    talep_patlamasi_aktif: bool = False
    talep_patlamasi_sku_orani: float = 0.03
    talep_patlamasi_carpan_araligi: tuple[float, float] = (2.0, 3.0)
    talep_patlamasi_sure_araligi: tuple[int, int] = (7, 21)

    olu_stok_aktif: bool = False
    olu_stok_sku_orani: float = 0.02
    olu_stok_carpani: float = 0.02  # tamamen 0 yerine kucuk bir kalinti talep birakilir
    olu_stok_baslangic_gun_orani_araligi: tuple[float, float] = (0.4, 0.85)

    fiyat_zammi_aktif: bool = False
    fiyat_zammi_tedarikci_orani: float = 0.10
    fiyat_zammi_orani_araligi: tuple[float, float] = (0.08, 0.25)

    sezon_sonu_fazlasi_aktif: bool = False
    sezon_sonu_fazlasi_carpani: float = 2.5
    sezon_sonu_fazlasi_sure_gun: int = 20
    sezon_sonu_fazi_kaymasi: float = 0.25  # sezon zirvesinden ne kadar sonra (yil fraksiyonu)

    sayim_farki_aktif: bool = False
    sayim_farki_yilda_sayisi: int = 4
    sayim_farki_sku_orani: float = 0.05
    sayim_farki_orani_araligi: tuple[float, float] = (-0.08, 0.08)


@dataclass(frozen=True)
class PatolojiCiktilari:
    """`run.py`'nin günlük döngüsüne enjekte edeceği hazır matrisler + log."""

    talep_carpani: np.ndarray  # (gun_sayisi, n_sku), varsayılan 1.0
    tedarik_ek_gecikme_gun: np.ndarray  # (gun_sayisi, n_tedarikci), varsayılan 0
    birim_maliyet_carpani: np.ndarray  # (gun_sayisi, n_tedarikci), varsayılan 1.0
    siparis_hedef_gun_carpani: np.ndarray  # (gun_sayisi, n_sku), varsayılan 1.0
    sayim_denetimleri: pd.DataFrame  # tarih, sku_id, fark_orani
    olay_logu: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(
            columns=["tarih", "tur", "hedef_id", "aciklama", "buyukluk"]
        )
    )


def _bos_olay_logu() -> list[dict]:
    return []


def _tedarikci_gecikmesi_uret(
    konfig: PatolojiKonfigurasyonu,
    tedarikci_df: pd.DataFrame,
    tarihler: pd.DatetimeIndex,
    rng: np.random.Generator,
    olaylar: list[dict],
) -> np.ndarray:
    """(gun_sayisi, n_tedarikci) ek gecikme gün matrisi. Basit durum makinesi:
    her gün her tedarikçi için, aktif değilse küçük olasılıkla gecikme başlar."""
    n_tedarikci = len(tedarikci_df)
    gun_sayisi = len(tarihler)
    ek_gecikme = np.zeros((gun_sayisi, n_tedarikci))

    kalan_gun = np.zeros(n_tedarikci, dtype=int)
    aktif_ek_gun = np.zeros(n_tedarikci)
    aktif_baslangic = np.full(n_tedarikci, -1)

    for t in range(gun_sayisi):
        bitenler = np.nonzero(kalan_gun == 1)[0]
        for idx in bitenler:
            olaylar.append(
                {
                    "tarih": tarihler[aktif_baslangic[idx]],
                    "tur": "TEDARIKCI_GECIKMESI",
                    "hedef_id": tedarikci_df.index[idx],
                    "aciklama": "Tedarikçi teslim süresi geçici olarak uzadı.",
                    "buyukluk": aktif_ek_gun[idx],
                }
            )

        kalan_gun = np.maximum(kalan_gun - 1, 0)

        baslayabilir = (kalan_gun == 0) & (
            rng.random(n_tedarikci) < konfig.tedarikci_gecikmesi_gunluk_baslama_olasiligi
        )
        for idx in np.nonzero(baslayabilir)[0]:
            sure = rng.integers(*konfig.tedarikci_gecikmesi_sure_araligi, endpoint=True)
            kalan_gun[idx] = sure
            aktif_ek_gun[idx] = rng.uniform(*konfig.tedarikci_gecikmesi_ek_gun_araligi)
            aktif_baslangic[idx] = t

        aktif = kalan_gun > 0
        ek_gecikme[t, aktif] = aktif_ek_gun[aktif]

    return ek_gecikme


def _talep_patlamasi_uret(
    konfig: PatolojiKonfigurasyonu,
    profile: CompanyProfile,
    sku_df: pd.DataFrame,
    tarihler: pd.DatetimeIndex,
    rng: np.random.Generator,
    olaylar: list[dict],
) -> np.ndarray:
    """(gun_sayisi, n_sku) çarpan matrisi. Rastgele seçilmiş SKU'larda, rastgele
    bir başlangıç gününden itibaren birkaç hafta süren 2-3 kat talep sıçraması."""
    n_sku = len(sku_df)
    gun_sayisi = len(tarihler)
    carpan = np.ones((gun_sayisi, n_sku))

    # Aday havuzu yalnızca zaten "hızlı hareket eden" (temel_hiz >= eşik) SKU'lar
    # olsun — neredeyse hiç satmayan bir SKU'yu 2-3 katına çıkarmak gözle görünür
    # bir "patlama" üretmez, aralıklı talebin gürültüsünde kaybolur.
    temel_hizlar = np.array(
        [
            temel_gunluk_hiz(satir.yillik_ciro_payi, satir.satis_fiyati_tl, profile)
            for satir in sku_df.itertuples(index=False)
        ]
    )
    aday_havuzu = np.nonzero(temel_hizlar >= GUNLUK_HIZLI_HAREKET_ESIGI)[0]
    if len(aday_havuzu) == 0:
        aday_havuzu = np.arange(n_sku)
    n_secilen = max(1, round(n_sku * konfig.talep_patlamasi_sku_orani))
    secilen_sku_idx = rng.choice(aday_havuzu, size=min(n_secilen, len(aday_havuzu)), replace=False)

    for sku_idx in secilen_sku_idx:
        baslangic = int(rng.integers(0, gun_sayisi))
        sure = int(rng.integers(*konfig.talep_patlamasi_sure_araligi, endpoint=True))
        bitis = min(baslangic + sure, gun_sayisi)
        etki = rng.uniform(*konfig.talep_patlamasi_carpan_araligi)
        carpan[baslangic:bitis, sku_idx] = etki
        olaylar.append(
            {
                "tarih": tarihler[baslangic],
                "tur": "TALEP_PATLAMASI",
                "hedef_id": sku_df.iloc[sku_idx]["sku_id"],
                "aciklama": f"Talep {etki:.1f} kat sıçradı, {bitis - baslangic} gün sürdü.",
                "buyukluk": etki,
            }
        )

    return carpan


def _olu_stok_uret(
    konfig: PatolojiKonfigurasyonu,
    sku_df: pd.DataFrame,
    tarihler: pd.DatetimeIndex,
    rng: np.random.Generator,
    olaylar: list[dict],
) -> np.ndarray:
    """(gun_sayisi, n_sku) çarpan matrisi: seçilen SKU'larda bir tarihten sonra
    talep neredeyse sıfıra düşer (tamamen 0 değil — gerçekçi kalıntı talep)."""
    n_sku = len(sku_df)
    gun_sayisi = len(tarihler)
    carpan = np.ones((gun_sayisi, n_sku))

    # Yavaş ama tamamen ölü OLMAYAN ürünler arasından seç (yaklaşık 20.-60.
    # persentil): gerçek hayatta ölü stok genelde zaten az satan ürünlerde
    # birikir, ama aday zaten satmıyorsa "önce/sonra" farkı hiç görünmez.
    siralanmis = sku_df.sort_values("yillik_ciro_payi").index.to_numpy()
    alt = round(len(siralanmis) * 0.20)
    ust = round(len(siralanmis) * 0.60)
    aday_havuzu = siralanmis[alt:ust]
    n_secilen = max(1, round(n_sku * konfig.olu_stok_sku_orani))
    secilen = rng.choice(aday_havuzu, size=min(n_secilen, len(aday_havuzu)), replace=False)

    for sku_idx in secilen:
        baslangic_orani = rng.uniform(*konfig.olu_stok_baslangic_gun_orani_araligi)
        baslangic = int(baslangic_orani * gun_sayisi)
        carpan[baslangic:, sku_idx] = konfig.olu_stok_carpani
        olaylar.append(
            {
                "tarih": tarihler[baslangic],
                "tur": "OLU_STOK",
                "hedef_id": sku_df.iloc[sku_idx]["sku_id"],
                "aciklama": "Ürün talebi kalıcı olarak neredeyse durdu.",
                "buyukluk": konfig.olu_stok_carpani,
            }
        )

    return carpan


def _fiyat_zammi_uret(
    konfig: PatolojiKonfigurasyonu,
    tedarikci_df: pd.DataFrame,
    tarihler: pd.DatetimeIndex,
    rng: np.random.Generator,
    olaylar: list[dict],
) -> np.ndarray:
    """(gun_sayisi, n_tedarikci) çarpan matrisi: seçilen tedarikçilerde bir
    tarihten itibaren kalıcı birim maliyet artışı."""
    n_tedarikci = len(tedarikci_df)
    gun_sayisi = len(tarihler)
    carpan = np.ones((gun_sayisi, n_tedarikci))

    n_secilen = max(1, round(n_tedarikci * konfig.fiyat_zammi_tedarikci_orani))
    secilen = rng.choice(n_tedarikci, size=n_secilen, replace=False)

    for idx in secilen:
        baslangic = int(rng.integers(0, gun_sayisi))
        zam_orani = rng.uniform(*konfig.fiyat_zammi_orani_araligi)
        carpan[baslangic:, idx] = 1.0 + zam_orani
        olaylar.append(
            {
                "tarih": tarihler[baslangic],
                "tur": "FIYAT_ZAMMI",
                "hedef_id": tedarikci_df.index[idx],
                "aciklama": f"Tedarikçi birim maliyeti kalıcı olarak %{zam_orani * 100:.0f} arttı.",
                "buyukluk": zam_orani,
            }
        )

    return carpan


def _sezon_sonu_fazlasi_uret(
    konfig: PatolojiKonfigurasyonu,
    profile: CompanyProfile,
    sku_df: pd.DataFrame,
    tarihler: pd.DatetimeIndex,
    olaylar: list[dict],
) -> np.ndarray:
    """(gun_sayisi, n_sku) çarpan matrisi: her kategorinin sezon zirvesinden bir
    süre sonra (sezon kapanırken), sipariş hedefini geçici olarak şişirir —
    gereksiz sipariş sezon sonunda fazla stok olarak birikir."""
    n_sku = len(sku_df)
    gun_sayisi = len(tarihler)
    carpan = np.ones((gun_sayisi, n_sku))

    kategori_index = {k.ad: k for k in profile.kategoriler}
    yil_sayisi = int(np.ceil(gun_sayisi / 365)) + 1

    for kategori_adi, kategori in kategori_index.items():
        sku_maskesi = (sku_df["kategori"] == kategori_adi).to_numpy()
        if not sku_maskesi.any():
            continue
        for yil in range(yil_sayisi):
            merkez_gun = int(
                (kategori.sezon_fazi + konfig.sezon_sonu_fazi_kaymasi) * 365 + yil * 365
            )
            baslangic = max(0, merkez_gun - konfig.sezon_sonu_fazlasi_sure_gun // 2)
            bitis = min(gun_sayisi, baslangic + konfig.sezon_sonu_fazlasi_sure_gun)
            if baslangic >= gun_sayisi or bitis <= baslangic:
                continue
            carpan[baslangic:bitis, sku_maskesi] = konfig.sezon_sonu_fazlasi_carpani
            olaylar.append(
                {
                    "tarih": tarihler[baslangic],
                    "tur": "SEZON_SONU_FAZLASI",
                    "hedef_id": kategori_adi,
                    "aciklama": "Sezon sonu sipariş hedefi geçici olarak şişirildi.",
                    "buyukluk": konfig.sezon_sonu_fazlasi_carpani,
                }
            )

    return carpan


def _sayim_farki_uret(
    konfig: PatolojiKonfigurasyonu,
    sku_df: pd.DataFrame,
    tarihler: pd.DatetimeIndex,
    rng: np.random.Generator,
    olaylar: list[dict],
) -> pd.DataFrame:
    """Denetim tarihleri x rastgele SKU örneklemi x fark oranı. Gerçek miktar
    farkı `run.py` çalışırken o anki eldeki stoktan hesaplanır (burada bilinmiyor)."""
    n_sku = len(sku_df)
    gun_sayisi = len(tarihler)
    yil_sayisi = max(1, round(gun_sayisi / 365))
    toplam_denetim = konfig.sayim_farki_yilda_sayisi * yil_sayisi
    denetim_gunleri = np.linspace(0, gun_sayisi - 1, toplam_denetim + 2, dtype=int)[1:-1]

    n_ornek = max(1, round(n_sku * konfig.sayim_farki_sku_orani))
    kayitlar = []
    for gun in denetim_gunleri:
        ornek_idx = rng.choice(n_sku, size=n_ornek, replace=False)
        farklar = rng.uniform(*konfig.sayim_farki_orani_araligi, size=n_ornek)
        for sku_idx, fark_orani in zip(ornek_idx, farklar, strict=True):
            kayitlar.append(
                {
                    "tarih": tarihler[gun],
                    "sku_id": sku_df.iloc[sku_idx]["sku_id"],
                    "fark_orani": fark_orani,
                }
            )
        olaylar.append(
            {
                "tarih": tarihler[gun],
                "tur": "SAYIM_FARKI",
                "hedef_id": f"denetim-{gun}",
                "aciklama": f"{n_ornek} SKU fiziksel sayıma tabi tutuldu.",
                "buyukluk": float(n_ornek),
            }
        )

    return pd.DataFrame(kayitlar, columns=["tarih", "sku_id", "fark_orani"])


def patolojiler_uret(
    profile: CompanyProfile,
    sku_df: pd.DataFrame,
    tedarikci_df: pd.DataFrame,
    tarihler: pd.DatetimeIndex,
    rng: np.random.Generator,
    konfig: PatolojiKonfigurasyonu | None = None,
) -> PatolojiCiktilari:
    """Aktif olan patolojileri üretir. `konfig=None` → hepsi kapalı, sağlıklı veri."""
    konfig = konfig or PatolojiKonfigurasyonu()
    n_sku = len(sku_df)
    n_tedarikci = len(tedarikci_df)
    gun_sayisi = len(tarihler)
    olaylar: list[dict] = _bos_olay_logu()

    talep_carpani = np.ones((gun_sayisi, n_sku))
    tedarik_ek_gecikme = np.zeros((gun_sayisi, n_tedarikci))
    birim_maliyet_carpani = np.ones((gun_sayisi, n_tedarikci))
    siparis_hedef_carpani = np.ones((gun_sayisi, n_sku))
    sayim_denetimleri = pd.DataFrame(columns=["tarih", "sku_id", "fark_orani"])

    if konfig.tedarikci_gecikmesi_aktif:
        tedarik_ek_gecikme = _tedarikci_gecikmesi_uret(konfig, tedarikci_df, tarihler, rng, olaylar)

    if konfig.talep_patlamasi_aktif:
        talep_carpani *= _talep_patlamasi_uret(konfig, profile, sku_df, tarihler, rng, olaylar)

    if konfig.olu_stok_aktif:
        talep_carpani *= _olu_stok_uret(konfig, sku_df, tarihler, rng, olaylar)

    if konfig.fiyat_zammi_aktif:
        birim_maliyet_carpani = _fiyat_zammi_uret(konfig, tedarikci_df, tarihler, rng, olaylar)

    if konfig.sezon_sonu_fazlasi_aktif:
        siparis_hedef_carpani = _sezon_sonu_fazlasi_uret(konfig, profile, sku_df, tarihler, olaylar)

    if konfig.sayim_farki_aktif:
        sayim_denetimleri = _sayim_farki_uret(konfig, sku_df, tarihler, rng, olaylar)

    olay_logu = pd.DataFrame(
        olaylar, columns=["tarih", "tur", "hedef_id", "aciklama", "buyukluk"]
    )
    if not olay_logu.empty:
        olay_logu = olay_logu.sort_values("tarih").reset_index(drop=True)

    return PatolojiCiktilari(
        talep_carpani=talep_carpani,
        tedarik_ek_gecikme_gun=tedarik_ek_gecikme,
        birim_maliyet_carpani=birim_maliyet_carpani,
        siparis_hedef_gun_carpani=siparis_hedef_carpani,
        sayim_denetimleri=sayim_denetimleri,
        olay_logu=olay_logu,
    )
