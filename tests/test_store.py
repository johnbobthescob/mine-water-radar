from dataclasses import replace
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest

from radar.ingest import ingest, load_replay
from radar.normalize import project_semantic_hash
from radar.sources import minedex, epbc
from radar.sources.http import Response
from radar.store import Store
from support_sources import Service

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = date(2026, 11, 25)
NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)


def batches(day=23):
    original = load_replay(FIXTURES / "replay/synthetic-a.json").batches
    observed = NOW.replace(day=day)
    return tuple(replace(b, provenance=replace(b.provenance, observed_at=observed)) for b in original)


def ingest_day(store, day=23, **kwargs):
    return ingest(store, batches(day), as_of=AS_OF, clock=lambda: NOW, run_key=f"day-{day}", **kwargs)


def version_hook(context):
    """Small explicit persistence exercise, not a project aggregation algorithm."""
    batch_id, records = next((key, rows) for key, rows in context.records.items()
                             if rows and rows[0].source == "minedex")
    record = records[0]
    version_id = context.run_id + ":test-version"
    context.store.add_project_version(id=version_id, run_id=context.run_id, project_id=record.project_id,
        title=record.values["proj_title"], site_membership_json=[record.business_key], stage_distribution_json={},
        representative_stage=None, representative_site=None, semantic_hash=project_semantic_hash([record]),
        status="current", coverage_json={}, freshness_json={})
    record_id = context.record_ids[(batch_id, record.business_key)]
    context.store.add_link(id=version_id+":link", project_version_id=version_id, source_record_id=record_id,
        method="test_explicit", supporting_reference=None, confidence="candidate", ambiguity_json=[], scope_json={})
    context.store.add_evidence(id=version_id+":evidence", evidence_key="test-evidence", project_version_id=version_id,
        source_record_id=record_id, field="site_stage", value_json=record.raw["site_stage"], excerpt=None,
        source_date_value=record.source_date.value, source_date_kind=record.source_date.kind,
        source_date_precision=record.source_date.precision, observed_at=context.store.run(context.run_id)["observed_at"],
        url=record.citation_url, licence_id="synthetic-CC-BY-4.0", role="synthetic test field", validity_json={"candidate": True})


def test_initial_schema_constraints_version_and_close_reopen(tmp_path):
    path = tmp_path / "nested/radar.sqlite"
    with Store(path) as store:
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert store.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {row[0] for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"runs", "source_batches", "source_records", "raw_responses", "projects", "project_versions",
                "links", "evidence", "changes", "score_sets", "scores"} <= tables
        with pytest.raises(RuntimeError, match="explicit"):
            store.ensure_project("minedex:TEST", NOW)
        with store.transaction():
            with pytest.raises(sqlite3.IntegrityError):
                store.connection.execute("INSERT INTO projects VALUES (?,?,?)", ("", NOW.isoformat(), NOW.isoformat()))
            with pytest.raises(sqlite3.IntegrityError):
                store.connection.execute("INSERT INTO projects VALUES (?,?,?)", ("minedex:X", "2026-11-25", "2026-11-24"))
        result = ingest_day(store, hook=version_hook)
        version = store.connection.execute("SELECT * FROM project_versions").fetchone()
        assert version["contract_status"] == "not_verified"
        with store.transaction():
            with pytest.raises(sqlite3.IntegrityError):
                store.connection.execute("UPDATE project_versions SET contract_status='open'")
            with pytest.raises(sqlite3.IntegrityError):
                store.connection.execute("UPDATE project_versions SET project_id='minedex:NONEXISTENT'")
            with pytest.raises(sqlite3.IntegrityError):
                store.connection.execute("UPDATE links SET confidence='guessed'")
            with pytest.raises(sqlite3.IntegrityError):
                store.connection.execute("UPDATE source_records SET business_key=(SELECT business_key FROM source_records LIMIT 1)")
        assert not store.connection.execute("PRAGMA foreign_key_check").fetchall()
    with Store(path) as store:
        assert store.latest_usable_run()["id"] == result.run_id
        assert store.connection.execute("SELECT count(*) FROM evidence").fetchone()[0] == 1
        value = store.connection.execute("SELECT value_json FROM evidence").fetchone()[0]
        assert json.loads(value) == "Proposed"
        assert store.connection.execute("SELECT count(*) FROM links").fetchone()[0] == 1


