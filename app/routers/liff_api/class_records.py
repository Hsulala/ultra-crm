from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.member_auth import require_member_role
from app.database import get_db
from app.models import Contract, ContractMember, Member
from app.schemas.class_record import (
    ActiveContractResponse,
    ClassRecordCreateRequest,
    ClassRecordResponse,
)
from app.services.class_record_service import create_class_record, get_class_records_for_member
from app.services.contract_service import get_active_contracts_for_coach, get_members_for_contract

router = APIRouter(prefix="/api/liff/class-records", tags=["liff-class-records"])


@router.get("/mine", response_model=List[ClassRecordResponse])
def my_class_records(
    member: Member = Depends(require_member_role("student")),
    db: Session = Depends(get_db),
):
    records = get_class_records_for_member(db, member.id, limit=5)
    result = []
    for r in records:
        coach = db.get(Member, r.actual_teaching_coach_id)
        result.append(
            ClassRecordResponse(
                id=r.id,
                contract_id=r.contract_id,
                actual_teaching_coach_id=r.actual_teaching_coach_id,
                coach_name=coach.name if coach else "未知教練",
                class_date=r.class_date,
                content_summary=r.content_summary,
            )
        )
    return result


@router.get("/active-contracts", response_model=List[ActiveContractResponse])
def active_contracts(
    coach: Member = Depends(require_member_role("coach")),
    db: Session = Depends(get_db),
):
    contracts = get_active_contracts_for_coach(db, coach.id)
    return [
        ActiveContractResponse(
            contract_id=c.id,
            contract_no=c.contract_no,
            student_names=[m.name for m in get_members_for_contract(db, c.id)],
            remaining_sessions=c.total_sessions - c.used_sessions,
        )
        for c in contracts
    ]


@router.post("", response_model=ClassRecordResponse)
def submit_class_record(
    payload: ClassRecordCreateRequest,
    coach: Member = Depends(require_member_role("coach")),
    db: Session = Depends(get_db),
):
    contract = db.get(Contract, payload.contract_id)
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到合約")

    is_member_of_contract = (
        db.query(ContractMember).filter(ContractMember.contract_id == payload.contract_id).count() > 0
    )
    if not is_member_of_contract:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "這份合約沒有任何學員，無法記錄課程")

    record = create_class_record(
        db,
        contract_id=payload.contract_id,
        actual_teaching_coach_id=coach.id,
        class_date=payload.class_date,
        content_summary=payload.content_summary,
        logged_by_id=coach.id,
    )
    return ClassRecordResponse(
        id=record.id,
        contract_id=record.contract_id,
        actual_teaching_coach_id=record.actual_teaching_coach_id,
        coach_name=coach.name,
        class_date=record.class_date,
        content_summary=record.content_summary,
    )
