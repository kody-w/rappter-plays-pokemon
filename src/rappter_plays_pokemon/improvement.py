"""Observe gameplay evidence and issue bounded next-cycle directives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1
PUBLIC_SCHEMA = "rappter-pokemon-execution/1.0"
DEFAULT_RUNTIME_DIR = Path.home() / ".openrappter" / "pokemon-red"
DEFAULT_STATE_DIR = Path.home() / ".openrappter" / "pokemon-red-improvement"
DIRECTIVE_NAME = "improvement-directive.json"
STATE_NAME = "state.json"
DIAGNOSES_NAME = "diagnoses.jsonl"
MAX_JSON_BYTES = 64 * 1024
MAX_NAVIGATION_BYTES = 8 * 1024 * 1024
MAX_EVIDENCE_LINE_BYTES = 8192
MAX_RECENT_RECORDS = 512
VALID_BUTTONS = {"a", "b", "start", "select", "up", "down", "left", "right"}
VALID_PHASES = {"intro", "menu", "dialogue", "overworld", "battle", "other"}
VALID_SOURCES = {
    "model",
    "route_target",
    "solved_route",
    "frontier_coverage",
    "operator",
}
VALID_STUCK_REASONS = {
    "room_cycle",
    "floor_cycle",
    "repeated_edge",
    "endpoint_revisit",
    "low_novelty",
}
VALID_VERDICTS = {
    "collect_more_data",
    "progress",
    "stable",
    "instrumentation",
    "memory",
    "planning",
    "reliability",
}
VALID_STRATEGIES = {
    "observe",
    "normal",
    "preserve_graph",
    "probe_frontier",
    "escalate_research",
}
PRIVATE_EVIDENCE_KEYS = {
    "schema_version",
    "event_id",
    "event_type",
    "run_id",
    "sequence",
    "observed_at",
    "agent_sha256",
    "model",
    "reasoning_effort",
    "navigation_schema",
    "decision_id",
    "source",
    "action_mode",
    "buttons",
    "state",
    "expected_destination",
    "navigation_mode",
    "stuck_reasons",
    "tainted",
}
MODEL_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ImprovementError(RuntimeError):
    """Raised when improvement inputs fail their private contract."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    payload = json.dumps(value, indent=2, sort_keys=True).encode("utf-8")
    if len(payload) > MAX_JSON_BYTES:
        raise ImprovementError(f"{path.name} exceeds the private size limit")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    payload = _canonical(value) + b"\n"
    if len(payload) > MAX_EVIDENCE_LINE_BYTES:
        raise ImprovementError("Diagnosis exceeds the private journal limit")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
        0o600,
    )
    try:
        if os.write(descriptor, payload) != len(payload):
            raise ImprovementError("Diagnosis journal write was incomplete")
    finally:
        os.close(descriptor)
    os.chmod(path, 0o600)


