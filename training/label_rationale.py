"""Buyuk LLM ile Turkce gerekce yazimi + guard ile dogrulama.

Sahip: Kisi A · Faz 3 A3.4

    Guard'i EGITIM VERISINDE de kullan - kirliligi kaynaginda kes.

Girdi: `training/build_dataset.py` (A3.1) çıktısı `data/egitim/karar_noktalari.jsonl`
(~50.050 satır — özellikler + kural motorunun ürettiği karar). Çıktı: her satır
için Türkçe bir gerekçe metni + guard sonucu, `data/egitim/gerekceler.jsonl`.

## Neden satır başına tek LLM çağrısı YAPILMIYOR

A3.3'te (bkz. aciklama.md) 24.999 satırın her birini ayrı ayrı büyük modele
göndermek 100 satırda 357 saniye tuttu — tam veri seti ~25 saate karşılık
geliyordu. Aynı hata burada tekrarlanmasın diye aynı çözüm uygulanıyor:
`decide.py::ozellikten_karar_uret` her karar tipi için SABİT bir kural
kodu dizisi üretir (bkz. o dosya) — yani 50.050 satır gerçekte yalnızca
birkaç "ŞEKİL"in (karar_tipi + tetiklenen kural kodları) tekrarıdır. Büyük
LLM'e şekil başına birkaç kez sorulup yer tutucu (placeholder) token'lı
birkaç cümle varyantı istenir; gerçek sayılar bu varyantlara YERELDE,
GPU'suz basılır. Onlarca LLM çağrısı, elli bine değil.

Yeni bir şekil (rules.py'ye yeni bir kural kodu eklenmesi gibi) veri
setinde daha önce görülmemişse, o şekle düşen satırlar tek-satır yoluna
(`_tek_satir_gerekce_uret`) düşer — daha yavaş ama doğru, ve aynı
guard/fallback zincirinden geçer.

## Colab yolu (RAM/GPU yetmiyorsa)

`qwen2.5:7b-instruct` gibi gerçekten "büyük" bir model yerel makineye (16 GB
RAM, GPU'suz) sığmayabilir. Şekil-bazlı tasarım tam olarak bunu çözmek için
uygun: yalnızca birkaç şekil olduğu için, tüm 50.050 satırı değil, yalnızca
şekil başına bir prompt'u Colab'a taşımak yeterli — A3.3'teki
`paraphrase_colab.ipynb` ile birebir aynı desen.

Akış:
1. Yerelde: `--sekil-ihrac-et data/egitim/sekil_promptlari.jsonl` ile
   birkaç satırlık bir prompt listesi çıkar (`sekil_promptlarini_ihrac_et`).
2. Bu dosyayı Colab'a yükle, `label_rationale_colab.ipynb`'de (T4 GPU,
   Qwen2.5-7B-Instruct 4-bit) her prompt için varyantları üret, sonucu
   `sekil_varyantlari.jsonl` olarak indir.
3. Yerelde, GPU'suz: `--varyant-girdi data/egitim/sekil_varyantlari.jsonl`
   ile tam veri setini çalıştır — gerçek sayılar buraya YEREL olarak basılır,
   Ollama'ya hiç ihtiyaç yok.

## Guard hakkında bir not

`app/llm/guard.py` (Kişi B, Faz 2 B2.5) henüz YER TUTUCU — yazılmadı. Bu
modül kendi sayı-doğrulama eşleniğini taşıyor (`_metni_dogrula`), çünkü
A3.4'ün üretmesi gereken veri, guard'ın var olmasını bekleyemez. Mantık
`DecisionCandidate.izinli_sayilar()` ile birebir aynı kaynağı kullanıyor.
Kişi B gerçek guard'ı yazınca ikisi hizalanmalı (muhtemelen bu dosya
oradan import edecek şekilde) — o zamana kadar burası kendi ayaklarının
üstünde duruyor.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from app.contracts import (
    Alan,
    DecisionCandidate,
    FiredRule,
    GuardSonucu,
    KararTipi,
    StockFeatures,
)
from app.llm.explain import sablon_gerekce

VARSAYILAN_GIRDI = Path("data/egitim/karar_noktalari.jsonl")
VARSAYILAN_CIKTI = Path("data/egitim/gerekceler.jsonl")
VARSAYILAN_MODEL = "qwen2.5:7b-instruct"
"""A3.3'teki gibi Qwen2.5 ailesi tercih edilir — ama önce `ollama pull` ile
çekilmiş olması gerekir. Yerelde yalnızca `llama3.2:1b` varsa `--model` ile
o verilebilir; kalite düşerse şablona düşme oranı artar, bu da raporlanır."""
VARSAYILAN_OLLAMA_URL = "http://127.0.0.1:11434"
SEKIL_BASINA_VARYANT_HEDEFI = 6
RED_ORANI_UYARI_ESIGI = 0.15
"""Görev tanımı: %15'i geçerse prompt düzeltilir, veri kabul edilmez."""

# ---------------------------------------------------------------------------
# Sayı çıkarma + doğrulama — yerel guard eşleniği
# ---------------------------------------------------------------------------

