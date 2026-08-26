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

# ⚠️ Burada yerel bir `istemci` fixture'i VARDI (`TestClient(app)`, module
# kapsamli) ve conftest'inkini golgeliyordu. Sonucu: bu dosyadaki testler
# GELISTIRME veritabanina yaziyordu, testin kendi gecici veritabanina degil.
#
# Sessiz bir hataydi — hicbir test kirilmiyordu, cunku hicbiri veritabanini
# saymiyordu. B1'de "kararlarin hepsi kalici oldu mu" testi yazilinca ortaya
# cikti: sayac 0 gosterdi, cunku kayitlar baska veritabanindaydi.
#
# Ayni hata `test_api_smoke.py`'de de vardi ve orada da boyle duzeltilmisti.
# conftest'teki `istemci` gecici veritabani kuruyor ve `api_oturumu` ile ayni
# motoru paylasiyor.


def test_tahsilat_ucu_karar_LISTESI_donduruyor(istemci: TestClient):
    """⚠️ Tur 8 · B1 — uç artık LİSTE döndürüyor (sürüm kırılımı).

    Önceden tek karar dönüyordu; bir müşteri aynı anda hem karşılık hem
    tahsilat takibi kararı alabildiği için bu, kararların sessizce
    kaybolması demekti.
    """
    cevap = istemci.post("/v1/decisions/finance/collection-review")

    assert cevap.status_code == 200
    govde = cevap.json()
    assert isinstance(govde, list), "uç liste döndürmeli"
    assert govde, "en az bir karar olmalı"
    for kalem in govde:
        assert kalem["aday"]["alan"] == "finans"
        assert kalem["aday"]["tip"].startswith("finans.")
        assert kalem["aday"]["ozellikler"]["musteri_adi"]
    # Hepsi AYNI müşteriye ait olmalı — uç bir müşteriyi değerlendiriyor.
    kimlikler = {k["aday"]["ozellikler"]["musteri_id"] for k in govde}
    assert len(kimlikler) == 1


def test_gerekce_varsayilan_olarak_uretilmiyor(istemci: TestClient):
    """⭐ Mimarinin ikinci kuralı: ERP asla LLM'i beklemez."""
    govde = istemci.post("/v1/decisions/finance/collection-review").json()

    assert all(k["gerekce"] is None for k in govde)


def test_bilinmeyen_musteri_404(istemci: TestClient):
    cevap = istemci.post(
        "/v1/decisions/finance/collection-review", params={"musteri_id": "YOK-9999"}
    )

    assert cevap.status_code == 404


def test_belirli_musteri_secilebiliyor(istemci: TestClient):
    ilk = istemci.post("/v1/decisions/finance/collection-review").json()
    mid = ilk[0]["aday"]["ozellikler"]["musteri_id"]

    tekrar = istemci.post(
        "/v1/decisions/finance/collection-review", params={"musteri_id": mid}
    ).json()

    assert all(k["aday"]["ozellikler"]["musteri_id"] == mid for k in tekrar)


def test_karar_shadow_modda_uygulanmiyor(istemci: TestClient):
    """Shadow modda karar üretilir, kaydedilir, uygulanmaz.

    ⚠️ Otonomi seviyesi **testte sabitleniyor**, `.env`'den okunmuyor.

    Faz 11'de `.env` `advisory`'ye alındı (otonomi yolu: önce öneri, sonra
    eşikli, giderek tam otomatik) ve bu test kırıldı — çünkü ortamdan gelen
    bir ayara bağlıydı. Shadow davranışını sınayan bir testin shadow modunu
    kendisi kurması gerekir; ortam değiştiğinde kırılan test, davranışı
    değil kurulumu ölçüyordu.
    """
    from app.contracts import OtonomiSeviyesi
    from app.core.config import Ayarlar, ayarlar
    from app.main import app

    app.dependency_overrides[ayarlar] = lambda: Ayarlar(autonomy_level=OtonomiSeviyesi.SHADOW)
    try:
        govde = istemci.post("/v1/decisions/finance/collection-review").json()
    finally:
        del app.dependency_overrides[ayarlar]

    for kalem in govde:
        assert kalem["politika"]["uygulandi"] is False
        assert "SHADOW_UYGULANMADI" in kalem["politika"]["gerekce_kodlari"]


