"""Alanı bilmeyen tek komut (`app/planlama/tam_plan.py`) — Faz 13 B13.1.

⚠️ Buradaki en önemli iki test şunlar:

· `test_IKI_ALAN_ayni_fonksiyona_gidiyor` — genellik iddiasının kendisi
· `test_KAYNAKTA_alan_adi_gecmiyor` — iddianın çürümesini engelleyen bekçi

İkincisi olmadan birincisi zamanla anlamsızlaşır: bir gün birisi
`if alan == "uretim"` yazar, testler yeşil kalır ve motor sessizce
alan-özel hâle gelir.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from app.planlama import tam_plan as tam_plan_modulu
from app.planlama.tam_plan import (
    TamPlan,
    TamPlanHatasi,
    alanlari_listele,
    tam_plan,
)

BUGUN = date(2026, 8, 26)
SAHTE_ADAPTOR = "tests.sahte_adaptor"


def tanim_yaz(dizin: Path, alan: str, **fazlasi) -> Path:
    """Tek JSON ile alan ekler — fazın 3. kapısının test hâli."""
    tanim = {
        "ad": alan.capitalize(),
        "kapasite_birimi": "saat",
        "kaynaklar": [
            {"id": f"{alan.upper()}-1", "ad": "Kaynak 1", "gunluk_kapasite": 8},
            {"id": f"{alan.upper()}-2", "ad": "Kaynak 2", "gunluk_kapasite": 6},
        ],
        "isler": [
            {
                "id": f"{alan.upper()}-IS-{n}",
                "ad": f"İş {n}",
                "yuk": 3.0,
                "oncelik": float(n),
                "uygun_kaynaklar": [f"{alan.upper()}-1", f"{alan.upper()}-2"],
            }
            for n in range(4)
        ],
    }
    tanim.update(fazlasi)
    yol = dizin / f"{alan}.json"
    yol.write_text(json.dumps(tanim, ensure_ascii=False), encoding="utf-8")
    return yol


@pytest.fixture
def dizin(tmp_path: Path) -> Path:
    """İki alanlı bir dünya — adları bilinçli olarak anlamsız."""
    tanim_yaz(tmp_path, "alfa")
    tanim_yaz(tmp_path, "beta")
    return tmp_path


# --- Genellik: iddianın kendisi ----------------------------------------------


def test_IKI_ALAN_ayni_fonksiyona_gidiyor(dizin: Path):
    """⚠️ Fazın 1. kapısı. Aynı komut, iki alan, iki plan."""
    ilk = tam_plan("alfa", baslangic=BUGUN, dizin=dizin)
    ikinci = tam_plan("beta", baslangic=BUGUN, dizin=dizin)

    assert isinstance(ilk, TamPlan) and isinstance(ikinci, TamPlan)
    assert ilk.satirlar and ikinci.satirlar, "alanlardan biri plan üretmedi"
    assert ilk.alan != ikinci.alan
    assert [s.is_id for s in ilk.satirlar] != [s.is_id for s in ikinci.satirlar]


def test_KAYNAKTA_alan_adi_gecmiyor():
    """⚠️ `if alan == "uretim"` yazan tek satır bu fazın iddiasını çürütür.

    Kural incelemede değil testte duruyor: incelemeler unutulur, test
    unutmaz. Aranan şey yalnızca `if` değil, alan adının kaynakta geçmesi.
    """
    kaynak = Path(tam_plan_modulu.__file__).read_text(encoding="utf-8")
    # Belge blokları (docstring) örnek verebilir; sınanan şey KOD.
    kod = re.sub(r'""".*?"""', "", kaynak, flags=re.DOTALL)

    for alan_adi in ("uretim", "üretim", "nakliye", "stok", "finans", "vardiya"):
        assert alan_adi not in kod.lower(), (
            f"tam_plan.py kodunda '{alan_adi}' geçiyor — motor alanı tanımaya başlamış"
        )


def test_YENI_ALAN_tek_JSON_ile_ekleniyor(dizin: Path):
    """⚠️ Fazın 3. kapısının çekirdeği: yeni müşteri = tek dosya, sıfır kod."""
    assert alanlari_listele(dizin) == ("alfa", "beta")

    tanim_yaz(dizin, "gama")

    assert alanlari_listele(dizin) == ("alfa", "beta", "gama")
    assert tam_plan("gama", baslangic=BUGUN, dizin=dizin).satirlar


# --- İşlerin nereden geldiği (üç kip) ----------------------------------------


def test_ELLE_kipi_ADAPTOR_ARAMIYOR(dizin: Path):
    """Varsayılan yol: işler JSON'da yazılı, kod hiç devreye girmiyor."""
    plan = tam_plan("alfa", baslangic=BUGUN, dizin=dizin)
    assert plan.isler_kaynagi == "elle"
    assert plan.is_sayisi == 4


