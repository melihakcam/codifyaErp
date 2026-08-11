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

    # Faz 6 · Finans & Tahsilat
    FINANS_TAHSILAT_TAKIBI = "finans.tahsilat_takibi"
    FINANS_KREDI_LIMITI_DUSUR = "finans.kredi_limiti_dusur"
    FINANS_KARSILIK_AYIR = "finans.karsilik_ayir"
    FINANS_AKSIYON_YOK = "finans.aksiyon_yok"

    # Faz 10 · Üretim Planlama
    #
    # Her tip, eklendiği adımda **üretiliyor**. Kullanılmayan bir karar tipi
    # tanımlamak `stok.tedarikci_degisim`'de bir kez yapıldı: politika
    # tablosunda ve enum'da aylarca ölü durdu, golden set'te örneği yoktu ve
    # "var mı yok mu" sorusu her incelemede yeniden soruldu
    # (BILINEN-EKSIKLER §5).
    URETIM_EMIR_AC = "uretim.emir_ac"
    URETIM_EMIR_ERTELEME = "uretim.emir_erteleme"
    URETIM_AKSIYON_YOK = "uretim.aksiyon_yok"
    # ⚠️ Adım 4. Diğer üç tiple **ortogonal**: aynı kalem için hem "emir aç"
    # hem "hat dolu" aynı anda doğru olabilir. Bu yüzden karar üreticisi
    # liste döndürüyor ve bu tip o listeye ayrı bir eleman olarak giriyor —
    # `elif` zincirine EKLENMİYOR (finanstaki kusurun kaynağı buydu, §9).
    URETIM_KAPASITE_ASIMI = "uretim.kapasite_asimi"

    @property
    def aksiyon_yok_mu(self) -> bool:
        """ "Yapılacak bir şey yok" tipi mi?

        ⚠️ Politika bu soruyu **alan bağımsız** sormalı. Önceden
        `aday.tip is KararTipi.STOK_AKSIYON_YOK` diye yazılıydı; finans
        eklendiğinde `finans.aksiyon_yok` sessizce oto-uygulama yoluna
        girerdi — "yapılacak bir şey yok" kararı için onay kuyruğu açmak
        gibi görünür ama aslında tersi: hiçbir şey yapmayan bir kararı
        "uygulandı" diye kaydetmek olurdu.
        """
        return self.value.endswith(".aksiyon_yok")

    @property
    def alan(self) -> str:
        """Tipin ait olduğu alan (`"stok.siparis"` → `"stok"`)."""
        return self.value.split(".", 1)[0]


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