def test_iki_uc_de_ayni_akisi_kullaniyor():
    """⚠️ Ortak gövde kopyalanmamalı.

    `_karari_isle` Faz 6'da stok ucundan çıkarıldı. İki uç da ortak akışa
    girmeli; biri kendi kopyasını taşısaydı commit sıralaması zamanla
    ayrışırdı.

    Tur 8 · B1'de finans ucu çoğullaştı ve `_kararlari_isle`'yi çağırıyor.
    Kural bozulmadı, aksine güçlendi: `_karari_isle` artık kendi gövdesini
    taşımıyor, `_kararlari_isle`'ye deleg ediyor — yani commit sıralaması
    **tek** bir yerde yaşıyor. Test bunu da doğruluyor.
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

    ORTAK = {"_karari_isle", "_kararlari_isle"}
    assert cagrilar["stok_siparis_degerlendir"] & ORTAK, "stok ucu ortak akışa girmiyor"
    assert cagrilar["finans_tahsilat_degerlendir"] & ORTAK, "finans ucu ortak akışa girmiyor"

    # ⭐ Asıl koruma: sıralama TEK yerde. Tekil yol kendi gövdesini taşımamalı.
    assert "_kararlari_isle" in cagrilar["_karari_isle"], (
        "_karari_isle kendi kopyasini tasiyor — commit sirasi iki yerde yasar"
    )
    assert "oturum.commit" not in str(cagrilar["_karari_isle"])


def test_kill_switch_iki_ucta_da_var():
    """`AUTONOMY_LEVEL=off` her iki uçta da 503 vermeli."""
    import ast
    import inspect

    from app.api import decisions

    agac = ast.parse(inspect.getsource(decisions))
    for ad in ("stok_siparis_degerlendir", "finans_tahsilat_degerlendir"):
        fn = next(d for d in ast.walk(agac) if isinstance(d, ast.FunctionDef) and d.name == ad)
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

    geri_alinamaz = [
        k
        for k in govde
        if k["aday"]["tip"]
        in {KararTipi.FINANS_KARSILIK_AYIR.value, KararTipi.FINANS_KREDI_LIMITI_DUSUR.value}
    ]
    assert geri_alinamaz, "hedef müşterinin geri alınamaz kararı listede olmalı"
    for kalem in geri_alinamaz:
        assert kalem["politika"]["sonuc"] == PolitikaSonucu.ONAY_KUYRUGU.value
        assert "TIP_DAIMA_ONAY" in kalem["politika"]["gerekce_kodlari"]


def test_cok_kararli_musterinin_KARARLARI_KAYBOLMUYOR(istemci: TestClient):
    """⭐ Tur 8 · B1'in asıl sebebi — bu test olmasa kusur geri gelir.

    Faz 7'de `ozellikten_kararlar_uret` liste döndürür oldu: bir müşteri aynı
    anda hem karşılık hem tahsilat takibi kararı alabiliyor. Ama HTTP ucu
    listenin yalnızca **birincisini** veriyordu.

    Somut sonuç: batık bir müşteri için ERP karşılık kararını görüyor,
    **aynı müşterinin tahsilat takibi kararını hiç görmüyordu.** Karar
    üretilmiş, kaydedilmiş, ama dışarıya hiç çıkmamış oluyordu.

    ⚠️ Demo dünyada müşteri başına EN FAZLA 2 karar çıkıyor (800 müşterinin
    16'sı). Görev tanımı "üç kararlı müşteri" diyordu ama üçüncüsü
    (`finans.kredi_limiti_dusur`) demo dünyada hiç üretilmiyor — ayrı bir
    bulgu, `BILINEN-EKSIKLER.md`'ye yazıldı. Test gerçekte var olan azami
    çokluğu sınıyor; sabit "2" değil, dünyadan okunan sayı kullanılıyor ki
    limit kararı canlanınca test kendiliğinden kapsasın.
    """
    from app.domain.finance.decide import _demo_ozellikleri, ozellikten_kararlar_uret

    hedef, beklenen = None, []
    for ozellik in _demo_ozellikleri():
        kararlar = ozellikten_kararlar_uret(ozellik)
        if len(kararlar) > len(beklenen):
            hedef, beklenen = ozellik, kararlar

    assert hedef is not None
    if len(beklenen) < 2:
        pytest.skip("demo dünyasında çok kararlı müşteri yok")

    govde = istemci.post(
        "/v1/decisions/finance/collection-review", params={"musteri_id": hedef.musteri_id}
    ).json()

    assert len(govde) == len(beklenen), (
        f"{hedef.musteri_id} için {len(beklenen)} karar var, uç {len(govde)} döndürdü"
    )
    assert {k["aday"]["tip"] for k in govde} == {k.tip.value for k in beklenen}


def test_cok_kararli_musteride_HEPSI_kaliciya_yaziliyor(istemci: TestClient, api_oturumu):
    """⭐ Kararların hepsi tek commit'te kalıcı olmalı, gerekçeden ÖNCE.

    Karar başına ayrı `_karari_isle` çağrılsaydı sıralama şöyle olurdu:
    karar1 → gerekçe1 → karar2 → gerekçe2. O zaman gerekçe1 üretilirken
    süreç ölse **karar2 hiç yazılmamış** olurdu — oysa ikisi de üretilmişti.
    """
    from sqlalchemy import func, select

    from app.domain.finance.decide import _demo_ozellikleri, ozellikten_kararlar_uret
    from app.models import Decision

    hedef, beklenen = None, []
    for ozellik in _demo_ozellikleri():
        kararlar = ozellikten_kararlar_uret(ozellik)
        if len(kararlar) > len(beklenen):
            hedef, beklenen = ozellik, kararlar
    if hedef is None or len(beklenen) < 2:
        pytest.skip("demo dünyasında çok kararlı müşteri yok")

    onceki = api_oturumu.scalar(select(func.count()).select_from(Decision))

    istemci.post("/v1/decisions/finance/collection-review", params={"musteri_id": hedef.musteri_id})

    api_oturumu.expire_all()
    sonraki = api_oturumu.scalar(select(func.count()).select_from(Decision))

    assert sonraki == onceki + len(beklenen), "kararların hepsi kalıcı olmalı"