def test_TAHMIN_kipi_ADAPTORU_TANIMDAN_buluyor(dizin: Path):
    """⚠️ Motorda kayıt defteri yok; modül adı tanımdan geliyor."""
    tanim_yaz(dizin, "delta", isler_kaynagi="tahmin", adaptor=SAHTE_ADAPTOR, isler=[])

    plan = tam_plan("delta", baslangic=BUGUN, dizin=dizin)

    assert plan.isler_kaynagi == "tahmin"
    assert plan.is_sayisi == 2, "adaptör çağrılmadı"
    assert all(s.is_id.startswith("T") for s in plan.satirlar)


def test_ALAN_kipi_ONCEKI_ALANIN_CIKTISINI_devraliyor(dizin: Path):
    """Zincir bağı: bir alanın çıktısı başka alanın girdisi."""
    tanim_yaz(dizin, "epsilon", isler_kaynagi="alan:alfa", adaptor=SAHTE_ADAPTOR, isler=[])

    plan = tam_plan("epsilon", baslangic=BUGUN, dizin=dizin)

    devralinan = [s for s in plan.satirlar if s.is_id.startswith("D-")]
    assert len(devralinan) == 4, "alfa'nın işleri zincirden geçmedi"
    assert plan.isler_kaynagi == "alan:alfa"


def test_ZINCIR_DONGUSU_yigin_tasmasiyla_degil_HATAYLA_duruyor(dizin: Path):
    """A, B'den; B, A'dan beslenirse zincir sonsuza gider."""
    tanim_yaz(dizin, "zeta", isler_kaynagi="alan:eta", adaptor=SAHTE_ADAPTOR, isler=[])
    tanim_yaz(dizin, "eta", isler_kaynagi="alan:zeta", adaptor=SAHTE_ADAPTOR, isler=[])

    with pytest.raises(TamPlanHatasi, match="döngü"):
        tam_plan("zeta", baslangic=BUGUN, dizin=dizin)


def test_ADAPTORSUZ_TAHMIN_tanimi_YUKLEME_ANINDA_patliyor(dizin: Path):
    """İşleri kimin üreteceği yazılmamışsa plan hiç kurulmuyor."""
    tanim_yaz(dizin, "theta", isler_kaynagi="tahmin", isler=[])

    with pytest.raises(Exception, match="adaptor"):
        tam_plan("theta", baslangic=BUGUN, dizin=dizin)


def test_ADAPTOR_IMZASI_TUTMUYORSA_soyluyor(dizin: Path):
    """`isleri_uret` yoksa hata mesajı tek imzayı hatırlatıyor."""
    tanim_yaz(dizin, "iota", isler_kaynagi="tahmin", adaptor="json", isler=[])

    with pytest.raises(TamPlanHatasi, match="isleri_uret"):
        tam_plan("iota", baslangic=BUGUN, dizin=dizin)


def test_OLMAYAN_ADAPTOR_modulu_ANLASILIR_hata(dizin: Path):
    tanim_yaz(dizin, "kappa", isler_kaynagi="tahmin", adaptor="hic.olmayan.modul", isler=[])

    with pytest.raises(TamPlanHatasi, match="yüklenemedi"):
        tam_plan("kappa", baslangic=BUGUN, dizin=dizin)


# --- Seçenekler, uyarılar, hatalar -------------------------------------------


def test_OLCUT_VERILMEZSE_uc_plan_kosuluyor_ve_TABLO_duruyor(dizin: Path):
    """⚠️ Öneri tabloyu gizlemiyor — Faz 11'in kuralı burada da geçerli."""
    plan = tam_plan("alfa", baslangic=BUGUN, dizin=dizin)

    assert len(plan.karsilastirma.karneler) == 3
    assert plan.olcut == plan.karsilastirma.onerilen_olcut
    assert plan.karsilastirma.oneri_gerekcesi


