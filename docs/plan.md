# Hong Kong Weather Prediction Market AI Agent --- PLAN (Revised)

## 0. Feasibility Research (Day 0 --- MUST complete before any build)

This is a new phase inserted before all other work. The original plan
built 34 sections of architecture before validating whether the core
business premise is even possible. That is backwards. Nothing in
Section 1 onward should start until this phase produces a written
go/no-go answer.

Answer these questions manually (via API exploration / browser),
write the findings into `docs/feasibility.md`, and treat unresolved
items as blockers:

```text
Q1. Does Polymarket expose historical price time-series for CLOSED /
    resolved markets via API, or only for currently active markets?
    → This determines whether Section 6's "collect complete history"
      is realistic, or whether the project must run in
      collect-forward-only mode (i.e. data only starts accumulating
      from the day this system goes live).

Q2. How many Hong Kong weather markets has Polymarket listed in the
    last 90 days? What is typical volume and bid/ask spread?
    → If markets are rare or illiquid, the whole trading-signal
      premise may not be viable regardless of model quality.

Q3. What is HKO's actual forecast publish cadence?
    (hourly nowcast vs 3-hourly vs twice-daily 9-day forecast)
    → Determines real polling frequency; do not assume "every hour"
      by default.

Q4. What does Polymarket's resolution source actually reference?
    Which station, which measurement window, which rounding rule?
    → Must match (or be reconcilable with) the HKO station chosen as
      ground truth in Section 5.1.

Q5. Does Polymarket's Terms of Service permit automated
    trading/API access from Hong Kong? Any jurisdictional
    restriction relevant to the operator?
```

**Go/No-Go rule:** if Q1 shows no historical price access AND Q2
shows markets appear less than ~2x/month with thin volume, stop and
reconsider the project before writing any collector code.

------------------------------------------------------------------------

## 1. Goal

Build an end-to-end system that predicts the probability distribution
of Hong Kong daily HIGH/LOW temperatures, compares those probabilities
with Polymarket prices, calculates net edge/expected value, applies
deterministic risk rules, and sends signals/summaries to Telegram.

The system must start in **paper/signal mode**. Real-money execution is
a later phase, gated by quantitative criteria (see Section 35).

Core principle:

> Weather model predicts probability. Market data provides price. Risk
> engine decides whether the opportunity is tradable. LLM
> explains/orchestrates; it does not directly decide or bypass risk
> controls.

Real objective, restated precisely:

> Estimate the probability better than the market, prove that edge is
> statistically real (not sample noise), and determine whether the
> difference is large enough to justify risk after fees, slippage,
> liquidity and uncertainty.

------------------------------------------------------------------------

## 2. Architecture

```text
HKO Open Data ───────┐
                     ├──> Collectors ──> PostgreSQL ──> Feature Pipeline
Polymarket APIs ─────┘                                      │
                                                           ▼
                                                   Weather ML Model
                                                           │
                                                           ▼
                                                   Probability
                                                           │
Polymarket prices ─────────────────────────────────────────┤
                                                           ▼
                                                    Edge / EV Engine
                                                           │
                                                           ▼
                                                     Risk Engine
                                                           │
                                      ┌────────────────────┴──────────────┐
                                      ▼                                   ▼
                                  Telegram                         Paper Trading
                                      │                                   │
                                      └──────────────────┬────────────────┘
                                                         ▼
                                                     Analytics
                                                         │
                                                         ▼
                                                     Retraining
```

------------------------------------------------------------------------

## 3. Infrastructure

Infra cost is treated as a non-constraint for this revision, but
complexity is still kept minimal to reduce operational risk and
development time, not money.

Start with:

- 1 Compute Engine VM (or local machine during Day 0--M3)
- Docker Compose
- PostgreSQL
- Object storage for raw data / model artifacts
- Secret Manager
- Logging/Monitoring
- Telegram Bot
- cron or systemd timers

Avoid initially: Kubernetes, Kafka, GPU, microservices, managed ML
endpoints, Airflow, Redis. Scale only when a specific, observed
bottleneck justifies it — not preemptively.

------------------------------------------------------------------------

