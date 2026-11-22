# WA Mine Water Opportunity Radar — Research memo

**Product:** an intelligence service that identifies Western Australian mining developments likely to need groundwater investigations, dewatering, pumping, bore drilling or water treatment. Intended buyers are mine-water consultants and drillers (examples: AQ2, Rockwater, PPS Water).

**Date:** 22 November 2026, Australia/Perth (UTC+8).  
**Method:** Codex CLI (`gpt-6-astra`, reasoning effort `xhigh`, ChatGPT account `lennotau@gmail.com`) ran live, unauthenticated HTTP probes and catalogue lookups from this environment, and used web search. The session (`01a2024d-68f1-7db3-b420-3519cc848e6c`) was cut short by a ChatGPT usage limit after about 7.5 minutes and 223,049 billed tokens, before Codex could write this memo. The findings below are compiled from that session’s live responses, Data WA / SLIP payloads, and cited search snippets. No request was made to DWER Environment Online (the probe helper refused any URL containing `environmentonline`).

Raw request metadata is in [`research/live-tests.json`](research/live-tests.json). Small response samples are in [`research/samples/`](research/samples/).

---

## 1. Executive summary

A licence-compatible v1 is **feasible** using WA government open spatial APIs that responded here without authentication, under **Creative Commons Attribution 4.0 (CC BY 4.0)**:

- **MINEDEX (DMIRS-001)** — 48,564 public sites in 4,904 projects; stable `site_code` / `proj_code`; operating stage; commodities; official evidence links. Live ArcGIS REST and WFS both returned HTTP 200 in 0.2–0.7 seconds. This is the right spine for project-level change detection.
- **Mining tenements (DMIRS-003)** — 30,613 records, including holder names, tenure type and LIVE/pending status (CC BY 4.0).
- **WAMEX (DMIRS-033)** — 119,224 open-file exploration reports with operator, abstract and official report links (CC BY 4.0). Abstracts can mention dewatering, but the first hit was a 1993 report, so WAMEX is supporting evidence, not a timely contract signal.
- **EPBC referrals (Commonwealth)** — 8,111 referrals nationally, 1,581 in jurisdiction `WA`, 406 of those categorised `Mining`, also CC BY 4.0 with a required attribution to DCCEEW.

The spatial MINEDEX layer **does not expose operator names or an explicit dewatering-required flag**. Water-related evidence *does* appear as infrastructure sites (for example `site_sub_t = Borefield`, titles containing “Borefield”). Strong “approved development describing dewatering” alerts therefore need a second, licence-compatible text source. Federal EPBC referrals can help. WA EPA / DWER water-licence layers cannot be used in a paid product without prior written permission (see below).

**The most important licence constraint:** several DWER and EPA datasets on Data WA are labelled “Open” in the catalogue UI but are licensed **Custom (Active Acceptance)**, `isopen=false`. The 2026 agreement’s permitted use is *internal business, academic or personal purposes only and not for any distribution, sale, licence, hire, let or trade to a third party*, and derived publications need the Licensor’s prior permission. **Do not use those layers in a commercial weekly digest until DWER grants permission in writing.**

**ASX.com.au is not a permitted v1 source.** ASX terms prohibit robots/scrapers and commercial reuse of site content without written consent. Company announcements should only be used later if a separately licensed official feed is obtained.

**DWER Environment Online is forbidden** for automated monitoring. This project must not scrape, crawl, poll or otherwise automatically access it.

**Honest competitive gap:** Projectory, MiningEdge, Mining Intelligence and Prospect Signal AU sell broad project, tender or ownership intelligence. None of the public pages reviewed describes a mine-water / dewatering opportunity score with evidence links. The gap is real, but those products already occupy the “project radar” budget of many suppliers. A A$349/month water-specific digest has to be narrower and better evidenced than a general project list.

---

## 2. Source catalogue