def test_OLCUT_VERILIRSE_tek_plan_ve_o_olcut(dizin: Path):
    plan = tam_plan("alfa", olcut="en_cok_is", baslangic=BUGUN, dizin=dizin)

    assert plan.olcut == "en_cok_is"
    assert len(plan.karsilastirma.karneler) == 1


def test_BILINMEYEN_OLCUT_sessizce_varsayilana_dusmuyor(dizin: Path):
    with pytest.raises(TamPlanHatasi, match="Bilinmeyen ölçüt"):
        tam_plan("alfa", olcut="en_acilll", baslangic=BUGUN, dizin=dizin)


def test_OLMAYAN_ALAN_tanimli_alanlari_soyluyor(dizin: Path):
    """Hata mesajı "yok" demekle kalmıyor, ne olduğunu söylüyor."""
    with pytest.raises(TamPlanHatasi, match="alfa"):
        tam_plan("hicbiryer", baslangic=BUGUN, dizin=dizin)


def test_SIFIR_UFUK_plan_penceresi_olamaz(dizin: Path):
    with pytest.raises(TamPlanHatasi, match="ufuk"):
        tam_plan("alfa", ufuk_gun=0, baslangic=BUGUN, dizin=dizin)


def test_UFKA_SIGMAYAN_IS_uyari_uretiyor(dizin: Path):
    """⚠️ Sığmayan iş sessizce düşmüyor; plan "her şey yetişiyor" demiyor."""
    tanim_yaz(
        dizin,
        "mu",
        isler=[
            {
                "id": f"MU-{n}",
                "ad": f"Ağır iş {n}",
                "yuk": 20.0,
                "oncelik": float(n),
                "uygun_kaynaklar": ["MU-1", "MU-2"],
            }
            for n in range(4)
        ],
    )

    plan = tam_plan("mu", ufuk_gun=1, baslangic=BUGUN, dizin=dizin)

    assert plan.sigmayanlar
    assert any("sığmadı" in u for u in plan.uyarilar)


def test_ISI_OLMAYAN_ALAN_patlamiyor_ama_SUSMUYOR(dizin: Path):
    tanim_yaz(dizin, "lambda", isler=[])

    plan = tam_plan("lambda", baslangic=BUGUN, dizin=dizin)

    assert plan.satirlar == ()
    assert any("iş yok" in u for u in plan.uyarilar)


def test_DOLU_KAYNAK_uyarisi(dizin: Path):
    """Doluluk bir hedef değil; %90 üstü tek gecikmeye dayanıksız demek."""
    plan = tam_plan("alfa", ufuk_gun=1, baslangic=BUGUN, dizin=dizin)

    assert any("doluluğu" in u for u in plan.uyarilar)


# --- Determinizm --------------------------------------------------------------


def test_AYNI_GIRDI_AYNI_PLAN(dizin: Path):
    """⚠️ Fazın 4. kapısı. Gerekçeler de karşılaştırılıyor (A13.1 sonrası anlam kazanacak)."""
    ilk = tam_plan("alfa", baslangic=BUGUN, dizin=dizin)
    ikinci = tam_plan("alfa", baslangic=BUGUN, dizin=dizin)

    assert [(s.is_id, s.kaynak_id, s.baslangic, s.gerekce) for s in ilk.satirlar] == [
        (s.is_id, s.kaynak_id, s.baslangic, s.gerekce) for s in ikinci.satirlar
    ]
    assert ilk.olcut == ikinci.olcut
    assert ilk.karsilastirma.oneri_gerekcesi == ikinci.karsilastirma.oneri_gerekcesi


def test_GERCEK_NAKLIYE_TANIMI_yeni_komuttan_geciyor():
    """Faz 11'in alan tanımı değiştirilmeden yeni girişten koşuyor."""
    plan = tam_plan("nakliye", baslangic=BUGUN)

    assert plan.is_sayisi == 10
    assert plan.isler_kaynagi == "elle"
    assert plan.satirlar
