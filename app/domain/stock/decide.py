"""Stok kararı üretimi — kural motoru + ML'in birleştiği yer.

Sahip: Kişi A · Faz 2 A2.6

`stok_karari_uret()` gerçek karar üretimidir: `features.py` ham veriden
`StockFeatures` çıkarır, `rules.py` emniyet stoğu/ROP/EOQ/ABC-XYZ/ölü
stok/tedarikçi skorunu hesaplar, bu dosya hepsini birleştirip
`DecisionCandidate` döner. `decide_stub()` hâlâ burada duruyor — `app/api/`
Kişi B'nin sahipliğinde olduğu için `decisions.py`'deki tek satırlık
`decide_stub()` → `stok_karari_uret()` geçişini o yapacak (bkz. o dosyanın
docstring'i: "bu dosyada başka bir şey değişmeyecek").

**Veri kaynağı notu:** Kişi B'nin kalıcı veri katmanı (B1.x, SQLite) henüz
yok. Bu yüzden bu modül "demo dünyası" olarak `simulator.run.simulasyon_calistir`
çıktısını process-içi önbellekte tutar (`_ONBELLEK`) — ilk çağrıda bir kez
simüle edilir, sonraki her çağrı önbellekten milisaniyelerde döner. Kalıcı
veri katmanı geldiğinde bu önbellek DB sorgusuyla değişecek; `StockFeatures`
sözleşmesi sayesinde geri kalan hiçbir şey değişmeyecek.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from app.contracts import (
    ABCSinifi,
    Alan,
    DecisionCandidate,
    FiredRule,
    KararTipi,
    StockFeatures,
    XYZSinifi,
)
from app.domain.stock.features import (
    UZUN_PENCERE_GUN,
    katalog_ozelliklerini_hesapla,
    sku_ozelliklerini_hesapla,
)
from app.domain.stock.rules import (
    abc_xyz_siniflandir,
    olu_stok_degerlendir,
    rop_ve_emniyet_stogu,
    siparis_miktari_hesapla,
    tedarikci_degisim_degerlendir,
    tedarikci_skoru_hesapla,
)
from simulator.company import yapi_malzemesi_toptancisi
from simulator.run import simulasyon_calistir

KURAL_SURUMU = "0.2-gercek"

VARSAYILAN_SEED = 42
VARSAYILAN_YIL_SAYISI = 3

GUVEN_AGIRLIK_VERI_YETERLILIGI = 0.40
GUVEN_AGIRLIK_KURAL_MUTABAKATI = 0.35
GUVEN_AGIRLIK_TAHMIN_BELIRSIZLIGI = 0.25
VARSAYILAN_TAHMIN_GUVEN_PUANI = 0.70
"""ml.py (A2.7) henüz yazılmadı — talep tahmini belirsizliği bileşeni şimdilik
nötr bir sabittir. A2.7 tamamlanınca gerçek tahmin aralığından türetilecek."""

_ONBELLEK: dict[int, dict] = {}


def _demo_dunyasini_yukle(seed: int = VARSAYILAN_SEED) -> dict:
    """Simülasyonu bir kez çalıştırıp process-içi önbellekte tutar."""
    if seed not in _ONBELLEK:
        profile = yapi_malzemesi_toptancisi()
        sonuc = simulasyon_calistir(profile=profile, seed=seed, yil_sayisi=VARSAYILAN_YIL_SAYISI)
        sonuc["olcum_tarihi"] = sonuc["envanter_gunluk"]["tarih"].max().date()
        _ONBELLEK[seed] = sonuc
    return _ONBELLEK[seed]


def _siniflandirmayi_hesapla(dunya: dict) -> pd.DataFrame:
    """İki geçişli sınıflandırma: (1) varsayılanlarla tüm katalog için özellik
    çıkar, (2) gözlemlenen ciro/varyasyondan ABC/XYZ + tedarikçi skorunu
    hesaplayıp tek bir `siniflandirma` tablosunda birleştirir."""
    if "siniflandirma" in dunya:
        return dunya["siniflandirma"]

    on_ozellikler = katalog_ozelliklerini_hesapla(
        olcum_tarihi=dunya["olcum_tarihi"],
        talep=dunya["talep"],
        envanter_gunluk=dunya["envanter_gunluk"],
        sku_df=dunya["sku"],
        tedarikci_df=dunya["tedarikci"],
    )
    siniflandirma = abc_xyz_siniflandir(on_ozellikler)

    tedarikci_skorlari = tedarikci_skoru_hesapla(dunya["siparisler"], dunya["tedarikci"])
    sku_tedarikci = dunya["sku"].set_index("sku_id")["tedarikci_id"]
    siniflandirma["tedarikci_skoru"] = sku_tedarikci.map(tedarikci_skorlari["tedarikci_skoru"])

    dunya["siniflandirma"] = siniflandirma
    return siniflandirma


def _varsayilan_demo_sku_id(dunya: dict, siniflandirma: pd.DataFrame) -> str:
    """Sipariş kararını tetikleyen ilk SKU'yu seçer — `sku_id` verilmediğinde
    boş bir 'aksiyon yok' örneği yerine anlamlı bir demo kararı dönsün diye."""
    sku_ids = dunya["sku"]["sku_id"].to_numpy()
    for sku_id in sku_ids[:200]:
        ozellik = sku_ozelliklerini_hesapla(
            sku_id=sku_id,
            olcum_tarihi=dunya["olcum_tarihi"],
            talep=dunya["talep"],
            envanter_gunluk=dunya["envanter_gunluk"],
            sku_df=dunya["sku"],
            tedarikci_df=dunya["tedarikci"],
            siniflandirma=siniflandirma,
        )
        rop, _ = rop_ve_emniyet_stogu(ozellik)
        if ozellik.kullanilabilir_stok + ozellik.yoldaki_stok < rop:
            return sku_id
    return sku_ids[0]


def _guven_skoru_hesapla(ozellik: StockFeatures) -> float:
    """Veri yeterliliği + kural mutabakatı + tahmin belirsizliği ağırlıklı toplamı."""
    veri_yeterliligi_puani = min(1.0, ozellik.veri_gun_sayisi / UZUN_PENCERE_GUN)
    kural_mutabakati_puani = 1.0 - min(1.0, ozellik.talep_varyasyon_katsayisi)
    guven = (
        GUVEN_AGIRLIK_VERI_YETERLILIGI * veri_yeterliligi_puani
        + GUVEN_AGIRLIK_KURAL_MUTABAKATI * kural_mutabakati_puani
        + GUVEN_AGIRLIK_TAHMIN_BELIRSIZLIGI * VARSAYILAN_TAHMIN_GUVEN_PUANI
    )
    return float(min(1.0, max(0.0, guven)))


def stok_karari_uret(sku_id: str | None = None, seed: int = VARSAYILAN_SEED) -> DecisionCandidate:
    """Bir SKU için gerçek stok kararı üretir — `decide_stub()`'ın yerini alır.

    `sku_id=None` ise (API'nin bugünkü stub-uyumlu çağrı şekli) sipariş
    kararını tetikleyen ilk SKU otomatik seçilir.
    """
    dunya = _demo_dunyasini_yukle(seed)
    siniflandirma = _siniflandirmayi_hesapla(dunya)

    if sku_id is None:
        sku_id = _varsayilan_demo_sku_id(dunya, siniflandirma)

    ozellik = sku_ozelliklerini_hesapla(
        sku_id=sku_id,
        olcum_tarihi=dunya["olcum_tarihi"],
        talep=dunya["talep"],
        envanter_gunluk=dunya["envanter_gunluk"],
        sku_df=dunya["sku"],
        tedarikci_df=dunya["tedarikci"],
        siniflandirma=siniflandirma,
    )

    return ozellikten_karar_uret(ozellik)


def ozellikten_karar_uret(ozellik: StockFeatures) -> DecisionCandidate:
    """`stok_karari_uret`'in saf karar mantığı — herhangi bir `StockFeatures`
    için çalışır. `training/build_dataset.py` (A3.1) bunu farklı (sku_id,
    tarih) kombinasyonları için tekrar tekrar çağırarak etiketli eğitim
    verisi üretir; "demo dünyası" önbelleğine bağımlı değildir.

    ## Karar önceliği — A2 incelemesi (2026-08-10)

    Sıra `tasfiye → sipariş → aksiyon yok` ve **dışlayıcı olması doğru**.
    Finansta aynı kalıp kusurluydu (`BILINEN-EKSIKLER.md` §9) ve stok da
    aynı gözle incelendi; iki alan gerçekten farklı çıktı:

    · Finansta üç kol **ortogonaldi**: karşılık muhasebe, limit gelecek
      risk, takip bugünkü nakit. Üçü aynı anda doğru olabilirdi.
    · Stokta tasfiye ile sipariş **aynı soruya zıt cevap veriyor**: "bu mala
      para bağlamalı mıyım?" İkisi birden uygulanamaz.

    Eşiğin yönü de doğru: `rules._olu_stok_esigi` `max(mutlak, göreceli)`
    kullanıyor, yani eşik yalnızca yukarı çıkabiliyor. Finanstaki kusur
    kalıbın kendisinde değil, kopyalanırken yönün ters çevrilmesindeydi
    (`min` yazılmıştı).

    ⚠️ **Ama dışlamanın sağlamlığı `son_hareket_gun_once`'ın doğruluğuna
    bağlı.** Gerçek veride o alan fiili satıştan türüyor ve stoksuz kalmış
    bir ürün "ölü" görünüyor — bkz. `rules.olu_stok_degerlendir` ve
    `BILINEN-EKSIKLER.md` §11.

    ⚠️ **A3 için not:** `stok.tedarikci_degisim` kuralı yazıldığında bu
    `elif` zincirine EKLENMEMELİ. Tedarikçi değişimi bir **karşı taraf**
    kararı; ölü stok tespiti onu geçersiz kılmaz, tıpkı finansta karşılık
    ayırmanın tahsilat takibini geçersiz kılmaması gibi. Ortogonal kol,
    ortogonal üretilir.
    """
    kurallar: list[FiredRule] = []
    rop, emniyet_stogu = rop_ve_emniyet_stogu(ozellik)
    net_pozisyon = ozellik.kullanilabilir_stok + ozellik.yoldaki_stok

    kurallar.append(
        FiredRule(
            kod="EMNIYET_STOGU_HESAPLANDI",
            aciklama=(
                f"Hedef %{ozellik.hedef_servis_seviyesi * 100:.0f} servis seviyesi için "
                f"emniyet stoğu hesaplandı."
            ),
            degerler={
                "emniyet_stogu": round(emniyet_stogu, 2),
                "hedef_servis_seviyesi": ozellik.hedef_servis_seviyesi,
            },
        )
    )
    kurallar.append(
        FiredRule(
            kod="ROP_HESAPLANDI",
            aciklama="Yeniden sipariş noktası hesaplandı.",
            degerler={"rop": round(rop, 2), "net_pozisyon": float(net_pozisyon)},
        )
    )

    olu_degerlendirme = olu_stok_degerlendir(ozellik)

    if olu_degerlendirme["olu_stok_mu"]:
        tip = KararTipi.STOK_TASFIYE
        iskonto = olu_degerlendirme["onerilen_iskonto_orani"]
        bagli_sermaye = olu_degerlendirme["bagli_sermaye_tl"]
        aksiyon: dict[str, float | int | str | None] = {
            "onerilen_iskonto_orani": iskonto,
            "eldeki_stok": ozellik.eldeki_stok,
        }
        tahmini_tutar_tl = bagli_sermaye * iskonto
        geri_alinabilir = False
        kurallar.append(
            FiredRule(
                kod="OLU_STOK_TESPIT_EDILDI",
                aciklama=(
                    f"{olu_degerlendirme['son_hareket_gun_once']} gündür hareketsiz, "
                    f"%{iskonto * 100:.0f} iskontoyla tasfiye önerilir."
                ),
                degerler={
                    "son_hareket_gun_once": float(olu_degerlendirme["son_hareket_gun_once"]),
                    "bagli_sermaye_tl": round(bagli_sermaye, 2),
                    "onerilen_iskonto_orani": iskonto,
                },
            )
        )
    elif net_pozisyon < rop + ozellik.mrp_ihtiyaci:
        # ⚠️ MRP ihtiyacı ROP'un ÜSTÜNE ekleniyor, stoktan düşülmüyor.
        #
        # İkisi aynı sonucu vermez: düşmek `kullanilabilir_stok`'u bozar ve o
        # sayı gerekçede geçiyor — insan "elde 300 var" derken sistem 180
        # yazardı. Eşiği yükseltmek ise soruyu doğru soruyor: "satış talebi
        # + üretim talebi toplamını karşılayacak stoğum var mı?"
        tip = KararTipi.STOK_SIPARIS
        siparis_miktari = siparis_miktari_hesapla(ozellik)
        aksiyon = {"siparis_miktari": siparis_miktari, "tedarikci_id": ozellik.tedarikci_id}
        tahmini_tutar_tl = siparis_miktari * ozellik.birim_maliyet_tl
        geri_alinabilir = True
        if ozellik.mrp_ihtiyaci > 0:
            kurallar.append(
                FiredRule(
                    kod="URETIM_TALEBI_EKLENDI",
                    aciklama=(
                        "Açılması önerilen üretim emirleri bu malzemeden ayrıca "
                        "ihtiyaç doğuruyor; sipariş eşiği o kadar yükseltildi."
                    ),
                    degerler={
                        "mrp_ihtiyaci": round(ozellik.mrp_ihtiyaci, 2),
                        "rop": round(rop, 2),
                    },
                )
            )
        kurallar.append(
            FiredRule(
                kod="ROP_ALTINDA",
                aciklama="Kullanılabilir stok + yoldaki stok yeniden sipariş noktasının altında.",
                degerler={"rop": round(rop, 2), "net_pozisyon": float(net_pozisyon)},
            )
        )
        kurallar.append(
            FiredRule(
                kod="SIPARIS_MIKTARI_HESAPLANDI",
                aciklama="EOQ hesaplanıp MOQ/paket adedine yuvarlandı.",
                degerler={
                    "siparis_miktari": float(siparis_miktari),
                    "moq": float(ozellik.moq),
                    "paket_adedi": float(ozellik.paket_adedi),
                },
            )
        )
        kurallar.append(
            FiredRule(
                kod="TEDARIKCI_DEGERLENDIRILDI",
                aciklama=(
                    f"{ozellik.tedarikci_adi} "
                    f"({'onaylı' if ozellik.tedarikci_onayli else 'onaysız'}) seçildi."
                ),
                degerler={"tedarikci_skoru": round(ozellik.tedarikci_skoru, 2)},
            )
        )
    else:
        tip = KararTipi.STOK_AKSIYON_YOK
        aksiyon = {}
        tahmini_tutar_tl = 0.0
        geri_alinabilir = True
        kurallar.append(
            FiredRule(
                kod="ROP_USTUNDE",
                aciklama="Net pozisyon yeniden sipariş noktasının üstünde, aksiyon gerekmiyor.",
                degerler={"rop": round(rop, 2), "net_pozisyon": float(net_pozisyon)},
            )
        )

    return DecisionCandidate(
        alan=Alan.STOK,
        tip=tip,
        aksiyon=aksiyon,
        tahmini_tutar_tl=round(tahmini_tutar_tl, 2),
        geri_alinabilir=geri_alinabilir,
        guven=_guven_skoru_hesapla(ozellik),
        tetiklenen_kurallar=kurallar,
        ozellikler=ozellik,
        model_surumleri={"rules": KURAL_SURUMU, "demand_ml": "-"},
    )


def ozellikten_kararlar_uret(ozellik: StockFeatures) -> list[DecisionCandidate]:
    """`StockFeatures` → koşulu sağlanan **tüm** kararlar.

    `app/domain/finance/decide.py::ozellikten_kararlar_uret` ile aynı
    sözleşme, ama içindeki mantık bilinçli olarak farklı:

    · **Tasfiye ve sipariş dışlayıcı kalıyor.** İkisi aynı soruya zıt cevap
      veriyor ("bu mala para bağlamalı mıyım?"), aynı anda uygulanamaz.
      A2 incelemesi bunu doğruladı (`BILINEN-EKSIKLER.md` §11).
    · **Tedarikçi değişimi ortogonal.** "Bu malı kimden almalıyım?" ayrı bir
      soru; ölü stok tespiti onu geçersiz kılmaz. Finanstaki karşılık/takip
      ayrımıyla aynı gerekçe (§9).

    Yani liste en fazla iki karar taşır: biri stok aksiyonu, biri tedarikçi.
    """
    kararlar: list[DecisionCandidate] = []

    birincil = ozellikten_karar_uret(ozellik)
    degisim = _tedarikci_degisim_karari(ozellik)

    # "Aksiyon yok" + tedarikçi kararı birlikte anlamsız: yapılacak bir şey
    # VAR. Aksi hâlde kuyrukta hem "bir şey yapma" hem "tedarikçiyi gözden
    # geçir" satırı yan yana görünürdü.
    if not (birincil.tip is KararTipi.STOK_AKSIYON_YOK and degisim is not None):
        kararlar.append(birincil)
    if degisim is not None:
        kararlar.append(degisim)

    return kararlar


def _tedarikci_degisim_karari(ozellik: StockFeatures) -> DecisionCandidate | None:
    """Tedarikçi gözden geçirme kararı — koşul sağlanmıyorsa `None`.

    ⚠️ Faz 8'e kadar `stok.tedarikci_degisim` tipi tanımlıydı ama hiç
    üretilmiyordu (`BILINEN-EKSIKLER.md` §5). Ölü bir karar tipi, politika
    tablosunda eşiği olan ama asla tetiklenmeyen bir satır demek — sistemin
    neyi yapabildiğine dair yanlış bir izlenim veriyordu.
    """
    d = tedarikci_degisim_degerlendir(ozellik)
    if not d["gozden_gecirilmeli"]:
        return None

    return DecisionCandidate(
        alan=Alan.STOK,
        tip=KararTipi.STOK_TEDARIKCI_DEGISIM,
        aksiyon={
            "tedarikci_id": ozellik.tedarikci_id,
            "tedarikci_skoru": ozellik.tedarikci_skoru,
        },
        tahmini_tutar_tl=round(d["maruz_kalinan_deger_tl"], 2),
        # Tedarikçi değişimi geri alınabilir: sözleşme yenilenebilir,
        # eski tedarikçiye dönülebilir. Tasfiyeden farkı bu.
        geri_alinabilir=True,
        guven=_guven_skoru_hesapla(ozellik),
        tetiklenen_kurallar=[
            FiredRule(
                kod="TEDARIKCI_SKORU_DUSUK",
                aciklama=(
                    f"Tedarikçi skoru {ozellik.tedarikci_skoru:.0f}; zamanında teslim "
                    f"oranı %{ozellik.tedarikci_zamaninda_teslim_orani * 100:.0f}. "
                    f"Alternatif tedarikçi değerlendirilmeli."
                ),
                degerler={
                    "tedarikci_skoru": ozellik.tedarikci_skoru,
                    "tedarikci_degisim_esigi": d["tedarikci_degisim_esigi"],
                    "tedarikci_zamaninda_teslim_orani": ozellik.tedarikci_zamaninda_teslim_orani,
                    "maruz_kalinan_deger_tl": d["maruz_kalinan_deger_tl"],
                },
            )
        ],
        ozellikler=ozellik,
        model_surumleri={"rules": KURAL_SURUMU},
    )


def _ornek_ozellikler() -> StockFeatures:
    """Elle yazılmış gerçekçi bir SKU anlık görüntüsü.

    Sayılar bilinçli olarak tutarlı: ROP = 42 × 12 + 111 ≈ 615 çıkar,
    eldeki 310 < 615 olduğu için sipariş kararı mantıklı görünür.
    """
    return StockFeatures(
        sku_id="SKU-01432",
        sku_adi="Kırmızı Tuğla 19x9x5",
        kategori="Kaba Yapı Malzemesi",
        eldeki_stok=310,
        rezerve_stok=40,
        yoldaki_stok=0,
        ort_gunluk_talep=42.0,
        talep_std=11.5,
        veri_gun_sayisi=180,
        tedarik_suresi_gun=12.0,
        tedarik_suresi_std=2.5,
        abc_sinifi=ABCSinifi.A,
        xyz_sinifi=XYZSinifi.Y,
        hedef_servis_seviyesi=0.95,
        son_hareket_gun_once=1,
        raf_omru_kalan_gun=None,
        birim_maliyet_tl=4.75,
        satis_fiyati_tl=6.90,
        tedarikci_id="T-014",
        tedarikci_adi="Yılmaz Yapı",
        tedarikci_skoru=87.0,
        tedarikci_zamaninda_teslim_orani=0.94,
        tedarikci_onayli=True,
        moq=500,
        paket_adedi=100,
        olcum_tarihi=dt.date(2026, 7, 30),
    )


def decide_stub() -> DecisionCandidate:
    """Sabit, elle yazılmış bir karar adayı döndürür (Faz 0.5).

    Artık kullanılan yol değil (`app/api/decisions.py` `stok_karari_uret()`'i
    çağırıyor) — testlerin ve dokümantasyonun stub davranışına referans
    verebilmesi için korunuyor.
    """
    ozellikler = _ornek_ozellikler()

    kurallar = [
        FiredRule(
            kod="ROP_ALTINDA",
            aciklama="Kullanılabilir stok yeniden sipariş noktasının altına düştü.",
            degerler={
                "rop": 615.0,
                "kullanilabilir_stok": float(ozellikler.kullanilabilir_stok),
                "emniyet_stogu": 111.0,
            },
        ),
        FiredRule(
            kod="TEDARIKCI_SECILDI",
            aciklama="En yüksek skorlu onaylı tedarikçi seçildi.",
            degerler={"tedarikci_skoru": 87.0},
        ),
    ]

    return DecisionCandidate(
        alan=Alan.STOK,
        tip=KararTipi.STOK_SIPARIS,
        aksiyon={"siparis_miktari": 1200, "tedarikci_id": "T-014"},
        tahmini_tutar_tl=1200 * ozellikler.birim_maliyet_tl,
        geri_alinabilir=True,
        guven=0.88,
        tetiklenen_kurallar=kurallar,
        ozellikler=ozellikler,
        model_surumleri={"rules": "0.1-stub", "demand_ml": "-"},
    )
