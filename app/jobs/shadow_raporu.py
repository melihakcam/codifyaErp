"""Faz 4.3 — shadow mod raporu: sistemin kararı vs vasat taban politika.

Sahip: Kişi B · Faz 4.3

    uv run python -m app.jobs.shadow_raporu

`shadow` modda sistem karar veriyor ama hiçbirini uygulamıyor (bkz.
`app/api/decisions.py`, `PolitikaKarari.uygulandi`). Bu betik, DB'ye
kaydedilmiş **gerçek** kararları (`Decision` tablosu — simülasyon değil,
sistemin canlı ürettiği kararlar) alıp her biri için "vasat taban politika
ne derdi" sorusunu yeniden hesaplar ve tablo halinde karşılaştırır.

⚠️ Bu, Kişi A'nın `training/genellenebilirlik_ve_para_metrigi.py`'sinden
**farklı bir şey ölçüyor**. Orası simülasyonu baştan koşturup üç politikayı
(vasat/kural motoru/oracle) sentetik veride karşılaştırıyor — kapsamlı ama
sentetik. Bu betik ise gerçek/canlı sistemin (shadow modda) ürettiği gerçek
kararları, aynı SKU anlık görüntüsü üzerinden vasat kuralla karşılaştırıyor
— dar ama **gerçek çalışma zamanı verisi**.

⚠️ **Vasat kuralın kayan pencere farkı.** `simulator/run.py`'deki vasat
politika, "ortalama günlük talep"i simülasyon boyunca güncellenen 30 günlük
bir kayan pencereden hesaplıyor (`TALEP_ORTALAMA_PENCERE_GUN`). Burada öyle
bir günlük geçmiş yok — elimizdeki tek şey `StockFeatures.ort_gunluk_talep`,
kural motorunun kendi (daha uzun pencereli) talep tahmini. Vasat kuralın eşik
(`ROP_ESIK_GUN=10`) ve hedef (`SIPARIS_HEDEF_GUN=30`) sabitleri
`simulator/run.py` ile **birebir aynı** tutuldu (adil karşılaştırma için tek
kaynaktan alınması gerekirdi ama `simulator/` Kişi A'nın alanı — sabitler
burada bilinçli olarak kopyalandı, iki taraf da değiştirirse birbirinden
haberdar olmalı). Talep tahmini farkı yüzünden **mutlak sayılar simülasyon
raporuyla birebir karşılaştırılamaz**; burada asıl bakılan şey yön uyuşması
(ikisi de sipariş ver/verme konusunda hemfikir mi) ve göreli tutar farkı.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from math import ceil

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import KararTipi
from app.core.db import oturum_fabrikasi
from app.models import Decision

ROP_ESIK_GUN = 10.0
"""simulator/run.py::ROP_ESIK_GUN ile birebir aynı olmalı."""

SIPARIS_HEDEF_GUN = 30.0
"""simulator/run.py::SIPARIS_HEDEF_GUN ile birebir aynı olmalı."""


@dataclass(frozen=True)
class VasatKarari:
    siparis_verir: bool
    miktar: float


def vasat_karari_hesapla(ozellik: dict) -> VasatKarari:
    """`simulator/run.py`'deki vasat kuralın tek-nokta (stateless) hâli.

    `ozellik`, `Decision.ozellikler`'in JSON hâli — `StockFeatures.model_dump()`.
    """
    ort_talep = ozellik["ort_gunluk_talep"]
    net_pozisyon = ozellik["eldeki_stok"] - ozellik["rezerve_stok"] + ozellik["yoldaki_stok"]

    if ort_talep <= 0:
        return VasatKarari(siparis_verir=False, miktar=0.0)

    esik = ROP_ESIK_GUN * ort_talep
    if net_pozisyon >= esik:
        return VasatKarari(siparis_verir=False, miktar=0.0)

    hedef_miktar = SIPARIS_HEDEF_GUN * ort_talep
    paket_adedi = max(1, ozellik["paket_adedi"])
    paket_katlari = max(1, ceil(hedef_miktar / paket_adedi))
    miktar = paket_katlari * paket_adedi
    miktar = max(miktar, ozellik["moq"])
    return VasatKarari(siparis_verir=True, miktar=float(miktar))


@dataclass(frozen=True)
class KarsilastirmaSatiri:
    karar_id: str
    sku_id: str
    sku_adi: str
    sistem_siparis_verir: bool
    sistem_miktar: float
    vasat_siparis_verir: bool
    vasat_miktar: float
    ayni_yon: bool
    tutar_farki_tl: float


def karsilastirma_uret(kararlar: list[Decision]) -> list[KarsilastirmaSatiri]:
    """Yalnızca `stok.siparis` ve `stok.aksiyon_yok` kararları kapsar.

    İkisi birlikte "sipariş verildi mi verilmedi mi" sorusunun iki yanı —
    vasat kuralla doğrudan karşılaştırılabilir tek karar tipleri bunlar.
    `stok.tasfiye` gibi diğer tipler vasat politikada hiç yok (vasat yalnızca
    yeniden sipariş kararı verir), o yüzden kapsam dışı bırakıldı.
    """
    satirlar = []
    for k in kararlar:
        if k.tip not in (KararTipi.STOK_SIPARIS, KararTipi.STOK_AKSIYON_YOK):
            continue

        vasat = vasat_karari_hesapla(k.ozellikler)
        sistem_siparis_verir = k.tip is KararTipi.STOK_SIPARIS
        sistem_miktar = float(k.aksiyon.get("siparis_miktari", 0)) if sistem_siparis_verir else 0.0

        birim_maliyet = k.ozellikler.get("birim_maliyet_tl", 0.0)
        tutar_farki = (sistem_miktar - vasat.miktar) * birim_maliyet

        satirlar.append(
            KarsilastirmaSatiri(
                karar_id=str(k.karar_id),
                sku_id=k.ozellikler.get("sku_id", "?"),
                sku_adi=k.ozellikler.get("sku_adi", "?"),
                sistem_siparis_verir=sistem_siparis_verir,
                sistem_miktar=sistem_miktar,
                vasat_siparis_verir=vasat.siparis_verir,
                vasat_miktar=vasat.miktar,
                ayni_yon=sistem_siparis_verir == vasat.siparis_verir,
                tutar_farki_tl=tutar_farki,
            )
        )
    return satirlar


def rapor_yaz(satirlar: list[KarsilastirmaSatiri]) -> str:
    if not satirlar:
        return "Karşılaştırılabilir karar yok (DB'de stok.siparis/stok.aksiyon_yok kaydı yok)."

    satir = "-" * 88
    baslik = f"{'SKU':30s} {'sistem':>10s} {'vasat':>10s} {'yon':>6s} {'tutar farki tl':>16s}"
    govde = [satir, baslik, satir]
    for s in satirlar:
        sistem_ozet = f"{s.sistem_miktar:.0f}" if s.sistem_siparis_verir else "-"
        vasat_ozet = f"{s.vasat_miktar:.0f}" if s.vasat_siparis_verir else "-"
        yon = "aynı" if s.ayni_yon else "FARKLI"
        govde.append(
            f"{s.sku_adi[:30]:30s} {sistem_ozet:>10s} {vasat_ozet:>10s} "
            f"{yon:>6s} {s.tutar_farki_tl:>16,.0f}"
        )
    govde.append(satir)

    n = len(satirlar)
    ayni_yon_sayisi = sum(s.ayni_yon for s in satirlar)
    toplam_tutar_farki = sum(s.tutar_farki_tl for s in satirlar)

    govde.append(f"toplam karar            : {n}")
    govde.append(
        f"yön uyuşması            : {ayni_yon_sayisi}/{n} (%{ayni_yon_sayisi / n * 100:.1f})"
    )
    govde.append(f"toplam tutar farkı (TL) : {toplam_tutar_farki:,.0f}")
    govde.append(
        "  (pozitif = sistem vasat'tan daha fazla sipariş veriyor, "
        "negatif = daha az)"
    )
    return "\n".join(govde)


def raporu_hesapla(oturum: Session) -> list[KarsilastirmaSatiri]:
    kararlar = list(oturum.scalars(select(Decision)).all())
    return karsilastirma_uret(kararlar)


def _cli() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    argparse.ArgumentParser(description="Faz 4.3 shadow mod raporu").parse_args()

    with oturum_fabrikasi()() as oturum:
        satirlar = raporu_hesapla(oturum)

    print(rapor_yaz(satirlar))


if __name__ == "__main__":
    _cli()
