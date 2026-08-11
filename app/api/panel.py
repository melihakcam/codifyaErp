"""Yönetim paneli — tek bakışta sistem durumu.

Sahip: Kişi B · Faz 9

Onay ekranı (`app/api/ui.py`) tek tek kararlarla ilgilenir: "bunu onaylıyor
muyum?". Bu sayfa farklı bir soruya cevap veriyor: **"sistem ne yapıyor?"**

    kaç karar üretildi · ne kadar tutar · kaç tanesi bekliyor · hangi tipte

⚠️ Panel **iş verisi gösteriyor**, dolayısıyla kimlik doğrulamanın
arkasında (`kimlik_dogrula_ui`). Anahtarsız istek giriş sayfasına gider —
onay ekranıyla aynı davranış.

⚠️ Hiçbir karar burada uygulanamaz, değiştirilemez. Sayfa salt okunur;
eylem onay ekranında. Ayrım bilinçli: özet ekranında yanlışlıkla
tıklanacak bir düğme olmamalı.

## Neden ayrı dosya

`ui.py` HTML üretiyor ama iş mantığı `approvals.py`'de. Aynı kalıp burada
da geçerli: bu dosya yalnızca sorgu + HTML. Sayılar doğrudan `decision`
tablosundan geliyor, ara bir katman yok — panelin gösterdiği sayı ile
veritabanındaki sayı arasında yorum farkı olmasın.
"""

from __future__ import annotations

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select

from app.contracts import PolitikaSonucu
from app.core.auth import KimlikUiDep
from app.core.db import OturumDep
from app.core.isletme_profili import profil
from app.models import Approval, Decision, OnayDurumu

router = APIRouter(prefix="/panel", tags=["panel"], include_in_schema=False)

