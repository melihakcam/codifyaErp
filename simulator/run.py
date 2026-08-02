"""3 yıl x günlük olay döngüsü.

Sahip: Kişi A · Faz 1 A1.3

Her gün sırayla: (1) müşteri siparişleri düşer, (2) stok varsa sevk edilir —
yoksa karşılanamayan talep ayrı tabloya kaydedilir, (3) basit bir sipariş
politikası eşik altına düşen SKU'lar için tedarikçiye sipariş açar, (4) yoldaki
siparişler tedarik süresi sonunda gelir, (5) sevk edilen her satış için fatura
kesilir, ödeme müşteri segmentinin vadesine göre gecikmeli planlanır.

    DİKKAT: buradaki sipariş politikası KASITLI OLARAK VASAT olmalı —
    Faz 5'te AI politikasını buna karşı ölçeceğiz. Bu senin taban çizgin.
    Eşik/hedef gün sayıları sabit ve kaba (10 günlük altına düşünce 30 günlük
    sipariş ver) — gerçek emniyet stoğu/EOQ formülü kullanmaz, kasıtlı olarak.

Performans notu: 2.000 SKU x ~1.095 gün için satır satır Python döngüsü yerine
her günü tüm SKU'lar için tek seferde işleyen **vektörize** bir döngü kullanılır
(gün ekseni Python `for`, SKU ekseni numpy). Böylece "olay tabanlı" mantık
korunurken tam katalog saniyeler içinde simüle edilir.
"""

from __future__ import annotations

import argparse
import datetime as dt
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from simulator.catalog import katalog_uret
from simulator.company import CompanyProfile, yapi_malzemesi_toptancisi
from simulator.demand import katalog_icin_talep_uret, temel_gunluk_hiz
from simulator.pathologies import PatolojiKonfigurasyonu, patolojiler_uret

ROP_ESIK_GUN = 10.0
"""Kasıtlı vasat eşik: net pozisyon bu kadar günlük tüketimin altına düşerse sipariş verilir."""

SIPARIS_HEDEF_GUN = 30.0
"""Kasıtlı vasat hedef: sipariş, bu kadar günlük tüketimi karşılayacak miktarda verilir."""

TALEP_ORTALAMA_PENCERE_GUN = 30
"""Sipariş politikasının 'ortalama günlük talep' tahmini için kullandığı kayan pencere."""

BASLANGIC_STOK_GUN_KARSILIGI = 20.0
"""Simülasyon başlangıcındaki stok, ort. günlük talebin kaç katı olsun (ilk günlerde
gereksiz sipariş patlamasını önlemek için makul bir başlangıç noktası)."""


def _bos_veya_birlestir(parcalar: list[pd.DataFrame], kolonlar: list[str]) -> pd.DataFrame:
    if not parcalar:
        return pd.DataFrame(columns=kolonlar)
    return pd.concat(parcalar, ignore_index=True)


