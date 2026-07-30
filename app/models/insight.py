"""Gecelik taramanın ürettiği Türkçe bulgular.

Sahip: Kişi B · Faz 1 B1.1 (tablo) → Faz 2 B2.6 (gecelik iş doldurur)

`kosu_id` her gecelik koşuya bir UUID verir: "bu sabahın bulguları" tek
sorguyla çekilebilsin. Tarihe göre filtrelemek yetmez — bir koşu gece yarısını
geçerse iki güne bölünür.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.contracts import Alan
from app.models.base import KimlikliTablo, enum_kolonu
from app.models.decision import Decision


class Insight(KimlikliTablo):
    """Tek bir içgörü satırı.

    `karar_id` nullable: her bulgu tek bir karara bağlı değil. "23 SKU'da
    tedarikçi gecikmesi arttı" gibi toplu bulgular hiçbir karara ait değildir.
    """

    __tablename__ = "insight"

    kosu_id: Mapped[UUID] = mapped_column(sa.Uuid, index=True)
    alan: Mapped[Alan] = mapped_column(enum_kolonu(Alan), index=True)

    baslik: Mapped[str]
    metin: Mapped[str] = mapped_column(sa.Text)

    # Gecelik iş yalnızca en önemli N karar için gerekçe üretir
    # (`config.gecelik_gerekce_ust_n`). Sıralama bu kolona göre yapılır.
    onem_skoru: Mapped[float] = mapped_column(index=True)

    karar_id: Mapped[UUID | None] = mapped_column(
        sa.ForeignKey("decision.karar_id", ondelete="SET NULL"), default=None, index=True
    )

    zaman: Mapped[datetime] = mapped_column(default=datetime.now, index=True)

    karar: Mapped[Decision | None] = relationship()
