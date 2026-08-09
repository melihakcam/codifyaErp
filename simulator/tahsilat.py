"""Tahsilat simülasyonu — faturaların gerçekte ne zaman ödendiği (Faz 6).

Stok simülatörü (`run.py`) faturayı sevkiyatın yan ürünü olarak zaten
üretiyor: tarih, SKU, tutar, ödeme vadesi, **planlanan** ödeme tarihi. Ama
tahsilatı hiç modellemiyor — kim aldı, gerçekten ödedi mi, ne kadar geç
ödedi, hiç ödemedi mi?

Bu modül o boşluğu dolduruyor.

## ⚠️ Neden `run.py`'ye dokunulmadı

Fatura döngüsüne müşteri ataması eklemek `tedarik_rng`'den fazladan bir
çekim yapmak demekti. Rastgele akış kayınca **stok tarafındaki her sonuç
değişirdi** — para metriği (%7,6), shadow raporu (9.908 karar), aşırı uyum
testi (9/9), hepsi yeniden ölçülmek zorunda kalırdı ve eski sayılarla
karşılaştırılamazdı.

Bu modül bunun yerine **sonradan** çalışıyor: `run.py`'nin ürettiği
`faturalar` ve `musteri` tablolarını alıp kendi RNG'siyle müşteri ataması
ve ödeme davranışı üretiyor. Stok tarafı bit bazında aynı kalıyor.

## Model

Her müşteriye bir **ödeme davranışı profili** veriliyor:

    gecikme_egilimi   — vadeye ek olarak ortalama kaç gün geç öder
    gecikme_oynakligi — bu gecikmenin standart sapması

⭐ Bu iki sayının **ayrı** olması modelin özü. Ortalaması kötü ama düzenli
ödeyen bir müşteri (hep 40 gün geç) ile ortalaması iyi ama rastgele ödeyen
bir müşteri (10-90 gün arası) çok farklı risklerdir. Birincisi planlanabilir,
ikincisi planlanamaz. Kural motoru bu ayrımı XYZ sınıfıyla yakalayacak —
stoktaki talep oynaklığıyla birebir aynı mantık.

## Patolojiler

Hepsi varsayılan kapalı, `TahsilatPatolojisi` ile açılır:

| patoloji | ne yapar | neden önemli |
|---|---|---|
| `kronik_gecikme` | yüksek ortalama, DÜŞÜK sapma | "kötü ama tahmin edilebilir" — XYZ:X |
| `duzensiz_odeme` | orta ortalama, YÜKSEK sapma | asıl riskli olan — XYZ:Z |
| `sezonluk_tikanma` | belirli aylarda herkes geç öder | sektörel nakit sıkışması |
| `batak` | bazı faturalar hiç ödenmez | karşılık ayırma kararının dayanağı |
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Segmente göre taban gecikme eğilimi — vadeye EK gün.
#
# ⚠️ Anahtarlar `CompanyProfile.musteri_segmentleri` ile birebir aynı olmak
# ZORUNDA. İlk yazımda uydurma segment adları (`perakende`, `bayi`,
# `müteahhit`) kullanıldı; hiçbiri eşleşmedi, her müşteri varsayılana düştü
# ve segment farklılaşması sessizce çalışmadı — dört segmentin dördü de
# ~17 gün ortalama verdi. `test_segment_adlari_profille_uyusuyor` bunu
# kalıcı olarak yakalıyor.
#
# Değerler sektör davranışını yansıtıyor: bireysel peşin/kapıda öder,
# şantiye hakediş bekler.
SEGMENT_GECIKME_EGILIMI: dict[str, float] = {
    "bireysel": 1.5,
    "usta": 7.0,
    "perakendeci": 14.0,
    "santiye": 28.0,
}
VARSAYILAN_GECIKME_EGILIMI = 10.0

# Taban oynaklık, eğilimin oranı olarak. 0,45 → ortalama 20 gün geciken bir
# müşteride sapma ~9 gün. Ölçüldü: bu değer XYZ sınıflarını dengeli dağıtıyor.
TABAN_OYNAKLIK_ORANI = 0.45

# Ödeme hiç yapılmadıysa `gercek_odeme_tarihi` boş kalır ve bu gün sayısı
# sonrasında "batak" sayılır. 180 gün, Türkiye'de şüpheli alacak karşılığı
# için yaygın eşik.
BATAK_ESIGI_GUN = 180


@dataclass(frozen=True)
class TahsilatPatolojisi:
    """Hangi tahsilat patolojilerinin açık olduğu. Hepsi varsayılan kapalı."""

    kronik_gecikme_aktif: bool = False
    kronik_gecikme_musteri_orani: float = 0.12
    kronik_gecikme_ek_gun_araligi: tuple[float, float] = (25.0, 55.0)
    # ⚠️ Kronik gecikenin oynaklığı DÜŞÜK olmalı — "hep 40 gün geç" demek bu.
    kronik_gecikme_oynaklik_orani: float = 0.12

    duzensiz_odeme_aktif: bool = False
    duzensiz_odeme_musteri_orani: float = 0.08
    duzensiz_odeme_oynaklik_orani: float = 1.4

    sezonluk_tikanma_aktif: bool = False
    sezonluk_tikanma_aylar: tuple[int, ...] = (1, 2, 12)  # inşaatta kış
    sezonluk_tikanma_ek_gun: float = 18.0

    batak_aktif: bool = False
    batak_musteri_orani: float = 0.02
    batak_fatura_orani: float = 0.6  # batak müşterinin faturalarının bu oranı ödenmez


@dataclass(frozen=True)
class TahsilatSonucu:
    """`tahsilat_uret` çıktısı."""

    faturalar: pd.DataFrame
    """Girdi faturalar + `musteri_id`, `gercek_odeme_tarihi`, `gecikme_gun`, `odendi`."""

    musteri_profili: pd.DataFrame
    """Müşteri başına atanan davranış: eğilim, oynaklık, patoloji etiketi."""

    patoloji_olaylari: list[dict] = field(default_factory=list)
    """Hangi patolojinin hangi müşteriye uygulandığı — denetim izi."""


def _musteri_profili_uret(
    musteri_df: pd.DataFrame, rng: np.random.Generator, patoloji: TahsilatPatolojisi
) -> tuple[pd.DataFrame, list[dict]]:
    """Her müşteriye gecikme eğilimi + oynaklık atar, patolojileri uygular."""
    n = len(musteri_df)
    segmentler = musteri_df["segment"].to_numpy()

    egilim = np.array(
        [SEGMENT_GECIKME_EGILIMI.get(s, VARSAYILAN_GECIKME_EGILIMI) for s in segmentler],
        dtype=float,
    )
    # Müşteriye özgü sapma: aynı segmentte de herkes aynı değil.
    egilim = np.maximum(0.0, egilim * rng.normal(1.0, 0.30, size=n))
    oynaklik = egilim * TABAN_OYNAKLIK_ORANI

    etiket = np.array(["normal"] * n, dtype=object)
    olaylar: list[dict] = []
    musteri_ids = musteri_df["musteri_id"].to_numpy()

    def _sec(oran: float) -> np.ndarray:
        adet = round(n * oran)
        if adet <= 0:
            return np.array([], dtype=int)
        return rng.choice(n, size=min(adet, n), replace=False)

    if patoloji.kronik_gecikme_aktif:
        for i in _sec(patoloji.kronik_gecikme_musteri_orani):
            egilim[i] = rng.uniform(*patoloji.kronik_gecikme_ek_gun_araligi)
            # ⭐ Oynaklık DÜŞÜRÜLÜYOR: kötü ama tahmin edilebilir.
            oynaklik[i] = egilim[i] * patoloji.kronik_gecikme_oynaklik_orani
            etiket[i] = "kronik_gecikme"
            olaylar.append({"patoloji": "kronik_gecikme", "musteri_id": musteri_ids[i]})

    if patoloji.duzensiz_odeme_aktif:
        for i in _sec(patoloji.duzensiz_odeme_musteri_orani):
            if etiket[i] != "normal":
                continue
            # ⭐ Eğilim ORTA kalıyor, yalnızca oynaklık patlıyor.
            oynaklik[i] = egilim[i] * patoloji.duzensiz_odeme_oynaklik_orani
            etiket[i] = "duzensiz_odeme"
            olaylar.append({"patoloji": "duzensiz_odeme", "musteri_id": musteri_ids[i]})

    batak_musteriler: set[str] = set()
    if patoloji.batak_aktif:
        for i in _sec(patoloji.batak_musteri_orani):
            batak_musteriler.add(musteri_ids[i])
            etiket[i] = "batak"
            olaylar.append({"patoloji": "batak", "musteri_id": musteri_ids[i]})

    profil = pd.DataFrame(
        {
            "musteri_id": musteri_ids,
            "segment": segmentler,
            "odeme_vadesi_gun": musteri_df["odeme_vadesi_gun"].to_numpy(),
            "gecikme_egilimi_gun": egilim,
            "gecikme_oynakligi_gun": oynaklik,
            "patoloji": etiket,
            "batak_mi": [m in batak_musteriler for m in musteri_ids],
        }
    )
    return profil, olaylar


def _faturalari_musteriye_ata(
    faturalar: pd.DataFrame, profil: pd.DataFrame, rng: np.random.Generator
) -> np.ndarray:
    """Her faturayı, vadesi uyan bir müşteriye atar.

    ⚠️ Rastgele atama YAPILMIYOR. `run.py` faturanın vadesini müşteri
    havuzundan çekmişti; vadeyi yok sayıp rastgele atamak, 60 gün vadeli bir
    faturayı peşin çalışan bir perakendeciye yazmak olurdu. Vade uyumu, iki
    modül arasındaki tek tutarlılık bağı.
    """
    atama = np.empty(len(faturalar), dtype=object)
    vade_gruplari = profil.groupby("odeme_vadesi_gun")["musteri_id"].apply(list).to_dict()
    tum_musteriler = profil["musteri_id"].tolist()

    for vade, idx in faturalar.groupby("odeme_vadesi_gun").groups.items():
        havuz = vade_gruplari.get(vade) or tum_musteriler
        konum = faturalar.index.get_indexer(idx)
        atama[konum] = rng.choice(havuz, size=len(konum))

    return atama


def tahsilat_uret(
    faturalar: pd.DataFrame,
    musteri_df: pd.DataFrame,
    seed: int = 101,
    patoloji: TahsilatPatolojisi | None = None,
) -> TahsilatSonucu:
    """Faturalara müşteri ve gerçek ödeme tarihi ekler.

    `faturalar` `run.py`'nin ürettiği tablo: `tarih`, `sku_id`, `tutar_tl`,
    `odeme_vadesi_gun`, `odeme_tarihi` (planlanan).

    ⚠️ Kendi RNG'si var (`seed`), `run.py`'nin akışına dokunmuyor — stok
    tarafındaki ölçümler bit bazında korunuyor.
    """
    patoloji = patoloji or TahsilatPatolojisi()
    rng = np.random.default_rng(seed)

    if faturalar.empty:
        return TahsilatSonucu(faturalar=faturalar.copy(), musteri_profili=pd.DataFrame())

    profil, olaylar = _musteri_profili_uret(musteri_df, rng, patoloji)
    f = faturalar.reset_index(drop=True).copy()
    f["musteri_id"] = _faturalari_musteriye_ata(f, profil, rng)

    p = profil.set_index("musteri_id")
    egilim = f["musteri_id"].map(p["gecikme_egilimi_gun"]).to_numpy()
    oynaklik = f["musteri_id"].map(p["gecikme_oynakligi_gun"]).to_numpy()
    batak_mi = f["musteri_id"].map(p["batak_mi"]).to_numpy()

    gecikme = rng.normal(egilim, np.maximum(oynaklik, 1e-9))

    if patoloji.sezonluk_tikanma_aktif:
        ay = pd.to_datetime(f["odeme_tarihi"]).dt.month.to_numpy()
        tikanik = np.isin(ay, patoloji.sezonluk_tikanma_aylar)
        gecikme = gecikme + tikanik * patoloji.sezonluk_tikanma_ek_gun

    # Erken ödeme mümkün ama nadir; negatif gecikme -3 günle sınırlanıyor.
    gecikme = np.maximum(gecikme, -3.0)

    odenmedi = batak_mi & (rng.random(len(f)) < patoloji.batak_fatura_orani)

    gercek = pd.to_datetime(f["odeme_tarihi"]) + pd.to_timedelta(np.round(gecikme), unit="D")
    f["gercek_odeme_tarihi"] = gercek.where(~odenmedi)
    f["gecikme_gun"] = np.where(odenmedi, np.nan, np.round(gecikme))
    f["odendi"] = ~odenmedi

    return TahsilatSonucu(faturalar=f, musteri_profili=profil, patoloji_olaylari=olaylar)


def acik_alacaklar(faturalar: pd.DataFrame, olcum_tarihi: dt.date) -> pd.DataFrame:
    """`olcum_tarihi` itibarıyla henüz tahsil edilmemiş faturalar.

    Bir fatura o tarihte açıktır eğer kesilmişse ve (hiç ödenmemişse ya da
    ödemesi o tarihten sonraysa). İkinci koşul kritik: bugün bakarken
    "yarın ödenecek" bilgisini kullanmak geleceği görmek olurdu.
    """
    ts = pd.Timestamp(olcum_tarihi)
    kesilmis = pd.to_datetime(faturalar["tarih"]) <= ts
    odeme = pd.to_datetime(faturalar["gercek_odeme_tarihi"])
    acik = odeme.isna() | (odeme > ts)

    d = faturalar[kesilmis & acik].copy()
    d["gecikme_gun_bugun"] = (ts - pd.to_datetime(d["odeme_tarihi"])).dt.days
    return d


__all__ = [
    "BATAK_ESIGI_GUN",
    "SEGMENT_GECIKME_EGILIMI",
    "TahsilatPatolojisi",
    "TahsilatSonucu",
    "acik_alacaklar",
    "tahsilat_uret",
]