_SAYI_DESENI = re.compile(r"\d[\d.,]*\d|\d")


def _sayiyi_normalize_et(token: str) -> float | None:
    """'1.200' -> 1200.0 · '94,5' -> 94.5 (Türkçe biçim: nokta binlik, virgül ondalık)."""
    t = token.strip().strip(".,")
    if not t:
        return None
    if "," in t:
        tam, ondalik = t.rsplit(",", 1)
        tam = tam.replace(".", "")
        aday = f"{tam}.{ondalik}" if tam else f"0.{ondalik}"
    else:
        aday = t.replace(".", "")
    try:
        return float(aday)
    except ValueError:
        return None


def _metni_maskele(metin: str, satir: dict[str, Any]) -> str:
    """Ad/kod alanlarındaki rakamları (ör. tedarikçi kodu 'T-014') sayı sanmayı önler.

    Bu alanlar guard'ın izinli sayılar kümesinde yer almaz (string'dir) ama
    içlerinde rakam geçebilir — maskelenmezse guard onları "uydurma sayı"
    sanıp geçerli bir metni reddeder.
    """
    o = satir["ozellikler"]
    for deger in (o.get("sku_adi"), o.get("tedarikci_adi"), o.get("sku_id"), o.get("tedarikci_id")):
        if isinstance(deger, str) and deger:
            metin = metin.replace(deger, " ")
    return metin


def _sayilari_cikar(metin: str) -> list[float]:
    adaylar = (_sayiyi_normalize_et(tok) for tok in _SAYI_DESENI.findall(metin))
    return [s for s in adaylar if s is not None]


def _metni_dogrula(
    metin: str, satir: dict[str, Any], tolerans: float = 0.01
) -> tuple[bool, list[float]]:
    """Metindeki her sayı `izinli_sayilar` kümesinde mi? Değilse reddedilenleri döner."""
    izinli = satir["izinli_sayilar"]
    maskeli = _metni_maskele(metin, satir)
    reddedilenler = []
    for sayi in _sayilari_cikar(maskeli):
        if not any(abs(sayi - izin) <= tolerans for izin in izinli):
            reddedilenler.append(sayi)
    return (len(reddedilenler) == 0, reddedilenler)


def _tr_bicimli_sayi(deger: float) -> str:
    """1200.0 -> '1.200' · 4.75 -> '4,75' — `app/llm/explain.py::_tr_sayi` ile aynı biçim.

    Ayrı tutuluyor çünkü o fonksiyon `app/llm/` altında (Kişi B'nin alanı);
    burada birebir aynı mantığın yerel bir kopyası var.
    """
    if float(deger).is_integer():
        return f"{int(deger):,}".replace(",", ".")
    return f"{deger:,.2f}".replace(",", "~").replace(".", ",").replace("~", ".")


# ---------------------------------------------------------------------------
# Karar noktasını DecisionCandidate'e geri kurma (şablon fallback için)
# ---------------------------------------------------------------------------


def _karar_adayi_olustur(satir: dict[str, Any]) -> DecisionCandidate:
    return DecisionCandidate(
        alan=Alan.STOK,
        tip=KararTipi(satir["karar_tipi"]),
        aksiyon=satir["aksiyon"],
        tahmini_tutar_tl=satir["tahmini_tutar_tl"],
        guven=satir["guven"],
        tetiklenen_kurallar=[FiredRule.model_validate(k) for k in satir["tetiklenen_kurallar"]],
        ozellikler=StockFeatures.model_validate(satir["ozellikler"]),
    )


# ---------------------------------------------------------------------------
# Şekil (shape) gruplama — A3.3'teki "şablon" fikrinin karar-noktası karşılığı
# ---------------------------------------------------------------------------


