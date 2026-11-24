"""SQLite history and transaction boundaries for ingestion and later milestones.

Writers require an explicit transaction. Nested transactions use savepoints so
M4/M5 can participate in ingestion without committing the enclosing run.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import sqlite3
from typing import Any

from .config import PERTH
from .normalize import stable_json, utc, utc_iso

SCHEMA_VERSION = 1
MODES = {"live", "recorded_fixture", "synthetic_fixture"}


@dataclass(frozen=True)
class ScopeView:
    source: str
    scope_hash: str
    availability: str  # current, partial, unavailable, suppressed
    fresh: bool  # acquisition freshness only; scoring must apply date gates
    stale: bool
    batch: dict | None
    records: tuple[dict, ...]
    reason: str | None = None


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._savepoint = 0
        try:
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError("unversioned nonempty database; refusing to overwrite")
                sql = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
                try:
                    self.connection.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
                except BaseException:
                    if self.connection.in_transaction:
                        self.connection.rollback()
                    raise
            elif version != SCHEMA_VERSION:
                raise ValueError(f"unsupported schema version {version}; expected {SCHEMA_VERSION}")
        except BaseException:
            self.close()
            raise

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def transaction(self):
        nested = self.connection.in_transaction
        self._savepoint += 1
        name = f"radar_{self._savepoint}"
        self.connection.execute(f"SAVEPOINT {name}" if nested else "BEGIN IMMEDIATE")
        try:
            yield self
            self.connection.execute(f"RELEASE SAVEPOINT {name}" if nested else "COMMIT")
        except BaseException:
            if self.connection.in_transaction:
                if nested:
                    self.connection.execute(f"ROLLBACK TO SAVEPOINT {name}")
                    self.connection.execute(f"RELEASE SAVEPOINT {name}")
                else:
                    self.connection.execute("ROLLBACK")
            raise

    def require_transaction(self):
        if not self.connection.in_transaction:
            raise RuntimeError("write requires an explicit Store.transaction()")

    def bind_mode(self, mode: str):
        self.require_transaction()
        if mode not in MODES:
            raise ValueError("unknown provenance mode")
        previous = self.connection.execute("SELECT data_mode FROM database_state WHERE singleton=1").fetchone()[0]
        if previous is not None and previous != mode:
            raise ValueError(f"cannot mix provenance modes: {previous} and {mode}")
        self.connection.execute("UPDATE database_state SET data_mode=? WHERE singleton=1", (mode,))

    def run(self, run_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("unknown run: " + run_id)
        return dict(row)

    def latest_usable_run(self, *, as_of: date | None = None,
                          observed_at_or_before=None) -> dict | None:
        rows = self.connection.execute(
            "SELECT * FROM runs WHERE usable=1 AND status IN ('complete','degraded') "
            "ORDER BY observed_at DESC, rowid DESC").fetchall()
        for row in rows:
            if observed_at_or_before is not None and utc(row["observed_at"]) > utc(observed_at_or_before):
                continue
            if as_of is None or utc(row["observed_at"]).astimezone(PERTH).date() <= as_of:
                return dict(row)
        return None

    def validate_as_of(self, run_id: str, as_of: date):
        if as_of < utc(self.run(run_id)["observed_at"]).astimezone(PERTH).date():
            raise ValueError("as-of must not precede the selected run's observation date")

    def records(self, batch_id: str) -> tuple[dict, ...]:
        return tuple(dict(row) for row in self.connection.execute(
            "SELECT * FROM source_records WHERE batch_id=? ORDER BY business_key", (batch_id,)))

    def batches(self, run_id: str) -> tuple[dict, ...]:
        return tuple(dict(row) for row in self.connection.execute(
            "SELECT * FROM source_batches WHERE run_id=? ORDER BY source,scope_hash", (run_id,)))

    def latest_successful_batch(self, source: str, scope_hash: str, *, before_run_id: str | None = None) -> dict | None:
        """Audit/comparison history for exactly one source scope; partials excluded.

        Report callers use scope_view() instead, to apply availability/licensing.
        """
        params = [source, scope_hash]
        cutoff = ""
        if before_run_id is not None:
            cutoff = (" AND (r.observed_at < ? OR (r.observed_at=? AND r.rowid < "
                      "(SELECT rowid FROM runs WHERE id=?)))")
            observed = self.run(before_run_id)["observed_at"]
            params.extend((observed, observed, before_run_id))
        row = self.connection.execute(
            "SELECT b.* FROM source_batches b JOIN runs r ON r.id=b.run_id "
            "WHERE b.source=? AND b.scope_hash=? AND b.status='complete' AND b.complete=1 AND r.usable=1" +
            cutoff + " ORDER BY r.observed_at DESC,r.rowid DESC LIMIT 1", params).fetchone()
        return dict(row) if row else None

    def source_suppressed(self, source: str) -> bool:
        # Unknown licensing cannot undo an explicit incompatibility. Failed core
        # runs also carry licensing decisions, even though they are not usable.
        row = self.connection.execute(
            "SELECT b.licence_status FROM source_batches b JOIN runs r ON r.id=b.run_id "
            "WHERE b.source=? AND b.licence_status IN ('verified','incompatible') "
            "ORDER BY r.observed_at DESC,r.rowid DESC,b.rowid DESC LIMIT 1", (source,)).fetchone()
        return row is not None and row[0] == "incompatible"

    def scope_view(self, run_id: str, source: str, scope_hash: str, *, retain_stale=True) -> ScopeView:
        """Explicit unavailable scopes; retained context never becomes current.

        This is an audit/context view, not evidence admission or scoring. No
        content from an explicitly incompatible source is returned here.
        """
        if self.source_suppressed(source):
            return ScopeView(source, scope_hash, "suppressed", False, False, None, (), "incompatible licence")
        run = self.run(run_id)
        current = self.connection.execute(
            "SELECT * FROM source_batches WHERE run_id=? AND source=? AND scope_hash=?",
            (run_id, source, scope_hash)).fetchone()
        if current and run["usable"] and current["status"] == "complete" and current["complete"]:
            batch = dict(current)
            return ScopeView(source, scope_hash, "current", True, False, batch, self.records(batch["id"]))
        if current and current["status"] == "partial":
            batch = dict(current)
            return ScopeView(source, scope_hash, "partial", False, False, batch, self.records(batch["id"]),
                             "fixture:selected-records; incomplete research sample")
        previous = self.connection.execute(
            "SELECT b.* FROM source_batches b JOIN runs r ON r.id=b.run_id "
            "WHERE b.source=? AND b.scope_hash=? AND b.status='complete' AND b.complete=1 "
            "AND r.usable=1 AND (r.observed_at < ? OR (r.observed_at=? AND r.rowid <= "
            "(SELECT rowid FROM runs WHERE id=?))) "
            "ORDER BY r.observed_at DESC,r.rowid DESC LIMIT 1",
            (source, scope_hash, run["observed_at"], run["observed_at"], run_id)).fetchone() if retain_stale else None
        batch = dict(previous) if previous else None
        return ScopeView(source, scope_hash, "unavailable", False, bool(batch), batch,
                         self.records(batch["id"]) if batch else (),
                         (current["error"] or current["status"]) if current else "scope not queried in selected run")

    def ensure_project(self, project_id: str, observed_at):
        self.require_transaction()
        when = utc_iso(observed_at)
        self.connection.execute(
            "INSERT INTO projects(id,first_seen,last_seen) VALUES (?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET first_seen=min(first_seen,excluded.first_seen),"
            "last_seen=max(last_seen,excluded.last_seen)", (project_id, when, when))

    # The table/column identifiers below are internal constants, never input.
    # Public persistence methods accept only the fields declared for that table.
    _FIELDS = {
        "project_versions": "id run_id project_id title site_membership_json stage_distribution_json representative_stage representative_site semantic_hash status coverage_json freshness_json",
        "links": "id project_version_id source_record_id method supporting_reference confidence ambiguity_json scope_json",
        "evidence": "id evidence_key project_version_id source_record_id field value_json excerpt source_date_value source_date_kind source_date_precision observed_at url licence_id role validity_json",
        "changes": "id event_key project_id previous_version_id current_version_id event_type old_json new_json supporting_site_ids_json evidence_ids_json observed_at digest_eligible",
        "score_sets": "id run_id as_of rubric_version reviewed_evidence_hash completed_at status",
        "scores": "score_set_id project_version_id total tier positive_json negative_json caps_json evidence_ids_json change_ids_json reason",
    }

    def _insert(self, table: str, values: dict[str, Any]):
        self.require_transaction()
        fields = self._FIELDS[table].split()
        if set(values) != set(fields):
            raise ValueError(f"{table} fields mismatch: missing {set(fields)-set(values)}, extra {set(values)-set(fields)}")
        # JSON columns accept Python values, including strings as JSON scalars.
        params = [stable_json(values[name]) if name.endswith("_json")
                  else values[name] for name in fields]
        self.connection.execute(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})", params)

    def add_project_version(self, **values):
        self._insert("project_versions", values)

    def add_link(self, **values):
        self._insert("links", values)

    def add_evidence(self, **values):
        self._insert("evidence", values)

    def add_change(self, **values):
        """Return the original event without refreshing its first observation."""
        self.require_transaction()
        old = self.connection.execute("SELECT * FROM changes WHERE event_key=?", (values["event_key"],)).fetchone()
        if old:
            # Same identity must not silently overwrite a different event.
            for key, val in values.items():
                if key not in {"id", "observed_at"}:
                    val = stable_json(val) if key.endswith("_json") else val
                    if old[key] != val:
                        raise ValueError("conflicting change event key")
            return dict(old)
        self._insert("changes", values)
        return dict(self.connection.execute("SELECT * FROM changes WHERE event_key=?", (values["event_key"],)).fetchone())

    @contextmanager
    def score_set(self, *, score_set_id: str, run_id: str, as_of: date,
                  rubric_version: str, reviewed_evidence_hash: str, completed_at):
        """Build/replace a whole set atomically; exceptions restore the old set."""
        with self.transaction():
            self.validate_as_of(run_id, as_of)
            run = self.run(run_id)
            core = [batch for batch in self.batches(run_id) if batch["source"] == "minedex"]
            pending_core = (run["status"] == "ingesting" and len(core) == 1 and
                            core[0]["complete"] and core[0]["status"] == "complete" and
                            json.loads(core[0]["scope_json"]).get("where") == "1=1")
            if not (run["usable"] or pending_core):
                raise ValueError("scoring requires a usable run or a validated core ingestion transaction")
            old = self.connection.execute(
                "SELECT id FROM score_sets WHERE run_id=? AND as_of=? AND rubric_version=? AND reviewed_evidence_hash=?",
                (run_id, as_of.isoformat(), rubric_version, reviewed_evidence_hash)).fetchone()
            if old:
                self.connection.execute("DELETE FROM scores WHERE score_set_id=?", (old[0],))
                self.connection.execute("DELETE FROM score_sets WHERE id=?", (old[0],))
            self._insert("score_sets", dict(id=score_set_id, run_id=run_id, as_of=as_of.isoformat(),
                         rubric_version=rubric_version, reviewed_evidence_hash=reviewed_evidence_hash,
                         completed_at=None, status="building"))
            yield score_set_id
            expected = self.connection.execute("SELECT count(*) FROM project_versions WHERE run_id=?", (run_id,)).fetchone()[0]
            actual = self.connection.execute("SELECT count(*) FROM scores WHERE score_set_id=?", (score_set_id,)).fetchone()[0]
            if actual != expected:
                raise ValueError("incomplete score set")
            self.connection.execute("UPDATE score_sets SET status='complete',completed_at=? WHERE id=?",
                                    (utc_iso(completed_at), score_set_id))

    def add_score(self, **values):
        self.require_transaction()
        row = self.connection.execute("SELECT status FROM score_sets WHERE id=?", (values["score_set_id"],)).fetchone()
        if row is None or row[0] != "building":
            raise ValueError("scores require a building score set")
        self._insert("scores", values)

    def latest_score_set(self, run_id: str, as_of: date, rubric_version: str,
                         reviewed_evidence_hash: str) -> dict | None:
        self.validate_as_of(run_id, as_of)
        row = self.connection.execute(
            "SELECT * FROM score_sets WHERE run_id=? AND as_of=? AND rubric_version=? "
            "AND reviewed_evidence_hash=? AND status='complete' ORDER BY completed_at DESC LIMIT 1",
            (run_id, as_of.isoformat(), rubric_version, reviewed_evidence_hash)).fetchone()
        return dict(row) if row else None
