"""Finansın para metriği — tahsilat politikalarının karşılaştırması (Faz 7).

`app/domain/stock/ml.py::politika_karsilastirmasi_calistir`'in finanstaki
karşılığı ve aynı soruyu soruyor: **kural motoru, vasat bir tahsilat
politikasına göre parayı ne kadar iyi yönetiyor?**

Stokta cevap %7,6 maliyet düşüşüydü. Finansta bugüne kadar karşılığı yoktu:
sistem 800 müşteriden 40'ı için karar üretiyordu ama bu kararların bir lira
karşılığı ölçülmemişti.

## ⚠️ Bu dosyanın stok karşılığından ZAYIF olduğu nokta

Stok simülasyonunda politikanın sonucu **fiziksel** olarak belirlenir:
sipariş ver, mal gelir, talep karşılanır ya da karşılanmaz. Kimsenin bir
şey varsaymasına gerek yok.

Tahsilatta öyle değil. "Müşteriyi aradın, ne oldu?" sorusunun cevabı
simülasyonda yok — çünkü insan davranışı. O yüzden burada bir **etki
modeli** var ve bu model varsayım:

    arama → kalan gecikmenin bir kısmı kapanır      (TAKIP_HIZLANDIRMA_ORANI)
    arama → batık alacak bir olasılıkla kurtarılır  (yaşla azalan)
    limit düşürme → gelecek satış engellenir        (marj kaybı, risk kazancı)
    karşılık → nakit etkisi YOK                     (muhasebe kaydı)

Bu sayılar sahadan ölçülmedi; makul kabul edilen değerler. Bu yüzden:

1. Hepsi modül düzeyinde sabit ve **tek yerde**, gizli değil.
2. `duyarlilik_analizi_calistir` sonucun bu sayılara ne kadar bağlı
   olduğunu gösteriyor. Sonuç yalnızca dar bir parametre aralığında
   çıkıyorsa, iddia zayıftır ve öyle raporlanmalı.
3. Rapor cümlesi "maliyeti %X düşürdü" değil, **"bu etki modeli altında
   maliyeti %X düşürdü"** olmalı.

⚠️ Karşılaştırmanın kendisi yine de anlamlı: üç politika **aynı** etki
modeline tabi. Model yanlış olsa bile politikalar arasındaki sıralama, o
modelin içinde adil ölçülüyor.

## Vasat politika neden bu?

"30 günü geçen herkesi her ay ara." Sahada gerçekten yapılan bu: tek bir
mutlak eşik, müşteri ayrımı yok. Kural motorunun iddiası da tam buraya
karşı — eşiği müşterinin **kendi** ödeme davranışından türetmek.

İki ucun arasındaki fark üç yerden gelir:

· hep zamanında ödeyen müşteri 31. günde aranmaz (gereksiz arama maliyeti)
· düzensiz ödeyene ayrıca limit düşürülür (maruz kalınan gelecek risk azalır)
· eşik müşterinin kendi davranışından türer, tek bir 30 gün değil

⚠️ Üçüncü bir fark **yoktu ve olması gerekiyordu**: ilk ölçümde batık
müşteri karşılık koluna düşüp hiç aranmıyordu. Bu, `decide.py`'de düzeltilen
gerçek bir kusurdu — bkz. `dokumantasyon/BILINEN-EKSIKLER.md` §9.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.contracts import KararTipi
from app.domain.finance.decide import ozellikten_kararlar_uret
from app.domain.finance.features import musteri_ozelliklerini_hesapla
from simulator.company import CompanyProfile, yapi_malzemesi_toptancisi
from simulator.run import simulasyon_calistir
from simulator.tahsilat import TahsilatPatolojisi, tahsilat_uret

# ---------------------------------------------------------------------------
# Etki modeli — hepsi varsayım, hepsi burada
# ---------------------------------------------------------------------------

TAKIP_HIZLANDIRMA_ORANI = 0.5
"""Bir tahsilat araması, faturanın **kalan** gecikmesinin bu oranını kapatır.

Çarpımsal olması bilinçli: ikinci arama birincinin kalanı üzerinden etki
eder, yani tekrar aramanın getirisi kendiliğinden azalır. Ek bir "soğuma
süresi" kuralına gerek kalmıyor."""

TAKIP_TEPKI_GUN = 7
"""Aramadan sonra en erken tahsilat. Aynı gün ödeme gerçekçi değil."""

