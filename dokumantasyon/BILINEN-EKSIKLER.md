# Bilinen Eksikler

> Bu dosya, **bilerek** ertelenmiş işleri tutar. Her madde ne olduğunu, neyi
> engellediğini ve ne zaman çözülmesi gerektiğini söyler. Amaç, bir eksiğin
> "unutulmuş" ile "ertelenmiş" arasındaki farkı kaybetmemesi.
>
> Son güncelleme: 2026-08-09 · Faz 7 · Kimlik doğrulama + finans para metriği

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
Sözleşme açıldığında `tedarikci_siparis_sayisi` eklenmeli.

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

## 8. 🔴 Finansın iş değeri ÖLÇÜLDÜ ve ÇIKMADI

Faz 7'de `app/domain/finance/para_metrigi.py` yazıldı: stoktaki para
metriğinin finanstaki karşılığı. Sonuç, stoktakinin aksine **olumsuz**.

`kucuk_nalbur_dukkani`, 1 yıl, aylık inceleme:

| politika | toplam maliyet | batak zararı | takip maliyeti | marj kaybı |
|---|---|---|---|---|
| taban (hiçbir şey yapma) | 228.696 TL | 197.945 | 0 | 0 |
| vasat (30 günü geçeni ara) | 232.413 TL | 186.745 | 18.300 | 0 |
| kural_motoru | 255.725 TL | 195.328 | 11.550 | 21.699 |

İki cümlelik özet: **kural motoru vasat politikadan %10 pahalı, vasat
politika ise hiçbir şey yapmamaktan %1,6 pahalı.** Yani bu etki modelinde
tahsilat çabası kendini zar zor çıkarıyor, seçici olmak ise marj kaybı
üretiyor.

**Bu sonuç neden yine de değerli:** ölçüm dört gerçek kusur buldurdu
(tahsilat oranının paydası, karşılık eşiğinin tabanı, limit kesintisinin
kademesizliği, limitin geri açılmaması). Dördü de düzeltildikten SONRAKİ
sayı bu.

⚠️ **Sonucun en zayıf yeri etki modelinin kendisi.** Stok simülasyonunda
politikanın sonucu fizikle belirlenir; tahsilatta "müşteriyi aradın, ne
oldu?" sorusunun cevabı varsayım. Parametreler
`para_metrigi.py`'nin başında tek yerde ve `duyarlilik_analizi_calistir`
sonucun `TAKIP_MALIYETI_TL`'ye bağımlılığını gösteriyor.

**Ne yapılmalı:** üç seçenek var ve karar verilmedi.

1. Etki modeli sahadan kalibre edilmeli (gerçek tahsilat kayıtları) —
   şu anki sayılar makul kabuller, ölçüm değil.
2. Kural motorunun finanstaki değeri maliyet düşürmek değil **iş gücü
   tasarrufu** olabilir: 122 arama yerine 77 arama, üstelik hangi
   müşterinin aranacağı gerekçesiyle. Bu ayrı bir metrik ister.
3. Kurallar gerçekten zayıf olabilir. Limit düşürme kolu, marj kaybı
   ürettiği için net zararlı çıkıyor — kaldırılıp yeniden ölçülmeli.

**Engellediği:** finans için "%7,6" gibi bir satış cümlesi YOK. Stok
tarafındaki iddia yerinde duruyor, finansa taşınamaz.

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

## 12. 🔴 A1 sonucu: iş gücü iddiası da tutmuyor

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
