"""Yapılandırılmış çıktı şemaları testleri (Faz 2 B2.2).

⚠️ Hiçbiri gerçek modeli çalıştırmaz — sahte cevaplarla.

Kabul ölçütü ("20 ardışık çağrının 20'si geçerli JSON") gerçek modelle ayrıca
ölçülür ve `dokumantasyon/OLCUMLER.md`'ye yazılır. Buradaki testler o ölçümün
dayandığı mantığı sınar: şema üretimi, doğrulama, yeniden deneme.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Ayarlar
from app.llm.client import OllamaIstemcisi
from app.llm.schemas import (
    ARAC_PARAMETRELERI,
    AracAdi,
    AracCagrisi,
    GerekceCiktisi,
    SemaUyumsuz,
    sema_of,
    semayi_duzlestir,
    yapilandirilmis_uret,
)

# Kişi A'nın training/build_dataset.py'sindeki ARAC_TANIMLARI ile birebir aynı
# olmalı — eğitim verisi o adlarla üretildi.
KISI_A_ARAC_ADLARI = {
    "kritik_stok_sorgula",
    "olu_stok_sorgula",
    "tedarikci_performansi_sorgula",
    "siparis_onerisi_sorgula",
    "onay_kuyrugu_sorgula",
    "gecelik_ozet_sorgula",
    "genel_stok_durumu_sorgula",
}


def _ayar() -> Ayarlar:
    return Ayarlar(ollama_base_url="http://sahte:11434", llm_yeniden_deneme=0)


def _istemci(cevaplar: list[str]) -> OllamaIstemcisi:
    """Sırayla verilen metinleri döndüren sahte istemci."""
    kalan = list(cevaplar)

    def isleyici(istek: httpx.Request) -> httpx.Response:
        metin = kalan.pop(0) if kalan else ""
        return httpx.Response(
            200,
            json={
                "model": "sahte",
                "response": metin,
                "eval_count": 20,
                "eval_duration": 1_000_000_000,
                "load_duration": 0,
            },
        )

    return OllamaIstemcisi(_ayar(), transport=httpx.MockTransport(isleyici))


# --- Araç listesi Kişi A ile uyumlu mu ----------------------------------------


def test_arac_adlari_kisi_a_ile_ayni():
    """⭐ Eğitim verisi bu adlarla üretildi.

    Ad ayrışırsa model öğrendiği etiketi tanımaz ve router sessizce
    başarısız olur — hata mesajı da vermez, sadece doğruluk düşer.
    """
    # ⚠️ Faz 12: `AracAdi` artık üretim/planlama araçlarını da taşıyor.
    # Kişi A'nın eğitim verisiyle eşleşmesi gereken küme `EGITILMIS_ARAC_ADLARI`
    # — modelin SEÇEBİLDİKLERİ. Tamamı ise ÇALIŞTIRILABİLİRLER.
    #
    # İkisini bir tutmak, yeni bir aracın "model bunu da seçebilir" sanılmasına
    # yol açardı; seçemiyor, çünkü eğitimde görmedi.
    from app.llm.schemas import EGITILMIS_ARAC_ADLARI

    assert {str(a) for a in EGITILMIS_ARAC_ADLARI} == KISI_A_ARAC_ADLARI
    assert {a.value for a in AracAdi} >= KISI_A_ARAC_ADLARI


def test_her_aracin_parametresi_tanimli():
    assert set(ARAC_PARAMETRELERI) == set(AracAdi)


# --- Şema üretimi -------------------------------------------------------------


def test_sema_duzlestirilir_ref_kalmaz():
    """Ollama'nın `$ref` çözebildiğini varsaymak gereksiz bir bahis."""
    sema = sema_of(AracCagrisi)
    metin = json.dumps(sema)

    assert "$ref" not in metin
    assert "$defs" not in metin


def test_sema_arac_adlarini_enum_olarak_tasir():
    """Model yalnızca TANIMLI araçlardan birini üretebilsin — uydurma reddedilsin.

    ⚠️ Şema `AracAdi`'nin tamamını taşıyor, eğitilmiş alt kümeyi değil.
    Sebebi: taban kipinde (araç listesi isteme giriyor) yeni araçlar
    seçilebilmeli. Şemayı 7 ile sınırlamak, taban kipini de eğitilmiş kipin
    sınırına hapsederdi.
    """
    sema = sema_of(AracCagrisi)
    enum_degerleri = set(sema["properties"]["arac"]["enum"])

    assert enum_degerleri == {a.value for a in AracAdi}
    assert enum_degerleri >= KISI_A_ARAC_ADLARI


def test_duzlestirme_ek_alanlari_korur():
    kaynak = {
        "$defs": {"X": {"type": "string", "enum": ["a"]}},
        "properties": {"f": {"$ref": "#/$defs/X", "description": "aciklama"}},
    }
    sonuc = semayi_duzlestir(kaynak)

    assert sonuc["properties"]["f"]["enum"] == ["a"]
    assert sonuc["properties"]["f"]["description"] == "aciklama"


