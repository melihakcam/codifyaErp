"""Bir planın beklenen maliyeti — hangi planı önereceğimizin dayanağı.

Sahip: Kişi B · Faz 11 B11.1

## ⚠️ Öneri "bence" değil, hesap olmak zorunda

Sistem birkaç plan üretip birini öneriyor. Öneri bir şeye dayanmazsa "bence"
demiş olur ve kullanıcı haklı olarak dinlemez. Dayanacak sayılar profilde
**zaten tanımlı** (`app/core/isletme_profili.py::StokProfili`):

    stoktukenmesi_ceza_carpani  2,5   stok tukenmesi kayip karin kac kati
    yillik_elde_tutma_orani     0,25  erken uretilen mali tutmanin yillik bedeli
    siparis_maliyeti_tl         250   bir kurulumun sabit maliyeti

## ⚠️ Bu bir TAHMİN ve varsayımları açık

Her bileşenin altında bir varsayım var ve hiçbiri kanıtlanmadı. `varsayimlar`
listesi çıktının yanında basılıyor; tek bir "toplam maliyet" sayısına
indirgeyip tabloyu gizlemek, bu projede beş kez yaşanan **"sayı tek başına
yalan söyler"** hatasının tekrarı olurdu.

Maliyet planları **birbiriyle** karşılaştırmak için var. Mutlak değeri
("bu plan 180.000 TL'ye mal olur") ciddiye alınmamalı; aradaki fark
("B, A'dan 90.000 TL ucuz") anlamlı olan.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.isletme_profili import StokProfili, profil
from app.planlama.contracts import KaynakPlani

ETIKET_TUTAR = "tutar"

# Bir yıl kaç gün — elde tutma maliyeti yıllık orandan günlüğe çevriliyor.
YIL_GUN = 365.0


@dataclass(frozen=True)
class MaliyetKirilimi:
    """Planın maliyeti, bileşenlerine ayrılmış.

    ⚠️ Kırılım **zorunlu**, toplam tek başına yeterli değil. İki planın
    toplamı yakınsa hangi bileşenin farklı olduğu kararı değiştirir:
    stoksuzluktan gelen 50.000 TL ile elde tutmadan gelen 50.000 TL aynı
    şey değildir — biri müşteri kaybı, diğeri bağlı sermaye.
    """

    stoksuzluk_tl: float
    elde_tutma_tl: float
    kurulum_tl: float
    karsilanamayan_deger_tl: float
    yerlesen_is: int
    sigmayan_is: int
    varsayimlar: tuple[str, ...] = field(default_factory=tuple)

    @property
    def toplam_tl(self) -> float:
        return self.stoksuzluk_tl + self.elde_tutma_tl + self.kurulum_tl


def _tutar(etiketler: dict[str, str]) -> float:
    """İşin parasal karşılığı. Yoksa 0 — motor sözleşmesinde para alanı yok."""
    try:
        return float(etiketler.get(ETIKET_TUTAR, 0.0))
    except (TypeError, ValueError):
        return 0.0


def plan_maliyeti(
    planlar: list[KaynakPlani], stok_profili: StokProfili | None = None
) -> MaliyetKirilimi:
    """Bir planın beklenen maliyeti.

    ⚠️ Girdi **donmuş sözleşme** (`KaynakPlani`), motor değil. Bu fonksiyon
    `plan_kur`'u hiç çağırmıyor; testleri elle kurulmuş plan nesneleriyle
    yazılabiliyor ve motor tarafı bittiyse bitmediyse fark etmiyor.

    ### Bileşenler ve varsayımları

    **Stoksuzluk.** Ufka sığmayan iş, karşılamak için var olduğu talebi
    karşılamıyor. Kaybın büyüklüğü işin parasal değeri; ceza çarpanı
    (2,5) müşteri güveni ve acil tedarik gibi dolaylı maliyetleri temsil
    ediyor. ⚠️ *Varsayım: sığmayan her iş gerçekten stoksuzluğa yol açıyor.*
    Gerçekte bir kısmı ufuk dışında yetişir.

    **Elde tutma.** Erken biten iş, ihtiyaç anına kadar stokta bekliyor.
    ⚠️ *Varsayım: işin bittiği gün ile ufkun sonu arasındaki süre boyunca
    mal elde duruyor.* Gerçekte satış kademeli olur.

    **Kurulum.** Her iş bir kez kurulum gerektiriyor (hat değişimi, araç
    yükleme). ⚠️ *Varsayım: aynı kaynaktaki ardışık işler kurulum
    paylaşmıyor.* Gerçek çizelgelemede benzer işler gruplanıp bu maliyet
    düşürülür — motor bunu yapmıyor ve yapmadığı yazılı.
    """
    p = stok_profili or profil().stok

    yerlesen = [s for plan in planlar for s in plan.satirlar]
    sigmayan = [s for plan in planlar for s in plan.sigmayanlar]

    karsilanamayan = sum(_tutar(s.etiketler) for s in sigmayan)
    stoksuzluk = karsilanamayan * p.stoktukenmesi_ceza_carpani

    # Erken biten işin bekleme süresi: planın en geç bitişine kadar.
    # ⚠️ Ufuk sonu yerine "en geç bitiş" kullanılıyor — ufuk boş geçen
    # günleri de sayardı ve dolu olmayan bir hattı cezalandırırdı.
    tum_bitisler = [s.bitis for s in yerlesen]
    son_gun = max(tum_bitisler) if tum_bitisler else None
    elde_tutma = 0.0
    if son_gun is not None:
        for s in yerlesen:
            bekleme_gun = (son_gun - s.bitis).days
            elde_tutma += _tutar(s.etiketler) * p.yillik_elde_tutma_orani * bekleme_gun / YIL_GUN

    kurulum = len(yerlesen) * p.siparis_maliyeti_tl

    return MaliyetKirilimi(
        stoksuzluk_tl=round(stoksuzluk, 2),
        elde_tutma_tl=round(elde_tutma, 2),
        kurulum_tl=round(kurulum, 2),
        karsilanamayan_deger_tl=round(karsilanamayan, 2),
        yerlesen_is=len(yerlesen),
        sigmayan_is=len(sigmayan),
        varsayimlar=(
            f"sığmayan her iş stoksuzluğa yol açıyor (ceza ×{p.stoktukenmesi_ceza_carpani})",
            f"erken biten mal planın sonuna kadar stokta bekliyor (yıllık %"
            f"{p.yillik_elde_tutma_orani * 100:.0f})",
            f"her iş ayrı kurulum gerektiriyor ({p.siparis_maliyeti_tl:.0f} TL)",
        ),
    )


__all__ = ["MaliyetKirilimi", "plan_maliyeti"]
