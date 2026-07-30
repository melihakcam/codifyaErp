"""Gecelik batch bulgularını döndürür.

Sahip: Kişi B · Faz 1 B1.5 (uç) → Faz 2 B2.6 (gecelik iş doldurur)

Tablo Faz 2'ye kadar boş kalacak; uç şimdi yazılıyor ki gecelik iş yazılırken
tüketici tarafı hazır olsun.

`kosu_id` filtresi bilinçli: "bu sabahın bulguları" tek sorguyla çekilebilmeli.
Tarihe göre filtrelemek yetmez — bir koşu gece yarısını geçerse iki güne
bölünür ve rapor yanlış çıkar.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.contracts import Alan
from app.core.db import OturumDep
from app.models import Insight

router = APIRouter(prefix="/v1/insights", tags=["içgörüler"])


class IcgoruKalemi(BaseModel):
    id: int
    kosu_id: UUID
    alan: Alan
    baslik: str
    metin: str
    onem_skoru: float
    karar_id: UUID | None
    zaman: datetime


@router.get("", response_model=list[IcgoruKalemi], summary="Gecelik bulguları listele")
def icgorulari_listele(
    oturum: OturumDep,
    alan: Annotated[Alan | None, Query(description="Boş bırakılırsa tüm alanlar.")] = None,
    kosu_id: Annotated[UUID | None, Query(description="Tek bir gecelik koşunun bulguları.")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[IcgoruKalemi]:
    """Bulguları önem skoruna göre azalan sırada döndürür."""
    sorgu = select(Insight).order_by(Insight.onem_skoru.desc(), Insight.zaman.desc()).limit(limit)

    if alan is not None:
        sorgu = sorgu.where(Insight.alan == alan)
    if kosu_id is not None:
        sorgu = sorgu.where(Insight.kosu_id == kosu_id)

    return [
        IcgoruKalemi(
            id=i.id,
            kosu_id=i.kosu_id,
            alan=i.alan,
            baslik=i.baslik,
            metin=i.metin,
            onem_skoru=i.onem_skoru,
            karar_id=i.karar_id,
            zaman=i.zaman,
        )
        for i in oturum.scalars(sorgu).all()
    ]
