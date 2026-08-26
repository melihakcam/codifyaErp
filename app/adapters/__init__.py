"""Dış veri kaynaklarını karar motorunun sözleşmesine çeviren adaptörler.

Kural: adaptörler **hesap yapmaz**, yalnızca biçim çevirir. Talep
istatistikleri, ABC/XYZ, ROP gibi her şey `app/domain/`'de kalır — aksi hâlde
aynı formül iki yerde yaşar ve zamanla ayrışır.
"""
