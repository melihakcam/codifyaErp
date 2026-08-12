"""Üretim planlama (Faz 10, Adım 3) — fabrika dünyası + üretim emri kararı.

⚠️ Buradaki en önemli testler **sözleşme** ve **dışlama** testleri. Üretim
kararı yeni bir alan ve alan-bağımsız katmanlar (guard, politika, gerekçe)
onu ilk kez görüyor; Faz 6'da finans eklenirken tam bu noktada sessiz
kırılmalar çıkmıştı.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from app.contracts import (
    ABCSinifi,
    Alan,
    KararTipi,
    UretimOzellikleri,
    XYZSinifi,
)
from app.core.isletme_profili import UretimProfili
from app.domain.production.decide import ozellikten_kararlar_uret
from app.domain.production.rules import (
    emir_ekonomik_mi,
    emir_miktari_hesapla,
    hat_yuku_saat,
    ihtiyac_hesapla,
)
from simulator.uretim import (
    uretilen_mi,
    uretim_ana_verisi_uret,
    varsayilan_fabrika,
)

BUGUN = dt.date(2026, 8, 11)


def ozellik_kur(**degisiklikler) -> UretimOzellikleri:
    """Makul bir üretilen kalem; testler yalnızca ilgilendikleri alanı ezer."""
    varsayilan = {
        "kalem_id": "S-00001",
        "kalem_adi": "Kırmızı Tuğla 19x9x5",
        "kategori": "Tuğla",
        "eldeki_stok": 100,
        "rezerve_stok": 0,
        "acik_emir_miktari": 0,
        "tahmin_toplam": 140.0,
        "tahmin_alt_band": 100.0,
        "tahmin_ust_band": 200.0,
        "tahmin_yontemi": "croston",
        "tahmin_ufuk_gun": 14,
        "veri_gun_sayisi": 400,
        "hat_id": "H-01",
        "hat_adi": "Kesim Hattı",
        "parti_buyuklugu": 100,
        "asgari_parti": 100,
        "hazirlik_suresi_saat": 1.5,
        "birim_islem_suresi_saat": 0.005,
        "uretim_suresi_gun": 5.0,
        "hat_gunluk_kapasite_saat": 16.0,
        "abc_sinifi": ABCSinifi.A,
        "xyz_sinifi": XYZSinifi.X,
        "hedef_servis_seviyesi": 0.95,
        "birim_maliyet_tl": 12.0,
        "satis_fiyati_tl": 18.0,
        "olcum_tarihi": BUGUN,
    }
    return UretimOzellikleri(**{**varsayilan, **degisiklikler})


# --- Sözleşme ----------------------------------------------------------------


def test_net_pozisyon_ACIK_EMRI_sayiyor():
    """⭐ Açık emri saymamak, stoktaki "yoldaki stoğu unutma" hatasının ikizi.

    Sayılmazsa sistem her koşuda aynı kalem için yeniden emir önerir ve
    fabrika aynı malı üst üste üretir.
    """
    o = ozellik_kur(eldeki_stok=100, rezerve_stok=20, acik_emir_miktari=50)
    assert o.kullanilabilir_stok == 80
    assert o.net_pozisyon == 130


def test_veri_yetersizken_OTO_UYGULAMA_ENGELI_var():
    """⚠️ Stokta engel tedarikçi onayı, finansta kredi onayı; üretimde karşı
    taraf yok — engel tahminin dayanağından gelmek zorunda."""
    assert ozellik_kur(veri_gun_sayisi=400).oto_uygulama_engeli() is None
    assert ozellik_kur(veri_gun_sayisi=30).oto_uygulama_engeli() == "TAHMIN_GECMISI_YETERSIZ"


def test_maskelenecek_alanlar_HAT_ADINI_da_iceriyor():
    """⭐ Guard maskelemesi eksikse geçerli her gerekçe reddedilir.

    "Kesim Hattı" rakam içermiyor ama "H-01" içeriyor; kalem adındaki
    19x9x5 de ölçü, veri değil. Faz 6'da finans eklenirken tam bu tür bir
    eksiklik gerekçeleri sessizce şablona düşürmüştü.
    """
    alanlar = ozellik_kur().maskelenecek_alanlar()
    assert "Kesim Hattı" in alanlar
    assert "H-01" in alanlar
    assert "Kırmızı Tuğla 19x9x5" in alanlar


def test_hesaplanan_sayilar_IZINLI_KUMEYE_giriyor():
    """`model_dump()`'ta görünmeyen property'ler guard'a bildirilmeli."""
    kararlar = ozellikten_kararlar_uret(ozellik_kur())
    izinli = kararlar[0].izinli_sayilar()

    assert 130.0 not in izinli  # bu kalemde net pozisyon 100
    assert 100.0 in izinli  # net_pozisyon = kullanilabilir_stok
    assert 100.0 in izinli  # tahmin_bant_genisligi = 200 - 100


# --- Kural ------------------------------------------------------------------


def test_ihtiyac_NOKTA_TAHMINE_degil_BANDA_bakiyor():
    """⭐ Faz 10'un ölçülmüş kararı.

    Kataloğun %76'sı aralıklı talepli ve orada nokta tahmini kararın
    dayanabileceği bir sayı değil. İhtiyaç üst banttan hesaplanmalı.
    """
    o = ozellik_kur(tahmin_toplam=140.0, tahmin_ust_band=200.0)
    p = UretimProfili(emniyet_bant_carpani=1.0)

    assert ihtiyac_hesapla(o, p) == 200.0
    assert ihtiyac_hesapla(o, p) != o.tahmin_toplam


