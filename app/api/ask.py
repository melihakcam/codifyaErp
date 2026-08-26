"""Doğal dil sorusu → router → araç çağrısı.

Sahip: Kişi B · Faz 2 B2.3

İlk sürümde bu uç **yalnızca yönlendirme** yapıyordu; seçilen aracı
çalıştırmıyordu. Sebebi bilinçliydi: B2.3'ün ölçtüğü şey "doğru aracı
seçebiliyor muyuz" idi ve çalıştırmayı aynı adıma sıkıştırmak, yanlış
yönlendirmeyi doğru sonucun arkasına gizlerdi.

O ölçüm yapıldı (`OLCUMLER.md`). Faz 12'de araç çalıştırma bağlandı:
`?calistir=true` ile uç artık **cevabın kendisini** döndürüyor.

⚠️ Çalıştırma varsayılan DEĞİL. Yönlendirme ölçümü hâlâ yönlendirmeyi
ölçebilmeli; ayrıca yanlış seçilmiş bir aracı koşturmak, kullanıcıya
"anlamadım" demekten daha kötü — yanlış cevabı doğru gibi sunar.

⚠️ Bu uç LLM'e bağlı, dolayısıyla **karar yolu değil**. Model erişilemezse
503 döner; `POST /v1/decisions/...` bundan etkilenmez.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.llm.araclar import AracCalistirilamadi, araci_calistir
from app.llm.client import LLMErisilemiyor, OllamaIstemcisi
from app.llm.router import soruyu_yonlendir
from app.llm.schemas import AracAdi, SemaUyumsuz

router = APIRouter(prefix="/v1/ask", tags=["doğal dil"])


class SoruIstegi(BaseModel):
    soru: Annotated[str, Field(min_length=1, max_length=500)]


class YonlendirmeCevabi(BaseModel):
    soru: str
    arac: AracAdi
    parametreler: dict[str, str]
    deneme_sayisi: int
    uretim_ms: int
    # ⚠️ `calistir=true` verilmediyse None. Boş sözlük DEĞİL: "çalıştırmadım"
    # ile "çalıştırdım, sonuç boş" farklı şeyler.
    sonuc: dict | None = None
    calistirma_hatasi: str | None = None


@router.post("", response_model=YonlendirmeCevabi, summary="Soruyu araca yönlendir")
def soru_sor(
    istek: SoruIstegi,
    calistir: Annotated[
        bool,
        Query(
            description="Seçilen araç çalıştırılıp cevabın kendisi de dönsün mü? "
            "Varsayılan False — yanlış seçilmiş bir aracı koşturmak, "
            "'anlamadım' demekten daha kötüdür."
        ),
    ] = False,
) -> YonlendirmeCevabi:
    """Türkçe soruyu bilinen araçlardan birine yönlendirir.

    Hata durumları bilinçli olarak ayrı:

    · **422** — model geçerli bir araç çağrısı üretemedi. Kullanıcıya
      "anlayamadım" demek doğru; tahmin edip yanlış araca yönlendirmek değil.
    · **503** — model sunucusuna ulaşılamadı. Geçici bir altyapı sorunu,
      istemci tekrar deneyebilir.
    """
    try:
        with OllamaIstemcisi() as istemci:
            sonuc = soruyu_yonlendir(istemci, istek.soru)
    except SemaUyumsuz as hata:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Soru bilinen araçlardan birine yönlendirilemedi. "
                f"({hata.denemeler} deneme yapıldı.)"
            ),
        ) from hata
    except LLMErisilemiyor as hata:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Dil modeline ulaşılamadı: {hata}",
        ) from hata

    cevap = YonlendirmeCevabi(
        soru=istek.soru,
        arac=sonuc.cagri.arac,
        parametreler=sonuc.cagri.parametreler,
        deneme_sayisi=sonuc.deneme_sayisi,
        uretim_ms=sonuc.uretim_ms,
    )
    if not calistir:
        return cevap

    # ⚠️ Araç çalıştırma LLM'siz ve deterministik. Buradaki hata
    # yönlendirme hatasından ayrı raporlanıyor: "soruyu anlayamadım" ile
    # "anladım ama veriye ulaşamadım" kullanıcıya aynı şeyi söylemiyor.
    parametre = next(iter(sonuc.cagri.parametreler.values()), None)
    try:
        return cevap.model_copy(update={"sonuc": araci_calistir(sonuc.cagri.arac, parametre)})
    except AracCalistirilamadi as hata:
        return cevap.model_copy(update={"calistirma_hatasi": str(hata)})
