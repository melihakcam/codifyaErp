"""Tahmin ölçümü — kayan başlangıçlı geriye dönük sınama.

    uv run python -m app.forecast.olcum

⚠️ **Rastgele bölme YASAK.** Zaman serisinde satırları rastgele ayırmak,
geleceği eğitip geçmişi test etmek demektir. Model yarının değerini görmüş
olur ve hata olduğundan küçük çıkar. Golden set incelemesinde aynı sızıntı
sorusunu bir kez sorduk; burada tuzağa düşmek daha kolay çünkü sızıntı
dosya çakışması gibi görünür bir iz bırakmıyor.

Doğrusu **kayan başlangıç**: bir kesme tarihi seçilir, yalnızca o güne kadar
olan veriyle tahmin üretilir, sonraki `ufuk` gün gerçekleşenle karşılaştırılır.
Kesme tarihi ileri kaydırılıp tekrarlanır.

## Ölçüt neden MASE

MAE tek başına anlamsız: günde 2 adet satan kalemde MAE=1,5 felaket, günde
500 satanda mükemmel. MASE, hatayı **naif tabanın hatasına** böler:

    MASE < 1  ->  model naif tabandan iyi
    MASE = 1  ->  naif tabanla aynı
    MASE > 1  ->  model işe yaramıyor

⚠️ MASE > 1 çıkması bir **bulgu**, başarısızlık değil. O zaman doğru karar
karmaşık modeli atıp naif tabanı kullanmaktır — ve bunu söyleyebilmek için
tabanın ölçümde durması gerekiyor.

## Neden bu sayı gerçekten güvenilir

`app/adapters/geriye_donuk.py`'nin haklı olarak yazdığı gibi, geçmiş veride
bir *politikayı* ölçmek imkânsız: sistemin önerdiği sipariş o gün verilmedi,
sonucu gözlenemez. Tahminde bu sorun yok — gerçekleşen talep zaten kayıtlı.
Karşı-olgusal olmadığı için buradan çıkan sayı, sistemdeki ölçümlerin en
doğrudan yorumlanabilir olanı.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.forecast.aralikli import ARALIKLI_MODELLER
from app.forecast.contracts import VARSAYILAN_UFUK_GUN
from app.forecast.model import MODELLER
from app.forecast.taban import TABANLAR, naif_hata_olcegi

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Kaç farklı kesme tarihinde sınanacak. Tek bir kesme tarihi, o tarihin
# özel bir döneme (promosyon, sezon tepesi) denk gelmesi hâlinde yanıltır.
VARSAYILAN_KESME_SAYISI = 6

# Kesme tarihleri arasındaki mesafe. Ufuktan büyük olmalı ki test
# pencereleri örtüşmesin; örtüşen pencereler aynı günleri birden çok kez
# sayar ve iyi/kötü bir dönemin ağırlığını yapay olarak artırır.
KESME_ARALIGI_GUN = 28

# Bu kadar günden az geçmişi olan kalem ölçüme girmiyor. Mevsimsel naif
# 364 gün istiyor; onun altında tabanlar arası karşılaştırma adil olmaz.
ASGARI_GECMIS_GUN = 400


@dataclass
class KalemSonucu:
    kalem_id: str
    yontem: str
    mutlak_hatalar: list[float] = field(default_factory=list)
    olcek: float = 0.0
    # Katmanlama icin: kalemin egitim penceresindeki ortalama gunluk talebi.
    # ⚠️ EGITIM penceresinden, tum seriden degil -- test donemindeki talep
    # seviyesini bilmek, kalemi siniflandirirken gelecege bakmak olurdu.
    ort_talep: float = 0.0
    # ⚠️ MASE TEK BASINA YETMIYOR -- aralikli talepte yaniltiyor.
    #
    # MASE gun gun yakinligi olcer ve cogu gunu sifir olan bir seride "hep
    # sifir de" stratejisini odullendirir (medyan sifir). Olculdu:
    # mevsimsel_naif yavas katmanda MASE 0,50 ile birinci, ama ufuk
    # toplamini %20 EKSIK tahmin ediyor ve pencerelerin %90'inda "hic talep
    # yok" diyor. Uretim plani icin bu kullanilamaz -- "hic uretme" demek.
    #
    # Uretim plani `TalepTahmini.toplam()` kullaniyor. Dogru olcut o yuzden
    # ufuk toplamindaki yanlilik; asagidaki iki alan onu tasiyor.
    tahmin_toplami: float = 0.0
    gercek_toplam: float = 0.0
    sifir_pencere: int = 0
    pencere_sayisi: int = 0

    @property
    def yanlilik(self) -> float | None:
        """Ufuk toplamindaki yuzde sapma. Gercek 0 ise tanimsiz."""
        if not self.gercek_toplam:
            return None
        return (self.tahmin_toplami - self.gercek_toplam) / self.gercek_toplam * 100

    @property
    def sifir_orani(self) -> float:
        """Ufuk boyunca HIC talep tahmin etmedigi pencerelerin orani."""
        if not self.pencere_sayisi:
            return 0.0
        return self.sifir_pencere / self.pencere_sayisi

    @property
    def mae(self) -> float:
        return float(np.mean(self.mutlak_hatalar)) if self.mutlak_hatalar else 0.0

    @property
    def mase(self) -> float | None:
        """Ölçek 0 ise MASE tanımsız — o kalem ölçüm dışı.

        Ölçek 0, seride hiç değişim olmadığı anlamına gelir (hep aynı sayı
        ya da hep sıfır). Bölme tanımsız; 0'a bölmek yerine `None` dönüp
        raporda o kalemi saymamak doğru.
        """
        if not self.olcek:
            return None
        return self.mae / self.olcek


def talep_serilerini_yukle(yil_sayisi: int = 3, seed: int = 42) -> dict[str, pd.Series]:
    """Simülasyondan SKU başına günlük talep serisi.

    ⚠️ Simülasyon **tahmin edilebilir bir yapı** üretiyor (trend × sezon ×
    haftalık desen). Buradan çıkan sayı bu yüzden bir **üst sınır** olarak
    okunmalı: gerçek veride aynı sonucu beklemek yanlış olur. Gerçek ölçüm
    `app/adapters/csv_erp.py::hareketleri_oku` ile gelen hareket verisiyle
    yapılacak; bu fonksiyonun ikizi orada yazılır.
    """
    from simulator.run import simulasyon_calistir

    sonuc = simulasyon_calistir(seed=seed, yil_sayisi=yil_sayisi)
    talep = sonuc["talep"]
    seriler: dict[str, pd.Series] = {}
    for sku_id, grup in talep.groupby("sku_id"):
        s = grup.set_index("tarih")["talep_miktari"].sort_index()
        seriler[str(sku_id)] = s.astype(float)
    return seriler


def kesme_tarihleri(seri: pd.Series, ufuk: int, adet: int) -> list[int]:
    """Kayan başlangıç noktaları — serinin sonundan geriye doğru.

    Son kesme, ufkun tamamının gözlenebildiği en geç nokta. Daha ileri
    gitmek test penceresini eksik bırakır ve son günleri hiç ölçmez.
    """
    son = len(seri) - ufuk
    if son <= ASGARI_GECMIS_GUN:
        return []
    # ⚠️ Kesmeler serinin KUYRUGUNDAN degil, kullanilabilir araligin
    # TAMAMINA yayiliyor.
    #
    # Ilk surum son N pencereyi aliyordu ve bu olcumu bozuyordu: serinin son
    # doneminde talep dususe gectiginde HER yontem yukari yanli goruniyordu.
    # Croston'un yanliligi kuyruk ornegiyle +%94 cikti, seriye yayilinca +%2 --
    # yani sayi modelin degil ornekleme penceresinin ozelligiydi.
    #
    # Kuyruk ornegi bir de en yeni donemi asiri temsil ediyor; mevsimsel bir
    # seride bu, tek bir mevsime bakip yil boyu iddiada bulunmak demek.
    adim = max(KESME_ARALIGI_GUN, (son - ASGARI_GECMIS_GUN) // max(adet, 1))
    noktalar = list(range(ASGARI_GECMIS_GUN, son, adim))[:adet]
    return noktalar


def olc(
    seriler: dict[str, pd.Series],
    ufuk: int = VARSAYILAN_UFUK_GUN,
    kesme_sayisi: int = VARSAYILAN_KESME_SAYISI,
    kalem_siniri: int | None = None,
) -> dict[str, list[KalemSonucu]]:
    """Her yöntemi her kalemde, her kesme tarihinde sınar."""
    yontemler = {**TABANLAR, **MODELLER, **ARALIKLI_MODELLER}
    sonuclar: dict[str, list[KalemSonucu]] = defaultdict(list)

    kalemler = list(seriler.items())
    if kalem_siniri:
        kalemler = kalemler[:kalem_siniri]

    for kalem_id, seri in kalemler:
        degerler = seri.tolist()
        if len(degerler) < ASGARI_GECMIS_GUN + ufuk:
            continue
        noktalar = kesme_tarihleri(seri, ufuk, kesme_sayisi)
        if not noktalar:
            continue

        for ad, fonksiyon in yontemler.items():
            kayit = KalemSonucu(kalem_id=kalem_id, yontem=ad)
            olcekler = []
            for kesme in noktalar:
                # ⚠️ Eğitim penceresi KESME'de bitiyor. Bir gün bile ileri
                # almak sızıntıdır ve hatayı gerçekte olduğundan küçük
                # gösterir.
                egitim = degerler[:kesme]
                gercek = degerler[kesme : kesme + ufuk]
                if len(gercek) < ufuk:
                    continue

                baslangic = _tarihe_cevir(seri.index[kesme])
                tahmin = fonksiyon(egitim, kalem_id, baslangic, ufuk)
                kayit.mutlak_hatalar += [
                    abs(t - g) for t, g in zip(tahmin.gunluk, gercek, strict=True)
                ]
                kayit.tahmin_toplami += tahmin.toplam()
                kayit.gercek_toplam += float(sum(gercek))
                kayit.pencere_sayisi += 1
                if tahmin.toplam() < 0.01:
                    kayit.sifir_pencere += 1
                # Ölçek EĞİTİM penceresinden — test penceresinden değil.
                olcekler.append(naif_hata_olcegi(egitim))

            kayit.olcek = float(np.mean([o for o in olcekler if o])) if any(olcekler) else 0.0
            kayit.ort_talep = float(np.mean(degerler[: noktalar[0]])) if noktalar else 0.0
            if kayit.mutlak_hatalar:
                sonuclar[ad].append(kayit)

    return dict(sonuclar)


def _tarihe_cevir(deger: object) -> date:
    if isinstance(deger, date):
        return deger
    return pd.Timestamp(deger).date()  # type: ignore[arg-type]


# Talep hızı katmanları (adet/gün). Ölçümün toplamı bu ayrımı yapmadan
# okunamaz — sebebi `KATMAN_UYARISI`'nda.
KATMANLAR: tuple[tuple[str, float, float], ...] = (
    ("hizli  (>=2/gun)", 2.0, float("inf")),
    ("orta   (0,3-2)", 0.3, 2.0),
    ("yavas  (<0,3/gun)", 0.0, 0.3),
)

KATMAN_UYARISI = """
⚠️ TOPLAM MASE TEK BAŞINA OKUNAMAZ — ilk ölçümde bunu doğruladık.

