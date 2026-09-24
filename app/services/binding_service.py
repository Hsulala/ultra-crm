"""綁定碼產生/兌換/過期，以及解綁邏輯。

解綁不是單一布林值翻轉，而是由多種事件觸發（會籍到期、教練離職、堂數用罄）。
這裡先提供 unbind_member() 這個共用入口，之後夜間掃描（app/services/scheduler.py）
跟合約異動事件都呼叫它，行為才會一致。
"""

import random
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from sqlalchemy.orm import Session

from app.models import BindingCode, Member, VenueRentalCoach
from app.services import line_client
from app.services.rich_menu import rich_menu_id_for_role

BINDING_CODE_TTL_MINUTES = 30


class BindingError(Exception):
    pass


def _generate_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def _as_aware_utc(dt: datetime) -> datetime:
    # SQLite 不會保留 tz 資訊，讀回來的 datetime 會變成 naive；
    # Postgres（正式環境）則沒有這個問題。統一補上 UTC 才能安全比較。
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def generate_binding_code(
    db: Session,
    *,
    member_id: Optional[int] = None,
    venue_coach_id: Optional[int] = None,
    created_by_admin_id: Optional[int] = None,
) -> BindingCode:
    if (member_id is None) == (venue_coach_id is None):
        raise BindingError("member_id 跟 venue_coach_id 必須恰好指定一個")

    # 同一個對象若還有其他有效碼，先作廢，避免同時存在多組可用碼造成混淆
    query = db.query(BindingCode).filter(BindingCode.status == "active")
    if member_id is not None:
        query = query.filter(BindingCode.member_id == member_id)
    else:
        query = query.filter(BindingCode.venue_coach_id == venue_coach_id)
    for stale in query.all():
        stale.status = "revoked"

    code = BindingCode(
        code=_generate_code(),
        member_id=member_id,
        venue_coach_id=venue_coach_id,
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=BINDING_CODE_TTL_MINUTES),
        created_by_admin_id=created_by_admin_id,
    )
    db.add(code)
    db.commit()
    db.refresh(code)
    return code


def redeem_binding_code(db: Session, *, code: str, line_user_id: str) -> Union[Member, VenueRentalCoach]:
    binding = (
        db.query(BindingCode)
        .filter(BindingCode.code == code, BindingCode.status == "active")
        .order_by(BindingCode.created_at.desc())
        .first()
    )
    if binding is None:
        raise BindingError("綁定碼不存在或已失效，請跟店家索取新的綁定碼")

    if _as_aware_utc(binding.expires_at) < datetime.now(timezone.utc):
        binding.status = "expired"
        db.commit()
        raise BindingError("綁定碼已過期，請跟店家重新產生一組")

    binding.status = "used"
    binding.used_at = datetime.now(timezone.utc)

    if binding.member_id is not None:
        target: Union[Member, VenueRentalCoach] = db.get(Member, binding.member_id)
        target.line_user_id = line_user_id
        role_for_menu = target.role
    else:
        target = db.get(VenueRentalCoach, binding.venue_coach_id)
        target.line_user_id = line_user_id
        role_for_menu = "venue_coach"

    db.commit()
    db.refresh(target)

    rich_menu_id = rich_menu_id_for_role(role_for_menu)
    if rich_menu_id:
        line_client.link_rich_menu_to_user(line_user_id, rich_menu_id)

    return target


def unbind_member(db: Session, *, member_id: int, reason: str) -> None:
    member = db.get(Member, member_id)
    if member is None or member.line_user_id is None:
        return

    line_user_id = member.line_user_id
    member.line_user_id = None
    member.role = None
    db.commit()

    line_client.unlink_rich_menu_from_user(line_user_id)


def unbind_venue_coach(db: Session, *, venue_coach_id: int, reason: str) -> None:
    coach = db.get(VenueRentalCoach, venue_coach_id)
    if coach is None or coach.line_user_id is None:
        return

    line_user_id = coach.line_user_id
    coach.line_user_id = None
    db.commit()

    line_client.unlink_rich_menu_from_user(line_user_id)


def expire_stale_codes(db: Session) -> int:
    """夜間掃描用：把過期但還是 active 狀態的碼標成 expired。"""
    now = datetime.now(timezone.utc)
    stale = db.query(BindingCode).filter(BindingCode.status == "active", BindingCode.expires_at < now).all()
    for code in stale:
        code.status = "expired"
    db.commit()
    return len(stale)
