"""Finans endpoint'i (Faz 6.5).

⚠️ Bu testlerin asıl işi endpoint'i değil, **ortak akışın gerçekten ortak
olduğunu** doğrulamak. `_karari_isle` iki uçtan da çağrılıyor; içindeki
commit sıralaması (önce karar, sonra gerekçe) mimarinin ikinci kuralının
veri katmanındaki karşılığı ve iki yerde yaşamamalı.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.contracts import KararTipi, PolitikaSonucu
from app.main import app


@pytest.fixture(scope="module")
def istemci() -> TestClient:
    return TestClient(app)


def test_tahsilat_ucu_karar_donduruyor(istemci: TestClient):
    cevap = istemci.post("/v1/decisions/finance/collection-review")

    assert cevap.status_code == 200
    govde = cevap.json()
    assert govde["aday"]["alan"] == "finans"
    assert govde["aday"]["tip"].startswith("finans.")
    assert govde["aday"]["ozellikler"]["musteri_adi"]


def test_gerekce_varsayilan_olarak_uretilmiyor(istemci: TestClient):
    """⭐ Mimarinin ikinci kuralı: ERP asla LLM'i beklemez."""
    govde = istemci.post("/v1/decisions/finance/collection-review").json()

    assert govde["gerekce"] is None


def test_bilinmeyen_musteri_404(istemci: TestClient):
    cevap = istemci.post(
        "/v1/decisions/finance/collection-review", params={"musteri_id": "YOK-9999"}
    )

    assert cevap.status_code == 404


def test_belirli_musteri_secilebiliyor(istemci: TestClient):
    ilk = istemci.post("/v1/decisions/finance/collection-review").json()
    mid = ilk["aday"]["ozellikler"]["musteri_id"]

    tekrar = istemci.post(
        "/v1/decisions/finance/collection-review", params={"musteri_id": mid}
    ).json()

    assert tekrar["aday"]["ozellikler"]["musteri_id"] == mid


def test_karar_shadow_modda_uygulanmiyor(istemci: TestClient):
    """`AUTONOMY_LEVEL=shadow` — karar üretilir, kaydedilir, uygulanmaz."""
    govde = istemci.post("/v1/decisions/finance/collection-review").json()

    assert govde["politika"]["uygulandi"] is False
    assert "SHADOW_UYGULANMADI" in govde["politika"]["gerekce_kodlari"]


def test_iki_uc_de_ayni_akisi_kullaniyor():
    """⚠️ Ortak gövde kopyalanmamalı.

    `_karari_isle` Faz 6'da stok ucundan çıkarıldı. İki uç da onu çağırmalı;
    biri kendi kopyasını taşısaydı commit sıralaması zamanla ayrışırdı.
    """
    import ast
    import inspect

    from app.api import decisions

    agac = ast.parse(inspect.getsource(decisions))
    cagrilar: dict[str, set[str]] = {}
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.FunctionDef):
            cagrilar[dugum.name] = {
                a.func.id
                for a in ast.walk(dugum)
                if isinstance(a, ast.Call) and isinstance(a.func, ast.Name)
            }

    assert "_karari_isle" in cagrilar["stok_siparis_degerlendir"]
    assert "_karari_isle" in cagrilar["finans_tahsilat_degerlendir"]


def test_kill_switch_iki_ucta_da_var():
    """`AUTONOMY_LEVEL=off` her iki uçta da 503 vermeli."""
    import ast
    import inspect

    from app.api import decisions

    agac = ast.parse(inspect.getsource(decisions))
    for ad in ("stok_siparis_degerlendir", "finans_tahsilat_degerlendir"):
        fn = next(
            d for d in ast.walk(agac) if isinstance(d, ast.FunctionDef) and d.name == ad
        )
        cagrilar = {
            a.func.id
            for a in ast.walk(fn)
            if isinstance(a, ast.Call) and isinstance(a.func, ast.Name)
        }
        assert "_kapali_mi" in cagrilar, f"{ad} kill switch kontrolü yapmıyor"


def test_geri_alinamaz_karar_onay_kuyruguna_giriyor(istemci: TestClient):
    """Karşılık/limit kararları daima onay ister — hangi tutarda olursa olsun."""
    from app.domain.finance.decide import _demo_ozellikleri, ozellikten_karar_uret

    hedef = next(
        (
            o
            for o in _demo_ozellikleri()
            if ozellikten_karar_uret(o).tip
            in {KararTipi.FINANS_KARSILIK_AYIR, KararTipi.FINANS_KREDI_LIMITI_DUSUR}
        ),
        None,
    )
    if hedef is None:
        pytest.skip("demo dünyasında karşılık/limit kararı çıkmadı")

    govde = istemci.post(
        "/v1/decisions/finance/collection-review", params={"musteri_id": hedef.musteri_id}
    ).json()

    assert govde["politika"]["sonuc"] == PolitikaSonucu.ONAY_KUYRUGU.value
    assert "TIP_DAIMA_ONAY" in govde["politika"]["gerekce_kodlari"]
