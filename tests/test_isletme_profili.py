"""İşletme profili (Faz 9, `app/core/isletme_profili.py`).

Bu dosyanın sorduğu soru: **bir müşteriye özel sayı, kod dağıtmadan
değiştirilebiliyor mu?**
"""

from __future__ import annotations

import json

import pytest

from app.core.isletme_profili import FinansProfili, IsletmeProfili, StokProfili


def test_varsayilanlar_mevcut_davranisi_koruyor():
    """⚠️ Profil eklemek tek başına HİÇBİR sayıyı oynatmamalı.

    Varsayılanlar bugüne kadarki modül sabitlerinin birebir aynısı. Bu test
    kırılırsa, refaktör sırasında bir eşik sessizce kaymış demektir — ve o
    kayma ancak aylar sonra tuhaf bir karar olarak görünürdü.
    """
    p = IsletmeProfili()

    assert p.stok.olu_stok_mutlak_esik_gun == 90
    assert p.stok.olu_stok_goreceli_carpan == 6.0
    assert p.stok.olu_stok_asgari_stok_gun == 1.0
    assert p.stok.tedarikci_degisim_asgari_siparis == 5

    assert p.finans.karsilik_mutlak_esik_gun == 180
    assert p.finans.karsilik_taban_esik_gun == 90
    assert p.finans.limit_kolu_aktif is True
    assert p.finans.limit_dusurme_skor_esigi == 45.0
    assert p.finans.maks_limit_kesinti_orani == 0.5


def test_maddi_esik_turetiliyor_secilmiyor():
    """Eşik iki iş girdisinden çıkıyor; profilde ayrı bir alan DEĞİL."""
    p = FinansProfili()
    assert p.takip_eylem_maliyeti_tl == 150.0
    assert 4_000 < p.maddi_takip_esigi_tl < 4_100

    # Personel ucuzsa eşik kendiliğinden düşer.
    ucuz = FinansProfili(personel_saatlik_maliyet_tl=150.0)
    assert ucuz.maddi_takip_esigi_tl < p.maddi_takip_esigi_tl


def test_gecersiz_deger_yuklemede_patliyor():
    """⚠️ Sessiz kabul yok. `hedef_servis_seviyesi` 1,2 yazılırsa
    `norm.ppf` sonsuz döndürür ve emniyet stoğu patlar — hata aylar sonra,
    tuhaf bir sipariş miktarı olarak görünürdü."""
    with pytest.raises(ValueError):
        StokProfili(yillik_elde_tutma_orani=1.5)
    with pytest.raises(ValueError):
        FinansProfili(maks_limit_kesinti_orani=2.0)
    with pytest.raises(ValueError):
        FinansProfili(limit_dusurme_skor_esigi=150.0)


def test_yazim_hatasi_sessizce_gecmiyor(tmp_path):
    """Fazla alan hata vermeli.

    `karsilik_esigi` diye yazıp `karsilik_taban_esik_gun` demeyi unutan bir
    kurulum, sessizce varsayılanla çalışır ve kimse fark etmezdi.
    """
    yol = tmp_path / "profil.json"
    yol.write_text(json.dumps({"finans": {"karsilik_esigi": 45}}), encoding="utf-8")

    with pytest.raises(ValueError):
        IsletmeProfili.dosyadan(yol)


def test_dosyadan_yuklenip_kurala_gecebiliyor(tmp_path):
    """⭐ Asıl iddia: müşteri sayısı kod dağıtmadan değişiyor."""
    import datetime as dt

    from app.contracts import ABCSinifi, FinansOzellikleri, XYZSinifi
    from app.domain.finance.rules import karsilik_degerlendir

    ozellik = FinansOzellikleri(
        musteri_id="M-1",
        musteri_adi="Test",
        segment="usta",
        toplam_alacak_tl=10_000.0,
        vadesi_gecen_tl=10_000.0,
        en_eski_gecikme_gun=100,
        ort_odeme_gecikmesi_gun=5.0,
        odeme_gecikmesi_std=2.0,
        veri_gun_sayisi=400,
        kredi_limiti_tl=20_000.0,
        abc_sinifi=ABCSinifi.B,
        xyz_sinifi=XYZSinifi.X,
        hedef_tahsilat_orani=0.95,
        son_odeme_gun_once=30,
        tahsilat_orani=0.9,
        musteri_kredi_onayli=True,
        olcum_tarihi=dt.date(2026, 8, 10),
    )

    # Varsayılan profil: taban 90 gün → 100 günlük gecikme karşılık gerektirir.
    assert karsilik_degerlendir(ozellik)["karsilik_gerekli"] is True

    # Muhafazakâr müşteri: taban 180 güne çekilmiş → aynı alacak için karşılık yok.
    yol = tmp_path / "muhafazakar.json"
    IsletmeProfili(
        ad="muhafazakar",
        finans=FinansProfili(karsilik_taban_esik_gun=180),
    ).dosyaya_yaz(yol)

    yeni = IsletmeProfili.dosyadan(yol)
    assert karsilik_degerlendir(ozellik, yeni.finans)["karsilik_gerekli"] is False


