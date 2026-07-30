# Codifya Karar Motoru

Codifya ERP için **hibrit karar mekanizması**: sayısal kararı deterministik kural motoru
ve küçük klasik ML modelleri verir, 1B sınıfı bir LLM yalnızca Türkçe gerekçe yazar ve
doğal dil sorularını yönlendirir.

ERP'nin *içinde* değil *yanında* durur — REST ile konuşur, dolayısıyla ERP hangi dilde
yazılırsa yazılsın bu motor yeniden yazılmaz.

---

## Mimariyi ayakta tutan iki kural

Kod okurken bu ikisini akılda tut; tasarımın geri kalanı bunların sonucudur.

**1. LLM asla sayı üretmez.**
Sayılar prompt'a kural motorundan *verilir*, model onları yalnızca cümleye yerleştirir.
Üretilen metindeki her sayı `DecisionCandidate.izinli_sayilar()` kümesinde yok ise çıktı
reddedilir (`app/llm/guard.py`). 1B modeli üretime uygun kılan tek en önemli bileşen budur.

**2. ERP asla LLM'i beklemez.**
Karar kural motorundan milisaniyelerde çıkar; LLM yalnızca açıklama metnini yazar
(CPU'da ~6-8 sn). Bu yüzden `?gerekce=true` **varsayılan değil**: karar yolu LLM'e hiç
bağımlı değildir.

---

## Kurulum

Ön koşul: [uv](https://docs.astral.sh/uv/) ve git.

> ⚠️ **Bu makinelerde C: sürücüsünde ~3 GB boş yer var.** Önbellekler D:'ye yönlendirilmeden
> çalışmaya başlamayın — Qwen2.5-1.5B'nin indirmesi tek başına C:'yi doldurur.

```powershell
[Environment]::SetEnvironmentVariable("UV_CACHE_DIR","D:\ERP\.cache\uv","User"); [Environment]::SetEnvironmentVariable("HF_HOME","D:\ERP\.cache\huggingface","User"); [Environment]::SetEnvironmentVariable("PIP_CACHE_DIR","D:\ERP\.cache\pip","User"); [Environment]::SetEnvironmentVariable("TORCH_HOME","D:\ERP\.cache\torch","User"); [Environment]::SetEnvironmentVariable("UV_PYTHON_INSTALL_DIR","D:\ERP\.cache\uv-python","User")
```

Terminali kapatıp yeniden açın, sonra:

```bash
uv sync
```

```bash
cp .env.example .env
```

## Çalıştırma

```bash
uv run uvicorn app.main:app --reload
```

Sonra <http://127.0.0.1:8000/docs>

```bash
uv run pytest
```

```bash
uv run ruff check .
```

---

## Dizin haritası ve sahiplik

Her yer tutucu modülün docstring'inde **sahibi ve fazı** yazılıdır.

| Yol | Sahip | Ne işe yarar |
|-----|-------|--------------|
| `app/contracts.py` | **ortak · DONDURULMUŞ** | Kişi A ile B arasındaki sınır. Tek taraflı değiştirilmez. |
| `app/core/policy.py` | Kişi B | Eşikli otonomi: risk skoru → oto-uygula / onay kuyruğu |
| `app/core/config.py` | Kişi B | Tüm eşikler ve bağlantılar. Kodda sabit eşik yok. |
| `app/core/audit.py` | Kişi B | Denetim kaydı. **Denetim kaydı olmayan karar yolu merge edilmez.** |
| `app/api/` | Kişi B | REST arayüzü, onay kuyruğu, geri bildirim |
| `app/llm/` | Kişi B | Ollama istemcisi, router, gerekçe, **guard** |
| `app/domain/stock/` | Kişi A | Kural motoru (ROP, EOQ, ABC/XYZ, ölü stok) + ML |
| `simulator/` | Kişi A | Sanal KOBİ simülasyonu — eğitim verisinin kaynağı |
| `training/` | A veri · B eğitim | Veri seti üretimi, LoRA, GGUF, benchmark |

## Otonomi kademeleri

`.env` içindeki `AUTONOMY_LEVEL` ile seçilir. Sıra bu şekilde ilerler, **atlanmaz**:

| Kademe | Davranış |
|--------|----------|
| `shadow` | Karar verir, kaydeder, **hiçbir şey uygulamaz.** Başlangıç modu. |
| `advisory` | Öneri + gerekçe gösterir, uygulamayı insan yapar |
| `threshold` | Eşik altını kendi uygular, üstünü onay kuyruğuna alır |
| `off` | Kill switch — endpoint 503 döner |

`shadow` modda ölçülmüş doğruluk raporu olmadan `threshold`'a geçilmez.
Bu teknik değil, süreç kararıdır — `tests/test_policy.py` bunu sınar.

## Çalışma disiplini

- `main`'e direkt push yok; her adım kendi branch'inde (`a/...`, `b/...`)
- **Her PR'ı diğer kişi inceler.** Kalite kontrolü değil, öğrenme mekanizması —
  böylece ikiniz de sistemin tamamını tanırsınız.
- `uv run pytest` ve `uv run ruff check .` geçmeden merge yok

## Dokümantasyon

| Dosya | Kim okur |
|-------|----------|
| [dokumantasyon/KISI-A-GOREV.md](dokumantasyon/KISI-A-GOREV.md) | **Kişi A** — kendi başına yeterli görev dosyası (kurulum + adım adım liste) |
| [dokumantasyon/KISI-B-GOREV.md](dokumantasyon/KISI-B-GOREV.md) | **Kişi B** — kendi başına yeterli görev dosyası (kurulum + adım adım liste) |
| [dokumantasyon/YOL-HARITASI.md](dokumantasyon/YOL-HARITASI.md) | **İkisi** — mimari kararlar, buluşma noktaları, takvim, riskler |

Yeni katılan kişi yalnızca kendi görev dosyasını okuyarak başlayabilir.

## Durum

**Faz 0 tamam** — sözleşme donduruldu, stub'lı uçtan uca akış çalışıyor (25 test yeşil).
Sıradaki: Faz 1 — Kişi A simülatörü, Kişi B veri katmanı + API'yi paralel yazar.
