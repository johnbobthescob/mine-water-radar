"""Small shared data contracts; source-specific behavior lives in later modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Sequence

JsonRecord = Mapping[str, Any]


@dataclass(frozen=True)
class Provenance:
    source: str
    source_url: str | None = None
    licence: str = "CC BY 4.0"
    licence_url: str = "https://creativecommons.org/licenses/by/4.0/"
    captured_at: datetime | None = None
    observed_at: datetime | None = None
    sha256: str | None = None
    data_mode: str = "live"
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class Coverage:
    scope: str
    complete: bool
    expected_count: int | None = None
    received_count: int | None = None
    exceeded_transfer_limit: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceBatch:
    source: str
    records: Sequence[JsonRecord]
    provenance: Provenance
    coverage: Coverage


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source: str
    record_id: str
    field: str
    value: Any
    source_date: date | None = None
    date_precision: str | None = None
    observed_at: datetime | None = None
    url: str | None = None
    match_method: str | None = None
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScoreView:
    project_id: str
    score: int
    tier: str
    breakdown: Mapping[str, int] = field(default_factory=dict)
    caps: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportView:
    project_id: str
    project_name: str
    operator: str | None
    operator_status: str
    stage: str | None
    score: ScoreView | None
    evidence: tuple[Evidence, ...] = ()
    contract_status: str = "not_verified"
    data_mode: str = "live"
    coverage: tuple[Coverage, ...] = ()
    attributions: tuple[str, ...] = ()
