"""SQLAlchemy tablo testleri (Faz 1 B1.1).

Bu dosya "tablo oluştu mu" sorusunu değil, **sözleşme gidiş-dönüşü bozulmuyor
mu** sorusunu sınar. En kritik testi `test_gidis_donus_izinli_sayilari_korur`:
guard (Faz 2 B2.5) izinli sayı kümesini DB'den okunan karardan çıkaracak.
Kayıtta bir alan eksilirse küme değişir ve guard doğru gerekçeyi reddeder —
bu test o sessiz bozulmayı yakalar.

Testler bellek içi SQLite kullanır, `data/codifya.db`'ye dokunmaz.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.contracts import (
    Alan,
    DecisionCandidate,
    GuardSonucu,
    KararTipi,
    OtonomiSeviyesi,
    PolitikaKarari,
)
from app.core.config import Ayarlar
from app.core.policy import politika_uygula
from app.domain.stock.decide import decide_stub
from app.models import (
    Approval,
    Base,
    Decision,
    DecisionAudit,
    Feedback,
    GeriBildirimTuru,
    Insight,
    OnayDurumu,
    Policy,
)

BEKLENEN_TABLOLAR = {
    "decision",
    "decision_audit",
    "approval",
    "feedback",
    "policy",
    "insight",
}


@pytest.fixture
def oturum() -> Iterator[Session]:
    """Bellek içi, her testte sıfırdan kurulan bir veritabanı.

    `StaticPool` şart: bellek içi SQLite'ta her yeni bağlantı BOŞ bir
    veritabanıdır. Havuz tek bağlantıyı yeniden kullanmazsa `create_all` ile
    kurulan tablolar sorgu anında yok olur.
    """
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
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


# --- Şema ---------------------------------------------------------------------


def test_alti_tablo_da_metadataya_kayitli():
    """Bir tablo `app/models/__init__.py`'de import edilmezse alembic onu görmez."""
    assert set(Base.metadata.tables) >= BEKLENEN_TABLOLAR


# --- Sözleşme gidiş-dönüşü ----------------------------------------------------


def test_gidis_donus_izinli_sayilari_korur(oturum: Session):
    """⭐ Guard'ın dayanağı: DB'den okunan karar aynı izinli sayı kümesini vermeli.

    Gerekçe tembel üretiliyor — guard saatler sonra çalışıp kümeyi bu satırdan
    çıkaracak. Küme değişirse guard doğru metni reddeder ve hata gerekçe
    üretiminde değil DB kaydında olur; bulmak çok zordur.
    """
    aday, politika = _aday_ve_politika()
    oturum.add(Decision.sozlesmeden(aday, politika))
    oturum.commit()
    oturum.expunge_all()

    okunan = oturum.scalars(select(Decision)).one().adaya_cevir()

    assert okunan.izinli_sayilar() == aday.izinli_sayilar()
    assert okunan.ozellikler == aday.ozellikler
    assert okunan.tetiklenen_kurallar == aday.tetiklenen_kurallar
    assert okunan.karar_id == aday.karar_id


def test_politika_gidis_donusu_sonuc_uygulandi_ayrimini_korur(oturum: Session):
    """Shadow modda `sonuc` OTO_UYGULA olabilir ama `uygulandi` False kalır."""
    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 100.0, "guven": 0.99})
    ayar = Ayarlar(
        autonomy_level=OtonomiSeviyesi.SHADOW,
        esik_oto_uygula_tutar_tl=5_000.0,
        esik_oto_uygula_min_guven=0.85,
    )
    politika = politika_uygula(aday, ayar)

    oturum.add(Decision.sozlesmeden(aday, politika))
    oturum.commit()
    oturum.expunge_all()

    geri = oturum.scalars(select(Decision)).one().politikaya_cevir()
    assert geri.sonuc is politika.sonuc
    assert geri.uygulandi is False
    assert "SHADOW_UYGULANMADI" in geri.gerekce_kodlari


def test_enumlar_dbye_deger_olarak_yazilir(oturum: Session):
    """DB'de `stok.siparis` yazmalı, `STOK_SIPARIS` değil.

    `enum_kolonu()`'ndaki `values_callable` bunu sağlar. Olmadan politika
    tablosundaki anahtar ile sözleşmedeki `.value` ayrışır.
    """
    aday, politika = _aday_ve_politika()
    oturum.add(Decision.sozlesmeden(aday, politika))
    oturum.commit()

    ham = oturum.execute(text("select alan, tip, politika_sonucu from decision")).one()
    assert ham.alan == "stok"
    assert ham.tip == "stok.siparis"
    assert ham.politika_sonucu == politika.sonuc.value


def test_enumlar_python_tipi_olarak_geri_gelir(oturum: Session):
    aday, politika = _aday_ve_politika()
    oturum.add(Decision.sozlesmeden(aday, politika))
    oturum.commit()
    oturum.expunge_all()

    okunan = oturum.scalars(select(Decision)).one()
    assert isinstance(okunan.alan, Alan)
    assert isinstance(okunan.tip, KararTipi)
    assert isinstance(okunan.otonomi_seviyesi, OtonomiSeviyesi)


# --- Gerekçe alanları ---------------------------------------------------------


