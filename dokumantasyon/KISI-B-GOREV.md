# Kişi B — Servis & Model · Görev Dosyası

> Bu dosya kendi başına yeterlidir. Projeyi hiç bilmiyorsan baştan sonuna oku,
> sonra "Hemen başla" bölümündeki komutları çalıştır.

---

## 1. Ne yapıyoruz?

Codifya ERP'ye bir **yapay zekâ karar mekanizması** kuruyoruz. Sistem stok, finans,
satış ve üretim alanlarında karar üretecek; düşük riskli olanları kendi uygulayacak,
yükseklerini insan onayına düşürecek.

**Kritik tasarım kısıtı:** Elimizde 16 GB RAM'li, GPU'suz bilgisayarlar var. Bu yüzden
1B parametreli küçük bir dil modeli kullanacağız (Qwen2.5-1.5B-Instruct). Ama 1B model
**sayısal karar veremez** — emniyet stoğu, marj, risk hesaplarında uydurma yapar.
Bu yüzden mimari hibrit:

```
Sayısal kararı   →  KURAL MOTORU + küçük ML     ←  Kişi A'nın işi
Türkçe metni     →  1B LLM                       ←  SENİN İŞİN
Servis, politika, denetim, eğitim hattı           ←  SENİN İŞİN
```

**Senin işin sistemin dil ve yetki katmanı.** LLM'in sayı uydurmasını engelleyen
mekanizmayı sen yazacaksın — projenin en kritik bileşeni o.

---

## 2. Senin sahiplendiğin dosyalar

| Dosya | Durum | Ne yapacak |
|-------|-------|-----------|
| `app/core/config.py` | ✅ yazıldı | Tüm eşikler ve bağlantılar |
| `app/core/policy.py` | ✅ yazıldı | Eşikli otonomi (DB tablosuna taşınacak) |
| `app/api/decisions.py` | ✅ yazıldı | Karar endpoint'i (stub veriyle) |
| `app/llm/explain.py` | ⚠️ kısmi | Şablon gerekçe var, LLM yok |
| `app/models/` | ⛔ boş | SQLAlchemy tabloları |
| `app/core/db.py` | ⛔ boş | Session factory |
| `app/core/audit.py` | ⛔ boş | Denetim kaydı |
| `app/api/approvals.py` | ⛔ boş | Onay kuyruğu |
| `app/api/feedback.py` | ⛔ boş | İnsan geri bildirimi |
| `app/api/insights.py` | ⛔ boş | Gecelik bulgular |
| `app/api/ask.py` | ⛔ boş | Doğal dil → araç çağrısı |
| `app/llm/client.py` | ⛔ boş | Ollama istemcisi |
| `app/llm/schemas.py` | ⛔ boş | Yapılandırılmış çıktı şemaları |
| `app/llm/router.py` | ⛔ boş | Niyet → araç seçimi |
| `app/llm/guard.py` | ⛔ boş | **Sayısal doğrulama guard'ı** ⭐ |
| `app/jobs/nightly.py` | ⛔ boş | Gecelik tarama |
| `app/jobs/triggers.py` | ⛔ boş | Olay tetikleyicileri |
| `training/train_lora.ipynb` | ⛔ yok | LoRA eğitim notebook'u |
| `training/export_gguf.py` | ⛔ boş | GGUF dönüşümü |
| `training/eval/benchmark.py` | ⛔ boş | Değerlendirme |

**Hiç dokunmayacağın yerler:** `simulator/`, `app/domain/stock/`,
`training/build_dataset.py`, `training/label_rationale.py`. Bunlar Kişi A'nın.
Stok formüllerine veya talep simülasyonuna karışma.

**Öğreneceğin şeyler:** FastAPI, pydantic, SQLAlchemy, pytest, Ollama,
HuggingFace + peft/Unsloth, llama.cpp/GGUF, Google Colab (ücretsiz T4).

**Nerede çalışacaksın:** kod, servis, testler **yerelde** (`uv` + FastAPI + Ollama);
yalnızca GPU gerektiren eğitim adımları **Colab'da**. Faz 3'e kadar Colab'a hiç
ihtiyacın yok.

---

## 3. Mimariyi ayakta tutan iki kural

Kod yazarken bu ikisini akılda tut; tasarımın geri kalanı bunların sonucudur.

### Kural 1 — LLM asla sayı üretmez

Sayılar prompt'a kural motorundan **verilir**, model onları yalnızca cümleye yerleştirir.
Üretilen metindeki her sayı `DecisionCandidate.izinli_sayilar()` kümesinde yok ise
çıktı **reddedilir**.

`app/contracts.py`'de bu metot hazır — özellikler + kural değerleri + aksiyondan,
gerekçede geçmesine izin verilen sayıların tam kümesini çıkarıyor. Senin yazacağın
`guard.py` tam olarak bu kümeyi kullanacak.

Üç kademeli koruma:
1. **Şema zorlaması** — Ollama'nın `format` parametresine JSON şeması geç
2. **Sayısal guard** — metindeki her sayıyı izinli kümeyle karşılaştır
3. **Şablon geri dönüşü** — 2 denemede geçemezse `explain.sablon_gerekce()`'ye düş

Üçüncü kademe zaten yazılı. Yani **karar hiçbir koşulda bloke olmuyor.**

### Kural 2 — ERP asla LLM'i beklemez

