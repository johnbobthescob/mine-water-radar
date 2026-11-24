-- Schema v1. Store installs this file in one explicit transaction.
CREATE TABLE database_state (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    data_mode TEXT CHECK (data_mode IN ('live','recorded_fixture','synthetic_fixture'))
);
INSERT INTO database_state(singleton) VALUES (1);
CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    run_key TEXT NOT NULL UNIQUE,
    input_hash TEXT NOT NULL,
    data_mode TEXT NOT NULL CHECK (data_mode IN ('live','recorded_fixture','synthetic_fixture')),
    as_of TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    observed_at TEXT NOT NULL,
    replayed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('ingesting','complete','degraded','partial','failed')),
    usable INTEGER NOT NULL DEFAULT 0 CHECK (usable IN (0,1)),
    coverage_json TEXT NOT NULL,
    limitations_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    normalization_version INTEGER NOT NULL,
    linking_annotations_hash TEXT NOT NULL DEFAULT '',
    CHECK (usable = 0 OR status IN ('complete','degraded'))
);
CREATE TRIGGER runs_mode_guard BEFORE INSERT ON runs
WHEN (SELECT data_mode FROM database_state WHERE singleton=1) IS NOT NEW.data_mode
BEGIN SELECT RAISE(ABORT, 'provenance modes cannot be mixed'); END;
CREATE TABLE source_batches (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    source TEXT NOT NULL CHECK (source IN ('minedex','tenements','wamex','epbc')),
    scope_id TEXT NOT NULL,
    scope_hash TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('complete','partial','failed','disabled')),
    complete INTEGER NOT NULL CHECK (complete IN (0,1)),
    expected_count INTEGER CHECK (expected_count >= 0),
    received_count INTEGER CHECK (received_count >= 0),
    licence_status TEXT NOT NULL CHECK (licence_status IN ('verified','unknown','incompatible')),
    licence_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    coverage_json TEXT NOT NULL,
    counts_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    captured_at TEXT,
    fetched_at TEXT,
    extraction_min TEXT,
    extraction_max TEXT,
    raw_manifest_json TEXT NOT NULL,
    error TEXT,
    UNIQUE(run_id, source, scope_hash),
    CHECK (complete=0 OR (status='complete' AND licence_status='verified'))
);
CREATE TABLE raw_responses (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES source_batches(id),
    ordinal INTEGER NOT NULL,
    path TEXT,
    sha256 TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    response_json TEXT NOT NULL,
    UNIQUE(batch_id, ordinal)
);
CREATE TABLE source_records (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES source_batches(id),
    business_key TEXT NOT NULL CHECK (length(trim(business_key)) > 0),
    raw_json TEXT NOT NULL,
    normalized_json TEXT NOT NULL,
    semantic_hash TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    raw_manifest_json TEXT NOT NULL,
    source_date_value TEXT,
    source_date_kind TEXT NOT NULL,
    source_date_precision TEXT,
    observed_at TEXT NOT NULL,
    UNIQUE(batch_id, business_key)
);
CREATE TABLE projects (
    id TEXT PRIMARY KEY CHECK (id GLOB 'minedex:?*' OR id GLOB 'site:?*'),
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    CHECK (first_seen <= last_seen)
);
CREATE TABLE project_versions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    title TEXT,
    site_membership_json TEXT NOT NULL,
    stage_distribution_json TEXT NOT NULL,
    representative_stage TEXT,
    representative_site TEXT,
    semantic_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('current','missing')),
    coverage_json TEXT NOT NULL,
    freshness_json TEXT NOT NULL,
    contract_status TEXT NOT NULL DEFAULT 'not_verified' CHECK (contract_status='not_verified'),
    UNIQUE(run_id, project_id)
);
CREATE TABLE links (
    id TEXT PRIMARY KEY,
    project_version_id TEXT NOT NULL REFERENCES project_versions(id),
    source_record_id TEXT NOT NULL REFERENCES source_records(id),
    method TEXT NOT NULL,
    supporting_reference TEXT,
    confidence TEXT NOT NULL CHECK (confidence IN ('exact','reviewed','candidate')),
    ambiguity_json TEXT NOT NULL,
    scope_json TEXT NOT NULL
);
CREATE TABLE evidence (
    id TEXT PRIMARY KEY,
    evidence_key TEXT NOT NULL,
    project_version_id TEXT NOT NULL REFERENCES project_versions(id),
    source_record_id TEXT NOT NULL REFERENCES source_records(id),
    field TEXT NOT NULL,
    value_json TEXT NOT NULL,
    excerpt TEXT,
    source_date_value TEXT,
    source_date_kind TEXT NOT NULL,
    source_date_precision TEXT,
    observed_at TEXT NOT NULL,
    url TEXT NOT NULL,
    licence_id TEXT NOT NULL,
    role TEXT NOT NULL,
    validity_json TEXT NOT NULL,
    UNIQUE(project_version_id, evidence_key)
);
CREATE TABLE changes (
    id TEXT PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL REFERENCES projects(id),
    previous_version_id TEXT REFERENCES project_versions(id),
    current_version_id TEXT NOT NULL REFERENCES project_versions(id),
    event_type TEXT NOT NULL,
    old_json TEXT NOT NULL,
    new_json TEXT NOT NULL,
    supporting_site_ids_json TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    digest_eligible INTEGER NOT NULL CHECK (digest_eligible IN (0,1))
);
CREATE TABLE score_sets (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    as_of TEXT NOT NULL,
    rubric_version TEXT NOT NULL,
    reviewed_evidence_hash TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('building','complete')),
    UNIQUE(run_id, as_of, rubric_version, reviewed_evidence_hash),
    CHECK (status != 'complete' OR completed_at IS NOT NULL)
);
CREATE TABLE scores (
    score_set_id TEXT NOT NULL REFERENCES score_sets(id),
    project_version_id TEXT NOT NULL REFERENCES project_versions(id),
    total INTEGER NOT NULL CHECK (total BETWEEN 0 AND 100),
    tier TEXT NOT NULL CHECK (tier IN ('High','Priority','Watch','Background')),
    positive_json TEXT NOT NULL,
    negative_json TEXT NOT NULL,
    caps_json TEXT NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    change_ids_json TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY(score_set_id, project_version_id)
);
CREATE TRIGGER scores_run_guard BEFORE INSERT ON scores
WHEN (SELECT run_id FROM score_sets WHERE id=NEW.score_set_id) !=
     (SELECT run_id FROM project_versions WHERE id=NEW.project_version_id)
BEGIN SELECT RAISE(ABORT, 'score and project version must belong to same run'); END;
CREATE INDEX batches_history ON source_batches(source, scope_hash, observed_at);
CREATE INDEX records_business ON source_records(business_key);
CREATE INDEX runs_observed ON runs(usable, observed_at);
CREATE INDEX versions_project ON project_versions(project_id, run_id);
PRAGMA user_version = 1;
