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
from pathlib import Path
from typing import Any

from app.planlama.contracts import Is, Kaynak

# Zorunlu alanlar. Eksikse hata mesajı hangi satırda olduğunu söylüyor —
# 200 satırlık bir tanımda "bir yerde eksik alan var" demek yardım etmez.
KAYNAK_ZORUNLU = ("id", "ad", "gunluk_kapasite")
IS_ZORUNLU = ("id", "ad", "yuk", "oncelik")


class TanimHatasi(ValueError):
    """Alan tanımı okunamadı. Mesaj hangi kayıtta ne eksik olduğunu söyler."""


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


def tanimdan_yukle(tanim: dict[str, Any]) -> tuple[list[Kaynak], list[Is]]:
    """Sözlük tanımından kaynak ve iş listesi."""
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


def dosyadan_yukle(yol: Path | str) -> tuple[list[Kaynak], list[Is]]:
    """JSON dosyasından alan tanımı."""
    yol = Path(yol)
    try:
        tanim = json.loads(yol.read_text(encoding="utf-8"))
    except json.JSONDecodeError as hata:
        raise TanimHatasi(f"{yol}: geçerli JSON değil — {hata}") from hata
    return tanimdan_yukle(tanim)


__all__ = ["TanimHatasi", "dosyadan_yukle", "tanimdan_yukle"]