Live tests were run between 16:09 and 16:16 AWST on 22 November 2026. “Auth” means whether a key or login was required. SLIP query endpoints used `maxRecordCount = 10000` and honour `resultOffset` (pagination was verified on MINEDEX).

### 2.1 Recommended or usable in a paid v1 (with attribution)

| Source | Access method (verified URL) | Licence | Live test | Relevant fields / notes |
|---|---|---|---|---|
| Minedex (DMIRS-001) | Data WA package: [minedex-dmirs-001](https://catalogue.data.wa.gov.au/dataset/minedex-dmirs-001). ArcGIS layer 0: `https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Industry_and_Mining/MapServer/0`. WFS type `Minedex__DMIRS-001_`. | **CC BY 4.0**, `isopen=true`, org: DEMIRS / DMPE. Licence URL: https://creativecommons.org/licenses/by/4.0/ | Count 48,564 in 0.50s; 3-record sample 0.55s; distinct `proj_code` 4,904; WFS GetFeature 0.63s. No auth. | `site_code`, `site_title`, `site_type_`, `site_sub_t`, `site_stage`, `commodity` / `target_com` / `site_commo`, `proj_code`, `proj_title`, lat/long, `web_link` (official MINEDEX jump URL), `extract_da`. Sample extract date **2026-11-19 00:00 UTC**. **No operator field in this layer.** |
| Mining Tenements (DMIRS-003) | [mining-tenements-dmirs-003](https://catalogue.data.wa.gov.au/dataset/mining-tenements-dmirs-003). ArcGIS layer 3 of the same MapServer. WFS type `Mining_Tenements__DMIRS-003_`. | **CC BY 4.0**, `isopen=true` | Count 30,613 in 0.24s; LIVE sample 0.87s. CRS for WFS default: EPSG:7844 (GDA2020). | `fmt_tenid`, `type` (e.g. exploration licence vs mining lease), `tenstatus`, `holder1`–`holder9`, grant/start/end dates, `legal_area`. Holder names can stand in for operator when joining by location. |
| Mineral exploration reports (WAMEX) (DMIRS-033) | [mineral-exploration-reports-wamex](https://catalogue.data.wa.gov.au/dataset/mineral-exploration-reports-wamex). ArcGIS layer 22. | **CC BY 4.0**, `isopen=true`. Layer description also states “License: Creative Commons Attribution”. | Count 119,224 in 0.51s. A `abstract LIKE '%DEWATER%'` sample returned HTTP 200 in 0.40s. | `anumber`, `title`, `project`, **`operator`**, `report_year`, `date_released`, `abstract`, `dpxe_abs`, `dpxe_rep` (official WAMEX abstract/report URLs). Useful keyword evidence; often historical. |
| Major Resources Projects | [major-resources-projects](https://catalogue.data.wa.gov.au/dataset/major-resources-projects) | **CC BY 4.0**, `isopen=true` | Catalogue record OK. The advertised DASC download (`dasc.dmirs.wa.gov.au/home?productAlias=MINEDEXMajorResProj` and `/download/File/3986`) returned **HTTP 403** (Incapsula) from this environment. | Keep as a CC BY candidate if a SLIP/DASC path can be fetched later. Do not treat as a v1 dependency. |
| EPBC Referrals Spatial Database — Public | ArcGIS item and MapServer: `https://gis.environment.gov.au/gispubmap/rest/services/ogc_services/EPBC_Referrals/MapServer/0` | **CC BY 4.0**. Item licence text requires credit to the Australian Government Department of Climate Change, Energy, the Environment and Water and a link to the source. Copyright: © Commonwealth of Australia (DCCEEW) 2026. | 8,111 referrals in 1.13s; `PRIMARY_JURISDICTION='WA'` = 1,581; `WA` + `CATEGORY='Mining'` = 406; West Angelas sample 1.06s. No auth. `PRIMARY_JURISDICTION='Western Australia'` returned 0 — use the code `WA`. | Referral name, reference number, jurisdiction, category, and geometry. Suitable evidence that a mining proposal is in the federal assessment process. Not a water-licence register. |
| Data WA CKAN API | `https://catalogue.data.wa.gov.au/api/3/action/package_show` and `package_search` | Catalogue metadata; dataset licences vary by package. | Multiple package_show / package_search calls returned HTTP 200 in ~1–2s. | Use to refresh licence, organisation and resource URLs, not as the opportunity database. |
| CC BY 4.0 legal code | https://creativecommons.org/licenses/by/4.0/legalcode.en | CC BY 4.0 itself | HTTP 200, 49,582 bytes. | Commercial use and reuse of licensed material is allowed if you give attribution, indicate changes, and do not imply endorsement. |

**MINEDEX site stages (live group-by, 22 Nov 2026):** Proposed 4,677; Under Development 234; Operating 4,562; Care and Maintenance 2,138; Undeveloped 16,704; Shut 20,249.

**MINEDEX water-related sites (sample query):** `site_type_` / `site_sub_t` / `site_title` matching water or borefield returned infrastructure such as “Murrin Murrin Borefield Infrastructure Corridor” (Operating, `site_sub_t=Borefield`), “DeGrussa Borefield” (Proposed), and “Plutonic Plant and Borefield”. These are concrete, licence-compatible water-demand signals.

**Official evidence links already in the payloads:**  
`https://minedex.dmirs.wa.gov.au/Web/common/jump.jsp?jumpType=SITE&id={site_code}`  
`https://wamex.dmp.wa.gov.au/Wamex/Search/ReportDetails?ANumber={anumber}`

Do **not** scrape the MINEDEX or WAMEX HTML applications (both sit behind Incapsula / access gateways). Use the deep links only as citations.

### 2.2 Technically reachable but **not cleared** for a paid product

These layers responded on the public SLIP services, but Data WA marks them **Custom (Active Acceptance)**, `isopen=false`, organisation DWER. The [DWER Active Acceptance Licence Agreement 2026](https://catalogue.data.wa.gov.au/dataset/dwer-active-acceptance-licence-agreement) (PDF also catalogued as a Data WA resource; text extracted from the copy fetched via the catalogue) defines:

> **Permitted Use** means the use for internal business, academic or personal purposes only and not for any distribution, sale, licence, hire, let or trade to a third party, regardless of charge or not.

Clause 4: if information or products derived from it are to be used for publication, promotion, or external display, **Licensor permission must be obtained prior**.

Until written permission is obtained, treat the following as **internal research only**, not as inputs to a sold digest:

| Source | Access (live) | Licence on Data WA | Why it would have been useful |
|---|---|---|---|
| EPA Referred Significant Proposals (DWER-120) | SLIP Environment MapServer layer 115 and Environment WFS; catalogue [epa-referred-significant-proposals](https://catalogue.data.wa.gov.au/dataset/epa-referred-significant-proposals) | Custom (Active Acceptance), `isopen=false`. Metadata modified 2026-11-16. Schema HTTP 200 in 0.49s. | Closest official WA “proposal referred / assessment stage” layer. |
| Environmental Impact Assessments, Outcomes and Changes (EIAOC) (DWER-088) | Catalogue record only in this session | Custom (Active Acceptance) | Assessment outcomes and changes — strong dewatering-condition evidence if text is present. |
| WRIMS – Groundwater Resources (DWER-084) | Water MapServer layer 49; HTTP 200 in 0.50s | Custom (Active Acceptance) | Groundwater management units and extraction limits near a project. |
| Groundwater Salinity Statewide (DWER-026) | Water MapServer layer 40; HTTP 200 in 0.23s | Custom (Active Acceptance) | Treatment / disposal difficulty context. |
| DWER Water Information Sites (DWER-145) | Water MapServer layer 61, 61 fields; HTTP 200 in 0.49s | Custom (Active Acceptance) | Monitoring / bores context. |
| Other DWER water layers found in catalogue search (WRIMS surface water, management areas, etc.) | Catalogue search | Almost all `custom_active_acceptance` or Landgate/Water Corporation `custom_other`, `isopen=false` | Same restriction. |

A CKAN title search for DWER “approval / licence / registration” did **not** surface a CC BY register of individual water licences or works approvals. Published licence *documents* appear to live in Environment Online, which must not be monitored automatically.

**Landgate / Water Corporation layers** (topo water, hydrants, WaterCorp bores and pipes) are `custom_other`, `isopen=false`. Do not use them in v1.

**DISR Resources and Energy Major Projects 2025** spreadsheet was downloadable (`https://www.industry.gov.au/sites/default/files/2025-12/resources-and-energy-major-projects-2025-data.xlsx`, HTTP 200, 1.96 MB, 2.6s). The department copyright page returned 404; the disclaimer page does not clearly grant CC BY for reuse in a paid product. Treat as **licence unconfirmed**. Do not depend on it for v1.

### 2.3 Failed, blocked, or unsuitable endpoints

| Target | Result | Implication |
|---|---|---|
| DASC HTML/download links (`dasc.dmirs.wa.gov.au/download/File/3981` MINEDEX CSV, `3986` major projects, `3988` operators; also `productAlias=` pages) | **HTTP 403**, Incapsula “Access forbidden” | Do not rely on DASC file downloads from this environment. Prefer SLIP REST/WFS. |
| MINEDEX web app home (`minedex.dmirs.wa.gov.au`) | HTML hop to `/Web` plus Incapsula | Citation links only; no scraping. |
| `www.epa.wa.gov.au/copyright` and `/robots.txt` | HTTP 403 | Could not confirm EPA *website* copyright live. Spatial EPA data is already constrained by the DWER Active Acceptance licence. |
| `www.der.wa.gov.au/copyright` and `/robots.txt` | HTTP 403 | Same. |
| BoM NGIS access/copyright and robots | HTTP 403 | No BoM groundwater database in v1. |
| bhp.com robots/terms | HTTP 403 | Do not scrape issuer websites as a general strategy. |
| Data WA “APIs” help article (`toolkit.data.wa.gov.au/...Data-WA-APIs`) | HTTP 403 | Not required; CKAN and SLIP already work. |
| Landgate “SLIP data licensing” legacy URL | 301 to landgate.wa.gov.au | Public SLIP Industry and Mining services worked without a Landgate account. Still attribute SLIP / the source agency. |
| Azure blob `robots.txt` for DASC CDN | HTTP 400 | Irrelevant; PDF data dictionary and URL list were fetched as direct, published CDN files (200). |
| ResourcesOnline `robots.txt` | HTTP 404 | Public search page returned 200. Legal basis for automating that portal is unclear — **out of scope for v1**. |
| ASX.com.au announcements / terms page | Terms 200 at https://www.asx.com.au/legals/terms-of-use. robots.txt 200 (minimal). | See §4. Not a v1 source. |

WFS GetCapabilities for Industry and Mining succeeded (200, 0.70s) and lists MINEDEX, live tenements, dead/pending tenement layers, and WAMEX.

---

## 3. What is forbidden or out of bounds

### 3.1 DWER Environment Online — do not automate

Web search (not a request to the portal itself) indexed the official terms at `https://environmentonline.dwer.wa.gov.au/terms-of-use/`, including a “not use automation” obligation and a “do not access or use Environment Online” clause if terms are not accepted. The product brief already states that Environment Online **prohibits automated monitoring**.

**Rule for this repo:** no crawling, scraping, polling, account login, or “manual but scripted” collection against Environment Online, its APIs, or any hostname containing `environmentonline`. Water licences and works approvals must only come from a separately published, permitted dataset (none was found under CC BY in this pass).

### 3.2 Do not scrape these for v1

- **ASX website content**, including announcements. Terms allow saving/printing for personal, non-commercial use only; they prohibit spiders, screen scrapers and robots, and require ASX’s express written consent for commercial use of content.
- **wa.gov.au HTML** via bots. The [WA Government terms of use](https://www.wa.gov.au/terms-of-use) include “no automation: not access or use the WA.gov.au website or Other Government Services using automated means (whether or not including the use of bots or artificial intelligence)”. Use the documented CKAN and SLIP machine interfaces instead of harvesting HTML articles.
- **DMPE website IP** for resale, except material expressly published for redistribution (the CC BY datasets on Data WA / SLIP are that class of material). See [DMPE terms and conditions of use](https://www.wa.gov.au/organisation/department-of-mines-petroleum-and-exploration/dmpe-terms-and-conditions-of-use).
- **Issuer corporate websites** as a default announcement source (bot protection; varying terms).
- **DWER/EPA Custom (Active Acceptance) data** in any sold, distributed or publicly displayed product without prior written permission.

### 3.3 Commercial-use summary for a A$349/month product

| Class | Commercial weekly alerts? |
|---|---|
| CC BY 4.0 MINEDEX, tenements, WAMEX, (if fetched) Major Resources Projects | Yes, with attribution, licence notice, and no implied endorsement. |
| EPBC referrals (CC BY 4.0, DCCEEW credit required) | Yes, with the required credit and source link. |
| DWER/EPA Active Acceptance layers | **No**, not without prior written permission. |
| Environment Online | **No automation at all.** |
| ASX.com.au | **No**, not without written consent or a licensed feed. |
| DISR REMP spreadsheet | Unclear; do not ship until the licence is confirmed. |

CC BY 4.0 does **not** block a paid derived product. Attribution must name the source agency (for example “Minedex (DMIRS-001), Department of Energy, Mines, Industry Regulation and Safety, CC BY 4.0”) and link the licence. If the data is modified (joins, scores, filters), say so.

---

## 4. Competitor landscape

Public pages only; no paid subscriptions were opened. Pricing is as published on 22 November 2026 and may change.

| Product | What they sell (public description) | Mine-water / dewatering coverage | Public price | Gap this product can honestly claim |
|---|---|---|---|---|
| [Projectory](https://www.projectory.com.au/help-faqs) | Weekday news and developments on major Australian resource, construction, energy, infrastructure and defence projects with budgeted capex **over A$30 million**; searchable archives; quarterly major-project lists; custom alerts; newsletter. | Not described as water-consultancy specific. Threshold excludes smaller dewatering / borefield jobs. | **A$2,510 + GST / 12 months** or **A$4,540 + GST / 24 months**; up to 16 staff logins. | Narrower, cheaper, WA mine-water evidence (stage, borefield sites, CC BY sources) rather than general capex news. |
| [MiningEdge](https://miningedge.com.au/) | Sales platform for mining suppliers: tenders, projects, companies, contacts, “market signals”. Categories include water treatment, pumps, environmental services. “Start free trial” / “Book demo”. The `/pricing-plan/` URL redirected to the homepage; **no public price** was found. | Broad supplier intelligence, including water-related categories, but not an evidence-scored dewatering opportunity feed. | Not published (trial/demo). | A transparent, sourced scoring model (weak vs strong evidence; never claiming an open contract without an authoritative source) rather than a sales CRM. |
| [Mining Intelligence](https://www2.miningintelligence.com/exploration) | Global exploration / prospecting database, search templates, daily alerts, contacts. | Exploration-centric; no public mine-water module found on the page tested. | Subscriptions **from US$4,400 per user**. | Price and geography: a WA-only water radar at a small-consultant price point. |
| [Prospect Signal AU](https://prospectsignal.com.au/) | One-time CSVs of Australian mine ownership and a development/restart pipeline, each fact sourced and dated. Free map preview. 346 mine sites; 453 development & restart projects (figures from the page, data as at 4 Nov 2026). | Ownership and stage, not dewatering demand. | **A$299** per dataset, or **A$449** for both; organisation-wide licence; 10 free sample rows. | Recurring change detection and water-specific evidence, not a static ownership file. |

No public product was found that scores *groundwater investigation / dewatering / bore drilling / water treatment* opportunities on official WA evidence and states when a contract is *not* known to be open. That is the credible niche. It is not an empty market for “mining project intelligence” in general.

---

## 5. Recommended v1 data pipeline

Keep v1 inside licence-clear, already-working APIs.

1. **Weekly pull, paginated** (`resultRecordCount` ≤ 10,000, `resultOffset` until complete) of MINEDEX layer 0 (`outFields=*`, geometry optional for the first digest). Store a snapshot keyed by `site_code` and roll up to `proj_code`.
2. **Change detection** at project level: new `proj_code`; `site_stage` transitions (especially into Proposed / Under Development / Operating, or out of Care and Maintenance); new or updated water-related sites (`site_sub_t` / title / type matching borefield, bore, pipeline, water, dewatering, potable, brine, tailings seepage — exact dictionary to be finalised in the plan).
3. **Spatial join** to LIVE tenements (layer 3) for holder names, tenure type (exploration vs mining lease / general purpose / miscellaneous licence) and official tenement IDs.
4. **Optional keyword scan** of WAMEX abstracts for recent `date_released` only (for example last 24 months) with dewater / borefield / groundwater / water treatment terms; attach report links as supporting evidence, clearly dated.
5. **Optional spatial or name match** to EPBC WA mining referrals as a “federal assessment underway” flag, with DCCEEW attribution.
6. **Score and explain** using only fields and documents in hand (see §6). Each alert: project, operator (or “holder unknown — not in MINEDEX layer; tenement holder X” / “operator unknown”), reason, stage, source date (`extract_da` or report/referral date), evidence links.
7. **Outputs:** a weekly markdown/HTML digest, a searchable project list (JSON + simple HTML), and a top-5 briefing. Never assert that a contract, tender or engagement is open unless an authoritative source in the permitted set says so (v1 will almost always *not* have that).

**Out of v1:** Environment Online, DWER/EPA Active Acceptance layers, ASX scraping, DASC 403 downloads, ResourcesOnline HTML, issuer websites, paid APIs.

**Attribution block** (draft): “Project locations and stages from Minedex (DMIRS-001) and tenement holders from Mining Tenements (DMIRS-003), Department of Energy, Mines, Industry Regulation and Safety, via SLIP public services, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Exploration report metadata from Mineral exploration reports (WAMEX) (DMIRS-033), same licence. Where used, EPBC referral locations from the Referrals Spatial Database — Public, © Commonwealth of Australia (Department of Climate Change, Energy, the Environment and Water), CC BY 4.0. Scores and commentary are added by WA Mine Water Opportunity Radar and are not official advice.”

---

## 6. Proposed scoring signals (research-level)

These are hypotheses grounded in fields actually returned. Final weights belong in `PLAN.md`.

| Direction | Signal | Source / field example | Strength |
|---|---|---|---|
| + | Project or site stage is **Under Development** or **Proposed** | MINEDEX `site_stage` (234 under development; 4,677 proposed) | Medium, stronger if paired with water infrastructure |
| + | New or existing **borefield / water infrastructure** site on the project | e.g. DeGrussa Borefield, `site_type_=Infrastructure`, `site_sub_t=Borefield`, stage Proposed | **Strong** physical water-scope evidence |
| + | Stage change since last snapshot into Under Development / Operating, or a new proj_code | Snapshot diff on `proj_code` + `site_stage` + `extract_da` | Medium–strong (change detection) |
| + | Tenure is a **mining lease** or miscellaneous/general-purpose licence rather than exploration only | Tenements `type`, `tenstatus=LIVE` | Medium |
| + | Recent WAMEX abstract mentions dewatering, borefield, groundwater investigation, water treatment | WAMEX `abstract`, `date_released`, official report URL | Supporting only; may be old or exploration-only |
| + | WA mining EPBC referral overlaps the project or shares a name | EPBC `NAME`, `CATEGORY='Mining'`, `PRIMARY_JURISDICTION='WA'` | Medium (“assessment underway”), not a water scope by itself |
| Weak / low | **Exploration tenure only**, undeveloped deposit, no water infrastructure, no recent water-language evidence | Tenement type + MINEDEX `site_stage=Undeveloped` / exploration reports only | Weak — include only in a “watch” tier, if at all |
| − | Stage is **Shut** or **Care and Maintenance** with no restart evidence | MINEDEX `site_stage` (20,249 shut; 2,138 C&M) | Strong negative unless a restart signal exists |
| − | Contractor, consultant or driller **already named** in a permitted source | Would come from a permitted announcement or document; **not available in the MINEDEX layer**. If later found, lower priority and quote the source. | Lower priority, not a “closed” claim unless the source is explicit |
| Forbidden claim | “A contract / tender is open” | No permitted v1 source states this | **Never claim** without an authoritative source |

Operator display rule: prefer tenement `holder1` (and additional holders) when MINEDEX has no operator; label the role accurately (“first-named tenement holder”, not “confirmed mine operator”) unless a permitted source names the operator (WAMEX `operator` may be stale or a historical reporter).

---

## 7. Technical feasibility notes

- **Auth:** none on the working SLIP, CKAN and EPBC endpoints.
- **Latency:** typical SLIP queries 0.2–0.7s; catalogue and Commonwealth endpoints 1–2s.
- **Pagination:** `maxRecordCount=10000`. A full MINEDEX pull is about five pages; tenements about four; WAMEX about twelve. Offset pagination worked on MINEDEX (`resultOffset=3` returned the next site codes).
- **CRS:** WFS default EPSG:7844 (GDA2020). REST geometry was not required for the attribute sample.
- **Bot protection:** DASC, some agency websites, and the MINEDEX HTML app are gated (403 / Incapsula). Public SLIP REST/WFS were not.
- **Staleness:** MINEDEX `extract_da` on the sample was 19 November 2026 — a few days behind “today” at test time. Weekly cadence is consistent with that.
- **Field truncation:** some names are clipped (`site_type_`, `site_sub_t`, `site_commo`) but values are usable.
- **WAMEX keyword noise:** a dewatering match can be decades old. Always show `report_year` / `date_released`.
- **Rate limits:** none advertised on the public SLIP URL. Be polite (serial pagination, modest concurrency) and cache weekly snapshots.
- **Cost:** all recommended v1 sources are free. No paid API is required.

---

## 8. Risks and open questions

1. **Operator gap** in the MINEDEX spatial extract. Can holders from tenements plus WAMEX operators be joined reliably enough for a consultant-grade alert? Needs a measured match rate in the build.
2. **DWER permission.** If written permission is later granted for DWER-120 / EIAOC or a published water-licence extract, scoring would improve substantially. Until then, do not quietly “just use” those layers.
3. **No CC BY water-licence register** was found. v1 cannot list licensed allocation volumes or works-approval conditions.
4. **Commercial reuse of DISR REMP** is unconfirmed.
5. **ASX licensed feeds** (official market data / company news products) might be a later, paid path — out of scope while the brief is free-tier only.
6. **Incapsula / 403** on DASC may be environment-specific; a browser session might work for a one-off dictionary download, but the pipeline should not depend on it. A MINEDEX data dictionary PDF *was* fetched from the public Azure CDN (`MINEDEX_Database_DataDictionary_GDA2020.pdf`).
7. **wa.gov.au “no automation” language** is broad. Staying on documented SLIP/CKAN APIs is the conservative reading.
8. **Market risk:** even with a clean niche, general project radars already sell to the same firms at much higher prices. A hand-made sample digest should be tested with buyers before assuming A$349/month revenue (outside the scope of this technical research).
9. **Codex session interrupted.** Competitor pages for MiningEdge pricing and some secondary sources were only partially reviewed. Figures above are from the pages that returned 200.

---

## 9. Bibliography and primary links

- Data WA — Minedex (DMIRS-001): https://catalogue.data.wa.gov.au/dataset/minedex-dmirs-001  
- Data WA — Mining Tenements (DMIRS-003): https://catalogue.data.wa.gov.au/dataset/mining-tenements-dmirs-003  
- Data WA — Mineral exploration reports (WAMEX) (DMIRS-033): https://catalogue.data.wa.gov.au/dataset/mineral-exploration-reports-wamex  
- Data WA — Major Resources Projects: https://catalogue.data.wa.gov.au/dataset/major-resources-projects  
- Data WA — EPA Referred Significant Proposals (DWER-120): https://catalogue.data.wa.gov.au/dataset/epa-referred-significant-proposals  
- Data WA — WRIMS Groundwater Resources (DWER-084): https://catalogue.data.wa.gov.au/dataset/wrims-groundwater-resources  
- Data WA — DWER Active Acceptance Licence Agreement: https://catalogue.data.wa.gov.au/dataset/dwer-active-acceptance-licence-agreement  
- SLIP public Industry and Mining MapServer: https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Industry_and_Mining/MapServer  
- SLIP Industry and Mining WFS GetCapabilities: https://public-services.slip.wa.gov.au/public/services/SLIP_Public_Services/Industry_and_Mining_WFS/MapServer/WFSServer?service=WFS&request=GetCapabilities  
- CC BY 4.0: https://creativecommons.org/licenses/by/4.0/  
- WA Government terms of use: https://www.wa.gov.au/terms-of-use  
- DMPE terms and conditions of use: https://www.wa.gov.au/organisation/department-of-mines-petroleum-and-exploration/dmpe-terms-and-conditions-of-use  
- DMPE publicly available information (resource and environmental regulation): https://www.wa.gov.au/organisation/department-of-mines-petroleum-and-exploration/publicly-available-information-resource-and-environmental-regulation  
- Environment Online terms (cited from search snippets only; do not automate this host): https://environmentonline.dwer.wa.gov.au/terms-of-use/  
- ASX terms of use: https://www.asx.com.au/legals/terms-of-use  
- EPBC Referrals MapServer: https://gis.environment.gov.au/gispubmap/rest/services/ogc_services/EPBC_Referrals/MapServer/0  
- DISR Resources and Energy Major Projects 2025: https://www.industry.gov.au/publications/resources-and-energy-major-projects-2025  
- Projectory FAQs / pricing: https://www.projectory.com.au/help-faqs  
- MiningEdge: https://miningedge.com.au/  
- Mining Intelligence: https://www2.miningintelligence.com/exploration  
- Prospect Signal AU: https://prospectsignal.com.au/

---

## 10. Session provenance

- Codex CLI 0.164.0, model `gpt-6-astra`, `model_reasoning_effort=xhigh`, approval bypass, full disk/network access in `/workspace/radars/mine-water-radar`.
- ChatGPT login: `lennotau@gmail.com` (`codex login status`: “Logged in using ChatGPT”).
- The research run ended with: “You’ve hit your usage limit… try again at 9:08 PM.” Reported token usage on the exec footer: 223,049 tokens (internal totals were higher because of cached input).
- A tiny follow-up exec on `gpt-6.1-sol` / `low` was refused with the same usage limit, so the memo was compiled from the already-fetched live materials rather than left unwritten until the reset.
