"""Faz 5 — uçtan uca benchmark raporu.

Sahip: Kişi B · Faz 5

    uv run python -m training.eval.benchmark

Görev dosyasındaki (`dokumantasyon/KISI-B-GOREV.md`, Faz 4-5) beş hedefi tek
raporda toplar:

| Metrik | Hedef |
|--------|-------|
| Router: araç + parametre tam eşleşme | > %95 |
| Gerekçe: uydurma sayı | 0 — sert kapı |
| Gerekçe: Türkçe akıcılık | LLM-jüri puanı |
| Gecelik tarama süresi | < 10 dk |
| Tepe RAM | < 4 GB |

⚠️ **`shadow` modda ölçülmüş doğruluk raporu olmadan `threshold`'a ASLA
geçilmez** (`KISI-B-GOREV.md`). Bu betiğin çıktısı o kararın dayanağıdır —
bir metrik hedefi ıskalarsa (aşağıda görüleceği gibi router şu an ıskalıyor,
bkz. `dokumantasyon/OLCUMLER.md` B3.5: %73,3/%66,7) sonuç olduğu gibi
raporlanır, gizlenmez ya da yumuşatılmaz.

Para metriği (AI politikası vs vasat taban vs oracle) burada YOK — o Kişi
A'nın `training/genellenebilirlik_ve_para_metrigi.py`'sinde, sentetik
simülasyon verisiyle zaten yapılıyor. Bu betik yalnızca Kişi B'nin
sahiplendiği üç şeyi (router, gerekçe kalitesi, işletim performansı) ölçer.

## Her metrik neyi, nasıl ölçüyor

1. **Router** — `training/eval/router_taban.py`'nin aynı 30 soruluk, elle
   yazılmış setini yeniden kullanır (kendi ayrı bir set yazmak, B3.5'teki
   sonuçla karşılaştırılamaz bir sayı üretirdi).

2. **Uydurma sayı** — gerçek demo kataloğundan örneklenmiş N karar için
   `gerekce_uret()` çağrılır ve **nihai** `Gerekce.metin`, guard'ın kendi
   doğrulayıcısıyla (`app/llm/guard.py::adayi_dogrula`) yeniden kontrol
   edilir — kendi sayı ayıklama mantığımızı yazmak yerine production
   kodunun aynısı kullanılıyor (ilk denemede kendi regex'imiz SKU
   boyutlarını, ör. "13.5x19x19", sahte pozitif "uydurma" saydı —
   `adayi_dogrula` ürün adı/SKU/tedarikçi kodu gibi alanları maskeliyor).
   Bu metrik tanım gereği hep 0 çıkmalı — `guard.py::gerekceyi_guvenceye_al`
   şema tutmayan ya da sayı uyduran metni hiçbir zaman dışarı sızdırmıyor,
   şablona düşürüyor. Yine de **empirik olarak** doğrulanıyor; "böyle
   tasarlandı" ile "böyle çalıştığı ölçüldü" farklı iddialardır.

3. **Türkçe akıcılık** — ⚠️ **gösterge, sert kapı değil.** Yargıç da 1,5B'lik
   taban model; küçük bir modelin kendi sınıfındaki çıktıyı yargılaması
   gürültülü. Puanlama başarısız ayrıştırılırsa (model 1-5 arası bir sayı
   üretmezse) o örnek atlanır, ortalamaya dahil edilmez — sessizce 0 ya da 3
   varsayılmaz.

4. **Gecelik tarama süresi + tepe RAM** — `app/jobs/nightly.gecelik_tarama`
   gerçek üreteçlerle (`_gercek_karar_ureteci` + `llm_gerekce_ureteci`),
   **tam demo kataloğu üzerinde** çalıştırılır — örnekleme yok, gerçek
   `_cli()` çağrısının ne yapacağının birebir aynısı. RAM `psutil` ile
   ölçülür (`resource` modülü Windows'ta yok).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psutil

from app.contracts import DecisionCandidate
from app.core.config import ayarlar
from app.core.db import oturum_fabrikasi
from app.domain.stock.decide import (
    _demo_dunyasini_yukle,
    _siniflandirmayi_hesapla,
    ozellikten_karar_uret,
)
from app.domain.stock.features import katalog_ozelliklerini_hesapla
from app.jobs.nightly import _gercek_karar_ureteci, gecelik_tarama
from app.llm.client import OllamaIstemcisi
from app.llm.explain import anlatilacak_sayi_var_mi, gerekce_uret, llm_gerekce_ureteci
from app.llm.guard import adayi_dogrula
from training.eval.router_taban import kayitlari_yukle
from training.eval.router_taban import olc as router_olc

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SONUC_DOSYASI = Path(__file__).with_name("benchmark_sonuc.json")

HEDEF_ROUTER_TAM_DOGRULUK = 0.95
HEDEF_UYDURMA_SAYI = 0
HEDEF_GECELIK_TARAMA_SN = 600.0  # 10 dk
HEDEF_TEPE_RAM_MB = 4096.0  # 4 GB

UYDURMA_ORNEK_ADEDI = 20
AKICILIK_ORNEK_ADEDI = 10

TABAN_MODEL_ADI = "qwen2.5:1.5b-instruct"
"""Akıcılık yargıcının kullandığı model — bkz. `_akicilik_olc` docstring'i."""


