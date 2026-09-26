from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.member_auth import get_current_venue_coach
from app.database import get_db
from app.models import VenueRentalCoach
from app.schemas.venue_booking import VenueBookingCreateRequest, VenueBookingResponse
from app.services.venue_booking_service import VenueBookingError, create_venue_booking

# 獨立約課入口，跟一般學員/教練約課完全分開，符合規格「場租教練版：獨立圖文選單 +
# 獨立約課入口」的要求。
router = APIRouter(prefix="/api/liff/venue-bookings", tags=["liff-venue-bookings"])


@router.post("", response_model=VenueBookingResponse)
def create_venue_booking_endpoint(
    payload: VenueBookingCreateRequest,
    venue_coach: VenueRentalCoach = Depends(get_current_venue_coach),
    db: Session = Depends(get_db),
):
    try:
        return create_venue_booking(
            db,
            venue_coach_id=venue_coach.id,
            customer_name=payload.customer_name,
            customer_phone=payload.customer_phone,
            party_size=payload.party_size,
            slot_date=payload.slot_date,
            slot_start_time=payload.slot_start_time,
            area=payload.area,
        )
    except VenueBookingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
