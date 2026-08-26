"""Golden set incelemesi — ortak onay için hazırlık (Kişi B tarafı).

    uv run python -m training.eval.golden_set_inceleme --dosya <yol>

Golden set, sistemin "doğru cevap" referansı. Ölçümlerin tamamı buna
dayanacağı için **tek kişi kapatamaz** — bu betik Kişi B'nin incelemesini
üretir, karar ortak verilir.

Bakılanlar:

1. **Sızıntı.** Golden set'teki bir örnek **eğitim veya doğrulama** verisinde
   de varsa, model onu ezberlemiş olabilir ve ölçüm şişer. En kritik kontrol.

   ⚠️ **`*_test.jsonl` ile çakışma sızıntı DEĞİLDİR.** Golden set zaten
   ayrılmış test bölümünden seçiliyor; oradaki örtüşme beklenen ve doğru
   olandır. İlk sürümde bu ayrım yapılmamıştı ve betik "400 sızıntı" diye
   yanlış alarm verdi. Tehlikeli olan tek şey `train` ve `val` çakışması:
   ilki modele öğretilmiş, ikincisi eğitim sırasında karar vermek için
   kullanılmıştır.
2. **Tekrar.** Aynı soru/karar iki kez sayılıyorsa ağırlığı iki katına çıkar.
3. **Kapsam.** Yedi aracın ve üç karar tipinin hepsi temsil ediliyor mu?
   Seyrek araç eksikse ölçüm o aracı hiç sınamaz.
4. **Guard uyumu.** Gerekçe satırlarındaki hedef metinler bugünkü guard'dan
   geçiyor mu? Geçmiyorsa referansın kendisi kuralı ihlal ediyor demektir.
5. **Sözleşme uyumu.** Araç adları `AracAdi` ile, karar tipleri `KararTipi`
   ile birebir mi?
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.contracts import KararTipi
from app.llm.guard import sayilari_dogrula
from app.llm.schemas import AracAdi

# Bir araci bu sayidan az ornekle olcmek gurultu uretir: 4 ornekte tek
# hata dogrulugu %25 oynatir. Sinir kesin degil ama altinda kalan araclar
# icin "olctuk" demek dogru olmaz.
ASGARI_ORNEK = 5

VARSAYILAN = Path("D:/veri-20260802T115351Z-1-001/veri/golden_set_aday.jsonl")
EGITIM_KLASORU = VARSAYILAN.parent


def oku(yol: Path) -> list[dict]:
    with yol.open(encoding="utf-8") as f:
        return [json.loads(s) for s in f if s.strip()]


def _anahtar(k: dict) -> str:
    """Satırın kimliği — sızıntı ve tekrar karşılaştırmasında kullanılır."""
    if k.get("kaynak") == "router" or "soru" in k:
        return "R:" + k.get("soru", "").strip().casefold()
    return "G:" + (k.get("sku_id", "") + "|" + str(k.get("tarih", "")))


# `test` bilinçli olarak TEHLIKELI değil: golden set zaten oradan seçiliyor.
_TEHLIKELI = ("router_train.jsonl", "router_val.jsonl", "gerekce_train.jsonl", "gerekce_val.jsonl")


def sizinti_kontrolu(golden: list[dict]) -> dict[str, int]:
    """Golden set örnekleri hangi bölümlerde de geçiyor?"""
    golden_anahtarlari = {_anahtar(k) for k in golden}
    sonuc: dict[str, int] = {}
    for ad in (
        "router_train.jsonl",
        "router_val.jsonl",
        "router_test.jsonl",
        "gerekce_train.jsonl",
        "gerekce_val.jsonl",
        "gerekce_test.jsonl",
    ):
        yol = EGITIM_KLASORU / ad
        if not yol.exists():
            continue
        ortak = 0
        with yol.open(encoding="utf-8") as f:
            for satir in f:
                if _anahtar(json.loads(satir)) in golden_anahtarlari:
                    ortak += 1
        sonuc[ad] = ortak
    return sonuc


def main() -> None:
    ayristirici = argparse.ArgumentParser(description="Golden set incelemesi")
    ayristirici.add_argument("--dosya", type=Path, default=VARSAYILAN)
    args = ayristirici.parse_args()

    golden = oku(args.dosya)
    router = [k for k in golden if k.get("kaynak") == "router"]
    gerekce = [k for k in golden if k.get("kaynak") == "gerekce"]

    print("=" * 66)
    print("GOLDEN SET INCELEMESI")
    print("=" * 66)
    print(f"  dosya  : {args.dosya.name}")
    print(f"  toplam : {len(golden)}  (router {len(router)} · gerekce {len(gerekce)})")

    # --- 1. Sizinti ---------------------------------------------------------
    print("\n1. SIZINTI")
    print("   " + "-" * 58)
    ortusme = sizinti_kontrolu(golden)
    toplam_sizinti = sum(adet for ad, adet in ortusme.items() if ad in _TEHLIKELI)
    for ad, adet in ortusme.items():
        if ad in _TEHLIKELI:
            isaret = "  <-- SIZINTI!" if adet else "  temiz"
        else:
            isaret = "  (beklenen — golden zaten test'ten seciliyor)"
        print(f"   {ad:24s} {adet:5d}{isaret}")
    print()
    if toplam_sizinti:
        print(f"   ⚠️ train/val ile {toplam_sizinti} ortusme — olcum siser.")
    else:
        print("   ✅ train ve val ile ortusme YOK. Golden set temiz.")

    # --- 2. Tekrar ----------------------------------------------------------
    print("\n2. TEKRAR")
    print("   " + "-" * 58)
    anahtarlar = Counter(_anahtar(k) for k in golden)
    tekrarli = {a: n for a, n in anahtarlar.items() if n > 1}
    print(f"   ozgun ornek : {len(anahtarlar)}/{len(golden)}")
    print(f"   tekrarlanan : {len(tekrarli)}")
    for a, n in list(tekrarli.items())[:5]:
        print(f"     {n}x  {a[:60]}")

    # --- 3. Kapsam ----------------------------------------------------------
    print("\n3. KAPSAM")
    print("   " + "-" * 58)
    if router:
        araclar = Counter(k.get("arac") for k in router)
        for arac in sorted(a.value for a in AracAdi):
            adet = araclar.get(arac, 0)
            isaret = "  <-- HIC YOK" if adet == 0 else ""
            print(f"   {arac:32s} {adet:4d}{isaret}")
        bilinmeyen = set(araclar) - {a.value for a in AracAdi}
        if bilinmeyen:
            print(f"   ⚠️ SOZLESMEDE OLMAYAN ARAC: {bilinmeyen}")
    if gerekce:
        print()
        tipler = Counter(k.get("karar_tipi") for k in gerekce)
        for tip in sorted(t.value for t in KararTipi):
            adet = tipler.get(tip, 0)
            print(f"   {tip:32s} {adet:4d}")
        bilinmeyen = set(tipler) - {t.value for t in KararTipi}
        if bilinmeyen:
            print(f"   ⚠️ SOZLESMEDE OLMAYAN KARAR TIPI: {bilinmeyen}")

    # --- 4. Guard uyumu -----------------------------------------------------
    print("\n4. GUARD UYUMU (gerekce satirlarinin hedef metinleri)")
    print("   " + "-" * 58)
    gecen = 0
    ornekler: list[tuple[str, list[float]]] = []
    for k in gerekce:
        o = k.get("ozellikler", {})
        maske = [
            o.get("sku_adi", ""),
            o.get("sku_id", ""),
            o.get("tedarikci_adi", ""),
            o.get("tedarikci_id", ""),
        ]
        sonuc = sayilari_dogrula(
            k.get("gerekce_metni", ""),
            k.get("izinli_sayilar", []),
            maskelenecek=[m for m in maske if m],
        )
        if sonuc.gecti:
            gecen += 1
        elif len(ornekler) < 5:
            ornekler.append((o.get("sku_adi", "?"), sonuc.reddedilen))

    if gerekce:
        oran = gecen / len(gerekce) * 100
        print(f"   guard'dan gecen : {gecen}/{len(gerekce)}  (%{oran:.1f})")
        for ad, red in ornekler:
            print(f"     RED  {ad[:34]:36s} {red}")
        if gecen < len(gerekce):
            print("   ⚠️ Referansin kendisi guard'i ihlal ediyor.")

    # --- Karar --------------------------------------------------------------
    print("\n" + "=" * 66)
    sorunlar = []
    if toplam_sizinti:
        sorunlar.append(f"train/val sizintisi {toplam_sizinti}")
    if tekrarli:
        sorunlar.append(f"tekrar {len(tekrarli)}")
    if gerekce and gecen < len(gerekce):
        sorunlar.append(f"guard reddi {len(gerekce) - gecen}")

    # Kapsam: bir araci N ornekle olcmek, N kucukse hicbir sey olcmemektir.
    # 5'in altinda tek bir yanlis cevap oran %20 oynatir; bu sinyal degil
    # gurultu. Sizinti kadar kritik degil ama ortak onayda konusulmali.
    if router:
        ince = [a.value for a in AracAdi if araclar.get(a.value, 0) < ASGARI_ORNEK]
        if ince:
            sorunlar.append(f"{len(ince)} arac {ASGARI_ORNEK} ornekten az")
            print("  ⚠️ OLCULEMEYECEK KADAR INCE ARACLAR:")
            for a in ince:
                adet = araclar.get(a, 0)
                pay = 100 / adet if adet else 0
                print(f"       {a:32s} {adet} ornek  (tek hata = %{pay:.0f} oynama)")
    if gerekce:
        bos = [t.value for t in KararTipi if tipler.get(t.value, 0) == 0]
        if bos:
            sorunlar.append(f"{len(bos)} karar tipi hic yok")
            print(f"  ⚠️ HIC ORNEGI OLMAYAN KARAR TIPI: {bos}")
            print("       (kural motoru bu tipi hic uretmiyorsa beklenen olabilir)")

    if sorunlar:
        print(f"  ⚠️ INCELEME NOTLARI: {', '.join(sorunlar)}")
        print("  Ortak onaydan once konusulmali.")
    else:
        print("  ✅ Kisi B tarafindan sorun bulunmadi — ortak onaya hazir.")
    print("=" * 66)


if __name__ == "__main__":
    main()
