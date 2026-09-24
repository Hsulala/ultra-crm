from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import Contract, ContractMember, Member


class ContractError(Exception):
    pass


def create_contract(
    db: Session,
    *,
    coach_id: int,
    member_ids: List[int],
    purchase_date: date,
    unit_price,
    total_sessions: int,
    contract_no: Optional[str] = None,
    status: str = "active",
    expiry_date: Optional[date] = None,
) -> Contract:
    if not member_ids:
        raise ContractError("合約至少要有一位學員")
    if len(member_ids) > 2:
        raise ContractError("合約最多支援 1對2（兩位學員）")

    contract = Contract(
        contract_no=contract_no,
        coach_id=coach_id,
        purchase_date=purchase_date,
        unit_price=unit_price,
        total_sessions=total_sessions,
        used_sessions=0,
        expiry_date=expiry_date,
        status=status,
    )
    db.add(contract)
    db.flush()  # 取得 contract.id，還在同一個交易裡

    for member_id in member_ids:
        db.add(ContractMember(contract_id=contract.id, member_id=member_id))

    db.commit()
    db.refresh(contract)
    return contract


def get_contracts_for_member(db: Session, member_id: int) -> List[Contract]:
    return (
        db.query(Contract)
        .join(ContractMember, ContractMember.contract_id == Contract.id)
        .filter(ContractMember.member_id == member_id)
        .order_by(Contract.purchase_date.desc())
        .all()
    )


def get_members_for_contract(db: Session, contract_id: int) -> List[Member]:
    return (
        db.query(Member)
        .join(ContractMember, ContractMember.member_id == Member.id)
        .filter(ContractMember.contract_id == contract_id)
        .all()
    )


def get_active_contracts_for_coach(db: Session, coach_id: int) -> List[Contract]:
    """教練版「紀錄課程」的合約挑選清單：該教練名下所有「進行中」合約
    （紀錄課程要指定合約，不能只給學員姓名——同一學員可能同時有多份合約）。
    目前先給教練自己名下登記的合約；之後接上 Phase 3 排班後可以換成
    「當天實際排定要教的學員」，會更準確地涵蓋代課情境。"""
    return db.query(Contract).filter(Contract.coach_id == coach_id, Contract.status == "active").all()
