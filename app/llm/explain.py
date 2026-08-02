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

SISTEM_ISTEMI = """Sen bir stok yönetimi uzmanısın. Sana bir ürünün verileri \
verilir, sen o kararın gerekçesini açıklayan tek paragraf yazarsın.

Kurallar:
1. YALNIZCA sana verilen sayıları kullan. Yeni sayı üretme, toplama \
çıkarma yapma, tahmin etme.
2. Sayıları sana verildiği biçimde yaz (1.200, 4,75, %94).
3. 2-3 tam cümle. Başlık, liste, madde işareti kullanma.
4. Verileri olduğu gibi sıralama; aralarındaki ilişkiyi açıkla.
5. ÜRÜN ADI VE TEDARİKÇİ ADI YAZMA. Sadece "ürün" veya "bu kalem" de.
6. Sade iş Türkçesi kullan.

ÖRNEK

VERİLER:
karar: stok.siparis
günlük ortalama talep (adet): 42
tedarik süresi (gün): 12
kullanılabilir stok (adet): 270
yeniden sipariş noktası (adet): 615
önerilen sipariş miktarı (adet): 1.200

GEREKÇE:
Günlük ortalama 42 adet tüketim ve 12 günlük tedarik süresi karşısında \
kullanılabilir stok 270 adede inerek 615 adetlik yeniden sipariş noktasının \
altına düştü. Tedarik süresi boyunca stoksuz kalmamak için 1.200 adet sipariş \
öneriliyor."""

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

    parcalar = [
        "VERİLER:",
        f"karar: {aday.tip.value}",
        *satirlar,
    ]

    if onceki_red:
        yasak = ", ".join(_tr_sayi(s) for s in onceki_red)
        parcalar += [
            "",
            f"UYARI: Önceki denemende şu sayıları uydurdun: {yasak}. "
            "Bu sayıları kullanma, yukarıdaki listede olmayan hiçbir sayı yazma.",
        ]

    parcalar += ["", "GEREKÇE:"]

    return "\n".join(parcalar)


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

    def uret(aday: DecisionCandidate, *, onceki_red: list[float] | None = None) -> str:
        sonuc = yapilandirilmis_uret(
            istemci,
            GerekceCiktisi,
            istem_kur(aday, onceki_red),
            sistem=SISTEM_ISTEMI,
            sicaklik=sicaklik,
            tohum=tohum,
        )
        return sonuc.deger.gerekce

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
    """
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
