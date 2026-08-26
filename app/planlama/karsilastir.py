"""Birkaç plan yan yana — karne ve gerekçeli öneri.

Sahip: Kişi B · Faz 11 B11.2

## ⚠️ Sistem "en iyi planı" bilmiyor; farkı gösteriyor

"En iyi" işe göre değişir. Bu yüzden aynı veriden birkaç plan üretiliyor ve
aralarındaki fark **sayıyla** konuluyor:

    yetisen is       41         47         38
    ufka sigmayan     8          2         11
    beklenen maliyet 180k      240k       310k

Bu tablo olmadan "hangi plan" sorusunun cevabı yok. Tabloyla birlikte cevap
on saniyede veriliyor.

## ⚠️ Öneri tabloyu GİZLEMİYOR

Sistem en düşük maliyetli planı işaretliyor ama tablo daima basılıyor. Öneri
bir tahmine dayanıyor (`maliyet.py`'nin varsayımları) ve o varsayımlar
kullanıcının göremediği bir yerde kalırsa, öneri "sayı tek başına yalan
söyler" hatasının yeni bir biçimi olur.

⚠️ Öğrenen öneri (kullanıcının seçtiğini hatırlayıp ona göre önerme)
**kapsam dışı**: geçmiş veri yok ve "ne öğrendiği" açıklanamaz hâle gelir.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.planlama.contracts import KaynakPlani
from app.planlama.maliyet import MaliyetKirilimi, plan_maliyeti


@dataclass(frozen=True)
class PlanKarnesi:
    """Tek bir planın karnesi."""

    olcut: str
    aciklama: str
    planlar: tuple[KaynakPlani, ...]
    maliyet: MaliyetKirilimi

    @property
    def doluluk(self) -> float:
        """Kaynakların ufuk boyunca ortalama doluluk oranı.

        ⚠️ Hesap `KaynakPlani.doluluk`'ta, burada değil. İlk sürümde burada
        yapılıyordu ve ufku bilmediği için %535 gibi sayılar üretiyordu —
        yük ufuk boyunca birikirken kapasite günlüktü. Sözleşmenin bildiği
        bir şeyi çağıran tarafta yeniden hesaplamak, tam olarak böyle
        hatalar üretir.
        """
        if not self.planlar:
            return 0.0
        return sum(p.doluluk for p in self.planlar) / len(self.planlar)


@dataclass(frozen=True)
class Karsilastirma:
    """Karneler + önerilen plan."""

    karneler: tuple[PlanKarnesi, ...]
    onerilen_olcut: str
    oneri_gerekcesi: str


def planlari_karsilastir(
    planlar_by_olcut: dict[str, list[KaynakPlani]],
    aciklamalar: dict[str, str] | None = None,
) -> Karsilastirma:
    """Ölçüt → plan sözlüğünü karneye çevirir ve birini önerir.

    ⚠️ Girdi zaten kurulmuş planlar; bu fonksiyon `plan_kur` çağırmıyor.
    Değerlendirme motordan bağımsız kalabilsin diye — testleri elle
    kurulmuş planlarla yazılabiliyor.
    """
    aciklamalar = aciklamalar or {}

    karneler = tuple(
        PlanKarnesi(
            olcut=olcut,
            aciklama=aciklamalar.get(olcut, olcut),
            planlar=tuple(planlar),
            maliyet=plan_maliyeti(planlar),
        )
        # ⚠️ Ölçüt adına göre sıralı: sözlük sırasına bırakmak, aynı girdiye
        # farklı sıralı bir tablo üretebilirdi.
        for olcut, planlar in sorted(planlar_by_olcut.items())
    )

    if not karneler:
        return Karsilastirma((), "", "Karşılaştırılacak plan yok.")

    # En düşük toplam maliyet. Eşitlikte ölçüt adı kırıyor — kararlı olsun.
    en_iyi = min(karneler, key=lambda k: (k.maliyet.toplam_tl, k.olcut))
    digerleri = [k for k in karneler if k.olcut != en_iyi.olcut]

    if digerleri:
        en_yakin = min(digerleri, key=lambda k: k.maliyet.toplam_tl)
        fark = en_yakin.maliyet.toplam_tl - en_iyi.maliyet.toplam_tl
        gerekce = (
            f'"{en_iyi.aciklama}" öneriliyor: beklenen toplam maliyeti '
            f'"{en_yakin.aciklama}" planından {fark:,.0f} TL düşük.'
            if fark > 0
            else f'"{en_iyi.aciklama}" öneriliyor: maliyetler eşit, ölçüt adı belirledi.'
        )
    else:
        gerekce = f'"{en_iyi.aciklama}" tek seçenek.'

    return Karsilastirma(karneler=karneler, onerilen_olcut=en_iyi.olcut, oneri_gerekcesi=gerekce)


def karne_metni(karsilastirma: Karsilastirma) -> str:
    """Karşılaştırmayı insan okunur tabloya çevirir.

    ⚠️ Varsayımlar tablonun altında **daima** basılıyor. Maliyet bir tahmin
    ve neye dayandığı görünmezse öneri sorgulanamaz hâle gelir.
    """
    if not karsilastirma.karneler:
        return karsilastirma.oneri_gerekcesi

    k = karsilastirma.karneler
    genislik = 18
    satirlar = ["", "PLAN KARŞILAŞTIRMASI", "=" * (22 + genislik * len(k))]

    def satir(baslik: str, degerler: list[str]) -> str:
        return f"  {baslik:<20}" + "".join(f"{d:>{genislik}}" for d in degerler)

    satirlar.append(satir("", [f'"{x.aciklama}"' for x in k]))
    satirlar.append("  " + "-" * (20 + genislik * len(k)))
    satirlar.append(satir("yerleşen iş", [str(x.maliyet.yerlesen_is) for x in k]))
    satirlar.append(satir("ufka sığmayan", [str(x.maliyet.sigmayan_is) for x in k]))
    satirlar.append(
        satir("karşılanamayan", [f"{x.maliyet.karsilanamayan_deger_tl:,.0f} TL" for x in k])
    )
    satirlar.append(satir("kaynak doluluğu", [f"{x.doluluk:.0%}" for x in k]))
    satirlar.append("")
    satirlar.append(satir("· stoksuzluk", [f"{x.maliyet.stoksuzluk_tl:,.0f} TL" for x in k]))
    satirlar.append(satir("· elde tutma", [f"{x.maliyet.elde_tutma_tl:,.0f} TL" for x in k]))
    satirlar.append(satir("· kurulum", [f"{x.maliyet.kurulum_tl:,.0f} TL" for x in k]))
    satirlar.append(satir("BEKLENEN MALİYET", [f"{x.maliyet.toplam_tl:,.0f} TL" for x in k]))

    satirlar += ["", f"  → {karsilastirma.oneri_gerekcesi}", "", "  ⚠️ Maliyet bir TAHMİN:"]
    satirlar += [f"     · {v}" for v in k[0].maliyet.varsayimlar]
    satirlar.append("     Mutlak değeri değil, planlar arasındaki FARK anlamlı.")
    return "\n".join(satirlar)


__all__ = ["Karsilastirma", "PlanKarnesi", "karne_metni", "planlari_karsilastir"]
