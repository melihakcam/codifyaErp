"""Kritik olay tetikleyicileri: büyük sipariş, kritik stok, limit aşımı.

Sahip: Kişi B · Faz 2 B2.6

Gecelik tarama günde bir kez koşuyor. Bazı durumlar sabahı beklememeli — bu
modül onları anında yakalar.

Tetikleyici **karar üretmez**, üretilmiş bir kararı değerlendirir. Yani kural
motorunun yerine geçmiyor, çıktısına bakıp "bu sabahı bekleyemez" diyor.
Ayrım önemli: tetikleyici mantığı karar mantığına karışırsa iş kuralı iki
yerde yaşar ve zamanla ayrışır.

Eşikler `config.py`'de — sahada "büyük sipariş" neye denir şirkete göre
değişir ve kod dağıtmadan ayarlanabilmeli.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import DecisionCandidate, KararTipi
from app.core.config import Ayarlar, ayarlar
from app.models import Decision, Insight


class Tetikleyici(StrEnum):
    """Anında ele alınması gereken durumlar."""

    BUYUK_SIPARIS = "buyuk_siparis"
    KRITIK_STOK = "kritik_stok"
    LIMIT_ASIMI = "limit_asimi"


@dataclass(frozen=True)
class Tetiklenme:
    """Tetiklenmiş tek bir olay.

    `deger` ve `esik` birlikte tutuluyor: "neden tetiklendi" sorusu sonradan
    kayıttan cevaplanabilsin ve içgörü metni somut sayı taşısın diye.
    """

    tur: Tetikleyici
    aciklama: str
    deger: float
    esik: float


def _stok_gun_karsiligi(aday: DecisionCandidate) -> float | None:
    """Kullanılabilir stok kaç günlük tüketime yetiyor.

    Talep sıfırsa cevap yok — `None` dönüyor, 0 değil. 0 dönmek "hemen
    bitecek" anlamına gelirdi ve hiç satmayan bir ürün için her gece yanlış
    alarm üretirdi.
    """
    talep = aday.ozellikler.ort_gunluk_talep
    if talep <= 0:
        return None
    return aday.ozellikler.kullanilabilir_stok / talep


def gunluk_siparis_toplami(oturum: Session, gun: date | None = None) -> float:
    """Belirtilen gün içinde kaydedilen sipariş kararlarının toplam tutarı."""
    gun = gun or date.today()
    baslangic = datetime.combine(gun, time.min)
    bitis = datetime.combine(gun, time.max)

    toplam = oturum.scalar(
        select(func.coalesce(func.sum(Decision.tahmini_tutar_tl), 0.0)).where(
            Decision.tip == KararTipi.STOK_SIPARIS,
            Decision.olusturma_zamani >= baslangic,
            Decision.olusturma_zamani <= bitis,
        )
    )
    return float(toplam or 0.0)


def tetikleyicileri_degerlendir(
    aday: DecisionCandidate,
    ayar: Ayarlar | None = None,
    *,
    gunluk_toplam: float | None = None,
) -> list[Tetiklenme]:
    """Bir kararın hangi tetikleyicileri ateşlediğini döndürür.

    `gunluk_toplam` verilmezse limit aşımı kontrolü **yapılmaz**. O kontrol DB
    sorgusu gerektiriyor ve bu fonksiyon bilinçli olarak saf tutuluyor — saf
    olduğu için modelsiz, DB'siz test edilebiliyor. Çağıran taraf
    `gunluk_siparis_toplami()` ile hesaplayıp geçirir.
    """
    ayar = ayar or ayarlar()
    tetiklenenler: list[Tetiklenme] = []

    if aday.tahmini_tutar_tl >= ayar.tetik_buyuk_siparis_tutar_tl:
        tetiklenenler.append(
            Tetiklenme(
                tur=Tetikleyici.BUYUK_SIPARIS,
                aciklama=(
                    f"{aday.ozellikler.sku_adi} için {aday.tahmini_tutar_tl:,.0f} TL'lik "
                    f"karar, {ayar.tetik_buyuk_siparis_tutar_tl:,.0f} TL eşiğinin üstünde."
                ),
                deger=aday.tahmini_tutar_tl,
                esik=ayar.tetik_buyuk_siparis_tutar_tl,
            )
        )

    gun_karsiligi = _stok_gun_karsiligi(aday)
    if gun_karsiligi is not None and gun_karsiligi < ayar.tetik_kritik_stok_gun:
        tetiklenenler.append(
            Tetiklenme(
                tur=Tetikleyici.KRITIK_STOK,
                aciklama=(
                    f"{aday.ozellikler.sku_adi} stoğu {gun_karsiligi:.1f} günlük tüketime "
                    f"yetiyor ({ayar.tetik_kritik_stok_gun:.0f} gün eşiğinin altı)."
                ),
                deger=gun_karsiligi,
                esik=ayar.tetik_kritik_stok_gun,
            )
        )

    if gunluk_toplam is not None:
        yeni_toplam = gunluk_toplam + aday.tahmini_tutar_tl
        if yeni_toplam >= ayar.tetik_gunluk_siparis_limiti_tl:
            tetiklenenler.append(
                Tetiklenme(
                    tur=Tetikleyici.LIMIT_ASIMI,
                    aciklama=(
                        f"Bugünkü sipariş toplamı {yeni_toplam:,.0f} TL, günlük "
                        f"{ayar.tetik_gunluk_siparis_limiti_tl:,.0f} TL limitini aşıyor."
                    ),
                    deger=yeni_toplam,
                    esik=ayar.tetik_gunluk_siparis_limiti_tl,
                )
            )

    return tetiklenenler


def _siddet(t: Tetiklenme) -> float:
    """Eşiğin kaç katı aşıldığı.

    Sabit 1.0 yerine oran kullanılıyor: limitin iki katı bir sipariş, sınırda
    olandan daha acil ve kuyrukta üstte görünmeli.

    Kritik stokta eşiğin ALTINA düşülüyor, o yüzden oran ters çevriliyor —
    "ne kadar kötü" anlamı üç tetikleyicide de aynı yönde olsun.
    """
    if t.tur is Tetikleyici.KRITIK_STOK:
        return (t.esik / t.deger) if t.deger > 0 else t.esik
    return (t.deger / t.esik) if t.esik > 0 else 1.0


def tetiklenmeleri_kaydet(
    oturum: Session,
    aday: DecisionCandidate,
    tetiklenenler: list[Tetiklenme],
    kosu_id: UUID | None = None,
) -> list[Insight]:
    """Tetiklenen olayları `insight` tablosuna yazar.

    Gecelik taramanın içgörüleriyle **aynı tabloya** yazılıyor çünkü tüketici
    aynı: `GET /v1/insights`. Ayırt etmek isteyen `kosu_id`'ye bakar —
    tetikleyici kaynaklı içgörülerin kendi koşu kimliği olur.

    ⚠️ **Ön koşul:** `aday` daha önce DB'ye yazılmış olmalı
    (`audit.karari_kaydet`). İçgörü satırı `karar_id` üzerinden karara bağlı;
    karar yoksa yabancı anahtar kısıtı reddeder. Sıra bilinçli: tetikleyici
    üretilmiş bir kararı değerlendirir, kararın kendisini üretmez.
    """
    kosu_id = kosu_id or uuid4()
    yazilanlar = []

    for t in tetiklenenler:
        icgoru = Insight(
            kosu_id=kosu_id,
            alan=aday.alan,
            baslik=f"[{t.tur.value}] {aday.ozellikler.sku_adi}",
            metin=t.aciklama,
            onem_skoru=_siddet(t),
            karar_id=aday.karar_id,
        )
        oturum.add(icgoru)
        yazilanlar.append(icgoru)

    return yazilanlar


__all__ = [
    "Tetiklenme",
    "Tetikleyici",
    "gunluk_siparis_toplami",
    "tetiklenmeleri_kaydet",
    "tetikleyicileri_degerlendir",
]
