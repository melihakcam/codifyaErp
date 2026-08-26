"""Yönetim paneli (`app/api/panel.py`).

⚠️ Panel 246 satırlık bir dosya olarak **hiç testi olmadan** eklenmişti.
Buradaki testler üç iddiayı sınıyor, üçü de kodun kendi docstring'inde
yazılı ama hiçbiri doğrulanmamıştı:

1. Panel iş verisi gösterdiği için kimlik doğrulamanın arkasında.
2. Sayfa SALT OKUNUR — hiçbir karar buradan uygulanamaz.
3. Kullanıcı verisi HTML'e kaçırılarak giriyor.

Üçüncüsü özellikle önemli: kalem adları (ürün adı, müşteri adı) dışarıdan
gelen veri. Kaçırılmazsa panel bir XSS taşıyıcısı olurdu ve panel tam da
yöneticinin baktığı sayfa.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Ayarlar, ayarlar
from app.core.db import oturum_al
from app.main import app

PANEL_UC = "/panel"
ANAHTAR = "panel-test-anahtari-123456"


@pytest.fixture
def anahtarli_istemci(api_motoru: Engine) -> Iterator[TestClient]:
    """Kimlik doğrulaması AÇIK istemci — `test_auth.py`'deki kalıbın aynısı."""
    fabrika = sessionmaker(bind=api_motoru, expire_on_commit=False)

    def oturum_ver() -> Iterator[Session]:
        with fabrika() as oturum:
            yield oturum

    app.dependency_overrides[oturum_al] = oturum_ver
    app.dependency_overrides[ayarlar] = lambda: Ayarlar(api_anahtarlari=ANAHTAR)
    try:
        yield TestClient(app, follow_redirects=False)
    finally:
        app.dependency_overrides.clear()


def test_panel_kimliksiz_veri_SIZDIRMIYOR(anahtarli_istemci: TestClient):
    """⭐ Panel iş verisi gösteriyor; anahtarsız istek içeriği görmemeli.

    Beklenen 401 JSON değil giriş sayfasına yönlendirme (`kimlik_dogrula_ui`):
    tarayıcıda gezinen insana `{"detail": ...}` göstermek arızalı sayfa
    izlenimi verir. Önemli olan hangi kod olduğu değil, **gövdenin iş verisi
    taşımaması**.
    """
    cevap = anahtarli_istemci.get(PANEL_UC)

    assert cevap.status_code in {302, 303, 307, 401}
    # Yonlendirme govdesi bos ya da kisa olmali; panel icerigi sizmamali.
    assert "kartlar" not in cevap.text
    assert "otonomi" not in cevap.text


def test_panel_kimlikle_aciliyor(anahtarli_istemci: TestClient):
    cevap = anahtarli_istemci.get(PANEL_UC, headers={"X-API-Key": ANAHTAR})

    assert cevap.status_code == 200
    assert "text/html" in cevap.headers["content-type"]


def test_panel_SALT_OKUNUR(anahtarli_istemci: TestClient):
    """⭐ Özet ekranında yanlışlıkla tıklanacak düğme olmamalı.

    Panel'in kendi docstring'i "hiçbir karar buradan uygulanamaz" diyor.
    Eylem onay ekranında; panelde bir onay/uygula düğmesi belirirse operatör
    özete bakarken karar uygulayabilir hâle gelir.
    """
    govde = anahtarli_istemci.get(PANEL_UC, headers={"X-API-Key": ANAHTAR}).text

    assert "<form" not in govde.lower()
    assert "hx-post" not in govde.lower()
    assert "hx-delete" not in govde.lower()
    for tehlikeli in ("onayla", "reddet", "uygula"):
        assert f">{tehlikeli}<" not in govde.lower(), f"panelde '{tehlikeli}' dugmesi var"


def test_panel_kalem_adini_KACIRIYOR(anahtarli_istemci: TestClient, api_motoru: Engine):
    """⭐ Kalem adı dışarıdan gelen veri — kaçırılmazsa panel XSS taşır.

    Ürün/müşteri adı ERP'den geliyor; içinde `<script>` olan bir ad
    kaçırılmadan basılırsa kod **yöneticinin tarayıcısında** çalışır. Panel
    tam da yöneticinin baktığı sayfa olduğu için bu en kötü yer.

    Test gerçek bir kararın adını zehirleyip panelde ham etiketin
    görünmediğini doğruluyor.
    """
    from app.contracts import PolitikaSonucu
    from app.core.audit import karari_kaydet
    from app.core.policy import esikleri_yukle, politika_uygula
    from app.domain.stock.decide import stok_karari_uret
    from app.models import Approval

    zehir = "<script>alert(1)</script>"
    ayar = Ayarlar(api_anahtarlari=ANAHTAR)

    fabrika = sessionmaker(bind=api_motoru, expire_on_commit=False)
    with fabrika() as oturum:
        aday = stok_karari_uret()
        # Kalem adi ozelliklerden okunuyor; adi zehirleyip kaydediyoruz.
        bozuk = aday.model_copy(
            update={"ozellikler": aday.ozellikler.model_copy(update={"sku_adi": zehir})}
        )
        politika = politika_uygula(bozuk, ayar, esikleri_yukle(oturum, bozuk.tip, ayar))
        karari_kaydet(oturum, bozuk, politika)
        if politika.sonuc is PolitikaSonucu.ONAY_KUYRUGU:
            oturum.add(Approval(karar_id=bozuk.karar_id))
        oturum.commit()

    govde = anahtarli_istemci.get(PANEL_UC, headers={"X-API-Key": ANAHTAR}).text

    assert zehir not in govde, "kalem adi HAM basiliyor — XSS"

    # ⚠️ Bu iki satir olmadan test BOSA GECEBILIR: zehirli kayit panele hic
    # dusmezse "ham zehir yok" onermesi kendiliginden dogru olur ve kacis
    # hic sinanmamis kalir. Kaydin gercekten render edildigi dogrulandi
    # (kacirilmis hali govdede), yani asagidaki iki iddia birlikte
    # "ad basildi VE kacirildi" diyor.
    assert "&lt;script&gt;" in govde, "zehirli kayit panele hic dusmemis — test bosa geciyor"
    assert "alert(1)" in govde
