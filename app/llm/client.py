"""Ollama HTTP istemcisi: zaman aşımı, yeniden deneme, token/süre ölçümü.

Sahip: Kişi B · Faz 2 B2.1

Bu dosya modelin **tek giriş kapısı**. `explain.py`, `router.py` ve gecelik iş
modele doğrudan değil buradan konuşur. Sebebi: zaman aşımı, yeniden deneme ve
ölçüm mantığı üç yerde tekrarlanmasın, ve Faz 4'teki "LLM çökerse kural motoru
tek başına devam etmeli" davranışı tek yerde garanti edilsin.

Üç tasarım kararı:

1. **Ölçüm modelin kendi raporundan alınır.** Ollama cevabında `eval_count`
   (üretilen token) ve `eval_duration` (nanosaniye) döner. Duvar saatiyle
   ölçmek ağ gecikmesini ve model yükleme süresini de içine katardı; B2.1'in
   istediği sayı saf üretim hızı.

2. **İş parçacığı sayısı yapılandırmadan gelir** (`config.llm_iplik_sayisi`).
   Ollama sınır verilmezse tüm çekirdekleri kullanır — dizüstü bilgisayarda
   sürekli tam yük ve ısınma demek. Bu istemci her istekte sınırı açıkça
   geçirir.

3. **Erişilemezlik bir istisnadır, çökme değil.** `LLMErisilemiyor` yakalanıp
   şablona düşülebilir. Karar yolu hiçbir koşulda LLM'e bağlı değil.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Ayarlar, ayarlar


class LLMErisilemiyor(RuntimeError):
    """Model sunucusuna ulaşılamadı veya zaman aşımına uğradı.

    Çağıran taraf bunu yakalayıp `explain.sablon_gerekce()`'ye düşmelidir —
    Faz 4'teki graceful degradation gereksinimi. Karar zaten üretilmiş
    durumdadır, yalnızca Türkçe cümle yazılamamıştır.
    """


@dataclass(frozen=True)
class UretimSonucu:
    """Tek bir üretim çağrısının çıktısı + ölçümleri.

    B2.1'in kabul ölçütü `token_hizi` alanı: "saniyedeki token sayısını ölçüp
    bir yere yazmışsın". Bu sayı Faz 4'te mimari kararları belirleyecek —
    gecelik iş bütçesi ve tepe RAM hedefi buna dayanacak.
    """

    metin: str
    model: str
    istem_token: int
    uretim_token: int

    # Modelin kendi raporladığı saf üretim süresi (ns → ms).
    uretim_ms: int
    # Ağ + model yükleme dahil, duvar saati.
    toplam_ms: int
    # Modelin bellekten yüklenme süresi. İlk çağrıda büyük, sonrakilerde ~0.
    yukleme_ms: int

    iplik_sayisi: int

    @property
    def token_hizi(self) -> float:
        """Saniyedeki üretilen token sayısı. Ölçümün asıl çıktısı."""
        if self.uretim_ms <= 0:
            return 0.0
        return self.uretim_token / (self.uretim_ms / 1000.0)

    def ozet(self) -> str:
        """Ölçüm satırı — ölçüm çıktılarına ve loga basmak için."""
        return (
            f"{self.model} | iplik={self.iplik_sayisi} | "
            f"{self.uretim_token} token / {self.uretim_ms} ms = "
            f"{self.token_hizi:.1f} token/sn | "
            f"yukleme={self.yukleme_ms} ms | toplam={self.toplam_ms} ms"
        )


def _ns_to_ms(deger: Any) -> int:
    """Ollama süreleri nanosaniye döndürür."""
    try:
        return int(int(deger) / 1_000_000)
    except (TypeError, ValueError):
        return 0


class OllamaIstemcisi:
    """Ollama `/api/generate` ucuna konuşan ince istemci.

    `transport` parametresi yalnızca testler için: gerçek ağa çıkmadan sahte
    cevap verilebilsin diye. Üretimde hiç kullanılmaz — bu sayede istemcinin
    tüm mantığı (yeniden deneme, ölçüm ayrıştırma, hata çevirisi) modeli
    çalıştırmadan sınanabiliyor.
    """

    def __init__(
        self,
        ayar: Ayarlar | None = None,
        *,
        iplik_sayisi: int | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.ayar = ayar or ayarlar()
        self.iplik_sayisi = iplik_sayisi if iplik_sayisi is not None else self.ayar.llm_iplik_sayisi
        self._istemci = httpx.Client(
            base_url=self.ayar.ollama_base_url,
            timeout=self.ayar.llm_timeout_sn,
            transport=transport,
        )

    # --- yaşam döngüsü -------------------------------------------------------

    def kapat(self) -> None:
        self._istemci.close()

    def __enter__(self) -> OllamaIstemcisi:
        return self

    def __exit__(self, *_: object) -> None:
        self.kapat()

    # --- sorgular ------------------------------------------------------------

    def ayakta_mi(self) -> bool:
        """Ollama sunucusu cevap veriyor mu. Model yüklemez, ısıtmaz."""
        try:
            return self._istemci.get("/api/tags").status_code == 200
        except httpx.HTTPError:
            return False

    def modeller(self) -> list[str]:
        """Kurulu model adları. Ölçümden önce modelin var olduğunu doğrulamak için."""
        try:
            cevap = self._istemci.get("/api/tags")
            cevap.raise_for_status()
        except httpx.HTTPError as hata:
            raise LLMErisilemiyor(f"Ollama'ya ulaşılamadı: {hata}") from hata
        return [m["name"] for m in cevap.json().get("models", [])]

    # --- üretim --------------------------------------------------------------

    def uret(
        self,
        istem: str,
        *,
        sistem: str | None = None,
        max_token: int | None = None,
        sicaklik: float | None = None,
        sema: dict[str, Any] | None = None,
        model: str | None = None,
        tohum: int | None = None,
    ) -> UretimSonucu:
        """Tek bir üretim çağrısı yapar ve ölçümlerle birlikte döndürür.

        `sema` verilirse Ollama'nın `format` parametresine geçirilir — model
        çıktıyı o JSON şemasına uymaya zorlanır (B2.2'nin dayanağı). Şemasız
        çağrılarda düz metin döner.

        `stream=False`: cevabı parça parça değil tek seferde alıyoruz. Ölçüm
        için gerekli sayaçlar (`eval_count`, `eval_duration`) yalnızca akış
        kapalıyken tek bir cevapta toplu gelir.

        `tohum` + `sicaklik=0` ⇒ **tekrarlanabilir çıktı.** Ölçüm scriptleri
        için şart: taban çizgi koşudan koşuya ±7 puan oynarsa "eğitim işe
        yaradı mı" sorusu gürültüden ayırt edilemez hale gelir. Üretimde
        kullanılmıyor — orada çeşitlilik zararsız.
        """
        govde: dict[str, Any] = {
            "model": model or self.ayar.llm_model_adi,
            "prompt": istem,
            "stream": False,
            "options": {
                # Isı kontrolünün asıl kolu. Verilmezse Ollama tüm çekirdekleri
                # kullanır.
                "num_thread": self.iplik_sayisi,
                "temperature": (sicaklik if sicaklik is not None else self.ayar.llm_sicaklik),
                "num_predict": max_token or self.ayar.llm_gerekce_max_token,
            },
        }
        if tohum is not None:
            govde["options"]["seed"] = tohum
        if sistem is not None:
            govde["system"] = sistem
        if sema is not None:
            govde["format"] = sema

        ham = self._istek_at("/api/generate", govde)

        return UretimSonucu(
            metin=ham["cevap"].get("response", ""),
            model=ham["cevap"].get("model", govde["model"]),
            istem_token=int(ham["cevap"].get("prompt_eval_count", 0)),
            uretim_token=int(ham["cevap"].get("eval_count", 0)),
            uretim_ms=_ns_to_ms(ham["cevap"].get("eval_duration")),
            toplam_ms=ham["duvar_ms"],
            yukleme_ms=_ns_to_ms(ham["cevap"].get("load_duration")),
            iplik_sayisi=self.iplik_sayisi,
        )

    # --- alt seviye ----------------------------------------------------------

    def _istek_at(self, yol: str, govde: dict[str, Any]) -> dict[str, Any]:
        """POST at, ağ hatalarında yeniden dene, duvar saatini ölç.

        Yeniden deneme YALNIZCA bağlantı/zaman aşımı hatalarında yapılır.
        Sunucu 4xx döndürdüyse istek hatalıdır — tekrarlamak aynı hatayı
        üretir ve boşuna CPU yakar.
        """
        son_hata: Exception | None = None

        for deneme in range(self.ayar.llm_yeniden_deneme + 1):
            baslangic = time.perf_counter()
            try:
                cevap = self._istemci.post(yol, json=govde)
                cevap.raise_for_status()
            except httpx.HTTPStatusError as hata:
                # Sunucu cevap verdi ama hata döndürdü; yeniden denemenin anlamı yok.
                raise LLMErisilemiyor(
                    f"Ollama {hata.response.status_code} döndürdü: {hata.response.text[:200]}"
                ) from hata
            except httpx.HTTPError as hata:
                son_hata = hata
                if deneme < self.ayar.llm_yeniden_deneme:
                    # Kısa, artan bekleme. Sunucu yeni ayağa kalkıyor olabilir.
                    time.sleep(0.5 * (deneme + 1))
                continue
            else:
                return {
                    "cevap": cevap.json(),
                    "duvar_ms": int((time.perf_counter() - baslangic) * 1000),
                }

        raise LLMErisilemiyor(
            f"Ollama'ya {self.ayar.llm_yeniden_deneme + 1} denemede ulaşılamadı: {son_hata}"
        )