def test_emniyet_carpani_ihtiyaci_buyutuyor():
    o = ozellik_kur(tahmin_ust_band=200.0)
    assert ihtiyac_hesapla(o, UretimProfili(emniyet_bant_carpani=1.2)) == pytest.approx(240.0)


def test_emir_miktari_PARTI_KATINA_YUKARI_yuvarlaniyor():
    """⚠️ Aşağı yuvarlamak açığı kapatmayan bir emir önermek olurdu."""
    o = ozellik_kur(parti_buyuklugu=100, asgari_parti=100)
    p = UretimProfili()

    assert emir_miktari_hesapla(101.0, o, p) == 200
    assert emir_miktari_hesapla(100.0, o, p) == 100
    assert emir_miktari_hesapla(1.0, o, p) == 100


def test_emir_miktari_AZAMI_SINIRA_dayaniyor():
    """⭐ Makuliyet kapısı: bozuk bir tahmin hattı aylarca dolduramamalı.

    Bir kez bozuk ölçüm yüzünden %90'lık sahte yanlılık gördük; o sayı
    karara girseydi emir miktarı da o oranda şişerdi. Üst sınıra dayanan
    bir öneri, sayının kendisinden çok daha erken fark edilir.
    """
    o = ozellik_kur(parti_buyuklugu=100)
    p = UretimProfili(azami_emir_parti_sayisi=5)

    assert emir_miktari_hesapla(100_000.0, o, p) == 500


def test_acik_yoksa_emir_miktari_sifir():
    assert emir_miktari_hesapla(0.0, ozellik_kur(), UretimProfili()) == 0
    assert emir_miktari_hesapla(-50.0, ozellik_kur(), UretimProfili()) == 0


def test_hat_yuku_hazirlik_suresini_iceriyor():
    """Hazırlık sabit maliyet; yükün içine girmezse kapasite planı yanılır."""
    o = ozellik_kur(hazirlik_suresi_saat=1.5, birim_islem_suresi_saat=0.005)
    assert hat_yuku_saat(200, o) == pytest.approx(1.5 + 1.0)


def test_talep_yokken_ekonomiklik_SIFIRA_BOLMUYOR():
    o = ozellik_kur(tahmin_toplam=0.0)
    assert emir_ekonomik_mi(100, o, UretimProfili()) is True


# --- Karar ------------------------------------------------------------------


def test_acik_varken_EMIR_AC_kararI_cikiyor():
    """⭐ Adım 3'ün bitti ölçütü: üretilen bir kalem için emir kararı çıkıyor."""
    o = ozellik_kur(eldeki_stok=50, tahmin_ust_band=200.0)
    kararlar = ozellikten_kararlar_uret(o, UretimProfili())

    assert len(kararlar) == 1
    karar = kararlar[0]
    assert karar.tip is KararTipi.URETIM_EMIR_AC
    assert karar.alan is Alan.URETIM
    assert karar.aksiyon["emir_miktari"] == 200  # acik 150 -> 2 parti
    assert karar.aksiyon["hat_id"] == "H-01"
    assert karar.tahmini_tutar_tl == pytest.approx(200 * 12.0)


def test_stok_yetiyorsa_AKSIYON_YOK():
    o = ozellik_kur(eldeki_stok=500, tahmin_ust_band=200.0)
    kararlar = ozellikten_kararlar_uret(o, UretimProfili())

    assert kararlar[0].tip is KararTipi.URETIM_AKSIYON_YOK
    assert kararlar[0].aksiyon == {}
    assert kararlar[0].tahmini_tutar_tl == 0.0


def test_kucuk_acik_ERTELENIYOR():
    """⚠️ Hazırlık süresi sabit maliyet: bir günlük talep için hat kurulmaz.

    Açık var ama emir yalnızca yarım günlük talebi karşılıyor — sistem
    "üretme" değil "**ertele**" demeli. İkisi farklı: erteleme, ihtiyacın
    varlığını kabul edip zamanlamasını reddediyor.
    """
    o = ozellik_kur(
        eldeki_stok=195,
        tahmin_toplam=1400.0,  # gunde 100 adet
        tahmin_ust_band=200.0,
        parti_buyuklugu=5,
        asgari_parti=5,
    )
    kararlar = ozellikten_kararlar_uret(o, UretimProfili(asgari_emir_gun=3.0))

    assert kararlar[0].tip is KararTipi.URETIM_EMIR_ERTELEME
    assert kararlar[0].tahmini_tutar_tl == 0.0
    kodlar = [k.kod for k in kararlar[0].tetiklenen_kurallar]
    assert "EMIR_EKONOMIK_DEGIL" in kodlar


def test_kararlar_LISTE_donuyor():
    """⭐ Adım 4'ün kapasite kararı ortogonal; bugünden liste dönmezse kırar.

    Finansta tam bu ders alındı: tekil dönen bir uç, ikinci karar kolu
    eklenince API'ye kadar dalga yaptı (BILINEN-EKSIKLER §9).
    """
    assert isinstance(ozellikten_kararlar_uret(ozellik_kur()), list)


def test_tahmin_kural_izi_HER_ZAMAN_var():
    """⚠️ Bu iz olmadan gerekçe tahmin sayılarını kullanamaz — guard reddeder."""
    for stok in (50, 500):
        kararlar = ozellikten_kararlar_uret(ozellik_kur(eldeki_stok=stok))
        kodlar = [k.kod for k in kararlar[0].tetiklenen_kurallar]
        assert "TALEP_TAHMINI_ALINDI" in kodlar


