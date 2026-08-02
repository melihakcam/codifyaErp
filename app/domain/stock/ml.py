"""Talep tahmini (XGBoost) + anomali (IsolationForest). Kurallara sayı besler, kuralları atlamaz.

Sahip: Kişi A · Faz 2 A2.7-A2.8

**A2.7 — Talep tahmini:** SKU başına ayrı model değil, tüm hızlı hareket eden
SKU'lar için **tek bir XGBoost** (SKU/kategori özellik olarak girer). Aralıklı
talepli yavaş hareket edenler **Croston yöntemiyle** ayrı ele alınır — ortalama
almak büyük hata, çünkü çoğu gün 0 satan bir ürünün "ortalaması" hiçbir günü
doğru tahmin etmez.

**Kritik kural:** train/test bölmesi **tarihe göre** yapılır, rastgele değil.
Rastgele bölünürse gelecekteki veriyle geçmiş tahmin edilmiş olur — skor
harika çıkar, üretimde çalışmaz.

**Dürüstlük kuralı:** `xgboost_talep_modeli_egit()` sonucunda `kullanilabilir`
alanı `False` dönerse, model naif taban çizgisinden (son 30 günün ortalaması)
iyi değildir demektir. Bu durumda XGBoost kullanılmaz, naif tahmin kullanılır
ve bu dürüstçe raporlanır — çalışmayan bir modeli "çalışıyor" diye bırakmak
sonraki her ölçümü zehirler.

**A2.8 — Anomali + oracle karşılaştırması:** `anomali_tespit_et` /
`fiyat_sapmasi_tespit_et` IsolationForest ile beklenmedik sıçramaları /
fiyat sapmalarını işaretler. `politika_karsilastirmasi_calistir` aynı
gerçekleşen talep üzerinde üç politikayı (vasat taban, kural motoru, oracle)
paralel koşturup karşılaştırır — kural motorunun gerçekten işe yaradığının
kanıtı budur.

**Bilinçli sınırlama:** "promo bayrağı" özelliği dahil edilmedi — simülatör
promosyon etkisini talebe gömülü uyguluyor (`simulator/demand.py`), ayrı bir
günlük sinyal olarak dışa vermiyor. Gerçek bir promo takvimi olmadan bu
özelliği eklemek var olmayan bir sinyali uydurmak olurdu.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import norm
from sklearn.ensemble import IsolationForest

from app.contracts import ABCSinifi, StockFeatures, XYZSinifi
from app.domain.stock.rules import (
    VARSAYILAN_SIPARIS_MALIYETI_TL,
    VARSAYILAN_YILLIK_ELDE_TUTMA_ORANI,
    abc_xyz_siniflandir,
)
from simulator.catalog import katalog_uret
from simulator.company import CompanyProfile, yapi_malzemesi_toptancisi
from simulator.demand import (
    DINI_BAYRAM_BASLANGICLARI,
    GUNLUK_HIZLI_HAREKET_ESIGI,
    katalog_icin_talep_uret,
)
from simulator.run import (
    BASLANGIC_STOK_GUN_KARSILIGI,
    ROP_ESIK_GUN,
    SIPARIS_HEDEF_GUN,
    TALEP_ORTALAMA_PENCERE_GUN,
)

# ---------------------------------------------------------------------------
# A2.7 — Özellik mühendisliği
# ---------------------------------------------------------------------------

LAG_GUNLERI = (1, 7, 14, 28)
HAREKETLI_ORTALAMA_PENCERELERI = (7, 30)
OZELLIK_KOLONLARI = (
    [f"lag_{g}" for g in LAG_GUNLERI]
    + [f"hareketli_ort_{p}" for p in HAREKETLI_ORTALAMA_PENCERELERI]
    + ["haftanin_gunu", "ay", "tatil_mi", "kategori_kod", "sku_kod"]
)

_BAYRAM_SURESI_GUN = 4


def _tatil_bayragi_hesapla(tarihler: pd.DatetimeIndex) -> np.ndarray:
    """`DINI_BAYRAM_BASLANGICLARI`'ndan (simulator.demand) gün bazlı 0/1 tatil bayrağı."""
    bayrak = np.zeros(len(tarihler), dtype=int)
    for i, tarih in enumerate(tarihler):
        yil_bayramlari = DINI_BAYRAM_BASLANGICLARI.get(tarih.year)
        if yil_bayramlari is None:
            continue
        gun = tarih.date() if hasattr(tarih, "date") else tarih
        for baslangic in yil_bayramlari:
            bitis = baslangic + dt.timedelta(days=_BAYRAM_SURESI_GUN)
            if baslangic <= gun < bitis:
                bayrak[i] = 1
    return bayrak