@dataclass
class MetrikSonucu:
    ad: str
    deger: float
    hedef: float
    gecti: bool
    yorum: str = ""
    sert_kapi: bool = True

    def satir(self) -> str:
        isaret = "GECTI" if self.gecti else ("KALDI" if self.sert_kapi else "GOSTERGE")
        return f"  [{isaret:8s}] {self.ad:34s} {self.deger:>10.2f}  (hedef: {self.hedef})"


def router_metrigi() -> MetrikSonucu:
    kayitlar = kayitlari_yukle()
    router_olc(kayitlar, ayrinti=False)
    tam_dogru = sum(k.tam_dogru for k in kayitlar)
    oran = tam_dogru / len(kayitlar)
    return MetrikSonucu(
        ad="router: araç+parametre tam eşleşme",
        deger=oran,
        hedef=HEDEF_ROUTER_TAM_DOGRULUK,
        gecti=oran > HEDEF_ROUTER_TAM_DOGRULUK,
        yorum=f"{tam_dogru}/{len(kayitlar)} — bkz. dokumantasyon/OLCUMLER.md B3.5",
    )


def _demo_kararlari_ornekle(n: int) -> list[DecisionCandidate]:
    """`anlatilacak_sayi_var_mi()` True olan ilk N kararı döner.

    Sayısı olmayan kararlar (`stok.aksiyon_yok`) zaten LLM'i hiç çağırmıyor
    (bkz. `gerekce_uret`), o yüzden uydurma/akıcılık ölçümü için anlamsız.
    """
    dunya = _demo_dunyasini_yukle()
    siniflandirma = _siniflandirmayi_hesapla(dunya)
    ozellikler = katalog_ozelliklerini_hesapla(
        olcum_tarihi=dunya["olcum_tarihi"],
        talep=dunya["talep"],
        envanter_gunluk=dunya["envanter_gunluk"],
        sku_df=dunya["sku"],
        tedarikci_df=dunya["tedarikci"],
        siniflandirma=siniflandirma,
    )
    kararlar = []
    for o in ozellikler:
        aday = ozellikten_karar_uret(o)
        if anlatilacak_sayi_var_mi(aday):
            kararlar.append(aday)
        if len(kararlar) >= n:
            break
    return kararlar


_AKICILIK_ISTEMI = (
    "Asagidaki Turkce cumleyi 1 (cok kotu/bozuk) ile 5 (akici/dogal) arasinda "
    "PUANLA. Yalnizca tek bir rakam yaz, baska hicbir sey yazma.\n\n"
    "CUMLE: {metin}\n\nPUAN:"
)


