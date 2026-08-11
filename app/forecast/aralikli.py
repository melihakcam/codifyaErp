"""Aralıklı talep — Croston ve SBA.

Sahip: Kişi B · Faz 10 · B10.2

⚠️ Bu dosya bir **ölçüm bulgusunun** cevabı. Adım 1-2'de üssel düzleştirme
yavaş kalemlerde naif tabandan %49 kötü çıktı (`olcum.py::KATMAN_UYARISI`).
Sebep model kalitesi değil, **model ailesi**: Holt-Winters "her gün bir miktar
satış var" varsayar. Kataloğun %76'sında ise seri çoğu gün sıfır, arada bir
toplu satış — simülatörün kendisi de o kalemler için ayrı bir süreç kullanıyor
(`simulator/demand.py::_aralikli_talep_uret`, Bernoulli(gün) × miktar).

Croston tam bu yapıyı ayrıştırıyor: **talep büyüklüğü** ile **talepler arası
süre** ayrı ayrı düzleştirilir, tahmin ikisinin oranıdır.

    gunluk_hiz = z / p        z: ortalama talep buyuklugu
                              p: talepler arasi ortalama gun

SBA (Syntetos-Boylan) aynı hesabın yanlılığı düzeltilmiş hâli: Croston'ın
`z/p` oranı beklenen değerde **yukarı yanlıdır** (bir oranın beklentisi,
beklentilerin oranı değildir). `(1 - alfa/2)` çarpanı bu yanlılığı kapatıyor.

## ⚠️ Bant neden gün gün değil, ufuk toplamından kuruluyor

Diğer modellerde bant "tahmin ± katsayı × günlük sapma" biçiminde kuruluyor
ve `toplam_bandi()` bunları topluyor. Aralıklı seride bu **anlamsız** bir
sayı üretir: günde 0,07 satan bir kalemde günlük sapma 1,3 civarıdır, yani
bant "günde ±1,7 adet" der — kalemin iki haftalık toplam satışının 12 katı.

Burada bant, geçmişteki **gerçek `ufuk` günlük toplamların** ampirik
kuantillerinden kuruluyor ve ufka eşit dağıtılıyor. Böylece
`toplam_bandi()` — üretim emri kuralının gerçekten okuduğu sayı — doğrudan
kalibre edilmiş oluyor. Bandın okunduğu yerde kalibre etmek, başka bir yerde
kalibre edip toplarken bozmaktan iyi.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from app.forecast.contracts import TalepTahmini
from app.forecast.taban import hareketli_ortalama

# Düzleştirme katsayısı. Croston literatüründe 0,05-0,20 aralığı önerilir;
# aralıklı seride gözlem seyrek olduğu için yüksek alfa tek bir satışa aşırı
# tepki verir.
#
# ⚠️ Kalem başına en iyi alfayı aramak şu an YANLIŞ olurdu: aynı veriyle hem
# katsayı seçip hem başarı ölçmek ölçümü şişirir (`model.py`'de aynı gerekçe).
ARALIKLI_ALFA = 0.1

# Croston kurulabilmesi için gereken en az pozitif gün sayısı. İki pozitif
# gün olmadan "talepler arası süre" diye bir şey yok — tek satıştan aralık
# çıkarılamaz.
ASGARI_POZITIF_GUN = 3

# Ampirik bant kuantilleri (%). Simetrik ve geniş: aralıklı talepte dağılım
# sıfırda yığılmış ve sağa çarpık, normal varsayımı tutmuyor.
ALT_KUANTIL = 10.0
UST_KUANTIL = 90.0


def _croston_cekirdek(gecmis: list[float], alfa: float) -> tuple[float, float]:
    """Talep büyüklüğü (z) ve talepler arası süre (p) tahminleri.

    ⚠️ Düzleştirme **yalnızca satış olan günlerde** güncelleniyor. Klasik
    üssel düzleştirmenin aralıklı seride çökme sebebi tam bu: sıfır günleri
    de güncelleme sayıp seviyeyi sürekli sıfıra çekiyor, sonra tek bir satış
    onu yukarı fırlatıyor.
    """
    z = 0.0
    p = 0.0
    ilk = True
    aradan_gecen = 0

    for gozlem in gecmis:
        aradan_gecen += 1
        if gozlem <= 0:
            continue
        if ilk:
            z, p, ilk = gozlem, float(aradan_gecen), False
        else:
            z = alfa * gozlem + (1 - alfa) * z
            p = alfa * aradan_gecen + (1 - alfa) * p
        aradan_gecen = 0

    return z, p


def _ampirik_bant(gecmis: list[float], ufuk: int) -> tuple[float, float] | None:
    """Geçmişteki `ufuk` günlük toplamların alt/üst kuantili.

    Kayan pencere kullanılıyor: pencereler örtüşüyor, yani gözlemler bağımsız
    değil. Kuantil tahmini bu yüzden bir olasılık iddiası değil, "bu kalem
    iki haftada tarihsel olarak şu aralıkta satmış" ifadesi — üretim kararı
    için sorulan soru da zaten bu.

    Yeterli pencere yoksa `None`; çağıran taraf o zaman bandı kurmaz.
    """
    if len(gecmis) < ufuk * 2:
        return None
    dizi = np.asarray(gecmis, dtype=float)
    kumulatif = np.concatenate(([0.0], np.cumsum(dizi)))
    toplamlar = kumulatif[ufuk:] - kumulatif[:-ufuk]
    return float(np.percentile(toplamlar, ALT_KUANTIL)), float(
        np.percentile(toplamlar, UST_KUANTIL)
    )


def _tahmini_kur(
    gunluk_hiz: float,
    gecmis: list[float],
    kalem_id: str,
    baslangic: date,
    ufuk: int,
    yontem: str,
) -> TalepTahmini:
    """Sabit günlük hızı ufka yayar, bandı ufuk toplamından kurar."""
    toplam = gunluk_hiz * ufuk
    bant = _ampirik_bant(gecmis, ufuk)
    if bant is None:
        # Bandı uyduramayız. Nokta tahmininin etrafında ±%100: dar bir bant
        # yazmak, belirsizliği ölçmüş gibi görünüp ölçmemek olurdu.
        alt_toplam, ust_toplam = 0.0, toplam * 2
    else:
        alt_toplam, ust_toplam = bant

    # ⚠️ Nokta tahmini bandın dışına düşebilir (geçmiş pencereler ile
    # düzleştirilmiş hız farklı şeyler ölçüyor). Sözleşme alt <= tahmin <= üst
    # istiyor; bandı genişletiyoruz, tahmini kırpmıyoruz — tahmini banda
    # uydurmak, ölçtüğümüz sayıyı bozmak olurdu.
    #
    # Kıyas GÜNLÜK değerler üzerinden: toplam üzerinden kıyaslayıp sonra
    # ufka bölmek, kayan noktada bir bit altta kalan bir üst bant üretip
    # sözleşmeyi patlatıyor (ölçümde 2.000 kalemin ilkinde yakalandı).
    alt_gun = min(max(0.0, alt_toplam / ufuk), gunluk_hiz)
    ust_gun = max(ust_toplam / ufuk, gunluk_hiz)

    return TalepTahmini(
        kalem_id=kalem_id,
        baslangic=baslangic,
        gunluk=[gunluk_hiz] * ufuk,
        alt_band=[alt_gun] * ufuk,
        ust_band=[ust_gun] * ufuk,
        yontem=yontem,
        egitim_gun_sayisi=len(gecmis),
    )


def _hiz_hesapla(gecmis: list[float], alfa: float) -> float | None:
    """Croston günlük hızı; kurulamıyorsa `None`."""
    if sum(1 for d in gecmis if d > 0) < ASGARI_POZITIF_GUN:
        return None
    z, p = _croston_cekirdek(gecmis, alfa)
    if p <= 0:
        return None
    return z / p


def croston(
    gecmis: list[float], kalem_id: str, baslangic: date, ufuk: int, alfa: float = ARALIKLI_ALFA
) -> TalepTahmini:
    """Klasik Croston (1972).

    ⚠️ Yeterli pozitif gün yoksa hareketli ortalamaya düşülüyor. Sessizce
    sıfır döndürmek, veri yokluğunu "talep yok" diye raporlamak olurdu —
    üretim planında yapılabilecek en tehlikeli hata (`taban.py` ile aynı
    gerekçe).
    """
    hiz = _hiz_hesapla(gecmis, alfa)
    if hiz is None:
        return hareketli_ortalama(gecmis, kalem_id, baslangic, ufuk)
    return _tahmini_kur(hiz, gecmis, kalem_id, baslangic, ufuk, "croston")


def sba(
    gecmis: list[float], kalem_id: str, baslangic: date, ufuk: int, alfa: float = ARALIKLI_ALFA
) -> TalepTahmini:
    """Syntetos-Boylan Approximation — yanlılığı düzeltilmiş Croston.

    Croston'ın `z/p` oranı yukarı yanlı; `(1 - alfa/2)` çarpanı bunu kapatır.
    Fark küçük görünür (alfa=0,1'de %5) ama sistematiktir: her kalemde aynı
    yönde. Üretim emrinde sistematik yukarı sapma = sürekli fazla üretim.
    """
    hiz = _hiz_hesapla(gecmis, alfa)
    if hiz is None:
        return hareketli_ortalama(gecmis, kalem_id, baslangic, ufuk)
    return _tahmini_kur(hiz * (1 - alfa / 2), gecmis, kalem_id, baslangic, ufuk, "sba")


ARALIKLI_MODELLER = {"croston": croston, "sba": sba}
"""Ölçümde tabanlarla yan yana koşturulacak aralıklı talep modelleri."""


__all__ = [
    "ALT_KUANTIL",
    "ARALIKLI_ALFA",
    "ARALIKLI_MODELLER",
    "ASGARI_POZITIF_GUN",
    "UST_KUANTIL",
    "croston",
    "sba",
]
