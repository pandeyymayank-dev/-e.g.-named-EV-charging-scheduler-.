# ⚡ EV Charging Smart Scheduler — Control Room Dashboard

An intelligent Electric Vehicle (EV) charging station scheduler and telemetry dashboard designed for peak load flattening and Time-of-Use (TOU) cost optimization using the **Least Slack First (LSF)** algorithm.

Built with **FastAPI**, **SQLAlchemy**, **SQLite**, and a dark SCADA-style **Vanilla JS + Chart.js** telemetry frontend.

---

## 🌟 Key Features

1. **Least Slack First (LSF) Scheduling Algorithm**:
   - Pure Python discrete time-slot simulation with zero database/web dependencies in core scheduler.
   - Evaluates active EVs each slot and prioritizes by:
     $$\text{Slack} = \text{Deadline} - \text{Current Slot} - \text{Remaining Hours}$$
   - Flattens uncontrolled arrival peaks (e.g., shaving 30 kW demand peaks down to 20 kW capacity limit).
   - Seamlessly handles deadlines crossing midnight (e.g., 22:00 arrival with 06:00/07:00 departure).

2. **Time-of-Use (TOU) Tariff & Financial Savings (₹ INR)**:
   - Evaluates energy costs under realistic multi-tier tariffs:
     - **Off-Peak (23:00 – 06:00)**: **₹4.5 / kWh**
     - **Mid-Peak (06:00 – 18:00)**: **₹7.0 / kWh**
     - **Peak (18:00 – 23:00)**: **₹10.0 / kWh**
   - Calculates financial savings by deferring charging from high peak evening hours (₹10/kWh) to overnight off-peak hours (₹4.5/kWh).

3. **Indian EV Fleet Simulation**:
   - Preset configurations for popular Indian electric vehicles:
     - **Tata Nexon EV** (7.2 kW Wallbox)
     - **Tata Punch EV** (7.2 kW Wallbox)
     - **Mahindra XUV400** (7.2 kW Wallbox)
     - **MG ZS EV** (7.4 kW Wallbox)
     - **Tata Tiago EV** (3.3 kW 15A Home AC)
     - **MG Comet EV** (3.3 kW Home AC)
   - One-click `Simulate 20 EVs` endpoint that generates random evening commuter arrivals (17:00–21:00) with overnight charging windows.

4. **Telemetry Control Room Dashboard**:
   - Real-time grouped bar chart comparing hourly uncontrolled baseline vs. scheduled loads against a dashed red capacity line.
   - Live stat cards: Peak Load Reduction %, Deadlines Met, and Total Cost in Rupees (`₹`).
   - Interactive vehicle queue manager and live LSF algorithm decision stream.

---

## 🏗️ System Architecture

```
├── app/
│   ├── scheduler.py         # Pure Python Least Slack First scheduling engine
│   ├── database.py          # SQLAlchemy SQLite connection
│   ├── models.py            # Station and Request database models
│   ├── schemas.py           # Pydantic schemas
│   └── __init__.py
├── frontend/
│   ├── index.html           # Dark telemetry control-room dashboard
│   ├── style.css            # Cyber SCADA dark theme
│   └── app.js               # Reactive vanilla JS and Chart.js integration
├── tests/
│   ├── test_scheduler.py    # Unit tests for core algorithm & edge cases
│   ├── test_api.py          # API integration tests with TestClient (httpx)
│   └── __init__.py
├── main.py                  # FastAPI application & REST endpoints
├── requirements.txt         # Production dependencies
├── render.yaml              # Render deployment blueprint
└── README.md
```

---

## 🔌 REST API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/station` | Get current station configuration (name and capacity kW) |
| `PUT` | `/api/station` | Update station capacity and name |
| `GET` | `/api/requests` | List all EV charging requests in the queue |
| `POST` | `/api/requests` | Add a new EV request (`label`, `arrival`, `deadline`, `hours_needed`, `power_kw`) |
| `DELETE` | `/api/requests/{id}` | Delete an EV request by ID |
| `POST` | `/api/schedule/run` | Run LSF scheduler on current queue and return load profiles, slots, and costs |
| `POST` | `/api/reset` | Reset station to 20 kW and seed the standard 4-EV benchmark |
| `POST` | `/api/simulate` | Generate $N$ random EVs (5-9 PM arrivals, 1-3h, 3.3/7.4/11 kW) with TOU analysis |
| `GET` | `/` | Serves the frontend single-page dashboard |
| `GET` | `/docs` | Interactive Swagger UI API documentation |

---

## 🚀 Quickstart & Local Setup

### Prerequisites
- Python 3.10+
- pip

### 1. Clone the repository
```bash
git clone https://github.com/your-username/ev-charging-scheduler.git
cd ev-charging-scheduler
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the development server
```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser.

### 4. Run automated tests
```bash
pytest -v
```

All 17 unit and API integration tests will run and pass:
- 4-EV example (30 kW peak shaved to 20 kW capacity limit)
- Impossible deadlines
- Zero capacity handling
- Empty list resilience
- Midnight crossover support (e.g. 22:00 to 07:00 next day)
- Time-of-Use tariff calculations
- Simulation endpoints and CRUD routes

---

## 🌐 Deploy to Render

This repository includes a [`render.yaml`](render.yaml) blueprint for automated zero-configuration deployment.

### Method 1: Deploy with Blueprint
1. Push this repository to your GitHub account.
2. Sign in to [Render](https://render.com).
3. Click **New +** > **Blueprint**.
4. Select your `ev-charging-scheduler` repository.
5. Render will detect `render.yaml` and deploy the web service automatically.

### Method 2: Manual Web Service
1. In Render, select **New +** > **Web Service**.
2. Connect your GitHub repository.
3. Configure the service:
   - **Environment**: `Python`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Click **Create Web Service**.

Your application will be live at `https://<your-service-name>.onrender.com`.

---

## 📜 License
MIT License. Free for open-source and commercial use.
