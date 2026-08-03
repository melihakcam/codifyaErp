"""Guard testleri (Faz 2 B2.5) — projenin en kritik test dosyası.

Görev dosyasının "bitti sayılır" ölçütü:

1. bağlamda olmayan sayı içeren elle yazılmış metinler **hepsi** reddediliyor
2. geçerli metinler geçiyor
3. Türkçe binlik ayracı ve yüzde biçimleri doğru ayrıştırılıyor

⚠️ Hiçbir test modeli çalıştırmıyor — guard zaten modele bağlı değil,
üreteç enjekte ediliyor.

Uydurma sayı vakaları hayali değil: **bu modelin bu projede gerçekten
ürettiği** metinlerden alındı (B2.1 ve B2.2 ölçümleri).
"""

from __future__ import annotations

import pytest

from app.contracts import DecisionCandidate, GuardSonucu
from app.domain.stock.decide import decide_stub
from app.llm.explain import sablon_gerekce
from app.llm.guard import (
    DogrulamaSonucu,
    adayi_dogrula,
    gerekceyi_guvenceye_al,
    maskelenecek_alanlar,
    metni_maskele,
    sayi_izinli_mi,
    sayilari_cikar,
    sayilari_dogrula,
    sayiyi_coz,
)


@pytest.fixture
def aday() -> DecisionCandidate:
    return decide_stub()


# --- Türkçe sayı biçimleri (ölçüt 3) ------------------------------------------


@pytest.mark.parametrize(
    ("belirtec", "beklenen"),
    [
        ("1.200", 1200.0),  # binlik ayracı nokta
        ("1.200.000", 1200000.0),
        ("4,75", 4.75),  # ondalık ayracı virgül
        ("1.200,50", 1200.5),
        ("94", 94.0),
        ("0,94", 0.94),
        ("42", 42.0),
        ("5", 5.0),
    ],
)
def test_turkce_sayi_bicimleri_cozuluyor(belirtec: str, beklenen: float):
    assert sayiyi_coz(belirtec) == pytest.approx(beklenen)


def test_yuzde_ve_para_birimi_iceren_metinden_sayi_cikariliyor():
    metin = "Tedarikçi %94 zamanında teslim yaptı, tutar 5.000 TL, birim 4,75 TL."

    assert sayilari_cikar(metin) == [94.0, 5000.0, 4.75]


def test_cumle_sonu_noktasi_sayiya_karismiyor():
    assert sayilari_cikar("Toplam 1.200 adet sipariş verildi.") == [1200.0]


def test_bozuk_belirtec_none_doner():
    assert sayiyi_coz("...") is None
    assert sayiyi_coz("") is None


# --- Maskeleme (guard'ın çalışması için zorunlu) ------------------------------


def test_kendi_sablon_gerekcemiz_kendi_guardimizdan_geciyor(aday: DecisionCandidate):
    """⭐⭐ EN KRİTİK TEST.

    Şablon gerekçe, guard'ın **geri dönüş noktası**. O da reddedilirse sistemin
    güvenli çıkışı kalmaz ve karar bloke olur.

    Bu test maskeleme olmadan KIRMIZI olur: `"Kırmızı Tuğla 19x9x5"` içindeki
    19, 9, 5 izinli kümede yok. Ölçüldü, doğrulandı — fikir Kişi A'nın
    `_metni_maskele`'sinden geldi.
    """
    sonuc = adayi_dogrula(sablon_gerekce(aday), aday)

    assert sonuc.gecti, f"şablon gerekçe reddedildi: {sonuc.reddedilen}"


def test_maskeleme_olmadan_urun_adindaki_olculer_reddedilir(aday: DecisionCandidate):
    """Yukarıdaki testin neden gerekli olduğunun kanıtı."""
    metin = sablon_gerekce(aday)

    maskesiz = sayilari_dogrula(metin, aday.izinli_sayilar())  # maskelenecek YOK

    assert not maskesiz.gecti
    assert {19.0, 9.0, 5.0} <= set(maskesiz.reddedilen), "19x9x5 sayı sanılmalıydı"


def test_tedarikci_kodu_maskeleniyor(aday: DecisionCandidate):
    metin = f"Tedarikçi {aday.ozellikler.tedarikci_id} seçildi."

    assert adayi_dogrula(metin, aday).gecti


