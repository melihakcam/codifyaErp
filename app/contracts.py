"""Codifya Karar Motoru — Sözleşmeler.

⚠️ BU DOSYA DONDURULMUŞTUR (Faz 0.4).

Bu dosya Kişi A ile Kişi B arasındaki sınırdır:
  · Kişi A  (Veri & Alan)   → bu tipleri ÜRETİR   (app/domain/, simulator/)
  · Kişi B  (Servis & Model) → bu tipleri TÜKETİR (app/api/, app/core/, app/llm/)

Değişiklik gerekiyorsa ikisi birlikte karar verir ve tek bir PR'da yapılır.
Tek taraflı değişiklik diğerinin kodunu sessizce bozar.

İsimlendirme: yapısal isimler İngilizce (BaseModel, Enum), iş alanı terimleri
Türkçe (eldeki_stok, tedarik_suresi_gun). İş terimleri ERP kullanıcısının
konuştuğu dilde kalsın diye bilinçli bir tercih.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Sabit kümeler
# ---------------------------------------------------------------------------


class Alan(StrEnum):
    """Karar motorunun kapsadığı iş alanları. Faz 1 yalnızca STOK."""

    STOK = "stok"
    FINANS = "finans"
    SATIS = "satis"
    URETIM = "uretim"


class KararTipi(StrEnum):
    """Nokta ayrımlı isimler politika tablosunda anahtar olarak kullanılır."""

    STOK_SIPARIS = "stok.siparis"
    STOK_TASFIYE = "stok.tasfiye"
    STOK_TEDARIKCI_DEGISIM = "stok.tedarikci_degisim"
    STOK_AKSIYON_YOK = "stok.aksiyon_yok"


class ABCSinifi(StrEnum):
    """Ciro katkısına göre sınıf. A = cironun büyük kısmını taşıyan azınlık."""

    A = "A"
    B = "B"
    C = "C"


class XYZSinifi(StrEnum):
    """Talep değişkenliğine göre sınıf. X = düzenli, Z = çok değişken."""

    X = "X"
    Y = "Y"
    Z = "Z"


class OtonomiSeviyesi(StrEnum):
    """Sistemin yetki kademesi. Sıra bu şekilde ilerler, atlanmaz.

    SHADOW    : karar verir, kaydeder, HİÇBİR ŞEY UYGULAMAZ. Başlangıç modu.
    ADVISORY  : öneri + gerekçe gösterir, uygulamayı insan yapar.
    THRESHOLD : eşik altını kendi uygular, üstünü onay kuyruğuna alır.
    OFF       : kill switch — hiç karar üretilmez.
    """

    SHADOW = "shadow"
    ADVISORY = "advisory"
    THRESHOLD = "threshold"
    OFF = "off"


class PolitikaSonucu(StrEnum):
    """Politikanın SAF çıktısı — otonomi seviyesinden bağımsızdır."""

    OTO_UYGULA = "oto_uygula"
    ONAY_KUYRUGU = "onay_kuyrugu"
    AKSIYON_YOK = "aksiyon_yok"


class GuardSonucu(StrEnum):
    """Sayısal doğrulama guard'ının sonucu. Denetim kaydına yazılır."""

    GECTI = "gecti"
    YENIDEN_URETILDI = "yeniden_uretildi"
    SABLONA_DUSTU = "sablona_dustu"
    ATLANDI = "atlandi"  # gerekçe hiç üretilmedi (kuyrukta bekliyor)


# ---------------------------------------------------------------------------
# Özellikler — kural motorunun gördüğü her şey
# ---------------------------------------------------------------------------


