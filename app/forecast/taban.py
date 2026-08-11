"""Naif tahmin tabanları — karmaşıklığın gerekçesi.

⚠️ Bu dosyadaki modeller **iyi olmak için değil, sınır çizmek için** var.

Bir tahmin modelinin "iyi" olduğunu söylemek ancak bir şeye göre mümkün.
Mutlak hata (MAE) tek başına anlamsız: günde 2 adet satan bir kalemde
MAE=1,5 felaket, günde 500 satan kalemde mükemmel. Bu yüzden ölçüm
`olcum.py`'de **MASE** kullanıyor — hatanın naif tabana oranı.

Karmaşık model naif tabanı geçemiyorsa, doğru karar onu atmaktır. Bunu
söyleyebilmek için tabanın kodda ve ölçümde durması gerekiyor.

Router taban çizgisinde aynı disiplin vardı (`training/eval/router_taban.py`):
eğitim öncesi sayı kaydedilmeseydi "eğitim işe yaradı mı" sorusu kalıcı
olarak cevapsız kalırdı.
"""

from __future__ import annotations

import statistics
from datetime import date

import numpy as np

from app.forecast.contracts import TalepTahmini

# Hareketli ortalamanın baktığı gün sayısı.
#
# 28 seçildi: haftalık desen dört kez tekrar ettiği için hafta günü etkisi
# ortalamada sönümleniyor. 7 alsaydık taban, tahmin ettiği güne denk gelen
# hafta gününden bağımsız tek bir sayı üretirdi ve haftalık deseni olan bir
# seride haksız yere kötü görünürdü — taban çizgiyi zayıflatmak, üstüne
# kurulan modeli olduğundan iyi gösterir.
HAREKETLI_PENCERE_GUN = 28

# Mevsimsel naif kaç gün geriye bakıyor. 364 = 52 tam hafta; 365 değil.
#
# ⚠️ 365 kullanmak hafta gününü kaydırır (geçen yılın aynı tarihi farklı bir
# hafta gününe düşer) ve haftalık deseni olan seride tahmini bozar. 364, hem
# yıllık mevsimi hem hafta gününü hizalı tutuyor.
MEVSIMSEL_GERI_GUN = 364

# Bant genişliği: tahmin ± bu katsayı × geçmiş standart sapma.
#
# 1,28 tek taraflı %90 normal kuantili. Kesin bir olasılık iddiası DEĞİL —
# talep normal dağılmıyor (aralıklı talepte sıfır yığılması var). Amaç
# "belirsizlik şu mertebede" demek; gerçek kalibrasyon ölçüldükten sonra
# ayarlanır.
BANT_KATSAYISI = 1.28


def _bant_kur(
    tahmin: list[float], sapma: float, kalem_id: str, baslangic: date, yontem: str, gecmis_gun: int
) -> TalepTahmini:
    """Nokta tahmininin etrafına simetrik bant koyar ve sözleşmeyi kurar.

    Alt bant 0'ın altına inmiyor: negatif talep diye bir şey yok ve
    sözleşme de buna izin vermiyor.
    """
    yayilim = BANT_KATSAYISI * sapma
    return TalepTahmini(
        kalem_id=kalem_id,
        baslangic=baslangic,
        gunluk=tahmin,
        alt_band=[max(0.0, d - yayilim) for d in tahmin],
        ust_band=[d + yayilim for d in tahmin],
        yontem=yontem,
        egitim_gun_sayisi=gecmis_gun,
    )


def hareketli_ortalama(
    gecmis: list[float], kalem_id: str, baslangic: date, ufuk: int
) -> TalepTahmini:
    """Son `HAREKETLI_PENCERE_GUN` günün ortalaması, ufuk boyunca sabit.

    En basit anlamlı taban. Trendi ve haftalık deseni **göremez** — zaten
    amacı bu: bunları gören bir model burayı geçmeli.
    """
    pencere = gecmis[-HAREKETLI_PENCERE_GUN:] if gecmis else [0.0]
    ortalama = float(np.mean(pencere))
    sapma = float(np.std(pencere)) if len(pencere) > 1 else 0.0
    return _bant_kur(
        [ortalama] * ufuk, sapma, kalem_id, baslangic, "hareketli_ortalama", len(gecmis)
    )


def mevsimsel_naif(gecmis: list[float], kalem_id: str, baslangic: date, ufuk: int) -> TalepTahmini:
    """Geçen yılın aynı gününü tekrarlar (364 gün geri).

    Yıllık mevsimi ve hafta gününü birlikte yakalayan en ucuz yöntem.
    ⚠️ Bir yıldan kısa geçmişte kullanılamaz; o durumda hareketli ortalamaya
    düşülüyor. Sessizce sıfır döndürmek, veri yokluğunu "talep yok" diye
    raporlamak olurdu — üretim planında en tehlikeli yanlış bu.
    """
    if len(gecmis) < MEVSIMSEL_GERI_GUN + ufuk:
        return hareketli_ortalama(gecmis, kalem_id, baslangic, ufuk)

    # `gecmis`'in sonu bugüne bitişik; geçen yılın karşılık gelen dilimi:
    basla = len(gecmis) - MEVSIMSEL_GERI_GUN
    dilim = gecmis[basla : basla + ufuk]
    artik = [
        simdi - onceki
        for simdi, onceki in zip(gecmis[-ufuk:], gecmis[basla - ufuk : basla], strict=False)
    ]
    sapma = float(statistics.pstdev(artik)) if len(artik) > 1 else 0.0
    return _bant_kur(
        [float(d) for d in dilim], sapma, kalem_id, baslangic, "mevsimsel_naif", len(gecmis)
    )


def naif_hata_olcegi(gecmis: list[float], mevsim: int = 7) -> float:
    """MASE'nin paydası: mevsimsel naif tahminin geçmişteki ortalama hatası.

    ⚠️ Ölçeği **eğitim penceresinden** hesaplamak zorunlu, test
    penceresinden değil. Test verisinden hesaplanan bir ölçek, test
    dönemindeki oynaklığı bölene taşır ve modeli olduğundan iyi ya da kötü
    gösterir — sızıntının ince biçimi.

    `mevsim=7`: bir önceki aynı hafta gününe göre fark. Günlük perakende
    talebinde en güçlü tekrar haftalık.

    0 dönerse (seride hiç değişim yok) çağıran taraf MASE hesaplamamalı;
    bölme tanımsız olur ve 0'a bölmek yerine o kalem ölçüm dışı bırakılır.
    """
    if len(gecmis) <= mevsim:
        return 0.0
    farklar = [abs(gecmis[i] - gecmis[i - mevsim]) for i in range(mevsim, len(gecmis))]
    return float(np.mean(farklar)) if farklar else 0.0


TABANLAR = {
    "hareketli_ortalama": hareketli_ortalama,
    "mevsimsel_naif": mevsimsel_naif,
}
"""Ölçümde otomatik koşturulacak tabanlar. Yeni bir taban buraya eklenince
ölçüm raporunda kendiliğinden görünür."""


__all__ = [
    "BANT_KATSAYISI",
    "HAREKETLI_PENCERE_GUN",
    "MEVSIMSEL_GERI_GUN",
    "TABANLAR",
    "hareketli_ortalama",
    "mevsimsel_naif",
    "naif_hata_olcegi",
]