def test_limit_kolu_profilden_kapatilabiliyor():
    """§14'ün kararı artık müşteri başına verilebiliyor."""
    import datetime as dt

    from app.contracts import ABCSinifi, FinansOzellikleri, XYZSinifi
    from app.domain.finance.rules import limit_degerlendir

    riskli = FinansOzellikleri(
        musteri_id="M-2",
        musteri_adi="Riskli",
        segment="santiye",
        toplam_alacak_tl=100_000.0,
        vadesi_gecen_tl=50_000.0,
        en_eski_gecikme_gun=60,
        ort_odeme_gecikmesi_gun=20.0,
        odeme_gecikmesi_std=45.0,
        veri_gun_sayisi=500,
        kredi_limiti_tl=200_000.0,
        abc_sinifi=ABCSinifi.A,
        xyz_sinifi=XYZSinifi.Z,
        hedef_tahsilat_orani=0.95,
        son_odeme_gun_once=40,
        tahsilat_orani=0.30,
        musteri_kredi_onayli=True,
        olcum_tarihi=dt.date(2026, 8, 10),
    )

    assert limit_degerlendir(riskli)["limit_dusurulmeli"] is True
    kapali = FinansProfili(limit_kolu_aktif=False)
    assert limit_degerlendir(riskli, kapali)["limit_dusurulmeli"] is False


# ---------------------------------------------------------------------------
# Stok tarafı
# ---------------------------------------------------------------------------


def _stok_ozelligi(**degisiklikler):
    import datetime as dt

    from app.contracts import ABCSinifi, StockFeatures, XYZSinifi

    varsayilan = {
        "sku_id": "SKU-1",
        "sku_adi": "Test Ürünü",
        "kategori": "genel",
        "eldeki_stok": 400,
        "rezerve_stok": 0,
        "yoldaki_stok": 0,
        "ort_gunluk_talep": 0.5,
        "talep_std": 0.2,
        "veri_gun_sayisi": 365,
        "tedarik_suresi_gun": 7.0,
        "tedarik_suresi_std": 2.0,
        "abc_sinifi": ABCSinifi.B,
        "xyz_sinifi": XYZSinifi.Y,
        "hedef_servis_seviyesi": 0.95,
        "son_hareket_gun_once": 100,
        "raf_omru_kalan_gun": None,
        "birim_maliyet_tl": 10.0,
        "satis_fiyati_tl": 15.0,
        "tedarikci_id": "T-1",
        "tedarikci_adi": "Test Tedarikçi",
        "tedarikci_skoru": 80.0,
        "tedarikci_zamaninda_teslim_orani": 0.9,
        "tedarikci_onayli": True,
        "tedarikci_siparis_sayisi": 20,
        "moq": 1,
        "paket_adedi": 1,
        "olcum_tarihi": dt.date(2026, 8, 10),
    }
    return StockFeatures(**{**varsayilan, **degisiklikler})


def test_olu_stok_esigi_profilden_geliyor():
    """⭐ Nalburun sabrı toptancınınkinden uzun — artık ayarlanabiliyor.

    100 gündür hareketsiz bir ürün varsayılan profilde (90 gün) ölü; nalbur
    profilinde (120 gün) değil.
    """
    from app.domain.stock.rules import olu_stok_degerlendir

    urun = _stok_ozelligi(son_hareket_gun_once=100)

    assert olu_stok_degerlendir(urun)["olu_stok_mu"] is True

    sabirli = StokProfili(olu_stok_mutlak_esik_gun=120)
    assert olu_stok_degerlendir(urun, sabirli)["olu_stok_mu"] is False


def test_tedarikci_kaniti_profilden_geliyor():
    """Kaç sipariş sonra tedarikçi hakkında hüküm verilir — müşteri kararı."""
    from app.domain.stock.rules import tedarikci_degisim_degerlendir

    az_siparisli = _stok_ozelligi(tedarikci_skoru=30.0, tedarikci_siparis_sayisi=8)

    # Varsayılan kapı 5 sipariş → 8 yeterli.
    assert tedarikci_degisim_degerlendir(az_siparisli)["gozden_gecirilmeli"] is True

    # Temkinli müşteri 15 sipariş istiyor → 8 yetmiyor.
    temkinli = StokProfili(tedarikci_degisim_asgari_siparis=15)
    assert tedarikci_degisim_degerlendir(az_siparisli, temkinli)["gozden_gecirilmeli"] is False


def test_ornek_profiller_yuklenebiliyor():
    """Depodaki üç örnek profil geçerli olmalı — bozuksa kurulum başarısız."""
    from pathlib import Path

    from app.core.isletme_profili import PROJE_KOKU

    for ad in ("varsayilan", "nalbur", "toptanci"):
        yol = Path(PROJE_KOKU) / "profiller" / f"{ad}.json"
        assert yol.exists(), f"{ad}.json yok"
        p = IsletmeProfili.dosyadan(yol)
        assert p.ad == ad

    # Nalburda limit kolu kapalı olmalı (§14'ün kararı müşteri bazında).
    nalbur = IsletmeProfili.dosyadan(Path(PROJE_KOKU) / "profiller" / "nalbur.json")
    assert nalbur.finans.limit_kolu_aktif is False
