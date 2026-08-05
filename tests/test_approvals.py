"""Onay kuyruğu, geri bildirim ve içgörü uçları (Faz 1 B1.5).

Dosyanın merkezi `test_tam_tur`: görev dosyasının "bitti sayılır" ölçütü olan
**karar üret → kuyrukta gör → reddet → feedback tablosuna düştüğünü doğrula**
turu. O test kırmızıysa B1.5 bitmemiş demektir.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import GuardSonucu, PolitikaSonucu
from app.models import Approval, Decision, DecisionAudit, Feedback, OnayDurumu

KARAR_UCU = "/v1/decisions/stock/reorder-review"


def _karar_uret(istemci: TestClient, *, gerekce: bool = False) -> dict:
    cevap = istemci.post(f"{KARAR_UCU}?gerekce={'true' if gerekce else 'false'}")
    assert cevap.status_code == 200, cevap.text
    return cevap.json()


# --- Kabul ölçütü -------------------------------------------------------------


def test_tam_tur(istemci: TestClient, api_oturumu: Session):
    """⭐ B1.5'in kabul ölçütü: karar → kuyruk → red → feedback."""
    # 1. Karar üret
    karar = _karar_uret(istemci)
    karar_id = karar["aday"]["karar_id"]
    assert karar["politika"]["sonuc"] == PolitikaSonucu.ONAY_KUYRUGU.value

    # 2. Kuyrukta gör
    kuyruk = istemci.get("/v1/approvals").json()
    assert len(kuyruk) == 1
    assert kuyruk[0]["karar_id"] == karar_id
    assert kuyruk[0]["durum"] == OnayDurumu.BEKLIYOR.value
    assert kuyruk[0]["risk_skoru"] > 0

    # 3. Reddet
    red = istemci.post(
        f"/v1/approvals/{karar_id}",
        json={"eylem": "reddet", "kullanici": "esmanur", "yorum": "Tedarikçi riskli."},
    )
    assert red.status_code == 200, red.text
    assert red.json()["durum"] == OnayDurumu.REDDEDILDI.value

    # 4. feedback tablosuna düştü mü
    geri_bildirimler = api_oturumu.scalars(select(Feedback)).all()
    assert len(geri_bildirimler) == 1
    assert str(geri_bildirimler[0].karar_id) == karar_id
    assert geri_bildirimler[0].tur.value == "red"
    assert geri_bildirimler[0].kullanici == "esmanur"
    assert geri_bildirimler[0].yorum == "Tedarikçi riskli."

    # 5. Kuyruk artık bekleyen kayıt göstermiyor
    assert istemci.get("/v1/approvals").json() == []
    tumu = istemci.get("/v1/approvals?durum=reddedildi").json()
    assert len(tumu) == 1


# --- Kayıt ve denetim ---------------------------------------------------------


def test_karar_dbye_yazilir(istemci: TestClient, api_oturumu: Session):
    karar = _karar_uret(istemci)

    satir = api_oturumu.scalars(select(Decision)).one()
    assert str(satir.karar_id) == karar["aday"]["karar_id"]
    assert satir.tahmini_tutar_tl == karar["aday"]["tahmini_tutar_tl"]
    # B1.4: eşikler tabloda olduğu için yedeğe düşme uyarısı çıkmamalı.
    assert "ESIK_VARSAYILANA_DUSTU" not in satir.gerekce_kodlari


def test_her_karar_denetim_satiri_birakir(istemci: TestClient, api_oturumu: Session):
    """KURAL: denetim kaydı olmayan karar yolu yok."""
    _karar_uret(istemci)

    kayit = api_oturumu.scalars(select(DecisionAudit)).one()
    assert len(kayit.girdi_hash) == 64
    assert kayit.cikti
    assert kayit.guard_sonucu is GuardSonucu.ATLANDI


def test_gerekce_istenince_denetime_guard_sonucu_yazilir(istemci: TestClient, api_oturumu: Session):
    _karar_uret(istemci, gerekce=True)

    kayit = api_oturumu.scalars(select(DecisionAudit)).one()
    # ⚠️ Belirli bir guard sonucuna bağlanmıyor. Bu test stub döneminde
    # `SABLONA_DUSTU` bekliyordu (`explain_stub` her zaman şablon dönerdi);
    # gerçek model bağlandıktan sonra sonuç **hangi modelin yapılandırıldığına**
    # bağlı hale geldi (taban model guard'ı geçiyor, eğitilmiş model çoğunlukla
    # şablona düşüyor — bkz. OLCUMLER.md "2. turun KÖK NEDENİ").
    #
    # Burada doğrulanan asıl davranış: gerekçe istendiğinde denetim satırına
    # **gerçek bir guard sonucu** yazılıyor, `ATLANDI` kalmıyor.
    assert kayit.guard_sonucu is not GuardSonucu.ATLANDI
    assert kayit.guard_sonucu in {
        GuardSonucu.GECTI,
        GuardSonucu.YENIDEN_URETILDI,
        GuardSonucu.SABLONA_DUSTU,
    }

    satir = api_oturumu.scalars(select(Decision)).one()
    assert satir.gerekce_metni is not None


