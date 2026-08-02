"""Train/val/test bölme + golden set adayı (Faz 3 A3.5).

Sahip: Kişi A · Faz 3 A3.5 (golden set NİHAİ onayı Kişi B ile birlikte)

**Neden SKU bazında, satır bazında rastgele DEĞİL:** Aynı SKU hem eğitimde
hem testte görülürse model o SKU'nun sayılarını ezberleyebilir, ölçüm yalan
çıkar (bkz. `dokumantasyon/KISI-A-GOREV.md` A3.5). Bu yüzden önce SKU
evreni train/val/test'e bölünüyor, sonra her iki veri seti de (gerekçe VE
router) SKU'ya bağlı satırlarını bu bölmeye göre yerleştiriyor — bir SKU'nun
TÜM kayıtları (hangi haftadan/hangi soru şablonundan gelirse gelsin) aynı
bölmede kalıyor.

Router verisinde SKU'ya bağlı olmayan satırlar (kategori/tedarikçi/tarih
ifadesi/parametresiz araçlar) için SKU evreni bir şey ifade etmiyor —
kategori yalnızca 8 tane, hepsini train'e hapsetmek test'i anlamsızlaştırır.
Bunlar yerine metnin kendisinden türeyen deterministik bir bölme kullanılır
(hash bazlı) — aynı soru metni her çalıştırmada aynı bölmeye düşer.

**Golden set adayı:** `golden_set_adayi_olustur()` yalnızca bir ADAY üretir
— zorlayıcı vakalara (veri azlığı, nadir karar tipi, guard'ın şablona
düştüğü satırlar) bilinçli olarak ağırlık verir. Nihai onay ("gerçekten
zorlayıcı mı, elle eklenecek başka vaka var mı") Kişi B ile birlikte
yapılacak — bkz. görev tanımındaki "son yarım günü Kişi B ile birlikte".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Literal

Bolme = Literal["train", "val", "test"]

VARSAYILAN_ORANLAR: dict[Bolme, float] = {"train": 0.80, "val": 0.10, "test": 0.10}
VARSAYILAN_SEED = 13
VARSAYILAN_GOLDEN_SET_HEDEFI = 400


def _jsonl_oku(yol: Path) -> list[dict[str, Any]]:
    with open(yol, encoding="utf-8") as f:
        return [json.loads(satir) for satir in f if satir.strip()]


def _jsonl_yaz(kayitlar: list[dict[str, Any]], yol: Path) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    with open(yol, "w", encoding="utf-8") as f:
        for kayit in kayitlar:
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")


def _oranlari_dogrula(oranlar: dict[Bolme, float]) -> None:
    toplam = sum(oranlar.values())
    if abs(toplam - 1.0) > 1e-9:
        raise ValueError(f"Oranların toplamı 1.0 olmalı, {toplam} bulundu")


def _metne_gore_bol(metin: str, oranlar: dict[Bolme, float], tuz: str) -> Bolme:
    """Deterministik, SKU'suz satırlar için: aynı metin her zaman aynı bölmeye düşer.

    `tuz` aynı metnin farklı bağlamlarda (ör. hem gerekçe hem router verisinde
    aynı kelimeler geçse) birbirinden bağımsız bölünmesini sağlar.
    """
    özet = hashlib.sha256(f"{tuz}:{metin}".encode()).hexdigest()
    oran = int(özet[:8], 16) / 0xFFFFFFFF
    eşik_train = oranlar["train"]
    eşik_val = oranlar["train"] + oranlar["val"]
    if oran < eşik_train:
        return "train"
    if oran < eşik_val:
        return "val"
    return "test"


def sku_bolmelerini_olustur(
    sku_ids: list[str],
    oranlar: dict[Bolme, float] = VARSAYILAN_ORANLAR,
    seed: int = VARSAYILAN_SEED,
) -> dict[str, Bolme]:
    """Her SKU'yu tek bir bölmeye atar — o SKU'nun TÜM kayıtları bu bölmede kalır."""
    _oranlari_dogrula(oranlar)
    sirali = sorted(set(sku_ids))
    return {sku_id: _metne_gore_bol(sku_id, oranlar, tuz=f"sku-{seed}") for sku_id in sirali}


def gerekce_veri_setini_bol(
    karar_noktalari: list[dict[str, Any]],
    gerekceler: list[dict[str, Any]],
    sku_bolmeleri: dict[str, Bolme],
) -> dict[Bolme, list[dict[str, Any]]]:
    """`karar_noktalari.jsonl` (özellikler+karar) ile `gerekceler.jsonl`'ü
    (sku_id, tarih) üzerinden birleştirip SKU bölmesine göre dağıtır.

    Gerçek eğitim çifti budur: (özellikler + kural motoru kararı) → gerekçe
    metni. `gerekceler.jsonl` tek başına yeterli değil (bkz. `label_rationale.py`
    docstring'i) — girdi tarafı burada tamamlanıyor.
    """
    gerekce_indeks = {(g["sku_id"], g["tarih"]): g for g in gerekceler}

    sonuc: dict[Bolme, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}
    eslesmeyen = 0
    for satir in karar_noktalari:
        anahtar = (satir["sku_id"], satir["tarih"])
        gerekce = gerekce_indeks.get(anahtar)
        if gerekce is None:
            eslesmeyen += 1
            continue
        bolme = sku_bolmeleri.get(satir["sku_id"])
        if bolme is None:
            continue
        birlesik = {
            **satir,
            "gerekce_metni": gerekce["metin"],
            "guard_sonucu": gerekce["guard_sonucu"],
        }
        sonuc[bolme].append(birlesik)

    if eslesmeyen:
        print(f"[A3.5] Uyarı: {eslesmeyen} karar noktası için gerekçe bulunamadı, atlandı.")

    return sonuc


def router_veri_setini_bol(
    router_satirlari: list[dict[str, Any]],
    sku_bolmeleri: dict[str, Bolme],
    oranlar: dict[Bolme, float] = VARSAYILAN_ORANLAR,
    seed: int = VARSAYILAN_SEED,
) -> dict[Bolme, list[dict[str, Any]]]:
    """Router satırlarını SKU'ya bağlıysa SKU bölmesine, değilse soru
    metninin deterministik hash'ine göre böler. Tekrarlanan satırlar
    (ör. hem A3.2 hem A3.3 çıktısında aynı soru) yalnızca bir kez sayılır.
    """
    _oranlari_dogrula(oranlar)
    görülen: set[str] = set()
    sonuc: dict[Bolme, list[dict[str, Any]]] = {"train": [], "val": [], "test": []}

    for satir in router_satirlari:
        soru = satir["soru"]
        if soru in görülen:
            continue
        görülen.add(soru)

        sku_id = satir.get("parametreler", {}).get("sku_adi")
        if sku_id is not None and sku_id in sku_bolmeleri:
            bolme = sku_bolmeleri[sku_id]
        else:
            bolme = _metne_gore_bol(soru, oranlar, tuz=f"router-{seed}")

        sonuc[bolme].append(satir)

    return sonuc


def golden_set_adayi_olustur(
    gerekce_test: list[dict[str, Any]],
    router_test: list[dict[str, Any]],
    hedef: int = VARSAYILAN_GOLDEN_SET_HEDEFI,
    seed: int = VARSAYILAN_SEED,
) -> list[dict[str, Any]]:
    """Yalnızca test bölmesinden, zorlayıcı vakalara ağırlık vererek bir ADAY üretir.

    Ağırlıklandırma: `guard_sonucu == "sablona_dustu"` (LLM'in güvenle
    reddedildiği, en riskli örnekler) ve `veri_gun_sayisi` düşük (az veriyle
    karar verilmiş) satırlar normalden fazla temsil edilir. Nihai onay ve
    elle eklenecek ek vakalar Kişi B ile birlikte yapılacak — bu fonksiyon
    yalnızca başlangıç noktası.
    """
    import random

    rng = random.Random(seed)

    zorlayici_mi = [
        s["guard_sonucu"] == "sablona_dustu" or s["ozellikler"]["veri_gun_sayisi"] < 30
        for s in gerekce_test
    ]
    zorlayici = [s for s, z in zip(gerekce_test, zorlayici_mi, strict=True) if z]
    sikinti_yok = [s for s, z in zip(gerekce_test, zorlayici_mi, strict=True) if not z]

    gerekce_hedefi = int(hedef * 0.6)
    zorlayici_pay = min(len(zorlayici), gerekce_hedefi // 2)
    normal_pay = min(len(sikinti_yok), gerekce_hedefi - zorlayici_pay)

    secilen_gerekce = rng.sample(zorlayici, zorlayici_pay) + rng.sample(sikinti_yok, normal_pay)
    for s in secilen_gerekce:
        s["kaynak"] = "gerekce"

    router_hedefi = hedef - len(secilen_gerekce)
    secilen_router = rng.sample(router_test, min(router_hedefi, len(router_test)))
    for s in secilen_router:
        s["kaynak"] = "router"

    aday = secilen_gerekce + secilen_router
    rng.shuffle(aday)
    return aday


def _cli() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ayristirici = argparse.ArgumentParser(description="Train/val/test bölme (A3.5)")
    ayristirici.add_argument("--karar-noktalari", default="data/egitim/karar_noktalari.jsonl")
    ayristirici.add_argument("--gerekceler", default="data/egitim/gerekceler.jsonl")
    ayristirici.add_argument(
        "--router-girdileri",
        nargs="+",
        default=["data/egitim/router_sorulari.jsonl", "data/egitim/router_sorulari_parafraz.jsonl"],
    )
    ayristirici.add_argument("--cikti-dizini", default="data/egitim")
    ayristirici.add_argument("--seed", type=int, default=VARSAYILAN_SEED)
    ayristirici.add_argument("--golden-set-hedefi", type=int, default=VARSAYILAN_GOLDEN_SET_HEDEFI)
    args = ayristirici.parse_args()

    cikti_dizini = Path(args.cikti_dizini)

    karar_noktalari = _jsonl_oku(Path(args.karar_noktalari))
    gerekceler = _jsonl_oku(Path(args.gerekceler))
    router_satirlari: list[dict[str, Any]] = []
    for yol in args.router_girdileri:
        router_satirlari.extend(_jsonl_oku(Path(yol)))

    tum_sku_idler = {s["sku_id"] for s in karar_noktalari}
    sku_bolmeleri = sku_bolmelerini_olustur(list(tum_sku_idler), seed=args.seed)

    gerekce_bolunmus = gerekce_veri_setini_bol(karar_noktalari, gerekceler, sku_bolmeleri)
    router_bolunmus = router_veri_setini_bol(router_satirlari, sku_bolmeleri, seed=args.seed)

    print("[A3.5] SKU bölme dağılımı:")
    for bolme in ("train", "val", "test"):
        n_sku = sum(1 for v in sku_bolmeleri.values() if v == bolme)
        print(f"  {bolme}: {n_sku} SKU (%{100 * n_sku / len(sku_bolmeleri):.1f})")

    print()
    print("[A3.5] Gerekçe veri seti:")
    for bolme in ("train", "val", "test"):
        _jsonl_yaz(gerekce_bolunmus[bolme], cikti_dizini / f"gerekce_{bolme}.jsonl")
        print(f"  {bolme}: {len(gerekce_bolunmus[bolme])} satır")

    print()
    print("[A3.5] Router veri seti:")
    for bolme in ("train", "val", "test"):
        _jsonl_yaz(router_bolunmus[bolme], cikti_dizini / f"router_{bolme}.jsonl")
        print(f"  {bolme}: {len(router_bolunmus[bolme])} satır")

    # Bütünlük kontrolü: hiçbir SKU iki bölmede birden görünmüyor.
    gerekce_sku = {b: {s["sku_id"] for s in satirlar} for b, satirlar in gerekce_bolunmus.items()}
    kesisim = (
        (gerekce_sku["train"] & gerekce_sku["val"])
        | (gerekce_sku["train"] & gerekce_sku["test"])
        | (gerekce_sku["val"] & gerekce_sku["test"])
    )
    print()
    if kesisim:
        print(f"[A3.5] ❌ SKU SIZINTISI: {len(kesisim)} SKU birden fazla bölmede görünüyor!")
    else:
        print("[A3.5] ✅ Bölmeler arası SKU sızıntısı yok.")

    golden = golden_set_adayi_olustur(
        gerekce_bolunmus["test"],
        router_bolunmus["test"],
        hedef=args.golden_set_hedefi,
        seed=args.seed,
    )
    _jsonl_yaz(golden, cikti_dizini / "golden_set_aday.jsonl")
    print()
    print(f"[A3.5] Golden set adayı: {len(golden)} satır -> golden_set_aday.jsonl")
    print("[A3.5] Bu bir ADAY — nihai onay Kişi B ile birlikte yapılacak (bkz. modül docstring'i).")


if __name__ == "__main__":
    _cli()
