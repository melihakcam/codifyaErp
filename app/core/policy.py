"""Eşikli otonomi motoru.

Sahip: Kişi B · Faz 1 B1.4'te eşikler `policy` tablosuna taşındı

⚠️ Bu dosyanın en önemli özelliği: `sonuc` (politikanın hükmü) ile `uygulandi`
(gerçekten olan şey) ayrı tutulur. Shadow mod raporu tam olarak bu ikisinin
karşılaştırmasıdır.

B1.4'te değişen: eşikler artık `PolitikaEsikleri` değer nesnesiyle taşınıyor
ve normal yolda `policy` tablosundan okunuyor (`esikleri_yukle()`).
`config.py` yedek kaynak olarak kaldı — DB'de o karar tipi için satır yoksa
karar bloke olmuyor, config'e düşüyor ve bu durum `ESIK_VARSAYILANA_DUSTU`
koduyla denetim kaydına yazılıyor. Sessizce yedeğe düşmek, eşik tablosunun
boş olduğunu aylarca fark etmemek demekti.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import (
    DecisionCandidate,
    KararTipi,
    OtonomiSeviyesi,
    PolitikaKarari,
    PolitikaSonucu,
)
from app.core.config import Ayarlar
from app.models import Policy

# Geri alınamayan kararların riski katsayıyla ağırlaştırılır.
GERI_ALINAMAZ_KATSAYISI = 3.0

# ⚠️ Artık YEDEK. Yetkili kaynak `policy` tablosundaki `daima_onay_gerektirir`
# kolonu; bu küme yalnızca o satır yoksa kullanılır. Yeni bir karar tipi
# eklerken buraya değil tabloya satır ekleyin (migration ile).
DAIMA_ONAY_GEREKTIREN: frozenset[KararTipi] = frozenset(
    {KararTipi.STOK_TASFIYE, KararTipi.STOK_TEDARIKCI_DEGISIM}
)


class EsikKaynagi(StrEnum):
    """Eşiklerin nereden geldiği. Denetim için ayrımı korumak gerekiyor.

    DB           : `policy` tablosunda satır bulundu — normal yol.
    CONFIG       : DB'ye hiç bakılmadı (test/DB'siz yol). Kasıtlı.
    CONFIG_YEDEK : DB'ye bakıldı, satır YOKTU. Operasyonel sorun — işaretlenir.
    """

    DB = "db"
    CONFIG = "config"
    CONFIG_YEDEK = "config_yedek"


@dataclass(frozen=True)
class PolitikaEsikleri:
    """Bir karar tipi için geçerli eşikler.

    Politika mantığı artık `Ayarlar`'a değil bu nesneye bakıyor. Ayrım şunu
    mümkün kılıyor: eşikler config'den de gelebilir, DB'den de gelebilir,
    testte elle de kurulabilir — mantık üçünde de aynı.
    """

    tutar_tl: float
    min_guven: float
    daima_onay: bool
    kaynak: EsikKaynagi

    @classmethod
    def configden(
        cls,
        tip: KararTipi,
        ayar: Ayarlar,
        kaynak: EsikKaynagi = EsikKaynagi.CONFIG,
    ) -> PolitikaEsikleri:
        """`config.py` değerlerinden eşik nesnesi kurar (yedek yol)."""
        return cls(
            tutar_tl=ayar.esik_oto_uygula_tutar_tl,
            min_guven=ayar.esik_oto_uygula_min_guven,
            daima_onay=tip in DAIMA_ONAY_GEREKTIREN,
            kaynak=kaynak,
        )

    @classmethod
    def satirdan(cls, satir: Policy) -> PolitikaEsikleri:
        """`policy` tablosundaki satırdan eşik nesnesi kurar (normal yol)."""
        return cls(
            tutar_tl=satir.esik_oto_uygula_tutar_tl,
            min_guven=satir.esik_oto_uygula_min_guven,
            daima_onay=satir.daima_onay_gerektirir,
            kaynak=EsikKaynagi.DB,
        )


def esikleri_yukle(oturum: Session, tip: KararTipi, ayar: Ayarlar) -> PolitikaEsikleri:
    """Karar tipinin eşiklerini `policy` tablosundan okur.

    Satır yoksa config'e düşer ve bunu `CONFIG_YEDEK` olarak işaretler —
    karar hiçbir koşulda bloke olmuyor. Eşik tablosu boş bir sistemde her
    kararın gerekçe kodlarında `ESIK_VARSAYILANA_DUSTU` görünür; bu, sorunun
    ilk gecelik raporda fark edilmesini sağlıyor.

    Yalnızca `aktif=True` satırlar okunur: geçmiş eşikleri silmek yerine
    pasifleştiriyoruz ki hangi kararın hangi eşikle verildiği izlenebilsin.
    """
    satir = oturum.scalars(
        select(Policy).where(Policy.karar_tipi == tip, Policy.aktif.is_(True))
    ).one_or_none()

    if satir is None:
        return PolitikaEsikleri.configden(tip, ayar, kaynak=EsikKaynagi.CONFIG_YEDEK)

    return PolitikaEsikleri.satirdan(satir)


def risk_skoru_hesapla(aday: DecisionCandidate) -> float:
    """Finansal etki × geri alınabilirlik × belirsizlik.

    Yüksek tutar, geri alınamazlık ve düşük güven riski birlikte büyütür.
    Güven 1.0 ise belirsizlik terimi 0'a gitmesin diye taban 0.05 eklenir —
    aksi halde "çok eminim" diyen bir model sınırsız yetki kazanırdı.
    """
    belirsizlik = max(0.05, 1.0 - aday.guven)
    katsayi = 1.0 if aday.geri_alinabilir else GERI_ALINAMAZ_KATSAYISI
    return aday.tahmini_tutar_tl * katsayi * belirsizlik


def _saf_politika(
    aday: DecisionCandidate, esikler: PolitikaEsikleri
) -> tuple[PolitikaSonucu, list[str]]:
    """Otonomi seviyesinden bağımsız hüküm: bu karar oto-uygulanabilir mi?"""
    # ⚠️ Alan bağımsız soruluyor. Önceden `is KararTipi.STOK_AKSIYON_YOK`
    # diye yazılıydı; Faz 6'da `finans.aksiyon_yok` bu daldan geçemez ve
    # "yapılacak bir şey yok" kararı oto-uygulama yoluna girerdi.
    if aday.tip.aksiyon_yok_mu:
        return PolitikaSonucu.AKSIYON_YOK, ["AKSIYON_GEREKMIYOR"]

    if esikler.daima_onay:
        return PolitikaSonucu.ONAY_KUYRUGU, ["TIP_DAIMA_ONAY"]

    gerekceler: list[str] = []
    if aday.tahmini_tutar_tl >= esikler.tutar_tl:
        gerekceler.append("TUTAR_ESIK_USTU")
    if aday.guven <= esikler.min_guven:
        gerekceler.append("GUVEN_ESIK_ALTI")
    # ⚠️ Alan-özel engel, alanın kendisi tarafından bildiriliyor. Stokta
    # "tedarikçi onaysız", finansta "müşterinin kredisi onaysız" — politika
    # hangisi olduğunu bilmiyor, yalnızca engel var mı diye soruyor.
    engel = aday.ozellikler.oto_uygulama_engeli()
    if engel:
        gerekceler.append(engel)

    if gerekceler:
        return PolitikaSonucu.ONAY_KUYRUGU, gerekceler
    return PolitikaSonucu.OTO_UYGULA, ["ESIK_ALTI_OTOMATIK"]


def politika_uygula(
    aday: DecisionCandidate,
    ayar: Ayarlar,
    esikler: PolitikaEsikleri | None = None,
) -> PolitikaKarari:
    """Karar adayını politikadan geçirip ne olacağına karar verir.

    `esikler` verilmezse `config.py`'den türetilir. Bu varsayılan bilinçli:
    politika mantığı DB'siz de çalışabilmeli — hem testler için hem de
    "veritabanı erişilemez ama karar üretilmeye devam etmeli" durumu için.
    Normal akışta çağıran taraf `esikleri_yukle()` ile DB satırını geçirir.
    """
    if esikler is None:
        esikler = PolitikaEsikleri.configden(aday.tip, ayar)

    sonuc, gerekceler = _saf_politika(aday, esikler)
    seviye = ayar.autonomy_level

    # Yalnızca THRESHOLD modunda gerçekten uygulama yapılır.
    uygulandi = seviye is OtonomiSeviyesi.THRESHOLD and sonuc is PolitikaSonucu.OTO_UYGULA

    if esikler.kaynak is EsikKaynagi.CONFIG_YEDEK:
        gerekceler = [*gerekceler, "ESIK_VARSAYILANA_DUSTU"]

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
