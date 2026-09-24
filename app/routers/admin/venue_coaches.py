from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import AdminUser, VenueRentalCoach
from app.schemas.member import BindingCodeResponse
from app.schemas.venue_booking import VenueCoachCreateRequest, VenueCoachResponse
from app.services.binding_service import generate_binding_code

router = APIRouter(prefix="/admin/venue-coaches", tags=["admin-venue-coaches"])


@router.post("", response_model=VenueCoachResponse)
def create_venue_coach(
    payload: VenueCoachCreateRequest,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    coach = VenueRentalCoach(name=payload.name, phone=payload.phone)
    db.add(coach)
    db.commit()
    db.refresh(coach)
    return coach


@router.post("/{venue_coach_id}/binding-code", response_model=BindingCodeResponse)
def issue_venue_coach_binding_code(
    venue_coach_id: int,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    coach = db.get(VenueRentalCoach, venue_coach_id)
    if coach is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到場租教練")

    return generate_binding_code(db, venue_coach_id=venue_coach_id, created_by_admin_id=admin.id)
