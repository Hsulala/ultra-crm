from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import ADMIN_ROLE_LABELS, AdminUser
from app.schemas.admin_account import AdminAccountCreateRequest, AdminAccountResponse
from app.services.admin_account_service import (
    AdminAccountError,
    create_admin_account,
    list_admin_accounts,
    set_admin_account_active,
)
from app.templating import templates

router = APIRouter(prefix="/admin/accounts", tags=["admin-accounts"])


@router.get("/page")
def accounts_page(
    request: Request,
    admin: AdminUser = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
):
    accounts = list_admin_accounts(db)
    return templates.TemplateResponse(
        request,
        "admin/accounts.html",
        {
            "current_user": admin,
            "active": "accounts",
            "accounts": accounts,
            "role_labels": ADMIN_ROLE_LABELS,
        },
    )


@router.post("", response_model=AdminAccountResponse)
def create_account_endpoint(
    payload: AdminAccountCreateRequest,
    admin: AdminUser = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
):
    try:
        return create_admin_account(
            db,
            username=payload.username,
            password=payload.password,
            role=payload.role,
            linked_member_id=payload.linked_member_id,
        )
    except AdminAccountError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/{account_id}/deactivate")
def deactivate_account_endpoint(
    account_id: int,
    admin: AdminUser = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
):
    if account_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能停用自己的帳號")
    try:
        set_admin_account_active(db, account_id=account_id, is_active=False)
    except AdminAccountError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "success"}


@router.post("/{account_id}/activate")
def activate_account_endpoint(
    account_id: int,
    admin: AdminUser = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
):
    try:
        set_admin_account_active(db, account_id=account_id, is_active=True)
    except AdminAccountError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "success"}
