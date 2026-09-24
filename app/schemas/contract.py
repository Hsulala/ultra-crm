from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ContractCreateRequest(BaseModel):
    coach_id: int
    member_ids: List[int]
    purchase_date: date
    unit_price: float
    total_sessions: int
    contract_no: Optional[str] = None
    status: str = "active"
    expiry_date: Optional[date] = None


class ContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_no: Optional[str]
    coach_id: int
    purchase_date: date
    unit_price: float
    total_sessions: int
    used_sessions: int
    expiry_date: Optional[date]
    status: str


class MyContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_no: Optional[str]
    coach_id: int
    coach_name: str
    purchase_date: date
    total_sessions: int
    used_sessions: int
    remaining_sessions: int
    expiry_date: Optional[date]
    status: str
    is_shared: bool
    shared_with_names: List[str]
