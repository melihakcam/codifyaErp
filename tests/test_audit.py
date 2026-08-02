"""Denetim kaydı testleri (Faz 1 B1.3).

Projenin kuralı "denetim kaydı olmayan karar yolu merge edilmez". Bu dosya o
kuralın kodda gerçekten zorlandığını sınar:

· `test_karar_ve_denetim_ayni_islemde` — geri alma ikisini birlikte siliyor mu
· `test_girdi_hashi_karar_kimligine_bagli_degil` — hash karşılaştırılabilir mi
· `test_gerekce_yoksa_guard_sonucu_atlandi` — "çalışmadı" ile "geçti" ayrı mı
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import (
    DecisionCandidate,
    Gerekce,
    GuardSonucu,
    KararSonucu,
    OtonomiSeviyesi,
    PolitikaKarari,
)
from app.core.audit import denetim_yaz, girdi_hash_hesapla, karari_kaydet
from app.core.config import Ayarlar
from app.core.db import motor_olustur
from app.core.policy import politika_uygula
from app.domain.stock.decide import decide_stub
from app.llm.explain import explain_stub
from app.models import Base, Decision, DecisionAudit


@pytest.fixture
def oturum(tmp_path: Path) -> Iterator[Session]:
    engine: Engine = motor_olustur(f"sqlite:///{tmp_path / 'audit.db'}")
    Base.metadata.create_all(engine)
    fabrika = sessionmaker(bind=engine, expire_on_commit=False)
    with fabrika() as s:
        yield s
    engine.dispose()


def _aday_ve_politika() -> tuple[DecisionCandidate, PolitikaKarari]:
    aday = decide_stub()
    ayar = Ayarlar(
        autonomy_level=OtonomiSeviyesi.SHADOW,
        esik_oto_uygula_tutar_tl=5_000.0,
        esik_oto_uygula_min_guven=0.85,
    )
    return aday, politika_uygula(aday, ayar)


# --- Girdi hash'i -------------------------------------------------------------


def test_girdi_hashi_64_hex_karakter():
    h = girdi_hash_hesapla(decide_stub().ozellikler)
    assert len(h) == 64
    assert set(h) <= set("0123456789abcdef")


def test_ayni_girdi_ayni_hash():
    assert girdi_hash_hesapla(decide_stub().ozellikler) == girdi_hash_hesapla(
        decide_stub().ozellikler
    )


def test_girdi_hashi_karar_kimligine_bagli_degil():
    """⭐ Hash yalnızca özelliklerden çıkmalı.

    `karar_id` ve `uretim_zamani` her çalıştırmada değişir. Hash'e girerlerse
    iki koşu asla eşleşmez ve "aynı girdiye aynı kararı verdik mi" sorusu
    cevaplanamaz hale gelir.
    """
    birinci = decide_stub()
    ikinci = decide_stub()

    assert birinci.karar_id != ikinci.karar_id
    assert girdi_hash_hesapla(birinci.ozellikler) == girdi_hash_hesapla(ikinci.ozellikler)


def test_ozellik_degisince_hash_degisir():
    ozgun = decide_stub().ozellikler
    degisen = ozgun.model_copy(update={"eldeki_stok": ozgun.eldeki_stok + 1})

    assert girdi_hash_hesapla(degisen) != girdi_hash_hesapla(ozgun)


# --- Denetim satırının eksiksizliği -------------------------------------------


def test_denetim_satiri_eksiksiz_yazilir(oturum: Session):
    """Görev dosyasının saydığı altı alanın hepsi dolu olmalı."""
    aday, politika = _aday_ve_politika()
    karari_kaydet(oturum, aday, politika)
    oturum.commit()

    kayit = oturum.scalars(select(DecisionAudit)).one()

    assert kayit.karar_id == aday.karar_id
    assert kayit.girdi_hash == girdi_hash_hesapla(aday.ozellikler)
    assert len(kayit.tetiklenen_kurallar) == len(aday.tetiklenen_kurallar)
    assert kayit.model_surumleri == aday.model_surumleri
    assert kayit.cikti, "çıktı anlık görüntüsü boş kalmamalı"
    assert kayit.guard_sonucu is GuardSonucu.ATLANDI
    assert kayit.zaman is not None


def test_cikti_karar_sonucuna_geri_cevrilebilir(oturum: Session):
    """Denetim satırından ERP'nin o an gördüğü cevap yeniden kurulabilmeli."""
    aday, politika = _aday_ve_politika()
    gerekce = explain_stub(aday)
    karari_kaydet(oturum, aday, politika, gerekce)
    oturum.commit()

    kayit = oturum.scalars(select(DecisionAudit)).one()
    geri = KararSonucu.model_validate(kayit.cikti)

    assert geri.aday.karar_id == aday.karar_id
    assert geri.politika.uygulandi is politika.uygulandi
    assert geri.gerekce is not None
    assert geri.gerekce.metin == gerekce.metin
    # Sözleşme gidiş-dönüşü: guard'ın dayanağı burada da bozulmamalı.
    assert geri.aday.izinli_sayilar() == aday.izinli_sayilar()


