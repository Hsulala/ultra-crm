from datetime import date, time
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import Booking, Contract
from app.services.capacity_service import CapacityError, contract_unit_count, reserve_pilates_capacity


class BookingError(Exception):
    pass


def create_booking(
    db: Session,
    *,
    coach_id: int,
    contract_id: int,
    slot_date: date,
    slot_start_time: time,
    area: str,
    created_by_id: int,
) -> Booking:
    if area not in ("strength", "pilates"):
        raise BookingError("area 必須是 strength 或 pilates")

    contract = db.get(Contract, contract_id)
    if contract is None or contract.status != "active":
        raise BookingError("找不到有效（進行中）的合約")

    # 防呆：同一教練同時段不可重複被約。partial unique index 是最後一道防線，
    # 這裡先查一次是為了給前端一個可讀的錯誤訊息，而不是等 DB 丟 IntegrityError。
    existing = (
        db.query(Booking)
        .filter(
            Booking.coach_id == coach_id,
            Booking.slot_date == slot_date,
            Booking.slot_start_time == slot_start_time,
            Booking.status == "booked",
        )
        .first()
    )
    if existing:
        raise BookingError("這位教練在這個時段已經有其他預約了")

    if area == "pilates":
        units = contract_unit_count(db, contract_id)
        reserve_pilates_capacity(db, slot_date=slot_date, slot_start_time=slot_start_time, units=units)

    booking = Booking(
        coach_id=coach_id,
        contract_id=contract_id,
        slot_date=slot_date,
        slot_start_time=slot_start_time,
        area=area,
        status="booked",
        created_by_id=created_by_id,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


def cancel_booking(db: Session, *, booking_id: int) -> Booking:
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise BookingError("找不到這筆預約")
    booking.status = "cancelled"
    db.commit()
    db.refresh(booking)
    return booking


def get_bookings_for_coach(db: Session, coach_id: int, *, slot_date: Optional[date] = None) -> List[Booking]:
    query = db.query(Booking).filter(Booking.coach_id == coach_id, Booking.status == "booked")
    if slot_date is not None:
        query = query.filter(Booking.slot_date == slot_date)
    return query.order_by(Booking.slot_date, Booking.slot_start_time).all()
