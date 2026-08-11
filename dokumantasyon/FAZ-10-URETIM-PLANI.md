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

**2. `explain.py`'de `uretim.*` şablonu yok.** Üretim kararları bugün
alan-bağımsız son çareye düşüyor: metin doğru ve patlamıyor (testi var) ama
zayıf — "X için uretim.emir_ac kararı üretildi". Şablonları yazmak Adım
6'nın (B10.3) işi.

## Adım 4 — Kapasite (A)

`uretim.kapasite_asimi`: bir haftanın önerilen emir yükü hattın kapasitesini
aşıyorsa uyarır ve düşük öncelikli emri erteler.

⚠️ **Vardiya/çizelge optimizasyonu kapsam dışı.** Otonomi modeli kalem
bazında insan onayına dayanıyor; "tüm fabrikayı optimize et" kararı tek tek
onaylanamaz. Sistem kısıtı **görünür kılar ve erteleme önerir**, çizelgeyi
kurmaz. Bu değişecekse mimari kararı önce konuşulmalı.

## Adım 5 — MRP (A)

Ürün ağacını patlatıp hammadde ihtiyacı çıkarır. Çıktısı **yeni bir karar
türü değil**, mevcut `stok.siparis` kararının girdisi. İki alanı ilk kez
birbirine bağladığı için en sona bırakıldı.

## Adım 6 — Servis katmanı (B, 3-5'e paralel)

- `POST /v1/decisions/production/order-review` — **liste döndürür**
  (B1'de öğrenildi: bir kalem aynı anda birden çok karar alabilir)
- `explain.py`'ye `uretim.*` tipleri
  ⚠️ B5'te görüldü: `explain.py`'nin "alan-bağımsız" sanılan yerleri aslında
  alana bağlıydı ve **finans sessizce şablona düşüyordu**. Üretimde aynısı
  olmasın diye önce test, sonra kod.
- `nightly.py`: üretim taramaya girer. Guard kırılımı sayacı artık var, yeni
  alan şablona düşerse **ilk koşuda görünür**.

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
