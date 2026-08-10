"""Gecelik tam tarama. Karar üretimi senkron+hızlı, gerekçe kuyruklu+tembel.

Sahip: Kişi B · Faz 2 B2.6

    uv run python -m app.jobs.nightly

**Hedef: 2.000 SKU < 10 dakika.**

Bu hedef mimarinin ikinci kuralının doğrudan sonucu. Naif tasarım şöyle
olurdu: her SKU için karar üret, her karar için gerekçe yaz. 2.000 × ~9 sn =
**5 saat.** Onun yerine:

1. **Tüm SKU'lar için karar üretilir** — kural motoru, milisaniyeler.
2. Kararlar **önem sırasına** dizilir (risk skoru).
3. Gerekçe **yalnızca üst N** karar için yazılır
   (`config.gecelik_gerekce_ust_n`, varsayılan 25).

Geri kalan kararlar gerekçesiz kaydedilir; `Gerekce` alanı `None` kalır ve
denetim kaydına `GuardSonucu.ATLANDI` yazılır. Bu bir eksiklik değil, tasarım:
insan zaten ilk 25'e bakıyor.

`KosuOzeti` karar süresiyle gerekçe süresini **ayrı** raporlar — mimarinin
"karar hızlı, gerekçe yavaş" iddiası ancak ölçülürse doğrulanabilir.

CLI (`_cli()`) gerçek üreteçleri kullanır (`_gercek_karar_ureteci` +
`llm_gerekce_ureteci`); `gecelik_tarama()`'nın kendi varsayılanları
(`_stub_ureteci`, `explain_stub`) bilinçli olarak stub kalır — testler ve
Ollama'sız ortamlar bu sayede çalışır kalıyor (bkz. `gecelik_tarama`
docstring'i).
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import (
    Alan,
    DecisionCandidate,
    Gerekce,
    KararTipi,
    PolitikaKarari,
    PolitikaSonucu,
)
from app.core.audit import denetim_yaz, karari_kaydet
from app.core.config import Ayarlar, ayarlar
from app.core.db import motor, oturum_fabrikasi
from app.core.policy import PolitikaEsikleri, esikleri_yukle, politika_uygula
from app.domain.stock.decide import (
    _demo_dunyasini_yukle,
    _siniflandirmayi_hesapla,
    decide_stub,
    ozellikten_karar_uret,
)
from app.domain.stock.features import katalog_ozelliklerini_hesapla
from app.llm.client import OllamaIstemcisi
from app.llm.explain import explain_stub, llm_gerekce_ureteci
from app.models import Approval, Decision, Insight

KararUreteci = Callable[[], Iterable[DecisionCandidate]]
GerekceUreteci = Callable[[DecisionCandidate], Gerekce]


@dataclass
class KosuOzeti:
    """Bir gecelik koşunun sonucu.

    Süreler bilinçli olarak ayrı: mimarinin "karar milisaniyelerde çıkar,
    gerekçe saniyeler sürer" iddiası ancak bu ikisi ayrı ölçülürse
    doğrulanabilir. Tek bir toplam süre bu ayrımı gizlerdi.
    """

    kosu_id: UUID
    taranan: int = 0
    kuyruga_giren: int = 0
    gerekce_uretilen: int = 0
    gerekce_atlanan: int = 0
    icgoru_yazilan: int = 0
    karar_sn: float = 0.0
    gerekce_sn: float = 0.0

    @property
    def toplam_sn(self) -> float:
        return self.karar_sn + self.gerekce_sn

    def ozet(self) -> str:
        karar_hizi = self.taranan / self.karar_sn if self.karar_sn else 0.0
        return (
            f"koşu {self.kosu_id}\n"
            f"  taranan SKU        : {self.taranan:,}\n"
            f"  kuyruğa giren      : {self.kuyruga_giren:,}\n"
            f"  gerekçe üretilen   : {self.gerekce_uretilen}\n"
            f"  gerekçe atlanan    : {self.gerekce_atlanan:,}\n"
            f"  içgörü yazılan     : {self.icgoru_yazilan}\n"
            f"  karar süresi       : {self.karar_sn:.1f} sn  ({karar_hizi:,.0f} karar/sn)\n"
            f"  gerekçe süresi     : {self.gerekce_sn:.1f} sn\n"
            f"  TOPLAM             : {self.toplam_sn:.1f} sn"
        )


logger = logging.getLogger(__name__)


def _stub_ureteci() -> Iterable[DecisionCandidate]:
    """`gecelik_tarama()`'nın varsayılanı — testler ve Ollama'sız ortamlar için."""
    return [decide_stub()]


def _gercek_karar_ureteci() -> Iterable[DecisionCandidate]:
    """Tüm katalog için gerçek karar üretir — `_cli()`'nin kullandığı üreteç.

    `katalog_ozelliklerini_hesapla` vektörize (`training/build_dataset.py`
    ile aynı desen): 2.000 SKU için tek toplu çağrı, SKU başına ayrı sorgu
    değil. 10 dakikalık bütçe bu sayede korunuyor.
    """
    dunya = _demo_dunyasini_yukle()
    siniflandirma = _siniflandirmayi_hesapla(dunya)
    ozellikler = katalog_ozelliklerini_hesapla(
        olcum_tarihi=dunya["olcum_tarihi"],
        talep=dunya["talep"],
        envanter_gunluk=dunya["envanter_gunluk"],
        sku_df=dunya["sku"],
        tedarikci_df=dunya["tedarikci"],
        siniflandirma=siniflandirma,
    )
    kararlar = [ozellikten_karar_uret(o) for o in ozellikler]

    # ⚠️ Faz 6: finans kararları da aynı taramaya giriyor.
    #
    # Ayrı bir gecelik iş açmak yerine tek taramada birleştirildi, çünkü
    # kullanıcı sabah **tek bir liste** görmek istiyor: "bugün neye bakmam
    # lazım?" sorusunun cevabı alan başına bölünmemeli.
    #
    # Sıralama zaten risk skoruna göre yapılıyor (`gecelik_tarama`), yani
    # 200.000 TL'lik bir tahsilat riski 500 TL'lik bir sipariş önerisinin
    # üstünde çıkıyor — alanlar arası önceliklendirme kendiliğinden doğru.
    kararlar.extend(_finans_kararlari())
    return kararlar


def _finans_kararlari() -> list[DecisionCandidate]:
    """Demo dünyasındaki tüm müşteriler için tahsilat kararları.

    Hata durumunda **boş liste** dönüyor: finans tarafındaki bir sorun
    gecelik taramanın tamamını düşürmemeli. Stok kararları kullanıcıya
    ulaşmaya devam eder ve eksiklik log'dan görülür.
    """
    try:
        from app.domain.finance.decide import _demo_ozellikleri, ozellikten_kararlar_uret

        # ⚠️ Çoğul: bir müşteri aynı anda hem karşılık hem takip
        # gerektirebilir (bkz. `finance/decide.py` modül docstring'i).
        # Tekil sürüm kullanılsaydı batık müşterinin takip kararı kuyruğa
        # hiç girmezdi.
        return [k for o in _demo_ozellikleri() for k in ozellikten_kararlar_uret(o)]
    except Exception:  # gecelik iş hiçbir koşulda düşmemeli
        logger.exception("Finans kararları üretilemedi; tarama stokla devam ediyor.")
        return []


class _EsikOnbellegi:
    """Karar tipi başına eşikleri bir kez okur.

    ⚠️ Bu önbellek olmadan `esikleri_yukle()` her SKU için ayrı bir SELECT
    atardı — 2.000 SKU = 2.000 sorgu. Karar tipi yalnızca 4 tane olduğu için
    tamamı 4 sorguya iniyor. 10 dakikalık bütçenin korunmasında en ucuz
    kazanç bu.
    """

    def __init__(self, oturum: Session, ayar: Ayarlar) -> None:
        self._oturum = oturum
        self._ayar = ayar
        self._kayit: dict[KararTipi, PolitikaEsikleri] = {}

    def al(self, tip: KararTipi) -> PolitikaEsikleri:
        if tip not in self._kayit:
            self._kayit[tip] = esikleri_yukle(self._oturum, tip, self._ayar)
        return self._kayit[tip]


def _icgoru_basligi(aday: DecisionCandidate, politika: PolitikaKarari) -> str:
    """Gecelik özet satırının başlığı.

    ⚠️ Ad **`gorunen_ad` üzerinden** alınıyor. Faz 6'ya kadar burada doğrudan
    `o.sku_adi` yazıyordu; finans kararı gecelik taramaya girdiği anda
    `AttributeError` verecekti — ve bu, gecelik işin tamamını düşürürdü.
    """
    o = aday.ozellikler
    ad = o.gorunen_ad

    if aday.tip is KararTipi.STOK_SIPARIS:
        return f"{ad}: {aday.aksiyon.get('siparis_miktari')} adet sipariş önerisi"
    if aday.tip is KararTipi.STOK_TASFIYE:
        return f"{ad}: tasfiye önerisi ({o.son_hareket_gun_once} gündür hareketsiz)"
    if aday.tip is KararTipi.STOK_TEDARIKCI_DEGISIM:
        return f"{ad}: tedarikçi değişimi önerisi"

    if aday.tip is KararTipi.FINANS_TAHSILAT_TAKIBI:
        return f"{ad}: {o.en_eski_gecikme_gun} gündür gecikmede, tahsilat takibi"
    if aday.tip is KararTipi.FINANS_KARSILIK_AYIR:
        oran = aday.aksiyon.get("onerilen_karsilik_orani") or 0
        return f"{ad}: %{float(oran) * 100:.0f} karşılık önerisi"
    if aday.tip is KararTipi.FINANS_KREDI_LIMITI_DUSUR:
        return f"{ad}: kredi limiti düşürme önerisi"

    return f"{ad}: {aday.tip.value}"


def gecelik_tarama(
    oturum: Session,
    ayar: Ayarlar | None = None,
    *,
    karar_ureteci: KararUreteci = _stub_ureteci,
    gerekce_ureteci: GerekceUreteci = explain_stub,
    gerekce_ust_n: int | None = None,
) -> KosuOzeti:
    """Tüm SKU'ları tarar, kararları kaydeder, üst N için gerekçe üretir.

    `gerekce_ureteci` **varsayılanı bilinçli olarak şablon**. Gerçek üreteç
    B2.4'te geldi ve imza aynı kaldı; kullanmak için çağıran taraf geçirir:

        gecelik_tarama(oturum, gerekce_ureteci=llm_gerekce_ureteci(istemci))

    Varsayılanı şablon bırakmanın sebebi, testlerin ve modelsiz ortamların
    çalışır kalması. Gerçek üreteci varsayılan yapmak, Ollama kurulu olmayan
    her yerde gecelik işi 25 kez bağlantı hatasına sokardı — sonuç yine
    şablon olurdu ama boşuna beklenerek.

    `commit()` iki kez atılıyor: kararlar yazıldıktan sonra bir kez, gerekçeler
    yazıldıktan sonra bir kez. Sebebi: gerekçe üretimi dakikalar sürebilir ve o
    süre boyunca kararların görünmez kalması istenmiyor. Karar yolu gerekçeyi
    beklemiyor — bu mimarinin ikinci kuralı, burada da geçerli.
    """
    ayar = ayar or ayarlar()
    ust_n = gerekce_ust_n if gerekce_ust_n is not None else ayar.gecelik_gerekce_ust_n
    ozet = KosuOzeti(kosu_id=uuid4())
    esikler = _EsikOnbellegi(oturum, ayar)

    # --- 1. Kararlar: hızlı yol, LLM'e hiç dokunulmuyor ---------------------
    baslangic = time.perf_counter()
    yazilan_kimlikler: list[UUID] = []

    for aday in karar_ureteci():
        politika = politika_uygula(aday, ayar, esikler.al(aday.tip))
        karari_kaydet(oturum, aday, politika)
        yazilan_kimlikler.append(aday.karar_id)
        ozet.taranan += 1

        if politika.sonuc is PolitikaSonucu.ONAY_KUYRUGU:
            oturum.add(Approval(karar_id=aday.karar_id))
            ozet.kuyruga_giren += 1

    oturum.commit()
    ozet.karar_sn = time.perf_counter() - baslangic

    # --- 2. Gerekçe: yavaş yol, yalnızca üst N ------------------------------
    baslangic = time.perf_counter()

    onemliler = oturum.scalars(
        select(Decision)
        .where(Decision.karar_id.in_(yazilan_kimlikler))
        .order_by(Decision.risk_skoru.desc())
        .limit(ust_n)
    ).all()
    ozet.gerekce_atlanan = ozet.taranan - len(onemliler)

    for karar in onemliler:
        aday = karar.adaya_cevir()
        politika = karar.politikaya_cevir()
        gerekce = gerekce_ureteci(aday)

        karar.gerekce_metni = gerekce.metin
        karar.guard_sonucu = gerekce.guard_sonucu
        karar.llm_model_adi = gerekce.model_adi
        karar.gerekce_uretim_ms = gerekce.uretim_ms
        ozet.gerekce_uretilen += 1

        # Gerekçe üretimi ayrı bir olay — ilk denetim satırının üstüne
        # yazılmıyor, yenisi ekleniyor.
        denetim_yaz(oturum, aday, politika, gerekce)

        oturum.add(
            Insight(
                kosu_id=ozet.kosu_id,
                alan=aday.alan,
                baslik=_icgoru_basligi(aday, politika),
                metin=gerekce.metin,
                onem_skoru=karar.risk_skoru,
                karar_id=karar.karar_id,
            )
        )
        ozet.icgoru_yazilan += 1

    # Toplu özet: tek bir karara ait değil, bu yüzden `karar_id` boş.
    oturum.add(
        Insight(
            kosu_id=ozet.kosu_id,
            alan=Alan.STOK,
            baslik=f"Gecelik tarama: {ozet.taranan} SKU, {ozet.kuyruga_giren} karar onay bekliyor",
            metin=(
                f"{ozet.taranan} SKU tarandı. {ozet.kuyruga_giren} karar onay kuyruğuna "
                f"girdi. En önemli {ozet.gerekce_uretilen} karar için gerekçe üretildi, "
                f"{ozet.gerekce_atlanan} karar gerekçesiz kaydedildi."
            ),
            # Toplu özet listenin en üstünde kalsın; tekil içgörülerin skoru
            # risk skoru olduğu için sonlu, bu bilinçli olarak onların üstünde.
            onem_skoru=float("inf"),
        )
    )
    ozet.icgoru_yazilan += 1

    oturum.commit()
    ozet.gerekce_sn = time.perf_counter() - baslangic
    return ozet


def _cli() -> None:
    ayristirici = argparse.ArgumentParser(description="Gecelik tam tarama")
    ayristirici.add_argument(
        "--ust-n", type=int, default=None, help="Kaç karar için gerekçe üretilsin"
    )
    args = ayristirici.parse_args()

    ayar = ayarlar()
    with oturum_fabrikasi()() as oturum, OllamaIstemcisi(ayar=ayar) as istemci:
        ozet = gecelik_tarama(
            oturum,
            ayar,
            karar_ureteci=_gercek_karar_ureteci,
            gerekce_ureteci=llm_gerekce_ureteci(istemci),
            gerekce_ust_n=args.ust_n,
        )

    print(ozet.ozet())
    if ozet.toplam_sn > 600:
        print("\n⚠️ 10 dakika hedefi aşıldı.")
    motor().dispose()


if __name__ == "__main__":
    _cli()