## 4. Repository Structure

```text
hongkong-weather-agent/
├── README.md
├── PLAN.md
├── docs/
│   └── feasibility.md
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── Makefile
├── app/
│   ├── config/
│   ├── collectors/
│   │   ├── hko.py
│   │   └── polymarket.py
│   ├── storage/
│   ├── features/
│   ├── ml/
│   │   ├── train.py
│   │   ├── predict.py
│   │   ├── calibrate.py
│   │   └── evaluate.py
│   ├── market/
│   │   ├── probability.py
│   │   ├── edge.py
│   │   └── ev.py
│   ├── risk/
│   ├── agent/
│   ├── notifications/
│   │   └── telegram.py
│   └── jobs/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── leakage/          # NEW: dedicated leakage test suite
│   └── backtest/
├── notebooks/
└── infra/
    ├── docker/
    ├── systemd/
    └── gcp/
```

------------------------------------------------------------------------

## 5. Data Sources

### 5.1 HKO

Collect, where available:

- hourly temperature
- daily maximum/minimum
- humidity, rainfall, pressure, wind, weather conditions
- forecasts and forecast revisions

**Authoritative station rule (new):** designate exactly ONE HKO
station as ground truth (default candidate: HK Observatory
Headquarters, since this is what official reports and most
third-party resolution sources reference). Store data from other
stations too, but mark them as `is_authoritative = false` and treat
them only as optional supplementary features, never as the training
target. This choice must be re-verified against Section 5.1's Q4
finding — the authoritative station used for training MUST match
whatever Polymarket's resolution source actually references.

**Forecast polling frequency (revised):** do not assume hourly
polling by default. Set the collector's polling interval to match the
*actual* publish cadence discovered in Feasibility Q3 (e.g. if HKO
only updates the 9-day forecast twice a day, polling hourly wastes
22/24 calls on identical data). Nowcast/short-range products may
justify more frequent polling — confirm per product, not globally.

Use HKO observations from the authoritative station as ground truth
for evaluation.

### 5.2 Polymarket

Discover and collect Hong Kong weather markets dynamically — do not
hard-code a market ID.

**Discovery reliability (new):** run market discovery at the same
frequency as price collection (e.g. every 15 min), not as a separate
slow job. If HK weather markets are normally created daily, alert via
Telegram when no new market for the next target date is found by a
defined cutoff time (e.g. by 18:00 HKT the day before) — this
prevents silently missing a day's market due to a discovery gap.

**Question/schema drift (new):** Polymarket market question formats
can change over time (e.g. different temperature bucket widths,
different phrasing). Build an explicit parser/normalizer with test
cases per known format variant, and flag any market whose question
text does not match a known pattern for manual review instead of
silently mis-parsing it.

Store:

- event ID, market ID, slug, question
- outcome/token IDs, outcome labels (as literal bucket ranges, e.g.
  "31--32°C", not just a label string)
- target date, market start/end
- resolution source (verbatim link/text, not paraphrased)
- status, price history, volume, liquidity, bid/ask when available

Do not assume multi-year Polymarket history exists — this must be
measured, not assumed (see Feasibility Q1/Q2).

------------------------------------------------------------------------

## 6. Historical Data Plan

### HKO

Target 5--8 years if available and consistent, from the single
authoritative station. Keep raw API responses in object storage so
the dataset can be rebuilt.

### Polymarket

Collect whatever historical market data the API actually exposes
(determined in Feasibility Q1). Two realistic scenarios, planned for
explicitly instead of assumed:

```text
Scenario A: API exposes historical prices for closed markets
  → build historical dataset immediately, backtest can start once
    enough resolved markets exist.

Scenario B: API only exposes active/current markets
  → switch to collect-forward-only mode. Historical trading-strategy
    backtesting is not possible until the system has been running
    live (in signal mode) for enough weeks/months to accumulate its
    own price history. Milestone M6 (Backtest) must be re-scoped
    accordingly — see Section 30.
```

The two datasets serve different purposes and must not be conflated:

- HKO = weather ground truth/features (can have years of history)
- Polymarket = market belief/price/microstructure (may only have a
  short history — this bounds statistical power of any trading
  backtest, see Section 20a)

