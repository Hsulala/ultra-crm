from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.admin import require_role
from app.database import get_db
from app.models import AdminUser, Contract, ContractMember, ContractSession, Member, VenueRentalCoach
from app.schemas.contract import ContractCreateRequest, ContractResponse
from app.services.contract_service import ContractError, create_contract, get_members_for_contract
from app.templating import templates

router = APIRouter(prefix="/admin/contracts", tags=["admin-contracts"])


PAGE_SIZE = 50
VIEW_LABELS = {
    "open": "還有剩餘堂數",
    "done": "已上完",
    "refunded": "已退費",
    "all": "全部",
}


@router.get("/page")
def contracts_page(
    request: Request,
    q: Optional[str] = None,
    view: str = "open",
    course: str = "",
    page: int = 1,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    if view not in VIEW_LABELS:
        view = "open"
    query = db.query(Contract)
    if view == "open":
        query = query.filter(Contract.status != "refunded", Contract.used_sessions < Contract.total_sessions)
    elif view == "done":
        query = query.filter(Contract.status != "refunded", Contract.used_sessions >= Contract.total_sessions)
    elif view == "refunded":
        query = query.filter(Contract.status == "refunded")
    if course in ("strength", "pilates"):
        query = query.filter(Contract.course_type == course)
    q = (q or "").strip()
    if q:
        like = f"%{q}%"
        member_hit = (
            db.query(ContractMember.contract_id)
            .join(Member, Member.id == ContractMember.member_id)
            .filter(Member.name.ilike(like))
        )
        coach_member_ids = db.query(Member.id).filter(Member.role == "coach", Member.name.ilike(like))
        venue_ids = db.query(VenueRentalCoach.id).filter(VenueRentalCoach.name.ilike(like))
        query = query.filter(
            or_(
                Contract.contract_no.ilike(like),
                Contract.id.in_(member_hit),
                Contract.coach_id.in_(coach_member_ids),
                Contract.venue_coach_id.in_(venue_ids),
            )
        )

    total = query.count()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(page, 1), pages)
    contracts = (
        query.order_by(Contract.purchase_date.desc(), Contract.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    member_coaches = {m.id: m.name for m in db.query(Member).filter(Member.role == "coach").all()}
    venue_coach_names = {vc.id: vc.name for vc in db.query(VenueRentalCoach).all()}
    ids = [c.id for c in contracts]
    students_by_contract: dict = {}
    sessions_by_contract: dict = {}
    if ids:
        for cid, name in (
            db.query(ContractMember.contract_id, Member.name)
            .join(Member, Member.id == ContractMember.member_id)
            .filter(ContractMember.contract_id.in_(ids))
        ):
            students_by_contract.setdefault(cid, []).append(name)
        for sess in (
            db.query(ContractSession)
            .filter(ContractSession.contract_id.in_(ids))
            .order_by(ContractSession.session_no)
        ):
            sessions_by_contract.setdefault(sess.contract_id, []).append(sess)

    rows = []
    for c in contracts:
        if c.coach_id is not None:
            coach_name = member_coaches.get(c.coach_id, "未知")
        else:
            coach_name = f"{venue_coach_names.get(c.venue_coach_id, '未知')}（場租）"
        sessions = sessions_by_contract.get(c.id, [])
        dated = [x.session_date for x in sessions if x.session_date]
        rows.append(
            {
                "id": c.id,
                "contract_no": c.contract_no,
                "student_names": "、".join(students_by_contract.get(c.id, [])),
                "coach_name": coach_name,
                "course_type": c.course_type,
                "status": c.status,
                "total_sessions": c.total_sessions,
                "used_sessions": c.used_sessions,
                "purchase_date": c.purchase_date,
                "expiry_date": c.expiry_date,
                "unit_price": c.unit_price,
                "note": c.note,
                "sessions": sessions,
                "last_session": max(dated) if dated else None,
            }
        )

    coaches = db.query(Member).filter(Member.role == "coach").all()
    students = db.query(Member).filter(Member.role == "student").order_by(Member.name).all()
    venue_coaches = db.query(VenueRentalCoach).filter(VenueRentalCoach.is_active == True).all()  # noqa: E712

    return templates.TemplateResponse(
        request,
        "admin/contracts.html",
        {
            "current_user": admin,
            "active": "contracts",
            "contracts": rows,
            "coaches": coaches,
            "venue_coaches": venue_coaches,
            "students": students,
            "q": q,
            "view": view,
            "course": course,
            "view_labels": VIEW_LABELS,
            "page": page,
            "pages": pages,
            "total": total,
        },
    )


@router.post("", response_model=ContractResponse)
def create_contract_endpoint(
    payload: ContractCreateRequest,
    admin: AdminUser = Depends(require_role("manager", "front_desk")),
    db: Session = Depends(get_db),
):
    if (payload.coach_id is None) == (payload.venue_coach_id is None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "請選擇一位教練")

    if payload.coach_id is not None:
        coach = db.get(Member, payload.coach_id)
        if coach is None or coach.role != "coach":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "coach_id 不是有效的教練")
    else:
        venue_coach = db.get(VenueRentalCoach, payload.venue_coach_id)
        if venue_coach is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "venue_coach_id 不是有效的場租教練")

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
            venue_coach_id=payload.venue_coach_id,
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
