"""SQLAlchemy temel sınıfı ve ortak kolon tipleri.

Sahip: Kişi B · Faz 1 B1.1

`Base.metadata` alembic'in "hangi tablolar olmalı" sorusuna verdiği cevaptır.
Bir tablo `app/models/__init__.py`'de import edilmezse alembic onu görmez ve
migration'a yazmaz — sessizce eksik kalır.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def enum_kolonu(enum_sinifi: type[StrEnum]) -> sa.Enum:
    """StrEnum'u VARCHAR + CHECK kısıtı olarak saklar.

    İki ayar bilinçli:

    · `native_enum=False` — SQLite'ta gerçek ENUM tipi yoktur. Bu ayar
      olmadan Postgres'e geçişte migration davranışı ayrışır; kapatınca
      her iki veritabanında da aynı VARCHAR + CHECK üretilir.

    · `values_callable` — SQLAlchemy'nin varsayılanı üyenin ADINI saklar
      (`STOK_SIPARIS`). Biz DEĞERİNİ istiyoruz (`stok.siparis`), çünkü
      sözleşmedeki `.value` ve politika tablosundaki anahtar o. Bu ayar
      olmadan DB'deki metin ile `KararTipi.STOK_SIPARIS.value` uyuşmaz.
    """
    return sa.Enum(
        enum_sinifi,
        values_callable=lambda e: [uye.value for uye in e],
        native_enum=False,
        validate_strings=True,
    )


class Base(DeclarativeBase):
    """Tüm tabloların ortak atası.

    `type_annotation_map` sayesinde `Mapped[dict[str, Any]]` yazmak yeterli;
    her kolonda `mapped_column(sa.JSON)` tekrar etmeye gerek kalmıyor.
    """

    type_annotation_map = {  # noqa: RUF012
        dict[str, Any]: sa.JSON,
        list[dict[str, Any]]: sa.JSON,
        list[str]: sa.JSON,
        list[float]: sa.JSON,
        str: sa.String(255),
    }


class KimlikliTablo(Base):
    """Otomatik artan tamsayı birincil anahtarı olan tablolar için taban.

    `decision` bunu kullanmaz — onun anahtarı sözleşmeden gelen `karar_id`
    (UUID). Aynı kararın DB'de ikinci bir kimliği olması izlenebilirliği
    bozardı.
    """

    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True)
