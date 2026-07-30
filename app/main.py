"""Codifya Karar Motoru — FastAPI uygulaması.

Sahip: Kişi B

Çalıştırma:
    uv run uvicorn app.main:app --reload
Sonra: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI

from app.api import decisions
from app.core.config import Ayarlar, ayarlar

app = FastAPI(
    title="Codifya Karar Motoru",
    description=(
        "ERP için hibrit karar mekanizması: sayısal kararı kural motoru + "
        "küçük ML verir, 1B LLM yalnızca Türkçe gerekçe yazar."
    ),
    version="0.1.0",
)

app.include_router(decisions.router)


@app.get("/health", tags=["sistem"])
def health(ayar: Annotated[Ayarlar, Depends(ayarlar)]) -> dict[str, str]:
    """Ayakta mı + hangi otonomi seviyesinde çalışıyor.

    Otonomi seviyesini burada göstermek bilinçli: sistemin canlıda hangi
    yetkiyle çalıştığı tek istekle görülebilmeli.
    """
    return {
        "durum": "ayakta",
        "ortam": ayar.ortam,
        "otonomi_seviyesi": ayar.autonomy_level.value,
        "llm_model": ayar.llm_model_adi,
    }
