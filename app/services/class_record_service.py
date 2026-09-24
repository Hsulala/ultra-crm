from datetime import date
from typing import List

from sqlalchemy.orm import Session

from app.models import ClassRecord, Contract, ContractMember


def create_class_record(
    db: Session,
    *,
    contract_id: int,
    actual_teaching_coach_id: int,
    class_date: date,
    content_summary: str,
    logged_by_id: int,
) -> ClassRecord:
    record = ClassRecord(
        contract_id=contract_id,
        actual_teaching_coach_id=actual_teaching_coach_id,
        class_date=class_date,
        content_summary=content_summary,
        logged_by_id=logged_by_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_class_records_for_member(db: Session, member_id: int, limit: int = 5) -> List[ClassRecord]:
    # 1對2 合約雙方都查得到同一筆紀錄，靠 ContractMember join 做到對稱查詢。
    return (
        db.query(ClassRecord)
        .join(Contract, Contract.id == ClassRecord.contract_id)
        .join(ContractMember, ContractMember.contract_id == Contract.id)
        .filter(ContractMember.member_id == member_id)
        .order_by(ClassRecord.class_date.desc())
        .limit(limit)
        .all()
    )