Do not treat Polymarket prices as weather ground truth.

------------------------------------------------------------------------

## 7. Database Schema

*(unchanged from original, with additions marked NEW)*

### weather_observations

```text
id, observed_at, station, is_authoritative (NEW),
temperature, humidity, rainfall, pressure,
wind_speed, wind_direction, weather_condition,
source, ingested_at
```

### weather_daily

```text
date, station, max_temperature, min_temperature, mean_temperature,
total_rainfall, created_at
```

### weather_forecasts

```text
id, forecast_created_at, target_date, target_hour,
forecast_temperature, forecast_min_temperature, forecast_max_temperature,
humidity, rain_probability, wind, source, ingested_at
```

### polymarket_markets

```text
market_id, event_id, slug, question, market_type,
outcome_bucket_schema (NEW: raw bucket definitions as parsed),
target_date, metric, status, resolution_source_raw (NEW: verbatim text),
start_time, end_time, created_at, updated_at
```

### polymarket_outcomes

```text
market_id, token_id, outcome_label, outcome_bucket_low (NEW),
outcome_bucket_high (NEW), outcome_value
```

### polymarket_prices

```text
id, market_id, token_id, timestamp, price, side, volume, ingested_at
```

### predictions

```text
id, market_id, prediction_timestamp, model_version,
outcome, model_probability, market_probability,
edge, expected_value, confidence
```

### signals

```text
id, prediction_id, decision, reason,
recommended_price, recommended_size, risk_limit, created_at
```

### paper_trades

```text
id, signal_id, entry_price, position_size, exit_price,
pnl, fees, slippage, status, opened_at, closed_at
```

### model_runs

```text
model_version, training_start, training_end,
validation_start, validation_end, test_start, test_end,
brier_score, log_loss, calibration_error, mae, rmse, created_at
```

------------------------------------------------------------------------

## 8. Critical Data-Leakage Rule

Every prediction must use only information available at the decision
timestamp.

```text
Prediction timestamp: 2026-08-22 08:00

Allowed:
- HKO data before 08:00
- HKO forecast available before 08:00
- Polymarket prices before 08:00
- historical observations

Forbidden:
- actual 2026-08-22 temperature
- later forecast revisions
- later market prices
```

Keep both `forecast_created_at` and `target_date`. Do not overwrite
forecast history.

**Derived-feature leakage (new):** features derived from forecasts —
e.g. "revision count", "revision delta since yesterday" — are easy to
leak by mis-indexing even when the raw rule above is respected. Add
dedicated unit tests in `tests/leakage/` for every derived feature,
not just for raw timestamp fields.

------------------------------------------------------------------------

## 9. ML Strategy

Do not start with an LLM or deep learning.

### 9.1 Output architecture decision (must be made BEFORE any modeling)

