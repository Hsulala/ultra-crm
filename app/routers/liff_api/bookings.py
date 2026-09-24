from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.member_auth import get_current_member, require_member_role
from app.database import get_db
from app.models import ContractMember, Member
from app.schemas.booking import BookingCreateRequest, BookingResponse
from app.services.booking_service import BookingError, create_booking, get_bookings_for_coach
from app.services.capacity_service import CapacityError

router = APIRouter(prefix="/api/liff/bookings", tags=["liff-bookings"])


@router.get("/mine", response_model=List[BookingResponse])
def my_bookings_as_coach(
    coach: Member = Depends(require_member_role("coach")),
    db: Session = Depends(get_db),
):
    return get_bookings_for_coach(db, coach.id)


@router.post("", response_model=BookingResponse)
def create_booking_endpoint(
    payload: BookingCreateRequest,
    member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    # 教練跟學員都可以發起約課；學員只能替自己（或自己所在的合約）約，
    # 教練則可以代學員約課，或替自己排班。
    if member.role == "student":
        is_party = (
            db.query(ContractMember)
            .filter(ContractMember.contract_id == payload.contract_id, ContractMember.member_id == member.id)
            .first()
        )
        if not is_party:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "這不是您的合約，無法約課")

    try:
        return create_booking(
            db,
            coach_id=payload.coach_id,
            contract_id=payload.contract_id,
            slot_date=payload.slot_date,
            slot_start_time=payload.slot_start_time,
            area=payload.area,
            created_by_id=member.id,
        )
    except (BookingError, CapacityError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
