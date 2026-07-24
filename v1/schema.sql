PRAGMA foreign_keys = ON;

CREATE TABLE warehouse_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE source_commits (
    ordinal INTEGER PRIMARY KEY,
    commit_sha TEXT NOT NULL UNIQUE,
    parent_sha TEXT,
    commit_at TEXT NOT NULL,
    story_revision TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload_bytes INTEGER NOT NULL,
    event_count INTEGER NOT NULL
);

CREATE TABLE story_snapshots (
    commit_sha TEXT PRIMARY KEY REFERENCES source_commits(commit_sha),
    story_id TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL,
    incomplete_before INTEGER NOT NULL,
    continuous_source INTEGER NOT NULL,
    event_count INTEGER NOT NULL
) WITHOUT ROWID;

CREATE TABLE event_records (
    record_id TEXT PRIMARY KEY,
    story_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    first_commit_sha TEXT NOT NULL REFERENCES source_commits(commit_sha),
    last_commit_sha TEXT NOT NULL REFERENCES source_commits(commit_sha),
    first_seen_ordinal INTEGER NOT NULL,
    last_seen_ordinal INTEGER NOT NULL,
    latest_version INTEGER NOT NULL,
    latest_content_sha256 TEXT NOT NULL,
    UNIQUE(story_id, event_id)
) WITHOUT ROWID;

CREATE TABLE event_versions (
    record_id TEXT NOT NULL REFERENCES event_records(record_id),
    version INTEGER NOT NULL,
    commit_sha TEXT NOT NULL REFERENCES source_commits(commit_sha),
    source_ordinal INTEGER NOT NULL,
    content_sha256 TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL,
    chapter TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    location TEXT NOT NULL,
    badge_count INTEGER NOT NULL,
    party_size INTEGER,
    highest_level INTEGER,
    pokedex_seen INTEGER,
    pokedex_caught INTEGER,
    play_time_seconds INTEGER,
    coverage_gap_before INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY(record_id, version)
) WITHOUT ROWID;

CREATE TABLE event_badges (
    record_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    position INTEGER NOT NULL,
    badge TEXT NOT NULL,
    PRIMARY KEY(record_id, version, position),
    FOREIGN KEY(record_id, version)
        REFERENCES event_versions(record_id, version)
) WITHOUT ROWID;

CREATE TABLE snapshot_events (
    commit_sha TEXT NOT NULL REFERENCES story_snapshots(commit_sha),
    position INTEGER NOT NULL,
    record_id TEXT NOT NULL REFERENCES event_records(record_id),
    version INTEGER NOT NULL,
    PRIMARY KEY(commit_sha, position),
    UNIQUE(commit_sha, record_id),
    FOREIGN KEY(record_id, version)
        REFERENCES event_versions(record_id, version)
) WITHOUT ROWID;

CREATE TABLE execution_receipts (
    record_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    agent_sha256 TEXT NOT NULL,
    requested_model TEXT NOT NULL,
    reasoning_effort TEXT NOT NULL,
    game_time_seconds INTEGER,
    phase TEXT NOT NULL,
    badge_count INTEGER NOT NULL,
    party_size INTEGER,
    pokedex_seen INTEGER,
    pokedex_caught INTEGER,
    lift_key INTEGER,
    silph_scope INTEGER,
    hall_of_fame INTEGER NOT NULL,
    progress_changed INTEGER NOT NULL,
    action_source TEXT NOT NULL,
    buttons_json TEXT NOT NULL,
    action_mode TEXT,
    movement_result TEXT NOT NULL,
    stuck_reasons_json TEXT NOT NULL,
    navigation_schema INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(run_id, sequence)
) WITHOUT ROWID;

CREATE VIEW events_latest_known AS
SELECT
    records.record_id,
    records.story_id,
    records.event_id,
    records.first_commit_sha,
    records.last_commit_sha,
    versions.*
FROM event_records AS records
JOIN event_versions AS versions
  ON versions.record_id = records.record_id
 AND versions.version = records.latest_version;

CREATE VIEW events_current_story AS
SELECT latest.*
FROM snapshot_events AS membership
JOIN source_commits AS source ON source.commit_sha = membership.commit_sha
JOIN events_latest_known AS latest ON latest.record_id = membership.record_id
WHERE source.ordinal = (SELECT MAX(ordinal) FROM source_commits)
ORDER BY membership.position;

CREATE VIEW commit_summary AS
SELECT
    source.ordinal,
    source.commit_sha,
    source.commit_at,
    source.story_revision,
    source.event_count,
    snapshot.status,
    snapshot.first_observed_at,
    snapshot.last_observed_at
FROM source_commits AS source
JOIN story_snapshots AS snapshot USING (commit_sha)
ORDER BY source.ordinal;
