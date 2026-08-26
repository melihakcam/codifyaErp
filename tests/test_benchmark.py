"""Faz 5 benchmark (`training/eval/benchmark.py`) — yalnızca LLM'e ihtiyaç
duymayan saf mantık test ediliyor, aynı `test_llm_router.py`'nin
`router_taban.py`'yi ele alış biçimi gibi. Gerçek model çağrısı yapan
fonksiyonlar (`router_metrigi`, `uydurma_ve_akicilik_metrikleri`,
`gecelik_tarama_metrikleri`) elle/CI dışında çalıştırılır.

Sayı ayıklama/doğrulama mantığı burada tekrar test edilmiyor — bu betik
kendi regex'ini yazmak yerine `app/llm/guard.py::adayi_dogrula`'yı
(zaten `test_guard.py`'de test edilen production kodu) doğrudan kullanıyor.
"""

from __future__ import annotations

from training.eval.benchmark import SONUC_DOSYASI, MetrikSonucu, _demo_kararlari_ornekle, sonuc_yolu


def test_metrik_sonucu_satir_formatlanir():
    m = MetrikSonucu(ad="test metriği", deger=0.733, hedef=0.95, gecti=False)
    satir = m.satir()
    assert "KALDI" in satir
    assert "test metriği" in satir


def test_metrik_sonucu_gosterge_farkli_isaretlenir():
    m = MetrikSonucu(ad="gösterge", deger=3.5, hedef=4.0, gecti=False, sert_kapi=False)
    assert "GOSTERGE" in m.satir()


def test_demo_kararlari_ornekle_sayisi_olan_kararlar_doner():
    kararlar = _demo_kararlari_ornekle(5)
    assert 0 < len(kararlar) <= 5
    for aday in kararlar:
        # anlatilacak_sayi_var_mi filtresi: en az bir sifir-olmayan sayi olmali.
        assert any(v != 0 for v in aday.izinli_sayilar())


def test_kosular_birbirinin_sonucunu_ezmiyor():
    """⭐ `router_taban.py::sonuc_yolu`'nun düzelttiği hatanın aynısı buradaydı.

    Önceden her koşu `benchmark_sonuc.json`'a yazıyordu — taban model ve
    3. tur karşılaştırması yapılmak istendiğinde ilki sessizce kaybolurdu.
    """
    assert sonuc_yolu("taban") == SONUC_DOSYASI
    assert sonuc_yolu("taban-cizgi-egitim-oncesi") == SONUC_DOSYASI

    yollar = [sonuc_yolu(e) for e in ("lora-tur2", "lora-tur3", "lora-tur3-tekrar")]
    assert len(set(yollar)) == len(yollar)
    assert SONUC_DOSYASI not in yollar

    kotu = sonuc_yolu("../../etc/parola")
    assert kotu.parent == SONUC_DOSYASI.parent
