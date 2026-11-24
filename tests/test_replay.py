from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from radar.ingest import load_replay, replay
from radar.sources.http import HttpClient
from radar.store import Store

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)
AS_OF = date(2026, 11, 24)


def test_synthetic_replay_reopen_repeat_and_original_observation(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("replay must not construct an HTTP client")
    monkeypatch.setattr(HttpClient, "__init__", forbidden)
    db = tmp_path / "radar.sqlite"
    path = FIXTURES / "replay/synthetic-a.json"
    with Store(db) as store:
        result = replay(store, path, as_of=AS_OF, clock=lambda: NOW)
        assert result.status == "complete" and result.usable and result.exit_code == 0
        row = store.run(result.run_id)
        assert row["data_mode"] == "synthetic_fixture"
        assert row["observed_at"] == "2026-10-30T00:00:00+00:00"
        assert row["replayed_at"] == NOW.isoformat()
        assert len(store.connection.execute("SELECT * FROM source_records").fetchall()) == 4
        first_seen = store.connection.execute("SELECT first_seen FROM projects ORDER BY id").fetchall()
    with Store(db) as store:
        again = replay(store, path, as_of=AS_OF, clock=lambda: NOW.replace(day=25))
        assert again.run_id == result.run_id and again.repeated
        assert store.run(result.run_id)["replayed_at"] == NOW.isoformat()
        assert store.connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
        assert store.connection.execute("SELECT count(*) FROM source_records").fetchone()[0] == 4
        assert store.connection.execute("SELECT first_seen FROM projects ORDER BY id").fetchall() == first_seen
        assert store.latest_usable_run()["id"] == result.run_id


def test_recorded_replay_is_partial_and_unchanged_and_never_latest_usable(tmp_path):
    loaded = load_replay(FIXTURES / "replay/recorded-baseline.json")
    with Store(tmp_path / "recorded.sqlite") as store:
        result = replay(store, FIXTURES / "replay/recorded-baseline.json", as_of=AS_OF, clock=lambda: NOW)
        assert result.status == "partial" and result.exit_code == 3 and not result.usable
        assert store.latest_usable_run() is None
        row = store.run(result.run_id)
        assert row["data_mode"] == "recorded_fixture"
        assert "not statewide" in loaded.label
        assert "partial" in row["limitations_json"] or "research" in row["limitations_json"]
        batches = store.batches(result.run_id)
        assert len(batches) == 5 and all(b["status"] == "partial" and not b["complete"] for b in batches)
        for batch in batches:
            assert batch["scope_id"] == "fixture:selected-records" and batch["expected_count"] is None
            view = store.scope_view(result.run_id, batch["source"], batch["scope_hash"])
            assert view.availability == "partial" and not view.fresh
            assert view.records and "incomplete" in view.reason
        water = next(b for b in loaded.batches if "water-types" in b.scope.get("fixture", ""))
        assert all("extract_da" not in raw and "proj_title" not in raw for raw in water.records)
        minedex = next(b for b in batches if "minedex-sample" in b["scope_json"])
        records = store.records(minedex["id"])
        original = json.loads((FIXTURES / "recorded/minedex-sample.json").read_text())["features"][0]["attributes"]
        normalized = json.loads(records[0]["normalized_json"])
        assert normalized["raw"]["site_stage"] == original["site_stage"]
        assert normalized["raw"]["extract_da"] == original["extract_da"]
        assert normalized["operator"] is None and normalized["contract_status"] == "not_verified"
        original_batch = next(b for b in loaded.batches if b.scope_hash == minedex["scope_hash"])
        assert records[0]["observed_at"] == original_batch.provenance.observed_at.isoformat()
        assert "exceededTransferLimit" not in json.loads(records[0]["raw_json"])
        assert json.loads((FIXTURES / "recorded/minedex-sample.json").read_text())["exceededTransferLimit"] is True
        assert store.connection.execute("SELECT count(*) FROM source_records").fetchone()[0] == 12
        assert replay(store, FIXTURES / "replay/recorded-baseline.json", as_of=AS_OF, clock=lambda: NOW).repeated


def test_synthetic_abc_preserve_history_without_m3_aggregation_or_changes(tmp_path):
    with Store(tmp_path / "db") as store:
        results = [replay(store, FIXTURES / f"replay/synthetic-{key}.json", as_of=AS_OF, clock=lambda: NOW) for key in "abc"]
        assert store.latest_usable_run()["id"] == results[-1].run_id
        assert len(store.batches(results[0].run_id)) == 4
        assert store.connection.execute("SELECT count(*) FROM source_records").fetchone()[0] == 12
        assert store.connection.execute("SELECT count(*) FROM projects").fetchone()[0] == 4
        gone = store.connection.execute("SELECT * FROM projects WHERE id='minedex:SYNTH-PROJ-GONE'").fetchone()
        assert gone["last_seen"].startswith("2026-10-30")
        alpha = store.connection.execute("SELECT * FROM projects WHERE id='minedex:SYNTH-PROJ-ALPHA'").fetchone()
        assert alpha["first_seen"].startswith("2026-10-30") and alpha["last_seen"].startswith("2026-11-13")
        assert store.connection.execute("SELECT count(*) FROM project_versions").fetchone()[0] == 0
        assert store.connection.execute("SELECT count(*) FROM changes").fetchone()[0] == 0


@pytest.mark.parametrize("name,as_of", [("synthetic-a", date(2026, 10, 29)), ("recorded-baseline", date(2026, 11, 21))])
def test_replay_as_of_cannot_precede_original_observation(tmp_path, name, as_of):
    with Store(tmp_path / "db") as store:
        with pytest.raises(ValueError, match="as-of"):
            replay(store, FIXTURES / f"replay/{name}.json", as_of=as_of, clock=lambda: NOW)
        assert store.connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        assert store.connection.execute("SELECT data_mode FROM database_state").fetchone()[0] is None


def test_recorded_synthetic_mode_isolation(tmp_path):
    with Store(tmp_path / "db") as store:
        replay(store, FIXTURES / "replay/synthetic-a.json", as_of=AS_OF, clock=lambda: NOW)
        with pytest.raises(ValueError, match="provenance modes"):
            replay(store, FIXTURES / "replay/recorded-baseline.json", as_of=AS_OF, clock=lambda: NOW)
        assert store.connection.execute("SELECT count(*) FROM runs").fetchone()[0] == 1


def test_tampered_unindexed_and_escaping_fixture_paths_fail(tmp_path):
    root = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, root)
    path = root / "replay/recorded-baseline.json"
    payload = root / "recorded/minedex-sample.json"
    payload.write_bytes(payload.read_bytes() + b" ")
    with pytest.raises(ValueError, match="SHA-256"):
        load_replay(path)
    with pytest.raises(ValueError, match="outside fixture root"):
        load_replay(path, fixture_root=FIXTURES)
    with pytest.raises(ValueError, match="indexed"):
        load_replay(root / "replay/unindexed.json")


def test_no_recorded_manifest_can_claim_complete_even_with_valid_hash(tmp_path):
    root = tmp_path / "fixtures"
    shutil.copytree(FIXTURES, root)
    path = root / "replay/recorded-baseline.json"
    value = json.loads(path.read_text())
    value["complete_snapshot"] = True
    path.write_text(json.dumps(value))
    index_path = root / "manifest.json"
    index = json.loads(index_path.read_text())
    for entry in index["fixtures"]:
        if entry["path"] == "replay/recorded-baseline.json":
            entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    index_path.write_text(json.dumps(index))
    with pytest.raises(ValueError, match="explicitly partial"):
        load_replay(path)
