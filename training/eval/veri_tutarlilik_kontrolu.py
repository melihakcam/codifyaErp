"""Eğitim verisi tutarlılık kontrolü — ⭐ HER EĞİTİM TURUNDAN ÖNCE KOŞTUR.

Sahip: Kişi B · Faz 5 (2. tur başarısızlığının kök neden analizinden doğdu)

    uv run python -m training.eval.veri_tutarlilik_kontrolu

## Neyi kontrol ediyor

Tek bir soru: **hedef metindeki her sayı, istemde modele veriliyor mu?**

Verilmiyorsa model o sayıyı *yoktan üretmeyi* öğrenir. Bu bir kalite
sorunu değil, doğrudan halüsinasyon eğitimidir — ve guard'ın var olma
sebebiyle çelişir.

## Bu kontrol neden var: 2. turun kök nedeni

Ekip bu hatayı **ürün adları** için B3.1'de doğru teşhis etmişti:

> "İsteme ad koymaz, hedefte ad varsa → model *yoktan ad uydurmayı*
>  öğrenir. **En kötü seçenek.**"

Adlar için düzeltildi. Ama **sayılar için aynı hata fark edilmedi**:

    veri_hazirla.py::ETIKETLER  ->  istemde YALNIZCA 5 ozellik alani
    hedef metin                 ->  izinli_sayilar()'in TAMAMINI kullanabilir
                                    (tetiklenen kural degerleri + aksiyon:
                                     ROP, emniyet stogu, iskonto orani,
                                     siparis miktari, tedarikci skoru...)

Ölçüldüğünde eğitim örneklerinin **%79,4'ü** istemde bulunmayan en az bir
sayı içeriyordu. En sık uydurtulan değer `15` (886 kez) —
`rules.py::onerilen_iskonto_orani = 0.15`, guard'a göre meşru ama modele
hiç gösterilmiyor.

Sonuç (`dokumantasyon/OLCUMLER.md`, Faz 5 kök neden bölümü): 2. tur LoRA
gerekçe tarafında taban modelin çok altında kaldı (guard kabulü %25,7 vs
%100). Taban model iyi çünkü onun istemi (`explain.py::sayi_etiketleri`)
kullanabileceği **her** sayıyı içeriyor.

⚠️ **Bu hata "daha çok eğitimle" düzelmez, kötüleşir** — daha fazla epoch
ya da daha büyük veri, uydurma davranışını daha da pekiştirir. Düzeltme
veri hazırlama tarafında: istem, hedefin kullandığı sayıların tamamını
içermeli.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.llm.guard import metni_maskele, sayilari_cikar

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VARSAYILAN_DOSYA = Path("data/colab_yukle/gerekce_train.jsonl")

# İstemdeki değer yuvarlanmış olabilir (91,5955 -> "91,60"). guard.py ile aynı
# mantık: mutlak küçük tolerans veya %1 bağıl fark.
MUTLAK_TOLERANS = 0.02
BAGIL_TOLERANS = 0.01

# Bu oranın üstü, veri setinin modele sistematik olarak uydurma öğrettiği
# anlamına gelir. Eşik değil sınır: %5 bile fazla, ama %0 pratikte zor.
KABUL_EDILEBILIR_ORAN = 0.05


@dataclass
class Sonuc:
    toplam: int = 0
    uydurmali: int = 0
    fazla_degerler: Counter[float] = field(default_factory=Counter)
    ornekler: list[tuple[str, list[float]]] = field(default_factory=list)

    @property
    def oran(self) -> float:
        return self.uydurmali / self.toplam if self.toplam else 0.0

    @property
    def gecti(self) -> bool:
        return self.oran <= KABUL_EDILEBILIR_ORAN


def _urun_adini_al(istem: str) -> str:
    """İstemdeki `urun: ...` satırı — maskeleme için.

    Ürün adları rakam içerebilir ("Alçıpan 12.5mm", "Delikli Tuğla 13.5x19x19");
    maskelenmezse bunlar sayı sanılır ve sahte pozitif üretirler.
    """
    for satir in istem.splitlines():
        if satir.startswith("urun: "):
            return satir[len("urun: ") :].strip()
    return ""


def _istemde_var_mi(sayi: float, istemdekiler: set[float]) -> bool:
    return any(
        abs(sayi - i) <= max(MUTLAK_TOLERANS, abs(i) * BAGIL_TOLERANS) for i in istemdekiler
    )


def istemde_olmayan_sayilar(istem: str, cevap: str) -> list[float]:
    """Hedef metinde olup istemde olmayan sayılar."""
    maske = [ad] if (ad := _urun_adini_al(istem)) else []
    istemdekiler = set(sayilari_cikar(metni_maskele(istem, maske)))
    cevaptakiler = set(sayilari_cikar(metni_maskele(cevap, maske)))
    return sorted(s for s in cevaptakiler if not _istemde_var_mi(s, istemdekiler))


def dosyayi_kontrol_et(yol: Path, sinir: int | None = None) -> Sonuc:
    sonuc = Sonuc()
    with yol.open(encoding="utf-8") as f:
        for satir in f:
            if sinir is not None and sonuc.toplam >= sinir:
                break
            if not satir.strip():
                continue
            k = json.loads(satir)
            fazlalar = istemde_olmayan_sayilar(k["istem"], k["cevap"])

            sonuc.toplam += 1
            if fazlalar:
                sonuc.uydurmali += 1
                sonuc.fazla_degerler.update(fazlalar)
                if len(sonuc.ornekler) < 5:
                    sonuc.ornekler.append((_urun_adini_al(k["istem"]), fazlalar))
    return sonuc


def raporla(sonuc: Sonuc) -> str:
    satirlar = [
        "=" * 66,
        "EGITIM VERISI TUTARLILIK KONTROLU",
        "=" * 66,
        f"  incelenen ornek                : {sonuc.toplam:,}",
        f"  istemde OLMAYAN sayi iceren    : {sonuc.uydurmali:,}  (%{sonuc.oran * 100:.1f})",
        f"  kabul edilebilir ust sinir     : %{KABUL_EDILEBILIR_ORAN * 100:.0f}",
        "",
    ]

    if sonuc.fazla_degerler:
        satirlar.append("  EN SIK UYDURTULAN DEGERLER:")
        for deger, adet in sonuc.fazla_degerler.most_common(8):
            satirlar.append(f"    {deger:>12,.2f}   x{adet}")
        satirlar.append("")
        satirlar.append("  ORNEKLER:")
        for urun, fazlalar in sonuc.ornekler:
            kisa = [round(x, 2) for x in fazlalar][:6]
            satirlar.append(f"    {urun[:34]:34s} -> {kisa}")
        satirlar.append("")

    if sonuc.gecti:
        satirlar.append("  ✅ GECTI — istem, hedefin kullandigi sayilari kapsiyor.")
    else:
        satirlar += [
            "  ❌ KALDI — bu veriyle egitim, modele SAYI UYDURMAYI ogretir.",
            "",
            "  Duzeltme veri hazirlamada (training/veri_hazirla.py::ETIKETLER):",
            "  istem, hedefin kullanabildigi TUM sayilari icermeli — yalnizca",
            "  5 ozellik alanini degil, tetiklenen kural degerlerini ve aksiyonu",
            "  da. Referans: app/llm/explain.py::sayi_etiketleri (taban kipin",
            "  istemi bunu zaten dogru yapiyor, guard kabulu %100).",
            "",
            "  ⚠️ Daha fazla epoch / daha buyuk veri bu hatayi KOTULESTIRIR.",
        ]
    satirlar.append("=" * 66)
    return "\n".join(satirlar)


def _cli() -> None:
    ayristirici = argparse.ArgumentParser(description="Egitim verisi tutarlilik kontrolu")
    ayristirici.add_argument("--dosya", type=Path, default=VARSAYILAN_DOSYA)
    ayristirici.add_argument(
        "--sinir", type=int, default=5000, help="Kac ornek incelensin (0 = hepsi)"
    )
    args = ayristirici.parse_args()

    if not args.dosya.exists():
        raise SystemExit(f"Dosya yok: {args.dosya}")

    sonuc = dosyayi_kontrol_et(args.dosya, sinir=args.sinir or None)
    print(raporla(sonuc))
    raise SystemExit(0 if sonuc.gecti else 1)


if __name__ == "__main__":
    _cli()