class AlanOzellikleri(BaseModel):
    """Her iş alanının özellik sınıfının uyduğu taban.

    ⚠️ **Bu sınıfın var olma sebebi Faz 6.** Faz 1-5 boyunca yalnızca stok
    vardı ve alan-bağımsız katmanlar (guard, politika, gerekçe üretimi)
    doğrudan `StockFeatures` alanlarını okuyordu — `sku_adi`,
    `tedarikci_onayli` gibi. Finans eklenirken bu sızıntıların her biri
    ayrı bir kırılma noktası olurdu.

    Aşağıdaki üç metot, alan-bağımsız katmanların **tek ihtiyacı**. Yeni bir
    alan eklerken cevaplanması gereken üç soru bunlar:

    1. Hangi metin alanları rakam içerebilir? (guard maskelemesi)
    2. `model_dump()`'ta görünmeyen hangi hesaplanan sayılar var?
    3. Bu kaydın oto-uygulamayı engelleyen bir durumu var mı?

    ⚠️ Taban sınıf **veri alanı tanımlamaz** (`olcum_tarihi` dâhil). Sebebi:
    her alanın kendi zaman kavramı olabilir ve ortak alan zorlamak, olmayan
    bir benzerliği varsaymak olurdu. Ortak olan yalnızca davranış.
    """

    model_config = ConfigDict(frozen=True)

    def maskelenecek_alanlar(self) -> list[str]:
        """Rakam içerebilen ad/kod alanları — guard bunları metinden siler.

        `"Kırmızı Tuğla 19x9x5"` içindeki 19, 9, 5 ölçüdür, veri değil.
        Maskelenmezse geçerli her gerekçe reddedilir (bkz. `app/llm/guard.py`).
        """
        raise NotImplementedError

    def hesaplanan_sayilar(self) -> dict[str, float]:
        """`model_dump()`'ta görünmeyen, property olarak hesaplanan sayılar.

        `izinli_sayilar()` bunları da kümeye katar; aksi hâlde model kendi
        verdiğimiz bir türetilmiş sayıyı gerekçede kullanamaz.
        """
        raise NotImplementedError

    @property
    def gorunen_ad(self) -> str:
        """Kullanıcıya gösterilecek kısa kimlik — ürün adı, müşteri adı...

        ⚠️ Alan-bağımsız katmanlar başlık kurarken bunu kullanmalı. Faz 6'da
        `app/jobs/nightly.py::_icgoru_basligi` doğrudan `o.sku_adi` okuyordu;
        finans kararı gecelik taramaya girdiği anda `AttributeError` verirdi.
        """
        raise NotImplementedError

    def oto_uygulama_engeli(self) -> str | None:
        """Oto-uygulamayı engelleyen alan-özel bir durum varsa gerekçe kodu.

        Stokta "tedarikçi onaylı değil", finansta "müşterinin kredisi
        onaysız" gibi. Yoksa `None`.

        ⚠️ Politika motoru bu bilgiyi alan bilmeden sormalı. Önceden
        `aday.ozellikler.tedarikci_onayli` diye doğrudan okunuyordu ve
        finans özellikleri geldiğinde `AttributeError` verirdi.
        """
        return None


class StockFeatures(AlanOzellikleri):
    """Bir SKU hakkında kural motorunun karar verirken gördüğü her şey.

    Aynı zamanda guard'ın "izinli sayılar" kümesinin ana kaynağıdır:
    gerekçe metninde geçen her sayı ya buradan ya tetiklenen kurallardan
    ya da aksiyondan gelmek zorundadır. Bu yüzden buraya alan eklemek,
    LLM'in o sayıyı kullanmasına izin vermek anlamına gelir.
    """

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
    tedarikci_siparis_sayisi: int = Field(
        default=0,
        ge=0,
        description=(
            "Bu tedarikçiye verilmiş sipariş sayısı — tedarikçi hakkındaki "
            "kanıtın miktarı. 0 = bilinmiyor."
        ),
    )

    # Sipariş kısıtları
    moq: int = Field(ge=0, description="Minimum sipariş adedi")
    paket_adedi: int = Field(gt=0, description="Sipariş bu sayının katı olmalı")

    # Üretimden gelen talep (Faz 10 · Adım 5 · MRP)
    mrp_ihtiyaci: float = Field(
        default=0.0,
        ge=0,
        description=(
            "Açılması önerilen üretim emirlerinin bu hammaddeden istediği miktar. "
            "Yeniden sipariş noktasının ÜSTÜNE eklenir — satış talebiyle üretim "
            "talebi aynı stoktan karşılanıyor.\n\n"
            "⚠️ Varsayılan 0 ve bu bilinçli: MRP hiç koşmamışsa stok kararı "
            "bugüne kadarki davranışını birebir sürdürür. Alanın eklenmesi tek "
            "başına hiçbir sayıyı oynatmıyor."
        ),
    )

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

    # --- AlanOzellikleri sözleşmesi -------------------------------------

    @property
    def gorunen_ad(self) -> str:
        return self.sku_adi

    def maskelenecek_alanlar(self) -> list[str]:
        return [self.sku_adi, self.sku_id, self.tedarikci_adi, self.tedarikci_id]

    def hesaplanan_sayilar(self) -> dict[str, float]:
        return {
            "kullanilabilir_stok": float(self.kullanilabilir_stok),
            "talep_varyasyon_katsayisi": self.talep_varyasyon_katsayisi,
        }

    def oto_uygulama_engeli(self) -> str | None:
        return None if self.tedarikci_onayli else "TEDARIKCI_ONAYSIZ"


