"""Geriye dönük test hattı (A4, `app/adapters/geriye_donuk.py`).

⚠️ Bu testler sistemin **iyi karar verdiğini** doğrulamıyor. Doğrulanan şey
hattın kendisi: geçmiş stok doğru kuruluyor mu, geleceğe bakılmıyor mu,
tükenme tespiti doğru mu. Sonucun ne çıktığı veriye bağlı ve ölçümün konusu.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from app.adapters.csv_erp import CsvBicimHatasi
from app.adapters.geriye_donuk import (
    geriye_donuk_ozet,
    geriye_donuk_test,
    hareket_akisini_oku,
    stok_gecmisini_kur,
)


def _veri_yaz(dizin: Path, gun_sayisi: int = 200, gunluk_satis: int = 5) -> Path:
    """Basit ama tutarlı bir dünya: her gün satış, 30 günde bir mal girişi."""
    baslangic = dt.date(2025, 1, 1)
    satirlar = ["tarih,sku_id,miktar,hareket_tipi"]
    stok = 100
    for g in range(gun_sayisi):
        tarih = baslangic + dt.timedelta(days=g)
        if g % 30 == 0 and g > 0:
            satirlar.append(f"{tarih},A1,150,giris")
            stok += 150
        satirlar.append(f"{tarih},A1,{gunluk_satis},cikis")
        stok -= gunluk_satis

    (dizin / "hareketler.csv").write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    (dizin / "urunler.csv").write_text(
        "sku_id,sku_adi,birim_maliyet_tl,satis_fiyati_tl,tedarikci_id,stok\n"
        f"A1,Tugla,10,15,T1,{stok}\n",
        encoding="utf-8",
    )
    return dizin


def test_giris_hareketi_yoksa_acik_hata(tmp_path: Path):
    """Sessizce yanlış sayı üretmektense hata vermek: geçmiş stok, giriş
    hareketleri olmadan kurulamaz."""
    (tmp_path / "hareketler.csv").write_text(
        "tarih,sku_id,miktar\n2025-01-01,A1,5\n", encoding="utf-8"
    )

    with pytest.raises(CsvBicimHatasi, match="hareket_tipi"):
        hareket_akisini_oku(tmp_path / "hareketler.csv")


def test_akis_giris_ve_cikisi_isaretliyor(tmp_path: Path):
    (tmp_path / "hareketler.csv").write_text(
        "tarih,sku_id,miktar,hareket_tipi\n"
        "2025-01-01,A1,10,giris\n"
        "2025-01-02,A1,4,cikis\n",
        encoding="utf-8",
    )
    akis = hareket_akisini_oku(tmp_path / "hareketler.csv")

    assert akis["net"].tolist() == [10.0, -4.0]
    # Talep yalnızca çıkıştan: mal kabulü talep değildir.
    assert akis["talep_miktari"].tolist() == [0.0, 4.0]


def test_stok_gecmisi_bugunku_bakiyeden_geriye_kuruluyor(tmp_path: Path):
    """stok(t) = stok(t+1) - net(t+1)."""
    (tmp_path / "hareketler.csv").write_text(
        "tarih,sku_id,miktar,hareket_tipi\n"
        "2025-01-01,A1,10,cikis\n"
        "2025-01-02,A1,50,giris\n"
        "2025-01-03,A1,20,cikis\n",
        encoding="utf-8",
    )
    akis = hareket_akisini_oku(tmp_path / "hareketler.csv")
    gecmis = stok_gecmisini_kur(akis, pd.Series({"A1": 100.0}), dt.date(2025, 1, 3))

    # Son gün 100. Bir önceki gün: 100 - (-20) = 120. Ondan önce: 120 - 50 = 70.
    assert gecmis.loc[pd.Timestamp("2025-01-03"), "A1"] == 100.0
    assert gecmis.loc[pd.Timestamp("2025-01-02"), "A1"] == 120.0
    assert gecmis.loc[pd.Timestamp("2025-01-01"), "A1"] == 70.0


def test_negatif_stok_gizlenmiyor(tmp_path: Path):
    """Kırpmak veri tutarsızlığını saklardı; çağıran görmeli."""
    (tmp_path / "hareketler.csv").write_text(
        "tarih,sku_id,miktar,hareket_tipi\n"
        "2025-01-01,A1,10,cikis\n"
        "2025-01-02,A1,500,giris\n",
        encoding="utf-8",
    )
    akis = hareket_akisini_oku(tmp_path / "hareketler.csv")
    gecmis = stok_gecmisini_kur(akis, pd.Series({"A1": 10.0}), dt.date(2025, 1, 2))

    assert gecmis.loc[pd.Timestamp("2025-01-01"), "A1"] < 0


def test_uctan_uca_kosuyor(tmp_path: Path):
    dizin = _veri_yaz(tmp_path)
    sonuc = geriye_donuk_test(dizin, adim_gun=30, isinma_gun=90)

    assert not sonuc.empty
    assert set(sonuc.columns) >= {
        "olcum_tarihi",
        "sku_id",
        "siparis_onerildi",
        "tukenme_yasandi",
        "yakaladi",
    }
    # Isınma payı: ilk ölçüm ilk hareketten en az 90 gün sonra.
    assert min(sonuc["olcum_tarihi"]) >= dt.date(2025, 4, 1)


def test_ozet_duyarlilik_hesapliyor(tmp_path: Path):
    sonuc = geriye_donuk_test(_veri_yaz(tmp_path), adim_gun=30, isinma_gun=90)
    ozet = geriye_donuk_ozet(sonuc)

    assert ozet["karar_sayisi"] == len(sonuc)
    assert 0.0 <= ozet["duyarlilik"] <= 1.0
    # Tükenme hiç yaşanmadıysa duyarlılık 0 döner — sıfıra bölme yok.
    assert ozet["tukenme_sayisi"] >= 0


def test_tukenmeyen_dunyada_kacirilan_yok(tmp_path: Path):
    """Bol stoklu dünyada tükenme yok → kaçırılan da yok.

    Ölçümün tabanı: sistem olmayan bir riski "kaçırdı" diye yazmamalı.
    """
    dizin = _veri_yaz(tmp_path, gunluk_satis=1)
    ozet = geriye_donuk_ozet(geriye_donuk_test(dizin, adim_gun=30, isinma_gun=90))

    assert ozet["tukenme_sayisi"] == 0
    assert ozet["kacirilan"] == 0
