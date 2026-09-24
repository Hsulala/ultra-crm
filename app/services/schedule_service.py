from datetime import date, datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import CoachUnavailability, Schedule

UNAVAILABILITY_DEADLINE_DAY = 22


class ScheduleError(Exception):
    pass


def submit_unavailability(
    db: Session,
    *,
    coach_id: int,
    target_month: date,
    entries: List[dict],
) -> List[CoachUnavailability]:
    """entries: [{"unavailable_date": date, "shift": str, "note": Optional[str]}, ...]
    同一教練同一個月重新提交會整批覆蓋掉舊的回報，避免新舊資料混在一起。"""
    db.query(CoachUnavailability).filter(
        CoachUnavailability.coach_id == coach_id,
        CoachUnavailability.target_month == target_month,
    ).delete()

    now = datetime.now(timezone.utc)
    rows = [
        CoachUnavailability(
            coach_id=coach_id,
            target_month=target_month,
            unavailable_date=entry["unavailable_date"],
            shift=entry["shift"],
            note=entry.get("note"),
            submitted_at=now,
        )
        for entry in entries
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def is_submission_late(target_month: date, submitted_at: datetime) -> bool:
    """每月22號前回報下月班表——只回傳布林值給呼叫端當警告用，不擋提交
    （例外狀況店長還是可能需要教練臨時補交）。"""
    first_of_target = target_month.replace(day=1)
    if first_of_target.month == 1:
        deadline = date(first_of_target.year - 1, 12, UNAVAILABILITY_DEADLINE_DAY)
    else:
        deadline = date(first_of_target.year, first_of_target.month - 1, UNAVAILABILITY_DEADLINE_DAY)
    return submitted_at.date() > deadline


def assign_shift(
    db: Session,
    *,
    work_date: date,
    shift: str,
    coach_id: Optional[int] = None,
    admin_user_id: Optional[int] = None,
) -> Schedule:
    if (coach_id is None) == (admin_user_id is None):
        raise ScheduleError("coach_id 跟 admin_user_id 必須恰好指定一個")

    entry = Schedule(work_date=work_date, shift=shift, coach_id=coach_id, admin_user_id=admin_user_id, status="draft")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def month_bounds(year: int, month: int):
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def publish_month(db: Session, *, year: int, month: int) -> int:
    start, end = month_bounds(year, month)
    rows = (
        db.query(Schedule)
        .filter(Schedule.work_date >= start, Schedule.work_date < end, Schedule.status == "draft")
        .all()
    )
    for row in rows:
        row.status = "published"
    db.commit()
    return len(rows)


def get_published_schedule(db: Session, *, year: int, month: int) -> List[Schedule]:
    start, end = month_bounds(year, month)
    return (
        db.query(Schedule)
        .filter(Schedule.work_date >= start, Schedule.work_date < end, Schedule.status == "published")
        .order_by(Schedule.work_date, Schedule.shift)
        .all()
    )
