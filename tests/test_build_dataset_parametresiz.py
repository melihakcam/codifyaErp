"""`gecelik_ozet_sorgula` eğitim verisinde parametresiz tek örnek yoktu (184/0).

Ölçüm setlerinde ise bu araç 10 sorunun 9'unda parametresiz soruluyor. Model
hiç görmediği bir durumu üretmek zorunda kalınca tarih uydurdu
(`tarih_ifadesi="geçen gün"` — eğitimdeki dört geçerli değerin hiçbiri) ve bu
araçtaki tam doğruluk taban modelin 7/10'undan 3. turda 1/10'a düştü.

Bu testler boşluğun geri açılmamasını koruyor. Ayrıntı:
`dokumantasyon/OLCUMLER.md`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from training.build_dataset import (
    ARAC_TANIMLARI,
    TARIH_IFADELERI,
    router_veri_seti_uret,
    sablonlari_ihrac_et,
)

OLCUM_DOSYALARI = (
    Path("training/eval/router_taban_sorulari.jsonl"),
    Path("training/eval/router_ek_sorular.jsonl"),
)


def _sahte_kataloglar() -> tuple[pd.DataFrame, pd.DataFrame]:
    sku_df = pd.DataFrame([{"sku_id": f"S-{i:05d}", "sku_adi": f"Ürün {i}"} for i in range(1, 6)])
    tedarikci_df = pd.DataFrame([{"tedarikci_id": f"T-{i:04d}"} for i in range(1, 4)])
    return sku_df, tedarikci_df


def _gecelik_satirlari() -> pd.DataFrame:
    sku_df, tedarikci_df = _sahte_kataloglar()
    df = router_veri_seti_uret(sku_df, tedarikci_df, sku_ornek_sayisi=5)
    return df[df["arac"] == "gecelik_ozet_sorgula"]


def test_gecelik_ozet_parametresiz_ornek_uretiyor():
    """Asıl regresyon: bu sayı 0 olursa 3. turdaki çöküş geri gelir."""
    gecelik = _gecelik_satirlari()
    parametresiz = gecelik[gecelik["parametreler"].map(lambda p: not p)]

    tanim = next(a for a in ARAC_TANIMLARI if a.isim == "gecelik_ozet_sorgula")

    assert len(parametresiz) > 0, "gecelik_ozet parametresiz örnek üretmiyor"
    assert len(parametresiz) == len(tanim.parametresiz_sablonlar)


def test_parametresiz_sablonlarda_tarih_ifadesi_gecmiyor():
    """Tarih geçen bir soru parametresiz etiketlenirse model YANLIŞ öğrenir.

    Bu, kapatmaya çalıştığımız hatanın tam tersi: modele "tarih görsen bile
    parametre üretme" demek olurdu.
    """
    gecelik = _gecelik_satirlari()
    parametresiz = gecelik[gecelik["parametreler"].map(lambda p: not p)]

    for soru in parametresiz["soru"]:
        dusuk = soru.casefold()
        gecenler = [t for t in TARIH_IFADELERI if t in dusuk]
        assert not gecenler, f"parametresiz şablonda tarih ifadesi var: {soru!r} -> {gecenler}"


def test_parametreli_ornekler_korundu():
    """Parametresiz örnek eklemek parametreli olanları düşürmemeli."""
    gecelik = _gecelik_satirlari()
    parametreli = gecelik[gecelik["parametreler"].map(bool)]

    assert len(parametreli) >= 30, "parametreli gecelik örnekleri kayboldu"
    degerler = {p["tarih_ifadesi"] for p in parametreli["parametreler"]}
    assert degerler == set(TARIH_IFADELERI)


def test_parametresiz_sablonlar_olcum_setleriyle_cakismiyor():
    """Sızıntı kapısı: eğitim şablonu ölçüm sorusuyla aynı olmamalı.

    Ölçüm setleri elle yazıldı ve donmuş durumda; bir şablonu oradan
    kopyalamak "eğitim işe yaradı mı" sorusunu geçersiz kılardı.
    """
    olcum_sorulari = set()
    for yol in OLCUM_DOSYALARI:
        for satir in yol.read_text(encoding="utf-8").splitlines():
            if satir.strip():
                olcum_sorulari.add(json.loads(satir)["soru"].strip().casefold())

    gecelik = _gecelik_satirlari()
    parametresiz = gecelik[gecelik["parametreler"].map(lambda p: not p)]

    cakisan = [s for s in parametresiz["soru"] if s.strip().casefold() in olcum_sorulari]
    assert not cakisan, f"ölçüm setiyle çakışan şablon: {cakisan}"


def _kelimeler(metin: str) -> set[str]:
    from training.eval.router_taban import aksansiz

    return set(re.findall(r"[^\W\d_]+", aksansiz(metin)))


def _en_yakin_olcum_sorusu(aday: str) -> tuple[float, str]:
    """Adayın ölçüm setindeki en benzer soruyla Jaccard benzerliği."""
    sorular = []
    for yol in OLCUM_DOSYALARI:
        for satir in yol.read_text(encoding="utf-8").splitlines():
            if satir.strip():
                d = json.loads(satir)
                if d["arac"] == "gecelik_ozet_sorgula":
                    sorular.append(d["soru"])

    aday_k = _kelimeler(aday)
    en_iyi = max(
        sorular,
        key=lambda s: len(aday_k & _kelimeler(s)) / max(1, len(aday_k | _kelimeler(s))),
    )
    ortak = aday_k & _kelimeler(en_iyi)
    birlesim = aday_k | _kelimeler(en_iyi)
    return len(ortak) / max(1, len(birlesim)), en_iyi


# Sızıntı yalnızca birebir kopyayla olmaz. Ölçüm sorusuna çok yakın bir eğitim
# cümlesi de o soruyu sınav öncesi modele göstermek demektir ve ölçümü şişirir.
#
# ⚠️ Eşik ölçülerek kondu, tahminle değil: elle yazılmış şablonlar doğal olarak
# en fazla 0,33'e çıkıyor (kısa sorular ortak kelime paylaşır). Paraphrase
# turunun ürettiği "Sistem gece ne buldu?" ise "Dün gece sistem ne buldu?" ile
# **0,80** çıktı — o yüzden alınmadı. 0,50 ikisinin arasında geniş paylı bir yer.
OLCUM_YAKINLIK_SINIRI = 0.50


def test_parametresiz_sablonlar_olcum_setine_yakin_degil():
    tanim = next(a for a in ARAC_TANIMLARI if a.isim == "gecelik_ozet_sorgula")

    fazla_yakin = []
    for sablon in tanim.parametresiz_sablonlar:
        oran, en_yakin = _en_yakin_olcum_sorusu(sablon)
        if oran >= OLCUM_YAKINLIK_SINIRI:
            fazla_yakin.append(f"{oran:.2f} {sablon!r} ~ {en_yakin!r}")

    assert not fazla_yakin, "ölçüm sorusuna fazla yakın şablon:\n" + "\n".join(fazla_yakin)


def test_paraphrase_turundan_gelen_sizintili_aday_reddedilirdi():
    """Kapının gerçekten çalıştığının kanıtı.

    Paraphrase turu bu cümleyi üretti ve elenmesinin sebebi tam olarak buydu.
    """
    oran, _ = _en_yakin_olcum_sorusu("Sistem gece ne buldu?")

    assert oran >= OLCUM_YAKINLIK_SINIRI


def test_parametresiz_sablonlar_ihracta_varlik_almiyor():
    """Paraphrase turuna `varlik_turu="yok"` ile gitmeliler.

    Kendi varlık türleriyle (`tarih_ifadesi`) gitselerdi yeniden çoğaltma
    adımı onları tarihlerle çarpar ve boşluğu geri açardı.
    """
    df = sablonlari_ihrac_et({"gecelik_ozet_sorgula"})
    parametresiz = df[df["varlik_turu"] == "yok"]

    assert len(parametresiz) > 0, "parametresiz şablonlar ihraç edilmiyor"
    assert (parametresiz["placeholder_token"] == "").all()
    assert (df[df["varlik_turu"] == "tarih_ifadesi"]["placeholder_token"] == "ZAMAN_IFADESI").all()
