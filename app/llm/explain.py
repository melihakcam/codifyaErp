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

from app.contracts import (
    ORAN_ALANLARI,
    Alan,
    DecisionCandidate,
    FinansOzellikleri,
    Gerekce,
    GuardSonucu,
    KararTipi,
    UretimOzellikleri,
)
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

    ⚠️ **Faz 8 / B5'te bulunan kusur.** Bu fonksiyon alan-bağımsız bir
    katmanda duruyor ama stok alanlarını doğrudan okuyordu (`o.sku_adi`).
    Finans kararı buraya düştüğü anda `AttributeError` — ve buraya düşmek
    istisna değil, normal akış: anlatacak sayısı olmayan her karar ve
    guard'ın reddettiği her gerekçe şablona geliyor.

    Gecelik iş bunu yakalayıp yutuyor (`_finans_kararlari` try/except) ama
    o zaman da finans kararları sessizce kuyruğa hiç girmiyordu.
    `BILINEN-EKSIKLER.md` §1'in gözden kaçmış beşinci sızıntısı.
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

    if isinstance(o, FinansOzellikleri):
        if aday.tip is KararTipi.FINANS_TAHSILAT_TAKIBI:
            return (
                f"{o.musteri_adi} için {_tr_sayi(o.vadesi_gecen_tl)} TL vadesi geçmiş "
                f"alacak var ve en eski fatura {_tr_sayi(o.en_eski_gecikme_gun)} gündür "
                f"gecikmede. Bu müşteri ortalama {_tr_sayi(o.ort_odeme_gecikmesi_gun)} "
                f"gün gecikmeyle ödüyor; tahsilat takibi öneriliyor."
            )
        if aday.tip is KararTipi.FINANS_KARSILIK_AYIR:
            oran = aday.aksiyon.get("onerilen_karsilik_orani")
            return (
                f"{o.musteri_adi} alacağının en eskisi {_tr_sayi(o.en_eski_gecikme_gun)} "
                f"gündür tahsil edilemiyor. {_tr_sayi(o.vadesi_gecen_tl)} TL vadesi geçen "
                f"tutar için "
                f"{_tr_sayi(float(oran) * 100) if oran is not None else '—'}% karşılık "
                f"ayrılması öneriliyor."
            )
        if aday.tip is KararTipi.FINANS_KREDI_LIMITI_DUSUR:
            yeni = aday.aksiyon.get("onerilen_kredi_limiti_tl")
            return (
                f"{o.musteri_adi} tahsilat oranı {_tr_sayi(o.tahsilat_orani * 100)}% ve "
                f"ödeme davranışı öngörülemez. Kredi limitinin "
                f"{_tr_sayi(o.kredi_limiti_tl)} TL'den "
                f"{_tr_sayi(float(yeni)) if yeni is not None else '—'} TL'ye "
                f"düşürülmesi öneriliyor."
            )
        return f"{o.musteri_adi} için aksiyon gerekmiyor: gecikme bu müşterinin olağan aralığında."

    if isinstance(o, UretimOzellikleri):
        if aday.tip is KararTipi.URETIM_EMIR_AC:
            miktar = aday.aksiyon.get("emir_miktari")
            return (
                f"{o.kalem_adi} için önümüzdeki {o.tahmin_ufuk_gun} günde en fazla "
                f"{_tr_sayi(o.tahmin_ust_band)} adet talep bekleniyor; elde ve açık "
                f"emirlerde {_tr_sayi(o.net_pozisyon)} adet var. "
                f"{_tr_sayi(float(miktar)) if miktar is not None else '—'} adet "
                f"üretim emri açılması öneriliyor ({o.hat_adi})."
            )
        if aday.tip is KararTipi.URETIM_EMIR_ERTELEME:
            miktar = aday.aksiyon.get("onerilen_miktar")
            return (
                f"{o.kalem_adi} için ihtiyaç var ama "
                f"{_tr_sayi(float(miktar)) if miktar is not None else '—'} adetlik emir, "
                f"{o.hat_adi} hattının {_tr_sayi(o.hazirlik_suresi_saat)} saatlik hazırlık "
                f"süresini karşılayacak kadar büyük değil; emir erteleniyor."
            )
        if aday.tip is KararTipi.URETIM_KAPASITE_ASIMI:
            asim = aday.aksiyon.get("asim_saat")
            return (
                f"{o.hat_adi} kapasitesi "
                f"{_tr_sayi(float(asim)) if asim is not None else '—'} saat aşılıyor. "
                f"{o.kalem_adi} için eldeki mal diğer kalemlere göre daha uzun süre "
                f"yettiğinden bu emrin ertelenmesi öneriliyor."
            )
        return (
            f"{o.kalem_adi} için üretim gerekmiyor: elde ve açık emirlerdeki "
            f"{_tr_sayi(o.net_pozisyon)} adet, {o.tahmin_ufuk_gun} günlük talebi "
            f"karşılıyor."
        )

    # ⚠️ Son çare, alan-bağımsız: `gorunen_ad` sözleşmenin bu soruya cevabı.
    # Doğrudan `o.sku_adi` yazmak, yeni bir alan eklendiğinde burayı yeniden
    # kırardı (bkz. yukarıdaki uyarı).
    return f"{o.gorunen_ad} için {aday.tip.value} kararı üretildi."


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

