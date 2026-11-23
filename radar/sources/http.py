"""Serial urllib transport, bounded retries and immutable raw response capture."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import socket
import time
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from radar.config import DEFAULT_RAW_DIR
from radar.models import RawPage
from .registry import PolicyError, SourceRegistry


class FetchError(RuntimeError):
    pass


class ResponseError(FetchError):
    def __init__(self, message: str, status: int | None = None, response=None):
        super().__init__(message)
        self.status = status
        self.response = response


class ArcGISError(ResponseError):
    def __init__(self, error: dict):
        super().__init__(f"ArcGIS error: {error}", error.get("code"))
        self.error = error


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: Mapping[str, str]
    url: str | None = None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urllib_transport(url: str, timeout: float, *, registry: SourceRegistry | None = None) -> Response:
    (registry or SourceRegistry()).validate(url)
    # The opener never follows redirects, including before HTTPError is returned.
    opener = build_opener(_NoRedirect())
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "WA-Mine-Water-Radar/0.1"})
    try:
        with opener.open(request, timeout=timeout) as reply:
            return Response(reply.status, reply.read(), dict(reply.headers), reply.url)
    except HTTPError as exc:
        with exc:
            return Response(exc.code, exc.read(), dict(exc.headers), exc.url)


class HttpClient:
    def __init__(self, *, transport: Callable | None = None, registry: SourceRegistry | None = None,
                 clock: Callable = lambda: datetime.now(timezone.utc), sleep: Callable = time.sleep,
                 raw_dir: Path | str | None = DEFAULT_RAW_DIR, data_mode: str = "live"):
        self.registry = registry or SourceRegistry()
        self.transport = transport or (lambda url, timeout: urllib_transport(url, timeout, registry=self.registry))
        self.clock, self.sleep = clock, sleep
        self.raw_dir = Path(raw_dir) / uuid4().hex if raw_dir is not None else None
        self.data_mode = data_mode
        self.pages: list[RawPage] = []
        self._last_request: datetime | None = None

    def _capture(self, url: str, source: str, response: Response, attempt: int, licence: str | None):
        digest = hashlib.sha256(response.body).hexdigest()
        now = self.clock()
        path = None
        if self.raw_dir is not None:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            path = self.raw_dir / f"{len(self.pages):06d}-{digest}.bin"
            with path.open("xb") as output:
                output.write(response.body)
        page = RawPage(source, url, dict(parse_qsl(urlsplit(url).query)), now, digest,
                       response.status, dict(response.headers), licence, str(path) if path else None,
                       attempt, self.data_mode)
        self.pages.append(page)
        if path:
            with path.with_suffix(".json").open("x", encoding="utf-8") as output:
                json.dump(asdict(page), output, default=lambda v: v.isoformat(), sort_keys=True, indent=2)

    def get(self, url: str, *, licence: str | None = None) -> Response:
        source = self.registry.validate(url)  # before even the first transport call
        for attempt in range(1, 4):
            now = self.clock()
            if self._last_request is not None:
                self.sleep(max(0.0, 0.2 - (now - self._last_request).total_seconds()))
            self._last_request = self.clock()
            try:
                response = self.transport(url, 30.0)
            except (TimeoutError, socket.timeout, URLError) as exc:
                is_timeout = isinstance(exc, TimeoutError) or (isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError))
                if not is_timeout or attempt == 3:
                    raise FetchError(f"transport failed: {exc}") from exc
                self.sleep(float(2 ** (attempt - 1)))
                continue
            # An injected transport must also honour the no-redirect contract.
            if response.url and response.url != url:
                self.registry.validate(response.url)
                raise PolicyError("transport followed a redirect without authorisation")
            self._capture(url, source, response, attempt, licence)
            headers = {key.lower(): value for key, value in response.headers.items()}
            if 300 <= response.status < 400:
                if "location" in headers:
                    self.registry.validate(urljoin(url, headers["location"]))
                raise PolicyError("redirects are disabled")
            retryable = response.status == 429 or 500 <= response.status <= 599
            if retryable and attempt < 3:
                delay = float(2 ** (attempt - 1))
                value = headers.get("retry-after")
                if value:
                    try:
                        retry_after = float(value)
                    except ValueError:
                        try:
                            retry_after = (parsedate_to_datetime(value) - self.clock()).total_seconds()
                        except (ValueError, TypeError, OverflowError):
                            retry_after = 0.0
                    if retry_after > 0:
                        delay = max(delay, min(30.0, retry_after))
                self.sleep(delay)
                continue
            if not 200 <= response.status < 300:
                raise ResponseError(f"HTTP {response.status}", response.status, response)
            return response
        raise AssertionError("unreachable")

    def get_json(self, url: str, *, licence: str | None = None) -> dict:
        try:
            response = self.get(url, licence=licence)
        except ResponseError as exc:
            # Some services return an unsupported-operation ArcGIS object with
            # HTTP 400; preserve it for the narrowly allowed inventory fallback.
            if exc.response is not None:
                try:
                    self._decode_json(exc.response)
                except ArcGISError:
                    raise
                except ResponseError:
                    pass
            raise
        return self._decode_json(response)

    @staticmethod
    def _decode_json(response: Response) -> dict:
        content_type = next((value for key, value in response.headers.items() if key.lower() == "content-type"), "")
        if "html" in content_type.lower() or response.body.lstrip().startswith(b"<"):
            raise ResponseError("HTML received instead of JSON")
        try:
            def invalid_constant(value):
                raise ValueError(f"invalid JSON constant {value}")
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(f"duplicate JSON key: {key}")
                    result[key] = value
                return result
            value = json.loads(response.body, parse_constant=invalid_constant, object_pairs_hook=unique_object)
        except (ValueError, UnicodeError) as exc:
            raise ResponseError("invalid JSON response") from exc
        if not isinstance(value, dict):
            raise ResponseError("JSON object required")
        if "error" in value:
            if (not isinstance(value["error"], dict) or
                    isinstance(value["error"].get("code"), bool) or
                    not isinstance(value["error"].get("code"), int)):
                raise ResponseError("malformed ArcGIS error")
            raise ArcGISError(value["error"])
        return value
