"""Gerçek gerekçe üretimi testleri (Faz 2 B2.4).

⚠️ Hiçbiri gerçek modeli çalıştırmaz — sahte cevaplarla.

Kabul ölçütü ("10 gerçek karar için üretilen gerekçelerin Türkçesi anlaşılır
ve sayıları doğru") insan gözüyle ayrıca ölçülür ve
`dokumantasyon/OLCUMLER.md`'ye yazılır. Buradaki testler o ölçümün dayandığı
mantığı sınar: isteme hangi sayılar konuyor, guard zinciri bağlı mı, model
patlarsa ne oluyor.
"""

from __future__ import annotations

import httpx
import pytest

from app.contracts import DecisionCandidate, GuardSonucu
from app.core.config import Ayarlar
from app.domain.stock.decide import decide_stub, stok_karari_uret
from app.llm.client import OllamaIstemcisi
from app.llm.explain import (
    gerekce_uret,
    istem_kur,
    llm_ureteci,
    sayi_etiketleri,
)


@pytest.fixture
def aday() -> DecisionCandidate:
    return decide_stub()


def _ayar() -> Ayarlar:
    return Ayarlar(ollama_base_url="http://sahte:11434", llm_yeniden_deneme=0)


def _istemci(cevaplar: list[str]) -> OllamaIstemcisi:
    """Sırayla verilen metinleri döndüren sahte istemci."""
    kalan = list(cevaplar)

    def isleyici(istek: httpx.Request) -> httpx.Response:
        metin = kalan.pop(0) if kalan else ""
        return httpx.Response(
            200,
            json={
                "model": "sahte",
                "response": metin,
                "eval_count": 20,
                "eval_duration": 1_000_000_000,
                "load_duration": 0,
            },
        )

    return OllamaIstemcisi(_ayar(), transport=httpx.MockTransport(isleyici))


def _cevap(metin: str) -> str:
    """Modelin GerekceCiktisi şemasına uyan cevabı."""
    import json

    return json.dumps({"gerekce": metin}, ensure_ascii=False)


# --- İsteme konan sayılar -----------------------------------------------------


@pytest.mark.parametrize("uretici", [decide_stub, stok_karari_uret])
def test_isteme_konan_her_sayi_izinli_kumede(uretici):
    """⭐ B2.4'ün en kritik değişmezi.

    İsteme guard'ın reddedeceği bir sayı koyarsak model o sayıyı iyi niyetle
    kullanır ve metin **her seferinde** şablona düşer. Sessiz bir arıza olur:
    hata yok, log yok, sadece gerekçeler hiç LLM'den gelmez.

    İki motorla da sınanıyor — stub yuvarlak sayılar, gerçek motor ondalıklı.
    """
    aday = uretici()
    izinli = aday.izinli_sayilar()

    disarida = [(ad, d) for ad, d in sayi_etiketleri(aday) if d not in izinli]

    assert not disarida, f"izinli kümede olmayan sayı isteme kondu: {disarida}"


def test_etiketler_bos_degil(aday: DecisionCandidate):
    """Sayı etiketsiz verilirse model doğru sayıyı yanlış cümlede kullanır."""
    ciftler = sayi_etiketleri(aday)

    assert ciftler
    assert all(ad.strip() for ad, _ in ciftler)


def test_ayni_sayi_iki_kez_konmuyor(aday: DecisionCandidate):
    """Aksiyon ve kural değerleri çakışabiliyor; tekrar isteme gürültü katar."""
    adlar = [ad for ad, _ in sayi_etiketleri(aday)]

    assert len(adlar) == len(set(adlar))


# --- İstem metni --------------------------------------------------------------


def test_istem_sayilari_turkce_bicimde_veriyor():
    """Model gördüğü biçimi kopyalar; guard da Türkçe biçim bekler."""
    aday = decide_stub()

    istem = istem_kur(aday)

    # stub'ın sipariş miktarı 1200 → '1.200' olarak geçmeli, '1200' olarak değil
    assert "1.200" in istem
    assert "önerilen sipariş miktarı" in istem


def test_istem_karar_tipini_tasiyor(aday: DecisionCandidate):
    assert aday.tip.value in istem_kur(aday)


def test_istem_urun_ve_tedarikci_adini_TASIMIYOR(aday: DecisionCandidate):
    """⭐ 1.5B model Türkçe özel adları bozuyor, guard da bunu yakalayamıyor.

    Ölçümde görülenler: "Astar Boya" → *starboy*, "İzocam" → *isyancı yalıtım
    levhası*. Uydurulan şey sayı olmadığı için guard sessiz kalıyor. Ad zaten
    ERP'de kararın yanında duruyor; isteme koymamak sorunu kaynağında kesiyor.
    """
    istem = istem_kur(aday)

    assert aday.ozellikler.sku_adi not in istem
    assert aday.ozellikler.tedarikci_adi not in istem


