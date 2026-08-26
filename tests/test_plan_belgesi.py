"""Plan belgesi (`app/planlama/belge.py`) — Faz 13 B13.2.

⚠️ Buradaki en önemli test `test_BELGE_MODELSIZ_uretiliyor`.

Faz 8'de bir tip liste dışında kaldığı için model **hiç çağrılmadı**, metin
sessizce şablona düştü ve kimse fark etmedi. Bu belge o yüzden modelden
bağımsız üretiliyor ve testi model olmadan koşuyor: modelin çalışmadığı bir
günde çıktı bozulmamalı.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

from app.planlama import belge as belge_modulu
from app.planlama.belge import Belge, belge_metni, plan_belgesi
from app.planlama.contracts import AtamaGerekcesi, KaynakPlani, PlanSatiri
from app.planlama.karsilastir import planlari_karsilastir
from app.planlama.tam_plan import TamPlan, tam_plan

BUGUN = date(2026, 8, 26)

BASLIKLAR = (
    "1 · GELECEK",
    "2 · NE YAPILACAK",
    "3 · TAKVİM",
    "4 · GEREKÇELER",
    "5 · PLAN SEÇENEKLERİ",
    "6 · DİKKAT",
)


def satir(is_id: str = "I1", gerekce: AtamaGerekcesi | None = None) -> PlanSatiri:
    return PlanSatiri(
        is_id=is_id,
        ad=f"İş {is_id}",
        kaynak_id="K1",
        kaynak_adi="Kaynak 1",
        baslangic=BUGUN,
        bitis=BUGUN,
        yuk=2.0,
        oncelik=1.0,
        gerekce=gerekce,
    )


def sahte_tam_plan(
    satirlar: tuple[PlanSatiri, ...] = (),
    sigmayanlar: tuple[PlanSatiri, ...] = (),
    uyarilar: tuple[str, ...] = (),
) -> TamPlan:
    """Belge testleri motoru çağırmıyor — girdi donmuş sözleşme.

    ⚠️ `plan_kur` çağırsaydı belge testleri yerleştirme algoritması
    değiştiğinde kırılırdı; belgenin sınandığı şey biçim, plan değil.
    """
    plan = KaynakPlani(
        kaynak_id="K1",
        kaynak_adi="Kaynak 1",
        gunluk_kapasite=8.0,
        kapasite_birimi="saat",
        satirlar=satirlar,
        sigmayanlar=sigmayanlar,
        ufuk_gun=5,
    )
    return TamPlan(
        alan="alfa",
        alan_adi="Alfa",
        olcut="en_acil",
        ufuk_gun=5,
        baslangic=BUGUN,
        isler_kaynagi="elle",
        is_sayisi=len(satirlar) + len(sigmayanlar),
        planlar=(plan,),
        karsilastirma=planlari_karsilastir({"en_acil": [plan]}),
        uyarilar=uyarilar,
    )


# --- Modelden bağımsızlık ------------------------------------------------------


def test_BELGE_MODELSIZ_uretiliyor():
    """⚠️ Faz 8'in dersi: belge önce kodla üretilir, model sonra ekler."""
    kaynak = Path(belge_modulu.__file__).read_text(encoding="utf-8")
    kod = kaynak.split('"""', 2)[-1]  # modül docstring'i dışarıda

    for yasak in ("llm", "ollama", "istem", "prompt"):
        assert yasak not in kod.lower(), f"belge üretimi '{yasak}' katmanına bağlanmış"

    assert not any(ad.startswith("app.llm") for ad in sys.modules if ad in kaynak), (
        "belge modülü LLM katmanını import ediyor"
    )


def test_ALTI_BOLUM_daima_var():
    """⚠️ Boş bölüm atlanmıyor — atlamak planı olduğundan iyi gösterir."""
    belge = plan_belgesi(sahte_tam_plan())

    assert [ad for ad, _ in belge.bolumler] == list(BASLIKLAR)
    assert isinstance(belge, Belge)


def test_ISI_OLMAYAN_PLAN_da_alti_bolum():
    metin = belge_metni(sahte_tam_plan())

    for baslik in BASLIKLAR:
        assert baslik in metin


# --- Gerekçe bölümü ------------------------------------------------------------


def test_GEREKCE_YOKSA_bolum_EKSIKLIGI_soyluyor():
    """Gerekçe henüz üretilmiyorsa (A13.1 öncesi) belge susmuyor."""
    metin = belge_metni(sahte_tam_plan(satirlar=(satir(),)))

    assert "gerekçe verisi yok" in metin
    assert "neden bu kaynak" in metin.lower()


def test_GEREKCE_VARSA_SECILEN_ve_ELENEN_yaziliyor():
    gerekce = AtamaGerekcesi(
        secilen_kaynak="K1",
        aday_kaynaklar=("K1", "K2"),
        belirleyici="kapasite",
        elenme_nedenleri={"K2": "ufuk boyunca daha dolu"},
    )
    metin = belge_metni(sahte_tam_plan(satirlar=(satir(gerekce=gerekce),)))

    assert "K1: uygun kaynaklar arasında en boş olanı buydu" in metin
    assert "K2 olmadı: ufuk boyunca daha dolu" in metin


def test_GEREKCE_LISTESI_SINIRLI_ama_kayip_SOYLENIYOR():
    """⚠️ Kısaltma bir veri kaybı değil; kaç satırın gizlendiği yazılıyor."""
    gerekce = AtamaGerekcesi(secilen_kaynak="K1", aday_kaynaklar=("K1",))
    satirlar = tuple(satir(f"I{n}", gerekce=gerekce) for n in range(20))

    metin = belge_metni(sahte_tam_plan(satirlar=satirlar))

    assert "5 satır daha" in metin


# --- Dikkat ve sığmayanlar -----------------------------------------------------


def test_SIGMAYAN_IS_hem_OZETTE_hem_DIKKATTE():
    tam = sahte_tam_plan(
        satirlar=(satir("I1"),),
        sigmayanlar=(satir("I2"),),
        uyarilar=("1 iş ufka sığmadı: İş I2",),
    )
    metin = belge_metni(tam)

    assert "Ufka sığmayan   : 1" in metin
    assert "yetişmiyor" in metin
    assert "⚠️ 1 iş ufka sığmadı" in metin


def test_UYARI_YOKSA_bolum_ACIKCA_bos_diyor():
    metin = belge_metni(sahte_tam_plan(satirlar=(satir(),)))

    assert "dikkat çeken bir durum yok" in metin


# --- Gerçek zincirin ucundan -----------------------------------------------------


@pytest.mark.parametrize("alan", ["nakliye"])
def test_GERCEK_ALANDAN_belge_cikiyor(alan: str):
    """Tek komut → belge. ⚠️ İkinci alan A13.2 ile eklenecek."""
    metin = belge_metni(tam_plan(alan, baslangic=BUGUN))

    for baslik in BASLIKLAR:
        assert baslik in metin
    assert "BEKLENEN MALİYET" in metin, "maliyet tablosu belgede yok"
    assert "Maliyet bir TAHMİN" in metin, "varsayımlar gizlenmiş"
