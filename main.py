"""
main.py

FastAPI backend application for EV Charging Scheduler.
Endpoints:
  - POST /api/requests
  - GET /api/requests
  - DELETE /api/requests/{id}
  - GET /api/station
  - PUT /api/station
  - POST /api/schedule/run
  - POST /api/reset
Serves frontend/ as static files at /.
"""
import os
import random
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine, get_db
from models import Request, Station
from schemas import (
    CostSummary,
    RequestCreate,
    RequestOut,
    SimulateParams,
    StationOut,
    StationUpdate,
)
from app.scheduler import schedule


def get_tou_rate(hour: float) -> float:
    """
    Time-of-Use (TOU) tariff:
      - 23:00 - 06:00: 4.5 per kWh (Off-Peak)
      - 06:00 - 18:00: 7.0 per kWh (Mid-Peak / Day)
      - 18:00 - 23:00: 10.0 per kWh (Peak / Evening)
    """
    clock_hour = float(hour) % 24.0
    if 23.0 <= clock_hour or clock_hour < 6.0:
        return 4.5
    elif 6.0 <= clock_hour < 18.0:
        return 7.0
    else:
        return 10.0


def calculate_tou_costs(
    scheduled_load: Dict[Any, float],
    uncontrolled_load: Dict[Any, float],
    slot_hours: float = 1.0,
) -> Dict[str, Any]:
    """Calculate energy cost in Indian Rupees (INR / ₹) under Time-of-Use tariff."""
    sched_cost = 0.0
    unctrl_cost = 0.0
    sched_energy = 0.0
    unctrl_energy = 0.0

    all_slots = set(scheduled_load.keys()) | set(uncontrolled_load.keys())
    for s in all_slots:
        rate = get_tou_rate(float(s))
        s_load = scheduled_load.get(s, 0.0)
        u_load = uncontrolled_load.get(s, 0.0)

        s_kwh = s_load * slot_hours
        u_kwh = u_load * slot_hours

        sched_cost += s_kwh * rate
        unctrl_cost += u_kwh * rate
        sched_energy += s_kwh
        unctrl_energy += u_kwh

    savings = unctrl_cost - sched_cost
    savings_pct = (savings / unctrl_cost * 100.0) if unctrl_cost > 0 else 0.0

    return {
        "scheduled_cost": round(sched_cost, 2),
        "uncontrolled_cost": round(unctrl_cost, 2),
        "savings": round(savings, 2),
        "savings_pct": round(savings_pct, 1),
        "scheduled_energy_kwh": round(sched_energy, 2),
        "uncontrolled_energy_kwh": round(unctrl_energy, 2),
        "currency": "INR",
        "currency_symbol": "₹",
        "tariff_schedule": {
            "off_peak": 4.5,
            "mid_peak": 7.0,
            "peak": 10.0,
            "description": "23:00-06:00: ₹4.5/kWh | 06:00-18:00: ₹7.0/kWh | 18:00-23:00: ₹10.0/kWh",
        },
    }


