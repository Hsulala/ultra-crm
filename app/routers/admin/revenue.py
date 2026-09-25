from datetime import date as date_cls

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import AdminUser, Member, RevenueDetail
from app.schemas.revenue import RevenueEntryCreateRequest, RevenueEntryResponse
from app.services.revenue_service import (
    create_revenue_entry,
    get_coach_class_counts,
    get_daily_summary,
    get_monthly_entries,
    get_monthly_summary,
)
from app.templating import templates

router = APIRouter(prefix="/admin/revenue", tags=["admin-revenue"])


@router.get("/page")
def revenue_page(
    request: Request,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    today = date_cls.today()
    daily = get_daily_summary(db, entry_date=today)
    monthly = get_monthly_summary(db, year=today.year, month=today.month)
    coach_performance = get_coach_class_counts(db, year=today.year, month=today.month)
    coach_names = {m.id: m.name for m in db.query(Member).filter(Member.role == "coach").all()}

    today_entries = (
        db.query(RevenueDetail).filter(RevenueDetail.entry_date == today).order_by(RevenueDetail.id.desc()).all()
    )
    month_entries = get_monthly_entries(db, year=today.year, month=today.month)

    category_labels = {
        "service_venue": "服務(含場租)",
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