def test_uretim_suresi_ufku_asinca_KAYIT_dusuyor_ama_emir_aciliyor():
    """Sessiz geçmek planı sistematik iyimser yapardı; erteleme sebebi değil."""
    o = ozellik_kur(eldeki_stok=50, uretim_suresi_gun=30.0, tahmin_ufuk_gun=14)
    kararlar = ozellikten_kararlar_uret(o, UretimProfili())

    assert kararlar[0].tip is KararTipi.URETIM_EMIR_AC
    kodlar = [k.kod for k in kararlar[0].tetiklenen_kurallar]
    assert "URETIM_SURESI_UFKU_ASIYOR" in kodlar


def test_genis_bant_GUVENI_dusuruyor():
    """Bandın darlığı tahminin güveni; karar bunu taşımalı."""
    dar = ozellik_kur(tahmin_toplam=140.0, tahmin_alt_band=130.0, tahmin_ust_band=150.0)
    genis = ozellik_kur(tahmin_toplam=140.0, tahmin_alt_band=0.0, tahmin_ust_band=400.0)

    dar_guven = ozellikten_kararlar_uret(dar)[0].guven
    genis_guven = ozellikten_kararlar_uret(genis)[0].guven

    assert dar_guven > genis_guven


# --- Fabrika dünyası (A10.1) -------------------------------------------------


def _sahte_katalog(n: int = 100) -> pd.DataFrame:
    paylar = np.linspace(1.0, 0.01, n)
    return pd.DataFrame(
        {
            "sku_id": [f"S-{i:05d}" for i in range(1, n + 1)],
            "sku_adi": [f"Ürün {i}" for i in range(1, n + 1)],
            "kategori": ["Tuğla"] * n,
            "birim_maliyet_tl": np.linspace(5, 50, n),
            "satis_fiyati_tl": np.linspace(8, 80, n),
            "yillik_ciro_payi": paylar / paylar.sum(),
        }
    )


def test_uretim_ana_verisi_DETERMINISTIK():
    """⭐ Aynı seed, bit bit aynı tablo.

    Tekrarlanabilir olmazsa "üretim kararı iyileşti mi" sorusu sonradan
    cevaplanamaz. Tahmin ölçümünde bu dersi iki kez aldık.
    """
    katalog = _sahte_katalog()
    ilk = uretim_ana_verisi_uret(katalog, seed=7)
    ikinci = uretim_ana_verisi_uret(katalog, seed=7)

    pd.testing.assert_frame_equal(ilk, ikinci)


def test_uretilenler_CIRO_USTUNDEN_seciliyor():
    """Az satan çeşit malı üretmek yerine satın almak neredeyse hep ucuz."""
    katalog = _sahte_katalog(100)
    uretim = uretim_ana_verisi_uret(katalog, seed=7)

    assert len(uretim) == 15  # varsayilan oran %15
    # Ciro payi en yuksek kalem uretilenler arasinda olmali.
    en_buyuk = katalog.sort_values("yillik_ciro_payi", ascending=False).iloc[0]["sku_id"]
    assert uretilen_mi(en_buyuk, uretim)
    en_kucuk = katalog.sort_values("yillik_ciro_payi").iloc[0]["sku_id"]
    assert not uretilen_mi(en_kucuk, uretim)


def test_parti_buyuklugu_SIFIR_OLAMAZ():
    """⚠️ Sıfır parti "bu kalem üretilemez" demek olurdu — hem de bir
    yuvarlama hatasının ağzından."""
    katalog = _sahte_katalog(20)
    katalog["yillik_ciro_payi"] = 1e-9  # hepsi neredeyse hic satmiyor

    uretim = uretim_ana_verisi_uret(katalog, seed=7)

    assert (uretim["parti_buyuklugu"] > 0).all()


def test_satin_alinan_kalem_icin_ozellik_URETILMIYOR():
    """ "Üretim süresi NULL" satır döndürmek, çağıranı her yerde NULL
    kontrolüne mahkûm ederdi ve bir yerde unutulurdu."""
    from app.domain.production.features import kalem_ozelliklerini_hesapla

    katalog = _sahte_katalog(100)
    uretim = uretim_ana_verisi_uret(katalog, seed=7)
    satin_alinan = katalog.sort_values("yillik_ciro_payi").iloc[0]["sku_id"]

    with pytest.raises(ValueError, match="satın alınan"):
        kalem_ozelliklerini_hesapla(
            sku_id=satin_alinan,
            olcum_tarihi=BUGUN,
            talep=pd.DataFrame(columns=["sku_id", "tarih", "talep_miktari"]),
            envanter_gunluk=pd.DataFrame(columns=["sku_id", "tarih", "eldeki_stok"]),
            sku_df=katalog,
            uretim_df=uretim,
        )


def test_fabrika_hatlari_kapasite_tasiyor():
    """Adım 4 bunun üstüne kurulacak; şimdiden dolu olmalı."""
    for hat in varsayilan_fabrika().hatlar:
        assert hat.gunluk_kapasite_saat > 0
        assert hat.hazirlik_suresi_saat >= 0
        assert hat.birim_islem_suresi_min <= hat.birim_islem_suresi_max


# --- Alan-bağımsız katmanlar (Faz 6'nın dersi) -------------------------------


def test_politika_URETIM_KARARINI_tanıyor():
    """⭐ Faz 6'da finans eklenirken alan-bağımsız katmanlar sessizce kırılmıştı.

    Politika motoru üretim kararını hiç görmeden yazıldı; `AttributeError`
    vermeden geçmesi ve `aksiyon_yok`'u oto-uygulamaya sokmaması gerekiyor.
    """
    from app.core.config import Ayarlar
    from app.core.policy import politika_uygula

    ayar = Ayarlar()
    emir = ozellikten_kararlar_uret(ozellik_kur(eldeki_stok=50))[0]
    yok = ozellikten_kararlar_uret(ozellik_kur(eldeki_stok=500))[0]

    assert politika_uygula(emir, ayar) is not None
    assert politika_uygula(yok, ayar).sonuc.value == "aksiyon_yok"