class StockFeatures(BaseModel):
    """Bir SKU hakkında kural motorunun karar verirken gördüğü her şey.

    Aynı zamanda guard'ın "izinli sayılar" kümesinin ana kaynağıdır:
    gerekçe metninde geçen her sayı ya buradan ya tetiklenen kurallardan
    ya da aksiyondan gelmek zorundadır. Bu yüzden buraya alan eklemek,
    LLM'in o sayıyı kullanmasına izin vermek anlamına gelir.
    """

    model_config = ConfigDict(frozen=True)

    # Kimlik
    sku_id: str
    sku_adi: str
    kategori: str

    # Stok durumu
    eldeki_stok: int = Field(ge=0)
    rezerve_stok: int = Field(ge=0, description="Satılmış ama sevk edilmemiş")
    yoldaki_stok: int = Field(ge=0, description="Sipariş verilmiş, henüz gelmemiş")

    # Talep profili
    ort_gunluk_talep: float = Field(ge=0)
    talep_std: float = Field(ge=0)
    veri_gun_sayisi: int = Field(
        ge=0, description="Kaç günlük geçmişe dayanıyor — güven skorunu besler"
    )

    # Tedarik profili
    tedarik_suresi_gun: float = Field(gt=0)
    tedarik_suresi_std: float = Field(ge=0)

    # Sınıflandırma ve hedef
    abc_sinifi: ABCSinifi
    xyz_sinifi: XYZSinifi
    hedef_servis_seviyesi: float = Field(
        gt=0, lt=1, description="ABC/XYZ matrisinden türetilir, ör. 0.95"
    )

    # Hareketsizlik / bozulma
    son_hareket_gun_once: int = Field(ge=0)
    raf_omru_kalan_gun: int | None = Field(default=None, ge=0)

    # Para
    birim_maliyet_tl: float = Field(ge=0)
    satis_fiyati_tl: float = Field(ge=0)

    # Tedarikçi
    tedarikci_id: str
    tedarikci_adi: str
    tedarikci_skoru: float = Field(ge=0, le=100)
    tedarikci_zamaninda_teslim_orani: float = Field(ge=0, le=1)
    tedarikci_onayli: bool = Field(description="Eşikli otonomi ön koşulu")

    # Sipariş kısıtları
    moq: int = Field(ge=0, description="Minimum sipariş adedi")
    paket_adedi: int = Field(gt=0, description="Sipariş bu sayının katı olmalı")

    # Bağlam
    olcum_tarihi: date

    @property
    def kullanilabilir_stok(self) -> int:
        """Rezerve düşülmüş, gerçekten satılabilir stok."""
        return self.eldeki_stok - self.rezerve_stok

    @property
    def talep_varyasyon_katsayisi(self) -> float:
        """σ/μ — XYZ sınıflandırmasının dayanağı. Talep yoksa 0."""
        if self.ort_gunluk_talep <= 0:
            return 0.0
        return self.talep_std / self.ort_gunluk_talep


# ---------------------------------------------------------------------------
# Kural izleri
# ---------------------------------------------------------------------------


class FiredRule(BaseModel):
    """Tetiklenmiş tek bir kuralın izi.

    `degerler` yalnızca insana bilgi değil — guard'ın izinli sayılar
    kümesine katkı verir. Kural bir sayı hesapladıysa, LLM o sayıyı
    gerekçede kullanabilsin diye buraya yazılmak zorundadır.
    """

    model_config = ConfigDict(frozen=True)

    kod: str = Field(description="Makine okunur kod, ör. ROP_ALTINDA")
    aciklama: str = Field(description="İnsan okunur tek cümle, Türkçe")
    degerler: dict[str, float] = Field(
        default_factory=dict,
        description="Kuralın kullandığı/hesapladığı sayılar, ör. {'rop': 615}",
    )


# ---------------------------------------------------------------------------
# Karar adayı — A'nın ürettiği, B'nin tükettiği ana nesne
# ---------------------------------------------------------------------------

ORAN_ALANLARI: frozenset[str] = frozenset(
    {
        "hedef_servis_seviyesi",
        "tedarikci_zamaninda_teslim_orani",
        "talep_varyasyon_katsayisi",
    }
)
"""Yüzde olarak da yazılabilen oran alanları. Adı burada olmayan bir alan için
×100 karşılığı ÜRETİLMEZ. Bu liste bilinçli olarak açık: koşulu değere göre
kurmak (0-1 aralığı) adet/gün alanlarını da yakalıyordu —
`son_hareket_gun_once=1` olan bir ürün için "%100" izinli hale geliyordu.

Yeni bir oran alanı eklenirse (`FiredRule.degerler` içinde veya
`StockFeatures`'a) buraya da eklenmeli. Unutulursa sonuç GÜVENLİ tarafa
düşer: yüzdesi izinli olmaz, guard reddeder, gerekçe şablona düşer — karar
hiçbir koşulda bloke olmaz, yalnızca o cümle yazılamaz."""


