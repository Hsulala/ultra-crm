from datetime import date, time

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
    coach_id: int
    contract_id: int
    slot_date: date
    slot_start_time: time
    area: str
    status: str


class AdminBookingCreateRequest(BaseModel):
    coach_id: int
    contract_id: int
    slot_date: date
    slot_start_time: time