# --- Kuyruğa kimin girdiği ----------------------------------------------------


def test_esik_altindaki_karar_kuyruga_girmez(istemci: TestClient, api_oturumu: Session):
    """Shadow modda eşik altı karar KAYDEDİLİR ama kuyruğa GİRMEZ.

    Kimsenin bakmayacağı bir kaydı insanın önüne koymak kuyruğu değersizleştirir.
    Eşiği stub kararın tutarının (5.700 TL) üstüne çekip sınıyoruz.
    """
    from app.models import Policy

    esik = api_oturumu.scalars(select(Policy)).all()
    for satir in esik:
        satir.esik_oto_uygula_tutar_tl = 100_000.0
        satir.esik_oto_uygula_min_guven = 0.1
    api_oturumu.commit()

    karar = _karar_uret(istemci)

    assert karar["politika"]["sonuc"] == PolitikaSonucu.OTO_UYGULA.value
    assert karar["politika"]["uygulandi"] is False, "shadow modda uygulanmamalı"
    assert api_oturumu.scalars(select(Decision)).all(), "karar kaydedilmeli"
    assert api_oturumu.scalars(select(Approval)).all() == [], "kuyruğa girmemeli"
    assert istemci.get("/v1/approvals").json() == []


# --- Onay ucunun sınır durumları ----------------------------------------------


def test_bilinmeyen_karar_404(istemci: TestClient):
    cevap = istemci.post(
        f"/v1/approvals/{uuid4()}",
        json={"eylem": "onayla", "kullanici": "esmanur"},
    )
    assert cevap.status_code == 404


def test_ayni_karar_iki_kez_sonuclandirilamaz(istemci: TestClient):
    """İkinci istek 409 — iş akışı geçmişi üzerine yazılmamalı."""
    karar_id = _karar_uret(istemci)["aday"]["karar_id"]
    govde = {"eylem": "onayla", "kullanici": "esmanur"}

    assert istemci.post(f"/v1/approvals/{karar_id}", json=govde).status_code == 200
    ikinci = istemci.post(f"/v1/approvals/{karar_id}", json=govde)
    assert ikinci.status_code == 409
    assert "feedback" in ikinci.json()["detail"]


def test_duzeltme_aksiyon_olmadan_reddedilir(istemci: TestClient):
    """ "Düzeltildi" yazan ama neye düzeltildiği belirsiz kayıt oluşmamalı."""
    karar_id = _karar_uret(istemci)["aday"]["karar_id"]

    cevap = istemci.post(
        f"/v1/approvals/{karar_id}",
        json={"eylem": "duzelt", "kullanici": "esmanur"},
    )
    assert cevap.status_code == 422


def test_duzeltme_aksiyonu_feedbacke_yazilir(istemci: TestClient, api_oturumu: Session):
    """En değerli eğitim sinyali: insanın "1.200 değil 800" demesi."""
    karar_id = _karar_uret(istemci)["aday"]["karar_id"]

    cevap = istemci.post(
        f"/v1/approvals/{karar_id}",
        json={
            "eylem": "duzelt",
            "kullanici": "esmanur",
            "duzeltilmis_aksiyon": {"siparis_miktari": 800},
            "yorum": "1.200 fazla.",
        },
    )
    assert cevap.status_code == 200
    assert cevap.json()["durum"] == OnayDurumu.DUZELTILDI.value

    geri = api_oturumu.scalars(select(Feedback)).one()
    assert geri.duzeltilmis_aksiyon == {"siparis_miktari": 800}


def test_kullanici_zorunlu(istemci: TestClient):
    """Kararı kimin verdiği bilinmeden denetim izi eksik kalır."""
    karar_id = _karar_uret(istemci)["aday"]["karar_id"]

    cevap = istemci.post(f"/v1/approvals/{karar_id}", json={"eylem": "onayla"})
    assert cevap.status_code == 422


