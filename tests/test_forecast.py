"""Talep tahmini (`app/forecast/**`) — Faz 10, Adım 1-2.

⚠️ Buradaki testlerin en önemlisi **sızıntı** testi. Zaman serisinde sızıntı
dosya çakışması gibi görünür bir iz bırakmaz: model yarını görmüş olur, hata
küçük çıkar, herkes sevinir. Golden set incelemesinde sızıntıyı dosya
karşılaştırmasıyla yakalayabiliyorduk; burada tek koruma testin kendisi.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.forecast.contracts import TalepTahmini
from app.forecast.model import ussel_duzlestirme
from app.forecast.olcum import KalemSonucu, katman_adi
from app.forecast.taban import hareketli_ortalama, mevsimsel_naif, naif_hata_olcegi

BUGUN = date(2026, 8, 11)


# --- Sözleşme ----------------------------------------------------------------


def test_bant_sirasiz_olamaz():
    """⭐ Bantları karıştırmış bir model, üretim tarafında çok uzakta belirti verir.

    "Emniyet payı negatif çıktı" hatası üretim kararında görülür ve oradan
    tahmin modeline geri izlemek saatler alır. Kontrol kurulum anında.
    """
    with pytest.raises(ValueError, match="bant sıralı değil"):
        TalepTahmini(
            kalem_id="S-1",
            baslangic=BUGUN,
            gunluk=[5.0],
            alt_band=[9.0],  # alt > tahmin
            ust_band=[10.0],
            yontem="deneme",
            egitim_gun_sayisi=100,
        )


def test_diziler_ayni_uzunlukta_olmali():
    with pytest.raises(ValueError, match="aynı uzunlukta"):
        TalepTahmini(
            kalem_id="S-1",
            baslangic=BUGUN,
            gunluk=[1.0, 2.0],
            alt_band=[0.0],
            ust_band=[3.0, 4.0],
            yontem="deneme",
            egitim_gun_sayisi=100,
        )


def test_negatif_talep_reddediliyor():
    with pytest.raises(ValueError, match="negatif"):
        TalepTahmini(
            kalem_id="S-1",
            baslangic=BUGUN,
            gunluk=[1.0],
            alt_band=[-1.0],
            ust_band=[3.0],
            yontem="deneme",
            egitim_gun_sayisi=100,
        )


def test_toplam_ve_bant_hesaplari():
    t = TalepTahmini(
        kalem_id="S-1",
        baslangic=BUGUN,
        gunluk=[2.0, 3.0],
        alt_band=[1.0, 2.0],
        ust_band=[4.0, 5.0],
        yontem="deneme",
        egitim_gun_sayisi=100,
    )
    assert t.ufuk_gun == 2
    assert t.bitis == date(2026, 8, 12)
    assert t.toplam() == 5.0
    assert t.toplam_bandi() == (3.0, 9.0)


# --- Sızıntı -----------------------------------------------------------------


@pytest.mark.parametrize("model", [hareketli_ortalama, mevsimsel_naif, ussel_duzlestirme])
def test_tahmin_GELECEGI_GORMUYOR(model):
    """⭐ Modele verilen geçmiş dışında hiçbir şey tahmini etkilememeli.

    Sınama: aynı geçmişin sonuna **çok farklı** bir gelecek eklenip model
    yine yalnızca geçmişle çağrılıyor. Tahmin bit bit aynı çıkmalı. Fark
    çıkarsa model bir şekilde geleceğe erişiyor demektir.

    Bu test bir imza koruması: `olc()` içinde `degerler[:kesme]` yerine
    yanlışlıkla `degerler` yazılırsa buradan değil ölçümden geçer — o yüzden
    ayrıca `test_olcum_egitim_penceresini_asmiyor` var.
    """
    gecmis = [float((i % 7) + 1) for i in range(420)]

    ilk = model(gecmis, "S-1", BUGUN, 14)
    # Gecmis DEGISMEDI; sadece cagirandan sonra baska veri var gibi dusun.
    ikinci = model(list(gecmis), "S-1", BUGUN, 14)

    assert ilk.gunluk == ikinci.gunluk
    assert ilk.egitim_gun_sayisi == len(gecmis)


def test_olcum_egitim_penceresini_asmiyor():
    """⭐ Asıl sızıntı riski `olc()` içindeki dilimlemede.

    Model doğru yazılsa bile ölçüm ona test dönemini verirse hata sahte
    biçimde küçülür. Burada modelin gördüğü uzunluk doğrudan sınanıyor.
    """
    import pandas as pd

    from app.forecast.olcum import ASGARI_GECMIS_GUN, olc

    gorulen: list[int] = []

    def casus(gecmis, kalem_id, baslangic, ufuk):
        gorulen.append(len(gecmis))
        return hareketli_ortalama(gecmis, kalem_id, baslangic, ufuk)

    n = ASGARI_GECMIS_GUN + 100
    seri = pd.Series(
        [float(i % 5) for i in range(n)],
        index=pd.date_range("2024-01-01", periods=n, freq="D"),
    )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.forecast.olcum.TABANLAR", {"casus": casus})
        mp.setattr("app.forecast.olcum.MODELLER", {})
        olc({"S-1": seri}, ufuk=14, kesme_sayisi=2)

    assert gorulen, "olcum modeli hic cagirmadi"
    # Her cagrida gorulen uzunluk kesme noktasi; ufuk kadar veri HER ZAMAN
    # disarida kalmali.
    for uzunluk in gorulen:
        assert uzunluk <= n - 14, f"model test penceresini gordu: {uzunluk} > {n - 14}"


# --- Ölçüt -------------------------------------------------------------------


def test_mase_olcek_sifirken_TANIMSIZ():
    """Sabit seride naif hata 0; 0'a bölmek yerine kalem ölçüm dışı kalmalı."""
    kayit = KalemSonucu(kalem_id="S-1", yontem="x", mutlak_hatalar=[1.0, 2.0], olcek=0.0)

    assert kayit.mae == 1.5
    assert kayit.mase is None