def test_sablon_gerekce_URETIMDE_PATLAMIYOR():
    """⚠️ Şablon gerekçe stok alanlarını doğrudan okuyordu ve finans kararı
    geldiğinde `AttributeError` veriyordu (BILINEN-EKSIKLER §1'in beşinci
    sızıntısı). Üretimde aynısı olmasın diye önce test.

    ⚠️ Bugün üretim kararları **alan-bağımsız son çareye** düşüyor: metin
    doğru ama zayıf. `uretim.*` şablonlarını yazmak B10.3'ün işi; bu test o
    zamana kadar "en azından patlamıyor"u koruyor.
    """
    from app.llm.explain import sablon_gerekce

    for stok in (50, 500):
        karar = ozellikten_kararlar_uret(ozellik_kur(eldeki_stok=stok))[0]
        metin = sablon_gerekce(karar)
        assert "Kırmızı Tuğla" in metin
        assert metin.strip()


def test_veri_yetersiz_kalem_OTO_UYGULANMIYOR():
    """Ölçülmemiş bir tahmine makine hızında para bağlanmamalı."""
    from app.core.config import Ayarlar
    from app.core.policy import politika_uygula

    karar = ozellikten_kararlar_uret(ozellik_kur(eldeki_stok=50, veri_gun_sayisi=30))[0]
    sonuc = politika_uygula(karar, Ayarlar())

    assert sonuc.sonuc.value != "oto_uygula"
    assert "TAHMIN_GECMISI_YETERSIZ" in " ".join(sonuc.gerekce_kodlari)


# --- Kapasite (A10.3 · Adım 4) ----------------------------------------------


def _emir_kararlari(*ozellikler):
    """Verilen kalemler için emir_ac kararları — kapasite testlerinin girdisi."""
    kararlar = []
    for o in ozellikler:
        kararlar += ozellikten_kararlar_uret(o, UretimProfili())
    return [k for k in kararlar if k.tip is KararTipi.URETIM_EMIR_AC]


def test_kapasite_yetiyorsa_KARAR_URETILMIYOR():
    """Kısıt yoksa uyarı da yok — her koşuda gürültü basan bir kural okunmaz."""
    from app.domain.production.kapasite import kapasite_kararlari_uret

    emirler = _emir_kararlari(ozellik_kur(eldeki_stok=50))
    assert kapasite_kararlari_uret(emirler, UretimProfili()) == []


def test_kapasite_asilinca_EN_AZ_ACIL_erteleniyor():
    """⭐ Adım 4'ün özü: 2 gün yeten kalem değil, 40 gün yeten kalem ertelenir.

    Ölçüt tutar değil zaman. Tutara göre sıralamak, pahalı bir kalemin
    stoğu biterken ucuz bir kalem için hattı açık tutardı.
    """
    from app.domain.production.kapasite import kapasite_kararlari_uret

    # Ayni hat, ikisi de emir gerektiriyor; birinin stogu cok daha uzun yetiyor.
    # Hat kapasitesi: 8 saat/gun x %85 x 14 gun = 95,2 saat.
    # Ikisinin toplam yuku 123 saat -> asim var; bekleyebilir dusunce 81,5'e
    # iniyor ve sigiyor. Yani erteleme SECIMI olculuyor, "hepsini ertele" degil.
    acil = ozellik_kur(
        kalem_id="S-ACIL",
        eldeki_stok=10,
        tahmin_toplam=280.0,  # gunde 20 -> kapsama 0,5 gun
        tahmin_ust_band=400.0,
        birim_islem_suresi_saat=0.2,
        hat_gunluk_kapasite_saat=8.0,
    )
    bekleyebilir = ozellik_kur(
        kalem_id="S-BEKLER",
        eldeki_stok=300,
        tahmin_toplam=140.0,  # gunde 10 -> kapsama 30 gun
        tahmin_ust_band=500.0,
        birim_islem_suresi_saat=0.2,
        hat_gunluk_kapasite_saat=8.0,
    )

    emirler = _emir_kararlari(acil, bekleyebilir)
    assert len(emirler) == 2

    kararlar = kapasite_kararlari_uret(emirler, UretimProfili())

    assert kararlar, "kapasite asilmasina ragmen karar uretilmedi"
    ertelenenler = {k.ozellikler.kalem_id for k in kararlar}
    assert "S-BEKLER" in ertelenenler
    assert "S-ACIL" not in ertelenenler


def test_kapasite_karari_ORTOGONAL_emri_susturmuyor():
    """⚠️ Finanstaki kusurun üretim karşılığı burada olurdu.

    Kapasite kararı `elif` zincirine girseydi "emir aç" kararı yok olurdu ve
    ERP, üretilmesi gereken malı hiç görmezdi. İkisi ayrı ayrı onaylanmalı.
    """
    from app.domain.production.kapasite import kapasite_kararlari_uret

    o = ozellik_kur(eldeki_stok=10, tahmin_ust_band=5000.0, birim_islem_suresi_saat=0.5)
    emirler = _emir_kararlari(o)
    kapasite = kapasite_kararlari_uret(emirler, UretimProfili())

    tumu = emirler + kapasite
    tipler = {k.tip for k in tumu}
    assert KararTipi.URETIM_EMIR_AC in tipler
    assert KararTipi.URETIM_KAPASITE_ASIMI in tipler


