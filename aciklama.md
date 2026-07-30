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

## Sırada ne var?

Faz 2 bitti. Sırada roadmap'e göre **Faz 3 — Eğitim verisi üretimi**
(`training/build_dataset.py`, `training/label_rationale.py`) var: kural
motorunun ürettiği kararları örnekleyip küçük LLM'in Türkçe konuşmayı
öğrenmesi için eğitim verisi hazırlamak.
