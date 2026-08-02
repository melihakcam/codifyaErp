"""Sanal KOBİ profili konfigürasyonu (öneri: yapı malzemesi toptancısı).

Sahip: Kişi A · Faz 1 A1.1

Bu modül tek bir şey üretir: `CompanyProfile`. Diğer simülatör modülleri
(`catalog.py`, `demand.py`, `run.py`, `pathologies.py`) parametrelerini
buradan okur — sabit sayı hiçbiri kendi içinde tutmaz. Faz 4'te "3 farklı
şirket profiliyle simülasyon" gereksinimi bu yüzden tek dosyayı değiştirmekle
karşılanır.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class KategoriProfili:
    """Bir ürün kategorisinin katalog ve talep üretimindeki davranışı."""

    ad: str
    # Birim maliyet aralığı (TL) — log-normal örneklemenin alt/üst çapası.
    birim_maliyet_min: float
    birim_maliyet_max: float
    # Kâr marjı aralığı — satış fiyatı = birim_maliyet * (1 + marj).
    marj_min: float
    marj_max: float
    # Kategori talebe göre ne kadar sezonsal (0 = hiç, 1 = çok güçlü).
    sezonsallik_genligi: float
    # Yıl içinde talebin zirve yaptığı faz (0-1, 0 = 1 Ocak).
    sezon_fazi: float
    # Paket adedi seçenekleri — sipariş bu sayılardan birinin katı olmalı.
    paket_adedi_secenekleri: tuple[int, ...]
    # Tipik raf ömrü (gün). None = bozulmaz / raf ömrü takibi yok.
    raf_omru_gun: int | None = None


@dataclass(frozen=True)
class CompanyProfile:
    """Sanal KOBİ'nin tüm sabitleri.

    `yapi_malzemesi_toptancisi()` fabrika fonksiyonu varsayılan profildir:
    inşaat sezonuna bağlı belirgin sezonsallık, temiz stok mantığı, doğal
    Türkçe ürün adları (tuğla, çimento, demir, alçı, boya, seramik...).
    """

    ad: str
    n_sku: int
    n_tedarikci: int
    n_musteri: int
    kategoriler: tuple[KategoriProfili, ...]

    # Pareto/ciro dağılımı: en üstteki bu oran kadar SKU, cironun
    # `pareto_ciro_orani` kadarını taşısın (ör. üst %20 SKU → %80 ciro).
    pareto_sku_orani: float = 0.20
    pareto_ciro_orani: float = 0.80

    # Şirketin hedeflenen yıllık toplam cirosu (TL). `demand.py` her SKU'nun
    # ortalama günlük satış adedini bu toplamı `yillik_ciro_payi` ile bölüştürerek
    # türetir — katalogdaki Pareto dağılımı böylece gerçek satış hacmine yansır.
    toplam_yillik_hedef_ciro_tl: float = 50_000_000.0

    # Tedarikçi tedarik süresi (gün) — normal dağılımın ortalama/std aralığı,
    # her tedarikçi için bu aralıktan bir çift örneklenir.
    tedarikci_ort_tedarik_suresi_min: float = 3.0
    tedarikci_ort_tedarik_suresi_max: float = 21.0
    tedarikci_tedarik_suresi_std_orani: float = 0.20  # std ≈ ortalama * bu oran
    tedarikci_guvenilirlik_min: float = 0.75
    tedarikci_guvenilirlik_max: float = 0.99

    # Müşteri segmentleri ve yaklaşık ağırlıkları (toplamı 1 olmalı).
    musteri_segmentleri: tuple[str, ...] = ("perakendeci", "usta", "santiye", "bireysel")
    musteri_segment_agirliklari: tuple[float, ...] = (0.35, 0.30, 0.20, 0.15)
    # Ödeme vadesi (gün) segment bazında ortalama — gecikme simülasyonunda kullanılır.
    musteri_odeme_vadesi_gun: dict[str, int] = field(
        default_factory=lambda: {
            "perakendeci": 30,
            "usta": 15,
            "santiye": 45,
            "bireysel": 0,
        }
    )

    def __post_init__(self) -> None:
        toplam_agirlik = sum(self.musteri_segment_agirliklari)
        if abs(toplam_agirlik - 1.0) > 1e-6:
            raise ValueError(
                f"musteri_segment_agirliklari toplamı 1.0 olmalı, {toplam_agirlik} bulundu"
            )
        if len(self.musteri_segmentleri) != len(self.musteri_segment_agirliklari):
            raise ValueError("musteri_segmentleri ve ağırlıkları aynı uzunlukta olmalı")


def yapi_malzemesi_toptancisi() -> CompanyProfile:
    """Varsayılan profil: yapı malzemesi toptancısı, ~2.000 SKU, ~60 tedarikçi, ~800 müşteri.

    Kategori seçimi ve sezonsallık genlikleri inşaat sektörünün bilinen
    davranışını yansıtır: çimento/demir gibi kaba yapı malzemeleri baharda
    zirve yapan güçlü sezonsallığa sahipken, seramik/boya gibi ince yapı
    malzemeleri daha az sezonsal ve yıl boyu daha dengeli satar.
    """
    kategoriler = (
        KategoriProfili(
            ad="cimento",
            birim_maliyet_min=80,
            birim_maliyet_max=180,
            marj_min=0.12,
            marj_max=0.22,
            sezonsallik_genligi=0.55,
            sezon_fazi=0.35,  # nisan-mayıs zirvesi
            paket_adedi_secenekleri=(1, 10, 25),
        ),
        KategoriProfili(
            ad="demir",
            birim_maliyet_min=15000,
            birim_maliyet_max=28000,
            marj_min=0.08,
            marj_max=0.15,
            sezonsallik_genligi=0.45,
            sezon_fazi=0.30,
            paket_adedi_secenekleri=(1, 1, 2),
        ),
        KategoriProfili(
            ad="tugla",
            birim_maliyet_min=2,
            birim_maliyet_max=8,
            marj_min=0.15,
            marj_max=0.25,
            sezonsallik_genligi=0.50,
            sezon_fazi=0.35,
            paket_adedi_secenekleri=(100, 250, 500),
        ),
        KategoriProfili(
            ad="alci",
            birim_maliyet_min=40,
            birim_maliyet_max=90,
            marj_min=0.18,
            marj_max=0.30,
            sezonsallik_genligi=0.35,
            sezon_fazi=0.40,
            paket_adedi_secenekleri=(1, 5, 20),
        ),
        KategoriProfili(
            ad="boya",
            birim_maliyet_min=150,
            birim_maliyet_max=1200,
            marj_min=0.25,
            marj_max=0.45,
            sezonsallik_genligi=0.20,
            sezon_fazi=0.45,
            paket_adedi_secenekleri=(1, 4, 12),
            raf_omru_gun=730,
        ),
        KategoriProfili(
            ad="seramik",
            birim_maliyet_min=90,
            birim_maliyet_max=600,
            marj_min=0.20,
            marj_max=0.40,
            sezonsallik_genligi=0.15,
            sezon_fazi=0.50,
            paket_adedi_secenekleri=(1, 2, 10),
        ),
        KategoriProfili(
            ad="izolasyon",
            birim_maliyet_min=60,
            birim_maliyet_max=400,
            marj_min=0.20,
            marj_max=0.35,
            sezonsallik_genligi=0.30,
            sezon_fazi=0.25,
            paket_adedi_secenekleri=(1, 6, 20),
        ),
        KategoriProfili(
            ad="hirdavat",
            birim_maliyet_min=5,
            birim_maliyet_max=350,
            marj_min=0.30,
            marj_max=0.55,
            sezonsallik_genligi=0.10,
            sezon_fazi=0.50,
            paket_adedi_secenekleri=(1, 10, 50, 100),
        ),
    )

    return CompanyProfile(
        ad="Yapı Malzemesi Toptancısı",
        n_sku=2000,
        n_tedarikci=60,
        n_musteri=800,
        kategoriler=kategoriler,
    )


def kucuk_nalbur_dukkani() -> CompanyProfile:
    """Faz 4 A4.2 — küçük ölçek: mahalle nalbur/hırdavat dükkânı.

    Kural motorunun **ölçeğe aşırı uyum** (overfitting) gösterip
    göstermediğini sınamak için kasıtlı olarak varsayılan profilin ~1/8'i
    büyüklüğünde: ~250 SKU, ~10 tedarikçi, ~150 müşteri. Kategori karması da
    daha dar (yalnızca hırdavat/boya/tuğla) ve sezonsallık daha zayıf —
    büyük toptancı gibi güçlü inşaat-sezonu dalgası yaşamaz, yıl boyu
    nispeten dengeli satar.
    """
    kategoriler = (
        KategoriProfili(
            ad="hirdavat",
            birim_maliyet_min=5,
            birim_maliyet_max=350,
            marj_min=0.30,
            marj_max=0.55,
            sezonsallik_genligi=0.10,
            sezon_fazi=0.50,
            paket_adedi_secenekleri=(1, 10, 50, 100),
        ),
        KategoriProfili(
            ad="boya",
            birim_maliyet_min=150,
            birim_maliyet_max=1200,
            marj_min=0.25,
            marj_max=0.45,
            sezonsallik_genligi=0.20,
            sezon_fazi=0.45,
            paket_adedi_secenekleri=(1, 4, 12),
            raf_omru_gun=730,
        ),
        KategoriProfili(
            ad="tugla",
            birim_maliyet_min=2,
            birim_maliyet_max=8,
            marj_min=0.15,
            marj_max=0.25,
            sezonsallik_genligi=0.25,
            sezon_fazi=0.35,
            paket_adedi_secenekleri=(100, 250),
        ),
    )

    return CompanyProfile(
        ad="Küçük Nalbur Dükkânı",
        n_sku=250,
        n_tedarikci=10,
        n_musteri=150,
        kategoriler=kategoriler,
        toplam_yillik_hedef_ciro_tl=3_000_000.0,
        tedarikci_ort_tedarik_suresi_min=1.0,
        tedarikci_ort_tedarik_suresi_max=7.0,
        musteri_segmentleri=("usta", "bireysel"),
        musteri_segment_agirliklari=(0.55, 0.45),
        musteri_odeme_vadesi_gun={"usta": 15, "bireysel": 0},
    )


def buyuk_insaat_deposu() -> CompanyProfile:
    """Faz 4 A4.2 — büyük ölçek: bölgesel kaba yapı malzemesi dağıtım deposu.

    Varsayılan profilin ~2.5 katı büyüklüğünde (~5.000 SKU, ~150 tedarikçi,
    ~2.000 müşteri), yalnızca kaba yapı kategorilerine (çimento/demir/tuğla/
    alçı/izolasyon) odaklı ve **daha güçlü** inşaat-sezonu dalgası. Amaç:
    kural motorunun büyük ölçekte de (özellikle EOQ/ROP'un çok daha büyük
    hacimlerde makul kalıp kalmadığını) sınamak.
    """
    kategoriler = (
        KategoriProfili(
            ad="cimento",
            birim_maliyet_min=80,
            birim_maliyet_max=180,
            marj_min=0.10,
            marj_max=0.18,
            sezonsallik_genligi=0.70,
            sezon_fazi=0.35,
            paket_adedi_secenekleri=(1, 10, 25, 50),
        ),
        KategoriProfili(
            ad="demir",
            birim_maliyet_min=15000,
            birim_maliyet_max=28000,
            marj_min=0.06,
            marj_max=0.12,
            sezonsallik_genligi=0.60,
            sezon_fazi=0.30,
            paket_adedi_secenekleri=(1, 1, 2, 5),
        ),
        KategoriProfili(
            ad="tugla",
            birim_maliyet_min=2,
            birim_maliyet_max=8,
            marj_min=0.12,
            marj_max=0.20,
            sezonsallik_genligi=0.65,
            sezon_fazi=0.35,
            paket_adedi_secenekleri=(250, 500, 1000),
        ),
        KategoriProfili(
            ad="alci",
            birim_maliyet_min=40,
            birim_maliyet_max=90,
            marj_min=0.15,
            marj_max=0.25,
            sezonsallik_genligi=0.45,
            sezon_fazi=0.40,
            paket_adedi_secenekleri=(1, 5, 20, 50),
        ),
        KategoriProfili(
            ad="izolasyon",
            birim_maliyet_min=60,
            birim_maliyet_max=400,
            marj_min=0.15,
            marj_max=0.28,
            sezonsallik_genligi=0.40,
            sezon_fazi=0.25,
            paket_adedi_secenekleri=(1, 6, 20, 50),
        ),
    )

    return CompanyProfile(
        ad="Büyük İnşaat Deposu",
        n_sku=5000,
        n_tedarikci=150,
        n_musteri=2000,
        kategoriler=kategoriler,
        toplam_yillik_hedef_ciro_tl=500_000_000.0,
        tedarikci_ort_tedarik_suresi_min=5.0,
        tedarikci_ort_tedarik_suresi_max=35.0,
        musteri_segmentleri=("perakendeci", "santiye"),
        musteri_segment_agirliklari=(0.30, 0.70),
        musteri_odeme_vadesi_gun={"perakendeci": 30, "santiye": 60},
    )
