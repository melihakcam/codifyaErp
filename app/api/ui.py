"""Basit onay ekranı — minimal HTML/HTMX arayüzü.

Sahip: Kişi B · Faz 4.5

React'a bilinçli olarak girilmedi (görev dosyası: "minimal HTML/HTMX
yeter, React'a girme"). HTMX, sayfayı yeniden yüklemeden tabloyu
güncellemeyi sağlıyor; build adımı / npm / bundler yok, tek dosya.

Bu ekran `/v1/approvals` JSON API'sinin **üstüne** ince bir HTML katmanı —
iş mantığının hiçbiri burada değil, hepsi `app/api/approvals.py`'de. Bu
dosya yalnızca aynı fonksiyonları doğrudan çağırıp HTML'e çeviriyor
(FastAPI dekoratörleri fonksiyonu değiştirmiyor, düz Python çağrısı olarak
da kullanılabiliyor).

⚠️ Ekran Faz 7'de kimlik doğrulamanın arkasına alındı (`kimlik_dogrula_ui`);
anahtarsız istek `/onay/giris`'e yönlendirilir. Ama "kullanıcı" alanı hâlâ
serbest metin ve bu bilinçli bir sınır: anahtar **sistemi** doğruluyor,
kişiyi değil. Denetim kaydındaki isim çağıranın beyanı — kişi bazlı yetki
(kim neyi onaylayabilir) ayrı bir iş ve henüz yok.

⚠️ "Düzelt" eylemi bu ekranda yok — `duzeltilmis_aksiyon` karar tipine göre
şekli değişen serbest bir sözlük, minimal bir form bunu güvenle temsil
edemez. Düzeltme gereken kararlar için Swagger (`/docs`) üzerinden
`POST /v1/approvals/{karar_id}` kullanılır.
"""

from __future__ import annotations

from html import escape
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from app.api.approvals import (
    KuyrukKalemi,
    OnayEylemi,
    OnayIstegi,
    karari_sonuclandir,
    kuyrugu_listele,
)
from app.core.auth import KimlikUiDep
from app.core.db import OturumDep

router = APIRouter(prefix="/onay", tags=["onay ekranı"], include_in_schema=False)

