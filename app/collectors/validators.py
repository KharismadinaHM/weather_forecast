"""Data quality validators for weather observations and forecasts (Section 17)."""

from datetime import UTC, datetime
from typing import Any

from app.logging_config import get_logger

logger = get_logger("data_quality")


class DataQualityError(ValueError):
    """Exception raised when meteorological data fails validation."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


def validate_temperature(temp: float | None, context: str = "") -> float | None:
    """Validate temperature is within realistic Hong Kong bounds (-10°C to 50°C)."""
    if temp is None:
        return None
    if not (-10.0 <= temp <= 50.0):
        msg = f"Temperature {temp}°C out of realistic bounds (-10 to 50°C) in {context}"
        logger.warning(
            "Data quality check failed", metric="temperature", value=temp, context=context
        )
        raise DataQualityError(msg, {"metric": "temperature", "value": temp, "context": context})
    return temp


def validate_humidity(humidity: float | None, context: str = "") -> float | None:
    """Validate relative humidity is between 0% and 100%."""
    if humidity is None:
        return None
    if not (0.0 <= humidity <= 100.0):
        msg = f"Humidity {humidity}% out of valid range (0-100%) in {context}"
        logger.warning(
            "Data quality check failed", metric="humidity", value=humidity, context=context
        )
        raise DataQualityError(msg, {"metric": "humidity", "value": humidity, "context": context})
    return humidity


def validate_rainfall(rainfall: float | None, context: str = "") -> float | None:
    """Validate rainfall amount is non-negative and plausible (0 to 1000 mm)."""
    if rainfall is None:
        return None
    if rainfall < 0.0 or rainfall > 1000.0:
        msg = f"Rainfall {rainfall} mm invalid (must be 0-1000 mm) in {context}"
        logger.warning(
            "Data quality check failed", metric="rainfall", value=rainfall, context=context
        )
        raise DataQualityError(msg, {"metric": "rainfall", "value": rainfall, "context": context})
    return rainfall


def validate_pressure(pressure: float | None, context: str = "") -> float | None:
    """Validate atmospheric pressure is within realistic bounds (850 to 1080 hPa)."""
    if pressure is None:
        return None
    if not (850.0 <= pressure <= 1080.0):
        msg = f"Pressure {pressure} hPa out of realistic bounds (850-1080 hPa) in {context}"
        logger.warning(
            "Data quality check failed", metric="pressure", value=pressure, context=context
        )
        raise DataQualityError(msg, {"metric": "pressure", "value": pressure, "context": context})
    return pressure


def validate_station_name(station: str, context: str = "") -> str:
    """Validate station identifier is non-empty and well-formed."""
    clean_station = station.strip()
    if not clean_station or len(clean_station) > 100:
        msg = f"Invalid station name '{station}' in {context}"
        logger.warning(
            "Data quality check failed", metric="station", value=station, context=context
        )
        raise DataQualityError(msg, {"metric": "station", "value": station, "context": context})
    return clean_station


def validate_observation_timestamp(dt: datetime, max_future_seconds: int = 300) -> datetime:
    """Ensure observation timestamp is not significantly in the future."""
    now = datetime.now(UTC)
    # Ensure dt is timezone aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    diff = (dt - now).total_seconds()
    if diff > max_future_seconds:
        msg = f"Observation timestamp {dt.isoformat()} is in the future by {diff:.1f}s"
        logger.warning("Data quality check failed", metric="observed_at", value=dt.isoformat())
        raise DataQualityError(
            msg, {"metric": "observed_at", "value": dt.isoformat(), "skew_seconds": diff}
        )
    return dt
