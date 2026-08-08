"""Router testleri (Faz 2 B2.3).

⚠️ Hiçbiri gerçek modeli çalıştırmaz.

Doğruluk ölçümü ayrı: `training/eval/router_taban.py` gerçek modelle 30 soruyu
koşturur ve sonucu `dokumantasyon/OLCUMLER.md`'ye yazılır. Buradaki testler o
ölçümün dayandığı mantığı sınar — prompt kurulumu, hata yolları, sözleşme
uyumu.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Ayarlar
from app.llm.client import LLMErisilemiyor, OllamaIstemcisi
from app.llm.router import (
    ARAC_ACIKLAMALARI,
    ORNEKLER,
    egitilmis_istem,
    sistem_istemi,
    soruyu_yonlendir,
)
from app.llm.schemas import AracAdi, SemaUyumsuz
from app.main import app


def _ayar() -> Ayarlar:
    return Ayarlar(ollama_base_url="http://sahte:11434", llm_yeniden_deneme=0)


def _istemci(cevaplar: list[str]) -> OllamaIstemcisi:
    kalan = list(cevaplar)

    def isleyici(istek: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "sahte",
                "response": kalan.pop(0) if kalan else "",
                "eval_count": 12,
                "eval_duration": 500_000_000,
            },
        )

    return OllamaIstemcisi(_ayar(), transport=httpx.MockTransport(isleyici))


# --- Eğitilmiş model kipi (Faz 3) ---------------------------------------------


def test_egitilmis_istem_egitim_bicimiyle_ayni():
    """⭐ `training/train_lora.ipynb`'deki `router_metni()` ile birebir aynı.

    Model eğitimde tam olarak bu satırları gördü. Bir satır bile kayarsa
    tanımadığı bir girdiyle karşılaşır ve eğitimin kazandırdığı kaybolur.
    """
    istem = egitilmis_istem("kritik stok var mi")

    assert istem == "GOREV: router\nSORU: kritik stok var mi\n\nARAC:"


def test_egitilmis_istem_arac_listesi_TASIMIYOR():
    """Araç listesi ve few-shot ağırlıklara işlendi; istemde olması gereksiz.

    Yan faydası hız: taban sistem promptu ~600 token, bu ~15.
    """
    istem = egitilmis_istem("kritik stok var mi")

    for arac in AracAdi:
        assert arac.value not in istem
    assert len(istem) < len(sistem_istemi()) / 10


def test_istem_bicimi_ayara_gore_seciliyor():
    """`llm_istem_bicimi` hangi istemin ve sistem promptunun gideceğini belirler."""
    gonderilen: list[dict] = []

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.append(json.loads(istek.content))
        return httpx.Response(
            200,
            json={
                "model": "sahte",
                "response": json.dumps(
                    {"arac": "kritik_stok_sorgula", "parametreler": {}}, ensure_ascii=False
                ),
                "eval_count": 12,
                "eval_duration": 500_000_000,
            },
        )

    for bicim, egitilmis_mi in (("taban", True), ("egitilmis", False)):
        ayar = Ayarlar(
            ollama_base_url="http://sahte:11434",
            llm_yeniden_deneme=0,
            llm_istem_bicimi=bicim,
        )
        istemci = OllamaIstemcisi(ayar, transport=httpx.MockTransport(isleyici))
        gonderilen.clear()
        soruyu_yonlendir(istemci, "kritik stok var mi")

        istek = gonderilen[0]
        # Taban kipte sistem promptu VAR, eğitilmiş kipte YOK
        assert bool(istek.get("system")) is egitilmis_mi, bicim
        assert istek["prompt"].startswith("GOREV: router") is not egitilmis_mi, bicim


# --- Sistem promptu -----------------------------------------------------------


def test_sistem_istemi_yedi_araci_da_tanitiyor():
    """Modelin seçemeyeceği araç, prompt'ta olmayan araçtır."""
    istem = sistem_istemi()
    for arac in AracAdi:
        assert arac.value in istem