class FinansOzellikleri(AlanOzellikleri):
    """Bir müşterinin alacak/tahsilat durumu — Faz 6, Finans & Tahsilat.

    `StockFeatures` ile bilinçli olarak **aynı iskelet**: kimlik, durum,
    davranış profili (ortalama + sapma + veri günü), sınıflandırma + hedef,
    hareketsizlik, para, karşı taraf, bağlam. Aynı iskelet, aynı kural
    motoru kalıbını taşımayı mümkün kılıyor.

    ⚠️ `ABCSinifi` ve `XYZSinifi` yeniden kullanılıyor, yenisi
    tanımlanmıyor:

    · **ABC** stokta ciro katkısıydı; burada da ciro katkısı — aynı anlam.
    · **XYZ** stokta talep oynaklığıydı; burada **ödeme gecikmesi
      oynaklığı**. Aynı soru: bu kalem tahmin edilebilir mi? Düzenli geç
      ödeyen bir müşteri (hep 40 gün) rastgele ödeyenden (10-90 gün arası)
      daha az risklidir, ortalaması kötü olsa bile.

    Bu, mimarinin taşınabilirlik sınavıydı ve geçti: sınıflandırma
    makinesi alan değiştirince yeniden yazılmadı.
    """

    # Kimlik
    musteri_id: str
    musteri_adi: str
    segment: str = Field(description="Sektör/kanal — stoktaki `kategori`nin karşılığı")

    # Alacak durumu
    toplam_alacak_tl: float = Field(ge=0)
    vadesi_gecen_tl: float = Field(ge=0, description="Vadesi dolmuş, tahsil edilmemiş")
    en_eski_gecikme_gun: int = Field(ge=0, description="En eski açık faturanın gecikmesi")

    # Ödeme davranışı profili
    ort_odeme_gecikmesi_gun: float = Field(ge=0)
    odeme_gecikmesi_std: float = Field(ge=0)
    veri_gun_sayisi: int = Field(
        ge=0, description="Kaç günlük geçmişe dayanıyor — güven skorunu besler"
    )

    # Kredi
    kredi_limiti_tl: float = Field(ge=0)

    # Sınıflandırma ve hedef
    abc_sinifi: ABCSinifi
    xyz_sinifi: XYZSinifi
    hedef_tahsilat_orani: float = Field(
        gt=0, lt=1, description="ABC/XYZ matrisinden türetilir — stoktaki servis seviyesi gibi"
    )

    # Hareketsizlik
    son_odeme_gun_once: int = Field(ge=0)

    # Geçmiş performans
    tahsilat_orani: float = Field(ge=0, le=1, description="Geçmişte tahsil edilen / fatura edilen")

    # Karşı taraf
    musteri_kredi_onayli: bool = Field(description="Eşikli otonomi ön koşulu")

    # Bağlam
    olcum_tarihi: date

    @property
    def limit_asimi_tl(self) -> float:
        """Kredi limitinin üstüne çıkılan tutar. Aşım yoksa 0.

        `kullanilabilir_stok`'un karşılığı: ham alanlardan türeyen, kararın
        özünü taşıyan sayı.
        """
        return max(0.0, self.toplam_alacak_tl - self.kredi_limiti_tl)

    @property
    def gecikme_varyasyon_katsayisi(self) -> float:
        """σ/μ — XYZ sınıflandırmasının dayanağı. Gecikme yoksa 0.

        Stoktaki `talep_varyasyon_katsayisi` ile birebir aynı formül ve
        aynı iş: bu müşterinin ödeme davranışı tahmin edilebilir mi?
        """
        if self.ort_odeme_gecikmesi_gun <= 0:
            return 0.0
        return self.odeme_gecikmesi_std / self.ort_odeme_gecikmesi_gun

    @property
    def vadesi_gecen_orani(self) -> float:
        """Alacağın ne kadarı gecikmede. Alacak yoksa 0."""
        if self.toplam_alacak_tl <= 0:
            return 0.0
        return self.vadesi_gecen_tl / self.toplam_alacak_tl

    # --- AlanOzellikleri sözleşmesi -------------------------------------

    @property
    def gorunen_ad(self) -> str:
        return self.musteri_adi

    def maskelenecek_alanlar(self) -> list[str]:
        return [self.musteri_adi, self.musteri_id]

    def hesaplanan_sayilar(self) -> dict[str, float]:
        return {
            "limit_asimi_tl": self.limit_asimi_tl,
            "gecikme_varyasyon_katsayisi": self.gecikme_varyasyon_katsayisi,
            "vadesi_gecen_orani": self.vadesi_gecen_orani,
        }

    def oto_uygulama_engeli(self) -> str | None:
        return None if self.musteri_kredi_onayli else "MUSTERI_KREDI_ONAYSIZ"


