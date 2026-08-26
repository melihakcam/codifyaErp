"""Finans kural motoru + karar üretimi testleri (Faz 6.3).

Bu testlerin iki işi var:

1. Finans kurallarının doğru çalıştığını göstermek.
2. **Stok kalıbının gerçekten taşındığını** göstermek — aynı formül, aynı
   iskelet, aynı sözleşme. Kalıp taşınmadıysa Faz 6'nın geri kalanı (satış,
   üretim) her seferinde sıfırdan yazılmak zorunda kalır.
"""

from __future__ import annotations

import datetime as dt

from app.contracts import ABCSinifi, Alan, FinansOzellikleri, KararTipi, XYZSinifi
from app.domain.finance.decide import ozellikten_karar_uret
from app.domain.finance.rules import (
    HEDEF_TAHSILAT_ORANI_MATRISI,
    LIMIT_DUSURME_SKOR_ESIGI,
    emniyet_gunu_hesapla,
    esik_ve_emniyet_gunu,
    karsilik_degerlendir,
    karsilik_orani_hesapla,
    limit_degerlendir,
    musteri_risk_skoru,
)


def oz(**degisiklikler) -> FinansOzellikleri:
    varsayilan = {
        "musteri_id": "M-0042",
        "musteri_adi": "Yılmaz İnşaat Ltd.",
        "segment": "santiye",
        "toplam_alacak_tl": 250_000.0,
        "vadesi_gecen_tl": 95_000.0,
        "en_eski_gecikme_gun": 62,
        "ort_odeme_gecikmesi_gun": 18.5,
        "odeme_gecikmesi_std": 7.4,
        "veri_gun_sayisi": 540,
        "kredi_limiti_tl": 200_000.0,
        "abc_sinifi": ABCSinifi.A,
        "xyz_sinifi": XYZSinifi.Y,
        "hedef_tahsilat_orani": 0.95,
        "son_odeme_gun_once": 41,
        "tahsilat_orani": 0.88,
        "musteri_kredi_onayli": True,
        "olcum_tarihi": dt.date(2026, 8, 8),
    }
    return FinansOzellikleri(**{**varsayilan, **degisiklikler})


# --- Takip eşiği: stoktaki ROP'un karşılığı -----------------------------------


def test_emniyet_gunu_belirsizlikle_buyuyor():
    az = emniyet_gunu_hesapla(0.95, odeme_gecikmesi_std=5.0)
    cok = emniyet_gunu_hesapla(0.95, odeme_gecikmesi_std=25.0)

    assert cok > az


def test_belirsizlik_yoksa_emniyet_payi_yok():
    """Hep tam vadesinde ödeyen müşteri için erken arama gerekmez."""
    assert emniyet_gunu_hesapla(0.95, odeme_gecikmesi_std=0.0) == 0.0


def test_hedef_yukseldikce_pay_buyuyor():
    dusuk = emniyet_gunu_hesapla(0.85, 10.0)
    yuksek = emniyet_gunu_hesapla(0.99, 10.0)

    assert yuksek > dusuk


def test_esik_anomali_dedektoru_gibi_calisiyor():
    """⭐ Modelin özü ve stoktakiyle YÖNÜ TERS olan yer.

    Düzenli ödeyen için dar bant (küçük sapma alarm), savrulan için geniş
    bant (aynı sapma gürültü). Bu, "erken davran" değil "olağandışını
    yakala" mantığı — ve bilinçli.
    """
    duzenli = oz(ort_odeme_gecikmesi_gun=20.0, odeme_gecikmesi_std=2.0)
    savrulan = oz(ort_odeme_gecikmesi_gun=20.0, odeme_gecikmesi_std=30.0)

    esik_duzenli, _ = esik_ve_emniyet_gunu(duzenli)
    esik_savrulan, _ = esik_ve_emniyet_gunu(savrulan)

    assert esik_duzenli < 30, "düzenli ödeyen için bant dar olmalı"
    assert esik_savrulan > 50, "savrulan için bant geniş olmalı"


# --- Karşılık: stoktaki ölü stok değerlendirmesinin karşılığı -----------------


def test_karsilik_orani_yaslandikca_artiyor():
    assert karsilik_orani_hesapla(10) == 0.0
    assert karsilik_orani_hesapla(45) == 0.05
    assert karsilik_orani_hesapla(120) == 0.20
    assert karsilik_orani_hesapla(200) == 0.50
    assert karsilik_orani_hesapla(400) == 1.00


