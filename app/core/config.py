"""Yapılandırma — tüm eşikler ve bağlantılar buradan okunur.

Sahip: Kişi B · Faz 0.2 / Faz 1 B1.2

KURAL: Kodda hiçbir sabit (hardcoded) eşik olmayacak. Bir sayı iş kararıysa
buraya ya da (Faz 1'den sonra) `policy` tablosuna girer. Bu kural olmadan
eşikleri değiştirmek için kod dağıtmak gerekir.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.contracts import OtonomiSeviyesi

PROJE_KOKU = Path(__file__).resolve().parents[2]


class Ayarlar(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJE_KOKU / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Ortam ---
    ortam: str = "gelistirme"

    # --- Veritabanı ---
    # SQLite ile başlıyoruz (C: sürücüsünde yer yok, Docker gereksiz yük).
    # Postgres'e geçiş yalnızca bu satırın değişmesi demek.
    database_url: str = f"sqlite:///{PROJE_KOKU / 'data' / 'codifya.db'}"

    # --- Otonomi ---
    # ⚠️ shadow modda ölçülmüş doğruluk raporu olmadan threshold'a geçilmez.
    autonomy_level: OtonomiSeviyesi = OtonomiSeviyesi.SHADOW

    # --- Eşikler (Faz 1'de policy tablosuna taşınacak) ---
    esik_oto_uygula_tutar_tl: float = 5_000.0
    esik_oto_uygula_min_guven: float = 0.85

    # --- LLM ---
    ollama_base_url: str = "http://127.0.0.1:11434"
    llm_model_adi: str = "qwen2.5:1.5b-instruct"
    llm_timeout_sn: float = 60.0
    llm_gerekce_max_token: int = 220

    # --- Gecelik iş ---
    # 2.000 SKU × ~7 sn = 4 saat olurdu. Gerekçe yalnızca insanın gerçekten
    # baktığı ilk N karar için üretilir; geri kalanı kuyrukta bekler.
    gecelik_gerekce_ust_n: int = 25

    # --- Simülasyon verisi ---
    sim_veri_koku: Path = PROJE_KOKU / "data" / "sim"


@lru_cache
def ayarlar() -> Ayarlar:
    """Tek örnek (singleton) ayar nesnesi. FastAPI dependency olarak kullanılır."""
    return Ayarlar()
