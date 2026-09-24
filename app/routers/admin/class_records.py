from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.admin import get_current_admin_user
from app.database import get_db
from app.models import AdminUser, ClassRecord, Contract, ContractMember, Member
from app.services.class_record_service import create_class_record
from app.services.contract_service import get_active_contracts_for_coach, get_members_for_contract
from app.templating import templates

router = APIRouter(prefix="/admin/class-records", tags=["admin-class-records"])


class AdminClassRecordCreateRequest(BaseModel):
    coach_id: int
    contract_id: int
    class_date: str
    content_summary: str


@router.get("/page")
def class_records_page(
    request: Request,
    coach_id: Optional[int] = None,
    admin: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    # 教練登入自己的帳號只看得到自己名下的合約；店長/櫃檯可以選教練，
    # 方便教練不方便操作時由櫃檯代為登打。
    coaches = db.query(Member).filter(Member.role == "coach").all()

    if admin.role == "coach":
        if not admin.linked_member_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "這個教練帳號尚未連結對應的會員資料，請聯絡店長設定")
        selected_coach_id = admin.linked_member_id
    else:
        selected_coach_id = coach_id or (coaches[0].id if coaches else None)

    active_contracts = []
    if selected_coach_id:
        contracts = get_active_contracts_for_coach(db, selected_coach_id)
        for c in contracts:
            students = get_members_for_contract(db, c.id)
            active_contracts.append(
                {
                    "contract_id": c.id,
                    "contract_no": c.contract_no,
                    "student_names": "、".join(m.name for m in students),
                    "remaining_sessions": c.total_sessions - c.used_sessions,
                }
            )

    recent_records = []
    if selected_coach_id:
        records = (
            db.query(ClassRecord)
            .filter(ClassRecord.actual_teaching_coach_id == selected_coach_id)
            .order_by(ClassRecord.class_date.desc())
            .limit(10)
            .all()
        )
        for r in records:
            students = get_members_for_contract(db, r.contract_id)
            recent_records.append(
                {
                    "class_date": r.class_date,
                    "student_names": "、".join(m.name for m in students),
                    "content_summary": r.content_summary,
                }
            )

    return templates.TemplateResponse(
        request,
        "admin/class_records.html",
        {
            "current_user": admin,
            "active": "class-records",
            "coaches": coaches,
            "selected_coach_id": selected_coach_id,
            "is_coach_locked": admin.role == "coach",
            "active_contracts": active_contracts,
            "recent_records": recent_records,
            "today": date_cls.today().isoformat(),
        },
    )


@router.post("")
def create_class_record_endpoint(
    payload: AdminClassRecordCreateRequest,
    admin: AdminUser = Depends(get_current_admin_user),
    db: Session = Depends(get_db),
):
    # 教練帳號只能替自己記錄；店長/櫃檯可以替任何教練記錄（代打字）。
    if admin.role == "coach" and admin.linked_member_id != payload.coach_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "只能記錄自己的課程")

    contract = db.get(Contract, payload.contract_id)
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到合約")

    is_valid_contract = (
        db.query(ContractMember).filter(ContractMember.contract_id == payload.contract_id).count() > 0
    )
    if not is_valid_contract:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "這份合約沒有任何學員，無法記錄課程")

    record = create_class_record(
        db,
        contract_id=payload.contract_id,
        actual_teaching_coach_id=payload.coach_id,
        class_date=date_cls.fromisoformat(payload.class_date),
        content_summary=payload.content_summary,
        logged_by_id=payload.coach_id,
    )
    return {"status": "success", "id": record.id}
