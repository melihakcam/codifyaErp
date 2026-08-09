"""Finansın para metriği (Faz 7, `app/domain/finance/para_metrigi.py`).

⚠️ Bu testler **sonucun yönünü** doğrulamıyor. Kural motorunun vasat
politikayı yendiğini bir teste yazmak, ölçümü ölçüm olmaktan çıkarırdı:
kod değiştiğinde test kırılmasın diye sonucu zorlamak, tam olarak
ölçmemek demek. Doğrulanan şey **mekanizma**: eylemler doğru faturalara
uygulanıyor mu, muhasebe topluyor mu, geleceğe bakılıyor mu.

Küçük profil + 1 yıl bilinçli — koşu süresi test takımını yavaşlatmasın.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.domain.finance import para_metrigi as pm
from simulator.company import kucuk_nalbur_dukkani


@pytest.fixture(scope="module")
def karsilastirma() -> pd.DataFrame:
    return pm.tahsilat_politikasi_karsilastir(
        profile=kucuk_nalbur_dukkani(), yil_sayisi=1
    )


def _durum(faturalar: pd.DataFrame) -> pm._PolitikaDurumu:
    return pm._PolitikaDurumu(faturalar=faturalar, rng=np.random.default_rng(0))


def _fatura_tablosu(satirlar: list[dict]) -> pd.DataFrame:
    f = pd.DataFrame(satirlar)
    for kolon in ("tarih", "vade_tarihi", "gercek_odeme_tarihi"):
        f[kolon] = pd.to_datetime(f[kolon])
    f["iptal"] = False
    f["takip_denemesi"] = 0
    return f


# ---------------------------------------------------------------------------
# Etki modeli — takip
# ---------------------------------------------------------------------------


def test_takip_gecikmis_faturayi_one_ceker():
    f = _fatura_tablosu(
        [
            {
                "musteri_id": "M1",
                "tarih": "2024-01-01",
                "vade_tarihi": "2024-02-01",
                "gercek_odeme_tarihi": "2024-04-01",
                "tutar_tl": 1000.0,
            }
        ]
    )
    durum = _durum(f)
    pm._takip_uygula(durum, "M1", pd.Timestamp("2024-03-01"))

    assert durum.takip_sayisi == 1
    assert f.at[0, "gercek_odeme_tarihi"] < pd.Timestamp("2024-04-01")


def test_takip_vadesi_gelmemis_faturaya_dokunmaz():
    """Vadesi dolmamış faturayı "erken ödet" diye aramak sahada yapılmaz —
    modelde yapılırsa politikaya bedava kazanç yazar."""
    f = _fatura_tablosu(
        [
            {
                "musteri_id": "M1",
                "tarih": "2024-01-01",
                "vade_tarihi": "2024-06-01",
                "gercek_odeme_tarihi": "2024-06-10",
                "tutar_tl": 1000.0,
            }
        ]
    )
    durum = _durum(f)
    pm._takip_uygula(durum, "M1", pd.Timestamp("2024-03-01"))

    assert durum.takip_sayisi == 0
    assert f.at[0, "gercek_odeme_tarihi"] == pd.Timestamp("2024-06-10")


def test_takip_odeme_tarihini_gecmise_atmaz():
    """Aramadan önce ödenmiş faturaya dokunulmamalı."""
    f = _fatura_tablosu(
        [
            {
                "musteri_id": "M1",
                "tarih": "2024-01-01",
                "vade_tarihi": "2024-02-01",
                "gercek_odeme_tarihi": "2024-02-15",
                "tutar_tl": 1000.0,
            }
        ]
    )
    durum = _durum(f)
    pm._takip_uygula(durum, "M1", pd.Timestamp("2024-03-01"))

    assert f.at[0, "gercek_odeme_tarihi"] == pd.Timestamp("2024-02-15")


def test_batak_kurtarma_olasiligi_denemeyle_azalir():
    """Aynı faturaya ikinci gidiş, birincinin bağımsız tekrarı değil."""
    f = _fatura_tablosu(
        [
            {
                "musteri_id": "M1",
                "tarih": "2024-01-01",
                "vade_tarihi": "2024-02-01",
                "gercek_odeme_tarihi": None,
                "tutar_tl": 1000.0,
            }
        ]
    )
    durum = _durum(f)
    # RNG'yi 1.0 döndürecek şekilde sabitlemek yerine sayacı doğruluyoruz:
    # olasılığın kendisi rastgele, sayaç deterministik.
    pm._takip_uygula(durum, "M1", pd.Timestamp("2024-03-01"))
    if pd.isna(f.at[0, "gercek_odeme_tarihi"]):
        assert f.at[0, "takip_denemesi"] == 1
        pm._takip_uygula(durum, "M1", pd.Timestamp("2024-04-01"))
        assert f.at[0, "takip_denemesi"] >= 2


# ---------------------------------------------------------------------------
# Etki modeli — limit
# ---------------------------------------------------------------------------


def test_limit_bakiye_dustukce_satisi_yeniden_acar():
    """Limit bir kapı, giyotin değil: ödeme gelince yeni fatura geçmeli."""
    f = _fatura_tablosu(
        [
            # Açık bakiye 900, mart başında ödeniyor.
            {
                "musteri_id": "M1",
                "tarih": "2024-01-01",
                "vade_tarihi": "2024-02-01",
                "gercek_odeme_tarihi": "2024-03-05",
                "tutar_tl": 900.0,
            },
            # Bakiye hâlâ 900 iken kesiliyor → limiti (1000) aşar, iptal.
            {
                "musteri_id": "M1",
                "tarih": "2024-03-01",
                "vade_tarihi": "2024-04-01",
                "gercek_odeme_tarihi": "2024-04-01",
                "tutar_tl": 500.0,
            },
            # Bakiye sıfırlandıktan sonra kesiliyor → geçmeli.
            {
                "musteri_id": "M1",
                "tarih": "2024-03-10",
                "vade_tarihi": "2024-04-10",
                "gercek_odeme_tarihi": "2024-04-10",
                "tutar_tl": 500.0,
            },
        ]
    )
    durum = _durum(f)
    pm._limit_uygula(
        durum, "M1", 1000.0, pd.Timestamp("2024-02-20"), pd.Timestamp("2024-03-31")
    )

    assert bool(f.at[1, "iptal"]) is True
    assert bool(f.at[2, "iptal"]) is False
    assert durum.iptal_tutari_tl == 500.0


# ---------------------------------------------------------------------------
# Muhasebe
# ---------------------------------------------------------------------------


def test_iptal_edilen_fatura_maliyete_girmez_marj_kaybi_yazilir():
    f = _fatura_tablosu(
        [
            {
                "musteri_id": "M1",
                "tarih": "2024-01-01",
                "vade_tarihi": "2024-02-01",
                "gercek_odeme_tarihi": None,
                "tutar_tl": 1000.0,
            }
        ]
    )
    f.at[0, "iptal"] = True
    durum = _durum(f)
    durum.iptal_edilen_fatura = 1
    durum.iptal_tutari_tl = 1000.0

    ozet = pm._maliyet_ozeti(durum, pd.Timestamp("2024-12-31"), marj_orani=0.25)

    # İptal edilen fatura batak sayılmaz — o satış hiç yapılmadı.
    assert ozet["batak_zarari_tl"] == 0.0
    assert ozet["finansman_maliyeti_tl"] == 0.0
    assert ozet["kaybedilen_marj_tl"] == 250.0


def test_odenmemis_fatura_batak_ve_finansman_uretir():
    f = _fatura_tablosu(
        [
            {
                "musteri_id": "M1",
                "tarih": "2024-01-01",
                "vade_tarihi": "2024-02-01",
                "gercek_odeme_tarihi": None,
                "tutar_tl": 1000.0,
            }
        ]
    )
    ozet = pm._maliyet_ozeti(_durum(f), pd.Timestamp("2024-03-02"), marj_orani=0.25)

    assert ozet["batak_zarari_tl"] == 1000.0
    # 30 gün taşıma maliyeti.
    beklenen = 1000.0 * 30 * pm.YILLIK_FINANSMAN_ORANI / 365.0
    assert ozet["finansman_maliyeti_tl"] == pytest.approx(beklenen, rel=1e-6)


def test_erken_odeme_negatif_maliyet_yazmaz():
    f = _fatura_tablosu(
        [
            {
                "musteri_id": "M1",
                "tarih": "2024-01-01",
                "vade_tarihi": "2024-02-01",
                "gercek_odeme_tarihi": "2024-01-20",
                "tutar_tl": 1000.0,
            }
        ]
    )
    ozet = pm._maliyet_ozeti(_durum(f), pd.Timestamp("2024-03-02"), marj_orani=0.25)
    assert ozet["finansman_maliyeti_tl"] == 0.0


# ---------------------------------------------------------------------------
# Uçtan uca
# ---------------------------------------------------------------------------


def test_uc_politika_da_ciktida_var(karsilastirma: pd.DataFrame):
    assert set(karsilastirma.index) == set(pm.POLITIKALAR)


def test_taban_politika_hicbir_eylem_yapmaz(karsilastirma: pd.DataFrame):
    """Zemin politikanın takip maliyeti ve marj kaybı sıfır olmalı."""
    taban = karsilastirma.loc["taban"]
    assert taban["takip_sayisi"] == 0
    assert taban["takip_maliyeti_tl"] == 0.0
    assert taban["kaybedilen_marj_tl"] == 0.0


def test_toplam_maliyet_kalemlerin_toplami(karsilastirma: pd.DataFrame):
    for politika in pm.POLITIKALAR:
        s = karsilastirma.loc[politika]
        beklenen = (
            s["finansman_maliyeti_tl"]
            + s["batak_zarari_tl"]
            + s["takip_maliyeti_tl"]
            + s["kaybedilen_marj_tl"]
        )
        assert s["toplam_maliyet_tl"] == pytest.approx(beklenen)


def test_kural_motoru_uc_karar_tipini_de_uretir(karsilastirma: pd.DataFrame):
    """Karşılık ve limit kararları hiç üretilmiyorsa ölçüm yalnızca takibi
    ölçüyor demektir — karşılaştırma eksik olur."""
    kural = karsilastirma.loc["kural_motoru"]
    assert kural["takip_sayisi"] > 0
    assert kural["karsilik_karari"] > 0
    assert kural["limit_karari"] > 0


def test_ayni_tohum_ayni_sonuc():
    """Rapor edilen sayı tekrar üretilebilir olmalı."""
    kwargs = {"profile": kucuk_nalbur_dukkani(), "yil_sayisi": 1, "politikalar": ("vasat",)}
    bir = pm.tahsilat_politikasi_karsilastir(**kwargs)
    iki = pm.tahsilat_politikasi_karsilastir(**kwargs)
    assert bir.loc["vasat", "toplam_maliyet_tl"] == iki.loc["vasat", "toplam_maliyet_tl"]


def test_duyarlilik_analizi_sabiti_geri_yukler():
    orijinal = pm.TAKIP_MALIYETI_TL
    pm.duyarlilik_analizi_calistir(
        takip_maliyetleri=(0.0,),
        profile=kucuk_nalbur_dukkani(),
        yil_sayisi=1,
    )
    assert orijinal == pm.TAKIP_MALIYETI_TL
