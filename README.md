# Hong Kong Weather Prediction Market AI Agent

An end-to-end quantitative trading system that predicts probability distributions of Hong Kong daily **maximum (highest)** and **minimum (lowest)** temperatures, compares against Polymarket prediction market prices in real time, and executes paper trading signals under strict Section 35 quantitative risk controls.

---

## Milestone Status

- [x] **M0 — Feasibility Research**: Completed & approved (`docs/feasibility.md`)
- [x] **M1 — Infrastructure**: Python project scaffolding, Docker Compose, PostgreSQL schema (10 tables), logging & config
- [x] **M2 — HKO Collector**: Ingestion pipeline for HKO observations & forecasts with data-quality validation
- [x] **M3 — Polymarket Collector**: Discovery for Highest & Lowest temperature markets & NegRisk/discrete bucket schema parser
- [x] **M4 — Dataset & Feature Pipeline**: Feature engineering & anti-leakage verification
- [x] **M5 — Weather ML Model**: Dual-target calibrated LightGBM model (Max & Min temp distributions)
- [x] **M6 — Trading Logic**: Edge/EV engine, fee/slippage models & risk controls
- [x] **M7 — Backtest & Statistical Significance**: Walk-forward validation & Model G control
- [x] **M8 — Telegram Interface**: Interactive command bot (`/health`, `/prediction`, `/market`, `/status`) & daily alert notifications
- [x] **M9 — Cloud Deployment**: Production Docker stack (`postgres`, `migrate`, `agent`, `bot`, `dashboard`), backup engine & scheduler
- [x] **M10 — Paper Trading**: Forward position tracker & Section 35 quantitative go/no-go gates
- [x] **M-Dashboard — Streamlit Monitoring Dashboard**: Live web dashboard for pipeline freshness, Section 35 gates, Max/Min signals & cumulative PnL

---

## Quick Navigation

