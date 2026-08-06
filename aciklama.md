# Açıklama — Codifya Karar Motoru, basit dille

> Bu dosya, projede yapılan her önemli adımın **sade Türkçe** özetidir. Kod
> detaylarını değil, "ne yaptık ve neden yaptık"ı anlatır.
>
> **İki bölümden oluşur:** Kişi A (Melih — Veri & Alan) ve Kişi B (Esmanur —
> Servis & Model). Herkes kendi bölümünü günceller; ortak bölümler birlikte.
> Kod değişti ama burası değişmediyse, burası yanlıştır.

---

## Genel resim: ne inşa ediyoruz?

Codifya ERP'ye bir **yapay zekâ karar mekanizması** ekliyoruz. Amaç: stok
yönetiminde ("şu üründen ne zaman, ne kadar sipariş verilsin?") kararları
otomatikleştirmek. Ama küçük bir dil modeli (1,5B parametre, GPU'suz makinede
çalışacak) sayısal hesap yapamıyor — uydurma yapar. Bu yüzden mimari
**hibrit**:

- **Sayısal karar** → kural motoru + basit ML (Kişi A'nın işi)
- **Türkçe açıklama metni** → küçük LLM (Kişi B'nin işi)

İki kişi `app/contracts.py` adında dondurulmuş bir "sözleşme" üzerinden
anlaşıyor — Kişi A ürettiği veri tiplerini Kişi B tüketiyor, birbirlerini
beklemeden paralel çalışabiliyorlar.

### Sistemi ayakta tutan iki kural

**1. Dil modeli asla sayı üretmez.** Sayılar ona *verilir*, o sadece cümleye
yerleştirir. Ürettiği metindeki her sayı, karardan gelen "izinli sayılar"
kümesinde yoksa metin **reddedilir**. Bu kontrolü yapan koda **guard** deniyor
(Faz 2 B2.5) — projenin en kritik parçası.

**2. ERP asla dil modelini beklemez.** Karar milisaniyelerde çıkar. Gerekçe
metni ancak istenirse üretilir (CPU'da 6-8 saniye sürüyor).

---

## Kim ne yapıyor?

| | Kişi A (Melih) | Kişi B (Esmanur) |
|---|---|---|
| **Sahiplendiği** | `simulator/`, `app/domain/stock/`, `training/build_dataset.py`, `training/label_rationale.py` | `app/api/`, `app/core/`, `app/models/`, `app/llm/`, `app/jobs/`, `training/train_lora.ipynb`, CI |
| **Öğrendiği** | pandas, numpy, stok formülleri, XGBoost, Parquet | FastAPI, SQLAlchemy, pytest, Ollama, LoRA eğitimi |

`app/contracts.py` **dondurulmuş** — tek taraflı değiştirilmez, iki kişi
birlikte tek PR'da değiştirir.

---

## Şu an neredeyiz?

| Faz | Kişi A | Kişi B |
|---|---|---|
| **Faz 1** | ✅ Simülatör | ✅ Veri katmanı + API + CI |
| **Faz 2** | ✅ Kural motoru + ML | 🔄 LLM katmanı (B2.1 başladı) |
| **Faz 3** | ✅ A3.1–A3.4 · ⬜ A3.5 (B ile birlikte) | ⬜ LoRA eğitimi |
| **Faz 4-5** | ✅ Genellenebilirlik + para metriği | ⬜ Sağlamlaştırma + benchmark |

---
---

# KİŞİ A — Veri & Alan (Melih)

## A · Faz 1 — Simülatör (TAMAMLANDI ✅)

Elimizde gerçek ERP verisi olmadığı için, önce **sahte ama gerçekçi bir
dünya** kurduk — bir yapı malzemesi toptancısı hayal edip onun 3 yıllık
geçmişini simüle ettik.

1. **`company.py`** — şirket profili: 2000 ürün, 60 tedarikçi, 800 müşteri;
   8 kategori (çimento, demir, tuğla, boya...) her birinin kendi
   maliyet/marj/sezonsallık özellikleriyle.
2. **`catalog.py`** — bu profile göre gerçek katalog verisi üretti: her
   ürüne isim, fiyat, tedarikçi, paket büyüklüğü atadı. Önemli detay:
   ürünlerin **%20'si cironun %80'ini** taşıyacak şekilde kurgulandı
   (Pareto ilkesi — gerçek hayatta da böyledir).
3. **`demand.py`** — her ürün için 3 yıllık günlük talep üretti: mevsimsellik
   (yaz aylarında inşaat sezonu zirvesi), haftalık desen (pazar kapalı),
   yıllık trend, ve gerçekçi rastgelelik (bazı ürünler düzenli satar,
   bazıları seyrek ama toplu satar).
4. **`run.py`** — asıl simülasyon motoru: her gün sırayla müşteri siparişi
   düşürüp stoktan karşıladı, stok azalınca (kasıtlı olarak **kötü/vasat**
   bir kuralla — "10 günlük stok kalınca 30 günlük sipariş ver") tedarikçiye
   sipariş açtı. Bu vasat politika bizim **karşılaştırma tabanımız** —
   ileride yazılan akıllı kural motorunun "ne kadar daha iyi" olduğu buna
   göre ölçülecek.
5. **`pathologies.py`** — gerçek hayatta olan sorunları isteğe bağlı enjekte
   edebiliyoruz: tedarikçi gecikmesi, ani talep patlaması, ölü stok, fiyat
   zammı vb. Hepsi loglanıyor ki "sistemimiz bu sorunu yakaladı mı?" diye
   ölçülebilsin.
6. Son olarak bunları **Parquet dosyalarına** kaydettik ve bir **Jupyter
   notebook**'ta tüm grafikleri/kontrolleri belgeledik.

Bunu bitirince **`faz1-simulator`** adında bir GitHub branch'ine push edildi.

> **Kişi B'nin incelemesi (SP1):** A1.1–A1.5'in tüm kabul ölçütleri bağımsız
> olarak ölçüldü ve geçti — determinizm (11 tablo bit bit aynı), Pareto
> (%80,0), mutabakat farkı tam sıfır, patoloji ayrımı. Onaylandı.
> Ayrıca üç sözleşme boşluğu bulundu, aşağıda "Açık konular"da.

---

## A · Faz 2 — Kural motoru (TAMAMLANDI ✅)

Artık sahte dünyamız var, şimdi bu dünyaya bakıp **akıllı kararlar** üreten
kodu yazdık.

### `features.py`

Ham simülasyon verisinden (talep geçmişi, stok seviyesi) her ürün için bir
"özet kart" (`StockFeatures`) çıkarıyor: ortalama günlük talep, talep
değişkenliği, stok durumu, tedarikçi bilgisi vs. 30 ve 90 günlük hareketli
ortalamalarla hesaplanıyor.

### `rules.py`

Gerçek iş mantığı formülleri:

- **Emniyet stoğu + ROP**: "ne zaman sipariş verilmeli" hesabı — hem talebin
  hem tedarikçinin belirsizliğini hesaba katıyor.
- **EOQ + MOQ**: "ne kadar sipariş verilmeli" — ekonomik sipariş miktarı,
  ama gerçek dünyada olduğu gibi paket büyüklüğüne yuvarlanıyor (1187 tuğla
  değil, 1200 tuğla sipariş edilir).
- **ABC/XYZ sınıflandırma**: hangi ürün ne kadar önemli (ciroya göre) ve ne
  kadar öngörülebilir (talep düzenliliğine göre) — buna göre hedef servis
  seviyesi belirleniyor (önemli+düzenli ürüne %99 stok garantisi,
  önemsiz+kaotik ürüne %85 yeter).
- **Ölü stok tespiti**: uzun süredir satmayan ürünleri bulup
  iskonto/tasfiye öneriyor.
- **Tedarikçi skoru**: gerçekleşen teslimat performansına bakıp 0-100 puan
  veriyor (kötü tedarikçiyi tespit etmek için).

Bu adımda **iki gerçek hata bulunup düzeltildi**: tedarikçi skoru yanlış
indeksleniyordu (hep 100 puan çıkıyordu), ölü stok eşiği çok agresifti
(sağlıklı ürünleri bile "ölü" damgalıyordu). İkisi de gerçek veriyle test
edilerek yakalandı.

### `decide.py` (⭐ en kritik dosya)

Yukarıdakilerin **hepsini birleştiriyor**: bir ürün için özellikleri
çıkarır, kuralları çalıştırır, hangi kararı vereceğine karar verir (sipariş
ver / tasfiye et / bir şey yapma), ve bu kararın **güven skorunu**
hesaplar. Test edildi: gerçekten çalışıyor, mantıklı sonuçlar üretiyor
(örnek: bir ürün için "60 adet sipariş ver, T-0004 tedarikçisinden"
kararı + gerekçesi).

### `ml.py` — talep tahmini + anomali + oracle karşılaştırması

**A2.7 — Talep tahmini:** Hızlı hareket eden ürünler için tek bir XGBoost
modeli (SKU/kategori özellik olarak giriyor), çok yavaş/seyrek satan ürünler
için ise **Croston yöntemi** (aralıklı talebe özel bir istatistik yöntemi —
basit ortalama almak büyük hata olurdu). Eğitim/test bölmesi **tarihe göre**
yapıldı (rastgele değil — yoksa gelecekten geçmişe sızıntı olur).

Sonuç: model, "son 30 günün ortalaması" naif tahminden **%35 daha iyi**
çıktı (hata payı 3.87 → 2.50). Yani XGBoost gerçekten işe yarıyor, kullanıma
uygun.

**A2.8 — Anomali tespiti + oracle karşılaştırması:**

- Ani tüketim sıçraması ve fiyat sapması tespiti için IsolationForest
  kullanıldı. Fiyat sapması tespitinde ilk denemede bir hata buldum:
  tedarikçi bazında karşılaştırma yapıyordum, ama bir tedarikçi çok farklı
  fiyatlı ürünler taşıyabiliyor (5 TL'lik tuğla + 20.000 TL'lik demir), bu
  karışım gerçek zam sinyalini gizliyordu. **SKU bazında** karşılaştırmaya
  geçince başarı oranı %3.4'ten **%78.6'ya** çıktı.
- Talep sıçraması tespitinde ise dürüstçe söylemem gerekiyor: başarı oranı
  düşük kaldı (~%10-15) çünkü enjekte ettiğimiz "yapay" talep patlamaları,
  simülatörün zaten ürettiği doğal gürültüyle (promosyonlar, aralıklı satış
  dalgalanmaları) büyüklük olarak örtüşüyor — ayırt etmek zor. Bu bir kod
  hatası değil, iyileştirmeye açık bir sınırlama, olduğu gibi raporlanıyor.
- **Oracle karşılaştırması** (projenin en önemli ölçümü): aynı talep
  üzerinde üç politika paralel koşturuldu — **vasat taban** (Faz 1'deki
  kötü/kaba kural), **kural motorumuz** (ROP/EOQ formülleri), **oracle**
  (geleceği mükemmel bilen hayali politika). Sonuç beklendiği gibi çıktı:
  - Stok tükenme oranı: vasat %6.97 → kural motoru **%0.67** → oracle %0.05
  - Toplam maliyet (kayıp kâr + envanter + sipariş maliyeti): vasat 21.85M →
    kural motoru **18.66M** → oracle 15.50M TL

  Yani **kural motorumuz vasat politikadan kesin olarak daha iyi, mükemmel
  bilgiden (oracle) daha kötü** — beklenen ve istenen sonuç tam bu. Bu
  ölçüm ilk denemede tutmadı (oracle bir noktada kural motorundan "kötü"
  çıkmıştı), iki gerçek hata buldum ve düzelttim: (1) oracle'ın tedarik
  süresi belirsizliğini hesaba katmaması, (2) kayıp satışın ciro yerine
  kâr marjı + "itibar kaybı" çarpanıyla hesaplanması gerektiği, (3) EOQ'nun
  sipariş sıklığı avantajının maliyet toplamına hiç girmemesi.

`features.py`, `rules.py`, `decide.py`, `ml.py` — hepsi yazıldı, test
edildi, gerçek veriyle doğrulandı.

---

## A · Faz 3 — Eğitim verisi üretimi

Artık kural motoru çalışıyor. Şimdi bu motorun ürettiği kararları
örnekleyip küçük LLM'e "Türkçe konuşmayı" öğretecek eğitim verisini
hazırlıyoruz. Etiketler kural motorundan geldiği için (deterministik)
halüsinasyon imkânsız.

### `build_dataset.py` — A3.1 (bitti ✅)

3 yıllık simülasyon zaman çizgisinden **50.050 karar noktası** örnekledim
(SKU x hafta, rastgele gün). Her nokta için özellikler çıkarıldı, kural
motoru çalıştırıldı, sonuç `data/egitim/karar_noktalari.jsonl` dosyasına
yazıldı.

Dağılım: %67 "aksiyon yok", %25 "tasfiye", %8 "sipariş ver". Tasfiye oranı
ilk bakışta yüksek görünüyor ama bu bir hata değil — katalog Pareto
dağılımlı olduğu için (SKU'ların büyük kısmı az satan "kuyruk" ürünler),
gerçekten de ürünlerin önemli bir kısmı doğal olarak "ölü stok" sayılıyor.

İlk denemede bir performans sorunu buldum: her hafta için tüm 2.19 milyon
satırlık talep tablosunun tamamını yeniden işliyordum (143 kez tekrarlanınca
çok yavaşladı). SKU alt kümesine göre önceden filtreleyince çalışma süresi
makul seviyeye indi (~2 dakika).

### `build_dataset.py` — A3.2 (bitti ✅) — router soru şablonları

Kişi B'nin router'ı (`app/llm/router.py`, `app/api/ask.py`) henüz Faz 2
B2.2-B2.3'te yazılacak — yani gerçek bir "araç listesi" henüz yok. Bu yüzden
roadmap'teki tek somut ipucuna ve mevcut API stub'larına dayanarak **geçici
ama makul** 7 araç tanımladım: kritik stok, ölü stok, tedarikçi performansı,
sipariş önerisi, onay kuyruğu, gecelik özet, genel stok durumu. Kişi B
gerçek router şemasını yazınca bu liste güncellenip veri seti yeniden
üretilecek.

Sonuç: **24.999 soru-araç çifti** (`data/egitim/router_sorulari.jsonl`),
4 stil çeşitliliğiyle (resmi/günlük/kısaltmalı/yazım hatalı).

Burada da bir hata bulup düzelttim: ilk denemede yalnızca **1.884** satır
çıktı. Sebep: katalogdaki ürün isimleri sınırlı sayıda şablon+marka
kombinasyonundan üretiliyor, aynı isim onlarca farklı üründe tekrarlanabiliyor
— metin bazlı tekilleştirme bu tekrarların çoğunu eledi. Çözüm: soru metnine
ürün adının yanına SKU kodunu da eklemek (`"Portland Çimento 32.5 R - Çimsa
(S-01636)"`) — hem gerçekçi hem de benzersizliği garanti ediyor.

### A3.3 — büyük LLM ile soru başkalaştırma (bitti ✅, iki turda)

`training/paraphrase_colab.ipynb` yazıldı, Colab'da (T4 GPU, Qwen2.5-7B-Instruct
4-bit) çalıştırıldı. İki tasarım hatası bulunup düzeltildi:

1. **Performans:** İlk denemede 24.999 satırın HER BİRİ ayrı ayrı modele
   gönderiliyordu — 100 satır 357 sn, tüm veri seti ~25 saate karşılık
   geliyordu (Colab sınırı ~12 saat). Çözüm: yalnızca arkadaki **~84 benzersiz
   şablonu** başkalaştırıp sonucu yerelde gerçek varlıklarla çoğaltmak.
   ~250x hızlanma, ~5 dakikaya indi.
2. **Prompt sızıntısı:** Talimat metnindeki "tire" kelimesini model çıktının
   parçası sanıp taklit ediyordu. Kelime kaldırıldı, regex güvenlik ağı eklendi.

**Ama asıl sorun ilk turda çözülemedi:** Model bazı cümlelerde **anlamı
tersine çeviriyordu** — "listesini görebilir miyim?" → "listeden kaldırılmasını
istiyorum" gibi, ~%40 oranında. Eğitim verisi için kabul edilemez. Adım geçici
olarak **askıya alındı.**

**A3.4'ün dersleriyle geri dönüldü.** Orada aynı sınıf bir hatayı (karar
tipinin iş anlamını prompt'a yazmayınca modelin yönü karıştırması) çözmüştük.
İki düzeltme uygulandı:

1. **Niyet-koruma kuralı:** Prompt'a cümlenin bir SORU olduğu, asla KOMUT'a
   çevrilmemesi gerektiği açıkça yazıldı + doğru/yanlış örnek çifti.
2. **İkinci LLM ile doğrulama (guard deseni):** Üretilen her aday parafraz,
   aynı modele ikinci kısa bir çağrıyla ("bu iki cümle aynı bilgiyi mi
   istiyor?") doğrulanıyor. A3.4'teki guard/retry/fallback zincirinin birebir
   aynı fikri.

İlk gerçek denemede **%64,7 red oranı** çıktı — ama elle bakılan örneklerde
kabul edilenlerin çoğu doğruydu. Kök neden: doğrulayıcıya yalnızca
`max_new_tokens=5` veriliyordu; model "EVET/HAYIR" demeden önce birkaç kelime
tereddütle başlayınca kesiliyor ve sessizce "HAYIR" sayılıyordu.
`max_new_tokens` 16'ya çıkarıldı, biçim hatası artık **kabul** tarafına
düşüyor (bu bir kalite süzgeci, A3.4'teki sayısal guard kadar sert bir
güvenlik sınırı değil), ayrı bir `belirsiz` sayacı eklendi, İngilizce sızıntısı
için `LATIN_YABANCI_DESENI` filtresi kondu.

Yeniden denemede **`BELİRSİZ %0`** çıktı — teori doğrulandı. Kalan %58,9 red
bu sefer gerçek: doğrulayıcı, "verilmesi **gereken**" (gereklilik) ifadesini
"verilecek" (kesinleşmiş gelecek) yapan varyantları doğru eliyor. Sistem
tasarlandığı gibi çalışıyor: yanlışı üretmektense üretmemeyi tercih ediyor.

**Sonuç:** 84 şablondan 61'i doğrulanmış parafraz aldı, 23'ü güvenle orijinal
kaldı (veri kaybı yok). **35.375 soru-araç çifti**,
`data/egitim/router_sorulari_parafraz.jsonl`.

### `label_rationale.py` — A3.4 (bitti ✅) — gerekçe etiketleme + guard

Amaç: her kararı Türkçe, doğal bir gerekçe cümlesine çevirmek — büyük bir
LLM'in yazdığı, ama halüsinasyon içermediği garanti edilmiş bir cümle.

**Tasarım kararı:** 50.050 satırın her birini ayrı ayrı büyük modele göndermek
~25 saat sürerdi. Fark ettim ki `decide.py` her karar tipi için **sabit bir
kural kodu dizisi** üretiyor — yani 50.050 satır aslında birkaç "ŞEKİL"in
tekrarı. Büyük modele şekil başına birkaç kez soruldu (yer tutucu token'lı),
gerçek sayılar bu varyantlara yerelde basıldı. Elli bin değil, onlarca LLM
çağrısı. Gerçek veride yalnızca **3 benzersiz şekil** bulundu — tasarım
varsayımı doğrulandı.

**Guard'la ilgili not:** `app/llm/guard.py` (Kişi B, B2.5) henüz yazılmadı.
A3.4 bunu bekleyemeyeceği için `label_rationale.py` kendi sayı-doğrulama
eşleniğini taşıyor (`_metni_dogrula`) — `izinli_sayilar()` ile aynı kaynağı
kullanan, gerçek guard yazılınca hizalanması gereken bağımsız bir kopya.
Kişi B'nin `app/llm/` alanına dokunmadım (sözleşme gereği).

Doğrulama zinciri: şekil varyantı doldurulur → sayılar `izinli_sayilar` ile
karşılaştırılır (ürün adındaki rakamlar önce maskelenir, "Tuğla 19x9x5"
içindeki 19/9/5 uydurma sanılmasın diye) → geçmezse `explain.py`'deki
`sablon_gerekce()`'ye düşülür.

**Gerçek modelle üç sorun bulundu ve düzeltildi:**

1. **Anlam tersine dönüyordu** — prompt yalnızca `karar_tipi` kodunu veriyordu,
   iş anlamını açıklamıyordu. `KARAR_TIPI_ACIKLAMASI` + `SLOT_ACIKLAMALARI`
   eklendi.
2. **Zorunlu yer tutucular atlanıyordu** — "hiçbirini atlama" vurgusu güçlendirildi.
3. **Çince metin sızıntısı** — Qwen2.5 ailesinde bilinen sorun, `_CJK_DESENI`
   filtresi eklendi.

Ayrıca zayıf modelle (`llama3.2:1b`) duman testinde bir hata daha çıktı: model
talimatı kendi cevabıymış gibi geri döndürüyordu ve "token'lar var mı" kontrolünden
geçiyordu. `_YANKI_IFADELERI` kara listesi eklendi.

Son olarak tam veri setine ilk uygulamada `stok.siparis` şeklinin tamamı
(3.838 satır) şablona düştü: sabit 300 karakterlik uzunluk sınırım vardı ama
7 yer tutuculu doğru bir cümlenin doğal uzunluğu 338-362 karakterdi. Sınır
artık yer tutucu sayısına göre ölçekleniyor.

**Sonuç — tam 50.050 satırlık koşu:** `data/egitim/gerekceler.jsonl`,
**guard geçme oranı %100** (0 şablona düşme). Karar tipi dağılımı A3.1 ile
neredeyse birebir örtüşüyor. 6,7 saniyede tamamlandı (tamamı yerel — yalnızca
3 Colab çağrısının sonucu 50.050 satıra uygulandı).

### Faz 3 durumu

- ✅ A3.1 — karar noktası örnekleme (50.050 nokta)
- ✅ A3.2 — router soru şablonları (24.999 çift, geçici araç listesiyle)
- ✅ A3.3 — soru başkalaştırma (35.375 satır)
- ✅ A3.4 — gerekçe etiketleme (50.050 satır, guard %100)
- ✅ A3.5 — SKU bazlı train/val/test bölme + golden set adayı
  (golden set'in **nihai onayı** hâlâ ikisi birlikte)

---

### A3.5 sonrası — Kişi B'nin bulduğu üç sorun düzeltildi

Kişi B, Drive'a yüklenen veriyi bağımsız doğrularken (satır sayıları, SKU
sızıntısı, sıra bağımsızlığı — hepsini kendi testleriyle) iki ciddi bulgu
buldu:

**1. Router verisi 3.808x dengesiz.** `siparis_onerisi_sorgula` (2.000
SKU'dan üretildiği için) toplam verinin %95,6'sını kaplıyordu —
`onay_kuyrugu_sorgula` 14, `genel_stok_durumu_sorgula` 11 satırla
karşılaştırıldığında. Riski netti: LoRA "her şeye siparis_onerisi de"
öğrenebilir, ve val/test AYNI dengesizlikte olduğu için bu risk kendi
ölçümünde bile görünmez kalır — hep aynı cevabı veren bir model kendi
testinde %95 "başarı" gösterir.

**Düzeltme:** `training/veri_bolme.py`'ye `router_verisini_dengele()`
eklendi — baskın aracı tekilleştirmeden SONRA 2.000'e alt örnekliyor.
Dengesizlik **3.808x'ten ~143x'e düştü** (2.000/14). Bunu, golden set'in
router kısmının da saf rastgele örnekleme yerine **her araçtan taban pay
garanti eden** stratified örneklemeye geçirilmesi izledi — önceki golden
set adayı yalnızca 2 araçtan örnek içeriyordu (diğer 5'i hiç ölçemiyordu),
yenisi 7 aracın 7'sini de kapsıyor (en seyrek ikisi hâlâ ince: 4 ve 1 örnek
— test bölmesinde o kadar satır olduğu için, daha fazlası yok).

**Not (henüz yapılmadı, isteğe bağlı):** Bu düzeltme tamamen yerel/koddan
yapıldı, ek bir Colab turu gerektirmedi. Seyrek araçları (özellikle
parametresiz `onay_kuyrugu_sorgula`/`genel_stok_durumu_sorgula`) 500-2.000
bandına daha da yaklaştırmak isteniyorsa ek bir paraphrase turu (daha
yüksek `n`) gerekir — ama bu iki aracın doğal dil çeşitliliği zaten sınırlı
(parametre yok, tek bir statik niyet), 500+ farklı doğal cümle üretmek
zorlama/tekrar riski taşır. Alternatif: LoRA eğitiminde class-weighted
sampling — bu, B'nin karar vereceği bir eğitim-tarafı tercihi.

**2. `sku_adi` parametresi aslında SKU KODU taşıyordu, ürün adı değil**
(`{"sku_adi": "S-01971"}`). Bu, B'nin taban çizgi karşılaştırmasını
(beklenen değerler ürün adıydı) geçersiz kılabilirdi. **Karar: parametre
anahtarı `sku_id` olarak yeniden adlandırıldı** (`build_dataset.py`'nin
`ARAC_TANIMLARI`sı, `PLACEHOLDER_TOKENLARI`, `veri_bolme.py`'nin SKU
eşleştirmesi) — içerik zaten hep ID'ydi, artık adı da öyle. Var olan
`sablon_parafraz.jsonl`/`sablon_listesi.jsonl` dosyaları (Colab'dan gelen,
yeniden üretmesi maliyetli) alan adı düzeltmesiyle yerinde güncellendi,
Colab'a tekrar gidilmedi. B kendi tarafında `schemas.py`'yi buna göre
güncelleyecek.

**3. Golden set'e iki vaka daha eklendi:** `tedarikci_onayli=False`
sentetik bir örnek elle oluşturuldu (gerçek `decide.py` + `sablon_gerekce`
üzerinden, `sentetik_not` alanıyla işaretli) — bu durum eğitim verisinde
hiç görülmüyor (bkz. yukarıdaki `TEDARIKCI_ONAY_ESIGI` notu) ama onay
kuyruğu politikasının bunu doğru yakalayıp yakalamadığını test etmek
önemli. **`stok.tedarikci_degisim` eklenemedi** — `KararTipi` enum'unda
tanımlı olsa da `decide.py::ozellikten_karar_uret` bu kararı hiçbir zaman
üretmiyor (tedarikçi değişim mantığı hiç yazılmadı). Golden set, sistemin
üretmediği bir kararın örneğini içeremez — bu, veri hazırlığının bir
eksiği değil, decide.py'de henüz yazılmamış bir özelliğin işareti; B'ye ve
gerekirse gelecekteki bir role/faz'a not olarak bırakıldı.

Yeniden üretilen tüm veri (`router_sorulari.jsonl`, `router_sorulari_parafraz.jsonl`,
`router_train/val/test.jsonl`, `golden_set_aday.jsonl`) Drive'a tekrar
yüklenmeli.

---

## A · Faz 4-5 — Genellenebilirlik testi + para metriği (✅)

A3.5 Kişi B'yi beklediği için, ona hiç bağımlı olmayan Faz 4-5 işlerine
geçildi.

### 2 yeni şirket profili (A4.2)

`kucuk_nalbur_dukkani()` (~250 SKU, dar kategori, zayıf sezonsallık) ve
`buyuk_insaat_deposu()` (~5.000 SKU, güçlü sezonsallık) eklendi — varsayılan
~2.000 SKU'luk profilin yanına, ölçek ve karma bakımından iki uç nokta.

### `maliyet_raporu_uret()` (A4.4)

Kendi simülasyon döngüsünü çalıştırmaz — `simulasyon_calistir()`'in **gerçek**
tablolarını doğrudan işler, yani herhangi bir koşuya (sağlıklı, patolojili,
farklı seed/profil) uygulanabilir. 6 birim testiyle doğrulandı.

### A4.2 sonucu

3 profil × 3 seed = 9 kombinasyonun **tamamında** kural motoru vasat
politikadan hem daha düşük stok tükenme oranı hem daha düşük toplam maliyet
üretti. İyileşme ölçekle büyüyor: küçük dükkânda %1,4-3,2, varsayılan profilde
%15-19, büyük depoda %39-45.

**İlginç bir bulgu:** `kucuk_nalbur_dukkani` + seed=2026'da oracle'ın ham stok
tükenme sayısı (maliyeti değil) baseline'lardan yüksek çıktı. Kök neden: bu
profilde tedarik süresi kısa olduğu için oracle çok daha sık sipariş veriyor
(3049 vs ~700-1100); her döngüde sabit 3-sigma tamponunu aşma olasılığına
(~%0,13) yeniden maruz kalıyor — 3049 tekrarda en az bir "kötü şans" çekme
olasılığı ~%98. Kod hatası değil, oracle'ın sabit-tampon tasarımının bilinen
bir sınırlaması; script bunu gizlemek yerine açıkça gösteriyor.

### Faz 5 — projenin can alıcı sonucu

Eğitim verisi üretiminde hiç kullanılmamış taze bir seed'le
(`FAZ5_HELD_OUT_SEED=20250801`), varsayılan profilde, 3 yıllık tutulmamış koşu:

| Politika | Stok tükenme | Kayıp kâr | Aşırı stok | Sipariş maliyeti | **Toplam** |
|---|---|---|---|---|---|
| vasat | %5,31 | 7,69M | 9,41M | 1,72M | **18,82M TL** |
| kural motoru | %0,47 | 3,82M | 12,41M | 1,16M | **17,40M TL** |
| oracle | ~%0 | 0,20M | 8,70M | 6,00M | **14,90M TL** |

**Kural motoru toplam maliyeti %7,6 düşürdü, stok tükenme oranını %5,31'den
%0,47'ye indirdi.**

İki nokta bilinçli olarak raporlanıyor:

1. Kural motorunun **aşırı stok maliyeti vasat'tan yüksek** (12,41M vs 9,41M)
   — hata değil, kasıtlı değiş tokuş: önemli ürünlere %99 servis seviyesi
   hedeflemek daha fazla emniyet stoğu demek. Karşılığında kayıp kâr yarıya
   düşüyor, net etki lehine.
2. Oracle'ın sipariş maliyeti (6,00M) en yüksek — 40.021 sipariş verdiği için.
   Mükemmel bilgiyle stok maliyetini minimize etmek mümkün ama bedeli çok sık,
   küçük siparişler. Teoriyle tam uyumlu.

---
---

# KİŞİ B — Servis & Model (Esmanur)

## B · Adım 0 — Ortam kurulumu

| Yapılan | Neden |
|---|---|
| `uv` kuruldu | Projenin paket yöneticisi. `pip` + `venv` + `pyenv` yerine tek araç |
| Python 3.12.13 indirildi | Sistemde 3.11 vardı, proje 3.12+ istiyor. `uv` kendi indirdi |
| 140 paket kuruldu | `uv.lock` sayesinde Melih'le **birebir aynı** sürümler |
| Cache'ler `D:\ERP\.cache`'e yönlendirildi | C: sürücüsünde 5,8 GB kalmıştı. Cache 725 MB oldu ama C: hiç dolmadı |
| `.env` oluşturuldu | Ayarlar (`AUTONOMY_LEVEL=shadow` gibi) |

**Bu projede `pip install` asla kullanılmaz.** Yeni paket gerekirse `uv add`.
`pip install` paketi sadece tek bilgisayara kurar, `uv.lock`'a girmez, CI'da
patlar.

## B · Adım 1 — Kod okuma turu

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

## B · Faz 1 — Veri katmanı + API + CI (TAMAMLANDI ✅)

**Testler: 25 → 91**, hepsi yeşil. `faz1-servis` branch'ine push edildi,
CI GitHub'da yeşil (34 saniye).

### B1.1 · Veritabanı tabloları

Altı tablo:

| Tablo | Ne tutuyor |
|---|---|
| `decision` | Üretilen her karar + politikanın hükmü + (varsa) gerekçe |
| `decision_audit` | **Değişmez** denetim izi. Her olay için bir satır, asla güncellenmez |
| `approval` | Onay kuyruğu — kim, ne zaman, ne dedi |
| `feedback` | İnsan geri bildirimi — sonraki eğitim turunun verisi |
| `policy` | Eşik tablosu |
| `insight` | Gecelik bulgular (Faz 2'de dolacak) |

**`alembic` nedir:** Veritabanı yapısını kodla değiştirmenin yolu.
`alembic upgrade head` yazınca tablolar oluşuyor. Yapı değişince yeni bir
"migration" dosyası yazılıyor; böylece iki bilgisayardaki tablolar aynı kalıyor.

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
  denetim satırını **birlikte, aynı işlemde** yazıyor.
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
   (ikincisi 409). Feedback ucu sınırsız yorum alır — çünkü kullanıcı bir hafta
   sonra "fazlaydı" derse iş akışı değişmemeli ama eğitim verisine girmeli.
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
| `uv sync --frozen` | Kilit dosyası güncel mi |
| `ruff check .` | Kod stili |
| `pytest` | 91 test |
| `alembic upgrade head` | Migration'lar boş veritabanında uygulanabiliyor mu |
| `alembic check` | Model ile migration uyumlu mu |

⚠️ **Bu dosya tek başına yeterli değil.** GitHub'da `main` için branch
protection açılmalı (Settings → Branches), yoksa CI sadece bilgi verir.

---

## B · Faz 2 — LLM katmanı (başladı 🔄)

### B2.1 · Model + istemci (bitti ✅)

`qwen2.5:1.5b-instruct` indirildi (986 MB, `D:\Ollama\models` — C: sürücüsüne
hiç dokunmadı). `app/llm/client.py` yazıldı: modelin **tek giriş kapısı**.
Zaman aşımı, yeniden deneme, token/süre ölçümü tek yerde.

**18 test, hiçbiri gerçek modeli çalıştırmıyor** — sahte cevaplarla. Yani CI'da
Ollama olmadan koşuyorlar ve geliştirme sırasında işlemciyi yormuyorlar.

**Isınma endişesi vardı, ölçerek çözüldü.** Geliştirme makinesi tek ve yedeği
yok; "muhtemelen sorun olmaz" yeterli bir cevap değildi. İki koruma kondu:

| Koruma | Ne yapıyor |
|---|---|
| İşlemci üst sınırı %60 | Windows güç planı; çip o ısıya hiç ulaşamıyor |
| `LLM_IPLIK_SAYISI=4` | Model 22 çekirdeğin sadece 4'ünü kullanıyor |

Sonra 2/4/8/16/22 iş parçacığıyla ölçüldü. **22 iş parçacığı 16'dan yavaş
çıktı** — bu işlemcide üç tip çekirdek var, hepsini birden kullanınca hızlılar
yavaşları bekliyor.

`4` seçildi. En hızlısı değil, bilinçli: 16'ya çıkmak gecelik işi 4,1 dakikadan
2,9 dakikaya indiriyor — gece, kimse başında değilken çalışan bir iş için 1,2
dakika kazanç. Dört kat çekirdek yükünü karşılamıyor.

**Sonuç: 22,4 token/sn → gerekçe ~9,8 sn → gecelik iş ~4,1 dakika** (hedef
< 10 dk). Ayrıntılı tablolar `dokumantasyon/OLCUMLER.md`'de.

**Yan bulgu — model ilk çağrıda sayı uydurdu.** Basit bir istemle:

> *"Kirmizi Tugla için **35** adet ek satışı yapar."*

Verilen sayılar 42, 12, 270, 1200'dü; **35** hiçbir yerde yoktu. Mimarinin
birinci kuralının neden var olduğunun canlı kanıtı — ilk denemede,
kendiliğinden. İsteme "yeni sayı üretme" eklenince kayboldu, ama bu bir garanti
değil yalnızca olasılık düşürme. Guard (B2.5) bu yüzden zorunlu.

### B2.2 · Yapılandırılmış çıktı (bitti ✅)

Modelden düz metin değil **şemaya uyan JSON** istiyoruz. `app/llm/schemas.py`:

- `AracAdi` — router'ın seçebileceği 7 araç. **Kişi A'nın eğitim verisindeki
  adlarla birebir aynı**; ayrışırsa model öğrendiği etiketi tanımaz ve router
  sessizce başarısız olur. Bir test bunu kilitliyor.
- `AracCagrisi` — araç + parametre. Yanlış parametre reddediliyor: model doğru
  aracı seçip uydurma parametre ekleyebiliyor, bu aşağı akışta anlamsız sorgu
  demek.
- `GerekceCiktisi` — tek alanlı. Model düz metin istendiğinde başına "İşte
  açıklama:" gibi girişler ekliyordu; tek alanlı şema bunu yapısal olarak
  engelliyor.
- `yapilandirilmis_uret()` — şemaya uymazsa yeniden dener, olmazsa
  `SemaUyumsuz` fırlatır (çağıran şablona düşer, karar bloke olmaz).

**Kabul ölçütü: 20/20 geçerli JSON, hepsi ilk denemede.** Yedek plan (llama.cpp
GBNF grammar) gerekmedi.

**Ama önemli bir ders çıktı: şema biçimi garanti eder, anlamı etmez.**

Yirmi çıktının hepsi kusursuz JSON'du. İçerik değildi:

```
#18  "163..."                       ← UYDURMA SAYI
#19  "42 + 615 - 1200 = 397..."     ← UYDURMA + aritmetik
#20  "1976-03-14T13:44:00Z..."      ← RASTGELE TARİH
```

Bu sayıların hiçbiri isteme verilmemişti. Guard'ın (B2.5) neden pazarlık
konusu olmadığının ikinci kanıtı — birincisi B2.1'deki `35`'ti.

Router tarafında ön bulgu: 14 sorudan 11'i doğru. Model **açık** ifadelerde
iyi, **dolaylı** ifadelerde takılıyor ("kuyrukta ne var" → yanlış araç). Resmî
taban çizgi B2.3'te, 30 dengeli soruyla ölçülecek.

### B2.3 · Router + taban çizgi (bitti ✅)

`app/llm/router.py` — Türkçe soruyu 7 araçtan birine yönlendiriyor. Henüz
eğitim yok, few-shot örneklerle çalışıyor. `POST /v1/ask` ucu da eklendi.

Uç **yalnızca yönlendirme** yapıyor, aracı çalıştırmıyor. Bilinçli: B2.3'ün
ölçtüğü şey "doğru aracı seçebiliyor muyuz". Çalıştırmayı da aynı adıma
sıkıştırmak, yanlış yönlendirmeyi doğru sonucun arkasına gizlerdi.

**Taban çizgi ölçüldü — bu sayı projenin en kritik ölçümlerinden.** Faz 3'te
LoRA eğitildikten sonra aynı 30 soru yeniden koşturulup karşılaştırılacak.
Şimdi ölçülmeseydi "eğitim işe yaradı mı" sorusu kalıcı olarak cevapsız
kalırdı.

| Ölçüt | Değer | Faz 5 hedefi |
|---|---|---|
| Araç doğru | **%76,7** (23/30) | — |
| Araç + parametre | **%73,3** (22/30) | **> %95** |

Arada 22 puan var. LoRA'nın kapatması gereken mesafe bu.

Ölçüme **üç koruma** eklendi (Kişi A'nın verisini inceledikten sonra):

1. **Parametre biçimi esnek.** Eğitim verisinde `sku_adi` parametresi ürün
   adını değil **kodunu** taşıyor (`"S-01971"`). Model eğitimden sonra kod
   üretmeye başlarsa katı karşılaştırma doğru cevabı yanlış sayar ve LoRA
   öncesi/sonrası kıyaslaması geçersiz olurdu. Beklenen değer artık liste —
   ad da kod da kabul.
2. **Uydurma parametre dedektörü.** Model parametreyi ancak sorudan
   çıkarabilir; soruda geçmeyen bir değer üretiyorsa ayrıca sayılıyor.
   İlk koşuda 1 tane yakaladı.
3. **Çöküş dedektörü** (aşağıda).

Ham sonuçlar `training/eval/router_taban_sonuc.json`'a kaydediliyor —
B3.5'te puanlama değişirse modeli tekrar çalıştırmaya gerek kalmasın.

**Asıl bulgu:** sekiz hatanın **dördü tek bir araçta**. Model "ölü stok"u
(satılmayan, fazla mal) "kritik stok"la (tükenen, eksik mal) karıştırıyor —
ikisi de "stok sorunu" ama iş anlamı zıt.

```
olu_stok_sorgula : 1/5     ←←← 
diğer altı araç  : 21/25
```

En çarpıcısı: *"Ölü stok durumundaki ürünleri listeler misin?"* sorusunda
**"ölü stok" kelimesi birebir geçiyor** ve model yine kritik stoğa
yönlendirdi. Few-shot prompt bu ayrımı öğretemiyor; LoRA'nın somut olarak
çözmesi gereken şey bu.

Soru seti **elle yazıldı**, Kişi A'nın otomatik ürettiği eğitim verisinden
bilinçli olarak ayrı — aynı şablonlardan türeyen bir test seti, modelin
şablonu ezberlemesini "başarı" diye ölçerdi.

### ⚠️ Eğitim verisi dengesizliği — LoRA öncesi çözülmeli

Kişi A'nın Drive'daki verisi bağımsız olarak incelendi (2026-08-02). Satır
sayılarının hepsi tutuyor, **sızıntı yok** (train/val/test SKU kümeleri
tamamen ayrık, hem `sku_id` hem `sku_adi` üzerinden doğrulandı). Ama araç
dağılımı çok çarpık:

```
siparis_onerisi_sorgula      41.886   %95,6
tedarikci_performansi          1.325
kritik_stok_sorgula              256
olu_stok_sorgula                 240
gecelik_ozet_sorgula              66
onay_kuyrugu_sorgula              14
genel_stok_durumu_sorgula         11
```

**En sık / en seyrek = 3808 kat.**

Bu veriyle eğitilen model "her şeye `siparis_onerisi` de" davranışına
çökebilir. Asıl tehlike şu: **Kişi A'nın val/test bölmeleri de aynı
dengesizlikte**, yani hep aynı cevabı veren bir model onun test setinde
**%95 doğruluk** gösterir. Rakam mükemmel görünür, router çalışmaz.

Bu çarpıklığı görebilecek tek ölçüm **dengeli olan taban çizgi seti**. Bu
yüzden `router_taban.py`'ye **çöküş dedektörü** eklendi: model tek araca
%40'tan fazla yığılırsa açıkça uyarı basıyor. "Doğruluk düştü" ile "model
ayrım yapmayı bıraktı" farklı sorunlar — birincisi daha çok veri ister,
ikincisi dengeyi düzeltmeyi.

Kök sebep yapısal, bir hata değil: `siparis_onerisi` 2.000 SKU'dan
üretiliyor, `kritik_stok` yalnızca ~8 kategoriden.

Kişi A'ya iletildi. Önerilen: `siparis_onerisi`'ni ~2.000'e alt örnekle
(3808x → 150x) **ve** seyrek araçları A3.3 parafraz makinesiyle çoğalt.

Ayrıntılar `dokumantasyon/OLCUMLER.md`'de.

### Sırada
### B2.6 · Gecelik iş + tetikleyiciler (bitti ✅)

**`app/jobs/nightly.py`** — mimarinin can alıcı noktasını hayata geçiriyor.

Naif tasarım şöyle olurdu: her SKU için karar üret, her karar için gerekçe
yaz. 2.000 × ~9 sn = **5 saat.** Onun yerine:

1. Tüm SKU'lar için karar üretilir — kural motoru, milisaniyeler
2. Kararlar **önem sırasına** dizilir (risk skoru)
3. Gerekçe **yalnızca üst 25** karar için yazılır

Geri kalan kararlar gerekçesiz kaydedilir; denetim kaydına `ATLANDI` yazılır.
Bu bir eksiklik değil, tasarım — insan zaten ilk 25'e bakıyor.

`KosuOzeti` **karar süresiyle gerekçe süresini ayrı** raporluyor. Mimarinin
"karar hızlı, gerekçe yavaş" iddiası ancak ayrı ölçülürse doğrulanabilir; tek
bir toplam süre bu ayrımı gizlerdi.

Bir performans detayı: eşikler karar tipi başına **bir kez** okunuyor. Bu
önbellek olmadan 2.000 SKU = 2.000 ayrı SELECT olurdu; 4 karar tipi olduğu
için hepsi 4 sorguya iniyor. 10 dakikalık bütçenin korunmasında en ucuz
kazanç bu.

**`app/jobs/triggers.py`** — üç tetikleyici: büyük sipariş, kritik stok,
limit aşımı. Eşikler `config.py`'de, çünkü sahada "büyük sipariş" neye denir
şirkete göre değişir.

Tetikleyici **karar üretmez**, üretilmiş bir kararı değerlendirir. Ayrım
önemli: tetikleyici mantığı karar mantığına karışırsa iş kuralı iki yerde
yaşar ve zamanla ayrışır.

İki incelik:

- **Talep sıfırsa kritik stok tetiklenmiyor.** "Kaç gün yeter" sorusunun
  cevabı yok; 0 dönmek "hemen bitecek" demek olurdu ve hiç satmayan bir ürün
  için her gece yanlış alarm üretirdi.
- **Önem skoru eşiğin kaç katı aşıldığı**, sabit 1.0 değil. Limitin iki katı
  bir sipariş, sınırda olandan daha acil ve kuyrukta üstte görünmeli.

24 test eklendi, hiçbiri model çalıştırmıyor (gerekçe üreteci enjekte
edilebilir). **Kabul ölçütü "2.000 SKU < 10 dakika" merge'i bekliyor** —
gerçek kural motoru gerekiyor. Kod hazır, `karar_ureteci` parametresine
`stok_karari_uret()` geçirilecek, başka bir şey değişmeyecek.

### B2.5 · ⭐ Guard — projenin en kritik parçası (bitti ✅)

Mimarinin birinci kuralını hayata geçiren kod: **LLM asla sayı üretmez.**
Metindeki her sayı `izinli_sayilar()` kümesinde yoksa metin reddedilir.

Bu kural teorik değil. Modelin bu projede **gerçekten** yaptıkları:

```
B2.1  "Kırmızı Tuğla için 35 adet ek satışı yapar"   ← 35 uydurma
B2.2  "163..."                                       ← uydurma
B2.2  "42 + 615 - 1200 = 397..."                     ← uydurma + aritmetik
B2.2  "1976-03-14T13:44:00Z..."                      ← rastgele tarih
```

Dördü de guard testine **birebir test vakası** olarak kondu. Hayali örnek
kullanmadık.

**Zincir:** üret → doğrula → geçmezse 1 kez yeniden üret → yine geçmezse
şablona düş. Sonuç her koşulda denetim kaydına yazılır. Üreteç patlasa bile
(LLM erişilemez) şablona düşülüyor — **karar hiçbir koşulda bloke olmuyor.**

#### İki tasarım kararı, ikisi de ölçümle alındı

**1. Maskeleme zorunlu.** Ürün/tedarikçi adlarındaki rakamlar sayı değil.
Maskeleme olmadan **kendi şablon gerekçemiz kendi guard'ımızdan geçmiyor** —
iki motorda da doğrulandı:

```
stub          maskesiz: REDDEDER [19, 9, 5]   ← "Kırmızı Tuğla 19x9x5"
gerçek motor  maskesiz: REDDEDER [125]        ← "Alçıpan 12.5mm"
```

İkincisi daha sinsi: `12.5mm` Türkçe biçimde ayrıştırılınca **125** oluyor.
Şablon guard'ın geri dönüş noktası; o da reddedilirse sistemin güvenli çıkışı
kalmaz. Fikir Kişi A'nın `label_rationale.py::_metni_maskele`'sinden geldi —
onun kodunu incelemek benim yapacağım bir hatayı önledi.

**2. Tolerans hem yuvarlamayı kabul etmeli hem kabalığı kesmeli.** Üç kural
gerçek vakalarla karşılaştırıldı:

| kural | `27,38 → "%27"` | `4,75 → "5"` |
|---|---|---|
| mutlak tolerans (0,01) | ❌ reddediyor | ✅ |
| yalnız yuvarlama | ✅ | ❌ **geçiriyor** |
| **yuvarlama + bağıl %2** | ✅ | ✅ |

Seçilen: **birebir eşleşme VEYA (yazılan hassasiyette doğru yuvarlama VE
bağıl fark ≤ %2)**. Bağıl sınır olmasa `0,94 → "1"` geçerdi ve gerekçede
"1 adet" yazan bir uydurma kullanıcıya giderdi.

#### Kişi A için çağrılabilir arayüz

Görev dosyası: *"Ona sade, çağrılabilir bir fonksiyon arayüzü bırak."*

```python
sayilari_dogrula(metin, izinli, maskelenecek=...) -> DogrulamaSonucu
```

`DecisionCandidate` bilmiyor — yalnızca metin, izinli küme ve maskelenecek
metinler alıyor. Böylece eğitim verisi üretiminde de çalışma zamanında da
**aynı kod** çalışır. `label_rationale.py` kendi kopyasını silip bunu import
edebilir.

42 test. Hiçbiri model çalıştırmıyor.

#### Kişi A'nın incelemesi ve çıkan tek düzeltme

Kişi A guard'ı bağımsız olarak kendi makinesinde çalıştırdı (ayrı bir `git
worktree` ile) ve onayladı. Bir gözlem bıraktı: `"14.03.1976"` gibi nokta
ayraçlı bir tarih **tek bir sayı** olarak okunuyor ve `14031976` diye garip
bir değer olarak reddediliyor.

Bunu değiştirmedik, çünkü değiştirmek **tehlikeli**. Neden:

Guard bir belirteci çözemezse (`None` döndürürse) o belirteci **yok sayar**.
Yani "14.03.1976 geçersiz binlik gruplaması, `None` döndüreyim" diye
"düzeltmek" tarihi guard'dan **geçirir**. Garip görünen sayı, güvenli olan
davranış. Ayrıca `reddedilen_sayilar` sözleşmede `list[float]` — dondurulmuş,
zaten metin tutamaz.

Yapılan: davranışı kilitleyen bir test eklendi
(`test_nokta_ayracli_tarih_reddediliyor`), gerekçesi test docstring'ine
yazıldı. Böylece ileride biri "iyileştirme" niyetiyle bu kapıyı açamaz.

### B2.4 · Gerçek gerekçe üretimi (kod bitti ✅, insan okuması bekliyor)

Guard'ın üstüne gerçek LLM üretimi kondu: `app/llm/explain.py`.

Şimdiye kadar gerekçeler **şablondan** geliyordu — doğru ama kalıp cümleler.
Artık modele yazdırıyoruz, guard da yazdığını denetliyor.

#### Modele sayı listesi veriliyor, üstelik adlandırılmış

En kritik tasarım kararı bu. Modele "işte karar, gerekçe yaz" demek yerine
kullanabileceği sayılar **etiketli** olarak veriliyor:

```
Kullanabileceğin sayılar (BUNLARIN DIŞINA ÇIKMA):
günlük ortalama talep (adet): 42
tedarik süresi (gün): 12
kullanılabilir stok (adet): 270
önerilen sipariş miktarı (adet): 1.200
```

Etiket olmadan model **doğru sayıyı yanlış cümlede** kullanıyor — "tedarik
süresi 270 gün" gibi. Guard bunu yakalayamaz, çünkü 270 meşru bir sayı.
Guard sayının varlığını denetler, yerini değil. Etiket bu boşluğu kapatan
tek şey.

Sayılar isteme **Türkçe biçimde** yazılıyor (`1.200`, `4,75`). Model gördüğü
biçimi kopyalar, guard da Türkçe biçim bekler; ikisini hizalamak bedava.

#### Sayı listesi bilinçli olarak dar

İzinli küme 25 sayı içeriyor ama isteme yalnızca karar tipiyle ilgili olanlar
konuyor (sipariş kararında tedarik süresi var, raf ömrü yok). İki sebep:
25 sayının hepsi metni sayı çöplüğüne çeviriyor, ve konuyla ilgisiz sayıyı
vermek onu kullanmaya davet ediyor.

**Testle kilitlenen değişmez:** isteme konan her sayı `izinli_sayilar()`
içinde olmalı. Olmazsa model o sayıyı iyi niyetle kullanır ve metin **her
seferinde** şablona düşer — hata yok, log yok, sadece gerekçeler hiç
LLM'den gelmez. Sessiz arıza. Test hem stub hem gerçek motorla koşuyor.

#### İkinci deneme birincisinden farklı

Guard reddederse ikinci istemin sonuna ekleniyor:

```
UYARI: Önceki denemende şu sayıları uydurdun: 9.999.
Bu sayıları kullanma, yukarıdaki listede olmayan hiçbir sayı yazma.
```

Bu, B2.5'te guard'a koyduğum `onceki_red` kancasının varlık sebebiydi;
şimdi gerçekten kullanılıyor.

#### İki ayrı yeniden deneme katmanı var

Karıştırılmaması gereken bir ayrım:

| katman | neyi yakalar |
|---|---|
| `yapilandirilmis_uret` (B2.2) | bozuk JSON, şemaya uymayan çıktı — **biçim** hatası |
| `gerekceyi_guvenceye_al` (B2.5) | şema tuttu ama sayı uydurdu — **içerik** hatası |

En kötü durumda 4 model çağrısı. Pratikte şema uyumu yüksek olduğu için
1-2 çağrı görülüyor.

#### Döngüsel import çıktı, doğru yönde çözüldü

`guard.py` şablonu çağırıyordu, `explain.py` de guard'ı çağırmaya başlayınca
Python döngüye girdi. Doğru bağımlılık yönü **explain → guard** (explain üst
katman). Bu yüzden guard'ın şablon import'u fonksiyon içine alındı — guard
şablona yalnızca geri düşerken ihtiyaç duyuyor, modül yüklenirken değil.

#### Nereye bağlandı, nereye bağlanmadı

**Gecelik iş:** `llm_gerekce_ureteci(istemci)` ile takılıyor. Varsayılan
**şablon kaldı** — bilinçli. Gerçek üreteci varsayılan yapmak, Ollama kurulu
olmayan her ortamda gecelik işi 25 kez bağlantı hatasına sokardı; sonuç yine
şablon olurdu ama boşuna beklenerek.

**API (`?gerekce=true`) bağlanmadı** — bunu bilerek yapmadım. Bir HTTP
isteğinin içinde LLM beklemek 9-36 saniye sürer ve o süre boyunca veritabanı
oturumu açık kalır. Mimarinin ikinci kuralı "ERP asla LLM'i beklemez" tam da
bunu yasaklıyor. Gerekçe toplu işte (gecelik) üretilip kaydediliyor, API
kayıtlı olanı okuyor. Bu bir eksiklik değil, kuralın uygulanması.

18 test, hiçbiri model çalıştırmıyor. Toplam **263 test yeşil**.

#### Ölçüm: ilk deneme çöktü, istem üç kez düzeltildi

Modeli gerçekten çalıştırınca kod doğru ama **istem yanlış** çıktı. Üç tur:

**1. tur — 10/10 çöp, ama guard "7 geçti" dedi.** İstem sayı listesiyle
bitiyordu, model listeyi devam ettirip **istemi olduğu gibi geri yazdı**:

> "Ürün: Astar Boya - Filli Boya / Kullanabileceğin sayılar: ..."

Guard bunu geçirdi çünkü echo edilen sayılar zaten izinli sayılardı. **Bu,
projenin en öğretici anı:** guard sayıyı denetliyor, metnin gerekçe olduğunu
denetlemiyor. Sayıya bakıp "%70 başarı" demek yanıltıcı olurdu.

Çözüm: istemin sonuna `GEREKÇE:` satırı + sistem istemine bir örnek. Tek
satırlık bir işaret, tüm zincirin çalışıp çalışmamasını belirliyor.

**2. tur — cümle geliyor ama veri dökümü.** Model 10 sayının hepsini
sıralıyordu ("eldeki stok 10 adetlik ve tedarikçi skoru 91,60 olarak
belirtilen durumda, emniyet stoğu 6,58 adetlik ve..."). Oranları da `0,90`
diye yazıyordu.

Çözüm: sayı listesi 10'dan 3-6'ya indirildi, oranlar yüzde olarak veriliyor
(`0,90` yerine `90`). Sayı azalınca model ilişki kurmak zorunda kalıyor.

**3. tur — ürün adını uyduruyor.** "Astar Boya" → *starboy*, "İzocam" →
*isyancı yalıtım levhası*. Guard bunu yakalayamaz, uydurulan şey sayı değil.

Çözüm: **ürün ve tedarikçi adı isteme hiç konmuyor.** Ad zaten ERP'de
kararın yanında duruyor. Şablon adı yazmaya devam ediyor — o deterministik.

**Sonuç: 10/10 guard'dan geçiyor, ortalama 6,5 saniye.**

#### Guard'ın kör noktası artık teorik değil

Ölçüm iki gerçek örnek verdi:

> "Son hareketten bu yana geçen günlerde **216 adet** tasfiye edilmiştir."

`216` gün sayısı, adet değil. Doğru sayı, yanlış cümle.

> "232 adede inerek 656,57 adetlik yeniden sipariş noktasının **üstüne** ulaştı."

232 < 656,57 — altına düştü. Model yönü ters yazdı.

İkisinde de sayılar izinli olduğu için guard sessiz kaldı. Bunu kaydetmek
önemli: guard sayı uydurmasını **tamamen** engelliyor, ama sayının doğru
cümlede kullanıldığını garanti etmiyor. O iş dil modelinin kalitesine kalıyor
ve Faz 3'teki eğitimin hedefi tam olarak bu.

**Karar yolu etkilenmiyor:** gerekçe bozuk olsa bile karar, sayılar ve
politika sonucu kural motorundan geliyor.

#### İkinci tur: iki kusur da kapatıldı

İlk ölçümdeki iki somut hatayı hedefleyen üç değişiklik yapıldı.

**1. Sayısı sıfır olan kararlarda model hiç çağrılmıyor.** İki karar
(`#1`, `#3`) tüm değerleri sıfırdı — talep 0, stok 0, eşik 0. Modelden
"hiçbir şey yok" durumundan cümle istemek, olmayan bir **sebep** uydurmasını
davet ediyordu ("stok yönetimi kurallarını taklit eden bir durumdur"). Guard
yakalayamaz, uydurulan şey sayı değil. Artık bu kararlar doğrudan şablona
gidiyor — hem doğru cümle çıkıyor hem model 2 kez daha az çalışıyor.

**2. Kararın yönü modele söyleniyor.** Model `232 < 656,57` karşılaştırmasını
yapamıyordu. Artık isteme hazır satır giriyor:

```
durum: kullanılabilir stok yeniden sipariş noktasının ALTINA düştü
```

Yön zaten kural motorunun kararından belli; 1.5B modelden aritmetik beklemek
yerine sonucu vermek hem doğru hem ucuz. **Ters yön hatası kalmadı.**

**3. Her karar tipine yalnızca kendi örneği gösteriliyor.** Bu, ara denemede
öğrenilen bir ders: üç örneği birden verince sonuç **kötüleşti**. Model
örnekleri harmanladı — sipariş kararının gerekçesi "tasfiye değerlendirilmeli"
diye bitti, bir diğeri "sipariş açmaya gerek yoktur" dedi, yani kararın tam
tersi. Tek örneğe inince karışma bitti.

Kaydedilmeye değer: **örnek eklemek her zaman iyileştirmiyor.** Örnekler
birbirine benziyorsa model aralarında sızıntı yapıyor.

| | 1. ölçüm | 2. ölçüm |
|---|---|---|
| ortalama süre | 6,5 sn | **5,5 sn** |
| ters yön hatası | 1 | **0** |
| anlamsız metin | 2 | **0** |
| örnek sızıntısı | — | 0 |

#### Üçüncü tur: örnek cilası + cümle kırpma

Kalan kusurlar dil bilgisi düzeyindeydi. İki şey yapıldı.

**1. Örnek cümleler iyileştirildi.** Ölçümün en net bulgusu şu: model örneği
**neredeyse kelimesi kelimesine kopyalıyor.**

```
ornek     : "elde kalan 12 adet, birim maliyeti 225,62 TL uzerinden
             2.707,43 TL'lik sermayeyi bagliyor"
cikti #5  : "elde kalan  6 adet, birim maliyeti 312,94 TL uzerinden
             1.877,61 TL'lik sermayeyi bagliyor"
```

Tasfiye çıktıları iyiydi çünkü tasfiye örneğim iyiydi. Sipariş örneğini daha
iyi Türkçeyle yeniden yazdım, sonuç doğrudan yansıdı.

**Genel ilke: few-shot örneği bir talimat değil, bir kalıptır. Ne yazarsan onu
alırsın.**

**2. Üçüncü cümle kırpılıyor.** "En fazla 2 cümle" talimatı **ve** token
sınırı birlikte bile yetmedi; model kuralı kabul edip yine de dolgu cümle
ekliyordu:

> "...60 adet sipariş açılması öneriliyor. **Bu durumda hedef servis seviyesi
> %90'ı karşılayacak şekilde bir sipariş oluşturuluyor.**"

Modele yalvarmak yerine kırptım. Deterministik ve bedava.

Küçük bir tuzak vardı: Türkçede cümleyi `split(".")` ile bölemezsin, çünkü
`2.707,43` içindeki de nokta. Desen noktadan sonra **boşluk + büyük harf**
arıyor; `2.707,43` ve `12.5mm` bölünmüyor. Üçü de teste bağlı.

| ölçü | 1. tur | 2. tur | 3. tur |
|---|---|---|---|
| ortalama süre | 6,5 sn | 5,5 sn | **5,1 sn** |
| ters yön hatası | 1 | 0 | 0 |
| anlamsız metin | 2 | 0 | 0 |
| dolgu 3. cümle | 2 | 5 | **0** |
| yanlış metin | — | — | **0** |

Bu nokta **1.5B taban modelin tavanı** sayılmalı: bugün 0/10 kullanılabilir
metinden buraya gelindi ve son iki turda kazanç belirgin şekilde azaldı.
Kalan devrik cümleler istemle değil, Faz 3'teki eğitimle düzelir.

Ayrıntılı ölçüm: `dokumantasyon/OLCUMLER.md` → B2.4 (üç bölüm).

### Sırada

### B2.6 ölçümü — 2.000 SKU taraması

Kabul ölçütü: **"2.000 SKU'luk gecelik tarama < 10 dakika."**

Ölçüm baştan sona **gerçek zincirle** yapıldı: Melih'in gerçek karar motoru +
B2.4'ün guard'lı LLM gerekçe üreteci. Şablonla ölçmek yalancı sonuç verirdi —
şablon anında üretiyor, LLM 6,7 saniye.

```
taranan karar        2.000      hata: 0
onay kuyruguna       743
gerekce uretilen     25         (atlanan: 1.975)

karar suresi         152,2 sn
gerekce suresi       166,6 sn
TOPLAM               318,8 sn  =  5,31 dakika

HEDEF 10 dakika  ->  GECTI, 4,69 dakika pay
```

#### Mimarinin iki iddiası artık ölçülü

**"Karar milisaniyelerde çıkar, gerekçe saniyeler sürer."**

```
karar basina       76 ms
gerekce basina  6.700 ms      ->  88 KAT fark
```

Kural motoru + politika + veritabanı yazımı bir karar için 76 milisaniye.
Aynı karar için Türkçe cümle yazmak 6,7 saniye. `KosuOzeti`'nin iki süreyi
ayrı tutması ve `commit()`'in iki kez atılması bu yüzden — kararlar gerekçe
beklemeden görünür oluyor.

**"Gerekçe yalnızca üst N için üretilir."**

1.975 karar için gerekçe üretilmedi. Üretilseydi:

```
2.000 x 6,7 sn = 3 saat 43 dakika        (hedefin 22 kati)
```

Yani üst-N kısıtı bir hız iyileştirmesi değil, **işin çalışabilmesinin ön
şartı**. Kalan kararlar gerekçesiz kaydediliyor; birine bakılması gerekirse
gerekçe sonradan üretilebiliyor.

Ayrıntılı ölçüm: `dokumantasyon/OLCUMLER.md` → B2.6.

---

## FAZ 2 TAMAMLANDI ✅

| iş | durum |
|---|---|
| B2.1 model + istemci | ✅ |
| B2.2 yapılandırılmış çıktı | ✅ |
| B2.3 router + taban çizgi | ✅ |
| B2.4 gerçek gerekçe üretimi | ✅ |
| B2.5 guard | ✅ |
| B2.6 gecelik iş + tetikleyiciler | ✅ |

Altı işin de kodu yazıldı, ölçümü yapıldı ve `dokumantasyon/OLCUMLER.md`'ye
kaydedildi. Sırada Faz 3 (LoRA eğitimi) var — o iş Colab'da yapılacak,
bilgisayara yük binmeyecek.

---
---

# ORTAK

## Yolda bulunan hatalar ve tuzaklar

Tekrar yaşanmasın diye:

| Ne | Sonucu | Çözüm |
|---|---|---|
| `.gitignore`'da `models/` | `app/models/` git tarafından **sessizce yok sayılıyordu** | `/models/` (başına eğik çizgi) |
| `alembic.ini`'de Türkçe | Her alembic komutu `UnicodeDecodeError` (o dosya locale kodlamasıyla okunuyor) | Dosya **sadece ASCII**; Türkçe açıklamalar `env.py`'de |
| Alembic'in ürettiği dosyalar lint'e uymuyor | Her migration CI'yı kırardı | `post_write_hooks` ile otomatik `ruff` |
| SQLite koruma kuralları kapalı | `CASCADE` tanımları süstü | `PRAGMA foreign_keys=ON` her bağlantıda |
| Tohum migration'ı çakıştı | Mevcut satır varsa `upgrade` yarıda kalıyordu | Yalnızca eksik satırlar ekleniyor |
| Migration çıktısını filtrelemek | Hata mesajı görünmedi, çöktüğü fark edilmedi | Migration çıktısı **filtrelenmez** |
| Windows konsolu (cp1254) | Türkçe karakterde `UnicodeEncodeError` | `sys.stdout.reconfigure` |
| LLM'e satır satır çağrı | 50.050 satır ~25 saat sürerdi | **Şekil/şablon bazlı** üretim, sonra yerelde çoğaltma |
| Qwen2.5 Çince sızıntısı | Türkçe cümle ortasında Çince karakterler | `_CJK_DESENI` regex filtresi |
| Doğrulayıcıya kısa token limiti | Model tereddütle başlayınca sessizce "HAYIR" sayılıyordu | Limit 16'ya çıkarıldı, biçim hatası **kabul** tarafına |

## Sözleşme kusuru — bulundu ve düzeltildi ✅

**Kişi B buldu (B2.5 guard hazırlığında):** `izinli_sayilar()` içindeki `×100`
kuralı, bir sayının 0-1 aralığında olup olmadığına bakarak karar veriyordu —
**değerine göre, alan adına göre değil.** Bu yüzden `son_hareket_gun_once` gibi
bir adet/gün alanı `1` değerini aldığında `%100` sayısı yanlışlıkla gerekçede
kullanılabilir hale geliyordu.

**Neden ciddiydi:** `son_hareket_gun_once = 1` demek "ürün dün hareket görmüş".
2.000 SKU'lu bir katalogda aktif ürünlerin büyük kısmı bu durumda — yani delik
sürekli açıktı. Ve `%100` bir dil modelinin uydurmaya en yatkın olduğu
sayılardan ("stok %100 tükendi", "tedarikçi %100 zamanında teslim yapıyor").

**Kişi A düzeltti:** `ORAN_ALANLARI` adlı açık bir liste eklendi, `×100`
karşılığı yalnızca gerçek oran alanları için üretiliyor. 3 regresyon testi
eklendi. Ayrı bir `fix-izinli-sayilar-oran-alanlari` branch'ine push edildi
(dosya ortak/dondurulmuş olduğu için).

**Doğrulandı:** İki branch geçici bir kopyada birleştirilip test edildi —
**94 test geçiyor**, lint temiz. Sözleşme değişikliği Kişi B'nin kodunu
bozmuyor.

Ek karar: `guven` bilinçli olarak kümenin dışında — güven skoru iç politika
kararı için üretilir, iş kullanıcısına gösterilecek bir sayı değil.

## Merge planı — `main` hâlâ Faz 0'da

Beş branch birden Faz 0'dan ayrılmış durumda, hiçbiri birleştirilmemiş. Dallar
şöyle bağlı:

```
main (Faz 0)
 ├── faz1-servis                          (Kişi B, 7 commit)
 └── faz1-simulator                       (1)
      └── faz2-kural-motoru               (2)
           ├── fix-izinli-sayilar-...     (3)  ← sözleşme düzeltmesi
           └── faz3-egitim-verisi         (11) ← düzeltme YOK (kardeş dal)
```

`fix-...` branch'i `faz1-simulator` ve `faz2-kural-motoru`'nu **zaten
içeriyor** — onu birleştirmek üçünü birden getiriyor. Yani beş değil **üç
merge** yeterli.

**Prova yapıldı** (geçici bir kopyada, sırayla birleştirilip test edildi):

| Sıra | Branch | Sonuç |
|---|---|---|
| 1 | `faz1-servis` | temiz |
| 2 | `fix-izinli-sayilar-oran-alanlari` | `aciklama.md` çakışması |
| 3 | `faz3-egitim-verisi` | `aciklama.md` çakışması |

Birleşik ağaçta **130 test geçiyor**, `alembic upgrade head` ve `alembic check`
temiz, `contracts.py` düzeltmesi hayatta, `decide_stub()` duruyor.

**Çakışma çözümü hep aynı:** `aciklama.md` için birleşik sürümü koru
(`git checkout --ours aciklama.md`) — o dosya zaten ikisinin içeriğini taşıyor.

Birleştirme bitince `faz1-simulator` ve `faz2-kural-motoru` silinebilir
(içerikleri `fix-...` üzerinden geldi).

### Provada bulunan sorun: CI kırmızı olacaktı

`training/paraphrase_colab.ipynb` içinde üç satır 100 karakteri aşıyor —
notebook hücrelerindeki **prompt metinleri**. Kod değil, modele gönderilen
cümleler; bölmek prompt'u ve modelin davranışını değiştirir.

Kişi A'nın branch'leri CI'ı hiç görmedi (CI Kişi B'nin branch'inde), o yüzden
fark edilmemişti. Merge sonrası `main`'de patlardı.

Düzeltme `pyproject.toml`'a eklendi (`faz1-servis` branch'inde, yani `main`'e
ilk giren PR'da):

```toml
"training/**/*.ipynb" = ["E402", "I001", "E501"]
```

⚠️ **2. merge'de `pyproject.toml` de çakışabilir** — Kişi A aynı bölüme
`notebooks/**/*.ipynb` satırını eklemişti. Çözüm: **iki satırı da tut**, ama
aynı anahtarı iki kez yazma (TOML yinelenen anahtar kabul etmez).

## Açık konular (2026-08-03 itibarıyla güncellendi)

**1. ✅ Kapandı — `StockFeatures`'ta üç alanın kaynağı.** Kişi A kesinleştirdi:
`tedarikci_onayli` eşiği (70.0) gerçek veriyle doğrulandı, `raf_omru_kalan_gun`
ve `rezerve_stok` mevcut haliyle nihai karar olarak işaretlendi (detay
yukarıda, A3.5 sonrası bölümünde).

**2. ✅ Kapandı — A3.5** (train/val/test bölme + golden set adayı). SKU bazlı
bölme, sızıntı yok, golden set 7/7 araç kapsıyor. **Yalnızca golden set'in
nihai onayı** ("ikiniz birlikte 300-500 örneği elle gözden geçirin") hâlâ
bekliyor — bu, tanım gereği tek başına kapatılamayan tek adım.

**3. ✅ Kapandı (2026-08-05) — `decisions.py` artık `decide_stub()` çağırmıyor.**
Faz 3 (LoRA, `codifya-router:tur2`) tamamlanınca geçiş yapıldı:
`app/api/decisions.py` → `stok_karari_uret()`/`gerekce_uret()`,
`app/jobs/nightly.py::_cli()` → `_gercek_karar_ureteci`/`llm_gerekce_ureteci`.
`gecelik_tarama()`'nın kendi varsayılanları (stub) testler için bilinçli
olarak kaldı. `test_api_smoke.py`'deki iki test, sabit stub değerleri yerine
gerçek (sabit seed'li) motor çıktısına göre güncellendi — LLM'in stokastik
olduğu (sıcaklık > 0, sabit tohum yok) göz önünde bulundurularak yapısal
kontrole geçildi. SP3 doğrulaması: guard kabul oranı taban model %0 →
eğitilmiş model %25,7 (bkz. `dokumantasyon/OLCUMLER.md`).

**4. ✅ Kapandı — A3.2'deki 7 araç listesi.** Kişi B gerçek router şemasını
(`app/llm/schemas.py::AracAdi`) A3.2'nin geçici listesiyle **birebir aynı**
tutarak yazdı — yeniden üretmeye gerek kalmadı. Tek fark: `sku_adi` parametre
anahtarı `sku_id` olarak düzeltildi (içerik zaten SKU koduydu), iki taraf da
buna göre hizalandı.

**5. YENİ — `stok.tedarikci_degisim` hiç üretilmiyor.** `KararTipi` enum'unda
tanımlı ama `decide.py::ozellikten_karar_uret` bu kararı hiçbir zaman
üretmiyor (tedarikçi değişim mantığı hiç yazılmadı). Golden set'e bu yüzden
örneği eklenemedi. Kod hatası değil, ileride ele alınabilecek yazılmamış bir
özellik — şimdilik kapsam dışı.

## Merge + branch temizliği (2026-08-03)

PR #2 (`faz2-llm` → `main`, 36 commit, Faz 1-5'in tamamı) her iki tarafın da
bağımsız doğrulamasından (Kişi B: 271 test + ruff + alembic yerelde; GitHub
Actions CI: Ubuntu'da yeşil) geçtikten sonra merge edildi
(`6a50f7d8`). `main` artık projenin **tek gerçek kaynağı** — simülatör, kural
motoru, ML, LLM client/router/guard/gerçek gerekçe üretimi, DB katmanı, API
uçları, CI hepsi tek ağaçta.

Merge sonrası 6 branch (`faz1-simulator`, `faz2-kural-motoru`,
`faz3-egitim-verisi`, `fix-izinli-sayilar-oran-alanlari`, `faz1-servis`,
`faz2-llm`) `git merge-base --is-ancestor` ile **tek tek** doğrulanıp (hepsi
`main`'in ataları — hiçbir commit kaybolmuyor) hem yerelde hem GitHub'da
silindi. Artık ekip yalnızca `main`'den branch açıyor.

**Bilinçli olarak yapılmadı:** `main`'in canlı davranışı değişmedi —
`app/api/decisions.py` hâlâ stub veri döndürüyor (bkz. Açık konular #3).
Merge "kodun birleşmesi", "sistemin canlanması" değil.

## Faydalı komutlar

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

## Güncelleme geçmişi

| Tarih | Ne oldu |
|---|---|
| 2026-07-30 | **B:** Adım 0 (ortam), Adım 1 (okuma), B1.1–B1.6 tamamlandı, `faz1-servis` push edildi, CI yeşil. Kişi A'nın Faz 1 PR'ı incelendi ve onaylandı. |
| 2026-07-30 | **B:** `contracts.py` ×100 kusuru ölçüldü, yama önerildi. **A:** düzeltmeyi uyguladı, 3 regresyon testi ekledi. Birleşik ağaçta 94 test yeşil. |
| 2026-07-30 | **A:** Faz 2 (kural motoru + ML), Faz 3 A3.1–A3.4 (eğitim verisi), Faz 4-5 (genellenebilirlik + para metriği) tamamlandı. |
| 2026-07-30 | **Ortak:** iki ayrı `aciklama.md` tek dosyada birleştirildi. |
| 2026-07-30 | **B:** B2.1 bitti — model indirildi, `client.py` yazıldı (18 test, modelsiz), hız ölçüldü (22,4 token/sn @ 4 iplik), ısı koruması kondu. Ölçümler `dokumantasyon/OLCUMLER.md`'de. |
| 2026-08-02 | **B:** B2.2 (yapılandırılmış çıktı), B2.3 (router + `/v1/ask`), B2.5 (guard, 41 test — Kişi A bağımsız doğruladı), B2.4 (gerçek gerekçe üretimi, 261 test — Kişi A bağımsız doğruladı), B2.6 ölçümü (2.000 SKU / 5,31 dk, karar-gerekçe arası 88x fark) tamamlandı. **Faz 2 kapandı.** |
| 2026-08-02 | **A:** A3.5 sonrası — Kişi B'nin bulduğu router dengesizliği (3.808x→~143x), `sku_adi`→`sku_id` düzeltmesi, golden set yeniden dengelendi (2/7→7/7 araç) + `tedarikci_onayli=False` sentetik vaka eklendi. `StockFeatures`'ın 3 açık alanı kesinleştirildi. |
| 2026-08-03 | **Ortak:** PR #2 (`faz2-llm`→`main`, 36 commit) her iki tarafın bağımsız doğrulamasından (yerel + GitHub Actions CI) geçip merge edildi (`6a50f7d8`). 6 eski branch güvenle silindi (`git merge-base --is-ancestor` ile tek tek doğrulanarak). `main` artık projenin tek gerçek kaynağı. Sırada: Kişi B'nin Faz 3'ü (LoRA eğitimi) ve golden set'in nihai ortak onayı. |
| 2026-08-03 | **B:** Faz 3 basladi — B3.1 (Colab ortami, dort olcut Colab'da dogrulandi), B3.2 (100 ornekle boru hatti provasi, 4/4), B3.3 1. tur (15k ornek, ~56 dk, dogrulama kaybi 0,225→0,188, ezberleme yok). Guard'da kucuk sayi hatasi bulundu ve duzeltildi (siparis gerekcelerinin %16,9'u bosuna reddediliyordu). 1. tur router olcumu %70→%40 **dustu**; sebep veri seciminde bulundu (uc arac egitime hic girmemis) ve verinin eski kopya oldugu **A** tarafindan kanitlandi. |

---
---

# FAZ 3 — LoRA EĞİTİMİ (Kişi B)

Faz 2'de dil modelini **kullandık**. Faz 3'te onu **eğiteceğiz**.

Neden gerek var: B2.4 ölçümünde gördük ki 1.5B taban model Türkçeyi kabaca
yazıyor — devrik cümleler, zayıf fiiller. İstem düzelterek buraya kadar
geldik, gerisi eğitimle düzelir. Melih'in ürettiği **40.293 gerekçe** ve
**43.798 router sorusu** tam bunun için var.

Eğitim **Colab'ın GPU'sunda** yapılacak, bilgisayara yük binmeyecek.

## B3.1 · Colab ortamı (bitti ✅, Colab'da doğrulandı)

`training/train_lora.ipynb` — Colab'da açılacak defter. Eğitim yapmıyor,
eğitimin **koşabileceği ortamı kurup kanıtlıyor**.

Ücretsiz Colab'ın üç kısıtı tasarımı belirliyor:

| kısıt | sonucu |
|---|---|
| Tek T4 GPU | 55 bin örnek için 4-7 saat |
| Oturum ~90 dk boşta, ~12 saatte kesin kopar | **Tek koşu büyük olasılıkla yarıda kesilir** |
| `/content` uçucu | Oturum kapanınca dosyalar gider |

Bu yüzden eğitim kaldığı yerden devam edebilen bir süreç olacak ve her şey
Drive'da duracak.

### Eğitime girmeden bulunan iki sorun

Defteri yazarken veriye baktım ve ikisi de eğitimi çöpe atacak cinsten.

**1. Ürün adı çelişkisi.** Melih'in eğitim verisindeki gerekçelerin
**%100'ünde** ürün adı geçiyor. Ama B2.4'te istemden ürün adını **bilerek
çıkarmıştım** — taban model adları bozuyordu ("Astar Boya" → *starboy*).

Bu ikisi uyuşmak zorunda. İsteme ad koymayıp hedefte ad varsa, model *yoktan
ad uydurmayı* öğrenir — "starboy" sorununu ağırlıklara işlemiş oluruz.

**Karar: ad isteme konacak.** Böylece model adı *kopyalamayı* öğrenir. Taban
model beceremiyordu çünkü hiç öğretilmemişti. B3.2'de 100 örnekle sınanacak —
tam eğitimden önce, ucuz.

**2. Guard eğitim verisinin %17'sini boşuna reddediyordu.**

Bu bir hata ve düzeltildi. Ayrıntısı aşağıda.

## Guard düzeltmesi — küçük sayılara haksızlık

B2.5'te guard'a şu kuralı koymuştum: *"yazılan sayı gerçeğinden en fazla %2
sapabilir."* Amaç `0,94 → "1"` gibi kaba yuvarlamaları kesmekti.

Ama kural küçük sayılara haksızlık ediyor:

```
gercek   0,14444...
yazilan  "0,14"        <- 2 ondalikta DOGRU yazim, kimse 0,14444 demez
fark     %3,08         <- %2 sinirini asiyor
sonuc    RED
```

Sayı küçüldükçe aynı yuvarlama yüzde olarak büyüyor. 1.000 TL'lik üründe %2
tolerans 20 TL demek — makul. 0,14'lük değerde 0,003 demek — imkânsız.

Etkisi ölçüldü:

```
stok.tasfiye        0/1059   %0,0
stok.aksiyon_yok    0/3639   %0,0
stok.siparis       51/ 302  %16,9   <- her alti siparis gerekcesinden biri
```

Sadece eğitim verisini değil **çalışma zamanını da** etkiliyordu: günlük talebi
1'in altında olan her SKU'da gerekçe sessizce şablona düşüyordu. B2.4
ölçümünde fark etmemiştim çünkü oradaki 10 ürünün değerleri şans eseri sınırın
içinde kalmış.

### Düzeltme

Kurala bir istisna eklendi: **virgülden sonra 2 basamak yazılmışsa bağıl sınır
aranmaz.** Kaç ondalık yazdığın, ne kadar hassas davrandığını ilan eder.
`"0,14"` yazan iki basamak hassasiyet iddia ediyor; `"1"` yazan hiç.

```
"0,14"  ondalik 2  ->  KABUL   (duzeltme)
"1"     ondalik 0  ->  RED     (eskisi gibi)
"5"     ondalik 0  ->  RED     (eskisi gibi)
```

Asıl amaç korundu — `0,94 → "1"` ve `4,75 → "5"` hâlâ reddediliyor.

Sonuç: **5.000 eğitim hedefinin 5.000'i geçiyor** (önce 4.949).

3 yeni test. Toplam **274 test yeşil**.

⚠️ Guard'ı Melih incelemiş ve onaylamıştı; bu değişiklik ona bildirilecek.

### Colab'da koşturuldu — dört ölçüt de geçti

```
GECTI  GPU baglandi: Tesla T4          (14,6 GB VRAM)
GECTI  Drive bagli: MyDrive/codifya
GECTI  unsloth import edildi           (kurulum 37 sn)
GECTI  veri/ okunabiliyor ve bicim dogru
B3.1 TAMAM
```

Veri Drive'a yüklendi ve satır sayıları birebir doğrulandı: `gerekce_train`
40.293, `router_train` 43.798. İstem/cevap biçimi de defterde gösterildi.

Yol boyunca çıkan tek engel: Colab "çok fazla oturum var" dedi. Sabah açılan
eski defter GPU'yu tutuyordu; oturumu sonlandırınca çözüldü. Ücretsiz Colab
aynı anda tek GPU oturumuna izin veriyor — B3.3'te uzun eğitim koşarken bunu
akılda tutmak gerek, ikinci bir defter açmak eğitimi düşürür.

### Sırada

- ⬜ B3.2 — 100 örnekle boru hattı provası (eğit → kaydet → merge → GGUF →
  Ollama). Görev dosyası "bu adımı atlama" diyor: tam eğitim 4-7 saat sürüyor
  ve 3. saatte çıkacak bir biçim hatası hem eğitimi hem Colab oturumunu yakar.

## B3.2 · 100 örnekle boru hattı provası (bitti ✅)

Görev dosyasının "atlanmaz" dediği adım. Amaç kalite değil, **hattın uçtan uca
çalıştığını kanıtlamak**: yükle → eğit → kaydet → üret.

```
egitilen parametre   18,4 milyon / 1,56 milyar  =  %1,18
kayip                0,77 -> 0,54 -> 0,43 -> 0,39   (duzenli dusuyor)
egitim suresi        63 saniye
LoRA boyutu          81,4 MB    (tam model 3 GB olurdu)
olcutler             4/4 GECTI
```

Kayıp düzenli düşüyor — eğitim gerçekten oluyor. Boru hattı sağlam.

### Ürün adı sınavı: cevap aldık sandık, almadık

Üç örnekte de ürün adı **birebir doğru** kopyalandı. "starboy" yok. İlk bakışta
B3.1'deki kararımız doğrulanmış görünüyor.

**Ama üretilen metinler hedeflerle harfi harfine aynı çıktı.** Model o üç
örneği ezberlemiş — 100 örnek, 30 adım ve 0,39 kayıpla beklenen şey bu.

Yani cevapladığımız soru *"adı kopyalayabiliyor mu"* değil, *"ezberleyebiliyor
mu"* idi. İkisi aynı şey değil.

Doğru sınav modelin **hiç görmediği** örnekle yapılır. `gerekce_val.jsonl` tam
bunun için ayrılmış; deftere o bölümü ekledim, B3.3'ün yanında koşacak.

Bunu kaydetmeye değer çünkü **ölçüm yaparken en kolay düşülen tuzak bu:
eğitim verisinden ölçmek.** B2.4'te de benzeri olmuştu — guard "7/10 geçti"
demişti ama metinler istemin kopyasıydı. Sayı doğru, soru yanlış.

### B3.3 için çıkan tahmin

100 örnek 63 saniye sürdü. 40.293 örnek için kabaca **4-6 saat** — görev
dosyasının 4-7 saat tahminiyle uyumlu. LoRA 81 MB olduğu için ara kayıtlar
Drive'da rahat sığar.

### Sırada

- ⬜ B3.3 — tam LoRA eğitimi (40.293 örnek, 4-6 saat, kesintiye dayanıklı)

## B3.3 · 1. tur eğitimi (bitti ✅)

15.000 örnekle (7.500 gerekçe + 7.500 router) tek model eğitildi, **~56 dakika**.
Ayrım `GOREV:` etiketiyle yapılıyor. Eğitilmiş adaptör Drive'da:
`cikti/b33_tur1_lora/`.

### Sonuç: ölçüt karşılandı

```
dogrulama kaybi   0,2250  ->  0,1878     dusup yataylasti
egitim kaybi      0,2988  ->  0,1877
```

**Ezberleme yok.** Eğitim kaybı 0,1877, doğrulama 0,1888 — ikisi neredeyse aynı.
Eğitim kaybı doğrulamanın belirgin altına inseydi ezberleme olurdu; burada aralık
yok.

### Ama iyileşme sertçe yavaşlıyor

```
ilk yari    (200 -> 1000)   0,2250 -> 0,1944    fark 0,0306
ikinci yari (1000 -> 1875)  0,1944 -> 0,1888    fark 0,0056
```

İkinci yarı, benzer miktarda veriyle ilkinin **beşte birini** kazandırdı. Bu, 2.
tur (35 bin örnek) için doğrudan bir uyarı: kayıp tarafında büyük kazanç
beklenmemeli.

### Kayıp yanlış soru olabilir

`0,188` bize **router doğruluğunun** ne olduğunu söylemiyor. B2.3'te ölçtüğümüz
taban çizgi araç doğruluğu **%70,0**, araç+parametre **%66,7** idi. Eğitimin işe
yarayıp yaramadığı ancak aynı 30 soruluk set yeniden koşturulunca anlaşılır.

Görev dosyası da 1. turun amacını böyle tanımlıyor: *"Tek oturumda biter. **Router
doğruluğunu ölç.**"*

**Karar: 2. tura geçmeden önce ölçüm yapılacak.** Eğitim ucuz değil (56 dakika);
neyi kazandırdığını bilmeden ikincisini koşturmak körlemesine olur.

### Sırada

- ⬜ 1. tur ölçümü — 30 soruluk router seti + görülmemiş örnekte ürün adı
- ⬜ Ölçüme göre karar: 2. tur (35k) mı, yoksa veri kalitesi mi

## 1. tur ölçümü: doğruluk DÜŞTÜ — sebebi benim veri seçimim

```
arac dogrulugu    %70,0  ->  %40,0     dustu
arac + parametre  %66,7  ->  %26,7     dustu
sema hatasi        2/30  ->   8/30     artti
olu_stok_sorgula    1/5  ->   4/5      IYILESTI
```

### Ne oldu

Veriyi hazırlarken router dosyasının **ilk 7.500 satırını** aldım, rastgele
seçmedim. Dosya araca göre sıralıymış:

```
                                  EGITIME GIREN    TUM DOSYA
  siparis_onerisi_sorgula              6.742         41.886   %90
  gecelik_ozet_sorgula                     0             66   SIFIR
  onay_kuyrugu_sorgula                     0             14   SIFIR
  genel_stok_durumu_sorgula                0             11   SIFIR
```

**Üç araç eğitime hiç girmedi.** Model hiç görmediği aracı seçemez — ölçümde de
o üçünü hiç seçmedi. Taban çizgide bu üçlü 9/10 doğru cevap veriyordu; düşüşün
büyük kısmı burada.

Eğitimin çalıştığının kanıtı da aynı tabloda: `olu_stok_sorgula` 99 örnek gördü
ve **1/5'ten 4/5'e** çıktı. Sorun eğitimde değil, neyi eğittiğimizde.

### Ölçüm de tam adil değildi

Taban çizgi Ollama'nın **JSON şema zorlamasıyla** ölçülmüştü — model geçersiz
JSON üretemiyordu. Bu ölçümde zorlama yok, ham üretim var. 8 şema hatasının bir
kısmı modelin değil, kurulumun farkı. Geçerli JSON çıkan 22 sorunun 12'si doğru
= %54,5.

**Ders: iki ölçümü karşılaştırırken yalnızca modeli değil, çevre koşullarını da
eşitle.** Yoksa hangi farkın neyden geldiği bilinmez.

### 2. tur için

1. **Sınıf ağırlıklı örnekleme** — her araca taban kota, seyrek olanlar
   tekrarlanarak. Görev dosyası B3.3'te bunu zaten istiyordu; atlamışım.
2. **Rastgele örnekleme** — sıralı alma bir daha yapılmayacak.
3. **Şema zorlaması** — ölçüm taban çizgideki gibi JSON kısıtıyla yapılmalı.
4. Melih'e sorulacak: dengelenmiş router dışa aktarımı var mı? Elimizdeki dosya
   hâlâ **3.808 kat** dengesiz (41.886 vs 11).

## 2. tur hazırlığı: sınıf ağırlıklı örnekleme

1. turun hatası düzeltildi. Yeni örnekleyici her araca **taban kota** veriyor ve
seyrek olanları tekrarlıyor — ama tekrarı sınırlayarak.

```
dengesizlik   68x (+ uc arac SIFIR)  ->  3,0x
disarida kalan arac                  ->  0
ozgun soru                           ->  %42,5
```

### `TAVAN_KAT` neden var

11 örnekli bir aracı sınırsız tekrarlamak modele o **11 cümleyi ezberletir**,
aracı öğretmez. Tavan tekrar katsayısını bağlıyor. Yerelde ölçülen denge:

| tavan | özgün soru | en seyrek kota | dengesizlik |
|---|---|---|---|
| 10 | %47,5 | 110 | 15,0x |
| 20 | %44,4 | 220 | 6,5x |
| **40** | **%42,5** | **440** | **3,0x** |
| 80 | %37,2 | 880 | 1,3x |

İlginç olan: tavanı 10'dan 80'e çıkarmak dengesizliği **15x'ten 1,3x'e**
indiriyor ama özgünlüğü sadece %47'den %37'ye düşürüyor. Denge ucuz. **40**
seçildi.

### Ama bu bir yama

**Hiçbir örnekleme 11 özgün soruyu çoğaltamaz.** Ölçüm iyileşebilir — model o 11
kalıbı öğrenir — ama aynı aracın *yeni* bir soruluşunu tanıması beklenmez.
Gerçek çözüm seyrek araçlar için daha çeşitli soru üretmek, o da Melih'in tarafı.

### Gerekçe verisi etkilenmemişti

Aynı hatayı gerekçe tarafında da yapmıştım ama zararsız kalmış:

```
                     ILK 7.500   gercek dagilim
  aksiyon_yok          %72,3        %67,6
  tasfiye              %20,5        %24,8
  siparis               %7,2         %7,5
  hic girmeyen tip: yok
```

Yine de 2. turda gerekçe tarafı da rastgele ve dengeli örnekleniyor.

## İki düzeltme

### Elimizdeki veri eski kopyaymış

Melih kanıtladı: `41.886 = 52.000 × (1611/2000)` — dosyamız dengeleme
uygulanmamış ham sürüm. Onun güncel dosyasında `siparis_onerisi_sorgula`
train'de **1.633**.

Yani **1. turun bütün dağılım sayıları eski veriye ait.** Yeni veriyle
tekrarlanmalı.

### "Dosya araca göre sıralı" teşhisim yanlıştı

Doğrusu: dosya **bloklu**. Üç seyrek aracın hiçbiri 20.090. satırdan önce yok:

```
genel_stok_durumu     ilk gorunum  20.131. satir
onay_kuyrugu          ilk gorunum  20.090. satir
gecelik_ozet          ilk gorunum  20.098. satir
```

İlk ~20.000 satır bir üretim partisi (yalnızca 4 araç), sonrası ikinci parti.
İlk 7.500 satırı almak o üçünü **hiçbir koşulda** yakalayamazdı. Etki aynı,
sebep farklı.

**Ders: bir dosyanın "karışık" olduğunu varsayma, bak.** Yazdığım basit "her
değer tek blok mu" kontrolü bunu yakalayamadı — *"sıralı değil"* dedi. Gerçeği
gösteren şey konum dağılımı oldu.

### Seyrek araçlar için Melih çözüm hazırlamış

`--sablon-ihrac-araclar` bayrağı 3 seyrek aracın 28 şablonunu ayrı dosyaya
çıkarıyor; parafraz defterindeki `VARYANT_SAYISI` 2'den 12-15'e çıkarılınca
gerçek çeşitlilikte yeni sorular üretiliyor.

Bu, benim tekrarlama yamamdan **çok daha iyi**. Tekrarlamak 11 cümleyi
ezberletiyordu; bu yöntem 11'i 150-200 farklı soruya çıkarıyor.

## `GOREV:` biçimi çalışma zamanına taşındı

Eğitilmiş modeli sisteme takmadan önce yapılması gereken iş. Eğitimde modele şu
biçim öğretildi:

```
GOREV: router              GOREV: gerekce
SORU: ...                  VERILER: ...
                           GEREKCE:
ARAC:
```

Ama `router.py` ve `explain.py` hâlâ B2.3/B2.4'ün taban model istemlerini
kullanıyordu — kurallar bloğu, few-shot örnek, uzun sistem promptu. Eğitilmiş
modeli o istemle çalıştırmak, modelin **hiç görmediği** bir girdi göndermek
demek; eğitim ne kadar iyi olursa olsun sonuç bozulur.

### Yapılan

Yeni ayar: `llm_istem_bicimi = "taban" | "egitilmis"`. Varsayılan `taban` —
eğitilmiş model henüz üretime hazır değil.

| | taban kip | eğitilmiş kip |
|---|---|---|
| sistem promptu | var (~600 token) | **yok** |
| kurallar + örnek | var | **yok** |
| ürün adı (gerekçe) | **yok** | **var** |
| istem uzunluğu | ~600 token | ~60 token |

### Ürün adı: iki kip zıt, ikisi de doğru

B2.4'te adı istemden **çıkarmıştım** çünkü taban model bozuyordu (`Astar Boya`
→ *starboy*). Eğitim verisindeki gerekçelerin ise **%100'ünde** ad geçiyor;
eğitilmiş kipte adı koymazsak model *yoktan ad uydurmayı* öğrenmiş olur.

Yani aynı sorunun iki modelde iki farklı doğru cevabı var. Test bunu kilitliyor:
`test_egitilmis_istem_URUN_ADINI_TASIYOR` biri koyuyor, diğeri koymuyor diye
ikisini birden doğruluyor.

### Etiketlerde Türkçe karakter yok

Eğitim verisi `gunluk ortalama talep`, `tedarik suresi` diye üretilmişti.
Düzeltmek cazip ama **model bunu gördü**; değiştirmek eğitimin kazandırdığını
çöpe atar. Test bunu da kilitliyor.

### Bilinen sınır: eğitilmiş kipte yeniden deneme çalışmıyor

Taban kipte guard reddedince isteme *"şu sayıları kullanma"* uyarısı ekleniyor.
Eğitilmiş modelde böyle bir satır eğitimde hiç geçmedi; eklemek modeli dağılım
dışına çıkarır.

Sonucu: eğitilmiş kipte ikinci deneme birincinin aynısı olur (açgözlü üretimde
birebir) ve boşa gider. Çözümü hazır — yeniden denemede sıcaklığı yükseltmek,
istemi değiştirmeden çıktıyı değiştirir. Model üretime alınırken yapılacak.

7 yeni test. Toplam **282 test yeşil**.

## Ölçüm adaleti: ayrı betik değil, aynı betik

1. tur ölçümünü Colab'da ham `generate()` ile yapmıştım; taban çizgi ise
Ollama'nın **JSON şema zorlamasıyla** ölçülmüştü. 30 sorunun 8'i "şema hatası"
sayıldı ama bir kısmı modelin değil, **kurulumun** farkıydı.

İlk düşüncem Colab'da şema zorlamasını taklit etmekti. Daha iyi bir yol var:
`training/eval/router_taban.py` zaten `soruyu_yonlendir()` kullanıyor — yani
taban çizgiyle **birebir aynı kod yolu**. Tek eksik, modeli seçebilmekti.

İki bayrak eklendi:

```bash
uv run python -m training.eval.router_taban   --model codifya-router:tur2 --istem-bicimi egitilmis --etiket lora-tur2
```

Artık B3.5 ölçümü şu olacak: **aynı betik, aynı 30 soru, aynı puanlama, aynı
şema kısıtı, aynı sıcaklık ve tohum. Tek değişen model.**

`--istem-bicimi egitilmis` bir önceki bölümde eklenen ayarı kullanıyor — model
eğitimde gördüğü kısa `GOREV:` istemini alıyor, taban modelin uzun istemini
değil.

### Ön şart

Bu ölçüm ancak eğitilmiş model **Ollama'da** olunca çalışır. Yani B3.4 (merge →
GGUF → `ollama create`) tamamlanmadan koşturulamaz. Colab'daki ara ölçümler
gidişat için bilgi verir ama **karşılaştırma sayısı** buradan çıkacak.

Toplam **282 test yeşil**.

## Güncel veri geldi ve doğrulandı

Melih'in parafraz turu sonrası dosyalar indirildi ve kontrol edildi:

```
DENGELENMIS       siparis_onerisi 1.633  (once 41.886)
eksik arac        yok
sizinti           train/val/test uclusu de TEMIZ
ozgun soru        3.674/3.674  (%100)
```

Seyrek araçlar arttı (eğitim bölümü): `genel_stok_durumu` 11→26,
`onay_kuyrugu` 14→39, `gecelik_ozet` 66→155. Bölümler toplamı Melih'in verdiği
sayılarla tutuyor.

⚠️ **Dosya hâlâ araca göre sıralı.** Yani 1. turdaki hata bu veriyle de tekrar
ederdi — dengeli örnekleme zorunluluğunu koruyor. Kontrol betiği bu sefer
uyarıyı bastı (eski dosyada basamamıştı, sebebi bloklu yapıydı).

### Örnekleme ayarı yeniden ölçüldü

Havuz 43.798'den 3.674'e indiği için 7.500 router hedefi anlamsızlaştı:

| router hedefi | özgün | en çok tekrar |
|---|---|---|
| 7.500 | %38,3 | 40,0x |
| **2.000** | **%64,5** | **11,0x** |
| 1.400 | %72,9 | 7,7x |

Denge her ayarda tam (1,0x); fark özgünlükte. Tekrarlanan örnek ilk birkaç
geçişten sonra neredeyse hiçbir şey öğretmiyor, yani düşük özgünlük boşa hesap.

**Seçilen: router 2.000, gerekçe 8.000.** Toplam 10.000 — Tur 1'den küçük ama
üç aracın hiç görülmediği bir 15.000'den kesinlikle iyi.

## `veri_hazirla.py` repoya taşındı

2. tur eğitimi Melih'e devredilirken bir eksik ortaya çıktı: defterin okuduğu
gerekçe dosyaları **benim yerelde dönüştürdüğüm biçimde** (`istem` / `cevap`),
ama dönüştüren betik scratchpad'de duruyordu — yani repoda yoktu.

Melih ham dosyaları doğrudan Drive'a koysa defter `KeyError: 'istem'` verirdi.

Betik `training/veri_hazirla.py` olarak taşındı ve komut satırından
çalışacak hâle getirildi:

```bash
uv run python -m training.veri_hazirla --kaynak <ham_klasor> --hedef <cikti_klasor>
```

Ne yapıyor:

```
gerekce_*.jsonl   ->  {istem, cevap} bicimine cevrilir     103 MB -> 27 MB
router_*.jsonl    ->  oldugu gibi kopyalanir  (defter kendi bicimlendiriyor)
golden_set        ->  oldugu gibi kopyalanir
```

`izinli_sayilar` yalnızca val/test dosyalarında korunuyor — B3.5 ölçümünde
guard'ı koşturmak için gerekli, eğitimde gereksiz.

⚠️ Betikteki etiketler `app/llm/explain.py::_EGITILMIS_ETIKETLER` ile birebir
aynı olmak zorunda. İkisi ayrışırsa eğitilmiş model çalışma zamanında
tanımadığı bir istem görür. Dosya başına bu uyarı yazıldı.

### Devir sebebi

GPU kotası tekrar doldu (bugün ~1,5 saat T4 kullanıldı). 2. tur eğitimi
Kişi A'ya devredildi; defter, veri ve hazırlık betiği repoda hazır.

## 2. tur eğitimi bitti (Melih koşturdu)

GPU kotam dolduğu için eğitimi Melih devraldı. Defter, veri ve hazırlık betiği
repodan aldı.

```
                  1. tur              2. tur
ornek             15.000              9.993
router            7.500 (3 arac YOK)  1.995 = 285 x 7 arac
gerekce           7.500               7.998 = 2.666 x 3 tip
denge             68x + uc arac yok   TAM DENGELI
sure              56 dk               44 dk
```

### Kayıp eğrisi

```
adim    egitim   dogrulama
 200    0,2421    0,2920
 600    0,1982    0,2439
1000    0,1822    0,2192
1250    0,1797    0,2134
```

Doğrulama kaybı baştan sona düştü, hiç yükselmedi — **ezberleme yok**.

⚠️ **1. turun kaybıyla karşılaştırılamaz.** 1. turda 0,1888'di, şimdi 0,2134.
Daha yüksek görünüyor ama **veri değişti**: bu turda seyrek araçların örnekleri
çok daha ağırlıklı ve onlar daha zor. Farklı veri kümesinde ölçülen kayıplar
yan yana konmaz. Karşılaştırılabilir tek şey **router doğruluğu**.

### Benim hatam çıktı ve düzeltildi

`veri_hazirla.py`, `karar_tipi` alanını yalnızca val/test dosyalarına
koyuyordu — "boyut küçültme" diye. Ama defterin dengeleme kodu o alanı eğitim
dosyasında arıyordu, `KeyError` verdi. Melih geçici olarak istem metninden
çıkarmış, veri kaybı olmamış.

Kalıcı düzeltme yapıldı: `karar_tipi` artık **her dosyada**. Alan başına ~20
bayt, 40 bin satırda 800 KB — dengeli örneklemenin çalışması için ödenecek
bedel bu değildi.

**Ders: aynı veriyi üreten ve tüketen iki kod parçası varsa, aralarındaki
varsayım tek yerde yazılı olmalı.** Burada yazılı değildi; biri alan çıkardı,
diğeri o alanı aradı.

## B3.4 hazır: merge → GGUF → Ollama

Eğitilmiş LoRA'yı taban modelle birleştirip Ollama'nın anlayacağı biçime
çeviren bölüm deftere eklendi. Bundan sonra model **yerelde**, ERP'nin yanında
çalışacak.

**GPU gerekmiyor** — birleştirme ve dönüştürme işlemci işi. Kota doluysa
"GPU olmadan bağlan" ile de koşar.

### Neden `q8_0`

```
f16      ~3,1 GB   kayipsiz
q8_0     ~1,6 GB   pratikte kayipsiz    <- secilen
q4_k_m   ~1,0 GB   hafif kayip + llama-quantize derlemesi ister
```

`convert_hf_to_gguf.py` `q8_0`'ı doğrudan üretiyor, derleme gerekmiyor. 1,5B
modelde kalite farkı ölçülemeyecek kadar küçük.

### ⚠️ En kritik ayar: `TEMPLATE`

Ollama varsayılan olarak modelin **sohbet şablonunu** uygular
(`<|im_start|>user ...`). Ama bu model **ham metinle** eğitildi:

```
GOREV: router
SORU: kritik stok var mi

ARAC:
```

Sohbet şablonu araya girerse model eğitimde hiç görmediği bir sarmalayıcı görür
ve LoRA'nın kazandırdığı **tamamen kaybolur**. `training/Modelfile`'daki
`TEMPLATE {{ .Prompt }}` bunu engelliyor — istem olduğu gibi geçiyor.

Bu, kolayca gözden kaçıp "eğitim işe yaramadı" sonucuna götürecek türden bir
ayrıntı. Modelfile'a gerekçesiyle yazıldı.

### Modelfile'daki diğer ayarlar

```
stop <|im_end|>, <|endoftext|>   egitim metinleri EOS ile bitiyordu
temperature 0, seed 42           olcum tekrarlanabilir olmali
num_predict 256                  router JSON'u kisa, gerekce iki cumle
num_thread 4                     isi korumasi (B2.1'de olculdu)
```

### Adaptör seçimi

Defterin 2. hücresi `cikti/` altındaki klasörleri **tarih ve boyutuyla**
listeliyor. Melih'in raporundaki yol `b33_tur1_lora` görünüyordu; 2. tur oraya
mı kaydedildi yoksa yazım hatası mı, listeden görülecek. Yanlış adaptörle
ölçüm yapmak, yanlış modeli ölçmek demek.

## B2 · Kişi A'nın Faz 3-4-5 işi incelendi

### Sözleşme değişikliği — onaylandı

`contracts.py::ORAN_ALANLARI`'na `onerilen_iskonto_orani` eklenmiş. Dondurulmuş
dosya olduğu için bağımsız doğruladım; **kanıt Melih'in raporundan daha güçlü**
çıktı:

```
tasfiye iskonto oranlari : 0,15 (4.706) · 0,30 (2.181) · 0,50 (3.113)
hedefte yuzde yazilmis   : 10.000 / 10.000
guard_sonucu = gecti     : 10.000 / 10.000
```

Sadece "%15, 886 kez" değil — üç oranın tamamı, on binin on bini. Veri, bu
alanın ×100 karşılığının izinli olduğu bir guard sürümüyle üretilmiş.

Genişlemenin dar olduğunu da test ettim:

```
iskonto %15 iken  "15" -> KABUL    "20" -> RED
                "0,15" -> KABUL    "30" -> RED
```

### İki kipli ayrım — onaylandı

```
                   taban    egitilmis   fark
stok.siparis         6         6        tedarikci_skoru
stok.tasfiye         4         5        onerilen_iskonto_orani
stok.aksiyon_yok     3         3        -
```

Taban kipin dar tutulması B2.4'te ölçülmüş bir kalite kararıydı (sayı artınca
model veri döküyor). Eğitilmiş kip ise hedefin kullandığı **tüm** sayıları
içermek zorunda. İkisi ayrı kalmalı — doğru yapılmış.

### Yapısal koruma — en değerli parça

`veri_hazirla.py` artık kendi alan listesini taşımıyor,
`explain.py::egitilmis_istem_govdesi`'ni çağırıyor. Eğitim ile çalışma zamanının
ayrışması **yapısal olarak imkânsız** hale gelmiş. Test de bağını doğruluyor.

Veri tutarlılık kapısını yerelde koşturdum (`data/*` gitignore'da olduğu için
veriyi yeniden ürettim): **%79,4 → %0,0**.

### Bir inceleme notu: API artık LLM'i bekliyor

`decisions.py`'de `?gerekce=true` artık senkron olarak LLM çağırıyor. B2.4'te
bunu **bilerek yapmamıştım** — mimarinin ikinci kuralı ("ERP asla LLM'i
beklemez") ve veritabanı oturumunun açık kalması yüzünden.

Melih'in gerekçesi savunulabilir: `gerekce=true` isteğe bağlı, karar yolu
etkilenmiyor, `gerekce_uret` hata fırlatmıyor.

Somut maliyet: **veritabanı oturumu LLM çağrısı boyunca açık kalıyor** (~6 sn,
zaman aşımında 60 sn'ye kadar). Demo/geliştirme ucu için kabul edilebilir,
üretim yükünde bağlantı birikmesine yol açar.

Engellemiyorum; not olarak kalsın, üretime çıkarken tekrar bakılmalı.

### Gürültü payı iddiasına düzeltme

Melih *"router'daki değişim ±7 puan gürültü payında"* demiş. O 7 puan
**sıcaklık 0,2'den** geliyordu; artık sıcaklık 0 + sabit tohumla ölçüyoruz,
aynı model iki kez koşunca **birebir aynı** sonucu veriyor. Gürültü sıfır.

Belirsizlik başka yerden: **30 soru az.** Wilson %95 güven aralığı:

```
19/30 = %63,3  ->  %45,5 - %78,1
21/30 = %70,0  ->  %52,1 - %83,3
27/30 = %90,0  ->  %74,4 - %96,5
```

Yani 2. turun %63,3'ü tabandan **anlamlı şekilde kötü bile değil** — aralıklar
çakışıyor. Sonucu doğru, sebebi farklı: örneklem küçüklüğü.

Anlamlı bir iyileşme iddiası için kabaca **27/30'un üstüne** çıkmak gerekiyor.

## B3 · Eğitilmiş kipte yeniden deneme düzeltildi

Kendi bıraktığım eksik. Eğitilmiş kip `onceki_red`'i isteme yazamıyor (o satır
eğitimde hiç geçmedi). İstem aynı kalınca sıcaklık 0'da çıktı da **birebir
aynı** oluyordu — ikinci deneme bir model çağrısı harcayıp hiçbir şey
kazandırmıyordu.

Çözüm istemi değil **üretimi** değiştirmek:

```
ilk deneme      sicaklik 0,0   tohum 42
yeniden deneme  sicaklik 0,7   tohum 43
istem                    AYNI  (egitimde gorulmeyen satir eklenmiyor)
```

Tohum da değişmeli — sıcaklık yükselse bile aynı tohum aynı örneklemeyi verir.

`0,7` seçildi: 0,2-0,3 açgözlü üretimden yeterince ayrışmıyor, 1,0 üstü
uydurmayı artırıyor. Guard ikinci denemeyi de denetlediği için risk yok;
tutmazsa şablona düşülür.

Taban kipte hiçbir şey değişmedi — orada çözüm zaten istem tarafında.

2 yeni test. Toplam **320 test yeşil**.

## Golden set incelemesi (Kişi B tarafı)

`training/eval/golden_set_inceleme.py` — golden set ölçümlerin tamamının
referansı olduğu için **tek kişi kapatamaz**. Bu betik benim incelememi
üretiyor, karar ortak verilecek.

### Temiz çıkanlar

```
train / val sizintisi   0        <- en kritik kontrol
tekrar                  0/400
guard uyumu             240/240  (%100)
sozlesme uyumu          tum arac ve karar tipleri gecerli
```

**Sızıntı kontrolünde kendi hatamı düzelttim.** İlk sürüm "400 sızıntı" diye
alarm verdi — çünkü golden set'in 400 satırının tamamı `*_test.jsonl`'de de
var. Ama bu **sızıntı değil**: golden set zaten ayrılmış test bölümünden
seçiliyor, örtüşme beklenen ve doğru olan. Tehlikeli olan `train`/`val`
çakışması, o da **sıfır**.

Bu ayrım betiğe yazıldı; yanlış alarm bir daha çıkmayacak.

### Ortak onaydan önce konuşulacak iki şey

**1. İki araç ölçülemeyecek kadar ince**

```
onay_kuyrugu_sorgula        3 ornek   tek hata = %33 oynama
genel_stok_durumu_sorgula   3 ornek   tek hata = %33 oynama
```

Bu araçlar için "ölçtük" demek doğru olmaz. Ya golden set'te sayıları
artırılmalı ya da raporlarda bu iki aracın sonucu **ayrı** verilmeli.

**2. `stok.tedarikci_degisim` hiç yok**

240 gerekçe örneğinin hiçbirinde bu karar tipi geçmiyor. Kural motoru bu tipi
üretmiyorsa beklenen bir durum — ama öyleyse `KararTipi`'nde neden duruyor,
Melih'le netleşmeli.

### Dağılım notu

```
stok.aksiyon_yok   159/240  (%66)
stok.tasfiye        61/240  (%25)
stok.siparis        20/240  (%8)
```

Doğal dağılıma yakın, ama ölçümün üçte ikisi en kolay vakayı (aksiyon yok)
sınıyor. Zor vakalar (sipariş) 20 örnekle temsil ediliyor.

## İnceleme notunu düzeltmeye çevirdim: karar artık gerekçeden önce yazılıyor

İncelemede *"`?gerekce=true` senkron LLM çağırıyor, engellemiyorum ama not
olsun"* demiştim. Nota bakınca asıl sorunun performans değil **veri kaybı**
olduğunu gördüm:

```
ESKI SIRA:  karar uret -> LLM (6 sn) -> veritabanina yaz
```

O altı saniyede süreç ölürse **karar tamamen kayboluyordu** — oysa karar zaten
üretilmişti, kaybedilecek bir şey yoktu.

```
YENI SIRA:  karar uret -> veritabanina yaz -> commit
                       -> LLM (6 sn) -> gerekceyi ekle -> commit
```

`nightly.py` zaten bu deseni kullanıyordu (kararlar bir commit, gerekçeler
ikinci commit). API'ye de taşındı — mimarinin ikinci kuralının veri
katmanındaki karşılığı bu.

Melih'in eklediği özellik olduğu gibi duruyor; yalnızca sırası değişti.

### Yan etki: iki denetim satırı

`?gerekce=true` artık **iki** denetim satırı yazıyor:

```
1. karar kaydedilirken        guard_sonucu = ATLANDI  (gerekce henuz yok)
2. gerekce uretildikten sonra gercek guard sonucu
```

Bu bir kusur değil, denetim izinin amacı: "ne zaman ne oldu" görünsün.
`nightly.py` de aynısını yapıyor. Mevcut test bir satır bekliyordu, gerekçesiyle
güncellendi.

### Teste bağlandı

`test_karar_gerekceden_ONCE_kaliciya_yaziliyor` — gerekçe üretimi zorla
patlatılıyor, kararın yine de veritabanında olduğu doğrulanıyor. Sıra geri
çevrilirse bu test kırılır.

Toplam **321 test yeşil**.


---

## Ek soru seti: ölçemediğimiz iki araç

### Sorun

Modelin doğru aracı seçip seçmediğini 30 soruluk bir setle ölçüyoruz. Ama o
30 soru 7 araca **eşit dağılmıyor**:

```
genel_stok_durumu_sorgula   2 soru
gecelik_ozet_sorgula        3 soru
```

İki soruyla "bu araç %100 doğru" demek ölçüm değil. Yazı tura attık, iki kez
tura geldi. Üçüncü atışta ne olacağını bilmiyoruz.

Ve bu set önemsiz bir set değil — sistemin gerçekten karar vermeye
başlamasına (`threshold` seviyesi) izin verecek olan kapı bu.

### Neden o sete soru eklemedik

Ekleyemezdik. Taban çizgi sayımız (**%70,0**) tam olarak o 30 soruyla
ölçüldü. Eğitimin işe yarayıp yaramadığını anlamanın tek yolu **aynı**
soruları eğitimden sonra tekrar sormak. Sete bir soru eklersek "%70'ten
%75'e çıktı" cümlesi anlamsızlaşır — soru seti değişmiş olur.

O dosya donmuş kabul ediliyor.

### Ne yaptık

Ayrı bir dosya açtık: `router_ek_sorular.jsonl`, 18 yeni soru, elle yazıldı.

```
genel_stok_durumu   2 soru  ->  10 soru
gecelik_ozet        3 soru  ->  10 soru
onay_kuyrugu        5 soru  ->   8 soru
```

Ayrı koşuyor, ayrı raporlanıyor. Taban sayıya karışmıyor:

```bash
uv run python -m training.eval.router_taban --ek
```

Yeni soruların hiçbiri eğitim verisinde yok — kontrol edildi. Olsaydı model
cevabı ezberlemiş olabilirdi ve ölçüm şişerdi.

### İlk sonuç: model iki aracı birbirine karıştırıyor

Eğitilmemiş model 18 sorunun 13'ünü doğru bildi (%72,2). İlginç olan
**hataların şekli** — beşinin dördü aynı iki araç arasında ve **iki yönde
birden**:

```
"Bugün depoda genel tablo nedir?"     genel stok  ->  gecelik ozet   X
"Ben yokken sistem ne tespit etti?"   gecelik ozet ->  genel stok    X
```

Bir yönde olsa "model bu aracı seviyor" derdik. İki yönde olması şunu
söylüyor: **model bu iki aracı birbirinden ayıramıyor.** İkisi de kulağa
"bana durumu anlat" gibi geliyor. Aradaki fark zamansal — biri *şu anki*
durum, diğeri *gece boyunca olanlar* — ve model bu farkı görmüyor.

2 ve 3 soruyla bunu asla fark edemezdik. Eğitim bittiğinde bakacağımız ilk
yer burası olacak: model bu ayrımı öğrenebildi mi?

### Bir de yanlış alarm yakaladık

Sistemde "çöküş dedektörü" var: model bütün sorulara aynı cevabı vermeye
başlarsa uyarı basıyor. Eşik %40 — yani bir araç cevapların %40'ından
fazlasını alırsa alarm.

Ek seti ilk koşturduğumuzda **alarm çaldı.** Ama model çökmemişti.

Sebep: %40 eşiği 7 araçlı set düşünülerek konmuştu. 7 araç varsa her birine
düşen normal pay ~%14; %40 bunun neredeyse 3 katı, gerçekten anormal. Ama ek
sette sadece 3 araç var — orada normal pay zaten ~%33. Eşik normal davranışı
anormal sayıyordu.

Eşik artık sete göre hesaplanıyor:

```
7 araç  ->  %40    (değişmedi)
3 araç  ->  %83
```

Taban çizgi yeniden koşturuldu, sayı aynı çıktı: **%70,0**. Değişiklik eski
ölçümü bozmuyor.

### Düzeltmenin kendisi de bir kusur doğurdu

İlk yazdığımız formül bir testi kırdı. Testin hatası değildi, formülünkü.

Eşiği "araç sayısına böl" diye hesaplayınca, **tek araçlı** bir sette eşik
%250 çıkıyordu. Bir araç cevapların en fazla %100'ünü alabilir — yani o sette
alarm asla çalamaz. Dedektör var gibi görünüyor ama çalışmıyor.

Bu, yanlış alarmdan daha kötü: yanlış alarmı duyan gelip bakar, hiç çalmayan
alarmı kimse fark etmez.

Eşiğe üst sınır koyduk: en fazla %90. İki test yazıldı, biri eşiğin taban
sette değişmediğini, diğeri hiçbir sette %100'ü aşmadığını kontrol ediyor.

### Bir de: ölçümler birbirinin üstüne yazıyormuş

Ek seti test ederken yanlışlıkla olmayan bir modele soru sordum. Hepsi hata
verdi, sorun değil — ama o başarısız deneme **taban çizgi kaydımızı sildi.**

Sebep: bütün ölçümler tek bir dosyaya yazıyordu. Taban çizgi, ek set, 1. tur,
2. tur, hepsi `router_taban_sonuc.json`'a. Yani dosyada her zaman sadece en
son koşturduğumuz şey duruyordu.

Oysa o dosyanın amacı şuydu: "sonradan puanlamayı değiştirirsek modeli
tekrar çalıştırmayalım, kayıtlı cevaplara bakalım." Bu söz hiç tutulmuyormuş
ve kimse fark etmemiş.

Artık her ölçüm kendi dosyasına yazıyor:

```
taban cizgi   ->  router_taban_sonuc.json
3. tur        ->  router_sonuc_lora-tur3.json
3. tur ek set ->  router_sonuc_lora-tur3-ek.json
```

Taban çizgiyi tekrar ürettik, eski kayıtla birebir aynı çıktı — yalnızca
süreler farklı. Yani ölçüm gerçekten tekrarlanabilir.

Toplam **324 test yeşil**.

---

## Ölçmeden önce tahmin yazdık

Ek set, modelin iki aracı karıştırdığını göstermişti. Sıradaki soru: eğitim
bunu düzeltir mi?

3. tur hâlâ eğitilirken bu sorunun cevabına **veriye bakarak** yaklaşmak
mümkündü. Baktık ve tahminimizi ölçümden **önce** yazdık. Sebebi basit:
sonucu gördükten sonra "zaten böyle olacağını biliyorduk" demek çok kolay.
Önceden yazılan tahmin ya tutar ya tutmaz.

### Veride ne var

Önce iyi haber: model bu iki aracı ayırt edecek işareti bulabiliyor.

```
"genel"     -> genel stok sorularinin %69'unda,  gecelik'te HIC
"stok"      -> %42'sinde,                        gecelik'te HIC
"bugün"     -> genel stokta HIC,                 gecelik'in %24'unde
"özet"      -> %35                               %42     <- tek belirsiz kelime
```

Kötü haber, örnek sayıları:

```
genel_stok_durumu     26 ornek     (tum egitim verisinin %0,7'si)
gecelik_ozet         155 ornek
siparis_onerisi     1633 ornek
```

Üstelik o 26 örneğin 7'si aynı cümlenin nezaket çeşitlemesi:
*"Envanterin genel özetini gösterir/açıklar/paylaşır mısınız?"*

`gecelik_ozet`'te ise 155 örnekte 140 farklı cümle yapısı var — gerçek
çeşitlilik.

Yani ortak kelime olan "özet" geldiğinde model 155'e karşı 26 görüyor.

### Tahminimiz

1. **`gecelik_ozet` düzelecek** — bol ve çeşitli örneği var. 5/7'den 6-7/7'ye.
2. **`genel_stok_durumu` düzelmeyecek, kötüleşebilir** — 26 örnek yetmez.
   6/8'den aşağı.
3. **Karışma tek yönlü kalacak** — şu an iki yönlü. Eğitimden sonra sadece
   `genel_stok -> gecelik` yönü kalacak, çünkü hacim o tarafta.

Tahmin tutmazsa hipotezimiz yanlış demektir ve sorun sandığımız yerde değil.
O da öğrenilecek bir şey.

### Bir şeyi yapmadık: etiket değiştirmedik

Ek setteki 18 soruyu eğitim verisine karşı denetledik. Birinde çelişki çıktı:

> *"Bugün depoda genel tablo nedir?"* — biz `genel_stok_durumu` dedik. Ama
> "bugün" kelimesi eğitimde `gecelik_ozet`'e ait bir işaret.

Etiketi **değiştirmedik.** Çünkü anlamca haklıyız: "depoda genel tablo" stok
durumudur, oradaki "bugün" "şu an" demek. Soruyu dosyada "bilinçli zor vaka"
diye işaretledik, o kadar.

Modelin yanlış cevabına bakıp doğru cevabı değiştirmek, sınavı öğrenciye
uydurmaktır. O andan sonra sınav hiçbir şey ölçmez.