def _sekil_anahtari(satir: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    kodlar = tuple(sorted(k["kod"] for k in satir["tetiklenen_kurallar"]))
    return (satir["karar_tipi"], kodlar)


# Karar tipine göre hangi yer tutucular zorunlu + nereden okunur.
# (kaynak, anahtar) -> "ozellik" ise ozellikler dict'inden, "aksiyon" ise
# aksiyon dict'inden, "kural:KOD" ise o kuralın degerler sözlüğünden, "hesap"
# ise asagidaki _hesapla ile turetilir.
_SLOT_TANIMLARI: dict[str, list[tuple[str, str, str]]] = {
    KararTipi.STOK_AKSIYON_YOK.value: [
        ("SKU_ADI", "ozellik", "sku_adi"),
        ("KULLANILABILIR_STOK", "hesap", "kullanilabilir_stok"),
        ("ROP", "kural:ROP_USTUNDE", "rop"),
    ],
    KararTipi.STOK_SIPARIS.value: [
        ("SKU_ADI", "ozellik", "sku_adi"),
        ("ORT_GUNLUK_TALEP", "ozellik", "ort_gunluk_talep"),
        ("TEDARIK_SURESI_GUN", "ozellik", "tedarik_suresi_gun"),
        ("KULLANILABILIR_STOK", "hesap", "kullanilabilir_stok"),
        ("SIPARIS_MIKTARI", "aksiyon", "siparis_miktari"),
        ("TEDARIKCI_ADI", "ozellik", "tedarikci_adi"),
        ("TEDARIKCI_SKORU", "ozellik", "tedarikci_skoru"),
    ],
    KararTipi.STOK_TASFIYE.value: [
        ("SKU_ADI", "ozellik", "sku_adi"),
        ("SON_HAREKET_GUN_ONCE", "ozellik", "son_hareket_gun_once"),
        ("ELDEKI_STOK", "ozellik", "eldeki_stok"),
        ("ISKONTO_YUZDE", "hesap", "iskonto_yuzde"),
        ("BAGLI_SERMAYE_TL", "kural:OLU_STOK_TESPIT_EDILDI", "bagli_sermaye_tl"),
    ],
    # --- Finans (Faz 8) ---
    #
    # ⚠️ Slot adları stok tarafındakilerle kasıtlı olarak ÖRTÜŞMÜYOR. Model
    # tek bir ağırlık kümesinde iki alanı birden öğreniyor; aynı slot adı
    # farklı anlamlara gelirse (ör. "TUTAR") cümleler karışır. Her alan kendi
    # sözlüğünü taşıyor.
    KararTipi.FINANS_TAHSILAT_TAKIBI.value: [
        ("MUSTERI_ADI", "ozellik", "musteri_adi"),
        ("VADESI_GECEN_TL", "ozellik", "vadesi_gecen_tl"),
        ("EN_ESKI_GECIKME_GUN", "ozellik", "en_eski_gecikme_gun"),
        ("ORT_ODEME_GECIKMESI_GUN", "ozellik", "ort_odeme_gecikmesi_gun"),
        ("TAKIP_ESIGI_GUN", "kural:TAKIP_ESIGI_HESAPLANDI", "takip_esigi_gun"),
    ],
    KararTipi.FINANS_KARSILIK_AYIR.value: [
        ("MUSTERI_ADI", "ozellik", "musteri_adi"),
        ("EN_ESKI_GECIKME_GUN", "ozellik", "en_eski_gecikme_gun"),
        ("VADESI_GECEN_TL", "ozellik", "vadesi_gecen_tl"),
        ("KARSILIK_YUZDE", "hesap", "karsilik_yuzde"),
        ("KARSILIK_TUTARI_TL", "kural:KARSILIK_GEREKLI", "karsilik_tutari_tl"),
    ],
    KararTipi.FINANS_KREDI_LIMITI_DUSUR.value: [
        ("MUSTERI_ADI", "ozellik", "musteri_adi"),
        ("MUSTERI_RISK_SKORU", "kural:MUSTERI_RISKI_YUKSEK", "musteri_risk_skoru"),
        ("TAHSILAT_YUZDE", "hesap", "tahsilat_yuzde"),
        ("KREDI_LIMITI_TL", "ozellik", "kredi_limiti_tl"),
        ("ONERILEN_KREDI_LIMITI_TL", "aksiyon", "onerilen_kredi_limiti_tl"),
    ],
    KararTipi.FINANS_AKSIYON_YOK.value: [
        ("MUSTERI_ADI", "ozellik", "musteri_adi"),
        ("EN_ESKI_GECIKME_GUN", "ozellik", "en_eski_gecikme_gun"),
        ("TAKIP_ESIGI_GUN", "kural:TAKIP_ESIGI_HESAPLANDI", "takip_esigi_gun"),
    ],
}


KARAR_TIPI_ACIKLAMASI: dict[str, str] = {
    KararTipi.STOK_AKSIYON_YOK.value: (
        "Stok YETERLİ — kullanılabilir stok yeniden sipariş noktasının ÜSTÜNDE, "
        "HİÇBİR aksiyon önerilmiyor. Cümle bunu net söylemeli: sipariş vermeye "
        "gerek YOK, durum iyi."
    ),
    KararTipi.STOK_SIPARIS.value: (
        "Stok YETERSİZ — kullanılabilir stok yeniden sipariş noktasının ALTINA "
        "düşmüş, YENİ SİPARİŞ verilmesi gerekiyor ve miktar/tedarikçi zaten hesaplanmış."
    ),
    KararTipi.STOK_TASFIYE.value: (
        "Ürün uzun süredir HAREKETSİZ (ölü stok) — TASFİYE/İSKONTO öneriliyor, yeni sipariş DEĞİL."
    ),
    KararTipi.FINANS_TAHSILAT_TAKIBI.value: (
        "Müşteriden ALACAK var ve gecikme ya bu müşterinin OLAĞAN aralığının "
        "ÜSTÜNDE ya da tutar takip maliyetini karşılayacak kadar BÜYÜK — "
        "TAHSİLAT TAKİBİ (arama/yazışma) öneriliyor. Zarar yazmak DEĞİL."
    ),
    KararTipi.FINANS_KARSILIK_AYIR.value: (
        "Alacak, tahsil edilemeyecek kadar ESKİ — muhasebe kaydı olarak "
        "ŞÜPHELİ ALACAK KARŞILIĞI ayrılması öneriliyor. ⚠️ Bu, müşteriyi "
        "aramayı BIRAKMAK anlamına GELMEZ; ayrı bir takip kararı da üretilmiş "
        "olabilir."
    ),
    KararTipi.FINANS_KREDI_LIMITI_DUSUR.value: (
        "Müşterinin ödeme davranışı RİSKLİ — GELECEK satışları sınırlamak için "
        "KREDİ LİMİTİNİN DÜŞÜRÜLMESİ öneriliyor. Mevcut alacağın tahsili ayrı "
        "bir karar."
    ),
    KararTipi.FINANS_AKSIYON_YOK.value: (
        "Gecikme bu müşteri için OLAĞAN aralıkta — HİÇBİR aksiyon önerilmiyor. "
        "Cümle bunu net söylemeli: aramaya gerek YOK."
    ),
}

SLOT_ACIKLAMALARI: dict[str, str] = {
    "SKU_ADI": "ürün adı (metin, sayı değil)",
    "TEDARIKCI_ADI": "tedarikçi adı (metin, sayı değil)",
    "KULLANILABILIR_STOK": "kullanılabilir stok miktarı, adet (sayı)",
    "ROP": "yeniden sipariş noktası, adet (sayı)",
    "ORT_GUNLUK_TALEP": "günlük ortalama talep, adet (sayı)",
    "TEDARIK_SURESI_GUN": "tedarikçiden mal gelme süresi, gün (sayı)",
    "SIPARIS_MIKTARI": "önerilen sipariş miktarı, adet (sayı)",
    "TEDARIKCI_SKORU": "tedarikçi performans skoru, 0-100 arası (sayı)",
    "SON_HAREKET_GUN_ONCE": "kaç GÜNDÜR hareket görmediği — bir TARİH DEĞİL, bir gün SAYISI",
    "ELDEKI_STOK": "elde bulunan toplam stok, adet (sayı)",
    "ISKONTO_YUZDE": "önerilen iskonto oranı, yüzde (sayı)",
    "BAGLI_SERMAYE_TL": "bu stoka bağlı sermaye, Türk Lirası (sayı)",
    # Finans
    "MUSTERI_ADI": "müşteri adı (metin, sayı değil)",
    "VADESI_GECEN_TL": "vadesi geçmiş alacak tutarı, Türk Lirası (sayı)",
    "EN_ESKI_GECIKME_GUN": (
        "en eski faturanın kaç GÜNDÜR geciktiği — bir TARİH DEĞİL, gün SAYISI"
    ),
    "ORT_ODEME_GECIKMESI_GUN": "bu müşterinin ortalama ödeme gecikmesi, gün (sayı)",
    "TAKIP_ESIGI_GUN": (
        "bu müşteri için hesaplanan takip eşiği, gün (sayı) — bunun üstü olağandışı"
    ),
    "KARSILIK_YUZDE": "önerilen şüpheli alacak karşılığı oranı, yüzde (sayı)",
    "KARSILIK_TUTARI_TL": "ayrılması önerilen karşılık tutarı, Türk Lirası (sayı)",
    "MUSTERI_RISK_SKORU": "müşteri risk skoru, 0-100 arası — YÜKSEK = güvenilir (sayı)",
    "TAHSILAT_YUZDE": "geçmişte tahsil edilen alacak oranı, yüzde (sayı)",
    "KREDI_LIMITI_TL": "mevcut kredi limiti, Türk Lirası (sayı)",
    "ONERILEN_KREDI_LIMITI_TL": "önerilen yeni kredi limiti, Türk Lirası (sayı)",
}


def _hesapla(anahtar: str, satir: dict[str, Any]) -> float:
    o = satir["ozellikler"]
    if anahtar == "kullanilabilir_stok":
        return float(o["eldeki_stok"] - o["rezerve_stok"])
    if anahtar == "iskonto_yuzde":
        return float(satir["aksiyon"]["onerilen_iskonto_orani"]) * 100.0
    # ⚠️ Oranlar yüzdeye burada çevriliyor. Guard'ın izinli kümesi
    # `ORAN_ALANLARI` sayesinde x100 karşılığını zaten kabul ediyor
    # (bkz. `app/contracts.py`); ikisi ayrışırsa gerekçe reddedilir.
    if anahtar == "karsilik_yuzde":
        return float(satir["aksiyon"]["onerilen_karsilik_orani"]) * 100.0
    if anahtar == "tahsilat_yuzde":
        return float(satir["ozellikler"]["tahsilat_orani"]) * 100.0
    raise ValueError(f"Bilinmeyen hesap anahtarı: {anahtar}")


def _slotlari_cikar(satir: dict[str, Any]) -> dict[str, str | float] | None:
    """Karar tipi tanınmıyorsa (ör. henüz decide.py'de üretilmeyen TEDARIKCI_DEGISIM) None döner."""
    tanimlar = _SLOT_TANIMLARI.get(satir["karar_tipi"])
    if tanimlar is None:
        return None
    slotlar: dict[str, str | float] = {}
    for token, kaynak, anahtar in tanimlar:
        if kaynak == "ozellik":
            slotlar[token] = satir["ozellikler"][anahtar]
        elif kaynak == "aksiyon":
            slotlar[token] = satir["aksiyon"][anahtar]
        elif kaynak == "hesap":
            slotlar[token] = _hesapla(anahtar, satir)
        elif kaynak.startswith("kural:"):
            kod = kaynak.split(":", 1)[1]
            kural = next((k for k in satir["tetiklenen_kurallar"] if k["kod"] == kod), None)
            slotlar[token] = kural["degerler"][anahtar] if kural else 0.0
        else:  # pragma: no cover - _SLOT_TANIMLARI kodlama hatası
            raise ValueError(f"Bilinmeyen slot kaynağı: {kaynak}")
    return slotlar


def _sablonu_doldur(varyant: str, slotlar: dict[str, str | float]) -> str:
    metin = varyant
    for token, deger in slotlar.items():
        yerine = deger if isinstance(deger, str) else _tr_bicimli_sayi(float(deger))
        metin = metin.replace("{" + token + "}", yerine)
    return metin


# ---------------------------------------------------------------------------
# Ollama çağrısı
# ---------------------------------------------------------------------------


def _ollama_uret(
    prompt: str, model: str, ollama_url: str, sicaklik: float = 0.7, timeout: float = 120.0
) -> str:
    yanit = httpx.post(
        f"{ollama_url}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": sicaklik},
        },
        timeout=timeout,
    )
    yanit.raise_for_status()
    return yanit.json()["response"].strip()


