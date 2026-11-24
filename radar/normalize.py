"""Lossless source values alongside conservative, typed comparison values.

Only registry fields enter business content. Transport IDs and extraction times
never enter a change hash; raw source values remain available for audit.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from typing import Any, Mapping

from .models import Provenance
from .sources import epbc, minedex, tenements, wamex
from .sources.registry import SOURCES

NORMALIZATION_VERSION = 1


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=_json_default)


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def semantic_hash(value: Any) -> str:
    """Canonical unordered collections: input ordering is never intelligence."""
    def canonical(item):
        if isinstance(item, Mapping):
            return {key: canonical(val) for key, val in sorted(item.items())}
        if isinstance(item, (list, tuple, set, frozenset)):
            values = [canonical(val) for val in item]
            return sorted(values, key=stable_json)
        return item
    return hashlib.sha256(stable_json(canonical(value)).encode()).hexdigest()


def utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("an aware timestamp is required")
    return value.astimezone(timezone.utc)


def utc_iso(value: datetime | str) -> str:
    return utc(value).isoformat()


@dataclass(frozen=True)
class SourceDate:
    value: str | None
    kind: str
    precision: str | None
    raw: Any = None
    valid: bool = True
    issue: str | None = None


def normalize_date(value: Any, kind: str, *, year_only: bool = False) -> SourceDate:
    """Never substitute an observation date or manufacture a day for a year."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return SourceDate(None, kind, None, value)
    try:
        if isinstance(value, bool):
            raise ValueError("boolean date")
        if year_only:
            number = float(value)
            if not math.isfinite(number) or not number.is_integer() or not 1 <= number <= 9999:
                raise ValueError("invalid year")
            return SourceDate(f"{int(number):04d}", kind, "year", value)
        if isinstance(value, (int, float)):
            if not math.isfinite(value):
                raise ValueError("nonfinite epoch")
            instant = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=value)
            return SourceDate(instant.isoformat(), kind, "millisecond", value)
        if not isinstance(value, str):
            raise ValueError("unsupported date value")
        text = value.strip()
        if len(text) == 10:
            return SourceDate(date.fromisoformat(text).isoformat(), kind, "day", value)
        instant = utc(text)
        precision = "microsecond" if instant.microsecond else "second"
        return SourceDate(instant.isoformat(), kind, precision, value)
    except (ValueError, TypeError, OverflowError) as exc:
        return SourceDate(None, kind, None, value, False, str(exc))


@dataclass(frozen=True)
class AttributedRole:
    name: str
    role: str
    date: SourceDate | None = None


@dataclass(frozen=True)
class NormalizedRecord:
    source: str
    business_key: str
    raw: Mapping[str, Any]
    values: Mapping[str, Any]
    dates: Mapping[str, SourceDate]
    source_date: SourceDate
    semantic_hash: str
    citation_url: str
    project_id: str | None = None
    provenance: Provenance | None = None
    operator: str | None = None
    operator_status: str = "Unknown — not supplied by current MINEDEX layer"
    holders: tuple[AttributedRole, ...] = ()
    reporting_operators: tuple[AttributedRole, ...] = ()
    contract_status: str = "not_verified"

    def to_dict(self) -> dict:
        return asdict(self)


_DATE_FIELDS = {
    "minedex": {"extract_da": "extraction"},
    "tenements": {"extract_da": "extraction", "grantdate": "tenure_grant",
                  "startdate": "tenure_start", "enddate": "tenure_end"},
    "wamex": {"date_released": "release", "report_year": "report_year"},
    "epbc": {"YEAR": "referral_year"},
}
_PRIMARY_DATE = {"minedex": "extract_da", "tenements": "extract_da",
                 "wamex": "date_released", "epbc": "YEAR"}
_CITATIONS = {"minedex": minedex.citation, "tenements": tenements.citation,
              "wamex": wamex.citation, "epbc": epbc.citation}


def normalize_record(source: str, raw: Mapping[str, Any], *,
                     provenance: Provenance | None = None) -> NormalizedRecord:
    spec = SOURCES[source]
    key = raw.get(spec.key)
    if isinstance(key, bool) or not isinstance(key, (str, int)) or not str(key).strip():
        raise ValueError(f"{source}: missing/invalid business key {spec.key}")
    key = str(key).strip()
    # Addresses in the old recorded tenement envelope are not product fields.
    original = {name: raw[name] for name in spec.fields if name in raw}
    values = {name: (" ".join(val.split()) if isinstance(val, str) else val)
              for name, val in original.items()}
    values[spec.key] = key
    dates = {name: normalize_date(original.get(name), kind, year_only=name in {"YEAR", "report_year"})
             for name, kind in _DATE_FIELDS[source].items()}
    business = {name: val for name, val in values.items() if name != "extract_da"}
    for name, val in dates.items():
        if name != "extract_da" and name in business:
            business[name] = {"value": val.value, "kind": val.kind, "precision": val.precision,
                              "invalid_raw": val.raw if not val.valid else None,
                              "missing_raw": val.raw if val.value is None else None}
    project_id = None
    if source == "minedex":
        code = values.get("proj_code")
        project_id = "minedex:" + str(code).strip() if code is not None and str(code).strip() else "site:" + key
        business["project_id"] = project_id
    holders = tuple(AttributedRole(values[f"holder{i}"], "tenement holder at sampled site", dates["extract_da"])
                    for i in range(1, 10) if values.get(f"holder{i}")) if source == "tenements" else ()
    reporting = (AttributedRole(values["operator"], "WAMEX reporting operator", dates["report_year"]),) if source == "wamex" and values.get("operator") else ()
    return NormalizedRecord(source, key, original, values, dates, dates[_PRIMARY_DATE[source]],
                            semantic_hash(business), _CITATIONS[source]({**original, spec.key: key}),
                            project_id, provenance, holders=holders, reporting_operators=reporting)


def normalize_records(source: str, records, *, provenance: Provenance | None = None) -> tuple[NormalizedRecord, ...]:
    unique = {}
    for raw in records:
        record = normalize_record(source, raw, provenance=provenance)
        previous = unique.get(record.business_key)
        if previous is not None:
            # Compare all supplied business fields, including extraction dates.
            # Equal change hashes alone cannot establish equal source records.
            def content(item):
                return {**item.raw, SOURCES[source].key: item.business_key}
            if stable_json(content(previous)) != stable_json(content(record)):
                raise ValueError(f"{source}: conflicting duplicate business key: {record.business_key}")
        else:
            unique[record.business_key] = record
    return tuple(unique[key] for key in sorted(unique))


def project_semantic_hash(records) -> str:
    """Include site identities/membership, without aggregating stages or linking."""
    return semantic_hash([{ "site_code": record.business_key, "project_id": record.project_id,
                            "semantic_hash": record.semantic_hash} for record in records])
