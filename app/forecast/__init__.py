"""Talep tahmini — geçmiş satıştan gelecek talebe.

Sahip: Kişi B · Faz 10

⚠️ Bu paket **karar vermez.** Yalnızca "önümüzdeki N gün ne kadar talep
beklenir" sorusunu cevaplar. Kararı `app/domain/**` verir ve buradaki
tahmini *çağırır* — içermez.

Ayrı bir paket olmasının sebebi mimari, kolaylık değil:

1. **Ölçülebilirlik.** Tahmin, sistemdeki en dürüst ölçülebilir parça.
   `app/adapters/geriye_donuk.py`'nin doğru biçimde işaret ettiği gibi,
   geçmiş veride bir *politikayı* ölçmek imkânsızdır — sistemin önerdiği
   sipariş o gün verilmedi, sonucu gözlenemez. Tahminde böyle bir sorun
   yok: tahmin et, gerçekleşeni oku, karşılaştır. Karşı-olgusal yok.

2. **Tek tüketici değil.** Üretim emri, kapasite ve malzeme ihtiyacı
   kararlarının üçü de aynı tahmini kullanacak. Birinin içine gömülseydi
   diğer ikisi ya kopyalar ya da farklı bir tahmine bakardı.

3. **İki kişilik çalışma.** Alanlar (`app/domain/**`) Kişi A'nın sahası.
   Tahmin servis olarak ayrılınca iki taraf da tek bir sözleşmeye
   (`TalepTahmini`) bakarak birbirini beklemeden çalışabiliyor.
"""

from app.forecast.contracts import TalepTahmini

__all__ = ["TalepTahmini"]