BATAK_KURTARMA_OLASILIGI = 0.30
"""Batık bir alacağın arama ile kurtarılma olasılığı — gecikme sıfırken."""

BATAK_KURTARMA_YARILANMA_GUN = 90.0
"""Kurtarma olasılığı bu gün sayısında yarıya iner.

⭐ Bu üstel azalma, "zamanında aramak" ile "geç aramak" arasındaki farkı
modelin içine koyan tek şey. Sabit bir olasılık kullanılsaydı, batık
müşteriyi 300. günde aramak 30. günde aramakla aynı değeri üretirdi ve
erken davranmanın hiçbir karşılığı olmazdı."""

BATAK_TEKRAR_SONUMU = 0.35
"""Aynı faturaya yapılan her yeni denemenin olasılığı bu oranla çarpılır.

⚠️ Bu katsayı olmadan model **politikayı değil ısrarı** ölçüyordu. İlk
kurulumda her deneme bağımsız bir çekilişti; "herkesi her ay ara" politikası
12 ay boyunca aynı batık faturaya 12 bağımsız şans elde ediyor ve 141
faturayı kurtarıyordu. Gerçekte ödemeyen müşteri her ay **aynı sebeple**
ödemiyor: ilk ciddi temas bilgiyi üretir, sonraki aramalar aynı cevabı alır.

Bağımsız çekiliş varsayımı, yeterince ısrarcı her politikayı kazanan yapar —
ölçüm aracı olarak değersizleştirir."""

TAKIP_MALIYETI_TL = 150.0
"""Bir tahsilat eyleminin maliyeti: personel zamanı, arama, yazışma, takip.

⚠️ Sonucun en duyarlı olduğu sayı bu. Sıfıra yaklaştıkça "herkesi ara"
politikası kazanır — seçici olmanın değeri, seçmemenin bedeliyle ölçülüyor.
`duyarlilik_analizi_calistir` bu bağımlılığı açıkça gösteriyor."""

YILLIK_FINANSMAN_ORANI = 0.45
"""Tahsil edilmemiş alacağın yıllık taşıma maliyeti. Alacak, müşteriye
verilmiş faizsiz kredidir; parayı bir yerden bulmak gerekir."""

# ---------------------------------------------------------------------------
# Vasat politika
# ---------------------------------------------------------------------------

VASAT_TAKIP_ESIGI_GUN = 30
"""Vasat politikanın tek eşiği. Müşteri ayrımı yok — sahadaki yaygın pratik."""

VARSAYILAN_INCELEME_ARALIGI_GUN = 30
"""Tahsilat ekibi ayda bir listeye bakar. Üç politika için de aynı."""

POLITIKALAR = ("taban", "vasat", "kural_motoru")

ABLASYON_POLITIKALARI = ("taban", "vasat", "kural_motoru", "kural_motoru_limitsiz")
"""Ablasyon koşusu: kural motoru + limit kolu KAPALI dördüncü politika.

⭐ Bu ayrımın amacı "kazanan kombinasyonu bulmak" DEĞİL. Kural motoru üç
kollu (takip / limit / karşılık) ve toplam sonuç kaybettiğinde hangi kolun
sorumlu olduğu görünmüyor. Ablasyon o soruyu ayırıyor: limit kolu kaldırılıp
sonuç düzeliyorsa kol zararlı, değişmiyorsa etkisiz, kötüleşiyorsa değerli.

⚠️ Sonuca göre kolu kaldırmak ayrı bir karar ve bu dosyanın işi değil —
burada yalnızca ölçülüyor."""


@dataclass
class _PolitikaDurumu:
    """Bir politikanın kendi dünyası — faturalar bu tabloda değişiyor."""

    faturalar: pd.DataFrame
    rng: np.random.Generator
    aktif_limitler: dict[str, float] = field(default_factory=dict)
    takip_sayisi: int = 0
    kurtarilan_fatura: int = 0
    iptal_edilen_fatura: int = 0
    iptal_tutari_tl: float = 0.0
    karsilik_karari: int = 0
    limit_karari: int = 0


