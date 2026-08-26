def test_ozet_sablona_dusmeyi_GORUNUR_yapiyor():
    """⭐ `gerekce_uretilen` tek başına yalan söylüyordu.

    O sayaç modelden gelen metinle şablona düşeni ayırmıyordu: %100 şablona
    düşen bir koşu, %100 modelden gelen koşuyla özet çıktısında **birebir
    aynı** görünüyordu.

    Bedeli Tur 8 · B5'te ölçüldü: `explain.py`'nin alan-bağımsız sanılan üç
    yeri finansta patlıyordu ve her finans kararı 0 saniyede şablona
    düşüyordu — model hiç çağrılmıyordu. Sinyal vardı
    (`guard_sonucu="sablona_dustu"`) ama özet göstermediği için görülmedi.
    """
    from uuid import uuid4

    from app.jobs.nightly import KosuOzeti

    saglikli = KosuOzeti(kosu_id=uuid4())
    saglikli.gerekce_uretilen = 10
    saglikli.gerekce_gecti = 9
    saglikli.gerekce_sablona_dustu = 1

    bozuk = KosuOzeti(kosu_id=uuid4())
    bozuk.gerekce_uretilen = 10
    bozuk.gerekce_sablona_dustu = 10

    # ⭐ Asil nokta: iki kosu ARTIK ayirt edilebiliyor.
    assert saglikli.ozet() != bozuk.ozet()

    assert saglikli.guard_uyarisi() is None, "saglikli kosuda uyari cikmamali"
    assert bozuk.guard_uyarisi() is not None, "tamami sablon olan kosu uyarmali"
    assert "ŞABLONA DÜŞTÜ" in bozuk.ozet()
    assert "ŞABLONA DÜŞTÜ" not in saglikli.ozet()


def test_gerekce_uretilmeyen_kosuda_uyari_yok():
    """Sıfıra bölme yok, ve gerekçe istenmediyse uyarmak yanlış alarm olurdu."""
    from uuid import uuid4

    from app.jobs.nightly import KosuOzeti

    ozet = KosuOzeti(kosu_id=uuid4())
    ozet.taranan = 500
    ozet.gerekce_atlanan = 500

    assert ozet.guard_uyarisi() is None
    assert ozet.ozet()
