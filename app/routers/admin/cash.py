from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import AdminUser, CashClosing, CashMovement
from app.schemas.cash import (
    ClosingCreatedResponse,
    ClosingCreateRequest,
    FloatRequest,
    MovementCreateRequest,
    NoteRequest,
    ReasonRequest,
    ReviewRequest,
)
from app.services import cash_service
from app.services.cash_service import CashError
from app.templating import templates

router = APIRouter(prefix="/admin/cash", tags=["admin-cash"])

# 櫃檯、店長都能結帳與登記異動（跟「新增收款紀錄」同樣的人）；super_admin 由 require_role 自動放行。
# 覆核、作廢、設定零用金、看全部差額總覽只有店長。
OPERATOR_ROLES = ("manager", "front_desk")
MANAGER_ROLES = ("manager", "super_admin")


def _bad_request(error: CashError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


@router.get("/page")
def cash_page(
    request: Request,
    admin: AdminUser = Depends(require_role(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    today = cash_service.taipei_today()
    is_manager = admin.role in MANAGER_ROLES

    overview = None
    if is_manager:
        overview = cash_service.get_overview(db, today - timedelta(days=29), today)

    return templates.TemplateResponse(
        request,
        "admin/cash.html",
        {
            "current_user": admin,
            "active": "cash",
            "is_manager": is_manager,
            "today": today,
            "current_shift": cash_service.current_shift(),
            "day_status": cash_service.get_day_status(db, today),
            "today_movements": cash_service.list_movements_for_date(db, today),
            "counterparty_suggestions": cash_service.counterparty_suggestions(db),
            "cash_float": cash_service.get_cash_float(db),
            "denominations": cash_service.DENOMINATIONS,
            "users": cash_service.usernames(db),
            "overview": overview,
        },
    )


@router.post("/closings", response_model=ClosingCreatedResponse)
def create_closing_endpoint(
    payload: ClosingCreateRequest,
    admin: AdminUser = Depends(require_role(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        closing = cash_service.create_closing(
            db,
            business_date=payload.business_date,
            shift=payload.shift,
            denominations=payload.denominations,
            collected_amount=payload.collected_amount,
            note=payload.note,
            closed_by_id=admin.id,
        )
    except CashError as e:
        raise _bad_request(e)
    return ClosingCreatedResponse(id=closing.id)


@router.get("/closings/{closing_id}/page")
def closing_page(
    closing_id: int,
    request: Request,
    admin: AdminUser = Depends(require_role(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    closing = db.get(CashClosing, closing_id)
    if not closing:
        raise HTTPException(status_code=404, detail="找不到這筆結帳")
    is_manager = admin.role in MANAGER_ROLES
    # 櫃檯只能看自己結的帳（結完立刻看結果）；全部人的差額只有店長看得到
    if not is_manager and closing.closed_by_id != admin.id:
        raise HTTPException(status_code=403, detail="沒有權限")

    return templates.TemplateResponse(
        request,
        "admin/cash_closing.html",
        {
            "current_user": admin,
            "active": "cash",
            "is_manager": is_manager,
            "closing": closing,
            "status": cash_service.variance_status(closing),
            "detail": cash_service.closing_detail(db, closing),
            "denomination_rows": sorted(
                ((int(denom), count) for denom, count in (closing.denominations or {}).items()), reverse=True
            ),
            "users": cash_service.usernames(db),
            "can_add_note": is_manager or (closing.closed_by_id == admin.id and not closing.note),
        },
    )


@router.post("/closings/{closing_id}/note")
def closing_note_endpoint(
    closing_id: int,
    payload: NoteRequest,
    admin: AdminUser = Depends(require_role(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        cash_service.set_note(db, closing_id, admin, payload.note)
    except CashError as e:
        raise _bad_request(e)
    return {"ok": True}


@router.post("/closings/{closing_id}/review")
def closing_review_endpoint(
    closing_id: int,
    payload: ReviewRequest,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    try:
        cash_service.review_closing(db, closing_id, admin.id, payload.note)
    except CashError as e:
        raise _bad_request(e)
    return {"ok": True}


@router.post("/closings/{closing_id}/void")
def closing_void_endpoint(
    closing_id: int,
    payload: ReasonRequest,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    try:
        cash_service.void_closing(db, closing_id, admin.id, payload.reason)
    except CashError as e:
        raise _bad_request(e)
    return {"ok": True}


@router.post("/movements")
def create_movement_endpoint(
    payload: MovementCreateRequest,
    admin: AdminUser = Depends(require_role(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        movement = cash_service.create_movement(
            db,
            entry_date=payload.entry_date,
            movement_type=payload.movement_type,
            amount=payload.amount,
            counterparty=payload.counterparty,
            description=payload.description,
            entered_by_id=admin.id,
        )
    except CashError as e:
        raise _bad_request(e)
    return {"id": movement.id}


@router.post("/movements/{movement_id}/void")
def void_movement_endpoint(
    movement_id: int,
    payload: ReasonRequest,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    try:
        cash_service.void_movement(db, movement_id, admin.id, payload.reason)
    except CashError as e:
        raise _bad_request(e)
    return {"ok": True}


@router.post("/settings/float")
def set_float_endpoint(
    payload: FloatRequest,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    try:
        value = cash_service.set_cash_float(db, payload.amount)
    except CashError as e:
        raise _bad_request(e)
    return {"cash_float": float(value)}