def test_karsilik_esigi_musteriye_gore_degisiyor():
    """Yavaş ödeyen segmentte eşik yukarı kayar; aşağı kaymaz.

    ⚠️ Bu test Faz 7'de değişti. Önceden hızlı ödeyende eşik 20 güne kadar
    inebiliyordu ve 60 günlük alacak için karşılık isteniyordu. Göreceli
    çarpan artık yalnızca eşiği yükseltiyor, `KARSILIK_TABAN_ESIK_GUN`'ün
    altına indiremiyor — gerekçesi `rules._karsilik_esigi` docstring'inde.
    """
    hizli = karsilik_degerlendir(oz(ort_odeme_gecikmesi_gun=5.0, en_eski_gecikme_gun=120))
    yavas = karsilik_degerlendir(oz(ort_odeme_gecikmesi_gun=40.0, en_eski_gecikme_gun=120))

    assert hizli["karsilik_esigi_gun"] < yavas["karsilik_esigi_gun"]
    assert hizli["karsilik_gerekli"]
    assert not yavas["karsilik_gerekli"]


def test_karsilik_esigi_taban_altina_inmiyor():
    """Ortalama 5 günde ödeyen müşterinin 40 günlük alacağına karşılık
    ayrılmaz — muhasebe pratiği 90 günden önce anlamlı karşılık tanımıyor."""
    d = karsilik_degerlendir(oz(ort_odeme_gecikmesi_gun=5.0, en_eski_gecikme_gun=40))

    assert d["karsilik_esigi_gun"] == 90
    assert not d["karsilik_gerekli"]


def test_karsilik_tutari_vadesi_gecenden_hesaplaniyor():
    d = karsilik_degerlendir(oz(en_eski_gecikme_gun=200, vadesi_gecen_tl=100_000.0))

    assert d["onerilen_karsilik_orani"] == 0.50
    assert d["karsilik_tutari_tl"] == 50_000.0


# --- Risk skoru: stoktaki tedarikçi skorunun karşılığı ------------------------


def test_risk_skoru_tahsilat_gecmisine_duyarli():
    iyi = musteri_risk_skoru(oz(tahsilat_orani=0.98))
    kotu = musteri_risk_skoru(oz(tahsilat_orani=0.40))

    assert iyi > kotu


def test_risk_skoru_ortalamaya_degil_OYNAKLIGA_bakiyor():
    """⭐ Geç ama düzenli ödeyen, erken ama savrulan müşteriden iyidir.

    Kronik geciken (ortalama kötü, sapma küçük) ile düzensiz ödeyen
    (ortalama iyi, sapma büyük) karşılaştırılıyor. Tahsilat geçmişleri
    eşit tutuldu ki fark yalnızca davranış tutarlılığından gelsin.
    """
    kronik = oz(ort_odeme_gecikmesi_gun=45.0, odeme_gecikmesi_std=5.0)
    duzensiz = oz(ort_odeme_gecikmesi_gun=12.0, odeme_gecikmesi_std=25.0)

    assert musteri_risk_skoru(kronik) > musteri_risk_skoru(duzensiz), (
        "geç ama öngörülebilir ödeyen, erken ama savrulan müşteriden iyi skorlanmalı"
    )


def test_riskli_musteride_limit_dusuruluyor(limit_kolu_acik):
    riskli = oz(tahsilat_orani=0.30, ort_odeme_gecikmesi_gun=20.0, odeme_gecikmesi_std=45.0)

    d = limit_degerlendir(riskli)

    assert d["limit_dusurulmeli"]
    assert d["musteri_risk_skoru"] < LIMIT_DUSURME_SKOR_ESIGI
    assert d["onerilen_kredi_limiti_tl"] < riskli.kredi_limiti_tl


