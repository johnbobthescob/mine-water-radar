"""Closed v1 fetch boundary. Citation URLs never belong to this registry."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
import math
import re
from types import MappingProxyType
from urllib.parse import parse_qsl, urlencode, urlsplit

SLIP = "https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Industry_and_Mining/MapServer"
EPBC_LAYER = "https://gis.environment.gov.au/gispubmap/rest/services/ogc_services/EPBC_Referrals/MapServer/0"
CKAN = "https://catalogue.data.wa.gov.au/api/3/action/package_show"
CC_BY = "https://creativecommons.org/licenses/by/4.0/"
EPBC_ITEMS = tuple("https://www.arcgis.com/sharing/rest/content/items/" + item for item in (
    "ee02ed7773d44c6fa799bf558c70f81a", "ff8ef1108dd148c99fad93799d67ee94"))
EPBC_WHERE = "PRIMARY_JURISDICTION='WA' AND CATEGORY='Mining'"
WATER_TERMS = ("dewater", "borefield", "groundwater investigation", "groundwater abstraction",
               "water treatment", "water pumping", "water supply bore", "hydrogeological investigation")
WATER_PREDICATE = "(" + " OR ".join(
    f"UPPER({field}) LIKE '%{term.upper()}%'" for field in ("title", "abstract") for term in WATER_TERMS) + ")"


@dataclass(frozen=True)
class SourceSpec:
    name: str
    layer: str
    fields: tuple[str, ...]
    key: str
    package: str | None = None
    core: bool = False


SOURCES = MappingProxyType({spec.name: spec for spec in (
    SourceSpec("minedex", SLIP + "/0", tuple("site_code site_title short_name site_type_ site_sub_t site_stage site_commo target_com commodity proj_code proj_title latitude longitude web_link extract_da".split()), "site_code", "minedex-dmirs-001", True),
    SourceSpec("tenements", SLIP + "/3", tuple("tenid fmt_tenid type tenstatus holdercnt".split()) + tuple(f"holder{i}" for i in range(1, 10)) + tuple("grantdate startdate enddate legal_area unit_of_me extract_da".split()), "tenid", "mining-tenements-dmirs-003"),
    SourceSpec("wamex", SLIP + "/22", tuple("anumber title project operator report_year date_released abstract dpxe_abs dpxe_rep".split()), "anumber", "mineral-exploration-reports-wamex"),
    SourceSpec("epbc", EPBC_LAYER, tuple("REFERENCE_NUMBER NAME PRIMARY_JURISDICTION CATEGORY REFERRAL_DECISION STANDARD_DETERMINATION STATUS_DESCRIPTION STAGE_NAME REFERRAL_TYPE YEAR REFERRAL_URL".split()), "REFERENCE_NUMBER"),
)})


class PolicyError(ValueError):
    pass


def wamex_where(as_of: date) -> str:
    start = as_of - timedelta(days=730)
    end = as_of + timedelta(days=1)
    return (f"date_released >= TIMESTAMP '{start} 00:00:00' AND "
            f"date_released < TIMESTAMP '{end} 00:00:00' AND {WATER_PREDICATE}")


class SourceRegistry:
    """OID names are admitted only after schema discovery, per HTTP session."""
    def __init__(self):
        self._oids: dict[str, str] = {}

    def register_oid(self, source: str, name: str) -> None:
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or name.lower().startswith("addr"):
            raise PolicyError("unsafe schema object-ID field")
        self._oids[source] = name

    def url(self, source: str, kind: str, **params) -> str:
        spec = SOURCES[source]
        if kind == "licence":
            if not spec.package:
                raise PolicyError("EPBC uses item metadata")
            url = CKAN + "?" + urlencode({"id": spec.package})
        elif kind in {"schema", "query"}:
            url = spec.layer + ("/query" if kind == "query" else "") + "?" + urlencode({"f": "json", **params})
        else:
            raise PolicyError("unknown endpoint kind")
        self.validate(url)
        return url

    def validate(self, url: str) -> str:
        if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
            raise PolicyError("unsafe URL")
        try:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port is not None or parsed.fragment:
                raise PolicyError("only exact HTTPS endpoints are allowed")
            if "environmentonline" in (parsed.hostname or "").lower():
                raise PolicyError("Environment Online is forbidden")
            base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        except ValueError as exc:
            raise PolicyError("invalid URL") from exc
        args = dict(pairs)
        if len(args) != len(pairs):
            raise PolicyError("duplicate query arguments")
        if base == CKAN:
            if set(args) != {"id"}:
                raise PolicyError("only fixed package_show lookups allowed")
            for spec in SOURCES.values():
                if args["id"] == spec.package:
                    return spec.name
            raise PolicyError("unapproved catalogue package")
        if base in EPBC_ITEMS:
            if args not in ({"f": "json"}, {"f": "pjson"}):
                raise PolicyError("only item JSON metadata allowed")
            return "epbc"
        for spec in SOURCES.values():
            if base == spec.layer:
                if args not in ({"f": "json"}, {"f": "pjson"}):
                    raise PolicyError("only schema JSON allowed")
                return spec.name
            if base == spec.layer + "/query":
                self._query(spec, args)
                return spec.name
        raise PolicyError("unapproved fetch destination")

    def _query(self, spec: SourceSpec, args: dict[str, str]) -> None:
        permitted = {"f", "where", "outFields", "returnGeometry", "returnIdsOnly", "returnCountOnly", "objectIds",
                     "orderByFields", "resultOffset", "resultRecordCount", "geometry", "geometryType", "inSR", "spatialRel"}
        if set(args) - permitted or args.get("f") != "json" or args.get("returnGeometry") != "false":
            raise PolicyError("unapproved query parameters")
        if spec.name == "minedex" and args.get("where") != "1=1":
            raise PolicyError("MINEDEX must use the complete layer scope")
        if spec.name == "epbc" and args.get("where") != EPBC_WHERE:
            raise PolicyError("EPBC must use WA Mining scope")
        if spec.name == "wamex":
            match = re.fullmatch(r"date_released >= TIMESTAMP '(\d{4}-\d{2}-\d{2}) 00:00:00' AND date_released < TIMESTAMP '(\d{4}-\d{2}-\d{2}) 00:00:00' AND " + re.escape(WATER_PREDICATE), args.get("where", ""))
            if not match:
                raise PolicyError("WAMEX requires bounded recent-release water scope")
            try:
                if date.fromisoformat(match[2]) - date.fromisoformat(match[1]) != timedelta(days=731):
                    raise ValueError()
            except ValueError as exc:
                raise PolicyError("invalid WAMEX window") from exc
        spatial = {"geometry", "geometryType", "inSR", "spatialRel"}
        if spec.name == "tenements":
            if args.get("where") != "tenstatus='LIVE'" or args.get("geometryType") != "esriGeometryPoint" or args.get("inSR") != "4326" or args.get("spatialRel") != "esriSpatialRelIntersects":
                raise PolicyError("tenements require a LIVE WGS84 point scope")
            try:
                point = json.loads(args["geometry"])
                if set(point) != {"x", "y", "spatialReference"} or point["spatialReference"] != {"wkid": 4326}:
                    raise ValueError()
                x, y = point["x"], point["y"]
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (x, y)) or not (-180 <= x <= 180 and -90 <= y <= 90):
                    raise ValueError()
            except (KeyError, TypeError, ValueError) as exc:
                raise PolicyError("invalid point geometry") from exc
        elif spatial & set(args):
            raise PolicyError("unexpected geometry query")
        allowed_fields = set(spec.fields) | ({self._oids[spec.name]} if spec.name in self._oids else set())
        if "outFields" in args and (not args["outFields"] or set(args["outFields"].split(",")) - allowed_fields):
            raise PolicyError("fields outside public allowlist")
        if "orderByFields" in args and args["orderByFields"] != self._oids.get(spec.name, "") + " ASC":
            raise PolicyError("ordering must use discovered OID")
        for key in ("returnIdsOnly", "returnCountOnly"):
            if key in args and args[key] != "true":
                raise PolicyError("invalid retrieval flag")
        for key in ("resultOffset", "resultRecordCount"):
            if key in args and (not args[key].isdigit() or (key == "resultRecordCount" and int(args[key]) < 1)):
                raise PolicyError("invalid page bound")
        if "objectIds" in args and not re.fullmatch(r"\d+(,\d+)*", args["objectIds"]):
            raise PolicyError("invalid object IDs")
