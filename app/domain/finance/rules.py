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

⚠️ **Ama yön stoktakiyle TERS ve bu bilinçli.** Stokta belirsizlik erken
davranmayı gerektirir (stok tükenmesin). Finansta eşik bir **anomali
dedektörü**: "bu gecikme, bu müşteri için olağandışı mı?"

    hep 20±2 gunde odeyen  -> 40 gun ALARM      (esik ~23 gun)
    0-90 arasi savrulan    -> 40 gun normal     (esik ~68 gun)

İkincisini erken aramak istatistiksel olarak anlamsız: o müşteride 40 gün
gürültüden ayırt edilemez. Zaten **doğru tepki de arama değil**: düzensiz
ödeyen müşteri `musteri_risk_skoru` üzerinden yakalanır ve
`kredi_limiti_dusur` tetiklenir. Öngörülemezliği daha sık arayarak değil,
**maruz kalınan riski azaltarak** yönetirsin.

Yani iki patoloji iki farklı kolla ele alınıyor:

    kronik_gecikme (yuksek ort, dusuk σ) -> takip esigi yakalar
    duzensiz_odeme (orta ort, yuksek σ)  -> risk skoru yakalar

Ortalamaya bakan tek eksenli bir sistem ikisini de karıştırır: kronik
gecikeni "kötü müşteri" diye keser, düzensizi ise fark etmez.
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

# Göreceli eşiğin inebileceği taban. `KARSILIK_KADEMELERI`'nde anlamlı
# karşılığın (%20) başladığı gün — bkz. `_karsilik_esigi`.
KARSILIK_TABAN_ESIK_GUN = 90

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
    """Karşılık ayırma eşiği — göreceli, ama bir tabanın altına inmez.

    ⚠️ Faz 7'de düzeltildi. Önceden `min(180, ort_gecikme x 4)` idi ve
    stoktaki `_olu_stok_esigi`'nin birebir kopyasıydı. Stokta doğru:
    hızlı dönen bir SKU 40 gün hareketsizse gerçekten ölüdür.

    **Alacakta aynı mantık tutmuyor** ve iki nedenle:

    1. **Muhasebe.** Ortalama 10 günde ödeyen bir müşterinin 40 günlük
       alacağı için şüpheli alacak karşılığı ayrılmaz. Modülün kendi
       `KARSILIK_KADEMELERI` tablosu bunu zaten söylüyor: 30 günde %5,
       anlamlı karşılık 90 günde başlıyor.
    2. **Karar önceliği.** `decide.py`'de karşılık, takibin ÜSTÜNDE. Eşik
       40 güne inince müşteri hiç aranmadan doğrudan zarar yazılıyordu —
       tahsil edilebilecek alacak, tahsil edilmeye çalışılmadan
       kaybediliyordu.

    Faz 7 para metriğinde ölçüldü: kural motoru 12 ayda **hiçbir** batık
    alacağı kurtaramıyordu (vasat politika 141 tanesini kurtardı), çünkü
    kovalaması gereken müşterilere daha 40. günde karşılık ayırmıştı.

    Göreceli çarpan yine de duruyor — ama artık yalnızca eşiği **yukarı**
    taşıyabiliyor: çok yavaş ödeyen bir segmentte 90 gün normal olabilir.
    """
    if ort_odeme_gecikmesi_gun <= 0:
        return float(KARSILIK_MUTLAK_ESIK_GUN)
    goreceli = ort_odeme_gecikmesi_gun * KARSILIK_GORECELI_CARPAN
    return float(min(KARSILIK_MUTLAK_ESIK_GUN, max(KARSILIK_TABAN_ESIK_GUN, goreceli)))


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

LIMIT_KOLU_AKTIF = True
"""Kredi limiti düşürme kolu açık mı? **Varsayılan AÇIK.**

⚠️ Bu bayrak bugün iki kez ölçüldü ve iki farklı cevap verdi. İkisi de
doğru; soru değişti.

**A7.1 (kapatıldı).** Varsayılan senaryoda — batak müşteri oranı %2, ufuk
1 yıl — kol her ayarda zarar ettiriyordu. Beş eşik × üç kesinti oranında
tarandı, hepsinde maliyet arttı. Kapatıldı.

**A5 (yeniden açıldı).** Kapatma gerekçesinin bilinen bir sınırı vardı ve
o sınır test edildi: kredi limitinin asıl işi **nadir ama büyük** çöküşü
engellemek, o senaryo ise 1 yıl / %2 batakta hiç temsil edilmiyordu.

`limit_kolu_risk_taramasi` çıktısı (kol açık vs kapalı, net katkı TL —
pozitif = kol kazandırdı):

| batak oranı | 1 yıl | 3 yıl |
|---|---|---|
| %2 | **-8.543** | +18.309 |
| %5 | +31.445 | +67.109 |
| %10 | +18.644 | +96.541 |

Altı senaryonun **beşinde** kol kârlı. Kaybettiği tek hücre, en yumuşak
senaryo.

⭐ **Varsayılanı belirleyen şey çoğunluk değil, kaybın asimetrisi.** Kol
gereksizken açık olmanın bedeli 8.543 TL; gerekliyken kapalı olmanın
bedeli 96.541 TL — **11 kat**. Kredi limiti bir sigortadır: primi düşük
riskte boşa gider, ama yangın çıktığında ödediğin primle
kıyaslanmayacak kadar iş görür.

⚠️ **Bunun bedeli var ve saklanmıyor:** varsayılan senaryoda (§8'in ölçüm
zemini) kural motoru vasat politikaya göre %2,4 yerine %6,1 geride
kalıyor. Yani kolu açık bırakmak, benchmark sayısını **kötüleştiriyor**.
Sayıyı iyi göstermek için kapatmak, sistemi gerçek riskte savunmasız
bırakmak olurdu.

**Müşteri bazında karar:** gerçek veride portföyün batak oranı ölçülebilir
(`FinansOzellikleri.tahsilat_orani` üzerinden). %3'ün altındaysa ve planlama
ufku 1 yılsa bu bayrak `False` yapılabilir. Emin değilsen açık bırak —
asimetri onu söylüyor."""

