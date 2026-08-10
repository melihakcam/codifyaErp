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
from sqlalchemy import Engine, select
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
    """ "Anahtar tanımlamayı unuttuk" durumu sessiz kalmamalı.

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
        bagimliliklar = {b.call for b in rota.dependant.dependencies if b.call is not None}
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
        bagimliliklar = {b.call for b in rota.dependant.dependencies if b.call is not None}
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


# ---------------------------------------------------------------------------
# B3 — Kimlik kişiyi de taşıyor
# ---------------------------------------------------------------------------

KIMLIKLI_ANAHTAR = "k-esmanur-9876543210"
OPERATOR_ANAHTARI = "k-ali-1234567890"


def _kimlikli_ayar() -> Ayarlar:
    return Ayarlar(
        api_anahtarlari=f"{KIMLIKLI_ANAHTAR}:esmanur:yonetici, {OPERATOR_ANAHTARI}:ali",
        # ⚠️ 1 TL gerçekçi değil, kasıtlı: demo kararının tutarı ne olursa
        # olsun eşiğin üstünde kalsın ve test atlanmasın. Eşiği gerçekçi
        # tutmak, testi dünyanın rastgele bir sayısına bağımlı kılardı.
        onay_yonetici_esigi_tl=1.0,
    )


@pytest.fixture
def kimlikli_istemci(api_motoru: Engine) -> Iterator[TestClient]:
    fabrika = sessionmaker(bind=api_motoru, expire_on_commit=False)

    def oturum_ver() -> Iterator[Session]:
        with fabrika() as oturum:
            yield oturum

    app.dependency_overrides[oturum_al] = oturum_ver
    app.dependency_overrides[ayarlar] = _kimlikli_ayar
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_anahtar_ad_ve_rol_tasiyor():
    ayar = _kimlikli_ayar()

    assert ayar.api_kimlikleri[KIMLIKLI_ANAHTAR] == ("esmanur", "yonetici")
    # Rol verilmezse operator.
    assert ayar.api_kimlikleri[OPERATOR_ANAHTARI] == ("ali", "operator")


def test_ad_verilmezse_bilinmeyen():
    ayar = Ayarlar(api_anahtarlari="sadece-anahtar")
    assert ayar.api_kimlikleri["sadece-anahtar"] == ("bilinmeyen", "operator")


def test_onayda_isim_anahtardan_geliyor(kimlikli_istemci: TestClient, api_oturumu: Session):
    """⭐ B3'ün ana iddiası: çağıran denetim kaydındaki ismi seçemiyor."""
    from app.models import Feedback

    cevap = kimlikli_istemci.post(
        "/v1/decisions/stock/reorder-review", headers={"X-API-Key": KIMLIKLI_ANAHTAR}
    )
    karar_id = cevap.json()["aday"]["karar_id"]

    # Gövdede başka bir isim iddia ediliyor — yok sayılmalı.
    sonuc = kimlikli_istemci.post(
        f"/v1/approvals/{karar_id}",
        json={"eylem": "onayla", "kullanici": "genel mudur"},
        headers={"X-API-Key": KIMLIKLI_ANAHTAR},
    )
    assert sonuc.status_code == 200

    geri_bildirim = api_oturumu.scalars(select(Feedback)).one()
    assert geri_bildirim.kullanici == "esmanur"
    assert geri_bildirim.kullanici != "genel mudur"


def test_esik_ustunu_operator_onaylayamiyor(kimlikli_istemci: TestClient):
    """Otonomi kademelerinin insan tarafındaki karşılığı."""
    cevap = kimlikli_istemci.post(
        "/v1/decisions/stock/reorder-review", headers={"X-API-Key": OPERATOR_ANAHTARI}
    )
    karar_id = cevap.json()["aday"]["karar_id"]

    sonuc = kimlikli_istemci.post(
        f"/v1/approvals/{karar_id}",
        json={"eylem": "onayla"},
        headers={"X-API-Key": OPERATOR_ANAHTARI},
    )
    assert sonuc.status_code == 403
    assert "yönetici" in sonuc.json()["detail"]


