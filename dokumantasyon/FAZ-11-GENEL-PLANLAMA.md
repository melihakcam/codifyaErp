# Faz 11 — Genel planlama motoru

> Onaylandı 2026-08-11, **tamamlandı 2026-08-12**.

## ✅ Sonuç

`app/planlama/` kuruldu; üretim çizelgesi onun adaptörüne dönüştü.

**Genellik iki şeyle kanıtlandı:**

1. Üretim motora taşındıktan sonra **mevcut 9 çizelge testi değiştirilmeden
   geçti** — davranış kaymadı.
2. İkinci alan **tek satır kod yazılmadan** eklendi (`ornekler/nakliye.json`).
   Motor araçları kendi dağıttı, uygunluk kısıtına uydu, bölünemez işi güne
   yaymadı. Bir test iki alanın da `plan_kur` çağırdığını doğruluyor —
   çağırmazsa "genel" iddiası düşer.

**Üç plan + parayla öneri** (gerçek üretim verisi, rapor çıktısından):

```
                  "en acil önce"  "en çok iş bitir"  "en değerli önce"
yerlesen is             92              95                 94
ufka sigmayan            7               4                  5
karsilanamayan    28.258 TL       16.642 TL           3.854 TL
· stoksuzluk      70.645 TL       41.604 TL           9.634 TL
· elde tutma       8.863 TL        6.988 TL           9.297 TL
· kurulum         23.000 TL       23.750 TL          23.500 TL
BEKLENEN MALIYET 102.509 TL       72.342 TL          42.431 TL

-> "en degerli once" onerildi: 29.912 TL dusuk.
```

**Testin yakaladığı iki gerçek hata:** sıralamada rastgele UUID (aynı girdi
farklı plan üretiyordu; kapasite modülünde de vardı) ve doluluk hesabının
ufku saymaması (%535 çıkıyordu).

⚠️ `ornekler/nakliye.json` **ürün özelliği değil, test verisi**. Adları
bilinçli olarak soyut; gerçek bir işletme temsil etmiyor.

---


## Context

Projenin amacı alan-özel çözümler değil, **genel bir karar mekanizması**.
Kural motoru bu sınavı bir kez geçti: aynı iskelet (özellik → kural → aday →
politika) stok, finans ve üretime yeniden yazılmadan taşındı.

Planlama tarafında aynı sınav verilmedi. Bugün çizelge
`app/domain/production/cizelge.py` içinde ve "hat", "emir", "parti"
kelimeleriyle konuşuyor — ikinci bir alan geldiğinde kopyalanması gerekir.

Melih'in istediği (2026-08-11): alan tarif edilince sistem plan çıkarsın;
"şu araç şuraya gidebilir" gibi. Nakliye bugün ürün kapsamında değil, ama
motorun onu da kaldırabilmesi bekleniyor.

**Bu turda hedeflenen sonuç:** aynı planlama motoru hem üretimi hem nakliyeyi
koşuyor, birkaç alternatif plan üretiyor, aralarındaki farkı parayla
gösteriyor ve birini gerekçeli öneriyor.

### Bu oturumda zaten yapılmış olanlar

- `.env` → `AUTONOMY_LEVEL=advisory` (otonomi yolu: şimdi öneri → sonra
  eşikli → giderek tam otomatik)
- Hafızaya iki not: genel karar mekanizması hedefi, otonomi yolu
- `app/planlama/__init__.py` + `contracts.py` **taslak yazıldı, commit
  edilmedi** — sözleşme dondurma adımında gözden geçirilecek

---

## İş bölümü — iki kişi, birbirini beklemeden

Bugün aynı iş **iki kez** paralel yapıldı ve birleştirmek zaman aldı.
Sahiplik tablosu tam bunu önlemek için var ve bu turda baştan kuruluyor.

### Adım 0 — ORTAK, yarım gün: sözleşmeyi dondur

`app/planlama/contracts.py` ikisi birlikte onaylanır ve **dondurulur**:
`Kaynak`, `Is`, `PlanSatiri`, `KaynakPlani`.

Bu adım bitmeden ikisi de kod yazmaz. Bittikten sonra **kimse kimseyi
beklemez** — Faz 10'da `TalepTahmini` ile aynı yöntem, orada işe yaradı.

⚠️ Sözleşmede hiçbir alan adı iş alanına ait olmayacak. `hat_id` /
`arac_plakasi` eklendiği gün motor genel olmaktan çıkar. Alan kimliği
`etiketler` sözlüğünde taşınır, motor ona **bakmaz**.

### Sahiplik tablosu

| Kişi A — Motor & Alan | Kişi B — Değerlendirme & Servis |
|---|---|
| `app/planlama/yerlestirme.py` | `app/planlama/maliyet.py` |
| `app/planlama/olcut.py` | `app/planlama/karsilastir.py` |
| `app/planlama/tanim.py` | `app/api/decisions.py` — plan uçları |
| `app/domain/production/cizelge.py` — adaptör | `app/core/isletme_profili.py` — maliyet parametreleri |
| `ornekler/nakliye.json` + kanıt testi | `app/llm/explain.py` — plan özeti metni |

