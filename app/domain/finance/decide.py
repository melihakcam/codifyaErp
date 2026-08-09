"""Finans & Tahsilat karar üretimi — Faz 6.

`app/domain/stock/decide.py`'nin karşılığı ve aynı iskelet: özellikleri al,
kuralları koştur, tek bir `DecisionCandidate` üret.

## Karar önceliği

Stokta sıra `tasfiye → sipariş → aksiyon yok` idi: ölü stok tespiti sipariş
önerisini ezer, çünkü hareketsiz bir ürüne sipariş vermek anlamsızdır.

Finansta aynı mantıkla `karşılık → limit → takip → aksiyon yok`:

1. **Karşılık** — alacak tahsil edilemeyecek kadar eskiyse, o müşteriyi
   aramak değil zararı yazmak gerekir.
2. **Limit** — müşteri riskliyse, önce yeni satışı durdur; eski alacağı
   kovalamak ikinci iş.
3. **Takip** — normal gecikme eşiği aşılmışsa ara.

⚠️ Sıra keyfi değil: her adım bir öncekinin anlamsız kıldığı durumu eliyor.
Ters sırada işletilseydi batık bir müşteriye "hadi ödeyin" mesajı giderdi.
"""

from __future__ import annotations

from app.contracts import Alan, DecisionCandidate, FinansOzellikleri, FiredRule, KararTipi
from app.domain.finance.rules import (
    esik_ve_emniyet_gunu,
    karsilik_degerlendir,
    limit_degerlendir,
)

# Güven skoru, veri geçmişinin uzunluğuyla artar. 365 günlük geçmiş tam
# güven; altındaki oranla ölçeklenir. Stoktaki `_guven_skoru_hesapla` ile
# aynı fikir — az veriyle verilen karar daha az güvenilirdir.
TAM_GUVEN_ICIN_GUN = 365
TABAN_GUVEN = 0.55


def _guven_skoru_hesapla(ozellik: FinansOzellikleri) -> float:
    """Veri geçmişi + ödeme davranışının öngörülebilirliğinden güven skoru.

    İki bileşen: **ne kadar veri var** ve **davranış ne kadar tutarlı**.
    Rastgele ödeyen bir müşteri hakkında 3 yıllık veri de olsa, bir sonraki
    ödemesini tahmin edemeyiz — güven düşük olmalı.
    """
    veri_payi = min(1.0, ozellik.veri_gun_sayisi / TAM_GUVEN_ICIN_GUN)
    tutarlilik = max(0.0, 1.0 - min(1.0, ozellik.gecikme_varyasyon_katsayisi))
    ham = TABAN_GUVEN + (1.0 - TABAN_GUVEN) * (0.5 * veri_payi + 0.5 * tutarlilik)
    return round(min(0.99, ham), 3)


