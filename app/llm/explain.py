"""Türkçe gerekçe üretimi.

Sahip: Kişi B · B2.4

İki üretici var ve ikisi de kalıcı:

· `sablon_gerekce()` — deterministik, LLM'e hiç dokunmaz. Guard'ın geri
  dönüş noktası. Akıcı değil ama **asla yanlış değil**.
· `gerekce_uret()`   — gerçek LLM üretimi, guard'la sarılı.

`gerekce_uret` hiçbir koşulda hata fırlatmaz; model kapalıysa, şema
tutmazsa veya sayı uydurursa şablona düşer. Mimarinin ikinci kuralı:
**ERP asla LLM'i beklemez.** Karar zaten üretilmiştir, burada yalnızca
Türkçe cümle yazılır.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.contracts import ORAN_ALANLARI, DecisionCandidate, Gerekce, GuardSonucu, KararTipi
from app.llm.client import OllamaIstemcisi
from app.llm.guard import GerekceUreteci, gerekceyi_guvenceye_al
from app.llm.schemas import GerekceCiktisi, yapilandirilmis_uret


def _tr_sayi(deger: float) -> str:
    """1200.0 → '1.200' · 4.75 → '4,75' (Türkçe biçim)."""
    if float(deger).is_integer():
        return f"{int(deger):,}".replace(",", ".")
    return f"{deger:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")


def sablon_gerekce(aday: DecisionCandidate) -> str:
    """Deterministik Türkçe gerekçe — guard geri dönüşü olarak kullanılır.

    Yalnızca `aday` içindeki sayıları kullanır, dolayısıyla guard'dan her
    zaman geçer. Akıcılığı LLM kadar iyi değil ama asla yanlış değil.
    """
    o = aday.ozellikler

    if aday.tip is KararTipi.STOK_SIPARIS:
        miktar = aday.aksiyon.get("siparis_miktari")
        return (
            f"{o.sku_adi} için günlük ortalama {_tr_sayi(o.ort_gunluk_talep)} adet "
            f"tüketim var ve tedarik süresi {_tr_sayi(o.tedarik_suresi_gun)} gün. "
            f"Kullanılabilir stok {_tr_sayi(o.kullanilabilir_stok)} adede düştüğü için "
            f"{_tr_sayi(float(miktar)) if miktar is not None else '—'} adet sipariş "
            f"öneriliyor. Tedarikçi: {o.tedarikci_adi} "
            f"(skor {_tr_sayi(o.tedarikci_skoru)})."
        )

    if aday.tip is KararTipi.STOK_TASFIYE:
        return (
            f"{o.sku_adi} {_tr_sayi(o.son_hareket_gun_once)} gündür hareket görmedi. "
            f"Elde {_tr_sayi(o.eldeki_stok)} adet bağlı sermaye bulunuyor; "
            f"tasfiye değerlendirilmeli."
        )

    if aday.tip is KararTipi.STOK_AKSIYON_YOK:
        return (
            f"{o.sku_adi} için aksiyon gerekmiyor: kullanılabilir stok "
            f"{_tr_sayi(o.kullanilabilir_stok)} adet ve yeniden sipariş noktasının "
            f"üzerinde."
        )

    return f"{o.sku_adi} için {aday.tip.value} kararı üretildi."


def explain_stub(aday: DecisionCandidate) -> Gerekce:
    """Faz 0.5 stub'ı — şablon cümleyi Gerekce nesnesine sarar.

    Faz 2 B2.4'te `gerekce_uret(aday)` gelecek; bu fonksiyon şablon geri
    dönüşü olarak yaşamaya devam edecek.
    """
    return Gerekce(
        karar_id=aday.karar_id,
        metin=sablon_gerekce(aday),
        guard_sonucu=GuardSonucu.SABLONA_DUSTU,
        model_adi=None,
        uretim_ms=0,
    )


# ---------------------------------------------------------------------------
# B2.4 · Gerçek LLM üretimi
# ---------------------------------------------------------------------------

_KURALLAR = """Sen bir stok yönetimi uzmanısın. Sana bir ürünün verileri \
verilir, sen o kararın gerekçesini açıklayan tek paragraf yazarsın.

