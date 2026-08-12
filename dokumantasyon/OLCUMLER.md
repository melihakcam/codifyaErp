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

## B2.4 · Üçüncü ölçüm — örnek cilası + cümle kırpma (2026-08-02)

İkinci ölçümde kalan kusur dil bilgisi düzeyindeydi: zayıf fiiller, devrik
cümleler, dolgu üçüncü cümle. İki değişiklik yapıldı.

### 1. Örnek cümleler iyileştirildi

Ölçümün en net bulgusu: **model örneği neredeyse kelimesi kelimesine
kopyalıyor.**

```
ornek     : "elde kalan 12 adet, birim maliyeti 225,62 TL uzerinden
             2.707,43 TL'lik sermayeyi bagliyor"
cikti #5  : "elde kalan  6 adet, birim maliyeti 312,94 TL uzerinden
             1.877,61 TL'lik sermayeyi bagliyor"
```

Tasfiye çıktıları iyiydi çünkü tasfiye örneği iyiydi; sipariş çıktıları zayıftı
çünkü sipariş örneğinin sonu zayıftı. Örnek yeniden yazıldı:

> **eski:** "...Tedarik süresi boyunca stoksuz kalmamak için 1.200 adet
> sipariş öneriliyor."
> **yeni:** "...Günlük 42 adetlik tüketim hızıyla eldeki miktar 12 günlük
> tedarik süresini karşılamadığından 1.200 adet sipariş açılması öneriliyor."

Sonuç doğrudan yansıdı — `#6`, `#7`, `#8` bu kalıbı aldı.

**Genel ilke: few-shot örneği bir talimat değil, bir kalıptır. Ne yazarsan onu
alırsın.** Örneği iyileştirmek bu aşamada en ucuz ve en güvenilir kaldıraç.

### 2. Üçüncü cümle kırpılıyor

"EN FAZLA 2 cümle" talimatı **ve** `num_predict=160` sınırı birlikte bile
yetmedi; model kuralı kabul edip yine de dolgu cümle ekledi:

> "...60 adet sipariş açılması öneriliyor. **Bu durumda hedef servis seviyesi
> %90'ı karşılayacak şekilde bir sipariş oluşturuluyor.**"

Modele yalvarmak yerine `ilk_cumleleri_al()` ile kırpıldı. Deterministik,
bedava, geri tepmesi yok.

⚠️ Cümle bölme Türkçede naif `split(".")` ile yapılamaz — `2.707,43` binlik
ayracı da nokta. Desen noktadan sonra **boşluk + büyük harf** arıyor;
`2.707,43` ve `12.5mm` bölünmüyor. Üçü de teste bağlı.

Kırpma guard'dan **önce** yapılıyor: atılan cümlede uydurma sayı varsa zaten
kullanıcıya gitmiyor, guard'ın onu görüp iyi olan ilk iki cümleyi şablona
düşürmesi gereksiz kayıp olurdu.

### Sonuç — üç ölçümün karşılaştırması

| ölçü | 1. | 2. | 3. |
|---|---|---|---|
| ortalama süre | 6,5 sn | 5,5 sn | **5,1 sn** |
| ters yön hatası | 1 | 0 | 0 |
| anlamsız metin | 2 | 0 | 0 |
| örnek sızıntısı | — | 0 | 0 |
| dolgu 3. cümle | 2 | 5 | **0** |
| uydurma ürün adı | 0 | 0 | 0 |

### Nitelik (insan okuması)

| | sayı |
|---|---|
| akıcı, mantığı doğru | 6 |
| anlaşılır, hafif devrik | 2 (`#9`, `#10`) |
| şablon (bilinçli) | 2 (`#1`, `#3`) |
| yanlış / anlamsız | **0** |

Kalan kusurlar: `#9`'da "önerilen sipariş miktarı 32 adet **öneriliyor**"
(fiil tekrarı), `#10`'un ikinci cümlesi devrik. İkisi de anlaşılıyor.

### Buradan sonrası

Bu nokta **1.5B taban modelin tavanı** sayılmalı. Bugün 0/10 kullanılabilir
metinden buraya gelindi ve son iki turda kazanç belirgin şekilde azaldı.
Kalan devrik cümleler istemle değil, eğitimle düzelir.

B3.5'te aynı 10 karar aynı tohumla tekrarlanacak; karşılaştırma tabanı
bu tablodur.

## B2.6 · Gecelik tarama suresi (2026-08-02)

Gorev dosyasinin olcutu: **"2.000 SKU'luk gecelik tarama < 10 dakika."**

| | |
|---|---|
| Karar ureteci | `stok_karari_uret()` — Kisi A'nin gercek motoru |
| Gerekce ureteci | `llm_gerekce_ureteci()` — B2.4, guard'li, gercek LLM |
| Model | `qwen2.5:1.5b-instruct`, `iplik=4`, `sicaklik=0.0`, `tohum=42` |
| Gerekce ust N | 25 (`.env`'deki gercek deger) |
| Veritabani | SQLite, WAL, `foreign_keys=ON` |

⚠️ Sablonla olcmek yalanci sonuc verirdi: sablon aninda uretiyor, LLM ~6,7 sn.
Bu olcum bastan sona gercek zincirle yapildi.

### Sonuc

| olcu | deger |
|---|---|
| taranan karar | 2.000 |
| hata / atlanan | **0** |
| onay kuyruguna giren | 743 |
| gerekce uretilen | 25 |
| gerekce atlanan | 1.975 |
| icgoru yazilan | 26 |

| sure | |
|---|---|
| karar | 152,2 sn |
| gerekce | 166,6 sn |
| **toplam** | **318,8 sn = 5,31 dakika** |
| hedef | 10 dakika |
| **pay** | **4,69 dakika** ✅ |

### Mimarinin iki iddiasi artik olculu

**1. "Karar milisaniyelerde cikar, gerekce saniyeler surer."**

```
karar basina    :   76,1 ms
gerekce basina  : 6.700   ms
                  --------
fark            :      88 kat
```

Kural motoru + politika + veritabani yazimi bir karar icin 76 milisaniye.
Ayni karar icin Turkce cumle yazmak 6,7 saniye. Bu yuzden `KosuOzeti` iki
sureyi ayri tutuyor ve `commit()` iki kez atiliyor — kararlar gerekce
beklemeden gorunur oluyor.

**2. "Gerekce yalnizca ust N icin uretilir."**

1.975 karar icin gerekce uretilmedi. Uretilseydi:

```
2.000 x 6,7 sn = 13.400 sn = 3 saat 43 dakika
```

Hedefin **22 katı**. Ust-N kısıtı bir optimizasyon degil, isin calisabilmesinin
on sarti. Kalan kararlar gerekcesiz kaydediliyor; birine bakilmasi gerekirse
gerekce sonradan uretilebiliyor.

### Sinirlar

- Tek makine, tek Ollama ornegi, 4 iplik. Paralellestirme denenmedi.
- Simulasyon dunyasinin yuklenmesi (19,0 sn) taramaya **dahil degil**: dunya
  bir kez yukleniyor ve gercek ERP'de veri zaten veritabaninda olur.
- 743 kararin onay kuyruguna dusmesi `shadow` modun beklenen davranisi.

### B3.5'te tekrarlanacak

Egitilmis model daha uzun/kisa cumle uretirse `gerekce basina` degisir.
Karsilastirma tabani: **76,1 ms / 6,7 sn / 5,31 dakika**.

## B3.2 · Boru hatti provasi — 100 ornek (2026-08-03)

Gorev dosyasinin olcutu: hattin **ucdan uca calistigini** kanitlamak.
Kalite BEKLENMIYOR.

| | |
|---|---|
| Ortam | Colab, Tesla T4, 14,6 GB VRAM |
| Taban model | `unsloth/Qwen2.5-1.5B-Instruct`, 4-bit |
| LoRA | `r=16`, `alpha=32`, tum dikkat + MLP (7 modul) |
| Egitim | 100 ornek, 30 adim, lr 2e-4, seed 42 |

### Sonuc

| olcu | deger |
|---|---|
| egitilen parametre | 18.464.768 / 1.562.179.072 = **%1,18** |
| kayip (30 adimda) | 0,77 -> 0,54 -> 0,43 -> **0,39** |
| egitim suresi | 63 sn |
| LoRA boyutu | **81,4 MB** (tam model 3 GB olurdu) |
| B3.2 olcutleri | 4/4 GECTI |

Kayip duzenli dusuyor — egitim gercekten oluyor, boru hatti saglam.

### Urun adi sinavi: sonuc HENUZ GECERSIZ

Uc ornekte de ad birebir dogru kopyalandi (`Porselen Karo - Vitra`,
`Insaat Demiri 12mm - Icdas`, `Ic Cephe Boyasi - Marshall`). "starboy" yok.

⚠️ **Ama uretilen metinler hedeflerle harfi harfine ayni cikti.** Model bu uc
ornegi ezberlemis; 100 ornek + 30 adim + kayip 0,39 ile beklenen sonuc bu.

Yani cevaplanan soru *"adi kopyalayabiliyor mu"* degil,
*"ezberleyebiliyor mu"* idi. Ikisi ayni sey degil.

Dogru sinav **gorulmemis** ornekle yapilir; `gerekce_val.jsonl` bunun icin
ayrilmis. Deftere `8. Gorulmemis ornekle sinav` bolumu eklendi, B3.3'un
yaninda kosturulacak.

Bu, olcum yaparken en kolay dusulen tuzagin bir ornegi: **egitim verisinden
olcmek.** B2.4'te de benzeri olmustu (guard "7/10 gecti" demisti ama metinler
istem echo'suydu). Sayi dogru, soru yanlis.

### B3.3 icin cikan sayilar

- 100 ornek / 30 adim = 63 sn
- 40.293 ornek icin kaba tahmin: **~4-6 saat** (gorev dosyasinin 4-7 saat
  tahminiyle uyumlu)
- LoRA 81,4 MB -> checkpoint'ler Drive'da rahat siger

## B3.3 · 1. tur LoRA egitimi (2026-08-03)

| | |
|---|---|
| Ortam | Colab, Tesla T4 |
| Veri | 15.000 ornek (7.500 gerekce + 7.500 router), tek modelde |
| Ayirac | `GOREV: gerekce` / `GOREV: router` etiketi |
| LoRA | r=16, alpha=32, tum dikkat + MLP, %1,18 parametre |
| Egitim | 1 epoch, 1.875 adim, batch 8 (2x4), lr 2e-4, seed 42 |
| Sure | ~56 dakika |
| Cikti | `cikti/b33_tur1_lora/` (adapter_model.safetensors) |

### Dogrulama kaybi

| adim | dogrulama |
|---|---|
| 200 | 0,2250 |
| 400 | 0,2058 |
| 600 | 0,2065 |
| 800 | 0,1992 |
| 1000 | 0,1944 |
| 1200 | 0,1967 |
| 1400 | 0,1903 |
| 1600 | 0,1914 |
| 1800 | **0,1878** (en iyi) |
| 1875 | 0,1888 |

**"Bitti sayilir" olcutu KARSILANDI**: dogrulama kaybi dusup yatay seyre gecti.
Son deger en iyinin %0,6 ustunde -- gurultu araligi, yukselis degil.

### Ezberleme yok

```
egitim kaybi  (1875. adim) : 0,1877
dogrulama     (1875. adim) : 0,1888
```

Ikisi neredeyse ayni. Egitim kaybi dogrulamanin belirgin altina inseydi ezberleme
olurdu; burada aralik yok. Model veriyi ezberlemiyor.

### ⚠️ Iyilesme belirgin sekilde yavasliyor

```
ilk yari  (200 -> 1000)  : 0,2250 -> 0,1944   fark 0,0306
ikinci yari (1000 -> 1875): 0,1944 -> 0,1888   fark 0,0056
```

**Ikinci yari, benzer miktarda veriyle ilkinin besde birini kazandirdi.** Egri
sertce yataylasiyor.

Bu, 2. tur (35k) icin dogrudan bir uyari: kayip tarafinda buyuk kazanc
beklenmemeli. Gorev dosyasinin kurali burada devreye giriyor -- *"iyilesme yoksa
darbogaz veri miktari degil, veri kalitesi."*

### Ama kayip yanlis soru olabilir

Kayip 0,188 bize **router dogrulugunun** ne oldugunu soylemiyor. B2.3 taban
cizgisi arac dogrulugu %70,0 / arac+parametre %66,7 idi; bu egitimin ise yarayip
yaramadigi ancak ayni 30 soruluk setle olculunce anlasilir.

Gorev dosyasi da 1. turun amacini boyle tanimliyor: *"Tek oturumda biter.
**Router dogrulugunu olc.**"*

**Karar: 2. tura gecmeden once olcum yapilacak.** Egitim ucuz degil (56 dakika);
neyi kazandigini bilmeden ikincisini kosturmak korlemesine.

### Not: baslangic kaybi zaten dusuktu

Ilk kayit (25. adim) 0,2988. Bu, hedeflerin **cok kalipli** oldugunu dusundurur --
Kisi A'nin uretici sablonlari duzenli oldugu icin model dili hizla yakaliyor.
Kalipli hedef, kaybin erken yataylasmasini da acikliyor.

## B3.5 (1. tur) · Router olcumu — DUSTU, sebebi veri secimi (2026-08-03)

B2.3'un birebir ayni 30 soruluk seti, egitilmis modelle.

| olcu | taban (B2.3) | 1. tur | |
|---|---|---|---|
| arac dogrulugu | %70,0 | **%40,0** | dustu |
| arac + parametre | %66,7 | **%26,7** | dustu |
| sema hatasi | 2/30 | **8/30** | artti |
| `olu_stok_sorgula` | 1/5 | **4/5** | ⬆ iyilesti |

Secilen araclar: `kritik_stok` 9, **cozulemeyen 8**, `tedarikci` 5, `olu_stok` 4,
`siparis` 3, `sorgula` (bozuk) 1.

### Kok sebep: egitim verisi sirali alindi, rastgele degil

`veri_hazirla.py` ve defter, router dosyasinin **ilk 7.500 satirini** aliyordu.
Dosya araca gore sirali oldugu icin:

```
                                  EGITIME GIREN    TUM DOSYA
  siparis_onerisi_sorgula              6.742         41.886   %90
  tedarikci_performansi_sorgula          543          1.325
  kritik_stok_sorgula                    116            256
  olu_stok_sorgula                        99            240
  gecelik_ozet_sorgula                     0             66   SIFIR
  onay_kuyrugu_sorgula                     0             14   SIFIR
  genel_stok_durumu_sorgula                0             11   SIFIR
```

**Uc arac egitime hic girmedi.** Model hic gormedigi araci secemez; olcumde de
o uc araci hic secmedi. Taban cizgide bu uclu 9/10 dogru cevap veriyordu —
dususun buyuk kismi burada.

Dogrulayan detay: `olu_stok_sorgula` 99 ornek gordu ve **1/5 → 4/5** cikti.
Egitim calisiyor; sorun neyin ogretildigi.

### Ikinci sorun: olcum tam adil degil

B2.3 taban cizgisi Ollama'nin **JSON sema zorlamasiyla** olculmustu — model
gecersiz JSON uretemiyordu. Bu olcum ham uretim, zorlama yok. 8 sema hatasinin
bir kismi modelin degil, kurulumun farki.

Gecerli JSON uretilen 22 sorunun 12'si dogru = **%54,5**. Yine %70'in altinda
ama %40 kadar kotu degil.

Ders: **iki olcumu karsilastirirken yalnizca modeli degil, cevre kosullarini da
esitle.** Aksi halde hangi farkin neyden geldigi bilinmez.

### Kok sebebin kok sebebi

Dosyanin kendisi **3.808 kat dengesiz** (41.886 vs 11). Bu, oturumun basinda
tespit edilip Kisi A'ya bildirilmisti; `router_verisini_dengele()` eklemisti.
Ama elimizdeki `router_train.jsonl` dengelenmemis surum.

### 2. tur icin yapilacaklar

1. **Sinif agirlikli ornekleme** — her arac icin taban kota, seyrek olanlar
   tekrarlanarak. Gorev dosyasi B3.3'te bunu zaten istiyordu.
2. **Rastgele ornekleme** — sirali alma bir daha yapilmayacak.
3. **Sema zorlamasi** — olcum, taban cizgideki gibi JSON kisitiyla yapilmali.
4. Kisi A'ya sorulacak: dengelenmis router disa aktarimi var mi?

⚠️ 11 ornekli bir araci tekrarlayarak ogretmek ezberletme riski tasiyor. Gercek
cozum seyrek araclar icin **daha cesitli soru** uretmek — o Kisi A'nin tarafi.

## Duzeltme · 1. tur teshisi ve veri surumu (2026-08-03)

Iki duzeltme, ikisi de onceki bolumu tamamen gecersiz kilmiyor ama sebebi
degistiriyor.

### 1. Elimizdeki veri ESKI KOPYA

Kisi A kanitladi: `41.886 = 52.000 x (1611/2000)` — yani dosya yalnizca
SKU-train filtresinden gecmis ham veri, **dengeleme hic uygulanmamis**.
Guncel dosyasinda `siparis_onerisi_sorgula` train'de **1.633**.

Dengeleme `router_verisini_dengele()` ile `veri_bolme.py` icinde, split'ten
ONCE calisiyor. Yani dengelenmis bir disa aktarim var; bizdeki indirme
zamanlama yuzunden eski surum.

**Sonuc: 1. turun tum dagilim sayilari eski veriye ait.** Yeni veriyle
tekrarlanmali.

### 2. "Dosya araca gore sirali" teshisi yanlisti

Dogru teshis: dosya **bloklu**. Seyrek araclarin ilk gorunum satirlari:

```
arac                          adet    ilk satir   ortanca
genel_stok_durumu_sorgula       11       20.131    20.136
onay_kuyrugu_sorgula            14       20.090    20.097
gecelik_ozet_sorgula            66       20.098    43.761
olu_stok_sorgula               240          116    20.299
kritik_stok_sorgula            256            0    20.150
tedarikci_performansi          1325          215    20.538
siparis_onerisi_sorgula       41886          758    22.812
```

Uc seyrek aracin **hicbiri 20.090. satirdan once yok**. Ilk ~20.000 satir bir
uretim partisi (yalnizca 4 arac), sonrasi ikinci parti.

Ilk 7.500 satiri almak o ucunu **hicbir kosulda** yakalayamazdi. Etki ayni,
sebep farkli.

**Genel ders: bir dosyanin "karisik" oldugunu varsayma, bak.** Basit bir
"her deger tek blok mu" kontrolu bunu yakalayamadi (`sirali mi: hayir` dedi);
gercegi gosteren sey konum dagilimiydi.

### Yeni veri gelince kosulacak kontrol

`scratchpad/yeni_veri_kontrol.py` yazildi. Bakiyor:
dengeleme uygulanmis mi (2000 ust siniri), egitimde eksik arac var mi,
train/val/test sizintisi, konum dagilimi, arac basina **ozgun** soru sayisi.

Eski kopyadaki ozgunluk (cesitlilik gostergesi):

```
genel_stok_durumu_sorgula       11 ozgun /    11 satir
onay_kuyrugu_sorgula            14 ozgun /    14 satir
gecelik_ozet_sorgula            66 ozgun /    66 satir
```

Kisi A bu ucu icin `--sablon-ihrac-araclar` bayragi ve parafraz defterinde
`VARYANT_SAYISI` ayari hazirladi; 28 sablondan 12-15 varyant uretilerek gercek
cesitlilik saglanabilir. Tekrarlamaya gore cok daha iyi bir cozum.


## Guncel veri dogrulandi (2026-08-03)

Kisi A'nin parafraz turu sonrasi indirilen dosyalar `yeni_veri_kontrol.py` ile
sinandi.

```
DENGELENMIS       en cok gorulen arac 1.633  (ust sinir 2.000)
eksik arac        yok
train vs val      TEMIZ
train vs test     TEMIZ
val vs test       TEMIZ
ozgun soru        3.674/3.674  (%100)
sirali mi         EVET -- ilk-N almak TEHLIKELI
```

Router havuzu **43.798 -> 3.674** satira indi (dengeleme uygulandi).
Seyrek araclar (egitim bolumu):

```
                           once   sonra
genel_stok_durumu_sorgula    11      26
onay_kuyrugu_sorgula         14      39
gecelik_ozet_sorgula         66     155
```

Bolumler toplami Kisi A'nin verdigi sayilarla tutuyor (34 / 43 / 184).

⚠️ **Dosya hala araca gore sirali.** 1. turdaki hata bu veriyle de tekrar
ederdi; dengeli ornekleme zorunlulugunu koruyor.

### 2. tur ornekleme ayari yeniden olculdu

Havuz kuculunce 7.500 router hedefi anlamsizlasti (her seyi 2 kat tekrarlamak
olurdu):

| router hedefi | ozgun | en cok tekrar | dengesizlik |
|---|---|---|---|
| 7.500 | %38,3 | 40,0x | 1,0x |
| 3.500 | %49,0 | 19,2x | 1,0x |
| **2.000** | **%64,5** | **11,0x** | **1,0x** |
| 1.400 | %72,9 | 7,7x | 1,0x |

Denge her ayarda tam; fark ozgunlukte. **Secilen: router 2.000 (tavan 20),
gerekce 8.000.** Toplam 10.000 -- Tur 1'den (15.000) kucuk ama uc aracin hic
gorulmedigi bir 15.000'den kesinlikle iyi.


## B3.3 · 2. tur LoRA egitimi (2026-08-03, Kisi A kosturdu)

GPU kotasi doldugu icin egitim Kisi A'ya devredildi. Defter, veri ve hazirlik
betigi repodan alindi.

| | 1. tur | 2. tur |
|---|---|---|
| ornek | 15.000 | 9.993 |
| router | 7.500 (3 arac SIFIR) | 1.995 = **285 x 7 arac** |
| gerekce | 7.500 | 7.998 = 2.666 x 3 tip |
| denge | 68x + uc arac yok | **tam dengeli** |
| adim | 1.875 | 1.250 |
| sure | 56 dk | 44 dk 11 sn |

### Kayip egrisi

| adim | egitim | dogrulama |
|---|---|---|
| 200 | 0,2421 | 0,2920 |
| 600 | 0,1982 | 0,2439 |
| 1000 | 0,1822 | 0,2192 |
| 1250 | 0,1797 | 0,2134 |

Dogrulama kaybi bastan sona dustu, hic yukselmedi -- **ezberleme isareti yok**.

⚠️ **1. turun kaybiyla karsilastirilamaz.** 1. turda dogrulama 0,1888'di, bu
turda 0,2134. Daha yuksek gorunuyor ama veri degisti: 2. turda seyrek araclarin
ornekleri cok daha agirlikli ve onlar daha zor. Farkli veri kumesinde olculen
kayiplar yan yana konmaz. Karsilastirilabilir olan tek sey **router
dogrulugu**.

### Cikan hata: veri_hazirla.py ile defter arasinda varsayim uyusmazligi

`veri_hazirla.py` `karar_tipi` alanini yalnizca val/test dosyalarina koyuyordu
("boyut kucultme"), ama defterin 2. tur dengeleme kodu
`dengeli_ornekle(..., 'karar_tipi', ...)` derken egitim dosyasinda ariyordu ->
`KeyError`.

Kisi A gecici olarak istem metnindeki `karar: ...` satirindan cikardi, veri
kaybi olmadi. **Kalici duzeltme yapildi:** `karar_tipi` artik her dosyada.
Alan basina ~20 bayt, 40 bin satirda 800 KB -- dengeli orneklemenin calismasi
icin odenecek bedel bu degildi.

Ders: **ayni veriyi ureten ve tuketen iki kod parcasi varsa, aralarindaki
varsayim tek yerde yazili olmali.** Burada yazili degildi; biri alan cikardi,
digeri o alani aradi.

### Sirada

`router_taban.py --model ... --istem-bicimi egitilmis` ile taban cizgiyle
(%70,0 arac / %66,7 tam) ayni kosulda olcum. On sart: model Ollama'da olmali
(B3.4).

## B3.4 · Merge → GGUF → Ollama (2026-08-05)

B'nin GPU kotası dolduğu için ayrı, unsloth/cuda bağımlılığı olmayan bir
defter hazırlandı: `training/b34_gguf_colab.ipynb` (commit a5f1ac0). GPU'suz
Colab çalışma zamanında koşturuldu (Kişi B'nin yönlendirmesiyle Melih
çalıştırdı).

⚠️ **Klasör adı yanıltıcı:** `cikti/b33_tur1_lora` adının içinde aslında
**2. turun** adaptörü var — 2. tur kaydedilirken defterdeki değişken adı
güncellenmemiş, dosya üzerine yazılmış. Kişi B ile teyit edildi, defter buna
göre not düşüldü.

Karşılaşılan ve çözülen üç bağımsız Colab paket çakışması (GPU'suz taze
oturumda hepsi tekrar eder, sırayla):

1. **numpy ikili uyumsuzluğu** — kurulumdan hemen sonra `import torch` taze
   bir oturumda patlıyor (`numpy.dtype size changed`). Çözüm: oturumu yeniden
   başlat, tekrar çalıştır. Dosyaya dokunmuyor, yalnızca Python sürecini
   sıfırlıyor.
2. **protobuf ↔ tensorflow çakışması** — `transformers`, kullanılmayan
   TensorFlow'u içe aktarmaya çalışıp `ImportError: cannot import name
   'runtime_version'` veriyordu. Çözüm: `tensorflow`/`tensorboard` paketleri
   kaldırıldı (hiç kullanılmıyor, yalnızca PyTorch tarafı işletiliyor).
3. **torchao eski sürüm** — Colab'ın hazır gelen `torchao 0.10.0`'ı peft'in
   istediği `>0.16.0`'ın altında kalıyordu. Çözüm: `torchao` da kaldırıldı.

Üçü de kurulum hücresine kalıcı olarak eklendi
(`!pip uninstall -y tensorflow tensorflow-cpu tensorboard tensorflow-metadata torchao`),
sonraki koşularda tekrar aranmaz.

Çıktı: `codifya-tur2-q8_0.gguf` (1,53 GB, q8_0). Yerelde
`ollama create codifya-router:tur2 -f training/Modelfile` ile içe aktarıldı.

## B3.5 (2. tur) · Router ölçümü (2026-08-05)

Aynı 30 soruluk set, aynı puanlama (B2.3/1. tur ile birebir).

| | taban çizgi (B2.3) | 1. tur | **2. tur** |
|---|---|---|---|
| araç doğruluğu | %70,0 | %40 | **%73,3** |
| araç + parametre | %66,7 | — | **%66,7** |
| şema hatası | 2 | — | 4 |
| çöküş | yok | — | yok (%27, eşik %40) |

Araç seçiminde taban çizgiye göre hafif iyileşme var (%70,0 → %73,3). **Tam
doğrulukta hiç kazanım yok** (%66,7 → %66,7) — parametre çıkarma tarafı
gelişmedi. Şema hatası 2'den 4'e çıktı; bu ölçüm B2.3'teki gibi JSON şema
zorlaması olmadan (ham üretim) yapıldığından bir kısmı modelin değil, ortam
farkının sonucu olabilir (daha önce de not edilen adaletsizlik).

En zayıf araç hâlâ `tedarikci_performansi_sorgula` — dolaylı sorularda
(`Bizi kim geciktiriyor?`, `Yılmaz Yapı'nın teslimat skoru kaç?`)
`genel_stok_durumu_sorgula`ya kayıyor. `T-0031 güvenilir mi?` ve
`t-0007 gecikiyomu` şema hatası verdi.

Ham sonuçlar: `training/eval/router_lora_tur2_sonuc.json` (taban çizgi
dosyasının üzerine yazılmaması için ayrı dosyada tutuldu).

### Karar noktası

3. tur (35-55k örnek, 5-7 saat GPU + günlerce kota bekleme) için **net bir
gerekçe yok** — marjinal kazanım belirsiz, tam doğrulukta hiç ilerleme yok.
Sıradaki adım tartışılacak: 3. tura girmeden mevcut modeli (`codifya-router:tur2`)
`decisions.py`'ye bağlamak mı, yoksa veri kalitesi tarafına mı (özellikle
`tedarikci_performansi_sorgula` ve parametre çıkarma) eğilmek mi.