def _akicilik_olc(ayar, orneklenenler: list[tuple[DecisionCandidate, str]]) -> MetrikSonucu:
    """Yargıç bilinçli olarak TABAN modelde çalışır.

    Eğitilmiş model yalnızca `GOREV: router` / `GOREV: gerekce` biçimini
    görmüş; bu ad-hoc "cümleyi puanla" talimatı o biçimde değil, muhtemelen
    yanıt vermez ya da anlamsız üretir. Genel talimat takibi hâlâ taban
    modelde.
    """
    yargic_ayar = ayar.model_copy(
        update={"llm_model_adi": TABAN_MODEL_ADI, "llm_istem_bicimi": "taban"}
    )
    puanlar: list[int] = []
    with OllamaIstemcisi(ayar=yargic_ayar) as istemci:
        for _, metin in orneklenenler[:AKICILIK_ORNEK_ADEDI]:
            try:
                sonuc = istemci.uret(
                    _AKICILIK_ISTEMI.format(metin=metin), max_token=5, sicaklik=0.0, tohum=42
                )
                eslesme = re.search(r"[1-5]", sonuc.metin)
                if eslesme:
                    puanlar.append(int(eslesme.group()))
            except Exception:
                continue

    ornek_sayisi = min(len(orneklenenler), AKICILIK_ORNEK_ADEDI)
    ortalama = sum(puanlar) / len(puanlar) if puanlar else 0.0
    return MetrikSonucu(
        ad="gerekçe: Türkçe akıcılık (LLM-jüri, 1-5)",
        deger=ortalama,
        hedef=4.0,
        gecti=ortalama >= 4.0,
        yorum=f"{len(puanlar)}/{ornek_sayisi} örnek puanlandı — gösterge, sert kapı değil",
        sert_kapi=False,
    )


def uydurma_ve_akicilik_metrikleri(ayar) -> tuple[MetrikSonucu, MetrikSonucu | None, list[dict]]:
    kararlar = _demo_kararlari_ornekle(UYDURMA_ORNEK_ADEDI)
    detaylar: list[dict[str, Any]] = []
    uydurma_sayisi = 0
    kabul_edilenler: list[tuple[DecisionCandidate, str]] = []

    with OllamaIstemcisi(ayar=ayar) as istemci:
        for aday in kararlar:
            g = gerekce_uret(aday, istemci)
            # Guard'ın kendi doğrulayıcısı (`adayi_dogrula`) kullanılıyor —
            # ürün adı/SKU/tedarikçi kodundaki rakamları maskeliyor
            # (`maskelenecek_alanlar`). Kendi regex'imizi yazmak SKU
            # boyutlarını ("13.5x19x19") sahte pozitif olarak işaretledi;
            # bu yüzden production kodunun aynısı yeniden kullanılıyor.
            dogrulama = adayi_dogrula(g.metin, aday)
            uydurmalar = dogrulama.reddedilen
            if uydurmalar:
                uydurma_sayisi += 1
            detaylar.append(
                {
                    "karar_id": str(aday.karar_id),
                    "guard_sonucu": g.guard_sonucu.value,
                    "uydurma_bulundu": bool(uydurmalar),
                    "uydurma_sayilar": uydurmalar,
                }
            )
            if g.guard_sonucu.value in {"gecti", "yeniden_uretildi"}:
                kabul_edilenler.append((aday, g.metin))

    uydurma_metrigi = MetrikSonucu(
        ad="gerekçe: uydurma sayı (final metinde)",
        deger=float(uydurma_sayisi),
        hedef=float(HEDEF_UYDURMA_SAYI),
        gecti=uydurma_sayisi == HEDEF_UYDURMA_SAYI,
        yorum=(
            f"{len(kararlar)} gerçek karar örneklendi, "
            f"{len(kabul_edilenler)} LLM'den (şablona düşmeden) kabul edildi"
        ),
        sert_kapi=True,
    )

    akicilik_metrigi = _akicilik_olc(ayar, kabul_edilenler) if kabul_edilenler else None
    return uydurma_metrigi, akicilik_metrigi, detaylar


