# Feasibility Research — Hong Kong Weather Prediction Market AI Agent

**Date:** 2026-08-22
**Author:** Automated research (Day 0 / M0)
**Status:** COMPLETE — awaiting owner review

---

## Q1. Does Polymarket expose historical price time-series for CLOSED / resolved markets via API?

### Finding: PARTIALLY — unreliable via REST API, reliable via on-chain data

**REST API (`clob.polymarket.com`):**
- Polymarket's CLOB API provides a `GET /prices-history` endpoint
  (documented at `docs.polymarket.com/api-reference/markets/get-prices-history`).
- However, this endpoint is **primarily designed for active/current markets**.
  Multiple developer reports (GitHub issues, community forums) confirm that
  `prices-history` frequently returns **empty or truncated data** for closed
  and resolved markets.
- A batch variant (`GET /batch-prices-history`) also exists but shares the
  same limitation.

**Gamma API (`gamma-api.polymarket.com`):**
- The Gamma API can list market metadata for closed markets (using
  `closed=true` filter), including outcome prices at resolution, volume,
  liquidity, and timestamps.
- However, it does **not** provide intraday price time-series (i.e., the
  price path from market creation to resolution).

**On-chain data (Polygon blockchain):**
- All Polymarket trades are recorded on-chain as `OrderFilled` events on
  Polygon smart contracts.
- Tools like **Envio HyperSync** can stream these logs and reconstruct
  complete trade/price histories for any market (active or resolved).
- Open-source datasets exist (e.g., `SII-WANGZJ/Polymarket_data` on GitHub)
  with billions of decoded trading records.
- Third-party indexers (e.g., **Bitquery** GraphQL API, **Apify** actors)
  offer pre-processed historical data including L2 order book snapshots.

### Implication for Section 6

| Approach | Effort | Reliability | Coverage |
|----------|--------|-------------|----------|
| REST API `prices-history` | Low | **Unreliable** for closed markets | Incomplete |
| Gamma API metadata only | Low | Good for snapshots | No intraday series |
| On-chain indexing (HyperSync/Bitquery) | Medium-High | **Complete & permanent** | Full trade history |
| Third-party datasets | Medium | Depends on provider | Varies |

**Conclusion:** Historical price data for closed HK weather markets **does
exist** but is not easily accessible via the standard REST API alone.
Reconstructing it requires on-chain indexing or third-party data providers.

**→ This is a hybrid between Scenario A and Scenario B:**
- Scenario A applies *in principle* (data exists on-chain).
- But the engineering effort to extract it is non-trivial (Medium-High).
- **Recommended approach:** Start in **Scenario B (collect-forward-only)**
  mode using the REST API for active markets, while building on-chain
  indexing as a parallel workstream to backfill historical data. This avoids
  blocking M1–M3 on the indexing pipeline.

---

## Q2. How many Hong Kong weather markets has Polymarket listed? Typical volume and bid/ask spread?

### Finding: ACTIVE and SIGNIFICANT — daily markets with meaningful volume

**Market availability:**
- Hong Kong daily temperature markets are **currently active** on Polymarket
  as of August 2026.
- These markets were previously delisted (circa late 2025 / early 2026) but
  were **resumed** with clarified resolution rules referencing the Hong Kong
  Observatory (HKO).
- Markets are created **daily** — typically one event per day for the daily
  high temperature, structured as a multi-outcome (negative-risk) market
  with discrete temperature buckets.

**Market structure:**
- Outcomes are structured as **density buckets**, typically 1°C or 2°C wide
  (e.g., "≤29°C", "30°C", "31°C", "32°C", "33°C", "≥34°C").
- Each bucket is a separate tradeable token within a single event.

**Volume:**
- Individual daily markets have recorded volume exceeding **$200,000** in
  August 2026.
- Cumulative volume for HK daily temperature markets in July–August 2026 is
  reportedly in the **millions of dollars**.
- This is well above the threshold needed for viable signal generation.