def test_sistem_istemi_parametre_bilgisini_tasiyor():
    istem = sistem_istemi()
    assert "parametre: kategori" in istem
    assert "parametre almaz" in istem


def test_her_arac_icin_aciklama_var():
    assert set(ARAC_ACIKLAMALARI) == set(AracAdi)


def test_ornekler_dolayli_ifadelerden_secilmis():
    """⭐ B2.2 ön ölçümünde model açık sorularda zaten iyiydi.

    Few-shot örneklerini modelin zaten bildiği yerden seçmek boşa bağlam
    olurdu; hataların tamamı dolaylı ifadelerdeydi.
    """
    sorular = [s for s, _ in ORNEKLER]
    assert "Kuyrukta ne var?" in sorular
    assert "Dün gece ne bulundu?" in sorular
    # Örneklerdeki cevaplar geçerli araç adları olmalı.
    gecerli = {a.value for a in AracAdi}
    for _, cevap in ORNEKLER:
        assert json.loads(cevap)["arac"] in gecerli


# --- Yönlendirme --------------------------------------------------------------


def test_gecerli_cevap_araca_cevrilir():
    istemci = _istemci(['{"arac": "kritik_stok_sorgula", "parametreler": {"kategori": "Boya"}}'])

    sonuc = soruyu_yonlendir(istemci, "Boya kategorisinde kritik stok var mı?")

    assert sonuc.cagri.arac is AracAdi.KRITIK_STOK
    assert sonuc.cagri.parametreler == {"kategori": "Boya"}
    assert sonuc.deneme_sayisi == 1


def test_uydurma_arac_reddedilir_ve_yeniden_denenir():
    """Model olmayan bir araç uydurursa kabul edilmemeli."""
    istemci = _istemci(
        [
            '{"arac": "stok_sil", "parametreler": {}}',
            '{"arac": "olu_stok_sorgula", "parametreler": {}}',
        ]
    )

    sonuc = soruyu_yonlendir(istemci, "hareketsiz ürünler")

    assert sonuc.deneme_sayisi == 2
    assert sonuc.cagri.arac is AracAdi.OLU_STOK


def test_israrla_uydurursa_sema_uyumsuz():
    """Tahmin etmektense cevapsız bırakmak doğru."""
    istemci = _istemci(['{"arac": "stok_sil"}', '{"arac": "urun_ekle"}'])

    with pytest.raises(SemaUyumsuz):
        soruyu_yonlendir(istemci, "bilinmeyen bir sey")


def test_model_erisilemezse_hata_yukari_tasinir():
    """Router'ın şablon karşılığı yok — 'hangi araç' sorusunun deterministik
    cevabı olmadığı için sessizce tahmin edilmemeli."""

    def isleyici(istek: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("yok", request=istek)

    istemci = OllamaIstemcisi(_ayar(), transport=httpx.MockTransport(isleyici))

    with pytest.raises(LLMErisilemiyor):
        soruyu_yonlendir(istemci, "soru")


# --- /v1/ask ucu --------------------------------------------------------------


def _ask_istemcisi(monkeypatch: pytest.MonkeyPatch, cevaplar: list[str]) -> TestClient:
    """`ask.py` içindeki istemci kurulumunu sahte taşımayla değiştirir."""
    kalan = list(cevaplar)

    def isleyici(istek: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "sahte",
                "response": kalan.pop(0) if kalan else "",
                "eval_count": 12,
                "eval_duration": 500_000_000,
            },
        )

    def sahte_istemci(*_: Any, **__: Any) -> OllamaIstemcisi:
        return OllamaIstemcisi(_ayar(), transport=httpx.MockTransport(isleyici))

    monkeypatch.setattr("app.api.ask.OllamaIstemcisi", sahte_istemci)
    return TestClient(app)