1. [Local Development Setup](#local-development-setup-mac--linux--windows)
2. [Streamlit Monitoring Dashboard (M-Dashboard)](#streamlit-monitoring-dashboard-m-dashboard)
3. [Google Cloud Platform (GCP) Deployment](#google-cloud-platform-gcp-deployment)
4. [Development & Feature Update Workflow](#-development--feature-update-workflow)
5. [Running Individual Jobs & Schedulers](#running-individual-jobs)
6. [Telegram Bot Integration](#telegram-bot-setup)
7. [Configuration Reference](#configuration-reference)
8. [Make Commands Reference](#make-commands-reference)

---

## Local Development Setup (Mac / Linux / Windows)

### 1. Prerequisites
- **Docker Desktop**: [Install Docker Desktop](https://www.docker.com/products/docker-desktop)
- **Python 3.13+**

### 2. Setup Virtual Environment
```bash
cd weather-forecast

# Create virtual environment and install dependencies
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Start Database & Run Migrations
```bash
# Start PostgreSQL container
make up

# Apply Alembic database migrations (creates all 10 tables)
make migrate

# Run tests to verify setup (79 tests passing)
make test
```

### 4. Run Full Prediction Cycle Locally
```bash
source .venv/bin/activate
python -m app.jobs.scheduler
```

---

## Streamlit Monitoring Dashboard (M-Dashboard)

The system includes an interactive, web-based monitoring dashboard built with **Streamlit** (`app/dashboard/main.py`). The dashboard operates in **read-only mode**, querying the active PostgreSQL database to provide real-time visibility into data freshness, predictions, market prices, and risk controls.

### Launching the Dashboard

```bash
# Start the Streamlit dashboard
make dashboard
# or: streamlit run app/dashboard/main.py
```
Open **`http://localhost:8501`** in your web browser.

### Seeding Demo Data (Optional for Visualization)

If you want to instantly preview full historical charts, backtests, and dual-market predictions (Highest & Lowest Temp):

```bash
# Seed demo prediction markets & paper trade history
make seed
# or: python scripts/seed_demo_data.py
```
After running, click **🔄 Refresh Data** in the dashboard sidebar.

---

### Dashboard Modules Breakdown

```
┌────────────────────────────────────────────────────────────────────────┐
│               ⛅ HK Weather Prediction Market Dashboard                │
├────────────────────────────────────────────────────────────────────────┤
│ 1. 📡 Ingestion Pipeline Freshness (HKO, Polymarket, ML Model Status)  │
├────────────────────────────────────────────────────────────────────────┤
│ 2. 💡 Tactical Diurnal Peak & Timing Insights (Best Entry Hours WIB)   │
├────────────────────────────────────────────────────────────────────────┤
│ 3. 🛡️ Section 35 Quantitative Go/No-Go Gates (5 Visual KPIs & Verdict) │
├────────────────────────────────────────────────────────────────────────┤
│ 4. 🎯 Latest Predictions & Signals (Filter by Highest/Lowest Temp)    │
├────────────────────────────────────────────────────────────────────────┤
│ 5. 📈 Polymarket Price vs Model Probability Chart (Market Selector)    │
├────────────────────────────────────────────────────────────────────────┤
│ 6. 💼 Paper Trading Performance & Cumulative PnL Curve                 │
└────────────────────────────────────────────────────────────────────────┘
```

#### 1. Ingestion Pipeline Freshness
* **HKO Observations**: Displays the timestamp and age of the latest real-time weather observations from the 27 official HKO stations (`🟢 FRESH` if $< 2$ hours old, `🔴 STALE` otherwise).
* **HKO 9-Day Forecast**: Shows the freshness of the latest official 9-day minimum/maximum temperature forecasts.
* **Polymarket Markets & Prices**: Tracks when active Polymarket weather contracts and token prices were last synchronized.
* **ML Predictions**: Displays when the model last generated probability distributions.

#### 2. Tactical Diurnal Peak & Timing Insights
* Identifies daily peak temperature windows (13:00–15:00 HKT / 12:00–14:00 WIB) and minimum temperature windows (05:00–07:00 HKT / 04:00–06:00 WIB).
* Highlights the recommended entry window before Polymarket order books adjust.

#### 3. Section 35 Quantitative Go/No-Go Gates
Evaluates whether the trading system meets the 5 strict numeric gates defined in **PLAN.md Section 35 & 23** before any live experiment:
* **Gate 1 (Sample Size)**: Minimum $\ge 50$ resolved trades required (`❌ FAILED` if $N < 50$, `✅ PASSED` if $N \ge 50$).
* **Gate 2 (Positive ROI)**: Net ROI after all execution fees and slippage $> 0\%$.
* **Gate 3 (Significance)**: Permutation test versus Model G random control ($p < 0.05$).
* **Gate 4 (Calibration)**: Expected Calibration Error (ECE) $< 0.05$.
* **Gate 5 (Weather Baseline)**: ML Model Brier Score $\le$ HKO Official Forecast Brier Score.
* **Overall Verdict Banner**: `READY_FOR_LIVE_EXPERIMENT`, `CONTINUE_PAPER_TRADING`, or `REJECT_STRATEGY`.

#### 4. Latest Predictions & Trading Signals
* Supports both **Highest Temperature (`🔥 Max Temp`)** and **Lowest Temperature (`❄️ Min Temp`)** markets.
* Filter by **Market Type** (`ALL`, `🔥 Highest Temp`, `❄️ Lowest Temp`) and **Decision** (`ALL`, `BUY`, `HOLD`).
* Columns: `Timestamp`, `Type`, `Market Question`, `Target Date`, `Outcome`, `Model Probability`, `Market Price`, `Gross Edge`, `Net EV`, `Decision` (`BUY`/`HOLD`), `Recommended Size`, and `Model Version`.

#### 5. Polymarket Price vs Model Probability Chart
* Interactive **Market Selector**: Choose any active Highest or Lowest Temperature market to plot.
* Select any outcome bucket from the dropdown to visualize the historical time-series of Polymarket market prices versus the model's estimated fair probability.

#### 6. Paper Trading Performance & Cumulative PnL
* **Key Metrics**: Total Trades, Resolved Trades, Win Rate (%), and Cumulative Net PnL ($).
* **Cumulative PnL Chart**: Visualizes portfolio growth and drawdown over time.
* **Trade Log**: Complete table of executed paper orders with entry prices, slippage, fees, status (`OPEN` / `CLOSED`), and realized PnL.

---

## Google Cloud Platform (GCP) Deployment

Deploying to GCP Compute Engine allows the system to run **24/7 in the cloud**, automatically collecting HKO weather data and Polymarket prices, executing predictions, and sending morning Telegram summaries on schedule.

### Step 1: Create a Compute Engine VM on GCP

1. Open [GCP Console → Compute Engine → VM instances](https://console.cloud.google.com/compute/instances).
2. Click **Create Instance**:
   - **Name**: `weather-forecast-agent`
   - **Region / Zone**: Choose closest region (e.g. `asia-east2` Hong Kong or `asia-southeast1` Singapore).
   - **Machine configuration**: `General-purpose` → Series `E2` → Machine type: `e2-small` (2 vCPU, 2 GB RAM) or `e2-micro` (Free Tier eligible).
   - **Boot disk**: Ubuntu 22.04 LTS or Debian 12 (20 GB Standard Persistent Disk).
   - **Identity and API access**: Allow default service account.
   - **Firewall**: Allow HTTP/HTTPS traffic (optional).
3. Click **Create**.

---

### Step 2: Connect to VM & Install Docker

Click the **SSH** button next to your VM instance on GCP Console, then run:

```bash
# 1. Update packages
sudo apt-get update && sudo apt-get upgrade -y

# 2. Install Docker and Docker Compose Plugin
sudo apt-get install -y docker.io docker-compose-v2 git

# 3. Add current user to docker group (avoid sudo for docker commands)
sudo usermod -aG docker $USER
newgrp docker
```

---

### Step 3: Clone Repository & Configure Environment

```bash
# 1. Clone your repository
git clone https://github.com/KharismadinaHM/weather_forecast.git
cd weather_forecast

# 2. Create production environment file
cp .env.example .env

# 3. Edit .env with your secrets
nano .env
```

Set the following production values in `.env`:
```env
ENVIRONMENT=production
LOG_LEVEL=INFO

# Strong password for production PostgreSQL
POSTGRES_USER=hkw
POSTGRES_PASSWORD=YOUR_STRONG_SECURE_PASSWORD
POSTGRES_DB=hk_weather
DATABASE_URL=postgresql+psycopg://hkw:YOUR_STRONG_SECURE_PASSWORD@db:5432/hk_weather

# Telegram Bot Credentials
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=YOUR_TELEGRAM_CHAT_ID
```
*(Press `Ctrl + O` then `Enter` to save, and `Ctrl + X` to exit nano)*.

---

### Step 4: Launch Production Containers

Run using Docker Compose:

```bash
# Build and start all production services in the background
docker compose -f docker-compose.prod.yml up -d --build

# Verify running containers (all 4 services should be healthy/running)
docker compose -f docker-compose.prod.yml ps
```

The production stack starts:
1. **`hk_weather_postgres_prod`**: Production PostgreSQL 16 database with persisted volume.
2. **`hk_weather_migrate_prod`**: Automatic Alembic schema migration runner.
3. **`hk_weather_agent_prod`**: Continuous 15-minute scheduler daemon for HKO observations & Polymarket predictions.
4. **`hk_weather_bot_prod`**: Interactive Telegram command bot listener (`/health`, `/prediction`, `/status`, `/market`).
5. **`hk_weather_dashboard_prod`**: Streamlit Web Monitoring Dashboard accessible on port `8501`.

```bash
# View live logs of any service
docker compose -f docker-compose.prod.yml logs -f agent
docker compose -f docker-compose.prod.yml logs -f bot
docker compose -f docker-compose.prod.yml logs -f dashboard
```

---

### Step 5: Setup Automated Backup Cron on GCP

To automatically backup the database daily at 03:00 UTC and rotate old backups:

```bash
# Make backup script executable
chmod +x scripts/backup.sh

# Add to crontab
(crontab -l 2>/dev/null; echo "0 3 * * * cd /home/$USER/weather_forecast && ./scripts/backup.sh >> /var/log/db_backup.log 2>&1") | crontab -
```

---

### Managing the GCP Deployment

```bash
# View live logs
docker compose -f docker-compose.prod.yml logs -f --tail=100

# Stop all services
docker compose -f docker-compose.prod.yml down
```

---

## 🔄 Development & Feature Update Workflow

How to develop new features using **Antigravity IDE** locally and seamlessly update your active **GCP Server**:

```
┌─────────────────────────┐         ┌─────────────────────────┐         ┌─────────────────────────┐
│   1. Antigravity IDE    │ ──────> │    2. GitHub Remote     │ ──────> │    3. GCP Cloud Server  │
│   (Local Development)   │ git push│ (github.com/.../repo)   │ git pull│   (24/7 Live Production)│
└─────────────────────────┘         └─────────────────────────┘         └─────────────────────────┘
```

### Step 1: Develop & Test in Antigravity (Local Machine)
1. Request new features, indicators, or adjustments directly in Antigravity IDE.
2. Antigravity writes the code, verifies with unit tests (`make test`), and commits & pushes to GitHub:
   ```bash
   git push origin main
   ```

### Step 2: Deploy Updates to GCP Server (1-Click Command)
In your GCP VM terminal (SSH), pull the latest update and rebuild containers:

```bash
cd weather_forecast
git pull origin main
docker compose -f docker-compose.prod.yml up -d --build
```
*(Or simply run `./scripts/deploy.sh`)*

**What the update automatically does:**
1. Pulls the latest code from GitHub.
2. Runs database migrations automatically if new tables or columns were added.
3. Rebuilds and restarts the container stack with zero manual configuration.
4. Preserves all historical database records in Docker volume (`postgres_prod_data`).

> 🛡️ **Data Safety Guarantee**: All database records (historical observations, predictions, paper trades, PnL) are preserved across updates because PostgreSQL stores its data in the isolated Docker volume (`postgres_prod_data`).


---

## Running Individual Jobs

```bash
source .venv/bin/activate

# 1. Collect HKO observations only
python -c "from app.jobs.hko_jobs import run_hko_observations_job; print(run_hko_observations_job())"

# 2. Collect HKO 9-day forecast only
python -c "from app.jobs.hko_jobs import run_hko_forecast_job; print(run_hko_forecast_job())"

# 3. Discover Polymarket markets + ingest prices
python -c "from app.jobs.polymarket_jobs import run_polymarket_discovery_and_prices_job; print(run_polymarket_discovery_and_prices_job())"

# 4. Run system health check
python -c "from app.jobs.health import run_health_check_job; import json; print(json.dumps(run_health_check_job(), indent=2))"
```

---

## Telegram Bot Setup & Local Testing

You can interact and chat with the bot in real-time right from your local machine before deploying to GCP:

### Step 1: Initialize Chat with Your Bot
> ⚠️ **IMPORTANT**: In Telegram, a bot cannot message you first until you initiate the conversation.
1. Open your Telegram app and search for your bot username (from [@BotFather](https://t.me/BotFather)).
2. Click **Start** (or send `/start`).

### Step 2: Test Message Connection
Verify that your credentials in `.env` are working:
```bash
# Send a test greeting message to your Telegram
make test-telegram
```

### Step 3: Start Interactive Bot Listener Locally
Run the interactive listener to chat and send commands to the bot:
```bash
# Start bot listener (responds to /today, /status, etc.)
make bot
```

---

### Available Telegram Commands

| Command | Description |
| :--- | :--- |
| `/today` | Today's official HKO weather observation & max/min temperature forecast |
| `/prediction` | Latest ML model probability distribution, gross edge & net EV |
| `/market` | Active Polymarket weather contracts & current market prices |
| `/performance` | Paper trading strategy PnL, Win Rate %, and total trades |
| `/positions` | Current open paper trade positions & risk allocation |
| `/model` | Active ML model metadata, Brier score & validation status |
| `/status` | System runtime state, environment, and pipeline status |
| `/health` | Database latency, freshness checks & data quality status |
| `/pause` | 🚨 **Kill Switch**: Immediately halts trade signal generation |
| `/resume` | Deactivates kill switch and resumes active strategy evaluation |
| `/help` | Display list of all available commands |


---

## Configuration Reference

Edit `.env` to configure the system:

```env
# Environment ('development' or 'production')
ENVIRONMENT=development
LOG_LEVEL=INFO

# PostgreSQL Database (use 5433 for local Docker to avoid port conflicts)
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_DB=hk_weather
POSTGRES_USER=hkw
POSTGRES_PASSWORD=hkw_secret_pass
DATABASE_URL=postgresql+psycopg://hkw:hkw_secret_pass@localhost:5433/hk_weather

# HKO Open Data API (public endpoint)
HKO_BASE_URL=https://data.weather.gov.hk/weatherAPI/opendata/weather.php

# Polymarket APIs (public endpoints)
POLYMARKET_GAMMA_URL=https://gamma-api.polymarket.com
POLYMARKET_CLOB_URL=https://clob.polymarket.com

# Telegram Bot
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=YOUR_TELEGRAM_CHAT_ID
```

---

## Make Commands Reference

```bash
make help          # Show all available commands
make up            # Start PostgreSQL in Docker
make down          # Stop all containers
make logs          # Tail container logs
make migrate       # Run database migrations
make test          # Run full test suite (80 tests)
make lint          # Run ruff linting
make typecheck     # Run mypy type checking
make dashboard     # Launch Streamlit monitoring dashboard
make seed          # Seed realistic demo data into database
make bot           # Start interactive Telegram command bot
make test-telegram # Send a test message to verify Telegram credentials
make run           # Run 1 full orchestration cycle
make daemon        # Run continuous background scheduler loop
make shell-db      # Open psql shell in database
make clean         # Remove caches and build artifacts
```


---

## Project Structure

```
weather-forecast/
├── app/
│   ├── collectors/       # HKO & Polymarket data ingestion
│   ├── features/         # Feature engineering & dataset builder
│   ├── ml/               # LightGBM model, baselines & calibration
│   ├── trading/          # Edge/EV engine & risk controls
│   ├── backtest/         # Walk-forward backtest & significance testing
│   ├── telegram/         # Bot, formatter & Telegram client
│   ├── dashboard/        # Streamlit web monitoring dashboard & queries
│   ├── jobs/             # Scheduled jobs & orchestrator
│   ├── paper/            # Paper trading tracker & gate evaluator
│   └── storage/          # SQLAlchemy models, DB session & backup engine
├── tests/
│   ├── leakage/          # Anti-data-leakage test suite
│   └── unit/             # Unit tests (79 total)
├── docs/
│   ├── plan.md           # Full system architecture & rules
│   └── feasibility.md    # Feasibility research
├── migrations/           # Alembic database migrations
├── scripts/              # deploy.sh, backup.sh & seed_demo_data.py
├── docker-compose.yml         # Development (DB only)
├── docker-compose.prod.yml    # Production (DB + Agent)
├── Dockerfile
└── .env.example
```
