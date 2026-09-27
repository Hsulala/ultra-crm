from datetime import date, time
from typing import Optional

from pydantic import BaseModel, ConfigDict


class BookingCreateRequest(BaseModel):
    coach_id: int
    contract_id: int
    slot_date: date
    slot_start_time: time
    area: str


class BookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    coach_id: Optional[int]
    venue_coach_id: Optional[int]
    contract_id: int
    slot_date: date
    slot_start_time: time
    area: str
    status: str


class AdminBookingCreateRequest(BaseModel):
    # 不填的話後端會直接跟著合約的教練走（見 booking_service.create_booking）——
    # 皮拉提斯共用欄位新增預約就是不填，因為合約可能是場租教練開的。
    coach_id: Optional[int] = None
    contract_id: int
    slot_date: date
    slot_start_time: time
