"""Alan adaptörleri (`app/domain/*/adapter.py`) — Faz 13 A13.2.

⚠️ Bu fazın genellik iddiasını taşıyan dosyalar bunlar. İki adaptör
**aynı imzayı** taşıyor ve motor ikisini ayırt etmiyor; ayrışırlarsa motor
"hangi alan hangi biçimde çağrılır" bilgisini taşımak zorunda kalır ve
genellik biter. `test_IKI_ADAPTOR_AYNI_IMZAYI_tasiyor` bunun bekçisi.

Testlerin çoğu gerçek üretim hattını **çağırmıyor**: `uretim_kararlari_uret`
ölçülen süresi ~36-75 sn olan bir hesap. Zincirin gerçek veriyle koştuğu
tek test `yavas` işaretli.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from app.domain.logistics import adapter as sevkiyat
from app.domain.production import adapter as uretim
from app.planlama.contracts import Is, Kaynak
from app.planlama.tam_plan import tam_plan
from app.planlama.tanim import AlanTanimi, IslerKaynagi

BUGUN = date(2026, 8, 26)


def sevkiyat_tanimi(**parametreler: str) -> AlanTanimi:
    return AlanTanimi(
        ad="Sevkiyat",
        kaynaklar=(
            Kaynak(kaynak_id="ARAC-1", ad="Araç 1", gunluk_kapasite=9),
            Kaynak(kaynak_id="ARAC-2", ad="Araç 2", gunluk_kapasite=6),
        ),
        isler=(),
        isler_kaynagi=IslerKaynagi(kip="alan", kaynak_alan="uretim"),
        adaptor="app.domain.logistics.adapter",
        parametreler=parametreler,
    )


def uretim_isi(is_id: str = "S-001", miktar: str = "100", oncelik: float = 3.0) -> Is:
    return Is(
        is_id=is_id,
        ad=f"Kalem {is_id}",
        yuk=4.0,
        oncelik=oncelik,
        kaynak_id="H-01",
        etiketler={"miktar": miktar, "kalem_id": is_id},
    )


# --- Ortak imza: genelliğin taşıyıcısı ----------------------------------------


def test_IKI_ADAPTOR_AYNI_IMZAYI_tasiyor():
    """⚠️ Motor adaptörleri ayırt etmiyor; imzaları ayrışırsa etmek zorunda kalır."""
    assert inspect.signature(uretim.isleri_uret) == inspect.signature(sevkiyat.isleri_uret)


def test_ADAPTORLER_alan_adini_PARAMETRE_olarak_almiyor():
    """Adaptör hangi alan olduğunu bilmiyor; tanımı alıyor."""
    for modul in (uretim, sevkiyat):
        parametreler = list(inspect.signature(modul.isleri_uret).parameters)
        assert parametreler[0] == "tanim"
        assert "alan" not in parametreler


# --- Üretim adaptörü (hızlı, gerçek hesap yerine sahte) ------------------------


@pytest.fixture
def sahte_uretim(monkeypatch: pytest.MonkeyPatch):
    """`_emirler` yerine sabit veri — 36-75 sn'lik hesap testte koşmasın."""
    isler = [uretim_isi("S-001"), uretim_isi("S-002", oncelik=1.0)]
    kaynaklar = [Kaynak(kaynak_id="H-01", ad="Kesim Hattı", gunluk_kapasite=13.6)]
    cagri = {"sayi": 0}

    def sahte() -> tuple[list[Is], list[Kaynak]]:
        cagri["sayi"] += 1
        return isler, kaynaklar

    monkeypatch.setattr(uretim, "_emirler", sahte)
    return cagri


def test_URETIM_ADAPTORU_isleri_ve_KAYNAKLARI_veriyor(sahte_uretim):
    tanim = AlanTanimi(ad="Üretim", kaynaklar=(), isler=())

    isler = uretim.isleri_uret(tanim=tanim, ufuk_gun=14, baslangic=BUGUN)
    kaynaklar = uretim.kaynaklari_uret(tanim)

    assert [i.is_id for i in isler] == ["S-001", "S-002"]
    assert [k.kaynak_id for k in kaynaklar] == ["H-01"]


def test_URETIM_ZINCIRIN_BASI_kaynak_isleri_kullanmiyor(sahte_uretim):
    """Üretim kimseden beslenmiyor; verilen işler çıktıyı değiştirmemeli."""
    tanim = AlanTanimi(ad="Üretim", kaynaklar=(), isler=())

    yalin = uretim.isleri_uret(tanim=tanim, ufuk_gun=14, baslangic=BUGUN)
    beslenmis = uretim.isleri_uret(
        tanim=tanim, ufuk_gun=14, baslangic=BUGUN, kaynak_isler=(uretim_isi("X"),)
    )

    assert [i.is_id for i in yalin] == [i.is_id for i in beslenmis]


