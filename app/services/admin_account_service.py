from typing import List, Optional

from sqlalchemy.orm import Session

from app.auth.admin import hash_password
from app.models import ADMIN_ROLE_LABELS, AdminUser


class AdminAccountError(Exception):
    pass


def create_admin_account(
    db: Session,
    *,
    username: str,
    password: str,
    role: str,
    linked_member_id: Optional[int] = None,
) -> AdminUser:
    if role not in ADMIN_ROLE_LABELS:
        raise AdminAccountError("角色不正確")
    if not username or not password:
        raise AdminAccountError("帳號密碼不可空白")
    if db.query(AdminUser).filter(AdminUser.username == username).first():
        raise AdminAccountError("帳號已存在")

    user = AdminUser(
        username=username,
        password_hash=hash_password(password),
        role=role,
        linked_member_id=linked_member_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def set_admin_account_active(db: Session, *, account_id: int, is_active: bool) -> AdminUser:
    user = db.get(AdminUser, account_id)
    if user is None:
        raise AdminAccountError("找不到這個帳號")
    user.is_active = is_active
    db.commit()
    db.refresh(user)
    return user


def list_admin_accounts(db: Session) -> List[AdminUser]:
    return db.query(AdminUser).order_by(AdminUser.created_at.desc()).all()