Katalog aralıklı talep ağırlıklı: medyan günlük talep 0,07 (iki haftada bir
satış). İlk koşuda toplam sayı üç yöntemi de "naif tabandan iyi" gösterdi.
Katmanlara ayırınca tablo tersine döndü:

    katman             hareketli  mevsimsel  ussel
    hizli   (197)         0,98      0,93     0,84   <- model kazaniyor
    orta    (273)         0,98      0,94     1,06
    yavas  (1530)         0,77      0,52     1,49   <- model FELAKET

Üssel düzleştirme yalnızca hızlı kalemlerde işe yarıyor; kataloğun %76'sını
oluşturan yavaş kalemlerde naif tabandan **%49 kötü**. Klasik üssel
düzleştirme aralıklı talep için yanlış model ailesi (simülatörün kendisi de
o kalemler için ayrı bir "aralıklı talep" süreci kullanıyor).

Sonuç: **tek bir model seçilemez.** Kalem bazında seçim gerekiyor ve seçimin
ölçütü talep hızı. Bu ayrımı gizleyen bir rapor, üretim kararlarını
kataloğun dörtte üçünde bilerek kötü bir tahmine bağlardı.
"""


def katman_adi(ort_talep: float) -> str:
    for ad, alt, ust in KATMANLAR:
        if alt <= ort_talep < ust:
            return ad
    return KATMANLAR[-1][0]


def rapor(sonuclar: dict[str, list[KalemSonucu]], ufuk: int) -> dict[str, float]:
    """Yöntemleri yan yana basar ve özet sözlüğü döndürür."""
    print("=" * 68)
    print(f"TALEP TAHMİNİ ÖLÇÜMÜ  ·  ufuk {ufuk} gün")
    print("=" * 68)
    print("  Kayan başlangıçlı geriye dönük sınama. Eğitim penceresi kesme")
    print("  tarihinde bitiyor; rastgele bölme YOK (sızıntı olurdu).\n")

    ozet: dict[str, float] = {}
    print(f"  {'yöntem':<24}{'kalem':>7}{'MAE':>10}{'MASE':>9}")
    print("  " + "-" * 50)
    for ad, kayitlar in sorted(sonuclar.items()):
        maseler = [k.mase for k in kayitlar if k.mase is not None]
        mae = float(np.mean([k.mae for k in kayitlar]))
        mase = float(np.mean(maseler)) if maseler else float("nan")
        ozet[ad] = mase
        isaret = ""
        if maseler:
            isaret = "  ✅" if mase < 1 else "  ⚠️ naif tabandan kötü"
        print(f"  {ad:<24}{len(kayitlar):>7}{mae:>10.2f}{mase:>9.2f}{isaret}")

    # --- Katman kırılımı: toplamın gizlediği şey -----------------------------
    #
    # ⚠️ Bu bölüm rapordan ÇIKARILAMAZ. Yukarıdaki toplam satırı tek başına
    # yanıltıcı; sebebi `KATMAN_UYARISI`'nda ölçülmüş hâliyle yazılı.
    print("\n  TALEP HIZINA GÖRE (toplamın gizlediği)")
    print("  " + "-" * 62)
    basliklar = [ad for ad, _, _ in KATMANLAR]
    print(f"  {'yöntem':<24}" + "".join(f"{b.split()[0]:>13}" for b in basliklar))
    katman_ozet: dict[str, dict[str, float]] = {}
    for ad, kayitlar in sorted(sonuclar.items()):
        satir = f"  {ad:<24}"
        katman_ozet[ad] = {}
        for katman in basliklar:
            ilgili = [
                k.mase for k in kayitlar if k.mase is not None and katman_adi(k.ort_talep) == katman
            ]
            if ilgili:
                deger = float(np.mean(ilgili))
                katman_ozet[ad][katman] = deger
                satir += f"{deger:>13.2f}"
            else:
                satir += f"{'—':>13}"
        print(satir)

    # --- Üretim planı için asıl ölçüt: ufuk toplamındaki yanlılık ----------
    print("\n  ÜRETİM PLANI İÇİN: UFUK TOPLAMI YANLILIĞI ve SIFIR ORANI")
    print("  " + "-" * 62)
    print("  ⚠️ MASE gün gün yakınlığı ölçer ve aralıklı seride 'hep sıfır de'")
    print("     stratejisini ödüllendirir (medyan sıfır). Üretim planı ise")
    print("     `toplam()` kullanıyor — doğru ölçüt ufuk toplamındaki sapma.")
    print(f"\n  {'yöntem':<24}{'yanlılık':>12}{'sıfır%':>10}")
    for ad, kayitlar in sorted(sonuclar.items()):
        # ⚠️ Kalem başına yüzdeleri ortalamak yanlış: küçük kalemde tek
        # adetlik sapma %100 görünür ve ortalamayı ele geçirir. Toplamlar
        # üzerinden hesaplamak doğru ağırlığı veriyor.
        tt = sum(k.tahmin_toplami for k in kayitlar)
        gg = sum(k.gercek_toplam for k in kayitlar)
        if not gg:
            continue
        yanli = (tt - gg) / gg * 100
        sifir = float(np.mean([k.sifir_orani for k in kayitlar])) * 100
        uyari = "  ⚠️ çoğunlukla 'hiç üretme' diyor" if sifir > 70 else ""
        print(f"  {ad:<24}{yanli:>11.0f}%{sifir:>9.0f}%{uyari}")

    print(f"\n  {'katman':<24}{'en iyi yöntem':<26}{'MASE':>8}")
    print("  " + "-" * 60)
    for katman in basliklar:
        adaylar = {a: d[katman] for a, d in katman_ozet.items() if katman in d}
        if not adaylar:
            continue
        en_iyi = min(adaylar, key=lambda a: adaylar[a])
        uyari = "" if adaylar[en_iyi] < 1.0 else "  ⚠️ hiçbiri tabanı geçemedi"
        print(f"  {katman:<24}{en_iyi:<26}{adaylar[en_iyi]:>8.2f}{uyari}")

    # Tek bir yöntem her katmanda kazanıyor mu? Kazanmıyorsa kalem bazında
    # seçim şart demektir ve bunu rapor açıkça söylemeli.
    kazananlar = {
        min(
            {a: d[k] for a, d in katman_ozet.items() if k in d},
            key=lambda a: {a2: d2[k] for a2, d2 in katman_ozet.items() if k in d2}[a],
        )
        for k in basliklar
        if any(k in d for d in katman_ozet.values())
    }
    if len(kazananlar) > 1:
        print("\n  ⚠️ TEK BİR YÖNTEM HER KATMANDA KAZANMIYOR.")
        print(f"     Katmanlara göre kazananlar: {', '.join(sorted(kazananlar))}")
        print("     Yani kalem bazında yöntem seçimi gerekiyor; tek model seçmek")
        print("     kataloğun bir kısmını bilerek kötü tahmine bağlar.")

    print()
    if ozet:
        en_iyi = min(ozet, key=lambda a: ozet[a])
        print(f"  Toplamda en düşük MASE: {en_iyi} ({ozet[en_iyi]:.2f})")
        print("  ⚠️ Bu satır tek başına karar dayanağı DEĞİL — üstteki kırılıma bakın.")
        if ozet[en_iyi] >= 1.0:
            print("  ⚠️ HİÇBİR yöntem naif tabanı geçemedi.")
            print("     Bu bir bulgu: karmaşık modeli atıp tabanı kullanmak doğru olur.")
    print("=" * 68)
    return ozet


def _cli() -> None:
    ayristirici = argparse.ArgumentParser(description="Talep tahmini ölçümü")
    ayristirici.add_argument("--ufuk", type=int, default=VARSAYILAN_UFUK_GUN)
    ayristirici.add_argument("--kesme", type=int, default=VARSAYILAN_KESME_SAYISI)
    ayristirici.add_argument(
        "--kalem",
        type=int,
        default=None,
        help="Yalnızca ilk N kalemi ölç (hızlı deneme için)",
    )
    args = ayristirici.parse_args()

    print("simülasyon koşuluyor...")
    seriler = talep_serilerini_yukle()
    print(f"{len(seriler)} kalem, {len(next(iter(seriler.values())))} günlük seri\n")

    sonuclar = olc(seriler, ufuk=args.ufuk, kesme_sayisi=args.kesme, kalem_siniri=args.kalem)
    rapor(sonuclar, args.ufuk)


if __name__ == "__main__":
    _cli()


__all__ = ["ASGARI_GECMIS_GUN", "KalemSonucu", "olc", "rapor", "talep_serilerini_yukle"]
