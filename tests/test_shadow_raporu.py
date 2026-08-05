"""Faz 4.3 shadow mod raporu (`app/jobs/shadow_raporu.py`)."""

from __future__ import annotations

from app.contracts import KararTipi
from app.domain.stock.decide import decide_stub
from app.jobs.shadow_raporu import karsilastirma_uret, rapor_yaz, vasat_karari_hesapla
from app.models import Decision


def _ozellik(**gecersiz_kilanlar: object) -> dict:
    """`decide_stub()`'ın özelliklerinden bir sözlük üretir, istenen alanlar değiştirilir."""
    taban = decide_stub().ozellikler.model_dump(mode="json")
    taban.update(gecersiz_kilanlar)
    return taban


def test_vasat_esik_ustundeyse_siparis_vermez():
    ozellik = _ozellik(eldeki_stok=1000, rezerve_stok=0, yoldaki_stok=0, ort_gunluk_talep=1.0)
    vasat = vasat_karari_hesapla(ozellik)
    assert vasat.siparis_verir is False
    assert vasat.miktar == 0.0


def test_vasat_esik_altindaysa_siparis_verir():
    # net pozisyon 5, esik = 10 * 1.0 = 10 -> siparis verilmeli
    ozellik = _ozellik(
        eldeki_stok=5, rezerve_stok=0, yoldaki_stok=0, ort_gunluk_talep=1.0, moq=1, paket_adedi=1
    )
    vasat = vasat_karari_hesapla(ozellik)
    assert vasat.siparis_verir is True
    # hedef = 30 * 1.0 = 30, paket/moq 1 oldugu icin tam 30
    assert vasat.miktar == 30.0


def test_vasat_paket_ve_moq_kisitina_uyar():
    ozellik = _ozellik(
        eldeki_stok=0, rezerve_stok=0, yoldaki_stok=0, ort_gunluk_talep=1.0, moq=50, paket_adedi=12
    )
    vasat = vasat_karari_hesapla(ozellik)
    assert vasat.siparis_verir is True
    # hedef=30 -> ceil(30/12)=3 paket -> 36, ama moq 50 daha buyuk -> 50
    assert vasat.miktar == 50.0


def test_talep_sifirsa_siparis_vermez():
    ozellik = _ozellik(eldeki_stok=0, rezerve_stok=0, yoldaki_stok=0, ort_gunluk_talep=0.0)
    vasat = vasat_karari_hesapla(ozellik)
    assert vasat.siparis_verir is False


def test_karsilastirma_sadece_siparis_ve_aksiyon_yok_kapsar():
    siparis = Decision.sozlesmeden(decide_stub(), _politika_stub())
    tasfiye_aday = decide_stub().model_copy(update={"tip": KararTipi.STOK_TASFIYE})
    tasfiye = Decision.sozlesmeden(tasfiye_aday, _politika_stub())

    satirlar = karsilastirma_uret([siparis, tasfiye])
    assert len(satirlar) == 1
    assert satirlar[0].sistem_siparis_verir is True


def test_yon_uyusmazligi_dogru_isaretlenir():
    # decide_stub: siparis_miktari=1200, ort_gunluk_talep buyuk oldugu icin
    # vasat da esik altindaysa siparis verir -> ayni yon beklenir; burada
    # ozellikleri manuel olarak vasat'in "hayir" diyecegi sekilde ayarliyoruz.
    aday = decide_stub()
    aday = aday.model_copy(
        update={
            "ozellikler": aday.ozellikler.model_copy(
                update={"eldeki_stok": 100_000, "yoldaki_stok": 0, "rezerve_stok": 0}
            )
        }
    )
    karar = Decision.sozlesmeden(aday, _politika_stub())

    satirlar = karsilastirma_uret([karar])
    assert len(satirlar) == 1
    assert satirlar[0].sistem_siparis_verir is True
    assert satirlar[0].vasat_siparis_verir is False
    assert satirlar[0].ayni_yon is False


def test_rapor_yaz_bos_listede_mesaj_doner():
    assert "yok" in rapor_yaz([])


def test_rapor_yaz_ozet_satirlari_icerir():
    aday = decide_stub()
    karar = Decision.sozlesmeden(aday, _politika_stub())
    satirlar = karsilastirma_uret([karar])
    metin = rapor_yaz(satirlar)
    assert "toplam karar" in metin
    assert "yön uyuşması" in metin


def _politika_stub():
    from app.contracts import OtonomiSeviyesi, PolitikaKarari, PolitikaSonucu

    aday = decide_stub()
    return PolitikaKarari(
        karar_id=aday.karar_id,
        sonuc=PolitikaSonucu.ONAY_KUYRUGU,
        uygulandi=False,
        otonomi_seviyesi=OtonomiSeviyesi.SHADOW,
        risk_skoru=1.0,
        gerekce_kodlari=[],
    )
