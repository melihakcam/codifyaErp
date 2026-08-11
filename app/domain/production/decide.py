"""Üretim emri kararı — kural motoru + tahminin birleştiği yer.

Sahip: Kişi A · Faz 10 A10.2

## ⚠️ Neden liste döndürüyor

`ozellikten_kararlar_uret` tek bir karar değil **liste** döndürüyor, bugün
listede hep bir eleman olsa bile. Sebep Faz 7'de öğrenildi: finans kararı
tekil döndürüyordu, sonra bir müşterinin aynı anda hem karşılık hem takip
kararı alabildiği ortaya çıktı ve değişiklik API'ye kadar dalga yaptı
(`BILINEN-EKSIKLER.md` §9, B1).

Üretimde aynısı **kesin** olacak: Adım 4'ün kapasite kararı emir kararıyla
ortogonal — bir kalem için hem "emir aç" hem "hat dolu, ertele" aynı anda
doğru olabilir. Şimdi liste döndürmek, o adımda hiçbir şeyin kırılmaması
demek.

## Karar kolları dışlayıcı, ve bu doğru

`emir_ac` / `emir_erteleme` / `aksiyon_yok` **aynı soruya** cevap veriyor:
"bu kalemden şimdi üretmeli miyim?" Üçü birden uygulanamaz. Stoktaki
`tasfiye → sipariş` dışlaması da böyleydi ve incelemede doğru çıkmıştı;
finanstaki kusur ise kolların gerçekte ortogonal olmasıydı
(`app/domain/stock/decide.py` docstring'i, A2 incelemesi).

⚠️ Adım 4'ün kapasite kararı bu zincire **eklenmeyecek**. Ortogonal kol,
ortogonal üretilir — listeye ayrı bir eleman olarak girer.
"""

from __future__ import annotations

from app.contracts import (
    Alan,
    DecisionCandidate,
    FiredRule,
    KararTipi,
    UretimOzellikleri,
)
from app.core.isletme_profili import UretimProfili, profil
from app.domain.production.rules import (
    acik_hesapla,
    emir_ekonomik_mi,
    emir_miktari_hesapla,
    hat_yuku_saat,
    ihtiyac_hesapla,
    uretim_suresi_yetiyor_mu,
)

KURAL_SURUMU = "1.0-uretim"

GUVEN_AGIRLIK_VERI_YETERLILIGI = 0.40
GUVEN_AGIRLIK_TAHMIN_BELIRSIZLIGI = 0.60
"""⚠️ Ağırlıklar stoktan farklı ve bilinçli.

Stokta üç bileşen vardı (veri yeterliliği, kural mutabakatı, tahmin
belirsizliği) ve tahmin bileşeni sabit bir sayıydı — çünkü ölçülmüş bir
tahmin yoktu. Üretimde tahmin **ölçüldü** ve kararın tamamı ona dayanıyor;
o yüzden en ağır bileşen o. "Kural mutabakatı" bileşeni ise burada yok:
kollar dışlayıcı, mutabık olacak ikinci bir kural yok."""

TAM_GUVEN_VERI_GUN = 365
"""Veri yeterliliği bu günde tavan yapıyor. Bir tam yıl: mevsimin tamamı
görülmüş demek. Stoktaki 90 günden uzun, çünkü üretim planı mevsimsel
kaymaya stok siparişinden daha duyarlı — parti büyük ve süreç uzun."""


def _tahmin_guven_puani(ozellik: UretimOzellikleri) -> float:
    """Bandın darlığı = tahminin güveni.

    Bant genişliği nokta tahminine oranlanıyor: 100 adet beklenen bir
    kalemde ±10 adetlik bant dar, ±200 adetlik bant kararı taşıyamaz.

    ⚠️ Tahmin 0 iken oran tanımsız. O durumda güven **düşük** sayılıyor,
    yüksek değil: "hiç satmayacak" tahmini kesinlik değil, çoğu zaman
    veri yokluğudur.
    """
    if ozellik.tahmin_toplam <= 0:
        return 0.3
    bagil_bant = ozellik.tahmin_bant_genisligi / ozellik.tahmin_toplam
    return float(max(0.0, 1.0 - min(1.0, bagil_bant / 2.0)))


