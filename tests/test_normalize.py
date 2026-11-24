from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from radar.normalize import (normalize_date, normalize_record, normalize_records,
                             project_semantic_hash, semantic_hash, utc)
from support_sources import load


def site():
    return deepcopy(load("replay/synthetic-a.json")["minedex"][0])


def test_business_ids_roles_and_raw_display_values():
    raw = load("recorded/tenements-sample.json")["features"][0]["attributes"]
    record = normalize_record("tenements", raw)
    assert record.business_key == "CML1200448"
    assert record.raw["tenid"] == "CML1200448 "
    assert record.values["holder2"] == ""
    assert record.raw["holder2"] == " "
    assert "addr1" not in record.raw
    assert len(record.holders) == 1
    assert record.holders[0].role == "tenement holder at sampled site"
    assert record.operator is None and record.contract_status == "not_verified"
    assert record.dates["grantdate"].value == "1952-02-28T00:00:00+00:00"
    assert record.dates["startdate"].value.startswith("1951-")
    assert record.dates["enddate"].value.startswith("2031-")


def test_unknown_operator_title_suffix_and_historical_reporting_role():
    raw = load("recorded/minedex-sample.json")["features"][0]["attributes"]
    record = normalize_record("minedex", raw)
    assert record.project_id == "minedex:J00238"
    assert "/ Focus" in record.values["proj_title"]
    assert record.operator is None
    assert record.operator_status == "Unknown — not supplied by current MINEDEX layer"
    report = normalize_record("wamex", load("recorded/wamex-water.json")["features"][0]["attributes"])
    assert report.reporting_operators[0].name == "MR DOHERTY DP"
    assert report.reporting_operators[0].role == "WAMEX reporting operator"
    assert report.reporting_operators[0].date.value == "1994"
    assert report.source_date.kind == "release" and report.source_date.value.startswith("2008-")
    assert report.operator is None


@pytest.mark.parametrize("value,expected,precision", [
    (-1, "1969-12-31T23:59:59.999000+00:00", "millisecond"),
    (0, "1970-01-01T00:00:00+00:00", "millisecond"),
    ("2026-11-22T08:00:00+08:00", "2026-11-22T00:00:00+00:00", "second"),
    ("2026-11-22T00:00:00Z", "2026-11-22T00:00:00+00:00", "second"),
    ("2026-11-22", "2026-11-22", "day"),
    (None, None, None), ("", None, None), ("   ", None, None),
])
def test_date_normalization(value, expected, precision):
    result = normalize_date(value, "test_date")
    assert result.value == expected and result.precision == precision
    assert result.kind == "test_date" and result.raw == value and result.valid


@pytest.mark.parametrize("value", [True, "bad", "2026-02-30", "2026-11-22T00:00:00", float("inf"), 10**30])
def test_invalid_dates_are_retained_with_issue_not_replaced_by_observation(value):
    result = normalize_date(value, "extraction")
    assert result.value is None and not result.valid and result.issue and result.raw == value


def test_year_precision_no_manufactured_day_and_malformed_epbc_url_is_only_raw():
    raw = load("recorded/epbc-sample.json")["features"][0]["attributes"]
    record = normalize_record("epbc", raw)
    assert record.source_date.value == "2021" and record.source_date.precision == "year"
    assert record.source_date.kind == "referral_year"
    assert "\\" in record.raw["REFERRAL_URL"]
    assert "REFERENCE_NUMBER" in record.citation_url and "2021%2F8923" in record.citation_url
    assert normalize_date(2021.5, "year", year_only=True).valid is False
    assert normalize_date(" 2021 ", "year", year_only=True).value == "2021"


def test_blank_null_missing_and_unicode_survive_normalization():
    raw = {**site(), "site_title": "  Fictional  Güm  水  ", "short_name": "", "site_sub_t": None}
    record = normalize_record("minedex", raw)
    assert record.raw["site_title"] == raw["site_title"]
    assert record.values["site_title"] == "Fictional Güm 水"
    assert record.values["short_name"] == "" and record.values["site_sub_t"] is None
    assert record.semantic_hash != normalize_record("minedex", {**raw, "short_name": None}).semantic_hash
    assert "web_link" not in record.raw
    for code in (None, "", "   "):
        assert normalize_record("minedex", {**raw, "proj_code": code}).project_id == "site:SYNTH-SITE-A1"


def test_semantic_hash_excludes_transport_extract_provenance_and_input_order():
    raw = site()
    original = normalize_record("minedex", raw)
    later = normalize_record("minedex", {**raw, "oid": 999, "OBJECTID": 123,
                                        "transport_id": 15, "extract_da": "2026-11-20T00:00:00Z"})
    assert original.semantic_hash == later.semantic_hash
    records = normalize_records("minedex", load("replay/synthetic-b.json")["minedex"])
    reordered = normalize_records("minedex", load("replay/synthetic-c.json")["minedex"])
    assert project_semantic_hash(records) == project_semantic_hash(reordered)
    assert semantic_hash({"b": [2, 1], "a": {"y": 2, "x": 1}}) == semantic_hash({"a": {"x": 1, "y": 2}, "b": [1, 2]})
    for field, value in (("site_stage", "Operating"), ("proj_code", "OTHER"),
                         ("longitude", 121), ("site_title", "Other"), ("commodity", "Changed")):
        assert normalize_record("minedex", {**raw, field: value}).semantic_hash != original.semantic_hash
    assert project_semantic_hash([original]) != project_semantic_hash([replace(original, project_id="minedex:OTHER")])


def test_conflicting_business_keys_checked_even_when_only_extract_differs():
    raw = site()
    assert len(normalize_records("minedex", [raw, {**raw, "oid": 2}])) == 1
    for update in ({"site_stage": "Operating"}, {"extract_da": None}):
        with pytest.raises(ValueError, match="conflicting duplicate business key"):
            normalize_records("minedex", [raw, {**raw, **update}])
    with pytest.raises(ValueError, match="conflicting duplicate business key"):
        normalize_records("tenements", [{"tenid": " T1 ", "holder1": "One"}, {"tenid": "T1", "holder1": "Two"}])
    for value in (None, " ", True):
        with pytest.raises(ValueError, match="business key"):
            normalize_record("minedex", {**raw, "site_code": value})


def test_timestamp_helpers_require_timezone():
    with pytest.raises(ValueError, match="aware"):
        utc(datetime(2026, 1, 1))
    assert utc("2026-11-22T08:00:00+08:00") == datetime(2026, 11, 22, tzinfo=timezone.utc)
