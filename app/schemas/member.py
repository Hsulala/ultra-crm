from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class MemberCreateRequest(BaseModel):
    member_no: str
    name: str
    role: str  # 'student' 或 'coach'


class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    member_no: str
    name: str
    role: Optional[str]


class BindingCodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    status: str
    expires_at: datetime
