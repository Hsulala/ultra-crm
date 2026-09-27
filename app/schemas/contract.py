from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ContractCreateRequest(BaseModel):
    coach_id: Optional[int] = None
    venue_coach_id: Optional[int] = None
    member_ids: List[int] = []
    course_type: str = "strength"
    purchase_date: date
    unit_price: float
    total_sessions: int
    contract_no: Optional[str] = None
    status: str = "active"
    expiry_date: Optional[date] = None
    # 填了 new_student_name 代表這位是全新學員，後端會自動建會員資料，
    # 不用先切去會員頁面建人——見 contract_service.create_contract。
    new_student_name: Optional[str] = None
    new_student_phone: Optional[str] = None


class ContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_no: Optional[str]
    coach_id: Optional[int]
    venue_coach_id: Optional[int]
    course_type: str
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
    coach_id: Optional[int]
    coach_name: str
    course_type: str
    purchase_date: date
    total_sessions: int
    used_sessions: int
    remaining_sessions: int
    expiry_date: Optional[date]
    status: str
    is_shared: bool
    shared_with_names: List[str]
