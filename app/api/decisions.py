"""Karar endpoint'leri.

Sahip: Kişi B · Faz 0.5 (stub) → Faz 1 B1.5 (DB'ye kayıt + kuyruk)
       → Faz 3 sonrası (SP2/#3): gerçek karar motoru + eğitilmiş model bağlandı

Bu dosya mimarinin ikinci temel kuralını hayata geçirir: ERP asla LLM'i
beklemez. Karar `stok_karari_uret()` çağrısından milisaniyelerde çıkar;
gerekçe `gerekce=True` istenmediği sürece hiç üretilmez. İstense bile
`gerekce_uret()` "hiçbir koşulda hata fırlatmaz" — LLM erişilemezse şablona
düşer, karar yolu bundan etkilenmez (bkz. `app/llm/guard.py`).

B1.5'te eklenen: karar artık DB'ye yazılıyor ve `ONAY_KUYRUGU` alan kararlar
onay kuyruğuna giriyor. Eşikler `policy` tablosundan okunuyor (B1.4).

Faz 6'da finans ucu eklendi. İki ucun gövdesi **aynı** — yalnızca karar
üreteci farklı — bu yüzden ortak akış `_karari_isle`'ye çıkarıldı. Kopyalansaydı
commit sıralamasındaki kritik kural (önce karar, sonra gerekçe) iki yerde
yaşar ve zamanla ayrışırdı.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.contracts import (
    DecisionCandidate,
    KararSonucu,
    OtonomiSeviyesi,
    PolitikaSonucu,
)
from app.core.audit import denetim_yaz, karari_kaydet
from app.core.config import Ayarlar, ayarlar
from app.core.db import OturumDep
from app.core.policy import esikleri_yukle, politika_uygula
from app.domain.finance.decide import _demo_ozellikleri, ozellikten_kararlar_uret
from app.domain.production.decide import uretim_kararlari_uret
from app.domain.stock.decide import stok_karari_uret
from app.llm.client import OllamaIstemcisi
from app.llm.explain import gerekce_uret
from app.models import Approval

router = APIRouter(prefix="/v1/decisions", tags=["kararlar"])

AyarDep = Annotated[Ayarlar, Depends(ayarlar)]


@router.post(
    "/stock/reorder-review",
    response_model=KararSonucu,
    summary="Stok yeniden sipariş değerlendirmesi",
)
def stok_siparis_degerlendir(
    ayar: AyarDep,
    oturum: OturumDep,
    gerekce: Annotated[
        bool,
        Query(
            description="Türkçe gerekçe metni de üretilsin mi? "
            "Varsayılan False — karar yolu LLM'i beklemesin diye."
        ),
    ] = False,
) -> KararSonucu:
    """Bir SKU için sipariş kararı üretir, kaydeder ve gerekiyorsa kuyruğa alır.

    `sku_id` verilmiyor: `stok_karari_uret(None)` demo dünyasında sipariş
    kararını tetikleyen ilk SKU'yu otomatik seçer (sabit `seed=42`, dolayısıyla
    çağrıdan çağrıya tutarlı).
    """
    _kapali_mi(ayar)
    return _karari_isle(stok_karari_uret(), ayar, oturum, gerekce)


def _kapali_mi(ayar: Ayarlar) -> None:
    """Kill switch — `AUTONOMY_LEVEL=off` ise hiç karar üretilmez."""
    if ayar.autonomy_level is OtonomiSeviyesi.OFF:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Karar motoru kapalı (AUTONOMY_LEVEL=off).",
        )


def _karari_isle(
    aday: DecisionCandidate, ayar: Ayarlar, oturum: OturumDep, gerekce: bool
) -> KararSonucu:
    """Tek karar isteyen uçlar için — `_kararlari_isle`'nin tekil sarmalayıcısı.

    ⚠️ Gövde bilinçli olarak **kopyalanmadı**. Commit sıralaması (önce karar,
    sonra gerekçe) mimarinin ikinci kuralının veri katmanındaki karşılığı;
    iki yerde yaşasaydı biri güncellenip diğeri unutulurdu. Faz 6'da bu
    fonksiyon stok ucundan tam bu sebeple çıkarılmıştı — çoğullaşırken aynı
    hatayı tersinden yapmamak için tekil yol da çoğula bağlandı.
    """
    return _kararlari_isle([aday], ayar, oturum, gerekce)[0]


def _kararlari_isle(
    adaylar: list[DecisionCandidate], ayar: Ayarlar, oturum: OturumDep, gerekce: bool
) -> list[KararSonucu]:
    """Politika → kayıt → (istenirse) gerekçe. Alan bilmez, adet bilmez.

    ⚠️ **Tüm kararlar tek commit'te kalıcı olur, gerekçeler ikinci commit'te.**
    Karar başına ayrı ayrı `_karari_isle` çağırmak da çalışırdı ama sıralamayı
    bozardı: 3 kararlı bir müşteride 2. kararın gerekçesi üretilirken süreç
    ölse, 3. karar hiç yazılmamış olurdu. Oysa üçü de zaten üretilmişti.

    `nightly.py` de tam bu deseni kullanıyor (kararlar bir commit, gerekçeler
    ikinci) — çoğul yol oraya hizalandı.
    """
    # --- 1. Kararlar önce kalıcı olur ---------------------------------------
    #
    # ⚠️ Gerekçe üretimi bilinçli olarak BU COMMIT'TEN SONRA. Sıra ters
    # olsaydı (önce LLM, sonra kayıt) 6 saniyelik üretim penceresinde süreç
    # ölünce **karar tamamen kaybolurdu** — oysa karar zaten üretilmişti,
    # kaybedilecek bir şey yoktu.
    islenen = []
    for aday in adaylar:
        # Eşikler config'den değil `policy` tablosundan (B1.4). Satır yoksa
        # config'e düşer ve gerekçe kodlarında `ESIK_VARSAYILANA_DUSTU` görünür.
        esikler = esikleri_yukle(oturum, aday.tip, ayar)
        politika = politika_uygula(aday, ayar, esikler)
        karar, _ = karari_kaydet(oturum, aday, politika)

        # Kuyruğa YALNIZCA insan onayı bekleyen kararlar girer. Shadow modda
        # eşik altı kalan karar kaydedilir ama kuyruğa girmez — kimsenin
        # bakmayacağı kaydı insanın önüne koymak kuyruğu değersizleştirir.
        if politika.sonuc is PolitikaSonucu.ONAY_KUYRUGU:
            oturum.add(Approval(karar_id=aday.karar_id))

        islenen.append((aday, politika, karar))

    oturum.commit()

    # --- 2. Gerekçeler: istenirse, kararların üstüne -------------------------
    gerekceler: dict[int, object] = {}
    if gerekce:
        # Tek istemci, tüm kararlar için: her karar başına bağlantı kurmak
        # 3 kararlı bir müşteride üç kat kurulum maliyeti demek.
        with OllamaIstemcisi(ayar=ayar) as istemci:
            for i, (aday, _politika, karar) in enumerate(islenen):
                uretilen = gerekce_uret(aday, istemci)
                karar.gerekce_metni = uretilen.metin
                karar.guard_sonucu = uretilen.guard_sonucu
                karar.llm_model_adi = uretilen.model_adi
                karar.gerekce_uretim_ms = uretilen.uretim_ms
                gerekceler[i] = uretilen

        # Gerekçe üretimi ayrı bir olay — ilk denetim satırının üstüne
        # yazılmıyor, yenisi ekleniyor (`nightly.py` ile aynı).
        for i, (aday, politika, _karar) in enumerate(islenen):
            denetim_yaz(oturum, aday, politika, gerekceler[i])
        oturum.commit()

    return [
        KararSonucu(aday=aday, politika=politika, gerekce=gerekceler.get(i))
        for i, (aday, politika, _karar) in enumerate(islenen)
    ]


def _finans_adaylari(musteri_id: str | None) -> list[DecisionCandidate]:
    """Bir müşterinin **tüm** kararları.

    ⚠️ `app/domain/**` bu turda Kişi A'nın sahası; oraya çoğul bir giriş
    noktası eklenmedi. `nightly.py::_finans_kararlari` zaten aynı iki
    fonksiyonu bu şekilde çağırıyor — desen kopyalanmadı, hizalandı.

    Müşteri seçimi `finans_karari_uret`'in davranışını birebir koruyor:
    `musteri_id` verilmezse **aksiyon gerektiren** ilk müşteri, hiç yoksa ilk
    müşteri. Uç çoğullaştı ama hangi müşteriye baktığı değişmedi.
    """
    ozellikler = _demo_ozellikleri()
    if not ozellikler:
        raise ValueError("Demo dünyasında hiç müşteri yok.")

    if musteri_id is not None:
        secilen = next((o for o in ozellikler if o.musteri_id == musteri_id), None)
        if secilen is None:
            raise KeyError(f"Müşteri bulunamadı: {musteri_id}")
        return ozellikten_kararlar_uret(secilen)

    for ozellik in ozellikler:
        kararlar = ozellikten_kararlar_uret(ozellik)
        if any(not k.tip.aksiyon_yok_mu for k in kararlar):
            return kararlar
    return ozellikten_kararlar_uret(ozellikler[0])


@router.post(
    "/finance/collection-review",
    response_model=list[KararSonucu],
    summary="Tahsilat / alacak değerlendirmesi",
)
def finans_tahsilat_degerlendir(
    ayar: AyarDep,
    oturum: OturumDep,
    musteri_id: Annotated[
        str | None,
        Query(description="Belirli bir müşteri. Verilmezse aksiyon gerektiren ilk müşteri."),
    ] = None,
    gerekce: Annotated[
        bool,
        Query(
            description="Türkçe gerekçe metni de üretilsin mi? "
            "Varsayılan False — karar yolu LLM'i beklemesin diye."
        ),
    ] = False,
) -> list[KararSonucu]:
    """Bir müşterinin tahsilat kararlarını üretir, kaydeder, gerekiyorsa kuyruğa alır.

    ⚠️ **Bu uç bir LİSTE döndürür** (Tur 8 · B1). Önceden tek karar
    döndürüyordu ve bu bir kusurdu: bir müşteri aynı anda hem karşılık hem
    tahsilat takibi kararı alabilir (Faz 7, `BILINEN-EKSIKLER.md` §9). Kural
    motoru düzeltilmişti ama HTTP ucu hâlâ listenin yalnızca **birincisini**
    veriyordu — yani ERP, batık bir müşterinin karşılık kararını görüyor,
    aynı müşterinin takip kararını hiç görmüyordu.

    Sürüm kırılımı; ayrıntı `dokumantasyon/ERP-ENTEGRASYON.md`'de.

    Dört karar tipi olabilir: karşılık ayır, kredi limitini düşür, tahsilat
    takibi, aksiyon yok. Öncelik sırası `app/domain/finance/decide.py`'de.

    ⚠️ `karsilik_ayir` ve `kredi_limiti_dusur` **daima onay** gerektirir
    (`DAIMA_ONAY_GEREKTIREN`): ilki muhasebe kaydı, ikincisi müşteri
    ilişkisini etkileyen ticari karar.
    """
    _kapali_mi(ayar)
    try:
        adaylar = _finans_adaylari(musteri_id)
    except KeyError as hata:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(hata)) from hata
    return _kararlari_isle(adaylar, ayar, oturum, gerekce)


@router.post(
    "/production/order-review",
    response_model=list[KararSonucu],
    summary="Üretim emri değerlendirmesi",
)
def uretim_emri_degerlendir(
    ayar: AyarDep,
    oturum: OturumDep,
    kalem_id: Annotated[
        str | None,
        Query(description="Belirli bir üretilen kalem. Verilmezse tüm üretim kararları."),
    ] = None,
    gerekce: Annotated[
        bool,
        Query(
            description="Türkçe gerekçe metni de üretilsin mi? "
            "Varsayılan False — karar yolu LLM'i beklemesin diye."
        ),
    ] = False,
) -> list[KararSonucu]:
    """Üretim emri ve kapasite kararlarını üretir, kaydeder, gerekiyorsa kuyruğa alır.

    ⚠️ **Bu uç bir LİSTE döndürür** ve bu, tek kalem sorulduğunda bile
    geçerli: bir kalem aynı anda hem `uretim.emir_ac` hem
    `uretim.kapasite_asimi` kararı alabilir. İkisi ortogonal — biri "üret"
    diyor, diğeri "ama hat dolu, sıraya gir". Tekil dönen bir uç, ikincisini
    ERP'den gizlerdi; finansta tam bu kusur yaşandı (`BILINEN-EKSIKLER.md`
    §9, Tur 8 · B1).

    ⚠️ `kalem_id` verilse bile kapasite hesabı **tüm hat** üzerinden yapılır:
    "bu emir hattı aşıyor mu" sorusunun cevabı diğer emirlere bağlıdır.

    Dört karar tipi olabilir: emir aç, emir erteleme, kapasite aşımı,
    aksiyon yok.
    """
    _kapali_mi(ayar)
    try:
        adaylar = uretim_kararlari_uret(kalem_id)
    except KeyError as hata:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(hata)) from hata

    return _kararlari_isle(adaylar, ayar, oturum, gerekce)
