# Bilinen Eksikler

> Bu dosya, **bilerek** ertelenmiş işleri tutar. Her madde ne olduğunu, neyi
> engellediğini ve ne zaman çözülmesi gerektiğini söyler. Amaç, bir eksiğin
> "unutulmuş" ile "ertelenmiş" arasındaki farkı kaybetmemesi.
>
> Son güncelleme: 2026-08-10 · Faz 8 · A paketi (A1-A5) + §12

---

## 1. ✅ ÇÖZÜLDÜ — Sözleşme stok'a çakılıydı

```python
class DecisionCandidate(BaseModel):
    alan: Alan                    # FINANS, SATIS, URETIM tanımlı ✅
    tip: KararTipi                # yalnızca stok.* tipleri var
    ozellikler: StockFeatures     # ⚠️ tip çakılı
```

`Alan` enum'ı ileriye dönük yazılmış ama `ozellikler` alanı `StockFeatures`
tipine sabit. Finans modülü yazıldığında oraya `FinansOzellikleri`
konulamaz.

**Alan-bağımsız katmanlara sızan stok bilgisi — dört nokta:**

| dosya | sızıntı |
|---|---|
| `app/contracts.py` | `ozellikler: StockFeatures`; `izinli_sayilar()` iki stok property'sini elle ekliyor |
| `app/llm/guard.py::maskelenecek_alanlar` | `sku_adi, sku_id, tedarikci_adi, tedarikci_id` okuyor |
| `app/core/policy.py:147` | `ozellikler.tedarikci_onayli` |
| `app/llm/explain.py` | `_ETIKETLER` / `_TIPE_GORE_ALANLAR` stok alanlarıyla dolu |

Geri kalan 37 `StockFeatures` göndermesi `app/domain/stock/` ve
`app/adapters/` içinde — orada olmaları **doğru**.

**✅ 2026-08-09'da çözüldü.** `AlanOzellikleri` taban sınıfı eklendi,
`ozellikler` alanı birleşim oldu, dört sızıntının dördü de kapatıldı.

⚠️ Ertelemek doğru karardı: taban sınıfın dört davranışı
(`maskelenecek_alanlar`, `hesaplanan_sayilar`, `oto_uygulama_engeli`,
`gorunen_ad`) **finans yazılırken ortaya çıkan gerçek ihtiyaçlardan** doğdu.
Önceden tasarlansaydı ya eksik ya fazla olurdu — özellikle son ikisi,
ancak politika ve gecelik iş kırıldığında görüldü.

---

## 2. ✅ ÇÖZÜLDÜ — Kimlik doğrulama yok

**✅ 2026-08-09'da çözüldü (Faz 7).** `app/core/auth.py`: API anahtarı, üç
taşıyıcı (`X-API-Key`, `Bearer`, çerez). Tüm `/v1` uçları ve onay ekranı
korumalı; `/health` bilinçli olarak açık (yük dengeleyici için, iş verisi
içermiyor). Anahtar tanımlı değilse doğrulama kapalı çalışır — ama
`ortam=uretim` iken hem açılış hem her istek reddedilir.

⚠️ **Geriye kalan sınır:** anahtar **sistemi** doğruluyor, kişiyi değil.
Denetim kaydındaki `kullanici` hâlâ çağıranın beyanı. Kişi bazlı yetki
(kim neyi onaylayabilir) ayrı bir iş.

`tests/test_auth.py::test_tum_v1_uclari_korumali` rota tablosunu gezerek
korumasız uç arıyor — yeni bir uç eklenip kimlik unutulursa test kırılır.

---

## 3. 🟡 Router sert kapısı açık: %75 (hedef %95)

Beş eğitim turu denendi. En iyi sonuç 36/48 (%75,0). Ayrıntı ve turların
tam karşılaştırması: `OLCUMLER.md`.

⚠️ **Bu bir iş değeri kapısı değil.** Para metriği gösterdi ki maliyet
düşüşünü kural motoru sağlıyor; router yanlış araç seçtiğinde kullanıcı
yanlış raporu görür ve tekrar sorar, para kaybı olmaz.

**Değerlendirme:** %95 hedefi 1,5B modelde, elle yazılmış şablonlardan
üretilen veriyle muhtemelen ulaşılamaz. Gerçek çözüm daha fazla eğitim turu
değil, **gerçek kullanıcı sorusu toplamak** (`/v1/feedback` ucu bunun için
duruyor). Hedefin gerçekçi bir yere çekilmesi (ör. %85) ayrıca tartışılmalı.

---

## 4. 🟡 Tüm ölçümler simülasyon verisinde

Para metriği, shadow raporu, router doğruluğu — hepsi simüle edilmiş
katalog ve talep akışı üzerinde. Gerçek veride:

- kural motoru ve guard **aynen** çalışır (formül ve kontrol, veriden bağımsız)
- gerekçe büyük ölçüde taşınır (model adı/sayıyı istemden kopyalıyor)
- **router en zayıf halka** — gerçek kullanıcı şablon yazılmamış şekilde sorar

`app/adapters/csv_erp.py` yazıldı; üç CSV gelir gelmez ölçüm hattı hazır.
Geriye dönük test (geçmiş 12 ay) bir haftalık canlı gözlemden güçlü kanıt
üretir.

**Engellediği:** `threshold` moduna geçiş. Faz 6'yı engellemiyor.

---

## 5. ✅ ÇÖZÜLDÜ — `stok.tedarikci_degisim` artık üretiliyor

Kural motoru bu karar tipini hiç çıkarmıyor; golden set'te de örneği yok.
Politika tablosunda ve `KararTipi`'nde tanımlı ama ölü.

