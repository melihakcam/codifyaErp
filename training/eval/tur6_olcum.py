"""6. tur ölçümü — iki alanlı gerekçe kalitesi (Faz 8).

Sahip: Kişi A · Tur 8

    uv run python -m training.eval.tur6_olcum --model codifya-router:tur6
    uv run python -m training.eval.tur6_olcum --model codifya-router:tur6 --karsilastir tur5

## ⚠️ Bu turun kapısı GUARD DEĞİL

Önceki turlarda ölçüt "guard uydurma sayı yakaladı mı" idi. Finansta o ölçüt
**çalışmıyor** ve bu ölçülerek görüldü: tur5'te 20 finans gerekçesinin
20'si de guard'dan geçti, ama metinlerin dörtte biri istem satırlarını
(`karar:`, `Gerekce:`, `VERILER`) doğrudan çıktıya sızdırıyordu.

Guard yalnızca **sayılara** bakıyor. Model istemdeki sayıları kopyalayıp
etrafına anlamsız Türkçe dizerse hiçbir sayı uydurulmadığı için guard
sessiz kalır. Yani %100 geçme oranı, kalite hakkında hiçbir şey söylemez.

Bu yüzden buradaki asıl metrik **istem sızıntısı**:

    sizinti_orani = istem satırı içeren çıktı / toplam çıktı

Tur5'te finansta ~%25. Tur6 bunu belirgin düşürmezse tur geri alınmalı.

## Ölçülen dört şey

| metrik | ne söyler | iyi yön |
|---|---|---|
| `sizinti_orani` | model istemi geri kusuyor mu | ↓ |
| `guard_gecti_orani` | uydurma sayı var mı | ↑ |
| `sablona_dusme_orani` | kaç gerekçe üretilemedi | ↓ |
| `ort_uzunluk` | cümle mi, tirat mı | 80-250 arası |

⚠️ Dördü **birlikte** okunur. Bugün beş kez görüldü ki tek metrik yalan
söyler: sızıntı düşerken şablona düşme fırlıyorsa model susmayı öğrenmiş
demektir, düzelmiş değil.

## Az örnekli iki karar tipi

`finans.karsilik_ayir` ve `finans.kredi_limiti_dusur` eğitim setinde
sırasıyla 137 ve 111 **eşsiz** örnekle temsil ediliyor; dengeleyici onları
~10 kat çoğaltıyor. Aynı örnekler tekrarlanıyor, yeni bilgi eklenmiyor.
Bu yüzden rapor karar tipi **kırılımlı** — genel ortalama iyi görünürken
bu iki tip öğrenilmemiş olabilir ve tabloda görünür.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.contracts import DecisionCandidate, GuardSonucu
from app.core.config import Ayarlar
from app.llm.client import OllamaIstemcisi
from app.llm.explain import anlatilacak_sayi_var_mi, gerekce_uret

SONUC_DIZINI = Path(__file__).parent

# İstem satırlarının çıktıya sızdığını gösteren imzalar.
#
# ⚠️ Bunlar "model kötü yazdı" değil, "model istemi kopyaladı" işareti —
# ikisi farklı arızalar ve farklı çözümleri var. Kötü Türkçe eğitim
# verisinin kalitesini, istem kopyalama ise eğitim biçiminin kendisini
# işaret eder.
_SIZINTI_IMZALARI = (
    "VERILER",
    "GOREV:",
    "GEREKCE:",
    "Gerekce:",
    "karar:",
    "musteri:",
    "urun:",
)

# Aynı cümlenin tekrar tekrar yazılması (tur4'te görülmüştü).
_TEKRAR_DESENI = re.compile(r"(.{25,})\1", re.DOTALL)


@dataclass
class TipSonucu:
    toplam: int = 0
    sizintili: int = 0
    guard_gecti: int = 0
    sablona_dustu: int = 0
    tekrarli: int = 0
    uzunluklar: list[int] = field(default_factory=list)

    @property
    def sizinti_orani(self) -> float:
        return self.sizintili / self.toplam if self.toplam else 0.0

    @property
    def guard_orani(self) -> float:
        return self.guard_gecti / self.toplam if self.toplam else 0.0

    @property
    def sablon_orani(self) -> float:
        return self.sablona_dustu / self.toplam if self.toplam else 0.0

    @property
    def ort_uzunluk(self) -> float:
        return sum(self.uzunluklar) / len(self.uzunluklar) if self.uzunluklar else 0.0


def sizinti_var_mi(metin: str) -> bool:
    """Çıktıda istem satırı var mı?

    ⚠️ Küçük/büyük harf duyarlı bilerek: "karar" kelimesi doğal bir
    cümlede geçebilir ama "karar:" iki nokta üst üsteyle istem biçimidir.
    Duyarsız arama, geçerli cümleleri sızıntı sayardı.
    """
    return any(imza in metin for imza in _SIZINTI_IMZALARI)


def _kararlari_topla(n_stok: int, n_finans: int) -> list[DecisionCandidate]:
    """Ölçüm için stok ve finans kararları — ikisi de gerekli.

    ⚠️ Yalnızca finans ölçmek yetmez: tur6 finansı öğrenirken stoğu
    unutmuş olabilir (felaket unutma). Karşılaştırma tablosu iki alanı da
    gösteriyor, çünkü bir alanın kazancı diğerinin kaybıysa tur başarısız.
    """
    from app.domain.finance.decide import _demo_ozellikleri, ozellikten_kararlar_uret
    from app.domain.stock.decide import _demo_dunyasini_yukle, _siniflandirmayi_hesapla
    from app.domain.stock.decide import ozellikten_karar_uret as stok_karar
    from app.domain.stock.features import katalog_ozelliklerini_hesapla

    kararlar: list[DecisionCandidate] = []

    dunya = _demo_dunyasini_yukle()
    siniflandirma = _siniflandirmayi_hesapla(dunya)
    stok_ozellikleri = katalog_ozelliklerini_hesapla(
        olcum_tarihi=dunya["olcum_tarihi"],
        talep=dunya["talep"],
        envanter_gunluk=dunya["envanter_gunluk"],
        sku_df=dunya["sku"],
        tedarikci_df=dunya["tedarikci"],
        siniflandirma=siniflandirma,
    )
    stok_alinan = 0
    for o in stok_ozellikleri:
        aday = stok_karar(o)
        if anlatilacak_sayi_var_mi(aday):
            kararlar.append(aday)
            stok_alinan += 1
        if stok_alinan >= n_stok:
            break

    # Finansta karar tipi çeşitliliği önemli: az örnekli iki tip ölçüme
    # girmezse "öğrendi mi" sorusu cevapsız kalır. Tip başına kota var.
    tip_kotasi = max(1, n_finans // 4)
    tip_sayaci: dict[str, int] = {}
    for ozellik in _demo_ozellikleri():
        for aday in ozellikten_kararlar_uret(ozellik):
            tip = aday.tip.value
            if tip_sayaci.get(tip, 0) >= tip_kotasi:
                continue
            if not anlatilacak_sayi_var_mi(aday):
                continue
            kararlar.append(aday)
            tip_sayaci[tip] = tip_sayaci.get(tip, 0) + 1
        if sum(tip_sayaci.values()) >= n_finans:
            break

    return kararlar


def olc(model_adi: str, n_stok: int = 15, n_finans: int = 24) -> dict:
    """Modeli koştur, karar tipi kırılımlı sonuç döndür."""
    ayar = Ayarlar(llm_model_adi=model_adi, llm_istem_bicimi="egitilmis")
    kararlar = _kararlari_topla(n_stok, n_finans)

    tipler: dict[str, TipSonucu] = {}
    ornekler: list[dict] = []
    t0 = time.time()

    with OllamaIstemcisi(ayar=ayar) as istemci:
        for aday in kararlar:
            gerekce = gerekce_uret(aday, istemci)
            tip = aday.tip.value
            s = tipler.setdefault(tip, TipSonucu())
            s.toplam += 1
            s.uzunluklar.append(len(gerekce.metin))
            if sizinti_var_mi(gerekce.metin):
                s.sizintili += 1
            if _TEKRAR_DESENI.search(gerekce.metin):
                s.tekrarli += 1
            if gerekce.guard_sonucu is GuardSonucu.GECTI:
                s.guard_gecti += 1
            elif gerekce.guard_sonucu is GuardSonucu.SABLONA_DUSTU:
                s.sablona_dustu += 1
            if len(ornekler) < 8:
                ornekler.append({"tip": tip, "metin": gerekce.metin[:220]})

    sure = time.time() - t0
    genel = TipSonucu()
    for s in tipler.values():
        genel.toplam += s.toplam
        genel.sizintili += s.sizintili
        genel.guard_gecti += s.guard_gecti
        genel.sablona_dustu += s.sablona_dustu
        genel.tekrarli += s.tekrarli
        genel.uzunluklar.extend(s.uzunluklar)

    return {
        "model": model_adi,
        "sure_sn": round(sure, 1),
        "karar_basina_sn": round(sure / max(1, genel.toplam), 1),
        "genel": _ozet(genel),
        "tip_kirilimi": {t: _ozet(s) for t, s in sorted(tipler.items())},
        "ornekler": ornekler,
    }


def _ozet(s: TipSonucu) -> dict:
    return {
        "toplam": s.toplam,
        "sizinti_orani": round(s.sizinti_orani, 3),
        "guard_gecti_orani": round(s.guard_orani, 3),
        "sablona_dusme_orani": round(s.sablon_orani, 3),
        "tekrarli": s.tekrarli,
        "ort_uzunluk": round(s.ort_uzunluk),
    }


def _yazdir(sonuc: dict) -> None:
    g = sonuc["genel"]
    print("=" * 74)
    print(f"MODEL: {sonuc['model']}   ({sonuc['karar_basina_sn']} sn/karar)")
    print("=" * 74)
    print(
        f"GENEL  n={g['toplam']:3d}  sizinti %{g['sizinti_orani'] * 100:5.1f}  "
        f"guard %{g['guard_gecti_orani'] * 100:5.1f}  "
        f"sablon %{g['sablona_dusme_orani'] * 100:5.1f}  "
        f"uzunluk {g['ort_uzunluk']}"
    )
    print("-" * 74)
    print(f"{'karar tipi':30s} {'n':>3s} {'sizinti':>8s} {'guard':>7s} {'sablon':>7s} {'uzun':>5s}")
    for tip, s in sonuc["tip_kirilimi"].items():
        print(
            f"{tip:30s} {s['toplam']:3d} {s['sizinti_orani'] * 100:7.1f}% "
            f"{s['guard_gecti_orani'] * 100:6.1f}% {s['sablona_dusme_orani'] * 100:6.1f}% "
            f"{s['ort_uzunluk']:5d}"
        )


def _karsilastir(yeni: dict, eski: dict) -> None:
    print()
    print("=" * 74)
    print(f"KARSILASTIRMA: {eski['model']}  ->  {yeni['model']}")
    print("=" * 74)
    y, e = yeni["genel"], eski["genel"]
    for ad, anahtar, iyi_yon in (
        ("istem sizintisi", "sizinti_orani", "dusuk"),
        ("guard gecti", "guard_gecti_orani", "yuksek"),
        ("sablona dustu", "sablona_dusme_orani", "dusuk"),
    ):
        fark = y[anahtar] - e[anahtar]
        iyilesti = fark < 0 if iyi_yon == "dusuk" else fark > 0
        isaret = "IYILESTI" if abs(fark) > 0.01 and iyilesti else (
            "KOTULESTI" if abs(fark) > 0.01 else "ayni"
        )
        print(
            f"  {ad:18s} %{e[anahtar] * 100:5.1f} -> %{y[anahtar] * 100:5.1f}  "
            f"({fark * 100:+5.1f} puan)  {isaret}"
        )

    # ⚠️ Hüküm ÜÇ metriğe birden bakıyor. İlk sürüm yalnızca sızıntıya
    # bakıyordu ve tur6 için "ONE GECTI" dedi — oysa sızıntı sıfırlanırken
    # şablona düşme %0'dan %28'e fırlamıştı. Modelin susmayı öğrenmesi
    # düzelmek değildir. Bugünün altıncı "tek metrik yalan söyler" vakası,
    # bu sefer ölçüm aracının kendisinde.
    print()
    sizinti_dusru = y["sizinti_orani"] < e["sizinti_orani"] - 0.05
    sizinti_artti = y["sizinti_orani"] > e["sizinti_orani"] + 0.05
    sablon_firladi = y["sablona_dusme_orani"] > e["sablona_dusme_orani"] + 0.10

    print("KARAR: ", end="")
    if sizinti_artti:
        print("GERI ALINMALI — istem sizintisi arttı.")
    elif sizinti_dusru and not sablon_firladi:
        print("ONE GECTI — sizinti dustu, sablona dusme artmadi.")
    elif sizinti_dusru and sablon_firladi:
        print("KISMI — sizinti dustu AMA sablona dusme firladi.")
        print("       Model bazi karar tiplerinde susmayi ogrenmis olabilir;")
        print("       asagidaki tip kiriliminda guard %0 olan tiplere bak.")
    else:
        print("BELIRSIZ — sizintida anlamli degisim yok, tip kirilimina bak.")

    kotu_tipler = [
        t for t, s in yeni["tip_kirilimi"].items() if s["sablona_dusme_orani"] > 0.5
    ]
    if kotu_tipler:
        print()
        print(f"⚠️ Yarisindan fazlasi sablona dusen tipler: {', '.join(kotu_tipler)}")


def _cli() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    a = argparse.ArgumentParser(description="Tur 6 gerekçe kalitesi ölçümü")
    a.add_argument("--model", default="codifya-router:tur6")
    a.add_argument("--karsilastir", default=None, help="ör. tur5 — o turun kaydıyla karşılaştır")
    a.add_argument("--n-stok", type=int, default=15)
    a.add_argument("--n-finans", type=int, default=24)
    args = a.parse_args()

    sonuc = olc(args.model, args.n_stok, args.n_finans)
    _yazdir(sonuc)

    etiket = args.model.replace(":", "-")
    yol = SONUC_DIZINI / f"tur6_olcum_{etiket}.json"
    yol.write_text(json.dumps(sonuc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nkaydedildi: {yol.name}")

    if args.karsilastir:
        eski_yol = SONUC_DIZINI / f"tur6_olcum_codifya-router-{args.karsilastir}.json"
        if eski_yol.exists():
            _karsilastir(sonuc, json.loads(eski_yol.read_text(encoding="utf-8")))
        else:
            print(f"\n⚠️ {eski_yol.name} yok — once o modeli olcun:")
            print(
                "   uv run python -m training.eval.tur6_olcum "
                f"--model codifya-router:{args.karsilastir}"
            )

    print("\nORNEK CIKTILAR")
    print("-" * 74)
    for o in sonuc["ornekler"][:5]:
        bayrak = "SIZINTI" if sizinti_var_mi(o["metin"]) else "temiz  "
        print(f"[{bayrak}] {o['tip']}")
        print(f"          {o['metin'][:150]}")


if __name__ == "__main__":
    _cli()
