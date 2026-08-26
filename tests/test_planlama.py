"""Genel planlama motoru (`app/planlama/**`) — Faz 11.

⚠️ Buradaki en önemli test `test_URETIM_VE_NAKLIYE_ayni_fonksiyonu_cagiriyor`.
"Genel motor" iddiası ancak ikinci bir alanla kanıtlanır; tek kullanıcısı olan
bir motor genel değil, yalnızca soyutlanmıştır.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.planlama.contracts import AtamaGerekcesi, Is, Kaynak, KaynakPlani, PlanSatiri
from app.planlama.olcut import OLCUTLER, olcut_al
from app.planlama.tanim import (
    AlanTanimi,
    IslerKaynagi,
    TanimHatasi,
    alan_tanimi_dosyadan,
    alan_tanimi_oku,
    dosyadan_yukle,
    tanimdan_yukle,
)
from app.planlama.yerlestirme import plan_kur

BUGUN = date(2026, 8, 11)
NAKLIYE = Path(__file__).resolve().parents[1] / "ornekler" / "nakliye.json"


def kaynak(kaynak_id: str = "K1", kapasite: float = 8.0) -> Kaynak:
    return Kaynak(kaynak_id=kaynak_id, ad=f"Kaynak {kaynak_id}", gunluk_kapasite=kapasite)


def is_(is_id: str = "I1", yuk: float = 2.0, oncelik: float = 1.0, **kw) -> Is:
    kw.setdefault("kaynak_id", "K1")
    return Is(is_id=is_id, ad=f"İş {is_id}", yuk=yuk, oncelik=oncelik, **kw)


# --- Sözleşme ----------------------------------------------------------------


def test_kapasitesiz_kaynak_KURULUM_ANINDA_patliyor():
    """Kapasitesiz kaynağa iş verilemez; hata plan koşarken değil burada."""
    with pytest.raises(ValueError, match="kapasite"):
        Kaynak(kaynak_id="K1", ad="Boş", gunluk_kapasite=0)


def test_kaynaksiz_is_KURULUM_ANINDA_patliyor():
    """⚠️ Ne atanmış ne uygun kaynağı olan iş hiçbir yere yerleşemez.

    Sessizce kabul edilseydi plan koşar, iş görünmez ve "yapılacak bir şey
    yok" izlenimi doğardı.
    """
    with pytest.raises(ValueError, match="kaynak"):
        Is(is_id="I1", ad="Sahipsiz", yuk=1.0, oncelik=1.0)


def test_yuksuz_is_reddediliyor():
    with pytest.raises(ValueError, match="yük"):
        is_(yuk=0.0)


def test_kaynak_adaylari_iki_kipi_de_veriyor():
    """Üretim kipi: atanmış. Nakliye kipi: seçilecek."""
    assert is_(kaynak_id="K1").kaynak_adaylari() == ("K1",)
    assert is_(kaynak_id=None, uygun_kaynaklar=("K1", "K2")).kaynak_adaylari() == ("K1", "K2")


# --- Yerleştirme -------------------------------------------------------------


def test_is_EN_BOS_kaynaga_atanıyor():
    """⭐ "Şu araç şuraya gidebilir" — atamanın kendisi karar.

    Dört eşit iş, iki eşit kaynak: ikiye ikiye bölünmeli. Hepsi ilk kaynağa
    yığılırsa atama yapılmıyor, yalnızca listenin ilki seçiliyor demektir.
    """
    kaynaklar = [kaynak("K1"), kaynak("K2")]
    isler = [
        is_(f"I{n}", yuk=2.0, oncelik=n, kaynak_id=None, uygun_kaynaklar=("K1", "K2"))
        for n in range(4)
    ]

    planlar = plan_kur(isler, kaynaklar, ufuk_gun=5, baslangic=BUGUN)

    assert [len(p.satirlar) for p in planlar] == [2, 2]


def test_atama_KAPASITE_ORANINA_bakiyor_mutlak_yuke_degil():
    """⚠️ Günde 24 saat çalışan kaynak, 8 saatlikten daha fazla yük taşır.

    Mutlak yüke bakmak büyük kaynağı haksız yere "dolu" gösterir ve işler
    küçük kaynağa yığılır.
    """
    kaynaklar = [kaynak("BUYUK", 24.0), kaynak("KUCUK", 4.0)]
    isler = [
        is_(f"I{n}", yuk=2.0, oncelik=n, kaynak_id=None, uygun_kaynaklar=("BUYUK", "KUCUK"))
        for n in range(6)
    ]

    planlar = {p.kaynak_id: p for p in plan_kur(isler, kaynaklar, ufuk_gun=1, baslangic=BUGUN)}

    assert len(planlar["BUYUK"].satirlar) > len(planlar["KUCUK"].satirlar)


def test_gune_sigmayan_is_ERTESI_GUNE_tasiyor():
    planlar = plan_kur([is_(yuk=12.0)], [kaynak(kapasite=8.0)], ufuk_gun=5, baslangic=BUGUN)
    satir = planlar[0].satirlar[0]

    assert satir.gun_sayisi == 2
    assert satir.baslangic == BUGUN


def test_bolunemez_is_GUN_BASINA_tasiniyor():
    """Fırın bir kez yakılır; 5 saatlik bölünemez iş 3 saatlik boşluğa girmez."""
    kaynaklar = [kaynak(kapasite=8.0)]
    isler = [
        is_("DOLDURAN", yuk=5.0, oncelik=1),
        is_("BOLUNEMEZ", yuk=5.0, oncelik=2, bolunebilir=False),
    ]

    planlar = plan_kur(isler, kaynaklar, ufuk_gun=5, baslangic=BUGUN)
    yerler = {s.is_id: s for s in planlar[0].satirlar}

    assert yerler["BOLUNEMEZ"].gun_sayisi == 1, "bolunemez is gune yayilmis"
    assert yerler["BOLUNEMEZ"].baslangic > yerler["DOLDURAN"].baslangic


def test_bolunemez_ve_GUNE_HIC_SIGMAYAN_is_plana_girmiyor():
    """⚠️ Günde 8 saat çalışan kaynakta 20 saatlik bölünemez iş yapılamaz.

    Güne yaymak "yetişecek" demek olurdu; sahada uygulanamaz bir plan.
    """
    planlar = plan_kur(
        [is_(yuk=20.0, bolunebilir=False)], [kaynak(kapasite=8.0)], ufuk_gun=10, baslangic=BUGUN
    )

    assert not planlar[0].satirlar
    assert len(planlar[0].sigmayanlar) == 1


def test_ufka_sigmayan_is_KAYBOLMUYOR():
    """Plana koymamak iptal etmek değil; kullanıcı neyin dışarıda kaldığını görmeli."""
    planlar = plan_kur([is_(yuk=50.0)], [kaynak(kapasite=8.0)], ufuk_gun=2, baslangic=BUGUN)

    assert not planlar[0].satirlar
    assert planlar[0].sigmayanlar[0].is_id == "I1"


def test_tanimsiz_kaynaga_isaret_eden_is_PLANI_DURDURUYOR():
    """⚠️ Sessizce atlamak, eksikliği görünmez kılardı. Bu bir tanım hatası."""
    with pytest.raises(ValueError, match="kaynağı tanımlı değil"):
        plan_kur([is_(kaynak_id="YOK")], [kaynak("K1")], ufuk_gun=5, baslangic=BUGUN)


def test_kaynaklar_PARALEL_isliyor():
    kaynaklar = [kaynak("K1"), kaynak("K2")]
    isler = [is_("I1", kaynak_id="K1"), is_("I2", kaynak_id="K2")]

    planlar = plan_kur(isler, kaynaklar, ufuk_gun=5, baslangic=BUGUN)

    assert all(p.satirlar[0].baslangic == BUGUN for p in planlar)


def test_plan_TEKRARLANABILIR():
    """⚠️ Aynı girdi aynı plan. Eşitlik `is_id` ile kırılıyor.

    Üretim tarafında bu bir kez `karar_id` (rastgele UUID) ile yapıldı ve
    aynı fabrika durumu iki farklı plan üretiyordu.
    """
    kaynaklar = [kaynak("K1"), kaynak("K2")]
    isler = [
        is_(f"I{n}", yuk=2.0, oncelik=1.0, kaynak_id=None, uygun_kaynaklar=("K1", "K2"))
        for n in range(6)
    ]

    ilk = plan_kur(isler, kaynaklar, ufuk_gun=5, baslangic=BUGUN)
    ikinci = plan_kur(list(reversed(isler)), kaynaklar, ufuk_gun=5, baslangic=BUGUN)

    assert [[s.is_id for s in p.satirlar] for p in ilk] == [
        [s.is_id for s in p.satirlar] for p in ikinci
    ], "girdi sirasi plani degistiriyor"


# --- Ölçüt -------------------------------------------------------------------


def test_olcut_degisince_SIRA_degisiyor():
    """⭐ "İyi plan" tanımı değişince plan da değişmeli; yoksa ölçüt süs."""
    kaynaklar = [kaynak(kapasite=100.0)]
    isler = [
        is_("BUYUK_ACIL", yuk=10.0, oncelik=1),
        is_("KUCUK_BEKLER", yuk=1.0, oncelik=9),
    ]

    acil = plan_kur(isler, kaynaklar, "en_acil", ufuk_gun=5, baslangic=BUGUN)
    cok_is = plan_kur(isler, kaynaklar, "en_cok_is", ufuk_gun=5, baslangic=BUGUN)

    assert acil[0].satirlar[0].is_id == "BUYUK_ACIL"
    assert cok_is[0].satirlar[0].is_id == "KUCUK_BEKLER"


def test_en_degerli_olcutu_TUTARA_bakiyor():
    """Tutar etikette taşınıyor: motorun sözleşmesinde para alanı yok."""
    kaynaklar = [kaynak(kapasite=100.0)]
    isler = [
        is_("UCUZ", oncelik=1, etiketler={"tutar": "100"}),
        is_("PAHALI", oncelik=9, etiketler={"tutar": "50000"}),
    ]

    plan = plan_kur(isler, kaynaklar, "en_degerli", ufuk_gun=5, baslangic=BUGUN)

    assert plan[0].satirlar[0].is_id == "PAHALI"


def test_tutarsiz_isde_en_degerli_PATLAMIYOR():
    kaynaklar = [kaynak(kapasite=100.0)]
    plan = plan_kur([is_()], kaynaklar, "en_degerli", ufuk_gun=5, baslangic=BUGUN)
    assert plan[0].satirlar


def test_bilinmeyen_olcut_SESSIZCE_VARSAYILANA_dusmuyor():
    """⚠️ Yazım hatası olan bir çağrı, istediği ölçütü aldığını sanmamalı."""
    with pytest.raises(KeyError, match="Bilinmeyen ölçüt"):
        olcut_al("en_hizli")


def test_tum_olcutler_calisir_durumda():
    kaynaklar = [kaynak(kapasite=100.0)]
    for ad in OLCUTLER:
        plan = plan_kur([is_()], kaynaklar, ad, ufuk_gun=5, baslangic=BUGUN)
        assert plan[0].satirlar, f"{ad} plan uretemedi"


# --- Alan tanımı (JSON) ------------------------------------------------------


def test_tanimdan_plan_KOD_YAZMADAN_cikiyor():
    """⭐ "Yeni alan = bir dosya, kod yok" iddiasının testi."""
    tanim = {
        "kaynaklar": [{"id": "M1", "ad": "Makine 1", "gunluk_kapasite": 8}],
        "isler": [{"id": "J1", "ad": "Parti A", "yuk": 3, "oncelik": 1, "kaynak_id": "M1"}],
    }
    kaynaklar, isler = tanimdan_yukle(tanim)
    plan = plan_kur(isler, kaynaklar, ufuk_gun=5, baslangic=BUGUN)

    assert plan[0].satirlar[0].ad == "Parti A"


def test_tanimda_eksik_alan_YUKLEME_ANINDA_patliyor():
    """⚠️ `kapasite` yazıp `gunluk_kapasite` demeyi unutan tanım sessizce
    varsayılanla çalışırsa kimse fark etmez ve plan yanlış çıkar."""
    with pytest.raises(TanimHatasi, match="zorunlu alan eksik"):
        tanimdan_yukle({"kaynaklar": [{"id": "M1", "ad": "M", "kapasite": 8}], "isler": []})


def test_tanimda_olmayan_kaynak_YUKLEME_ANINDA_patliyor():
    with pytest.raises(TanimHatasi, match="tanımlı olmayan kaynak"):
        tanimdan_yukle(
            {
                "kaynaklar": [{"id": "M1", "ad": "M", "gunluk_kapasite": 8}],
                "isler": [{"id": "J1", "ad": "J", "yuk": 1, "oncelik": 1, "kaynak_id": "M9"}],
            }
        )


def test_bilinmeyen_alanlar_ETIKET_olarak_tasiniyor():
    """⚠️ Profildeki `extra="forbid"` kuralının TERSİ ve bilinçli.

    Profil kapalı bir küme (iş parametreleri); alan tanımı açık bir küme —
    nakliyede "plaka", vardiyada "departman" tanımda yaşamalı.
    """
    kaynaklar, isler = tanimdan_yukle(
        {
            "kaynaklar": [{"id": "K", "ad": "K", "gunluk_kapasite": 8, "plaka": "34 ABC 01"}],
            "isler": [
                {"id": "J", "ad": "J", "yuk": 1, "oncelik": 1, "kaynak_id": "K", "musteri": "X"}
            ],
        }
    )

    assert kaynaklar[0].etiketler["plaka"] == "34 ABC 01"
    assert isler[0].etiketler["musteri"] == "X"


# --- ⭐ Genelliğin kanıtı ----------------------------------------------------


def test_nakliye_ornegi_JSONDAN_plan_uretiyor():
    """Nakliye için tek satır alan kodu yazılmadı."""
    kaynaklar, isler = dosyadan_yukle(NAKLIYE)
    planlar = plan_kur(isler, kaynaklar, ufuk_gun=3, baslangic=BUGUN)

    assert len(kaynaklar) == 3
    assert len(isler) == 10
    yerlesen = sum(len(p.satirlar) for p in planlar)
    assert yerlesen >= 8, f"sevkiyatlarin cogu yerlesmeli, yerlesen: {yerlesen}"


def test_nakliye_UYGUNLUK_kisitina_uyuyor():
    """Uygun olmayan kaynağa iş verilmemeli; tek adaylı iş oraya gitmeli."""
    kaynaklar, isler = dosyadan_yukle(NAKLIYE)
    planlar = {p.kaynak_id: p for p in plan_kur(isler, kaynaklar, ufuk_gun=3, baslangic=BUGUN)}

    kisitli = {s.is_id for s in planlar["KAYNAK-3"].satirlar}
    assert "SV-002" not in kisitli, "uygun olmayan kaynaga is verilmis"
    # SV-003 YALNIZCA bu kaynaga uygun.
    assert "SV-003" in kisitli


def test_URETIM_VE_NAKLIYE_ayni_fonksiyonu_cagiriyor():
    """⭐⭐ Faz 11'in tüm iddiası bu testte.

    "Genel motor" demek, ikinci bir alanın **aynı kodu** kullanması demek.
    Üretim çizelgesi kendi yerleştirmesini yapmaya devam etseydi, ortada
    genel bir motor değil iki ayrı planlayıcı olurdu.

    Test `plan_kur`'u sarmalayıp iki alandan da çağrıldığını doğruluyor.
    """
    from app.domain.production import cizelge as uretim_cizelge

    cagrilar: list[str] = []
    gercek = plan_kur

    def casus(isler, kaynaklar, *a, **kw):
        cagrilar.append(kaynaklar[0].kaynak_id if kaynaklar else "?")
        return gercek(isler, kaynaklar, *a, **kw)

    kaynaklar, isler = dosyadan_yukle(NAKLIYE)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(uretim_cizelge, "plan_kur", casus)

        # 1) Nakliye — JSON'dan, alan kodu yok
        casus(isler, kaynaklar, "en_acil", 3, BUGUN)

        # 2) Üretim — kendi adaptörü üzerinden
        from tests.test_uretim import _emir_kararlari, ozellik_kur

        uretim_cizelge.cizelge_kur(_emir_kararlari(ozellik_kur(eldeki_stok=10)), baslangic=BUGUN)

    assert len(cagrilar) == 2, f"iki alan da plan_kur cagirmali, cagrilar: {cagrilar}"
    assert cagrilar[0].startswith("KAYNAK-"), "ikinci alanin kaynagi olmali"
    assert cagrilar[1].startswith("H-"), "uretim kaynagi hat olmali"


# --- Maliyet ve karşılaştırma (Kişi B) ---------------------------------------
#
# ⚠️ Bu testlerin hiçbiri `plan_kur` çağırmıyor. Girdi elle kurulmuş
# `KaynakPlani` nesneleri — yani donmuş sözleşme. Bağımsızlığın kanıtı bu:
# motor tarafı hiç yazılmamış olsa da bu testler yazılabilirdi.


def plan_kayit(
    yerlesen: list[tuple[str, float, int]] | None = None,
    sigmayan: list[tuple[str, float]] | None = None,
    kapasite: float = 8.0,
    ufuk_gun: int = 5,
) -> KaynakPlani:
    """Elle plan kur: (ad, tutar, bitis_gun_offset) / (ad, tutar)."""

    def satir(ad: str, tutar: float, gun: int) -> PlanSatiri:
        return PlanSatiri(
            is_id=ad,
            ad=ad,
            kaynak_id="K1",
            kaynak_adi="Kaynak",
            baslangic=BUGUN,
            bitis=date(2026, 8, 11 + gun),
            yuk=1.0,
            oncelik=1.0,
            etiketler={"tutar": str(tutar)},
        )

    return KaynakPlani(
        kaynak_id="K1",
        kaynak_adi="Kaynak",
        gunluk_kapasite=kapasite,
        kapasite_birimi="saat",
        satirlar=tuple(satir(a, t, g) for a, t, g in (yerlesen or [])),
        sigmayanlar=tuple(satir(a, t, 0) for a, t in (sigmayan or [])),
        ufuk_gun=ufuk_gun,
    )


def test_sigmayan_is_STOKSUZLUK_maliyeti_uretiyor():
    """Ufka sığmayan iş bedelsiz değil — öneri bu farktan doğuyor."""
    from app.planlama.maliyet import plan_maliyeti

    m = plan_maliyeti([plan_kayit(sigmayan=[("A", 10_000.0)])])

    assert m.karsilanamayan_deger_tl == 10_000.0
    assert m.stoksuzluk_tl == pytest.approx(25_000.0)  # ceza carpani 2,5
    assert m.sigmayan_is == 1


def test_maliyet_KIRILIMLI_donuyor():
    """⚠️ Toplam tek başına yetmez: 50.000 TL stoksuzluk ile 50.000 TL elde
    tutma aynı şey değildir — biri müşteri kaybı, diğeri bağlı sermaye."""
    from app.planlama.maliyet import plan_maliyeti

    m = plan_maliyeti([plan_kayit(yerlesen=[("A", 1000.0, 0), ("B", 1000.0, 4)])])

    assert m.kurulum_tl == pytest.approx(500.0)  # 2 is x 250
    assert m.elde_tutma_tl > 0, "erken biten is elde tutma maliyeti dogurmali"
    assert m.stoksuzluk_tl == 0.0
    assert m.varsayimlar, "varsayimlar cikti ile birlikte tasinmali"


def test_bos_plan_maliyeti_PATLAMIYOR():
    from app.planlama.maliyet import plan_maliyeti

    m = plan_maliyeti([plan_kayit()])
    assert m.toplam_tl == 0.0


def test_karsilastirma_EN_UCUZU_oneriyor():
    """⭐ Öneri "bence" değil hesap: en düşük beklenen maliyet."""
    from app.planlama.karsilastir import planlari_karsilastir

    sonuc = planlari_karsilastir(
        {
            "pahali": [plan_kayit(sigmayan=[("X", 100_000.0)])],
            "ucuz": [plan_kayit(yerlesen=[("Y", 1000.0, 0)])],
        }
    )

    assert sonuc.onerilen_olcut == "ucuz"
    assert "TL düşük" in sonuc.oneri_gerekcesi


def test_karsilastirma_TABLOYU_gizlemiyor():
    """⚠️ Öneri varsayımlarını gizlerse sorgulanamaz hâle gelir."""
    from app.planlama.karsilastir import karne_metni, planlari_karsilastir

    metin = karne_metni(
        planlari_karsilastir(
            {
                "a": [plan_kayit(sigmayan=[("X", 5000.0)])],
                "b": [plan_kayit(yerlesen=[("Y", 5000.0, 0)])],
            }
        )
    )

    assert "BEKLENEN MALİYET" in metin
    assert "TAHMİN" in metin, "varsayim uyarisi basilmali"
    assert "stoksuzluk" in metin, "kirilim basilmali"


def test_karsilastirma_esitlikte_KARARLI():
    """Aynı maliyetli iki plan hep aynı sırayla seçilmeli."""
    from app.planlama.karsilastir import planlari_karsilastir

    girdi = {"b_olcut": [plan_kayit()], "a_olcut": [plan_kayit()]}
    assert planlari_karsilastir(girdi).onerilen_olcut == "a_olcut"
    assert planlari_karsilastir(dict(reversed(list(girdi.items())))).onerilen_olcut == "a_olcut"


def test_doluluk_UFKU_hesaba_katiyor():
    """⚠️ İlk sürüm ufku bilmiyordu ve %535 gibi sayılar üretiyordu."""
    plan = plan_kayit(yerlesen=[("A", 0.0, 0)], kapasite=8.0, ufuk_gun=5)
    assert plan.doluluk == pytest.approx(1.0 / 40.0)


# --- Faz 13 · Adım 0: dondurulmuş sözleşme ----------------------------------
#
# ⚠️ Bu bölüm KOD DEĞİL SÖZLEŞME sınıyor. İki tarafın (A gerekçeyi üretir,
# B tüketir) birbirini beklemeden çalışabilmesi buradaki iki garantiye
# dayanıyor: gerekçe varsayılanlı, işler kaynağı varsayılanlı. İkisi de
# bozulursa paralel çalışma sessizce biter.


def test_gerekce_VARSAYILANLI_eski_cagrilar_bozulmuyor():
    """Faz 11'de yazılmış her `PlanSatiri` kurulumu aynen çalışmalı."""
    satir = PlanSatiri(
        is_id="I1",
        ad="İş",
        kaynak_id="K1",
        kaynak_adi="Kaynak",
        baslangic=BUGUN,
        bitis=BUGUN,
        yuk=2.0,
        oncelik=1.0,
    )
    assert satir.gerekce is None, "gerekce varsayilanli degil — B, A'yi beklemek zorunda kalir"


