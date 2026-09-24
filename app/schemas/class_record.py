from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ClassRecordCreateRequest(BaseModel):
    contract_id: int
    class_date: date
    content_summary: str


class ClassRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_id: int
    actual_teaching_coach_id: int
    coach_name: str
    class_date: date
    content_summary: str


class ActiveContractResponse(BaseModel):
    contract_id: int
    contract_no: Optional[str]
    student_names: List[str]
    remaining_sessions: int
