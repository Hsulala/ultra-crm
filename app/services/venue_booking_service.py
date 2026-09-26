from datetime import date, time
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import VenueBooking

VENUE_SLOT_NUMBERS = (1, 2, 3)


class VenueBookingError(Exception):
    pass


def _booked_slot_numbers(db: Session, *, slot_date: date, slot_start_time: time) -> set:
    rows = (
        db.query(VenueBooking.slot_number)
        .filter(
            VenueBooking.slot_date == slot_date,
            VenueBooking.slot_start_time == slot_start_time,
            VenueBooking.status == "booked",
        )
        .all()
    )
    return {n for (n,) in rows}


def create_venue_booking(
    db: Session,
    *,
    venue_coach_id: int,
    customer_name: str,
    customer_phone: Optional[str],
    party_size: int,
    slot_date: date,
    slot_start_time: time,
    area: str = "strength",
    slot_number: Optional[int] = None,
) -> VenueBooking:
    """slot_number 是總覽頁「自由教練1/2/3」這種共用檔期，跟哪位教練無關。
    後台總覽頁的「+」按鈕會直接指定要佔哪一檔（slot_number）；教練自己用
    LINE 約課沒有欄位可以挑，就自動找當下時段還空著的檔期（滿了就報錯）。

    場租教練是一樓重訓區的場地租借，跟二樓皮拉提斯（器械床位、有獨立名額
    上限）是完全不同的空間，所以這裡固定只收 strength，不像一般 Booking
    還要挑 area、也不會去動皮拉提斯的名額。"""
    if area != "strength":
        raise VenueBookingError("場租教練只租一樓重訓區，area 只能是 strength")
    if party_size not in (1, 2):
        raise VenueBookingError("party_size 只能是 1 或 2")

    booked = _booked_slot_numbers(db, slot_date=slot_date, slot_start_time=slot_start_time)

    if slot_number is None:
        free = [n for n in VENUE_SLOT_NUMBERS if n not in booked]
        if not free:
            raise VenueBookingError(f"這個時段場租名額已滿（{len(VENUE_SLOT_NUMBERS)}/{len(VENUE_SLOT_NUMBERS)}）")
        slot_number = free[0]
    else:
        if slot_number not in VENUE_SLOT_NUMBERS:
            raise VenueBookingError("slot_number 只能是 1、2 或 3")
        if slot_number in booked:
            raise VenueBookingError("這個檔期剛剛已經被約走了，請重新整理頁面")

    booking = VenueBooking(
        venue_coach_id=venue_coach_id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        party_size=party_size,
        slot_date=slot_date,
        slot_start_time=slot_start_time,
        slot_number=slot_number,
        area=area,
        status="booked",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


def cancel_venue_booking(db: Session, *, booking_id: int) -> VenueBooking:
    booking = db.get(VenueBooking, booking_id)
    if booking is None:
        raise VenueBookingError("找不到這筆預約")
    booking.status = "cancelled"
    db.commit()
    db.refresh(booking)
    return booking


def get_venue_bookings_for_date(db: Session, slot_date: date) -> List[VenueBooking]:
    """總覽/班表網格用：當天所有場租教練的預約。"""
    return (
        db.query(VenueBooking)
        .filter(VenueBooking.slot_date == slot_date, VenueBooking.status == "booked")
        .order_by(VenueBooking.slot_start_time)
        .all()
    )