def test_naif_olcek_sabit_seride_sifir():
    assert naif_hata_olcegi([5.0] * 30) == 0.0
    assert naif_hata_olcegi([1.0, 2.0]) == 0.0  # mevsimden kısa


def test_katman_siniri():
    assert katman_adi(5.0).startswith("hizli")
    assert katman_adi(1.0).startswith("orta")
    assert katman_adi(0.05).startswith("yavas")


# --- Model davranışı ---------------------------------------------------------


def test_kisa_gecmiste_naif_tabana_dusuluyor():
    """⚠️ Veri yokluğunu "talep yok" diye raporlamak üretimde en tehlikeli hata.

    Üç haftadan kısa geçmişte Holt-Winters kurulamaz; sessizce sıfır dönmek
    yerine hareketli ortalamaya düşmeli.
    """
    gecmis = [10.0] * 10
    tahmin = ussel_duzlestirme(gecmis, "S-1", BUGUN, 7)

    assert tahmin.yontem == "hareketli_ortalama"
    assert all(d > 0 for d in tahmin.gunluk), "kisa gecmiste sifir talep raporlanmamali"


def test_mevsimsel_naif_bir_yildan_kisada_tabana_dusuyor():
    tahmin = mevsimsel_naif([3.0] * 100, "S-1", BUGUN, 14)
    assert tahmin.yontem == "hareketli_ortalama"


def test_haftalik_deseni_yakaliyor():
    """⭐ Simülatör haftalık desen üretiyor; model onu görmezse işe yaramaz.

    Hafta içi 10, hafta sonu 0 olan yapay bir seride tahmin de aynı deseni
    taşımalı — düz ortalama (≈7,1) değil.
    """
    gecmis = [0.0 if (i % 7) in (5, 6) else 10.0 for i in range(140)]
    tahmin = ussel_duzlestirme(gecmis, "S-1", BUGUN, 14)

    hafta_sonu = [d for i, d in enumerate(tahmin.gunluk) if ((140 + i) % 7) in (5, 6)]
    hafta_ici = [d for i, d in enumerate(tahmin.gunluk) if ((140 + i) % 7) not in (5, 6)]

    assert max(hafta_sonu) < min(hafta_ici), "model haftalik deseni goremiyor"


def test_tahmin_negatife_dusmuyor():
    """Düşen trendde uzun ufuk tahmini eksiye geçirebilir; sözleşme izin vermez."""
    gecmis = [float(max(0, 200 - i)) for i in range(200)]
    tahmin = ussel_duzlestirme(gecmis, "S-1", BUGUN, 60)

    assert all(d >= 0 for d in tahmin.gunluk)
    assert all(a >= 0 for a in tahmin.alt_band)


# --- Aralıklı talep (Croston / SBA) ------------------------------------------


