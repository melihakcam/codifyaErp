"""SQLAlchemy engine + session factory + FastAPI dependency.

Sahip: Kişi B · Faz 1 B1.2

Üç sorumluluk:

1. Motoru **bir kez** kurmak (`motor()` — `lru_cache`'li). Her istekte yeni
   engine kurmak bağlantı havuzunu anlamsız kılar.
2. SQLite'ın güvensiz varsayılanlarını düzeltmek (`_sqlite_pragmalari`).
3. Endpoint'lere istek başına bir `Session` vermek (`OturumDep`).

⚠️ Şema burada oluşturulmaz. `Base.metadata.create_all()` çağrısı YOK ve
olmayacak: şemanın tek doğruluk kaynağı alembic migration'larıdır. İkisi
birlikte kullanılırsa migration'ı atlayan bir tablo sessizce oluşur ve
`alembic upgrade head` bir daha tutarlı çalışmaz.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Ayarlar, ayarlar

SQLITE_ONEKI = "sqlite"


def veritabani_adresi(ayar: Ayarlar | None = None) -> str:
    """Bağlantı adresini döndürür; SQLite ise dosyanın dizinini garanti eder.

    `config.py`'deki varsayılan `data/codifya.db`. Temiz klonda `data/` dizini
    `.gitkeep` sayesinde var, ama kullanıcı silmiş olabilir — SQLite var
    olmayan bir dizine dosya açamaz ve hatası ("unable to open database file")
    sebebi göstermez. Bir `mkdir` ile yarım saatlik kafa karışıklığı önlenir.

    Alembic de (`alembic/env.py`) bu fonksiyonu çağırır: adres tek yerden
    çözülsün, servis ile migration ayrışmasın.
    """
    ayar = ayar or ayarlar()
    url = ayar.database_url

    if url.startswith(SQLITE_ONEKI):
        dosya_yolu = url.split("///", 1)[-1]
        # ":memory:" gibi dosya olmayan adreslerde dizin yoktur, dokunma.
        if dosya_yolu and ":memory:" not in dosya_yolu:
            Path(dosya_yolu).parent.mkdir(parents=True, exist_ok=True)

    return url


def _sqlite_pragmalari(dbapi_baglanti: Any, _baglanti_kaydi: Any) -> None:
    """Her yeni SQLite bağlantısında çalışır. Üçü de varsayılanı düzeltiyor.

    · `foreign_keys=ON` — ⚠️ SQLite yabancı anahtarları VARSAYILAN OLARAK
      ZORLAMAZ. Bu satır olmadan modellerdeki `ondelete="CASCADE"` süstür:
      var olmayan bir `karar_id` ile `approval` satırı yazılabilir ve denetim
      izi sessizce tutarsız hale gelir. Pragma bağlantı başınadır — bir kez
      açmak yetmez, o yüzden `connect` olayına bağlı.

    · `journal_mode=WAL` — okuyucuyla yazıcıyı birbirini kilitlemekten kurtarır.
      Faz 2'de gecelik iş 2.000 SKU yazarken API okumaya devam edecek;
      varsayılan `delete` kipinde bu "database is locked" demek.

    · `busy_timeout=5000` — kilit varsa hemen hata vermek yerine 5 sn bekler.
    """
    imlec = dbapi_baglanti.cursor()
    imlec.execute("PRAGMA foreign_keys=ON")
    imlec.execute("PRAGMA journal_mode=WAL")
    imlec.execute("PRAGMA busy_timeout=5000")
    imlec.close()


def motor_olustur(url: str) -> Engine:
    """Verilen adres için engine kurar. Saf fonksiyon — testler bunu çağırır.

    `motor()`'dan ayrı olması bilinçli: `lru_cache`'li singleton'ı test etmek
    zordur, saf fabrikayı geçici bir dosyayla çağırmak kolaydır. Böylece
    testler de gerçek pragma yolundan geçer, ayrı bir kurulum taklit etmez.
    """
    baglanti_argumanlari: dict[str, Any] = {}

    if url.startswith(SQLITE_ONEKI):
        # FastAPI senkron endpoint'leri bir thread havuzunda koşturur; bağlantı
        # bir thread'de açılıp başkasında kullanılabilir. SQLite sürücüsü
        # varsayılan olarak buna itiraz eder.
        baglanti_argumanlari["check_same_thread"] = False

    olusan = create_engine(url, connect_args=baglanti_argumanlari)

    if url.startswith(SQLITE_ONEKI):
        event.listen(olusan, "connect", _sqlite_pragmalari)

    return olusan


@lru_cache
def motor() -> Engine:
    """Uygulamanın tek engine'i. Adresi `config.py`'den alır."""
    return motor_olustur(veritabani_adresi())


@lru_cache
def oturum_fabrikasi() -> sessionmaker[Session]:
    """Session üreten fabrika.

    `expire_on_commit=False` bilinçli: varsayılan davranışta `commit()` tüm
    nesneleri "bayat" işaretler ve sonraki her alan erişimi DB'ye yeni sorgu
    atar. İstek bittiğinde oturum kapandığı için o sorgu
    `DetachedInstanceError` ile patlar — endpoint `commit()` sonrası nesneyi
    cevaba koyduğunda tam olarak bu olur. Kapatınca commit sonrası değerler
    bellekte kalır.
    """
    return sessionmaker(bind=motor(), expire_on_commit=False)


def oturum_al() -> Iterator[Session]:
    """İstek başına bir Session veren FastAPI dependency'si.

    ⚠️ Burada `commit()` YOK — bilinçli. Otomatik commit, endpoint'in yarım
    bıraktığı işi de kalıcı hale getirir ve kaydın hangi noktada olduğunu kodu
    okurken göremezsin. Kaydı endpoint açıkça yapar.

    Hata durumunda `with` bloğu oturumu kapatır, kapanış açık işlemi geri alır.
    Yani "exception fırladı ama yarım veri yazıldı" durumu oluşmaz.
    """
    with oturum_fabrikasi()() as oturum:
        yield oturum


OturumDep = Annotated[Session, Depends(oturum_al)]