def test_maskeleme_buyuk_kucuk_harf_duyarsiz():
    """Model ürün adının yazımını değiştirebilir."""
    maskeli = metni_maskele("KIRMIZI TUĞLA 19x9x5 için", ["Kırmızı Tuğla 19x9x5"])

    assert "19" not in maskeli


def test_uzun_metin_once_maskeleniyor():
    """`T-014` ile `T-0141` gibi önek çakışmasında kısası önce silinirse uzun bozulur."""
    maskeli = metni_maskele("T-0141 ve T-014 tedarikçileri", ["T-014", "T-0141"])

    assert "0141" not in maskeli
    assert "014" not in maskeli


# --- Uydurma sayı reddi (ölçüt 1) ---------------------------------------------


@pytest.mark.parametrize(
    ("metin", "uydurma"),
    [
        # ⚠️ Hepsi bu modelin bu projede GERÇEKTEN ürettiği metinler.
        ("Kırmızı Tuğla 19x9x5 için 35 adet ek satışı yapar.", 35.0),
        ("163 adet öneriliyor.", 163.0),
        ("42 + 615 - 1200 = 397 adet kaldı.", 397.0),
        ("Tarih 1976-03-14 itibarıyla stok yeterli.", 1976.0),
        # Elle yazılmış ek vakalar
        ("Stok 9999 adede düştü.", 9999.0),
        ("Marj %73,5 olarak hesaplandı.", 73.5),
        ("Toplam 12.345 TL tutuyor.", 12345.0),
    ],
)
def test_uydurma_sayi_reddediliyor(metin: str, uydurma: float, aday: DecisionCandidate):
    """⭐ Görev dosyasının 1. ölçütü: bağlamda olmayan sayı içeren metinler hepsi reddedilir."""
    sonuc = adayi_dogrula(metin, aday)

    assert not sonuc.gecti
    assert uydurma in sonuc.reddedilen


def test_gercek_sayilar_arasina_gizlenmis_uydurma_yakalanir(aday: DecisionCandidate):
    """Modelin en sinsi hatası: doğru sayıların arasına bir yanlış karıştırmak."""
    metin = "Günlük 42 adet tüketim, 12 gün tedarik, 270 adet stok, 888 adet sipariş."

    sonuc = adayi_dogrula(metin, aday)

    assert not sonuc.gecti
    assert sonuc.reddedilen == [888.0]


def test_nokta_ayracli_tarih_reddediliyor(aday: DecisionCandidate):
    """Nokta ayraçlı tarih tek bir sayı olarak okunur ve reddedilir.

    `'14.03.1976'` binlik gruplaması geçersizdir (2-2-4) ama `sayiyi_coz` yine
    de 14031976.0 üretir. Denetim kaydında garip görünür — Kişi A'nın guard
    incelemesindeki gözlem buydu.

    ⚠️ Bu test **kozmetik değil, yön kilididir.** "Geçersiz gruplama, `None`
    döndüreyim" diye düzeltmek cazip gelir; ama `None` dönen belirteç
    `sayilari_cikar` tarafından *yok sayılır* — yani tarih guard'dan **geçer**.
    Garip görünen sayı, güvenli olan davranıştır.
    """
    sonuc = adayi_dogrula("14.03.1976 tarihinde stok tükendi.", aday)

    assert not sonuc.gecti
    assert sonuc.reddedilen == [14031976.0]


# --- Geçerli metinler (ölçüt 2) -----------------------------------------------


def test_izinli_sayilarla_yazilmis_metin_geciyor(aday: DecisionCandidate):
    metin = (
        "Günlük ortalama 42 adet tüketim var, tedarik süresi 12 gün ve elde "
        "270 adet kaldı. Yeniden sipariş noktası 615 adedin altına düşüldüğü "
        "için 1.200 adet sipariş öneriliyor."
    )

    assert adayi_dogrula(metin, aday).gecti


def test_oran_yuzde_olarak_yazilabiliyor(aday: DecisionCandidate):
    """`tedarikci_zamaninda_teslim_orani = 0,94` gerekçede "%94" olarak yazılır."""
    assert adayi_dogrula("Tedarikçi %94 zamanında teslim yapıyor.", aday).gecti


def test_sayisiz_metin_geciyor(aday: DecisionCandidate):
    assert adayi_dogrula("Stok yeterli, aksiyon gerekmiyor.", aday).gecti


# --- Tolerans: yuvarlama kabul, kabalık ret -----------------------------------