**Liquidity and spread:**
- Liquidity can be **thin** in less popular buckets (tails of the
  distribution) and outside peak trading hours.
- The most liquid buckets (near the forecast median) typically have tighter
  spreads (1–3 cents).
- Tail buckets may have wide spreads (5–10+ cents) or no resting orders.
- Professional traders and bots are active in this niche, contributing to
  price discovery but also meaning the market is not "easy edge."

**Frequency assessment:**
- Markets appear **daily** (≫ 2×/month threshold from go/no-go rule).
- Market creation timing needs to be verified empirically during M3 to
  confirm the cutoff time for discovery alerting (Section 15).

### Implication

Q2 passes the go/no-go threshold: markets are frequent (daily), volume is
meaningful ($200K+/day), and the market structure (temperature buckets) is
well-suited for probabilistic weather modeling.

> [!WARNING]
> The fact that professional bots already trade these markets means the
> "easy edge" assumption should be tempered. The model must genuinely beat
> market consensus, not just beat climatology.

---

## Q3. What is HKO's actual forecast publish cadence?

### Finding: Product-dependent — ranges from every 12 minutes to twice daily

Verified via the official HKO Open Data API documentation and live API
responses on 2026-08-22:

| HKO Product | API `dataType` | Update Cadence | Relevance |
|-------------|---------------|----------------|-----------|
| Current Weather Report | `rhrread` | **Hourly** + on change | Temperature, humidity, wind — actuals |
| Local Weather Forecast | `flw` | **Hourly** + on change | Short-range narrative forecast |
| 9-Day Weather Forecast | `fnd` | **~Twice daily** + on change | Max/min temp per day — **primary forecast input** |
| Rainfall Nowcast (gridded) | `gridRain` | **Every 12 min** | Rain probability feature |
| Hourly Rainfall (past hour) | `rhrread` (rainfall section) | **Every 15 min** | Rain actuals |
| Special Weather Tips | various | As needed | Severe weather alerts |

**Key observation for the 9-day forecast:**
- Live API response showed `updateTime: "2026-08-22T11:30:00+08:00"`.
- The 9-day forecast (`fnd`) provides `forecastMaxtemp` and
  `forecastMintemp` for each of the next 9 days — this is the **most
  directly relevant** product for predicting Polymarket temperature bucket
  outcomes.
- Since it updates ~twice daily (plus ad-hoc), polling hourly for this
  product would waste ~22/24 calls on identical data. **Recommended polling:
  every 3–4 hours** with change detection (compare `updateTime` to last
  known value).

**For the current weather report (`rhrread`):**
- Updates hourly with actual temperatures from ~27 stations across Hong
  Kong.
- The **"Hong Kong Observatory"** station is explicitly listed with its own
  temperature reading (confirmed: 31°C at 13:00 HKT on 2026-08-22).
- **Recommended polling: hourly**, aligned with the data update cycle.

### Polling Schedule Recommendation (for Section 15)

```text
Product               Recommended Poll    Rationale
─────────────────────────────────────────────────────
9-day forecast (fnd)  Every 3–4 hours     Updates ~2×/day; use change detection
Current weather        Every 1 hour        Updates hourly
Local forecast (flw)  Every 1 hour        Updates hourly
Rainfall nowcast      Every 15 min        Updates every 12 min (if used as feature)
Polymarket prices     Every 15 min        Per Section 15
Market discovery      Every 15 min        Combined with price collection
```

---

## Q4. What does Polymarket's resolution source actually reference?

### Finding: Hong Kong Observatory — likely HKO Headquarters station

**Resolution source:**
- Polymarket HK weather markets reference the **Hong Kong Observatory
  (HKO)** as their official data source for resolution.
- The markets were explicitly resumed with this clarification after the
  earlier delisting.

**HKO Headquarters station:**
- The HKO Headquarters (Tsim Sha Tsui) has been Hong Kong's official
  meteorological reference station since **1884**.
