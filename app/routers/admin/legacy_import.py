import datetime as dt
import gzip
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import AdminUser, Contract, Member, RevenueDetail
from app.services.legacy_import import LegacyImportError, run_import
from app.templating import templates

router = APIRouter(prefix="/admin/legacy-import", tags=["admin-legacy-import"])


@router.get("/page")
def legacy_import_page(
    request: Request,
    admin: AdminUser = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
):
    current = {
        "members": db.query(func.count(Member.id)).scalar(),
        "contracts": db.query(func.count(Contract.id)).scalar(),
        "revenue": db.query(func.count(RevenueDetail.id)).scalar(),
        "imported": db.query(Member.import_batch).filter(Member.import_batch.isnot(None)).distinct().all(),
    }
    return templates.TemplateResponse(
        request,
        "admin/legacy_import.html",
        {"current_user": admin, "active": "legacy-import", "current": current},
    )


@router.post("")
async def legacy_import_run(
    bundle: UploadFile = File(...),
    mode: str = Form("dryrun"),
    clear_existing: bool = Form(False),
    confirm: str = Form(""),
    admin: AdminUser = Depends(require_role("super_admin")),
    db: Session = Depends(get_db),
):
    raw = await bundle.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "檔案不是匯入用的 JSON")

    commit = mode == "commit"
    if commit and confirm.strip() != "匯入":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "正式匯入前請在確認欄輸入「匯入」兩個字")

    batch = "legacy-" + dt.datetime.now().strftime("%Y%m%d-%H%M")
    try:
        report = run_import(db, data, batch=batch, clear_existing=clear_existing, commit=commit)
    except LegacyImportError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    report["issue_samples"] = data.get("issues", [])[:300]
    return report
