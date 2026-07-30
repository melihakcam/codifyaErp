"""Stok kararı üretimi — kural motoru + ML'in birleştiği yer.

Sahip: Kişi A · gerçek uygulaması Faz 2 A2.6

ŞU AN: yalnızca `decide_stub()` var. Amacı, Kişi B'nin servis katmanını
Kişi A'nın kural motorunu beklemeden yazabilmesi. Faz 2 A2.6'da
`stok_karari_uret()` gerçek haliyle yazılacak ve API'de tek satır
değişecek — sözleşme doğru tasarlandıysa B'nin kodunda başka hiçbir şey
değişmeyecek. Bu, Faz 0.4'ün sınavıdır.
"""

from __future__ import annotations

from datetime import date

from app.contracts import (
    ABCSinifi,
    Alan,
    DecisionCandidate,
    FiredRule,
    KararTipi,
    StockFeatures,
    XYZSinifi,
)

KURAL_SURUMU = "0.1-stub"


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
        olcum_tarihi=date(2026, 7, 30),
    )


def decide_stub() -> DecisionCandidate:
    """Sabit, elle yazılmış bir karar adayı döndürür (Faz 0.5).

    Faz 2 A2.6'da silinecek. O zamana kadar bütün servis katmanı, gecelik iş
    ve guard testleri bunun üzerinden geliştirilir.
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
        model_surumleri={"rules": KURAL_SURUMU, "demand_ml": "-"},
    )
