"""Aralıklı talep tahmini — Croston ve SBA.

⚠️ Bu dosya **kataloğun %76'sı** için var. Ölçüm şunu gösterdi:

    katman            kalem   hareketli  mevsimsel   ussel
    yavas (<0,3/gun)   1530      0,77       0,52     1,49

Klasik üssel düzleştirme yavaş kalemlerde naif tabandan **%49 kötü**. Sebebi
model ailesinin yanlış olması, ayarın kötü olması değil.

## Neden klasik düzleştirme burada çöküyor

Günlük seri şöyle görünüyor:

    0 0 0 0 3 0 0 0 0 0 0 2 0 0 0 0 0 0 0 4 0 0 ...

Üssel düzleştirme her günü bir gözlem sayar ve sıfırlar seviyeyi aşağı
çeker; talep günü gelince yukarı sıçrar. Sonuç, hiçbir günü doğru
tahmin etmeyen sürekli oynayan bir seviye.

## Croston'un fikri

Seriyi **iki ayrı seriye** böl:

    buyukluk : 3, 2, 4, ...        (yalnizca talep gunleri)
    aralik   : 7, 6, 8, ...        (talepler arasi gun sayisi)

İkisini ayrı ayrı düzleştir, sonra oranla:

    gunluk_tahmin = duzlestirilmis_buyukluk / duzlestirilmis_aralik

Sıfırlar artık seviyeyi bozmuyor; "ne kadar" ile "ne sıklıkta" ayrı
öğreniliyor.

## SBA neden var

Croston tahmininin **yukarı yanlı** olduğu biliniyor: oranın beklenen değeri,
beklenen değerlerin oranına eşit değil (Jensen eşitsizliği). Syntetos-Boylan
düzeltmesi bunu `(1 - alfa/2)` katsayısıyla telafi ediyor.

⚠️ Üretim planında yanlılığın yönü önemli: yukarı yanlı tahmin **fazla
üretime** yol açar. Fazla üretim, eksik üretimden ucuz olabilir ama bunun
kararı politika katmanının (emniyet payı), tahmin katmanının değil. Tahmin
yansız olmalı, temkin ayrı bir düğme.

İkisi de ölçüme giriyor; hangisinin kazandığını sayı söyleyecek.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from app.forecast.contracts import TalepTahmini
from app.forecast.taban import hareketli_ortalama

# Düzleştirme katsayısı. Literatürde aralıklı talep için 0,1-0,2 aralığı
# öneriliyor; yavaş serilerde gözlem az olduğu için düşük tutmak gerekiyor.
# `model.py`'deki ALFA'dan (0,25) ayrı — orada günlük gözlem var, burada
# yalnızca talep günlerinde güncelleme oluyor.
ALFA = 0.15

# Bu kadar talep günü görülmeden Croston kurulamaz: iki nokta arasından
# "aralık" çıkarmak için en az iki talep günü şart, güvenilir bir ortalama
# için daha fazlası.
ASGARI_TALEP_GUNU = 3


def _croston_cekirdegi(gecmis: list[float], alfa: float) -> tuple[float, float, list[float]]:
    """Düzleştirilmiş (büyüklük, aralık) ve talep büyüklükleri.

    ⚠️ Güncelleme **yalnızca talep günlerinde** yapılıyor. Sıfır günlerinde
    güncellemek Croston'u klasik düzleştirmeye geri çevirirdi ve tüm
    kazanımı yok ederdi — yöntemin özü bu.
    """
    buyuklukler = [d for d in gecmis if d > 0]
    if len(buyuklukler) < ASGARI_TALEP_GUNU:
        return 0.0, 0.0, buyuklukler

    # ⚠️ BAŞLANGIÇ DEĞERİ AMPİRİK ORTALAMADAN — ilk gözlemden DEĞİL.
    #
    # İlk sürüm `x`'i "serinin başından ilk talebe kadar geçen gün" ile
    # başlatıyordu. Talep 0. güne denk gelirse `x=1` çıkıyor, yani "her gün
    # talep var" — seyrek bir seride oranı katbekat şişiriyor. `alfa=0,15`
    # ile bu başlangıç kolay sönmüyor: sönmesi için ~7 talep olayı gerekiyor
    # ve yavaş kalemlerde toplam talep günü zaten o mertebede.
    #
    # Ampirik ortalama hem yansız hem kararlı: `z0` ortalama talep
    # büyüklüğü, `x0` ortalama talepler arası gün.
    #
    # ⚠️ DÜZELTME KAYDI — bu değişiklik yanlış bir teşhisle yapıldı.
    # Ölçümde Croston +%91 yukarı yanlı görünmüştü ve SBA'nın varlık sebebi
    # yanlılığı düşürmek olduğu için bu teoriye aykırıydı; ilk şüphe (doğru
    # olarak) kendi koduma yöneldi ve başlangıç değeri düzeltildi.
    #
    # Ama sayı neredeyse hiç oynamadı (+%91 → +%94). Asıl sebep başkaydı:
    # **ölçüm yalnızca serinin son üç penceresinden örnek alıyordu** ve o
    # dönemde talep düşüktü, dolayısıyla HER yöntem yukarı yanlı görünüyordu
    # (`hareketli_ortalama` bile +%87). Kesmeler seriye yayılınca Croston
    # +%2'ye indi — teorinin söylediği yere.
    #
    # Düzeltme yine de duruyor: ampirik başlangıç standart ve daha sağlam.
    # Ama sebebi "yanlılığı düzeltti" değil; o iddia yanlıştı. Ölçüm
    # penceresinin kendisi bulguyu üretiyordu (bkz. `kesme_tarihleri`).
    z = float(np.mean(buyuklukler))
    x = len(gecmis) / len(buyuklukler)
    ilk = next(i for i, d in enumerate(gecmis) if d > 0)
    bekleyen = 1

    for gozlem in gecmis[ilk + 1 :]:
        if gozlem > 0:
            z = alfa * gozlem + (1 - alfa) * z
            x = alfa * bekleyen + (1 - alfa) * x
            bekleyen = 1
        else:
            bekleyen += 1

    return z, x, buyuklukler


def _tahmin_kur(
    oran: float,
    buyuklukler: list[float],
    kalem_id: str,
    baslangic: date,
    ufuk: int,
    yontem: str,
    gecmis_gun: int,
) -> TalepTahmini:
    """Sabit günlük oranı sözleşmeye çevirir.

    ⚠️ **Bant burada simetrik DEĞİL** ve bu bilinçli. Aralıklı seride
    günlerin çoğu gerçekten sıfır; alt bandı 0'ın üstüne çekmek "her gün
    en az şu kadar satılır" demek olurdu ve bu yanlış.

    Üst bant, tipik bir talep gününün büyüklüğü: "çoğu gün hiçbir şey
    satılmaz, satıldığında bu mertebede olur." Üretim planı için doğru bilgi
    bu — ortalamanın etrafına dar bir bant koymak, aralıklı talebin
    doğasını gizlerdi.

    `TalepTahmini.toplam_bandi()` ufuk toplamını verirken bu günlük
    bantları topluyor; aralıklı seride üst sınır böylece "her gün satış
    olsaydı" senaryosuna yaklaşıyor. Kasıtlı olarak temkinli.
    """
    ust = float(np.percentile(buyuklukler, 90)) if buyuklukler else oran
    return TalepTahmini(
        kalem_id=kalem_id,
        baslangic=baslangic,
        gunluk=[oran] * ufuk,
        alt_band=[0.0] * ufuk,
        ust_band=[max(ust, oran)] * ufuk,
        yontem=yontem,
        egitim_gun_sayisi=gecmis_gun,
    )


def croston(gecmis: list[float], kalem_id: str, baslangic: date, ufuk: int) -> TalepTahmini:
    """Klasik Croston: büyüklük / aralık.

    Yeterli talep günü yoksa naif tabana düşülüyor — modelin yokluğunu
    sessizce "talep yok" diye raporlamak, üretim planında en tehlikeli hata.
    """
    z, x, buyuklukler = _croston_cekirdegi(gecmis, ALFA)
    if not x:
        return hareketli_ortalama(gecmis, kalem_id, baslangic, ufuk)
    return _tahmin_kur(z / x, buyuklukler, kalem_id, baslangic, ufuk, "croston", len(gecmis))


def sba(gecmis: list[float], kalem_id: str, baslangic: date, ufuk: int) -> TalepTahmini:
    """Syntetos-Boylan: Croston'un yukarı yanlılığı düzeltilmiş hâli.

    Düzeltme katsayısı `(1 - alfa/2)`. Croston'un oranı beklenen değerlerin
    oranı değil, oranın beklenen değeri olduğu için yukarı kayıyor; bu
    katsayı onu geri çekiyor.
    """
    z, x, buyuklukler = _croston_cekirdegi(gecmis, ALFA)
    if not x:
        return hareketli_ortalama(gecmis, kalem_id, baslangic, ufuk)
    duzeltilmis = (1 - ALFA / 2) * (z / x)
    return _tahmin_kur(duzeltilmis, buyuklukler, kalem_id, baslangic, ufuk, "sba", len(gecmis))


ARALIKLI_MODELLER = {"croston": croston, "sba": sba}
"""Ölçümde diğerleriyle yan yana koşturulacak aralıklı talep modelleri."""


__all__ = ["ALFA", "ARALIKLI_MODELLER", "ASGARI_TALEP_GUNU", "croston", "sba"]
