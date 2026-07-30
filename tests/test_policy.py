"""Eşikli otonomi testleri.

Bu dosya projenin güvenlik kapısını sınar. Buradaki testler kırmızıysa
sistem canlıya çıkmaz — hangi kararın uygulanıp hangisinin insana gittiği
tahmine bırakılamaz.
"""

from __future__ import annotations

import pytest

from app.contracts import (
    DecisionCandidate,
    KararTipi,
    OtonomiSeviyesi,
    PolitikaSonucu,
)
from app.core.config import Ayarlar
from app.core.policy import politika_uygula, risk_skoru_hesapla
from app.domain.stock.decide import decide_stub


def ayar_ile(seviye: OtonomiSeviyesi, **kwargs) -> Ayarlar:
    return Ayarlar(
        autonomy_level=seviye,
        esik_oto_uygula_tutar_tl=5_000.0,
        esik_oto_uygula_min_guven=0.85,
        **kwargs,
    )


def aday_ile(**degisiklikler) -> DecisionCandidate:
    """Stub kararı üzerinde alan değiştirerek test vakası üretir."""
    return DecisionCandidate.model_validate(decide_stub().model_dump() | degisiklikler)


# --- Saf politika hükmü -------------------------------------------------------


def test_esik_altinda_oto_uygula():
    aday = aday_ile(tahmini_tutar_tl=4_999.0, guven=0.90)
    karar = politika_uygula(aday, ayar_ile(OtonomiSeviyesi.THRESHOLD))
    assert karar.sonuc is PolitikaSonucu.OTO_UYGULA
    assert karar.uygulandi is True


def test_tutar_esigin_tam_ustunde_onaya_gider():
    """Sınır durumu: eşik dahil değil — 5.000 TL onaya gider."""
    aday = aday_ile(tahmini_tutar_tl=5_000.0, guven=0.90)
    karar = politika_uygula(aday, ayar_ile(OtonomiSeviyesi.THRESHOLD))
    assert karar.sonuc is PolitikaSonucu.ONAY_KUYRUGU
    assert "TUTAR_ESIK_USTU" in karar.gerekce_kodlari


def test_dusuk_guven_onaya_gider():
    aday = aday_ile(tahmini_tutar_tl=100.0, guven=0.60)
    karar = politika_uygula(aday, ayar_ile(OtonomiSeviyesi.THRESHOLD))
    assert karar.sonuc is PolitikaSonucu.ONAY_KUYRUGU
    assert "GUVEN_ESIK_ALTI" in karar.gerekce_kodlari


def test_onaysiz_tedarikci_onaya_gider():
    stub = decide_stub()
    ozellikler = stub.ozellikler.model_copy(update={"tedarikci_onayli": False})
    aday = DecisionCandidate.model_validate(
        stub.model_dump()
        | {
            "tahmini_tutar_tl": 100.0,
            "guven": 0.99,
            "ozellikler": ozellikler.model_dump(),
        }
    )
    karar = politika_uygula(aday, ayar_ile(OtonomiSeviyesi.THRESHOLD))
    assert karar.sonuc is PolitikaSonucu.ONAY_KUYRUGU
    assert "TEDARIKCI_ONAYSIZ" in karar.gerekce_kodlari


def test_tasfiye_tutari_ne_olursa_olsun_onaya_gider():
    """Tasfiye geri alınamaz — 1 TL bile olsa insan onayı şart."""
    aday = aday_ile(
        tip=KararTipi.STOK_TASFIYE.value,
        tahmini_tutar_tl=1.0,
        guven=0.99,
        geri_alinabilir=False,
    )
    karar = politika_uygula(aday, ayar_ile(OtonomiSeviyesi.THRESHOLD))
    assert karar.sonuc is PolitikaSonucu.ONAY_KUYRUGU
    assert "TIP_DAIMA_ONAY" in karar.gerekce_kodlari


# --- Otonomi kademeleri -------------------------------------------------------


def test_shadow_modda_hicbir_sey_uygulanmaz():
    """En kritik test: shadow modda politika OTO_UYGULA der ama uygulanmaz."""
    aday = aday_ile(tahmini_tutar_tl=100.0, guven=0.99)
    karar = politika_uygula(aday, ayar_ile(OtonomiSeviyesi.SHADOW))
    assert karar.sonuc is PolitikaSonucu.OTO_UYGULA, "Hüküm değişmemeli"
    assert karar.uygulandi is False, "Ama uygulanmamalı"
    assert "SHADOW_UYGULANMADI" in karar.gerekce_kodlari


def test_advisory_modda_insan_uygular():
    aday = aday_ile(tahmini_tutar_tl=100.0, guven=0.99)
    karar = politika_uygula(aday, ayar_ile(OtonomiSeviyesi.ADVISORY))
    assert karar.uygulandi is False
    assert "ADVISORY_INSAN_UYGULAR" in karar.gerekce_kodlari


@pytest.mark.parametrize(
    "seviye",
    [OtonomiSeviyesi.SHADOW, OtonomiSeviyesi.ADVISORY, OtonomiSeviyesi.OFF],
)
def test_yalnizca_threshold_modu_uygular(seviye: OtonomiSeviyesi):
    aday = aday_ile(tahmini_tutar_tl=100.0, guven=0.99)
    assert politika_uygula(aday, ayar_ile(seviye)).uygulandi is False


# --- Risk skoru ---------------------------------------------------------------


def test_geri_alinamaz_karar_daha_riskli():
    geri_alinabilir = aday_ile(tahmini_tutar_tl=1_000.0, guven=0.80, geri_alinabilir=True)
    geri_alinamaz = aday_ile(tahmini_tutar_tl=1_000.0, guven=0.80, geri_alinabilir=False)
    assert risk_skoru_hesapla(geri_alinamaz) > risk_skoru_hesapla(geri_alinabilir)


def test_tam_guven_bile_sifir_risk_vermez():
    """guven=1.0 sınırsız yetki anlamına gelmemeli — taban belirsizlik korunur."""
    aday = aday_ile(tahmini_tutar_tl=1_000.0, guven=1.0)
    assert risk_skoru_hesapla(aday) > 0.0
