"""Yapılandırılmış çıktı şemaları (Ollama `format` parametresi).

Sahip: Kişi B · Faz 2 B2.2

Modelden düz metin değil **şemaya uyan JSON** istiyoruz. İki sebep:

1. **Router için zorunlu.** "Hangi araç, hangi parametre" sorusunun cevabı
   ayrıştırılabilir olmalı; serbest metinden araç adı çıkarmaya çalışmak
   kırılgan.
2. **Gerekçe için de faydalı.** Model düz metin istendiğinde önüne "İşte
   açıklama:" gibi giriş cümleleri ekliyor (B2.1'de görüldü). Tek alanlı bir
   şema bunu yapısal olarak engelliyor.

⚠️ `ARAC_ADLARI` listesi Kişi A'nın `training/build_dataset.py`'sindeki
`ARAC_TANIMLARI` ile **birebir aynı olmak zorunda.** Eğitim verisi o adlarla
üretildi; burada farklı bir ad kullanmak modelin öğrendiği etiketi
tanımaması demek. Ad değişecekse ikisi birlikte değişir.

Şema $ref'leri düzleştiriliyor (`semayi_duzlestir`): pydantic enum'ları
`$defs` + `$ref` olarak üretiyor, ama şemayı tüketen tarafın referans
çözebildiğini varsaymak gereksiz bir bahis. Düzleştirmek hem taşınabilir hem
de hata ayıklaması kolay.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.llm.client import OllamaIstemcisi, UretimSonucu


class AracAdi(StrEnum):
    """Router'ın seçebileceği araçlar.

    Kişi A'nın eğitim verisiyle aynı adlar. Bu listede olmayan bir araç adı
    modelin uydurmasıdır ve reddedilir.
    """

    KRITIK_STOK = "kritik_stok_sorgula"
    OLU_STOK = "olu_stok_sorgula"
    TEDARIKCI_PERFORMANSI = "tedarikci_performansi_sorgula"
    SIPARIS_ONERISI = "siparis_onerisi_sorgula"
    ONAY_KUYRUGU = "onay_kuyrugu_sorgula"
    GECELIK_OZET = "gecelik_ozet_sorgula"
    GENEL_STOK_DURUMU = "genel_stok_durumu_sorgula"

    # ⚠️ Faz 12'de eklendi — ve eklenmesinin bir SINIRI var.
    #
    # Canlı model (`codifya-router:tur6`) yalnızca yukarıdaki 7 araçla
    # eğitildi. Eğitilmiş kipte istemde araç listesi YOK (`router.py::
    # egitilmis_istem`), yani model bu adları hiç görmedi ve pratikte
    # üretemiyor. Aşağıdaki araçlar `llm_istem_bicimi="taban"` kipinde
    # (araç listesi isteme giriyor) seçilebiliyor.
    #
    # Yani bir aracı buraya eklemek onu ÇALIŞTIRILABİLİR yapar, modelin
    # SEÇEBİLİR olmasını sağlamaz. Ölçüldü ve `OLCUMLER.md`'ye yazıldı.
    URETIM_EMIRLERI = "uretim_emirleri_sorgula"
    URETIM_CIZELGESI = "uretim_cizelgesi_sorgula"
    KAPASITE_DURUMU = "kapasite_durumu_sorgula"
    PLAN_KARSILASTIR = "plan_karsilastir_sorgula"


EGITILMIS_ARAC_ADLARI: frozenset[str] = frozenset(
    {
        AracAdi.KRITIK_STOK,
        AracAdi.OLU_STOK,
        AracAdi.TEDARIKCI_PERFORMANSI,
        AracAdi.SIPARIS_ONERISI,
        AracAdi.ONAY_KUYRUGU,
        AracAdi.GECELIK_OZET,
        AracAdi.GENEL_STOK_DURUMU,
    }
)
"""Canlı modelin (`codifya-router:tur6`) eğitimde GÖRDÜĞÜ araçlar.

⚠️ Bu küme `AracAdi`'nin tamamı DEĞİL ve fark önemli:

    AracAdi                -> calistirilabilir araclarin tamami
    EGITILMIS_ARAC_ADLARI  -> modelin secebildikleri (egitilmis kipte)

