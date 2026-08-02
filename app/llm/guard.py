"""SAYISAL DOĞRULAMA GUARD'I — projenin en kritik parçası.

Sahip: Kişi B · Faz 2 B2.5

Mimarinin birinci kuralı: **LLM asla sayı üretmez.** Sayılar prompt'a kural
motorundan verilir, model onları yalnızca cümleye yerleştirir. Ürettiği
metindeki her sayı `DecisionCandidate.izinli_sayilar()` kümesinde yoksa çıktı
reddedilir.

Bu kural teorik bir önlem değil — bu projede modelin gerçekten yaptığı şey:

    B2.1  "Kırmızı Tuğla için 35 adet ek satışı yapar"    ← 35 uydurma
    B2.2  "163..."                                        ← uydurma
    B2.2  "42 + 615 - 1200 = 397..."                      ← uydurma + aritmetik
    B2.2  "1976-03-14T13:44:00Z..."                       ← rastgele tarih

İlki şemasız bir çağrıydı; **son üçü şema zorlamalı çağrılarda çıktı.** Yani
şema biçimi garanti ediyor, anlamı etmiyor. Guard olmadan bu sayılar
kullanıcıya gider.

Zincir (görev dosyası B2.5):

    üret → doğrula → geçmezse 1 kez YENİDEN ÜRET → yine geçmezse ŞABLONA DÜŞ

Sonuç her koşulda `GuardSonucu` olarak denetim kaydına yazılır. **Karar
hiçbir koşulda bloke olmaz** — şablon gerekçe deterministik ve her zaman
geçer.

---

**İki tasarım kararı, ikisi de acı deneyimle öğrenildi:**

**1. Maskeleme zorunlu.** Ürün ve tedarikçi adlarındaki rakamlar sayı değil.
`"Kırmızı Tuğla 19x9x5"` içindeki 19, 9, 5 ölçüdür ve izinli kümede yoktur.
Maskelenmezse **kendi şablon gerekçemiz kendi guard'ımızdan geçemez** —
ölçüldü, doğrulandı. Şablon guard'ın geri dönüş noktası olduğu için o da
reddedilirse sistemin güvenli çıkışı kalmaz. Fikir Kişi A'nın
`label_rationale.py::_metni_maskele`'sinden geldi.

**2. Tolerans hem yuvarlamayı kabul etmeli hem kabalığı kesmeli.**
`talep_varyasyon_katsayisi = 27,380952` iken model `%27` yazabilir — bu doğru
bir yuvarlama, reddedilmemeli. Ama `0,94 → "1"` de bir yuvarlama ve o kabul
edilirse gerekçede "1 adet" yazan bir uydurma geçer.

Kural: **birebir eşleşme VEYA (yazılan hassasiyette doğru yuvarlama VE bağıl
fark ≤ %2)**. Üç alternatif gerçek vakalarla karşılaştırıldı; mutlak tolerans
(0,01) meşru yuvarlamayı reddediyor, yalnız-yuvarlama ise `4,75 → "5"` gibi
kaba yuvarlamaları geçiriyordu.

---

⚠️ **Kişi A da bu guard'ı kullanacak** (A3.4 etiketleme hattı). Onun için
`sayilari_dogrula()` sade ve bağımsız tutuldu: `DecisionCandidate` bilmiyor,
yalnızca metin + izinli küme + maskelenecek metinler alıyor. `label_rationale.py`
kendi kopyasını silip bunu import edebilir.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from app.contracts import DecisionCandidate, Gerekce, GuardSonucu
from app.llm.explain import sablon_gerekce

# Türkçe sayı biçimleri: 1.200 · 4,75 · %94 · 5.000 TL · 1.200,50
# Tek haneli sayılar da yakalanmalı (ör. "3 gün").
SAYI_DESENI = re.compile(r"\d[\d.,]*\d|\d")

# Yuvarlamada izin verilen bağıl sapma. %2: `27,38 → "%27"` (%1,4 sapma)
# geçiyor, `4,75 → "5"` (%5,3 sapma) geçmiyor.
YUVARLAMA_BAGIL_SINIRI = 0.02

# Kayan nokta gürültüsü için birebir eşleşme payı.
_EPSILON = 1e-9


@dataclass(frozen=True)
class DogrulamaSonucu:
    """Bir metnin sayısal doğrulama sonucu."""

    gecti: bool
    bulunan: list[float]
    reddedilen: list[float]


class GerekceUreteci(Protocol):
    """Metin üreten herhangi bir şey — LLM, sahte üreteç, sabit metin.

    `onceki_red` verildiğinde üreteç bunu prompt'a ekleyebilir ("şu sayıları
    kullanma"). Zorunlu değil; basit üreteçler yok sayabilir. İkinci denemeyi
    birinciden farklı kılmanın en ucuz yolu bu.
    """

    def __call__(
        self, aday: DecisionCandidate, *, onceki_red: list[float] | None = None
    ) -> str: ...


# ---------------------------------------------------------------------------
# Sayı ayrıştırma
# ---------------------------------------------------------------------------


def sayiyi_coz(belirtec: str) -> float | None:
    """Türkçe biçimli bir sayı belirtecini float'a çevirir.

    `'1.200'` → 1200.0 · `'4,75'` → 4.75 · `'1.200,50'` → 1200.5

    Nokta binlik ayracı, virgül ondalık ayracıdır — Türkçe biçim. Model
    İngilizce biçimde (`'1,200'` = 1200) yazarsa bu 1,2 olarak çözülür ve
    büyük olasılıkla reddedilir. Bu bilinçli: guard **güvenli tarafa** hata
    yapar, metin şablona düşer. Ters yönde esnetmek uydurma bir sayının iki
    yorumdan biriyle kümeye denk gelmesine kapı açardı.
    """
    t = belirtec.strip().strip(".,")
    if not t:
        return None

    if "," in t:
        tam, _, ondalik = t.rpartition(",")
        aday = f"{tam.replace('.', '')}.{ondalik}" if tam else f"0.{ondalik}"
    else:
        aday = t.replace(".", "")

    try:
        return float(aday)
    except ValueError:
        return None


def metni_maskele(metin: str, maskelenecek: Iterable[str]) -> str:
    """Ad/kod alanlarını metinden siler.

    ⚠️ Guard'ın çalışması için ZORUNLU. `"Kırmızı Tuğla 19x9x5"` içindeki
    19, 9, 5 ölçüdür, veri değil — izinli kümede yoktur. Maskelenmezse geçerli
    her gerekçe reddedilir.

    Uzun metinler önce maskeleniyor: `"T-014"` ile `"T-0141"` gibi biri
    diğerinin öneki olan kodlarda kısa olanı önce silmek uzununu bozardı.

    Büyük/küçük harf duyarsız — model ürün adının yazımını değiştirebilir.
    """
    for deger in sorted((d for d in maskelenecek if d), key=len, reverse=True):
        metin = re.sub(re.escape(deger), " ", metin, flags=re.IGNORECASE)
    return metin


def sayilari_cikar(metin: str) -> list[float]:
    """Metindeki tüm sayıları sırayla döndürür."""
    return [s for s in (sayiyi_coz(t) for t in SAYI_DESENI.findall(metin)) if s is not None]


# ---------------------------------------------------------------------------
# Doğrulama — Kişi A'nın da kullanacağı sade arayüz
# ---------------------------------------------------------------------------


def _ondalik_sayisi(deger: float) -> int:
    """Yazılan sayının kaç ondalık basamağı var."""
    metin = f"{deger:.10f}".rstrip("0").rstrip(".")
    return len(metin.partition(".")[2])


def sayi_izinli_mi(yazilan: float, izinli: Iterable[float]) -> bool:
    """Yazılan sayı izinli kümedeki bir değerin kabul edilebilir yazımı mı?

    İki koşuldan biri yeterli:

    1. **Birebir eşleşme** (kayan nokta payıyla).
    2. **Doğru yuvarlama + bağıl sınır**: yazılan sayı, izinli bir değerin
       kendi hassasiyetinde doğru yuvarlanmışı VE aradaki bağıl fark
       `YUVARLAMA_BAGIL_SINIRI`'ni aşmıyor.

    İkinci koşulun bağıl sınırı olmasa `0,94 → "1"` ve `4,75 → "5"` gibi kaba
    yuvarlamalar geçerdi; bunlar gerekçede adet olarak okunur ve uydurma bir
    sayı kullanıcıya gider.
    """
    basamak = _ondalik_sayisi(yazilan)

    for deger in izinli:
        if abs(yazilan - deger) < _EPSILON:
            return True
        if abs(yazilan - round(deger, basamak)) >= _EPSILON:
            continue
        if abs(deger) < _EPSILON:
            continue  # sıfırın yuvarlaması yalnızca sıfırdır, o da yukarıda yakalandı
        if abs(yazilan - deger) / abs(deger) <= YUVARLAMA_BAGIL_SINIRI:
            return True

    return False


def sayilari_dogrula(
    metin: str,
    izinli: Iterable[float],
    *,
    maskelenecek: Iterable[str] = (),
) -> DogrulamaSonucu:
    """Metindeki her sayı izinli kümede mi?

    ⚠️ **Kişi A'nın kullanacağı arayüz budur** (A3.4 etiketleme hattı).
    Bilinçli olarak `DecisionCandidate` bilmiyor: yalnızca metin, izinli küme
    ve maskelenecek metinler alıyor. Böylece eğitim verisi üretiminde de
    çalışma zamanında da aynı kod çalışır — iki kopya zamanla ayrışırdı.
    """
    izinli = list(izinli)
    bulunan = sayilari_cikar(metni_maskele(metin, maskelenecek))
    reddedilen = [s for s in bulunan if not sayi_izinli_mi(s, izinli)]
    return DogrulamaSonucu(gecti=not reddedilen, bulunan=bulunan, reddedilen=reddedilen)


def maskelenecek_alanlar(aday: DecisionCandidate) -> list[str]:
    """Bir karar adayında rakam içerebilen ad/kod alanları."""
    o = aday.ozellikler
    return [o.sku_adi, o.sku_id, o.tedarikci_adi, o.tedarikci_id]


def adayi_dogrula(metin: str, aday: DecisionCandidate) -> DogrulamaSonucu:
    """`sayilari_dogrula` için kısayol — izinli kümeyi ve maskeyi adaydan alır."""
    return sayilari_dogrula(
        metin,
        aday.izinli_sayilar(),
        maskelenecek=maskelenecek_alanlar(aday),
    )


# ---------------------------------------------------------------------------
# Tam zincir: üret → doğrula → yeniden dene → şablona düş
# ---------------------------------------------------------------------------


def gerekceyi_guvenceye_al(
    aday: DecisionCandidate,
    uretici: GerekceUreteci,
    *,
    model_adi: str | None = None,
    max_deneme: int = 2,
) -> Gerekce:
    """Guard'lı gerekçe üretimi. **Hiçbir koşulda hata fırlatmaz.**

    Üreteç patlarsa (LLM erişilemez, şema tutmaz, ne olursa) şablona düşülür.
    Sebebi mimarinin ikinci kuralı: karar zaten üretilmiş durumda, yalnızca
    Türkçe cümle yazılamamış. Bunun kararı bloke etmesi kabul edilemez.

    `max_deneme=2` görev dosyasının kuralı: "2 denemede geçemezse şablona düş".
    Daha fazla denemek CPU yakar; ölçümlerde 3. deneme 2.'den anlamlı şekilde
    iyi çıkmıyor.

    Dönen `GuardSonucu`:

    · `GECTI`            — ilk denemede geçti
    · `YENIDEN_URETILDI` — ilk deneme reddedildi, ikincisi geçti
    · `SABLONA_DUSTU`    — hiçbiri geçmedi (veya üreteç patladı)

    `reddedilen_sayilar` **son** denemenin reddettikleridir; şablona düşüldüyse
    bu liste "model neyi uydurdu" sorusunun kaydıdır ve denetim satırına yazılır.
    """
    baslangic = time.perf_counter()
    son_red: list[float] = []

    for deneme in range(1, max_deneme + 1):
        try:
            metin = uretici(aday, onceki_red=son_red or None)
        except Exception:
            # Üreteç ne fırlatırsa fırlatsın karar bloke olmamalı. Ayrıntı
            # denetim kaydındaki reddedilen_sayilar'dan değil, üretecin kendi
            # loglarından izlenir.
            break

        sonuc = adayi_dogrula(metin, aday)
        if sonuc.gecti:
            return Gerekce(
                karar_id=aday.karar_id,
                metin=metin,
                guard_sonucu=(GuardSonucu.GECTI if deneme == 1 else GuardSonucu.YENIDEN_URETILDI),
                model_adi=model_adi,
                uretim_ms=int((time.perf_counter() - baslangic) * 1000),
                reddedilen_sayilar=[],
            )
        son_red = sonuc.reddedilen

    return Gerekce(
        karar_id=aday.karar_id,
        metin=sablon_gerekce(aday),
        guard_sonucu=GuardSonucu.SABLONA_DUSTU,
        model_adi=None,  # şablon deterministik, modelden gelmedi
        uretim_ms=int((time.perf_counter() - baslangic) * 1000),
        reddedilen_sayilar=son_red,
    )


__all__ = [
    "SAYI_DESENI",
    "YUVARLAMA_BAGIL_SINIRI",
    "DogrulamaSonucu",
    "GerekceUreteci",
    "adayi_dogrula",
    "gerekceyi_guvenceye_al",
    "maskelenecek_alanlar",
    "metni_maskele",
    "sayi_izinli_mi",
    "sayilari_cikar",
    "sayilari_dogrula",
    "sayiyi_coz",
]
