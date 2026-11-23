"""Offline ArcGIS simulator: synthetic envelopes, never an HTTP fallback."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from radar.sources.http import HttpClient, Response
from radar.sources.registry import SOURCES

FIXTURES = Path(__file__).parent / "fixtures"


def load(path):
    return json.loads((FIXTURES / path).read_text())


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 23, tzinfo=timezone.utc)
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


class Service:
    def __init__(self, source="minedex"):
        self.source = source
        self.spec = SOURCES[source]
        self.fixture = deepcopy(load("synthetic/source-services.json")[source])
        self.schema = self.fixture["schema"]
        self.records = self.fixture["records"]
        self.licence = self.fixture["licence"]
        self.requests = []
        self.hook = None
        self.clock = Clock()

    def respond(self, args):
        if args.get("returnCountOnly") == "true":
            return {"count": len(self.records)}
        if args.get("returnIdsOnly") == "true":
            return {"objectIdFieldName": "transport_id", "objectIds": [r["transport_id"] for r in self.records]}
        if "objectIds" in args:
            ids = set(map(int, args["objectIds"].split(",")))
            rows = [r for r in self.records if r["transport_id"] in ids]
        else:
            offset, count = int(args["resultOffset"]), int(args["resultRecordCount"])
            rows = self.records[offset:offset + count]
        return {"features": [{"attributes": row} for row in rows]}

    def __call__(self, url, timeout):
        assert timeout == 30
        args = dict(parse_qsl(urlsplit(url).query))
        self.requests.append((url, args))
        if self.hook:
            value = self.hook(url, args)
            if value is not None:
                return value if isinstance(value, Response) else Response(200, json.dumps(value).encode(), {})
        if "package_show" in url or "/content/items/" in url:
            value = self.licence
        elif urlsplit(url).path.endswith("/query"):
            value = self.respond(args)
        else:
            value = self.schema
        return Response(200, json.dumps(value).encode(), {"Content-Type": "application/json"})

    def http(self, raw_dir=None):
        return HttpClient(transport=self, clock=self.clock, sleep=self.clock.sleep,
                          raw_dir=raw_dir, data_mode="synthetic_fixture")
