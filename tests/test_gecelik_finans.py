"""Gecelik taramanın iki alanı birden kapsaması (Faz 6.6).

Kullanıcı sabah **tek bir liste** görmek istiyor: "bugün neye bakmam
lazım?" sorusunun cevabı alan başına bölünmemeli. Bu testler hem
birleştirmenin çalıştığını hem de finans tarafındaki bir sorunun taramanın
tamamını düşürmediğini doğruluyor.
"""

from __future__ import annotations

from unittest.mock import patch

from app.contracts import Alan, KararTipi
from app.jobs.nightly import _finans_kararlari, _icgoru_basligi


def _finans_karari(tip: KararTipi):
    from app.domain.finance.decide import ozellikten_karar_uret
    from tests.test_finans_kurallari import oz

    senaryolar = {
        KararTipi.FINANS_TAHSILAT_TAKIBI: oz(en_eski_gecikme_gun=62),
        KararTipi.FINANS_KARSILIK_AYIR: oz(en_eski_gecikme_gun=400),
        KararTipi.FINANS_KREDI_LIMITI_DUSUR: oz(
            en_eski_gecikme_gun=62, tahsilat_orani=0.30, odeme_gecikmesi_std=45.0
        ),
        KararTipi.FINANS_AKSIYON_YOK: oz(en_eski_gecikme_gun=5),
    }
    return ozellikten_karar_uret(senaryolar[tip])


# --- Başlık üretimi -----------------------------------------------------------


def test_finans_basliklari_patlamiyor():
    """⭐ Faz 6'da bulunan hata.

    `_icgoru_basligi` doğrudan `o.sku_adi` okuyordu. Finans kararı taramaya
    girdiği anda `AttributeError` verir ve **gecelik işin tamamı** düşerdi —
    stok kararları da dâhil.
    """
    for tip in (
        KararTipi.FINANS_TAHSILAT_TAKIBI,
        KararTipi.FINANS_KARSILIK_AYIR,
        KararTipi.FINANS_KREDI_LIMITI_DUSUR,
        KararTipi.FINANS_AKSIYON_YOK,
    ):
        baslik = _icgoru_basligi(_finans_karari(tip), None)

        assert baslik
        assert "Yılmaz İnşaat" in baslik, f"{tip.value}: müşteri adı başlıkta yok"


def test_stok_basliklari_bozulmadi():
    from app.domain.stock.decide import decide_stub

    baslik = _icgoru_basligi(decide_stub(), None)

    assert baslik
    assert ":" in baslik


def test_gorunen_ad_iki_alanda_da_var():
    from app.domain.stock.decide import decide_stub

    stok = decide_stub().ozellikler
    finans = _finans_karari(KararTipi.FINANS_TAHSILAT_TAKIBI).ozellikler

    assert stok.gorunen_ad == stok.sku_adi
    assert finans.gorunen_ad == finans.musteri_adi


# --- Dayanıklılık -------------------------------------------------------------


def test_finans_patlarsa_tarama_devam_ediyor():
    """⚠️ Finans tarafındaki bir sorun stok kararlarını engellememeli.

    Gecelik iş, kullanıcının sabah gördüğü tek kaynak. Bir alanın hatası
    diğerinin çıktısını da yok ederse sistem sessizce körleşir.
    """
    with patch("app.domain.finance.decide._demo_ozellikleri", side_effect=RuntimeError("patladı")):
        sonuc = _finans_kararlari()

    assert sonuc == [], "hata durumunda boş liste dönmeli, istisna fırlatmamalı"


def test_finans_kararlari_uretiliyor():
    kararlar = _finans_kararlari()

    assert kararlar
    assert all(k.alan is Alan.FINANS for k in kararlar)
    assert all(k.tip.alan == "finans" for k in kararlar)