def test_plan_kur_GEREKCESIZ_calisiyor():
    """A13.1 yazılmadan da plan çıkıyor; gerekçe alanı boş duruyor."""
    planlar = plan_kur([is_("I1")], [kaynak("K1")], ufuk_gun=3, baslangic=BUGUN)
    assert [s.gerekce for p in planlar for s in p.satirlar] == [None]


def test_gerekce_BELIRLEYICISI_kapali_kume():
    """⚠️ Serbest metin olsaydı her alan kendi kelimesini yazardı."""
    with pytest.raises(ValueError, match="belirleyici"):
        AtamaGerekcesi(secilen_kaynak="K1", aday_kaynaklar=("K1",), belirleyici="hat_musait")


def test_gerekce_SECILEN_KAYNAK_adaylarda_olmali():
    """Atamayı anlatmayan gerekçe, hiç olmamasından kötüdür — yanlış bilgi verir."""
    with pytest.raises(ValueError, match="aday listesinde yok"):
        AtamaGerekcesi(secilen_kaynak="K9", aday_kaynaklar=("K1", "K2"))


def test_gerekce_ELENME_NEDENI_aday_olmayana_yazilamaz():
    with pytest.raises(ValueError, match="aday olmayan"):
        AtamaGerekcesi(
            secilen_kaynak="K1",
            aday_kaynaklar=("K1", "K2"),
            belirleyici="kapasite",
            elenme_nedenleri={"K7": "kapasite dolu"},
        )


