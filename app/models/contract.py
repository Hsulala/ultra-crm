from datetime import date
from typing import Optional

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

CONTRACT_STATUS_LABELS = {
    "active": "進行中",
    "refunded": "已退費",
    "free": "FREE",
}

COURSE_TYPE_LABELS = {
    "strength": "重訓",
    "pilates": "皮拉提斯",
}


class Contract(Base, TimestampMixin):
    """coach_id / venue_coach_id 兩者恰好擇一：重訓合約只會是店內正職（coach_id）；
    皮拉提斯合約店內正職、場租教練都可能開（客戶「課堂報表」合約資料(皮拉提斯)分頁
    教練欄本來就同時有 YOKO 這種正職跟 ELSA 這種場租教練），所以皮拉提斯合約可以
    掛在任一邊，但只能擇一。"""

    __tablename__ = "contracts"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'refunded', 'free')", name="ck_contracts_status"),
        CheckConstraint("course_type IN ('strength', 'pilates')", name="ck_contracts_course_type"),
        CheckConstraint(
            "(coach_id IS NOT NULL AND venue_coach_id IS NULL) OR (coach_id IS NULL AND venue_coach_id IS NOT NULL)",
            name="ck_contracts_coach_xor_venue_coach",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contract_no: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # 合約「登記」教練，可能跟課堂紀錄裡「實際帶課教練」不同（見 ClassRecord）
    coach_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"), nullable=True)
    venue_coach_id: Mapped[Optional[int]] = mapped_column(ForeignKey("venue_rental_coaches.id"), nullable=True)
    course_type: Mapped[str] = mapped_column(String, nullable=False, default="strength")
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    total_sessions: Mapped[int] = mapped_column(nullable=False)
    used_sessions: Mapped[int] = mapped_column(nullable=False, default=0)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")


class ContractMember(Base):
    """合約與學員的對應表。1對2 合約會有兩筆列指向同一個 contract_id，
    雙方查詢時用這張表做對稱 join，不用在 Contract 上硬塞 student2_id。"""

    __tablename__ = "contract_members"

    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"), primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), primary_key=True)
