"""Tahmin sözleşmesi — Kişi A ile Kişi B arasındaki tek bağ.

⚠️ **DONMUŞ DOSYA.** `app/contracts.py` ile aynı kural geçerli: tek taraflı
değiştirilmez. Üretim kararları (Kişi A) bu tipi tüketiyor; alan adı ya da
anlamı değişirse karar tarafı sessizce yanlış sayı okur.

Neden ayrı bir sözleşme dosyası: `app/contracts.py` karar motorunun
sözleşmesi ve zaten donmuş. Tahmin oraya eklenirse iki farklı hızda değişen
şey tek dosyada yaşar. Buradaki sözleşme daha küçük ve daha yeni; ayrı
tutulup ayrı dondurulması, ana sözleşmeyi her tahmin değişikliğinde açmaya
zorlamıyor.
"""

from __future__ import annotations

from datetime import date, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Varsayılan planlama ufku. Üretim tarafı profilden kendi ufkunu verebilir;
# bu yalnızca ölçüm ve varsayılan çağrılar için başlangıç noktası.
#
# 14 gün seçildi çünkü üretim emri kararının anlamlı olduğu en kısa aralık
# bu: tipik hazırlık + işlem + sevkiyat süresinden uzun, ama mevsimsel
# kaymanın tahmini bozacağı kadar da uzun değil.
VARSAYILAN_UFUK_GUN = 14


class TalepTahmini(BaseModel):
    """Bir kalem için ufuk boyunca beklenen günlük talep.

    ⚠️ **Bant zorunlu, tek sayı yeterli değil.** Üretim planı belirsizliği
    göremezse emniyet payını körlemesine seçer; kapasite kararı da "kötü
    senaryoda ne olur" sorusunu hiç soramaz. Tek nokta tahmini vermek,
    tahminin kesin olduğu izlenimi yaratır — oysa `talep_varyasyon_katsayisi`
    zaten kalemlerin bir kısmının öngörülemez olduğunu söylüyor (XYZ
    sınıflandırması tam bu soruyu cevaplıyor).

    `yontem` ve `egitim_gun_sayisi` süs değil, **ölçümün taşıyıcısı**: hangi
    modelin ne kadar geçmişle ürettiği kayıtlı olmazsa "tahmin iyileşti mi"
    sorusu sonradan cevaplanamaz. Router ölçümünde aynı dersi aldık — hangi
    modelle ölçüldüğü kaydedilmediği için bir koşu yeniden üretilemedi.
    """

    model_config = ConfigDict(frozen=True)

    kalem_id: str = Field(description="SKU ya da üretilen ürün kimliği")
    baslangic: date = Field(description="`gunluk[0]`'ın ait olduğu gün")
    gunluk: list[float] = Field(min_length=1, description="Beklenen günlük talep")
    alt_band: list[float] = Field(description="Alt sınır — kötümser senaryo")
    ust_band: list[float] = Field(description="Üst sınır — iyimser senaryo")
    yontem: str = Field(description="Tahmini üreten modelin adı")
    egitim_gun_sayisi: int = Field(ge=0, description="Kaç günlük geçmişten üretildi")

    @model_validator(mode="after")
    def _tutarli_mi(self) -> TalepTahmini:
        """Üç dizi aynı uzunlukta ve bantlar sıralı olmalı.

        ⚠️ Bu kontrol çalışma zamanında değil **kurulum anında** patlasın
        diye burada. Bantları karıştırmış bir model, üretim tarafında
        "emniyet payı negatif çıktı" gibi çok uzak bir yerde belirti verirdi
        ve oradan buraya geri izlemek saatler alırdı.
        """
        n = len(self.gunluk)
        if len(self.alt_band) != n or len(self.ust_band) != n:
            raise ValueError(
                f"gunluk({n}), alt_band({len(self.alt_band)}) ve "
                f"ust_band({len(self.ust_band)}) aynı uzunlukta olmalı"
            )
        for i, (alt, orta, ust) in enumerate(
            zip(self.alt_band, self.gunluk, self.ust_band, strict=True)
        ):
            if not (alt <= orta <= ust):
                raise ValueError(
                    f"{i}. günde bant sıralı değil: alt={alt}, tahmin={orta}, üst={ust}"
                )
        if any(d < 0 for d in self.alt_band):
            raise ValueError("talep negatif olamaz; alt bant 0'ın altına inmemeli")
        return self

    @property
    def ufuk_gun(self) -> int:
        return len(self.gunluk)

    @property
    def bitis(self) -> date:
        """Tahminin kapsadığı son gün (dâhil)."""
        return self.baslangic + timedelta(days=self.ufuk_gun - 1)

    def toplam(self) -> float:
        """Ufuk boyunca beklenen toplam talep.

        Üretim emri kararının doğrudan kullandığı sayı: "önümüzdeki 14 günde
        bu üründen ne kadar satılacak".
        """
        return float(sum(self.gunluk))

    def toplam_bandi(self) -> tuple[float, float]:
        """Ufuk toplamının alt ve üst sınırı.

        ⚠️ Günlük bantları toplamak, bağımsızlık varsayımı altında gerçek
        belirsizliği **abartır** (hatalar birbirini kısmen götürür). Yine de
        kasıtlı olarak böyle: üretim planında fazla temkinli olmak, az
        temkinli olmaktan ucuz. Daha dar bir bant istenirse hesabı buraya
        eklenir, çağıran tarafa değil — o zaman tek yerde düzelir.
        """
        return float(sum(self.alt_band)), float(sum(self.ust_band))


__all__ = ["VARSAYILAN_UFUK_GUN", "TalepTahmini"]