def test_unsupported_and_unversioned_existing_databases_are_not_overwritten(tmp_path):
    path = tmp_path / "db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=999")
    connection.close()
    with pytest.raises(ValueError, match="unsupported schema"):
        Store(path)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=0")
    connection.execute("CREATE TABLE existing(x)")
    connection.close()
    with pytest.raises(ValueError, match="unversioned nonempty"):
        Store(path)


def test_conflicting_duplicate_keys_roll_back_and_same_logical_batch_is_idempotent(tmp_path):
    with Store(tmp_path / "db") as store:
        first = ingest_day(store)
        again = ingest_day(store)
        assert again.run_id == first.run_id and again.repeated
        changed = batches(24)
        core = changed[0]
        conflict = {**core.records[0], "site_stage": "Operating"}
        core = replace(core, records=tuple(core.records)+(conflict,),
                       coverage=replace(core.coverage, expected_count=5, received_count=5))
        with pytest.raises(ValueError, match="conflicting duplicate"):
            ingest(store, (core,)+changed[1:], as_of=AS_OF, clock=lambda: NOW)
        assert store.latest_usable_run()["id"] == first.run_id
        assert store.connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
        with pytest.raises(ValueError, match="logical run key"):
            ingest(store, changed, as_of=AS_OF, run_key="day-23", clock=lambda: NOW)


def test_mixed_batch_and_live_fixture_database_modes_rejected(tmp_path):
    service = Service()
    synthetic = minedex.fetch(service.http())
    live = replace(synthetic, provenance=replace(synthetic.provenance, data_mode="live"),
                   raw_pages=tuple(replace(page, data_mode="live") for page in synthetic.raw_pages))
    with Store(tmp_path / "db") as store:
        result = ingest(store, (live,), as_of=AS_OF, clock=lambda: NOW)
        assert result.exit_code == 3 and result.usable  # missing optionals explicitly unavailable
        with pytest.raises(ValueError, match="provenance modes"):
            ingest_day(store)
        assert store.connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
    with Store() as store:
        with pytest.raises(ValueError, match="provenance modes"):
            ingest(store, (live, batches()[2]), as_of=AS_OF, clock=lambda: NOW)
        assert store.connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_failed_final_source_page_retains_previous_usable_and_raw_failure_audit(tmp_path):
    service = Service()
    http = service.http(tmp_path / "raw")
    with Store(tmp_path / "db") as store:
        first_batch = minedex.fetch(http)
        first = ingest(store, [first_batch], as_of=AS_OF, clock=lambda: NOW)
        records = store.connection.execute("SELECT count(*) FROM source_records").fetchone()[0]
        service.hook = lambda url, args: Response(503, b"unavailable", {}) if args.get("objectIds") == "3" else None
        failed = minedex.fetch(http)
        assert failed.status == "failed" and not failed.records
        result = ingest(store, [failed], as_of=AS_OF, clock=lambda: NOW)
        assert result.exit_code == 1 and result.status == "failed" and not result.usable
        assert store.latest_usable_run()["id"] == first.run_id
        assert store.connection.execute("SELECT count(*) FROM source_records").fetchone()[0] == records
        failed_db = next(b for b in store.batches(result.run_id) if b["source"] == "minedex")
        assert store.records(failed_db["id"]) == () and "503" in failed_db["error"]
        assert json.loads(failed_db["raw_manifest_json"])
        view = store.scope_view(result.run_id, "minedex", first_batch.scope_hash)
        assert view.availability == "unavailable" and view.stale and not view.fresh and view.records
        pointers = json.loads(store.records(next(b for b in store.batches(first.run_id) if b["source"] == "minedex")["id"])[0]["raw_manifest_json"])
        assert len(pointers) == 1 and Path(pointers[0]["path"]).exists()
        assert pointers[0]["sha256"] in {p.sha256 for p in first_batch.raw_pages}


