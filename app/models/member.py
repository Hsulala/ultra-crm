from datetime import date
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

# 教練跟學員共用同一張表：合約的 coach_id、課程紀錄的 actual_teaching_coach_id
# 都指回這裡。role 為 NULL 代表尚未綁定（訪客）；角色互斥（不會同時是教練跟學員）
# 由 service layer 保證，這裡不用 DB constraint 表達。
MEMBER_ROLE_LABELS = {
    "student": "學員",
    "coach": "教練",
}


class Member(Base, TimestampMixin):
    __tablename__ = "members"
    __table_args__ = (CheckConstraint("role IN ('student', 'coach')", name="ck_members_role"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    member_no: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    photo_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    line_user_id: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # 單月會籍的起訖日——單次會籍不記日期，只在營收登記一筆即可（不影響這兩欄）。
    # membership_active_until 也是自動解綁判斷依據：過期即解綁，見 binding_service。
    membership_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    membership_active_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    import_batch: Mapped[Optional[str]] = mapped_column(String, nullable=True)
