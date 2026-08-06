"""Eğitilmiş kip istemi — eğitim ve çalışma zamanı hizası (2. tur kök neden düzeltmesi).

Bu dosyanın merkezi `test_egitim_ve_calisma_zamani_istemi_birebir_ayni`:
o test kırmızıysa eğitim verisi, modelin çalışma zamanında göreceğinden
farklı bir biçimde üretiliyor demektir ve eğitimin kazandırdığı her şey
çöpe gider.

İkinci kritik değişmez: hedef metnin kullanabildiği her sayı istemde
olmalı. Aksi halde model o sayıyı uydurmayı öğrenir — 2. turda tam olarak
bu oldu (örneklerin %79,4'ü). Bkz. `dokumantasyon/OLCUMLER.md`.
"""

from __future__ import annotations

import json

import pytest

from app.contracts import KararTipi
from app.domain.stock.decide import decide_stub, stok_karari_uret
from app.llm.explain import (
    GOREV_ETIKETI_GEREKCE,
    egitilmis_istem_govdesi,
    egitilmis_istem_kur,
    egitilmis_sayi_etiketleri,
)
from app.llm.guard import metni_maskele, sayilari_cikar
from training.eval.veri_tutarlilik_kontrolu import istemde_olmayan_sayilar
from training.veri_hazirla import istem_kur


def _ham_kayit(aday) -> dict:
    """`DecisionCandidate`'ten `veri_hazirla`'nın beklediği ham kayıt biçimi."""
    return {
        "ozellikler": json.loads(aday.ozellikler.model_dump_json()),
        "karar_tipi": aday.tip.value,
        "aksiyon": aday.aksiyon,
        "tahmini_tutar_tl": aday.tahmini_tutar_tl,
        "guven": aday.guven,
        "tetiklenen_kurallar": [json.loads(k.model_dump_json()) for k in aday.tetiklenen_kurallar],
    }


# --- ⭐ Kabul ölçütü ----------------------------------------------------------


def test_egitim_ve_calisma_zamani_istemi_birebir_ayni():
    """⭐ Eğitim verisi ile çalışma zamanı istemi aynı olmalı.

    2. turda ikisi ayrı listelerden üretiliyordu ve sessizce ayrıştılar.
    Artık ikisi de `egitilmis_istem_govdesi`'nden besleniyor; bu test o
    bağın kopmadığını doğruluyor.
    """
    aday = decide_stub()

    egitim_istemi = istem_kur(_ham_kayit(aday))
    calisma_zamani_istemi = egitilmis_istem_govdesi(aday)

    assert egitim_istemi == calisma_zamani_istemi


def test_egitilmis_kipte_yeniden_deneme_sicakligi_yukseltiyor():
    """⭐ Eğitilmiş kipte yeniden denemeyi anlamlı kılan tek şey bu.

    `onceki_red` isteme yazılamıyor (o satır eğitimde hiç geçmedi), dolayısıyla
    ikinci denemenin istemi birinciyle **aynı**. Sıcaklık 0'da çıktı da birebir
    aynı olurdu — bir model çağrısı, hiçbir kazanç.

    Çözüm istemi değil üretimi değiştirmek: sıcaklık ve tohum yeniden denemede
    değişiyor.
    """
    import json

    import httpx

    from app.core.config import Ayarlar
    from app.llm.client import OllamaIstemcisi
    from app.llm.explain import YENIDEN_DENEME_SICAKLIGI, llm_ureteci

    gonderilen: list[dict] = []

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.append(json.loads(istek.content))
        return httpx.Response(
            200,
            json={
                "model": "sahte",
                "response": json.dumps({"gerekce": "Stok yeterli."}, ensure_ascii=False),
                "eval_count": 5,
                "eval_duration": 1_000_000_000,
                "load_duration": 0,
            },
        )

    ayar = Ayarlar(
        ollama_base_url="http://sahte:11434",
        llm_yeniden_deneme=0,
        llm_istem_bicimi="egitilmis",
    )
    istemci = OllamaIstemcisi(ayar, transport=httpx.MockTransport(isleyici))
    uret = llm_ureteci(istemci, sicaklik=0.0, tohum=42)
    aday = decide_stub()

    uret(aday)  # ilk deneme
    uret(aday, onceki_red=[9999.0])  # guard reddetti, yeniden

    ilk, ikinci = gonderilen[0]["options"], gonderilen[1]["options"]

    assert ilk["temperature"] == 0.0
    assert ikinci["temperature"] == YENIDEN_DENEME_SICAKLIGI
    assert ikinci["seed"] != ilk["seed"], "tohum da degismeli, yoksa ayni ornekleme"
    # İstem değişmemeli — eğitimde görülmeyen satır eklenmiyor.
    assert gonderilen[0]["prompt"] == gonderilen[1]["prompt"]


