"""A3.4 gerekçe etiketleme testleri.

Ollama'ya gerçek ağ çağrısı yapmıyor — yalnızca sayı doğrulama (yerel guard
eşleniği), şekil/slot çıkarımı ve şablon doldurma mantığını sınar. Bunlar
büyük LLM'in ürettiği metnin kabul/red kararını veren asıl kritik kod.
"""

from __future__ import annotations

from app.contracts import GuardSonucu, KararTipi
from training.label_rationale import (
    _metni_dogrula,
    _sablonu_doldur,
    _sayilari_cikar,
    _sekil_anahtari,
    _sekil_id_oku,
    _sekil_id_yaz,
    _slotlari_cikar,
    _varyantlari_ayikla,
    gerekceleri_uret,
    sekil_promptlarini_ihrac_et,
)


def _ozellikler(**degisiklikler) -> dict:
    taban = {
        "sku_id": "S-00001",
        "sku_adi": "Kırmızı Tuğla",
        "kategori": "Kaba Yapı Malzemesi",
        "eldeki_stok": 310,
        "rezerve_stok": 40,
        "yoldaki_stok": 0,
        "ort_gunluk_talep": 42.0,
        "talep_std": 11.5,
        "veri_gun_sayisi": 180,
        "tedarik_suresi_gun": 12.0,
        "tedarik_suresi_std": 2.5,
        "abc_sinifi": "A",
        "xyz_sinifi": "Y",
        "hedef_servis_seviyesi": 0.95,
        "son_hareket_gun_once": 1,
        "raf_omru_kalan_gun": None,
        "birim_maliyet_tl": 4.75,
        "satis_fiyati_tl": 6.90,
        "tedarikci_id": "T-014",
        "tedarikci_adi": "Yılmaz Yapı",
        "tedarikci_skoru": 87.0,
        "tedarikci_zamaninda_teslim_orani": 0.94,
        "tedarikci_onayli": True,
        "moq": 500,
        "paket_adedi": 100,
        "olcum_tarihi": "2026-07-30",
    }
    taban.update(degisiklikler)
    return taban


def _siparis_satiri() -> dict:
    ozellikler = _ozellikler()
    kurallar = [
        {"kod": "EMNIYET_STOGU_HESAPLANDI", "aciklama": "x", "degerler": {"emniyet_stogu": 111.0}},
        {"kod": "ROP_HESAPLANDI", "aciklama": "x", "degerler": {"rop": 615.0}},
        {"kod": "ROP_ALTINDA", "aciklama": "x", "degerler": {"rop": 615.0}},
        {
            "kod": "SIPARIS_MIKTARI_HESAPLANDI",
            "aciklama": "x",
            "degerler": {"siparis_miktari": 1200.0},
        },
        {
            "kod": "TEDARIKCI_DEGERLENDIRILDI",
            "aciklama": "x",
            "degerler": {"tedarikci_skoru": 87.0},
        },
    ]
    aksiyon = {"siparis_miktari": 1200, "tedarikci_id": "T-014"}
    izinli = set()
    for k in kurallar:
        izinli.update(k["degerler"].values())
    for v in ozellikler.values():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            izinli.add(float(v))
    for v in aksiyon.values():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            izinli.add(float(v))
    izinli.add(1200 * 4.75)
    izinli.add(270.0)  # kullanilabilir_stok = 310 - 40
    izinli.add(95.0)  # hedef_servis_seviyesi * 100

    return {
        "sku_id": "S-00001",
        "tarih": "2026-07-30",
        "ozellikler": ozellikler,
        "karar_tipi": KararTipi.STOK_SIPARIS.value,
        "aksiyon": aksiyon,
        "tahmini_tutar_tl": 1200 * 4.75,
        "guven": 0.88,
        "tetiklenen_kurallar": kurallar,
        "izinli_sayilar": sorted(izinli),
    }


# --- Sayı çıkarma / doğrulama --------------------------------------------------


def test_turkce_bicimli_sayilar_dogru_ayristirilir():
    assert _sayilari_cikar("1.200 adet, %94,5 oran") == [1200.0, 94.5]


def test_izinli_sayi_iceren_metin_gecer():
    satir = _siparis_satiri()
    metin = "Kırmızı Tuğla için 1.200 adet sipariş öneriliyor."
    gecti, reddedilenler = _metni_dogrula(metin, satir)
    assert gecti
    assert reddedilenler == []


def test_uydurma_sayi_reddedilir():
    satir = _siparis_satiri()
    metin = "Kırmızı Tuğla için 3 gün içinde 999 adet sipariş öneriliyor."
    gecti, reddedilenler = _metni_dogrula(metin, satir)
    assert not gecti
    assert 999.0 in reddedilenler


