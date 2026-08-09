"""Karar endpoint'leri.

Sahip: Kişi B · Faz 0.5 (stub) → Faz 1 B1.5 (DB'ye kayıt + kuyruk)
       → Faz 3 sonrası (SP2/#3): gerçek karar motoru + eğitilmiş model bağlandı

Bu dosya mimarinin ikinci temel kuralını hayata geçirir: ERP asla LLM'i
beklemez. Karar `stok_karari_uret()` çağrısından milisaniyelerde çıkar;
gerekçe `gerekce=True` istenmediği sürece hiç üretilmez. İstense bile
`gerekce_uret()` "hiçbir koşulda hata fırlatmaz" — LLM erişilemezse şablona
düşer, karar yolu bundan etkilenmez (bkz. `app/llm/guard.py`).

B1.5'te eklenen: karar artık DB'ye yazılıyor ve `ONAY_KUYRUGU` alan kararlar
onay kuyruğuna giriyor. Eşikler `policy` tablosundan okunuyor (B1.4).

Faz 6'da finans ucu eklendi. İki ucun gövdesi **aynı** — yalnızca karar
üreteci farklı — bu yüzden ortak akış `_karari_isle`'ye çıkarıldı. Kopyalansaydı
commit sıralamasındaki kritik kural (önce karar, sonra gerekçe) iki yerde
yaşar ve zamanla ayrışırdı.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.contracts import (
    DecisionCandidate,
    KararSonucu,
    OtonomiSeviyesi,
    PolitikaSonucu,
)
from app.core.audit import denetim_yaz, karari_kaydet
from app.core.config import Ayarlar, ayarlar
from app.core.db import OturumDep
from app.core.policy import esikleri_yukle, politika_uygula
from app.domain.finance.decide import finans_karari_uret
from app.domain.stock.decide import stok_karari_uret
from app.llm.client import OllamaIstemcisi
from app.llm.explain import gerekce_uret
from app.models import Approval

router = APIRouter(prefix="/v1/decisions", tags=["kararlar"])

AyarDep = Annotated[Ayarlar, Depends(ayarlar)]


@router.post(
    "/stock/reorder-review",
    response_model=KararSonucu,
    summary="Stok yeniden sipariş değerlendirmesi",
)
def stok_siparis_degerlendir(
    ayar: AyarDep,
    oturum: OturumDep,
    gerekce: Annotated[
        bool,
        Query(
            description="Türkçe gerekçe metni de üretilsin mi? "
            "Varsayılan False — karar yolu LLM'i beklemesin diye."
        ),
    ] = False,
) -> KararSonucu:
    """Bir SKU için sipariş kararı üretir, kaydeder ve gerekiyorsa kuyruğa alır.

    `sku_id` verilmiyor: `stok_karari_uret(None)` demo dünyasında sipariş
    kararını tetikleyen ilk SKU'yu otomatik seçer (sabit `seed=42`, dolayısıyla
    çağrıdan çağrıya tutarlı).
    """
    _kapali_mi(ayar)
    return _karari_isle(stok_karari_uret(), ayar, oturum, gerekce)


def _kapali_mi(ayar: Ayarlar) -> None:
    """Kill switch — `AUTONOMY_LEVEL=off` ise hiç karar üretilmez."""
    if ayar.autonomy_level is OtonomiSeviyesi.OFF:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Karar motoru kapalı (AUTONOMY_LEVEL=off).",
        )


def _karari_isle(
    aday: DecisionCandidate, ayar: Ayarlar, oturum: OturumDep, gerekce: bool
) -> KararSonucu:
    """Politika → kayıt → (istenirse) gerekçe. Alan bilmez.

    ⚠️ Bu fonksiyon Faz 6'da stok ucundan **çıkarıldı**, kopyalanmadı.
    İçindeki commit sıralaması (önce karar, sonra gerekçe) mimarinin ikinci
    kuralının veri katmanındaki karşılığı; iki yerde yaşasaydı biri
    güncellenip diğeri unutulurdu.
    """
    # Eşikler config'den değil `policy` tablosundan (B1.4). Satır yoksa
    # config'e düşer ve gerekçe kodlarında `ESIK_VARSAYILANA_DUSTU` görünür.
    esikler = esikleri_yukle(oturum, aday.tip, ayar)
    politika = politika_uygula(aday, ayar, esikler)

    # --- 1. Karar önce kalıcı olur ------------------------------------------
    #
    # ⚠️ Gerekçe üretimi bilinçli olarak BU COMMIT'TEN SONRA. Sıra ters
    # olsaydı (önce LLM, sonra kayıt) 6 saniyelik üretim penceresinde süreç
    # ölünce **karar tamamen kaybolurdu** — oysa karar zaten üretilmişti,
    # kaybedilecek bir şey yoktu.
    #
    # `nightly.py` de aynı deseni kullanıyor: kararlar bir commit, gerekçeler
    # ikinci commit. Mimarinin ikinci kuralının veri katmanındaki karşılığı
    # bu — karar yolu gerekçeyi beklemez.
    karar, _ = karari_kaydet(oturum, aday, politika)

    # Kuyruğa YALNIZCA insan onayı bekleyen kararlar girer. Shadow modda eşik
    # altı kalan karar kaydedilir ama kuyruğa girmez — kimsenin bakmayacağı
    # kaydı insanın önüne koymak kuyruğu değersizleştirir.
    if politika.sonuc is PolitikaSonucu.ONAY_KUYRUGU:
        oturum.add(Approval(karar_id=aday.karar_id))

    oturum.commit()

    # --- 2. Gerekçe: istenirse, kararın üstüne -------------------------------
    uretilen_gerekce = None
    if gerekce:
        with OllamaIstemcisi(ayar=ayar) as istemci:
            uretilen_gerekce = gerekce_uret(aday, istemci)

        karar.gerekce_metni = uretilen_gerekce.metin
        karar.guard_sonucu = uretilen_gerekce.guard_sonucu
        karar.llm_model_adi = uretilen_gerekce.model_adi
        karar.gerekce_uretim_ms = uretilen_gerekce.uretim_ms

        # Gerekçe üretimi ayrı bir olay — ilk denetim satırının üstüne
        # yazılmıyor, yenisi ekleniyor (`nightly.py` ile aynı).
        denetim_yaz(oturum, aday, politika, uretilen_gerekce)
        oturum.commit()

    return KararSonucu(aday=aday, politika=politika, gerekce=uretilen_gerekce)


@router.post(
    "/finance/collection-review",
    response_model=KararSonucu,
    summary="Tahsilat / alacak değerlendirmesi",
)
def finans_tahsilat_degerlendir(
    ayar: AyarDep,
    oturum: OturumDep,
    musteri_id: Annotated[
        str | None,
        Query(description="Belirli bir müşteri. Verilmezse aksiyon gerektiren ilk müşteri."),
    ] = None,
    gerekce: Annotated[
        bool,
        Query(
            description="Türkçe gerekçe metni de üretilsin mi? "
            "Varsayılan False — karar yolu LLM'i beklemesin diye."
        ),
    ] = False,
) -> KararSonucu:
    """Bir müşteri için tahsilat kararı üretir, kaydeder ve gerekiyorsa kuyruğa alır.

    Dört karardan biri çıkar: karşılık ayır, kredi limitini düşür, tahsilat
    takibi, aksiyon yok. Öncelik sırası `app/domain/finance/decide.py`'de.

    ⚠️ `karsilik_ayir` ve `kredi_limiti_dusur` **daima onay** gerektirir
    (`DAIMA_ONAY_GEREKTIREN`): ilki muhasebe kaydı, ikincisi müşteri
    ilişkisini etkileyen ticari karar.
    """
    _kapali_mi(ayar)
    try:
        aday = finans_karari_uret(musteri_id)
    except KeyError as hata:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(hata)
        ) from hata
    return _karari_isle(aday, ayar, oturum, gerekce)
