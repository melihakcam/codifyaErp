"""A3.5 — train/val/test bölme testleri.

Sentetik, küçük veri setleriyle sınanıyor: gerçek 50.050 satırlık dosyaları
okumadan bölme mantığının (SKU sızıntısı yok, oranlar makul, deterministik)
doğruluğunu doğrular.
"""

from __future__ import annotations

from training.veri_bolme import (
    VARSAYILAN_ORANLAR,
    gerekce_veri_setini_bol,
    golden_set_adayi_olustur,
    router_veri_setini_bol,
    sku_bolmelerini_olustur,
)


def _sku_ids(n: int) -> list[str]:
    return [f"S-{i:05d}" for i in range(n)]


def test_sku_bolmeleri_tum_skulari_kapsar():
    sku_ids = _sku_ids(200)
    bolmeler = sku_bolmelerini_olustur(sku_ids)
    assert set(bolmeler.keys()) == set(sku_ids)
    assert set(bolmeler.values()) <= {"train", "val", "test"}


def test_sku_bolmeleri_deterministik():
    sku_ids = _sku_ids(200)
    b1 = sku_bolmelerini_olustur(sku_ids, seed=13)
    b2 = sku_bolmelerini_olustur(sku_ids, seed=13)
    assert b1 == b2


def test_sku_bolmeleri_farkli_seed_farkli_dagilim():
    sku_ids = _sku_ids(200)
    b1 = sku_bolmelerini_olustur(sku_ids, seed=13)
    b2 = sku_bolmelerini_olustur(sku_ids, seed=99)
    assert b1 != b2


def test_sku_bolme_oranlari_makul():
    sku_ids = _sku_ids(2000)
    bolmeler = sku_bolmelerini_olustur(sku_ids)
    n_train = sum(1 for v in bolmeler.values() if v == "train")
    n_val = sum(1 for v in bolmeler.values() if v == "val")
    n_test = sum(1 for v in bolmeler.values() if v == "test")
    assert 0.75 < n_train / 2000 < 0.85
    assert 0.05 < n_val / 2000 < 0.15
    assert 0.05 < n_test / 2000 < 0.15


def test_gerekce_bolme_sku_sizintisi_yok():
    sku_ids = _sku_ids(300)
    bolmeler = sku_bolmelerini_olustur(sku_ids)
    karar_noktalari = [
        {
            "sku_id": sku_id,
            "tarih": f"2026-0{gun}-01",
            "ozellikler": {"veri_gun_sayisi": 180},
        }
        for sku_id in sku_ids
        for gun in (1, 2, 3)
    ]
    gerekceler = [
        {"sku_id": k["sku_id"], "tarih": k["tarih"], "metin": "x", "guard_sonucu": "gecti"}
        for k in karar_noktalari
    ]
    bolunmus = gerekce_veri_setini_bol(karar_noktalari, gerekceler, bolmeler)

    sku_kumeleri = {b: {s["sku_id"] for s in satirlar} for b, satirlar in bolunmus.items()}
    assert not (sku_kumeleri["train"] & sku_kumeleri["val"])
    assert not (sku_kumeleri["train"] & sku_kumeleri["test"])
    assert not (sku_kumeleri["val"] & sku_kumeleri["test"])
    # Her SKU'nun 3 kaydı da aynı bölmede olmalı.
    toplam_satir = sum(len(v) for v in bolunmus.values())
    assert toplam_satir == len(karar_noktalari)


def test_gerekce_bolme_eslesmeyen_satiri_atlar():
    bolmeler = sku_bolmelerini_olustur(["S-00001"])
    karar_noktalari = [
        {"sku_id": "S-00001", "tarih": "2026-01-01", "ozellikler": {"veri_gun_sayisi": 180}}
    ]
    bolunmus = gerekce_veri_setini_bol(karar_noktalari, gerekceler=[], sku_bolmeleri=bolmeler)
    toplam = sum(len(v) for v in bolunmus.values())
    assert toplam == 0


def test_router_bolme_sku_baglantili_satir_sku_bolmesini_takip_eder():
    bolmeler = {"S-00001": "test"}
    router_satirlari = [
        {
            "soru": "X ürünü için sipariş önerisi",
            "arac": "siparis_onerisi_sorgula",
            "parametreler": {"sku_adi": "S-00001"},
        },
    ]
    bolunmus = router_veri_setini_bol(router_satirlari, bolmeler)
    assert bolunmus["test"] == router_satirlari
    assert bolunmus["train"] == []
    assert bolunmus["val"] == []


def test_router_bolme_tekrar_eden_soru_bir_kez_sayilir():
    bolmeler: dict[str, str] = {}
    router_satirlari = [
        {"soru": "Kritik stok var mı?", "arac": "kritik_stok_sorgula", "parametreler": {}},
        {"soru": "Kritik stok var mı?", "arac": "kritik_stok_sorgula", "parametreler": {}},
    ]
    bolunmus = router_veri_setini_bol(router_satirlari, bolmeler)
    toplam = sum(len(v) for v in bolunmus.values())
    assert toplam == 1


def test_router_bolme_kategori_gibi_kucuk_evren_tum_bolmelere_dagilir():
    """8 kategori × çok sayıda şablon varyantı — tümü aynı bölmeye hapsolmamalı."""
    bolmeler: dict[str, str] = {}
    router_satirlari = [
        {
            "soru": f"{kategori} kategorisinde varyant {i}",
            "arac": "kritik_stok_sorgula",
            "parametreler": {"kategori": kategori},
        }
        for kategori in ("cimento", "demir", "tugla", "alci")
        for i in range(20)
    ]
    bolunmus = router_veri_setini_bol(router_satirlari, bolmeler)
    assert len(bolunmus["train"]) > 0
    assert len(bolunmus["val"]) > 0 or len(bolunmus["test"]) > 0


def test_golden_set_hedef_boyutu_asmaz():
    gerekce_test = [
        {
            "sku_id": f"S-{i:05d}",
            "guard_sonucu": "gecti" if i % 5 else "sablona_dustu",
            "ozellikler": {"veri_gun_sayisi": 10 if i % 3 == 0 else 180},
        }
        for i in range(100)
    ]
    router_test = [{"soru": f"soru {i}", "arac": "x", "parametreler": {}} for i in range(100)]
    aday = golden_set_adayi_olustur(gerekce_test, router_test, hedef=50)
    assert len(aday) <= 50
    assert all(s["kaynak"] in ("gerekce", "router") for s in aday)


def test_varsayilan_oranlar_toplami_bir():
    assert abs(sum(VARSAYILAN_ORANLAR.values()) - 1.0) < 1e-9