class DecisionCandidate(BaseModel):
    """Kural motoru + ML'in ürettiği karar adayı.

    "Aday" çünkü henüz politikadan geçmemiştir: uygulanıp uygulanmayacağına
    app/core/policy.py karar verir. LLM bu nesneyi yalnızca OKUR ve
    gerekçe metnine dönüştürür — içindeki hiçbir sayıyı değiştirmez.
    """

    model_config = ConfigDict(frozen=True)

    karar_id: UUID = Field(default_factory=uuid4)
    alan: Alan
    tip: KararTipi

    aksiyon: dict[str, float | int | str | None] = Field(
        description="Uygulanacak somut aksiyon, ör. "
        "{'siparis_miktari': 1200, 'tedarikci_id': 'T-014'}. "
        "AKSIYON_YOK durumunda boş sözlük."
    )
    tahmini_tutar_tl: float = Field(ge=0, description="Finansal etki — risk skorunun ana girdisi")
    geri_alinabilir: bool = Field(
        default=True,
        description="Sipariş iptal edilebilir mi? Tasfiye genelde geri alınamaz.",
    )
    guven: float = Field(
        ge=0.0,
        le=1.0,
        description="Veri yeterliliği + kural mutabakatı + tahmin belirsizliği",
    )

    tetiklenen_kurallar: list[FiredRule] = Field(default_factory=list)
    ozellikler: StockFeatures

    model_surumleri: dict[str, str] = Field(
        default_factory=dict,
        description="İzlenebilirlik, ör. {'rules': '1.0', 'demand_ml': '1.2'}",
    )
    uretim_zamani: datetime = Field(default_factory=datetime.now)

    def izinli_sayilar(self) -> set[float]:
        """Gerekçe metninde geçmesine izin verilen sayıların tam kümesi.

        Guard (app/llm/guard.py) tam olarak bu kümeyi kullanır. Sözleşmenin
        bu metodu barındırması bilinçlidir: "hangi sayılar meşru" sorusunun
        cevabı A ile B arasında tek bir yerde tanımlı olsun.

        `ORAN_ALANLARI`'nda adı geçen alanlar için ×100 karşılığı da eklenir;
        çünkü 0.94 oranı gerekçede "%94" olarak yazılır. Bu kontrol **alan
        adına** göre yapılır, değerin 0-1 aralığında olmasına göre değil —
        aksi halde adet/gün alanları (`son_hareket_gun_once`, `eldeki_stok`
        vb.) 1 değerini aldığında "%100" sayısı da yanlışlıkla izinli hale
        gelirdi (bkz. Kişi B'nin B2.5 guard incelemesinde bulduğu kusur:
        `son_hareket_gun_once=1` iken 100 izinliydi — dün hareket görmüş her
        SKU için "%100" gerekçede kullanılabilir hale geliyordu).

        Not: `guven` bu kümenin dışındadır — LLM gerekçede güven skorunu
        yüzde olarak kullanamaz. Bilinçli bir tercih: güven skoru iş
        kullanıcısına gösterilecek bir sayı değil, iç politika kararı
        (`app/core/policy.py`) için üretilir.
        """
        sayilar: set[float] = set()

        def ekle(v: object, ad: str = "") -> None:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return
            f = float(v)
            sayilar.add(f)
            if ad in ORAN_ALANLARI:
                sayilar.add(f * 100.0)

        # Özellikler (hesaplanan property'ler dahil)
        for ad, deger in self.ozellikler.model_dump().items():
            ekle(deger, ad)
        ekle(self.ozellikler.kullanilabilir_stok, "kullanilabilir_stok")
        ekle(self.ozellikler.talep_varyasyon_katsayisi, "talep_varyasyon_katsayisi")

        # Kuralların hesapladığı sayılar
        for kural in self.tetiklenen_kurallar:
            for ad, deger in kural.degerler.items():
                ekle(deger, ad)

        # Aksiyon ve tutar
        for ad, deger in self.aksiyon.items():
            ekle(deger, ad)
        ekle(self.tahmini_tutar_tl, "tahmini_tutar_tl")

        return sayilar


# ---------------------------------------------------------------------------
# Politika çıktısı
# ---------------------------------------------------------------------------


class PolitikaKarari(BaseModel):
    """Politikanın bir karar adayı hakkındaki hükmü.

    `sonuc` ile `uygulandi` bilinçli olarak ayrıdır: shadow modda politika
    OTO_UYGULA der ama `uygulandi=False` olur. Shadow mod raporu tam olarak
    bu iki alanın karşılaştırmasından çıkar.
    """

    model_config = ConfigDict(frozen=True)

    karar_id: UUID
    sonuc: PolitikaSonucu
    uygulandi: bool
    otonomi_seviyesi: OtonomiSeviyesi
    risk_skoru: float = Field(ge=0)
    gerekce_kodlari: list[str] = Field(
        default_factory=list,
        description="Bu sonuca neden varıldığı, ör. ['TUTAR_ESIK_USTU']",
    )


# ---------------------------------------------------------------------------
# Gerekçe (LLM çıktısı)
# ---------------------------------------------------------------------------


class Gerekce(BaseModel):
    """LLM'in ürettiği Türkçe açıklama + guard sonucu.

    Karar yolundan bağımsızdır: gerekçe üretilemese bile karar geçerlidir.
    """

    model_config = ConfigDict(frozen=True)

    karar_id: UUID
    metin: str
    guard_sonucu: GuardSonucu
    model_adi: str | None = None
    uretim_ms: int | None = Field(default=None, ge=0)
    reddedilen_sayilar: list[float] = Field(
        default_factory=list,
        description="Guard'ın yakaladığı, bağlamda olmayan sayılar",
    )


class KararSonucu(BaseModel):
    """API'nin dışarıya döndürdüğü birleşik cevap.

    `gerekce` None olabilir — kuyrukta bekliyor demektir. ERP bunu bekler
    durumda kalmaz; karar `aday` ve `politika` alanlarıyla zaten tamdır.
    """

    aday: DecisionCandidate
    politika: PolitikaKarari
    gerekce: Gerekce | None = None
