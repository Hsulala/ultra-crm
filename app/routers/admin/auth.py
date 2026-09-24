from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin_user, verify_password
from app.database import get_db
from app.models import AdminUser, Contract, Member
from app.services.contract_service import get_members_for_contract
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
    user: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    today = date.today()
    daily = get_daily_summary(db, entry_date=today)
    monthly = get_monthly_summary(db, year=today.year, month=today.month)

    student_count = db.query(Member).filter(Member.role == "student").count()
    coach_count = db.query(Member).filter(Member.role == "coach").count()
    active_contract_count = db.query(Contract).filter(Contract.status == "active").count()

    recent = (
        db.query(Contract).filter(Contract.status == "active").order_by(Contract.purchase_date.desc()).limit(8).all()
    )
    recent_contracts = []
    for c in recent:
        coach = db.get(Member, c.coach_id)
        students = get_members_for_contract(db, c.id)
        recent_contracts.append(
            {
                "id": c.id,
                "contract_no": c.contract_no,
                "student_names": "、".join(m.name for m in students),
                "coach_name": coach.name if coach else "未知",
                "status": c.status,
                "total_sessions": c.total_sessions,
                "used_sessions": c.used_sessions,
                "purchase_date": c.purchase_date,
            }
        )

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
            "recent_contracts": recent_contracts,
        },
    )