**✅ 2026-08-10'da çözüldü (A3).** Kural yazıldı:
`rules.tedarikci_degisim_degerlendir` + `decide._tedarikci_degisim_karari`.

Üç tasarım kararı, üçü de bugün ölçülen kusurlardan geliyor:

1. **Ortogonal kol.** `elif` zincirine EKLENMEDİ. "Bu mala para bağlamalı
   mıyım?" ile "bu malı kimden almalıyım?" ayrı sorular; bir SKU aynı anda
   hem sipariş hem tedarikçi gözden geçirme kararı alabiliyor (§9, §11).
2. **Kanıt kapısı.** `TEDARIKCI_DEGISIM_ASGARI_VERI_GUN = 180`. Finansta
   limit kolu, veri azken yanlış tetikleniyordu (§8); karşı taraf hakkında
   karar veren her kural kanıt yeterliliğine bakmak zorunda.
3. **Öneri "değiştir" değil "gözden geçir".** Alternatif tedarikçi bilgisi
   `StockFeatures`'ta yok — sistem sorunu işaret ediyor, yerine kimin
   geleceğini insan seçiyor.

⚠️ **Bilinen sınır:** kanıt kapısı `veri_gun_sayisi` üzerinden, yani bir
**vekil ölçü**. Doğru kapı "bu tedarikçiye kaç sipariş verildi" olurdu ama
`StockFeatures` o alanı taşımıyor ve eklemek sözleşme değişikliği demek.
**✅ Aynı gün eklendi.** `StockFeatures.tedarikci_siparis_sayisi` sözleşmeye
girdi; asıl kapı artık `TEDARIKCI_DEGISIM_ASGARI_SIPARIS = 5`. Veri kaynağı
sipariş sayısını taşımıyorsa (alan 0) eski vekil ölçüye düşülüyor — kanıt
kapısı hiç olmamasındansa zayıf bir kapı.

⚠️ **B'ye etkisi:** `ozellikten_kararlar_uret` (çoğul) eklendi; tekil sürüm
davranışını korudu. Gecelik iş ve API çoğula geçtiğinde
(B1) bu karar tipi kuyrukta görünmeye başlayacak — politika tablosunda
eşiği zaten tanımlı.

---

## 6. 🟢 `onay_kuyrugu_sorgula` golden set'te ince

4 örnek — tek hata %25 oynatıyor. Ölçümün çözünürlüğünü düşürüyor ama
yanlış sonuç üretmiyor.

**Ne zaman:** bir sonraki veri üretim turunda hedefli paraphrase ile.

---

## 7. ✅ ÇÖZÜLDÜ — `yoldaki_stok` artık okunuyor

Çoğu ERP bunu ayrı tutmuyor. Sıfır varsaymak güvenli taraf (fazladan
sipariş önerir, tersi stok tükenmesine yol açardı).

**✅ 2026-08-10'da çözüldü (A4).** `urunler.csv`'de kolon varsa okunuyor;
sekiz yaygın ad tanınıyor (`yolda`, `siparis_edilen`, `acik_siparis`,
`on_order`, `in_transit`...). Yoksa 0 varsayılmaya devam ediyor.

⚠️ Güvenli taraf bedava değil ve bu artık belgede yazılı: yoldaki mal
görünmediğinde **aynı sipariş iki kez verilebilir**. Kurulumda bu alanın
varlığı sorulmalı.

---

## 8. 🔴 Finansın iş değeri hâlâ çıkmadı (güncel sayılar)

⚠️ **Bu bölümün sayıları 2026-08-10'da yenilendi.** Önceki tablo dört
değişiklik öncesine aitti (§9 ortogonal kollar, §10/§14 limit kolu,
§12 maddiyet kolu) ve artık gerçeği yansıtmıyordu. Eski sayılara bakıp
karar veren biri yanılırdı; ölçüm belgesi bayatlarsa ölçüm olmaktan çıkar.

**1 yıl, aylık inceleme, iki profil:**

| | taban | vasat | kural_motoru |
|---|---|---|---|
| **küçük nalbur** | 228.696 | **232.413** | 247.699 |
| batak zararı | 197.945 | 186.745 | **178.415** |
| takip maliyeti | 0 | 18.300 | 20.400 |
| marj kaybı | 0 | 0 | 24.215 |
| | | | **%-6,6** |
| **yapı toptancısı** | 5.578.239 | **5.438.518** | 5.649.408 |
| batak zararı | 4.909.498 | 4.631.836 | **4.478.426** |
| takip maliyeti | 0 | 210.900 | 195.750 |
| marj kaybı | 0 | 0 | 483.677 |
| | | | **%-3,9** |

**Özet: kural motoru toplam maliyette hâlâ vasatın gerisinde.** Ama tablo
tek renkli değil ve bu önemli:

⭐ **Batak zararında kural motoru her iki profilde de AÇIK ARA ÖNDE.**
Küçük nalburda vasattan 8.330 TL, büyük toptancıda 153.410 TL daha az
zarar. Yani "hangi alacağı kurtarabilirim" sorusunu vasattan iyi
cevaplıyor.

⚠️ **Kaybettiği tek yer marj kaybı** — limit kolunun bedeli (24 bin /
484 bin). Bu kalem çıkarılırsa kural motoru her iki profilde de kazanıyor.
Ama kolu kapatmak §14'te ölçülerek reddedildi: kol, batak riski
yükseldiğinde 11 kat asimetrik koruma sağlıyor.

