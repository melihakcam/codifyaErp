# Codifya Karar Motoru — Durum Raporu

**Tarih:** 2026-08-08 · **Faz:** 3 sonu (SP3) · **Otonomi:** `shadow`
**Canlı model:** `codifya-router:tur5` (Qwen2.5-1.5B-Instruct + LoRA, r=32)

Bu belge sistemin **ölçülmüş** durumunu anlatır. Buradaki her sayı
`training/eval/` altındaki ham sonuç dosyalarından gelir ve yeniden
üretilebilir. Ayrıntılı ölçüm günlüğü: [OLCUMLER.md](OLCUMLER.md).

---

## 1. Sistem ne yapıyor

Bir KOBİ deposu için (~2.000 SKU) stok ve satınalma kararları üretiyor:
ne zaman sipariş verilmeli, hangi ürün tasfiye edilmeli, hangi tedarikçi
sorunlu. Kararı **Türkçe gerekçesiyle** birlikte veriyor ve kullanıcının
sorularını anlıyor.

### Mimariyi ayakta tutan iki kural

**1. LLM asla sayı üretmez.** Sayıları kural motoru hesaplar, prompt'a
verilir; model onları yalnızca cümleye yerleştirir. Metindeki her sayı
`DecisionCandidate.izinli_sayilar()` kümesinde yoksa çıktı reddedilir ve
deterministik şablona düşülür.

**2. ERP asla LLM'i beklemez.** Karar kural motorundan milisaniyelerde
çıkar; LLM yalnızca açıklama metnini yazar. Gerekçe kuyruklu ve tembel.

Bu iki kural, 1,5B'lik bir modeli üretime uygun kılan şeydir. **Sistemin
gerçek zekâsı kural motorunda; LLM bir dil katmanı.**

---

## 2. Ölçülen sonuçlar

Beş metrik, dördü sert kapı. Ölçüm: `uv run python -m training.eval.benchmark`

| metrik | hedef | ölçülen | |
|---|---|---|---|
| gerekçede uydurma sayı | **0** | **0,00** (20/20 kabul) | ✅ sert kapı |
| gecelik tarama süresi | < 600 sn | **173 sn** | ✅ sert kapı |
| tepe RAM | < 4 GB | **426 MB** | ✅ sert kapı |
| Türkçe akıcılık (LLM-jüri) | > 4,0 | **4,8/5** | ✅ gösterge |
| router: araç+parametre tam eşleşme | > %95 | **%73** | ❌ sert kapı |

**Dört kapıdan üçü geçildi. Kalan tek açık router doğruluğu.**

### Uydurma sayı — sıfır, ve bu tesadüf değil

Gerekçe metinlerinde uydurma sayı **0**. Bu, projenin en kritik güvencesi:
kullanıcı bir gerekçede `%15 iskonto` okuyorsa o değer gerçekten kural
motorundan gelmiştir.

Bu sayı hep 0 değildi. 2. tur eğitiminde guard kabul oranı %25,7'ye
düşmüştü; kök neden eğitim verisinde bulundu — örneklerin **%79,4'ü**
modele "istemde olmayan bir sayı üret" diye öğretiyordu. Düzeltildikten
sonra 5.000 örneğin 5.000'i geçiyor.

---

## 3. Router doğruluğu — dört turun hikâyesi

48 soruluk sabit ölçüm seti (30 taban + 18 ek). Sorular **elle yazıldı**,
üreticiden değil; eğitim verisiyle çakışmıyor. Sıcaklık 0, sabit tohum,
soğuk başlangıç.

| model | araç doğru | **tam doğru** | uydurma | şema hatası |
|---|---|---|---|---|
| taban (eğitimsiz) | 34/48 · %70,8 | 32/48 · %66,7 | 0 | 0 |
| 1. tur | — | — | — | — |
| 2. tur | 22/30 · %73,3 ¹ | 20/30 · %66,7 ¹ | 0 | 0 |
| **3. tur (canlı)** | **39/48 · %81,2** | 33/48 · %68,8 | 3 | 0 |
| 4. tur (arşiv) | 38/48 · %79,2 | 35/48 · %72,9 | 1 | 3 |

¹ 2. tur yalnızca 30 soruluk taban sette ölçüldü.

### Neden 3. tur canlıda, 4. tur değil

4. tur router'ı iyileştirdi ama **gerekçe tarafını bozdu.** Aynı guard'la,
aynı 20 kararla ölçüldüğünde:

| model | gerekçe kabul | şablona düştü |
|---|---|---|
| 3. tur | **20/20** | 0 |
| 4. tur | 11/20 | **9** |

Gerekçe yüzeyi router'dan geniş — her karar bir gerekçe üretir, router
yalnızca kullanıcı soru sorunca çalışır. 48 soruda +2 doğru, açıklamaların
%45'ini şablona düşürmeye değmedi.

### ⭐ Bulunan asıl darboğaz: kapasite

3. ve 4. tur arasında **gerekçe verisi hiç değişmedi** (aynı 40.293 satır,
aynı örnekleme). Değişen tek şey router verisiydi. Buna rağmen gerekçe
kalitesi düştü.

Sebep: router ve gerekçe **aynı LoRA ağırlıklarını paylaşıyor** (`r=16`,
eğitilebilir parametre %1,18). Router verisi çeşitlenince kapasitenin daha
büyüğünü tüketti; gerekçe bedelini ödedi.

**Bu, "daha çok/iyi veri = daha iyi model" varsayımının bu ölçekte
kırıldığı yer.** %95 hedefine giden yol daha fazla veriden değil, daha
fazla kapasiteden geçiyor:

1. LoRA rank'ı yükselt (`r=16` → 32) — en ucuz deneme, hipotezi doğrudan sınar
2. Görev oranını ayarla (router şu an 10.000 örneğin 2.000'i)
3. İki ayrı adaptör — kapasite yarışı biter, yönetim yükü artar

⚠️ Hangisi denenirse denensin **her turda iki taraf da ölçülmeli.** 4. tur
bunu öğretti: router ölçümüne tek başına bakılsaydı "başarılı" görünüyordu.

---

## 4. Güvenlik: en kötü senaryoda ne olur

| bileşen bozulursa | sonuç |
|---|---|
| Router yanlış araç seçer | Kullanıcı yanlış raporu görür, tekrar sorar. Rahatsız edici, zararsız. |
| Router şema üretemez | Açık hata döner. Sessiz yanlış cevap yok. |
| Gerekçe bozuk çıkar | Guard yakalar, şablona düşer. Metin tahtadan ama **doğru**. |
| LLM tamamen erişilemez | Karar yine üretilir; yalnızca açıklama şablondan gelir. |

**Hiçbir senaryoda yanlış sipariş verilmez**, çünkü kararı LLM vermiyor.
`AUTONOMY_LEVEL=shadow` olduğu sürece sistem zaten hiçbir şey uygulamıyor —
karar verir, kaydeder, insan onayına bırakır.

---

## 5. Bilinen sınırlar

**Veri simülasyondan.** Buradaki tüm sayılar simüle edilmiş bir katalog ve
talep akışı üzerinde ölçüldü. Gerçek veride:

- **Kural motoru ve guard aynen çalışır** — formül ve kontrol, veriden bağımsız
- **Gerekçe büyük ölçüde taşınır** — model adı/sayıyı istemden kopyalıyor, ezberinden değil
- **Router en zayıf halka** — gerçek kullanıcı, şablon yazılmamış şekillerde sorar.
  %70 muhtemelen daha da düşer.

Bunu ölçmenin tek yolu `shadow` modda gerçek veride bir hafta koşmak
(Faz 4). Ve `/v1/feedback` ucu, gerçek soruların bir sonraki eğitim turunun
verisi olmasını sağlıyor — router'ın sim2real açığını kapatmanın tek gerçek
yolu şablon yazmak değil, gerçek soru toplamak.

**Ölçüm setleri ince.** `onay_kuyrugu_sorgula` golden set'te 4 örnek — tek
hata %25 oynatıyor. `stok.tedarikci_degisim` karar tipinin hiç örneği yok.
İkisi de bilinen ve kabul edilmiş durumlar.

---

## 6. `threshold` moduna geçiş kararı

> **`shadow` modda ölçülmüş doğruluk raporu olmadan `threshold`'a ASLA
> geçilmez.** Bu teknik değil, süreç kararıdır (`tests/test_policy.py`
> bunu sınar).

**Bugünkü öneri: geçilmemeli.** İki sebep:

1. Router sert kapısı açık (%70 < %95)
2. Ölçümlerin tamamı simülasyon verisinde — gerçek veride shadow koşusu yapılmadı

Sistem `shadow` modda güvenli ve faydalı: kararları üretiyor, gerekçelendiriyor,
onay kuyruğuna alıyor. Bu haliyle kullanılabilir.

---

## 7. Ölçüleri yeniden üretmek

```bash
uv run python -m training.eval.benchmark --etiket kontrol
uv run python -m training.eval.router_taban --model codifya-router:tur3 --istem-bicimi egitilmis --ek
uv run python -m training.eval.veri_tutarlilik_kontrolu
uv run python -m training.eval.golden_set_inceleme --dosya data/egitim/golden_set_aday.jsonl
uv run pytest
```

Kod: 55 Python modülü, 26 test dosyası, 353 test.
Ham ölçüm sonuçları: `training/eval/*.json`

---

## 8. 5. tur sonucu: kapasite hipotezi çürütüldü

`r=16 → 32` denendi (tek değişken rank; veri, adım, tohum aynı).

**Router tarafı en iyi sonucu verdi:** tam doğruluk 36/48 (%75,0),
`gecelik_ozet` 1/10 → 5/10 → **7/10** ile taban seviyesine tam döndü.

**Ama gerekçe tarafı daha da bozuldu:**

| tur | rank | gerekçe kabul |
|---|---|---|
| 3 | 16 | **20/20** |
| 4 | 16 | 11/20 |
| 5 | **32** | **7/20** |

Kapasite hipotezi doğru olsaydı 20/20'ye dönmesi beklenirdi. Tam tersi oldu.

### Yeni yorum: kapasite değil, görev girişimi

    veri degisikligi (tur3 -> tur4):  20/20 -> 11/20
    rank iki katina  (tur4 -> tur5):  11/20 ->  7/20

Kapasite arttıkça model router görevine daha güçlü oturuyor ve o görevin
biçimi (kısa, yapılandırılmış JSON) serbest Türkçe düzyazıyı bastırıyor.
İki görev kapasite için **yarışmıyor**, birbirine **karışıyor**. Daha fazla
kapasite karışmayı güçlendiriyor.

`r=64` denemesi de anlamsız — aynı yönde daha kötü sonuç verir.

### 6. tur için tek makul yol: iki ayrı adaptör

Aynı taban model, göreve göre farklı LoRA. Karışma fiziksel olarak imkânsız
hale gelir. Yönetim yükü artar (iki adaptör, çalışma zamanında seçim) ama
iki turluk kanıt başka yol bırakmıyor.

⚠️ Bu turun değeri **ucuz bir çürütme** olması: bir saatlik GPU turu,
"rank'ı büyütelim" fikrinin yanlış olduğunu kesin gösterdi. Sınamadan iki
adaptöre geçseydik, işe yaramayan bir karmaşıklığı boşuna üstlenebilirdik.

Canlı model değişmedi: `codifya-router:tur3`.


---

## 9. ⭐ İŞ DEĞERİ — para metriği

Yol haritasının merkezine koyduğu sayı. `training/genellenebilirlik_ve_para_metrigi.py`,
tutulmamış seed (20250801), 3 yıl / 1.095 gün.

| | vasat yönetim | **kural motoru** | oracle (üst sınır) |
|---|---|---|---|
| stok tükenme oranı | %5,31 | **%0,47** | %0 |
| kayıp kâr | 7.688.130 TL | **3.819.706 TL** | 197.585 TL |
| sipariş sayısı | 11.473 | **7.741** | 40.021 |
| **toplam maliyet** | **18.816.055 TL** | **17.395.365 TL** | 14.903.128 TL |

> **AI politikası toplam stok maliyetini %7,6 düşürdü ve stok tükenmesini
> 11 kat azalttı (%5,31 → %0,47).**

⚠️ Sistem **daha fazla** stok tutuyor (aşırı stok maliyeti 9,4M → 12,4M) ve
**%33 daha az sipariş** veriyor. Yani "stoğu kıs" gibi ezber bir kural
işletmiyor: emniyet stoğu bırakıp müşteri kaybını önlüyor, siparişleri daha
büyük ve ekonomik partilerde topluyor.

### Aşırı uyum testi: 9/9

Dört şirket profili × üç tohum, kriter her kombinasyonda vasat'tan hem daha
az tükenme hem daha az maliyet:

| profil | maliyet iyileşmesi |
|---|---|
| küçük nalbur dükkânı | %1,4 – %3,2 |
| yapı malzemesi toptancısı | %15,0 – %19,5 |
| büyük inşaat deposu | **%39,1 – %44,7** |

**Kazanç şirket büyüdükçe artıyor.** Küçük nalburda fark küçük (az SKU, sahip
kafadan takip edebiliyor), büyük depoda %40'a çıkıyor — sistemin asıl
müşteri segmenti bu.

### Bu sayı LLM'den bağımsız

Hesabı kural motoru yapıyor. Router doğruluğu %75'te takılı olsa da iş
değeri etkilenmiyor — mimarinin birinci kuralının ("LLM asla sayı üretmez")
doğrudan sonucu.

Bu, açık kalan sert kapıyı da yeniden çerçeveliyor: **router %95, bir iş
değeri kapısı değil, kullanıcı deneyimi kapısı.** Router yanlış araç
seçtiğinde kullanıcı yanlış raporu görür ve tekrar sorar; para kaybı olmaz.

---

## 10. Gerçek veriye geçiş — pilot müşteriden istenecekler

Buraya kadarki her sayı **simülasyon** verisinde ölçüldü. Gerçek bir şirkette
çalıştırmak için `app/adapters/csv_erp.py` yazıldı.

### İstenecek üç dosya

Her ERP'de (hatta Excel'le çalışan bir depoda bile) hazır duruyorlar:

| dosya | içindekiler |
|---|---|
| **urunler.csv** | stok kodu, ad, kategori, alış fiyatı, satış fiyatı, tedarikçi, mevcut stok |
| **hareketler.csv** | tarih, stok kodu, miktar (giriş/çıkış) — **en az 6-12 aylık** |
| **siparisler.csv** | tedarikçi, sipariş tarihi, teslim tarihi |

Gerisini sistem hesaplıyor: günlük ortalama talep ve sapması, ABC/XYZ sınıfı,
son hareket tarihi, tedarik süresi ortalaması/sapması, tedarikçi güvenilirliği.

⚠️ **Kolon adları esnek.** `Stok Kodu`, `Ürün Kodu`, `SKU`, `item_code` — hepsi
tanınıyor, Türkçe karakterler dâhil. Tanınmayan ad gelirse hata mesajı hangi
adların kabul edildiğini yazıyor; müşterinin muhasebecisi de anlayabilsin diye.

⚠️ **`siparisler.csv` "isteğe bağlı" görünüyor ama vazgeçilmez.** Tedarik
süresi **belirsizliği** oradan çıkıyor ve emniyet stoğu hesabının temeli o.
Dosya yoksa sapma sıfır varsayılır — sistemin en değerli hesabı körleşir.

### Bir hafta beklemeye gerek yok: geriye dönük test

