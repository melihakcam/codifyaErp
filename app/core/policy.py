"""Eşikli otonomi motoru.

Sahip: Kişi B · Faz 1 B1.4'te `policy` tablosundan okuyacak şekilde genişletilecek

ŞU AN eşikler `config.py`'den okunuyor (DB tablosu henüz yok). Mantığın
kendisi gerçek — shadow mod semantiği şimdiden doğru çalışıyor, çünkü Faz 0.5
uçtan uca akışının bunu göstermesi gerekiyor.

⚠️ Bu dosyanın en önemli özelliği: `sonuc` (politikanın hükmü) ile `uygulandi`
(gerçekten olan şey) ayrı tutulur. Shadow mod raporu tam olarak bu ikisinin
karşılaştırmasıdır.
"""

from __future__ import annotations

from app.contracts import (
    DecisionCandidate,
    KararTipi,
    OtonomiSeviyesi,
    PolitikaKarari,
    PolitikaSonucu,
)
from app.core.config import Ayarlar

# Geri alınamayan kararların riski katsayıyla ağırlaştırılır.
GERI_ALINAMAZ_KATSAYISI = 3.0

# Bu tipler tutarı ne olursa olsun insan onayına gider.
DAIMA_ONAY_GEREKTIREN: frozenset[KararTipi] = frozenset(
    {KararTipi.STOK_TASFIYE, KararTipi.STOK_TEDARIKCI_DEGISIM}
)


def risk_skoru_hesapla(aday: DecisionCandidate) -> float:
    """Finansal etki × geri alınabilirlik × belirsizlik.

    Yüksek tutar, geri alınamazlık ve düşük güven riski birlikte büyütür.
    Güven 1.0 ise belirsizlik terimi 0'a gitmesin diye taban 0.05 eklenir —
    aksi halde "çok eminim" diyen bir model sınırsız yetki kazanırdı.
    """
    belirsizlik = max(0.05, 1.0 - aday.guven)
    katsayi = 1.0 if aday.geri_alinabilir else GERI_ALINAMAZ_KATSAYISI
    return aday.tahmini_tutar_tl * katsayi * belirsizlik


def _saf_politika(aday: DecisionCandidate, ayar: Ayarlar) -> tuple[PolitikaSonucu, list[str]]:
    """Otonomi seviyesinden bağımsız hüküm: bu karar oto-uygulanabilir mi?"""
    if aday.tip is KararTipi.STOK_AKSIYON_YOK:
        return PolitikaSonucu.AKSIYON_YOK, ["AKSIYON_GEREKMIYOR"]

    if aday.tip in DAIMA_ONAY_GEREKTIREN:
        return PolitikaSonucu.ONAY_KUYRUGU, ["TIP_DAIMA_ONAY"]

    gerekceler: list[str] = []
    if aday.tahmini_tutar_tl >= ayar.esik_oto_uygula_tutar_tl:
        gerekceler.append("TUTAR_ESIK_USTU")
    if aday.guven <= ayar.esik_oto_uygula_min_guven:
        gerekceler.append("GUVEN_ESIK_ALTI")
    if not aday.ozellikler.tedarikci_onayli:
        gerekceler.append("TEDARIKCI_ONAYSIZ")

    if gerekceler:
        return PolitikaSonucu.ONAY_KUYRUGU, gerekceler
    return PolitikaSonucu.OTO_UYGULA, ["ESIK_ALTI_OTOMATIK"]


def politika_uygula(aday: DecisionCandidate, ayar: Ayarlar) -> PolitikaKarari:
    """Karar adayını politikadan geçirip ne olacağına karar verir."""
    sonuc, gerekceler = _saf_politika(aday, ayar)
    seviye = ayar.autonomy_level

    # Yalnızca THRESHOLD modunda gerçekten uygulama yapılır.
    uygulandi = seviye is OtonomiSeviyesi.THRESHOLD and sonuc is PolitikaSonucu.OTO_UYGULA

    if seviye is OtonomiSeviyesi.SHADOW:
        gerekceler = [*gerekceler, "SHADOW_UYGULANMADI"]
    elif seviye is OtonomiSeviyesi.ADVISORY:
        gerekceler = [*gerekceler, "ADVISORY_INSAN_UYGULAR"]

    return PolitikaKarari(
        karar_id=aday.karar_id,
        sonuc=sonuc,
        uygulandi=uygulandi,
        otonomi_seviyesi=seviye,
        risk_skoru=risk_skoru_hesapla(aday),
        gerekce_kodlari=gerekceler,
    )
