"""Uçtan uca duman testi (Faz 0.5).

Bu test "iskelet ayakta mı" sorusunu cevaplar. Faz 2'de gerçek kural motoru
ve gerçek LLM devreye girdiğinde bu testin DEĞİŞMEMESİ beklenir — değişmesi
gerekiyorsa sözleşme sızmış demektir.

B1.5'te tek değişiklik: modül düzeyindeki `TestClient(app)` yerine `istemci`
fixture'ı kullanılıyor (`tests/conftest.py`). Sebebi mimari değil altyapı —
`decisions.py` artık DB'ye yazıyor, testler geliştirme veritabanına
dokunmamalı. Kontrol edilen davranışların hiçbiri değişmedi.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_kok_docse_yonlendirir(istemci: TestClient):
    """`localhost:8000` açan biri 404 değil Swagger görmeli."""
    cevap = istemci.get("/", follow_redirects=False)
    assert cevap.status_code in {307, 302}
    assert cevap.headers["location"] == "/docs"


def test_health_otonomi_seviyesini_gosterir(istemci: TestClient):
    cevap = istemci.get("/health")
    assert cevap.status_code == 200
    govde = cevap.json()
    assert govde["durum"] == "ayakta"
    # Sistemin hangi yetkiyle çalıştığı tek istekle görülebilmeli.
    assert govde["otonomi_seviyesi"] in {"shadow", "advisory", "threshold", "off"}


def test_karar_endpointi_gerekce_olmadan_doner(istemci: TestClient):
    """Varsayılan yol: LLM hiç çağrılmaz, gerekçe None."""
    cevap = istemci.post("/v1/decisions/stock/reorder-review")
    assert cevap.status_code == 200
    govde = cevap.json()

    assert govde["aday"]["tip"] == "stok.siparis"
    # Gerçek karar motoru + sabit seed'li demo dünyası (stok_karari_uret) ->
    # çağrıdan çağrıya sabit değer. LLM'e hiç bağlı değil.
    assert govde["aday"]["aksiyon"]["siparis_miktari"] == 60
    assert govde["politika"]["risk_skoru"] > 0
    assert govde["gerekce"] is None, "Karar yolu LLM'i beklememeli"


def test_karar_endpointi_gerekce_istenince_metin_doner(istemci: TestClient):
    cevap = istemci.post("/v1/decisions/stock/reorder-review?gerekce=true")
    assert cevap.status_code == 200
    govde = cevap.json()
    gerekce = govde["gerekce"]

    assert gerekce is not None
    # ⚠️ Gerçek LLM çağrısı (sıcaklık > 0, sabit tohum yok) — metin çalıştırmadan
    # çalıştırmaya değişebilir. Sabit olan şey: guard her zaman geçerli bir sonuç
    # döndürür (asla hata fırlatmaz) ve SKU adı -- LLM başarılı olsun ya da
    # şablona düşsün -- metinde geçer.
    assert gerekce["guard_sonucu"] in {"gecti", "yeniden_uretildi", "sablona_dustu"}
    assert govde["aday"]["ozellikler"]["sku_adi"] in gerekce["metin"]


def test_shadow_modda_karar_uygulanmaz(istemci: TestClient):
    """Varsayılan AUTONOMY_LEVEL=shadow olduğu için uygulandi False olmalı."""
    govde = istemci.post("/v1/decisions/stock/reorder-review").json()
    assert govde["politika"]["otonomi_seviyesi"] == "shadow"
    assert govde["politika"]["uygulandi"] is False