**Yani asıl soru şu hâle geldi:** kredi limitini sıkmanın marj bedeli, o
limitin önlediği riske değer mi? Cevap müşterinin batak oranına bağlı ve
o oran **gerçek veriyle ölçülebilir** (§13'teki geriye dönük test hattı
hazır).

**Bugüne kadar denenen ve sonuç vermeyen dört yol:**

1. Etki modelinin `TAKIP_MALIYETI_TL` varsayımı — 0'dan 1.000 TL'ye beş
   noktada da kaybediyor. Sonuç parametre seçimine bağlı değil.
2. İş gücü tasarrufu anlatısı — §12'den sonra geçersiz; sistem artık
   daha ÇOK arıyor.
3. Adet bazlı kurtarma metriği — aldatıcı çıktı, tutar bazlıya çevrildi.
4. Limit kolunu kapatmak — kısa vadede kazandırıyor, risk profilinde
   kaybettiriyor.

**Dürüst konum:** finans için "maliyeti %X düşürdü" cümlesi **yok** ve
zorlanarak üretilmeyecek. Söylenebilecek olan: *"şüpheli alacak zararını
vasat bir tahsilat politikasına göre %4-6 azaltıyor, karşılığında kredi
limitini sıkarak bir miktar satış marjından vazgeçiyor."* Bu bir ödünleşim
cümlesi, zafer cümlesi değil.

---

## 9. ✅ ÇÖZÜLDÜ — Karar önceliği sorunlu müşteriyi tahsilatın dışına atıyordu

Faz 7 ablasyon koşusunun bulduğu şey ve §8'deki olumsuz sonucun asıl kök
nedeni bu.

`app/domain/finance/decide.py` müşteri başına **tek** karar üretiyor ve
sırası: `karşılık → limit → takip → aksiyon yok`. Docstring'i şöyle
diyor: *"her adım bir öncekinin anlamsız kıldığı durumu eliyor."*

Ölçüm bunun tersini gösterdi. `kucuk_nalbur_dukkani`, 1 yıl, 3 batık
müşteri — sistemin bu üç müşteriye ürettiği kararlar:

| gün | üretilen kararlar |
|---|---|
| 120 | karşılık 2, limit 1 |
| 240 | karşılık 3 |
| 330 | karşılık 3 |

**Hiçbiri, hiçbir zaman `tahsilat_takibi` almıyor.** Yani parasını
gerçekten alamayacağın müşteri, sistemin tahsilat kolunun hiç dokunmadığı
tek grup.

Ablasyon sayıları (limit kolu kapalı koşu):

| | taban | vasat | kural_motoru | kural_motoru_limitsiz |
|---|---|---|---|---|
| toplam maliyet | 228.696 | 232.413 | 255.725 | 239.944 |
| batak zararı | 197.945 | 186.745 | 195.328 | **197.945** |
| takip sayısı | 0 | 122 | 77 | 75 |

Son sütundaki batak zararı **tabanla birebir aynı** (197.944,685531).
75 tahsilat eylemi yapılmış, 11.250 TL harcanmış, kurtarılan alacak
sıfır. Çünkü o 75 eylem, zaten ödeyecek müşterilere gitmiş.

⭐ **Kusur mantık hatası değil, modelleme hatası.** Üç kol birbirini
dışlar varsayıldı; oysa ortogonaller:

· karşılık ayırmak bir **muhasebe** işlemidir, takibi durdurmaz
· kredi limitini düşürmek **gelecek** riski keser, mevcut alacağı tahsil etmez
· ikisi de "bu müşteriyi arama" demek değil

Doğru davranış: batık bir müşteriye hem karşılık ayır, hem aramaya devam et.

**Ne yapılmalı:** `ozellikten_karar_uret` tek `DecisionCandidate` yerine
**liste** döndürmeli. Bu bir sözleşme değişikliği (`app/contracts.py`
dondurulmuş) — Kişi A ve B birlikte karar vermeli, tek PR'da. Etkileyeceği
yerler: gecelik iş, onay kuyruğu (müşteri başına birden çok satır),
eğitim verisi üreticisi, shadow raporu.

⚠️ Stok tarafında aynı kusur **yok gibi görünüyor** ama doğrulanmadı:
`tasfiye → sipariş` önceliği orada gerçekten dışlayıcı (ölü ürüne sipariş
vermek anlamsız). Yine de finans bunu ortaya çıkarana kadar kimse
sormamıştı; stok önceliği de aynı gözle bir kez incelenmeli.

### ✅ Düzeltildi (aynı gün)

`ozellikten_kararlar_uret` eklendi: müşteri başına **liste** döndürüyor,
koşulu sağlanan her kol kendi kararını üretiyor. `elif` zinciri kalktı.
Sözleşme değişmedi — `DecisionCandidate` aynı, yalnızca bir müşteri birden
çok aday üretebiliyor. `ozellikten_karar_uret` tekil sürüm olarak duruyor
(HTTP ucu tek karar döndürmek zorunda) ama artık "birincil karar" demek.

Çağıranlar güncellendi: gecelik tarama ve para metriği çoğul sürümü
kullanıyor. Regresyon kilidi:
`test_batak_musteri_hem_karsilik_hem_takip_aliyor`.

**Düzeltme sonrası ölçüm:**

| | taban | vasat | kural_motoru | limitsiz |
|---|---|---|---|---|
| toplam maliyet | 228.696 | 232.413 | **246.592** | 238.049 |
| batak zararı | 197.945 | 186.745 | **178.415** | 191.416 |
| kurtarılan fatura | 0 | 74 | 26 | **81** |
| takip sayısı | 0 | 122 | 121 | 117 |

