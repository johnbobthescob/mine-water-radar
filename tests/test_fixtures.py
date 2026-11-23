from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest


ROOT = Path(__file__).parent / "fixtures"


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_fixture_manifest_hashes_and_provenance_are_valid():
    manifest = read_json("manifest.json")
    entries = manifest["fixtures"]
    assert entries
    indexed = {entry["path"]: entry for entry in entries}
    actual = {
        path.relative_to(ROOT).as_posix()
        for path in ROOT.rglob("*")
        if path.is_file() and path.name not in {"manifest.json", "README.md"}
    }
    assert set(indexed) == actual

    for relpath, entry in indexed.items():
        payload = (ROOT / relpath).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
        assert entry["origin"] in {"recorded", "synthetic"}
        if entry["origin"] == "recorded":
            if entry.get("kind") == "licence_metadata":
                from radar.sources.registry import CKAN, EPBC_ITEMS, SourceRegistry

                url = entry["original_url"]
                assert url.startswith(CKAN + "?") or any(url.startswith(item + "?") for item in EPBC_ITEMS)
                assert SourceRegistry().validate(url) == entry["source"]
                assert entry["response_status"] == 200
                assert entry["response_truncated"] is False
                assert entry["scope"] == "licence metadata only; not a dataset snapshot"
            else:
                assert entry["source_path"].startswith("research/samples/") or relpath.startswith("replay/")
            assert entry["original_capture_time_utc"] or relpath.startswith("replay/")
            assert entry["licence"]["url"] == "https://creativecommons.org/licenses/by/4.0/"
            assert "response_truncated" in entry
        else:
            assert "fictional synthetic" in entry["transformation"]


def test_recorded_payloads_are_byte_identical_research_copies():
    recorded = ROOT / "recorded"
    originals = Path(__file__).parents[1] / "research" / "samples"
    manifest = read_json("manifest.json")
    for entry in manifest["fixtures"]:
        if entry["path"].startswith("recorded/"):
            original = Path(__file__).parents[1] / entry["source_path"]
            copy = ROOT / entry["path"]
            assert original.read_bytes() == copy.read_bytes()
            assert original.parent == originals


def test_recorded_partial_envelopes_and_replay_limits_remain_explicit():
    for name in (
        "minedex-sample.json",
        "minedex-water-types.json",
        "tenements-sample.json",
        "wamex-water.json",
    ):
        assert read_json(f"recorded/{name}")["exceededTransferLimit"] is True
    assert "exceededTransferLimit" not in read_json("recorded/epbc-sample.json")

    replay = read_json("replay/recorded-baseline.json")
    assert replay["data_mode"] == "fixture:selected-records"
    assert replay["complete_snapshot"] is False
    assert replay["statewide"] is False
    assert all(
        selection["response_exceeded_transfer_limit"] is True
        for selection in replay["selections"][:-1]
    )
    assert replay["selections"][-1]["response_exceeded_transfer_limit"] is None

    epbc = read_json("recorded/epbc-sample.json")["features"][0]["attributes"]
    assert "\\\\" in epbc["REFERRAL_URL"]
    tenement = read_json("recorded/tenements-sample.json")["features"][0]["attributes"]
    assert tenement["grantdate"] < 0
    assert "addr1" in tenement
    wamex = read_json("recorded/wamex-water.json")["features"][0]["attributes"]
    assert len(wamex["abstract"]) == 250
    assert "1993" in wamex["abstract"]


def test_synthetic_replays_are_fictional_complete_snapshots_with_requested_changes():
    a, b, c = (read_json(f"replay/synthetic-{letter}.json") for letter in "abc")
    assert all(item["origin"] == "synthetic" and item["complete_snapshot"] for item in (a, b, c))
    assert all(item["scope"] == "synthetic:complete-snapshot" for item in (a, b, c))
    a_ids = {row["site_code"] for row in a["minedex"]}
    b_ids = {row["site_code"] for row in b["minedex"]}
    assert "SYNTH-PROJ-NEW" in {row["proj_code"] for row in b["minedex"]}
    assert "SYNTH-SITE-GONE" in a_ids and "SYNTH-SITE-GONE" not in b_ids
    assert b_ids - a_ids == {"SYNTH-SITE-WATER"}
    a_restart = next(row for row in a["minedex"] if row["site_code"] == "SYNTH-SITE-R1")
    b_restart = next(row for row in b["minedex"] if row["site_code"] == "SYNTH-SITE-R1")
    assert (a_restart["site_stage"], b_restart["site_stage"]) == ("Care and Maintenance", "Operating")
    moved_a = next(row for row in a["minedex"] if row["site_code"] == "SYNTH-SITE-MOVE")
    moved_b = next(row for row in b["minedex"] if row["site_code"] == "SYNTH-SITE-MOVE")
    assert moved_a["proj_code"] != moved_b["proj_code"]

    def business_content(snapshot):
        return sorted(
            (row["site_code"], row["proj_code"], row["proj_title"], row["site_title"], row["site_stage"])
            for row in snapshot["minedex"]
        )

    assert business_content(b) == business_content(c)
    assert [row["site_code"] for row in b["minedex"]] != [row["site_code"] for row in c["minedex"]]
    assert {row["extract_da"] for row in b["minedex"]} != {row["extract_da"] for row in c["minedex"]}


def test_focused_synthetic_variants_cover_required_edge_cases():
    variants = read_json("synthetic/edge-cases.json")
    assert variants["origin"] == "synthetic"
    for key in (
        "ambiguous_exact_name",
        "deposit_named_borefield",
        "wamex_negated_historical",
        "stale_and_missing_dates",
        "conflicting_business_keys",
        "multi_holder_tenement",
        "failed_truncated_pagination",
        "reviewed_approval",
        "contractor_evidence",
    ):
        assert key in variants


def test_socket_connect_and_dns_attempts_are_blocked():
    with pytest.raises(RuntimeError, match="network access is blocked"):
        socket.create_connection(("example.invalid", 443))
    with pytest.raises(RuntimeError, match="network access is blocked"):
        socket.getaddrinfo("example.invalid", 443)