def _sekil_prompt_olustur(karar_tipi: str, slot_tokenlari: list[str], varyant_sayisi: int) -> str:
    slot_aciklama_satirlari = "\n".join(
        f"- {{{t}}}: {SLOT_ACIKLAMALARI.get(t, 'açıklama yok')}" for t in slot_tokenlari
    )
    token_listesi = ", ".join("{" + t + "}" for t in slot_tokenlari)
    durum_aciklamasi = KARAR_TIPI_ACIKLAMASI.get(karar_tipi, karar_tipi)
    # ⚠️ Rol tanımı alana göre değişiyor (Faz 8). Finans şekillerinde de
    # "stok yönetimi asistanısın" yazıyordu; büyük modele yanlış bağlam
    # vermek, üretilen cümlelerin tahsilat yerine stok diliyle yazılmasına
    # yol açardı — ve o cümleler eğitim verisi olarak kalıcılaşırdı.
    rol = "alacak ve tahsilat yönetimi" if karar_tipi.startswith("finans.") else "stok yönetimi"
    return (
        f"Sen bir ERP {rol} asistanısın. Aşağıdaki DURUM için "
        f"{varyant_sayisi} FARKLI, doğal, profesyonel Türkçe gerekçe cümlesi yaz.\n\n"
        f"DURUM: {durum_aciklamasi}\n\n"
        f"Cümlede AYNEN şu {len(slot_tokenlari)} yer tutucunun HEPSİ geçmeli "
        f"(harfi harfine, süslü parantezli, tek birini bile atlamadan):\n"
        f"{slot_aciklama_satirlari}\n\n"
        "Kurallar:\n"
        "- Yukarıdaki DURUM açıklamasıyla ÇELİŞMEYEN bir cümle yaz — anlamı tersine çevirme.\n"
        f"- Her varyantta bu {len(slot_tokenlari)} yer tutucunun HEPSİ kullanılmalı, "
        "hiçbiri atlanmamalı.\n"
        "- Yer tutucuların hiçbirini çevirme, değiştirme, kısaltma.\n"
        "- Yer tutucular dışında HİÇBİR sayı, yüzde veya rakam yazma.\n"
        "- Yalnızca Türkçe yaz. Başka hiçbir dilde (Çince, İngilizce vb.) TEK KELİME bile yazma.\n"
        "- Her varyant 1-2 cümle olsun, birbirinden üslup olarak farklı olsun.\n"
        "- Yalnızca numaralı liste döndür, başka açıklama yazma.\n"
        f"\nToken listesi (kontrol için): {token_listesi}"
    )


