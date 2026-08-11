"""Kapasite kısıtı — hat dolduğunda hangi emir ertelenir.

Sahip: Kişi A · Faz 10 A10.3 (Adım 4)

## ⚠️ Bu modül ÇİZELGE KURMUYOR

Vardiya planlama ve iş sırası optimizasyonu **kapsam dışı** ve bu teknik bir
eksiklik değil, mimari bir karar. Sistemin otonomi modeli kalem bazında insan
onayına dayanıyor: her karar tek tek onaylanabilir, reddedilebilir,
gerekçesi okunabilir. "Tüm fabrikayı optimize et" çıktısı bu modele
sığmıyor — tek bir çizelgeyi onaylamak, içindeki yüzlerce örtük kararı
görmeden onaylamak olurdu.

Bu modül bunun yerine kısıtı **görünür kılıyor**: hat dolduğunda hangi
emirlerin sığmadığını söylüyor ve en az aciliyeti olanı ertelemeyi öneriyor.
Kararın kendisi yine kalem bazında ve yine onaylanabilir.

## Öncelik neye göre

Ertelenecek emir, **stoğu en uzun süre yetecek** olan. Ölçüt "kapsama günü":

    kapsama_gun = net_pozisyon / günlük tahmin

Sezgisel karşılığı: elimizdeki mal kaç gün daha yeter. 2 gün yeten kalemi
ertelemek stoksuzluk demek; 40 gün yeteni ertelemek yalnızca emri öteler.

⚠️ Ölçüt olarak **tutar** kullanmak cazip ve yanlış olurdu: pahalı bir
kalemin stoğu bitmek üzereyken ucuz bir kalem için hat açık tutulurdu. Para
buradaki sorunun ölçüsü değil; sorun zaman.
"""

from __future__ import annotations

from app.contracts import (
    Alan,
    DecisionCandidate,
    FiredRule,
    KararTipi,
    UretimOzellikleri,
)
from app.core.isletme_profili import UretimProfili, profil

KURAL_SURUMU = "1.0-kapasite"

SONSUZ_KAPSAMA_GUN = 10_000.0
"""Talep tahmini 0 olan kalemin kapsaması "sonsuz" sayılıyor.

Bölme tanımsız ve doğru cevap açık: hiç satmayan bir kalem için hat
tutmak, ertelenecek ilk şeydir. Sonsuz yerine büyük bir sayı kullanmak,
sıralamanın `inf` ile karşılaşınca kararsız kalmasını önlüyor."""


def kapasite_saat(ozellik: UretimOzellikleri, uretim_profili: UretimProfili) -> float:
    """Hattın ufuk boyunca kullanılabilir süresi.

    ⚠️ Hedef kullanım oranı (%85) burada çarpan olarak giriyor, sonradan
    kontrol edilen bir eşik olarak değil. Sebebi: %100 dolu bir hat, tek bir
    gecikmede tüm planı kaydırır. Payı baştan ayırmak, "kapasite aşıldı mı"
    sorusunu doğru yerden sordurtuyor.

    ⚠️ Pencere **planlama ufku**, takvim haftası değil. Emirler ufka göre
    üretiliyor; kapasiteyi haftaya bölmek, emirle kapasiteyi iki farklı
    zaman ölçeğinde karşılaştırmak olurdu.
    """
    return (
        ozellik.hat_gunluk_kapasite_saat
        * uretim_profili.hedef_kapasite_kullanimi
        * uretim_profili.planlama_ufku_gun
    )


def kapsama_gun(ozellik: UretimOzellikleri) -> float:
    """Eldeki mal kaç gün daha yeter — erteleme önceliğinin ölçütü."""
    gunluk = ozellik.tahmin_toplam / ozellik.tahmin_ufuk_gun
    if gunluk <= 0:
        return SONSUZ_KAPSAMA_GUN
    return ozellik.net_pozisyon / gunluk


def _emir_yuku(karar: DecisionCandidate) -> float:
    return float(karar.aksiyon.get("hat_yuku_saat") or 0.0)


def _uretim_ozelligi(karar: DecisionCandidate) -> UretimOzellikleri:
    """Kararın üretim özelliklerini tip güvenli okur.

    ⚠️ `assert` kullanılmıyor: `python -O` altında assert'ler siliniyor ve
    tip daraltması sessizce kayboluyor. Üretim kodunda tip kontrolü assert'e
    bırakılmaz.
    """
    if not isinstance(karar.ozellikler, UretimOzellikleri):
        raise TypeError(f"{karar.tip.value} üretim kararı değil — kapasite sorusu sorulamaz.")
    return karar.ozellikler


