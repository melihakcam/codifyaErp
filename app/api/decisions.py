"""Karar endpoint'leri.

Sahip: Kişi B · Faz 0.5 (stub) → Faz 1 B1.5 (DB'ye kayıt + kuyruk)

Bu dosya mimarinin ikinci temel kuralını hayata geçirir: ERP asla LLM'i
beklemez. Karar `decide_*` çağrısından milisaniyelerde çıkar; gerekçe
`gerekce=True` istenmediği sürece hiç üretilmez.

B1.5'te eklenen: karar artık DB'ye yazılıyor ve `ONAY_KUYRUGU` alan kararlar
onay kuyruğuna giriyor. Eşikler `policy` tablosundan okunuyor (B1.4).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.contracts import KararSonucu, OtonomiSeviyesi, PolitikaSonucu
from app.core.audit import karari_kaydet
from app.core.config import Ayarlar, ayarlar
from app.core.db import OturumDep
from app.core.policy import esikleri_yukle, politika_uygula
from app.domain.stock.decide import decide_stub
from app.llm.explain import explain_stub
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

    Faz 0.5: sabit stub veri döner. Faz 2 A2.6'da `decide_stub()` yerine
    gerçek `stok_karari_uret(sku_id)` gelecek — bu dosyada başka bir şey
    değişmeyecek.
    """
    if ayar.autonomy_level is OtonomiSeviyesi.OFF:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Karar motoru kapalı (AUTONOMY_LEVEL=off).",
        )

    aday = decide_stub()

    # Eşikler config'den değil `policy` tablosundan (B1.4). Satır yoksa
    # config'e düşer ve gerekçe kodlarında `ESIK_VARSAYILANA_DUSTU` görünür.
    esikler = esikleri_yukle(oturum, aday.tip, ayar)
    politika = politika_uygula(aday, ayar, esikler)

    uretilen_gerekce = explain_stub(aday) if gerekce else None

    # `karari_kaydet` Decision + DecisionAudit satırlarını birlikte yazar;
    # denetim kaydını atlamak mümkün değil.
    karari_kaydet(oturum, aday, politika, uretilen_gerekce)

    # Kuyruğa YALNIZCA insan onayı bekleyen kararlar girer. Shadow modda eşik
    # altı kalan karar kaydedilir ama kuyruğa girmez — kimsenin bakmayacağı
    # kaydı insanın önüne koymak kuyruğu değersizleştirir.
    if politika.sonuc is PolitikaSonucu.ONAY_KUYRUGU:
        oturum.add(Approval(karar_id=aday.karar_id))

    oturum.commit()

    return KararSonucu(aday=aday, politika=politika, gerekce=uretilen_gerekce)
