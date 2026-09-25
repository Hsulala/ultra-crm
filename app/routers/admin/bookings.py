from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin_user
from app.database import get_db
from app.models import AdminUser, Contract
from app.schemas.booking import AdminBookingCreateRequest, BookingResponse
from app.services.booking_service import BookingError, cancel_booking, create_booking
from app.services.capacity_service import CapacityError

router = APIRouter(prefix="/admin/bookings", tags=["admin-bookings"])


@router.post("", response_model=BookingResponse)
def create_booking_endpoint(
    payload: AdminBookingCreateRequest,
    admin: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    """後台版約課：任何登入的後台帳號（店長/櫃檯/教練）都能用，主要給店員在
    教練不方便操作手機時代為登打，或教練自己用電腦排下一堂。area 直接跟著
    合約的課程類型走，不用另外選。"""
    contract = db.get(Contract, payload.contract_id)
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到合約")

    try:
        return create_booking(
            db,
            coach_id=payload.coach_id,
            contract_id=payload.contract_id,
            slot_date=payload.slot_date,
            slot_start_time=payload.slot_start_time,
            area=contract.course_type,
            created_by_id=payload.coach_id,
        )
    except (BookingError, CapacityError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{booking_id}/cancel", response_model=BookingResponse)
def cancel_booking_endpoint(
    booking_id: int,
    admin: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    try:
        return cancel_booking(db, booking_id=booking_id)
    except BookingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
