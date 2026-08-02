"""Denetim kaydı yazıcı.

Sahip: Kişi B · Faz 1 B1.3

KURAL: denetim kaydı olmayan bir karar yolu merge edilmez.

Bu kuralı yoruma bırakmamak için modül iki kapı sunuyor:

· `karari_kaydet()` — kararı DB'ye yazmanın **tek** meşru yolu. Decision
  satırıyla DecisionAudit satırını aynı işlemde yazar, dolayısıyla "denetim
  kaydını eklemeyi unuttum" diye bir durum oluşamaz.
· `denetim_yaz()` — sonradan gelen olaylar için (gerekçe üretildi, guard
  reddetti, yeniden denendi). Her çağrı YENİ satır ekler, mevcut satırı
  güncellemez.

Fonksiyonların hiçbiri `commit()` çağırmaz — `app/core/db.py`'deki kararla
tutarlı. Sebebi burada daha da kritik: karar ile denetim kaydı **aynı işlemde**
kalmak zorunda. Ayrı commit edilirse aradaki bir çökme, denetim izi olmayan
bir karar bırakır ve tam olarak engellemeye çalıştığımız şey olur.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.contracts import (
    DecisionCandidate,
    Gerekce,
    GuardSonucu,
    KararSonucu,
    PolitikaKarari,
    StockFeatures,
)
from app.models import Decision, DecisionAudit


def girdi_hash_hesapla(ozellikler: StockFeatures) -> str:
    """Karar girdisinin SHA-256'sı (64 hex karakter).

    Amaç: "aynı girdiye aynı kararı verdik mi" sorusunu cevaplamak. Bu yüzden
    hash'e YALNIZCA özellikler girer — `karar_id` ve `uretim_zamani` her
    çalıştırmada değişir, onları katmak hash'i her seferinde farklı yapar ve
    karşılaştırma imkânı yok olur.

    Kanonik biçim şart: `sort_keys=True` ve boşluksuz ayraçlar. Aynı sözlüğün
    farklı sırada serileştirilmesi farklı hash üretirdi ve "girdi değişti"
    yalancı alarmı verirdi.

    ⚠️ Bu hash bir sürüm kimliği değil, sapma dedektörüdür: kanonikleştirme
    biçimi değişirse (ör. `ensure_ascii`) tüm eski hash'ler geçersiz olur.
    Değiştirmek gerekiyorsa migration'la eski satırları işaretleyin.
    """
    kanonik = json.dumps(
        ozellikler.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(kanonik.encode("utf-8")).hexdigest()


def _cikti_anlik_goruntusu(
    aday: DecisionCandidate,
    politika: PolitikaKarari,
    gerekce: Gerekce | None,
) -> dict[str, Any]:
    """Dışarıya dönen cevabın tamamını JSON'a çevirir.

    Kararın parçalarını tek tek değil `KararSonucu` olarak saklıyoruz: denetim
    satırından ERP'nin o an ne gördüğü birebir yeniden kurulabilsin. "Sistem
    ne önerdi" tartışması çıktığında elimizde tahmin değil kayıt olur.
    """
    return KararSonucu(aday=aday, politika=politika, gerekce=gerekce).model_dump(mode="json")


def denetim_yaz(
    oturum: Session,
    aday: DecisionCandidate,
    politika: PolitikaKarari,
    gerekce: Gerekce | None = None,
) -> DecisionAudit:
    """Tek çağrıyla eksiksiz bir denetim satırı hazırlar ve oturuma ekler.

    Guard sonucu ve reddedilen sayılar `gerekce`'den okunur — ayrı parametre
    olarak istenmiyor. Sebebi: iki yerden gelen bilgi ayrışır. Gerekçe
    üretilmediyse `GuardSonucu.ATLANDI` yazılır; "guard çalışmadı" ile "guard
    geçti" asla aynı değere düşmez.

    `commit()` çağrılmaz — çağıran tarafın işlemine katılır.
    """
    return _ekle(
        oturum,
        DecisionAudit(
            karar_id=aday.karar_id,
            girdi_hash=girdi_hash_hesapla(aday.ozellikler),
            tetiklenen_kurallar=[k.model_dump(mode="json") for k in aday.tetiklenen_kurallar],
            model_surumleri=aday.model_surumleri,
            cikti=_cikti_anlik_goruntusu(aday, politika, gerekce),
            guard_sonucu=gerekce.guard_sonucu if gerekce else GuardSonucu.ATLANDI,
            reddedilen_sayilar=list(gerekce.reddedilen_sayilar) if gerekce else [],
        ),
    )


def karari_kaydet(
    oturum: Session,
    aday: DecisionCandidate,
    politika: PolitikaKarari,
    gerekce: Gerekce | None = None,
) -> tuple[Decision, DecisionAudit]:
    """Kararı ve denetim kaydını birlikte yazar. Kararı kaydetmenin tek yolu.

    `Decision(...)` nesnesini elle kurup `oturum.add()` etmek yerine bunu
    kullanın: iki satır tek yerde üretildiği için denetim kaydını atlamak
    mümkün değil. Kural yoruma değil imzaya gömülü.

    Gerekçe genellikle `None`'dır — karar milisaniyelerde çıkar, gerekçe
    kuyrukta bekler. Faz 2'de guard çalıştığında `denetim_yaz()` ikinci satırı
    ekler ve `Decision`'ın gerekçe kolonları güncellenir.

    `commit()` çağrılmaz: çağıran endpoint karar verir. Bu sayede iki satır
    tek işlemde kalır — yarısı yazılmış bir karar oluşamaz.
    """
    karar = _ekle(oturum, Decision.sozlesmeden(aday, politika))

    if gerekce is not None:
        karar.gerekce_metni = gerekce.metin
        karar.guard_sonucu = gerekce.guard_sonucu
        karar.llm_model_adi = gerekce.model_adi
        karar.gerekce_uretim_ms = gerekce.uretim_ms

    return karar, denetim_yaz(oturum, aday, politika, gerekce)


def _ekle[T](oturum: Session, nesne: T) -> T:
    """`oturum.add()` bir şey döndürmediği için küçük bir sarmalayıcı."""
    oturum.add(nesne)
    return nesne
