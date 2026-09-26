from datetime import date
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ClassRecord, Contract, RevenueDetail
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
    （同一合約輪流上課時不會兩人平分同一堂）。依課程類型（重訓/皮拉提斯）分開統計，
    比照現行「重訓／皮拉提斯」分欄的月報表。金額換算跟抽成比例本期不做。"""
    start, end = month_bounds(year, month)
    rows = (
        db.query(ClassRecord.actual_teaching_coach_id, Contract.course_type, func.count(ClassRecord.id))
        .join(Contract, Contract.id == ClassRecord.contract_id)
        .filter(ClassRecord.class_date >= start, ClassRecord.class_date < end)
        .group_by(ClassRecord.actual_teaching_coach_id, Contract.course_type)
        .all()
    )

    by_coach: Dict[int, Dict[str, int]] = {}
    for coach_id, course_type, count in rows:
        by_coach.setdefault(coach_id, {"strength": 0, "pilates": 0})[course_type] = count

    return [
        {"coach_id": coach_id, "strength_count": counts["strength"], "pilates_count": counts["pilates"]}
        for coach_id, counts in by_coach.items()
    ]


def get_monthly_entries(db: Session, *, year: int, month: int) -> List[RevenueDetail]:
    start, end = month_bounds(year, month)
    return (
        db.query(RevenueDetail)
        .filter(RevenueDetail.entry_date >= start, RevenueDetail.entry_date < end)
        .order_by(RevenueDetail.entry_date.desc(), RevenueDetail.id.desc())
        .all()
    )


# 常用品項/付款方式快選清單：先用現行銷售表裡真的出現過的樣式頂著，
# 之後資料庫裡打過的品項名稱會自動併進來（見 get_item_name_suggestions），
# 這份靜態清單只是在資料還很少的時候給個起點。
COMMON_ITEM_NAMES = [
    "1V1PT*12", "1V1PT*16", "1V1PT*24", "1V2PT*12", "1V2PT*16", "1V2PT*24",
    "1V1PL*12", "1V1PL*16", "1V2PL*12",
    "PT體驗", "PL體驗",
    "單次會籍", "單月會籍",
    "場租*8", "場租1V2*10",
    "運動飲料", "魔爪", "冷萃蒸綠茶(小)", "原萃日式綠茶(大)", "水",
]
COMMON_PAYMENT_METHODS = ["現金", "匯款", "信用卡", "LinePay"]


def get_item_name_suggestions(db: Session) -> List[str]:
    used = [row[0] for row in db.query(RevenueDetail.item_name).distinct().all() if row[0]]
    merged = list(dict.fromkeys(used + COMMON_ITEM_NAMES))  # 保留順序去重，資料庫裡實際用過的排前面
    return merged


def get_payment_method_suggestions(db: Session) -> List[str]:
    used = [row[0] for row in db.query(RevenueDetail.payment_method).distinct().all() if row[0]]
    return list(dict.fromkeys(used + COMMON_PAYMENT_METHODS))
