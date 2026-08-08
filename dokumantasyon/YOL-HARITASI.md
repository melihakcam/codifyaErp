# Yol Haritası

> ⚠️ **GÜNCELLEME (2026-08-08): iki kişilik kurulum artık geçerli değil.**
>
> Bu belge iki geliştiricinin (Kişi A — Veri & Alan, Kişi B — Servis & Model)
> paralel çalışacağı varsayımıyla yazıldı. Gerçekte proje **tek kişi + AI
> asistanı** ile yürüdü ve iki tarafın işi de yapıldı.
>
> Aşağıdaki rol dağılımı, buluşma noktaları ve "diğerinin onayı" kuralları
> **tarihsel kayıt** olarak duruyor — silinmedi çünkü mimari kararların
> gerekçesini taşıyorlar (dondurulmuş sözleşme, stub'lar, dosya ayrımı gibi
> tasarımlar oradan doğdu ve hâlâ geçerli). Ama **süreç kuralı olarak
> uygulanmıyorlar.** Yürürlükte olan kurallar için bkz. "Tek kişilik düzende
> neler değişti".
>
> Görev listeleri hâlâ kullanışlı birer kontrol listesi:
> · [KISI-A-GOREV.md](KISI-A-GOREV.md) — Veri & Alan
> · [KISI-B-GOREV.md](KISI-B-GOREV.md) — Servis & Model
>
> Ölçülmüş durum ve teslimat raporu: [RAPOR.md](RAPOR.md)

## Tek kişilik düzende neler değişti

| iki kişilik kural | yerine geçen |
|---|---|
| Merge için diğerinin PR onayı şart | **Otomatik kapılar zorunlu**: `pytest` (353 test), `ruff`, `veri_tutarlilik_kontrolu`, `golden_set_inceleme`. Kapı geçmeden commit'lenmez. |
| Sözleşme değişikliği iki kişi konuşup yapar | `app/contracts.py` **yine de dondurulmuş sayılır** — değiştirmek için yazılı gerekçe ve ölçüm gerekir. Tek kişi olmak sözleşmeyi gevşetmez, aksine daha kolay bozar. |
| Buluşma noktalarında (SP0-SP5) birlikte oturulur | Aynı kontroller **tek başına** yapılır ama **yazılı** yapılır: her buluşma noktasının çıktısı `OLCUMLER.md`'ye işlenir. |
| Bilgi tek kişide toplanmasın diye karşılıklı inceleme | Bilgi zaten tek kişide. Karşılığı: **her karar gerekçesiyle belgelenir.** `OLCUMLER.md` bunun için var — kod neden böyle yazıldığını değil, hangi ölçümün onu gerektirdiğini tutuyor. |
| Paralel çalışma için stub'lar | Artık paralellik yok, ama stub'lar duruyor: testleri LLM'siz koşturmayı sağlıyorlar. |

⚠️ **En çok kaybedilen şey inceleme.** İki kişilik düzende ikinci bir çift
göz vardı. Tek kişide onun yerini otomatik kapılar ve ölçüm alıyor — bu
yüzden bu projede "çalışıyor gibi görünüyor" yeterli sayılmıyor, her
iddianın bir ölçümü var.

---

## Alınan kararlar ve gerekçeleri

| Konu | Karar | Neden |
|------|-------|-------|
| **Mimari** | Hibrit: kural motoru + küçük ML (sayı) · 1B LLM (dil) | 1B model sayısal muhakemede güvenilmez; sayıyı deterministik kod hesaplar, LLM sadece anlatır |
| **Yetki** | Eşikli otonomi, `shadow` modda başlar | Ölçülmemiş bir sisteme yetki vermek finansal risk |
| **Temel model** | Qwen2.5-1.5B-Instruct | 1B sınıfında en iyi Türkçe + JSON; Apache-2.0 (ticari kullanıma uygun) |
| **Eğitim** | **Google Colab (ücretsiz T4)** üzerinde LoRA, yerelde CPU inference | Elimizde GPU yok. Tek T4 ve oturum kopmaları var → eğitim checkpoint'li ve bölünebilir tasarlanır |
| **Geliştirme** | Yerelde (`uv` + FastAPI + Ollama). Colab **yalnızca** Faz 3 eğitim adımları için | Servis, testler, simülatör notebook'ta değil repoda yaşar; Colab oturumu uçucu |
| **Veri** | Simülatör + kural motoru etiketi + büyük LLM gerekçe yazımı | Gerçek ERP verimiz yok; etiket deterministik olduğu için halüsinasyonsuz |
| **Veritabanı** | SQLite (Postgres değil) | C:'de 3 GB kaldı, Docker gereksiz yük; SQLAlchemy ile geçiş tek satır |
| **Servis** | Bağımsız Python/FastAPI, ERP ile REST | ERP stack kararı sonraya kalabilir, motor yeniden yazılmaz |
| **Döngü** | Gecelik batch + kritik olay tetikleyici | CPU'da 1B model gerçek zamanlıya yetmez |
| **Ölçek** | KOBİ: ~2.000 SKU, ~800 müşteri, günde 50-500 hareket | Türkiye'de en yaygın ERP müşterisi |
| **Kapsam** | Faz 1'de yalnızca Stok & Satınalma, uçtan uca | Tek alanı çalıştırıp kalıbı kanıtlamak, 4 alanı yarım bırakmaktan iyi |

