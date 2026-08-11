"""Üretim emri kuralları — saf fonksiyonlar, aynı girdi aynı çıktı.

Sahip: Kişi A · Faz 10 A10.2

Stok sipariş kuralının ikizi ama iki yerde bilinçli olarak ayrışıyor:

· **ihtiyaç**: stokta ROP (ort. talep × tedarik süresi + emniyet stoğu),
  üretimde tahminin **üst bandı** × emniyet çarpanı.
· **miktar**: stokta EOQ → MOQ + paket katı, üretimde parti katı + azami
  parti sınırı.

## ⚠️ Neden ROP formülü kopyalanmadı

ROP, talebin ortalaması ve standart sapmasıyla çalışır ve normal dağılım
varsayar. Üretilen kalemlerin bir kısmı aralıklı talepli ve orada bu
varsayım tutmuyor: dağılım sıfırda yığılmış ve sağa çarpık.

`app/forecast` zaten bu soruyu ölçerek cevaplamış durumda ve bandı ampirik
kuantillerden kuruyor — yani "bu kalem 14 günde tarihsel olarak en fazla
şu kadar sattı" bilgisi elimizde. Onun üstüne bir de normal varsayımlı
emniyet stoğu hesaplamak, ölçülmüş bir sayının yerine varsayılmış bir
sayı koymak olurdu.
"""

from __future__ import annotations

import math

from app.contracts import UretimOzellikleri
from app.core.isletme_profili import UretimProfili


def ihtiyac_hesapla(ozellik: UretimOzellikleri, profil: UretimProfili) -> float:
    """Ufuk boyunca karşılanması gereken talep.

    ⚠️ Nokta tahminine (`tahmin_toplam`) değil **üst banda** bakılıyor.
    Ölçülmüş gerekçe: kataloğun büyük kısmı aralıklı talepli ve orada nokta
    tahmini kararın dayanabileceği bir sayı değil
    (`app/forecast/olcum.py::TOPLAM_UYARISI`). Emniyet payı, bandın
    genişliğinden geliyor — öngörülemez kalemde kendiliğinden büyüyor,
    düzenli kalemde küçülüyor.
    """
    return ozellik.tahmin_ust_band * profil.emniyet_bant_carpani


def acik_hesapla(ozellik: UretimOzellikleri, profil: UretimProfili) -> float:
    """İhtiyaç − net pozisyon. Pozitifse üretilmesi gereken var."""
    return ihtiyac_hesapla(ozellik, profil) - ozellik.net_pozisyon


def emir_miktari_hesapla(acik: float, ozellik: UretimOzellikleri, profil: UretimProfili) -> int:
    """Açığı kapatan, parti politikasına uyan emir miktarı.

    Gerçek hatta 1.187 adet üretilmez, 1.200 üretilir. Yuvarlama **yukarı**:
    aşağı yuvarlamak açığı kapatmayan bir emir önermek olurdu ve karar kendi
    gerekçesini çürütürdü.

    ⚠️ Azami sınır bir makuliyet kapısı, optimizasyon değil. Bozuk bir
    tahmin — ya da bir kez yaşandığı gibi bozuk bir **ölçüm** — hattı
    aylarca dolduracak bir emir önerebilir. Üst sınıra dayanmış bir öneri,
    sayının kendisinden çok daha erken fark edilir.
    """
    if acik <= 0:
        return 0

    if not profil.parti_katina_yuvarla:
        miktar = max(math.ceil(acik), ozellik.asgari_parti)
        return min(miktar, ozellik.parti_buyuklugu * profil.azami_emir_parti_sayisi)

    parti_sayisi = max(1, math.ceil(acik / ozellik.parti_buyuklugu))
    parti_sayisi = min(parti_sayisi, profil.azami_emir_parti_sayisi)
    miktar = parti_sayisi * ozellik.parti_buyuklugu
    return max(miktar, ozellik.asgari_parti)


def emir_ekonomik_mi(miktar: int, ozellik: UretimOzellikleri, profil: UretimProfili) -> bool:
    """Emir, hattı kurmaya değecek kadar uzun bir dönemi karşılıyor mu?

    Hazırlık süresi (setup) sabit bir maliyet: hat bu kaleme geçirilirken
    başka bir şey üretilmiyor. Bir günlük talebi karşılamak için hattı
    kurmak, o sabit maliyeti çok az adede yaymak demektir.

    ⚠️ Talep tahmini 0 olan kalemde bu soru **sorulamaz** — sıfıra bölünür.
    O durumda karar zaten "aksiyon yok" koluna gitmiş oluyor; buraya
    düşerse ekonomik saymak doğru: açık varsa ve talep tahmini yoksa,
    ertelemenin dayanağı da yok.
    """
    gunluk_tahmin = ozellik.tahmin_toplam / ozellik.tahmin_ufuk_gun
    if gunluk_tahmin <= 0:
        return True
    return miktar / gunluk_tahmin >= profil.asgari_emir_gun


def hat_yuku_saat(miktar: int, ozellik: UretimOzellikleri) -> float:
    """Emrin hattı meşgul edeceği toplam süre: hazırlık + adet × işlem.

    Adım 4 (kapasite) bunun üstüne kurulacak. Şimdiden hesaplanıyor çünkü
    emir kararının gerekçesinde de yeri var: "bu emir hattı 6,5 saat meşgul
    eder" cümlesi, kararı okuyan üretim sorumlusunun ilk sorduğu şey.
    """
    return ozellik.hazirlik_suresi_saat + miktar * ozellik.birim_islem_suresi_saat


def uretim_suresi_yetiyor_mu(ozellik: UretimOzellikleri) -> bool:
    """Emir bugün açılsa, mal ufuk bitmeden elde olur mu?

    ⚠️ Yetmiyorsa bu bir **erteleme** sebebi değil, tam tersi: geç kalmışız
    demektir. Kararın gerekçesinde görünmesi gerekiyor ki "sistem neden
    şimdi söylüyor" sorusu cevaplanabilsin.
    """
    return ozellik.uretim_suresi_gun <= ozellik.tahmin_ufuk_gun


__all__ = [
    "acik_hesapla",
    "emir_ekonomik_mi",
    "emir_miktari_hesapla",
    "hat_yuku_saat",
    "ihtiyac_hesapla",
    "uretim_suresi_yetiyor_mu",
]
