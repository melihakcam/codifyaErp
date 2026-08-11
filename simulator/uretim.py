"""Fabrika dünyası — hangi kalem üretiliyor, hangi hatta, ne kadar sürede.

Sahip: Kişi A · Faz 10 A10.1

Bugüne kadarki dünyada her SKU **satın alınıyordu**: bir tedarikçisi, bir
tedarik süresi ve bir MOQ'su vardı. Üretim planlaması ise kalemlerin bir
kısmının **kendi ürettiğimiz** şeyler olmasını gerektiriyor — onların
tedarikçisi yok, hattı var; MOQ'su yok, parti büyüklüğü var.

## Bu modül CSV'nin yerine geçiyor

Gerçek kurulumda fabrika ana verisi ERP'den üç CSV ile gelir (ürün ağacı, iş
merkezleri, rotalar). Simülatörde o veriyi burası üretiyor. İkisinin
**çıktısı aynı biçimde** olmak zorunda; alan tarafı hangisinden geldiğini
bilmiyor.

⚠️ Bu yüzden buradaki parametreler `UretimProfili`'ne (işletme profili
JSON'u) **konmadı**. O dosya iş sahibinin elle düzenlediği karar
parametrelerini tutuyor: planlama ufku, emniyet payı, parti politikası.
Buradakiler ise verinin kendisi — "hangi kalem hangi hatta" bir karar
parametresi değil, bir olgu. İkisini aynı dosyaya koymak, profili kimsenin
açmadığı bir dosyaya çevirirdi.

## Üretilen / satın alınan ayrımı neye göre

Rastgele değil, **ciro payına göre**: bir işletme kendi ürettiği şeyi
genelde çok sattığı için üretir. Az satan çeşit malı üretmek yerine satın
almak, hazırlık süresi (setup) yüzünden neredeyse her zaman daha ucuzdur.

⚠️ Bunun ölçüm açısından bir sonucu var ve bilinmeli: üretilen kalemler
kataloğun **hızlı satan** ucunda yoğunlaşıyor. Yani üretim kararları,
tahminin en iyi çalıştığı katmanda alınacak. Tahmin ölçümündeki kötü
sayılar (yavaş katmanda MASE > 1) üretim planını olduğu gibi vurmuyor —
ama bu bir şans, tasarım değil. Gerçek fabrikada üretilen kalem listesi
ciroya göre değil, **yapılabilirliğe** göre belirlenir ve orada yavaş
kalemler de olur.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Fabrika profili — CSV'den okunacak ana verinin simülasyon karşılığı
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HatProfili:
    """Bir üretim hattının kapasitesi ve davranışı."""

    hat_id: str
    ad: str
    # Hattın günde kaç saat çalıştığı. Kapasite kararının (Adım 4) tabanı.
    gunluk_kapasite_saat: float
    # Bu hatta bir kalemden diğerine geçmenin sabit süresi.
    hazirlik_suresi_saat: float
    # Bir adedin hattaki işlem süresi aralığı (saat). Kalem başına örneklenir.
    birim_islem_suresi_min: float
    birim_islem_suresi_max: float


@dataclass(frozen=True)
class FabrikaProfili:
    """Simülasyondaki fabrikanın tamamı.

    ⚠️ `uretilen_kalem_orani` kataloğun **ciro sıralamasının üstünden**
    alınıyor, rastgele değil — modül docstring'indeki gerekçe.
    """

    ad: str
    hatlar: tuple[HatProfili, ...]
    uretilen_kalem_orani: float = 0.15
    # Parti büyüklüğü, kalemin günlük talebinin kaç katı olarak seçilsin.
    # Gerçek fabrikada parti, hazırlık süresini amorti edecek kadar büyük
    # tutulur; bu çarpan onun kaba karşılığı.
    parti_gun_carpani: float = 10.0
    # Parti büyüklükleri bu sayılara yuvarlanır — "1187 adetlik parti" diye
    # bir şey yok, hat 100'lük ya da 500'lük partiler koşar.
    parti_yuvarlama_secenekleri: tuple[int, ...] = (10, 25, 50, 100, 250, 500)
    # Üretim süresi: hazırlık + işlem dışında beklemenin (kuyruk, malzeme,
    # kalite) kaba karşılığı. Gerçek hatta lead time işlem süresinden
    # belirgin biçimde uzundur; bunu 0 saymak planı sistematik iyimser yapar.
    asgari_uretim_suresi_gun: float = 2.0
    azami_uretim_suresi_gun: float = 10.0


def varsayilan_fabrika() -> FabrikaProfili:
    """Yapı malzemesi toptancısının kendi ürettiği kalemler için üç hat.

    Hatlar kataloğun kategorilerinden bağımsız tutuldu: gerçek fabrikada bir
    hat birden çok kategoriyi koşar ve kalemi hatta bağlayan şey kategori
    değil, işlem tipidir.
    """
    return FabrikaProfili(
        ad="Codifya Üretim",
        hatlar=(
            HatProfili(
                hat_id="H-01",
                ad="Kesim Hattı",
                gunluk_kapasite_saat=16.0,
                hazirlik_suresi_saat=1.5,
                birim_islem_suresi_min=0.002,
                birim_islem_suresi_max=0.010,
            ),
            HatProfili(
                hat_id="H-02",
                ad="Montaj Hattı",
                gunluk_kapasite_saat=8.0,
                hazirlik_suresi_saat=3.0,
                birim_islem_suresi_min=0.010,
                birim_islem_suresi_max=0.040,
            ),
            HatProfili(
                hat_id="H-03",
                ad="Paketleme Hattı",
                gunluk_kapasite_saat=24.0,
                hazirlik_suresi_saat=0.5,
                birim_islem_suresi_min=0.001,
                birim_islem_suresi_max=0.005,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Üretim ana verisi
# ---------------------------------------------------------------------------


def _parti_buyuklugu_sec(gunluk_talep: float, carpani: float, secenekler: tuple[int, ...]) -> int:
    """Günlük talebin `carpani` katına en yakın standart parti.

    ⚠️ Aşağı değil **en yakına** yuvarlanıyor ve asgari seçenek taban.
    Aşağı yuvarlamak, günde 0,05 satan bir kalemde partiyi 0'a indirirdi ve
    `parti_buyuklugu > 0` sözleşmesi kurulum anında patlardı — ama asıl
    sorun o değil: sıfır parti "bu kalem üretilemez" demek olurdu ve bunu
    bir yuvarlama hatası söylemiş olurdu.
    """
    hedef = max(gunluk_talep * carpani, float(min(secenekler)))
    return min(secenekler, key=lambda s: abs(s - hedef))


def uretim_ana_verisi_uret(
    sku_df: pd.DataFrame,
    talep_df: pd.DataFrame | None = None,
    fabrika: FabrikaProfili | None = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Kataloğu üretilen/satın alınan diye ayırır ve üretilenlere hat verir.

    Dönen tablo **yalnızca üretilen kalemleri** içerir; satın alınanlar için
    satır yok. Sebebi biçimsel değil anlamsal: "üretim süresi NULL" olan bir
    satır, sorgulayan tarafın her yerde NULL kontrolü yapmasını gerektirir ve
    bir yerde unutulur.

    `talep_df` verilmezse parti büyüklüğü ciro payından türetilir. Gerçek
    kurulumda parti büyüklüğü CSV'den gelir ve bu tahmin hiç kullanılmaz.

    ⚠️ Aynı `seed` ile bit bit aynı tabloyu üretir. Ölçüm tekrarlanabilir
    olmazsa "üretim kararı iyileşti mi" sorusu sonradan cevaplanamaz —
    tahmin ölçümünde bu dersi iki kez aldık.
    """
    fabrika = fabrika or varsayilan_fabrika()
    rng = np.random.default_rng(seed)

    # Ciro payına göre üst dilim üretiliyor.
    sirali = sku_df.sort_values("yillik_ciro_payi", ascending=False)
    adet = max(1, int(len(sirali) * fabrika.uretilen_kalem_orani))
    uretilenler = sirali.head(adet).copy()

    # Günlük talep: parti büyüklüğünün girdisi.
    if talep_df is not None:
        gun_sayisi = talep_df["tarih"].nunique()
        toplam = talep_df.groupby("sku_id")["talep_miktari"].sum()
        gunluk_talep = (toplam / max(gun_sayisi, 1)).reindex(uretilenler["sku_id"]).fillna(0.0)
    else:
        gunluk_talep = pd.Series(
            uretilenler["yillik_ciro_payi"].to_numpy() * 1000.0 / 365.0,
            index=uretilenler["sku_id"],
        )

    n = len(uretilenler)
    hat_index = rng.integers(0, len(fabrika.hatlar), size=n)
    hatlar = [fabrika.hatlar[i] for i in hat_index]

    birim_islem = np.array(
        [rng.uniform(h.birim_islem_suresi_min, h.birim_islem_suresi_max) for h in hatlar]
    )
    uretim_suresi = rng.uniform(
        fabrika.asgari_uretim_suresi_gun, fabrika.azami_uretim_suresi_gun, size=n
    )
    parti = [
        _parti_buyuklugu_sec(
            float(gunluk_talep.loc[sku_id]),
            fabrika.parti_gun_carpani,
            fabrika.parti_yuvarlama_secenekleri,
        )
        for sku_id in uretilenler["sku_id"]
    ]

    return pd.DataFrame(
        {
            "sku_id": uretilenler["sku_id"].to_numpy(),
            "hat_id": [h.hat_id for h in hatlar],
            "hat_adi": [h.ad for h in hatlar],
            "parti_buyuklugu": parti,
            # Asgari parti = bir parti. Hazırlık süresini yarım partiye
            # amorti etmek, hattın en pahalı dakikalarını çöpe atmak olurdu.
            "asgari_parti": parti,
            "hazirlik_suresi_saat": [h.hazirlik_suresi_saat for h in hatlar],
            "birim_islem_suresi_saat": birim_islem,
            "uretim_suresi_gun": uretim_suresi,
            "gunluk_kapasite_saat": [h.gunluk_kapasite_saat for h in hatlar],
        }
    )