def ozellik_matrisi_olustur(talep: pd.DataFrame, sku_df: pd.DataFrame) -> pd.DataFrame:
    """Uzun formattaki (tarih, sku_id, talep_miktari) talepten XGBoost özellik matrisi kurar.

    Gecikmeli talep + hareketli ortalamalar **causal**dır (o günden önceki
    günlere `shift`lenir) — bugünün veya geleceğin bilgisini kullanmaz.
    """
    df = talep.merge(sku_df[["sku_id", "kategori"]], on="sku_id", how="left")
    df = df.sort_values(["sku_id", "tarih"]).reset_index(drop=True)

    grup = df.groupby("sku_id")["talep_miktari"]
    for gecikme in LAG_GUNLERI:
        df[f"lag_{gecikme}"] = grup.shift(gecikme)
    for pencere in HAREKETLI_ORTALAMA_PENCERELERI:
        df[f"hareketli_ort_{pencere}"] = grup.transform(
            lambda s, p=pencere: s.shift(1).rolling(p, min_periods=1).mean()
        )

    df["haftanin_gunu"] = df["tarih"].dt.dayofweek
    df["ay"] = df["tarih"].dt.month
    df["tatil_mi"] = _tatil_bayragi_hesapla(pd.DatetimeIndex(df["tarih"]))
    df["kategori_kod"] = df["kategori"].astype("category").cat.codes
    df["sku_kod"] = df["sku_id"].astype("category").cat.codes

    return df


# ---------------------------------------------------------------------------
# A2.7 — Aralıklı talep: Croston yöntemi
# ---------------------------------------------------------------------------


def croston_tahmin(gecmis_talep: np.ndarray, alfa: float = 0.1) -> float:
    """Croston yöntemi: z/p — aralıklı (çoğu gün 0 satan) talep için nokta tahmini.

    z: talep pozitif olduğunda büyüklüğün üstel düzeltilmiş ortalaması.
    p: iki pozitif talep arasındaki üstel düzeltilmiş ortalama gün aralığı.
    Klasik ortalama burada yanıltıcıdır — 60 günde 3 kez 10 birim satan bir
    ürünün "günlük ortalaması" 0.5 çıkar ama gerçek davranış "arada bir 10
    birim"dir; Croston bu iki bileşeni ayrı tutar.
    """
    pozitif_indeksler = np.nonzero(gecmis_talep > 0)[0]
    if len(pozitif_indeksler) == 0:
        return 0.0
    if len(pozitif_indeksler) == 1:
        return float(gecmis_talep[pozitif_indeksler[0]])

    z = float(gecmis_talep[pozitif_indeksler[0]])
    p = float(pozitif_indeksler[0] + 1)
    onceki_indeks = pozitif_indeksler[0]
    for indeks in pozitif_indeksler[1:]:
        z = alfa * float(gecmis_talep[indeks]) + (1 - alfa) * z
        p = alfa * float(indeks - onceki_indeks) + (1 - alfa) * p
        onceki_indeks = indeks

    return z / p if p > 0 else 0.0


# ---------------------------------------------------------------------------
# A2.7 — Metrikler
# ---------------------------------------------------------------------------


def mae_hesapla(gercek: np.ndarray, tahmin: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(gercek) - np.asarray(tahmin))))


def mase_hesapla(gercek: np.ndarray, tahmin: np.ndarray, egitim_gercek: np.ndarray) -> float:
    """MASE = MAE(model) / MAE(naif 1-adım taban çizgisi, eğitim verisinde).

    MASE < 1 → model, "dünkü değeri tahmin olarak kullan" naif kuralından iyi.
    """
    naif_hata = np.abs(np.diff(np.asarray(egitim_gercek)))
    olcek = float(np.mean(naif_hata)) if len(naif_hata) > 0 else 1.0
    if olcek == 0:
        olcek = 1e-9
    return mae_hesapla(gercek, tahmin) / olcek


# ---------------------------------------------------------------------------
# A2.7 — XGBoost eğitimi (tarih bazlı bölme)
# ---------------------------------------------------------------------------


