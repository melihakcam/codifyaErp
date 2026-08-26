"""Sevkiyat adaptörü — bir alanın çıktısı, başka alanın girdisi.

Sahip: Kişi A · Faz 13 A13.2

## Zincir bağının en küçük kanıtı

Üretim planı "hangi kalem, hangi hatta, ne kadar" diyor. Üretilen mal
sevk edilecek; yani üretimin çıktısı sevkiyatın **girdisi**.

    uretim isleri  ->  sevkiyat isleri  ->  arac atamasi

⚠️ Bu dosya üretimi **bilmiyor**. Gelen şey `Is` listesi — motorun ortak
dili. Yarın zincirin başına başka bir alan konursa (satın alma, montaj)
burası değişmez; `ornekler/sevkiyat.json` içindeki tek satır değişir.

## ⚠️ Sayılar koda gömülü değil

"Bir birim kaç saatte yüklenir", "her sevkiyatın sabit hazırlığı ne kadar"
— bunlar müşteriye göre değişir ve tanımdaki `parametreler` içinde durur.
Koda gömülseydi ikinci müşteri kod değişikliği isterdi; Faz 9'da aynı iş
işletme profili için yapılmıştı, aynı gerekçe.

## Bu adaptör ne YAPMIYOR

Rota kurmuyor, mesafe hesaplamıyor, durak sıralamıyor. Faz 13 kapsamı
**kapasite + uygunluk ataması** olarak karara bağlandı; coğrafi rota ayrı
bir çözücü ve ayrı bir ölçüm ister.
"""

from __future__ import annotations

from datetime import date

from app.planlama.contracts import Is
from app.planlama.tanim import AlanTanimi

# Tanımda yazılmazsa kullanılan değerler. ⚠️ Varsayılanın kendisi bir
# varsayım: "yükleme süresi taşınan miktarla orantılı". Gerçek müşteride
# palet/ağırlık kırılımı gelirse burası değil, tanım değişir.
VARSAYILAN_BIRIM_SAAT = 0.01
VARSAYILAN_SABIT_SAAT = 0.5
ETIKET_MIKTAR = "miktar"
ETIKET_KAYNAK_IS = "kaynak_is"


def _miktar(is_: Is) -> float:
    """Taşınacak miktar. Etiket yoksa işin yükü vekil ölçü olarak kullanılıyor."""
    ham = is_.etiketler.get(ETIKET_MIKTAR)
    if ham is None:
        return is_.yuk
    try:
        return float(ham)
    except (TypeError, ValueError):
        # ⚠️ Bozuk etiket planı durdurmuyor ama sessiz de kalmıyor: yük
        # vekil ölçüye düşüyor ve etiket çıktıda görünmeye devam ediyor.
        return is_.yuk


def isleri_uret(
    tanim: AlanTanimi,
    ufuk_gun: int,
    baslangic: date,
    kaynak_isler: tuple[Is, ...] = (),
) -> list[Is]:
    """Önceki alanın işlerini sevkiyata çevirir.

    Önceliği **devralıyor**: üretimde acil olan kalem sevkiyatta da acil.
    Ayrı bir aciliyet tanımı iki alanın birbiriyle çelişmesi demek olurdu.
    """
    birim_saat = tanim.sayi("birim_yukleme_saat", VARSAYILAN_BIRIM_SAAT)
    sabit_saat = tanim.sayi("sabit_hazirlik_saat", VARSAYILAN_SABIT_SAAT)
    uygun = tuple(k.kaynak_id for k in tanim.kaynaklar)

    isler: list[Is] = []
    for kaynak_is in kaynak_isler:
        yuk = sabit_saat + _miktar(kaynak_is) * birim_saat
        isler.append(
            Is(
                is_id=f"SVK-{kaynak_is.is_id}",
                ad=f"Sevkiyat · {kaynak_is.ad}",
                yuk=round(yuk, 4),
                oncelik=kaynak_is.oncelik,
                # ⚠️ Araç atanmıyor, aday listesi veriliyor: "şu araç şuraya
                # gidebilir" sorusunun cevabı plana ait bir karar.
                uygun_kaynaklar=uygun,
                etiketler={**kaynak_is.etiketler, ETIKET_KAYNAK_IS: kaynak_is.is_id},
            )
        )
    return isler


__all__ = ["ETIKET_KAYNAK_IS", "VARSAYILAN_BIRIM_SAAT", "VARSAYILAN_SABIT_SAAT", "isleri_uret"]