def test_dogru_yuvarlama_kabul_ediliyor():
    """`27,380952` için "%27" doğru bir yuvarlama — reddedilmemeli."""
    izinli = [27.380952380952383]

    assert sayi_izinli_mi(27.0, izinli)
    assert sayi_izinli_mi(27.4, izinli)
    assert sayi_izinli_mi(27.38, izinli)


def test_yanlis_yuvarlama_reddediliyor():
    assert not sayi_izinli_mi(28.0, [27.380952380952383])
    assert not sayi_izinli_mi(27.5, [27.380952380952383])


def test_kaba_yuvarlama_reddediliyor():
    """⭐ `0,94 → "1"` ve `4,75 → "5"` geçerse gerekçede uydurma adet oluşur.

    Bağıl %2 sınırı olmadan bu ikisi "doğru yuvarlama" sayılırdı.
    """
    assert not sayi_izinli_mi(1.0, [0.94]), "0,94 -> 1 kabul edilmemeli"
    assert not sayi_izinli_mi(5.0, [4.75]), "4,75 -> 5 kabul edilmemeli"


def test_iki_ondalikli_yazim_bagil_sinira_takilmiyor():
    """⭐ Bağıl sınır tek başına küçük sayılara haksızlık ediyordu.

    Ölçülmüş vaka (Kişi A'nın eğitim verisi, `gerekce_train.jsonl`):

        gerçek 0,14444…  →  metinde "0,14"  →  bağıl fark %3,08

    "0,14" iki ondalıkla doğru bir yazım; kimse "0,14444 adet" demez. Ama sayı
    küçüldükçe aynı yuvarlama yüzde olarak büyüyor ve %2 sınırını aşıyordu.
    Bu, sipariş gerekçelerinin **%16,9'unu** boşuna reddediyordu.
    """
    assert sayi_izinli_mi(0.14, [0.14444444444444443])
    assert sayi_izinli_mi(0.03, [0.0325])
    assert sayi_izinli_mi(0.31, [0.3149])


def test_iki_ondalik_istisnasi_yanlis_yuvarlamayi_kurtarmiyor():
    """İstisna yalnızca DOĞRU yuvarlamayı serbest bırakır, uydurmayı değil."""
    assert not sayi_izinli_mi(0.15, [0.14444444444444443])  # 0,14 olmalıydı
    assert not sayi_izinli_mi(0.99, [0.14444444444444443])


def test_kaba_yuvarlama_hala_reddediliyor_istisnaya_ragmen():
    """⭐ İstisna eklendikten sonra da B2.5'in asıl amacı korunuyor.

    `0,94 → "1"` ve `4,75 → "5"` ondalık içermiyor, dolayısıyla istisnadan
    yararlanamıyor ve bağıl sınıra takılmaya devam ediyor.

    Not: `6,9 → "7"` bağıl fark %1,45 ile sınırın **altında** ve kabul ediliyor —
    bu istisnadan değil, en baştaki %2 kuralından geliyor. `27,38 → "%27"`
    (%1,39) ile aynı sınıfta; ikisini ayırmanın tutarlı bir yolu yok.
    """
    assert not sayi_izinli_mi(1.0, [0.94])
    assert not sayi_izinli_mi(5.0, [4.75])


def test_birebir_eslesme_her_zaman_geciyor():
    assert sayi_izinli_mi(0.94, [0.94])
    assert sayi_izinli_mi(1200.0, [1200.0])
    assert sayi_izinli_mi(0.0, [0.0])


# --- Zincir: üret → doğrula → yeniden dene → şablona düş ----------------------


def test_ilk_denemede_gecerse_gecti(aday: DecisionCandidate):
    def uretici(a: DecisionCandidate, *, onceki_red=None) -> str:
        return "Stok yeterli, aksiyon gerekmiyor."

    gerekce = gerekceyi_guvenceye_al(aday, uretici, model_adi="test-model")

    assert gerekce.guard_sonucu is GuardSonucu.GECTI
    assert gerekce.model_adi == "test-model"
    assert gerekce.reddedilen_sayilar == []


