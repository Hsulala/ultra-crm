from datetime import date, time
from typing import Optional

from pydantic import BaseModel, ConfigDict


class VenueBookingCreateRequest(BaseModel):
    customer_name: str
    customer_phone: Optional[str] = None
    party_size: int = 1
    slot_date: date
    slot_start_time: time
    area: str = "strength"


class VenueBookingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    venue_coach_id: int
    customer_name: str
    customer_phone: Optional[str]
    party_size: int
    slot_date: date
    slot_start_time: time
    slot_number: int
    area: str
    status: str


class VenueCoachCreateRequest(BaseModel):
    name: str
    phone: Optional[str] = None


class VenueCoachUpdateRequest(BaseModel):
    name: str
    phone: Optional[str] = None


class VenueCoachResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    phone: Optional[str]
    is_active: bool
