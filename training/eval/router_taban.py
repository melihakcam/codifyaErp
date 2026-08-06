"""Router taban çizgisi ölçümü (Faz 2 B2.3).

Sahip: Kişi B

    uv run python -m training.eval.router_taban

⚠️ Bu script'in ürettiği sayı **eğitimin işe yarayıp yaramadığının tek
karşılaştırma noktası.** Faz 3'te LoRA eğitildikten sonra aynı script aynı
soru setiyle yeniden koşturulacak (B3.5) ve iki sayı yan yana konacak.

Ölçüm yapılmadan eğitime geçilirse "eğitim işe yaradı mı" sorusunun cevabı
kalıcı olarak kaybolur — sonradan üretilemez, çünkü eğitim öncesi model
durumu geri getirilemez.

Soru seti `router_taban_sorulari.jsonl`'de ve **elle** yazıldı. Kişi A'nın
otomatik ürettiği eğitim verisinden bilinçli olarak ayrı: aynı şablonlardan
türeyen bir test seti, modelin şablonu ezberlemesini "başarı" diye ölçerdi.

Dört koruma var, dördü de eğitim verisindeki bilinen sorunlara karşı:

1. **Parametre biçimi esnek.** Eğitim verisinde `sku_adi` parametresi ürün
   ADINI değil KODUNU taşıyor (`"S-01971"`). Model eğitimden sonra kod
   üretmeye başlarsa katı bir karşılaştırma doğru cevabı yanlış sayardı ve
   öncesi/sonrası kıyaslaması geçersiz olurdu. Beklenen değer liste olarak
   verilebiliyor (herhangi biri kabul).

2. **Parametre halüsinasyon kontrolü.** Model parametreyi ancak soruda geçen
   bir şeyden çıkarabilir. Soruda hiç geçmeyen bir değer üretiyorsa bu
   uydurmadır — ayrıca sayılıyor.

3. **Çöküş dedektörü.** Eğitim verisi 3808 kat dengesiz
   (`siparis_onerisi_sorgula` %95,6). Bu veriyle eğitilen model "her şeye aynı
   aracı de" davranışına çökebilir. Dengeli bir test setinde tek araca aşırı
   yığılma açıkça uyarı basıyor — "doğruluk düştü" ile "model çöktü" çok
   farklı sorunlar, karıştırılmamalı.

4. **Çekim gücü.** Çöküş dedektörü kaba bir soru sorar ve ancak felaket
   seviyesinde ateşlenir. Daha ince bir bozulma var: bir sınıfın **çöp
   kutusu** haline gelmesi — hiçbir sınıfa güçlü uymayan soruları kapması.
   Rapor her araç için "kaç kez beklendi / kaç kez seçildi" basıyor. Genel
   doğruluk bunu göstermez: bir sınıf kazanıp diğeri kaybettiğinde toplam
   sabit kalabilir. 2. turda tam bu oldu ve fark edilmeden durdu.

Sonuçlar etikete göre ayrı dosyalara yazılıyor (`sonuc_yolu`); donmuş taban
çizgi `router_taban_sonuc.json`'da. `--rapor <dosya>` ile kayıtlı bir sonuç
**modeli hiç çalıştırmadan** bugünkü puanlama mantığıyla yeniden raporlanır.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Ayarlar, ayarlar
from app.llm.client import LLMErisilemiyor, OllamaIstemcisi
from app.llm.router import soruyu_yonlendir
from app.llm.schemas import SemaUyumsuz

# Windows konsolu varsayilan olarak cp1254 kullaniyor ve Turkce karakterlerde
# UnicodeEncodeError firlatiyor. Ayni sorunu Kisi A da yasadi (A3.4).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SORU_DOSYASI = Path(__file__).with_name("router_taban_sorulari.jsonl")

# ⚠️ EK SET — `SORU_DOSYASI`'na KARIŞTIRILMAZ.
#
# Taban çizgi (%70,0 araç / %66,7 tam) o 30 soruyla ölçüldü. Sete tek bir soru
# eklemek bile karşılaştırmayı geçersiz kılar; o dosya **donmuş** sayılmalı.
#
# Ama 30 soruluk set iki aracı ölçemiyor:
#
#     genel_stok_durumu_sorgula   2 soru   tek hata = %50 oynama
#     gecelik_ozet_sorgula        3 soru   tek hata = %33 oynama
#
# Bu set projenin `threshold`'a geçiş kapısı olduğu için bu kabul edilemez.
# Çözüm: ek soruları ayrı dosyada tutmak ve **ayrı raporlamak**. Taban
# karşılaştırması bozulmadan araç bazında çözünürlük artıyor.
#
# Sorular elle yazıldı (üreticiden değil) ve hiçbiri taban setle, eğitim,
# doğrulama ya da test verisiyle çakışmıyor — sızıntı yok.
EK_SORU_DOSYASI = Path(__file__).with_name("router_ek_sorular.jsonl")
SONUC_DOSYASI = Path(__file__).with_name("router_taban_sonuc.json")

# Dengeli bir test setinde 7 araç varsa tek aracın payı ~%14 olmalı. Bu eşiğin
# üstü, modelin ayrım yapmayı bırakıp tek cevaba yığıldığına işaret eder.
COKUS_ESIGI = 0.40

# Eşik araç sayısına göre yukarı kayıyor (bkz. `cokus_esigi`), ama sınırsız
# değil: tavan olmazsa az araçlı setlerde eşik %100'ü aşar ve dedektör hiçbir
# zaman ateşlenemez hale gelir. Bu tavanın üstünde bir yığılma her sette
# çöküştür — model artık ayrım yapmıyordur.
COKUS_TAVANI = 0.90

# ⚠️ Olcum TEKRARLANABILIR olmali. Varsayilan sicaklikla (0.2) ayni set iki
# kez kosturuldugunda %70 ve %76,7 cikti — 7 puanlik gurultu. Taban cizgi ile
# LoRA sonrasi farki bu gurultuden ayirt edilemezdi. Sicaklik 0 + sabit tohum
# ile model acgozlu (greedy) uretim yapiyor. Uretimde kullanilmiyor; orada
# cesitlilik zararsiz.
#
# ⚠️ DUZELTME: burada eskiden "ayni girdiye ayni cevabi veriyor" yaziyordu.
# YANLIS. Sicaklik 0 gurultunun buyuk kismini aliyor ama HEPSINI degil: hicbir
# kod degismeden, ayni model digest'iyle taban cizgi 20/30 ile 21/30 arasinda
# oynadi. Belirleyici olan modelin ISINMA DURUMU — ayrinti icin bkz.
# `modeli_bellekten_at`. Kalan gurultu `olc()` icinde soguk baslangicla
# kapatiliyor.
OLCUM_SICAKLIGI = 0.0
OLCUM_TOHUMU = 42


@dataclass
class Kayit:
    soru: str
    stil: str
    beklenen_arac: str
    # Değer bir liste olabilir: kabul edilen biçimlerin herhangi biri yeter
    # (ör. ürün adı VEYA SKU kodu).
    beklenen_parametreler: dict[str, list[str]] = field(default_factory=dict)
    secilen_arac: str | None = None
    secilen_parametreler: dict[str, str] | None = None
    hata: str | None = None
    uretim_ms: int = 0
    deneme: int = 0

    @property
    def arac_dogru(self) -> bool:
        return self.secilen_arac == self.beklenen_arac

    @property
    def parametre_dogru(self) -> bool:
        """Beklenen her parametre için kabul edilen biçimlerden biri gelmiş mi.

        Karşılaştırma büyük/küçük harf ve boşluk duyarsız: modelin "kirmizi
        tugla" yazması ile "Kırmızı Tuğla" yazması arasındaki fark bu ölçümün
        konusu değil.
        """
        secilen = {k: v.strip().casefold() for k, v in (self.secilen_parametreler or {}).items()}

        if set(secilen) != set(self.beklenen_parametreler):
            return False

        return all(
            secilen[ad] in {d.strip().casefold() for d in kabul_edilenler}
            for ad, kabul_edilenler in self.beklenen_parametreler.items()
        )

    @property
    def tam_dogru(self) -> bool:
        return self.arac_dogru and self.parametre_dogru

    @property
    def uydurma_parametre(self) -> list[str]:
        """Soruda hiç geçmeyen parametre değerleri.

        Model parametreyi ancak sorudan çıkarabilir; soruda olmayan bir değer
        üretmek uydurmadır. Araç doğru olsa bile bu bir kalite sorunu.
        """
        soru = self.soru.casefold()
        return [
            f"{ad}={deger}"
            for ad, deger in (self.secilen_parametreler or {}).items()
            if deger.strip() and deger.strip().casefold() not in soru
        ]


def kayitlari_yukle(yol: Path = SORU_DOSYASI) -> list[Kayit]:
    kayitlar = []
    for satir in yol.read_text(encoding="utf-8").splitlines():
        if not satir.strip():
            continue
        ham = json.loads(satir)
        # Tek değer de liste de yazılabilsin.
        beklenen = {
            ad: (deger if isinstance(deger, list) else [deger])
            for ad, deger in ham.get("parametreler", {}).items()
        }
        kayitlar.append(
            Kayit(
                soru=ham["soru"],
                stil=ham.get("stil", "?"),
                beklenen_arac=ham["arac"],
                beklenen_parametreler=beklenen,
            )
        )
    return kayitlar


def modeli_bellekten_at(istemci: OllamaIstemcisi) -> bool:
    """Ölçümden önce modeli Ollama'nın belleğinden atar (soğuk başlangıç).

    ⚠️ **Sıcaklık 0 + sabit tohum, tekrarlanabilirlik için YETMİYOR.**

    Böyle olduğu sanılıyordu ve modül docstring'i de bunu söylüyordu. Ölçüldü,
    doğru değil: hiçbir kod değişmeden, aynı model (aynı digest), aynı soru
    setiyle taban çizgi **20/30 ile 21/30 arasında oynadı**.

        model bellekten atilarak, 3 kez  ->  arac 21/30 · tam 20/30  (hep ayni)
        isinmis modelle,          2 kez  ->  arac 21/30 · tam 21/30  (hep ayni)

    Yani sonuç kendi içinde tutarlı ama **modelin ısınma durumuna bağlı**.
    Oynayan soru: *"Bizi kim geciktiriyor?"* — ısınmış modelde parametresiz
    (doğru), soğukta `tedarikci_id="Bizi Kim Geciktiriyor"` uyduruyor. Sınıra
    yakın bir kararın iki yana düşmesi.

    Sebebi sıcaklık değil: llama.cpp/Ollama'da yığınlama ve KV önbellek
    durumu logit'leri son basamakta oynatabiliyor; başa baş giden iki seçenek
    yer değiştiriyor.

    Neden önemli: 1 soru = 3,3 puan. 3. tur %73,3 verirse bu "eğitim işe
    yaradı" mı yoksa ısınma farkı mı — ayırt edilemezdi.

    Çözüm ısınmayı beklemek değil, **her ölçümü aynı yerden başlatmak**.
    `keep_alive=0` modeli düşürüyor; sonraki istek onu sıfırdan yüklüyor.

    ⚠️ Bu, taban çizgiyi resmî değere (%70,0 araç / %66,7 tam) geri getirdi —
    o değer de soğuk başlangıçla ölçülmüştü.
    """
    try:
        cevap = istemci._istemci.post(
            "/api/generate",
            json={"model": istemci.ayar.llm_model_adi, "keep_alive": 0},
            timeout=30.0,
        )
        return cevap.status_code == 200
    except httpx.HTTPError:
        # Ölçümü buna bağlamak yanlış olur: model düşürülemezse ölçüm yine
        # yapılır, yalnızca soğuk başlangıç garantisi kalkar.
        return False


def olc(kayitlar: list[Kayit], *, ayrinti: bool = True, ayar: Ayarlar | None = None) -> list[Kayit]:
    """Soruları modele sorar. `ayar` verilmezse `.env`'deki model kullanılır.

    ⚠️ **Eğitim sonrası ölçüm bu fonksiyonla yapılmalı, ayrı bir betikle
    değil.** B3.5'te ilk denemede ölçüm Colab'da ham `generate()` ile
    yapılmıştı; taban çizgi ise Ollama'nın JSON şema zorlamasıyla ölçülmüştü.
    Sonuç karşılaştırılamaz çıktı — 30 sorunun 8'i "şema hatası" sayıldı ama
    bunların bir kısmı modelin değil, kurulumun farkıydı.

    Aynı betiği farklı bir modele yöneltmek, karşılaştırmayı gerçekten adil
    yapan tek yol: aynı sorular, aynı puanlama, aynı şema kısıtı, aynı
    sıcaklık ve tohum. Tek değişen model.
    """
    with OllamaIstemcisi(ayar) as istemci:
        modeli_bellekten_at(istemci)
        for i, k in enumerate(kayitlar, 1):
            try:
                sonuc = soruyu_yonlendir(
                    istemci, k.soru, sicaklik=OLCUM_SICAKLIGI, tohum=OLCUM_TOHUMU
                )
                k.secilen_arac = sonuc.cagri.arac.value
                k.secilen_parametreler = dict(sonuc.cagri.parametreler)
                k.uretim_ms = sonuc.uretim_ms
                k.deneme = sonuc.deneme_sayisi
            except SemaUyumsuz as hata:
                k.hata = f"sema uyumsuz ({hata.denemeler} deneme)"
            except LLMErisilemiyor as hata:
                k.hata = f"llm erisilemiyor: {hata}"

            if ayrinti:
                if k.hata:
                    isaret = "HATA"
                elif k.tam_dogru:
                    isaret = "TAM "
                elif k.arac_dogru:
                    isaret = "ARAC"
                else:
                    isaret = "  X "
                print(
                    f"{i:>3} [{isaret}] {k.stil:<8} {k.soru[:44]:<46} -> {k.secilen_arac or k.hata}"
                )
    return kayitlar


def cekim_gucu(kayitlar: list[Kayit]) -> dict[str, tuple[int, int]]:
    """Her araç için (kaç kez beklendi, kaç kez seçildi).

    ⭐ Çöküş dedektörü "model tek araca yığıldı mı" diye bakar — kaba bir
    sorudur ve ancak felaket seviyesinde ateşlenir. Bu ise daha ince bir
    bozulmayı görür: bir sınıfın **çöp kutusu** haline gelmesi.

    Çöp kutusu sınıf, hiçbir sınıfa güçlü şekilde uymayan soruları kapan
    sınıftır. Beklendiğinden fazla seçilir. Doğruluğu iyi bile görünebilir
    (kendi sorularını doğru bilir) ama **başka araçların** sorularını çalar.

    2. turda tam bu oldu ve `router_lora_tur2_sonuc.json`'da aylarca
    görülmeden durdu:

        siparis_onerisi        5 beklendi / 6 seçildi  ->  5 / 3   düştü
        genel_stok_durumu      2 beklendi / 3 seçildi  ->  2 / 4   ARTTI
        onay_kuyrugu           5 beklendi / 5 seçildi  ->  5 / 7   ARTTI

    2. turun gerçek araca giden dört hatasının dördü de o iki sınıfa aktı.
    Ortak özellikleri az örnek DEĞİL — `dengeli_kota` kotaları eşitliyor —
    az **özgünlük**: 26 cümle 11 kez tekrarlanınca sınıfın karar sınırı
    bulanıklaşıyor (ayrıntı: `dokumantasyon/OLCUMLER.md`).

    Genel doğruluk bunu göstermez: bir sınıf kazanıp diğeri kaybettiğinde
    toplam sabit kalabilir.
    """
    beklenen = Counter(k.beklenen_arac for k in kayitlar)
    secilen = Counter(k.secilen_arac for k in kayitlar if k.secilen_arac)
    return {a: (beklenen[a], secilen[a]) for a in sorted(set(beklenen) | set(secilen))}


def cokus_esigi(kayitlar: list[Kayit]) -> float:
    """Çöküş eşiği — setteki araç sayısına göre.

    Sabit %40, yedi araçlı taban set için konmuştu: orada dengeli dağılım araç
    başına ~%14 demek, %40 bunun ~2,8 katı — gerçek bir yığılma.

    Ama ek set (`router_ek_sorular.jsonl`) yalnızca üç aracı kapsıyor; orada
    dengeli dağılım zaten ~%33. Sabit eşik o sette **yanlış alarm** veriyordu —
    ilk koşuda tam bu oldu, taban model %50 payla "ÇÖKÜŞ" damgası yedi.

    `2,5 / araç_sayısı` dengeli paya oranlı bir sınır veriyor. Taban set için
    0,357 çıkıyor; `COKUS_ESIGI` tabanı devrede kaldığı için **taban çizginin
    sonucu değişmiyor** (%70,0 / %66,7, çöküş yok — doğrulandı).

    ⚠️ `COKUS_TAVANI` olmazsa formül kendi kendini iptal ediyor: tek araçlı bir
    sette eşik %250 çıkar ve pay hiçbir zaman oraya ulaşamayacağı için dedektör
    **sessizce işlevsizleşir**. Bunu `test_cokus_tespit_ediliyor` yakaladı.
    Tavan, dedektörün hiçbir sette boşa düşmemesini garanti ediyor.
    """
    arac_sayisi = len({k.beklenen_arac for k in kayitlar}) or 1
    return min(COKUS_TAVANI, max(COKUS_ESIGI, 2.5 / arac_sayisi))


def cokus_kontrolu(kayitlar: list[Kayit]) -> tuple[bool, str, float]:
    """Model tek araca yığılmış mı?

    ⚠️ Eğitim verisi 3808 kat dengesiz (`siparis_onerisi_sorgula` %95,6) ve
    Kişi A'nın val/test bölmeleri de aynı dengesizlikte. Yani hep aynı cevabı
    veren bir model **onun test setinde %95 doğruluk** gösterir. Bu çarpıklığı
    görebilecek tek ölçüm dengeli olan bu set.

    "Doğruluk düştü" ile "model çöktü" farklı sorunlar: birincisi daha çok/iyi
    veri ister, ikincisi veri dengesini düzeltmeyi.
    """
    secilenler = [k.secilen_arac for k in kayitlar if k.secilen_arac]
    if not secilenler:
        return False, "", 0.0
    arac, adet = Counter(secilenler).most_common(1)[0]
    pay = adet / len(secilenler)
    return pay >= cokus_esigi(kayitlar), arac, pay


def rapor(kayitlar: list[Kayit], gecen_sn: float) -> dict[str, Any]:
    toplam = len(kayitlar)
    arac_dogru = sum(k.arac_dogru for k in kayitlar)
    tam_dogru = sum(k.tam_dogru for k in kayitlar)
    hatali = sum(k.hata is not None for k in kayitlar)
    uydurmali = [k for k in kayitlar if k.uydurma_parametre]

    print("\n" + "=" * 68)
    print("TABAN ÇİZGİ")
    print("=" * 68)
    print(f"  soru sayısı            : {toplam}")
    print(f"  araç doğru             : {arac_dogru}/{toplam}  (%{arac_dogru / toplam * 100:.1f})")
    print(f"  araç + parametre doğru : {tam_dogru}/{toplam}  (%{tam_dogru / toplam * 100:.1f})")
    print(f"  şema hatası            : {hatali}")
    print(f"  uydurma parametre      : {len(uydurmali)}")
    print(f"  toplam süre            : {gecen_sn:.1f} sn")

    cokmus, cokus_araci, cokus_payi = cokus_kontrolu(kayitlar)
    print("\n  ÇÖKÜŞ KONTROLÜ:")
    print(f"    en sık seçilen araç: {cokus_araci} (%{cokus_payi * 100:.0f})")
    if cokmus:
        print(f"    ⚠️  ÇÖKÜŞ — model cevapların %{cokus_payi * 100:.0f}'ini tek araca veriyor.")
        print("       Bu 'doğruluk düştü' değil, 'ayrım yapmayı bıraktı' demek.")
        print("       Muhtemel sebep: eğitim verisi dengesizliği (bkz. modül docstring'i).")
    else:
        print(f"    tamam — eşik %{cokus_esigi(kayitlar) * 100:.0f}, altında.")

    print("\n  STİLE GÖRE:")
    stil_toplam: dict[str, int] = defaultdict(int)
    stil_dogru: dict[str, int] = defaultdict(int)
    for k in kayitlar:
        stil_toplam[k.stil] += 1
        stil_dogru[k.stil] += int(k.arac_dogru)
    for stil in sorted(stil_toplam):
        d, t = stil_dogru[stil], stil_toplam[stil]
        print(f"    {stil:<10} {d}/{t}  (%{d / t * 100:.0f})")

    print("\n  ARACA GÖRE:")
    arac_toplam: dict[str, int] = defaultdict(int)
    arac_dogru_say: dict[str, int] = defaultdict(int)
    for k in kayitlar:
        arac_toplam[k.beklenen_arac] += 1
        arac_dogru_say[k.beklenen_arac] += int(k.arac_dogru)
    for arac in sorted(arac_toplam):
        d, t = arac_dogru_say[arac], arac_toplam[arac]
        print(f"    {arac:<32} {d}/{t}")

    print("\n  ÇEKİM GÜCÜ (beklenen -> seçilen):")
    print("    Fazla seçilen sınıf 'çöp kutusu' olmuş olabilir: kendi sorularını")
    print("    bilirken başka araçların sorularını da kapıyor. Genel doğruluk bunu")
    print("    göstermez — bir sınıf kazanıp diğeri kaybederse toplam sabit kalır.")
    cekim = cekim_gucu(kayitlar)
    kutular = []
    for arac, (bek, sec) in cekim.items():
        fark = sec - bek
        if fark > 0:
            isaret = f"  +{fark}  <-- fazla seçiliyor"
            kutular.append((arac, fark))
        elif fark < 0:
            isaret = f"  {fark}"
        else:
            isaret = "   0"
        print(f"    {arac:<32} {bek:>2} -> {sec:<2}{isaret}")
    if kutular:
        en_buyuk = max(kutular, key=lambda x: x[1])
        print(f"\n    En çok çeken: {en_buyuk[0]} (+{en_buyuk[1]})")
        print("    Bu sınıfın eğitim örnekleri az çeşitliyse beklenen davranış;")
        print("    çözüm daha çok eğitim turu değil, daha çeşitli soru.")

    if uydurmali:
        print("\n  UYDURMA PARAMETRELER (soruda hiç geçmiyor):")
        for k in uydurmali:
            print(f"    {k.soru[:50]} -> {k.uydurma_parametre}")

    yanlislar = [k for k in kayitlar if not k.arac_dogru]
    if yanlislar:
        print("\n  YANLIŞ YÖNLENDİRİLENLER:")
        for k in yanlislar:
            print(f"    [{k.stil}] {k.soru}")
            print(f"        beklenen: {k.beklenen_arac}")
            print(f"        seçilen : {k.secilen_arac or k.hata}")

    return {
        "soru_sayisi": toplam,
        "arac_dogruluk": arac_dogru / toplam,
        "tam_dogruluk": tam_dogru / toplam,
        "sema_hatasi": hatali,
        "uydurma_parametre": len(uydurmali),
        "cokus": {"var": cokmus, "arac": cokus_araci, "pay": cokus_payi},
        "arac_bazinda": {a: [arac_dogru_say[a], arac_toplam[a]] for a in sorted(arac_toplam)},
        "stil_bazinda": {s: [stil_dogru[s], stil_toplam[s]] for s in sorted(stil_toplam)},
        "cekim_gucu": {a: list(v) for a, v in cekim.items()},
        "sure_sn": round(gecen_sn, 1),
    }


def sonuctan_yukle(yol: Path) -> tuple[str, list[Kayit]]:
    """Kayıtlı sonuç JSON'unu `Kayit` listesine geri çevirir.

    Modül docstring'i "B3.5'te yeniden puanlama gerekirse modeli tekrar
    çalıştırmaya gerek kalmasın" diye söz veriyordu ama bunu yapacak bir yol
    yoktu — kayıtlı sonuca bakmak için her seferinde tek kullanımlık betik
    yazmak gerekiyordu. `--rapor` bu boşluğu kapatıyor.

    Puanlama `Kayit`'in property'lerinden geliyor, JSON'a gömülü değil; yani
    puanlama mantığı değişirse eski ölçüm **yeni mantıkla** yeniden puanlanır.
    Zaten amaç buydu.
    """
    govde = json.loads(yol.read_text(encoding="utf-8"))

    # ⚠️ ALTIN ETIKETLER SORU DOSYALARINDAN TAZELENIYOR.
    #
    # Kayitli JSON, olcum anindaki altin etiketi de tasiyor. Ama altin etiket
    # DUZELTILEBILIR: ek sette "dun gece ne cikti" parametresiz yazilmisti,
    # oysa schemas.py bu araca `tarih_ifadesi` veriyor ve egitim verisindeki
    # 155 ornegin 155'i parametreli. Etiket yanlisti.
    #
    # Etiket duzeltilince ESKI olcumler de yeni etiketle yeniden puanlanmali;
    # yoksa taban ile tur3 farkli altin etiketlerle karsilastirilir ve
    # kiyaslama gecersiz olur. Modul zaten "modeli tekrar calistirmaya gerek
    # kalmasin" diye soz veriyordu -- bu, o sozun asil kismi.
    #
    # ⚠️ Bu, altin etiketi modelin ciktisina uydurmak DEGIL. Etiket yalnizca
    # soru dosyasinda degistiyse degisir; soru dosyasi da sozlesme ve egitim
    # kuralina gore duzeltilir, modele bakilarak degil.
    altin: dict[str, Kayit] = {}
    for soru_dosyasi in (SORU_DOSYASI, EK_SORU_DOSYASI):
        if soru_dosyasi.exists():
            for ref in kayitlari_yukle(soru_dosyasi):
                altin[ref.soru.strip()] = ref

    kayitlar = [
        Kayit(
            soru=k["soru"],
            stil=k["stil"],
            beklenen_arac=k["beklenen_arac"],
            beklenen_parametreler=(
                altin[k["soru"].strip()].beklenen_parametreler
                if k["soru"].strip() in altin
                else k.get("beklenen_parametreler", {})
            ),
            secilen_arac=k.get("secilen_arac"),
            secilen_parametreler=k.get("secilen_parametreler"),
            hata=k.get("hata"),
            uretim_ms=k.get("uretim_ms", 0),
            deneme=k.get("deneme", 0),
        )
        for k in govde["kayitlar"]
    ]
    degisen = [
        k.soru
        for k, ham in zip(kayitlar, govde["kayitlar"], strict=True)
        if k.beklenen_parametreler != ham.get("beklenen_parametreler", {})
    ]
    if degisen:
        print(f"  ⚠️ {len(degisen)} sorunun altin etiketi soru dosyasindan tazelendi:")
        for soru in degisen:
            print(f"       {soru}")
        print()
    return govde.get("etiket", yol.stem), kayitlar


def sonuc_yolu(etiket: str) -> Path:
    """Etikete göre ayrı dosya — koşular birbirinin üstüne yazmasın.

    ⚠️ Önceden **her koşu** `router_taban_sonuc.json`'a yazıyordu: taban çizgi,
    ek set, 1. tur, 2. tur, hepsi aynı dosyaya. Yani dosya her zaman *en son*
    koşuyu tutuyordu ve "modeli tekrar çalıştırmaya gerek kalmasın" vaadi
    aslında tutulmuyordu.

    Bu sessiz bir veri kaybıydı: bayrak kombinasyonunu denemek için
    koşturduğum, var olmayan bir modele giden ve 18/18 hata veren bir koşu
    taban çizgi kaydını sildi. Hiçbir uyarı çıkmadı.

    Artık her etiket kendi dosyasına yazıyor; `router_taban_sonuc.json` ise
    donmuş taban çizginin adı olarak korunuyor (`--etiket taban`).
    """
    guvenli = "".join(c if c.isalnum() or c in "-_" else "-" for c in etiket)
    if guvenli in {"taban", "baseline", "taban-cizgi-egitim-oncesi"}:
        return SONUC_DOSYASI
    return SONUC_DOSYASI.with_name(f"router_sonuc_{guvenli}.json")


def sonucu_kaydet(kayitlar: list[Kayit], ozet: dict[str, Any], etiket: str) -> Path:
    """Ham sonuçları diske yazar.

    B3.5'te puanlama mantığı değişirse (ör. yeni bir kabul biçimi eklenirse)
    eski ölçümü modeli tekrar çalıştırmadan yeniden puanlayabilmek için.
    """
    govde = {
        "etiket": etiket,
        "ozet": ozet,
        "kayitlar": [
            {
                "soru": k.soru,
                "stil": k.stil,
                "beklenen_arac": k.beklenen_arac,
                "beklenen_parametreler": k.beklenen_parametreler,
                "secilen_arac": k.secilen_arac,
                "secilen_parametreler": k.secilen_parametreler,
                "hata": k.hata,
                "uretim_ms": k.uretim_ms,
                "deneme": k.deneme,
            }
            for k in kayitlar
        ],
    }
    yol = sonuc_yolu(etiket)
    yol.write_text(json.dumps(govde, ensure_ascii=False, indent=2), encoding="utf-8")
    return yol


def _cli() -> None:
    ayristirici = argparse.ArgumentParser(description="Router taban çizgisi ölçümü")
    ayristirici.add_argument("--sessiz", action="store_true", help="Satır satır çıktı basma")
    ayristirici.add_argument(
        "--etiket",
        default="taban-cizgi-egitim-oncesi",
        help="Sonuç dosyasına yazılacak etiket (ör. 'lora-15k-sonrasi')",
    )
    ayristirici.add_argument(
        "--model",
        default=None,
        help=(
            "Ollama model adı. Verilmezse .env'deki kullanılır. "
            "Eğitim sonrası ölçüm için: --model codifya-router:tur1"
        ),
    )
    ayristirici.add_argument(
        "--istem-bicimi",
        choices=("taban", "egitilmis"),
        default=None,
        help=(
            "Eğitilmiş modelde 'egitilmis' verilmeli — istem biçimi eğitimdekiyle "
            "aynı olmazsa model tanımadığı bir girdi görür"
        ),
    )
    ayristirici.add_argument(
        "--ek",
        action="store_true",
        help=(
            "Ince araclar icin ek soru setini de kostur (AYRI raporlanir; "
            "taban cizgiyle karistirilmaz)"
        ),
    )
    ayristirici.add_argument(
        "--rapor",
        type=Path,
        default=None,
        help=(
            "Modeli hic calistirmadan, kayitli bir sonuc JSON'undan raporu "
            "yeniden uret (or. --rapor training/eval/router_lora_tur2_sonuc.json)"
        ),
    )
    args = ayristirici.parse_args()

    if args.rapor:
        etiket, kayitlar = sonuctan_yukle(args.rapor)
        print(f"kayitli sonuc: {args.rapor.name}  (etiket: {etiket})")
        print("model CAGRILMADI — puanlama bugunku mantikla yeniden yapildi.\n")
        rapor(kayitlar, 0.0)
        return

    ayar = None
    if args.model or args.istem_bicimi:
        temel = ayarlar()
        ayar = temel.model_copy(
            update={
                k: v
                for k, v in (
                    ("llm_model_adi", args.model),
                    ("llm_istem_bicimi", args.istem_bicimi),
                )
                if v is not None
            }
        )
        print(f"model: {ayar.llm_model_adi} | istem biçimi: {ayar.llm_istem_bicimi}")

    kayitlar = kayitlari_yukle()
    print(f"{len(kayitlar)} soru, model çağrılıyor...\n")

    baslangic = time.perf_counter()
    olc(kayitlar, ayrinti=not args.sessiz, ayar=ayar)
    ozet = rapor(kayitlar, time.perf_counter() - baslangic)
    yol = sonucu_kaydet(kayitlar, ozet, args.etiket)

    print(f"\nHam sonuçlar: {yol}")
    print("⚠️ Özeti dokumantasyon/OLCUMLER.md'ye de yaz — B3.5'te karşılaştırılacak.")

    if args.ek:
        # ⚠️ AYRI raporlanıyor, taban setle BİRLEŞTİRİLMİYOR. Taban çizgi
        # (%70,0 / %66,7) 30 soruyla ölçüldü; karışık bir toplam o sayıyla
        # karşılaştırılamaz hale gelirdi.
        ek = kayitlari_yukle(EK_SORU_DOSYASI)
        print("\n" + "=" * 66)
        print(f"EK SET — ince araçlar için ayrı ölçüm ({len(ek)} soru)")
        print("Taban çizgiyle KARŞILAŞTIRILMAZ; araç bazında çözünürlük içindir.")
        print("=" * 66)
        baslangic = time.perf_counter()
        olc(ek, ayrinti=not args.sessiz, ayar=ayar)
        ek_ozet = rapor(ek, time.perf_counter() - baslangic)
        sonucu_kaydet(ek, ek_ozet, args.etiket + "-ek")


if __name__ == "__main__":
    _cli()


__all__ = [
    "COKUS_ESIGI",
    "Kayit",
    "cekim_gucu",
    "cokus_esigi",
    "cokus_kontrolu",
    "kayitlari_yukle",
    "modeli_bellekten_at",
    "olc",
    "rapor",
    "sonuctan_yukle",
    "sonucu_kaydet",
]
