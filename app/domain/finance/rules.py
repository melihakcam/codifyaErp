"""Finans & Tahsilat kural motoru — Faz 6.

⭐ **Bu modülün asıl iddiası: stok kalıbı finansa aynen taşınıyor.**

Stoktaki üç karar ve finanstaki karşılıkları:

| stok | finans | ortak mantık |
|---|---|---|
| ROP altına düştü → sipariş ver | gecikme eşiğini aştı → tahsilat takibi | eşik + emniyet payı |
| uzun süre hareketsiz → tasfiye | çok eski alacak → karşılık ayır | yaşlanma |
| tedarikçi skoru düştü → değişim | risk arttı → kredi limitini düşür | karşı taraf performansı |

En güçlü eşleşme birincisinde ve tesadüf değil. Stokta emniyet stoğu:

    emniyet = Z(servis_seviyesi) x sqrt(tedarik_suresi x talep_std^2 + ...)

Finansta aynı formül, aynı anlam:

    emniyet_gun = Z(tahsilat_hedefi) x odeme_gecikmesi_std

İkisi de tek bir soruyu soruyor: **belirsizliğe karşı ne kadar pay
bırakmalıyım?** Stokta pay adet, finansta gün cinsinden — matematik aynı,
`scipy.stats.norm` çağrısı bile ortak.

⚠️ Bunun pratik sonucu şu: `duzensiz_odeme` patolojisi (yüksek σ) olan
müşteriyi **çok daha erken** aramak gerekiyor, çünkü emniyet payı σ ile
büyüyor. `kronik_gecikme` (yüksek ortalama, düşük σ) ise geç ödese bile
öngörülebilir — 40. günde arayacağını bilirsin. Ortalamaya bakan bir sistem
bu ikisini karıştırır ve yanlış müşteriyi kovalar.
"""

from __future__ import annotations

import math

from scipy.stats import norm

from app.contracts import ABCSinifi, FinansOzellikleri, XYZSinifi

# ---------------------------------------------------------------------------
# Hedef tahsilat oranı — ABC/XYZ matrisi
# ---------------------------------------------------------------------------

HEDEF_TAHSILAT_ORANI_MATRISI: dict[tuple[ABCSinifi, XYZSinifi], float] = {
    (ABCSinifi.A, XYZSinifi.X): 0.99,
    (ABCSinifi.A, XYZSinifi.Y): 0.97,
    (ABCSinifi.A, XYZSinifi.Z): 0.95,
    (ABCSinifi.B, XYZSinifi.X): 0.97,
    (ABCSinifi.B, XYZSinifi.Y): 0.95,
    (ABCSinifi.B, XYZSinifi.Z): 0.90,
    (ABCSinifi.C, XYZSinifi.X): 0.95,
    (ABCSinifi.C, XYZSinifi.Y): 0.90,
    (ABCSinifi.C, XYZSinifi.Z): 0.85,
}
"""Stoktaki servis seviyesi matrisiyle **aynı sayılar**, ve bu bilinçli.

Mantık da aynı: cirosu yüksek + ödemesi düzenli (AX) müşteriyi kaybetmek
pahalıya gelir, sıkı takip edilir. Cirosu düşük + ödemesi kaotik (CZ)
müşteride yüksek tahsilat hedefi tutturmaya çalışmak, tahsilat maliyetini
alacağın üstüne çıkarır.

⚠️ Sayıların aynı olması "kopyala yapıştır" değil: iki matris de aynı
Pareto/öngörülebilirlik ikilisinden türüyor. Alanlar ayrıştıkça değerler
ayrışabilir; o zaman bu docstring güncellenir."""


# ---------------------------------------------------------------------------
# Tahsilat takibi eşiği — stoktaki ROP'un karşılığı
# ---------------------------------------------------------------------------


