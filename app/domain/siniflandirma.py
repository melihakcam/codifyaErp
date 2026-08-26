"""ABC/XYZ sınıflandırması — alandan bağımsız çekirdek (Faz 6).

Bu modül Faz 6'da doğdu ama **yeni bir fikir değil**: kod Faz 2'de
`app/domain/stock/rules.py` içinde yazılmıştı. Finans alanı eklenirken
ortaya çıktı ki iki soru da aynı:

    stokta  : bu ÜRÜN ciroya ne kadar katkı veriyor, talebi ne kadar düzenli?
    finansta: bu MÜŞTERİ ciroya ne kadar katkı veriyor, ödemesi ne kadar düzenli?

⚠️ Modül `app/domain/stock/` içinde bırakılıp finanstan import edilebilirdi
— ama o zaman finans stoka bağımlı olurdu. İki eşdüzey alandan birinin
diğerine bağlanması, üçüncü alan (satış) eklendiğinde çözülemez bir düğüme
dönerdi. Ortak çekirdek üst dizinde durmalı.

## İki eksenin anlamı

**ABC — büyüklük.** Kümülatif katkıya göre: cironun %80'ini taşıyan azınlık
A, sonraki %15 B, kalan C. Pareto.

**XYZ — öngörülebilirlik.** Değişim katsayısına (σ/μ) göre: düzenli X,
orta Y, kaotik Z.

⭐ İki eksenin **bağımsız** olması modelin özü. Cirosu yüksek ama kaotik bir
kalem (AZ) ile cirosu düşük ama düzenli bir kalem (CX) tamamen farklı
muamele ister. Tek bir "önem skoru" bu ayrımı yok ederdi.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

from app.contracts import ABCSinifi, XYZSinifi

# Pareto kesimleri. Cironun %80'ini taşıyanlar A, %95'e kadar B, gerisi C.
ABC_KESIM_A = 0.80
ABC_KESIM_B = 0.95

# Değişim katsayısı (σ/μ) kesimleri. 0,5 altı düzenli sayılır; 1,0 üstü,
# sapmanın ortalamayı aştığı yer — orada tahmin pratikte işe yaramaz.
XYZ_KESIM_X = 0.5
XYZ_KESIM_Y = 1.0


def abc_sinif_ata(kumulatif_deger_orani: float) -> ABCSinifi:
    """Kümülatif katkı oranından ABC sınıfı."""
    if kumulatif_deger_orani <= ABC_KESIM_A:
        return ABCSinifi.A
    if kumulatif_deger_orani <= ABC_KESIM_B:
        return ABCSinifi.B
    return ABCSinifi.C


def xyz_sinif_ata(varyasyon_katsayisi: float) -> XYZSinifi:
    """Değişim katsayısından (σ/μ) XYZ sınıfı."""
    if varyasyon_katsayisi <= XYZ_KESIM_X:
        return XYZSinifi.X
    if varyasyon_katsayisi <= XYZ_KESIM_Y:
        return XYZSinifi.Y
    return XYZSinifi.Z


def abc_xyz_hesapla(
    kimlikler: Sequence[str],
    degerler: Sequence[float],
    varyasyonlar: Sequence[float],
    *,
    kimlik_adi: str = "kimlik",
    deger_adi: str = "deger",
) -> pd.DataFrame:
    """Kimlik + büyüklük + oynaklık üçlüsünden ABC/XYZ tablosu.

    Alan bilmiyor: stokta `(sku_id, yıllık ciro, talep oynaklığı)`, finansta
    `(musteri_id, yıllık ciro, ödeme gecikmesi oynaklığı)` verilir.

    ⚠️ Toplam değer 0 ise kümülatif oran **1.0** kabul edilir, yani herkes C
    olur. Sıfıra bölme yerine bu seçildi çünkü anlamı doğru: hiç ciro yoksa
    hiçbir kalem "cironun %80'ini taşıyan azınlık" olamaz.

    Dönen tablo `kimlik_adi` ile indekslenir; kolonlar: `deger_adi`,
    `varyasyon_katsayisi`, `abc_sinifi`, `xyz_sinifi`.
    """
    df = pd.DataFrame(
        {
            kimlik_adi: list(kimlikler),
            deger_adi: list(degerler),
            "varyasyon_katsayisi": list(varyasyonlar),
        }
    ).set_index(kimlik_adi)

    toplam = df[deger_adi].sum()
    df = df.sort_values(deger_adi, ascending=False)
    kumulatif = df[deger_adi].cumsum() / toplam if toplam > 0 else pd.Series(1.0, index=df.index)

    df["abc_sinifi"] = kumulatif.apply(abc_sinif_ata)
    df["xyz_sinifi"] = df["varyasyon_katsayisi"].apply(xyz_sinif_ata)
    return df


def matris_degeri(
    matris: dict[tuple[ABCSinifi, XYZSinifi], float],
    abc: ABCSinifi,
    xyz: XYZSinifi,
) -> float:
    """ABC/XYZ matrisinden hedef değer okur.

    Her alan kendi matrisini tanımlar (stokta hedef servis seviyesi,
    finansta hedef tahsilat oranı) ama okuma biçimi ortak.
    """
    return matris[(abc, xyz)]


__all__ = [
    "ABC_KESIM_A",
    "ABC_KESIM_B",
    "XYZ_KESIM_X",
    "XYZ_KESIM_Y",
    "abc_sinif_ata",
    "abc_xyz_hesapla",
    "matris_degeri",
    "xyz_sinif_ata",
]