Eğitilmiş kipte istem araç listesi taşımıyor (`router.py::egitilmis_istem`);
model yalnızca ağırlıklarına işlenmiş adları üretebiliyor. Faz 12'de eklenen
üretim/planlama araçları o kipte **pratikte ulaşılamaz**.

Taban kipinde (`llm_istem_bicimi="taban"`) araç listesi isteme giriyor ve
hepsi seçilebiliyor — ama o kipin genel doğruluğu daha düşük.

⚠️ Bu küme **eğitim verisiyle birlikte** değişir. Yeni bir tur eğitilip
üretim araçları da veriye girerse burası güncellenmeli; yoksa "model bunu
seçemez" bilgisi yanlış kalır."""


# Her aracın kabul ettiği parametre adı. `None` = parametre almaz.
# Kişi A'nın `AracTanimi.varlik_turu` alanıyla aynı.
ARAC_PARAMETRELERI: dict[AracAdi, str | None] = {
    AracAdi.KRITIK_STOK: "kategori",
    AracAdi.OLU_STOK: "kategori",
    AracAdi.TEDARIKCI_PERFORMANSI: "tedarikci_id",
    # `sku_id`, `sku_adi` değil: eğitim verisinde bu parametre ürün adını değil
    # SKU kodunu (`"S-01971"`) taşıyor. Kişi A ile birlikte adlandırma
    # düzeltildi (2026-08-02) — alan adı taşıdığı şeyle uyuşsun diye.
    AracAdi.SIPARIS_ONERISI: "sku_id",
    AracAdi.ONAY_KUYRUGU: None,
    AracAdi.GECELIK_OZET: "tarih_ifadesi",
    AracAdi.GENEL_STOK_DURUMU: None,
    # Faz 12 — üretim ve planlama araçları
    AracAdi.URETIM_EMIRLERI: None,
    AracAdi.URETIM_CIZELGESI: None,
    AracAdi.KAPASITE_DURUMU: None,
    AracAdi.PLAN_KARSILASTIR: None,
}


class AracCagrisi(BaseModel):
    """Router çıktısı: hangi araç, hangi parametreyle çağrılacak.

    `extra="forbid"`: model şemada olmayan bir alan uydurursa doğrulama
    başarısız olur ve yeniden denenir. Sessizce yok saymak, modelin
    "açıklama" gibi alanlar ekleyip bunu bizim onaylamamız anlamına gelirdi.
    """

    model_config = ConfigDict(extra="forbid")

    arac: AracAdi = Field(description="Çağrılacak aracın adı")
    parametreler: dict[str, str] = Field(
        default_factory=dict,
        description="Aracın beklediği parametre. Parametre almayan araçlarda boş.",
    )

    @model_validator(mode="after")
    def parametre_araca_uygun_mu(self) -> AracCagrisi:
        """Aracın kabul etmediği bir parametre gelirse reddet.

        Model doğru aracı seçip yanlış parametre uydurabilir — ör.
        `onay_kuyrugu_sorgula` parametre almaz ama modelin `{"kategori": "boya"}`
        eklemesi mümkün. Bunu geçirmek, aşağı akışta anlamsız bir sorgu demek.
        """
        beklenen = ARAC_PARAMETRELERI[self.arac]

        if beklenen is None:
            if self.parametreler:
                raise ValueError(
                    f"{self.arac.value} parametre almaz, geldi: {sorted(self.parametreler)}"
                )
            return self

        fazlalik = set(self.parametreler) - {beklenen}
        if fazlalik:
            raise ValueError(
                f"{self.arac.value} yalnizca '{beklenen}' alir, fazlalik: {sorted(fazlalik)}"
            )
        return self


class GerekceCiktisi(BaseModel):
    """Gerekçe üretimi çıktısı — tek alan, giriş cümlesi olmadan.

    Neden şema: B2.1'de model düz metin istendiğinde girdiyi liste hâlinde geri
    yazdı ve başına başlık ekledi. Tek alanlı şema, metnin doğrudan cümle
    olmasını yapısal olarak zorluyor.
    """

    model_config = ConfigDict(extra="forbid")

    gerekce: str = Field(
        min_length=1,
        description="Kararı açıklayan tek paragraflık Türkçe metin",
    )


