"""Eğitim verisi tutarlılık kontrolü (`training/eval/veri_tutarlilik_kontrolu.py`).

2. tur LoRA'nın kök nedenini yakalayan kontrol — testler o kök nedenin
kendisini örnekliyor: hedefte olup istemde olmayan sayı.
"""

from __future__ import annotations

import json

from training.eval.veri_tutarlilik_kontrolu import (
    Sonuc,
    dosyayi_kontrol_et,
    istemde_olmayan_sayilar,
    raporla,
)

ISTEM = (
    "VERILER:\n"
    "urun: Alcipan 12.5mm - Alcipan\n"
    "karar: stok.siparis\n"
    "gunluk ortalama talep (adet): 0,31\n"
    "eldeki stok (adet): 10\n"
    "birim maliyet (TL): 84,18\n"
    "\nGEREKCE:"
)


def test_istemdeki_sayilari_kullanan_cevap_temiz():
    cevap = "Gunluk 0,31 adet tuketim var, eldeki stok 10 adet, birim maliyet 84,18 TL."
    assert istemde_olmayan_sayilar(ISTEM, cevap) == []


def test_istemde_olmayan_sayi_yakalanir():
    # %15 iskonto istemde YOK -- 2. turun kok nedeni tam olarak buydu.
    cevap = "Eldeki 10 adet icin %15 iskonto onerilir."
    assert istemde_olmayan_sayilar(ISTEM, cevap) == [15.0]


def test_urun_adindaki_rakamlar_sayi_sayilmaz():
    """'Alcipan 12.5mm' icindeki 12.5 sahte pozitif uretmemeli."""
    cevap = "Alcipan 12.5mm - Alcipan icin eldeki stok 10 adet."
    assert istemde_olmayan_sayilar(ISTEM, cevap) == []


def test_yuvarlama_farki_uydurma_sayilmaz():
    """Istemde 84,18 varken cevapta 84,18 -- ayni sayi, tolerans icinde."""
    istem = ISTEM.replace("84,18", "84,1833")
    cevap = "Birim maliyet 84,18 TL."
    assert istemde_olmayan_sayilar(istem, cevap) == []


def test_temiz_dosya_gecer(tmp_path):
    yol = tmp_path / "temiz.jsonl"
    kayit = {"istem": ISTEM, "cevap": "Eldeki stok 10 adet, birim maliyet 84,18 TL."}
    yol.write_text(json.dumps(kayit, ensure_ascii=False) + "\n", encoding="utf-8")

    sonuc = dosyayi_kontrol_et(yol)
    assert sonuc.toplam == 1
    assert sonuc.uydurmali == 0
    assert sonuc.gecti is True


def test_kirli_dosya_kalir(tmp_path):
    yol = tmp_path / "kirli.jsonl"
    kayit = {"istem": ISTEM, "cevap": "Eldeki 10 adet icin %15 iskonto onerilir."}
    yol.write_text(
        "\n".join(json.dumps(kayit, ensure_ascii=False) for _ in range(4)) + "\n",
        encoding="utf-8",
    )

    sonuc = dosyayi_kontrol_et(yol)
    assert sonuc.toplam == 4
    assert sonuc.uydurmali == 4
    assert sonuc.gecti is False
    assert sonuc.fazla_degerler[15.0] == 4


def test_rapor_kaldi_durumunda_duzeltme_yolunu_soyler():
    sonuc = Sonuc(toplam=100, uydurmali=79)
    metin = raporla(sonuc)
    assert "KALDI" in metin
    assert "veri_hazirla" in metin
    # Yanlis yonlendirmeye karsi acik uyari: daha cok egitim cozum degil.
    assert "KOTULESTIRIR" in metin


def test_rapor_gecti_durumunda_uyari_basmaz():
    sonuc = Sonuc(toplam=100, uydurmali=2)
    metin = raporla(sonuc)
    assert "GECTI" in metin
    assert "KALDI" not in metin
