"""Türkçe gerekçe üretimi.

Sahip: Kişi B · gerçek uygulaması Faz 2 B2.4

ŞU AN: yalnızca `explain_stub()` var — LLM'e hiç dokunmaz, deterministik
şablonla cümle kurar.

Bu şablon Faz 2'de de silinmeyecek: guard iki denemede geçemezse buraya
düşülür. Yani "en kötü durum çıktısı" şimdiden yazılıyor ve karar yolu
LLM'e hiç bağımlı olmuyor.
"""

from __future__ import annotations

from app.contracts import DecisionCandidate, Gerekce, GuardSonucu, KararTipi


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