def test_ask_ucu_araci_dondurur(monkeypatch: pytest.MonkeyPatch):
    istemci = _ask_istemcisi(monkeypatch, ['{"arac": "onay_kuyrugu_sorgula", "parametreler": {}}'])

    cevap = istemci.post("/v1/ask", json={"soru": "Kuyrukta ne var?"})

    assert cevap.status_code == 200
    govde = cevap.json()
    assert govde["arac"] == "onay_kuyrugu_sorgula"
    assert govde["parametreler"] == {}


def test_ask_ucu_yonlendiremezse_422(monkeypatch: pytest.MonkeyPatch):
    """Anlaşılmayan soruya tahminle cevap vermektense 422 dönmek doğru."""
    istemci = _ask_istemcisi(monkeypatch, ["bozuk", "yine bozuk"])

    cevap = istemci.post("/v1/ask", json={"soru": "anlamsiz bir sey"})

    assert cevap.status_code == 422


def test_ask_ucu_model_yoksa_503(monkeypatch: pytest.MonkeyPatch):
    def isleyici(istek: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("yok", request=istek)

    def sahte_istemci(*_: Any, **__: Any) -> OllamaIstemcisi:
        return OllamaIstemcisi(_ayar(), transport=httpx.MockTransport(isleyici))

    monkeypatch.setattr("app.api.ask.OllamaIstemcisi", sahte_istemci)

    cevap = TestClient(app).post("/v1/ask", json={"soru": "soru"})

    assert cevap.status_code == 503


def test_bos_soru_reddedilir():
    assert TestClient(app).post("/v1/ask", json={"soru": ""}).status_code == 422


# --- Taban çizgi soru seti ----------------------------------------------------


def test_taban_soru_seti_dengeli_ve_gecerli():
    """⭐ Ölçümün güvenilirliği soru setinin dengesine bağlı.

    Yalnızca açık sorularla ölçmek sayıyı yanıltıcı yüksek gösterir ve LoRA
    sonrası iyileşmeyi göremeyiz.
    """
    from training.eval.router_taban import kayitlari_yukle

    kayitlar = kayitlari_yukle()
    gecerli_araclar = {a.value for a in AracAdi}

    assert len(kayitlar) == 30
    assert {k.beklenen_arac for k in kayitlar} == gecerli_araclar, "7 araç da temsil edilmeli"

    stiller = {k.stil for k in kayitlar}
    assert {"acik", "dolayli", "gunluk"} <= stiller

    dolayli = sum(k.stil == "dolayli" for k in kayitlar)
    assert dolayli >= 10, "dolaylı ifadeler yeterince temsil edilmeli"


def test_beklenen_parametre_her_zaman_soruda_geciyor():
    """⭐ Beklenen değer soruda geçmiyorsa model onu üretemez.

    Böyle bir bekleyiş ölçümü haksız yere düşürür — modelin bilemeyeceği bir
    şeyi istemiş oluruz.
    """
    from training.eval.router_taban import kayitlari_yukle

    for k in kayitlari_yukle():
        for ad, kabul_edilenler in k.beklenen_parametreler.items():
            gecen = [d for d in kabul_edilenler if d.casefold() in k.soru.casefold()]
            assert gecen, f"{k.soru!r} · {ad}: hiçbir kabul edilen biçim soruda geçmiyor"


def test_sku_parametresi_hem_adi_hem_kodu_kabul_ediyor():
    """⭐ Eğitim verisinde `sku_adi` ürün ADINI değil KODUNU taşıyor.

    Model eğitimden sonra kod üretmeye başlarsa katı karşılaştırma doğru
    cevabı yanlış sayar ve LoRA öncesi/sonrası kıyaslaması geçersiz olur.
    """
    from training.eval.router_taban import kayitlari_yukle

    sku_kayitlari = [k for k in kayitlari_yukle() if "sku_id" in k.beklenen_parametreler]
    assert sku_kayitlari, "sipariş önerisi soruları parametreli olmalı"

    for k in sku_kayitlari:
        kabul = k.beklenen_parametreler["sku_id"]
        assert any(d.upper().startswith("S-") for d in kabul), (
            f"{k.soru!r}: SKU kodu kabul edilmiyor"
        )
        assert any(not d.upper().startswith("S-") for d in kabul), (
            f"{k.soru!r}: ürün adı kabul edilmiyor"
        )


# --- Çöküş dedektörü ----------------------------------------------------------


def test_cokus_tespit_ediliyor():
    """⭐ Dengesiz eğitim verisiyle model tek araca yığılabilir.

    Kişi A'nın val/test bölmeleri de aynı dengesizlikte (siparis_onerisi
    %95,6), yani hep aynı cevabı veren bir model ONUN test setinde %95
    doğruluk gösterir. Bu çarpıklığı görebilecek tek ölçüm dengeli olan bu set.
    """
    from training.eval.router_taban import Kayit, cokus_kontrolu

    cokmus_kayitlar = [
        Kayit(soru=f"s{i}", stil="acik", beklenen_arac="olu_stok_sorgula") for i in range(10)
    ]
    for k in cokmus_kayitlar:
        k.secilen_arac = "siparis_onerisi_sorgula"

    cokmus, arac, pay = cokus_kontrolu(cokmus_kayitlar)
    assert cokmus is True
    assert arac == "siparis_onerisi_sorgula"
    assert pay == 1.0


def test_dengeli_dagilim_cokus_saymaz():
    from training.eval.router_taban import Kayit, cokus_kontrolu

    araclar = [a.value for a in AracAdi]
    kayitlar = []
    for i, a in enumerate(araclar * 3):
        k = Kayit(soru=f"s{i}", stil="acik", beklenen_arac=a)
        k.secilen_arac = a
        kayitlar.append(k)

    cokmus, _, pay = cokus_kontrolu(kayitlar)
    assert cokmus is False
    assert pay < 0.40


# --- Parametre halüsinasyonu --------------------------------------------------


def test_soruda_gecmeyen_parametre_uydurma_sayilir():
    """Model parametreyi ancak sorudan çıkarabilir."""
    from training.eval.router_taban import Kayit

    k = Kayit(soru="Kritik stok var mı?", stil="acik", beklenen_arac="kritik_stok_sorgula")
    k.secilen_arac = "kritik_stok_sorgula"
    k.secilen_parametreler = {"kategori": "seramik"}

    assert k.uydurma_parametre == ["kategori=seramik"]


def test_soruda_gecen_parametre_uydurma_sayilmaz():
    from training.eval.router_taban import Kayit

    k = Kayit(soru="Boya kategorisinde kritik stok var mı?", stil="acik", beklenen_arac="x")
    k.secilen_parametreler = {"kategori": "Boya"}

    assert k.uydurma_parametre == []


def test_aksansiz_yazilan_soruda_aksanli_cevap_uydurma_sayilmaz():
    """Kullanıcı aksansız yazınca modelin doğru normalleştirmesi cezalanmasın.

    3. tur ölçümünde raporlanan 4 uydurmanın 1'i buydu: *"dun gece ne cikti"*
    sorusuna model `tarih_ifadesi="dün"` üretti — altın etiket bunu zaten kabul
    ediyor (`["dün", "dun"]`) ama düz altdizi araması `"dün"`ü soruda bulamayıp
    uydurma saydı. Dedektör doğru davranışı yanlış olarak raporluyordu.
    """
    from training.eval.router_taban import Kayit

    k = Kayit(
        soru="dun gece ne cikti",
        stil="kisa",
        beklenen_arac="gecelik_ozet_sorgula",
        beklenen_parametreler={"tarih_ifadesi": ["dün", "dun"]},
    )
    k.secilen_arac = "gecelik_ozet_sorgula"
    k.secilen_parametreler = {"tarih_ifadesi": "dün"}

    assert k.uydurma_parametre == []
    assert k.tam_dogru


def test_normallestirme_gercek_uydurmayi_gizlemiyor():
    """Aksan katlaması dedektörü körleştirmemeli.

    Asıl vaka bu: soruda hiçbir tarih ifadesi yokken model `"geçen gün"`
    üretiyor — 3. turdaki gerçek 3 uydurmanın deseni. Normalleştirme bunu
    hâlâ yakalamalı.
    """
    from training.eval.router_taban import Kayit

    k = Kayit(soru="gece raporu", stil="kisa", beklenen_arac="gecelik_ozet_sorgula")
    k.secilen_arac = "gecelik_ozet_sorgula"
    k.secilen_parametreler = {"tarih_ifadesi": "geçen gün"}

    assert k.uydurma_parametre == ["tarih_ifadesi=geçen gün"]


def test_aksansiz_turkce_harfleri_katliyor():
    from training.eval.router_taban import aksansiz

    assert aksansiz("ÇĞİIÖŞÜ") == "cgiiosu"
    assert aksansiz("çğıöşü") == "cgiosu"
    # Katlama yalnızca aksanı düşürür; farklı harfleri eşitlemez.
    assert aksansiz("boya") != aksansiz("boye")


# --- Esnek parametre karşılaştırması ------------------------------------------


def test_kabul_edilen_biçimlerden_biri_yeterli():
    from training.eval.router_taban import Kayit

    k = Kayit(
        soru="Kırmızı Tuğla (S-01432) için sipariş",
        stil="acik",
        beklenen_arac="siparis_onerisi_sorgula",
        beklenen_parametreler={"sku_id": ["Kırmızı Tuğla", "S-01432"]},
    )
    k.secilen_arac = "siparis_onerisi_sorgula"

    k.secilen_parametreler = {"sku_id": "S-01432"}
    assert k.tam_dogru, "SKU kodu kabul edilmeli"

    k.secilen_parametreler = {"sku_id": "kırmızı tuğla"}
    assert k.tam_dogru, "ürün adı (harf duyarsız) kabul edilmeli"

    k.secilen_parametreler = {"sku_id": "Beyaz Tuğla"}
    assert not k.tam_dogru, "yanlış ürün kabul edilmemeli"


def test_cokus_esigi_arac_sayisina_gore_kayiyor():
    """⭐ Sabit %40 eşiği az araçlı setlerde YANLIŞ ALARM veriyordu.

    `router_ek_sorular.jsonl` yalnızca üç aracı kapsıyor; orada dengeli
    dağılım zaten ~%33, yani sabit %40 normal davranışı çöküş sayıyor. İlk ek
    koşuda tam bu oldu: taban model %50 payla "ÇÖKÜŞ" damgası yedi.

    Eşik artık `2,5 / araç_sayısı` ile ölçekleniyor. Kritik olan: taban setin
    (7 araç) eşiği DEĞİŞMEMELİ, yoksa %70,0 karşılaştırması geçersiz olur.
    """
    from training.eval.router_taban import COKUS_ESIGI, Kayit, cokus_esigi

    def kayitlar_uret(arac_sayisi: int) -> list[Kayit]:
        araclar = [a.value for a in AracAdi][:arac_sayisi]
        return [
            Kayit(soru=f"s{i}", stil="acik", beklenen_arac=a) for i, a in enumerate(araclar * 3)
        ]

    # Taban set: 7 araç -> 2,5/7 = 0,357, COKUS_ESIGI tabanı devrede kalıyor.
    assert cokus_esigi(kayitlar_uret(7)) == COKUS_ESIGI

    # Ek set: 3 araç -> dengeli pay zaten %33, eşik yukarı kaymalı.
    assert cokus_esigi(kayitlar_uret(3)) > COKUS_ESIGI


def test_cokus_esigi_hicbir_sette_ulasilamaz_olmuyor():
    """⭐ Tavan olmazsa dedektör sessizce işlevsizleşiyor.

    Ölçekleme tek başına bırakılırsa tek araçlı bir sette eşik %250 çıkar;
    pay tanımı gereği en fazla %100 olabileceği için dedektör hiçbir zaman
    ateşlenemez. Sessiz işlevsizlik, yanlış alarmdan daha tehlikeli — kimse
    fark etmez.
    """
    from training.eval.router_taban import Kayit, cokus_esigi

    for arac_sayisi in range(1, 8):
        araclar = [a.value for a in AracAdi][:arac_sayisi]
        kayitlar = [
            Kayit(soru=f"s{i}", stil="acik", beklenen_arac=a) for i, a in enumerate(araclar)
        ]
        esik = cokus_esigi(kayitlar)
        assert esik < 1.0, f"{arac_sayisi} araç: eşik %{esik * 100:.0f} — asla ulaşılamaz"


def test_kosular_birbirinin_sonucunu_ezmiyor():
    """⭐ Her koşu aynı JSON'a yazıyordu — sessiz veri kaybı.

    Taban çizgi, ek set, 1. tur, 2. tur: hepsi `router_taban_sonuc.json`'a
    yazıyordu, yani dosya her zaman yalnızca *en son* koşuyu tutuyordu.
    Docstring'in "modeli tekrar çalıştırmaya gerek kalmasın" vaadi
    tutulmuyordu.

    Nasıl yakalandı: bayrak kombinasyonunu denemek için var olmayan bir
    modele koşturulan ve 18/18 hata veren bir deneme, taban çizgi kaydını
    sildi. Hiçbir uyarı çıkmadı — asıl tehlike bu.
    """
    from training.eval.router_taban import SONUC_DOSYASI, sonuc_yolu

    # Donmus taban cizgi kendi adini korumali (varsayilan etiket dahil).
    assert sonuc_yolu("taban") == SONUC_DOSYASI
    assert sonuc_yolu("taban-cizgi-egitim-oncesi") == SONUC_DOSYASI

    # Diger her etiket ayri dosyaya gitmeli, hicbiri digerini ezmemeli.
    yollar = [sonuc_yolu(e) for e in ("taban-ek", "lora-tur2", "lora-tur3", "lora-tur3-ek")]
    assert len(set(yollar)) == len(yollar)
    assert SONUC_DOSYASI not in yollar

    # Etiket dosya adina giriyor; yol kacisi olusturamamali.
    kotu = sonuc_yolu("../../etc/parola")
    assert kotu.parent == SONUC_DOSYASI.parent


def test_cekim_gucu_cop_kutusu_sinifi_gosteriyor():
    """⭐ Genel doğruluk, bir sınıfın 'çöp kutusu' olduğunu GİZLER.

    Bir sınıf başka sınıfların sorularını kapıyorsa kendi doğruluğu iyi
    görünür ve kaybeden sınıfın düşüşüyle toplamda dengelenebilir — genel
    yüzde hiç kıpırdamaz.

    2. turda gerçekten böyle oldu: `genel_stok_durumu` ve `onay_kuyrugu`
    beklenenden fazla seçildi, dört hatanın dördü o iki sınıfa aktı, ama
    bu `router_lora_tur2_sonuc.json`'da fark edilmeden durdu.
    """
    from training.eval.router_taban import Kayit, cekim_gucu

    kayitlar = []
    # 'cop' sinifi 2 kez bekleniyor, ama 4 soruyu birden kapiyor.
    for i in range(2):
        k = Kayit(soru=f"c{i}", stil="acik", beklenen_arac="cop")
        k.secilen_arac = "cop"
        kayitlar.append(k)
    for i in range(2):
        k = Kayit(soru=f"k{i}", stil="acik", beklenen_arac="kurban")
        k.secilen_arac = "cop"  # kurban'in sorulari cop'a gidiyor
        kayitlar.append(k)

    cekim = cekim_gucu(kayitlar)
    assert cekim["cop"] == (2, 4), "cop fazla secilmis olarak gorunmeli"
    assert cekim["kurban"] == (2, 0), "kurban hic secilmemis olarak gorunmeli"

    # Asil nokta: cekim farki pozitifken kurban negatif.
    assert cekim["cop"][1] - cekim["cop"][0] > 0
    assert cekim["kurban"][1] - cekim["kurban"][0] < 0


def test_kayitli_sonuc_modelsiz_yeniden_puanlanabiliyor():
    """⭐ Modül 'modeli tekrar çalıştırmaya gerek kalmasın' diye söz veriyordu.

    Ama bunu yapacak bir yol yoktu: kayıtlı sonuca bakmak için her seferinde
    tek kullanımlık betik yazmak gerekiyordu. `--rapor` boşluğu kapattı.

    Puanlama JSON'a gömülü değil, `Kayit`'in property'lerinden geliyor —
    yani puanlama mantığı değişirse eski ölçüm yeni mantıkla yeniden
    puanlanır. Amaç zaten buydu.
    """
    import json
    import tempfile
    from pathlib import Path

    from training.eval.router_taban import Kayit, sonuctan_yukle, sonucu_kaydet

    k = Kayit(soru="Genel stok durumu nedir?", stil="acik", beklenen_arac="genel")
    k.secilen_arac = "genel"
    k.uretim_ms = 123

    with tempfile.TemporaryDirectory() as gecici:
        yol = Path(gecici) / "sonuc.json"
        govde = {
            "etiket": "deneme",
            "ozet": {},
            "kayitlar": [
                {
                    "soru": k.soru,
                    "stil": k.stil,
                    "beklenen_arac": k.beklenen_arac,
                    "beklenen_parametreler": k.beklenen_parametreler,
                    "secilen_arac": k.secilen_arac,
                    "secilen_parametreler": k.secilen_parametreler,
                    "hata": k.hata,
                    "uretim_ms": k.uretim_ms,
                    "deneme": k.deneme,
                }
            ],
        }
        yol.write_text(json.dumps(govde, ensure_ascii=False), encoding="utf-8")

        etiket, geri = sonuctan_yukle(yol)

    assert etiket == "deneme"
    assert len(geri) == 1
    assert geri[0].soru == k.soru
    assert geri[0].secilen_arac == "genel"
    # Puanlama JSON'dan degil property'den geliyor.
    assert geri[0].arac_dogru is True
    assert sonucu_kaydet is not None


def test_olcum_soguk_baslangicla_yapiliyor():
    """⭐ Sıcaklık 0 + sabit tohum tekrarlanabilirlik için YETMİYOR.

    Böyle sanılıyordu ve modülde de öyle yazıyordu. Ölçüldü, doğru değil:
    hiçbir kod değişmeden, aynı model digest'iyle taban çizgi 20/30 ile
    21/30 arasında oynadı. Belirleyici olan modelin ısınma durumuydu.

    1 soru = 3,3 puan. 3. tur %73,3 verirse "eğitim işe yaradı" mı yoksa
    ısınma farkı mı — ayırt edilemezdi. Bu yüzden `olc()` ölçüme başlamadan
    modeli düşürüyor.

    Bu test o çağrının yapıldığını doğruluyor; kaldırılırsa kırılır.
    """
    import contextlib
    from unittest.mock import patch

    from training.eval.router_taban import Kayit, olc

    with (
        patch("training.eval.router_taban.modeli_bellekten_at") as dusur,
        patch("training.eval.router_taban.OllamaIstemcisi"),
        patch("training.eval.router_taban.soruyu_yonlendir") as yonlendir,
    ):
        yonlendir.side_effect = RuntimeError("model cagrilmasin")
        kayitlar = [Kayit(soru="s", stil="acik", beklenen_arac="a")]
        with contextlib.suppress(RuntimeError):
            olc(kayitlar, ayrinti=False)

    assert dusur.called, "olc() olcume baslamadan modeli dusurmeli"