def test_istem_gerekce_isaretiyle_bitiyor(aday: DecisionCandidate):
    """⭐ İstem veri listesiyle biterse model listeyi devam ettiriyor.

    B2.4'ün ilk ölçümünde tam bu oldu: 10 örneğin 6'sında model istemi olduğu
    gibi geri yazdı ve guard bunu **geçirdi**, çünkü echo edilen sayılar zaten
    izinli sayılardı. Sondaki `GEREKÇE:` satırı "sıra sende" işareti.
    """
    assert istem_kur(aday).rstrip().endswith("GEREKÇE:")
    assert istem_kur(aday, onceki_red=[9999.0]).rstrip().endswith("GEREKÇE:")


def test_onceki_red_isteme_yaziliyor(aday: DecisionCandidate):
    """İkinci denemeyi birinciden farklı kılan tek şey bu."""
    istem = istem_kur(aday, onceki_red=[397.0, 9999.0])

    assert "397" in istem
    assert "9.999" in istem
    assert "kullanma" in istem


def test_onceki_red_yoksa_uyari_bolumu_yok(aday: DecisionCandidate):
    assert "UYARI" not in istem_kur(aday)
    assert "UYARI" not in istem_kur(aday, onceki_red=[])


# --- Guard zinciriyle birlikte ------------------------------------------------


def test_temiz_cevap_ilk_denemede_geciyor(aday: DecisionCandidate):
    metin = "Kullanılabilir stok 270 adede düştüğü için 1.200 adet sipariş öneriliyor."
    istemci = _istemci([_cevap(metin)])

    gerekce = gerekce_uret(aday, istemci)

    assert gerekce.guard_sonucu is GuardSonucu.GECTI
    assert gerekce.metin == metin
    assert gerekce.reddedilen_sayilar == []


def test_uydurma_sayi_ikinci_denemeye_gonderiyor(aday: DecisionCandidate):
    """İlk cevapta uydurma var, ikincisi temiz → YENIDEN_URETILDI."""
    temiz = "Günlük 42 adet tüketim var, 1.200 adet sipariş öneriliyor."
    istemci = _istemci([_cevap("Stok 9999 adede düştü."), _cevap(temiz)])

    gerekce = gerekce_uret(aday, istemci)

    assert gerekce.guard_sonucu is GuardSonucu.YENIDEN_URETILDI
    assert gerekce.metin == temiz


def test_iki_deneme_de_uydurursa_sablona_dusuyor(aday: DecisionCandidate):
    istemci = _istemci([_cevap("Stok 9999 adet."), _cevap("Stok 8888 adet.")])

    gerekce = gerekce_uret(aday, istemci)

    assert gerekce.guard_sonucu is GuardSonucu.SABLONA_DUSTU
    assert gerekce.reddedilen_sayilar == [8888.0]
    assert gerekce.model_adi is None  # şablon modelden gelmedi


def test_model_kapaliysa_sablona_dusuyor(aday: DecisionCandidate):
    """⭐ Mimarinin ikinci kuralı: ERP asla LLM'i beklemez."""

    def isleyici(istek: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("baglanti yok")

    istemci = OllamaIstemcisi(_ayar(), transport=httpx.MockTransport(isleyici))

    gerekce = gerekce_uret(aday, istemci)

    assert gerekce.guard_sonucu is GuardSonucu.SABLONA_DUSTU
    assert gerekce.metin  # boş değil, şablon cümle geldi


def test_bozuk_json_sablona_dusuyor(aday: DecisionCandidate):
    """Şema hatası da kararı bloke etmemeli."""
    istemci = _istemci(["bu json degil", "hala degil", "yine degil", "olmadi"])

    gerekce = gerekce_uret(aday, istemci)

    assert gerekce.guard_sonucu is GuardSonucu.SABLONA_DUSTU


def test_gecen_metnin_model_adi_yaziliyor(aday: DecisionCandidate):
    """Denetim için: bu cümleyi hangi model yazdı?"""
    istemci = _istemci([_cevap("Aksiyon gerekmiyor, stok yeterli.")])

    gerekce = gerekce_uret(aday, istemci)

    assert gerekce.model_adi == istemci.ayar.llm_model_adi


def test_uretici_protokole_uyuyor(aday: DecisionCandidate):
    """`llm_ureteci` guard'ın beklediği imzayı veriyor mu."""
    istemci = _istemci([_cevap("Stok yeterli."), _cevap("Stok yeterli.")])
    uret = llm_ureteci(istemci)

    assert uret(aday) == "Stok yeterli."
    assert uret(aday, onceki_red=[9999.0]) == "Stok yeterli."


# --- Gerçek karar motoruyla ---------------------------------------------------


def test_gercek_motorun_sablonu_zincirden_geciyor():
    """Gerçek motor + sahte model kapalı → şablon, ve şablon guard'dan geçiyor."""

    def isleyici(istek: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("baglanti yok")

    gercek = stok_karari_uret()
    istemci = OllamaIstemcisi(_ayar(), transport=httpx.MockTransport(isleyici))

    gerekce = gerekce_uret(gercek, istemci)

    assert gerekce.guard_sonucu is GuardSonucu.SABLONA_DUSTU
    assert gerekce.metin
