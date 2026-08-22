"""Unit tests for HKOCollector parser, data quality checks, and ingestion."""

from datetime import date
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.collectors.hko import HKOCollector
from app.collectors.validators import DataQualityError
from app.storage.models import WeatherForecast, WeatherObservation


@pytest.fixture
def sample_rhrread_payload() -> dict[str, Any]:
    """Sample live payload for HKO rhrread endpoint."""
    return {
        "updateTime": "2026-08-22T13:00:00+08:00",
        "temperature": {
            "data": [
                {"place": "Hong Kong Observatory", "value": 31.2, "unit": "C"},
                {"place": "King's Park", "value": 30.8, "unit": "C"},
                {"place": "Chek Lap Kok", "value": 33.1, "unit": "C"},
            ]
        },
        "humidity": {
            "recordTime": "2026-08-22T13:00:00+08:00",
            "data": [{"place": "Hong Kong Observatory", "value": 78, "unit": "percent"}],
        },
        "rainfall": {"data": [{"place": "Central & Western District", "max": 0, "main": "TRUE"}]},
        "specialWxTips": ["Hot weather warning in force."],
    }


@pytest.fixture
def sample_fnd_payload() -> dict[str, Any]:
    """Sample live payload for HKO fnd (9-day forecast) endpoint."""
    return {
        "updateTime": "2026-08-22T11:30:00+08:00",
        "generalSituation": "Trough of low pressure active.",
        "weatherForecast": [
            {
                "forecastDate": "20260823",
                "forecastMaxtemp": {"value": 32, "unit": "C"},
                "forecastMintemp": {"value": 27, "unit": "C"},
                "forecastMaxrh": {"value": 95, "unit": "percent"},
                "forecastMinrh": {"value": 70, "unit": "percent"},
                "forecastWind": "Southwest force 3 to 4.",
                "PSR": "Medium High",
            },
            {
                "forecastDate": "20260824",
                "forecastMaxtemp": {"value": 31, "unit": "C"},
                "forecastMintemp": {"value": 26, "unit": "C"},
                "forecastMaxrh": {"value": 95, "unit": "percent"},
                "forecastMinrh": {"value": 75, "unit": "percent"},
                "forecastWind": "South force 4 to 5.",
                "PSR": "High",
            },
        ],
    }


def test_parse_current_observations(sample_rhrread_payload: dict[str, Any]) -> None:
    """Verify parsing and authoritative station tagging."""
    collector = HKOCollector()
    observations = collector.parse_current_observations(
        sample_rhrread_payload, enforce_time_check=False
    )

    assert len(observations) == 3

    # Find authoritative station observation
    hko_obs = next(obs for obs in observations if obs.station == "Hong Kong Observatory")
    assert hko_obs.is_authoritative is True
    assert hko_obs.temperature == 31.2
    assert hko_obs.humidity == 78.0
    assert hko_obs.rainfall == 0.0

    # Non-authoritative stations
    other_obs = next(obs for obs in observations if obs.station == "King's Park")
    assert other_obs.is_authoritative is False
    assert other_obs.temperature == 30.8


def test_parse_9day_forecast(sample_fnd_payload: dict[str, Any]) -> None:
    """Verify parsing 9-day forecast entries into WeatherForecast models."""
    collector = HKOCollector()
    forecasts = collector.parse_9day_forecast(sample_fnd_payload)

    assert len(forecasts) == 2

    fc1 = forecasts[0]
    assert fc1.target_date == date(2026, 8, 23)
    assert fc1.forecast_max_temperature == 32.0
    assert fc1.forecast_min_temperature == 27.0
    assert fc1.rain_probability == 0.70  # Medium High
    assert fc1.source == "hko_9day"

    fc2 = forecasts[1]
    assert fc2.target_date == date(2026, 8, 24)
    assert fc2.forecast_max_temperature == 31.0
    assert fc2.rain_probability == 0.90  # High


def test_data_quality_rejection_on_extreme_temperature(
    sample_rhrread_payload: dict[str, Any],
) -> None:
    """Verify corrupted / unphysical temperatures (>50°C) are skipped with data quality checks."""
    collector = HKOCollector()
    sample_rhrread_payload["temperature"]["data"].append(
        {"place": "Corrupt Station", "value": 99.9, "unit": "C"}
    )
    observations = collector.parse_current_observations(
        sample_rhrread_payload, enforce_time_check=False
    )

    # Corrupt station should be excluded
    stations = [obs.station for obs in observations]
    assert "Corrupt Station" not in stations
    assert len(observations) == 3


def test_data_quality_error_on_empty_payload() -> None:
    """Verify DataQualityError raised when structure is fundamentally corrupted."""
    collector = HKOCollector()
    with pytest.raises(DataQualityError):
        collector.parse_current_observations({"bad_key": True}, enforce_time_check=False)


def test_ingest_observations_idempotency(
    db_session: Session, sample_rhrread_payload: dict[str, Any], tmp_path: Any
) -> None:
    """Verify multiple ingestion runs of identical observation payload do not duplicate rows."""
    collector = HKOCollector()
    inserted_first = collector.ingest_current_observations(
        db_session, sample_rhrread_payload, archive_raw=False
    )
    assert inserted_first == 3

    total_count = db_session.query(WeatherObservation).count()
    assert total_count == 3

    # Ingest again
    inserted_second = collector.ingest_current_observations(
        db_session, sample_rhrread_payload, archive_raw=False
    )
    assert inserted_second == 0
    assert db_session.query(WeatherObservation).count() == 3


def test_ingest_forecast_idempotency(
    db_session: Session, sample_fnd_payload: dict[str, Any]
) -> None:
    """Verify multiple ingestion runs of identical forecast payload do not duplicate records."""
    collector = HKOCollector()
    inserted_first = collector.ingest_9day_forecast(
        db_session, sample_fnd_payload, archive_raw=False
    )
    assert inserted_first == 2

    assert db_session.query(WeatherForecast).count() == 2

    # Ingest again with same revision timestamp
    inserted_second = collector.ingest_9day_forecast(
        db_session, sample_fnd_payload, archive_raw=False
    )
    assert inserted_second == 0
    assert db_session.query(WeatherForecast).count() == 2
