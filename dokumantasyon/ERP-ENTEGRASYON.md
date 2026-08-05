# ERP Entegrasyon Sözleşmesi

> Faz 4.6. ERP stack'i (hangi ERP, hangi dil) henüz seçilmedi — bu doküman
> stack'ten bağımsız, **sözleşme** düzeyinde yazıldı. Gerçek entegrasyon
> başladığında burası güncellenir, mimari değişmez.

## 1. Temel kural

Karar Motoru **bağımsız bir REST servisidir**, ERP'nin içine gömülmez.
ERP hangi stack'te olursa olsun (.NET, Java, PHP, Python — fark etmez)
HTTP üzerinden konuşur. Bkz. `dokumantasyon/YOL-HARITASI.md` — "Servis"
kararı ve gerekçesi.

```
ERP  ──REST/JSON──▶  Karar Motoru (bu repo, FastAPI)
 ▲                          │
 │                          ▼
 └──────── (senkron/asenkron) sonuç
```

Karar Motoru ERP'nin veritabanına **doğrudan erişmez**. ERP verisi bu
sisteme ya (a) API çağrısıyla anlık gönderilir ya da (b) düzenli bir
aktarımla (CSV/DB replikasyonu) `simulator`/veri katmanına beslenir —
bu doküman (a)'yı, yani API sözleşmesini tanımlar.

## 2. Kimlik doğrulama — ⚠️ henüz yok

Şu an **hiçbir uç kimlik doğrulaması istemiyor**. Bu bilinçli bir eksiklik
değil, henüz sırası gelmemiş bir iş — geliştirme/demo aşamasında gürültü
yaratmasın diye ertelendi.

**Üretime geçmeden önce zorunlu:** ERP'den gelen her isteğin bir servis
hesabı/API anahtarıyla doğrulanması. Öneri: `Authorization: Bearer <token>`
+ FastAPI `Depends` ile merkezi bir doğrulama katmanı (`app/core/auth.py`,
henüz yazılmadı). Bu olmadan servis dış ağa **asla** açılmamalı — yalnızca
ERP ile aynı iç ağda, güvenlik grubu/firewall arkasında çalıştırılmalı.

## 3. Uçlar ve kim çağırır

| Uç | Yön | Kim çağırır | Ne zaman |
|---|---|---|---|
| `POST /v1/decisions/stock/reorder-review` | ERP → Karar Motoru | ERP (ya da gecelik iş) | Bir SKU için karar istendiğinde |
| `GET /v1/approvals` | ERP → Karar Motoru | ERP'nin onay ekranı / bu reponun kendi HTMX ekranı | Bekleyen kararları listelemek için |
| `POST /v1/approvals/{karar_id}` | ERP → Karar Motoru | İnsan onay/red/düzelt dediğinde | — |
| `POST /v1/feedback` | ERP → Karar Motoru | Karardan bağımsız, sonradan gelen yorum | — |
| `GET /v1/insights` | ERP → Karar Motoru | Gecelik özet ekranı | Sabah taraması |
| `POST /v1/ask` | ERP → Karar Motoru | Doğal dil arayüzü (varsa) | — |

**Karar Motoru hiçbir zaman ERP'yi çağırmaz** (webhook yok, push yok).
ERP her zaman istemci, Karar Motoru her zaman sunucu. Bu, ERP tarafında
gelen bağlantı kabul etme/firewall açma gereğini ortadan kaldırır.

## 4. Senkron mu asenkron mu

`POST /v1/decisions/stock/reorder-review` **senkron** — karar
milisaniyelerde döner (mimarinin ikinci kuralı, bkz. `YOL-HARITASI.md`).
`gerekce=true` istenirse yanıt gerekçe metnini bekler, bu **saniyeler**
sürebilir (LLM üretimi + guard). ERP bu iki modu ayrı ele almalı:

- Kararı hemen ekrana basacaksa: `gerekce=false` (varsayılan), gerekçeyi
  arka planda ayrıca çekmesi gerekirse `GET /v1/approvals` üzerinden
  (kuyruğa girdiyse) alsın.
- Kararı zaten kuyruklu bir işte üretiyorsa: `gerekce=true` sorun değil.

**Gecelik toplu tarama** (`app/jobs/nightly.py`) ERP tarafından
tetiklenmez — bağımsız bir cron/scheduled task olarak bu repoda çalışır,
sonuçlarını DB'ye yazar. ERP yalnızca `GET /v1/insights` ve
`GET /v1/approvals` ile sonucu **okur**.

