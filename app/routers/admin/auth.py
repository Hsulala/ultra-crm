import json
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin_user, verify_password
from app.database import get_db
from app.models import AdminUser, Contract, Member, VenueRentalCoach
from app.services.booking_service import build_day_grid
from app.services.revenue_service import get_daily_summary, get_monthly_summary
from app.templating import templates

router = APIRouter(prefix="/admin", tags=["admin-auth"])


@router.get("/login")
def login_page(request: Request, denied: int = 0):
    return templates.TemplateResponse(
        request, "admin/login.html", {"denied": bool(denied), "error": None}
    )


@router.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(AdminUser).filter(AdminUser.username == username).first()
    if not user or not user.is_active or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request, "admin/login.html", {"denied": False, "error": "帳號或密碼錯誤"}, status_code=401
        )

    request.session["admin_user_id"] = user.id
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("/")
def admin_home(
    request: Request,
    d: Optional[str] = None,
    user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    today = date.today()
    target_date = date.fromisoformat(d) if d else today

    daily = get_daily_summary(db, entry_date=today)
    monthly = get_monthly_summary(db, year=today.year, month=today.month)

    student_count = db.query(Member).filter(Member.role == "student").count()
    coach_count = db.query(Member).filter(Member.role == "coach").count()
    active_contract_count = db.query(Contract).filter(Contract.status == "active").count()

    grid = build_day_grid(db, target_date)
    contract_options_json = json.dumps(
        {str(col["coach_id"]): col["contract_options"] for col in grid["columns"]}
    )
    venue_coach_options = (
        db.query(VenueRentalCoach)
        .filter(VenueRentalCoach.is_active == True)  # noqa: E712
        .order_by(VenueRentalCoach.name)
        .all()
    )
    venue_coach_options_json = json.dumps([{"id": vc.id, "name": vc.name} for vc in venue_coach_options])

    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "current_user": user,
            "active": "dashboard",
            "today_revenue": daily["total"],
            "month_revenue": monthly["total"],
            "student_count": student_count,
            "coach_count": coach_count,
            "active_contract_count": active_contract_count,
            "target_date": target_date,
            "prev_date": target_date - timedelta(days=1),
            "next_date": target_date + timedelta(days=1),
            "is_today": target_date == today,
            "hours": grid["hours"],
            "columns": grid["columns"],
            "venue_columns": grid["venue_columns"],
            "pilates_usage": grid["pilates_usage"],
            "contract_options_json": contract_options_json,
            "venue_coach_options_json": venue_coach_options_json,
        },
    )
