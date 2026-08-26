"""Guard'ın dil tarafındaki açığı — canlı onay kuyruğunda bulundu.

Guard yalnızca sayıları denetliyordu. Gerekçesi olan 100 kararın 14'ünde
(%14) metne Çince/Japonca karakter sızmıştı ve **hepsi
`guard_sonucu="gecti"` damgasıyla geçmişti**:

    "... ürününün 1.090 gün hareket göstermedikten sonra tafiyetine karar
     verildi ve bu tafiyetine契合したのは24 adet矣。"

Guard'ın geçirmesi kendi kuralına göre tutarlıydı — içindeki `24` meşru bir
sayı. Hata mantıkta değil kapsamdaydı: dil hiç denetlenmiyordu.
"""

from __future__ import annotations

import pytest

from app.llm.guard import (
    ASGARI_KELIME_SAYISI,
    latin_disi_harfler,
    metni_dogrula,
)

# Kuyruktan alınmış gerçek bozuk metin.
GERCEK_BOZUK = (
    "İnşaat Demiri 10mm - Kardemir ürününün 1.090 gün hareket göstermedikten "
    "sonra tafiyetine karar verildi ve bu tafiyetine契合したのは24 adet矣。"
)

# Kuyruktan alınmış gerçek SAĞLAM metin — reddedilmemeli.
GERCEK_SAGLAM = (
    "Ürün 1.090 gündür hiç hareket görmedi ve elde kalan 24 adet, birim maliyeti "
    "24.126,72 TL üzerinden 579.041,18 TL'lik sermayeyi bağlıyor. Talep geri "
    "dönmediği sürece bu tutar atıl kalacağından tasfiye değerlendirilmesi öneriliyor."
)


def test_gercek_bozuk_metin_reddediliyor():
    sonuc = metni_dogrula(GERCEK_BOZUK)

    assert not sonuc.gecti
    assert any("latin disi" in s for s in sonuc.sorunlar)


def test_gercek_saglam_metin_geciyor():
    """Yanlış alarm, bozuk metni geçirmekten daha pahalı olabilir.

    Meşru bir gerekçe reddedilirse şablona düşer ve kullanıcı daha kötü
    (ama doğru) bir metin görür. Canlı kuyruktaki 86 sağlam gerekçenin
    hiçbiri reddedilmedi — bu test o güvenceyi sabitliyor.
    """
    assert metni_dogrula(GERCEK_SAGLAM).gecti


@pytest.mark.parametrize(
    "metin",
    [
        "Ürün 24 gündür hareketsiz, стоимость yüksek.",  # Kiril
        "Ürün 24 gündür hareketsiz, المخزون fazla.",  # Arap
        "Ürün 24 gündür hareketsiz, απόθεμα fazla.",  # Yunan
    ],
)
def test_diger_yazi_sistemleri_de_yakalaniyor(metin: str):
    """CJK'ya özel bir liste değil, Latin dışı her yazı sistemi."""
    assert not metni_dogrula(metin).gecti


def test_turkce_harfler_latin_sayiliyor():
    """ı ğ ş ç ö ü ve büyükleri Unicode'da LATIN — reddedilmemeliler."""
    assert latin_disi_harfler("ıİğĞşŞçÇöÖüÜ") == []


def test_noktalama_ve_simgeler_yanlis_alarm_uretmiyor():
    """Kontrol yalnızca HARFLERE bakıyor; ₺ % — “ ” gibi işaretlere değil."""
    metin = "Bağlı sermaye 579.041,18 ₺ (%50 iskonto) — “tasfiye” önerilir; oran ±%2."

    assert metni_dogrula(metin).gecti


def test_gerekce_yerine_sadece_urun_adi_reddediliyor():
    """Kuyruktaki ikinci hata deseni: gerekçe yerine yalnızca ürün adı.

    Sayı içermediği için sayısal guard'dan sorunsuz geçiyordu.
    """
    sonuc = metni_dogrula(
        "İnşaat Demiri 10mm - Kardemir",
        maskelenecek=["İnşaat Demiri 10mm", "Kardemir"],
    )

    assert not sonuc.gecti
    assert any("gerekce bos" in s for s in sonuc.sorunlar)


def test_maskeleme_sonrasi_dolu_kalan_metin_geciyor():
    """Uzunluk kuralı ürün adı geçen meşru gerekçeleri kesmemeli."""
    sonuc = metni_dogrula(
        GERCEK_SAGLAM + " İnşaat Demiri 10mm - Kardemir",
        maskelenecek=["İnşaat Demiri 10mm", "Kardemir"],
    )

    assert sonuc.gecti


def test_kisa_ama_mesru_gerekce_geciyor():
    """⚠️ Bu, ilk denemede kuralı yanlış kurduğum yer.

    Eşik önce karakter sayısıydı (15) ve `"Stok yeterli."` gibi kısa ama
    bilgi taşıyan bir gerekçeyi kesiyordu — `test_guard.py`'deki mevcut bir
    test yakaladı. Kelime sayımı ayrımı keskin yapıyor: burada 2 kelime var,
    yalnızca ürün adından ibaret metinde 0.
    """
    assert metni_dogrula("Stok yeterli.").gecti
    assert ASGARI_KELIME_SAYISI == 2
