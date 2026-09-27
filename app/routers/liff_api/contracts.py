from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.member_auth import require_member_role
from app.database import get_db
from app.models import Member, VenueRentalCoach
from app.schemas.contract import MyContractResponse
from app.services.contract_service import get_contracts_for_member, get_members_for_contract

router = APIRouter(prefix="/api/liff/contracts", tags=["liff-contracts"])


@router.get("/mine", response_model=List[MyContractResponse])
def my_contracts(
    member: Member = Depends(require_member_role("student")),
    db: Session = Depends(get_db),
):
    contracts = get_contracts_for_member(db, member.id)
    result = []
    for c in contracts:
        if c.coach_id is not None:
            coach = db.get(Member, c.coach_id)
            coach_name = coach.name if coach else "未知教練"
        else:
            venue_coach = db.get(VenueRentalCoach, c.venue_coach_id)
            coach_name = f"{venue_coach.name}（場租）" if venue_coach else "未知教練"
        contract_members = get_members_for_contract(db, c.id)
        other_members = [m for m in contract_members if m.id != member.id]
        result.append(
            MyContractResponse(
                id=c.id,
                contract_no=c.contract_no,
                coach_id=c.coach_id,
                coach_name=coach_name,
                course_type=c.course_type,
                purchase_date=c.purchase_date,
                total_sessions=c.total_sessions,
                used_sessions=c.used_sessions,
                remaining_sessions=c.total_sessions - c.used_sessions,
                expiry_date=c.expiry_date,
                status=c.status,
                is_shared=len(contract_members) > 1,
                shared_with_names=[m.name for m in other_members],
            )
        )
    return result
