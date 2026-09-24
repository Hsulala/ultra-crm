"""皮拉提斯器械名額容量檢查：全館單一時段上限 4 個名額，機器算名額，
1對2 預約一次佔用 2 個名額。一般學員的 Booking 跟場租教練的 VenueBooking
共用同一個上限，這裡兩張表都要算進去。

用 Postgres advisory lock 鎖住「這個時段」，鎖內即時 SUM 已訂名額，
不用維護一張容易跟 cancel/refund 失同步的計數器表。SQLite（本機開發）
沒有 advisory lock，用不到並發保護，直接跳過上鎖。
"""

import hashlib
from datetime import date, time

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Booking, ContractMember, VenueBooking

PILATES_CAPACITY = 4


class CapacityError(Exception):
    pass


def _advisory_lock_key(slot_date: date, slot_start_time: time) -> int:
    raw = f"pilates:{slot_date.isoformat()}:{slot_start_time.isoformat()}"
    # pg_advisory_xact_lock 吃 bigint，取 md5 前 8 碼轉數字，範圍夠小又幾乎不會撞。
    return int(hashlib.md5(raw.encode()).hexdigest()[:8], 16)


def _acquire_slot_lock(db: Session, slot_date: date, slot_start_time: time) -> None:
    if db.bind.dialect.name != "postgresql":
        return
    key = _advisory_lock_key(slot_date, slot_start_time)
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def contract_unit_count(db: Session, contract_id: int) -> int:
    """1對2 合約佔 2 個名額，一般合約佔 1 個。"""
    count = db.query(ContractMember).filter(ContractMember.contract_id == contract_id).count()
    return 2 if count >= 2 else 1


def reserve_pilates_capacity(db: Session, *, slot_date: date, slot_start_time: time, units: int) -> None:
    """在交易內鎖住這個時段，確認名額夠用。呼叫端要在同一個 db session/transaction
    裡緊接著寫入 Booking，鎖才會涵蓋到寫入為止（db.commit() 會釋放 advisory lock）。"""
    _acquire_slot_lock(db, slot_date, slot_start_time)

    used = 0
    bookings = (
        db.query(Booking)
        .filter(
            Booking.area == "pilates",
            Booking.slot_date == slot_date,
            Booking.slot_start_time == slot_start_time,
            Booking.status == "booked",
        )
        .all()
    )
    for booking in bookings:
        used += contract_unit_count(db, booking.contract_id)

    venue_bookings = (
        db.query(VenueBooking)
        .filter(
            VenueBooking.area == "pilates",
            VenueBooking.slot_date == slot_date,
            VenueBooking.slot_start_time == slot_start_time,
            VenueBooking.status == "booked",
        )
        .all()
    )
    for venue_booking in venue_bookings:
        used += venue_booking.party_size

    if used + units > PILATES_CAPACITY:
        raise CapacityError(f"該時段皮拉提斯名額已滿（目前 {used}/{PILATES_CAPACITY}，還需要 {units} 個名額）")
