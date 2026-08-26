"""Tahsilat simülasyonu testleri (Faz 6.2).

Modelin özü tek bir ayrımda: **ortalama gecikme ile gecikmenin oynaklığı
ayrı şeylerdir.** Hep 40 gün geç ödeyen müşteri planlanabilir; 10-90 gün
arası rastgele ödeyen planlanamaz. İkincisi daha riskli, ortalaması daha iyi
olsa bile. Bu testler o ayrımın gerçekten üretildiğini doğruluyor.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from simulator.company import yapi_malzemesi_toptancisi
from simulator.tahsilat import (
    SEGMENT_GECIKME_EGILIMI,
    TahsilatPatolojisi,
    acik_alacaklar,
    tahsilat_uret,
)


def _musteriler(n: int = 200) -> pd.DataFrame:
    profil = yapi_malzemesi_toptancisi()
    segmentler = list(profil.musteri_segmentleri)
    seg = [segmentler[i % len(segmentler)] for i in range(n)]
    return pd.DataFrame(
        {
            "musteri_id": [f"M-{i:04d}" for i in range(1, n + 1)],
            "musteri_adi": [f"Müşteri {i}" for i in range(1, n + 1)],
            "segment": seg,
            "odeme_vadesi_gun": [profil.musteri_odeme_vadesi_gun[s] for s in seg],
        }
    )


def _faturalar(musteri_df: pd.DataFrame, gun: int = 200, tohum: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(tohum)
    vadeler = musteri_df["odeme_vadesi_gun"].unique()
    n = gun * 5
    tarihler = pd.Timestamp("2026-01-01") + pd.to_timedelta(rng.integers(0, gun, n), unit="D")
    vade = rng.choice(vadeler, size=n)
    return pd.DataFrame(
        {
            "tarih": tarihler,
            "sku_id": [f"S-{i % 50:04d}" for i in range(n)],
            "tutar_tl": rng.uniform(500, 25_000, n).round(2),
            "odeme_vadesi_gun": vade,
            "odeme_tarihi": tarihler + pd.to_timedelta(vade, unit="D"),
        }
    )


# --- Sözleşme uyumu -----------------------------------------------------------


def test_segment_adlari_profille_uyusuyor():
    """⭐ İlk yazımda tam bu hata yapıldı.

    `SEGMENT_GECIKME_EGILIMI` uydurma adlar taşıyordu (`perakende`, `bayi`,
    `müteahhit`). Hiçbiri `CompanyProfile.musteri_segmentleri` ile eşleşmedi,
    her müşteri varsayılana düştü ve segment farklılaşması **sessizce**
    çalışmadı — dört segmentin dördü de ~17 gün ortalama verdi.

    Sessiz olması tehlikeliydi: hata yok, uyarı yok, yalnızca yanlış veri.
    """
    profil = yapi_malzemesi_toptancisi()

    eksik = set(profil.musteri_segmentleri) - set(SEGMENT_GECIKME_EGILIMI)

    assert not eksik, f"gecikme eğilimi tanımsız segment: {eksik}"


def test_stok_simulasyonuna_dokunulmuyor():
    """`run.py`'nin RNG akışı korunmalı — yoksa tüm stok ölçümleri geçersiz olur.

    Tahsilat modülü stok simülasyonunu **çağırmamalı**; ona `run.py`'nin
    çıktısı dışarıdan verilir. Çağırsaydı ya da RNG'sine dokunsaydı para
    metriği, shadow raporu ve aşırı uyum testi yeniden ölçülmek zorunda
    kalırdı.

    ⚠️ Kontrol ham metin araması DEĞİL — modül docstring'i `tedarik_rng`'yi
    zaten açıklıyor ve metin araması onu da yakalıyordu. Bakılması gereken
    şey bağımlılık: modül `simulator.run`'ı import ediyor mu?
    """
    import ast
    import inspect

    from simulator import tahsilat

    agac = ast.parse(inspect.getsource(tahsilat))
    ithal: set[str] = set()
    for dugum in ast.walk(agac):
        if isinstance(dugum, ast.Import):
            ithal.update(a.name for a in dugum.names)
        elif isinstance(dugum, ast.ImportFrom) and dugum.module:
            ithal.add(dugum.module)

    assert not any(m.startswith("simulator.run") for m in ithal), (
        f"tahsilat modülü stok simülasyonuna bağımlı olmamalı: {ithal}"
    )


# --- Modelin özü: ortalama ≠ oynaklık ----------------------------------------


def test_kronik_geciken_kotu_ama_ongorulebilir():
    """Yüksek ortalama, DÜŞÜK değişim katsayısı."""
    m = _musteriler()
    f = _faturalar(m)
    pat = TahsilatPatolojisi(kronik_gecikme_aktif=True, kronik_gecikme_musteri_orani=0.25)

    r = tahsilat_uret(f, m, seed=7, patoloji=pat)
    d = r.faturalar.merge(r.musteri_profili[["musteri_id", "patoloji"]], on="musteri_id")
    kronik = d[d["patoloji"] == "kronik_gecikme"]["gecikme_gun"]
    normal = d[d["patoloji"] == "normal"]["gecikme_gun"]

    assert kronik.mean() > normal.mean(), "kronik geciken daha geç ödemeli"
    assert kronik.std() / kronik.mean() < 0.5, "ama öngörülebilir olmalı (düşük değişim katsayısı)"


def test_duzensiz_odeyen_ongorulemez():
    """Orta ortalama, YÜKSEK değişim katsayısı — asıl riskli olan bu."""
    m = _musteriler()
    f = _faturalar(m)
    pat = TahsilatPatolojisi(duzensiz_odeme_aktif=True, duzensiz_odeme_musteri_orani=0.25)

    r = tahsilat_uret(f, m, seed=7, patoloji=pat)
    d = r.faturalar.merge(r.musteri_profili[["musteri_id", "patoloji"]], on="musteri_id")
    duzensiz = d[d["patoloji"] == "duzensiz_odeme"]["gecikme_gun"]
    normal = d[d["patoloji"] == "normal"]["gecikme_gun"]

    assert duzensiz.std() > normal.std() * 1.3, "oynaklık belirgin şekilde artmalı"


def test_kronik_ve_duzensiz_ayirt_edilebiliyor():
    """⭐ Kural motorunun XYZ sınıflandırması bu ayrıma dayanacak.

    Kronik geciken ortalamada DAHA KÖTÜ ama değişim katsayısında DAHA İYİ
    olmalı. İki eksen birbirinden bağımsız hareket etmezse XYZ sınıfı bilgi
    taşımaz.
    """
    m = _musteriler()
    f = _faturalar(m)
    pat = TahsilatPatolojisi(
        kronik_gecikme_aktif=True,
        kronik_gecikme_musteri_orani=0.2,
        duzensiz_odeme_aktif=True,
        duzensiz_odeme_musteri_orani=0.2,
    )

    r = tahsilat_uret(f, m, seed=11, patoloji=pat)
    d = r.faturalar.merge(r.musteri_profili[["musteri_id", "patoloji"]], on="musteri_id")
    g = d.groupby("patoloji")["gecikme_gun"].agg(["mean", "std"])
    dk = g["std"] / g["mean"]

    assert g.loc["kronik_gecikme", "mean"] > g.loc["duzensiz_odeme", "mean"]
    assert dk["kronik_gecikme"] < dk["duzensiz_odeme"], (
        "kronik geciken daha öngörülebilir olmalı — XYZ ayrımının dayanağı bu"
    )


# --- Segment davranışı --------------------------------------------------------


def test_segmentler_farkli_davraniyor():
    m = _musteriler()
    f = _faturalar(m)

    r = tahsilat_uret(f, m, seed=5)
    d = r.faturalar.merge(r.musteri_profili[["musteri_id", "segment"]], on="musteri_id")
    ort = d.groupby("segment")["gecikme_gun"].mean()

    assert ort["bireysel"] < ort["usta"] < ort["perakendeci"] < ort["santiye"], (
        f"segment sıralaması beklenen gibi değil: {ort.to_dict()}"
    )


# --- Fatura ataması -----------------------------------------------------------


def test_fatura_vadesi_musteri_vadesiyle_uyusuyor():
    """Vade yok sayılıp rastgele atansa, 45 gün vadeli fatura peşin çalışan
    bir müşteriye yazılırdı."""
    m = _musteriler()
    f = _faturalar(m)

    r = tahsilat_uret(f, m, seed=5)
    d = r.faturalar.merge(
        r.musteri_profili[["musteri_id", "odeme_vadesi_gun"]],
        on="musteri_id",
        suffixes=("", "_musteri"),
    )

    assert (d["odeme_vadesi_gun"] == d["odeme_vadesi_gun_musteri"]).all()


def test_her_fatura_bir_musteriye_atanmis():
    m = _musteriler()
    f = _faturalar(m)

    r = tahsilat_uret(f, m, seed=5)

    assert r.faturalar["musteri_id"].notna().all()
    assert set(r.faturalar["musteri_id"]).issubset(set(m["musteri_id"]))


# --- Batak --------------------------------------------------------------------


def test_batak_faturalar_odenmemis_gorunuyor():
    m = _musteriler()
    f = _faturalar(m)
    pat = TahsilatPatolojisi(batak_aktif=True, batak_musteri_orani=0.15)

    r = tahsilat_uret(f, m, seed=9, patoloji=pat)

    odenmemis = r.faturalar[~r.faturalar["odendi"]]
    assert len(odenmemis) > 0
    assert odenmemis["gercek_odeme_tarihi"].isna().all(), "ödenmemiş faturada tarih olmamalı"
    assert odenmemis["gecikme_gun"].isna().all()


def test_patoloji_kapaliyken_hepsi_odeniyor():
    m = _musteriler()
    f = _faturalar(m)

    r = tahsilat_uret(f, m, seed=5)

    assert r.faturalar["odendi"].all()
    assert (r.musteri_profili["patoloji"] == "normal").all()


# --- Açık alacak --------------------------------------------------------------


def test_acik_alacak_gelecegi_gormuyor():
    """⭐ Ölçüm tarihinde "yarın ödenecek" bilgisi kullanılamaz.

    Bu, geriye dönük testin geçerliliğinin temeli: bugüne bakarken yarının
    ödemesini bilmek, sistemin gerçekte sahip olmadığı bilgiyi kullanmak
    olurdu ve sonuçlar olduğundan iyi çıkardı.
    """
    m = _musteriler(20)
    f = _faturalar(m, gun=60, tohum=4)
    r = tahsilat_uret(f, m, seed=5)

    olcum = dt.date(2026, 2, 1)
    acik = acik_alacaklar(r.faturalar, olcum)

    ts = pd.Timestamp(olcum)
    assert (pd.to_datetime(acik["tarih"]) <= ts).all(), "kesilmemiş fatura açık olamaz"
    odeme = pd.to_datetime(acik["gercek_odeme_tarihi"])
    assert (odeme.isna() | (odeme > ts)).all(), "ölçüm tarihinde ödenmiş fatura açık sayılmamalı"


def test_acik_alacak_gecikmeyi_hesapliyor():
    m = _musteriler(20)
    f = _faturalar(m, gun=60, tohum=4)
    r = tahsilat_uret(f, m, seed=5)

    acik = acik_alacaklar(r.faturalar, dt.date(2026, 3, 1))

    assert "gecikme_gun_bugun" in acik.columns
    beklenen = (pd.Timestamp("2026-03-01") - pd.to_datetime(acik["odeme_tarihi"])).dt.days
    assert (acik["gecikme_gun_bugun"] == beklenen).all()


# --- Tekrarlanabilirlik -------------------------------------------------------


def test_ayni_seed_ayni_sonuc():
    m = _musteriler(50)
    f = _faturalar(m, gun=40)

    a = tahsilat_uret(f, m, seed=42)
    b = tahsilat_uret(f, m, seed=42)

    pd.testing.assert_frame_equal(a.faturalar, b.faturalar)


def test_farkli_seed_farkli_sonuc():
    m = _musteriler(50)
    f = _faturalar(m, gun=40)

    a = tahsilat_uret(f, m, seed=1)
    b = tahsilat_uret(f, m, seed=2)

    assert not a.faturalar["gecikme_gun"].equals(b.faturalar["gecikme_gun"])


def test_bos_fatura_tablosu_patlamiyor():
    m = _musteriler(5)
    bos = pd.DataFrame(columns=["tarih", "sku_id", "tutar_tl", "odeme_vadesi_gun", "odeme_tarihi"])

    r = tahsilat_uret(bos, m)

    assert r.faturalar.empty


@pytest.mark.parametrize("ay", [1, 2, 12])
def test_sezonluk_tikanma_belirtilen_aylarda_geciktiriyor(ay: int):
    m = _musteriler(60)
    f = _faturalar(m, gun=365, tohum=8)
    pat = TahsilatPatolojisi(sezonluk_tikanma_aktif=True, sezonluk_tikanma_aylar=(ay,))

    normal = tahsilat_uret(f, m, seed=5)
    tikanik = tahsilat_uret(f, m, seed=5, patoloji=pat)

    hedef = pd.to_datetime(f["odeme_tarihi"]).dt.month == ay
    assert (
        tikanik.faturalar.loc[hedef, "gecikme_gun"].mean()
        > normal.faturalar.loc[hedef, "gecikme_gun"].mean()
    )
