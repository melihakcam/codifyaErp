"""Ollama istemcisi testleri (Faz 2 B2.1).

⚠️ Bu dosyadaki testlerin HİÇBİRİ gerçek modeli çalıştırmaz. `httpx`'in
`MockTransport`'u ile sahte cevap verilir — dolayısıyla:

· CI'da Ollama kurulu olmadan koşarlar,
· geliştirme sırasında işlemciyi hiç yormazlar.

Gerçek modelle yapılacak tek şey B2.1'in hız ölçümü; o ayrı ve elle yapılır.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.config import Ayarlar
from app.llm.client import LLMErisilemiyor, OllamaIstemcisi, UretimSonucu

# Ollama'nın gerçek cevabından sadeleştirilmiş örnek. Süreler NANOSANİYE.
ORNEK_CEVAP: dict[str, Any] = {
    "model": "qwen2.5:1.5b-instruct",
    "response": "Kırmızı Tuğla için 1.200 adet sipariş öneriliyor.",
    "done": True,
    "prompt_eval_count": 180,
    "eval_count": 42,
    "eval_duration": 7_000_000_000,  # 7 sn
    "load_duration": 350_000_000,  # 0,35 sn
    "total_duration": 7_400_000_000,
}


def ayar_ile(**degisiklikler: Any) -> Ayarlar:
    temel = {
        "ollama_base_url": "http://sahte:11434",
        "llm_model_adi": "qwen2.5:1.5b-instruct",
        "llm_timeout_sn": 5.0,
        "llm_iplik_sayisi": 4,
        "llm_yeniden_deneme": 2,
    }
    return Ayarlar(**(temel | degisiklikler))


def istemci_ile(isleyici) -> OllamaIstemcisi:
    return OllamaIstemcisi(ayar_ile(), transport=httpx.MockTransport(isleyici))


# --- Ölçüm --------------------------------------------------------------------


def test_token_hizi_modelin_kendi_raporundan_hesaplanir():
    """⭐ B2.1'in kabul ölçütü: saniyedeki token sayısı.

    Duvar saatinden değil modelin `eval_count` / `eval_duration` değerlerinden
    hesaplanır — aksi halde ağ gecikmesi ve model yükleme süresi de sayıya
    karışır ve ölçüm saf üretim hızını göstermez.
    """
    sonuc = istemci_ile(lambda _: httpx.Response(200, json=ORNEK_CEVAP)).uret("merhaba")

    assert sonuc.uretim_token == 42
    assert sonuc.uretim_ms == 7_000  # 7e9 ns -> 7000 ms
    assert sonuc.token_hizi == pytest.approx(6.0)  # 42 token / 7 sn


def test_yukleme_suresi_ayri_raporlanir():
    """İlk çağrıda model belleğe yüklenir; o süre üretim hızına karışmamalı."""
    sonuc = istemci_ile(lambda _: httpx.Response(200, json=ORNEK_CEVAP)).uret("merhaba")

    assert sonuc.yukleme_ms == 350
    assert sonuc.uretim_ms == 7_000


def test_uretim_suresi_sifirsa_hiz_sifir():
    """Sıfıra bölme olmamalı — model hiç token üretmediyse hız 0."""
    bos = ORNEK_CEVAP | {"eval_count": 0, "eval_duration": 0}
    sonuc = istemci_ile(lambda _: httpx.Response(200, json=bos)).uret("merhaba")

    assert sonuc.token_hizi == 0.0


def test_ozet_olcum_satiri_uretir():
    sonuc = istemci_ile(lambda _: httpx.Response(200, json=ORNEK_CEVAP)).uret("merhaba")
    ozet = sonuc.ozet()

    assert "6.0 token/sn" in ozet
    assert "iplik=4" in ozet


# --- Isı kontrolü -------------------------------------------------------------


def test_iplik_sayisi_her_istekte_gonderilir():
    """⭐ Isı kontrolünün asıl kolu.

    Ollama `num_thread` verilmezse tüm çekirdekleri kullanır. Dizüstü
    bilgisayarda bu sürekli tam yük demek — bu test o ayarın sessizce
    düşmesini engelliyor.
    """
    gonderilen: dict[str, Any] = {}

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.update(json.loads(istek.content))
        return httpx.Response(200, json=ORNEK_CEVAP)

    istemci_ile(isleyici).uret("merhaba")

    assert gonderilen["options"]["num_thread"] == 4


def test_iplik_sayisi_cagrida_ezilebilir():
    """B2.1'de farklı iplik sayılarıyla ölçüm yapabilmek için."""
    gonderilen: dict[str, Any] = {}

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.update(json.loads(istek.content))
        return httpx.Response(200, json=ORNEK_CEVAP)

    istemci = OllamaIstemcisi(ayar_ile(), iplik_sayisi=12, transport=httpx.MockTransport(isleyici))
    sonuc = istemci.uret("merhaba")

    assert gonderilen["options"]["num_thread"] == 12
    assert sonuc.iplik_sayisi == 12


