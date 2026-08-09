"""Gerçek ERP CSV'lerini okuyan adaptörün testleri.

Bu adaptör, sistemi ilk kez simülatör dışı bir veriyle besliyor. Testler
sahte ama **gerçekçi** CSV'ler üretiyor: eksik kolon adları, hareket görmemiş
ürünler, tek siparişi olan tedarikçi, boş günler.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from app.adapters.csv_erp import (
    ASGARI_SIPARIS_SAYISI,
    VARSAYILAN_TEDARIK_SURESI_GUN,
    CsvBicimHatasi,
    hareketleri_oku,
    ozellikleri_uret,
    siparislerden_tedarikci_tablosu,
    urunleri_oku,
)


def _urunler_yaz(dizin, kolonlar: dict | None = None) -> None:
    varsayilan = {
        "sku_id": ["S-1", "S-2", "S-3"],
        "sku_adi": ["Çimento", "Tuğla", "Hiç Satılmayan"],
        "kategori": ["çimento", "tuğla", "hırdavat"],
        "birim_maliyet_tl": [100.0, 5.0, 50.0],
        "satis_fiyati_tl": [130.0, 7.0, 65.0],
        "tedarikci_id": ["T-1", "T-1", "T-2"],
        "eldeki_stok": [500, 2000, 10],
    }
    pd.DataFrame(kolonlar or varsayilan).to_csv(dizin / "urunler.csv", index=False)


def _hareketler_yaz(dizin) -> None:
    satirlar = []
    baslangic = dt.date(2026, 1, 1)
    for gun in range(120):
        tarih = baslangic + dt.timedelta(days=gun)
        # S-1 her gün satılıyor, S-2 haftada bir, S-3 hiç.
        satirlar.append({"tarih": tarih, "sku_id": "S-1", "miktar": 10})
        if gun % 7 == 0:
            satirlar.append({"tarih": tarih, "sku_id": "S-2", "miktar": 100})
    pd.DataFrame(satirlar).to_csv(dizin / "hareketler.csv", index=False)


def _siparisler_yaz(dizin) -> None:
    satirlar = []
    for i in range(6):  # T-1: 6 sipariş, sapması hesaplanabilir
        satirlar.append(
            {
                "tedarikci_id": "T-1",
                "siparis_tarihi": dt.date(2026, 1, 1) + dt.timedelta(days=i * 15),
                "teslim_tarihi": dt.date(2026, 1, 1) + dt.timedelta(days=i * 15 + 5 + i % 3),
            }
        )
    satirlar.append(  # T-2: tek sipariş — sapma güvenilmez
        {
            "tedarikci_id": "T-2",
            "siparis_tarihi": dt.date(2026, 2, 1),
            "teslim_tarihi": dt.date(2026, 2, 10),
        }
    )
    pd.DataFrame(satirlar).to_csv(dizin / "siparisler.csv", index=False)


@pytest.fixture
def veri_dizini(tmp_path):
    _urunler_yaz(tmp_path)
    _hareketler_yaz(tmp_path)
    _siparisler_yaz(tmp_path)
    return tmp_path


# --- Kolon eşleme -------------------------------------------------------------


def test_farkli_kolon_adlari_taniniyor(tmp_path):
    """Müşteri 'stok_kodu' yazar, biz 'sku_id' bekleriz. İkisi de çalışmalı."""
    pd.DataFrame(
        {
            "Stok Kodu": ["S-1"],
            "Ürün Adı": ["Çimento"],
            "Alış Fiyatı": [100.0],
            "Satış Fiyatı": [130.0],
            "Cari Kod": ["T-1"],
        }
    ).to_csv(tmp_path / "urunler.csv", index=False)

    df = urunleri_oku(tmp_path / "urunler.csv")

    assert df.loc[0, "sku_id"] == "S-1"
    assert df.loc[0, "tedarikci_id"] == "T-1"
    assert df.loc[0, "birim_maliyet_tl"] == 100.0


def test_eksik_kolon_anlasilir_hata_veriyor(tmp_path):
    """Bu dosyaları hazırlayan çoğu zaman geliştirici değil."""
    pd.DataFrame({"sku_id": ["S-1"]}).to_csv(tmp_path / "urunler.csv", index=False)

    with pytest.raises(CsvBicimHatasi) as hata:
        urunleri_oku(tmp_path / "urunler.csv")

    mesaj = str(hata.value)
    assert "sku_adi" in mesaj
    assert "Kabul edilen adlar" in mesaj, "hangi adların kabul edildiği yazmalı"


# --- Talep hesabı -------------------------------------------------------------


def test_hareketsiz_gunler_sifirla_dolduruluyor(veri_dizini):
    """⭐ En kolay yapılacak hata bu.

    Yalnızca satış olan günler sayılırsa, haftada bir satılan bir ürün
    'günde 100 adet' gibi görünür ve sistem sürekli sipariş verir.
    """
    talep = hareketleri_oku(veri_dizini / "hareketler.csv")

    s2 = talep[talep["sku_id"] == "S-2"]
    assert len(s2) == 120, "her gün için satır olmalı, yalnızca satış günleri değil"
    assert (s2["talep_miktari"] == 0).sum() > 100, "satış olmayan günler 0 olmalı"


def test_gunluk_ortalama_gercekci(veri_dizini):
    ozellikler = ozellikleri_uret(veri_dizini)
    sozluk = {o.sku_id: o for o in ozellikler}

    # S-1: her gün 10 adet
    assert 9.0 < sozluk["S-1"].ort_gunluk_talep < 11.0
    # S-2: haftada bir 100 adet ≈ günde 14
    assert 10.0 < sozluk["S-2"].ort_gunluk_talep < 18.0


def test_hic_hareketi_olmayan_urun_disarida(veri_dizini):
    """Hiç satılmamış ürün için 'günlük ortalama talep' anlamsız."""
    ozellikler = ozellikleri_uret(veri_dizini)

    assert "S-3" not in {o.sku_id for o in ozellikler}
    assert len(ozellikler) == 2


# --- Tedarikçi ----------------------------------------------------------------


def test_tedarik_suresi_siparislerden_hesaplaniyor(veri_dizini):
    urunler = urunleri_oku(veri_dizini / "urunler.csv")

    df = siparislerden_tedarikci_tablosu(veri_dizini / "siparisler.csv", urunler)
    t1 = df[df["tedarikci_id"] == "T-1"].iloc[0]

    assert 5.0 <= t1["ort_tedarik_suresi_gun"] <= 7.0
    assert t1["tedarik_suresi_std_gun"] > 0, "6 siparişten sapma hesaplanabilmeli"
    assert 0.0 <= t1["guvenilirlik"] <= 1.0


def test_tek_siparisli_tedarikcide_sapma_sifir_kalmiyor(veri_dizini):
    """⚠️ Tek gözlemden sapma 0 çıkar — bu, riski YOK saymak olur.

    Emniyet stoğu doğrudan tedarik süresi belirsizliğinden hesaplanıyor;
    sıfır sapma o ürünü korumasız bırakırdı.
    """
    urunler = urunleri_oku(veri_dizini / "urunler.csv")

    df = siparislerden_tedarikci_tablosu(veri_dizini / "siparisler.csv", urunler)
    t2 = df[df["tedarikci_id"] == "T-2"].iloc[0]

    assert t2["tedarik_suresi_std_gun"] > 0, (
        f"tek siparişli tedarikçide katalog sapması kullanılmalı "
        f"(ASGARI_SIPARIS_SAYISI={ASGARI_SIPARIS_SAYISI})"
    )


def test_siparis_dosyasi_yoksa_varsayilana_dusuyor(veri_dizini):
    urunler = urunleri_oku(veri_dizini / "urunler.csv")

    df = siparislerden_tedarikci_tablosu(veri_dizini / "yok.csv", urunler)

    assert (df["ort_tedarik_suresi_gun"] == VARSAYILAN_TEDARIK_SURESI_GUN).all()


# --- Uçtan uca ----------------------------------------------------------------


def test_ozellikler_sozlesmeye_uyuyor(veri_dizini):
    """Çıktı doğrudan karar motoruna verilebilmeli."""
    from app.domain.stock.decide import ozellikten_karar_uret

    ozellikler = ozellikleri_uret(veri_dizini)

    assert ozellikler
    for o in ozellikler:
        assert o.ort_gunluk_talep >= 0
        assert o.tedarik_suresi_gun > 0
        assert o.birim_maliyet_tl > 0
        assert o.olcum_tarihi == dt.date(2026, 4, 30)

    # Ve gerçekten karar üretilebiliyor mu — adaptörün asıl vaadi bu.
    karar = ozellikten_karar_uret(ozellikler[0])
    assert karar.tip is not None
    assert karar.izinli_sayilar()


def test_yoldaki_stok_sifir_varsayiliyor(veri_dizini):
    """Güvenli taraf: olmayan malı var sanmaktansa fazladan sipariş öner."""
    ozellikler = ozellikleri_uret(veri_dizini)

    assert all(o.yoldaki_stok == 0 for o in ozellikler)
