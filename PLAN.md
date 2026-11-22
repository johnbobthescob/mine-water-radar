# WA Mine Water Opportunity Radar — v1 implementation plan

Planning date: 22 November 2026 (Australia/Perth). Phase 2 produces only this plan and `tasks.json`; application implementation belongs to Phase 3.

## 1. Product boundary and definition of done

Build a weekly, local intelligence pipeline for WA mine-water consultants and drillers. It identifies projects with evidence relevant to groundwater investigations, dewatering, pumping, bore drilling and water treatment. A score expresses research priority, not the probability of winning work or the existence of a tender.

Required deliverables after implementation:

- Project-level history and changes, with stable MINEDEX project identities.
- Explainable scores with evidence requirements, positive and negative contributions, caps and dates.
- A weekly digest in HTML and Markdown, a searchable static project list plus CSV/JSON, and a top-five Markdown briefing. Files are generated locally; no email is sent and nothing is published.
- Every alert identifies project, operator or explicitly unknown operator, attributed holder/reporting roles, reason, stage, source date or explicitly unknown date, observation date and evidence links.
- An offline test suite and reproducible sample outputs with honest provenance.

Use Python 3.11+, the standard library (`urllib`, `sqlite3`, `argparse`, `json`, `csv`, `html`, `hashlib`, `datetime`, `zoneinfo`) and pytest as the only required development dependency. No runtime dependency is necessary. No web framework, database service, GIS dependency, LLM inference, paid API, account, scheduler, email integration or hosted application is needed.

Development setup should use `python3 -m venv .venv` and activate that environment before installing pytest/running commands. The planning environment exposes `python3`, not a system `python` executable; the activated environment supplies the required `python -m pytest -q` command.

Read [RESEARCH.md](RESEARCH.md) and every file under `research/` before implementation. The observations below come from that supplied research, not a new verification of source availability. Preserve those files unchanged. In particular, the research samples are small, sometimes deliberately truncated API responses, not complete snapshots.

## 2. Permitted sources and attribution

Only the following four CC BY 4.0 datasets may supply product evidence. Dataset and licence metadata from their documented machine interfaces may be read to verify provenance; those metadata services are not additional opportunity sources.

### 2.1 Endpoints and fields

SLIP base:
`https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Industry_and_Mining/MapServer`

Use the listed layer URL for schema metadata (`?f=json`) and append `/query` for records. Fetch only explicitly needed fields and the discovered object-ID field; transport object IDs are not business identities.

| Dataset | Endpoint and query scope | Fields used | Identity and date semantics |
| --- | --- | --- | --- |
| MINEDEX (DMIRS-001) | SLIP base + `/0`; `where=1=1`; full public layer, attributes only | `site_code`, `site_title`, `short_name`, `site_type_`, `site_sub_t`, `site_stage`, `site_commo`, `target_com`, `commodity`, `proj_code`, `proj_title`, `latitude`, `longitude`, `web_link`, `extract_da` | Site: `site_code`; project: `proj_code`. `extract_da` is the dataset extraction timestamp, **not** the date a mine changed stage. No operator field exists in the recorded schema. |
| Mining Tenements (DMIRS-003) | SLIP base + `/3`; bounded point-intersection queries with `tenstatus='LIVE'` | `tenid`, `fmt_tenid`, `type`, `tenstatus`, `holdercnt`, `holder1`–`holder9`, `grantdate`, `startdate`, `enddate`, `legal_area`, `unit_of_me`, `extract_da` | Use trimmed `tenid`, with `fmt_tenid` for display. A holder is not a confirmed operator. Grant/start/end dates describe tenure, not mine approval. Do not request `addr1`–`addr9`. |
| WAMEX (DMIRS-033) | SLIP base + `/22`; paginated recent-release water-keyword subset | `anumber`, `title`, `project`, `operator`, `report_year`, `date_released`, `abstract`, `dpxe_abs`, `dpxe_rep` | `anumber`; report year and public release timestamp are distinct. The sample abstract is limited to 250 characters and describes 1993 work despite later release. A reporting operator can be historical. |
| EPBC Referrals Spatial Database — Public | `https://gis.environment.gov.au/gispubmap/rest/services/ogc_services/EPBC_Referrals/MapServer/0`; `PRIMARY_JURISDICTION='WA' AND CATEGORY='Mining'` | `REFERENCE_NUMBER`, `NAME`, `PRIMARY_JURISDICTION`, `CATEGORY`, `REFERRAL_DECISION`, `STANDARD_DETERMINATION`, `STATUS_DESCRIPTION`, `STAGE_NAME`, `REFERRAL_TYPE`, `YEAR`, `REFERRAL_URL` | `REFERENCE_NUMBER`; `YEAR` has year precision only. No precise decision date, operator or dewatering narrative is established by the samples. Preserve the raw status fields. |

CC BY 4.0 licence URL for all four: `https://creativecommons.org/licenses/by/4.0/`.

WA dataset catalogue URLs, also used as attribution links:

- `https://catalogue.data.wa.gov.au/dataset/minedex-dmirs-001`
- `https://catalogue.data.wa.gov.au/dataset/mining-tenements-dmirs-003`
- `https://catalogue.data.wa.gov.au/dataset/mineral-exploration-reports-wamex`

Licence verification uses `https://catalogue.data.wa.gov.au/api/3/action/package_show?id=<one-of-the-three-package-slugs-above>`. Record licence ID, licence URL, organisation and verification timestamp. For Commonwealth metadata the research documents these exact ArcGIS item endpoints:

- `https://www.arcgis.com/sharing/rest/content/items/ee02ed7773d44c6fa799bf558c70f81a?f=json`
- `https://www.arcgis.com/sharing/rest/content/items/ff8ef1108dd148c99fad93799d67ee94?f=json`

Verify that item/service metadata actually pertains to the EPBC dataset and states CC BY 4.0; retain the supporting metadata, credit and source relationship. Do not assume an unrelated item's licence applies. The research records the verification result but does not include full licence response bodies: capture these during implementation if reachable, otherwise mark the fixture metadata as synthetic and use the documented research provenance for the offline demo. Live ingestion requires a successful licence check for that source in the current fetch run; unknown or changed licensing disables that source for the run. An explicit incompatible licence also excludes its retained evidence from new reports until resolved. Never silently accept `isopen=true` as sufficient.

Documented WFS alternative:
`https://public-services.slip.wa.gov.au/public/services/SLIP_Public_Services/Industry_and_Mining_WFS/MapServer/WFSServer`.
Research verified WFS 2.0.0 type `SLIP_Public_Services_Industry_and_Mining_WFS:Minedex__DMIRS-001_`; it also lists `Mining_Tenements__DMIRS-003_`. Default CRS is EPSG:7844. **REST is the only v1 implementation path**; do not add an untested WFS fallback or silently mix CRSs. Retain this documented alternative for a later change if REST stops working.

### 2.2 Citation links and required credits

MINEDEX citation: use the supplied safe `web_link`, or construct
`https://minedex.dmirs.wa.gov.au/Web/common/jump.jsp?jumpType=SITE&id=<site_code>`.
WAMEX citation: use the supplied safe report link, or construct
`https://wamex.dmp.wa.gov.au/Wamex/Search/ReportDetails?ANumber=<anumber>`.
These HTML applications are citations only: never fetch them or follow their report/document links automatically.

For tenements, cite a reproducible layer `/query` URL selecting `tenid`, with URL-encoded parameters. For EPBC, cite a reproducible permitted layer query selecting `REFERENCE_NUMBER`. The recorded `REFERRAL_URL` is a malformed backslash URL to a generic referrals list; preserve it as raw data but do not turn it into a guessed project link. A valid generic portal URL still does not replace the record-specific query citation. No citation link is fetched during rendering.

Include source-specific credits wherever that source is used, and licence/provenance fields in machine outputs:

> Project locations and stages: Minedex (DMIRS-001), Department of Energy, Mines, Industry Regulation and Safety / current custodian recorded in Data WA, via SLIP public services, CC BY 4.0.

> Tenure and named holders: Mining Tenements (DMIRS-003), Department of Energy, Mines, Industry Regulation and Safety / current custodian recorded in Data WA, via SLIP public services, CC BY 4.0.

> Exploration report metadata: Mineral exploration reports (WAMEX) (DMIRS-033), Department of Energy, Mines, Industry Regulation and Safety / current custodian recorded in Data WA, via SLIP public services, CC BY 4.0.

> EPBC referral metadata: Referrals Spatial Database — Public, © Commonwealth of Australia (Department of Climate Change, Energy, the Environment and Water), CC BY 4.0. Source: the EPBC Referrals public spatial service.

In rendered credits replace “current custodian recorded in Data WA” with the verified organisation name if available; retain the research attribution when running recorded fixtures. Link each dataset and the licence. Add: “Data filtered, normalised and linked; scores and commentary added by WA Mine Water Opportunity Radar. Source agencies do not endorse these interpretations.” Retain any copyright year supplied by verified metadata; do not invent one from a report's generation date.

### 2.3 Enforced access boundary

Use a fixed source registry and a restrictive HTTPS URL validator before **every** outbound request, including redirects. Permit only the four exact REST layer/schema/query paths, the three specific CKAN package lookups, and the two listed EPBC metadata item paths. Query arguments come from code, not arbitrary supplied URLs. Reject redirects by default; an explicitly handled redirect must pass the same registry check before another request occurs.

Forbidden inputs/access: DWER/EPA custom-licence layers (including other layers on the same SLIP host), DWER Environment Online and all hostnames containing `environmentonline`, ASX announcements, wa.gov.au HTML, DASC, ResourcesOnline, corporate websites, paid feeds, accounts and keys. Never probe forbidden hosts, including robots or terms endpoints. Major Resources Projects and DISR spreadsheets are outside this four-source v1. The research log contains historical probes of excluded services; it must never be replayed as a fetch list.

## 3. Architecture and CLI contracts

Flow: permitted HTTP or offline fixture transport → immutable raw responses → validated source batches → SQLite project versions and evidence → semantic changes → deterministic scores → local reports.

Planned files:

```text
radar/
  __init__.py, __main__.py, cli.py, config.py, models.py
  sources/{__init__.py,registry.py,http.py,arcgis.py,minedex.py,tenements.py,wamex.py,epbc.py}
  store.py, schema.sql, normalize.py, ingest.py
  matching.py, changes.py, evidence.py, scoring.py
  reports.py, templates/{digest.html,projects.html}
tests/
  conftest.py, test_*.py
  fixtures/{manifest.json,recorded/,synthetic/,replay/}
samples/{README.md,provenance.json,recorded/ or live/,synthetic/}
pyproject.toml
README.md
```

Templates use the standard library; no template engine is required. Runtime data goes to ignored `data/raw/` and `data/radar.sqlite`; generated working reports to ignored `out/`. Only deliberate sample outputs and small fixtures are committed. Preserve existing ignore rules and add runtime SQLite sidecars, pytest caches and `out/` as needed.