# Eğitilmiş kipte yeniden denemede kullanılan sıcaklık.
#
# Neden gerekli: eğitilmiş kip `onceki_red`'i isteme yazamıyor (o satır
# eğitimde hiç geçmedi). İstem aynı kalınca, sıcaklık 0'da çıktı da birebir
# aynı olur ve ikinci deneme boşa gider.
#
# 0,7 seçildi: 0,2-0,3 açgözlü üretimden yeterince ayrışmıyor, 1,0 üstü
# uydurmayı artırıyor. Guard ikinci denemeyi de denetlediği için risk yok —
# tutmazsa şablona düşülür.
YENIDEN_DENEME_SICAKLIGI = 0.7

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
    # ⚠️ Faz 8 / B5'te eklendi. Finans tipleri bu sözlükte YOKTU ve sonucu
    # sessizdi: `sayi_etiketleri` boş liste döndürüyor, dolayısıyla
    # `anlatilacak_sayi_var_mi` her finans kararında False oluyor ve
    # **model hiç çağrılmıyordu**. Her finans gerekçesi şablona düşüyordu.
    #
    # Yani "model finansı hiç görmedi" tespiti doğruydu ama sebebi eğitim
    # eksikliği değil, sorunun hiç sorulmamasıydı. Ölçüm bunu ancak
    # koşturunca ortaya çıkardı — 25 kararın 25'i 0 saniyede şablona düştü.
    KararTipi.FINANS_TAHSILAT_TAKIBI: (
        "vadesi_gecen_tl",
        "en_eski_gecikme_gun",
        "ort_odeme_gecikmesi_gun",
        "takip_esigi_gun",
    ),
    KararTipi.FINANS_KARSILIK_AYIR: (
        "en_eski_gecikme_gun",
        "vadesi_gecen_tl",
        "onerilen_karsilik_orani",
        "karsilik_tutari_tl",
    ),
    KararTipi.FINANS_KREDI_LIMITI_DUSUR: (
        "musteri_risk_skoru",
        "tahsilat_orani",
        "kredi_limiti_tl",
        "onerilen_kredi_limiti_tl",
    ),
    KararTipi.FINANS_AKSIYON_YOK: (
        "en_eski_gecikme_gun",
        "takip_esigi_gun",
        "ort_odeme_gecikmesi_gun",
    ),
    # ⚠️ Faz 10 / Adım 6. Üretim tipleri buraya **kod yazılmadan önce**
    # eklendi: B5'te finans tam bu sözlükte olmadığı için `sayi_etiketleri`
    # boş dönüyor, `anlatilacak_sayi_var_mi` False oluyor ve model hiç
    # çağrılmıyordu — 25 kararın 25'i 0 saniyede şablona düşmüştü. Sessiz
    # bir kusur; ancak ölçünce görünüyor.
    KararTipi.URETIM_EMIR_AC: (
        "tahmin_toplam",
        "tahmin_ust_band",
        "net_pozisyon",
        "emir_miktari",
        "hat_yuku_saat",
    ),
    KararTipi.URETIM_EMIR_ERTELEME: (
        "acik",
        "onerilen_miktar",
        "hazirlik_suresi_saat",
        "tahmin_toplam",
    ),
    KararTipi.URETIM_KAPASITE_ASIMI: (
        "toplam_yuk_saat",
        "kapasite_saat",
        "asim_saat",
        "kapsama_gun",
        "ertelenen_miktar",
    ),
    KararTipi.URETIM_AKSIYON_YOK: (
        "net_pozisyon",
        "tahmin_ust_band",
        "tahmin_ufuk_gun",
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
    # Finans (B5)
    "vadesi_gecen_tl": "vadesi geçmiş alacak (TL)",
    "en_eski_gecikme_gun": "en eski faturanın gecikmesi (gün)",
    "ort_odeme_gecikmesi_gun": "müşterinin ortalama ödeme gecikmesi (gün)",
    "takip_esigi_gun": "takip eşiği (gün)",
    "onerilen_karsilik_orani": "önerilen karşılık oranı",
    "karsilik_tutari_tl": "karşılık tutarı (TL)",
    "musteri_risk_skoru": "müşteri risk skoru (0-100)",
    "tahsilat_orani": "tahsilat oranı",
    "kredi_limiti_tl": "mevcut kredi limiti (TL)",
    "onerilen_kredi_limiti_tl": "önerilen kredi limiti (TL)",
    # Üretim (Adım 6)
    "tahmin_toplam": "ufuk boyunca beklenen talep (adet)",
    "tahmin_alt_band": "beklenen talebin alt sınırı (adet)",
    "tahmin_ust_band": "beklenen talebin üst sınırı (adet)",
    "tahmin_ufuk_gun": "planlama ufku (gün)",
    "net_pozisyon": "elde + açık emirlerdeki miktar (adet)",
    "emir_miktari": "önerilen üretim miktarı (adet)",
    "onerilen_miktar": "önerilen üretim miktarı (adet)",
    "ertelenen_miktar": "ertelenen üretim miktarı (adet)",
    "hat_yuku_saat": "emrin hattı meşgul edeceği süre (saat)",
    "toplam_yuk_saat": "hattaki emirlerin toplam yükü (saat)",
    "kapasite_saat": "hattın kullanılabilir kapasitesi (saat)",
    "asim_saat": "kapasite aşımı (saat)",
    "kapsama_gun": "eldeki malın yeteceği süre (gün)",
    "hazirlik_suresi_saat": "hat hazırlık süresi (saat)",
    "acik": "karşılanamayan ihtiyaç (adet)",
    "mrp_ihtiyaci": "üretim emirlerinden doğan ek ihtiyaç (adet)",
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
    # Finans (B5) — yön yine söyleniyor, hesaplatılmıyor.
    KararTipi.FINANS_TAHSILAT_TAKIBI: (
        "gecikme, bu müşterinin kendi olağan aralığının ÜSTÜNDE ya da alacak "
        "takip maliyetini karşılayacak kadar BÜYÜK"
    ),
    KararTipi.FINANS_KARSILIK_AYIR: "alacak, karşılık ayrılacak kadar ESKİ",
    KararTipi.FINANS_KREDI_LIMITI_DUSUR: "müşterinin risk skoru eşiğin ALTINDA",
    KararTipi.FINANS_AKSIYON_YOK: "gecikme, bu müşteri için OLAĞAN aralıkta",
    # Üretim (Adım 6) — yön yine söyleniyor, hesaplatılmıyor.
    KararTipi.URETIM_EMIR_AC: (
        "elde ve açık emirlerdeki miktar, ufuktaki talebin ÜST SINIRINI karşılamıyor"
    ),
    KararTipi.URETIM_EMIR_ERTELEME: ("açık var ama hattı kurmaya değecek kadar BÜYÜK DEĞİL"),
    KararTipi.URETIM_KAPASITE_ASIMI: (
        "hattaki emirlerin toplam yükü kapasitenin ÜSTÜNDE ve bu kalemin stoğu "
        "diğerlerine göre DAHA UZUN süre yetiyor"
    ),
    KararTipi.URETIM_AKSIYON_YOK: (
        "elde ve açık emirlerdeki miktar, ufuktaki talebi ZATEN karşılıyor"
    ),
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
    return _sayi_etiketleri_kur(aday, _TIPE_GORE_ALANLAR.get(aday.tip, ()), _ETIKETLER)


def _sayi_etiketleri_kur(
    aday: DecisionCandidate,
    izinli_adlar: tuple[str, ...],
    etiket_sozlugu: dict[str, str],
) -> list[tuple[str, float]]:
    """`sayi_etiketleri` ile `egitilmis_sayi_etiketleri`'nin ortak gövdesi.

    İki kip **aynı mantığı** kullanır (kaynaklar, oran×100, sıralama); yalnızca
    hangi alanların geçeceği ve etiket metinleri farklıdır. Mantığı tek yerde
    tutmak bilinçli: kopyalanırsa biri düzeltilip diğeri unutulur — bu dosyanın
    zaten bir kez yaşadığı hata.
    """

    def etiketle(ad: str) -> str:
        return etiket_sozlugu.get(ad, ad.replace("_", " "))

    ciftler: list[tuple[str, float]] = []
    gorulen: set[str] = set()

    def ekle(ad: str, deger: object) -> None:
        if ad not in izinli_adlar or ad in gorulen:
            return
        if isinstance(deger, bool) or not isinstance(deger, (int, float)):
            return
        gorulen.add(ad)
        if ad in ORAN_ALANLARI:
            ciftler.append((f"{etiketle(ad)} (%)", float(deger) * 100.0))
        else:
            ciftler.append((etiketle(ad), float(deger)))

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
    sira = {etiketle(a): i for i, a in enumerate(izinli_adlar)}
    return sorted(ciftler, key=lambda c: sira.get(c[0].removesuffix(" (%)"), 99))


# ---------------------------------------------------------------------------
# Eğitilmiş model kipi (Faz 3)
# ---------------------------------------------------------------------------

GOREV_ETIKETI_GEREKCE = "GOREV: gerekce"

# ⭐ Eğitilmiş kipin alan listesi — 2. turun kök nedeninin düzeltmesi (2026-08-06).
#
# ÖNCEKİ SÜRÜM karar tipinden bağımsız **5 sabit alan** veriyordu. Hedef
# metinler ise `training/label_rationale.py::SLOTLAR`'daki alanlardan
# üretilmişti — iskonto oranı, sipariş miktarı, tedarikçi skoru, ROP...
# İstemde olmayan bu sayıları model ancak **uydurarak** yazabilirdi ve
# eğitim örneklerinin %79,4'ü tam olarak bunu öğretiyordu. Ölçülen sonuç:
# eğitilmiş modelin guard kabulü %25,7, taban modelin %100.
# (Tam analiz: dokumantasyon/OLCUMLER.md, "2. turun KÖK NEDENİ".)
#
# ⚠️ Bu liste `_TIPE_GORE_ALANLAR`'dan (taban kip) BİLİNÇLİ OLARAK AYRI.
# Taban kipin listesi B2.4'te dar tutulacak şekilde ayarlandı: sayı arttıkça
# model ilişki kurmayı bırakıp veri döküyor. Oradaki daraltma bir kalite
# kararı; buradaki genişlik ise bir **zorunluluk** — hedef metnin kullandığı
# her sayı istemde olmak zorunda. İkisini birleştirmek, birini bozmadan
# diğerini düzeltmeyi imkânsız kılardı.
#
# ⚠️ `training/veri_hazirla.py` bu listeyi **doğrudan bu dosyadan** alıyor
# (import ediyor). Eskiden iki yerde elle kopyalanmıştı ve ayrışma riski
# taşıyordu; artık tek kaynak burası.
_EGITILMIS_TIPE_GORE_ALANLAR: dict[KararTipi, tuple[str, ...]] = {
    KararTipi.STOK_SIPARIS: (
        "ort_gunluk_talep",
        "tedarik_suresi_gun",
        "kullanilabilir_stok",
        "rop",
        "siparis_miktari",
        "tedarikci_skoru",
    ),
    KararTipi.STOK_TASFIYE: (
        "son_hareket_gun_once",
        "eldeki_stok",
        "birim_maliyet_tl",
        "bagli_sermaye_tl",
        "onerilen_iskonto_orani",
    ),
    KararTipi.STOK_AKSIYON_YOK: (
        "kullanilabilir_stok",
        "ort_gunluk_talep",
        "rop",
    ),
    # ⚠️ Faz 8 / B5'te eklendi. Finans tipleri bu sözlükte YOKTU ve sonucu
    # sessizdi: `sayi_etiketleri` boş liste döndürüyor, dolayısıyla
    # `anlatilacak_sayi_var_mi` her finans kararında False oluyor ve
    # **model hiç çağrılmıyordu**. Her finans gerekçesi şablona düşüyordu.
    #
    # Yani "model finansı hiç görmedi" tespiti doğruydu ama sebebi eğitim
    # eksikliği değil, sorunun hiç sorulmamasıydı. Ölçüm bunu ancak
    # koşturunca ortaya çıkardı — 25 kararın 25'i 0 saniyede şablona düştü.
    KararTipi.FINANS_TAHSILAT_TAKIBI: (
        "vadesi_gecen_tl",
        "en_eski_gecikme_gun",
        "ort_odeme_gecikmesi_gun",
        "takip_esigi_gun",
    ),
    KararTipi.FINANS_KARSILIK_AYIR: (
        "en_eski_gecikme_gun",
        "vadesi_gecen_tl",
        "onerilen_karsilik_orani",
        "karsilik_tutari_tl",
    ),
    KararTipi.FINANS_KREDI_LIMITI_DUSUR: (
        "musteri_risk_skoru",
        "tahsilat_orani",
        "kredi_limiti_tl",
        "onerilen_kredi_limiti_tl",
    ),
    KararTipi.FINANS_AKSIYON_YOK: (
        "en_eski_gecikme_gun",
        "takip_esigi_gun",
        "ort_odeme_gecikmesi_gun",
    ),
    # ⚠️ Faz 10 / Adım 6. Üretim tipleri buraya **kod yazılmadan önce**
    # eklendi: B5'te finans tam bu sözlükte olmadığı için `sayi_etiketleri`
    # boş dönüyor, `anlatilacak_sayi_var_mi` False oluyor ve model hiç
    # çağrılmıyordu — 25 kararın 25'i 0 saniyede şablona düşmüştü. Sessiz
    # bir kusur; ancak ölçünce görünüyor.
    KararTipi.URETIM_EMIR_AC: (
        "tahmin_toplam",
        "tahmin_ust_band",
        "net_pozisyon",
        "emir_miktari",
        "hat_yuku_saat",
    ),
    KararTipi.URETIM_EMIR_ERTELEME: (
        "acik",
        "onerilen_miktar",
        "hazirlik_suresi_saat",
        "tahmin_toplam",
    ),
    KararTipi.URETIM_KAPASITE_ASIMI: (
        "toplam_yuk_saat",
        "kapasite_saat",
        "asim_saat",
        "kapsama_gun",
        "ertelenen_miktar",
    ),
    KararTipi.URETIM_AKSIYON_YOK: (
        "net_pozisyon",
        "tahmin_ust_band",
        "tahmin_ufuk_gun",
    ),
}

# Türkçe karakter YOK ("gunluk", "suresi") — eğitim verisi böyle üretiliyor,
# tokenizer'a gereksiz yük bindirmemek için. Etiket metinleri değişirse eğitim
# verisi yeniden üretilmeli, yoksa model tanımadığı bir istem görür.
_EGITILMIS_ETIKETLER: dict[str, str] = {
    "ort_gunluk_talep": "gunluk ortalama talep (adet)",
    "tedarik_suresi_gun": "tedarik suresi (gun)",
    "kullanilabilir_stok": "kullanilabilir stok (adet)",
    "eldeki_stok": "eldeki stok (adet)",
    "son_hareket_gun_once": "son hareketten bu yana gecen gun",
    "birim_maliyet_tl": "birim maliyet (TL)",
    "bagli_sermaye_tl": "bagli sermaye (TL)",
    "siparis_miktari": "onerilen siparis miktari (adet)",
    "rop": "yeniden siparis noktasi (adet)",
    "tedarikci_skoru": "tedarikci skoru",
    "onerilen_iskonto_orani": "onerilen iskonto orani",
}

# Sipariş gerekçelerinde tedarikçi ADI da geçiyor (bkz. label_rationale
# SLOTLAR: TEDARIKCI_ADI). Sayı değil ama aynı kural geçerli: istemde yoksa
# model uydurur — üstelik guard metin uydurmasını **yakalayamaz**, çünkü
# uydurulan şey sayı değil. Ürün adı B3.1'de aynı gerekçeyle eklenmişti.
_EGITILMIS_METIN_ALANLARI: dict[KararTipi, tuple[tuple[str, str], ...]] = {
    KararTipi.STOK_SIPARIS: (("tedarikci_adi", "tedarikci"),),
}


def egitilmis_sayi_etiketleri(aday: DecisionCandidate) -> list[tuple[str, float]]:
    """Eğitilmiş kipin isteme koyacağı `(etiket, değer)` çiftleri.

    `sayi_etiketleri` ile aynı mantık, farklı liste — gerekçesi
    `_EGITILMIS_TIPE_GORE_ALANLAR`'ın açıklamasında.
    """
    return _sayi_etiketleri_kur(
        aday, _EGITILMIS_TIPE_GORE_ALANLAR.get(aday.tip, ()), _EGITILMIS_ETIKETLER
    )


def egitilmis_istem_govdesi(aday: DecisionCandidate) -> str:
    """İstemin `GOREV:` başlığı **olmadan** gövdesi.

    ⭐ Eğitim verisini üreten `training/veri_hazirla.py` de bu fonksiyonu
    çağırır. Başlığın ayrı olmasının sebebi tarihsel: eğitim defteri
    (`train_lora.ipynb::gerekce_metni`) `GOREV: gerekce` satırını kendisi
    ekliyor, `veri_hazirla` ise yalnızca gövdeyi yazıyor. Çalışma zamanı
    ikisini birleştiriyor. Tek kaynak burası olduğu sürece üçü de tutar.
    """
    o = aday.ozellikler
    # ⚠️ Kalem etiketi alana göre değişiyor (Faz 8 / B5). Önceden
    # `f"urun: {o.sku_adi}"` yazılıydı ve finans kararı geldiği anda
    # `AttributeError` veriyordu — istem hiç kurulamıyor, gerekçe şablona
    # düşüyordu. Model finansı görmemesinin sebebi eğitim değil, buydu.
    #
    # ⚠️ Stok tarafında etiket **birebir korunuyor** (`urun:`). Eğitilmiş
    # kipin istemi eğitimdekiyle aynı olmak zorunda; bir kelime değişse
    # model tanımadığı bir girdi görür (bkz. modül üstündeki uyarı ve
    # `OLCUMLER.md`'deki 4./5. tur vakası). Finans için `musteri:`
    # kullanmak yeni bir biçim değil, olmayan bir biçimin ilki.
    etiket = "musteri" if aday.alan is Alan.FINANS else "urun"
    satirlar = [
        "VERILER:",
        f"{etiket}: {o.gorunen_ad}",
        f"karar: {aday.tip.value}",
    ]

    # Metin alanları (tedarikçi adı gibi) sayılardan ÖNCE — hedef metinlerde
    # de bu sırada geçiyorlar ve model cümleyi bu akışla kuruyor.
    for alan, etiket in _EGITILMIS_METIN_ALANLARI.get(aday.tip, ()):
        deger = getattr(o, alan, None)
        if isinstance(deger, str) and deger:
            satirlar.append(f"{etiket}: {deger}")

    for etiket, deger in egitilmis_sayi_etiketleri(aday):
        satirlar.append(f"{etiket}: {_tr_sayi(deger)}")

    return "\n".join(satirlar) + "\n\nGEREKCE:"


def egitilmis_istem_kur(aday: DecisionCandidate) -> str:
    """Eğitilmiş modelin beklediği gerekçe istemi.

    Taban kipten **üç farkı** var, üçü de bilinçli:

    1. **Ürün adı VAR.** B2.4'te adı çıkarmıştım çünkü taban model bozuyordu
       (`Astar Boya` → *starboy*). Ama eğitim verisindeki gerekçelerin
       %100'ünde ad geçiyor; isteme koymazsak model *yoktan ad uydurmayı*
       öğrenmiş olur. B3.1'de bu karara varıldı.
    2. **Kurallar ve few-shot örnek YOK.** Davranış ağırlıklara işlendi.
    3. **Alan listesi karar tipine göre değişir** — hedef metnin kullandığı
       her sayı istemde olsun diye. (Önceki sürüm tipten bağımsız 5 sabit
       alan veriyordu; 2. turun kök nedeni buydu.)

    Bu fonksiyon "daha iyi bir istem" yazmaya çalışmaz; **eğitimdekini
    tekrarlar.** İyileştirme yapılacaksa eğitim verisiyle birlikte yapılmalı —
    artık ikisi de `egitilmis_istem_govdesi`'nden beslendiği için bu
    otomatik.

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
    return f"{GOREV_ETIKETI_GEREKCE}\n{egitilmis_istem_govdesi(aday)}"


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
        # ⚠️ Eğitilmiş kipte yeniden denemeyi ANLAMLI kılan tek şey bu.
        #
        # Taban kipte guard reddedince isteme "şu sayıları kullanma" uyarısı
        # ekleniyor ve ikinci deneme birinciden farklı oluyor. Eğitilmiş kipte
        # böyle bir satır eğitimde hiç geçmedi; eklemek modeli tanımadığı bir
        # girdiye sokar.
        #
        # Sonuç: istem aynı, sıcaklık 0 ise çıktı da **birebir aynı** olur ve
        # ikinci deneme boşa gider — bir model çağrısı, hiçbir kazanç.
        #
        # Çözüm istemi değil ÜRETİMİ değiştirmek: yeniden denemede sıcaklığı
        # yükseltmek. Model aynı istemi görür ama farklı bir yol seçer.
        yeniden = bool(onceki_red)
        etkin_sicaklik = sicaklik
        if egitilmis and yeniden:
            etkin_sicaklik = max(YENIDEN_DENEME_SICAKLIGI, sicaklik or 0.0)

        # Tohum da değişmeli: sıcaklık yükselse bile aynı tohum aynı
        # örneklemeyi verir, yani yine aynı cümle çıkardı.
        etkin_tohum = (tohum + 1) if (egitilmis and yeniden and tohum is not None) else tohum

        if egitilmis:
            # ⭐ EĞİTİLMİŞ KİPTE JSON ŞEMASI KULLANILMAZ.
            #
            # Şema (`GerekceCiktisi`) B2.1'de TABAN model için konmuştu: düz
            # metin istendiğinde taban model girdiyi liste hâlinde geri yazıp
            # başına başlık ekliyordu. Orada hâlâ gerekli.
            #
            # Ama eğitilmiş modelde şema **zarar veriyor**, çünkü eğitim ile
            # çalışma zamanı biçimi uyuşmuyor:
            #
            #     egitimde hedef  :  Porselen Karo - Vitra urununun 97 gun...
            #     calisma zamani  :  {"gerekce": "..."}   <- HIC GORULMEDI
            #
            # Model `{"gerekce": ...}` sarmalayıcısını eğitimde hiç görmedi;
            # Ollama'nın grammar kısıtı onu tanımadığı bir kalıba sokuyor.
            #
            # ⚠️ Ölçüldü (2026-08-08, aynı 20 karar, tek değişken şema):
            #
            #     tur5  semali  ->   7/20 kabul      tur3  semali  -> 20/20
            #     tur5  semasiz -> *20/20* kabul     tur3  semasiz -> 20/20
            #
            # Yani şema, 4. ve 5. turun "gerekçe tarafını bozduğu" sonucunun
            # tek sebebiydi. Model bozuk değildi, kısıt bozuktu. Kaldırmak
            # tur5'i kurtarıyor ve tur3'e hiç dokunmuyor.
            #
            # Biçim güvencesi kaybolmuyor: guard metni zaten doğruluyor
            # (sayı + dil), `ilk_cumleleri_al` fazla cümleyi kırpıyor ve
            # geçmezse şablona düşülüyor.
            ham = istemci.uret(
                egitilmis_istem_kur(aday),
                max_token=GEREKCE_MAX_TOKEN,
                sicaklik=etkin_sicaklik,
                tohum=etkin_tohum,
            ).metin
        else:
            sonuc = yapilandirilmis_uret(
                istemci,
                GerekceCiktisi,
                istem_kur(aday, onceki_red),
                sistem=sistem_istemi(aday.tip),
                max_token=GEREKCE_MAX_TOKEN,
                sicaklik=etkin_sicaklik,
                tohum=etkin_tohum,
            )
            ham = sonuc.deger.gerekce

        return ilk_cumleleri_al(ham.strip())

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
