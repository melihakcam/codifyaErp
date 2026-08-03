"""Gerçek gerekçe üretimi testleri (Faz 2 B2.4).

⚠️ Hiçbiri gerçek modeli çalıştırmaz — sahte cevaplarla.

Kabul ölçütü ("10 gerçek karar için üretilen gerekçelerin Türkçesi anlaşılır
ve sayıları doğru") insan gözüyle ayrıca ölçülür ve
`dokumantasyon/OLCUMLER.md`'ye yazılır. Buradaki testler o ölçümün dayandığı
mantığı sınar: isteme hangi sayılar konuyor, guard zinciri bağlı mı, model
patlarsa ne oluyor.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.contracts import DecisionCandidate, GuardSonucu, KararTipi
from app.core.config import Ayarlar
from app.domain.stock.decide import decide_stub, stok_karari_uret
from app.llm.client import OllamaIstemcisi
from app.llm.explain import (
    anlatilacak_sayi_var_mi,
    egitilmis_istem_kur,
    gerekce_uret,
    ilk_cumleleri_al,
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


def test_istem_karar_yonunu_hazir_veriyor(aday: DecisionCandidate):
    """⭐ Modelden `232 < 656,57` karşılaştırmasını beklemiyoruz.

    Ölçümde tam bu koptu: model "656,57 adetlik yeniden sipariş noktasının
    ÜSTÜNE ulaştı" yazdı, oysa karar `stok.siparis` — altına düşmüştü. Guard
    sessiz kaldı çünkü iki sayı da izinliydi; uydurulan şey sayı değil ilişki.

    Yön kural motorunun kararından zaten belli, hazır veriliyor.
    """
    assert "ALTINA düştü" in istem_kur(aday)  # stub bir sipariş kararı

    yok = aday.model_copy(update={"tip": KararTipi.STOK_AKSIYON_YOK})
    assert "ÜZERİNDE" in istem_kur(yok)


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


# --- Eğitilmiş model kipi (Faz 3) ---------------------------------------------


def test_egitilmis_istem_gorev_etiketiyle_basliyor(aday: DecisionCandidate):
    """⭐ Router ile gerekçe tek modelde eğitildi; ayrım bu satırdan yapılıyor."""
    istem = egitilmis_istem_kur(aday)

    assert istem.startswith("GOREV: gerekce\n")
    assert istem.rstrip().endswith("GEREKCE:")


def test_egitilmis_istem_URUN_ADINI_TASIYOR(aday: DecisionCandidate):
    """⭐ Taban kipin TAM TERSİ — ve bu bilinçli.

    B2.4'te adı çıkarmıştım çünkü taban model bozuyordu ("Astar Boya" →
    *starboy*). Ama eğitim verisindeki gerekçelerin **%100'ünde** ad geçiyor;
    isteme koymazsak model *yoktan ad uydurmayı* öğrenmiş olur (B3.1 kararı).

    Bu test iki kipin farkını kilitliyor: biri adı koyar, diğeri koymaz, ve
    ikisi de doğrudur — çünkü farklı modellere konuşuyorlar.
    """
    assert aday.ozellikler.sku_adi in egitilmis_istem_kur(aday)
    assert aday.ozellikler.sku_adi not in istem_kur(aday)


def test_egitilmis_istem_etiketleri_egitimdekiyle_ayni(aday: DecisionCandidate):
    """⚠️ Etiketlerde Türkçe karakter YOK — eğitim verisi böyle üretildi.

    "gunluk", "suresi" yazımını düzeltmek cazip ama model bunu gördü.
    Değiştirmek eğitimin kazandırdığını çöpe atar.
    """
    istem = egitilmis_istem_kur(aday)

    assert "gunluk ortalama talep (adet):" in istem
    assert "tedarik suresi (gun):" in istem
    assert "günlük" not in istem  # Türkçe yazım eğitimde yoktu


def test_egitilmis_istem_kural_ve_ornek_TASIMIYOR(aday: DecisionCandidate):
    """Davranış ağırlıklara işlendi; kural listesi ve few-shot gereksiz.

    Yan faydası hız: taban istem ~600 token, bu ~60.
    """
    istem = egitilmis_istem_kur(aday)

    assert "Kurallar:" not in istem
    assert "ÖRNEK" not in istem
    assert len(istem) < len(istem_kur(aday))


def test_istem_bicimi_ayara_gore_seciliyor(aday: DecisionCandidate):
    """`llm_istem_bicimi` hangi istemin gideceğini belirliyor."""
    gonderilen: list[str] = []

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.append(json.loads(istek.content)["prompt"])
        return httpx.Response(
            200,
            json={
                "model": "sahte",
                "response": _cevap("Stok yeterli."),
                "eval_count": 5,
                "eval_duration": 1_000_000_000,
                "load_duration": 0,
            },
        )

    for bicim, beklenen in (("taban", False), ("egitilmis", True)):
        ayar = Ayarlar(
            ollama_base_url="http://sahte:11434",
            llm_yeniden_deneme=0,
            llm_istem_bicimi=bicim,
        )
        istemci = OllamaIstemcisi(ayar, transport=httpx.MockTransport(isleyici))
        gonderilen.clear()
        llm_ureteci(istemci)(aday)

        assert gonderilen, f"{bicim}: istek gitmedi"
        assert gonderilen[0].startswith("GOREV: gerekce") is beklenen


# --- Cümle kırpma -------------------------------------------------------------


def test_ucuncu_cumle_kirpiliyor():
    """⭐ "En fazla 2 cümle" talimatı da token sınırı da yetmedi.

    Model kuralı kabul edip yine de dolgu bir üçüncü cümle ekliyordu. Modele
    yalvarmak yerine kırpmak deterministik ve bedava.
    """
    metin = (
        "Kullanılabilir stok 10 adede inerek altına düştü. "
        "Günlük 0,31 adetlik tüketimle 60 adet sipariş öneriliyor. "
        "Bu durumda hedef servis seviyesi %90'ı karşılayacak şekilde oluşuyor."
    )

    kirpilmis = ilk_cumleleri_al(metin)

    assert kirpilmis.endswith("60 adet sipariş öneriliyor.")
    assert "hedef servis" not in kirpilmis


def test_binlik_ayraci_cumle_sonu_sanilmiyor():
    """⚠️ Naif `split(".")` Türkçede çalışmaz: 2.707,43 içindeki nokta da nokta.

    Desen noktadan sonra boşluk arıyor; binlik ayracında boşluk yok.
    """
    metin = "Elde kalan 12 adet 2.707,43 TL'lik sermayeyi bağlıyor. Tasfiye öneriliyor."

    assert ilk_cumleleri_al(metin) == metin


def test_urun_olculeri_bolunmuyor():
    """`Alçıpan 12.5mm` gibi ölçüler cümle sonu sanılmamalı."""
    metin = "Alçıpan 12.5mm için 60 adet sipariş öneriliyor."

    assert ilk_cumleleri_al(metin) == metin


def test_iki_cumleden_kisa_metin_bozulmuyor():
    metin = "Stok yeterli, aksiyon gerekmiyor."

    assert ilk_cumleleri_al(metin) == metin


def test_kirpma_guarddan_once_yapiliyor(aday: DecisionCandidate):
    """Atılan cümledeki uydurma sayı guard'a hiç ulaşmamalı.

    Ulaşsaydı guard metni reddeder ve iyi olan ilk iki cümle boşuna şablona
    düşerdi — kullanıcıya zaten gitmeyecek bir cümle yüzünden.
    """
    metin = (
        "Günlük 42 adet tüketim var. "
        "Kullanılabilir stok 270 adede düştü. "
        "Toplam 9999 adet uydurma sayı burada."
    )
    istemci = _istemci([_cevap(metin)])

    gerekce = gerekce_uret(aday, istemci)

    assert gerekce.guard_sonucu is GuardSonucu.GECTI
    assert "9999" not in gerekce.metin


# --- Anlatacak sayısı olmayan kararlar ----------------------------------------


def test_sayilari_olan_karar_modele_gidiyor(aday: DecisionCandidate):
    assert anlatilacak_sayi_var_mi(aday)


def test_tum_sayilari_sifir_olan_karar_modele_GITMIYOR(aday: DecisionCandidate):
    """⭐ B2.4 ölçümünde 10 kararın 2'si böyleydi: talep 0, stok 0, ROP 0.

    Modelden "hiçbir şey yok" durumundan cümle istemek, olmayan bir sebep
    uydurmasını davet ediyor — ölçümde gerçekten öyle oldu ("stok yönetimi
    kurallarını taklit eden bir durumdur"). Guard yakalayamaz, çünkü uydurulan
    şey sayı değil sebep.
    """
    # Ölçümdeki iki vaka da `aksiyon_yok`'tu. `stok.siparis` için bu durum
    # zaten imkânsız: sözleşme tedarik süresine `gt=0` koyuyor.
    o = aday.ozellikler.model_copy(
        update={"eldeki_stok": 0, "rezerve_stok": 0, "yoldaki_stok": 0, "ort_gunluk_talep": 0.0}
    )
    sifirli = aday.model_copy(
        update={
            "tip": KararTipi.STOK_AKSIYON_YOK,
            "ozellikler": o,
            "tetiklenen_kurallar": [],
            "aksiyon": {},
        }
    )

    assert not anlatilacak_sayi_var_mi(sifirli)

    # İstemci hiç çağrılmamalı: cevap listesi boş, çağrılsa patlardı
    istemci = _istemci([])
    gerekce = gerekce_uret(sifirli, istemci)

    assert gerekce.guard_sonucu is GuardSonucu.SABLONA_DUSTU
    assert gerekce.model_adi is None
    assert gerekce.uretim_ms == 0  # model çalışmadı


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
