"""Codifya Karar Motoru — FastAPI uygulaması.

Sahip: Kişi B

Çalıştırma:
    uv run uvicorn app.main:app --reload
Sonra: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request, status
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select, text

from app.api import approvals, ask, decisions, feedback, giris, insights, ui
from app.core.auth import (
    UiKimlikGerekli,
    _istekten_anahtar_oku,
    anahtar_gecerli_mi,
    kimlik_dogrula,
    kimlik_yapilandirmasini_dogrula,
)
from app.core.config import Ayarlar, ayarlar
from app.core.db import OturumDep
from app.models import Decision

_ISTEK_GECMISI: defaultdict[str, deque[float]] = defaultdict(deque)
"""Anahtar → son bir dakikanın istek zaman damgaları (hız sınırı)."""


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
    # ⚠️ Varsayılan doküman uçları KAPATILDI; aşağıda kimlik isteyen
    # sürümleri tanımlı (B4). FastAPI'nin kendi uçları bağımlılık kabul
    # etmiyor, o yüzden tek yol bu.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def _hiz_siniri(request: Request, sonraki):
    """Anahtar başına dakikalık istek sınırı.

    ⚠️ Yalnızca kimlik doğrulama AÇIKKEN uygulanıyor — sınır, servis dışarı
    açıldığında anlam kazanıyor ve o da anahtar tanımlı olduğu durum.

    ⚠️ **Bellekte tutuluyor.** Tek süreçte doğru çalışır; birden çok worker
    ile çalıştırılırsa her worker kendi sayacını tutar ve gerçek sınır
    worker sayısıyla çarpılır. Tek süreçli kurulum için yeterli, ölçekli
    kurulumda Redis'e taşınmalı — bu not silinmeden çoğaltılmasın.
    """
    # ⚠️ Middleware bağımlılık enjeksiyonu kullanamıyor (FastAPI'nin DI'ı
    # yalnızca rota işleyicilerinde çalışır). Bu yüzden ayarlar doğrudan
    # okunuyor — ama `dependency_overrides` tablosuna da bakılıyor ki
    # testler ve `--reload` sırasında yapılan geçici ayarlar burada da
    # geçerli olsun. Aksi hâlde hız sınırı, uygulamanın geri kalanından
    # farklı bir dünyada yaşardı.
    ayar_ureteci = app.dependency_overrides.get(ayarlar, ayarlar)
    ayar = ayar_ureteci()
    sinir = ayar.hiz_siniri_dakikada
    if sinir > 0 and ayar.api_anahtar_kumesi:
        anahtar = _istekten_anahtar_oku(request) or "anonim"
        simdi = time.monotonic()
        pencere = _ISTEK_GECMISI[anahtar]
        # 60 saniyeden eski kayıtları at.
        while pencere and simdi - pencere[0] > 60.0:
            pencere.popleft()
        if len(pencere) >= sinir:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": f"Dakikada {sinir} istek sınırı aşıldı."},
                headers={"Retry-After": "60"},
            )
        pencere.append(simdi)

    return await sonraki(request)


def _docs_kimligi(
    request: Request, ayar: Annotated[Ayarlar, Depends(ayarlar)]
) -> None:
    """Doküman uçları için kimlik — ayarla kapatılabilir.

    `docs_kimlik_istesin=False` yapan bir kurulum şemayı bilerek açıyor
    demektir (ör. tamamen kapalı bir iç ağ). Varsayılan kapalı değil:
    şema, sistemin hangi kararları verdiğini satır satır anlatıyor.
    """
    if ayar.docs_kimlik_istesin:
        kimlik_dogrula(request, ayar)


DocsKimlik = Annotated[None, Depends(_docs_kimligi)]


@app.get("/openapi.json", include_in_schema=False)
def openapi_semasi(_kimlik: DocsKimlik) -> JSONResponse:
    """OpenAPI şeması — kimlik doğrulama açıksa korumalı.

    Şema, sistemin hangi kararları verdiğini ve hangi alanları okuduğunu
    satır satır anlatıyor; iç ağda bile gereksiz yere açık durmasının bir
    faydası yok.
    """
    return JSONResponse(app.openapi())


@app.get("/docs", include_in_schema=False)
def swagger_arayuzu(_kimlik: DocsKimlik) -> HTMLResponse:
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Codifya - API")

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
def health_db(
    request: Request, oturum: OturumDep, ayar: Annotated[Ayarlar, Depends(ayarlar)]
) -> dict[str, str | int | bool]:
    """Veritabanı bağlantısı + FK zorlaması (+ kimlikliyse karar sayısı).

    `yabanci_anahtar_zorlamasi` alanı burada bilinçli: SQLite bu pragmayı
    bağlantı başına ister ve kapalı kalırsa hiçbir hata vermez — denetim izi
    sessizce tutarsızlaşır. Canlıda tek istekle görülebilmesi gerekiyor.

    ⚠️ B4'te değişti: `kayitli_karar` **iş verisidir** — kaç karar üretildiği
    şirketin işlem hacmini ele verir. Uç açık kalıyor (izleme sistemi
    bağlantıyı sorabilmeli) ama sayı yalnızca kimliği doğrulanmış çağırana
    veriliyor. Sağlık kontrolü için bağlantı durumu zaten yeterli.
    """
    fk_acik = bool(oturum.execute(text("PRAGMA foreign_keys")).scalar())
    cevap: dict[str, str | int | bool] = {
        "durum": "baglandi",
        "yabanci_anahtar_zorlamasi": fk_acik,
    }

    if not ayar.api_anahtar_kumesi:
        cevap["kayitli_karar"] = oturum.scalar(select(func.count()).select_from(Decision)) or 0
        return cevap

    anahtar = _istekten_anahtar_oku(request)
    if anahtar is not None and anahtar_gecerli_mi(anahtar, ayar.api_anahtar_kumesi):
        cevap["kayitli_karar"] = oturum.scalar(select(func.count()).select_from(Decision)) or 0

    return cevap
