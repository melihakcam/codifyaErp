"""Router taban çizgisi ölçümü (Faz 2 B2.3).

Sahip: Kişi B

    uv run python -m training.eval.router_taban

⚠️ Bu script'in ürettiği sayı **eğitimin işe yarayıp yaramadığının tek
karşılaştırma noktası.** Faz 3'te LoRA eğitildikten sonra aynı script aynı
soru setiyle yeniden koşturulacak (B3.5) ve iki sayı yan yana konacak.

Ölçüm yapılmadan eğitime geçilirse "eğitim işe yaradı mı" sorusunun cevabı
kalıcı olarak kaybolur — sonradan üretilemez, çünkü eğitim öncesi model
durumu geri getirilemez.

Soru seti `router_taban_sorulari.jsonl`'de ve **elle** yazıldı. Kişi A'nın
otomatik ürettiği eğitim verisinden bilinçli olarak ayrı: aynı şablonlardan
türeyen bir test seti, modelin şablonu ezberlemesini "başarı" diye ölçerdi.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app.llm.client import LLMErisilemiyor, OllamaIstemcisi
from app.llm.router import soruyu_yonlendir
from app.llm.schemas import SemaUyumsuz

SORU_DOSYASI = Path(__file__).with_name("router_taban_sorulari.jsonl")


@dataclass
class Kayit:
    soru: str
    stil: str
    beklenen_arac: str
    beklenen_parametreler: dict[str, str]
    secilen_arac: str | None = None
    secilen_parametreler: dict[str, str] | None = None
    hata: str | None = None
    uretim_ms: int = 0
    deneme: int = 0

    @property
    def arac_dogru(self) -> bool:
        return self.secilen_arac == self.beklenen_arac

    @property
    def tam_dogru(self) -> bool:
        """Araç + parametre birlikte doğru mu.

        Parametre karşılaştırması büyük/küçük harf ve boşluk duyarsız:
        modelin "kirmizi tugla" yazması ile "Kırmızı Tuğla" yazması arasındaki
        fark bu ölçümün konusu değil — aşağı akışta arama zaten esnek olacak.
        """
        if not self.arac_dogru:
            return False
        secilen = {k: v.strip().casefold() for k, v in (self.secilen_parametreler or {}).items()}
        beklenen = {k: v.strip().casefold() for k, v in self.beklenen_parametreler.items()}
        return secilen == beklenen


def kayitlari_yukle(yol: Path = SORU_DOSYASI) -> list[Kayit]:
    kayitlar = []
    for satir in yol.read_text(encoding="utf-8").splitlines():
        if not satir.strip():
            continue
        ham = json.loads(satir)
        kayitlar.append(
            Kayit(
                soru=ham["soru"],
                stil=ham.get("stil", "?"),
                beklenen_arac=ham["arac"],
                beklenen_parametreler=ham.get("parametreler", {}),
            )
        )
    return kayitlar


def olc(kayitlar: list[Kayit], *, ayrinti: bool = True) -> list[Kayit]:
    with OllamaIstemcisi() as istemci:
        for i, k in enumerate(kayitlar, 1):
            try:
                sonuc = soruyu_yonlendir(istemci, k.soru)
                k.secilen_arac = sonuc.cagri.arac.value
                k.secilen_parametreler = dict(sonuc.cagri.parametreler)
                k.uretim_ms = sonuc.uretim_ms
                k.deneme = sonuc.deneme_sayisi
            except SemaUyumsuz as hata:
                k.hata = f"sema uyumsuz ({hata.denemeler} deneme)"
            except LLMErisilemiyor as hata:
                k.hata = f"llm erisilemiyor: {hata}"

            if ayrinti:
                if k.hata:
                    isaret = "HATA"
                elif k.tam_dogru:
                    isaret = "TAM "
                elif k.arac_dogru:
                    isaret = "ARAC"
                else:
                    isaret = "  X "
                print(
                    f"{i:>3} [{isaret}] {k.stil:<8} {k.soru[:44]:<46} -> {k.secilen_arac or k.hata}"
                )
    return kayitlar


def rapor(kayitlar: list[Kayit], gecen_sn: float) -> dict[str, float]:
    toplam = len(kayitlar)
    arac_dogru = sum(k.arac_dogru for k in kayitlar)
    tam_dogru = sum(k.tam_dogru for k in kayitlar)
    hatali = sum(k.hata is not None for k in kayitlar)

    print("\n" + "=" * 68)
    print("TABAN ÇİZGİ — eğitim ÖNCESİ")
    print("=" * 68)
    print(f"  soru sayısı            : {toplam}")
    print(f"  araç doğru             : {arac_dogru}/{toplam}  (%{arac_dogru / toplam * 100:.1f})")
    print(f"  araç + parametre doğru : {tam_dogru}/{toplam}  (%{tam_dogru / toplam * 100:.1f})")
    print(f"  şema hatası            : {hatali}")
    print(f"  toplam süre            : {gecen_sn:.1f} sn")

    print("\n  STİLE GÖRE (asıl ilgi çekici kırılım):")
    stil_toplam: dict[str, int] = defaultdict(int)
    stil_dogru: dict[str, int] = defaultdict(int)
    for k in kayitlar:
        stil_toplam[k.stil] += 1
        stil_dogru[k.stil] += int(k.arac_dogru)
    for stil in sorted(stil_toplam):
        d, t = stil_dogru[stil], stil_toplam[stil]
        print(f"    {stil:<10} {d}/{t}  (%{d / t * 100:.0f})")

    print("\n  ARACA GÖRE:")
    arac_toplam: dict[str, int] = defaultdict(int)
    arac_dogru_say: dict[str, int] = defaultdict(int)
    for k in kayitlar:
        arac_toplam[k.beklenen_arac] += 1
        arac_dogru_say[k.beklenen_arac] += int(k.arac_dogru)
    for arac in sorted(arac_toplam):
        d, t = arac_dogru_say[arac], arac_toplam[arac]
        print(f"    {arac:<32} {d}/{t}")

    yanlislar = [k for k in kayitlar if not k.arac_dogru]
    if yanlislar:
        print("\n  YANLIŞ YÖNLENDİRİLENLER:")
        for k in yanlislar:
            print(f"    [{k.stil}] {k.soru}")
            print(f"        beklenen: {k.beklenen_arac}")
            print(f"        seçilen : {k.secilen_arac or k.hata}")

    return {
        "arac_dogruluk": arac_dogru / toplam,
        "tam_dogruluk": tam_dogru / toplam,
    }


def _cli() -> None:
    ayristirici = argparse.ArgumentParser(description="Router taban çizgisi ölçümü")
    ayristirici.add_argument("--sessiz", action="store_true", help="Satır satır çıktı basma")
    args = ayristirici.parse_args()

    kayitlar = kayitlari_yukle()
    print(f"{len(kayitlar)} soru, model çağrılıyor...\n")

    baslangic = time.perf_counter()
    olc(kayitlar, ayrinti=not args.sessiz)
    rapor(kayitlar, time.perf_counter() - baslangic)

    print("\n⚠️ Bu sayıyı dokumantasyon/OLCUMLER.md'ye yaz. Faz 3'te (B3.5) aynı")
    print("   script yeniden koşturulup karşılaştırılacak.")


if __name__ == "__main__":
    _cli()
