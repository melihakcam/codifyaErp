"""Onay ekranı finans kararlarıyla (Faz 7).

`test_ui.py` ekranı yalnızca stok kararıyla sınıyordu. İki alanlı bir
sistemde bu yeterli değil: ekranın alan-bağımsız olduğu iddiası, ikinci
alan konmadan **doğrulanmamış bir iddia**.

Bulunan somut eksik: kuyrukta kararın konusu olan kalemin adı hiç yoktu.
Operatör "finans.tahsilat_takibi · 41.200 TL" satırını görüyor ama hangi
müşteri olduğunu bilemiyordu.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.contracts import KararTipi
from app.core.config import ayarlar
from app.core.policy import politika_uygula
from app.domain.finance.decide import finans_karari_uret
from app.models import Approval, Decision, OnayDurumu

STOK_UCU = "/v1/decisions/stock/reorder-review"


def _finans_karari_kuyruga_koy(oturum: Session) -> tuple[str, str]:
    """Demo dünyasından bir finans kararı üretip onay kuyruğuna yazar.

    API ucu yerine doğrudan alan koduna gidiliyor: burada sınanan şey
    kararın nasıl üretildiği değil, kuyruğa girdikten sonra ekranda nasıl
    göründüğü.
    """
    aday = finans_karari_uret()
    politika = politika_uygula(aday, ayarlar())

    oturum.add(Decision.sozlesmeden(aday, politika))
    oturum.add(Approval(karar_id=aday.karar_id, durum=OnayDurumu.BEKLIYOR))
    oturum.commit()

    return str(aday.karar_id), aday.ozellikler.gorunen_ad


def test_finans_karari_ekranda_musteri_adiyla_gorunur(istemci: TestClient, api_oturumu: Session):
    karar_id, musteri_adi = _finans_karari_kuyruga_koy(api_oturumu)

    cevap = istemci.get("/onay/liste")
    assert cevap.status_code == 200
    assert karar_id in cevap.text
    # ⭐ Asıl iddia: operatör hangi müşteri olduğunu görüyor.
    assert musteri_adi in cevap.text
    assert "finans" in cevap.text


def test_finans_karari_onaylanabilir(istemci: TestClient, api_oturumu: Session):
    karar_id, _ = _finans_karari_kuyruga_koy(api_oturumu)

    cevap = istemci.post(f"/onay/{karar_id}/onayla", data={"kullanici": "esmanur"})
    assert cevap.status_code == 200
    assert karar_id not in cevap.text

    kuyruk = istemci.get("/v1/approvals").json()
    assert kuyruk == []


def test_kuyruk_kalemi_alan_ve_kalem_adi_tasir(istemci: TestClient, api_oturumu: Session):
    _finans_karari_kuyruga_koy(api_oturumu)

    kalem = istemci.get("/v1/approvals").json()[0]
    assert kalem["alan"] == "finans"
    assert kalem["kalem_adi"]
    assert "geri_alinabilir" in kalem


def test_iki_alan_ayni_kuyrukta_gorunur(istemci: TestClient, api_oturumu: Session):
    """Gecelik tarama iki alanı tek listede birleştiriyor; ekran da öyle."""
    assert istemci.post(STOK_UCU).status_code == 200
    _finans_karari_kuyruga_koy(api_oturumu)

    kuyruk = istemci.get("/v1/approvals").json()
    alanlar = {k["alan"] for k in kuyruk}
    assert alanlar == {"stok", "finans"}

    sayfa = istemci.get("/onay/liste").text
    assert "stok" in sayfa and "finans" in sayfa


def test_geri_alinamaz_karar_ekranda_isaretli(istemci: TestClient, api_oturumu: Session):
    """Karşılık ayırma ve tasfiye geri alınamaz — operatör tıklamadan ÖNCE
    görmeli."""
    aday = finans_karari_uret()
    if aday.tip is not KararTipi.FINANS_KARSILIK_AYIR:
        # Demo dünyasında ilk aksiyonlu karar karşılık olmayabilir; o zaman
        # geri alınabilirlik bayrağının ekrana taşındığını doğrulamak yeter.
        _finans_karari_kuyruga_koy(api_oturumu)
        sayfa = istemci.get("/onay/liste").text
        assert ("geri alinamaz" in sayfa) == (not aday.geri_alinabilir)
        return

    _finans_karari_kuyruga_koy(api_oturumu)
    assert "geri alinamaz" in istemci.get("/onay/liste").text


# ---------------------------------------------------------------------------
# B2 — Kuyruk kalem bazında gruplanıyor
# ---------------------------------------------------------------------------


def test_ayni_musterinin_kararlari_tek_grupta(istemci: TestClient, api_oturumu: Session):
    """⭐ B2'nin ana iddiası: operatör ilişkiyi görebilmeli.

    Faz 7'de finans kararları çoğullaştı; bir müşteri aynı anda karşılık +
    limit + takip kararı alabiliyor. Kuyrukta üç ayrı satır olarak
    göründüklerinde operatör bunların aynı müşteriye ait olduğunu
    göremiyordu.
    """
    from app.domain.finance.decide import _demo_ozellikleri, ozellikten_kararlar_uret

    # Demo dünyasında en çok karar üreten müşteriyi bul — sabit bir müşteri
    # kimliği yazmak, dünya değişince testi sessizce anlamsızlaştırırdı.
    en_cok = max(
        (ozellikten_kararlar_uret(o) for o in _demo_ozellikleri()),
        key=len,
    )
    if len(en_cok) < 2:
        pytest.skip("demo dünyasında çoklu karar üreten müşteri yok")

    for aday in en_cok:
        politika = politika_uygula(aday, ayarlar())
        api_oturumu.add(Decision.sozlesmeden(aday, politika))
        api_oturumu.add(Approval(karar_id=aday.karar_id, durum=OnayDurumu.BEKLIYOR))
    api_oturumu.commit()

    sayfa = istemci.get("/onay/liste").text

    # Kalem adı bir kez başlıkta; kararlar onun altında ayrı satırlar.
    assert sayfa.count(en_cok[0].ozellikler.gorunen_ad) == 1
    assert f"{len(en_cok)} karar" in sayfa
    for aday in en_cok:
        assert str(aday.karar_id) in sayfa


def test_kararlar_birlestirilmiyor_ayri_onaylanabiliyor(istemci: TestClient, api_oturumu: Session):
    """Gruplama sunum; veri modeli değil. Üçü ayrı onaylanabilmeli —
    operatör "karşılık ayır ama aramaya devam et" diyebilmeli."""
    from app.domain.finance.decide import _demo_ozellikleri, ozellikten_kararlar_uret

    en_cok = max((ozellikten_kararlar_uret(o) for o in _demo_ozellikleri()), key=len)
    if len(en_cok) < 2:
        pytest.skip("demo dünyasında çoklu karar üreten müşteri yok")

    for aday in en_cok:
        politika = politika_uygula(aday, ayarlar())
        api_oturumu.add(Decision.sozlesmeden(aday, politika))
        api_oturumu.add(Approval(karar_id=aday.karar_id, durum=OnayDurumu.BEKLIYOR))
    api_oturumu.commit()

    # Yalnızca birincisini onayla.
    cevap = istemci.post(f"/onay/{en_cok[0].karar_id}/onayla", data={"kullanici": "esmanur"})
    assert cevap.status_code == 200

    kalan = {k["karar_id"] for k in istemci.get("/v1/approvals").json()}
    assert str(en_cok[0].karar_id) not in kalan
    assert str(en_cok[1].karar_id) in kalan