Karar kural motorundan **milisaniyelerde** çıkar. LLM yalnızca açıklama metnini yazar
(CPU'da ~6-8 sn). Bu yüzden endpoint'te `?gerekce=true` **varsayılan değil** —
karar yolu LLM'e hiç bağımlı değil.

Bu, gecelik iş tasarımını da belirliyor: 2.000 SKU × 7 sn = 4 saat olurdu. Gerekçe
yalnızca insanın gerçekten baktığı ilk N karar için üretilir, gerisi kuyrukta bekler.

---

## 4. Hemen başla

### 4.1 · Ortam kurulumu (kendi PC'nde, bir kez)

> ⚠️ **Bu adımı atlamayın.** Bu makinelerde C: sürücüsünde ~3 GB boş yer var.
> Qwen2.5-1.5B'nin HuggingFace indirmesi tek başına ~3,1 GB. Varsayılan ayarlarla
> ilk günde disk dolar ve nedeni anlaşılmaz hatalar alırsınız.

PowerShell'de:

```powershell
[Environment]::SetEnvironmentVariable("UV_CACHE_DIR","D:\ERP\.cache\uv","User"); [Environment]::SetEnvironmentVariable("HF_HOME","D:\ERP\.cache\huggingface","User"); [Environment]::SetEnvironmentVariable("PIP_CACHE_DIR","D:\ERP\.cache\pip","User"); [Environment]::SetEnvironmentVariable("TORCH_HOME","D:\ERP\.cache\torch","User"); [Environment]::SetEnvironmentVariable("UV_PYTHON_INSTALL_DIR","D:\ERP\.cache\uv-python","User")
```

Ollama modelleri de D:'de olsun:

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS","D:\OllamaModels","User")
```

Terminali **kapat, yeniden aç**, doğrula:

```powershell
$env:UV_CACHE_DIR; $env:HF_HOME; $env:OLLAMA_MODELS
```

### 4.2 · Projeyi al ve çalıştır

```bash
git clone <repo-url> D:/ERP/codifya-decision-engine
```

```bash
cd /d/ERP/codifya-decision-engine && uv sync && cp .env.example .env
```

```bash
uv run pytest
```

25 test geçmeli.

```bash
uv run uvicorn app.main:app --reload
```

<http://127.0.0.1:8000/docs> → `POST /v1/decisions/stock/reorder-review` dene.
`?gerekce=true` ile de dene. Şu an dönen karar Kişi A'nın `decide_stub()`'ı —
sabit veri. Senin işin etrafındaki her şeyi gerçek yapmak.

### 4.3 · Faz 0'da hazır olanı oku (30 dk)

Sırayla:
1. `app/contracts.py` — **sözleşme, dondurulmuş.** Özellikle `izinli_sayilar()`
2. `app/core/policy.py` — eşikli otonomi. `sonuc` ve `uygulandi` neden ayrı, oku
3. `app/core/config.py` — kodda sabit eşik yok, hepsi burada
4. `tests/test_policy.py` — otonomi kademelerinin nasıl test edildiği
5. `app/llm/explain.py` — `sablon_gerekce()` senin guard'ının geri dönüş noktası

---

## 5. Görev listesi

Süreler günde ~4-6 verimli saat varsayıyor, öğrenme dahil.
Her adım kendi branch'inde: `git checkout -b b/models-sqlalchemy` gibi.

### FAZ 1 — Veri katmanı + API + politika (~10 gün)

---

#### B1.1 · `app/models/` — SQLAlchemy tabloları · 2 gün

**Yapılacak:** Tablolar:
- `decision` — karar kaydı
- `decision_audit` — girdi hash'i, tetiklenen kurallar, model sürümleri, guard sonucu
- `approval` — onay kuyruğu
- `feedback` — onay/red/düzeltme
- `policy` — eşik tablosu (kodda gömülü olmayacak)
- `insight` — gecelik bulgular

**Öğrenmen gereken:** SQLAlchemy 2.0 declarative sözdizimi (`Mapped`,
`mapped_column`), ilişkiler, JSON kolon tipi.

> Veritabanı **SQLite** — Docker/Postgres kullanmıyoruz. Sebebi C:'de 3 GB
> kalması ve iki yeni başlayanın öğrenme yükünü artırmamak. SQLAlchemy kullandığımız
> için Postgres'e geçiş `config.py`'deki tek satır.

**Bitti sayılır:** `alembic upgrade head` SQLite dosyasını oluşturuyor; her tabloya
elle bir satır yazıp okuyabiliyorsun.

---

#### B1.2 · `app/core/db.py` — DB katmanı · 1 gün

**Yapılacak:** Engine + session factory + FastAPI dependency.

⚠️ `config.py`'deki `database_url` varsayılanı `data/codifya.db`. Temiz klonda
`data/` dizini var (`.gitkeep` sayesinde) ama yine de engine oluşturmadan önce
dizini garanti et.

**Bitti sayılır:** endpoint'ten DB session alınıp bir kayıt yazılabiliyor.

---

#### B1.3 · `app/core/audit.py` — Denetim kaydı · 1 gün

**Yapılacak:** Tek çağrıyla tam denetim satırı yazan fonksiyon:
- girdi anlık görüntüsünün SHA-256'sı
- tetiklenen kurallar
- model sürümleri (`aday.model_surumleri`)
- çıktı
- guard sonucu
- zaman damgası

**Bitti sayılır:** karar akışı çalıştığında `decision_audit` tablosunda eksiksiz satır.

> **Kural: denetim kaydı olmayan bir karar yolu asla merge edilmez.** Bu alışkanlık
> baştan yerleşmeli — sonradan eklemek çok daha zor ve eksik kalır.

---

#### B1.4 · `policy.py`'yi DB'ye taşı · 1 gün

Mantık **zaten yazılı** ve testli. Yapılacak: eşikleri `config.py` yerine `policy`
tablosundan oku, alan bazlı (`stok.siparis`, `stok.tasfiye`) satırlar olsun.

Mevcut testler (`tests/test_policy.py`) geçmeye devam etmeli.

---

#### B1.5 · API endpoint'leri · 2 gün

**Yapılacak:**
- `GET /v1/approvals` — kuyruk listesi
- `POST /v1/approvals/{id}` — onayla / reddet / düzelt
- `POST /v1/feedback`
- `GET /v1/insights`

Kararlar artık DB'ye yazılsın; `decisions.py` da kayıt atsın.

**Bitti sayılır:** `/docs` üzerinden onay kuyruğunun **tam turu** elle yapılabiliyor:
karar üret → kuyrukta gör → reddet → `feedback` tablosuna düştüğünü doğrula.

---

#### B1.6 · CI · 1 gün

**Yapılacak:** GitHub Actions workflow: `uv sync` + `uv run ruff check .` +
`uv run pytest`.

**Bitti sayılır:** PR açıldığında CI otomatik koşup yeşil/kırmızı gösteriyor.
`main` branch protection ile birleşince "main her zaman yeşil" kuralı kendiliğinden
zorunlu olur.

> **🔗 Buluşma noktası (SP1):** Kişi A sana simülasyon verisini ve kalite notebook'unu
> gösterir (verinin mantıklı olduğunu onaylaman gerekiyor), sen ona onay kuyruğu
> turunu gösterirsin.

---

### FAZ 2 — LLM katmanı (~10 gün)

---

#### B2.1 · Model kurulumu + istemci · 1,5 gün

**Yapılacak:**

```bash
ollama pull qwen2.5:1.5b-instruct
```

Modelin `D:\OllamaModels`'e indiğini doğrula (C: dolmasın).

`app/llm/client.py`: Ollama HTTP istemcisi — timeout, retry, **token/süre ölçümü**.

**Neden Qwen2.5-1.5B (Llama 3.2 1B değil):** 1B sınıfında Türkçesi ve yapılandırılmış
JSON üretimi belirgin şekilde daha iyi, ayrıca Apache-2.0 lisansı ticari kullanıma
uygun (Llama lisansı ek şart getiriyor).

**Bitti sayılır:** Türkçe bir prompt'a cevap alıyorsun **ve saniyedeki token sayısını
ölçüp bir yere yazmışsın.** Bu sayı Faz 4'te mimari kararları belirleyecek — şimdi
ölçmezsen sonra tahmin etmek zorunda kalırsın.

---

#### B2.2 · `schemas.py` — Yapılandırılmış çıktı · 1,5 gün

**Yapılacak:** Router ve gerekçe çıktıları için pydantic şemaları. Ollama'nın `format`
parametresine `model_json_schema()` geçirerek JSON zorlaması. Şema uymadığında yeniden dene.

**Bitti sayılır:** 20 ardışık çağrının 20'si de geçerli JSON döndürüyor.

> Dönmüyorsa çözüm "daha çok prompt yazmak" değil — llama.cpp'nin GBNF grammar
> desteğine geçmek. Bu yedek planı baştan bil, prompt'la boğuşarak gün kaybetme.

---

#### B2.3 · `router.py` — Niyet → araç · 2 gün

**Yapılacak:** Türkçe soru → `{"tool": "...", "params": {...}}`.
**Henüz eğitim yok** — few-shot örneklerle çalışır. Bilinen araç listesi + parametre
doğrulaması; model olmayan bir araç uydurursa reddet.

**Bitti sayılır:** elle yazdığın **30 Türkçe soruluk** test setinde doğruluk ölçülmüş
ve dosyaya kaydedilmiş.

> Bu sayı zorunlu: Faz 3'te LoRA eğitiminin işe yarayıp yaramadığını ancak buna
> kıyaslayarak anlayabilirsin. Şimdi ölçmezsen "eğitim işe yaradı mı" sorusunun
> cevabı kalıcı olarak kaybolur.

---

#### B2.4 · `explain.py` — Gerçek gerekçe üretimi · 1,5 gün

`sablon_gerekce()` zaten yazılı ve kalacak. Yapılacak: LLM ile gerçek gerekçe.

Prompt'ta sayılar **açıkça etiketli** verilir ve modele "yalnızca verilen sayıları
kullan" talimatı geçilir. Hedef çıktı:

> *"Son 30 günde günlük ortalama 42 adet tüketim var, tedarik süresi 12 gün ve elde
> 310 adet kaldı. Yeniden sipariş noktası 615 adedin altına düşüldüğü için 1.200 adet
> sipariş öneriliyor; Yılmaz Yapı son 6 ayda %94 zamanında teslim yaptığı için
> tedarikçi olarak seçildi."*

**Bitti sayılır:** 10 gerçek karar için üretilen gerekçeleri okuduğunda Türkçesi
anlaşılır ve sayılar doğru.

---

#### B2.5 · ⭐⭐ `guard.py` — Sayısal doğrulama · 2 gün

**Projenin en kritik 200 satırı.** Bu olmadan sistem üretime çıkamaz.

**Yapılacak:**
1. `aday.izinli_sayilar()` ile izinli sayı kümesini al (metot hazır)
2. Üretilen metindeki tüm sayıları regex ile yakala — **Türkçe biçimler:**
   `1.200` (binlik ayracı nokta), `4,75` (ondalık virgül), `%94`, `5.000 TL`
3. Her sayı izinli kümede (makul yuvarlama toleransıyla) yok ise **reddet**
4. Reddedilirse **1 kez** yeniden üret; yine geçmezse `sablon_gerekce()`'ye düş
5. Sonucu (`GECTI` / `YENIDEN_URETILDI` / `SABLONA_DUSTU`) **daima** denetim kaydına yaz

`GuardSonucu` enum'u `contracts.py`'de hazır.

**Bitti sayılır:** `tests/test_guard.py` —
- bağlamda olmayan sayı içeren elle yazılmış metinler **hepsi** reddediliyor
- geçerli metinler geçiyor
- Türkçe binlik ayracı ve yüzde biçimleri doğru ayrıştırılıyor

> ⚠️ **Bu guard'ı Kişi A da kullanacak** — eğitim verisi etiketlemesinde (A3.4).
> Yani halüsinasyon hem çalışma zamanında hem eğitim verisinde kesiliyor.
> Ona sade, çağrılabilir bir fonksiyon arayüzü bırak.

---

#### B2.6 · `jobs/` — Gecelik iş + tetikleyiciler · 2 gün

**`nightly.py`:** tüm SKU'ları tara, kararları üret, önem sırasına diz,
**yalnızca üst N tanesi için** gerekçe üret (`config.gecelik_gerekce_ust_n`),
`insight` tablosuna yaz.

**`triggers.py`:** büyük sipariş / kritik stok / limit aşımı olaylarında anında tetikleme.

**Bitti sayılır:** `uv run python -m app.jobs.nightly` 2.000 SKU'yu tarayıp Türkçe
içgörü listesi üretiyor ve **toplam süre 10 dakikanın altında.**

> **🔗 Buluşma noktası (SP2):** Kişi A'nın gerçek `decide.py`'si bağlanır, stub'lar
> silinir. Sistem `shadow` modda gerçek veri üzerinde gerçek karar verip Türkçe
> gerekçelendiriyor. **Bu noktada LoRA eğitimi hiç yapılmamış olsa bile sistem çalışıyor.**

---

### FAZ 3 — LoRA eğitimi · Google Colab (ücretsiz) (~8 gün)

---

#### B3.1 · Colab ortamı (ücretsiz) · 1 gün

**Yapılacak:** `training/train_lora.ipynb` — Colab'da açılacak notebook.

`Runtime → Change runtime type → T4 GPU` seç. Sonra:

```python
!nvidia-smi
```

**Ücretsiz Colab'ın bilmen gereken üç kısıtı** — bunlar eğitim tasarımını belirliyor:

| Kısıt | Sonucu |
|-------|--------|
| **Tek T4** (Kaggle'da 2 tanedir) | Eğitim daha yavaş: ~55k örnek için 4-7 saat |
| **Oturum kopuyor** — ~90 dk hareketsizlikte, toplam ~12 saatte kesin | 4-7 saatlik tek koşu **büyük olasılıkla yarıda kesilir** |
| **`/content` uçucu** | Oturum kapanınca dosyalar gider; model, veri, checkpoint **Drive'da** durmalı |

Bu yüzden eğitimi **tek koşu değil, kaldığı yerden devam edebilen bölünebilir bir
süreç** olarak kuracaksın. Bu bir çözüm değil, zorunluluk.

**Notebook'un ilk hücresi her oturumda çalışacak** (Colab her açılışta sıfırlanır):

```python
from google.colab import drive
drive.mount('/content/drive')
```

```python
!pip install -q unsloth
```

Drive'da şu düzeni kur:

```
/content/drive/MyDrive/codifya/
  veri/         ← Kişi A'nın JSONL dosyaları (bir kez yükle, her oturumda kullan)
  checkpoint/   ← eğitim ara kayıtları (oturum kopunca buradan devam)
  cikti/        ← merge edilmiş model + GGUF
```

> ⚠️ **Veriyi her oturumda yeniden yükleme.** Kişi A'nın ürettiği ~55k örneklik JSONL
> Drive'a bir kez konur, notebook oradan okur. Yerel yükleme her oturumda 10-20 dakika
> yakar ve kopma riskini artırır.

**Bitti sayılır:**
1. `nvidia-smi` T4 gösteriyor
2. Drive bağlı, `unsloth` import ediliyor
3. Drive'daki `veri/` klasöründen bir dosya okunabiliyor

---

#### B3.2 · ⭐ 100 örnekle boru hattı kanıtı · 1 gün

**Bu adımı atlama.**

Kişi A'nın ürettiği **100 örneklik** küçük bir örnekle tüm hattı baştan sona çalıştır:
yükle → eğit (2 dk) → kaydet → merge → GGUF → Ollama → cevap al.

**Neden:** tam eğitim 4-7 saat sürüyor ve ücretsiz Colab'da oturum kopabiliyor. Hattın
3. saatinde çıkacak bir biçim hatası, hem 3 saati hem de bir Colab oturumunu yakar.
Küçük veriyle hattı kanıtlamak, bu işte en yüksek getirili tek alışkanlık.

**Bitti sayılır:** 100 örnekle eğitilmiş (kalitesi berbat ama çalışan) bir model
yerelde Ollama'da cevap veriyor. **Yani `.gguf` dosyası yerel diskine inmiş ve
`ollama run` ile Türkçe bir cevap üretmiş.**

---

#### B3.3 · Tam LoRA eğitimi · 2-3 gün (çoğu bekleme)

**Yapılacak:** Qwen2.5-1.5B-Instruct + LoRA, Unsloth ile:
- `r=16`, `alpha=32`
- hedef modüller: tüm dikkat + MLP projeksiyonları
- `max_seq_length=1024` — gerekçe prompt'ları kısa, daha uzunu boşa VRAM ve süre yakar

Router ve gerekçe görevlerini **tek modelde birlikte** eğit (görev etiketiyle
ayrıştırılır). İki ayrı model yönetmek 16 GB'lık makinede gereksiz yük.

##### Ücretsiz Colab için eğitim stratejisi

Oturum kopmasını bir **hata** değil, **beklenen durum** olarak ele al.

**1. Checkpoint'i Drive'a yaz, sık yaz:**

```python
TrainingArguments(
    output_dir="/content/drive/MyDrive/codifya/checkpoint",
    save_steps=200,          # sık kaydet — kopma her an olabilir
    save_total_limit=2,      # Drive'ı doldurmasın
    ...
)
```

**2. Kaldığı yerden devam et.** Oturum koptuğunda notebook'u yeniden aç, ilk hücreleri
çalıştır ve:

```python
trainer.train(resume_from_checkpoint=True)
```

Bu satır olmadan her kopma seni başa döndürür. **Önce bunun çalıştığını doğrula:**
eğitimi başlat, 300 adım sonra kasten durdur (Runtime → Interrupt), sonra
`resume_from_checkpoint=True` ile devam ettir ve adım sayacının kaldığı yerden
saydığını gör. Bu 15 dakikalık test, sonraki günlerde saatler kazandırır.

**3. Küçükten büyüğe git.** 55k örnekle başlama:

| Tur | Örnek | Süre | Amaç |
|-----|-------|------|------|
| 1 | ~15k | ~1,5 saat | Tek oturumda biter. Router doğruluğunu ölç. |
| 2 | ~35k | ~3-4 saat | İyileşme var mı? Varsa devam mantıklı. |
| 3 | ~55k | ~5-7 saat | Ancak 2. tur iyileşme gösterdiyse. |

> 1. turdan 2. tura kayda değer iyileşme yoksa **veri miktarı senin darboğazın değil** —
> veri *kalitesi* öyle. O zaman Kişi A ile A3.4'ün guard reddedilme oranına bakın.
> Daha çok veriyle daha uzun beklemek, kötü veriyi düzeltmiyor.

**4. Sekmeyi açık tut.** Ücretsiz Colab ~90 dakika hareketsizlikte oturumu kapatır.
Tarayıcı sekmesini kapatmayın; eğitim koşarken makineyi uyutmayın.

**Öğrenmen gereken:**
- LoRA nedir: tüm ağırlıkları değil, küçük ek matrisleri eğitmek — bu yüzden 1,5B model
  tek T4'e sığıyor
- `r` ve `alpha` ne yapar
- Aşırı öğrenmeyi (overfitting) doğrulama kaybından okumak: eğitim kaybı düşerken
  doğrulama kaybı yükselmeye başlarsa dur

**Bitti sayılır:** doğrulama kaybı düşüp yatay seyre geçmiş; LoRA adaptörü
Drive'daki `cikti/` klasöründe.

---

#### B3.4 · Merge + GGUF + Ollama · 1,5 gün

**Ağır işin tamamı Colab'da yapılır, yerele sadece bitmiş dosya iner.** Sınır burada:

| Adım | Nerede | Neden |
|------|--------|-------|
| LoRA'yı temel modele merge et | **Colab** | 3,1 GB'lık temel modeli indirmek + RAM işi |
| `llama.cpp` ile GGUF'a çevir | **Colab** | Windows'ta llama.cpp derlemek zahmetli, Colab'da hazır |
| **Q4_K_M** kuantize et (~1,1 GB) | **Colab** | Aynı sebep |
| GGUF'u indir | **yerel** | Tek dosya, ~1,1 GB |
| `Modelfile` + `ollama create` | **yerel** | Servis burada koşuyor |

> Bu ayrım sayesinde 3,1 GB'lık temel modeli hiç yerele indirmen gerekmiyor.
> Sadece 1,1 GB'lık bitmiş GGUF iniyor.

GGUF'u Drive'daki `cikti/` klasörüne yaz, oradan indir — Colab'ın kendi indirme
bağlantısı kopabilir, Drive daha güvenilir.

Yerelde son adım:

```bash
ollama create codifya-karar:v1 -f Modelfile
```

`Modelfile` içinde sistem promptu ve parametreler (`temperature`, `num_ctx`) sabitlenir —
böylece kod tarafında her çağrıda tekrarlanmaz.

**RAM bütçesi kontrolü:** model 1,2 GB + KV cache 0,3 GB + FastAPI/pandas ~1 GB +
SQLite ~0,2 GB ≈ **3 GB.** 16 GB'ta rahat.

**Bitti sayılır:** `ollama run codifya-karar:v1` çalışıyor, dosya `D:\OllamaModels`'de,
**C: dolmadı** (`Get-PSDrive C` ile kontrol et).

---

#### B3.5 · Ölçüm · 1 gün

**Yapılacak:** token/sn, ilk token gecikmesi, tepe RAM. B2.3'teki 30 soruluk router
taban çizgisini **yeniden koştur** ve karşılaştır.

**Bitti sayılır:** "LoRA öncesi %X → sonrası %Y" şeklinde somut bir sayı var.

> İyileşme yoksa bu bir başarısızlık değil, bir **bulgu**. Veri kalitesine bak
> (Kişi A'nın A3.4'teki guard reddedilme oranı). Sonucu olduğu gibi raporla.

> **🔗 Buluşma noktası (SP3):** `.env`'de model adını `codifya-karar:v1` yap, tüm
> sistemi koştur. **Guard reddedilme oranının düştüğünü** doğrula — eğitim işe
> yaradıysa model artık sayı uydurmayı daha az deniyor.

---

### FAZ 4-5 — Senin payın (~5 gün)

- **4.1** Hata yönetimi, timeout. **LLM çökerse kural motoru tek başına devam etmeli**
  (graceful degradation)
- **4.3** `shadow` mod raporu: sistemin kararı vs vasat taban politika, tablo halinde
- **4.5** Basit onay ekranı — minimal HTML/HTMX yeter, **React'a girme**
- **4.6** ERP entegrasyon sözleşmesi dokümanı (ERP stack'i hâlâ seçilmemiş olabilir,
  doküman yeter)
- **5** `training/eval/benchmark.py`:

| Metrik | Hedef |
|--------|-------|
| Router: araç + parametre tam eşleşme | > %95 |
| Gerekçe: uydurma sayı | **0 — sert kapı** |
| Gerekçe: Türkçe akıcılık | LLM-jüri puanı |
| Gecelik tarama süresi | < 10 dk |
| Tepe RAM | < 4 GB |

> **⚠️ `shadow` modda ölçülmüş doğruluk raporu olmadan `threshold`'a ASLA geçilmez.**
> Bu teknik değil, süreç kararı. Projenin güvenlik kapısı bu ve bekçisi sensin.

---

## 6. Çalışma disiplini

| Ne | Nasıl |
|----|-------|
| **Günlük senk** | Her sabah 15 dk, Kişi A ile: "bugün ne yapıyorum / neye takıldım / senden ne bekliyorum" |
| **Branch** | Her adımda yeni: `b/api-approvals`, `b/llm-guard` |
| **PR** | `main`'e direkt push YOK. PR aç, **Kişi A onaylamadan merge etme** |
| **PR incelemesi** | Sen de onun PR'larını incele. Bu kalite kontrolü değil, öğrenme — ikiniz de tüm sistemi tanıyın |
| **Merge öncesi** | `uv run pytest` ve `uv run ruff check .` geçmeli |

```bash
uv run pytest && uv run ruff check .
```

## 7. Takıldığında

1. **`app/contracts.py`** — tüketeceğin nesnelerin tanımı, özellikle `izinli_sayilar()`
2. **`app/core/policy.py`** — çalışan referans örnek: config'den okuma, testli mantık
3. **`tests/test_policy.py`** — test yazma kalıbı
4. Her yer tutucu dosyanın docstring'inde **kimin, hangi fazda** yazacağı belirtilmiş
5. Sözleşmede eksik bir alan varsa **kendi başına ekleme** — Kişi A ile konuş,
   tek PR'da birlikte ekleyin

---

# TUR 8 — Bağımsız iş paketi B (Servis & Model)

> Yazıldı: 2026-08-10, Faz 7 bitiminde. **Bu paketteki hiçbir madde A
> paketinden bir çıktı beklemiyor.** Sıra serbest, paralel çalışılabilir.

## Dosya sahipliği (çakışma önleme)

| B'nin sahası | A'nın sahası |
|---|---|
| `app/api/**` | `app/domain/**` |
| `app/core/**` | `app/adapters/**` |
| `app/llm/**` | `simulator/**` |
| `app/jobs/**` | `app/contracts.py` *(bu tur A'da)* |
| `training/**` (veri üretimi dâhil) | — |

⚠️ Bu turda B'nin **sözleşmeye dokunan işi yok**. `app/contracts.py`'de bir
şey gerekiyorsa dur ve A ile konuş — tek taraflı değiştirme.

⚠️ Kural motorunun davranışı bu tur **sabit**. B'nin tüm işleri mevcut
karar çıktısını tüketiyor, üretmiyor.

## ⚠️ Colab çalışmıyorsa bloke DEĞİLSİN

Depoda Colab'a bağlı tek dosya `training/b34_gguf_colab.ipynb` — yani
**yeni bir LoRA turu + GGUF dışa aktarımı**. Başka hiçbir iş ona bağlı
değil:

| iş | Colab gerekir mi |
|---|---|
| B1 finans API çoğul karar | hayır |
| B2 onay kuyruğu gruplama | hayır |
| B3 kişi bazlı yetki | hayır |
| B4 üretim sertleştirmesi | hayır |
| B5 **ölçüm yarısı** (guard reddedilme oranı) | **hayır** |
| B5 **eğitim yarısı** (tur6) | evet |
| B6 gecelik iş + benchmark | hayır |

`training/codifya-tur2..tur5-q8_0.gguf` zaten diskte; canlı model (tur5)
etkilenmiyor, Ollama yerelde çalışıyor.

**Sıra önerisi:** B5'in ölçüm yarısını önce koştur. Sonuç "guard finans
gerekçelerini kabul ediyor" çıkarsa **tur6 hiç gerekmez** ve Colab sorunu
konu dışı kalır. Ölçüm ucuz, eğitim turu pahalı.

Colab kalıcı olarak çözülmezse ve tur6 gerçekten gerekliyse, `training/**`
sahipliği komple A'ya devredilir — **yarısı sende yarısı onda kalmaz**, iki
paketin bağımsızlığı buna bağlı. Devir kararını Melih verecek.

---

## B1 — Finans API'si çoklu kararı yansıtmıyor ✅ ÇÖZÜLDÜ (Kişi B, 2026-08-10)

Faz 7'de `ozellikten_kararlar_uret` liste döndürür oldu: bir müşteri aynı
anda karşılık + takip kararı alabiliyor (`BILINEN-EKSIKLER.md` §9).

**Ama HTTP ucu hâlâ tek karar döndürüyor.** `app/api/decisions.py`
`finans_karari_uret` çağırıyor, o da listenin yalnızca **birincisini**
veriyor. Yani ERP, batık bir müşteri için karşılık kararını görüyor ama
aynı müşterinin tahsilat takibi kararını **hiç görmüyor**.

Bu, düzeltilen kusurun API katmanında hâlâ yaşayan hâli.

**Yapılacak:** finans ucu karar **listesi** döndürmeli. `KararSonucu` tekil;
ya liste döndüren yeni bir cevap tipi ya da mevcut ucun çoğullaştırılması.
Sürüm kırılımı olacaksa `ERP-ENTEGRASYON.md`'ye yaz.

**Bitti sayılır:** üç kararı olan bir müşteri için API üçünü de döndürüyor,
testi var.

## B2 — Onay kuyruğu kalem bazında gruplanmalı ✅ ÇÖZÜLDÜ (2026-08-10)

Aynı değişikliğin ekran tarafı: bir müşteri kuyrukta 2-3 ayrı satır olarak
görünüyor, operatör bunların aynı müşteriye ait olduğunu göremiyor.

**Yapılacak:** `app/api/ui.py`'de `kalem_adi` (Faz 7'de eklendi) altında
gruplama. ⚠️ Kararları **birleştirme** — üçü ayrı, ayrı onaylanabilmeli.
Sorun sunum, veri modeli değil.

**Bitti sayılır:** üç kararlı müşteri tek başlık altında, üç ayrı onay
düğmesiyle. Kalıp: `tests/test_ui_finans.py`.

## B3 — Kişi bazlı yetki ✅ ÇÖZÜLDÜ (2026-08-10)

`BILINEN-EKSIKLER.md` §2'nin kalan sınırı. API anahtarı **sistemi**
doğruluyor, kişiyi değil: onay ekranındaki kutuya "genel müdür" yazan
herkes denetim kaydına öyle geçiyor.

**Yapılacak:** anahtar → (ad, rol) eşlemesi; `app/api/approvals.py`'de
`kullanici` alanı beyandan değil kimlikten gelsin.

**Bitti sayılır:** onay kaydındaki isim çağıran tarafından
değiştirilemiyor. Tutar eşiğine göre rol kısıtı (ör. 100k üstünü yalnızca
`yonetici`) ayrıca tartışılmalı — otonomi kademelerinin insan karşılığı bu.

## B4 — Üretim sertleştirmesi ✅ ÇÖZÜLDÜ (2026-08-10)

Kimlik doğrulama var, üretim kurulumunun geri kalanı denenmedi:

- `CEREZ_GUVENLI=true` ile TLS arkasında ekran çalışıyor mu?
- `/docs` ve `/openapi.json` korumasız — şema dışarı açılmalı mı?
- Hız sınırı yok; anahtar sızarsa sınırsız istek gider.
- `/health/db` kayıtlı karar sayısını anahtarsız veriyor — sorun mu?

**Bitti sayılır:** her madde için "şöyle çözüldü" ya da "şu yüzden kabul
edildi". Cevapsız madde kalmasın.

## B5 — Model finansı hiç görmedi ✅ ÇÖZÜLDÜ (tur6, 2026-08-10)

Gerekçe modeli yalnızca stok kararlarıyla eğitildi. Finans kararları için
gerekçe üretimi **hiç ölçülmedi**: guard finans sayılarıyla sınanmadı,
golden set'te finans örneği yok, LoRA turlarının hiçbirinde finans verisi
yoktu.

Canlıda finans kararı geldiğinde model tanımadığı bir girdi görüyor — Faz
7'de bulunan "eğitim/çalışma zamanı biçim uyuşmazlığı" ile aynı risk.

**Yapılacak (tam dikey, A'ya bağımlı değil):**
1. Finans kararlarından gerekçe eğitim verisi üret. `training/build_dataset.py`
   şu an yalnızca `app.domain.stock`'tan import ediyor; finans için
   genişlet — `app/domain/finance` fonksiyonlarını **çağırarak**,
   değiştirmeden. Dosya bu tur senin sahanda.

   ⚠️ **Önce ölç, sonra eğit.** `data/egitim/` altında sıfır finans örneği
   var (doğrulandı), ama bu "eğitim turu şart" demek değil: gerekçe üretimi
   büyük ölçüde "istemdeki sayıyı kopyala" işi ve stok için öğrenilen
   davranış finansa taşınmış olabilir. Mevcut tur5 modeliyle finans
   gerekçesi ürettirip **guard reddedilme oranını ölç**; düşükse yeni bir
   LoRA turu hiç gerekmeyebilir.

   Faz 7'de iki eğitim turu "modeli bozuyor" diye haksız yere geri alındı —
   bozuk olan ölçüm yoluydu. Eğitim turu pahalı; ölçüm ucuz.
2. Guard'ı finans sayılarıyla sına (`ORAN_ALANLARI`'na Faz 6'da finans
   oranları eklenmişti, doğrulanmadı).
3. Golden set'e finans örnekleri ekle, benchmark'ı yeniden koştur.

**Bitti sayılır:** "finans gerekçelerinde guard reddedilme oranı %X"
şeklinde bir sayı. Yüksekse bu bir bulgu, başarısızlık değil.

## B6 — Gecelik iş + benchmark yeniden ölçümü ✅ ÖLÇÜLDÜ (2026-08-10)

İki şey değişti ve ikisi de taramayı büyüttü: ikinci alan (finans) ve
müşteri başına çoklu karar. `gecelik_gerekce_ust_n = 25` tek alan / tek
karar varsayımıyla seçilmişti. Faz 5 hedefi hâlâ **< 10 dk** ve **< 4 GB**.

Aynı koşuda `BILINEN-EKSIKLER.md` §3'ü de kapat: router %75'te; hedefin
%95'te kalıp kalmayacağı yazılı bir karar bekliyor. §6 (golden set'te
`onay_kuyrugu_sorgula` ince, 4 örnek) bu turda B5 ile birlikte düzeltilir.

**Bitti sayılır:** ölçülmüş süre + RAM, gerekirse yeni
`gecelik_gerekce_ust_n`, ve router hedefi hakkında karar.

---

# FAZ 10 — Üretim Planlama · B paketi

> Tam plan: `dokumantasyon/FAZ-10-URETIM-PLANI.md`

## ✅ B10.1 — Tahmin çekirdeği + ölçüm — BİTTİ (`3ba8f5b`)

`app/forecast/`: donmuş sözleşme (`TalepTahmini`), naif tabanlar, üssel
düzleştirme, kayan başlangıçlı geriye dönük sınama. 15 test.

Bulgu: kataloğun %76'sı aralıklı talepli ve orada klasik model naif tabandan
%49 kötü. Rapor artık "tek bir yöntem her katmanda kazanmıyor" uyarısını
kendisi basıyor.

## ✅ B10.2 — Aralıklı talep için doğru model — BİTTİ (2026-08-11)

`app/forecast/aralikli.py`: Croston + SBA, 8 yeni test. Ölçüm hattına
katıldılar; `olcum.py` artık **ufuk toplamı** ve **bant kapsaması** da
raporluyor.

⚠️ **Bu iş iki taraf tarafından paralel yapıldı** (sahiplik tablosu tam
bunu önlemek için vardı, aynı gün ikinci kez oldu). Birleştirildi: kesme
penceresi düzeltmesi + yanlılık/sıfır oranı bir taraftan, ampirik bant +
bağıl hata/bant kapsama diğerinden.

### Bulgu 1 — ölçüm penceresi bulgunun kendisini üretiyordu

Croston +%91 yukarı yanlı çıktı; teoriye aykırıydı. Asıl sebep kodda değil
ölçümdeydi: kesmeler yalnızca serinin **son üç penceresinden** alınıyordu ve
o dönemde talep düşüktü, dolayısıyla HER yöntem yukarı yanlı görünüyordu
(`hareketli_ortalama` bile +%87). Kesmeler seriye yayılınca Croston %0'a
indi. `kesme_tarihleri` düzeltildi, testi var.

### Bulgu 2 — MASE üretim planının sorusunu sormuyor

Aralıklı seride günlerin çoğu gerçekten sıfır; **"hiç satmayacağız" demek
gün gün en yakın cevap** ve MASE bunu ödüllendiriyor. Üretim emri o tahmini
kullanamaz — `toplam()` ve `toplam_bandi()` okuyor.

Rapor artık üç sütun daha basıyor: **yanlılık** (sapma hangi yönde), **bağıl
hata** (ne kadar), **sıfır oranı** (kaç pencerede "hiç üretme" diyor).
⚠️ Yanlılık tek başına yanıltır: ±%100 sapan bir yöntem yanlılıkta mükemmel
görünür, hatalar birbirini götürür. İkisi ayrı ölçülüyor.

### Ölçülen (2.000 kalem, ufuk 14 gün — rapor çıktısından)

```
yontem              MASE(yavas)  yanlilik  sifir%  bagil hata(yavas)  bant
croston                 1,12         0%     28%          1,59         93%
sba                     1,08        -7%     28%          1,54         93%
hareketli_ortalama      1,12        -1%     60%          1,59         92%
mevsimsel_naif          1,08        +1%     68%          1,61         82%
ussel_duzlestirme       1,55        +7%     34%          2,29         91%
```

MASE'de `mevsimsel_naif` önde ama pencerelerin **%68'inde "hiç üretme"**
diyor. Croston %28.

### Bulgu 3 — bant okunduğu yerden başka yerde kalibre ediliyordu

Üst bant "tipik talep günü büyüklüğü"ydü; sözleşme bandı gün gün taşıyıp
`toplam_bandi()` topladığı için 10 günde bir 5 adet satan kalemde iki
haftalık üst sınır ~70 adet çıkıyordu. Bant artık geçmişteki gerçek 14
günlük toplamların ampirik kuantillerinden kuruluyor: kapsama yavaş
katmanda %93.

### Karar

- Üretim emri kuralı **Croston** kullansın. Sebep SBA'nın 0,05'lik bağıl
  hata üstünlüğü değil, **yanlılık**: SBA bu veride −%7, Croston %0.
  Düzeltme, düzeltecek yanlılık bulamayıp aşağı kaydırıyor; üretim
  planında sistematik eksik tahmin = kronik stoksuzluk.
- Günlük MASE tek başına **karar ölçütü değil**.
- ⚠️ Bu sayılar simülasyondan; **üst sınır**. Gerçek ölçüt B10.4 — SBA
  orada haklı çıkabilir.

### ⚠️ Süreç bulgusu — yazıya geçen sayılar yeniden üretilemiyor

Hem Adım 1-2'nin belgelediği tablo (yavaş katmanda 0,52) hem bu turun ilk
commit mesajındaki tablo (0,50 / −%20 / %90) **depodaki kodla koşulduğunda
çıkmıyor**. İkisi de ayrı ayrı doğrulandı: ilgili commit'e dönülüp ölçüm
koşuldu, sayılar bugünküyle bit bit aynı çıktı.

Bu belgelerdeki sayılar karar gerekçesi oluyor. Bundan sonra **rapor çıktısı
olduğu gibi yapıştırılacak**, elle özetlenmeyecek.

## B10.3 — Üretim servis katmanı 🟡 *(A10.2'ye bağlı)*

- `POST /v1/decisions/production/order-review` — **liste** döndürür
- `explain.py`'ye `uretim.*` tipleri
  ⚠️ B5'te `explain.py`'nin alan-bağımsız sanılan yerleri finansta patlıyordu
  ve **sessizce şablona düşüyordu**. Üretimde aynısı olmasın: önce test.
- `nightly.py`: üretim taramaya girer; guard kırılımı sayacı ilk koşuda
  şablona düşmeyi gösterir.

## B10.4 — Tahmini gerçek veriyle ölçmek 🟡

Şimdiki sayı **simülasyondan** ve simülatör tahmin edilebilir bir yapı
üretiyor — yani bir **üst sınır**. Gerçek ölçüt `csv_erp.py::hareketleri_oku`
ile gelen hareket verisi.

**Bitti sayılır:** aynı ölçüm gerçek veriyle koşuluyor ve iki sayı yan yana.

---

# FAZ 11 — Genel planlama motoru · B paketi

> Tam plan: `dokumantasyon/FAZ-11-GENEL-PLANLAMA.md`
> ⚠️ **Adım 0 (sözleşme dondurma) bitmeden kod yazılmaz.**

## ⚠️ A'yı hiç beklemiyorsun

Bu paketteki işlerin **hiçbiri `plan_kur()` çağırmıyor.** Maliyet, karne ve
öneri girdi olarak `KaynakPlani` alıyor — yani donmuş sözleşmenin kendisini.
Testlerini **elle kurduğun plan nesneleriyle** yazıyorsun; motor hiç koşmuyor.

Motorla buluşma yalnızca en sonda, API ucunda ve o uç senin sahanda: tek
satırlık bir çağrı.

Faz 10'da aynı disiplin uygulandı — B tahmin çekirdeğini yazarken A üretim
kuralını yazdı, ikisi `TalepTahmini` dışında hiç temas etmedi.

## Sahiplik tablosu

| Sende | A'da |
|---|---|
| `app/planlama/maliyet.py` | `app/planlama/yerlestirme.py` |
| `app/planlama/karsilastir.py` | `app/planlama/olcut.py` |
| `app/api/decisions.py` — plan uçları | `app/planlama/tanim.py` |
| `app/core/isletme_profili.py` | `app/domain/production/cizelge.py` |
| `app/llm/explain.py` | `ornekler/nakliye.json` |

## ✅ B11.1 — `maliyet.py` · planın beklenen maliyeti — BİTTİ (`1636c8d`)

`plan_maliyeti(plan: KaynakPlani, ...) -> MaliyetKirilimi`. Bileşenler
profilde zaten var: `stoktukenmesi_ceza_carpani` (2,5),
`yillik_elde_tutma_orani` (0,25), `siparis_maliyeti_tl` (250).

⚠️ Maliyet bir **tahmin**. Varsayımları çıktının yanında yazılı olacak; tek
sayıya indirgeyip tabloyu gizlemek "sayı tek başına yalan söyler" hatasının
tekrarı olurdu.

**Bitti sayılır:** iki elle kurulmuş plan için fark elle doğrulanabiliyor;
kırılım (stoksuzluk / elde tutma / kurulum) ayrı görünüyor.

## ✅ B11.2 — `karsilastir.py` · karne ve gerekçeli öneri — BİTTİ (`1636c8d`)

Üç plan yan yana, önerilen **parayla** işaretli: *"B'yi öneriyorum: beklenen
maliyeti A'dan 90.000 TL düşük."*

⚠️ Tablo daima basılacak; öneri onu gizlemeyecek.
⚠️ Öğrenen öneri kapsam dışı — geçmiş veri yok, açıklanabilirlik bozulur.

## ✅ B11.3 — Servis uçları — BİTTİ (`1636c8d`; ⚠️ uçlar hâlâ ÜRETİME ÖZEL, bkz. Faz 13)

- `GET .../schedule?olcut=en_acil` (varsayılan = bugünkü davranış)
- `GET .../schedule/compare` — üç plan + karne + öneri

⚠️ İkisi de `GET`, DB'ye yazmıyor. Çizelge karar değil, kararların görünümü.

## B11.4 — Plan özeti metni 🟡

`explain.py`'ye Türkçe özet. ⚠️ Faz 8'in dersi: tip `_TIPE_GORE_ALANLAR`'a
girmezse model **hiç çağrılmaz** ve metin sessizce şablona düşer. Önce test.

---

# FAZ 13 — "Tam plan" · B paketi

> ✅ **Tanımlandı 2026-08-12.** Ortak plan:
> [FAZ-13-TAM-PLAN.md](FAZ-13-TAM-PLAN.md). Dört soru soruldu ve cevaplandı;
> aşağıdakiler tahmin değil.
>
> ⚠️ Önceki üç okumada hata aynıydı: **örnek olarak verilen alan, işin konusu
> sanıldı.** Teslim edilen şey bir alan değil, alanı bilmeyen bir mekanizma.
> Nakliye ve yapı malzemesi örnektir. `if alan == "..."` yazdığın an bu fazın
> iddiası çürür.

## Kabul ölçütü — tek cümle

Alan adını hiç bilmeyen bir komut iki farklı alanda plan üretiyor, üçüncü alan
**tek JSON** ile ekleniyor.

## ✅ Adım 0 — ORTAK, tek PR — BİTTİ (`0902e3b`)

`AtamaGerekcesi` ve `IslerKaynagi` donduruldu, 12 test. İkisi de
**varsayılanlı ve geriye uyumlu** — Faz 11 çağrılarının hiçbiri değişmedi.

| ne | nerede | garanti |
|---|---|---|
| `AtamaGerekcesi` (seçilen · adaylar · elenme nedenleri · belirleyici) | `app/planlama/contracts.py` | belirleyici **kapalı küme**; seçilen kaynak adaylarda olmak zorunda |
| `PlanSatiri.gerekce` | aynı dosya | varsayılanı `None` — B, A'yı beklemiyor |
| `IslerKaynagi` (`elle` · `tahmin` · `alan:<ad>`) | `app/planlama/tanim.py` | üst seviye anahtarlar kapalı küme: `isler_kaynak` yazan tanım **patlıyor** |
| `AlanTanimi` + `alan_tanimi_oku/dosyadan` | aynı dosya | `dosyadan_yukle` aynen korundu |

Bu bitmeden aşağıdakilere başlanmaz — ama bittikten sonra A'yı **beklemezsin**:
`gerekce=None` ile çalışırsın, plan belgesi o bölümü atlar.

## ✅ B13.1 — `app/planlama/tam_plan.py` · alanı bilmeyen tek giriş — BİTTİ

```python
tam_plan(alan, olcut=None, ufuk_gun=None, baslangic=None, dizin=None) -> TamPlan
```

Zincir koşuyor: tanım (JSON) → işler → yerleştirme → maliyet + karşılaştırma.
Üç kip de bağlı (`elle` · `tahmin` · `alan:<ad>`), zincir döngüsü okunur
hatayla duruyor. 20 test.

⚠️ **Sözleşmeye bir ekleme yapıldı (B13.1 sırasında):** `elle` dışındaki
kiplerde işleri üretecek modülün yolu tanımda yazılı — `"adaptor": "..."`.
Alternatifi motorda `{"uretim": ...}` sözlüğü tutmaktı; o durumda yeni alan
eklemek **kod** değişikliği gerektirir ve fazın 3. kapısı düşerdi. `elle`
kipinde adaptör aranmıyor: yeni müşteri hâlâ tek JSON.

⚠️ **1. kapı henüz yarım:** iki alan testte (`tmp_path`) kanıtlanıyor,
gerçek iki alanla değil — `ornekler/uretim.json` A13.2 ile gelecek.

Bulunan ve düzeltilen hata: `ufuk_gun=0` sessizce 14'e dönüyordu
(`ufuk_gun or 14`). Artık hata veriyor.

## ✅ B13.2 — Plan belgesi — BİTTİ

`app/planlama/belge.py` · altı bölüm: gelecek · ne yapılacak · takvim ·
gerekçeler · plan seçenekleri (maliyet tablosu + varsayımlar) · ⚠️ dikkat.
9 test.

⚠️ **Model çağrılmıyor.** Faz 8'in dersi tersine çevrildi: belge önce kodla
üretiliyor ve testi var; model sonradan yalnızca özet cümlesini yazacak.
Bir test kaynak dosyada `llm`/`istem`/`prompt` geçmediğini doğruluyor —
bağlanırsa kırılır.

⚠️ **Boş bölüm atlanmıyor.** Gerekçe verisi yoksa (A13.1 öncesi) belge
"neden bu kaynak sorusu bu çıktıdan cevaplanamaz" diye **yazıyor**. Boş
bölümü gizlemek planı olduğundan iyi gösterirdi.

## ✅ B13.3 — `POST /v1/plan/{alan}` — BİTTİ

Üretime özel uçların genel karşılığı. Mevcut uçlar **silinmez** (geriye
uyumluluk), yeni uca yönlendirdikleri belgelenir.

## ✅ B13.4 — Araç olarak ekle — BİTTİ (`tam_plan_sorgula`)

`app/llm/araclar.py`'ye `tam_plan`. Araç sayısı 7 → 8.

## ✅ B13.5 — Ölçüm — BİTTİ (faz13-tur1: %86,7 · %80,0 — DEĞİŞMEDİ)

`router_taban`, **aynı donmuş 30 soruluk set**, `--etiket faz13-tur1`.

⚠️ **Faz 12'nin süreç hatası tekrarlanmayacak:** orada araç eklemekle model
sürümü aynı anda değişti ve iyileşme ikisine de bağlanamadı. Bu turda **model
sürümü sabit.** Değişmesi gerekirse ayrı koşu.

Beklenti: araç eklemek mevcut **%86,7'yi düşürmemeli.** Yükselmesi hedef değil.

## Elde hazır olanlar (yeniden yazma)

| ne | nerede |
|---|---|
| genel yerleştirme (kaynak/iş) | `app/planlama/yerlestirme.py` |
| plan ölçütleri | `app/planlama/olcut.py` |
| JSON alan tanımı okuyucu | `app/planlama/tanim.py` |
| maliyet + karne + öneri | `app/planlama/maliyet.py`, `karsilastir.py` |
| tahmin çekirdeği (girdisi düz geçmiş — genel) | `app/forecast/` |
| üretim adaptörü | `app/domain/production/cizelge.py` |
| araç çalıştırma (LLM'siz) | `app/llm/araclar.py` |
| işletme profili | `app/core/isletme_profili.py`, `profiller/*.json` |

## Bu fazda yapılmayacak

Sevkiyat simülatörü (~1 hafta) **plandan çıkarıldı** — bir alanı
zenginleştirmek genel mekanizmaya hiçbir şey katmıyor. Coğrafi rota, kurulum
sihirbazı, müşteri ERP aktarımı da kapsam dışı. Gerekçeler:
[FAZ-13-TAM-PLAN.md](FAZ-13-TAM-PLAN.md) §Kapsam dışı.


---

# Faz 13 · B paketi — kapanış notları (26.08.2026)

## B13.3 · `POST /v1/plan/{alan}`

Dört alan da dışarıdan çağrılabilir: `GET /v1/plan/alanlar` listeliyor,
`POST /v1/plan/{alan}` planı veriyor, `?belge=true` altı bölümlük metni de
ekliyor. Üretime özel uçlar **silinmedi**.

Uçta iki şey yakalandı:

⚠️ **404 mesajı sunucunun dizin yapısını sızdırıyordu.** Motorun hata metni
tanım dosyasının tam yolunu (`D:\ERP\...`) içeriyor — içeride yararlı,
dışarıda gereksiz ve riskli. Uç kendi mesajını kuruyor;
`test_HATA_METNI_SUNUCU_YOLUNU_sizdirmiyor` kilitliyor.

**Kimlik doğrulama otomatik geldi:** router seviyesinde bağlı olduğu için
yeni uç korumalı doğdu (`test_tum_v1_uclari_korumali` yeşil). Kill switch de
planı durduruyor — karar üretilmiyorsa plan da üretilmemeli.

## B13.4 · `tam_plan_sorgula`

Çalıştırılabilir araç 5 → 6, `AracAdi` 11 → 12.

⚠️ **Parametresi alan adı.** "Nakliye planı çıkar" ile "vardiya planı çıkar"
aynı aracın iki çağrısı; alan başına araç eklemek listeyi şişirir ve modelin
işini zorlaştırırdı.

Alan verilmezse **tahmin etmiyor**: tanımlı alanları listeleyip soruyu geri
soruyor. Rastgele bir alanın planını vermek, istenmeyen cevabı doğruymuş
gibi göstermek olurdu.

⚠️ `EGITILMIS_ARAC_ADLARI`'ya **eklenmedi** ve bu bir test ile sabit: canlı
model bu adı eğitimde görmedi, eğitilmiş kipte seçemez.

## B13.5 · Ölçüm — beklenti karşılandı, ama sınırı yazılı

faz12-tur6 → faz13-tur1: **%86,7 · %80,0 → %86,7 · %80,0.** Tek soru bile
değişmedi.

⚠️ Bu sayının bilgi değeri sınırlı: ölçüm `egitilmis` kipte koşuyor, o kipte
istem araç listesi taşımıyor, model yeni aracın adını üretemez — yani
ölçümün düşmesi zaten mümkün değildi. "Zarar vermedi" doğru; "işe yarıyor"
bu ölçümden çıkmaz. Ayrıntı: `OLCUMLER.md` §Faz 13 · B13.5.
