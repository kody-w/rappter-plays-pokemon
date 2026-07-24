"""Build and publish a Git-backed SQLite warehouse and static RAPP API."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import quote

from .improvement import DEFAULT_RUNTIME_DIR, PUBLIC_SCHEMA, export_public
from .story import PUBLIC_EVENT_KEYS, validate_public_story

WAREHOUSE_SCHEMA_VERSION = 1
WAREHOUSE_SCHEMA = "rappter-pokemon-warehouse/1.0"
STATIC_API_SCHEMA = "rapp-static-api/1.0"
STATUS_SCHEMA = "rappter-pokemon-warehouse-status/1.0"
DEFAULT_REPOSITORY = "kody-w/rappter-plays-pokemon"
DEFAULT_SOURCE_REF = "refs/remotes/origin/story-archive"
DEFAULT_BRANCH = "story-warehouse"
DEFAULT_WAREHOUSE_STATE_DIR = (
    Path.home() / ".openrappter" / "pokemon-red-warehouse"
)
STORY_PATH = "v1/story.json"
MAX_STORY_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 8192
MAX_PUBLISH_FILE_BYTES = 100 * 1024 * 1024
GITHUB_BLOB_API_SAFE_BYTES = 20 * 1024 * 1024
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

WAREHOUSE_SCHEMA_SQL = """
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
""".strip()


class WarehouseError(RuntimeError):
    """Raised when warehouse inputs or publication fail closed."""


def _canonical(value: Any, *, pretty: bool = False) -> bytes:
    if pretty:
        text = json.dumps(
            value,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
    else:
        text = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    return (text + "\n").encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(
    repository_root: Path,
    *arguments: str,
    text: bool = True,
    allow_failure: bool = False,
) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        capture_output=True,
        text=text,
        check=False,
        env={
            **os.environ,
            "LC_ALL": "C",
            "TZ": "UTC",
        },
    )
    if result.returncode and not allow_failure:
        detail = result.stderr.strip() if text else result.stderr.decode().strip()
        raise WarehouseError(f"Git command failed: {detail}")
    return result.stdout


def _story_at(repository_root: Path, commit_sha: str) -> tuple[dict[str, Any], bytes]:
    payload = _git(
        repository_root,
        "show",
        f"{commit_sha}:{STORY_PATH}",
        text=False,
    )
    if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_STORY_BYTES:
        raise WarehouseError(f"Invalid story payload at {commit_sha}")
    try:
        story = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WarehouseError(f"Invalid story JSON at {commit_sha}") from error
    if (
        isinstance(story, dict)
        and isinstance(story.get("events"), list)
        and story["events"]
        and all(
            isinstance(event, dict)
            and set(event) == PUBLIC_EVENT_KEYS - {"video"}
            for event in story["events"]
        )
    ):
        story = dict(story)
        story["events"] = [{**event, "video": None} for event in story["events"]]
        body = dict(story)
        body.pop("revision", None)
        story["revision"] = "sha256:" + hashlib.sha256(
            json.dumps(
                body,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
    validate_public_story(story)
    return story, payload


def _story_commits(repository_root: Path, source_ref: str) -> list[str]:
    raw = _git(
        repository_root,
        "rev-list",
        "--reverse",
        "--first-parent",
        source_ref,
    )
    commits = [
        line
        for line in str(raw).splitlines()
        if SHA_RE.fullmatch(line)
        and subprocess.run(
            [
                "git",
                "-C",
                str(repository_root),
                "cat-file",
                "-e",
                f"{line}:{STORY_PATH}",
            ],
            capture_output=True,
            check=False,
            env={**os.environ, "LC_ALL": "C", "TZ": "UTC"},
        ).returncode
        == 0
    ]
    if not commits:
        raise WarehouseError(f"No story revisions found on {source_ref}")
    return commits


def _commit_metadata(
    repository_root: Path,
    commit_sha: str,
) -> tuple[str | None, str]:
    parent = str(
        _git(
            repository_root,
            "rev-parse",
            f"{commit_sha}^",
            allow_failure=True,
        )
    ).strip()
    parent = parent if SHA_RE.fullmatch(parent) else None
    committed_at = str(
        _git(repository_root, "show", "-s", "--format=%cI", commit_sha)
    ).strip()
    try:
        parsed = datetime.fromisoformat(committed_at.replace("Z", "+00:00"))
    except ValueError as error:
        raise WarehouseError(f"Invalid commit timestamp: {commit_sha}") from error
    return parent, parsed.astimezone(timezone.utc).isoformat()


def _event_payload(event: dict[str, Any]) -> tuple[str, str]:
    event = {**event, "video": None}
    payload = json.dumps(
        event,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _insert_event(
    connection: sqlite3.Connection,
    *,
    story_id: str,
    event: dict[str, Any],
    commit_sha: str,
    source_ordinal: int,
) -> tuple[str, int]:
    record_id = f"{story_id}/{event['id']}"
    payload_json, content_sha256 = _event_payload(event)
    existing = connection.execute(
        """
        SELECT latest_version, latest_content_sha256
        FROM event_records WHERE record_id = ?
        """,
        (record_id,),
    ).fetchone()
    if existing is None:
        version = 1
        connection.execute(
            """
            INSERT INTO event_records (
                record_id, story_id, event_id, first_commit_sha,
                last_commit_sha, first_seen_ordinal, last_seen_ordinal,
                latest_version, latest_content_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                story_id,
                event["id"],
                commit_sha,
                commit_sha,
                source_ordinal,
                source_ordinal,
                version,
                content_sha256,
            ),
        )
    else:
        version = int(existing[0])
        if existing[1] != content_sha256:
            version += 1
        connection.execute(
            """
            UPDATE event_records
            SET last_commit_sha = ?, last_seen_ordinal = ?,
                latest_version = ?, latest_content_sha256 = ?
            WHERE record_id = ?
            """,
            (
                commit_sha,
                source_ordinal,
                version,
                content_sha256,
                record_id,
            ),
        )
    if existing is None or existing[1] != content_sha256:
        connection.execute(
            """
            INSERT INTO event_versions (
                record_id, version, commit_sha, source_ordinal,
                content_sha256, observed_at, sequence, kind, chapter,
                title, summary, location, badge_count, party_size,
                highest_level, pokedex_seen, pokedex_caught,
                play_time_seconds, coverage_gap_before, payload_json
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?
            )
            """,
            (
                record_id,
                version,
                commit_sha,
                source_ordinal,
                content_sha256,
                event["observed_at"],
                event["sequence"],
                event["kind"],
                event["chapter"],
                event["title"],
                event["summary"],
                event["location"],
                len(event["badges"]),
                event["party_size"],
                event["highest_level"],
                event["pokedex"]["seen"],
                event["pokedex"]["caught"],
                event["play_time_seconds"],
                int(event["coverage_gap_before"]),
                payload_json,
            ),
        )
        connection.executemany(
            """
            INSERT INTO event_badges (record_id, version, position, badge)
            VALUES (?, ?, ?, ?)
            """,
            [
                (record_id, version, position, badge)
                for position, badge in enumerate(event["badges"])
            ],
        )
    return record_id, version


