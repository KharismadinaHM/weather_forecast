"""Unit tests for PolymarketCollector parser, discovery, and ingestion."""

from datetime import date
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.collectors.polymarket import PolymarketCollector
from app.storage.models import PolymarketMarket, PolymarketPrice


@pytest.fixture
def sample_hk_weather_event() -> dict[str, Any]:
    """Sample Polymarket Gamma event structure for Hong Kong temperature market."""
    return {
        "id": "evt_hk_20260823",
        "title": "Highest temperature in Hong Kong on August 23, 2026",
        "slug": "hong-kong-high-temp-august-23-2026",
        "description": "Resolves to max daily temperature by Hong Kong Observatory.",
        "resolutionSource": "https://data.weather.gov.hk",
        "startDate": "2026-08-22T00:00:00Z",
        "endDate": "2026-08-23T16:00:00Z",
        "active": True,
        "closed": False,
        "markets": [
            {
                "id": "mkt_hk_9988",
                "question": "What will the highest temperature in Hong Kong be on August 23, 2026?",
                "slug": "hong-kong-high-temp-august-23-2026",
                "outcomes": '["<=30°C", "31°C", "32°C", ">=33°C"]',
                "clobTokenIds": '["tok_0", "tok_1", "tok_2", "tok_3"]',
                "outcomePrices": '["0.10", "0.35", "0.45", "0.10"]',
                "volumeNum": 125000.0,
                "active": True,
                "closed": False,
            }
        ],
    }


def test_parse_market_data(sample_hk_weather_event: dict[str, Any]) -> None:
    """Verify parsing raw Gamma market data into SQLAlchemy model entities."""
    collector = PolymarketCollector()
    raw_mkt = sample_hk_weather_event["markets"][0]
    market, outcomes, prices = collector.parse_market_data(
        raw_mkt, event_data=sample_hk_weather_event
    )

    assert market.market_id == "mkt_hk_9988"
    assert market.target_date == date(2026, 8, 23)
    assert market.status == "active"
    assert "data.weather.gov.hk" in str(market.resolution_source_raw)
    assert isinstance(market.outcome_bucket_schema, list)
    assert len(market.outcome_bucket_schema) == 4

    assert len(outcomes) == 4
    assert outcomes[0].token_id == "tok_0"
    assert outcomes[0].outcome_label == "<=30°C"
    assert outcomes[0].outcome_bucket_high == 30.0

    assert outcomes[1].token_id == "tok_1"
    assert outcomes[1].outcome_label == "31°C"
    assert outcomes[1].outcome_bucket_low == 31.0
    assert outcomes[1].outcome_bucket_high == 31.0

    assert len(prices) == 4
    assert prices[1].price == 0.35
    assert prices[2].price == 0.45


def test_price_out_of_bounds_data_quality_filter(sample_hk_weather_event: dict[str, Any]) -> None:
    """Verify prices outside [0, 1] are rejected per Section 17."""
    collector = PolymarketCollector()
    raw_mkt = sample_hk_weather_event["markets"][0]
    # Corrupt one price to 1.50
    raw_mkt["outcomePrices"] = '["0.10", "1.50", "0.45", "0.10"]'

    _, _, prices = collector.parse_market_data(raw_mkt, event_data=sample_hk_weather_event)
    # The invalid price should be filtered out
    assert len(prices) == 3


def test_ingest_markets_and_prices(
    db_session: Session, sample_hk_weather_event: dict[str, Any]
) -> None:
    """Verify end-to-end database ingestion of markets, outcomes, and price snapshots."""
    collector = PolymarketCollector()
    m_cnt, o_cnt, p_cnt = collector.ingest_markets_and_prices(
        db_session, [sample_hk_weather_event], archive_raw=False
    )

    assert m_cnt == 1
    assert o_cnt == 4
    assert p_cnt == 4

    # Verify rows in DB
    db_mkt = db_session.query(PolymarketMarket).filter_by(market_id="mkt_hk_9988").first()
    assert db_mkt is not None
    assert len(db_mkt.outcomes) == 4
    assert len(db_mkt.prices) == 4

    # Re-ingest: adds a new price row snapshot, while market and outcomes are merged
    m_cnt2, o_cnt2, p_cnt2 = collector.ingest_markets_and_prices(
        db_session, [sample_hk_weather_event], archive_raw=False
    )
    assert m_cnt2 == 0
    assert o_cnt2 == 0
    assert p_cnt2 == 4
    assert db_session.query(PolymarketPrice).count() == 8


def test_check_missing_markets(sample_hk_weather_event: dict[str, Any]) -> None:
    """Verify missing market alert identifies target dates without active markets."""
    collector = PolymarketCollector()
    # Listed date: 2026-08-23
    target_dates = [date(2026, 8, 23), date(2026, 8, 24), date(2026, 8, 25)]

    missing = collector.check_missing_markets(target_dates, active_events=[sample_hk_weather_event])
    assert len(missing) == 2
    assert date(2026, 8, 24) in missing
    assert date(2026, 8, 25) in missing
    assert date(2026, 8, 23) not in missing