def test_urun_adindaki_rakam_sayi_sanilmaz():
    """sku_adi/tedarikci_adi içindeki rakamlar (ör. kod) yanlışlıkla reddedilmemeli."""
    satir = _siparis_satiri()
    satir["ozellikler"]["sku_adi"] = "Tuğla 19x9x5"
    metin = "Tuğla 19x9x5 için 1.200 adet sipariş öneriliyor."
    gecti, _ = _metni_dogrula(metin, satir)
    assert gecti


# --- Şekil + slot çıkarımı ------------------------------------------------------


def test_sekil_anahtari_kural_kodlarina_gore_gruplar():
    satir = _siparis_satiri()
    karar_tipi, kodlar = _sekil_anahtari(satir)
    assert karar_tipi == KararTipi.STOK_SIPARIS.value
    assert kodlar == tuple(sorted(k["kod"] for k in satir["tetiklenen_kurallar"]))


def test_siparis_slotlari_dogru_hesaplanir():
    satir = _siparis_satiri()
    slotlar = _slotlari_cikar(satir)
    assert slotlar is not None
    assert slotlar["SIPARIS_MIKTARI"] == 1200
    assert slotlar["KULLANILABILIR_STOK"] == 270.0
    assert slotlar["TEDARIKCI_ADI"] == "Yılmaz Yapı"


def test_bilinmeyen_karar_tipi_none_doner():
    satir = _siparis_satiri()
    satir["karar_tipi"] = "stok.tedarikci_degisim"
    assert _slotlari_cikar(satir) is None


# --- Şablon doldurma round-trip -------------------------------------------------


def test_dolu_sablon_guard_tan_gecer():
    satir = _siparis_satiri()
    slotlar = _slotlari_cikar(satir)
    varyant = (
        "{SKU_ADI} için günlük {ORT_GUNLUK_TALEP} adet tüketim var, tedarik süresi "
        "{TEDARIK_SURESI_GUN} gün. Kullanılabilir stok {KULLANILABILIR_STOK}. "
        "{SIPARIS_MIKTARI} adet {TEDARIKCI_ADI} tedarikçisinden sipariş öneriliyor "
        "(skor {TEDARIKCI_SKORU})."
    )
    dolu = _sablonu_doldur(varyant, slotlar)  # type: ignore[arg-type]
    gecti, reddedilenler = _metni_dogrula(dolu, satir)
    assert gecti, reddedilenler


# --- Uçtan uca akış (LLM çağrısı olmadan, varyant havuzu boş) -------------------


def test_llm_erisilemezse_sablona_duser():
    """Ollama'ya erişilemediğinde (test ortamında ağ yok) güvenli geri dönüş şablon olmalı."""
    satir = _siparis_satiri()
    sonuclar = gerekceleri_uret([satir], ollama_url="http://127.0.0.1:1")
    assert len(sonuclar) == 1
    assert sonuclar[0]["guard_sonucu"] == GuardSonucu.SABLONA_DUSTU.value
    assert sonuclar[0]["metin"]


# --- Colab yolu: şekil ihracı + önceden üretilmiş varyant içe aktarımı --------


def test_sekil_id_roundtrip():
    sekil = (KararTipi.STOK_SIPARIS.value, ("ROP_ALTINDA", "SIPARIS_MIKTARI_HESAPLANDI"))
    assert _sekil_id_oku(_sekil_id_yaz(sekil)) == sekil


def test_sekil_promptlari_ihrac_edilir():
    satirlar = [_siparis_satiri()]
    promptlar = sekil_promptlarini_ihrac_et(satirlar)
    assert len(promptlar) == 1
    assert promptlar[0]["karar_tipi"] == KararTipi.STOK_SIPARIS.value
    assert "SIPARIS_MIKTARI" in promptlar[0]["slot_tokenlari"]
    assert "{SIPARIS_MIKTARI}" in promptlar[0]["prompt"]


def test_onceden_uretilmis_varyant_ollama_i_atlar():
    """Colab'dan gelmiş gibi bir varyant havuzu verildiğinde Ollama'ya hiç gidilmemeli."""
    satir = _siparis_satiri()
    sekil = _sekil_anahtari(satir)
    slotlar = _slotlari_cikar(satir)
    varyant = (
        "{SKU_ADI} için günlük {ORT_GUNLUK_TALEP} adet tüketim var, tedarik süresi "
        "{TEDARIK_SURESI_GUN} gün. Kullanılabilir stok {KULLANILABILIR_STOK}. "
        "{SIPARIS_MIKTARI} adet {TEDARIKCI_ADI} tedarikçisinden sipariş öneriliyor "
        "(skor {TEDARIKCI_SKORU})."
    )
    assert _varyantlari_ayikla(varyant, list(slotlar.keys())) == [varyant]  # type: ignore[union-attr]

    sonuclar = gerekceleri_uret(
        [satir],
        ollama_url="http://127.0.0.1:1",  # ulaşılamaz — havuzda olduğu için hiç denenmemeli
        onceden_uretilmis_varyantlar={sekil: [varyant]},
    )
    assert sonuclar[0]["guard_sonucu"] == GuardSonucu.GECTI.value
    assert "{" not in sonuclar[0]["metin"]