def test_gerekce_KARSILASTIRILABILIR():
    """⚠️ Determinizm kapısı gerekçeleri de karşılaştıracak (A13.1).

    Eşitlik veri üzerinden çalışmazsa `test_plan_TEKRARLANABILIR` gerekçe
    kaymasını göremez ve sessiz kalır.
    """
    kur = lambda: AtamaGerekcesi(  # noqa: E731
        secilen_kaynak="K1",
        aday_kaynaklar=("K1", "K2"),
        belirleyici="kapasite",
        elenme_nedenleri={"K2": "daha dolu"},
    )
    assert kur() == kur()


def test_isler_kaynagi_VARSAYILANI_elle():
    """Bugünkü davranış korunuyor: işler JSON'da yazılı."""
    tanim = alan_tanimi_oku(
        {
            "ad": "Üretim",
            "kaynaklar": [{"id": "M1", "ad": "Makine", "gunluk_kapasite": 8}],
            "isler": [{"id": "J1", "ad": "Parti", "yuk": 3, "oncelik": 1, "kaynak_id": "M1"}],
        }
    )
    assert isinstance(tanim, AlanTanimi)
    assert tanim.isler_kaynagi == IslerKaynagi()
    assert str(tanim.isler_kaynagi) == "elle"


@pytest.mark.parametrize(
    ("ham", "kip", "kaynak_alan"),
    [("elle", "elle", None), ("tahmin", "tahmin", None), ("alan:uretim", "alan", "uretim")],
)
def test_isler_kaynagi_UC_YOL_ayristiriliyor(ham, kip, kaynak_alan):
    tanim = alan_tanimi_oku(
        {
            "kaynaklar": [{"id": "M1", "ad": "M", "gunluk_kapasite": 8}],
            "isler": [{"id": "J1", "ad": "J", "yuk": 3, "oncelik": 1, "kaynak_id": "M1"}],
            "isler_kaynagi": ham,
        }
    )
    assert (tanim.isler_kaynagi.kip, tanim.isler_kaynagi.kaynak_alan) == (kip, kaynak_alan)
    assert str(tanim.isler_kaynagi) == ham


