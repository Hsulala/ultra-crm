from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin


class ItemCatalogEntry(Base, TimestampMixin):
    """營收頁面「品項名稱」的下拉來源，比照現行銷售表的品項分類。
    default_price 可以留空（像飲料常常沒有固定單價、教練特殊報價），
    留空的話選了這個品項只會帶出名稱，金額還是要店員自己填。"""

    __tablename__ = "item_catalog_entries"
    __table_args__ = (
        CheckConstraint(
            "item_category IN ('service_venue', 'membership', 'beverage', 'coaching', 'custom')",
            name="ck_item_catalog_entries_category",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    item_category: Mapped[str] = mapped_column(String, nullable=False)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    default_price: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
