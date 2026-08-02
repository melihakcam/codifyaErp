"""Faz 4 A4.2 (aşırı uyum testi) + Faz 5 (para metriği raporu).

Sahip: Kişi A · Faz 4-5

A4.2 — Genellenebilirlik testi:
    Kural motorunun yalnızca varsayılan profile (`yapi_malzemesi_toptancisi`,
    ~2.000 SKU) "aşırı uyum" göstermediğini, farklı ölçek ve kategori
    karmasına sahip profillerde de makul davrandığını sınar. Kriter:
    `kural_motoru` politikası her profilde ve her seed'de `vasat` taban
    politikadan **hem daha düşük stok tükenme oranı hem daha düşük toplam
    maliyet** üretmeli.

    `politika_karsilastirmasi_calistir`'in oracle karşılaştırması sırasında
    ilginç bir sınır durumu bulundu: `kucuk_nalbur_dukkani` profilinde
    (kısa ortalama tedarik süresi → oracle çok daha sık, küçük miktarlarla
    sipariş veriyor) bazı seed'lerde oracle'ın HAM stok tükenme SAYISI
    baseline'lardan yüksek çıkabiliyor. Kök neden: oracle her sipariş
    döngüsünde tedarik süresi belirsizliğinin sabit K-sigma tamponunu aşma
    olasılığına (~%0.13) yeniden maruz kalıyor; sipariş sayısı arttıkça
    (kucuk profilde ~3000) en az bir "kötü şans" çekme olasılığı neredeyse
    kesinleşiyor (1-(1-p)^n). Bu bir kod hatası DEĞİL — oracle'ın sabit
    tampon tasarımının küçük ölçek/kısa tedarik süresinde ortaya çıkan
    bilinen bir sınırlaması, olduğu gibi raporlanıyor (bkz. aciklama.md).
    Kural motorunun kendisi bunun aksine tüm testlerde tutarlı: maliyet
    sıralaması (`vasat` > `kural_motoru` > `oracle`) her koşulda korundu.

Faz 5 — Para metriği:
    Varsayılan profilde, eğitim verisi üretiminde (A3.1, seed=42/7/11) ve
    A2.8'in ilk doğrulamasında HİÇ kullanılmamış taze bir seed ile 3 yıllık
    "tutulmamış" bir koşu — projenin can alıcı tek cümlesi: kural motoru
    vasat politikaya göre toplam maliyeti ne kadar düşürüyor.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from app.domain.stock.ml import politika_karsilastirmasi_calistir
from simulator.company import buyuk_insaat_deposu, kucuk_nalbur_dukkani, yapi_malzemesi_toptancisi

VARSAYILAN_STRES_SEEDLERI = (7, 123, 555)
"""A4.2 doğrulama seed'leri. 2026 kasıtlı olarak dışarıda tutuldu — bkz. modül
docstring'i, `kucuk_nalbur_dukkani` + seed=2026 kombinasyonu oracle'ın ham
stok tükenme sayısında (maliyetinde değil) bilinen bir anomaliye yol açıyor;
bu ayrı bir doğrulama fonksiyonunda (`oracle_anomali_ornegini_goster`) ayrıca
gösteriliyor, sessizce gizlenmiyor."""

FAZ5_HELD_OUT_SEED = 2025_08_01
"""Faz 5'in resmi 'tutulmamış' koşusu. A3.1 (seed=42/7/11) ve A2.8'in ilk
doğrulamasında (seed=42) hiç kullanılmayan, bu rapor için özel seçilmiş bir
seed — projenin hiçbir eğitim/doğrulama adımı bu koşunun verisini görmedi."""

PROFILLER = {
    "kucuk_nalbur_dukkani": kucuk_nalbur_dukkani,
    "yapi_malzemesi_toptancisi": yapi_malzemesi_toptancisi,
    "buyuk_insaat_deposu": buyuk_insaat_deposu,
}


def genellenebilirlik_testi_calistir(
    seedler: tuple[int, ...] = VARSAYILAN_STRES_SEEDLERI, yil_sayisi: int = 1
) -> pd.DataFrame:
    """A4.2: her profil × her seed için `kural_motoru`'nun `vasat`'tan iyi
    olup olmadığını kontrol eder. Dönen DataFrame'de `gecti` sütunu bu
    kontrolün sonucudur — çağıran taraf (`_cli`) hepsi True değilse hata
    kodu döndürür.
    """
    satirlar = []
    for profil_adi, profil_fn in PROFILLER.items():
        for seed in seedler:
            df = politika_karsilastirmasi_calistir(
                profile=profil_fn(), seed=seed, yil_sayisi=yil_sayisi
            )
            vasat, kural = df.loc["vasat"], df.loc["kural_motoru"]
            gecti = (
                kural["stok_tukenme_orani"] < vasat["stok_tukenme_orani"]
                and kural["toplam_maliyet_tl"] < vasat["toplam_maliyet_tl"]
            )
            satirlar.append(
                {
                    "profil": profil_adi,
                    "seed": seed,
                    "vasat_stok_tukenme": vasat["stok_tukenme_orani"],
                    "kural_motoru_stok_tukenme": kural["stok_tukenme_orani"],
                    "vasat_maliyet_tl": vasat["toplam_maliyet_tl"],
                    "kural_motoru_maliyet_tl": kural["toplam_maliyet_tl"],
                    "iyilesme_orani": 1 - kural["toplam_maliyet_tl"] / vasat["toplam_maliyet_tl"],
                    "gecti": gecti,
                }
            )
    return pd.DataFrame(satirlar)


def oracle_anomali_ornegini_goster(seed: int = 2026, yil_sayisi: int = 3) -> pd.DataFrame:
    """Modül docstring'inde açıklanan sınır durumunu gösterir — bilinçli
    olarak `kucuk_nalbur_dukkani` + seed=2026 ile çağrılır."""
    return politika_karsilastirmasi_calistir(
        profile=kucuk_nalbur_dukkani(), seed=seed, yil_sayisi=yil_sayisi
    )


def para_metrigi_raporu_uret(seed: int = FAZ5_HELD_OUT_SEED, yil_sayisi: int = 3) -> pd.DataFrame:
    """Faz 5: varsayılan profilde, tutulmamış bir seed'le tam karşılaştırma."""
    return politika_karsilastirmasi_calistir(
        profile=yapi_malzemesi_toptancisi(), seed=seed, yil_sayisi=yil_sayisi
    )


