"""Golden set ortak incelemesinde bulundu: paraphrase edilmiş şablonlar,
yer tutucu sonekini ("tedarikçisinin"/"kategorisinde") bazen kendi içinde
de tekrar ediyordu; token değişimiyle birleşince bitişik tekrar oluşuyordu
("T-0005 tedarikçisinin tedarikçinin gecikiyomu var mı?"). Golden set'in
%30,6'sında (49/160), `tedarikci_performansi_sorgula`'da %60,3'ünde vardı.
"""

from __future__ import annotations

from training.build_dataset import yer_tutucu_tekrarini_temizle


def test_tedarikci_bitisik_tekrari_temizlenir():
    kirli = "T-0005 tedarikçisinin tedarikçinin gecikiyomu var mı?"
    beklenen = "T-0005 tedarikçisinin gecikiyomu var mı?"
    assert yer_tutucu_tekrarini_temizle(kirli, "tedarikci_id") == beklenen


def test_kategori_bitisik_tekrari_temizlenir():
    kirli = "çimento kategorisinde kategorisinde acil sipariş gerekliliği var mı?"
    temiz = yer_tutucu_tekrarini_temizle(kirli, "kategori")
    assert temiz == "çimento kategorisinde acil sipariş gerekliliği var mı?"


def test_tekrarsiz_cumleye_dokunmaz():
    temiz_cumle = "T-0005 tedarikçisinin performansı hakkında bilgi verir misiniz?"
    assert yer_tutucu_tekrarini_temizle(temiz_cumle, "tedarikci_id") == temiz_cumle


def test_uzak_dogal_tekrara_dokunmaz():
    """Bitişik olmayan, gerçek bir ikinci bahsi silmemeli."""
    cumle = "T-0005 tedarikçisinin performansı düşükse, bu tedarikçiyle devam edelim mi?"
    assert yer_tutucu_tekrarini_temizle(cumle, "tedarikci_id") == cumle


def test_diger_varlik_turlerine_dokunmaz():
    cumle = "S-01432 için sipariş verilmeli mi?"
    assert yer_tutucu_tekrarini_temizle(cumle, "sku_id") == cumle
    assert yer_tutucu_tekrarini_temizle(cumle, "yok") == cumle