def semayi_duzlestir(sema: dict[str, Any]) -> dict[str, Any]:
    """`$defs` + `$ref` yapısını satır içine açar.

    pydantic enum ve iç içe modelleri `$defs` altında tanımlayıp `$ref` ile
    işaret ediyor. Şemayı tüketen tarafın referans çözebildiğini varsaymak
    gereksiz bir bahis — düzleştirilmiş şema her yerde aynı davranır.

    Özyinelemeli (kendine referans veren) şemalarda sonsuz döngüye girer;
    bizim şemalarımız düz olduğu için sorun değil, ama yeni bir model
    eklenirken akılda tutulmalı.
    """
    tanimlar = sema.get("$defs", {})

    def coz(dugum: Any) -> Any:
        if isinstance(dugum, dict):
            if "$ref" in dugum:
                ad = dugum["$ref"].rsplit("/", 1)[-1]
                hedef = copy.deepcopy(tanimlar.get(ad, {}))
                # `$ref` yanında description gibi ek alanlar olabilir; korunur.
                ek = {k: v for k, v in dugum.items() if k != "$ref"}
                return coz({**hedef, **ek})
            return {k: coz(v) for k, v in dugum.items() if k != "$defs"}
        if isinstance(dugum, list):
            return [coz(x) for x in dugum]
        return dugum

    return coz(sema)


def sema_of(model: type[BaseModel]) -> dict[str, Any]:
    """Bir pydantic modelinin Ollama'ya geçirilecek düzleştirilmiş şeması."""
    return semayi_duzlestir(model.model_json_schema())


# ---------------------------------------------------------------------------
# Şema zorlamalı üretim
# ---------------------------------------------------------------------------


class SemaUyumsuz(ValueError):
    """Model, izin verilen deneme sayısı içinde şemaya uyan çıktı üretemedi.

    Çağıran taraf buna göre davranır: gerekçe üretiminde şablona düşülür,
    router'da soru cevapsız bırakılır. İkisi de kararı bloke etmez.
    """

    def __init__(self, mesaj: str, *, denemeler: int, son_ham_cikti: str) -> None:
        super().__init__(mesaj)
        self.denemeler = denemeler
        self.son_ham_cikti = son_ham_cikti


@dataclass(frozen=True)
class YapilandirilmisSonuc[T: BaseModel]:
    """Şemaya uyan çıktı + kaç denemede elde edildiği + ölçümler."""

    deger: T
    deneme_sayisi: int
    uretim: UretimSonucu


def yapilandirilmis_uret[T: BaseModel](
    istemci: OllamaIstemcisi,
    model_sinifi: type[T],
    istem: str,
    *,
    sistem: str | None = None,
    max_token: int | None = None,
    max_deneme: int = 2,
    sicaklik: float | None = None,
    tohum: int | None = None,
) -> YapilandirilmisSonuc[T]:
    """Şemaya uyan çıktı alana kadar dener, alamazsa `SemaUyumsuz` fırlatır.

    Yeniden deneme burada **içerik** hatası içindir (geçersiz JSON, şemaya
    uymayan alan, uydurma araç adı). Ağ hataları bir kat altta,
    `client._istek_at` içinde ele alınıyor — ikisi bilinçli olarak ayrı:
    ağ hatası tekrarlanabilir bir aksaklık, şema hatası modelin davranışı.

    `max_deneme=2` görev dosyasının guard için koyduğu kuralla aynı ("2
    denemede geçemezse şablona düş"). Daha fazla denemek CPU yakar ve
    pratikte 3. deneme 2.'den anlamlı şekilde iyi olmuyor.
    """
    sema = sema_of(model_sinifi)
    son_ham = ""
    son_hata = ""

    for deneme in range(1, max_deneme + 1):
        uretim = istemci.uret(
            istem,
            sistem=sistem,
            max_token=max_token,
            sema=sema,
            sicaklik=sicaklik,
            tohum=tohum,
        )
        son_ham = uretim.metin

        try:
            return YapilandirilmisSonuc(
                deger=model_sinifi.model_validate_json(uretim.metin),
                deneme_sayisi=deneme,
                uretim=uretim,
            )
        except ValidationError as hata:
            # İlk hatanın kısa özeti yeter; tam gövde `son_ham_cikti`'da.
            son_hata = str(hata).splitlines()[0] if str(hata) else type(hata).__name__

    raise SemaUyumsuz(
        f"{model_sinifi.__name__} şeması {max_deneme} denemede tutturulamadı: {son_hata}",
        denemeler=max_deneme,
        son_ham_cikti=son_ham,
    )