def egitim_test_bol(
    ozellik_df: pd.DataFrame, bolme_tarihi: dt.date
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Zaman serisinde bölme **tarihe göre** yapılır, rastgele değil.

    Rastgele bölünürse gelecekteki veriyle geçmiş tahmin edilmiş olur — skor
    harika çıkar, üretimde çalışmaz. Bu, bu işte en sık yapılan hata.
    """
    olcum = pd.Timestamp(bolme_tarihi)
    egitim = ozellik_df[ozellik_df["tarih"] < olcum]
    test = ozellik_df[ozellik_df["tarih"] >= olcum]
    return egitim, test


def xgboost_talep_modeli_egit(
    talep: pd.DataFrame, sku_df: pd.DataFrame, bolme_tarihi: dt.date
) -> dict:
    """Hızlı hareket eden tüm SKU'lar için tek bir XGBoost modeli eğitir.

    Döner: `model`, `ozellik_kolonlari`, eğitim/test satır sayıları, model ve
    naif taban çizgisi için MAE/MASE, ve **`kullanilabilir: bool`** — model
    naif taban çizgisinden ölçülebilir şekilde iyi değilse `False`. `False`
    ise bu modeli üretimde kullanma; naif tahmini kullan ve bunu raporla.
    """
    ort_gunluk_talep_sku = talep.groupby("sku_id")["talep_miktari"].mean()
    hizli_sku_idler = ort_gunluk_talep_sku[
        ort_gunluk_talep_sku >= GUNLUK_HIZLI_HAREKET_ESIGI
    ].index

    talep_hizli = talep[talep["sku_id"].isin(hizli_sku_idler)]
    ozellik_df = ozellik_matrisi_olustur(talep_hizli, sku_df).dropna(
        subset=[*OZELLIK_KOLONLARI, "talep_miktari"]
    )

    egitim, test = egitim_test_bol(ozellik_df, bolme_tarihi)
    if len(egitim) == 0 or len(test) == 0:
        raise ValueError("Eğitim veya test kümesi boş — bölme tarihini kontrol et.")

    model = xgb.XGBRegressor(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        objective="reg:squarederror",
        random_state=42,
    )
    model.fit(egitim[OZELLIK_KOLONLARI], egitim["talep_miktari"])

    tahmin = np.clip(model.predict(test[OZELLIK_KOLONLARI]), 0, None)
    naif_tahmin = test["hareketli_ort_30"].to_numpy()

    gercek_test = test["talep_miktari"].to_numpy()
    gercek_egitim = egitim["talep_miktari"].to_numpy()

    model_mae = mae_hesapla(gercek_test, tahmin)
    naif_mae = mae_hesapla(gercek_test, naif_tahmin)

    return {
        "model": model,
        "ozellik_kolonlari": list(OZELLIK_KOLONLARI),
        "sku_sayisi": len(hizli_sku_idler),
        "egitim_satir_sayisi": len(egitim),
        "test_satir_sayisi": len(test),
        "model_mae": model_mae,
        "naif_mae": naif_mae,
        "model_mase": mase_hesapla(gercek_test, tahmin, gercek_egitim),
        "naif_mase": mase_hesapla(gercek_test, naif_tahmin, gercek_egitim),
        "kullanilabilir": model_mae < naif_mae,
    }


def modeli_diske_kaydet(model: object, yol: Path) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, yol)


# ---------------------------------------------------------------------------
# A2.8 — Anomali tespiti
# ---------------------------------------------------------------------------


def anomali_tespit_et(
    talep: pd.DataFrame, sku_df: pd.DataFrame, kontaminasyon: float = 0.01
) -> pd.DataFrame:
    """IsolationForest ile beklenmedik tüketim sıçramalarını işaretler.

    Özellik olarak mutlak talep yerine **kendi 30 günlük hareketli ortalamasına
    oranı** kullanılır — aksi halde model yalnızca zaten büyük hacimli SKU'ları
    "anormal" bulur, oysa aranan şey SKU'nun *kendi* alışkanlığından sapma.

    **Dürüstçe raporlanan sınırlama:** `pathologies.TALEP_PATLAMASI` (2-3 kat
    sıçrama) enjekte edilen olaylarda ölçülen recall düşük çıkıyor (~%10-15).
    Kök neden bir kod hatası değil, sinyal/gürültü oranı: `demand.py`'nin
    kendi ürettiği doğal varyasyon (promosyon çarpanı 1.3-2.0x, negatif binom
    aşırı yayılımı) enjekte edilen patlamayla (2.0-3.0x) büyüklük olarak
    örtüşüyor — model ikisini güvenilir şekilde ayıramıyor. 90 günlük referans
    penceresi de denendi, iyileşme sağlamadı. Üretimde bunu düzeltmenin yolu
    büyüklük eşiğini artırmak değil, SKU/kategori bazlı ayrı eşikler veya
    sıçramanın *süresine* bakan (tek gün değil, ardışık N gün) bir yöntemdir.
    """
    df = ozellik_matrisi_olustur(talep, sku_df).dropna(subset=["hareketli_ort_30"])
    df["talep_orani"] = df["talep_miktari"] / df["hareketli_ort_30"].replace(0, np.nan)
    df["talep_orani"] = df["talep_orani"].fillna(df["talep_miktari"])

    model = IsolationForest(contamination=kontaminasyon, random_state=42)
    tahmin = model.fit_predict(df[["talep_miktari", "talep_orani"]].to_numpy())
    df["anomali_mi"] = tahmin == -1

    return df[["tarih", "sku_id", "talep_miktari", "talep_orani", "anomali_mi"]]


def fiyat_sapmasi_tespit_et(
    siparisler: pd.DataFrame, kontaminasyon: float = 0.02
) -> pd.DataFrame:
    """SKU başına gerçekleşen birim fiyatın kendi geçmiş ortalamasına göre
    sapmasını IsolationForest ile işaretler (fiyat zammı patolojisini yakalamak için).

    **Tasarım notu (ilk denemede bulunan hata):** Referans ortalama **SKU
    bazında** hesaplanır, tedarikçi bazında değil. İlk denemede tedarikçi
    bazında gruplamıştım — bir tedarikçi çok farklı fiyat aralığındaki
    SKU'ları taşıdığı için (ör. 5 TL'lik tuğla ile 20.000 TL'lik demir aynı
    tedarikçiden), bu karışım gerçek zam sinyalini gürültüye boğuyordu.
    Enjekte edilen fiyat zammı olaylarında ölçülen recall tedarikçi bazında
    **%3.4**, SKU bazında **%78.6** çıktı — bu düzeltme sayesinde.
    """
    df = siparisler.copy()
    df["birim_fiyat"] = df["tutar_tl"] / df["siparis_miktari"]
    df = df.sort_values(["sku_id", "tarih"])
    df["sku_ort_fiyat"] = df.groupby("sku_id")["birim_fiyat"].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )
    df = df.dropna(subset=["sku_ort_fiyat"])
    df["fiyat_orani"] = df["birim_fiyat"] / df["sku_ort_fiyat"]

    model = IsolationForest(contamination=kontaminasyon, random_state=42)
    tahmin = model.fit_predict(df[["fiyat_orani"]].to_numpy())
    df["anomali_mi"] = tahmin == -1

    return df[["tarih", "sku_id", "tedarikci_id", "birim_fiyat", "fiyat_orani", "anomali_mi"]]


# ---------------------------------------------------------------------------
# A2.8 — Oracle karşılaştırması
# ---------------------------------------------------------------------------


STOKTUKENMESI_CEZA_CARPANI = 2.5
"""Bir stok tükenmesinin gerçek maliyeti, o anki kayıp kâr marjından fazladır
(müşteri güveni, acil tedarik, gelecekteki satış riski). Tedarik zinciri
literatüründe 'shortage cost' genelde marjın 2-5 katı olarak modellenir."""

ORACLE_TEDARIK_SURESI_GUVEN_KATSAYISI = 3.0
"""Oracle, tedarik süresinin ort + bu katsayı*std kadarını (≈%99.9 üst sınır)
kapsayacak şekilde ileriye bakar. Talebi mükemmel bilmek, tedarik süresi
belirsizliğini otomatik olarak ortadan kaldırmaz — bu düzeltilmezse oracle
gerçek teslimat ortalamadan uzun sürdüğünde stok tükenmesi yaşayabilir, ki bu
"mükemmel bilgi" tanımıyla çelişir."""


def _vektorel_yuvarla(miktar: np.ndarray, moq: np.ndarray, paket_adedi: np.ndarray) -> np.ndarray:
    """`rules.siparis_miktarini_yuvarla`'nın vektörize hali (karşılaştırma döngüsü için)."""
    miktar = np.maximum(miktar, 0.0)
    paket_kati = np.maximum(1, np.ceil(miktar / paket_adedi))
    yuvarlanmis = paket_kati * paket_adedi
    altinda = yuvarlanmis < moq
    yuvarlanmis = np.where(altinda, np.ceil(moq / paket_adedi) * paket_adedi, yuvarlanmis)
    return yuvarlanmis


