"""Karar kaydı ve denetim izi.

Sahip: Kişi B · Faz 1 B1.1

İki tablonun rol ayrımı bilinçli:

· `decision`       → kararın GÜNCEL durumu. Tek satırdan `DecisionCandidate`
                     yeniden kurulabilir (`adaya_cevir()`). Bu şart, çünkü
                     gerekçe tembel üretiliyor: guard saatler sonra çalıştığında
                     `izinli_sayilar()` kümesini bu satırdan çıkaracak.
· `decision_audit` → EKLEMELİ olay izi. Asla güncellenmez. Gerekçe iki kez
                     üretildiyse iki satır olur; guard'ın ilk denemede neyi
                     reddettiği kaybolmaz.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.contracts import (
    Alan,
    DecisionCandidate,
    GuardSonucu,
    KararTipi,
    OtonomiSeviyesi,
    PolitikaKarari,
    PolitikaSonucu,
)
from app.models.base import Base, KimlikliTablo, enum_kolonu


class Decision(Base):
    """Üretilen karar adayı + politikanın hükmü + (varsa) gerekçe.

    `ozellikler` ve `tetiklenen_kurallar` tam JSON olarak saklanır. Yer
    kazanmak için kırpma yapılmaz: guard'ın izinli sayılar kümesi bu iki
    alandan türüyor, eksik alan doğrudan yanlış guard kararı demek.
    """

    __tablename__ = "decision"

    # Sözleşmeden gelen UUID doğrudan birincil anahtar — ikinci bir kimlik yok.
    karar_id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)

    # --- Karar adayı (Kişi A üretir) ---
    alan: Mapped[Alan] = mapped_column(enum_kolonu(Alan), index=True)
    tip: Mapped[KararTipi] = mapped_column(enum_kolonu(KararTipi), index=True)
    aksiyon: Mapped[dict[str, Any]]
    tahmini_tutar_tl: Mapped[float]
    geri_alinabilir: Mapped[bool]
    guven: Mapped[float]
    tetiklenen_kurallar: Mapped[list[dict[str, Any]]]
    ozellikler: Mapped[dict[str, Any]]
    model_surumleri: Mapped[dict[str, Any]]
    uretim_zamani: Mapped[datetime]

    # --- Politikanın hükmü (Kişi B üretir) ---
    # ⚠️ `politika_sonucu` ile `uygulandi` ayrı kolonlar. Shadow mod raporu
    # tam olarak bu ikisinin karşılaştırması — birleştirmek raporu imkânsız kılar.
    politika_sonucu: Mapped[PolitikaSonucu] = mapped_column(enum_kolonu(PolitikaSonucu), index=True)
    uygulandi: Mapped[bool] = mapped_column(index=True)
    otonomi_seviyesi: Mapped[OtonomiSeviyesi] = mapped_column(enum_kolonu(OtonomiSeviyesi))
    risk_skoru: Mapped[float] = mapped_column(index=True)
    gerekce_kodlari: Mapped[list[str]]

    # --- Gerekçe (Faz 2'de dolar; şimdilik hep NULL) ---
    # Hepsi nullable: karar geçerlidir, gerekçesi kuyrukta bekliyor olabilir.
    gerekce_metni: Mapped[str | None] = mapped_column(sa.Text, default=None)
    guard_sonucu: Mapped[GuardSonucu | None] = mapped_column(enum_kolonu(GuardSonucu), default=None)
    llm_model_adi: Mapped[str | None] = mapped_column(default=None)
    gerekce_uretim_ms: Mapped[int | None] = mapped_column(default=None)

    olusturma_zamani: Mapped[datetime] = mapped_column(default=datetime.now, index=True)

    audit_kayitlari: Mapped[list[DecisionAudit]] = relationship(
        back_populates="karar",
        cascade="all, delete-orphan",
        order_by="DecisionAudit.zaman",
    )

    @classmethod
    def sozlesmeden(cls, aday: DecisionCandidate, politika: PolitikaKarari) -> Decision:
        """Sözleşme nesnelerinden DB satırı üretir.

        `mode="json"` şart: `model_dump()` `date` ve `UUID` nesnelerini olduğu
        gibi döndürür, JSON kolonu bunları serileştiremez ve kayıt anında
        `TypeError` alırsın. `mode="json"` ISO metne çevirir.
        """
        return cls(
            karar_id=aday.karar_id,
            alan=aday.alan,
            tip=aday.tip,
            aksiyon=aday.aksiyon,
            tahmini_tutar_tl=aday.tahmini_tutar_tl,
            geri_alinabilir=aday.geri_alinabilir,
            guven=aday.guven,
            tetiklenen_kurallar=[k.model_dump(mode="json") for k in aday.tetiklenen_kurallar],
            ozellikler=aday.ozellikler.model_dump(mode="json"),
            model_surumleri=aday.model_surumleri,
            uretim_zamani=aday.uretim_zamani,
            politika_sonucu=politika.sonuc,
            uygulandi=politika.uygulandi,
            otonomi_seviyesi=politika.otonomi_seviyesi,
            risk_skoru=politika.risk_skoru,
            gerekce_kodlari=list(politika.gerekce_kodlari),
        )

    def adaya_cevir(self) -> DecisionCandidate:
        """DB satırından `DecisionCandidate`'i yeniden kurar.

        Faz 2'nin taşıyıcı metodu: gecelik iş gerekçeyi saatler sonra
        ürettiğinde guard'ın ihtiyacı olan `izinli_sayilar()` kümesi buradan
        çıkar. Kayıp veri = yanlış guard kararı, o yüzden alanların tamamı
        DB'de tutuluyor.
        """
        return DecisionCandidate.model_validate(
            {
                "karar_id": self.karar_id,
                "alan": self.alan,
                "tip": self.tip,
                "aksiyon": self.aksiyon,
                "tahmini_tutar_tl": self.tahmini_tutar_tl,
                "geri_alinabilir": self.geri_alinabilir,
                "guven": self.guven,
                "tetiklenen_kurallar": self.tetiklenen_kurallar,
                "ozellikler": self.ozellikler,
                "model_surumleri": self.model_surumleri,
                "uretim_zamani": self.uretim_zamani,
            }
        )

    def politikaya_cevir(self) -> PolitikaKarari:
        """DB satırından `PolitikaKarari`'yi yeniden kurar."""
        return PolitikaKarari(
            karar_id=self.karar_id,
            sonuc=self.politika_sonucu,
            uygulandi=self.uygulandi,
            otonomi_seviyesi=self.otonomi_seviyesi,
            risk_skoru=self.risk_skoru,
            gerekce_kodlari=self.gerekce_kodlari,
        )