Kurallar:
1. YALNIZCA sana verilen sayıları kullan. Yeni sayı üretme, toplama \
çıkarma yapma, tahmin etme.
2. Sayıları sana verildiği biçimde yaz (1.200, 4,75, %94).
3. EN FAZLA 2 cümle yaz. Başlık, liste, madde işareti kullanma.
4. Verileri olduğu gibi sıralama; aralarındaki ilişkiyi açıkla.
5. ÜRÜN ADI VE TEDARİKÇİ ADI YAZMA. Sadece "ürün" veya "bu kalem" de.
6. Sade iş Türkçesi kullan."""

# Her karar tipine YALNIZCA kendi örneği gösterilir.
#
# ⚠️ Üçü birden verildiğinde model örnekleri harmanlıyordu: sipariş kararının
# gerekçesi "tasfiye değerlendirilmeli" diye bitiyor, bir diğeri "sipariş
# açmaya gerek yoktur" diyordu — kararın tam tersi. Guard bunların hiçbirini
# yakalayamaz, çünkü uydurulan şey sayı değil.
#
# Tek örnek ayrıca istemi kısaltıyor: daha az token, daha hızlı üretim.
_ORNEKLER: dict[KararTipi, str] = {
    KararTipi.STOK_SIPARIS: """ÖRNEK

VERİLER:
karar: stok.siparis
durum: kullanılabilir stok yeniden sipariş noktasının ALTINA düştü
günlük ortalama talep (adet): 42
tedarik süresi (gün): 12
kullanılabilir stok (adet): 270
yeniden sipariş noktası (adet): 615
önerilen sipariş miktarı (adet): 1.200

GEREKÇE:
Kullanılabilir stok 270 adede inerek 615 adetlik yeniden sipariş noktasının \
altına düştü. Günlük 42 adetlik tüketim hızıyla eldeki miktar 12 günlük \
tedarik süresini karşılamadığından 1.200 adet sipariş açılması öneriliyor.""",
    KararTipi.STOK_TASFIYE: """ÖRNEK

VERİLER:
karar: stok.tasfiye
durum: ürün uzun süredir hiç hareket görmedi
son hareketten bu yana geçen gün: 216
eldeki stok (adet): 12
birim maliyet (TL): 225,62
bağlı sermaye (TL): 2.707,43

GEREKÇE:
Ürün 216 gündür hiç hareket görmedi ve elde kalan 12 adet, birim maliyeti \
225,62 TL üzerinden 2.707,43 TL'lik sermayeyi bağlıyor. Talep geri dönmediği \
sürece bu tutar atıl kalacağından tasfiye değerlendirilmesi öneriliyor.""",
    KararTipi.STOK_AKSIYON_YOK: """ÖRNEK

VERİLER:
karar: stok.aksiyon_yok
durum: kullanılabilir stok yeniden sipariş noktasının ÜZERİNDE
kullanılabilir stok (adet): 480
günlük ortalama talep (adet): 12
yeniden sipariş noktası (adet): 260

GEREKÇE:
Kullanılabilir 480 adetlik stok, 260 adetlik yeniden sipariş noktasının \
üzerinde seyrediyor. Günlük 12 adetlik tüketim hızıyla mevcut miktar yeterli \
olduğundan şu aşamada sipariş açılması gerekmiyor.""",
}


def sistem_istemi(tip: KararTipi) -> str:
    """Kurallar + o karar tipine ait tek örnek."""
    ornek = _ORNEKLER.get(tip)
    return f"{_KURALLAR}\n\n{ornek}" if ornek else _KURALLAR


# İki cümlelik Türkçe gerekçe + JSON sarmalı için üst sınır.
#
# ⚠️ Bu bir kalite aracı, kaynak tasarrufu değil. "En fazla 2 cümle" talimatı
# tek başına yetmiyordu: model kuralı kabul edip yine de üçüncü bir dolgu
# cümlesi ekliyordu ("...bu durumun hedef servis seviyesine uygun oluyor").
# Bütçeyi kısınca üçüncü cümleye hiç başlayamıyor.
#
# Cümle ortasında kesilme riski var; kesilirse JSON bozulur, şema hatası
# olur ve zincir şablona düşer. Yani en kötü durum guard'ın zaten kapsadığı
# durum — kullanıcıya yarım cümle gitmez.
GEREKCE_MAX_TOKEN = 160

MAX_CUMLE = 2

# Cümle sonu: nokta + boşluk + BÜYÜK harf, ya da metnin sonundaki nokta.
#
# ⚠️ Naif bir `split(".")` Türkçede çalışmaz: `2.707,43` binlik ayracı da
# nokta. Buradaki desen noktadan sonra boşluk ARIYOR, `2.707` içindeki nokta
# boşluksuz olduğu için bölmüyor. Büyük harf koşulu da `12.5mm` gibi ürün
# ölçülerini koruyor.
_CUMLE_SONU = re.compile(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ])")


