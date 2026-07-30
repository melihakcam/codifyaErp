"""Onay kuyruğu: listele, onayla, reddet, düzelt.

Sahip: Kişi B · Faz 1 B1.5

Kuyruğa yalnızca `PolitikaSonucu.ONAY_KUYRUGU` alan kararlar girer. Shadow
modda eşik altı kalan bir karar **kaydedilir ama kuyruğa girmez** — kimsenin
bakmayacağı bir kaydı insanın önüne koymak kuyruğu değersizleştirir.

İnsan kararı iki yere yazılır:
· `approval` → iş akışı durumu (kim, ne zaman, ne dedi)
· `feedback` → sonraki eğitim turunun verisi (özellikle `duzeltilmis_aksiyon`)

⚠️ `Decision.uygulandi` bu endpoint'te DEĞİŞTİRİLMEZ. O alan "sistem uyguladı
mı" demek; insanın onaylaması sistemin uygulaması değildir. Karıştırılırsa
shadow mod raporu (politikanın hükmü vs gerçekten olan) anlamını kaybeder.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.contracts import GuardSonucu, KararTipi, PolitikaSonucu
from app.core.db import OturumDep
from app.models import Approval, Decision, Feedback, GeriBildirimTuru, OnayDurumu

router = APIRouter(prefix="/v1/approvals", tags=["onaylar"])


class OnayEylemi(StrEnum):
    """İnsanın kuyrukta yapabileceği üç şey."""

    ONAYLA = "onayla"
    REDDET = "reddet"
    DUZELT = "duzelt"


# Eylem → (iş akışı durumu, geri bildirim türü). Tek yerde tanımlı olması
# bilinçli: iki eşleme ayrı yerlerde durursa sessizce ayrışır.
_EYLEM_ESLEMESI: dict[OnayEylemi, tuple[OnayDurumu, GeriBildirimTuru]] = {
    OnayEylemi.ONAYLA: (OnayDurumu.ONAYLANDI, GeriBildirimTuru.ONAY),
    OnayEylemi.REDDET: (OnayDurumu.REDDEDILDI, GeriBildirimTuru.RED),
    OnayEylemi.DUZELT: (OnayDurumu.DUZELTILDI, GeriBildirimTuru.DUZELTME),
}


class KuyrukKalemi(BaseModel):
    """Kuyrukta insanın gördüğü tek satır."""

    karar_id: UUID
    durum: OnayDurumu
    tip: KararTipi
    aksiyon: dict[str, Any]
    tahmini_tutar_tl: float
    guven: float
    risk_skoru: float
    politika_sonucu: PolitikaSonucu
    gerekce_kodlari: list[str]
    gerekce_metni: str | None
    guard_sonucu: GuardSonucu | None
    kuyruga_giris: datetime


class OnayIstegi(BaseModel):
    """Kuyruktaki bir karara verilen insan kararı."""

    eylem: OnayEylemi
    kullanici: str = Field(min_length=1, description="Kararı veren kişi — denetim için zorunlu")
    duzeltilmis_aksiyon: dict[str, float | int | str | None] | None = None
    yorum: str | None = None

    @model_validator(mode="after")
    def duzeltme_aksiyon_ister(self) -> OnayIstegi:
        """`duzelt` eyleminde düzeltilmiş aksiyon zorunlu.

        Aksi halde "düzeltildi" yazan ama neye düzeltildiği belli olmayan bir
        kayıt oluşur — eğitim verisi olarak değersiz.
        """
        if self.eylem is OnayEylemi.DUZELT and not self.duzeltilmis_aksiyon:
            raise ValueError("duzelt eylemi icin duzeltilmis_aksiyon zorunlu")
        return self


class OnaySonucu(BaseModel):
    karar_id: UUID
    durum: OnayDurumu
    feedback_id: int
    karar_zamani: datetime


@router.get("", response_model=list[KuyrukKalemi], summary="Onay kuyruğunu listele")
def kuyrugu_listele(
    oturum: OturumDep,
    durum: Annotated[
        OnayDurumu | None,
        Query(description="Boş bırakılırsa tüm durumlar döner."),
    ] = OnayDurumu.BEKLIYOR,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KuyrukKalemi]:
    """Kuyruğu risk skoruna göre azalan sırada döndürür.

    Sıralama bilinçli: insanın zamanı kısıtlı, en yüksek riskli karar en üstte
    olmalı. Tarihe göre sıralamak 5.000 TL'lik bir kararı 50 TL'lik kararların
    arkasına atardı.
    """
    sorgu = (
        select(Approval, Decision)
        .join(Decision, Approval.karar_id == Decision.karar_id)
        .order_by(Decision.risk_skoru.desc(), Approval.olusturma_zamani)
        .limit(limit)
        .offset(offset)
    )
    if durum is not None:
        sorgu = sorgu.where(Approval.durum == durum)

    return [
        KuyrukKalemi(
            karar_id=onay.karar_id,
            durum=onay.durum,
            tip=karar.tip,
            aksiyon=karar.aksiyon,
            tahmini_tutar_tl=karar.tahmini_tutar_tl,
            guven=karar.guven,
            risk_skoru=karar.risk_skoru,
            politika_sonucu=karar.politika_sonucu,
            gerekce_kodlari=karar.gerekce_kodlari,
            gerekce_metni=karar.gerekce_metni,
            guard_sonucu=karar.guard_sonucu,
            kuyruga_giris=onay.olusturma_zamani,
        )
        for onay, karar in oturum.execute(sorgu).all()
    ]


@router.post(
    "/{karar_id}",
    response_model=OnaySonucu,
    summary="Kuyruktaki kararı onayla / reddet / düzelt",
)
def karari_sonuclandir(
    karar_id: UUID,
    istek: OnayIstegi,
    oturum: OturumDep,
) -> OnaySonucu:
    """İnsan kararını uygular: `approval` durumunu günceller, `feedback` yazar.

    Yol adındaki kimlik `approval.id` değil `karar_id` — sistemdeki tüm
    tablolar (`feedback`, `decision_audit`, `insight`) buna göre anahtarlanıyor.
    İki kimlik dolaştırmak, yanlış olanı kullanma hatasını davet eder.
    """
    onay = oturum.scalars(select(Approval).where(Approval.karar_id == karar_id)).one_or_none()

    if onay is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Kuyrukta {karar_id} kimlikli karar yok.",
        )

    if onay.durum is not OnayDurumu.BEKLIYOR:
        # 409: karar zaten verilmiş. Durumu yeniden yazmak iş akışı geçmişini
        # bozar; ek yorum eklemek isteyen POST /v1/feedback kullanır.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Karar zaten sonuçlandırılmış (durum={onay.durum.value}). "
                "Ek geri bildirim için POST /v1/feedback kullanın."
            ),
        )

    durum, geri_bildirim_turu = _EYLEM_ESLEMESI[istek.eylem]
    simdi = datetime.now()

    onay.durum = durum
    onay.karar_zamani = simdi
    onay.karar_veren = istek.kullanici

    geri_bildirim = Feedback(
        karar_id=karar_id,
        tur=geri_bildirim_turu,
        duzeltilmis_aksiyon=istek.duzeltilmis_aksiyon,
        yorum=istek.yorum,
        kullanici=istek.kullanici,
        zaman=simdi,
    )
    oturum.add(geri_bildirim)
    oturum.commit()

    return OnaySonucu(
        karar_id=karar_id,
        durum=durum,
        feedback_id=geri_bildirim.id,
        karar_zamani=simdi,
    )