def test_hedef_kullanim_orani_kapasiteyi_KISIYOR():
    """%100 dolu hat, tek bir gecikmede tüm planı kaydırır."""
    from app.domain.production.kapasite import kapasite_saat

    o = ozellik_kur(hat_gunluk_kapasite_saat=10.0)
    tam = kapasite_saat(o, UretimProfili(hedef_kapasite_kullanimi=1.0, planlama_ufku_gun=14))
    hedefli = kapasite_saat(o, UretimProfili(hedef_kapasite_kullanimi=0.85, planlama_ufku_gun=14))

    assert tam == pytest.approx(140.0)
    assert hedefli == pytest.approx(119.0)


def test_talep_yokken_kapsama_SIFIRA_BOLMUYOR():
    """Hiç satmayan kalem için hat tutmak, ertelenecek ilk şeydir."""
    from app.domain.production.kapasite import SONSUZ_KAPSAMA_GUN, kapsama_gun

    assert kapsama_gun(ozellik_kur(tahmin_toplam=0.0)) == SONSUZ_KAPSAMA_GUN


def test_kapasite_sonucu_TEKRARLANABILIR():
    """⚠️ Aynı fabrika durumu iki kez hesaplanınca aynı emirler ertelenmeli.

    ⭐ Kararlar HER SEFERİNDE YENİDEN üretiliyor — aynı liste iki kez
    verilmiyor. Fark önemli: ilk sürüm eşitliği `karar_id` ile kırıyordu ve
    o alan her üretimde yeniden atanan rastgele bir UUID. Aynı listeyi iki
    kez veren bir test bunu göremezdi; nitekim göremedi, kusuru çizelgenin
    tekrarlanabilirlik testi yakaladı.
    """
    from app.domain.production.kapasite import kapasite_kararlari_uret

    def kosu() -> list[str]:
        kalemler = [
            ozellik_kur(kalem_id=f"S-{i}", eldeki_stok=10, birim_islem_suresi_saat=0.5)
            for i in range(5)
        ]
        kararlar = kapasite_kararlari_uret(_emir_kararlari(*kalemler), UretimProfili())
        return [k.ozellikler.kalem_id for k in kararlar]

    ilk, ikinci = kosu(), kosu()

    assert ilk, "kapasite asilmadi -- test bos kume karsilastiriyor olurdu"
    assert ilk == ikinci


def test_ayri_hatlar_BIRBIRINI_ETKILEMIYOR():
    """Bir hattın dolu olması, başka hattaki emri ertelemez."""
    from app.domain.production.kapasite import kapasite_kararlari_uret

    dolu = ozellik_kur(
        kalem_id="S-DOLU",
        hat_id="H-01",
        eldeki_stok=10,
        tahmin_ust_band=5000.0,
        birim_islem_suresi_saat=0.5,
    )
    bos = ozellik_kur(kalem_id="S-BOS", hat_id="H-02", eldeki_stok=50)

    kararlar = kapasite_kararlari_uret(_emir_kararlari(dolu, bos), UretimProfili())

    assert all(k.ozellikler.hat_id == "H-01" for k in kararlar)


def test_erteleme_tutari_SIFIR_DEGIL():
    """⚠️ Ertelemeyi bedelsiz göstermek, büyük emri küçük emirle aynı risk
    sınıfına sokardı — politika riski tutardan hesaplıyor."""
    from app.domain.production.kapasite import kapasite_kararlari_uret

    o = ozellik_kur(eldeki_stok=10, tahmin_ust_band=5000.0, birim_islem_suresi_saat=0.5)
    kararlar = kapasite_kararlari_uret(_emir_kararlari(o), UretimProfili())

    assert kararlar[0].tahmini_tutar_tl > 0


# --- MRP (A10.4 · Adım 5) ----------------------------------------------------


def _urun_agaci(**satirlar) -> pd.DataFrame:
    """{"S-1": [("H-A", 2.0), ("H-B", 0.5)]} biçiminden ürün ağacı tablosu."""
    kayitlar = [
        {"uretilen_sku_id": uretilen, "bilesen_sku_id": h, "birim_basina_miktar": m}
        for uretilen, bilesenler in satirlar.items()
        for h, m in bilesenler
    ]
    return pd.DataFrame(kayitlar)


def test_mrp_emri_hammaddeye_PATLATIYOR():
    """⭐ Adım 5'in özü: 200 adet mamul → kaç adet hammadde."""
    from app.domain.production.mrp import hammadde_ihtiyaci_hesapla

    emirler = _emir_kararlari(ozellik_kur(kalem_id="S-1", eldeki_stok=50))
    assert emirler[0].aksiyon["emir_miktari"] == 200

    agac = _urun_agaci(**{"S-1": [("H-A", 2.0), ("H-B", 0.5)]})
    ihtiyac = hammadde_ihtiyaci_hesapla(emirler, agac)

    assert ihtiyac["H-A"].toplam_miktar == 400.0
    assert ihtiyac["H-B"].toplam_miktar == 100.0
    assert ihtiyac["H-A"].kaynak_emirler == ("S-1",)


def test_mrp_AYNI_HAMMADDEYI_topluyor():
    """İki mamul aynı hammaddeyi kullanıyorsa ihtiyaç toplanmalı.

    Toplamamak, her mamul için ayrı sipariş açmak demek olurdu — MRP'nin
    önlemek için var olduğu şeyin ta kendisi.
    """
    from app.domain.production.mrp import hammadde_ihtiyaci_hesapla

    emirler = _emir_kararlari(
        ozellik_kur(kalem_id="S-1", eldeki_stok=50),
        ozellik_kur(kalem_id="S-2", eldeki_stok=50),
    )
    agac = _urun_agaci(**{"S-1": [("H-A", 1.0)], "S-2": [("H-A", 3.0)]})

    ihtiyac = hammadde_ihtiyaci_hesapla(emirler, agac)

    assert ihtiyac["H-A"].toplam_miktar == 800.0  # 200x1 + 200x3
    assert ihtiyac["H-A"].kaynak_emirler == ("S-1", "S-2")


def test_mrp_ERTELENEN_emri_saymiyor():
    """⚠️ Ertelenen emrin malzemesini sipariş etmek, ertelemeyi boşa çıkarır."""
    from app.domain.production.mrp import hammadde_ihtiyaci_hesapla

    ertelenen = ozellik_kur(
        kalem_id="S-1",
        eldeki_stok=195,
        tahmin_toplam=1400.0,
        tahmin_ust_band=200.0,
        parti_buyuklugu=5,
        asgari_parti=5,
    )
    kararlar = ozellikten_kararlar_uret(ertelenen, UretimProfili(asgari_emir_gun=3.0))
    assert kararlar[0].tip is KararTipi.URETIM_EMIR_ERTELEME

    agac = _urun_agaci(**{"S-1": [("H-A", 2.0)]})
    assert hammadde_ihtiyaci_hesapla(kararlar, agac) == {}


def test_mrp_eksik_agac_GORUNUR_oluyor():
    """⚠️ Sessiz atlama gerekli ama yeterli değil.

    Ürün ağacı tanımsız kalem sessizce atlanıyor (tek eksik satır tüm MRP
    koşusunu düşürmemeli) — ama atlandığı raporlanmazsa, üretimi durduran
    bir malzeme eksiği üç ay sonra keşfedilir.
    """
    from app.domain.production.mrp import eksik_agac_kalemleri, hammadde_ihtiyaci_hesapla

    emirler = _emir_kararlari(ozellik_kur(kalem_id="S-YOK", eldeki_stok=50))
    agac = _urun_agaci(**{"S-BASKA": [("H-A", 1.0)]})

    assert hammadde_ihtiyaci_hesapla(emirler, agac) == {}
    assert eksik_agac_kalemleri(emirler, agac) == ["S-YOK"]


def test_mrp_ihtiyaci_STOK_ESIGINI_yukseltiyor():
    """⭐ MRP'nin stoğa bağlandığı tek nokta.

    Aynı SKU, aynı stok: MRP ihtiyacı olmadan "aksiyon yok", ihtiyaçla
    birlikte "sipariş". Bu bağ kurulmazsa MRP dekoratif kalır.
    """
    from app.contracts import StockFeatures
    from app.domain.stock.decide import ozellikten_karar_uret

    ortak = {
        "sku_id": "H-A",
        "sku_adi": "Çimento 50kg",
        "kategori": "Çimento",
        "eldeki_stok": 500,
        "rezerve_stok": 0,
        "yoldaki_stok": 0,
        "ort_gunluk_talep": 10.0,
        "talep_std": 2.0,
        "veri_gun_sayisi": 400,
        "tedarik_suresi_gun": 10.0,
        "tedarik_suresi_std": 1.0,
        "abc_sinifi": ABCSinifi.A,
        "xyz_sinifi": XYZSinifi.X,
        "hedef_servis_seviyesi": 0.95,
        "son_hareket_gun_once": 1,
        "birim_maliyet_tl": 100.0,
        "satis_fiyati_tl": 150.0,
        "tedarikci_id": "T-1",
        "tedarikci_adi": "Yılmaz Yapı",
        "tedarikci_skoru": 90.0,
        "tedarikci_zamaninda_teslim_orani": 0.94,
        "tedarikci_onayli": True,
        "moq": 100,
        "paket_adedi": 50,
        "olcum_tarihi": BUGUN,
    }

    mrpsiz = ozellikten_karar_uret(StockFeatures(**ortak))
    mrpli = ozellikten_karar_uret(StockFeatures(**ortak, mrp_ihtiyaci=2000.0))

    assert mrpsiz.tip is KararTipi.STOK_AKSIYON_YOK
    assert mrpli.tip is KararTipi.STOK_SIPARIS
    kodlar = [k.kod for k in mrpli.tetiklenen_kurallar]
    assert "URETIM_TALEBI_EKLENDI" in kodlar


def test_mrp_varsayilani_stok_davranisini_DEGISTIRMIYOR():
    """⚠️ Sözleşmeye alan eklemek tek başına hiçbir sayıyı oynatmamalı."""
    from app.contracts import StockFeatures

    assert StockFeatures.model_fields["mrp_ihtiyaci"].default == 0.0


def test_urun_agaci_bilesenleri_SATIN_ALINANDAN_seciyor():
    """⚠️ Bileşen de üretilen olsaydı özyineleme ve döngü riski doğardı.

    A parçası B'yi, B de A'yı içerirse patlatma sonsuza gider. Satın
    alınanlarla sınırlamak bu riski kontrol ederek değil, **imkânsız
    kılarak** kapatıyor.
    """
    from simulator.uretim import urun_agaci_uret

    katalog = _sahte_katalog(100)
    uretim = uretim_ana_verisi_uret(katalog, seed=7)
    agac = urun_agaci_uret(katalog, uretim, seed=7)

    uretilenler = set(uretim["sku_id"])
    assert set(agac["uretilen_sku_id"]) == uretilenler
    assert not (set(agac["bilesen_sku_id"]) & uretilenler)


# --- Servis katmanı (Adım 6) -------------------------------------------------


def test_explain_URETIM_TIPLERINI_taniyor():
    """⭐ B5'in kök nedeninin tekrarını önleyen test.

    Finans tipleri `_TIPE_GORE_ALANLAR`'da yoktu; sonuç sessizdi —
    `sayi_etiketleri` boş dönüyor, model hiç çağrılmıyor, 25 kararın 25'i
    0 saniyede şablona düşüyordu. Kusur ancak ölçünce görülmüştü.
    """
    from app.llm.explain import sayi_etiketleri

    for stok in (50, 500):
        karar = ozellikten_kararlar_uret(ozellik_kur(eldeki_stok=stok))[0]
        etiketler = sayi_etiketleri(karar)
        assert etiketler, f"{karar.tip.value} icin modele verilecek sayi yok"
        # Etiketler Turkce ve ham alan adi degil.
        assert all("_" not in ad for ad, _ in etiketler), etiketler