# Karar tipine göre gerekçede işi olan sayılar — özellik, kural değeri ve
# aksiyon ayrımı yapmadan, tek bir izin listesi.
#
# ⚠️ Bilinçli olarak ÇOK dar. İlk sürümde 10+ sayı veriliyordu ve model
# açıklamak yerine hepsini sıralıyordu ("eldeki stok 10 adetlik ve tedarikçi
# skoru 91,60 olarak belirtilen durumda, emniyet stoğu 6,58 adetlik ve...").
# Sayı azaldıkça model ilişki kurmak zorunda kalıyor. Buradaki her ekleme
# metni veri dökümüne bir adım daha yaklaştırır.
_TIPE_GORE_ALANLAR: dict[KararTipi, tuple[str, ...]] = {
    KararTipi.STOK_SIPARIS: (
        "ort_gunluk_talep",
        "tedarik_suresi_gun",
        "kullanilabilir_stok",
        "rop",
        "siparis_miktari",
        "hedef_servis_seviyesi",
    ),
    KararTipi.STOK_TASFIYE: (
        "son_hareket_gun_once",
        "eldeki_stok",
        "birim_maliyet_tl",
        "bagli_sermaye_tl",
    ),
    KararTipi.STOK_AKSIYON_YOK: (
        "kullanilabilir_stok",
        "ort_gunluk_talep",
        "rop",
    ),
}

_ETIKETLER: dict[str, str] = {
    "ort_gunluk_talep": "günlük ortalama talep (adet)",
    "tedarik_suresi_gun": "tedarik süresi (gün)",
    "kullanilabilir_stok": "kullanılabilir stok (adet)",
    "eldeki_stok": "eldeki stok (adet)",
    "son_hareket_gun_once": "son hareketten bu yana geçen gün",
    "birim_maliyet_tl": "birim maliyet (TL)",
    "bagli_sermaye_tl": "bağlı sermaye (TL)",
    "siparis_miktari": "önerilen sipariş miktarı (adet)",
    "rop": "yeniden sipariş noktası (adet)",
    "hedef_servis_seviyesi": "hedef servis seviyesi",
}


# Kararın yönünü modele **söylüyoruz**, hesaplatmıyoruz.
#
# ⚠️ B2.4 ölçümünde model `232 < 656,57` karşılaştırmasını yapamadı ve
# "656,57 adetlik yeniden sipariş noktasının ÜSTÜNE ulaştı" yazdı — oysa karar
# `stok.siparis`, yani altına düşmüştü. Guard sessiz kaldı, çünkü iki sayı da
# izinliydi; uydurulan şey sayı değil **ilişki**.
#
# Yön zaten kural motorunun verdiği karardan belli. 1.5B modelden aritmetik
# beklemek yerine sonucu hazır vermek hem doğru hem ucuz.
_DURUM_IFADELERI: dict[KararTipi, str] = {
    KararTipi.STOK_SIPARIS: "kullanılabilir stok yeniden sipariş noktasının ALTINA düştü",
    KararTipi.STOK_AKSIYON_YOK: "kullanılabilir stok yeniden sipariş noktasının ÜZERİNDE",
    KararTipi.STOK_TASFIYE: "ürün uzun süredir hiç hareket görmedi",
}


def _etiketle(ad: str) -> str:
    return _ETIKETLER.get(ad, ad.replace("_", " "))