def test_URETIM_ONBELLEGI_HESABI_IKI_KEZ_yapmiyor(monkeypatch: pytest.MonkeyPatch):
    """⚠️ Motor iş ve kaynağı ayrı istiyor; hesap iki kez koşarsa süre ikiye katlanır."""
    uretim.onbellek_temizle()
    sayac = {"n": 0}

    def sahte_kararlar():
        sayac["n"] += 1
        return []

    monkeypatch.setattr(uretim, "uretim_kararlari_uret", sahte_kararlar)
    tanim = AlanTanimi(ad="Üretim", kaynaklar=(), isler=())

    uretim.isleri_uret(tanim=tanim, ufuk_gun=14, baslangic=BUGUN)
    uretim.kaynaklari_uret(tanim)

    assert sayac["n"] == 1, "aynı hesap iki kez koştu"

    uretim.onbellek_temizle()
    uretim.kaynaklari_uret(tanim)
    assert sayac["n"] == 2, "önbellek temizlenince yeniden hesaplanmadı"


# --- Sevkiyat adaptörü: zincir bağı -------------------------------------------


def test_SEVKIYAT_ONCEKI_ALANIN_ISLERINDEN_turuyor():
    isler = sevkiyat.isleri_uret(
        tanim=sevkiyat_tanimi(),
        ufuk_gun=14,
        baslangic=BUGUN,
        kaynak_isler=(uretim_isi("S-001"), uretim_isi("S-002")),
    )

    assert [i.is_id for i in isler] == ["SVK-S-001", "SVK-S-002"]
    assert all(i.etiketler["kaynak_is"].startswith("S-") for i in isler)


def test_SEVKIYAT_ONCELIGI_DEVRALIYOR():
    """⚠️ Ayrı bir aciliyet tanımı iki alanı birbiriyle çelişkiye sokardı."""
    isler = sevkiyat.isleri_uret(
        tanim=sevkiyat_tanimi(),
        ufuk_gun=14,
        baslangic=BUGUN,
        kaynak_isler=(uretim_isi("S-001", oncelik=7.0),),
    )

    assert isler[0].oncelik == 7.0


def test_SEVKIYAT_ARAC_ATAMASINI_PLANA_birakiyor():
    """ "Şu araç şuraya gidebilir" sorusunun cevabı plana ait bir karar."""
    isler = sevkiyat.isleri_uret(
        tanim=sevkiyat_tanimi(),
        ufuk_gun=14,
        baslangic=BUGUN,
        kaynak_isler=(uretim_isi(),),
    )

    assert isler[0].kaynak_id is None
    assert isler[0].uygun_kaynaklar == ("ARAC-1", "ARAC-2")


def test_SEVKIYAT_YUKU_TANIMDAKI_parametrelerden():
    """⚠️ Sayılar koda gömülü değil: ikinci müşteri kod değişikliği istemesin."""
    isler = sevkiyat.isleri_uret(
        tanim=sevkiyat_tanimi(birim_yukleme_saat="0.02", sabit_hazirlik_saat="1.0"),
        ufuk_gun=14,
        baslangic=BUGUN,
        kaynak_isler=(uretim_isi(miktar="100"),),
    )

    assert isler[0].yuk == pytest.approx(1.0 + 100 * 0.02)


def test_SEVKIYAT_BOZUK_PARAMETRE_sessizce_varsayilana_dusmuyor():
    with pytest.raises(Exception, match="sayı değil"):
        sevkiyat.isleri_uret(
            tanim=sevkiyat_tanimi(birim_yukleme_saat="çok"),
            ufuk_gun=14,
            baslangic=BUGUN,
            kaynak_isler=(uretim_isi(),),
        )


def test_SEVKIYAT_BESLENMEZSE_bos_donuyor():
    """Zincirin başı boşsa sevkiyat da boş — uydurma iş üretmiyor."""
    assert sevkiyat.isleri_uret(tanim=sevkiyat_tanimi(), ufuk_gun=14, baslangic=BUGUN) == []


# --- Gerçek veri: fazın 1. kapısı ---------------------------------------------


@pytest.mark.yavas
def test_GERCEK_IKI_ALAN_ayni_komuttan_plan_uretiyor():
    """⚠️ Fazın 1. kapısı — artık sahte alanlarla değil, gerçek tanımlarla.

    Üretim işlerini tahminden alıyor, nakliye tanımdan; ikisi de aynı
    fonksiyondan geçiyor.
    """
    uretim.onbellek_temizle()

    uretim_plani = tam_plan("uretim", baslangic=BUGUN)
    nakliye_plani = tam_plan("nakliye", baslangic=BUGUN)

    assert uretim_plani.isler_kaynagi == "tahmin"
    assert nakliye_plani.isler_kaynagi == "elle"
    assert uretim_plani.satirlar and nakliye_plani.satirlar
    assert all(s.gerekce is not None for s in uretim_plani.satirlar)


@pytest.mark.yavas
def test_GERCEK_ZINCIR_uretimden_sevkiyata():
    """Bir alanın çıktısı başka alanın girdisi — gerçek veriyle."""
    sevkiyat_plani = tam_plan("sevkiyat", baslangic=BUGUN)

    assert sevkiyat_plani.isler_kaynagi == "alan:uretim"
    assert sevkiyat_plani.satirlar
    assert all(s.is_id.startswith("SVK-") for s in sevkiyat_plani.satirlar)
    # Araç ataması gerçekten yapılıyor: işler tek araca yığılmıyor.
    assert len({s.kaynak_id for s in sevkiyat_plani.satirlar}) > 1
