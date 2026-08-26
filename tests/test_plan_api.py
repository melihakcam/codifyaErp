"""Genel plan ucu (`app/api/plan.py`) — Faz 13 B13.3.

⚠️ Bu uç Faz 12'de yazılı kalan boşluğu kapatıyor: *motor genel, API yüzeyi
değil.* Nakliye motorda koşuyor ama dışarıdan çağrılamıyordu.

Testler bilinçli olarak `elle` kipindeki alanları kullanıyor (vardiya,
nakliye): `tahmin` kipi gerçek üretim hattını çağırıyor ve ~70 sn sürüyor.
Ucun alanı ayırt etmediği zaten `test_UC_ALAN_ADINI_bilmiyor` ile
kanıtlanıyor — yavaş alanı burada koşturmak yeni bir şey kanıtlamazdı.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.contracts import OtonomiSeviyesi
from app.core.config import ayarlar
from app.main import app


@pytest.fixture
def istemci() -> TestClient:
    return TestClient(app)


def test_ALANLAR_ucu_tanimli_alanlari_listeliyor(istemci: TestClient):
    cevap = istemci.get("/v1/plan/alanlar")

    assert cevap.status_code == 200
    alanlar = cevap.json()["alanlar"]
    assert {"nakliye", "uretim", "vardiya"} <= set(alanlar)


def test_PLAN_ucu_gerekce_dahil_tam_plan_donuyor(istemci: TestClient):
    cevap = istemci.post("/v1/plan/vardiya", json={"olcut": "en_acil"})

    assert cevap.status_code == 200
    veri = cevap.json()
    assert veri["alan"] == "vardiya"
    assert veri["olcut"] == "en_acil"
    assert veri["kaynaklar"], "kaynak listesi boş"

    isler = [is_ for k in veri["kaynaklar"] for is_ in k["isler"]]
    assert isler
    gerekce = isler[0]["gerekce"]
    # ⚠️ Gerekçe METİN DEĞİL veri olarak dönüyor: istemci kendi cümlesini
    # kurabilsin, ve alanlar test edilebilir kalsın.
    assert set(gerekce) == {
        "secilen_kaynak",
        "aday_kaynaklar",
        "belirleyici",
        "elenme_nedenleri",
    }


def test_UC_ALAN_ADINI_bilmiyor(istemci: TestClient):
    """⚠️ Fazın 1. kapısının API karşılığı: aynı uç, iki alan."""
    ilk = istemci.post("/v1/plan/vardiya", json={})
    ikinci = istemci.post("/v1/plan/nakliye", json={})

    assert ilk.status_code == ikinci.status_code == 200
    assert ilk.json()["alan"] != ikinci.json()["alan"]
    assert ilk.json()["kaynaklar"] and ikinci.json()["kaynaklar"]


def test_SECENEK_TABLOSU_daima_donuyor(istemci: TestClient):
    """Öneri tabloyu gizlemiyor; varsayımlar da birlikte gidiyor."""
    veri = istemci.post("/v1/plan/vardiya", json={}).json()

    karneler = veri["secenekler"]["karneler"]
    assert len(karneler) == 3
    assert veri["secenekler"]["onerilen_olcut"] == veri["olcut"]
    assert all(k["varsayimlar"] for k in karneler), "maliyet varsayımları gizlenmiş"


def test_BELGE_ISTENDIGINDE_alti_bolum_geliyor(istemci: TestClient):
    veri = istemci.post("/v1/plan/vardiya?belge=true", json={}).json()

    assert "4 · GEREKÇELER" in veri["belge"]
    assert "6 · DİKKAT" in veri["belge"]


def test_BELGE_ISTENMEDIGINDE_govdede_YOK(istemci: TestClient):
    """Metin varsayılan olarak dönmüyor: uç veri ucu, ekran değil."""
    assert "belge" not in istemci.post("/v1/plan/vardiya", json={}).json()


def test_TANIMSIZ_ALAN_404_ve_TANIMLILARI_soyluyor(istemci: TestClient):
    cevap = istemci.post("/v1/plan/hicboyle", json={})

    assert cevap.status_code == 404
    assert "vardiya" in cevap.json()["detail"]


def test_HATA_METNI_SUNUCU_YOLUNU_sizdirmiyor(istemci: TestClient):
    """⚠️ Motorun mesajı tanım dosyasının tam yolunu içeriyor; dışarı çıkmamalı."""
    detay = istemci.post("/v1/plan/hicboyle", json={}).json()["detail"]

    assert ":\\" not in detay and "/ornekler/" not in detay


def test_BILINMEYEN_OLCUT_422(istemci: TestClient):
    """Sessizce varsayılana düşmüyor — kullanıcı istediğini aldığını sanmamalı."""
    cevap = istemci.post("/v1/plan/vardiya", json={"olcut": "en_acilll"})

    assert cevap.status_code == 422


def test_KILL_SWITCH_plani_da_durduruyor(istemci: TestClient, monkeypatch: pytest.MonkeyPatch):
    """`AUTONOMY_LEVEL=off` iken karar üretilmiyorsa plan da üretilmemeli."""
    ayar = ayarlar()
    monkeypatch.setattr(ayar, "autonomy_level", OtonomiSeviyesi.OFF)

    cevap = istemci.post("/v1/plan/vardiya", json={})

    assert cevap.status_code == 503


def test_UFUK_GUN_gecirilebiliyor(istemci: TestClient):
    veri = istemci.post("/v1/plan/vardiya", json={"ufuk_gun": 3}).json()

    assert veri["ufuk_gun"] == 3


# --- B13.4: araç olarak eklenmesi ---------------------------------------------


def test_TAM_PLAN_ARACI_calistirilabilir():
    """Router doğru aracı seçtiğinde çalışan bir cevap dönmeli."""
    from app.llm.araclar import arac_calistirilabilir_mi, araci_calistir
    from app.llm.schemas import AracAdi

    assert arac_calistirilabilir_mi(AracAdi.TAM_PLAN)

    sonuc = araci_calistir(AracAdi.TAM_PLAN, "vardiya")

    assert sonuc["alan"] == "vardiya"
    assert sonuc["yerlesen_is"] > 0
    assert "4 · GEREKÇELER" in sonuc["belge"]


def test_TAM_PLAN_ARACI_ALANI_PARAMETREDEN_aliyor():
    """⚠️ Alan başına ayrı araç eklemek listeyi şişirir, modelin işini zorlaştırır."""
    from app.llm.araclar import araci_calistir
    from app.llm.schemas import AracAdi

    ilk = araci_calistir(AracAdi.TAM_PLAN, "vardiya")
    ikinci = araci_calistir(AracAdi.TAM_PLAN, "nakliye")

    assert ilk["alan"] != ikinci["alan"]


def test_TAM_PLAN_ARACI_ALAN_VERILMEZSE_TAHMIN_ETMIYOR():
    """Rastgele bir alanın planı, istenmeyen cevabı doğruymuş gibi gösterirdi."""
    from app.llm.araclar import araci_calistir
    from app.llm.schemas import AracAdi

    sonuc = araci_calistir(AracAdi.TAM_PLAN, None)

    assert sonuc["alan"] is None
    assert "Hangi alanın planı" in sonuc["mesaj"]
    assert "belge" not in sonuc


def test_TAM_PLAN_ARACI_TANIMSIZ_ALANDA_patlamiyor():
    """Araç çökmesi "cevap yok" gibi görünmemeli; açık mesaj dönüyor."""
    from app.llm.araclar import araci_calistir
    from app.llm.schemas import AracAdi

    sonuc = araci_calistir(AracAdi.TAM_PLAN, "hicboyle")

    assert "tanımlı bir alan değil" in sonuc["mesaj"]


def test_TAM_PLAN_ARACI_EGITILMIS_KUMEYE_girmiyor():
    """⚠️ Ölçülmüş sınır: canlı model bu adı eğitimde hiç görmedi.

    Eğitilmiş kümeye eklemek, modelin seçebildiği izlenimini verirdi —
    Faz 12'de yazılan sınırın aynısı burada da geçerli.
    """
    from app.llm.schemas import EGITILMIS_ARAC_ADLARI, AracAdi

    assert AracAdi.TAM_PLAN not in EGITILMIS_ARAC_ADLARI
