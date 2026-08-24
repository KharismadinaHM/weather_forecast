"""Polymarket prediction market discovery, schema parsing, and price ingestion pipeline."""

import json
import re
from datetime import UTC, date, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.collectors.bucket_parser import BucketParser
from app.collectors.validators import DataQualityError
from app.config.settings import Settings, get_settings
from app.logging_config import get_logger
from app.storage.models import PolymarketMarket, PolymarketOutcome, PolymarketPrice
from app.storage.raw import save_raw_response

logger = get_logger("polymarket_collector")


class PolymarketCollector:
    """Client for discovering Hong Kong weather prediction markets and collecting prices."""

    def __init__(self, settings: Settings | None = None, timeout: float = 10.0) -> None:
        self.settings = settings or get_settings()
        self.gamma_url = self.settings.POLYMARKET_GAMMA_URL.rstrip("/")
        self.clob_url = self.settings.POLYMARKET_CLOB_URL.rstrip("/")
        self.timeout = timeout

    def _fetch_gamma(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Fetch endpoint from Polymarket Gamma API with retries."""
        url = f"{self.gamma_url}/{path.lstrip('/')}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }
        transport = httpx.HTTPTransport(retries=3)
        with httpx.Client(
            transport=transport, timeout=self.timeout, follow_redirects=True, headers=headers
        ) as client:
            try:
                response = client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Polymarket Gamma HTTP error", status_code=e.response.status_code, path=path
                )
                raise
            except httpx.RequestError as e:
                logger.error("Polymarket Gamma connection error", error=str(e), path=path)
                raise

    def discover_hk_weather_events(self, active_only: bool = True) -> list[dict[str, Any]]:
        """Query Gamma API dynamically for Hong Kong weather related events."""
        matched_events: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        # 1. Query by series_slugs (Hong Kong Daily Weather, Lowest Temp, etc.)
        for s_slug in [
            "hong-kong-daily-weather",
            "lowest-temperature-in-hong-kong",
            "hong-kong-lowest-temperature",
            "hong-kong-weather",
        ]:
            series_params: dict[str, Any] = {"series_slug": s_slug}
            if active_only:
                series_params["closed"] = "false"
            try:
                series_data = self._fetch_gamma("events", params=series_params)
                if isinstance(series_data, list):
                    for event in series_data:
                        e_id = str(event.get("id"))
                        if e_id not in seen_ids:
                            seen_ids.add(e_id)
                            matched_events.append(event)
            except Exception as exc:
                logger.debug("Series query not found", series_slug=s_slug, error=str(exc))

        # 2. Query by tag_slug (hong-kong)
        tag_params: dict[str, Any] = {"tag_slug": "hong-kong"}
        if active_only:
            tag_params["closed"] = "false"
        try:
            tag_data = self._fetch_gamma("events", params=tag_params)
            if isinstance(tag_data, list):
                for event in tag_data:
                    e_id = str(event.get("id"))
                    if e_id not in seen_ids:
                        title = str(event.get("title", "")).lower()
                        desc = str(event.get("description", "")).lower()
                        slug = str(event.get("slug", "")).lower()
                        is_weather = (
                            "temperature" in title
                            or "temperature" in desc
                            or "weather" in title
                            or "weather" in desc
                            or "degrees" in desc
                            or "daily-weather" in slug
                        )
                        if is_weather:
                            seen_ids.add(e_id)
                            matched_events.append(event)
        except Exception as exc:
            logger.warning("Error fetching tag_slug events", error=str(exc))

        # 3. Fallback general query with HK keywords
        params: dict[str, Any] = {"limit": 100}
        if active_only:
            params["closed"] = "false"
        try:
            data = self._fetch_gamma("events", params=params)
            if isinstance(data, list):
                for event in data:
                    e_id = str(event.get("id"))
                    if e_id in seen_ids:
                        continue
                    title = str(event.get("title", "")).lower()
                    desc = str(event.get("description", "")).lower()
                    slug = str(event.get("slug", "")).lower()

                    is_hk = (
                        "hong kong" in title
                        or "hong kong" in desc
                        or "hong-kong" in slug
                        or "hko" in desc
                    )
                    is_weather = (
                        "temperature" in title
                        or "temperature" in desc
                        or "weather" in title
                        or "weather" in desc
                        or "degrees" in desc
                    )

                    if is_hk and is_weather:
                        seen_ids.add(e_id)
                        matched_events.append(event)
        except Exception as exc:
            logger.warning("Error fetching fallback events", error=str(exc))

        logger.info("Discovered Hong Kong weather events", count=len(matched_events))
        return matched_events

    def check_missing_markets(
        self, target_dates: list[date], active_events: list[dict[str, Any]] | None = None
    ) -> list[date]:
        """Verify presence of listed markets for upcoming target dates (missing market alerting)."""
        if active_events is None:
            active_events = self.discover_hk_weather_events(active_only=True)

        found_dates: set[date] = set()
        for event in active_events:
            for mkt in event.get("markets", []):
                question = mkt.get("question", "")
                slug = mkt.get("slug", "")
                try:
                    t_date = BucketParser.extract_target_date(question, slug)
                    found_dates.add(t_date)
                except DataQualityError:
                    continue

        missing_dates = [d for d in target_dates if d not in found_dates]
        if missing_dates:
            logger.warning(
                "Missing market alert: No Polymarket weather market discovered for dates",
                missing_dates=missing_dates,
            )

        return missing_dates

    def parse_market_data(
        self, raw_market: dict[str, Any], event_data: dict[str, Any] | None = None
    ) -> tuple[PolymarketMarket, list[PolymarketOutcome], list[PolymarketPrice]]:
        """Parse raw market and event JSON into structured SQLAlchemy model entities."""
        event_data = event_data or {}

        market_id = str(raw_market.get("id", "")).strip()
        if not market_id:
            raise DataQualityError("Market is missing required 'id' field")

        event_id = str(raw_market.get("eventId") or event_data.get("id") or "").strip()
        slug = str(
            raw_market.get("slug") or event_data.get("slug") or f"market-{market_id}"
        ).strip()
        question = str(raw_market.get("question", "")).strip()
        if not question:
            raise DataQualityError(f"Market {market_id} is missing question text")

        # 1. Extract Target Date
        target_date = BucketParser.extract_target_date(question, slug)

        # 2. Extract Resolution Source (Verbatim)
        resolution_source_raw = (
            raw_market.get("resolutionSource")
            or event_data.get("resolutionSource")
            or raw_market.get("description")
            or event_data.get("description")
        )
        resolution_str = str(resolution_source_raw).strip() if resolution_source_raw else None

        # 3. Market Status and Timestamps
        is_closed = bool(raw_market.get("closed", False))
        is_active = bool(raw_market.get("active", True))
        status = "closed" if is_closed else ("active" if is_active else "inactive")

        start_time: datetime | None = None
        end_time: datetime | None = None
        if raw_market.get("startDate"):
            try:
                start_time = datetime.fromisoformat(str(raw_market["startDate"]))
            except ValueError:
                pass
        if raw_market.get("endDate"):
            try:
                end_time = datetime.fromisoformat(str(raw_market["endDate"]))
            except ValueError:
                pass

        # 4. Parse Outcomes & Tokens
        # Outcomes can be a JSON string like '["<=30°C", "31°C", ...]' or a list
        raw_outcomes = raw_market.get("outcomes", [])
        if isinstance(raw_outcomes, str):
            try:
                raw_outcomes = json.loads(raw_outcomes)
            except json.JSONDecodeError as err:
                raise DataQualityError(f"Invalid outcomes JSON for market {market_id}") from err

        raw_clob_tokens = raw_market.get("clobTokenIds", [])
        if isinstance(raw_clob_tokens, str):
            try:
                raw_clob_tokens = json.loads(raw_clob_tokens)
            except json.JSONDecodeError:
                raw_clob_tokens = []

        raw_outcome_prices = raw_market.get("outcomePrices", [])
        if isinstance(raw_outcome_prices, str):
            try:
                raw_outcome_prices = json.loads(raw_outcome_prices)
            except json.JSONDecodeError:
                raw_outcome_prices = []

        if not raw_outcomes or not isinstance(raw_outcomes, list):
            raise DataQualityError(f"Market {market_id} has no valid outcomes defined")

        # Check if outcomes is binary ["Yes", "No"] (Polymarket NegRisk market for specific temperature bucket)
        is_binary_yes_no = (
            len(raw_outcomes) == 2
            and str(raw_outcomes[0]).strip().lower() == "yes"
            and str(raw_outcomes[1]).strip().lower() == "no"
        )

        if is_binary_yes_no:
            bucket_label = (
                raw_market.get("groupItemTitle")
                or raw_market.get("title")
                or ""
            ).strip()

            if not bucket_label:
                # Try to extract temperature phrase from question or slug
                m_temp = re.search(
                    r"(\d+(?:\.\d+)?\s*(?:°?C|degrees?)?(?:\s*(?:or\s+(?:higher|above|more|greater|below|lower|less|under))|\+)?|(?:<=|<|>=|>|under|below|above|over)\s*\d+(?:\.\d+)?\s*(?:°?C|degrees?)?)",
                    f"{question} {slug}",
                    re.IGNORECASE,
                )
                if m_temp:
                    bucket_label = m_temp.group(1).strip()
                else:
                    raise DataQualityError(
                        f"Binary market {market_id} has no groupItemTitle and temperature bucket could not be extracted from question '{question}'"
                    )

            parsed_bucket = BucketParser.parse_bucket(bucket_label)
            parsed_buckets = [parsed_bucket]
            outcome_bucket_schema = [parsed_bucket.to_dict()]
        else:
            # Parse multi-outcome discrete buckets using Section 9.1 BucketParser
            parsed_buckets = BucketParser.parse_bucket_schema([str(o) for o in raw_outcomes])
            outcome_bucket_schema = [b.to_dict() for b in parsed_buckets]

        is_low = (
            "lowest" in f"{question} {slug}".lower()
            or "minimum" in f"{question} {slug}".lower()
            or "min temp" in f"{question} {slug}".lower()
        )
        market_type = "temperature_low" if is_low else "temperature_high"

        market = PolymarketMarket(
            market_id=market_id,
            event_id=event_id or "unknown_event",
            slug=slug,
            question=question,
            market_type=market_type,
            outcome_bucket_schema=outcome_bucket_schema,
            target_date=target_date,
            metric="temperature_celsius",
            status=status,
            resolution_source_raw=resolution_str,
            start_time=start_time,
            end_time=end_time,
        )

        outcomes: list[PolymarketOutcome] = []
        prices: list[PolymarketPrice] = []
        now_utc = datetime.now(UTC)

        for idx, bucket in enumerate(parsed_buckets):
            token_id = (
                str(raw_clob_tokens[idx]) if idx < len(raw_clob_tokens) else f"{market_id}_{idx}"
            )
            outcome_obj = PolymarketOutcome(
                market_id=market_id,
                token_id=token_id,
                outcome_label=bucket.raw_label,
                outcome_bucket_low=bucket.low,
                outcome_bucket_high=bucket.high,
                outcome_value=str(idx),
            )
            outcomes.append(outcome_obj)

            # Check price if available in outcomePrices (for binary market, outcomePrices[0] is Yes price)
            if idx < len(raw_outcome_prices):
                try:
                    price_val = float(raw_outcome_prices[idx])
                    # Data Quality Check: price must be in [0.0, 1.0]
                    if not (0.0 <= price_val <= 1.0):
                        logger.warning(
                            "Price out of bounds [0, 1]; SKIP price point",
                            token_id=token_id,
                            price=price_val,
                        )
                    else:
                        price_obj = PolymarketPrice(
                            market_id=market_id,
                            token_id=token_id,
                            timestamp=now_utc,
                            price=price_val,
                            side=None,
                            volume=float(
                                raw_market.get("volumeNum") or raw_market.get("volume") or 0.0
                            ),
                        )
                        prices.append(price_obj)
                except (ValueError, TypeError) as err:
                    logger.warning(
                        "Failed to parse outcome price", error=str(err), token_id=token_id
                    )

        return market, outcomes, prices

    def ingest_markets_and_prices(
        self,
        session: Session,
        raw_events: list[dict[str, Any]] | None = None,
        archive_raw: bool = True,
    ) -> tuple[int, int, int]:
        """Discover, parse, and persist HK weather markets, outcomes, and price snapshots."""
        if raw_events is None:
            raw_events = self.discover_hk_weather_events(active_only=False)

        if archive_raw and raw_events:
            save_raw_response("polymarket", "events", raw_events)

        markets_count = 0
        outcomes_count = 0
        prices_count = 0

        for event in raw_events:
            event_markets = event.get("markets", [])
            for raw_mkt in event_markets:
                try:
                    market, outcomes, prices = self.parse_market_data(raw_mkt, event_data=event)
                except (DataQualityError, Exception) as err:
                    logger.error(
                        "Failed to parse market; SKIP record",
                        error=str(err),
                        market_id=raw_mkt.get("id"),
                    )
                    continue

                # 1. Ingest / Merge Market
                existing_mkt = (
                    session.query(PolymarketMarket).filter_by(market_id=market.market_id).first()
                )
                if not existing_mkt:
                    session.add(market)
                    markets_count += 1
                else:
                    existing_mkt.status = market.status
                    existing_mkt.market_type = market.market_type
                    existing_mkt.outcome_bucket_schema = market.outcome_bucket_schema
                    existing_mkt.resolution_source_raw = (
                        market.resolution_source_raw or existing_mkt.resolution_source_raw
                    )

                # 2. Ingest Outcomes
                for outcome in outcomes:
                    existing_out = (
                        session.query(PolymarketOutcome)
                        .filter_by(market_id=outcome.market_id, token_id=outcome.token_id)
                        .first()
                    )
                    if not existing_out:
                        session.add(outcome)
                        outcomes_count += 1
                    else:
                        existing_out.outcome_bucket_low = outcome.outcome_bucket_low
                        existing_out.outcome_bucket_high = outcome.outcome_bucket_high

                # 3. Ingest Prices
                for price in prices:
                    session.add(price)
                    prices_count += 1

        session.commit()
        logger.info(
            "Completed Polymarket ingestion",
            markets=markets_count,
            outcomes=outcomes_count,
            prices=prices_count,
        )
        return markets_count, outcomes_count, prices_count
