from datetime import date, time

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
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("area IN ('strength', 'pilates')", name="ck_bookings_area"),
        CheckConstraint("status IN ('booked', 'completed', 'cancelled', 'no_show')", name="ck_bookings_status"),
        # 防呆：同一教練同時段不可重複被約。用 partial unique index 只管 status='booked'
        # 的那些列，取消/完成的舊紀錄不會擋到之後同時段重新預約。
        Index(
            "ux_bookings_coach_slot_active",
            "coach_id",
            "slot_date",
            "slot_start_time",
            unique=True,
            postgresql_where=text("status = 'booked'"),
            sqlite_where=text("status = 'booked'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    coach_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), nullable=False)
    slot_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_start_time: Mapped[time] = mapped_column(Time, nullable=False)
    area: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="booked")
    created_by_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