# --- Doğrulama kuralları ------------------------------------------------------


def test_bilinmeyen_arac_reddedilir():
    """Model olmayan bir araç uydurursa şema düzeyinde elenir."""
    with pytest.raises(ValidationError):
        AracCagrisi.model_validate({"arac": "stok_sil", "parametreler": {}})


def test_parametresiz_arac_parametre_alirsa_reddedilir():
    """Doğru araç + uydurma parametre = aşağı akışta anlamsız sorgu."""
    with pytest.raises(ValidationError, match="parametre almaz"):
        AracCagrisi.model_validate(
            {"arac": "onay_kuyrugu_sorgula", "parametreler": {"kategori": "boya"}}
        )


def test_yanlis_parametre_adi_reddedilir():
    with pytest.raises(ValidationError, match="yalnizca"):
        AracCagrisi.model_validate(
            {"arac": "kritik_stok_sorgula", "parametreler": {"tedarikci_id": "T-014"}}
        )


def test_dogru_parametre_kabul_edilir():
    cagri = AracCagrisi.model_validate(
        {"arac": "kritik_stok_sorgula", "parametreler": {"kategori": "boya"}}
    )
    assert cagri.arac is AracAdi.KRITIK_STOK
    assert cagri.parametreler == {"kategori": "boya"}


def test_parametresiz_arac_bos_sozlukle_gecerli():
    cagri = AracCagrisi.model_validate({"arac": "onay_kuyrugu_sorgula"})
    assert cagri.parametreler == {}


def test_semada_olmayan_alan_reddedilir():
    """`extra="forbid"`: model kendi alanını uydurursa sessizce kabul etmeyelim."""
    with pytest.raises(ValidationError):
        AracCagrisi.model_validate(
            {"arac": "onay_kuyrugu_sorgula", "parametreler": {}, "aciklama": "..."}
        )


def test_bos_gerekce_reddedilir():
    with pytest.raises(ValidationError):
        GerekceCiktisi.model_validate({"gerekce": ""})


# --- Şema zorlamalı üretim ----------------------------------------------------


def test_gecerli_json_ilk_denemede_kabul_edilir():
    istemci = _istemci(['{"arac": "onay_kuyrugu_sorgula", "parametreler": {}}'])

    sonuc = yapilandirilmis_uret(istemci, AracCagrisi, "kuyrukta ne var")

    assert sonuc.deger.arac is AracAdi.ONAY_KUYRUGU
    assert sonuc.deneme_sayisi == 1
    assert sonuc.uretim.uretim_token == 20


def test_bozuk_json_sonra_duzgun_json_yeniden_denenir():
    istemci = _istemci(
        [
            "bu JSON degil",
            '{"arac": "kritik_stok_sorgula", "parametreler": {"kategori": "boya"}}',
        ]
    )

    sonuc = yapilandirilmis_uret(istemci, AracCagrisi, "kritik stok var mi")

    assert sonuc.deneme_sayisi == 2
    assert sonuc.deger.arac is AracAdi.KRITIK_STOK


def test_tum_denemeler_bozuksa_sema_uyumsuz():
    istemci = _istemci(["bozuk", "yine bozuk"])

    with pytest.raises(SemaUyumsuz) as hata:
        yapilandirilmis_uret(istemci, AracCagrisi, "soru", max_deneme=2)

    assert hata.value.denemeler == 2
    assert hata.value.son_ham_cikti == "yine bozuk"


def test_uydurma_arac_adi_yeniden_denemeye_yol_acar():
    """Geçerli JSON ama olmayan araç — şema doğrulaması bunu da yakalamalı."""
    istemci = _istemci(
        [
            '{"arac": "stok_sil", "parametreler": {}}',
            '{"arac": "genel_stok_durumu_sorgula", "parametreler": {}}',
        ]
    )

    sonuc = yapilandirilmis_uret(istemci, AracCagrisi, "soru")

    assert sonuc.deneme_sayisi == 2
    assert sonuc.deger.arac is AracAdi.GENEL_STOK_DURUMU


def test_sema_her_istekte_gonderilir():
    gonderilen: dict[str, Any] = {}

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.update(json.loads(istek.content))
        return httpx.Response(
            200,
            json={
                "model": "sahte",
                "response": '{"gerekce": "Bir cumle."}',
                "eval_count": 5,
                "eval_duration": 1_000_000_000,
            },
        )

    istemci = OllamaIstemcisi(_ayar(), transport=httpx.MockTransport(isleyici))
    yapilandirilmis_uret(istemci, GerekceCiktisi, "acikla")

    assert "format" in gonderilen
    assert gonderilen["format"]["properties"]["gerekce"]["type"] == "string"


def test_gerekce_ciktisi_metni_tasir():
    istemci = _istemci(['{"gerekce": "Stok yeterli, aksiyon gerekmiyor."}'])

    sonuc = yapilandirilmis_uret(istemci, GerekceCiktisi, "acikla")

    assert sonuc.deger.gerekce == "Stok yeterli, aksiyon gerekmiyor."