Takip kolu artık **çalışıyor**: kural motorunun batak zararı üç politikanın
en düşüğü (178.415 — vasattan 8.330 TL iyi). Limitsiz koşu 81 fatura
kurtarıyor, vasatın 74'ünden fazla.

⚠️ **Ama toplam sonuç hâlâ vasatın gerisinde (%-6,1).** İki sebep:

1. Limit kolu 24.215 TL marj kaybı yazıyor ve tahsilat kazancını yiyor.
2. Takip sayısı 121'e çıktı (vasat 122) — "daha az arama" avantajı kalmadı.
   Kollar ortogonal olunca sistem de neredeyse herkesi arıyor.

Yani §8 hâlâ açık: finansın iş değeri ölçüldü, çıkmadı. Ama artık
**sebebini biliyoruz** ve sebep bir kod kusuru değil: limit kolunun marj
maliyeti, tahsilat kolunun kazancından büyük. Sıradaki adım limit kolunun
eşiğini (`LIMIT_DUSURME_SKOR_ESIGI = 45`) düşürmek olabilir — daha az
müşteriye, daha emin olduğunda dokunmak.

---

## 10. ✅ A7.1 ÇÖZÜLDÜ — Limit kolu kapatıldı (ölçüldü)

`limit_kolu_taramasi_calistir` iki profilde, beş eşik × üç kesinti oranında
taradı. Sonuç **tek yönlü**: kol ne kadar tetiklenirse o kadar zarar.

`kucuk_nalbur_dukkani` (vasata göre toplam maliyet):

| eşik | limit kararı | marj kaybı | vasata göre |
|---|---|---|---|
| kapalı | 0 | 0 | **%-2,4** |
| 30 | 12 | 1.748 | %-3,1 |
| 45 (eskisi) | 165 | 24.215 | %-6,1 |
| 60 | 305 | 50.048 | %-16,0 |

`yapi_malzemesi_toptancisi`: kapalı %-0,3 · 45 → %-4,9 · 60 → %-9,3.

⭐ Kol **işini yapıyor** — batak zararını gerçekten düşürüyor (büyük
profilde 4,73M → 4,35M). Ama önlediği riskten üç kat fazla marj yakıyor
(1,03M). Sorun kolun bozukluğu değil, korumanın fiyatı.

**Karar:** `rules.LIMIT_KOLU_AKTIF = False`. Kod silinmedi, kapatıldı —
ölçüm varsayımsal bir etki modeline dayanıyor ve simülasyonda batak oranı
%2 / ufuk 1 yıl; kredi limitinin asıl işi nadir ama büyük çöküşü
engellemek, bu ufukta temsil edilmiyor. A7.2 kalibrasyonundan sonra
bayrak `True` yapılarak geri açılabilir.

**§8'in güncel hâli:** kural motoru artık vasatın %2,4 gerisinde (%6,1
değil), büyük profilde %0,3. Yani **başa baş**. Tahsilat kolu 81 fatura
kurtarıyor (vasat 74) ve 117 aramayla yapıyor (vasat 122). Hâlâ "maliyeti
%X düşürdü" denecek bir sayı yok — ama "aynı işi daha az aramayla yapıyor"
denebilir. İş gücü metriği (§8 seçenek 2) artık gerçekçi bir iddia.

---

## 11. ✅ ÇÖZÜLDÜ — Stoksuzluk, ölü stok gibi görünüyordu

A2 incelemesinin bulduğu şey. §9'un stok kardeşini ararken çıktı — ama
beklenen yerde değil.

**Beklenen kusur YOK.** Stokta `tasfiye → sipariş` dışlaması doğru: ikisi
aynı soruya zıt cevap veriyor ("bu mala para bağlamalı mıyım?"), aynı anda
uygulanamaz. Finansta üç kol ortogonaldi, burada değil. Eşiğin yönü de
doğru — `_olu_stok_esigi` `max(mutlak, göreceli)` kullanıyor, eşik yalnızca
yukarı çıkabiliyor. **Finanstaki kusur kalıbın kendisinde değil,
kopyalanırken `max`'ın `min` yazılmasındaymış.**

**Ama başka bir şey çıktı.** Dışlamanın sağlamlığı tek bir alana bağlı:
`son_hareket_gun_once`. O alanın anlamı veri kaynağına göre değişiyor:

| kaynak | `talep` neyi taşıyor | stoksuzlukta |
|---|---|---|
| `simulator/run.py` | **gerçek talep** (karşılanamayan ayrıca kayıtlı) | hareket görünür |
| `adapters/csv_erp.py` | `hareketler.csv` = **fiili satış** | hareket YOK |

Yani gerçek veride uzun süre stoksuz kalmış bir ürün "120 gündür hareketsiz"
görünür. Tasfiye tetiklenir, tasfiye siparişi bastırır, ürün bir daha hiç
hareket etmez — **teşhis kendi kendini doğrular.** Aç kalan ürün ölü ilan
edilip iskontoyla elden çıkarılır.

`tests/test_alan_genisletme.py::test_stoksuzluk_olu_stok_gibi_gorunuyor`
bu davranışı belgeliyor (onaylamıyor): elde 2 birim, 120 gün hareketsiz,
geçmiş talep günde 8 → sistem `stok.tasfiye` diyor.

**Şimdi zararsız, gerçek veride canlı risk.** Bugün tüm ölçümler
simülasyonda (§4) ve orada talep tablosu gerçek talebi taşıyor.

