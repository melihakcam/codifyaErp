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
