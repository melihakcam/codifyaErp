# Faz 10 — Üretim Planlama (ortak plan)

> Yazan: **Kişi B**, 2026-08-11. Kişi A'nın onayı bekleniyor.
> Adım 1 ve 2 **yapıldı ve itildi** (`3ba8f5b`); geri kalanı teklif.

---

## Neden

Sistem bugün **geçmişe bakıp bugüne** karar veriyor: `ort_gunluk_talep` tek
bir ortalama, ufuk yok. Üretim planı ise "gelecek N günde ne kadar satacağız"
sorusuna dayanır ve o cevap sistemde **hiç yoktu**.

Üç şey lehimizeydi:

| | |
|---|---|
| `Alan.URETIM` | sözleşmede **zaten tanımlı**, hiç kullanılmamış |
| talep simülatörü | trend × sezon × haftalık desen × promo × gürültü — tahmin edilecek gerçek yapı var |
| işletme profili (Faz 9) | "yeni müşteri = yeni JSON, kod dağıtımı yok" mekanizması hazır |

İstenen üç karar türü de (üretim emri, kapasite, MRP) aynı şeye dayanıyor.
Ölçülmemiş bir tahminin üstüne üç katman kurmak, bu projede beş kez yaşanan
**"sayı tek başına yalan söyler"** hatasının en pahalı hâli olurdu. O yüzden
sıra: **tahmin → üretim emri → kapasite → MRP.**

---

## İş bölümü

Sorun: yeni bir alan doğal olarak **A'nın sahasına** düşer (`app/domain/**`,
`simulator/**`, `contracts.py`). B'ye iş kalmaz, B beklemeye geçer.

Çözüm: **tahmini ayrı bir servis yapmak.** Tahmin bir model işi; B "Servis &
Model" tarafı. Domain onu *çağırır*, içermez.

```
    A: simulator/uretim  ->  app/domain/production  --+
                                                      | cagirir
    B:                        app/forecast  <---------+
```

| Kişi B | Kişi A |
|---|---|
| `app/forecast/**` | `simulator/uretim.py` — fabrika dünyası |
| tahmin ölçümü + geriye dönük sınama | `app/domain/production/**` — özellik + kural |
| `app/api/**` — üretim uçları | `contracts.py` — `URETIM_*`, `UretimOzellikleri` |
| `app/llm/**` — üretim gerekçeleri | `app/core/isletme_profili.py` — `UretimProfili` |
| `app/jobs/nightly.py` | `app/adapters/` — BOM / rota / iş merkezi CSV |
| `training/**` | |

**Aramızdaki tek bağ:** `app/forecast/contracts.py::TalepTahmini`. Önce o
dondurulur, sonra iki taraf birbirini beklemeden çalışır. Dosya çakışması
yok — bugünkü B2 karışıklığının (ikimiz de aynı işe başlamıştık) tekrarını
bu tablo engelliyor.

---

## ✅ Adım 1-2 — BİTTİ (B, `3ba8f5b`)

`app/forecast/`: donmuş sözleşme, naif tabanlar, üssel düzleştirme, ölçüm.
15 test. Ölçüm komutu:

```
uv run python -m app.forecast.olcum
```

### ⚠️ Kural motorunu doğrudan ilgilendiren bulgu

Katalog **aralıklı talep** ağırlıklı: kalemlerin **%76'sı** (1525/2000)
günde 0,3'ten az satıyor. Toplam MASE bu kütlenin ortalaması olduğu için tek
başına okunamıyor; rapor katman kırılımını zorunlu basıyor.

Klasik üssel düzleştirme yalnızca hızlı kalemlerde tabanı geçiyor (0,89),
yavaş katmanda **%55 kötü** (1,55) — çoğu günü sıfır olan seriler için
yanlış model ailesi. Simülatörün kendisi de o kalemler için ayrı bir
"aralıklı talep" süreci kullanıyor.

⚠️ Bu sayılar B10.2'deki kesme penceresi düzeltmesinden **sonraki** koşudan;
öncekiler geçersiz.

