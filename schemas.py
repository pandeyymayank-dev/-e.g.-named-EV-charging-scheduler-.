"""
schemas.py

Pydantic schemas for request validation and response serialization.
"""
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field


class StationBase(BaseModel):
    name: Optional[str] = "Main Station"
    capacity_kw: float = Field(..., ge=0, description="Station power capacity in kW")


class StationUpdate(BaseModel):
    capacity_kw: float = Field(..., ge=0, description="Station power capacity in kW")
    name: Optional[str] = None


class StationOut(BaseModel):
    id: int
    name: str
    capacity_kw: float

    model_config = ConfigDict(from_attributes=True)


class RequestBase(BaseModel):
    label: str = Field(..., min_length=1, description="EV label or owner name")
    arrival: float = Field(..., description="Arrival hour float (e.g. 8.0, 22.0)")
    deadline: float = Field(..., description="Deadline hour float (e.g. 11.0, 6.0)")
    hours_needed: float = Field(..., ge=0, description="Hours of charging required")
    power_kw: float = Field(..., ge=0, description="Charging power demand in kW")
    station_id: Optional[int] = None


class RequestCreate(RequestBase):
    pass


class RequestOut(BaseModel):
    id: int
    station_id: int
    label: str
    arrival: float
    deadline: float
    hours_needed: float
    power_kw: float

    model_config = ConfigDict(from_attributes=True)


class SimulateParams(BaseModel):
    n: int = Field(default=20, ge=1, le=100, description="Number of random EVs to generate")


class CostSummary(BaseModel):
    uncontrolled_cost: float
    scheduled_cost: float
    savings: float
    savings_pct: float
    scheduled_energy_kwh: float
    uncontrolled_energy_kwh: float


class ScheduleRunResponse(BaseModel):
    scheduled_load: Dict[str, float]
    uncontrolled_load: Dict[str, float]
    assigned_slots: Dict[str, List[Union[int, float]]]
    deadline_met: Dict[str, bool]
    log: List[str]
    capacity_kw: float
    costs: Optional[CostSummary] = None
