"""Gerçek ERP verisini (CSV) karar motorunun anladığı biçime çevirir.

Bugüne kadar sistem yalnızca `simulator/` ile beslendi. Bu modül, **gerçek
bir şirketin** verisiyle çalıştırmayı mümkün kılıyor — pilot müşteri, geriye
dönük test ya da `shadow` mod için.

    uv run python -m app.adapters.csv_erp --dizin veriler/ --tarih 2026-06-30

## Neden yalnızca üç dosya

Karar motoru 26 alan istiyor ama bunların çoğu **türetilebilir**. Bir
şirketten istenecek şey, her ERP'de (hatta Excel'de) hazır duran üç tablo:

    urunler.csv     ürün kartları    — kod, ad, kategori, maliyet, fiyat...
    hareketler.csv  stok hareketleri — tarih, ürün, giren/çıkan miktar
    siparisler.csv  satınalma        — sipariş tarihi, teslim tarihi, tedarikçi

Gerisini bu modül hesaplıyor: günlük ortalama talep ve sapması, ABC/XYZ
sınıfı, son hareket tarihi, tedarik süresi ortalaması/sapması, tedarikçi
güvenilirliği.

⚠️ **Hesabın kendisi burada YAPILMIYOR.** Bu modül yalnızca CSV'leri
`katalog_ozelliklerini_hesapla`'nın beklediği tablolara çeviriyor; talep
istatistikleri, ROP, ABC/XYZ hep mevcut kodda kalıyor. Aksi hâlde aynı
formüller iki yerde yaşar ve zamanla ayrışır — projenin bu hatayı bir kez
yaşadığı yer için bkz. `dokumantasyon/OLCUMLER.md` (guard'ın iki kopyası).

## Beklenen CSV biçimi

Kolon adları esnek: `KOLON_ESLESMELERI` yaygın Türkçe/İngilizce karşılıkları
tanıyor (`stok_kodu`, `urun_kodu`, `sku`, `item_code`...). Tanınmayan bir ad
gelirse hata mesajı hangi kolonun eksik olduğunu ve hangi adların kabul
edildiğini yazıyor — "KeyError: 'sku_id'" diye kapanmıyor.

### urunler.csv (zorunlu)

    sku_id, sku_adi, kategori, birim_maliyet_tl, satis_fiyati_tl, tedarikci_id

İsteğe bağlı: `tedarikci_adi`, `moq`, `paket_adedi`, `raf_omru_gun`.
Verilmezse makul varsayılanlar kullanılır (bkz. `VARSAYILANLAR`).

### hareketler.csv (zorunlu)

    tarih, sku_id, miktar

`miktar` **çıkış (satış) miktarıdır**, pozitif yazılır. Giriş hareketleri
(mal kabul) ayrı bir satırda `hareket_tipi=giris` ile verilebilir; verilirse
stok seviyesi hesabında kullanılır, verilmezse yalnızca talep hesaplanır ve
eldeki stok `urunler.csv`'deki `eldeki_stok` kolonundan alınır.

### siparisler.csv (isteğe bağlı ama ÖNEMLİ)

    tedarikci_id, siparis_tarihi, teslim_tarihi

Tedarik süresi ve gecikme riski buradan çıkıyor. Yoksa
`VARSAYILAN_TEDARIK_SURESI_GUN` kullanılır — ama o zaman emniyet stoğu
hesabı gerçek riski yansıtmaz, çünkü tedarik süresi **belirsizliği** sıfır
varsayılır. Bu, sistemin en değerli hesabını körleştirir; dosya mutlaka
istenmeli.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from app.contracts import StockFeatures
from app.domain.stock.features import katalog_ozelliklerini_hesapla

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# Aynı alanın sektörde/ERP'lerde karşılaştığı adlar. Küçük harfe indirilip
# eşleştiriliyor; boşluk ve tire alt çizgiye çevriliyor.
KOLON_ESLESMELERI: dict[str, tuple[str, ...]] = {
    "sku_id": ("sku_id", "sku", "stok_kodu", "urun_kodu", "malzeme_kodu", "item_code", "kod"),
    "sku_adi": ("sku_adi", "urun_adi", "stok_adi", "malzeme_adi", "item_name", "ad", "aciklama"),
    "kategori": ("kategori", "grup", "urun_grubu", "category", "stok_grubu"),
    "birim_maliyet_tl": ("birim_maliyet_tl", "birim_maliyet", "maliyet", "alis_fiyati", "cost"),
    "satis_fiyati_tl": ("satis_fiyati_tl", "satis_fiyati", "fiyat", "price", "liste_fiyati"),
    "tedarikci_id": ("tedarikci_id", "tedarikci_kodu", "cari_kod", "supplier_id", "supplier"),
    "tedarikci_adi": ("tedarikci_adi", "tedarikci", "cari_unvan", "supplier_name"),
    "eldeki_stok": ("eldeki_stok", "stok", "mevcut_stok", "bakiye", "miktar_stok", "on_hand"),
    # §7: yoldaki mal. ERP'lerde en sık bu adlarla geçiyor.
    "yoldaki_stok": (
        "yoldaki_stok",
        "yolda",
        "yoldaki",
        "siparis_edilen",
        "acik_siparis",
        "beklenen_giris",
        "on_order",
        "in_transit",
    ),
    "moq": ("moq", "min_siparis", "minimum_siparis_miktari", "min_order_qty"),
    "paket_adedi": ("paket_adedi", "koli_adedi", "paket", "pack_size"),
    "raf_omru_gun": ("raf_omru_gun", "raf_omru", "shelf_life_days"),
    "tarih": ("tarih", "islem_tarihi", "hareket_tarihi", "date", "fis_tarihi"),
    "miktar": ("miktar", "cikis_miktari", "satis_miktari", "adet", "quantity", "qty"),
    "hareket_tipi": ("hareket_tipi", "tip", "islem_tipi", "type", "yon"),
    "siparis_tarihi": ("siparis_tarihi", "order_date", "verilis_tarihi"),
    "teslim_tarihi": ("teslim_tarihi", "delivery_date", "mal_kabul_tarihi", "giris_tarihi"),
}

VARSAYILANLAR: dict[str, object] = {
    # Stok kolonu isteğe bağlı sayılıyor: bazı ERP'ler bakiyeyi ayrı bir
    # dosyada tutuyor. Yoksa 0 — sistem her ürünü stoksuz görür ve sipariş
    # önerir, ki yanlış yönde hata yapmaktan iyidir.
    "eldeki_stok": 0,
    # ⚠️ 0 varsaymak güvenli taraf ama bedava değil: yoldaki mal görünmezse
    # aynı sipariş iki kez verilebilir. Müşteride alan varsa doldurulmalı.
    "yoldaki_stok": 0,
    "moq": 1,
    "paket_adedi": 1,
    "raf_omru_gun": None,
    "kategori": "genel",
}

# Tedarik süresi verisi yoksa kullanılır. ⚠️ Sapma 0 varsayıldığı için emniyet
# stoğu gerçek riski yansıtmaz — `siparisler.csv` mutlaka istenmeli.
VARSAYILAN_TEDARIK_SURESI_GUN = 7.0
VARSAYILAN_TEDARIK_SURESI_STD = 0.0
VARSAYILAN_GUVENILIRLIK = 0.90

# Gerçek veride bir tedarikçinin tek siparişi olabilir; tek gözlemden sapma
# hesaplanamaz. Bu sayının altındaki tedarikçilerde katalog ortalaması
# kullanılır — sıfır sapma yazmak, riski yok saymak olurdu.
ASGARI_SIPARIS_SAYISI = 3


class CsvBicimHatasi(ValueError):
    """CSV beklenen kolonları taşımıyor. Mesaj hangi adların kabul edildiğini yazar."""


_TURKCE_KATLAMA = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iissgguuoocc")


def _normalle(ad: str) -> str:
    """Kolon adını karşılaştırılabilir hâle getirir.

    ⚠️ Türkçe harfler katlanıyor. Müşteri `"Alış Fiyatı"` yazar, bizim
    listemizde `alis_fiyati` var — katlama olmadan ikisi eşleşmez ve
    "kolon bulunamadı" hatası alınır. İlk testte tam bu oldu.
    """
    return ad.strip().translate(_TURKCE_KATLAMA).lower().replace(" ", "_").replace("-", "_")


def kolonlari_esle(df: pd.DataFrame, gerekli: tuple[str, ...], dosya: str) -> pd.DataFrame:
    """Tanınan kolon adlarını standart adlara çevirir.

    Eksik kolonda `KeyError` yerine ne yapılması gerektiğini söyleyen bir hata
    veriyor — bu dosyaları hazırlayan kişi çoğu zaman geliştirici değil,
    müşterinin muhasebecisi.
    """
    mevcut = {_normalle(k): k for k in df.columns}
    yeniden_adlandir: dict[str, str] = {}

    for standart in gerekli:
        for aday in KOLON_ESLESMELERI.get(standart, (standart,)):
            if aday in mevcut:
                yeniden_adlandir[mevcut[aday]] = standart
                break
        else:
            kabul = ", ".join(KOLON_ESLESMELERI.get(standart, (standart,)))
            raise CsvBicimHatasi(
                f"{dosya}: '{standart}' kolonu bulunamadı.\n"
                f"  Kabul edilen adlar: {kabul}\n"
                f"  Dosyadaki kolonlar: {', '.join(df.columns)}"
            )

    return df.rename(columns=yeniden_adlandir)


def urunleri_oku(yol: Path) -> pd.DataFrame:
    """`urunler.csv` → `sku_df`."""
    ham = pd.read_csv(yol)
    df = kolonlari_esle(
        ham,
        ("sku_id", "sku_adi", "birim_maliyet_tl", "satis_fiyati_tl", "tedarikci_id"),
        yol.name,
    )

    # İsteğe bağlı kolonlar: varsa eşle, yoksa varsayılanı koy.
    for ad, varsayilan in VARSAYILANLAR.items():
        mevcut = {_normalle(k): k for k in ham.columns}
        for aday in KOLON_ESLESMELERI.get(ad, (ad,)):
            if aday in mevcut:
                df[ad] = ham[mevcut[aday]]
                break
        else:
            df[ad] = varsayilan

    if "tedarikci_adi" not in df.columns:
        df["tedarikci_adi"] = df["tedarikci_id"]

    df["sku_id"] = df["sku_id"].astype(str)
    df["tedarikci_id"] = df["tedarikci_id"].astype(str)

    yinelenen = df["sku_id"].duplicated().sum()
    if yinelenen:
        raise CsvBicimHatasi(f"{yol.name}: {yinelenen} SKU kodu birden fazla satırda.")

    return df


def hareketleri_oku(yol: Path) -> pd.DataFrame:
    """`hareketler.csv` → günlük talep tablosu (`tarih`, `sku_id`, `talep_miktari`).

    ⚠️ Hareket olmayan günler **sıfırla dolduruluyor.** Aksi hâlde talep
    ortalaması yalnızca satış olan günler üzerinden hesaplanır ve gerçeğin
    kat kat üstüne çıkar — ayda bir satılan bir ürün "günde 1 adet" gibi
    görünür, sistem de sürekli sipariş verir.
    """
    ham = pd.read_csv(yol)
    df = kolonlari_esle(ham, ("tarih", "sku_id", "miktar"), yol.name)
    df["tarih"] = pd.to_datetime(df["tarih"])
    df["sku_id"] = df["sku_id"].astype(str)

    # Giriş/çıkış ayrımı varsa yalnızca çıkışlar talebi oluşturur.
    if "hareket_tipi" in df.columns or any(
        _normalle(k) in KOLON_ESLESMELERI["hareket_tipi"] for k in ham.columns
    ):
        df = kolonlari_esle(df, ("hareket_tipi",), yol.name)
        cikis = df["hareket_tipi"].astype(str).str.lower().str.startswith(("cik", "çık", "sat"))
        df = df[cikis]

    df["miktar"] = pd.to_numeric(df["miktar"], errors="coerce").fillna(0).abs()

    gunluk = df.groupby(["tarih", "sku_id"], as_index=False)["miktar"].sum()
    gunluk = gunluk.rename(columns={"miktar": "talep_miktari"})

    # Tam takvim × tüm SKU'lar — boş günler 0.
    takvim = pd.date_range(gunluk["tarih"].min(), gunluk["tarih"].max(), freq="D")
    tam = pd.MultiIndex.from_product(
        [takvim, gunluk["sku_id"].unique()], names=["tarih", "sku_id"]
    )
    return (
        gunluk.set_index(["tarih", "sku_id"])
        .reindex(tam, fill_value=0.0)
        .reset_index()
    )


def siparislerden_tedarikci_tablosu(
    yol: Path | None, sku_df: pd.DataFrame
) -> pd.DataFrame:
    """`siparisler.csv` → `tedarikci_df` (tedarik süresi ortalaması, sapması, güvenilirlik).

    Güvenilirlik = zamanında teslim oranı. "Zamanında"nın tanımı: teslim
    süresi, o tedarikçinin kendi ortalamasını aşmadıysa. Mutlak bir hedef gün
    sayısı kullanılmıyor çünkü sektöre göre değişiyor ve müşteride böyle bir
    alan çoğu zaman yok.
    """
    tedarikciler = sku_df[["tedarikci_id", "tedarikci_adi"]].drop_duplicates()

    if yol is None or not yol.exists():
        tedarikciler = tedarikciler.assign(
            ort_tedarik_suresi_gun=VARSAYILAN_TEDARIK_SURESI_GUN,
            tedarik_suresi_std_gun=VARSAYILAN_TEDARIK_SURESI_STD,
            guvenilirlik=VARSAYILAN_GUVENILIRLIK,
        )
        return tedarikciler.reset_index(drop=True)

    ham = pd.read_csv(yol)
    df = kolonlari_esle(ham, ("tedarikci_id", "siparis_tarihi", "teslim_tarihi"), yol.name)
    df["tedarikci_id"] = df["tedarikci_id"].astype(str)
    df["siparis_tarihi"] = pd.to_datetime(df["siparis_tarihi"])
    df["teslim_tarihi"] = pd.to_datetime(df["teslim_tarihi"])
    df = df.dropna(subset=["siparis_tarihi", "teslim_tarihi"])
    df["sure"] = (df["teslim_tarihi"] - df["siparis_tarihi"]).dt.days
    df = df[df["sure"] >= 0]

    ozet = df.groupby("tedarikci_id")["sure"].agg(["mean", "std", "count"])
    katalog_ort = float(df["sure"].mean()) if len(df) else VARSAYILAN_TEDARIK_SURESI_GUN
    katalog_std = float(df["sure"].std()) if len(df) > 1 else VARSAYILAN_TEDARIK_SURESI_STD

    # Az gözlemli tedarikçide kendi sapması güvenilmez (tek siparişte 0 çıkar).
    seyrek = ozet["count"] < ASGARI_SIPARIS_SAYISI
    ozet.loc[seyrek, "std"] = katalog_std
    ozet["std"] = ozet["std"].fillna(katalog_std)

    df = df.merge(ozet["mean"].rename("kendi_ort"), on="tedarikci_id", how="left")
    zamaninda = df.assign(zamaninda=df["sure"] <= df["kendi_ort"])
    oran = zamaninda.groupby("tedarikci_id")["zamaninda"].mean()

    tedarikciler = tedarikciler.merge(
        ozet[["mean", "std"]].rename(
            columns={"mean": "ort_tedarik_suresi_gun", "std": "tedarik_suresi_std_gun"}
        ),
        on="tedarikci_id",
        how="left",
    ).merge(oran.rename("guvenilirlik"), on="tedarikci_id", how="left")

    tedarikciler["ort_tedarik_suresi_gun"] = tedarikciler["ort_tedarik_suresi_gun"].fillna(
        katalog_ort
    )
    tedarikciler["tedarik_suresi_std_gun"] = tedarikciler["tedarik_suresi_std_gun"].fillna(
        katalog_std
    )
    tedarikciler["guvenilirlik"] = tedarikciler["guvenilirlik"].fillna(VARSAYILAN_GUVENILIRLIK)

    return tedarikciler.reset_index(drop=True)


def envanter_tablosu(
    sku_df: pd.DataFrame, talep: pd.DataFrame, olcum_tarihi: dt.date
) -> pd.DataFrame:
    """Ölçüm tarihindeki stok seviyesi tablosu.

    Gerçek ERP'lerde günlük stok fotoğrafı saklanmaz; elde **bugünkü** bakiye
    vardır. `urunler.csv`'deki `eldeki_stok` o bakiyedir ve ölçüm tarihine
    yazılır.

    `yoldaki_stok` (sipariş verilmiş, henüz gelmemiş mal) `urunler.csv`'de
    varsa **okunuyor**, yoksa 0 kabul ediliyor.

    ⚠️ Sıfır varsaymak **güvenli taraf**: sistem yoldaki malı görmezse
    fazladan sipariş önerir, tersi (olmayan malı var sanmak) stok tükenmesine
    yol açardı. Ama güvenli taraf bedava değil — yoldaki mal görünmediğinde
    aynı sipariş iki kez verilebilir. Müşteride alan varsa mutlaka
    doldurulmalı (`BILINEN-EKSIKLER.md` §7).
    """
    stok = (
        sku_df["eldeki_stok"]
        if "eldeki_stok" in sku_df.columns
        else pd.Series(0, index=sku_df.index)
    )
    return pd.DataFrame(
        {
            "tarih": pd.Timestamp(olcum_tarihi),
            "sku_id": sku_df["sku_id"].to_numpy(),
            "eldeki_stok": pd.to_numeric(stok, errors="coerce").fillna(0).to_numpy(),
            "yoldaki_stok": (
                pd.to_numeric(sku_df["yoldaki_stok"], errors="coerce").fillna(0).to_numpy()
                if "yoldaki_stok" in sku_df.columns
                else np.zeros(len(sku_df))
            ),
            # Sütun `VARSAYILANLAR` sayesinde normalde hep var; `else` dalı
            # adaptörü doğrudan çağıran testler için duruyor.
        }
    )


def ozellikleri_uret(dizin: Path, olcum_tarihi: dt.date | None = None) -> list[StockFeatures]:
    """Üç CSV → `StockFeatures` listesi. Karar motoruna doğrudan verilebilir."""
    urunler = urunleri_oku(dizin / "urunler.csv")
    talep = hareketleri_oku(dizin / "hareketler.csv")
    tedarikciler = siparislerden_tedarikci_tablosu(dizin / "siparisler.csv", urunler)

    if olcum_tarihi is None:
        olcum_tarihi = talep["tarih"].max().date()

    # Ürün kartında olup hiç hareketi olmayan SKU'lar talep tablosunda yok;
    # onları 0 talebe eşitlemek yerine dışarıda bırakıyoruz — çünkü hiç satış
    # görmemiş bir ürün için "günlük ortalama talep" anlamlı değil ve sistem
    # onu ölü stok sanır. Kullanıcıya kaç tanesinin elendiği söyleniyor.
    hareketli = set(talep["sku_id"].unique())
    kapsanan = urunler[urunler["sku_id"].isin(hareketli)].reset_index(drop=True)

    envanter = envanter_tablosu(kapsanan, talep, olcum_tarihi)
    talep = talep[talep["sku_id"].isin(set(kapsanan["sku_id"]))]

    return katalog_ozelliklerini_hesapla(
        olcum_tarihi=olcum_tarihi,
        talep=talep,
        envanter_gunluk=envanter,
        sku_df=kapsanan,
        tedarikci_df=tedarikciler,
    )


def _cli() -> None:
    ayristirici = argparse.ArgumentParser(
        description="Gerçek ERP CSV'lerini karar motoru biçimine çevirir"
    )
    ayristirici.add_argument("--dizin", type=Path, required=True, help="CSV'lerin bulunduğu klasör")
    ayristirici.add_argument(
        "--tarih",
        type=dt.date.fromisoformat,
        default=None,
        help="Ölçüm tarihi (YYYY-AA-GG). Verilmezse verideki son gün.",
    )
    args = ayristirici.parse_args()

    urunler = urunleri_oku(args.dizin / "urunler.csv")
    ozellikler = ozellikleri_uret(args.dizin, args.tarih)

    print("=" * 66)
    print("CSV → KARAR MOTORU")
    print("=" * 66)
    print(f"  ürün kartı            : {len(urunler)}")
    print(f"  hareketi olan SKU     : {len(ozellikler)}")
    elenen = len(urunler) - len(ozellikler)
    if elenen:
        print(f"  hiç hareketi yok      : {elenen}  (ölçüme alınmadı)")
    if ozellikler:
        print(f"  ölçüm tarihi          : {ozellikler[0].olcum_tarihi}")
        print(f"  veri geçmişi          : {ozellikler[0].veri_gun_sayisi} gün")
        print()
        print("  ÖRNEK:")
        o = ozellikler[0]
        print(f"    {o.sku_adi} ({o.sku_id})")
        print(f"      eldeki stok        : {o.eldeki_stok}")
        print(f"      günlük ort. talep  : {o.ort_gunluk_talep:.2f} (± {o.talep_std:.2f})")
        print(
            f"      tedarik süresi     : {o.tedarik_suresi_gun:.1f} gün "
            f"(± {o.tedarik_suresi_std:.1f})"
        )
        print(f"      ABC/XYZ            : {o.abc_sinifi.value} / {o.xyz_sinifi.value}")
        print(f"      son hareket        : {o.son_hareket_gun_once} gün önce")
    print()
    print("Sonraki adım: `ozellikten_karar_uret(o)` ile karara çevir")
    print("(bkz. app/domain/stock/decide.py) ya da geriye dönük teste ver.")


if __name__ == "__main__":
    _cli()


__all__ = [
    "CsvBicimHatasi",
    "envanter_tablosu",
    "hareketleri_oku",
    "kolonlari_esle",
    "ozellikleri_uret",
    "siparislerden_tedarikci_tablosu",
    "urunleri_oku",
]