def emniyet_gunu_hesapla(
    hedef_tahsilat_orani: float,
    odeme_gecikmesi_std: float,
) -> float:
    """Ödeme gecikmesi belirsizliğine karşı bırakılan gün payı.

    `emniyet_stogu_hesapla`'nın finanstaki karşılığı. Stokta iki belirsizlik
    kaynağı vardı (talep + tedarik süresi); burada tek bir kaynak var
    (ödeme davranışı), o yüzden karekök içi tek terim.

    ⚠️ σ = 0 ise pay da 0. Bu doğru: hep tam vadesinde ödeyen bir müşteri
    için erken arama gerekmez.
    """
    z = norm.ppf(hedef_tahsilat_orani)
    return float(z * math.sqrt(max(odeme_gecikmesi_std**2, 0.0)))


def takip_esigi_hesapla(
    ort_odeme_gecikmesi_gun: float, emniyet_gunu: float
) -> float:
    """Kaç gün gecikmeden sonra takibe girilmeli.

    `yeniden_siparis_noktasi_hesapla`'nın karşılığı: beklenen gecikme +
    emniyet payı. Bu eşiğin altındaki gecikme "normal davranış", üstü
    "bu müşteri bu sefer farklı davranıyor" demek.
    """
    return ort_odeme_gecikmesi_gun + emniyet_gunu


def esik_ve_emniyet_gunu(ozellik: FinansOzellikleri) -> tuple[float, float]:
    """`FinansOzellikleri`'nden (takip_esigi, emniyet_gunu) — `decide.py` girişi."""
    emniyet = emniyet_gunu_hesapla(
        hedef_tahsilat_orani=ozellik.hedef_tahsilat_orani,
        odeme_gecikmesi_std=ozellik.odeme_gecikmesi_std,
    )
    esik = takip_esigi_hesapla(ozellik.ort_odeme_gecikmesi_gun, emniyet)
    return esik, emniyet


# ---------------------------------------------------------------------------
# Karşılık ayırma — stoktaki ölü stok değerlendirmesinin karşılığı
# ---------------------------------------------------------------------------

# Türkiye'de şüpheli alacak karşılığı için yaygın kabul gören eşik.
KARSILIK_MUTLAK_ESIK_GUN = 180

# Müşterinin kendi ortalama gecikmesinin bu katı da eşik sayılır. Stoktaki
# `OLU_STOK_GORECELI_CARPAN` ile aynı fikir: mutlak bir gün sayısı, çok yavaş
# ödeyen bir segmentte haksızlık eder.
KARSILIK_GORECELI_CARPAN = 4.0

# Yaşlandırma kademeleri: (gecikme_gun_alt_siniri, karsilik_orani).
# Sondan başa doğru okunur; ilk eşleşen kademe uygulanır.
KARSILIK_KADEMELERI: tuple[tuple[int, float], ...] = (
    (360, 1.00),
    (180, 0.50),
    (90, 0.20),
    (30, 0.05),
)
"""Basamaklar keyfi değil, muhasebe pratiğinin yaygın kademeleri. 360 günde
tam karşılık: bir yıldır ödenmemiş alacak pratikte tahsil edilmiyor."""


def _karsilik_esigi(ort_odeme_gecikmesi_gun: float) -> float:
    """Mutlak ve göreceli eşiğin küçüğü.

    Stoktaki `_olu_stok_esigi` ile aynı mantık: hızlı ödeyen bir müşteride
    60 günlük gecikme zaten alarm; çok yavaş ödeyen bir segmentte 60 gün
    normal olabilir.
    """
    if ort_odeme_gecikmesi_gun <= 0:
        return float(KARSILIK_MUTLAK_ESIK_GUN)
    goreceli = ort_odeme_gecikmesi_gun * KARSILIK_GORECELI_CARPAN
    return float(min(KARSILIK_MUTLAK_ESIK_GUN, goreceli))


def karsilik_orani_hesapla(gecikme_gun: int) -> float:
    """Yaşlandırma kademesinden karşılık oranı."""
    for alt_sinir, oran in KARSILIK_KADEMELERI:
        if gecikme_gun >= alt_sinir:
            return oran
    return 0.0