def test_incomplete_core_never_promotes_even_if_marked_complete(tmp_path):
    with Store(tmp_path / "db") as store:
        first = ingest_day(store)
        later = batches(24)
        core = replace(later[0], coverage=replace(later[0].coverage, complete=False, exceeded_transfer_limit=True))
        result = ingest(store, (core,)+later[1:], as_of=AS_OF, clock=lambda: NOW)
        assert result.status == "failed" and result.exit_code == 1
        assert store.latest_usable_run()["id"] == first.run_id
        assert store.scope_view(result.run_id, "epbc", later[-1].scope_hash).fresh is False


def test_generator_failure_and_hook_failure_roll_back_everything(tmp_path):
    with Store(tmp_path / "db") as store:
        first = ingest_day(store, hook=version_hook)
        initial_counts = {table: store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                          for table in ("runs", "source_batches", "source_records", "raw_responses", "projects", "project_versions", "links", "evidence")}
        def broken_pages():
            yield batches(24)[0]
            raise RuntimeError("last page failed")
        with pytest.raises(RuntimeError, match="last page"):
            ingest(store, broken_pages(), as_of=AS_OF, clock=lambda: NOW)
        def broken_comparison(context):
            assert context.previous_run["id"] == first.run_id
            assert context.store.connection.in_transaction
            version_hook(context)
            context.store.ensure_project("minedex:SHOULD-ROLL-BACK", NOW)
            raise RuntimeError("comparison failed")
        with pytest.raises(RuntimeError, match="comparison"):
            ingest_day(store, 24, hook=broken_comparison)
        for table, expected in initial_counts.items():
            assert store.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == expected
        assert store.latest_usable_run()["id"] == first.run_id


def test_nested_transaction_cannot_commit_outer_transaction():
    with Store() as store:
        with pytest.raises(RuntimeError):
            with store.transaction():
                with store.transaction():
                    store.ensure_project("minedex:ROLLBACK", NOW)
                raise RuntimeError("outer failure")
        assert not store.connection.execute("SELECT * FROM projects").fetchall()
        with store.transaction():
            store.ensure_project("minedex:RETAIN", NOW)
            with pytest.raises(RuntimeError):
                with store.transaction():
                    store.ensure_project("minedex:INNER", NOW)
                    raise RuntimeError("inner failure")
        assert [row[0] for row in store.connection.execute("SELECT id FROM projects")] == ["minedex:RETAIN"]


def test_optional_failure_retains_original_scope_as_stale_and_unqueried_is_unknown(tmp_path):
    service = Service("epbc")
    optional = epbc.fetch(service.http())
    current = tuple(b for b in batches(23) if b.source != "epbc")+(optional,)
    with Store(tmp_path / "db") as store:
        first = ingest(store, current, as_of=AS_OF, clock=lambda: NOW)
        failure = replace(optional, records=(), status="failed", error="optional final page failed",
                          provenance=replace(optional.provenance, observed_at=NOW.replace(day=24)),
                          coverage=replace(optional.coverage, complete=False, received_count=None))
        second = ingest(store, tuple(b for b in batches(24) if b.source != "epbc")+(failure,), as_of=AS_OF, clock=lambda: NOW)
        assert second.status == "degraded" and second.exit_code == 3 and second.usable
        assert store.latest_usable_run()["id"] == second.run_id
        view = store.scope_view(second.run_id, "epbc", optional.scope_hash)
        assert view.availability == "unavailable" and view.stale and not view.fresh
        assert view.batch["run_id"] == first.run_id and len(view.records) == 3
        assert all(row["observed_at"].startswith("2026-11-23") for row in view.records)
        assert store.scope_view(second.run_id, "epbc", optional.scope_hash, retain_stale=False).records == ()
        unknown = store.scope_view(second.run_id, "tenements", "never-queried")
        assert unknown.availability == "unavailable" and not unknown.records and not unknown.fresh
        historical = store.scope_view(first.run_id, "epbc", optional.scope_hash)
        assert historical.fresh and not historical.stale


