"""İşletme profili — müşteriye göre değişen her sayı tek dosyada.

Sahip: Kişi A · Faz 9

`app/core/config.py` şu kuralı koyuyor:

    KURAL: Kodda hiçbir sabit (hardcoded) eşik olmayacak. Bir sayı iş
    kararıysa buraya ya da `policy` tablosuna girer.

⚠️ **Kural tutulmadı.** 2026-08-10'da sayıldı: 34 iş parametresi
`app/domain/*/rules.py` içinde modül sabiti olarak duruyor. Hedef servis
seviyesi matrisi, ölü stok eşikleri, karşılık kademeleri, finansman oranı,
personel saatlik maliyeti, kredi limiti kolu... Hepsi **müşteriye göre
değişir** ve şu an değiştirmek için kod dağıtmak gerekiyor.

Sebebi anlaşılır: her sabit yazılırken "bu genel bir doğru" gibi görünüyordu.
Bir nalburun ölü stok eşiğiyle bir ilaç deposununki aynı olamaz — ama tek
müşterin yokken bu görünmüyor.

## Bu dosya ne yapıyor

Tüm iş parametrelerini tek bir **profil** nesnesinde topluyor. Varsayılan
değerler bugüne kadarki sabitlerin birebir aynısı, yani davranış
değişmiyor. Yeni müşteri = yeni profil dosyası, kod dağıtımı yok.

    # .env
    ISLETME_PROFILI_YOLU=profiller/nalbur.json

⚠️ Profil **iş kararlarını** taşır, teknik ayarları değil. Veritabanı
adresi, LLM modeli, zaman aşımı `config.py`'de kalır — onlar kuruluma
göre değişir, işe göre değil. İki dosyanın karışması, "bu sayıyı kim
değiştirebilir" sorusunu belirsizleştirir: profili iş sahibi, config'i
sistem yöneticisi değiştirir.

## Neden pydantic, neden düz sözlük değil

Yanlış bir sayı sessizce kabul edilmemeli. `hedef_servis_seviyesi` 1,2
yazılırsa (yüzde sanılıp) `norm.ppf` sonsuz döndürür ve emniyet stoğu
patlar — hata aylar sonra, tuhaf bir sipariş miktarı olarak görünür.
Sınırlar burada tanımlı; profil yüklenirken patlar, çalışırken değil.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

PROJE_KOKU = Path(__file__).resolve().parents[2]


class StokProfili(BaseModel):
    """Stok kararlarının iş parametreleri."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Ölü stok ---
    olu_stok_mutlak_esik_gun: int = Field(
        default=90,
        ge=1,
        description="Hiçbir SKU bunun altında ölü sayılmaz.",
    )
    olu_stok_goreceli_carpan: float = Field(
        default=6.0,
        gt=0,
        description="Ürünün tipik satış aralığının kaç katı sessizlik ölü sayılır.",
    )
    olu_stok_asgari_stok_gun: float = Field(
        default=1.0,
        ge=0,
        description=(
            "Ölü stok kararı için elde en az bu kadar günlük talebi karşılayacak "
            "mal olmalı. ⚠️ Bu kapı olmadan stoksuzluk ölü stok gibi görünür "
            "(bkz. BILINEN-EKSIKLER §11)."
        ),
    )

    # --- Maliyet ---
    yillik_elde_tutma_orani: float = Field(
        default=0.25,
        gt=0,
        lt=1,
        description="Stok tutmanın yıllık maliyeti, malın değerine oran.",
    )
    siparis_maliyeti_tl: float = Field(
        default=250.0,
        ge=0,
        description="Bir sipariş açmanın sabit maliyeti (EOQ girdisi).",
    )
    stoktukenmesi_ceza_carpani: float = Field(
        default=2.5,
        ge=1,
        description=(
            "Stok tükenmesinin gerçek maliyeti kayıp kâr marjının kaç katı. "
            "Müşteri güveni, acil tedarik, gelecek satış riski."
        ),
    )

    # --- Tedarikçi ---
    tedarikci_degisim_skor_esigi: float = Field(default=50.0, ge=0, le=100)
    tedarikci_degisim_asgari_siparis: int = Field(
        default=5,
        ge=1,
        description="Bu kadar sipariş geçmişi yoksa tedarikçi hakkında hüküm verilmez.",
    )


