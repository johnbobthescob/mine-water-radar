"""Bounded release subset only; reporting operators may be historical."""
from datetime import date, datetime, timedelta, timezone
import re
from urllib.parse import urlencode

from .arcgis import ArcGISClient
from .registry import WATER_TERMS, wamex_where

# Acquisition includes uncertain/negated matches; evidence admission belongs to M5.
_TERMS = re.compile(r"\b(?:dewater(?:ing)?|borefields?|" + "|".join(
    re.escape(term) for term in WATER_TERMS if term not in {"dewater", "borefield"}) + r")\b", re.I)


def eligible(record, as_of: date):
    value = record.get("date_released")
    try:
        if isinstance(value, bool):
            return False
        if isinstance(value, (float, int)):
            released = (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=value)).date()
        elif isinstance(value, str):
            released = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        else:
            return False
    except (ValueError, OverflowError):
        return False
    text = " ".join(str(record.get(field) or "") for field in ("title", "abstract"))
    return as_of - timedelta(days=730) <= released <= as_of and bool(_TERMS.search(text))


def citation(record):
    return "https://wamex.dmp.wa.gov.au/Wamex/Search/ReportDetails?" + urlencode({"ANumber": record["anumber"]})


def fetch(http, *, as_of: date):
    # ArcGIS standardized SQL TIMESTAMP literal is supported by the REST path.
    # Unsupported SQL fails this optional scope; never fall back to the archive.
    return ArcGISClient(http, "wamex").fetch({"where": wamex_where(as_of)},
                                            recheck=lambda record: eligible(record, as_of))