## SP3 · Buluşma noktası — guard reddedilme oranı (2026-08-05)

`.env` güncellendi: `LLM_MODEL_ADI=codifya-router:tur2`,
`LLM_ISTEM_BICIMI=egitilmis`. Sunucu ayağa kaldırılıp `/v1/ask` gerçek modelle
sınandı — soru doğru araca yönlendirildi (~1 sn).

Asıl doğrulanacak şey: **guard reddedilme oranı düştü mü?** Demo dünyasından
40 SKU'luk gerçek karar seti (`stok_karari_uret`) üretildi, anlatılacak
sayısı olan 35'i taban model ve eğitilmiş modelle ayrı ayrı `gerekce_uret()`
üzerinden geçirildi, `guard_sonucu` karşılaştırıldı:

| | taban model | eğitilmiş model (`tur2`) |
|---|---|---|
| guard kabul oranı (İLK ÖLÇÜM, YANLIŞ) | ~~%0 (0/35)~~ | %25,7 (9/35) |

⚠️ **DÜZELTME (2026-08-05, aynı gün):** %0 rakamı yanlıştı. Sebep betik
hatası değil, ortam hatası — **`qwen2.5:1.5b-instruct` (taban model) bu
makinede hiç indirilmemişti.** `Ayarlar(llm_model_adi="qwen2.5:1.5b-instruct")`
ile açılan her `OllamaIstemcisi` çağrısı `LLMErisilemiyor` (404, model bulunamadı)
fırlatıyordu; `gerekce_uret()` **"hiçbir koşulda hata fırlatmaz"** tasarımı
gereği bunu sessizce yakalayıp şablona düşüyordu (`app/llm/guard.py::gerekceyi_guvenceye_al`).
Yani %0, taban modelin kalitesi hakkında hiçbir şey söylemiyordu — sadece
modelin kurulu olmadığını gösteriyordu. Dört örneği "elle doğrulama" da bu
yüzden yanılttı: şablon metni gerçekten şablondu, ama nedeni "model kötü"
değil "model yok"tu.

Model indirilip (`ollama pull qwen2.5:1.5b-instruct`) **aynı 35 kararla
yeniden ölçüldü:**

| | taban model (gerçek) | eğitilmiş model (`tur2`) |
|---|---|---|
| guard kabul oranı | **%100** (35/35) | **%25,7** (9/35) |

