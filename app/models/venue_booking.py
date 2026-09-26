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
    只留姓名/電話當識別。皮拉提斯名額跟一般學員共用同一個上限
    （見 app/services/capacity_service.py）。

    跟一般教練不同：場租教練同一個時段可以同時接好幾組客人（他們是
    租場地做自己的事，不是綁死一對一/一對二），所以這裡刻意不像
    Booking 一樣加「同時段只能一筆」的限制。"""

    __tablename__ = "venue_bookings"
    __table_args__ = (
        CheckConstraint("area IN ('strength', 'pilates')", name="ck_venue_bookings_area"),
        CheckConstraint("status IN ('booked', 'completed', 'cancelled')", name="ck_venue_bookings_status"),
        CheckConstraint("party_size IN (1, 2)", name="ck_venue_bookings_party_size"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    venue_coach_id: Mapped[int] = mapped_column(ForeignKey("venue_rental_coaches.id"), nullable=False)
    customer_name: Mapped[str] = mapped_column(String, nullable=False)
    customer_phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    slot_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot_start_time: Mapped[time] = mapped_column(Time, nullable=False)
    area: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="booked")