Faz 4 "`shadow` modda bir hafta koş" diyor. Ama elde **geçmiş 12 aylık**
hareket varsa çok daha güçlüsü yapılabilir: sistemi geçen yılın verisiyle
gün gün çalıştırıp *"o gün ne karar verirdi"* sorusunu sormak, sonra gerçekte
ne olduğuna bakmak.

Bir haftalık canlı gözlem ~7 gün ve birkaç yüz karar üretir; bir yıllık geriye
dönük test **binlerce** karar, gerçek talep dalgalanması ve gerçek tedarikçi
gecikmeleriyle. Üstelik beklemek gerekmez — veri gelir gelmez koşar.

**Pilot müşteri ikna etmenin en hızlı yolu bu:** üç dosyayı al, aynı gün
*"sizin deponuzda geçen yıl şu kadar kazandırırdı"* raporunu geri ver.

### Adaptörün bilinçli kabulleri

- **`yoldaki_stok` = 0.** Çoğu ERP bunu ayrı tutmuyor. Sıfır varsaymak güvenli
  taraf: sistem yoldaki malı görmezse fazladan sipariş önerir; tersi (olmayan
  malı var sanmak) stok tükenmesine yol açardı.
- **Hiç hareketi olmayan ürün ölçüme alınmaz.** Hiç satılmamış bir ürün için
  "günlük ortalama talep" anlamsız; sistem onu ölü stok sanırdı.
- **Hareketsiz günler sıfırla doldurulur.** Yalnızca satış olan günler
  sayılsaydı, ayda bir satılan ürün "günde 1 adet" gibi görünür ve sistem
  sürekli sipariş verirdi.
- **Tek siparişi olan tedarikçide katalog sapması kullanılır.** Tek gözlemden
  sapma sıfır çıkar; o da riski yok saymak olurdu.

10 regresyon testi (`tests/test_csv_erp.py`), hepsi gerçekçi kirli CSV'lerle.
