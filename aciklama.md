# Açıklama — Kişi B tarafında ne yaptık

> Bu dosya **basit dille** yazılmıştır. Amacı: projeye sonradan bakan birinin
> (ya da bir hafta sonra kendinin) "burada ne olmuş, neden böyle yapılmış"
> sorusuna cevap bulması.
>
> **Her güncellemede bu dosya da güncellenir.** Kod değişti ama burası
> değişmediyse, burası yanlıştır.
>
> Son güncelleme: Faz 1 tamamlandı (B1.1–B1.6) · commit `64b701b`

---

## 1. Proje ne yapıyor?

Codifya ERP'ye bir **yapay zekâ karar mekanizması** kuruyoruz. Sistem stok
durumuna bakıp "şu üründen 1.200 adet sipariş verilmeli" gibi kararlar
üretiyor. Düşük riskli kararları kendisi uygulayacak, yüksek riskli olanları
insan onayına düşürecek.

**En önemli tasarım kısıtı:** elimizde GPU yok, 16 GB RAM'li bilgisayarlar var.
Bu yüzden küçük bir dil modeli (Qwen2.5-1.5B) kullanacağız. Ama küçük modeller
**sayı uydurur**. Bu yüzden sistem ikiye ayrılmış:

| Kim hesaplıyor | Ne hesaplıyor |
|---|---|
| **Kural motoru + küçük ML** (Kişi A) | Sayılar: kaç adet sipariş, emniyet stoğu, risk |
| **Dil modeli** (Kişi B) | Yalnızca Türkçe cümle: "şu yüzden bu kadar sipariş öneriliyor" |

Yani zekâ kural motorunda, dil modeli sadece anlatıcı.

### Sistemi ayakta tutan iki kural

**1. Dil modeli asla sayı üretmez.** Sayılar ona *verilir*, o sadece cümleye
yerleştirir. Ürettiği metindeki her sayı, karardan gelen "izinli sayılar"
kümesinde yoksa metin **reddedilir**. Bu kontrolü yapan koda **guard** deniyor
ve Faz 2'de yazılacak — projenin en kritik parçası.

