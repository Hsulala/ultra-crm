from datetime import date

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class ClassRecord(Base, TimestampMixin):
    """教練「紀錄課程」留下的內容記錄，純查詢用，不扣合約堂數。"""

    __tablename__ = "class_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), nullable=False)
    actual_teaching_coach_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    class_date: Mapped[date] = mapped_column(nullable=False)
    content_summary: Mapped[str] = mapped_column(Text, nullable=False)
    logged_by_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
