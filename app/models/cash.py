from datetime import date, datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, TimestampMixin
from app.models.schedule import SHIFT_CHECK

# 抽屜現金會流出/流入的「非銷售」情況。銷售收入本身不在這裡——那是 RevenueDetail
# （付款方式為現金的那些），對帳時直接從營收流水帳算，避免同一筆錢記兩個地方。
MOVEMENT_TYPE_LABELS = {
    "petty_cash": "零用金支出",
    "refund": "現金退費",
    "coach_advance": "代墊／找零給教練",
    "advance_return": "教練歸還代墊",
}
# 方向跟著類型走：out = 現金離開抽屜、in = 現金回到抽屜
MOVEMENT_DIRECTIONS = {
    "petty_cash": "out",
    "refund": "out",
    "coach_advance": "out",
    "advance_return": "in",
}
MOVEMENT_TYPE_CHECK = "movement_type IN ('petty_cash', 'refund', 'coach_advance', 'advance_return')"


class AppSetting(Base, TimestampMixin):
    """很小的 key/value 設定表。目前只放 cash_float（每天固定留在抽屜的零用金）。"""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)


class CashMovement(Base, TimestampMixin):
    """抽屜現金的非銷售異動。不能修改、不能刪除，記錯只能由店長作廢（留下原因與時間），
    這樣事後才查得到「這筆錢是被誰、什麼時候、為什麼拿掉的」。"""

    __tablename__ = "cash_movements"
    __table_args__ = (
        CheckConstraint(MOVEMENT_TYPE_CHECK, name="ck_cash_movements_type"),
        CheckConstraint("direction IN ('in', 'out')", name="ck_cash_movements_direction"),
        CheckConstraint("amount > 0", name="ck_cash_movements_amount_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    movement_type: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    # 對象（教練、廠商…）用自由文字：店內教練跟場租教練分在兩張表，這裡不綁外鍵
    counterparty: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entered_by_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), nullable=False)

    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    void_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class CashClosing(Base, TimestampMixin):
    """班次交接時的現金結帳。

    應有現金 = 期初現金（上一次結帳留在抽屜的金額）
              + 這段時間的現金收款（營收流水帳、付款方式為現金、依建立時間落在區間內）
              + 現金收入類異動 − 現金支出類異動
    差額 = 實點 − 應有。每一次結帳都是下一次的起點，所以哪一段時間少錢、少多少，
    一定會落在某一次結帳的區間裡。

    結帳送出後不可修改；點錯只能由店長作廢後重點。數字都存快照，之後帳目被動過
    （例如異動被作廢）可以用 cash_service.recompute_live 跟快照比對看出來。"""

    __tablename__ = "cash_closings"
    __table_args__ = (
        CheckConstraint(SHIFT_CHECK, name="ck_cash_closings_shift"),
        CheckConstraint("counted_cash >= 0", name="ck_cash_closings_counted_nonnegative"),
        CheckConstraint("collected_amount >= 0", name="ck_cash_closings_collected_nonnegative"),
        # 同一天同一班只能有一筆「有效」結帳；作廢的不算，作廢後可以重點
        Index(
            "ux_cash_closings_date_shift_active",
            "business_date",
            "shift",
            unique=True,
            postgresql_where=text("voided_at IS NULL"),
            sqlite_where=text("voided_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    shift: Mapped[str] = mapped_column(String, nullable=False)

    # 計算區間：(interval_start, closed_at]。第一次結帳時 interval_start 是當天 00:00（台北）
    interval_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    opening_cash: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    cash_sales: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    movements_in: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    movements_out: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    expected_cash: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    counted_cash: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    # 面額 -> 張數，例如 {"1000": 12, "500": 3}；實點金額由伺服器依此算出，不信任前端合計
    denominations: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    variance: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)  # 實點 − 應有，負數 = 短少

    # 點完之後從抽屜拿走的現金（通常晚班：實點 − 固定零用金）；留在抽屜的就是下一班的期初
    collected_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    remaining_cash: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    cash_float_snapshot: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closed_by_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), nullable=False)

    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    voided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admin_users.id"), nullable=True)
    void_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
