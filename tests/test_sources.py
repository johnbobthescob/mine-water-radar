from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from radar.sources import epbc, minedex, tenements, wamex
from radar.sources.registry import CC_BY, EPBC_LAYER, verify_licence
from support_sources import Service, load


@pytest.mark.parametrize("source,module", [("minedex", minedex), ("wamex", wamex), ("epbc", epbc)])
def test_source_fields_scope_and_raw_evidence_are_preserved(source, module):
    service = Service(source)
    kwargs = {"as_of": date(2026, 11, 23)} if source == "wamex" else {}
    batch = module.fetch(service.http(), **kwargs)
    assert batch.status == "complete"
    assert batch.contract_status == "not_verified"
    assert batch.licence_verification.status == "verified"
    assert batch.provenance.data_mode == "synthetic_fixture"
    assert len(batch.records) == 3
    for row in batch.records:
        original = next(r for r in service.records if r[service.spec.key] == row[service.spec.key])
        assert row == {field: original[field] for field in service.spec.fields}
    queries = [args for url, args in service.requests if "/query?" in url]
    assert all(args["returnGeometry"] == "false" for args in queries)
    if source == "epbc":
        assert all(args["where"] == "PRIMARY_JURISDICTION='WA' AND CATEGORY='Mining'" for args in queries)
        assert batch.records[0]["YEAR"] == 2021.0
        assert "\\" in batch.records[0]["REFERRAL_URL"]
        assert "REFERENCE_NUMBER" in epbc.citation(batch.records[0])
    if source == "minedex":
        assert all(args["where"] == "1=1" for args in queries)
        assert "operator" not in batch.records[0]


@pytest.mark.parametrize("source", ["minedex", "wamex", "tenements"])
@pytest.mark.parametrize("licence_id,licence_url,status", [
    (None, None, "unknown"), ("cc-by", None, "unknown"),
    ("custom_active_acceptance", None, "incompatible"), ("cc-by-3.0", CC_BY, "incompatible"),
])
def test_licence_must_explicitly_establish_cc_by_4(source, licence_id, licence_url, status):
    service = Service(source)
    service.licence["result"].update(license_id=licence_id, license_url=licence_url, isopen=True)
    result = verify_licence(service.http(), source)
    assert result.status == status
    assert result.metadata and result.verified_at.tzinfo


def test_core_licence_failure_is_fatal_and_optional_is_disabled_without_schema_fetch():
    for name, module in [("minedex", minedex), ("wamex", wamex)]:
        service = Service(name)
        service.licence["result"]["license_id"] = "custom_other"
        result = module.fetch(service.http(), **({"as_of": date(2026, 11, 23)} if name == "wamex" else {}))
        assert result.status == ("failed" if name == "minedex" else "disabled")
        assert not result.records and not result.coverage.complete
        assert len(service.requests) == 1


def test_licence_checks_are_fresh_on_repeated_fetches():
    service = Service()
    http = service.http()
    assert minedex.fetch(http).status == "complete"
    service.licence["result"]["license_id"] = "custom_other"
    assert minedex.fetch(http).status == "failed"
    assert sum("package_show" in url for url, _ in service.requests) == 2


def test_mismatched_ckan_identity_disables_source():
    service = Service()
    service.licence["result"]["name"] = "unrelated-package"
    assert minedex.fetch(service.http()).licence_verification.status == "unknown"


def test_unrelated_epbc_item_licence_is_never_inherited():
    service = Service("epbc")
    service.licence["url"] = EPBC_LAYER.replace("EPBC_Referrals", "Unrelated")
    batch = epbc.fetch(service.http())
    assert batch.status == "disabled"
    assert batch.licence_verification.status == "unknown"
    assert len(service.requests) == 2


@pytest.mark.parametrize("terms", ["All rights reserved", "https://creativecommons.org/licenses/by-nc/4.0/", CC_BY + " non-commercial use only"])
def test_epbc_incompatible_terms_exclude_evidence(terms):
    service = Service("epbc")
    service.licence["licenseInfo"] = terms
    result = epbc.fetch(service.http())
    assert result.status == "disabled" and result.licence_verification.status == "incompatible"


def test_epbc_second_fixed_item_can_supply_service_related_licence():
    service = Service("epbc")
    def hook(url, args):
        if "ee02ed" in url:
            return {"url": EPBC_LAYER, "title": "EPBC item without terms"}
    service.hook = hook
    result = epbc.fetch(service.http())
    assert result.status == "complete"
    assert len(result.licence_verification.metadata) == 2


