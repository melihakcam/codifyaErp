"""Finans & Tahsilat karar üretimi — Faz 6.

`app/domain/stock/decide.py`'nin karşılığı ve aynı iskelet: özellikleri al,
kuralları koştur, tek bir `DecisionCandidate` üret.

## ⚠️ Karar önceliği kaldırıldı — üç kol ORTOGONAL

Bu modül önce stok kalıbını birebir taşımıştı: müşteri başına **tek** karar,
öncelik `karşılık → limit → takip → aksiyon yok`. Gerekçesi şuydu: *"her
adım bir öncekinin anlamsız kıldığı durumu eliyor; ters sırada işletilseydi
batık bir müşteriye 'hadi ödeyin' mesajı giderdi."*

**Faz 7 para metriği bunun yanlış olduğunu ölçtü.**
`app/domain/finance/para_metrigi.py` ablasyonunda, kural motorunun batak
zararı hiçbir şey yapmayan taban politikayla **ondalığına kadar aynı**
çıktı (197.944,685531). 75 tahsilat eylemi yapılmış, kurtarılan alacak
sıfırdı.

Sebebi: batık müşteri her zaman karşılık koluna gidiyor ve bir daha
takibe **hiç** girmiyordu. Yani parasını gerçekten alamayacağın müşteri,
tahsilat kolunun hiç dokunmadığı tek gruptu.

Kusur mantık hatası değil, modelleme hatasıydı. Üç kol birbirini dışlar
varsayılmıştı; oysa ayrı sorulara cevap veriyorlar:

| kol | sorusu | zaman ekseni |
|---|---|---|
| karşılık | bu alacağı defterde nasıl gösteriyorum? | geçmiş, muhasebe |
| limit | bu müşteriye daha ne kadar mal veririm? | gelecek, risk |
| takip | bu parayı nasıl tahsil ederim? | şimdi, nakit |

Karşılık ayırmak bir muhasebe işlemidir, tahsilat çabasını durdurmaz.
Doğru davranış: batık müşteriye hem karşılık ayır, hem aramaya devam et.

Bu yüzden `ozellikten_kararlar_uret` bir **liste** döndürüyor: hangi kolun
koşulu sağlanıyorsa o karar üretilir, biri diğerini bastırmaz.

⚠️ **Stok tarafı bilinçli olarak tekil kaldı.** Oradaki `tasfiye → sipariş`
dışlaması gerçekten doğru: hareketsiz bir ürüne sipariş vermek anlamsız,
iki karar aynı anda uygulanamaz. İki alanın burada ayrışması, kalıbın
körlemesine taşınmadığının işareti — finansın kendi gerçeği farklı çıktı.
"""

from __future__ import annotations