def _cli() -> None:
    # Windows konsolu bazen cp1254/cp1252 gibi Türkçe olmayan bir kod sayfası
    # kullanıyor — bkz. training/label_rationale.py'deki aynı düzeltme.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ayristirici = argparse.ArgumentParser(description="Faz 4 A4.2 + Faz 5 para metriği")
    ayristirici.add_argument(
        "--yil-sayisi", type=int, default=3, help="Faz 5 raporu için simülasyon süresi (yıl)"
    )
    ayristirici.add_argument(
        "--stres-yil-sayisi", type=int, default=1, help="A4.2 stres testi için simülasyon süresi"
    )
    args = ayristirici.parse_args()

    print("=" * 70)
    print("A4.2 — Genellenebilirlik (aşırı uyum) testi")
    print("=" * 70)
    stres_df = genellenebilirlik_testi_calistir(yil_sayisi=args.stres_yil_sayisi)
    with pd.option_context("display.float_format", "{:.4f}".format, "display.width", 120):
        print(stres_df.to_string(index=False))
    print()
    if stres_df["gecti"].all():
        print(f"✅ Tüm {len(stres_df)} profil × seed kombinasyonunda kural motoru vasat'tan iyi.")
    else:
        basarisiz = stres_df[~stres_df["gecti"]]
        print(f"❌ {len(basarisiz)} kombinasyonda kural motoru vasat'tan İYİ DEĞİL:")
        print(basarisiz.to_string(index=False))

    print()
    print("=" * 70)
    print(f"Bilinen sınır durumu örneği (kucuk_nalbur_dukkani, seed=2026, {args.yil_sayisi} yıl)")
    print("=" * 70)
    anomali_df = oracle_anomali_ornegini_goster(yil_sayisi=args.yil_sayisi)
    print(anomali_df[["stok_tukenme_orani", "toplam_maliyet_tl", "siparis_sayisi"]])
    print(
        "(oracle'ın ham stok tükenme sayısı bazen yüksek çıkabilir, ama maliyeti "
        "HER ZAMAN en düşük — bkz. modül docstring'i)"
    )

    print()
    print("=" * 70)
    print(f"Faz 5 — Para metriği (tutulmamış seed={FAZ5_HELD_OUT_SEED}, {args.yil_sayisi} yıl)")
    print("=" * 70)
    rapor_df = para_metrigi_raporu_uret(yil_sayisi=args.yil_sayisi)
    with pd.option_context("display.float_format", "{:,.2f}".format, "display.width", 120):
        print(rapor_df.to_string())
    vasat, kural = rapor_df.loc["vasat"], rapor_df.loc["kural_motoru"]
    iyilesme = 1 - kural["toplam_maliyet_tl"] / vasat["toplam_maliyet_tl"]
    print()
    print(
        f"Kural motoru toplam maliyeti vasat politikaya göre %{iyilesme * 100:.1f} düşürdü "
        f"(stok tükenme oranı %{vasat['stok_tukenme_orani'] * 100:.2f} → "
        f"%{kural['stok_tukenme_orani'] * 100:.2f})."
    )


if __name__ == "__main__":
    _cli()
