"""Üssel düzleştirme — trend + haftalık mevsim (Holt-Winters, toplamsal).

⚠️ Model seçimi keyfi değil, **veriyi taklit ediyor**. `simulator/demand.py`
talebi şöyle üretiyor:

    temel_hiz × trend × sezon × haftalık_desen × promo × gürültü

Holt-Winters tam olarak "seviye + trend + dönemsel desen" ayrıştırması
yapıyor. Yani buradaki model, verinin üretim sürecinin bildiğimiz yapısına
karşılık geliyor — rastgele seçilmiş bir "güçlü model" değil.

⚠️ Bu **iyi haber değil, dikkat gerektiren bir durum.** Simülasyonda
mükemmele yakın çıkması modelin gerçek veride de iyi olacağını göstermez;
yalnızca simülatörün varsayımlarını yakaladığını gösterir. Gerçek ölçüt
`app/adapters/csv_erp.py` yoluyla gelen gerçek hareket verisi olacak.
Simülasyon sonucu bir **üst sınır** olarak okunmalı.

Çarpımsal değil toplamsal mevsim kullanılıyor: talebin sıfır olduğu günler
var (aralıklı talep) ve çarpımsal ayrıştırma sıfıra bölmeye ya da sıfırda
çöken bir mevsim katsayısına yol açıyor.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from app.forecast.aralikli import ARALIKLI_MODELLER
from app.forecast.contracts import TalepTahmini
from app.forecast.taban import BANT_KATSAYISI, hareketli_ortalama

HAFTA = 7

# Düzleştirme katsayıları. Sabit — ölçüm tekrarlanabilir olsun diye.
#
# ⚠️ Kalem başına en iyi katsayıyı aramak (grid search) cazip ve şu an
# YANLIŞ olurdu: aynı veriyle hem katsayı seçip hem başarı ölçmek, ölçümü
# şişirir. Katsayı araması ancak ayrı bir doğrulama penceresiyle yapılabilir
# ve o, ölçüm hattı oturduktan sonraki iş.
ALFA = 0.25  # seviye — düşük tutuldu, günlük gürültüye kapılmasın
BETA = 0.05  # trend — çok düşük; talep trendi yavaş değişiyor
GAMMA = 0.30  # mevsim — hafta günü deseni görece kararlı

# Bu kadar günden az geçmişte Holt-Winters kurulamaz.
#
# İki tam hafta mevsim bileşenini kurmaya yetmez; en az üç hafta gerekli ki
# hafta günü ortalaması gürültüden ayrışsın. Altındaysa naif tabana düşülüyor
# — modelin yokluğunu sessizce sıfır talep diye raporlamak, üretim planında
# yapılabilecek en tehlikeli hata.
ASGARI_GECMIS_GUN = HAFTA * 3


def _mevsim_baslat(gecmis: list[float]) -> list[float]:
    """Hafta günü başına ortalama sapma (toplamsal mevsim bileşeni).

    Genel ortalamadan sapma olarak kuruluyor, oran olarak değil — modül
    docstring'indeki sıfır talep gerekçesi.
    """
    genel = float(np.mean(gecmis))
    mevsim = []
    for gun in range(HAFTA):
        ayni_gunler = gecmis[gun::HAFTA]
        mevsim.append(float(np.mean(ayni_gunler)) - genel if ayni_gunler else 0.0)
    return mevsim


def ussel_duzlestirme(
    gecmis: list[float], kalem_id: str, baslangic: date, ufuk: int
) -> TalepTahmini:
    """Holt-Winters ile `ufuk` günlük tahmin.

    Bant, modelin **geçmişteki kendi hatasından** kuruluyor (artıkların
    standart sapması) — sabit bir yüzde değil. Böylece öngörülemez kalemde
    bant kendiliğinden genişliyor, düzenli kalemde daralıyor. XYZ
    sınıflandırmasının söylediği şeyi model kendi hatasından öğreniyor.
    """
    if len(gecmis) < ASGARI_GECMIS_GUN:
        return hareketli_ortalama(gecmis, kalem_id, baslangic, ufuk)

    seviye = float(np.mean(gecmis[:HAFTA]))
    trend = 0.0
    mevsim = _mevsim_baslat(gecmis)
    artiklar: list[float] = []

    for i, gozlem in enumerate(gecmis):
        m = i % HAFTA
        beklenen = seviye + trend + mevsim[m]
        artiklar.append(gozlem - beklenen)

        onceki_seviye = seviye
        seviye = ALFA * (gozlem - mevsim[m]) + (1 - ALFA) * (seviye + trend)
        trend = BETA * (seviye - onceki_seviye) + (1 - BETA) * trend
        mevsim[m] = GAMMA * (gozlem - seviye) + (1 - GAMMA) * mevsim[m]

    # ⚠️ Artıkların ilk haftası atılıyor: model daha ısınmamışken yaptığı
    # hata, gelecekteki belirsizliği temsil etmiyor. Dâhil edilseydi bant
    # her kalemde haksız yere genişlerdi.
    kararli = artiklar[HAFTA:] or artiklar
    sapma = float(np.std(kararli))

    tahmin = []
    for adim in range(1, ufuk + 1):
        m = (len(gecmis) + adim - 1) % HAFTA
        deger = seviye + adim * trend + mevsim[m]
        # Negatif talep diye bir şey yok. Trend aşağıysa uzun ufukta
        # tahmin eksiye geçebilir; sözleşme de buna izin vermiyor.
        tahmin.append(max(0.0, float(deger)))

    yayilim = BANT_KATSAYISI * sapma
    return TalepTahmini(
        kalem_id=kalem_id,
        baslangic=baslangic,
        gunluk=tahmin,
        alt_band=[max(0.0, d - yayilim) for d in tahmin],
        ust_band=[d + yayilim for d in tahmin],
        yontem="ussel_duzlestirme",
        egitim_gun_sayisi=len(gecmis),
    )


MODELLER = {"ussel_duzlestirme": ussel_duzlestirme, **ARALIKLI_MODELLER}
"""Ölçümde tabanlarla yan yana koşturulacak modeller.

⚠️ Aralıklı talep modelleri (`aralikli.py`) buraya **kasıtlı** olarak
katılıyor: ölçüm hepsini aynı kesme tarihlerinde, aynı kalemlerde koşturmazsa
"hangi katmanda hangi yöntem" sorusu cevaplanamaz. Ayrı ölçüm hattı kurmak
iki farklı sayı üretir ve ikisi kıyaslanamaz."""


__all__ = ["ALFA", "ASGARI_GECMIS_GUN", "BETA", "GAMMA", "MODELLER", "ussel_duzlestirme"]
