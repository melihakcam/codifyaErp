"""Onay ekranı girişi — anahtarı çereze koyan tek sayfa.

Sahip: Kişi B · Faz 7

`app/core/auth.py` üç taşıyıcı kabul ediyor; bu sayfa yalnızca sonuncusunu
(çerez) doldurmak için var. ERP tarafı buraya hiç uğramaz — o `X-API-Key`
başlığıyla konuşur.

⚠️ Bu router bilinçli olarak **korumasız**: kimlik almanın yolu kimlik
gerektiremez. Sayfanın kendisi hiçbir iş verisi göstermiyor, yalnızca bir
form.

⚠️ Bu bir "oturum" değil. Çerez anahtarın kendisini taşıyor, sunucu tarafında
tutulan bir oturum kaydı yok — dolayısıyla "çıkış yap" tek bir tarayıcıyı
temizler, anahtarı iptal etmez. Anahtar iptali `API_ANAHTARLARI` ayarından
o anahtarı silmekle olur.
"""

from __future__ import annotations

from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.auth import CEREZ_ADI, anahtar_gecerli_mi
from app.core.config import Ayarlar, ayarlar

router = APIRouter(prefix="/onay", tags=["onay ekranı"], include_in_schema=False)

AyarDep = Annotated[Ayarlar, Depends(ayarlar)]

VARSAYILAN_HEDEF = "/onay"

# Çerez ömrü. 12 saat = bir vardiya; ertesi gün yeniden giriş istenir.
CEREZ_OMRU_SN = 12 * 60 * 60


def _guvenli_hedef(hedef: str | None) -> str:
    """Yalnızca kendi onay ekranımıza dönülür.

    ⚠️ Girişten sonra kullanıcıyı serbest metinden gelen bir adrese
    yönlendirmek açık yönlendirme (open redirect) açığıdır: saldırgan
    `/onay/giris?hedef=https://kotu.example` bağlantısı yollar, kurban giriş
    yaptıktan sonra sahte bir ekranda bulur kendini. `/onay` ile başlama
    şartı bunu kapatıyor; `//baska.site` gibi protokolsüz mutlak adresler de
    bu kontrolden geçemez.
    """
    if hedef and hedef.startswith("/onay") and not hedef.startswith("//"):
        return hedef
    return VARSAYILAN_HEDEF


_FORM = """<form method="post" action="/onay/giris">
    <input type="hidden" name="hedef" value="{hedef}">
    <label for="anahtar">API anahtari</label>
    <input id="anahtar" name="anahtar" type="password" autofocus autocomplete="current-password">
    <button type="submit">Giris</button>
  </form>"""


def _giris_sayfasi(hedef: str, hata: str | None = None, form_goster: bool = True) -> str:
    hata_html = f'<p class="hata">{escape(hata)}</p>' if hata else ""
    govde = (
        _FORM.format(hedef=escape(hedef))
        if form_goster
        else '<p class="not">Kimlik dogrulama KAPALI (API_ANAHTARLARI bos). '
        '<a href="/onay">Ekrana git</a>.</p>'
    )
    return f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>Codifya - Giris</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 420px; margin: 4rem auto;
         padding: 0 1rem; }}
  input {{ width: 100%; padding: 0.5rem; font-size: 1rem; box-sizing: border-box; }}
  button {{ margin-top: 0.8rem; padding: 0.5rem 1.2rem; cursor: pointer; }}
  .hata {{ color: #b71c1c; }}
  .not {{ color: #666; font-size: 0.9rem; }}
</style>
</head>
<body>
  <h1>Codifya - Onay Ekrani</h1>
  {hata_html}
  {govde}
  <p class="not">Anahtar yoneticinizden alinir. ERP entegrasyonu bu sayfayi
  kullanmaz, <code>X-API-Key</code> basligiyla calisir.</p>
</body>
</html>"""


@router.get("/giris", response_class=HTMLResponse)
def giris_sayfasi(ayar: AyarDep, hedef: str | None = None) -> HTMLResponse:
    """Giriş formu. Kimlik doğrulama kapalıysa doğrudan ekrana gönderir."""
    # Anahtar tanımlı değilse form anlamsız — girilen hiçbir şey
    # doğrulanmayacak. Kullanıcıyı boş yere yazmaya zorlamıyoruz.
    return HTMLResponse(
        _giris_sayfasi(_guvenli_hedef(hedef), form_goster=bool(ayar.api_anahtar_kumesi))
    )


@router.post("/giris", response_model=None)
def giris_yap(
    istek: Request,
    ayar: AyarDep,
    anahtar: Annotated[str, Form()],
    hedef: Annotated[str | None, Form()] = None,
) -> HTMLResponse | RedirectResponse:
    """Anahtar doğruysa çereze yazar ve ekrana yönlendirir."""
    guvenli_hedef = _guvenli_hedef(hedef)

    if not anahtar_gecerli_mi(anahtar.strip(), ayar.api_anahtar_kumesi):
        # 401 döndürülüyor ama gövde HTML: tarayıcıdaki insan formu tekrar
        # görmeli, JSON hata nesnesi değil.
        return HTMLResponse(
            _giris_sayfasi(guvenli_hedef, hata="Anahtar gecersiz."), status_code=401
        )

    cevap = RedirectResponse(url=guvenli_hedef, status_code=303)
    # ⚠️ B4: `Secure` bayrağı isteğin şemasından da çıkarılıyor. Ayarı
    # elle True yapmayı unutan bir TLS kurulumunda çerez korumasız giderdi;
    # ayarı elle True yapıp HTTP'de çalışan bir geliştirme kurulumunda ise
    # tarayıcı çerezi hiç göndermez ve ekran sessizce çalışmaz. İkisi de
    # sessiz arıza — şemaya bakmak ikisini de kapatıyor.
    guvenli = ayar.cerez_guvenli or istek.url.scheme == "https"
    cevap.set_cookie(
        CEREZ_ADI,
        anahtar.strip(),
        max_age=CEREZ_OMRU_SN,
        httponly=True,  # sayfadaki JS anahtarı okuyamasın
        samesite="strict",  # başka siteden gelen istekte çerez gitmesin (CSRF)
        secure=guvenli,
    )
    return cevap


@router.post("/cikis")
def cikis_yap() -> RedirectResponse:
    """Çerezi siler. Anahtarı iptal ETMEZ — bkz. modül docstring'i."""
    cevap = RedirectResponse(url="/onay/giris", status_code=303)
    cevap.delete_cookie(CEREZ_ADI, httponly=True, samesite="strict")
    return cevap