def gecelik_tarama_metrikleri() -> tuple[MetrikSonucu, MetrikSonucu]:
    ayar = ayarlar()
    surec = psutil.Process()
    tepe_ram_mb = surec.memory_info().rss / 1024**2

    with oturum_fabrikasi()() as oturum, OllamaIstemcisi(ayar=ayar) as istemci:
        baslangic = time.perf_counter()
        ozet = gecelik_tarama(
            oturum,
            ayar,
            karar_ureteci=_gercek_karar_ureteci,
            gerekce_ureteci=llm_gerekce_ureteci(istemci),
        )
        gecen_sn = time.perf_counter() - baslangic
        tepe_ram_mb = max(tepe_ram_mb, surec.memory_info().rss / 1024**2)

    print(
        f"\n  (gecelik tarama detayi: {ozet.taranan} SKU tarandi, "
        f"{ozet.gerekce_uretilen} gerekce uretildi)"
    )

    sure_metrigi = MetrikSonucu(
        ad="gecelik tarama süresi (sn)",
        deger=gecen_sn,
        hedef=HEDEF_GECELIK_TARAMA_SN,
        gecti=gecen_sn < HEDEF_GECELIK_TARAMA_SN,
        yorum=f"{ozet.taranan} SKU, {ozet.gerekce_uretilen} gerekçe üretildi",
    )
    ram_metrigi = MetrikSonucu(
        ad="tepe RAM (MB)",
        deger=tepe_ram_mb,
        hedef=HEDEF_TEPE_RAM_MB,
        gecti=tepe_ram_mb < HEDEF_TEPE_RAM_MB,
        yorum="bu Python sürecinin RSS'i — Ollama sunucusu ayrı süreç, dahil değil",
    )
    return sure_metrigi, ram_metrigi


def _cli() -> None:
    ayristirici = argparse.ArgumentParser(description="Faz 5 uçtan uca benchmark")
    ayristirici.add_argument(
        "--atla",
        nargs="*",
        choices=("router", "uydurma", "gecelik"),
        default=[],
        help="Zaman alan adımları atla (ör. --atla gecelik)",
    )
    args = ayristirici.parse_args()
    ayar = ayarlar()

    print("=" * 72)
    print(f"FAZ 5 BENCHMARK — model: {ayar.llm_model_adi} ({ayar.llm_istem_bicimi})")
    print("=" * 72)

    sonuclar: list[MetrikSonucu] = []
    detay: dict[str, Any] = {}

    if "router" not in args.atla:
        print("\n[1/3] Router ölçülüyor (30 soru)...")
        sonuclar.append(router_metrigi())

    if "uydurma" not in args.atla:
        print(f"\n[2/3] Uydurma sayı + akıcılık ölçülüyor ({UYDURMA_ORNEK_ADEDI} gerçek karar)...")
        uydurma, akicilik, detaylar = uydurma_ve_akicilik_metrikleri(ayar)
        sonuclar.append(uydurma)
        if akicilik:
            sonuclar.append(akicilik)
        detay["uydurma_detay"] = detaylar

    if "gecelik" not in args.atla:
        print("\n[3/3] Gecelik tarama çalıştırılıyor (tam katalog, gerçek üreteçler)...")
        sure, ram = gecelik_tarama_metrikleri()
        sonuclar.append(sure)
        sonuclar.append(ram)

    print("\n" + "=" * 72)
    print("SONUÇ")
    print("=" * 72)
    for s in sonuclar:
        print(s.satir())
        if s.yorum:
            print(f"             {s.yorum}")

    sert_kapilar = [s for s in sonuclar if s.sert_kapi]
    basarisiz = [s for s in sert_kapilar if not s.gecti]
    print()
    if not basarisiz:
        print(f"✅ {len(sert_kapilar)} sert kapının tamamı geçti.")
    else:
        print(f"❌ {len(basarisiz)}/{len(sert_kapilar)} sert kapı KALDI:")
        for s in basarisiz:
            print(f"   - {s.ad}")
    print("\n⚠️ threshold moduna geçiş kararı bu rapora dayanmalı — teknik değil süreç kararı.")

    SONUC_DOSYASI.write_text(
        json.dumps(
            {
                "model": ayar.llm_model_adi,
                "istem_bicimi": ayar.llm_istem_bicimi,
                "metrikler": [s.__dict__ for s in sonuclar],
                **detay,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nHam sonuçlar: {SONUC_DOSYASI}")


if __name__ == "__main__":
    _cli()