_YANKI_IFADELERI = (
    "yer tutucu",
    "harfi harfine",
    "süslü parantez",
    "aynen şu",
    "aynen ",
    "numaralı liste",
    "karar türü",
    "varyant",
    "format",
)
"""Zayıf modeller (ör. küçük yerel model) talimatı cevap sanıp aynen tekrarlayabilir
— gerçek bir gerekçe cümlesinde bu talimat kelimeleri asla geçmez. Gerçek veride
(llama3.2:1b ile duman testinde) tam olarak bu bulundu: model 'Cümlede AYNEN şu
yer tutucular geçmeli...' talimatını kendi cevabıymış gibi geri döndürdü ve bu,
yalnızca token varlığına bakan ilk kontrolden (yanlışlıkla) geçti."""

_CJK_DESENI = re.compile(r"[一-鿿぀-ヿ가-힯]")
"""Qwen2.5 ailesinde bilinen bir sorun (bkz. A3.3 / paraphrase_colab.ipynb):
model bazen Türkçe cümlenin ortasına Çince/Japonca/Korece karakter sızdırıyor.
Gerçek Colab testinde (`stok.siparis` şekli, 7B model) tam olarak bu görüldü —
varyantların çoğu '送货周期下，现有库存不足' gibi karışık metin döndürdü."""


