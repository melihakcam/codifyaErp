"""İnsan geri bildirimi; sonraki eğitim turunun verisi.

Sahip: Kişi B · Faz 1 B1.5

`POST /v1/approvals/{karar_id}` ile farkı: orası **iş akışı** ucudur, kararı
bir kez sonuçlandırır. Burası **veri** ucudur, aynı karara sınırsız yorum
eklenebilir.

Bu ayrımın sebebi Faz 3: LoRA'nın ikinci turu bu tablodan besleniyor. Kullanıcı
bir kararı onayladıktan bir hafta sonra "aslında bu miktar fazlaydı" diyorsa, o
bilgi iş akışını değiştirmemeli ama eğitim verisine girmeli.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.db import OturumDep
from app.models import Decision, Feedback, GeriBildirimTuru

router = APIRouter(prefix="/v1/feedback", tags=["geri bildirim"])


class GeriBildirimIstegi(BaseModel):
    karar_id: UUID
    tur: GeriBildirimTuru
    kullanici: str = Field(min_length=1, description="Denetim için zorunlu")
    duzeltilmis_aksiyon: dict[str, float | int | str | None] | None = None
    yorum: str | None = None


class GeriBildirimSonucu(BaseModel):
    feedback_id: int
    karar_id: UUID
    tur: GeriBildirimTuru
    zaman: datetime


@router.post("", response_model=GeriBildirimSonucu, summary="Bir karara geri bildirim ekle")
def geri_bildirim_ekle(istek: GeriBildirimIstegi, oturum: OturumDep) -> GeriBildirimSonucu:
    """Geri bildirimi kaydeder. İş akışı durumuna dokunmaz.

    Kararın varlığı önce kontrol ediliyor: yabancı anahtar kısıtı da bunu
    yakalar ama `IntegrityError` istemciye 500 olarak döner. Var olmayan bir
    kimlik istemci hatasıdır — 404 dönmesi gerekir.
    """
    varmi = oturum.scalars(
        select(Decision.karar_id).where(Decision.karar_id == istek.karar_id)
    ).one_or_none()

    if varmi is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{istek.karar_id} kimlikli karar yok.",
        )

    geri_bildirim = Feedback(
        karar_id=istek.karar_id,
        tur=istek.tur,
        duzeltilmis_aksiyon=istek.duzeltilmis_aksiyon,
        yorum=istek.yorum,
        kullanici=istek.kullanici,
    )
    oturum.add(geri_bildirim)
    oturum.commit()

    return GeriBildirimSonucu(
        feedback_id=geri_bildirim.id,
        karar_id=geri_bildirim.karar_id,
        tur=geri_bildirim.tur,
        zaman=geri_bildirim.zaman,
    )