def test_esik_ustunu_yonetici_onaylayabiliyor(kimlikli_istemci: TestClient):
    cevap = kimlikli_istemci.post(
        "/v1/decisions/stock/reorder-review", headers={"X-API-Key": KIMLIKLI_ANAHTAR}
    )
    karar_id = cevap.json()["aday"]["karar_id"]

    sonuc = kimlikli_istemci.post(
        f"/v1/approvals/{karar_id}",
        json={"eylem": "onayla"},
        headers={"X-API-Key": KIMLIKLI_ANAHTAR},
    )
    assert sonuc.status_code == 200


def test_kimlik_kapaliyken_kisit_yok(istemci: TestClient):
    """Doğrulama kapalıyken rol bilinmiyor; herkesi yetkisiz saymak
    geliştirmeyi kilitler, herkesi yönetici saymak kontrolü sahte kılar."""
    karar_id = istemci.post("/v1/decisions/stock/reorder-review").json()["aday"]["karar_id"]

    sonuc = istemci.post(
        f"/v1/approvals/{karar_id}", json={"eylem": "onayla", "kullanici": "melih"}
    )
    assert sonuc.status_code == 200


def test_uretimde_kisa_anahtar_acilisi_engelliyor():
    """⭐ İçinde ':' geçen anahtar SESSİZCE kırpılıyordu.

    `api_kimlikleri` anahtar metnini `anahtar:ad:rol` diye bölüyor. Rastgele
    üretilmiş bir anahtarda ':' varsa geriye yalnızca ilk parça kalıyor,
    gerisi "kullanıcı adı" oluyor ve **hiçbir uyarı çıkmıyordu**:

        API_ANAHTARLARI="Xy9:aBcD3fGh1jKlMnOpQrStUvWxYz0123"
        etkin anahtar  : "Xy9"     <- uc karakter

    Yönetici 34 karakterlik anahtar koyduğunu sanırken servis üç karakterle
    açılıyordu. Rol yükseltme riski yok (küme yalnızca ':'ten önceki kısmı
    tutar) ama kaba kuvvete karşı koruma tamamen kalkıyordu.
    """
    import pytest

    from app.core.auth import ASGARI_ANAHTAR_UZUNLUGU, kimlik_yapilandirmasini_dogrula
    from app.core.config import Ayarlar

    kirpilan = "Xy9:aBcD3fGh1jKlMnOpQrStUvWxYz0123"
    ayar = Ayarlar(ortam="uretim", api_anahtarlari=kirpilan)

    # Once kusurun hala orada oldugunu gosterelim: anahtar gercekten kirpiliyor.
    assert ayar.api_anahtar_kumesi == frozenset({"Xy9"})

    with pytest.raises(RuntimeError) as hata:
        kimlik_yapilandirmasini_dogrula(ayar)
    assert "':'" in str(hata.value), "hata mesaji sebebi soylemeli"
    # ⚠️ Anahtarin kendisi hata metnine sizmamali.
    assert kirpilan not in str(hata.value)
    assert "Xy9" not in str(hata.value)

    # Yeterince uzun, ':' icermeyen anahtar sorunsuz gecmeli.
    saglam = "a" * ASGARI_ANAHTAR_UZUNLUGU
    kimlik_yapilandirmasini_dogrula(Ayarlar(ortam="uretim", api_anahtarlari=saglam))


def test_gelistirmede_kisa_anahtar_serbest():
    """Kısıt yalnızca üretimde — geliştirmede "test" gibi anahtarlar yaygın.

    Her ortamda zorlamak günlük akışı kilitlerdi ve kimse üretimde de
    olmayan bir korumadan fayda görmezdi.
    """
    from app.core.auth import kimlik_yapilandirmasini_dogrula
    from app.core.config import Ayarlar

    kimlik_yapilandirmasini_dogrula(Ayarlar(ortam="gelistirme", api_anahtarlari="kisa"))