### ⚠️ Bağımsızlık nasıl korunuyor

B'nin işlerinin **hiçbiri `plan_kur()` çağırmıyor.** Maliyet hesabı, karne ve
öneri girdi olarak `KaynakPlani` alıyor — yani donmuş sözleşmenin kendisini.
B testlerini elle kurduğu plan nesneleriyle yazar; motor hiç koşmaz.

Motor ile değerlendirme yalnızca **en sonda**, API ucunda buluşuyor ve o uç
B'nin sahasında, tek satırlık bir çağrı.

Aynı disiplin Faz 10'da uygulandı: B tahmin çekirdeğini yazarken A üretim
kuralını yazdı, ikisi `TalepTahmini` dışında hiç temas etmedi.

---

## Kişi A — Motor & Alan

### A11.1 · `yerlestirme.py` — genel yerleştirme

`plan_kur(isler, kaynaklar, olcut, ufuk_gun, baslangic) -> list[KaynakPlani]`

Açgözlü: ölçüte göre sırala, sırayla yerleştir, kaynak dolunca ertesi güne.

- `Is.kaynak_id` boşsa `uygun_kaynaklar` içinden **en boş olana** ata.
  ⚠️ Bu alan sözleşmeye eklenecek: üretimde kalem zaten bir hatta bağlı,
  ama nakliyede "hangi araç" sorusunun kendisi karar. Atama desteği olmadan
  nakliye örneği sahte olur.
- `bolunebilir=False` iş bir güne sığmıyorsa **hiç yerleştirilmez** —
  fırın bir kez yakılır, kamyon yolun yarısında durmaz.
- Ufka sığmayan iş `sigmayanlar`'a düşer, sessizce kaybolmaz.

⚠️ Sıralamada eşitlik **`is_id` ile** kırılacak. Bugün `cizelge.py` ve
`kapasite.py`'de aynı hata bir kez yapıldı (`karar_id` rastgele UUID) ve
aynı girdi iki farklı plan üretiyordu; testi yakaladı.

⚠️ Optimize edici değil, dosyada yazılı olacak. Gerçek çözücüye
(OR-Tools/CP-SAT) geçilirse bu dosya değişir, sözleşme değişmez.

**Bitti sayılır:** aynı girdi iki koşuda bit bit aynı plan; atama, bölünemez
iş ve ufuk taşması testli.

### A11.2 · `olcut.py` — "iyi plan" tanımları

Öncelik ölçütleri kayıt defteri; her ölçüt bir `Is` → sayı fonksiyonu
(küçük = önce):

- `en_acil` — kaynak biteceği güne kalan süre (üretimde bugünkü davranış)
- `en_cok_is` — küçük iş önce, ufka en çok iş sığsın
- `en_degerli` — tutarı büyük olan önce

Yeni ölçüt eklemek = bu sözlüğe bir satır.

**Bitti sayılır:** ölçüt değişince planın sırası değişiyor, testi var.

### A11.3 · `tanim.py` — alan tanımı okuyucu

JSON/dict → `Kaynak` + `Is` listesi. "Yeni alan = bir dosya, kod yok"
iddiasının taşıyıcısı.

⚠️ Eksik/yanlış alan **yükleme anında** patlayacak — `IsletmeProfili.dosyadan`
ile aynı disiplin: yazım hatası sessizce varsayılana düşmemeli.

### A11.4 · Üretimi motora taşı

`app/domain/production/cizelge.py` ince adaptöre dönüşür: `uretim.emir_ac`
kararları → `Is`, hat → `Kaynak`, öncelik → `kapsama_gun`.

`kapasite.py`'deki `kapsama_gun` ortak kalır — kapasite "en az acili ertele",
çizelge "en acili öne al" diyor; iki ayrı öncelik tanımı sistemi kendi içinde
çelişkiye sokar.

**Bitti sayılır (kanıt ölçütü):** `tests/test_uretim.py`'deki mevcut 9
çizelge testi **değiştirilmeden** yeşil. Değiştirmek gerekiyorsa davranış
kaymış demektir.

### A11.5 · Nakliye — genelliğin asıl kanıtı

`ornekler/nakliye.json`: araçlar (kapasite: saat), sevkiyatlar (yük: süre,
öncelik: teslime kalan gün), bazı sevkiyatlar birden çok araca uygun.

**Tek satır alan kodu yazılmayacak.** Test JSON'u yükleyip `plan_kur`
çağıracak ve üretimle **aynı fonksiyonu** kullandığını doğrulayacak.

⚠️ Nakliye ürün kapsamında değil: karar tipi, `app/contracts.py`
değişikliği, API ucu **yok**. Yalnızca motorun genelliğini kanıtlayan örnek.

**Bitti sayılır:** JSON'dan plan çıkıyor ve testte üretimle aynı fonksiyonun
çağrıldığı doğrulanıyor. Çağrılmıyorsa "genel" iddiası düşer.