def _guven_skoru_hesapla(ozellik: UretimOzellikleri) -> float:
    veri_puani = min(1.0, ozellik.veri_gun_sayisi / TAM_GUVEN_VERI_GUN)
    guven = (
        GUVEN_AGIRLIK_VERI_YETERLILIGI * veri_puani
        + GUVEN_AGIRLIK_TAHMIN_BELIRSIZLIGI * _tahmin_guven_puani(ozellik)
    )
    return float(min(1.0, max(0.0, guven)))


def _tahmin_kurali(ozellik: UretimOzellikleri) -> FiredRule:
    """Tahminin kendisi bir kural izi olarak kaydediliyor.

    ⚠️ Bu satır olmadan gerekçe metni tahmin sayılarını **kullanamaz**:
    guard yalnızca `izinli_sayilar()` kümesindeki sayılara izin veriyor ve
    kural değerleri o kümenin bir parçası. Yöntem adı da burada duruyor ki
    "hangi modelin ürettiği" karar kaydında kalsın.
    """
    return FiredRule(
        kod="TALEP_TAHMINI_ALINDI",
        aciklama=(
            f"{ozellik.tahmin_ufuk_gun} günlük ufukta {ozellik.tahmin_toplam:.0f} adet "
            f"talep bekleniyor ({ozellik.tahmin_yontemi})."
        ),
        degerler={
            "tahmin_toplam": round(ozellik.tahmin_toplam, 2),
            "tahmin_alt_band": round(ozellik.tahmin_alt_band, 2),
            "tahmin_ust_band": round(ozellik.tahmin_ust_band, 2),
            "tahmin_ufuk_gun": float(ozellik.tahmin_ufuk_gun),
        },
    )


