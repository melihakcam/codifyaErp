"""Üretim planlama alanı — Faz 10.

Sahip: Kişi A · Adım 3-5

⚠️ Bu paket talep tahmini **üretmiyor**, `app/forecast`'i çağırıyor. Ayrım
mimari: tahmin ölçülebilir bir model işi, üretim emri bir karar işi. Üç
karar türü de (emir, kapasite, malzeme ihtiyacı) aynı tahmini kullanacak;
birinin içine gömülseydi diğer ikisi ya kopyalar ya farklı bir tahmine
bakardı.
"""
