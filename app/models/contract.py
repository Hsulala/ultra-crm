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


class Contract(Base, TimestampMixin):
    __tablename__ = "contracts"
    __table_args__ = (CheckConstraint("status IN ('active', 'refunded', 'free')", name="ck_contracts_status"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contract_no: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # 合約「登記」教練，可能跟課堂紀錄裡「實際帶課教練」不同（見 ClassRecord）
    coach_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
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