**Gerçek sonuç önceki iddianın tam tersi: LoRA eğitimi gerekçe/guard
tarafında işleri düzeltmemiş, belirgin şekilde kötüleştirmiş.** Taban
model — uzun istem, kurallar bloğu, few-shot örnek içeren `istem_kur()`
(B2.3/B2.4'ün ayarladığı biçim) — guard'ı her denemede geçiyor. Eğitilmiş
model — kısa istem, `egitilmis_istem_kur()`, davranışın ağırlıklara
işlendiği varsayımıyla kurallar/örnek olmadan çalışıyor — 4 denemeden
3'ünde reddediliyor.

B3.5'in router bulgusuyla (tam doğruluk hiç değişmedi: %66,7 → %66,7)
birlikte okununca tablo şu: **2. tur eğitim ölçülebilir hiçbir yerde
iyileşme sağlamadı; gerekçe tarafında belirgin kötüleşme var.** Olası
sebep: eğitilmiş modelin kısa istemi, taban modelin sayı kopyalamasını
kolaylaştıran açık kuralları/örneği taşımıyor — LoRA'nın bunu ağırlıklara
yeterince işlemediği görülüyor.

**Ders:** `.env`'de bir modelin adı yanlış/eksikse (`LLMErisilemiyor`),
guard mimarisi bunu **kararı bloke etmeden** şablona düşürüyor — bu doğru
davranış (mimarinin ikinci kuralı) ama aynı zamanda bir ölçüm hatasını da
sessizce gizleyebiliyor. Ölçüm scriptleri bundan sonra modelin gerçekten
yanıt verdiğini (`ollama list` / basit bir "merhaba" isteği) **önce**
doğrulamalı.

## Faz 5 · Uçtan uca benchmark (2026-08-05)

`training/eval/benchmark.py` ile beş hedef tek raporda ölçüldü
(`codifya-router:tur2`, taban model artık gerçekten kurulu):

| Metrik | Sonuç | Hedef | Durum |
|---|---|---|---|
| router: araç+parametre tam eşleşme | %63,3 (19/30) | > %95 | ❌ KALDI |
| gerekçe: uydurma sayı (final metin) | 0/20 | 0 | ✅ GEÇTİ |
| gerekçe: Türkçe akıcılık (LLM-jüri) | 4,5/5 (4 örnek) | ≥ 4,0 | ✅ (gösterge) |
| gecelik tarama süresi (2.000 SKU) | 234,7 sn | < 600 sn | ✅ GEÇTİ |
| tepe RAM | 426 MB | < 4.096 MB | ✅ GEÇTİ |

**4 sert kapıdan 1'i (router) KALDI.** Diğer üçü rahatça geçti — performans
ve sayısal güvenlik tarafında sistem sağlam. "Uydurma sayı = 0" sonucu,
guard'ın tasarım iddiasının (hiçbir zaman hallüsinasyon sızdırmaz) ilk kez
gerçek üretim kodu (`adayi_dogrula`) ile empirik doğrulanışı.

**Sonuç: threshold moduna geçiş için gerekli koşul sağlanmadı.** Router
%63-73 bandında (ölçümden ölçüme küçük oynama var, hepsi 30 soruluk küçük
sette), hedef %95. Bu Faz 3'ün SP3 düzeltmesindeki bulguyla tutarlı:
2. tur LoRA eğitimi net bir kazanım göstermedi, gerekçe tarafında taban
modelden geriye gitti. `shadow` modda kalmaya devam — bu teknik değil,
süreç kararı (`KISI-B-GOREV.md`, Faz 5 uyarısı).

Ham sonuçlar: `training/eval/benchmark_sonuc.json`.

## ⭐ 2. turun KÖK NEDENİ — eğitim verisi modele sayı uydurmayı öğretmiş

**Bulgu: sorun eğitimin miktarında değil, eğitim verisinin kendisinde.**
Bu yüzden "daha çok epoch" ya da "3. tur" işleri **kötüleştirirdi**.

### Nasıl bulundu — üç adım, ikisi hipotezi çürüttü

**1. Kontrollü karşılaştırma (2×2).** Önceki ölçüm iki değişkeni birden
değiştiriyordu: model *ve* istem. Ayrıldığında:

| | UZUN istem (kurallar + few-shot) | KISA istem |
|---|---|---|
| taban model | **12/12** | **12/12** |
| tur2 (LoRA) | 7/12 | 3/12 |

Okuma: taban model istem biçiminden **hiç** etkilenmiyor — "kısa istem
kötü" açıklaması çürüdü. Fark modelde. Ama uzun istem tur2'yi 3→7
düzeltiyor: model, eğitimle kazanması gereken davranışı hâlâ istemdeki
açık kurallardan almaya muhtaç.

**2. Çürütülen hipotez — JSON şema zorlaması.** Kod okumasından çıkan
makul bir teori: gerekçe eğitimde **düz metin** öğretilmişti, çalışma
zamanında ise `yapilandirilmis_uret()` JSON şeması zorluyor
(router ise JSON ile eğitilmişti — asimetriyi açıklıyor gibiydi).
Sınandı:

```
A) JSON sema zorlamali (mevcut kod)     3/12
B) HAM METIN (egitimdeki bicim)         2/12
```

**Hipotez yanlış.** Zorlamayı kaldırmak iyileştirmedi. Ama B'nin
çıktıları asıl ipucunu verdi: metinler akıcı ve mantıklı, sadece
**sayılar uydurma** — ör. *"19 adet kullanılabilir olduğuna göre, 6,82
değerinin üstündeyken..."* (6,82 hiçbir yerde yok).

**3. Veri ölçümü — kök neden.** `gerekce_train.jsonl`'de hedef metindeki
sayıların istemde bulunup bulunmadığı ölçüldü:

```
incelenen egitim ornegi              : 5.000
cevapta ISTEMDE OLMAYAN sayi iceren  : 3.968   (%79,4)

en sik uydurtulan degerler:
    15,00  x886     <- rules.py::onerilen_iskonto_orani = 0.15
    30,00  x148
    92,13  x28      <- tedarikci skorlari
```

### Mekanizma

`training/veri_hazirla.py::ETIKETLER` isteme **yalnızca 5 özellik alanı**
koyuyor. Hedef metin ise `izinli_sayilar()`'ın tamamını kullanabiliyor —
tetiklenen kural değerleri (ROP, emniyet stoğu, iskonto oranı) ve aksiyon
(sipariş miktarı) dahil. Bu sayılar guard'a göre **meşru**, ama modele
hiç gösterilmiyor. Model onları ancak **uydurarak** üretebilir; 5 örnekten
4'ünde bunu yapması öğretilmiş.

Taban modelin istemi (`app/llm/explain.py::sayi_etiketleri`) tam tersini
yapıyor: kaynakları `izinli_sayilar()` ile **aynı** — kullanılabilecek her
sayı isteme konuyor. Guard kabulü %100 olmasının sebebi bu.

| | modele verilen sayılar | guard kabulü |
|---|---|---|
| taban istem | özellikler + kural değerleri + aksiyon | **%100** |
| eğitilmiş istem | yalnızca 5 sabit özellik alanı | **%25,7** |

### Bu hata daha önce YARIM tespit edilmişti

B3.1'de aynı mekanizma **ürün adları** için doğru teşhis edilip
düzeltilmişti:

> "İsteme ad koymaz, hedefte ad varsa → model *yoktan ad uydurmayı*
>  öğrenir. **En kötü seçenek.**"

Adlar isteme konuldu. Ama **sayılar için aynı muhakeme yapılmadı** —
oysa guard'ın bütün varlık sebebi tam olarak sayı uydurmayı engellemek.

### Düzeltme ve kalıcı koruma

Düzeltme veri hazırlama tarafında: `veri_hazirla.py::istem_kur`, hedefin
kullanabildiği tüm sayıları isteme koymalı (referans uygulama:
`explain.py::sayi_etiketleri`). Sonra veri yeniden üretilip eğitim
tekrarlanmalı. `explain.py::_EGITILMIS_ETIKETLER` de aynı anda
güncellenmeli — ikisi birebir aynı kalmak zorunda.

Kalıcı koruma: **`training/eval/veri_tutarlilik_kontrolu.py`** yazıldı,
her eğitim turundan önce koşturulmalı. Hedefte olup istemde olmayan sayı
oranı %5'i aşarsa hata koduyla çıkıyor:

```bash
uv run python -m training.eval.veri_tutarlilik_kontrolu
```

### Genel ders

**"Model öğrenemedi" ile "modele yanlış şey öğretildi" farklı
teşhislerdir ve tedavileri zıttır.** Birincisi daha çok eğitim ister;
ikincisinde daha çok eğitim zararı büyütür. Ayırt etmenin yolu veriye
bakmak — 2. turda kayıp eğrisi kusursuz görünüyordu (düzgün düşüş,
ezberleme yok) çünkü model kendisine öğretilen şeyi *başarıyla*
öğrenmişti. Öğretilen şey yanlıştı.

## Kök nedenin DÜZELTMESİ (2026-08-06)

Üç ayrı kusur bulundu ve düzeltildi. Veri yeniden üretildi:
**%79,4 → %0,0** (`veri_tutarlilik_kontrolu` kapıyı açtı).

### 1. İstem, hedefin kullandığı sayıları içermiyordu

`veri_hazirla.py` karar tipinden bağımsız **5 sabit alan** veriyordu.
Hedefler ise `label_rationale.py::SLOTLAR`'dan üretilmişti — karar tipine
göre değişen, daha geniş bir küme. Eksikler:

| karar tipi | istemde olmayan ama hedefte kullanılan |
|---|---|
| `stok.siparis` | kullanılabilir stok, ROP, sipariş miktarı, tedarikçi skoru, **tedarikçi adı** |
| `stok.tasfiye` | bağlı sermaye, **iskonto oranı** |
| `stok.aksiyon_yok` | kullanılabilir stok, ROP |

Yeni liste: `explain.py::_EGITILMIS_TIPE_GORE_ALANLAR` — karar tipine göre,
`label_rationale.py::SLOTLAR` ile hizalı.

⚠️ Taban kipin listesi (`_TIPE_GORE_ALANLAR`) **bilinçli olarak
genişletilmedi.** B2.4'te dar tutulmuştu: sayı arttıkça model ilişki
kurmayı bırakıp veri döküyor. Oradaki daraltma bir kalite kararı,
buradaki genişlik bir zorunluluk — birleştirmek, birini bozmadan diğerini
düzeltmeyi imkânsız kılardı.

### 2. Tedarikçi adı da eksikti — guard'ın göremediği açık

Sipariş gerekçelerinde tedarikçi adı geçiyor ama istemde yoktu. Sayı
uydurmasını guard yakalar; **metin uydurmasını yakalayamaz.** Ürün adı
B3.1'de tam bu gerekçeyle eklenmişti, tedarikçi adı atlanmış.

### 3. ⚠️ SÖZLEŞME DEĞİŞİKLİĞİ — `ORAN_ALANLARI` ayrışmıştı

`onerilen_iskonto_orani`, `contracts.py::ORAN_ALANLARI`'nda **yoktu**.
Sonucu: tasfiye kararlarında model, kararın özü olan iskonto oranını
doğal Türkçeyle ("%15") yazamıyordu — yalnızca "0,15" izinliydi.

Kanıt (ilk ölçüm, 5.000 örneklik alt küme): eğitim hedefleri 886 kez "%15"
kullanıyor ve üretildikleri sırada **guard'dan geçmişler**
(`guard_sonucu: gecti`). Yani veri, bu alanın ×100 karşılığının izinli
olduğu bir sürümle doğrulanmış; sonradan ayrışmış. Docstring'in
"unutulursa" senaryosu aynen gerçekleşmiş.

`ORAN_ALANLARI`'na eklendi. **Bu bir sözleşme değişikliği** (`contracts.py`
donmuş dosya) — Kişi A yaptı, **Kişi B onayladı** (2026-08-06).

**Kişi B'nin bağımsız doğrulaması, kanıtı tam veriye genişletti:**
10.000 tasfiye hedefinin **10.000'i** — üç oranın (0,15 / 0,30 / 0,50)
tamamı — yüzde olarak yazılmış ve hepsi `guard_sonucu: gecti` ile
üretilmiş. B ayrıca genişlemenin dar kaldığını test etti: iskonto %15
olan bir kararda "20"/"30"/"50" hâlâ reddediliyor. İkisi de burada
bağımsız olarak yeniden koşturulup doğrulandı.

### Yapısal koruma: tek kaynak

`veri_hazirla.py::istem_kur` artık kendi listesini taşımıyor; doğrudan
`app/llm/explain.py::egitilmis_istem_govdesi`'ni çağırıyor — çalışma
zamanının kullandığı **birebir aynı** fonksiyon. Eğitim ile çalışma
zamanının bir daha ayrışması yapısal olarak imkânsız.

Bunu koruyan test: `tests/test_egitilmis_istem.py::
test_egitim_ve_calisma_zamani_istemi_birebir_ayni`.

### Düzeltilmiş istem (tasfiye örneği)

```
VERILER:
urun: Porselen Karo - Vitra
karar: stok.tasfiye
son hareketten bu yana gecen gun: 97
eldeki stok (adet): 1
birim maliyet (TL): 312,94
bagli sermaye (TL): 312,94
onerilen iskonto orani (%): 15      <- eskiden YOKTU, model uyduruyordu

GEREKCE:
```

Hedef metin: *"...97 gün hareket göstermedikten sonra 1 adet stokta
bulunmaktadır ve bu stok maliyeti 312,94 TL'dir. ...%15 iskonto
sunulacaktır."* — artık her sayı istemde.

### Sırada

Veri (`data/colab_yukle/`) yeniden üretildi ve kapıdan geçiyor. 3. tur
eğitim bu veriyle koşulabilir. **Eğitimden önce zorunlu:**

```bash
uv run python -m training.eval.veri_tutarlilik_kontrolu
```

---

## Ek soru seti — ince araçlar için çözünürlük (Kişi B, 2026-08-06)

### Sorun: taban çizgi iki aracı hiç ölçemiyor

30 soruluk taban çizgi seti 7 araca dağılmış ama dağılım eşit değil:

```
genel_stok_durumu_sorgula   2 soru   tek hata = %50 oynama
gecelik_ozet_sorgula        3 soru   tek hata = %33 oynama
```

Bu setle "genel_stok_durumu doğruluğu %100" demek ölçüm değil, iki yazı
turasının ikisinin de tura gelmesi. Ve bu set projenin `threshold`
seviyesine geçiş kapısı — yani karar verecek olan sayı.

Aynı eleştiriyi golden set için yapmıştım; Kişi A doğruladı ve golden'daki
dağılımı paylaştı (`onay_kuyrugu` 3, `genel_stok_durumu` 3). Sorun tek bir
dosyada değil, **ölçüm altyapısının tamamında.**

### Neden taban sete soru eklenmedi

**Eklenemezdi.** Taban çizgi (%70,0 araç / %66,7 tam) o 30 soruyla ölçüldü
ve eğitimin işe yarayıp yaramadığının tek karşılaştırma noktası. Sete tek
bir soru eklemek bile 1. ve 2. tur karşılaştırmalarını geçersiz kılardı.
`router_taban_sorulari.jsonl` **donmuş dosya** sayılmalı.

### Çözüm: ayrı dosya, ayrı rapor

`training/eval/router_ek_sorular.jsonl` — 18 soru, elle yazıldı:

| araç | ek soru | taban ile toplam |
|---|---|---|
| `genel_stok_durumu_sorgula` | 8 | 10 |
| `gecelik_ozet_sorgula` | 7 | 10 |
| `onay_kuyrugu_sorgula` | 3 | 8 |

Artık her araç için en az 5 örnek var (golden set incelemesindeki
`ASGARI_ORNEK` eşiği).

Sızıntı kontrolü yapıldı: 18 sorunun hiçbiri taban setle, `router_train`,
`router_val` ya da `router_test` ile çakışmıyor.

```bash
uv run python -m training.eval.router_taban --ek --sessiz --etiket taban-ek
```

`--ek` bayrağı seti **ayrı** koşturur ve ayrı raporlar. Taban sayıya
karışmaz.

### Taban modelin ek set sonucu

| | sonuç |
|---|---|
| araç doğru | 13/18 · **%72,2** |
| araç + parametre | 13/18 · **%72,2** |
| şema hatası | 0 |
| uydurma parametre | 0 |

Araca göre: `gecelik_ozet` 5/7 · `genel_stok_durumu` 6/8 · `onay_kuyrugu` 2/3

### Bulgu: iki araç çift yönlü karışıyor

Beş hatanın dördü aynı çiftte ve **iki yönde birden**:

```
"Bugün depoda genel tablo nedir?"    genel_stok_durumu -> gecelik_ozet
"durum ozeti ver"                    genel_stok_durumu -> gecelik_ozet
"Ben yokken sistem ne tespit etti?"  gecelik_ozet      -> genel_stok_durumu
"Sabaha ne bırakmış sistem?"         gecelik_ozet      -> genel_stok_durumu
```

Tek yönlü olsaydı "model bir aracı tercih ediyor" derdik. Çift yönlü olması
başka bir şey söylüyor: model bu iki aracı **birbirinden ayıramıyor**. İkisi
de "bana genel durumu anlat" gibi okunuyor; ayrım zamansal (*şu an* mı,
*gece boyunca olanlar* mı) ve model bu ayrımı yakalamıyor.

2 ve 3 soruluk taban set bu bulguyu asla üretemezdi. 3. tur sonrası bakılacak
ilk yer burası: eğitim bu ayrımı öğretebiliyor mu?

Beşinci hata ayrı: *"Üzerimde kalan iş var mı?"* → `genel_stok_durumu`
(beklenen `onay_kuyrugu`). "Üzerimde kalan iş" = bekleyen onaylar; model
bunu stok sorusu sanıyor.

### Yan düzeltme: çöküş dedektörü yanlış alarm veriyordu

İlk ek koşuda rapor **"⚠️ ÇÖKÜŞ"** bastı. Yanlış alarmdı.

`COKUS_ESIGI = 0.40` sabiti 7 araçlı taban set için konmuştu: orada dengeli
dağılım araç başına ~%14, %40 bunun ~2,8 katı — gerçek yığılma. Ama ek set
3 aracı kapsıyor, orada dengeli dağılım zaten ~%33. Sabit eşik normal
davranışı çöküş sayıyordu.

Eşik artık setteki araç sayısına uyarlanıyor (`cokus_esigi()`):

```
esik = max(COKUS_ESIGI, 2.5 / arac_sayisi)
```

| araç sayısı | dengeli pay | eşik |
|---|---|---|
| 7 (taban) | %14,3 | **%40,0** — değişmedi |
| 3 (ek) | %33,3 | %83,3 |

`COKUS_ESIGI` tabanı devrede kaldığı için **taban çizginin sonucu
değişmedi** — yeniden koşturulup doğrulandı: %70,0 / %66,7, çöküş yok.

#### Ölçeklemenin kendi kusuru: tavan gerekiyordu

İlk sürüm yalnızca `max(COKUS_ESIGI, 2.5 / arac_sayisi)` idi ve mevcut bir
testi kırdı (`test_cokus_tespit_ediliyor`). Test artefaktı değildi, gerçek
kusurdu: **tek araçlı bir sette eşik %250 çıkıyor.** Pay tanımı gereği en
fazla %100 olabileceği için dedektör o sette hiçbir zaman ateşlenemez —
sessizce işlevsizleşir.

Sessiz işlevsizlik yanlış alarmdan daha tehlikeli: yanlış alarmı gören
inceler, ateşlenmeyen dedektörü kimse fark etmez.

```
esik = min(COKUS_TAVANI, max(COKUS_ESIGI, 2.5 / arac_sayisi))   # tavan 0,90
```

İki uç durum da teste bağlandı:

| test | ne koruyor |
|---|---|
| `test_cokus_esigi_arac_sayisina_gore_kayiyor` | 7 araçta eşik değişmiyor, 3 araçta kayıyor |
| `test_cokus_esigi_hicbir_sette_ulasilamaz_olmuyor` | 1–7 araç, eşik hep %100'ün altında |

### Ayrı bulgu: koşular birbirinin sonucunu eziyordu

Ek seti koştururken bayrak kombinasyonunu (`--ek --model ... --istem-bicimi
egitilmis`) doğrulamak için var olmayan bir modele bir deneme yaptım. 18/18
hata verdi — beklenen. Ama o deneme **taban çizgi kaydını sildi.**

`sonucu_kaydet` her koşuyu tek bir dosyaya yazıyordu:
`router_taban_sonuc.json`. Taban çizgi, ek set, 1. tur, 2. tur — hepsi aynı
yere. Dosya her zaman yalnızca *en son* koşuyu tutuyordu. Docstring'in
"B3.5'te modeli tekrar çalıştırmaya gerek kalmasın" vaadi aslında hiç
tutulmuyordu ve bunu kimse fark etmemişti.

Artık her etiket kendi dosyasına yazıyor (`sonuc_yolu`):

```
--etiket taban          -> router_taban_sonuc.json   (donmus taban cizgi)
--etiket lora-tur3      -> router_sonuc_lora-tur3.json
--etiket lora-tur3 --ek -> router_sonuc_lora-tur3-ek.json
```

Etiket dosya adına girdiği için karakter süzmesi de var; yol kaçışı
oluşturamıyor. Testi: `test_kosular_birbirinin_sonucunu_ezmiyor`.

Taban çizgi yeniden üretildi ve donmuş dosyaya geri yazıldı. Ölçüm içeriği
eski kayıtla **birebir aynı** çıktı (fark yalnızca süre alanlarında) —
determinizm bir kez daha doğrulandı.

Toplam **324 test yeşil**.

---

## 3. tur ÖNCESİ tahmin — çürütülebilir, önceden yazıldı (Kişi B, 2026-08-06)

⚠️ **Bu bölüm 3. tur ölçümünden ÖNCE yazıldı.** Sonucu görüp sonradan
açıklama uydurmak kolaydır; önceden yazılmış tahmin ise ya tutar ya tutmaz.
Aşağıdaki sayılar ölçüm geldiğinde **değiştirilmeyecek**.