def test_incompatible_licence_suppresses_retained_content_until_verified_again(tmp_path):
    optional = epbc.fetch(Service("epbc").http())
    with Store(tmp_path / "db") as store:
        first = ingest(store, tuple(b for b in batches(23) if b.source != "epbc")+(optional,), as_of=AS_OF, clock=lambda: NOW)
        def fail(day, licence_status):
            return replace(optional, records=(), status="disabled", error="licensing unavailable",
                provenance=replace(optional.provenance, observed_at=NOW.replace(day=day)),
                coverage=replace(optional.coverage, complete=False, received_count=None),
                licence_verification=replace(optional.licence_verification, status=licence_status))
        def run(day, batch):
            return ingest(store, tuple(b for b in batches(day) if b.source != "epbc")+(batch,), as_of=AS_OF, clock=lambda: NOW)
        incompatible = run(24, fail(24, "incompatible"))
        for run_id in (first.run_id, incompatible.run_id):
            view = store.scope_view(run_id, "epbc", optional.scope_hash)
            assert view.availability == "suppressed" and view.records == () and view.batch is None
        assert store.connection.execute("SELECT count(*) FROM source_records").fetchone()[0] == 11
        unknown = run(25, fail(25, "unknown"))
        assert store.source_suppressed("epbc")
        restored = run(25, replace(optional, provenance=replace(optional.provenance, observed_at=NOW)))
        assert not store.source_suppressed("epbc")
        assert store.scope_view(restored.run_id, "epbc", optional.scope_hash).fresh


def test_conflicts_across_point_scopes_are_checked_before_promotion():
    values = list(batches())
    tenure = values[1]
    def point(site, holder):
        scope = {"source": "tenements", "site_code": site, "longitude": 120, "latitude": -25}
        from radar.sources.arcgis import scope_hash
        raw = {field: None for field in Service("tenements").spec.fields}
        raw.update(tenid=" T1 ", holder1=holder)
        return replace(tenure, records=(raw,), scope=scope, scope_hash=scope_hash(scope),
                       coverage=replace(tenure.coverage, expected_count=1, received_count=1))
    with Store() as store:
        with pytest.raises(ValueError, match="conflicting duplicate"):
            ingest(store, (values[0], point("A", "One"), point("B", "Two"), *values[2:]), as_of=AS_OF, clock=lambda: NOW)
        assert store.connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_as_of_uses_perth_date_and_latest_selection_uses_observation_not_replay_time():
    with Store() as store:
        late = ingest_day(store, 24)
        early = ingest_day(store, 23)
        assert store.latest_usable_run()["id"] == late.run_id
        assert store.latest_usable_run(as_of=date(2026, 11, 23))["id"] == early.run_id
        with pytest.raises(ValueError, match="as-of"):
            store.validate_as_of(late.run_id, date(2026, 11, 23))
        later = list(batches(24))
        # UTC Nov 24 20:00 is already Nov 25 in Perth.
        later[0] = replace(later[0], provenance=replace(later[0].provenance, observed_at=NOW.replace(day=24, hour=20)))
        with pytest.raises(ValueError, match="as-of"):
            ingest(store, later, as_of=date(2026, 11, 24), clock=lambda: NOW)


