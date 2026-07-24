import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

from rappter_plays_pokemon.improvement import public_records
from rappter_plays_pokemon.story import _with_revision
from rappter_plays_pokemon.warehouse import (
    GitHubWarehousePublisher,
    WarehouseError,
    build_database,
    build_static_api,
    load_public_receipts,
    verify_database,
)


def _git(repo: Path, *args, env=None):
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, **(env or {})},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _event(sequence, *, title, video=None):
    return {
        "id": f"event-{sequence:06d}",
        "sequence": sequence,
        "observed_at": f"2026-07-2{sequence}T00:00:00+00:00",
        "kind": "opening" if sequence == 1 else "progress",
        "chapter": "Setting Out",
        "title": title,
        "summary": f"Verified event {sequence}.",
        "location": "Pallet Town",
        "badges": [],
        "party_size": 1,
        "highest_level": 5,
        "pokedex": {"seen": 1, "caught": 1},
        "play_time_seconds": sequence * 60,
        "coverage_gap_before": False,
        "video": video,
    }


def _story(events):
    return _with_revision(
        {
            "schema_version": 1,
            "story_id": "rappter-plays-pokemon-main-run",
            "updated_at": events[-1]["observed_at"],
            "status": "in_progress",
            "summary": "A deterministic warehouse fixture.",
            "coverage": {
                "first_observed_at": events[0]["observed_at"],
                "last_observed_at": events[-1]["observed_at"],
                "incomplete_before": False,
                "continuous_source": True,
                "event_count": len(events),
            },
            "events": events,
        }
    )


def _commit_story(repo: Path, story, message, timestamp):
    path = repo / "v1" / "story.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(story, indent=2, sort_keys=True) + "\n")
    _git(repo, "add", "v1/story.json")
    env = {
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
    }
    _git(repo, "commit", "-m", message, env=env)
    return _git(repo, "rev-parse", "HEAD")


def _repository(tmp_path):
    repo = tmp_path / "repository"
    repo.mkdir()
    _git(repo, "init", "-b", "story-archive")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / ".story-archive").write_text("fixture\n")
    _git(repo, "add", ".story-archive")
    _git(
        repo,
        "commit",
        "-m",
        "initialize",
        env={
            "GIT_AUTHOR_DATE": "2026-07-20T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-07-20T00:00:00+00:00",
        },
    )
    first = _event(1, title="Opening")
    first_sha = _commit_story(
        repo,
        _story([first]),
        "first story",
        "2026-07-21T00:00:00+00:00",
    )
    changed = _event(
        1,
        title="Opening with video",
        video={"youtube_id": "abcdefghijk", "start_seconds": 1, "end_seconds": 2},
    )
    second_sha = _commit_story(
        repo,
        _story([changed, _event(2, title="Progress")]),
        "second story",
        "2026-07-22T00:00:00+00:00",
    )
    return repo, first_sha, second_sha


def _private_record(sequence, x):
    return {
        "schema_version": 1,
        "event_id": f"run-a:execution:{sequence:08d}",
        "event_type": "execution",
        "run_id": "run-a",
        "sequence": sequence,
        "observed_at": f"2026-07-24T01:0{sequence}:00+00:00",
        "agent_sha256": "a" * 64,
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
        "navigation_schema": 4,
        "decision_id": sequence,
        "source": "model",
        "action_mode": "precision",
        "buttons": ["right"],
        "state": {
            "phase": "overworld",
            "location": "private",
            "map_id": 201,
            "coordinates": {"x": x, "y": 1},
            "badges": ["Boulder"],
            "party_size": 1,
            "pokedex_seen": 1,
            "pokedex_caught": 1,
            "lift_key": False,
            "silph_scope": False,
            "hall_of_fame": False,
            "game_time_seconds": 100 + sequence,
        },
        "expected_destination": None,
        "navigation_mode": "puzzle",
        "stuck_reasons": ["floor_cycle"],
        "tainted": False,
    }


def test_full_history_warehouse_is_deterministic_and_queryable(tmp_path):
    repo, first_sha, second_sha = _repository(tmp_path)
    public = public_records([_private_record(1, 1), _private_record(2, 2)])
    receipts = tmp_path / "receipts.jsonl"
    receipts.write_text("".join(json.dumps(row) + "\n" for row in public))
    first_db = tmp_path / "first.db"
    second_db = tmp_path / "second.db"
    first_manifest = tmp_path / "first-manifest.json"
    second_manifest = tmp_path / "second-manifest.json"

    manifest = build_database(
        repo,
        "story-archive",
        first_db,
        first_manifest,
        public_receipts_path=receipts,
    )
    build_database(
        repo,
        "story-archive",
        second_db,
        second_manifest,
        public_receipts_path=receipts,
    )

    assert first_db.read_bytes() == second_db.read_bytes()
    assert manifest["source"]["head_commit"] == second_sha
    assert verify_database(first_db, first_manifest)["status"] == "success"
    with sqlite3.connect(first_db) as connection:
        assert connection.execute(
            "select count(*) from source_commits"
        ).fetchone()[0] == 2
        assert connection.execute(
            "select count(*) from event_records"
        ).fetchone()[0] == 2
        assert connection.execute(
            "select count(*) from event_versions"
        ).fetchone()[0] == 3
        assert connection.execute(
            "select count(*) from execution_receipts"
        ).fetchone()[0] == 2
        history = connection.execute(
            """
            select commit_sha, version from event_versions
            where record_id like '%event-000001' order by version
            """
        ).fetchall()
        assert history == [(first_sha, 1), (second_sha, 2)]


