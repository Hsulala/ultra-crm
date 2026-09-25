from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import AdminUser, Contract, Member
from app.schemas.contract import ContractCreateRequest, ContractResponse
from app.services.contract_service import ContractError, create_contract, get_members_for_contract
from app.templating import templates

router = APIRouter(prefix="/admin/contracts", tags=["admin-contracts"])


@router.get("/page")
def contracts_page(
    request: Request,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    contracts = db.query(Contract).order_by(Contract.purchase_date.desc()).all()
    rows = []
    for c in contracts:
        coach = db.get(Member, c.coach_id)
        students = get_members_for_contract(db, c.id)
        rows.append(
            {
                "id": c.id,
                "contract_no": c.contract_no,
                "student_names": "、".join(m.name for m in students),
                "coach_name": coach.name if coach else "未知",
                "course_type": c.course_type,
                "status": c.status,
                "total_sessions": c.total_sessions,
                "used_sessions": c.used_sessions,
                "purchase_date": c.purchase_date,
                "expiry_date": c.expiry_date,
            }
        )

    coaches = db.query(Member).filter(Member.role == "coach").all()
    students = db.query(Member).filter(Member.role == "student").all()

    return templates.TemplateResponse(
        request,
        "admin/contracts.html",
        {
            "current_user": admin,
            "active": "contracts",
            "contracts": rows,
            "coaches": coaches,
            "students": students,
        },
    )


@router.post("", response_model=ContractResponse)
def create_contract_endpoint(
    payload: ContractCreateRequest,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    coach = db.get(Member, payload.coach_id)
    if coach is None or coach.role != "coach":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "coach_id 不是有效的教練")

    if payload.member_ids:
        found = db.query(Member).filter(Member.id.in_(payload.member_ids)).all()
        if len(found) != len(set(payload.member_ids)):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "member_ids 裡有不存在的會員")

    if not payload.member_ids and not payload.new_student_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "請至少選一位既有學員，或填新學員姓名")

    try:
        return create_contract(
            db,
            coach_id=payload.coach_id,
            member_ids=payload.member_ids,
            course_type=payload.course_type,
            purchase_date=payload.purchase_date,
            unit_price=payload.unit_price,
            total_sessions=payload.total_sessions,
            contract_no=payload.contract_no,
            status=payload.status,
            expiry_date=payload.expiry_date,
            new_student_name=payload.new_student_name,
            new_student_phone=payload.new_student_phone,
        )
    except ContractError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
