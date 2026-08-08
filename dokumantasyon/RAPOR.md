# Codifya Karar Motoru — Durum Raporu

**Tarih:** 2026-08-08 · **Faz:** 3 sonu (SP3) · **Otonomi:** `shadow`
**Canlı model:** `codifya-router:tur3` (Qwen2.5-1.5B-Instruct + LoRA)

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
| gerekçede uydurma sayı | **0** | **0,00** | ✅ sert kapı |
| gecelik tarama süresi | < 600 sn | **180 sn** | ✅ sert kapı |
| tepe RAM | < 4 GB | **421 MB** | ✅ sert kapı |
| Türkçe akıcılık (LLM-jüri) | > 4,0 | **4,8/5** | ✅ gösterge |
| router: araç+parametre tam eşleşme | > %95 | **%70** | ❌ sert kapı |

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
