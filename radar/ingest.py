"""Transactional SourceBatch ingestion and strictly local manifest replay.

No transport is created here. M4 may supply ``hook(context)`` to build versions,
links and comparisons inside the same transaction, before a run is promoted.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import parse_qsl, urlsplit

from .config import PERTH
from .models import Coverage, LicenceVerification, Provenance, RawPage, SourceBatch
from .normalize import (NORMALIZATION_VERSION, NormalizedRecord, normalize_records,
                        semantic_hash, stable_json, utc, utc_iso)
from .sources.arcgis import scope_hash
from .sources.registry import CC_BY, SOURCES, SourceRegistry, verify_licence
from .store import SCHEMA_VERSION, Store


@dataclass(frozen=True)
class IngestionContext:
    store: Store
    run_id: str
    previous_run: dict | None
    batches: tuple[SourceBatch, ...]
    records: Mapping[str, tuple[NormalizedRecord, ...]]  # batch ID -> records
    record_ids: Mapping[tuple[str, str], str]  # (batch ID, business key) -> DB ID
    partial: bool


@dataclass(frozen=True)
class IngestResult:
    run_id: str
    status: str
    usable: bool
    exit_code: int
    repeated: bool = False


def _identifier(*parts) -> str:
    return hashlib.sha256(stable_json(parts).encode()).hexdigest()


def _partial(batch):
    return (batch.provenance.data_mode == "recorded_fixture" and
            batch.coverage.scope == "fixture:selected-records" and
            batch.scope.get("fixture_scope") == "fixture:selected-records")


def _scope(batch):
    calculated = scope_hash(dict(batch.scope))
    if batch.scope_hash and batch.scope_hash != calculated:
        raise ValueError("source scope hash does not match query scope")
    return batch.scope_hash or calculated


def _validated(batch, *, allow_partial_recorded):
    if batch.source not in SOURCES or batch.provenance.source != batch.source:
        raise ValueError("unknown or mismatched source")
    if batch.contract_status != "not_verified":
        raise ValueError("contract availability is not verified")
    _scope(batch)
    if batch.scope.get("source") != batch.source:
        raise ValueError("query scope source mismatch")
    if batch.status not in {"complete", "failed", "disabled"}:
        raise ValueError("invalid source batch status")
    partial = _partial(batch)
    if partial and not allow_partial_recorded:
        raise ValueError("partial recorded scopes require explicit selected-record replay")
    if batch.provenance.observed_at is None:
        raise ValueError("batch observation timestamp required")
    utc(batch.provenance.observed_at)
    for page in batch.raw_pages:
        if page.source != batch.source or page.data_mode != batch.provenance.data_mode:
            raise ValueError("raw page provenance mode/source mismatch")
    licence = batch.licence_verification
    verified = bool(licence and licence.status == "verified" and licence.licence_id and
                    licence.licence_url in {CC_BY, CC_BY.rstrip('/'), CC_BY.replace('https:', 'http:')})
    if licence and licence.status not in {"verified", "unknown", "incompatible"}:
        raise ValueError("invalid licence status")
    if batch.status != "complete":
        if batch.records or batch.coverage.complete:
            raise ValueError("unsuccessful source scope must not expose records or complete coverage")
        return batch
    if not verified:
        return replace(batch, status="failed", records=(), coverage=replace(batch.coverage, complete=False),
                       error="current source licence is not verified CC BY 4.0")
    if partial:
        if batch.coverage.complete or batch.coverage.expected_count is not None:
            raise ValueError("selected-record scope cannot claim complete layer acquisition")
    elif (not batch.coverage.complete or batch.coverage.exceeded_transfer_limit or
          batch.coverage.expected_count is None):
        return replace(batch, status="failed", records=(), coverage=replace(batch.coverage, complete=False),
                       error="incomplete source scope; refusing promotion")
    if batch.coverage.received_count != len(batch.records):
        raise ValueError("received record count mismatch")
    if batch.coverage.expected_count is not None and batch.coverage.expected_count < len(batch.records):
        raise ValueError("expected record count smaller than received")
    if not partial:
        # Source clients validate service schemas. At the ingestion boundary,
        # require the same business evidence fields in every provenance mode.
        # short_name is a display convenience; the MINEDEX citation can be
        # constructed from site_code under PLAN section 2.2.
        required = set(SOURCES[batch.source].fields)
        if batch.source == "minedex":
            required -= {"short_name", "web_link"}
        for raw in batch.records:
            if required - set(raw):
                raise ValueError(f"{batch.source}: complete scope record missing fields: {sorted(required-set(raw))}")
    return batch


def _record_pointers(batch: SourceBatch) -> dict:
    """Map saved feature pages to keys once; retain batch references otherwise."""
    pointers = {}
    key_field = SOURCES[batch.source].key
    for page in batch.raw_pages:
        if page.path is None:
            continue
        try:
            body = Path(page.path).read_bytes()
        except OSError as exc:
            raise ValueError("captured raw response missing: " + page.path) from exc
        if hashlib.sha256(body).hexdigest() != page.sha256:
            raise ValueError("captured raw response hash mismatch")
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            continue  # Failed HTTP pages are still retained for audit.
        if not isinstance(payload, dict):
            continue
        features = payload.get("features")
        records = [feature.get("attributes", {}) for feature in features
                   if isinstance(feature, dict)] if isinstance(features, list) else []
        if payload.get("origin") == "synthetic" and isinstance(payload.get(batch.source), list):
            records += payload[batch.source]
        for record in records:
            if not isinstance(record, dict) or key_field not in record:
                continue
            key = str(record[key_field]).strip()
            pointer = {"path": page.path, "sha256": page.sha256}
            if pointer not in pointers.setdefault(key, []):
                pointers[key].append(pointer)
    return pointers


def ingest(store: Store, batches, *, as_of: date, run_key: str | None = None,
           clock: Callable = lambda: datetime.now(timezone.utc), hook: Callable | None = None,
           allow_partial_recorded: bool = False, limitations=(), replayed_at=None,
           linking_annotations_hash: str = "") -> IngestResult:
    """Consume all pages/batches before promotion; any exception rolls back.

    A returned failed core is saved as an audit-only failed run, without records
    or project updates. An exception (including a generator or M4 failure)
    rolls back the whole attempt. Neither path replaces a previous usable run.
    ``run_key`` identifies one immutable logical acquisition/replay, not a week.
    """
    with store.transaction():
        started = utc(clock())
        batches = tuple(_validated(batch, allow_partial_recorded=allow_partial_recorded) for batch in batches)
        if not batches:
            raise ValueError("no source batches")
        modes = {batch.provenance.data_mode for batch in batches}
        if len(modes) != 1:
            raise ValueError("cannot mix provenance modes in a run")
        mode = next(iter(modes))
        store.bind_mode(mode)
        # Missing optional inputs must remain visibly unavailable, not empty.
        missing = set(SOURCES) - {batch.source for batch in batches}
        observed = max(utc(batch.provenance.observed_at) for batch in batches)
        for source in sorted(missing - {"minedex"}):
            scope = {"source": source, "unavailable": "not_supplied"}
            batches += (SourceBatch(source, (), Provenance(source, observed_at=observed, data_mode=mode),
                        Coverage("not_supplied", False, warnings=("source not supplied",)),
                        status="disabled", scope_hash=scope_hash(scope), scope=scope, error="source not supplied"),)
        if as_of < observed.astimezone(PERTH).date():
            raise ValueError("as-of must not precede the selected observation date")
        identities = [(batch.source, _scope(batch)) for batch in batches]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate source scope in one run")
        for source in SOURCES:
            statuses = {b.licence_verification.status for b in batches
                        if b.source == source and b.licence_verification is not None}
            if "incompatible" in statuses and "verified" in statuses:
                raise ValueError("contradictory licensing decisions for source")
        # Normalise/check duplicates before promotion, including records which
        # recur across separate sampled point scopes in the same acquisition.
        normal = {}
        by_source = {}
        for batch in batches:
            records = normalize_records(batch.source, batch.records, provenance=batch.provenance)
            normal[(batch.source, _scope(batch))] = records
            by_source.setdefault(batch.source, []).extend(batch.records)
        for source, records in by_source.items():
            normalize_records(source, records)
        core = [batch for batch in batches if batch.source == "minedex"]
        partial = bool(core) and all(_partial(batch) and batch.status == "complete" for batch in core)
        complete_core = (len(core) == 1 and core[0].status == "complete" and
                         core[0].coverage.complete and not _partial(core[0]) and
                         (core[0].scope.get("where") == "1=1"))
        if not core or not (partial or complete_core):
            status, usable, exit_code = "failed", False, 1
        elif partial:
            status, usable, exit_code = "partial", False, 3
        else:
            degraded = any(b.status != "complete" or not b.coverage.complete or
                           b.counts.get("budget_truncated", 0) or b.counts.get("skipped", 0)
                           for b in batches if b.source != "minedex" and
                           b.scope.get("disabled_reason") != "site_limit_zero")
            status, usable, exit_code = ("degraded", True, 3) if degraded else ("complete", True, 0)
        input_hash = semantic_hash({"mode": mode, "linking_annotations_hash": linking_annotations_hash,
            "batches": [{"source": b.source, "scope": b.scope, "status": b.status,
                "records": [r.raw for r in normal[(b.source, _scope(b))]],
                "coverage": asdict(b.coverage), "observed_at": utc_iso(b.provenance.observed_at),
                "captured_at": utc_iso(b.provenance.captured_at) if b.provenance.captured_at else None,
                "licence": asdict(b.licence_verification) if b.licence_verification else None,
                "raw_hashes": [p.sha256 for p in b.raw_pages], "error": b.error} for b in batches]})
        key = run_key or "batch:" + input_hash
        existing = store.connection.execute("SELECT * FROM runs WHERE run_key=?", (key,)).fetchone()
        if existing:
            if existing["input_hash"] != input_hash:
                raise ValueError("logical run key reused with different content")
            store.validate_as_of(existing["id"], as_of)
            return IngestResult(existing["id"], existing["status"], bool(existing["usable"]),
                                {"failed": 1, "partial": 3, "degraded": 3, "complete": 0}[existing["status"]], True)
        run_id = _identifier("run", mode, key)
        previous = store.latest_usable_run(observed_at_or_before=observed)
        coverage = [{"source": b.source, "scope_hash": _scope(b), "status": "partial" if _partial(b) and b.status == "complete" else b.status,
                     "coverage": asdict(b.coverage), "counts": dict(b.counts), "error": b.error} for b in batches]
        store.connection.execute(
            "INSERT INTO runs(id,run_key,input_hash,data_mode,as_of,started_at,observed_at,replayed_at,status,"
            "coverage_json,limitations_json,schema_version,normalization_version,linking_annotations_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, key, input_hash, mode, as_of.isoformat(), utc_iso(started), utc_iso(observed),
             utc_iso(replayed_at) if replayed_at else None, "ingesting", stable_json(coverage),
             stable_json(tuple(limitations)), SCHEMA_VERSION, NORMALIZATION_VERSION, linking_annotations_hash))
        context_records, record_ids = {}, {}
        for batch in batches:
            batch_id = _identifier(run_id, batch.source, _scope(batch))
            records = normal[(batch.source, _scope(batch))]
            if status == "failed":
                records = ()
            batch_status = "partial" if _partial(batch) and batch.status == "complete" else batch.status
            licence = batch.licence_verification
            pages = [asdict(page) for page in batch.raw_pages]
            extracts = [r.dates["extract_da"].value for r in records
                        if "extract_da" in r.dates and r.dates["extract_da"].value]
            store.connection.execute(
                "INSERT INTO source_batches(id,run_id,source,scope_id,scope_hash,scope_json,status,complete,"
                "expected_count,received_count,licence_status,licence_json,provenance_json,coverage_json,counts_json,"
                "observed_at,captured_at,fetched_at,extraction_min,extraction_max,raw_manifest_json,error) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (batch_id, run_id, batch.source, batch.coverage.scope, _scope(batch), stable_json(batch.scope),
                 batch_status, int(batch.coverage.complete), batch.coverage.expected_count, batch.coverage.received_count,
                 licence.status if licence else "unknown", stable_json(asdict(licence) if licence else None),
                 stable_json(asdict(batch.provenance)), stable_json(asdict(batch.coverage)), stable_json(batch.counts),
                 utc_iso(batch.provenance.observed_at), utc_iso(batch.provenance.captured_at) if batch.provenance.captured_at else None,
                 max((utc_iso(page.fetched_at) for page in batch.raw_pages), default=None),
                 min(extracts, default=None), max(extracts, default=None), stable_json(pages), batch.error))
            for index, page in enumerate(batch.raw_pages):
                store.connection.execute(
                    "INSERT INTO raw_responses(id,batch_id,ordinal,path,sha256,fetched_at,response_json) VALUES (?,?,?,?,?,?,?)",
                    (_identifier(batch_id, index), batch_id, index, page.path, page.sha256, utc_iso(page.fetched_at), stable_json(asdict(page))))
            context_records[batch_id] = records
            pointers = _record_pointers(batch)
            for record in records:
                record_id = _identifier(batch_id, record.business_key)
                record_ids[(batch_id, record.business_key)] = record_id
                store.connection.execute(
                    "INSERT INTO source_records(id,batch_id,business_key,raw_json,normalized_json,semantic_hash,content_hash,"
                    "raw_manifest_json,source_date_value,source_date_kind,source_date_precision,observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (record_id, batch_id, record.business_key, stable_json(record.raw), stable_json(record.to_dict()),
                     record.semantic_hash, hashlib.sha256(stable_json(record.raw).encode()).hexdigest(),
                     stable_json(pointers.get(record.business_key, {"batch_id": batch_id,
                         "raw_hashes": [page.sha256 for page in batch.raw_pages]})),
                     record.source_date.value, record.source_date.kind, record.source_date.precision,
                     utc_iso(batch.provenance.observed_at)))
                if record.project_id:
                    store.ensure_project(record.project_id, batch.provenance.observed_at)
        if status != "failed" and hook:
            hook(IngestionContext(store, run_id, previous, batches, context_records, record_ids, partial))
        store.connection.execute("UPDATE runs SET status=?,usable=?,finished_at=? WHERE id=?",
                                 (status, int(usable), utc_iso(clock()), run_id))
        return IngestResult(run_id, status, usable, exit_code)


@dataclass(frozen=True)
class Replay:
    run_key: str
    batches: tuple[SourceBatch, ...]
    observed_at: datetime
    limitations: tuple[str, ...]
    label: str
    partial: bool


class _FixtureIndex:
    def __init__(self, root):
        self.root = Path(root).resolve()
        manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.entries = {item["path"]: item for item in manifest["fixtures"]}

    def read(self, relative, *, origin=None):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or relative not in self.entries:
            raise ValueError("replay file must be indexed inside the fixture root")
        entry = self.entries[relative]
        if origin and entry["origin"] != origin:
            raise ValueError("fixture origin mismatch")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError("fixture SHA-256 mismatch: " + relative)
        return json.loads(body), entry, str(path)


class _LocalLicenceMetadata:
    """Implement metadata lookup only; never instantiate an HTTP client."""
    def __init__(self, index, source):
        self.index, self.source = index, source
        self.registry = SourceRegistry()
        self.entries = {item["original_url"]: item for item in index.entries.values()
                        if item.get("kind") == "licence_metadata" and item["source"] == source}
        self.documents = []
        self.last_capture = None

    def get_json(self, url):
        self.registry.validate(url)
        if url not in self.entries:
            raise ValueError("offline licence metadata unavailable")
        entry = self.entries[url]
        document, _, path = self.index.read(entry["path"], origin="recorded")
        self.last_capture = utc(entry["original_capture_time_utc"])
        self.documents.append((entry, path))
        return document

    def clock(self):
        return self.last_capture


def _recorded_licence(index, source):
    metadata = _LocalLicenceMetadata(index, source)
    licence = verify_licence(metadata, source)
    if licence.status != "verified":
        raise ValueError("recorded licence metadata does not establish CC BY 4.0")
    pages = tuple(RawPage(source, entry["original_url"], entry.get("parameters", {}),
                          utc(entry["original_capture_time_utc"]), entry["sha256"], 200,
                          entry.get("response_headers", {}), licence.identity, path, 1, "recorded_fixture")
                  for entry, path in metadata.documents)
    return licence, pages


def load_replay(path: str | Path, *, fixture_root: str | Path | None = None) -> Replay:
    """Load the M1 replay format with hash/origin checks, without any HTTP.

    Recorded files remain untouched, including truncation flags. Their metadata
    URLs are audit strings only and are never treated as a fetch instruction.
    """
    path = Path(path).resolve()
    if path.is_dir():
        path /= "manifest.json"
    elif not path.exists() and not path.suffix:
        path = path.with_suffix(".json")
    root = Path(fixture_root).resolve() if fixture_root else path.parent.parent
    index = _FixtureIndex(root)
    if not path.is_relative_to(root):
        raise ValueError("replay outside fixture root")
    replay, replay_entry, replay_path = index.read(path.relative_to(root).as_posix())
    label = replay["label"]
    origin = replay["origin"]
    if origin != replay_entry["origin"]:
        raise ValueError("replay origin mismatch")
    batches = []
    if origin == "recorded":
        if (replay.get("data_mode") != "fixture:selected-records" or
                replay.get("complete_snapshot") is not False or replay.get("statewide") is not False):
            raise ValueError("recorded replay must be explicitly partial selected records")
        limitations = tuple(replay["limitations"]) + tuple(replay.get("recorded_caveats", ()))
        if not limitations:
            raise ValueError("partial replay limitations are required")
        keys = {spec.key: source for source, spec in SOURCES.items()}
        for selection in replay["selections"]:
            source = keys.get(selection["business_id_field"])
            if source is None or not selection["fixture"].startswith("recorded/"):
                raise ValueError("invalid selected-record source")
            body, entry, raw_path = index.read(selection["fixture"], origin="recorded")
            if body.get("exceededTransferLimit") != selection["response_exceeded_transfer_limit"]:
                raise ValueError("recorded response truncation flag mismatch")
            selected = [str(key).strip() for key in selection["business_ids"]]
            if len(set(selected)) != len(selected):
                raise ValueError("duplicate selected business ID")
            records = [feature["attributes"] for feature in body["features"]
                       if str(feature["attributes"].get(selection["business_id_field"])).strip() in selected]
            if {str(row[selection["business_id_field"]]).strip() for row in records} != set(selected):
                raise ValueError("selected business record missing from recorded envelope")
            # Never fill missing fields in the small water-type projection.
            captured = utc(entry["original_capture_time_utc"])
            licence, licence_pages = _recorded_licence(index, source)
            scope = {"source": source, "fixture_scope": "fixture:selected-records",
                     "fixture": selection["fixture"], "business_ids": sorted(selected)}
            raw_page = RawPage(source, entry["original_url"], dict(parse_qsl(urlsplit(entry["original_url"]).query)),
                               captured, entry["sha256"], 200, {}, licence.identity, raw_path, 1, "recorded_fixture")
            batches.append(SourceBatch(source, records,
                Provenance(source, SOURCES[source].layer, captured_at=captured, observed_at=captured,
                           sha256=entry["sha256"], data_mode="recorded_fixture", limitations=limitations),
                Coverage("fixture:selected-records", False, received_count=len(records),
                         exceeded_transfer_limit=body.get("exceededTransferLimit", False), warnings=limitations),
                scope_hash=scope_hash(scope), licence_verification=licence,
                raw_pages=(raw_page,) + licence_pages, scope=scope))
        partial = True
    elif origin == "synthetic":
        if (replay.get("complete_snapshot") is not True or
                replay.get("scope") != "synthetic:complete-snapshot"):
            raise ValueError("synthetic replay requires an explicit complete scenario scope")
        observed = utc(replay["observed_at_utc"])
        if date.fromisoformat(replay["snapshot_date"]) != observed.astimezone(PERTH).date():
            raise ValueError("synthetic snapshot/observation date mismatch")
        limitations = (label, "Fictional synthetic scenario; no current or statewide source facts.")
        for source in SOURCES:
            records = replay[source]
            if not isinstance(records, list):
                raise ValueError("synthetic source records must be an array")
            scope = {"source": source, "fixture_scope": replay["scope"]}
            if source == "minedex":
                scope["where"] = "1=1"
            licence = LicenceVerification("verified", observed, licence_id="synthetic-CC-BY-4.0",
                licence_url=CC_BY, organisation="Synthetic fixture; no real custodian",
                metadata=({"origin": "synthetic", "note": "Simulated licence check; never live verification"},))
            page = RawPage(source, SOURCES[source].layer, {}, observed, replay_entry["sha256"], 200, {},
                           licence.identity, replay_path, 1, "synthetic_fixture")
            batches.append(SourceBatch(source, records,
                Provenance(source, SOURCES[source].layer, captured_at=observed, observed_at=observed,
                           sha256=replay_entry["sha256"], data_mode="synthetic_fixture", limitations=limitations),
                Coverage(replay["scope"], True, len(records), len(records)), scope_hash=scope_hash(scope),
                licence_verification=licence, raw_pages=(page,), scope=scope))
        partial = False
    else:
        raise ValueError("only recorded or synthetic fixture manifests may be replayed")
    if not batches:
        raise ValueError("empty replay")
    return Replay("replay:" + replay["fixture_id"] + ":" + replay_entry["sha256"], tuple(batches),
                  max(utc(b.provenance.observed_at) for b in batches), limitations, label, partial)


def replay(store: Store, path: str | Path, *, as_of: date, fixture_root=None,
           clock: Callable = lambda: datetime.now(timezone.utc), hook=None) -> IngestResult:
    loaded = load_replay(path, fixture_root=fixture_root)
    return ingest(store, loaded.batches, as_of=as_of, run_key=loaded.run_key, clock=clock,
                  hook=hook, allow_partial_recorded=loaded.partial, limitations=loaded.limitations,
                  replayed_at=clock())
