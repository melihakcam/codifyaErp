# Kurulum

> Sıfırdan bir müşteriye kurmak için gereken her şey. Sırayla.

## 1. Gereken

| | |
|---|---|
| Docker + Docker Compose | tek gereksinim |
| RAM | en az 4 GB (LLM CPU'da çalışıyor) |
| Disk | ~5 GB (imaj + model + veri) |

⚠️ GPU **gerekmiyor**. Model 1,5B ve CPU'da koşuyor.

## 2. Ayarları hazırla

```bash
cp .env.ornek .env
```

`.env` içinde en az şunu doldur:

```
API_ANAHTARLARI=uzun-bir-anahtar:erp:sistem
```

⚠️ **Anahtarın içinde `:` olmamalı** — ayraç olduğu için anahtar sessizce
kırpılır. Üretimde 16 karakterden kısaysa servis açılmaz (bilinçli).

Anahtar üretmek için:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32).replace(':',''))"
```

## 3. İşletme profilini seç

Müşterinin işine göre `profiller/` altından birini seç ya da yeni yaz:

| profil | kime |
|---|---|
| `varsayilan.json` | emin değilsen |
| `nalbur.json` | küçük ölçek, yavaş dönen stok |
| `toptanci.json` | yüksek ciro, hızlı dönen stok, ciddi batak riski |

`.env` içinde:

```
ISLETME_PROFILI_YOLU=profiller/nalbur.json
```

⚠️ Profil **iş** parametrelerini taşır (ölü stok eşiği, finansman oranı,
personel maliyeti). `.env` ise **kurulum** parametrelerini. Ayrım bilinçli:
profili iş sahibi, `.env`'i sistem yöneticisi değiştirir.

## 4. Ayağa kaldır

```bash
docker compose up -d
```

## 5. Modeli yükle

```bash
docker compose exec ollama ollama pull qwen2.5:1.5b-instruct
```

Eğitilmiş model (`codifya-router:tur6`) kullanılacaksa GGUF dosyasını
konteynere kopyalayıp `ollama create` çalıştır. Model yoksa sistem
**çökmez** — kural motoru kararı verir, gerekçe şablona düşer.

## 6. Doğrula

```bash
curl http://localhost:8000/health
```

Beklenen:

```json
{"durum":"ayakta","ortam":"uretim","otonomi_seviyesi":"shadow",
 "kimlik_dogrulama":"acik"}
```

⚠️ `kimlik_dogrulama` **acik** yazmalı. `kapali` yazıyorsa anahtar
tanımlanmamış demektir ve servis korumasız çalışıyordur.

Onay ekranı: `http://localhost:8000/onay` — anahtarı bir kez girersin,
12 saat çerezde durur.

## 7. ERP'yi bağla

Üç CSV: `urunler.csv`, `hareketler.csv`, `siparisler.csv`.
Beklenen kolonlar ve kabul edilen alternatif adlar:
`dokumantasyon/ERP-ENTEGRASYON.md`.

⚠️ Geriye dönük test koşulacaksa `hareketler.csv`'de **`hareket_tipi`
kolonu zorunlu** — geçmiş stok bugünkü bakiyeden geriye yürünerek
kuruluyor, giriş hareketleri olmadan bu hesap yapılamaz.

---

## Otonomi kademeleri

Sistem `shadow` ile başlar ve **öyle kalmalıdır**:

| kademe | ne yapar |
|---|---|
| `shadow` | karar verir, kaydeder, **hiçbir şey uygulamaz** |
| `advisory` | öneri gösterir, uygulamayı insan yapar |
| `threshold` | eşik altını kendi uygular |
| `off` | kill switch |

⚠️ **Gerçek veride ölçülmüş doğruluk raporu olmadan `threshold`'a
ASLA geçilmez.** Bu teknik değil süreç kararıdır.

## Bilinen sınırlar

| | |
|---|---|
| Tek worker | hız sınırı sayacı bellekte; çok worker'da sınır çarpılır |
| SQLite | tek makine. Postgres'e geçiş `DATABASE_URL` değişikliği |
| Ollama portu kapalı | kimlik doğrulaması yok, dışarı açılmamalı |
| Yedekleme yok | `codifya-veri` volume'ü dışarıdan yedeklenmeli |

Tam liste: `dokumantasyon/BILINEN-EKSIKLER.md`.
