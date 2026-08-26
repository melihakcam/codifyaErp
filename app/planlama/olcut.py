""" "İyi plan" ne demek — ölçüt kayıt defteri.

Sahip: Kişi A · Faz 11 A11.2

## ⚠️ Sistem "en iyi planı" bilmiyor ve bilemez

"En iyi" işe göre değişir: bugün stoksuz kalmamak önemliyken yarın hattı boş
bırakmamak önemli olabilir. Bu yüzden motor tek bir plan üretip "en iyisi bu"
demiyor; **aynı veriden birkaç plan** üretip aralarındaki farkı gösteriyor
(`karsilastir.py`).

Buradaki her fonksiyon bir "iyi plan" tanımı. Motor onların içine bakmıyor,
yalnızca **küçükten büyüğe sıralıyor** — küçük olan önce yerleşiyor.

Yeni bir ölçüt eklemek `OLCUTLER` sözlüğüne bir satır. Alan kodu değişmiyor;
"genel karar mekanizması" iddiasının planlama tarafındaki karşılığı bu.
"""

from __future__ import annotations

from collections.abc import Callable

from app.planlama.contracts import Is

Olcut = Callable[[Is], float]


def en_acil(is_: Is) -> float:
    """İşin kendi aciliyeti — alanın hesapladığı sayı.

    ⚠️ Aciliyetin **anlamı** alana ait: üretimde "eldeki mal kaç gün yeter",
    nakliyede "teslime kaç gün kaldı", vardiyada "kaç gündür boşta". Motor
    bunu hesaplamıyor, yalnızca sıralıyor.

    Hesaplasaydı motora alan bilgisi taşımak gerekirdi ve genellik orada
    biterdi.
    """
    return is_.oncelik


def en_cok_is(is_: Is) -> float:
    """Küçük iş önce — ufka en çok sayıda iş sığsın.

    Aciliyeti hiç dikkate almıyor ve bu bilinçli: ölçütün amacı "en çok işi
    bitirmek". Aciliyetle karışmış bir ölçüt, karşılaştırma tablosunda iki
    seçeneği birbirine benzetir ve tabloyu değersizleştirir.

    ⚠️ Bu ölçüt tek başına tehlikeli: acil ama büyük bir iş sona kalır ve
    stok tükenir. Karşılaştırma tablosundaki "karşılanamayan talep" satırı
    tam bunu görünür kılmak için var.
    """
    return is_.yuk


def en_degerli(is_: Is) -> float:
    """Parasal karşılığı büyük olan önce.

    Tutar `etiketler["tutar"]` içinde taşınıyor: motor sözleşmesinde para
    alanı **yok** ve olmamalı — vardiya planlamasında bir nöbetin "tutarı"
    yoktur.

    ⚠️ Tutar yoksa iş **en sona** düşüyor (`inf` değil büyük bir sayı):
    sonsuz, sıralamada eşitlik kırmayı bozuyor.
    """
    try:
        return -float(is_.etiketler.get("tutar", 0.0))
    except (TypeError, ValueError):
        return 0.0


OLCUTLER: dict[str, Olcut] = {
    "en_acil": en_acil,
    "en_cok_is": en_cok_is,
    "en_degerli": en_degerli,
}

OLCUT_ACIKLAMALARI: dict[str, str] = {
    "en_acil": "en acil önce",
    "en_cok_is": "en çok iş bitir",
    "en_degerli": "en değerli önce",
}

VARSAYILAN_OLCUT = "en_acil"
"""Üretimin bugünkü davranışı. Varsayılanı değiştirmek, hiçbir şey
istemeyen çağıranın planını sessizce değiştirir."""


def olcut_al(ad: str) -> Olcut:
    """Ada göre ölçüt. Bilinmeyen ad **sessizce varsayılana düşmüyor**.

    Düşseydi, yazım hatası olan bir çağrı "en_acil" planı alır ve kullanıcı
    istediği ölçütü aldığını sanırdı. İşletme profilinde aynı disiplin var:
    fazla alan hata veriyor.
    """
    if ad not in OLCUTLER:
        raise KeyError(f"Bilinmeyen ölçüt: {ad}. Tanımlılar: {sorted(OLCUTLER)}")
    return OLCUTLER[ad]


__all__ = [
    "OLCUTLER",
    "OLCUT_ACIKLAMALARI",
    "VARSAYILAN_OLCUT",
    "Olcut",
    "en_acil",
    "en_cok_is",
    "en_degerli",
    "olcut_al",
]