def simulasyon_calistir(
    profile: CompanyProfile | None = None,
    seed: int = 42,
    yil_sayisi: int = 3,
    baslangic_tarihi: dt.date = dt.date(2022, 1, 1),
    patoloji_konfig: PatolojiKonfigurasyonu | None = None,
) -> dict[str, pd.DataFrame]:
    """3 yıllık (varsayılan) günlük olay döngüsünü tüm katalog için çalıştırır.

    `patoloji_konfig=None` (varsayılan) → tüm patolojiler kapalı, "sağlıklı" veri;
    A1.3'teki davranışla bit bit aynıdır. Bir `PatolojiKonfigurasyonu` verilirse
    (`simulator.pathologies`), açık olan patolojiler günlük döngüye enjekte edilir
    ve her enjeksiyon `patoloji_olaylari` tablosuna loglanır.

    Döner:
        `sku`, `tedarikci`, `musteri` — katalog tabloları (`catalog.katalog_uret`)
        `talep` — SKU x gün talep serisi (patoloji sonrası, gerçekleşen)
        `envanter_gunluk` — her SKU x gün için eldeki/yoldaki stok anlık görüntüsü
        `karsilanamayan_talep` — talebin tam karşılanamadığı SKU x gün satırları
        `siparisler` — tedarikçiye açılan sipariş olayları
        `faturalar` — sevkiyat karşılığı kesilen faturalar + planlanan ödeme tarihi
        `mutabakat` — SKU başına giriş/çıkış/son stok mutabakatı (sayım düzeltmesi dahil)
        `sayim_kayitlari` — gerçekleşen fiziksel sayım düzeltmeleri
        `patoloji_olaylari` — hangi patolojinin ne zaman enjekte edildiği
    """
    profile = profile or yapi_malzemesi_toptancisi()

    # Talep ve tedarik rastgeleliği katalog rastgeleliğinden ayrı tutulur ki
    # aynı katalog farklı talep/tedarik gerçekleşmeleriyle yeniden çalıştırılabilsin.
    talep_rng = np.random.default_rng(seed + 1)
    tedarik_rng = np.random.default_rng(seed + 2)
    patoloji_rng = np.random.default_rng(seed + 3)

    kataloglar = katalog_uret(profile, seed=seed)
    sku_df = kataloglar["sku"].reset_index(drop=True)
    tedarikci_df = kataloglar["tedarikci"].set_index("tedarikci_id")
    musteri_df = kataloglar["musteri"]

    n_sku = len(sku_df)
    gun_sayisi = 365 * yil_sayisi
    sku_ids = sku_df["sku_id"].to_numpy()
    tarihler = pd.date_range(baslangic_tarihi, periods=gun_sayisi, freq="D")

    patoloji_ciktilari = patolojiler_uret(
        profile, sku_df, tedarikci_df, tarihler, patoloji_rng, patoloji_konfig
    )

    talep_df = katalog_icin_talep_uret(
        sku_df, profile, baslangic_tarihi, gun_sayisi, talep_rng
    )
    talep_wide = (
        talep_df.pivot(index="tarih", columns="sku_id", values="talep_miktari")
        .reindex(columns=sku_ids)
        .to_numpy()
    )
    talep_wide = np.round(talep_wide * patoloji_ciktilari.talep_carpani).astype(int)
    talep_df = pd.DataFrame(
        {
            "tarih": np.repeat(tarihler.to_numpy(), n_sku),
            "sku_id": np.tile(sku_ids, gun_sayisi),
            "talep_miktari": talep_wide.reshape(-1),
        }
    )

    sku_tedarikci_id = sku_df["tedarikci_id"].to_numpy()
    ort_tedarik_suresi = tedarikci_df.loc[sku_tedarikci_id, "ort_tedarik_suresi_gun"].to_numpy()
    tedarik_suresi_std = tedarikci_df.loc[sku_tedarikci_id, "tedarik_suresi_std_gun"].to_numpy()
    paket_adedi = sku_df["paket_adedi"].to_numpy()
    moq = sku_df["moq"].to_numpy()
    birim_maliyet = sku_df["birim_maliyet_tl"].to_numpy()
    satis_fiyati = sku_df["satis_fiyati_tl"].to_numpy()
    odeme_vadeleri = musteri_df["odeme_vadesi_gun"].to_numpy()

    tedarikci_id_to_idx = {tid: i for i, tid in enumerate(tedarikci_df.index)}
    sku_tedarikci_idx = np.array([tedarikci_id_to_idx[t] for t in sku_tedarikci_id])

    sku_id_to_idx = {sid: i for i, sid in enumerate(sku_ids)}
    sayim_gunu_haritasi: dict[int, list[tuple[int, float]]] = defaultdict(list)
    if not patoloji_ciktilari.sayim_denetimleri.empty:
        tarih_to_gun = {tarih: i for i, tarih in enumerate(tarihler)}
        for satir in patoloji_ciktilari.sayim_denetimleri.itertuples(index=False):
            gun = tarih_to_gun.get(satir.tarih)
            if gun is not None:
                sayim_gunu_haritasi[gun].append((sku_id_to_idx[satir.sku_id], satir.fark_orani))

    ort_gunluk_talep_katalog = np.array(
        [
            temel_gunluk_hiz(satir.yillik_ciro_payi, satir.satis_fiyati_tl, profile)
            for satir in sku_df.itertuples(index=False)
        ]
    )
    stok = np.round(ort_gunluk_talep_katalog * BASLANGIC_STOK_GUN_KARSILIGI).astype(float)
    baslangic_stogu = stok.copy()
    yoldaki_stok = np.zeros(n_sku)

    gelecek_teslimatlar: dict[int, list[tuple[np.ndarray, np.ndarray]]] = defaultdict(list)
    talep_gecmisi = np.zeros((TALEP_ORTALAMA_PENCERE_GUN, n_sku))

    toplam_teslim_alinan = np.zeros(n_sku)
    toplam_sevkiyat = np.zeros(n_sku)
    toplam_sayim_duzeltmesi = np.zeros(n_sku)

    envanter_kayitlari: list[pd.DataFrame] = []
    karsilanamayan_kayitlari: list[pd.DataFrame] = []
    siparis_kayitlari: list[pd.DataFrame] = []
    fatura_kayitlari: list[pd.DataFrame] = []
    sayim_kayitlari: list[dict] = []

    for t in range(gun_sayisi):
        tarih = tarihler[t]

        # 4. Yoldaki siparişlerden bugün varan varsa teslim al.
        for sku_idx_arr, miktar_arr in gelecek_teslimatlar.pop(t, []):
            stok[sku_idx_arr] += miktar_arr
            yoldaki_stok[sku_idx_arr] -= miktar_arr
            toplam_teslim_alinan[sku_idx_arr] += miktar_arr

        # Fiziksel sayım denetimi varsa: kayıtlı stok gerçek sayımla değiştirilir.
        # Bu fark sevkiyat/teslimattan gelmez — mutabakatta ayrı bir terim olarak yer alır.
        for sku_idx, fark_orani in sayim_gunu_haritasi.pop(t, []):
            eski = stok[sku_idx]
            delta = round(eski * fark_orani)
            stok[sku_idx] = max(0.0, eski + delta)
            gerceklesen_delta = stok[sku_idx] - eski
            toplam_sayim_duzeltmesi[sku_idx] += gerceklesen_delta
            sayim_kayitlari.append(
                {
                    "tarih": tarih,
                    "sku_id": sku_ids[sku_idx],
                    "kayitli_stok": eski,
                    "sayilan_stok": stok[sku_idx],
                    "fark_miktari": gerceklesen_delta,
                }
            )

        # 1-2. Müşteri talebi düşer, stok varsa sevk edilir; yoksa karşılanamaz.
        talep_bugun = talep_wide[t]
        sevkiyat = np.minimum(talep_bugun, stok)
        karsilanamayan = talep_bugun - sevkiyat
        stok -= sevkiyat
        toplam_sevkiyat += sevkiyat

        karsilanamayan_idx = np.nonzero(karsilanamayan > 0)[0]
        if len(karsilanamayan_idx) > 0:
            karsilanamayan_kayitlari.append(
                pd.DataFrame(
                    {
                        "tarih": tarih,
                        "sku_id": sku_ids[karsilanamayan_idx],
                        "karsilanamayan_miktar": karsilanamayan[karsilanamayan_idx],
                    }
                )
            )

        # Kayan pencere: sipariş politikasının kullandığı "ortalama günlük talep" tahmini.
        talep_gecmisi[t % TALEP_ORTALAMA_PENCERE_GUN] = talep_bugun
        gecerli_gun_sayisi = min(t + 1, TALEP_ORTALAMA_PENCERE_GUN)
        ort_gunluk_talep = talep_gecmisi.sum(axis=0) / gecerli_gun_sayisi

        # 3. Kasıtlı vasat sipariş politikası: net pozisyon eşik altındaysa sipariş.
        net_pozisyon = stok + yoldaki_stok
        esik = ROP_ESIK_GUN * ort_gunluk_talep
        siparis_gerekiyor = (net_pozisyon < esik) & (ort_gunluk_talep > 0)
        siparis_idx = np.nonzero(siparis_gerekiyor)[0]

        if len(siparis_idx) > 0:
            hedef_gun_carpani = patoloji_ciktilari.siparis_hedef_gun_carpani[t, siparis_idx]
            hedef_miktar = SIPARIS_HEDEF_GUN * hedef_gun_carpani * ort_gunluk_talep[siparis_idx]
            paket_katlari = np.maximum(1, np.ceil(hedef_miktar / paket_adedi[siparis_idx]))
            siparis_miktari = paket_katlari * paket_adedi[siparis_idx]
            siparis_miktari = np.maximum(siparis_miktari, moq[siparis_idx])

            ek_gecikme = patoloji_ciktilari.tedarik_ek_gecikme_gun[
                t, sku_tedarikci_idx[siparis_idx]
            ]
            tedarik_suresi = np.maximum(
                1,
                np.round(
                    tedarik_rng.normal(
                        ort_tedarik_suresi[siparis_idx], tedarik_suresi_std[siparis_idx]
                    )
                    + ek_gecikme
                ),
            ).astype(int)

            maliyet_carpani = patoloji_ciktilari.birim_maliyet_carpani[
                t, sku_tedarikci_idx[siparis_idx]
            ]

            yoldaki_stok[siparis_idx] += siparis_miktari

            # Aynı varış gününe denk gelen siparişleri tek olayda topla.
            varis_gunleri = t + tedarik_suresi
            for varis_gunu in np.unique(varis_gunleri):
                if varis_gunu >= gun_sayisi:
                    # Simülasyon penceresinin dışına düşen teslimat: yoldaki_stok'ta
                    # kalır, toplam_teslim_alinan'a hiç girmez — mutabakat bunu
                    # zaten doğru şekilde dışlar.
                    continue
                mask = varis_gunleri == varis_gunu
                gelecek_teslimatlar[int(varis_gunu)].append(
                    (siparis_idx[mask], siparis_miktari[mask])
                )

            siparis_kayitlari.append(
                pd.DataFrame(
                    {
                        "tarih": tarih,
                        "sku_id": sku_ids[siparis_idx],
                        "tedarikci_id": sku_tedarikci_id[siparis_idx],
                        "siparis_miktari": siparis_miktari,
                        "beklenen_tedarik_suresi_gun": tedarik_suresi,
                        "tutar_tl": siparis_miktari * birim_maliyet[siparis_idx] * maliyet_carpani,
                    }
                )
            )

        # 5. Sevk edilen satışlar için fatura + gecikmeli ödeme planı.
        fatura_idx = np.nonzero(sevkiyat > 0)[0]
        if len(fatura_idx) > 0:
            vade = tedarik_rng.choice(odeme_vadeleri, size=len(fatura_idx))
            fatura_kayitlari.append(
                pd.DataFrame(
                    {
                        "tarih": tarih,
                        "sku_id": sku_ids[fatura_idx],
                        "tutar_tl": sevkiyat[fatura_idx] * satis_fiyati[fatura_idx],
                        "odeme_vadesi_gun": vade,
                        "odeme_tarihi": tarih + pd.to_timedelta(vade, unit="D"),
                    }
                )
            )

        envanter_kayitlari.append(
            pd.DataFrame(
                {
                    "tarih": tarih,
                    "sku_id": sku_ids,
                    "eldeki_stok": stok.copy(),
                    "yoldaki_stok": yoldaki_stok.copy(),
                }
            )
        )

    envanter_gunluk = pd.concat(envanter_kayitlari, ignore_index=True)
    karsilanamayan_talep = _bos_veya_birlestir(
        karsilanamayan_kayitlari, ["tarih", "sku_id", "karsilanamayan_miktar"]
    )
    siparisler = _bos_veya_birlestir(
        siparis_kayitlari,
        [
            "tarih",
            "sku_id",
            "tedarikci_id",
            "siparis_miktari",
            "beklenen_tedarik_suresi_gun",
            "tutar_tl",
        ],
    )
    faturalar = _bos_veya_birlestir(
        fatura_kayitlari,
        ["tarih", "sku_id", "tutar_tl", "odeme_vadesi_gun", "odeme_tarihi"],
    )
    sayim_kayitlari_df = _bos_veya_birlestir(
        [pd.DataFrame(sayim_kayitlari)] if sayim_kayitlari else [],
        ["tarih", "sku_id", "kayitli_stok", "sayilan_stok", "fark_miktari"],
    )

    mutabakat = pd.DataFrame(
        {
            "sku_id": sku_ids,
            "baslangic_stok": baslangic_stogu,
            "toplam_teslim_alinan": toplam_teslim_alinan,
            "toplam_sayim_duzeltmesi": toplam_sayim_duzeltmesi,
            "toplam_sevkiyat": toplam_sevkiyat,
            "son_stok": stok,
        }
    )
    mutabakat["fark"] = (
        mutabakat["baslangic_stok"]
        + mutabakat["toplam_teslim_alinan"]
        + mutabakat["toplam_sayim_duzeltmesi"]
        - mutabakat["toplam_sevkiyat"]
        - mutabakat["son_stok"]
    )

    return {
        "sku": sku_df,
        "tedarikci": kataloglar["tedarikci"],
        "musteri": musteri_df,
        "talep": talep_df,
        "envanter_gunluk": envanter_gunluk,
        "karsilanamayan_talep": karsilanamayan_talep,
        "siparisler": siparisler,
        "faturalar": faturalar,
        "sayim_kayitlari": sayim_kayitlari_df,
        "mutabakat": mutabakat,
        "patoloji_olaylari": patoloji_ciktilari.olay_logu,
    }