def _takip_uygula(
    durum: _PolitikaDurumu, musteri_id: str, bugun: pd.Timestamp
) -> None:
    """Bir müşteriye tahsilat eylemi uygular — açık ve gecikmiş faturalarına.

    ⚠️ Yalnızca **vadesi geçmiş** faturalar etkileniyor. Henüz vadesi
    gelmemiş bir faturayı "erken ödet" diye aramak sahada yapılmaz ve
    modelde yapılırsa politikaya bedava kazanç yazar.
    """
    f = durum.faturalar
    acik = (
        (f["musteri_id"] == musteri_id)
        & (~f["iptal"])
        & (f["tarih"] <= bugun)
        & (f["vade_tarihi"] < bugun)
        & (f["gercek_odeme_tarihi"].isna() | (f["gercek_odeme_tarihi"] > bugun))
    )
    idx = f.index[acik]
    if len(idx) == 0:
        return

    durum.takip_sayisi += 1

    en_erken = bugun + pd.Timedelta(days=TAKIP_TEPKI_GUN)
    for i in idx:
        odeme = f.at[i, "gercek_odeme_tarihi"]
        gecikme_gun = (bugun - f.at[i, "vade_tarihi"]).days

        if pd.isna(odeme):
            # Batık: kurtarma olasılığı hem alacağın yaşıyla hem de o
            # faturaya kaçıncı kez gidildiğiyle azalıyor.
            deneme = int(f.at[i, "takip_denemesi"])
            f.at[i, "takip_denemesi"] = deneme + 1
            olasilik = (
                BATAK_KURTARMA_OLASILIGI
                * 0.5 ** (gecikme_gun / BATAK_KURTARMA_YARILANMA_GUN)
                * BATAK_TEKRAR_SONUMU**deneme
            )
            if durum.rng.random() < olasilik:
                f.at[i, "gercek_odeme_tarihi"] = en_erken
                durum.kurtarilan_fatura += 1
            continue

        kalan = (odeme - bugun).days
        if kalan <= 0:
            continue
        hizlanmis = round(kalan * (1 - TAKIP_HIZLANDIRMA_ORANI))
        yeni = bugun + pd.Timedelta(days=max(TAKIP_TEPKI_GUN, hizlanmis))
        if yeni < odeme:
            f.at[i, "gercek_odeme_tarihi"] = yeni


def _limit_uygula(
    durum: _PolitikaDurumu,
    musteri_id: str,
    limit_tl: float,
    bugun: pd.Timestamp,
    pencere_sonu: pd.Timestamp,
) -> None:
    """Kredi limitini bir sonraki incelemeye kadar uygular: aşan faturalar iptal.

    ⚠️ Açık bakiye **her fatura tarihinde yeniden** hesaplanıyor, inceleme
    anında bir kez değil. İlk yazımda tek seferlik anlık görüntü
    kullanılmıştı ve sonuç saçmaydı: bakiyesi bir kez limiti aşan müşterinin
    o aya ait TÜM satışları iptal ediliyordu — 4.878 fatura, 256 bin TL marj
    kaybı. Gerçekte müşteri ay boyunca ödeme yapar, bakiye düşer ve satış
    yeniden açılır. Limit bir kapı, giyotin değil.
    """
    f = durum.faturalar
    kendi = f.index[(f["musteri_id"] == musteri_id) & (~f["iptal"])]
    if len(kendi) == 0:
        return

    alt = f.loc[kendi, ["tarih", "gercek_odeme_tarihi", "tutar_tl"]]
    gelecek = alt[(alt["tarih"] > bugun) & (alt["tarih"] <= pencere_sonu)].sort_values("tarih")

    for i, satir in gelecek.iterrows():
        t = satir["tarih"]
        odeme = alt["gercek_odeme_tarihi"]
        acik = alt[(alt["tarih"] <= t) & (odeme.isna() | (odeme > t))]
        bakiye = float(acik["tutar_tl"].sum())

        tutar = float(satir["tutar_tl"])
        if bakiye + tutar > limit_tl:
            f.at[i, "iptal"] = True
            durum.iptal_edilen_fatura += 1
            durum.iptal_tutari_tl += tutar
            # İptal edilen fatura bakiyeye girmemeli — sonraki faturaların
            # kararı bu satırın var olmadığı bir dünyada verilir.
            alt = alt.drop(index=i)