def test_uretim_sablonu_ALAN_BAGIMSIZ_SON_CAREYE_dusmuyor():
    """Artık kendi şablonu var; genel "karar üretildi" cümlesi kalmamalı."""
    from app.llm.explain import sablon_gerekce

    emir = ozellikten_kararlar_uret(ozellik_kur(eldeki_stok=50))[0]
    metin = sablon_gerekce(emir)

    assert "uretim.emir_ac" not in metin, "alan-bagimsiz son careye dusmus"
    assert "Kesim Hattı" in metin
    assert "üretim emri" in metin


def test_kapasite_sablonu_HATTI_anlatiyor():
    from app.domain.production.kapasite import kapasite_kararlari_uret
    from app.llm.explain import sablon_gerekce

    o = ozellik_kur(eldeki_stok=10, tahmin_ust_band=5000.0, birim_islem_suresi_saat=0.5)
    kararlar = kapasite_kararlari_uret(_emir_kararlari(o), UretimProfili())

    metin = sablon_gerekce(kararlar[0])
    assert "Kesim Hattı" in metin
    assert "kapasite" in metin.lower()


def test_uretim_ucu_LISTE_donuyor(istemci):
    """⭐ Adım 6'nın bitti ölçütü: uç, bir kalemin tüm kararlarını döndürüyor.

    ⚠️ Tekil dönen bir uç, "emir aç" ile "hat dolu" kararlarından birini
    ERP'den gizlerdi — finansta tam bu kusur yaşandı (B1).
    """
    cevap = istemci.post("/v1/decisions/production/order-review")

    assert cevap.status_code == 200
    govde = cevap.json()
    assert isinstance(govde, list)
    assert govde, "hic uretim karari donmedi"

    tipler = {k["aday"]["tip"] for k in govde}
    assert tipler <= {
        "uretim.emir_ac",
        "uretim.emir_erteleme",
        "uretim.kapasite_asimi",
        "uretim.aksiyon_yok",
    }
    assert "uretim.emir_ac" in tipler
    # Karar yolu LLM'i beklememeli.
    assert all(k["gerekce"] is None for k in govde)


def test_uretim_ucu_bilinmeyen_kalemde_404(istemci):
    cevap = istemci.post("/v1/decisions/production/order-review?kalem_id=YOK-123")
    assert cevap.status_code == 404


def test_gecelik_tarama_URETIMI_de_tariyor():
    """⚠️ Yeni alan gecelik taramaya girmezse sistem kendi kendine koşmuyor demektir.

    Faz 6'da finans kararları `try/except` içinde sessizce yutuluyordu ve
    kuyruğa hiç girmiyorlardı. Üretim için aynısı olmasın diye üreteç
    doğrudan sınanıyor.
    """
    from app.jobs.nightly import _uretim_kararlari

    kararlar = _uretim_kararlari()

    assert kararlar, "gecelik tarama uretim karari uretmiyor"
    assert all(k.alan is Alan.URETIM for k in kararlar)


# --- Çizelge (Adım 7) --------------------------------------------------------


def _cizelge(*ozellikler):
    from app.domain.production.cizelge import cizelge_kur

    return cizelge_kur(
        _emir_kararlari(*ozellikler), baslangic=BUGUN, uretim_profili=UretimProfili()
    )


def test_cizelge_en_ACIL_isi_one_aliyor():
    """⭐ Çizelgenin sıralama ölçütü kapasite kararıyla AYNI olmalı.

    İki ayrı öncelik tanımı olsaydı sistem kendi içinde çelişirdi: kapasite
    "bunu ertele" derken çizelge aynı işi başa koyardı.
    """
    acil = ozellik_kur(
        kalem_id="S-ACIL", kalem_adi="Acil Ürün", eldeki_stok=10, tahmin_toplam=280.0
    )
    bekler = ozellik_kur(
        kalem_id="S-BEKLER", kalem_adi="Bekleyen Ürün", eldeki_stok=190, tahmin_toplam=140.0
    )

    cizelge = _cizelge(acil, bekler)

    assert len(cizelge) == 1
    sira = [s.kalem_id for s in cizelge[0].satirlar]
    assert sira[0] == "S-ACIL", f"acil is basta olmali, sira: {sira}"


def test_cizelge_gune_SIGMAYAN_isi_ertesi_gune_tasiyor():
    """Günlük kapasite 13,6 saat; 21,5 saatlik iş iki güne yayılmalı."""
    o = ozellik_kur(
        eldeki_stok=10,
        tahmin_ust_band=400.0,
        birim_islem_suresi_saat=0.05,  # 400 adet -> 1,5 + 20 = 21,5 saat
        hat_gunluk_kapasite_saat=16.0,
    )
    satir = _cizelge(o)[0].satirlar[0]

    assert satir.gun_sayisi >= 2, "21,5 saatlik is tek gune sigmamali"
    assert satir.baslangic == BUGUN


def test_cizelge_hatlari_PARALEL_isliyor():
    """Bir hattaki doluluk diğer hattı geciktirmemeli."""
    h1 = ozellik_kur(kalem_id="S-1", hat_id="H-01", hat_adi="Kesim", eldeki_stok=10)
    h2 = ozellik_kur(kalem_id="S-2", hat_id="H-02", hat_adi="Montaj", eldeki_stok=10)

    cizelge = _cizelge(h1, h2)

    assert len(cizelge) == 2
    assert all(h.satirlar[0].baslangic == BUGUN for h in cizelge)


