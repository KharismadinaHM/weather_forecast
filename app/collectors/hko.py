"""Hong Kong Observatory (HKO) Open Data API client and ingestion pipeline."""

from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.collectors.validators import (
    DataQualityError,
    validate_humidity,
    validate_observation_timestamp,
    validate_rainfall,
    validate_station_name,
    validate_temperature,
)
from app.config.settings import Settings, get_settings
from app.logging_config import get_logger
from app.storage.models import WeatherDaily, WeatherForecast, WeatherObservation
from app.storage.raw import save_raw_response

logger = get_logger("hko_collector")


class HKOCollector:
    """Collector and parser for HKO Open Data API."""

    # Authoritative ground truth station designated for prediction markets
    AUTHORITATIVE_STATION: str = "Hong Kong Observatory"

    def __init__(self, settings: Settings | None = None, timeout: float = 10.0) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.HKO_BASE_URL
        self.timeout = timeout

    def _fetch_api(self, data_type: str, lang: str = "en") -> dict[str, Any]:
        """Fetch endpoint from HKO Open Data API with retries and timeout."""
        params = {"dataType": data_type, "lang": lang}
        transport = httpx.HTTPTransport(retries=3)
        with httpx.Client(transport=transport, timeout=self.timeout) as client:
            try:
                response = client.get(self.base_url, params=params)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise DataQualityError(
                        f"Unexpected JSON response structure for {data_type}: expected dict"
                    )
                return data
            except httpx.HTTPStatusError as e:
                logger.error(
                    "HKO API HTTP error", status_code=e.response.status_code, endpoint=data_type
                )
                raise
            except httpx.RequestError as e:
                logger.error("HKO API connection error", error=str(e), endpoint=data_type)
                raise

    def fetch_current_weather(self) -> dict[str, Any]:
        """Fetch Current Weather Report (rhrread)."""
        return self._fetch_api("rhrread")

    def fetch_9day_forecast(self) -> dict[str, Any]:
        """Fetch 9-Day Weather Forecast (fnd)."""
        return self._fetch_api("fnd")

    def fetch_local_forecast(self) -> dict[str, Any]:
        """Fetch Local Weather Forecast (flw)."""
        return self._fetch_api("flw")

    def parse_current_observations(
        self, raw_json: dict[str, Any], enforce_time_check: bool = True
    ) -> list[WeatherObservation]:
        """Parse rhrread response into validated WeatherObservation model instances."""
        observations: list[WeatherObservation] = []

        # 1. Parse observation timestamp
        update_time_str = raw_json.get("updateTime")
        if not update_time_str:
            raise DataQualityError("Missing updateTime in HKO rhrread payload")

        try:
            observed_at = datetime.fromisoformat(update_time_str)
            if enforce_time_check:
                observed_at = validate_observation_timestamp(observed_at)
        except ValueError as e:
            raise DataQualityError(f"Invalid updateTime format '{update_time_str}'") from e

        # Extract general meteorological metrics if available
        # Humidity
        humidity_val: float | None = None
        humidity_data = raw_json.get("humidity", {}).get("data", [])
        if humidity_data and isinstance(humidity_data, list):
            for h_item in humidity_data:
                if h_item.get("place") == self.AUTHORITATIVE_STATION or humidity_val is None:
                    try:
                        raw_h = float(h_item.get("value", 0))
                        humidity_val = validate_humidity(raw_h, context="rhrread.humidity")
                    except (ValueError, TypeError, DataQualityError) as err:
                        logger.warning("Skipping invalid humidity value", error=str(err))

        # Rainfall
        rainfall_val: float | None = None
        rainfall_data = raw_json.get("rainfall", {}).get("data", [])
        if rainfall_data and isinstance(rainfall_data, list):
            # Take main/max or default
            for r_item in rainfall_data:
                if r_item.get("main") == "TRUE" or rainfall_val is None:
                    try:
                        raw_r = float(r_item.get("max", 0))
                        rainfall_val = validate_rainfall(raw_r, context="rhrread.rainfall")
                    except (ValueError, TypeError, DataQualityError) as err:
                        logger.warning("Skipping invalid rainfall value", error=str(err))

        # Weather condition
        weather_condition: str | None = None
        special_tips = raw_json.get("specialWxTips")
        if special_tips and isinstance(special_tips, list) and len(special_tips) > 0:
            weather_condition = str(special_tips[0])[:100]

        # 2. Iterate stations and parse temperatures
        temp_list = raw_json.get("temperature", {}).get("data", [])
        if not temp_list or not isinstance(temp_list, list):
            raise DataQualityError("Missing temperature.data in HKO rhrread payload")

        for item in temp_list:
            raw_place = item.get("place")
            raw_val = item.get("value")

            if not raw_place or raw_val is None:
                logger.warning("Skipping observation with missing place or temperature", item=item)
                continue

            try:
                station = validate_station_name(str(raw_place), context="rhrread.station")
                temp = validate_temperature(float(raw_val), context=f"rhrread.{station}")
            except (ValueError, TypeError, DataQualityError) as err:
                logger.warning(
                    "Data quality check failed for station observation; SKIP record",
                    error=str(err),
                    station=raw_place,
                )
                continue

            is_auth = station == self.AUTHORITATIVE_STATION

            obs = WeatherObservation(
                observed_at=observed_at,
                station=station,
                is_authoritative=is_auth,
                temperature=temp,
                humidity=humidity_val if is_auth else None,
                rainfall=rainfall_val if is_auth else None,
                pressure=None,  # Not directly present in basic rhrread
                wind_speed=None,
                wind_direction=None,
                weather_condition=weather_condition if is_auth else None,
                source="hko",
            )
            observations.append(obs)

        if not observations:
            raise DataQualityError("No valid observations could be parsed from HKO rhrread payload")

        return observations

    def parse_9day_forecast(self, raw_json: dict[str, Any]) -> list[WeatherForecast]:
        """Parse fnd response into validated WeatherForecast instances (anti-leakage compliant)."""
        forecasts: list[WeatherForecast] = []

        update_time_str = raw_json.get("updateTime")
        if not update_time_str:
            raise DataQualityError("Missing updateTime in HKO fnd payload")

        try:
            forecast_created_at = datetime.fromisoformat(update_time_str)
        except ValueError as e:
            raise DataQualityError(f"Invalid updateTime format '{update_time_str}'") from e

        forecast_list = raw_json.get("weatherForecast", [])
        if not forecast_list or not isinstance(forecast_list, list):
            raise DataQualityError("Missing weatherForecast list in HKO fnd payload")

        for item in forecast_list:
            raw_date_str = item.get("forecastDate")
            if not raw_date_str or len(str(raw_date_str)) != 8:
                logger.warning("Skipping forecast item with invalid date format", item=item)
                continue

            try:
                t_year = int(raw_date_str[:4])
                t_month = int(raw_date_str[4:6])
                t_day = int(raw_date_str[6:8])
                target_date = date(t_year, t_month, t_day)
            except ValueError as err:
                logger.warning(
                    "Invalid target date; SKIP forecast item", error=str(err), raw_date=raw_date_str
                )
                continue

            # Temperature values
            max_temp_obj = item.get("forecastMaxtemp", {})
            min_temp_obj = item.get("forecastMintemp", {})
            max_rh_obj = item.get("forecastMaxrh", {})
            min_rh_obj = item.get("forecastMinrh", {})

            try:
                max_temp = validate_temperature(
                    float(max_temp_obj.get("value")) if "value" in max_temp_obj else None,
                    context="forecast.max_temp",
                )
                min_temp = validate_temperature(
                    float(min_temp_obj.get("value")) if "value" in min_temp_obj else None,
                    context="forecast.min_temp",
                )
                max_rh = validate_humidity(
                    float(max_rh_obj.get("value")) if "value" in max_rh_obj else None,
                    context="forecast.max_rh",
                )
                min_rh = validate_humidity(
                    float(min_rh_obj.get("value")) if "value" in min_rh_obj else None,
                    context="forecast.min_rh",
                )
            except (ValueError, TypeError, DataQualityError) as err:
                logger.warning(
                    "Data quality check failed for forecast entry; SKIP record",
                    error=str(err),
                    target_date=str(target_date),
                )
                continue

            # Mean humidity estimate
            avg_humidity: float | None = None
            if max_rh is not None and min_rh is not None:
                avg_humidity = (max_rh + min_rh) / 2.0

            wind_desc = item.get("forecastWind")
            wind_str = str(wind_desc)[:200] if wind_desc else None

            # Probability of Significant Rain (PSR) string mapping
            psr = item.get("PSR")
            psr_prob: float | None = None
            if psr == "Low":
                psr_prob = 0.15
            elif psr == "Medium Low":
                psr_prob = 0.35
            elif psr == "Medium":
                psr_prob = 0.50
            elif psr == "Medium High":
                psr_prob = 0.70
            elif psr == "High":
                psr_prob = 0.90

            forecast = WeatherForecast(
                forecast_created_at=forecast_created_at,
                target_date=target_date,
                target_hour=None,
                forecast_temperature=None,
                forecast_min_temperature=min_temp,
                forecast_max_temperature=max_temp,
                humidity=avg_humidity,
                rain_probability=psr_prob,
                wind=wind_str,
                source="hko_9day",
            )
            forecasts.append(forecast)

        if not forecasts:
            raise DataQualityError("No valid forecast entries could be parsed from HKO fnd payload")

        return forecasts

    def parse_daily_records(self, raw_records: list[dict[str, Any]]) -> list[WeatherDaily]:
        """Parse daily climatological records into validated WeatherDaily instances."""
        daily_list: list[WeatherDaily] = []

        for row in raw_records:
            try:
                record_date = (
                    row["date"]
                    if isinstance(row["date"], date)
                    else date.fromisoformat(str(row["date"]))
                )
                station = validate_station_name(
                    str(row.get("station", self.AUTHORITATIVE_STATION)), context="daily.station"
                )
                max_t = validate_temperature(
                    float(row["max_temperature"])
                    if row.get("max_temperature") is not None
                    else None,
                    context="daily.max_t",
                )
                min_t = validate_temperature(
                    float(row["min_temperature"])
                    if row.get("min_temperature") is not None
                    else None,
                    context="daily.min_t",
                )
                mean_t = validate_temperature(
                    float(row["mean_temperature"])
                    if row.get("mean_temperature") is not None
                    else None,
                    context="daily.mean_t",
                )
                rainfall = validate_rainfall(
                    float(row["total_rainfall"]) if row.get("total_rainfall") is not None else None,
                    context="daily.rainfall",
                )

                daily = WeatherDaily(
                    date=record_date,
                    station=station,
                    max_temperature=max_t,
                    min_temperature=min_t,
                    mean_temperature=mean_t,
                    total_rainfall=rainfall,
                )
                daily_list.append(daily)
            except (KeyError, ValueError, TypeError, DataQualityError) as err:
                logger.warning("Skipping invalid daily record", error=str(err), record=row)
                continue

        return daily_list

    def ingest_current_observations(
        self, session: Session, raw_data: dict[str, Any] | None = None, archive_raw: bool = True
    ) -> int:
        """Fetch and persist current observations idempotently."""
        if raw_data is None:
            raw_data = self.fetch_current_weather()

        if archive_raw:
            save_raw_response("hko", "rhrread", raw_data)

        observations = self.parse_current_observations(raw_data)
        inserted_count = 0

        for obs in observations:
            # Idempotency check on (observed_at, station)
            exists = (
                session.query(WeatherObservation)
                .filter_by(observed_at=obs.observed_at, station=obs.station)
                .first()
            )
            if not exists:
                session.add(obs)
                inserted_count += 1
            else:
                # Update existing observation if values became available
                exists.temperature = obs.temperature
                exists.humidity = obs.humidity or exists.humidity
                exists.rainfall = obs.rainfall or exists.rainfall
                exists.is_authoritative = obs.is_authoritative

        session.commit()
        logger.info(
            "Ingested HKO current observations", inserted=inserted_count, total=len(observations)
        )
        return inserted_count

    def ingest_9day_forecast(
        self, session: Session, raw_data: dict[str, Any] | None = None, archive_raw: bool = True
    ) -> int:
        """Fetch and persist 9-day forecasts preserving revision history (Section 8)."""
        if raw_data is None:
            raw_data = self.fetch_9day_forecast()

        if archive_raw:
            save_raw_response("hko", "fnd", raw_data)

        forecasts = self.parse_9day_forecast(raw_data)
        inserted_count = 0

        for fc in forecasts:
            # Check unique constraint (forecast_created_at, target_date, source)
            exists = (
                session.query(WeatherForecast)
                .filter_by(
                    forecast_created_at=fc.forecast_created_at,
                    target_date=fc.target_date,
                    source=fc.source,
                )
                .first()
            )
            if not exists:
                session.add(fc)
                inserted_count += 1

        session.commit()
        logger.info("Ingested HKO 9-day forecast", inserted=inserted_count, total=len(forecasts))
        return inserted_count

    def ingest_daily_records(self, session: Session, raw_records: list[dict[str, Any]]) -> int:
        """Persist historical daily weather ground truth."""
        daily_records = self.parse_daily_records(raw_records)
        inserted_count = 0

        for rec in daily_records:
            exists = (
                session.query(WeatherDaily).filter_by(date=rec.date, station=rec.station).first()
            )
            if not exists:
                session.add(rec)
                inserted_count += 1
            else:
                exists.max_temperature = rec.max_temperature
                exists.min_temperature = rec.min_temperature
                exists.mean_temperature = rec.mean_temperature
                exists.total_rainfall = rec.total_rainfall

        session.commit()
        logger.info("Ingested HKO daily records", inserted=inserted_count, total=len(daily_records))
        return inserted_count
