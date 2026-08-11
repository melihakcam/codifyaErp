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

İlk ölçüm üç yöntemi de "naif tabandan iyi" gösterdi. Ama en **basit** yöntem
karmaşık modelden iyiydi — kazanması gereken yerde kaybeden bir model varsa
ölçümde sorun vardır. Katmanlara ayırınca tablo tersine döndü:

```
katman            kalem   hareketli  mevsimsel   ussel
hizli (>=2/gun)     197      0,98       0,93     0,84   <- model kazaniyor
orta                273      0,98       0,94     1,06
yavas (<0,3/gun)   1530      0,77       0,52     1,49   <- model FELAKET
```

Katalog **aralıklı talep** ağırlıklı: medyan günlük satış **0,07** (iki
haftada bir). Klasik üssel düzleştirme, çoğu günü sıfır olan seriler için
yanlış model ailesi — simülatörün kendisi de o kalemler için ayrı bir
"aralıklı talep" süreci kullanıyor.

**Üretim emri kuralı yazarken bunun karşılığı şu:** tahmin tek bir sayı
olarak kullanılamaz. Kataloğun **%76'sında** en iyi seçeneğimiz şu an naif
taban ve orada bant çok geniş olacak. `TalepTahmini` bu yüzden bandı
**zorunlu** tutuyor; emniyet payı banda bakarak seçilmeli, nokta tahminine
değil.

Rapor bunu kendisi söylüyor: hiçbir yöntem her katmanda kazanmıyorsa uyarı
basıyor ve toplam satırının yanına *"tek başına karar dayanağı değil"* notu
düşüyor.

---

## Adım 3 — Üretim emri kararı (A)

Stok sipariş kararının ikizi: aynı iskelet (özellik → kural → aday → politika
→ onay), tedarikçiden almak yerine kendi üretmek.

- `simulator/uretim.py`: kalemler **üretilen / satın alınan** diye ayrılır;
  üretilenlere hat, parti büyüklüğü, hazırlık ve işlem süresi verilir.
- Karar tipleri: `uretim.emir_ac`, `uretim.emir_erteleme`,
  `uretim.aksiyon_yok`.
- Kural: `tahmin.toplam_bandi()` üst sınırı + emniyet > eldeki + açık emirler
  → emir öner.

**Bitti sayılır:** üretilen bir kalem için emir kararı çıkıyor, testi var.

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
