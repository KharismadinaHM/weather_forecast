"""Polymarket temperature bucket schema parser and normalizer (Section 9.1)."""

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.collectors.validators import DataQualityError
from app.logging_config import get_logger

logger = get_logger("bucket_parser")


@dataclass(frozen=True)
class ParsedBucket:
    """Structured representation of a temperature outcome bucket."""

    raw_label: str
    low: float | None
    high: float | None
    is_open_lower: bool
    is_open_upper: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert parsed bucket to serializable dictionary."""
        return {
            "label": self.raw_label,
            "low": self.low,
            "high": self.high,
            "is_open_lower": self.is_open_lower,
            "is_open_upper": self.is_open_upper,
        }


class BucketParser:
    """Parser for diverse Polymarket temperature outcome bucket formats with drift detection."""

    # Regex patterns for matching common temperature bucket phrasing
    # 1. Lower open bounds: "<=30", "30 or below", "under 30", "<30"
    RE_LOWER_OPEN = re.compile(
        r"^(?:(?:<=|<|under|below|less\s+than)\s*([+-]?\d+(?:\.\d+)?)\s*(?:°?C|degrees?)?|"
        r"([+-]?\d+(?:\.\d+)?)\s*(?:°?C|degrees?)?\s*(?:or\s+(?:below|lower|less|under)))$",
        re.IGNORECASE,
    )

    # 2. Upper open bounds: ">=34", "34 or above", "over 34", ">34", "34+"
    RE_UPPER_OPEN = re.compile(
        r"^(?:(?:>=|>|over|above|more\s+than)\s*([+-]?\d+(?:\.\d+)?)\s*(?:°?C|degrees?)?|"
        r"([+-]?\d+(?:\.\d+)?)\s*(?:°?C|degrees?)?\s*(?:or\s+(?:above|higher|more|greater))|"
        r"([+-]?\d+(?:\.\d+)?)\s*\+\s*(?:°?C|degrees?)?)$",
        re.IGNORECASE,
    )

    # 3. Discrete range bounds: "31 - 32°C", "31 to 32°C", "31-32"
    RE_RANGE = re.compile(
        r"^([+-]?\d+(?:\.\d+)?)\s*(?:°?C)?\s*(?:-|–|—|to)\s*([+-]?\d+(?:\.\d+)?)\s*(?:°?C|degrees?)?$",
        re.IGNORECASE,
    )

    # 4. Single discrete degree: "31°C", "31 degrees", "31"
    RE_SINGLE = re.compile(
        r"^([+-]?\d+(?:\.\d+)?)\s*(?:°?C|degrees?)?$",
        re.IGNORECASE,
    )

    # Month name to number mapping for question date extraction
    MONTHS = {
        "january": 1,
        "jan": 1,
        "february": 2,
        "feb": 2,
        "march": 3,
        "mar": 3,
        "april": 4,
        "apr": 4,
        "may": 5,
        "june": 6,
        "jun": 6,
        "july": 7,
        "jul": 7,
        "august": 8,
        "aug": 8,
        "september": 9,
        "sep": 9,
        "sept": 9,
        "october": 10,
        "oct": 10,
        "november": 11,
        "nov": 11,
        "december": 12,
        "dec": 12,
    }

    @classmethod
    def parse_bucket(cls, label: str) -> ParsedBucket:
        """Parse outcome label into numeric bounds. Raises DataQualityError on schema drift."""
        clean_label = label.strip()
        if not clean_label:
            raise DataQualityError("Empty outcome label cannot be parsed")

        # 1. Test Lower Open Bound
        m_lower = cls.RE_LOWER_OPEN.match(clean_label)
        if m_lower:
            val_str = m_lower.group(1) or m_lower.group(2)
            high_val = float(val_str)
            return ParsedBucket(
                raw_label=clean_label,
                low=None,
                high=high_val,
                is_open_lower=True,
                is_open_upper=False,
            )

        # 2. Test Upper Open Bound
        m_upper = cls.RE_UPPER_OPEN.match(clean_label)
        if m_upper:
            val_str = m_upper.group(1) or m_upper.group(2) or m_upper.group(3)
            low_val = float(val_str)
            return ParsedBucket(
                raw_label=clean_label,
                low=low_val,
                high=None,
                is_open_lower=False,
                is_open_upper=True,
            )

        # 3. Test Range Bound
        m_range = cls.RE_RANGE.match(clean_label)
        if m_range:
            low_val = float(m_range.group(1))
            high_val = float(m_range.group(2))
            if low_val > high_val:
                low_val, high_val = high_val, low_val
            return ParsedBucket(
                raw_label=clean_label,
                low=low_val,
                high=high_val,
                is_open_lower=False,
                is_open_upper=False,
            )

        # 4. Test Single Degree Integer / Float
        m_single = cls.RE_SINGLE.match(clean_label)
        if m_single:
            single_val = float(m_single.group(1))
            return ParsedBucket(
                raw_label=clean_label,
                low=single_val,
                high=single_val,
                is_open_lower=False,
                is_open_upper=False,
            )

        # Schema Drift Detected!
        msg = f"Unknown temperature bucket schema drift detected for label: '{label}'"
        logger.error("Bucket schema drift", label=label)
        raise DataQualityError(msg, {"label": label, "error_type": "schema_drift"})

    @classmethod
    def parse_bucket_schema(cls, outcome_labels: list[str]) -> list[ParsedBucket]:
        """Parse and validate an entire set of outcome labels for a market."""
        if not outcome_labels:
            raise DataQualityError("Outcome labels list cannot be empty")

        parsed_list = [cls.parse_bucket(lbl) for lbl in outcome_labels]
        return parsed_list

    @classmethod
    def extract_target_date(
        cls, question: str, slug: str = "", default_year: int | None = None
    ) -> date:
        """Extract the target date from market question or slug."""
        text = f"{question} {slug}".lower()
        curr_year = default_year or datetime.now().year

        # Pattern: Month Day, Year (e.g. "August 23, 2026" or "Aug 23 2026")
        p_mdy = re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
            r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?",
            text,
        )
        if p_mdy:
            m_name = p_mdy.group(1)
            day = int(p_mdy.group(2))
            year = int(p_mdy.group(3)) if p_mdy.group(3) else curr_year
            month = cls.MONTHS[m_name]
            return date(year, month, day)

        # Pattern: ISO date YYYY-MM-DD or YYYYMMDD
        p_iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
        if p_iso:
            return date(int(p_iso.group(1)), int(p_iso.group(2)), int(p_iso.group(3)))

        # Fallback error
        raise DataQualityError(
            f"Could not extract target date from market question: '{question}'",
            {"question": question, "slug": slug},
        )
