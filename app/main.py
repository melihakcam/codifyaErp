"""Codifya Karar Motoru — FastAPI uygulaması.

Sahip: Kişi B

Çalıştırma:
    uv run uvicorn app.main:app --reload
Sonra: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, text

from app.api import approvals, ask, decisions, feedback, insights, ui
from app.core.config import Ayarlar, ayarlar
from app.core.db import OturumDep
from app.models import Decision

app = FastAPI(
    title="Codifya Karar Motoru",
    description=(
        "ERP için hibrit karar mekanizması: sayısal kararı kural motoru + "
        "küçük ML verir, 1B LLM yalnızca Türkçe gerekçe yazar."
    ),
    version="0.1.0",
)

app.include_router(decisions.router)
app.include_router(approvals.router)
app.include_router(feedback.router)
app.include_router(insights.router)
app.include_router(ask.router)
app.include_router(ui.router)


@app.get("/", include_in_schema=False)
def kok() -> RedirectResponse:
    """Kökü `/docs`'a yönlendirir.

    FastAPI kök adrese varsayılan olarak hiçbir şey koymaz; `localhost:8000`
    açan biri `{"detail":"Not Found"}` görür ve servisin çökmüş olduğunu
    sanır. Tek satırlık yönlendirme bu yanlış teşhisi ortadan kaldırıyor.

    `include_in_schema=False`: bu bir API ucu değil, kolaylık. OpenAPI
    şemasında görünmesi ERP tarafını yanıltır.
    """
    return RedirectResponse(url="/docs")


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


@app.get("/health/db", tags=["sistem"])
def health_db(oturum: OturumDep) -> dict[str, str | int | bool]:
    """Veritabanı bağlantısı + kayıtlı karar sayısı + FK zorlaması.

    `yabanci_anahtar_zorlamasi` alanı burada bilinçli: SQLite bu pragmayı
    bağlantı başına ister ve kapalı kalırsa hiçbir hata vermez — denetim izi
    sessizce tutarsızlaşır. Canlıda tek istekle görülebilmesi gerekiyor.
    """
    fk_acik = bool(oturum.execute(text("PRAGMA foreign_keys")).scalar())
    karar_sayisi = oturum.scalar(select(func.count()).select_from(Decision)) or 0

    return {
        "durum": "baglandi",
        "kayitli_karar": karar_sayisi,
        "yabanci_anahtar_zorlamasi": fk_acik,
    }
