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
    # mevsimsel_naif yavas katmanda MASE 1,08 ile birinci, ama pencerelerin
    # %68'inde "hic talep yok" diyor (croston %28). Uretim plani icin bu
    # kullanilamaz -- pencerelerin ucte ikisinde "hic uretme" demek.
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

    # --- Ufuk toplami: uretim emri kuralinin GERCEKTEN okudugu sayi ---------
    #
    # ⚠️ Gunluk MASE ile ayni sey DEGIL ve aralikli seride ikisi ters
    # yonde ilerleyebilir; sebebi `TOPLAM_UYARISI`'nda.
    toplam_hatalar: list[float] = field(default_factory=list)
    gercek_toplamlar: list[float] = field(default_factory=list)
    bant_tuttu: list[bool] = field(default_factory=list)

    @property
    def mae(self) -> float:
        return float(np.mean(self.mutlak_hatalar)) if self.mutlak_hatalar else 0.0

    @property
    def toplam_bagil_hata(self) -> float | None:
        """Ufuk toplamındaki ortalama mutlak hata / ortalama gerçek toplam.

        Gerçek toplam 0 ise tanımsız: o kalem test penceresinde hiç satmamış,
        "yüzde kaç saptı" sorusunun cevabı yok.
        """
        gercek = float(np.mean(self.gercek_toplamlar)) if self.gercek_toplamlar else 0.0
        if not gercek or not self.toplam_hatalar:
            return None
        return float(np.mean(self.toplam_hatalar)) / gercek

    @property
    def bant_kapsama(self) -> float | None:
        """Gerçek ufuk toplamının bandın içinde kalma oranı."""
        if not self.bant_tuttu:
            return None
        return float(np.mean(self.bant_tuttu))

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
                # Ufuk toplamı ayrıca kaydediliyor: üretim emri kuralı
                # `toplam()` ve `toplam_bandi()` okuyor, gün gün tahmine
                # bakmıyor. Ölçüm neyi kullanıyorsak onu ölçmeli.
                #
                # ⚠️ İKİ AYRI SORU, İKİ AYRI SAYI — birbirinin yerine geçmez:
                #   yanlilik  : sapma hangi YÖNDE (fazla mı üretiriz, eksik mi)
                #   bagil hata: sapma ne KADAR (yön gözetmeden)
                # Yansız ama her pencerede %80 sapan bir yöntem yanlılıkta
                # mükemmel görünür; hatalar birbirini götürür. Üretim planı
                # ikisini de bilmek zorunda.
                gercek_toplam = float(sum(gercek))
                alt, ust = tahmin.toplam_bandi()
                kayit.tahmin_toplami += tahmin.toplam()
                kayit.gercek_toplam += gercek_toplam
                kayit.pencere_sayisi += 1
                if tahmin.toplam() < 0.01:
                    kayit.sifir_pencere += 1
                kayit.toplam_hatalar.append(abs(tahmin.toplam() - gercek_toplam))
                kayit.gercek_toplamlar.append(gercek_toplam)
                kayit.bant_tuttu.append(alt <= gercek_toplam <= ust)
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
⚠️ TOPLAM MASE TEK BAŞINA OKUNAMAZ.

Katalog aralıklı talep ağırlıklı: kalemlerin %76'sı (1525/2000) günde 0,3'ten
az satıyor. Toplam satır bu kütlenin ortalamasıdır; hızlı kalemlerdeki
davranışı tamamen gizler. Katman kırılımı (B10.2, 2026-08-11 koşusu):

    katman              kalem   hareketli  mevsimsel  croston   sba   ussel
    hizli  (>=2/gun)      195      1,04       0,99      1,05    1,04   0,89
    orta   (0,3-2)        280      0,93       1,01      0,96    0,94   1,01
    yavas  (<0,3/gun)    1525      1,12       1,08      1,12    1,08   1,55

