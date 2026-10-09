from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class RevenueEntryCreateRequest(BaseModel):
    entry_date: date
    item_category: str
    item_name: str
    payment_method: str
    amount: float
    coach_id: Optional[int] = None
    content: Optional[str] = None
    contract_id: Optional[int] = None
    remittance_last5: Optional[str] = None

    @field_validator("remittance_last5")
    @classmethod
    def _last5_digits(cls, v):
        v = (v or "").strip()
        if not v:
            return None
        if not (len(v) == 5 and v.isdigit()):
            raise ValueError("匯款末五碼必須是 5 位數字")
        return v


class RevenueEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    item_category: str
    item_name: str
    coach_id: Optional[int]
    payment_method: str
    remittance_last5: Optional[str] = None
    amount: float
