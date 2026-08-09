"""Codifya Karar Motoru — FastAPI uygulaması.

Sahip: Kişi B

Çalıştırma:
    uv run uvicorn app.main:app --reload
Sonra: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, text

from app.api import approvals, ask, decisions, feedback, giris, insights, ui
from app.core.auth import UiKimlikGerekli, kimlik_dogrula, kimlik_yapilandirmasini_dogrula
from app.core.config import Ayarlar, ayarlar
from app.core.db import OturumDep
from app.models import Decision


@asynccontextmanager
async def _yasam_dongusu(_: FastAPI) -> AsyncIterator[None]:
    """Açılışta yapılandırmayı doğrular.

    ⚠️ Üretimde anahtarsız açılış burada patlar. Hatanın açılışta verilmesi
    bilinçli: ilk isteği bekleyen bir kontrol, servisi "ayakta ama korumasız"
    bir aralıkta bırakırdı.
    """
    kimlik_yapilandirmasini_dogrula(ayarlar())
    yield


app = FastAPI(
    title="Codifya Karar Motoru",
    description=(
        "ERP için hibrit karar mekanizması: sayısal kararı kural motoru + "
        "küçük ML verir, 1B LLM yalnızca Türkçe gerekçe yazar."
    ),
    version="0.1.0",
    lifespan=_yasam_dongusu,
)

# ⚠️ Kimlik doğrulama router SEVİYESİNDE bağlanıyor, tek tek uçlarda değil.
# Sebebi: yeni bir uç eklerken dekoratöre `dependencies=` yazmayı unutmak
# sessizce korumasız bir uç bırakırdı. Router'a bağlıyken unutmak mümkün
# değil — yeni uç zaten korumalı doğuyor.
_KORUMALI = [Depends(kimlik_dogrula)]

app.include_router(decisions.router, dependencies=_KORUMALI)
app.include_router(approvals.router, dependencies=_KORUMALI)
app.include_router(feedback.router, dependencies=_KORUMALI)
app.include_router(insights.router, dependencies=_KORUMALI)
app.include_router(ask.router, dependencies=_KORUMALI)
# Onay ekranı ve giriş sayfası kendi kimlik bağımlılığını taşıyor
# (`kimlik_dogrula_ui`): tarayıcıdaki insana 401 JSON değil giriş sayfası
# gösterilmeli. `giris` router'ı bilinçli olarak korumasız — kimlik almanın
# yolu kimlik gerektiremez.
app.include_router(giris.router)
app.include_router(ui.router)


@app.exception_handler(UiKimlikGerekli)
async def _ui_kimlik_yonlendir(request: Request, _: UiKimlikGerekli) -> RedirectResponse:
    """Onay ekranında kimlik yoksa giriş sayfasına götürür.

    `hedef` sorgu parametresi, girişten sonra insanın baktığı sayfaya geri
    dönmesi için. Yalnızca yol (`request.url.path`) taşınıyor, tam URL değil:
    dışarıdan verilen bir adrese yönlendirmek açık yönlendirme (open
    redirect) açığıdır.
    """
    return RedirectResponse(url=f"/onay/giris?hedef={request.url.path}", status_code=303)


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
    yetkiyle çalıştığı tek istekle görülebilmeli. Aynı gerekçeyle
    `kimlik_dogrulama` da burada — "anahtar tanımlamayı unuttuk" durumu
    sessiz kalmamalı.

    ⚠️ Bu uç bilinçli olarak korumasız: yük dengeleyici ve izleme sistemi
    anahtar taşımadan sağlık sorabilmeli. Karşılığında burada **hiçbir iş
    verisi yok** — yalnızca yapılandırma durumu.
    """
    return {
        "durum": "ayakta",
        "ortam": ayar.ortam,
        "otonomi_seviyesi": ayar.autonomy_level.value,
        "llm_model": ayar.llm_model_adi,
        "kimlik_dogrulama": "acik" if ayar.api_anahtar_kumesi else "kapali",
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
