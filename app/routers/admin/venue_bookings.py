from datetime import date, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin_user
from app.database import get_db
from app.models import AdminUser
from app.services.capacity_service import CapacityError
from app.services.venue_booking_service import VenueBookingError, cancel_venue_booking, create_venue_booking

router = APIRouter(prefix="/admin/venue-bookings", tags=["admin-venue-bookings"])


class AdminVenueBookingCreateRequest(BaseModel):
    venue_coach_id: int
    customer_name: str
    party_size: int = 1
    area: str
    slot_date: date
    slot_start_time: time
    slot_number: int
    customer_phone: Optional[str] = None


@router.post("")
def create_venue_booking_endpoint(
    payload: AdminVenueBookingCreateRequest,
    admin: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    try:
        booking = create_venue_booking(
            db,
            venue_coach_id=payload.venue_coach_id,
            customer_name=payload.customer_name,
            customer_phone=payload.customer_phone,
            party_size=payload.party_size,
            slot_date=payload.slot_date,
            slot_start_time=payload.slot_start_time,
            slot_number=payload.slot_number,
            area=payload.area,
        )
    except (VenueBookingError, CapacityError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"status": "success", "id": booking.id}


@router.post("/{booking_id}/cancel")
def cancel_venue_booking_endpoint(
    booking_id: int,
    admin: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    try:
        cancel_venue_booking(db, booking_id=booking_id)
    except VenueBookingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "success"}
