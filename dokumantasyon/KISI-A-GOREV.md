# Kişi A — Veri & Alan · Görev Dosyası

> ⚠️ **GÜNCELLEME (2026-08-08): bu dosya artık bir GÖREV ATAMASI değil,
> KONTROL LİSTESİ.**
>
> Proje iki geliştiriciyle (Kişi A / Kişi B) planlanmıştı; gerçekte tek kişi
> + AI asistanı ile yürüdü ve iki tarafın işi de yapıldı. Aşağıdaki adımlar
> hâlâ geçerli — ama "senin işin / onun işi" ayrımı yok.
>
> Yürürlükteki süreç kuralları: [YOL-HARITASI.md](YOL-HARITASI.md#tek-kişilik-düzende-neler-değişti)
> · Ölçülmüş durum: [RAPOR.md](RAPOR.md)

> Bu dosya kendi başına yeterlidir. Projeyi hiç bilmiyorsan baştan sonuna oku,
> sonra "Hemen başla" bölümündeki komutları çalıştır.

---

## 1. Ne yapıyoruz?

Codifya ERP'ye bir **yapay zekâ karar mekanizması** kuruyoruz. Sistem stok, finans,
satış ve üretim alanlarında karar üretecek; düşük riskli olanları kendi uygulayacak,
yükseklerini insan onayına düşürecek.

**Kritik tasarım kısıtı:** Elimizde 16 GB RAM'li, GPU'suz bilgisayarlar var. Bu yüzden
1B parametreli küçük bir dil modeli (LLM) kullanacağız. Ama 1B model **sayısal karar
veremez** — emniyet stoğu, marj, risk hesaplarında uydurma yapar. Bu yüzden mimari
hibrit:

```
Sayısal kararı   →  KURAL MOTORU + küçük ML     ←  SENİN İŞİN
Türkçe metni     →  1B LLM                       ←  Kişi B'nin işi
```

**Yani sistemin gerçek zekâsı senin yazdığın kodda.** LLM sadece senin hesapladığın
sayıları Türkçe cümleye çeviriyor. Bu bir küçümseme değil, mimarinin özü: LLM'in
uyduramayacağı tek şey, ona hazır verilen sayılar.

---

## 2. Senin sahiplendiğin dosyalar

| Dosya | Ne yapacak |
|-------|-----------|
| `simulator/catalog.py` | ~2.000 SKU, ~60 tedarikçi, ~800 müşteri üretir |
| `simulator/company.py` | Sanal KOBİ profili konfigürasyonu |
| `simulator/demand.py` | Günlük talep süreci (sezon, trend, promo, gürültü) |
| `simulator/run.py` | 3 yıllık günlük olay döngüsü |
| `simulator/pathologies.py` | Enjekte edilen sorunlar (gecikme, talep patlaması...) |
| `app/domain/stock/features.py` | Ham veri → `StockFeatures` |
| `app/domain/stock/rules.py` | ROP, EOQ, ABC/XYZ, ölü stok, tedarikçi skoru |
| `app/domain/stock/ml.py` | Talep tahmini + anomali |
| `app/domain/stock/decide.py` | Hepsini birleştirip karar üretir |
| `training/build_dataset.py` | Eğitim verisi üretimi |
| `training/label_rationale.py` | Büyük LLM ile gerekçe etiketleme |

**Hiç dokunmayacağın yerler:** `app/api/`, `app/core/`, `app/llm/`, `app/jobs/`,
`app/models/`, `training/train_lora.ipynb`. Bunlar Kişi B'nin. Bir şey gerekiyorsa
ona söyle, sen yazma — yoksa aynı dosyada çakışırsınız.

**Öğreneceğin şeyler:** pandas, numpy, olasılık dağılımları, stok yönetimi formülleri,
scikit-learn/XGBoost, Parquet. FastAPI ve LLM öğrenmene gerek yok.

**Nerede çalışacaksın:** Her şey **yerelde** — `uv` ile kurulu proje, Jupyter Lab
kendi makinende. Google Colab'a ihtiyacın yok; Colab yalnızca Faz 3'teki GPU'lu
model eğitimi için ve o iş Kişi B'nin. (İstersen pandas/numpy öğrenirken deneme
notebook'larını Colab'da tutabilirsin, ama **proje kodu repoda yaşar** — Colab
oturumu kapanınca içindeki her şey siliniyor.)

