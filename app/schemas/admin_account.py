from typing import Optional

from pydantic import BaseModel


class AdminAccountCreateRequest(BaseModel):
    username: str
    password: str
    role: str
    linked_member_id: Optional[int] = None


class AdminAccountResponse(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    linked_member_id: Optional[int] = None

    class Config:
        from_attributes = True