def test_ilk_deneme_reddedilirse_yeniden_uretiliyor(aday: DecisionCandidate):
    cagri = {"sayi": 0}

    def uretici(a: DecisionCandidate, *, onceki_red=None) -> str:
        cagri["sayi"] += 1
        return "9999 adet." if cagri["sayi"] == 1 else "Stok yeterli."

    gerekce = gerekceyi_guvenceye_al(aday, uretici)

    assert cagri["sayi"] == 2
    assert gerekce.guard_sonucu is GuardSonucu.YENIDEN_URETILDI
    assert gerekce.metin == "Stok yeterli."


def test_ikinci_deneme_de_reddedilirse_sablona_dusuluyor(aday: DecisionCandidate):
    """⭐ Karar hiçbir koşulda bloke olmaz."""

    def uretici(a: DecisionCandidate, *, onceki_red=None) -> str:
        return "9999 adet uydurma."

    gerekce = gerekceyi_guvenceye_al(aday, uretici)

    assert gerekce.guard_sonucu is GuardSonucu.SABLONA_DUSTU
    assert gerekce.metin == sablon_gerekce(aday)
    assert gerekce.model_adi is None, "şablon modelden gelmedi"
    assert 9999.0 in gerekce.reddedilen_sayilar


def test_sablona_dusen_metin_de_guarddan_geciyor(aday: DecisionCandidate):
    """Geri dönüş noktası kendi kontrolünden geçmezse sistem çıkışsız kalır."""

    def uretici(a: DecisionCandidate, *, onceki_red=None) -> str:
        return "9999"

    gerekce = gerekceyi_guvenceye_al(aday, uretici)

    assert adayi_dogrula(gerekce.metin, aday).gecti


def test_uretici_patlarsa_sablona_dusuluyor(aday: DecisionCandidate):
    """LLM erişilemez olsa bile karar bloke olmamalı (Faz 4 graceful degradation)."""

    def uretici(a: DecisionCandidate, *, onceki_red=None) -> str:
        raise RuntimeError("ollama yok")

    gerekce = gerekceyi_guvenceye_al(aday, uretici)

    assert gerekce.guard_sonucu is GuardSonucu.SABLONA_DUSTU
    assert gerekce.metin == sablon_gerekce(aday)


def test_reddedilen_sayilar_ikinci_denemeye_bildiriliyor(aday: DecisionCandidate):
    """Üreteç prompt'a "şu sayıları kullanma" ekleyebilsin."""
    gorulen: list[list[float] | None] = []

    def uretici(a: DecisionCandidate, *, onceki_red=None) -> str:
        gorulen.append(onceki_red)
        return "9999 adet."

    gerekceyi_guvenceye_al(aday, uretici)

    assert gorulen[0] is None, "ilk denemede önceki red olmamalı"
    assert gorulen[1] == [9999.0]


def test_uretim_suresi_olculuyor(aday: DecisionCandidate):
    def uretici(a: DecisionCandidate, *, onceki_red=None) -> str:
        return "Stok yeterli."

    assert gerekceyi_guvenceye_al(aday, uretici).uretim_ms >= 0


# --- Kişi A'nın kullanacağı arayüz --------------------------------------------


def test_sayilari_dogrula_decisioncandidate_bilmiyor():
    """⭐ Kişi A eğitim verisi üretiminde bunu çağıracak.

    Görev dosyası: "Ona sade, çağrılabilir bir fonksiyon arayüzü bırak."
    İki kopya guard mantığı zamanla ayrışır; tek kaynak olmalı.
    """
    sonuc = sayilari_dogrula(
        "Tuğla 19x9x5 için 1.200 adet sipariş.",
        izinli=[1200.0],
        maskelenecek=["Tuğla 19x9x5"],
    )

    assert isinstance(sonuc, DogrulamaSonucu)
    assert sonuc.gecti


def test_maskelenecek_alanlar_ad_ve_kodlari_veriyor(aday: DecisionCandidate):
    alanlar = maskelenecek_alanlar(aday)

    assert aday.ozellikler.sku_adi in alanlar
    assert aday.ozellikler.tedarikci_id in alanlar


# --- Gerçek karar motoruyla ---------------------------------------------------


def test_gercek_karar_motorunun_sablonu_da_geciyor():
    """Kişi A'nın gerçek motoru farklı ürün adları ve ondalıklı değerler üretiyor."""
    from app.domain.stock.decide import stok_karari_uret

    gercek = stok_karari_uret()
    sonuc = adayi_dogrula(sablon_gerekce(gercek), gercek)

    assert sonuc.gecti, f"gerçek kararın şablonu reddedildi: {sonuc.reddedilen}"
