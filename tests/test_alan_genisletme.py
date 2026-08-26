"""Faz 6 · Sözleşmenin ikinci bir iş alanını taşıdığının kanıtı.

Faz 1-5 boyunca yalnızca stok vardı ve alan-bağımsız katmanlar (guard,
politika, gerekçe) doğrudan `StockFeatures` alanlarını okuyordu. Bu testler
o sızıntıların kapandığını ve `FinansOzellikleri`'nin **hiçbir stok koduna
dokunmadan** aynı hattan geçtiğini doğruluyor.

⚠️ Asıl değerleri şu: yeni bir alan (satış, üretim) eklendiğinde bu
dosyadaki testler o alan için kopyalanabilir ve neyin sağlanması gerektiği
kendiliğinden belli olur.
"""

from __future__ import annotations

import datetime as dt

from app.contracts import (
    ABCSinifi,
    Alan,
    AlanOzellikleri,
    DecisionCandidate,
    FinansOzellikleri,
    KararTipi,
    StockFeatures,
    XYZSinifi,
)


def _finans_ozellikleri(**degisiklikler) -> FinansOzellikleri:
    varsayilan = {
        "musteri_id": "M-0042",
        "musteri_adi": "Yılmaz İnşaat 34 Ltd.",
        "segment": "müteahhit",
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


def _finans_adayi(**degisiklikler) -> DecisionCandidate:
    ozellikler = degisiklikler.pop("ozellikler", None) or _finans_ozellikleri()
    varsayilan = {
        "alan": Alan.FINANS,
        "tip": KararTipi.FINANS_TAHSILAT_TAKIBI,
        "aksiyon": {"takip_edilecek_tutar_tl": 95_000.0, "gecikme_gun": 62},
        "tahmini_tutar_tl": 95_000.0,
        "geri_alinabilir": True,
        "guven": 0.82,
        "ozellikler": ozellikler,
        "model_surumleri": {"rules": "0.1-finans"},
    }
    return DecisionCandidate(**{**varsayilan, **degisiklikler})


# --- Sözleşme ikinci alanı kabul ediyor mu ------------------------------------


def test_karar_adayi_finans_ozellikleri_kabul_ediyor():
    """⭐ Faz 6'yı engelleyen tam bu satırdı: `ozellikler: StockFeatures`."""
    aday = _finans_adayi()

    assert isinstance(aday.ozellikler, FinansOzellikleri)
    assert aday.alan is Alan.FINANS


def test_pydantic_gercek_tipi_koruyor():
    """Birleşim tipinde alt sınıf alanları kırpılmamalı.

    Pydantic "smart" birleşimde örneğin gerçek tipini korur; sol taraftaki
    tipe zorlasaydı finans alanları sessizce kaybolurdu.
    """
    aday = _finans_adayi()

    assert aday.ozellikler.musteri_adi == "Yılmaz İnşaat 34 Ltd."
    assert not hasattr(aday.ozellikler, "sku_id")


def test_iki_alan_da_taban_sinifi_uyguluyor():
    assert issubclass(StockFeatures, AlanOzellikleri)
    assert issubclass(FinansOzellikleri, AlanOzellikleri)


# --- Alan-bağımsız katmanlar stok bilmeden çalışıyor mu -----------------------


def test_guard_maskesi_finansta_musteri_adini_siliyor():
    """Guard, hangi alanları sileceğini özellik sınıfından öğreniyor.

    Önceden `o.sku_adi, o.tedarikci_adi` diye yazılıydı — finans
    özellikleriyle `AttributeError` verirdi.
    """
    from app.llm.guard import maskelenecek_alanlar, metni_maskele

    aday = _finans_adayi()
    alanlar = maskelenecek_alanlar(aday)

    assert "Yılmaz İnşaat 34 Ltd." in alanlar
    # Ad içindeki "34" veri değil; maskelenmezse guard onu uydurma sayar.
    temiz = metni_maskele("Yılmaz İnşaat 34 Ltd. 95.000 TL borçlu.", alanlar)
    assert "34" not in temiz
    assert "95.000" in temiz


def test_guard_finans_gerekcesini_geciriyor():
    """Uçtan uca: finans gerekçesindeki sayılar izinli kümeden geliyor mu."""
    from app.llm.guard import adayi_dogrula

    aday = _finans_adayi()
    metin = (
        "Yılmaz İnşaat 34 Ltd. müşterisinin 95.000,00 TL tutarındaki alacağı "
        "62 gündür gecikmede; tahsilat takibi öneriliyor."
    )

    assert adayi_dogrula(metin, aday).gecti


def test_guard_finansta_uydurma_sayiyi_yakaliyor():
    from app.llm.guard import adayi_dogrula

    aday = _finans_adayi()
    sonuc = adayi_dogrula("Müşteri 777.777 TL borçlu.", aday)

    assert not sonuc.gecti
    assert 777777.0 in sonuc.reddedilen


# --- Hesaplanan sayılar -------------------------------------------------------


def test_finans_hesaplanan_sayilari_izinli_kumede():
    """`limit_asimi_tl` gibi türetilmiş sayılar `model_dump()`'ta yok.

    Alan kendisi bildirmezse model onları gerekçede kullanamaz.
    """
    aday = _finans_adayi()
    izinli = aday.izinli_sayilar()

    # 250.000 alacak − 200.000 limit = 50.000 aşım
    assert 50_000.0 in izinli
    # vadesi_gecen_orani = 95.000 / 250.000 = 0,38 → "%38" de yazılabilmeli.
    # ⚠️ `pytest.approx` küme üyeliğinde kullanılamaz (hashlenemez); kayan
    # nokta payı elle veriliyor — 0,38 × 100 tam 38,0 çıkmayabilir.
    assert any(abs(x - 38.0) < 1e-6 for x in izinli), "yüzde karşılığı izinli olmalı"


def test_limit_asimi_yoksa_sifir():
    ozellikler = _finans_ozellikleri(toplam_alacak_tl=100_000.0, kredi_limiti_tl=200_000.0)

    assert ozellikler.limit_asimi_tl == 0.0


def test_gecikme_varyasyon_katsayisi_stoktakiyle_ayni_formul():
    """XYZ sınıflandırması alan değiştirince yeniden yazılmadı — kanıtı bu."""
    ozellikler = _finans_ozellikleri(ort_odeme_gecikmesi_gun=20.0, odeme_gecikmesi_std=5.0)

    assert ozellikler.gecikme_varyasyon_katsayisi == 0.25

    gecikmesiz = _finans_ozellikleri(ort_odeme_gecikmesi_gun=0.0, odeme_gecikmesi_std=0.0)
    assert gecikmesiz.gecikme_varyasyon_katsayisi == 0.0


# --- Politika -----------------------------------------------------------------


def test_finans_aksiyon_yok_oto_uygulanmiyor():
    """⚠️ En sinsi hata buydu.

    Politika `aday.tip is KararTipi.STOK_AKSIYON_YOK` diye soruyordu;
    `finans.aksiyon_yok` o daldan geçemez ve "yapılacak bir şey yok" kararı
    oto-uygulama yoluna girerdi.
    """
    from app.contracts import PolitikaSonucu
    from app.core.config import Ayarlar
    from app.core.policy import politika_uygula

    aday = _finans_adayi(tip=KararTipi.FINANS_AKSIYON_YOK, tahmini_tutar_tl=0.0)
    karar = politika_uygula(aday, Ayarlar(ollama_base_url="http://sahte:11434"))

    assert karar.sonuc is PolitikaSonucu.AKSIYON_YOK


def test_aksiyon_yok_mu_her_alanda_calisiyor():
    assert KararTipi.STOK_AKSIYON_YOK.aksiyon_yok_mu
    assert KararTipi.FINANS_AKSIYON_YOK.aksiyon_yok_mu
    assert not KararTipi.STOK_SIPARIS.aksiyon_yok_mu
    assert not KararTipi.FINANS_TAHSILAT_TAKIBI.aksiyon_yok_mu


def test_kredi_onaysiz_musteri_onay_kuyruguna_gidiyor():
    """Stoktaki "tedarikçi onaysız" kuralının finanstaki karşılığı."""
    from app.contracts import PolitikaSonucu
    from app.core.config import Ayarlar
    from app.core.policy import politika_uygula

    aday = _finans_adayi(
        ozellikler=_finans_ozellikleri(musteri_kredi_onayli=False),
        tahmini_tutar_tl=10.0,
        guven=0.99,
    )
    karar = politika_uygula(aday, Ayarlar(ollama_base_url="http://sahte:11434"))

    assert karar.sonuc is PolitikaSonucu.ONAY_KUYRUGU
    assert "MUSTERI_KREDI_ONAYSIZ" in karar.gerekce_kodlari


def test_stok_engeli_bozulmadi():
    """Genelleme eskiyi kırmamalı."""
    from app.domain.stock.decide import decide_stub

    aday = decide_stub()
    onaysiz = aday.model_copy(
        update={"ozellikler": aday.ozellikler.model_copy(update={"tedarikci_onayli": False})}
    )

    assert aday.ozellikler.oto_uygulama_engeli() is None
    assert onaysiz.ozellikler.oto_uygulama_engeli() == "TEDARIKCI_ONAYSIZ"


# --- Tip/alan tutarlılığı -----------------------------------------------------


def test_karar_tipi_alanini_biliyor():
    assert KararTipi.STOK_SIPARIS.alan == "stok"
    assert KararTipi.FINANS_KARSILIK_AYIR.alan == "finans"


def test_her_karar_tipi_tanimli_bir_alana_ait():
    """Yeni tip eklenirken `Alan` enum'ına eklemeyi unutmayı yakalar."""
    alanlar = {a.value for a in Alan}

    for tip in KararTipi:
        assert tip.alan in alanlar, f"{tip.value} tanımsız alana ait"


# ---------------------------------------------------------------------------
# A2 — Stok karar önceliği incelemesi (Faz 8)
# ---------------------------------------------------------------------------


def _stok_ozelligi(**degisiklikler) -> StockFeatures:
    """Sağlıklı, hızlı dönen bir SKU. Testler yalnızca ilgilendikleri alanı ezer."""
    varsayilan = {
        "sku_id": "SKU-0001",
        "sku_adi": "Kırmızı Tuğla 19x9x5",
        "kategori": "tugla",
        "eldeki_stok": 400,
        "rezerve_stok": 0,
        "yoldaki_stok": 0,
        "ort_gunluk_talep": 8.0,
        "talep_std": 2.0,
        "veri_gun_sayisi": 365,
        "tedarik_suresi_gun": 7.0,
        "tedarik_suresi_std": 2.0,
        "abc_sinifi": ABCSinifi.A,
        "xyz_sinifi": XYZSinifi.X,
        "hedef_servis_seviyesi": 0.95,
        "son_hareket_gun_once": 1,
        "raf_omru_kalan_gun": None,
        "birim_maliyet_tl": 12.0,
        "satis_fiyati_tl": 18.0,
        "tedarikci_id": "T-014",
        "tedarikci_adi": "Anadolu Yapi",
        "tedarikci_skoru": 80.0,
        "tedarikci_zamaninda_teslim_orani": 0.93,
        "tedarikci_onayli": True,
        "moq": 100,
        "paket_adedi": 50,
        "olcum_tarihi": dt.date(2026, 8, 10),
    }
    return StockFeatures(**{**varsayilan, **degisiklikler})


def test_stok_olu_esigi_yalnizca_yukari_cikar():
    """⭐ Finanstaki kusurun stok karşılığı YOK — ve sebebi tek bir kelime.

    `rules._olu_stok_esigi` `max(mutlak, göreceli)` kullanıyor: eşik hiçbir
    zaman 90 günün altına inemez. Finansta aynı satır `min(...)` yazılmıştı
    ve hızlı ödeyen bir müşterinin 40 günlük alacağı için karşılık
    ayrılıyordu (`BILINEN-EKSIKLER.md` §9).

    Bu test yönü kilitliyor: `min`'e dönerse kırılır.
    """
    from app.domain.stock.rules import OLU_STOK_MUTLAK_ESIK_GUN, _olu_stok_esigi

    # Günde 10 birim satan hızlı ürün: göreceli eşik 6/10 = 0,6 gün.
    hizli = _olu_stok_esigi(ort_gunluk_talep=10.0)
    # Günde 0,01 birim satan yavaş ürün: göreceli eşik 600 gün.
    yavas = _olu_stok_esigi(ort_gunluk_talep=0.01)

    assert hizli == OLU_STOK_MUTLAK_ESIK_GUN, "hızlı üründe eşik tabana oturmalı"
    assert yavas > OLU_STOK_MUTLAK_ESIK_GUN, "yavaş üründe eşik yukarı çıkmalı"


def test_stoksuzluk_olu_stok_sayilmiyor():
    """⭐ §11 düzeltildi: aç kalan ürün ölü ilan edilmiyor.

    Elde 2 birim kalmış, 120 gündür hareket yok — çünkü satacak mal yoktu.
    Geçmiş talep hâlâ yüksek (günde 8 birim), yani ürün ölü DEĞİL, aç.

    Düzeltme öncesi sistem tasfiye öneriyordu ve tasfiye siparişi
    bastırdığı için ürün bir daha hiç hareket etmiyordu — teşhis kendi
    kendini doğruluyordu. Artık ölü stok iddiası ancak **satılabilecek
    kadar mal varken** kurulabiliyor (`rules.OLU_STOK_ASGARI_STOK_GUN`).

    Beklenen: tasfiye değil SİPARİŞ — ürün ölü değil, aç.
    """
    from app.contracts import KararTipi
    from app.domain.stock.decide import ozellikten_karar_uret

    ac_kalmis = _stok_ozelligi(
        eldeki_stok=2,
        rezerve_stok=0,
        yoldaki_stok=0,
        ort_gunluk_talep=8.0,
        talep_std=2.0,
        son_hareket_gun_once=120,
        veri_gun_sayisi=365,
    )
    karar = ozellikten_karar_uret(ac_kalmis)

    assert karar.tip is KararTipi.STOK_SIPARIS, (
        "aç kalan ürün yeniden sipariş edilmeli, tasfiye edilmemeli"
    )


def test_gercek_olu_stok_hala_tasfiye_ediliyor():
    """Düzeltme fazla ileri gitmemeli: talebi bitmiş ürün hâlâ ölü.

    Elde 400 birim var, 200 gündür hareket yok, günlük talep 0,1 (göreli
    eşik 90 güne oturuyor). Burada "satacak mal yoktu" mazereti geçersiz —
    mal duruyor, alan yok.

    ⚠️ İlk yazımda talep 0,01 verilmişti ve test kırıldı: göreli eşik
    6/0,01 = 600 güne çıkıyor, 200 gün yetmiyor. Kod doğruydu, test yanlıştı
    — çok yavaş satan bir ürün için 200 gün sessizlik gerçekten normal.
    """
    from app.contracts import KararTipi
    from app.domain.stock.decide import ozellikten_karar_uret

    gercekten_olu = _stok_ozelligi(
        eldeki_stok=400,
        ort_gunluk_talep=0.1,
        talep_std=0.05,
        son_hareket_gun_once=200,
        veri_gun_sayisi=365,
    )
    assert ozellikten_karar_uret(gercekten_olu).tip is KararTipi.STOK_TASFIYE


def test_tedarikci_degisim_artik_uretiliyor():
    """§5 kapanıyor: tanımlı ama ölü olan karar tipi artık tetikleniyor."""
    from app.domain.stock.decide import ozellikten_kararlar_uret

    kotu_tedarikci = _stok_ozelligi(tedarikci_skoru=30.0, tedarikci_zamaninda_teslim_orani=0.55)
    tipler = {k.tip for k in ozellikten_kararlar_uret(kotu_tedarikci)}

    assert KararTipi.STOK_TEDARIKCI_DEGISIM in tipler


def test_tedarikci_degisimi_siparisi_bastirmiyor():
    """⭐ A2'nin bağlayıcı çıktısı: kol ORTOGONAL, `elif` zincirinde değil.

    Stoğu ROP'un altına düşmüş VE tedarikçisi kötü bir SKU iki karar birden
    almalı: mal sipariş edilmeli (bugünkü ihtiyaç) ve tedarikçi gözden
    geçirilmeli (yapısal sorun). Biri diğerini geçersiz kılmaz.
    """
    from app.domain.stock.decide import ozellikten_kararlar_uret

    hem_stoksuz_hem_kotu = _stok_ozelligi(
        eldeki_stok=5, tedarikci_skoru=30.0, tedarikci_zamaninda_teslim_orani=0.55
    )
    tipler = {k.tip for k in ozellikten_kararlar_uret(hem_stoksuz_hem_kotu)}

    assert tipler == {KararTipi.STOK_SIPARIS, KararTipi.STOK_TEDARIKCI_DEGISIM}


def test_az_veriyle_tedarikci_degisimi_onerilmiyor():
    """Finanstaki kusur buraya taşınmasın: kanıt yetersizken karşı taraf
    hakkında karar verilmez (`BILINEN-EKSIKLER.md` §8)."""
    from app.domain.stock.decide import ozellikten_kararlar_uret

    yeni_tedarikci = _stok_ozelligi(tedarikci_skoru=30.0, veri_gun_sayisi=60)
    tipler = {k.tip for k in ozellikten_kararlar_uret(yeni_tedarikci)}

    assert KararTipi.STOK_TEDARIKCI_DEGISIM not in tipler


def test_saglam_tedarikcide_ek_karar_yok():
    from app.domain.stock.decide import ozellikten_kararlar_uret

    kararlar = ozellikten_kararlar_uret(_stok_ozelligi())
    assert len(kararlar) == 1


def test_az_siparisli_tedarikcide_degisim_onerilmiyor():
    """⭐ Vekil ölçü gerçeğiyle değişti: asıl kapı sipariş sayısı.

    İki siparişten hesaplanan bir tedarikçi skoru gürültüdür. Talep geçmişi
    üç yıllık olsa bile, o tedarikçiyle iki kez çalışılmışsa hüküm verilemez.
    """
    from app.domain.stock.decide import ozellikten_kararlar_uret

    az_siparisli = _stok_ozelligi(
        tedarikci_skoru=30.0, veri_gun_sayisi=1000, tedarikci_siparis_sayisi=2
    )
    tipler = {k.tip for k in ozellikten_kararlar_uret(az_siparisli)}

    assert KararTipi.STOK_TEDARIKCI_DEGISIM not in tipler


def test_yeterli_siparisli_tedarikcide_degisim_oneriliyor():
    from app.domain.stock.decide import ozellikten_kararlar_uret

    cok_siparisli = _stok_ozelligi(
        tedarikci_skoru=30.0, veri_gun_sayisi=1000, tedarikci_siparis_sayisi=20
    )
    tipler = {k.tip for k in ozellikten_kararlar_uret(cok_siparisli)}

    assert KararTipi.STOK_TEDARIKCI_DEGISIM in tipler


def test_siparis_sayisi_bilinmiyorsa_vekil_olcuye_dusuluyor():
    """Alan 0 ise (veri kaynağı taşımıyor) kapı kapanmıyor, zayıflıyor."""
    from app.domain.stock.decide import ozellikten_kararlar_uret

    bilinmiyor = _stok_ozelligi(
        tedarikci_skoru=30.0, veri_gun_sayisi=1000, tedarikci_siparis_sayisi=0
    )
    tipler = {k.tip for k in ozellikten_kararlar_uret(bilinmiyor)}

    assert KararTipi.STOK_TEDARIKCI_DEGISIM in tipler


# ---------------------------------------------------------------------------
# B5 — Gerekçe katmanı finans kararını taşıyor mu
# ---------------------------------------------------------------------------


def _finans_adayi_ornek() -> DecisionCandidate:
    from app.domain.finance.decide import ozellikten_kararlar_uret

    ozellik = FinansOzellikleri(
        musteri_id="M-0042",
        musteri_adi="Yılmaz İnşaat Ltd.",
        segment="santiye",
        toplam_alacak_tl=250_000.0,
        vadesi_gecen_tl=95_000.0,
        en_eski_gecikme_gun=62,
        ort_odeme_gecikmesi_gun=18.5,
        odeme_gecikmesi_std=7.4,
        veri_gun_sayisi=540,
        kredi_limiti_tl=200_000.0,
        abc_sinifi=ABCSinifi.A,
        xyz_sinifi=XYZSinifi.Y,
        hedef_tahsilat_orani=0.95,
        son_odeme_gun_once=41,
        tahsilat_orani=0.88,
        musteri_kredi_onayli=True,
        olcum_tarihi=dt.date(2026, 8, 10),
    )
    return ozellikten_kararlar_uret(ozellik)[0]


def test_sablon_gerekce_finansta_cokmuyor():
    """🔴 B5'in bulduğu kusur: şablon `o.sku_adi` okuyordu.

    Şablona düşmek istisna değil normal akış — anlatacak sayısı olmayan her
    karar ve guard'ın reddettiği her gerekçe buraya geliyor. Finans kararı
    geldiğinde `AttributeError` veriyordu.
    """
    from app.llm.explain import sablon_gerekce

    metin = sablon_gerekce(_finans_adayi_ornek())

    assert "Yılmaz İnşaat" in metin
    assert "95.000" in metin or "95000" in metin.replace(".", "")


def test_egitilmis_istem_finansta_kurulabiliyor():
    """🔴 İkinci kusur: eğitilmiş istem `urun: {sku_adi}` yazıyordu.

    İstem kurulamadığı için model **hiç çağrılmıyordu** — "model finansı
    görmedi" tespitinin gerçek sebebi eğitim eksikliği değil, buydu.
    """
    from app.llm.explain import egitilmis_istem_govdesi

    govde = egitilmis_istem_govdesi(_finans_adayi_ornek())

    assert "musteri: Yılmaz İnşaat Ltd." in govde
    assert "urun:" not in govde


def test_stok_istem_bicimi_korunuyor():
    """⚠️ Stok etiketi BİREBİR aynı kalmalı: eğitilmiş kipin istemi
    eğitimdekiyle aynı olmak zorunda. Bir kelime kayarsa model tanımadığı
    bir girdi görür (OLCUMLER.md, 4./5. tur vakası)."""
    from app.domain.stock.decide import ozellikten_karar_uret
    from app.llm.explain import egitilmis_istem_govdesi

    govde = egitilmis_istem_govdesi(ozellikten_karar_uret(_stok_ozelligi(eldeki_stok=5)))

    assert govde.splitlines()[1].startswith("urun: ")


def test_finans_kararinda_anlatilacak_sayi_var():
    """`_TIPE_GORE_ALANLAR`'da finans tipleri yoktu; `anlatilacak_sayi_var_mi`
    her finans kararında False dönüyor ve LLM atlanıyordu."""
    from app.llm.explain import anlatilacak_sayi_var_mi, sayi_etiketleri

    aday = _finans_adayi_ornek()

    assert sayi_etiketleri(aday), "finans kararı için istem sayıları boş kalmamalı"
    assert anlatilacak_sayi_var_mi(aday)
