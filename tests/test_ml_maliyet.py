"""A4.4 — maliyet_raporu_uret testleri.

Sentetik, elle hesaplanabilir küçük bir `sonuc` sözlüğüyle sınanıyor —
gerçek simülasyonu çalıştırmadan formülün doğruluğunu doğrular.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.domain.stock.ml import maliyet_raporu_uret
from app.domain.stock.rules import (
    VARSAYILAN_SIPARIS_MALIYETI_TL,
    VARSAYILAN_YILLIK_ELDE_TUTMA_ORANI,
)


def _sonuc(**degisiklikler) -> dict:
    sku_df = pd.DataFrame(
        {
            "sku_id": ["S-001", "S-002"],
            "birim_maliyet_tl": [10.0, 100.0],
            "satis_fiyati_tl": [15.0, 150.0],
        }
    )
    envanter_gunluk = pd.DataFrame(
        {
            "tarih": pd.to_datetime(["2026-01-01", "2026-01-02"] * 2),
            "sku_id": ["S-001", "S-001", "S-002", "S-002"],
            "eldeki_stok": [100, 100, 10, 10],
        }
    )
    karsilanamayan_talep = pd.DataFrame(
        {
            "tarih": pd.to_datetime(["2026-01-01"]),
            "sku_id": ["S-002"],
            "karsilanamayan_miktar": [5.0],
        }
    )
    talep = pd.DataFrame({"talep_miktari": [50.0, 5.0, 20.0]})
    siparisler = pd.DataFrame({"sku_id": ["S-001"], "siparis_miktari": [200]})

    taban = {
        "sku": sku_df,
        "envanter_gunluk": envanter_gunluk,
        "karsilanamayan_talep": karsilanamayan_talep,
        "talep": talep,
        "siparisler": siparisler,
    }
    taban.update(degisiklikler)
    return taban


def test_asiri_stok_maliyeti_gunluk_elde_tutma_oranindan_dogru_hesaplanir():
    rapor = maliyet_raporu_uret(_sonuc())
    gunluk_oran = VARSAYILAN_YILLIK_ELDE_TUTMA_ORANI / 365.0
    # (100+100)*10*oran + (10+10)*100*oran
    beklenen = (200 * 10.0 + 20 * 100.0) * gunluk_oran
    assert rapor["asiri_stok_maliyeti_tl"] == pytest.approx(beklenen)


def test_kayip_kar_marj_ve_ceza_carpaniyla_hesaplanir():
    rapor = maliyet_raporu_uret(_sonuc(), stoktukenmesi_ceza_carpani=2.0)
    # kar marji = 150-100 = 50, 5 adet karsilanamadi, ceza carpani 2.0
    assert rapor["kayip_kar_tl"] == pytest.approx(5.0 * 50.0 * 2.0)


def test_stok_tukenme_orani_dogru():
    rapor = maliyet_raporu_uret(_sonuc())
    assert rapor["toplam_talep_adet"] == 75.0
    assert rapor["toplam_karsilanamayan_adet"] == 5.0
    assert rapor["stok_tukenme_orani"] == pytest.approx(5.0 / 75.0)


def test_siparis_maliyeti_siparis_sayisina_gore():
    rapor = maliyet_raporu_uret(_sonuc())
    assert rapor["siparis_sayisi"] == 1
    assert rapor["siparis_maliyeti_tl"] == pytest.approx(VARSAYILAN_SIPARIS_MALIYETI_TL)


def test_toplam_maliyet_bilesenlerin_toplami():
    rapor = maliyet_raporu_uret(_sonuc())
    toplam = rapor["kayip_kar_tl"] + rapor["asiri_stok_maliyeti_tl"] + rapor["siparis_maliyeti_tl"]
    assert rapor["toplam_maliyet_tl"] == pytest.approx(toplam)


def test_karsilanamayan_talep_bosken_kayip_kar_sifir():
    sonuc = _sonuc(
        karsilanamayan_talep=pd.DataFrame(columns=["tarih", "sku_id", "karsilanamayan_miktar"])
    )
    rapor = maliyet_raporu_uret(sonuc)
    assert rapor["kayip_kar_tl"] == 0.0
    assert rapor["toplam_karsilanamayan_adet"] == 0.0
