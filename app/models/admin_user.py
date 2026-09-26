from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

# 超級管理者 super_admin／店長 manager／櫃檯 front_desk／教練 coach。
# super_admin 是唯一能管理後台帳號的角色，其餘權限比照 manager。
ADMIN_ROLE_LABELS = {
    "super_admin": "超級管理者",
    "manager": "店長",
    "front_desk": "櫃檯",
    "coach": "教練",
}


class AdminUser(Base, TimestampMixin):
    __tablename__ = "admin_users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('super_admin', 'manager', 'front_desk', 'coach')", name="ck_admin_users_role"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # role='coach' 的後台帳號用這欄過濾出「只看自己的班表/業績」
    linked_member_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"), nullable=True)