# Bu skorun altındaki müşteride limit düşürme önerilir (0-100 ölçeği).
LIMIT_DUSURME_SKOR_ESIGI = 45.0

# Limit en fazla bu oranda kısılır (skor 0 olsa bile).
#
# ⚠️ Faz 7'de eklendi ve bir tasarım kusurunu kapatıyor. Önceden öneri
# doğrudan `limit x skor/100` idi: skoru 44 olan müşteri — eşiğin bir puan
# altında — limitinin %56'sını kaybediyordu. Eşik böylece bir kademe değil
# uçurum oluyordu.
#
# Ölçülen sonucu: para metriğinde 12 aylık koşuda 3.762 fatura iptal edildi,
# 258 bin TL marj kaybı yazıldı — kural motorunu vasat politikanın %49
# gerisine düşüren tek kalem buydu. Kesinti artık skorun eşiğe uzaklığıyla
# orantılı: eşikte sıfır, skor sıfırken bu tavan.
#
# Stok tarafındaki emniyet stoğu mantığıyla aynı: tepki belirsizlikle
# ORANTILI büyür, eşiği geçince bir anda maksimuma çıkmaz.
MAKS_LIMIT_KESINTI_ORANI = 0.5


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


def kesinti_orani_hesapla(skor: float) -> float:
    """Risk skorundan limit kesinti oranı — eşikte 0, skor 0'da tavan.

    Ayrı fonksiyon olması bilinçli: kademenin şekli tek satırda görülebilsin
    ve doğrudan test edilebilsin. Süreklilik önemli — eşiğin iki yanındaki
    iki müşteriye çok farklı davranan bir kural, skorun ölçüm gürültüsünü
    iş kararına çevirir.
    """
    if skor >= LIMIT_DUSURME_SKOR_ESIGI:
        return 0.0
    sertlik = (LIMIT_DUSURME_SKOR_ESIGI - skor) / LIMIT_DUSURME_SKOR_ESIGI
    return MAKS_LIMIT_KESINTI_ORANI * max(0.0, min(1.0, sertlik))


def limit_degerlendir(ozellik: FinansOzellikleri) -> dict:
    """Kredi limiti düşürülmeli mi, ne kadara?"""
    skor = musteri_risk_skoru(ozellik)
    asim = ozellik.limit_asimi_tl

    # Riskli müşteride limit, skorun eşiğe uzaklığıyla ORANTILI kısılır.
    onerilen = ozellik.kredi_limiti_tl * (1.0 - kesinti_orani_hesapla(skor))

    # ⚠️ Kol kapalıyken skor ve öneri YİNE hesaplanıyor, yalnızca
    # `limit_dusurulmeli` bastırılıyor. Sebebi: `musteri_risk_skoru` gerekçe
    # metninde ve insight'larda kullanılıyor — riski görmeyi bırakmıyoruz,
    # yalnızca otomatik aksiyon üretmiyoruz.
    return {
        "musteri_risk_skoru": skor,
        "limit_asimi_tl": asim,
        "onerilen_kredi_limiti_tl": round(onerilen, 2),
        "limit_dusurulmeli": bool(LIMIT_KOLU_AKTIF and skor < LIMIT_DUSURME_SKOR_ESIGI),
    }


__all__ = [
    "HEDEF_TAHSILAT_ORANI_MATRISI",
    "KARSILIK_GORECELI_CARPAN",
    "KARSILIK_KADEMELERI",
    "KARSILIK_MUTLAK_ESIK_GUN",
    "KARSILIK_TABAN_ESIK_GUN",
    "LIMIT_DUSURME_SKOR_ESIGI",
    "LIMIT_KOLU_AKTIF",
    "MAKS_LIMIT_KESINTI_ORANI",
    "RISK_AGIRLIK_GECIKME",
    "RISK_AGIRLIK_TAHSILAT",
    "emniyet_gunu_hesapla",
    "esik_ve_emniyet_gunu",
    "karsilik_degerlendir",
    "karsilik_orani_hesapla",
    "kesinti_orani_hesapla",
    "limit_degerlendir",
    "musteri_risk_skoru",
    "takip_esigi_hesapla",
]
