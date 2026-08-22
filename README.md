# Hong Kong Weather Prediction Market AI Agent

An end-to-end quantitative trading system that predicts probability distributions of Hong Kong daily maximum temperature, compares against Polymarket prediction market prices, and executes paper trading signals under strict risk controls.

---

## Milestone Status

- [x] **M0 — Feasibility Research**: Completed & approved (`docs/feasibility.md`)
- [x] **M1 — Infrastructure**: Python project scaffolding, Docker Compose, PostgreSQL schema (10 tables), logging & config
- [x] **M2 — HKO Collector**: Ingestion pipeline for HKO observations & forecasts with data-quality validation
- [x] **M3 — Polymarket Collector**: Market discovery & temperature bucket schema parser (Section 9.1)
- [x] **M4 — Dataset & Feature Pipeline**: Feature engineering & anti-leakage verification
- [x] **M5 — Weather ML Model**: Climatology / HKO baseline vs calibrated LightGBM model
- [x] **M6 — Trading Logic**: Edge/EV engine, fee/slippage models & risk controls
- [x] **M7 — Backtest & Statistical Significance**: Walk-forward validation & Model G control
- [x] **M8 — Telegram Interface**: Daily notifications & command bot
- [x] **M9 — Cloud Deployment**: Production Docker stack, backup engine & automated job scheduler
- [x] **M10 — Paper Trading**: Forward position tracker & Section 35 quantitative go/no-go gates

---

## Prerequisites

- **Docker Desktop** (for PostgreSQL): https://www.docker.com/products/docker-desktop
- **Python 3.13+**: https://www.python.org/downloads/
- **uv** (package manager, recommended) or `pip`

---

## Quick Start (Local Development)

### 1. Clone & Install Dependencies

```bash
cd /Users/kharismadinahijram/Downloads/weather-forecast

# Create a virtual environment and install all dependencies
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure Environment

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your values (see Configuration section below)
# Minimum required: leave defaults as-is for local development
# Optional: add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID for Telegram alerts
```

### 3. Start the Database

```bash
# Start PostgreSQL in Docker (runs in background)
make up

# Apply database migrations (create all 10 tables)
make migrate
```

### 4. Run All Tests (verify everything works)

```bash
make test
# Expected: 75 passed in ~5s
```

---

## Running the Agent (1 Full Cycle)

Run all pipelines once — HKO collection, Polymarket discovery, ML prediction, health check:

```bash
source .venv/bin/activate
python -m app.jobs.scheduler
```

**What this does (in order):**
1. 🌡️ **Fetches live HKO observations** from Hong Kong Observatory Open Data API
2. 🌤️ **Fetches 9-day HKO forecast** with daily max temperature predictions
3. 📊 **Discovers active Polymarket markets** for HK weather (via Gamma API)
4. 📈 **Ingests current token prices** for each market outcome bucket
5. 🤖 **Runs ML prediction cycle** — evaluates each active market against model probabilities
6. ⚖️ **Risk Engine evaluation** — calculates Edge, EV, checks risk limits
7. ✅ **System health check** — reports database latency and data freshness

---

## Running Individual Jobs

```bash
source .venv/bin/activate

# Collect HKO observations only
python -c "from app.jobs.hko_jobs import run_hko_observations_job; print(run_hko_observations_job())"

# Collect HKO 9-day forecast only
python -c "from app.jobs.hko_jobs import run_hko_forecast_job; print(run_hko_forecast_job())"

# Discover Polymarket markets + ingest prices
python -c "from app.jobs.polymarket_jobs import run_polymarket_discovery_and_prices_job; print(run_polymarket_discovery_and_prices_job())"

# System health check
python -c "from app.jobs.health import run_health_check_job; import json; print(json.dumps(run_health_check_job(), indent=2))"
```

---

## Telegram Bot Setup (Optional)

To receive daily summaries and trading alerts on your phone:

1. **Create a Telegram bot**: Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → copy the token
2. **Get your Chat ID**: Message [@userinfobot](https://t.me/userinfobot) → copy the ID
3. **Add to `.env`**:

```env
TELEGRAM_BOT_TOKEN=123456:ABC-your-token-here
TELEGRAM_CHAT_ID=-100your-chat-id
```

4. **Start the Telegram command bot** (responds to `/status`, `/today`, `/pause`, etc.):

```bash
source .venv/bin/activate
python -c "
import asyncio
from app.telegram.bot import TelegramCommandHandler
handler = TelegramCommandHandler()
asyncio.run(handler.start_polling())
"
```

**Available bot commands:**
| Command | Description |
| :--- | :--- |
| `/status` | System health and scheduler status |
| `/today` | Today's model prediction & market prices |
| `/market <id>` | Details for a specific Polymarket market |
| `/positions` | Open paper trade positions |
| `/performance` | Strategy PnL summary |
| `/model` | Current ML model metadata |
| `/health` | Database latency & data freshness |
| `/pause` | Activate kill switch (stop generating signals) |
| `/resume` | Deactivate kill switch |
| `/help` | List all commands |

---

## Production Deployment (Docker)

For running continuously (e.g. on a cloud VM or Mac server):

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# Build and start production stack (PostgreSQL + Agent worker)
docker compose -f docker-compose.prod.yml up -d

# View live logs
docker compose -f docker-compose.prod.yml logs -f agent

# Stop
docker compose -f docker-compose.prod.yml down
```

---

## Configuration Reference

Edit `.env` to configure the system:

```env
# Environment ('development' or 'production')
ENVIRONMENT=development
LOG_LEVEL=INFO

# PostgreSQL Database
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=hk_weather
POSTGRES_USER=hkw
POSTGRES_PASSWORD=change_me
DATABASE_URL=postgresql+psycopg://hkw:change_me@localhost:5432/hk_weather

# HKO Open Data API (no key needed — public API)
HKO_BASE_URL=https://data.weather.gov.hk/weatherAPI/opendata/weather.php

# Polymarket APIs (no key needed — public API)
POLYMARKET_GAMMA_URL=https://gamma-api.polymarket.com
POLYMARKET_CLOB_URL=https://clob.polymarket.com

# Telegram (optional — leave empty to log locally instead)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

---

## All Make Commands

```bash
make help        # Show all available commands
make up          # Start PostgreSQL in Docker
make down        # Stop all containers
make logs        # Tail container logs
make migrate     # Run database migrations
make test        # Run full test suite (75 tests)
make lint        # Run ruff linting
make typecheck   # Run mypy type checking
make shell-db    # Open psql shell in database
make clean       # Remove caches and build artifacts
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
│   ├── jobs/             # Scheduled jobs & orchestrator
│   ├── paper/            # Paper trading tracker & gate evaluator
│   └── storage/          # SQLAlchemy models, DB session & backup engine
├── tests/
│   ├── leakage/          # Anti-data-leakage test suite
│   └── unit/             # Unit tests (75 total)
├── docs/
│   ├── plan.md           # Full system architecture & rules
│   └── feasibility.md    # Feasibility research
├── migrations/           # Alembic database migrations
├── scripts/              # deploy.sh & backup.sh
├── docker-compose.yml         # Development (DB only)
├── docker-compose.prod.yml    # Production (DB + Agent)
├── Dockerfile
└── .env.example
```