def test_wamex_recent_predicate_and_local_eligibility_rechecks():
    service = Service("wamex")
    service.records[1]["date_released"] = 1203552000000  # recorded old release
    service.records[2]["abstract"] = "Generic drilling and water."
    service.records[2]["title"] = "Fictional exploration"
    result = wamex.fetch(service.http(), as_of=date(2026, 11, 23))
    assert result.status == "complete" and len(result.records) == 1
    assert result.counts == {"retrieved": 3, "eligible": 1}
    queries = [args for _, args in service.requests if "where" in args]
    assert all("TIMESTAMP '2024-11-23 00:00:00'" in args["where"] for args in queries)
    assert all("TIMESTAMP '2026-11-24 00:00:00'" in args["where"] for args in queries)
    assert all("UPPER(abstract)" in args["where"] and "DEWATER" in args["where"] for args in queries)
    old = load("recorded/wamex-water.json")["features"][0]["attributes"]
    assert not wamex.eligible(old, date(2026, 11, 23))
    # Old report years remain visible: admission to scoring uses a separate gate.
    recent_old_work = {**service.records[0], "report_year": 1994}
    assert wamex.eligible(recent_old_work, date(2026, 11, 23))


def test_wamex_date_sql_failure_never_falls_back_to_archive():
    service = Service("wamex")
    service.hook = lambda url, args: {"error": {"code": 400, "message": "TIMESTAMP unsupported"}} if "where" in args else None
    result = wamex.fetch(service.http(), as_of=date(2026, 11, 23))
    assert result.status == "failed" and not result.records
    assert all(args.get("where") != "1=1" for _, args in service.requests)


def site(site_code="SYNTH-SITE", **kwargs):
    return {"site_code": site_code, "proj_code": "SYNTH-PROJECT", "site_stage": "Proposed",
            "longitude": 120, "latitude": -28, **kwargs}


def test_tenement_selection_priority_budget_and_coordinate_coverage():
    sites = [site("SYNTH-PROPOSED"), site("SYNTH-DEV", site_stage="Under Development"),
             site("SYNTH-WATER", site_stage="Operating", site_type_="Infrastructure", site_title="Borefield"),
             site("SYNTH-INVALID", latitude=999), site("SYNTH-OTHER", site_stage="Operating"),
             site("SYNTH-DEPOSIT", site_stage="Operating", site_type_="Deposit", site_title="Borefield")]
    selected = tenements.select_sites(list(reversed(sites)), 2)
    assert [s["site_code"] for s in selected.selected] == ["SYNTH-WATER", "SYNTH-DEV"]
    assert selected.skipped == ("SYNTH-INVALID",)
    assert selected.unqueried == ("SYNTH-DEPOSIT", "SYNTH-OTHER", "SYNTH-PROPOSED")
    assert selected.budget_truncated == 1
    service = Service("tenements")
    result = tenements.fetch(service.http(), sites, limit=2)
    assert result.status == "complete" and result.counts["budget_truncated"] == 1
    assert result.counts["attempted"] == result.counts["sites_covered"] == 2
    assert result.counts["projects_covered"] == 1


def test_tenement_ties_use_stable_project_then_site_order():
    sites = [site("SYNTH-B", proj_code="Z"), site("SYNTH-C", proj_code="A"), site("SYNTH-A", proj_code="A")]
    assert [s["site_code"] for s in tenements.select_sites(sites).selected] == ["SYNTH-A", "SYNTH-C", "SYNTH-B"]


@pytest.mark.parametrize("value", [None, "nan", float("inf"), True, "invalid", 181])
def test_invalid_coordinates_skipped_with_warning(value):
    result = tenements.select_sites([site(longitude=value)])
    assert result.skipped and not result.selected


def test_tenement_exact_point_attributes_and_holders_without_addresses():
    service = Service("tenements")
    http = service.http()
    result = tenements.fetch(http, [site()])
    assert result.status == "complete"
    batch = result.batches[0]
    assert batch.coverage.complete and len(batch.records) == 3
    assert batch.records[0]["holder1"] == "FICTIONAL HOLDER ONE"
    assert batch.records[0]["holder2"] == "FICTIONAL HOLDER TWO"
    assert batch.records[0]["grantdate"] < 0
    assert batch.scope["site_code"] == "SYNTH-SITE"
    queries = [args for _, args in service.requests if "where" in args]
    for args in queries:
        assert args["where"] == "tenstatus='LIVE'"
        assert args["inSR"] == "4326"
        assert args["geometryType"] == "esriGeometryPoint"
        assert args["spatialRel"] == "esriSpatialRelIntersects"
        assert args["returnGeometry"] == "false"
        assert "addr" not in args.get("outFields", "")
    assert batch.contract_status == "not_verified"
    # Even within one HTTP session the next weekly lookup is issued again.
    calls = len(service.requests)
    repeated = tenements.fetch(http, [site()])
    assert repeated.batches[0].scope_hash == batch.scope_hash
    assert len(service.requests) == calls * 2
    moved = tenements.fetch(http, [site(longitude=121)])
    assert moved.batches[0].scope_hash != batch.scope_hash