def _vasat_adim(durum: _PolitikaDurumu, bugun: pd.Timestamp) -> None:
    """30 günü geçen her müşteriyi ara. Müşteri ayrımı yok."""
    f = durum.faturalar
    gecikmis = (
        (~f["iptal"])
        & (f["tarih"] <= bugun)
        & (f["vade_tarihi"] < bugun - pd.Timedelta(days=VASAT_TAKIP_ESIGI_GUN))
        & (f["gercek_odeme_tarihi"].isna() | (f["gercek_odeme_tarihi"] > bugun))
    )
    for musteri_id in f.loc[gecikmis, "musteri_id"].unique():
        _takip_uygula(durum, str(musteri_id), bugun)


def _kural_motoru_adim(
    durum: _PolitikaDurumu,
    musteri_df: pd.DataFrame,
    bugun: pd.Timestamp,
    pencere_sonu: pd.Timestamp,
    limit_kolu: bool = True,
) -> None:
    """Gerçek karar hattı: özellik hesabı → `ozellikten_kararlar_uret` → eylem.

    ⚠️ Burada kuralların bir kopyası DEĞİL, üretimde çalışan fonksiyonun
    kendisi çağrılıyor. Kopyalansaydı ölçüm, kodun ölçtüğünü sandığımız
    şeyi değil kopyayı ölçerdi.
    """
    acik_tablo = durum.faturalar[~durum.faturalar["iptal"]]
    ozellikler = musteri_ozelliklerini_hesapla(acik_tablo, musteri_df, bugun.date())

    # ⚠️ Limitler HER incelemede sıfırdan kuruluyor, birikmiyor. İlk yazımda
    # bir kez konan limit sonsuza kadar yürürlükte kalıyordu; ödemesini
    # toparlayan müşterinin limiti hiç geri açılmıyor ve satışı yıl boyunca
    # kesik kalıyordu. Gerçekte kredi limiti dönemsel olarak yeniden
    # değerlendirilir — nitekim sistemin kendisi de her gecelik taramada
    # kararı yeniden üretiyor.
    durum.aktif_limitler = {}

    for ozellik in ozellikler:
        # ⚠️ Çoğul. İlk ölçümde tekil sürüm kullanılıyordu ve batık müşteri
        # karşılık kolunda takılıp hiç aranmıyordu — ölçümün bulduğu ve
        # `decide.py`'de düzeltilen kusur tam olarak buydu.
        for karar in ozellikten_kararlar_uret(ozellik):
            if karar.tip is KararTipi.FINANS_TAHSILAT_TAKIBI:
                _takip_uygula(durum, ozellik.musteri_id, bugun)

            elif karar.tip is KararTipi.FINANS_KREDI_LIMITI_DUSUR:
                if not limit_kolu:
                    # Ablasyon: karar üretiliyor ama uygulanmıyor.
                    continue
                durum.limit_karari += 1
                limit = float(karar.aksiyon["onerilen_kredi_limiti_tl"])
                durum.aktif_limitler[ozellik.musteri_id] = limit
                _limit_uygula(durum, ozellik.musteri_id, limit, bugun, pencere_sonu)

            elif karar.tip is KararTipi.FINANS_KARSILIK_AYIR:
                # Nakit etkisi yok — muhasebe kaydı. Artık takibi de
                # SUSTURMUYOR: aynı müşteri için takip kararı ayrıca üretilip
                # bu döngüde ayrıca uygulanıyor.
                durum.karsilik_karari += 1


# ---------------------------------------------------------------------------
# Maliyet muhasebesi
# ---------------------------------------------------------------------------