def test_gerekcesiz_karar_gecerlidir(oturum: Session):
    """ERP asla LLM'i beklemez: gerekçe kolonları NULL kalabilir."""
    aday, politika = _aday_ve_politika()
    oturum.add(Decision.sozlesmeden(aday, politika))
    oturum.commit()
    oturum.expunge_all()

    okunan = oturum.scalars(select(Decision)).one()
    assert okunan.gerekce_metni is None
    assert okunan.guard_sonucu is None


# --- Denetim izi --------------------------------------------------------------


def test_denetim_kaydi_varsayilan_guard_sonucu_atlandi(oturum: Session):
    """Gerekçe hiç üretilmediyse ATLANDI — "guard geçti" ile karışmasın."""
    aday, politika = _aday_ve_politika()
    oturum.add(Decision.sozlesmeden(aday, politika))
    oturum.add(
        DecisionAudit(
            karar_id=aday.karar_id,
            girdi_hash="0" * 64,
            tetiklenen_kurallar=[k.model_dump(mode="json") for k in aday.tetiklenen_kurallar],
            model_surumleri=aday.model_surumleri,
            cikti={},
        )
    )
    oturum.commit()
    oturum.expunge_all()

    kayit = oturum.scalars(select(DecisionAudit)).one()
    assert kayit.guard_sonucu is GuardSonucu.ATLANDI
    assert kayit.reddedilen_sayilar == []


def test_bir_karara_birden_cok_denetim_satiri_yazilabilir(oturum: Session):
    """Gerekçe iki denemede üretildiyse iki satır olur — ilk red kaybolmaz."""
    aday, politika = _aday_ve_politika()
    karar = Decision.sozlesmeden(aday, politika)
    oturum.add(karar)
    for sonuc, reddedilen in (
        (GuardSonucu.YENIDEN_URETILDI, [9999.0]),
        (GuardSonucu.SABLONA_DUSTU, [73.5]),
    ):
        oturum.add(
            DecisionAudit(
                karar_id=aday.karar_id,
                girdi_hash="0" * 64,
                tetiklenen_kurallar=[],
                model_surumleri={},
                cikti={},
                guard_sonucu=sonuc,
                reddedilen_sayilar=reddedilen,
            )
        )
    oturum.commit()
    oturum.refresh(karar)

    assert len(karar.audit_kayitlari) == 2
    assert [k.guard_sonucu for k in karar.audit_kayitlari] == [
        GuardSonucu.YENIDEN_URETILDI,
        GuardSonucu.SABLONA_DUSTU,
    ]


# --- Kısıtlar -----------------------------------------------------------------


def test_ayni_karar_kuyruga_iki_kez_giremez(oturum: Session):
    """Gecelik iş aynı SKU'yu tekrar tararsa DB reddetmeli — koda güvenmiyoruz."""
    aday, politika = _aday_ve_politika()
    oturum.add(Decision.sozlesmeden(aday, politika))
    oturum.add(Approval(karar_id=aday.karar_id))
    oturum.commit()

    oturum.add(Approval(karar_id=aday.karar_id))
    with pytest.raises(IntegrityError):
        oturum.commit()
    oturum.rollback()


def test_ayni_karara_birden_cok_geri_bildirim_yazilabilir(oturum: Session):
    """Feedback'te UNIQUE YOK — her yorum sonraki eğitim turunun verisi."""
    aday, politika = _aday_ve_politika()
    oturum.add(Decision.sozlesmeden(aday, politika))
    oturum.add(Feedback(karar_id=aday.karar_id, tur=GeriBildirimTuru.RED))
    oturum.add(
        Feedback(
            karar_id=aday.karar_id,
            tur=GeriBildirimTuru.DUZELTME,
            duzeltilmis_aksiyon={"siparis_miktari": 800},
        )
    )
    oturum.commit()

    assert len(oturum.scalars(select(Feedback)).all()) == 2


def test_ayni_karar_tipi_icin_iki_politika_satiri_olamaz(oturum: Session):
    """Eşik tablosunda çelişki kabul edilemez — güvenlik kapısı burası."""
    for _ in range(2):
        oturum.add(
            Policy(
                karar_tipi=KararTipi.STOK_SIPARIS,
                esik_oto_uygula_tutar_tl=5_000.0,
                esik_oto_uygula_min_guven=0.85,
            )
        )
    with pytest.raises(IntegrityError):
        oturum.commit()
    oturum.rollback()


# --- Varsayılanlar ------------------------------------------------------------


def test_onay_varsayilan_durumu_bekliyor(oturum: Session):
    aday, politika = _aday_ve_politika()
    oturum.add(Decision.sozlesmeden(aday, politika))
    oturum.add(Approval(karar_id=aday.karar_id))
    oturum.commit()
    oturum.expunge_all()

    onay = oturum.scalars(select(Approval)).one()
    assert onay.durum is OnayDurumu.BEKLIYOR
    assert onay.karar_zamani is None
    assert onay.karar_veren is None


def test_icgoru_karara_bagli_olmadan_yazilabilir(oturum: Session):
    """Toplu bulgular tek bir karara ait değildir — `karar_id` nullable."""
    oturum.add(
        Insight(
            kosu_id=uuid4(),
            alan=Alan.STOK,
            baslik="23 SKU'da tedarikçi gecikmesi arttı",
            metin="Son 30 günde ortalama gecikme yükseldi.",
            onem_skoru=0.7,
        )
    )
    oturum.commit()

    assert oturum.scalars(select(Insight)).one().karar_id is None