def test_onay_karar_veren_ve_zamani_kaydeder(istemci: TestClient, api_oturumu: Session):
    karar_id = _karar_uret(istemci)["aday"]["karar_id"]
    istemci.post(f"/v1/approvals/{karar_id}", json={"eylem": "onayla", "kullanici": "melih"})

    onay = api_oturumu.scalars(select(Approval)).one()
    assert onay.durum is OnayDurumu.ONAYLANDI
    assert onay.karar_veren == "melih"
    assert onay.karar_zamani is not None


def test_onay_uygulandi_alanina_dokunmaz(istemci: TestClient, api_oturumu: Session):
    """⚠️ `uygulandi` "sistem uyguladı mı" demek; insan onayı bunu değiştirmez.

    Karıştırılırsa shadow mod raporu (politikanın hükmü vs gerçekten olan)
    anlamını kaybeder.
    """
    karar_id = _karar_uret(istemci)["aday"]["karar_id"]
    istemci.post(f"/v1/approvals/{karar_id}", json={"eylem": "onayla", "kullanici": "melih"})

    api_oturumu.expire_all()
    assert api_oturumu.scalars(select(Decision)).one().uygulandi is False


# --- Kuyruk sıralaması --------------------------------------------------------


def test_kuyruk_riske_gore_azalan_sirali(istemci: TestClient, api_oturumu: Session):
    """İnsanın zamanı kısıtlı — en riskli karar en üstte olmalı."""
    for _ in range(3):
        _karar_uret(istemci)

    # Risk skorlarını elle ayırıyoruz; stub her çağrıda aynı değeri üretiyor.
    for sira, satir in enumerate(api_oturumu.scalars(select(Decision)).all()):
        satir.risk_skoru = float(sira + 1) * 100.0
    api_oturumu.commit()

    kuyruk = istemci.get("/v1/approvals").json()
    riskler = [k["risk_skoru"] for k in kuyruk]
    assert riskler == sorted(riskler, reverse=True)
    assert riskler[0] == 300.0


# --- /v1/feedback -------------------------------------------------------------


def test_feedback_ucu_ayni_karara_birden_cok_kayit_alir(istemci: TestClient, api_oturumu: Session):
    """İş akışı ucu bir kez sonuçlandırır; veri ucu sınırsız yorum alır."""
    karar_id = _karar_uret(istemci)["aday"]["karar_id"]
    istemci.post(f"/v1/approvals/{karar_id}", json={"eylem": "onayla", "kullanici": "melih"})

    for yorum in ("Sonradan bakınca fazla geldi.", "Tedarikçi de gecikti."):
        cevap = istemci.post(
            "/v1/feedback",
            json={
                "karar_id": karar_id,
                "tur": "duzeltme",
                "kullanici": "esmanur",
                "yorum": yorum,
            },
        )
        assert cevap.status_code == 200, cevap.text

    # 1 onay + 2 ek yorum
    assert len(api_oturumu.scalars(select(Feedback)).all()) == 3
    # İş akışı durumu değişmedi.
    assert api_oturumu.scalars(select(Approval)).one().durum is OnayDurumu.ONAYLANDI


def test_feedback_bilinmeyen_karar_404(istemci: TestClient):
    cevap = istemci.post(
        "/v1/feedback",
        json={"karar_id": str(uuid4()), "tur": "red", "kullanici": "esmanur"},
    )
    assert cevap.status_code == 404


# --- /v1/insights -------------------------------------------------------------


def test_insights_bos_liste_doner(istemci: TestClient):
    """Tablo Faz 2 B2.6'ya kadar boş; uç yine de çalışmalı."""
    cevap = istemci.get("/v1/insights")
    assert cevap.status_code == 200
    assert cevap.json() == []


def test_insights_onem_skoruna_gore_sirali(istemci: TestClient, api_oturumu: Session):
    from app.contracts import Alan
    from app.models import Insight

    kosu = uuid4()
    for skor in (0.3, 0.9, 0.6):
        api_oturumu.add(
            Insight(
                kosu_id=kosu,
                alan=Alan.STOK,
                baslik=f"bulgu {skor}",
                metin="metin",
                onem_skoru=skor,
            )
        )
    api_oturumu.commit()

    kalemler = istemci.get("/v1/insights").json()
    assert [k["onem_skoru"] for k in kalemler] == [0.9, 0.6, 0.3]

    # kosu_id filtresi: "bu sabahın bulguları" tek sorguyla çekilebilmeli.
    assert len(istemci.get(f"/v1/insights?kosu_id={kosu}").json()) == 3
    assert istemci.get(f"/v1/insights?kosu_id={uuid4()}").json() == []