**Ne yapılmalı (A4 ile birlikte):** ölü stok kuralı "hareket yok" ile
"satacak mal yoktu" arasını ayırmalı. En ucuz ayrım: hareketsiz geçen
günlerde **eldeki stok da sıfıra yakın mıydı?** Öyleyse bu ölü stok değil,
karşılanamayan talep. `envanter_gunluk` tablosu bu bilgiyi zaten taşıyor;
CSV adaptörünün karşılığı `stok_seviyesi` sütunu.

⚠️ **A3 için bağlayıcı not:** `stok.tedarikci_degisim` kuralı yazıldığında
`decide.py`'deki `elif` zincirine **eklenmemeli**. Tedarikçi değişimi bir
karşı taraf kararı; ölü stok tespiti onu geçersiz kılmaz — tıpkı finansta
karşılık ayırmanın tahsilat takibini geçersiz kılmaması gibi (§9).


---

## 12. ✅ ÇÖZÜLDÜ — A1 sonucu: iş gücü iddiası da tutmuyordu

> Teşhis §12, düzeltmesi **§15**. Başlık 2026-08-10'da güncellendi;
> "🔴 açık" görünüyordu ama iş aynı gün bitmişti.

§8 kapanırken "maliyet iddiası yok ama iş gücü tasarrufu var" denmişti.
A1 bunu ölçtü ve **o iddia da yanlış çıktı.**

Yanılgının kaynağı: adet saymak.

| | vasat | kural_motoru |
|---|---|---|
| takip saati | 40,7 | **39,0** |
| kurtarılan **fatura** | 74 | **81** |
| kurtarılan **tutar** | **8.437 TL** | 6.606 TL |
| saat başına kurtarılan | **207 TL** | 169 TL |

Kural motoru daha çok fatura kurtarıyor ama daha az para: kurtardıkları
**küçük** faturalar. Saat başına verimde vasat %22 önde.

⚠️ Bu, projenin kendi raporunda bir kez yapılmış hatanın aynısı: metriği
adet üzerinden kurmak. Yalnızca "81 vs 74" yazan bir rapor, sistemi
kazanmış gösterirdi.

**Teşhis:** takip eşiği "bu gecikme bu müşteri için olağandışı mı?"
sorusunu soruyor — **anomali**. Ama "bu benim zamanıma değer mi?" sorusunu
hiç sormuyor — **büyüklük**. Vasatın düz 30 gün kuralı ayrım yapmadığı
için büyük alacakları da yakalıyor; kural motoru istatistiksel olarak
sıradan görünen büyük bir alacağı atlıyor.

Risk skoru (`app/core/policy.py`) kuyruğu tutara göre sıralıyor ama
**karar verme** aşaması büyüklüğe hiç bakmıyor. Anomali tespiti ile
önceliklendirme iki ayrı iş ve şu an yalnızca birincisi var.

**Duyarlılık:** sonuç `TAKIP_MALIYETI_TL`'ye bağlı değil — 0 TL'den
1.000 TL'ye kadar beş noktada da kural motoru kaybediyor (%-3,0 → %-0,4).
Yani bulgu bir parametre seçiminin sonucu değil.

**Ne yapılmalı:** takip kararına bir büyüklük bileşeni eklenmeli — ör.
eşiği aşan alacaklar arasında `vadesi_gecen_tl` ile ağırlıklandırma, ya da
"eşiği aşmasa bile şu tutarın üstündeki gecikmeler takibe girer" ikinci
kuralı. ⚠️ Değişiklikten sonra **yeniden ölçülmeli**; kazanana kadar
parametre denemek değil, tek bir tasarım değişikliği yapıp sonucu olduğu
gibi raporlamak.


### §11 çözümü (2026-08-10, A4)

`OLU_STOK_ASGARI_STOK_GUN = 1.0` eklendi: ölü stok iddiası ancak elde **en
az bir günlük talebi karşılayacak mal varken** kurulabiliyor.

    eski: eldeki_stok > 0
    yeni: eldeki_stok > 0 ve eldeki_stok >= ort_gunluk_talep x 1 gün

Elde 2 birim kalmış, günde 8 birim talep gören ürün artık tasfiye değil
**sipariş** kararı alıyor. Gerçek ölü stok (400 birim, talep 0,1/gün, 200
gün sessiz) hâlâ tasfiye ediliyor — düzeltme fazla ileri gitmiyor, iki test
bunu kilitliyor.

⚠️ Sözleşme değişikliği gerekmedi: `eldeki_stok` ve `ort_gunluk_talep`
zaten `StockFeatures`'ta vardı. Doğru soru sorulmamış, veri eksik değildi.


---

## 13. 🟡 Geriye dönük test hattı hazır, gerçek veri hâlâ yok

A4'ün ana teslimatı: `app/adapters/geriye_donuk.py`. Sistem geçmiş
tarihlerde koşturulup kararları gerçekleşenle karşılaştırılabiliyor.

**Ne ölçüyor:** "sistem riski önceden gördü mü?" — tükenme yaşandı ve
sistem öncesinde sipariş dediyse *yakaladı*, sessiz kaldıysa *kaçırdı*.

⚠️ **Ne ölçemiyor:** "sipariş verilseydi ne olurdu?" Geçmişte o sipariş
verilmedi; sonucu gözlenemez. Bu yüzden çıkan sayı bir **duyarlılık
(recall)** ölçüsü, doğruluk değil.

⚠️ **Duyarlılık tek başına okunamaz.** İlk deneme koşusunda duyarlılık
1,00 çıktı — ama sipariş önerisi oranı da 1,00'dı. Yani sistem her ölçüm
noktasında "sipariş ver" diyordu; sayı iyiliği değil ayrımsızlığı
gösteriyordu. Rapora her zaman iki sayı birlikte yazılmalı.

