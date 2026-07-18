from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from rappter_plays_pokemon.story import (
    GitHubPublisher,
    StoryError,
    apply_theater_config,
    build_story,
    load_theater_config,
    merge_stories,
    story_bytes,
    validate_public_story,
    write_private_story,
)


def write_clip(
    runtime: Path,
    sequence: int,
    observed_at: datetime,
    *,
    reason: str = "automatic clip boundary",
    location: str = "Pallet Town",
    badges: list[str] | None = None,
    party_size: int = 1,
    caught: int = 1,
    seen: int = 2,
    hall_of_fame: bool = False,
) -> None:
    clips = runtime / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    stamp = observed_at.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")
    media_name = f"clip-{sequence:04d}-{stamp}.mp4"
    media = clips / media_name
    media.write_bytes(b"synthetic-completed-clip")
    manifest = {
        "schema_version": 1,
        "name": media_name,
        "started_at": (
            observed_at - timedelta(minutes=10)
        ).isoformat(),
        "completed_at": observed_at.isoformat(),
        "reason": reason,
        "frames": 18000,
        "fps": 30,
        "duration_seconds": 600,
        "bytes": media.stat().st_size,
        "sha256": "0" * 64,
        "game_state": {
            "location": location,
            "badges": badges or [],
            "party_count": party_size,
            "party": [
                {"nickname": f"PRIVATE-{index}", "level": 10 + index}
                for index in range(party_size)
            ],
            "pokedex": {"caught": caught, "seen": seen, "total": 151},
            "play_time": {
                "hours": sequence,
                "minutes": 0,
                "seconds": 0,
            },
            "hall_of_fame": hall_of_fame,
            "coordinates": {"x": 1, "y": 2},
            "player_name": "PRIVATE",
            "rival_name": "PRIVATE",
            "screen_text": "PRIVATE",
        },
    }
    media.with_suffix(".json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


def test_story_is_deterministic_grounded_and_public_safe(tmp_path):
    start = datetime(2026, 7, 18, tzinfo=timezone.utc)
    write_clip(tmp_path, 1, start)
    write_clip(
        tmp_path,
        2,
        start + timedelta(minutes=5),
        reason="Copilot checkpoint: private model objective",
        location="Viridian City",
    )
    write_clip(
        tmp_path,
        3,
        start + timedelta(minutes=20),
        reason="Badge milestone: Boulder",
        location="Pewter Gym",
        badges=["Boulder"],
    )
    write_clip(
        tmp_path,
        5,
        start + timedelta(minutes=40),
        reason="Copilot checkpoint: another private objective",
        location="Route 3",
        badges=["Boulder"],
        party_size=2,
        caught=2,
        seen=8,
    )

    first = build_story(tmp_path)
    second = build_story(tmp_path)

    assert first == second
    assert [event["kind"] for event in first["events"]] == [
        "opening",
        "badge",
        "party",
    ]
    assert first["coverage"] == {
        "first_observed_at": "2026-07-18T00:00:00Z",
        "last_observed_at": "2026-07-18T00:40:00Z",
        "incomplete_before": False,
        "continuous_source": False,
        "event_count": 3,
    }
    serialized = story_bytes(first).decode("utf-8").lower()
    for forbidden in (
        "private",
        "objective",
        "reason",
        "nickname",
        "coordinates",
        "player_name",
        "rival_name",
        "screen_text",
        "\"rom",
        "/users/",
    ):
        assert forbidden not in serialized


def test_story_marks_an_incomplete_retained_beginning(tmp_path):
    write_clip(
        tmp_path,
        36,
        datetime(2026, 7, 18, tzinfo=timezone.utc),
        location="Pewter City",
    )

    story = build_story(tmp_path)

    assert story["coverage"]["incomplete_before"] is True
    assert "earliest retained" in story["events"][0]["summary"].lower()


def test_story_rejects_manifest_media_mismatch_and_symlinks(tmp_path):
    observed_at = datetime(2026, 7, 18, tzinfo=timezone.utc)
    write_clip(tmp_path, 1, observed_at)
    manifest = next((tmp_path / "clips").glob("*.json"))
    value = json.loads(manifest.read_text())
    value["bytes"] += 1
    manifest.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(StoryError, match="size does not match"):
        build_story(tmp_path)

    manifest.unlink()
    manifest.symlink_to(tmp_path / "missing.json")
    with pytest.raises(StoryError, match="regular non-symlink"):
        build_story(tmp_path)


def test_story_merge_preserves_events_that_left_local_retention(tmp_path):
    start = datetime(2026, 7, 18, tzinfo=timezone.utc)
    old_runtime = tmp_path / "old"
    write_clip(old_runtime, 1, start, location="Pallet Town")
    write_clip(
        old_runtime,
        2,
        start + timedelta(hours=1),
        reason="Badge milestone: Boulder",
        location="Pewter Gym",
        badges=["Boulder"],
    )
    new_runtime = tmp_path / "new"
    write_clip(
        new_runtime,
        10,
        start + timedelta(hours=2),
        location="Cerulean City",
        badges=["Boulder"],
    )

    merged = merge_stories(
        build_story(old_runtime),
        build_story(new_runtime),
    )

    assert [event["id"] for event in merged["events"]] == [
        "event-000001",
        "event-000002",
        "event-000010",
    ]
    assert merged["coverage"]["incomplete_before"] is False
    validate_public_story(merged)


def test_story_merge_cannot_rewrite_an_archived_completion(tmp_path):
    start = datetime(2026, 7, 18, tzinfo=timezone.utc)
    completed_runtime = tmp_path / "completed"
    write_clip(completed_runtime, 1, start)
    write_clip(
        completed_runtime,
        2,
        start + timedelta(hours=1),
        location="Indigo Plateau",
        hall_of_fame=True,
    )
    retained_runtime = tmp_path / "retained"
    write_clip(
        retained_runtime,
        2,
        start + timedelta(hours=1),
        location="Indigo Plateau",
        hall_of_fame=False,
    )

    merged = merge_stories(
        build_story(completed_runtime),
        build_story(retained_runtime),
    )

    assert merged["events"][-1]["kind"] == "completion"
    assert merged["status"] == "completed"


def test_source_gap_is_carried_to_the_next_published_event(tmp_path):
    start = datetime(2026, 7, 18, tzinfo=timezone.utc)
    write_clip(tmp_path, 1, start)
    write_clip(tmp_path, 2, start + timedelta(minutes=5))
    write_clip(tmp_path, 4, start + timedelta(minutes=10))
    write_clip(
        tmp_path,
        5,
        start + timedelta(minutes=20),
        reason="Copilot checkpoint: private objective",
        location="Viridian City",
    )

    story = build_story(tmp_path)

    assert [event["id"] for event in story["events"]] == [
        "event-000001",
        "event-000005",
    ]
    assert story["events"][-1]["coverage_gap_before"] is True
    assert story["coverage"]["continuous_source"] is False


def test_story_validation_rejects_unknown_public_fields(tmp_path):
    write_clip(
        tmp_path,
        1,
        datetime(2026, 7, 18, tzinfo=timezone.utc),
    )
    story = build_story(tmp_path)
    story["events"][0]["raw_manifest"] = "private"

    with pytest.raises(StoryError, match="unexpected fields"):
        validate_public_story(story)


def test_private_story_write_is_atomic_and_mode_0600(tmp_path):
    runtime = tmp_path / "runtime"
    write_clip(
        runtime,
        1,
        datetime(2026, 7, 18, tzinfo=timezone.utc),
    )
    output = tmp_path / "editor" / "story.json"

    assert write_private_story(build_story(runtime), output) == output
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert list(output.parent.glob("*.tmp")) == []


def test_theater_config_adds_only_bounded_youtube_segments(tmp_path):
    runtime = tmp_path / "runtime"
    write_clip(
        runtime,
        1,
        datetime(2026, 7, 18, tzinfo=timezone.utc),
    )
    config = tmp_path / "theater.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "events": {
                    "event-000001": {
                        "youtube_id": "NBSKt_dou6o",
                        "start_seconds": 10,
                        "end_seconds": 70,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    story = apply_theater_config(
        build_story(runtime),
        load_theater_config(config),
    )

    assert story["events"][0]["video"] == {
        "youtube_id": "NBSKt_dou6o",
        "start_seconds": 10,
        "end_seconds": 70,
    }
    validate_public_story(story)

    value = json.loads(config.read_text())
    value["events"]["event-000001"]["end_seconds"] = 5000
    config.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(StoryError, match="video range"):
        load_theater_config(config)


def test_publisher_target_and_raw_url_are_bounded(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda command: f"/usr/bin/{command}")

    publisher = GitHubPublisher()

    assert publisher.raw_url == (
        "https://raw.githubusercontent.com/kody-w/rappter-plays-pokemon/"
        "refs/heads/story-archive/v1/story.json"
    )
    with pytest.raises(StoryError, match="owner/name"):
        GitHubPublisher("../other")
    with pytest.raises(StoryError, match="branch"):
        GitHubPublisher(branch="../main")


def test_publisher_rewrites_an_in_memory_legacy_migration(
    monkeypatch,
    tmp_path,
):
    runtime = tmp_path / "runtime"
    write_clip(
        runtime,
        1,
        datetime(2026, 7, 18, tzinfo=timezone.utc),
    )
    story = build_story(runtime)
    monkeypatch.setattr("shutil.which", lambda command: f"/usr/bin/{command}")
    publisher = GitHubPublisher()
    monkeypatch.setattr(publisher, "ensure_branch", lambda: None)
    monkeypatch.setattr(
        publisher,
        "read_remote_story",
        lambda: (story, "a" * 40, True),
    )
    calls = []

    def api(endpoint, **kwargs):
        calls.append((endpoint, kwargs))
        return {"commit": {"sha": "b" * 40}}

    monkeypatch.setattr(publisher, "_api", api)

    result = publisher.publish(story)

    assert result["changed"] is True
    assert len(calls) == 1
    assert calls[0][1]["method"] == "PUT"
