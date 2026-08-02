"""Eşik tablosu — kodda gömülü eşiklerin gideceği yer.

Sahip: Kişi B · Faz 1 B1.1 (tablo) → B1.4 (app/core/policy.py buradan okur)

Şu an `app/core/policy.py` eşikleri `config.py`'den okuyor ve
`DAIMA_ONAY_GEREKTIREN` frozenset'i koda gömülü. B1.4'te ikisi de bu tabloya
taşınacak; böylece eşiği değiştirmek kod dağıtmayı değil bir satır UPDATE
etmeyi gerektirecek.

Alan bazlı satırlar: `stok.siparis` ve `stok.tasfiye` farklı eşiklerle
yönetilebilsin. Tek global eşik, tasfiyeyi siparişle aynı kefeye koyardı.
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.contracts import KararTipi
from app.models.base import KimlikliTablo, enum_kolonu


class Policy(KimlikliTablo):
    """Bir karar tipi için eşik satırı.

    `karar_tipi` UNIQUE: aynı tip için iki çelişen eşik satırı olamaz.
    Hangisinin geçerli olduğunu koda sormak zorunda kalmak, güvenlik kapısı
    olan bir tabloda kabul edilemez.
    """

    __tablename__ = "policy"

    karar_tipi: Mapped[KararTipi] = mapped_column(enum_kolonu(KararTipi), unique=True, index=True)

    esik_oto_uygula_tutar_tl: Mapped[float]
    esik_oto_uygula_min_guven: Mapped[float]

    # Tasfiye ve tedarikçi değişimi için True — tutar ne olursa olsun onaya gider.
    # `app/core/policy.py`'deki DAIMA_ONAY_GEREKTIREN frozenset'inin yerini alacak.
    daima_onay_gerektirir: Mapped[bool] = mapped_column(default=False)

    # Satırı silmek yerine pasifleştirmek: geçmiş kararların hangi eşikle
    # verildiği izlenebilir kalsın.
    aktif: Mapped[bool] = mapped_column(default=True, index=True)

    aciklama: Mapped[str | None] = mapped_column(sa.Text, default=None)
    guncelleme_zamani: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)