**Yeni gereksinim:** `hareketler.csv` artık geriye dönük test için
**`hareket_tipi` kolonunu zorunlu** kılıyor. Geçmiş stok bugünkü bakiyeden
geriye yürünerek kuruluyor; giriş hareketleri olmadan bu hesap yapılamaz.
Kolon yoksa modül açık hata veriyor — sessizce yanlış sayı üretmiyor.

**Veri kalitesi sinyali:** `negatif_stok_gun`. Yeniden kurulan stok
negatife düşüyorsa bakiye ile hareketler tutarsızdır (eksik giriş kaydı,
sayım farkı). Ölçüm yine koşuyor ama sonucun güvenilirliği düşer.

**Engellediği:** hâlâ `threshold` modu — çünkü **gerçek müşteri verisi
yok**. Hat hazır, üç CSV gelir gelmez koşacak. Eksik olan kod değil veri.


---

## 14. ✅ A5: limit kolu yeniden AÇILDI (aynı gün, ters karar)

§10'da kol ölçülerek kapatılmıştı. A5 kapatma gerekçesinin bilinen sınırını
test etti ve **kararı tersine çevirdi**. İkisi de doğru; soru değişti.

§10 tek bir senaryoyu ölçmüştü: batak müşteri oranı %2, ufuk 1 yıl. Oysa
kredi limitinin asıl işi **nadir ama büyük** çöküşü engellemek ve o senaryo
orada hiç temsil edilmiyordu.

`limit_kolu_risk_taramasi` — kol açık vs kapalı, net katkı TL
(pozitif = kol kazandırdı):

| batak oranı | 1 yıl | 3 yıl |
|---|---|---|
| %2 | **-8.543** | +18.309 |
| %5 | +31.445 | +67.109 |
| %10 | +18.644 | +96.541 |

Altı senaryonun beşinde kol kârlı. Kaybettiği tek hücre, en yumuşak olanı.

⭐ **Varsayılanı belirleyen çoğunluk değil, kaybın asimetrisi.** Kol
gereksizken açık olmanın bedeli 8.543 TL; gerekliyken kapalı olmanın bedeli
96.541 TL — **11 kat**. Kredi limiti bir sigortadır: primi düşük riskte
boşa gider, yangında ödediğin primle kıyaslanmaz.

