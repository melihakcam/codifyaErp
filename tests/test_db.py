"""DB katmanı testleri (Faz 1 B1.2).

Bu testler bağlantının kurulduğunu değil, **SQLite'ın güvensiz
varsayılanlarının düzeltildiğini** sınar. En kritik olanı
`test_yabanci_anahtar_zorlanir`: pragma kapalı kalırsa hiçbir hata alınmaz,
sadece denetim izi sessizce tutarsızlaşır — yani bu testi kaybetmek bir
regresyonu görünmez kılar.

Gerçek dosya tabanlı SQLite kullanılır (`tmp_path`), bellek içi değil: pragma
davranışı ve WAL yalnızca dosyada gerçekten sınanabilir.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Ayarlar, OtonomiSeviyesi
from app.core.db import (
    OturumDep,
    motor_olustur,
    oturum_al,
    veritabani_adresi,
)
from app.core.policy import politika_uygula
from app.domain.stock.decide import decide_stub
from app.main import app
from app.models import Approval, Base, Decision


@pytest.fixture
def test_motoru(tmp_path: Path) -> Iterator[Engine]:
    """Geçici dosyada, şeması kurulmuş, gerçek pragma yolundan geçen engine."""
    engine = motor_olustur(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def test_oturumu(test_motoru: Engine) -> Iterator[Session]:
    fabrika = sessionmaker(bind=test_motoru, expire_on_commit=False)
    with fabrika() as oturum:
        yield oturum


def _karar_yaz(oturum: Session) -> Decision:
    aday = decide_stub()
    ayar = Ayarlar(
        autonomy_level=OtonomiSeviyesi.SHADOW,
        esik_oto_uygula_tutar_tl=5_000.0,
        esik_oto_uygula_min_guven=0.85,
    )
    karar = Decision.sozlesmeden(aday, politika_uygula(aday, ayar))
    oturum.add(karar)
    oturum.commit()
    return karar


# --- Adres çözme --------------------------------------------------------------


def test_sqlite_dizini_yoksa_olusturulur(tmp_path: Path):
    """`data/` silinmişse motor kurulmadan önce geri gelmeli."""
    olmayan = tmp_path / "hic" / "yok" / "codifya.db"
    assert not olmayan.parent.exists()

    veritabani_adresi(Ayarlar(database_url=f"sqlite:///{olmayan}"))

    assert olmayan.parent.exists()


def test_bellek_ici_adres_dizin_olusturmaya_calismaz():
    """`sqlite://` veya `:memory:` bir dosya değil — mkdir denenmemeli."""
    assert veritabani_adresi(Ayarlar(database_url="sqlite://")) == "sqlite://"


# --- SQLite pragmaları --------------------------------------------------------


def test_pragmalar_her_baglantida_acik(test_motoru: Engine):
    """Pragma bağlantı başınadır; havuzdan gelen ikinci bağlantı da açık olmalı."""
    for _ in range(2):
        with test_motoru.connect() as baglanti:
            assert baglanti.execute(text("PRAGMA foreign_keys")).scalar() == 1
            assert baglanti.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert baglanti.execute(text("PRAGMA busy_timeout")).scalar() == 5_000


def test_yabanci_anahtar_zorlanir(test_oturumu: Session):
    """⭐ Var olmayan bir karara onay satırı yazılamamalı.

    Pragma olmadan bu satır SESSİZCE yazılır: SQLite yabancı anahtarları
    varsayılan olarak zorlamaz. Modellerdeki `ondelete="CASCADE"` de o durumda
    süs olur.
    """
    test_oturumu.add(Approval(karar_id=uuid4()))

    with pytest.raises(IntegrityError):
        test_oturumu.commit()
    test_oturumu.rollback()


def test_karar_silinince_onay_satiri_da_silinir(test_oturumu: Session):
    """`ondelete="CASCADE"` gerçekten çalışıyor mu — pragma açık olduğuna göre."""
    karar = _karar_yaz(test_oturumu)
    test_oturumu.add(Approval(karar_id=karar.karar_id))
    test_oturumu.commit()
    assert test_oturumu.scalars(select(Approval)).all()

    # ORM'in kendi cascade'ini atlayıp DB'nin davranışını sınıyoruz.
    test_oturumu.execute(text("delete from decision"))
    test_oturumu.commit()

    assert test_oturumu.scalars(select(Approval)).all() == []


# --- Session davranışı --------------------------------------------------------


def test_commit_sonrasi_alanlar_okunabilir(test_oturumu: Session):
    """`expire_on_commit=False` olmadan burada DetachedInstanceError alınır."""
    karar = _karar_yaz(test_oturumu)
    test_oturumu.close()

    # Oturum kapalı; yine de commit anındaki değerler bellekte durmalı.
    assert karar.tahmini_tutar_tl == 5_700.0
    assert karar.adaya_cevir().izinli_sayilar() == decide_stub().izinli_sayilar()


# --- FastAPI dependency -------------------------------------------------------


def test_endpointten_alinan_oturumla_kayit_yazilabilir(test_motoru: Engine):
    """⭐ B1.2'nin kabul ölçütü: endpoint'ten DB session alınıp kayıt yazılıyor.

    `dependency_overrides` kalıbı B1.5'te onay kuyruğu endpoint'lerini test
    ederken de kullanılacak — asıl uygulama motoruna hiç dokunmadan.
    """
    fabrika = sessionmaker(bind=test_motoru, expire_on_commit=False)
    test_app = FastAPI()

    @test_app.post("/deneme/karar")
    def karar_yaz(oturum: OturumDep) -> dict[str, str]:
        karar = _karar_yaz(oturum)
        return {"karar_id": str(karar.karar_id)}

    @test_app.get("/deneme/sayi")
    def karar_sayisi(oturum: OturumDep) -> dict[str, int]:
        return {"adet": len(oturum.scalars(select(Decision)).all())}

    def test_oturumu_ver() -> Iterator[Session]:
        with fabrika() as oturum:
            yield oturum

    test_app.dependency_overrides[oturum_al] = test_oturumu_ver
    istemci = TestClient(test_app)

    yazma = istemci.post("/deneme/karar")
    assert yazma.status_code == 200
    assert yazma.json()["karar_id"]

    assert istemci.get("/deneme/sayi").json()["adet"] == 1


def test_health_db_baglantiyi_ve_fkyi_bildirir(test_motoru: Engine):
    """`/health/db` canlıda FK zorlamasının açık olduğunu göstermeli."""
    fabrika = sessionmaker(bind=test_motoru, expire_on_commit=False)

    def test_oturumu_ver() -> Iterator[Session]:
        with fabrika() as oturum:
            yield oturum

    app.dependency_overrides[oturum_al] = test_oturumu_ver
    try:
        govde = TestClient(app).get("/health/db").json()
    finally:
        app.dependency_overrides.clear()

    assert govde["durum"] == "baglandi"
    assert govde["yabanci_anahtar_zorlamasi"] is True
    assert govde["kayitli_karar"] == 0