class UretimOzellikleri(AlanOzellikleri):
    """Üretilen bir kalemin üretim planı durumu — Faz 10, Üretim Planlama.

    Diğer iki alanla **aynı iskelet**: kimlik, durum, davranış profili,
    sınıflandırma + hedef, para, karşı taraf (burada üretim hattı), bağlam.
    Üçüncü kez taşındı ve yine yeniden yazılmadı.

    ## ⚠️ Tahmin neden nesne değil, düz sayılar

    Talep tahmini `app/forecast/contracts.py::TalepTahmini` ile üretiliyor
    ama buraya **düzleştirilmiş** giriyor. İki sebep:

    1. **Katman yönü.** `app/contracts.py` en alttaki sözleşme; buradan
       `app.forecast`'e bağımlılık, alan katmanının altına bir modül
       katmanı sokardı. Alan tahmini *çağırır*, sözleşme onu *içermez*.
    2. **Guard.** `izinli_sayilar()` yalnızca düz sayıları görüyor. İç içe
       bir nesnenin alanları `model_dump()`'ta sözlük olarak çıkar ve
       guard onları sayıya çeviremez; gerekçe "14 günde 42 adet" diyemezdi.

    ## ⚠️ Neden üç tahmin alanı birden

    `tahmin_toplam` tek başına yeterli değil ve bu ölçülmüş bir sonuç:
    kataloğun %76'sı aralıklı talepli, orada nokta tahmini dar bir aralığa
    güven vermiyor. Emniyet payı `tahmin_ust_band`'a bakarak seçilmeli
    (bkz. `app/forecast/olcum.py::TOPLAM_UYARISI`). `tahmin_yontemi` de
    süs değil: hangi modelin ürettiği kayıtlı olmazsa "tahmin iyileşti mi"
    sorusu sonradan cevaplanamaz.
    """

    # Kimlik
    kalem_id: str
    kalem_adi: str
    kategori: str

    # Stok durumu
    eldeki_stok: int = Field(ge=0)
    rezerve_stok: int = Field(ge=0, description="Satılmış ama sevk edilmemiş")
    acik_emir_miktari: int = Field(
        ge=0,
        description=(
            "Üretim emri açılmış, henüz tamamlanmamış miktar. Stoktaki "
            "`yoldaki_stok`'un karşılığı — hesaba katılmazsa üst üste emir açılır."
        ),
    )

    # Talep tahmini (app/forecast çıktısından düzleştirilmiş)
    tahmin_toplam: float = Field(ge=0, description="Ufuk boyunca beklenen toplam talep")
    tahmin_alt_band: float = Field(ge=0, description="Kötümser senaryo — ufuk toplamı")
    tahmin_ust_band: float = Field(ge=0, description="İyimser senaryo — ufuk toplamı")
    tahmin_yontemi: str = Field(description="Tahmini üreten modelin adı")
    tahmin_ufuk_gun: int = Field(gt=0, description="Tahminin kapsadığı gün sayısı")
    veri_gun_sayisi: int = Field(
        ge=0, description="Kaç günlük geçmişe dayanıyor — güven skorunu besler"
    )

    # Üretim profili
    hat_id: str = Field(description="Kalemin üretildiği hat")
    hat_adi: str
    parti_buyuklugu: int = Field(gt=0, description="Emir bu sayının katı olmalı")
    asgari_parti: int = Field(ge=0, description="Bundan küçük emir açmak ekonomik değil")
    hazirlik_suresi_saat: float = Field(
        ge=0, description="Hattı bu kaleme geçirmenin sabit süresi (setup)"
    )
    birim_islem_suresi_saat: float = Field(gt=0, description="Bir adedin hattaki süresi")
    uretim_suresi_gun: float = Field(
        gt=0,
        description=(
            "Emir açıldıktan kaç gün sonra mal elde olur. Stoktaki "
            "`tedarik_suresi_gun`'ün karşılığı."
        ),
    )
    hat_gunluk_kapasite_saat: float = Field(
        gt=0,
        description=(
            "Hattın günlük çalışma süresi. ⚠️ Kalemin değil HATTIN özelliği; "
            "aynı hatta koşan her kalemde aynı sayı görünür. Kalem "
            "özelliğine taşınmasının sebebi kapasite kararının kalem bazında "
            "onaylanması: 'hat dolu' hükmü tek tek emirlere düşüyor, hatta "
            "değil (bkz. Adım 4'ün kapsam notu — çizelge kurmuyoruz)."
        ),
    )

    # Sınıflandırma ve hedef
    abc_sinifi: ABCSinifi
    xyz_sinifi: XYZSinifi
    hedef_servis_seviyesi: float = Field(gt=0, lt=1)

    # Para
    birim_maliyet_tl: float = Field(ge=0)
    satis_fiyati_tl: float = Field(ge=0)

    # Bağlam
    olcum_tarihi: date

    @property
    def kullanilabilir_stok(self) -> int:
        """Rezerve düşülmüş, gerçekten satılabilir stok."""
        return self.eldeki_stok - self.rezerve_stok

    @property
    def net_pozisyon(self) -> int:
        """Elde + açık emirler. Emir kararının karşılaştırdığı sol taraf.

        ⚠️ Açık emri saymamak, stoktaki "yoldaki stoğu unutup üst üste
        sipariş verme" hatasının üretim karşılığı olurdu.
        """
        return self.kullanilabilir_stok + self.acik_emir_miktari

    @property
    def tahmin_bant_genisligi(self) -> float:
        """Üst bant − alt bant. Belirsizliğin büyüklüğü.

        Aralıklı talepli kalemlerde geniş olacak; bu kusur değil, dürüstlük
        (bkz. `app/forecast/aralikli.py`).
        """
        return self.tahmin_ust_band - self.tahmin_alt_band

    # --- AlanOzellikleri sözleşmesi -------------------------------------

    @property
    def gorunen_ad(self) -> str:
        return self.kalem_adi

    def maskelenecek_alanlar(self) -> list[str]:
        return [self.kalem_adi, self.kalem_id, self.hat_adi, self.hat_id]

    def hesaplanan_sayilar(self) -> dict[str, float]:
        return {
            "kullanilabilir_stok": float(self.kullanilabilir_stok),
            "net_pozisyon": float(self.net_pozisyon),
            "tahmin_bant_genisligi": self.tahmin_bant_genisligi,
        }

    def oto_uygulama_engeli(self) -> str | None:
        """Üretimde oto-uygulamayı engelleyen tek durum: tahmin dayanaksız.

        ⚠️ Stokta engel "tedarikçi onaylı değil", finansta "kredi onaysız"
        — ikisi de **karşı tarafla** ilgili. Üretimde karşı taraf yok;
        fabrika bizim. O yüzden engel de başka bir yerden gelmek zorunda ve
        tek makul yer tahminin kendisi: yeterli geçmişi olmayan bir kalem
        için üretim emrini insan görmeden açmak, ölçülmemiş bir sayıya
        makine hızında para bağlamaktır.
        """
        if self.veri_gun_sayisi < ASGARI_TAHMIN_GECMIS_GUN:
            return "TAHMIN_GECMISI_YETERSIZ"
        return None


