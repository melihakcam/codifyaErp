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

### Sonuç

| Ölçüt | Değer | Faz 5 hedefi |
|---|---|---|
| **Araç doğru** | **22/30 · %73,3** | — |
| **Araç + parametre tam eşleşme** | **21/30 · %70,0** | **> %95** |
| Şema hatası (yönlendirilemedi) | 1 | — |
| Toplam süre | 52,8 sn | — |

Hedefle arada **25 puan** var. LoRA'nın kapatması gereken mesafe bu.

### Stile göre

| stil | doğru | oran |
|---|---|---|
| açık | 10/12 | %83 |
| dolaylı | 9/13 | %69 |
| günlük dil | 3/5 | %60 |

Beklenen yönde: ifade ne kadar dolaylı/serbestse doğruluk o kadar düşüyor.

### Araca göre — asıl bulgu

| araç | doğru |
|---|---|
| `gecelik_ozet_sorgula` | 3/3 |
| `genel_stok_durumu_sorgula` | 2/2 |
| `kritik_stok_sorgula` | 4/5 |
| **`olu_stok_sorgula`** | **1/5** |
| `onay_kuyrugu_sorgula` | 4/5 |
| `siparis_onerisi_sorgula` | 4/5 |
| `tedarikci_performansi_sorgula` | 4/5 |

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

### B3.5'te bakılacak

1. Genel doğruluk %70'ten ne kadar yükseldi?
2. **`olu_stok_sorgula` 1/5'ten kurtuldu mu?** Eğitimin işe yarayıp
   yaramadığının en keskin göstergesi bu.
3. Günlük dil (%60) ile açık dil (%83) arasındaki fark kapandı mı?

## B3.5 · LoRA sonrası ölçüm

⬜ Henüz ölçülmedi. Aynı 30 soruluk set yeniden koşturulup B2.3 ile
karşılaştırılacak. Ayrıca token/sn, ilk token gecikmesi, tepe RAM.