def ozellikten_karar_uret(ozellik: FinansOzellikleri) -> DecisionCandidate:
    """`FinansOzellikleri` → `DecisionCandidate`. Saf fonksiyon, yan etkisiz.

    `app/domain/stock/decide.py::ozellikten_karar_uret` ile aynı imza ve
    aynı sözleşme — eğitim verisi üreticisi ikisini de aynı şekilde
    çağırabilsin diye.
    """
    kurallar: list[FiredRule] = []
    esik, emniyet_gunu = esik_ve_emniyet_gunu(ozellik)

    kurallar.append(
        FiredRule(
            kod="TAKIP_ESIGI_HESAPLANDI",
            aciklama=(
                f"Hedef %{ozellik.hedef_tahsilat_orani * 100:.0f} tahsilat oranı için "
                f"takip eşiği hesaplandı."
            ),
            degerler={
                "takip_esigi_gun": round(esik, 2),
                "emniyet_gunu": round(emniyet_gunu, 2),
                "hedef_tahsilat_orani": ozellik.hedef_tahsilat_orani,
            },
        )
    )

    karsilik = karsilik_degerlendir(ozellik)
    limit = limit_degerlendir(ozellik)

    if karsilik["karsilik_gerekli"]:
        tip = KararTipi.FINANS_KARSILIK_AYIR
        oran = karsilik["onerilen_karsilik_orani"]
        aksiyon: dict[str, float | int | str | None] = {
            "onerilen_karsilik_orani": oran,
            "vadesi_gecen_tl": round(ozellik.vadesi_gecen_tl, 2),
        }
        tahmini_tutar_tl = karsilik["karsilik_tutari_tl"]
        # ⚠️ Karşılık ayırmak muhasebe kaydıdır; geri almak düzeltme fişi
        # gerektirir. Stoktaki tasfiye gibi geri alınamaz sayılıyor.
        geri_alinabilir = False
        kurallar.append(
            FiredRule(
                kod="KARSILIK_GEREKLI",
                aciklama=(
                    f"En eski alacak {ozellik.en_eski_gecikme_gun} gündür gecikmede; "
                    f"%{oran * 100:.0f} karşılık önerilir."
                ),
                degerler={
                    "en_eski_gecikme_gun": float(ozellik.en_eski_gecikme_gun),
                    "karsilik_esigi_gun": round(karsilik["karsilik_esigi_gun"], 2),
                    "onerilen_karsilik_orani": oran,
                    "karsilik_tutari_tl": round(karsilik["karsilik_tutari_tl"], 2),
                },
            )
        )

    elif limit["limit_dusurulmeli"]:
        tip = KararTipi.FINANS_KREDI_LIMITI_DUSUR
        aksiyon = {
            "onerilen_kredi_limiti_tl": limit["onerilen_kredi_limiti_tl"],
            "mevcut_kredi_limiti_tl": round(ozellik.kredi_limiti_tl, 2),
        }
        # Etki, kısılan limit kadar: bağlanmayan risk.
        tahmini_tutar_tl = max(
            0.0, ozellik.kredi_limiti_tl - limit["onerilen_kredi_limiti_tl"]
        )
        geri_alinabilir = True
        kurallar.append(
            FiredRule(
                kod="MUSTERI_RISKI_YUKSEK",
                aciklama=(
                    f"Risk skoru {limit['musteri_risk_skoru']:.0f}; kredi limitinin "
                    f"düşürülmesi önerilir."
                ),
                degerler={
                    "musteri_risk_skoru": limit["musteri_risk_skoru"],
                    "tahsilat_orani": ozellik.tahsilat_orani,
                    "onerilen_kredi_limiti_tl": limit["onerilen_kredi_limiti_tl"],
                },
            )
        )

    elif ozellik.en_eski_gecikme_gun > esik and ozellik.vadesi_gecen_tl > 0:
        tip = KararTipi.FINANS_TAHSILAT_TAKIBI
        aksiyon = {
            "takip_edilecek_tutar_tl": round(ozellik.vadesi_gecen_tl, 2),
            "gecikme_gun": ozellik.en_eski_gecikme_gun,
        }
        tahmini_tutar_tl = ozellik.vadesi_gecen_tl
        geri_alinabilir = True
        kurallar.append(
            FiredRule(
                kod="TAKIP_ESIGI_ASILDI",
                aciklama=(
                    "Gecikme, müşterinin kendi ödeme davranışından beklenen eşiği aştı."
                ),
                degerler={
                    "takip_esigi_gun": round(esik, 2),
                    "en_eski_gecikme_gun": float(ozellik.en_eski_gecikme_gun),
                    "vadesi_gecen_tl": round(ozellik.vadesi_gecen_tl, 2),
                },
            )
        )

    else:
        tip = KararTipi.FINANS_AKSIYON_YOK
        aksiyon = {}
        tahmini_tutar_tl = 0.0
        geri_alinabilir = True
        kurallar.append(
            FiredRule(
                kod="ESIK_ALTINDA",
                aciklama="Gecikme, bu müşteri için beklenen aralıkta.",
                degerler={
                    "takip_esigi_gun": round(esik, 2),
                    "en_eski_gecikme_gun": float(ozellik.en_eski_gecikme_gun),
                },
            )
        )

    return DecisionCandidate(
        alan=Alan.FINANS,
        tip=tip,
        aksiyon=aksiyon,
        tahmini_tutar_tl=round(tahmini_tutar_tl, 2),
        geri_alinabilir=geri_alinabilir,
        guven=_guven_skoru_hesapla(ozellik),
        tetiklenen_kurallar=kurallar,
        ozellikler=ozellik,
        model_surumleri={"rules": "0.1-finans"},
    )


__all__ = ["TABAN_GUVEN", "TAM_GUVEN_ICIN_GUN", "ozellikten_karar_uret"]