**2. ERP asla dil modelini beklemez.** Karar milisaniyelerde çıkar. Gerekçe
metni ancak istenirse üretilir (CPU'da 6-8 saniye sürüyor).

---

## 2. Kim ne yapıyor?

| | Kişi A (Melih) | Kişi B (sen) |
|---|---|---|
| **Sahiplendiği** | `simulator/`, `app/domain/stock/`, eğitim verisi üretimi | `app/api/`, `app/core/`, `app/models/`, `app/llm/`, `app/jobs/`, CI |
| **Öğrendiği** | pandas, numpy, stok formülleri, XGBoost | FastAPI, SQLAlchemy, pytest, Ollama, LoRA eğitimi |

`app/contracts.py` **dondurulmuş** — ikisinin arasındaki sözleşme. A bu tipleri
üretir, B tüketir. Tek taraflı değiştirilmez.

---

## 3. Şu an neredeyiz?

```
FAZ 0  ✅  repoda hazır geldi (sözleşme, taklit akış, 25 test)
Adım 0 ✅  ORTAM KURULUMU
Adım 1 ✅  KOD OKUMA TURU
FAZ 1  ✅  TAMAMLANDI
   B1.1 ✅  Veritabanı tabloları
   B1.2 ✅  Veritabanı katmanı
   B1.3 ✅  Denetim kaydı
   B1.4 ✅  Eşikler veritabanına taşındı
   B1.5 ✅  API uçları + onay kuyruğu
   B1.6 ✅  CI (otomatik kontrol)
+ ekstra ✅  Kişi A'nın PR'ı incelendi
FAZ 2  ⬜  LLM katmanı — SIRADAKİ
```

**Testler: 25 → 91.** Hepsi geçiyor, lint temiz.

---

## 4. Adım adım ne yaptık?

### Adım 0 · Ortam kurulumu

Bilgisayarda proje çalışabilir hale getirildi.

| Yapılan | Neden |
|---|---|
| `uv` kuruldu | Projenin paket yöneticisi. `pip` + `venv` + `pyenv` yerine tek araç |
| Python 3.12.13 indirildi | Sistemde 3.11 vardı, proje 3.12+ istiyor. `uv` kendi indirdi |
| 140 paket kuruldu | `uv.lock` sayesinde Melih'le **birebir aynı** sürümler |
| Cache'ler `D:\ERP\.cache`'e yönlendirildi | C: sürücüsünde 5,8 GB kalmıştı. Cache 725 MB oldu ama C: hiç dolmadı |
| `.env` oluşturuldu | Ayarlar (`AUTONOMY_LEVEL=shadow` gibi) |

**Bu projede `pip install` asla kullanılmaz.** Yeni paket gerekirse `uv add`.
`pip install` paketi sadece senin bilgisayarına kurar, `uv.lock`'a girmez,
CI'da patlar.

### Adım 1 · Kod okuma turu

Faz 0'da hazır gelen kod anlatıldı. İki kritik konu:

**`izinli_sayilar()`** — Bir karar için, gerekçe metninde geçmesine izin
verilen sayıların listesi. Taklit karar için tam **25 sayı**. Faz 2'de guard
bunu kullanacak: metindeki bir sayı bu listede yoksa metin çöpe gidecek.

**`sonuc` ≠ `uygulandi`** — İki ayrı şey:
- `sonuc` = politikanın hükmü ("bu karar otomatik uygulanabilir")
- `uygulandi` = gerçekten olan şey ("ama shadow moddayız, dokunmadım")

Bir hafta shadow modda çalışıp bu ikisini karşılaştırdığında elde ettiğin sayı,
sistemi gerçekten uygulama moduna (`threshold`) geçirme iznin oluyor.

---

### B1.1 · Veritabanı tabloları

Kararların saklandığı yer kuruldu. Altı tablo:

| Tablo | Ne tutuyor |
|---|---|
| `decision` | Üretilen her karar + politikanın hükmü + (varsa) gerekçe |
| `decision_audit` | **Değişmez** denetim izi. Her olay için bir satır, asla güncellenmez |
| `approval` | Onay kuyruğu — kim, ne zaman, ne dedi |
| `feedback` | İnsan geri bildirimi — sonraki eğitim turunun verisi |
| `policy` | Eşik tablosu (B1.4'te devreye girdi) |
| `insight` | Gecelik bulgular (Faz 2'de dolacak) |

**`alembic` nedir:** Veritabanı yapısını kodla değiştirmenin yolu.
`alembic upgrade head` yazınca tablolar oluşuyor. Yapı değişince yeni bir
"migration" dosyası yazılıyor; böylece Melih'in bilgisayarındaki tablolar
seninkiyle aynı kalıyor.

**En önemli tasarım:** `decision` satırından sözleşme nesnesi geri
kurulabiliyor. Bu şart, çünkü gerekçe **sonradan** üretiliyor — guard saatler
sonra çalıştığında "izinli sayılar"ı o satırdan çıkaracak.

### B1.2 · Veritabanı katmanı

Uygulamanın veritabanına nasıl bağlandığı (`app/core/db.py`).

**Buradaki asıl bulgu:** SQLite yabancı anahtarları **varsayılan olarak
zorlamıyor**. Test ettim, var olmayan bir karara onay satırı yazılabiliyordu.
Yani B1.1'de yazdığım koruma kuralları **süstü**.

Üç ayar eklendi, her yeni bağlantıda çalışıyor:

| Ayar | Ne işe yarıyor |
|---|---|
| `foreign_keys=ON` | Yukarıdaki açığı kapatıyor |
| `journal_mode=WAL` | Gecelik iş yazarken API okumaya devam edebilsin |
| `busy_timeout=5000` | Kilitte hemen hata vermek yerine 5 sn bekle |

Ayrıca `GET /health/db` ucu eklendi: bağlantı durumu ve koruma kuralının açık
olduğu tek istekle görülebiliyor.

### B1.3 · Denetim kaydı

Projenin kuralı: **denetim kaydı olmayan bir karar yolu birleştirilmez.**

`app/core/audit.py` bu kuralı yoruma bırakmıyor:

- `karari_kaydet()` — kararı kaydetmenin **tek** yolu. Karar satırını ve
  denetim satırını **birlikte, aynı işlemde** yazıyor. Denetim kaydını atlamak
  mümkün değil.
- `girdi_hash_hesapla()` — girdinin parmak izi (SHA-256). "Aynı girdiye aynı
  kararı verdik mi" sorusunun cevabı.

**Hash'e yalnızca özellikler giriyor**, karar kimliği ve zaman girmiyor.
Girseler her çalıştırmada farklı hash çıkar ve karşılaştırma imkânsız olur.

**Neden aynı işlem:** ayrı ayrı kaydedilseydi, aradaki bir çökme *denetim izi
olmayan bir karar* bırakırdı — tam olarak engellemek istediğimiz şey.

### B1.4 · Eşikler koddan tabloya

Önce eşikler (5.000 TL, güven 0,85) kodda sabitti. Artık `policy` tablosunda,
karar tipi başına ayrı satır.

**Neden:** eşiği değiştirmek için kod dağıtmak gerekmesin. Kanıtı — canlıda tek
`UPDATE` ile davranış değişti:

```
eşik 5.000 -> 10.000
sonuç: onay_kuyrugu  ->  oto_uygula
```

Üç durum ayırt ediliyor: `db` (normal), `config` (kasıtlı veritabanısız yol),
`config_yedek` (**veritabanına bakıldı, satır yoktu**). Üçüncüsü gerekçe
kodlarına `ESIK_VARSAYILANA_DUSTU` ekliyor — sessizce yedeğe düşmek, eşik
tablosunun boş olduğunu aylarca fark etmemek demekti.

Mevcut `tests/test_policy.py` **hiç değiştirilmedi** ve geçmeye devam ediyor.

### B1.5 · API uçları

Dört yeni uç ve kararların veritabanına yazılması.

| Uç | Ne yapıyor |
|---|---|
| `GET /v1/approvals` | Onay kuyruğu, **risk skoruna göre azalan** |
| `POST /v1/approvals/{karar_id}` | Onayla / reddet / düzelt |
| `POST /v1/feedback` | Ek geri bildirim |
| `GET /v1/insights` | Gecelik bulgular (Faz 2'de dolacak) |

**Dört tasarım kararı:**

1. **Kuyruğa yalnızca onay bekleyen kararlar girer.** Shadow modda eşik altı
   kalan karar kaydedilir ama kuyruğa girmez — kimsenin bakmayacağı kaydı
   insanın önüne koymak kuyruğu değersizleştirir.
2. **`uygulandi` onay ucunda değişmez.** O alan "sistem uyguladı mı" demek;
   insan onayı sistemin uygulaması değil.
3. **İş akışı ucu ile veri ucu ayrı.** Onay ucu kararı bir kez sonuçlandırır
   (ikincisi 409 döner). Feedback ucu sınırsız yorum alır — çünkü kullanıcı bir
   hafta sonra "fazlaydı" derse iş akışı değişmemeli ama eğitim verisine
   girmeli.
4. **Kuyruk riske göre sıralı.** İnsanın zamanı kısıtlı.

Ayrıca `GET /` → `/docs` yönlendirmesi eklendi. FastAPI köke hiçbir şey
koymuyor; `localhost:8000` açan biri 404 görüp servisi çökmüş sanıyordu.

**Elle doğrulandı:** `/docs` üzerinden karar üretildi, kuyrukta görüldü,
reddedildi, `feedback` tablosuna düştüğü doğrulandı. Kırmızı senaryolar da
geçti: kullanıcı eksik → 422, düzeltme aksiyonu yok → 422, aynı kararı iki kez
→ 409, olmayan karar → 404.

### B1.6 · CI (otomatik kontrol)

`.github/workflows/ci.yml` — her pull request'te otomatik koşuyor:

| Adım | Ne kontrol ediyor |
|---|---|
| `uv sync --frozen` | Kilit dosyası güncel mi ("paket ekledim ama lock'u işlemedim") |
| `ruff check .` | Kod stili |
| `pytest` | 91 test |
| `alembic upgrade head` | Migration'lar boş veritabanında uygulanabiliyor mu |
| `alembic check` | Model ile migration uyumlu mu ("modeli değiştirdim ama migration üretmeyi unuttum") |

⚠️ **Bu dosya tek başına yeterli değil.** GitHub'da `main` için branch
protection açılmalı (Settings → Branches), yoksa CI sadece bilgi verir, kırmızı
bir PR'ı engellemez.

---

### Ekstra · Kişi A'nın PR incelemesi

Melih'in `faz1-simulator` branch'i ayrı bir çalışma kopyasında incelendi.
A1.1–A1.5'in tüm kabul ölçütleri **geçti**:

| Ölçüt | Ölçüm |
|---|---|
| Aynı seed → aynı sonuç | 11 tablo, tam eşleşme |
| Pareto (üst %20 SKU) | cironun **%80,0**'i |
| Talep yapısı | Pazar kapalı, zirve Ağustos, trend %+5,8/yıl |
| Negatif stok | **0** |
| Mutabakat farkı | **tam sıfır** (patolojiler açıkken de) |
| Patolojiler | kapalı 0 olay / açık 314 olay, 6 tip |

**Üç sözleşme boşluğu bulundu**, Melih'e iletildi:

1. **`tedarikci_onayli` yok** — bu bir güvenlik kapısı girdisi; tedarikçi
   onaylı değilse karar tutarı ne olursa olsun onaya gidiyor.
2. **`raf_omru_kalan_gun` türetilemiyor** — tabloda statik raf ömrü var ama
   parti giriş tarihi yok.
3. **`rezerve_stok` yapısal olarak 0** — olay döngüsü aynı gün sevk ediyor.

**Faz 5 için taban çizgi:** taban politikanın stok tükenme oranı **%0,86**. AI
politikasının yenmesi gereken sayı bu.

---

## 5. Yolda bulunan hatalar ve tuzaklar

Bunlar tekrar yaşanmasın diye yazıldı:

| Ne | Sonucu | Çözüm |
|---|---|---|
| `.gitignore`'da `models/` | `app/models/` git tarafından **sessizce yok sayılıyordu** — 6 tablo PR'a hiç girmeyecekti | `/models/` (başına eğik çizgi) |
| `alembic.ini`'de Türkçe | Her alembic komutu `UnicodeDecodeError` veriyordu (o dosya locale kodlamasıyla okunuyor) | Dosya **sadece ASCII**; Türkçe açıklamalar `env.py`'de |
| Alembic'in ürettiği dosyalar lint'e uymuyor | Her migration CI'yı kırardı | `post_write_hooks` ile otomatik `ruff` |
| SQLite koruma kuralları kapalı | `CASCADE` tanımları süstü, tutarsız veri yazılabiliyordu | `PRAGMA foreign_keys=ON` her bağlantıda |
| Tohum migration'ı çakıştı | Mevcut satır varsa `upgrade` yarıda kalıyordu | Yalnızca eksik satırlar ekleniyor |
| Migration çıktısını filtrelemek | Hata mesajı görünmedi, migration'ın çöktüğü fark edilmedi | Migration çıktısı **filtrelenmez** |

---

## 6. Sırada ne var?

**FAZ 2 — LLM katmanı (~10 gün)**

| Adım | İş |
|---|---|
| B2.1 | `ollama pull qwen2.5:1.5b-instruct` + istemci. **Token/saniyeyi ölç ve yaz** |
| B2.2 | Yapılandırılmış çıktı şemaları (20/20 geçerli JSON) |
| B2.3 | Türkçe soru → araç seçimi. **30 soruluk taban çizgiyi ölç ve kaydet** |
| B2.4 | Gerçek gerekçe üretimi |
| **B2.5** | ⭐ **`guard.py`** — projenin en kritik parçası |
| B2.6 | Gecelik iş + tetikleyiciler (2.000 SKU < 10 dk) |

**Ölçümleri zamanında yapmak önemli:** B2.1'deki token/saniye ve B2.3'teki 30
soruluk doğruluk, Faz 3'te "eğitim işe yaradı mı" sorusunun tek cevabı. Şimdi
ölçülmezse o cevap kalıcı olarak kaybolur.

**Bir de:** Faz 2'ye girmeden `contracts.py`'deki bir kusuru Melih'le birlikte
düzeltmek gerekiyor. `izinli_sayilar()` içindeki "×100" kuralı oranlar için
yazılmış ama tam sayı adetlerde de tetikliyor. Örnek: `son_hareket_gun_once=1`
olan bir ürün için `100` sayısı izinli hale geliyor, yani model *"stok %100
tükendi"* diye uydursa guard bunu geçirir.

---

## 7. Faydalı komutlar

```bash
uv sync
```

```bash
uv run pytest
```

```bash
uv run ruff check .
```

```bash
uv run alembic upgrade head
```

```bash
uv run uvicorn app.main:app --reload
```

Sonra <http://localhost:8000> → Swagger arayüzü açılır.

---

## 8. Güncelleme geçmişi

| Tarih | Ne oldu |
|---|---|
| 2026-07-30 | Adım 0 (ortam), Adım 1 (okuma), B1.1–B1.6 tamamlandı. Kişi A'nın PR'ı incelendi. Faz 1 bitti. |