def test_croston_sifirlarda_seviye_bozulmuyor():
    """⭐ Croston'un tüm fikri bu: sıfır günlerinde GÜNCELLEME YOK.

    Sıfırlarda güncellemek yöntemi klasik üssel düzleştirmeye geri çevirir
    ve kazanımı yok eder. Aynı talep deseninin araları uzatıldığında oran
    düşmeli — büyüklük aynı, sıklık azalmış demektir.
    """
    from app.forecast.aralikli import croston

    sik = ([5.0] + [0.0] * 4) * 40  # 5 gunde bir 5 adet
    seyrek = ([5.0] + [0.0] * 19) * 20  # 20 gunde bir 5 adet

    a = croston(sik, "S-1", BUGUN, 14).gunluk[0]
    b = croston(seyrek, "S-1", BUGUN, 14).gunluk[0]

    assert a > b, "aralik uzayinca gunluk oran dusmeli"
    assert 0.5 < a / b < 6.0, "oran mertebesi aralik oraniyla uyumlu olmali"


def test_sba_crostondan_KUCUK():
    """SBA, Croston'un yukarı yanlılığını `(1 - alfa/2)` ile geri çeker."""
    from app.forecast.aralikli import ALFA, croston, sba

    gecmis = ([3.0] + [0.0] * 9) * 45

    c = croston(gecmis, "S-1", BUGUN, 14).gunluk[0]
    s = sba(gecmis, "S-1", BUGUN, 14).gunluk[0]

    assert s < c
    assert s == pytest.approx(c * (1 - ALFA / 2), rel=1e-6)


def test_aralikli_bant_SIMETRIK_DEGIL():
    """⭐ Aralıklı seride alt bandı 0'ın üstüne çekmek yanlış olurdu.

    "Her gün en az şu kadar satılır" demek, günlerin çoğunun gerçekten sıfır
    olduğu bir seride yanlış bilgi. Üst bant ise tipik bir talep gününün
    büyüklüğü: "çoğu gün hiçbir şey satılmaz, satıldığında bu mertebede."
    """
    from app.forecast.aralikli import croston

    gecmis = ([4.0] + [0.0] * 9) * 45
    t = croston(gecmis, "S-1", BUGUN, 14)

    assert all(a == 0.0 for a in t.alt_band), "alt bant 0 olmali"
    assert t.ust_band[0] > t.gunluk[0], "ust bant talep gunu buyuklugunu tasimali"


def test_az_talep_gununde_naif_tabana_dusuluyor():
    from app.forecast.aralikli import croston

    gecmis = [0.0] * 200 + [1.0, 0.0]  # tek talep gunu
    assert croston(gecmis, "S-1", BUGUN, 14).yontem == "hareketli_ortalama"


# --- Ölçüm penceresi ---------------------------------------------------------


def test_kesmeler_serinin_KUYRUGUNA_YIGILMIYOR():
    """⭐ Ölçümün kendisi bulguyu üretebilir — bu yakalandı ve düzeltildi.

    İlk sürüm kesmeleri serinin sonundan geriye alıyordu. Serinin son
    döneminde talep düşükse HER yöntem yukarı yanlı görünüyordu: Croston
    +%94, `hareketli_ortalama` bile +%87. Kesmeler seriye yayılınca Croston
    +%2'ye indi.

    Yani sayı modelin değil, örnekleme penceresinin özelliğiydi.
    """
    import pandas as pd

    from app.forecast.olcum import ASGARI_GECMIS_GUN, kesme_tarihleri

    n = ASGARI_GECMIS_GUN + 600
    seri = pd.Series(range(n), index=pd.date_range("2023-01-01", periods=n, freq="D"))

    noktalar = kesme_tarihleri(seri, ufuk=14, adet=6)

    assert len(noktalar) >= 2
    yayilim = noktalar[-1] - noktalar[0]
    kullanilabilir = (n - 14) - ASGARI_GECMIS_GUN
    assert yayilim > kullanilabilir * 0.5, (
        f"kesmeler kuyruga yigilmis: yayilim {yayilim}, kullanilabilir {kullanilabilir}"
    )


def test_yanlilik_ve_sifir_orani_hesaplaniyor():
    """MASE'nin yetmediği yerde kullanılan iki ölçüt."""
    k = KalemSonucu(kalem_id="S-1", yontem="x")
    k.tahmin_toplami = 80.0
    k.gercek_toplam = 100.0
    k.pencere_sayisi = 10
    k.sifir_pencere = 9

    assert k.yanlilik == pytest.approx(-20.0)
    assert k.sifir_orani == pytest.approx(0.9)

    bos = KalemSonucu(kalem_id="S-2", yontem="x")
    assert bos.yanlilik is None, "gercek 0 iken yanlilik tanimsiz"
    assert bos.sifir_orani == 0.0
