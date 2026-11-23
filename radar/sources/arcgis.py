"""Complete ArcGIS scope retrieval; unsuccessful scopes expose no partial records."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from radar.models import Coverage, Provenance, SourceBatch
from .http import ArcGISError, FetchError, ResponseError
from .registry import SOURCES, verify_licence


class SchemaError(FetchError):
    pass


class InconsistentSnapshot(FetchError):
    pass


def scope_hash(scope: dict) -> str:
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def integer(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResponseError(f"invalid {label}")
    return value


@dataclass(frozen=True)
class Schema:
    oid: str
    page_size: int
    metadata: dict


class ArcGISClient:
    def __init__(self, http, source: str):
        self.http = http
        self.spec = SOURCES[source]
        self.licence = None
        self.schema = None

    def prepare(self):
        self.licence = verify_licence(self.http, self.spec.name)
        if self.licence.status != "verified":
            return False
        metadata = self.http.get_json(self.http.registry.url(self.spec.name, "schema"), licence=self.licence.identity)
        fields = metadata.get("fields")
        if not isinstance(fields, list) or any(not isinstance(f, dict) or not isinstance(f.get("name"), str) for f in fields):
            raise SchemaError("schema fields missing or malformed")
        names = [f["name"] for f in fields]
        if len(names) != len(set(names)) or set(self.spec.fields) - set(names):
            raise SchemaError("schema drift: required fields missing or duplicated")
        if self.spec.name == "wamex" and not any(
                f["name"] == "date_released" and f.get("type") == "esriFieldTypeDate" for f in fields):
            raise SchemaError("WAMEX release field no longer supports date SQL")
        oids = [f["name"] for f in fields if f.get("type") == "esriFieldTypeOID"]
        declared = metadata.get("objectIdField", metadata.get("objectIdFieldName"))
        if len(oids) != 1 or (declared is not None and declared != oids[0]):
            raise SchemaError("schema must identify one unambiguous object-ID field")
        maximum = integer(metadata.get("maxRecordCount"), "service page limit")
        if maximum == 0:
            raise SchemaError("service page limit must be positive")
        self.http.registry.register_oid(self.spec.name, oids[0])
        self.schema = Schema(oids[0], min(1000, maximum), metadata)
        return True

    def query(self, params: dict, **extra):
        url = self.http.registry.url(self.spec.name, "query", **{**params, **extra})
        return self.http.get_json(url, licence=self.licence.identity)

    def count(self, params):
        return integer(self.query(params, returnCountOnly="true").get("count"), "count")

    def inventory(self, params):
        result = self.query(params, returnIdsOnly="true")
        ids = result.get("objectIds")
        if result.get("objectIdFieldName") != self.schema.oid or not isinstance(ids, list):
            raise ResponseError("missing or mismatched object ID inventory")
        if self.limited(result):
            raise InconsistentSnapshot("truncated ID inventory")
        for value in ids:
            integer(value, "object ID")
        if len(ids) != len(set(ids)):
            raise InconsistentSnapshot("duplicate inventory IDs")
        return sorted(ids)

    @staticmethod
    def limited(page):
        value = page.get("exceededTransferLimit", False)
        if not isinstance(value, bool):
            raise ResponseError("invalid exceededTransferLimit flag")
        return value

    def features(self, page):
        features = page.get("features")
        if not isinstance(features, list):
            raise ResponseError("features missing")
        records = []
        required = set(self.spec.fields) | {self.schema.oid}
        for feature in features:
            attrs = feature.get("attributes") if isinstance(feature, dict) else None
            if not isinstance(attrs, dict) or required - set(attrs):
                raise SchemaError("record missing required attributes")
            integer(attrs[self.schema.oid], "feature object ID")
            records.append({key: attrs[key] for key in (*self.spec.fields, self.schema.oid)})
        return records

    def id_batch(self, params, ids):
        page = self.query(params, objectIds=",".join(map(str, ids)),
                          outFields=",".join((*self.spec.fields, self.schema.oid)),
                          resultRecordCount=str(min(self.schema.page_size, len(ids))))
        records = self.features(page)
        actual = [r[self.schema.oid] for r in records]
        if len(set(actual)) != len(actual) or set(actual) - set(ids):
            raise InconsistentSnapshot("duplicate or extra IDs in batch")
        if self.limited(page):
            if len(ids) == 1:
                raise InconsistentSnapshot("single-ID batch is transfer limited")
            middle = len(ids) // 2
            return self.id_batch(params, ids[:middle]) + self.id_batch(params, ids[middle:])
        if set(actual) != set(ids):
            raise InconsistentSnapshot("missing IDs in batch")
        return records

    def offsets(self, params, before):
        caps = self.schema.metadata.get("advancedQueryCapabilities", {})
        if not isinstance(caps, dict) or caps.get("supportsPagination") is not True or caps.get("supportsOrderBy") is not True:
            raise SchemaError("safe stable-ID offset pagination unsupported")
        records, seen = [], set()
        while len(records) < before:
            page = self.query(params, outFields=",".join((*self.spec.fields, self.schema.oid)),
                              resultOffset=str(len(records)), resultRecordCount=str(self.schema.page_size),
                              orderByFields=self.schema.oid + " ASC")
            batch = self.features(page)
            ids = [r[self.schema.oid] for r in batch]
            if not ids or ids != sorted(set(ids)) or seen.intersection(ids) or (seen and min(ids) <= max(seen)):
                raise InconsistentSnapshot("repeated/non-progressing or unordered offset page")
            seen.update(ids)
            records.extend(batch)
            if len(records) > before or (len(records) == before and self.limited(page)):
                raise InconsistentSnapshot("offset count/transfer limit inconsistent")
            # A short page is not an end marker: use count, even with a false flag.
        if self.count(params) != before:
            raise InconsistentSnapshot("moving offset count")
        return records

    def retrieve(self, params):
        """Retry a moving snapshot once, never return the first partial attempt."""
        params = {"returnGeometry": "false", **params}
        for attempt in range(2):
            try:
                before = self.count(params)
                try:
                    ids = self.inventory(params)
                except ArcGISError as exc:
                    message = json.dumps(exc.error).lower()
                    if exc.status not in {400, 501} or not any(term in message for term in ("not supported", "unsupported", "not implemented")):
                        raise
                    records = self.offsets(params, before)
                else:
                    if len(ids) != before:
                        raise InconsistentSnapshot("inventory/count mismatch")
                    records = []
                    for offset in range(0, len(ids), self.schema.page_size):
                        records.extend(self.id_batch(params, ids[offset:offset + self.schema.page_size]))
                    if self.inventory(params) != ids or self.count(params) != before:
                        raise InconsistentSnapshot("moving inventory/count")
                return self.business_records(records), before
            except InconsistentSnapshot:
                if attempt:
                    raise
        raise AssertionError("unreachable")

    def business_records(self, records):
        unique = {}
        for raw in records:
            key = raw[self.spec.key]
            if isinstance(key, bool) or not isinstance(key, (str, int)) or not str(key).strip():
                raise SchemaError("empty/invalid stable business key")
            key = str(key).strip()
            business = {field: raw[field] for field in self.spec.fields}
            if key in unique and unique[key] != business:
                raise SchemaError("conflicting duplicate business key: " + key)
            unique[key] = business
        return [unique[key] for key in sorted(unique)]

    def result(self, scope, start, *, status, records=(), expected=None, error=None, counts=None):
        limitations = {
            "minedex": ("Operator is not supplied by the current MINEDEX layer; extraction time is not a stage-change date.",),
            "wamex": ("Reporting operators may be historical; report year and release date differ.",
                      "Abstracts may be truncated; acquisition keywords do not prove a water requirement."),
            "epbc": ("YEAR has year precision; status does not establish a precise decision date or water requirement.",),
            "tenements": ("Tenement holder at sampled site; point intersections may be ambiguous and do not establish project ownership or full tenure coverage.",),
        }[self.spec.name]
        return SourceBatch(self.spec.name, records,
                           Provenance(self.spec.name, self.spec.layer,
                                      licence="CC BY 4.0" if self.licence and self.licence.status == "verified" else "not_verified",
                                      licence_url=self.licence.licence_url if self.licence and self.licence.status == "verified" else None,
                                      observed_at=self.http.clock(),
                                      data_mode=self.http.data_mode, limitations=limitations),
                           Coverage(scope_hash(scope), status == "complete", expected,
                                    len(records) if status == "complete" else None,
                                    warnings=(error,) if error else ()),
                           status, scope_hash(scope), self.licence, tuple(self.http.pages[start:]),
                           error, scope, counts or {})

    def fetch(self, params, *, scope=None, recheck=None):
        scope = scope or {"source": self.spec.name, **params}
        start = len(self.http.pages)
        try:
            if not self.prepare():
                status = "failed" if self.spec.core else "disabled"
                return self.result(scope, start, status=status, error="licence not verified: " + str(self.licence.reason))
            records, expected = self.retrieve(params)
            if recheck:
                records = [record for record in records if recheck(record)]
            return self.result(scope, start, status="complete", records=records, expected=expected,
                               counts={"retrieved": expected, "eligible": len(records)})
        except (FetchError, ValueError) as exc:
            return self.result(scope, start, status="failed", error=str(exc))