class FinansProfili(BaseModel):
    """Tahsilat ve alacak kararlarının iş parametreleri."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- Karşılık ---
    karsilik_mutlak_esik_gun: int = Field(default=180, ge=1)
    karsilik_taban_esik_gun: int = Field(
        default=90,
        ge=1,
        description=(
            "Göreceli eşiğin inebileceği taban. ⚠️ Altına inerse hızlı ödeyen "
            "müşterinin 40 günlük alacağına karşılık ayrılır (§9)."
        ),
    )
    karsilik_goreceli_carpan: float = Field(default=4.0, gt=0)

    # --- Kredi limiti ---
    limit_kolu_aktif: bool = Field(
        default=True,
        description=(
            "Kredi limiti düşürme kolu. ⚠️ Batak oranı %3'ün altında ve "
            "planlama ufku 1 yılsa kapatılabilir (§14). Emin değilsen açık "
            "bırak — asimetri onu söylüyor."
        ),
    )
    limit_dusurme_skor_esigi: float = Field(default=45.0, ge=0, le=100)
    maks_limit_kesinti_orani: float = Field(
        default=0.5,
        ge=0,
        le=1,
        description="Limit en fazla bu oranda kısılır (skor 0 olsa bile).",
    )
    limit_ciro_carpani: float = Field(default=2.0, gt=0)

    # --- İş gücü ve finansman ---
    personel_saatlik_maliyet_tl: float = Field(
        default=450.0,
        ge=0,
        description="Tahsilat personelinin yüklenmiş saatlik maliyeti.",
    )
    takip_suresi_dk: float = Field(
        default=20.0,
        gt=0,
        description="Bir tahsilat eyleminin insan zamanı.",
    )
    yillik_finansman_orani: float = Field(
        default=0.45,
        gt=0,
        description="Tahsil edilmemiş alacağın yıllık taşıma maliyeti.",
    )
    maddi_takip_ufku_gun: int = Field(default=30, ge=1)
    maddi_asgari_gecikme_gun: int = Field(default=7, ge=0)

    @property
    def takip_eylem_maliyeti_tl(self) -> float:
        """Bir tahsilat eyleminin parasal maliyeti — türetiliyor, seçilmiyor."""
        return self.personel_saatlik_maliyet_tl * (self.takip_suresi_dk / 60.0)

    @property
    def maddi_takip_esigi_tl(self) -> float:
        """Aramanın kendini ödediği asgari alacak.

        ⭐ Seçilmiyor, **türetiliyor**:

            eylem maliyeti = alacak x günlük finansman oranı x ufuk

        Müşteride faiz düşükse eşik kendiliğinden yükselir, personel ucuzsa
        düşer. Elle ayarlanacak bir sayı olmaması bilinçli.
        """
        gunluk = self.yillik_finansman_orani / 365.0
        return self.takip_eylem_maliyeti_tl / (gunluk * self.maddi_takip_ufku_gun)


class IsletmeProfili(BaseModel):
    """Bir müşterinin iş parametrelerinin tamamı.

    ⚠️ Varsayılanlar bugüne kadarki modül sabitlerinin **birebir aynısı**.
    Profil verilmezse davranış değişmiyor — bu dosyanın eklenmesi tek
    başına hiçbir sayıyı oynatmıyor.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ad: str = Field(default="varsayilan", description="Müşteri/kurulum adı — log ve rapor için.")
    sektor: str = Field(default="genel", description="Serbest metin; yalnızca insan okur.")
    stok: StokProfili = Field(default_factory=StokProfili)
    finans: FinansProfili = Field(default_factory=FinansProfili)

    @classmethod
    def dosyadan(cls, yol: Path | str) -> IsletmeProfili:
        """JSON profilini okur.

        ⚠️ Eksik alanlar varsayılana düşer, **fazla alanlar hata verir**.
        Sebebi: `karsilik_esigi` diye yazıp `karsilik_taban_esik_gun`
        demeyi unutan bir kurulum, sessizce varsayılanla çalışırdı ve
        kimse fark etmezdi. Yazım hatası hata vermeli.
        """
        yol = Path(yol)
        if not yol.is_absolute():
            yol = PROJE_KOKU / yol
        return cls.model_validate(json.loads(yol.read_text(encoding="utf-8")))

    def dosyaya_yaz(self, yol: Path | str) -> None:
        """Profili JSON olarak yazar — yeni müşteri için şablon üretmek üzere."""
        Path(yol).write_text(
            json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


@lru_cache
def profil() -> IsletmeProfili:
    """Etkin işletme profili.

    `ISLETME_PROFILI_YOLU` ayarı verilmişse o dosyadan, yoksa varsayılan.
    `lru_cache` bilinçli: profil çalışma sırasında değişmez, her okumada
    dosyaya gitmek anlamsız. Test içinde değiştirmek için
    `profil.cache_clear()`.
    """
    from app.core.config import ayarlar

    yol = ayarlar().isletme_profili_yolu
    if yol:
        return IsletmeProfili.dosyadan(yol)
    return IsletmeProfili()


__all__ = ["FinansProfili", "IsletmeProfili", "StokProfili", "profil"]