def sayi_etiketleri(aday: DecisionCandidate) -> list[tuple[str, float]]:
    """Modele verilecek `(etiket, değer)` çiftleri — hepsi izinli kümede.

    Kaynaklar `izinli_sayilar()` ile aynı: özellikler, tetiklenen kuralların
    hesapladığı değerler, aksiyon. İki fark var:

    1. **Adlandırılmış.** Model neyin ne olduğunu bilmezse doğru sayıyı yanlış
       cümlede kullanır ("tedarik süresi 270 gün") — guard bunu yakalayamaz,
       çünkü sayı meşrudur.
    2. **Seçilmiş.** Yalnızca `_TIPE_GORE_ALANLAR`'daki adlar geçer, kaynağı
       ne olursa olsun.

    Oran alanları (`ORAN_ALANLARI`) yüzde olarak veriliyor: 0,90 yerine 90.
    Sözleşmenin `izinli_sayilar()`'ı bu alanlar için ×100 karşılığını zaten
    üretiyor, dolayısıyla guard'a takılmaz. Modele 0,90 vermek ise metne
    "hedef servis seviyesi 0,90" gibi iş diline yabancı bir ifade sokuyordu.
    """
    izinli_adlar = _TIPE_GORE_ALANLAR.get(aday.tip, ())
    ciftler: list[tuple[str, float]] = []
    gorulen: set[str] = set()

    def ekle(ad: str, deger: object) -> None:
        if ad not in izinli_adlar or ad in gorulen:
            return
        if isinstance(deger, bool) or not isinstance(deger, (int, float)):
            return
        gorulen.add(ad)
        if ad in ORAN_ALANLARI:
            ciftler.append((f"{_etiketle(ad)} (%)", float(deger) * 100.0))
        else:
            ciftler.append((_etiketle(ad), float(deger)))

    for ad in izinli_adlar:
        ekle(ad, getattr(aday.ozellikler, ad, None))

    for kural in aday.tetiklenen_kurallar:
        for ad, deger in kural.degerler.items():
            ekle(ad, deger)

    for ad, deger in aday.aksiyon.items():
        ekle(ad, deger)

    # İstemdeki sıra izin listesindeki sıra olsun — kaynağa göre değil.
    # Böylece "talep → tedarik süresi → stok → eşik → aksiyon" akışı korunur
    # ve model cümleyi bu mantıkla kurar.
    sira = {_etiketle(a): i for i, a in enumerate(izinli_adlar)}
    return sorted(ciftler, key=lambda c: sira.get(c[0].removesuffix(" (%)"), 99))


# ---------------------------------------------------------------------------
# Eğitilmiş model kipi (Faz 3)
# ---------------------------------------------------------------------------

GOREV_ETIKETI_GEREKCE = "GOREV: gerekce"

# ⚠️ Eğitimde kullanılan etiketler — `scratchpad/veri_hazirla.py` ile **birebir
# aynı** olmak zorunda. Türkçe karakter YOK ("gunluk", "suresi"), çünkü eğitim
# verisi böyle üretildi. Düzeltmek cazip ama model bunu gördü.
_EGITILMIS_ETIKETLER: tuple[tuple[str, str], ...] = (
    ("ort_gunluk_talep", "gunluk ortalama talep (adet)"),
    ("tedarik_suresi_gun", "tedarik suresi (gun)"),
    ("eldeki_stok", "eldeki stok (adet)"),
    ("son_hareket_gun_once", "son hareketten bu yana gecen gun"),
    ("birim_maliyet_tl", "birim maliyet (TL)"),
)


def egitilmis_istem_kur(aday: DecisionCandidate) -> str:
    """Eğitilmiş modelin beklediği gerekçe istemi.

    Taban kipten **üç farkı** var, üçü de bilinçli:

    1. **Ürün adı VAR.** B2.4'te adı çıkarmıştım çünkü taban model bozuyordu
       (`Astar Boya` → *starboy*). Ama eğitim verisindeki gerekçelerin
       %100'ünde ad geçiyor; isteme koymazsak model *yoktan ad uydurmayı*
       öğrenmiş olur. B3.1'de bu karara varıldı.
    2. **Kurallar ve few-shot örnek YOK.** Davranış ağırlıklara işlendi.
    3. **Etiketler eğitimdeki gibi.** Türkçe karakter yok, alan listesi sabit
       (karar tipine göre daralmıyor) — eğitim böyle yapıldı.

    Bu fonksiyon "daha iyi bir istem" yazmaya çalışmaz; **eğitimdekini
    tekrarlar.** İyileştirme yapılacaksa eğitim verisiyle birlikte yapılmalı.

    ⚠️ **`onceki_red` alınmıyor ve bu bilinçli.** Taban kipte guard reddedince
    isteme "şu sayıları kullanma" uyarısı ekleniyor; eğitilmiş modelde böyle
    bir satır eğitimde hiç geçmedi, eklemek modeli tanımadığı bir girdiye
    sokar.

    Bunun bilinen sonucu: eğitilmiş kipte **ikinci deneme birincinin aynısı**
    olur (açgözlü üretimde birebir). Yani guard reddettiğinde yeniden deneme
    boşa gider ve doğrudan şablona düşülür.

    Çözümü hazır ama eğitilmiş model üretime alınırken yapılmalı: yeniden
    denemede sıcaklığı yükseltmek. İstemi değiştirmeden çıktıyı değiştirir.
    Şu an `llm_istem_bicimi="taban"` olduğu için bu yol hiç çalışmıyor.
    """
    o = aday.ozellikler
    satirlar = [
        "VERILER:",
        f"urun: {o.sku_adi}",
        f"karar: {aday.tip.value}",
    ]
    for alan, etiket in _EGITILMIS_ETIKETLER:
        deger = getattr(o, alan, None)
        if isinstance(deger, (int, float)) and not isinstance(deger, bool):
            satirlar.append(f"{etiket}: {_tr_sayi(float(deger))}")

    return f"{GOREV_ETIKETI_GEREKCE}\n" + "\n".join(satirlar) + "\n\nGEREKCE:"