All subcommands accept `--db PATH` and `--as-of YYYY-MM-DD`; dates default to the Perth calendar date. Internally use aware UTC timestamps; never substitute observation time for missing source dates.

- `python -m radar fetch --db data/radar.sqlite --raw-dir data/raw`: fetch and ingest a new run; build versions, links and changes. Only this command's live mode makes network calls.
- `python -m radar score --db data/radar.sqlite --as-of 2026-11-22`: score the latest usable run; no network. Optional `--reviewed-evidence PATH` attaches the constrained annotations in §6.
- `python -m radar report --db data/radar.sqlite --out out --as-of 2026-11-22 --days 7`: write all outputs from scores for that run/as-of/rule version. If scores are absent or inconsistent, fail with an actionable message; do not silently fetch.
- `python -m radar all --db data/radar.sqlite --raw-dir data/raw --out out --as-of 2026-11-22`: fetch → score → report with the same options and one selected run.
- `fetch` and `all` also accept `--fixture-dir tests/fixtures/replay/<snapshot>` and `--tenement-site-limit 100`. Fixture mode is entirely offline and visibly labelled. The site limit must be a nonnegative integer; zero disables tenure enrichment explicitly.
- `fetch`, `score` and `all` accept `--reviewed-evidence PATH`. Fetch applies validated `project_match` aliases before linking/comparison; score applies the approval/contractor annotations to established links. Score must reject aliases that differ from the selected run's stored linking annotations and explain that re-ingestion is required. A review alone is not a newly observed source development and earns no change bonus. `all` carries the same file through both phases.
- `python -m radar --help` and each subcommand's help work without a database or network.

Exit codes: 0 complete success (including explicitly disabled enrichment); 2 invalid arguments/input; 1 fatal core failure or inconsistent DB/report state; 3 successful core with failed, unverified or budget-truncated optional enrichment. In `all`, exit 3 still produces reports with coverage warnings. A failed MINEDEX batch is fatal: retain previous data and outputs, return 1, and do not imply a current fetch succeeded. Users can deliberately score/report the last successful run, whose age remains visible.

Keep interfaces small: source clients return batches of raw record dictionaries plus coverage/provenance; normalisers produce typed records; ingestion owns transactions; matching and change functions accept normalised inputs; scoring accepts a project/evidence/change bundle plus explicit as-of and returns a score breakdown; reporters consume a shared serialisable project view. No renderer contains scoring rules or makes network calls. Stubs introduced before their milestone must fail clearly, not claim success.

## 4. Fetching, scope and enrichment

### 4.1 Robust ArcGIS retrieval

Read each layer's schema and capabilities. Discover the object-ID field and record limit; do not assume `OBJECTID` (MINEDEX samples use `oid`). Use a default page size of 1,000, bounded by the service maximum. Prefer a complete `returnIdsOnly=true` inventory followed by serial object-ID batches. Check missing/extra/duplicate IDs and split batches if `exceededTransferLimit` is true. Where ID inventory is unsupported, use stable object-ID ordering, `resultOffset`, a pre/post count and a repeated-page/no-progress guard. Never stop merely because a response is shorter than requested if the transfer limit says more exists. Finish only when completeness checks agree; retry a moving/inconsistent inventory once, then fail the scope. Fail on duplicate stable business keys with conflicting values rather than choosing arbitrarily. Transport IDs changing between snapshots must not cause business changes.

Recognise ArcGIS `error` JSON even with HTTP 200; reject HTML, invalid JSON and missing required fields. Save each received page and metadata with request parameters, fetched-at, source licence identity and SHA-256. Timeouts: 30 seconds per attempt, at most three attempts for timeout/429/5xx, exponential delays of 1 then 2 seconds (bounded Retry-After up to 30 seconds), at least 0.2 seconds between live requests. No retry for 401/403 or other permanent errors. Inject transport, clock and sleep so tests are fast and offline. Repeated/truncated responses fail safely; they never become deletion evidence.

### 4.2 Bounded enrichment instead of a GIS subsystem

MINEDEX is the complete project spine. Fetch all WA Mining EPBC records as a small optional metadata set, without geometry. Fetch WAMEX only for releases in the preceding 730 days and a broad water-term predicate; recheck dates and text locally. Use capability-appropriate ArcGIS date syntax, covered by fixtures; if unsupported, fail optional enrichment rather than download the whole report archive or switch sources. Old research WAMEX data remains useful as an offline negative test.

Tenements use server-side point intersection, avoiding full statewide polygon downloads and a GIS library. Select up to 100 site points per run, ordered deterministically: active water-infrastructure sites first, then Under Development, then Proposed; tie-break by project code and site code. Other sites are unqueried, not assumed to have no tenure. Query each selected valid point with `geometryType=esriGeometryPoint`, `geometry={x:longitude,y:latitude,spatialReference:{wkid:4326}}`, `inSR=4326`, `spatialRel=esriSpatialRelIntersects`, `returnGeometry=false` and LIVE tenure filter. Validate coordinates; prefer correctly projected geometry if the schema later establishes a different coordinate CRS, otherwise skip with a warning. Do not reinterpret GDA2020 WFS coordinates as REST WGS84.

Each point lookup is its own complete or failed scope, with site ID and coordinates in its scope hash. Query results can contain multiple holders/tenements; retain all and say “tenement holder at sampled site”. Do not infer project ownership, an operator, a contract award or full project tenure coverage. Do not reuse a point lookup from an earlier weekly run as fresh evidence. Previous results may remain visible as stale context only. Budget truncation, attempted/complete/failed/skipped lookups and sites/projects covered must be reported. `exploration_only_at_sampled_sites` describes sampled evidence, never the entire project.

