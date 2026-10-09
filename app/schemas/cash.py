from datetime import date
from typing import Dict, Optional

from pydantic import BaseModel


class ClosingCreateRequest(BaseModel):
    business_date: date
    shift: str
    # 面額 -> 張數，例如 {"1000": 12, "500": 3}；實點金額由伺服器依此計算
    denominations: Dict[str, int] = {}
    collected_amount: float = 0
    note: Optional[str] = None


class ClosingCreatedResponse(BaseModel):
    id: int


class MovementCreateRequest(BaseModel):
    entry_date: date
    movement_type: str
    amount: float
    counterparty: Optional[str] = None
    description: str


class ReasonRequest(BaseModel):
    reason: str


class NoteRequest(BaseModel):
    note: str


class ReviewRequest(BaseModel):
    note: Optional[str] = None


class FloatRequest(BaseModel):
    amount: float
