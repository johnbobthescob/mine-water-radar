"""Fresh LIVE tenure at a deterministic, bounded sample of site points."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from urllib.parse import urlencode

from radar.config import DEFAULT_TENEMENT_SITE_LIMIT
from .arcgis import ArcGISClient
from .http import FetchError
from .registry import SOURCES

_ACTIVE = {"Proposed", "Under Development", "Operating"}
_WATER_INFRASTRUCTURE = re.compile(
    r"\b(?:borefields?|dewater(?:ing)? (?:facilit(?:y|ies)|plants?|infrastructure)|"
    r"groundwater abstraction facilit(?:y|ies)|water supply infrastructure|"
    r"water treatment plants?|water pipelines?|water pumping stations?)\b", re.I)


def active_water_infrastructure(site):
    return (str(site.get("site_type_") or "").strip().casefold() == "infrastructure" and
            site.get("site_stage") in _ACTIVE and
            bool(_WATER_INFRASTRUCTURE.search(" ".join(str(site.get(k) or "") for k in ("site_sub_t", "site_title")))))


def coordinates(site):
    try:
        values = [site.get("longitude"), site.get("latitude")]
        if any(isinstance(value, bool) or value is None for value in values):
            return None
        x, y = map(float, values)
        if not math.isfinite(x) or not math.isfinite(y) or not (-180 <= x <= 180 and -90 <= y <= 90):
            return None
        return x, y
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class Selection:
    selected: tuple[dict, ...]
    skipped: tuple[str, ...]
    unqueried: tuple[str, ...]
    budget_truncated: int
    total_sites: int
    eligible_sites: int
    warnings: tuple[str, ...] = ()


def select_sites(sites, limit=DEFAULT_TENEMENT_SITE_LIMIT):
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("tenement site limit must be a nonnegative integer")
    ranked, skipped, unqueried = [], [], []
    for site in sites:
        site_id = str(site.get("site_code") or "").strip()
        priority = 0 if active_water_infrastructure(site) else {"Under Development": 1, "Proposed": 2}.get(site.get("site_stage"))
        if priority is None:
            unqueried.append(site_id)
        elif not site_id or coordinates(site) is None:
            skipped.append(site_id)
        else:
            ranked.append((priority, str(site.get("proj_code") or ""), site_id, dict(site)))
    ranked.sort(key=lambda row: row[:3])
    # MINEDEX must already be a validated spine; ambiguous points are not sampled.
    if len({row[2] for row in ranked}) != len(ranked):
        raise ValueError("duplicate site identities in tenement selection")
    selected = tuple(row[3] for row in ranked[:limit])
    unqueried.extend(row[2] for row in ranked[limit:])
    warnings = tuple(f"site {identity or '(missing ID)'} skipped: missing/invalid WGS84 coordinates or identity" for identity in sorted(skipped))
    if limit and len(ranked) > limit:
        warnings += (f"site budget leaves {len(ranked) - limit} eligible sites unqueried; tenure unknown",)
    return Selection(selected, tuple(sorted(skipped)), tuple(sorted(unqueried)), max(0, len(ranked) - limit) if limit else 0,
                     len(sites), len(ranked), warnings)


def citation(record):
    tenid = str(record["tenid"]).strip().replace("'", "''")
    return SOURCES["tenements"].layer + "/query?" + urlencode({"f": "json", "where": f"tenid='{tenid}'",
                                                             "outFields": "tenid", "returnGeometry": "false"})


@dataclass(frozen=True)
class TenementResult:
    status: str
    batches: tuple
    selection: Selection
    counts: dict
    error: str | None = None
    disabled_reason: str | None = None

    @property
    def degraded(self):
        """For the caller's optional-enrichment exit-code/coverage decision."""
        if self.disabled_reason == "site_limit_zero":
            return False
        return bool(self.status != "complete" or self.selection.skipped or self.selection.budget_truncated)


def fetch(http, sites, *, limit=DEFAULT_TENEMENT_SITE_LIMIT):
    sites = list(sites)
    selection = select_sites(sites, limit)
    counts = {"total_sites": selection.total_sites, "eligible_sites": selection.eligible_sites,
              "selected": len(selection.selected), "attempted": 0, "complete": 0, "failed": 0,
              "skipped": len(selection.skipped), "unqueried": len(selection.unqueried),
              "budget_truncated": selection.budget_truncated, "sites_covered": 0, "projects_covered": 0,
              "disabled": 0, "not_attempted": len(selection.selected), "unknown_sites": selection.total_sites}
    if limit == 0:
        return TenementResult("disabled", (), selection, counts, "tenement enrichment explicitly disabled", "site_limit_zero")
    if not selection.selected:
        return TenementResult("complete", (), selection, counts)
    client = ArcGISClient(http, "tenements")
    prepare_start = len(http.pages)
    prepare_error = None
    try:
        if not client.prepare():
            prepare_error = "licence not verified: " + str(client.licence.reason)
    except (FetchError, ValueError) as exc:
        prepare_error = str(exc)
    batches, projects = [], set()
    for index, site in enumerate(selection.selected):
        x, y = coordinates(site)
        point = {"x": x, "y": y, "spatialReference": {"wkid": 4326}}
        params = {"where": "tenstatus='LIVE'", "geometryType": "esriGeometryPoint",
                  "geometry": json.dumps(point, separators=(",", ":")), "inSR": "4326",
                  "spatialRel": "esriSpatialRelIntersects"}
        scope = {"source": "tenements", "site_code": site["site_code"], "proj_code": site.get("proj_code"),
                 "longitude": x, "latitude": y, "query": params,
                 "role": "tenement holder at sampled site", "link_method": "point_intersection"}
        start = prepare_start if index == 0 else len(http.pages)
        if prepare_error:
            status = "disabled" if client.licence and client.licence.status != "verified" else "failed"
            batches.append(client.result(scope, start, status=status, error=prepare_error))
            counts[status] += 1
            continue
        counts["attempted"] += 1
        counts["not_attempted"] -= 1
        try:
            records, expected = client.retrieve(params)
            if any(record["tenstatus"] != "LIVE" for record in records):
                raise FetchError("non-LIVE tenement returned for LIVE point scope")
            batches.append(client.result(scope, start, status="complete", records=records, expected=expected))
            counts["complete"] += 1
            counts["sites_covered"] += 1
            if site.get("proj_code"):
                projects.add(site["proj_code"])
        except (FetchError, ValueError) as exc:
            batches.append(client.result(scope, start, status="failed", error=str(exc)))
            counts["failed"] += 1
    counts["projects_covered"] = len(projects)
    counts["unknown_sites"] -= counts["sites_covered"]
    status = "failed" if counts["failed"] or prepare_error else "complete"
    if client.licence and client.licence.status != "verified":
        status = "disabled"
    return TenementResult(status, tuple(batches), selection, counts, prepare_error,
                          "licence_unverified" if status == "disabled" else None)