def ozellikten_kararlar_uret(
    ozellik: UretimOzellikleri, uretim_profili: UretimProfili | None = None
) -> list[DecisionCandidate]:
    """Bir üretilen kalem için üretim kararları."""
    p = uretim_profili or profil().uretim

    ihtiyac = ihtiyac_hesapla(ozellik, p)
    acik = acik_hesapla(ozellik, p)

    kurallar: list[FiredRule] = [_tahmin_kurali(ozellik)]
    kurallar.append(
        FiredRule(
            kod="IHTIYAC_HESAPLANDI",
            aciklama=(
                "İhtiyaç, tahminin üst bandından hesaplandı; elde ve açık emirlerdeki "
                "miktar düşüldü."
            ),
            degerler={
                "ihtiyac": round(ihtiyac, 2),
                "net_pozisyon": float(ozellik.net_pozisyon),
                "acik_emir_miktari": float(ozellik.acik_emir_miktari),
            },
        )
    )

    if acik <= 0:
        return [_karar_kur(ozellik, KararTipi.URETIM_AKSIYON_YOK, {}, 0.0, kurallar, True)]

    miktar = emir_miktari_hesapla(acik, ozellik, p)
    yuk_saat = hat_yuku_saat(miktar, ozellik)

    if not emir_ekonomik_mi(miktar, ozellik, p):
        kurallar.append(
            FiredRule(
                kod="EMIR_EKONOMIK_DEGIL",
                aciklama=(
                    f"Açık {acik:.0f} adet ama {ozellik.hazirlik_suresi_saat:.1f} saatlik "
                    f"hazırlık süresini amorti edecek kadar değil; emir erteleniyor."
                ),
                degerler={
                    "acik": round(acik, 2),
                    "emir_miktari": float(miktar),
                    "hazirlik_suresi_saat": ozellik.hazirlik_suresi_saat,
                },
            )
        )
        return [
            _karar_kur(
                ozellik,
                KararTipi.URETIM_EMIR_ERTELEME,
                {"onerilen_miktar": miktar, "hat_id": ozellik.hat_id},
                0.0,
                kurallar,
                True,
            )
        ]

    kurallar.append(
        FiredRule(
            kod="URETIM_ACIGI_VAR",
            aciklama="Elde ve açık emirlerdeki miktar, ufuktaki ihtiyacı karşılamıyor.",
            degerler={"acik": round(acik, 2), "ihtiyac": round(ihtiyac, 2)},
        )
    )
    kurallar.append(
        FiredRule(
            kod="EMIR_MIKTARI_HESAPLANDI",
            aciklama=f"Açık, {ozellik.parti_buyuklugu} adetlik parti katına yuvarlandı.",
            degerler={
                "emir_miktari": float(miktar),
                "parti_buyuklugu": float(ozellik.parti_buyuklugu),
                "hat_yuku_saat": round(yuk_saat, 2),
            },
        )
    )

    if not uretim_suresi_yetiyor_mu(ozellik):
        # ⚠️ Bu erteleme sebebi DEĞİL. Emir yine açılıyor; kayıt, kararın
        # neden bugün geldiğini ve malın ufuk içinde yetişmeyeceğini
        # söylüyor. Sessiz geçmek, planı sistematik iyimser yapardı.
        kurallar.append(
            FiredRule(
                kod="URETIM_SURESI_UFKU_ASIYOR",
                aciklama=(
                    f"Üretim süresi {ozellik.uretim_suresi_gun:.0f} gün, planlama ufku "
                    f"{ozellik.tahmin_ufuk_gun} gün — mal ufuk içinde yetişmeyecek."
                ),
                degerler={
                    "uretim_suresi_gun": ozellik.uretim_suresi_gun,
                    "tahmin_ufuk_gun": float(ozellik.tahmin_ufuk_gun),
                },
            )
        )

    return [
        _karar_kur(
            ozellik,
            KararTipi.URETIM_EMIR_AC,
            {
                "emir_miktari": miktar,
                "hat_id": ozellik.hat_id,
                "hat_yuku_saat": round(yuk_saat, 2),
            },
            miktar * ozellik.birim_maliyet_tl,
            kurallar,
            # Açılmış bir üretim emri iptal edilebilir ama hazırlık yapıldıysa
            # o süre geri gelmez. Stok siparişinden daha az geri alınabilir,
            # tasfiyeden daha çok; "geri alınabilir" demek yine de doğru.
            True,
        )
    ]


def _karar_kur(
    ozellik: UretimOzellikleri,
    tip: KararTipi,
    aksiyon: dict[str, float | int | str | None],
    tutar: float,
    kurallar: list[FiredRule],
    geri_alinabilir: bool,
) -> DecisionCandidate:
    return DecisionCandidate(
        alan=Alan.URETIM,
        tip=tip,
        aksiyon=aksiyon,
        tahmini_tutar_tl=round(tutar, 2),
        geri_alinabilir=geri_alinabilir,
        guven=_guven_skoru_hesapla(ozellik),
        tetiklenen_kurallar=kurallar,
        ozellikler=ozellik,
        model_surumleri={"rules": KURAL_SURUMU, "tahmin": ozellik.tahmin_yontemi},
    )


# ---------------------------------------------------------------------------
# Demo dünyası girişi — Adım 6'nın (servis katmanı) tüketicisi
# ---------------------------------------------------------------------------

_URETIM_ONBELLEK: dict[int, dict] = {}


