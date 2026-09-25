import calendar
from datetime import date as date_cls
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import AdminUser, Member, Schedule
from app.schemas.schedule import PublishMonthRequest, ScheduleAssignRequest, ScheduleResponse
from app.services.schedule_service import ScheduleError, month_bounds, assign_shift, publish_month
from app.templating import templates

router = APIRouter(prefix="/admin/schedule", tags=["admin-schedule"])


SHIFT_ORDER = ["morning", "afternoon", "evening"]
SHIFT_SHORT_LABELS = {"morning": "早", "afternoon": "中", "evening": "晚"}


@router.get("/page")
def schedule_page(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    today = date_cls.today()
    year = year or today.year
    month = month or today.month

    start, end = month_bounds(year, month)
    entries = (
        db.query(Schedule)
        .filter(Schedule.work_date >= start, Schedule.work_date < end)
        .order_by(Schedule.work_date, Schedule.shift)
        .all()
    )
    coach_names = {m.id: m.name for m in db.query(Member).filter(Member.role == "coach").all()}
    admin_names = {a.id: a.username for a in db.query(AdminUser).all()}

    by_day = {}
    for e in entries:
        assignee = coach_names.get(e.coach_id) if e.coach_id else admin_names.get(e.admin_user_id)
        by_day.setdefault(e.work_date, []).append(
            {
                "shift_short": SHIFT_SHORT_LABELS.get(e.shift, e.shift),
                "shift": e.shift,
                "assignee": assignee or "未知",
                "status": e.status,
            }
        )
    for day_entries in by_day.values():
        day_entries.sort(key=lambda x: SHIFT_ORDER.index(x["shift"]) if x["shift"] in SHIFT_ORDER else 99)

    cal = calendar.Calendar(firstweekday=0)  # 週一開頭
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        week_cells = []
        for day in week:
            week_cells.append(
                {
                    "date": day,
                    "in_month": day.month == month,
                    "is_today": day == today,
                    "entries": by_day.get(day, []),
                }
            )
        weeks.append(week_cells)

    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    next_month = 1 if month == 12 else month + 1
    next_year = year + 1 if month == 12 else year

    coaches = db.query(Member).filter(Member.role == "coach").all()

    return templates.TemplateResponse(
        request,
        "admin/schedule.html",
        {
            "current_user": admin,
            "active": "schedule",
            "today": today,
            "year": year,
            "month": month,
            "weeks": weeks,
            "coaches": coaches,
            "prev_year": prev_year,
            "prev_month": prev_month,
            "next_year": next_year,
            "next_month": next_month,
        },
    )


@router.get("", response_model=List[ScheduleResponse])
def list_schedule(
    year: int,
    month: int,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    start, end = month_bounds(year, month)
    return (
        db.query(Schedule)
        .filter(Schedule.work_date >= start, Schedule.work_date < end)
        .order_by(Schedule.work_date, Schedule.shift)
        .all()
    )


@router.post("", response_model=ScheduleResponse)
def assign_shift_endpoint(
    payload: ScheduleAssignRequest,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    try:
        return assign_shift(
            db,
            work_date=payload.work_date,
            shift=payload.shift,
            coach_id=payload.coach_id,
            admin_user_id=payload.admin_user_id,
        )
    except ScheduleError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/publish")
def publish_month_endpoint(
    payload: PublishMonthRequest,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    count = publish_month(db, year=payload.year, month=payload.month)
    return {"status": "success", "published_count": count}
