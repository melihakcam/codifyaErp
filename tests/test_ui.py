"""Onay ekranı (Faz 4.5, `app/api/ui.py`).

`test_approvals.py::test_tam_tur`'ün HTML/HTMX yoluyla aynısı: karar üret →
ekranda gör → onayla → kuyruktan düştüğünü doğrula. İş mantığı burada
kopyalanmıyor (`app/api/approvals.py`'yi doğrudan çağırıyor), bu yüzden
testler de o mantığı değil yalnızca HTML katmanının doğru şeyi çağırdığını
doğruluyor.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import PolitikaSonucu
from app.models import Feedback, OnayDurumu

KARAR_UCU = "/v1/decisions/stock/reorder-review"


def _karar_uret(istemci: TestClient) -> str:
    cevap = istemci.post(KARAR_UCU)
    assert cevap.status_code == 200, cevap.text
    govde = cevap.json()
    assert govde["politika"]["sonuc"] == PolitikaSonucu.ONAY_KUYRUGU.value
    return govde["aday"]["karar_id"]


def test_onay_sayfasi_acilir(istemci: TestClient):
    cevap = istemci.get("/onay")
    assert cevap.status_code == 200
    assert "text/html" in cevap.headers["content-type"]
    assert 'hx-get="/onay/liste"' in cevap.text


def test_liste_bekleyen_karari_gosterir(istemci: TestClient):
    karar_id = _karar_uret(istemci)

    cevap = istemci.get("/onay/liste")
    assert cevap.status_code == 200
    assert karar_id in cevap.text
    assert "1 karar onay bekliyor" in cevap.text


def test_liste_bos_kuyrukta_mesaj_gosterir(istemci: TestClient):
    cevap = istemci.get("/onay/liste")
    assert cevap.status_code == 200
    assert "Kuyruk bos" in cevap.text


def test_onayla_butonu_kuyruktan_dusurur(istemci: TestClient):
    karar_id = _karar_uret(istemci)

    cevap = istemci.post(f"/onay/{karar_id}/onayla", data={"kullanici": "esmanur"})
    assert cevap.status_code == 200
    assert karar_id not in cevap.text
    assert "Kuyruk bos" in cevap.text

    kuyruk = istemci.get("/v1/approvals").json()
    assert kuyruk == []


def test_reddet_geri_bildirim_yazar(istemci: TestClient, api_oturumu: Session):
    karar_id = _karar_uret(istemci)

    cevap = istemci.post(f"/onay/{karar_id}/reddet", data={"kullanici": "esmanur"})
    assert cevap.status_code == 200

    geri_bildirimler = api_oturumu.scalars(select(Feedback)).all()
    assert len(geri_bildirimler) == 1
    assert str(geri_bildirimler[0].karar_id) == karar_id
    assert geri_bildirimler[0].tur.value == "red"
    assert geri_bildirimler[0].kullanici == "esmanur"


def test_kullanici_bos_gonderilirse_varsayilana_duser(istemci: TestClient):
    karar_id = _karar_uret(istemci)

    cevap = istemci.post(f"/onay/{karar_id}/onayla", data={"kullanici": "   "})
    assert cevap.status_code == 200

    kuyruk_gecmisi = istemci.get("/v1/approvals?durum=onaylandi").json()
    assert len(kuyruk_gecmisi) == 1
    assert kuyruk_gecmisi[0]["durum"] == OnayDurumu.ONAYLANDI.value