## 5. Veri sözleşmesi

Tüm gövdeler `app/contracts.py`'deki Pydantic modelleriyle birebir
eşleşir — o dosya **donmuş sözleşmedir**, değişikliği tek taraflı
yapılmaz (bkz. `YOL-HARITASI.md`, Rol dağılımı bölümü). ERP tarafı JSON
şemasını `GET /openapi.json`'dan (Swagger/OpenAPI 3.1) otomatik üretebilir
— bu doküman elle senkron tutulmaz, o dosya tektir.

Önemli tipler:

- `KararSonucu` — bir karar isteğinin tam cevabı (`aday` + `politika` +
  opsiyonel `gerekce`).
- `DecisionCandidate.aksiyon` — **`dict[str, Any]`**, karar tipine göre
  şekli değişir (`stok.siparis` → `siparis_miktari`/`tedarikci_id`,
  `stok.tasfiye` → farklı alanlar). ERP tarafı `tip` alanına göre dallanmalı.
- Para birimi her yerde **TL**, ondalık ayırıcı JSON'da nokta (`.`) —
  Türkçe biçim (`1.200,50`) yalnızca `Gerekce.metin` içindeki **görüntülenen
  metinde** kullanılır, sayısal alanlarda asla.

## 6. Hata sözleşmesi

| Kod | Anlamı | ERP ne yapmalı |
|---|---|---|
| 200 | Başarılı | — |
| 404 | Kimlik yok (`karar_id` vb.) | Kullanıcıya "kayıt bulunamadı" göster, tekrar deneme |
| 409 | Karar zaten sonuçlandırılmış | Kullanıcıya güncel durumu göster, `POST /v1/feedback` ile yorum eklenebilir |
| 422 | İstek gövdesi geçersiz / (`/v1/ask`'ta) model soruyu anlayamadı | Kullanıcıya "anlaşılamadı" göster, **tahmin etme** |
| 503 | Karar motoru kapalı (`AUTONOMY_LEVEL=off`) ya da (`/v1/ask`'ta) LLM'e ulaşılamıyor | Geçici; kısa aralıkla yeniden dene |
| 500 | Beklenmeyen sunucu hatası | Loglanmalı, kullanıcıya "geçici sorun" — **asla sayı/karar retry ile tekrar üretilmemeli**, `karar_id` sabit kalmalı |

`POST /v1/decisions/...` yolunda **LLM'e bağlı hiçbir hata 500/503 olarak
dışarı sızmaz** — `gerekce_uret()` çökerse şablon metne düşer (bkz. Faz 4.1
doğrulaması, `tests/test_api_smoke.py::test_llm_erisilemezken_karar_endpointi_500_vermez`).
Yani ERP tarafı bu uç için LLM kesintisine karşı **ek bir yeniden deneme
mantığı yazmak zorunda değil** — servis zaten kendi içinde bunu hallediyor.

## 7. Otonomi seviyesi ve ERP'nin rolü

`AUTONOMY_LEVEL` (`shadow` | `advisory` | `threshold` | `off`) Karar
Motoru'nun **kendi** yapılandırmasıdır, ERP'den kontrol edilmez.
`KararSonucu.politika.uygulandi` alanı ERP'ye "bu kararı sen de gerçekten
uygulamalı mısın" sorusunun cevabıdır:

- `uygulandi=false` → ERP kararı **yalnızca gösterir/kaydeder**, stok
  hareketi/sipariş oluşturmaz.
- `uygulandi=true` (yalnızca `threshold` modda, eşik üstü kararlarda) →
  ERP kararı gerçek bir işleme (PO oluşturma vb.) çevirebilir.

`threshold` moduna geçiş **yalnızca insan kararıyla** olur — bkz.
`YOL-HARITASI.md` "Otonomi kademeleri" ve `KISI-B-GOREV.md` Faz 5 uyarısı:
*"shadow modda ölçülmüş doğruluk raporu olmadan threshold'a asla geçilmez."*
ERP tarafı bu geçişi API üzerinden **tetikleyemez** — bilinçli olarak
böyle bırakıldı, yanlışlıkla otonomi seviyesi değiştirilemesin diye.

## 8. Sürümleme

Tüm uçlar `/v1/` altında. Sözleşmede geriye dönük uyumsuz bir değişiklik
gerekirse `/v2/` açılır, `/v1/` bir geçiş süresi boyunca yaşamaya devam
eder. Şu an tek tüketici bu repo içindeki testler/demo olduğu için henüz
`/v2/` gerekmedi.