### 4.3 Conservative record linking

- MINEDEX site → project: exact nonempty `proj_code`; canonical key `minedex:<proj_code>`. Keep all site IDs. Missing project codes get `site:<site_code>` as visibly ungrouped watch records, excluded from priority digest/top-five until associated; never merge them by similar title.
- Tenement → project: the exact site point used in a successful intersection query. Store this method and sampled-site limitations with the link. Boundary intersections may be ambiguous; retain them as candidates, with no claim of ownership.
- WAMEX → project: unique exact normalised `project` versus MINEDEX `proj_title`. Normalisation case-folds, trims and collapses punctuation/whitespace; no substring, token overlap, geospatial proximity or removal of meaningful name components. If multiple projects match, retain an unresolved candidate and award no points.
- EPBC → project: the same unique exact normalised name rule. Exact matching will miss many expansions; expose the match rate. An optional local reviewed alias may map a specific source record ID to a project only with a reviewer note citing the two allowed records. It is a linking annotation, not a new data source. Store method `reviewed_alias` and show that label; never silently resolve fuzzy matches.

Operator display is `Unknown — not supplied by current MINEDEX layer`. Separately show dated tenement holders and, when confidently linked, “WAMEX reporting operator (report year YYYY): X”. Neither changes the confirmed operator field. Do not parse an operator out of a project title (for example a slash suffix) or confuse a holder, proponent, author or operator with a contractor.

## 5. SQLite and project-level change detection

### 5.1 Logical schema

Enable foreign keys and version schema changes with `PRAGMA user_version`. Use parameterised SQL and explicit transactions. JSON text columns are acceptable for small structured collections; a general ORM and migration framework are unnecessary.

| Table | Minimum content and constraints |
| --- | --- |
| `runs` | ID, mode (`live`, `recorded_fixture`, `synthetic_fixture`), as-of, started/finished UTC, status, coverage summary, schema/normalisation versions. |
| `source_batches` | Run/source/scope ID, query scope hash, complete/failed/disabled status, expected/received counts, licence verification, fetched-at, extraction range, raw manifest reference. Full MINEDEX scope is required for a usable run. |
| `source_records` | Batch ID + business record key unique; raw response pointer/hash, normalised JSON, semantic hash, source date value/kind/precision. Null is distinct from an empty string. |
| `projects` | Stable canonical ID, first-seen, last-seen; disappearance is not deletion. |
| `project_versions` | Unique run + project ID, title, site membership and stage distribution, representative stage/site, semantic hash, current/missing status, evidence freshness/coverage flags. Retain previous versions. |
| `links` | Project-version ID, source-record ID, method, supporting site/alias reference, confidence (`exact`, `reviewed`, `candidate`), ambiguity and scope. Candidates do not score. |
| `evidence` | Stable evidence identity, project-version ID, source record/field and exact excerpt or field value, source date + precision, observed-at, URL, licence ID, role/type and validity flags. |
| `changes` | Stable event key, project ID, previous/current versions, event type, old/new values, supporting site/evidence IDs, observed-at, digest eligibility. Unique key prevents duplicate creation on re-ingestion. |
| `score_sets` | Complete scoring execution ID, selected run, as-of, rubric version, reviewed-evidence hash, completed timestamp/status. Publish the whole set atomically. |
| `scores` | Unique score-set + project-version; total/tier, positive/negative contributions, caps, evidence/change IDs and reason. Replacing the same input set is atomic. |

Fixture mode must not contaminate a live database: reject mixing provenance modes in one DB (recorded and synthetic demonstrations also use separate DBs). Store UTC ISO dates and explicit precision; ArcGIS epoch milliseconds include valid pre-1970 tenure dates. Preserve EPBC year-only dates as a year, never January 1. Stable IDs and foreign keys must survive process restart.

Standalone report selects the latest completed score set matching the selected run/as-of/current rubric; it never combines rows from different annotation hashes. `all` passes the exact score-set ID it just produced. Include that identity and annotation hash in report provenance.

### 5.2 Semantic comparison and event rules

Normalise whitespace/case only where semantics permit; preserve raw display text, IDs and source values. Canonical hashes use sorted sets/maps and stable JSON. Exclude transport IDs, response order, retrieval time and `extract_da` from business-change hashes. Changes in extraction time alone update freshness, not intelligence. Include site stage, title/type/subtype, project membership, coordinates, commodities and relevant linked evidence fields; classify cosmetic/title/coordinate corrections separately from substantive water/stage evidence.

Compare consecutive successful snapshots **of the same source and scope**. Build one project event bundle per project, with constituent site changes, rather than duplicate alerts per site. Track:

- A newly observed project after the baseline, and newly added/removed site membership.
- Site stage changes with explicit old and new values; observed restart from Shut/Care and Maintenance into Proposed/Under Development/Operating; development progression and commissioning separately.
- A newly added or substantively changed classified water-infrastructure site. A deposit merely named “Borefield” is not infrastructure.
- Confidently linked new/changed EPBC or WAMEX evidence, and holder/tenure changes only for point scopes successfully observed in both snapshots at unchanged coordinates.
- A project or site absent from a complete MINEDEX scope: “not present in latest extract”, never “closed”. Reappearance is “reappeared”, not a new project. Reassignment of a site to another project is a membership change, not a discovery of a new water asset.

