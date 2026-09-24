from typing import Optional

from pydantic import BaseModel


class BindingRedeemRequest(BaseModel):
    code: str


class BindingRedeemResponse(BaseModel):
    status: str
    role: Optional[str]
    name: str