---

## Mimariyi ayakta tutan iki kural

**1. LLM asla sayı üretmez.** Sayılar prompt'a kural motorundan *verilir*, model onları
yalnızca cümleye yerleştirir. Metindeki her sayı `DecisionCandidate.izinli_sayilar()`
kümesinde yok ise çıktı reddedilir. 1B modeli üretime uygun kılan tek en önemli bileşen.

**2. ERP asla LLM'i beklemez.** Karar kural motorundan milisaniyelerde çıkar; LLM
yalnızca açıklama metnini yazar (~6-8 sn). Gerekçe kuyruklu ve tembel.

```
ERP (stack özgür)  ──REST──▶  Karar Motoru (FastAPI)
                                   │
      ┌────────────────────────────┼────────────────────────────┐
      ▼                            ▼                            ▼
  A. Kural Motoru           B. Küçük ML                  C. 1B LLM
  ROP, EOQ, ABC/XYZ,        talep tahmini,               niyet→araç,
  ölü stok, tedarikçi       anomali                      Türkçe gerekçe
      │                            │                            │
      └──────────▶ Karar Adayı ◀───┘                            │
                        │                                       │
                        ▼                                       │
              Eşik Politikası ──▶ oto-uygula │ onay kuyruğu ◀───┘
                        │
                        ▼
                 Denetim Kaydı ──▶ İnsan geri bildirimi ──▶ sonraki eğitim turu
```

---

## Rol dağılımı

İki rol bilinçli olarak **farklı beceri kümelerine** ayrıldı — kimse diğerinin
öğrendiğini tekrar öğrenmesin. Ama PR incelemesi zorunlu, böylece ikisi de sistemin
tamamını tanır.

| | Kişi A — Veri & Alan | Kişi B — Servis & Model |
|---|---|---|
| **Sahiplendiği** | `simulator/`, `app/domain/stock/`, `training/build_dataset.py`, `training/label_rationale.py` | `app/api/`, `app/core/`, `app/models/`, `app/llm/`, `app/jobs/`, `training/train_lora.ipynb`, `training/eval/` |
| **Öğrendiği** | pandas, numpy, olasılık dağılımları, stok formülleri, XGBoost, Parquet | FastAPI, pydantic, SQLAlchemy, pytest, Ollama, peft/Unsloth, GGUF |
| **Dokunmadığı** | FastAPI, LLM, GGUF, eğitim notebook'u | Stok formülleri, talep simülasyonu |

**Paralel çalışmayı mümkün kılan şey:** `app/contracts.py` **dondurulmuştur.**
A bu tipleri üretir, B tüketir. B, A'nın gerçek kural motoru bitene kadar
`decide_stub()` kullanır. Dosya kümeleri hiç kesişmiyor — merge çakışması da yok.

> ~~Sözleşmede değişiklik gerekiyorsa **tek taraflı yapılmaz.** İkiniz konuşup tek PR'da
> yaparsınız.~~ · **Tek kişilik düzende:** sözleşme yine dondurulmuş sayılır; değiştirmek
> için yazılı gerekçe ve etkilenen testlerin güncellenmesi gerekir.

---

## Buluşma noktaları

~~Buralarda birlikte oturup entegrasyonu yaparsınız.~~ · **Tek kişilik düzende:**
her buluşma noktası bir **yazılı kontrol** — çıktısı `OLCUMLER.md`'ye işlenir.