def _maliyet_ozeti(
    durum: _PolitikaDurumu, ufuk_sonu: pd.Timestamp, marj_orani: float
) -> dict[str, float]:
    """Dört maliyet kalemi + tahsilat göstergeleri.

    Kalemlerin ayrı raporlanması bilinçli: toplam düşerken hangi kalemin
    arttığı görülmezse, kazancın nereden geldiği bilinmez.
    """
    f = durum.faturalar
    gecerli = f[~f["iptal"]]
    gunluk_oran = YILLIK_FINANSMAN_ORANI / 365.0

    odendi = gecerli["gercek_odeme_tarihi"].notna() & (
        gecerli["gercek_odeme_tarihi"] <= ufuk_sonu
    )
    odenen = gecerli[odendi]
    odenmeyen = gecerli[~odendi]

    # Gecikme günü: ödenende ödeme-vade, ödenmeyende ufuk sonu-vade.
    # Negatif (erken ödeme) sıfırlanıyor: erken ödeyen müşteri finansman
    # maliyeti üretmez, ama "eksi maliyet" de yazmaz.
    gecikme_odenen = (odenen["gercek_odeme_tarihi"] - odenen["vade_tarihi"]).dt.days.clip(lower=0)
    gecikme_odenmeyen = (ufuk_sonu - odenmeyen["vade_tarihi"]).dt.days.clip(lower=0)

    finansman = float(
        (odenen["tutar_tl"] * gecikme_odenen * gunluk_oran).sum()
        + (odenmeyen["tutar_tl"] * gecikme_odenmeyen * gunluk_oran).sum()
    )
    batak_zarari = float(odenmeyen["tutar_tl"].sum())
    takip_maliyeti = durum.takip_sayisi * TAKIP_MALIYETI_TL
    kaybedilen_marj = durum.iptal_tutari_tl * marj_orani

    faturalanan = float(gecerli["tutar_tl"].sum())
    tahsil_edilen = float(odenen["tutar_tl"].sum())

    return {
        "finansman_maliyeti_tl": finansman,
        "batak_zarari_tl": batak_zarari,
        "takip_maliyeti_tl": takip_maliyeti,
        "kaybedilen_marj_tl": kaybedilen_marj,
        "toplam_maliyet_tl": finansman + batak_zarari + takip_maliyeti + kaybedilen_marj,
        "ort_gecikme_gun": float(gecikme_odenen.mean()) if len(odenen) else 0.0,
        "tahsilat_orani": tahsil_edilen / faturalanan if faturalanan > 0 else 0.0,
        "takip_sayisi": float(durum.takip_sayisi),
        "kurtarilan_fatura": float(durum.kurtarilan_fatura),
        "iptal_edilen_fatura": float(durum.iptal_edilen_fatura),
        "karsilik_karari": float(durum.karsilik_karari),
        "limit_karari": float(durum.limit_karari),
    }


# ---------------------------------------------------------------------------
# Ana koşu
# ---------------------------------------------------------------------------