def _regular_json(
    path: Path,
    *,
    required: bool = True,
    max_bytes: int = MAX_JSON_BYTES,
) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if not required:
            return {}
        raise ImprovementError(f"Missing private input: {path.name}") from None
    except OSError as error:
        raise ImprovementError(f"Cannot inspect {path.name}: {error}") from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ImprovementError(f"{path.name} must be a regular file")
    if not 1 <= metadata.st_size <= max_bytes:
        raise ImprovementError(f"{path.name} has an invalid size")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ImprovementError(f"Cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise ImprovementError(f"{path.name} must contain one object")
    return value


def _valid_private_record(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != PRIVATE_EVIDENCE_KEYS:
        return False
    state = value.get("state")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("event_type") != "execution"
        or not isinstance(value.get("event_id"), str)
        or not isinstance(value.get("run_id"), str)
        or not isinstance(value.get("sequence"), int)
        or value.get("sequence") < 1
        or not isinstance(value.get("observed_at"), str)
        or not isinstance(value.get("agent_sha256"), str)
        or not SHA256_RE.fullmatch(value["agent_sha256"])
        or not isinstance(value.get("model"), str)
        or not MODEL_RE.fullmatch(value["model"])
        or value.get("reasoning_effort") not in {"low", "medium", "high", "max"}
        or value.get("source") not in VALID_SOURCES
        or value.get("navigation_mode") not in {"normal", "puzzle"}
        or not isinstance(value.get("buttons"), list)
        or any(button not in VALID_BUTTONS for button in value["buttons"])
        or not isinstance(value.get("stuck_reasons"), list)
        or any(reason not in VALID_STUCK_REASONS for reason in value["stuck_reasons"])
        or not isinstance(value.get("tainted"), bool)
        or not isinstance(state, dict)
    ):
        return False
    return True


def load_evidence(
    runtime_dir: Path,
    *,
    limit: int = MAX_RECENT_RECORDS,
) -> list[dict[str, Any]]:
    evidence_dir = runtime_dir.expanduser().resolve() / "evidence"
    if not evidence_dir.exists():
        return []
    if evidence_dir.is_symlink() or not evidence_dir.is_dir():
        raise ImprovementError("Evidence input must be a private directory")
    records: deque[dict[str, Any]] = deque(maxlen=max(1, min(limit, 10000)))
    paths = sorted(
        evidence_dir.glob("events-*.jsonl"),
        key=lambda candidate: candidate.stat().st_mtime_ns,
    )
    for path in paths:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ImprovementError(f"Invalid evidence shard: {path.name}")
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if len(line.encode("utf-8")) > MAX_EVIDENCE_LINE_BYTES:
                    raise ImprovementError(f"Oversized evidence line: {path.name}")
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ImprovementError(
                        f"Invalid evidence JSON: {path.name}"
                    ) from error
                if not _valid_private_record(value):
                    raise ImprovementError(
                        f"Invalid evidence record: {path.name}"
                    )
                records.append(value)
    return list(records)


def _progress_marker(status: dict[str, Any]) -> dict[str, Any]:
    game = status.get("game_state")
    game = game if isinstance(game, dict) else {}
    badges = game.get("badges")
    badges = badges if isinstance(badges, list) else []
    keys = game.get("key_items")
    keys = keys if isinstance(keys, dict) else {}
    pokedex = game.get("pokedex")
    pokedex = pokedex if isinstance(pokedex, dict) else {}
    return {
        "badges": len(badges),
        "lift_key": keys.get("lift_key") is True,
        "silph_scope": keys.get("silph_scope") is True,
        "pokedex_caught": (
            pokedex.get("caught") if isinstance(pokedex.get("caught"), int) else None
        ),
        "hall_of_fame": game.get("hall_of_fame") is True,
    }


def _marker_advanced(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> bool:
    if not previous:
        return False
    for field in ("badges", "pokedex_caught"):
        before = previous.get(field)
        after = current.get(field)
        if isinstance(before, int) and isinstance(after, int) and after > before:
            return True
    return any(
        current.get(field) is True and previous.get(field) is not True
        for field in ("lift_key", "silph_scope", "hall_of_fame")
    )


def _navigation_counts(runtime_dir: Path) -> dict[str, int]:
    value = _regular_json(
        runtime_dir / "navigation-memory.json",
        required=False,
        max_bytes=MAX_NAVIGATION_BYTES,
    )
    return {
        "walk_edges": (
            len(value.get("walk_edges", []))
            if isinstance(value.get("walk_edges"), list)
            else 0
        ),
        "macro_edges": (
            len(value.get("macro_edges", []))
            if isinstance(value.get("macro_edges"), list)
            else 0
        ),
    }


def judge(
    runtime_dir: Path,
    state_dir: Path = DEFAULT_STATE_DIR,
    *,
    minimum_records: int = 20,
    stuck_budget: int = 100,
    directive_ttl_seconds: int = 900,
) -> dict[str, Any]:
    runtime_dir = runtime_dir.expanduser().resolve()
    state_dir = state_dir.expanduser().resolve()
    status = _regular_json(runtime_dir / "status.json")
    records = load_evidence(runtime_dir)
    previous_state = _regular_json(state_dir / STATE_NAME, required=False)
    previous_marker = previous_state.get("progress_marker")
    previous_marker = previous_marker if isinstance(previous_marker, dict) else {}
    marker = _progress_marker(status)
    advanced = _marker_advanced(previous_marker, marker)
    evidence_error = status.get("evidence_error")
    stuck_count = status.get("stuck_decision_count")
    stuck_count = stuck_count if isinstance(stuck_count, int) else 0
    recent = records[-100:]
    stuck_records = 0
    for record in reversed(records):
        if not record["stuck_reasons"]:
            break
        stuck_records += 1
    route_records = sum(
        record["source"] in {"route_target", "solved_route", "frontier_coverage"}
        for record in recent
    )
    navigation = _navigation_counts(runtime_dir)

    effective_stuck_count = max(stuck_count, stuck_records)
    if (
        status.get("running") is not True
        or status.get("lifecycle") != "ready"
        or status.get("last_error") not in (None, "")
    ):
        verdict, strategy = "reliability", "observe"
    elif evidence_error not in (None, ""):
        verdict, strategy = "instrumentation", "observe"
    elif advanced:
        verdict, strategy = "progress", "normal"
    elif len(records) < minimum_records:
        verdict, strategy = "collect_more_data", "observe"
    elif (
        status.get("stuck_state") is True
        and effective_stuck_count >= stuck_budget
    ):
        if navigation["walk_edges"] >= 3800 or navigation["macro_edges"] >= 240:
            verdict, strategy = "memory", "preserve_graph"
        elif (
            effective_stuck_count >= stuck_budget * 2
            and status.get("web_research_state") in {"ready", "searching"}
        ):
            verdict, strategy = "planning", "escalate_research"
        elif status.get("web_research_state") in {"ready", "searching"}:
            verdict, strategy = "planning", "probe_frontier"
        else:
            verdict, strategy = "planning", "escalate_research"
    else:
        verdict, strategy = "stable", "normal"

    evidence = {
        "execution_records": len(records),
        "recent_stuck_records": stuck_records,
        "recent_route_records": route_records,
        "stuck_decisions": effective_stuck_count,
        "walk_edges": navigation["walk_edges"],
        "macro_edges": navigation["macro_edges"],
        "progress_marker": marker,
    }
    now = datetime.now(timezone.utc)
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now.isoformat(),
        "expires_at": (
            now + timedelta(seconds=max(60, directive_ttl_seconds))
        ).isoformat(),
        "verdict": verdict,
        "strategy": strategy,
        "evidence": evidence,
        "applies_to_run": status.get("evidence_run_id"),
    }
    directive = {
        **unsigned,
        "directive_id": f"sha256:{hashlib.sha256(_canonical(unsigned)).hexdigest()}",
    }
    _atomic_json(runtime_dir / DIRECTIVE_NAME, directive)
    diagnosis_body = {
        "schema_version": SCHEMA_VERSION,
        "verdict": verdict,
        "strategy": strategy,
        "evidence": evidence,
    }
    diagnosis = {
        **diagnosis_body,
        "diagnosis_id": (
            "sha256:" + hashlib.sha256(_canonical(diagnosis_body)).hexdigest()
        ),
        "created_at": directive["created_at"],
    }
    prior_diagnosis = previous_state.get("diagnosis_id")
    if prior_diagnosis != diagnosis["diagnosis_id"]:
        _append_jsonl(state_dir / DIAGNOSES_NAME, diagnosis)
    _atomic_json(
        state_dir / STATE_NAME,
        {
            "schema_version": SCHEMA_VERSION,
            "updated_at": directive["created_at"],
            "diagnosis_id": diagnosis["diagnosis_id"],
            "progress_marker": marker,
            "verdict": verdict,
            "strategy": strategy,
            "execution_records": len(records),
        },
    )
    return directive


def _public_record(
    record: dict[str, Any],
    next_record: dict[str, Any] | None,
    previous_marker: tuple[Any, ...] | None,
) -> tuple[dict[str, Any] | None, tuple[Any, ...]]:
    state = record["state"]
    marker = (
        tuple(state.get("badges", [])),
        state.get("lift_key"),
        state.get("silph_scope"),
        state.get("pokedex_caught"),
        state.get("hall_of_fame"),
    )
    if record["tainted"] or record["source"] == "operator":
        return None, marker
    next_state = next_record["state"] if next_record is not None else {}
    if (
        state.get("map_id") is not None
        and next_state.get("map_id") is not None
        and state.get("map_id") != next_state.get("map_id")
    ):
        movement_result = "transition"
    elif (
        state.get("coordinates") is not None
        and next_state.get("coordinates") is not None
        and state.get("coordinates") != next_state.get("coordinates")
    ):
        movement_result = "moved"
    elif state.get("phase") != next_state.get("phase") and next_record is not None:
        movement_result = "phase_change"
    elif next_record is None:
        movement_result = "unknown"
    else:
        movement_result = "blocked_or_waited"
    payload = {
        "schema": PUBLIC_SCHEMA,
        "run_id": record["run_id"],
        "sequence": record["sequence"],
        "agent_sha256": record["agent_sha256"],
        "inference": {
            "provider": "github-copilot",
            "requested_model": record["model"],
            "reasoning_effort": record["reasoning_effort"],
            "tools_enabled": False,
        },
        "game_time_seconds": state.get("game_time_seconds"),
        "phase": (
            state.get("phase")
            if state.get("phase") in VALID_PHASES
            else "other"
        ),
        "progress": {
            "badge_count": len(state.get("badges", [])),
            "party_size": state.get("party_size"),
            "pokedex_seen": state.get("pokedex_seen"),
            "pokedex_caught": state.get("pokedex_caught"),
            "lift_key": state.get("lift_key"),
            "silph_scope": state.get("silph_scope"),
            "hall_of_fame": state.get("hall_of_fame") is True,
            "changed": previous_marker is not None and marker != previous_marker,
        },
        "action": {
            "source": record["source"],
            "buttons": record["buttons"],
            "mode": record["action_mode"],
        },
        "outcome": {
            "movement_result": movement_result,
            "stuck_reasons": record["stuck_reasons"],
        },
        "quality": {
            "runtime_observed": True,
            "training_eligible": True,
            "taint": "none",
        },
        "provenance": {
            "projection_version": SCHEMA_VERSION,
            "navigation_schema": record["navigation_schema"],
        },
    }
    record_id = hashlib.sha256(_canonical(payload)).hexdigest()
    return {"record_id": f"sha256:{record_id}", **payload}, marker


def public_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["run_id"]].append(record)
    output: list[dict[str, Any]] = []
    for run_id in sorted(grouped):
        run_records = sorted(grouped[run_id], key=lambda item: item["sequence"])
        previous_marker: tuple[Any, ...] | None = None
        for index, record in enumerate(run_records):
            next_record = (
                run_records[index + 1] if index + 1 < len(run_records) else None
            )
            public, previous_marker = _public_record(
                record,
                next_record,
                previous_marker,
            )
            if public is not None:
                output.append(public)
    return output


