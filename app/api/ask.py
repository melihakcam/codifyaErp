"""Doğal dil sorusu → router → araç çağrısı.

Sahip: Kişi B · Faz 2 B2.3

Bu uç **yalnızca yönlendirme** yapar; seçilen aracı henüz çalıştırmaz. Sebebi
bilinçli: B2.3'ün ölçtüğü şey "doğru aracı seçebiliyor muyuz". Aracın
çalıştırılmasını da aynı adıma sıkıştırmak, yanlış yönlendirmeyi doğru
sonucun arkasına gizlerdi.

Araç çalıştırma Faz 4'te bağlanacak — o zaman `arac` alanına göre ilgili
endpoint çağrılacak (`onay_kuyrugu_sorgula` → `GET /v1/approvals` gibi).

⚠️ Bu uç LLM'e bağlı, dolayısıyla **karar yolu değil**. Model erişilemezse
503 döner; `POST /v1/decisions/...` bundan etkilenmez.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.llm.client import LLMErisilemiyor, OllamaIstemcisi
from app.llm.router import soruyu_yonlendir
from app.llm.schemas import AracAdi, SemaUyumsuz

router = APIRouter(prefix="/v1/ask", tags=["doğal dil"])


class SoruIstegi(BaseModel):
    soru: Annotated[str, Field(min_length=1, max_length=500)]


class YonlendirmeCevabi(BaseModel):
    soru: str
    arac: AracAdi
    parametreler: dict[str, str]
    deneme_sayisi: int
    uretim_ms: int


@router.post("", response_model=YonlendirmeCevabi, summary="Soruyu araca yönlendir")
def soru_sor(istek: SoruIstegi) -> YonlendirmeCevabi:
    """Türkçe soruyu bilinen araçlardan birine yönlendirir.

    Hata durumları bilinçli olarak ayrı:

    · **422** — model geçerli bir araç çağrısı üretemedi. Kullanıcıya
      "anlayamadım" demek doğru; tahmin edip yanlış araca yönlendirmek değil.
    · **503** — model sunucusuna ulaşılamadı. Geçici bir altyapı sorunu,
      istemci tekrar deneyebilir.
    """
    try:
        with OllamaIstemcisi() as istemci:
            sonuc = soruyu_yonlendir(istemci, istek.soru)
    except SemaUyumsuz as hata:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Soru bilinen araçlardan birine yönlendirilemedi. "
                f"({hata.denemeler} deneme yapıldı.)"
            ),
        ) from hata
    except LLMErisilemiyor as hata:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Dil modeline ulaşılamadı: {hata}",
        ) from hata

    return YonlendirmeCevabi(
        soru=istek.soru,
        arac=sonuc.cagri.arac,
        parametreler=sonuc.cagri.parametreler,
        deneme_sayisi=sonuc.deneme_sayisi,
        uretim_ms=sonuc.uretim_ms,
    )