def uretilen_mi(sku_id: str, uretim_df: pd.DataFrame) -> bool:
    """Kalem üretiliyor mu, satın mı alınıyor?"""
    return bool((uretim_df["sku_id"] == sku_id).any())


# ---------------------------------------------------------------------------
# Ürün ağacı (BOM) — Adım 5'in girdisi
# ---------------------------------------------------------------------------

# Bir üretilen kalemin kaç farklı hammaddeden oluştuğu.
#
# Gerçek ürün ağaçları çok daha derin ve geniş olabilir; buradaki amaç MRP
# mantığını sınamak, gerçek bir ürünü modellemek değil.
ASGARI_BILESEN = 2
AZAMI_BILESEN = 5


def urun_agaci_uret(
    sku_df: pd.DataFrame,
    uretim_df: pd.DataFrame,
    seed: int = 42,
) -> pd.DataFrame:
    """Üretilen her kalem için hammadde listesi.

    Dönen tablo: `uretilen_sku_id`, `bilesen_sku_id`, `birim_basina_miktar`.

    ## ⚠️ Ağaç TEK KATMANLI ve bu bilinçli

    Bileşenler yalnızca **satın alınan** kalemlerden seçiliyor, yani
    "üretilen ürün → hammadde" tek adımda bitiyor. Gerçek ürün ağaçları çok
    katmanlı olabilir (yarı mamul → mamul) ve orada patlatma özyinelemeli
    yapılır.

    Tek katmanla başlamanın sebebi ölçülebilirlik: çok katmanlı bir ağaçta
    MRP çıktısı yanlışsa hatanın hangi katmanda olduğunu ayırt etmek zor.
    Önce tek katman doğrulanır, sonra derinlik eklenir.

    ⚠️ Bir bileşenin **kendisinin de üretilen** olması özyinelemeye ve
    sonsuz döngüye açık kapı bırakır (A parçası B'yi, B de A'yı içerirse).
    Satın alınanlarla sınırlamak bu riski yapısal olarak kapatıyor —
    kontrol etmek yerine imkânsız kılmak.
    """
    rng = np.random.default_rng(seed)

    uretilen_idler = set(uretim_df["sku_id"])
    satin_alinanlar = sku_df[~sku_df["sku_id"].isin(uretilen_idler)]["sku_id"].to_numpy()
    if len(satin_alinanlar) == 0:
        raise ValueError("Ürün ağacı kurulamıyor: kataloğun tamamı üretiliyor, hammadde kalmıyor.")

    satirlar = []
    for uretilen in uretim_df["sku_id"]:
        adet = int(rng.integers(ASGARI_BILESEN, AZAMI_BILESEN + 1))
        bilesenler = rng.choice(satin_alinanlar, size=adet, replace=False)
        for bilesen in bilesenler:
            satirlar.append(
                {
                    "uretilen_sku_id": uretilen,
                    "bilesen_sku_id": str(bilesen),
                    # Bir adet mamul için kaç adet hammadde. Tam sayı değil:
                    # 0,5 kg boya, 1,5 m profil gibi kullanımlar gerçek.
                    "birim_basina_miktar": round(float(rng.uniform(0.5, 4.0)), 2),
                }
            )

    return pd.DataFrame(satirlar)


__all__ = [
    "ASGARI_BILESEN",
    "AZAMI_BILESEN",
    "FabrikaProfili",
    "HatProfili",
    "uretilen_mi",
    "uretim_ana_verisi_uret",
    "urun_agaci_uret",
    "varsayilan_fabrika",
]