def karsilik_degerlendir(ozellik: FinansOzellikleri) -> dict:
    """Karşılık ayrılmalı mı, ne kadar?

    Dönen sözlük `FiredRule.degerler`'e doğrudan verilebilir — içindeki her
    sayı guard'ın izinli kümesine girer.
    """
    esik = _karsilik_esigi(ozellik.ort_odeme_gecikmesi_gun)
    oran = karsilik_orani_hesapla(ozellik.en_eski_gecikme_gun)
    tutar = ozellik.vadesi_gecen_tl * oran

    return {
        "karsilik_esigi_gun": esik,
        "onerilen_karsilik_orani": oran,
        "karsilik_tutari_tl": tutar,
        "karsilik_gerekli": bool(oran > 0 and ozellik.en_eski_gecikme_gun >= esik),
    }


# ---------------------------------------------------------------------------
# Kredi limiti — stoktaki tedarikçi skorunun karşılığı
# ---------------------------------------------------------------------------

# Limit önerisi, müşterinin son dönemdeki aylık cirosunun bu katı kadar.
LIMIT_CIRO_CARPANI = 2.0

# Risk skorunda ağırlıklar. Tahsilat geçmişi, gecikme davranışından ağır
# basıyor: geç ama ödeyen müşteri, erken ama ödemeyen müşteriden iyidir.
RISK_AGIRLIK_TAHSILAT = 0.6
RISK_AGIRLIK_GECIKME = 0.4

# Bu skorun altındaki müşteride limit düşürme önerilir (0-100 ölçeği).
LIMIT_DUSURME_SKOR_ESIGI = 45.0


def musteri_risk_skoru(ozellik: FinansOzellikleri) -> float:
    """0-100 arası risk skoru — yüksek = güvenilir.

    `tedarikci_skoru_hesapla`'nın karşılığı ve aynı iki bileşenli yapı:
    stokta (zamanında teslim + tutarlılık), finansta (tahsilat + gecikme
    tutarlılığı).

    ⚠️ Gecikme bileşeni **ortalamaya değil oynaklığa** bakıyor. Düzenli
    geç ödeyen müşteri planlanabilir; asıl risk öngörülemezlikte.
    """
    tahsilat = max(0.0, min(1.0, ozellik.tahsilat_orani))

    # Değişim katsayısı 0 → tam puan, 1,5 ve üstü → sıfır puan.
    dk = ozellik.gecikme_varyasyon_katsayisi
    tutarlilik = max(0.0, min(1.0, 1.0 - dk / 1.5))

    skor = RISK_AGIRLIK_TAHSILAT * tahsilat + RISK_AGIRLIK_GECIKME * tutarlilik
    return float(round(skor * 100, 2))


def limit_degerlendir(ozellik: FinansOzellikleri) -> dict:
    """Kredi limiti düşürülmeli mi, ne kadara?"""
    skor = musteri_risk_skoru(ozellik)
    asim = ozellik.limit_asimi_tl

    # Riskli müşteride limit, skorla orantılı olarak kısılır.
    onerilen = ozellik.kredi_limiti_tl * (skor / 100.0) if skor < LIMIT_DUSURME_SKOR_ESIGI else (
        ozellik.kredi_limiti_tl
    )

    return {
        "musteri_risk_skoru": skor,
        "limit_asimi_tl": asim,
        "onerilen_kredi_limiti_tl": round(onerilen, 2),
        "limit_dusurulmeli": bool(skor < LIMIT_DUSURME_SKOR_ESIGI),
    }


__all__ = [
    "HEDEF_TAHSILAT_ORANI_MATRISI",
    "KARSILIK_GORECELI_CARPAN",
    "KARSILIK_KADEMELERI",
    "KARSILIK_MUTLAK_ESIK_GUN",
    "LIMIT_DUSURME_SKOR_ESIGI",
    "RISK_AGIRLIK_GECIKME",
    "RISK_AGIRLIK_TAHSILAT",
    "emniyet_gunu_hesapla",
    "esik_ve_emniyet_gunu",
    "karsilik_degerlendir",
    "karsilik_orani_hesapla",
    "limit_degerlendir",
    "musteri_risk_skoru",
    "takip_esigi_hesapla",
]
