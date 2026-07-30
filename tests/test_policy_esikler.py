"""Eşiklerin `policy` tablosundan okunması (Faz 1 B1.4).

`tests/test_policy.py` bilinçli olarak DEĞİŞTİRİLMEDİ: politika mantığının
kendisi aynı kaldı, yalnızca eşiklerin kaynağı değişti. Bu dosya kaynağın
gerçekten DB olduğunu ve yedeğe düşüşün görünür olduğunu sınar.

En kritik ikisi:
· `test_db_esigi_configi_ezer` — tablo gerçekten yetkili mi
· `test_db_satiri_daima_onayi_ezer` — koda gömülü frozenset artık yetkisiz mi
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import KararTipi, OtonomiSeviyesi, PolitikaSonucu
from app.core.config import Ayarlar
from app.core.db import motor_olustur
from app.core.policy import (
    EsikKaynagi,
    PolitikaEsikleri,
    esikleri_yukle,
    politika_uygula,
)
from app.domain.stock.decide import decide_stub
from app.models import Base, Policy


@pytest.fixture
def oturum(tmp_path: Path) -> Iterator[Session]:
    engine: Engine = motor_olustur(f"sqlite:///{tmp_path / 'policy.db'}")
    Base.metadata.create_all(engine)
    fabrika = sessionmaker(bind=engine, expire_on_commit=False)
    with fabrika() as s:
        yield s
    engine.dispose()


def ayar_ile(seviye: OtonomiSeviyesi = OtonomiSeviyesi.THRESHOLD) -> Ayarlar:
    return Ayarlar(
        autonomy_level=seviye,
        esik_oto_uygula_tutar_tl=5_000.0,
        esik_oto_uygula_min_guven=0.85,
    )


def satir_ekle(
    oturum: Session,
    tip: KararTipi = KararTipi.STOK_SIPARIS,
    *,
    tutar: float = 5_000.0,
    guven: float = 0.85,
    daima_onay: bool = False,
    aktif: bool = True,
) -> Policy:
    satir = Policy(
        karar_tipi=tip,
        esik_oto_uygula_tutar_tl=tutar,
        esik_oto_uygula_min_guven=guven,
        daima_onay_gerektirir=daima_onay,
        aktif=aktif,
    )
    oturum.add(satir)
    oturum.commit()
    return satir


# --- Kaynak seçimi ------------------------------------------------------------


def test_satir_varsa_kaynak_db(oturum: Session):
    satir_ekle(oturum, tutar=1_234.0, guven=0.7)

    esikler = esikleri_yukle(oturum, KararTipi.STOK_SIPARIS, ayar_ile())

    assert esikler.kaynak is EsikKaynagi.DB
    assert esikler.tutar_tl == 1_234.0
    assert esikler.min_guven == 0.7


def test_satir_yoksa_config_yedegine_duser(oturum: Session):
    """Karar bloke olmaz — config'e düşer ama bu işaretlenir."""
    esikler = esikleri_yukle(oturum, KararTipi.STOK_SIPARIS, ayar_ile())

    assert esikler.kaynak is EsikKaynagi.CONFIG_YEDEK
    assert esikler.tutar_tl == 5_000.0


def test_pasif_satir_yok_sayilir(oturum: Session):
    """`aktif=False` satır okunmamalı — geçmiş eşikler silinmiyor, pasifleşiyor."""
    satir_ekle(oturum, tutar=1.0, aktif=False)

    esikler = esikleri_yukle(oturum, KararTipi.STOK_SIPARIS, ayar_ile())

    assert esikler.kaynak is EsikKaynagi.CONFIG_YEDEK
    assert esikler.tutar_tl == 5_000.0


def test_yedege_dusus_gerekce_kodlarinda_gorunur(oturum: Session):
    """⭐ Sessizce yedeğe düşmek, eşik tablosunun boş olduğunu fark etmemek demek."""
    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 100.0, "guven": 0.99})
    esikler = esikleri_yukle(oturum, aday.tip, ayar_ile())

    karar = politika_uygula(aday, ayar_ile(), esikler)

    assert "ESIK_VARSAYILANA_DUSTU" in karar.gerekce_kodlari