def istem_kur(aday: DecisionCandidate, onceki_red: list[float] | None = None) -> str:
    """Gerekçe istemini kurar.

    Biçim sistem istemindeki örnekle **birebir aynı**: `VERİLER:` bloğu, sonra
    `GEREKÇE:` satırı. İkisi ayrışırsa model örneği taklit edemez.

    ⚠️ İstem veri listesiyle **bitmemeli.** B2.4'ün ilk ölçümünde bitiyordu ve
    1.5B model 10 örneğin 6'sında listeyi devam ettirdi — istemi olduğu gibi
    geri yazdı. Guard bunu geçirdi, çünkü echo edilen metindeki sayılar zaten
    izinli sayılardı. Sondaki `GEREKÇE:` satırı modele "sıra sende" diyen
    işaret; bu tek satır olmadan tüm zincir sessizce çöp üretiyor.

    Sayılar Türkçe biçimde veriliyor (`1.200`, `4,75`) — model gördüğü biçimi
    kopyalar, guard da Türkçe biçim bekler. İkisini hizalamak bedava.

    ⚠️ **Ürün ve tedarikçi adı isteme KONMUYOR.** 1.5B model Türkçe özel
    adları bozuyordu: "Astar Boya" → *"starboy"*, "İzocam" → *"isyancı
    yalıtım levhası"*. Guard bunu yakalayamaz, çünkü uydurulan şey sayı
    değil. Ad zaten ERP'de kararın yanında duruyor; gerekçenin içinde
    tekrarlanması gerekmiyor. Şablon (`sablon_gerekce`) adı yazmaya devam
    ediyor — o deterministik, bozma riski yok.
    """
    satirlar = [f"{_etiketle(ad)}: {_tr_sayi(deger)}" for ad, deger in sayi_etiketleri(aday)]

    parcalar = ["VERİLER:", f"karar: {aday.tip.value}"]
    durum = _DURUM_IFADELERI.get(aday.tip)
    if durum:
        parcalar.append(f"durum: {durum}")
    parcalar += satirlar

    if onceki_red:
        yasak = ", ".join(_tr_sayi(s) for s in onceki_red)
        parcalar += [
            "",
            f"UYARI: Önceki denemende şu sayıları uydurdun: {yasak}. "
            "Bu sayıları kullanma, yukarıdaki listede olmayan hiçbir sayı yazma.",
        ]

    parcalar += ["", "GEREKÇE:"]

    return "\n".join(parcalar)


def ilk_cumleleri_al(metin: str, en_fazla: int = MAX_CUMLE) -> str:
    """Metni ilk `en_fazla` cümleye kırpar.

    "En fazla 2 cümle" talimatı ve `num_predict` sınırı tek başına yetmedi:
    model kuralı kabul edip yine de üçüncü bir dolgu cümlesi ekliyordu.

        "...60 adet sipariş açılması öneriliyor. Bu durumda hedef servis
         seviyesi %90'ı karşılayacak şekilde bir sipariş oluşturuluyor."

    İkinci cümle kararı açıklıyor, üçüncüsü hiçbir şey söylemiyor. Modele
    yalvarmak yerine kırpmak deterministik ve bedava.

    ⚠️ Kırpma guard'dan **önce** yapılıyor. Atılan cümlede uydurma sayı varsa
    zaten kullanıcıya gitmiyor; guard'ın onu görüp metni şablona düşürmesi
    gereksiz bir kayıp olurdu.
    """
    parcalar = _CUMLE_SONU.split(metin.strip())
    return " ".join(parcalar[:en_fazla]).strip()


