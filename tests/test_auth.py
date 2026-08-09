"""Kimlik doğrulama (Faz 7, `app/core/auth.py` + `app/api/giris.py`).

Bu dosyanın sorduğu tek soru: **bir uç yanlışlıkla korumasız kalabilir mi?**

`test_tum_v1_uclari_korumali` bunun için var ve diğer testlerden farklı
çalışıyor: tek tek uç saymıyor, uygulamanın rota tablosunu geziyor. Yeni bir
`/v1` ucu eklenip kimlik bağımlılığı unutulursa bu test kırılır — insan
hafızasına bırakılmayacak kadar önemli.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.auth import (
    UiKimlikGerekli,
    anahtar_gecerli_mi,
    kimlik_dogrula,
    kimlik_dogrula_ui,
    kimlik_yapilandirmasini_dogrula,
)
from app.core.config import Ayarlar, ayarlar
from app.core.db import oturum_al
from app.main import app

ANAHTAR = "test-anahtari-1234567890"
IKINCI_ANAHTAR = "rotasyon-anahtari-0987654321"

# Kimlik gerektirdiği doğrulanacak temsilci uç. GET olması bilinçli: POST
# uçları gövde doğrulamasına takılıp 422 dönebilir ve 401 beklerken 422
# görmek testi anlamsızlaştırır.
KORUMALI_UC = "/v1/approvals"


def _anahtarli_ayar() -> Ayarlar:
    return Ayarlar(api_anahtarlari=f"{ANAHTAR},{IKINCI_ANAHTAR}")


@pytest.fixture
def anahtarli_istemci(api_motoru: Engine) -> Iterator[TestClient]:
    """Kimlik doğrulaması AÇIK bir istemci.

    `conftest.istemci` bilinçli olarak anahtarsız (kimlik kapalı) — 450
    testin tamamına anahtar eklemek, korumanın kendisini test etmeyen
    dosyalara gereksiz gürültü katardı.
    """
    fabrika = sessionmaker(bind=api_motoru, expire_on_commit=False)

    def oturum_ver() -> Iterator[Session]:
        with fabrika() as oturum:
            yield oturum

    app.dependency_overrides[oturum_al] = oturum_ver
    app.dependency_overrides[ayarlar] = _anahtarli_ayar
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Kapalı kip — anahtar tanımlı değilken
# ---------------------------------------------------------------------------


def test_anahtar_tanimsizsa_istek_gecer(istemci: TestClient):
    """Geliştirme kolaylığı: anahtar yoksa kimlik doğrulama kapalı."""
    assert istemci.get(KORUMALI_UC).status_code == 200


def test_health_kimlik_kapaliyi_bildirir(istemci: TestClient):
    """"Anahtar tanımlamayı unuttuk" durumu sessiz kalmamalı.

    ⚠️ İki istemci fixture'ı aynı `app.dependency_overrides` sözlüğünü
    paylaşıyor; tek testte ikisini birden istemek ayarları birbirine
    karıştırır. Bu yüzden iki ayrı test.
    """
    assert istemci.get("/health").json()["kimlik_dogrulama"] == "kapali"


def test_health_kimlik_aciki_bildirir(anahtarli_istemci: TestClient):
    assert anahtarli_istemci.get("/health").json()["kimlik_dogrulama"] == "acik"


# ---------------------------------------------------------------------------
# Açık kip — üç taşıyıcı
# ---------------------------------------------------------------------------


def test_anahtarsiz_istek_401(anahtarli_istemci: TestClient):
    cevap = anahtarli_istemci.get(KORUMALI_UC)
    assert cevap.status_code == 401
    assert cevap.headers["WWW-Authenticate"] == "Bearer"


def test_yanlis_anahtar_401(anahtarli_istemci: TestClient):
    cevap = anahtarli_istemci.get(KORUMALI_UC, headers={"X-API-Key": "yanlis"})
    assert cevap.status_code == 401


def test_baslikla_gecer(anahtarli_istemci: TestClient):
    cevap = anahtarli_istemci.get(KORUMALI_UC, headers={"X-API-Key": ANAHTAR})
    assert cevap.status_code == 200


def test_bearer_ile_gecer(anahtarli_istemci: TestClient):
    cevap = anahtarli_istemci.get(KORUMALI_UC, headers={"Authorization": f"Bearer {ANAHTAR}"})
    assert cevap.status_code == 200


def test_cerezle_gecer(anahtarli_istemci: TestClient):
    anahtarli_istemci.cookies.set("codifya_anahtar", ANAHTAR)
    assert anahtarli_istemci.get(KORUMALI_UC).status_code == 200


def test_ikinci_anahtar_da_gecerli(anahtarli_istemci: TestClient):
    """Anahtar döndürme (rotation): eski ve yeni bir süre birlikte çalışır."""
    cevap = anahtarli_istemci.get(KORUMALI_UC, headers={"X-API-Key": IKINCI_ANAHTAR})
    assert cevap.status_code == 200


def test_health_anahtarsiz_erisilebilir(anahtarli_istemci: TestClient):
    """Yük dengeleyici/izleme anahtar taşımadan sağlık sorabilmeli."""
    assert anahtarli_istemci.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# Kapsam — hiçbir /v1 ucu korumasız kalmasın
# ---------------------------------------------------------------------------


def test_tum_v1_uclari_korumali():
    """Rota tablosunu gezerek kimlik bağımlılığı olmayan `/v1` ucu arar."""
    korumasiz = []
    for rota in app.routes:
        if not isinstance(rota, APIRoute) or not rota.path.startswith("/v1"):
            continue
        bagimliliklar = {
            b.call for b in rota.dependant.dependencies if b.call is not None
        }
        if kimlik_dogrula not in bagimliliklar:
            korumasiz.append(f"{sorted(rota.methods)} {rota.path}")

    assert not korumasiz, f"Kimlik doğrulaması olmayan uçlar: {korumasiz}"


def test_onay_ekrani_uclari_korumali():
    """Giriş/çıkış dışındaki her `/onay` ucu UI kimliği istemeli."""
    korumasiz = []
    for rota in app.routes:
        if not isinstance(rota, APIRoute) or not rota.path.startswith("/onay"):
            continue
        if rota.path in ("/onay/giris", "/onay/cikis"):
            continue
        bagimliliklar = {
            b.call for b in rota.dependant.dependencies if b.call is not None
        }
        if kimlik_dogrula_ui not in bagimliliklar:
            korumasiz.append(f"{sorted(rota.methods)} {rota.path}")

    assert not korumasiz, f"Kimlik doğrulaması olmayan onay ekranı uçları: {korumasiz}"


# ---------------------------------------------------------------------------
# Onay ekranı — 401 JSON değil, giriş sayfası
# ---------------------------------------------------------------------------


def test_anahtarsiz_onay_ekrani_girise_yonlendirir(anahtarli_istemci: TestClient):
    cevap = anahtarli_istemci.get("/onay", follow_redirects=False)
    assert cevap.status_code == 303
    assert cevap.headers["location"].startswith("/onay/giris")
    # Nereye dönüleceği taşınıyor.
    assert "hedef=/onay" in cevap.headers["location"]


def test_giris_sayfasi_anahtarsiz_acilir(anahtarli_istemci: TestClient):
    cevap = anahtarli_istemci.get("/onay/giris")
    assert cevap.status_code == 200
    assert 'name="anahtar"' in cevap.text


def test_giris_dogru_anahtarla_cerez_koyar(anahtarli_istemci: TestClient):
    cevap = anahtarli_istemci.post(
        "/onay/giris", data={"anahtar": ANAHTAR, "hedef": "/onay"}, follow_redirects=False
    )
    assert cevap.status_code == 303
    assert cevap.headers["location"] == "/onay"
    assert "codifya_anahtar" in cevap.cookies

    # Çerez artık istemcide; ekran açılmalı.
    assert anahtarli_istemci.get("/onay").status_code == 200


def test_giris_yanlis_anahtarla_formu_geri_verir(anahtarli_istemci: TestClient):
    cevap = anahtarli_istemci.post("/onay/giris", data={"anahtar": "yanlis"})
    assert cevap.status_code == 401
    assert "gecersiz" in cevap.text.lower()
    assert "codifya_anahtar" not in cevap.cookies


def test_giris_disaridaki_adrese_yonlendirmez(anahtarli_istemci: TestClient):
    """Açık yönlendirme (open redirect) kapalı olmalı."""
    for kotu in ("https://kotu.example", "//kotu.example", "/v1/decisions"):
        cevap = anahtarli_istemci.post(
            "/onay/giris", data={"anahtar": ANAHTAR, "hedef": kotu}, follow_redirects=False
        )
        assert cevap.headers["location"] == "/onay"


def test_cikis_cerezi_siler(anahtarli_istemci: TestClient):
    anahtarli_istemci.post("/onay/giris", data={"anahtar": ANAHTAR}, follow_redirects=False)
    assert anahtarli_istemci.get("/onay").status_code == 200

    anahtarli_istemci.post("/onay/cikis", follow_redirects=False)
    assert anahtarli_istemci.get("/onay", follow_redirects=False).status_code == 303


def test_giris_sayfasi_kimlik_kapaliyken_form_gostermez(istemci: TestClient):
    cevap = istemci.get("/onay/giris")
    assert cevap.status_code == 200
    assert 'name="anahtar"' not in cevap.text
    assert "KAPALI" in cevap.text


# ---------------------------------------------------------------------------
# Üretim ortamı — anahtarsız açılış yasak
# ---------------------------------------------------------------------------


def test_uretimde_anahtarsiz_acilis_reddedilir():
    with pytest.raises(RuntimeError, match="API_ANAHTARLARI"):
        kimlik_yapilandirmasini_dogrula(Ayarlar(ortam="uretim", api_anahtarlari=""))


def test_uretimde_anahtar_varsa_acilis_gecer():
    kimlik_yapilandirmasini_dogrula(Ayarlar(ortam="uretim", api_anahtarlari=ANAHTAR))


def test_uretimde_anahtarsiz_istek_503(api_motoru: Engine):
    """Fail-closed: açılış kontrolü atlansa bile istek geçmez."""
    fabrika = sessionmaker(bind=api_motoru, expire_on_commit=False)

    def oturum_ver() -> Iterator[Session]:
        with fabrika() as oturum:
            yield oturum

    app.dependency_overrides[oturum_al] = oturum_ver
    app.dependency_overrides[ayarlar] = lambda: Ayarlar(ortam="uretim", api_anahtarlari="")
    try:
        cevap = TestClient(app).get(KORUMALI_UC)
        assert cevap.status_code == 503
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Birim: anahtar karşılaştırma ve ayrıştırma
# ---------------------------------------------------------------------------


def test_bos_kume_hicbir_anahtari_kabul_etmez():
    assert not anahtar_gecerli_mi("", frozenset())
    assert not anahtar_gecerli_mi(ANAHTAR, frozenset())


def test_bos_parcalar_ayiklanir():
    """`"a,,b,"` boş string'i geçerli anahtar yapmamalı — yaparsa
    anahtarsız her istek kabul edilirdi."""
    ayar = Ayarlar(api_anahtarlari="a, ,b,")
    assert ayar.api_anahtar_kumesi == frozenset({"a", "b"})
    assert not anahtar_gecerli_mi("", ayar.api_anahtar_kumesi)


def test_bos_ayar_bos_kume():
    assert Ayarlar(api_anahtarlari="").api_anahtar_kumesi == frozenset()
    assert Ayarlar(api_anahtarlari="   ").api_anahtar_kumesi == frozenset()


def test_ui_kimlik_gerekli_istisnasi_ayri_tip():
    """UI yolu 401 yerine yönlendirme üretebilsin diye ayrı istisna kullanır."""
    assert issubclass(UiKimlikGerekli, Exception)
