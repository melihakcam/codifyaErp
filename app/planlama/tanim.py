"""Alan tanımı okuyucu — "yeni alan = bir dosya, kod yok".

Sahip: Kişi A · Faz 11 A11.3

Bu dosya bir iddianın taşıyıcısı: yeni bir planlama alanı eklemek için kod
yazmak gerekmemeli. Araçlar/duraklar, kişiler/vardiyalar, makineler/işler —
hepsi aynı biçimde tarif edilip aynı motora veriliyor.

    {
      "ad": "Nakliye",
      "kapasite_birimi": "saat",
      "kaynaklar": [
        {"id": "KAYNAK-1", "ad": "Araç 1", "gunluk_kapasite": 9}
      ],
      "isler": [
        {"id": "IS-1", "ad": "Teslimat A", "yuk": 2.5,
         "oncelik": 1, "uygun_kaynaklar": ["KAYNAK-1"]}
      ]
    }

⚠️ **Eksik ya da yanlış alan yükleme anında patlar.** `IsletmeProfili.dosyadan`
ile aynı disiplin: `kapasite` yazıp `gunluk_kapasite` demeyi unutan bir tanım
sessizce varsayılanla çalışırsa kimse fark etmez ve plan yanlış çıkar. Yazım
hatası hata vermeli.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path
from typing import Any

from app.planlama.contracts import Is, Kaynak

# Zorunlu alanlar. Eksikse hata mesajı hangi satırda olduğunu söylüyor —
# 200 satırlık bir tanımda "bir yerde eksik alan var" demek yardım etmez.
KAYNAK_ZORUNLU = ("id", "ad", "gunluk_kapasite")
IS_ZORUNLU = ("id", "ad", "yuk", "oncelik")

# ⚠️ Üst seviye anahtarlar KAPALI küme — kayıtların içi (etiketler) açık.
# Ayrım bilinçli: kaydın içindeki "plaka", "musteri" alanın kendi dünyası ve
# taşınmalı; üst seviyede ise motorun davranışını değiştiren anahtarlar var
# ve oradaki bir yazım hatası sessizce varsayılana düşerse plan yanlış çıkar,
# kimse fark etmez. Faz 9'un dersi (`extra="forbid"`).
UST_ALANLAR = (
    "ad",
    "not",
    "aciklama",
    "kapasite_birimi",
    "kaynaklar",
    "isler",
    "isler_kaynagi",
    "adaptor",
    "parametreler",
)

ELLE = "elle"
TAHMIN = "tahmin"
ALAN_ONEKI = "alan:"


class TanimHatasi(ValueError):
    """Alan tanımı okunamadı. Mesaj hangi kayıtta ne eksik olduğunu söyler."""


@dataclass(frozen=True)
class IslerKaynagi:
    """İşlerin **nereden geldiği** — tanımda yazılı, kodda gizli değil.

    Faz 13'e kadar tek yol vardı: işler JSON'a elle yazılıyordu. "Önceki
    detaylara bakarak geleceğe göre" çalışabilmesi için işlerin geçmişten
    türeyebilmesi, bir alanın çıktısının başka bir alanın girdisi
    olabilmesi gerekiyor. Üç yol da burada:

        elle          -> isler JSON'da yazili (bugunku davranis, VARSAYILAN)
        tahmin        -> gecmisten tahminle uretilecek
        alan:<ad>     -> baska bir alanin ciktisi girdi olacak

    ⚠️ Zincir bağının **tanımda** durması bilinçli. Kodda gizli bir bağ,
    "bu plan nereden besleniyor" sorusunu kaynak okumadan cevaplanamaz
    yapardı; burada duran bağ okunabilir ve tek dosyayla değiştirilebilir.
    """

    kip: str = ELLE
    kaynak_alan: str | None = None

    def __post_init__(self) -> None:
        if self.kip not in (ELLE, TAHMIN, "alan"):
            raise TanimHatasi(f"tanımsız işler kaynağı kipi: {self.kip!r}")
        if (self.kip == "alan") != bool(self.kaynak_alan):
            raise TanimHatasi(
                "kip 'alan' ise kaynak alan adı zorunlu, değilse boş olmalı: "
                f"kip={self.kip!r} kaynak_alan={self.kaynak_alan!r}"
            )

    def __str__(self) -> str:
        return f"{ALAN_ONEKI}{self.kaynak_alan}" if self.kip == "alan" else self.kip


def isler_kaynagi_ayristir(ham: Any) -> IslerKaynagi:
    """`"elle"` · `"tahmin"` · `"alan:uretim"` -> `IslerKaynagi`."""
    if not isinstance(ham, str):
        raise TanimHatasi(f"isler_kaynagi metin olmalı, gelen: {type(ham).__name__}")
    deger = ham.strip()
    if deger in (ELLE, TAHMIN):
        return IslerKaynagi(kip=deger)
    if deger.startswith(ALAN_ONEKI):
        ad = deger[len(ALAN_ONEKI) :].strip()
        if not ad:
            # ⚠️ "alan:" tek başına sessizce elle'ye düşmüyor. Zincir
            # bağının yarım yazılması, bağın hiç olmamasından tehlikeli:
            # kullanıcı bağladığını sanır.
            raise TanimHatasi("isler_kaynagi 'alan:' — hangi alan olduğu yazılmamış")
        return IslerKaynagi(kip="alan", kaynak_alan=ad)
    raise TanimHatasi(
        f"isler_kaynagi {deger!r} tanımlı değil. "
        f"Tanımlılar: {ELLE!r}, {TAHMIN!r}, '{ALAN_ONEKI}<ad>'"
    )


@dataclass(frozen=True)
class AlanTanimi:
    """Bir planlama alanının tamamı — motorun alan hakkında bildiği her şey.

    ⚠️ Motor bu nesnenin **içeriğine** bakar, adına değil. `ad` yalnızca
    çıktıyı okunur kılmak için; içinde `if ad == "uretim"` geçen bir satır
    genellik iddiasını çürütür.
    """

    ad: str
    kaynaklar: tuple[Kaynak, ...]
    isler: tuple[Is, ...]
    isler_kaynagi: IslerKaynagi = IslerKaynagi()
    kapasite_birimi: str = "saat"
    # ⚠️ İşleri üretecek modülün yolu — `isler_kaynagi` "elle" DEĞİLSE
    # zorunlu. Motorun alan adını bilmemesi tam olarak buna dayanıyor:
    # "üretim işlerini nasıl çıkarırım" bilgisi motorda değil, tanımda.
    # `elle` kipinde adaptör aranmıyor; yeni müşteri hâlâ tek JSON.
    adaptor: str | None = None
    # ⚠️ Alanın kendi sayıları — motor BAKMAZ, yalnızca adaptöre taşır.
    # Sevkiyatın "bir palet kaç saat yüklenir"i, vardiyanın "bir nöbet kaç
    # saat"i gibi bilgiler koda gömülseydi yeni müşteri kod değişikliği
    # isterdi. Serbest sözlük: kapalı küme olsaydı her yeni alan bu
    # dosyayı değiştirmek zorunda kalırdı.
    parametreler: dict[str, str] = field(default_factory=dict)

    def sayi(self, ad: str, varsayilan: float) -> float:
        """Parametreyi sayı olarak okur. Bozuksa **sessizce** varsayılana düşmez."""
        if ad not in self.parametreler:
            return varsayilan
        try:
            return float(self.parametreler[ad])
        except (TypeError, ValueError) as hata:
            raise TanimHatasi(
                f"'{self.ad}' parametresi {ad}={self.parametreler[ad]!r} sayı değil"
            ) from hata

    def __post_init__(self) -> None:
        if self.isler_kaynagi.kip != ELLE and not self.adaptor:
            raise TanimHatasi(
                f"isler_kaynagi '{self.isler_kaynagi}' için 'adaptor' zorunlu — "
                "işleri kimin üreteceği yazılmamış."
            )


def _zorunlu_kontrol(kayit: dict[str, Any], alanlar: tuple[str, ...], nerede: str) -> None:
    eksik = [a for a in alanlar if a not in kayit]
    if eksik:
        raise TanimHatasi(f"{nerede}: zorunlu alan eksik: {eksik}. Gelen: {sorted(kayit)}")


def _etiketler(kayit: dict[str, Any], bilinen: tuple[str, ...]) -> dict[str, str]:
    """Motorun tanımadığı alanlar etiket olarak taşınıyor.

    ⚠️ Bilinmeyen alan **hata değil**: taşımada "plaka", vardiyada "departman"
    gibi alana özel bilgiler tanımda yaşamalı ve çıktıya kadar gitmeli. Motor
    onlara bakmıyor, yalnızca taşıyor.

    Bu, profil dosyasındaki `extra="forbid"` kuralının **tersi** ve bilinçli:
    profil kapalı bir küme (iş parametreleri), alan tanımı açık bir küme
    (alanın kendi dünyası).
    """
    return {k: str(v) for k, v in kayit.items() if k not in bilinen}


def _ust_alan_kontrol(tanim: dict[str, Any]) -> None:
    """Tanımadığımız bir üst seviye anahtar varsa yükleme burada durur.

    ⚠️ `isler_kaynak` yazıp `isler_kaynagi` demeyi unutan bir tanım
    **hata vermeli**, sessizce varsayılana düşmemeli. Sessiz düşüş, planın
    geçmişten beslenmesi beklenirken elle yazılmış işlerle koşması demek;
    çıktı geçerli görünür, yanlış olur.
    """
    bilinmeyen = [k for k in tanim if k not in UST_ALANLAR]
    if not bilinmeyen:
        return
    ipuclari = []
    for k in bilinmeyen:
        yakin = get_close_matches(k, UST_ALANLAR, n=1, cutoff=0.7)
        ipuclari.append(f"{k!r}" + (f" (bunu mu demek istediniz: {yakin[0]!r})" if yakin else ""))
    raise TanimHatasi(
        f"tanımda bilinmeyen üst seviye alan: {', '.join(ipuclari)}. "
        f"Tanımlılar: {list(UST_ALANLAR)}"
    )


def tanimdan_yukle(tanim: dict[str, Any]) -> tuple[list[Kaynak], list[Is]]:
    """Sözlük tanımından kaynak ve iş listesi."""
    _ust_alan_kontrol(tanim)
    if "kaynaklar" not in tanim or "isler" not in tanim:
        raise TanimHatasi(
            f"Tanımda 'kaynaklar' ve 'isler' olmalı. Gelen anahtarlar: {sorted(tanim)}"
        )

    birim = tanim.get("kapasite_birimi", "saat")

    kaynaklar: list[Kaynak] = []
    for i, kayit in enumerate(tanim["kaynaklar"]):
        _zorunlu_kontrol(kayit, KAYNAK_ZORUNLU, f"kaynaklar[{i}]")
        kaynaklar.append(
            Kaynak(
                kaynak_id=str(kayit["id"]),
                ad=str(kayit["ad"]),
                gunluk_kapasite=float(kayit["gunluk_kapasite"]),
                kapasite_birimi=str(kayit.get("kapasite_birimi", birim)),
                etiketler=_etiketler(kayit, (*KAYNAK_ZORUNLU, "kapasite_birimi")),
            )
        )

    bilinen_kaynaklar = {k.kaynak_id for k in kaynaklar}
    isler: list[Is] = []
    for i, kayit in enumerate(tanim["isler"]):
        _zorunlu_kontrol(kayit, IS_ZORUNLU, f"isler[{i}]")
        uygun = tuple(str(k) for k in kayit.get("uygun_kaynaklar", ()))
        kaynak_id = kayit.get("kaynak_id")

        # ⚠️ Var olmayan kaynağa işaret eden iş, plan koşarken değil BURADA
        # patlıyor. Orada patlarsa hata mesajı "plan kurulamadı" olur ve
        # sebebi bir yazım hatası olduğu anlaşılmaz.
        for aday in (str(kaynak_id),) if kaynak_id else uygun:
            if aday not in bilinen_kaynaklar:
                raise TanimHatasi(
                    f"isler[{i}] ({kayit['id']}): tanımlı olmayan kaynak '{aday}'. "
                    f"Tanımlılar: {sorted(bilinen_kaynaklar)}"
                )

        isler.append(
            Is(
                is_id=str(kayit["id"]),
                ad=str(kayit["ad"]),
                yuk=float(kayit["yuk"]),
                oncelik=float(kayit["oncelik"]),
                kaynak_id=str(kaynak_id) if kaynak_id else None,
                uygun_kaynaklar=uygun,
                bolunebilir=bool(kayit.get("bolunebilir", True)),
                etiketler=_etiketler(
                    kayit, (*IS_ZORUNLU, "kaynak_id", "uygun_kaynaklar", "bolunebilir")
                ),
            )
        )

    return kaynaklar, isler


def _sozluk_oku(yol: Path | str) -> dict[str, Any]:
    yol = Path(yol)
    try:
        return json.loads(yol.read_text(encoding="utf-8"))
    except json.JSONDecodeError as hata:
        raise TanimHatasi(f"{yol}: geçerli JSON değil — {hata}") from hata


def dosyadan_yukle(yol: Path | str) -> tuple[list[Kaynak], list[Is]]:
    """JSON dosyasından kaynak ve iş listesi.

    ⚠️ Faz 11'den beri var ve **korunuyor**: çağıranları bozmamak için.
    Alanın tamamı (adı, işlerin nereden geldiği) gerektiğinde
    `alan_tanimi_oku` kullanılır.
    """
    return tanimdan_yukle(_sozluk_oku(yol))


def alan_tanimi_oku(tanim: dict[str, Any], ad: str | None = None) -> AlanTanimi:
    """Sözlük tanımından alanın tamamı."""
    kaynaklar, isler = tanimdan_yukle(tanim)
    return AlanTanimi(
        ad=str(tanim.get("ad", ad or "")),
        kaynaklar=tuple(kaynaklar),
        isler=tuple(isler),
        isler_kaynagi=isler_kaynagi_ayristir(tanim.get("isler_kaynagi", ELLE)),
        kapasite_birimi=str(tanim.get("kapasite_birimi", "saat")),
        adaptor=str(tanim["adaptor"]) if tanim.get("adaptor") else None,
        parametreler={k: str(v) for k, v in (tanim.get("parametreler") or {}).items()},
    )


def alan_tanimi_dosyadan(yol: Path | str) -> AlanTanimi:
    """JSON dosyasından alanın tamamı. Ad yazılmamışsa dosya adı kullanılır."""
    yol = Path(yol)
    return alan_tanimi_oku(_sozluk_oku(yol), ad=yol.stem)


__all__ = [
    "ALAN_ONEKI",
    "ELLE",
    "TAHMIN",
    "AlanTanimi",
    "IslerKaynagi",
    "TanimHatasi",
    "alan_tanimi_dosyadan",
    "alan_tanimi_oku",
    "dosyadan_yukle",
    "isler_kaynagi_ayristir",
    "tanimdan_yukle",
]
