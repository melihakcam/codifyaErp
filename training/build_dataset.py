"""Karar noktası örnekleme + router soru şablonları -> JSONL.

Sahip: Kişi A · Faz 3 A3.1-A3.2

**A3.1:** Simülasyon zaman çizgisinden (SKU x hafta) karar noktaları örnekler,
her nokta için `StockFeatures` çıkarır, `decide.ozellikten_karar_uret` ile
kural motorunu çalıştırır — çıkan karar **etikettir**. Etiket deterministik
kural motorundan geldiği için halüsinasyon imkânsızdır.

    Etiket kural motorundan gelir, dolayısıyla halüsinasyon imkânsız.

Sınıf dengesi kasıtlı olarak zorlanmaz — haftalık rastgele örnekleme,
gerçekte ROP altına düşen ve düşmeyen anların doğal oranını yansıtır. Bu
oran raporlanır; aşırı dengesizse (`STOK_AKSIYON_YOK` %95'i geçerse) örnekleme
stratejisi (haftalık yerine iki haftalık, veya ROP'a yakın anları ağırlıklı
örnekleme) gözden geçirilmelidir.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from app.domain.stock.decide import ozellikten_karar_uret
from app.domain.stock.features import katalog_ozelliklerini_hesapla
from app.domain.stock.rules import abc_xyz_siniflandir, tedarikci_skoru_hesapla
from simulator.company import yapi_malzemesi_toptancisi
from simulator.run import simulasyon_calistir

ISINMA_GUN = 90
"""İlk N gün örnekleme dışı tutulur — 90 günlük kayan pencerenin (features.py)
henüz dolmadığı erken dönemde özellikler güvenilir değildir."""

HAFTA_GUN = 7
VARSAYILAN_HEDEF_NOKTA_SAYISI = 50_000


def _siniflandirmayi_hesapla(sonuc: dict) -> pd.DataFrame:
    """ABC/XYZ + tedarikçi skorunu simülasyonun son gününe göre bir kerelik hesaplar.

    Gerçek sistemde de sınıflandırma periyodiktir (haftalık değil) — burada
    tüm örnekleme boyunca sabit tutulması bunun eğitim-verisi karşılığıdır.
    """
    sku_df = sonuc["sku"]
    olcum_tarihi = sonuc["envanter_gunluk"]["tarih"].max().date()
    on_ozellikler = katalog_ozelliklerini_hesapla(
        olcum_tarihi=olcum_tarihi,
        talep=sonuc["talep"],
        envanter_gunluk=sonuc["envanter_gunluk"],
        sku_df=sku_df,
        tedarikci_df=sonuc["tedarikci"],
    )
    siniflandirma = abc_xyz_siniflandir(on_ozellikler)

    tedarikci_skorlari = tedarikci_skoru_hesapla(sonuc["siparisler"], sonuc["tedarikci"])
    sku_tedarikci = sku_df.set_index("sku_id")["tedarikci_id"]
    siniflandirma["tedarikci_skoru"] = sku_tedarikci.map(tedarikci_skorlari["tedarikci_skoru"])
    return siniflandirma


def karar_noktasi_veri_seti_uret(
    sonuc: dict,
    hedef_nokta_sayisi: int = VARSAYILAN_HEDEF_NOKTA_SAYISI,
    isinma_gun: int = ISINMA_GUN,
    hafta_gun: int = HAFTA_GUN,
    seed: int = 7,
) -> pd.DataFrame:
    """~`hedef_nokta_sayisi` karar noktası (sku_id, tarih, özellikler, karar) örnekler.

    Performans için örnekleme **hafta bazında** gruplanır: her hafta tek bir
    rastgele gün seçilir, o günde tüm katalog yerine rastgele bir SKU alt
    kümesi için `katalog_ozelliklerini_hesapla` **tek seferde** (vektörize)
    çağrılır — 50.000 nokta için 50.000 ayrı tekil sorgu yerine ~150 toplu
    sorgu yapılır.
    """
    rng = np.random.default_rng(seed)
    sku_df = sonuc["sku"]
    n_sku = len(sku_df)
    sku_ids = sku_df["sku_id"].to_numpy()

    tarihler = pd.DatetimeIndex(sorted(sonuc["envanter_gunluk"]["tarih"].unique()))
    gecerli_tarihler = tarihler[isinma_gun:]
    hafta_sayisi = len(gecerli_tarihler) // hafta_gun
    if hafta_sayisi == 0:
        raise ValueError("Isınma günü sonrası en az bir hafta veri gerekiyor.")

    nokta_basina_sku = max(1, min(n_sku, round(hedef_nokta_sayisi / hafta_sayisi)))

    siniflandirma = _siniflandirmayi_hesapla(sonuc)

    # Her hafta yeniden filtrelemek yerine bir kere indexlenir (bkz. aşağıdaki
    # performans notu) — sku_id ve tarih bazında hızlı `.loc` erişimi için.
    talep_indeksli = sonuc["talep"].set_index("sku_id").sort_index()
    envanter_tarih_indeksli = sonuc["envanter_gunluk"].set_index("tarih").sort_index()

    kayitlar: list[dict] = []
    for hafta in range(hafta_sayisi):
        gun_ofset = int(rng.integers(0, hafta_gun))
        tarih = gecerli_tarihler[hafta * hafta_gun + gun_ofset]

        secilen_sku_id = rng.choice(sku_ids, size=nokta_basina_sku, replace=False)
        secilen_sku_kumesi = set(secilen_sku_id)
        alt_sku_df = sku_df[sku_df["sku_id"].isin(secilen_sku_kumesi)]

        # Performans: 2.19M satırlık tam talep/envanter tablosunu her hafta
        # yeniden pivot etmek yerine, o haftanın SKU alt kümesine önceden
        # filtrelenmiş küçük bir dilim geçilir. features.py yalnızca
        # `sku_df`'deki SKU'ları pivot ediyor olsa da, girdi olarak verilen
        # `talep`/`envanter_gunluk` tam boyutta olursa pivot/filtre işlemi
        # yine de tüm 2.19M satır üzerinde çalışır — bu 143 kez tekrarlanınca
        # çok yavaşlar.
        alt_talep = talep_indeksli.loc[list(secilen_sku_kumesi)].reset_index()
        alt_envanter = envanter_tarih_indeksli.loc[[tarih]].reset_index()
        alt_envanter = alt_envanter[alt_envanter["sku_id"].isin(secilen_sku_kumesi)]

        ozellikler = katalog_ozelliklerini_hesapla(
            olcum_tarihi=tarih.date(),
            talep=alt_talep,
            envanter_gunluk=alt_envanter,
            sku_df=alt_sku_df,
            tedarikci_df=sonuc["tedarikci"],
            siniflandirma=siniflandirma,
        )

        for ozellik in ozellikler:
            karar = ozellikten_karar_uret(ozellik)
            kayitlar.append(
                {
                    "sku_id": ozellik.sku_id,
                    "tarih": tarih.date().isoformat(),
                    "ozellikler": json.loads(ozellik.model_dump_json()),
                    "karar_tipi": karar.tip.value,
                    "aksiyon": karar.aksiyon,
                    "tahmini_tutar_tl": karar.tahmini_tutar_tl,
                    "guven": round(karar.guven, 4),
                    "tetiklenen_kurallar": [
                        json.loads(k.model_dump_json()) for k in karar.tetiklenen_kurallar
                    ],
                    "izinli_sayilar": sorted(karar.izinli_sayilar()),
                }
            )

    return pd.DataFrame(kayitlar)


def jsonl_yaz(df: pd.DataFrame, yol: Path) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    with open(yol, "w", encoding="utf-8") as f:
        for kayit in df.to_dict(orient="records"):
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# A3.2 — Router soru şablonları
# ---------------------------------------------------------------------------
#
# ⚠️ GEÇİCİ ARAÇ LİSTESİ. Kişi B'nin router'ı (`app/llm/router.py`,
# `app/api/ask.py`, `app/llm/schemas.py`) henüz yazılmadı (Faz 2 B2.2-B2.3,
# B1'den sonra sırada) — bu yüzden aşağıdaki 7 araç, gerçek bir şemaya değil,
# YOL-HARITASI.md'deki tek somut ipucuna ("elimizde kritik seviyeye düşen
# ürün var mı?" → router doğru aracı seçmeli) ve mevcut API stub'larına
# (decisions/approvals/insights/feedback) dayanan makul bir tahmindir.
# Kişi B gerçek router şemasını yazınca ARAC_TANIMLARI güncellenip bu veri
# seti yeniden üretilir — o zamana kadar router eğitiminin baştan sona
# çalıştığını kanıtlamak için yeterlidir.


@dataclass(frozen=True)
class AracTanimi:
    isim: str
    aciklama: str
    varlik_turu: str  # "kategori" | "tedarikci_id" | "sku_id" | "tarih_ifadesi" | "yok"
    sablonlar: tuple[str, ...]


KATEGORILER = ("çimento", "demir", "tuğla", "alçı", "boya", "seramik", "izolasyon", "hırdavat")
TARIH_IFADELERI = ("bugün", "dün", "bu hafta", "geçen hafta")

ARAC_TANIMLARI: tuple[AracTanimi, ...] = (
    AracTanimi(
        isim="kritik_stok_sorgula",
        aciklama="ROP altına düşen / kritik stok seviyesindeki ürünleri listeler",
        varlik_turu="kategori",
        sablonlar=(
            "{varlik}Kritik stok seviyesine düşen ürünleri listeler misiniz?",
            "{varlik}Yeniden sipariş noktasının altına düşmüş SKU'ları raporlar mısınız?",
            "{varlik}Stok seviyesi kritik olan ürünlerin dökümünü alabilir miyim?",
            "{varlik}Acil sipariş verilmesi gereken ürünleri bildirir misiniz?",
            "{varlik}hangi ürünlerde stok azaldı?",
            "{varlik}stoğu biten ya da bitmek üzere olan ürün var mı?",
            "{varlik}tükenmek üzere olan ürünleri gösterir misin?",
            "{varlik}stok seviyesi düşük olanlar hangileri?",
            "{varlik}kritik stok var mı",
            "{varlik}stok durumu ne",
            "{varlik}azalan urun var mi",
            "{varlik}acil siparis gereken var mi",
            "{varlik}stok durmu ne",
            "{varlik}kritk stok hangi urunlerde",
            "{varlik}hangi urunler tukenmek uzre",
            "{varlik}stoğu azalanlari yazarmısın",
        ),
    ),
    AracTanimi(
        isim="olu_stok_sorgula",
        aciklama="Uzun süredir hareketsiz, tasfiye/iskonto önerilen ürünleri listeler",
        varlik_turu="kategori",
        sablonlar=(
            "{varlik}Ölü stok durumundaki ürünleri listeler misiniz?",
            "{varlik}Uzun süredir hareket görmeyen ürünlerin raporunu alabilir miyim?",
            "{varlik}Tasfiye edilmesi önerilen ürünler hangileri?",
            "{varlik}İskonto uygulanması gereken ürünleri bildirir misiniz?",
            "{varlik}hangi ürünler aylardır satılmıyor?",
            "{varlik}elimizde bekleyen, satılmayan ürün var mı?",
            "{varlik}durgun stok var mı?",
            "{varlik}hareketsiz ürünleri gösterir misin?",
            "{varlik}olu stok var mi",
            "{varlik}satilmayan urun hangileri",
            "{varlik}tasfiye onerisi var mi",
            "{varlik}iskonto onerlen urun var mi",
            "{varlik}hangi urunler aylardirsatilmiyo",
            "{varlik}durgn stok listesi",
        ),
    ),
    AracTanimi(
        isim="tedarikci_performansi_sorgula",
        aciklama="Tedarikçi performans skorunu (teslimat, tutarlılık) sorgular",
        varlik_turu="tedarikci_id",
        sablonlar=(
            "{varlik}performansı hakkında bilgi verir misiniz?",
            "{varlik}teslimat performansını raporlar mısınız?",
            "{varlik}skoru kaç, değerlendirir misiniz?",
            "{varlik}zamanında teslimat oranı nedir?",
            "{varlik}performansı nasıl?",
            "{varlik}iyi bir tedarikçi mi?",
            "{varlik}gecikme yaşıyor mu?",
            "{varlik}skoru ne",
            "{varlik}performans nasil",
            "{varlik}gecikiyomu",
            "{varlik}performnsi nasil",
            "en kötü performans gösteren tedarikçi hangisi?",
            "en iyi tedarikçimiz kim?",
            "hangi tedarikçi sürekli gecikiyor?",
        ),
    ),
    AracTanimi(
        isim="siparis_onerisi_sorgula",
        aciklama="Belirli bir ürün için sipariş kararını (miktar, tedarikçi, gerekçe) sorgular",
        varlik_turu="sku_id",
        sablonlar=(
            "{varlik}için sipariş verilmesi gerekiyor mu?",
            "{varlik}için ne kadar sipariş vermeliyim?",
            "{varlik}ürünü için sipariş önerisini alabilir miyim?",
            "{varlik}stok durumu ve sipariş kararı nedir?",
            "{varlik}ne kadar sipariş vermek lazım?",
            "{varlik}sipariş vermeli miyiz?",
            "{varlik}kaç adet alalım?",
            "{varlik}icin siparis lazim mi",
            "{varlik}ne kadar alalim",
            "{varlik}siparis onerisi ne",
            "{varlik}icin kac adet siparis vericez",
            "{varlik}siparis verilcekmi",
        ),
    ),
    AracTanimi(
        isim="onay_kuyrugu_sorgula",
        aciklama="İnsan onayı bekleyen kararları listeler",
        varlik_turu="yok",
        sablonlar=(
            "Onay bekleyen kararları listeler misiniz?",
            "Onay kuyruğunda ne var?",
            "İncelenmemiş kararlar hangileri?",
            "Onayımı bekleyen işlemler var mı?",
            "onay bekleyenler neler",
            "kuyrukta ne var",
            "onaylanacak bir şey var mı?",
            "onay kuyrgunda nevar",
            "bekleyen onay var mi",
            "inceleme bekleyenler",
        ),
    ),
    AracTanimi(
        isim="gecelik_ozet_sorgula",
        aciklama="Gecelik toplu işin ürettiği Türkçe içgörü özetini sorgular",
        varlik_turu="tarih_ifadesi",
        sablonlar=(
            "{varlik}için hazırlanan özeti alabilir miyim?",
            "{varlik}ne oldu, özetler misiniz?",
            "{varlik}gecelik raporu paylaşır mısınız?",
            "{varlik}öne çıkan gelişmeler neler?",
            "{varlik}durum özeti nedir?",
            "{varlik}ozet nedir",
            "{varlik}ne olmus",
            "{varlik}rapor varmi",
            "{varlik}one cikan bisi varmi",
        ),
    ),
    AracTanimi(
        isim="genel_stok_durumu_sorgula",
        aciklama="ABC/XYZ dağılımı, toplam stok değeri gibi genel KPI'ları sorgular",
        varlik_turu="yok",
        sablonlar=(
            "Genel stok durumumuz nasıl?",
            "Toplam stok değerini alabilir miyim?",
            "ABC/XYZ dağılımını gösterir misiniz?",
            "Envanterin genel özetini paylaşır mısınız?",
            "stoklar nasıl gidiyor",
            "genel durum ne",
            "stok ozet",
            "envanter nasil",
            "genel tablo nedir",
        ),
    ),
)


def _varlik_ifadesi(varlik_turu: str, goruntu: str) -> str:
    if varlik_turu == "kategori":
        return "" if goruntu == "genel" else f"{goruntu} kategorisinde "
    if varlik_turu == "tedarikci_id":
        return "" if goruntu == "genel" else f"{goruntu} tedarikçisinin "
    if varlik_turu in ("sku_id", "tarih_ifadesi"):
        return f"{goruntu} "
    return ""


def _varlik_ornekle(
    varlik_turu: str,
    sku_df: pd.DataFrame,
    tedarikci_df: pd.DataFrame,
    rng: np.random.Generator,
    sku_ornek_sayisi: int,
) -> list[tuple[str, str]]:
    """(görüntü_metni, parametre_değeri) çiftleri döner.

    `sku_id` için görüntü metni yalnızca isim OLAMAZ — katalogdaki ürün
    isimleri sınırlı sayıda şablon+marka kombinasyonundan üretildiği için
    (bkz. `simulator/catalog.py`) aynı isim onlarca farklı SKU'da tekrarlanır.
    Yalnızca isim kullanılsaydı `drop_duplicates` bu tekrarları eleyip veri
    setini hedeflenen ~30.000'in çok altına düşürüyordu (ilk denemede 1.884
    çıktı, beklenen ~24.000'in bir kısmı). Görüntü metnine SKU ID'sini de
    eklemek hem gerçekçidir (bir ERP kullanıcısı ürünü kodla da belirtebilir)
    hem de benzersizliği garanti eder. `parametre_degeri` zaten hep SKU ID
    taşıyordu (görüntü metni değil) — parametre anahtarı da buna uysun diye
    `sku_adi` yerine `sku_id` kullanılıyor (bkz. B'nin bulduğu isimlendirme
    tutarsızlığı, aciklama.md).
    """
    if varlik_turu == "kategori":
        return [(k, k) for k in (*KATEGORILER, "genel")]
    if varlik_turu == "tedarikci_id":
        return [(t, t) for t in (*tedarikci_df["tedarikci_id"].tolist(), "genel")]
    if varlik_turu == "sku_id":
        n = min(sku_ornek_sayisi, len(sku_df))
        alt_kume = sku_df.sample(n=n, random_state=rng.integers(0, 2**31 - 1))
        return [
            (f"{satir.sku_adi} ({satir.sku_id})", satir.sku_id)
            for satir in alt_kume.itertuples(index=False)
        ]
    if varlik_turu == "tarih_ifadesi":
        return [(t, t) for t in TARIH_IFADELERI]
    return [("", "")]


def router_veri_seti_uret(
    sku_df: pd.DataFrame,
    tedarikci_df: pd.DataFrame,
    seed: int = 11,
    sku_ornek_sayisi: int = 2000,
) -> pd.DataFrame:
    """`Şablon x varlık = veri`. Her araç için varlık örnekleriyle çarpılmış
    soru-araç çiftleri üretir. `varlik_turu="yok"` olan araçlar yalnızca
    şablon çeşitliliğinden (stil: resmi/günlük/kısaltmalı/yazım hatalı) veri
    alır — bunlarda gerçek bir "varlık" kavramı yoktur.
    """
    rng = np.random.default_rng(seed)
    kayitlar: list[dict] = []

    for arac in ARAC_TANIMLARI:
        varliklar = _varlik_ornekle(arac.varlik_turu, sku_df, tedarikci_df, rng, sku_ornek_sayisi)
        for sablon in arac.sablonlar:
            for goruntu, parametre_degeri in varliklar:
                if "{varlik}" in sablon:
                    soru = sablon.format(varlik=_varlik_ifadesi(arac.varlik_turu, goruntu))
                else:
                    soru = sablon
                soru = soru[0].upper() + soru[1:] if soru else soru
                if parametre_degeri in ("", "genel"):
                    parametreler = {}
                else:
                    parametreler = {arac.varlik_turu: parametre_degeri}
                kayitlar.append({"soru": soru, "arac": arac.isim, "parametreler": parametreler})

    df = pd.DataFrame(kayitlar).drop_duplicates(subset="soru").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# A3.3 — Şablon başkalaştırma (paraphrase) için hazırlık + yeniden çoğaltma
# ---------------------------------------------------------------------------
#
# İlk Colab denemesinde 24.999 satırın HER BİRİNİ ayrı ayrı LLM'e gönderdik —
# 100 satır 357 saniye sürdü, tüm veri seti için ~25 saate karşılık geliyordu
# (Colab'ın ücretsiz oturum sınırı ~12 saat). Oysa gerçekte yalnızca ~100
# benzersiz ŞABLON var, geri kalan 24.899 satır aynı şablonun farklı
# ürün/kategori/tedarikçi ile doldurulmuş halidir. Çözüm: yalnızca şablonları
# başkalaştır (placeholder token'la), sonra aynı entity çarpımını paraphrase
# edilmiş şablona **yerelde, GPU'suz** yeniden uygula — ~250x daha az LLM
# çağrısı, saniyeler içinde tamamlanan bir yeniden çoğaltma adımı.

PLACEHOLDER_TOKENLARI: dict[str, str] = {
    "kategori": "KATEGORI_ADI",
    "tedarikci_id": "TEDARIKCI_KODU",
    "sku_id": "URUN_ADI",
    "tarih_ifadesi": "ZAMAN_IFADESI",
    "yok": "",
}
"""Her varlık türü için, LLM'e gönderilecek şablon metninde gerçek değerin
yerini tutan sabit bir kelime. LLM'den bu kelimeyi DEĞİŞTİRMEDEN cümlenin
içinde tutması istenir (Colab notebook'undaki prompt'ta) — böylece
başkalaştırılmış metne geri dönüp gerçek varlıkları yerleştirebiliriz."""


def sablonlari_ihrac_et(yalnizca_araclar: set[str] | None = None) -> pd.DataFrame:
    """LLM'e gönderilecek ~100 benzersiz şablonu (placeholder token'lı) çıkarır.

    `yalnizca_araclar` verilirse yalnızca o araçların şablonları çıkarılır —
    B'nin bulduğu sorunu (seyrek araçların ~10-14 satırı, sınıf ağırlıklı
    örneklemede aynı 10-14 örneğin yüzlerce kez tekrarlanıp ezberletmesi
    riski) çözmek için: bu araçların şablonlarını **daha yüksek `n`** ile
    yeniden başkalaştırıp gerçek çeşitlilik üretmek üzere hedeflenmiş, ucuz
    bir Colab turu yapılabilsin diye. Tüm ~84 şablonu tekrar göndermeye
    gerek yok.

    Dönen DataFrame Colab'a yüklenip başkalaştırılacak, sonra
    `parafraz_sablonlarindan_veri_uret` ile yerelde yeniden çoğaltılacak.
    """
    kayitlar = []
    for arac in ARAC_TANIMLARI:
        if yalnizca_araclar is not None and arac.isim not in yalnizca_araclar:
            continue
        token = PLACEHOLDER_TOKENLARI[arac.varlik_turu]
        varlik_ifadesi = _varlik_ifadesi(arac.varlik_turu, token) if token else ""
        for sablon in arac.sablonlar:
            metin = sablon.format(varlik=varlik_ifadesi) if "{varlik}" in sablon else sablon
            metin = metin[0].upper() + metin[1:] if metin else metin
            kayitlar.append(
                {
                    "arac": arac.isim,
                    "varlik_turu": arac.varlik_turu,
                    "placeholder_token": token,
                    "sablon_metni": metin,
                }
            )
    return pd.DataFrame(kayitlar)


_YER_TUTUCU_TEKRAR_DESENLERI: dict[str, re.Pattern[str]] = {
    # `_varlik_ifadesi()` bu varlık türleri için sabit bir sonek üretir
    # ("X tedarikçisinin ", "Y kategorisinde "). Paraphrase LLM'i şablonu
    # yeniden yazarken bazen aynı kelimeyi cümlede başka bir yere de
    # ekliyor; token yerine geçen sonek ile çakışınca bitişik tekrar
    # oluşuyor ("T-0005 tedarikçisinin tedarikçinin gecikiyomu var mı?").
    #
    # ⚠️ Bulgu: golden set'in %30,6'sında (49/160) bu desen vardı,
    # `tedarikci_performansi_sorgula`'da %60,3'e çıkıyordu — ortak onaydan
    # önce fark edildi (bkz. dokumantasyon/OLCUMLER.md, golden set
    # incelemesi). Kaynağı burası: paraphrase LLM'e gönderilmeden önce bile
    # şablon zaten "TEDARIKCI_KODU tedarikçisinin ..." biçimindeydi
    # (`sablonlari_ihrac_et`), LLM onu yeniden yazarken kelimeyi bir kez
    # daha kullanabiliyordu.
    "tedarikci_id": re.compile(r"\btedarikçisinin\s+tedarikç\w*\b", re.IGNORECASE),
    "kategori": re.compile(r"\bkategorisinde\s+kategorisinde\b", re.IGNORECASE),
}


def yer_tutucu_tekrarini_temizle(soru: str, varlik_turu: str) -> str:
    """Bitişik "X sonekinin sonekinin/soneki" tekrarını tek kelimeye indirir.

    Yalnızca **bitişik** tekrarı temizler — cümlenin başka bir yerinde
    doğal bir tekrar varsa (ör. "tedarikçi güvenilir mi, bu tedarikçiyle
    devam edelim mi?") dokunmaz, çünkü o gerçek bir tekrar değil.
    """
    desen = _YER_TUTUCU_TEKRAR_DESENLERI.get(varlik_turu)
    if desen is None:
        return soru
    tekli = "tedarikçisinin" if varlik_turu == "tedarikci_id" else "kategorisinde"
    return desen.sub(tekli, soru, count=1)


def parafraz_sablonlarindan_veri_uret(
    parafraz_df: pd.DataFrame,
    sku_df: pd.DataFrame,
    tedarikci_df: pd.DataFrame,
    seed: int = 11,
    sku_ornek_sayisi: int = 2000,
) -> pd.DataFrame:
    """Colab'dan dönen başkalaştırılmış şablonları gerçek varlıklarla çarpar.

    `parafraz_df` kolonları: `arac`, `varlik_turu`, `placeholder_token`,
    `sablon_metni` (artık LLM tarafından yeniden yazılmış, placeholder
    token'ı hâlâ içeren metin).
    """
    rng = np.random.default_rng(seed)
    kayitlar: list[dict] = []

    for satir in parafraz_df.itertuples(index=False):
        varliklar = _varlik_ornekle(satir.varlik_turu, sku_df, tedarikci_df, rng, sku_ornek_sayisi)
        # pandas None'ı NaN (float) yapar — `isinstance` ile güvenli kontrol.
        token = satir.placeholder_token if isinstance(satir.placeholder_token, str) else None
        for goruntu, parametre_degeri in varliklar:
            if token:
                varlik_ifadesi = _varlik_ifadesi(satir.varlik_turu, goruntu).strip()
                if token not in satir.sablon_metni:
                    continue  # guard: token korunmamışsa bu satır güvenilmez, atla
                soru = satir.sablon_metni.replace(token, varlik_ifadesi)
                soru = yer_tutucu_tekrarini_temizle(soru, satir.varlik_turu)
            else:
                soru = satir.sablon_metni
            soru = " ".join(soru.split())  # fazla boşlukları temizle

            if parametre_degeri in ("", "genel"):
                parametreler = {}
            else:
                parametreler = {satir.varlik_turu: parametre_degeri}
            kayitlar.append({"soru": soru, "arac": satir.arac, "parametreler": parametreler})

    return pd.DataFrame(kayitlar).drop_duplicates(subset="soru").reset_index(drop=True)


def _cli() -> None:
    ayristirici = argparse.ArgumentParser(description="Eğitim veri seti üreteci (A3.1 + A3.2)")
    ayristirici.add_argument("--seed", type=int, default=42, help="Simülasyon seed'i")
    ayristirici.add_argument("--ornekleme-seed", type=int, default=7)
    ayristirici.add_argument(
        "--hedef-nokta-sayisi", type=int, default=VARSAYILAN_HEDEF_NOKTA_SAYISI
    )
    ayristirici.add_argument("--cikti", type=str, default="data/egitim/karar_noktalari.jsonl")
    ayristirici.add_argument(
        "--router-cikti", type=str, default="data/egitim/router_sorulari.jsonl"
    )
    ayristirici.add_argument("--router-seed", type=int, default=11)
    ayristirici.add_argument("--sadece-router", action="store_true")
    ayristirici.add_argument(
        "--sablon-ihrac-et",
        type=str,
        default=None,
        help="Verilirse yalnızca (Colab'a yüklenecek) benzersiz şablon listesini bu yola yazar",
    )
    ayristirici.add_argument(
        "--sablon-ihrac-araclar",
        nargs="+",
        default=None,
        help=(
            "--sablon-ihrac-et ile birlikte: yalnızca bu araçların şablonlarını çıkar "
            "(ör. seyrek araçları hedefli, yüksek-n paraphrase turuna sokmak için)"
        ),
    )
    args = ayristirici.parse_args()

    if args.sablon_ihrac_et:
        arac_filtresi = set(args.sablon_ihrac_araclar) if args.sablon_ihrac_araclar else None
        sablon_df = sablonlari_ihrac_et(yalnizca_araclar=arac_filtresi)
        jsonl_yaz(sablon_df, Path(args.sablon_ihrac_et))
        print(f"[A3.3] Toplam benzersiz şablon: {len(sablon_df)}")
        print(f"[A3.3] Yazıldı: {args.sablon_ihrac_et}")
        return

    profile = yapi_malzemesi_toptancisi()
    sonuc = simulasyon_calistir(profile=profile, seed=args.seed, yil_sayisi=3)

    if not args.sadece_router:
        df = karar_noktasi_veri_seti_uret(
            sonuc,
            hedef_nokta_sayisi=args.hedef_nokta_sayisi,
            seed=args.ornekleme_seed,
        )
        yol = Path(args.cikti)
        jsonl_yaz(df, yol)

        print(f"[A3.1] Toplam karar noktası: {len(df)}")
        print(f"[A3.1] Yazıldı: {yol}")
        print()
        print("[A3.1] Karar tipi dağılımı:")
        print(df["karar_tipi"].value_counts())
        print()
        print("[A3.1] Karar tipi oranı:")
        print((df["karar_tipi"].value_counts(normalize=True) * 100).round(2))
        print()

    router_df = router_veri_seti_uret(sonuc["sku"], sonuc["tedarikci"], seed=args.router_seed)
    router_yol = Path(args.router_cikti)
    jsonl_yaz(router_df, router_yol)

    print(f"[A3.2] Toplam router sorusu: {len(router_df)}")
    print(f"[A3.2] Yazıldı: {router_yol}")
    print()
    print("[A3.2] Araç başına soru sayısı:")
    print(router_df["arac"].value_counts())


if __name__ == "__main__":
    _cli()
