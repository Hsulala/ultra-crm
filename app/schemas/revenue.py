from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict


class RevenueEntryCreateRequest(BaseModel):
    entry_date: date
    item_category: str
    item_name: str
    payment_method: str
    amount: float
    coach_id: Optional[int] = None
    content: Optional[str] = None
    contract_id: Optional[int] = None


class RevenueEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    item_category: str
    item_name: str
    coach_id: Optional[int]
    payment_method: str
    amount: float
