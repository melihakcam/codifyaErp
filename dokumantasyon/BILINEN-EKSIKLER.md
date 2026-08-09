# Bilinen Eksikler

> Bu dosya, **bilerek** ertelenmiş işleri tutar. Her madde ne olduğunu, neyi
> engellediğini ve ne zaman çözülmesi gerektiğini söyler. Amaç, bir eksiğin
> "unutulmuş" ile "ertelenmiş" arasındaki farkı kaybetmemesi.
>
> Son güncelleme: 2026-08-09 · Faz 6 · Finans tamam

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

## 2. 🔴 Kimlik doğrulama yok — üretimi engelliyor

Hiçbir uç kimlik doğrulaması istemiyor (bkz. `ERP-ENTEGRASYON.md` §2).
Servis dış ağa **asla** açılmamalı; yalnızca ERP ile aynı iç ağda,
firewall arkasında çalıştırılmalı.

**Ne zaman çözülecek:** ilk gerçek kurulumdan önce. Faz 6'yı engellemiyor.

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

## 5. 🟢 `stok.tedarikci_degisim` hiç üretilmiyor

Kural motoru bu karar tipini hiç çıkarmıyor; golden set'te de örneği yok.
Politika tablosunda ve `KararTipi`'nde tanımlı ama ölü.

**Ne zaman:** ya kural yazılmalı ya da tip kaldırılmalı. Acil değil.

---

## 6. 🟢 `onay_kuyrugu_sorgula` golden set'te ince

4 örnek — tek hata %25 oynatıyor. Ölçümün çözünürlüğünü düşürüyor ama
yanlış sonuç üretmiyor.

**Ne zaman:** bir sonraki veri üretim turunda hedefli paraphrase ile.

---

## 7. 🟢 `yoldaki_stok` CSV adaptöründe 0 varsayılıyor

Çoğu ERP bunu ayrı tutmuyor. Sıfır varsaymak güvenli taraf (fazladan
sipariş önerir, tersi stok tükenmesine yol açardı). Müşteride alan varsa
`app/adapters/csv_erp.py::envanter_tablosu` genişletilmeli.