def _dunya_hazirla(
    profile: CompanyProfile, seed: int, yil_sayisi: int, tahsilat_seed: int,
    patoloji: TahsilatPatolojisi,
) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Simülasyon + tahsilat → (faturalar, musteri, ortalama marj oranı)."""
    dunya = simulasyon_calistir(profile=profile, seed=seed, yil_sayisi=yil_sayisi)
    sonuc = tahsilat_uret(
        dunya["faturalar"], dunya["musteri"], seed=tahsilat_seed, patoloji=patoloji
    )

    f = sonuc.faturalar.copy()
    f["tarih"] = pd.to_datetime(f["tarih"])
    # `odeme_tarihi` planlanan ödeme, yani vade. Adı burada `vade_tarihi`
    # yapılıyor: "planlanan" ile "gerçekleşen" iki kolonun adı birbirine
    # benzediği sürece yanlış olanı okumak an meselesi.
    f["vade_tarihi"] = pd.to_datetime(f["odeme_tarihi"])
    f["gercek_odeme_tarihi"] = pd.to_datetime(f["gercek_odeme_tarihi"])
    f["iptal"] = False
    f["takip_denemesi"] = 0

    sku = dunya["sku"]
    marj = ((sku["satis_fiyati_tl"] - sku["birim_maliyet_tl"]) / sku["satis_fiyati_tl"]).mean()

    return f.reset_index(drop=True), dunya["musteri"], float(marj)


def tahsilat_politikasi_karsilastir(
    profile: CompanyProfile | None = None,
    seed: int = 42,
    yil_sayisi: int = 2,
    tahsilat_seed: int = 101,
    patoloji: TahsilatPatolojisi | None = None,
    inceleme_araligi_gun: int = VARSAYILAN_INCELEME_ARALIGI_GUN,
    politikalar: tuple[str, ...] = POLITIKALAR,
) -> pd.DataFrame:
    """Aynı tahsilat dünyasında üç politikayı koşturup karşılaştırır.

    - **taban**: hiçbir şey yapma. Zemin — "kimse aramasa ne olurdu?"
    - **vasat**: 30 günü geçen herkesi her ay ara.
    - **kural_motoru**: `app/domain/finance/decide.py`'nin kendisi.

    **Bitti sayılır:** `kural_motoru`'nun toplam maliyeti `vasat`'ınkinden
    düşük olmalı. Değilse ya kurallar değersiz ya etki modeli politikaların
    farkını taşımıyor — ikisi de raporlanır, gizlenmez.

    ⚠️ Her politika kendi RNG'sini **aynı tohumdan** kurar. Bu, batık
    kurtarma çekilişlerinin politikalar arasında birebir hizalandığı
    anlamına gelmez (çekiliş sayısı politikaya göre değişir); toplam
    ölçekte adil, tek bir faturayı politikalar arası karşılaştırmak için
    değil. `politika_karsilastirmasi_calistir`'deki aynı uyarı.
    """
    profile = profile or yapi_malzemesi_toptancisi()
    patoloji = patoloji or TahsilatPatolojisi(
        kronik_gecikme_aktif=True,
        duzensiz_odeme_aktif=True,
        sezonluk_tikanma_aktif=True,
        batak_aktif=True,
    )

    faturalar, musteri_df, marj_orani = _dunya_hazirla(
        profile, seed, yil_sayisi, tahsilat_seed, patoloji
    )
    if faturalar.empty:
        raise ValueError("Simülasyon hiç fatura üretmedi — karşılaştırma yapılamaz.")

    baslangic = faturalar["tarih"].min()
    ufuk_sonu = faturalar["tarih"].max()
    inceleme_tarihleri = pd.date_range(
        baslangic + pd.Timedelta(days=inceleme_araligi_gun),
        ufuk_sonu,
        freq=f"{inceleme_araligi_gun}D",
    )

    satirlar = []
    for politika in politikalar:
        durum = _PolitikaDurumu(
            faturalar=faturalar.copy(), rng=np.random.default_rng(seed + 3)
        )

        for i, bugun in enumerate(inceleme_tarihleri):
            pencere_sonu = (
                inceleme_tarihleri[i + 1]
                if i + 1 < len(inceleme_tarihleri)
                else ufuk_sonu
            )
            if politika == "vasat":
                _vasat_adim(durum, bugun)
            elif politika.startswith("kural_motoru"):
                _kural_motoru_adim(
                    durum,
                    musteri_df,
                    bugun,
                    pencere_sonu,
                    limit_kolu=(politika != "kural_motoru_limitsiz"),
                )

        ozet = _maliyet_ozeti(durum, ufuk_sonu, marj_orani)
        ozet["politika"] = politika
        satirlar.append(ozet)

    return pd.DataFrame(satirlar).set_index("politika")


def duyarlilik_analizi_calistir(
    takip_maliyetleri: tuple[float, ...] = (0.0, 50.0, 150.0, 400.0, 1000.0),
    **kwargs: object,
) -> pd.DataFrame:
    """Sonucun `TAKIP_MALIYETI_TL` varsayımına ne kadar bağlı olduğunu gösterir.

    ⚠️ Bu fonksiyon modül düzeyindeki sabiti geçici olarak değiştiriyor.
    Test sırasında paralel koşuda yan etki üretir — bilinçli kabul edilen
    bir sınır, çünkü alternatifi (sabiti her fonksiyona parametre olarak
    taşımak) sekiz imzayı kirletirdi ve asıl kullanım tek koşuluk bir
    rapor betiği.

    Okunuşu: kural motorunun üstünlüğü hangi maliyet aralığında geçerli?
    Yalnızca yüksek maliyette kazanıyorsa iddia zayıftır — "sistem iyi"
    değil "aramak pahalı" demiş oluruz.
    """
    global TAKIP_MALIYETI_TL
    orijinal = TAKIP_MALIYETI_TL

    satirlar = []
    try:
        for maliyet in takip_maliyetleri:
            TAKIP_MALIYETI_TL = maliyet
            df = tahsilat_politikasi_karsilastir(**kwargs)  # type: ignore[arg-type]
            vasat = df.loc["vasat", "toplam_maliyet_tl"]
            kural = df.loc["kural_motoru", "toplam_maliyet_tl"]
            satirlar.append(
                {
                    "takip_maliyeti_tl": maliyet,
                    "vasat_toplam_tl": vasat,
                    "kural_motoru_toplam_tl": kural,
                    "iyilesme_orani": 1 - kural / vasat if vasat else 0.0,
                    "kural_motoru_kazandi": bool(kural < vasat),
                }
            )
    finally:
        TAKIP_MALIYETI_TL = orijinal

    return pd.DataFrame(satirlar)


def limit_kolu_taramasi_calistir(
    esikler: tuple[float, ...] = (0.0, 20.0, 30.0, 45.0, 60.0),
    kesinti_oranlari: tuple[float, ...] = (0.25, 0.5, 0.75),
    **kwargs: object,
) -> pd.DataFrame:
    """A7.1: limit kolunun hangi ayarda (varsa) değer ürettiğini tarar.

    `LIMIT_DUSURME_SKOR_ESIGI` = 0 satırı **kolun tamamen kapalı** hâli:
    hiçbir müşterinin skoru 0'ın altına inemez, kol hiç tetiklenmez. Bu
    satır taramanın kontrol grubu — "kolu kaldırmak" seçeneğinin sayısı.

    ⚠️ **Bu bir arama değil, bir ölçüm.** Çıktının tamamı raporlanmalı,
    yalnızca en iyi hücre değil. Kazanan bir hücre bulup diğerlerini
    saklamak, parametreyi veriye uydurup "sistem kazandı" demektir —
    `duyarlilik_analizi_calistir`'ın docstring'indeki aynı uyarı.

    Vasat taban bir kez koşuluyor: limit ayarı vasat politikayı etkilemiyor,
    her hücrede yeniden hesaplamak yalnızca süre harcardı.
    """
    from app.domain.finance import rules

    taban_df = tahsilat_politikasi_karsilastir(politikalar=("vasat",), **kwargs)  # type: ignore[arg-type]
    vasat_maliyet = float(taban_df.loc["vasat", "toplam_maliyet_tl"])

    orijinal_esik = rules.LIMIT_DUSURME_SKOR_ESIGI
    orijinal_kesinti = rules.MAKS_LIMIT_KESINTI_ORANI
    orijinal_aktif = rules.LIMIT_KOLU_AKTIF
    # Kol varsayılan olarak KAPALI (ölçülmüş karar, bkz. `rules.LIMIT_KOLU_AKTIF`).
    # Tarama onu ölçmek için var, o yüzden burada açılıyor; `esik=0` satırı
    # zaten "kol hiç tetiklenmiyor" durumunu temsil ediyor.
    rules.LIMIT_KOLU_AKTIF = True

    satirlar = []
    try:
        for esik in esikler:
            for kesinti in kesinti_oranlari:
                rules.LIMIT_DUSURME_SKOR_ESIGI = esik
                rules.MAKS_LIMIT_KESINTI_ORANI = kesinti
                df = tahsilat_politikasi_karsilastir(
                    politikalar=("kural_motoru",), **kwargs  # type: ignore[arg-type]
                )
                s = df.loc["kural_motoru"]
                satirlar.append(
                    {
                        "esik": esik,
                        "maks_kesinti": kesinti,
                        "toplam_maliyet_tl": s["toplam_maliyet_tl"],
                        "batak_zarari_tl": s["batak_zarari_tl"],
                        "kaybedilen_marj_tl": s["kaybedilen_marj_tl"],
                        "takip_sayisi": s["takip_sayisi"],
                        "limit_karari": s["limit_karari"],
                        "vasata_gore": 1 - s["toplam_maliyet_tl"] / vasat_maliyet,
                    }
                )
                if esik == 0.0:
                    # Kol kapalıyken `maks_kesinti` hiçbir şeyi değiştirmez;
                    # aynı koşuyu üç kez yapmanın anlamı yok.
                    break
    finally:
        rules.LIMIT_DUSURME_SKOR_ESIGI = orijinal_esik
        rules.MAKS_LIMIT_KESINTI_ORANI = orijinal_kesinti
        rules.LIMIT_KOLU_AKTIF = orijinal_aktif

    return pd.DataFrame(satirlar)


__all__ = [
    "BATAK_KURTARMA_OLASILIGI",
    "BATAK_KURTARMA_YARILANMA_GUN",
    "POLITIKALAR",
    "TAKIP_HIZLANDIRMA_ORANI",
    "TAKIP_MALIYETI_TL",
    "TAKIP_TEPKI_GUN",
    "VASAT_TAKIP_ESIGI_GUN",
    "YILLIK_FINANSMAN_ORANI",
    "duyarlilik_analizi_calistir",
    "limit_kolu_taramasi_calistir",
    "tahsilat_politikasi_karsilastir",
]
