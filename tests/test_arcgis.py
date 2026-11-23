from copy import deepcopy

import pytest

from radar.sources import minedex
from radar.sources.http import Response
from support_sources import Service, load


def test_discovered_oid_batched_complete_with_short_final_page():
    service = Service()
    batch = minedex.fetch(service.http())
    assert batch.status == "complete"
    assert batch.coverage.complete and batch.coverage.expected_count == 3
    assert len(batch.records) == 3
    assert all("transport_id" not in row for row in batch.records)
    pages = [args for _, args in service.requests if "objectIds" in args]
    assert [args["objectIds"] for args in pages] == ["1,2", "3"]
    assert all(int(args["resultRecordCount"]) <= 2 for args in pages)
    assert all(set(args["outFields"].split(",")) == set(service.spec.fields) | {"transport_id"} for args in pages)
    assert all(page.licence_identity == batch.licence_verification.identity for page in batch.raw_pages[1:])


def test_transfer_limited_batch_is_split_serially():
    service = Service()
    def hook(url, args):
        if args.get("objectIds") == "1,2":
            return {"features": [{"attributes": service.records[0]}], "exceededTransferLimit": True}
    service.hook = hook
    batch = minedex.fetch(service.http())
    assert batch.status == "complete"
    assert [args["objectIds"] for _, args in service.requests if "objectIds" in args] == ["1,2", "1", "2", "3"]


@pytest.mark.parametrize("problem", ["missing", "extra", "duplicate", "single-truncated", "missing-features", "missing-attribute", "bad-transfer-flag", "last-page-http", "last-page-json"])
def test_invalid_or_failed_final_page_never_returns_partial_core(problem):
    service = Service()
    def hook(url, args):
        if args.get("objectIds") == "3":
            row = deepcopy(service.records[-1])
            if problem == "missing":
                return {"features": []}
            if problem == "extra":
                row["transport_id"] = 99
            if problem == "duplicate":
                return {"features": [{"attributes": row}] * 2}
            if problem == "single-truncated":
                return {"features": [{"attributes": row}], "exceededTransferLimit": True}
            if problem == "missing-features":
                return {}
            if problem == "missing-attribute":
                del row["site_stage"]
            if problem == "bad-transfer-flag":
                return {"features": [{"attributes": row}], "exceededTransferLimit": "false"}
            if problem == "last-page-http":
                return Response(503, b"unavailable", {})
            if problem == "last-page-json":
                return Response(200, b"{", {})
            return {"features": [{"attributes": row}]}
    service.hook = hook
    batch = minedex.fetch(service.http())
    assert batch.status == "failed" and not batch.coverage.complete
    assert not batch.records and batch.error
    assert batch.raw_pages


@pytest.mark.parametrize("kind", ["duplicate-inventory", "moving-inventory", "moving-count"])
def test_inventory_inconsistency_retries_whole_snapshot_once_then_fails(kind):
    service = Service()
    calls = {"inventory": 0, "count": 0}
    def hook(url, args):
        if "returnCountOnly" in args:
            calls["count"] += 1
            if kind == "moving-count" and calls["count"] % 2 == 0:
                return {"count": 4}
        if "returnIdsOnly" in args:
            calls["inventory"] += 1
            if kind == "duplicate-inventory":
                return {"objectIdFieldName": "transport_id", "objectIds": [1, 1, 3]}
            if kind == "moving-inventory" and calls["inventory"] % 2 == 0:
                return {"objectIdFieldName": "transport_id", "objectIds": [1, 2, 4]}
    service.hook = hook
    batch = minedex.fetch(service.http())
    assert batch.status == "failed" and not batch.records
    assert calls["inventory"] == (2 if kind == "duplicate-inventory" else 4)


def test_one_moving_snapshot_can_stabilise_on_second_attempt():
    service = Service()
    inventories = 0
    def hook(url, args):
        nonlocal inventories
        if "returnIdsOnly" in args:
            inventories += 1
            if inventories == 2:
                return {"objectIdFieldName": "transport_id", "objectIds": [1, 2, 4]}
    service.hook = hook
    batch = minedex.fetch(service.http())
    assert batch.status == "complete" and inventories == 4
    assert len(batch.records) == 3


def unsupported_inventory(service):
    def hook(url, args):
        if "returnIdsOnly" in args:
            return {"error": {"code": 400, "message": "returnIdsOnly not supported"}}
    service.hook = hook


