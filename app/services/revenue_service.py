from datetime import date
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ClassRecord, RevenueDetail
from app.services.schedule_service import month_bounds


def create_revenue_entry(
    db: Session,
    *,
    entry_date: date,
    item_category: str,
    item_name: str,
    payment_method: str,
    amount: float,
    coach_id: Optional[int] = None,
    content: Optional[str] = None,
    contract_id: Optional[int] = None,
    entered_by_id: int,
) -> RevenueDetail:
    entry = RevenueDetail(
        entry_date=entry_date,
        item_category=item_category,
        item_name=item_name,
        coach_id=coach_id,
        content=content,
        payment_method=payment_method,
        amount=amount,
        contract_id=contract_id,
        entered_by_id=entered_by_id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_daily_summary(db: Session, *, entry_date: date) -> Dict:
    """比照現行「單日業績表」：當天各品項分類小計 + 總額，給店長晚上核對用。"""
    rows = (
        db.query(RevenueDetail.item_category, func.sum(RevenueDetail.amount))
        .filter(RevenueDetail.entry_date == entry_date)
        .group_by(RevenueDetail.item_category)
        .all()
    )
    by_category = {category: float(total) for category, total in rows}
    return {
        "entry_date": entry_date,
        "by_category": by_category,
        "total": sum(by_category.values()),
    }


def get_monthly_summary(db: Session, *, year: int, month: int) -> Dict:
    """月報表：依現行邏輯用公式即時彙總算出來，不另外存一張彙總表，
    避免跟原始流水帳（RevenueDetail）長期下來對不起來。"""
    start, end = month_bounds(year, month)

    by_category_rows = (
        db.query(RevenueDetail.item_category, func.sum(RevenueDetail.amount))
        .filter(RevenueDetail.entry_date >= start, RevenueDetail.entry_date < end)
        .group_by(RevenueDetail.item_category)
        .all()
    )
    by_category = {category: float(total) for category, total in by_category_rows}

    by_day_rows = (
        db.query(RevenueDetail.entry_date, func.sum(RevenueDetail.amount))
        .filter(RevenueDetail.entry_date >= start, RevenueDetail.entry_date < end)
        .group_by(RevenueDetail.entry_date)
        .order_by(RevenueDetail.entry_date)
        .all()
    )
    by_day = {d.isoformat(): float(total) for d, total in by_day_rows}

    return {
        "year": year,
        "month": month,
        "by_category": by_category,
        "by_day": by_day,
        "total": sum(by_category.values()),
    }


def get_coach_class_counts(db: Session, *, year: int, month: int) -> List[Dict]:
    """教練業績歸屬：規格要求算給「當堂實際帶課教練」，不是收款當下登記的教練
    （同一合約輪流上課時不會兩人平分同一堂）。這裡先給「實際帶課堂數」的原始統計，
    金額換算（乘上合約單價/堂）跟抽成比例本期不做，之後有需要再接上。"""
    start, end = month_bounds(year, month)
    rows = (
        db.query(ClassRecord.actual_teaching_coach_id, func.count(ClassRecord.id))
        .filter(ClassRecord.class_date >= start, ClassRecord.class_date < end)
        .group_by(ClassRecord.actual_teaching_coach_id)
        .all()
    )
    return [{"coach_id": coach_id, "class_count": count} for coach_id, count in rows]