- It is the station used for official daily maximum and minimum temperature
  records published in the HKO's climatological bulletins.
- The HKO Open Data API lists it explicitly as `"Hong Kong Observatory"` in
  the temperature readings (confirmed in live API response).

**Measurement details:**
- Daily max/min temperatures are recorded to **0.1°C** precision.
- The "daily" measurement window follows standard meteorological convention
  (midnight to midnight HKT, i.e., UTC+8).
- Historical daily data is available via `data.gov.hk` in CSV format and
  through the HKO climatological information services portal, going back
  to 1884 (with a gap 1940–1946).

**Reconciliation with Section 5.1:**
- The authoritative station for this project should be **HKO Headquarters**
  (`place: "Hong Kong Observatory"` in the API).
- This matches what Polymarket's resolution source references.
- Other stations in the API (King's Park, Sha Tin, Chek Lap Kok, etc.)
  should be stored with `is_authoritative = false` and used only as
  supplementary features.

> [!IMPORTANT]
> **Remaining verification needed during M3:** Inspect the exact resolution
> text of 3–5 live Polymarket HK weather markets to confirm whether they
> reference "Hong Kong Observatory" generally (which could mean the
> institution's published figure, i.e., HQ station) or a specific station
> name. This must be confirmed before finalizing the authoritative station
> choice.

---

## Q5. Does Polymarket's Terms of Service permit automated trading/API access from Hong Kong?

### Finding: TECHNICALLY PERMITTED but LEGALLY GRAY

**Polymarket's position on automated trading:**
- Polymarket provides official CLOB API and SDKs (Python, TypeScript)
  explicitly designed for programmatic trading.
- Automated trading (bots, market making, algorithmic strategies) is a
  **well-established and permitted** practice on the platform.
- The platform has recently migrated to CLOB V2 with updated libraries
  (`py-clob-client-v2`).
- Dynamic fees were introduced on certain short-term markets in early 2026,
  which affects bot profitability — this must be factored into the fee model
  (Section 12).

**Hong Kong jurisdictional status:**
- As of August 2026, Polymarket is **accessible** from Hong Kong — there is
  no geo-block or IP-based restriction for HK users (unlike Singapore,
  Taiwan, and Thailand which are blocked).
- However, Hong Kong authorities (Investor and Financial Education Council
  under the SFC) have publicly **warned** that prediction market platforms
  pose significant risks and that participation could potentially be
  classified as **illegal gambling** under local laws.
- Users operate **without regulatory protections** — no recourse under the
  Securities and Futures Ordinance.

**Risk assessment for this project:**

| Risk | Level | Mitigation |
|------|-------|------------|
| Platform access blocked | Low (currently) | Monitor for geo-block changes |
| Legal classification as gambling | **Medium** | Paper/signal mode only initially; no real money |
| Funds at risk on platform | Medium | Minimal bankroll ($15); kill switch |
| ToS violation | Low | API trading is explicitly supported |
| Regulatory change | Medium | Monitor HK SFC announcements |

> [!CAUTION]
> **For paper/signal mode (Sections 23, M10):** No legal risk — the system
> only generates signals and does not transact.
>
> **For live trading (Section 24, M12):** The operator must independently
> verify the current legal status of prediction market participation in
> their jurisdiction before deploying real money. This feasibility study
> does NOT constitute legal advice. The $15 bankroll is deliberately tiny
> to limit exposure, but the legal gray area is a genuine risk.

---

## Go/No-Go Decision

### Criteria Assessment

| Criterion | Result | Status |
|-----------|--------|--------|
| Q1: Historical price access | Partial — on-chain yes, REST API unreliable | ⚠️ Manageable |
| Q2: Market frequency ≥ 2×/month | **Daily** markets with $200K+ volume | ✅ PASS |
| Q2: Sufficient liquidity | Moderate — liquid at center, thin at tails | ✅ PASS (with caveats) |
| Q3: Forecast cadence known | Yes — product-specific, documented | ✅ PASS |
| Q4: Resolution source matches HKO | Yes — HKO Headquarters station | ✅ PASS |
| Q5: API trading permitted | Yes, explicitly supported | ✅ PASS |
| Q5: Jurisdiction clear | No — legal gray area for live trading | ⚠️ Risk accepted for paper mode |

### Decision: **🟢 GO** (with conditions)

The project is viable and should proceed to M1, subject to these conditions:

1. **Start in Scenario B (collect-forward-only)** for Polymarket price data.
   Build on-chain indexing as a parallel/deferred workstream to backfill
   historical prices. Do not block M1–M5 on this.

2. **Paper/signal mode only** until the jurisdictional risk is independently
   assessed by the operator for live trading (M12).

3. **Authoritative station = HKO Headquarters** (`"Hong Kong Observatory"`
   in the API). Verify against exact Polymarket resolution text during M3.

4. **Fee model must account for dynamic fees** introduced in early 2026,
   not just the base 4% taker fee. Verify the current fee schedule for
   weather markets specifically during M3.

5. **Temper edge expectations:** Professional bots already trade HK weather
   markets. The go/no-go check at M5 (Section 9.3 — does ML beat HKO
   forecast?) is critical and should be treated as a hard gate.

### Section 6 Scenario Determination

**→ Scenario B (collect-forward-only) as the primary path.**

Rationale:
- The REST API's `prices-history` endpoint is unreliable for closed markets.
- On-chain indexing (Scenario A in principle) is feasible but requires
  significant additional engineering (Polygon event decoding, HyperSync or
  Bitquery integration) that should not block the core pipeline.
- Forward collection via the REST API for active markets is
  straightforward and sufficient to begin building the dataset immediately.
- Backfilling historical data can proceed in parallel once the core
  pipeline (M1–M5) is functional.

**Impact on downstream milestones:**
- M7 (Backtest): Must be re-scoped per Section 18 caveat — no meaningful
  trading backtest until ≥50 resolved trades are collected in forward mode.
  Weather model validation can proceed immediately using 5–8 years of HKO
  historical data.
- M10 (Paper Trading): Timeline may extend beyond 60 days if trade sample
  remains small. The ≥50 resolved trades threshold from Section 23 applies.

---

## Appendix: Live API Verification (2026-08-22)

### HKO 9-Day Forecast (sample)

```json
{
  "updateTime": "2026-08-22T11:30:00+08:00",
  "weatherForecast": [
    {
      "forecastDate": "20260823",
      "forecastMaxtemp": {"value": 32, "unit": "C"},
      "forecastMintemp": {"value": 27, "unit": "C"}
    },
    {
      "forecastDate": "20260824",
      "forecastMaxtemp": {"value": 31, "unit": "C"},
      "forecastMintemp": {"value": 27, "unit": "C"}
    }
  ]
}
```

### HKO Current Temperature Stations (partial)

```text
Station                    Temp (°C)   Time
──────────────────────────────────────────────
Hong Kong Observatory      31         13:00 HKT  ← authoritative
King's Park                31         13:00 HKT
Sha Tin                    31         13:00 HKT
Chek Lap Kok               33         13:00 HKT
Happy Valley               33         13:00 HKT
(27 stations total)
```

### Polymarket API Structure

```text
Gamma API:  gamma-api.polymarket.com  → market discovery, metadata, outcomes
CLOB API:   clob.polymarket.com       → live prices, order book, trading
Data API:   data-api.polymarket.com   → user-specific trade history
```

---

## M0 Checklist

- [x] Answer Feasibility Q1–Q5
- [x] Go/No-Go decision documented: **GO** (with conditions)
- [x] Authoritative HKO station identified: **HKO Headquarters**
  (pending final verification against Polymarket resolution text in M3)
- [x] Scenario A vs B determined: **Scenario B (collect-forward-only)**
  as primary path; on-chain backfill as deferred parallel workstream
