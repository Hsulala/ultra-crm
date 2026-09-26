from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import VenueRentalCoach


class VenueCoachError(Exception):
    pass


def list_venue_coaches(db: Session) -> List[VenueRentalCoach]:
    """管理頁用：連停用的也列出來，跟總覽頁只抓 is_active 的不一樣。"""
    return db.query(VenueRentalCoach).order_by(VenueRentalCoach.is_active.desc(), VenueRentalCoach.name).all()


def create_venue_coach(db: Session, *, name: str, phone: Optional[str] = None) -> VenueRentalCoach:
    coach = VenueRentalCoach(name=name.strip(), phone=phone)
    db.add(coach)
    db.commit()
    db.refresh(coach)
    return coach


def update_venue_coach(db: Session, *, coach_id: int, name: str, phone: Optional[str] = None) -> VenueRentalCoach:
    coach = db.get(VenueRentalCoach, coach_id)
    if coach is None:
        raise VenueCoachError("找不到場租教練")
    coach.name = name.strip()
    coach.phone = phone
    db.commit()
    db.refresh(coach)
    return coach


def set_venue_coach_active(db: Session, *, coach_id: int, is_active: bool) -> VenueRentalCoach:
    coach = db.get(VenueRentalCoach, coach_id)
    if coach is None:
        raise VenueCoachError("找不到場租教練")
    coach.is_active = is_active
    db.commit()
    db.refresh(coach)
    return coach