The original plan asked for a per-integer-degree probability
distribution without specifying how to produce it. This is an
architectural decision, not an implementation detail, and it depends
entirely on how Polymarket actually buckets outcomes (see Section
5.2's outcome_bucket fields). Resolve in this order:

```text
1. Inspect real Polymarket HK weather markets' outcome buckets
   (e.g. "≤30°C", "31°C", "32°C", "33°C", "≥34°C" — width may vary).
2. Design the model to predict probability mass natively over those
   buckets — do NOT build a fine-grained per-degree distribution and
   manually re-aggregate at prediction time unless bucket widths are
   confirmed to always be 1°C.
3. Choose one of:
   a. Multinomial classification over the observed bucket set
      (simplest, but buckets may change between markets — needs
      re-mapping logic).
   b. Continuous regression (e.g. predict max temp + residual
      distribution assumed Gaussian or empirical) then integrate over
      whatever bucket a given market defines — most robust to bucket
      schema changes, recommended default.
   c. Quantile regression, converted to a CDF, then differenced per
      bucket — good middle ground, more complex to calibrate.
Recommended default: (b), because it decouples model training from
Polymarket's bucket schema, which may change over time (Section 5.2).
```

### 9.2 Baselines

Build these first, in this priority order:

```text
1. climatology
2. HKO official forecast          <- the ONE baseline that actually
                                       matters for go/no-go (see 9.3)
3. persistence (weak baseline, expect it to lose to climatology —
   keep only as a sanity check, not a serious competitor)
4. logistic/multinomial regression
5. LightGBM
```

### 9.3 Go/No-Go on model quality

**The single most important comparison in this project is: does the
custom ML model beat HKO's own official forecast?** If it does not,
the project has no edge to offer over what the market can already see
for free, and should stop here regardless of how good the ML pipeline
looks on paper. This check must happen before Section 12 (Edge/EV) is
built out, not after.

### 9.4 Potential features

```text
month, day_of_year, hour
temperature lags, rolling temperatures (7-day, 30-day)
humidity, pressure, rainfall, wind
previous-day max/min
HKO forecast + forecast revision (leakage-tested, see Section 8)
seasonal climatology
```

------------------------------------------------------------------------

## 10. Calibration

Evaluate: Brier score, log loss, reliability diagram, expected
calibration error.

Try: Platt scaling, isotonic regression, or other appropriate
technique — chosen via time-based validation, not random split.

------------------------------------------------------------------------

## 11. Market Probability

For a binary $1-settlement outcome, price ≈ market-implied
probability, but execution logic must consider bid/ask spread,
liquidity, fees, slippage, stale prices, and market status. Do not
treat a displayed price as a guaranteed executable price.

------------------------------------------------------------------------

## 12. Edge and Expected Value

```text
edge = model_probability - market_probability

EV = model_probability - effective_entry_price - fees - estimated_slippage
```

Trade only when net EV exceeds a tested threshold:

```text
MIN_EDGE = 0.08     (starting point, must be optimized out-of-sample)
MIN_NET_EV = 0.05   (starting point, must be optimized out-of-sample)
```

These are research parameters, not assumed-optimal defaults.

------------------------------------------------------------------------

## 13. Risk Engine

Initial research bankroll: $15 (kept small deliberately, independent
of infra cost — this bounds real-money risk, not compute risk).

```text
MAX_TRADE = $1
MAX_DAILY_RISK = $2
MAX_OPEN_POSITIONS = 2
```

Also implement: kill switch, daily loss limit, max market exposure,
stale-data protection, liquidity minimum, API-health protection.

```text
LLM suggestion → Risk Engine → ALLOW / DENY
```

The risk engine has final authority. The LLM can never override it.

------------------------------------------------------------------------

## 14. Telegram

### Daily summary (example)

```text
🌡️ HONG KONG WEATHER AI
Date: 2026-08-22
Model distribution (bucket-aligned to live market):
31°C 12%  32°C 43%  33°C 36%  34°C 9%
Best opportunity: 32°C
Model: 43%  Market: 31%  Gross edge: +12%  Net EV: +8%
Decision: 🟢 BUY   Risk allocation: $1
Model: weather-v003
```

### Commands

```text
/status /today /market /prediction /performance
/model /positions /health /pause /resume
```

`/pause` must disable execution/signal generation immediately.

------------------------------------------------------------------------

## 15. Scheduling

Do not hard-code frequencies before Feasibility Q3 is answered.
Template (fill actual numbers after Day 0):

```text
Every 15 min  → Polymarket prices + market discovery (combined)
Per HKO's actual publish cadence → HKO observations
Per HKO's actual publish cadence → HKO forecasts
Every 1 hour  → generate prediction
Every 15 min  → evaluate signal
07:00 HKT     → daily Telegram summary
By 18:00 HKT (day before target date) → alert if no market found (NEW)
00:00         → data-quality check
03:00         → database backup
Weekly/monthly → model candidate training (see Section 21)
```

Store timestamps in UTC; convert to HKT only for display/scheduling.

------------------------------------------------------------------------

## 16. Reliability

Every API client: timeout, retry with exponential backoff, rate-limit
handling, idempotency, duplicate detection, structured logging.

```text
API timeout → retry 5s → retry 15s → retry 60s → mark failed → Telegram alert
```

Never create duplicate records because a scheduled job ran twice.

------------------------------------------------------------------------

## 17. Data Quality

### HKO
Valid timestamps, plausible temperatures, duplicate records, missing
intervals, schema changes, **station consistency (NEW: reject/flag
records where station ≠ registered authoritative station without
explicit non-authoritative tagging)**.

### Polymarket
Valid market, complete outcomes, price in [0,1], fresh timestamps,
market status, resolution source present, sufficient liquidity,
**bucket schema matches a known parser pattern (NEW, see 5.2)**.

### Model
No NaN, probabilities sum to 1 (or integrate to 1 over buckets),
valid model version, feature schema matches training, calibration
artifact exists.

If checks fail, decision must be `SKIP`.

------------------------------------------------------------------------

## 18. Backtesting

```text
historical timestamp → load available information → generate prediction
  → load market price at that time → calculate edge/EV
  → apply risk rules → simulate order → wait for resolution → calculate PnL
```

Do not use the final market price as entry price unless the strategy
really entered at that time.

Evaluate: ROI, net PnL, max drawdown, win rate, average edge, average
EV, fees, slippage, number of trades.

**Sample size caveat (new):** if Scenario B from Section 6 applies
(no historical Polymarket prices), this section cannot run
meaningfully until enough live signal history accumulates. Do not
report backtest results computed on fewer than ~50 resolved trades —
label such results explicitly as "insufficient sample, directional
only."

------------------------------------------------------------------------

## 19. Walk-Forward Validation

Use time-based validation, not random train/test splitting.

```text
Train 2019–2022 → Test 2023
Train 2019–2023 → Test 2024
Train 2019–2024 → Test 2025
Train 2019–2025 → Paper/live 2026
```

Note: this cadence applies to the *weather model* only (long HKO
history available). The *trading strategy* backtest is separately
bounded by however much Polymarket price history actually exists
(see Section 6, Section 18 caveat) — do not conflate the two
timelines when reporting results.

------------------------------------------------------------------------

## 20. Model Comparison

```text
Model A: climatology
Model B: persistence
Model C: HKO official forecast      <- primary go/no-go competitor
Model D: ML
Model E: ML + forecast revisions
Model F: trading strategy using model + market
Model G: no-edge / random-trade control (NEW)
```

Report: MAE, RMSE, Brier, Log Loss, Calibration, ROI, Max Drawdown.

### 20a. Statistical significance (new)

Model G exists specifically to answer: is Model F's PnL distinguishable
from noise? Before declaring the strategy "profitable," run a
significance test (e.g. bootstrap confidence interval on ROI, or a
permutation test against Model G's trade outcomes) using the actual
trade sample size. With bankroll and market frequency this small, the
number of resolved trades in the first several months may be low
(tens, not hundreds) — treat any positive ROI on a small sample as
provisional, not conclusive.

------------------------------------------------------------------------

## 21. Retraining

Two separate cadences (revised — original conflated them):

```text
Weather model retraining:
  Monthly or bimonthly. HK seasonal temperature patterns are
  reasonably stationary at sub-monthly scale; weekly retraining adds
  compute and instability risk without clear benefit.

Trading strategy monitoring:
  Weekly review of live performance metrics (edge realized vs
  predicted, slippage vs modeled, market liquidity trends). This is
  where weekly cadence actually matters, because market
  microstructure (spread, liquidity, participant behavior) can shift
  faster than weather patterns.
```

Deploy a new model version only if it beats the current version on
out-of-sample metrics AND does not regress calibration.

Version models: `weather-v001`, `weather-v002`, ... Record training
period, features, hyperparameters, metrics, calibration method, git
commit, artifact path.

------------------------------------------------------------------------

## 22. AI Agent Layer

Add the LLM only after the deterministic pipeline (Sections 9-21)
already works end-to-end without it.

**Justify before building (new):** do not add an agent/orchestration
layer by default. Before implementing, name at least 2-3 concrete use
cases that a template-based Python script genuinely cannot do as well
— e.g. free-form anomaly investigation, answering ad-hoc
natural-language questions via Telegram. If the only use case is
"format the daily summary message," a plain string template is
sufficient and should be used instead; skip this layer entirely in
that case.

If built, tools the agent can call:

```text
get_latest_weather() / get_forecast() / get_market() / get_market_history()
get_model_prediction() / calculate_edge() / calculate_ev()
get_risk_status() / get_performance()
```

Do NOT use the LLM as the primary numerical temperature predictor.
Do NOT let the LLM call the order API directly.

------------------------------------------------------------------------

## 23. Paper Trading

Run at least 30--60 days, or longer if Scenario B (Section 6) applies
and the trade sample is still small after 60 days — extend until a
minimum of ~50 resolved trades is reached, whichever is later.

Record: market, outcome, entry price, model probability, market
probability, edge, EV, position size, result, fees, slippage, net PnL.

Compare against: no-trade baseline, HKO forecast, market-implied
probability alone (Model G), and a Telegram signal provider if
comparable data is available.

Only proceed to live trading if the strategy demonstrates positive
out-of-sample expectancy after costs AND passes the significance test
from Section 20a.

------------------------------------------------------------------------

## 24. Live Trading Rollout

Only after paper validation passes Section 35's quantitative gate.

```text
Stage 1: $0.50–$1 per trade
Stage 2: increase only after stable performance over a defined
         minimum number of additional resolved trades — never
         increase size simply because of a short winning streak.
```

Default production mode: `PAPER`. Explicitly switch to `SIGNAL`, then
later `LIVE`.

------------------------------------------------------------------------

## 25. Security & Compliance

Never commit secrets. Use Secret Manager for
`TELEGRAM_BOT_TOKEN`, `DATABASE_PASSWORD`, Polymarket credentials,
other API credentials. `.env` locally, added to `.gitignore`.

Compute Engine firewall: SSH keys only, no password SSH, no public
PostgreSQL, expose only required ports, least-privilege service
account.

**Legal/compliance check (new, from Feasibility Q5):** before any
live-money automation, confirm Polymarket's Terms of Service permit
automated API trading from the operator's actual jurisdiction. Do not
assume this is fine by default — verify and document the finding in
`docs/feasibility.md`.

------------------------------------------------------------------------

## 26. Storage and Backups

Object storage for immutable raw data and model artifacts:

```text
raw/hko/, raw/polymarket/, models/weather-v001/, models/weather-v002/, backups/
```

Database backup: daily, 7 daily / 4 weekly / 3 monthly retained. Test
restore periodically.

------------------------------------------------------------------------

## 27. Observability

Structured logs tracking: collector_success/failure,
prediction_success/failure, signal_count, paper_trade_count, API
latency, data freshness, daily PnL, model version.

Critical failures notify Telegram: HKO/Polymarket API unavailable,
database unavailable, model prediction failed, stale market, invalid
probability distribution, **no new market discovered by cutoff time
(NEW, see Section 15)**.

------------------------------------------------------------------------

## 28. CI/CD

```text
git push → lint → unit tests → leakage tests (NEW) → integration tests
  → build image → push → deploy → health check
```

Manual deployment acceptable initially (`docker compose pull && up -d`).
Automate later.

------------------------------------------------------------------------

## 29. Recommended Python Stack

```text
Core: Python 3.12+, pandas, numpy, scikit-learn, lightgbm, scipy,
      httpx, pydantic, SQLAlchemy, Alembic, psycopg
Telegram: python-telegram-bot
Testing/tooling: pytest, ruff, mypy
Later if needed: LangGraph, MLflow, Optuna, Great Expectations, dbt
```

Do not add "later if needed" items before there is a concrete need.

------------------------------------------------------------------------

## 30. Development Milestones (revised)

### M0 --- Feasibility (NEW, replaces jumping straight to infra)
- [ ] Answer Feasibility Q1--Q5, write `docs/feasibility.md`
- [ ] Go/No-Go decision documented
- [ ] Confirm authoritative HKO station matches Polymarket resolution source
- [ ] Determine Scenario A vs B for historical Polymarket data (Section 6)

### M1 --- Infrastructure
- [ ] Git repo, Python project, Docker, PostgreSQL, environment config, logging

### M2 --- HKO
- [ ] HKO client (polling cadence per Feasibility Q3, not assumed)
- [ ] historical ingestion, forecast ingestion, raw storage
- [ ] normalized schema, data-quality tests, station authority tagging

### M3 --- Polymarket
- [ ] market discovery (high-frequency, with missing-market alerting)
- [ ] question/bucket-schema parser with test cases per format variant
- [ ] market metadata, outcome/token mapping, price collector
- [ ] historical prices (if Scenario A) OR forward-collection start (if Scenario B)

### M4 --- Dataset
- [ ] feature tables, timestamp alignment
- [ ] leakage checks (dedicated test suite, including derived features)
- [ ] reproducible training dataset

### M5 --- ML
- [ ] output architecture decision finalized (Section 9.1)
- [ ] climatology + HKO-forecast baselines
- [ ] go/no-go check: does ML beat HKO forecast? (Section 9.3)
- [ ] LightGBM, calibration, evaluation

### M6 --- Trading Logic
- [ ] market probability, edge, EV, fee model, slippage model
- [ ] liquidity filter, risk engine

### M7 --- Backtest
- [ ] walk-forward validation (weather model)
- [ ] paper execution simulator
- [ ] no-edge control (Model G) + significance test
- [ ] ROI, drawdown, sensitivity analysis
- [ ] explicit sample-size caveat if Scenario B

### M8 --- Telegram
- [ ] daily summary, opportunity alerts, commands, health alerts

### M9 --- Production Deployment
- [ ] Compute Engine, Docker Compose, scheduler, Secret Manager,
      object storage, backups, monitoring

### M10 --- Paper Trading
- [ ] run until ≥50 resolved trades AND ≥30 days, whichever is later
- [ ] performance report, model recalibration, false-positive analysis
- [ ] significance test result documented

### M11 --- Agent Layer (optional, justify first)
- [ ] concrete use cases documented (Section 22) before building
- [ ] tool definitions, orchestration, guardrails
- [ ] deterministic risk integration (agent cannot bypass risk engine)

### M12 --- Optional Live Execution
- [ ] legal/compliance check passed (Section 25)
- [ ] authentication, execution simulator, tiny real-money test
- [ ] reconciliation, kill switch, audit log

------------------------------------------------------------------------

## 31. First 7 Days (revised — Day 0 added, infra pushed later)

### Day 0
- Answer Feasibility Q1--Q5
- Manually inspect 3-5 real Polymarket HK weather markets: bucket
  widths, resolution source text, typical volume/spread
- Write go/no-go decision

### Day 1
- Git, Docker, PostgreSQL (local is fine — infra migration can wait)
- HKO API client skeleton

### Day 2
- HKO historical ingestion, raw storage, schema
- Confirm authoritative station

### Day 3
- Polymarket discovery + bucket-schema parser
- Market metadata, price collection

### Day 4
- HKO + Polymarket alignment, EDA, data-quality checks
- Finalize output architecture decision (Section 9.1)

### Day 5
- Baseline models (climatology, HKO forecast baseline)
- Go/no-go check: does anything beat HKO forecast on early data?

### Day 6
- LightGBM, calibration, edge/EV, risk rules, paper-trade simulator

### Day 7
- Telegram daily summary, opportunity alerts, `/status`, `/performance`,
  health checks

At the end of this week the system should produce useful paper
signals, with an honest written note on whether Scenario A or B
applies to backtesting depth.

------------------------------------------------------------------------

## 32. Suggested Job Schedule

See Section 15 (frequencies now depend on Feasibility Q3 findings
rather than fixed assumptions).

------------------------------------------------------------------------

## 33. Important Product Decisions

### Do
- Run Feasibility research (Section 0) before writing any collector code
- Collect 5--8 years of HKO data from one authoritative station
- Collect whatever Polymarket history actually exists (Scenario A or B)
- Preserve forecast versions; leakage-test derived features specifically
- Design model output around actual Polymarket bucket schema
- Beat HKO's own forecast before considering the model useful
- Calibrate probabilities; account for fees/slippage
- Include a no-edge statistical control and run significance tests
- Paper trade until a minimum trade-count threshold, not just a fixed number of days
- Log every decision; keep the risk engine deterministic

### Do not
- Build 30+ sections of architecture before validating market
  liquidity and data availability
- Assume Polymarket has multi-year history without checking
- Assume HKO forecast update cadence — verify it
- Train an LLM to predict temperature
- Use random train/test split
- Leak raw OR derived features
- Start with auto-trading
- Conflate weather-model retraining cadence with trading-strategy monitoring cadence
- Use high leverage to compensate for a $15 bankroll
- Let an LLM bypass risk controls
- Build the agent layer without a concrete justified use case
- Declare "profitable" from a small trade sample without a significance test

------------------------------------------------------------------------

## 34. Final Target Architecture

```text
                  ┌──────────────────────────────┐
                  │          INTERNET             │
                  └──────────────┬───────────────┘
                                 │
                ┌────────────────┴────────────────┐
                │                                 │
                ▼                                 ▼
          HKO Open Data                      Polymarket
                │                                 │
                ▼                                 ▼
          HKO Collector                    Market Collector
        (authoritative station)          (bucket-schema parser)
                │                                 │
                └──────────────┬──────────────────┘
                               ▼
                          PostgreSQL
                               │
                   ┌───────────┴───────────┐
                   ▼                       ▼
            Feature Pipeline         Market Engine
                   │                       │
                   ▼                       │
             Weather Model                │
           (bucket-native output)         │
                   │                       │
                   ▼                       │
              Calibration                 │
                   │                       │
                   └───────────┬───────────┘
                               ▼
                          Edge + EV
                               │
                               ▼
                          Risk Engine
                               │
                     ┌─────────┴─────────┐
                     ▼                   ▼
                 Telegram          Paper Trading
                     │                   │
                     └─────────┬─────────┘
                               ▼
                    Analytics + Significance Test
                               │
                               ▼
                           Retraining
                               │
                               └──────> New Model
```

------------------------------------------------------------------------

## 35. Definition of Done (revised with quantitative gates)

The system is ready for a controlled small-money experiment only
when ALL of the following are true — vague checkbox items from the
original plan have been replaced with numeric thresholds:

- [ ] HKO ingestion reliable (>99% scheduled job success over 30 days)
- [ ] Polymarket ingestion reliable, including discovery (no missed
      market-day incidents over the trial period)
- [ ] Historical/forward dataset reproducible from raw storage
- [ ] Leakage tests pass (raw AND derived features)
- [ ] **ML model beats HKO official forecast** on out-of-sample Brier
      score by a clear margin (e.g. ≥10% relative improvement) —
      hard gate, not optional
- [ ] Probabilities calibrated (expected calibration error below an
      agreed threshold, e.g. <0.05)
- [ ] Backtest/paper sample reaches ≥50 resolved trades
- [ ] Strategy ROI positive AND statistically distinguishable from
      the no-edge control (Model G) at a pre-agreed significance level
- [ ] Fees/slippage included in all PnL figures
- [ ] Risk limits enforced in practice (verified via at least one
      deliberately triggered test of each limit)
- [ ] Kill switch tested
- [ ] Telegram monitoring and `/pause` verified to actually halt signal generation
- [ ] Database backup/restore tested end-to-end at least once
- [ ] Model versioning works
- [ ] Secrets secured (no plaintext secrets in repo history)
- [ ] Compliance check passed (Section 25)
- [ ] Live execution disabled by default

------------------------------------------------------------------------

## 36. Long-Term Roadmap

```text
V0.0  Feasibility research (NEW — gates everything else)
V0.1  Data collectors
V0.2  Weather prediction (must beat HKO forecast baseline)
V0.3  Polymarket integration
V0.4  Edge/EV engine
V0.5  Telegram signal bot
V0.6  Paper trading + significance testing
V0.7  AI agent (only if justified use case exists)
V0.8  Optional automated execution
V0.9  Portfolio/risk optimization
V1.0  Production quantitative weather-market agent
```

The real objective is not simply "predict tomorrow's temperature." It
is: estimate the probability better than the market, prove that edge
is statistically real rather than noise, and determine whether the
difference is large enough to justify risk after fees, slippage,
liquidity, and uncertainty.
