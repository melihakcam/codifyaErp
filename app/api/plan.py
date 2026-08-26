"""Genel plan ucu — `POST /v1/plan/{alan}`.

Sahip: Kişi B · Faz 13 B13.3

## Neden ayrı bir uç

Motor Faz 11'de genelleşti ama **API yüzeyi genelleşmedi**: uçlar hâlâ
üretime özeldi (`/v1/decisions/production/schedule`). Nakliye motorda
koşuyor ama dışarıdan çağrılamıyordu. Bu uç o boşluğu kapatıyor: alan adı
yoldan geliyor, kod alanı tanımıyor.

⚠️ **Üretime özel uçlar SİLİNMEDİ.** Onları çağıran bir istemci varsa
sessizce kırmak, uyumluluk sözünü bir kere bozmak demektir. Yeni ucun
onların yerine geçtiği belgede yazılı; silme kararı ayrı ve sonraki bir iş.

## ⚠️ Bu uç KARAR ÜRETMİYOR

`uretim_cizelgesi` ile aynı ayrım: plan, zaten üretilmiş kararların
takvime dizilmiş **görünümü**. DB'ye hiçbir şey yazılmıyor, hiçbir şey
onaya sunulmuyor. Otonomi modeli kalem bazında insan onayına dayanıyor;
tek bir planı onaylamak içindeki yüzlerce örtük kararı görmeden onaylamak
olurdu.

`POST` olması bunun aksini söylemiyor — gövdede ölçüt ve ufuk taşıdığı
için POST; yan etkisi yok.

## ⚠️ Süre: üretim planı ~70 saniye

Ölçüldü: `uretim_kararlari_uret()` ilk koşu 74,7 sn, ikinci 35,9 sn
(2.000 kalem için tahmin + kural). Bu **yeni bir sorun değil** — mevcut
`/v1/decisions/production/schedule` ucu da aynı hesabı yapıyor.

Adaptördeki süreli önbellek sayesinde arka arkaya gelen istekler hızlı;
ilk istek yavaş. Gerçek çözüm gecelik işteki kalıp (sonucu hazırla, uç
hazırı versin) ve **bu fazın kapsamı dışında** — kayıt için
`dokumantasyon/BILINEN-EKSIKLER.md`.

`elle` kipindeki alanlar (nakliye, vardiya) milisaniyelerde dönüyor.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, status

from app.contracts import OtonomiSeviyesi
from app.core.config import Ayarlar, ayarlar
from app.planlama.belge import belge_metni
from app.planlama.olcut import OLCUT_ACIKLAMALARI, OLCUTLER
from app.planlama.tam_plan import TamPlan, TamPlanHatasi, alanlari_listele, tam_plan

router = APIRouter(prefix="/v1/plan", tags=["plan"])

AyarDep = Annotated[Ayarlar, Depends(ayarlar)]


def _kapali_mi(ayar: Ayarlar) -> None:
    """Kill switch — `AUTONOMY_LEVEL=off` ise plan da üretilmiyor."""
    if ayar.autonomy_level is OtonomiSeviyesi.OFF:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Karar motoru kapalı (AUTONOMY_LEVEL=off).",
        )


def _sozluge_cevir(plan: TamPlan, belge: bool) -> dict:
    """`TamPlan` → JSON. ⚠️ Gerekçe metne çevrilmiyor, **veri** kalıyor."""
    return {
        "alan": plan.alan,
        "alan_adi": plan.alan_adi,
        "olcut": plan.olcut,
        "olcut_aciklamasi": OLCUT_ACIKLAMALARI.get(plan.olcut, plan.olcut),
        "ufuk_gun": plan.ufuk_gun,
        "baslangic": plan.baslangic.isoformat(),
        "isler_kaynagi": plan.isler_kaynagi,
        "is_sayisi": plan.is_sayisi,
        "kaynaklar": [
            {
                "kaynak_id": k.kaynak_id,
                "kaynak_adi": k.kaynak_adi,
                "gunluk_kapasite": k.gunluk_kapasite,
                "kapasite_birimi": k.kapasite_birimi,
                "doluluk": round(k.doluluk, 4),
                "isler": [
                    {
                        "is_id": s.is_id,
                        "ad": s.ad,
                        "baslangic": s.baslangic.isoformat(),
                        "bitis": s.bitis.isoformat(),
                        "yuk": s.yuk,
                        "oncelik": s.oncelik,
                        "etiketler": s.etiketler,
                        "gerekce": None
                        if s.gerekce is None
                        else {
                            "secilen_kaynak": s.gerekce.secilen_kaynak,
                            "aday_kaynaklar": list(s.gerekce.aday_kaynaklar),
                            "belirleyici": s.gerekce.belirleyici,
                            "elenme_nedenleri": s.gerekce.elenme_nedenleri,
                        },
                    }
                    for s in k.satirlar
                ],
                # ⚠️ Sığmayanlar ayrı bir liste olarak dönüyor: plana
                # koymamak onları iptal etmek değil ve istemci "her şey
                # yetişiyor" sanmamalı.
                "sigmayanlar": [
                    {"is_id": s.is_id, "ad": s.ad, "yuk": s.yuk} for s in k.sigmayanlar
                ],
            }
            for k in plan.planlar
        ],
        "secenekler": {
            "onerilen_olcut": plan.karsilastirma.onerilen_olcut,
            "gerekce": plan.karsilastirma.oneri_gerekcesi,
            "karneler": [
                {
                    "olcut": karne.olcut,
                    "aciklama": karne.aciklama,
                    "yerlesen_is": karne.maliyet.yerlesen_is,
                    "sigmayan_is": karne.maliyet.sigmayan_is,
                    "beklenen_maliyet_tl": round(karne.maliyet.toplam_tl, 2),
                    "doluluk": round(karne.doluluk, 4),
                    # ⚠️ Varsayımlar daima birlikte gidiyor: maliyet bir
                    # tahmin ve neye dayandığı görünmezse sorgulanamaz.
                    "varsayimlar": list(karne.maliyet.varsayimlar),
                }
                for karne in plan.karsilastirma.karneler
            ],
        },
        "uyarilar": list(plan.uyarilar),
        **({"belge": belge_metni(plan)} if belge else {}),
    }


@router.get("/alanlar")
def alanlar() -> dict:
    """Tanımlı alanlar — yeni alan eklemek için kod değil JSON gerekiyor."""
    return {"alanlar": list(alanlari_listele())}


@router.post("/{alan}")
def plan_uret(
    ayar: AyarDep,
    alan: Annotated[str, Path(description="Alan adı — `GET /v1/plan/alanlar` ile listelenir")],
    belge: Annotated[
        bool, Query(description="Okunabilir plan belgesini de döndür (altı bölüm)")
    ] = False,
    olcut: Annotated[str | None, Body(embed=True)] = None,
    ufuk_gun: Annotated[int | None, Body(embed=True)] = None,
) -> dict:
    """Bir alanın **tamamının** planı — tek komut, alan adı yoldan.

    `olcut` verilmezse üç ölçüt de koşulur, maliyeti en düşük olan önerilir
    ve tablo yine de çıktıda durur.
    """
    _kapali_mi(ayar)

    if olcut is not None and olcut not in OLCUTLER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Bilinmeyen ölçüt: {olcut}. Tanımlılar: {sorted(OLCUTLER)}",
        )

    try:
        plan = tam_plan(alan, olcut=olcut, ufuk_gun=ufuk_gun)
    except TamPlanHatasi as hata:
        # ⚠️ Tanımsız alan 404: istemcinin yazım hatası ile sunucu hatası
        # aynı koda düşerse hangisinin suçlu olduğu anlaşılmaz.
        #
        # ⚠️ Hata metni OLDUĞU GİBİ dönmüyor: motorun mesajı tanım
        # dosyasının tam yolunu içeriyor ("D:\ERP\..."), o da sunucunun
        # dizin yapısını dışarıya sızdırır. İçeride yararlı, dışarıda
        # gereksiz ve risklidir.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"'{alan}' tanımlı bir alan değil. Tanımlılar: {list(alanlari_listele())}",
        ) from hata

    return _sozluge_cevir(plan, belge)


__all__ = ["router"]
