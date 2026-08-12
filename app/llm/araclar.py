"""Araç çalıştırma — router'ın seçtiği aracı gerçekten koşturur.

Sahip: Kişi B · Faz 12

## Neden ayrı bir katman

Bugüne kadar `/v1/ask` yalnızca **yönlendirme** yapıyordu: soruyu alıp
"hangi araç" diye cevap veriyor, aracı çalıştırmıyordu. Sebebi bilinçliydi
(B2.3): ölçülen şey "doğru aracı seçebiliyor muyuz" idi ve çalıştırmayı aynı
adıma sıkıştırmak, yanlış yönlendirmeyi doğru sonucun arkasına gizlerdi.

O ölçüm yapıldı. Şimdi eksik olan cevabın kendisi.

## ⚠️ Bu katman LLM'siz çalışıyor

Araç çalıştırma **tamamen deterministik**: araç adı → fonksiyon → sonuç.
Model hata yapsa bile bu katman doğru çalışır; model erişilemese bile araç
doğrudan çağrılabilir.

Ayrım pratik bir sonuç doğuruyor: "genel arayüz" iki parçadan oluşuyor ve
biri **güvenilir** (bu dosya), diğeri **olasılıklı** (router). İkisini aynı
yerde tutmak, arayüzün tamamını modelin doğruluğuna bağlardı.

## ⚠️ Araç eklemek router'ı otomatik güncellemiyor

Buraya bir araç eklemek onu **çalıştırılabilir** yapar; modelin onu
**seçebilmesi** ayrı bir konu. Eğitilmiş kipte (`llm_istem_bicimi=egitilmis`)
istemde araç listesi yok — model yalnızca eğitimde gördüğü adları
üretebiliyor. Yeni bir araç o kipte pratikte ulaşılamaz kalır.

Bu bir kusur değil, ölçülmüş bir sınır; `dokumantasyon/OLCUMLER.md`'ye
yazıldı ve `AracAdi`'ye araç eklerken hatırlanması gerekiyor.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.llm.schemas import AracAdi

AracSonucu = dict[str, Any]
AracFonksiyonu = Callable[[str | None], AracSonucu]


class AracCalistirilamadi(RuntimeError):
    """Araç bulundu ama koşturulamadı. Yönlendirme hatasından ayrı tutuluyor.

    ⚠️ Ayrım kullanıcıya farklı şeyler söylüyor: "sorunu anlayamadım" ile
    "anladım ama veriye ulaşamadım" aynı cümle olmamalı.
    """


def _kritik_stok(parametre: str | None) -> AracSonucu:
    """Yeniden sipariş noktasının altına düşmüş kalemler."""
    from app.contracts import KararTipi
    from app.domain.stock.decide import (
        _demo_dunyasini_yukle,
        _siniflandirmayi_hesapla,
        ozellikten_karar_uret,
    )
    from app.domain.stock.features import katalog_ozelliklerini_hesapla

    dunya = _demo_dunyasini_yukle()
    ozellikler = katalog_ozelliklerini_hesapla(
        olcum_tarihi=dunya["olcum_tarihi"],
        talep=dunya["talep"],
        envanter_gunluk=dunya["envanter_gunluk"],
        sku_df=dunya["sku"],
        tedarikci_df=dunya["tedarikci"],
        siniflandirma=_siniflandirmayi_hesapla(dunya),
    )
    if parametre:
        ozellikler = [o for o in ozellikler if o.kategori.lower() == parametre.lower()]

    kararlar = [
        k for k in (ozellikten_karar_uret(o) for o in ozellikler) if k.tip is KararTipi.STOK_SIPARIS
    ]
    kararlar.sort(key=lambda k: -k.tahmini_tutar_tl)

    return {
        "adet": len(kararlar),
        "kalemler": [
            {
                "sku_id": k.ozellikler.sku_id,
                "ad": k.ozellikler.gorunen_ad,
                "eldeki_stok": k.ozellikler.eldeki_stok,
                "onerilen_siparis": k.aksiyon.get("siparis_miktari"),
                "tutar_tl": k.tahmini_tutar_tl,
            }
            for k in kararlar[:20]
        ],
    }


def _uretim_emirleri(parametre: str | None) -> AracSonucu:
    """Açılması önerilen üretim emirleri."""
    from app.contracts import KararTipi
    from app.domain.production.decide import uretim_kararlari_uret

    kararlar = [k for k in uretim_kararlari_uret() if k.tip is KararTipi.URETIM_EMIR_AC]
    kararlar.sort(key=lambda k: -k.tahmini_tutar_tl)

    return {
        "adet": len(kararlar),
        "toplam_tutar_tl": round(sum(k.tahmini_tutar_tl for k in kararlar), 2),
        "emirler": [
            {
                "kalem_id": k.ozellikler.kalem_id,
                "ad": k.ozellikler.gorunen_ad,
                "miktar": k.aksiyon.get("emir_miktari"),
                "hat": k.ozellikler.hat_adi,
                "tutar_tl": k.tahmini_tutar_tl,
            }
            for k in kararlar[:20]
        ],
    }


def _uretim_cizelgesi(parametre: str | None) -> AracSonucu:
    """Hangi iş, hangi hatta, hangi gün."""
    from app.contracts import KararTipi
    from app.domain.production.cizelge import cizelge_kur
    from app.domain.production.decide import uretim_kararlari_uret

    emirler = [k for k in uretim_kararlari_uret() if k.tip is KararTipi.URETIM_EMIR_AC]
    cizelgeler = cizelge_kur(emirler)

    return {
        "hatlar": [
            {
                "hat": h.hat_adi,
                "planlanan_is": len(h.satirlar),
                "ufka_sigmayan": len(h.sigmayanlar),
                "ilk_isler": [
                    {"ad": s.kalem_adi, "gun": s.baslangic.isoformat(), "miktar": s.miktar}
                    for s in h.satirlar[:5]
                ],
            }
            for h in cizelgeler
        ]
    }


def _kapasite_durumu(parametre: str | None) -> AracSonucu:
    """Hatların doluluğu ve kapasite aşımı."""
    from app.contracts import KararTipi
    from app.core.isletme_profili import profil
    from app.domain.production.cizelge import emirleri_ise_cevir
    from app.domain.production.decide import uretim_kararlari_uret

    kararlar = uretim_kararlari_uret()
    emirler = [k for k in kararlar if k.tip is KararTipi.URETIM_EMIR_AC]
    asimlar = [k for k in kararlar if k.tip is KararTipi.URETIM_KAPASITE_ASIMI]
    isler, kaynaklar = emirleri_ise_cevir(emirler)
    ufuk = profil().uretim.planlama_ufku_gun

    yuk: dict[str, float] = {}
    for i in isler:
        yuk[i.kaynak_id or ""] = yuk.get(i.kaynak_id or "", 0.0) + i.yuk

    return {
        "erteleme_onerisi": len(asimlar),
        "hatlar": [
            {
                "hat": k.ad,
                "yuk_saat": round(yuk.get(k.kaynak_id, 0.0), 1),
                "kapasite_saat": round(k.gunluk_kapasite * ufuk, 1),
                "doluluk": round(yuk.get(k.kaynak_id, 0.0) / (k.gunluk_kapasite * ufuk), 3),
            }
            for k in kaynaklar
        ],
    }


def _plan_karsilastir(parametre: str | None) -> AracSonucu:
    """Plan seçenekleri ve gerekçeli öneri."""
    from app.contracts import KararTipi
    from app.core.isletme_profili import profil
    from app.domain.production.cizelge import emirleri_ise_cevir
    from app.domain.production.decide import uretim_kararlari_uret
    from app.planlama.karsilastir import planlari_karsilastir
    from app.planlama.olcut import OLCUT_ACIKLAMALARI, OLCUTLER
    from app.planlama.yerlestirme import plan_kur

    emirler = [k for k in uretim_kararlari_uret() if k.tip is KararTipi.URETIM_EMIR_AC]
    isler, kaynaklar = emirleri_ise_cevir(emirler)
    if not isler:
        return {"karneler": [], "onerilen": None, "gerekce": "Planlanacak emir yok."}

    ufuk = profil().uretim.planlama_ufku_gun
    sonuc = planlari_karsilastir(
        {ad: plan_kur(isler, kaynaklar, ad, ufuk_gun=ufuk) for ad in OLCUTLER},
        OLCUT_ACIKLAMALARI,
    )
    return {
        "karneler": [
            {
                "olcut": k.olcut,
                "aciklama": k.aciklama,
                "yerlesen_is": k.maliyet.yerlesen_is,
                "ufka_sigmayan": k.maliyet.sigmayan_is,
                "beklenen_maliyet_tl": round(k.maliyet.toplam_tl, 2),
            }
            for k in sonuc.karneler
        ],
        "onerilen": sonuc.onerilen_olcut,
        "gerekce": sonuc.oneri_gerekcesi,
        # ⚠️ Varsayımlar cevabın parçası; öneri onları gizlemiyor.
        "varsayimlar": list(sonuc.karneler[0].maliyet.varsayimlar),
    }


ARACLAR: dict[AracAdi, AracFonksiyonu] = {
    AracAdi.KRITIK_STOK: _kritik_stok,
    AracAdi.URETIM_EMIRLERI: _uretim_emirleri,
    AracAdi.URETIM_CIZELGESI: _uretim_cizelgesi,
    AracAdi.KAPASITE_DURUMU: _kapasite_durumu,
    AracAdi.PLAN_KARSILASTIR: _plan_karsilastir,
}
"""Çalıştırılabilir araçlar.