def export_public(runtime_dir: Path, output: Path) -> dict[str, Any]:
    records = public_records(load_evidence(runtime_dir, limit=10000))
    payload = b"".join(_canonical(record) + b"\n" for record in records)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.replace(temporary, output)
    os.chmod(output, 0o600)
    return {
        "status": "success",
        "records": len(records),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "output": str(output),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Judge and export the RAPPter Plays Pokemon improvement cycle"
    )
    parser.add_argument(
        "action",
        choices=("judge", "watch", "status", "export"),
    )
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--minimum-records", type=int, default=20)
    parser.add_argument("--stuck-budget", type=int, default=100)
    parser.add_argument("--directive-ttl", type=int, default=900)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--once", action="store_true")
    return parser


def run(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    runtime_dir = args.runtime_dir.expanduser().resolve()
    state_dir = args.state_dir.expanduser().resolve()
    if args.action == "status":
        return {
            "status": "success",
            "state": _regular_json(state_dir / STATE_NAME, required=False),
            "directive": _regular_json(
                runtime_dir / DIRECTIVE_NAME,
                required=False,
            ),
        }
    if args.action == "export":
        if args.output is None:
            raise ImprovementError("export requires --output")
        return export_public(runtime_dir, args.output)
    if args.action == "judge":
        return {
            "status": "success",
            "directive": judge(
                runtime_dir,
                state_dir,
                minimum_records=args.minimum_records,
                stuck_budget=args.stuck_budget,
                directive_ttl_seconds=args.directive_ttl,
            ),
        }

    interval = max(10, args.interval)
    cycles = 0
    latest: dict[str, Any] = {}
    while True:
        latest = judge(
            runtime_dir,
            state_dir,
            minimum_records=args.minimum_records,
            stuck_budget=args.stuck_budget,
            directive_ttl_seconds=args.directive_ttl,
        )
        cycles += 1
        if args.once:
            break
        time.sleep(interval)
    return {"status": "success", "cycles": cycles, "directive": latest}


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run(argv)
    except ImprovementError as error:
        result = {"status": "error", "message": str(error)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