def test_varsayilan_sicaklik_dusuk():
    """Gerekçede yaratıcılık istemiyoruz: aynı karara aynı cümle çıksın.

    Guard'ın davranışı tekrarlanabilir olmazsa B2.5'te hata ayıklamak imkânsız.
    """
    gonderilen: dict[str, Any] = {}

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.update(json.loads(istek.content))
        return httpx.Response(200, json=ORNEK_CEVAP)

    istemci_ile(isleyici).uret("merhaba")

    assert gonderilen["options"]["temperature"] <= 0.3


# --- İstek gövdesi ------------------------------------------------------------


def test_akis_kapali():
    """Ölçüm sayaçları yalnızca akış kapalıyken tek cevapta toplu gelir."""
    gonderilen: dict[str, Any] = {}

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.update(json.loads(istek.content))
        return httpx.Response(200, json=ORNEK_CEVAP)

    istemci_ile(isleyici).uret("merhaba")

    assert gonderilen["stream"] is False


def test_sema_verilirse_format_alanina_gecer():
    """B2.2'nin dayanağı: Ollama'ya JSON şeması zorlatmak."""
    gonderilen: dict[str, Any] = {}

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.update(json.loads(istek.content))
        return httpx.Response(200, json=ORNEK_CEVAP)

    sema = {"type": "object", "properties": {"tool": {"type": "string"}}}
    istemci_ile(isleyici).uret("merhaba", sema=sema)

    assert gonderilen["format"] == sema


def test_sema_verilmezse_format_alani_hic_gonderilmez():
    gonderilen: dict[str, Any] = {}

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.update(json.loads(istek.content))
        return httpx.Response(200, json=ORNEK_CEVAP)

    istemci_ile(isleyici).uret("merhaba")

    assert "format" not in gonderilen


def test_sistem_istemi_gonderilir():
    gonderilen: dict[str, Any] = {}

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.update(json.loads(istek.content))
        return httpx.Response(200, json=ORNEK_CEVAP)

    istemci_ile(isleyici).uret("merhaba", sistem="Sen bir ERP asistanısın.")

    assert gonderilen["system"] == "Sen bir ERP asistanısın."


# --- Hata yönetimi ------------------------------------------------------------


def test_baglanti_hatasinda_yeniden_denenir():
    denemeler = {"sayi": 0}

    def isleyici(istek: httpx.Request) -> httpx.Response:
        denemeler["sayi"] += 1
        if denemeler["sayi"] < 3:
            raise httpx.ConnectError("baglanti yok", request=istek)
        return httpx.Response(200, json=ORNEK_CEVAP)

    sonuc = istemci_ile(isleyici).uret("merhaba")

    assert denemeler["sayi"] == 3  # 1 ilk + 2 yeniden deneme
    assert sonuc.uretim_token == 42


def test_tum_denemeler_basarisizsa_llm_erisilemiyor():
    """Faz 4 graceful degradation: çağıran bunu yakalayıp şablona düşecek."""

    def isleyici(istek: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("baglanti yok", request=istek)

    with pytest.raises(LLMErisilemiyor):
        istemci_ile(isleyici).uret("merhaba")


def test_sunucu_hatasinda_yeniden_DENENMEZ():
    """⭐ 4xx istek hatasıdır — tekrarlamak aynı hatayı üretir, boşuna CPU yakar.

    Isı açısından da önemli: hatalı bir istemi üç kez göndermek işlemciyi üç
    kez çalıştırır.
    """
    denemeler = {"sayi": 0}

    def isleyici(istek: httpx.Request) -> httpx.Response:
        denemeler["sayi"] += 1
        return httpx.Response(400, text="gecersiz istek")

    with pytest.raises(LLMErisilemiyor, match="400"):
        istemci_ile(isleyici).uret("merhaba")

    assert denemeler["sayi"] == 1, "4xx'te yeniden deneme yapılmamalı"


def test_ayakta_mi_sunucu_yoksa_false_doner():
    """Çökmeden False dönmeli — ölçüm script'i buna bakıp erken çıkabilsin."""

    def isleyici(istek: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("baglanti yok", request=istek)

    assert istemci_ile(isleyici).ayakta_mi() is False


def test_ayakta_mi_sunucu_varsa_true_doner():
    istemci = istemci_ile(lambda _: httpx.Response(200, json={"models": []}))
    assert istemci.ayakta_mi() is True


def test_modeller_listelenir():
    cevap = {"models": [{"name": "qwen2.5:1.5b-instruct"}, {"name": "llama3.2:1b"}]}
    istemci = istemci_ile(lambda _: httpx.Response(200, json=cevap))

    assert istemci.modeller() == ["qwen2.5:1.5b-instruct", "llama3.2:1b"]


# --- Kaynak yönetimi ----------------------------------------------------------


def test_context_manager_olarak_kullanilabilir():
    with OllamaIstemcisi(
        ayar_ile(), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=ORNEK_CEVAP))
    ) as istemci:
        sonuc = istemci.uret("merhaba")

    assert isinstance(sonuc, UretimSonucu)
