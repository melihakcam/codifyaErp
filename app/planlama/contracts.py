"""Planlama sözleşmesi — alanların genel motorla konuştuğu dil.

⚠️ Buradaki hiçbir alan adı bir iş alanına ait olmamalı. `hat_id`,
`arac_plakasi`, `vardiya_kodu` gibi bir alan eklendiği gün motor genel
olmaktan çıkar ve o kelimeyi kullanmayan alan onu kullanamaz.

Alanın kendi kimliği `kaynak_id`/`is_id` içinde taşınır ve `etiketler`
sözlüğüyle zenginleştirilir; motor onlara **bakmaz**, yalnızca taşır.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Kaynak:
    """Kapasitesi olan ve işleri üstlenen şey.

    Üretimde hat, nakliyede araç, vardiyada kişi, bilgi işlemde makine.

    `gunluk_kapasite` bir **sayı**, birimi alanın bileceği iş: saat, km,
    m³, adam-saat. Motor birimi bilmiyor ve bilmemeli — bilseydi birim
    başına özel davranış yazma isteği doğar ve genellik orada biterdi.
    `kapasite_birimi` yalnızca çıktıyı okunur kılmak için.
    """

    kaynak_id: str
    ad: str
    gunluk_kapasite: float
    kapasite_birimi: str = "saat"
    etiketler: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.gunluk_kapasite <= 0:
            raise ValueError(
                f"{self.kaynak_id}: günlük kapasite 0 olamaz — kapasitesiz bir "
                "kaynağa iş verilemez ve bu hata plan koşarken değil, kurulum "
                "anında görünmeli."
            )


@dataclass(frozen=True)
class Is:
    """Bir kaynağa yerleştirilecek iş.

    Üretimde üretim emri, nakliyede sevkiyat, vardiyada nöbet.

    ## ⚠️ `oncelik`: küçük olan önce

    Sayının **anlamı alana ait**, sıralaması motora. Üretimde "eldeki mal
    kaç gün yeter" (2 gün = acil), nakliyede "teslime kaç gün kaldı",
    vardiyada "kaç gündür boşta". Motor yalnızca küçükten büyüğe sıralıyor.

    Bu ayrım bilinçli: önceliği motorun hesaplaması, ona alan bilgisi
    taşımak olurdu. Alan kendi aciliyetini bilir, motor yalnızca sırayı.

    `bolunebilir=False` olan iş bir güne sığmıyorsa **hiç yerleştirilmiyor**.
    Fırın bir kez yakılır, kamyon yolun yarısında durmaz; böyle işleri iki
    güne bölmek planı kâğıt üzerinde doğru, sahada uygulanamaz yapar.

    ## ⚠️ `kaynak_id` boş olabilir — atamanın kendisi karar olabilir

    Üretimde kalem zaten bir hatta bağlıdır: "hangi hat" sorusu ana veride
    cevaplanmış. Nakliyede ise **soru tam olarak budur** — "şu araç şuraya
    gidebilir". Bir sevkiyat birden çok araca uygunsa hangisine verileceği
    plana ait bir karardır.

    Bu yüzden iki kip var ve ikisi de sözleşmede:

        kaynak_id dolu    -> is o kaynaga baglidir (uretim)
        kaynak_id bos     -> uygun_kaynaklar arasindan secilir (nakliye)

    Atama desteği olmadan nakliye örneği sahte olurdu: araçları elle
    dağıtıp "motor genel" demek, motorun yapmadığı işi yapmış saymaktır.
    """

    is_id: str
    ad: str
    yuk: float
    oncelik: float
    kaynak_id: str | None = None
    uygun_kaynaklar: tuple[str, ...] = ()
    bolunebilir: bool = True
    etiketler: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.yuk <= 0:
            raise ValueError(f"{self.is_id}: yük 0 olamaz — yüksüz iş plana girmemeli.")
        if not self.kaynak_id and not self.uygun_kaynaklar:
            raise ValueError(
                f"{self.is_id}: ne kaynak atanmış ne de uygun kaynak listesi var — "
                "bu iş hiçbir yere yerleştirilemez. Hata plan koşarken değil, "
                "kurulum anında görünmeli."
            )

    def kaynak_adaylari(self) -> tuple[str, ...]:
        """Bu işin gidebileceği kaynaklar. Atanmışsa tek elemanlı."""
        return (self.kaynak_id,) if self.kaynak_id else self.uygun_kaynaklar


BELIRLEYICILER = ("kapasite", "uygunluk", "aciliyet", "tek_aday")


@dataclass(frozen=True)
class AtamaGerekcesi:
    """Bir işin NEDEN o kaynağa gittiği.

    ⚠️ **Metin değil, VERİ.** Serbest metin olsaydı iki şey birden
    kaybedilirdi: test edilemezdi (bir cümlenin doğruluğu assert edilemez)
    ve LLM'in uydurmasına açık olurdu. Alanlar sayı ve kimlik; cümleyi
    bunlardan üreten katman ayrı ve sonra geliyor.

    `belirleyici` "asıl sebep hangisiydi" sorusunun tek kelimelik cevabı:

        tek_aday   -> baska aday yoktu, secim degil zorunluluk
        uygunluk   -> adaylarin cogu uygunluk kisitindan elendi
        kapasite   -> adaylar uygundu, en bos olan secildi
        aciliyet   -> sira isin onceligi yuzunden boyle kuruldu

    ⚠️ Değer kümesi **kapalı**. Serbest bırakılsaydı her alan kendi
    kelimesini yazar ("hat_musait", "arac_bos") ve motorun genelliği
    gerekçe alanından sızarak biterdi.
    """

    secilen_kaynak: str
    aday_kaynaklar: tuple[str, ...]
    belirleyici: str = "tek_aday"
    # kaynak_id -> neden olmadi. ⚠️ Aday listesinin DISINDAKI kaynaklar da
    # burada yer alabilir: uygunluk kisitindan elenen kaynak aday sayilmaz
    # ama kullaniciya soylenmesi gereken bilgi tam olarak odur ("Arac 3 bu
    # ise uygun degil"). Aday listesi "yarisanlar", elenme sozlugu ise
    # "neden olmadi" sorusunun cevabi.
    elenme_nedenleri: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.belirleyici not in BELIRLEYICILER:
            raise ValueError(
                f"belirleyici '{self.belirleyici}' tanımlı değil. "
                f"Tanımlılar: {list(BELIRLEYICILER)}"
            )
        if self.secilen_kaynak not in self.aday_kaynaklar:
            # ⚠️ Seçilen kaynağın aday listesinde olmaması, gerekçenin
            # atamayı anlatmadığı anlamına gelir. Böyle bir gerekçe
            # yanlış bilgi verir; hiç olmamasından kötüdür.
            raise ValueError(
                f"seçilen kaynak '{self.secilen_kaynak}' aday listesinde yok: "
                f"{list(self.aday_kaynaklar)}"
            )
        if self.secilen_kaynak in self.elenme_nedenleri:
            # ⚠️ Seçilen kaynak aynı anda "elenen" olamaz. Gerekçenin
            # kendisiyle çelişmesi, hiç gerekçe olmamasından kötüdür.
            raise ValueError(
                f"seçilen kaynak '{self.secilen_kaynak}' elenme nedenleri arasında da var"
            )


@dataclass(frozen=True)
class PlanSatiri:
    """Bir işin plandaki yeri."""

    is_id: str
    ad: str
    kaynak_id: str
    kaynak_adi: str
    baslangic: date
    bitis: date
    yuk: float
    oncelik: float
    etiketler: dict[str, str] = field(default_factory=dict)
    # ⚠️ Varsayılanlı ve geriye uyumlu. Gerekçeyi üreten taraf (yerleştirme)
    # ile tüketen taraf (plan belgesi) ayrı kişilerde ilerliyor; belge
    # gerekçe yoksa o bölümü atlar, patlamaz. Faz 10-11'de aynı disiplin
    # ikisinin birbirini beklemesini önledi.
    gerekce: AtamaGerekcesi | None = None

    @property
    def gun_sayisi(self) -> int:
        return (self.bitis - self.baslangic).days + 1


@dataclass(frozen=True)
class KaynakPlani:
    """Bir kaynağın planı ve dışarıda kalanlar."""

    kaynak_id: str
    kaynak_adi: str
    gunluk_kapasite: float
    kapasite_birimi: str
    satirlar: tuple[PlanSatiri, ...]
    # ⚠️ Ufuk plana AİT bir bilgi, çağıranın hatırlaması gereken bir şey
    # değil. Doluluk oranı ufuk olmadan hesaplanamaz: yük ufuk boyunca
    # birikirken kapasite günlüktür ve ikisini bölmek %500 gibi anlamsız
    # sayılar üretir (ilk koşuda tam bu oldu).
    ufuk_gun: int = 1
    # ⚠️ Sığmayanlar sessizce düşmüyor. Bir işi plana koymamak onu iptal
    # etmek değil; kullanıcı neyin dışarıda kaldığını görmek zorunda. Aksi
    # hâlde plan "her şey yetişiyor" yalanını söyler.
    sigmayanlar: tuple[PlanSatiri, ...] = ()

    @property
    def toplam_yuk(self) -> float:
        return sum(s.yuk for s in self.satirlar)

    @property
    def doluluk(self) -> float:
        """Ufuk boyunca kullanılan kapasitenin oranı.

        ⚠️ Yüksek doluluk **iyi değil**, yalnızca bir olgu. %100 dolu bir
        kaynak tek gecikmede tüm planı kaydırır; bu sayı bir hedefle
        karşılaştırılmıyor, olduğu gibi raporlanıyor.
        """
        toplam = self.gunluk_kapasite * self.ufuk_gun
        return self.toplam_yuk / toplam if toplam else 0.0


__all__ = ["BELIRLEYICILER", "AtamaGerekcesi", "Is", "Kaynak", "KaynakPlani", "PlanSatiri"]
