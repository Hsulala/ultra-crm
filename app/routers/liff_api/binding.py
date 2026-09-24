from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.line_auth import get_line_user_id
from app.database import get_db
from app.schemas.binding import BindingRedeemRequest, BindingRedeemResponse
from app.services.binding_service import BindingError, redeem_binding_code

router = APIRouter(prefix="/api/liff/binding", tags=["liff-binding"])


@router.post("/redeem", response_model=BindingRedeemResponse)
def redeem(
    payload: BindingRedeemRequest,
    line_user_id: str = Depends(get_line_user_id),
    db: Session = Depends(get_db),
):
    try:
        target = redeem_binding_code(db, code=payload.code, line_user_id=line_user_id)
    except BindingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    role = getattr(target, "role", None) or "venue_coach"
    return BindingRedeemResponse(status="success", role=role, name=target.name)
