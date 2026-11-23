"""Shared data contracts for source acquisition, evidence and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import hashlib
import json
from typing import Any, Mapping, Sequence

JsonRecord = Mapping[str, Any]


@dataclass(frozen=True)
class RawPage:
    source: str
    url: str
    parameters: Mapping[str, str]
    fetched_at: datetime
    sha256: str
    status: int
    headers: Mapping[str, str]
    licence_identity: str | None
    path: str | None
    attempt: int
    data_mode: str


@dataclass(frozen=True)
class LicenceVerification:
    status: str  # verified, unknown, incompatible
    verified_at: datetime
    metadata_urls: tuple[str, ...] = ()
    licence_id: str | None = None
    licence_url: str | None = None
    organisation: str | None = None
    credit: str | None = None
    metadata: tuple[JsonRecord, ...] = ()
    reason: str | None = None

    @property
    def identity(self) -> str:
        """Bind captured pages to this run's actual metadata and verification."""
        value = {"status": self.status, "verified_at": self.verified_at.isoformat(),
                 "urls": self.metadata_urls, "metadata": self.metadata,
                 "licence_id": self.licence_id, "licence_url": self.licence_url}
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Provenance:
    source: str
    source_url: str | None = None
    licence: str = "CC BY 4.0"
    licence_url: str | None = "https://creativecommons.org/licenses/by/4.0/"
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
    status: str = "complete"  # complete, failed, disabled
    scope_hash: str = ""
    licence_verification: LicenceVerification | None = None
    raw_pages: tuple[RawPage, ...] = ()
    error: str | None = None
    scope: JsonRecord = field(default_factory=dict)
    counts: Mapping[str, int] = field(default_factory=dict)
    contract_status: str = "not_verified"


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
