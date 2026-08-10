"""Kimlik doğrulama — API anahtarı.

Sahip: Kişi B · Faz 7

`BILINEN-EKSIKLER.md` §2'nin karşılığı: bugüne kadar hiçbir uç kimlik
istemiyordu ve servis yalnızca "firewall arkasında çalıştırın" notuyla
korunuyordu. Bu dosya o notu koda çeviriyor.

## Neden API anahtarı, neden OAuth değil

Karşı taraf bir **ERP sunucusu**, bir insan değil. Makineden makineye
çağrıda kullanıcı adı/parola akışının, token yenilemenin, oturum
yönetiminin karşılığı yok. Anahtar tek bir sırdır, ERP'nin yapılandırma
dosyasında durur, dönmesi (rotation) yeni anahtar ekleyip eskisini silmek
demektir — bu yüzden ayar **liste** kabul ediyor: eski ve yeni anahtar bir
süre birlikte geçerli olabilsin.

⚠️ Anahtar **kimliği değil yetkiyi** taşır. Denetim kaydındaki `kullanici`
alanı hâlâ çağıranın bildirdiği isim; anahtar "bu çağrı Codifya'ya
konuşmaya yetkili bir sistemden geldi" der, "bunu Esmanur yaptı" demez. Rol
bazlı yetki (kim neyi onaylayabilir) ayrı bir iş ve henüz yok.

## Üç taşıyıcı, tek doğrulama

| taşıyıcı | kim kullanır |
|---|---|
| `X-API-Key` başlığı | ERP entegrasyonu (önerilen) |
| `Authorization: Bearer` | hazır HTTP istemcisi olan taraflar |
| `codifya_anahtar` çerezi | tarayıcıdaki onay ekranı |

Çerez şart: onay ekranı bir insanın tarayıcısında çalışıyor ve tarayıcı her
isteğe özel başlık koyamaz. HttpOnly — sayfadaki JavaScript anahtarı
okuyamasın (HTMX'in çerezi okumaya ihtiyacı yok, tarayıcı kendisi yolluyor).

## Anahtar tanımlı değilse

Kimlik doğrulama **kapalı** çalışır ve `/health` bunu açıkça söyler. Sebebi
geliştirme kolaylığı: 450 testin ve `--reload`'lu her koşunun anahtar
üretmesi gereksiz sürtünme.

⚠️ Ama `ortam=uretim` iken anahtarsız açılış **reddedilir** — hem uygulama
başlarken (`kimlik_yapilandirmasini_dogrula`) hem her istekte (fail-closed).
Tek kontrol yeterli değil: birincisi yanlışlıkla kaldırılırsa ikincisi
servisi açıkta bırakmaz.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Ayarlar, ayarlar

API_ANAHTAR_BASLIGI = "X-API-Key"
CEREZ_ADI = "codifya_anahtar"

URETIM_ORTAMI = "uretim"


@dataclass(frozen=True)
class Kimlik:
    """Doğrulanmış çağıranın kimliği.

    ⚠️ `dogrulandi=False` iken `ad` **beyandır, kanıt değildir**. Kimlik
    doğrulama kapalıyken (geliştirme) denetim kaydına yine bir isim yazmak
    gerekiyor; o isim çağıranın kendi söylediği. Alanın adı bunu saklamasın
    diye ayrı tutuluyor — denetim raporunda "kim yaptı" sorusunun cevabı
    ancak `dogrulandi=True` iken bağlayıcıdır.
    """

    ad: str
    rol: str = "operator"
    dogrulandi: bool = False

    @property
    def yonetici_mi(self) -> bool:
        return self.rol == "yonetici"


ANONIM = Kimlik(ad="operator", rol="operator", dogrulandi=False)
"""Kimlik doğrulama kapalıyken kullanılan varsayılan."""


class UiKimlikGerekli(Exception):
    """Onay ekranında kimlik yok — 401 JSON değil, giriş sayfasına yönlendir.

    Tarayıcıda gezinen bir insana `{"detail": "..."}` göstermek arızalı bir
    sayfa izlenimi verir. `app/main.py` bu istisnayı yakalayıp
    `/onay/giris`'e yönlendiriyor.
    """


def _anahtar_kumesi(ayar: Ayarlar) -> frozenset[str]:
    return ayar.api_anahtar_kumesi


def _istekten_anahtar_oku(request: Request) -> str | None:
    """Üç taşıyıcıdan ilk bulunanı. Sıra önemli değil, hepsi eşdeğer."""
    baslik = request.headers.get(API_ANAHTAR_BASLIGI)
    if baslik:
        return baslik.strip()

    yetki = request.headers.get("Authorization", "")
    if yetki.lower().startswith("bearer "):
        return yetki[7:].strip()

    cerez = request.cookies.get(CEREZ_ADI)
    if cerez:
        return cerez.strip()

    return None


def anahtar_gecerli_mi(sunulan: str, gecerli_anahtarlar: frozenset[str]) -> bool:
    """Sabit zamanlı karşılaştırma — erken çıkış YOK.

    ⚠️ `sunulan in gecerli_anahtarlar` yazmak cazip ama string karşılaştırması
    ilk farklı karakterde durur; yanıt süresi doğru ön ekin uzunluğunu ele
    verir. `compare_digest` bunu engelliyor. Döngü de erken kırılmıyor:
    kaçıncı anahtarın tuttuğu da bilgi sızdırır.
    """
    eslesti = False
    for gecerli in gecerli_anahtarlar:
        if secrets.compare_digest(sunulan, gecerli):
            eslesti = True
    return eslesti


def kimlik_yapilandirmasini_dogrula(ayar: Ayarlar) -> None:
    """Üretim ortamında anahtarsız açılışı engeller. `app/main.py` çağırır."""
    if ayar.ortam == URETIM_ORTAMI and not _anahtar_kumesi(ayar):
        raise RuntimeError(
            "ortam=uretim iken API_ANAHTARLARI boş olamaz. "
            "En az bir anahtar tanımlayın (virgülle ayrılmış), yoksa servis "
            "kimlik doğrulamasız açılırdı."
        )


def _dogrula(request: Request, ayar: Ayarlar, ui_mi: bool) -> Kimlik:
    gecerli_anahtarlar = _anahtar_kumesi(ayar)

    if not gecerli_anahtarlar:
        if ayar.ortam == URETIM_ORTAMI:
            # Fail-closed: açılış kontrolü bir şekilde atlandıysa bile
            # üretimde anahtarsız istek geçmez.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Kimlik doğrulama yapılandırılmamış; servis istek kabul etmiyor.",
            )
        return ANONIM

    sunulan = _istekten_anahtar_oku(request)
    if sunulan is not None and anahtar_gecerli_mi(sunulan, gecerli_anahtarlar):
        # ⚠️ Sözlükten okumak sabit zamanlı DEĞİL, ama doğrulama zaten
        # `anahtar_gecerli_mi` ile yapıldı; buradaki arama yalnızca adı ve
        # rolü bulmak için ve ancak geçerli bir anahtarla buraya gelinir.
        ad, rol = ayar.api_kimlikleri.get(sunulan, ("bilinmeyen", "operator"))
        return Kimlik(ad=ad, rol=rol, dogrulandi=True)

    if ui_mi:
        raise UiKimlikGerekli

    # Eksik anahtar ile yanlış anahtar aynı cevabı alır: hangisi olduğunu
    # söylemek, geçerli bir anahtarın varlığını doğrulamaya yarar.
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Geçersiz veya eksik API anahtarı.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def kimlik_dogrula(
    request: Request, ayar: Annotated[Ayarlar, Depends(ayarlar)]
) -> Kimlik:
    """JSON uçları için kimlik kontrolü. Başarısızsa 401."""
    return _dogrula(request, ayar, ui_mi=False)


def kimlik_dogrula_ui(
    request: Request, ayar: Annotated[Ayarlar, Depends(ayarlar)]
) -> Kimlik:
    """Onay ekranı için kimlik kontrolü. Başarısızsa giriş sayfasına yönlendirir."""
    return _dogrula(request, ayar, ui_mi=True)


KimlikDep = Annotated[Kimlik, Depends(kimlik_dogrula)]
KimlikUiDep = Annotated[Kimlik, Depends(kimlik_dogrula_ui)]


__all__ = [
    "ANONIM",
    "API_ANAHTAR_BASLIGI",
    "CEREZ_ADI",
    "Kimlik",
    "KimlikDep",
    "KimlikUiDep",
    "UiKimlikGerekli",
    "anahtar_gecerli_mi",
    "kimlik_dogrula",
    "kimlik_dogrula_ui",
    "kimlik_yapilandirmasini_dogrula",
]
