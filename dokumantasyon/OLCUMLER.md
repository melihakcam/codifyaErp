# Ölçümler

> Bu dosya proje boyunca alınan **sayısal ölçümleri** biriktirir. Amaç: Faz 4-5'te
> "eğitim işe yaradı mı", "hedefleri tutturduk mu" sorularını tahminle değil
> kayıtla cevaplamak.
>
> Yeni ölçüm eklerken **eskisini silme** — karşılaştırma ancak geçmiş kalırsa
> mümkün.

---

## B2.1 · Model üretim hızı (2026-07-30)

**Neden ölçülüyor:** Görev dosyası B2.1'in kabul ölçütü. Bu sayı Faz 4'te
mimari kararları belirliyor — gecelik iş bütçesi ve tepe RAM hedefi buna
dayanıyor. Ölçülmezse sonradan tahmin etmek zorunda kalınır.

### Ortam

| | |
|---|---|
| İşlemci | Intel Core Ultra 7 155H (16 çekirdek / 22 iş parçacığı) |
| RAM | 15,5 GB |
| GPU | yok (CPU çıkarımı) |
| İşletim sistemi | Windows 11 |
| **İşlemci üst sınırı** | **%60** (güç planı ile sınırlandı — ısınma endişesi) |
| Model | `qwen2.5:1.5b-instruct` (986 MB, Ollama) |
| Ölçüm kaynağı | Ollama'nın kendi `eval_count` / `eval_duration` alanları |

⚠️ İşlemci %60'la sınırlı olduğu için bu sayılar **kötümser**. Sınır kaldırılırsa
daha hızlı olur. Faz 4 planlamasını bu güvenli sayılarla yapmak bilinçli.

### İş parçacığı sayısı / hız eğrisi

Aynı istem, `num_predict=100`, model bellekte:

| iş parçacığı | token/sn | 4'e göre | not |
|---|---|---|---|
| 2 | 13,1 | −42% | |
| **4** | **22,4** | — | **seçilen ayar** |
| 8 | 26,4 | +18% | |
| 16 | 32,1 | +43% | en hızlı |
| 22 | 25,3 | +13% | **16'dan yavaş** |

**22 iş parçacığı 16'dan yavaş.** Core Ultra 7 155H'de üç tip çekirdek var
(performans / verimlilik / düşük güç); hepsi birden kullanılınca hızlı
çekirdekler yavaşları bekliyor. "Daha çok çekirdek = daha hızlı" bu işlemcide
geçerli değil.

### Seçilen ayar: `LLM_IPLIK_SAYISI=4`

En hızlı ayar değil, **bilinçli olarak** seçilmedi:

| iplik | gerekçe süresi (~220 token) | gecelik iş (25 gerekçe) |
|---|---|---|
| 4 | 9,8 sn | **~4,1 dakika** |
| 16 | 6,9 sn | ~2,9 dakika |

16'ya çıkmak gecelik işi yalnızca **1,2 dakika** kısaltıyor — gece, kimse
başında değilken çalışan bir iş için. Buna karşılık dört kat fazla çekirdek
yükü ve ısı demek. Geliştirme makinesi tek ve yedeği yok; kazanç riski
karşılamıyor.

Ayar `.env`'de: ısınma sorun olmazsa yükseltilebilir, hiçbir kod değişikliği
gerekmez.

### Hedeflerle karşılaştırma

| Ölçüt | Hedef | Ölçülen | Durum |
|---|---|---|---|
| Bir gerekçe cümlesi | ~6-8 sn (yol haritasının tahmini) | 9,8 sn | ✅ tahmine yakın |
| Gecelik tarama | < 10 dakika | ~4,1 dakika | ✅ iki kat pay |
| Tepe RAM | < 4 GB | ölçülmedi | ⬜ Faz 4 |
| İlk token gecikmesi | — | ölçülmedi | ⬜ B3.5 |

Model yükleme süresi ilk çağrıda **~3,2 sn**, sonraki çağrılarda ~0 (Ollama
modeli bellekte tutuyor). Gecelik işte bu maliyet bir kez ödeniyor.

### Yan bulgu: ilk çıktı sayı uydurdu

İlk denemede, basit bir istemle:

> *"Stok kararım: Kirmizi Tugla için **35** adet ek satışı yapar."*

İsteme verilen sayılar 42, 12, 270, 1200 idi. **35** hiçbir yerde yok.

Bu, mimarinin birinci kuralının (*"LLM asla sayı üretmez"*) neden var olduğunun
canlı kanıtı — ilk çağrıda, kendiliğinden çıktı. `35` sayısı
`izinli_sayilar()` kümesinde olmadığı için B2.5'teki guard bunu reddedecek.

İsteme *"yeni sayı üretme"* eklenip sayılar etiketli verilince uydurma
kayboldu. Ama bu bir garanti değil, yalnızca olasılık düşürme — guard bu
yüzden zorunlu.

---

## B2.2 · Şema zorlamalı çıktı (2026-08-01)

**Kabul ölçütü:** 20 ardışık çağrının 20'si de geçerli JSON dönmeli.

### Sonuç: 20/20 ✅ — hepsi **ilk denemede**

| | |
|---|---|
| Geçerli JSON | **20/20** |
| İlk denemede başarılı | **20/20** (yeniden deneme hiç gerekmedi) |
| Toplam süre | 37,2 sn |
| Çağrı başına | 1,9 sn |
| Dağılım | 14 router + 6 gerekçe |

Yedek plan (llama.cpp GBNF grammar) **gerekmedi** — Ollama'nın `format`
parametresine düzleştirilmiş JSON şeması geçirmek yeterli oldu.

### ⚠️ Şema biçimi garanti eder, anlamı etmez

Yirmi çıktının hepsi kusursuz JSON'du. İçerik ise değildi:

```
#17  "1200 adet yeniden siparis..."          eksik cümle
#18  "163..."                                UYDURMA SAYI
#19  "42 + 615 - 1200 = 397..."              UYDURMA + aritmetik
#20  "1976-03-14T13:44:00Z..."               RASTGELE TARİH
```

`163`, `397` ve o tarih isteme verilen hiçbir sayıda yok. Şema modeli JSON
yazmaya zorluyor; **ne yazacağını** zorlayamıyor.