The first successful snapshot creates a labelled baseline and zero new-project/change alerts; reports may show its current priorities under “Initial baseline — changes not yet available”. A newly enabled enrichment source or a newly sampled point also starts a baseline, not a historical change. WAMEX aging out of the rolling query window is not a removal. Fetch failures, unqueried sites and unmatched records never create negative change events.

Mixed-stage projects display `Mixed` plus counts; their scoring stage is the highest-priority active stage among sites: Under Development, then Proposed, then Operating, then Undeveloped, then Care and Maintenance, then Shut; retain the responsible site ID and explain that this is a site-level stage. Apply project dormancy only when all known sites are Shut/Care and Maintenance. A project-wide stage cannot conceal a new water-site change.

On repeated identical content, preserve first observation of each event: no duplicate alerts and no refreshed “recent change” bonus. If a state genuinely changes back and later changes again, create a new event keyed by the consecutive version pair. Report regeneration for the same run/as-of/window is idempotent; it does not consume alerts. No sent-email ledger is needed.

Core ingestion, version creation and change creation are transactional. Failed source scopes retain their last successful history; optional stale evidence can be displayed with its original date but cannot contribute positive points or appear as fresh changes. An explicit incompatible licence suppresses even that source's retained display content in new reports. Keep raw data/history for audit without redistributing the excluded source.

## 6. Evidence and scoring rubric `v1`

### 6.1 Evidence admission

Every scored fact must trace to a permitted, licence-verified source record, a precise field/value or exact excerpt, a confident project link and a source/observation date distinction. Missing, ambiguous, negated or stale facts yield no positive points. Store rejected/candidate facts with reasons for audit; do not silently treat unknown as false.

Classify water infrastructure only when `site_type_` is Infrastructure and subtype/title explicitly identifies a borefield, dewatering facility, groundwater abstraction facility, water supply infrastructure, water treatment plant, water pipeline or water pumping station. Match case-insensitive word/phrase boundaries, supporting singular/plural and dewater/dewatering forms. “Water” alone, an unspecified pipeline, a generic pump, exploration drilling, tailings alone, or a deposit titled “Borefield” does not qualify. The sample Plutonic processing plant title contains an explicit borefield and can qualify; the sample Deposit/Borefield cannot. Record exactly which field/phrase established the classification. Proposed/Under Development/Operating water sites qualify for active scope; dormant and undeveloped water sites remain context only.

WAMEX supporting terms: `dewater`/`dewatering`, `borefield`, `groundwater investigation`, `groundwater abstraction`, `water treatment`, `water pumping`, `water supply bore` and `hydrogeological investigation`. Generic “drilling” or “water” does not qualify. Exclude matched clauses containing explicit negation (`no`, `not`, `without`, `not required`) or uncertain scope (`may`, `might`, `possible`, `potential`); ambiguous/truncated clauses remain visible but score zero. Recently performed work can be historical context with an 8-point supporting signal, never an assertion that more work is required. Both release date and report year must pass the freshness gate below. Keep the keyword dictionary and matching decisions testable, not spread across renderers.

EPBC `Controlled Action`, `Assessment Approach`, `Post-Approval` or presence in the database must not be translated into “approved mine” or “dewatering required”. Show actual source wording. An EPBC referral is not a water licence.

Optional local reviewed annotations are restricted to `project_match`, `approved_water_scope` and `named_contractor`. Use a versioned JSON file with project ID, source ID, business record key, field names, exact cited values/excerpts, reviewer note and reviewed-at. Validate that every citation exists unchanged in stored CC BY records; a note/review timestamp is not itself source evidence. Bind annotations to record content hashes so changed text invalidates them. Do not fetch annotation URLs or allow free-form imported documents. Review mode works offline; fixture annotations must be labelled synthetic.

- `project_match` records the explicit source-record → MINEDEX-project alias described in §4.3.
- `approved_water_scope` requires an authoritative EPBC record explicitly stating approval of the identified development/action **and** an explicit planned/required dewatering or other mine-water scope for that same action. Store both excerpts and the shared referral identity. WAMEX is not an approval authority; tenure grants and MINEDEX development stages are insufficient. A separately inferred borefield plus a generic `Post-Approval` label fails. The recorded schemas/samples demonstrate no qualifying narrative: this rule is expected to remain inactive on live v1 data. Do not invent a narrative field, retrieve portal documents or relax the rule to manufacture high scores.
- `named_contractor` requires an explicit name **and** contractor/consultant/driller appointment for the relevant water scope in a permitted record. Distinguish appointment from reporting operator, holder, author, speculative bidder and historic unrelated work. Require source date within 730 days (for WAMEX, also a recent report year), and a confident same-project/scope link. An old or undated appointment is shown as historical/undated context with no deduction. A name alone is insufficient. The deduction means reduced research priority, not “contract closed”.

### 6.2 Weights, caps and tiers

All positives are once per project per category, not per site, report, term or referral. Choose the maximum within each mutually exclusive row. Never sum duplicate evidence for the same fact.