---

## 3. Bilmen gereken tek dosya: `app/contracts.py`

Bu dosya **dondurulmuştur** — sen ve Kişi B arasındaki sınır. Sen bu tipleri
*üretiyorsun*, o *tüketiyor*. Bu sayede birbirinizi beklemeden çalışabiliyorsunuz.

Üç şeye bak:

**`StockFeatures`** — bir SKU hakkında kural motorunun gördüğü her şey. Senin
`features.py`'nin çıktısı bu.

**`FiredRule`** — tetiklenen bir kuralın izi: kod + Türkçe açıklama + kullanılan sayılar.
Bir kural bir sayı hesapladıysa `degerler` sözlüğüne **yazmak zorundasın**. Sebebi
aşağıda.

**`DecisionCandidate`** — senin ürettiğin nihai karar. İçinde `izinli_sayilar()` diye
bir metot var; şunu yapıyor: özellikler + kural değerleri + aksiyondan, gerekçe
metninde geçmesine izin verilen sayıların tam kümesini çıkarıyor.

> **Bu yüzden `degerler` sözlüğünü doldurmak kritik.** Kişi B'nin yazacağı "guard",
> LLM'in ürettiği metindeki her sayıyı bu kümeyle karşılaştırıyor. Kümede olmayan bir
> sayı görürse metni reddediyor. Yani bir kuralın hesapladığı sayıyı `degerler`'e
> yazmazsan, LLM o sayıyı gerekçede kullanamaz — çünkü "uydurma" sayılır.

