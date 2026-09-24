from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

BINDING_CODE_STATUS_LABELS = {
    "active": "有效",
    "used": "已使用",
    "expired": "已過期",
    "revoked": "已作廢",
}


class BindingCode(Base, TimestampMixin):
    __tablename__ = "binding_codes"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'used', 'expired', 'revoked')", name="ck_binding_codes_status"),
        CheckConstraint(
            "(member_id IS NOT NULL) != (venue_coach_id IS NOT NULL)",
            name="ck_binding_codes_exactly_one_target",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    member_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"), nullable=True)
    venue_coach_id: Mapped[Optional[int]] = mapped_column(ForeignKey("venue_rental_coaches.id"), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
