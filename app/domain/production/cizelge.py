"""Üretim çizelgesi — hangi emir, hangi hatta, hangi gün.

Sahip: Kişi A · Faz 10 · Adım 7

## ⚠️ Çizelge bir KARAR DEĞİL, kararların takvime dizilmiş hâli

Adım 4'te çizelge kurmamanın gerekçesi şuydu: otonomi modeli kalem bazında
insan onayına dayanıyor ve tek bir çizelgeyi onaylamak, içindeki yüzlerce
örtük kararı görmeden onaylamak olurdu.

O gerekçe hâlâ geçerli — ve bu modül onu **bozmuyor**. Buradaki çizelge yeni
bir `KararTipi` üretmiyor, hiçbir şeyi onaya sunmuyor. Girdisi zaten üretilmiş
`uretim.emir_ac` kararları; yaptığı tek şey onları zaman eksenine yerleştirmek.

    karar katmani   : "bu urunden 1500 adet uret"        <- onaylanabilir
    cizelge katmani : "1500 adetlik emir Pzt 08:00'de"   <- turetilmis gorunum

Bir emir reddedilirse çizelgeden düşer ve kalanlar yeniden dizilir. Çizelgeyi
onaylamak diye bir şey yok, çünkü çizelgede onaylanacak bir şey yok.

⚠️ **Bu ayrım korunmalı.** Çizelgeye "şu işi öne al" gibi bir düğme
eklendiği gün, çizelge karar üretmeye başlar ve onay modeli sessizce
delinir. O noktada `KararTipi.URETIM_CIZELGE_DEGISIKLIGI` gibi bir tip ve
kendi onay yolu gerekir.

## Sıralama: en acil önce

Ölçüt yine kapsama günü — eldeki mal kaç gün yeter (`kapasite.py` ile aynı,
ters yönde). Kapasite kararı "en az acili ertele" diyordu; çizelge "en acili
öne al" diyor. İkisi aynı ölçütün iki yüzü ve bilinçli olarak aynı
fonksiyondan besleniyor: iki ayrı öncelik tanımı olsaydı sistem kendi
içinde çelişirdi.

⚠️ Bu **optimizasyon değil**, açgözlü (greedy) bir yerleştirme. Hazırlık
sürelerini toplamayı, benzer ürünleri yan yana koymayı, teslim tarihlerine
göre geriye planlamayı denemiyor. Gerçek bir çizelgeleyici bunları yapar ve
bunu yapmadığımız yazılı olsun: burada üretilen çizelge "makul", "en iyi"
değil.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.contracts import DecisionCandidate, KararTipi, UretimOzellikleri
from app.core.isletme_profili import UretimProfili, profil
from app.domain.production.kapasite import kapsama_gun


@dataclass(frozen=True)
class CizelgeSatiri:
    """Bir emrin çizelgedeki yeri."""

    kalem_id: str
    kalem_adi: str
    hat_id: str
    hat_adi: str
    miktar: int
    baslangic: date
    bitis: date
    yuk_saat: float
    # Emrin sırasını belirleyen sayı — "neden bu iş önce" sorusunun cevabı.
    kapsama_gun: float
    karar_id: str

    @property
    def gun_sayisi(self) -> int:
        return (self.bitis - self.baslangic).days + 1


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


def _emir_satiri(karar: DecisionCandidate) -> tuple[UretimOzellikleri, int, float] | None:
    ozellik = karar.ozellikler
    if karar.tip is not KararTipi.URETIM_EMIR_AC:
        return None
    if not isinstance(ozellik, UretimOzellikleri):
        return None
    miktar = int(karar.aksiyon.get("emir_miktari") or 0)
    yuk = float(karar.aksiyon.get("hat_yuku_saat") or 0.0)
    if miktar <= 0 or yuk <= 0:
        return None
    return ozellik, miktar, yuk


def cizelge_kur(
    emirler: list[DecisionCandidate],
    baslangic: date | None = None,
    uretim_profili: UretimProfili | None = None,
) -> list[HatCizelgesi]:
    """Emirleri hat hat, gün gün yerleştirir.

    Her hat kendi takvimine sahip: hatlar paralel çalışıyor, bir hattaki
    doluluk diğerini geciktirmiyor.

    Yerleştirme günlük kapasiteye göre: bir emir bir güne sığmıyorsa ertesi
    güne taşıyor (bölünebilir iş varsayımı). ⚠️ Gerçek fabrikada her iş
    bölünemez — fırın bir kez yakılır, parti bitene kadar durmaz. Bölünmez
    işler için bu yerleştirme iyimser kalır ve gerçek çizelgeleyici
    geldiğinde ilk düzeltilecek varsayım budur.
    """
    p = uretim_profili or profil().uretim
    ilk_gun = baslangic or date.today()

    hatlar: dict[str, list[tuple[UretimOzellikleri, int, float, str]]] = {}
    for karar in emirler:
        cozum = _emir_satiri(karar)
        if cozum is None:
            continue
        ozellik, miktar, yuk = cozum
        hatlar.setdefault(ozellik.hat_id, []).append((ozellik, miktar, yuk, str(karar.karar_id)))

    return [
        _tek_hat_cizelgesi(hat_id, isler, ilk_gun, p) for hat_id, isler in sorted(hatlar.items())
    ]


def _tek_hat_cizelgesi(
    hat_id: str,
    isler: list[tuple[UretimOzellikleri, int, float, str]],
    ilk_gun: date,
    p: UretimProfili,
) -> HatCizelgesi:
    ornek = isler[0][0]
    gunluk = ornek.hat_gunluk_kapasite_saat * p.hedef_kapasite_kullanimi

    # En acil önce. Eşitlik `kalem_id` ile kırılıyor.
    #
    # ⚠️ Önce `karar_id` kullanılıyordu ve testi kırdı: `karar_id` her karar
    # üretiminde yeniden atanan rastgele bir UUID. Aynı fabrika durumu iki
    # kez hesaplandığında çizelge farklı çıkıyordu — "sistem neden fikir
    # değiştirdi" sorusunun cevabı "değiştirmedi, zar attı" olurdu.
    #
    # Eşitliği kıran şey **iş anlamı taşıyan ve koşudan koşuya değişmeyen**
    # bir alan olmak zorunda. `kalem_id` ikisini de sağlıyor.
    sirali = sorted(isler, key=lambda i: (kapsama_gun(i[0]), i[0].kalem_id))

    satirlar: list[CizelgeSatiri] = []
    sigmayanlar: list[CizelgeSatiri] = []
    gun_offset = 0
    gun_kalan = gunluk

    for ozellik, miktar, yuk, karar_id in sirali:
        # Ufuk dışına taşan iş çizelgeye girmiyor — ama kaybolmuyor.
        if gun_offset >= p.planlama_ufku_gun:
            sigmayanlar.append(
                _satir_kur(ozellik, miktar, yuk, ilk_gun, gun_offset, gun_offset, karar_id)
            )
            continue

        bas_offset = gun_offset
        kalan_yuk = yuk
        while kalan_yuk > 0 and gun_offset < p.planlama_ufku_gun:
            kullanilan = min(kalan_yuk, gun_kalan)
            kalan_yuk -= kullanilan
            gun_kalan -= kullanilan
            if gun_kalan <= 0:
                gun_offset += 1
                gun_kalan = gunluk

        bitis_offset = min(gun_offset, p.planlama_ufku_gun - 1)
        satir = _satir_kur(ozellik, miktar, yuk, ilk_gun, bas_offset, bitis_offset, karar_id)
        if kalan_yuk > 0:
            # Ufuk bitti, iş yarım kaldı: çizelgeye koymak "yetişecek"
            # demek olurdu.
            sigmayanlar.append(satir)
        else:
            satirlar.append(satir)

    return HatCizelgesi(
        hat_id=hat_id,
        hat_adi=ornek.hat_adi,
        satirlar=tuple(satirlar),
        gunluk_kapasite_saat=gunluk,
        sigmayanlar=tuple(sigmayanlar),
    )


def _satir_kur(
    ozellik: UretimOzellikleri,
    miktar: int,
    yuk: float,
    ilk_gun: date,
    bas_offset: int,
    bitis_offset: int,
    karar_id: str,
) -> CizelgeSatiri:
    return CizelgeSatiri(
        kalem_id=ozellik.kalem_id,
        kalem_adi=ozellik.kalem_adi,
        hat_id=ozellik.hat_id,
        hat_adi=ozellik.hat_adi,
        miktar=miktar,
        baslangic=ilk_gun + timedelta(days=bas_offset),
        bitis=ilk_gun + timedelta(days=bitis_offset),
        yuk_saat=round(yuk, 2),
        kapsama_gun=round(min(kapsama_gun(ozellik), 9999.0), 1),
        karar_id=karar_id,
    )


def cizelge_metni(cizelgeler: list[HatCizelgesi]) -> str:
    """Çizelgeyi insan okunur tabloya çevirir.

    Ekran ve API sonradan gelir; önce çıktının doğru olduğu gözle
    görülebilmeli. Bu projede birkaç kez yaşandı: sayı doğruydu ama neyi
    ölçtüğü yanlıştı ve ancak basılınca fark edildi.
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


__all__ = ["CizelgeSatiri", "HatCizelgesi", "cizelge_kur", "cizelge_metni"]