def add_score(store, set_id, version_id):
    store.add_score(score_set_id=set_id, project_version_id=version_id, total=0, tier="Background",
        positive_json={}, negative_json={}, caps_json=[], evidence_ids_json=[], change_ids_json=[], reason="synthetic persistence test")


def test_score_set_atomic_replacement_and_input_identity(tmp_path):
    with Store(tmp_path / "db") as store:
        run = ingest_day(store, hook=version_hook)
        version_id = run.run_id+":test-version"
        kwargs = dict(run_id=run.run_id, as_of=AS_OF, rubric_version="test-v1", reviewed_evidence_hash="hash-a", completed_at=NOW)
        with store.score_set(score_set_id="original", **kwargs):
            add_score(store, "original", version_id)
        assert store.latest_score_set(run.run_id, AS_OF, "test-v1", "hash-a")["id"] == "original"
        assert store.latest_score_set(run.run_id, AS_OF, "test-v1", "hash-b") is None
        with pytest.raises(ValueError, match="incomplete score set"):
            with store.score_set(score_set_id="replacement", **kwargs):
                pass
        assert store.latest_score_set(run.run_id, AS_OF, "test-v1", "hash-a")["id"] == "original"
        with store.score_set(score_set_id="replacement", **kwargs):
            add_score(store, "replacement", version_id)
        assert store.latest_score_set(run.run_id, AS_OF, "test-v1", "hash-a")["id"] == "replacement"
        with store.transaction():
            with pytest.raises(ValueError, match="building"):
                add_score(store, "replacement", version_id)


def test_change_event_key_preserves_first_observation_and_rejects_conflict():
    with Store() as store:
        run = ingest_day(store, hook=version_hook)
        version_id = run.run_id+":test-version"
        project_id = store.connection.execute("SELECT project_id FROM project_versions").fetchone()[0]
        event = dict(id="event-1", event_key="stable", project_id=project_id, previous_version_id=None,
                     current_version_id=version_id, event_type="synthetic_test", old_json=None, new_json="Proposed",
                     supporting_site_ids_json=[], evidence_ids_json=[], observed_at="2026-11-23T00:00:00+00:00", digest_eligible=False)
        with store.transaction():
            first = store.add_change(**event)
            second = store.add_change(**{**event, "id": "event-2", "observed_at": NOW.isoformat()})
            assert first["id"] == second["id"] and second["observed_at"].startswith("2026-11-23")
            with pytest.raises(ValueError, match="conflicting change"):
                store.add_change(**{**event, "new_json": "Operating"})
        assert store.connection.execute("SELECT count(*) FROM changes").fetchone()[0] == 1


def test_repeated_batch_without_explicit_run_key_does_not_duplicate_acquisition():
    with Store() as store:
        original = batches()
        first = ingest(store, original, as_of=AS_OF, clock=lambda: NOW)
        second = ingest(store, tuple(reversed(original)), as_of=AS_OF, clock=lambda: NOW)
        assert first.run_id == second.run_id and second.repeated
        assert store.connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
        assert store.connection.execute("SELECT count(*) FROM source_records").fetchone()[0] == 4


def test_versions_and_scores_can_share_ingestion_transaction_and_rollback():
    with Store() as store:
        def hook(context):
            version_hook(context)
            with context.store.score_set(score_set_id="inside-ingestion", run_id=context.run_id,
                    as_of=AS_OF, rubric_version="test-v1", reviewed_evidence_hash="", completed_at=NOW):
                add_score(context.store, "inside-ingestion", context.run_id+":test-version")
        first = ingest_day(store, hook=hook)
        assert store.latest_score_set(first.run_id, AS_OF, "test-v1", "")["id"] == "inside-ingestion"
        def failure(context):
            version_hook(context)
            with context.store.score_set(score_set_id="rollback-score", run_id=context.run_id,
                    as_of=AS_OF, rubric_version="test-v1", reviewed_evidence_hash="", completed_at=NOW):
                add_score(context.store, "rollback-score", context.run_id+":test-version")
            raise RuntimeError("after scores")
        with pytest.raises(RuntimeError, match="after scores"):
            ingest_day(store, 24, hook=failure)
        assert store.connection.execute("SELECT count(*) FROM score_sets").fetchone()[0] == 1
        assert store.connection.execute("SELECT count(*) FROM scores").fetchone()[0] == 1
        assert store.latest_usable_run()["id"] == first.run_id


