from datetime import date, time
from typing import Optional

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

VENUE_BOOKING_STATUS_LABELS = {
    "booked": "已預約",
    "completed": "已完成",
    "cancelled": "已取消",
}


class VenueBooking(Base, TimestampMixin):
    """場租教練的預約——客人不是會員，沒有 Member/Contract 可以掛，
    只留姓名/電話當識別。場租教練租的是一樓重訓區場地，跟二樓皮拉提斯
    （器械床位、有獨立名額上限，見 app/services/capacity_service.py）是
    完全不同的空間，所以 area 固定只會是 strength。

    比照客戶原本紙本班表：slot_number（1~3）是「自由教練1/2/3」這種共用
    檔期，同一時段最多 3 組場租客人，哪一組用哪個檔期、是哪位教練無關，
    所以不像 Booking 一樣綁死「同一教練同時段只能一筆」，改成綁「同時段
    同檔期只能一筆」（見 ux_venue_bookings_slot_active）。"""

    __tablename__ = "venue_bookings"
    __table_args__ = (
        CheckConstraint("area = 'strength'", name="ck_venue_bookings_area"),
        CheckConstraint("status IN ('booked', 'completed', 'cancelled')", name="ck_venue_bookings_status"),
        CheckConstraint("party_size IN (1, 2)", name="ck_venue_bookings_party_size"),
        CheckConstraint("slot_number IN (1, 2, 3)", name="ck_venue_bookings_slot_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    venue_coach_id: Mapped[int] = mapped_column(ForeignKey("venue_rental_coaches.id"), nullable=False)
    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    customer_phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    slot_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_start_time: Mapped[time] = mapped_column(Time, nullable=False)
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    area: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="booked")
