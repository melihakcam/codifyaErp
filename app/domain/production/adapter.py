"""Üretim adaptörü — geçmişten gelen talep, plana giren iş olur.

Sahip: Kişi A · Faz 13 A13.2

## Bu dosya ne yapıyor

Genel motor "işleri ver" diyor; bu dosya üretim dünyasından iş çıkarıyor:

    gecmis (3 yil)  ->  tahmin  ->  uretim.emir_ac karari  ->  Is

⚠️ **Hiçbir halka burada yeniden yazılmadı.** Tahmin `app/forecast/`,
emir kararı `app/domain/production/decide.py`, çeviri
`cizelge.emirleri_ise_cevir` içinde ve üçü de Faz 10-11'den beri testli.
Buradaki tek yeni şey **imza**: genel motorun tanıdığı `isleri_uret`.

Yeniden yazsaydık üretimin bugünkü davranışı ile plan komutunun davranışı
ayrışırdı ve hangisinin doğru olduğu sorusu cevapsız kalırdı.

## ⚠️ Kaynaklar neden tanımda yazılı değil

Hatlar ve kapasiteleri işletmenin verisinde yaşıyor: hat listesi ana
veriden, günlük kapasite `profiller/*.json`'daki hedef kullanım oranından
geliyor. `ornekler/uretim.json`'a elle kopyalansaydı iki ayrı gerçek olurdu
— kapasite değişince plan sessizce yanlış çıkardı.

O yüzden tanımda `"kaynaklar": []` yazıyor ve motor kaynağı buradan
istiyor. ⚠️ Bu **istisna, kural değil**: nakliye ve vardiya gibi kaynak
listesi sabit olan alanlarda kaynaklar tanımda durur ve bu dosya hiç
devreye girmez.

## ⚠️ Neden önbellek var

`uretim_kararlari_uret()` ölçüldü: **ilk koşu ~75 sn, sonrakiler ~36 sn**
(3 yıllık geçmiş üzerinde ~2.000 kalem için tahmin + kural). Motor işleri
ve kaynakları ayrı ayrı istediği için bu hesap tek bir plan çağrısında iki
kez yapılırdı — plan komutu bir buçuk dakika sürerdi.

Önbellek **süreli** (`ONBELLEK_SANIYE`): süresiz olsaydı uzun koşan bir
serviste veri değiştikten sonra da eski planı vermeye devam ederdi ve
"sistem neden güncellenmiyor" sorusunun cevabı hiçbir yerde yazmazdı.
Test ve gecelik iş `onbellek_temizle()` ile sıfırlayabilir.
"""

from __future__ import annotations

import time
from datetime import date

from app.contracts import KararTipi
from app.domain.production.cizelge import emirleri_ise_cevir
from app.domain.production.decide import uretim_kararlari_uret
from app.planlama.contracts import Is, Kaynak
from app.planlama.tanim import AlanTanimi

# Aynı plan çağrısı içinde iş ve kaynak iki ayrı istek olarak geliyor; bu
# süre ikisini kapsayacak kadar uzun, veri tazeliğini bozacak kadar kısa.
ONBELLEK_SANIYE = 300.0

_onbellek: tuple[float, list[Is], list[Kaynak]] | None = None


def onbellek_temizle() -> None:
    """Bir sonraki çağrı hesabı yeniden yapsın."""
    global _onbellek
    _onbellek = None


def _emirler() -> tuple[list[Is], list[Kaynak]]:
    """Bugünün üretim emirleri → genel motorun iş ve kaynakları."""
    global _onbellek

    if _onbellek is not None:
        yazilma, isler, kaynaklar = _onbellek
        if time.monotonic() - yazilma < ONBELLEK_SANIYE:
            return isler, kaynaklar

    kararlar = uretim_kararlari_uret()
    emirler = [k for k in kararlar if k.tip is KararTipi.URETIM_EMIR_AC]
    isler, kaynaklar = emirleri_ise_cevir(emirler)
    _onbellek = (time.monotonic(), isler, kaynaklar)
    return isler, kaynaklar


def isleri_uret(
    tanim: AlanTanimi,
    ufuk_gun: int,
    baslangic: date,
    kaynak_isler: tuple[Is, ...] = (),
) -> list[Is]:
    """Tahminden türeyen üretim işleri.

    ⚠️ `ufuk_gun` ve `baslangic` bilinçli olarak **kullanılmıyor**: emir
    kararı kendi ufkunu işletme profilinden alıyor (`planlama_ufku_gun`) ve
    burada ikinci bir ufuk uygulamak aynı sorunun iki farklı cevabını
    üretirdi. İmza yine de ortak — motor bütün adaptörleri aynı biçimde
    çağırıyor, hangisinin neyi kullandığına bakmıyor.

    `kaynak_isler` de kullanılmıyor: üretim zincirin **başı**, kimseden
    beslenmiyor.
    """
    isler, _ = _emirler()
    return isler


def kaynaklari_uret(tanim: AlanTanimi) -> list[Kaynak]:
    """Üretim hatları — ana veriden, kapasiteleri profilden."""
    _, kaynaklar = _emirler()
    return kaynaklar


__all__ = ["ONBELLEK_SANIYE", "isleri_uret", "kaynaklari_uret", "onbellek_temizle"]