def test_tenement_failed_point_does_not_hide_other_complete_scope():
    service = Service("tenements")
    def hook(url, args):
        if '"x":121.0' in args.get("geometry", ""):
            return {"error": {"code": 500, "message": "query failed"}}
    service.hook = hook
    result = tenements.fetch(service.http(), [site("SYNTH-A"), site("SYNTH-B", longitude=121)])
    assert result.status == "failed"
    assert [batch.status for batch in result.batches] == ["complete", "failed"]
    assert not result.batches[1].records
    assert result.counts["failed"] == result.counts["complete"] == 1


def test_zero_tenement_budget_disables_without_requests():
    service = Service("tenements")
    result = tenements.fetch(service.http(), [site()], limit=0)
    assert result.status == "disabled" and not service.requests
    assert result.counts["unqueried"] == 1


def test_tenement_licence_failure_keeps_selected_scopes_unknown():
    service = Service("tenements")
    service.licence["result"]["license_id"] = "custom_other"
    result = tenements.fetch(service.http(), [site("SYNTH-A"), site("SYNTH-B")])
    assert result.status == "disabled"
    assert all(batch.status == "disabled" and not batch.coverage.complete for batch in result.batches)
    assert result.counts["attempted"] == 0


@pytest.mark.parametrize("source", ["minedex", "tenements", "wamex", "epbc"])
def test_new_recorded_licence_bodies_verify_offline_with_full_provenance(source):
    service = Service(source)
    names = {"minedex": "minedex-package", "tenements": "tenements-package", "wamex": "wamex-package"}
    if source != "epbc":
        service.licence = load("licence/" + names[source] + ".json")
    else:
        service.licence = load("licence/epbc-layer-item.json")
        service.hook = lambda url, args: load("licence/epbc-service-item.json") if "ee02ed" in url else None
    result = verify_licence(service.http(), source)
    assert result.status == "verified" and result.licence_url == CC_BY
    assert result.metadata and result.metadata_urls and result.organisation
    if source == "epbc":
        assert len(result.metadata) == len(result.metadata_urls) == 2
        assert "Department of Climate Change" in result.credit
        assert "2026" in result.metadata[1]["licenseInfo"]
    else:
        assert result.licence_id == "cc-by"


def test_generic_epbc_cc_by_without_version_remains_unknown():
    service = Service("epbc")
    service.licence["licenseInfo"] = "Available under the CC BY data licensing model"
    result = verify_licence(service.http(), "epbc")
    assert result.status == "unknown" and len(service.requests) == 2


def test_epbc_wrong_scope_fails_instead_of_silently_returning_incomplete_data():
    service = Service("epbc")
    service.records[-1]["PRIMARY_JURISDICTION"] = "QLD"
    result = epbc.fetch(service.http())
    assert result.status == "failed" and not result.records


def test_optional_schema_failure_retains_failed_status():
    service = Service("epbc")
    service.schema["fields"] = []
    result = epbc.fetch(service.http())
    assert result.status == "failed" and result.licence_verification.status == "verified"


def test_tenement_schema_failure_accounts_for_unattempted_unknown_scopes():
    service = Service("tenements")
    service.schema["fields"] = []
    result = tenements.fetch(service.http(), [site("SYNTH-A"), site("SYNTH-B")])
    assert result.status == "failed"
    assert result.counts["failed"] == result.counts["not_attempted"] == result.counts["unknown_sites"] == 2
    assert result.counts["attempted"] == 0


def test_wamex_changed_date_field_type_fails_before_query():
    service = Service("wamex")
    for field in service.schema["fields"]:
        if field["name"] == "date_released":
            field["type"] = "esriFieldTypeString"
    result = wamex.fetch(service.http(), as_of=date(2026, 11, 23))
    assert result.status == "failed"
    assert not any("where" in args for _, args in service.requests)


@pytest.mark.parametrize("bad_value", [[], {}, True, 42])
def test_malformed_licence_identity_is_explicitly_unverified(bad_value):
    service = Service()
    service.licence["result"].update(license_id=bad_value, license_url=bad_value)
    result = minedex.fetch(service.http())
    assert result.status == "failed" and result.licence_verification.status == "unknown"
    assert result.provenance.licence == "not_verified"


def test_malformed_epbc_relationship_is_unknown():
    service = Service("epbc")
    service.licence["url"] = []
    result = epbc.fetch(service.http())
    assert result.status == "disabled" and result.licence_verification.status == "unknown"


def test_tenement_disabled_and_degraded_coverage_are_distinguishable():
    service = Service("tenements")
    disabled = tenements.fetch(service.http(), [site()], limit=0)
    assert disabled.disabled_reason == "site_limit_zero"
    assert not disabled.degraded and disabled.counts["budget_truncated"] == 0
    truncated = tenements.fetch(service.http(), [site("SYNTH-A"), site("SYNTH-B")], limit=1)
    assert truncated.degraded and truncated.counts["budget_truncated"] == 1
    service.licence["result"]["license_id"] = "custom_other"
    unverified = tenements.fetch(service.http(), [site()])
    assert unverified.degraded and unverified.disabled_reason == "licence_unverified"
