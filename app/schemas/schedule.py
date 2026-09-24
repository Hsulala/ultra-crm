from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class UnavailabilityEntry(BaseModel):
    unavailable_date: date
    shift: str
    note: Optional[str] = None


class UnavailabilitySubmitRequest(BaseModel):
    target_month: date  # 該月第一天，例如 2026-11-01 代表 11 月
    entries: List[UnavailabilityEntry]


class ScheduleAssignRequest(BaseModel):
    work_date: date
    shift: str
    coach_id: Optional[int] = None
    admin_user_id: Optional[int] = None


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    work_date: date
    shift: str
    coach_id: Optional[int]
    admin_user_id: Optional[int]
    status: str


class PublishMonthRequest(BaseModel):
    year: int
    month: int