Örnek (`decide.py` içindeki mevcut stub'dan):

```python
FiredRule(
    kod="ROP_ALTINDA",
    aciklama="Kullanılabilir stok yeniden sipariş noktasının altına düştü.",
    degerler={"rop": 615.0, "kullanilabilir_stok": 270.0, "emniyet_stogu": 111.0},
)
```

---

## 4. Hemen başla

### 4.1 · Ortam kurulumu (kendi PC'nde, bir kez)

> ⚠️ **Bu adımı atlamayın.** Bu makinelerde C: sürücüsünde ~3 GB boş yer var.
> Python paketleri ve model dosyaları varsayılan olarak C:'ye iner ve ilk günde
> diskiniz dolar; hatalar da nedeni anlaşılmaz şeyler olur.

PowerShell'de:

```powershell
[Environment]::SetEnvironmentVariable("UV_CACHE_DIR","D:\ERP\.cache\uv","User"); [Environment]::SetEnvironmentVariable("HF_HOME","D:\ERP\.cache\huggingface","User"); [Environment]::SetEnvironmentVariable("PIP_CACHE_DIR","D:\ERP\.cache\pip","User"); [Environment]::SetEnvironmentVariable("TORCH_HOME","D:\ERP\.cache\torch","User"); [Environment]::SetEnvironmentVariable("UV_PYTHON_INSTALL_DIR","D:\ERP\.cache\uv-python","User")
```

Terminali **kapat, yeniden aç**, sonra doğrula (ikisi de `D:\ERP\.cache\...` göstermeli):

```powershell
$env:UV_CACHE_DIR; $env:HF_HOME
```

`uv` kurulu değilse:

```powershell
winget install --id=astral-sh.uv -e
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

25 test geçmeli. Geçmiyorsa Kişi B'ye söyle, kendi kodunla ilgisi yok.

### 4.3 · Ne halde olduğunu gör

```bash
uv run uvicorn app.main:app --reload
```

<http://127.0.0.1:8000/docs> → `POST /v1/decisions/stock/reorder-review` dene.
Şu an **sabit stub veri** dönüyor: `decide_stub()` elle yazılmış bir karar.
Senin işin bunu gerçeğiyle değiştirmek.

Sonra `app/domain/stock/decide.py`'yi aç ve oku. Hedefin bu dosya.

---

## 5. Görev listesi

Süreler günde ~4-6 verimli saat varsayıyor, öğrenme dahil.
Her adım kendi branch'inde: `git checkout -b a/simulator-catalog` gibi.

### FAZ 1 — Simülatör (~10 gün)

Neden simülatör? Elimizde gerçek ERP verisi yok. Modeli eğitmek için veri gerek,
ayrıca kural motorunun iyi çalışıp çalışmadığını ölçmek için de "gerçeği bildiğimiz"
bir dünya gerek. Simülatör hem veri kaynağı hem ölçüm laboratuvarı.

---

#### A1.1 · `simulator/catalog.py` — Katalog üreteci · 1,5 gün

**Yapılacak:** Deterministik (seed'li) olarak üret:
- ~2.000 SKU: ad, kategori, birim maliyet, satış fiyatı, tedarikçi, paket adedi, MOQ, raf ömrü
- ~60 tedarikçi: tedarik süresi ortalaması + std, güvenilirlik
- ~800 müşteri: segment, ödeme alışkanlığı

Şirket profili önerisi: **yapı malzemesi toptancısı** — sezonsallığı belirgin
(inşaat sezonu), stok mantığı temiz, Türkçe ürün adları doğal (tuğla, çimento, demir,
alçı, boya, seramik...).

**Öğrenmen gereken:**
- `numpy.random.default_rng(seed)` — eski `np.random.seed` değil, yeni Generator API
- `dataclass` veya pydantic model ile veri sınıfı tanımlama
- Pareto dağılımı: gerçek hayatta ürünlerin %20'si cironun %80'ini yapar

**Bitti sayılır:**
1. Fonksiyonu aynı seed ile iki kez çağırdığında **bit bit aynı** çıktı geliyor
2. Ciro dağılımını sıraladığında üst %20 SKU cironun ~%80'ini taşıyor

---

#### A1.2 · `simulator/demand.py` — Talep süreci · 2,5 gün

Projenin en zevkli ve en belirleyici parçası. Kötü bir talep modeli, sonradan yazdığın
her şeyi değersizleştirir.

**Yapılacak:** SKU başına günlük talep:

```
talep = temel_hız × trend × yıllık_sezon × haftalık_desen × promo_etkisi × gürültü
```

- **trend:** yıllık yavaş büyüme/küçülme
- **yıllık_sezon:** sinüs bileşeni — inşaat sezonu (ilkbahar-yaz zirve), ayrıca
  Ramazan/bayram etkileri
- **haftalık_desen:** pazar kapalı, cumartesi yarım, hafta içi normal
- **gürültü:** hızlı hareket edenler için **negatif binom**, yavaş/aralıklı talep için
  Bernoulli × miktar

**Öğrenmen gereken:**
- Sezonsallığı sinüsle modellemek: `1 + genlik * sin(2*pi*(gun/365 - faz))`
- **Neden Poisson yetmez:** Poisson'da varyans = ortalama. Gerçek talep "aşırı
  yayılımlı" (overdispersed) — varyans ortalamadan büyük. Negatif binom bunu modeller.
  Poisson kullanırsan talep gerçeğinden fazla düzgün çıkar ve emniyet stoğu hesabın
  yanlış kalibre olur.
- **Aralıklı talep (intermittent demand):** yavaş hareket eden ürün çoğu gün 0 satar,
  arada 5 satar. Bunu ortalamayla modellemek büyük hata.

**Bitti sayılır:** Tek bir SKU'nun 3 yıllık talebini `matplotlib` ile çiz. Grafikte
**trend + yıllık dalga + haftalık diş diş yapı gözle görülüyor** olmalı.
Bu grafiği çizmeden bu adım bitmez — çizip Kişi B'ye göster.

---

#### A1.3 · `simulator/run.py` — Olay motoru · 2,5 gün

**Yapılacak:** 3 yıl × günlük döngü. Her gün sırayla:
1. Müşteri siparişleri düşer
2. Stok varsa sevk edilir; **yoksa karşılanamayan talep ayrı bir tabloya kaydedilir**
   (bu tablo Faz 5'te para metriğinin yarısı)
3. Basit bir sipariş politikası tedarikçiye sipariş açar
4. Yoldaki siparişler tedarik süresi sonunda gelir (gecikme olabilir)
5. Faturalar kesilir, ödemeler gecikmeli gelir

**Öğrenmen gereken:** olay tabanlı simülasyon döngüsü, "yoldaki stok" (in-transit)
takibi — sipariş verilmiş ama gelmemiş miktarı da hesaba katmak zorundasın, yoksa
üst üste sipariş verirsin.

> ⚠️ **Buradaki sipariş politikası KASITLI OLARAK VASAT olmalı.**
> Örnek: "stok 10 günlük tüketimin altına düşerse 30 günlük sipariş ver."
> Sebebi: Faz 5'te senin kural motorunu **buna karşı** ölçeceğiz. Bu senin
> taban çizgin (baseline). Buraya akıllı bir politika yazarsan kıyaslayacak
> bir şey kalmaz.

**Bitti sayılır:**
1. Stok hiçbir zaman negatife düşmüyor
2. Karşılanamayan talep ayrı tabloda kayıtlı
3. **Mutabakat testi geçiyor:** toplam giriş − toplam çıkış = son stok

---

#### A1.4 · `simulator/pathologies.py` — Patolojiler · 1,5 gün

**Yapılacak:** Enjekte edilecek sorunlar, her biri config ile açılıp kapanabilir:
- tedarikçi gecikmesi
- ani talep patlaması (2-3 kat)
- ölü stok birikmesi
- tedarikçi fiyat zammı
- sezon sonu fazlası
- sayım farkı (fiziksel sayım ile kayıt uyuşmazlığı)

Her enjeksiyonun **ne zaman yapıldığını ayrı bir log tablosuna yaz.**

**Neden log:** "modelimiz bu olayı yakaladı mı?" sorusunu ancak olayın ne zaman
olduğunu bilirsen ölçebilirsin. Bu log, Faz 5 değerlendirmesinin dayanağı.

**Bitti sayılır:** patolojiler kapalıyken veri "sağlıklı", açıkken belirgin sorunlu.

---

#### A1.5 · Çıktı + veri kalitesi notebook'u · 1,5 gün

**Yapılacak:**
- Tabloları Parquet olarak `data/sim/<seed>/` altına yaz (`pyarrow`)
- Bir Jupyter notebook: temel istatistikler, stok/talep grafikleri, mutabakat
  kontrolleri, patoloji zaman çizgisi

```bash
uv run jupyter lab
```

**Bitti sayılır:** notebook baştan sona hatasız çalışıyor **ve Kişi B notebook'a
bakıp verinin mantıklı olduğunu onaylıyor.** Bu onay önemli — kendi verine kör
olursun, ikinci bir göz şart.

> **🔗 Buluşma noktası (SP1):** Simülasyon verisini ve notebook'u Kişi B'ye göster.
> O da sana onay kuyruğu akışını gösterir.

---

### FAZ 2 — Kural motoru + ML (~10 gün)

Sistemin gerçek zekâsı bu fazda yazılıyor. Tamamı saf fonksiyon (aynı girdiye aynı
çıktı), tamamı birim testli, LLM'e hiç dokunmuyor.

---

#### A2.1 · `features.py` — Özellik çıkarımı · 1,5 gün

**Yapılacak:** Parquet'ten ham veriyi oku, `StockFeatures` üret. Ortalama günlük talep
ve standart sapmayı **kayan pencereyle** hesapla (30 ve 90 gün).

**Bitti sayılır:** rastgele 5 SKU için değerleri elle (Excel'de bile olur) hesapla,
fonksiyonun çıktısıyla karşılaştır — örtüşmeli.

---

#### A2.2 · `rules.py` — Emniyet stoğu + ROP · 1,5 gün

**Yapılacak:**

```
emniyet_stoğu = Z(servis_seviyesi) × √(tedarik_süresi × talep_std²
                                       + ort_talep² × tedarik_süresi_std²)

ROP = ort_günlük_talep × tedarik_süresi + emniyet_stoğu
```

**Öğrenmen gereken:**
- Servis seviyesi ↔ Z skoru: `scipy.stats.norm.ppf(0.95)` → 1.645
- **Neden karekökün içinde iki terim var:** çoğu kaynak sadece talep belirsizliğini
  yazar. Ama tedarikçi bazen 12 gün bazen 17 günde getiriyorsa, bu belirsizlik de
  emniyet stoğu gerektirir. İkinci terimi atlarsan sistematik olarak stok tükenmesi
  yaşarsın — ve simülasyonda bunu göreceksin.

**Bitti sayılır (sınır durum testleri):**
1. Servis seviyesi %90 → %99 çıkarıldığında emniyet stoğu **artıyor**
2. İki std de 0 iken emniyet stoğu **0** oluyor

---

#### A2.3 · Sipariş miktarı — EOQ + MOQ · 1 gün

**Yapılacak:** EOQ (ekonomik sipariş miktarı) hesapla, sonra tedarikçinin **minimum
sipariş adedine (MOQ)** ve **paket katına yukarı yuvarla.**

Gerçek dünyada 1.187 adet tuğla sipariş edilmez — 1.200 edilir (paket 100'lük).
Bu yuvarlamayı atlarsan çıktın kâğıt üzerinde doğru, sahada kullanılamaz olur.

**Bitti sayılır:** çıktı her zaman MOQ'dan büyük **ve** paket adedinin tam katı.

---

#### A2.4 · ABC/XYZ sınıflandırma · 1 gün

**Yapılacak:**
- **ABC:** ciro katkısına göre, kümülatif %80 / %95 kesimleri
- **XYZ:** talep varyasyon katsayısına göre (σ/μ)

Sonra **servis seviyesi hedefini bu matristen türet**: AX ürününe %99, CZ ürününe %85
gibi. Bu değer A2.2'deki emniyet stoğu hesabına girdi olur.

Mantık: cirosu yüksek ve talebi düzenli ürünün stoğu tükenmesin (pahalıya gelir,
kolay tahmin edilir). Cirosu düşük ve talebi kaotik ürün için yüksek servis seviyesi
tutmak, boşa para bağlamaktır.

**Bitti sayılır:** 2.000 SKU sınıflandırıldığında A sınıfı ~%20 kalem / ~%80 ciro.

---

#### A2.5 · Ölü stok + tedarikçi skoru · 1,5 gün

**Ölü stok:** N gündür hareketsiz + kalan raf ömrü + bağlı sermaye → tasfiye/iskonto önerisi.

**Tedarikçi skoru (0-100):** zamanında teslim oranı, fiyat sapması, iade/red oranı,
tedarik süresi varyansı — ağırlıklı toplam.

**Bitti sayılır:** simülasyonda kasıtlı olarak kötü davranan tedarikçi, skor listesinin
**en altında** çıkıyor. Çıkmıyorsa ağırlıkların yanlış.

---

#### A2.6 · ⭐ `decide.py` — Gerçek karar üretimi · 1,5 gün

**Yapılacak:** `decide_stub()`'ı gerçeğiyle değiştir:
- Tüm kuralları çalıştır
- Tetiklenen her kural için `FiredRule` kaydet (kod + açıklama + **kullanılan sayılar**)
- `guven` skorunu hesapla: veri yeterliliği (`veri_gun_sayisi`) + kural mutabakatı +
  tahmin belirsizliği
- `DecisionCandidate` döndür

**Bitti sayılır:** Kişi B'nin endpoint'i **tek satır** değişiklikle (stub → gerçek)
çalışıyor ve onun kodunda **başka hiçbir şey değişmiyor.**

> Bu, sözleşmenin sınavıdır. B'nin kodunda başka şeyler değişmek zorunda kalıyorsa
> sözleşme sızmış demektir — ikiniz oturup konuşun.

---

#### A2.7 · `ml.py` — Talep tahmini · 2 gün

**Yapılacak:** SKU başına ayrı model **değil**, tüm SKU'lar için **tek bir XGBoost**
(SKU kimliği/kategorisi özellik olarak girer). Özellikler: gecikmeli talep (lag),
hareketli ortalamalar, haftanın günü, ay, promo bayrağı, tatil.

Aralıklı talepli yavaş hareket edenler için **Croston yöntemi** ayrı ele alınır.
`joblib` ile modeli diske yaz.

**Öğrenmen gereken:**
- ⚠️ **Zaman serisinde train/test bölmesi TARİHE göre yapılır.** Rastgele bölersen
  gelecekteki veriyle geçmişi tahmin etmiş olursun; skorun harika çıkar, gerçekte
  çalışmaz. Bu, bu işte en sık yapılan hata.
- MAE ve MASE metrikleri

**Bitti sayılır:** tahmin, "son 30 günün ortalaması" naif taban çizgisinden
**ölçülebilir şekilde iyi.**

> **Değilse XGBoost'u kullanma, naif ortalamayı kullan ve bunu dürüstçe raporla.**
> KOBİ ölçeğinde ve simülasyon verisinde bu senaryo gerçekten olabilir. Çalışmayan
> bir ML modelini "çalışıyor" diye bırakmak, sonraki her ölçümü zehirler.

---

#### A2.8 · Anomali + oracle karşılaştırması · 1 gün

**Anomali:** `IsolationForest` ile beklenmedik tüketim sıçraması, fiyat sapması.

**Oracle karşılaştırması:** kural motorunun kararlarını simülasyonun *gerçekleşen*
talebiyle karşılaştıran bir script. "Talebi mükemmel bilseydik ne yapardık" (oracle)
ile arayı ölç.

**Bitti sayılır:** kural motorun, A1.3'teki vasat taban politikadan **daha iyi**;
oracle'dan **daha kötü**. İkisinin arasında değilse bir yerde hata var:
- Taban politikadan kötüyse → kurallarda hata
- Oracle'dan iyiyse → değerlendirmede sızıntı var (imkânsız bir sonuç)

> **🔗 Buluşma noktası (SP2):** `decide.py` B'nin servisine bağlanır. Sistem ilk kez
> gerçek veri üzerinde gerçek karar verip Türkçe gerekçelendiriyor. **Bu noktada
> LLM eğitimi hiç yapılmamış olsa bile sistem çalışıyor.**

---

### FAZ 3 — Eğitim verisi üretimi (~7 gün)

Artık kural motoru çalışıyor. Şimdi LLM'e Türkçe konuşmayı öğretmek için veri
üretiyoruz. **Etiketler senin kural motorundan geliyor** — deterministik olduğu için
halüsinasyon imkânsız.

> **Bu fazda veriyi Kişi B'ye Google Drive üzerinden teslim ediyorsun.** O, ücretsiz
> Colab'da eğitim yapacak. Paylaşılan klasör:
> `MyDrive/codifya/veri/` — sen yazarsın, o okur.
> Veri Drive'a **bir kez** konur; her Colab oturumunda yeniden yüklemek onun 10-20
> dakikasını yakar ve oturum kopma riskini artırır.

> ⚠️ **İlk iş: 100 örneklik küçük bir dosya çıkar ve Drive'a koy** (`veri/ornek_100.jsonl`).
> Tam veri setini beklemesin — Kişi B bu 100 örnekle Colab eğitim hattının baştan sona
> çalıştığını kanıtlayacak (buluşma noktası SP2.5). Ücretsiz Colab'da tam eğitim 4-7 saat
> sürüyor; hattın 3. saatinde çıkacak bir biçim hatası hem saatleri hem bir oturumu yakar.
> Bu 100 örnek, projenin en yüksek getirili yarım günü.

---

#### A3.1 · `build_dataset.py` — Karar noktası örnekleme · 1,5 gün

**Yapılacak:** Simülasyon zaman çizgisinden karar noktaları örnekle (SKU × hafta).
Her nokta için özellikleri çıkar, kural motorunu çalıştır → **çıkan karar etikettir.**

Sınıf dengesine dikkat: "sipariş gerekmiyor" durumları da yeterince olsun, yoksa model
her şeye "sipariş ver" der.

**Bitti sayılır:** ~50.000 karar noktası JSONL olarak yazılmış;
sipariş / sipariş-yok / tasfiye dağılımı raporlanmış.

---

#### A3.2 · Router soru şablonları · 1,5 gün

**Yapılacak:** Her araç için 30-50 Türkçe soru şablonu. Varyantları unutma:
- resmi: *"Kritik stok seviyesine düşen ürünleri listeler misiniz?"*
- günlük: *"hangi üründe stok azaldı"*
- kısaltmalı: *"kritik stok var mı"*
- yazım hatalı: *"stok durmu ne"* ← gerçek kullanıcı böyle yazar

Şablon × varlık = veri.

**Bitti sayılır:** ~30.000 çift üretilmiş; elle 50 tanesini okuyup doğal bulmuşsun.

---

#### A3.3 · Büyük LLM ile başkalaştırma · 1 gün

Şablonlar tek başına yetersiz çeşitlilik verir. Ucuz/hızlı bir büyük modelle soruları
başkalaştır (paraphrase).

> **Önce maliyeti ölç:** 100 örnekle çalıştır, token maliyetini gör, 30.000'e çarp,
> sonra devam et. Ölçmeden tam veri setini çalıştırma.

---

#### A3.4 · ⭐ `label_rationale.py` — Gerekçe etiketleme · 2 gün

**Yapılacak:** (özellikler + karar) → Türkçe gerekçe, büyük LLM yazar.

**Sonra Kişi B'nin `guard.py`'sini etiketleme hattında kullan:** girdide olmayan sayı
içeren örnek veri setine **alınmaz**. Reddedilme oranını raporla.

**Neden kritik:** eğitim verisi halüsinasyon içeriyorsa 1B modele halüsinasyonu
öğretirsin. Guard'ı hem eğitim verisinde hem çalışma zamanında kullanmak, kirliliği
kaynağında keser.

**Bitti sayılır:** ~25.000 doğrulanmış gerekçe; reddedilme oranı biliniyor.
**%15'in üzerindeyse prompt'u düzelt, veriyi kabul etme.**

---

#### A3.5 · Bölme + golden set · 1,5 gün (son yarım günü Kişi B ile birlikte)

**Yapılacak:** train/val/test bölmesi — **SKU ve tarih bazında ayır, rastgele değil.**
Aynı SKU hem eğitimde hem testte olursa sonuç yalan çıkar.

Sonra ikiniz **birlikte** 300-500 örneği elle gözden geçirip `golden_set.jsonl`
oluşturun. Zorlayıcı vakaları elle ekleyin: veri yok, çelişkili kurallar, aşırı değerler.

**Bitti sayılır:**
1. Bölme tarih + SKU bazında yapılmış
2. Tam veri seti (`train.jsonl`, `val.jsonl`, `test.jsonl`) **Drive'daki
   `codifya/veri/` klasöründe** — Kişi B buradan okuyacak
3. Golden set ikinizin onayından geçmiş. Bu dosya projenin karnesi.

> Kişi B eğitimi kademeli yapacak (15k → 35k → 55k). 1. turdan 2. tura kayda değer
> iyileşme çıkmazsa darboğaz veri *miktarı* değil, veri *kalitesi* demektir — o zaman
> ikiniz A3.4'teki guard reddedilme oranına bakacaksınız. Bu yüzden o oranı bir yere
> yazmayı unutma.

---

### FAZ 4-5 — Senin payın (~4 gün)

- **4.2** 3 farklı şirket profiliyle simülasyon üret (aşırı uyumu test et) — motor
  hepsinde makul davranmalı
- **4.4** Karşılanamayan talep + aşırı stok maliyetini hesaplayan script
- **5** Para metriği: tutulmamış bir simülasyon koşusunda *senin kural motoru* vs
  *vasat taban politika* vs *oracle* → stok tükenme oranı, aşırı stok maliyeti,
  toplam maliyet

> **Faz 5'in çıktısı raporun merkezidir:** "model şu kadar iyi cevap veriyor" değil,
> **"AI politikası toplam stok maliyetini %X düşürdü, stok tükenmesini %Y azalttı."**
> İş değerini gösteren tek sayı bu ve onu sen üretiyorsun.

---

## 6. Çalışma disiplini

| Ne | Nasıl |
|----|-------|
| **Günlük senk** | Her sabah 15 dk, Kişi B ile: "bugün ne yapıyorum / neye takıldım / senden ne bekliyorum" |
| **Branch** | Her adımda yeni: `a/simulator-demand`, `a/rules-rop` |
| **PR** | `main`'e direkt push YOK. PR aç, **Kişi B onaylamadan merge etme** |
| **PR incelemesi** | Sen de onun PR'larını incele. Bu kalite kontrolü değil, öğrenme — ikiniz de tüm sistemi tanıyın |
| **Merge öncesi** | `uv run pytest` ve `uv run ruff check .` geçmeli |

```bash
uv run pytest && uv run ruff check .
```

Kod biçimlendirme:

```bash
uv run ruff format .
```

## 7. Takıldığında

1. **`app/contracts.py`** — üreteceğin nesnelerin tanımı orada, docstring'leri oku
2. **`app/domain/stock/decide.py`** — mevcut stub, gerçekçi örnek değerlerle dolu;
   hedefin bunun gerçek hali
3. Her yer tutucu dosyanın docstring'inde **kimin, hangi fazda** yazacağı belirtilmiş
4. Sözleşmede eksik bir alan varsa **kendi başına ekleme** — Kişi B ile konuş,
   tek PR'da birlikte ekleyin
