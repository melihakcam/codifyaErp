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


def test_izinli_sayilar_adet_alani_1_iken_100_uretmez():
    """Regresyon: Kişi B'nin B2.5 guard incelemesinde bulduğu kusur.

    ×100 karşılığı eskiden değere (0-1 aralığı) göre ekleniyordu; bu da
    `son_hareket_gun_once` gibi bir adet/gün alanı 1 değerini aldığında
    "%100" sayısını yanlışlıkla izinli hale getiriyordu — 2.000 SKU'lu bir
    katalogda dün hareket görmüş her ürün bu durumdaydı. ×100 artık yalnızca
    `ORAN_ALANLARI`'nda adı geçen alanlar için üretilir.

    `paket_adedi` stub'da varsayılan olarak 100 olduğundan (100'ün başka
    meşru kaynağı), önce 250'ye çekilir — Kişi B'nin orijinal doğrulamasıyla
    aynı izolasyon.
    """
    stub = decide_stub()
    temel_ozellik = stub.ozellikler.model_copy(update={"paket_adedi": 250})
    temel_aday = stub.model_copy(update={"ozellikler": temel_ozellik})
    assert 100.0 not in temel_aday.izinli_sayilar(), "paket_adedi=250 iken 100 izinli olmamalı"

    ozellikler_1 = temel_ozellik.model_copy(update={"son_hareket_gun_once": 1})
    aday = stub.model_copy(update={"ozellikler": ozellikler_1})
    assert 100.0 not in aday.izinli_sayilar()

    for alan in ("yoldaki_stok", "rezerve_stok", "veri_gun_sayisi", "moq", "eldeki_stok"):
        ozellik_guncel = temel_ozellik.model_copy(update={alan: 1})
        aday_guncel = stub.model_copy(update={"ozellikler": ozellik_guncel})
        assert 100.0 not in aday_guncel.izinli_sayilar(), f"{alan}=1 iken 100 izinli olmamalı"


def test_izinli_sayilar_oran_sinir_degerlerinde_dogru_calisir():
    """Oranın kendisi gerçekten 1.0 (%100) veya 0.0 (%0) ise bu meşrudur."""
    stub = decide_stub()

    tam_teslimat = stub.ozellikler.model_copy(update={"tedarikci_zamaninda_teslim_orani": 1.0})
    assert 100.0 in stub.model_copy(update={"ozellikler": tam_teslimat}).izinli_sayilar()

    hic_teslimat_yok = stub.ozellikler.model_copy(update={"tedarikci_zamaninda_teslim_orani": 0.0})
    assert 0.0 in stub.model_copy(update={"ozellikler": hic_teslimat_yok}).izinli_sayilar()


def test_izinli_sayilar_guven_kumede_yok():
    """Güven skoru iş kullanıcısına gösterilecek bir sayı değil — LLM'in
    gerekçede güveni yüzde olarak kullanamaması bilinçli bir tercihtir."""
    aday = decide_stub()
    izinli = aday.izinli_sayilar()
    assert aday.guven not in izinli
    assert aday.guven * 100 not in izinli
