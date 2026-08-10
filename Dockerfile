# Codifya Karar Motoru — üretim imajı
#
# ⚠️ Bu imaj YALNIZCA karar motorunu taşıyor. Ollama (LLM) ayrı bir servis
# ve bilinçli olarak buraya konmadı: model 1,5 GB ve CPU'da çalışıyor, aynı
# imaja koymak her dağıtımda o boyutu taşımak demek. Ayrıca müşteride
# Ollama zaten kurulu olabilir ya da başka bir makinede çalışabilir.
#
#     docker build -t codifya:latest .
#     docker run -p 8000:8000 --env-file .env -v codifya-veri:/veri codifya:latest
#
# LLM'e ulaşamazsa sistem ÇÖKMEZ — kural motoru kararı verir, gerekçe
# şablona düşer (bkz. app/llm/explain.py). Bu bilinçli bir tasarım: LLM
# süs, karar değil.

FROM python:3.12-slim AS temel

# ⚠️ uv, pip yerine: bağımlılık çözümü kilit dosyasından (uv.lock) birebir
# yeniden üretiliyor. `pip install -r requirements.txt` sürüm sürüklenmesine
# açık; ölçülmüş bir sistemde kütüphane sürümünün sessizce değişmesi,
# yeniden üretilemeyen bir sonuç demek.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /uygulama

# Bağımlılıklar önce: kod değiştiğinde bu katman yeniden kurulmuyor.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY simulator ./simulator
COPY alembic ./alembic
COPY alembic.ini ./
COPY profiller ./profiller

RUN uv sync --frozen --no-dev

# ⚠️ Veritabanı ve profiller VOLUME'da. İmajın içinde tutulursa konteyner
# her yenilendiğinde denetim izi silinir — kararların geçmişi kaybolur.
VOLUME ["/veri"]
ENV DATABASE_URL=sqlite:////veri/codifya.db

# ⚠️ Kök kullanıcı DEĞİL. Konteyner ele geçirilirse yetkiyi sınırlar.
RUN useradd --create-home --uid 10001 codifya && chown -R codifya:codifya /uygulama /veri
USER codifya

EXPOSE 8000

# ⚠️ Sağlık kontrolü `/health` — kimlik istemiyor (yük dengeleyici için)
# ve iş verisi döndürmüyor. Bkz. app/main.py.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=4).status==200 else 1)"

# ⚠️ Tek worker. Hız sınırı sayacı BELLEKTE tutuluyor (app/main.py); çok
# worker'la her worker kendi sayacını tutar ve gerçek sınır worker sayısıyla
# çarpılır. Ölçekleme gerekirse önce o sayaç Redis'e taşınmalı.
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
