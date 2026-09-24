from datetime import date, time
from typing import Optional

from sqlalchemy.orm import Session

from app.models import VenueBooking
from app.services.capacity_service import reserve_pilates_capacity


class VenueBookingError(Exception):
    pass


def create_venue_booking(
    db: Session,
    *,
    venue_coach_id: int,
    customer_name: str,
    customer_phone: Optional[str],
    party_size: int,
    slot_date: date,
    slot_start_time: time,
    area: str,
) -> VenueBooking:
    if area not in ("strength", "pilates"):
        raise VenueBookingError("area 必須是 strength 或 pilates")
    if party_size not in (1, 2):
        raise VenueBookingError("party_size 只能是 1 或 2")

    existing = (
        db.query(VenueBooking)
        .filter(
            VenueBooking.venue_coach_id == venue_coach_id,
            VenueBooking.slot_date == slot_date,
            VenueBooking.slot_start_time == slot_start_time,
            VenueBooking.status == "booked",
        )
        .first()
    )
    if existing:
        raise VenueBookingError("這個時段已經有其他預約了")

    if area == "pilates":
        reserve_pilates_capacity(db, slot_date=slot_date, slot_start_time=slot_start_time, units=party_size)

    booking = VenueBooking(
        venue_coach_id=venue_coach_id,
        customer_name=customer_name,
        customer_phone=customer_phone,
        party_size=party_size,
        slot_date=slot_date,
        slot_start_time=slot_start_time,
        area=area,
        status="booked",
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking
