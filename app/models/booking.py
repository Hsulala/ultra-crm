from datetime import date, time
from typing import Optional

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, Time, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

BOOKING_AREA_LABELS = {
    "strength": "重訓",
    "pilates": "皮拉提斯",
}
BOOKING_STATUS_LABELS = {
    "booked": "已預約",
    "completed": "已完成",
    "cancelled": "已取消",
    "no_show": "未到",
}


class Booking(Base, TimestampMixin):
    """coach_id / venue_coach_id 兩者恰好擇一，跟著 Contract 的教練走
    （皮拉提斯合約可能是場租教練開的，見 app/models/contract.py）。"""

    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("area IN ('strength', 'pilates')", name="ck_bookings_area"),
        CheckConstraint("status IN ('booked', 'completed', 'cancelled', 'no_show')", name="ck_bookings_status"),
        CheckConstraint(
            "(coach_id IS NOT NULL AND venue_coach_id IS NULL) OR (coach_id IS NULL AND venue_coach_id IS NOT NULL)",
            name="ck_bookings_coach_xor_venue_coach",
        ),
        # 防呆：同一教練同時段不可重複被約。用 partial unique index 只管 status='booked'
        # 的那些列，取消/完成的舊紀錄不會擋到之後同時段重新預約。coach_id/venue_coach_id
        # 分開各自一組 index，因為同一時間只會有一邊非 NULL。
        Index(
            "ux_bookings_coach_slot_active",
            "coach_id",
            "slot_date",
            "slot_start_time",
            unique=True,
            postgresql_where=text("status = 'booked' AND coach_id IS NOT NULL"),
            sqlite_where=text("status = 'booked' AND coach_id IS NOT NULL"),
        ),
        Index(
            "ux_bookings_venue_coach_slot_active",
            "venue_coach_id",
            "slot_date",
            "slot_start_time",
            unique=True,
            postgresql_where=text("status = 'booked' AND venue_coach_id IS NOT NULL"),
            sqlite_where=text("status = 'booked' AND venue_coach_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    coach_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"), nullable=True)
    venue_coach_id: Mapped[Optional[int]] = mapped_column(ForeignKey("venue_rental_coaches.id"), nullable=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), nullable=False)
    slot_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_start_time: Mapped[time] = mapped_column(Time, nullable=False)
    area: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="booked")
    # 場租教練開的皮拉提斯合約約課時，可能沒有對應的 Member 可以記，所以放寬允許空值。
    created_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"), nullable=True)
