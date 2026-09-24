from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.member_auth import require_member_role
from app.database import get_db
from app.models import Member
from app.schemas.schedule import ScheduleResponse, UnavailabilitySubmitRequest
from app.services.schedule_service import get_published_schedule, submit_unavailability

router = APIRouter(prefix="/api/liff/schedule", tags=["liff-schedule"])


@router.post("/unavailability")
def submit_unavailability_endpoint(
    payload: UnavailabilitySubmitRequest,
    coach: Member = Depends(require_member_role("coach")),
    db: Session = Depends(get_db),
):
    rows = submit_unavailability(
        db,
        coach_id=coach.id,
        target_month=payload.target_month,
        entries=[e.model_dump() for e in payload.entries],
    )
    return {"status": "success", "count": len(rows)}


@router.get("", response_model=List[ScheduleResponse])
def view_schedule(
    year: int,
    month: int,
    coach: Member = Depends(require_member_role("coach")),
    db: Session = Depends(get_db),
):
    # 排班結果所有教練互相可見，不限自己的班
    return get_published_schedule(db, year=year, month=month)