# --- Guard sonucu -------------------------------------------------------------


def test_gerekce_yoksa_guard_sonucu_atlandi(oturum: Session):
    """ "Guard çalışmadı" ile "guard geçti" aynı değere düşmemeli."""
    aday, politika = _aday_ve_politika()
    karari_kaydet(oturum, aday, politika, gerekce=None)
    oturum.commit()

    kayit = oturum.scalars(select(DecisionAudit)).one()
    assert kayit.guard_sonucu is GuardSonucu.ATLANDI
    assert kayit.reddedilen_sayilar == []


def test_guard_sonucu_ve_reddedilen_sayilar_gerekceden_okunur(oturum: Session):
    """Ayrı parametre olarak istenmiyor — iki kaynak ayrışır."""
    aday, politika = _aday_ve_politika()
    karari_kaydet(oturum, aday, politika)
    oturum.commit()

    gerekce = Gerekce(
        karar_id=aday.karar_id,
        metin="Uydurma sayı içeren metin.",
        guard_sonucu=GuardSonucu.SABLONA_DUSTU,
        reddedilen_sayilar=[9999.0, 73.5],
    )
    denetim_yaz(oturum, aday, politika, gerekce)
    oturum.commit()

    kayit = oturum.scalars(select(DecisionAudit).order_by(DecisionAudit.id)).all()[-1]
    assert kayit.guard_sonucu is GuardSonucu.SABLONA_DUSTU
    assert kayit.reddedilen_sayilar == [9999.0, 73.5]


def test_yetim_denetim_satiri_yazilamaz(oturum: Session):
    """Var olmayan bir karara denetim satırı eklenemez.

    B1.2'deki `foreign_keys=ON` pragması bunu zorluyor. Pragma kapansa bu
    satır sessizce yazılır ve denetim izi var olmayan bir kararı işaret eder.
    """
    from sqlalchemy.exc import IntegrityError

    aday, politika = _aday_ve_politika()  # kararı DB'ye YAZMIYORUZ
    denetim_yaz(oturum, aday, politika)

    with pytest.raises(IntegrityError):
        oturum.commit()
    oturum.rollback()


def test_ikinci_cagri_yeni_satir_ekler(oturum: Session):
    """Gerekçe sonradan üretildiğinde ilk satır güncellenmez, ikincisi eklenir.

    Guard'ın ilk denemede neyi reddettiği kaybolmamalı.
    """
    aday, politika = _aday_ve_politika()
    karari_kaydet(oturum, aday, politika)
    oturum.commit()

    denetim_yaz(oturum, aday, politika, explain_stub(aday))
    oturum.commit()

    kayitlar = oturum.scalars(select(DecisionAudit).order_by(DecisionAudit.id)).all()
    assert len(kayitlar) == 2
    assert [k.guard_sonucu for k in kayitlar] == [
        GuardSonucu.ATLANDI,
        GuardSonucu.SABLONA_DUSTU,
    ]


# --- Atomiklik ----------------------------------------------------------------


def test_karar_ve_denetim_ayni_islemde(oturum: Session):
    """⭐ Geri alma ikisini de silmeli — yarım yazılmış karar oluşamaz.

    Ayrı işlemlerde commit edilseydi aradaki bir çökme, denetim izi olmayan
    bir karar bırakırdı. Tam olarak engellemek istediğimiz durum bu.
    """
    aday, politika = _aday_ve_politika()
    karari_kaydet(oturum, aday, politika)
    oturum.flush()

    assert oturum.scalars(select(Decision)).all()
    assert oturum.scalars(select(DecisionAudit)).all()

    oturum.rollback()

    assert oturum.scalars(select(Decision)).all() == []
    assert oturum.scalars(select(DecisionAudit)).all() == []


def test_karari_kaydet_gerekce_kolonlarini_doldurur(oturum: Session):
    aday, politika = _aday_ve_politika()
    gerekce = explain_stub(aday)
    karar, _ = karari_kaydet(oturum, aday, politika, gerekce)
    oturum.commit()

    assert karar.gerekce_metni == gerekce.metin
    assert karar.guard_sonucu is GuardSonucu.SABLONA_DUSTU
    assert karar.gerekce_uretim_ms == 0
