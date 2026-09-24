from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AdminUser

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def get_session_admin_id(request: Request) -> Optional[int]:
    return request.session.get("admin_user_id")


def get_current_admin_user(
    request: Request,
    db: Session = Depends(get_db),
) -> AdminUser:
    """要求已登入，且帳號還是啟用狀態（每次請求都重新查資料庫，
    不只信任 session 裡快取的資訊，帳號被停用要能立刻生效）。"""
    admin_id = get_session_admin_id(request)
    if admin_id is None:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})

    user = db.get(AdminUser, admin_id)
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login?denied=1"})

    return user


def require_role(*roles: str):
    def _check(user: AdminUser = Depends(get_current_admin_user)) -> AdminUser:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="沒有權限")
        return user

    return _check