def test_db_kaynagi_uyari_kodu_uretmez(oturum: Session):
    satir_ekle(oturum)
    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 100.0, "guven": 0.99})
    esikler = esikleri_yukle(oturum, aday.tip, ayar_ile())

    karar = politika_uygula(aday, ayar_ile(), esikler)

    assert "ESIK_VARSAYILANA_DUSTU" not in karar.gerekce_kodlari


# --- Tablo gerçekten yetkili mi -----------------------------------------------


def test_db_esigi_configi_ezer(oturum: Session):
    """⭐ Config 5.000 diyor, DB 100 diyor — 200 TL'lik karar onaya gitmeli.

    Bu test kırmızıysa eşikler hâlâ config'den okunuyor ve B1.4 yapılmamış
    demektir.
    """
    satir_ekle(oturum, tutar=100.0)
    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 200.0, "guven": 0.99})

    esikler = esikleri_yukle(oturum, aday.tip, ayar_ile())
    karar = politika_uygula(aday, ayar_ile(), esikler)

    assert karar.sonuc is PolitikaSonucu.ONAY_KUYRUGU
    assert "TUTAR_ESIK_USTU" in karar.gerekce_kodlari
    assert karar.uygulandi is False


def test_db_satiri_daima_onayi_ezer(oturum: Session):
    """⭐ Koda gömülü `DAIMA_ONAY_GEREKTIREN` artık yetkili değil.

    `stok.siparis` o kümede yok, ama DB satırı `daima_onay_gerektirir=True`
    diyorsa 1 TL'lik sipariş bile onaya gitmeli.
    """
    satir_ekle(oturum, daima_onay=True)
    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 1.0, "guven": 0.99})

    esikler = esikleri_yukle(oturum, aday.tip, ayar_ile())
    karar = politika_uygula(aday, ayar_ile(), esikler)

    assert karar.sonuc is PolitikaSonucu.ONAY_KUYRUGU
    assert "TIP_DAIMA_ONAY" in karar.gerekce_kodlari


def test_esikler_karar_tipi_bazinda_ayrisir(oturum: Session):
    """Alan bazlı satırların amacı: tasfiye siparişle aynı kefeye girmesin."""
    satir_ekle(oturum, KararTipi.STOK_SIPARIS, tutar=10_000.0, daima_onay=False)
    satir_ekle(oturum, KararTipi.STOK_TASFIYE, tutar=10_000.0, daima_onay=True)

    siparis = esikleri_yukle(oturum, KararTipi.STOK_SIPARIS, ayar_ile())
    tasfiye = esikleri_yukle(oturum, KararTipi.STOK_TASFIYE, ayar_ile())

    assert siparis.daima_onay is False
    assert tasfiye.daima_onay is True


# --- Geriye dönük uyumluluk ---------------------------------------------------


def test_esikler_verilmezse_configden_turetilir():
    """DB erişilemese bile karar üretilmeye devam etmeli.

    `tests/test_policy.py`'nin tamamı bu yoldan geçiyor — o yüzden hiç
    değişmeden geçmeye devam ediyor.
    """
    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 100.0, "guven": 0.99})

    karar = politika_uygula(aday, ayar_ile())

    assert karar.sonuc is PolitikaSonucu.OTO_UYGULA
    assert karar.uygulandi is True
    # Kasıtlı config yolu bir sorun değil — uyarı kodu üretmemeli.
    assert "ESIK_VARSAYILANA_DUSTU" not in karar.gerekce_kodlari


def test_configden_daima_onay_frozenseti_yedek_olarak_calisir():
    """DB satırı yokken tasfiye hâlâ onaya gitmeli."""
    esikler = PolitikaEsikleri.configden(KararTipi.STOK_TASFIYE, ayar_ile())

    assert esikler.daima_onay is True
    assert esikler.kaynak is EsikKaynagi.CONFIG