Üssel düzleştirme yalnızca hızlı kalemlerde tabanı geçiyor; yavaş kalemlerde
naif tabandan %55 kötü. Klasik üssel düzleştirme aralıklı talep için yanlış
model ailesi (simülatörün kendisi de o kalemler için ayrı bir "aralıklı
talep" süreci kullanıyor) — `aralikli.py` bu yüzden yazıldı.

⚠️ **Daha önce yazıya geçmiş iki tablo da bu kodla yeniden üretilemedi**
(Adım 1-2'nin 0,52'si ve B10.2 ilk turunun 0,50 / −%20 / %90 satırı). İkisi
de ilgili commit'e dönülüp koşularak doğrulandı; sayılar buradakilerle bit
bit aynı çıktı. Eski tablolar kaynak olarak kullanılmamalı.

Sonuç: **tek bir model seçilemez.** Kalem bazında seçim gerekiyor ve seçimin
ölçütü talep hızı. Bu ayrımı gizleyen bir rapor, üretim kararlarını
kataloğun dörtte üçünde bilerek kötü bir tahmine bağlardı.
"""


TOPLAM_UYARISI = """
⚠️ GÜNLÜK MASE, ARALIKLI TALEPTE YANLIŞ SORUYU ÖLÇÜYOR.

Çoğu günü sıfır olan bir seride gün gün mutlak hatayı en küçük yapan tahmin
**sıfırdır**. Kalem iki haftada bir 5 adet satıyorsa "her gün 0" tahmini 13
günde tam isabet eder, bir günde 5 sapar; "her gün 0,36" tahmini ise HER gün
sapar. Günlük MASE birinciyi ödüllendirir — ama üretim emri "her gün sıfır
üret" diyemez.

Üretim emri kuralı `toplam()` ve `toplam_bandi()` okuyor: "önümüzdeki 14 günde
ne kadar satılacak, en kötü senaryoda ne kadar". Sıfır tahmini o soruda
%100 sapar. Bu yüzden aşağıdaki ikinci tablo var; aralıklı kalemlerde karar
dayanağı **odur**, günlük MASE değil.

Bant kapsama oranı da burada: bandın işi belirsizliği taşımak. %90 hedefle
kurulmuş bir bant %50 tutuyorsa emniyet payı sistematik olarak az seçilir.

Ölçülen (2026-08-11, ufuk 14 gün):

    yontem              bagil hata(yavas)  yanlilik  sifir%   bant
    sba                        1,54           -7%     28%      93%
    croston                    1,59            0%     28%      93%
    hareketli_ortalama         1,59           -1%     60%      92%
    mevsimsel_naif             1,61           +1%     68%      82%
    ussel_duzlestirme          2,29           +7%     34%      91%

MASE tablosunda mevsimsel naif yavaş katmanda öndeyken, pencerelerin
%68'inde "hiç talep yok" diyor — üretimi sistematik olarak durdurur.
Üretim emri kuralı bu yüzden Croston kullanıyor: yansız (%0) ve sıfır
oranı %28. SBA'nın bağıl hatası kıl payı iyi ama −%7 yanlı; düzeltecek bir
yanlılık bulamayıp aşağı kaydırıyor.
"""


def katman_adi(ort_talep: float) -> str:
    for ad, alt, ust in KATMANLAR:
        if alt <= ort_talep < ust:
            return ad
    return KATMANLAR[-1][0]


def _toplam_raporu(sonuclar: dict[str, list[KalemSonucu]], basliklar: list[str]) -> None:
    """Ufuk toplamı hatası ve bant kapsaması — katman kırılımlı.

    ⚠️ Bu bölüm rapordan ÇIKARILAMAZ. Günlük MASE tablosu aralıklı kalemlerde
    yanlış soruyu ölçüyor; sebebi `TOPLAM_UYARISI`'nda.
    """
    print("\n  UFUK TOPLAMI — bağıl hata (üretim emrinin okuduğu sayı)")
    print("  " + "-" * 62)
    print(f"  {'yöntem':<24}" + "".join(f"{b.split()[0]:>13}" for b in basliklar))
    for ad, kayitlar in sorted(sonuclar.items()):
        satir = f"  {ad:<24}"
        for katman in basliklar:
            ilgili = [
                k.toplam_bagil_hata
                for k in kayitlar
                if k.toplam_bagil_hata is not None and katman_adi(k.ort_talep) == katman
            ]
            satir += f"{float(np.mean(ilgili)):>13.2f}" if ilgili else f"{'—':>13}"
        print(satir)

    print("\n  BANT KAPSAMA — gerçek toplam bandın içinde kalma oranı")
    print("  " + "-" * 62)
    print(f"  {'yöntem':<24}" + "".join(f"{b.split()[0]:>13}" for b in basliklar))
    for ad, kayitlar in sorted(sonuclar.items()):
        satir = f"  {ad:<24}"
        for katman in basliklar:
            ilgili = [
                k.bant_kapsama
                for k in kayitlar
                if k.bant_kapsama is not None and katman_adi(k.ort_talep) == katman
            ]
            satir += f"{float(np.mean(ilgili)):>12.0%}" + " " if ilgili else f"{'—':>13}"
        print(satir)


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

    # Katman başına kalem sayısı: hangi katmanın kataloğu taşıdığını
    # göstermeden "şu katmanda şu yöntem iyi" cümlesi eksik kalır.
    ornek = next(iter(sonuclar.values()), [])
    katman_adedi = {k: sum(1 for r in ornek if katman_adi(r.ort_talep) == k) for k in basliklar}

    print(f"\n  {'katman':<24}{'kalem':>7}  {'en iyi yöntem':<24}{'MASE':>8}")
    print("  " + "-" * 66)
    for katman in basliklar:
        adaylar = {a: d[katman] for a, d in katman_ozet.items() if katman in d}
        if not adaylar:
            continue
        en_iyi = min(adaylar, key=lambda a: adaylar[a])
        uyari = "" if adaylar[en_iyi] < 1.0 else "  ⚠️ hiçbiri tabanı geçemedi"
        print(
            f"  {katman:<24}{katman_adedi[katman]:>7}  {en_iyi:<24}{adaylar[en_iyi]:>8.2f}{uyari}"
        )

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

    _toplam_raporu(sonuclar, basliklar)

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
