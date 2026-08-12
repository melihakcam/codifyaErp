"""Genel planlama motoru — alandan bağımsız kaynak/iş yerleştirme.

Sahip: ortak · Faz 11

## Neden var

Projenin amacı alan-özel çözümler değil, **genel bir karar mekanizması**.
Kural motoru bunu bir kez kanıtladı: aynı iskelet (özellik → kural → aday →
politika) stok, finans ve üretime yeniden yazılmadan taşındı.

Planlama tarafında aynı sınav henüz verilmemişti. Üretim çizelgesi
`app/domain/production/cizelge.py` içinde yazılmıştı ve "hat", "emir",
"parti" kelimeleriyle konuşuyordu — yani ikinci bir alan (nakliye, vardiya)
geldiğinde kopyalanması gerekirdi.

Bu paket o mantığı alan kelimelerinden arındırıyor:

    hat / arac / kisi / makine        ->  Kaynak
    uretim emri / sevkiyat / vardiya  ->  Is
    saat / km / adam-saat             ->  kapasite birimi

⚠️ **Genellik iddiası ancak ikinci alanla kanıtlanır.** Tek kullanıcısı olan
bir "genel" motor, genel değil sadece soyutlanmış demektir. O yüzden bu
paket üretimle birlikte **nakliye** için de koşuyor ve ikisi de aynı
fonksiyonu çağırıyor.

## Ne yapmıyor

Bu bir **optimize edici değil**. Açgözlü yerleştirme yapıyor: en acil iş
önce, kaynak dolunca ertesi güne. Hazırlık sürelerini gruplamıyor, teslim
tarihine göre geriye planlamıyor, iş sırasını iyileştirmiyor.

Gerçek bir çözücü (OR-Tools, CP-SAT) bunları yapar. Oraya geçilecekse
`yerlestirme.py` değişir, sözleşme değişmez — alanlar bu ayrımın arkasında
duruyor.
"""

from app.planlama.contracts import Is, Kaynak, KaynakPlani, PlanSatiri
from app.planlama.yerlestirme import plan_kur, plan_metni

__all__ = ["Is", "Kaynak", "KaynakPlani", "PlanSatiri", "plan_kur", "plan_metni"]
