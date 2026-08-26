"""Test adaptörü — motorun adaptörü TANIMDAN bulduğunu kanıtlar.

⚠️ Ürün kodu değil. Burada durmasının sebebi tam olarak şu: gerçek bir
alan adaptörü (üretim/nakliye) henüz yazılmadı ve motorun adaptör
mekanizması ona bağlanmadan sınanabilmeli. Motor bu modülü yalnızca
`ornekler/*.json` içinde adı yazdığı için import ediyor — kodda hiçbir
yerde adı geçmiyor. Mekanizmanın kanıtı bu.
"""

from __future__ import annotations

from datetime import date

from app.planlama.contracts import Is
from app.planlama.tanim import AlanTanimi


def isleri_uret(
    tanim: AlanTanimi,
    ufuk_gun: int,
    baslangic: date,
    kaynak_isler: tuple[Is, ...] = (),
) -> list[Is]:
    """Kaynak sayısı kadar iş üretir; beslendiyse gelen işleri de taşır.

    Gerçek bir adaptör burada tahmin koşar ya da başka alanın çıktısını
    çevirir. Sınanan şey adaptörün ne yaptığı değil, motorun onu tanımdan
    bulup **aynı imzayla** çağırdığı.
    """
    uretilen = [
        Is(
            is_id=f"T{n}",
            ad=f"Türetilmiş iş {n}",
            yuk=2.0,
            oncelik=float(n),
            uygun_kaynaklar=tuple(k.kaynak_id for k in tanim.kaynaklar),
        )
        for n, _ in enumerate(tanim.kaynaklar)
    ]
    # Zincir kipinde önceki alanın işleri de plana giriyor — "bir alanın
    # çıktısı başka bir alanın girdisi" iddiasının görünür hâli.
    devralinan = [
        Is(
            is_id=f"D-{i.is_id}",
            ad=f"Devralınan {i.ad}",
            yuk=i.yuk,
            oncelik=i.oncelik,
            uygun_kaynaklar=tuple(k.kaynak_id for k in tanim.kaynaklar),
        )
        for i in kaynak_isler
    ]
    return uretilen + devralinan
