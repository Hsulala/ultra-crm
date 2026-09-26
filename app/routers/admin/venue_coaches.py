from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import AdminUser, VenueRentalCoach
from app.schemas.member import BindingCodeResponse
from app.schemas.venue_booking import VenueCoachCreateRequest, VenueCoachResponse, VenueCoachUpdateRequest
from app.services.binding_service import generate_binding_code
from app.services.venue_coach_service import (
    VenueCoachError,
    create_venue_coach,
    list_venue_coaches,
    set_venue_coach_active,
    update_venue_coach,
)
from app.templating import templates

router = APIRouter(prefix="/admin/venue-coaches", tags=["admin-venue-coaches"])


@router.get("/page")
def venue_coaches_page(
    request: Request,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    coaches = list_venue_coaches(db)
    return templates.TemplateResponse(
        request,
        "admin/venue_coaches.html",
        {
            "current_user": admin,
            "active": "venue-coaches",
            "coaches": coaches,
        },
    )


@router.post("", response_model=VenueCoachResponse)
def create_venue_coach_endpoint(
    payload: VenueCoachCreateRequest,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    return create_venue_coach(db, name=payload.name, phone=payload.phone)


@router.post("/{venue_coach_id}", response_model=VenueCoachResponse)
def update_venue_coach_endpoint(
    venue_coach_id: int,
    payload: VenueCoachUpdateRequest,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    try:
        return update_venue_coach(db, coach_id=venue_coach_id, name=payload.name, phone=payload.phone)
    except VenueCoachError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/{venue_coach_id}/deactivate")
def deactivate_venue_coach_endpoint(
    venue_coach_id: int,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    try:
        set_venue_coach_active(db, coach_id=venue_coach_id, is_active=False)
    except VenueCoachError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "success"}


@router.post("/{venue_coach_id}/activate")
def activate_venue_coach_endpoint(
    venue_coach_id: int,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    try:
        set_venue_coach_active(db, coach_id=venue_coach_id, is_active=True)
    except VenueCoachError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "success"}


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
