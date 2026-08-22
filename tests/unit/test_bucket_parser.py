"""Unit tests for BucketParser and temperature bucket schema normalizer."""

from datetime import date

import pytest

from app.collectors.bucket_parser import BucketParser, ParsedBucket
from app.collectors.validators import DataQualityError


def test_parse_lower_open_buckets() -> None:
    """Test parsing various lower open bound representations."""
    variants = [
        "<=30°C",
        "<= 30°C",
        "30°C or below",
        "30 or lower",
        "under 30°C",
        "<30",
        "below 30 degrees",
    ]
    for label in variants:
        bucket = BucketParser.parse_bucket(label)
        assert bucket.low is None
        assert bucket.high == 30.0
        assert bucket.is_open_lower is True
        assert bucket.is_open_upper is False


def test_parse_upper_open_buckets() -> None:
    """Test parsing various upper open bound representations."""
    variants = [
        ">=34°C",
        ">= 34°C",
        "34°C or above",
        "34 or higher",
        "over 34°C",
        ">34",
        "34+°C",
        "34+",
    ]
    for label in variants:
        bucket = BucketParser.parse_bucket(label)
        assert bucket.low == 34.0
        assert bucket.high is None
        assert bucket.is_open_lower is False
        assert bucket.is_open_upper is True


def test_parse_discrete_range_buckets() -> None:
    """Test parsing interval / range buckets."""
    variants = ["31-32°C", "31 - 32°C", "31 to 32°C", "31°C to 32°C", "31–32", "31.5 to 32.5°C"]
    for label in variants:
        bucket = BucketParser.parse_bucket(label)
        assert bucket.low is not None
        assert bucket.high is not None
        assert bucket.is_open_lower is False
        assert bucket.is_open_upper is False

    b1 = BucketParser.parse_bucket("31-32°C")
    assert b1.low == 31.0
    assert b1.high == 32.0


def test_parse_single_degree_buckets() -> None:
    """Test parsing single degree integer buckets."""
    b = BucketParser.parse_bucket("31°C")
    assert b.low == 31.0
    assert b.high == 31.0
    assert b.is_open_lower is False
    assert b.is_open_upper is False


def test_schema_drift_detection() -> None:
    """Verify DataQualityError raised on unrecognized outcome phrasing (Section 9.1)."""
    with pytest.raises(DataQualityError) as exc_info:
        BucketParser.parse_bucket("Very hot sunny day")
    assert "schema drift" in str(exc_info.value).lower()

    with pytest.raises(DataQualityError):
        BucketParser.parse_bucket("")


def test_parse_full_market_schema() -> None:
    """Test parsing a complete multi-outcome market bucket schema."""
    outcomes = ["<=29°C", "30°C", "31-32°C", "33°C", ">=34°C"]
    parsed_buckets = BucketParser.parse_bucket_schema(outcomes)
    assert len(parsed_buckets) == 5

    assert parsed_buckets[0] == ParsedBucket("<=29°C", None, 29.0, True, False)
    assert parsed_buckets[1] == ParsedBucket("30°C", 30.0, 30.0, False, False)
    assert parsed_buckets[2] == ParsedBucket("31-32°C", 31.0, 32.0, False, False)
    assert parsed_buckets[3] == ParsedBucket("33°C", 33.0, 33.0, False, False)
    assert parsed_buckets[4] == ParsedBucket(">=34°C", 34.0, None, False, True)


def test_extract_target_date() -> None:
    """Test target date extraction from questions and slugs."""
    q1 = "What will the highest temperature in Hong Kong be on August 23, 2026?"
    assert BucketParser.extract_target_date(q1) == date(2026, 8, 23)

    q2 = "Hong Kong High Temperature on Sep 1st 2026"
    assert BucketParser.extract_target_date(q2) == date(2026, 9, 1)

    slug_iso = "hk-high-temp-2026-08-25"
    assert BucketParser.extract_target_date("High Temp in HK", slug=slug_iso) == date(2026, 8, 25)
