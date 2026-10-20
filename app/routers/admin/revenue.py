import json
from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import AdminUser, Member, RevenueDetail
from app.schemas.revenue import RevenueEntryCreateRequest, RevenueEntryResponse
from app.services.item_catalog_service import get_items_grouped_by_category
from app.services.revenue_service import (
    create_revenue_entry,
    get_coach_class_counts,
    get_daily_summary,
    get_monthly_entries,
    get_monthly_summary,
    get_payment_method_suggestions,
)
from app.services.cash_service import taipei_today
from app.templating import templates

router = APIRouter(prefix="/admin/revenue", tags=["admin-revenue"])


@router.get("/page")
def revenue_page(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
    ym: Optional[str] = None,
    tab: str = "today",
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    today = taipei_today()
    if ym and len(ym) == 7 and ym[4] == "-" and ym[:4].isdigit() and ym[5:].isdigit():
        year, month = int(ym[:4]), int(ym[5:])
    if not year or not month or not (1 <= month <= 12) or (year, month) > (today.year, today.month):
        year, month = today.year, today.month
    is_current_month = (year, month) == (today.year, today.month)
    prev_ym = (year - 1, 12) if month == 1 else (year, month - 1)
    next_ym = None if is_current_month else ((year + 1, 1) if month == 12 else (year, month + 1))
    daily = get_daily_summary(db, entry_date=today)
    monthly = get_monthly_summary(db, year=year, month=month)
    coach_performance = get_coach_class_counts(db, year=year, month=month)
    coach_names = {m.id: m.name for m in db.query(Member).filter(Member.role == "coach").all()}

    today_entries = (
        db.query(RevenueDetail).filter(RevenueDetail.entry_date == today).order_by(RevenueDetail.id.desc()).all()
    )
    month_entries = get_monthly_entries(db, year=year, month=month)

    category_labels = {
        "service": "服務",
        "venue_rental": "場租",
        "membership": "會籍",
        "beverage": "飲料",
        "coaching": "教練課",
        "custom": "自訂項目",
    }

    return templates.TemplateResponse(
        request,
        "admin/revenue.html",
        {
            "current_user": admin,
            "active": "revenue",
            "today": today,
            "year": year,
            "month": month,
            "month_label": f"{year - 1911} 年 {month} 月",
            "is_current_month": is_current_month,
            "prev_ym": prev_ym,
            "next_ym": next_ym,
            "initial_tab": "month" if tab == "month" or not is_current_month else "today",
            "daily": daily,
            "monthly": monthly,
            "coach_performance": [
                {
                    "coach_name": coach_names.get(row["coach_id"], "未知"),
                    "strength_count": row["strength_count"],
                    "pilates_count": row["pilates_count"],
                }
                for row in coach_performance
            ],
            "today_entries": today_entries,
            "month_entries": month_entries,
            "category_labels": category_labels,
            "items_by_category_json": json.dumps(get_items_grouped_by_category(db)),
            "payment_method_suggestions": get_payment_method_suggestions(db),
        },
    )


@router.post("", response_model=RevenueEntryResponse)
def create_revenue_entry_endpoint(
    payload: RevenueEntryCreateRequest,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    return create_revenue_entry(
        db,
        entry_date=payload.entry_date,
        item_category=payload.item_category,
        item_name=payload.item_name,
        payment_method=payload.payment_method,
        amount=payload.amount,
        coach_id=payload.coach_id,
        content=payload.content,
        contract_id=payload.contract_id,
        remittance_last5=payload.remittance_last5,
        entered_by_id=admin.id,
    )


# 以下報表只有店長看得到全部營收，比照規格書第十一節的權限劃分
@router.get("/daily-summary")
def daily_summary_endpoint(
    date: str,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    from datetime import date as date_cls

    return get_daily_summary(db, entry_date=date_cls.fromisoformat(date))


@router.get("/monthly-summary")
def monthly_summary_endpoint(
    year: int,
    month: int,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    return get_monthly_summary(db, year=year, month=month)


@router.get("/coach-performance")
def coach_performance_endpoint(
    year: int,
    month: int,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    return get_coach_class_counts(db, year=year, month=month)
