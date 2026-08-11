"""MRP — üretim emirlerini hammadde ihtiyacına çevirir.

Sahip: Kişi A · Faz 10 A10.4 (Adım 5)

## ⚠️ Bu modül YENİ BİR KARAR TÜRÜ ÜRETMİYOR

Çıktısı `stok.siparis` kararının **girdisi**. Sebebi mimari: hammadde
sipariş etmek zaten stok alanının işi ve orada çalışan bir kural motoru var
(ROP, emniyet stoğu, EOQ, MOQ, tedarikçi seçimi). MRP'nin eklediği tek şey
şu bilgi: "bu hammaddeden ayrıca üretim için de şu kadar lazım."

Ayrı bir `uretim.malzeme_siparis` tipi tanımlamak cazipti ve yanlış olurdu:
aynı hammadde için iki ayrı kaynaktan iki ayrı sipariş kararı çıkardı ve
ikisi birbirini görmezdi. Sonuç, tam olarak kaçınmaya çalıştığımız şey —
üst üste sipariş.

## İki alanı ilk kez birbirine bağlıyor

Bugüne kadar stok ve üretim ayrı dünyalardı. Bu modül aradaki tek bağ ve
yönü **tek**: üretim → stok. Ters yön (stok kararının üretimi etkilemesi)
bilinçli olarak yok; olsaydı iki alan birbirini besleyen bir döngüye girerdi
ve "önce hangisi hesaplanır" sorusunun cevabı olmazdı.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.contracts import DecisionCandidate, KararTipi, UretimOzellikleri


@dataclass(frozen=True)
class HammaddeIhtiyaci:
    """Bir hammaddenin üretim emirlerinden doğan toplam ihtiyacı.

    `kaynak_emirler` izlenebilirlik için: "bu 4.200 adet nereden çıktı"
    sorusu sonradan sorulacak ve cevabı olmazsa sayı savunulamaz. Stok
    tarafındaki gerekçe metni de bunu kullanacak.
    """

    hammadde_id: str
    toplam_miktar: float
    kaynak_emirler: tuple[str, ...] = field(default_factory=tuple)


def hammadde_ihtiyaci_hesapla(
    emirler: list[DecisionCandidate],
    urun_agaci: pd.DataFrame,
) -> dict[str, HammaddeIhtiyaci]:
    """Üretim emirlerini patlatıp hammadde başına toplam ihtiyacı çıkarır.

    Yalnızca `uretim.emir_ac` kararları sayılıyor. Ertelenen ve aksiyon
    gerektirmeyen kalemler için hammadde de ayrılmamalı — ertelenen bir emrin
    malzemesini şimdiden sipariş etmek, ertelemenin amacını boşa çıkarırdı.

    ⚠️ Ürün ağacında **olmayan** bir kalem sessizce atlanıyor ve bu doğru:
    her üretilen kalemin ağacı tanımlı olmayabilir (yeni ürün, eksik ana
    veri). Hata fırlatmak tüm MRP koşusunu tek bir eksik satır yüzünden
    durdururdu. Ama sessizlik de tehlikeli — `eksik_agac_kalemleri()` bunu
    ayrıca raporluyor.
    """
    agac = urun_agaci.groupby("uretilen_sku_id")
    birikim: dict[str, tuple[float, list[str]]] = {}

    for emir in emirler:
        if emir.tip is not KararTipi.URETIM_EMIR_AC:
            continue
        if not isinstance(emir.ozellikler, UretimOzellikleri):
            continue

        kalem_id = emir.ozellikler.kalem_id
        if kalem_id not in agac.groups:
            continue

        miktar = float(emir.aksiyon.get("emir_miktari") or 0.0)
        if miktar <= 0:
            continue

        for _, satir in agac.get_group(kalem_id).iterrows():
            hammadde = str(satir["bilesen_sku_id"])
            gerekli = miktar * float(satir["birim_basina_miktar"])
            toplam, kaynaklar = birikim.get(hammadde, (0.0, []))
            birikim[hammadde] = (toplam + gerekli, [*kaynaklar, kalem_id])

    return {
        hammadde: HammaddeIhtiyaci(
            hammadde_id=hammadde,
            # ⚠️ Yukarı yuvarlanıyor: 0,3 adet hammadde diye bir şey yok ve
            # aşağı yuvarlamak, emri koşturmaya yetmeyen bir sipariş
            # önermek olurdu.
            toplam_miktar=float(round(toplam + 0.4999999, 0)),
            kaynak_emirler=tuple(sorted(set(kaynaklar))),
        )
        for hammadde, (toplam, kaynaklar) in sorted(birikim.items())
    }


def eksik_agac_kalemleri(
    emirler: list[DecisionCandidate],
    urun_agaci: pd.DataFrame,
) -> list[str]:
    """Emir açılan ama ürün ağacı tanımlı olmayan kalemler.

    ⚠️ Bu liste boş değilse **MRP eksik hesaplıyor** demektir: o kalemlerin
    hammaddesi hiç sipariş edilmeyecek ve emir malzemesizlikten koşmayacak.
    Sessiz atlamanın gerekli ama yeterli olmayan tarafı bu — atlamayı
    görünür kılmadan sessiz bırakmak, üretimi durduran bir hatayı üç ay
    sonra keşfetmek olurdu.
    """
    tanimlilar = set(urun_agaci["uretilen_sku_id"])
    eksikler = {
        emir.ozellikler.kalem_id
        for emir in emirler
        if emir.tip is KararTipi.URETIM_EMIR_AC
        and isinstance(emir.ozellikler, UretimOzellikleri)
        and emir.ozellikler.kalem_id not in tanimlilar
    }
    return sorted(eksikler)


__all__ = ["HammaddeIhtiyaci", "eksik_agac_kalemleri", "hammadde_ihtiyaci_hesapla"]