def anlatilacak_sayi_var_mi(aday: DecisionCandidate) -> bool:
    """İsteme konacak sayıların hepsi sıfır mı?

    B2.4 ölçümünde 10 kararın 2'si böyleydi: talep 0, stok 0, yeniden sipariş
    noktası 0. Modelden "hiçbir şey yok" durumundan anlamlı bir cümle kurmasını
    istemek, olmayan bir sebep uydurmasını davet ediyor. Gerçekten öyle oldu:

        "Bu durum, stok yönetimi kurallarını taklit eden bir durumdur."

    Guard bunu yakalayamaz — cümlede uydurma sayı yok, uydurulan şey **sebep**.
    Bu kararlarda şablon hem doğru hem anlaşılır, üstelik model hiç çalışmıyor.
    """
    return any(deger != 0 for _, deger in sayi_etiketleri(aday))


def llm_ureteci(
    istemci: OllamaIstemcisi,
    *,
    sicaklik: float | None = None,
    tohum: int | None = None,
) -> GerekceUreteci:
    """`gerekceyi_guvenceye_al`'a verilecek üreteci kapamayla üretir.

    Guard'ın `GerekceUreteci` protokolü istemci bilmez (bilmemeli — testler
    sahte üreteçle çalışıyor). İstemciyi kapamada taşımak ikisini ayrı tutar.
    """

    egitilmis = istemci.ayar.llm_istem_bicimi == "egitilmis"

    def uret(aday: DecisionCandidate, *, onceki_red: list[float] | None = None) -> str:
        sonuc = yapilandirilmis_uret(
            istemci,
            GerekceCiktisi,
            egitilmis_istem_kur(aday) if egitilmis else istem_kur(aday, onceki_red),
            # Eğitilmiş kipte sistem promptu YOK: kurallar ve örnek ağırlıklara
            # işlendi, eğitimde de sistem promptu kullanılmadı.
            sistem=None if egitilmis else sistem_istemi(aday.tip),
            max_token=GEREKCE_MAX_TOKEN,
            sicaklik=sicaklik,
            tohum=tohum,
        )
        return ilk_cumleleri_al(sonuc.deger.gerekce)

    return uret


def gerekce_uret(
    aday: DecisionCandidate,
    istemci: OllamaIstemcisi,
    *,
    sicaklik: float | None = None,
    tohum: int | None = None,
    max_deneme: int = 2,
) -> Gerekce:
    """⭐ B2.4 · Guard'lı gerçek gerekçe üretimi. **Hata fırlatmaz.**

    İki ayrı yeniden deneme katmanı var ve bilinçli olarak ayrılar:

    · `yapilandirilmis_uret` içindeki — bozuk JSON / şemaya uymayan çıktı
    · buradaki (`gerekceyi_guvenceye_al`) — şema tuttu ama sayı uydurdu

    İkisi farklı arızalar: ilki modelin biçim hatası, ikincisi içerik hatası.
    En kötü durumda 4 model çağrısı olur; ölçümlerde şema uyumu yüksek
    olduğu için pratikte 1-2 çağrı görülüyor.

    Anlatacak sayısı olmayan kararlarda (bkz. `anlatilacak_sayi_var_mi`) model
    hiç çağrılmaz, doğrudan şablon döner.
    """
    if not anlatilacak_sayi_var_mi(aday):
        return explain_stub(aday)

    return gerekceyi_guvenceye_al(
        aday,
        llm_ureteci(istemci, sicaklik=sicaklik, tohum=tohum),
        model_adi=istemci.ayar.llm_model_adi,
        max_deneme=max_deneme,
    )


def llm_gerekce_ureteci(
    istemci: OllamaIstemcisi,
    *,
    sicaklik: float | None = None,
    tohum: int | None = None,
) -> Callable[[DecisionCandidate], Gerekce]:
    """`gecelik_tarama(gerekce_ureteci=...)` parametresine verilecek hâl.

    Gecelik iş `(aday) -> Gerekce` imzası bekliyor ve istemci bilmiyor —
    bilmemeli, testleri şablonla çevrimdışı koşuyor. İstemciyi kapamada
    taşımak ikisini ayrı tutar.

        ureteci = llm_gerekce_ureteci(OllamaIstemcisi())
        gecelik_tarama(oturum, gerekce_ureteci=ureteci)
    """

    def uret(aday: DecisionCandidate) -> Gerekce:
        return gerekce_uret(aday, istemci, sicaklik=sicaklik, tohum=tohum)

    return uret