ASGARI_TAHMIN_GECMIS_GUN = 90
"""Bu kadar günlük geçmişi olmayan kalemde üretim emri oto-uygulanmaz.

90 gün seçildi: haftalık desenin on üç kez tekrar ettiği, mevsim geçişinin
ise henüz görülmediği en kısa pencere. Daha kısası tek bir kampanya
dönemini tüm yılın normali sanmaya açık.

⚠️ Bu bir **eşik**, kapı değil: karar yine üretilir ve onay kuyruğuna
düşer. Karar üretmemek, "bilmiyoruz" bilgisini de yok etmek olurdu."""


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
        # Faz 6 · finans oranları — gerekçede "%38 gecikmede" diye yazılır.
        "hedef_tahsilat_orani",
        "tahsilat_orani",
        "vadesi_gecen_orani",
        "gecikme_varyasyon_katsayisi",
        # ⚠️ SÖZLEŞME DEĞİŞİKLİĞİ (2026-08-06) — Kişi A yaptı, **Kişi B onayladı**
        # (contracts.py donmuş dosya, tek taraflı değiştirilmez — bkz.
        # YOL-HARITASI.md, Rol dağılımı). B ayrıca bağımsız doğruladı ve dar
        # kapsamı test etti: iskonto %15 iken "20"/"30" hâlâ reddediliyor.
        #
        # `onerilen_iskonto_orani` bu listeye hiç eklenmemişti; docstring'in
        # "unutulursa" senaryosu tam olarak gerçekleşti. Sonuç: tasfiye
        # kararlarında model, kararın ÖZÜ olan iskonto oranını doğal Türkçeyle
        # ("%15") yazamıyordu — yalnızca "0,15" izinliydi.
        #
        # Kanıt (B'nin tam taraması): `data/egitim/gerekce_train.jsonl`'deki
        # 10.000 tasfiye hedefinin **10.000'i** — üç oranın (0,15/0,30/0,50)
        # tamamı — yüzde olarak yazılmış ve hepsi `guard_sonucu: gecti` ile
        # üretilmiş. Yani veri, bu alanın ×100 karşılığının izinli OLDUĞU bir
        # sürümle doğrulanmış. Sonradan ayrışmış.
        # (Ayrıntı: dokumantasyon/OLCUMLER.md, 2. turun kök nedeni.)
        "onerilen_iskonto_orani",
    }
)
"""Yüzde olarak da yazılabilen oran alanları. Adı burada olmayan bir alan için
×100 karşılığı ÜRETİLMEZ. Bu liste bilinçli olarak açık: koşulu değere göre
kurmak (0-1 aralığı) adet/gün alanlarını da yakalıyordu —
`son_hareket_gun_once=1` olan bir ürün için "%100" izinli hale geliyordu.

Yeni bir oran alanı eklenirse (`FiredRule.degerler` içinde veya
`StockFeatures`'a) buraya da eklenmeli. Unutulursa sonuç GÜVENLİ tarafa
düşer: yüzdesi izinli olmaz, guard reddeder, gerekçe şablona düşer — karar
hiçbir koşulda bloke olmaz, yalnızca o cümle yazılamaz.

⚠️ Buraya alan eklemek guard'ı **genişletir**. Genişleme dar kapsamlı:
yalnızca o alanın kendi değerinin ×100'ü izinli olur. İskonto gerçekte
%20 iken modelin "%15" demesi hâlâ reddedilir."""


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
    # ⚠️ Faz 6'da BİRLEŞİM oldu. Önceden `StockFeatures`'a çakılıydı ve
    # `Alan` enum'ında FINANS/SATIS/URETIM tanımlı olmasına rağmen ikinci bir
    # alan eklenemiyordu. Yeni alan eklerken buraya da eklenmeli.
    #
    # Pydantic "smart" birleşim kipinde örneğin gerçek tipi korunuyor; iki
    # sınıfın zorunlu alanları ayrık olduğu için ayrım belirsiz değil.
    ozellikler: StockFeatures | FinansOzellikleri | UretimOzellikleri

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
        # ⚠️ Hesaplanan property'ler `model_dump()`'ta görünmez; alanın
        # kendisi bildiriyor (bkz. `AlanOzellikleri.hesaplanan_sayilar`).
        # Önceden iki stok property'si burada elle yazılıydı — finans
        # eklendiğinde onun türetilmiş sayıları sessizce izinsiz kalırdı.
        for ad, deger in self.ozellikler.hesaplanan_sayilar().items():
            ekle(deger, ad)

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