| # | Ne zaman | Kontrol | Süre |
|---|----------|---------|------|
| **SP0** | ✅ **tamam** | Sözleşme donduruldu, stub'lı uçtan uca akış çalışıyor, 25 test yeşil | — |
| **SP1** | Faz 1 sonu | A: simülasyon verisi + kalite notebook'u (B onaylar) · B: onay kuyruğu tam turu | ½ gün |
| **SP2** | Faz 2 sonu | A'nın gerçek `decide.py`'si B'nin servisine bağlanır, stub'lar silinir. **Gerçek karar + gerçek Türkçe gerekçe** | 1 gün |
| **SP2.5** | Faz 3 ortası | **A**, 100 örneklik küçük veri setini Drive'a koyar → **B** Colab eğitim hattını uçtan uca kanıtlar. Tam veri beklemeden yapılır. | ½ gün |
| **SP3** | Faz 3 sonu | Eğitilmiş model serviste; guard reddedilme oranının düştüğü doğrulanır | ½ gün |
| **SP4** | Faz 4 sonu | Shadow mod bir hafta kesintisiz koştu | — |
| **SP5** | Faz 5 sonu | `RAPOR.md` + `threshold` moda geçiş kararı | — |

**SP2 hakkında:** bu noktada LoRA eğitimi hiç yapılmamış olsa bile sistem çalışıyor
olacak. Sıralama bilinçli — eğitim tarafı gecikirse veya beklediğini vermezse proje durmaz.

---

## Takvim

Günde ~4-6 verimli saat, öğrenme dahil.

| Faz | Kişi A | Kişi B | Süre |
|-----|--------|--------|------|
| **0** ✅ | — | — | tamam |
| **1** | Simülatör (A1.1-A1.5) | Veri katmanı + API + politika (B1.1-B1.6) | ~2 hafta |
| **2** | Kural motoru + ML (A2.1-A2.8) | LLM katmanı + guard (B2.1-B2.6) | ~2 hafta |
| **3** | Veri seti üretimi (A3.1-A3.5) | LoRA + GGUF, Colab'da (B3.1-B3.5) | ~1,5-2 hafta |
| **4** | Çok profilli simülasyon, para metriği | Sağlamlaştırma, shadow raporu, onay ekranı | ~1 hafta |
| **5** | Karar kalitesi metrikleri | Benchmark + rapor | ~1 hafta |

**Faz 0-5 toplam: ~8 hafta.** Faz 6 ile dört alanın tamamı ~12-13 hafta.

### Faz 6 — Diğer 3 alan (alan başına ~1 hafta)

Kalıp artık kurulu. Her yeni alan için aynı 5 adım:

1. **A:** simülatörü genişlet + patolojiler
2. **A:** kural motoru + ML + `DecisionCandidate` üretimi
3. **B:** endpoint + politika satırı + tetikleyici
4. **A:** veri seti üret · **B:** LoRA'yı yeni veriyle **birlikte** yeniden eğit
   (alanları ayrı modellere bölme — 16 GB'ta gereksiz yük)
5. **Birlikte:** golden set genişlet, benchmark yeniden koş

Öneri sıra: **Finans & Tahsilat** (veri yapısı stoka en benzer) → **Satış & Fiyatlama**
→ **Üretim & Planlama** (en karmaşık, en sona).

---

## Paylaşılan Google Drive düzeni

Faz 3'te eğitim verisinin ve model çıktılarının durduğu yer.

```
MyDrive/codifya/
  veri/         ← Kişi A yazar, Kişi B okur (JSONL eğitim verisi)
  checkpoint/   ← Kişi B yazar (eğitim ara kayıtları, oturum kopunca devam için)
  cikti/        ← Kişi B yazar (merge edilmiş model + GGUF)
```

Kurallar:
- **Veri Drive'a bir kez konur.** Her Colab oturumunda yeniden yüklemek 10-20 dakika
  yakar ve kopma riskini artırır.
- **Kod Drive'da yaşamaz.** Notebook'lar repoda (`training/*.ipynb`), Drive yalnızca
  veri/model deposudur. Colab'da yazılan kodu repoya geri işlemeyi unutmayın.
- Repo `.gitignore`'unda `*.gguf`, `*.safetensors` hariç tutuluyor — model dosyalarını
  git'e commit etmeye çalışmayın.

## Otonomi kademeleri

`.env` içindeki `AUTONOMY_LEVEL` ile seçilir. Sıra bu şekilde ilerler, **atlanmaz**:

| Kademe | Davranış |
|--------|----------|
| `shadow` | Karar verir, kaydeder, **hiçbir şey uygulamaz.** Başlangıç modu. |
| `advisory` | Öneri + gerekçe gösterir, uygulamayı insan yapar |
| `threshold` | Eşik altını kendi uygular, üstünü onay kuyruğuna alır |
| `off` | Kill switch — endpoint 503 döner |

> **`shadow` modda ölçülmüş doğruluk raporu olmadan `threshold`'a ASLA geçilmez.**
> Bu teknik değil, süreç kararıdır. `tests/test_policy.py` bunu sınar.

`policy.py`'de `sonuc` (politikanın hükmü) ve `uygulandi` (gerçekten olan) ayrı
tutulur — shadow mod raporu tam olarak bu ikisinin karşılaştırmasıdır.

---

## Başarı metrikleri

| Metrik | Hedef | Kim ölçer |
|--------|-------|-----------|
| Router: araç + parametre tam eşleşme | > %95 | B |
| Gerekçe: uydurma sayı | **0 — sert kapı** | B |
| Gerekçe: Türkçe akıcılık + dayanaklılık | LLM-jüri puanı | B |
| **Karar kalitesi (para metriği)** | *AI politikası* vs *vasat taban* vs *oracle*: stok tükenme oranı, aşırı stok maliyeti, toplam maliyet | A |
| Gecelik tarama süresi | < 10 dk | B |
| Tepe RAM | < 4 GB | B |

**Son satır işin para metriğidir.** Raporun ve sunumun merkezine *"model şu kadar iyi
cevap veriyor"* değil, **"AI politikası toplam stok maliyetini %X düşürdü, stok
tükenmesini %Y azalttı"** konur. İş değerini gösteren tek sayı bu.

---

## Riskler

| Risk | Karşılık |
|------|----------|
| **C: sürücüsü doluyor (~3 GB kaldı)** | Ortam değişkenleri D:'ye yönlendirildi; her faz başında `Get-PSDrive C` kontrolü |
| **Ücretsiz Colab oturumu kopuyor** | Eğitim 4-7 saat, oturum ~12 saatte / ~90 dk hareketsizlikte kesilir → Drive'a `save_steps=200` checkpoint + `resume_from_checkpoint=True`; eğitim 15k→35k→55k kademeli |
| Colab'da yazılan kod kaybolabilir | Notebook repoda yaşar, Drive yalnızca veri/model deposu; oturum sonunda repoya işle |
| 1B modelin Türkçe JSON tutarlılığı | Şema zorlamalı çıktı → GBNF grammar yedeği → guard → şablon geri dönüşü |
| Simülasyon-gerçek farkı (sim2real) | `shadow` modda gerçek veride ölçüm; Faz 4'te çok şirket profili |
| ~~İkinizin birbirini beklemesi~~ (tek kişide geçersiz) | Dondurulmuş sözleşme + stub'lar yine de duruyor: testleri LLM'siz koşturuyorlar |
| **Bilgi tek kişide toplanıyor** (tek kişilik düzende kaçınılmaz) | Karşılığı: her karar **gerekçesiyle** `OLCUMLER.md`'ye yazılır + otomatik kapılar (353 test, ruff, veri tutarlılığı, golden set) |
| Eğitim verisi halüsinasyon içeriyor | Guard'ı **etiketleme hattında da** kullan (A3.4); reddedilme oranını izle |
| "LLM her şeyi çözer" beklentisi | Gerçek zekâ kural motorunda; LLM dil katmanı. Sunumda net tutulur |
| CPU'da LLM gecikmesi | Karar yolu LLM'den bağımsız; gerekçe kuyruklu; gecelik işte yalnızca üst N karar |
| Zaman serisinde veri sızması | Train/test bölmesi **tarih + SKU** bazında — rastgele bölme yasak |

---

## Uçtan uca doğrulama

Faz 2 sonrasında sistemin tamamı şu sırayla sınanır:

```bash
uv run python -m simulator.run --years 3 --seed 42 --profile kobi_yapi
```

```bash
uv run pytest -v
```

```bash
uv run python -m training.eval.benchmark --golden training/eval/golden_set.jsonl
```

```bash
uv run uvicorn app.main:app --reload
```

Sonra elle:
1. `POST /v1/ask` → *"elimizde kritik seviyeye düşen ürün var mı?"* → router doğru aracı seçmeli
2. `POST /v1/decisions/stock/reorder-review` → karar **milisaniyelerde**, gerekçe kuyrukta
3. `uv run python -m app.jobs.nightly` → Türkçe içgörü listesi, < 10 dk
4. `GET /v1/approvals` → eşik üstü kuyrukta; eşik altı `shadow` modda **uygulanmamış ama kaydedilmiş**
5. `POST /v1/feedback` ile bir kararı reddet → `feedback` tablosunda ve denetim kaydı tam
6. **Guard testi:** bağlamda olmayan sayı içeren gerekçe ürettir → reddedilip şablona
   düştüğünü ve bunun denetim kaydına yazıldığını gör
