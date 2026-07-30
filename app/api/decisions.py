"""Karar endpoint'leri.

Sahip: Kişi B · Faz 0.5 (stub) → Faz 1 B1.5 (tam kuyruk akışı)

Bu dosya mimarinin ikinci temel kuralını hayata geçirir: ERP asla LLM'i
beklemez. Karar `decide_*` çağrısından milisaniyelerde çıkar; gerekçe
`gerekce=True` istenmediği sürece hiç üretilmez.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.contracts import KararSonucu, OtonomiSeviyesi
from app.core.config import Ayarlar, ayarlar
from app.core.policy import politika_uygula
from app.domain.stock.decide import decide_stub
from app.llm.explain import explain_stub

router = APIRouter(prefix="/v1/decisions", tags=["kararlar"])

AyarDep = Annotated[Ayarlar, Depends(ayarlar)]


@router.post(
    "/stock/reorder-review",
    response_model=KararSonucu,
    summary="Stok yeniden sipariş değerlendirmesi",
)
def stok_siparis_degerlendir(
    ayar: AyarDep,
    gerekce: Annotated[
        bool,
        Query(
            description="Türkçe gerekçe metni de üretilsin mi? "
            "Varsayılan False — karar yolu LLM'i beklemesin diye."
        ),
    ] = False,
) -> KararSonucu:
    """Bir SKU için sipariş kararı üretir.

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
    politika = politika_uygula(aday, ayar)

    return KararSonucu(
        aday=aday,
        politika=politika,
        gerekce=explain_stub(aday) if gerekce else None,
    )