| Code | Points | Required evidence |
| --- | ---: | --- |
| `stage` | +20 / +12 / +6 / 0 | Fresh MINEDEX site Under Development / Proposed / Operating / other; choose one using §5 stage precedence. Show contributing site. Stage does not establish statutory approval. |
| `water_scope` | +40 **or** +25 **or** 0 | +40 for valid reviewed approved-water-scope evidence; otherwise +25 for a fresh, explicitly classified active MINEDEX water-infrastructure site. These alternatives do not stack. |
| `tenure` | +4 **or** +1 **or** 0 | +4 for a current LIVE MINING LEASE, COAL MINING LEASE, GENERAL PURPOSE LEASE or MISCELLANEOUS LICENCE at a sampled site; otherwise +1 if successfully sampled LIVE tenure is exclusively EXPLORATION LICENCE/PROSPECTING LICENCE. Unknown/other types score 0. Preserve actual types; tenure is not development or water approval. |
| `wamex_support` | +8 | Confidently linked, unambiguous water-term evidence with release date in the preceding 730 days inclusive and report year from `as_of.year - 2` through `as_of.year`, inclusive. Older work newly released cannot qualify. |
| `epbc_context` | +6 | Confidently linked current WA Mining referral with recognised active assessment/post-approval status. Initial allowlist: `STAGE_NAME='Assessment Approach'` with `STATUS_DESCRIPTION='Assessment Method Determined'`, or `STAGE_NAME='Post-Approval'` with `STATUS_DESCRIPTION='Condition variation being considered'` (the recorded examples). Unknown, withdrawn, refused, lapsed and completed statuses score 0. Expanding this mapping requires a recorded fixture and review. This is context, not fresh approval or water scope. |
| `recent_change` | +15 / +10 / +8 / +5 / 0 | Maximum qualifying event first observed in the preceding 30 days: +15 same-site transition into Under Development or restart from Shut/Care and Maintenance into an active stage; +10 new/substantively changed active water infrastructure; +8 Proposed/Under Development → Operating commissioning; +5 newly observed project after baseline or Undeveloped → Proposed. Cosmetic edits, membership reassignments, source baselines and refresh timestamps score 0. |
| `dormant` | −25 | All known MINEDEX sites are Shut/Care and Maintenance, with no current active site. Missing/failed source data is not dormancy. An observed active restart removes the condition. |
| `contractor_named` | −20 | Valid recent reviewed named-contractor evidence for relevant water scope; apply once. Report the name, scope and citation, without declaring an open or closed procurement. |

Calculate in this order:

1. Sum eligible positives; cap at 100.
2. If no qualifying direct water scope (`water_scope=0`), cap at 34. Ungrouped sites also cap at 34. If only sampled exploration/prospecting tenure and Undeveloped/unknown stages are supported, with no direct water scope, cap at 15; WAMEX-only exploration does not escape this cap. Record applicable caps explicitly.
3. Subtract dormant and contractor deductions, floor at 0. Applying deductions after positive caps ensures an otherwise identical positive-scoring project with an appointed contractor is visibly lower.
4. Assign tier: `High` ≥60 with direct water scope; `Priority` 35–59 with direct water scope; `Watch` 1–34; `Background` 0. Ungrouped sites and missing-current-extract projects are excluded from priority outputs regardless of stored historical score. Missing projects receive current score 0 with an unavailable-data explanation.

Freshness: MINEDEX/tenement positives require a valid extraction date no more than 35 days before as-of and a successful batch observed no more than 35 days before as-of. WAMEX/EPBC evidence likewise requires a current successful batch within 35 days; WAMEX additionally uses both date gates above. An unknown MINEDEX extraction date cannot produce positive stage/water points. EPBC with only `YEAR` is explicitly year-dated; current batch observation supports presence/status context but does not establish a recent source event. Reviewed approval evidence must refer to the current valid EPBC record, with unchanged supporting text and no contrary withdrawal/refusal; review time never refreshes an old source fact. Recent-change bonuses require the current evidence still to support that signal. Unknown or future publication/extraction dates and contradictory status are flagged, not rewarded; legitimate future tenure expiry dates are valid. An as-of before the selected run's observed date is invalid.

Examples (fresh, confidently linked evidence; omitted terms are zero):

- Undeveloped site plus exploration tenure: 1, Watch; exploration context alone never becomes a priority.
- Under Development + mining lease + active EPBC context, without water scope: 30, Watch.
- Proposed borefield: 12 + 25 = 37, Priority; no claim that it is approved or procuring.
- Under Development + borefield + qualifying recent development transition + mining lease: 20 + 25 + 15 + 4 = 64, High.
- Approved development explicitly requiring dewatering + Under Development + mining lease: 40 + 20 + 4 = 64, High. This is a **synthetic rule example**, not a research finding.
- The preceding 64-point case with an appointed water contractor: 44, Priority.
- Operating borefield, no change/enrichment: 6 + 25 = 31, Watch. A 1994 WAMEX report released recently adds 0.

All v1 project views contain `contract_status="not_verified"` and “Contract availability not verified.” There is no v1 path to emit “open tender”, “contract available” or “seeking bids”. Authoritative evidence would be needed for such a future capability. No source currently establishes one. Synthetic testing must not introduce an open-contract rendering path.

## 7. Output contracts

Write output files atomically using a temporary directory and replacement only after successful rendering. Escape source text and validate displayed link schemes/hosts separately from the stricter fetch allowlist. Do not execute source HTML or interpolate unescaped JSON into scripts. Prevent CSV formula execution for cells beginning with `=`, `+`, `-`, `@`, tab or carriage return. No external JavaScript, fonts, analytics, fetch calls or remote images.

Every machine project object has: `project_id`, `project_name`, `operator` (nullable), `operator_status`, `holders` and `reporting_operators` with roles/dates, `stage`, `stage_distribution`, `score`, `tier`, `score_breakdown`, `reason`, `source_dates` (value/kind/precision/source), `observed_at`, `evidence` (IDs/excerpts/URLs/licences/match method), `changes`, `coverage`, `data_mode`, `contract_status` and `attributions`. Expose rubric version and report as-of in a shared report metadata object. The row's primary source date is labelled MINEDEX extract date or unknown; retain other dates per evidence rather than picking the most recent to disguise old information.