_SAYFA_ISKELETI = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>Codifya - Onay Kuyrugu</title>
<script src="https://unpkg.com/htmx.org@2.0.3"></script>
<style>
  body { font-family: system-ui, sans-serif; max-width: 1100px; margin: 2rem auto;
         padding: 0 1rem; }
  table { width: 100%; border-collapse: collapse; }
  th, td { border-bottom: 1px solid #ddd; padding: 0.5rem; text-align: left; vertical-align: top; }
  th { background: #f5f5f5; }
  button { cursor: pointer; padding: 0.3rem 0.7rem; margin-right: 0.3rem; border-radius: 4px; }
  .onayla { background: #d4f7d4; border: 1px solid #4caf50; }
  .reddet { background: #fbdada; border: 1px solid #e53935; }
  #durum { margin: 1rem 0; color: #555; }
  .alan { font-size: 0.8rem; text-transform: uppercase; color: #555; letter-spacing: 0.05em; }
  .kalem { font-weight: 600; }
  .kalici { color: #b71c1c; font-size: 0.8rem; display: block; }
  .ust { display: flex; justify-content: space-between; align-items: baseline; }
</style>
</head>
<body>
  <div class="ust">
    <h1>Onay Kuyrugu</h1>
    <form method="post" action="/onay/cikis"><button type="submit">Cikis</button></form>
  </div>
  <p>Kullanici: <input id="kullanici" name="kullanici" value="operator" size="15"></p>
  <div id="kuyruk" hx-get="/onay/liste" hx-trigger="load" hx-swap="innerHTML">
    yukleniyor...
  </div>
</body>
</html>"""


def _kullanici_dogrula(kullanici: str) -> str:
    """Bos gonderilirse audit kaydinda bos kullanici olmasin diye."""
    kullanici = kullanici.strip()
    return kullanici or "operator"


def _satir_html(kalem: KuyrukKalemi) -> str:
    aksiyon_ozet = ", ".join(f"{k}={v}" for k, v in kalem.aksiyon.items())
    gerekce = escape(kalem.gerekce_metni) if kalem.gerekce_metni else "<em>henuz uretilmedi</em>"
    # ⚠️ "Geri alinamaz" uyarısı satırda duruyor, kararın ayrıntısında değil:
    # tasfiye ve karşılık ayırma muhasebe kaydı üretiyor, onaylandıktan sonra
    # düzeltme fişi gerekiyor. Operatörün bunu tıklamadan ÖNCE görmesi lazım.
    kalici = "" if kalem.geri_alinabilir else '<span class="kalici">geri alinamaz</span>'
    return f"""
    <tr>
      <td>
        <span class="alan">{escape(kalem.alan.value)}</span><br>
        <span class="kalem">{escape(kalem.kalem_adi)}</span>
      </td>
      <td>{escape(kalem.tip.value)}{kalici}</td>
      <td>{escape(aksiyon_ozet)}</td>
      <td>{kalem.tahmini_tutar_tl:,.0f} TL</td>
      <td>%{kalem.guven * 100:.0f}</td>
      <td>{kalem.risk_skoru:,.0f}</td>
      <td>{gerekce}</td>
      <td>
        <button class="onayla" hx-post="/onay/{kalem.karar_id}/onayla"
                hx-include="#kullanici" hx-target="#kuyruk" hx-swap="innerHTML">Onayla</button>
        <button class="reddet" hx-post="/onay/{kalem.karar_id}/reddet"
                hx-include="#kullanici" hx-target="#kuyruk" hx-swap="innerHTML">Reddet</button>
      </td>
    </tr>"""


def _liste_html(oturum) -> str:
    kalemler = kuyrugu_listele(oturum)
    if not kalemler:
        return '<p id="durum">Kuyruk bos - bekleyen karar yok.</p>'
    satirlar = "".join(_satir_html(k) for k in kalemler)
    return f"""
    <p id="durum">{len(kalemler)} karar onay bekliyor.</p>
    <table>
      <tr><th>Kalem</th><th>Tip</th><th>Aksiyon</th><th>Tutar</th><th>Guven</th><th>Risk</th>
          <th>Gerekce</th><th></th></tr>
      {satirlar}
    </table>"""


# `_kimlik` parametreleri kullanılmıyor ama SİLİNMEMELİ: FastAPI bağımlılığı
# imzadan okuyor, parametre gidince kimlik kontrolü de gider.
@router.get("", response_class=HTMLResponse, summary="Onay ekranı (HTML)")
def onay_sayfasi(_kimlik: KimlikUiDep) -> HTMLResponse:
    return HTMLResponse(_SAYFA_ISKELETI)


@router.get("/liste", response_class=HTMLResponse, include_in_schema=False)
def liste_parcasi(oturum: OturumDep, _kimlik: KimlikUiDep) -> HTMLResponse:
    return HTMLResponse(_liste_html(oturum))


@router.post("/{karar_id}/onayla", response_class=HTMLResponse, include_in_schema=False)
def onayla(
    karar_id: UUID, kullanici: Annotated[str, Form()], oturum: OturumDep, _kimlik: KimlikUiDep
) -> HTMLResponse:
    istek = OnayIstegi(eylem=OnayEylemi.ONAYLA, kullanici=_kullanici_dogrula(kullanici))
    karari_sonuclandir(karar_id, istek, oturum)
    return HTMLResponse(_liste_html(oturum))


@router.post("/{karar_id}/reddet", response_class=HTMLResponse, include_in_schema=False)
def reddet(
    karar_id: UUID, kullanici: Annotated[str, Form()], oturum: OturumDep, _kimlik: KimlikUiDep
) -> HTMLResponse:
    istek = OnayIstegi(eylem=OnayEylemi.REDDET, kullanici=_kullanici_dogrula(kullanici))
    karari_sonuclandir(karar_id, istek, oturum)
    return HTMLResponse(_liste_html(oturum))