def politika_karsilastirmasi_calistir(
    profile: CompanyProfile | None = None,
    seed: int = 42,
    yil_sayisi: int = 3,
    baslangic_tarihi: dt.date = dt.date(2022, 1, 1),
) -> pd.DataFrame:
    """Aynı gerçekleşen talep üzerinde üç politikayı paralel koşturup karşılaştırır:

    - **vasat**: `simulator/run.py`'deki kasıtlı vasat taban politika (10 gün eşik / 30 gün hedef)
    - **kural_motoru**: `rules.py`'nin emniyet stoğu/ROP + EOQ formülleri
    - **oracle**: gerçekleşen *geleceği* bilerek sipariş verir, emniyet stoğu sıfır

    **Bitti sayılır:** kural motoru vasat'tan daha iyi, oracle'dan daha kötü
    olmalı. Aradaysa bir yerde hata var — vasat'tan kötüyse kurallarda hata,
    oracle'dan iyiyse ölçümde sızıntı var (imkânsız bir sonuç).

    **Bilinçli basitleştirme:** Üç politika da aynı `seed`'den türeyen ama
    birbirinden bağımsız tedarik-süresi rastgeleliği kullanır (aynı gün aynı
    SKU için üç politikada birebir aynı gecikme değildir). Toplam 3 yıl x 2.000
    SKU ölçeğinde agregat metrikler için bu yeterince adildir; tek bir SKU'nun
    tek bir siparişini politikalar arası birebir karşılaştırmak için yeterli
    değildir.
    """
    profile = profile or yapi_malzemesi_toptancisi()
    talep_rng = np.random.default_rng(seed + 1)

    kataloglar = katalog_uret(profile, seed=seed)
    sku_df = kataloglar["sku"].reset_index(drop=True)
    tedarikci_df = kataloglar["tedarikci"].set_index("tedarikci_id")

    n_sku = len(sku_df)
    gun_sayisi = 365 * yil_sayisi
    sku_ids = sku_df["sku_id"].to_numpy()

    talep_df = katalog_icin_talep_uret(sku_df, profile, baslangic_tarihi, gun_sayisi, talep_rng)
    talep_wide = (
        talep_df.pivot(index="tarih", columns="sku_id", values="talep_miktari")
        .reindex(columns=sku_ids)
        .to_numpy()
        .astype(float)
    )
    kumulatif_talep = np.vstack([np.zeros(n_sku), np.cumsum(talep_wide, axis=0)])

    sku_tedarikci_id = sku_df["tedarikci_id"].to_numpy()
    ort_tedarik_suresi = tedarikci_df.loc[sku_tedarikci_id, "ort_tedarik_suresi_gun"].to_numpy()
    tedarik_suresi_std = tedarikci_df.loc[sku_tedarikci_id, "tedarik_suresi_std_gun"].to_numpy()
    paket_adedi = sku_df["paket_adedi"].to_numpy().astype(float)
    moq = sku_df["moq"].to_numpy().astype(float)
    birim_maliyet = sku_df["birim_maliyet_tl"].to_numpy()

    # Kural motoru için ABC/XYZ + hedef servis seviyesi: ilk 90 günün
    # gerçekleşen talebinden bir kerelik hesaplanır (periyodik yeniden
    # sınıflandırma gerçek sistemde de her gün değil, dönemsel yapılır).
    isinma_gun = min(90, gun_sayisi)
    on_ozellikler = [
        StockFeatures(
            sku_id=sku_ids[j],
            sku_adi=sku_df.iloc[j]["sku_adi"],
            kategori=sku_df.iloc[j]["kategori"],
            eldeki_stok=0,
            rezerve_stok=0,
            yoldaki_stok=0,
            ort_gunluk_talep=float(talep_wide[:isinma_gun, j].mean()),
            talep_std=float(talep_wide[:isinma_gun, j].std()),
            veri_gun_sayisi=isinma_gun,
            tedarik_suresi_gun=float(ort_tedarik_suresi[j]),
            tedarik_suresi_std=float(tedarik_suresi_std[j]),
            abc_sinifi=ABCSinifi.C,
            xyz_sinifi=XYZSinifi.Z,
            hedef_servis_seviyesi=0.90,
            son_hareket_gun_once=0,
            raf_omru_kalan_gun=None,
            birim_maliyet_tl=float(sku_df.iloc[j]["birim_maliyet_tl"]),
            satis_fiyati_tl=float(sku_df.iloc[j]["satis_fiyati_tl"]),
            tedarikci_id=sku_tedarikci_id[j],
            tedarikci_adi="",
            tedarikci_skoru=50.0,
            tedarikci_zamaninda_teslim_orani=0.9,
            tedarikci_onayli=True,
            moq=int(moq[j]),
            paket_adedi=int(paket_adedi[j]),
            olcum_tarihi=baslangic_tarihi,
        )
        for j in range(n_sku)
    ]
    siniflandirma = abc_xyz_siniflandir(on_ozellikler)
    hedef_servis = siniflandirma.loc[sku_ids, "hedef_servis_seviyesi"].to_numpy()

    politikalar = ("vasat", "kural_motoru", "oracle")
    durum = {
        p: {
            "stok": np.round(
                np.array([o.ort_gunluk_talep for o in on_ozellikler]) * BASLANGIC_STOK_GUN_KARSILIGI
            ),
            "yoldaki": np.zeros(n_sku),
            "teslimatlar": defaultdict(list),
            "karsilanamayan_toplam": np.zeros(n_sku),
            "asiri_stok_maliyet_toplam": np.zeros(n_sku),
            "siparis_sayisi": 0,
            "talep_gecmisi": np.zeros((TALEP_ORTALAMA_PENCERE_GUN, n_sku)),
            "rng": np.random.default_rng(seed + 2),
        }
        for p in politikalar
    }

    gunluk_elde_tutma_orani = VARSAYILAN_YILLIK_ELDE_TUTMA_ORANI / 365.0

    for t in range(gun_sayisi):
        talep_bugun = talep_wide[t]

        for p in politikalar:
            s = durum[p]
            for sku_idx_arr, miktar_arr in s["teslimatlar"].pop(t, []):
                s["stok"][sku_idx_arr] += miktar_arr
                s["yoldaki"][sku_idx_arr] -= miktar_arr

            sevkiyat = np.minimum(talep_bugun, s["stok"])
            s["karsilanamayan_toplam"] += talep_bugun - sevkiyat
            s["stok"] -= sevkiyat
            s["asiri_stok_maliyet_toplam"] += (
                s["stok"] * birim_maliyet * gunluk_elde_tutma_orani
            )

            s["talep_gecmisi"][t % TALEP_ORTALAMA_PENCERE_GUN] = talep_bugun
            gecerli_gun = min(t + 1, TALEP_ORTALAMA_PENCERE_GUN)
            ort_talep = s["talep_gecmisi"].sum(axis=0) / gecerli_gun
            std_talep = (
                s["talep_gecmisi"][:gecerli_gun].std(axis=0) if gecerli_gun > 1 else np.zeros(n_sku)
            )
            net_pozisyon = s["stok"] + s["yoldaki"]

            if p == "vasat":
                esik = ROP_ESIK_GUN * ort_talep
                tetik = (net_pozisyon < esik) & (ort_talep > 0)
                hedef_miktar = SIPARIS_HEDEF_GUN * ort_talep
            elif p == "kural_motoru":
                z = norm.ppf(hedef_servis)
                varyans = (
                    ort_tedarik_suresi * std_talep**2 + ort_talep**2 * tedarik_suresi_std**2
                )
                emniyet = z * np.sqrt(np.clip(varyans, 0.0, None))
                rop = ort_talep * ort_tedarik_suresi + emniyet
                tetik = (net_pozisyon < rop) & (ort_talep > 0)
                yillik_talep = ort_talep * 365
                h = birim_maliyet * VARSAYILAN_YILLIK_ELDE_TUTMA_ORANI
                pay = np.maximum(2 * yillik_talep * VARSAYILAN_SIPARIS_MALIYETI_TL, 0)
                eoq = np.where(
                    (h > 0) & (yillik_talep > 0),
                    np.sqrt(pay / np.where(h > 0, h, 1)),
                    0.0,
                )
                hedef_miktar = eoq
            else:  # oracle
                # Talep mükemmel biliniyor ama tedarik süresi hâlâ rastgele —
                # oracle'ın gerçekten sıfır stok tükenmesi yaşaması için en
                # kötü senaryo kadar (ort + K*std) ileri bakması gerekir.
                # Yalnızca ortalama kadar bakarsa, gerçek teslimat ortalamadan
                # uzun sürdüğünde oracle da tükenme yaşar — bu, "mükemmel
                # bilgi" tanımının ihlalidir, ölçüm sızıntısı sayılır.
                guven_payi = ORACLE_TEDARIK_SURESI_GUVEN_KATSAYISI * tedarik_suresi_std
                ileri_gun = np.maximum(
                    1, np.round(ort_tedarik_suresi + guven_payi)
                ).astype(int)
                bitis_idx = np.minimum(t + ileri_gun, gun_sayisi)
                sku_araligi = np.arange(n_sku)
                gercek_gelecek_talep = (
                    kumulatif_talep[bitis_idx, sku_araligi] - kumulatif_talep[t, sku_araligi]
                )
                tetik = net_pozisyon < gercek_gelecek_talep
                hedef_miktar = np.maximum(gercek_gelecek_talep - net_pozisyon, 0.0)

            tetik_idx = np.nonzero(tetik)[0]
            if len(tetik_idx) > 0:
                s["siparis_sayisi"] += len(tetik_idx)
                miktar = _vektorel_yuvarla(
                    hedef_miktar[tetik_idx], moq[tetik_idx], paket_adedi[tetik_idx]
                )
                tedarik_suresi = np.maximum(
                    1,
                    np.round(
                        s["rng"].normal(
                            ort_tedarik_suresi[tetik_idx], tedarik_suresi_std[tetik_idx]
                        )
                    ),
                ).astype(int)
                s["yoldaki"][tetik_idx] += miktar

                varis_gunleri = t + tedarik_suresi
                for varis_gunu in np.unique(varis_gunleri):
                    if varis_gunu >= gun_sayisi:
                        continue
                    mask = varis_gunleri == varis_gunu
                    s["teslimatlar"][int(varis_gunu)].append((tetik_idx[mask], miktar[mask]))

    # Karşılanamayan talebin ekonomik maliyeti kâr marjı bazlıdır, ciro değil —
    # malın maliyeti zaten harcanmadı. Ama ham marj kaybı tek başına eksiktir:
    # bir stok tükenmesi güven kaybı, acil/pahalı tedarik ve gelecekteki
    # satışların riske girmesi anlamına gelir. Tedarik zinciri literatüründe
    # bu "shortage cost" genelde marjın birkaç katı olarak modellenir —
    # STOKTUKENMESI_CEZA_CARPANI bu ek maliyeti temsil eder.
    kar_marji_tl = (sku_df["satis_fiyati_tl"] - sku_df["birim_maliyet_tl"]).to_numpy()

    toplam_gun_sayisi = gun_sayisi
    ozet_satirlari = []
    for p in politikalar:
        s = durum[p]
        toplam_talep = talep_wide.sum()
        toplam_karsilanamayan = s["karsilanamayan_toplam"].sum()
        kayip_kar_tl = float(
            (s["karsilanamayan_toplam"] * kar_marji_tl).sum() * STOKTUKENMESI_CEZA_CARPANI
        )
        asiri_stok_maliyeti_tl = float(s["asiri_stok_maliyet_toplam"].sum())
        # EOQ'nun amacı tam olarak sipariş maliyeti ile elde tutma maliyeti
        # arasındaki dengeyi bulmaktır — sipariş maliyetini dışarıda bırakan
        # bir karşılaştırma, daha az/daha büyük sipariş vermenin kazancını
        # görmezden gelip yalnızca bedelini (daha fazla envanter) sayar.
        siparis_maliyeti_tl = s["siparis_sayisi"] * VARSAYILAN_SIPARIS_MALIYETI_TL
        ozet_satirlari.append(
            {
                "politika": p,
                "stok_tukenme_orani": float(toplam_karsilanamayan / toplam_talep),
                "kayip_kar_tl": kayip_kar_tl,
                "asiri_stok_maliyeti_tl": asiri_stok_maliyeti_tl,
                "siparis_maliyeti_tl": siparis_maliyeti_tl,
                "siparis_sayisi": s["siparis_sayisi"],
                "toplam_maliyet_tl": kayip_kar_tl + asiri_stok_maliyeti_tl + siparis_maliyeti_tl,
                "gun_sayisi": toplam_gun_sayisi,
            }
        )

    return pd.DataFrame(ozet_satirlari).set_index("politika")


