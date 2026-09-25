from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class MemberCreateRequest(BaseModel):
    member_no: str
    name: str
    role: str  # 'student' 或 'coach'
    # 單月會籍才需要填；單次會籍不用（單純登記一筆營收即可）。
    membership_start_date: Optional[date] = None
    membership_active_until: Optional[date] = None


class MembershipUpdateRequest(BaseModel):
    membership_start_date: Optional[date] = None
    membership_active_until: Optional[date] = None


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    member_no: str
    name: str
    role: Optional[str]
    membership_start_date: Optional[date]
    membership_active_until: Optional[date]


class BindingCodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    status: str
    expires_at: datetime
