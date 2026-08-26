"""Plan belgesi — tek komutun okunabilir çıktısı.

Sahip: Kişi B · Faz 13 B13.2

## ⚠️ Bu belge LLM'siz üretiliyor

Faz 8'in dersi: bir tip `_TIPE_GORE_ALANLAR`'a girmediğinde model **hiç
çağrılmıyor**, metin sessizce şablona düşüyor ve kimse fark etmiyor. Aynı
sessizlik burada olmasın diye sıra tersine çevrildi: belge **önce** kodla
üretilir ve testi vardır; model sonradan yalnızca özet cümlesini yazar.

Yani modelin çalışmadığı bir günde çıktı bozulmuyor, yalnızca giriş
paragrafı sadeleşiyor.

## Altı bölüm ve neden bu altısı

| bölüm | cevapladığı soru |
|---|---|
| 1 · Gelecek | işler nereden geldi, hangi pencereye bakıyoruz |
| 2 · Ne yapılacak | kaç iş yerleşti, kaçı dışarıda kaldı |
| 3 · Takvim | hangi iş, hangi kaynakta, hangi gün |
| 4 · Gerekçeler | **neden o kaynak** — planı savunulabilir yapan bölüm |
| 5 · Seçenekler | üç plan yan yana, farkı parayla |
| 6 · ⚠️ Dikkat | kapasite aşımı, sığmayan iş, geçmişi yetersiz kalem |

⚠️ **Hiçbir bölüm "iyi haber yoksa" gizlenmiyor.** Sığmayan iş yoksa bölüm
"yok" der; gerekçe henüz üretilmiyorsa onu söyler. Boş bölümü atlamak,
planı olduğundan iyi gösterir.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.planlama.contracts import PlanSatiri
from app.planlama.karsilastir import karne_metni
from app.planlama.tam_plan import TamPlan

# Gerekçe bölümünde en fazla kaç satır gösterilecek. ⚠️ Tamamı çıktıda
# olsaydı 200 işlik bir plan okunmaz hâle gelirdi; sayı bir kısaltma
# kararı, bir veri kaybı değil — tamamı `TamPlan` içinde duruyor.
GEREKCE_SATIR_SINIRI = 15

BELIRLEYICI_METNI = {
    "tek_aday": "başka uygun kaynak yoktu",
    "uygunluk": "diğer kaynaklar bu işe uygun değildi",
    "kapasite": "uygun kaynaklar arasında en boş olanı buydu",
    "aciliyet": "işin aciliyeti sırayı belirledi",
}


@dataclass(frozen=True)
class Belge:
    """Başlıklı bölümler. Metin tek parça değil ki test bölüm bölüm bakabilsin."""

    baslik: str
    bolumler: tuple[tuple[str, str], ...]

    def metin(self) -> str:
        parcalar = [self.baslik, "=" * len(self.baslik)]
        for ad, govde in self.bolumler:
            parcalar += ["", ad, "-" * len(ad), govde]
        return "\n".join(parcalar)


def _tarih(satir: PlanSatiri) -> str:
    if satir.gun_sayisi == 1:
        return f"{satir.baslangic:%d.%m}"
    return f"{satir.baslangic:%d.%m}-{satir.bitis:%d.%m}"


def _gelecek(tam: TamPlan) -> str:
    kaynak_metni = {
        "elle": "işler alan tanımında elle yazılı",
        "tahmin": "işler geçmişten tahminle türetildi",
    }.get(tam.isler_kaynagi, f"işler başka bir alandan devralındı ({tam.isler_kaynagi})")

    return "\n".join(
        [
            f"  Alan            : {tam.alan_adi} ({tam.alan})",
            f"  Pencere         : {tam.baslangic:%d.%m.%Y} tarihinden itibaren {tam.ufuk_gun} gün",
            f"  İşlerin kaynağı : {kaynak_metni}",
            f"  Planlanan iş    : {tam.is_sayisi}",
            f"  Kaynak sayısı   : {len(tam.planlar)}",
        ]
    )


def _ne_yapilacak(tam: TamPlan) -> str:
    yerlesen = len(tam.satirlar)
    sigmayan = len(tam.sigmayanlar)
    toplam_yuk = sum(s.yuk for s in tam.satirlar)
    birim = tam.planlar[0].kapasite_birimi if tam.planlar else ""

    satirlar = [
        f"  Yerleşen iş     : {yerlesen}",
        f"  Ufka sığmayan   : {sigmayan}",
        f"  Toplam yük      : {toplam_yuk:,.1f} {birim}",
        f"  Seçilen ölçüt   : {tam.olcut}",
    ]
    if sigmayan:
        # ⚠️ Sığmayan iş "yapılmayacak" demek değil, "bu pencereye
        # yetişmiyor" demek. İkisini karıştırmak planı yanlış okutur.
        satirlar.append(f"  ⚠️ {sigmayan} iş bu pencereye yetişmiyor — bkz. Dikkat bölümü.")
    return "\n".join(satirlar)


def _takvim(tam: TamPlan) -> str:
    if not tam.planlar:
        return "  (kaynak yok)"

    satirlar: list[str] = []
    for plan in tam.planlar:
        satirlar.append(
            f"  {plan.kaynak_adi} ({plan.kaynak_id}) — günde "
            f"{plan.gunluk_kapasite:.1f} {plan.kapasite_birimi} · "
            f"doluluk %{plan.doluluk * 100:.0f}"
        )
        if not plan.satirlar:
            satirlar.append("     (bu kaynağa planlanan iş yok)")
        for s in plan.satirlar:
            satirlar.append(
                f"     {_tarih(s):<12}{s.ad[:34]:<36}{s.yuk:>7.1f} {plan.kapasite_birimi}"
            )
        satirlar.append("")
    return "\n".join(satirlar).rstrip()


def _gerekceler(tam: TamPlan) -> str:
    """⚠️ Gerekçe yoksa bölüm atlanmıyor, eksik olduğu **yazılıyor**."""
    gerekceli = [s for s in tam.satirlar if s.gerekce is not None]
    if not gerekceli:
        return (
            "  (bu planda gerekçe verisi yok — yerleştirme henüz gerekçe üretmiyor)\n"
            "  ⚠️ Plan geçerli, ama 'neden bu kaynak' sorusu bu çıktıdan cevaplanamaz."
        )

    satirlar = []
    for s in gerekceli[:GEREKCE_SATIR_SINIRI]:
        g = s.gerekce
        assert g is not None
        neden = BELIRLEYICI_METNI.get(g.belirleyici, g.belirleyici)
        satirlar.append(f"  {s.ad[:34]:<36}→ {g.secilen_kaynak}: {neden}")
        for kaynak_id, elenme in sorted(g.elenme_nedenleri.items()):
            satirlar.append(f"       · {kaynak_id} olmadı: {elenme}")

    kalan = len(gerekceli) - GEREKCE_SATIR_SINIRI
    if kalan > 0:
        satirlar.append(f"  … {kalan} satır daha (tamamı plan verisinde)")
    return "\n".join(satirlar)


def _dikkat(tam: TamPlan) -> str:
    if not tam.uyarilar:
        return "  (dikkat çeken bir durum yok)"
    return "\n".join(f"  ⚠️ {u}" for u in tam.uyarilar)


def plan_belgesi(tam: TamPlan) -> Belge:
    """`TamPlan` → altı bölümlük belge. **Model çağrılmıyor.**"""
    return Belge(
        baslik=f"{tam.alan_adi.upper()} PLANI · {tam.baslangic:%d.%m.%Y} · {tam.ufuk_gun} gün",
        bolumler=(
            ("1 · GELECEK", _gelecek(tam)),
            ("2 · NE YAPILACAK", _ne_yapilacak(tam)),
            ("3 · TAKVİM", _takvim(tam)),
            ("4 · GEREKÇELER", _gerekceler(tam)),
            ("5 · PLAN SEÇENEKLERİ", karne_metni(tam.karsilastirma)),
            ("6 · DİKKAT", _dikkat(tam)),
        ),
    )


def belge_metni(tam: TamPlan) -> str:
    """Kısayol: belgenin düz metni."""
    return plan_belgesi(tam).metin()


__all__ = ["BELIRLEYICI_METNI", "GEREKCE_SATIR_SINIRI", "Belge", "belge_metni", "plan_belgesi"]
