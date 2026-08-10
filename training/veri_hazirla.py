"""Eğitim verisini Colab'a yüklenmeye hazır hâle getirir (Faz 3, Kişi B).

    uv run python -m training.veri_hazirla --kaynak <klasor> --hedef <klasor>

Ham JSONL'lerde `ozellikler`, `izinli_sayilar`, `tetiklenen_kurallar` gibi
alanlar var; eğitimde yalnızca istem + cevap kullanılıyor. Dönüştürmeyi yerelde
yapmak iki işi birden görüyor:

1. **Yüklenecek boyut küçülüyor** — 103 MB → 27 MB. Drive'a sürüklemek hızlanır.
2. **Colab'da dönüştürme adımı kalmıyor** — orada patlayacak bir şey azalır.

⚠️ `training/train_lora.ipynb` bu betiğin ürettiği biçimi bekler. Ham dosyaları
doğrudan Drive'a koyarsan defter `KeyError: 'istem'` verir.

Router dosyaları olduğu gibi kopyalanır: defter onları kendi içinde
biçimlendiriyor (`router_metni()`), çünkü router örneği çok daha kısa ve
dönüştürmenin kazancı yok.

`izinli_sayilar` **yalnızca val/test** dosyalarında korunuyor: B3.5 ölçümünde
guard'ı koşturmak için gerekli, eğitimde gereksiz.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from app.contracts import Alan, DecisionCandidate, KararTipi
from app.llm.explain import egitilmis_istem_govdesi

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ⚠️ ARTIK KULLANILMIYOR — 2026-08-06'da kaldırıldı, tarihsel kayıt için burada.
#
# Bu 5 alanlık sabit liste 2. turun kök nedeniydi: karar tipinden bağımsızdı ve
# hedef metnin kullandığı sayıların (iskonto oranı, sipariş miktarı, tedarikçi
# skoru, ROP...) çoğunu içermiyordu. Eğitim örneklerinin %79,4'ü modele
# "istemde olmayan bir sayı üret" diye öğretiyordu.
#
# Yerine `app/llm/explain.py::egitilmis_istem_govdesi` çağrılıyor — çalışma
# zamanının kullandığı **birebir aynı** fonksiyon. İki yerde elle senkron
# tutulan liste bir daha ayrışamaz.
_ESKI_ETIKETLER: tuple[tuple[str, str], ...] = (
    ("ort_gunluk_talep", "gunluk ortalama talep (adet)"),
    ("tedarik_suresi_gun", "tedarik suresi (gun)"),
    ("eldeki_stok", "eldeki stok (adet)"),
    ("son_hareket_gun_once", "son hareketten bu yana gecen gun"),
    ("birim_maliyet_tl", "birim maliyet (TL)"),
)

GEREKCE_DOSYALARI = {
    "gerekce_train.jsonl": False,  # olcum alanlari gerekmez
    "gerekce_val.jsonl": True,
    "gerekce_test.jsonl": True,
}

KOPYALANACAKLAR = (
    "router_train.jsonl",
    "router_val.jsonl",
    "router_test.jsonl",
    "golden_set_aday.jsonl",
)


def tr_sayi(deger: float) -> str:
    """1200.0 → '1.200' · 4.75 → '4,75' (Türkçe biçim).

    Model gördüğü biçimi kopyalar, guard da Türkçe biçim bekler.

    ⚠️ `app/llm/explain.py::_tr_sayi` ile aynı davranışı vermeli. İstem artık
    oradan üretildiği için bu fonksiyon yalnızca yardımcı/ölçüm amaçlı kaldı.
    """
    d = float(deger)
    if d.is_integer():
        return f"{int(d):,}".replace(",", ".")
    return f"{d:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")


def adaya_cevir(kayit: dict) -> DecisionCandidate:
    """Ham eğitim kaydını `DecisionCandidate`'e çevirir.

    Sözleşmenin gerektirdiği ama ham kayıtta bulunmayan alanlar (kimlik,
    zaman damgası) sentetik üretiliyor — istem kurulumunda kullanılmıyorlar.
    Kullanılan alanlar (`ozellikler`, `tetiklenen_kurallar`, `aksiyon`, `tip`)
    kayıtta zaten tam.

    Bu dönüşüm sayesinde eğitim verisi, çalışma zamanının **birebir aynı**
    istem kurucusundan (`egitilmis_istem_govdesi`) geçiyor.
    """
    # ⚠️ `alan` karar tipinden türetiliyor, sabit DEĞİL. Önceden `Alan.STOK`
    # yazılıydı; finans kaydı geldiğinde `egitilmis_istem_govdesi` yanlış
    # etiketi (`urun:`) seçerdi ve eğitim istemi çalışma zamanınkinden
    # ayrışırdı — bu dosyanın var olma sebebinin tam tersi.
    tip = KararTipi(kayit["karar_tipi"])
    return DecisionCandidate.model_validate(
        {
            "karar_id": uuid4(),
            "alan": Alan.FINANS if tip.alan == Alan.FINANS.value else Alan.STOK,
            "tip": kayit["karar_tipi"],
            "aksiyon": kayit.get("aksiyon", {}),
            "tahmini_tutar_tl": kayit.get("tahmini_tutar_tl", 0.0),
            "guven": kayit.get("guven", 0.0),
            "tetiklenen_kurallar": kayit.get("tetiklenen_kurallar", []),
            "ozellikler": kayit["ozellikler"],
            "model_surumleri": {},
        }
    )


def istem_kur(kayit: dict) -> str:
    """Eğitim istemi — çalışma zamanıyla tek kaynaktan.

    ⭐ 2. turun kök nedeninin düzeltmesi. Önceki sürüm kendi 5 alanlık listesini
    taşıyordu ve `explain.py`'dekiyle elle senkron tutuluyordu; ayrıştılar ve
    model, istemde olmayan sayıları uydurmayı öğrendi. Artık gövde doğrudan
    `egitilmis_istem_govdesi`'nden geliyor — ayrışma yapısal olarak imkânsız.
    """
    return egitilmis_istem_govdesi(adaya_cevir(kayit))


def gerekce_donustur(kaynak: Path, hedef: Path, *, olcum_icin: bool) -> int:
    """Ham gerekçe kaydını `{istem, cevap, karar_tipi}` biçimine çevirir.

    ⚠️ `karar_tipi` **her dosyada** var, eğitim dosyasında da. İlk sürümde
    yalnızca val/test'e konuyordu ("boyut küçültme") ve defterin 2. tur
    dengeleme kodu `dengeli_ornekle(..., 'karar_tipi', ...)` derken `KeyError`
    aldı. Kişi A geçici olarak istem metnindeki `karar: ...` satırından
    çıkarmak zorunda kaldı.

    Alan başına ~20 bayt; 40 bin satırda 800 KB. Dengeli örneklemenin
    çalışması için ödenecek bedel bu değil.
    """
    n = 0
    with kaynak.open(encoding="utf-8") as gir, hedef.open("w", encoding="utf-8") as cik:
        for satir in gir:
            k = json.loads(satir)
            o = k["ozellikler"]
            yeni = {
                "istem": istem_kur(k),
                "cevap": k["gerekce_metni"],
                "karar_tipi": k["karar_tipi"],
            }
            if olcum_icin:
                yeni["izinli_sayilar"] = k.get("izinli_sayilar", [])
                yeni["maske"] = [
                    o.get("sku_adi", ""),
                    o.get("sku_id", ""),
                    o.get("tedarikci_adi", ""),
                    o.get("tedarikci_id", ""),
                ]
            cik.write(json.dumps(yeni, ensure_ascii=False) + "\n")
            n += 1
    return n


def kopyala(kaynak: Path, hedef: Path) -> int:
    n = 0
    with kaynak.open(encoding="utf-8") as gir, hedef.open("w", encoding="utf-8") as cik:
        for satir in gir:
            cik.write(satir)
            n += 1
    return n


def mb(yol: Path) -> float:
    return yol.stat().st_size / 1024**2


def main() -> None:
    ayristirici = argparse.ArgumentParser(description="Eğitim verisini Colab'a hazırla")
    ayristirici.add_argument("--kaynak", required=True, help="Ham JSONL'lerin bulunduğu klasör")
    ayristirici.add_argument("--hedef", required=True, help="Çıktı klasörü (Drive'a yüklenecek)")
    args = ayristirici.parse_args()

    kaynak, hedef = Path(args.kaynak), Path(args.hedef)
    hedef.mkdir(parents=True, exist_ok=True)

    print(f"kaynak : {kaynak}")
    print(f"hedef  : {hedef}\n")
    print(f"  {'dosya':26s} {'satır':>7s} {'önce':>9s} {'sonra':>9s}")
    print("  " + "-" * 56)

    onceki = sonraki = 0.0
    eksik = []

    for ad, olcum in GEREKCE_DOSYALARI.items():
        gir = kaynak / ad
        if not gir.exists():
            eksik.append(ad)
            continue
        n = gerekce_donustur(gir, hedef / ad, olcum_icin=olcum)
        onceki += mb(gir)
        sonraki += mb(hedef / ad)
        print(f"  {ad:26s} {n:7d} {mb(gir):8.1f}M {mb(hedef / ad):8.1f}M")

    for ad in KOPYALANACAKLAR:
        gir = kaynak / ad
        if not gir.exists():
            eksik.append(ad)
            continue
        n = kopyala(gir, hedef / ad)
        onceki += mb(gir)
        sonraki += mb(hedef / ad)
        print(f"  {ad:26s} {n:7d} {mb(gir):8.1f}M {mb(hedef / ad):8.1f}M")

    print("  " + "-" * 56)
    print(f"  {'TOPLAM':26s} {'':7s} {onceki:8.1f}M {sonraki:8.1f}M")
    if onceki:
        print(f"\n  Yüklenecek boyut %{(1 - sonraki / onceki) * 100:.0f} küçüldü.")

    if eksik:
        print(f"\n  ⚠️ Bulunamayan dosyalar: {eksik}")

    ornek_yolu = hedef / "gerekce_train.jsonl"
    if ornek_yolu.exists():
        with ornek_yolu.open(encoding="utf-8") as f:
            ornek = json.loads(f.readline())
        print("\n" + "=" * 60)
        print("ÖRNEK KAYIT")
        print("=" * 60)
        print(ornek["istem"])
        print(ornek["cevap"])


if __name__ == "__main__":
    main()
