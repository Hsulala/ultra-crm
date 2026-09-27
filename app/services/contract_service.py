import re
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models import Contract, ContractMember, Member


class ContractError(Exception):
    pass


def generate_next_member_no(db: Session) -> str:
    """沿用現有 UF0001 格式，找目前最大的編號＋1。找不到任何 UF 開頭的
    編號就從 UF0001 開始——本機新專案跟已經有歷史資料匯入後都能正常接續。"""
    existing = db.query(Member.member_no).filter(Member.member_no.like("UF%")).all()
    max_no = 0
    for (member_no,) in existing:
        match = re.fullmatch(r"UF(\d+)", member_no or "")
        if match:
            max_no = max(max_no, int(match.group(1)))
    return f"UF{max_no + 1:04d}"


def create_contract(
    db: Session,
    *,
    member_ids: List[int],
    course_type: str,
    purchase_date: date,
    unit_price,
    total_sessions: int,
    coach_id: Optional[int] = None,
    venue_coach_id: Optional[int] = None,
    contract_no: Optional[str] = None,
    status: str = "active",
    expiry_date: Optional[date] = None,
    new_student_name: Optional[str] = None,
    new_student_phone: Optional[str] = None,
) -> Contract:
    """new_student_name 有填的話，會先自動建一個新學員（自動產生會員編號），
    再把它併入 member_ids 一起掛上合約——這樣合約頁面就能一次搞定全新客戶成交，
    不用先切去會員頁面建人。目前一次合約最多支援補一位新學員（1對2 情境下，
    另一位可以是既有會員也可以是這位新學員）。

    coach_id / venue_coach_id 恰好擇一：重訓只能是店內正職（coach_id）；
    皮拉提斯店內正職、場租教練都可能開（見 app/models/contract.py 的說明）。"""
    if course_type not in ("strength", "pilates"):
        raise ContractError("course_type 必須是 strength 或 pilates")
    if (coach_id is None) == (venue_coach_id is None):
        raise ContractError("coach_id 跟 venue_coach_id 必須擇一填寫")
    if venue_coach_id is not None and course_type != "pilates":
        raise ContractError("場租教練只能開皮拉提斯合約，重訓場地租借請用「場租教練」約課功能")

    final_member_ids = list(member_ids)

    if new_student_name:
        new_member = Member(
            member_no=generate_next_member_no(db),
            name=new_student_name,
            role="student",
        )
        db.add(new_member)
        db.flush()  # 取得 new_member.id
        final_member_ids.append(new_member.id)

    if not final_member_ids:
        raise ContractError("合約至少要有一位學員")
    if len(final_member_ids) > 2:
        raise ContractError("合約最多支援 1對2（兩位學員）")

    contract = Contract(
        contract_no=contract_no,
        coach_id=coach_id,
        venue_coach_id=venue_coach_id,
        course_type=course_type,
        purchase_date=purchase_date,
        unit_price=unit_price,
        total_sessions=total_sessions,
        used_sessions=0,
        expiry_date=expiry_date,
        status=status,
    )
    db.add(contract)
    db.flush()  # 取得 contract.id，還在同一個交易裡

    for member_id in final_member_ids:
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


def get_active_pilates_contracts(db: Session) -> List[Contract]:
    """總覽頁皮拉提斯共用欄位的約課挑選清單：不分店內正職／場租教練，
    只要是「進行中」的皮拉提斯合約都列出來（見 Contract 的說明，皮拉提斯
    合約兩種教練都可能開）。"""
    return (
        db.query(Contract)
        .filter(Contract.course_type == "pilates", Contract.status == "active")
        .all()
    )
