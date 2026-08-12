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

from app.core.config import Ayarlar, ayarlar
from app.main import app


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
    # ⚠️ Gerçek LLM çağrısı — metin çalıştırmadan çalıştırmaya, hatta hangi
    # modelin yapılandırıldığına göre değişir. Metnin **içeriğine** dair
    # varsayım yapılmıyor; bir önceki sürüm "SKU adı metinde geçer" diyordu ve
    # taban model devreye girince kırıldı: B2.4 istemi ürün adını bilinçli
    # olarak vermiyor (yalnızca `sablon_gerekce` adı yazar).
    #
    # Doğrulanan değişmezler:
    #   1. guard her zaman geçerli bir sonuç döndürür (asla hata fırlatmaz),
    #   2. metin boş değil,
    #   3. `model_adi` ile guard sonucu tutarlı — şablona düşüldüyse metin
    #      modelden gelmedi, `model_adi` None olmalı (bkz. guard.py).
    assert gerekce["guard_sonucu"] in {"gecti", "yeniden_uretildi", "sablona_dustu"}
    assert gerekce["metin"].strip()
    if gerekce["guard_sonucu"] == "sablona_dustu":
        assert gerekce["model_adi"] is None
    else:
        assert gerekce["model_adi"]


def test_shadow_modda_karar_uygulanmaz(istemci: TestClient):
    """Shadow modda karar üretilir, kaydedilir, UYGULANMAZ.

    ⚠️ Otonomi seviyesi **testte sabitleniyor**, `.env`'den okunmuyor.

    Faz 11'de `.env` `advisory`'ye alındı (otonomi yolu: önce öneri, sonra
    eşikli, giderek tam otomatik) ve bu test kırıldı — çünkü ortamdan gelen
    bir ayara bağlıydı. Shadow davranışını sınayan bir testin shadow modunu
    kendisi kurması gerekir; ortam değiştiğinde kırılan test, davranışı
    değil kurulumu ölçüyordu.
    """
    from app.contracts import OtonomiSeviyesi

    app.dependency_overrides[ayarlar] = lambda: Ayarlar(autonomy_level=OtonomiSeviyesi.SHADOW)
    try:
        govde = istemci.post("/v1/decisions/stock/reorder-review").json()
    finally:
        del app.dependency_overrides[ayarlar]

    assert govde["politika"]["otonomi_seviyesi"] == "shadow"
    assert govde["politika"]["uygulandi"] is False


def test_ONERI_modunda_da_karar_uygulanmaz(istemci: TestClient):
    """⭐ Bugünkü canlı ayar `advisory` — sistem öneriyor, uygulamıyor.

    Otonomi yolu: şimdi öneri → sonra eşikli (küçükleri kendi uygular) →
    giderek tam otomatik. Bu test yolun **birinci basamağını** koruyor:
    advisory'de hiçbir karar uygulanmamalı.
    """
    from app.contracts import OtonomiSeviyesi

    app.dependency_overrides[ayarlar] = lambda: Ayarlar(autonomy_level=OtonomiSeviyesi.ADVISORY)
    try:
        govde = istemci.post("/v1/decisions/stock/reorder-review").json()
    finally:
        del app.dependency_overrides[ayarlar]

    assert govde["politika"]["otonomi_seviyesi"] == "advisory"
    assert govde["politika"]["uygulandi"] is False


def test_llm_erisilemezken_karar_endpointi_500_vermez(istemci: TestClient):
    """Faz 4.1 — LLM çökerse karar yolu bozulmamalı, gerekçe şablona düşmeli.

    `ollama_base_url` kasıtlı olarak kimsenin dinlemediği bir adrese
    ayarlanıyor. Beklenen: 500 değil 200, `gerekce.guard_sonucu ==
    'sablona_dustu'` (bkz. `app/llm/guard.py::gerekceyi_guvenceye_al` —
    "hiçbir koşulda hata fırlatmaz").
    """
    bozuk_ayar = Ayarlar(ollama_base_url="http://127.0.0.1:1", llm_timeout_sn=3.0)
    app.dependency_overrides[ayarlar] = lambda: bozuk_ayar
    try:
        cevap = istemci.post("/v1/decisions/stock/reorder-review?gerekce=true")
    finally:
        del app.dependency_overrides[ayarlar]

    assert cevap.status_code == 200
    gerekce = cevap.json()["gerekce"]
    assert gerekce is not None
    assert gerekce["guard_sonucu"] == "sablona_dustu"
    assert gerekce["model_adi"] is None


def test_karar_gerekceden_ONCE_kaliciya_yaziliyor(istemci: TestClient, api_oturumu, monkeypatch):
    """⭐ Gerekçe üretimi kararı riske atmamalı.

    Sıra ters olsaydı (önce LLM, sonra kayıt) 6 saniyelik üretim penceresinde
    süreç ölünce **karar tamamen kaybolurdu** — oysa karar zaten üretilmişti.

    Bu test o pencereyi taklit ediyor: gerekçe üretimi patlatılıyor, sonra
    kararın yine de veritabanında olduğu doğrulanıyor.

    ⚠️ `gerekce_uret` normalde hata fırlatmaz (guard'ın tasarımı). Burada
    zorla fırlattırılıyor çünkü sınanan şey guard değil, **yazma sırası**.
    """
    import pytest
    from sqlalchemy import func, select

    from app.models import Decision

    def patla(*_args, **_kwargs):
        raise RuntimeError("uretim sirasinda surec oldu")

    monkeypatch.setattr("app.api.decisions.gerekce_uret", patla)

    onceki = api_oturumu.scalar(select(func.count()).select_from(Decision))

    with pytest.raises(RuntimeError):
        istemci.post("/v1/decisions/stock/reorder-review?gerekce=true")

    api_oturumu.expire_all()
    sonraki = api_oturumu.scalar(select(func.count()).select_from(Decision))

    assert sonraki == onceki + 1, "gerekce patlasa bile karar kalici olmali"
