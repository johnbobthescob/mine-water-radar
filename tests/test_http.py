import hashlib
import json
from urllib.error import URLError

import pytest

from radar.sources.http import ArcGISError, FetchError, HttpClient, Response, ResponseError
from radar.sources.registry import SOURCES, PolicyError
from support_sources import Clock

URL = SOURCES["minedex"].layer + "?f=json"


def client(sequence, **kwargs):
    clock, calls = Clock(), []
    def transport(url, timeout):
        calls.append((url, timeout, clock()))
        result = next(sequence)
        if isinstance(result, Exception):
            raise result
        return result
    return HttpClient(transport=transport, clock=clock, sleep=clock.sleep, raw_dir=kwargs.pop("raw_dir", None), **kwargs), clock, calls


@pytest.mark.parametrize("status", [401, 403, 404, 400])
def test_permanent_errors_are_not_retried(status):
    http, clock, calls = client(iter([Response(status, b"denied", {})]))
    with pytest.raises(ResponseError):
        http.get(URL)
    assert len(calls) == 1
    assert len(http.pages) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_three_attempts_bounded_retry_after_and_request_spacing(status):
    http, clock, calls = client(iter([Response(status, b"retry", {"Retry-After": "9999"})] * 3))
    with pytest.raises(ResponseError):
        http.get(URL)
    assert len(calls) == 3
    assert all(timeout == 30 for _, timeout, _ in calls)
    assert [value for value in clock.sleeps if value] == [30, 30]
    assert len(http.pages) == 3


@pytest.mark.parametrize("error", [TimeoutError("timeout"), URLError(TimeoutError("timeout"))])
def test_timeout_has_three_attempts_and_exponential_delays(error):
    http, clock, calls = client(iter([error] * 3))
    with pytest.raises(FetchError):
        http.get(URL)
    assert len(calls) == 3
    assert [delay for delay in clock.sleeps if delay] == [1, 2]


def test_non_timeout_url_error_no_retry():
    http, _, calls = client(iter([URLError("DNS failure")]))
    with pytest.raises(FetchError):
        http.get(URL)
    assert len(calls) == 1


@pytest.mark.parametrize("body,headers", [
    (b'<html>blocked</html>', {}), (b'{}', {"Content-Type": "text/html"}),
    (b'bad json', {}), (b'[]', {}), (b'{"n":NaN}', {}), (b'{"error":"bad"}', {}),
])
def test_bad_payloads_are_captured_then_rejected(body, headers):
    http, _, _ = client(iter([Response(200, body, headers)]))
    with pytest.raises(ResponseError):
        http.get_json(URL)
    assert http.pages[0].sha256 == hashlib.sha256(body).hexdigest()


def test_arcgis_error_inside_200():
    http, _, _ = client(iter([Response(200, b'{"error":{"code":400,"message":"Bad query"}}', {})]))
    with pytest.raises(ArcGISError) as exc:
        http.get_json(URL)
    assert exc.value.status == 400


def test_raw_bytes_and_manifests_are_immutable_and_hash_verified(tmp_path):
    payload = b'{"fields": []}'
    http, clock, calls = client(iter([Response(200, payload, {})] * 2), raw_dir=tmp_path)
    for _ in range(2):
        assert http.get_json(URL, licence="cc-by-4.0") == {"fields": []}
    assert (calls[1][2] - calls[0][2]).total_seconds() >= .2
    files = list(tmp_path.rglob("*.bin"))
    assert len(files) == 2
    for path in files:
        assert path.read_bytes() == payload
        manifest = json.loads(path.with_suffix(".json").read_text())
        assert manifest["parameters"] == {"f": "json"}
        assert manifest["licence_identity"] == "cc-by-4.0"
        assert manifest["sha256"] == hashlib.sha256(payload).hexdigest()
        assert manifest["fetched_at"].endswith("+00:00")


def test_transport_cannot_silently_follow_redirect():
    http, _, _ = client(iter([Response(200, b'{}', {}, SOURCES["epbc"].layer + "?f=json")]))
    with pytest.raises(PolicyError):
        http.get_json(URL)


def test_duplicate_json_keys_are_rejected_before_completeness_checks():
    http, _, _ = client(iter([Response(200, b'{"features":[],"exceededTransferLimit":true,"exceededTransferLimit":false}', {})]))
    with pytest.raises(ResponseError, match="invalid JSON"):
        http.get_json(URL)


def test_http_400_arcgis_error_details_are_preserved():
    http, _, calls = client(iter([Response(400, b'{"error":{"code":400,"message":"returnIdsOnly not supported"}}', {})]))
    with pytest.raises(ArcGISError, match="not supported"):
        http.get_json(URL)
    assert len(calls) == 1


def test_retry_after_http_date_is_bounded():
    from email.utils import format_datetime
    from datetime import timedelta
    clock = Clock()
    header = format_datetime(clock() + timedelta(hours=1))
    http, actual_clock, calls = client(iter([Response(429, b'', {"Retry-After": header}), Response(200, b'{}', {})]))
    assert http.get_json(URL) == {}
    assert max(actual_clock.sleeps) == 30
    assert len(calls) == 2


def test_default_urllib_transport_also_validates_before_network():
    from radar.sources.http import urllib_transport
    with pytest.raises(PolicyError):
        urllib_transport("https://environmentonline.example/", 30)


@pytest.mark.parametrize("error", ["bad", {}, {"code": {}}, {"code": True}])
def test_malformed_arcgis_error_is_rejected(error):
    http, _, _ = client(iter([Response(200, json.dumps({"error": error}).encode(), {})]))
    with pytest.raises(ResponseError, match="malformed ArcGIS"):
        http.get_json(URL)