⚠️ **Bedeli saklanmıyor:** varsayılan senaryoda (§8'in ölçüm zemini) kural
motoru vasata göre %2,4 yerine %6,1 geride kalıyor. Kolu açık bırakmak
benchmark sayısını **kötüleştiriyor**. Sayıyı iyi göstermek için kapatmak,
sistemi gerçek riskte savunmasız bırakmak olurdu — bu tercihi bilinçli
yapıyoruz.

**Müşteri bazında ayar:** portföyün batak oranı %3'ün altındaysa ve
planlama ufku 1 yılsa `LIMIT_KOLU_AKTIF = False` yapılabilir. Emin
değilsen açık bırak.


---

## 15. ✅ §12 çözüldü: takip kararı artık tutara da bakıyor

A1'in teşhisi: takip eşiği "bu gecikme bu müşteri için olağandışı mı?"
diye soruyordu (**anomali**) ama "bu alacak aramaya değer mi?" diye hiç
sormuyordu (**maddiyet**).

`rules.takip_gerekcesi` iki ortogonal kol taşıyor. Maddiyet eşiği
**seçilmedi, türetildi**:

    eylem maliyeti = alacak x günlük finansman oranı x ufuk
    150 TL = X x (0,45/365) x 30  →  X ≈ 4.056 TL

⭐ Türetilmiş olması önemli: bu bir "iş kararı" değil, iki iş girdisinin
(personel maliyeti, finansman oranı) sonucu. Müşteride faiz düşükse eşik
kendiliğinden yükselir.

Yan fayda: `PERSONEL_SAATLIK_MALIYET_TL`, `TAKIP_SURESI_DK` ve
`YILLIK_FINANSMAN_ORANI` artık **tek yerde** (`rules.py`); ölçüm modülü
oradan okuyor. Önceden ikisinde ayrı tanımlıydı ve sessizce ayrışabilirdi.

### Sonuç: profile göre değişiyor

| | küçük nalbur (1 yıl) | yapı toptancısı (1 yıl) |
|---|---|---|
| maddiyet kapalı | 246.592 | 5.705.491 |
| maddiyet açık | 247.699 | **5.649.408** |
| batak zararı | değişmedi | 4.566.924 → **4.478.426** |
| takip sayısı | 121 → 136 | 650 → **1.305** |
| kurtarılan tutar | ~aynı | 54.092 → **87.871** |

**Küçük nalburda zarar (+1.107 TL)**: 15 fazla arama, sıfır ek kurtarma.
Türetilmiş eşik o ölçekte nadiren bağlıyor.

**Büyük toptancıda kazanç (−56.083 TL)**: batak zararı 88 bin TL düşüyor,
kurtarılan tutar %62 artıyor.

⚠️ **Bedeli: iş yükü iki katına çıkıyor** (650 → 1.305 arama) ve saat
başına verim düşüyor (250 → 202 TL). Yani §12'nin düzeltmesi A1'in "daha az
aramayla" anlatısını **büsbütün ortadan kaldırıyor**. Sistem artık daha çok
arıyor ve daha çok para kurtarıyor.

**Açık kalan:** kural motoru büyük profilde hâlâ vasatın gerisinde
(5.649.408 vs 5.438.518). §8 kapanmadı.


## 16. ✅ ÇÖZÜLDÜ — `finans.kredi_limiti_dusur` hiç üretilmiyordu

**Bulan:** Kişi B, Tur 8 · B1 sırasında. **Çözen:** Kişi A, aynı gün,
§14 (A5 — limit kolu yeniden açıldı). İki iş birbirinden habersiz yürüdü ve
aynı yere çıktı.

**Çözüldükten sonra ölçüldü:**

```
                             once   sonra
finans.kredi_limiti_dusur       0      10
musteri basina azami karar      2       3   (9 musteride)
```

M-0192 artık tam olarak görev tanımındaki vaka: `karsilik_ayir` +
`kredi_limiti_dusur` + `tahsilat_takibi`. B1'in kabul ölçütü ("üç kararı
olan bir müşteri için API üçünü de döndürüyor") artık **gerçekten**
sınanabiliyor ve sınanıyor — test sabit sayı yerine dünyadan okunan azami
çokluğu kullandığı için kendiliğinden kapsadı, tek satır değişmedi.

---

### Bulgu kaydı (tarihsel)

Sözleşmede dört finans karar tipi var; demo dünyada üçü üretiliyor:

```
finans.aksiyon_yok         627
finans.tahsilat_takibi     173
finans.karsilik_ayir        16
finans.kredi_limiti_dusur    0   <-- hic
```

800 müşterinin hiçbiri limit düşürme kararı almıyor. `stok.tedarikci_degisim`
ile aynı durum — o §-A3'te canlandırılmıştı.

**Engellediği işler:**

- **B1'in kabul ölçütü.** Görev tanımı "üç kararı olan bir müşteri için API
  üçünü de döndürüyor" diyordu; demo dünyada azami çokluk **2**
  (800 müşterinin 16'sı, hepsi `karsilik_ayir` + `tahsilat_takibi`). Test
  sabit sayı yerine dünyadan okunan azami çokluğu kullanıyor, yani limit
  kararı canlanınca kendiliğinden kapsayacak.
- **B5 golden set.** Finans örnekleri eklenirken bu tipin örneği olmayacak;
  gerekçe üretimi o tip için hiç sınanmamış kalır.

⚠️ Kural motoru Kişi A'nın sahası; bu bir bulgu bildirimi, düzeltme değil.
Limit kolu §10'da "ölçüldü ve kapatıldı" diye geçiyor — bu sıfırın kasıtlı
mı yoksa eşiklerin demo dünyaya denk gelmemesi mi olduğu **doğrulanmadı**.


---

## 17. ✅ B4 + B6: üretim sertleştirmesi ve gecelik iş ölçümü

### B4 — dört soru, dört cevap

| soru | cevap |
|---|---|
| TLS çerezi | `Secure` bayrağı artık **isteğin şemasından de** çıkarılıyor (`cerez_guvenli or scheme == https`) |
| `/docs`, `/openapi.json` | Kimlik istiyor (`docs_kimlik_istesin`, varsayılan açık) |
| Hız sınırı | `hiz_siniri_dakikada = 300`, anahtar başına, kayan pencere |
| `/health/db` karar sayısı | Uç açık kaldı, **sayı kimliğe bağlandı** |

⚠️ Çerez bayrağında iki sessiz arıza vardı ve ikisi de kapandı: ayarı elle
`True` yapmayı unutan bir TLS kurulumunda çerez korumasız gidiyordu; ayarı
`True` yapıp HTTP'de çalışan bir geliştirme kurulumunda ise tarayıcı çerezi
hiç göndermiyor ve ekran sessizce çalışmıyordu.

⚠️ Hız sınırı **bellekte** tutuluyor. Tek süreçte doğru; birden çok worker
ile gerçek sınır worker sayısıyla çarpılır. Ölçekli kurulumda Redis'e
taşınmalı — kod içindeki not silinmeden çoğaltılmasın.

⚠️ Sınır yalnızca kimlik doğrulama **açıkken** uygulanıyor. Sınır, servis
dışarı açıldığında anlam kazanıyor ve o da tam olarak anahtar tanımlı olduğu
durum; geliştirmede kapalı kalması testleri rahat bırakıyor.

### B6 — gecelik iş, iki alandan sonra

| | ölçüm |
|---|---|
| karar sayısı | 2.826 stok + 826 finans = **3.652** |
| karar üretimi | **68 sn** (59 sn simülasyon + ~4 sn karar mantığı) |
| tepe RSS | **498 MB** (hedef < 4 GB) |
| gerekçe bütçesi | 25 × ~7 sn ≈ 175 sn |
| **toplam tahmin** | **~4 dk** (hedef < 10 dk) |

`gecelik_gerekce_ust_n = 25` **değiştirilmedi** — bütçenin yarısından
fazlası boşta. İki alan ve çoklu karar taramayı büyüttü ama darboğaz
gerekçe üretimi, karar üretimi değil.

⚠️ **İlk ölçümüm yanlıştı ve düzeltmesi öğretici.** `tracemalloc` açıkken
süre 297 sn çıktı; profilci her tahsisi izlediği için ölçümü ~5 kat
şişirmişti. Profilcisiz gerçek süre 68 sn. Ölçüm aracının kendisi ölçülen
şeyi bozabiliyor — bugünün dördüncü "metrik tek başına yalan söyler"
vakası.

⚠️ 59 saniyenin tamamı **demo simülasyonu**, karar mantığı değil. Gerçek
veride onun yerini CSV okuma alacak ve süre büyük olasılıkla düşecek.


---

## 18. ✅ ÇÖZÜLDÜ — B5: model finansı görmüyordu (tur6 ile kapandı)

Görev tanımı şuydu: "gerekçe modeli yalnızca stok kararlarıyla eğitildi,
finans için hiç ölçülmedi." Doğruydu. **Sebebi yanlış tahmin edilmişti.**

Ölçüm koşturulunca üç kusur çıktı ve üçü de `app/llm/explain.py`'de —
yani alan-bağımsız olduğu varsayılan katmanda. `BILINEN-EKSIKLER.md` §1'de
dört sızıntı kapatılmıştı; bunlar **beşinci, altıncı ve yedincisi**.

| # | kusur | sonucu |
|---|---|---|
| 1 | `sablon_gerekce` → `o.sku_adi` | finans kararında `AttributeError` |
| 2 | `egitilmis_istem_govdesi` → `urun: {o.sku_adi}` | istem hiç kurulamıyor |
| 3 | `_TIPE_GORE_ALANLAR`'da finans tipi yok | `anlatilacak_sayi_var_mi` hep False |

Üçünün birleşik etkisi: **her finans kararı 0 saniyede şablona düşüyordu.**
Model çağrılmıyordu bile. "Model finansı hiç görmedi" tespiti doğruydu ama
eğitim eksikliğinden değil, **sorunun hiç sorulmamasından**.

⚠️ Gecelik iş bunu yutuyordu: `_finans_kararlari` geniş bir `try/except`
ile sarılı ve hata log'a düşüp finans kararları sessizce kuyruğa hiç
girmiyordu. Faz 6'da "gecelik iş finans kararı görünce düşüyor" diye
bulunan kusurun kardeşi.

### Düzeltme sonrası ölçüm

| | |
|---|---|
| karar | 20 finans (`tahsilat_takibi`) |
| model | `codifya-router:tur5`, eğitilmiş kip |
| süre | 117 sn (**5,9 sn/karar**) |
| guard | **20/20 geçti** — reddedilen sayı yok |

### ⚠️ %0 reddetme oranı iyi haber DEĞİL

Guard yalnızca **sayıları** denetliyor. Model istemdeki sayıları kopyalayıp
etrafına anlamsız Türkçe diziyor; hiçbir sayı uydurulmadığı için guard
sessiz kalıyor. Örnekler:

```
"...gecikme durumunuz 21 gün ve bu durumdurunda 5,95 gün öne çıkar.
 Bu ürünlerin top..."
"Gerekce: Kayseri Bireysel Müşterisi 9 için finans.tahsilat_takibi
 raporu vardır ve bu rapor 143,79 tl seviyesi..."
```

Dördün birinde istem satırları (`karar:`, `Gerekce:`) doğrudan çıktıya
sızıyor. Metinler **kullanılamaz**; guard'ın ölçtüğü şey bu değil.

⭐ Bugünün beşinci "metrik tek başına yalan söyler" vakası. Guard reddetme
oranı finans için anlamlı bir kalite ölçüsü **değil** — çünkü guard sayı
uydurmaya karşı tasarlandı, saçmalamaya karşı değil.

**Şimdi eğitim turu gerçekten gerekli** ve gerekçesi netleşti: model finans
gerekçesi biçimini hiç görmedi. `training/build_dataset.py` finansı
kapsamıyor (B'nin sahasında). Eğitim öncesi ölçüm yapılmalıydı ve yapıldı —
ama ölçtüğü şey "eğitim gerekli mi" değil, "hat çalışıyor mu" oldu. Cevap:
çalışmıyordu, artık çalışıyor.

**Bir sonraki tur için kapı:** guard reddetme oranı değil, **istem sızıntısı
oranı** (`karar:` / `Gerekce:` / `VERILER` içeren çıktı yüzdesi) ve insan
okunabilirliği. Sayı doğruluğu zaten guard'ın işi.


---

## 19. 🟡 İki finans karar tipi tur6'da öğrenilmedi

tur6 ölçümü (39 karar, tur5 karşılaştırmalı):

| | tur5 | tur6 |
|---|---|---|
| istem sızıntısı | %15,4 | **%0,0** |
| guard geçti | %94,9 | %66,7 |
| şablona düştü | %0,0 | %30,8 |

**Asıl hedef tutturuldu:** istem kusma tamamen bitti ve stok tarafı
bozulmadı (`stok.*` guard %100, sızıntı %0). `finans.tahsilat_takibi`
tur5'te %50 sızdırıyordu, artık %0.

**Ama iki tip öğrenilmedi:**

| karar tipi | guard | şablon | eşsiz örnek |
|---|---|---|---|
| `finans.karsilik_ayir` | %0 | %83 | 137 |
| `finans.kredi_limiti_dusur` | %0 | %100 | 111 |

Sebep önceden biliniyordu: dengeleyici bu iki tipi ~10 kat çoğaltıyor.
Tekrar yeni bilgi eklemiyor — 111 örnekle öğrenilen bir tip öğrenilmemiş
sayılır.

⚠️ **Zararsız ama körelmiş.** O iki tipte model uydurma sayı üretiyor,
guard yakalıyor, sistem şablona düşüyor. Şablon doğru — düz ama yanlış
değil. Kullanıcıya çöp gitmiyor.

**Çözüm yeni eğitim turu DEĞİL, daha fazla eşsiz örnek.** Ölçüm noktası
sıklaştırılıp (30 gün → 15) ufuk uzatılırsa (2 → 3 yıl) bu iki tipin
örnek sayısı birkaç katına çıkar. Bir sonraki tur ancak o zaman anlamlı.
