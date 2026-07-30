"""Migration testleri (Faz 1 B1.5).

`tests/conftest.py` şemayı `create_all` ile kuruyor — hızlı, ama alembic
migration'larının gerçekten çalıştığını kanıtlamıyor. Bu dosya o boşluğu
kapatır: migration'lar geçici bir dosyaya baştan uygulanır.

B1.6'da CI bu testi koşacak; böylece "modeli değiştirdim, migration üretmeyi
unuttum" veya "veri migration'ı bozuldu" hataları PR aşamasında yakalanır.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.core.config import PROJE_KOKU

BEKLENEN_TABLOLAR = {
    "decision",
    "decision_audit",
    "approval",
    "feedback",
    "policy",
    "insight",
}

TOHUMLANAN_TIPLER = {
    "stok.siparis",
    "stok.tasfiye",
    "stok.tedarikci_degisim",
    "stok.aksiyon_yok",
}


@pytest.fixture
def alembic_ayari(tmp_path: Path) -> Config:
    """Geçici bir SQLite dosyasına yönlendirilmiş alembic yapılandırması.

    `sqlalchemy.url`'i burada set edebiliyor olmamız `alembic/env.py`'deki
    `_adres()` sayesinde — adres sabit olsaydı bu test geliştirme
    veritabanını ezerdi.
    """
    ayar = Config(str(PROJE_KOKU / "alembic.ini"))
    ayar.set_main_option("script_location", str(PROJE_KOKU / "alembic"))
    ayar.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'migration.db'}")
    return ayar


def _adres(ayar: Config) -> str:
    return ayar.get_main_option("sqlalchemy.url") or ""


def test_upgrade_head_alti_tabloyu_olusturur(alembic_ayari: Config):
    command.upgrade(alembic_ayari, "head")

    engine = create_engine(_adres(alembic_ayari))
    tablolar = set(inspect(engine).get_table_names())
    engine.dispose()

    assert tablolar >= BEKLENEN_TABLOLAR


def test_tohum_migrationi_dort_esik_satiri_yazar(alembic_ayari: Config):
    """Boş bir veritabanında eşik tablosu dolu gelmeli.

    Tablo boş kalırsa her karar config'e düşer ve `ESIK_VARSAYILANA_DUSTU`
    üretir — çalışır ama alan bazlı eşik yönetimi hiç devreye girmez.
    """
    command.upgrade(alembic_ayari, "head")

    engine = create_engine(_adres(alembic_ayari))
    with engine.connect() as baglanti:
        satirlar = dict(
            baglanti.execute(text("select karar_tipi, daima_onay_gerektirir from policy")).all()
        )
    engine.dispose()

    assert set(satirlar) == TOHUMLANAN_TIPLER
    # Tasfiye ve tedarikçi değişimi tutar ne olursa olsun onaya gider.
    assert satirlar["stok.tasfiye"]
    assert satirlar["stok.tedarikci_degisim"]
    assert not satirlar["stok.siparis"]


def test_tohum_migrationi_mevcut_satirla_cakismaz(alembic_ayari: Config):
    """⭐ Tohum, o tip için satır zaten varsa patlamamalı.

    `karar_tipi` UNIQUE. Doğrudan `bulk_insert`, operatörün elle eklediği bir
    satır varsa IntegrityError verip migration'ı yarıda bırakır. Bu test o
    gerilemeyi yakalar.
    """
    # Şemayı kur, tohumdan hemen önce dur.
    command.upgrade(alembic_ayari, "0384bcdc8515")

    engine = create_engine(_adres(alembic_ayari))
    with engine.begin() as baglanti:
        baglanti.execute(
            text(
                "insert into policy (karar_tipi, esik_oto_uygula_tutar_tl, "
                "esik_oto_uygula_min_guven, daima_onay_gerektirir, aktif, "
                "guncelleme_zamani) values ('stok.siparis', 1.0, 0.1, 0, 1, "
                "'2026-01-01 00:00:00')"
            )
        )

    # Tohum migration'ı bu satırın üstüne gelmeli, patlamamalı.
    command.upgrade(alembic_ayari, "head")

    with engine.connect() as baglanti:
        satirlar = dict(
            baglanti.execute(text("select karar_tipi, esik_oto_uygula_tutar_tl from policy")).all()
        )
    engine.dispose()

    assert set(satirlar) == TOHUMLANAN_TIPLER
    # Önceden var olan satır KORUNMALI, üzerine yazılmamalı.
    assert satirlar["stok.siparis"] == 1.0


def test_downgrade_base_tum_tablolari_kaldirir(alembic_ayari: Config):
    """Bozuk `downgrade()` sonradan fark edilen bir mayındır."""
    command.upgrade(alembic_ayari, "head")
    command.downgrade(alembic_ayari, "base")

    engine = create_engine(_adres(alembic_ayari))
    tablolar = set(inspect(engine).get_table_names())
    engine.dispose()

    assert not (BEKLENEN_TABLOLAR & tablolar)


def test_upgrade_downgrade_upgrade_turu(alembic_ayari: Config):
    command.upgrade(alembic_ayari, "head")
    command.downgrade(alembic_ayari, "base")
    command.upgrade(alembic_ayari, "head")

    engine = create_engine(_adres(alembic_ayari))
    with engine.connect() as baglanti:
        adet = baglanti.execute(text("select count(*) from policy")).scalar()
    engine.dispose()

    assert adet == len(TOHUMLANAN_TIPLER)
