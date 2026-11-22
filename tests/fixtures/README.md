# Fixture formats

`manifest.json` indexes each payload by path and SHA-256. Recorded entries point to their unchanged `research/samples/` source, capture URL/time from the research request log when available, CC BY 4.0 attribution, and the original `exceededTransferLimit` state. No licence response body is represented as recorded: the research explicitly says complete metadata response bodies were not retained.

## Recorded replay

`replay/recorded-baseline.json` is a selected-records replay manifest. It references exact business IDs from the partial envelopes in `recorded/`; consumers select those records without changing source facts. Its `data_mode` is `fixture:selected-records`, `complete_snapshot` and `statewide` are false, and the original response transfer-limit flags remain visible. It cannot support statewide coverage or deletion inference. EPBC has year-only dates and a malformed generic referral URL, WAMEX has an old report and a 250-character abstract, and the tenement sample contains pre-1970 dates plus historical address fields. Production source clients must not request `addr1`–`addr9`.

## Synthetic replays

`replay/synthetic-a.json`, `synthetic-b.json`, and `synthetic-c.json` each contain fictional records and a complete snapshot envelope scoped only to the synthetic test scenario. A is the baseline; B introduces a fictional project and water site, advances a development stage, restarts a dormant site, reassigns a site's project membership, and omits one project. C repeats B's business content with reordered records and a new extraction timestamp. “Complete” only describes these fictional scenario inputs; it makes no claim about a real layer.

`synthetic/edge-cases.json` holds small fictional examples for ambiguous matches, a Deposit named Borefield, negated and historical WAMEX language, stale/missing dates, conflicting keys, multiple holders, failed/truncated pagination, reviewed approval evidence and contractor evidence. These are test shapes, not evidence. A valid-looking approval example is fictional and does not establish any real approval or water requirement.
