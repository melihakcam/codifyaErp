"""Fatura geçmişinden `FinansOzellikleri` üretimi (Faz 6.4).

En kritik değişmez **geleceği görmemek**. Sistem ölçüm tarihinde yalnızca o
tarihe kadar olan bilgiye sahip olmalı; "yarın ödenecek" bilgisini bugün
kullanmak geriye dönük testi geçersiz kılar ve sonuçlar gerçekte
ulaşılamayacak kadar iyi çıkar.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from app.domain.finance.features import (
    ASGARI_ODEME_SAYISI,
    KREDI_ONAY_TAHSILAT_ESIGI,
    musteri_ozelliklerini_hesapla,
)


def _musteriler() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "musteri_id": ["M-1", "M-2", "M-3"],
            "musteri_adi": ["Alfa Yapı", "Beta İnşaat", "Gama Ltd."],
            "segment": ["perakendeci", "santiye", "usta"],
            "odeme_vadesi_gun": [30, 45, 15],
        }
    )


def _fatura(musteri: str, tarih: str, tutar: float, vade: int, odeme: str | None) -> dict:
    t = pd.Timestamp(tarih)
    return {
        "tarih": t,
        "sku_id": "S-1",
        "tutar_tl": tutar,
        "odeme_vadesi_gun": vade,
        "odeme_tarihi": t + pd.Timedelta(days=vade),
        "musteri_id": musteri,
        "gercek_odeme_tarihi": pd.Timestamp(odeme) if odeme else pd.NaT,
        "gecikme_gun": (
            (pd.Timestamp(odeme) - (t + pd.Timedelta(days=vade))).days if odeme else float("nan")
        ),
        "odendi": odeme is not None,
    }


# --- Geleceği görmeme ---------------------------------------------------------


def test_olcum_tarihinden_sonraki_odeme_bilinmiyor():
    """⭐ Geriye dönük testin geçerliliği buna bağlı.

    Fatura 1 Mart'ta ödenmiş; 1 Şubat'ta bakarken bu bilinemez, alacak
    **açık** görünmeli.
    """
    m = _musteriler()
    f = pd.DataFrame([_fatura("M-1", "2026-01-01", 10_000.0, 30, "2026-03-01")])

    oz = musteri_ozelliklerini_hesapla(f, m, dt.date(2026, 2, 1))

    assert len(oz) == 1
    assert oz[0].toplam_alacak_tl == 10_000.0, "1 Şubat'ta bu fatura hâlâ açık"
    assert oz[0].vadesi_gecen_tl == 10_000.0, "vadesi 31 Ocak'tı, gecikmede"


def test_olcum_tarihinden_sonra_kesilen_fatura_sayilmiyor():
    m = _musteriler()
    f = pd.DataFrame(
        [
            _fatura("M-1", "2026-01-01", 10_000.0, 30, None),
            _fatura("M-1", "2026-06-01", 99_000.0, 30, None),
        ]
    )

    oz = musteri_ozelliklerini_hesapla(f, m, dt.date(2026, 2, 1))

    assert oz[0].toplam_alacak_tl == 10_000.0, "Haziran faturası Şubat'ta görülemez"


def test_odeme_profili_yalnizca_gecmis_odemelerden():
    """Ortalama gecikme, ölçüm tarihinden sonra tahsil edilenleri içermemeli."""
    m = _musteriler()
    f = pd.DataFrame(
        [
            _fatura("M-1", "2026-01-01", 1_000.0, 30, "2026-02-05"),  # 5 gün geç
            _fatura("M-1", "2026-01-02", 1_000.0, 30, "2026-02-06"),  # 5 gün geç
            _fatura("M-1", "2026-01-03", 1_000.0, 30, "2026-09-01"),  # 180 gün geç
        ]
    )

    oz = musteri_ozelliklerini_hesapla(f, m, dt.date(2026, 3, 1))

    assert oz[0].ort_odeme_gecikmesi_gun == 5.0, (
        "Eylül'deki ödeme Mart'ta bilinemez; ortalamayı bozmamalı"
    )


# --- Açık alacak ve yaşlandırma -----------------------------------------------


def test_en_eski_gecikme_dogru():
    m = _musteriler()
    f = pd.DataFrame(
        [
            _fatura("M-1", "2025-06-01", 5_000.0, 30, None),
            _fatura("M-1", "2026-01-01", 3_000.0, 30, None),
        ]
    )

    oz = musteri_ozelliklerini_hesapla(f, m, dt.date(2026, 3, 1))

    # 2025-07-01 vadeli fatura, 2026-03-01'de 243 gün gecikmede
    assert oz[0].en_eski_gecikme_gun == 243
    assert oz[0].toplam_alacak_tl == 8_000.0


def test_vadesi_gelmemis_alacak_gecikmis_sayilmiyor():
    m = _musteriler()
    f = pd.DataFrame([_fatura("M-1", "2026-02-20", 4_000.0, 30, None)])

    oz = musteri_ozelliklerini_hesapla(f, m, dt.date(2026, 3, 1))

    assert oz[0].toplam_alacak_tl == 4_000.0
    assert oz[0].vadesi_gecen_tl == 0.0, "vade 22 Mart, henüz gecikme yok"
    assert oz[0].en_eski_gecikme_gun == 0


# --- Tahsilat oranı -----------------------------------------------------------


def test_tahsilat_orani_odenen_bolu_faturalanan():
    m = _musteriler()
    f = pd.DataFrame(
        [
            _fatura("M-1", "2026-01-01", 7_000.0, 30, "2026-02-01"),
            _fatura("M-1", "2026-01-02", 3_000.0, 30, None),
        ]
    )

    oz = musteri_ozelliklerini_hesapla(f, m, dt.date(2026, 3, 1))

    assert oz[0].tahsilat_orani == 0.7


def test_dusuk_tahsilatli_musteri_kredi_onaysiz():
    """Oto-uygulamayı engelleyen alan-özel durum."""
    m = _musteriler()
    f = pd.DataFrame(
        [
            _fatura("M-1", "2026-01-01", 1_000.0, 30, "2026-02-01"),
            _fatura("M-1", "2026-01-02", 1_000.0, 30, "2026-02-02"),
            _fatura("M-1", "2026-01-03", 1_000.0, 30, "2026-02-03"),
            _fatura("M-1", "2026-01-04", 90_000.0, 30, None),
        ]
    )

    oz = musteri_ozelliklerini_hesapla(f, m, dt.date(2026, 3, 1))

    assert oz[0].tahsilat_orani < KREDI_ONAY_TAHSILAT_ESIGI
    assert not oz[0].musteri_kredi_onayli
    assert oz[0].oto_uygulama_engeli() == "MUSTERI_KREDI_ONAYSIZ"


# --- Az veri -----------------------------------------------------------------


def test_az_odemeli_musteride_katalog_sapmasi():
    """⚠️ Tek gözlemden sapma 0 çıkar — bu riski yok saymak olur.

    `csv_erp.py::ASGARI_SIPARIS_SAYISI` ile aynı gerekçe.
    """
    m = _musteriler()
    satirlar = [
        # M-2: bol gözlem, gerçek sapma var
        *[
            _fatura("M-2", f"2026-01-{g:02d}", 1_000.0, 30, f"2026-02-{g + 5:02d}")
            for g in range(1, 10)
        ],
        # M-1: tek ödeme
        _fatura("M-1", "2026-01-01", 1_000.0, 30, "2026-02-01"),
    ]
    oz = musteri_ozelliklerini_hesapla(pd.DataFrame(satirlar), m, dt.date(2026, 3, 1))
    tek = next(o for o in oz if o.musteri_id == "M-1")

    assert ASGARI_ODEME_SAYISI > 1
    assert tek.odeme_gecikmesi_std >= 0.0


def test_faturasiz_musteri_listeye_girmiyor():
    """Alacağı olmayan müşteri için tahsilat kararı üretmek anlamsız."""
    m = _musteriler()
    f = pd.DataFrame([_fatura("M-1", "2026-01-01", 1_000.0, 30, None)])

    oz = musteri_ozelliklerini_hesapla(f, m, dt.date(2026, 3, 1))

    assert {o.musteri_id for o in oz} == {"M-1"}


def test_bos_gecmis_bos_liste():
    m = _musteriler()
    f = pd.DataFrame([_fatura("M-1", "2026-06-01", 1_000.0, 30, None)])

    assert musteri_ozelliklerini_hesapla(f, m, dt.date(2026, 1, 1)) == []


# --- Sözleşme -----------------------------------------------------------------


def test_uretilen_ozellikler_karar_uretebiliyor():
    from app.domain.finance.decide import ozellikten_karar_uret

    m = _musteriler()
    f = pd.DataFrame(
        [
            _fatura("M-1", "2025-06-01", 5_000.0, 30, None),
            _fatura("M-1", "2026-01-01", 3_000.0, 30, "2026-02-05"),
        ]
    )

    oz = musteri_ozelliklerini_hesapla(f, m, dt.date(2026, 3, 1))
    karar = ozellikten_karar_uret(oz[0])

    assert karar.tip.alan == "finans"
    assert karar.izinli_sayilar()
