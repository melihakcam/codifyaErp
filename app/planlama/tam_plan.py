"""Alanı bilmeyen tek giriş — `tam_plan(alan)`.

Sahip: Kişi B · Faz 13 B13.1

## Bu dosyanın tek işi

Zinciri baştan sona koşturmak:

    tanim (JSON)  ->  isler  ->  yerlestirme  ->  maliyet + karsilastirma

Ve bunu **alan adını hiç bilmeden** yapmak. `tam_plan("uretim")` ile
`tam_plan("nakliye")` aynı fonksiyona gidiyor, aynı satırları koşuyor.

## ⚠️ İçinde alan adı geçen tek bir `if` bile yok — ve olmayacak

`if alan == "uretim"` yazan tek satır bu fazın iddiasını çürütür. Bir test
bu dosyanın kaynağını okuyup alan adı arıyor. Kural incelemede değil
**testte** duruyor — incelemeler unutulur.

Kip'e göre dallanma (`elle` / `tahmin` / `alan:`) **serbest ve gerekli**:
kip sonlu bir kümedir ve her alan aynı kipleri kullanır. Alana göre
dallanma yasak, kipe göre dallanma zorunlu — ayrım bu.

## İşleri kim üretiyor

`elle` kipinde işler tanımın içinde yazılı; adaptör aranmıyor. Yeni
müşteri hâlâ **tek JSON**, kod yok.

`tahmin` ve `alan:<ad>` kiplerinde işleri üreten kod alana özeldir (üretim
emri ile sevkiyat aynı şeyden türemez) ve yolu **tanımda** yazılıdır. Motor
o modülü import edip `isleri_uret(...)` çağırır; ne yaptığını bilmez.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from app.planlama.contracts import Is, Kaynak, KaynakPlani, PlanSatiri
from app.planlama.karsilastir import Karsilastirma, planlari_karsilastir
from app.planlama.olcut import OLCUT_ACIKLAMALARI, OLCUTLER, VARSAYILAN_OLCUT
from app.planlama.tanim import ELLE, TAHMIN, AlanTanimi, alan_tanimi_dosyadan
from app.planlama.yerlestirme import plan_kur

VARSAYILAN_UFUK_GUN = 14

# Alan tanımlarının durduğu dizin. ⚠️ Tek yer: yeni alan buraya bir JSON
# bırakmakla ekleniyor. Kod tarafında bir kayıt defteri olsaydı "sıfır kod"
# iddiası daha ilk alanda düşerdi.
VARSAYILAN_DIZIN = Path(__file__).resolve().parents[2] / "ornekler"

# Doluluğu bu oranı geçen kaynak, belgede uyarı üretiyor.
# ⚠️ Yüksek doluluk "iyi" değil: %90 dolu bir kaynak tek gecikmede tüm
# planı kaydırır. Sayı bir hedef değil, dikkat çekme eşiği.
DOLULUK_UYARI_ESIGI = 0.90


class TamPlanHatasi(ValueError):
    """Zincir kurulamadı. Mesaj hangi halkada ne eksik olduğunu söyler."""


class IsUretici(Protocol):
    """Adaptörlerin taşıdığı tek imza.

    ⚠️ Üretim ve nakliye adaptörleri **aynı** imzayı taşır; alanı bilmeyen
    katman ikisini ayırt etmez. İmzalar ayrışırsa motor "hangi alan hangi
    biçimde çağrılır" bilgisini taşımak zorunda kalır ve genellik biter.
    """

    def isleri_uret(
        self,
        tanim: AlanTanimi,
        ufuk_gun: int,
        baslangic: date,
        kaynak_isler: tuple[Is, ...] = (),
    ) -> list[Is]: ...

    # ⚠️ İSTEĞE BAĞLI. Kaynaklar normalde tanımda yazılı (araçlar, kişiler
    # — sabit bir liste). Ama bazı alanlarda kaynak listesi işletmenin
    # kendi verisinde yaşıyor (üretim hatları ERP'de, kapasiteleri profil
    # dosyasından geliyor). Orada JSON'a elle kopyalamak iki ayrı gerçek
    # üretir: kapasite değişir, plan sessizce yanlış çıkar.
    #
    # Tanımda kaynak yazılıysa bu yordam **çağrılmaz** — tanım her zaman
    # üstündür.
    def kaynaklari_uret(self, tanim: AlanTanimi) -> list[Kaynak]: ...


@dataclass(frozen=True)
class TamPlan:
    """Tek komutun çıktısı — plan belgesinin ham verisi.

    ⚠️ İçinde metin YOK. Belge (B13.2) bu nesneden üretiliyor, tersi değil.
    Metni burada üretmek çıktıyı test edilemez ve makine tarafından
    okunamaz yapardı.
    """

    alan: str
    alan_adi: str
    olcut: str
    ufuk_gun: int
    baslangic: date
    isler_kaynagi: str
    is_sayisi: int
    planlar: tuple[KaynakPlani, ...]
    karsilastirma: Karsilastirma
    uyarilar: tuple[str, ...] = ()

    @property
    def satirlar(self) -> tuple[PlanSatiri, ...]:
        """Önerilen plandaki tüm satırlar, kaynak sırasıyla."""
        return tuple(s for p in self.planlar for s in p.satirlar)

    @property
    def sigmayanlar(self) -> tuple[PlanSatiri, ...]:
        """Ufka sığmayanlar. ⚠️ Sessizce düşmüyorlar, çıktıda duruyorlar."""
        return tuple(s for p in self.planlar for s in p.sigmayanlar)


def _tanim_yolu(alan: str, dizin: Path) -> Path:
    yol = dizin / f"{alan}.json"
    if not yol.exists():
        mevcut = sorted(p.stem for p in dizin.glob("*.json"))
        raise TamPlanHatasi(f"'{alan}' alanının tanımı yok: {yol}. Tanımlı alanlar: {mevcut}")
    return yol


def _adaptor_yukle(tanim: AlanTanimi) -> IsUretici:
    """Tanımda yazılı modülü import eder.

    ⚠️ Modül adı **tanımdan** geliyor, motordan değil. Motorda bir sözlük
    (`{"uretim": ...}`) tutulsaydı yeni alan eklemek kod değişikliği
    gerektirirdi ve fazın 3. kapısı düşerdi.
    """
    if not tanim.adaptor:  # AlanTanimi.__post_init__ zaten garanti ediyor
        raise TamPlanHatasi(f"'{tanim.ad}': adaptör yazılmamış.")
    try:
        modul: Any = importlib.import_module(tanim.adaptor)
    except ImportError as hata:
        raise TamPlanHatasi(
            f"'{tanim.ad}' adaptörü yüklenemedi: {tanim.adaptor} — {hata}"
        ) from hata
    if not hasattr(modul, "isleri_uret"):
        raise TamPlanHatasi(f"{tanim.adaptor}: 'isleri_uret' yok. Adaptörlerin tek imzası bu.")
    return modul


def girdileri_getir(
    tanim: AlanTanimi,
    ufuk_gun: int,
    baslangic: date,
    dizin: Path,
    _zincir: tuple[str, ...] = (),
) -> tuple[list[Is], list[Kaynak]]:
    """Planın iki girdisi: işler ve kaynaklar. Kipe göre dallanır."""
    kip = tanim.isler_kaynagi.kip

    if kip == ELLE:
        return list(tanim.isler), list(tanim.kaynaklar)

    kaynak_isler: tuple[Is, ...] = ()
    if kip == "alan":
        onceki = tanim.isler_kaynagi.kaynak_alan or ""
        # ⚠️ Döngü koruması: A alanı B'den, B de A'dan beslenirse zincir
        # sonsuza gider. Yığın taşmasıyla değil, okunur bir hatayla dursun.
        if onceki in _zincir:
            raise TamPlanHatasi(
                f"alanlar birbirini besliyor (döngü): {' -> '.join([*_zincir, onceki])}"
            )
        onceki_tanim = alan_tanimi_dosyadan(_tanim_yolu(onceki, dizin))
        kaynak_isler = tuple(
            girdileri_getir(onceki_tanim, ufuk_gun, baslangic, dizin, (*_zincir, onceki))[0]
        )

    uretici = _adaptor_yukle(tanim)
    isler = list(
        uretici.isleri_uret(
            tanim=tanim, ufuk_gun=ufuk_gun, baslangic=baslangic, kaynak_isler=kaynak_isler
        )
    )

    # Tanım her zaman üstün: kaynak yazılıysa adaptöre sorulmuyor.
    kaynaklar = list(tanim.kaynaklar)
    if not kaynaklar and hasattr(uretici, "kaynaklari_uret"):
        kaynaklar = list(uretici.kaynaklari_uret(tanim))
    return isler, kaynaklar


def isleri_getir(
    tanim: AlanTanimi,
    ufuk_gun: int,
    baslangic: date,
    dizin: Path,
    _zincir: tuple[str, ...] = (),
) -> list[Is]:
    """Yalnızca işler. `girdileri_getir`in ince sarmalayıcısı."""
    return girdileri_getir(tanim, ufuk_gun, baslangic, dizin, _zincir)[0]


def _uyarilar(planlar: tuple[KaynakPlani, ...], is_sayisi: int, kip: str) -> tuple[str, ...]:
    """Belgenin ⚠️ bölümünün ham hâli. Sessiz kalmak yerine söylüyor."""
    uyarilar: list[str] = []
    if not is_sayisi:
        bos = "tahmin boş döndü" if kip == TAHMIN else "tanımda iş yazılı değil"
        uyarilar.append(f"Planlanacak iş yok — {bos}.")

    sigmayan = [s for p in planlar for s in p.sigmayanlar]
    if sigmayan:
        adlar = ", ".join(s.ad for s in sigmayan[:5])
        uyarilar.append(
            f"{len(sigmayan)} iş ufka sığmadı: {adlar}" + (" …" if len(sigmayan) > 5 else "")
        )

    for p in planlar:
        if p.doluluk >= DOLULUK_UYARI_ESIGI:
            uyarilar.append(
                f"{p.kaynak_adi} doluluğu %{p.doluluk * 100:.0f} — tek gecikme planı kaydırır."
            )
    return tuple(uyarilar)


def tam_plan(
    alan: str,
    olcut: str | None = None,
    ufuk_gun: int | None = None,
    baslangic: date | None = None,
    dizin: Path | str | None = None,
) -> TamPlan:
    """Bir alanın **tamamının** planı — tek komut.

    `olcut` verilmezse üç ölçüt de koşulur ve maliyeti en düşük olan
    önerilir; tablo yine de çıktıda durur (`karsilastirma`).

    ⚠️ Bu fonksiyonun alan hakkında bildiği tek şey **adı** — o da yalnızca
    tanım dosyasını bulmak için. Davranışın tamamı tanımdan geliyor.
    """
    dizin_yolu = Path(dizin) if dizin else VARSAYILAN_DIZIN
    # ⚠️ `ufuk_gun or VARSAYILAN` yazmak 0'ı sessizce 14'e çeviriyordu —
    # "sıfır günlük plan" hatası, istenen davranış sanılıp geçerdi.
    ufuk = VARSAYILAN_UFUK_GUN if ufuk_gun is None else ufuk_gun
    ilk_gun = baslangic or date.today()

    if ufuk <= 0:
        raise TamPlanHatasi(f"ufuk {ufuk} gün olamaz — plan penceresi pozitif olmalı.")
    if olcut is not None and olcut not in OLCUTLER:
        # ⚠️ Sessizce varsayılana düşmüyor: `olcut_al` ile aynı disiplin.
        # Yazım hatası olan çağrı, istediği planı aldığını sanmamalı.
        raise TamPlanHatasi(f"Bilinmeyen ölçüt: {olcut}. Tanımlılar: {sorted(OLCUTLER)}")

    tanim = alan_tanimi_dosyadan(_tanim_yolu(alan, dizin_yolu))
    isler, kaynaklar = girdileri_getir(tanim, ufuk, ilk_gun, dizin_yolu)
    if isler and not kaynaklar:
        raise TamPlanHatasi(
            f"'{alan}': iş var ama kaynak yok — tanımda kaynak yazılmamış ve adaptör de üretmiyor."
        )

    denenecek = [olcut] if olcut else sorted(OLCUTLER)
    planlar_by_olcut = {
        ad: plan_kur(isler, kaynaklar, olcut=ad, ufuk_gun=ufuk, baslangic=ilk_gun)
        for ad in denenecek
    }
    karsilastirma = planlari_karsilastir(planlar_by_olcut, OLCUT_ACIKLAMALARI)

    secilen = olcut or karsilastirma.onerilen_olcut or VARSAYILAN_OLCUT
    planlar = tuple(planlar_by_olcut[secilen])

    return TamPlan(
        alan=alan,
        alan_adi=tanim.ad or alan,
        olcut=secilen,
        ufuk_gun=ufuk,
        baslangic=ilk_gun,
        isler_kaynagi=str(tanim.isler_kaynagi),
        is_sayisi=len(isler),
        planlar=planlar,
        karsilastirma=karsilastirma,
        uyarilar=_uyarilar(planlar, len(isler), tanim.isler_kaynagi.kip),
    )


def alanlari_listele(dizin: Path | str | None = None) -> tuple[str, ...]:
    """Tanımlı alanlar. API ve araç katmanı bunu kullanır."""
    yol = Path(dizin) if dizin else VARSAYILAN_DIZIN
    return tuple(sorted(p.stem for p in yol.glob("*.json"))) if yol.exists() else ()


__all__ = [
    "DOLULUK_UYARI_ESIGI",
    "VARSAYILAN_UFUK_GUN",
    "IsUretici",
    "TamPlan",
    "TamPlanHatasi",
    "alanlari_listele",
    "girdileri_getir",
    "isleri_getir",
    "tam_plan",
]
