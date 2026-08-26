"""Üretim çizelgesi — genel planlama motorunun üretim adaptörü.

Sahip: Kişi A · Faz 10 Adım 7 → Faz 11 A11.4

## ⚠️ Çizelge bir KARAR DEĞİL, kararların takvime dizilmiş hâli

Adım 4'te çizelge kurmamanın gerekçesi şuydu: otonomi modeli kalem bazında
insan onayına dayanıyor ve tek bir çizelgeyi onaylamak, içindeki yüzlerce
örtük kararı görmeden onaylamak olurdu.

O gerekçe hâlâ geçerli ve bu modül onu **bozmuyor**. Yeni bir `KararTipi`
üretilmiyor, hiçbir şey onaya sunulmuyor. Girdisi zaten üretilmiş
`uretim.emir_ac` kararları; yapılan tek şey onları zaman eksenine koymak.

⚠️ **Bu ayrım korunmalı.** Çizelgeye "şu işi öne al" gibi bir düğme
eklendiği gün çizelge karar üretmeye başlar ve onay modeli sessizce delinir.
O noktada `KararTipi.URETIM_CIZELGE_DEGISIKLIGI` gibi bir tip ve kendi onay
yolu gerekir.

## Faz 11: yerleştirme mantığı buradan çıktı

Bu dosya artık **ince bir adaptör**. Yerleştirme, sıralama, gün taşırma ve
tekrarlanabilirlik `app/planlama/` içinde ve orası alan kelimesi kullanmıyor.
Burada kalan tek iş çeviri:

    uretim.emir_ac karari  ->  Is     (yuk = hat yuku saat)
    hat                    ->  Kaynak (gunluk kapasite x hedef kullanim)
    kapsama gunu           ->  oncelik

Taşımanın kanıtı testlerde: `tests/test_uretim.py`'deki çizelge testleri
**değiştirilmeden** geçiyor. Değiştirmek gerekseydi davranış kaymış olurdu.

## Sıralama ölçütü kapasite kararıyla aynı

`kapasite.py` "en az acili ertele" diyor, çizelge "en acili öne al". İkisi
aynı ölçütün (`kapsama_gun`) iki yüzü ve bilinçli olarak aynı fonksiyondan
besleniyor: iki ayrı öncelik tanımı sistemi kendi içinde çelişkiye sokardı.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.contracts import DecisionCandidate, KararTipi, UretimOzellikleri
from app.core.isletme_profili import UretimProfili, profil
from app.domain.production.kapasite import kapsama_gun
from app.planlama.contracts import Is, Kaynak, KaynakPlani, PlanSatiri
from app.planlama.olcut import VARSAYILAN_OLCUT
from app.planlama.yerlestirme import plan_kur

# Etiket anahtarları: motorun taşıdığı ama bakmadığı alan bilgisi.
ETIKET_KALEM = "kalem_id"
ETIKET_MIKTAR = "miktar"
ETIKET_TUTAR = "tutar"
ETIKET_KARAR = "karar_id"


@dataclass(frozen=True)
class CizelgeSatiri:
    """Bir emrin çizelgedeki yeri — üretim diliyle.

    ⚠️ `PlanSatiri`'nin üzerine ince bir görünüm. Alan tarafının "kalem",
    "hat", "miktar" demeye devam etmesi için var; motor bu kelimeleri
    bilmiyor ve bilmemeli.
    """

    kalem_id: str
    kalem_adi: str
    hat_id: str
    hat_adi: str
    miktar: int
    baslangic: date
    bitis: date
    yuk_saat: float
    kapsama_gun: float
    karar_id: str

    @property
    def gun_sayisi(self) -> int:
        return (self.bitis - self.baslangic).days + 1

    @classmethod
    def plandan(cls, satir: PlanSatiri) -> CizelgeSatiri:
        return cls(
            kalem_id=satir.etiketler.get(ETIKET_KALEM, satir.is_id),
            kalem_adi=satir.ad,
            hat_id=satir.kaynak_id,
            hat_adi=satir.kaynak_adi,
            miktar=int(float(satir.etiketler.get(ETIKET_MIKTAR, 0))),
            baslangic=satir.baslangic,
            bitis=satir.bitis,
            yuk_saat=round(satir.yuk, 2),
            kapsama_gun=round(satir.oncelik, 1),
            karar_id=satir.etiketler.get(ETIKET_KARAR, ""),
        )


@dataclass(frozen=True)
class HatCizelgesi:
    """Bir hattın çizelgesi ve doluluk özeti."""

    hat_id: str
    hat_adi: str
    satirlar: tuple[CizelgeSatiri, ...]
    gunluk_kapasite_saat: float
    # ⚠️ Sığmayanlar ayrı tutuluyor, sessizce atılmıyor. Bir emri çizelgeye
    # koymamak onu iptal etmek değil; kullanıcı hangi işin dışarıda
    # kaldığını görmek zorunda.
    sigmayanlar: tuple[CizelgeSatiri, ...] = ()

    @property
    def toplam_yuk_saat(self) -> float:
        return sum(s.yuk_saat for s in self.satirlar)

    @classmethod
    def plandan(cls, plan: KaynakPlani) -> HatCizelgesi:
        return cls(
            hat_id=plan.kaynak_id,
            hat_adi=plan.kaynak_adi,
            satirlar=tuple(CizelgeSatiri.plandan(s) for s in plan.satirlar),
            gunluk_kapasite_saat=plan.gunluk_kapasite,
            sigmayanlar=tuple(CizelgeSatiri.plandan(s) for s in plan.sigmayanlar),
        )


def emirleri_ise_cevir(emirler: list[DecisionCandidate]) -> tuple[list[Is], list[Kaynak]]:
    """`uretim.emir_ac` kararları → genel motorun anladığı iş ve kaynaklar.

    Adaptörün tamamı burada. Emir dışındaki karar tipleri atlanıyor: aksiyon
    yok kararının hatta yükü yok, dolayısıyla çizelgede yeri de yok.

    ⚠️ İş kimliği `karar_id` DEĞİL `kalem_id`. `karar_id` her karar
    üretiminde yeniden atanan rastgele bir UUID; motor eşitliği `is_id` ile
    kırdığı için onu kimlik yapmak aynı girdiye farklı plan üretirdi. Bu
    hata bir kez yapıldı ve tekrarlanabilirlik testi yakaladı.
    """
    isler: list[Is] = []
    kaynaklar: dict[str, Kaynak] = {}
    p = profil().uretim

    for karar in emirler:
        ozellik = karar.ozellikler
        if karar.tip is not KararTipi.URETIM_EMIR_AC:
            continue
        if not isinstance(ozellik, UretimOzellikleri):
            continue

        miktar = int(karar.aksiyon.get("emir_miktari") or 0)
        yuk = float(karar.aksiyon.get("hat_yuku_saat") or 0.0)
        if miktar <= 0 or yuk <= 0:
            continue

        kaynaklar.setdefault(
            ozellik.hat_id,
            Kaynak(
                kaynak_id=ozellik.hat_id,
                ad=ozellik.hat_adi,
                # Hedef kullanım oranı burada çarpan: %100 dolu bir hat, tek
                # gecikmede tüm planı kaydırır (`kapasite.py` ile aynı gerekçe).
                gunluk_kapasite=ozellik.hat_gunluk_kapasite_saat * p.hedef_kapasite_kullanimi,
                kapasite_birimi="saat",
            ),
        )
        isler.append(
            Is(
                is_id=ozellik.kalem_id,
                ad=ozellik.kalem_adi,
                yuk=yuk,
                oncelik=min(kapsama_gun(ozellik), 9999.0),
                kaynak_id=ozellik.hat_id,
                etiketler={
                    ETIKET_KALEM: ozellik.kalem_id,
                    ETIKET_MIKTAR: str(miktar),
                    ETIKET_TUTAR: str(karar.tahmini_tutar_tl),
                    ETIKET_KARAR: str(karar.karar_id),
                },
            )
        )

    return isler, list(kaynaklar.values())


def cizelge_kur(
    emirler: list[DecisionCandidate],
    baslangic: date | None = None,
    uretim_profili: UretimProfili | None = None,
    olcut: str = VARSAYILAN_OLCUT,
) -> list[HatCizelgesi]:
    """Emirleri hat ve güne dizer — genel motoru çağırır.

    `olcut` ile "iyi plan" tanımı değiştirilebiliyor
    (`app/planlama/olcut.py`). Varsayılan `en_acil`, yani bugünkü davranış;
    varsayılanı değiştirmek hiçbir şey istemeyen çağıranın planını sessizce
    değiştirirdi.
    """
    p = uretim_profili or profil().uretim
    isler, kaynaklar = emirleri_ise_cevir(emirler)
    if not isler:
        return []

    planlar = plan_kur(
        isler,
        kaynaklar,
        olcut=olcut,
        ufuk_gun=p.planlama_ufku_gun,
        baslangic=baslangic,
    )
    return [HatCizelgesi.plandan(plan) for plan in planlar]


def cizelge_metni(cizelgeler: list[HatCizelgesi]) -> str:
    """Çizelgeyi insan okunur tabloya çevirir — üretim diliyle.

    ⚠️ Genel motorun `plan_metni`'nden ayrı: orada "öncelik 3" yazıyor,
    burada "stok 3g". Aynı sayı, ama üretim sorumlusunun okuduğu şey stok
    kapsaması; genel motor o kelimeyi bilmiyor.
    """
    satirlar: list[str] = []
    for hat in cizelgeler:
        satirlar.append(
            f"\n{hat.hat_adi} ({hat.hat_id}) — günde {hat.gunluk_kapasite_saat:.1f} saat"
        )
        satirlar.append("-" * 72)
        if not hat.satirlar:
            satirlar.append("  (bu hatta planlanan iş yok)")
        for s in hat.satirlar:
            tarih = (
                s.baslangic.strftime("%d.%m")
                if s.gun_sayisi == 1
                else f"{s.baslangic:%d.%m}-{s.bitis:%d.%m}"
            )
            satirlar.append(
                f"  {tarih:<12}{s.kalem_adi[:32]:<34}{s.miktar:>7} adet"
                f"{s.yuk_saat:>8.1f} sa   stok {s.kapsama_gun:.0f}g"
            )
        if hat.sigmayanlar:
            satirlar.append(f"  ⚠️ ufka sığmayan {len(hat.sigmayanlar)} iş:")
            for s in hat.sigmayanlar:
                satirlar.append(f"     {s.kalem_adi[:32]:<34}{s.miktar:>7} adet")
    return "\n".join(satirlar)


__all__ = [
    "CizelgeSatiri",
    "HatCizelgesi",
    "cizelge_kur",
    "cizelge_metni",
    "emirleri_ise_cevir",
]