def test_static_api_and_receipt_allowlist(tmp_path):
    repo, _, _ = _repository(tmp_path)
    database = tmp_path / "warehouse.db"
    manifest = tmp_path / "manifest.json"
    receipts = tmp_path / "receipts.jsonl"
    receipts.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in public_records(
                [_private_record(1, 1), _private_record(2, 2)]
            )
        )
    )
    build_database(
        repo,
        "story-archive",
        database,
        manifest,
        public_receipts_path=receipts,
    )
    static_dir = tmp_path / "static"

    registry = build_static_api(
        database,
        manifest,
        static_dir,
        public_receipts_path=receipts,
    )

    assert registry["schema"] == "rapp-static-api/1.0"
    assert {entry["name"] for entry in registry["entries"]} == {
        "warehouse",
        "execution-receipts",
    }
    assert (static_dir / "registry.json").is_file()
    assert (static_dir / "api/v1/status.json").is_file()
    assert (static_dir / "api/v1/dataset-card.json").is_file()
    assert (static_dir / "v1/warehouse.db").is_file()
    assert (static_dir / "v1/execution-receipts.jsonl").is_file()
    assert (static_dir / "llms.txt").is_file()
    assert (static_dir / ".nojekyll").is_file()

    unsafe = tmp_path / "unsafe.jsonl"
    unsafe.write_text(
        json.dumps(
            {
                "schema": "rappter-pokemon-execution/1.0",
                "record_id": "sha256:" + "a" * 64,
                "coordinates": [1, 2],
            }
        )
        + "\n"
    )
    with pytest.raises(WarehouseError, match="allowlist"):
        load_public_receipts(unsafe)


def test_publisher_refuses_monotonic_receipt_regression(monkeypatch, tmp_path):
    repo, _, _ = _repository(tmp_path)
    database = tmp_path / "warehouse.db"
    manifest = tmp_path / "manifest.json"
    receipts = tmp_path / "receipts.jsonl"
    receipts.write_text(
        "".join(
            json.dumps(row) + "\n"
            for row in public_records(
                [_private_record(1, 1), _private_record(2, 2)]
            )
        )
    )
    build_database(
        repo,
        "story-archive",
        database,
        manifest,
        public_receipts_path=receipts,
    )
    static_dir = tmp_path / "static"
    build_static_api(
        database,
        manifest,
        static_dir,
        public_receipts_path=receipts,
    )
    monkeypatch.setattr(
        "rappter_plays_pokemon.warehouse.shutil.which",
        lambda name: "/usr/bin/gh" if name == "gh" else None,
    )
    publisher = GitHubWarehousePublisher("owner/repository", "warehouse")
    monkeypatch.setattr(publisher, "ensure_branch", lambda: "a" * 40)
    monkeypatch.setattr(
        publisher,
        "_remote_release_summary",
        lambda: {
            "database_sha256": "b" * 64,
            "execution_receipts_sha256": "c" * 64,
            "source_commits": 2,
            "execution_receipts": 3,
        },
    )
    monkeypatch.setattr(
        publisher,
        "_api",
        lambda *args, **kwargs: pytest.fail("stale publish reached GitHub API"),
    )

    result = publisher.publish(static_dir)

    assert result["changed"] is False
    assert result["stale"] is True


def test_large_warehouse_uses_git_transport(monkeypatch, tmp_path):
    static_dir = tmp_path / "static"
    manifest_path = static_dir / "api" / "v1" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "source": {"head_commit": "a" * 40},
                "warehouse": {
                    "database_sha256": "b" * 64,
                    "execution_receipts_sha256": "c" * 64,
                    "counts": {
                        "source_commits": 2,
                        "execution_receipts": 3,
                    },
                },
            }
        )
    )
    database = static_dir / "v1" / "warehouse.db"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"x")
    monkeypatch.setattr(
        "rappter_plays_pokemon.warehouse.GITHUB_BLOB_API_SAFE_BYTES",
        0,
    )
    monkeypatch.setattr(
        "rappter_plays_pokemon.warehouse.shutil.which",
        lambda name: "/usr/bin/gh" if name == "gh" else None,
    )
    publisher = GitHubWarehousePublisher("owner/repository", "warehouse")
    monkeypatch.setattr(publisher, "ensure_branch", lambda: "d" * 40)
    monkeypatch.setattr(publisher, "_remote_release_summary", lambda: None)
    called = {}
    monkeypatch.setattr(
        publisher,
        "_publish_with_git",
        lambda static, manifest, digest: called.update(
            static=static,
            digest=digest,
        )
        or {"status": "success", "changed": True},
    )

    result = publisher.publish(static_dir)

    assert result["changed"] is True
    assert called["static"] == static_dir
    assert called["digest"] == "b" * 64