@pytest.mark.parametrize("ham", ["otomatik", "alan:", "ALAN:uretim", "", 3])
def test_isler_kaynagi_gecersiz_deger_SESSIZCE_VARSAYILANA_dusmuyor(ham):
    with pytest.raises(TanimHatasi):
        alan_tanimi_oku(
            {
                "kaynaklar": [{"id": "M1", "ad": "M", "gunluk_kapasite": 8}],
                "isler": [],
                "isler_kaynagi": ham,
            }
        )


def test_UST_SEVIYE_yazim_hatasi_patliyor():
    """⚠️ Faz 9'un dersi: `isler_kaynak` yazan tanım elle'ye düşerse plan
    geçmişten beslendiği sanılırken elle yazılmış işlerle koşar."""
    with pytest.raises(TanimHatasi, match="isler_kaynagi"):
        tanimdan_yukle(
            {
                "kaynaklar": [{"id": "M1", "ad": "M", "gunluk_kapasite": 8}],
                "isler": [],
                "isler_kaynak": "tahmin",
            }
        )


def test_KAYIT_ICI_bilinmeyen_alan_hala_ETIKET():
    """Üst seviye kapalı, kaydın içi açık — ayrım korunuyor."""
    _, isler = tanimdan_yukle(
        {
            "kaynaklar": [{"id": "K", "ad": "K", "gunluk_kapasite": 8}],
            "isler": [
                {"id": "J", "ad": "J", "yuk": 1, "oncelik": 1, "kaynak_id": "K", "musteri": "X"}
            ],
        }
    )
    assert isler[0].etiketler["musteri"] == "X"


def test_nakliye_ornegi_YENI_SOZLESMEYLE_okunuyor():
    """Mevcut alan tanımı değiştirilmeden yeni okuyucudan geçiyor."""
    tanim = alan_tanimi_dosyadan(NAKLIYE)
    assert len(tanim.kaynaklar) == 3
    assert len(tanim.isler) == 10
    assert tanim.isler_kaynagi.kip == "elle"