_SAYFA = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Codifya - Panel</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0;
         background: #f6f7f9; color: #1a1a1a; }}
  .kap {{ max-width: 1100px; margin: 0 auto; padding: 1.5rem 1rem 3rem; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 0.2rem; }}
  .alt {{ color: #666; font-size: 0.9rem; margin-bottom: 1.5rem; }}
  .kartlar {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
              gap: 0.8rem; margin-bottom: 2rem; }}
  .kart {{ background: #fff; border: 1px solid #e3e5e8; border-radius: 8px;
           padding: 1rem 1.1rem; }}
  .kart .etiket {{ font-size: 0.78rem; color: #666; text-transform: uppercase;
                   letter-spacing: 0.04em; }}
  .kart .deger {{ font-size: 1.8rem; font-weight: 600; margin-top: 0.3rem; }}
  .kart .not {{ font-size: 0.8rem; color: #888; margin-top: 0.2rem; }}
  .uyari {{ color: #b26a00; }}
  .iyi {{ color: #1b7a3d; }}
  h2 {{ font-size: 1.05rem; margin: 1.8rem 0 0.6rem; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border: 1px solid #e3e5e8; border-radius: 8px; overflow: hidden; }}
  th, td {{ padding: 0.55rem 0.8rem; text-align: left; font-size: 0.9rem;
            border-bottom: 1px solid #eef0f2; }}
  th {{ background: #fafbfc; font-weight: 600; color: #444; }}
  tr:last-child td {{ border-bottom: none; }}
  .sag {{ text-align: right; }}
  .rozet {{ display: inline-block; padding: 0.1rem 0.5rem; border-radius: 10px;
            font-size: 0.75rem; background: #eef0f2; color: #444; }}
  .baglanti {{ display: inline-block; margin-top: 1.5rem; padding: 0.5rem 1rem;
               background: #1a1a1a; color: #fff; text-decoration: none;
               border-radius: 6px; font-size: 0.9rem; }}
</style>
</head>
<body>
<div class="kap">
  <h1>Codifya Karar Motoru</h1>
  <div class="alt">{profil_adi} · otonomi: <b>{otonomi}</b> · {uygulama_notu}</div>

  <div class="kartlar">{kartlar}</div>

  <h2>Karar tipine göre</h2>
  {tip_tablosu}

  <h2>Onay bekleyen en riskli 10 karar</h2>
  {kuyruk_tablosu}

  <a class="baglanti" href="/onay">Onay ekranına git &rarr;</a>
</div>
</body>
</html>"""


def _kart(etiket: str, deger: str, not_: str = "", sinif: str = "") -> str:
    not_html = f'<div class="not {sinif}">{escape(not_)}</div>' if not_ else ""
    return (
        f'<div class="kart"><div class="etiket">{escape(etiket)}</div>'
        f'<div class="deger">{escape(deger)}</div>{not_html}</div>'
    )


def _tr(sayi: float, ondalik: int = 0) -> str:
    """Türkçe biçim: nokta binlik, virgül ondalık."""
    metin = f"{sayi:,.{ondalik}f}"
    return metin.replace(",", "~").replace(".", ",").replace("~", ".")


@router.get("", response_class=HTMLResponse, summary="Yönetim paneli")
def panel(oturum: OturumDep, _kimlik: KimlikUiDep) -> HTMLResponse:
    """Sistem durumu tek sayfada.

    ⚠️ Tüm sayılar `decision` tablosundan doğrudan geliyor. Ara bir
    hesaplama katmanı YOK — panelin gösterdiği sayı ile veritabanındaki
    arasında yorum farkı olmamalı.
    """
    p = profil()

    toplam = oturum.scalar(select(func.count()).select_from(Decision)) or 0
    bekleyen = (
        oturum.scalar(
            select(func.count())
            .select_from(Approval)
            .where(Approval.durum == OnayDurumu.BEKLIYOR)
        )
        or 0
    )
    uygulanan = (
        oturum.scalar(select(func.count()).select_from(Decision).where(Decision.uygulandi))
        or 0
    )
    bekleyen_tutar = (
        oturum.scalar(
            select(func.sum(Decision.tahmini_tutar_tl))
            .select_from(Decision)
            .join(Approval, Approval.karar_id == Decision.karar_id)
            .where(Approval.durum == OnayDurumu.BEKLIYOR)
        )
        or 0.0
    )

    # ⚠️ "aksiyon yok" kararları ayrı sayılıyor: sistemin ürettiği kararın
    # büyük kısmı "yapılacak bir şey yok" olabilir ve toplam sayı tek başına
    # yanıltır — bugün altı kez görüldüğü gibi.
    aksiyonlu = (
        oturum.scalar(
            select(func.count())
            .select_from(Decision)
            .where(Decision.politika_sonucu != PolitikaSonucu.AKSIYON_YOK)
        )
        or 0
    )

    kartlar = "".join(
        [
            _kart("Toplam karar", _tr(toplam), f"{_tr(aksiyonlu)} tanesi aksiyon gerektiriyor"),
            _kart(
                "Onay bekleyen",
                _tr(bekleyen),
                "insan kararı gerekiyor",
                "uyari" if bekleyen else "",
            ),
            _kart(
                "Bekleyen tutar",
                f"{_tr(bekleyen_tutar)} TL",
                "onaylanırsa etkilenecek",
            ),
            _kart(
                "Sistem uyguladı",
                _tr(uygulanan),
                "shadow modda 0 olması DOĞRU" if uygulanan == 0 else "otonomi açık",
                "iyi" if uygulanan == 0 else "uyari",
            ),
        ]
    )

    tip_satirlari = oturum.execute(
        select(
            Decision.tip,
            func.count().label("adet"),
            func.sum(Decision.tahmini_tutar_tl).label("tutar"),
        )
        .group_by(Decision.tip)
        .order_by(func.count().desc())
    ).all()

    tip_tablosu = (
        "<table><tr><th>Karar tipi</th><th class='sag'>Adet</th>"
        "<th class='sag'>Toplam tutar</th></tr>"
        + "".join(
            f"<tr><td>{escape(t.value)}</td><td class='sag'>{_tr(adet)}</td>"
            f"<td class='sag'>{_tr(tutar or 0)} TL</td></tr>"
            for t, adet, tutar in tip_satirlari
        )
        + "</table>"
        if tip_satirlari
        else "<p>Henüz karar üretilmedi.</p>"
    )

    kuyruk = oturum.execute(
        select(Decision)
        .join(Approval, Approval.karar_id == Decision.karar_id)
        .where(Approval.durum == OnayDurumu.BEKLIYOR)
        .order_by(Decision.risk_skoru.desc())
        .limit(10)
    ).scalars().all()

    kuyruk_tablosu = (
        "<table><tr><th>Kalem</th><th>Karar</th><th class='sag'>Tutar</th>"
        "<th class='sag'>Güven</th><th class='sag'>Risk</th></tr>"
        + "".join(
            f"<tr><td>{escape(k.gorunen_ad)}</td>"
            f"<td><span class='rozet'>{escape(k.tip.value)}</span></td>"
            f"<td class='sag'>{_tr(k.tahmini_tutar_tl)} TL</td>"
            f"<td class='sag'>%{k.guven * 100:.0f}</td>"
            f"<td class='sag'>{_tr(k.risk_skoru)}</td></tr>"
            for k in kuyruk
        )
        + "</table>"
        if kuyruk
        else "<p>Kuyruk boş — bekleyen karar yok.</p>"
    )

    from app.core.config import ayarlar

    ayar = ayarlar()
    uygulama_notu = (
        "sistem hiçbir kararı kendisi uygulamıyor"
        if ayar.autonomy_level.value == "shadow"
        else "⚠️ sistem bazı kararları kendisi uygulayabilir"
    )

    return HTMLResponse(
        _SAYFA.format(
            profil_adi=escape(p.ad),
            otonomi=escape(ayar.autonomy_level.value),
            uygulama_notu=escape(uygulama_notu),
            kartlar=kartlar,
            tip_tablosu=tip_tablosu,
            kuyruk_tablosu=kuyruk_tablosu,
        )
    )