class DecisionAudit(KimlikliTablo):
    """Değiştirilemez denetim izi — bir karar/gerekçe olayı = bir satır.

    KURAL: denetim kaydı olmayan bir karar yolu merge edilmez. B1.3'te bu
    tabloya tek çağrıyla satır yazan fonksiyon gelecek.
    """

    __tablename__ = "decision_audit"

    karar_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("decision.karar_id", ondelete="CASCADE"), index=True
    )

    # Girdi anlık görüntüsünün SHA-256'sı (64 hex karakter). Aynı girdiye aynı
    # kararı verdiğimizi kanıtlar; girdi değiştiyse hash değişir.
    girdi_hash: Mapped[str] = mapped_column(sa.String(64), index=True)

    tetiklenen_kurallar: Mapped[list[dict[str, Any]]]
    model_surumleri: Mapped[dict[str, Any]]
    cikti: Mapped[dict[str, Any]]

    # Gerekçe hiç üretilmediyse ATLANDI — "guard çalışmadı" ile "guard geçti"
    # asla karışmasın diye ayrı bir değer.
    guard_sonucu: Mapped[GuardSonucu] = mapped_column(
        enum_kolonu(GuardSonucu), default=GuardSonucu.ATLANDI, index=True
    )
    reddedilen_sayilar: Mapped[list[float]] = mapped_column(default=list)

    zaman: Mapped[datetime] = mapped_column(default=datetime.now, index=True)

    karar: Mapped[Decision] = relationship(back_populates="audit_kayitlari")