_UZUNLUK_TABANI = 150
_TOKEN_BASINA_UZUNLUK_PAYI = 45
"""Sabit bir üst sınır (ör. 300) çok token'lı şekilleri haksız yere eler:
gerçek Colab koşusunda `stok.siparis` (7 yer tutucu) şeklinin 3 geçerli
varyantı, hepsi doğru ve eksiksiz olduğu hâlde, 300 karakterlik sabit sınırı
aştığı için (338-362 karakter) reddedildi. Uzunluk sınırı artık yer tutucu
sayısına göre ölçekleniyor — amaç hâlâ aynı: gerçek bir gerekçe cümlesinin
alamayacağı kadar uzun (talimat yankısı, saçmalama) metni eleme."""


def _varyantlari_ayikla(yanit: str, slot_tokenlari: list[str]) -> list[str]:
    """LLM'in numaralı liste yanıtını satırlara böler, kullanılamaz satırları eler."""
    uzunluk_siniri = _UZUNLUK_TABANI + _TOKEN_BASINA_UZUNLUK_PAYI * len(slot_tokenlari)
    varyantlar = []
    for satir in yanit.splitlines():
        temiz = re.sub(r"^\s*\d+[.)]\s*", "", satir).strip().strip("-\"'").strip()
        if not temiz or len(temiz) > uzunluk_siniri:
            continue
        if any(ifade in temiz.lower() for ifade in _YANKI_IFADELERI):
            continue
        if _CJK_DESENI.search(temiz):
            continue
        if all("{" + t + "}" in temiz for t in slot_tokenlari):
            varyantlar.append(temiz)
    return varyantlar


def _sekil_icin_varyant_uret(
    karar_tipi: str, slot_tokenlari: list[str], model: str, ollama_url: str, varyant_sayisi: int
) -> list[str]:
    prompt = _sekil_prompt_olustur(karar_tipi, slot_tokenlari, varyant_sayisi)
    try:
        yanit = _ollama_uret(prompt, model, ollama_url)
    except httpx.HTTPError:
        return []
    return _varyantlari_ayikla(yanit, slot_tokenlari)


SEKIL_ID_AYIRICI = "::"


def _sekil_id_yaz(sekil: tuple[str, tuple[str, ...]]) -> str:
    karar_tipi, kodlar = sekil
    return f"{karar_tipi}{SEKIL_ID_AYIRICI}{'+'.join(kodlar)}"


def _sekil_id_oku(sekil_id: str) -> tuple[str, tuple[str, ...]]:
    karar_tipi, kodlar_metni = sekil_id.split(SEKIL_ID_AYIRICI, 1)
    kodlar = tuple(kodlar_metni.split("+")) if kodlar_metni else ()
    return (karar_tipi, kodlar)