# ---------------------------------------------------------------------------
# Finans slotları (Faz 8) — tur6 eğitim verisinin ön koşulu
# ---------------------------------------------------------------------------


def _finans_satiri(karar_tipi: str) -> dict:
    """`build_dataset.finans_karar_noktasi_veri_seti_uret` çıktısının bir satırı."""
    import datetime as dt
    import json

    from app.contracts import ABCSinifi, FinansOzellikleri, XYZSinifi
    from app.domain.finance.decide import ozellikten_kararlar_uret

    ozellik = FinansOzellikleri(
        musteri_id="M-0042",
        musteri_adi="Yılmaz İnşaat Ltd.",
        segment="santiye",
        toplam_alacak_tl=250_000.0,
        vadesi_gecen_tl=95_000.0,
        en_eski_gecikme_gun=400,
        ort_odeme_gecikmesi_gun=18.5,
        odeme_gecikmesi_std=45.0,
        veri_gun_sayisi=540,
        kredi_limiti_tl=200_000.0,
        abc_sinifi=ABCSinifi.A,
        xyz_sinifi=XYZSinifi.Y,
        hedef_tahsilat_orani=0.95,
        son_odeme_gun_once=41,
        tahsilat_orani=0.30,
        musteri_kredi_onayli=True,
        olcum_tarihi=dt.date(2026, 8, 10),
    )
    for karar in ozellikten_kararlar_uret(ozellik):
        if karar.tip.value != karar_tipi:
            continue
        return {
            "musteri_id": ozellik.musteri_id,
            "karar_tipi": karar.tip.value,
            "ozellikler": json.loads(ozellik.model_dump_json()),
            "aksiyon": karar.aksiyon,
            "tetiklenen_kurallar": [
                json.loads(k.model_dump_json()) for k in karar.tetiklenen_kurallar
            ],
        }
    raise AssertionError(f"{karar_tipi} üretilmedi")


def test_finans_karar_tiplerinin_hepsi_slot_uretiyor():
    """Slot tanımı olmayan karar tipi `None` döner ve eğitim verisinden
    sessizce düşer — tur6 öncesi kapatılması gereken boşluk buydu."""
    from training.label_rationale import _slotlari_cikar

    for tip in (
        "finans.tahsilat_takibi",
        "finans.karsilik_ayir",
        "finans.kredi_limiti_dusur",
    ):
        slotlar = _slotlari_cikar(_finans_satiri(tip))
        assert slotlar is not None, f"{tip} için slot tanımı yok"
        assert slotlar["MUSTERI_ADI"] == "Yılmaz İnşaat Ltd."


def test_oran_slotlari_yuzdeye_ceviriliyor():
    """⚠️ Guard'ın izinli kümesi `ORAN_ALANLARI` sayesinde ×100 karşılığını
    kabul ediyor; şablon farklı bir ölçek kullanırsa gerekçe reddedilir."""
    from training.label_rationale import _slotlari_cikar

    karsilik = _slotlari_cikar(_finans_satiri("finans.karsilik_ayir"))
    limit = _slotlari_cikar(_finans_satiri("finans.kredi_limiti_dusur"))

    assert karsilik["KARSILIK_YUZDE"] == 100.0  # 400 gün → %100 karşılık
    assert limit["TAHSILAT_YUZDE"] == 30.0  # tahsilat_orani 0,30


def test_finans_slot_adlari_stokla_cakismiyor():
    """Model tek ağırlık kümesinde iki alanı birden öğreniyor; aynı slot adı
    farklı anlama gelirse cümleler karışır."""
    from app.contracts import KararTipi
    from training.label_rationale import _SLOT_TANIMLARI

    def adlar(tipler: list[str]) -> set[str]:
        return {ad for t in tipler for ad, _, _ in _SLOT_TANIMLARI[t]}

    stok = adlar(
        [t.value for t in KararTipi if t.value.startswith("stok.") and t.value in _SLOT_TANIMLARI]
    )
    finans = adlar(
        [t.value for t in KararTipi if t.value.startswith("finans.") and t.value in _SLOT_TANIMLARI]
    )

    assert not (stok & finans), f"örtüşen slot adları: {stok & finans}"