def test_limit_kolu_varsayilan_acik():
    """⭐ A5'in sonucu: kol varsayılan AÇIK ve bu ölçülmüş bir karar.

    ⚠️ Bu bayrak bugün iki kez ölçüldü, iki farklı cevap verdi:
    A7.1 kapattı (varsayılan senaryoda zarar ettiriyordu), A5 yeniden açtı
    (altı risk senaryosunun beşinde kârlı). Belirleyici olan çoğunluk değil
    **kaybın asimetrisi**: gereksizken açık olmak 8.543 TL, gerekliyken
    kapalı olmak 96.541 TL — 11 kat. Tam tablo:
    `rules.LIMIT_KOLU_AKTIF` docstring'i.

    Bu test bir davranışı değil bir **kararı** koruyor. Bayrak sessizce
    değişirse ölçülmemiş bir risk profiline geçilmiş olur.
    """
    riskli = oz(tahsilat_orani=0.30, ort_odeme_gecikmesi_gun=20.0, odeme_gecikmesi_std=45.0)
    d = limit_degerlendir(riskli)

    assert d["limit_dusurulmeli"]
    assert d["musteri_risk_skoru"] < LIMIT_DUSURME_SKOR_ESIGI


def test_saglam_musteride_limit_korunuyor():
    d = limit_degerlendir(oz(tahsilat_orani=0.97, odeme_gecikmesi_std=3.0))

    assert not d["limit_dusurulmeli"]


# --- Karar üretimi: kollar ve birincil karar --------------------------------------------


def test_esik_altinda_ve_tutar_kucukse_aksiyon_yok():
    """⚠️ Bu test §12'de değişti ve değişme sebebi öğretici.

    Önceden yalnızca `en_eski_gecikme_gun=15` veriliyordu ve karar
    `aksiyon_yok` çıkıyordu. Maddiyet kolu eklenince aynı girdi
    `tahsilat_takibi` vermeye başladı — çünkü varsayılan `vadesi_gecen_tl`
    95.000 TL ve o tutar aramayı fazlasıyla hak ediyor.

    Yani eski test "eşik altında hiçbir şey yapılmaz" varsayıyordu; doğrusu
    "eşik altında **ve tutar küçükse** hiçbir şey yapılmaz". Kusur testte
    değil, sistemin o zamanki dünya görüşündeydi.
    """
    karar = ozellikten_karar_uret(oz(en_eski_gecikme_gun=15, vadesi_gecen_tl=800.0))

    assert karar.tip is KararTipi.FINANS_AKSIYON_YOK
    assert karar.tahmini_tutar_tl == 0.0


def test_esik_asilinca_takip():
    karar = ozellikten_karar_uret(oz(en_eski_gecikme_gun=62))

    assert karar.tip is KararTipi.FINANS_TAHSILAT_TAKIBI
    assert karar.tahmini_tutar_tl == 95_000.0


def test_cok_eski_alacakta_karsilik_birincil_karar():
    """Çok eski alacakta birincil karar karşılık.

    ⚠️ Faz 7'de anlamı değişti: karşılık artık takibi EZMİYOR, yalnızca
    listenin başında duruyor. Aynı müşteri için takip kararı da üretiliyor —
    `test_batak_musteri_hem_karsilik_hem_takip_aliyor` onu doğruluyor.
    """
    karar = ozellikten_karar_uret(oz(en_eski_gecikme_gun=400))

    assert karar.tip is KararTipi.FINANS_KARSILIK_AYIR
    assert not karar.geri_alinabilir, "karşılık muhasebe kaydı — geri alınamaz sayılmalı"


def test_riskli_musteride_limit_birincil_karar(limit_kolu_acik):
    """Riskli müşteride birincil karar limit düşürme.

    Takip kararı da üretilebilir; ikisi ayrı sorulara cevap veriyor —
    limit geleceği, takip bugünkü nakdi ilgilendirir.
    """
    karar = ozellikten_karar_uret(
        oz(en_eski_gecikme_gun=62, tahsilat_orani=0.30, odeme_gecikmesi_std=45.0)
    )

    assert karar.tip is KararTipi.FINANS_KREDI_LIMITI_DUSUR


# --- Sözleşme uyumu -----------------------------------------------------------


def test_karar_sozlesmeye_uyuyor():
    karar = ozellikten_karar_uret(oz())

    assert karar.alan is Alan.FINANS
    assert karar.tip.alan == "finans"
    assert 0.0 <= karar.guven <= 1.0
    assert karar.tetiklenen_kurallar
    assert karar.izinli_sayilar()