def sekil_promptlarini_ihrac_et(satirlar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Colab'a taşınacak, şekil başına TEK prompt'u çıkarır.

    Bilinmeyen (tanınmayan) karar tipleri burada yok — onlar zaten şablona
    düşer, Colab'a taşınmaya değmez. Çıktı çok küçüktür (birkaç satır),
    büyük veri setinin kendisi hiç Colab'a gitmez.
    """
    gorulen: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for satir in satirlar:
        sekil = _sekil_anahtari(satir)
        if sekil in gorulen:
            continue
        slotlar = _slotlari_cikar(satir)
        if slotlar is None:
            continue
        karar_tipi, _ = sekil
        gorulen[sekil] = {
            "sekil_id": _sekil_id_yaz(sekil),
            "karar_tipi": karar_tipi,
            "slot_tokenlari": list(slotlar.keys()),
            "prompt": _sekil_prompt_olustur(
                karar_tipi, list(slotlar.keys()), SEKIL_BASINA_VARYANT_HEDEFI
            ),
        }
    return list(gorulen.values())


def onceden_uretilmis_varyantlari_oku(
    yol: Path,
) -> dict[tuple[str, tuple[str, ...]], list[str]]:
    """Colab'dan dönen `sekil_varyantlari.jsonl`'ü okur.

    Beklenen kolonlar: `sekil_id`, ve ham LLM yanıtını taşıyan `yanit`
    (satır satır varyant, `_varyantlari_ayikla` ile aynı ayrıştırma burada
    da uygulanır — Colab'ın kendisi format/yankı kontrolü yapmaz, o
    sorumluluk burada, yerelde kalır).
    """
    havuz: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for kayit in _jsonl_oku(yol):
        sekil = _sekil_id_oku(kayit["sekil_id"])
        slot_tokenlari = kayit.get("slot_tokenlari", [])
        havuz[sekil] = _varyantlari_ayikla(kayit["yanit"], slot_tokenlari)
    return havuz


# ---------------------------------------------------------------------------
# Bilinmeyen şekil için satır başına yol (yavaş ama doğru, aynı guard zinciri)
# ---------------------------------------------------------------------------


def _tek_satir_prompt_olustur(satir: dict[str, Any]) -> str:
    aday = _karar_adayi_olustur(satir)
    kurallar_metni = "\n".join(
        f"- {k.kod}: {k.aciklama} ({k.degerler})" for k in aday.tetiklenen_kurallar
    )
    finans_mi = aday.tip.value.startswith("finans.")
    rol = "alacak ve tahsilat yönetimi" if finans_mi else "stok yönetimi"
    # ⚠️ `sku_adi` yerine `gorunen_ad`: sözleşmenin alan-bağımsız cevabı.
    # Doğrudan `sku_adi` okumak finans kararında `AttributeError` verirdi —
    # `app/llm/explain.py`'de aynı kusurun üç örneği bulunmuştu (§18).
    kalem_etiketi = "Müşteri" if finans_mi else "Ürün"
    return (
        f"Sen bir ERP {rol} asistanısın. Aşağıdaki kural motoru çıktısını "
        "TEK bir doğal Türkçe gerekçe cümlesine dönüştür. Yalnızca aşağıda verilen "
        "sayıları kullan, yeni sayı UYDURMA.\n\n"
        f"{kalem_etiketi}: {aday.ozellikler.gorunen_ad}\n"
        f"Karar: {aday.tip.value}\n"
        f"Aksiyon: {aday.aksiyon}\n"
        f"Tetiklenen kurallar:\n{kurallar_metni}\n\n"
        "Yalnızca gerekçe cümlesini yaz, başka hiçbir şey ekleme."
    )


def _tek_satir_gerekce_uret(
    satir: dict[str, Any], model: str, ollama_url: str
) -> tuple[str, GuardSonucu, list[float]]:
    prompt = _tek_satir_prompt_olustur(satir)
    for deneme in range(2):
        try:
            metin = _ollama_uret(prompt, model, ollama_url)
        except httpx.HTTPError:
            break
        gecti, reddedilenler = _metni_dogrula(metin, satir)
        if gecti:
            sonuc = GuardSonucu.GECTI if deneme == 0 else GuardSonucu.YENIDEN_URETILDI
            return metin, sonuc, []
        prompt = (
            prompt
            + f"\n\nÖNCEKİ DENEMEN reddedildi çünkü şu sayılar kaynakta yok: {reddedilenler}. "
            "Yalnızca yukarıda verilen sayıları kullanarak yeniden yaz."
        )
    aday = _karar_adayi_olustur(satir)
    return sablon_gerekce(aday), GuardSonucu.SABLONA_DUSTU, reddedilenler


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------


def gerekceleri_uret(
    satirlar: list[dict[str, Any]],
    model: str = VARSAYILAN_MODEL,
    ollama_url: str = VARSAYILAN_OLLAMA_URL,
    varyant_sayisi: int = SEKIL_BASINA_VARYANT_HEDEFI,
    onceden_uretilmis_varyantlar: dict[tuple[str, tuple[str, ...]], list[str]] | None = None,
) -> list[dict[str, Any]]:
    """`onceden_uretilmis_varyantlar` verilirse (Colab çıktısı) o şekiller için
    Ollama'ya HİÇ gidilmez — yalnızca havuzda olmayan şekiller için (varsa)
    yerel Ollama denenir, o da yoksa güvenle şablona düşülür."""
    sekiller: dict[tuple[str, tuple[str, ...]], list[int]] = defaultdict(list)
    for i, satir in enumerate(satirlar):
        sekiller[_sekil_anahtari(satir)].append(i)

    # Şekil başına varyant havuzu — yalnızca tanınan (bkz. _SLOT_TANIMLARI) şekiller için.
    varyant_havuzu: dict[tuple[str, tuple[str, ...]], list[str]] = dict(
        onceden_uretilmis_varyantlar or {}
    )
    for sekil, indeksler in sekiller.items():
        if sekil in varyant_havuzu:
            continue
        karar_tipi, _ = sekil
        ornek_slotlar = _slotlari_cikar(satirlar[indeksler[0]])
        if ornek_slotlar is None:
            continue
        varyant_havuzu[sekil] = _sekil_icin_varyant_uret(
            karar_tipi, list(ornek_slotlar.keys()), model, ollama_url, varyant_sayisi
        )

    sonuclar: list[dict[str, Any]] = []
    for satir in satirlar:
        sekil = _sekil_anahtari(satir)
        slotlar = _slotlari_cikar(satir)
        varyantlar = varyant_havuzu.get(sekil) or [] if slotlar is not None else []

        metin: str | None = None
        guard_sonucu = GuardSonucu.SABLONA_DUSTU
        reddedilenler: list[float] = []

        for deneme_no, varyant in enumerate(varyantlar):
            aday_metin = _sablonu_doldur(varyant, slotlar)  # type: ignore[arg-type]
            gecti, red = _metni_dogrula(aday_metin, satir)
            if gecti:
                metin = aday_metin
                guard_sonucu = GuardSonucu.GECTI if deneme_no == 0 else GuardSonucu.YENIDEN_URETILDI
                break
            reddedilenler = red

        if metin is None:
            if slotlar is None:
                # Bilinmeyen karar tipi/şekil — yavaş ama doğru satır başına yol.
                metin, guard_sonucu, reddedilenler = _tek_satir_gerekce_uret(
                    satir, model, ollama_url
                )
            else:
                aday = _karar_adayi_olustur(satir)
                metin = sablon_gerekce(aday)
                guard_sonucu = GuardSonucu.SABLONA_DUSTU

        sonuclar.append(
            {
                "sku_id": satir["sku_id"],
                "tarih": satir["tarih"],
                "karar_tipi": satir["karar_tipi"],
                "metin": metin,
                "guard_sonucu": guard_sonucu.value,
                "model_adi": model if guard_sonucu != GuardSonucu.SABLONA_DUSTU else None,
                "reddedilen_sayilar": (
                    reddedilenler if guard_sonucu == GuardSonucu.SABLONA_DUSTU else []
                ),
            }
        )

    return sonuclar


def _jsonl_oku(yol: Path) -> list[dict[str, Any]]:
    with open(yol, encoding="utf-8") as f:
        return [json.loads(satir) for satir in f if satir.strip()]


def _jsonl_yaz(kayitlar: list[dict[str, Any]], yol: Path) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    with open(yol, "w", encoding="utf-8") as f:
        for kayit in kayitlar:
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")


def _cli() -> None:
    # Windows konsolu bazen cp1254/cp1252 gibi Türkçe olmayan bir kod sayfası
    # kullanıyor — Türkçe karakterler `print` sırasında UnicodeEncodeError
    # patlatıyor. Çıktı bir dosyaya değil terminale yazıldığı için burada,
    # tek seferlik, zararsız bir düzeltme yapılıyor.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ayristirici = argparse.ArgumentParser(description="Gerekçe etiketleme (A3.4)")
    ayristirici.add_argument("--girdi", type=str, default=str(VARSAYILAN_GIRDI))
    ayristirici.add_argument("--cikti", type=str, default=str(VARSAYILAN_CIKTI))
    ayristirici.add_argument("--model", type=str, default=VARSAYILAN_MODEL)
    ayristirici.add_argument("--ollama-url", type=str, default=VARSAYILAN_OLLAMA_URL)
    ayristirici.add_argument("--varyant-sayisi", type=int, default=SEKIL_BASINA_VARYANT_HEDEFI)
    ayristirici.add_argument(
        "--limit", type=int, default=None, help="Yalnızca ilk N satırı işler (duman testi için)"
    )
    ayristirici.add_argument(
        "--sekil-ihrac-et",
        type=str,
        default=None,
        help=(
            "Verilirse Ollama'ya hiç gitmez — Colab'a taşınacak şekil-başına "
            "prompt listesini bu yola yazıp çıkar (bkz. modül docstring'i, 'Colab yolu')"
        ),
    )
    ayristirici.add_argument(
        "--varyant-girdi",
        type=str,
        default=None,
        help="Colab'dan dönen sekil_varyantlari.jsonl — verilirse o şekiller için Ollama atlanır",
    )
    args = ayristirici.parse_args()

    satirlar = _jsonl_oku(Path(args.girdi))
    if args.limit:
        satirlar = satirlar[: args.limit]

    if args.sekil_ihrac_et:
        promptlar = sekil_promptlarini_ihrac_et(satirlar)
        _jsonl_yaz(promptlar, Path(args.sekil_ihrac_et))
        print(f"[A3.4] Toplam benzersiz şekil: {len(promptlar)}")
        print(f"[A3.4] Yazıldı: {args.sekil_ihrac_et}")
        print("[A3.4] Bu dosyayı Colab'a yükleyip label_rationale_colab.ipynb'i çalıştırın.")
        return

    onceden_uretilmis = (
        onceden_uretilmis_varyantlari_oku(Path(args.varyant_girdi)) if args.varyant_girdi else None
    )

    sonuclar = gerekceleri_uret(
        satirlar,
        model=args.model,
        ollama_url=args.ollama_url,
        varyant_sayisi=args.varyant_sayisi,
        onceden_uretilmis_varyantlar=onceden_uretilmis,
    )
    _jsonl_yaz(sonuclar, Path(args.cikti))

    toplam = len(sonuclar)
    sablona_dusen = sum(1 for s in sonuclar if s["guard_sonucu"] == GuardSonucu.SABLONA_DUSTU.value)
    red_orani = sablona_dusen / toplam if toplam else 0.0

    print(f"[A3.4] Toplam gerekçe: {toplam}")
    print(f"[A3.4] Yazıldı: {args.cikti}")
    print()
    print("[A3.4] Guard sonucu dağılımı:")
    for sonuc in GuardSonucu:
        n = sum(1 for s in sonuclar if s["guard_sonucu"] == sonuc.value)
        oran = f"(%{100 * n / toplam:.1f})" if toplam else ""
        print(f"  {sonuc.value}: {n} {oran}")
    print()
    print(f"[A3.4] Şablona düşme oranı: %{red_orani * 100:.2f}")
    if red_orani > RED_ORANI_UYARI_ESIGI:
        print(
            f"UYARI: Şablona düşme oranı %{RED_ORANI_UYARI_ESIGI * 100:.0f} eşiğini aşıyor, "
            "prompt'u düzelt, bu veriyi kabul ETME (bkz. görev tanımı A3.4)."
        )


if __name__ == "__main__":
    _cli()