def _walk_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_walk_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_walk_keys(item) for item in value))
    return set()


def load_public_receipts(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise WarehouseError("Public receipts input must be a regular file")
    forbidden = {
        "coordinates",
        "map_id",
        "location",
        "objective",
        "observation",
        "reason",
        "screen_text",
        "rom_sha256",
        "youtube_id",
    }
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if len(line.encode("utf-8")) > MAX_RECEIPT_BYTES:
                raise WarehouseError("Public receipt exceeds the line limit")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise WarehouseError("Public receipts contain invalid JSON") from error
            if (
                not isinstance(value, dict)
                or value.get("schema") != PUBLIC_SCHEMA
                or not isinstance(value.get("record_id"), str)
                or not value["record_id"].startswith("sha256:")
                or forbidden & _walk_keys(value)
            ):
                raise WarehouseError("Public receipt failed its allowlist")
            records.append(value)
    records.sort(key=lambda item: (item["run_id"], item["sequence"]))
    return records


def _insert_public_receipts(
    connection: sqlite3.Connection,
    records: Iterable[dict[str, Any]],
) -> int:
    count = 0
    for record in records:
        inference = record["inference"]
        progress = record["progress"]
        action = record["action"]
        outcome = record["outcome"]
        provenance = record["provenance"]
        payload_json = json.dumps(
            record,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        connection.execute(
            """
            INSERT INTO execution_receipts (
                record_id, run_id, sequence, agent_sha256,
                requested_model, reasoning_effort, game_time_seconds,
                phase, badge_count, party_size, pokedex_seen,
                pokedex_caught, lift_key, silph_scope, hall_of_fame,
                progress_changed, action_source, buttons_json, action_mode,
                movement_result, stuck_reasons_json, navigation_schema,
                payload_json
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?
            )
            """,
            (
                record["record_id"],
                record["run_id"],
                record["sequence"],
                record["agent_sha256"],
                inference["requested_model"],
                inference["reasoning_effort"],
                record["game_time_seconds"],
                record["phase"],
                progress["badge_count"],
                progress["party_size"],
                progress["pokedex_seen"],
                progress["pokedex_caught"],
                progress["lift_key"],
                progress["silph_scope"],
                int(progress["hall_of_fame"]),
                int(progress["changed"]),
                action["source"],
                json.dumps(action["buttons"], separators=(",", ":")),
                action["mode"],
                outcome["movement_result"],
                json.dumps(outcome["stuck_reasons"], separators=(",", ":")),
                provenance["navigation_schema"],
                payload_json,
            ),
        )
        count += 1
    return count


def build_database(
    repository_root: Path,
    source_ref: str,
    output: Path,
    manifest_path: Path,
    *,
    public_receipts_path: Path | None = None,
) -> dict[str, Any]:
    repository_root = repository_root.expanduser().resolve()
    output = output.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    commits = _story_commits(repository_root, source_ref)
    receipts = load_public_receipts(public_receipts_path)
    receipts_payload = (
        public_receipts_path.read_bytes()
        if public_receipts_path is not None and public_receipts_path.is_file()
        else b""
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    latest_story: dict[str, Any] | None = None
    latest_commit_at = ""
    try:
        connection.execute("PRAGMA page_size = 4096")
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("PRAGMA synchronous = OFF")
        connection.execute("PRAGMA application_id = 0x52505057")
        connection.execute(f"PRAGMA user_version = {WAREHOUSE_SCHEMA_VERSION}")
        connection.executescript(WAREHOUSE_SCHEMA_SQL)
        for ordinal, commit_sha in enumerate(commits, start=1):
            story, payload = _story_at(repository_root, commit_sha)
            parent_sha, commit_at = _commit_metadata(repository_root, commit_sha)
            latest_story = story
            latest_commit_at = commit_at
            coverage = story["coverage"]
            connection.execute("BEGIN")
            try:
                connection.execute(
                    """
                    INSERT INTO source_commits (
                        ordinal, commit_sha, parent_sha, commit_at,
                        story_revision, payload_sha256, payload_bytes,
                        event_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ordinal,
                        commit_sha,
                        parent_sha,
                        commit_at,
                        story["revision"],
                        _sha256(payload),
                        len(payload),
                        len(story["events"]),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO story_snapshots (
                        commit_sha, story_id, status, updated_at, summary,
                        first_observed_at, last_observed_at,
                        incomplete_before, continuous_source, event_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        commit_sha,
                        story["story_id"],
                        story["status"],
                        story["updated_at"],
                        story["summary"],
                        coverage["first_observed_at"],
                        coverage["last_observed_at"],
                        int(coverage["incomplete_before"]),
                        int(coverage["continuous_source"]),
                        len(story["events"]),
                    ),
                )
                for position, event in enumerate(story["events"]):
                    record_id, version = _insert_event(
                        connection,
                        story_id=story["story_id"],
                        event=event,
                        commit_sha=commit_sha,
                        source_ordinal=ordinal,
                    )
                    connection.execute(
                        """
                        INSERT INTO snapshot_events (
                            commit_sha, position, record_id, version
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (commit_sha, position, record_id, version),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        receipt_count = _insert_public_receipts(connection, receipts)
        builder_commit = str(
            _git(repository_root, "rev-parse", "HEAD")
        ).strip()
        metadata = {
            "schema": WAREHOUSE_SCHEMA,
            "schema_version": str(WAREHOUSE_SCHEMA_VERSION),
            "source_ref": source_ref,
            "source_head": commits[-1],
            "source_commits": str(len(commits)),
            "builder_commit": builder_commit,
            "generated_at": latest_commit_at,
            "execution_receipts": str(receipt_count),
        }
        connection.executemany(
            "INSERT INTO warehouse_metadata (key, value) VALUES (?, ?)",
            sorted(metadata.items()),
        )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise WarehouseError("SQLite integrity verification failed")
        connection.execute("VACUUM")
    finally:
        connection.close()
    os.replace(temporary, output)
    os.chmod(output, 0o644)
    database_sha256 = _file_sha256(output)
    database_bytes = output.stat().st_size
    if latest_story is None:
        raise WarehouseError("Warehouse did not process a story")
    with sqlite3.connect(f"file:{output}?mode=ro", uri=True) as verification:
        counts = {
            "source_commits": verification.execute(
                "SELECT COUNT(*) FROM source_commits"
            ).fetchone()[0],
            "logical_events": verification.execute(
                "SELECT COUNT(*) FROM event_records"
            ).fetchone()[0],
            "event_versions": verification.execute(
                "SELECT COUNT(*) FROM event_versions"
            ).fetchone()[0],
            "snapshot_memberships": verification.execute(
                "SELECT COUNT(*) FROM snapshot_events"
            ).fetchone()[0],
            "execution_receipts": verification.execute(
                "SELECT COUNT(*) FROM execution_receipts"
            ).fetchone()[0],
        }
    builder_path = Path(__file__).resolve()
    manifest = {
        "schema": "rappter-pokemon-warehouse-manifest/1.0",
        "warehouse_id": "rappter-plays-pokemon",
        "license": {
            "id": "CC0-1.0",
            "scope": "publisher-owned compilation and generated telemetry",
            "notice": "https://github.com/kody-w/rappter-plays-pokemon/blob/main/DATA_LICENSE.md",
        },
        "generated_at": latest_commit_at,
        "source": {
            "repository": DEFAULT_REPOSITORY,
            "ref": source_ref,
            "head_commit": commits[-1],
            "story_revision": latest_story["revision"],
            "observed_through": latest_story["coverage"]["last_observed_at"],
        },
        "builder": {
            "commit": str(_git(repository_root, "rev-parse", "HEAD")).strip(),
            "module_sha256": _file_sha256(builder_path),
            "python": ".".join(map(str, __import__("sys").version_info[:3])),
            "sqlite": sqlite3.sqlite_version,
        },
        "warehouse": {
            "schema_version": WAREHOUSE_SCHEMA_VERSION,
            "database_sha256": database_sha256,
            "database_bytes": database_bytes,
            "execution_receipts_sha256": _sha256(receipts_payload),
            "execution_receipts_bytes": len(receipts_payload),
            "counts": counts,
        },
        "privacy": {
            "rom_assets": False,
            "media": False,
            "screenshots": False,
            "raw_model_output": False,
            "chat_or_identities": False,
            "local_paths": False,
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(_canonical(manifest, pretty=True))
    os.chmod(manifest_path, 0o644)
    return manifest


def verify_database(database: Path, manifest_path: Path) -> dict[str, Any]:
    database = database.expanduser().resolve()
    manifest = json.loads(manifest_path.expanduser().resolve().read_text())
    expected = manifest["warehouse"]["database_sha256"]
    actual = _file_sha256(database)
    if not SHA256_RE.fullmatch(expected) or actual != expected:
        raise WarehouseError("Warehouse database hash does not match manifest")
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
    if (
        integrity != "ok"
        or foreign_keys
        or schema_version != WAREHOUSE_SCHEMA_VERSION
    ):
        raise WarehouseError("Warehouse database failed verification")
    return {
        "status": "success",
        "database_sha256": actual,
        "database_bytes": database.stat().st_size,
        "schema_version": schema_version,
    }


def build_static_api(
    database: Path,
    manifest_path: Path,
    output_dir: Path,
    *,
    public_receipts_path: Path | None = None,
) -> dict[str, Any]:
    database = database.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify_database(database, manifest_path)
    files = {
        "manifest.json": {
            "schema": STATIC_API_SCHEMA,
            "name": "rappter-plays-pokemon-warehouse",
            "description": (
                "Public-safe gameplay evidence warehouse built from Git history"
            ),
            "source": manifest["source"],
        },
        "api/v1/status.json": {
            "schema": STATUS_SCHEMA,
            "status": "ready",
            "generated_at": manifest["generated_at"],
            "source_head": manifest["source"]["head_commit"],
            "database_sha256": manifest["warehouse"]["database_sha256"],
            "database_bytes": manifest["warehouse"]["database_bytes"],
            "execution_receipts_sha256": manifest["warehouse"][
                "execution_receipts_sha256"
            ],
            "execution_receipts_bytes": manifest["warehouse"][
                "execution_receipts_bytes"
            ],
            "counts": manifest["warehouse"]["counts"],
        },
        "api/v1/manifest.json": manifest,
        "api/v1/dataset-card.json": {
            "schema": "rappter-pokemon-dataset-card/1.0",
            "dataset_id": "rappter-plays-pokemon",
            "license": manifest["license"],
            "intended_uses": [
                "analysis",
                "retrieval",
                "evaluation",
                "optional downstream model training where permitted",
            ],
            "excluded": [
                "ROM and save data",
                "media and screenshots",
                "coordinates and map IDs",
                "prompts and raw model output",
                "chat and identities",
                "secrets and local paths",
            ],
            "limitations": [
                "single evolving run",
                "not an independent benchmark",
                "early decision evidence unavailable",
                "public story coverage has explicit gaps",
            ],
        },
    }
    for relative, value in files.items():
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_canonical(value, pretty=True))
    warehouse_target = output_dir / "v1" / "warehouse.db"
    warehouse_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(database, warehouse_target)
    (output_dir / "v1" / "schema.sql").write_text(
        WAREHOUSE_SCHEMA_SQL + "\n",
        encoding="utf-8",
    )
    receipts_entry = None
    if public_receipts_path is not None and public_receipts_path.is_file():
        receipts_target = output_dir / "v1" / "execution-receipts.jsonl"
        shutil.copyfile(public_receipts_path, receipts_target)
        receipts_payload = receipts_target.read_bytes()
        receipts_sha = _sha256(receipts_payload)
        if (
            receipts_sha
            != manifest["warehouse"]["execution_receipts_sha256"]
        ):
            raise WarehouseError(
                "Execution receipts do not match the warehouse manifest"
            )
        receipts_entry = {
            "name": "execution-receipts",
            "schema": PUBLIC_SCHEMA,
            "sha256": receipts_sha,
            "sha8": receipts_sha[:12],
            "bytes": len(receipts_payload),
            "src_url": (
                "https://raw.githubusercontent.com/"
                f"{DEFAULT_REPOSITORY}/refs/heads/{DEFAULT_BRANCH}/"
                "v1/execution-receipts.jsonl"
            ),
            "manifest_url": (
                "https://raw.githubusercontent.com/"
                f"{DEFAULT_REPOSITORY}/refs/heads/{DEFAULT_BRANCH}/"
                "api/v1/manifest.json"
            ),
            "source_commit": manifest["source"]["head_commit"],
        }
    elif manifest["warehouse"]["execution_receipts_bytes"] != 0:
        raise WarehouseError("Warehouse receipts are required for static build")
    database_sha = manifest["warehouse"]["database_sha256"]
    raw_base = (
        "https://raw.githubusercontent.com/"
        f"{DEFAULT_REPOSITORY}/refs/heads/{DEFAULT_BRANCH}"
    )
    registry = {
        "schema": STATIC_API_SCHEMA,
        "name": "rappter-plays-pokemon-warehouse",
        "generated": manifest["generated_at"],
        "raw_base": raw_base,
        "pages_base": (
            "https://kody-w.github.io/rappter-plays-pokemon/data/"
        ),
        "summary": {
            "endpoints": 5 if receipts_entry is not None else 4,
            "logical_events": manifest["warehouse"]["counts"]["logical_events"],
            "execution_receipts": manifest["warehouse"]["counts"][
                "execution_receipts"
            ],
        },
        "entries": [
            {
                "name": "warehouse",
                "schema": WAREHOUSE_SCHEMA,
                "sha256": database_sha,
                "sha8": database_sha[:12],
                "bytes": manifest["warehouse"]["database_bytes"],
                "src_url": f"{raw_base}/v1/warehouse.db",
                "manifest_url": f"{raw_base}/api/v1/manifest.json",
                "status_url": f"{raw_base}/api/v1/status.json",
                "source_commit": manifest["source"]["head_commit"],
            }
        ] + ([receipts_entry] if receipts_entry is not None else []),
    }
    (output_dir / "registry.json").write_bytes(_canonical(registry, pretty=True))
    (output_dir / "llms.txt").write_text(
        "# RAPPter Plays Pokemon warehouse\n\n"
        "> A public-safe, read-only, Git-backed gameplay telemetry corpus.\n\n"
        f"- Registry: {raw_base}/registry.json\n"
        f"- Status: {raw_base}/api/v1/status.json\n"
        f"- Manifest: {raw_base}/api/v1/manifest.json\n"
        f"- Dataset card: {raw_base}/api/v1/dataset-card.json\n"
        f"- SQLite: {raw_base}/v1/warehouse.db\n"
        f"- Execution receipts: {raw_base}/v1/execution-receipts.jsonl\n"
        f"- Schema: {raw_base}/v1/schema.sql\n\n"
        "The static API supports GET/HEAD only. It contains no ROM, media, "
        "screenshots, raw model output, chat, identities, secrets, or paths.\n",
        encoding="utf-8",
    )
    (output_dir / ".nojekyll").write_bytes(b"")
    for path in output_dir.rglob("*"):
        if path.is_file():
            os.chmod(path, 0o644)
    return registry


class GitHubWarehousePublisher:
    def __init__(
        self,
        repository: str = DEFAULT_REPOSITORY,
        branch: str = DEFAULT_BRANCH,
    ):
        if not REPOSITORY_RE.fullmatch(repository):
            raise WarehouseError("Repository must be an owner/name pair")
        if not BRANCH_RE.fullmatch(branch):
            raise WarehouseError("Warehouse branch name is invalid")
        if shutil.which("gh") is None:
            raise WarehouseError("GitHub CLI is required to publish")
        self.repository = repository
        self.branch = branch

    def _api(
        self,
        endpoint: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        command = ["gh", "api"]
        if method != "GET":
            command.extend(["--method", method])
        command.append(endpoint)
        input_text = None
        if payload is not None:
            command.extend(["--input", "-"])
            input_text = json.dumps(payload, separators=(",", ":"))
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            if allow_not_found and "HTTP 404" in detail:
                return None
            raise WarehouseError(f"GitHub API request failed: {detail}")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise WarehouseError("GitHub API returned invalid JSON") from error
        if not isinstance(value, dict):
            raise WarehouseError("GitHub API returned an unexpected response")
        return value

    def ensure_branch(self) -> str:
        ref_path = quote(f"heads/{self.branch}", safe="/")
        existing = self._api(
            f"repos/{self.repository}/git/ref/{ref_path}",
            allow_not_found=True,
        )
        if existing is not None:
            sha = existing.get("object", {}).get("sha")
            if isinstance(sha, str) and SHA_RE.fullmatch(sha):
                return sha
            raise WarehouseError("Warehouse ref is invalid")
        marker = self._api(
            f"repos/{self.repository}/git/blobs",
            method="POST",
            payload={
                "content": "RAPPter Plays Pokemon warehouse\n",
                "encoding": "utf-8",
            },
        )
        tree = self._api(
            f"repos/{self.repository}/git/trees",
            method="POST",
            payload={
                "tree": [
                    {
                        "path": ".warehouse",
                        "mode": "100644",
                        "type": "blob",
                        "sha": marker["sha"],
                    }
                ]
            },
        )
        commit = self._api(
            f"repos/{self.repository}/git/commits",
            method="POST",
            payload={
                "message": "data: initialize gameplay warehouse",
                "tree": tree["sha"],
                "parents": [],
            },
        )
        commit_sha = commit.get("sha")
        if not isinstance(commit_sha, str) or not SHA_RE.fullmatch(commit_sha):
            raise WarehouseError("GitHub did not create the warehouse commit")
        try:
            self._api(
                f"repos/{self.repository}/git/refs",
                method="POST",
                payload={
                    "ref": f"refs/heads/{self.branch}",
                    "sha": commit_sha,
                },
            )
        except WarehouseError:
            existing = self._api(
                f"repos/{self.repository}/git/ref/{ref_path}",
                allow_not_found=True,
            )
            if existing is None:
                raise
            commit_sha = existing["object"]["sha"]
        return commit_sha

    def _remote_release_summary(self) -> dict[str, Any] | None:
        path = quote("api/v1/manifest.json", safe="/")
        response = self._api(
            f"repos/{self.repository}/contents/{path}?ref={quote(self.branch)}",
            allow_not_found=True,
        )
        if response is None:
            return None
        try:
            payload = base64.b64decode(
                "".join(response["content"].split()),
                validate=True,
            )
            value = json.loads(payload.decode("utf-8"))
            warehouse = value["warehouse"]
            database_digest = warehouse["database_sha256"]
            receipts_digest = warehouse.get("execution_receipts_sha256")
            counts = warehouse["counts"]
        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as error:
            raise WarehouseError("Remote warehouse manifest is invalid") from error
        if not (
            isinstance(database_digest, str)
            and isinstance(receipts_digest, str)
            and isinstance(counts, dict)
            and isinstance(counts.get("source_commits"), int)
            and isinstance(counts.get("execution_receipts"), int)
        ):
            return None
        return {
            "database_sha256": database_digest,
            "execution_receipts_sha256": receipts_digest,
            "source_commits": counts["source_commits"],
            "execution_receipts": counts["execution_receipts"],
        }

    def publish(self, static_dir: Path) -> dict[str, Any]:
        static_dir = static_dir.expanduser().resolve()
        manifest = json.loads(
            (static_dir / "api/v1/manifest.json").read_text(encoding="utf-8")
        )
        database_sha = manifest["warehouse"]["database_sha256"]
        receipts_sha = manifest["warehouse"]["execution_receipts_sha256"]
        parent_sha = self.ensure_branch()
        remote = self._remote_release_summary()
        candidate_counts = manifest["warehouse"]["counts"]
        if remote is not None and (
            remote["source_commits"] > candidate_counts["source_commits"]
            or remote["execution_receipts"]
            > candidate_counts["execution_receipts"]
        ):
            return {
                "status": "success",
                "changed": False,
                "stale": True,
                "database_sha256": database_sha,
                "branch": self.branch,
            }
        if remote is not None and (
            remote["database_sha256"] == database_sha
            and remote["execution_receipts_sha256"] == receipts_sha
        ):
            return {
                "status": "success",
                "changed": False,
                "database_sha256": database_sha,
                "branch": self.branch,
            }
        publish_files = [
            path
            for path in sorted(static_dir.rglob("*"))
            if path.is_file()
            and not path.is_symlink()
            and (
                not path.relative_to(static_dir).as_posix().startswith(".")
                or path.relative_to(static_dir).as_posix() == ".nojekyll"
            )
        ]
        for path in publish_files:
            if path.stat().st_size > MAX_PUBLISH_FILE_BYTES:
                raise WarehouseError(
                    f"Publish file is too large: {path.name}"
                )
        if any(
            path.stat().st_size > GITHUB_BLOB_API_SAFE_BYTES
            for path in publish_files
        ):
            return self._publish_with_git(
                static_dir,
                manifest,
                database_sha,
            )
        parent = self._api(
            f"repos/{self.repository}/git/commits/{parent_sha}"
        )
        entries = []
        for path in publish_files:
            relative = path.relative_to(static_dir).as_posix()
            payload = path.read_bytes()
            blob = self._api(
                f"repos/{self.repository}/git/blobs",
                method="POST",
                payload={
                    "content": base64.b64encode(payload).decode("ascii"),
                    "encoding": "base64",
                },
            )
            entries.append(
                {
                    "path": relative,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob["sha"],
                }
            )
        tree = self._api(
            f"repos/{self.repository}/git/trees",
            method="POST",
            payload={
                "base_tree": parent["tree"]["sha"],
                "tree": entries,
            },
        )
        commit = self._api(
            f"repos/{self.repository}/git/commits",
            method="POST",
            payload={
                "message": (
                    "data: build warehouse through "
                    f"{manifest['source']['head_commit'][:12]}"
                ),
                "tree": tree["sha"],
                "parents": [parent_sha],
            },
        )
        commit_sha = commit["sha"]
        self._api(
            f"repos/{self.repository}/git/refs/heads/{quote(self.branch)}",
            method="PATCH",
            payload={"sha": commit_sha, "force": False},
        )
        return {
            "status": "success",
            "changed": True,
            "commit": commit_sha,
            "database_sha256": database_sha,
            "branch": self.branch,
        }

    def _publish_with_git(
        self,
        static_dir: Path,
        manifest: dict[str, Any],
        database_sha: str,
    ) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(
            prefix="rappter-warehouse-"
        ) as temporary:
            checkout = Path(temporary) / "repository"
            environment = {
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
            }
            setup = subprocess.run(
                ["gh", "auth", "setup-git"],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            if setup.returncode:
                raise WarehouseError(
                    "GitHub CLI could not configure Git authentication"
                )
            clone = subprocess.run(
                [
                    "gh",
                    "repo",
                    "clone",
                    self.repository,
                    str(checkout),
                    "--",
                    "--depth",
                    "1",
                    "--branch",
                    self.branch,
                ],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            if clone.returncode:
                detail = (clone.stderr or clone.stdout).strip()
                raise WarehouseError(f"Warehouse clone failed: {detail}")
            for source in sorted(static_dir.rglob("*")):
                if not source.is_file() or source.is_symlink():
                    continue
                relative = source.relative_to(static_dir)
                if (
                    relative.as_posix().startswith(".")
                    and relative.as_posix() != ".nojekyll"
                ):
                    continue
                destination = checkout / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
            commands = (
                ["git", "config", "user.name", "rappter-warehouse[bot]"],
                [
                    "git",
                    "config",
                    "user.email",
                    "rappter-warehouse[bot]@users.noreply.github.com",
                ],
                ["git", "add", "-A"],
                [
                    "git",
                    "commit",
                    "-m",
                    (
                        "data: build warehouse through "
                        f"{manifest['source']['head_commit'][:12]}"
                    ),
                ],
            )
            for command in commands:
                result = subprocess.run(
                    command,
                    cwd=checkout,
                    text=True,
                    capture_output=True,
                    check=False,
                    env=environment,
                )
                if result.returncode:
                    detail = (result.stderr or result.stdout).strip()
                    raise WarehouseError(
                        f"Warehouse Git publish failed: {detail}"
                    )
            commit_sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=checkout,
                text=True,
                capture_output=True,
                check=True,
                env=environment,
            ).stdout.strip()
            push = subprocess.run(
                [
                    "git",
                    "push",
                    "origin",
                    f"HEAD:refs/heads/{self.branch}",
                ],
                cwd=checkout,
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            if push.returncode:
                detail = (push.stderr or push.stdout).strip()
                raise WarehouseError(f"Warehouse push failed: {detail}")
            return {
                "status": "success",
                "changed": True,
                "commit": commit_sha,
                "database_sha256": database_sha,
                "branch": self.branch,
                "transport": "git",
            }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and publish the RAPPter Plays Pokemon warehouse"
    )
    parser.add_argument(
        "action",
        choices=("build", "verify", "static", "publish", "all", "watch"),
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--source-ref", default=DEFAULT_SOURCE_REF)
    parser.add_argument("--database", type=Path, default=Path("dist/warehouse.db"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("dist/warehouse-manifest.json"),
    )
    parser.add_argument("--public-receipts", type=Path)
    parser.add_argument(
        "--static-dir",
        type=Path,
        default=Path("dist/warehouse-static"),
    )
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=DEFAULT_WAREHOUSE_STATE_DIR,
    )
    parser.add_argument("--interval", type=int, default=600)
    parser.add_argument("--once", action="store_true")
    return parser


def _watch_cycle(args: argparse.Namespace) -> dict[str, Any]:
    repository_root = args.repository_root.expanduser().resolve()
    state_dir = args.state_dir.expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_dir, 0o700)
    receipts = state_dir / "execution-receipts.jsonl"
    database = state_dir / "warehouse.db"
    manifest = state_dir / "warehouse-manifest.json"
    static_dir = state_dir / "static"
    export = export_public(args.runtime_dir, receipts)
    _git(
        repository_root,
        "fetch",
        "--quiet",
        "origin",
        "story-archive:refs/remotes/origin/story-archive",
    )
    built = build_database(
        repository_root,
        args.source_ref,
        database,
        manifest,
        public_receipts_path=receipts,
    )
    build_static_api(
        database,
        manifest,
        static_dir,
        public_receipts_path=receipts,
    )
    published = GitHubWarehousePublisher(
        args.repository,
        args.branch,
    ).publish(static_dir)
    status = {
        "schema_version": WAREHOUSE_SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source_head": built["source"]["head_commit"],
        "database_sha256": built["warehouse"]["database_sha256"],
        "execution_receipts": export["records"],
        "publish_changed": published["changed"],
        "publish_commit": published.get("commit"),
        "status": "success",
    }
    status_path = state_dir / "status.json"
    status_path.write_bytes(_canonical(status, pretty=True))
    os.chmod(status_path, 0o600)
    return status


def run(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    if args.action == "watch":
        cycles = 0
        failures = 0
        latest: dict[str, Any] = {}
        while True:
            try:
                latest = _watch_cycle(args)
            except (
                OSError,
                sqlite3.Error,
                WarehouseError,
                json.JSONDecodeError,
            ) as error:
                failures += 1
                if args.once:
                    raise
                state_dir = args.state_dir.expanduser().resolve()
                state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                status_path = state_dir / "status.json"
                status_path.write_bytes(
                    _canonical(
                        {
                            "schema_version": WAREHOUSE_SCHEMA_VERSION,
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                            "status": "error",
                            "error_kind": type(error).__name__,
                            "consecutive_failures": failures,
                        },
                        pretty=True,
                    )
                )
                os.chmod(status_path, 0o600)
                time.sleep(min(max(60, args.interval), 60 * 2**min(failures, 4)))
                continue
            failures = 0
            cycles += 1
            if args.once:
                return {"status": "success", "cycles": cycles, "latest": latest}
            time.sleep(max(60, args.interval))
    if args.action in {"build", "all"}:
        manifest = build_database(
            args.repository_root,
            args.source_ref,
            args.database,
            args.manifest,
            public_receipts_path=args.public_receipts,
        )
        if args.action == "build":
            return {"status": "success", "manifest": manifest}
    if args.action == "verify":
        return verify_database(args.database, args.manifest)
    if args.action in {"static", "all"}:
        registry = build_static_api(
            args.database,
            args.manifest,
            args.static_dir,
            public_receipts_path=args.public_receipts,
        )
        if args.action == "static":
            return {"status": "success", "registry": registry}
    if args.action in {"publish", "all"}:
        publisher = GitHubWarehousePublisher(args.repository, args.branch)
        return publisher.publish(args.static_dir)
    raise WarehouseError("Unsupported warehouse action")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run(argv)
    except (
        OSError,
        sqlite3.Error,
        WarehouseError,
        json.JSONDecodeError,
    ) as error:
        result = {"status": "error", "message": str(error)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
