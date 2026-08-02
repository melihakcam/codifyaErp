"""SQLAlchemy tabloları.

Sahip: Kişi B · Faz 1 B1.1

⚠️ HER tablo burada import edilmek ZORUNDA. Alembic `Base.metadata`'ya bakar;
import edilmeyen bir tablo metadata'ya hiç kaydolmaz, `alembic revision
--autogenerate` onu sessizce atlar ve tablo hiç oluşmaz. Hata mesajı yoktur,
sadece "table not found" alırsın — bu yüzden yeni tablo eklerken ilk iş burası.
"""

from app.models.approval import Approval, Feedback, GeriBildirimTuru, OnayDurumu
from app.models.base import Base
from app.models.decision import Decision, DecisionAudit
from app.models.insight import Insight
from app.models.policy import Policy

__all__ = [
    "Approval",
    "Base",
    "Decision",
    "DecisionAudit",
    "Feedback",
    "GeriBildirimTuru",
    "Insight",
    "OnayDurumu",
    "Policy",
]
