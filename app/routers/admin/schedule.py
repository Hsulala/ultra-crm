from datetime import date as date_cls
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import SHIFT_LABELS, AdminUser, Member, Schedule
from app.schemas.schedule import PublishMonthRequest, ScheduleAssignRequest, ScheduleResponse
from app.services.schedule_service import ScheduleError, month_bounds, assign_shift, publish_month
from app.templating import templates

router = APIRouter(prefix="/admin/schedule", tags=["admin-schedule"])


@router.get("/page")
def schedule_page(
    request: Request,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    today = date_cls.today()
    start, end = month_bounds(today.year, today.month)
    entries = (
        db.query(Schedule)
        .filter(Schedule.work_date >= start, Schedule.work_date < end)
        .order_by(Schedule.work_date, Schedule.shift)
        .all()
    )
    coach_names = {m.id: m.name for m in db.query(Member).filter(Member.role == "coach").all()}
    admin_names = {a.id: a.username for a in db.query(AdminUser).all()}

    rows = []
    for e in entries:
        assignee = coach_names.get(e.coach_id) if e.coach_id else admin_names.get(e.admin_user_id)
        rows.append(
            {
                "id": e.id,
                "work_date": e.work_date,
                "shift": SHIFT_LABELS.get(e.shift, e.shift),
                "assignee": assignee or "未知",
                "status": "已發布" if e.status == "published" else "草稿",
            }
        )

    coaches = db.query(Member).filter(Member.role == "coach").all()

    return templates.TemplateResponse(
        request,
        "admin/schedule.html",
        {
            "current_user": admin,
            "active": "schedule",
            "today": today,
            "entries": rows,
            "coaches": coaches,
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