def test_kural_degerleri_izinli_kumede():
    """⭐ Guard'ın çalışması buna bağlı.

    Bir kural sayı hesaplayıp `degerler`'e yazmazsa, LLM o sayıyı gerekçede
    kullandığında guard onu uydurma sayar ve metin şablona düşer. Stokta bu
    hata bir kez yaşandı (bkz. `onerilen_iskonto_orani`, OLCUMLER.md).
    """
    karar = ozellikten_karar_uret(oz(en_eski_gecikme_gun=62))
    izinli = karar.izinli_sayilar()

    for kural in karar.tetiklenen_kurallar:
        for ad, deger in kural.degerler.items():
            assert float(deger) in izinli, f"{kural.kod}.{ad} izinli kümede yok"


def test_aksiyon_degerleri_izinli_kumede():
    karar = ozellikten_karar_uret(oz(en_eski_gecikme_gun=400))

    izinli = karar.izinli_sayilar()
    for ad, deger in karar.aksiyon.items():
        if isinstance(deger, (int, float)) and not isinstance(deger, bool):
            assert float(deger) in izinli, f"aksiyon.{ad} izinli kümede yok"


def test_guven_veri_azken_dusuk():
    az = ozellikten_karar_uret(oz(veri_gun_sayisi=30))
    cok = ozellikten_karar_uret(oz(veri_gun_sayisi=1000))

    assert az.guven < cok.guven


def test_guven_savrulan_musteride_dusuk():
    """Üç yıllık veri de olsa, rastgele ödeyen müşteri tahmin edilemez."""
    duzenli = ozellikten_karar_uret(oz(veri_gun_sayisi=1000, odeme_gecikmesi_std=2.0))
    savrulan = ozellikten_karar_uret(oz(veri_gun_sayisi=1000, odeme_gecikmesi_std=40.0))

    assert savrulan.guven < duzenli.guven


# --- Kalıbın taşındığının kanıtı ----------------------------------------------


def test_hedef_matrisi_stoktakiyle_ayni_yapida():
    """Aynı ABC/XYZ ızgarası, aynı dokuz hücre."""
    from app.domain.stock.rules import HEDEF_SERVIS_SEVIYESI_MATRISI

    assert set(HEDEF_TAHSILAT_ORANI_MATRISI) == set(HEDEF_SERVIS_SEVIYESI_MATRISI)
    assert len(HEDEF_TAHSILAT_ORANI_MATRISI) == 9


def test_iki_alan_ayni_siniflandirma_cekirdegini_kullaniyor():
    """`abc_sinif_ata` iki alanda da AYNI fonksiyon nesnesi olmalı."""
    from app.domain.siniflandirma import abc_sinif_ata as ortak
    from app.domain.stock.rules import abc_sinif_ata as stok

    assert stok is ortak


def test_finans_stoka_bagimli_degil():
    """⚠️ İki eşdüzey alandan biri diğerine bağlanmamalı.

    Bağlansaydı üçüncü alan (satış) eklendiğinde çözülemez bir düğüm olurdu.
    Ortak olan her şey `app/domain/siniflandirma.py`'de.
    """
    import ast
    import inspect

    from app.domain.finance import decide, rules

    for modul in (rules, decide):
        agac = ast.parse(inspect.getsource(modul))
        ithal = {d.module for d in ast.walk(agac) if isinstance(d, ast.ImportFrom) and d.module}
        assert not any(m.startswith("app.domain.stock") for m in ithal), (
            f"{modul.__name__} stok alanına bağımlı: {ithal}"
        )


# --- Politika güvenliği -------------------------------------------------------


def test_geri_alinamaz_finans_kararlari_daima_onay_istiyor():
    """⚠️ Faz 6'da bulunan güvenlik açığı.

    `DAIMA_ONAY_GEREKTIREN` yalnızca stok tiplerini taşıyordu. Finans
    kararları eklenince `karsilik_ayir` ve `kredi_limiti_dusur`, tutar ve
    güven eşiklerinin altında kalırlarsa **sessizce oto-uygulanabilir**
    hâle geliyordu.

    Karşılık bir muhasebe kaydıdır; limit kısmak müşteri ilişkisini etkiler.
    İkisi de insan onayı olmadan uygulanmamalı.
    """
    from app.core.policy import DAIMA_ONAY_GEREKTIREN

    assert KararTipi.FINANS_KARSILIK_AYIR in DAIMA_ONAY_GEREKTIREN
    assert KararTipi.FINANS_KREDI_LIMITI_DUSUR in DAIMA_ONAY_GEREKTIREN


