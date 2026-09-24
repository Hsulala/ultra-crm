"""把已驗證的 LINE userId 解析成實際的 Member/VenueRentalCoach 身分。

未綁定的訪客會直接被擋掉（403）——只有綁定流程本身（app/routers/liff_api/binding.py）
會直接使用 get_line_user_id，不需要先解析出身分。
"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.line_auth import get_line_user_id
from app.database import get_db
from app.models import Member, VenueRentalCoach


def get_current_member(
    line_user_id: str = Depends(get_line_user_id),
    db: Session = Depends(get_db),
) -> Member:
    member = db.query(Member).filter(Member.line_user_id == line_user_id, Member.is_active == True).first()  # noqa: E712
    if member is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "尚未綁定，請先完成會員/教練綁定")
    return member


def require_member_role(*roles: str):
    def _check(member: Member = Depends(get_current_member)) -> Member:
        if member.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "沒有權限使用此功能")
        return member

    return _check


def get_current_venue_coach(
    line_user_id: str = Depends(get_line_user_id),
    db: Session = Depends(get_db),
) -> VenueRentalCoach:
    """場租教練是獨立身分，不算會員，走自己的一套解析——絕對不會跟 Member 混在一起。"""
    coach = (
        db.query(VenueRentalCoach)
        .filter(VenueRentalCoach.line_user_id == line_user_id, VenueRentalCoach.is_active == True)  # noqa: E712
        .first()
    )
    if coach is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "尚未綁定場租教練身分")
    return coach
