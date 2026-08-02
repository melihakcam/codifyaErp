# Açıklama — Ne Yapıyoruz, Basit Dille

> Bu dosya, projede yapılan her önemli adımın **sade Türkçe** özetidir. Kod
> detaylarını değil, "ne yaptık ve neden yaptık"ı anlatır. Her yeni adımda
> bu dosya güncellenir.

---

## Genel resim: ne inşa ediyoruz?

Codifya ERP'ye bir **yapay zekâ karar mekanizması** ekliyoruz. Amaç: stok
yönetiminde ("şu üründen ne zaman, ne kadar sipariş verilsin?") kararları
otomatikleştirmek. Ama küçük bir dil modeli (1B parametre, GPU'suz makinede
çalışacak) sayısal hesap yapamıyor — uydurma yapar. Bu yüzden mimari
**hibrit**:

- **Sayısal karar** → kural motoru + basit ML (Kişi A'nın işi)
- **Türkçe açıklama metni** → küçük LLM (Kişi B'nin işi)

İki kişi `app/contracts.py` adında dondurulmuş bir "sözleşme" üzerinden
anlaşıyor — Kişi A ürettiği veri tiplerini Kişi B tüketiyor, birbirlerini
beklemeden paralel çalışabiliyorlar.

---

## Faz 1 — Simülatör (TAMAMLANDI ✅)

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

---

## Faz 2 — Kural motoru (şu an buradayız 🔄)

Artık sahte dünyamız var, şimdi bu dünyaya bakıp **akıllı kararlar** üreten
kodu yazıyoruz.

### `features.py` (bitti ✅)

Ham simülasyon verisinden (talep geçmişi, stok seviyesi) her ürün için bir
"özet kart" (`StockFeatures`) çıkarıyor: ortalama günlük talep, talep
değişkenliği, stok durumu, tedarikçi bilgisi vs. 30 ve 90 günlük hareketli
ortalamalarla hesaplanıyor.

### `rules.py` (bitti ✅)

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

### `decide.py` (bitti ✅, ⭐ en kritik dosya)

Yukarıdakilerin **hepsini birleştiriyor**: bir ürün için özellikleri
çıkarır, kuralları çalıştırır, hangi kararı vereceğine karar verir (sipariş
ver / tasfiye et / bir şey yapma), ve bu kararın **güven skorunu**
hesaplar. Test edildi: gerçekten çalışıyor, mantıklı sonuçlar üretiyor
(örnek: bir ürün için "60 adet sipariş ver, T-0004 tedarikçisinden"
kararı + gerekçesi).

### `ml.py` (bitti ✅) — talep tahmini + anomali + oracle karşılaştırması

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

---

## Faz 2 durumu: TAMAMLANDI ✅

`features.py`, `rules.py`, `decide.py`, `ml.py` — hepsi yazıldı, test
edildi, gerçek veriyle doğrulandı. 25/25 test yeşil, lint temiz.

---

## Faz 3 — Eğitim verisi üretimi (devam ediyor 🔄)

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
Bunu `rules.py` doğrulamasında da görmüştük, burada tutarlı çıktı.

İlk denemede bir performans sorunu buldum: her hafta için tüm 2.19 milyon
satırlık talep tablosunun tamamını yeniden işliyordum (143 kez tekrarlanınca
çok yavaşladı). SKU alt kümesine göre önceden filtreleyince çalışma süresi
makul seviyeye indi (~2 dakika).

### `build_dataset.py` — A3.2 (bitti ✅) — router soru şablonları

Kişi B'nin router'ı (`app/llm/router.py`, `app/api/ask.py`) henüz Faz 2
B2.2-B2.3'te yazılacak (B1'i yeni bitirdi, sırası gelmedi) — yani gerçek bir
"araç listesi" henüz yok. Bu yüzden roadmap'teki tek somut ipucuna
("kritik seviyeye düşen ürün var mı?" örneği) ve mevcut API stub'larına
dayanarak **geçici ama makul** 7 araç tanımladım: kritik stok, ölü stok,
tedarikçi performansı, sipariş önerisi, onay kuyruğu, gecelik özet, genel
stok durumu. Kişi B gerçek router şemasını yazınca bu liste güncellenip
veri seti yeniden üretilecek.

Sonuç: **24.999 soru-araç çifti** (`data/egitim/router_sorulari.jsonl`),
4 stil çeşitliliğiyle (resmi/günlük/kısaltmalı/yazım hatalı).

Burada da bir hata bulup düzelttim: ilk denemede yalnızca **1.884** satır
çıktı (hedef ~30.000'in çok altında). Sebep: katalogdaki ürün isimleri
sınırlı sayıda şablon+marka kombinasyonundan üretiliyor, aynı isim onlarca
farklı üründe tekrarlanabiliyor — metin bazlı tekilleştirme (dedup) bu
tekrarların çoğunu eledi. Çözüm: soru metnine ürün adının yanına SKU
kodunu da eklemek (`"Portland Çimento 32.5 R - Çimsa (S-01636)"`) — hem
gerçekçi (bir ERP kullanıcısı ürünü kodla da belirtebilir) hem de
benzersizliği garanti ediyor. Düzeltme sonrası 24.999 satır elde edildi.

### A3.3 — büyük LLM ile soru başkalaştırma (askıya alındı ⏸️)

`training/paraphrase_colab.ipynb` yazıldı, Colab'da (T4 GPU, Qwen2.5-7B-Instruct
4-bit) sırayla çalıştırıldı. İki tasarım hatası bulunup düzeltildi:

1. **Performans:** İlk denemede 24.999 satırın HER BİRİ ayrı ayrı modele
   gönderiliyordu — 100 satır 357 sn sürdü, tüm veri seti ~25 saate karşılık
   geliyordu (Colab'ın ücretsiz oturum sınırı ~12 saat). Çözüm: yalnızca
   arkadaki **~84 benzersiz şablonu** (yer tutucu token'lı, ör.
   `KATEGORI_ADI`) başkalaştırıp, sonucu yerelde (GPU'suz) gerçek
   varlıklarla yeniden çoğaltmak — `sablonlari_ihrac_et()` +
   `parafraz_sablonlarindan_veri_uret()`. ~250x hızlanma, ~5 dakikaya indi.
2. **Prompt sızıntısı:** Talimat metnindeki "tire" kelimesini model
   çıktının bir parçası sanıp taklit ediyordu (her varyantın başına
   anlamsız "Tire " ekleniyordu). Kelime kaldırılıp güvenlik ağı (regex
   temizleme) eklendi.

**Ama asıl sorun çözülemedi:** Model bazı cümlelerde **anlamı tersine
çeviriyor** — "listesini görebilir miyim?" → "listeden kaldırılmasını
istiyorum" gibi. Örneklem testinde ~%40 oranında ciddi anlam kayması
görüldü. Bu, eğitim verisi için kabul edilemez (yanlış soru-araç eşleşmesi
öğretir). Qwen2.5-7B'nin Türkçe'de olumsuzluk/edilgen-gerekirlik
kalıplarını (`-mesi gereken`, `-meyecek`) güvenilir şekilde koruyamadığı
sonucuna vardık.

**Karar (o zamanki kullanıcıyla birlikte):** Adım geçici olarak **askıya
alındı** — elimizdeki 24.999 satırlık şablon×varlık verisi zaten LLM
üretmediği için %100 güvenilirdi, hiçbir sonraki adım buna bağımlı değildi.

### A3.3'e geri dönüş — A3.4'ün dersleriyle düzeltme (devam ediyor 🔄)

A3.4'te aynı sınıf bir hatayı (karar tipinin iş anlamını prompt'a hiç
yazmayınca modelin yönü karıştırması) prompt'a açık anlam açıklaması
ekleyerek çözmüştük. Aynı dersi buraya da uyguladık — o zaman not ettiğimiz
iki alternatifin ikisini birden `paraphrase_colab.ipynb`'e ekledik:

1. **Niyet-koruma kuralı + örnek:** `PROMPT_SABLONU`'na artık cümlenin bir
   SORU/BİLGİ TALEBİ olduğu, asla KOMUT'a çevrilmemesi gerektiği açıkça
   yazılıyor, bir doğru/yanlış örnek çifti eklendi.
2. **İkinci LLM ile doğrulama (guard deseni):** Yeni `anlam_korundu_mu()`
   fonksiyonu, üretilen her aday parafrazı aynı modele ikinci, kısa bir
   çağrıyla ("bu iki cümle aynı bilgiyi mi istiyor, evet/hayır?") sorup
   doğruluyor; "hayır" derse aday atılıyor. Bu, A3.4'teki
   guard/retry/fallback zincirinin birebir aynı fikri — üretilen içeriği
   üretenin kendisine tekrar sorup doğrulatmak.

`parafraz_uret()`'in raporlama satırına anlam/niyet reddedilme oranı da
eklendi, böylece bu oran da (A3.4'teki şablona düşme oranı gibi) izlenebilir.

**Gerçek Colab denemesi (Qwen2.5-7B, T4) beklenmedik derecede yüksek bir
red oranı verdi: %64.7 (143/221 aday).** Ama elle bakılan ilk 5 örnekte
kabul edilen varyantların çoğu aslında doğruydu — biri de İngilizce kelime
sızdırmış ("Acil sipariş **needed** ürünler var mı?") olduğu hâlde kabul
edilmişti. Bu tutarsızlık, reddedilenlerin çoğunun **gerçek anlam
kaymasından değil, doğrulayıcının kendi biçim hatasından** kaynaklandığına
işaret ediyor: `anlam_korundu_mu()`'ya yalnızca `max_new_tokens=5`
veriliyordu — 7B'lik sohbet modeli çoğu zaman doğrudan "EVET/HAYIR"
demeden önce birkaç kelime tereddütle başlıyor, 5 token bu girişi bitirmeden
kesiliyor ve kod bunu sessizce "HAYIR" sayıyordu.

**Düzeltmeler:**
1. `max_new_tokens` 5'ten 16'ya çıkarıldı, ayrıştırma "yalnızca `EVET` ile
   başlıyor mu" yerine "yanıtta `EVET` mi `HAYIR` mı önce geçiyor"a
   gevşetildi — modelin kısa bir giriş yapıp asıl cevaba geçmesine izin
   veriyor.
2. Ne `EVET` ne `HAYIR` net biçimde geçen (biçim hatası) yanıtlar artık
   **kabul edilecek şekilde** ele alınıyor (reddetmek yerine) — bu bir
   kalite süzgeci, A3.4'teki sayısal guard kadar sert bir güvenlik sınırı
   değil; format hatasını "hayır" saymak iyi içeriği yanlışlıkla eler.
3. Ayrı bir `belirsiz` sayacı eklendi — bu oran yüksek çıkarsa asıl sorunun
   üretilen içerikte değil, doğrulayıcının biçim takibinde olduğu
   doğrulanmış olur.
4. Fark edilen İngilizce sızıntısını doğrudan yakalamak için basit bir
   `LATIN_YABANCI_DESENI` (is/are/needed/list vb. sık İngilizce kelimeler)
   filtresi eklendi — CJK filtresi Latin alfabesiyle yazılan İngilizceyi
   zaten yakalayamıyordu.

**Colab'da yeniden deneme (düzeltilmiş notebook, gerçek çalıştırma):**
`BELİRSİZ %0` çıktı — yani doğrulayıcının format takibi artık sağlam, önceki
teori (kısa token limiti) doğrulanmış oldu. Kalan `%58.9` (119/202) red oranı
bu sefer **gerçek**: örneklere bakınca doğrulayıcının, "verilmesi **gereken**"
(gereklilik) ifadesini "verilecek" (kesinleşmiş gelecek zaman) yapan
varyantları doğru şekilde elediği görüldü — tam olarak yakalamaya
çalıştığımız kip/modalite kaymasının kendisi. Yani sistem tasarlandığı gibi
çalışıyor: yanlışı üretmektense üretmemeyi tercih ediyor.

**Sonuç:** 84 şablondan 61'i en az bir doğrulanmış parafraz aldı, 23'ü
güvenle orijinal (parafrazsız) haliyle kaldı (veri kaybı yok — cell 7'de
otomatik). `parafraz_sablonlarindan_veri_uret()` ile tam veri setine
uygulandı: **35.375 soru-araç çifti**, `data/egitim/router_sorulari_parafraz.jsonl`.
Araç dağılımı (`siparis_onerisi_sorgula` %96 ile baskın — 34.000/35.375)
orijinal A3.2 verisiyle (24.000/24.999, aynı oran) tutarlı: bu `sku_adi`
varlık türünün 2.000 SKU'luk kombinasyon havuzundan kaynaklanan, önceden var
olan bir özellik, parafraz adımının yarattığı bir bozukluk değil.

**A3.3 artık tamamlandı ✅** — askıya alınan adım, A3.4'ün derslerini
(prompt'a açık niyet/anlam açıklaması + ikinci-LLM doğrulaması) uyarlayarak
güvenli şekilde bitirildi.

### `label_rationale.py` — A3.4 (bitti ✅) — gerekçe etiketleme + guard doğrulaması

Amaç: `karar_noktalari.jsonl`'daki her kararı (özellikler + tetiklenen kurallar +
aksiyon) Türkçe, doğal bir gerekçe cümlesine çevirmek — büyük bir LLM'in yazdığı,
ama halüsinasyon içermediği garanti edilmiş bir cümle.

**Tasarım kararı — A3.3'ün dersini burada da uyguladım:** 50.050 satırın her
birini ayrı ayrı büyük modele göndermek A3.3'te 100 satırda 357 saniye tutmuştu
(tam veri seti ~25 saat). Burada aynı hataya düşmemek için şunu fark ettim:
`decide.py::ozellikten_karar_uret` her karar tipi için **sabit bir kural kodu
dizisi** üretiyor — yani 50.050 satır aslında yalnızca birkaç "ŞEKİL"in (karar
tipi + tetiklenen kural kodları) tekrarı. Büyük modele şekil başına birkaç kez
(yer tutucu token'lı, ör. `{SIPARIS_MIKTARI}`) sorulup birkaç cümle varyantı
istendi; gerçek sayılar bu varyantlara yerelde, GPU'suz basıldı. Elli bin değil,
onlarca LLM çağrısı. Daha önce görülmemiş bir şekle (yeni bir kural kodu vb.)
düşen satırlar için tek-satır yolu (yavaş ama doğru) yedek olarak duruyor.

**Guard'la ilgili bir not:** `app/llm/guard.py` (Kişi B, Faz 2 B2.5) henüz yer
tutucu — yazılmadı. A3.4'ün veri üretmesi guard'ın var olmasını bekleyemeyeceği
için, `label_rationale.py` kendi sayı-doğrulama eşleniğini taşıyor
(`_metni_dogrula`) — `DecisionCandidate.izinli_sayilar()` ile aynı kaynağı
kullanan, üründeki gerçek guard yazılınca hizalanması gereken bağımsız bir
kopya. Kişi B'nin `app/llm/` alanına dokunmadım (sözleşme gereği).

Doğrulama zinciri: şekil varyantı doldurulur → sayılar `izinli_sayilar` ile
karşılaştırılır (ürün/tedarikçi adındaki rakamlar önce maskelenir, ör.
"Tuğla 19x9x5" içindeki 19/9/5 uydurma sayı sanılmasın diye) → geçerse
`GECTI`/`YENIDEN_URETILDI`, aynı şeklin tüm varyantları başarısız olursa
`app/llm/explain.py::sablon_gerekce()`'ye (Kişi B'nin zaten yazdığı
deterministik şablon) düşülür — `SABLONA_DUSTU`. Şablona düşme oranı %15'i
geçerse (görev tanımındaki eşik) script uyarı basıyor.

9 birim testi eklendi (Türkçe sayı ayrıştırma, uydurma sayı reddi, ürün adı
rakam karışıklığı, şekil/slot çıkarımı, şablon doldurma round-trip, Ollama'ya
erişilemediğinde güvenli şablon geri dönüşü) — hepsi ağa çıkmadan çalışıyor.
34/34 test yeşil (25 eskisi + 9 yenisi), lint temiz.

**Gerçek modelle duman testi (8 satır, `llama3.2:1b`) bir hata daha buldu:**
Zayıf model, "cümlede aynen şu yer tutucular geçmeli: {TOKEN}..." talimatını
kendi cevabıymış gibi aynen geri döndürdü — ve bu, yalnızca "yer tutucu
token'ları metinde var mı?" diye bakan ilk kontrolden (yanlışlıkla) geçti,
çünkü talimat cümlesinin kendisi de token'ları içeriyor. Düzeltme:
`_YANKI_IFADELERI` — "yer tutucu", "harfi harfine", "aynen", "format" gibi
talimat kelimelerini içeren satırları baştan eleyen bir kara liste. Aynı
duman testinde ayrıca Windows konsolunun (cp1254 kod sayfası) Türkçe
karakterlerde `UnicodeEncodeError` fırlattığı görüldü — `sys.stdout.reconfigure`
ile düzeltildi. Düzeltme sonrası `llama3.2:1b` ile 8 satırın **tamamı**
güvenle şablona düşüyor (beklenen: bu model "büyük LLM" değil, sistemin
zayıf modelde bile veri kirletmediğini doğruladık).

**RAM yetmiyorsa Colab yolu eklendi:** `qwen2.5:7b-instruct` yerel makineye
(16 GB RAM, GPU'suz) sığmayabilir. Şekil-bazlı tasarım tam olarak bunu
çözmeye uygun olduğu için (gerçek veride yalnızca **3 benzersiz şekil**
bulundu — tasarım varsayımı doğrulandı), A3.3'teki `paraphrase_colab.ipynb`
deseni burada da uygulandı:

1. Yerelde `--sekil-ihrac-et` ile birkaç satırlık bir prompt dosyası çıkarılır
   (`sekil_promptlarini_ihrac_et`).
2. `training/label_rationale_colab.ipynb` (Colab, T4 GPU, Qwen2.5-7B-Instruct
   4-bit) bu dosyayı işleyip `sekil_varyantlari.jsonl` üretir.
3. Yerelde, **GPU'suz**, `--varyant-girdi` ile tam veri seti işlenir — Ollama'ya
   hiç ihtiyaç kalmaz; havuzda olmayan şekiller (varsa) yine güvenle şablona
   düşer.

4 yeni test eklendi (şekil id round-trip, prompt ihracı, önceden üretilmiş
varyantla Ollama'nın hiç çağrılmadığının doğrulanması). Bu arada test
verisinde bir kopyala-yapıştır hatası bulundu: elle yazılan örnek varyant
metninde `{TEDARIK_SURESI_GUN}` yer tutucusu unutulmuştu — gerçek koddaki bir
hata değil, testin kendisindeki bir eksiklikti, düzeltildi. 37/37 test yeşil.

**Gerçek Qwen2.5-7B-Instruct (Colab, T4) ile ilk deneme 3 gerçek sorun buldu:**

1. **Anlam tersine dönüyor:** `stok.aksiyon_yok` şekli için model "stok
   yeterli, aksiyon gerekmiyor" yerine sanki stok yetersizmiş gibi cümleler
   kurdu. Sebep: prompt yalnızca `karar_tipi` kodunu (`stok.aksiyon_yok`)
   veriyordu, kodun iş anlamını hiç açıklamıyordu.
2. **Zorunlu yer tutucular atlanıyor:** `stok.tasfiye` şeklinde 5 yer
   tutucudan 2'si (`ISKONTO_YUZDE`, `BAGLI_SERMAYE_TL`), `stok.siparis`
   şeklinde 7'den 3'ü (`SIPARIS_MIKTARI`, `TEDARIKCI_ADI`, `TEDARIKCI_SKORU`)
   varyantların HİÇBİRİNDE geçmedi — guard'ın "tüm token'lar var mı"
   kontrolünden tamamı elenecekti.
3. **Çince metin sızıntısı:** `stok.siparis` varyantlarının çoğu Türkçe
   cümlenin ortasına Çince karakter karıştırdı (`送货周期下，现有库存不足`
   gibi) — Qwen2.5 ailesinde A3.3'te de görülmüş, bilinen bir sorun; bu
   notebook'ta o zamanki CJK filtresini eklemeyi unutmuşum.

**Düzeltmeler:** `_sekil_prompt_olustur` artık her karar tipinin iş anlamını
(`KARAR_TIPI_ACIKLAMASI`) ve her yer tutucunun ne temsil ettiğini
(`SLOT_ACIKLAMALARI`, ör. "SON_HAREKET_GUN_ONCE bir TARİH DEĞİL, bir gün
SAYISI") açıkça yazıyor, "hiçbirini atlama" vurgusu güçlendirildi. `_CJK_DESENI`
regex'i ile Çince/Korece/Japonca karakter içeren varyantlar otomatik eleniyor
(A3.3'teki aynı desen). `data/egitim/sekil_promptlari.jsonl` yeni prompt'la
yeniden çıkarıldı — Colab'da yalnızca üretim hücresi (model tekrar
yüklenmeden) yeniden çalıştırılacak.

**Düzeltilmiş prompt'la Colab'da (Qwen2.5-7B-Instruct, T4) yeniden üretim
denendi.** Bu sefer üç şeklin de tüm yer tutucuları eksiksiz, anlam doğru
yönde, Çince sızıntısı yok. Ama tam veri setine ilk uygulamada `stok.siparis`
şeklinin (7 yer tutucu) tamamı (3.838 satır) şablona düştü — ilginç bir bulgu:
sabit 300 karakterlik bir uzunluk sınırım vardı (talimat yankısı gibi saçma
uzun metinleri elemek için), ama 7 yer tutuculu doğru bir cümlenin doğal
uzunluğu (338-362 karakter) bu sınırı aşıyordu — 3 geçerli varyantın hepsi
yanlışlıkla elendi. Düzeltme: uzunluk sınırı artık yer tutucu SAYISINA göre
ölçekleniyor (`_UZUNLUK_TABANI` + `_TOKEN_BASINA_UZUNLUK_PAYI × token_sayisi`).

**Sonuç — tam 50.050 satırlık koşu tamamlandı:** `data/egitim/gerekceler.jsonl`
yazıldı, **guard geçme oranı %100** (0 şablona düşme). Karar tipi dağılımı
A3.1'in raporladığıyla neredeyse birebir örtüşüyor (%67,2 aksiyon_yok / %25,1
tasfiye / %7,7 sipariş vs. A3.1'in %67/%25/%8'i) — tutarlılık kontrolü geçti.
6,7 saniyede tamamlandı (tamamı yerel, ağ çağrısı yok — yalnızca 3 Colab
çağrısının sonucu 50.050 satıra yerelde uygulandı).

---

## Faz 3 durumu

- ✅ A3.1 — karar noktası örnekleme (50.050 nokta)
- ✅ A3.2 — router soru şablonları (24.999 çift, geçici araç listesiyle)
- ✅ A3.3 — büyük LLM ile soru başkalaştırma (ilk deneme askıya alınmıştı, A3.4'ün
  dersleriyle düzeltildi, 35.375 satır — `data/egitim/router_sorulari_parafraz.jsonl`)
- ✅ A3.4 — `label_rationale.py`: 50.050 satırın tamamı için gerekçe üretildi
  (Qwen2.5-7B-Instruct, Colab), guard geçme oranı %100, `data/egitim/gerekceler.jsonl`
- ⬜ A3.5 — train/val/test bölme + golden set (Kişi B ile birlikte)

---

## Faz 4-5 — Genellenebilirlik testi + para metriği (Kişi B'den bağımsız, tamamlandı ✅)

A3.5 Kişi B'yi beklediği için, ona hiç bağımlı olmayan Faz 4-5 işlerine
geçildi (`simulator/`, `app/domain/stock/`, `training/` — hiçbiri
`app/llm/`, `app/api/`, `app/core/` içe aktarmıyor, doğrulandı).

### `simulator/company.py` — A4.2 için 2 yeni şirket profili

`kucuk_nalbur_dukkani()` (~250 SKU, dar kategori, zayıf sezonsallık) ve
`buyuk_insaat_deposu()` (~5.000 SKU, yalnızca kaba yapı kategorileri, güçlü
sezonsallık) eklendi — varsayılan ~2.000 SKU'luk profilin yanına, ölçek ve
karma bakımından belirgin şekilde farklı iki uç nokta.

### `app/domain/stock/ml.py` — A4.4: `maliyet_raporu_uret()`

`politika_karsilastirmasi_calistir`'den farklı olarak kendi simülasyon
döngüsünü çalıştırmaz — `simulator.run.simulasyon_calistir()`'in **gerçek**
`envanter_gunluk` + `karsilanamayan_talep` tablolarını doğrudan işler, yani
herhangi bir koşuya (sağlıklı, patolojili, farklı seed/profil) uygulanabilir.
6 birim testiyle (sentetik veri, elle hesaplanmış beklenen değerler) doğrulandı.

### `training/genellenebilirlik_ve_para_metrigi.py` — A4.2 + Faz 5

**A4.2 sonucu:** 3 profil × 3 seed = 9 kombinasyonun **tamamında** kural
motoru vasat politikadan hem daha düşük stok tükenme oranı hem daha düşük
toplam maliyet üretti. İyileşme oranı ölçekle birlikte büyüyor: küçük
dükkânda %1,4-3,2, varsayılan profilde %15-19, büyük depoda %39-45. Bu
mantıklı — büyük ölçekte vasat politikanın "10 gün eşik / 30 gün hedef"
kaba kuralı çok daha fazla parayı yanlış yere koyuyor, kural motorunun
ABC/XYZ'ye duyarlı ROP/EOQ'su farkı büyütüyor.

**Test sırasında ilginç bir bulgu:** `kucuk_nalbur_dukkani` + seed=2026'da
oracle'ın HAM stok tükenme SAYISI (ama maliyeti değil) baseline'lardan
yüksek çıktı. Kök neden: bu profilde ortalama tedarik süresi kısa (2-6 gün)
olduğu için oracle çok daha sık (3049 sipariş/3 yıl, baseline'larda
~700-1100) küçük miktarlarla sipariş veriyor; her sipariş döngüsünde
tedarik süresi belirsizliğinin sabit 3-sigma tamponunu aşma olasılığına
(~%0,13) yeniden maruz kalıyor — bu kadar sık tekrarda en az bir "kötü
şans" çekme olasılığı neredeyse kesinleşiyor (1-(1-p)^3049 ≈ %98). Kod
hatası değil, oracle'ın sabit-tampon tasarımının küçük ölçek/kısa tedarik
süresinde ortaya çıkan bilinen bir sınırlaması — script bunu sessizce
gizlemek yerine ayrı bir bölümde açıkça gösteriyor.

**Faz 5 — projenin can alıcı sonucu:** Eğitim verisi üretiminde (A3.1
seed=42/7/11, A2.8 seed=42) hiç kullanılmamış taze bir seed'le
(`FAZ5_HELD_OUT_SEED=20250801`), varsayılan profilde, 3 yıllık tutulmamış
bir koşu:

| Politika | Stok tükenme | Kayıp kâr | Aşırı stok maliyeti | Sipariş maliyeti | Toplam maliyet |
|---|---|---|---|---|---|
| vasat | %5,31 | 7,69M TL | 9,41M TL | 1,72M TL | **18,82M TL** |
| kural motoru | %0,47 | 3,82M TL | 12,41M TL | 1,16M TL | **17,40M TL** |
| oracle | ~%0 | 0,20M TL | 8,70M TL | 6,00M TL | **14,90M TL** |

**Kural motoru toplam maliyeti %7,6 düşürdü, stok tükenme oranını %5,31'den
%0,47'ye indirdi** — A2.8'in ilk (farklı seed'li) ölçümüyle (%14,6
iyileşme) aynı yönde ama farklı büyüklükte, bu da beklenen bir seed-bazlı
varyasyon (tutulmamış bir koşu olduğu için A2.8 ile birebir aynı çıkması
zaten beklenmezdi — önemli olan yön ve tutarlılık, ikisi de sağlandı).

İki nokta dikkat çekici ve bilinçli olarak raporlanıyor:
1. Kural motorunun **aşırı stok maliyeti vasat'tan yüksek** (12,41M vs
   9,41M) — bu bir hata değil, kasıtlı bir değiş tokuş: ABC/XYZ'ye göre
   önemli/düzenli ürünlere yüksek servis seviyesi (%99'a kadar) hedeflemek
   daha fazla emniyet stoğu demek. Karşılığında kayıp kâr (3,82M vs 7,69M)
   ve sipariş maliyeti (1,16M vs 1,72M) ciddi düşüyor — net etki yine de
   lehine.
2. Oracle'ın sipariş maliyeti (6,00M) baseline'ların ikisinden de yüksek —
   40.021 sipariş (günde SKU başına neredeyse "tam zamanında" sipariş)
   verdiği için. Mükemmel bilgiyle stok tutma maliyetini de en aza indirmek
   mümkün ama bunun bedeli çok sık, küçük siparişler — teoriyle tam uyumlu.

---

## Ekip senkronizasyonu

Kişi B kendi tarafında **Faz 1 B1.1-B1.6**'yı bitirdi ve `faz1-servis`
branch'ini push etti: SQLAlchemy/Alembic veri katmanı, denetim kaydı,
policy eşik tablosu, onay kuyruğu API'leri, GitHub Actions CI. Kendi
`aciklama.md`'sini de yazmış — ikimizin dosyaları merge'de çakışacak,
o zaman birlikte birleştirilecek.

`app/api/decisions.py` hâlâ `decide_stub()` çağırıyor — benim
`stok_karari_uret()`'e geçiş henüz yapılmadı, sırası gelince Kişi B
tek satırlık değişikliği yapacak (sözleşme tam olarak bunun için var).

**Kişi B'den gelen sözleşme kusuru düzeltildi:** `izinli_sayilar()`
içindeki `×100` kuralı, bir sayının 0-1 aralığında olup olmadığına bakarak
karar veriyordu — değerine göre, alan adına göre değil. Bu yüzden
`son_hareket_gun_once` gibi bir adet/gün alanı 1 değerini aldığında "%100"
sayısı yanlışlıkla gerekçede kullanılabilir hale geliyordu (2.000 SKU'lu
katalogda dün hareket görmüş her ürün bu durumdaydı). Düzeltme: `ORAN_ALANLARI`
adlı açık bir liste eklendi, ×100 karşılığı yalnızca gerçek oran alanları için
üretiliyor artık. Ayrı bir `fix-izinli-sayilar-oran-alanlari` branch'ine
push edildi (bu dosya ortak/dondurulmuş olduğu için).

**Kişi B'nin SP1 incelemesinde flag'lediği 3 açık `StockFeatures` konusu
kesinleştirildi** (`app/domain/stock/features.py`, Kişi A tarafında karara
bağlandı, B'ye danışmaya gerek kalmadı):

1. **`tedarikci_onayli`** — zaten `decide.py`'nin gerçek `tedarikci_skoru_hesapla()`
   (A2.5) çıktısını kullandığı doğrulandı; `TEDARIKCI_ONAY_ESIGI = 70.0`
   eşiği gerçek veriyle test edildi: sağlıklı (patolojisiz) koşuda 60
   tedarikçinin skoru 89,6-93,2 arasında (hiçbiri eşiğin altına düşmüyor),
   tedarikçi gecikmesi patolojisi enjekte edilince en kötüler 42-52'ye
   düşüyor. Eşik doğru yerde duruyor — ama **mevcut A3.1 eğitim verisi
   patolojisiz üretildiği için `tedarikci_onayli=False` durumu training
   setinde hiç görülmüyor.** Bu bir hata değil, bilinen bir kapsam
   sınırlaması olarak dokümante edildi (A2.8'deki demand-spike
   sınırlamasıyla aynı kategoride) — ileride istenirse A3.1 patolojili bir
   koşuyla genişletilebilir, ama şimdilik kapsam dışı bırakıldı.
2. **`raf_omru_kalan_gun`** — simülatör parti/lot bazlı yaşlandırma
   tutmadığı için kategori tipik raf ömrü kullanılıyor; ölü stok tespiti
   asıl sinyali gerçek `son_hareket_gun_once`'tan aldığı için bu basit
   kalması işlevsel bir sorun yaratmıyor. Nihai karar: değişmeyecek.
3. **`rezerve_stok`** — simülatörün olay döngüsü aynı gün sevkiyat yaptığı
   için yapısal olarak hep 0; ayrı bir rezervasyon kuyruğu eklemek mevcut
   simülatörün kapsamının dışında. Nihai karar: değişmeyecek.
