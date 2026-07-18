"""Build and publish a public-safe story from finalized gameplay manifests."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported runtime is macOS
    fcntl = None


SCHEMA_VERSION = 1
STORY_ID = "rappter-plays-pokemon-main-run"
DEFAULT_RUNTIME_DIR = Path.home() / ".openrappter" / "pokemon-red"
DEFAULT_EDITOR_DIR = Path.home() / ".openrappter" / "pokemon-red-story"
DEFAULT_REPOSITORY = "kody-w/rappter-plays-pokemon"
DEFAULT_BRANCH = "story-archive"
REMOTE_STORY_PATH = "v1/story.json"
MAX_SOURCE_MANIFEST_BYTES = 128 * 1024
MAX_THEATER_CONFIG_BYTES = 128 * 1024
MAX_PUBLIC_STORY_BYTES = 1024 * 1024
MAX_PUBLIC_EVENTS = 512
MIN_PROGRESS_EVENT_SECONDS = 60 * 60
MIN_LOCATION_EVENT_SECONDS = 15 * 60
BADGE_NAMES = (
    "Boulder",
    "Cascade",
    "Thunder",
    "Rainbow",
    "Soul",
    "Marsh",
    "Volcano",
    "Earth",
)
CLIP_MANIFEST_RE = re.compile(
    r"^clip-(?P<sequence>\d{4,})-\d{8}-\d{6}(?:-\d{6})?\.json$"
)
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
EVENT_ID_RE = re.compile(r"^event-\d{6,}$")
PUBLIC_STORY_KEYS = {
    "schema_version",
    "story_id",
    "revision",
    "updated_at",
    "status",
    "summary",
    "coverage",
    "events",
}
PUBLIC_COVERAGE_KEYS = {
    "first_observed_at",
    "last_observed_at",
    "incomplete_before",
    "continuous_source",
    "event_count",
}
PUBLIC_EVENT_KEYS = {
    "id",
    "sequence",
    "observed_at",
    "kind",
    "chapter",
    "title",
    "summary",
    "location",
    "badges",
    "party_size",
    "highest_level",
    "pokedex",
    "play_time_seconds",
    "coverage_gap_before",
    "video",
}
PUBLIC_EVENT_KINDS = {
    "opening",
    "badge",
    "completion",
    "party",
    "pokedex",
    "journey",
    "progress",
    "continuity",
}
YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
VIDEO_KEYS = {"youtube_id", "start_seconds", "end_seconds"}
BROADCAST_KEYS = {"youtube_id", "started_at", "ended_at"}


class StoryError(RuntimeError):
    """Raised when story inputs or publication fail closed."""


@dataclass(frozen=True)
class Observation:
    sequence: int
    observed_at: str
    observed_datetime: datetime
    reason: str
    location: str | None
    badges: tuple[str, ...]
    party_size: int | None
    highest_level: int | None
    seen: int | None
    caught: int | None
    play_time_seconds: int | None
    hall_of_fame: bool


def _bounded_text(value: Any, limit: int, field: str) -> str:
    if not isinstance(value, str):
        raise StoryError(f"{field} must be text")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > limit:
        raise StoryError(f"{field} must contain 1-{limit} characters")
    if any(ord(character) < 32 for character in normalized):
        raise StoryError(f"{field} contains control characters")
    return normalized


def _optional_text(value: Any, limit: int, field: str) -> str | None:
    if value in (None, ""):
        return None
    return _bounded_text(value, limit, field)


def _bounded_int(
    value: Any,
    minimum: int,
    maximum: int,
    field: str,
) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise StoryError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise StoryError(f"{field} must be {minimum}-{maximum}")
    return value


def _timestamp(value: Any, field: str) -> tuple[str, datetime]:
    text = _bounded_text(value, 48, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise StoryError(f"{field} is not an RFC3339 timestamp") from error
    if parsed.tzinfo is None or not 2000 <= parsed.year <= 2100:
        raise StoryError(f"{field} must include a valid timezone")
    utc = parsed.astimezone(timezone.utc)
    return utc.isoformat().replace("+00:00", "Z"), utc


def _play_time_seconds(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise StoryError("game_state.play_time must be an object")
    hours = _bounded_int(value.get("hours"), 0, 9999, "play_time.hours")
    minutes = _bounded_int(value.get("minutes"), 0, 59, "play_time.minutes")
    seconds = _bounded_int(value.get("seconds"), 0, 59, "play_time.seconds")
    if hours is None or minutes is None or seconds is None:
        return None
    return hours * 3600 + minutes * 60 + seconds


def _regular_file(path: Path, field: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise StoryError(f"Cannot inspect {field}: {path.name}: {error}") from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise StoryError(f"{field} must be a regular non-symlink file: {path.name}")
    return metadata


def _read_observation(path: Path) -> Observation:
    match = CLIP_MANIFEST_RE.fullmatch(path.name)
    if not match:
        raise StoryError(f"Unexpected clip manifest name: {path.name}")
    metadata = _regular_file(path, "clip manifest")
    if not 1 <= metadata.st_size <= MAX_SOURCE_MANIFEST_BYTES:
        raise StoryError(f"Clip manifest has an invalid size: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StoryError(f"Cannot read clip manifest {path.name}: {error}") from error
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise StoryError(f"Unsupported clip manifest: {path.name}")

    expected_media_name = path.with_suffix(".mp4").name
    if value.get("name") != expected_media_name:
        raise StoryError(f"Clip manifest/media name mismatch: {path.name}")
    media = path.with_suffix(".mp4")
    media_metadata = _regular_file(media, "completed clip")
    declared_bytes = _bounded_int(
        value.get("bytes"),
        1,
        100 * 1024 * 1024,
        f"{path.name}.bytes",
    )
    if declared_bytes != media_metadata.st_size:
        raise StoryError(f"Clip size does not match its manifest: {path.name}")

    observed_at, observed_datetime = _timestamp(
        value.get("completed_at"),
        f"{path.name}.completed_at",
    )
    reason = _bounded_text(value.get("reason"), 512, f"{path.name}.reason")
    game_state = value.get("game_state")
    if not isinstance(game_state, dict):
        raise StoryError(f"{path.name}.game_state must be an object")

    location = _optional_text(
        game_state.get("location"),
        80,
        f"{path.name}.game_state.location",
    )
    badges_value = game_state.get("badges", [])
    if not isinstance(badges_value, list) or len(badges_value) > len(BADGE_NAMES):
        raise StoryError(f"{path.name}.game_state.badges is invalid")
    badges: list[str] = []
    for badge in badges_value:
        name = _bounded_text(badge, 24, f"{path.name}.badge")
        if name not in BADGE_NAMES or name in badges:
            raise StoryError(f"{path.name} contains an invalid badge set")
        badges.append(name)

    party_value = game_state.get("party", [])
    if not isinstance(party_value, list) or len(party_value) > 6:
        raise StoryError(f"{path.name}.game_state.party is invalid")
    levels: list[int] = []
    for index, member in enumerate(party_value):
        if not isinstance(member, dict):
            raise StoryError(f"{path.name}.party[{index}] must be an object")
        level = _bounded_int(
            member.get("level"),
            1,
            100,
            f"{path.name}.party[{index}].level",
        )
        if level is not None:
            levels.append(level)
    party_size = _bounded_int(
        game_state.get("party_count", len(party_value)),
        0,
        6,
        f"{path.name}.party_count",
    )

    pokedex = game_state.get("pokedex")
    if pokedex is not None and not isinstance(pokedex, dict):
        raise StoryError(f"{path.name}.game_state.pokedex must be an object")
    pokedex = pokedex or {}
    seen = _bounded_int(pokedex.get("seen"), 0, 151, f"{path.name}.pokedex.seen")
    caught = _bounded_int(
        pokedex.get("caught"),
        0,
        151,
        f"{path.name}.pokedex.caught",
    )
    if seen is not None and caught is not None and caught > seen:
        raise StoryError(f"{path.name} has caught greater than seen")

    return Observation(
        sequence=int(match.group("sequence")),
        observed_at=observed_at,
        observed_datetime=observed_datetime,
        reason=reason,
        location=location,
        badges=tuple(badges),
        party_size=party_size,
        highest_level=max(levels) if levels else None,
        seen=seen,
        caught=caught,
        play_time_seconds=_play_time_seconds(game_state.get("play_time")),
        hall_of_fame=game_state.get("hall_of_fame") is True,
    )


def load_observations(runtime_dir: Path) -> list[Observation]:
    clips_dir = runtime_dir.expanduser().resolve() / "clips"
    if not clips_dir.is_dir() or clips_dir.is_symlink():
        raise StoryError(f"Missing private clips directory: {clips_dir}")
    observations = [
        _read_observation(path)
        for path in sorted(clips_dir.glob("clip-*.json"))
    ]
    if not observations:
        raise StoryError(f"No completed clip manifests found in {clips_dir}")
    observations.sort(key=lambda item: (item.observed_datetime, item.sequence))
    seen_sequences: set[int] = set()
    for observation in observations:
        if observation.sequence in seen_sequences:
            raise StoryError(f"Duplicate clip sequence: {observation.sequence}")
        seen_sequences.add(observation.sequence)
    return observations


def _named_location(value: str | None) -> bool:
    return bool(value and not value.startswith("Map 0x"))


def _chapter(badges: tuple[str, ...], completed: bool) -> str:
    if completed:
        return "Hall of Fame"
    if not badges:
        return "Setting Out"
    if len(badges) == 1:
        return "Beyond the Boulder Badge"
    if len(badges) == 2:
        return "Beyond the Cascade Badge"
    if len(badges) == 3:
        return "Beyond the Thunder Badge"
    if len(badges) == 4:
        return "Beyond the Rainbow Badge"
    return f"{len(badges)} Badges Earned"


def _state_clause(observation: Observation) -> str:
    facts: list[str] = []
    if observation.badges:
        badge_label = "badge" if len(observation.badges) == 1 else "badges"
        facts.append(f"{len(observation.badges)} {badge_label}")
    if observation.caught is not None:
        facts.append(f"{observation.caught} caught Pokémon")
    if observation.party_size is not None:
        facts.append(f"a party of {observation.party_size}")
    if not facts:
        return ""
    if len(facts) == 1:
        joined = facts[0]
    elif len(facts) == 2:
        joined = f"{facts[0]} and {facts[1]}"
    else:
        joined = ", ".join(facts[:-1]) + f", and {facts[-1]}"
    return f"The retained state shows {joined}."


def _display_location(value: str | None) -> str:
    return (value or "Unknown location").replace("Pokemon", "Pokémon")


def _event(
    observation: Observation,
    previous: Observation | None,
    *,
    kind: str,
    coverage_gap: bool,
) -> dict[str, Any]:
    location = _display_location(observation.location)
    previous_location = _display_location(previous.location) if previous else None
    added_badges = [
        badge
        for badge in observation.badges
        if previous is None or badge not in previous.badges
    ]
    if kind == "opening":
        title = f"Earliest retained chapter: {location}"
        summary = (
            f"The public story begins with the earliest retained recording in "
            f"{location}, not necessarily the first minutes of the run."
        )
    elif kind == "badge":
        badge_text = " and ".join(f"{badge} Badge" for badge in added_badges)
        title = f"{badge_text} observed"
        summary = (
            f"The recorded state now includes {badge_text} in {location}, "
            f"bringing the verified total to {len(observation.badges)}."
        )
    elif kind == "completion":
        title = "Hall of Fame reached"
        summary = (
            "The retained state reports that the run reached the Hall of Fame, "
            "completing the autonomous playthrough."
        )
    elif kind == "continuity":
        title = f"A new continuity in {location}"
        summary = (
            "The observed progress counters moved backward, so this entry starts "
            "a separate continuity instead of claiming uninterrupted progress."
        )
    elif kind == "party":
        title = f"The party grows in {location}"
        summary = (
            f"The recorded party size increased from {previous.party_size} to "
            f"{observation.party_size} while the run was in {location}."
        )
    elif kind == "pokedex":
        title = f"Pokédex progress in {location}"
        summary = (
            f"The verified caught count increased from {previous.caught} to "
            f"{observation.caught} by this retained checkpoint."
        )
    elif kind == "journey":
        title = f"Reaching {location}"
        transition = (
            f"from {previous_location} to {location}"
            if previous_location
            else f"to {location}"
        )
        prefix = (
            "By the next retained checkpoint, the run"
            if coverage_gap
            else "The run"
        )
        summary = f"{prefix} had moved {transition}."
    else:
        title = f"Checkpoint in {location}"
        summary = (
            f"A retained progress checkpoint records the autonomous run in "
            f"{location}."
        )
    clause = _state_clause(observation)
    if clause and clause not in summary:
        summary = f"{summary} {clause}"
    return {
        "id": f"event-{observation.sequence:06d}",
        "sequence": observation.sequence,
        "observed_at": observation.observed_at,
        "kind": kind,
        "chapter": _chapter(observation.badges, observation.hall_of_fame),
        "title": title,
        "summary": summary,
        "location": location,
        "badges": list(observation.badges),
        "party_size": observation.party_size,
        "highest_level": observation.highest_level,
        "pokedex": {
            "seen": observation.seen,
            "caught": observation.caught,
        },
        "play_time_seconds": observation.play_time_seconds,
        "coverage_gap_before": coverage_gap,
        "video": None,
    }


def curate_events(observations: Sequence[Observation]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    previous: Observation | None = None
    last_selected: Observation | None = None
    gap_since_last_event = False
    for observation in observations:
        gap_since_last_event = gap_since_last_event or bool(
            previous is not None and observation.sequence != previous.sequence + 1
        )
        kind: str | None = None
        if observation.hall_of_fame and (
            previous is None or not previous.hall_of_fame
        ):
            kind = "completion"
        elif (
            observation.badges
            and previous is not None
            and any(badge not in previous.badges for badge in observation.badges)
        ):
            kind = "badge"
        elif previous is None:
            kind = "opening"
        elif (
            len(observation.badges) < len(previous.badges)
            or (
                observation.caught is not None
                and previous.caught is not None
                and observation.caught < previous.caught
            )
        ):
            kind = "continuity"
        elif (
            observation.party_size is not None
            and previous.party_size is not None
            and observation.party_size > previous.party_size
        ):
            kind = "party"
        elif (
            observation.caught is not None
            and previous.caught is not None
            and observation.caught > previous.caught
            and (
                last_selected is None
                or (
                    observation.observed_datetime
                    - last_selected.observed_datetime
                ).total_seconds()
                >= MIN_LOCATION_EVENT_SECONDS
            )
        ):
            kind = "pokedex"
        elif (
            observation.reason.startswith("Copilot checkpoint:")
            and _named_location(observation.location)
            and observation.location != last_selected.location
            and (
                observation.observed_datetime - last_selected.observed_datetime
            ).total_seconds()
            >= MIN_LOCATION_EVENT_SECONDS
        ):
            kind = "journey"
        elif (
            observation.reason != "session stopped"
            and (
                observation.observed_datetime - last_selected.observed_datetime
            ).total_seconds()
            >= MIN_PROGRESS_EVENT_SECONDS
            and _named_location(observation.location)
        ):
            kind = "progress"

        if kind is not None:
            event_previous = (
                last_selected
                if kind in {"journey", "progress"}
                else previous
            )
            events.append(
                _event(
                    observation,
                    event_previous,
                    kind=kind,
                    coverage_gap=gap_since_last_event,
                )
            )
            last_selected = observation
            gap_since_last_event = False
        previous = observation
    return events


def _overview(events: Sequence[dict[str, Any]]) -> str:
    first = events[0]
    latest = events[-1]
    badge_count = len(latest["badges"])
    status = (
        "The retained story reaches the Hall of Fame."
        if latest["kind"] == "completion"
        else f"The latest published chapter reaches {latest['location']}."
    )
    return (
        f"The archive starts with the earliest retained evidence in "
        f"{first['location']} and follows {len(events)} verified key events. "
        f"It currently records {badge_count} badges. {status}"
    )


def _story_without_revision(
    events: Sequence[dict[str, Any]],
    *,
    incomplete_before: bool,
    continuous_source: bool,
) -> dict[str, Any]:
    if not events:
        raise StoryError("A public story requires at least one event")
    first = events[0]
    latest = events[-1]
    return {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "updated_at": latest["observed_at"],
        "status": (
            "completed"
            if any(event["kind"] == "completion" for event in events)
            else "in_progress"
        ),
        "summary": _overview(events),
        "coverage": {
            "first_observed_at": first["observed_at"],
            "last_observed_at": latest["observed_at"],
            "incomplete_before": incomplete_before,
            "continuous_source": continuous_source,
            "event_count": len(events),
        },
        "events": list(events),
    }


def _with_revision(story: dict[str, Any]) -> dict[str, Any]:
    body = dict(story)
    body.pop("revision", None)
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    result = dict(body)
    result["revision"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return result


def build_story(runtime_dir: Path = DEFAULT_RUNTIME_DIR) -> dict[str, Any]:
    observations = load_observations(runtime_dir)
    events = curate_events(observations)
    continuous_source = all(
        current.sequence == previous.sequence + 1
        for previous, current in zip(
            observations,
            observations[1:],
            strict=False,
        )
    )
    story = _story_without_revision(
        events,
        incomplete_before=observations[0].sequence > 1,
        continuous_source=continuous_source,
    )
    result = _with_revision(story)
    validate_public_story(result)
    return result


def validate_public_story(story: Any) -> dict[str, Any]:
    if not isinstance(story, dict) or set(story) != PUBLIC_STORY_KEYS:
        raise StoryError("Public story has unexpected top-level fields")
    if story.get("schema_version") != SCHEMA_VERSION:
        raise StoryError("Unsupported public story schema")
    if story.get("story_id") != STORY_ID:
        raise StoryError("Unexpected public story ID")
    revision = _bounded_text(story.get("revision"), 80, "revision")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", revision):
        raise StoryError("Public story revision is invalid")
    _timestamp(story.get("updated_at"), "updated_at")
    if story.get("status") not in {"in_progress", "completed"}:
        raise StoryError("Public story status is invalid")
    _bounded_text(story.get("summary"), 1000, "summary")

    coverage = story.get("coverage")
    if not isinstance(coverage, dict) or set(coverage) != PUBLIC_COVERAGE_KEYS:
        raise StoryError("Public story coverage is invalid")
    first_at, _ = _timestamp(coverage.get("first_observed_at"), "coverage.first")
    last_at, _ = _timestamp(coverage.get("last_observed_at"), "coverage.last")
    if first_at > last_at:
        raise StoryError("Public story coverage is reversed")
    if not isinstance(coverage.get("incomplete_before"), bool):
        raise StoryError("coverage.incomplete_before must be boolean")
    if not isinstance(coverage.get("continuous_source"), bool):
        raise StoryError("coverage.continuous_source must be boolean")

    events = story.get("events")
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_PUBLIC_EVENTS:
        raise StoryError("Public story event count is invalid")
    if coverage.get("event_count") != len(events):
        raise StoryError("Public story event count does not match coverage")

    ids: set[str] = set()
    previous_order: tuple[str, int] | None = None
    for index, event in enumerate(events):
        if not isinstance(event, dict) or set(event) != PUBLIC_EVENT_KEYS:
            raise StoryError(f"Event {index} has unexpected fields")
        event_id = _bounded_text(event.get("id"), 80, f"events[{index}].id")
        if not EVENT_ID_RE.fullmatch(event_id) or event_id in ids:
            raise StoryError(f"Event {index} has an invalid or duplicate ID")
        ids.add(event_id)
        sequence = _bounded_int(
            event.get("sequence"),
            1,
            99999999,
            f"events[{index}].sequence",
        )
        observed_at, _ = _timestamp(
            event.get("observed_at"),
            f"events[{index}].observed_at",
        )
        order = (observed_at, int(sequence))
        if previous_order is not None and order <= previous_order:
            raise StoryError("Public story events are not strictly ordered")
        previous_order = order
        if event.get("kind") not in PUBLIC_EVENT_KINDS:
            raise StoryError(f"Event {index} kind is invalid")
        _bounded_text(event.get("chapter"), 100, f"events[{index}].chapter")
        _bounded_text(event.get("title"), 120, f"events[{index}].title")
        _bounded_text(event.get("summary"), 800, f"events[{index}].summary")
        _bounded_text(event.get("location"), 80, f"events[{index}].location")
        badges = event.get("badges")
        if (
            not isinstance(badges, list)
            or len(badges) > len(BADGE_NAMES)
            or len(set(badges)) != len(badges)
            or any(badge not in BADGE_NAMES for badge in badges)
        ):
            raise StoryError(f"Event {index} badges are invalid")
        _bounded_int(event.get("party_size"), 0, 6, f"events[{index}].party_size")
        _bounded_int(
            event.get("highest_level"),
            1,
            100,
            f"events[{index}].highest_level",
        )
        pokedex = event.get("pokedex")
        if not isinstance(pokedex, dict) or set(pokedex) != {"seen", "caught"}:
            raise StoryError(f"Event {index} Pokédex is invalid")
        seen = _bounded_int(pokedex.get("seen"), 0, 151, f"events[{index}].seen")
        caught = _bounded_int(
            pokedex.get("caught"),
            0,
            151,
            f"events[{index}].caught",
        )
        if seen is not None and caught is not None and caught > seen:
            raise StoryError(f"Event {index} caught count exceeds seen count")
        _bounded_int(
            event.get("play_time_seconds"),
            0,
            100000000,
            f"events[{index}].play_time_seconds",
        )
        if not isinstance(event.get("coverage_gap_before"), bool):
            raise StoryError(f"Event {index} gap marker must be boolean")
        video = event.get("video")
        if video is not None:
            if not isinstance(video, dict) or set(video) != VIDEO_KEYS:
                raise StoryError(f"Event {index} video reference is invalid")
            youtube_id = video.get("youtube_id")
            if not isinstance(youtube_id, str) or not YOUTUBE_ID_RE.fullmatch(
                youtube_id
            ):
                raise StoryError(f"Event {index} YouTube ID is invalid")
            start_seconds = _bounded_int(
                video.get("start_seconds"),
                0,
                10_000_000,
                f"events[{index}].video.start_seconds",
            )
            end_seconds = _bounded_int(
                video.get("end_seconds"),
                1,
                10_001_200,
                f"events[{index}].video.end_seconds",
            )
            if (
                start_seconds is None
                or end_seconds is None
                or not start_seconds < end_seconds <= start_seconds + 1200
            ):
                raise StoryError(
                    f"Event {index} video range must be 1-1200 seconds"
                )

    expected = _with_revision({key: value for key, value in story.items() if key != "revision"})
    if expected["revision"] != revision:
        raise StoryError("Public story revision does not match its content")
    return story


def merge_stories(
    existing: dict[str, Any] | None,
    current: dict[str, Any],
) -> dict[str, Any]:
    validate_public_story(current)
    if existing is None:
        return current
    validate_public_story(existing)
    existing_ids = {event["id"] for event in existing["events"]}
    events = {
        event["id"]: event
        for event in current["events"]
    }
    events.update({event["id"]: event for event in existing["events"]})
    ordered = sorted(
        events.values(),
        key=lambda event: (event["observed_at"], event["sequence"]),
    )
    if len(ordered) > MAX_PUBLIC_EVENTS:
        protected_ids = {
            event["id"]
            for event in ordered
            if event["kind"] in {"badge", "completion"}
        }
        protected_ids.add(ordered[0]["id"])
        protected = [
            event
            for event in ordered
            if event["id"] in protected_ids
        ]
        remaining_slots = MAX_PUBLIC_EVENTS - len(protected)
        context = [
            event
            for event in ordered
            if event["id"] not in protected_ids
        ]
        recent_context = context[-remaining_slots:] if remaining_slots else []
        ordered = sorted(
            [*protected, *recent_context],
            key=lambda event: (event["observed_at"], event["sequence"]),
        )
    earliest_story = min(
        (existing, current),
        key=lambda story: story["coverage"]["first_observed_at"],
    )
    merged = _story_without_revision(
        ordered,
        incomplete_before=earliest_story["coverage"]["incomplete_before"],
        continuous_source=(
            existing["coverage"]["continuous_source"]
            and current["coverage"]["continuous_source"]
            and any(event["id"] in existing_ids for event in current["events"])
        ),
    )
    result = _with_revision(merged)
    validate_public_story(result)
    return result


def story_bytes(story: dict[str, Any]) -> bytes:
    validate_public_story(story)
    payload = (
        json.dumps(story, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_PUBLIC_STORY_BYTES:
        raise StoryError("Public story exceeds the one MiB publication limit")
    return payload


def load_theater_config(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.exists():
        return {"events": {}, "broadcasts": []}
    metadata = _regular_file(path, "theater configuration")
    if not 1 <= metadata.st_size <= MAX_THEATER_CONFIG_BYTES:
        raise StoryError("Theater configuration has an invalid size")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StoryError(f"Cannot read theater configuration: {error}") from error
    if (
        not isinstance(value, dict)
        or not {"schema_version", "events"} <= set(value)
        or set(value) - {"schema_version", "events", "broadcasts"}
        or value.get("schema_version") != 1
        or not isinstance(value.get("events"), dict)
        or len(value["events"]) > MAX_PUBLIC_EVENTS
    ):
        raise StoryError("Theater configuration has an invalid schema")
    result: dict[str, dict[str, Any]] = {}
    for event_id, video in value["events"].items():
        if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
            raise StoryError("Theater configuration has an invalid event ID")
        if not isinstance(video, dict) or set(video) != VIDEO_KEYS:
            raise StoryError(f"Theater video for {event_id} is invalid")
        youtube_id = video.get("youtube_id")
        start_seconds = video.get("start_seconds")
        end_seconds = video.get("end_seconds")
        if (
            not isinstance(youtube_id, str)
            or not YOUTUBE_ID_RE.fullmatch(youtube_id)
            or isinstance(start_seconds, bool)
            or not isinstance(start_seconds, int)
            or isinstance(end_seconds, bool)
            or not isinstance(end_seconds, int)
            or not 0 <= start_seconds < end_seconds <= start_seconds + 1200
            or end_seconds > 10_001_200
        ):
            raise StoryError(f"Theater video range for {event_id} is invalid")
        result[event_id] = {
            "youtube_id": youtube_id,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
        }
    broadcasts_value = value.get("broadcasts", [])
    if not isinstance(broadcasts_value, list) or len(broadcasts_value) > 16:
        raise StoryError("Theater broadcasts are invalid")
    broadcasts: list[dict[str, Any]] = []
    for index, broadcast in enumerate(broadcasts_value):
        if not isinstance(broadcast, dict) or set(broadcast) != BROADCAST_KEYS:
            raise StoryError(f"Theater broadcast {index} is invalid")
        youtube_id = broadcast.get("youtube_id")
        if not isinstance(youtube_id, str) or not YOUTUBE_ID_RE.fullmatch(
            youtube_id
        ):
            raise StoryError(f"Theater broadcast {index} YouTube ID is invalid")
        started_at, started = _timestamp(
            broadcast.get("started_at"),
            f"broadcasts[{index}].started_at",
        )
        ended_value = broadcast.get("ended_at")
        ended_at = None
        if ended_value is not None:
            ended_at, ended = _timestamp(
                ended_value,
                f"broadcasts[{index}].ended_at",
            )
            if ended <= started:
                raise StoryError(f"Theater broadcast {index} ends before it starts")
        broadcasts.append(
            {
                "youtube_id": youtube_id,
                "started_at": started_at,
                "ended_at": ended_at,
            }
        )
    broadcasts.sort(key=lambda item: item["started_at"])
    return {"events": result, "broadcasts": broadcasts}


def apply_theater_config(
    story: dict[str, Any],
    theater: dict[str, Any],
) -> dict[str, Any]:
    validate_public_story(story)
    videos = theater.get("events", {})
    broadcasts = theater.get("broadcasts", [])
    if not videos and not broadcasts:
        return story
    events = [dict(event) for event in story["events"]]
    by_id = {event["id"]: event for event in events}
    unknown = sorted(set(videos) - set(by_id))
    if unknown:
        raise StoryError(
            "Theater configuration references unknown story events: "
            + ", ".join(unknown[:5])
        )
    for event in events:
        selected_broadcast = None
        observed = datetime.fromisoformat(
            event["observed_at"].replace("Z", "+00:00")
        )
        for broadcast in broadcasts:
            started = datetime.fromisoformat(
                broadcast["started_at"].replace("Z", "+00:00")
            )
            ended = (
                datetime.fromisoformat(
                    broadcast["ended_at"].replace("Z", "+00:00")
                )
                if broadcast["ended_at"] is not None
                else None
            )
            if observed >= started and (ended is None or observed <= ended):
                selected_broadcast = (broadcast, started)
        if selected_broadcast is not None:
            broadcast, started = selected_broadcast
            offset = int((observed - started).total_seconds())
            event["video"] = {
                "youtube_id": broadcast["youtube_id"],
                "start_seconds": max(0, offset - 120),
                "end_seconds": offset + 30,
            }
    for event_id, video in videos.items():
        by_id[event_id]["video"] = dict(video)
    body = dict(story)
    body["events"] = events
    result = _with_revision(body)
    validate_public_story(result)
    return result


def write_private_story(
    story: dict[str, Any],
    output: Path,
) -> Path:
    payload = story_bytes(story)
    path = output.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)
    return path


class GitHubPublisher:
    def __init__(
        self,
        repository: str = DEFAULT_REPOSITORY,
        branch: str = DEFAULT_BRANCH,
    ):
        repository_parts = repository.split("/", 1)
        if (
            not REPOSITORY_RE.fullmatch(repository)
            or any(part in {".", ".."} for part in repository_parts)
        ):
            raise StoryError("Repository must be an owner/name pair")
        if not BRANCH_RE.fullmatch(branch):
            raise StoryError("Story branch name is invalid")
        if shutil.which("gh") is None:
            raise StoryError("GitHub CLI is required to publish the story")
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
            raise StoryError(f"GitHub API request failed: {detail}")
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise StoryError("GitHub API returned invalid JSON") from error
        if not isinstance(value, dict):
            raise StoryError("GitHub API returned an unexpected response")
        return value

    def ensure_branch(self) -> None:
        ref_path = quote(f"heads/{self.branch}", safe="/")
        existing = self._api(
            f"repos/{self.repository}/git/ref/{ref_path}",
            allow_not_found=True,
        )
        if existing is not None:
            return
        marker = self._api(
            f"repos/{self.repository}/git/blobs",
            method="POST",
            payload={
                "content": "RAPPter Plays Pokemon story archive\n",
                "encoding": "utf-8",
            },
        )
        marker_sha = marker.get("sha")
        if not isinstance(marker_sha, str) or not re.fullmatch(
            r"[0-9a-f]{40}",
            marker_sha,
        ):
            raise StoryError("GitHub did not create the story marker blob")
        tree = self._api(
            f"repos/{self.repository}/git/trees",
            method="POST",
            payload={
                "tree": [
                    {
                        "path": ".story-archive",
                        "mode": "100644",
                        "type": "blob",
                        "sha": marker_sha,
                    }
                ]
            },
        )
        tree_sha = tree.get("sha")
        if not isinstance(tree_sha, str) or not re.fullmatch(
            r"[0-9a-f]{40}",
            tree_sha,
        ):
            raise StoryError("GitHub did not create the story archive tree")
        commit = self._api(
            f"repos/{self.repository}/git/commits",
            method="POST",
            payload={
                "message": "data: initialize story archive",
                "tree": tree_sha,
                "parents": [],
            },
        )
        commit_sha = commit.get("sha")
        if not isinstance(commit_sha, str) or not re.fullmatch(
            r"[0-9a-f]{40}",
            commit_sha,
        ):
            raise StoryError("GitHub did not create the story archive commit")
        try:
            self._api(
                f"repos/{self.repository}/git/refs",
                method="POST",
                payload={
                    "ref": f"refs/heads/{self.branch}",
                    "sha": commit_sha,
                },
            )
        except StoryError:
            if self._api(
                f"repos/{self.repository}/git/ref/{ref_path}",
                allow_not_found=True,
            ) is None:
                raise

    def read_remote_story(
        self,
    ) -> tuple[dict[str, Any] | None, str | None, bool]:
        path = quote(REMOTE_STORY_PATH, safe="/")
        response = self._api(
            f"repos/{self.repository}/contents/{path}?ref={quote(self.branch)}",
            allow_not_found=True,
        )
        if response is None:
            return None, None, False
        if (
            response.get("type") != "file"
            or not isinstance(response.get("sha"), str)
            or response.get("encoding") != "base64"
            or not isinstance(response.get("content"), str)
        ):
            raise StoryError("Remote story response is invalid")
        try:
            encoded = "".join(response["content"].split())
            payload = base64.b64decode(encoded, validate=True)
            value = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StoryError("Remote story content is invalid") from error
        migrated_legacy = False
        if (
            isinstance(value, dict)
            and value.get("schema_version") == 1
            and isinstance(value.get("events"), list)
            and value["events"]
            and all(
                isinstance(event, dict)
                and set(event) == PUBLIC_EVENT_KEYS - {"video"}
                for event in value["events"]
            )
        ):
            migrated = dict(value)
            migrated["events"] = [
                {**event, "video": None}
                for event in value["events"]
            ]
            value = _with_revision(migrated)
            migrated_legacy = True
        validate_public_story(value)
        return value, response["sha"], migrated_legacy

    def publish(
        self,
        current: dict[str, Any],
        theater: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_branch()
        existing, existing_sha, migrated_legacy = self.read_remote_story()
        merged = merge_stories(existing, current)
        merged = apply_theater_config(
            merged,
            theater or {"events": {}, "broadcasts": []},
        )
        payload = story_bytes(merged)
        if (
            existing is not None
            and not migrated_legacy
            and story_bytes(existing) == payload
        ):
            return {
                "changed": False,
                "revision": merged["revision"],
                "raw_url": self.raw_url,
            }
        body: dict[str, Any] = {
            "message": (
                "data: update story through "
                f"{merged['events'][-1]['id']}"
            ),
            "content": base64.b64encode(payload).decode("ascii"),
            "branch": self.branch,
        }
        if existing_sha is not None:
            body["sha"] = existing_sha
        path = quote(REMOTE_STORY_PATH, safe="/")
        result = self._api(
            f"repos/{self.repository}/contents/{path}",
            method="PUT",
            payload=body,
        )
        commit = result.get("commit")
        if not isinstance(commit, dict) or not isinstance(commit.get("sha"), str):
            raise StoryError("GitHub did not confirm the story commit")
        return {
            "changed": True,
            "revision": merged["revision"],
            "commit": commit["sha"],
            "raw_url": self.raw_url,
        }

    @property
    def raw_url(self) -> str:
        return (
            "https://raw.githubusercontent.com/"
            f"{self.repository}/refs/heads/{self.branch}/{REMOTE_STORY_PATH}"
        )


def _locked_publish(
    runtime_dir: Path,
    editor_dir: Path,
    publisher: GitHubPublisher,
    theater_config: Path,
    extra_broadcast: dict[str, Any] | None,
) -> dict[str, Any]:
    editor_dir = editor_dir.expanduser().resolve()
    editor_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(editor_dir, 0o700)
    lock_path = editor_dir / "publisher.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        os.chmod(lock_path, 0o600)
        if fcntl is not None:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise StoryError("Another story publisher is already running") from error
        story = build_story(runtime_dir)
        write_private_story(story, editor_dir / "story.json")
        theater = load_theater_config(theater_config)
        if extra_broadcast is not None:
            theater["broadcasts"].append(extra_broadcast)
            theater["broadcasts"].sort(key=lambda item: item["started_at"])
        return publisher.publish(story, theater)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and publish the public RAPPter Plays Pokémon story"
    )
    parser.add_argument(
        "action",
        choices=("build", "publish", "watch"),
        nargs="?",
        default="build",
    )
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--editor-dir", type=Path, default=DEFAULT_EDITOR_DIR)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--theater-config", type=Path)
    parser.add_argument("--youtube-video-id")
    parser.add_argument("--youtube-started-at")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument(
        "--interval",
        type=int,
        default=600,
        help="watch interval in seconds (minimum 60)",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    output = args.output or args.editor_dir / "story.json"
    if args.action == "build":
        story = build_story(args.runtime_dir)
        path = write_private_story(story, output)
        return {
            "status": "success",
            "message": "Public-safe story built",
            "events": len(story["events"]),
            "revision": story["revision"],
            "output": str(path),
        }

    publisher = GitHubPublisher(args.repository, args.branch)
    theater_config = args.theater_config or args.editor_dir / "theater.json"
    if bool(args.youtube_video_id) != bool(args.youtube_started_at):
        raise StoryError(
            "--youtube-video-id and --youtube-started-at must be provided together"
        )
    extra_broadcast = None
    if args.youtube_video_id:
        if not YOUTUBE_ID_RE.fullmatch(args.youtube_video_id):
            raise StoryError("YouTube video ID is invalid")
        started_at, _ = _timestamp(
            args.youtube_started_at,
            "youtube_started_at",
        )
        extra_broadcast = {
            "youtube_id": args.youtube_video_id,
            "started_at": started_at,
            "ended_at": None,
        }
    if args.action == "publish":
        result = _locked_publish(
            args.runtime_dir,
            args.editor_dir,
            publisher,
            theater_config,
            extra_broadcast,
        )
        return {
            "status": "success",
            "message": (
                "Story published"
                if result["changed"]
                else "Story is already current"
            ),
            **result,
        }

    if args.interval < 60:
        raise StoryError("Watch interval must be at least 60 seconds")
    print(
        json.dumps(
            {
                "status": "running",
                "message": "Story publisher watch loop started",
                "interval": args.interval,
                "raw_url": publisher.raw_url,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    while True:
        try:
            result = _locked_publish(
                args.runtime_dir,
                args.editor_dir,
                publisher,
                theater_config,
                extra_broadcast,
            )
            print(
                json.dumps(
                    {
                        "status": "success",
                        "timestamp": datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        **result,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        except (OSError, StoryError) as error:
            print(
                json.dumps(
                    {
                        "status": "error",
                        "timestamp": datetime.now(timezone.utc)
                        .isoformat()
                        .replace("+00:00", "Z"),
                        "message": str(error),
                    },
                    sort_keys=True,
                ),
                file=sys.stderr,
                flush=True,
            )
        time.sleep(args.interval)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run(argv)
    except (OSError, StoryError) as error:
        result = {"status": "error", "message": str(error)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
