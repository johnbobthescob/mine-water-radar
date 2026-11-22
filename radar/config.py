"""Shared configuration defaults for the local radar pipeline."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PERTH = ZoneInfo("Australia/Perth")
DEFAULT_DB = Path("data/radar.sqlite")
DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_OUTPUT_DIR = Path("out")
DEFAULT_TENEMENT_SITE_LIMIT = 100
DEFAULT_REPORT_DAYS = 7


def perth_today() -> date:
    """Return the current calendar date in the product's reporting timezone."""
    return datetime.now(PERTH).date()