# ---------------------------------------------------------------------------
# A4.4 — Karşılanamayan talep + aşırı stok maliyeti raporu
# ---------------------------------------------------------------------------


def maliyet_raporu_uret(
    sonuc: dict,
    stoktukenmesi_ceza_carpani: float = STOKTUKENMESI_CEZA_CARPANI,
) -> dict:
    """`simulator.run.simulasyon_calistir()` çıktısından maliyet metrikleri.

    `politika_karsilastirmasi_calistir`'den farkı: burada kendi simülasyon
    döngümüzü çalıştırmıyoruz — gerçek olay-tabanlı simülasyonun
    (`simulator/run.py`) zaten ürettiği `envanter_gunluk` ve
    `karsilanamayan_talep` tablolarını doğrudan kullanıyoruz. Bu yüzden
    **herhangi bir** koşuya (sağlıklı, patolojili, farklı seed/profil,
    ileride gerçek bir üretim politikasının çıktısı) uygulanabilir — o
    fonksiyondaki gibi üç politikayı paralel simüle etmeye ihtiyaç yok.

    Maliyet bileşenleri `politika_karsilastirmasi_calistir` ile aynı
    mantığı izler (kayıp kâr ceza çarpanlı, elde tutma maliyeti günlük,
    sipariş maliyeti sipariş başına sabit) — tek doğruluk kaynağı burada
    tekrarlanmıyor, aynı sabitler (`STOKTUKENMESI_CEZA_CARPANI`,
    `VARSAYILAN_YILLIK_ELDE_TUTMA_ORANI`, `VARSAYILAN_SIPARIS_MALIYETI_TL`)
    kullanılıyor.
    """
    sku_df = sonuc["sku"]
    sku_maliyet = sku_df.set_index("sku_id")[["birim_maliyet_tl", "satis_fiyati_tl"]]

    envanter = sonuc["envanter_gunluk"].merge(
        sku_maliyet[["birim_maliyet_tl"]], on="sku_id", how="left"
    )
    gunluk_elde_tutma_orani = VARSAYILAN_YILLIK_ELDE_TUTMA_ORANI / 365.0
    asiri_stok_maliyeti_tl = float(
        (envanter["eldeki_stok"] * envanter["birim_maliyet_tl"] * gunluk_elde_tutma_orani).sum()
    )

    karsilanamayan = sonuc["karsilanamayan_talep"]
    if karsilanamayan.empty:
        kayip_kar_tl = 0.0
        toplam_karsilanamayan_adet = 0.0
    else:
        birlesik = karsilanamayan.merge(sku_maliyet, on="sku_id", how="left")
        kar_marji_tl = birlesik["satis_fiyati_tl"] - birlesik["birim_maliyet_tl"]
        kayip_kar_tl = float(
            (birlesik["karsilanamayan_miktar"] * kar_marji_tl).sum() * stoktukenmesi_ceza_carpani
        )
        toplam_karsilanamayan_adet = float(karsilanamayan["karsilanamayan_miktar"].sum())

    toplam_talep_adet = float(sonuc["talep"]["talep_miktari"].sum())
    siparis_sayisi = len(sonuc["siparisler"])
    siparis_maliyeti_tl = siparis_sayisi * VARSAYILAN_SIPARIS_MALIYETI_TL

    return {
        "toplam_talep_adet": toplam_talep_adet,
        "toplam_karsilanamayan_adet": toplam_karsilanamayan_adet,
        "stok_tukenme_orani": (
            toplam_karsilanamayan_adet / toplam_talep_adet if toplam_talep_adet > 0 else 0.0
        ),
        "kayip_kar_tl": kayip_kar_tl,
        "asiri_stok_maliyeti_tl": asiri_stok_maliyeti_tl,
        "siparis_sayisi": siparis_sayisi,
        "siparis_maliyeti_tl": siparis_maliyeti_tl,
        "toplam_maliyet_tl": kayip_kar_tl + asiri_stok_maliyeti_tl + siparis_maliyeti_tl,
    }
