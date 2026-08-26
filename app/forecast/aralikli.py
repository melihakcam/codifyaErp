"""Aralıklı talep tahmini — Croston ve SBA.

⚠️ Bu dosya **kataloğun %76'sı** için var (1525/2000 kalem günde 0,3'ten az
satıyor). Ölçüm şunu gösterdi:

    katman            kalem   hareketli  mevsimsel   ussel
    yavas (<0,3/gun)   1525      1,12       1,08     1,55

Klasik üssel düzleştirme yavaş kalemlerde naif tabandan **%55 kötü**. Sebebi
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

# Ampirik bant kuantilleri (%). Geniş ve simetrik olmayan bir dağılım için:
# aralıklı talepte gözlemler sıfırda yığılmış ve sağa çarpık, normal
# varsayımı tutmuyor — o yüzden kuantil, standart sapma değil.
ALT_KUANTIL = 10.0
UST_KUANTIL = 90.0


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


def _ampirik_bant(gecmis: list[float], ufuk: int) -> tuple[float, float] | None:
    """Geçmişteki gerçek `ufuk` günlük toplamların alt/üst kuantili.

    Kayan pencere kullanılıyor: pencereler örtüşüyor, yani gözlemler
    bağımsız değil. Kuantil bu yüzden bir olasılık iddiası değil, "bu kalem
    iki haftada tarihsel olarak şu aralıkta satmış" ifadesi — üretim kararı
    için sorulan soru da zaten bu.

    Yeterli pencere yoksa `None`; çağıran taraf o zaman bandı kurmaz.
    """
    if len(gecmis) < ufuk * 2:
        return None
    kumulatif = np.concatenate(([0.0], np.cumsum(np.asarray(gecmis, dtype=float))))
    toplamlar = kumulatif[ufuk:] - kumulatif[:-ufuk]
    return (
        float(np.percentile(toplamlar, ALT_KUANTIL)),
        float(np.percentile(toplamlar, UST_KUANTIL)),
    )


def _tahmin_kur(
    oran: float,
    buyuklukler: list[float],
    gecmis: list[float],
    kalem_id: str,
    baslangic: date,
    ufuk: int,
    yontem: str,
) -> TalepTahmini:
    """Sabit günlük oranı sözleşmeye çevirir.

    ⚠️ **Bant burada simetrik DEĞİL** ve bu bilinçli. Aralıklı seride
    günlerin çoğu gerçekten sıfır; alt bandı 0'ın üstüne çekmek "her gün
    en az şu kadar satılır" demek olurdu ve bu yanlış.

    ## ⚠️ Bant, OKUNDUĞU YERDE kalibre ediliyor

    İlk sürüm üst bandı "tipik bir talep gününün büyüklüğü" (büyüklüklerin
    %90'lık dilimi) olarak koyuyordu. Sözleşme bandı gün gün taşıdığı ve
    `toplam_bandi()` onları topladığı için bu, ufuk toplamında "**her gün**
    talep günü olsaydı" senaryosunu üretiyor: 10 günde bir 5 adet satan
    kalemde iki haftalık üst sınır 70 adet — gerçeğin on katı. Kararın
    okuduğu sayıda kalibre olmayan bir bant, emniyet payını okunamaz hâle
    getirir.

    Şimdiki bant geçmişteki **gerçek `ufuk` günlük toplamların** ampirik
    kuantillerinden kurulup ufka eşit dağıtılıyor. Böylece `toplam_bandi()`
    doğrudan kalibre; ölçümdeki **BANT KAPSAMA** satırı bunu sınıyor.

    `buyuklukler` yine de gerekiyor: seri bandı kuracak kadar uzun değilse
    tipik talep büyüklüğü tek makul üst sınır.
    """
    bant = _ampirik_bant(gecmis, ufuk)
    if bant is None:
        # Bandı uyduramayız. Tipik talep günü büyüklüğü üst sınır olarak
        # kalıyor — dar bir bant yazmak, belirsizliği ölçmüş gibi görünüp
        # ölçmemek olurdu.
        gun_ust = float(np.percentile(buyuklukler, 90)) if buyuklukler else oran
        alt_gun, ust_gun = 0.0, max(gun_ust, oran)
    else:
        # ⚠️ Kıyas GÜNLÜK değerler üzerinden: toplam üzerinden kıyaslayıp
        # sonra ufka bölmek, kayan noktada bir bit altta kalan bir üst bant
        # üretip sözleşmeyi patlatıyor (2.000 kalemin ilkinde yakalandı).
        #
        # Nokta tahmini bandın dışına düşerse bandı genişletiyoruz, tahmini
        # kırpmıyoruz — tahmini banda uydurmak ölçtüğümüz sayıyı bozardı.
        alt_gun = min(max(0.0, bant[0] / ufuk), oran)
        ust_gun = max(bant[1] / ufuk, oran)

    return TalepTahmini(
        kalem_id=kalem_id,
        baslangic=baslangic,
        gunluk=[oran] * ufuk,
        alt_band=[alt_gun] * ufuk,
        ust_band=[ust_gun] * ufuk,
        yontem=yontem,
        egitim_gun_sayisi=len(gecmis),
    )


def croston(gecmis: list[float], kalem_id: str, baslangic: date, ufuk: int) -> TalepTahmini:
    """Klasik Croston: büyüklük / aralık.

    Yeterli talep günü yoksa naif tabana düşülüyor — modelin yokluğunu
    sessizce "talep yok" diye raporlamak, üretim planında en tehlikeli hata.
    """
    z, x, buyuklukler = _croston_cekirdegi(gecmis, ALFA)
    if not x:
        return hareketli_ortalama(gecmis, kalem_id, baslangic, ufuk)
    return _tahmin_kur(z / x, buyuklukler, gecmis, kalem_id, baslangic, ufuk, "croston")


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
    return _tahmin_kur(duzeltilmis, buyuklukler, gecmis, kalem_id, baslangic, ufuk, "sba")


ARALIKLI_MODELLER = {"croston": croston, "sba": sba}
"""Ölçümde diğerleriyle yan yana koşturulacak aralıklı talep modelleri."""


__all__ = [
    "ALFA",
    "ALT_KUANTIL",
    "ARALIKLI_MODELLER",
    "ASGARI_TALEP_GUNU",
    "UST_KUANTIL",
    "croston",
    "sba",
]