def test_taban_kipte_yeniden_deneme_istemi_degistiriyor():
    """Taban kipte çözüm farklı: istem değişiyor, sıcaklık sabit kalıyor."""
    import json

    import httpx

    from app.core.config import Ayarlar
    from app.llm.client import OllamaIstemcisi
    from app.llm.explain import llm_ureteci

    gonderilen: list[dict] = []

    def isleyici(istek: httpx.Request) -> httpx.Response:
        gonderilen.append(json.loads(istek.content))
        return httpx.Response(
            200,
            json={
                "model": "sahte",
                "response": json.dumps({"gerekce": "Stok yeterli."}, ensure_ascii=False),
                "eval_count": 5,
                "eval_duration": 1_000_000_000,
                "load_duration": 0,
            },
        )

    ayar = Ayarlar(
        ollama_base_url="http://sahte:11434",
        llm_yeniden_deneme=0,
        llm_istem_bicimi="taban",
    )
    istemci = OllamaIstemcisi(ayar, transport=httpx.MockTransport(isleyici))
    uret = llm_ureteci(istemci, sicaklik=0.0, tohum=42)
    aday = decide_stub()

    uret(aday)
    uret(aday, onceki_red=[9999.0])

    assert gonderilen[0]["options"]["temperature"] == gonderilen[1]["options"]["temperature"]
    assert gonderilen[0]["prompt"] != gonderilen[1]["prompt"]
    assert "9.999" in gonderilen[1]["prompt"]


def test_calisma_zamani_istemi_gorev_basligi_ekler():
    aday = decide_stub()
    tam = egitilmis_istem_kur(aday)

    assert tam.startswith(f"{GOREV_ETIKETI_GEREKCE}\n")
    # Başlık çıkarılınca geriye eğitim verisindeki gövde kalmalı — defter
    # (`train_lora.ipynb::gerekce_metni`) başlığı kendisi ekliyor.
    assert tam.removeprefix(f"{GOREV_ETIKETI_GEREKCE}\n") == istem_kur(_ham_kayit(aday))


# --- Kök nedenin kendisi ------------------------------------------------------


@pytest.mark.parametrize("uretici", [decide_stub, stok_karari_uret])
def test_hedefin_kullanabildigi_sayilar_istemde_var(uretici):
    """İstem, `izinli_sayilar()`'ın gerekçede kullanılan kısmını kapsamalı.

    Tam kapsama beklenmiyor (izinli küme bilinçli olarak geniş); beklenen
    şey, isteme konan her etiketin gerçekten izinli bir sayı taşıması ve
    karar tipinin ana sayılarının dışarıda kalmaması.
    """
    aday = uretici()
    izinli = aday.izinli_sayilar()

    ciftler = egitilmis_sayi_etiketleri(aday)
    assert ciftler, "istem hiç sayı içermiyor"

    for etiket, deger in ciftler:
        assert any(abs(deger - i) <= max(0.02, abs(i) * 0.01) for i in izinli), (
            f"{etiket}={deger} izinli kümede yok — guard bunu reddederdi"
        )


def test_tasfiye_isteminde_iskonto_orani_var():
    """2. turun en sık uydurtulan değeri (%15, 886 kez) artık istemde.

    `onerilen_iskonto_orani` hem `_EGITILMIS_TIPE_GORE_ALANLAR`'a hem de
    `ORAN_ALANLARI`'na eklendi; ikincisi olmadan yüzde karşılığı guard'a
    takılırdı.
    """
    aday = decide_stub().model_copy(
        update={"tip": KararTipi.STOK_TASFIYE, "aksiyon": {"onerilen_iskonto_orani": 0.15}}
    )
    istem = egitilmis_istem_govdesi(aday)

    assert "onerilen iskonto orani (%)" in istem
    assert "15" in istem
    assert 15.0 in aday.izinli_sayilar(), "yüzde karşılığı izinli değilse guard reddeder"


def test_siparis_isteminde_tedarikci_adi_var():
    """Tedarikçi ADI da istemde olmalı — guard metin uydurmasını yakalayamaz."""
    aday = decide_stub().model_copy(update={"tip": KararTipi.STOK_SIPARIS})
    istem = egitilmis_istem_govdesi(aday)

    assert f"tedarikci: {aday.ozellikler.tedarikci_adi}" in istem


def test_uretilen_istem_kendi_hedefini_kapsar():
    """Uçtan uca: şablon gerekçe hedef sayılsa, tutarlılık kontrolü geçmeli."""
    from app.llm.explain import sablon_gerekce

    aday = stok_karari_uret()
    istem = egitilmis_istem_govdesi(aday)
    hedef = sablon_gerekce(aday)

    assert istemde_olmayan_sayilar(istem, hedef) == []


# --- Biçim değişmezleri -------------------------------------------------------


def test_istem_turkce_karakter_icermez():
    """Etiketler ASCII — eğitim verisi böyle üretiliyor, tokenizer yükü az."""
    aday = decide_stub()
    metin_satirlari = ("urun:", "tedarikci:")
    etiket_bolumu = "\n".join(
        s
        for s in egitilmis_istem_govdesi(aday).splitlines()
        if not s.startswith(metin_satirlari)
    )
    assert not set(etiket_bolumu) & set("çğıöşüÇĞİÖŞÜ")


def test_istem_gerekce_ile_biter():
    """Model üretime `GEREKCE:` satırından sonra başlar."""
    assert egitilmis_istem_govdesi(decide_stub()).endswith("\n\nGEREKCE:")


def test_urun_adindaki_rakamlar_sayi_olarak_sayilmaz():
    """'Alcipan 12.5mm' ürün adı, istemdeki sayı kümesini kirletmemeli."""
    aday = decide_stub()
    istem = egitilmis_istem_govdesi(aday)
    ad = aday.ozellikler.sku_adi

    maskeli = sayilari_cikar(metni_maskele(istem, [ad]))
    etiketli_degerler = [d for _, d in egitilmis_sayi_etiketleri(aday)]
    assert len(maskeli) == len(etiketli_degerler)