from app.contracts import Alan, DecisionCandidate, FinansOzellikleri, FiredRule, KararTipi
from app.domain.finance.features import musteri_ozelliklerini_hesapla
from app.domain.finance.rules import (
    esik_ve_emniyet_gunu,
    karsilik_degerlendir,
    limit_degerlendir,
    takip_gerekcesi,
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


def _taban_kural(ozellik: FinansOzellikleri, esik: float, emniyet_gunu: float) -> FiredRule:
    """Her karara eşlik eden bağlam kuralı.

    Üretilen her karara konuyor, yalnızca takibe değil: `izinli_sayilar()`
    bu kuralın değerlerini de kümeye katıyor ve gerekçe metni "bu müşteri
    için beklenen eşik şu" cümlesini her karar tipinde kurabilmeli.
    """
    return FiredRule(
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


def _aday(
    ozellik: FinansOzellikleri,
    tip: KararTipi,
    aksiyon: dict[str, float | int | str | None],
    tahmini_tutar_tl: float,
    geri_alinabilir: bool,
    kurallar: list[FiredRule],
) -> DecisionCandidate:
    """Ortak `DecisionCandidate` kurulumu — üç kol da buradan geçiyor."""
    return DecisionCandidate(
        alan=Alan.FINANS,
        tip=tip,
        aksiyon=aksiyon,
        tahmini_tutar_tl=round(tahmini_tutar_tl, 2),
        geri_alinabilir=geri_alinabilir,
        guven=_guven_skoru_hesapla(ozellik),
        tetiklenen_kurallar=kurallar,
        ozellikler=ozellik,
        model_surumleri={"rules": "0.2-finans"},
    )


def ozellikten_kararlar_uret(ozellik: FinansOzellikleri) -> list[DecisionCandidate]:
    """`FinansOzellikleri` → koşulu sağlanan **tüm** kararlar. Saf fonksiyon.

    Liste sırası önem sırasıdır (karşılık → limit → takip) ama artık bu bir
    **eleme** değil yalnızca sunum sırası: üçü de aynı anda üretilebilir.
    Gerekçesi modül docstring'inde — ölçümle bulunmuş bir kusurun düzeltmesi.

    Hiçbir kolun koşulu sağlanmıyorsa tek elemanlı `aksiyon_yok` listesi
    döner. Boş liste DÖNMÜYOR: "bu müşteriye baktım, yapılacak bir şey yok"
    ile "bu müşteriye hiç bakmadım" farklı şeyler ve shadow raporu ikisini
    ayırabilmeli.
    """
    esik, emniyet_gunu = esik_ve_emniyet_gunu(ozellik)
    taban = _taban_kural(ozellik, esik, emniyet_gunu)

    karsilik = karsilik_degerlendir(ozellik)
    limit = limit_degerlendir(ozellik)
    kararlar: list[DecisionCandidate] = []

    if karsilik["karsilik_gerekli"]:
        oran = karsilik["onerilen_karsilik_orani"]
        kararlar.append(
            _aday(
                ozellik,
                KararTipi.FINANS_KARSILIK_AYIR,
                {
                    "onerilen_karsilik_orani": oran,
                    "vadesi_gecen_tl": round(ozellik.vadesi_gecen_tl, 2),
                },
                karsilik["karsilik_tutari_tl"],
                # ⚠️ Karşılık ayırmak muhasebe kaydıdır; geri almak düzeltme
                # fişi gerektirir. Stoktaki tasfiye gibi geri alınamaz.
                geri_alinabilir=False,
                kurallar=[
                    taban,
                    FiredRule(
                        kod="KARSILIK_GEREKLI",
                        aciklama=(
                            f"En eski alacak {ozellik.en_eski_gecikme_gun} gündür "
                            f"gecikmede; %{oran * 100:.0f} karşılık önerilir."
                        ),
                        degerler={
                            "en_eski_gecikme_gun": float(ozellik.en_eski_gecikme_gun),
                            "karsilik_esigi_gun": round(karsilik["karsilik_esigi_gun"], 2),
                            "onerilen_karsilik_orani": oran,
                            "karsilik_tutari_tl": round(karsilik["karsilik_tutari_tl"], 2),
                        },
                    ),
                ],
            )
        )

    if limit["limit_dusurulmeli"]:
        kararlar.append(
            _aday(
                ozellik,
                KararTipi.FINANS_KREDI_LIMITI_DUSUR,
                {
                    "onerilen_kredi_limiti_tl": limit["onerilen_kredi_limiti_tl"],
                    "mevcut_kredi_limiti_tl": round(ozellik.kredi_limiti_tl, 2),
                },
                # Etki, kısılan limit kadar: bağlanmayan risk.
                max(0.0, ozellik.kredi_limiti_tl - limit["onerilen_kredi_limiti_tl"]),
                geri_alinabilir=True,
                kurallar=[
                    taban,
                    FiredRule(
                        kod="MUSTERI_RISKI_YUKSEK",
                        aciklama=(
                            f"Risk skoru {limit['musteri_risk_skoru']:.0f}; kredi "
                            f"limitinin düşürülmesi önerilir."
                        ),
                        degerler={
                            "musteri_risk_skoru": limit["musteri_risk_skoru"],
                            "tahsilat_orani": ozellik.tahsilat_orani,
                            "onerilen_kredi_limiti_tl": limit["onerilen_kredi_limiti_tl"],
                        },
                    ),
                ],
            )
        )

    takip = takip_gerekcesi(ozellik, esik)
    if takip["gerekli"]:
        # ⭐ Bu koşul karşılık/limit kollarından BAĞIMSIZ. Faz 7 öncesi
        # `elif` idi ve batık müşteri hiçbir zaman buraya ulaşmıyordu.
        #
        # ⭐ Artık iki kolla tetikleniyor: anomali (istatistik) ve maddiyet
        # (ekonomi). Öncesinde yalnızca anomali vardı ve sistem, sıradan
        # görünen büyük alacakları atlıyordu — A1'de ölçüldü (§12).
        kararlar.append(
            _aday(
                ozellik,
                KararTipi.FINANS_TAHSILAT_TAKIBI,
                {
                    "takip_edilecek_tutar_tl": round(ozellik.vadesi_gecen_tl, 2),
                    "gecikme_gun": ozellik.en_eski_gecikme_gun,
                },
                ozellik.vadesi_gecen_tl,
                geri_alinabilir=True,
                kurallar=[
                    taban,
                    FiredRule(
                        kod="TAKIP_ESIGI_ASILDI" if takip["anomali"] else "TUTAR_TAKIBE_DEGER",
                        aciklama=(
                            "Gecikme, müşterinin kendi ödeme davranışından beklenen eşiği aştı."
                            if takip["anomali"]
                            else (
                                f"Gecikme bu müşteri için olağandışı değil, ama "
                                f"{ozellik.vadesi_gecen_tl:,.0f} TL alacak takip "
                                f"maliyetini fazlasıyla karşılıyor."
                            )
                        ),
                        degerler={
                            "takip_esigi_gun": round(esik, 2),
                            "en_eski_gecikme_gun": float(ozellik.en_eski_gecikme_gun),
                            "vadesi_gecen_tl": round(ozellik.vadesi_gecen_tl, 2),
                            "maddi_takip_esigi_tl": takip["maddi_takip_esigi_tl"],
                        },
                    ),
                ],
            )
        )

    if not kararlar:
        kararlar.append(
            _aday(
                ozellik,
                KararTipi.FINANS_AKSIYON_YOK,
                {},
                0.0,
                geri_alinabilir=True,
                kurallar=[
                    taban,
                    FiredRule(
                        kod="ESIK_ALTINDA",
                        aciklama="Gecikme, bu müşteri için beklenen aralıkta.",
                        degerler={
                            "takip_esigi_gun": round(esik, 2),
                            "en_eski_gecikme_gun": float(ozellik.en_eski_gecikme_gun),
                        },
                    ),
                ],
            )
        )

    return kararlar


def ozellikten_karar_uret(ozellik: FinansOzellikleri) -> DecisionCandidate:
    """Tek karar isteyen çağıranlar için **birincil** karar.

    ⚠️ Bu fonksiyon artık tam resmi vermiyor: bir müşteri aynı anda hem
    karşılık hem takip gerektirebilir ve burada yalnızca birincisi döner.
    Karar üreten her yol (`gecelik_tarama`, para metriği)
    `ozellikten_kararlar_uret` kullanmalı.

    Yaşamaya devam etmesinin tek sebebi tekil cevap zorunluluğu olan
    `GET /v1/decisions/finance/...`: HTTP ucu tek bir `KararSonucu`
    döndürüyor ve sözleşmeyi değiştirmek ERP tarafını kırar.
    """
    return ozellikten_kararlar_uret(ozellik)[0]


# ---------------------------------------------------------------------------
# Demo dünyası — API ve gecelik iş için giriş noktası
# ---------------------------------------------------------------------------
#
# `app/domain/stock/decide.py::stok_karari_uret`'in karşılığı. Simülasyonu
# bir kez koşturup process-içi önbellekte tutar; gerçek veriye geçince
# `app/adapters/csv_erp.py`'nin finans karşılığı buranın yerini alacak.

VARSAYILAN_SEED = 42
VARSAYILAN_YIL_SAYISI = 2
TAHSILAT_SEED = 101

_ONBELLEK: dict[int, list[FinansOzellikleri]] = {}


def _demo_ozellikleri(seed: int = VARSAYILAN_SEED) -> list[FinansOzellikleri]:
    """Simülasyon + tahsilat + özellik hattını bir kez koşturur, önbelleğe alır.

    ⚠️ Patolojiler AÇIK. Kapalı bir dünyada her müşteri tam vadesinde öder,
    hiçbir karar üretilmez ve endpoint boş döner — demo hiçbir şey göstermez.
    """
    if seed not in _ONBELLEK:
        import pandas as pd

        from simulator.company import yapi_malzemesi_toptancisi
        from simulator.run import simulasyon_calistir
        from simulator.tahsilat import TahsilatPatolojisi, tahsilat_uret

        dunya = simulasyon_calistir(
            profile=yapi_malzemesi_toptancisi(), seed=seed, yil_sayisi=VARSAYILAN_YIL_SAYISI
        )
        tahsilat = tahsilat_uret(
            dunya["faturalar"],
            dunya["musteri"],
            seed=TAHSILAT_SEED,
            patoloji=TahsilatPatolojisi(
                kronik_gecikme_aktif=True,
                duzensiz_odeme_aktif=True,
                sezonluk_tikanma_aktif=True,
                batak_aktif=True,
            ),
        )
        olcum = pd.to_datetime(tahsilat.faturalar["tarih"]).max().date()
        _ONBELLEK[seed] = musteri_ozelliklerini_hesapla(tahsilat.faturalar, dunya["musteri"], olcum)
    return _ONBELLEK[seed]


def finans_karari_uret(
    musteri_id: str | None = None, seed: int = VARSAYILAN_SEED
) -> DecisionCandidate:
    """Demo dünyasından bir müşteri için tahsilat kararı üretir.

    `musteri_id` verilmezse **aksiyon gerektiren** ilk müşteri seçilir —
    `stok_karari_uret`'in "sipariş kararını tetikleyen ilk SKU" davranışıyla
    aynı. Hiç aksiyon yoksa ilk müşteri döner (karar `aksiyon_yok` olur).
    """
    ozellikler = _demo_ozellikleri(seed)
    if not ozellikler:
        raise ValueError("Demo dünyasında hiç müşteri yok.")

    if musteri_id is not None:
        secilen = next((o for o in ozellikler if o.musteri_id == musteri_id), None)
        if secilen is None:
            raise KeyError(f"Müşteri bulunamadı: {musteri_id}")
        return ozellikten_karar_uret(secilen)

    for ozellik in ozellikler:
        karar = ozellikten_karar_uret(ozellik)
        if not karar.tip.aksiyon_yok_mu:
            return karar
    return ozellikten_karar_uret(ozellikler[0])


__all__ = [
    "TABAN_GUVEN",
    "TAM_GUVEN_ICIN_GUN",
    "finans_karari_uret",
    "ozellikten_karar_uret",
    "ozellikten_kararlar_uret",
]