def seed_default_station(db: Session) -> Station:
    """Ensure at least one default station exists with 20 kW capacity."""
    station = db.query(Station).first()
    if not station:
        station = Station(id=1, name="Default Station", capacity_kw=20.0)
        db.add(station)
        db.commit()
        db.refresh(station)
    return station


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create DB tables
    Base.metadata.create_all(bind=engine)
    # Seed default station
    db = SessionLocal()
    try:
        seed_default_station(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="EV Charging Scheduler API",
    description="Optimal EV charging scheduling with Least Slack First and peak flattening.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Station Endpoints ---
@app.get("/api/station", response_model=StationOut)
def get_station(db: Session = Depends(get_db)):
    """Retrieve the primary station details."""
    station = db.query(Station).first()
    if not station:
        station = seed_default_station(db)
    return station


@app.put("/api/station", response_model=StationOut)
def update_station(payload: StationUpdate, db: Session = Depends(get_db)):
    """Update primary station capacity and optionally name."""
    station = db.query(Station).first()
    if not station:
        station = seed_default_station(db)

    station.capacity_kw = payload.capacity_kw
    if payload.name is not None:
        station.name = payload.name

    db.commit()
    db.refresh(station)
    return station


# --- EV Requests Endpoints ---
@app.get("/api/requests", response_model=List[RequestOut])
def list_requests(db: Session = Depends(get_db)):
    """List all EV charging requests."""
    return db.query(Request).order_by(Request.arrival.asc(), Request.id.asc()).all()


@app.post("/api/requests", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
def create_request(payload: RequestCreate, db: Session = Depends(get_db)):
    """Create a new EV charging request."""
    station = db.query(Station).first()
    if not station:
        station = seed_default_station(db)

    station_id = payload.station_id if payload.station_id else station.id

    db_request = Request(
        station_id=station_id,
        label=payload.label,
        arrival=payload.arrival,
        deadline=payload.deadline,
        hours_needed=payload.hours_needed,
        power_kw=payload.power_kw,
    )
    db.add(db_request)
    db.commit()
    db.refresh(db_request)
    return db_request


@app.delete("/api/requests/{request_id}")
def delete_request(request_id: int, db: Session = Depends(get_db)):
    """Delete an EV charging request by ID."""
    req = db.query(Request).filter(Request.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail=f"Request with id {request_id} not found")

    db.delete(req)
    db.commit()
    return {"message": "Request deleted successfully", "id": request_id}


# --- Reset & Schedule Endpoints ---
@app.post("/api/reset")
def reset_four_ev_example(db: Session = Depends(get_db)):
    """
    Reset database:
      1. Reset default station capacity to 20.0 kW.
      2. Clear all existing requests.
      3. Insert the standard 4-EV example:
         - EV 1: arrival=8.0, deadline=11.0, hours_needed=2.0, power_kw=10.0
         - EV 2: arrival=8.0, deadline=9.0, hours_needed=1.0, power_kw=10.0
         - EV 3: arrival=8.0, deadline=12.0, hours_needed=3.0, power_kw=10.0
         - EV 4: arrival=9.0, deadline=12.0, hours_needed=2.0, power_kw=10.0
    """
    station = db.query(Station).first()
    if not station:
        station = Station(id=1, name="Default Station", capacity_kw=20.0)
        db.add(station)
        db.commit()
        db.refresh(station)
    else:
        station.capacity_kw = 20.0
        station.name = "Default Station"
        db.commit()

    # Clear all requests
    db.query(Request).delete()
    db.commit()

    # Seed 4-EV benchmark
    ev_examples = [
        {"label": "EV 1", "arrival": 8.0, "deadline": 11.0, "hours_needed": 2.0, "power_kw": 10.0},
        {"label": "EV 2", "arrival": 8.0, "deadline": 9.0, "hours_needed": 1.0, "power_kw": 10.0},
        {"label": "EV 3", "arrival": 8.0, "deadline": 12.0, "hours_needed": 3.0, "power_kw": 10.0},
        {"label": "EV 4", "arrival": 9.0, "deadline": 12.0, "hours_needed": 2.0, "power_kw": 10.0},
    ]

    created = []
    for ev in ev_examples:
        req = Request(station_id=station.id, **ev)
        db.add(req)
        created.append(req)

    db.commit()
    for req in created:
        db.refresh(req)

    return {
        "message": "Reset complete: 4-EV example loaded with 20 kW station",
        "station": {"id": station.id, "name": station.name, "capacity_kw": station.capacity_kw},
        "requests": [
            {
                "id": r.id,
                "label": r.label,
                "arrival": r.arrival,
                "deadline": r.deadline,
                "hours_needed": r.hours_needed,
                "power_kw": r.power_kw,
            }
            for r in created
        ],
    }


@app.post("/api/schedule/run")
def run_schedule(db: Session = Depends(get_db)):
    """
    Loads current EV requests and station capacity from DB, executes the
    pure Python scheduler, and returns complete scheduling results with TOU cost analysis.
    """
    station = db.query(Station).first()
    if not station:
        station = seed_default_station(db)

    db_requests = db.query(Request).order_by(Request.arrival.asc(), Request.id.asc()).all()

    requests_data = [
        {
            "id": r.id,
            "label": r.label,
            "arrival": r.arrival,
            "deadline": r.deadline,
            "hours_needed": r.hours_needed,
            "power_kw": r.power_kw,
        }
        for r in db_requests
    ]

    sched_result = schedule(requests_data, capacity_kw=station.capacity_kw, slot_minutes=60)

    # Stringify dict keys for standard JSON response
    scheduled_load = {str(k): v for k, v in sched_result.scheduled_load.items()}
    uncontrolled_load = {str(k): v for k, v in sched_result.uncontrolled_load.items()}
    assigned_slots = {str(k): v for k, v in sched_result.assigned_slots.items()}
    deadline_met = {str(k): v for k, v in sched_result.deadline_met.items()}
    log = [str(entry) for entry in sched_result.log]

    # Calculate summary metrics
    uncontrolled_peak = max(sched_result.uncontrolled_load.values(), default=0.0)
    scheduled_peak = max(sched_result.scheduled_load.values(), default=0.0)

    # Calculate Time-of-Use costs
    costs = calculate_tou_costs(
        sched_result.scheduled_load,
        sched_result.uncontrolled_load,
        slot_hours=1.0,
    )

    return {
        "capacity_kw": station.capacity_kw,
        "station_name": station.name,
        "scheduled_load": scheduled_load,
        "uncontrolled_load": uncontrolled_load,
        "assigned_slots": assigned_slots,
        "deadline_met": deadline_met,
        "log": log,
        "costs": costs,
        "metrics": {
            "capacity_kw": station.capacity_kw,
            "uncontrolled_peak_kw": uncontrolled_peak,
            "scheduled_peak_kw": scheduled_peak,
            "all_deadlines_met": all(sched_result.deadline_met.values()) if sched_result.deadline_met else True,
            "total_requests": len(requests_data),
            "uncontrolled_cost": costs["uncontrolled_cost"],
            "scheduled_cost": costs["scheduled_cost"],
            "cost_savings": costs["savings"],
            "cost_savings_pct": costs["savings_pct"],
        },
    }


@app.post("/api/simulate")
def simulate_evs(
    n: Optional[int] = None,
    payload: Optional[SimulateParams] = None,
    db: Session = Depends(get_db),
):
    """
    Generate N random EVs:
      - Arrivals: 5-9 PM (17:00 - 21:00)
      - Hours needed: 1.0 - 3.0 hours
      - Power: choice from 3.3, 7.4, or 11.0 kW
      - Deadlines: morning departure (6:00 - 8:00 AM, crossing midnight)
    Clears existing requests, seeds the N random EVs, and returns scheduling + TOU cost analysis.
    """
    count = 20
    if payload and payload.n:
        count = payload.n
    elif n is not None:
        count = n

    station = db.query(Station).first()
    if not station:
        station = seed_default_station(db)

    # Clear existing requests
    db.query(Request).delete()
    db.commit()

    ev_models = [
        "Tata Nexon EV",
        "Tata Punch EV",
        "Mahindra XUV400",
        "MG ZS EV",
        "Tata Tiago EV",
        "Tata Curvv EV",
        "Mahindra BE 6e",
        "BYD Atto 3",
        "Hyundai Ioniq 5",
        "MG Comet EV",
        "Tata Tigor EV",
        "Mahindra XUV.e8",
    ]
    power_choices = [3.3, 7.4, 11.0]

    created = []
    for i in range(count):
        # arrivals 5-9 PM (17.0 - 21.0)
        arrival = round(random.choice([17.0, 17.5, 18.0, 18.5, 19.0, 19.5, 20.0, 20.5, 21.0]), 1)
        # hours 1-3
        hours_needed = round(random.choice([1.0, 1.5, 2.0, 2.5, 3.0]), 1)
        # power from 3.3/7.4/11 kW
        power_kw = random.choice(power_choices)
        # morning deadline (6.0 - 8.0 AM, crossing midnight)
        deadline = round(random.choice([6.0, 6.5, 7.0, 7.5, 8.0]), 1)
        model = ev_models[i % len(ev_models)]
        label = f"{model} #{i+1}"

        req = Request(
            station_id=station.id,
            label=label,
            arrival=arrival,
            deadline=deadline,
            hours_needed=hours_needed,
            power_kw=power_kw,
        )
        db.add(req)
        created.append(req)

    db.commit()
    for req in created:
        db.refresh(req)

    # Run scheduler on the simulated fleet
    result = run_schedule(db)
    result["simulated_count"] = count
    result["requests_generated"] = [
        {
            "id": r.id,
            "label": r.label,
            "arrival": r.arrival,
            "deadline": r.deadline,
            "hours_needed": r.hours_needed,
            "power_kw": r.power_kw,
        }
        for r in created
    ]
    return result


# Ensure frontend directory exists before mounting static files
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
os.makedirs(frontend_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
