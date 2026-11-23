from datetime import date
from urllib.parse import urlencode

import pytest

from radar.sources.http import HttpClient, Response
from radar.sources.registry import (CKAN, EPBC_ITEMS, SOURCES, SLIP, PolicyError,
                                    SourceRegistry, wamex_where)


@pytest.mark.parametrize("url", [
    SLIP + "/1?f=json", SLIP + "/0/attachments?f=json",
    SLIP.replace("Industry_and_Mining", "Environment") + "/115?f=json",
    CKAN + "?id=epa-referred-significant-proposals", CKAN.replace("package_show", "package_search") + "?q=minedex",
    "https://environmentonline.dwer.wa.gov.au/", "https://environmentonline-variant.example/",
    "https://www.asx.com.au/", "https://www.wa.gov.au/robots.txt", "https://dasc.dmirs.wa.gov.au/",
    "https://minedex.dmirs.wa.gov.au/Web/common/jump.jsp?jumpType=SITE&id=1",
    "https://wamex.dmp.wa.gov.au/Wamex/Search/ReportDetails?ANumber=1",
    SLIP + "/0?f=json&token=secret", SLIP + "/0?f=json#x", SLIP + "/0?f=json&f=json",
    SLIP.replace("https://", "http://") + "/0?f=json",
    SLIP.replace("https://", "https://user@") + "/0?f=json",
    SLIP.replace(".gov.au/", ".gov.au:443/") + "/0?f=json",
    SLIP + "/%30?f=json", SLIP + "/3/../0?f=json", SLIP + "/0?f=json\n",
    EPBC_ITEMS[0] + "/data?f=json",
])
def test_forbidden_requests_never_reach_transport(url):
    calls = []
    http = HttpClient(transport=lambda *args: calls.append(args), raw_dir=None)
    with pytest.raises(PolicyError):
        http.get(url)
    assert not calls


def test_fixed_paths_and_metadata_only():
    registry = SourceRegistry()
    for name, spec in SOURCES.items():
        assert registry.validate(registry.url(name, "schema")) == name
        if spec.package:
            assert registry.validate(registry.url(name, "licence")) == name
    for item in EPBC_ITEMS:
        assert registry.validate(item + "?f=json") == "epbc"


@pytest.mark.parametrize("extra", [
    {"outFields": "*"}, {"outFields": "addr1"}, {"outFields": "operator"},
    {"where": "site_stage='Proposed'"}, {"returnGeometry": "true"},
    {"orderByFields": "site_code"}, {"resultOffset": "-1"}, {"objectIds": "1 OR 1=1"},
])
def test_query_arguments_are_closed(extra):
    registry = SourceRegistry()
    with pytest.raises(PolicyError):
        registry.url("minedex", "query", **{"where": "1=1", "returnGeometry": "false", **extra})


def test_wamex_archive_and_invalid_window_are_forbidden():
    registry = SourceRegistry()
    registry.url("wamex", "query", where=wamex_where(date(2026, 11, 23)), returnGeometry="false", returnIdsOnly="true")
    for where in ("1=1", wamex_where(date(2026, 11, 23)).replace("2024-11-23", "2020-11-23")):
        with pytest.raises(PolicyError):
            registry.url("wamex", "query", where=where, returnGeometry="false", returnIdsOnly="true")


@pytest.mark.parametrize("destination", [SLIP + "/1?f=json", SOURCES["epbc"].layer + "?f=json", "https://environmentonline.example/"])
def test_redirects_are_rejected_without_second_request(destination):
    calls = []
    def transport(url, timeout):
        calls.append(url)
        return Response(302, b"", {"Location": destination})
    http = HttpClient(transport=transport, raw_dir=None)
    with pytest.raises(PolicyError):
        http.get(SOURCES["minedex"].layer + "?f=json")
    assert len(calls) == 1


def test_tenement_addresses_and_unbounded_spatial_queries_blocked():
    registry = SourceRegistry()
    with pytest.raises(PolicyError):
        registry.url("tenements", "query", where="tenstatus='LIVE'", returnGeometry="false")


def test_implicit_all_attribute_queries_are_forbidden():
    registry = SourceRegistry()
    with pytest.raises(PolicyError, match="explicit attribute"):
        registry.url("minedex", "query", where="1=1", returnGeometry="false")
    with pytest.raises(PolicyError):
        registry.url("minedex", "query", where="1=1", returnGeometry="false", returnIdsOnly="true", returnCountOnly="true")