def kapasite_kararlari_uret(
    emirler: list[DecisionCandidate],
    uretim_profili: UretimProfili | None = None,
) -> list[DecisionCandidate]:
    """Açılması önerilen emirleri hat hat sınar, sığmayanlar için karar üretir.

    Girdi **yalnızca `uretim.emir_ac` kararları** olmalı; diğer tipler
    sessizce atlanıyor. Aksiyon yok kararının hatta yükü olmadığı için
    kapasite sorusu da yok.

    Dönen liste, `ozellikten_kararlar_uret`'in çıktısına **eklenir**,
    onun yerine geçmez: bir kalem için hem "emir aç" hem "hat dolu" aynı
    anda doğru olabilir ve ikisi ayrı ayrı onaylanmalı. Finansta bu ders
    pahalıya öğrenildi — ortogonal kollar `elif` zincirine sokulunca biri
    diğerini sessizce susturuyordu (BILINEN-EKSIKLER §9).
    """
    p = uretim_profili or profil().uretim

    hat_bazinda: dict[str, list[DecisionCandidate]] = {}
    for karar in emirler:
        if karar.tip is not KararTipi.URETIM_EMIR_AC:
            continue
        if not isinstance(karar.ozellikler, UretimOzellikleri):
            continue
        hat_bazinda.setdefault(karar.ozellikler.hat_id, []).append(karar)

    sonuc: list[DecisionCandidate] = []
    for hat_id, hat_emirleri in sorted(hat_bazinda.items()):
        sonuc += _tek_hat(hat_id, hat_emirleri, p)
    return sonuc


def _tek_hat(
    hat_id: str, emirler: list[DecisionCandidate], p: UretimProfili
) -> list[DecisionCandidate]:
    kapasite = kapasite_saat(_uretim_ozelligi(emirler[0]), p)
    toplam_yuk = sum(_emir_yuku(k) for k in emirler)
    if toplam_yuk <= kapasite:
        return []

    # En az acil olan önce ertelenir: kapsama günü büyükten küçüğe.
    #
    # ⚠️ Eşitlik `kalem_id` ile kırılıyor, `karar_id` ile DEĞİL. İlk sürüm
    # `karar_id` kullanıyordu ve bu sessiz bir kusurdu: o alan her karar
    # üretiminde yeniden atanan rastgele bir UUID, yani aynı fabrika durumu
    # iki kez hesaplandığında farklı emirler ertelenirdi.
    #
    # Kusuru çizelge modülünün tekrarlanabilirlik testi yakaladı; buradaki
    # test aynı listeyi iki kez verdiği için görmemişti.
    sirali = sorted(
        emirler,
        key=lambda k: (-kapsama_gun(_uretim_ozelligi(k)), _uretim_ozelligi(k).kalem_id),
    )

    kararlar: list[DecisionCandidate] = []
    kalan_yuk = toplam_yuk
    for karar in sirali:
        if kalan_yuk <= kapasite:
            break
        ozellik = _uretim_ozelligi(karar)
        yuk = _emir_yuku(karar)
        asim = kalan_yuk - kapasite
        kararlar.append(_kapasite_karari(ozellik, karar, kapasite, kalan_yuk, asim, hat_id))
        kalan_yuk -= yuk

    return kararlar


def _kapasite_karari(
    ozellik: UretimOzellikleri,
    emir: DecisionCandidate,
    kapasite: float,
    toplam_yuk: float,
    asim: float,
    hat_id: str,
) -> DecisionCandidate:
    miktar = emir.aksiyon.get("emir_miktari")
    kalan = kapsama_gun(ozellik)
    kurallar = [
        FiredRule(
            kod="HAT_KAPASITESI_ASILDI",
            aciklama=(
                f"{ozellik.hat_adi} için önerilen emirlerin toplam yükü "
                f"{toplam_yuk:.1f} saat; kullanılabilir kapasite {kapasite:.1f} saat."
            ),
            degerler={
                "toplam_yuk_saat": round(toplam_yuk, 2),
                "kapasite_saat": round(kapasite, 2),
                "asim_saat": round(asim, 2),
            },
        ),
        FiredRule(
            kod="ERTELEME_ONCELIGI",
            aciklama=(
                f"Eldeki mal {kalan:.0f} gün daha yetiyor; hattaki diğer emirler "
                f"daha acil olduğu için bu emir erteleniyor."
            ),
            degerler={
                "kapsama_gun": round(min(kalan, SONSUZ_KAPSAMA_GUN), 2),
                "hat_yuku_saat": round(_emir_yuku(emir), 2),
            },
        ),
    ]

    return DecisionCandidate(
        alan=Alan.URETIM,
        tip=KararTipi.URETIM_KAPASITE_ASIMI,
        aksiyon={
            "ertelenen_miktar": miktar,
            "hat_id": hat_id,
            "asim_saat": round(asim, 2),
        },
        # ⚠️ Tutar, ertelenen emrin değeri — sıfır değil. Politika motoru
        # riski tutardan hesaplıyor; ertelemeyi "bedelsiz" göstermek, büyük
        # bir emri ertelemeyi küçük bir emri ertelemekle aynı risk sınıfına
        # sokardı.
        tahmini_tutar_tl=emir.tahmini_tutar_tl,
        geri_alinabilir=True,
        guven=emir.guven,
        tetiklenen_kurallar=kurallar,
        ozellikler=ozellik,
        model_surumleri={"rules": KURAL_SURUMU, "tahmin": ozellik.tahmin_yontemi},
    )


__all__ = [
    "KURAL_SURUMU",
    "kapasite_kararlari_uret",
    "kapasite_saat",
    "kapsama_gun",
]