def test_karsilik_karari_kucuk_tutarda_bile_onaya_gidiyor():
    """Eşik altında kalan bir karşılık kararı da onay kuyruğuna girmeli."""
    from app.contracts import PolitikaSonucu
    from app.core.config import Ayarlar
    from app.core.policy import politika_uygula

    karar = ozellikten_karar_uret(
        oz(en_eski_gecikme_gun=400, vadesi_gecen_tl=50.0, veri_gun_sayisi=1000)
    )
    sonuc = politika_uygula(karar, Ayarlar(ollama_base_url="http://sahte:11434"))

    assert karar.tip is KararTipi.FINANS_KARSILIK_AYIR
    assert sonuc.sonuc is PolitikaSonucu.ONAY_KUYRUGU
    assert "TIP_DAIMA_ONAY" in sonuc.gerekce_kodlari


def test_takip_karari_esik_altinda_oto_uygulanabiliyor():
    """Karşıt kontrol: her finans kararı onay istemiyor.

    Tahsilat takibi geri alınabilir bir eylem (müşteriyi aramak) — küçük
    tutarda ve yüksek güvende oto-uygulanabilmeli. Aksi hâlde yukarıdaki
    test "her şey onaya gidiyor" diye de geçerdi ve hiçbir şey kanıtlamazdı.
    """
    from app.contracts import PolitikaSonucu
    from app.core.config import Ayarlar
    from app.core.policy import politika_uygula

    karar = ozellikten_karar_uret(
        oz(
            en_eski_gecikme_gun=62,
            vadesi_gecen_tl=100.0,
            veri_gun_sayisi=1000,
            odeme_gecikmesi_std=2.0,
            tahsilat_orani=0.97,
        )
    )
    sonuc = politika_uygula(karar, Ayarlar(ollama_base_url="http://sahte:11434"))

    assert karar.tip is KararTipi.FINANS_TAHSILAT_TAKIBI
    assert sonuc.sonuc is PolitikaSonucu.OTO_UYGULA


# --- Karar kolları ortogonal mi (Faz 7) --------------------------------------


def test_batak_musteri_hem_karsilik_hem_takip_aliyor():
    """⭐ Faz 7'nin ana düzeltmesi. Bu test kırılırsa kusur geri gelmiştir.

    Önceden `karşılık → limit → takip` bir `elif` zinciriydi: karşılık
    gereken müşteri hiçbir zaman takibe girmiyordu. Ölçüldüğünde sonuç şuydu
    — kural motoru 12 ayda hiçbir batık alacağı kurtaramıyor, batak zararı
    hiçbir şey yapmayan taban politikayla birebir aynı çıkıyordu.

    Ayrıntı: `app/domain/finance/decide.py` modül docstring'i,
    `dokumantasyon/BILINEN-EKSIKLER.md` §9.
    """
    from app.domain.finance.decide import ozellikten_kararlar_uret

    # Çok eski alacağı olan ama normalde hızlı ödeyen müşteri:
    # karşılık eşiğini de takip eşiğini de aşıyor.
    batak = oz(
        ort_odeme_gecikmesi_gun=10.0,
        odeme_gecikmesi_std=3.0,
        en_eski_gecikme_gun=250,
        vadesi_gecen_tl=80_000.0,
    )
    tipler = {k.tip for k in ozellikten_kararlar_uret(batak)}

    assert KararTipi.FINANS_KARSILIK_AYIR in tipler
    assert KararTipi.FINANS_TAHSILAT_TAKIBI in tipler, (
        "karşılık ayrılan müşteri tahsilat takibinden düşmemeli — "
        "muhasebe kaydı, tahsilat çabasını durdurmaz"
    )


def test_hicbir_kosul_saglanmazsa_tek_aksiyon_yok_karari():
    """Boş liste dönmemeli: "baktım, bir şey yok" ile "hiç bakmadım" farklı."""
    from app.domain.finance.decide import ozellikten_kararlar_uret

    sakin = oz(
        ort_odeme_gecikmesi_gun=10.0,
        odeme_gecikmesi_std=3.0,
        en_eski_gecikme_gun=0,
        vadesi_gecen_tl=0.0,
        tahsilat_orani=0.98,
    )
    kararlar = ozellikten_kararlar_uret(sakin)

    assert len(kararlar) == 1
    assert kararlar[0].tip is KararTipi.FINANS_AKSIYON_YOK