def test_offset_fallback_is_stable_and_short_page_does_not_stop_it():
    service = Service()
    unsupported_inventory(service)
    original = service.respond
    def respond(args):
        if "resultOffset" in args:
            offset = int(args["resultOffset"])
            return {"features": [{"attributes": service.records[offset]}], "exceededTransferLimit": offset < 2}
        return original(args)
    service.respond = respond
    batch = minedex.fetch(service.http())
    assert batch.status == "complete" and len(batch.records) == 3
    offsets = [args for _, args in service.requests if "resultOffset" in args]
    assert [args["resultOffset"] for args in offsets] == ["0", "1", "2"]
    assert all(args["orderByFields"] == "transport_id ASC" for args in offsets)


@pytest.mark.parametrize("kind", ["repeat", "no-progress", "moving-count", "truncated-final", "unsorted", "unsupported-capabilities"])
def test_offset_fallback_inconsistencies_fail(kind):
    service = Service()
    unsupported_inventory(service)
    if kind == "unsupported-capabilities":
        service.schema["advancedQueryCapabilities"]["supportsOrderBy"] = False
    original = service.respond
    counts = 0
    def respond(args):
        nonlocal counts
        if "returnCountOnly" in args:
            counts += 1
            return {"count": 3 if counts % 2 else (4 if kind == "moving-count" else 3)}
        if "resultOffset" in args:
            offset = int(args["resultOffset"])
            rows = service.records[offset:offset + 2]
            if kind == "repeat":
                rows = service.records[:2]
            if kind == "no-progress" and offset:
                rows = []
            if kind == "unsorted":
                rows = list(reversed(rows))
            return {"features": [{"attributes": row} for row in rows], "exceededTransferLimit": kind == "truncated-final"}
        return original(args)
    service.respond = respond
    batch = minedex.fetch(service.http())
    assert batch.status == "failed" and not batch.records


def test_inventory_error_is_not_a_generic_fallback_trigger():
    service = Service()
    service.hook = lambda url, args: {"error": {"code": 400, "message": "Invalid SQL"}} if "returnIdsOnly" in args else None
    assert minedex.fetch(service.http()).status == "failed"
    assert not any("resultOffset" in args for _, args in service.requests)


@pytest.mark.parametrize("change", ["field", "oid", "limit", "multiple-oids"])
def test_schema_drift_is_visible_before_record_queries(change):
    service = Service()
    if change == "field":
        service.schema["fields"] = [f for f in service.schema["fields"] if f["name"] != "site_stage"]
    elif change == "oid":
        service.schema["fields"][0]["type"] = "esriFieldTypeInteger"
    elif change == "limit":
        del service.schema["maxRecordCount"]
    else:
        service.schema["fields"].append({"name": "second_oid", "type": "esriFieldTypeOID"})
    result = minedex.fetch(service.http())
    assert result.status == "failed" and result.error
    assert not any("/query?" in url for url, _ in service.requests)


def test_conflicting_business_keys_fail_but_identical_duplicates_can_collapse():
    service = Service()
    service.records[1]["site_code"] = service.records[0]["site_code"]
    service.records[1]["site_title"] = "Conflicting fictional title"
    assert minedex.fetch(service.http()).status == "failed"
    service.records[1] = {**service.records[0], "transport_id": 2}
    batch = minedex.fetch(service.http())
    assert batch.status == "complete" and len(batch.records) == 2
    assert batch.coverage.expected_count == 3


def test_recorded_truncated_minedex_envelope_cannot_be_a_complete_pull():
    service = Service()
    original = service.respond
    recorded = load("recorded/minedex-sample.json")
    # The recorded schema uses oid; preserve that response unchanged and require
    # missing required transport IDs / truncation to reject the attempted pull.
    service.respond = lambda args: recorded if "objectIds" in args else original(args)
    assert minedex.fetch(service.http()).status == "failed"


def test_offset_fallback_accepts_explicit_unsupported_inventory_in_http_400():
    import json
    service = Service()
    service.hook = lambda url, args: Response(400, json.dumps({"error": {"code": 400, "message": "returnIdsOnly not supported"}}).encode(), {}) if "returnIdsOnly" in args else None
    assert minedex.fetch(service.http()).status == "complete"


def test_empty_scope_still_verifies_inventory_and_pre_post_counts():
    service = Service()
    service.records = []
    batch = minedex.fetch(service.http())
    assert batch.status == "complete" and not batch.records
    assert batch.coverage.expected_count == batch.coverage.received_count == 0
    assert sum("returnCountOnly" in args for _, args in service.requests) == 2
    assert sum("returnIdsOnly" in args for _, args in service.requests) == 2