---

## Kişi B — Değerlendirme & Servis

### B11.1 · `maliyet.py` — planın beklenen maliyeti

`plan_maliyeti(plan: KaynakPlani, ...) -> MaliyetKirilimi`

Girdi donmuş sözleşme; motor çağrılmıyor, testler elle kurulan planlarla
yazılıyor.

Bileşenler profilde **zaten tanımlı** (`app/core/isletme_profili.py::StokProfili`):
`stoktukenmesi_ceza_carpani` (2,5), `yillik_elde_tutma_orani` (0,25),
`siparis_maliyeti_tl` (250).

⚠️ Maliyet bir **tahmin**. Varsayımları çıktının yanında yazılı olacak ve
tek bir sayıya indirgenip tablo gizlenmeyecek — bu projede beş kez yaşanan
"sayı tek başına yalan söyler" hatasının tekrarı olurdu.

**Bitti sayılır:** iki elle kurulmuş plan için maliyet farkı elle
doğrulanabiliyor; kırılım (stoksuzluk / elde tutma / kurulum) ayrı ayrı
görünüyor.

### B11.2 · `karsilastir.py` — karne ve gerekçeli öneri

```
                      PLAN A            PLAN B             PLAN C
                   "en acil önce"   "en çok iş bitir"  "en değerli önce"
yetişen iş            41                 47                 38
ufka sığmayan          8                  2                 11
karşılanamayan talep   0 kalem            3 kalem            5 kalem
kaynak doluluğu      %87                %94                %81
beklenen maliyet   180.000 TL         240.000 TL         310.000 TL
```

Önerilen plan **parayla** işaretlenir, "bence" ile değil:

> "B'yi öneriyorum: beklenen toplam maliyeti A'dan 90.000 TL düşük."

⚠️ Tablo **daima** basılacak; öneri onu gizlemeyecek.

⚠️ Öğrenen öneri (seçilmişi hatırlayıp ona göre önerme) **kapsam dışı**:
geçmiş veri yok ve "ne öğrendiği" açıklanamaz hâle gelir — projenin tüm
mantığına ters.

**Bitti sayılır:** üç plandan en düşük maliyetli işaretleniyor; eşitlikte
kararlı davranıyor; tablo öneriyle birlikte basılıyor.

### B11.3 · Servis uçları

- `GET /v1/decisions/production/schedule?olcut=en_acil` — mevcut uca ölçüt
  parametresi (varsayılan `en_acil` = bugünkü davranış, kırılma yok)
- `GET /v1/decisions/production/schedule/compare` — üç plan + karne +
  önerilen plan

⚠️ İkisi de `GET` ve DB'ye yazmıyor: çizelge karar değil, kararların
görünümü. Bu sınırı bugün bir test koruyor (`cizelge` kaynağında
`DecisionCandidate(` geçerse test kırılıyor) ve genel motorda da korunacak.

### B11.4 · Plan özeti metni

`explain.py`'ye plan karşılaştırmasının Türkçe özeti.

⚠️ Faz 8'in dersi: yeni bir tip `_TIPE_GORE_ALANLAR`'a girmezse
`sayi_etiketleri` boş döner, model **hiç çağrılmaz** ve her metin sessizce
şablona düşer. Önce test, sonra kod.

---

## Doğrulama

1. `uv run pytest` — mevcut 9 çizelge testi **değiştirilmeden** geçmeli
2. Yeni testler: atama, bölünemez iş, ölçüt değişince planın değişmesi,
   tekrarlanabilirlik (planlar **yeniden üretilerek** karşılaştırılacak),
   JSON tanımından plan, maliyet kırılımı
3. `ornekler/nakliye.json` üretimle aynı fonksiyonu çağırıyor
4. Gerçek veride karşılaştırma koşusu: 99 emir, üç ölçüt; karne tablosu
   `aciklama.md`'ye **olduğu gibi** yapıştırılacak (elle özetlenmeyecek —
   bugün yazıya geçen üç tablo yeniden üretilemedi)
5. `uv run ruff check .`

---

## Riskler

| risk | karşılığı |
|---|---|
| Üretim davranışı taşınırken kayar | Mevcut testler değiştirilmeden geçmeli; geçmezse taşıma yanlış |
| Maliyet uydurma varsayımlara dayanır | Varsayımlar çıktının yanında; tablo daima basılıyor |
| "Genel" motor tek kullanıcılı kalır | Nakliye örneği aynı fonksiyonu çağırmazsa iddia düşer — testle bağlanacak |
| İki kişi yine çakışır | Sözleşme Adım 0'da donuyor; sahiplik tablosu dosya bazında ayrık |
| Kapsam büyür | Genel arayüz (router) bu turda **yok** |

## Kapsam dışı (bilinçli)

- Genel arayüz / router'a yeni araçlar — sıradaki tur
- Gerçek çözücü (OR-Tools), rota optimizasyonu, mesafe matrisi
- Nakliye için karar tipi, API ucu, ekran
- Öğrenen öneri
