from datetime import date, time
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import Booking, Contract, Member, Schedule, VenueBooking, VenueRentalCoach
from app.services.capacity_service import contract_unit_count, reserve_pilates_capacity
from app.services.contract_service import (
    get_active_contracts_for_coach,
    get_active_pilates_contracts,
    get_members_for_contract,
)
from app.services.venue_booking_service import get_venue_bookings_for_date

DAY_GRID_HOURS = [time(h, 0) for h in range(8, 22)]  # 08:00 ~ 21:00，跟現行紙本班表範圍一致
SHIFT_SHORT_LABELS = {"morning": "早", "afternoon": "中", "evening": "晚"}


class BookingError(Exception):
    pass


def create_booking(
    db: Session,
    *,
    contract_id: int,
    slot_date: date,
    slot_start_time: time,
    area: str,
    created_by_id: Optional[int] = None,
    coach_id: Optional[int] = None,
) -> Booking:
    """coach_id 不填的話直接跟著合約的教練走（見 Contract.coach_id/venue_coach_id）
    ——皮拉提斯合約可能是場租教練開的，這種情況呼叫端通常也答不出「coach_id」。"""
    if area not in ("strength", "pilates"):
        raise BookingError("area 必須是 strength 或 pilates")

    contract = db.get(Contract, contract_id)
    if contract is None or contract.status != "active":
        raise BookingError("找不到有效（進行中）的合約")

    venue_coach_id = None
    if coach_id is None:
        coach_id = contract.coach_id
        venue_coach_id = contract.venue_coach_id

    # 防呆：同一教練（不管是店內正職還是場租教練）同時段不可重複被約。
    # partial unique index 是最後一道防線，這裡先查一次是為了給前端可讀的錯誤訊息。
    existing_filter = (
        (Booking.coach_id == coach_id) if coach_id is not None else (Booking.venue_coach_id == venue_coach_id)
    )
    existing = (
        db.query(Booking)
        .filter(
            existing_filter,
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
        venue_coach_id=venue_coach_id,
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
    """總覽頁跟教練自己看班表共用的網格資料。比照現行紙本班表：一列一個時段，
    店內正職教練一人一欄（只放重訓，皮拉提斯改走下面的共用欄位），場租教練
    是「自由教練1/2/3」共用檔期（重訓場地租借），皮拉提斯是另一個共用欄位
    （店內正職、場租教練都可能開皮拉提斯合約，見 Contract 的說明）。"""
    coaches = db.query(Member).filter(Member.role == "coach", Member.is_active == True).all()  # noqa: E712

    schedules = db.query(Schedule).filter(Schedule.work_date == target_date, Schedule.coach_id.isnot(None)).all()
    shifts_by_coach: Dict[int, List[str]] = {}
    for s in schedules:
        shifts_by_coach.setdefault(s.coach_id, []).append(s.shift)

    bookings = get_bookings_for_date(db, target_date)
    strength_bookings_by_coach_hour: Dict[tuple, List[Booking]] = {}
    pilates_bookings_by_hour: Dict[time, List[Booking]] = {h: [] for h in DAY_GRID_HOURS}
    for b in bookings:
        if b.area == "pilates":
            pilates_bookings_by_hour.setdefault(b.slot_start_time, []).append(b)
        elif b.coach_id is not None:
            strength_bookings_by_coach_hour.setdefault((b.coach_id, b.slot_start_time), []).append(b)

    columns = []
    for coach in coaches:
        shift_labels = [SHIFT_SHORT_LABELS.get(s, s) for s in shifts_by_coach.get(coach.id, [])]

        contract_options = []
        for c in get_active_contracts_for_coach(db, coach.id):
            if c.course_type != "strength":
                continue
            students = get_members_for_contract(db, c.id)
            remaining = c.total_sessions - c.used_sessions
            contract_options.append(
                {
                    "contract_id": c.id,
                    "label": f"{'、'.join(m.name for m in students)}（剩{remaining}堂）",
                }
            )

        cells = {}
        for h in DAY_GRID_HOURS:
            cell_bookings = []
            for b in strength_bookings_by_coach_hour.get((coach.id, h), []):
                students = get_members_for_contract(db, b.contract_id)
                cell_bookings.append(
                    {"booking_id": b.id, "label": "、".join(m.name for m in students)}
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

    # 皮拉提斯是共用欄位（器械床位上限 4，不分店內正職／場租教練哪位教），
    # 顯示格式跟自由教練一樣「學員／教練」，capacity 由 reserve_pilates_capacity 把關。
    member_coach_names = {c.id: c.name for c in coaches}
    pilates_contract_options = []
    for c in get_active_pilates_contracts(db):
        students = get_members_for_contract(db, c.id)
        remaining = c.total_sessions - c.used_sessions
        if c.coach_id is not None:
            coach_label = member_coach_names.get(c.coach_id, "?")
        else:
            coach_label = f"{venue_coach_names.get(c.venue_coach_id, '?')}（場租）"
        pilates_contract_options.append(
            {
                "contract_id": c.id,
                "label": f"{'、'.join(m.name for m in students)}（{coach_label}・剩{remaining}堂）",
            }
        )

    pilates_cells = {}
    for h in DAY_GRID_HOURS:
        cell_bookings = []
        for b in pilates_bookings_by_hour.get(h, []):
            students = get_members_for_contract(db, b.contract_id)
            if b.coach_id is not None:
                coach_name = member_coach_names.get(b.coach_id, "?")
            else:
                coach_name = venue_coach_names.get(b.venue_coach_id, "?")
            party_note = "(1對2)" if len(students) >= 2 else ""
            cell_bookings.append(
                {
                    "booking_id": b.id,
                    "label": f"{'、'.join(m.name for m in students)}／{coach_name}{party_note}",
                }
            )
        pilates_cells[h] = cell_bookings

    return {
        "hours": DAY_GRID_HOURS,
        "columns": columns,
        "venue_columns": venue_columns,
        "pilates_cells": pilates_cells,
        "pilates_contract_options": pilates_contract_options,
    }
