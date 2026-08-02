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

    # Modelin kullanacağı CPU iş parçacığı sayısı.
    # ⚠️ Varsayılan bilinçli olarak DÜŞÜK. Ollama hiçbir sınır verilmezse tüm
    # çekirdekleri kullanır; dizüstü bilgisayarda bu sürekli tam yük ve ısınma
    # demek. 1,5B model CPU'da bellek bant genişliğine takıldığı için iş
    # parçacığı sayısını düşürmek hızın küçük bir kısmını kaybettirir ama ısıyı
    # belirgin azaltır. Doğru değer makineye göre değişir — B2.1'de ölçülüp
    # buraya yazılacak.
    llm_iplik_sayisi: int = 4

    # 0 = deterministik. Gerekçe metninde yaratıcılık istemiyoruz; aynı karara
    # aynı cümle çıksın ki guard'ın davranışı tekrarlanabilir olsun.
    llm_sicaklik: float = 0.2

    # Ağ/zaman aşımı hatalarında kaç kez yeniden denensin (ilk deneme hariç).
    # Şema uyumsuzluğu gibi içerik hataları burada değil, çağıran tarafta
    # ele alınır.
    llm_yeniden_deneme: int = 2

    # --- Gecelik iş ---
    # 2.000 SKU × ~7 sn = 4 saat olurdu. Gerekçe yalnızca insanın gerçekten
    # baktığı ilk N karar için üretilir; geri kalanı kuyrukta bekler.
    gecelik_gerekce_ust_n: int = 25

    # --- Olay tetikleyicileri (B2.6) ---
    # Gecelik taramayı beklemeden anında ele alınması gereken durumlar.
    # Eşikler burada çünkü iş kararı: sahada "büyük sipariş" neye denir,
    # şirkete göre değişir ve kod dağıtmadan ayarlanabilmeli.
    tetik_buyuk_siparis_tutar_tl: float = 25_000.0

    # Kullanılabilir stok kaç günlük tüketimin altına düşerse kritik sayılır.
    # Tedarik süresinden bağımsız kaba bir alarm — asıl ROP hesabı kural
    # motorunda; bu yalnızca "hemen bak" sinyali.
    tetik_kritik_stok_gun: float = 3.0

    # Bir günde açılan siparişlerin toplamı bu tutarı aşarsa uyarı.
    tetik_gunluk_siparis_limiti_tl: float = 250_000.0

    # --- Simülasyon verisi ---
    sim_veri_koku: Path = PROJE_KOKU / "data" / "sim"


@lru_cache
def ayarlar() -> Ayarlar:
    """Tek örnek (singleton) ayar nesnesi. FastAPI dependency olarak kullanılır."""
    return Ayarlar()