**Üretim emri kuralı yazarken bunun karşılığı şu:** tahmin tek bir sayı
olarak kullanılamaz. `TalepTahmini` bu yüzden bandı **zorunlu** tutuyor;
emniyet payı `toplam_bandi()` üst sınırına bakarak seçilmeli.

---

## ✅ Adım 2b (B10.2) — BİTTİ (2026-08-11)

`app/forecast/aralikli.py`: Croston + SBA. Tam tablolar `KISI-B-GOREV.md`'de.
⚠️ İki taraf bu işi **paralel** yaptı; birleştirildi.

Plan açısından bağlayıcı üç şey:

**1. Ölçüm penceresi düzeltildi.** Kesmeler serinin kuyruğundan alınıyordu ve
o dönemde talep düşük olduğu için HER yöntem yukarı yanlı görünüyordu.
Kesmeler seriye yayıldı; önceki tüm tahmin sayıları geçersiz.

**2. Ölçüt değişti.** MASE aralıklı seride "her gün sıfır" tahminini
ödüllendiriyor — üretim emri onu kullanamaz. Rapor artık **yanlılık**,
**bağıl hata**, **sıfır oranı** ve **bant kapsaması** da basıyor.
`mevsimsel_naif` MASE'de önde ama pencerelerin %68'inde "hiç üretme" diyor.

**3. Adım 3'e giren karar:** üretim emri kuralı `aralikli.croston` çağırsın
(yansız: %0; SBA −%7 yanlı). Bant, geçmişteki gerçek 14 günlük toplamların
kuantillerinden kuruluyor — kapsama %93.

⚠️ **Süreç:** hem Adım 1-2'nin hem bu turun ilk commit mesajının tabloları
depodaki kodla yeniden üretilemedi (ikisi de doğrulandı). Bundan sonra rapor
çıktısı olduğu gibi yapıştırılacak.

## ✅ Adım 3 — Üretim emri kararı — BİTTİ (2026-08-11)

