from datetime import date, datetime
from typing import Optional

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

SHIFT_LABELS = {
    "morning": "早班 09:00-13:00",
    "afternoon": "中班 13:00-18:00",
    "evening": "晚班 18:00-22:00",
}
SHIFT_CHECK = "shift IN ('morning', 'afternoon', 'evening')"


class CoachUnavailability(Base):
    """教練每月22號前回報下月「不排班」時段。"""

    __tablename__ = "coach_unavailabilities"
    __table_args__ = (CheckConstraint(SHIFT_CHECK, name="ck_coach_unavailabilities_shift"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    coach_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    target_month: Mapped[date] = mapped_column(Date, nullable=False)  # 該月第一天，標示這筆是哪個月份的回報
    unavailable_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Schedule(Base, TimestampMixin):
    """每個班可以有多筆列（同班可能同時有教練跟櫃檯，或多位教練）。"""

    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint(SHIFT_CHECK, name="ck_schedules_shift"),
        CheckConstraint("status IN ('draft', 'published')", name="ck_schedules_status"),
        CheckConstraint(
            "(coach_id IS NOT NULL) != (admin_user_id IS NOT NULL)",
            name="ck_schedules_exactly_one_assignee",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift: Mapped[str] = mapped_column(String, nullable=False)
    coach_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"), nullable=True)
    admin_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
