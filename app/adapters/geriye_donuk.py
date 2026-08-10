"""Geriye dönük test — sistemi geçmiş tarihlerde koşturup sonucu ölçmek.

Sahip: Kişi A · A4

`BILINEN-EKSIKLER.md` §4'ün cevabı: bugüne kadar her ölçüm simülasyonda
yapıldı. Bu modül gerçek ERP verisiyle aynı soruyu soruyor — ama **farklı
bir soru sorabildiği** için, ne sorduğu ve ne soramadığı çok net olmalı.

## ⚠️ Bu bir "ne olurdu" testi DEĞİL

Simülasyonda politikaları yan yana koşturabiliyoruz: sipariş verilir, mal
gelir, talep karşılanır. Geçmiş veride bu **imkânsız** — sistemin önerdiği
sipariş o gün verilmedi, dolayısıyla sonucu da gözlenemez.

Bu yüzden ölçülen şey şu: **sistem riski önceden gördü mü?**

    stok tükenmesi yaşandı  +  sistem öncesinde sipariş dedi  → yakaladı
    stok tükenmesi yaşandı  +  sistem sessiz kaldı            → kaçırdı

"Sistem sipariş dedi ve tükenme olmadı" hücresi **yanlış alarm sayılmıyor**
ve bu bilinçli: elde yeterli stok olduğu için tükenme yaşanmamış olabilir,
ki bu tam olarak sipariş önerisinin amacı. Bu hücreyi hataya yazmak,
tedbirli davranmayı cezalandırmak olurdu.

⚠️ Dolayısıyla buradan çıkan sayı bir **duyarlılık (recall)** ölçüsüdür,
doğruluk değil. "Sistem gerçekleşen tükenmelerin %X'ini önceden işaret
etti" denebilir; "sistem %X doğru karar verdi" denemez.

## Geçmiş stok nereden geliyor

ERP'ler günlük stok fotoğrafı saklamaz; elde bugünkü bakiye vardır. Geçmiş
stok, bakiyeden geriye doğru yürünerek kuruluyor:

    stok(t) = stok(bugün) - Σ giriş(t+1..bugün) + Σ çıkış(t+1..bugün)

⚠️ Bu, `hareketler.csv`'de **giriş hareketlerinin de bulunmasını** şart
koşuyor. Yalnızca satış satırları varsa geçmiş stok kurulamaz ve modül
açık bir hata verir — sessizce yanlış sayı üretmez.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from app.adapters.csv_erp import KOLON_ESLESMELERI, CsvBicimHatasi, _normalle, kolonlari_esle
from app.contracts import KararTipi
from app.domain.stock.decide import ozellikten_karar_uret
from app.domain.stock.features import katalog_ozelliklerini_hesapla

VARSAYILAN_ADIM_GUN = 30
"""Ölçüm noktaları arası mesafe. Aylık, çünkü tedarik kararları da aylık
döngüde gözden geçiriliyor; günlük adım aynı bilgiyi 30 kat maliyetle verir."""

ISINMA_GUN = 90
"""İlk ölçüm noktasından önce bu kadar geçmiş olmalı. Altındaki bir noktada
ortalama talep ve sapma güvenilmez — sistemin göremediği bir şeyi
"kaçırdı" diye yazmak ölçümü haksız kılar."""


def hareket_akisini_oku(yol: Path) -> pd.DataFrame:
    """`hareketler.csv` → işaretli hareket akışı (`tarih`, `sku_id`, `net`).

    `csv_erp.hareketleri_oku`'dan farkı: o yalnızca **çıkışları** okuyup
    talebe çeviriyor, bu ikisini birden tutuyor. Geçmiş stoğu kurmak için
    giriş hareketleri şart.
    """
    ham = pd.read_csv(yol)
    df = kolonlari_esle(ham, ("tarih", "sku_id", "miktar"), yol.name)

    tip_var = "hareket_tipi" in df.columns or any(
        _normalle(k) in KOLON_ESLESMELERI["hareket_tipi"] for k in ham.columns
    )
    if not tip_var:
        raise CsvBicimHatasi(
            f"{yol.name}: geriye dönük test için 'hareket_tipi' kolonu ZORUNLU.\n"
            "  Geçmiş stok, bugünkü bakiyeden geriye yürünerek kuruluyor;\n"
            "  giriş hareketleri olmadan bu hesap yapılamaz.\n"
            "  Yalnızca satış satırları varsa geriye dönük test koşulamaz."
        )

    df = kolonlari_esle(df, ("hareket_tipi",), yol.name)
    df["tarih"] = pd.to_datetime(df["tarih"], errors="coerce")
    df["sku_id"] = df["sku_id"].astype(str)
    df["miktar"] = pd.to_numeric(df["miktar"], errors="coerce").fillna(0).abs()

    cikis = df["hareket_tipi"].astype(str).str.lower().str.startswith(("cik", "çık", "sat"))
    df["net"] = np.where(cikis, -df["miktar"], df["miktar"])
    df["talep_miktari"] = np.where(cikis, df["miktar"], 0.0)

    return df.dropna(subset=["tarih"])[["tarih", "sku_id", "net", "talep_miktari"]]


def stok_gecmisini_kur(
    akis: pd.DataFrame, son_stok: pd.Series, son_tarih: dt.date
) -> pd.DataFrame:
    """Bugünkü bakiyeden geriye yürüyerek günlük stok tablosu kurar.

    Dönen tablo: satırlar tarih, sütunlar SKU.

    ⚠️ Negatif stok **sıfıra kırpılmıyor.** Kırpmak, veri tutarsızlığını
    (eksik giriş kaydı, sayım farkı) gizlerdi; çağıran taraf negatif değer
    görürse veriye güvenmemeyi bilmeli.
    """
    ts = pd.Timestamp(son_tarih)
    gunluk_net = (
        akis[akis["tarih"] <= ts]
        .pivot_table(index="tarih", columns="sku_id", values="net", aggfunc="sum")
        .fillna(0.0)
    )
    if gunluk_net.empty:
        raise CsvBicimHatasi("Hareket akışı boş — geriye dönük test koşulamaz.")

    tam_index = pd.date_range(gunluk_net.index.min(), ts, freq="D")
    gunluk_net = gunluk_net.reindex(tam_index, fill_value=0.0)
    sku_ids = gunluk_net.columns
    son = son_stok.reindex(sku_ids).fillna(0.0).to_numpy(dtype=float)

    # Sondan başa: stok(t) = stok(t+1) - net(t+1)
    net = gunluk_net.to_numpy(dtype=float)
    stok = np.empty_like(net)
    stok[-1] = son
    for i in range(len(net) - 2, -1, -1):
        stok[i] = stok[i + 1] - net[i + 1]

    return pd.DataFrame(stok, index=gunluk_net.index, columns=sku_ids)


def _stok_tukenmesi_yasandi(
    stok_gecmisi: pd.DataFrame,
    talep_genis: pd.DataFrame,
    sku_id: str,
    baslangic: pd.Timestamp,
    bitis: pd.Timestamp,
) -> bool:
    """Pencerede stok sıfırlanırken talep var mıydı?

    ⚠️ "Stok sıfır" tek başına yetmiyor: hiç talep görmeyen bir üründe sıfır
    stok tükenmesi değil, sadece stoksuzluk. Tükenme, **karşılanamayan
    talep** demek — gerçek veride o doğrudan gözlenemediği için en yakın
    vekil bu.
    """
    if sku_id not in stok_gecmisi.columns:
        return False
    pencere = (stok_gecmisi.index >= baslangic) & (stok_gecmisi.index <= bitis)
    if not pencere.any():
        return False

    stok = stok_gecmisi.loc[pencere, sku_id]
    talep = (
        talep_genis.loc[pencere, sku_id]
        if sku_id in talep_genis.columns
        else pd.Series(0.0, index=stok.index)
    )
    return bool(((stok <= 0) & (talep > 0)).any())


def geriye_donuk_test(
    dizin: Path,
    adim_gun: int = VARSAYILAN_ADIM_GUN,
    isinma_gun: int = ISINMA_GUN,
) -> pd.DataFrame:
    """Geçmiş veri üzerinde ölçüm noktası başına karar + sonuç tablosu.

    Her satır bir (ölçüm tarihi, SKU) çifti:

    · `siparis_onerildi` — sistem o gün sipariş dedi mi
    · `tukenme_yasandi`  — sonraki tedarik süresi içinde stok sıfırlanırken
                           talep var mıydı
    · `yakaladi`         — ikisi birden

    Özet için `geriye_donuk_ozet` kullanılır.
    """
    from app.adapters.csv_erp import (
        envanter_tablosu,
        siparislerden_tedarikci_tablosu,
        urunleri_oku,
    )

    sku_df = urunleri_oku(dizin / "urunler.csv")
    tedarikciler = siparislerden_tedarikci_tablosu(dizin / "siparisler.csv", sku_df)
    akis = hareket_akisini_oku(dizin / "hareketler.csv")

    son_tarih = akis["tarih"].max().date()
    son_stok = pd.Series(
        pd.to_numeric(sku_df["eldeki_stok"], errors="coerce").fillna(0).to_numpy(),
        index=sku_df["sku_id"].astype(str),
    )
    stok_gecmisi = stok_gecmisini_kur(akis, son_stok, son_tarih)

    # ⚠️ Aynı gün hem giriş hem çıkış satırı olabiliyor; toplanmazsa
    # (tarih, sku_id) çifti yinelenir ve özellik hesabındaki pivot patlar.
    talep = (
        akis.groupby(["tarih", "sku_id"], as_index=False)["talep_miktari"].sum()
    )
    talep_genis = (
        talep.pivot_table(index="tarih", columns="sku_id", values="talep_miktari", aggfunc="sum")
        .reindex(stok_gecmisi.index)
        .fillna(0.0)
    )

    # Hiç hareketi olmayan ürünler dışarıda — `ozellikleri_uret` ile aynı
    # gerekçe: satış görmemiş üründe "günlük ortalama talep" anlamsız.
    hareketli = set(talep["sku_id"].unique())
    sku_df = sku_df[sku_df["sku_id"].astype(str).isin(hareketli)].reset_index(drop=True)

    baslangic = stok_gecmisi.index.min() + pd.Timedelta(days=isinma_gun)
    olcum_tarihleri = pd.date_range(baslangic, stok_gecmisi.index.max(), freq=f"{adim_gun}D")

    # ⚠️ Yeniden kurulan stok negatife düşebilir: eksik giriş kaydı, sayım
    # farkı ya da tutarsız veri. `stok_gecmisini_kur` bunu bilinçli olarak
    # kırpmıyor — sorunu görünür tutuyor. Ama özellik hesabı negatif stok
    # kabul etmiyor (`StockFeatures.eldeki_stok >= 0`), o yüzden burada
    # kırpılıyor ve **kaç gün kırpıldığı sayılıp raporlanıyor**. Sessizce
    # kırpmak, veri kalitesi sorununu ölçüm sonucuna gömerdi.
    negatif_gun = int((stok_gecmisi < 0).to_numpy().sum())

    satirlar = []
    for olcum in olcum_tarihleri:
        # ⚠️ Ölçüm anındaki stok, o günün yeniden kurulmuş bakiyesi —
        # bugünkü bakiye DEĞİL. Bugünküyle hesaplamak geleceği görmek olurdu.
        gunun_stogu = stok_gecmisi.loc[olcum].clip(lower=0.0)
        sku_o_gun = sku_df.copy()
        sku_o_gun["eldeki_stok"] = (
            sku_o_gun["sku_id"].astype(str).map(gunun_stogu).fillna(0.0).to_numpy()
        )

        # ⚠️ Talep tablosu ölçüm tarihine kadar KIRPILIYOR. Kırpılmazsa
        # `katalog_ozelliklerini_hesapla` geleceği görmez ama envanter
        # tablosu görür — ve o gün için "son hareket" yanlış çıkar.
        talep_o_gune_kadar = talep[talep["tarih"] <= olcum]
        envanter = envanter_tablosu(sku_o_gun, talep_o_gune_kadar, olcum.date())

        ozellikler = katalog_ozelliklerini_hesapla(
            olcum_tarihi=olcum.date(),
            talep=talep_o_gune_kadar,
            envanter_gunluk=envanter,
            sku_df=sku_o_gun,
            tedarikci_df=tedarikciler,
        )

        for ozellik in ozellikler:
            karar = ozellikten_karar_uret(ozellik)
            bitis = olcum + pd.Timedelta(days=float(ozellik.tedarik_suresi_gun))
            tukendi = _stok_tukenmesi_yasandi(
                stok_gecmisi, talep_genis, ozellik.sku_id, olcum, bitis
            )
            onerildi = karar.tip is KararTipi.STOK_SIPARIS
            satirlar.append(
                {
                    "olcum_tarihi": olcum.date(),
                    "sku_id": ozellik.sku_id,
                    "siparis_onerildi": onerildi,
                    "tukenme_yasandi": tukendi,
                    "yakaladi": onerildi and tukendi,
                    "kacirdi": (not onerildi) and tukendi,
                }
            )

    sonuc = pd.DataFrame(satirlar)
    # Veri kalitesi sinyali satır bazında değil koşu bazında anlamlı;
    # `attrs` ile taşınıyor ki tabloya sahte bir kolon eklenmesin.
    sonuc.attrs["negatif_stok_gun"] = negatif_gun
    return sonuc


def geriye_donuk_ozet(sonuc: pd.DataFrame) -> dict[str, float]:
    """Tek satırlık karne.

    ⚠️ `duyarlilik` = yakalanan / gerçekleşen tükenme. Doğruluk DEĞİL —
    modül docstring'indeki gerekçe. Rapora "sistem tükenmelerin %X'ini
    önceden işaret etti" diye geçmeli.

    ⚠️⚠️ **`duyarlilik` tek başına okunamaz; `siparis_onerisi_orani` ile
    birlikte okunur.** Her ölçüm noktasında "sipariş ver" diyen bir sistem
    %100 duyarlılık alır ve hiçbir şey öğretmez. İlk deneme koşusunda tam
    olarak bu çıktı: duyarlılık 1,00 ve sipariş önerisi oranı da 1,00 —
    yani sayı, sistemin iyi olduğunu değil sürekli sipariş dediğini
    gösteriyordu.

    Anlamlı bir sonuç, sipariş önerisi oranı 1'in belirgin altındayken
    yüksek duyarlılıktır.
    """
    tukenme = int(sonuc["tukenme_yasandi"].sum())
    yakalanan = int(sonuc["yakaladi"].sum())

    return {
        "olcum_noktasi": float(sonuc["olcum_tarihi"].nunique()),
        "karar_sayisi": float(len(sonuc)),
        "tukenme_sayisi": float(tukenme),
        "yakalanan": float(yakalanan),
        "kacirilan": float(sonuc["kacirdi"].sum()),
        "duyarlilik": yakalanan / tukenme if tukenme else 0.0,
        "siparis_onerisi_orani": float(sonuc["siparis_onerildi"].mean()) if len(sonuc) else 0.0,
        # ⚠️ Sıfırdan büyükse veriye dikkat: bakiye ile hareketler
        # tutarsız. Ölçüm yine de koşuyor ama sonucun güvenilirliği düşer.
        "negatif_stok_gun": float(sonuc.attrs.get("negatif_stok_gun", 0)),
    }


__all__ = [
    "ISINMA_GUN",
    "VARSAYILAN_ADIM_GUN",
    "geriye_donuk_ozet",
    "geriye_donuk_test",
    "hareket_akisini_oku",
    "stok_gecmisini_kur",
]
