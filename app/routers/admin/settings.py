from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import AdminUser
from app.schemas.item_catalog import ItemCatalogCreateRequest, ItemCatalogResponse, ItemCatalogUpdateRequest
from app.services.item_catalog_service import (
    ItemCatalogError,
    create_item,
    deactivate_item,
    list_active_items,
    update_item,
)
from app.templating import templates

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])

CATEGORY_LABELS = {
    "service_venue": "服務(含場租)",
    "membership": "會籍",
    "beverage": "飲料",
    "coaching": "教練課",
    "custom": "自訂項目",
}


@router.get("/items/page")
def items_settings_page(
    request: Request,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    items = list_active_items(db)
    return templates.TemplateResponse(
        request,
        "admin/settings_items.html",
        {
            "current_user": admin,
            "active": "settings",
            "items": items,
            "category_labels": CATEGORY_LABELS,
        },
    )


@router.post("/items", response_model=ItemCatalogResponse)
def create_item_endpoint(
    payload: ItemCatalogCreateRequest,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    try:
        return create_item(
            db, item_category=payload.item_category, item_name=payload.item_name, default_price=payload.default_price
        )
    except ItemCatalogError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/items/{item_id}", response_model=ItemCatalogResponse)
def update_item_endpoint(
    item_id: int,
    payload: ItemCatalogUpdateRequest,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    try:
        return update_item(db, item_id=item_id, item_name=payload.item_name, default_price=payload.default_price)
    except ItemCatalogError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/items/{item_id}/deactivate")
def deactivate_item_endpoint(
    item_id: int,
    admin: AdminUser = Depends(require_role("manager")),
    db: Session = Depends(get_db),
):
    try:
        deactivate_item(db, item_id=item_id)
    except ItemCatalogError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"status": "success"}
