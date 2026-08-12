"""Genel yerleştirme — işleri kaynaklara ve günlere dağıtır.

Sahip: Kişi A · Faz 11 A11.1

## ⚠️ Bu bir OPTİMİZE EDİCİ DEĞİL

Açgözlü (greedy) yerleştirme: ölçüte göre sırala, sırayla yerleştir, kaynak
dolunca ertesi güne geç. Hazırlık sürelerini gruplamıyor, benzer işleri yan
yana koymuyor, teslim tarihine göre geriye planlamıyor, iş sırasını
iyileştirmiyor.

Gerçek bir çözücü (OR-Tools/CP-SAT) bunları yapar. Oraya geçilirse **bu
dosya** değişir, `contracts.py` değişmez — alanlar bu ayrımın arkasında
duruyor ve hiçbiri etkilenmez.

Üretilen plan "makul", "en iyi" değil. Bu yazılı olsun ki kimse çıktının
optimize edilmiş olduğunu sanmasın.

## Atama: "şu araç şuraya gidebilir"

`Is.kaynak_id` boşsa iş, uygun kaynaklar arasından **o an en boş olana**
veriliyor. Bu da açgözlü: ileriye bakmıyor, "bu işi buraya verirsem
sonraki iş nereye gider" diye sormuyor.

⚠️ En boş kaynağı seçmek, en erken biten kaynağı seçmekle aynı şey değil —
kapasiteler farklıysa ayrışırlar. **Doluluk oranı** kullanılıyor (yük /
kapasite), mutlak yük değil: günde 24 saat çalışan bir hat, 8 saatlik hattan
daha fazla yük taşıyabilir ve mutlak yüke bakmak onu haksız yere dolu
gösterirdi.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.planlama.contracts import Is, Kaynak, KaynakPlani, PlanSatiri
from app.planlama.olcut import VARSAYILAN_OLCUT, Olcut, olcut_al


def _sirala(isler: list[Is], olcut: Olcut) -> list[Is]:
    """Ölçüte göre sırala; eşitliği `is_id` ile kır.

    ⚠️ Eşitlik kıran alan **iş anlamı taşıyan ve koşudan koşuya
    değişmeyen** bir şey olmak zorunda. Bugün üretim tarafında bu bir kez
    yanlış yapıldı: `karar_id` kullanıldı ve o alan her karar üretiminde
    yeniden atanan rastgele bir UUID. Aynı fabrika durumu iki kez
    hesaplandığında farklı plan çıkıyordu — "sistem neden fikir değiştirdi"
    sorusunun cevabı "değiştirmedi, zar attı" olurdu.
    """
    return sorted(isler, key=lambda i: (olcut(i), i.is_id))


class _KaynakDurumu:
    """Bir kaynağın plan boyunca dolan takvimi."""

    def __init__(self, kaynak: Kaynak, ufuk_gun: int) -> None:
        self.kaynak = kaynak
        self.ufuk_gun = ufuk_gun
        self.gun = 0
        self.gun_kalan = kaynak.gunluk_kapasite
        self.satirlar: list[PlanSatiri] = []
        self.sigmayanlar: list[PlanSatiri] = []

    @property
    def doluluk(self) -> float:
        """Kullanılan kapasitenin ufka oranı — atama kararının ölçütü."""
        toplam = self.kaynak.gunluk_kapasite * self.ufuk_gun
        kullanilan = sum(s.yuk for s in self.satirlar)
        return kullanilan / toplam if toplam else 1.0


def _satir(durum: _KaynakDurumu, is_: Is, ilk_gun: date, bas: int, bitis: int) -> PlanSatiri:
    return PlanSatiri(
        is_id=is_.is_id,
        ad=is_.ad,
        kaynak_id=durum.kaynak.kaynak_id,
        kaynak_adi=durum.kaynak.ad,
        baslangic=ilk_gun + timedelta(days=bas),
        bitis=ilk_gun + timedelta(days=bitis),
        yuk=is_.yuk,
        oncelik=is_.oncelik,
        etiketler=is_.etiketler,
    )


def _yerlestir(durum: _KaynakDurumu, is_: Is, ilk_gun: date) -> PlanSatiri:
    """İşi kaynağın takvimine koyar ve satırı döndürür."""
    if not is_.bolunebilir:
        if is_.yuk > durum.kaynak.gunluk_kapasite:
            # ⚠️ Bölünemez ve tek güne HİÇ sığmayan iş. Bunu güne yaymak
            # "yetişecek" demek olurdu; kaynak günlük 8 saat çalışırken 20
            # saatlik bölünemez bir işi planlamak sahada uygulanamaz.
            durum.sigmayanlar.append(_satir(durum, is_, ilk_gun, durum.gun, durum.gun))
            return durum.sigmayanlar[-1]
        if is_.yuk > durum.gun_kalan:
            # Bugüne sığmıyor ama tam bir güne sığıyor: gün başına taşınıyor.
            durum.gun += 1
            durum.gun_kalan = durum.kaynak.gunluk_kapasite

    bas = durum.gun
    kalan = is_.yuk
    while kalan > 0 and durum.gun < durum.ufuk_gun:
        kullanilan = min(kalan, durum.gun_kalan)
        kalan -= kullanilan
        durum.gun_kalan -= kullanilan
        if durum.gun_kalan <= 0:
            durum.gun += 1
            durum.gun_kalan = durum.kaynak.gunluk_kapasite

    satir = _satir(durum, is_, ilk_gun, bas, min(durum.gun, durum.ufuk_gun - 1))
    if kalan > 0:
        # Ufuk bitti, iş yarım kaldı. Plana koymak "yetişecek" demek olurdu.
        durum.sigmayanlar.append(satir)
    else:
        durum.satirlar.append(satir)
    return satir


def plan_kur(
    isler: list[Is],
    kaynaklar: list[Kaynak],
    olcut: str = VARSAYILAN_OLCUT,
    ufuk_gun: int = 14,
    baslangic: date | None = None,
) -> list[KaynakPlani]:
    """İşleri kaynaklara ve günlere dağıtır.

    Kaynaklar **paralel** çalışıyor: birindeki doluluk diğerini geciktirmiyor.

    Aynı girdi her koşuda **bit bit aynı** planı veriyor. Bu bir konfor
    değil zorunluluk: tekrarlanabilir olmayan bir plan, "sistem neden fikir
    değiştirdi" sorusunu cevapsız bırakır.
    """
    ilk_gun = baslangic or date.today()
    olcut_fn = olcut_al(olcut)

    durumlar = {k.kaynak_id: _KaynakDurumu(k, ufuk_gun) for k in kaynaklar}

    # ⚠️ Tanımlı olmayan bir kaynağa işaret eden iş **sessizce atlanmıyor**,
    # plan hiç kurulmuyor. Sebebi: o iş planda görünmezse "yapılacak bir şey
    # yok" izlenimi doğar ve eksiklik fark edilmez. Bu bir tanım hatası,
    # kapasite sonucu değil — `IsletmeProfili.dosyadan` ile aynı disiplin,
    # yazım hatası hata vermeli.
    sahipsiz = [i for i in isler if not [k for k in i.kaynak_adaylari() if k in durumlar]]
    if sahipsiz:
        bilinen = sorted(durumlar)
        raise ValueError(
            f"{len(sahipsiz)} işin kaynağı tanımlı değil: "
            f"{[i.is_id for i in sahipsiz[:5]]}. Tanımlı kaynaklar: {bilinen}"
        )

    for is_ in _sirala(isler, olcut_fn):
        adaylar = [kid for kid in is_.kaynak_adaylari() if kid in durumlar]
        # En boş kaynağa ata. Tek aday varsa seçim yok (üretim kipi).
        #
        # ⚠️ Eşitlik `kaynak_id` ile kırılıyor: iki kaynak aynı dolulukta
        # olduğunda sözlük sırasına bırakmak, aynı girdiye farklı plan
        # üretebilirdi.
        secilen = min(
            (durumlar[kid] for kid in adaylar),
            key=lambda d: (d.doluluk, d.kaynak.kaynak_id),
        )
        _yerlestir(secilen, is_, ilk_gun)

    return [
        KaynakPlani(
            kaynak_id=d.kaynak.kaynak_id,
            kaynak_adi=d.kaynak.ad,
            gunluk_kapasite=d.kaynak.gunluk_kapasite,
            kapasite_birimi=d.kaynak.kapasite_birimi,
            satirlar=tuple(d.satirlar),
            sigmayanlar=tuple(d.sigmayanlar),
            ufuk_gun=ufuk_gun,
        )
        for _, d in sorted(durumlar.items())
    ]


def plan_metni(planlar: list[KaynakPlani]) -> str:
    """Planı insan okunur tabloya çevirir.

    Ekran ve API sonradan gelir; önce çıktının doğru olduğu **gözle**
    görülebilmeli. Bu projede birkaç kez yaşandı: sayı doğruydu ama neyi
    ölçtüğü yanlıştı ve ancak basılınca fark edildi.
    """
    satirlar: list[str] = []
    for plan in planlar:
        satirlar.append(
            f"\n{plan.kaynak_adi} ({plan.kaynak_id}) — günde "
            f"{plan.gunluk_kapasite:.1f} {plan.kapasite_birimi}"
        )
        satirlar.append("-" * 72)
        if not plan.satirlar:
            satirlar.append("  (bu kaynağa planlanan iş yok)")
        for s in plan.satirlar:
            tarih = (
                s.baslangic.strftime("%d.%m")
                if s.gun_sayisi == 1
                else f"{s.baslangic:%d.%m}-{s.bitis:%d.%m}"
            )
            satirlar.append(
                f"  {tarih:<12}{s.ad[:36]:<38}{s.yuk:>7.1f} {plan.kapasite_birimi}"
                f"   öncelik {s.oncelik:.0f}"
            )
        if plan.sigmayanlar:
            satirlar.append(f"  ⚠️ ufka sığmayan {len(plan.sigmayanlar)} iş:")
            for s in plan.sigmayanlar:
                satirlar.append(f"     {s.ad[:36]:<38}{s.yuk:>7.1f} {plan.kapasite_birimi}")
    return "\n".join(satirlar)


__all__ = ["plan_kur", "plan_metni"]
