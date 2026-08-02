"""Alembic çalışma ortamı.

Sahip: Kişi B · Faz 1 B1.1

Şablondan üç değişiklik yapıldı:

1. `target_metadata` → `app.models.Base.metadata`. Autogenerate'in "hangi
   tablolar olmalı" bilgisi buradan gelir.
2. Veritabanı adresi `alembic.ini` yerine `app/core/db.veritabani_adresi()`
   üzerinden okunuyor. Tek doğruluk kaynağı ilkesi: `.env`'de Postgres'e
   geçince alembic de otomatik takip etsin, servisle ayrışmasın.
3. `render_as_batch=True` — SQLite'ın ALTER TABLE desteği çok kısıtlıdır
   (kolon silme/tip değiştirme yok). Bu ayar alembic'i "yeni tablo oluştur,
   veriyi kopyala, eskiyi sil, yeniden adlandır" kalıbına geçirir. Şimdi
   açılmazsa ilk kolon değişikliğinde migration patlar.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.db import veritabani_adresi
from app.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _adres() -> str:
    """Çağıran taraf adres verdiyse onu, vermediyse `config.py`'dekini kullanır.

    `alembic.ini`'de `sqlalchemy.url` yok, dolayısıyla normal komut satırı
    kullanımında burası her zaman `veritabani_adresi()`'ne düşer.

    Enjeksiyon imkânı testler için: `tests/test_migrations.py` migration'ları
    geçici bir dosyaya uygulayıp gerçekten çalıştıklarını sınıyor. Adres sabit
    olsaydı o test geliştirme veritabanını ezerdi.
    """
    return config.get_main_option("sqlalchemy.url") or veritabani_adresi()


def run_migrations_offline() -> None:
    """SQL'i çalıştırmadan ekrana basar (`alembic upgrade head --sql`)."""
    context.configure(
        url=_adres(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Gerçek bağlantı açıp migration'ları uygular."""
    config.set_main_option("sqlalchemy.url", _adres())

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