⚠️ `AracAdi`'deki her araç burada YOK ve bu bilinçli. Kalanlar (`olu_stok`,
`onay_kuyrugu`, `gecelik_ozet`...) DB'ye ya da başka uçlara bağlı; onları
bağlamak ayrı bir iş. Eksik olan araç **sessizce boş cevap dönmüyor**,
`arac_calistirilabilir_mi()` ile önden sorulabiliyor ve uç açık bir mesaj
veriyor.

Sessiz boş cevap, "sistem cevap veremiyor" ile "cevap gerçekten yok"u
birbirine karıştırırdı."""


def arac_calistirilabilir_mi(arac: AracAdi) -> bool:
    return arac in ARACLAR


def araci_calistir(arac: AracAdi, parametre: str | None = None) -> AracSonucu:
    """Aracı koşturur. LLM'e hiç dokunmuyor.

    ⚠️ Hata yutulmuyor. Bir aracın çökmesi "cevap yok" diye görünürse sorun
    fark edilmez; çağıran taraf farkı kullanıcıya söyleyebilsin diye ayrı
    bir istisna atılıyor.
    """
    if arac not in ARACLAR:
        raise AracCalistirilamadi(
            f"{arac.value} henüz çalıştırılabilir değil. "
            f"Çalıştırılabilenler: {sorted(a.value for a in ARACLAR)}"
        )
    try:
        return ARACLAR[arac](parametre)
    except Exception as hata:
        raise AracCalistirilamadi(f"{arac.value} koşturulamadı: {hata}") from hata


__all__ = [
    "ARACLAR",
    "AracCalistirilamadi",
    "AracSonucu",
    "arac_calistirilabilir_mi",
    "araci_calistir",
]
