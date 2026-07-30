"""Onay kuyruğu ve insan geri bildirimi.

Sahip: Kişi B · Faz 1 B1.1 (tablolar) → B1.5 (endpoint'ler)

`approval` kararın *iş akışı* durumunu tutar; `feedback` insanın *ne dediğini*
tutar. Ayrı olmalarının sebebi: bir karar bir kez onaylanır (tek `approval`
satırı) ama üzerine birden çok yorum/düzeltme düşebilir ve bunların hepsi
sonraki eğitim turunun verisidir — biri silinirse veri kaybolur.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import KimlikliTablo, enum_kolonu
from app.models.decision import Decision


class OnayDurumu(StrEnum):
    """Kuyruktaki bir kararın iş akışı durumu.

    Sözleşmede (`contracts.py`) değil burada tanımlı: bu DB'ye özgü bir iş
    akışı kavramı, Kişi A'nın ürettiği veya tükettiği bir tip değil.
    """

    BEKLIYOR = "bekliyor"
    ONAYLANDI = "onaylandi"
    REDDEDILDI = "reddedildi"
    DUZELTILDI = "duzeltildi"


class GeriBildirimTuru(StrEnum):
    """İnsanın karar hakkındaki hükmü."""

    ONAY = "onay"
    RED = "red"
    DUZELTME = "duzeltme"


class Approval(KimlikliTablo):
    """Onay kuyruğundaki tek bir kayıt.

    `karar_id` UNIQUE: aynı karar kuyruğa iki kez girmez. Gecelik iş aynı
    SKU'yu tekrar taradığında ikinci kaydı eklemeye çalışırsa DB reddeder —
    bunu koda güvenmek yerine kısıtla garanti etmek bilinçli.
    """

    __tablename__ = "approval"

    karar_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("decision.karar_id", ondelete="CASCADE"), unique=True, index=True
    )
    durum: Mapped[OnayDurumu] = mapped_column(
        enum_kolonu(OnayDurumu), default=OnayDurumu.BEKLIYOR, index=True
    )

    olusturma_zamani: Mapped[datetime] = mapped_column(default=datetime.now, index=True)
    karar_zamani: Mapped[datetime | None] = mapped_column(default=None)
    karar_veren: Mapped[str | None] = mapped_column(default=None)

    karar: Mapped[Decision] = relationship()


class Feedback(KimlikliTablo):
    """İnsanın karara verdiği tepki — sonraki eğitim turunun verisi.

    Bu tablo yalnızca denetim için değil: Faz 3'te LoRA'nın ikinci turu
    buradaki düzeltmelerden beslenir. `duzeltilmis_aksiyon` en değerli alan —
    insanın "hayır, 1.200 değil 800 olacak" demesi, modelin öğrenmesi gereken
    tam olarak o.
    """

    __tablename__ = "feedback"

    karar_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("decision.karar_id", ondelete="CASCADE"), index=True
    )
    tur: Mapped[GeriBildirimTuru] = mapped_column(enum_kolonu(GeriBildirimTuru), index=True)

    duzeltilmis_aksiyon: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON, default=None)
    yorum: Mapped[str | None] = mapped_column(sa.Text, default=None)
    kullanici: Mapped[str | None] = mapped_column(default=None)

    zaman: Mapped[datetime] = mapped_column(default=datetime.now, index=True)

    karar: Mapped[Decision] = relationship()
