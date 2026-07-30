"""Uçtan uca duman testi (Faz 0.5).

Bu test "iskelet ayakta mı" sorusunu cevaplar. Faz 2'de gerçek kural motoru
ve gerçek LLM devreye girdiğinde bu testin DEĞİŞMEMESİ beklenir — değişmesi
gerekiyorsa sözleşme sızmış demektir.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

istemci = TestClient(app)


def test_health_otonomi_seviyesini_gosterir():
    cevap = istemci.get("/health")
    assert cevap.status_code == 200
    govde = cevap.json()
    assert govde["durum"] == "ayakta"
    # Sistemin hangi yetkiyle çalıştığı tek istekle görülebilmeli.
    assert govde["otonomi_seviyesi"] in {"shadow", "advisory", "threshold", "off"}


def test_karar_endpointi_gerekce_olmadan_doner():
    """Varsayılan yol: LLM hiç çağrılmaz, gerekçe None."""
    cevap = istemci.post("/v1/decisions/stock/reorder-review")
    assert cevap.status_code == 200
    govde = cevap.json()

    assert govde["aday"]["tip"] == "stok.siparis"
    assert govde["aday"]["aksiyon"]["siparis_miktari"] == 1200
    assert govde["politika"]["risk_skoru"] > 0
    assert govde["gerekce"] is None, "Karar yolu LLM'i beklememeli"


def test_karar_endpointi_gerekce_istenince_metin_doner():
    cevap = istemci.post("/v1/decisions/stock/reorder-review?gerekce=true")
    assert cevap.status_code == 200
    gerekce = cevap.json()["gerekce"]

    assert gerekce is not None
    assert "Kırmızı Tuğla" in gerekce["metin"]
    assert "1.200" in gerekce["metin"], "Sayılar Türkçe biçimde olmalı"
    assert gerekce["guard_sonucu"] == "sablona_dustu"


def test_shadow_modda_karar_uygulanmaz():
    """Varsayılan AUTONOMY_LEVEL=shadow olduğu için uygulandi False olmalı."""
    govde = istemci.post("/v1/decisions/stock/reorder-review").json()
    assert govde["politika"]["otonomi_seviyesi"] == "shadow"
    assert govde["politika"]["uygulandi"] is False
