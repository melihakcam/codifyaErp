# Faz 13 — "Tam plan": alanı bilmeyen tek komut

> Onaylandı 2026-08-12. **Durum: planlandı, kod yazılmadı.**
>
> Eski planın devamı, yerine geçmiyor. Motor ve sözleşmeler
> [FAZ-11-GENEL-PLANLAMA.md](FAZ-11-GENEL-PLANLAMA.md)'de kuruldu; burada
> üzerine **üç şey** ekleniyor. Adım listeleri:
> [KISI-A-GOREV.md](KISI-A-GOREV.md) · [KISI-B-GOREV.md](KISI-B-GOREV.md)

---

## Amaç — ve neyin amaç OLMADIĞI

> "Bizim yaptığımız şey genel anlamda karar mekanizması — kişinin ve şirketin
> işini kolaylaştırmak."
> — Melih, 2026-08-12

**Teslim edilen şey bu fazda bir alan değil, bir mekanizmadır.** Nakliye,
yapı malzemesi, taş yünü — hepsi **örnek**. Örnekler sınav malzemesidir;
ürünün kendisi değildir.

Melih'in tarif ettiği davranış:

> "Üretim planlama yapsın, önceki detaylara bakarak geleceğe göre yanıt versin."

> "Mesela nakliyat — tüm genel planı çıkarabilsin. Şu tır şuraya giderse daha
> iyi olur, bunun kapasitesi farklı buraya gidebilsin diye."

> "Şu an A ürünü için yapıyoruz; öyle iyi hazırlayalım ki B ürünü satan
> şirkete bu sistemi sattığımızda kolay hazırlayabilelim."

**Kavram: düğme değil, tek komut.** Alanı söylersin, o alanın **tamamının**
planı çıkar — parça parça değil.

⚠️ Bu istek **üç kez** yanlış anlaşıldı ve üçünde de aynı hatayla: istek her
seferinde *bir alanın* (önce üretimin, sonra nakliyenin) parçası gibi
kurgulandı. Hatanın kalıbı şu: örnek olarak verilen alan, işin konusu sanıldı.

**Bu fazın kabul ölçütü tek cümleyle:** alan adını hiç bilmeyen bir komut, iki
farklı alanda çalışan bir plan üretiyor — ve üçüncü alan **tek JSON** ile
ekleniyor. Alanların hangileri olduğu önemsizdir.

---

## Dört karar (soruldu, cevaplandı 2026-08-12)

| Soru | Karar | Bunun anlamı |
|------|-------|--------------|
| Nakliye ile üretimin ilişkisi? | **Tek şirket, iki bölüm** | Bir alanın çıktısı başka bir alanın girdisi olabilmeli. Genel yetenek olan bu; üretim→nakliye yalnızca ilk örneği. |
| "Şu tır şuraya" ne demek? | **Kapasite + uygunluk ataması** | Hangi iş hangi kaynağa, hangi gün — sebebi kaynağın kapasitesi, işin o kaynağa uygunluğu, aciliyet. **Coğrafya yok.** Tır bir örnek; "kaynak" genel adı. |
| Hangi şirket / ürün? | **Mevcut `kobi_yapi` profili** | ⚠️ **Örnek bağlam, kilit değil.** Geçmişi ve ölçümleri hazır olduğu için seçildi — sıfırdan veri üretilmesin diye. Sistem bu sektöre bağlanmaz. |
| "B ürünü şirketine kolay" nereye kadar? | **Sadece JSON dosyaları** | Yeni müşteri = yeni profil JSON'u + yeni alan tanımı JSON'u. **Kod dağıtımı yok.** Bir dilek değil, §Doğrulama'da kapı. Fazın asıl teslimatı bu. |

---

## Elde hazır olan — yeniden yazılmayacak

Faz 11-12'den kalan, testli ve çalışan parçalar:

| ne | nerede | durum |
|---|---|---|
| genel yerleştirme (kaynak/iş, kapasite, uygunluk, bölünemezlik) | `app/planlama/yerlestirme.py` | ✅ |
| plan ölçütleri ("iyi plan" tanımları) | `app/planlama/olcut.py` | ✅ |
| JSON alan tanımı okuyucu | `app/planlama/tanim.py` | ✅ |
| maliyet + karne + gerekçeli öneri | `app/planlama/maliyet.py`, `karsilastir.py` | ✅ |
| tahmin çekirdeği (Croston/SBA, bantlı) | `app/forecast/` | ✅ girdisi düz geçmiş serisi — **alandan bağımsız** |
| üretim adaptörü + MRP + kapasite | `app/domain/production/` | ✅ |
| araç çalıştırma (LLM'siz, deterministik) | `app/llm/araclar.py` | ✅ |
| işletme profili (müşteriye özel sayılar) | `app/core/isletme_profili.py`, `profiller/*.json` | ✅ |
| nakliye alan tanımı | `ornekler/nakliye.json` | ⚠️ **test verisi** — geçmişi yok |

**Parçalar var. Eksik olan üç şey:**

### 1 · Gerekçe — "neden bu araç"

`PlanSatiri` bugün *kim / nereye / ne zaman* diyor. **Neden** demiyor.
Melih'in "daha iyi olur **diye**" dediği kısım kodda hiç yok. Plan bir tablo;
savunulabilir bir belge değil.

### 2 · İşlerin nereden geldiği — bugün tek yol var

Bugün işler **yalnızca** JSON'a elle yazılarak veriliyor. "Önceki detaylara
bakarak geleceğe göre" çalışması için işlerin geçmişten türeyebilmesi
gerekiyor; bir alanın çıktısının başka bir alanın girdisi olabilmesi de aynı
eksiğin parçası. Üç yol da olacak (`elle` · `tahmin` · `alan:<ad>`) ve hangisi
kullanılacağı **alan tanımında yazılı** olacak, kodda gizli değil.

### 3 · Tek genel giriş

Motor genel, **API yüzeyi değil.** Uçlar hâlâ üretime özel
(`uretim_cizelgesi`, `uretim_plani_karsilastir`). Nakliye motorda koşuyor ama
dışarıdan çağrılamıyor.

---

## Zincir — hedeflenen akış

```
geçmiş (3 yıl)
    │
    ▼
tahmin  ─ app/forecast/ ─ bantlı, alandan bağımsız
    │
    ▼
alan adaptörü ─ tahmin → İş listesi
    │           üretim: emirler · nakliye: sevkiyatlar
    ▼
gerekçeli yerleştirme ─ app/planlama/yerlestirme.py + YENİ gerekçe
    │                   kapasite · uygunluk · bölünemezlik · aciliyet
    ▼
maliyet + karşılaştırma ─ üç plan, farkı parayla
    │
    ▼
PLAN BELGESİ ─ tek çıktı, alanı bilmeyen tek komuttan
```

⚠️ **Bu zincirin hiçbir halkası LLM'e bağlı değil.** Faz 11'in kuralı
sürüyor: sayıyı deterministik kod hesaplar, LLM yalnızca anlatır. Plan belgesi
LLM'siz de üretilebilir olmalı; model yalnızca özet cümlesini yazar.

---

## Adım 0 — ORTAK, yarım gün: sözleşmeyi dondur

Kod yazılmadan önce, tek PR'da, ikisi birlikte. Tek taraflı değişmez.

**İki ekleme, ikisi de geriye uyumlu (varsayılanlı):**

```python
# app/planlama/contracts.py
@dataclass(frozen=True)
class AtamaGerekcesi:
    """Bir işin NEDEN o kaynağa gittiği. Metin değil, VERİ.

    ⚠️ Serbest metin olsaydı test edilemezdi ve LLM'in uydurmasına açık
    olurdu. Alanlar sayı/kimlik; cümleyi bunlardan üreten katman ayrı.
    """
    secilen_kaynak: str
    aday_kaynaklar: tuple[str, ...]       # uygunluk kısıtından geçenler
    elenme_nedenleri: dict[str, str]      # kaynak_id -> neden olmadı
    belirleyici: str                      # "kapasite" | "uygunluk" | "aciliyet" | "tek_aday"

@dataclass(frozen=True)
class PlanSatiri:
    ...                                   # mevcut alanlar aynen
    gerekce: AtamaGerekcesi | None = None # YENİ, varsayılanlı
```

```python
# app/planlama/tanim.py — AlanTanimi JSON şemasına
"isler_kaynagi": "elle" | "tahmin" | "alan:<ad>"
#   elle        -> işler JSON'da yazılı (bugünkü davranış, VARSAYILAN)
#   tahmin      -> geçmişten tahminle üretilecek
#   alan:uretim -> başka bir alanın çıktısı girdi olacak (zincir bağı)
```

⚠️ `extra="forbid"` disiplini sürüyor: `isler_kaynak` yazıp
`isler_kaynagi` demeyi unutan bir tanım **hata vermeli**, sessizce
varsayılana düşmemeli. Faz 9'un dersi.

---

## Sahiplik tablosu — dosya kümeleri kesişmiyor

| | Kişi A — Veri & Alan | Kişi B — Servis & Model |
|---|---|---|
| **Dokunduğu** | `app/planlama/yerlestirme.py`, `app/domain/*/adapter.py` (yeni), `ornekler/*.json`, `profiller/*.json` | `app/planlama/tam_plan.py` (yeni), `app/api/`, `app/llm/araclar.py`, `training/eval/` |
| **Dokunmadığı** | API, router, ölçüm hattı | Yerleştirme algoritması, simülatör, alan adaptörleri |

⚠️ Bu fazda **`simulator/`'a dokunulmuyor.** Yeni veri üretmek genel
mekanizmayı kanıtlamıyor; mevcut üretim geçmişi yeterli.

**Paralelliği mümkün kılan:** Adım 0'da `AtamaGerekcesi` donduktan sonra B,
A'nın gerçek gerekçesini beklemeden `gerekce=None` ile çalışır — plan belgesi
gerekçe yoksa o bölümü atlar, patlamaz. Faz 10-11'de aynı disiplin işe yaradı.

---

## Kişi A — Veri & Alan

> **Not — fazın en pahalı kalemi bilinçli olarak silindi.** Önceki taslakta
> nakliye için 3 yıllık sevkiyat simülatörü yazılması vardı (~1 hafta, Kişi A).
> Silindi, çünkü **mekanizmayı kanıtlamaya gerekmiyor**: "geçmişten tahmin"
> zinciri geçmişi **zaten olan** üretimde kanıtlanır; "alanı bilmeyen komut"
> ise elle yazılı işlerle nakliyede kanıtlanır. İkisi birden kanıtlandığında
> iddia tamamlanır. Bir alanı zenginleştirmek genel mekanizmaya hiçbir şey
> katmıyordu. Bkz. §Kapsam dışı.

### A13.1 · Gerekçeli yerleştirme

`yerlestirme.py` her atama için `AtamaGerekcesi` doldurur. Bilgi zaten
algoritmanın içinden geçiyor — uygunluk süzgeci aday listesini biliyor,
kapasite kontrolü elenme nedenini biliyor. Şu an atılıyor; kaydedilecek.

⚠️ **Determinizm.** Faz 11'de sıralamada rastgele UUID vardı: aynı girdi
farklı plan üretiyordu ve aynı hata kapasite modülünde de bulundu. Gerekçe
eklemek yeni bir sıralama noktası açıyor — `test_ayni_girdi_ayni_plan`
gerekçeleri de karşılaştırmalı, yoksa kayma sessiz kalır.

### A13.2 · Alan adaptörleri — tahmin → `Is` listesi

`app/domain/production/adapter.py` ve `app/domain/logistics/adapter.py`.
İkisi de **aynı imzayı** taşır; alanı bilmeyen katman ikisini ayırt etmez.
Bu fazın genellik iddiasını taşıyan dosyalar bunlar.

`isler_kaynagi` üç değeri de bu adaptörlerden geçer:

| değer | hangi alanda kanıtlanıyor | neden orada |
|---|---|---|
| `tahmin` | **üretim** | 3 yıllık geçmişi var; "önceki detaylara bakarak geleceğe göre" ancak geçmişin olduğu yerde ölçülebilir |
| `elle` | **nakliye** | geçmişi yok, işler JSON'da yazılı — komutun alanı bilmediğini kanıtlayan yer tam burası |
| `alan:<ad>` | üretim → nakliye | bir alanın çıktısı başka alanın girdisi; zincir bağının en küçük kanıtı |

⚠️ `app/forecast/` **yeniden yazılmayacak.** `croston(gecmis, kalem_id,
baslangic, ufuk)` girdisi düz bir liste — zaten genel. Yalnız adlandırması
(`kalem_id`, "talep") stok kokuyor. **Yeniden adlandırma yapılmayacak**
(donmuş sözleşme); adaptör çeviriyi üstlenir.

### A13.3 · Üçüncü alan tanımı — sınavın kendisi

`ornekler/` altına **tek JSON**, kod değişikliği sıfır. Bir demo değil;
§Doğrulama'daki 3. kapının ölçüm aracı ve "yeni müşteriye kolay satılır"
iddiasının tek kanıtı.

⚠️ Alan bilinçli olarak **üretimden ve nakliyeden uzak** seçilir (ör. vardiya
/ personel çizelgesi). Yakın bir alan seçmek kapıyı geçirir ama hiçbir şey
kanıtlamaz — Faz 11'de nakliyenin "üretimden en uzak" olduğu için seçilmesiyle
aynı gerekçe.

---

## Kişi B — Servis & Model

### B13.1 · `app/planlama/tam_plan.py` — alanı bilmeyen tek giriş

```python
def tam_plan(alan: str, olcut: str | None = None, ufuk_gun: int | None = None) -> TamPlan
```

Zinciri baştan sona koşturur. **Alan adını `if`'lemez** — tanımı okur,
adaptörü tanımdan bulur. İçinde `if alan == "uretim"` geçen bir satır bu
fazın iddiasını çürütür.

### B13.2 · Plan belgesi

Tek çıktı, altı bölüm: gelecek tahmini · ne yapılacak · takvim (hangi iş,
hangi kaynakta, hangi gün) · **gerekçeler** · plan seçenekleri ve parayla
öneri · ⚠️ dikkat (kapasite aşımı, geçmişi yetersiz kalemler).

⚠️ **LLM'siz üretilebilir olmalı.** Faz 8'in dersi: tip
`_TIPE_GORE_ALANLAR`'a girmezse model **hiç çağrılmaz** ve metin sessizce
şablona düşer — sonra da kimse fark etmez. Önce test, sonra model.

### B13.3 · `POST /v1/plan/{alan}`

Üretime özel uçların genel karşılığı. Mevcut uçlar **silinmez** — geriye
uyumluluk; ama yeni uca yönlendirdikleri belgelenir.

### B13.4 · Araç olarak ekle

`app/llm/araclar.py`'ye `tam_plan` aracı: *"nakliye planı çıkar"* → çalışan
cevap. Araç sayısı 7 → 8.

### B13.5 · Ölçüm

`router_taban`, **aynı donmuş 30 soruluk set**, `--etiket faz13-tur1`.

⚠️ **Faz 12'nin süreç hatası tekrarlanmayacak:** orada araç eklemekle model
sürümü aynı anda değişti, iyileşme ikisine de bağlanamadı. Bu turda **model
sürümü sabit tutulur.** Değişmesi gerekirse ayrı bir koşu olarak ölçülür.

Beklenti: araç eklemek mevcut %86,7'yi **düşürmemeli**. Yükselmesi bu fazın
hedefi değil.

---

## Doğrulama — dört kapı

**1 · Aynı komut, iki alan.**

```bash
uv run python -c "from app.planlama.tam_plan import tam_plan; tam_plan('uretim'); tam_plan('nakliye')"
```

İkisi de plan üretmeli. Test iki çağrının aynı fonksiyona gittiğini
doğrulamalı — gitmezse "genel" iddiası düşer.

**2 · Üretim davranışı kaymadı.** Mevcut 9 çizelge testi **değiştirilmeden**
geçmeli. Faz 11'de kanıt buydu; aynı kanıt yeniden istenir.

```bash
uv run pytest -v
```

**3 · Yeni müşteri = sıfır kod.** "C ürünü" şirketi tek JSON ile eklenir.

```bash
git diff --stat -- 'app/**/*.py'   # BOŞ olmalı
```

⚠️ Bu kapı bir test tarafından kilitlenir (`test_yeni_alan_kod_gerektirmiyor`),
yoksa zamanla sessizce çürür. "B ürünü şirketine kolay satalım" isteğinin
ölçülebilir hâli tam olarak budur.

**4 · Determinizm.** Aynı girdi → aynı plan **ve aynı gerekçeler**.

---

## Takvim

Günde ~4-6 verimli saat, [YOL-HARITASI.md](YOL-HARITASI.md)'nin varsayımıyla.

| Adım | Kim | Süre |
|------|-----|------|
| Adım 0 · sözleşmeyi dondur | **ORTAK** | ½ gün |
| A13.1 · gerekçeli yerleştirme | A | 1 gün |
| A13.2 · alan adaptörleri (üç `isler_kaynagi` yolu) | A | 1½ gün |
| A13.3 · üçüncü alan JSON'u | A | ½ gün |
| B13.1 · `tam_plan` | B | 1 gün |
| B13.2 · plan belgesi (altı bölüm, LLM'siz test) | B | 1½ gün |
| B13.3 · `/v1/plan/{alan}` | B | ½ gün |
| B13.4 · araç olarak ekle | B | ½ gün |
| B13.5 · ölçüm + yazım | B | ½ gün |
| Entegrasyon (SP · dört kapı birlikte koşulur) | **ORTAK** | ½ gün |

| Senaryo | Kritik yol | Bitiş |
|---|---|---|
| **İki kişi paralel** | Adım 0 + B zinciri (4 gün) + entegrasyon | **~5 iş günü → 19.08.2026** |
| **Tek kişi (bugünkü durum)** | tüm adımlar seri: 3 + 4 + 1 | **~9 iş günü → 25.08.2026** |

⚠️ **Bugün geçerli olan ikinci satır.** Kişi A/B ayrımı yürürlükte ama ikisini
de Melih yapıyor; paralellik takvimde değil, yalnızca dosya kümelerinin
kesişmemesinde işe yarıyor.

⚠️ Bu süre **kod + test** süresidir; ölçümün beklenen sonucu vermemesi
(ör. router %86,7'nin altına düşerse B13.4'ün geri alınması) dahil değildir.
Faz 10-12'de ölçüm turları tahminleri birkaç kez uzattı.

---

## Riskler

| Risk | Karşılık |
|------|----------|
| Sevkiyat geçmişi simülasyon (sim2real) | Faz 4'ün yolu: `shadow` modda gerçek veride ölçüm. Simülasyon "gerçek" diye sunulmaz. |
| Sevkiyat talebi üretimin kopyası çıkar | A13.1'de bilinçli ayrışma; bir test iki serinin korelasyonuna üst sınır koyar |
| Gerekçe LLM'e yazdırılır → uydurma | `AtamaGerekcesi` **veri**, metin değil. Sayısal guard zaten kurulu (Faz 2 B2.5) |
| `tam_plan` içine alan-özel `if` sızar | Kod incelemesinde sert kural; `if alan ==` araması testte |
| Zincir bağı gizli kuplaj yaratır | `isler_kaynagi` **tanımda yazılı**, kodda gizli değil — zincir okunabilir |
| Araç eklemek router'ı düşürür | Aynı donmuş set, model sürümü sabit; düşerse araç geri alınır |
| Üçüncü alan JSON'u ürün özelliği sanılır | `nakliye.json`'daki uyarının aynısı: test verisi olduğu dosyanın içine yazılır |

---

## Kapsam dışı — bilinçli

| Ne | Neden |
|---|---|
| **Coğrafi rota / VRP** | Karar verildi: karar kapasite + uygunluk ataması. Mesafe, adres, durak sırası **yok**. Rota istenirse ayrı bir çözücü ve ayrı bir ölçüm gerektirir — ayrı faz. |
| **Nakliye sevkiyat simülatörü** (~1 hafta) | Planlanmıştı, **silindi.** Bir alanı zenginleştirmek genel mekanizmaya hiçbir şey katmıyor: "geçmişten tahmin" üretimde kanıtlanıyor, "alanı bilmeyen komut" nakliyede. Nakliyenin kendi geçmişi ancak gerçek bir nakliye müşterisi geldiğinde anlam kazanır — ve o zaman biçimi müşteri belirler. |
| **Kurulum sihirbazı / ekran** | Karar verildi: yeni müşteri JSON ile eklenir. Arayüz karar motoruna bir şey katmıyor. |
| **Müşterinin ERP'sinden veri aktarımı** | "Sadece JSON" kararının doğal sınırı. Gerçek müşteri gelince biçimi o belirler; şimdi tahminle yazmak boşa iş. |
| **Satış & Fiyatlama alanı** | İlk yol haritasında vardı, atlandı. Bu fazın konusu değil; [YOL-HARITASI.md](YOL-HARITASI.md)'de sapma olarak kayıtlı. |
| **ABC/XYZ matrisleri ve etki modeli sabitlerinin profile taşınması** | [BILINEN-EKSIKLER.md](BILINEN-EKSIKLER.md)'de açık; gerçek müşteri gelmeden hangi biçimin doğru olduğu belli değil. |