### Soru

Ek set, taban modelin `genel_stok_durumu` ile `gecelik_ozet`'i **çift yönlü**
karıştırdığını gösterdi. Eğitim bunu düzeltebilir mi?

Cevabı ölçmeden önce eğitim verisine bakmak mümkündü — bakıldı.

### Bulgu 1: sinyal temiz, sorun hacim

Vokabüler ayrımı aslında **net**. Eğitim verisinde:

| kelime | `genel_stok` | `gecelik_ozet` | ayırt edici mi |
|---|---|---|---|
| `genel` | %69,2 | %0,0 | ✅ kusursuz |
| `stok` | %42,3 | %0,0 | ✅ kusursuz |
| `envanter` | %38,5 | %0,0 | ✅ kusursuz |
| `bugün` | %0,0 | %23,9 | ✅ kusursuz |
| `gecelik` | %0,0 | %11,0 | ✅ kusursuz |
| `özet` | %34,6 | %41,9 | ❌ **belirsiz** |

Yani model bu iki sınıfı ayırt edecek işareti veride bulabiliyor. Tek
gerçekten paylaşılan kelime `özet` — ve iki sınıfın da üçte birinden
fazlasında geçiyor.

### Bulgu 2: asıl sorun örnek sayısı ve şablon çeşitliliği

```
                        train   val  test   farkli iskelet
genel_stok_durumu         26      5     3   20 (7'si AYNI kalip)
gecelik_ozet             155     17    12   140
siparis_onerisi         1633      —     —   —
```

`genel_stok_durumu` eğitim verisinin **%0,7'si**. Üstelik 26 örneğin 7'si
tek bir kalıbın nezaket çeşitlemesi:

```
7x  "envanterin genel özetini <FIIL> mısınız?"
```

`gecelik_ozet` ise 155 örnekte 140 farklı iskelet taşıyor — gerçek çeşitlilik.
Paylaşılan `özet` kelimesi geldiğinde model 155'e karşı 26 görüyor.

### Tahmin

1. **`gecelik_ozet` düzelecek.** 155 örnek ve yüksek çeşitlilik var. Taban
   5/7 idi; 3. turda **6/7 veya 7/7** bekliyorum.

2. **`genel_stok_durumu` düzelmeyecek, kötüleşebilir.** 26 örnek ve tek
   baskın kalıp yeterli değil; eğitim, paylaşılan `özet` sinyalini 155
   örneklik sınıfa doğru çekecek. Taban 6/8 idi; 3. turda **≤6/8**
   bekliyorum.

3. **Hataların yönü tek yönlüye dönecek.** Taban modelde karışma çift
   yönlüydü. Eğitimden sonra `gecelik_ozet → genel_stok` yönü kaybolacak,
   `genel_stok → gecelik_ozet` yönü kalacak — hacim farkının doğal sonucu.

4. **`onay_kuyrugu` da riskli** (39 eğitim örneği). Taban 2/3.

**Bu tahmin yanlış çıkarsa** — özellikle (2) ve (3) — hipotez yanlış demektir
ve sorun hacim değil başka bir şeydir. İkisi de öğrenilecek bilgi.

### Ne yapılmayacak

Ek setin altın etiketleri **değiştirilmeyecek**. Denetim yapıldı: 18 sorunun
1'inde eğitim verisiyle çelişen sinyal var —

> `"Bugün depoda genel tablo nedir?"` → `genel_stok_durumu_sorgula`
> çelişen: `bugün` (gecelik'in %24'ü) · destek: `genel` (genel_stok'un %69'u)

Etiket anlamca doğru: *"depoda genel tablo"* stok durumudur, *"bugün"* burada
*"şu an"* anlamında. Soru dosyada `not` alanıyla **bilinçli zor vaka** olarak
işaretlendi.

Modelin hatasına bakıp altın etiketi değiştirmek, ölçümü modele uydurmaktır —
o noktadan sonra ölçüm hiçbir şey söylemez.

### Eğer tahmin (2) tutarsa ne yapılmalı

Daha fazla eğitim turu bunu çözmez; **veri sorunu**. İki seçenek:

- `genel_stok_durumu` için ~150 örneğe çıkacak şekilde çeşitlilikli soru
  üretmek (Kişi A'nın üreticisiyle, ama tek kalıptan değil),
- ya da sınıf ağırlıklı örneklemede bu sınıfa özel tavan yükseltmek.

Karar ölçüm geldikten sonra, birlikte.

### DÜZELTME — tahminin dayanağı yanlıştı (3. tur hâlâ gelmeden)

⚠️ Yukarıdaki tahmin **olduğu gibi bırakıldı**; sonradan düzeltmek tahmini
anlamsız kılar. Bu bölüm onun üstüne yazılan bir düzeltme.

#### Hata: ham dosya sayısına bakıldı

Tahmin şuna dayanıyordu: *"`genel_stok` 26 örnek, `gecelik` 155 örnek; model
kararsız kalınca çok gördüğünü seçer."*

Ama eğitim ham dosyayı kullanmıyor. `train_lora.ipynb::dengeli_kota` sınıfları
eşitliyor (`TAVAN_KAT=20`, `ROUTER_ORNEK=2000`). Modelin gerçekten gördüğü:

| araç | özgün | kota | tekrar | **özgünlük** |
|---|---|---|---|---|
| `siparis_onerisi` | 1633 | 285 | 0,2x | %100,0 |
| `tedarikci_performansi` | 1325 | 285 | 0,2x | %100,0 |
| `kritik_stok` | 256 | 285 | 1,1x | %89,8 |
| `olu_stok` | 240 | 285 | 1,2x | %84,2 |
| `gecelik_ozet` | 155 | 285 | 1,8x | %54,4 |
| `onay_kuyrugu` | 39 | 285 | 7,3x | **%13,7** |
| `genel_stok_durumu` | 26 | 285 | 11,0x | **%9,1** |

**Kotalar eşit.** Hacim farkı diye bir şey yok — tahminin dayanağı buharlaştı.
Fark özgünlükte: `genel_stok` 26 cümleyi 11 kez tekrarlıyor, `gecelik` 155
farklı cümle gösteriyor. Aynı ağırlık, çok farklı çeşitlilik.

#### Kanıt: 2. tur zaten bunu gösteriyormuş

2. tur sonucu elimizdeydi (`router_lora_tur2_sonuc.json`) ve bakılmamıştı.
Sınıf başına "kaç kez beklendi / kaç kez seçildi":

| araç | özgünlük | taban | 2. tur | |
|---|---|---|---|---|
| `siparis_onerisi` | %100,0 | 5/6 | 5/3 | az seçilir oldu |
| `tedarikci_performansi` | %100,0 | 5/4 | 5/1 | az seçilir oldu |
| `gecelik_ozet` | %54,4 | 3/4 | 3/3 | düzeldi |
| `onay_kuyrugu` | **%13,7** | 5/5 | 5/**7** | **fazla seçilir oldu** |
| `genel_stok_durumu` | **%9,1** | 2/3 | 2/**4** | **fazla seçilir oldu** |

2. turun gerçek araca giden dört hatasının **dördü de** o iki sınıfa akmış:

```
2x  tedarikci_performansi -> genel_stok_durumu
1x  kritik_stok           -> onay_kuyrugu
1x  olu_stok              -> onay_kuyrugu
```

Yani düşük özgünlüklü sınıf **kaybetmiyor, çöp kutusu oluyor.** Eşit ağırlık
alıyor ama dar ve ezberlenmiş kalıpları olduğu için karar sınırı bulanık;
başka bir sınıfa güçlü şekilde uymayan her soruyu kapıyor.

#### Bu zaten öngörülmüştü

`train_lora.ipynb`, 2. tur bölümünde şunu yazıyordu:

> *"Hiçbir örnekleme 11 özgün soruyu çoğaltamaz. Ölçüm iyileşebilir (model o
> 11 kalıbı öğrenir) ama aynı aracın yeni bir soruluşunu tanıması beklenmez."*

Doğru çıkmış. Eksik olan tek şey, bunun **diğer sınıflara zarar verdiğinin**
görülmemesiydi.

#### Düzeltilmiş tahmin (3. tur için)

Eskisi geçersiz. Yenisi:

1. **`genel_stok_durumu` FAZLA seçilecek**, az değil. Ek setteki 8
   `genel_stok` sorusu **iyi** puan alabilir (≥6/8) — çünkü sınıf her şeyi
   çekiyor.
2. **Asıl zarar başka araçlarda görünecek.** `tedarikci_performansi` ve
   `kritik_stok` gibi sınıflardan `genel_stok`/`onay_kuyrugu`'na kaçış olacak.
3. **Karışma yönü tersine dönecek:** `gecelik → genel_stok` yönü artacak,
   `genel_stok → gecelik` azalacak. (Eski tahmin tam tersini söylüyordu.)
4. **`onay_kuyrugu` da fazla seçilecek** (%13,7 özgünlük).

**Ölçülebilir imza:** her sınıf için *seçilme − beklenme*. Düşük özgünlüklü
iki sınıfta pozitif, yüksek özgünlüklülerde negatif olmalı.

#### Sonuç: doğru çözüm ne

Daha fazla eğitim turu **bunu çözmez**; örnekleme ayarı da çözmez (dengeyi
bozar). Tek gerçek çözüm `genel_stok_durumu` ve `onay_kuyrugu` için **çeşitli
soru üretmek** — tek kalıbın nezaket çeşitlemesi değil, farklı soruluşlar.

Hedef: özgünlük ≥%50, yani her iki araç için ~150 özgün soru. Kişi A'nın
tarafı (Veri & Alan).

---

## ⚠️ Determinizm iddiası yanlıştı — sıcaklık 0 yetmiyor (Kişi B, 2026-08-06)

### Nasıl fark edildi

Rapora çekim gücü bölümü eklenip taban çizgi yeniden koşturuldu. Sonuç:

```
  araç doğru             : 21/30  (%70.0)     <- beklenen
  araç + parametre doğru : 21/30  (%70.0)     <- BEKLENEN %66,7 IDI
```

Tam doğruluk 20/30'dan 21/30'a çıkmıştı. Ama:

- kod değişmemişti (`git diff -- app/ router_taban_sorulari.jsonl` boş),
- model aynıydı (`qwen2.5:1.5b-instruct`, digest `65ec065481…`, 1 Ağustos'tan
  beri dokunulmamış),
- ölçüm sıcaklık 0 ve sabit tohumla yapılıyordu.

Üstelik tekrarlanabilirdi: iki koşu da 21/30 verdi. Yani gürültü değil.

### Deney

Model her koşudan önce `keep_alive=0` ile bellekten atıldı:

```
soguk baslangic, 3 kez  ->  arac 21/30 · tam 20/30   (ucunde de ayni)
isinmis modelle,  2 kez ->  arac 21/30 · tam 21/30   (ikisinde de ayni)
```

Her iki durum da **kendi içinde tam tekrarlanabilir**, ama birbirinden farklı.
Belirleyici olan modelin **ısınma durumu**.

Oynayan tek soru:

> *"Bizi kim geciktiriyor?"* — ısınmış modelde parametresiz (doğru), soğuk
> modelde `tedarikci_id="Bizi Kim Geciktiriyor"` uyduruyor.

Sınıra yakın bir kararın iki yana düşmesi. llama.cpp/Ollama'da yığınlama ve KV
önbellek durumu logit'leri son basamakta oynatabiliyor; başa baş giden iki
seçenek yer değiştiriyor. Sıcaklıkla ilgisi yok.

### Neden önemli

30 soruluk sette **1 soru = 3,3 puan**. 3. tur %73,3 verseydi, bunun eğitimden
mi yoksa ısınma farkından mı geldiği ayırt edilemezdi. Zaten Wilson %95 güven
aralığı zaten geniş (21/30 için %52–83); üstüne bir de ölçülemeyen bir kayma
eklenecekti.

Modülde yazan şu cümle **yanlıştı** ve düzeltildi:

> ~~"Sıcaklık 0 + sabit tohum ile model açgözlü üretim yapıyor ve aynı girdiye
> aynı cevabı veriyor."~~

Sıcaklık 0 gürültünün büyük kısmını alıyor (7 puanlık oynama → 3,3), ama
hepsini değil.

### Çözüm

`olc()` artık ölçüme başlamadan modeli düşürüyor (`modeli_bellekten_at`).
Her ölçüm aynı yerden başlıyor. Model düşürülemezse ölçüm yine yapılıyor —
yalnızca soğuk başlangıç garantisi kalkıyor; ölçümü buna bağlamak yanlış olur.

Doğrulama — soğuk başlangıçla üç ardışık koşu:

```
arac 21/30 (%70,0) · tam 20/30 (%66,7)
arac 21/30 (%70,0) · tam 20/30 (%66,7)
arac 21/30 (%70,0) · tam 20/30 (%66,7)
```

Resmî taban çizgiyle birebir aynı — o değer de soğuk başlangıçla ölçülmüştü.
Testi: `test_olcum_soguk_baslangicla_yapiliyor`.

### Ek set yeniden ölçüldü

Ek set ısınmış modelle ölçülmüştü; soğuk başlangıçla tekrarlandı ve **aynı**
çıktı: **13/18 · %72,2**. O sette sınıra yakın karar yokmuş.

### Kalan güvenilirlik notu

Soğuk başlangıç *bilinen* bir kayma kaynağını kapatıyor. Ollama sürümü,
donanım veya model dosyası değişirse aynı sorun geri gelebilir — bu yüzden
sonuç dosyalarında model adı ve etiket saklanıyor. **3. tur ölçümü ile taban
çizgi mümkünse aynı oturumda koşturulmalı.**
## ⭐ 3. tur SONUCU (2026-08-06)

Eğitim: 9.993 örnek, 1.250 adım, 43 dk. Kayıp eğrisi 2. turdan daha iyi
bitti (eğitim 0,1311, doğrulama 0,1750 — 2. tur: 0,1797/0,2134),
ezberleme işareti yok.

### Ana tablo

| | taban | 2. tur | **3. tur** |
|---|---|---|---|
| router tam doğruluk (30 soru, B2.3 seti) | %66,7 | %63,3 | **%70,0** |
| router araç doğruluğu | %70,0 | %73,3 | **%76,7** |
| **guard kabul oranı** ⭐ | %100 | **%25,7** | **%100** |
| gerekçe: uydurma sayı (final metin) | 0 | — | **0** |
| Türkçe akıcılık (LLM-jüri) | — | — | 4,80/5 |
| gecelik tarama (2.000 SKU) | — | — | 180 sn (hedef <600) |
| tepe RAM | — | — | 421 MB (hedef <4096) |

**Kök neden düzeltmesi doğrulandı.** Guard kabul oranı %25,7 → %100 —
taban modelle birebir eşleşti. 2. turun yarattığı hasar (istem, hedefin
kullandığı sayıların çoğunu içermiyordu — bkz. "2. turun KÖK NEDENİ")
tamamen giderildi. Router tarafında da taban çizgiyi geçti, ilk kez
**hiçbir eksende taban modelden kötü değil.**

⚠️ Router'daki iyileşme (%66,7→%70,0) B'nin Wilson eşiğinin (27/30, bkz.
SP3/B4 tartışması) altında — istatistiksel olarak "kesin kazanım" denemez,
gürültü payı içinde olabilir. Ama **guard tarafındaki fark (4 kat) gürültü
sınırlarının çok üzerinde**, o kesin.

### Ek set (18 soru, ince araçlar) — taban ile doğrudan kıyas

| | taban | **3. tur** |
|---|---|---|
| araç doğruluğu | %72,2 | **%88,9** ↑ |
| tam doğruluk | %72,2 | **%61,1** ↓ |
| uydurma parametre | 0 | **4** (yeni) |

Araç seçiminde net iyileşme ama **yeni bir halüsinasyon türü**: model
`gecelik_ozet_sorgula` sorularında hiç sorulmayan bir `tarih_ifadesi`
parametresi (`"dün"`, `"geçen gün"`) uydurmaya başladı. Taban modelde
hiç yoktu. İzlenmeli — 3. turun kazanımı parametre uydurma riskiyle
birlikte geliyor.

### B'nin DÜZELTİLMİŞ tahmini (özgünlük hipotezi) — sonuç: doğrulandı

İlk tahmin (yukarıda, "hacim" temelli) zaten yanlış çıkacağı önceden
biliniyordu — B ölçümden önce dayanağını düzeltmişti (bkz. yukarıdaki
"DÜZELTME" bölümü): sorun hacim değil **özgünlük**, düşük özgünlüklü
sınıflar (`genel_stok_durumu` %9,1, `onay_kuyrugu` %13,7) kaybetmiyor,
**çöp kutusu** oluyor — başka sınıflardan kaçan sorular oraya akıyor.

30 soruluk taban setteki tüm yanlış yönlendirmeler:

```
kritik_stok_sorgula            -> onay_kuyrugu_sorgula      (kaçış)
olu_stok_sorgula                -> onay_kuyrugu_sorgula      (kaçış)
gecelik_ozet_sorgula             -> genel_stok_durumu_sorgula (kaçış, YÖN TERSİNE DÖNDÜ)
onay_kuyrugu_sorgula             -> siparis_onerisi_sorgula   (tek ters örnek)
```

| düzeltilmiş tahmin | gerçekleşen | tuttu mu |
|---|---|---|
| `genel_stok_durumu` FAZLA seçilecek (çöp kutusu) | Ek sette 8/8, + taban sette 1 kaçış aldı | ✅ |
| Asıl zarar başka sınıflarda görünecek | `kritik_stok`, `olu_stok` başka yere kaçtı | ✅ |
| Karışma yönü tersine dönecek (`gecelik→genel_stok`) | Tam olarak bu yönde 1 kaçış, ters yönde 0 | ✅ |
| `onay_kuyrugu` da fazla seçilecek | 2 kaçış aldı (kritik_stok, olu_stok'tan) | ✅ |

**Dört tahminin dördü de doğrulandı.** Özgünlük hipotezi (hacim değil,
tekrarlanan dar kalıplar karar sınırını bulanıklaştırıyor) 3. tur
verisiyle net şekilde teyit edildi. Çözüm B'nin yazdığı gibi: daha fazla
eğitim turu değil, bu iki araç için **çeşitli** (~150 özgün) soru
üretmek — Kişi A'nın tarafı.

### Sonuç ve öneri

3. tur, ölçülen her eksende taban modelden **eşit ya da iyi** — 2. turun
aksine. `.env` `codifya-router:tur3` + `egitilmis` kipe alındı (ölçüm
için geçiciydi, kalıcı hale getirildi). Router hâlâ %95 hedefinin uzağında
ama bu artık eğitimin başarısızlığı değil, veri hacminin sınırı —
ayrı bir konu.

Ham sonuçlar: `training/eval/router_sonuc_lora-tur3.json`,
`training/eval/benchmark_sonuc_lora-tur3.json`.

---

## 3. tur — Kişi B'nin bağımsız incelemesi (2026-08-06)

Kişi A 3. tur sonucunu paylaştı. Sonuçlar burada yeniden puanlandı
(`--rapor`, model çalıştırılmadan). Üç bulgu var: biri onay, biri düzeltme,
biri **Kişi A'nın raporunda görünmeyen bir gerileme**.

### 1. Tahmin doğrulandı — çekim gücü tam öngörüldüğü gibi

"Hacim değil özgünlük" düzeltmesi 3. turda birebir tuttu:

| araç | özgünlük | beklenen → seçilen |
|---|---|---|
| `genel_stok_durumu` | %9,1 | 2 → 3 **(+1)** |
| `onay_kuyrugu` | %13,7 | 5 → 6 **(+1)** |
| `kritik_stok` | %89,8 | 5 → 3 (−2) |
| `olu_stok` | %84,2 | 5 → 4 (−1) |

Düşük özgünlüklü iki sınıf fazla seçiliyor, yüksek özgünlüklüler kaybediyor —
imza aynen çıktı. Kaçış listesi de öyle: `kritik_stok→onay_kuyrugu`,
`olu_stok→onay_kuyrugu`, `gecelik_ozet→genel_stok_durumu`.

### 2. Kişi B'nin etiket hatası — düzeltildi

Ek set ilk bakışta 3. turda **düştü** gibi görünüyordu (%72,2 → %61,1 tam).
Sebep model değil, **benim yanlış altın etiketim**.

`schemas.py::ARAC_PARAMETRELERI` `gecelik_ozet_sorgula`'ya `tarih_ifadesi`
veriyor ve eğitim verisindeki **155 örneğin 155'i** parametreli. Ben ek
setteki 7 gecelik sorusuna `{}` yazmıştım.

Denetlendi: 7 sorunun **6'sında `{}` doğru** (soruda tarih ifadesi yok),
**1'inde yanlış** — *"dun gece ne cikti"* içinde `dün` var. O etiket
düzeltildi.

> ⚠️ Gerekçe modelin çıktısı **değil**: şema + 155/155 eğitim kuralı. Kural
> net — değer dört ifadeden biri (`dün`, `bugün`, `bu hafta`, `geçen hafta`)
> ve soruda birebir geçiyor. Daha önce *"Bugün depoda genel tablo nedir?"*
> etiketini model itiraz ettiği için **değiştirmemiştim**; fark bu: orada
> bağımsız kanıt yoktu, burada sözleşme var.

`sonuctan_yukle` artık altın etiketleri soru dosyasından tazeliyor, yani
etiket düzeltmesi **eski ölçümlere de** uygulanıyor. Yoksa taban ile 3. tur
farklı altın etiketlerle karşılaştırılırdı.

### 3. ⚠️ Görünmeyen gerileme: parametre uydurma

Düzeltilmiş altın etiketle **ek set**:

| | taban | 3. tur | |
|---|---|---|---|
| araç doğru | 13/18 · %72,2 | **16/18 · %88,9** | ✅ gerçek kazanç |
| araç + parametre | 12/18 · %66,7 | 12/18 · %66,7 | değişmedi |
| **uydurma parametre** | **0** | **4** | ⚠️ **gerileme** |

Araç seçimi ciddi biçimde düzeldi ama model **olmayan tarih uydurmaya
başladı**. Tam doğruluğun sabit kalmasının sebebi bu: araçtaki kazanç
parametredeki kayıpla götürüldü.

```
"Gece taramasının sonuçlarını görebilir miyim"  -> tarih_ifadesi: 'geçen gün'
"Gece boyunca neler birikmiş?"                  -> tarih_ifadesi: 'geçen gün'
"gece raporu"                                   -> tarih_ifadesi: 'geçen gün'
"Son gecelik koşunun raporunu aç."              -> tarih_ifadesi: 'son gecelik'
```

Hiçbiri soruda geçmiyor; `geçen gün` ve `son gecelik` eğitimdeki dört geçerli
değerden hiçbiri de değil. Model uyduruyor.

**30 soruluk taban set bunu göremedi** (uydurma 0) — çünkü orada yalnızca 3
gecelik sorusu var, ek sette 7. Ek setin varlık sebebi tam olarak buydu.

### 4. Taban set sayıları — bir çekince

| | taban | 3. tur |
|---|---|---|
| araç doğru | 21/30 · %70,0 | 23/30 · **%76,7** |
| araç + parametre | 20/30 · %66,7 | 21/30 · **%70,0** |

⚠️ **`%66,7 → %70,0` tam olarak 1 soru** — ve ölçtüğüm ısınma sürüklenmesinin
büyüklüğü de tam olarak 1 soru, hem de aynı tipte (parametre değişimi).
Kişi A'nın ölçümü soğuk başlangıç düzeltmesinden **önceki** kodla yapıldı
(sonuç dosyasında `cekim_gucu` alanı yok, bu kanıtlıyor).

Yani tam doğruluktaki +1, eğitim kazancı da olabilir ısınma farkı da —
bu koşuyla ayırt edilemez.

**Araç doğruluğundaki +2 daha sağlam:** ölçtüğüm sürüklenme araç seçimini
hiç değiştirmedi, yalnızca parametreyi oynattı. Ek setteki +3 (%72,2 → %88,9)
de aynı yöne işaret ediyor.

### Sonuç

- **Araç seçimi gerçekten düzeldi** — iki bağımsız sette de (+2 ve +3).
- **Parametre disiplini geriledi** — 0 → 4 uydurma, yalnızca ek set gördü.
- **Tam doğruluktaki +1 doğrulanmalı**: 3. tur soğuk başlangıçla yeniden
  ölçülmeli (`d9e2eea` sonrası kodla).
## Golden set ortak onayı — bulunan hata ve düzeltmesi (2026-08-06)

Ortak onaydan önceki rastgele örnekleme taramasında, önceden hiç fark
edilmemiş bir veri kalitesi hatası bulundu: **golden set'in %30,6'sında
(49/160 router sorusu) bitişik kelime tekrarı vardı** —
*"T-0005 tedarikçisinin **tedarikçinin** gecikiyomu var mı?"*,
*"çimento kategorisinde **kategorisinde** acil sipariş..."* gibi.
`tedarikci_performansi_sorgula`'da oran %60,3'e çıkıyordu.

### Kök neden

`sablonlari_ihrac_et`, paraphrase LLM'ine gönderilecek şablonu
`_varlik_ifadesi()` ile önceden dolduruyor: `"TEDARIKCI_KODU tedarikçisinin
performansı..."` gibi. Paraphrase modeli cümleyi yeniden yazarken bazen
"tedarikçisinin"/"kategorisinde" kelimesini cümlenin başka bir yerinde de
kullanıyor. `parafraz_sablonlarindan_veri_uret` token'ı **yine** aynı sonekle
("X tedarikçisinin") değiştirince iki kez üst üste geliyor. Paraphrase
notebook'undaki `anlam_korundu_mu()` kontrolü bunu yakalayamıyordu çünkü
niyet/anlam hâlâ doğruydu — sorun dil bilgiseldi, anlam değil.

Ölçüm: tam üretim havuzunda (`router_sorulari_parafraz.jsonl`, 35.519 satır)
**1.256 satır** etkilenmiş; ham (paraphrase edilmemiş) havuzda bu oran
neredeyse sıfırdı — hata özellikle paraphrase adımından geliyor.

### Düzeltme

`training/build_dataset.py::yer_tutucu_tekrarini_temizle()` eklendi —
bitişik tekrarı tek kelimeye indiriyor, cümlenin başka yerindeki **gerçek**
tekrarlara (ör. *"tedarikçi güvenilir mi, bu tedarikçiyle devam edelim
mi?"*) dokunmuyor. `parafraz_sablonlarindan_veri_uret`'e otomatik
uygulanıyor (yeni paraphrase turları için kalıcı koruma). 5 regresyon
testi (`tests/test_build_dataset_yer_tutucu.py`).

Mevcut üretilmiş dosyalar yerinde yamalanıp yeniden ölçüldü:

| dosya | düzeltilen |
|---|---|
| `golden_set_aday.jsonl` | 45/160 |
| `router_sorulari_parafraz.jsonl` | 1.256/35.519 |
| `router_train.jsonl` | 1.018/3.674 |
| `router_val.jsonl` | 120/453 |
| `router_test.jsonl` | 118/387 |

Düzeltme sonrası tarama: **0 gerçek tekrar kaldı** (kalan 4 aday elle
kontrol edildi, hepsi doğal cümleler — *"tedarikçisinin iyi bir tedarikçi
mi?"* gibi, bitişik değil). `golden_set_inceleme.py` yeniden koşuldu:
sızıntı yok, tekrar yok, guard uyumu %100 — değişmedi.

⚠️ **Veri dosyaları `.gitignore`'da** (Drive üzerinden paylaşılıyor). Kod
düzeltmesi git'te, ama Drive'daki mevcut kopya hâlâ eski (bozuk) veriyi
taşıyor olabilir — 4. tur ya da yeni bir paraphrase turu öncesi
`data/colab_yukle/`'nin yeniden yüklenmesi gerekir.

**Golden set artık ortak onay için hazır** — n<10 iki araç ve
`stok.tedarikci_degisim` boşluğu (zaten kabul edilmiş, bkz. yukarıdaki
bölümler) dışında bilinen bir sorun yok.

## Çöp kutusu araçları için hedefli paraphrase turu (2026-08-06)

3. tur ölçümünde hem benim hem B'nin bağımsız doğruladığı özgünlük
hipotezine çözüm: `genel_stok_durumu_sorgula` ve `onay_kuyrugu_sorgula`
için `training/paraphrase_colab.ipynb` (Qwen2.5-7B, Colab GPU) ile
hedefli, yüksek-n bir paraphrase turu koşuldu.

⚠️ **İlk deneme kesilme (truncation) hatası verdi** — `VARYANT_SAYISI=18`
için sabit `max_new_tokens=200` yetersizdi, üretim yarıda kesilip
tamamlanmamış satırlar bıraktı ("Onay bekleyen kararları varsa l"). Kalıcı
düzeltme: `max_new_tokens` artık `n * 45` (varyant başına pay), tamamlanmamış
satırlar filtreleniyor, tek-üretim içi tekilleştirme eklendi.

İkinci (düzeltilmiş) deneme sonrası, **mevcut havuzla birleştirilerek**
(değiştirilmeden — hiçbir zaman geriye gitmemek için):

| araç | önce | sonra |
|---|---|---|
| `genel_stok_durumu_sorgula` | 28 şablon | **67 şablon** (+139%) |
| `onay_kuyrugu_sorgula` | 39 şablon | **65 şablon** (+67%) |

`training.veri_bolme` yeniden koşuldu, golden set adayı yenilendi:

| araç (golden set) | önce | sonra |
|---|---|---|
| `genel_stok_durumu_sorgula` | 3 (ince araç uyarısı) | **7** (eşiği geçti ✅) |
| `onay_kuyrugu_sorgula` | 3 | **4** (hâlâ ince, iyileşti) |

`veri_tutarlilik_kontrolu` ve `golden_set_inceleme` yeniden geçti (sızıntı
yok, guard uyumu %100). Hedef (~150/araç) tam tutmadı — paraphrase modelinin
tek üretimde üretebildiği gerçek çeşitlilik sınırlı çıktı — ama gerçek,
geriye gitmesiz bir kazanım. `data/colab_yukle/` yeniden üretildi.

⚠️ Veri dosyaları `.gitignore`'da; kod düzeltmesi (`paraphrase_colab.ipynb`)
git'te, veri Drive'a ayrıca yüklenmeli.

## 3. turdaki uydurmaların kökü: iki ayrı sorun (2026-08-08)

3. tur ek sette **4 uydurma parametre** raporlanmıştı (taban: 0) — araç
seçimi ilerlerken parametre disiplininin gerilediği tek işaret buydu ve
4. tur kararının önündeki asıl engeldi. Kazınca altından **iki farklı**
sorun çıktı, biri ölçümde biri veride.

### 1. Ölçüm hatası — 4'ün 1'i uydurma değildi

`Kayit.uydurma_parametre` "değer soruda geçiyor mu" diye düz altdizi
araması yapıyordu. Kullanıcı aksansız yazdığında:

    soru      : "dun gece ne cikti"
    model     : tarih_ifadesi = "dün"
    altın etiket: ["dün", "dun"]   -> parametre_dogru GEÇİYOR
    dedektör  : "dün" soruda yok   -> UYDURMA (yanlış)

Yani dedektör, modeli **doğru** aksan normalleştirmesi yaptığı için
cezalandırıyordu. Tek yönlü bir hata: doğru davranışı yanlış raporluyor.

Düzeltme: `aksansiz()` — `ı/İ/I` elle eşitlenir (NFKD onları ayrıştırmaz,
`ı` bağımsız bir kod noktası), kalan `ç ğ ö ş ü` NFKD + birleşen işaret
atmayla düşer. Yalnızca uydurma dedektöründe kullanılıyor; `parametre_dogru`
elle yazılmış kabul listesine bakmaya devam ediyor — o bir sözleşme,
normalleştirmeyle gevşetilmemeli. 3 regresyon testi
(`tests/test_llm_router.py`), biri normalleştirmenin **gerçek** uydurmayı
gizlemediğini doğruluyor.

Kayıtlı tüm sonuçlar `--rapor` ile yeniden puanlandı:

| sonuç | önce | sonra |
|---|---|---|
| `lora-tur3-ek` | 4 uydurma | **3** |
| taban, taban-ek, lora-tur3, lora-tur2 | 0 | 0 (değişmedi) |

Taban çizgilerin hiçbiri oynamadı — düzeltme hedefli.

### 2. Gerçek kök neden — eğitim verisinde parametresiz örnek yok

Kalan 3 uydurmanın üçü de **aynı**: soruda hiçbir tarih ifadesi yokken
model `tarih_ifadesi="geçen gün"` üretiyor.

    "Gece taramasının sonuçlarını görebilir miyim?"  -> tarih_ifadesi="geçen gün"
    "Gece boyunca neler birikmiş?"                   -> tarih_ifadesi="geçen gün"
    "gece raporu"                                    -> tarih_ifadesi="geçen gün"

`"geçen gün"` eğitim verisindeki dört geçerli değerin (`bugün`, `dün`,
`bu hafta`, `geçen hafta`) **hiçbiri değil** — model kendi eğitim
sözlüğünün dışına çıkıyor. Bu, doldurmak zorunda bırakıldığı bir slotta
klasik davranış.

Sebep, veri kapsamında:

| araç | parametreli | parametresiz |
|---|---|---|
| `gecelik_ozet_sorgula` | 184 | **0** ⚠️ |
| `siparis_onerisi_sorgula` | 2000 | **0** ⚠️ |
| `kritik_stok_sorgula` | 280 | 35 ✅ |
| `olu_stok_sorgula` | 256 | 32 ✅ |
| `tedarikci_performansi_sorgula` | 1563 | 27 ✅ |
| `genel_stok_durumu_sorgula` | 0 | 73 ✅ (şemaca parametresiz) |
| `onay_kuyrugu_sorgula` | 0 | 73 ✅ (şemaca parametresiz) |

Model `gecelik_ozet_sorgula`'yı **parametresiz** hiç görmedi. Parametresi
isteğe bağlı olan üç araçta (`kritik_stok`, `olu_stok`,
`tedarikci_performansi`) iki durum da temsil ediliyor ve oralarda uydurma
yok — desen tutarlı.

⚠️ `siparis_onerisi_sorgula` aynı boşluğu taşıyor (2000/0) ama ölçüm
setlerinde ürünsüz bir sipariş sorusu ("ne sipariş etmeliyim?") denk
gelmediği için henüz patlamadı. Aynı kusur, yalnızca görülmemiş.

**Karar:** 4. tur eğitimi bu boşluk kapatılmadan koşulmaz — aksi hâlde
kusur modele bir kez daha pekiştirilir.

### 3. Boşluğun asıl bedeli: `gecelik_ozet` eğitimle BOZULDU

Kapsama boşluğu bulununca bu aracı iki ölçüm setinde birden (taban set +
ek set, toplam 10 soru) ayrı puanladım. Tablo, genel doğruluğun sakladığı
şeyi gösteriyor:

| model | araç doğru | **tam doğru** |
|---|---|---|
| taban | 8/10 | **7/10** |
| 3. tur | 7/10 | **1/10** |

3. tur bu aracı **bozdu**. Genel doğruluk aynı anda %70,0'dan %76,7'ye
çıktığı için bu ölçümde hiç görünmedi — `cekim_gucu`'nun araç seçimi için
uyardığı "bir sınıf kazanır, diğeri kaybeder" durumunun **parametre**
hâli. Uydurma sayacı da tamamını göstermiyordu, çünkü hataların bir kısmı
teknik olarak uydurma değil:

    "Dün gece sistem ne buldu?"   -> tarih_ifadesi="dün"    (altın etiket: {})
    "Sabah raporunda ne çıkmış?"  -> tarih_ifadesi="Sabah"  (altın etiket: {})

İkisi de soruda geçtiği için "uydurma" sayılmıyor ama ikisi de **yanlış**:
bu sorular bir tarih aralığı istemiyor. Model, hiç görmediği "parametresiz
gecelik sorusu" durumunda eline geçen ilk zaman kelimesini slota koyuyor.

### Düzeltme

`AracTanimi`'ye `parametresiz_sablonlar` alanı eklendi ve
`gecelik_ozet_sorgula` için 15 şablon yazıldı (resmi / günlük / kısaltmalı
/ yazım hatalı karışımı, hiçbirinde tarih ifadesi yok).

Neden ayrı bir alan gerekti: `kategori` ve `tedarikci_id`'de parametresiz
örnekler `"genel"` varlığından geliyor ve şablon dilbilgisel kalıyor.
`tarih_ifadesi`'nde şablonlar baştaki varlığın üstüne kurulu, düşürünce
cümle bozuluyor — *"{varlik}için hazırlanan özeti alabilir miyim?"* →
*"İçin hazırlanan özeti alabilir miyim?"*. Bu durum kendi şablonlarını
istiyor.

`sablonlari_ihrac_et` bunları `varlik_turu="yok"` + boş token ile ihraç
ediyor; kendi varlık türleriyle gitselerdi yeniden çoğaltma adımı onları
tarihlerle çarpar ve kapatılan boşluğu geri açardı.

6 regresyon testi (`tests/test_build_dataset_parametresiz.py`) — biri
parametresiz şablonlarda tarih ifadesi geçmediğini (ters hatayı öğretmemek
için), biri ölçüm setleriyle çakışma olmadığını doğruluyor.

### Kapsamı `gecelik_ozet` ile sınırlama kararı

`siparis_onerisi_sorgula` da 2000/0 görünüyor ama **oraya dokunulmadı**:
`router.py` bu aracı *"belirli bir ürün için ne kadar sipariş verilmeli"*
diye tanımlıyor — parametresiz çağrı sözleşmede yok. Oradaki 0, boşluk
değil tasarım. Ölçüm setlerinde de ürünsüz bir sipariş sorusu yok.

### Yeniden üretim ve kapılar

`router_sorulari.jsonl` yeniden üretildi: **0 satır kayboldu, tam 15 satır
eklendi**, hepsi parametresiz `gecelik_ozet` (yedekle birebir diff'lendi).
`veri_bolme` sonrası:

| bölme | parametreli | parametresiz |
|---|---|---|
| train | 155 | **9** |
| val | 17 | **3** |
| test | 12 | **3** |

Kapılar: `veri_tutarlilik_kontrolu` ✅ (%0,0 uyumsuz sayı),
`golden_set_inceleme` ✅ (train/val sızıntısı yok, 400/400 özgün, guard
uyumu %100). Kalan iki uyarı (`onay_kuyrugu` n=4, `stok.tedarikci_degisim`
boş) önceden bilinen ve kabul edilmiş durumlar.

⚠️ **DÜZELTME (2026-08-08):** bu bölümde önce "`data/colab_yukle/`
yenilendi" yazıyordu — yanlıştı. O klasör `data/egitim/`'in kopyası DEĞİL:
gerekçe dosyaları `training/veri_hazirla.py` ile `istem`/`cevap` biçimine
dönüştürülmüş hâlleridir. Ham dosyalar elle kopyalanınca
`train_lora.ipynb` `KeyError: 'istem'` verir — `veri_hazirla.py`'nin
docstring'i tam olarak bunu uyarıyor. Doğru komut:

    uv run python -m training.veri_hazirla --kaynak data/egitim --hedef data/colab_yukle

Hata bir sonraki turda kapı yeniden koşulduğunda ortaya çıktı; ilk seferinde
kapı kopyalamadan ÖNCE koşturulduğu için görünmemişti. Sıra önemli: önce
dönüştür, sonra kapıyı koştur.

⚠️ **Kalan çekince — oran hâlâ ince.** train'de parametresiz pay %5,5
(9/164); `kritik_stok`'ta bu oran %11. Bu şablonlar henüz paraphrase
turundan geçmedi, yani 15 ham cümle. Özgünlük dersi (bkz. 3. tur bölümü)
burada da geçerli: az çeşitlilik karar sınırını bulanıklaştırıyor. 4. tur
öncesi bu 15 şablon için hedefli bir paraphrase turu koşulması önerilir —
`--sablon-ihrac-araclar gecelik_ozet_sorgula` ile ihraç edilebiliyor.
Boşluk kapandı ama dar; kapanmış olması 0'dan çok daha önemli.

## Guard'ın dil açığı — canlı kuyrukta bulundu (2026-08-08)

Sistem ayağa kaldırılıp onay ekranı (`/onay`) gerçek veriyle incelendiğinde,
hiçbir ölçümün göstermediği bir kusur göze çarptı: **gerekçelerin bir
kısmında Çince/Japonca karakterler vardı.**

    "... ürününün 1.090 gün hareket göstermedikten sonra tafiyetine karar
     verildi ve bu tafiyetine契合したのは24 adet矣。"

Ölçüldü — gerekçesi olan **100 kararın 14'ü (%14)** bozuktu ve **hepsi
`guard_sonucu="gecti"` damgasıyla geçmişti.**

⚠️ Bu oran ilk bakışta %2,8 sanılmıştı; payda yanlıştı. Kuyrukta 500 karar
var ama gerekçe yalnızca üst N karara üretiliyor (`GECELIK_GEREKCE_UST_N`),
yani gerekçesi olan 100 kayıt. Doğru payda o.

### Neden guard yakalamadı

Guard'ın kuralı "metindeki her sayı izinli kümede mi" idi ve bu sağlanıyordu
— `契合したのは24 adet矣` cümlesindeki `24` meşru bir değer. Yani hata guard'ın
**mantığında değil kapsamındaydı**: dil hiç denetlenmiyordu. Mimarinin en
kritik koruması sayı tarafında sağlam, dil tarafında tamamen açıktı.

İkinci bir desen daha vardı: 13 kayıtta gerekçe yerine yalnızca ürün adı
yazılmıştı (*"İnşaat Demiri 10mm - Kardemir"*). Hiç sayı içermediği için o
da sorunsuz geçiyordu.

### Düzeltme

`metni_dogrula()` eklendi, iki kontrol:

1. **Yazı sistemi.** Latin dışı **harf** içeren metin reddedilir. Yalnızca
   harflere bakılıyor, tüm karakterlere değil — `₺ % — “ ”` gibi işaretler
   meşru ve onlara takılmak yanlış alarm üretirdi. Türkçe harfler Unicode'da
   LATIN olarak adlandırıldığı için geçiyorlar. CJK'ya özel bir liste değil:
   Kiril, Arap, Yunan da yakalanıyor.
2. **Asgari içerik.** Ad/kod alanları maskelendikten sonra en az 2 kelime
   kalmalı.

⚠️ İkinci kural **önce yanlış kuruldu**: eşik karakter sayısıydı (15) ve
`"Stok yeterli."` gibi kısa ama bilgi taşıyan meşru bir gerekçeyi kesiyordu.
`test_guard.py`'deki mevcut bir test bunu yakaladı. Karakter eşiği kırılgan
çünkü sınıra yakın meşru metinler var. Kelime sayımı ayrımı keskin yapıyor:
hedeflenen hatada ad maskelenince geriye tire ve boşluktan başka bir şey
kalmıyor (**0 kelime**), meşru en kısa gerekçede **2 kelime** var.

Kontrol bilinçli olarak `sayilari_dogrula`'ya **eklenmedi** — o arayüz Kişi
A'nın etiketleme hattının sözleşmesi ve sade kalmalı. Çalışma zamanı
zincirine bağlandı (`gerekceyi_guvenceye_al`): reddedilen metin bir kez
yeniden üretilir, yine olmazsa şablona düşer. Şablon deterministik ve her
zaman Türkçe, yani güvenli çıkış korunuyor. `contracts.py`'ye de
dokunulmadı (sözleşme değişikliği tek taraflı yapılmaz).

### Doğrulama — canlı veriye karşı

Kural, kuyruktaki 100 gerçek gerekçeye uygulandı:

| | sonuç |
|---|---|
| reddedilen | **14** — hepsi Latin dışı harf, birebir bozuk olanlar |
| geçen | **86** — meşru gerekçelerin tamamı |
| yanlış alarm | **0** |

9 regresyon testi (`tests/test_guard_dil.py`), ikisi kuyruktan alınmış
gerçek metinlerle (biri bozuk, biri sağlam).

⚠️ Bu düzeltme **gelecekte üretilecek** gerekçeleri koruyor; kuyrukta duran
14 bozuk kayıt yerinde duruyor. Onlar 2. tur modelinden kalma ve zaten
yeniden üretilecekler.

## Hedefli paraphrase turu (gecelik_ozet) — çıktının %89'u elendi (2026-08-08)

Parametresiz şablonları çeşitlendirmek için `paraphrase_colab.ipynb` ile
hedefli bir tur koşuldu (Qwen2.5-7B, `VARYANT_SAYISI=24`, 24 şablon).
**102 varyant döndü, 11'i kullanıldı.**

### Neden elendi

**1. Bozuk dil bilgisi.** `"özeten"` (özetleyen değil), `"hazırsınız mı?"`,
`"bildirir miye?"`, `"mevcutsun mu?"`, `"alabilirim mi?"`, `"oldu ne"`.
Yazım hatası şablonlarından türeyenlerde anlamsız kelimeler: `"bisiyer"`.

**2. Niyet tersine dönmüş** — en tehlikelisi:

    "gecelik raporu paylaşır mısınız?"
      -> "gecelik raporu paylaşmayı mı istiyorsunuz?"

Orijinalde kullanıcı rapor istiyor; varyantta sisteme "sen mi paylaşmak
istiyorsun" diye soruluyor. Aynı desen: `"durum özeti nedir?"` →
`"hangi durumu özetlemeniz gerekmektedir?"` (soru, emre dönmüş).

Notebook'un `anlam_korundu_mu()` kontrolü bunları geçiriyor çünkü kelime
örtüşmesine bakıyor — niyet dönünce kelimeler aynı kalıyor. Bu, golden
set'teki yer tutucu hatasıyla aynı sınıftan bir kör nokta: kontrol doğru
şeyi ölçüyor ama yanlış boyutu.

**3. Model 24 varyant üretemiyor.** 24 istendi; en verimli şablonda 8,
birinde **sıfır** geldi. Geçen turda kaydedilen sınırın tekrarı.

### Ölçüm sızıntısı — kapı eklendi

Paraphrase `"Sistem gece ne buldu?"` üretti. Ölçüm setinde
`"Dün gece sistem ne buldu?"` var — **Jaccard benzerliği 0,80.** Eğitime
konsaydı o soruyu sınavdan önce modele göstermiş olurduk ve 4. tur ölçümü
şişerdi.

Mevcut sızıntı testi bunu yakalayamazdı: birebir eşleşmeye bakıyor.
`test_parametresiz_sablonlar_olcum_setine_yakin_degil` eklendi — her eğitim
şablonunun ölçüm sorularına anlamsal yakınlığını ölçüyor.

⚠️ Eşik **ölçülerek** kondu: elle yazılmış şablonlar doğal olarak en fazla
0,33'e çıkıyor (kısa sorular ortak kelime paylaşır), sızıntılı aday 0,80'di.
Sınır 0,50 — ikisinin arasında geniş paylı bir yer. Ayrı bir test de kapının
işlediğini kanıtlıyor: reddedilen o cümleyi alıp "bu geçmemeli" diye sınıyor.

### Sonuç

Sağlam çıkanlar alındı, gerisi elle yazıldı. Parametreli taraf hiç
alınmadı — havuzda zaten 184 satır var, boşluk orada değildi ve o
varyantlar daha da bozuktu.

| | önce | sonra |
|---|---|---|
| parametresiz şablon | 15 | **44** |
| `gecelik_ozet` ham satır | 51 | **81** |
| train'de parametresiz pay | %5,5 | **%18,4** |

(`kritik_stok`'ta bu oran %11 — artık onun da üstünde.)

Stil dağılımı: resmi 15, günlük 14, kısaltmalı 8, yazım hatalı 7.

⚠️ Şablonlar `build_dataset.py` içinde, veri dosyasında değil — veri
`.gitignore`'da olduğu için oraya yazılsa bir Drive senkronunda kaybolurdu.
Böylece git'te kalıcılar.

Kapılar yeniden geçti: `veri_tutarlilik_kontrolu` ✅ %0,0,
`golden_set_inceleme` ✅ (sızıntı yok, 400/400 özgün, guard %100).
`data/colab_yukle/` **`veri_hazirla.py` ile** yenilendi (bkz. yukarıdaki
düzeltme).

**4. tur eğitimi için veri hazır.**

## 4. TUR SONUCU (2026-08-08)

Eğitim: 1.250 adım, 44 dk, dengeli örnekleme (router 2.000 + gerekçe 8.000),
ayarlar 3. turla birebir aynı — **tek değişken veri**.

| | eğitim kaybı | doğrulama kaybı |
|---|---|---|
| 2. tur | 0,1797 | 0,2134 |
| 3. tur | 0,1311 | 0,1750 |
| **4. tur** | 0,1418 | **0,1845** |

Doğrulama kaybı baştan sona düştü, sona doğru yataylaştı — ezberleme yok
(aralık 0,043; 3. turda 0,044).

⚠️ Kayıp 3. turdan **yüksek** ama bu kötü değil: veri kasten zorlaştı
(parametresiz şablon 15→44, `gecelik_ozet` 155→190 satır). Farklı veri
kümesinde ölçülen kayıplar yan yana konmaz. **Kayıp bu projede karar
metriği değil** — 3. tur da kaybı düşürmüştü ve `gecelik_ozet`'i çökertmişti.

### Router ölçümü — 48 soru (taban set 30 + ek set 18)

Aynı sorular, aynı puanlama, sıcaklık 0 + tohum 42, soğuk başlangıç.
Değişen tek şey model.

| | araç doğru | **tam doğru** | uydurma | şema hatası |
|---|---|---|---|---|
| taban | 34/48 · %70,8 | 32/48 · %66,7 | 0 | 0 |
| 3. tur | **39/48 · %81,2** | 33/48 · %68,8 | 3 | 0 |
| **4. tur** | 38/48 · %79,2 | **35/48 · %72,9** | **1** | **3** ⚠️ |

### Araç bazında — hedef tuttu

| araç | n | taban | 3. tur | 4. tur | |
|---|---|---|---|---|---|
| `gecelik_ozet` | 10 | 7 | **1** | **5** | ✅ +4 |
| `onay_kuyrugu` | 8 | 6 | 7 | **8** | ✅ +1 |
| `kritik_stok` | 5 | 3 | 3 | 3 | — |
| `olu_stok` | 5 | 1 | 4 | 4 | — |
| `siparis_onerisi` | 5 | 4 | 4 | 4 | — |
| `genel_stok_durumu` | 10 | 8 | 10 | 9 | ⚠️ −1 |
| `tedarikci_performansi` | 5 | 3 | 4 | **2** | ⚠️ −2 |

**Bu turun sebebi olan çöküş onarıldı: 1/10 → 5/10.** Tabanın 7/10'una tam
dönülmedi, ama üçte ikisi geri alındı — ve bu **veriyle** yapıldı, model
ayarıyla değil. Kapsama boşluğunu kapatmak işe yaradı.

### ⚠️ Açık gerileme: şema kırılganlığı

3. turda 0 olan şema hatası 4. turda **3**. Üçü de tekrar üretilebiliyor:

    "Aylardır dönmeyen mal var mı elimizde?"  -> sema uyumsuz (2 deneme)
    "T-0031 güvenilir mi?"                    -> sema uyumsuz (2 deneme)
    "t-0007 gecikiyomu"                       -> sema uyumsuz (2 deneme)

`tedarikci_performansi`'nin 4→2 düşüşünün 2'si tam bu üçünden geliyor;
yani ayrı bir sorun değil, aynı kırılganlığın belirtisi.

**Yine de tur4 tercih edildi:** şema hatası "yanlış cevap" değil, "cevap
verememe" — sistem sessizce yanlış araç çağırmıyor, açıkça düşüyor. Bu
projenin felsefesi güvenli başarısızlığı yanlış cevaba tercih ediyor ve
tur4 toplamda daha az yanlış veriyor (35/48 vs 33/48).

### 5. tur için asıl fikir: biçim modelde değil, grammar'da

Şema zorlamasını **kapatıp** ham çıktıya bakınca çarpıcı bir şey görüldü:

    tur4 -> "Aracim acil olmakta, bu konunun detayli versiyonunu..."
    tur3 -> "T-0031 tedarikçisinin performansı hakkında bilgi verebilir miyim?"

**Her iki model de düz Türkçe cümle üretiyor, JSON değil.** Yani JSON
biçimini modelden çok Ollama'nın grammar zorlaması taşıyor. Eğitim, biçim
tarafını yeterince öğretmemiş; grammar kısıtı sıkıştırdığında model
tanımadığı bir yola giriyor ve bazen çıkamıyor — şema kırılganlığının
muhtemel kökü bu.

5. turun hedefi daha çok veri değil, **biçim öğretimi** olmalı: router
örneklerinin oranını yükseltmek (şu an 2.000/10.000 = %20) ve/veya cevabı
üretmeden önce biçimi zorlayan bir istem düzeni denemek.

### KARAR: 3. turda kalındı — 4. tur gerekçe tarafını bozdu

Benchmark'ta bir satır dikkat çekti:

    20 gerçek karar örneklendi, 11 LLM'den (şablona düşmeden) kabul edildi

3. turda bu **20/20**'ydi. Sert kapı yine de geçti (uydurma sayı 0) çünkü
şablon güvenli — ama 20 gerekçenin 9'u modelden değil şablondan geliyor
demek.

⚠️ **İki açıklama vardı ve ayırmadan karar verilemezdi:** bugün guard'a dil
kontrolü eklendi ve 3. turun 20/20'si o kontrolden **önce** ölçülmüştü.
Düşüşün sebebi model de olabilirdi, yeni kontrol de.

Ayrım için iki model **aynı guard'la, aynı 20 kararla** koşuldu:

| model | kabul | şablona düştü |
|---|---|---|
| `tur3` | **20** | 0 |
| `tur4` | 11 | **9** |

Guard masum. **4. turun gerekçe tarafı gerçekten bozuldu.**

Reddedilenlerde `reddedilen_sayilar=[]` — yani sayısal guard temiz geçti,
sorun sayı uydurma değil metnin kendisi. Ham çıktıda parça cümleler ve
İngilizce kelime karışması görüldü (*"293 days, 19 adet, 5.220,32 TL,
50% iskonto"* — bu örnek guard'dan **geçmişti** bile).

### Karar ve gerekçesi

| | 4. tur kazancı | 4. tur bedeli |
|---|---|---|
| router | tam doğruluk 33 → **35**/48 · `gecelik_ozet` 1/10 → **5/10** | 3 şema hatası (tur3: 0) |
| gerekçe | — | kabul oranı **20/20 → 11/20** · akıcılık 4,8 → 4,6 |

**Gerekçe yüzeyi router'dan çok daha geniş**: her karar bir gerekçe
üretiyor, router ise yalnızca kullanıcı soru sorunca çalışıyor. 48 soruda
+2 doğru, açıklamaların %45'ini tahtalaştırmaya değmez.

`.env` `codifya-router:tur3`'te bırakıldı. `codifya-router:tur4` Ollama'da
duruyor, silinmedi.

### ⭐ 5. tur için asıl bulgu: iki görev kapasite için yarışıyor

Kritik gözlem: **gerekçe verisi 3. ve 4. tur arasında hiç değişmedi.**
`gerekce_train.jsonl` iki turda da aynı 40.293 satır, örnekleme de aynı
(8.000). Değişen tek şey **router** verisiydi.

Buna rağmen gerekçe kalitesi düştü. Sebep tek model olması: router ve
gerekçe aynı LoRA ağırlıklarını paylaşıyor (`r=16`, eğitilebilir parametre
%1,18). Router verisi çeşitlenip zorlaşınca kapasitenin daha büyük bir
kısmını tüketti ve gerekçe tarafı bunun bedelini ödedi.

Bu, "daha çok/iyi veri her zaman daha iyi model" varsayımının bu ölçekte
kırıldığı yer. 5. tur için üç seçenek:

1. **LoRA rank'ı yükselt** (`r=16` → 32 veya 64) — en ucuz deneme, kapasite
   darboğazı hipotezini doğrudan sınar
2. **Görev oranını ayarla** — router şu an 2.000/10.000 (%20); gerekçe
   payını korurken router çeşitliliğini artırmanın yolu aranmalı
3. **İki ayrı adaptör** — aynı taban model, göreve göre farklı LoRA. Yönetim
   yükü artar ama kapasite yarışı biter

⚠️ Hangisi seçilirse seçilsin, **her turda İKİ tarafı da ölçmek zorunlu.**
Bu tur bunu öğretti: router ölçümü tek başına bakılsa 4. tur "başarılı"
görünüyordu.

### 4. turun kalıcı kazancı: veri düzeltmeleri

Model geri alındı ama **veri tarafındaki iş duruyor ve git'te kalıcı**:

- `gecelik_ozet` parametresiz kapsama boşluğu kapatıldı (184/0 → 184/35)
- parametresiz şablon 15 → 44
- ölçüm setine anlamsal yakınlık kapısı eklendi
- uydurma dedektöründeki aksan hatası düzeltildi
- guard'a dil kontrolü eklendi

Bunlar 5. turda da geçerli. Kapatılan boşluğun **işe yaradığı da kanıtlandı**
— `gecelik_ozet` 1/10'dan 5/10'a çıktı. Sorun düzeltmede değil, o
düzeltmenin tek modelde gerekçe tarafına yansıyan bedelinde.

## 5. TUR — kapasite hipotezi ÇÜRÜTÜLDÜ (2026-08-08)

4. tur şunu bulmuştu: gerekçe verisi hiç değişmediği hâlde gerekçe kalitesi
düştü, sebebi muhtemelen router ve gerekçenin aynı LoRA kapasitesini
paylaşması. 5. tur bunu sınadı.

**Tek değişken LoRA rank'ı:** `r=16 → 32`, `alpha=32 → 64`. Veri, örnekleme,
adım sayısı (1.250), öğrenme oranı, tohum — hepsi 4. turla birebir aynı.
Devam-etme testi ikisinde de atlandı (aynı başlangıç noktası).

| tur | rank | eğitim kaybı | doğrulama | adaptör |
|---|---|---|---|---|
| 4 | 16 | 0,1418 | 0,1845 | 81 MB |
| 5 | **32** | 0,1399 | 0,1831 | **152 MB** |

Kayıp neredeyse hiç oynamadı — ilk uyarı işareti buydu.

### Router: en iyi sonuç

| | araç doğru | **tam doğru** | şema hatası |
|---|---|---|---|
| taban | 34/48 · %70,8 | 32/48 · %66,7 | 0 |
| 3. tur | 39/48 · %81,2 | 33/48 · %68,8 | 0 |
| 4. tur | 38/48 · %79,2 | 35/48 · %72,9 | 3 |
| **5. tur** | **39/48 · %81,2** | **36/48 · %75,0** | 3 |

| araç | n | taban | 3. tur | 4. tur | **5. tur** |
|---|---|---|---|---|---|
| `gecelik_ozet` | 10 | 7 | 1 | 5 | **7** ✅ |
| `kritik_stok` | 5 | 3 | 3 | 3 | **4** |
| `olu_stok` | 5 | 1 | 4 | 4 | 4 |
| `onay_kuyrugu` | 8 | 6 | 7 | 8 | 7 |
| `genel_stok_durumu` | 10 | 8 | 10 | 9 | 8 |
| `tedarikci_performansi` | 5 | 3 | 4 | 2 | **2** ⚠️ |

`gecelik_ozet` **taban seviyesine tam döndü** (1 → 5 → 7). Router tarafında
5. tur dört modelin en iyisi.

### ⭐ Ama hipotez çürüdü

| tur | rank | gerekçe kabul (20 karar) |
|---|---|---|
| 3 | 16 | **20/20** |
| 4 | 16 | 11/20 |
| **5** | **32** | **7/20** |

**Kapasiteyi iki katına çıkarmak gerekçe tarafını DAHA DA bozdu.** Hipotez
doğru olsaydı 20/20'ye dönmesi beklenirdi; tam tersi oldu.

Akıcılık puanı yükseldi (4,86) ama bu yanıltıcı: yalnızca **7 örnek**
puanlandı, çünkü diğer 13'ü şablona düşmüştü. Az sayıda kabul edilen metnin
ortalaması yüksek çıkıyor — kabul oranı düştükçe bu gösterge şişiyor.

### Yeni yorum: sorun kapasite değil, GİRİŞİM

İki turluk kanıt şunu söylüyor:

    veri degisikligi (tur3 -> tur4):  20/20 -> 11/20
    rank iki katina  (tur4 -> tur5):  11/20 ->  7/20

Kapasite artınca model router görevine **daha güçlü** oturuyor ve o görevin
biçimi (kısa, yapılandırılmış JSON) serbest Türkçe düzyazı üretimini daha çok
bastırıyor. Yani iki görev kapasite için yarışmıyor — birbirine **karışıyor**.
Daha fazla kapasite karışmayı azaltmıyor, güçlendiriyor.

Bu, `r=64` denemesini de anlamsız kılıyor: aynı yönde daha kötü sonuç verir.

### Karar

`.env` `codifya-router:tur3`'te kaldı. `tur4` ve `tur5` Ollama'da duruyor.

**6. tur için tek makul yol: iki ayrı adaptör.** Aynı taban model, göreve göre
farklı LoRA — router için bir tane, gerekçe için bir tane. Karışma fiziksel
olarak imkânsız hale gelir. Yönetim yükü artar (iki adaptör, iki GGUF ya da
çalışma zamanında adaptör değiştirme) ama elimizdeki iki turluk kanıt başka
yol bırakmıyor.

⚠️ **Bu turun asıl değeri, ucuz bir çürütme olması.** Bir saatlik GPU turu,
"rank'ı büyütelim" fikrinin yanlış olduğunu kesin olarak gösterdi. O fikri
sınamadan iki adaptöre geçseydik, işe yaramayan bir karmaşıklığı kalıcı
olarak üstlenmiş olabilirdik.

## ⭐ DÜZELTME: 4. ve 5. tur haksız yere geri alındı (2026-08-08)

Yukarıdaki iki bölümde 4. ve 5. turun "gerekçe tarafını bozduğu" yazıyor ve
iki ayrı sebep öne sürülüyor: önce **kapasite darboğazı**, sonra **görev
girişimi**. **İkisi de yanlıştı.** Gerçek sebep bulundu ve düzeltildi.

### Nasıl bulundu

"Değerler neden azalıyor?" sorusunu tahminle değil ölçerek cevaplamaya
çalışırken, reddedilen metinlerin ham hâline bakıldı. Şaşırtıcı şey şuydu:
**modeli doğrudan çağırınca 20 kararın 20'si de temiz metin üretiyordu.**
Ama benchmark aynı modelde 13'ünü şablona düşürüyordu.

Fark, çağrı yolundaydı. `gerekce_uret` → `llm_ureteci` → `yapilandirilmis_uret`:
gerekçe üretimi de **JSON şema zorlamasıyla** yapılıyordu. Benim doğrudan
çağrım şemasızdı.

### Kök neden: eğitim/çalışma zamanı biçim uyuşmazlığı

    egitim hedefi (veri_hazirla) :  "Porselen Karo - Vitra urununun 97 gun..."
    calisma zamani (GerekceCiktisi):  {"gerekce": "..."}   <- HIC GORULMEDI

Model `{"gerekce": ...}` sarmalayıcısını eğitimde hiç görmedi. Ollama'nın
grammar kısıtı onu tanımadığı bir kalıba sokuyordu. 3. tur buna dayanabildi,
4. ve 5. tur dayanamadı.

⚠️ Bu, **2. turun kök nedeniyle aynı sınıftan** bir hata: eğitimin öğrettiği
ile çalışma zamanının istediği şeyin farklı olması. O sefer sayılarda oldu,
bu sefer biçimde.

### Kontrollü deney

Aynı 20 karar, aynı istem, aynı guard zinciri, aynı model. **Tek değişken
JSON şeması:**

| model | şemalı | şemasız |
|---|---|---|
| `tur3` | 20/20 | 20/20 |
| `tur4` | 11/20 | **20/20** |
| `tur5` | 7/20 | **20/20** |

Şema kaldırılınca **üçü de 20/20.** Modeller hiç bozulmamıştı; kısıt bozuktu.

### Düzeltme

`llm_ureteci` eğitilmiş kipte artık JSON şeması kullanmıyor, düz üretim
yapıyor. **Taban kipte şema duruyor** — orada gerçek bir işi var (B2.1'de
ölçüldü: taban model düz metin istendiğinde girdiyi liste hâlinde geri yazıp
başına başlık ekliyordu).

Biçim güvencesi kaybolmadı: guard metni doğruluyor (sayı + dil),
`ilk_cumleleri_al` fazla cümleyi kırpıyor, geçmezse şablona düşülüyor. Şema
üçüncü bir kemerdi ve eğitilmiş modelde faydadan çok zarar veriyordu.

### Yol boyunca bulunan ikinci hata

Testler `Ayarlar()` üzerinden `.env`'i okuyordu, yani `LLM_ISTEM_BICIMI`
değişince test davranışı **sessizce** değişiyordu. Sınıf varsayılanı `taban`
olduğu için bu fark uzun süre görünmemişti. Artık her test istem biçimini
açıkça veriyor.

`test_egitilmis_kipte_sema_kullanilmiyor` eklendi: isteğe `format` alanının
eğitilmiş kipte konmadığını, taban kipte konduğunu doğruluyor — düzeltmenin
sessizce geri alınmasını engelliyor.

### Yeni karar: 5. tur canlıya alındı

| model | router tam doğru | gerekçe kabul |
|---|---|---|
| taban | 32/48 · %66,7 | — |
| 3. tur | 33/48 · %68,8 | 20/20 |
| 4. tur | 35/48 · %72,9 | 20/20 |
| **5. tur** | **36/48 · %75,0** | **20/20** |

5. tur router'da dört modelin en iyisi ve artık gerekçe bedeli yok.
`gecelik_ozet` 1/10 → 5/10 → **7/10** ile taban seviyesine tam döndü.

### Ders

⚠️ **Bir turu "başarısız" ilan etmeden önce ölçüm yolunu da sorgula.** İki
tur, model kusuru sanılan bir altyapı hatası yüzünden geri alındı. İkisi de
aslında iyileşmeydi.

Beni yanlış yola sokan şey, hipotezi veriye bakmadan kurmamdı: önce
"kapasite", tutmayınca "girişim" dedim. İkisi de tabloyu açıklıyordu ama
ikisi de yanlıştı. Doğru cevap ancak **reddedilen metnin kendisine** bakınca
çıktı — ve o bakış on dakika sürdü.

## ⭐ PARA METRİĞİ — projenin iş değeri sayısı (2026-08-08)

Yol haritasının "başarı metrikleri" tablosundaki son satır, ve bugüne kadar
hiç hesaplanmamıştı:

> *"Raporun merkezine 'model şu kadar iyi cevap veriyor' değil, **'AI politikası
> toplam stok maliyetini %X düşürdü'** konur. İş değerini gösteren tek sayı bu."*

    uv run python -m training.genellenebilirlik_ve_para_metrigi

### Faz 5 — ana sonuç (tutulmamış seed=20250801, 3 yıl, 1.095 gün)

| | vasat | **kural motoru** | oracle |
|---|---|---|---|
| stok tükenme oranı | %5,31 | **%0,47** | %0 |
| kayıp kâr | 7.688.130 TL | **3.819.706 TL** | 197.585 TL |
| aşırı stok maliyeti | 9.406.976 TL | 12.414.508 TL | 8.702.393 TL |
| sipariş maliyeti | 1.720.950 TL | 1.161.150 TL | 6.003.150 TL |
| sipariş sayısı | 11.473 | **7.741** | 40.021 |
| **toplam maliyet** | **18.816.055 TL** | **17.395.365 TL** | 14.903.128 TL |

**Toplam maliyet %7,6 düştü; stok tükenme oranı 11 kat azaldı (%5,31 → %0,47).**

⚠️ **Kural motoru daha FAZLA stok tutuyor** (aşırı stok maliyeti 9,4M → 12,4M).
Bu bir kusur değil, bilinçli takas: emniyet stoğu bırakıp müşteri kaybını
önlüyor. Kayıp kâr yarıya iniyor (7,7M → 3,8M) ve net sonuç kârlı çıkıyor.
Ayrıca **%33 daha az sipariş** veriyor (11.473 → 7.741) — daha büyük, daha
seyrek, daha ekonomik partiler.

Yani sistem "stoğu kıs, para bağlama" gibi ezber bir kural işletmiyor;
gerçekten EOQ/ROP hesabı yapıyor.

### Faz 4 A4.2 — aşırı uyum testi: 9/9 geçti

Kural motoru yalnızca varsayılan profile göre ayarlanmış olabilirdi. Dört
profil × üç tohum ile sınandı; kriter her kombinasyonda vasat'tan **hem daha
az tükenme hem daha az maliyet**:

| profil | maliyet iyileşmesi |
|---|---|
| `kucuk_nalbur_dukkani` | %1,4 – %3,2 |
| `yapi_malzemesi_toptancisi` | %15,0 – %19,5 |
| `buyuk_insaat_deposu` | **%39,1 – %44,7** |

**9 kombinasyonun 9'u geçti.**

⭐ Anlamlı örüntü: **kazanç şirket büyüdükçe artıyor.** Küçük nalburda fark
küçük (az SKU, sahip kafadan takip edebiliyor), büyük depoda %40'a çıkıyor.
Sistemin asıl müşterisi bu segment — ve bu, satış anlatısının da dayanağı.

### ⚠️ Bu sayı LLM'den bağımsız

Hesabı **kural motoru** yapıyor. Bugün beş eğitim turu uğraştığımız dil
modelinin bu sayıya hiçbir katkısı yok; model yalnızca kararı Türkçe
anlatıyor.

Yani sistemin iş değeri, dil katmanı hiç çalışmasa bile ayakta. Mimarinin
birinci kuralı ("LLM asla sayı üretmez") burada karşılığını buluyor: router
doğruluğu %75'te takılı olsa da **iş değeri etkilenmiyor**.

Bu, `threshold` moduna geçiş tartışmasını da değiştiriyor: açık olan sert
kapı (router %95) iş değerini değil, kullanıcı deneyimini sınırlıyor.

## Faz 4.3 — Shadow mod raporu (2026-08-08)

    uv run python -m app.jobs.shadow_raporu

Bu, para metriğinden **farklı bir şey** ölçüyor. Para metriği simülasyonu
baştan koşturup üç politikayı sentetik veride karşılaştırıyor — kapsamlı ama
sentetik. Shadow raporu ise sistemin `shadow` modda **gerçekten ürettiği** ve
DB'ye yazdığı kararları alıp "vasat taban politika ne derdi" sorusunu
soruyor — dar ama gerçek çalışma zamanı verisi.

| | |
|---|---|
| toplam karar | 9.908 |
| yön uyuşması | 8.855 · **%89,4** |
| toplam tutar farkı | +6.752.672 TL |

### ⭐ Anlaşmazlıklar TEK YÖNLÜ

1.053 farklı kararın dağılımı:

| durum | adet |
|---|---|
| sistem sipariş veriyor, vasat vermiyor | **1.053** |
| vasat sipariş veriyor, sistem vermiyor | **0** |
| ikisi de veriyor, miktar farklı | 0 |

**Sistem hiçbir kararda vasat politikadan az sipariş önermiyor.** Fark
tamamen, vasat politikanın kaçırdığı durumları yakalamaktan geliyor.

Bu iki şeyi birden açıklıyor:

1. **Para metriğindeki mekanizma.** Stok tükenmesi %5,31 → %0,47'ye bu yüzden
   iniyor: sistem, basit kuralın "daha var" dediği ama tedarik süresi
   belirsizliğiyle birlikte bakınca riskli olan noktaları yakalıyor. Aşırı
   stok maliyetinin artması (9,4M → 12,4M) da aynı davranışın bedeli.

2. **Benimseme riski.** Bir pilot müşteri açısından kritik cümle şu: *sistem
   size hiçbir zaman "daha az sipariş verin" demiyor.* Mevcut pratiğe göre
   yalnızca ekleme yapıyor. "Ya sistem yanılır da stoksuz kalırsam" endişesi
   bu veriyle karşılanabiliyor.

⚠️ Bu rapor simülatörden beslenen kararlar üzerinde koşuldu. Gerçek veride
tekrarlanması gerekiyor (bkz. `app/adapters/csv_erp.py`) — ama ölçüm hattı
artık hazır ve gerçek veri gelir gelmez aynı komut koşulabilir.

### Faz 4 tamamlandı

| # | görev | durum |
|---|---|---|
| 4.1 | hata yönetimi / LLM çökerse devam | ✅ `test_model_kapaliysa_sablona_dusuyor` |
| 4.2 | 3 profille aşırı uyum testi | ✅ 9/9 |
| 4.3 | shadow mod raporu | ✅ **bu bölüm** |
| 4.4 | karşılanamayan talep + aşırı stok maliyeti | ✅ para metriğinde |
| 4.5 | onay ekranı | ✅ `/onay` |
| 4.6 | ERP entegrasyon sözleşmesi | ✅ `ERP-ENTEGRASYON.md` |

## FAZ 6 · Finans & Tahsilat alanı tamamlandı (2026-08-09)

Yol haritasının Faz 6 için öngördüğü altı adımın altısı da bitti. Asıl soru
şuydu: **kalıp taşınıyor mu, yoksa stok varsayımları her yere mi sinmiş?**

### Taşınan: sınıflandırma ve emniyet payı matematiği

`ABCSinifi` ve `XYZSinifi` **yeniden yazılmadı**, yeniden kullanıldı:

| eksen | stokta | finansta |
|---|---|---|
| ABC | ürünün ciro katkısı | müşterinin ciro katkısı |
| XYZ | talep oynaklığı | **ödeme gecikmesi oynaklığı** |

İkisi de aynı soruyu soruyor: *bu kalem tahmin edilebilir mi?* Düzenli geç
ödeyen müşteri (hep 40 gün) rastgele ödeyenden (10-90 gün) daha az
risklidir, ortalaması kötü olsa bile.

Emniyet payı formülü de taşındı — `scipy.stats.norm` çağrısı bile ortak:

    stok  : emniyet     = Z(servis_seviyesi) x sqrt(tedarik_suresi x talep_std^2 + ...)
    finans: emniyet_gun = Z(tahsilat_hedefi) x odeme_gecikmesi_std

⚠️ Ama **yön ters ve bu bilinçli.** Stokta belirsizlik erken davranmayı
gerektirir (stok tükenmesin). Finansta eşik bir **anomali dedektörü**:

    hep 20±2 gunde odeyen  -> 40 gun ALARM   (esik ~23 gun)
    0-90 arasi savrulan    -> 40 gun normal  (esik ~68 gun)

İkincisini erken aramak istatistiksel olarak anlamsız; o müşteride 40 gün
gürültüden ayırt edilemez. Düzensiz ödeyen **başka bir kolla** yakalanıyor:
risk skoru oynaklığı cezalandırıp `kredi_limiti_dusur` tetikliyor.
Öngörülemezliği daha sık arayarak değil, maruz kalınan riski azaltarak
yönetiyoruz.

⚠️ Bu ayrım kodda doğruydu ama **docstring'de yanlış yazılmıştı** ("düzensiz
ödeyeni daha erken ara"). Deneyde fark edildi ve düzeltildi.

### Bulunan dört sızıntı — hepsi aynı desende

Faz 1-5 boyunca alan-bağımsız katmanlar stoka özgü alanları **doğrudan**
okuyordu. Finans eklenince her biri ayrı bir kırılma noktası oldu:

| katman | sızıntı | ne olurdu | çözüm |
|---|---|---|---|
| `guard.py` | `sku_adi`, `tedarikci_adi` | `AttributeError` | `maskelenecek_alanlar()` |
| `policy.py` | `ozellikler.tedarikci_onayli` | `AttributeError` | `oto_uygulama_engeli()` |
| `policy.py` | `is KararTipi.STOK_AKSIYON_YOK` | **"aksiyon yok" kararı oto-uygulanır** | `tip.aksiyon_yok_mu` |
| `nightly.py` | `o.sku_adi` | **gecelik işin tamamı düşer** | `gorunen_ad` |

Üçüncü ve dördüncüsü sessiz felaketlerdi: biri hiçbir şey yapmayan bir
kararı "uygulandı" diye kaydederdi, diğeri kullanıcıya sabah boş ekran
gösterirdi.

`AlanOzellikleri` taban sınıfının dört davranışı bu dört ihtiyaçtan doğdu —
hiçbiri spekülatif değil. Üçüncü alan (satış) eklenirken bu listenin
değişmesi beklenmiyor.

### Bulunan güvenlik açığı

`DAIMA_ONAY_GEREKTIREN` yalnızca stok tiplerini taşıyordu.
`finans.karsilik_ayir` bir **muhasebe kaydıdır** (geri almak düzeltme fişi
ister, `stok.tasfiye`nin birebir karşılığı) ama listede yoktu — tutar ve
güven eşiklerinin altında kalırsa **sessizce oto-uygulanabilirdi**.
`kredi_limiti_dusur` de aynı sınıfta. İkisi de eklendi.

Test **karşıt kontrolüyle** yazıldı: tahsilat takibi (müşteriyi aramak,
geri alınabilir) küçük tutarda hâlâ oto-uygulanabiliyor. Aksi hâlde "her
şey onaya gidiyor" diye de geçerdi ve hiçbir şey kanıtlamazdı.

### Tahsilat simülatörü — stok RNG'sine dokunulmadı

`run.py` faturayı zaten üretiyordu (tarih, tutar, vade) ama tahsilatı hiç
modellemiyordu. Fatura döngüsüne müşteri ataması eklemek `tedarik_rng`'den
fazladan bir çekim demekti ve **stok tarafındaki her ölçüm değişirdi** —
para metriği (%7,6), shadow raporu (9.908 karar), aşırı uyum testi (9/9).

Bu yüzden tahsilat ayrı bir modül, kendi RNG'siyle, `run.py`'nin çıktısını
sonradan işliyor. Bir test bu bağımsızlığı kalıcı hale getiriyor.

Patoloji ayrımı ölçüldü:

| patoloji | ortalama gecikme | değişim katsayısı |
|---|---|---|
| `kronik_gecikme` | **39,2 gün** | **0,25** — kötü ama öngörülebilir |
| `duzensiz_odeme` | 19,6 gün | **1,39** — asıl riskli |
| normal | 12,4 gün | 0,98 |

⚠️ Segment adları ilk yazımda **uydurulmuştu** (`perakende`, `bayi`,
`müteahhit`); gerçekte `bireysel`, `usta`, `perakendeci`, `santiye`.
Hiçbiri eşleşmedi, her müşteri varsayılana düştü ve segment farklılaşması
**sessizce** çalışmadı. Düzeltildi; `test_segment_adlari_profille_uyusuyor`
bir daha açılmasını engelliyor.

### Uçtan uca sonuç

800 müşteri, gerçek simülasyon verisiyle:

| karar | adet |
|---|---|
| aksiyon yok | 760 |
| tahsilat takibi | 23 |
| karşılık ayır | 16 |
| kredi limiti düşür | 1 |

Gecelik tarama iki alanı **tek listede** birleştiriyor (2.800 karar).
Ayrı bir finans işi açılmadı: kullanıcı sabah "bugün neye bakmam lazım?"
sorusunun cevabını alan başına bölünmüş görmemeli. Sıralama risk skoruna
göre olduğu için alanlar arası önceliklendirme kendiliğinden doğru.

Finans tarafında hata olursa tarama **stokla devam ediyor** — bir alanın
sorunu diğerinin çıktısını yok etmemeli.

### Kalan tek adım

Router'ın finans araçlarını tanıması için eğitim. Yol haritası bunu **üç
alan bitince tek turda** yapmayı söylüyor (`alanları ayrı modellere bölme —
16 GB'ta gereksiz yük`), o yüzden Satış ve Üretim'den sonra.

---

# Faz 8 — A paketi ölçümleri (2026-08-10)

> Bu bölüm bir günün ölçüm kaydı. Her satır bir sorunun cevabı; sonucu
> olumsuz olanlar da burada, çünkü olumsuz sonuç da ölçümdür.

## Finans: iş değeri (1 yıl, aylık inceleme)

| profil | taban | vasat | kural_motoru | vasata göre |
|---|---|---|---|---|
| küçük nalbur | 228.696 | 232.413 | 247.699 | %-6,6 |
| yapı toptancısı | 5.578.239 | 5.438.518 | 5.649.408 | %-3,9 |

Batak zararında kural motoru her iki profilde önde (178.415 vs 186.745 ·
4.478.426 vs 4.631.836). Kaybettiği kalem marj kaybı (limit kolu bedeli).

## Limit kolu: iki kez ölçüldü, iki farklı cevap

**A7.1 — eşik/kesinti taraması** (kol ne kadar tetiklenirse o kadar zarar):

| eşik | limit kararı | marj kaybı | vasata göre |
|---|---|---|---|
| kapalı | 0 | 0 | %-2,4 |
| 30 | 12 | 1.748 | %-3,1 |
| 45 | 165 | 24.215 | %-6,1 |
| 60 | 305 | 50.048 | %-16,0 |

**A5 — risk taraması** (kol açık vs kapalı, net katkı TL):

| batak oranı | 1 yıl | 3 yıl |
|---|---|---|
| %2 | -8.543 | +18.309 |
| %5 | +31.445 | +67.109 |
| %10 | +18.644 | +96.541 |

Karar: kol **açık**. Belirleyici çoğunluk değil kaybın asimetrisi —
gereksizken açık olmak 8.543 TL, gerekliyken kapalı olmak 96.541 TL.

## Duyarlılık: takip maliyeti

| takip maliyeti | vasat | kural_motoru | fark |
|---|---|---|---|
| 0 TL | 214.113 | 220.499 | %-3,0 |
| 50 TL | 220.213 | 226.349 | %-2,8 |
| 150 TL | 232.413 | 238.049 | %-2,4 |
| 400 TL | 262.913 | 267.299 | %-1,7 |
| 1.000 TL | 336.113 | 337.499 | %-0,4 |

Beş noktada da kaybediyor → sonuç parametre seçiminin eseri değil.

## İş gücü (A1)

| | vasat | kural_motoru |
|---|---|---|
| takip saati | 40,7 | 39,0 |
| kurtarılan fatura | 74 | 81 |
| kurtarılan tutar | **8.437 TL** | 6.606 TL |
| saat başına | **207 TL** | 169 TL |

⚠️ Adet aldatıyor: motor daha çok fatura kurtarıyor, daha az para.
§12'den sonra bu tablo da geçersiz — sistem artık daha çok arıyor.

## Maddiyet kolu (§12)

| | küçük nalbur | yapı toptancısı |
|---|---|---|
| kapalı | 246.592 | 5.705.491 |
| açık | 247.699 | **5.649.408** |
| takip sayısı | 121 → 136 | 650 → **1.305** |

Küçük profilde zarar, büyük profilde kazanç. Tek profilde ölçülseydi
yanlış karar verilirdi.

## Stok tarafı

- Ölü stok eşiği `max(mutlak, göreceli)` — finanstaki kusurun karşılığı
  **yok** (orada `min` yazılmıştı).
- Stoksuzluk artık ölü stok sayılmıyor (§11): elde en az 1 günlük talebi
  karşılayacak mal olmalı.
- `stok.tedarikci_degisim` artık üretiliyor (§5), ortogonal kol olarak.

## Geriye dönük test hattı (§13)

İlk deneme koşusu: duyarlılık 1,00 — **ama sipariş önerisi oranı da 1,00**.
Yani sayı iyiliği değil ayrımsızlığı gösteriyordu. İki sayı birlikte
okunmalı.

---

## Faz 12 · Genel arayüz — araç eklemenin ölçülmüş sınırı (2026-08-12)

Ölçüm: `uv run python -m training.eval.router_taban --etiket faz12-tur6`
Ham sonuç: `training/eval/router_sonuc_faz12-tur6.json`
Soru seti: `router_taban_sorulari.jsonl` — **30 soruda donmuş, değiştirilmedi**

Üretim ve planlama araçları `AracAdi`'ye eklendi (4 yeni araç). Sorulan soru:
mevcut araçlardaki doğruluk bozuldu mu?

| Ölçüt | tur5 | faz12-tur6 |
|---|---|---|
| Araç doğru | %80,0 | **%86,7** |
| Araç + parametre tam | %73,3 | **%80,0** |
| Şema hatası | 2 | 2 |

**Bozulma yok.** ⚠️ Ama iyileşmeyi araç eklemeye bağlamak **yanlış olur**:
iki koşu arasında iki şey değişti (model tur5→tur6 ve araç listesi). Aynı
30 soruyla tur6 taban çizgisi hiç alınmamıştı, dolayısıyla ikisi ayrıştırılamaz.
Söylenebilecek tek şey: **araç eklemek mevcut doğruluğu düşürmedi.**

### ⭐ Asıl bulgu: yeni araçlar eğitilmiş kipte ULAŞILAMAZ

Model 30 sorunun hiçbirinde yeni araçlardan birini seçmedi:

```
modelin sectigi araclar: gecelik_ozet, genel_stok_durumu, kritik_stok,
                         olu_stok, onay_kuyrugu, siparis_onerisi,
                         tedarikci_performansi
YENI araclardan secilen: HICBIRI
```

Bu bir kusur değil, mimarinin sonucu. Eğitilmiş kipte istem araç listesi
**taşımıyor** (`router.py::egitilmis_istem` — 600 token yerine 20). Model
yalnızca ağırlıklarına işlenmiş adları üretebiliyor ve üretim araçlarını
eğitimde hiç görmedi.

Sonuç sözleşmeye yazıldı: `schemas.py::EGITILMIS_ARAC_ADLARI`. İki küme
artık ayrı ve testi var:

    AracAdi                -> calistirilabilir araclarin tamami (11)
    EGITILMIS_ARAC_ADLARI  -> modelin secebildikleri (7)

⚠️ Bir aracı `AracAdi`'ye eklemek onu **çalıştırılabilir** yapar, modelin
onu **seçebilir** olmasını sağlamaz. İkisini bir tutmak, "model bunu da
seçer" yanılgısını doğurur.

### Bunun pratik karşılığı

Genel arayüzün iki yarısı var ve **güvenilirlikleri farklı**:

| katman | nasıl çalışıyor | güvenilirlik |
|---|---|---|
| araç çalıştırma (`app/llm/araclar.py`) | araç adı → fonksiyon | deterministik, LLM'siz |
| araç seçimi (router) | Türkçe soru → araç | %86,7 ve 7 araçla sınırlı |

Yeni araçlara model üzerinden ulaşmak için iki yol var:

1. `llm_istem_bicimi="taban"` — istem araç listesi taşıyor, hepsi
   seçilebiliyor. ⚠️ Genel doğruluğu daha düşük (tur öncesi %70).
2. Yeni bir eğitim turu — üretim/planlama soruları eğitim verisine girer.
   ⚠️ Colab bağımlı ve tur 4-7 saat.

Karar verilmedi; ölçüm önce yapıldı çünkü ölçüm ucuz, eğitim turu pahalı.
