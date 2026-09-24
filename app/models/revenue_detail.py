from datetime import date
from typing import Optional

from sqlalchemy import CheckConstraint, Date, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin

# payment_method 先不做成 CHECK enum——實際使用的付款方式列舉還沒跟客戶確認過
# （見 /Users/lala/.claude/plans/mellow-brewing-liskov.md 待確認問題第 6 項）。
ITEM_CATEGORY_LABELS = {
    "service_venue": "服務(含場租)",
    "membership": "會籍",
    "beverage": "飲料",
    "coaching": "教練課",
    "custom": "自訂項目",
}


class RevenueDetail(Base, TimestampMixin):
    """比照現行「每日銷售表」的原始收款流水帳，一筆一筆記，不做彙總——
    彙總改用 app/services/revenue_service.py 的查詢即時算，避免跟原始帳目失同步。"""

    __tablename__ = "revenue_details"
    __table_args__ = (
        CheckConstraint(
            "item_category IN ('service_venue', 'membership', 'beverage', 'coaching', 'custom')",
            name="ck_revenue_details_item_category",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    item_category: Mapped[str] = mapped_column(String, nullable=False)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    # 收款當下登記的教練（業績歸屬另外從 ClassRecord.actual_teaching_coach_id 算，
    # 見 revenue_service.get_coach_class_counts；這欄只是原始流水帳的收款教練）
    coach_id: Mapped[Optional[int]] = mapped_column(ForeignKey("members.id"), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payment_method: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    contract_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contracts.id"), nullable=True)
    entered_by_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), nullable=False)
