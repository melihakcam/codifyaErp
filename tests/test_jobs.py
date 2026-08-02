"""Gecelik iş ve tetikleyici testleri (Faz 2 B2.6).

⚠️ Hiçbiri gerçek modeli çalıştırmaz — gerekçe üreteci enjekte edilebilir
olduğu için şablonla (veya sahte bir fonksiyonla) test ediliyor.

Kabul ölçütü ("2.000 SKU < 10 dakika") gerçek kural motorunu gerektiriyor,
yani Kişi A'nın `stok_karari_uret()`'inin merge edilmesini. Buradaki testler
o ölçümün dayandığı mantığı sınar: sıralama, üst-N kesme, denetim izi,
eşik önbelleği.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.contracts import (
    DecisionCandidate,
    Gerekce,
    GuardSonucu,
    KararTipi,
    OtonomiSeviyesi,
)
from app.core.config import Ayarlar
from app.core.db import motor_olustur
from app.domain.stock.decide import decide_stub
from app.jobs.nightly import KosuOzeti, gecelik_tarama
from app.jobs.triggers import (
    Tetikleyici,
    gunluk_siparis_toplami,
    tetiklenmeleri_kaydet,
    tetikleyicileri_degerlendir,
)
from app.models import Approval, Base, Decision, DecisionAudit, Insight, Policy


@pytest.fixture
def ayar() -> Ayarlar:
    return Ayarlar(
        autonomy_level=OtonomiSeviyesi.SHADOW,
        esik_oto_uygula_tutar_tl=5_000.0,
        esik_oto_uygula_min_guven=0.85,
        gecelik_gerekce_ust_n=3,
        tetik_buyuk_siparis_tutar_tl=25_000.0,
        tetik_kritik_stok_gun=3.0,
        tetik_gunluk_siparis_limiti_tl=250_000.0,
    )


@pytest.fixture
def oturum(tmp_path: Path) -> Iterator[Session]:
    engine: Engine = motor_olustur(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    fabrika = sessionmaker(bind=engine, expire_on_commit=False)
    with fabrika() as s:
        for tip in KararTipi:
            s.add(
                Policy(
                    karar_tipi=tip,
                    esik_oto_uygula_tutar_tl=5_000.0,
                    esik_oto_uygula_min_guven=0.85,
                    daima_onay_gerektirir=tip
                    in (KararTipi.STOK_TASFIYE, KararTipi.STOK_TEDARIKCI_DEGISIM),
                )
            )
        s.commit()
        yield s
    engine.dispose()


def adaylar(n: int) -> list[DecisionCandidate]:
    """Risk skorları birbirinden farklı n aday üretir.

    Tutar değişince risk skoru da değişiyor (risk = tutar × belirsizlik),
    böylece "gerekçe en riskli karara gider" testi anlamlı oluyor.
    Her adaya yeni bir `karar_id` veriliyor; aksi halde hepsi aynı satıra
    yazılmaya çalışılırdı.
    """
    temel = decide_stub()
    return [
        temel.model_copy(update={"karar_id": uuid4(), "tahmini_tutar_tl": (i + 1) * 1_000.0})
        for i in range(n)
    ]


# --- Gecelik tarama -----------------------------------------------------------


def test_tum_kararlar_kaydedilir(oturum: Session, ayar: Ayarlar):
    liste = adaylar(10)

    ozet = gecelik_tarama(oturum, ayar, karar_ureteci=lambda: liste)

    assert ozet.taranan == 10
    assert len(oturum.scalars(select(Decision)).all()) == 10


def test_gerekce_yalnizca_ust_n_icin_uretilir(oturum: Session, ayar: Ayarlar):
    """⭐ Mimarinin can alıcı noktası.

    Her karar için gerekçe üretmek 2.000 SKU'da ~5 saat sürerdi. Gerekçe
    yalnızca insanın gerçekten baktığı ilk N karar için üretilir.
    """
    liste = adaylar(10)

    ozet = gecelik_tarama(oturum, ayar, karar_ureteci=lambda: liste)

    assert ayar.gecelik_gerekce_ust_n == 3
    assert ozet.gerekce_uretilen == 3
    assert ozet.gerekce_atlanan == 7

    gerekceli = oturum.scalars(select(Decision).where(Decision.gerekce_metni.is_not(None))).all()
    assert len(gerekceli) == 3


def test_gerekce_en_riskli_kararlara_gider(oturum: Session, ayar: Ayarlar):
    """İnsanın zamanı kısıtlı — gerekçe en yüksek riskli karara yazılmalı."""
    liste = adaylar(10)

    gecelik_tarama(oturum, ayar, karar_ureteci=lambda: liste)

    gerekceli = oturum.scalars(select(Decision).where(Decision.gerekce_metni.is_not(None))).all()
    gerekcesiz = oturum.scalars(select(Decision).where(Decision.gerekce_metni.is_(None))).all()

    assert min(k.risk_skoru for k in gerekceli) > max(k.risk_skoru for k in gerekcesiz)


def test_gerekcesiz_kararlar_da_gecerli(oturum: Session, ayar: Ayarlar):
    """Gerekçesi olmayan karar eksik değil — kuyrukta bekliyor demek."""
    gecelik_tarama(oturum, ayar, karar_ureteci=lambda: adaylar(10))

    gerekcesiz = oturum.scalars(select(Decision).where(Decision.gerekce_metni.is_(None))).all()
    assert gerekcesiz
    for karar in gerekcesiz:
        assert karar.politika_sonucu is not None
        assert karar.risk_skoru > 0


def test_her_karar_denetim_izi_birakir(oturum: Session, ayar: Ayarlar):
    """KURAL: denetim kaydı olmayan karar yolu yok."""
    gecelik_tarama(oturum, ayar, karar_ureteci=lambda: adaylar(5))

    kayitlar = oturum.scalars(select(DecisionAudit)).all()
    # 5 karar + gerekçe üretilen 3 karar için ikinci satır
    assert len(kayitlar) == 5 + 3

    atlanan = [k for k in kayitlar if k.guard_sonucu is GuardSonucu.ATLANDI]
    assert len(atlanan) == 5, "gerekçe üretilmeyen adımda ATLANDI yazılmalı"


def test_kuyruga_yalnizca_onay_bekleyenler_girer(oturum: Session, ayar: Ayarlar):
    gecelik_tarama(oturum, ayar, karar_ureteci=lambda: adaylar(10))

    onaylar = oturum.scalars(select(Approval)).all()
    kararlar = {k.karar_id: k for k in oturum.scalars(select(Decision)).all()}

    for onay in onaylar:
        assert kararlar[onay.karar_id].politika_sonucu.value == "onay_kuyrugu"


def test_icgoru_yazilir_ve_toplu_ozet_eklenir(oturum: Session, ayar: Ayarlar):
    ozet = gecelik_tarama(oturum, ayar, karar_ureteci=lambda: adaylar(10))

    icgoruler = oturum.scalars(select(Insight)).all()
    assert len(icgoruler) == ozet.icgoru_yazilan == 3 + 1  # üst-N + toplu özet

    toplu = [i for i in icgoruler if i.karar_id is None]
    assert len(toplu) == 1, "toplu özet tek bir karara bağlı olmamalı"
    assert "10 SKU" in toplu[0].baslik


def test_ayni_kosunun_icgoruleri_ayni_kosu_idsini_tasir(oturum: Session, ayar: Ayarlar):
    """'Bu sabahın bulguları' tek sorguyla çekilebilmeli."""
    ozet = gecelik_tarama(oturum, ayar, karar_ureteci=lambda: adaylar(5))

    kimlikler = {i.kosu_id for i in oturum.scalars(select(Insight)).all()}
    assert kimlikler == {ozet.kosu_id}


def test_gerekce_ureteci_enjekte_edilebilir(oturum: Session, ayar: Ayarlar):
    """Faz 2 B2.5 bitince guard destekli üreteç buraya geçirilecek."""
    cagrildi = {"sayi": 0}

    def sahte_gerekce(aday: DecisionCandidate) -> Gerekce:
        cagrildi["sayi"] += 1
        return Gerekce(
            karar_id=aday.karar_id,
            metin="Sahte gerekçe.",
            guard_sonucu=GuardSonucu.GECTI,
            model_adi="sahte-model",
            uretim_ms=42,
        )

    gecelik_tarama(oturum, ayar, karar_ureteci=lambda: adaylar(10), gerekce_ureteci=sahte_gerekce)

    assert cagrildi["sayi"] == 3, "yalnızca üst N için çağrılmalı"
    karar = oturum.scalars(select(Decision).where(Decision.gerekce_metni.is_not(None))).first()
    assert karar.llm_model_adi == "sahte-model"
    assert karar.guard_sonucu is GuardSonucu.GECTI


def test_sureler_ayri_olculur(oturum: Session, ayar: Ayarlar):
    """⭐ 'Karar hızlı, gerekçe yavaş' iddiası ancak ayrı ölçülürse doğrulanır."""
    ozet = gecelik_tarama(oturum, ayar, karar_ureteci=lambda: adaylar(10))

    assert ozet.karar_sn > 0
    assert ozet.gerekce_sn > 0
    assert ozet.toplam_sn == pytest.approx(ozet.karar_sn + ozet.gerekce_sn)


def test_bos_katalogda_cokmez(oturum: Session, ayar: Ayarlar):
    ozet = gecelik_tarama(oturum, ayar, karar_ureteci=lambda: [])

    assert ozet.taranan == 0
    assert ozet.gerekce_uretilen == 0
    # Toplu özet yine de yazılmalı — "hiçbir şey bulunamadı" da bir bulgudur.
    assert ozet.icgoru_yazilan == 1


def test_ozet_metni_okunabilir(oturum: Session, ayar: Ayarlar):
    ozet = gecelik_tarama(oturum, ayar, karar_ureteci=lambda: adaylar(5))
    metin = ozet.ozet()

    assert "taranan SKU" in metin
    assert "karar süresi" in metin
    assert isinstance(ozet, KosuOzeti)


# --- Tetikleyiciler -----------------------------------------------------------


def test_buyuk_siparis_tetiklenir(ayar: Ayarlar):
    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 30_000.0})

    tetiklenenler = tetikleyicileri_degerlendir(aday, ayar)

    assert Tetikleyici.BUYUK_SIPARIS in {t.tur for t in tetiklenenler}


def test_esik_altinda_buyuk_siparis_tetiklenmez(ayar: Ayarlar):
    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 24_999.0})

    tetiklenenler = tetikleyicileri_degerlendir(aday, ayar)

    assert Tetikleyici.BUYUK_SIPARIS not in {t.tur for t in tetiklenenler}


def test_kritik_stok_tetiklenir(ayar: Ayarlar):
    """Stok 2 günlük tüketime yetiyorsa (eşik 3) alarm."""
    oz = decide_stub().ozellikler.model_copy(
        update={"eldeki_stok": 84, "rezerve_stok": 0, "ort_gunluk_talep": 42.0}
    )
    aday = decide_stub().model_copy(update={"ozellikler": oz})

    tetiklenenler = tetikleyicileri_degerlendir(aday, ayar)

    kritik = [t for t in tetiklenenler if t.tur is Tetikleyici.KRITIK_STOK]
    assert kritik
    assert kritik[0].deger == pytest.approx(2.0)


def test_talep_sifirsa_kritik_stok_tetiklenmez(ayar: Ayarlar):
    """⭐ Hiç satmayan ürün için her gece yanlış alarm üretilmemeli.

    Talep 0 iken "kaç gün yeter" sorusunun cevabı yok; 0 dönmek "hemen
    bitecek" demek olurdu.
    """
    oz = decide_stub().ozellikler.model_copy(
        update={"ort_gunluk_talep": 0.0, "eldeki_stok": 1, "rezerve_stok": 0}
    )
    aday = decide_stub().model_copy(update={"ozellikler": oz})

    tetiklenenler = tetikleyicileri_degerlendir(aday, ayar)

    assert Tetikleyici.KRITIK_STOK not in {t.tur for t in tetiklenenler}


def test_limit_asimi_gunluk_toplam_verilmezse_kontrol_edilmez(ayar: Ayarlar):
    """Saf fonksiyon: DB sorgusu gerektiren kontrol çağırana bırakılıyor."""
    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 500_000.0})

    tetiklenenler = tetikleyicileri_degerlendir(aday, ayar)

    assert Tetikleyici.LIMIT_ASIMI not in {t.tur for t in tetiklenenler}


def test_limit_asimi_tetiklenir(ayar: Ayarlar):
    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 10_000.0})

    tetiklenenler = tetikleyicileri_degerlendir(aday, ayar, gunluk_toplam=245_000.0)

    limit = [t for t in tetiklenenler if t.tur is Tetikleyici.LIMIT_ASIMI]
    assert limit
    assert limit[0].deger == pytest.approx(255_000.0)


def test_gunluk_toplam_dbden_hesaplanir(oturum: Session, ayar: Ayarlar):
    gecelik_tarama(oturum, ayar, karar_ureteci=lambda: adaylar(4))

    toplam = gunluk_siparis_toplami(oturum)

    # 1.000 + 2.000 + 3.000 + 4.000
    assert toplam == pytest.approx(10_000.0)


def test_gunluk_toplam_baska_gunu_saymaz(oturum: Session, ayar: Ayarlar):
    gecelik_tarama(oturum, ayar, karar_ureteci=lambda: adaylar(4))

    dun = date.today() - timedelta(days=1)
    assert gunluk_siparis_toplami(oturum, dun) == 0.0


def _karari_yaz(oturum: Session, ayar: Ayarlar, aday: DecisionCandidate) -> None:
    """İçgörü karara bağlı olduğu için karar önce DB'de olmalı.

    Bu sıra tetikleyici tasarımının bir parçası: tetikleyici üretilmiş bir
    kararı değerlendirir, kararın kendisini üretmez.
    """
    from app.core.audit import karari_kaydet
    from app.core.policy import politika_uygula

    karari_kaydet(oturum, aday, politika_uygula(aday, ayar))
    oturum.commit()


def test_tetiklenmeler_icgoru_olarak_yazilir(oturum: Session, ayar: Ayarlar):
    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 30_000.0})
    _karari_yaz(oturum, ayar, aday)

    yazilanlar = tetiklenmeleri_kaydet(oturum, aday, tetikleyicileri_degerlendir(aday, ayar))
    oturum.commit()

    assert yazilanlar
    icgoru = yazilanlar[0]
    assert icgoru.baslik.startswith("[buyuk_siparis]")
    assert "30" in icgoru.metin


def test_yazilmamis_karara_icgoru_eklenemez(oturum: Session, ayar: Ayarlar):
    """⭐ Ön koşul: karar DB'de olmalı.

    B1.2'deki `foreign_keys=ON` bunu zorluyor. Pragma kapalı olsaydı içgörü
    sessizce yazılır ve var olmayan bir kararı işaret ederdi.
    """
    from sqlalchemy.exc import IntegrityError

    aday = decide_stub().model_copy(update={"tahmini_tutar_tl": 30_000.0})
    tetiklenmeleri_kaydet(oturum, aday, tetikleyicileri_degerlendir(aday, ayar))

    with pytest.raises(IntegrityError):
        oturum.commit()
    oturum.rollback()


def test_siddet_esigin_kac_kati_asildigini_yansitir(oturum: Session, ayar: Ayarlar):
    """Limitin iki katı bir sipariş, sınırda olandan daha acil."""
    az = decide_stub().model_copy(update={"karar_id": uuid4(), "tahmini_tutar_tl": 26_000.0})
    cok = decide_stub().model_copy(update={"karar_id": uuid4(), "tahmini_tutar_tl": 100_000.0})
    _karari_yaz(oturum, ayar, az)
    _karari_yaz(oturum, ayar, cok)

    az_icgoru = tetiklenmeleri_kaydet(oturum, az, tetikleyicileri_degerlendir(az, ayar))
    cok_icgoru = tetiklenmeleri_kaydet(oturum, cok, tetikleyicileri_degerlendir(cok, ayar))
    oturum.commit()

    assert cok_icgoru[0].onem_skoru > az_icgoru[0].onem_skoru


def test_kritik_stok_siddeti_ters_cevriliyor(oturum: Session, ayar: Ayarlar):
    """Kritik stokta eşiğin ALTINA düşülüyor — 'ne kadar kötü' aynı yönde olmalı."""

    def stoklu(eldeki: int) -> DecisionCandidate:
        oz = decide_stub().ozellikler.model_copy(
            update={"eldeki_stok": eldeki, "rezerve_stok": 0, "ort_gunluk_talep": 42.0}
        )
        return decide_stub().model_copy(update={"karar_id": uuid4(), "ozellikler": oz})

    az_kotu = stoklu(84)  # 2 gün
    cok_kotu = stoklu(21)  # 0,5 gün
    _karari_yaz(oturum, ayar, az_kotu)
    _karari_yaz(oturum, ayar, cok_kotu)

    a = tetiklenmeleri_kaydet(oturum, az_kotu, tetikleyicileri_degerlendir(az_kotu, ayar))
    b = tetiklenmeleri_kaydet(oturum, cok_kotu, tetikleyicileri_degerlendir(cok_kotu, ayar))
    oturum.commit()

    a_kritik = next(i for i in a if "kritik_stok" in i.baslik)
    b_kritik = next(i for i in b if "kritik_stok" in i.baslik)
    assert b_kritik.onem_skoru > a_kritik.onem_skoru