def sonucu_diske_yaz(
    sonuc: dict[str, pd.DataFrame], seed: int, taban_dizin: Path = Path("data/sim")
) -> Path:
    """Simülasyon çıktısındaki her tabloyu `taban_dizin/<seed>/<tablo>.parquet` olarak yazar.

    Aynı seed ile tekrar çalıştırıldığında dosyalar üzerine yazılır — sonuç
    deterministik olduğundan bu zararsızdır (A1.1/A1.3'teki determinizm garantisi).
    """
    hedef_dizin = taban_dizin / str(seed)
    hedef_dizin.mkdir(parents=True, exist_ok=True)
    for tablo_adi, df in sonuc.items():
        df.to_parquet(hedef_dizin / f"{tablo_adi}.parquet", index=False)
    return hedef_dizin


_PROFIL_HARITASI = {"kobi_yapi": yapi_malzemesi_toptancisi}


def _cli() -> None:
    ayristirici = argparse.ArgumentParser(description="Codifya simülatör — 3 yıllık olay döngüsü")
    ayristirici.add_argument("--years", type=int, default=3, dest="yil_sayisi")
    ayristirici.add_argument("--seed", type=int, default=42)
    ayristirici.add_argument("--profile", type=str, default="kobi_yapi", choices=_PROFIL_HARITASI)
    ayristirici.add_argument(
        "--patoloji", action="store_true", help="Tüm patolojileri açık şekilde koştur (demo amaçlı)"
    )
    ayristirici.add_argument(
        "--disk-yaz", action="store_true", help="Sonucu data/sim/<seed>/ altına Parquet olarak yaz"
    )
    args = ayristirici.parse_args()

    profile = _PROFIL_HARITASI[args.profile]()
    patoloji_konfig = (
        PatolojiKonfigurasyonu(
            tedarikci_gecikmesi_aktif=True,
            talep_patlamasi_aktif=True,
            olu_stok_aktif=True,
            fiyat_zammi_aktif=True,
            sezon_sonu_fazlasi_aktif=True,
            sayim_farki_aktif=True,
        )
        if args.patoloji
        else None
    )
    sonuc = simulasyon_calistir(
        profile=profile,
        seed=args.seed,
        yil_sayisi=args.yil_sayisi,
        patoloji_konfig=patoloji_konfig,
    )

    print(f"SKU sayısı: {len(sonuc['sku'])}")
    print(f"Envanter satırı: {len(sonuc['envanter_gunluk'])}")
    print(f"Negatif stok satırı (0 olmalı): {(sonuc['envanter_gunluk']['eldeki_stok'] < 0).sum()}")
    print(f"Karşılanamayan talep satırı: {len(sonuc['karsilanamayan_talep'])}")
    print(f"Sipariş sayısı: {len(sonuc['siparisler'])}")
    print(f"Mutabakat max |fark|: {sonuc['mutabakat']['fark'].abs().max():.6f}")
    print(f"Enjekte edilen patoloji olayı sayısı: {len(sonuc['patoloji_olaylari'])}")

    if args.disk_yaz:
        hedef = sonucu_diske_yaz(sonuc, seed=args.seed)
        print(f"Parquet olarak yazıldı: {hedef}")


if __name__ == "__main__":
    _cli()
