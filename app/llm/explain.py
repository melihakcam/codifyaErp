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

from app.contracts import DecisionCandidate, Gerekce, GuardSonucu, KararTipi
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

SISTEM_ISTEMI = """Sen bir stok yönetimi uzmanısın. Verilen karara \
tek paragraflık Türkçe gerekçe yazıyorsun.

Kurallar:
1. YALNIZCA sana verilen sayıları kullan. Yeni sayı üretme, toplama \
çıkarma yapma, tahmin etme.
2. Sayıları sana verildiği biçimde yaz (1.200, 4,75, %94).
3. 2-3 cümle. Giriş cümlesi, başlık, madde işareti kullanma.
4. Kararın NEDEN alındığını açıkla, kararı tekrar etme.
5. Sade iş Türkçesi kullan."""

# Karar tipine göre gerekçede işi olan alanlar. Bilinçli olarak dar:
# modele 25 sayının hepsini vermek metni sayı çöplüğüne çeviriyor ve
# konuyla ilgisiz olanı kullanmasını davet ediyor.
_TIPE_GORE_ALANLAR: dict[KararTipi, tuple[str, ...]] = {
    KararTipi.STOK_SIPARIS: (
        "ort_gunluk_talep",
        "tedarik_suresi_gun",
        "kullanilabilir_stok",
        "eldeki_stok",
        "tedarikci_skoru",
        "tedarikci_zamaninda_teslim_orani",
    ),
    KararTipi.STOK_TASFIYE: (
        "son_hareket_gun_once",
        "eldeki_stok",
        "birim_maliyet_tl",
        "ort_gunluk_talep",
    ),
    KararTipi.STOK_AKSIYON_YOK: (
        "kullanilabilir_stok",
        "ort_gunluk_talep",
        "tedarik_suresi_gun",
    ),
}

_ETIKETLER: dict[str, str] = {
    "ort_gunluk_talep": "günlük ortalama talep (adet)",
    "tedarik_suresi_gun": "tedarik süresi (gün)",
    "kullanilabilir_stok": "kullanılabilir stok (adet)",
    "eldeki_stok": "eldeki stok (adet)",
    "tedarikci_skoru": "tedarikçi skoru",
    "tedarikci_zamaninda_teslim_orani": "tedarikçinin zamanında teslim oranı",
    "son_hareket_gun_once": "son hareketten bu yana geçen gün",
    "birim_maliyet_tl": "birim maliyet (TL)",
    "siparis_miktari": "önerilen sipariş miktarı (adet)",
    "rop": "yeniden sipariş noktası (adet)",
    "emniyet_stogu": "emniyet stoğu (adet)",
}


def _etiketle(ad: str) -> str:
    return _ETIKETLER.get(ad, ad.replace("_", " "))


def sayi_etiketleri(aday: DecisionCandidate) -> list[tuple[str, float]]:
    """Modele verilecek `(etiket, değer)` çiftleri — hepsi izinli kümede.

    Kaynaklar `izinli_sayilar()` ile aynı: özellikler, tetiklenen kuralların
    hesapladığı değerler, aksiyon. Fark, buradakinin **adlandırılmış ve
    seçilmiş** olması. Model neyin ne olduğunu bilmezse doğru sayıyı yanlış
    cümlede kullanır — guard bunu yakalayamaz, çünkü sayı meşrudur.
    """
    o = aday.ozellikler
    ciftler: list[tuple[str, float]] = []
    gorulen: set[str] = set()

    def ekle(ad: str, deger: object) -> None:
        if isinstance(deger, bool) or not isinstance(deger, (int, float)):
            return
        if ad in gorulen:
            return
        gorulen.add(ad)
        ciftler.append((_etiketle(ad), float(deger)))

    for ad in _TIPE_GORE_ALANLAR.get(aday.tip, ()):
        ekle(ad, getattr(o, ad, None))

    for kural in aday.tetiklenen_kurallar:
        for ad, deger in kural.degerler.items():
            ekle(ad, deger)

    for ad, deger in aday.aksiyon.items():
        ekle(ad, deger)

    return ciftler


def istem_kur(aday: DecisionCandidate, onceki_red: list[float] | None = None) -> str:
    """Gerekçe istemini kurar.

    Sayılar Türkçe biçimde veriliyor (`1.200`, `4,75`) — model gördüğü biçimi
    kopyalar, guard da Türkçe biçim bekler. İkisini hizalamak bedava.
    """
    o = aday.ozellikler
    satirlar = [f"{_etiketle(ad)}: {_tr_sayi(deger)}" for ad, deger in sayi_etiketleri(aday)]
    kurallar = ", ".join(k.kod for k in aday.tetiklenen_kurallar) or "—"

    parcalar = [
        f"Ürün: {o.sku_adi}",
        f"Tedarikçi: {o.tedarikci_adi}",
        f"Karar: {aday.tip.value}",
        f"Tetiklenen kurallar: {kurallar}",
        "",
        "Kullanabileceğin sayılar (BUNLARIN DIŞINA ÇIKMA):",
        *satirlar,
    ]

    if onceki_red:
        yasak = ", ".join(_tr_sayi(s) for s in onceki_red)
        parcalar += [
            "",
            f"UYARI: Önceki denemende şu sayıları uydurdun: {yasak}. "
            "Bu sayıları kullanma, yukarıdaki listede olmayan hiçbir sayı yazma.",
        ]

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