Bu, B2.5'teki guard'ın neden pazarlık konusu olmadığının ikinci kanıtı
(birincisi B2.1'deki `35`).

Not: gerekçe istemi kasıtlı olarak sadeydi — bu adımda biçim ölçülüyordu,
kalite değil. B2.4 sistem promptu, örnek cümle ve sayı etiketleme ekleyecek.
Kalite artacak ama **garanti olmayacak.**

### Ön bulgu: router doğruluğu ~11/14

Resmî taban çizgi **değil** (o B2.3'te, 30 dengeli soruyla). Yön veriyor:

| Soru | Seçilen | Doğru mu |
|---|---|---|
| "Boya kategorisinde stoğu azalan var mı?" | `kritik_stok_sorgula` + `{kategori: boya}` | ✓ |
| "T-0014 tedarikçisinin performansı nasıl?" | `tedarikci_performansi_sorgula` | ✓ |
| "Yılmaz Yapı zamanında teslimat yapıyor mu?" | `gecelik_ozet_sorgula` | ✗ |
| "Kuyrukta ne var?" | `genel_stok_durumu_sorgula` | ✗ |
| "Dün gece ne bulundu?" | `genel_stok_durumu_sorgula` | ✗ |

Model **açık** ifadelerde iyi ("kritik stok", "performansı nasıl"), **dolaylı**
ifadelerde takılıyor ("kuyrukta ne var", "dün gece ne bulundu"). Üç hatanın
üçü de bu sınıfta.

B2.3'te bu gözlem işe yarayacak: taban çizgi soru seti açık ve dolaylı
ifadeleri **dengeli** içermeli, yoksa sayı yanıltıcı çıkar.

---

## B2.3 · Router doğruluğu — TABAN ÇİZGİ (2026-08-01)

**LoRA eğitiminden ÖNCE.** Faz 3'te (B3.5) aynı script aynı soru setiyle
yeniden koşturulup bu sayılarla karşılaştırılacak. Bu satırları silmeyin.

Ölçüm: `uv run python -m training.eval.router_taban`
Soru seti: `training/eval/router_taban_sorulari.jsonl` (30 soru, **elle
yazıldı** — Kişi A'nın otomatik ürettiği eğitim verisinden bilinçli olarak
ayrı; aynı şablonlardan türeyen bir test seti, modelin şablonu ezberlemesini
"başarı" diye ölçerdi)

### ⚠️ Ölçüm deterministik yapıldı — önceki sayılar geçersiz

İlk üç koşu sırasıyla **%73,3 · %76,7 · %70,0** verdi. Aynı soru seti, aynı
model, aynı kod. Sebep: varsayılan sıcaklık 0,2, yani model her koşuda biraz
farklı davranıyor.

**7 puanlık gürültü, taban çizginin tüm amacını yok ediyordu.** LoRA sonrası
"%70 → %78" görsek bunun eğitimden mi rastgelelikten mi geldiğini
söyleyemezdik.

Düzeltme: ölçüm `sicaklik=0.0` + `tohum=42` ile koşuyor. Model açgözlü
(greedy) üretim yapıyor, aynı girdiye aynı cevabı veriyor. Doğrulandı — iki
ardışık koşu **birebir aynı** sonucu verdi.

Bu "daha iyi" bir ayar değil, **tekrarlanabilir** bir ayar. Üretimde
kullanılmıyor; orada çeşitlilik zararsız.

### Sonuç (deterministik)

Ham sonuçlar: `training/eval/router_taban_sonuc.json`. B3.5'te puanlama
mantığı değişirse ölçüm modeli tekrar çalıştırmadan yeniden puanlanabilsin
diye saklanıyor.

| Ölçüt | Değer | Faz 5 hedefi |
|---|---|---|
| **Araç doğru** | **21/30 · %70,0** | — |
| **Araç + parametre tam eşleşme** | **20/30 · %66,7** | **> %95** |
| Şema hatası (yönlendirilemedi) | 2 | 0 |
| Uydurma parametre | 0 | 0 |
| Çöküş (tek araca yığılma) | yok — en sık araç %21 | < %40 |
| Tekrarlanabilirlik | ✅ iki koşu birebir aynı | — |

Hedefle arada **28 puan** var. LoRA'nın kapatması gereken mesafe bu.

> **Parametre adı `sku_id`** (önceden `sku_adi`). Eğitim verisinde bu alan
> ürün adını değil SKU kodunu taşıyordu; Kişi A ile birlikte adlandırma
> düzeltildi (2026-08-02). Soru setindeki beklenen değerler yine de **her iki
> biçimi de** kabul ediyor — model ad da üretse kod da üretse ölçüm geçerli
> kalsın diye.

### Stile göre

| stil | doğru | oran |
|---|---|---|
| açık | 10/12 | %83 |
| dolaylı | 8/13 | %62 |
| günlük dil | 3/5 | %60 |

Beklenen yönde: ifade ne kadar dolaylı/serbestse doğruluk o kadar düşüyor.

### Araca göre — asıl bulgu

| araç | doğru | eğitim verisinde kaç örnek |
|---|---|---|
| `gecelik_ozet_sorgula` | 3/3 | 44 |
| `genel_stok_durumu_sorgula` | 2/2 | **10** |
| `kritik_stok_sorgula` | 3/5 | 171 |
| **`olu_stok_sorgula`** | **1/5** | **162** |
| `onay_kuyrugu_sorgula` | 4/5 | **12** |
| `siparis_onerisi_sorgula` | 4/5 | **2.000** |
| `tedarikci_performansi_sorgula` | 4/5 | 976 |

Eğitim verisi sütunu Kişi A'nın **dengeleme sonrası** sayıları
(2026-08-02). `olu_stok_sorgula` üç ardışık deterministik koşuda da 1/5 —
gürültü değil, sabit bir zayıflık.

**Sekiz hatanın dördü tek bir araçta.** Model "ölü stok"u (satılmayan,
hareketsiz, fazla mal) "kritik stok"la (azalan, tükenen, eksik mal)
karıştırıyor. İkisi de "stok sorunu" ama iş anlamı **zıt**.

Yanlış yönlendirilenler:

```
"Ölü stok durumundaki ürünleri listeler misin?"  -> kritik_stok      (açık soru!)
"Çimento kategorisinde hareketsiz ürün var mı?"  -> şema uyumsuz
"Rafta bekleyip duran ürünleri görebilir miyim?" -> onay_kuyrugu
"tasfiye onerlen urun var mi"                    -> kritik_stok
"Neyin acilen sipariş edilmesi gerekiyor?"       -> siparis_onerisi
"Demir profil için ne ısmarlayalım?"             -> kritik_stok
"t-0007 gecikiyomu"                              -> gecelik_ozet
"Sistem neyi bana sordu?"                        -> genel_stok_durumu
```

İlk satır dikkat çekici: soruda **"ölü stok" kelimesi birebir geçiyor** ve
model yine kritik stoğa yönlendirdi. Bu, few-shot prompt'un bu ayrımı
öğretemediğini gösteriyor — LoRA'nın somut olarak çözmesi gereken şey.

### ⚠️ Eğitim verisi dengesizliği — LoRA öncesi çözülmeli

Kişi A'nın Drive'daki router eğitim verisi bağımsız olarak incelendi
(2026-08-02). Araç dağılımı:

| araç | train | val | test |
|---|---|---|---|
| `siparis_onerisi_sorgula` | **41.886** (%95,6) | 5.902 | 4.212 |
| `tedarikci_performansi_sorgula` | 1.325 | 160 | 165 |
| `kritik_stok_sorgula` | 256 | 33 | 26 |
| `olu_stok_sorgula` | 240 | 21 | 27 |
| `gecelik_ozet_sorgula` | 66 | 5 | 9 |
| `onay_kuyrugu_sorgula` | **14** | 1 | 4 |
| `genel_stok_durumu_sorgula` | **11** | 2 | 1 |

**En sık / en seyrek = 3808 kat.**

Bu veriyle eğitilen model "her şeye `siparis_onerisi` de" davranışına
çökebilir. Tehlikeli olan: **val/test bölmeleri de aynı dengesizlikte**, yani
hep aynı cevabı veren bir model o setlerde **%95 doğruluk** gösterir. Rakam
mükemmel görünür, router çalışmaz.

Bu çarpıklığı görebilecek tek ölçüm **dengeli olan bu taban çizgi seti**
(30 soru, 7 araca eşit dağılmış). Bu yüzden `router_taban.py`'ye bir
**çöküş dedektörü** eklendi: model dengeli bir sette tek araca %40'tan fazla
yığılırsa açıkça uyarı basıyor. "Doğruluk düştü" ile "model ayrım yapmayı
bıraktı" farklı sorunlar, karıştırılmamalı.

Kök sebep yapısal, bir hata değil: `siparis_onerisi` 2.000 SKU'dan
üretiliyor, `kritik_stok` yalnızca ~8 kategoriden. Varlık havuzları farklı
büyüklükte.

**ÇÖZÜLDÜ (2026-08-02).** Kişi A `router_verisini_dengele()` ekledi: baskın
araç 2.000'e alt örnekleniyor. Bağımsız olarak doğrulandı — dengesizlik
**3400x → 200x**, sızıntı hâlâ yok, golden set artık **7/7 aracı** temsil
ediyor (önce 2/7'ydi).

**Kalan sınır:** alt örnekleme tavanı indiriyor, tabanı yükseltmiyor.
`genel_stok_durumu_sorgula` (10 satır) ve `onay_kuyrugu_sorgula` (12 satır)
hâlâ çok ince. Bu iki aracın doğal cümle çeşitliliği sınırlı; zorlamak tekrar
riski taşıyor. **Çözüm eğitim tarafında (B3.3): sınıf ağırlıklı örnekleme.**
Kişi B'nin kararı ve sorumluluğu.

### B3.5'te bakılacak

1. Genel doğruluk %73,3'ten ne kadar yükseldi? (hedef > %95)
2. **`olu_stok_sorgula` 1/5'ten kurtuldu mu?** Eğitimin işe yarayıp
   yaramadığının en keskin göstergesi bu — hem taban çizgide en zayıf nokta,
   hem eğitim verisinde yalnızca 240 örneği var.
3. **Çöküş dedektörü ne diyor?** Dengesizlik düzeltilmeden eğitilirse burası
   uyarı basmalı.
4. Günlük dil (%60) ile açık dil (%92) arasındaki fark kapandı mı?
5. Uydurma parametre 0'a indi mi?

## B3.5 · LoRA sonrası ölçüm

⬜ Henüz ölçülmedi. Aynı 30 soruluk set yeniden koşturulup B2.3 ile
karşılaştırılacak. Ayrıca token/sn, ilk token gecikmesi, tepe RAM.

## B2.4 · Gerekçe üretim kalitesi (2026-08-02)

| | |
|---|---|
| Model | `qwen2.5:1.5b-instruct` (0,92 GB) |
| Ayar | `sicaklik=0.0`, `tohum=42`, `iplik=4` |
| Örneklem | 10 gerçek karar (5 sipariş / 3 tasfiye / 2 aksiyon yok) |
| Kaynak | `stok_karari_uret()` — Kişi A'nın gerçek motoru, simülasyon dünyası |

### Sayısal sonuç

| ölçü | değer |
|---|---|
| guard'dan geçen | **10/10** |
| şablona düşen | 0 |
| ortalama süre | **6,5 sn** |
| toplam süre | 64,8 sn |

### İstem üç kez düzeltildi — ölçüm bunu ölçtü

| sürüm | guard | gerçekte ne oldu |
|---|---|---|
| 1. istem veri listesiyle bitiyor | 7/10 "geçti" | ⚠️ **0/10 kullanılabilir** — model istemi geri yazdı |
| 2. `GEREKÇE:` işareti + few-shot | 3/3 | cümle geliyor ama veri dökümü, oranlar `0,90` |
| 3. sayı listesi daraltıldı, oran %, ad kaldırıldı | 10/10 | kullanılabilir metinler |

**1. sürümdeki tuzak kaydedilmeye değer:** guard 7/10 "geçti" dedi ama
metinlerin hiçbiri gerekçe değildi — model istemi olduğu gibi geri yazmıştı ve
echo edilen sayılar zaten izinli sayılardı. **Guard sayıyı denetler, metnin
gerekçe olduğunu denetlemez.** Bu sayı tek başına okunursa yanıltır.

### Guard'ın iki kör noktası — gerçek örneklerle

Ölçüm bunları teorik değil, gözlemlenmiş olarak veriyor:

**1. Doğru sayı, yanlış cümle.** (#2)

> "Son hareketten bu yana geçen günlerde **216 adet tasfiye edilmiştir**."

`216` = son hareketten bu yana geçen **gün** sayısı. Guard geçirdi, çünkü 216
izinli. Adet olarak yazılması yanlış.

**2. Sayı doğru, mantık ters.** (#10)

> "...232 adede inerek 656,57 adetlik yeniden sipariş noktasının **üstüne
> ulaştı**."

232 < 656,57, yani **altına** düştü — karar tipi de `stok.siparis`. Model
yönü ters yazdı. Her iki sayı da izinli olduğu için guard sessiz kaldı.

**3. Özel adları bozma.** (2. sürümde görüldü, isteme ad koymayarak çözüldü)

"Astar Boya" → *starboy* · "İzocam" → *isyancı yalıtım levhası*

Ad artık isteme konmuyor; şablon adı yazmaya devam ediyor (deterministik,
bozma riski yok).

### Nitelik değerlendirmesi (insan okuması)

| | sayı | örnek |
|---|---|---|
| anlaşılır, mantığı doğru | 4 | #6, #7, #8, #9 |
| anlaşılır ama kusurlu | 4 | #2 (216 adet), #4, #5, #10 (yön ters) |
| anlamsız | 2 | #1, #3 — ikisi de tüm değerleri sıfır olan `aksiyon_yok` |

Kalan bozukluklar dil bilgisi düzeyinde: `%90'ye` (→ `%90'a`), "talep ...
boyunca", "adede inerek ... göstermektedir".

### Sonuç

Bu, **1.5B taban modelin Türkçe tavanı**. İstem mühendisliğiyle 0/10'dan
buraya gelindi; kalan kusurlar dil bilgisi ve muhakeme kusurları, istemle
çözülmez. Faz 3'teki LoRA eğitimi (Kişi A'nın 50.050 etiketli gerekçesi)
tam olarak bunun için var.

**Karar yolu etkilenmiyor:** gerekçe yanlış yazılsa bile karar, sayılar ve
politika sonucu kural motorundan geliyor. En kötü durumda şablona düşülür.

### B3.5'te bu ölçüm tekrarlanacak

Aynı 10 karar, aynı tohum, eğitilmiş modelle. Bakılacaklar: `%90'ye` gibi ek
hataları düzeldi mi, yön hatası (#10) kayboldu mu, sıfır değerli kararlarda
(#1, #3) anlamlı cümle kuruluyor mu.

## B2.4 · İkinci ölçüm — örnek başına karar tipi (2026-08-02)

Birinci ölçümdeki iki kusur (`aksiyon_yok`'ta anlamsız metin, `#10`'da ters
yön) hedeflenerek üç değişiklik yapıldı. Aynı 10 karar, aynı tohum.

### Değişiklikler ve tek tek etkileri

**1. Anlatacak sayısı olmayan kararlarda model hiç çağrılmıyor.**

İki karar (`#1`, `#3`) tüm sayıları sıfırdı: talep 0, stok 0, ROP 0. Modelden
"hiçbir şey yok" durumundan cümle istemek, olmayan bir **sebep** uydurmasını
davet ediyordu:

> "Bu durum, stok yönetimi kurallarını taklit eden bir durumdur."

Guard yakalayamaz — uydurulan şey sayı değil. Artık `anlatilacak_sayi_var_mi()`
bu kararları doğrudan şablona yönlendiriyor. **Model 2 kez daha az çalışıyor.**

**2. Kararın yönü modele söyleniyor, hesaplatılmıyor.**

Birinci ölçümde model `232 < 656,57` karşılaştırmasını yapamamış ve
"noktasının ÜSTÜNE ulaştı" yazmıştı. Artık isteme hazır bir satır giriyor:

```
durum: kullanılabilir stok yeniden sipariş noktasının ALTINA düştü
```

Yön zaten kural motorunun kararından belli. 1.5B modelden aritmetik beklemek
yerine sonucu vermek hem doğru hem ucuz. **Yön hatası kalmadı.**

**3. Her karar tipine YALNIZCA kendi örneği gösteriliyor.**

Ara denemede üç örnek birden verildi ve sonuç **daha kötü** oldu: model
örnekleri harmanladı, sipariş kararının gerekçesi "tasfiye değerlendirilmeli"
diye bitti, bir diğeri "sipariş açmaya gerek yoktur" dedi — kararın tam
tersi. Tek örneğe inince karışma bitti.

Bu ara adım kaydedilmeye değer: **few-shot örnek eklemek her zaman
iyileştirmiyor.** Örnekler birbirine yakın biçimdeyse model aralarında sızıntı
yapıyor.

### Sonuç

| ölçü | 1. ölçüm | 2. ölçüm |
|---|---|---|
| guard'dan geçen | 10/10 | 8/10 (+ 2 şablon, bilinçli) |
| ortalama süre | 6,5 sn | **5,5 sn** |
| ters yön hatası | 1 (`#10`) | **0** |
| anlamsız metin | 2 (`#1`, `#3`) | **0** |
| örnek sızıntısı | — | 0 |
| uydurma ürün adı | 0 | 0 |

Süre düştü çünkü istem kısaldı (üç örnek yerine bir) ve iki karar modele hiç
gitmiyor.

### Kalan kusurlar

Hepsi dil bilgisi düzeyinde, olgusal hata değil:

- "hedef servis seviyesi %90 **oluyor**" — zayıf fiil
- "%85 olan sipariş öneriliyor" (`#8`) — devrik
- `#10`'un son cümlesi dolgu

Bunlar istemle çözülmez; **1.5B taban modelin Türkçe tavanı**. Faz 3'teki LoRA
eğitimi bunun için var.

### Not: şablonun kendi kusuru

`#1` ve `#3` şablona düştüğünde çıkan cümle:

> "kullanılabilir stok 0 adet ve yeniden sipariş noktasının üzerinde"

ROP da 0 olduğu için teknik olarak doğru ama garip okunuyor. Şablon metni
`sablon_gerekce()` içinde, düzeltilmesi ucuz — B2.4 kapsamı dışında bırakıldı.