| File | Contents |
| --- | --- |
| `digest.md`, `digest.html` | Weekly changed Priority/High projects, one entry per project; a short watch-change section; source coverage and attributions. Include all required alert fields and exact old → new change text. On first run show a clearly titled initial baseline priority section. On later unchanged weeks say “No qualifying changes this week”; do not recycle old alerts as new. |
| `projects.json` | All current projects plus explicitly flagged missing/ungrouped records, metadata, full evidence and score explanation; deterministic ordering. |
| `projects.csv` | Flat equivalent: identity, names/roles, stage, score/tier, reason, date labels, links, coverage and provenance; structured collections as escaped JSON strings. Include licence/attribution columns and refer to JSON for full details. |
| `projects.html` | Self-contained static page with case-insensitive search over project/ID, holder/reporting operator, stage and reason, plus tier/stage filters and deterministic score/name sorting. Embed escaped data so opening via `file://` works. Show a visible result count and useful no-results message. |
| `top-5.md` | Up to five current Priority/High projects, ordered by score descending, then most recent qualifying change descending (null last), then project ID. Include “why now” or “baseline/current evidence; no recent change”, key evidence, uncertainty and contract disclaimer. Never pad to five with weak projects. Unlike the weekly digest, this is a current-priority briefing, not exclusively new changes. |
| `provenance.json` | Run ID, as-of/window, rubric version, source/scope counts and failures, timestamps, mode, raw hashes, licence checks and sample limitations. |

Use a trailing window of Perth calendar dates, inclusive: `as_of - (days - 1)` through `as_of`. Change observation time determines weekly inclusion, not extract or publication dates. Baseline reports must say that change monitoring needs a second complete snapshot. Sorting, IDs and content are repeatable given the same run, dates and annotations; omit volatile render timestamps from deterministic content.

## 8. Fixtures, tests and sample policy

All tests must pass with network unavailable. `tests/conftest.py` blocks socket connection and DNS entry points by default; HTTP tests use injected fake transports, not exceptions allowing live tests. Test CLI functions in process so the guard applies; a subprocess may be used for `--help` only. No test depends on current time, external services, paid credentials or optional browser tooling.

`tests/fixtures/manifest.json` describes every fixture: origin (`recorded` or `synthetic`), original source path/URL, capture date or explicit unknown, SHA-256, licence/research citation, and any transformation. Copy the four allowed feature samples and MINEDEX water-type sample from `research/samples/` unchanged into `recorded/`; include useful count/stage samples. Do not copy/replay the research request log as network instructions. Original recorded envelopes retain `exceededTransferLimit=true` where present and must fail a full-fetch completeness test.

For an offline recorded demonstration, a replay manifest may explicitly select only the recorded business IDs and feed their unchanged facts through normalisation under a `fixture:selected-records` scope. This is a labelled partial demonstration, never a successful full live snapshot. Do not remove truncation flags or invent missing fields to claim complete acquisition. Separate synthetic replay snapshots A/B/C exercise complete pagination, project/site changes and later identical content; synthetic entities use unmistakably fictional names and IDs. Keep approved-water and contractor cases synthetic unless an actual permitted record proves them.

Required test groups:

- Source policy: forbidden layer on an allowed host, arbitrary CKAN package, unsafe URL and redirect, environmentonline host variant, HTML/ArcGIS error responses, 403 no-retry, 429 bounded retry, timeouts, schema drift, changed/unknown licence.
- Pagination: discovered OID, multiple pages/batches, transfer limits, final short page, duplicate/repeated pages, missing IDs, changing inventory/count and failed last page. Never publish a partial core snapshot.
- Normalisation/storage: nulls, Unicode, whitespace, dates before 1970, year precision, missing dates, semantic hashes, foreign keys, rollback, same business key with conflicting records, restart persistence, provenance-mode isolation.
- Links/coverage: exact match, ambiguous duplicate names, unmatched EPBC expansion, invalid/reviewed alias, expired annotation hash, multiple tenement holders, point-query parameters, budget exhaustion, missing coordinates and partial coverage. Unknown operators remain unknown.
- Changes: first baseline, new project, stage progression, restart, water site, membership reassignment, project absence/reappearance, reordered records, extract-date-only updates, mixed stages, enrichment first observations, rolling WAMEX window and repeat-run idempotency.
- Scoring: table-driven examples in §6, every weight/cap, no double counting, all tier boundaries, stage does not imply approval, old work newly released, negation/uncertainty/truncation, deposit called Borefield, generic drilling/pipeline noise, source staleness, contractor role/date requirements, fake approval rejection and post-cap deductions.
- Reports/CLI: required fields across all formats, proper attributions, escaping, CSV safety, filters without network assets, zero/fewer-than-five results, weekly boundary and empty week, baseline label, degraded coverage, missing/stale scores, stable output, offline A/B/C end-to-end runs, clear exit codes.

Exact full-suite command from repository root for **every milestone**: `python -m pytest -q`.

Sample generation happens outside pytest. In M7 attempt one bounded live run against permitted interfaces (standard retry limits); if successful, commit small real generated outputs and a provenance manifest in `samples/live/`. If live fetching fails, generate `samples/recorded/` from the already fetched research facts and label it “Recorded fixture data — partial research sample captured 22 November 2026; not current or statewide”. Do not mix live and fixture facts silently. Always provide a separate `samples/synthetic/` change demonstration if two real time-separated snapshots are unavailable; label every rendered file and machine record synthetic. Never modify real facts to invent approvals, stage changes or contractor appointments. Include commands and source hashes in `samples/README.md`; do not commit the runtime database or full raw downloads.

