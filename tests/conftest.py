"""Ortak test altyapısı.

Sahip: Kişi B · Faz 1 B1.5

⚠️ Burada tanımlı `istemci` fixture'ı, `oturum_al` dependency'sini geçici bir
SQLite dosyasına yönlendirir. Bu şart: B1.5'ten sonra `decisions.py` DB'ye
yazıyor, override olmadan testler geliştirme veritabanını (`data/codifya.db`)
kirletir ve CI'da o dosya hiç bulunmadığı için testler kırılır.

Şema `create_all` ile kuruluyor, `alembic` ile değil — testler hızlı olsun.
Migration'ların gerçekten çalıştığını `tests/test_migrations.py` ayrıca sınar,
o yüzden bu kısayol bir boşluk bırakmıyor.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import KararTipi
from app.core.db import motor_olustur, oturum_al
from app.main import app
from app.models import Base, Policy

# `alembic/versions/1d7cc4d395fb...` tohumunun aynısı. Migration dosyası
# testlerden import EDİLMİYOR: migration geçmişi dondurulmuş bir kayıttır,
# değişince testin de değişmesi gerekmemeli.
VARSAYILAN_ESIKLER: tuple[tuple[KararTipi, float, float, bool], ...] = (
    (KararTipi.STOK_SIPARIS, 5_000.0, 0.85, False),
    (KararTipi.STOK_TASFIYE, 5_000.0, 0.85, True),
    (KararTipi.STOK_TEDARIKCI_DEGISIM, 5_000.0, 0.85, True),
    (KararTipi.STOK_AKSIYON_YOK, 5_000.0, 0.85, False),
)


@pytest.fixture
def api_motoru(tmp_path: Path) -> Iterator[Engine]:
    """Şeması kurulmuş, eşikleri tohumlanmış geçici veritabanı."""
    engine = motor_olustur(f"sqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(engine)

    fabrika = sessionmaker(bind=engine, expire_on_commit=False)
    with fabrika() as oturum:
        for tip, tutar, guven, daima_onay in VARSAYILAN_ESIKLER:
            oturum.add(
                Policy(
                    karar_tipi=tip,
                    esik_oto_uygula_tutar_tl=tutar,
                    esik_oto_uygula_min_guven=guven,
                    daima_onay_gerektirir=daima_onay,
                )
            )
        oturum.commit()

    yield engine
    engine.dispose()


@pytest.fixture
def api_oturumu(api_motoru: Engine) -> Iterator[Session]:
    """Endpoint'in yazdığını doğrulamak için doğrudan DB erişimi."""
    fabrika = sessionmaker(bind=api_motoru, expire_on_commit=False)
    with fabrika() as oturum:
        yield oturum


@pytest.fixture
def istemci(api_motoru: Engine) -> Iterator[TestClient]:
    """Geçici veritabanına bağlı FastAPI test istemcisi."""
    fabrika = sessionmaker(bind=api_motoru, expire_on_commit=False)

    def oturum_ver() -> Iterator[Session]:
        with fabrika() as oturum:
            yield oturum

    app.dependency_overrides[oturum_al] = oturum_ver
    try:
        yield TestClient(app)
    finally:
        # Sızdırılırsa sonraki testler gerçek veritabanına yazar.
        app.dependency_overrides.clear()
