"""Sözleşme testleri (Faz 0.4).

Bu testler "kod çalışıyor mu" değil, "sözleşmeyi doğru anladık mı" sorusunu
sınar. Kişi A ile Kişi B'nin aynı şeyi kastettiğinin kanıtıdır.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.contracts import Alan, DecisionCandidate, KararTipi, StockFeatures
from app.domain.stock.decide import decide_stub


def test_stub_karar_gecerli_bir_sozlesme_nesnesi():
    aday = decide_stub()
    assert aday.alan is Alan.STOK
    assert aday.tip is KararTipi.STOK_SIPARIS
    assert 0.0 <= aday.guven <= 1.0
    assert aday.tetiklenen_kurallar, "Karar en az bir kural izi taşımalı"


def test_kullanilabilir_stok_rezerveyi_duser():
    o = decide_stub().ozellikler
    assert o.kullanilabilir_stok == o.eldeki_stok - o.rezerve_stok


def test_varyasyon_katsayisi_talep_yoksa_sifir():
    o = decide_stub().ozellikler
    sifir_talepli = o.model_copy(update={"ort_gunluk_talep": 0.0})
    assert sifir_talepli.talep_varyasyon_katsayisi == 0.0


def test_ozellikler_dondurulmus():
    """Karar üretildikten sonra özellikler değişemez — denetim izi güvenilir kalsın."""
    o = decide_stub().ozellikler
    with pytest.raises(ValidationError):
        o.eldeki_stok = 999


def test_gecersiz_guven_reddedilir():
    """guven 0-1 aralığı dışındaysa nesne hiç oluşmamalı."""
    ham = decide_stub().model_dump()
    with pytest.raises(ValidationError):
        DecisionCandidate.model_validate(ham | {"guven": 1.5})


def test_negatif_stok_reddedilir():
    ham = decide_stub().ozellikler.model_dump()
    with pytest.raises(ValidationError):
        StockFeatures.model_validate(ham | {"eldeki_stok": -5})


# --- izinli_sayilar(): guard'ın dayanağı --------------------------------------


def test_izinli_sayilar_aksiyon_ve_kural_degerlerini_icerir():
    aday = decide_stub()
    izinli = aday.izinli_sayilar()

    assert 1200.0 in izinli, "Sipariş miktarı gerekçede kullanılabilmeli"
    assert 615.0 in izinli, "Kuralın hesapladığı ROP gerekçede kullanılabilmeli"
    assert 42.0 in izinli, "Ortalama günlük talep gerekçede kullanılabilmeli"
    assert 270.0 in izinli, "Hesaplanan kullanılabilir stok da izinli olmalı"


def test_izinli_sayilar_oranlari_yuzde_olarak_da_kabul_eder():
    """0.94 oranı gerekçede '%94' yazılır — guard bunu reddetmemeli."""
    izinli = decide_stub().izinli_sayilar()
    assert 0.94 in izinli
    assert 94.0 in izinli


def test_izinli_sayilar_uydurma_sayiyi_icermez():
    """Guard'ın işe yaradığının kanıtı: bağlamda olmayan sayı kümede yok."""
    izinli = decide_stub().izinli_sayilar()
    assert 9999.0 not in izinli
    assert 73.5 not in izinli
