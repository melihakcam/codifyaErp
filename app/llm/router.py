"""Türkçe soru → araç çağrısı. Bilinmeyen araç uydurursa reddedilir.

Sahip: Kişi B · Faz 2 B2.3

**Henüz eğitim yok** — model few-shot örneklerle çalışıyor. Faz 3'te LoRA
eğitildiğinde bu dosya değişmeyecek; yalnızca `.env`'deki model adı
değişecek. Bu yüzden B2.3'te ölçülen taban çizgi (bkz.
`dokumantasyon/OLCUMLER.md`) eğitimin işe yarayıp yaramadığının **tek**
karşılaştırma noktası.

Araç adları ve parametreleri `app/llm/schemas.py`'de; oradaki liste Kişi A'nın
eğitim verisiyle birebir aynı tutuluyor.

Güvenlik: uydurma araç adı şema düzeyinde eleniyor (`AracAdi` enum'u), yanlış
parametre `AracCagrisi` doğrulayıcısında. Yani bu dosyanın ayrıca "bilinen
araç mı" kontrolü yapmasına gerek yok — kontrol sözleşmede.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.llm.client import LLMErisilemiyor, OllamaIstemcisi
from app.llm.schemas import (
    ARAC_PARAMETRELERI,
    AracAdi,
    AracCagrisi,
    SemaUyumsuz,
    YapilandirilmisSonuc,
    yapilandirilmis_uret,
)

# Araç açıklamaları prompt'a bu sırayla giriyor. Kısa ve ayırt edici tutuldu:
# uzun açıklama küçük modelde ayırt ediciliği artırmıyor, bağlamı şişiriyor.
ARAC_ACIKLAMALARI: dict[AracAdi, str] = {
    AracAdi.KRITIK_STOK: "stoğu azalan, tükenmek üzere olan, acil sipariş gereken ürünler",
    AracAdi.OLU_STOK: "uzun süredir satılmayan, hareketsiz, tasfiye/iskonto önerilen ürünler",
    AracAdi.TEDARIKCI_PERFORMANSI: "bir tedarikçinin teslimat performansı, skoru, gecikmesi",
    AracAdi.SIPARIS_ONERISI: "belirli bir ürün için ne kadar sipariş verilmeli",
    AracAdi.ONAY_KUYRUGU: "insan onayı bekleyen kararlar, onay kuyruğu",
    AracAdi.GECELIK_OZET: "gecelik taramanın bulguları, gece üretilen rapor",
    AracAdi.GENEL_STOK_DURUMU: "deponun/envanterin genel durumu, toplu özet",
}

# Few-shot örnekleri bilinçli olarak DOLAYLI ifadelerden seçildi. B2.2 ön
# ölçümünde model açık sorularda (~"kritik stok var mı") zaten iyiydi;
# hataların tamamı dolaylı ifadelerdeydi ("kuyrukta ne var", "dün gece ne
# bulundu"). Örnekleri modelin zaten bildiği yerden seçmek boşa bağlam olurdu.
ORNEKLER: tuple[tuple[str, str], ...] = (
    ("Kuyrukta ne var?", '{"arac": "onay_kuyrugu_sorgula", "parametreler": {}}'),
    ("Dün gece ne bulundu?", '{"arac": "gecelik_ozet_sorgula", "parametreler": {}}'),
    (
        "Yılmaz Yapı zamanında teslim ediyor mu?",
        '{"arac": "tedarikci_performansi_sorgula", '
        '"parametreler": {"tedarikci_id": "Yılmaz Yapı"}}',
    ),
    (
        "Aylardır satılmayan ürünler var mı?",
        '{"arac": "olu_stok_sorgula", "parametreler": {}}',
    ),
)


def sistem_istemi() -> str:
    """Araç listesi + few-shot örnekleri içeren sistem promptu."""
    satirlar = [
        "Sen bir ERP asistanısın. Kullanıcının Türkçe sorusuna hangi aracın",
        "cevap vereceğini seç. YALNIZCA aşağıdaki araçlardan birini kullan,",
        "yeni araç adı uydurma.",
        "",
        "ARAÇLAR:",
    ]
    for arac, aciklama in ARAC_ACIKLAMALARI.items():
        parametre = ARAC_PARAMETRELERI[arac]
        parametre_metni = f"parametre: {parametre}" if parametre else "parametre almaz"
        satirlar.append(f"- {arac.value} — {aciklama} ({parametre_metni})")

    satirlar += ["", "ÖRNEKLER:"]
    for soru, cevap in ORNEKLER:
        satirlar += [f"Soru: {soru}", f"Cevap: {cevap}"]

    satirlar += [
        "",
        "Parametre yalnızca soruda AÇIKÇA geçiyorsa doldurulur.",
        "Geçmiyorsa parametreler boş bırakılır.",
    ]
    return "\n".join(satirlar)


@dataclass(frozen=True)
class YonlendirmeSonucu:
    """Router çıktısı + ölçümler."""

    cagri: AracCagrisi
    deneme_sayisi: int
    uretim_ms: int


def soruyu_yonlendir(
    istemci: OllamaIstemcisi,
    soru: str,
    *,
    max_deneme: int = 2,
    sicaklik: float | None = None,
    tohum: int | None = None,
) -> YonlendirmeSonucu:
    """Türkçe soruyu bir araç çağrısına çevirir.

    Fırlatabilecekleri:

    · `SemaUyumsuz`   — model `max_deneme` içinde geçerli araç çağrısı
                        üretemedi (uydurma araç adı, bozuk JSON, yanlış
                        parametre). Çağıran taraf kullanıcıya "anlayamadım"
                        demeli, tahmin etmemeli.
    · `LLMErisilemiyor` — model sunucusu yok. Router'ın şablon karşılığı yok:
                        gerekçede şablona düşebiliyoruz ama "hangi araç"
                        sorusunun deterministik cevabı yok. Bu yüzden hata
                        yukarı taşınıyor.
    """
    sonuc: YapilandirilmisSonuc[AracCagrisi] = yapilandirilmis_uret(
        istemci,
        AracCagrisi,
        f"Soru: {soru}",
        sistem=sistem_istemi(),
        max_token=80,
        max_deneme=max_deneme,
        sicaklik=sicaklik,
        tohum=tohum,
    )
    return YonlendirmeSonucu(
        cagri=sonuc.deger,
        deneme_sayisi=sonuc.deneme_sayisi,
        uretim_ms=sonuc.uretim.uretim_ms,
    )


__all__ = [
    "ARAC_ACIKLAMALARI",
    "LLMErisilemiyor",
    "SemaUyumsuz",
    "YonlendirmeSonucu",
    "sistem_istemi",
    "soruyu_yonlendir",
]