**A10.1 · fabrika dünyası** — `simulator/uretim.py`: katalog üretilen/satın
alınan diye ayrılıyor (ciro sıralamasının üst %15'i), üretilenlere hat, parti
büyüklüğü, hazırlık ve işlem süresi veriliyor. Deterministik, testli.

**A10.2 · üretim emri kararı** — `app/domain/production/`:
`uretim.emir_ac` / `uretim.emir_erteleme` / `uretim.aksiyon_yok`.
Kural: ihtiyaç = `tahmin.toplam_bandi()` üst sınırı × emniyet çarpanı;
açık = ihtiyaç − (elde + açık emirler); miktar parti katına yuvarlanıyor.

Sözleşmeye eklenenler: `KararTipi.URETIM_*`, `UretimOzellikleri`,
`UretimProfili` (işletme profili JSON'una `uretim` bloğu).

### Uçtan uca sonuç (gerçek simülasyon verisi)

```
uretilen kalem : 300 / 2000
uretim.emir_ac         99
uretim.aksiyon_yok    201
```

### ⚠️ Bilinen iki nokta

**1. `emir_erteleme` kolu gerçek veride hiç tetiklenmedi.** Sebebi
yapısal: simülatörde parti büyüklüğü kalemin ~10 günlük talebi olarak
seçiliyor, `asgari_emir_gun` ise 3 — yani bir parti her zaman eşiği
geçiyor. Kol birim testli ama **sahada denenmemiş** durumda.

Bunu ölü tip saymak yanlış olur (`stok.tedarikci_degisim` dersi): kural
gerçek fabrikada tetiklenir, çünkü orada parti büyüklüğü talebe göre değil
hatta göre belirlenir. Ama gerçek CSV geldiğinde **ilk bakılacak şey bu**.

**2. ~~`explain.py`'de `uretim.*` şablonu yok.~~** ✅ Adım 6'da kapandı.

## ✅ Adım 4 — Kapasite — BİTTİ (2026-08-11)

`app/domain/production/kapasite.py`: `uretim.kapasite_asimi`. Hat hat toplam
emir yükü hesaplanıyor; kapasiteyi aşan hatta **en az acil** emirler
erteleniyor.

**Öncelik ölçütü kapsama günü** (`net_pozisyon / günlük tahmin`), tutar
değil. Tutara göre sıralamak, pahalı bir kalemin stoğu biterken ucuz bir
kalem için hattı açık tutardı. Sorun para değil, zaman.

**Kapasite penceresi planlama ufku**, takvim haftası değil (plan "bir hafta"
diyordu). Emirler ufka göre üretiliyor; kapasiteyi haftaya bölmek emirle
kapasiteyi iki farklı zaman ölçeğinde karşılaştırmak olurdu.

**Hedef kullanım oranı (%85) çarpan olarak giriyor**, sonradan bakılan bir
eşik olarak değil. %100 dolu hat, tek gecikmede tüm planı kaydırır.

### Uçtan uca sonuç (gerçek simülasyon verisi)

```
HAT DOLULUGU
  H-01: yuk     97.5 saat / kapasite   190.4 saat  ( 51%)
  H-02: yuk    116.7 saat / kapasite    95.2 saat  (123%)   <- asim
  H-03: yuk     27.1 saat / kapasite   285.6 saat  (  9%)

KAPASITE: 7 erteleme onerisi (hepsi H-02)
  kapsama gunleri: 43, 36, 32, 30, 26, ...
```

Ertelenenler en yüksek kapsamalı kalemler — kural amaçlandığı gibi çalışıyor.
⚠️ Adım 3'teki `emir_erteleme` kolunun aksine bu kol gerçek veride
**tetikleniyor**.

### ⚠️ Kapsam: çizelge kurulmuyor

Vardiya planlama ve iş sırası optimizasyonu dışarıda ve bu mimari bir karar,
eksiklik değil. Otonomi modeli kalem bazında insan onayına dayanıyor; tek bir
çizelgeyi onaylamak, içindeki yüzlerce örtük kararı görmeden onaylamak
olurdu. Sistem kısıtı **görünür kılıyor ve erteleme öneriyor**.

Bu değişecekse mimari kararı önce konuşulmalı.

## ✅ Adım 5 — MRP — BİTTİ (2026-08-11)

`simulator/uretim.py::urun_agaci_uret` + `app/domain/production/mrp.py`.
Açılması önerilen emirler patlatılıp hammadde başına toplam ihtiyaç
çıkarılıyor.

**Çıktısı yeni bir karar türü değil.** `StockFeatures.mrp_ihtiyaci` alanına
giriyor ve stok kararında **yeniden sipariş noktasının üstüne ekleniyor**.
Ayrı bir `uretim.malzeme_siparis` tipi tanımlamak cazipti ve yanlış olurdu:
aynı hammadde için iki ayrı kaynaktan iki sipariş kararı çıkar, ikisi
birbirini görmez ve tam olarak kaçınmaya çalıştığımız üst üste sipariş
oluşurdu.

⚠️ MRP ihtiyacı stoktan **düşülmüyor**, eşiğe ekleniyor. Düşmek
`kullanilabilir_stok`'u bozardı ve o sayı gerekçede geçiyor — insan "elde
300 var" derken sistem 180 yazardı.

⚠️ `mrp_ihtiyaci` varsayılanı 0: alanın eklenmesi tek başına hiçbir sayıyı
oynatmıyor, testi var.

### Ürün ağacı tek katmanlı

Bileşenler yalnızca **satın alınan** kalemlerden seçiliyor. Bir bileşenin
kendisinin de üretilen olması özyinelemeye ve döngüye kapı açardı (A parçası
B'yi, B de A'yı içerirse). Satın alınanlarla sınırlamak bu riski kontrol
ederek değil, **imkânsız kılarak** kapatıyor.

Çok katmanlı ağaç (yarı mamul → mamul) sonraki iş. Önce tek katman
doğrulanır: çok katmanlıda çıktı yanlışsa hatanın hangi katmanda olduğunu
ayırt etmek zor.

⚠️ Ürün ağacı tanımsız kalem sessizce atlanıyor (tek eksik satır tüm MRP
koşusunu düşürmemeli) ama `eksik_agac_kalemleri()` bunu ayrıca raporluyor.
Sessiz atlama, üretimi durduran bir malzeme eksiğini üç ay sonra keşfetmek
demek olurdu.

---

## ✅ Adım 6 — Servis katmanı — BİTTİ (2026-08-11)

- **`POST /v1/decisions/production/order-review`** — liste döndürüyor.
  Tek kalem sorulsa bile: bir kalem aynı anda hem `emir_ac` hem
  `kapasite_asimi` alabilir.
- **`explain.py`'ye `uretim.*`** — dört tabloya birden eklendi
  (`_TIPE_GORE_ALANLAR`, `_DURUM_IFADELERI`, `_ETIKETLER`,
  `sablon_gerekce`). ⚠️ B5'in kök nedeni birincisiydi: tip orada yoksa
  `sayi_etiketleri` boş dönüyor, model **hiç çağrılmıyor** ve her gerekçe
  sessizce şablona düşüyor. Testi önce yazıldı.
- **`nightly.py`** — üretim taramaya girdi.

### Gecelik tarama gerçekten koştu

```
taranan SKU        : 3.133
kuyruga giren      : 1.155
gerekce uretilen   : 10  (gecti 5 · yeniden 1 · sablon 4)
TOPLAM             : 187,9 sn        (hedef < 600 sn)
```

Alan bazında guard kırılımı — planın doğrulama ölçütü buydu:

```
uretim.emir_ac    gecti              1
uretim.emir_ac    yeniden_uretildi   1
uretim.emir_ac    sablona_dustu      0
```

**Şablona düşme oranı %0** (eşik %50). ⚠️ Örneklem küçük: yalnızca 2 üretim
gerekçesi üretildi, çünkü gerekçe yalnızca en riskli ilk N karar için
çıkarılıyor. Sayı, "alan bağlanmamış" kusurunun yokluğunu gösteriyor;
gerekçe kalitesi hakkında bir şey söylemiyor.

---

## "Başka fabrikaya uyarlanabilsin" — iki katman

Bu ikisini karıştırmak profili bakılamaz hâle getirir:

| katman | ne tutar | nerede | boyut |
|---|---|---|---|
| `UretimProfili` | planlama ufku, parti politikası, hedef kapasite kullanımı, emniyet payı | işletme profili JSON'u | ~15 alan, elle yazılır |
| fabrika ana verisi | ürün ağacı, iş merkezleri, rotalar, süreler | `csv_erp.py` kalıbıyla CSV | binlerce satır |

Yeni fabrika = **bir JSON + üç CSV**. Kod değişmez.

⚠️ BOM'u profile koymak cazip ve yanlış: profil iş sahibinin elle düzenlediği
dosya, ürün ağacı ERP'den gelen tablo.

---

## Doğrulama

| adım | nasıl kanıtlanır |
|---|---|
| tahmin | `python -m app.forecast.olcum` → katman kırılımlı MASE, naif tabanla yan yana |
| üretim emri | çok kararlı bir kalem için API hepsini döndürüyor + testi |
| kapasite | kapasite aşan bir hafta kurgulanır, sistem erteleme öneriyor mu |
| profil | ikinci bir profil + CSV seti ile **kod değişmeden** farklı sonuç |
| LLM | gecelik koşuda üretim gerekçelerinin `sablona_dustu` oranı; %50 üstü = alan bağlanmamış |

---

## Kişi A'nın onayı gereken üç şey

1. **`app/forecast/` B'ye atansın mı?** Sahiplik tablosunda yoktu; yeni bir
   üst paket.
2. **`contracts.py`'ye `URETIM_*` + `UretimOzellikleri`** — donmuş dosya,
   tek taraflı değişmez. `ORAN_ALANLARI` değişikliğinde izlenen yolun aynısı.
3. **`TalepTahmini` alanları yetiyor mu?** Üretim kuralı başka bir şeye
   ihtiyaç duyuyorsa **şimdi** söylenmeli — sözleşme dondurulduktan sonra
   değiştirmek ikimizi de kırar.
