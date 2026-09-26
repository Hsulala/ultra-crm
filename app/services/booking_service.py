from datetime import date, time
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import Booking, Contract, Member, Schedule, VenueBooking, VenueRentalCoach
from app.services.capacity_service import (
    CapacityError,
    contract_unit_count,
    get_pilates_usage,
    reserve_pilates_capacity,
)
from app.services.contract_service import get_active_contracts_for_coach, get_members_for_contract
from app.services.venue_booking_service import get_venue_bookings_for_date

DAY_GRID_HOURS = [time(h, 0) for h in range(8, 22)]  # 08:00 ~ 21:00，跟現行紙本班表範圍一致
SHIFT_SHORT_LABELS = {"morning": "早", "afternoon": "中", "evening": "晚"}


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


def get_bookings_for_date(db: Session, slot_date: date) -> List[Booking]:
    """總覽/班表網格用：當天所有教練的預約，不限特定一位教練。"""
    return (
        db.query(Booking)
        .filter(Booking.slot_date == slot_date, Booking.status == "booked")
        .order_by(Booking.slot_start_time)
        .all()
    )


def build_day_grid(db: Session, target_date: date) -> Dict:
    """總覽頁跟教練自己看班表共用的「教練 × 時段」網格資料。比照現行紙本班表：
    一列一個時段，一欄一位教練，欄位頂端顯示當天班別，格子裡顯示已約的學員，
    空格可以直接選合約約進去——店員/教練都能用同一個畫面看班表兼約課。"""
    coaches = db.query(Member).filter(Member.role == "coach", Member.is_active == True).all()  # noqa: E712

    schedules = db.query(Schedule).filter(Schedule.work_date == target_date, Schedule.coach_id.isnot(None)).all()
    shifts_by_coach: Dict[int, List[str]] = {}
    for s in schedules:
        shifts_by_coach.setdefault(s.coach_id, []).append(s.shift)

    bookings = get_bookings_for_date(db, target_date)
    bookings_by_coach_hour: Dict[tuple, List[Booking]] = {}
    for b in bookings:
        bookings_by_coach_hour.setdefault((b.coach_id, b.slot_start_time), []).append(b)

    pilates_usage = {h: get_pilates_usage(db, slot_date=target_date, slot_start_time=h) for h in DAY_GRID_HOURS}

    columns = []
    for coach in coaches:
        shift_labels = [SHIFT_SHORT_LABELS.get(s, s) for s in shifts_by_coach.get(coach.id, [])]

        contract_options = []
        for c in get_active_contracts_for_coach(db, coach.id):
            students = get_members_for_contract(db, c.id)
            course_label = "重訓" if c.course_type == "strength" else "皮拉提斯"
            remaining = c.total_sessions - c.used_sessions
            contract_options.append(
                {
                    "contract_id": c.id,
                    "label": f"{'、'.join(m.name for m in students)}（剩{remaining}堂・{course_label}）",
                }
            )

        cells = {}
        for h in DAY_GRID_HOURS:
            cell_bookings = []
            for b in bookings_by_coach_hour.get((coach.id, h), []):
                students = get_members_for_contract(db, b.contract_id)
                prefix = "PL" if b.area == "pilates" else "PT"
                cell_bookings.append(
                    {"booking_id": b.id, "label": f"{prefix} {'、'.join(m.name for m in students)}"}
                )
            cells[h] = cell_bookings

        columns.append(
            {
                "coach_id": coach.id,
                "coach_name": coach.name,
                "shift_labels": shift_labels,
                "cells": cells,
                "contract_options": contract_options,
            }
        )

    # 場租教練不是一位教練一欄，是比照客戶紙本班表的「自由教練1/2/3」共用檔期——
    # 同一時段最多 3 組場租客人，哪一檔給哪位教練用跟教練是誰無關，所以這裡固定
    # 建 3 個欄位（slot_number），每筆預約的顯示文字才帶教練名字。
    venue_coach_names = {vc.id: vc.name for vc in db.query(VenueRentalCoach).all()}
    venue_bookings = get_venue_bookings_for_date(db, target_date)
    venue_bookings_by_slot_hour: Dict[tuple, List[VenueBooking]] = {}
    for vb in venue_bookings:
        venue_bookings_by_slot_hour.setdefault((vb.slot_number, vb.slot_start_time), []).append(vb)

    venue_columns = []
    for slot_number in (1, 2, 3):
        cells = {}
        for h in DAY_GRID_HOURS:
            cell_bookings = []
            for vb in venue_bookings_by_slot_hour.get((slot_number, h), []):
                coach_name = venue_coach_names.get(vb.venue_coach_id, "?")
                party_note = "(1對2)" if vb.party_size == 2 else ""
                cell_bookings.append(
                    {
                        "booking_id": vb.id,
                        "label": f"{vb.customer_name}／{coach_name}{party_note}",
                        "venue_coach_id": vb.venue_coach_id,
                    }
                )
            cells[h] = cell_bookings
        venue_columns.append({"slot_number": slot_number, "cells": cells})

    return {
        "hours": DAY_GRID_HOURS,
        "columns": columns,
        "venue_columns": venue_columns,
        "pilates_usage": pilates_usage,
    }
