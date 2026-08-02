"""Faz 1 B1.4: policy tablosunu varsayilan esiklerle tohumla

Revision ID: 1d7cc4d395fb
Revises: 0384bcdc8515
Create Date: 2026-07-30 15:11:03.960473

Şema değil VERİ migration'ı. Amacı: `alembic upgrade head` her ortamda
kullanılabilir bir eşik tablosu bıraksın. Tablo boş kalırsa her karar
config'e düşer ve gerekçe kodlarında `ESIK_VARSAYILANA_DUSTU` görünür —
çalışır ama alan bazlı eşik yönetimi hiç devreye girmez.

Değerler bilinçli olarak burada sabit, `config.py`'den okunmuyor: migration
her ortamda AYNI başlangıç durumunu üretmek zorunda. Ortama özgü değer
istiyorsanız migration'dan sonra UPDATE atın — kodu dağıtmak gerekmez, zaten
eşikleri tabloya taşımanın amacı bu.
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1d7cc4d395fb"
down_revision: str | Sequence[str] | None = "0384bcdc8515"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# `app.models.Policy` yerine hafif bir tablo tanımı: migration'lar model
# dosyalarına bağlanmamalı. Model yarın değişirse bu migration hâlâ o günün
# şemasına göre çalışmak zorunda, yoksa geçmiş migration'lar bozulur.
policy_tablosu = sa.table(
    "policy",
    sa.column("karar_tipi", sa.String),
    sa.column("esik_oto_uygula_tutar_tl", sa.Float),
    sa.column("esik_oto_uygula_min_guven", sa.Float),
    sa.column("daima_onay_gerektirir", sa.Boolean),
    sa.column("aktif", sa.Boolean),
    sa.column("aciklama", sa.Text),
    sa.column("guncelleme_zamani", sa.DateTime),
)

TOHUM = (
    # (karar_tipi, tutar_tl, min_guven, daima_onay, aciklama)
    (
        "stok.siparis",
        5_000.0,
        0.85,
        False,
        "Eşik altı sipariş threshold modunda oto-uygulanabilir.",
    ),
    (
        "stok.tasfiye",
        5_000.0,
        0.85,
        True,
        "Tasfiye geri alınamaz — tutar ne olursa olsun insan onayı.",
    ),
    (
        "stok.tedarikci_degisim",
        5_000.0,
        0.85,
        True,
        "Tedarikçi değişimi ticari ilişkiyi etkiler — daima onay.",
    ),
    (
        "stok.aksiyon_yok",
        5_000.0,
        0.85,
        False,
        "Aksiyon gerektirmeyen karar; eşikler kullanılmaz ama satır bulunsun.",
    ),
)


def upgrade() -> None:
    """Eksik olan karar tipleri için varsayılan eşik satırını ekler.

    ⚠️ Önce mevcut satırlara bakılıyor. `karar_tipi` UNIQUE olduğu için
    doğrudan `bulk_insert`, o tip için zaten satır bulunan bir veritabanında
    IntegrityError verip migration'ı yarıda bırakır — operatör elle bir satır
    eklediyse veya tohum kısmen uygulanmışsa tam olarak bu olur. Veri
    migration'ları çakışmaya dayanıklı yazılmak zorunda.
    """
    baglanti = op.get_bind()
    mevcut = {satir[0] for satir in baglanti.execute(sa.text("select karar_tipi from policy"))}
    eklenecek = [kayit for kayit in TOHUM if kayit[0] not in mevcut]

    if not eklenecek:
        return

    simdi = datetime.now()
    op.bulk_insert(
        policy_tablosu,
        [
            {
                "karar_tipi": tip,
                "esik_oto_uygula_tutar_tl": tutar,
                "esik_oto_uygula_min_guven": guven,
                "daima_onay_gerektirir": daima_onay,
                "aktif": True,
                "aciklama": aciklama,
                "guncelleme_zamani": simdi,
            }
            for tip, tutar, guven, daima_onay, aciklama in eklenecek
        ],
    )


def downgrade() -> None:
    """Tohumlanan dört karar tipinin satırlarını siler.

    `delete from policy` YAZILMIYOR: operatörün eklediği BAŞKA karar tipleri
    korunuyor.

    ⚠️ Sınır: bu dört tipten birinin satırı migration'dan önce zaten varsa,
    geri alma onu da siler. Migration hangi satırı kendisinin eklediğini
    bilmiyor — kimin eklediğini izlemek için ek bir kolon gerekirdi ve tohum
    verisi için bu maliyet gereksiz. Geri alma sonrası eşik tablosunun
    beklenen satırları taşıdığını elle kontrol edin.
    """
    eklenen = tuple(tip for tip, *_ in TOHUM)
    op.execute(
        policy_tablosu.delete().where(
            policy_tablosu.c.karar_tipi.in_(eklenen)  # type: ignore[attr-defined]
        )
    )
