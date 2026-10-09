from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AttractionOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    admission_mode: str
    requires_real_name: bool
    no_show_limit: int | None


class SlotCreate(BaseModel):
    attraction_id: str
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(gt=0, le=100_000)


class SlotOut(BaseModel):
    id: str
    attraction_id: str
    starts_at: str
    ends_at: str
    capacity: int
    remaining_capacity: int


class ReservationCreate(BaseModel):
    attraction_id: str
    slot_id: str
    visitor_reference: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1, le=10)


class ReservationOut(BaseModel):
    id: str
    tenant_id: str
    attraction_id: str
    slot_id: str
    quantity: int
    status: str
    validation_code: str
    created_at: str


class ValidationCreate(BaseModel):
    validation_code: str = Field(min_length=8, max_length=200)


class ValidationOut(BaseModel):
    reservation_id: str
    status: str
    validated_at: str


class TenantMetricsOut(BaseModel):
    tenant_id: str
    reservations_confirmed: int
    reservations_cancelled: int
    admissions_validated: int
    seats_reserved: int