## 9. Sequential milestones and model assignments

The driver executes M1 → M7, reviews each result and commits each accepted milestone. Implementers must **not commit or push**. Prompts in `tasks.json` are self-contained and repeat the non-negotiable source, test and commit rules. Each milestone leaves the full offline suite passing; do not create failing tests for future modules. Escalation is justified by a concrete unresolved issue, not by convenience.

| ID | Scope and principal files | Cheapest reliable assignment | Acceptance criteria |
| --- | --- | --- | --- |
| M1 | Packaging, CLI help/contracts, shared types/config, fixture manifest and recorded/synthetic corpus; `pyproject.toml`, `radar/{__init__,__main__,cli,config,models}.py`, `tests/conftest.py`, fixture tests, ignore rules | `gpt-6-luna`, `high` | Import/help works without network; fixtures have provenance and untouched recorded payloads; synthetic A/B/C are labelled; network guard works; pytest passes. No real source/client/scoring implementation yet. |
| M2 | Registry, URL/licence policy, urllib transport, robust ArcGIS retrieval and four source clients; `radar/sources/*`, source/pagination/policy tests | `gpt-6.1-sol`, `high` | Only approved machine paths reachable; redirects/forbidden inputs blocked; full core pagination verified or rejected; bounded enrichment and raw provenance; failed optional source represented explicitly; pytest passes offline. |
| M3 | Normalisation, schema, transactional snapshot ingestion, replay loading; `radar/{store,normalize,ingest}.py`, `radar/schema.sql`, storage/replay tests | `gpt-6.1-sol`, `high` | Stable identities, dates and hashes; atomic successful-core snapshots; partial failures cannot replace the core; fixture/live isolation; original sampled truncation not misrepresented; repeated ingestion and DB reopen safe; pytest passes. |
| M4 | Project aggregation, exact/reviewed linking and change events; `radar/{matching,changes}.py`, `radar/evidence.py` linking portion, tests | `gpt-6.1-sol`, `high` | No false ownership/operator claims; ambiguity and budgets visible; baseline has no changes; A/B/C produces correct bundled changes then no duplicates; scope-aware failures/absence/reassignment handled; pytest passes. |
| M5 | Evidence validation, reviewed annotations, scoring/explanations; `radar/{evidence,scoring}.py`, scoring/evidence tests | `gpt-6.1-sol`, `xhigh` | Exact rubric and order; guarded approval/contractor evidence; historical/ambiguous/negated evidence cannot inflate scores; all numeric examples and boundary tests pass; scores reproducible and persisted; no open-contract path. |
| M6 | Shared project views and every output format; `radar/reports.py`, local templates, report tests | `gpt-6-luna`, `high` | Searchable offline HTML, CSV/JSON, both digests, top-five and provenance; required fields, attribution, dates, score reasons and labels everywhere; escaping and deterministic output tests pass. Keep intelligence logic in existing modules. |
| M7 | CLI orchestration, end-to-end checks, operational README and generated samples; `radar/cli.py`, integration tests, `README.md`, `samples/*` | `gpt-6.1-sol`, `high` | All commands/exit codes work; offline A/B/C reruns and degraded/fatal cases pass; bounded real sample attempt documented; honest sample fallback and separate synthetic demo committed by driver; full suite passes. |

Model rationale: fixture scaffolding and rendering have concrete contracts suitable for Luna high; network policy, persistence and comparison need Sol high; subtle evidence admission, score caps and procurement language warrant Sol xhigh. No implementation milestone needs Astra by default. After M7 the top-model orchestrator reviews the complete diff, source boundary, scoring evidence, samples and test results; the driver addresses findings before considering v1 complete. That final review is part of Phase 3, not permission to implement during this planning session.

## 10. Risks and deliberate limits

- **No demonstrated approval narrative:** the strongest rule may have zero live matches. Keep it gated and show useful infrastructure/stage priorities; never substitute DWER, portal scraping or title inference.
- **Unknown operators and narrow joins:** MINEDEX lacks operators; exact names miss many referrals; sampled tenure does not establish ownership. Report role/date/method and match/coverage rates. Accept false negatives rather than unsupported entity merges.
- **Old and truncated records:** WAMEX abstracts can omit context and report long-completed work; EPBC YEAR is not a decision date. Conservative zero-point cases and precise labels are intentional.
- **Public service failures/schema/licence drift:** use recorded fixtures for reproducibility, bounded retries, explicit completeness checks and source-level degradation. Keep forbidden fallback routes unavailable.
- **Moving datasets:** no ArcGIS transaction guarantees a perfectly consistent statewide snapshot. Inventory/count validation catches common truncation; raw capture and semantic history preserve auditability. Do not claim the observation date is the real-world change date.
- **Spatial ambiguity and cost:** boundary points, coordinate uncertainty and the 100-site budget leave gaps. Retain the sampled-site caveat; a future polygon join is outside v1.
- **Rubric calibration:** weights are transparent prioritisation choices, not measured predictions. Version them and preserve evidence; buyer feedback/calibration can follow a working sample.
- **Baseline and sample limitations:** one research capture cannot prove change detection on real history. Demonstrate algorithmic changes using separately labelled synthetic snapshots, and describe the need for another live weekly run.
- **Scope discipline:** no email sending, scraping, hosted search, user accounts, automatic purchasing, tender claims or advanced GIS. Deliver local evidence-bearing files first.
