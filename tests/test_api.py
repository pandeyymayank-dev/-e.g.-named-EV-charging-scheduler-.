"""
tests/test_api.py

API integration tests using FastAPI TestClient (httpx).
Tests:
  - GET /api/station (default 20 kW capacity)
  - PUT /api/station (update capacity)
  - POST /api/reset (resets to 4-EV benchmark)
  - GET /api/requests
  - POST /api/requests
  - DELETE /api/requests/{id} (success & 404)
  - POST /api/schedule/run (uncontrolled peak 30, scheduled peak 20)
  - GET / (frontend static files serving)
"""
import pytest
from fastapi.testclient import TestClient
from main import app, seed_default_station
from database import Base, SessionLocal, engine
from models import Station, Request


@pytest.fixture(autouse=True)
def setup_db():
    """Ensure clean database tables and seeded station for each test run."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Reset tables
        db.query(Request).delete()
        station = db.query(Station).first()
        if not station:
            station = Station(id=1, name="Default Station", capacity_kw=20.0)
            db.add(station)
        else:
            station.capacity_kw = 20.0
            station.name = "Default Station"
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_get_station(client: TestClient):
    """Test retrieving primary station configuration."""
    response = client.get("/api/station")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Default Station"
    assert data["capacity_kw"] == 20.0
    assert "id" in data


def test_update_station(client: TestClient):
    """Test updating station capacity."""
    response = client.put("/api/station", json={"capacity_kw": 35.0, "name": "Supercharger Hub"})
    assert response.status_code == 200
    data = response.json()
    assert data["capacity_kw"] == 35.0
    assert data["name"] == "Supercharger Hub"

    # Verify retrieval reflects update
    get_res = client.get("/api/station")
    assert get_res.json()["capacity_kw"] == 35.0


def test_reset_endpoint(client: TestClient):
    """Test POST /api/reset resets station to 20 kW and seeds the 4-EV benchmark."""
    response = client.post("/api/reset")
    assert response.status_code == 200
    data = response.json()

    assert data["station"]["capacity_kw"] == 20.0
    assert len(data["requests"]) == 4

    labels = [r["label"] for r in data["requests"]]
    assert "EV 1" in labels
    assert "EV 2" in labels
    assert "EV 3" in labels
    assert "EV 4" in labels


def test_crud_requests(client: TestClient):
    """Test creating, listing, and deleting EV charging requests."""
    # 1. Start clean
    client.post("/api/reset")

    # 2. List requests (should be 4)
    res = client.get("/api/requests")
    assert res.status_code == 200
    initial_count = len(res.json())
    assert initial_count == 4

    # 3. Create a new request
    new_req = {
        "label": "Custom EV 5",
        "arrival": 10.0,
        "deadline": 14.0,
        "hours_needed": 2.0,
        "power_kw": 8.0,
    }
    create_res = client.post("/api/requests", json=new_req)
    assert create_res.status_code == 201
    created_data = create_res.json()
    req_id = created_data["id"]
    assert created_data["label"] == "Custom EV 5"
    assert created_data["power_kw"] == 8.0

    # 4. Verify list count increased
    list_res = client.get("/api/requests")
    assert len(list_res.json()) == initial_count + 1

    # 5. Delete the created request
    del_res = client.delete(f"/api/requests/{req_id}")
    assert del_res.status_code == 200
    assert del_res.json()["id"] == req_id

    # 6. Verify 404 on deleting non-existent ID
    del_404 = client.delete(f"/api/requests/{req_id}")
    assert del_404.status_code == 404


def test_schedule_run_endpoint_four_ev_benchmark(client: TestClient):
    """
    Test POST /api/schedule/run on the 4-EV benchmark:
    Uncontrolled peak should be 30 kW, scheduled peak must be flattened to 20 kW.
    """
    # Reset to 4-EV example with 20 kW station
    client.post("/api/reset")

    # Run scheduler
    res = client.post("/api/schedule/run")
    assert res.status_code == 200
    data = res.json()

    metrics = data["metrics"]
    assert metrics["capacity_kw"] == 20.0
    assert metrics["uncontrolled_peak_kw"] == 30.0
    assert metrics["scheduled_peak_kw"] == 20.0
    assert metrics["all_deadlines_met"] is True
    assert metrics["total_requests"] == 4

    # Verify per-slot loads
    scheduled_load = data["scheduled_load"]
    assert scheduled_load["8"] == 20.0
    assert scheduled_load["9"] == 20.0
    assert scheduled_load["10"] == 20.0
    assert scheduled_load["11"] == 20.0

    uncontrolled_load = data["uncontrolled_load"]
    assert uncontrolled_load["8"] == 30.0
    assert uncontrolled_load["9"] == 30.0
    assert uncontrolled_load["10"] == 20.0

    # Verify log output exists
    assert len(data["log"]) > 0
    assert any("CHARGE" in entry for entry in data["log"])
    assert any("DEFER" in entry for entry in data["log"])


def test_serve_frontend_static_files(client: TestClient):
    """Test serving the frontend folder at /."""
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "EV Charging Smart Scheduler" in res.text
    assert "style.css" in res.text
    assert "app.js" in res.text

    # Test serving css and js static files directly
    css_res = client.get("/style.css")
    assert css_res.status_code == 200
    assert "css" in css_res.headers["content-type"]

    js_res = client.get("/app.js")
    assert js_res.status_code == 200
    assert "javascript" in js_res.headers["content-type"]


def test_simulate_endpoint_default_20_evs(client: TestClient):
    """
    Test POST /api/simulate generates 20 random EVs:
      - Arrivals 5-9 PM (17:00 - 21:00)
      - Hours needed 1-3 hours
      - Power from {3.3, 7.4, 11.0} kW
      - TOU costs computed: uncontrolled vs scheduled
    """
    res = client.post("/api/simulate")
    assert res.status_code == 200
    data = res.json()

    assert data["simulated_count"] == 20
    generated = data["requests_generated"]
    assert len(generated) == 20

    # Verify attributes of generated EVs
    for ev in generated:
        assert 17.0 <= ev["arrival"] <= 21.0, f"Arrival {ev['arrival']} outside 17-21"
        assert 1.0 <= ev["hours_needed"] <= 3.0, f"Hours {ev['hours_needed']} outside 1-3"
        assert ev["power_kw"] in [3.3, 7.4, 11.0], f"Invalid power {ev['power_kw']}"

    # Verify TOU costs are calculated
    assert "costs" in data
    costs = data["costs"]
    assert "scheduled_cost" in costs
    assert "uncontrolled_cost" in costs
    assert "savings" in costs
    assert costs["uncontrolled_cost"] > 0
    assert costs["scheduled_cost"] > 0
    # Because charging shifted from peak (18-23h @ $10) to off-peak (23-06h @ $4.5), scheduled cost should be lower
    assert costs["scheduled_cost"] <= costs["uncontrolled_cost"]
    assert costs["savings"] >= 0


def test_simulate_endpoint_custom_count(client: TestClient):
    """Test POST /api/simulate with custom count ?n=10 and body."""
    # Query param test
    res = client.post("/api/simulate?n=10")
    assert res.status_code == 200
    data = res.json()
    assert data["simulated_count"] == 10
    assert len(data["requests_generated"]) == 10

    # JSON body test
    res_body = client.post("/api/simulate", json={"n": 5})
    assert res_body.status_code == 200
    data_body = res_body.json()
    assert data_body["simulated_count"] == 5
    assert len(data_body["requests_generated"]) == 5


def test_time_of_use_tariff_calculation():
    """Directly verify the TOU tariff schedule logic and cost calculations."""
    from main import get_tou_rate, calculate_tou_costs

    # Off-peak: 23:00 - 06:00 = 4.5
    assert get_tou_rate(23.0) == 4.5
    assert get_tou_rate(0.0) == 4.5
    assert get_tou_rate(2.0) == 4.5
    assert get_tou_rate(5.5) == 4.5
    assert get_tou_rate(24.0) == 4.5  # midnight wrapped
    assert get_tou_rate(25.0) == 4.5  # 1 AM wrapped

    # Mid-peak / Day: 06:00 - 18:00 = 7.0
    assert get_tou_rate(6.0) == 7.0
    assert get_tou_rate(10.0) == 7.0
    assert get_tou_rate(17.5) == 7.0

    # Peak / Evening: 18:00 - 23:00 = 10.0
    assert get_tou_rate(18.0) == 10.0
    assert get_tou_rate(20.0) == 10.0
    assert get_tou_rate(22.5) == 10.0

    # Test cost calculation:
    # 10 kW charged at hour 19 (peak @ 10) vs shifted to hour 23 (off-peak @ 4.5)
    sched_load = {23: 10.0}
    unctrl_load = {19: 10.0}
    costs = calculate_tou_costs(sched_load, unctrl_load, slot_hours=1.0)

    assert costs["uncontrolled_cost"] == 100.0  # 10 kW * 1h * 10
    assert costs["scheduled_cost"] == 45.0      # 10 kW * 1h * 4.5
    assert costs["savings"] == 55.0             # 100 - 45
    assert costs["savings_pct"] == 55.0