def test_successful_scope_history_and_hook_previous_run_are_observation_ordered():
    with Store() as store:
        future = ingest_day(store, 25)
        seen = []
        old = ingest_day(store, 23, hook=lambda context: seen.append(context.previous_run))
        middle = ingest_day(store, 24, hook=lambda context: seen.append(context.previous_run))
        assert seen[0] is None and seen[1]["id"] == old.run_id
        scope = batches()[0].scope_hash
        assert store.latest_successful_batch("minedex", scope)["run_id"] == future.run_id
        assert store.latest_successful_batch("minedex", scope, before_run_id=middle.run_id)["run_id"] == old.run_id
        assert store.latest_successful_batch("minedex", "different-scope") is None


def test_raw_hash_mismatch_rolls_back_before_promotion(tmp_path):
    service = Service()
    batch = minedex.fetch(service.http(tmp_path / "raw"))
    Path(batch.raw_pages[-1].path).write_bytes(b"changed")
    with Store() as store:
        with pytest.raises(ValueError, match="raw response hash mismatch"):
            ingest(store, (batch,), as_of=AS_OF, clock=lambda: NOW)
        assert store.connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_complete_synthetic_replay_uses_field_and_duplicate_validation():
    values = list(batches())
    missing_stage = dict(values[0].records[0])
    del missing_stage["site_stage"]
    values[0] = replace(values[0], records=(missing_stage,)+tuple(values[0].records[1:]))
    with Store() as store:
        with pytest.raises(ValueError, match="missing fields.*site_stage"):
            ingest(store, values, as_of=AS_OF, clock=lambda: NOW)
        assert store.latest_usable_run() is None


def test_partial_recorded_scope_cannot_be_ingested_as_complete_by_direct_caller():
    partial = load_replay(FIXTURES / "replay/recorded-baseline.json").batches
    with Store() as store:
        with pytest.raises(ValueError, match="explicit selected-record replay"):
            ingest(store, partial, as_of=AS_OF, clock=lambda: NOW)
        assert store.latest_usable_run() is None


def test_failed_optional_malformed_raw_envelope_does_not_abort_core(tmp_path):
    service = Service("epbc")
    service.hook = lambda url, args: {"features": None} if args.get("objectIds") == "3" else None
    failed = epbc.fetch(service.http(tmp_path / "raw"))
    assert failed.status == "failed" and not failed.records
    with Store() as store:
        result = ingest(store, tuple(b for b in batches() if b.source != "epbc")+(failed,), as_of=AS_OF, clock=lambda: NOW)
        assert result.usable and result.status == "degraded" and result.exit_code == 3
        view = store.scope_view(result.run_id, "epbc", failed.scope_hash)
        assert view.availability == "unavailable" and not view.records and not view.fresh


def test_distinct_batches_with_equal_observation_times_have_stable_history_order():
    with Store() as store:
        first = ingest_day(store)
        changed = list(batches())
        changed[0] = replace(changed[0], records=({**changed[0].records[0], "site_stage": "Operating"},)+tuple(changed[0].records[1:]))
        seen = []
        second = ingest(store, changed, as_of=AS_OF, clock=lambda: NOW, hook=lambda context: seen.append(context.previous_run))
        assert seen[0]["id"] == first.run_id
        assert store.latest_usable_run()["id"] == second.run_id
        assert store.latest_successful_batch("minedex", changed[0].scope_hash, before_run_id=second.run_id)["run_id"] == first.run_id
