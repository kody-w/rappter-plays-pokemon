import json
from pathlib import Path

from rappter_plays_pokemon.improvement import (
    DIRECTIVE_NAME,
    PUBLIC_SCHEMA,
    export_public,
    judge,
    load_evidence,
    public_records,
)


def _write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _status(*, stuck=True, stuck_count=120, badges=None):
    return {
        "running": True,
        "lifecycle": "ready",
        "last_error": None,
        "evidence_error": None,
        "evidence_run_id": "run-a",
        "stuck_state": stuck,
        "stuck_decision_count": stuck_count,
        "web_research_state": "ready",
        "game_state": {
            "badges": badges or ["Boulder"],
            "key_items": {"lift_key": False, "silph_scope": False},
            "pokedex": {"caught": 5},
            "hall_of_fame": False,
        },
    }


def _record(sequence, *, coordinates, source="model", tainted=False):
    return {
        "schema_version": 1,
        "event_id": f"run-a:execution:{sequence:08d}",
        "event_type": "execution",
        "run_id": "run-a",
        "sequence": sequence,
        "observed_at": f"2026-07-24T01:{sequence:02d}:00+00:00",
        "agent_sha256": "a" * 64,
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
        "navigation_schema": 4,
        "decision_id": sequence,
        "source": source,
        "action_mode": "precision",
        "buttons": ["right"],
        "state": {
            "phase": "overworld",
            "location": "private location",
            "map_id": 201,
            "coordinates": {"x": coordinates[0], "y": coordinates[1]},
            "badges": ["Boulder"],
            "party_size": 3,
            "pokedex_seen": 62,
            "pokedex_caught": 5,
            "lift_key": False,
            "silph_scope": False,
            "hall_of_fame": False,
            "game_time_seconds": 500000 + sequence,
        },
        "expected_destination": None,
        "navigation_mode": "puzzle",
        "stuck_reasons": ["floor_cycle"],
        "tainted": tainted,
    }


def _evidence(runtime: Path, records):
    path = runtime / "evidence" / "events-run-a.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def test_judge_writes_typed_directive_and_deduplicates_diagnosis(tmp_path):
    runtime = tmp_path / "runtime"
    state_dir = tmp_path / "improvement"
    _write_json(runtime / "status.json", _status())
    _write_json(
        runtime / "navigation-memory.json",
        {"walk_edges": [{}] * 800, "macro_edges": [{}] * 40},
    )
    _evidence(
        runtime,
        [_record(index, coordinates=(index, 1)) for index in range(1, 21)],
    )

    first = judge(runtime, state_dir, minimum_records=20, stuck_budget=100)
    second = judge(runtime, state_dir, minimum_records=20, stuck_budget=100)

    assert first["verdict"] == "planning"
    assert first["strategy"] == "probe_frontier"
    assert set(first) == {
        "schema_version",
        "directive_id",
        "created_at",
        "expires_at",
        "verdict",
        "strategy",
        "evidence",
        "applies_to_run",
    }
    assert json.loads((runtime / DIRECTIVE_NAME).read_text()) == second
    diagnoses = (state_dir / "diagnoses.jsonl").read_text().splitlines()
    assert len(diagnoses) == 1
    assert (runtime / DIRECTIVE_NAME).stat().st_mode & 0o777 == 0o600


def test_public_projection_pairs_outcomes_and_excludes_tainted_records(tmp_path):
    records = [
        _record(1, coordinates=(1, 1)),
        _record(2, coordinates=(2, 1)),
        _record(3, coordinates=(2, 1), source="operator", tainted=True),
    ]
    projected = public_records(records)

    assert len(projected) == 2
    assert projected[0]["schema"] == PUBLIC_SCHEMA
    assert projected[0]["outcome"]["movement_result"] == "moved"
    assert projected[0]["quality"]["training_eligible"] is True
    serialized = json.dumps(projected)
    for forbidden in (
        "coordinates",
        "map_id",
        "location",
        "objective",
        "observation",
        "screen_text",
    ):
        assert forbidden not in serialized

    runtime = tmp_path / "runtime"
    _evidence(runtime, records)
    output = tmp_path / "out" / "execution.jsonl"
    result = export_public(runtime, output)
    assert result["records"] == 2
    assert output.stat().st_mode & 0o777 == 0o600
    assert len(load_evidence(runtime)) == 3


def test_judge_escalates_ready_research_after_second_stuck_budget(tmp_path):
    runtime = tmp_path / "runtime"
    state_dir = tmp_path / "improvement"
    _write_json(runtime / "status.json", _status(stuck_count=200))
    _write_json(
        runtime / "navigation-memory.json",
        {"walk_edges": [{}] * 800, "macro_edges": [{}] * 40},
    )
    _evidence(
        runtime,
        [_record(index, coordinates=(index, 1)) for index in range(1, 21)],
    )

    directive = judge(
        runtime,
        state_dir,
        minimum_records=20,
        stuck_budget=100,
    )

    assert directive["verdict"] == "planning"
    assert directive["strategy"] == "escalate_research"