def test_ufka_SIGMAYAN_is_kaybolmuyor():
    """⚠️ Çizelgeye koymamak, işi iptal etmek değil.

    Kullanıcı hangi işin dışarıda kaldığını görmek zorunda; sessizce
    düşürmek "her şey planlandı" izlenimi verirdi.
    """
    # 12 parti x 100 adet x 0,5 saat = 600 saat; ufuk 14 gun x 13,6 = 190 saat.
    o = ozellik_kur(eldeki_stok=10, tahmin_ust_band=5000.0, birim_islem_suresi_saat=0.5)
    hat = _cizelge(o)[0]

    assert hat.sigmayanlar, "ufka sigmayan is raporlanmadi"
    assert not hat.satirlar, "yarim kalan is planlanmis gibi gosterilmemeli"


def test_cizelge_TEKRARLANABILIR():
    """Aynı girdi aynı çizelge — yoksa "sistem neden fikir değiştirdi" cevapsız."""
    kalemler = [ozellik_kur(kalem_id=f"S-{i}", eldeki_stok=10) for i in range(6)]

    ilk = _cizelge(*kalemler)
    ikinci = _cizelge(*kalemler)

    assert [s.kalem_id for s in ilk[0].satirlar] == [s.kalem_id for s in ikinci[0].satirlar]


def test_cizelge_YENI_KARAR_URETMIYOR():
    """⭐ Mimari sınır: çizelge türetilmiş bir görünüm, karar değil.

    Buraya bir `DecisionCandidate` girdiği gün onay modeli sessizce delinir —
    çizelgeyi onaylamak, içindeki yüzlerce örtük kararı görmeden onaylamak
    olur.
    """
    import inspect

    from app.domain.production import cizelge

    kaynak = inspect.getsource(cizelge)
    assert "DecisionCandidate(" not in kaynak, "cizelge karar uretiyor -- onay modeli delinir"


def test_cizelge_metni_okunabilir():
    from app.domain.production.cizelge import cizelge_metni

    metin = cizelge_metni(_cizelge(ozellik_kur(eldeki_stok=10)))

    assert "Kesim Hattı" in metin
    assert "Kırmızı Tuğla" in metin
    assert "adet" in metin


def test_cizelge_ucu_hat_ve_gun_donuyor(istemci):
    """⭐ Kullanıcının istediği çıktı: "şu iş, şu hatta, şu gün"."""
    cevap = istemci.get("/v1/decisions/production/schedule")

    assert cevap.status_code == 200
    hatlar = cevap.json()["hatlar"]
    assert hatlar, "hic hat donmedi"

    hat = hatlar[0]
    assert hat["hat_adi"]
    assert hat["isler"], "hatta planlanmis is yok"

    ilk = hat["isler"][0]
    assert ilk["baslangic"] and ilk["bitis"]
    assert ilk["miktar"] > 0
    # "Neden bu is once" sorusunun cevabi cikti da olmali.
    assert "stok_kapsama_gun" in ilk


def test_cizelge_ucu_KARAR_YAZMIYOR(istemci):
    """⚠️ Çizelge türetilmiş bir görünüm; DB'ye karar yazmamalı.

    Yazsaydı aynı emir hem karar ucundan hem çizelge ucundan iki kez
    kaydedilir ve onay kuyruğu çiftlenirdi.
    """
    from app.models import Decision

    def sayi() -> int:
        with istemci.app.state.oturum_fabrikasi()() as oturum:  # type: ignore[attr-defined]
            return oturum.query(Decision).count()

    try:
        onceki = sayi()
    except Exception:
        pytest.skip("oturum fabrikasi test istemcisinde acik degil")

    istemci.get("/v1/decisions/production/schedule")
    assert sayi() == onceki


def test_cizelge_ucu_OLCUT_parametresi_aliyor(istemci):
    """⭐ "İyi plan" tanımı çağıranın seçimi; varsayılan bugünkü davranış."""
    varsayilan = istemci.get("/v1/decisions/production/schedule")
    degerli = istemci.get("/v1/decisions/production/schedule?olcut=en_degerli")

    assert varsayilan.status_code == 200
    assert degerli.status_code == 200

    def ilk_isler(cevap):
        return [h["isler"][0]["kalem_id"] for h in cevap.json()["hatlar"] if h["isler"]]

    assert ilk_isler(varsayilan) != ilk_isler(degerli), "olcut plani degistirmiyor"


def test_cizelge_ucu_bilinmeyen_olcutte_422(istemci):
    """⚠️ Yazım hatası sessizce varsayılana düşmemeli."""
    cevap = istemci.get("/v1/decisions/production/schedule?olcut=en_hizli")
    assert cevap.status_code == 422


def test_karsilastirma_ucu_KARNE_ve_oneri_donuyor(istemci):
    """⭐ Kullanıcının istediği: birkaç plan, farkı görünür, biri önerili."""
    cevap = istemci.get("/v1/decisions/production/schedule/compare")

    assert cevap.status_code == 200
    govde = cevap.json()

    assert len(govde["karneler"]) >= 2, "tek plan karsilastirma degildir"
    assert govde["onerilen"] in {k["olcut"] for k in govde["karneler"]}
    assert "TL" in govde["gerekce"], "oneri parayla gerekcelendirilmeli"
    # ⚠️ Varsayımlar cevabın parçası olmalı; öneri onları gizlememeli.
    assert govde["varsayimlar"]

    karne = govde["karneler"][0]
    assert {"stoksuzluk_tl", "elde_tutma_tl", "kurulum_tl"} <= set(karne["maliyet"])
