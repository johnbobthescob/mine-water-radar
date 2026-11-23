# Fixture formats

`manifest.json` indexes each payload by path and SHA-256. Original recorded entries point to their unchanged `research/samples/` source, capture URL/time from the research request log when available, CC BY 4.0 attribution, and the original `exceededTransferLimit` state. The research did not retain full licence response bodies; the separate M2 metadata captures below supply newly recorded bodies with their own provenance.

## Recorded replay

`replay/recorded-baseline.json` is a selected-records replay manifest. It references exact business IDs from the partial envelopes in `recorded/`; consumers select those records without changing source facts. Its `data_mode` is `fixture:selected-records`, `complete_snapshot` and `statewide` are false, and the original response transfer-limit flags remain visible. It cannot support statewide coverage or deletion inference. EPBC has year-only dates and a malformed generic referral URL, WAMEX has an old report and a 250-character abstract, and the tenement sample contains pre-1970 dates plus historical address fields. Production source clients must not request `addr1`–`addr9`.

## Synthetic replays

`replay/synthetic-a.json`, `synthetic-b.json`, and `synthetic-c.json` each contain fictional records and a complete snapshot envelope scoped only to the synthetic test scenario. A is the baseline; B introduces a fictional project and water site, advances a development stage, restarts a dormant site, reassigns a site's project membership, and omits one project. C repeats B's business content with reordered records and a new extraction timestamp. “Complete” only describes these fictional scenario inputs; it makes no claim about a real layer.

`synthetic/edge-cases.json` holds small fictional examples for ambiguous matches, a Deposit named Borefield, negated and historical WAMEX language, stale/missing dates, conflicting keys, multiple holders, failed/truncated pagination, reviewed approval evidence and contractor evidence. These are test shapes, not evidence. A valid-looking approval example is fictional and does not establish any real approval or water requirement.

## M2 source protocol fixtures

`synthetic/source-services.json` contains fictional schemas, licence responses and records for the offline ArcGIS simulator. Its two-record page limit and invented transport IDs exercise complete acquisition without altering any recorded response. They are protocol test inputs, not evidence.

`licence/` contains full, byte-identical machine metadata responses captured during M2 from only the three permitted CKAN package lookups and two permitted EPBC item URLs. Their URLs, capture times, request parameters, response headers and SHA-256 values are indexed in `manifest.json`. These are new licence metadata captures, separate from the unchanged research samples. They do not establish current source-record facts or complete dataset coverage. Metadata links were not followed. Tests replay these bodies offline; live runs must obtain their own licence verification.

Data WA's recorded `cc-by` ID is accepted only together with its explicit 4.0 URL. The first EPBC item contains generic CC BY wording without a version; the second names the exact EPBC layer and supplies the 4.0 licence, attribution and copyright. The raw terms, credit and service relationship remain available in the verification result.