def _uretim_dunyasi(seed: int = 42) -> dict:
    """Fabrika ana verisi + ürün ağacı, process-içi önbellekte.

    Stok tarafındaki `_demo_dunyasini_yukle` deseni: kalıcı veri katmanı
    gelene kadar simülasyon bir kez koşuyor, sonraki çağrılar önbellekten
    dönüyor. Gecelik tarama bu sayede 2.000 SKU'yu tek simülasyonla tarıyor.
    """
    from app.domain.stock.decide import _demo_dunyasini_yukle
    from simulator.uretim import uretim_ana_verisi_uret, urun_agaci_uret

    if seed not in _URETIM_ONBELLEK:
        dunya = _demo_dunyasini_yukle(seed)
        uretim_df = uretim_ana_verisi_uret(dunya["sku"], dunya["talep"], seed=seed)
        _URETIM_ONBELLEK[seed] = {
            "dunya": dunya,
            "uretim": uretim_df,
            "urun_agaci": urun_agaci_uret(dunya["sku"], uretim_df, seed=seed),
        }
    return _URETIM_ONBELLEK[seed]


def uretim_kararlari_uret(kalem_id: str | None = None, seed: int = 42) -> list[DecisionCandidate]:
    """Üretim kararlarının tamamı: emir + kapasite.

    `kalem_id` verilirse yalnızca o kalem; verilmezse tüm üretilen katalog.

    ## ⚠️ Kapasite tek kalem için sorulamaz

    `kalem_id` verildiğinde bile kapasite hesabı **tüm hat** üzerinden
    yapılıyor: "bu emir hattı aşıyor mu" sorusunun cevabı diğer emirlere
    bağlı. Yalnızca istenen kalemin emrine bakıp "hat boş" demek, hattın
    dolu olduğu bir günde yanlış cevap vermek olurdu.

    Bu yüzden tek kalem sorgusu da tüm kataloğu hesaplıyor ve sonucu
    filtreliyor. Maliyeti önbellek karşılıyor.
    """
    from app.domain.production.features import kalem_ozelliklerini_hesapla
    from app.domain.production.kapasite import kapasite_kararlari_uret

    kayit = _uretim_dunyasi(seed)
    dunya, uretim_df = kayit["dunya"], kayit["uretim"]

    kararlar: list[DecisionCandidate] = []
    for sku_id in uretim_df["sku_id"]:
        ozellik = kalem_ozelliklerini_hesapla(
            sku_id=sku_id,
            olcum_tarihi=dunya["olcum_tarihi"],
            talep=dunya["talep"],
            envanter_gunluk=dunya["envanter_gunluk"],
            sku_df=dunya["sku"],
            uretim_df=uretim_df,
        )
        kararlar += ozellikten_kararlar_uret(ozellik)

    emirler = [k for k in kararlar if k.tip is KararTipi.URETIM_EMIR_AC]
    kararlar += kapasite_kararlari_uret(emirler)

    if kalem_id is None:
        return kararlar

    secilen = [
        k
        for k in kararlar
        if isinstance(k.ozellikler, UretimOzellikleri) and k.ozellikler.kalem_id == kalem_id
    ]
    if not secilen:
        raise KeyError(f"Üretilen kalem bulunamadı: {kalem_id}")
    return secilen


def hammadde_ihtiyaclari(seed: int = 42) -> dict[str, float]:
    """Açılması önerilen emirlerin doğurduğu hammadde ihtiyacı (MRP).

    Çıktısı `StockFeatures.mrp_ihtiyaci`'na verilmek üzere: hammadde
    sipariş kararı stok alanının işi, bu yalnızca ona giren ek talep.
    """
    from app.domain.production.mrp import hammadde_ihtiyaci_hesapla

    kayit = _uretim_dunyasi(seed)
    emirler = [k for k in uretim_kararlari_uret(seed=seed) if k.tip is KararTipi.URETIM_EMIR_AC]
    return {
        hammadde: ihtiyac.toplam_miktar
        for hammadde, ihtiyac in hammadde_ihtiyaci_hesapla(emirler, kayit["urun_agaci"]).items()
    }


__all__ = [
    "KURAL_SURUMU",
    "hammadde_ihtiyaclari",
    "ozellikten_kararlar_uret",
    "uretim_kararlari_uret",
]