def test_tekil_surum_birincil_karari_donduruyor():
    """`ozellikten_karar_uret` hâlâ çalışmalı — HTTP ucu tek karar döndürüyor."""
    from app.domain.finance.decide import ozellikten_karar_uret, ozellikten_kararlar_uret

    ornek = oz(en_eski_gecikme_gun=250, vadesi_gecen_tl=80_000.0)
    # Nesne eşitliği aranmıyor: `karar_id` her çağrıda yeni bir UUID.
    tekil, ilk = ozellikten_karar_uret(ornek), ozellikten_kararlar_uret(ornek)[0]
    assert tekil.tip is ilk.tip
    assert tekil.aksiyon == ilk.aksiyon


# --- Maddiyet kolu (§12) ------------------------------------------------------


def test_maddi_esik_is_maliyetinden_turetiliyor():
    """⭐ Eşik seçilmedi, türetildi: aramanın kendini ödediği nokta.

        eylem maliyeti = alacak x günlük finansman oranı x ufuk
        150 TL = X x (0,45/365) x 30  →  X ≈ 4.056 TL

    Bu test formülü kilitliyor. Sabitlerden biri değişirse eşik
    kendiliğinden kayar — elle güncellenmesi gereken bir sayı olmamalı.
    """
    from app.domain.finance.rules import (
        MADDI_TAKIP_ESIGI_TL,
        MADDI_TAKIP_UFKU_GUN,
        TAKIP_EYLEM_MALIYETI_TL,
        YILLIK_FINANSMAN_ORANI,
    )

    beklenen = TAKIP_EYLEM_MALIYETI_TL / (YILLIK_FINANSMAN_ORANI / 365.0 * MADDI_TAKIP_UFKU_GUN)
    assert beklenen == MADDI_TAKIP_ESIGI_TL
    assert 3_500 < MADDI_TAKIP_ESIGI_TL < 4_500


def test_buyuk_alacak_anomali_olmasa_da_takibe_giriyor():
    """A1'in bulduğu boşluk: sıradan görünen büyük alacak atlanıyordu."""
    from app.domain.finance.rules import takip_gerekcesi

    # Gecikme eşiğin ALTINDA (bu müşteri için olağan) ama tutar büyük.
    buyuk_ama_siradan = oz(en_eski_gecikme_gun=20, vadesi_gecen_tl=250_000.0)
    d = takip_gerekcesi(buyuk_ama_siradan, takip_esigi=40.0)

    assert not d["anomali"], "gecikme eşiğin altında — anomali değil"
    assert d["maddiyet"]
    assert d["gerekli"]


def test_kucuk_alacak_maddiyetten_gecmiyor():
    """Eşiğin altındaki alacağı aramak, aramanın maliyetini çıkarmıyor."""
    from app.domain.finance.rules import takip_gerekcesi

    kucuk = oz(en_eski_gecikme_gun=20, vadesi_gecen_tl=500.0)
    d = takip_gerekcesi(kucuk, takip_esigi=40.0)

    assert not d["maddiyet"]
    assert not d["gerekli"]


def test_yeni_gecikmede_maddiyet_kolu_beklemede():
    """Vadesi dün dolmuş büyük faturayı aramak müşteriyi rahatsız eder;
    kol "büyük ve gecikmiş" diyor, sadece "büyük" demiyor."""
    from app.domain.finance.rules import takip_gerekcesi

    yeni = oz(en_eski_gecikme_gun=2, vadesi_gecen_tl=250_000.0)
    assert not takip_gerekcesi(yeni, takip_esigi=40.0)["gerekli"]


def test_anomali_kolu_kucuk_tutarda_da_calisiyor():
    """İki kol ortogonal: maddiyet eklendi diye anomali kolu susmamalı."""
    from app.domain.finance.rules import takip_gerekcesi

    sapan = oz(en_eski_gecikme_gun=90, vadesi_gecen_tl=800.0)
    d = takip_gerekcesi(sapan, takip_esigi=40.0)

    assert d["anomali"]
    assert not d["maddiyet"]
    assert d["gerekli"]
