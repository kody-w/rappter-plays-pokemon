import asyncio
import errno
import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from types import ModuleType, SimpleNamespace

import openrappter.agents.pokemon_agent as pokemon_module
import pytest
from openrappter.agents.pokemon_agent import (
    GAME_SYSTEM_PROMPT,
    GOLD_SYSTEM_PROMPT,
    YELLOW_SYSTEM_PROMPT,
    ActionPlayer,
    ClipRecorder,
    CopilotBrain,
    GitCheckpointArchive,
    NavigationMemory,
    PokemonAgent,
    PokemonGoldMemoryReader,
    PokemonRunner,
    PokemonYellowMemoryReader,
    StartupConfigurationError,
    ViewerServer,
    acquire_runtime_lock,
    build_parser,
    celadon_route_guidance,
    collision_allows_direction,
    discover_pokemon_red_rom,
    discover_pokemon_rom,
    endgame_route_guidance,
    ensure_copilot_runtime,
    file_sha256,
    gold_route_guidance,
    is_cloud_placeholder,
    is_pokemon_gold_rom,
    is_pokemon_red_rom,
    is_pokemon_yellow_rom,
    item_gate_guidance,
    list_clips,
    navigation_position,
    normalize_brain_decision,
    normalize_web_research,
    overworld_action_buttons,
    parse_agent_action,
    pokemon_game_id,
    pokemon_tower_route_guidance,
    precision_route_buttons,
    public_runtime_status,
    read_improvement_directive,
    read_youtube_chat_advisory,
    rock_tunnel_route_guidance,
    rocket_hideout_route_guidance,
    runner_main,
    runtime_command,
    runtime_status,
    search_pokemon_web,
    seed_legacy_ram_provenance,
    silph_co_route_guidance,
    supervisor_main,
    terminate_isolated_process_group,
    trusted_cerulean_cave_flee_buttons,
    trusted_gold_bugsy_battle_buttons,
    trusted_gold_cianwood_buttons,
    trusted_gold_dance_theater_buttons,
    trusted_gold_goldenrod_buttons,
    trusted_gold_hidden_phone_buttons,
    trusted_gold_ilex_buttons,
    trusted_gold_lake_buttons,
    trusted_gold_lighthouse_buttons,
    trusted_gold_morty_buttons,
    trusted_gold_poison_recovery_buttons,
    trusted_gold_rock_smash_gift_buttons,
    trusted_gold_rocket_buttons,
    trusted_gold_route35_recovery_buttons,
    trusted_gold_route_action,
    trusted_gold_squirtbottle_buttons,
    trusted_gold_sudowoodo_buttons,
    trusted_mewtwo_capture_buttons,
    trusted_mewtwo_finalize_buttons,
    trusted_mewtwo_surf_buttons,
    trusted_story_route_action,
    wait_for_stopping_supervisor,
    wait_for_supervised_child,
)


def make_rom(path: Path, title: bytes = b"POKEMON RED") -> Path:
    data = bytearray(256 * 1024)
    data[0x134 : 0x134 + len(title)] = title
    path.write_bytes(data)
    return path


def test_agent_contract():
    agent = PokemonAgent()

    assert agent.name == "Pokemon"
    assert agent.metadata["name"] == "Pokemon"
    assert agent.metadata["parameters"]["type"] == "object"
    assert "checkpoint" in agent.metadata["parameters"]["properties"]["action"]["enum"]
    assert "rewind" in agent.metadata["parameters"]["properties"]["action"]["enum"]
    assert "manual" in agent.metadata["parameters"]["properties"]["action"]["enum"]
    assert "autonomy" in agent.metadata["parameters"]["properties"]["action"]["enum"]
    assert "state_repo" in agent.metadata["parameters"]["properties"]


def test_git_checkpoint_archive_preserves_worktree_and_round_trips_state(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(repository)],
        check=True,
    )
    dirty = repository / "dirty.txt"
    dirty.write_text("working tree remains untouched\n")
    before = subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
    ).stdout
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    agent_path = tmp_path / "pokemon_agent.py"
    agent_path.write_text("AGENT = 'test'\n")
    archive = GitCheckpointArchive(
        repository,
        runtime,
        game_id="gold",
        rom_sha256="a" * 64,
        agent_path=agent_path,
        run_id="run-1",
    )

    commits = []
    for sequence, payload in enumerate((b"state one", b"state two"), start=1):
        state_path = (
            runtime
            / f"state-20260815-12000{sequence}-00000{sequence}.state"
        )
        state_path.write_bytes(payload)
        manifest = {
            "schema_version": 1,
            "created_at": f"2026-08-15T12:00:0{sequence}+00:00",
            "kind": "manual",
            "rom_sha256": "a" * 64,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "game_state": {
                "location": "Goldenrod Gym",
                "map_id": 0x0B03,
                "coordinates": {"x": 8, "y": 4},
                "badges": ["Zephyr", "Hive"],
                "party": [
                    {
                        "species_id": 159,
                        "level": 25,
                        "hp": 68,
                        "max_hp": 73,
                    }
                ],
            },
        }
        commits.append(archive.publish(state_path, manifest)["commit"])

    after = subprocess.run(
        ["git", "-C", str(repository), "status", "--porcelain=v1"],
        check=True,
        capture_output=True,
    ).stdout
    assert after == before
    assert archive._ref_tip() == commits[-1]
    parent = subprocess.run(
        [
            "git",
            f"--git-dir={archive.git_dir}",
            "rev-parse",
            f"{commits[-1]}^",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert parent == commits[0]
    tree_names = subprocess.run(
        [
            "git",
            f"--git-dir={archive.git_dir}",
            "ls-tree",
            "--name-only",
            commits[-1],
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert tree_names == [
        "checkpoint.state",
        "manifest.json",
        "pokemon_agent.py",
    ]

    resolved, manifest, state_bytes = archive.load(commits[-1][:12])

    assert resolved == commits[-1]
    assert state_bytes == b"state two"
    assert manifest["rom_sha256"] == "a" * 64
    assert manifest["state_sha256"] == hashlib.sha256(b"state two").hexdigest()
    assert str(repository) not in json.dumps(manifest)
    assert "working tree remains untouched" not in json.dumps(manifest)


def test_git_checkpoint_backfill_orders_mixed_filenames_by_manifest_time(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
    runtime = tmp_path / "runtime"
    states = runtime / "states"
    states.mkdir(parents=True)
    agent_path = tmp_path / "pokemon_agent.py"
    agent_path.write_text("AGENT = 'test'\n")
    archive = GitCheckpointArchive(
        repository,
        runtime,
        game_id="gold",
        rom_sha256="b" * 64,
        agent_path=agent_path,
        run_id="run-2",
    )
    entries = [
        (
            "state-20260815-150000-000001.state",
            "2026-08-15T12:00:00+00:00",
            b"older",
        ),
        (
            "state-20260815-120000-000001.state",
            "2026-08-15T13:00:00+00:00",
            b"newer",
        ),
    ]
    for name, created_at, payload in entries:
        state = states / name
        state.write_bytes(payload)
        state.with_suffix(".json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "created_at": created_at,
                    "kind": "manual",
                    "rom_sha256": "b" * 64,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                    "game_state": {},
                }
            )
        )
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.states_dir = states
    runner.git_checkpoint_archive = archive
    runner.status = {
        "rom_sha256": "b" * 64,
        "last_checkpoint": {"path": str(states / entries[-1][0])},
    }

    runner._publish_pending_git_checkpoints()
    _, manifest, payload = archive.load(archive._ref_tip())

    assert manifest["checkpoint_id"] == Path(entries[-1][0]).stem
    assert payload == b"newer"
    assert runner.status["last_checkpoint"]["git_commit"] == archive._ref_tip()


def test_execution_evidence_is_bounded_private_and_free_of_model_prose(tmp_path):
    state = {
        "phase": "overworld",
        "location": "Rocket Hideout B3F",
        "map_id": 0xC9,
        "coordinates": {"x": 18, "y": 15},
        "badges": ["Boulder"],
        "party_count": 3,
        "pokedex": {"seen": 62, "caught": 5},
        "key_items": {"lift_key": False, "silph_scope": False},
        "play_time": {"hours": 143, "minutes": 0, "seconds": 1},
    }
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.evidence_path = tmp_path / "evidence" / "events-test.jsonl"
    runner.evidence_sequence = 0
    runner.run_id = "test-run"
    runner.agent_sha256 = "a" * 64
    runner.args = SimpleNamespace(model="gpt-5.6-sol")
    runner.reasoning_effort = "medium"
    runner.navigation_mode = "puzzle"
    runner.status = {
        "stuck_reasons": ["floor_cycle"],
        "evidence_events": 0,
        "evidence_error": None,
    }

    runner._record_execution_evidence(
        source="model",
        buttons=["down"],
        game_state=state,
        decision_id=7,
        action_mode="precision",
    )

    evidence_file = runner.evidence_path
    assert evidence_file.stat().st_mode & 0o777 == 0o600
    record = json.loads(evidence_file.read_text())
    assert record["event_id"] == "test-run:execution:00000001"
    assert record["buttons"] == ["down"]
    assert record["state"]["coordinates"] == {"x": 18, "y": 15}
    assert record["state"]["game_time_seconds"] == 514801
    assert record["state"]["lift_key"] is False

    def keys(value):
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value))
        return set()

    evidence_keys = keys(record)
    for forbidden in ("objective", "observation", "reason", "screen_text"):
        assert forbidden not in evidence_keys

    runner._record_execution_evidence(
        source="trusted_gold_ilex",
        buttons=["up", "a"],
        game_state=state,
    )
    records = [
        json.loads(line)
        for line in evidence_file.read_text().splitlines()
    ]
    assert records[-1]["source"] == "trusted_gold_ilex"
    runner._record_execution_evidence(
        source="trusted_gold_goldenrod",
        buttons=["up", "a"],
        game_state=state,
    )
    records = [
        json.loads(line)
        for line in evidence_file.read_text().splitlines()
    ]
    assert records[-1]["source"] == "trusted_gold_goldenrod"


def test_improvement_directive_is_run_bound_expiring_and_enum_only(tmp_path):
    path = tmp_path / "improvement-directive.json"
    now = datetime.now(timezone.utc)
    value = {
        "schema_version": 1,
        "directive_id": "sha256:" + "a" * 64,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=10)).isoformat(),
        "verdict": "planning",
        "strategy": "probe_frontier",
        "evidence": {
            "execution_records": 100,
            "recent_stuck_records": 80,
            "recent_route_records": 10,
            "stuck_decisions": 120,
            "walk_edges": 900,
            "macro_edges": 60,
            "progress_marker": {
                "badges": 4,
                "lift_key": False,
                "silph_scope": False,
                "pokedex_caught": 5,
                "hall_of_fame": False,
                "stage": None,
            },
        },
        "applies_to_run": "run-a",
    }
    path.write_text(json.dumps(value))
    path.chmod(0o600)

    directive = read_improvement_directive(
        tmp_path,
        run_id="run-a",
        now=now,
    )
    assert directive["strategy"] == "probe_frontier"
    assert directive["evidence"]["walk_edges"] == 900
    assert read_improvement_directive(tmp_path, run_id="run-b", now=now) is None
    assert (
        read_improvement_directive(
            tmp_path,
            run_id="run-a",
            now=now + timedelta(minutes=11),
        )
        is None
    )


def test_rom_validation_uses_header(tmp_path):
    rom = make_rom(tmp_path / "renamed.gb")

    assert not is_cloud_placeholder(rom)
    assert is_pokemon_red_rom(rom)
    assert discover_pokemon_red_rom(str(rom)) == rom.resolve()


def test_rom_validation_rejects_other_game(tmp_path):
    rom = make_rom(tmp_path / "Pokemon Red.gb", b"OTHER GAME")

    assert not is_pokemon_red_rom(rom)
    with pytest.raises(FileNotFoundError):
        discover_pokemon_red_rom(str(rom))


def test_gold_rom_validation_uses_generation_two_header(tmp_path):
    rom = make_rom(tmp_path / "Pokemon Gold.gbc", b"POKEMON_GLDAAUE")

    assert is_pokemon_gold_rom(rom)
    assert not is_pokemon_red_rom(rom)
    assert pokemon_game_id(rom) == "gold"
    assert discover_pokemon_rom(str(rom)) == rom.resolve()
    assert "sixteen badges" in GOLD_SYSTEM_PROMPT
    assert "defeat Red" in GOLD_SYSTEM_PROMPT


def test_yellow_rom_validation_uses_cgb_truncated_header(tmp_path):
    rom = make_rom(tmp_path / "Pokemon Yellow.gbc", b"POKEMON YELLOW")
    data = bytearray(rom.read_bytes())
    data[0x143] = 0x80
    rom.write_bytes(data)

    assert is_pokemon_yellow_rom(rom)
    assert not is_pokemon_red_rom(rom)
    assert not is_pokemon_gold_rom(rom)
    assert pokemon_game_id(rom) == "yellow"
    assert discover_pokemon_rom(str(rom)) == rom.resolve()
    assert "starts with Pikachu" in YELLOW_SYSTEM_PROMPT
    assert "Hall of Fame" in YELLOW_SYSTEM_PROMPT
    assert PokemonYellowMemoryReader.GAME_ID == "yellow"


def test_gold_memory_reader_does_not_expose_red_wram_as_facts():
    memory = bytearray([0xFF]) * 65536

    snapshot = PokemonGoldMemoryReader(memory).snapshot()

    assert snapshot["game_id"] == "gold"
    assert snapshot["map_id"] is None
    assert snapshot["coordinates"] == {"x": None, "y": None}
    assert snapshot["badges"] == []
    assert snapshot["party"] == []
    assert snapshot["hall_of_fame_completed"] is False
    assert snapshot["red_defeated"] is False
    assert trusted_story_route_action(snapshot) is None
    assert navigation_position({
        "map_id": 0x1803,
        "coordinates": {"x": 14, "y": 15},
    }) == (0x1803, 14, 15)
    assert navigation_position({
        "map_id": 0x10000,
        "coordinates": {"x": 14, "y": 15},
    }) is None
    memory[0xD15F] = 1
    noisy_reader = PokemonGoldMemoryReader(memory)
    noisy_reader._decode_screen_text = lambda start, end: "99889899" * 8
    assert noisy_reader._screen_text_gold() == ""
    assert "downstairs warp is (7,0)" in gold_route_guidance({
        **snapshot,
        "map_group": 0x18,
        "map_number": 0x07,
        "coordinates": {"x": 1, "y": 4},
    })
    assert "middle Poke Ball is at (7,3)" in gold_route_guidance({
        **snapshot,
        "map_group": 0x18,
        "map_number": 0x05,
        "coordinates": {"x": 5, "y": 5},
        "party_count": 0,
    })
    assert "WEST to Cherrygrove" in gold_route_guidance({
        **snapshot,
        "map_group": 0x18,
        "map_number": 0x03,
        "coordinates": {"x": 40, "y": 8},
        "party_count": 1,
        "key_items": {"mystery_egg": False},
    })
    assert "EAST to New Bark" in gold_route_guidance({
        **snapshot,
        "map_group": 0x18,
        "map_number": 0x03,
        "coordinates": {"x": 20, "y": 8},
        "party_count": 1,
        "story_events": {
            "got_mystery_egg": True,
            "gave_mystery_egg_to_elm": False,
        },
    })
    assert "Route 31 branch to Violet" in gold_route_guidance({
        **snapshot,
        "map_group": 0x1A,
        "map_number": 0x03,
        "coordinates": {"x": 20, "y": 8},
        "party_count": 1,
        "story_events": {
            "got_mystery_egg": True,
            "gave_mystery_egg_to_elm": True,
        },
    })
    assert "Sprout Tower at (23,5)" in gold_route_guidance({
        **snapshot,
        "map_group": 0x0A,
        "map_number": 0x05,
        "coordinates": {"x": 39, "y": 25},
        "story_events": {"got_hm_flash": False},
        "badges": [],
    })
    assert "Violet Gym at (18,17)" in gold_route_guidance({
        **snapshot,
        "map_group": 0x0A,
        "map_number": 0x05,
        "coordinates": {"x": 23, "y": 6},
        "story_events": {"got_hm_flash": True},
        "badges": [],
    })
    assert "Falkner at (5,1)" in gold_route_guidance({
        **snapshot,
        "map_group": 0x0A,
        "map_number": 0x07,
        "coordinates": {"x": 5, "y": 10},
        "badges": [],
        "story_events": {"beat_bird_keeper_rod": True},
    })
    assert "Bird Keeper Rod's left-facing" in gold_route_guidance({
        **snapshot,
        "map_group": 0x0A,
        "map_number": 0x07,
        "coordinates": {"x": 5, "y": 8},
        "badges": [],
        "story_events": {"beat_bird_keeper_rod": False},
    })
    assert "Union Cave at (6,79)" in gold_route_guidance({
        **snapshot,
        "map_group": 0x0A,
        "map_number": 0x01,
        "coordinates": {"x": 8, "y": 1},
    })
    assert "south exit (17,31)" in gold_route_guidance({
        **snapshot,
        "map_group": 0x03,
        "map_number": 0x1D,
        "coordinates": {"x": 17, "y": 3},
    })
    assert "Kurt's House at (9,5)" in gold_route_guidance({
        **snapshot,
        "map_group": 0x08,
        "map_number": 0x07,
        "coordinates": {"x": 39, "y": 9},
        "badges": ["Zephyr"],
        "story_events": {"cleared_slowpoke_well": False},
    })
    assert "Parlyz Heal item ball at (16,7)" in gold_route_guidance({
        **snapshot,
        "map_group": 0x03,
        "map_number": 0x01,
        "coordinates": {"x": 17, "y": 7},
        "story_events": {
            "sprout_1f_parlyz_heal_collected": False,
        },
    })
    assert "(6,4), which enters 2F's first component" in gold_route_guidance({
        **snapshot,
        "map_group": 0x03,
        "map_number": 0x01,
        "coordinates": {"x": 5, "y": 6},
        "story_events": {
            "sprout_1f_parlyz_heal_collected": True,
        },
    })
    assert "Stop opening the Pack" in gold_route_guidance({
        **snapshot,
        "map_group": 0x03,
        "map_number": 0x02,
        "coordinates": {"x": 17, "y": 3},
        "party": [{"hp": 3, "max_hp": 35}],
        "story_events": {"got_hm_flash": False},
    })
    assert trusted_gold_route_action({
        **snapshot,
        "map_group": 0x03,
        "map_number": 0x02,
        "coordinates": {"x": 7, "y": 3},
        "screen_text": "",
        "story_events": {},
        "party": [{"hp": 3, "max_hp": 35}],
    }) == "left"
    bugsy_battle = {
        **snapshot,
        "map_group": 0x08,
        "map_number": 0x05,
        "in_battle": True,
        "badges": ["Zephyr"],
        "screen_text": "SCYTHER | FIGHT | PACK RUN",
    }
    assert trusted_gold_bugsy_battle_buttons(bugsy_battle) == [
        "up",
        "left",
        "a",
    ]
    assert trusted_gold_bugsy_battle_buttons({
        **bugsy_battle,
        "screen_text": "SCRATCH | LEER | BITE | WATER GUN",
        "menu_cursor_y": 3,
    }) == ["down"]
    assert trusted_gold_bugsy_battle_buttons({
        **bugsy_battle,
        "screen_text": "SCRATCH | LEER | BITE | WATER GUN",
        "menu_cursor_y": 4,
    }) == ["a"]
    post_bugsy = {
        **snapshot,
        "map_group": 0x08,
        "map_number": 0x05,
        "screen_text": "",
        "badges": ["Zephyr", "Hive"],
        "story_events": {"beat_bug_catcher_benny": True},
        "party": [{"hp": 1, "max_hp": 65}],
    }
    assert "do not approach Bugsy again" in gold_route_guidance({
        **post_bugsy,
        "coordinates": {"x": 6, "y": 7},
    })
    assert trusted_gold_route_action({
        **post_bugsy,
        "coordinates": {"x": 2, "y": 7},
    }) == "up"
    assert trusted_gold_route_action({
        **post_bugsy,
        "coordinates": {"x": 3, "y": 6},
    }) == "up"
    assert trusted_gold_route_action({
        **post_bugsy,
        "coordinates": {"x": 0, "y": 9},
    }) == "down"
    assert trusted_gold_route_action({
        **post_bugsy,
        "coordinates": {"x": 4, "y": 15},
    }) == "down"
    assert trusted_gold_route_action({
        **snapshot,
        "map_group": 0x0A,
        "map_number": 0x05,
        "coordinates": {"x": 28, "y": 28},
        "screen_text": "",
        "badges": ["Zephyr"],
        "story_events": {"got_hm_flash": True},
        "party": [{"hp": 42, "max_hp": 42}],
    }) == "left"
    assert trusted_gold_route_action({
        **snapshot,
        "map_group": 0x0A,
        "map_number": 0x05,
        "coordinates": {"x": 23, "y": 6},
        "screen_text": "",
        "story_events": {"got_hm_flash": False},
        "party": [{"hp": 3, "max_hp": 35}],
    }) is None
    assert trusted_gold_route_action({
        **snapshot,
        "map_group": 0x03,
        "map_number": 0x01,
        "coordinates": {"x": 16, "y": 1},
        "screen_text": "",
        "story_events": {"beat_sage_chow": True},
        "party": [{"hp": 35, "max_hp": 35}],
    }) == "left"
    assert trusted_gold_route_action({
        **snapshot,
        "map_group": 0x03,
        "map_number": 0x02,
        "coordinates": {"x": 5, "y": 5},
        "screen_text": "",
        "story_events": {"beat_sage_chow": True},
        "party": [{"hp": 35, "max_hp": 35}],
    }) == "up"
    assert trusted_gold_route_action({
        **snapshot,
        "map_group": 0x03,
        "map_number": 0x01,
        "coordinates": {"x": 17, "y": 3},
        "screen_text": "",
        "story_events": {"beat_sage_chow": True},
        "party": [{"hp": 35, "max_hp": 35}],
    }) == "up"
    assert trusted_gold_route_action({
        **snapshot,
        "map_group": 0x03,
        "map_number": 0x01,
        "coordinates": {"x": 3, "y": 6},
        "screen_text": "",
        "story_events": {"beat_sage_chow": True},
        "party": [{"hp": 35, "max_hp": 35}],
    }) == "left"
    route29_state = {
        **snapshot,
        "map_group": 0x18,
        "map_number": 0x03,
        "coordinates": {"x": 20, "y": 15},
        "screen_text": "",
        "story_events": {
            "got_mystery_egg": False,
            "gave_mystery_egg_to_elm": False,
        },
    }
    assert trusted_gold_route_action(route29_state) == "up"
    assert trusted_gold_route_action({
        **route29_state,
        "coordinates": {"x": 14, "y": 15},
    }) == "right"
    assert trusted_gold_route_action({
        **route29_state,
        "coordinates": {"x": 24, "y": 11},
    }) == "right"
    assert trusted_gold_route_action({
        **route29_state,
        "coordinates": {"x": 31, "y": 14},
    }) == "up"
    assert trusted_gold_route_action({
        **route29_state,
        "map_group": 0x1A,
        "map_number": 0x02,
        "coordinates": {"x": 25, "y": 11},
        "story_events": {
            "got_mystery_egg": True,
            "gave_mystery_egg_to_elm": True,
        },
    }) == "down"
    assert trusted_gold_route_action({
        **route29_state,
        "map_group": 0x1A,
        "map_number": 0x0B,
        "coordinates": {"x": 9, "y": 5},
        "story_events": {
            "got_mystery_egg": True,
            "gave_mystery_egg_to_elm": True,
        },
    }) == "left"
    assert trusted_gold_route_action({
        **route29_state,
        "map_group": 0x0A,
        "map_number": 0x05,
        "coordinates": {"x": 27, "y": 28},
        "story_events": {"got_hm_flash": False},
    }) == "right"
    assert trusted_gold_route_action({
        **route29_state,
        "map_group": 0x0A,
        "map_number": 0x05,
        "coordinates": {"x": 23, "y": 6},
        "story_events": {"got_hm_flash": False},
    }) == "up"
    assert trusted_gold_route_action({
        **route29_state,
        "coordinates": {"x": 22, "y": 6},
    }) == "up"
    assert trusted_gold_route_action({
        **route29_state,
        "coordinates": {"x": 17, "y": 4},
    }) == "down"
    assert trusted_gold_route_action({
        **route29_state,
        "coordinates": {"x": 21, "y": 15},
        "story_events": {
            "got_mystery_egg": True,
            "gave_mystery_egg_to_elm": False,
        },
    }) == "up"
    assert trusted_gold_route_action({
        **route29_state,
        "coordinates": {"x": 40, "y": 9},
        "story_events": {
            "got_mystery_egg": True,
            "gave_mystery_egg_to_elm": False,
        },
    }) == "right"
    assert trusted_gold_route_action({
        **route29_state,
        "map_group": 0x1A,
        "map_number": 0x01,
        "coordinates": {"x": 4, "y": 31},
        "story_events": {
            "got_mystery_egg": True,
            "gave_mystery_egg_to_elm": True,
        },
    }) == "right"
    assert trusted_gold_route_action({
        **route29_state,
        "map_group": 0x1A,
        "map_number": 0x01,
        "coordinates": {"x": 2, "y": 24},
        "story_events": {
            "got_mystery_egg": True,
            "gave_mystery_egg_to_elm": True,
        },
    }) == "up"


def test_gold_reader_decodes_lower_tilemap_rows_for_bugsy_battle():
    memory = bytearray(65536)
    memory[0xDA00] = 0x08
    memory[0xDA01] = 0x05
    memory[0xDA02] = 7
    memory[0xDA03] = 5
    memory[0xD116] = 1
    memory[0xD57C] = 1
    cursor = 0xC580
    for line in ("FIGHT", "PACK RUN"):
        for character in line:
            memory[cursor] = (
                0x7F
                if character == " "
                else 0x80 + ord(character) - ord("A")
            )
            cursor += 1
        memory[cursor] = 0x4E
        cursor += 1

    snapshot = PokemonGoldMemoryReader(memory).snapshot()

    assert snapshot["screen_text"] == "FIGHT | PACK RUN"
    assert trusted_gold_bugsy_battle_buttons(snapshot) == [
        "up",
        "left",
        "a",
    ]


def test_gold_underground_route_reaches_and_unlocks_basement_door():
    base = {
        "game_id": "gold",
        "map_id": 0x032E,
        "map_group": 0x03,
        "map_number": 0x2E,
        "coordinates": {"x": 20, "y": 28},
        "screen_text": "",
        "story_events": {
            "cleared_radio_tower": False,
            "used_basement_key": False,
            "beat_rival_underground": False,
        },
        "key_items": {
            "basement_key": True,
            "card_key": False,
        },
        "party": [{"hp": 154, "max_hp": 154}],
    }

    assert trusted_gold_route_action(base) == "up"
    assert trusted_gold_route_action({
        **base,
        "coordinates": {"x": 20, "y": 25},
    }) == "right"

    regular = {
        **base,
        "map_number": 0x2D,
        "coordinates": {"x": 3, "y": 2},
    }
    assert trusted_gold_route_action(regular) == "down"
    assert trusted_gold_route_action({
        **regular,
        "coordinates": {"x": 3, "y": 10},
    }) == "up"
    assert trusted_gold_route_action({
        **regular,
        "coordinates": {"x": 6, "y": 7},
    }) == "right"
    assert trusted_gold_route_action({
        **regular,
        "coordinates": {"x": 18, "y": 7},
        "facing_direction": 0,
    }) == "up"
    assert trusted_gold_route_action({
        **regular,
        "coordinates": {"x": 18, "y": 7},
        "facing_direction": 4,
    }) == "a"
    assert "door at (18,6)" in gold_route_guidance(regular)

    replaced = []
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.status = {"phase": "overworld"}
    runner.player = SimpleNamespace(replace=replaced.append)
    runner.navigation_memory = SimpleNamespace(
        finish=lambda *_args, **_kwargs: None,
        begin=lambda *_args, **_kwargs: None,
    )
    runner.committed_route = None
    runner.settle_candidate = None
    runner.settle_samples = 0
    runner.position_settled = True
    runner.last_decision_finished = 0.0
    runner._record_execution_evidence = lambda **_kwargs: None

    assert runner._advance_trusted_story_route({
        **regular,
        "map_id": 0x032D,
        "coordinates": {"x": 18, "y": 7},
        "facing_direction": 4,
        "in_battle": False,
    })
    assert replaced == [["a"]]

    used_key = {
        **base,
        "map_number": 0x2D,
        "coordinates": {"x": 22, "y": 31},
        "story_events": {
            **base["story_events"],
            "used_basement_key": True,
        },
    }
    assert trusted_gold_route_action(used_key) == "up"
    assert trusted_gold_route_action({
        **used_key,
        "map_number": 0x2E,
        "coordinates": {"x": 23, "y": 5},
    }) == "left"


def test_gold_memory_reader_tracks_cianwood_boulder_state():
    memory = bytearray(65536)
    memory[0xDA00] = 0x16
    memory[0xDA01] = 0x05
    memory[0xDA02] = 9
    memory[0xDA03] = 4
    memory[0xD5E2] = 0xFF
    memory[0xD93F] = 0x01
    for event_id in range(0x0709, 0x070D):
        memory[0xD7B7 + event_id // 8] |= 1 << (event_id % 8)
    for slot, (x, y) in enumerate(((3, 6), (4, 7), (5, 7)), start=4):
        base = 0xD1FD + slot * 0x28
        memory[base] = 90
        memory[base + 0x06] = 0x40
        memory[base + 0x10] = x + 4
        memory[base + 0x11] = y + 4

    snapshot = PokemonGoldMemoryReader(memory).snapshot()

    assert snapshot["strength_active"] is True
    assert snapshot["ice_path_boulders_dropped"] == {
        "one": True,
        "two": True,
        "three": True,
        "four": True,
    }
    assert snapshot["cianwood_gym_boulders"] == [
        {"x": 3, "y": 6},
        {"x": 4, "y": 7},
        {"x": 5, "y": 7},
    ]
    memory[0xDA00] = 0x03
    memory[0xDA01] = 0x2A
    grunt = 0xD445 + 13 * 0x10
    memory[grunt + 2] = 5
    memory[grunt + 3] = 8

    assert PokemonGoldMemoryReader(memory).snapshot()[
        "rocket_grunt18_blocking"
    ] is True


def test_gold_farfetchd_position_and_verified_route():
    memory = bytearray(65536)
    memory[0xDA00] = 0x03
    memory[0xDA01] = 0x2C
    memory[0xDA02] = 23
    memory[0xDA03] = 20
    for event_id in range(0x06E9, 0x06F3):
        memory[0xD7B7 + event_id // 8] |= 1 << (event_id % 8)
    memory[0xD7B7 + 0x06EB // 8] &= ~(1 << (0x06EB % 8))

    snapshot = PokemonGoldMemoryReader(memory).snapshot()

    assert snapshot["story_events"]["farfetchd_position"] == 3
    assert "face DOWN" in gold_route_guidance(snapshot)
    assert trusted_gold_route_action({
        **snapshot,
        "coordinates": {"x": 15, "y": 24},
        "screen_text": "",
    }) == "up"
    assert trusted_gold_route_action({
        **snapshot,
        "coordinates": {"x": 19, "y": 23},
        "screen_text": "",
    }) == "right"
    assert trusted_gold_ilex_buttons({
        **snapshot,
        "coordinates": {"x": 20, "y": 23},
        "screen_text": "",
        "in_battle": False,
    }) == ["down", "a"]
    assert trusted_gold_ilex_buttons({
        **snapshot,
        "screen_text": "KWA!",
        "in_battle": False,
    }) == ["a"]
    assert trusted_gold_ilex_buttons({
        **snapshot,
        "screen_text": "ODDISH | FIGHT | PACK RUN",
        "in_battle": True,
    }) is None


def test_gold_farfetchd_handoff_routes_to_hm_cut():
    state = {
        "game_id": "gold",
        "map_id": 0x032C,
        "map_group": 0x03,
        "map_number": 0x2C,
        "coordinates": {"x": 11, "y": 35},
        "screen_text": "",
        "in_battle": False,
        "party": [{"hp": 1, "max_hp": 68}],
        "story_events": {
            "farfetchd_position": 10,
            "herded_farfetchd": True,
            "got_hm_cut": False,
        },
    }

    assert "keep pressing A" in gold_route_guidance(state)
    assert trusted_gold_route_action(state) == "up"
    assert trusted_gold_route_action({
        **state,
        "coordinates": {"x": 8, "y": 31},
    }) == "up"
    assert trusted_gold_route_action({
        **state,
        "coordinates": {"x": 6, "y": 29},
    }) == "left"
    assert trusted_gold_ilex_buttons({
        **state,
        "coordinates": {"x": 5, "y": 29},
    }) == ["up", "a"]
    assert trusted_gold_ilex_buttons({
        **state,
        "screen_text": "received HM01",
    }) == ["a"]

    cut_state = {
        **state,
        "coordinates": {"x": 5, "y": 29},
        "story_events": {
            **state["story_events"],
            "farfetchd_position": None,
            "got_hm_cut": True,
        },
    }
    assert "tree at (8,25)" in gold_route_guidance(cut_state)
    assert trusted_gold_route_action(cut_state) == "right"
    assert trusted_gold_route_action({
        **cut_state,
        "coordinates": {"x": 8, "y": 28},
    }) == "up"
    assert trusted_gold_ilex_buttons({
        **cut_state,
        "coordinates": {"x": 8, "y": 26},
    }) == ["up", "a"]
    assert trusted_gold_ilex_buttons({
        **cut_state,
        "coordinates": {"x": 8, "y": 26},
        "screen_text": "This tree can be CUT!",
    }) == ["a"]
    assert trusted_gold_route_action({
        **cut_state,
        "coordinates": {"x": 8, "y": 25},
    }) == "up"
    assert trusted_gold_route_action({
        **cut_state,
        "coordinates": {"x": 8, "y": 23},
    }) == "down"
    assert trusted_gold_route_action({
        **cut_state,
        "coordinates": {"x": 7, "y": 22},
    }) == "down"
    assert trusted_gold_route_action({
        **cut_state,
        "coordinates": {"x": 1, "y": 6},
    }) == "up"


def test_gold_goldenrod_required_route_and_whitney_handoff():
    base = {
        "game_id": "gold",
        "map_id": 0x0B03,
        "map_group": 0x0B,
        "map_number": 0x03,
        "coordinates": {"x": 0, "y": 5},
        "screen_text": "",
        "in_battle": False,
        "badges": ["Zephyr", "Hive"],
        "party": [{"hp": 61, "max_hp": 70}],
        "story_events": {
            "beat_beauty_victoria": True,
            "beat_lass_carrie": False,
            "beat_lass_bridget": False,
            "beat_whitney": False,
            "made_whitney_cry": False,
        },
    }

    assert "Carrie's RIGHT-facing sight line" in gold_route_guidance(base)
    assert trusted_gold_route_action(base) == "down"
    assert trusted_gold_route_action({
        **base,
        "coordinates": {"x": 14, "y": 13},
    }) == "left"
    assert trusted_gold_route_action({
        **base,
        "coordinates": {"x": 6, "y": 2},
    }) == "up"
    carrie_cleared = {
        **base,
        "coordinates": {"x": 13, "y": 13},
        "story_events": {
            **base["story_events"],
            "beat_lass_carrie": True,
        },
    }
    assert trusted_gold_route_action(carrie_cleared) == "up"
    assert trusted_gold_route_action({
        **carrie_cleared,
        "coordinates": {"x": 11, "y": 6},
    }) == "left"
    assert trusted_gold_goldenrod_buttons({
        **carrie_cleared,
        "coordinates": {"x": 10, "y": 6},
    }) == ["left", "a"]
    bridget_cleared = {
        **carrie_cleared,
        "coordinates": {"x": 10, "y": 6},
        "story_events": {
            **carrie_cleared["story_events"],
            "beat_lass_bridget": True,
        },
    }
    assert trusted_gold_route_action(bridget_cleared) == "right"
    assert trusted_gold_route_action({
        **bridget_cleared,
        "coordinates": {"x": 8, "y": 5},
    }) == "up"
    assert trusted_gold_route_action({
        **bridget_cleared,
        "coordinates": {"x": 3, "y": 13},
    }) == "up"
    assert trusted_gold_route_action({
        **bridget_cleared,
        "coordinates": {"x": 13, "y": 9},
    }) == "left"
    assert trusted_gold_goldenrod_buttons({
        **bridget_cleared,
        "coordinates": {"x": 8, "y": 4},
    }) == ["up", "a"]
    assert trusted_gold_goldenrod_buttons({
        **bridget_cleared,
        "in_battle": True,
        "screen_text": "MILTANK | FIGHT | PACK RUN",
    }) == ["up", "left", "a"]
    assert trusted_gold_goldenrod_buttons({
        **bridget_cleared,
        "in_battle": True,
        "screen_text": "CUT | LEER | BITE | WATER GUN",
        "menu_cursor_y": 2,
    }) == ["down"]
    assert trusted_gold_goldenrod_buttons({
        **bridget_cleared,
        "in_battle": True,
        "screen_text": "Disabled! | CUT | LEER | BITE | WATER GUN",
        "disabled_move_id": 55,
        "menu_cursor_y": 4,
    }) == ["up"]
    assert trusted_gold_goldenrod_buttons({
        **bridget_cleared,
        "in_battle": True,
        "screen_text": "Disabled! | CUT | LEER | BITE | WATER GUN",
        "disabled_move_id": 44,
        "menu_cursor_y": 3,
    }) == ["down"]
    crying = {
        **bridget_cleared,
        "coordinates": {"x": 8, "y": 4},
        "story_events": {
            **bridget_cleared["story_events"],
            "beat_whitney": True,
            "made_whitney_cry": True,
        },
    }
    assert trusted_gold_route_action(crying) == "down"
    ready_for_badge = {
        **crying,
        "coordinates": {"x": 8, "y": 5},
        "story_events": {
            **crying["story_events"],
            "made_whitney_cry": False,
        },
    }
    assert trusted_gold_route_action(ready_for_badge) == "up"
    assert trusted_gold_goldenrod_buttons({
        **ready_for_badge,
        "coordinates": {"x": 8, "y": 4},
    }) == ["up", "a"]
    plain_badge = {
        **ready_for_badge,
        "coordinates": {"x": 14, "y": 11},
        "badges": ["Zephyr", "Hive", "Plain"],
    }
    assert "south exit" in gold_route_guidance(plain_badge)
    assert trusted_gold_route_action(plain_badge) == "left"
    assert trusted_gold_route_action({
        **plain_badge,
        "coordinates": {"x": 4, "y": 17},
    }) == "left"
    assert trusted_gold_route_action({
        **plain_badge,
        "coordinates": {"x": 8, "y": 5},
    }) == "down"
    assert trusted_gold_route_action({
        **plain_badge,
        "coordinates": {"x": 4, "y": 9},
    }) == "right"
    wrong_house = {
        **plain_badge,
        "map_number": 0x0A,
        "coordinates": {"x": 5, "y": 4},
        "key_items": {"squirt_bottle": False},
    }
    assert "wrong PP tutorial house" in gold_route_guidance(wrong_house)
    assert trusted_gold_route_action(wrong_house) == "down"
    flower_shop = {
        **wrong_house,
        "map_number": 0x08,
        "coordinates": {"x": 3, "y": 6},
    }
    assert "teacher at (2,4)" in gold_route_guidance(flower_shop)
    assert trusted_gold_route_action(flower_shop) == "left"
    assert trusted_gold_squirtbottle_buttons({
        **flower_shop,
        "coordinates": {"x": 2, "y": 5},
    }) == ["up", "a"]
    with_bottle = {
        **flower_shop,
        "coordinates": {"x": 2, "y": 5},
        "key_items": {"squirt_bottle": True},
    }
    assert trusted_gold_route_action(with_bottle) == "down"
    assert trusted_gold_squirtbottle_buttons(with_bottle) is None
    city_to_flower = {
        **flower_shop,
        "map_number": 0x02,
        "coordinates": {"x": 29, "y": 8},
    }
    assert trusted_gold_route_action(city_to_flower) == "up"
    assert trusted_gold_route_action({
        **city_to_flower,
        "coordinates": {"x": 33, "y": 6},
    }) == "up"
    city_to_route35 = {
        **with_bottle,
        "map_number": 0x02,
        "coordinates": {"x": 21, "y": 10},
    }
    assert trusted_gold_route_action(city_to_route35) == "up"
    assert trusted_gold_route_action({
        **city_to_route35,
        "coordinates": {"x": 19, "y": 2},
    }) == "up"
    route35_gate = {
        **city_to_route35,
        "map_group": 0x0A,
        "map_number": 0x0E,
        "coordinates": {"x": 4, "y": 7},
    }
    assert trusted_gold_route_action(route35_gate) == "up"
    route35 = {
        **route35_gate,
        "map_number": 0x02,
        "coordinates": {"x": 9, "y": 19},
    }
    assert "Do not turn east" in gold_route_guidance(route35)
    assert trusted_gold_route_action(route35) == "left"
    assert trusted_gold_route_action({
        **route35,
        "coordinates": {"x": 3, "y": 6},
    }) == "up"
    assert trusted_gold_route_action({
        **route35,
        "coordinates": {"x": 5, "y": 12},
    }) == "left"
    sealed_route35 = {
        **route35,
        "coordinates": {"x": 7, "y": 19},
        "route35_ivan_blocking": True,
        "in_battle": False,
        "screen_text": "",
    }
    assert trusted_gold_route35_recovery_buttons(sealed_route35) == [
        "down",
        "a",
    ]
    assert trusted_gold_route35_recovery_buttons({
        **sealed_route35,
        "in_battle": True,
        "screen_text": "PIKACHU | FIGHT | PACK RUN",
    }) == ["up", "left", "a"]
    assert trusted_gold_route35_recovery_buttons({
        **sealed_route35,
        "in_battle": True,
        "screen_text": "CUT | LEER | BITE | WATER GUN",
        "menu_cursor_y": 3,
    }) == ["up"]
    national_park = {
        **route35,
        "map_group": 0x03,
        "map_number": 0x0F,
        "coordinates": {"x": 19, "y": 34},
    }
    assert "Route 36 gate" in gold_route_guidance(national_park)
    assert trusted_gold_route_action(national_park) == "up"
    assert trusted_gold_route_action({
        **national_park,
        "coordinates": {"x": 33, "y": 19},
    }) == "right"
    route36 = {
        **route35,
        "map_number": 0x03,
        "coordinates": {"x": 22, "y": 13},
        "story_events": {
            **route35["story_events"],
            "fought_sudowoodo": False,
        },
    }
    assert trusted_gold_route_action(route36) == "down"
    assert trusted_gold_route_action({
        **route36,
        "coordinates": {"x": 35, "y": 11},
    }) == "up"
    assert trusted_gold_sudowoodo_buttons({
        **route36,
        "coordinates": {"x": 35, "y": 10},
    }) == ["up", "a"]
    assert trusted_gold_sudowoodo_buttons({
        **route36,
        "coordinates": {"x": 35, "y": 10},
        "in_battle": True,
        "enemy_species_id": 185,
        "screen_text": "SUDOWOODO | FIGHT | PACK RUN",
    }) == ["up", "left", "a"]
    dance_theater = {
        **route36,
        "map_group": 0x04,
        "map_number": 0x05,
        "coordinates": {"x": 6, "y": 5},
        "story_events": {
            **route36["story_events"],
            "beat_kimono_miki": False,
            "beat_kimono_kuni": False,
            "beat_kimono_zuki": False,
            "beat_kimono_sayo": False,
            "beat_kimono_naoko": False,
            "got_hm_surf": False,
        },
    }
    assert trusted_gold_route_action(dance_theater) == "right"
    assert trusted_gold_dance_theater_buttons({
        **dance_theater,
        "coordinates": {"x": 10, "y": 2},
    }) == ["right", "a"]
    assert trusted_gold_dance_theater_buttons({
        **dance_theater,
        "in_battle": True,
        "enemy_species_id": 197,
        "screen_text": "CUT | LEER | BITE | WATER GUN",
        "menu_cursor_y": 3,
    }) == ["down"]
    all_kimono = {
        **dance_theater,
        "coordinates": {"x": 1, "y": 2},
        "story_events": {
            **dance_theater["story_events"],
            "beat_kimono_miki": True,
            "beat_kimono_kuni": True,
            "beat_kimono_zuki": True,
            "beat_kimono_sayo": True,
            "beat_kimono_naoko": True,
        },
    }
    assert trusted_gold_route_action(all_kimono) == "down"
    assert trusted_gold_dance_theater_buttons({
        **all_kimono,
        "coordinates": {"x": 6, "y": 10},
    }) == ["right", "a"]
    surf_owned = {
        **all_kimono,
        "coordinates": {"x": 6, "y": 10},
        "story_events": {
            **all_kimono["story_events"],
            "got_hm_surf": True,
        },
    }
    assert trusted_gold_route_action(surf_owned) == "down"
    ecruteak_low_hp = {
        **surf_owned,
        "map_number": 0x09,
        "coordinates": {"x": 23, "y": 22},
        "party": [{"hp": 19, "max_hp": 84}],
    }
    assert "below one-third HP" in gold_route_guidance(ecruteak_low_hp)
    assert trusted_gold_route_action(ecruteak_low_hp) == "down"
    assert trusted_gold_route_action({
        **ecruteak_low_hp,
        "coordinates": {"x": 24, "y": 29},
    }) == "up"
    assert trusted_gold_route_action({
        **ecruteak_low_hp,
        "coordinates": {"x": 23, "y": 23},
    }) == "left"
    ecruteak_tower = {
        **ecruteak_low_hp,
        "coordinates": {"x": 7, "y": 7},
        "party": [{"hp": 84, "max_hp": 84}],
        "lead_moves": [15, 249, 44, 55],
        "story_events": {
            **ecruteak_low_hp["story_events"],
            "got_tm_rock_smash": True,
        },
    }
    assert "release is optional" in gold_route_guidance(ecruteak_tower)
    assert trusted_gold_route_action(ecruteak_tower) is None
    rock_smash_unlearned = {
        **ecruteak_tower,
        "lead_moves": [15, 43, 44, 55],
    }
    assert "release is optional" in gold_route_guidance(rock_smash_unlearned)
    assert trusted_gold_route_action(rock_smash_unlearned) is None
    poisoned_tower = {
        **ecruteak_tower,
        "map_group": 0x03,
        "map_number": 0x0D,
        "coordinates": {"x": 9, "y": 15},
        "lead_status": 8,
        "script_mode": 1,
        "script_running": 0,
        "in_battle": False,
    }
    assert trusted_gold_poison_recovery_buttons(poisoned_tower) == ["a"]
    assert trusted_gold_route_action({
        **poisoned_tower,
        "script_mode": 0,
    }) == "down"
    assert trusted_gold_route_action({
        **poisoned_tower,
        "map_group": 0x04,
        "map_number": 0x09,
        "coordinates": {"x": 6, "y": 13},
        "script_mode": 0,
    }) == "right"
    assert trusted_gold_route_action({
        **poisoned_tower,
        "map_group": 0x04,
        "map_number": 0x09,
        "coordinates": {"x": 8, "y": 20},
        "script_mode": 0,
    }) == "down"
    assert trusted_gold_route_action({
        **poisoned_tower,
        "map_group": 0x04,
        "map_number": 0x09,
        "coordinates": {"x": 8, "y": 23},
        "script_mode": 0,
    }) == "right"
    assert trusted_gold_route_action({
        **poisoned_tower,
        "map_group": 0x04,
        "map_number": 0x09,
        "coordinates": {"x": 23, "y": 28},
        "script_mode": 0,
    }) == "up"
    healed_tower = {
        **poisoned_tower,
        "coordinates": {"x": 13, "y": 12},
        "lead_status": 0,
        "script_mode": 0,
    }
    assert "beasts are optional" in gold_route_guidance(healed_tower)
    assert trusted_gold_route_action({
        **healed_tower,
        "map_number": 0x0E,
        "coordinates": {"x": 8, "y": 14},
    }) == "left"
    assert trusted_gold_route_action({
        **healed_tower,
        "coordinates": {"x": 9, "y": 15},
        "story_events": {
            **healed_tower["story_events"],
            "got_tm_rock_smash": False,
        },
    }) == "down"
    ecruteak_gym = {
        **healed_tower,
        "map_group": 0x04,
        "map_number": 0x07,
        "coordinates": {"x": 4, "y": 13},
    }
    assert "invisible-floor route" in gold_route_guidance(ecruteak_gym)
    assert trusted_gold_route_action(ecruteak_gym) == "right"
    assert trusted_gold_route_action({
        **ecruteak_gym,
        "coordinates": {"x": 6, "y": 2},
    }) == "left"
    assert trusted_gold_morty_buttons({
        **ecruteak_gym,
        "coordinates": {"x": 5, "y": 2},
    }) == ["up", "a"]
    assert trusted_gold_hidden_phone_buttons({
        **ecruteak_gym,
        "script_mode": 1,
        "script_running": 0,
    }) == ["a"]
    lighthouse_1f = {
        **ecruteak_gym,
        "map_group": 0x03,
        "map_number": 0x22,
        "coordinates": {"x": 15, "y": 2},
    }
    assert trusted_gold_route_action(lighthouse_1f) == "down"
    assert trusted_gold_route_action({
        **lighthouse_1f,
        "coordinates": {"x": 11, "y": 14},
    }) == "right"
    assert trusted_gold_route_action({
        **lighthouse_1f,
        "coordinates": {"x": 3, "y": 10},
    }) == "down"
    lighthouse_2f = {
        **lighthouse_1f,
        "map_number": 0x23,
        "coordinates": {"x": 13, "y": 2},
    }
    assert trusted_gold_route_action({
        **lighthouse_2f,
        "coordinates": {"x": 3, "y": 11},
    }) == "down"
    assert trusted_gold_route_action(lighthouse_2f) == "left"
    assert trusted_gold_route_action({
        **lighthouse_2f,
        "coordinates": {"x": 6, "y": 3},
    }) == "left"
    assert trusted_gold_route_action({
        **lighthouse_2f,
        "coordinates": {"x": 9, "y": 15},
    }) == "up"
    assert trusted_gold_route_action({
        **lighthouse_2f,
        "coordinates": {"x": 5, "y": 15},
    }) == "up"
    assert trusted_gold_route_action({
        **lighthouse_2f,
        "coordinates": {"x": 10, "y": 3},
    }) == "up"
    assert trusted_gold_lighthouse_buttons({
        **lighthouse_2f,
        "coordinates": {"x": 10, "y": 3},
    }) == ["up", "up", "up"]
    assert trusted_gold_route_action({
        **lighthouse_2f,
        "coordinates": {"x": 10, "y": 2},
    }) == "left"
    lighthouse_3f = {
        **lighthouse_2f,
        "map_number": 0x24,
        "coordinates": {"x": 4, "y": 5},
    }
    assert trusted_gold_route_action({
        **lighthouse_3f,
        "coordinates": {"x": 5, "y": 3},
    }) == "down"
    assert trusted_gold_route_action(lighthouse_3f) == "left"
    assert trusted_gold_route_action({
        **lighthouse_3f,
        "coordinates": {"x": 14, "y": 3},
    }) == "left"
    assert trusted_gold_route_action({
        **lighthouse_3f,
        "coordinates": {"x": 3, "y": 6},
    }) == "left"
    lighthouse_4f = {
        **lighthouse_3f,
        "map_number": 0x25,
        "coordinates": {"x": 13, "y": 3},
    }
    assert trusted_gold_route_action(lighthouse_4f) == "left"
    assert trusted_gold_route_action({
        **lighthouse_4f,
        "coordinates": {"x": 3, "y": 6},
    }) is None
    assert trusted_gold_route_action({
        **lighthouse_4f,
        "coordinates": {"x": 3, "y": 8},
    }) == "down"
    assert trusted_gold_lighthouse_buttons({
        **lighthouse_4f,
        "coordinates": {"x": 15, "y": 3},
    }) == ["left"] * 6
    lighthouse_5f = {
        **lighthouse_4f,
        "map_number": 0x26,
        "coordinates": {"x": 3, "y": 5},
    }
    assert trusted_gold_route_action(lighthouse_5f) == "up"
    assert trusted_gold_lighthouse_buttons({
        **lighthouse_5f,
        "coordinates": {"x": 3, "y": 4},
    }) == ["down"] * 6
    assert trusted_gold_route_action({
        **lighthouse_5f,
        "coordinates": {"x": 9, "y": 13},
    }) == "down"
    lighthouse_6f = {
        **lighthouse_5f,
        "map_number": 0x27,
        "coordinates": {"x": 9, "y": 15},
    }
    assert trusted_gold_route_action(lighthouse_6f) == "up"
    assert trusted_gold_lighthouse_buttons({
        **lighthouse_6f,
        "coordinates": {"x": 8, "y": 9},
    }) == ["up", "a"]
    explained_lighthouse = {
        **lighthouse_6f,
        "coordinates": {"x": 8, "y": 9},
        "story_events": {
            **lighthouse_6f["story_events"],
            "jasmine_explained_sickness": True,
        },
    }
    assert trusted_gold_route_action(explained_lighthouse) == "right"
    assert trusted_gold_lighthouse_buttons(explained_lighthouse) == [
        "right",
    ] * 6
    assert trusted_gold_route_action({
        **explained_lighthouse,
        "coordinates": {"x": 10, "y": 8},
    }) == "down"
    assert trusted_gold_route_action({
        **explained_lighthouse,
        "coordinates": {"x": 10, "y": 10},
    }) == "up"
    assert trusted_gold_route_action({
        **explained_lighthouse,
        "map_number": 0x24,
        "coordinates": {"x": 14, "y": 10},
    }) == "down"
    assert trusted_gold_lighthouse_buttons({
        **explained_lighthouse,
        "map_number": 0x22,
        "coordinates": {"x": 11, "y": 15},
    }) == ["down"] * 6
    assert trusted_gold_route_action({
        **explained_lighthouse,
        "map_group": 0x01,
        "map_number": 0x0E,
        "coordinates": {"x": 27, "y": 27},
    }) == "up"
    assert trusted_gold_route_action({
        **explained_lighthouse,
        "map_group": 0x01,
        "map_number": 0x0E,
        "coordinates": {"x": 17, "y": 23},
    }) == "left"
    cianwood = {
        **explained_lighthouse,
        "map_group": 0x16,
        "map_number": 0x03,
        "coordinates": {"x": 19, "y": 33},
    }
    assert trusted_gold_route_action(cianwood) == "down"
    pharmacy = {
        **cianwood,
        "map_number": 0x07,
        "coordinates": {"x": 2, "y": 4},
    }
    assert "pharmacist" in gold_route_guidance(pharmacy)
    assert trusted_gold_route_action(pharmacy) == "up"
    assert trusted_gold_cianwood_buttons(pharmacy) == ["up", "a"]
    pharmacy_done = {
        **pharmacy,
        "story_events": {
            **pharmacy["story_events"],
            "got_secret_potion": True,
        },
    }
    assert trusted_gold_route_action(pharmacy_done) == "down"
    assert trusted_gold_cianwood_buttons(pharmacy_done) is None
    cianwood_hurt = {
        **pharmacy_done,
        "map_number": 0x03,
        "coordinates": {"x": 20, "y": 44},
        "party": [{"hp": 59, "max_hp": 121}],
    }
    assert trusted_gold_route_action(cianwood_hurt) == "right"
    cianwood_center = {
        **cianwood_hurt,
        "map_number": 0x06,
        "coordinates": {"x": 3, "y": 3},
    }
    assert trusted_gold_route_action(cianwood_center) is None
    assert trusted_gold_cianwood_buttons(cianwood_center) == ["up", "a"]
    assert trusted_gold_route_action({
        **cianwood_center,
        "coordinates": {"x": 3, "y": 4},
    }) == "up"
    cianwood_healed = {
        **cianwood_hurt,
        "coordinates": {"x": 20, "y": 44},
        "party": [{"hp": 121, "max_hp": 121}],
    }
    assert trusted_gold_route_action(cianwood_healed) == "left"
    cianwood_gym = {
        **pharmacy_done,
        "map_number": 0x05,
        "coordinates": {"x": 4, "y": 9},
        "strength_active": True,
        "facing_direction": 4,
        "cianwood_gym_boulders": [
            {"x": 3, "y": 7},
            {"x": 4, "y": 7},
            {"x": 5, "y": 7},
        ],
    }
    assert trusted_gold_route_action(cianwood_gym) == "up"
    assert trusted_gold_route_action({
        **cianwood_gym,
        "coordinates": {"x": 5, "y": 8},
    }) == "left"
    assert trusted_gold_route_action({
        **cianwood_gym,
        "coordinates": {"x": 5, "y": 7},
        "cianwood_gym_boulders": [
            {"x": 3, "y": 7},
            {"x": 4, "y": 7},
            {"x": 5, "y": 6},
        ],
    }) == "down"
    assert trusted_gold_route_action({
        **cianwood_gym,
        "coordinates": {"x": 5, "y": 13},
        "cianwood_gym_boulders": [],
    }) == "left"
    left_lifted = {
        **cianwood_gym,
        "coordinates": {"x": 3, "y": 8},
        "cianwood_gym_boulders": [
            {"x": 3, "y": 6},
            {"x": 4, "y": 7},
            {"x": 5, "y": 7},
        ],
    }
    assert trusted_gold_route_action(left_lifted) == "up"
    assert trusted_gold_route_action({
        **left_lifted,
        "facing_direction": 0,
    }) == "right"
    sides_lifted = {
        **left_lifted,
        "coordinates": {"x": 5, "y": 8},
        "cianwood_gym_boulders": [
            {"x": 3, "y": 6},
            {"x": 5, "y": 6},
            {"x": 4, "y": 7},
        ],
    }
    assert trusted_gold_route_action(sides_lifted) == "up"
    assert trusted_gold_route_action({
        **sides_lifted,
        "facing_direction": 0,
    }) == "left"
    center_open = {
        **sides_lifted,
        "coordinates": {"x": 4, "y": 6},
        "cianwood_gym_boulders": [
            {"x": 3, "y": 6},
            {"x": 5, "y": 6},
            {"x": 5, "y": 7},
        ],
    }
    assert trusted_gold_route_action(center_open) == "up"
    assert trusted_gold_route_action({
        **center_open,
        "coordinates": {"x": 4, "y": 4},
    }) == "left"
    assert trusted_gold_cianwood_buttons({
        **center_open,
        "coordinates": {"x": 4, "y": 2},
    }) == ["up", "a"]
    chuck_defeated = {
        **center_open,
        "coordinates": {"x": 4, "y": 2},
        "badges": [*center_open["badges"], "Storm"],
        "story_events": {
            **center_open["story_events"],
            "beat_chuck": True,
        },
    }
    assert "HM02 Fly" in gold_route_guidance(chuck_defeated)
    assert trusted_gold_route_action(chuck_defeated) == "left"
    assert trusted_gold_route_action({
        **chuck_defeated,
        "coordinates": {"x": 3, "y": 2},
    }) == "down"
    chuck_wife_route = {
        **chuck_defeated,
        "map_number": 0x03,
        "coordinates": {"x": 8, "y": 44},
    }
    assert "Chuck's wife" in gold_route_guidance(chuck_wife_route)
    assert trusted_gold_route_action(chuck_wife_route) == "down"
    assert trusted_gold_cianwood_buttons({
        **chuck_wife_route,
        "coordinates": {"x": 9, "y": 46},
    }) == ["right", "a"]
    assert "x=36" in gold_route_guidance({
        **chuck_wife_route,
        "map_number": 0x02,
        "story_events": {
            **chuck_wife_route["story_events"],
            "got_hm_fly": True,
        },
    })
    assert "NORTH through Route 40" in gold_route_guidance({
        **chuck_wife_route,
        "map_number": 0x01,
    })
    assert trusted_gold_route_action({
        **chuck_wife_route,
        "map_group": 0x01,
        "map_number": 0x0E,
        "coordinates": {"x": 23, "y": 11},
        "key_items": {"secret_potion": True},
    }) == "down"
    olivine_gym_route = {
        **chuck_wife_route,
        "map_group": 0x01,
        "map_number": 0x0E,
        "coordinates": {"x": 29, "y": 28},
        "story_events": {
            **chuck_wife_route["story_events"],
            "got_hm_strength": True,
            "got_secret_potion": True,
            "jasmine_returned_to_gym": True,
        },
    }
    assert "Amphy is healed" in gold_route_guidance(olivine_gym_route)
    assert trusted_gold_route_action(olivine_gym_route) == "left"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "coordinates": {"x": 16, "y": 18},
    }) == "right"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_number": 0x0D,
        "coordinates": {"x": 12, "y": 5},
        "badges": [*olivine_gym_route["badges"], "Mineral"],
    }) == "down"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x02,
        "map_number": 0x05,
        "coordinates": {"x": 18, "y": 14},
        "badges": [*olivine_gym_route["badges"], "Mineral"],
    }) == "up"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x02,
        "map_number": 0x05,
        "coordinates": {"x": 33, "y": 9},
        "badges": [*olivine_gym_route["badges"], "Glacier"],
    }) == "down"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x02,
        "map_number": 0x07,
        "coordinates": {"x": 16, "y": 8},
        "badges": [*olivine_gym_route["badges"], "Mineral"],
        "key_items": {"red_scale": False},
    }) == "left"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x09,
        "map_number": 0x06,
        "coordinates": {"x": 21, "y": 26},
        "key_items": {"red_scale": True},
    }) == "right"
    assert trusted_gold_lake_buttons({
        **olivine_gym_route,
        "map_group": 0x09,
        "map_number": 0x06,
        "coordinates": {"x": 22, "y": 28},
        "key_items": {"red_scale": True},
    }) == ["left", "a"]
    assert trusted_gold_lake_buttons({
        **olivine_gym_route,
        "map_group": 0x09,
        "map_number": 0x06,
        "coordinates": {"x": 22, "y": 28},
        "key_items": {"red_scale": True},
        "screen_text": "LAKE OF RAGE",
    }) == ["a"]
    assert trusted_gold_lake_buttons({
        **olivine_gym_route,
        "map_group": 0x09,
        "map_number": 0x06,
        "coordinates": {"x": 21, "y": 26},
        "key_items": {"red_scale": True},
        "screen_text": "YES | NO | Will you help?",
    }) == ["up", "a"]
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x09,
        "map_number": 0x05,
        "coordinates": {"x": 3, "y": 17},
        "story_events": {
            **olivine_gym_route["story_events"],
            "decided_to_help_lance": True,
        },
    }) == "right"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2A,
        "coordinates": {"x": 14, "y": 11},
        "story_events": {
            **olivine_gym_route["story_events"],
            "cleared_rocket_hideout": True,
        },
    }) == "down"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x29,
        "coordinates": {"x": 5, "y": 2},
        "story_events": {
            **olivine_gym_route["story_events"],
            "cleared_rocket_hideout": True,
        },
    }) == "right"
    assert trusted_gold_rocket_buttons({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2B,
        "coordinates": {"x": 11, "y": 10},
        "story_events": {
            **olivine_gym_route["story_events"],
            "met_rival_rocket_base": True,
        },
    }) == ["up", "a"]
    assert trusted_gold_rocket_buttons({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2A,
        "coordinates": {"x": 8, "y": 7},
        "story_events": {
            **olivine_gym_route["story_events"],
            "opened_rocket_transmitter_door": True,
            "rocket_electrode_3": True,
        },
    }) == ["left", "a"]
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2A,
        "coordinates": {"x": 8, "y": 9},
        "story_events": {
            **olivine_gym_route["story_events"],
            "opened_rocket_transmitter_door": True,
            "rocket_electrode_3": True,
        },
    }) == "right"
    assert trusted_gold_rocket_buttons({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2B,
        "coordinates": {"x": 3, "y": 3},
        "story_events": {
            **olivine_gym_route["story_events"],
            "learned_hail_giovanni": True,
        },
    }) == ["up"] * 6
    assert trusted_gold_rocket_buttons({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2A,
        "coordinates": {"x": 15, "y": 13},
        "story_events": {
            **olivine_gym_route["story_events"],
            "learned_hail_giovanni": True,
        },
    }) == ["up", "a"]
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2B,
        "coordinates": {"x": 3, "y": 2},
        "story_events": {
            **olivine_gym_route["story_events"],
            "learned_hail_giovanni": True,
        },
    }) == "down"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2A,
        "coordinates": {"x": 3, "y": 1},
        "story_events": {
            **olivine_gym_route["story_events"],
            "learned_hail_giovanni": True,
        },
    }) == "right"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2B,
        "coordinates": {"x": 10, "y": 10},
        "story_events": {
            **olivine_gym_route["story_events"],
            "opened_giovanni_office": True,
        },
    }) == "up"
    assert trusted_gold_rocket_buttons({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2B,
        "coordinates": {"x": 7, "y": 3},
        "story_events": {
            **olivine_gym_route["story_events"],
            "beat_rocket_commander": True,
        },
    }) == ["up", "a"]
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2B,
        "coordinates": {"x": 3, "y": 3},
        "story_events": {
            **olivine_gym_route["story_events"],
            "learned_raticate_tail": True,
            "learned_slowpoketail": True,
        },
    }) == "down"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2B,
        "coordinates": {"x": 8, "y": 10},
        "story_events": {
            **olivine_gym_route["story_events"],
            "learned_raticate_tail": True,
            "learned_slowpoketail": True,
            "met_rival_rocket_base": True,
        },
    }) == "right"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x29,
        "coordinates": {"x": 2, "y": 14},
    }) == "right"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2A,
        "coordinates": {"x": 10, "y": 13},
    }) == "right"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2A,
        "coordinates": {"x": 22, "y": 13},
    }) == "left"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2B,
        "coordinates": {"x": 28, "y": 4},
        "story_events": {
            **olivine_gym_route["story_events"],
            "learned_raticate_tail": True,
        },
    }) == "up"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2A,
        "coordinates": {"x": 27, "y": 3},
        "story_events": {
            **olivine_gym_route["story_events"],
            "learned_raticate_tail": True,
            "learned_slowpoketail": True,
        },
    }) == "right"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x2A,
        "coordinates": {"x": 5, "y": 1},
        "rocket_grunt18_blocking": True,
        "story_events": {
            **olivine_gym_route["story_events"],
            "learned_raticate_tail": True,
            "learned_slowpoketail": True,
        },
    }) == "right"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x02,
        "map_number": 0x07,
        "coordinates": {"x": 13, "y": 8},
        "story_events": {
            **olivine_gym_route["story_events"],
            "decided_to_help_lance": True,
        },
    }) == "left"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x02,
        "map_number": 0x02,
        "coordinates": {"x": 7, "y": 2},
    }) == "left"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x02,
        "map_number": 0x07,
        "coordinates": {"x": 10, "y": 14},
        "badges": [*olivine_gym_route["badges"], "Glacier"],
    }) == "up"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x0B,
        "map_number": 0x02,
        "coordinates": {"x": 15, "y": 28},
        "badges": [*olivine_gym_route["badges"], "Glacier"],
    }) == "right"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x02,
        "map_number": 0x07,
        "coordinates": {"x": 3, "y": 12},
        "story_events": {
            **olivine_gym_route["story_events"],
            "cleared_rocket_hideout": True,
        },
    }) == "left"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x03,
        "map_number": 0x28,
        "coordinates": {"x": 5, "y": 4},
        "story_events": {
            **olivine_gym_route["story_events"],
            "decided_to_help_lance": True,
        },
    }) == "right"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_number": 0x09,
        "coordinates": {"x": 0, "y": 5},
        "badges": [*olivine_gym_route["badges"], "Mineral"],
    }) == "right"
    assert trusted_gold_route_action({
        **olivine_gym_route,
        "map_group": 0x04,
        "map_number": 0x09,
        "coordinates": {"x": 32, "y": 21},
        "badges": [*olivine_gym_route["badges"], "Mineral"],
    }) == "down"
    assert trusted_gold_route_action({
        **chuck_wife_route,
        "map_group": 0x01,
        "map_number": 0x05,
        "coordinates": {"x": 2, "y": 7},
        "key_items": {"secret_potion": True},
    }) == "down"
    route36_rock_smash = {
        **healed_tower,
        "map_group": 0x0A,
        "map_number": 0x03,
        "coordinates": {"x": 32, "y": 9},
        "story_events": {
            **healed_tower["story_events"],
            "fought_sudowoodo": True,
            "got_tm_rock_smash": False,
        },
    }
    assert trusted_gold_route_action(route36_rock_smash) == "right"
    assert trusted_gold_rock_smash_gift_buttons({
        **route36_rock_smash,
        "coordinates": {"x": 43, "y": 9},
    }) == ["right", "a"]


def test_normalize_brain_decision_filters_buttons():
    response = """```json
    {
      "phase": "overworld",
      "observation": "Standing near a path",
      "objective": "Reach Viridian City",
      "reason": "The path continues north",
      "buttons": ["UP", "invalid", "a"],
      "checkpoint": true
    }
    ```"""

    decision = normalize_brain_decision(response)

    assert decision["buttons"] == ["up", "a"]
    assert decision["checkpoint"] is True
    assert decision["objective"] == "Reach Viridian City"
    assert decision["action_mode"] == "precision"


def test_normalize_brain_decision_requires_valid_button():
    with pytest.raises(ValueError, match="valid button"):
        normalize_brain_decision('{"buttons":["x"],"checkpoint":false}')


def test_normalize_brain_decision_normalizes_phase_and_action_mode():
    normalized = normalize_brain_decision(
        '{"phase":"Overworld","action_mode":"CORRIDOR","buttons":["up"]}'
    )
    assert normalized["phase"] == "overworld"
    assert normalized["action_mode"] == "corridor"

    invalid = normalize_brain_decision(
        '{"phase":"hostile","action_mode":"hostile","buttons":["up"]}'
    )
    assert invalid["phase"] == "other"
    assert invalid["action_mode"] == "precision"


@pytest.mark.parametrize(
    ("buttons", "expected"),
    [
        (["right"] * 6, ["right"] * 3),
        (["right", "right", "down", "down"], ["right", "right"]),
        (["a", "up"], ["a"]),
        (["b"] * 6, ["b"]),
    ],
)
def test_precision_route_buttons_force_short_reobservation(buttons, expected):
    assert precision_route_buttons(buttons) == expected


def test_overworld_action_mode_is_generic_not_route_specific():
    assert overworld_action_buttons(["right"] * 6, precision=False) == [
        "right"
    ] * 6
    assert overworld_action_buttons(
        ["right", "right", "down", "down"],
        precision=False,
    ) == ["right", "right"]
    assert overworld_action_buttons(["up"] * 6, precision=True) == ["up"] * 3


def test_copilot_prompt_keeps_static_rules_in_system_message():
    brain = CopilotBrain.__new__(CopilotBrain)
    prompt = brain._prompt(
        {"location": "Pallet Town", "badges": []},
        "####\n#P.#",
        [{"buttons": ["up"], "objective": "Leave home"}],
    )

    assert "Pallet Town" in prompt
    assert "Leave home" in prompt
    assert "####" in prompt
    assert "finish Pokemon Red" not in prompt
    assert "finish Pokemon Red" in GAME_SYSTEM_PROMPT
    assert "Never use Dig outside battle" in GAME_SYSTEM_PROMPT
    assert "B1F ladder (27,3)" in GAME_SYSTEM_PROMPT
    assert "1F south exit (15,33)" in GAME_SYSTEM_PROMPT
    assert "B1F (3,33) is not an exit" in GAME_SYSTEM_PROMPT
    assert "crowd route hypothesis" in GAME_SYSTEM_PROMPT
    assert "Navigation memory is trusted" in GAME_SYSTEM_PROMPT
    assert not hasattr(CopilotBrain, "_decide_cli")


def test_copilot_prompt_treats_crowd_direction_as_optional_hypothesis():
    prompt = CopilotBrain._prompt(
        {"location": "Rocket Hideout B3F"},
        "..........\n" * 4 + "....P.....\n" + "..........\n" * 4,
        [],
        {"kind": "overworld_direction", "direction": "left"},
    )

    assert "Optional untrusted crowd route hypothesis" in prompt
    assert '{"kind":"overworld_direction","direction":"left"}' in prompt
    assert "Ignore it unless" in prompt


def test_copilot_prompt_labels_source_cited_web_research_untrusted():
    prompt = CopilotBrain._prompt(
        {"location": "Rocket Hideout B3F"},
        None,
        [],
        None,
        {
            "summary": "The layout uses spin tiles.",
            "route_facts": ["B3F has a warp to B4F."],
            "sources": [
                {
                    "title": "Team Rocket Hideout",
                    "url": (
                        "https://bulbapedia.bulbagarden.net/wiki/"
                        "Team_Rocket_Hideout"
                    ),
                }
            ],
        },
    )

    assert "Optional source-cited web research" in prompt
    assert "untrusted background evidence" in prompt
    assert "Team_Rocket_Hideout" in prompt


def test_bulbapedia_search_uses_fixed_origin_and_bounded_extracts(monkeypatch):
    responses = iter(
        [
            {
                "query": {
                    "search": [
                        {"title": "Team Rocket Hideout"},
                    ]
                }
            },
            {
                "query": {
                    "pages": {
                        "1": {
                            "extract": "Spin tiles create a maze on B3F.",
                        }
                    }
                }
            },
        ]
    )
    calls = []

    def fake_read(parameters):
        calls.append(parameters)
        return next(responses)

    monkeypatch.setattr(pokemon_module, "_read_bulbapedia_json", fake_read)

    result = search_pokemon_web("Rocket Hideout B3F", "route")

    assert result["query"] == "Rocket Hideout B3F route"
    assert calls[0]["srsearch"] == "Rocket Hideout B3F route"
    assert result["results"] == [
        {
            "title": "Team Rocket Hideout",
            "url": (
                "https://bulbapedia.bulbagarden.net/wiki/"
                "Team_Rocket_Hideout"
            ),
            "extract": "Spin tiles create a maze on B3F.",
        }
    ]
    assert calls[0]["action"] == "query"
    assert calls[1]["prop"] == "extracts"


def test_web_research_normalization_requires_exact_cited_schema():
    valid = normalize_web_research(
        json.dumps(
            {
                "summary": "The retained guide describes a spin-tile maze.",
                "route_facts": ["B3F connects to B4F through a staircase."],
                "sources": [
                    {
                        "title": "Team Rocket Hideout",
                        "url": (
                            "https://bulbapedia.bulbagarden.net/wiki/"
                            "Team_Rocket_Hideout"
                        ),
                    }
                ],
            }
        )
    )
    assert valid["route_facts"] == [
        "B3F connects to B4F through a staircase."
    ]

    hostile = dict(valid)
    hostile["sources"] = [
        {
            "title": "Hostile",
            "url": "https://example.invalid/instructions",
        }
    ]
    with pytest.raises(ValueError, match="source origin"):
        normalize_web_research(json.dumps(hostile))


@pytest.mark.parametrize(
    ("map_id", "coordinates", "expected"),
    [
        (232, {"x": 33, "y": 25}, "B1F ladder (27,3)"),
        (232, {"x": 23, "y": 11}, "B1F ladder (3,3)"),
        (82, {"x": 15, "y": 3}, "1F ladder (37,3)"),
        (82, {"x": 5, "y": 3}, "1F ladder (17,11)"),
        (82, {"x": 37, "y": 17}, "south exit"),
    ],
)
def test_rock_tunnel_route_guidance(map_id, coordinates, expected):
    guidance = rock_tunnel_route_guidance(
        {"map_id": map_id, "coordinates": coordinates}
    )
    assert expected in guidance


def test_celadon_route_guidance_targets_exact_gym_warps():
    city = celadon_route_guidance({"map_id": 6, "badges": []})
    gym = celadon_route_guidance({"map_id": 134, "badges": []})
    assert "(12,27)" in city
    assert "use Cut" in city
    assert "Erika at (4,3)" in gym
    assert celadon_route_guidance({"map_id": 6, "badges": ["Rainbow"]}) is None


@pytest.mark.parametrize(
    ("map_id", "key_items", "expected"),
    [
        (0xC7, {"lift_key": False, "silph_scope": False}, "(23,2)"),
        (0xC8, {"lift_key": False, "silph_scope": False}, "(21,8)"),
        (0xC9, {"lift_key": False, "silph_scope": False}, "(19,18)"),
        (0xCA, {"lift_key": False, "silph_scope": False}, "(10,2)"),
        (0xC8, {"lift_key": True, "silph_scope": False}, "(24,19)/(25,19)"),
        (0xCB, {"lift_key": True, "silph_scope": False}, "(1,1)"),
        (0xCA, {"lift_key": True, "silph_scope": False}, "(19,10)"),
        (0xC7, {"lift_key": True, "silph_scope": True}, "(21,2)"),
    ],
)
def test_rocket_hideout_guidance_locks_inventory_aware_waypoints(
    map_id,
    key_items,
    expected,
):
    guidance = rocket_hideout_route_guidance(
        {
            "map_id": map_id,
            "coordinates": {"x": 15, "y": 11},
            "key_items": key_items,
        }
    )
    assert expected in guidance
    assert "required" in guidance


def test_rocket_hideout_b3f_guidance_blocks_known_loops():
    guidance = rocket_hideout_route_guidance(
        {
            "map_id": 0xC9,
            "coordinates": {"x": 25, "y": 6},
            "key_items": {"lift_key": False, "silph_scope": False},
        }
    )
    assert "SOUTHWEST spinner maze" in guidance
    assert "east along the southern band to (19,18)" in guidance
    assert "walk west to the lone UP arrow" in guidance
    assert "decoy" in guidance
    assert "Never descend at x>=22" in guidance
    assert rocket_hideout_route_guidance({"map_id": 0xC6}) is None


def test_rocket_hideout_b4f_lift_key_requires_second_talk():
    guidance = rocket_hideout_route_guidance(
        {
            "map_id": 0xCA,
            "coordinates": {"x": 12, "y": 3},
            "key_items": {"lift_key": False, "silph_scope": False},
        }
    )
    # Gen-1 bug: the defeated Grunt only hands over the Lift Key on a
    # second interaction.
    assert "TALK TO HIM AGAIN" in guidance
    assert "second interaction" in guidance
    assert "(11,2)" in guidance
    assert "(10,2)" in guidance


def test_rocket_hideout_b4f_east_region_targets_giovanni():
    guidance = rocket_hideout_route_guidance(
        {
            "map_id": 0xCA,
            "coordinates": {"x": 24, "y": 14},
            "key_items": {"lift_key": True, "silph_scope": False},
        }
    )
    assert "Giovanni at (25,3)" in guidance
    assert "Silph Scope at (25,2)" in guidance


@pytest.mark.parametrize(
    ("coordinates", "previous_map_id", "expected"),
    [
        ({"x": 19, "y": 17}, 0xCB, "Giovanni at (25,3)"),
        ({"x": 20, "y": 10}, 0xC9, "(19,10)"),
        ({"x": 12, "y": 20}, 0xC9, "(19,10)"),
    ],
)
def test_rocket_hideout_b4f_uses_entry_region_connectivity(
    coordinates,
    previous_map_id,
    expected,
):
    guidance = rocket_hideout_route_guidance(
        {
            "map_id": 0xCA,
            "previous_map_id": previous_map_id,
            "coordinates": coordinates,
            "key_items": {"lift_key": True, "silph_scope": False},
        }
    )
    assert expected in guidance


def test_rocket_hideout_lower_b1f_does_not_target_unreachable_upper_region():
    guidance = rocket_hideout_route_guidance(
        {
            "map_id": 0xC7,
            "previous_map_id": 0xC8,
            "coordinates": {"x": 21, "y": 24},
            "key_items": {"lift_key": False, "silph_scope": False},
        }
    )
    assert "(21,24)" in guidance
    assert "disconnected lower B1F landing" in guidance


def test_rocket_hideout_b3f_with_scope_backtracks_to_b2f():
    guidance = rocket_hideout_route_guidance(
        {
            "map_id": 0xC9,
            "coordinates": {"x": 19, "y": 18},
            "key_items": {"lift_key": True, "silph_scope": True},
        }
    )
    assert "(25,6)" in guidance
    assert "B2F" in guidance


def test_navigation_memory_persists_repeated_failed_attempts(tmp_path):
    path = tmp_path / "navigation-memory.json"
    position = (0xC9, 15, 11)
    now = datetime.now(timezone.utc)
    memory = NavigationMemory(path)
    for _ in range(2):
        memory.begin(position, ["right"], phase="overworld")
        memory.finish(position, now=now)

    guidance = memory.guidance(position)
    reloaded = NavigationMemory(path)

    assert guidance["avoid_repeating"] == [
        {
            "buttons": ["right"],
            "outcome": "no_progress",
            "attempts": 2,
        }
    ]
    assert guidance["loop_detected"] is False
    assert "Changing only button count or order" in guidance["directive"]
    assert reloaded.guidance(position) == guidance


def test_navigation_memory_aggregates_button_count_variants(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    position = (0xC9, 15, 11)
    now = datetime.now(timezone.utc)
    for buttons in (["right"], ["right"] * 6):
        memory.begin(position, buttons, phase="overworld")
        memory.finish(position, now=now)

    guidance = memory.guidance(position)

    assert guidance["avoid_repeating"][0]["attempts"] == 2
    assert guidance["avoid_repeating"][0]["buttons"] == ["right"]


def test_item_gate_guidance_names_the_poke_flute_for_a_sleeping_blocker():
    """The exact string the Route 12 Snorlax prints, as read from the game."""
    guidance = item_gate_guidance(
        {"screen_text": "A sleeping POKMON | blocks the way!"}
    )

    assert guidance is not None
    assert "POKE FLUTE" in guidance
    assert "ITEM" in guidance
    # It must say the obstacle is unroutable, or the agent keeps probing.
    assert "cannot be walked around" in guidance.lower()


def test_item_gate_guidance_ignores_unrelated_and_empty_text():
    assert item_gate_guidance({"screen_text": ""}) is None
    assert item_gate_guidance({"screen_text": None}) is None
    assert item_gate_guidance({}) is None
    assert item_gate_guidance(
        {"screen_text": "RED POKMON | are fully healed!"}
    ) is None
    # A boulder also "blocks the way" but is a Strength puzzle, not an item.
    assert item_gate_guidance(
        {"screen_text": "A boulder blocks the way!"}
    ) is None


def tower_state(map_id, warps, x=11, y=9):
    return {
        "map_id": map_id,
        "coordinates": {"x": x, "y": y},
        "warps": warps,
    }


def test_tower_guidance_picks_the_ascending_stairs_on_each_floor():
    """The staircases swap sides floor to floor, so this must come from RAM.

    Both coordinate sets below were read from wWarpEntries on a live run.
    """
    fifth = pokemon_tower_route_guidance(
        tower_state(
            0x92,
            [
                {"x": 3, "y": 9, "destination_map": 0x91,
                 "destination_name": "Pokemon Tower 4F"},
                {"x": 18, "y": 9, "destination_map": 0x93,
                 "destination_name": "Pokemon Tower 6F"},
            ],
        )
    )
    fourth = pokemon_tower_route_guidance(
        tower_state(
            0x91,
            [
                {"x": 3, "y": 9, "destination_map": 0x92,
                 "destination_name": "Pokemon Tower 5F"},
                {"x": 18, "y": 9, "destination_map": 0x90,
                 "destination_name": "Pokemon Tower 3F"},
            ],
        )
    )

    assert "staircase at (18,9)" in fifth
    assert "Pokemon Tower 6F" in fifth
    # Same y, opposite side — a hardcoded coordinate would be wrong here.
    assert "staircase at (3,9)" in fourth
    assert "Pokemon Tower 5F" in fourth


def test_tower_guidance_sends_you_out_once_the_flute_is_owned():
    """Re-entering a cleared Tower must not restart the climb directive."""
    warps = [
        {"x": 3, "y": 9, "destination_map": 0x8F,
         "destination_name": "Pokemon Tower 2F"},
        {"x": 18, "y": 9, "destination_map": 0x91,
         "destination_name": "Pokemon Tower 4F"},
    ]
    state = tower_state(0x90, warps)
    state["key_items"] = {"poke_flute": True}

    guidance = pokemon_tower_route_guidance(state)

    assert "COMPLETE" in guidance
    # It must point at the DOWN staircase (2F), never the up one (4F).
    assert "(3,9)" in guidance
    assert "(18,9)" not in guidance
    assert "Climb to 7F" not in guidance


def test_tower_guidance_still_climbs_before_the_flute():
    warps = [
        {"x": 18, "y": 9, "destination_map": 0x93,
         "destination_name": "Pokemon Tower 6F"},
    ]
    for key_items in ({"poke_flute": False}, {}, None):
        state = tower_state(0x92, warps)
        if key_items is not None:
            state["key_items"] = key_items
        guidance = pokemon_tower_route_guidance(state)
        assert "Climb to 7F" in guidance
        assert "staircase at (18,9)" in guidance


def test_tower_guidance_warns_about_the_purified_zone_only_on_5f():
    warps = [
        {"x": 18, "y": 9, "destination_map": 0x93,
         "destination_name": "Pokemon Tower 6F"},
    ]

    assert "purified zone" in pokemon_tower_route_guidance(
        tower_state(0x92, warps)
    )
    assert "purified zone" not in pokemon_tower_route_guidance(
        tower_state(0x91, warps)
    )


def test_tower_guidance_invents_no_staircase_on_the_top_floor():
    guidance = pokemon_tower_route_guidance(
        tower_state(
            0x94,
            [
                {"x": 3, "y": 9, "destination_map": 0x93,
                 "destination_name": "Pokemon Tower 6F"},
            ],
        )
    )

    assert "do not invent one" in guidance.lower()


def test_tower_guidance_is_silent_off_the_tower_and_without_warps():
    assert pokemon_tower_route_guidance(
        tower_state(0xCA, [{"x": 1, "y": 1, "destination_map": 0xCB}])
    ) is None
    assert pokemon_tower_route_guidance(tower_state(0x92, [])) is None


# Warp coordinates below are the real ones from pret/pokered's map object
# data, so these tests pin the guidance to the shipped game, not to a guess.
SILPH_5F_WARPS = [
    {"x": 24, "y": 0, "destination_map": 0xD3,
     "destination_name": "Silph Co. 6F"},
    {"x": 26, "y": 0, "destination_map": 0xD1,
     "destination_name": "Silph Co. 4F"},
    {"x": 20, "y": 0, "destination_map": 0xEC,
     "destination_name": "Silph Co. Elevator"},
    {"x": 27, "y": 3, "destination_map": 0xD4,
     "destination_name": "Silph Co. 7F"},
    {"x": 9, "y": 15, "destination_map": 0xE9,
     "destination_name": "Silph Co. 9F"},
    {"x": 11, "y": 5, "destination_map": 0xD0,
     "destination_name": "Silph Co. 3F"},
]
SILPH_9F_WARPS = [
    {"x": 14, "y": 0, "destination_map": 0xEA,
     "destination_name": "Silph Co. 10F"},
    {"x": 16, "y": 0, "destination_map": 0xD5,
     "destination_name": "Silph Co. 8F"},
    {"x": 18, "y": 0, "destination_map": 0xEC,
     "destination_name": "Silph Co. Elevator"},
    {"x": 17, "y": 15, "destination_map": 0xD2,
     "destination_name": "Silph Co. 5F"},
]
SILPH_7F_WARPS = [
    {"x": 16, "y": 0, "destination_map": 0xD5,
     "destination_name": "Silph Co. 8F"},
    {"x": 22, "y": 0, "destination_map": 0xD3,
     "destination_name": "Silph Co. 6F"},
    {"x": 18, "y": 0, "destination_map": 0xEC,
     "destination_name": "Silph Co. Elevator"},
    {"x": 5, "y": 7, "destination_map": 0xEB,
     "destination_name": "Silph Co. 11F"},
    {"x": 5, "y": 3, "destination_map": 0xD0,
     "destination_name": "Silph Co. 3F"},
    {"x": 21, "y": 15, "destination_map": 0xD2,
     "destination_name": "Silph Co. 5F"},
]


def silph_state(map_id, warps=None, x=28, y=5, **key_items):
    return {
        "map_id": map_id,
        "coordinates": {"x": x, "y": y},
        "warps": warps if warps is not None else [],
        "key_items": {"card_key": False, "master_ball": False, **key_items},
    }


def test_silph_guidance_names_the_card_key_tile_on_its_own_floor():
    """The run burned 345 stuck decisions on 5F without ever being told
    the Card Key was lying on that very floor."""
    guidance = silph_co_route_guidance(silph_state(0xD2, SILPH_5F_WARPS))

    assert "(21,16)" in guidance
    assert "ONLY objective" in guidance
    # The Rocket sprite it kept walking "up" into is permanent scenery.
    assert "(28,4)" in guidance


def test_silph_guidance_routes_other_floors_to_the_lift_not_the_pads():
    guidance = silph_co_route_guidance(silph_state(0xE9, SILPH_9F_WARPS))

    assert "reach 5F" in guidance
    assert "(21,16)" in guidance
    # 9F's lift is at (18,0); 5F's is at (20,0). Hardcoding would misfire.
    assert "elevator at (18,0)" in guidance


def test_silph_guidance_calls_out_the_exact_teleport_cycle():
    """5F (9,15) and 9F (17,15) are a closed pair — the observed floor cycle."""
    fifth = silph_co_route_guidance(silph_state(0xD2, SILPH_5F_WARPS))
    ninth = silph_co_route_guidance(silph_state(0xE9, SILPH_9F_WARPS))

    assert "(9,15)->Silph Co. 9F" in fifth
    assert "(17,15)->Silph Co. 5F" in ninth
    for guidance in (fifth, ninth):
        assert "TELEPORT PADS" in guidance
        # Stairs and the lift sit at y=0 and must never be called pads.
        assert "(20,0)" not in guidance.split("TELEPORT PADS")[-1]


def test_silph_guidance_switches_to_giovanni_once_the_card_key_is_owned():
    guidance = silph_co_route_guidance(
        silph_state(0xE9, SILPH_9F_WARPS, card_key=True)
    )
    entry = silph_co_route_guidance(
        silph_state(
            0xD0,
            [{"x": 11, "y": 11, "destination_map": 0xD4,
              "destination_name": "Silph Co. 7F"}],
            card_key=True,
        )
    )
    east_seventh = silph_co_route_guidance(
        silph_state(0xD4, SILPH_7F_WARPS, x=16, y=3, card_key=True)
    )
    west_seventh = silph_co_route_guidance(
        silph_state(0xD4, SILPH_7F_WARPS, x=5, y=3, card_key=True)
    )
    east = silph_co_route_guidance(
        silph_state(0xEB, [], x=13, y=0, card_key=True)
    )
    west = silph_co_route_guidance(
        silph_state(0xEB, [], x=3, y=2, card_key=True)
    )

    assert "choose 3F" in guidance
    assert "(21,16)" not in guidance
    assert "stand at (18,8)" in entry
    assert "face LEFT" in entry
    assert "press A once" in entry
    assert "only A opens it" in entry
    assert "pad (11,11)" in entry
    assert "WRONG EAST" in east_seventh
    assert "choose 3F" in east_seventh
    assert "(18,8)" in east_seventh
    assert "CORRECT WEST" in west_seventh
    assert "pad at (5,7)" in west_seventh
    assert "SEALED EAST" in east
    assert "already defeated" in east
    assert "3F (11,11)" in east
    assert "Rocket at (3,16)" in west
    assert "Giovanni at (6,9)" in west
    assert "never walk south to check again" in west
    assert "from (5,6)" in west
    assert "UP once to (5,5)" in west
    assert "RIGHT once to (6,5)" in west
    assert "face RIGHT" in west
    assert "master_ball" in west


def test_silph_guidance_sends_you_out_once_the_building_is_cleared():
    """Re-entry must not restart the climb, the mistake the Tower once made."""
    exits = [
        {"x": 10, "y": 17, "destination_map": 0x05,
         "destination_name": "Saffron City"},
    ]
    for owned in ({"card_key": True, "master_ball": True},):
        state = silph_state(0xB5, exits, **owned)
        guidance = silph_co_route_guidance(state)
        assert "COMPLETE" in guidance
        assert "(10,17)" in guidance
        assert "reach 11F" not in guidance
        assert "ONLY objective" not in guidance

    # The Marsh Badge is gated behind clearing Silph, so it proves the same
    # thing even after the Master Ball has been spent on a legendary.
    spent = silph_state(0xB5, exits, card_key=True)
    spent["badges"] = ["Boulder", "Marsh"]
    assert "COMPLETE" in silph_co_route_guidance(spent)

    top = silph_state(
        0xEB,
        [
            {"x": 5, "y": 5, "destination_map": 0xFF},
            {"x": 3, "y": 2, "destination_map": 0xD4},
        ],
        x=6,
        y=5,
        card_key=True,
        master_ball=True,
    )
    top_guidance = silph_co_route_guidance(top)
    assert "Do NOT use (5,5)" in top_guidance
    assert "LAST_MAP sentinel" in top_guidance
    assert "11F pad (3,2)" in top_guidance
    assert "7F pad (5,3)" in top_guidance

    lift = silph_state(
        0xEC,
        [],
        card_key=True,
        master_ball=True,
    )
    assert "choose 1F" in silph_co_route_guidance(lift)

    seventh = silph_state(
        0xD4,
        SILPH_7F_WARPS,
        x=5,
        y=3,
        card_key=True,
        master_ball=True,
    )
    seventh_guidance = silph_co_route_guidance(seventh)
    assert "LEFT to (4,3)" in seventh_guidance
    assert "RIGHT back onto (5,3)" in seventh_guidance
    assert "Never press DOWN" in seventh_guidance


def test_silph_guidance_never_claims_ownership_it_cannot_read():
    state = silph_state(0xD2, SILPH_5F_WARPS)
    state["key_items"] = {"card_key": None, "master_ball": None}

    guidance = silph_co_route_guidance(state)

    assert "do not claim" in guidance
    assert "ONLY objective" not in guidance


def test_silph_guidance_is_silent_outside_the_building():
    assert silph_co_route_guidance(silph_state(0xCA, [])) is None
    assert silph_co_route_guidance(silph_state(0x92, [])) is None
    # The elevator is a separate map and must still be handled.
    assert "panel at (3,0)" in silph_co_route_guidance(silph_state(0xEC, []))


def endgame_state(map_id, badges, **key_items):
    return {
        "map_id": map_id,
        "badges": badges,
        "key_items": {"secret_key": False, **key_items},
    }


def test_endgame_guidance_routes_six_badges_to_cinnabar():
    badges = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh"]

    celadon = endgame_route_guidance(endgame_state(0x06, badges))
    fuchsia = endgame_route_guidance(endgame_state(0x07, badges))
    cinnabar = endgame_route_guidance(endgame_state(0x08, badges))
    mansion = endgame_route_guidance(endgame_state(0xD8, badges))
    mansion_off = endgame_route_guidance({
        **endgame_state(0xD8, badges),
        "mansion_switch_on": False,
    })
    mansion_north_on = endgame_route_guidance({
        **endgame_state(0xD8, badges),
        "mansion_switch_on": True,
        "coordinates": {"x": 13, "y": 6},
    })
    mansion_south_on = endgame_route_guidance({
        **endgame_state(0xD8, badges),
        "mansion_switch_on": True,
        "coordinates": {"x": 17, "y": 25},
    })
    mansion_1f = endgame_route_guidance(endgame_state(0xA5, badges))
    mansion_2f = endgame_route_guidance(endgame_state(0xD6, badges))
    mansion_3f = endgame_route_guidance(endgame_state(0xD7, badges))
    unlocked = endgame_route_guidance(
        endgame_state(0x08, badges, secret_key=True)
    )
    pallet_with_key = endgame_route_guidance(
        endgame_state(0x00, badges, secret_key=True, hm_fly=True)
    )

    assert "Fly is OPTIONAL" in celadon
    assert "Route 7" in celadon
    assert "SURF" in fuchsia
    assert "Mansion at (6,3)" in cinnabar
    assert "B1F at (5,13)" in cinnabar
    assert "southern switch at (18,25)" in mansion
    assert "northern switch at (20,3)" in mansion
    assert "SECRET KEY ball at (5,13)" in mansion
    assert "switch is OFF" in mansion_off
    assert "Do NOT return south" in mansion_off
    assert "balls at (10,2) and (19,25) are items" in mansion_off
    assert "northern statue has turned" in mansion_north_on
    assert "Do NOT touch another statue" in mansion_north_on
    assert "southern switch at (18,25)" in mansion_south_on
    assert "face UP" in mansion_south_on
    assert "do not press the southern statue twice" in mansion_south_on
    assert "1F staircase at (5,10)" in mansion_1f
    assert "B1F stairs at (21,23)" in mansion_1f
    assert "2F staircase at (6,1)" in mansion_2f
    assert "Do NOT use (7,10)" in mansion_2f
    assert "LEFT drop at (16,14) or (17,14)" in mansion_3f
    assert "rightmost drop at (19,14)" in mansion_3f
    assert "Gym at (18,3)" in unlocked
    assert "choose CINNABAR ISLAND" in pallet_with_key
    assert "depleted Surf" in pallet_with_key


def test_endgame_guidance_covers_seafoam_boulder_chains():
    badges = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh"]
    items = {"hm_surf": True, "hm_strength": True}

    first = endgame_route_guidance(
        {
            **endgame_state(0xC0, badges, **items),
            "coordinates": {"x": 4, "y": 17},
        }
    )
    west = endgame_route_guidance(
        {
            **endgame_state(0xC0, badges, **items),
            "coordinates": {"x": 26, "y": 17},
        }
    )
    basement = endgame_route_guidance(
        endgame_state(0xA1, badges, **items)
    )
    bottom = endgame_route_guidance(
        endgame_state(0xA2, badges, **items)
    )
    route20_west = endgame_route_guidance(
        {
            **endgame_state(0x1F, badges, **items),
            "coordinates": {"x": 40, "y": 15},
        }
    )
    route20_pocket = endgame_route_guidance(
        {
            **endgame_state(0x1F, badges, **items),
            "coordinates": {"x": 46, "y": 9},
        }
    )

    assert "boulders at (18,10) and (26,7)" in first
    assert "holes at (17,6) and (24,6)" in first
    assert "do NOT step down or leave" in first
    assert "CINNABAR doors at (26,17)/(27,17)" in west
    assert "native boulders at (5,14) and (3,15)" in basement
    assert "holes at (6,16) and (3,16)" in basement
    assert "Ignore Articuno" in bottom
    assert "EAST ladder at (25,4)" in bottom
    assert "CINNABAR doors at (26,17)/(27,17)" in bottom
    assert "Do not return to Seafoam" in route20_west
    assert "Seafoam cave is MANDATORY" in route20_pocket
    assert "(48,6)" in route20_pocket
    assert "Do NOT target the (58,9) door" in route20_pocket


def test_endgame_guidance_blocks_seafoam_without_strength():
    badges = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh"]
    guidance = endgame_route_guidance(
        endgame_state(0xC0, badges, hm_surf=True, hm_strength=False)
    )

    assert "HM04 STRENGTH is not owned" in guidance


def test_endgame_guidance_ascends_after_seafoam_puzzle_complete():
    badges = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh"]
    state = endgame_state(
        0xA0,
        badges,
        hm_surf=True,
        hm_strength=True,
    )
    state["seafoam_boulders"] = {
        "one_to_b1f": True,
        "b1f_to_b2f": True,
        "b2f_to_b3f": True,
        "b3f_to_b4f": True,
    }
    state["coordinates"] = {"x": 25, "y": 14}

    b2_east = endgame_route_guidance(
        {**state, "coordinates": {"x": 25, "y": 11}}
    )
    b2_west = endgame_route_guidance(
        {**state, "coordinates": {"x": 5, "y": 13}}
    )
    b3_east = endgame_route_guidance({
        **state,
        "map_id": 0xA1,
        "coordinates": {"x": 23, "y": 12},
    })
    b3_west = endgame_route_guidance({
        **state,
        "map_id": 0xA1,
        "coordinates": {"x": 8, "y": 6},
    })
    b4 = endgame_route_guidance({
        **state,
        "map_id": 0xA2,
        "coordinates": {"x": 25, "y": 4},
    })
    b1_east = endgame_route_guidance({
        **state,
        "map_id": 0x9F,
        "coordinates": {"x": 25, "y": 3},
    })
    b1_west = endgame_route_guidance({
        **state,
        "map_id": 0x9F,
        "coordinates": {"x": 4, "y": 2},
    })
    one_west = endgame_route_guidance({
        **state,
        "map_id": 0xC0,
        "coordinates": {"x": 7, "y": 5},
    })
    one_east = endgame_route_guidance({
        **state,
        "map_id": 0xC0,
        "coordinates": {"x": 26, "y": 17},
    })
    route20_middle = endgame_route_guidance({
        **state,
        "map_id": 0x1F,
        "coordinates": {"x": 58, "y": 11},
    })
    route20_west_exit = endgame_route_guidance({
        **state,
        "map_id": 0x1F,
        "coordinates": {"x": 48, "y": 6},
    })
    route16 = endgame_route_guidance({
        **state,
        "map_id": 0x1B,
        "coordinates": {"x": 12, "y": 12},
    })
    fly_house = endgame_route_guidance({
        **state,
        "map_id": 0xBC,
        "coordinates": {"x": 3, "y": 5},
    })
    fuchsia_detour = endgame_route_guidance({
        **state,
        "map_id": 0x07,
    })
    vermilion_detour = endgame_route_guidance({
        **state,
        "map_id": 0x05,
    })
    route13_detour = endgame_route_guidance({
        **state,
        "map_id": 0x18,
    })
    route8_detour = endgame_route_guidance({
        **state,
        "map_id": 0x13,
    })
    route16_gate = endgame_route_guidance({
        **state,
        "map_id": 0xBA,
    })
    fly_ready = endgame_route_guidance({
        **state,
        "map_id": 0x1B,
        "key_items": {
            **state["key_items"],
            "hm_fly": True,
        },
    })

    assert "PUZZLE IS COMPLETE" in b2_east
    assert "follow this exit chain" in b2_east
    assert "press DOWN three times" in b2_east
    assert "B2F ladder (25,14)" in b2_east
    assert "Do not use (25,3)" in b2_east
    assert "west ladder at (5,3)" in b2_west
    assert "Reach (23,9), face DOWN" in b3_east
    assert "LEFT x4, UP x2, LEFT x4" in b3_east
    assert "B2F's west side at (5,13)" in b3_east
    assert "west ladder at (5,12)" in b3_west
    assert "B4F east ladder (25,4)" in b4
    assert "B3F Surf crossing" in b4
    assert "lower-right 1F stair landing" in b1_east
    assert "press UP x4" in b1_east
    assert "RIGHT x2" in b1_east
    assert "B1F ladder (25,11)" in b1_east
    assert "west ladder at (7,5)" in b1_west
    assert "western 1F component" in one_west
    assert "doors (4,17)/(5,17)" in one_west
    assert "lower-right stair at (23,15)" in one_east
    assert "UP x4, RIGHT x2" in one_east
    assert "Surf west" in one_east
    assert "Authoritative Pallet bypass" in route20_middle
    assert "Travel EAST across Route 20" in route20_middle
    assert "do not enter Seafoam again" in route20_west_exit
    assert "Fly House entrance at (7,5)" in route16
    assert "brunette girl at (2,3)" in fly_house
    assert "receive HM02 FLY" in fly_house
    assert "Fuchsia EAST onto Route 15" in fuchsia_detour
    assert "no-Bicycle route" in fuchsia_detour
    assert "Do not detour for the Bicycle Voucher" in vermilion_detour
    assert "Vermilion NORTH onto Route 6" in vermilion_detour
    assert "verified Route 13 fence path" in route13_detour
    assert "(14,4), (24,4), (24,6)" in route13_detour
    assert "(50,6), and (51,6)" in route13_detour
    assert "Route 8 directly into Saffron" in route8_detour
    assert "skip Underground Path" in route8_detour
    assert "WEST exits at (0,2)/(0,3)" in route16_gate
    assert "Fly House side" in route16_gate
    assert "Teach HM02 FLY to DODUO" in fly_ready
    assert "choose PALLET TOWN" in fly_ready
    assert trusted_story_route_action({
        **state,
        "map_id": 0xC0,
        "coordinates": {"x": 24, "y": 15},
    }) == "left"
    assert trusted_story_route_action({
        **state,
        "map_id": 0x9F,
        "coordinates": {"x": 23, "y": 15},
    }) == "up"
    assert trusted_story_route_action({
        **state,
        "map_id": 0x9F,
        "coordinates": {"x": 25, "y": 11},
    }) == "left"
    assert trusted_story_route_action({
        **state,
        "map_id": 0xA0,
        "coordinates": {"x": 25, "y": 13},
    }) == "down"
    assert trusted_story_route_action({
        **state,
        "map_id": 0xA1,
        "coordinates": {"x": 22, "y": 3},
    }) == "down"
    assert trusted_story_route_action({
        **state,
        "map_id": 0xA1,
        "coordinates": {"x": 24, "y": 4},
    }) == "right"
    assert trusted_story_route_action({
        **state,
        "map_id": 0xA1,
        "coordinates": {"x": 25, "y": 6},
    }) == "left"
    assert trusted_story_route_action({
        **state,
        "map_id": 0xA1,
        "coordinates": {"x": 25, "y": 7},
    }) == "left"
    assert trusted_story_route_action({
        **state,
        "map_id": 0xA1,
        "coordinates": {"x": 23, "y": 10},
    }) == "left"
    assert trusted_story_route_action({
        **state,
        "map_id": 0xA1,
        "coordinates": {"x": 19, "y": 10},
    }) == "up"
    assert trusted_story_route_action({
        **state,
        "map_id": 0xA1,
        "coordinates": {"x": 6, "y": 12},
    }) == "left"
    assert trusted_story_route_action({
        **state,
        "screen_text": "Wild encounter",
    }) is None


def test_endgame_guidance_enforces_seafoam_stage_order():
    badges = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh"]
    state = endgame_state(
        0xA0,
        badges,
        hm_surf=True,
        hm_strength=True,
    )
    state["seafoam_boulders"] = {
        "one_to_b1f": False,
        "b1f_to_b2f": False,
        "b2f_to_b3f": False,
        "b3f_to_b4f": False,
    }

    guidance = endgame_route_guidance(state)

    assert "first 1F boulder pair is INCOMPLETE" in guidance
    assert "Use an ESCAPE ROPE" in guidance
    assert "select DIGLETT and use DIG" in guidance
    assert "Route 20 door (48,5)" in guidance
    assert "holes at (19,6)" not in guidance


def test_endgame_guidance_uses_b1f_holes_for_separate_b2f_chambers():
    badges = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh"]
    state = endgame_state(
        0x9F,
        badges,
        hm_surf=True,
        hm_strength=True,
    )
    state["seafoam_boulders"] = {
        "one_to_b1f": True,
        "b1f_to_b2f": True,
        "b2f_to_b3f": False,
        "b3f_to_b4f": False,
    }
    state["seafoam_boulder_events"] = {
        "b2f_to_b3f_1": False,
        "b2f_to_b3f_2": False,
    }

    guidance = endgame_route_guidance(state)

    assert "B1F (12,6)" in guidance
    assert "NORTH to (12,2)" in guidance
    assert "SOUTH to (17,6)" in guidance
    assert "RIGHT into completed hole (18,6)" in guidance
    assert "RIGHT into B2F hole (19,6)" in guidance

    state["seafoam_boulder_events"]["b2f_to_b3f_1"] = True
    guidance = endgame_route_guidance(state)
    assert "first B2F boulder is COMPLETE" in guidance
    assert "ladder (7,5)" in guidance
    assert "east ladder at (25,3)" in guidance
    assert "hole (23,6)" in guidance


def test_endgame_guidance_routes_to_final_b3f_boulder_stage():
    badges = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh"]
    progress = {
        "one_to_b1f": True,
        "b1f_to_b2f": True,
        "b2f_to_b3f": True,
        "b3f_to_b4f": False,
    }
    items = {"hm_surf": True, "hm_strength": True}

    b1 = endgame_state(0x9F, badges, **items)
    b1["seafoam_boulders"] = progress
    b1_east = endgame_state(0x9F, badges, **items)
    b1_east["seafoam_boulders"] = progress
    b1_east["coordinates"] = {"x": 22, "y": 11}
    b2 = endgame_state(0xA0, badges, **items)
    b2["seafoam_boulders"] = progress
    b2_east = endgame_state(0xA0, badges, **items)
    b2_east["seafoam_boulders"] = progress
    b2_east["coordinates"] = {"x": 26, "y": 10}
    b3 = endgame_state(0xA1, badges, **items)
    b3["seafoam_boulders"] = progress
    b3_after_first = endgame_state(0xA1, badges, **items)
    b3_after_first["seafoam_boulders"] = progress
    b3_after_first["seafoam_boulder_events"] = {
        "b3f_to_b4f_1": True,
        "b3f_to_b4f_2": False,
    }
    b4 = endgame_state(0xA2, badges, **items)
    b4["seafoam_boulders"] = progress

    assert "western B1F landing (7,5)" in endgame_route_guidance(b1)
    assert "(5,14), (9,14), (9,8)" in endgame_route_guidance(b1)
    assert "completed hole (18,6)" in endgame_route_guidance(b1)
    assert "disconnected east chamber" in endgame_route_guidance(b1_east)
    assert "DIGLETT's DIG inside" in endgame_route_guidance(b1_east)
    assert "B2F (19,7)" in endgame_route_guidance(b2)
    assert "Press UP once" in endgame_route_guidance(b2)
    assert "Never use hole (22,6)" in endgame_route_guidance(b2)
    assert "disconnected east platform" in endgame_route_guidance(b2_east)
    assert "ladder (25,11) to B1F" in endgame_route_guidance(b2_east)
    assert "current is STOPPED" in endgame_route_guidance(b3)
    assert "(16,17), (8,17), (8,15)" in endgame_route_guidance(b3)
    assert "LEFT six separate times" in endgame_route_guidance(b3)
    assert "Hole (3,16) is complete" in endgame_route_guidance(b3_after_first)
    assert "UP x4" in endgame_route_guidance(b3_after_first)
    assert "blocker at (8,14)" in endgame_route_guidance(b3_after_first)
    assert "LEFT x4" in endgame_route_guidance(b3_after_first)
    assert "DOWN x2" in endgame_route_guidance(b3_after_first)
    assert "east ladder at (25,4)" in endgame_route_guidance(b4)


def test_endgame_guidance_recovers_stage_four_from_route20():
    badges = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh"]
    state = endgame_state(
        0x1F,
        badges,
        hm_surf=True,
        hm_strength=True,
    )
    state["seafoam_boulders"] = {
        "one_to_b1f": True,
        "b1f_to_b2f": True,
        "b2f_to_b3f": True,
        "b3f_to_b4f": False,
    }

    guidance = endgame_route_guidance(state)

    assert "Do not use Fly" in guidance
    assert "(62,5)" in guidance
    assert "(55,5)" in guidance
    assert "(48,6)" in guidance
    assert "door (48,5)" in guidance
    assert "1F ladder (7,5)" in guidance
    assert "B1F hole (18,6)" in guidance
    assert "B2F hole (19,6)" in guidance


def test_endgame_guidance_digs_out_of_route20_middle_basin():
    badges = ["Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh"]
    state = endgame_state(
        0x1F,
        badges,
        hm_surf=True,
        hm_strength=True,
    )
    state["coordinates"] = {"x": 56, "y": 10}
    state["seafoam_boulders"] = {
        "one_to_b1f": True,
        "b1f_to_b2f": True,
        "b2f_to_b3f": True,
        "b3f_to_b4f": False,
    }

    guidance = endgame_route_guidance(state)

    assert "middle basin" in guidance
    assert "DIG is rejected outdoors" in guidance
    assert "east Seafoam door at (58,9)" in guidance
    assert "use DIG from INSIDE" in guidance
    assert "three boulder stages are saved" in guidance
    assert "(48,5) door" in guidance


def test_endgame_guidance_routes_volcano_to_earth_badge():
    badges = [
        "Boulder", "Cascade", "Thunder", "Rainbow",
        "Soul", "Marsh", "Volcano",
    ]

    assert "SURFING NORTH" in endgame_route_guidance(
        endgame_state(0x08, badges, secret_key=True)
    )
    assert "choose VIRIDIAN CITY" in endgame_route_guidance(
        endgame_state(
            0x08,
            badges,
            secret_key=True,
            hm_fly=True,
        )
    )
    assert "Leave Cinnabar Gym" in endgame_route_guidance(
        endgame_state(0xA6, badges, secret_key=True, hm_fly=True)
    )
    assert "Gym at (32,7)" in endgame_route_guidance(
        endgame_state(0x01, badges, secret_key=True)
    )
    assert "Giovanni at (2,1)" in endgame_route_guidance(
        endgame_state(0x2D, badges, secret_key=True)
    )
    assert trusted_story_route_action({
        **endgame_state(0x2D, badges, secret_key=True),
        "coordinates": {"x": 15, "y": 7},
    }) == "left"
    assert trusted_story_route_action({
        **endgame_state(0x2D, badges, secret_key=True),
        "coordinates": {"x": 18, "y": 11},
    }) == "right"
    assert trusted_story_route_action({
        **endgame_state(0x2D, badges, secret_key=True),
        "coordinates": {"x": 4, "y": 1},
    }) == "left"


def test_endgame_guidance_routes_eight_badges_to_hall_of_fame():
    badges = list(pokemon_module.BADGE_NAMES)
    low_party = [{"nickname": "BLASTOISE", "hp": 44, "max_hp": 230}]

    route22 = endgame_route_guidance(
        endgame_state(0x21, badges, secret_key=True)
    )
    assert "League gate" in route22
    assert "(8,5)" in route22
    assert "ledge-safe path" in route22
    assert "(33,14), (33,8), (31,8)" in route22
    assert "(5,11), (5,9), (11,9)" in route22
    assert "FLY to VIRIDIAN CITY" in endgame_route_guidance({
        **endgame_state(
            0x21,
            badges,
            secret_key=True,
            hm_fly=True,
        ),
        "party": low_party,
    })
    assert "Heal the party" in endgame_route_guidance({
        **endgame_state(0x01, badges, secret_key=True),
        "party": low_party,
    })
    assert "Victory Road" in endgame_route_guidance(
        endgame_state(0xC2, badges, secret_key=True)
    )
    upper_route23 = endgame_route_guidance({
        **endgame_state(0x22, badges, secret_key=True),
        "coordinates": {"x": 14, "y": 32},
    })
    assert "Victory Road is complete" in upper_route23
    assert "(18,32), (18,20), (14,20)" in upper_route23
    assert "continue NORTH into Indigo Plateau" in upper_route23
    victory_road_closed = endgame_route_guidance({
        **endgame_state(0x6C, badges, secret_key=True),
        "victory_road_1_switch_on": False,
        "strength_active": True,
    })
    victory_road_strength_reset = endgame_route_guidance({
        **endgame_state(0x6C, badges, secret_key=True),
        "victory_road_1_switch_on": False,
        "strength_active": False,
    })
    victory_road_open = endgame_route_guidance({
        **endgame_state(0x6C, badges, secret_key=True),
        "victory_road_1_switch_on": True,
    })
    victory_road_deadlocked = endgame_route_guidance({
        **endgame_state(0x6C, badges, secret_key=True),
        "victory_road_1_switch_on": False,
        "victory_road_1_boulder": {"x": 5, "y": 14},
    })
    victory_road_ladder_recovery = endgame_route_guidance({
        **endgame_state(0x6C, badges, secret_key=True),
        "victory_road_1_switch_on": False,
        "strength_active": True,
        "coordinates": {"x": 1, "y": 1},
    })
    victory_road_far_side = endgame_route_guidance({
        **endgame_state(0x6C, badges, secret_key=True),
        "victory_road_1_switch_on": False,
        "strength_active": True,
        "coordinates": {"x": 7, "y": 8},
    })
    assert "switch event is FALSE" in victory_road_closed
    assert "switch (17,13)" in victory_road_closed
    assert "STRENGTH reset" in victory_road_strength_reset
    assert "strength_active is true" in victory_road_strength_reset
    assert "dead-end at (5,14)" in victory_road_deadlocked
    assert "south exit at (8,17)/(9,17)" in victory_road_deadlocked
    assert "far side at the (1,1) 2F ladder" in victory_road_ladder_recovery
    assert "RIGHT off (1,1), then LEFT" in victory_road_ladder_recovery
    assert "already inside the northwest passage" in victory_road_far_side
    assert "trusted far-side route" in victory_road_far_side
    assert trusted_story_route_action({
        **endgame_state(0x6C, badges, secret_key=True),
        "victory_road_1_switch_on": False,
        "strength_active": True,
        "coordinates": {"x": 7, "y": 8},
    }) == "left"
    assert trusted_story_route_action({
        **endgame_state(0x6C, badges, secret_key=True),
        "victory_road_1_switch_on": False,
        "strength_active": True,
        "coordinates": {"x": 1, "y": 1},
    }) == "right"
    assert trusted_story_route_action({
        **endgame_state(0x6C, badges, secret_key=True),
        "victory_road_1_switch_on": False,
        "strength_active": True,
        "victory_road_1_boulder": {"x": 5, "y": 15},
        "coordinates": {"x": 14, "y": 13},
    }) == "down"
    assert trusted_story_route_action({
        **endgame_state(0x6C, badges, secret_key=True),
        "victory_road_1_switch_on": False,
        "strength_active": True,
        "victory_road_1_boulder": {"x": 5, "y": 16},
        "coordinates": {"x": 4, "y": 16},
    }) == "right"
    assert trusted_story_route_action({
        **endgame_state(0x6C, badges, secret_key=True),
        "victory_road_1_switch_on": False,
        "strength_active": True,
        "victory_road_1_boulder": {"x": 17, "y": 12},
        "coordinates": {"x": 17, "y": 11},
    }) == "down"
    assert "northwest passage is open" in victory_road_open
    assert "(11,14), (9,14), (9,16)" in victory_road_open
    assert "(7,8), (3,8), (3,5)" in victory_road_open
    assert "2F ladder at (1,1)" in victory_road_open
    victory_road_2_closed = endgame_route_guidance({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": False, "two": False},
        "victory_road_2_boulders": [
            {"x": 4, "y": 14},
            {"x": 5, "y": 5},
            {"x": 23, "y": 16},
        ],
        "strength_active": True,
    })
    victory_road_far_side = endgame_route_guidance({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": False, "two": False},
        "coordinates": {"x": 28, "y": 7},
    })
    victory_road_2_open = endgame_route_guidance({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": False},
        "strength_active": True,
    })
    assert "Ignore the optional boulders" in victory_road_2_closed
    assert "route start at (7,14)" in victory_road_2_closed
    assert "already beside the exterior exit" in victory_road_far_side
    assert "EAST through (29,7)/(29,8)" in victory_road_far_side
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": False, "two": False},
        "coordinates": {"x": 28, "y": 7},
    }) == "right"
    assert "Switch one is ON" in victory_road_2_open
    assert "(28,16), (28,11), (23,11)" in victory_road_2_open
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": False},
        "strength_active": True,
        "coordinates": {"x": 3, "y": 16},
    }) == "up"
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": False},
        "strength_active": True,
        "coordinates": {"x": 15, "y": 16},
    }) == "right"
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": False},
        "strength_active": True,
        "coordinates": {"x": 23, "y": 8},
    }) == "up"
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": False},
        "strength_active": True,
        "coordinates": {"x": 23, "y": 7},
    }) == "left"
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": False},
        "strength_active": True,
        "coordinates": {"x": 22, "y": 7},
    }) == "right"
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": False, "two": False},
        "victory_road_2_boulders": [{"x": 4, "y": 14}],
        "strength_active": True,
        "coordinates": {"x": 7, "y": 14},
    }) == "left"
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": False, "two": False},
        "victory_road_2_boulders": [{"x": 2, "y": 16}],
        "strength_active": True,
        "coordinates": {"x": 3, "y": 16},
    }) == "left"
    victory_road_final_inactive = endgame_route_guidance({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": False},
        "victory_road_3_events": {
            "switch": True,
            "hole_boulder": True,
        },
        "strength_active": False,
    })
    victory_road_final = endgame_route_guidance({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": False},
        "victory_road_3_events": {
            "switch": True,
            "hole_boulder": True,
        },
        "strength_active": True,
    })
    victory_road_exit = endgame_route_guidance({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": True},
        "strength_active": True,
    })
    assert "Activate BLASTOISE's STRENGTH" in victory_road_final_inactive
    assert "DOWN x5 and LEFT x4" in victory_road_final
    assert "switch (9,16)" in victory_road_final
    assert "Both 2F switches are ON" in victory_road_exit
    assert "(25,14)" in victory_road_exit
    assert "(26,8)" in victory_road_exit
    assert "final exit at (29,7)/(29,8)" in victory_road_exit
    victory_road_3_exit = endgame_route_guidance({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": True},
        "victory_road_3_events": {
            "switch": True,
            "hole_boulder": True,
        },
    })
    assert "reach warp (26,8)" in victory_road_3_exit
    assert "walk EAST through exit" in victory_road_3_exit
    assert trusted_story_route_action({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": True},
        "coordinates": {"x": 22, "y": 7},
    }) == "right"
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": True},
        "coordinates": {"x": 23, "y": 7},
    }) == "down"
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": True},
        "coordinates": {"x": 24, "y": 14},
    }) == "right"
    assert trusted_story_route_action({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": True},
        "coordinates": {"x": 27, "y": 8},
    }) == "left"
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": True},
        "coordinates": {"x": 28, "y": 8},
    }) == "right"
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": False},
        "victory_road_2_boulders": [
            {"x": 1, "y": 16},
            {"x": 5, "y": 5},
            {"x": 23, "y": 16},
        ],
        "victory_road_3_events": {
            "switch": True,
            "hole_boulder": True,
        },
        "strength_active": True,
        "coordinates": {"x": 28, "y": 11},
    }) == "down"
    assert trusted_story_route_action({
        **endgame_state(0xC2, badges, secret_key=True),
        "victory_road_2_switches": {"one": True, "two": False},
        "victory_road_2_boulders": [
            {"x": 1, "y": 16},
            {"x": 5, "y": 5},
            {"x": 23, "y": 16},
        ],
        "victory_road_3_events": {
            "switch": True,
            "hole_boulder": True,
        },
        "strength_active": True,
        "coordinates": {"x": 24, "y": 16},
    }) == "left"
    victory_road_3_dead_end = endgame_route_guidance({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_3_events": {
            "switch": False,
            "hole_boulder": False,
        },
        "victory_road_3_boulders": [
            {"x": 22, "y": 3},
            {"x": 13, "y": 12},
            {"x": 24, "y": 10},
            {"x": 22, "y": 15},
        ],
        "coordinates": {"x": 7, "y": 2},
    })
    victory_road_3_switch = endgame_route_guidance({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_3_events": {
            "switch": True,
            "hole_boulder": False,
        },
    })
    victory_road_3_strength_reset = endgame_route_guidance({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_3_events": {
            "switch": False,
            "hole_boulder": False,
        },
        "strength_active": False,
        "coordinates": {"x": 23, "y": 7},
    })
    assert "dead-end (2,0) 3F pocket" in victory_road_3_dead_end
    assert "Use DIGLETT's DIG" in victory_road_3_dead_end
    assert "boulder four at (22,15)" in victory_road_3_switch
    assert "hole (23,15)" in victory_road_3_switch
    assert "DOWN, LEFT x3, DOWN x2" in victory_road_3_switch
    assert "Activate BLASTOISE's STRENGTH" in victory_road_3_strength_reset
    assert "UP x4, LEFT x4" in victory_road_3_strength_reset
    victory_road_3_moved = endgame_route_guidance({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_3_events": {
            "switch": False,
            "hole_boulder": False,
        },
        "victory_road_3_boulders": [{"x": 8, "y": 3}],
        "coordinates": {"x": 7, "y": 2},
    })
    assert "LEFT x27" in victory_road_3_moved
    assert "never Dig after boulder one moves" in victory_road_3_moved
    assert trusted_story_route_action({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_3_events": {
            "switch": False,
            "hole_boulder": False,
        },
        "victory_road_3_boulders": [{"x": 20, "y": 3}],
        "strength_active": True,
        "coordinates": {"x": 21, "y": 3},
    }) == "down"
    assert trusted_story_route_action({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_3_events": {
            "switch": False,
            "hole_boulder": False,
        },
        "victory_road_3_boulders": [{"x": 22, "y": 3}],
        "strength_active": True,
        "coordinates": {"x": 23, "y": 7},
    }) == "up"
    assert trusted_story_route_action({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_3_events": {
            "switch": False,
            "hole_boulder": False,
        },
        "victory_road_3_boulders": [{"x": 22, "y": 3}],
        "strength_active": True,
        "coordinates": {"x": 23, "y": 3},
    }) == "left"
    assert trusted_story_route_action({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_3_events": {
            "switch": False,
            "hole_boulder": False,
        },
        "victory_road_3_boulders": [{"x": 2, "y": 5}],
        "strength_active": True,
        "coordinates": {"x": 1, "y": 5},
    }) == "right"
    assert trusted_story_route_action({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_3_events": {
            "switch": True,
            "hole_boulder": False,
        },
        "victory_road_3_boulders": [
            {"x": 3, "y": 5},
            {"x": 13, "y": 12},
            {"x": 24, "y": 10},
            {"x": 22, "y": 15},
        ],
        "strength_active": True,
        "coordinates": {"x": 20, "y": 10},
    }) == "up"
    assert trusted_story_route_action({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_3_events": {
            "switch": True,
            "hole_boulder": False,
        },
        "victory_road_3_boulders": [
            {"x": 3, "y": 5},
            {"x": 13, "y": 12},
            {"x": 24, "y": 10},
            {"x": 22, "y": 15},
        ],
        "strength_active": True,
        "coordinates": {"x": 23, "y": 7},
    }) is None
    assert trusted_story_route_action({
        **endgame_state(0xC6, badges, secret_key=True),
        "victory_road_3_events": {
            "switch": True,
            "hole_boulder": False,
        },
        "victory_road_3_boulders": [
            {"x": 3, "y": 5},
            {"x": 13, "y": 12},
            {"x": 24, "y": 10},
            {"x": 22, "y": 15},
        ],
        "strength_active": True,
        "coordinates": {"x": 21, "y": 15},
    }) == "right"
    assert "Lorelei" in endgame_route_guidance(
        endgame_state(0xAE, badges, secret_key=True)
    )
    assert "Hall of Fame" in endgame_route_guidance(
        endgame_state(0x78, badges, secret_key=True)
    )
    assert endgame_route_guidance(
        endgame_state(0x06, ["Boulder"], secret_key=False)
    ) is None


def test_postgame_guidance_routes_to_master_ball_mewtwo_capture():
    completed = {
        **endgame_state(
            0x76,
            [],
            hm_fly=True,
            hm_surf=True,
            master_ball=True,
        ),
        "completed": True,
        "hall_of_fame": True,
        "mewtwo_caught": False,
        "mewtwo_encounter_resolved": False,
    }

    assert "choose CONTINUE" in endgame_route_guidance(completed)
    assert "Do not choose NEW GAME" in endgame_route_guidance(completed)
    assert "cave warp at (4,11)" in endgame_route_guidance({
        **completed,
        "map_id": 0x03,
        "hall_of_fame": False,
    })
    route24 = endgame_route_guidance({
        **completed,
        "map_id": 0x23,
        "hall_of_fame": False,
    })
    assert "Cross Nugget Bridge" in route24
    assert "Travel SOUTH" in route24
    assert "safe shoreline tile (5,16)" in route24
    assert "cursor from DODUO to BLASTOISE" in route24
    assert trusted_story_route_action({
        **completed,
        "map_id": 0x23,
        "hall_of_fame": False,
        "hall_of_fame_completed": True,
        "coordinates": {"x": 11, "y": 24},
    }) == "up"
    assert trusted_story_route_action({
        **completed,
        "map_id": 0x23,
        "hall_of_fame": False,
        "hall_of_fame_completed": True,
        "coordinates": {"x": 7, "y": 14},
    }) == "down"
    assert trusted_story_route_action({
        **completed,
        "map_id": 0x23,
        "hall_of_fame": False,
        "hall_of_fame_completed": True,
        "coordinates": {"x": 6, "y": 15},
    }) == "left"
    assert trusted_story_route_action({
        **completed,
        "map_id": 0x23,
        "hall_of_fame": False,
        "hall_of_fame_completed": True,
        "coordinates": {"x": 5, "y": 15},
    }) == "down"
    assert "water west of Nugget Bridge" in endgame_route_guidance({
        **completed,
        "map_id": 0x24,
        "hall_of_fame": False,
    })
    assert "ladder (23,7)" in endgame_route_guidance({
        **completed,
        "map_id": 0xE4,
        "hall_of_fame": False,
        "coordinates": {"x": 24, "y": 17},
    })
    assert "ladder (29,1)" in endgame_route_guidance({
        **completed,
        "map_id": 0xE2,
        "hall_of_fame": False,
        "coordinates": {"x": 22, "y": 6},
    })
    assert "trusted coordinate route" in endgame_route_guidance({
        **completed,
        "map_id": 0xE4,
        "hall_of_fame": False,
        "coordinates": {"x": 18, "y": 9},
    })
    assert "ladder (1,3)" in endgame_route_guidance({
        **completed,
        "map_id": 0xE2,
        "hall_of_fame": False,
        "coordinates": {"x": 3, "y": 11},
    })
    mewtwo = endgame_route_guidance({
        **completed,
        "map_id": 0xE3,
        "hall_of_fame": False,
        "coordinates": {"x": 27, "y": 14},
    })
    assert "Mewtwo at (27,13)" in mewtwo
    assert "MASTER BALL immediately" in mewtwo
    assert "NEVER ATTACK" in mewtwo
    assert "Dex 150 ownership" in mewtwo
    surf_state = {
        **completed,
        "map_id": 0xE4,
        "hall_of_fame": False,
        "hall_of_fame_completed": True,
        "coordinates": {"x": 23, "y": 3},
        "screen_text": "",
        "surfing": False,
        "party": [{"nickname": "BLASTOISE"}],
    }
    assert trusted_mewtwo_surf_buttons(surf_state) == [
        "down",
        "start",
    ]
    assert trusted_mewtwo_surf_buttons({
        **surf_state,
        "screen_text": (
            "POKDEX | POKMON | ITEM | RED | SAVE | OPTION | EXIT"
        ),
        "menu_cursor_index": 0,
    }) == ["down"]
    assert trusted_mewtwo_surf_buttons({
        **surf_state,
        "screen_text": "BLASTOISE | ODDISH | Choose a POKMON.",
        "menu_cursor_index": 0,
    }) == ["a"]
    assert trusted_mewtwo_surf_buttons({
        **surf_state,
        "screen_text": "SURF | STRENGTH | STATS | SWITCH | CANCEL",
        "menu_cursor_index": 0,
    }) == ["a", "a"]
    assert trusted_mewtwo_surf_buttons({
        **surf_state,
        "surfing": True,
    }) is None
    capture_state = {
        **completed,
        "map_id": 0xE3,
        "hall_of_fame": False,
        "hall_of_fame_completed": True,
        "coordinates": {"x": 27, "y": 14},
        "screen_text": "MEWTWO 70 | FIGHT | ITEM RUN",
        "in_battle": True,
        "enemy_species_id": 0x83,
        "menu_cursor_index": 0,
        "master_ball_bag_index": 15,
    }
    assert trusted_mewtwo_capture_buttons(capture_state) == ["down", "a"]
    assert trusted_mewtwo_capture_buttons({
        **capture_state,
        "screen_text": "TOWN MAP | HELIX FOSSIL | S.S.TICKET | HM01",
    }) == ["down"]
    assert trusted_mewtwo_capture_buttons({
        **capture_state,
        "screen_text": "HM04 | CARD KEY | MASTER BALL | HM02",
        "menu_cursor_index": 15,
    }) == ["a"]
    assert trusted_mewtwo_capture_buttons({
        **capture_state,
        "enemy_species_id": 0x2D,
    }) is None
    finalize_state = {
        **capture_state,
        "mewtwo_caught": True,
        "in_battle": True,
        "screen_text": "YES | NO | give a nickname | to MEWTWO?",
    }
    assert trusted_mewtwo_finalize_buttons(finalize_state) == ["down", "a"]
    assert trusted_mewtwo_finalize_buttons({
        **finalize_state,
        "in_battle": False,
        "mewtwo_encounter_resolved": True,
        "screen_text": "POKDEX | POKMON | ITEM | RED | SAVE | OPTION | EXIT",
        "menu_cursor_index": 0,
    }) == ["down"]
    assert trusted_mewtwo_finalize_buttons({
        **finalize_state,
        "in_battle": False,
        "mewtwo_encounter_resolved": True,
        "screen_text": "YES | NO | Would you like to SAVE the game?",
        "menu_cursor_index": 0,
    }) == ["a"]
    assert trusted_mewtwo_finalize_buttons({
        **finalize_state,
        "in_battle": False,
        "mewtwo_encounter_resolved": True,
        "screen_text": "RED saved | the game!",
    }) is None
    wild_state = {
        **capture_state,
        "map_id": 0xE2,
        "coordinates": {"x": 19, "y": 13},
        "enemy_species_id": 0x2D,
    }
    assert trusted_cerulean_cave_flee_buttons(wild_state) == [
        "down",
        "right",
        "a",
    ]
    assert trusted_cerulean_cave_flee_buttons({
        **wild_state,
        "menu_cursor_index": 3,
    }) == ["a"]
    assert trusted_cerulean_cave_flee_buttons({
        **wild_state,
        "map_id": 0xE3,
        "coordinates": {"x": 27, "y": 14},
    }) is None
    assert trusted_story_route_action({
        **completed,
        "map_id": 0xE4,
        "hall_of_fame": False,
        "hall_of_fame_completed": True,
        "coordinates": {"x": 21, "y": 11},
    }) == "up"
    assert trusted_story_route_action({
        **completed,
        "map_id": 0xE3,
        "hall_of_fame": False,
        "hall_of_fame_completed": True,
        "coordinates": {"x": 27, "y": 8},
    }) == "down"
    assert "static Mewtwo encounter is resolved" in endgame_route_guidance({
        **completed,
        "hall_of_fame": False,
        "mewtwo_encounter_resolved": True,
    })
    assert "MEWTWO is caught" in endgame_route_guidance({
        **completed,
        "hall_of_fame": False,
        "mewtwo_caught": True,
        "mewtwo_encounter_resolved": True,
    })


def test_collision_warp_tile_stays_probeable_after_a_wall_bump(tmp_path):
    """A Gen 1 elevator mat only fires when you walk INTO the closed doors.

    The first press reads as a wall bump, and `tried` is never cleared, so
    without a warp-tile exemption the one input that leaves the floor is
    suppressed forever — the Rocket Hideout B4F closed loop.
    """
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    mat = (0xCA, 24, 15)
    plain = (0xCA, 24, 14)
    now = datetime.now(timezone.utc)

    for origin in (mat, plain):
        memory.begin(origin, ["down"], phase="overworld")
        memory.finish(origin, now=now)

    def directions(frontier, tile):
        return {
            entry["direction"]
            for entry in frontier
            if entry["origin"] == [tile[1], tile[2]]
        }

    suppressed = memory.untried_frontier(mat)
    assert "down" not in directions(suppressed, mat)

    memory.observe_warps(
        0xCA, [{"x": 24, "y": 15, "destination_map": 0xCB}]
    )
    exempt = memory.untried_frontier(mat)

    assert "down" in directions(exempt, mat)
    # Only the warp tile is exempt; ordinary wall bumps stay suppressed.
    assert "down" not in directions(exempt, plain)


def test_observe_warps_replaces_only_the_reloaded_map(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    memory.observe_warps(0xCA, [{"x": 24, "y": 15}])
    memory.observe_warps(0xC7, [{"x": 21, "y": 2}])
    memory.observe_warps(0xCA, [{"x": 25, "y": 15}])

    assert memory.warp_tiles == {(0xC7, 21, 2), (0xCA, 25, 15)}


def test_navigation_trail_does_not_turn_one_failed_step_into_a_cycle(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    a = (0xC9, 15, 11)
    b = (0xC9, 16, 11)
    now = datetime.now(timezone.utc)

    memory.begin(a, ["right"], phase="overworld")
    memory.finish(b, now=now)
    memory.begin(b, ["right"], phase="overworld")
    memory.finish(b, now=now)

    assert memory.trail == [a, b]
    assert memory.guidance(b) is None


def test_navigation_memory_does_not_cycle_with_distinct_steps_in_one_zone(
    tmp_path,
):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    positions = [
        (0xC9, 0, 0),
        (0xC9, 1, 0),
        (0xC9, 2, 0),
        (0xC9, 2, 1),
    ]
    for origin, destination in zip(positions, positions[1:], strict=False):
        memory.begin(origin, ["right"], phase="overworld")
        memory.finish(destination, now=now)
    assert memory.guidance(positions[-1]) is None


def test_navigation_memory_discards_expired_attempts_and_trail(tmp_path):
    old = datetime.now(timezone.utc) - timedelta(hours=3)
    path = tmp_path / "navigation-memory.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": pokemon_module.NAVIGATION_MEMORY_SCHEMA_VERSION,
                "updated_at": old.isoformat(),
                "attempts": [
                    {
                        "map_id": 0xC9,
                        "origin": [15, 11],
                        "buttons": ["right"],
                        "outcome": "no_progress",
                        "count": 4,
                        "last_at": old.isoformat(),
                    }
                ],
                "trail": [[0xC9, 15, 11]] * 4,
            }
        ),
        encoding="utf-8",
    )

    memory = NavigationMemory(path)

    assert memory.guidance((0xC9, 15, 11)) is None
    assert memory.trail == []


def test_navigation_memory_detects_cross_floor_cycle_and_survives_reload(
    tmp_path,
):
    path = tmp_path / "navigation-memory.json"
    memory = NavigationMemory(path)
    now = datetime.now(timezone.utc)
    transitions = [
        ((0xC7, 23, 3), (0xC8, 27, 8)),
        ((0xC8, 27, 8), (0xC7, 23, 3)),
        ((0xC7, 23, 3), (0xC8, 27, 8)),
        ((0xC8, 27, 8), (0xC7, 23, 3)),
    ]
    for origin, destination in transitions:
        memory.begin(origin, ["up"], phase="overworld")
        memory.finish(destination, now=now)

    guidance = memory.guidance((0xC7, 23, 3))
    reloaded = NavigationMemory(path)

    assert guidance["loop_detected"] is True
    assert guidance["loop_kind"] == "cross_floor_cycle"
    assert guidance["cycle_maps"] == [0xC7, 0xC8]
    assert reloaded.floor_trail[-4:] == [0xC8, 0xC7, 0xC8, 0xC7]


def test_navigation_memory_migrates_v2_schema_without_discarding(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "navigation-memory.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "updated_at": now.isoformat(),
                "attempts": [
                    {
                        "map_id": 0xC9,
                        "origin": [15, 11],
                        "buttons": ["right"],
                        "outcome": "no_progress",
                        "count": 1,
                        "last_at": now.isoformat(),
                    }
                ],
                "trail": [[0xC9, 15, 11], [0xC9, 16, 11]],
                "floor_trail": [0xC9],
            }
        ),
        encoding="utf-8",
    )

    memory = NavigationMemory(path)

    assert len(memory.attempts) == 1
    assert memory.trail == [(0xC9, 15, 11), (0xC9, 16, 11)]
    assert memory.transitions == []
    assert memory.episode is None

    memory.begin((0xC9, 16, 11), ["down"], phase="overworld")
    memory.finish((0xC9, 16, 12), now=now)
    value = json.loads(path.read_text(encoding="utf-8"))

    assert (
        value["schema_version"]
        == pokemon_module.NAVIGATION_MEMORY_SCHEMA_VERSION
    )
    assert value["attempts"][0]["count"] == 1
    assert value["transitions"][0]["direction"] == "down"
    assert value["transitions"][0]["outcome"] == "moved"

    path.write_text(
        json.dumps({"schema_version": 1, "attempts": [{"bad": True}]}),
        encoding="utf-8",
    )
    discarded = NavigationMemory(path)
    assert discarded.attempts == []
    assert discarded.transitions == []


def test_stuck_assessment_activates_from_count1_evidence(tmp_path):
    path = tmp_path / "navigation-memory.json"
    memory = NavigationMemory(path)
    now = datetime.now(timezone.utc)
    a = (0xC9, 15, 11)
    b = (0xC9, 15, 13)

    memory.begin(a, ["right"], phase="overworld")
    memory.finish(a, now=now)
    early = memory.stuck_assessment(a, now=now)

    # One count-1 failed attempt is a single signal: not stuck yet.
    assert early["active"] is False
    assert early["episode"] is None

    memory.begin(a, ["down"], phase="overworld")
    memory.finish(b, now=now)
    memory.begin(b, ["up"], phase="overworld")
    memory.finish(a, now=now)
    memory.begin(a, ["down"], phase="overworld")
    memory.finish(b, now=now)

    assessment = memory.stuck_assessment(b, now=now)

    assert assessment["active"] is True
    assert "repeated_edge" in assessment["reasons"]
    # Every recorded attempt is still count 1: the old count>=2 gate never
    # sees this loop, but the shared assessment activates anyway.
    assert all(item["count"] == 1 for item in memory.attempts)
    episode = assessment["episode"]
    assert episode is not None
    assert episode["map_id"] == 0xC9
    assert episode["settled_transitions"] == 0

    reloaded = NavigationMemory(path)
    assert reloaded.episode is not None
    assert reloaded.episode["started_at"] == episode["started_at"]


def test_wall_bump_plus_hub_revisits_do_not_arm_puzzle_mode(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    hub = (0x01, 10, 10)

    # One bumped wall: a single count-1 failed attempt on this map.
    memory.begin(hub, ["up"], phase="overworld")
    memory.finish(hub, now=now)

    # Routine town errands: three returns to the same hub tile within 20
    # endpoints, but every directed edge is observed exactly once.
    for stop, out, back in [
        ((0x01, 10, 6), "up", "down"),
        ((0x01, 14, 10), "right", "left"),
        ((0x01, 6, 10), "left", "right"),
    ]:
        memory.begin(hub, [out], phase="overworld")
        memory.finish(stop, now=now)
        memory.begin(stop, [back], phase="overworld")
        memory.finish(hub, now=now)

    assessment = memory.stuck_assessment(hub, now=now)

    # The single bump is one incident, not a repeated settled edge, so the
    # hub revisits alone stay a single signal: no false puzzle activation
    # during normal shopping/talking gameplay.
    assert "repeated_edge" not in assessment["reasons"]
    assert assessment["active"] is False
    assert assessment["episode"] is None


def _activated_memory(tmp_path, map_id=0xC9):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    a = (map_id, 15, 11)
    b = (map_id, 15, 13)
    memory.begin(a, ["down"], phase="overworld")
    memory.finish(b, now=now)
    memory.begin(b, ["up"], phase="overworld")
    memory.finish(a, now=now)
    memory.begin(a, ["down"], phase="overworld")
    memory.finish(b, now=now)
    assert memory.stuck_assessment(b, now=now)["episode"] is not None
    return memory, now, b


def test_stuck_episode_survives_single_novel_coordinate(tmp_path):
    memory, now, b = _activated_memory(tmp_path)

    memory.begin(b, ["left"], phase="overworld")
    memory.finish((0xC9, 2, 2), now=now)

    assert memory.episode is not None
    assert memory.episode["discovery_streak"] == 1


def test_stuck_episode_resets_on_sustained_discovery(tmp_path):
    memory, now, b = _activated_memory(tmp_path)
    previous = b

    for step in range(pokemon_module.STUCK_EPISODE_DISCOVERY_EXIT):
        target = (0xC9, 30 + step, 2)
        memory.begin(previous, ["right"], phase="overworld")
        memory.finish(target, now=now)
        previous = target

    assert memory.episode is None


def test_stuck_episode_resets_on_map_and_story_progress(tmp_path):
    memory, now, b = _activated_memory(tmp_path)

    memory.begin(b, ["up"], phase="overworld")
    memory.finish((0x01, 5, 5), now=now)
    assert memory.episode is None

    memory, now, b = _activated_memory(tmp_path)
    memory.note_progress()
    assert memory.episode is None
    assert NavigationMemory(memory.path).episode is None


def test_runner_treats_b4f_entry_as_semantic_progress(tmp_path):
    memory, _, _ = _activated_memory(tmp_path)
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.navigation_memory = memory
    runner.last_progress_marker = None
    runner.status = {}

    runner._note_gameplay_progress(
        {
            "map_id": 0xCA,
            "coordinates": {"x": 19, "y": 10},
            "badges": ["Boulder", "Cascade", "Thunder", "Rainbow"],
            "key_items": {"lift_key": False, "silph_scope": False},
        }
    )

    assert memory.episode is None


def test_edge_guidance_exposes_learned_directed_edges(tmp_path):
    memory, now, b = _activated_memory(tmp_path)

    edges = memory.edge_guidance(b)

    assert edges is not None
    assert {
        "origin": [15, 11],
        "direction": "down",
        "destination": [0xC9, 15, 13],
        "outcome": "moved",
        "count": 1,
    } in edges
    assert memory.edge_guidance(None) is None


def test_macro_edge_learns_confirms_and_invalidates_on_contradiction(tmp_path):
    path = tmp_path / "navigation-memory.json"
    memory = NavigationMemory(path)
    now = datetime.now(timezone.utc)
    origin = (0xC8, 4, 9)

    memory.begin(origin, ["right"], phase="overworld")
    memory.observe((0xC8, 6, 9))
    memory.finish((0xC8, 9, 9), now=now)

    assert len(memory.macro_edges) == 1
    edge = memory.macro_edges[0]
    assert edge["origin"] == [0xC8, 4, 9]
    assert edge["direction"] == "right"
    assert edge["destination"] == [0xC8, 9, 9]
    assert edge["path"] == [[6, 9]]
    assert edge["confirmed"] == 1

    # Re-observation confirms the deterministic spinner chain.
    memory.begin(origin, ["right"], phase="overworld")
    memory.finish((0xC8, 9, 9), now=now)
    assert memory.macro_edges[0]["confirmed"] == 2

    # Single-tile moves never become macro-edges.
    memory.begin((0xC8, 9, 9), ["down"], phase="overworld")
    memory.finish((0xC8, 9, 10), now=now)
    assert len(memory.macro_edges) == 1

    # Only a contradicting settle destination invalidates the landing.
    memory.begin(origin, ["right"], phase="overworld")
    memory.finish((0xC8, 7, 9), now=now)
    assert memory.macro_edges[0]["destination"] == [0xC8, 7, 9]
    assert memory.macro_edges[0]["confirmed"] == 1

    reloaded = NavigationMemory(path)
    assert reloaded.macro_edges == memory.macro_edges


def test_multi_press_corridor_walk_is_never_learned_as_macro_edge(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)

    # A 3-press corridor walk legitimately moves 3 tiles; learning it as a
    # FORCED edge would poison routing with a false spinner.
    memory.begin((0xC8, 4, 9), ["up", "up", "up"], phase="overworld")
    memory.finish((0xC8, 4, 6), now=now)
    assert memory.macro_edges == []

    # The same displacement from a SINGLE press is forced movement.
    memory.begin((0xC8, 4, 9), ["up"], phase="overworld")
    memory.finish((0xC8, 4, 6), now=now)
    assert len(memory.macro_edges) == 1


def test_single_tile_settle_clears_stale_macro_edge(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    origin = (0xC8, 4, 9)

    memory.begin(origin, ["right"], phase="overworld")
    memory.finish((0xC8, 9, 9), now=now)
    assert len(memory.macro_edges) == 1

    # A later single-press settle moving one tile (or bumping a wall) at the
    # same (origin, direction) contradicts the forced edge and must clear it
    # — displacement <= 1 previously bypassed invalidation entirely.
    memory.begin(origin, ["right"], phase="overworld")
    memory.finish((0xC8, 5, 9), now=now)
    assert memory.macro_edges == []


def test_retreat_exit_is_not_memoized_as_solved_route(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    memory.episode = {
        "maps": [0xC9],
        "region": [[15, 11]],
        "settled_transitions": 5,
        "repeated_edges": 2,
        "discovery_streak": 0,
        "started_at": now.isoformat(),
    }
    # Enter B3F (0xC9) from B2F (0xC8), wander, then withdraw to B2F.
    memory.begin((0xC8, 5, 5), ["down"], phase="overworld")
    memory.finish((0xC9, 15, 11), now=now)
    memory.episode = {
        "maps": [0xC9],
        "region": [[15, 11]],
        "settled_transitions": 5,
        "repeated_edges": 2,
        "discovery_streak": 0,
        "started_at": now.isoformat(),
    }
    memory.begin((0xC9, 15, 11), ["down"], phase="overworld")
    memory.finish((0xC9, 15, 12), now=now)
    memory.begin((0xC9, 15, 12), ["up"], phase="overworld")
    memory.finish((0xC8, 5, 5), now=now)

    # Exiting back to the entry map is a withdrawal, not a solve.
    assert memory.solved_routes == []
    assert memory.episode is None


def test_navigation_memory_migrates_v3_schema_and_persists_v4_sections(
    tmp_path,
):
    now = datetime.now(timezone.utc)
    path = tmp_path / "navigation-memory.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "updated_at": now.isoformat(),
                "attempts": [],
                "trail": [[0xC8, 2, 9]],
                "floor_trail": [0xC8],
                "transitions": [
                    {
                        "origin": [0xC8, 2, 9],
                        "direction": "right",
                        "destination": [0xC8, 8, 9],
                        "path": [[4, 9], [6, 9]],
                        "outcome": "moved",
                        "at": now.isoformat(),
                    }
                ],
                "episode": None,
            }
        ),
        encoding="utf-8",
    )

    memory = NavigationMemory(path)

    # v3 files migrate with the new sections defaulting empty.
    assert len(memory.transitions) == 1
    assert memory.macro_edges == []
    assert memory.solved_routes == []

    memory.begin((0xC8, 2, 9), ["right"], phase="overworld")
    memory.finish((0xC8, 8, 9), now=now)
    value = json.loads(path.read_text(encoding="utf-8"))

    assert value["schema_version"] == 4
    assert value["schema_version"] == (
        pokemon_module.NAVIGATION_MEMORY_SCHEMA_VERSION
    )
    assert value["macro_edges"][0]["destination"] == [0xC8, 8, 9]
    assert value["solved_routes"] == []

    reloaded = NavigationMemory(path)
    assert reloaded.macro_edges == memory.macro_edges

    # Schemas older than v2 are still discarded entirely.
    path.write_text(
        json.dumps({"schema_version": 1, "macro_edges": value["macro_edges"]}),
        encoding="utf-8",
    )
    discarded = NavigationMemory(path)
    assert discarded.macro_edges == []
    assert discarded.solved_routes == []


def test_untried_frontier_lists_nearest_untried_entries_first(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    memory.begin((0xC8, 10, 10), ["right"], phase="overworld")
    memory.finish((0xC8, 11, 10), now=now)
    memory.begin((0xC8, 10, 10), ["down"], phase="overworld")
    memory.finish((0xC8, 10, 10), now=now)

    frontier = memory.untried_frontier((0xC8, 10, 10))

    entries = {(tuple(entry["origin"]), entry["direction"]) for entry in frontier}
    assert ((10, 10), "right") not in entries
    assert ((10, 10), "down") not in entries
    assert ((10, 10), "up") in entries
    assert ((10, 10), "left") in entries
    assert ((11, 10), "up") in entries
    assert frontier[0]["distance"] == 0
    assert len(frontier) <= pokemon_module.NAVIGATION_FRONTIER_LIMIT
    assert memory.untried_frontier(None) == []


def test_route_to_composes_single_step_and_macro_edges(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    memory.begin((0xC8, 5, 5), ["right"], phase="overworld")
    memory.finish((0xC8, 6, 5), now=now)
    memory.begin((0xC8, 6, 5), ["right"], phase="overworld")
    memory.finish((0xC8, 12, 5), now=now)

    steps = memory.route_to((0xC8, 5, 5), [12, 5])

    assert steps == [
        {
            "origin": [0xC8, 5, 5],
            "direction": "right",
            "destination": [0xC8, 6, 5],
        },
        {
            "origin": [0xC8, 6, 5],
            "direction": "right",
            "destination": [0xC8, 12, 5],
        },
    ]
    assert memory.route_to((0xC8, 5, 5), [40, 40]) is None
    assert memory.route_to((0xC8, 5, 5), [5, 5]) is None
    assert memory.route_to((0xC8, 5, 5), [12]) is None
    assert memory.route_to(None, [12, 5]) is None


def test_graph_neighborhood_renders_forced_blocked_and_untried_lines(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    memory.begin((0xC8, 2, 9), ["right"], phase="overworld")
    memory.finish((0xC8, 8, 9), now=now)
    memory.begin((0xC8, 2, 9), ["up"], phase="overworld")
    memory.finish((0xC8, 2, 9), now=now)

    frontier = memory.untried_frontier((0xC8, 2, 9))
    text = memory.graph_neighborhood((0xC8, 2, 9), frontier)

    assert "(2,9) +right: FORCED -> lands (8,9) [confirmed 1]" in text
    assert "(2,9) +up: BLOCKED" in text
    assert "(2,9) +down: UNTRIED" in text
    assert memory.graph_neighborhood(None) is None


def _solved_memory(tmp_path):
    memory, now, b = _activated_memory(tmp_path)
    memory.begin(b, ["down"], phase="overworld")
    memory.finish((0xC9, 15, 14), now=now)
    memory.begin((0xC9, 15, 14), ["down"], phase="overworld")
    memory.finish((0xC9, 15, 16), now=now)
    memory.begin((0xC9, 15, 16), ["down"], phase="overworld")
    memory.finish((0x01, 5, 5), now=now)
    return memory


def test_solved_route_memoized_on_episode_exit_with_loop_erasure(tmp_path):
    memory = _solved_memory(tmp_path)

    assert memory.episode is None
    assert len(memory.solved_routes) == 1
    route = memory.solved_routes[0]
    assert route["map_id"] == 0xC9
    assert route["entrance"] == [15, 11]
    # The a->b->a oscillation from the stuck phase is loop-erased; replay
    # crosses the maze directly and ends with the exiting step.
    assert [step["direction"] for step in route["steps"]] == ["down"] * 4
    assert route["steps"][-1]["destination"] == [0x01, 5, 5]

    steps = memory.solved_route_for((0xC9, 15, 11))
    assert steps is not None
    assert steps[0]["origin"] == [0xC9, 15, 11]
    assert memory.solved_route_for((0xC9, 15, 13)) is None
    assert memory.solved_route_for(None) is None

    reloaded = NavigationMemory(memory.path)
    assert reloaded.solved_routes == memory.solved_routes


def test_collision_direction_gate_accepts_only_open_adjacent_tiles():
    collision = "\n".join(
        [
            "##########",
            "##########",
            "##########",
            "####.#####",
            "###.P#####",
            "####.#####",
            "##########",
            "##########",
            "##########",
        ]
    )

    assert collision_allows_direction(collision, "up")
    assert collision_allows_direction(collision, "down")
    assert collision_allows_direction(collision, "left")
    assert not collision_allows_direction(collision, "right")
    assert not collision_allows_direction("malformed", "left")


def test_chat_advisory_reader_accepts_only_fresh_private_closed_schema(tmp_path):
    now = datetime(2026, 7, 18, 19, 0, tzinfo=timezone.utc)
    path = tmp_path / pokemon_module.YOUTUBE_CHAT_ADVISORY_NAME
    value = {
        "schema_version": 1,
        "source": "youtube-top-chat",
        "video_id": "NBSKt_dou6o",
        "sequence": 8,
        "generated_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=45)).isoformat(),
        "state": "eligible",
        "advisory": {
            "kind": "overworld_direction",
            "direction": "left",
            "observed_at": now.isoformat(),
        },
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)

    advisory, state, sequence = read_youtube_chat_advisory(tmp_path, now=now)

    assert advisory == {
        "kind": "overworld_direction",
        "direction": "left",
    }
    assert state == "eligible"
    assert sequence == 8

    path.chmod(0o644)
    assert read_youtube_chat_advisory(tmp_path, now=now) == (
        None,
        "invalid",
        None,
    )


def test_crowd_hint_is_prompted_only_when_stuck_and_collision_safe(
    tmp_path,
):
    now = datetime.now(timezone.utc)
    path = tmp_path / pokemon_module.YOUTUBE_CHAT_ADVISORY_NAME
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": "youtube-top-chat",
                "video_id": "NBSKt_dou6o",
                "sequence": 1,
                "generated_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=45)).isoformat(),
                "state": "eligible",
                "advisory": {
                    "kind": "overworld_direction",
                    "direction": "left",
                    "observed_at": now.isoformat(),
                },
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.youtube_chat_hints_enabled = True
    runner.status = {"phase": "overworld"}
    position = (0xC9, 15, 11)
    runner.last_crowd_advisory_position = None
    runner.last_crowd_advisory_sequence = -1
    collision = "\n".join(
        ["##########"] * 4
        + ["###.P#####"]
        + ["##########"] * 4
    )

    waiting = runner._crowd_route_advisory(
        position=position,
        collision_map=collision,
        stuck_active=False,
    )

    assert waiting is None
    assert runner.status["crowd_hints_state"] == "armed"

    advisory = runner._crowd_route_advisory(
        position=position,
        collision_map=collision,
        stuck_active=True,
    )

    assert advisory == {
        "kind": "overworld_direction",
        "direction": "left",
    }
    assert runner.status["crowd_hints_state"] == "prompted"
    assert runner.status["crowd_hints_count"] == 1
    assert (
        runner._crowd_route_advisory(
            position=position,
            collision_map=collision,
            stuck_active=True,
        )
        is None
    )


def _research_runner(tmp_path):
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.stuck_web_research_enabled = True
    runner.web_research_result = {}
    runner.web_research_lock = threading.Lock()
    runner.web_research_inflight = False
    runner.web_research_started = {}
    runner.control_generation = 0
    runner.status = {
        "objective": "Find another route",
        "web_research_state": "idle",
        "web_research_source_count": 0,
    }
    runner.runtime_dir = tmp_path
    runner.args = SimpleNamespace(model="gpt-5.6-sol")
    runner.steps_since_new_edge = 0
    runner.navigation_memory = NavigationMemory(
        tmp_path / "navigation-memory.json"
    )
    return runner


def _stuck_episode(**overrides):
    episode = {
        "map_id": 0xC9,
        "maps": [0xC9],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "settled_transitions": 4,
        "repeated_edges": 0,
        "discovery_streak": 0,
        "region": [],
    }
    episode.update(overrides)
    return {
        "active": True,
        "reasons": ["room_cycle"],
        "episode": episode,
    }


def test_stuck_puzzle_escalates_research_despite_route_guidance(
    monkeypatch,
    tmp_path,
):
    started = []

    class ThreadSpy:
        def __init__(self, *, target, args, name, daemon):
            started.append(
                {
                    "target": target,
                    "args": args,
                    "name": name,
                    "daemon": daemon,
                }
            )

        def start(self):
            started[-1]["started"] = True

    monkeypatch.setattr(pokemon_module.threading, "Thread", ThreadSpy)
    runner = _research_runner(tmp_path)
    screenshot = tmp_path / "frame.png"
    screenshot.write_bytes(b"synthetic")
    game_state = {
        "map_id": 0xC9,
        "location": "Rocket Hideout B3F",
        "coordinates": {"x": 15, "y": 11},
    }

    runner._maybe_start_web_research(
        screenshot=screenshot,
        game_state=game_state,
        route_guidance="Authoritative local route.",
        navigation_guidance=None,
        stuck_assessment=_stuck_episode(
            settled_transitions=1,
            repeated_edges=0,
        ),
    )
    assert started == []

    # Coarse route guidance is context now, never a veto; four settled
    # stuck transitions in puzzle mode start the bounded researcher.
    runner._maybe_start_web_research(
        screenshot=screenshot,
        game_state=game_state,
        route_guidance="Authoritative local route.",
        navigation_guidance=None,
        stuck_assessment=_stuck_episode(settled_transitions=4),
    )

    assert runner.web_research_inflight is True
    assert runner.status["web_research_state"] == "searching"
    assert started[0]["name"] == "pokemon-web-research"
    assert started[0]["daemon"] is True
    assert started[0]["started"] is True
    context = started[0]["args"][1]
    assert context["trusted_route_guidance"] == "Authoritative local route."
    assert context["stuck_reasons"] == ["room_cycle"]


def test_loaded_repeated_edge_episode_starts_research_immediately(
    monkeypatch,
    tmp_path,
):
    started = []

    class ThreadSpy:
        def __init__(self, *, target, args, name, daemon):
            started.append(name)

        def start(self):
            pass

    monkeypatch.setattr(pokemon_module.threading, "Thread", ThreadSpy)
    runner = _research_runner(tmp_path)
    screenshot = tmp_path / "frame.png"
    screenshot.write_bytes(b"synthetic")
    game_state = {
        "map_id": 0xC9,
        "location": "Rocket Hideout B3F",
        "coordinates": {"x": 15, "y": 11},
    }

    runner._maybe_start_web_research(
        screenshot=screenshot,
        game_state=game_state,
        route_guidance=None,
        navigation_guidance=None,
        stuck_assessment=_stuck_episode(
            settled_transitions=0,
            repeated_edges=2,
        ),
    )

    assert started == ["pokemon-web-research"]


def test_web_research_cooldown_is_keyed_by_map_and_episode(
    monkeypatch,
    tmp_path,
):
    started = []

    class ThreadSpy:
        def __init__(self, *, target, args, name, daemon):
            started.append(args[1]["coordinates"])

        def start(self):
            pass

    monkeypatch.setattr(pokemon_module.threading, "Thread", ThreadSpy)
    runner = _research_runner(tmp_path)
    screenshot = tmp_path / "frame.png"
    screenshot.write_bytes(b"synthetic")
    first_episode = _stuck_episode(started_at="2026-07-21T10:00:00+00:00")

    def attempt(x, y, stuck):
        runner._maybe_start_web_research(
            screenshot=screenshot,
            game_state={
                "map_id": 0xC9,
                "location": "Rocket Hideout B3F",
                "coordinates": {"x": x, "y": y},
            },
            route_guidance=None,
            navigation_guidance=None,
            stuck_assessment=stuck,
        )
        runner.web_research_inflight = False

    attempt(15, 11, first_episode)
    # Wandering inside the same stuck episode never re-triggers research,
    # even from a different exact coordinate.
    attempt(3, 4, first_episode)
    assert started == [[15, 11]]

    attempt(
        3,
        4,
        _stuck_episode(started_at="2026-07-21T11:00:00+00:00"),
    )
    assert started == [[15, 11], [3, 4]]


def test_settled_position_gate_requires_stable_samples_over_interval():
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.settle_candidate = None
    runner.settle_samples = 0
    runner.settle_started_at = 0.0
    runner.settle_generation = -1
    runner.control_generation = 0
    position = (0xC9, 15, 11)

    assert runner._movement_settled(position, now=100.0) is False
    for index in range(1, pokemon_module.SETTLE_SAMPLE_COUNT):
        # The 12th unchanged sample lands at 0.55s: sample count alone is
        # not enough before SETTLE_MIN_SECONDS has elapsed.
        assert (
            runner._movement_settled(position, now=100.0 + index * 0.05)
            is False
        )
    assert runner._movement_settled(position, now=100.61) is True

    # Any coordinate change restarts the candidate.
    assert runner._movement_settled((0xC9, 16, 11), now=100.65) is False
    assert runner.settle_samples == 1
    for index in range(1, 20):
        runner._movement_settled((0xC9, 16, 11), now=100.65 + index * 0.05)
    assert runner._movement_settled((0xC9, 16, 11), now=102.0) is True

    # A control-generation change restarts even a stable position.
    runner.control_generation += 1
    assert runner._movement_settled((0xC9, 16, 11), now=102.05) is False

    # Dialogue/non-overworld samples are ungated and clear the candidate.
    assert runner._movement_settled(None, now=102.1) is True
    assert runner.settle_candidate is None


def test_puzzle_mode_rejects_non_cardinal_with_structured_feedback(tmp_path):
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.brain_results = queue.Queue()
    runner.pending_decision_id = 1
    runner.decision_pending = True
    runner.control_generation = 0
    runner.control_mode = "ai"
    runner.emulator_pause_requested = False
    runner.last_decision_requested = 10.0
    runner.last_decision_finished = 5.0
    runner.status = {}
    runner.navigation_memory = NavigationMemory(
        tmp_path / "navigation-memory.json"
    )
    runner.puzzle_feedback = None
    runner.player = None  # any attempt to apply buttons would fail loudly
    runner.brain_results.put(
        {
            "decision_id": 1,
            "generation": 0,
            "navigation_mode": "puzzle",
            "decision": {
                "phase": "overworld",
                "observation": "spinner maze",
                "objective": "reach the stairs",
                "reason": "guess",
                "buttons": ["up", "up"],
                "checkpoint": False,
                "action_mode": "precision",
            },
        }
    )

    runner._apply_brain_result()

    assert runner.decision_pending is False
    assert runner.last_decision_finished == 0
    assert runner.puzzle_feedback["rejected_buttons"] == ["up", "up"]
    assert "exactly one of" in runner.puzzle_feedback["reason"]
    assert runner.status["puzzle_rejections"] == 1
    assert runner.status["brain_status"] == "idle"
    assert runner.status.get("last_action") is None


def test_puzzle_mode_applies_single_cardinal_decision(tmp_path):
    class PlayerSpy:
        def __init__(self):
            self.replaced = []

        def replace(self, buttons):
            self.replaced.append(buttons)

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.brain_results = queue.Queue()
    runner.pending_decision_id = 2
    runner.decision_pending = True
    runner.control_generation = 0
    runner.control_mode = "ai"
    runner.emulator_pause_requested = False
    runner.last_decision_requested = 10.0
    runner.last_decision_finished = 5.0
    runner.status = {"game_state": {}}
    runner.navigation_memory = NavigationMemory(
        tmp_path / "navigation-memory.json"
    )
    runner.puzzle_feedback = None
    runner.player = PlayerSpy()
    runner.history = []
    runner.total_decisions = 0
    runner.runtime_dir = tmp_path
    runner.brain_results.put(
        {
            "decision_id": 2,
            "generation": 0,
            "navigation_mode": "puzzle",
            "navigation_origin": None,
            "force_precision": True,
            "movement_context": True,
            "decision": {
                "phase": "overworld",
                "observation": "spinner maze",
                "objective": "reach the stairs",
                "reason": "learned edge",
                "buttons": ["left"],
                "checkpoint": False,
                "action_mode": "precision",
            },
        }
    )

    runner._apply_brain_result()

    assert runner.player.replaced == [["left"]]
    assert runner.status["last_action"] == ["left"]
    assert runner.puzzle_feedback is None
    assert runner.status["gameplay_progress_at"]


def test_puzzle_contract_exempts_non_overworld_phase(tmp_path):
    class PlayerSpy:
        def __init__(self):
            self.replaced = []

        def replace(self, buttons):
            self.replaced.append(buttons)

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.brain_results = queue.Queue()
    runner.pending_decision_id = 3
    runner.decision_pending = True
    runner.control_generation = 0
    runner.control_mode = "ai"
    runner.emulator_pause_requested = False
    runner.last_decision_requested = 10.0
    runner.last_decision_finished = 5.0
    runner.status = {"game_state": {}}
    runner.navigation_memory = NavigationMemory(
        tmp_path / "navigation-memory.json"
    )
    runner.puzzle_feedback = None
    runner.player = PlayerSpy()
    runner.history = []
    runner.total_decisions = 0
    runner.runtime_dir = tmp_path
    runner.brain_results.put(
        {
            "decision_id": 3,
            "generation": 0,
            "navigation_mode": "puzzle",
            "navigation_origin": None,
            "force_precision": False,
            "movement_context": False,
            "decision": {
                "phase": "battle",
                "observation": "a Rocket grunt sent out Zubat",
                "objective": "win the trainer battle",
                "reason": "select Fight",
                "buttons": ["a"],
                "checkpoint": False,
                "action_mode": "precision",
            },
        }
    )

    runner._apply_brain_result()

    # A battle that begins mid-decision must keep pressing a even while a
    # puzzle episode is active: the one-cardinal contract is overworld-only.
    assert runner.player.replaced == [["a"]]
    assert runner.status["last_action"] == ["a"]
    assert runner.puzzle_feedback is None
    assert "puzzle_rejections" not in runner.status


def test_request_decision_keeps_episode_but_drops_puzzle_off_route(tmp_path):
    memory, now, b = _activated_memory(tmp_path)
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.screens_dir = tmp_path
    runner.run_id = "test"
    runner.decision_sequence = 0
    runner.control_generation = 0
    runner.control_mode = "ai"
    runner.emulator_pause_requested = False
    runner.status = {"phase": "battle", "model_calls": 0}
    runner.navigation_memory = memory
    runner.decision_positions = []
    runner.stuck_decision_count = 5
    runner.puzzle_feedback = {"reason": "pending"}
    runner.navigation_mode = "puzzle"
    runner.stuck_web_research_enabled = False
    runner.total_decisions = 0
    runner.last_edge_count = 0
    runner.steps_since_new_edge = 0
    runner.edge_count_history = deque(
        maxlen=pokemon_module.EDGE_LEARNING_WINDOW_DECISIONS + 1
    )
    runner.history = []
    runner.pending_decision_id = None
    runner.decision_pending = False
    runner.brain_requests = queue.Queue()
    runner._maybe_start_web_research = lambda **kwargs: None
    runner._crowd_route_advisory = lambda **kwargs: None
    image = SimpleNamespace(
        save=lambda path, format=None: Path(path).write_bytes(b"png")
    )
    game_state = {
        "map_id": 0xC9,
        "x": b[1],
        "y": b[2],
        "screen_text": "ROCKET: I will not lose!",
    }

    runner._request_decision(image, game_state, None)

    request = runner.brain_requests.get_nowait()
    # A battle on the episode map is issued in normal mode so the brain can
    # press a/b freely, while the stuck episode itself stays persisted for
    # the next settled overworld decision.
    assert request["navigation_mode"] == "normal"
    assert runner.navigation_mode == "normal"
    assert runner.status["navigation_mode"] == "normal"
    assert memory.episode is not None
    assert runner.stuck_decision_count == 5
    assert runner.puzzle_feedback == {"reason": "pending"}


class _PlayerSpy:
    def __init__(self):
        self.replaced = []

    def replace(self, buttons):
        self.replaced.append(buttons)


def _route_runner(tmp_path, memory=None):
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.navigation_memory = memory or NavigationMemory(
        tmp_path / "navigation-memory.json"
    )
    runner.committed_route = None
    runner.solved_route_attempts = {}
    runner.navigation_mode = "puzzle"
    runner.steps_since_new_edge = 0
    runner.auto_coverage_rides = 0
    runner.auto_coverage_episode = None
    runner.control_generation = 0
    runner.player = _PlayerSpy()
    runner.settle_candidate = None
    runner.settle_samples = 0
    runner.position_settled = True
    runner.last_decision_finished = 0.0
    runner.status = {}
    return runner


def _coverage_runner(tmp_path, memory):
    runner = _route_runner(tmp_path, memory=memory)
    runner.steps_since_new_edge = pokemon_module.AUTO_COVERAGE_STALL_DECISIONS
    runner.auto_coverage_rides = 0
    runner.auto_coverage_episode = None
    memory.episode = {
        "maps": [0xC9],
        "region": [[15, 11]],
        "settled_transitions": 8,
        "repeated_edges": 3,
        "discovery_streak": 0,
        "started_at": "2026-07-22T10:00:00+00:00",
    }
    return runner


def test_auto_coverage_rides_adjacent_untried_entry_when_stalled(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    runner = _coverage_runner(tmp_path, memory)

    issued = runner._advance_committed_route(
        {"map_id": 0xC9, "coordinates": {"x": 15, "y": 11}}
    )

    # The harness itself commits a probe ride on an UNTRIED entry at the
    # current tile — no brain decision consumed.
    assert issued is True
    assert runner.player.replaced and len(runner.player.replaced[0]) == 1
    assert runner.status["committed_route"] is None  # single probe completes
    assert runner.status["auto_coverage_rides"] == 1


def test_auto_coverage_requires_stall_and_puzzle_mode(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    runner = _coverage_runner(tmp_path, memory)
    runner.steps_since_new_edge = 0
    assert (
        runner._advance_committed_route(
            {"map_id": 0xC9, "coordinates": {"x": 15, "y": 11}}
        )
        is False
    )
    runner.steps_since_new_edge = pokemon_module.AUTO_COVERAGE_STALL_DECISIONS
    runner.navigation_mode = "normal"
    assert (
        runner._advance_committed_route(
            {"map_id": 0xC9, "coordinates": {"x": 15, "y": 11}}
        )
        is False
    )


@pytest.mark.parametrize("strategy", ["probe_frontier", "escalate_research"])
def test_governor_probe_frontier_bypasses_local_stall_counter(
    tmp_path,
    strategy,
):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    runner = _coverage_runner(tmp_path, memory)
    runner.steps_since_new_edge = 0
    runner.status["improvement_cycle"] = {"strategy": strategy}

    assert (
        runner._advance_committed_route(
            {"map_id": 0xC9, "coordinates": {"x": 15, "y": 11}}
        )
        is True
    )
    assert runner.status["auto_coverage_rides"] == 1


def test_environment_probe_priority_outranks_closer_dead_end(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    memory.walk_edges[(0xC9, 20, 14, "down")] = [20, 15]
    runner = _coverage_runner(tmp_path, memory)
    runner.status["improvement_cycle"] = {"strategy": "probe_frontier"}

    assert (
        runner._advance_committed_route(
            {"map_id": 0xC9, "coordinates": {"x": 20, "y": 14}}
        )
        is True
    )
    assert runner.committed_route is not None
    assert runner.committed_route["steps"][-1] == {
        "origin": [0xC9, 20, 15],
        "direction": "down",
        "destination": None,
    }


def test_b3f_adapter_starts_south_from_entrance(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    runner = _coverage_runner(tmp_path, memory)
    runner.status["improvement_cycle"] = {"strategy": "escalate_research"}

    assert (
        runner._advance_committed_route(
            {"map_id": 0xC9, "coordinates": {"x": 15, "y": 11}}
        )
        is True
    )
    assert runner.player.replaced == [["down"]]
    assert runner.status["auto_coverage_rides"] == 1


def test_auto_coverage_episode_cap_and_reset(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    runner = _coverage_runner(tmp_path, memory)
    runner.auto_coverage_episode = "2026-07-22T10:00:00+00:00"
    runner.auto_coverage_rides = pokemon_module.AUTO_COVERAGE_EPISODE_LIMIT
    assert (
        runner._advance_committed_route(
            {"map_id": 0xC9, "coordinates": {"x": 15, "y": 11}}
        )
        is False
    )
    # A new episode identity resets the ride budget.
    memory.episode["started_at"] = "2026-07-22T11:00:00+00:00"
    assert (
        runner._advance_committed_route(
            {"map_id": 0xC9, "coordinates": {"x": 15, "y": 11}}
        )
        is True
    )
    assert runner.auto_coverage_rides == 1


def test_committed_route_executes_stepwise_and_aborts_on_surprise(tmp_path):
    runner = _route_runner(tmp_path)
    steps = [
        {
            "origin": [0xC8, 5, 5],
            "direction": "right",
            "destination": [0xC8, 6, 5],
        },
        {
            "origin": [0xC8, 6, 5],
            "direction": "up",
            "destination": [0xC8, 6, 4],
        },
    ]
    runner.committed_route = {
        "steps": steps,
        "index": 0,
        "generation": 0,
        "source": "route_target",
    }
    runner.navigation_memory.walk_edges[(0xC8, 5, 5, "right")] = [6, 5]

    issued = runner._advance_committed_route(
        {"map_id": 0xC8, "coordinates": {"x": 5, "y": 5}}
    )

    assert issued is True
    assert runner.player.replaced == [["right"]]
    assert runner.status["brain_status"] == "route"
    assert runner.status["last_action"] == ["right"]
    assert runner.status["committed_route"] == {
        "source": "route_target",
        "remaining": 1,
    }
    assert runner.position_settled is False
    assert runner.last_decision_finished > 0

    # An off-plan settled position (spinner surprise, wrong tile, wrong map)
    # aborts so the same slot falls through to a fresh brain decision.
    assert (
        runner._advance_committed_route(
            {"map_id": 0xC8, "coordinates": {"x": 9, "y": 5}}
        )
        is False
    )
    assert runner.committed_route is None
    assert runner.status["committed_route"] is None
    assert (0xC8, 5, 5, "right") not in runner.navigation_memory.walk_edges
    assert any(
        item["origin"] == [5, 5]
        and item["buttons"] == ["right"]
        and item["outcome"] == "cycle"
        for item in runner.navigation_memory.attempts
    )

    # Dialogue or battle text is a surprise even on the expected tile.
    runner.committed_route = {
        "steps": steps,
        "index": 1,
        "generation": 0,
        "source": "route_target",
    }
    assert (
        runner._advance_committed_route(
            {
                "map_id": 0xC8,
                "coordinates": {"x": 6, "y": 5},
                "screen_text": "A wild ZUBAT appeared!",
            }
        )
        is False
    )
    assert runner.committed_route is None

    # A control-generation change invalidates any committed plan.
    runner.committed_route = {
        "steps": steps,
        "index": 1,
        "generation": 0,
        "source": "route_target",
    }
    runner.control_generation = 1
    assert (
        runner._advance_committed_route(
            {"map_id": 0xC8, "coordinates": {"x": 6, "y": 5}}
        )
        is False
    )
    assert runner.committed_route is None


def test_solved_route_replays_as_committed_route_once_per_visit(tmp_path):
    memory = _solved_memory(tmp_path)
    runner = _route_runner(tmp_path, memory=memory)
    entered = {"map_id": 0xC9, "coordinates": {"x": 15, "y": 11}}

    # Re-entry at the memoized entrance commits the stored route.
    assert runner._advance_committed_route(entered) is True
    assert runner.player.replaced == [["down"]]
    assert runner.status["committed_route"]["source"] == "solved_route"

    # A surprise aborts, and the same entrance never re-commits the route.
    assert (
        runner._advance_committed_route(
            {"map_id": 0xC9, "coordinates": {"x": 3, "y": 3}}
        )
        is False
    )
    assert runner.committed_route is None
    assert runner._advance_committed_route(entered) is False

    # The block is process-lifetime: a map change (including the one a bad
    # route's own eject would cause) must NOT re-arm replay at this entrance.
    assert (
        runner._advance_committed_route(
            {"map_id": 0x01, "coordinates": {"x": 5, "y": 5}}
        )
        is False
    )
    assert runner._advance_committed_route(entered) is False

    # Outside puzzle mode a stored route is never a control override.
    runner.solved_route_attempts.clear()
    runner.navigation_mode = "normal"
    assert runner._advance_committed_route(entered) is False
    runner.navigation_mode = "puzzle"
    assert runner._advance_committed_route(entered) is True


def test_route_target_decision_commits_verified_bfs_route(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    memory.begin((0xC8, 5, 5), ["right"], phase="overworld")
    memory.finish((0xC8, 6, 5), now=now)
    memory.begin((0xC8, 6, 5), ["right"], phase="overworld")
    memory.finish((0xC8, 12, 5), now=now)

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.brain_results = queue.Queue()
    runner.pending_decision_id = 4
    runner.decision_pending = True
    runner.control_generation = 0
    runner.control_mode = "ai"
    runner.emulator_pause_requested = False
    runner.last_decision_requested = 10.0
    runner.last_decision_finished = 5.0
    runner.status = {
        "game_state": {"map_id": 0xC8, "coordinates": {"x": 5, "y": 5}}
    }
    runner.navigation_memory = memory
    runner.puzzle_feedback = None
    runner.player = _PlayerSpy()
    runner.history = []
    runner.total_decisions = 0
    runner.runtime_dir = tmp_path
    runner.committed_route = None
    runner.settle_candidate = None
    runner.settle_samples = 0
    runner.position_settled = False
    runner.brain_results.put(
        {
            "decision_id": 4,
            "generation": 0,
            "navigation_mode": "puzzle",
            "navigation_origin": [0xC8, 5, 5],
            "force_precision": True,
            "movement_context": True,
            "decision": {
                "phase": "overworld",
                "observation": "spinner maze",
                "objective": "ride to the learned far tile",
                "reason": "frontier target",
                "buttons": ["up"],
                "checkpoint": False,
                "action_mode": "precision",
                "route_target": [12, 5],
            },
        }
    )

    runner._apply_brain_result()

    # The brain named a graph tile; the harness committed the BFS route and
    # issued only its first verified step.
    assert runner.player.replaced == [["right"]]
    assert runner.committed_route["index"] == 1
    assert [
        step["direction"] for step in runner.committed_route["steps"]
    ] == ["right", "right"]
    assert runner.status["committed_route"] == {
        "source": "route_target",
        "remaining": 1,
    }


def test_untried_frontier_outranks_web_research(monkeypatch, tmp_path):
    started = []

    class ThreadSpy:
        def __init__(self, *, target, args, name, daemon):
            started.append(name)

        def start(self):
            pass

    monkeypatch.setattr(pokemon_module.threading, "Thread", ThreadSpy)
    runner = _research_runner(tmp_path)
    screenshot = tmp_path / "frame.png"
    screenshot.write_bytes(b"synthetic")
    game_state = {
        "map_id": 0xC9,
        "location": "Rocket Hideout B3F",
        "coordinates": {"x": 15, "y": 11},
    }

    # R3: while nearby UNTRIED entries remain AND coverage is still learning
    # new edges, the directive rung handles escalation and research waits.
    runner._maybe_start_web_research(
        screenshot=screenshot,
        game_state=game_state,
        route_guidance=None,
        navigation_guidance=None,
        stuck_assessment=_stuck_episode(settled_transitions=9),
        frontier=[{"origin": [15, 10], "direction": "up", "distance": 1}],
    )
    assert started == []

    # Coverage stall: a perpetually non-empty frontier must not starve the
    # ladder — once no new edge has been learned for FRONTIER_STALL_DECISIONS
    # decisions, research fires despite remaining UNTRIED entries.
    runner.steps_since_new_edge = pokemon_module.FRONTIER_STALL_DECISIONS
    runner._maybe_start_web_research(
        screenshot=screenshot,
        game_state=game_state,
        route_guidance=None,
        navigation_guidance=None,
        stuck_assessment=_stuck_episode(settled_transitions=9),
        frontier=[{"origin": [15, 10], "direction": "up", "distance": 1}],
    )
    assert len(started) == 1
    runner.web_research_inflight = False
    runner.web_research_started = {}
    runner.steps_since_new_edge = 0

    started.clear()
    # An exhausted frontier lets the research rung fire.
    runner._maybe_start_web_research(
        screenshot=screenshot,
        game_state=game_state,
        route_guidance=None,
        navigation_guidance=None,
        stuck_assessment=_stuck_episode(settled_transitions=9),
        frontier=[],
    )
    assert started == ["pokemon-web-research"]


def test_puzzle_decision_state_carries_neighborhood_directive_and_counters(
    tmp_path,
):
    memory, now, b = _activated_memory(tmp_path)
    a = (0xC9, 15, 11)
    # Two more oscillations make the endpoint revisit a second active signal.
    memory.begin(b, ["up"], phase="overworld")
    memory.finish(a, now=now)
    memory.begin(a, ["down"], phase="overworld")
    memory.finish(b, now=now)
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.screens_dir = tmp_path
    runner.run_id = "test"
    runner.decision_sequence = 0
    runner.control_generation = 0
    runner.control_mode = "ai"
    runner.emulator_pause_requested = False
    runner.status = {"phase": "overworld", "model_calls": 0}
    runner.navigation_memory = memory
    runner.decision_positions = deque(maxlen=6)
    runner.stuck_decision_count = 2
    runner.puzzle_feedback = None
    runner.navigation_mode = "puzzle"
    runner.stuck_web_research_enabled = False
    runner.total_decisions = 7
    runner.last_edge_count = 0
    runner.steps_since_new_edge = 3
    runner.edge_count_history = deque(
        maxlen=pokemon_module.EDGE_LEARNING_WINDOW_DECISIONS + 1
    )
    runner.history = []
    runner.pending_decision_id = None
    runner.decision_pending = False
    runner.brain_requests = queue.Queue()
    research_calls = []
    runner._maybe_start_web_research = (
        lambda **kwargs: research_calls.append(kwargs)
    )
    runner._crowd_route_advisory = lambda **kwargs: None
    image = SimpleNamespace(
        save=lambda path, format=None: Path(path).write_bytes(b"png")
    )
    collision = "\n".join(
        "....P....." if index == 4 else ".........." for index in range(9)
    )
    game_state = {"map_id": 0xC9, "coordinates": {"x": b[1], "y": b[2]}}

    runner._request_decision(image, game_state, collision)

    request = runner.brain_requests.get_nowait()
    state = request["game_state"]
    assert state["navigation_mode"] == "puzzle"
    counters = state["step_counters"]
    assert counters["global_actions"] == 7
    assert counters["decisions_this_episode"] == 3
    # Two distinct learned edges against a zero baseline reset the stall
    # counter this decision.
    assert counters["steps_since_new_edge"] == 0
    assert "UNTRIED" in state["graph_neighborhood"]
    assert "steps this episode:" in state["graph_neighborhood"]
    assert "new edges learned in last" in state["graph_neighborhood"]
    assert state["frontier_directive"].startswith("DIRECTIVE")
    assert "(" in state["frontier_directive"]
    # The computed frontier reaches the research gate (R3 ordering).
    assert research_calls and research_calls[0]["frontier"]


def test_exact_route_guidance_suppresses_conflicting_frontier(tmp_path):
    memory, now, b = _activated_memory(tmp_path, map_id=0xEA)
    a = (0xEA, 15, 11)
    warps = [
        {"x": 10, "y": 0, "destination_map": 0xEB},
        {"x": 12, "y": 0, "destination_map": 0xEC},
    ]
    # A newly observed warp signature intentionally resets an old episode.
    # Establish it first, then reproduce the loop the route override must relax.
    memory.observe_warps(0xEA, warps)
    memory.begin(a, ["down"], phase="overworld")
    memory.finish(b, now=now)
    memory.begin(b, ["up"], phase="overworld")
    memory.finish(a, now=now)
    memory.begin(a, ["down"], phase="overworld")
    memory.finish(b, now=now)
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.screens_dir = tmp_path
    runner.run_id = "test"
    runner.decision_sequence = 0
    runner.control_generation = 0
    runner.control_mode = "ai"
    runner.emulator_pause_requested = False
    runner.status = {"phase": "overworld", "model_calls": 0}
    runner.navigation_memory = memory
    runner.decision_positions = deque(maxlen=6)
    runner.stuck_decision_count = 2
    runner.puzzle_feedback = None
    runner.navigation_mode = "puzzle"
    runner.stuck_web_research_enabled = False
    runner.total_decisions = 7
    runner.last_edge_count = 0
    runner.steps_since_new_edge = 3
    runner.edge_count_history = deque(
        maxlen=pokemon_module.EDGE_LEARNING_WINDOW_DECISIONS + 1
    )
    runner.history = []
    runner.pending_decision_id = None
    runner.decision_pending = False
    runner.brain_requests = queue.Queue()
    runner._maybe_start_web_research = lambda **kwargs: None
    runner._crowd_route_advisory = lambda **kwargs: None
    image = SimpleNamespace(
        save=lambda path, format=None: Path(path).write_bytes(b"png")
    )
    game_state = silph_state(
        0xEA,
        warps,
        x=b[1],
        y=b[2],
        card_key=True,
    )

    collision = "\n".join(
        "....P....." if index == 4 else ".........." for index in range(9)
    )
    runner._request_decision(image, game_state, collision)

    request = runner.brain_requests.get_nowait()
    state = request["game_state"]
    assert "choose 3F" in state["route_guidance"]
    assert "frontier_directive" not in state
    assert "navigation_mode" not in state
    assert request["navigation_mode"] == "normal"
    # The deterministic stuck episode remains available after the story
    # interaction if it does not actually make progress.
    assert runner.navigation_mode == "puzzle"


def test_exact_route_guidance_cancels_route_before_replay(tmp_path):
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.committed_route = {
        "steps": [
            {
                "origin": [0xC0, 4, 17],
                "direction": "down",
                "destination": [0x1F, 48, 6],
            }
        ],
        "index": 0,
        "generation": 0,
        "source": "solved_route",
    }
    runner.status = {"committed_route": {"source": "solved_route"}}
    runner.navigation_memory = NavigationMemory(
        tmp_path / "navigation-memory.json"
    )
    game_state = {
        "map_id": 0xC0,
        "coordinates": {"x": 4, "y": 17},
        "screen_text": "",
        "badges": [
            "Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh"
        ],
        "key_items": {
            "hm_surf": True,
            "hm_strength": True,
            "secret_key": False,
        },
    }

    assert runner._advance_committed_route(game_state) is False
    assert runner.committed_route is None
    assert runner.status["committed_route"] is None


def test_prompt_stamps_step_counters_with_time_blindness_line():
    prompt = CopilotBrain._prompt(
        {
            "location": "Rocket Hideout B3F",
            "step_counters": {
                "global_actions": 4210,
                "decisions_this_episode": 37,
                "steps_since_new_edge": 22,
            },
        },
        None,
        [],
    )

    assert '"global_actions":4210' in prompt
    assert "no sense of elapsed time" in prompt
    assert "change strategy" in prompt
    # The counters render once in their own section, not duplicated inside
    # the RAM snapshot JSON.
    assert prompt.count("4210") == 1

    plain = CopilotBrain._prompt({"location": "Pallet Town"}, None, [])
    assert "Step counters" not in plain


def test_normalize_brain_decision_accepts_optional_route_target():
    decision = normalize_brain_decision(
        '{"buttons":["up"],"route_target":[12,5]}'
    )
    assert decision["route_target"] == [12, 5]

    for bad in ("[12]", "[300,5]", '["12",5]', "true", "[true,false]"):
        decision = normalize_brain_decision(
            f'{{"buttons":["up"],"route_target":{bad}}}'
        )
        assert "route_target" not in decision


def test_system_prompt_documents_frontier_and_route_target_contract():
    assert "frontier_directive" in GAME_SYSTEM_PROMPT
    assert "graph_neighborhood" in GAME_SYSTEM_PROMPT
    assert '"route_target":[x,y]' in GAME_SYSTEM_PROMPT
    assert "You have no sense of" in GAME_SYSTEM_PROMPT
    assert "elapsed time" in GAME_SYSTEM_PROMPT


def test_control_cursor_initializes_at_eof_and_never_replays(tmp_path):
    control = tmp_path / "control.jsonl"
    control.write_text('{"action":"pause"}\n', encoding="utf-8")

    def make_runner():
        runner = PokemonRunner.__new__(PokemonRunner)
        runner.runtime_dir = tmp_path
        runner.control_path = control
        runner.control_cursor_path = (
            tmp_path / pokemon_module.CONTROL_CURSOR_NAME
        )
        runner.controls = queue.Queue()
        runner.status = {}
        runner.control_offset = runner._load_control_cursor()
        return runner

    runner = make_runner()

    assert runner.control_offset == control.stat().st_size
    runner._read_external_controls()
    assert runner.controls.empty()  # the historical pause never replays

    with control.open("a", encoding="utf-8") as handle:
        handle.write('{"action":"resume"}\n')
    runner._read_external_controls()
    assert runner.controls.get_nowait()["action"] == "resume"

    # A restarted process resumes from the durable cursor: the processed
    # resume is not replayed either.
    restarted = make_runner()
    restarted._read_external_controls()
    assert restarted.controls.empty()


def _control_runner(monkeypatch):
    pyboy_module = ModuleType("pyboy")
    utils_module = ModuleType("pyboy.utils")

    class WindowEvent:
        PAUSE = "pause"
        UNPAUSE = "unpause"

    utils_module.WindowEvent = WindowEvent
    pyboy_module.utils = utils_module
    monkeypatch.setitem(sys.modules, "pyboy", pyboy_module)
    monkeypatch.setitem(sys.modules, "pyboy.utils", utils_module)

    class PlayerSpy:
        def release(self, pyboy):
            del pyboy

    class EmulatorSpy:
        def __init__(self):
            self.events = []
            self.speed = None

        def send_input(self, event):
            self.events.append(event)

        def set_emulation_speed(self, speed):
            self.speed = speed

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.controls = queue.Queue()
    runner.control_mode = "ai"
    runner.resume_mode = "ai"
    runner.control_generation = 0
    runner.paused = False
    runner.emulator_pause_requested = False
    runner.decision_pending = False
    runner.last_decision_finished = 0
    runner.player = PlayerSpy()
    runner.pyboy = EmulatorSpy()
    runner.status = {}
    runner.pause_kind = None
    runner.pause_owner = None
    runner.pause_expires_at = None
    runner.last_crowd_advisory_position = None
    return runner


def test_ambiguous_and_unbounded_pauses_are_rejected_with_report(monkeypatch):
    runner = _control_runner(monkeypatch)

    runner.controls.put({"action": "pause"})
    runner._process_controls()
    assert runner.control_mode == "ai"
    report = runner.status["last_rejected_control"]
    assert report["action"] == "pause"
    assert "kind" in report["reason"]

    runner.controls.put({"action": "pause", "kind": "automation"})
    runner._process_controls()
    assert runner.control_mode == "ai"

    far_future = datetime.now(timezone.utc) + timedelta(hours=5)
    runner.controls.put(
        {
            "action": "pause",
            "kind": "automation",
            "expires_at": far_future.isoformat(),
        }
    )
    runner._process_controls()
    assert runner.control_mode == "ai"
    assert "exceeds" in runner.status["last_rejected_control"]["reason"]

    stale = datetime.now(timezone.utc) - timedelta(seconds=30)
    runner.controls.put(
        {
            "action": "pause",
            "kind": "automation",
            "expires_at": stale.isoformat(),
        }
    )
    runner._process_controls()
    assert runner.control_mode == "ai"  # replayed/expired leases never apply


def test_automation_pause_lease_expires_and_auto_resumes(
    monkeypatch,
    tmp_path,
):
    runner = _control_runner(monkeypatch)
    runner.navigation_memory = NavigationMemory(
        tmp_path / "navigation-memory.json"
    )
    runner.navigation_memory.episode = {
        "map_id": 0xC9,
        "maps": [0xC9],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "settled_transitions": 4,
        "repeated_edges": 1,
        "discovery_streak": 0,
        "region": [],
    }
    expires = datetime.now(timezone.utc) + timedelta(seconds=60)
    runner.controls.put(
        {
            "action": "pause",
            "kind": "automation",
            "expires_at": expires.isoformat(),
            "owner": "recovery-bot",
        }
    )
    runner._process_controls()

    assert runner.control_mode == "paused"
    assert runner.status["pause_kind"] == "automation"
    assert runner.status["pause_owner"] == "recovery-bot"
    assert runner.status["pause_expires_at"] is not None

    runner._expire_automation_pause()
    assert runner.control_mode == "paused"  # lease not yet due

    runner.pause_expires_at = datetime.now(timezone.utc) - timedelta(
        seconds=1
    )
    runner._expire_automation_pause()

    assert runner.control_mode == "ai"
    assert runner.pause_kind is None
    assert runner.status["pause_kind"] is None
    assert runner.status["pause_autoresumed_at"]
    # Auto-resume never erases the persisted stuck episode.
    assert runner.navigation_memory.episode is not None


def test_operator_hold_is_never_auto_resumed(monkeypatch):
    runner = _control_runner(monkeypatch)

    runner.controls.put(
        {"action": "pause", "kind": "operator_hold", "owner": "kody"}
    )
    runner._process_controls()
    assert runner.control_mode == "ai"  # persistent intent must be explicit

    runner.controls.put(
        {
            "action": "pause",
            "kind": "operator_hold",
            "persistent": True,
            "owner": "kody",
        }
    )
    runner._process_controls()
    assert runner.control_mode == "paused"
    assert runner.status["pause_kind"] == "operator_hold"

    runner._expire_automation_pause()
    assert runner.control_mode == "paused"

    expires = datetime.now(timezone.utc) + timedelta(seconds=60)
    runner.controls.put(
        {
            "action": "pause",
            "kind": "automation",
            "expires_at": expires.isoformat(),
        }
    )
    runner._process_controls()
    assert runner.status["pause_kind"] == "operator_hold"

    runner.controls.put({"action": "resume"})
    runner._process_controls()
    assert runner.control_mode == "ai"
    assert runner.status["pause_kind"] is None
    assert runner.pause_owner is None


def test_rewind_persistence_failure_does_not_report_loaded_state_rejected(
    monkeypatch,
):
    runner = _control_runner(monkeypatch)
    runner._rotate_clip = lambda reason: None
    runner._hotload_git_checkpoint = lambda commit: "a" * 40

    def fail_checkpoint(reason):
        raise OSError("disk full")

    runner._save_checkpoint = fail_checkpoint
    runner.controls.put({"action": "rewind", "commit": "a" * 12})

    runner._process_controls()

    assert runner.status["last_rejected_control"] is None
    assert runner.status["last_error"] == (
        "Git rewind loaded, but checkpoint persistence failed: disk full"
    )


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("save checkpoint and start a new clip", ("checkpoint", None)),
        ("pause the game", ("pause", None)),
        ("continue playing", ("autonomy", None)),
        ("take over manually", ("manual", None)),
        ("press start", ("press", "start")),
        ("show progress", ("status", None)),
        ("open viewer", ("view", None)),
        ("stop playing", ("stop", None)),
        ("play Pokemon", ("start", None)),
    ],
)
def test_parse_agent_action(query, expected):
    assert parse_agent_action(query) == expected


def test_runtime_status_reports_stopped(tmp_path):
    (tmp_path / "status.json").write_text(
        json.dumps({"running": True, "pid": 999_999_999, "port": 9999})
    )

    status = runtime_status(tmp_path)

    assert status["running"] is False
    assert status["viewer_url"] == "http://127.0.0.1:9999"
    assert status["clips"] == []


def test_agent_rejects_control_when_not_running(tmp_path):
    result = json.loads(
        PokemonAgent().perform(action="checkpoint", runtime_dir=str(tmp_path))
    )

    assert result["status"] == "error"
    assert "not running" in result["message"]


def test_agent_validates_and_queues_git_rewind(tmp_path):
    (tmp_path / "status.json").write_text(
        json.dumps({"running": True, "pid": os.getpid(), "port": 9999})
    )

    invalid = json.loads(
        PokemonAgent().perform(
            action="rewind",
            commit="not-a-commit",
            runtime_dir=str(tmp_path),
        )
    )
    valid = json.loads(
        PokemonAgent().perform(
            action="rewind",
            commit="a" * 12,
            runtime_dir=str(tmp_path),
        )
    )

    assert invalid["status"] == "error"
    assert valid["status"] == "success"
    command = json.loads(
        (tmp_path / "control.jsonl").read_text().splitlines()[-1]
    )
    assert command["action"] == "rewind"
    assert command["commit"] == "a" * 12


def test_agent_pause_defaults_to_bounded_automation_lease(tmp_path):
    (tmp_path / "status.json").write_text(
        json.dumps({"running": True, "pid": os.getpid(), "port": 9999})
    )

    result = json.loads(
        PokemonAgent().perform(action="pause", runtime_dir=str(tmp_path))
    )

    assert result["status"] == "success"
    command = json.loads(
        (tmp_path / "control.jsonl").read_text().splitlines()[-1]
    )
    assert command["action"] == "pause"
    assert command["kind"] == "automation"
    assert command["owner"] == "agent-cli"
    # A forgotten agent pause auto-resumes: the lease carries an absolute
    # expiry within the watchdog-enforced automation maximum.
    expires_at = datetime.fromisoformat(
        command["expires_at"].replace("Z", "+00:00")
    )
    remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
    assert 0 < remaining <= pokemon_module.AGENT_PAUSE_LEASE_SECONDS
    assert (
        pokemon_module.AGENT_PAUSE_LEASE_SECONDS
        <= pokemon_module.AUTOMATION_PAUSE_MAX_SECONDS
    )


def test_agent_pause_hold_requires_explicit_intent(tmp_path):
    (tmp_path / "status.json").write_text(
        json.dumps({"running": True, "pid": os.getpid(), "port": 9999})
    )

    result = json.loads(
        PokemonAgent().perform(
            action="pause", hold=True, runtime_dir=str(tmp_path)
        )
    )

    assert result["status"] == "success"
    command = json.loads(
        (tmp_path / "control.jsonl").read_text().splitlines()[-1]
    )
    assert command["kind"] == "operator_hold"
    assert command["persistent"] is True
    assert command["owner"] == "agent-cli"
    assert "expires_at" not in command


def test_runtime_lock_rejects_second_owner(tmp_path):
    first = acquire_runtime_lock(tmp_path, "first")
    try:
        with pytest.raises(RuntimeError, match="Another Pokemon player"):
            acquire_runtime_lock(tmp_path, "second")
    finally:
        first.close()


def test_public_status_redacts_private_paths(tmp_path):
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "running": True,
                "pid": os.getpid(),
                "port": 9999,
                "rom_path": "/private/Pokemon Red.gb",
                "rom_sha256": "secret-hash",
                "runtime_dir": str(tmp_path),
                "instance_id": "private-instance",
                "current_clip": str(tmp_path / "clips" / "clip-1.mp4"),
            }
        )
    )

    status = public_runtime_status(tmp_path)

    assert status["running"] is True
    assert status["current_clip"] == "clip-1.mp4"
    for key in ("pid", "rom_path", "rom_sha256", "runtime_dir", "instance_id"):
        assert key not in status


def test_clip_listing_hides_partial_files_and_reads_manifest(tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / ".clip-0001-20260711-120000.mp4.partial.mp4").write_bytes(b"partial")
    completed = clips / "clip-0001-20260711-120000.mp4"
    completed.write_bytes(b"video")
    completed.with_suffix(".json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": completed.name,
                "sha256": "test-hash",
                "duration_seconds": 12.5,
                "reason": "badge",
                "game_state": {"location": "Pewter Gym"},
            }
        )
    )

    result = list_clips(tmp_path)

    assert [clip["name"] for clip in result] == [completed.name]
    assert result[0]["duration_seconds"] == 12.5
    assert result[0]["location"] == "Pewter Gym"


class FakeStateEmulator:
    def __init__(self):
        self.memory = bytearray(65536)
        self.loaded = []
        self.released = []
        self.ticks = 0

    def save_state(self, handle):
        handle.write(b"valid-state")

    def load_state(self, handle):
        self.loaded.append(handle.read())

    def button_release(self, button):
        self.released.append(button)

    def tick(self):
        self.ticks += 1
        return True


def test_running_client_hotloads_verified_git_state(tmp_path):
    class HotloadEmulator(FakeStateEmulator):
        def __init__(self):
            super().__init__()
            self.screen = SimpleNamespace(
                image=SimpleNamespace(copy=lambda: b"frame")
            )
            self.events = []

        def send_input(self, event):
            self.events.append(event)

        def set_emulation_speed(self, speed):
            self.speed = speed

    class HotloadReader:
        def __init__(self, memory):
            del memory

        def snapshot(self):
            return {
                "game_id": "gold",
                "map_id": 0x0B03,
                "map_group": 0x0B,
                "map_number": 0x03,
                "location": "Goldenrod Gym",
                "coordinates": {"x": 8, "y": 4},
                "badges": ["Zephyr", "Hive"],
                "elite_four_completed": False,
                "red_defeated": False,
            }

    class Archive:
        def load(self, commitish):
            assert commitish == "a" * 12
            return (
                "a" * 40,
                {"checkpoint_id": "state-20260815-120000-000001"},
                b"git-state",
            )

    rom = tmp_path / "Pokemon Gold.gbc"
    rom.write_bytes(b"rom")
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.git_checkpoint_archive = Archive()
    runner.rom = rom
    runner.rom_sha256 = file_sha256(rom)
    runner.pyboy = HotloadEmulator()
    runner.player = ActionPlayer()
    runner.memory_reader_class = HotloadReader
    runner.game_id = "gold"
    runner.control_mode = "ai"
    runner.resume_mode = "ai"
    runner.control_generation = 0
    runner.pause_kind = None
    runner.pause_owner = None
    runner.pause_expires_at = None
    runner.emulator_pause_requested = False
    runner.navigation_memory = SimpleNamespace(cancel_pending=lambda: None)
    runner.decision_positions = deque()
    runner.last_crowd_advisory_position = None
    runner.decision_pending = False
    runner.committed_route = None
    runner.last_progress_marker = None
    runner.status = {
        "brain_status": "idle",
        "game_state": {},
        "completed": False,
    }
    runner._save_latest_frame = lambda image: None

    resolved = runner._hotload_git_checkpoint("a" * 12)

    assert resolved == "a" * 40
    assert runner.pyboy.loaded[-1] == b"git-state"
    assert runner.status["loaded_state"] == "git:" + "a" * 40
    assert runner.status["game_state"]["location"] == "Goldenrod Gym"
    assert runner.status["last_rewind"]["checkpoint_id"].endswith("000001")


def test_checkpoint_is_atomic_and_manifested(tmp_path):
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.states_dir = tmp_path
    runner.pyboy = FakeStateEmulator()
    runner.player = ActionPlayer()
    runner.status = {"rom_sha256": "rom-hash", "game_state": {}}

    checkpoint = runner._save_checkpoint("test boundary")
    manifest = json.loads(checkpoint.with_suffix(".json").read_text())

    assert checkpoint.read_bytes() == b"valid-state"
    assert manifest["sha256"] == file_sha256(checkpoint)
    assert manifest["rom_sha256"] == "rom-hash"
    assert manifest["reason"] == "test boundary"
    assert list(tmp_path.glob("*.tmp")) == []
    assert set(runner.pyboy.released) == {
        "a",
        "b",
        "start",
        "select",
        "up",
        "down",
        "left",
        "right",
    }
    assert runner.pyboy.ticks == 1


def test_terminal_checkpoint_survives_closed_window(tmp_path):
    class ClosedWindowEmulator(FakeStateEmulator):
        def tick(self):
            self.ticks += 1
            return False

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.states_dir = tmp_path
    runner.pyboy = ClosedWindowEmulator()
    runner.player = ActionPlayer()
    runner.status = {"rom_sha256": "rom-hash", "game_state": {}}

    checkpoint = runner._save_checkpoint("window closed", allow_stopped=True)

    assert checkpoint.read_bytes() == b"valid-state"
    assert runner.pyboy.ticks == 1


def test_paused_runner_pumps_window_events_without_applying_input():
    class ClosedWindowEmulator:
        ticks = 0

        def tick(self):
            self.ticks += 1
            return False

    class InputSpy:
        ticks = 0

        def tick(self, pyboy):
            del pyboy
            self.ticks += 1

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.control_mode = "paused"
    runner.decision_pending = False
    runner.pyboy = ClosedWindowEmulator()
    runner.player = InputSpy()

    assert runner._tick_emulator() is False
    assert runner.pyboy.ticks == 1
    assert runner.player.ticks == 0


def test_resume_skips_corrupt_newest_checkpoint(tmp_path):
    older = tmp_path / "state-20260711-120000-000001.state"
    older.write_bytes(b"older-valid")
    older.with_suffix(".json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "rom_sha256": "rom-hash",
                "sha256": file_sha256(older),
                "created_at": "2026-07-11T12:00:00+00:00",
            }
        )
    )
    newer = tmp_path / "state-20260711-120001-000001.state"
    newer.write_bytes(b"corrupt")
    newer.with_suffix(".json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "rom_sha256": "rom-hash",
                "sha256": "wrong",
                "created_at": "2026-07-11T12:01:00+00:00",
            }
        )
    )
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.args = SimpleNamespace(resume=True)
    runner.runtime_dir = tmp_path
    runner.states_dir = tmp_path
    runner.pyboy = FakeStateEmulator()
    runner.player = ActionPlayer()
    runner.status = {"rom_sha256": "rom-hash"}

    selected = runner._load_latest_state()

    assert selected == older
    assert runner.pyboy.loaded[-1] == b"older-valid"
    assert runner.pyboy.ticks == 1


def test_interrupted_checkpoint_requires_matching_pending_provenance(tmp_path):
    state = tmp_path / "state-20260711-120000-000001.state"
    state.write_bytes(b"recoverable")
    state.with_suffix(".pending.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state_name": state.name,
                "created_at": "2026-07-11T12:00:00+00:00",
                "reason": "interrupted",
                "rom_sha256": "rom-hash",
            }
        )
    )
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.states_dir = tmp_path
    runner.status = {"rom_sha256": "rom-hash"}

    runner._recover_orphaned_states()

    manifest = json.loads(state.with_suffix(".json").read_text())
    assert manifest["recovered"] is True
    assert manifest["rom_sha256"] == "rom-hash"
    assert manifest["sha256"] == file_sha256(state)


def test_ambiguous_orphaned_checkpoint_is_quarantined(tmp_path):
    state = tmp_path / "state-20260711-120000-000001.state"
    state.write_bytes(b"unknown")
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.states_dir = tmp_path
    runner.status = {"rom_sha256": "rom-hash"}

    runner._recover_orphaned_states()

    assert not state.exists()
    assert list((tmp_path / "quarantine").glob("*.orphan"))


def test_cartridge_ram_is_rom_scoped_and_manifested(tmp_path):
    class RamEmulator:
        def stop(self, save, ram_file):
            assert save is True
            ram_file.write(b"battery-ram")

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.rom_sha256 = "a" * 64
    runner.ram_path = tmp_path / f"pokemon-red-{runner.rom_sha256[:16]}.ram"
    runner.pyboy = RamEmulator()
    runner.status = {}

    runner._save_ram_and_stop()

    manifest = json.loads(runner.ram_path.with_suffix(".json").read_text())
    assert manifest["rom_sha256"] == runner.rom_sha256
    assert manifest["sha256"] == file_sha256(runner.ram_path)
    assert runner._validated_ram_path() == runner.ram_path


def test_invalid_utf8_ram_manifest_is_quarantined(tmp_path):
    scoped = tmp_path / f"pokemon-red-{'b' * 16}.ram"
    scoped.write_bytes(b"ram")
    scoped.with_suffix(".json").write_bytes(b"\xff\xfeinvalid")
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.rom_sha256 = "b" * 64
    runner.ram_path = scoped
    runner.status = {}

    assert runner._validated_ram_path() is None
    assert not scoped.exists()
    assert list((tmp_path / "quarantine").glob("*.invalid"))


def test_ram_manifest_failure_restores_previous_verified_pair(monkeypatch, tmp_path):
    class NewRamEmulator:
        def stop(self, save, ram_file):
            assert save is True
            ram_file.write(b"new-ram")

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.rom_sha256 = "d" * 64
    runner.ram_path = tmp_path / f"pokemon-red-{runner.rom_sha256[:16]}.ram"
    runner.ram_path.write_bytes(b"old-ram")
    old_manifest = {
        "schema_version": 1,
        "rom_sha256": runner.rom_sha256,
        "sha256": file_sha256(runner.ram_path),
    }
    runner.ram_path.with_suffix(".json").write_text(json.dumps(old_manifest))
    runner.pyboy = NewRamEmulator()
    runner.status = {}
    real_atomic_write = pokemon_module.atomic_write_json

    def fail_new_manifest(path, value):
        if path == runner.ram_path.with_suffix(".json") and value.get("bytes") == 7:
            raise OSError("disk full")
        real_atomic_write(path, value)

    monkeypatch.setattr(pokemon_module, "atomic_write_json", fail_new_manifest)

    with pytest.raises(OSError, match="disk full"):
        runner._save_ram_and_stop()

    assert runner.ram_path.read_bytes() == b"old-ram"
    restored = json.loads(runner.ram_path.with_suffix(".json").read_text())
    assert restored["sha256"] == old_manifest["sha256"]


def test_legacy_ram_is_migrated_only_when_rom_context_matches(tmp_path):
    legacy = tmp_path / "pokemon-red.ram"
    legacy.write_bytes(b"\x00" * 32768)
    rom_sha = "e" * 64
    (tmp_path / "legacy-ram-provenance.json").write_text(
        json.dumps({"rom_sha256": rom_sha})
    )
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.rom_sha256 = rom_sha
    runner.ram_path = tmp_path / f"pokemon-red-{rom_sha[:16]}.ram"
    runner.status = {"rom_title": "POKEMON RED"}

    assert runner._validated_ram_path() == runner.ram_path
    assert not legacy.exists()
    assert runner.ram_path.stat().st_size == 32768
    manifest = json.loads(runner.ram_path.with_suffix(".json").read_text())
    assert manifest["migrated_from"] == "pokemon-red.ram"


def test_ram_recovery_handles_split_backup_pair(tmp_path):
    rom_sha = "f" * 64
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.rom_sha256 = rom_sha
    runner.ram_path = tmp_path / f"pokemon-red-{rom_sha[:16]}.ram"
    runner.status = {}
    backup_ram, _ = runner._ram_backup_paths()
    backup_ram.write_bytes(b"verified-old")
    runner.ram_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "rom_sha256": rom_sha,
                "sha256": file_sha256(backup_ram),
            }
        )
    )

    assert runner._validated_ram_path() == runner.ram_path
    assert runner.ram_path.read_bytes() == b"verified-old"


def test_contradictory_legacy_manifest_is_never_overridden_by_size_heuristic(tmp_path):
    legacy = tmp_path / "pokemon-red.ram"
    legacy.write_bytes(b"\x00" * 32768)
    legacy.with_suffix(".json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "rom_sha256": "other-rom",
                "sha256": file_sha256(legacy),
            }
        )
    )
    rom_sha = "1" * 64
    (tmp_path / "legacy-ram-provenance.json").write_text(
        json.dumps({"rom_sha256": rom_sha})
    )
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.rom = tmp_path / "Pokemon Red.gb"
    runner.rom_sha256 = rom_sha
    runner.ram_path = tmp_path / f"pokemon-red-{rom_sha[:16]}.ram"
    runner.status = {"rom_title": "POKEMON RED"}

    assert runner._validated_ram_path() is None
    assert legacy.exists()
    assert not runner.ram_path.exists()


def test_immutable_legacy_provenance_survives_rewritten_current_config(tmp_path):
    legacy = tmp_path / "pokemon-red.ram"
    legacy.write_bytes(b"\x00" * 32768)
    (tmp_path / "legacy-ram-provenance.json").write_text(
        json.dumps({"rom_sha256": "original-rom"})
    )
    (tmp_path / "config.json").write_text(
        json.dumps({"rom_sha256": "new-rom", "rom_path": "/new/rom.gb"})
    )
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.rom = tmp_path / "new-rom.gb"
    runner.rom_sha256 = "new-rom"
    runner.ram_path = tmp_path / "pokemon-red-new-rom.ram"
    runner.status = {"rom_title": "POKEMON RED"}

    assert runner._validated_ram_path() is None
    assert legacy.exists()
    assert not runner.ram_path.exists()


def test_released_layout_seeds_legacy_provenance_from_prior_status(tmp_path):
    legacy = tmp_path / "pokemon-red.ram"
    legacy.write_bytes(b"\x00" * 32768)
    rom_sha = "2" * 64
    (tmp_path / "config.json").write_text(
        json.dumps({"rom_path": "/owned/Pokemon Red.gb"})
    )
    (tmp_path / "status.json").write_text(
        json.dumps({"rom_sha256": rom_sha})
    )

    seed_legacy_ram_provenance(tmp_path)

    provenance = json.loads(
        (tmp_path / "legacy-ram-provenance.json").read_text()
    )
    assert provenance["rom_sha256"] == rom_sha
    assert provenance["rom_path"] == "/owned/Pokemon Red.gb"


def test_controller_normalization_failure_does_not_quarantine_valid_state(tmp_path):
    state = tmp_path / "state-20260711-120000-000001.state"
    state.write_bytes(b"valid")
    state.with_suffix(".json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-07-11T12:00:00+00:00",
                "rom_sha256": "rom-hash",
                "sha256": file_sha256(state),
            }
        )
    )

    class StopsDuringNormalization(FakeStateEmulator):
        def tick(self):
            return False

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.args = SimpleNamespace(resume=True)
    runner.runtime_dir = tmp_path
    runner.states_dir = tmp_path
    runner.pyboy = StopsDuringNormalization()
    runner.player = ActionPlayer()
    runner.status = {"rom_sha256": "rom-hash"}

    with pytest.raises(RuntimeError, match="normalizing controller"):
        runner._load_latest_state()

    assert state.exists()
    assert state.with_suffix(".json").exists()


def test_stale_ai_decision_is_discarded_after_manual_takeover():
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.brain_results = queue.Queue()
    runner.brain_results.put(
        {
            "decision_id": 1,
            "generation": 0,
            "decision": {
                "phase": "overworld",
                "observation": "walk north",
                "objective": "leave town",
                "reason": "path",
                "buttons": ["up"],
                "checkpoint": False,
            },
        }
    )
    runner.pending_decision_id = 1
    runner.decision_pending = True
    runner.control_generation = 1
    runner.control_mode = "manual"
    runner.emulator_pause_requested = False
    runner.last_decision_finished = 0
    runner.status = {}
    runner.history = []
    runner.total_decisions = 0

    runner._apply_brain_result()

    assert runner.decision_pending is False
    assert runner.history == []
    assert runner.status["last_discarded_decision"]["decision_id"] == 1
    assert runner.status["brain_status"] == "manual"


def test_stale_ai_decision_is_discarded_when_bugsy_helper_becomes_active(
    tmp_path,
):
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.brain_results = queue.Queue()
    runner.brain_results.put(
        {
            "decision_id": 2,
            "generation": 0,
            "decision": {
                "phase": "overworld",
                "observation": "walk toward Bugsy",
                "objective": "challenge the gym leader",
                "reason": "approach",
                "buttons": ["up"],
                "checkpoint": False,
            },
        }
    )
    runner.pending_decision_id = 2
    runner.decision_pending = True
    runner.control_generation = 0
    runner.control_mode = "ai"
    runner.emulator_pause_requested = False
    runner.last_decision_requested = 10.0
    runner.last_decision_finished = 5.0
    runner.status = {
        "game_state": {
            "game_id": "gold",
            "map_group": 0x08,
            "map_number": 0x05,
            "in_battle": True,
            "badges": ["Zephyr"],
            "screen_text": "FIGHT | PACK RUN",
        }
    }
    runner.navigation_memory = NavigationMemory(
        tmp_path / "navigation-memory.json"
    )
    runner.player = None

    runner._apply_brain_result()

    assert runner.decision_pending is False
    assert runner.status["last_discarded_decision"] == {
        "decision_id": 2,
        "reason": "trusted route became applicable",
        "timestamp": runner.status["last_discarded_decision"]["timestamp"],
    }
    assert runner.status["brain_status"] == "idle"
    assert runner.last_decision_finished == 0


def test_recording_clock_emits_wall_clock_frame_count(monkeypatch):
    class FakeRecorder:
        fps = 30
        writes = 0

        def write(self, image):
            del image
            self.writes += 1
            return True

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.recorder = FakeRecorder()
    runner.next_record_at = 0
    runner.status = {}
    now = [0.0]
    monkeypatch.setattr(pokemon_module.time, "monotonic", lambda: now[0])

    for frame in range(360):
        now[0] = frame / 60
        runner._record_due_frames(object())

    assert 179 <= runner.recorder.writes <= 181
    assert runner.status.get("recording_frames_skipped", 0) == 0


def test_viewer_requires_same_origin_authenticated_controls(tmp_path):
    controls = queue.Queue()
    server = ViewerServer(tmp_path, 0, controls)
    server.start()
    base_url = f"http://127.0.0.1:{server.port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as unauthenticated:
            urllib.request.urlopen(f"{base_url}/api/status")
        assert unauthenticated.value.code == 403

        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )
        with pytest.raises(urllib.error.HTTPError) as missing_token:
            opener.open(f"{base_url}/")
        assert missing_token.value.code == 403

        with opener.open(f"{base_url}/?token={server.token}") as response:
            assert response.status == 200
            assert response.headers["X-Frame-Options"] == "DENY"

        with opener.open(f"{base_url}/api/status") as response:
            assert json.load(response)["running"] is False

        hostile = urllib.request.Request(
            f"{base_url}/api/control",
            data=b'{"action":"pause"}',
            headers={
                "Content-Type": "application/json",
                "Origin": "https://attacker.example",
            },
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as cross_origin:
            opener.open(hostile)
        assert cross_origin.value.code == 403
        assert controls.empty()

        authorized = urllib.request.Request(
            f"{base_url}/api/control",
            data=b'{"action":"pause"}',
            headers={
                "Content-Type": "application/json",
                "Origin": base_url,
            },
            method="POST",
        )
        with opener.open(authorized) as response:
            assert json.load(response)["status"] == "success"
        assert controls.get_nowait()["action"] == "pause"
    finally:
        server.stop()


def test_brain_worker_reports_base_sdk_exception_and_recovers(monkeypatch, tmp_path):
    instances = []

    class FakeBrain:
        backend = "sdk"

        def __init__(self, *args):
            del args
            self.recoveries = 0
            instances.append(self)

        def start(self):
            return None

        def decide(self, **kwargs):
            del kwargs
            raise Exception("session transport failed")

        def recover(self):
            self.recoveries += 1

        def close(self):
            return None

    monkeypatch.setattr(pokemon_module, "CopilotBrain", FakeBrain)
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.args = SimpleNamespace(
        model="gpt-5.6-sol",
        decision_timeout=30,
        reasoning_effort="medium",
    )
    runner.reasoning_effort = "medium"
    runner.runtime_dir = tmp_path
    runner.stop_event = pokemon_module.threading.Event()
    runner.brain_ready = pokemon_module.threading.Event()
    runner.brain_available = pokemon_module.threading.Event()
    runner.brain_requests = queue.Queue()
    runner.brain_results = queue.Queue()
    runner.status = {}
    runner.brain_requests.put(
        {
            "screenshot": str(tmp_path / "frame.png"),
            "game_state": {},
            "collision_map": None,
            "history": [],
            "decision_id": 7,
            "generation": 2,
        }
    )
    runner.brain_requests.put(None)

    runner._brain_loop()

    result = runner.brain_results.get_nowait()
    assert result["decision_id"] == 7
    assert result["generation"] == 2
    assert "session transport failed" in result["error"]
    assert runner.status["brain_failure_count"] == 1
    assert instances[0].recoveries == 1
    assert runner.brain_available.is_set()


def test_copilot_close_force_stops_hung_client(monkeypatch, tmp_path):
    class FakeSession:
        async def disconnect(self):
            return None

    class HungClient:
        forced = False

        async def stop(self):
            await asyncio.sleep(60)

        async def force_stop(self):
            self.forced = True

    monkeypatch.setattr(pokemon_module, "COPILOT_STOP_TIMEOUT_SECONDS", 0.01)
    brain = CopilotBrain.__new__(CopilotBrain)
    brain.runtime_dir = tmp_path
    brain.loop = asyncio.new_event_loop()
    brain.session = FakeSession()
    brain.client = HungClient()

    client = brain.client
    brain.close()

    assert client.forced is True
    assert brain.loop is None


def test_copilot_decision_retries_invalid_button_response(tmp_path):
    class FakeSession:
        def __init__(self):
            self.prompts = []
            self.responses = deque([
                '{"phase":"dialogue","buttons":[]}',
                '{"phase":"dialogue","buttons":["a"],"checkpoint":false}',
            ])

        async def send_and_wait(self, prompt, attachments, timeout):
            self.prompts.append(prompt)
            assert attachments[0]["mimeType"] == "image/png"
            assert timeout == 5.0
            return SimpleNamespace(
                data=SimpleNamespace(content=self.responses.popleft())
            )

    screenshot = tmp_path / "frame.png"
    screenshot.write_bytes(b"png")
    brain = CopilotBrain.__new__(CopilotBrain)
    brain.session = FakeSession()
    brain.session_decisions = 0
    brain.max_decisions_per_session = 10
    brain.timeout_seconds = 5

    decision = asyncio.run(brain._decide_sdk(screenshot, "base prompt"))

    assert decision["buttons"] == ["a"]
    assert brain.session_decisions == 2
    assert brain.session.prompts[0] == "base prompt"
    assert "CORRECTION:" in brain.session.prompts[1]


def test_copilot_close_force_stops_after_disconnect_error(monkeypatch):
    class BrokenSession:
        async def disconnect(self):
            raise RuntimeError("transport gone")

    class ClientSpy:
        stopped = False
        forced = False

        async def stop(self):
            self.stopped = True

        async def force_stop(self):
            self.forced = True

    monkeypatch.setattr(pokemon_module, "COPILOT_STOP_TIMEOUT_SECONDS", 0.05)
    brain = CopilotBrain.__new__(CopilotBrain)
    brain.loop = asyncio.new_event_loop()
    brain.current_task = None
    brain.session = BrokenSession()
    brain.client = ClientSpy()

    client = brain.client
    brain.close()

    assert client.stopped is True
    assert client.forced is True
    assert brain.loop is None


def test_copilot_operation_can_be_cancelled_from_runner_thread():
    brain = CopilotBrain.__new__(CopilotBrain)
    brain.loop = None
    brain.current_task = None
    started = threading.Event()
    cancelled = threading.Event()

    async def hanging_operation():
        started.set()
        await asyncio.sleep(60)

    def worker():
        brain.loop = asyncio.new_event_loop()
        try:
            brain._run_operation(hanging_operation(), timeout=60)
        except asyncio.CancelledError:
            cancelled.set()
        finally:
            brain.loop.close()
            brain.loop = None

    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(timeout=1)
    brain.cancel()
    thread.join(timeout=1)

    assert cancelled.is_set()
    assert not thread.is_alive()


def test_runner_stop_owns_brain_thread_until_exit():
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.stop_event = threading.Event()
    runner.brain_requests = queue.Queue()
    runner.status = {}

    class BrainSpy:
        cancelled = False

        def cancel(self):
            self.cancelled = True

    runner.brain = BrainSpy()
    runner.brain_thread = threading.Thread(target=runner.brain_requests.get)
    runner.brain_thread.start()

    runner._stop_brain_worker()

    assert runner.brain.cancelled is True
    assert runner.stop_event.is_set()
    assert not runner.brain_thread.is_alive()


def test_pending_ai_decision_free_runs_emulator_on_resume(monkeypatch):
    pyboy_module = ModuleType("pyboy")
    utils_module = ModuleType("pyboy.utils")

    class WindowEvent:
        PAUSE = "pause"
        UNPAUSE = "unpause"

    utils_module.WindowEvent = WindowEvent
    pyboy_module.utils = utils_module
    monkeypatch.setitem(sys.modules, "pyboy", pyboy_module)
    monkeypatch.setitem(sys.modules, "pyboy.utils", utils_module)

    class PlayerSpy:
        def release(self, pyboy):
            del pyboy

    class EmulatorSpy:
        events = []
        speed = None

        def send_input(self, event):
            self.events.append(event)

        def set_emulation_speed(self, speed):
            self.speed = speed

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.control_mode = "paused"
    runner.resume_mode = "ai"
    runner.decision_pending = True
    runner.control_generation = 0
    runner.paused = True
    runner.emulator_pause_requested = True
    runner.player = PlayerSpy()
    runner.pyboy = EmulatorSpy()
    runner.status = {}
    runner.last_decision_finished = 0

    runner._set_control_mode("ai")

    assert runner.control_mode == "ai"
    assert runner.emulator_pause_requested is False
    assert len(runner.pyboy.events) == 1
    assert runner.pyboy.speed == 0


def test_shutdown_failures_do_not_skip_remaining_cleanup(tmp_path):
    calls = []

    class PlayerFailure:
        def release(self, pyboy):
            del pyboy
            raise OSError("controller failed")

    class RecorderFailure:
        frames_written = 0
        started_at = None

        def finish(self):
            raise OSError("recorder failed")

    class ViewerSpy:
        def stop(self):
            calls.append("viewer")

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.stop_event = threading.Event()
    runner.player = PlayerFailure()
    runner.pyboy = object()
    runner.recorder = RecorderFailure()
    runner.viewer = ViewerSpy()
    runner.status = {"lifecycle": "ready"}
    runner.runtime_dir = tmp_path
    runner._save_checkpoint = lambda *args, **kwargs: calls.append("checkpoint")
    runner._stop_brain_worker = lambda: calls.append("brain")
    runner._save_ram_and_stop = lambda: calls.append("ram")
    runner._write_status = lambda: calls.append("status")

    runner._shutdown_runtime("test shutdown")

    assert calls == ["checkpoint", "brain", "viewer", "ram", "status"]
    assert runner.status["lifecycle"] == "failed"
    assert "controller failed" in runner.status["last_error"]
    assert "recorder failed" in runner.status["last_error"]


def test_recorder_drops_frame_instead_of_blocking_full_queue():
    class ProcessSpy:
        stdin = object()

        def poll(self):
            return None

    class Image:
        def convert(self, mode):
            assert mode == "RGB"
            return self

        def tobytes(self):
            return b"frame"

    recorder = ClipRecorder.__new__(ClipRecorder)
    recorder.process = ProcessSpy()
    recorder.writer_error = None
    recorder.frame_queue = queue.Queue(maxsize=1)
    recorder.frame_queue.put_nowait(b"already queued")
    recorder.frames_written = 0
    recorder.frames_dropped = 0

    assert recorder.write(Image()) is False
    assert recorder.frames_written == 0
    assert recorder.frames_dropped == 1


def test_stalled_recorder_writer_is_unblocked_by_process_termination(monkeypatch):
    entered_write = threading.Event()
    terminated = threading.Event()

    class BlockingStdin:
        closed = False

        def write(self, payload):
            del payload
            entered_write.set()
            terminated.wait()
            raise BrokenPipeError("terminated")

    class StalledProcess:
        stdin = BlockingStdin()
        returncode = None

        def terminate(self):
            self.returncode = -15
            terminated.set()

        def kill(self):
            self.returncode = -9
            terminated.set()

        def wait(self, timeout):
            del timeout
            if self.returncode is None:
                raise pokemon_module.subprocess.TimeoutExpired("ffmpeg", 0.01)
            return self.returncode

    monkeypatch.setattr(pokemon_module, "RECORDER_WRITER_TIMEOUT_SECONDS", 0.01)
    recorder = ClipRecorder.__new__(ClipRecorder)
    recorder.process = StalledProcess()
    recorder.frame_queue = queue.Queue(maxsize=2)
    recorder.frame_queue.put_nowait(b"frame")
    recorder.writer_error = None
    recorder.frames_dropped = 0
    recorder.writer_thread = threading.Thread(target=recorder._writer_loop)
    recorder.writer_thread.start()
    assert entered_write.wait(timeout=1)

    recorder._stop_writer(recorder.process)

    assert terminated.is_set()
    assert not recorder.writer_thread.is_alive()


def test_copilot_runtime_preparation_is_bounded(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pokemon_module.subprocess, "run", fake_run)

    ensure_copilot_runtime(timeout_seconds=42)

    assert calls[0][0][-2:] == ["copilot", "download-runtime"]
    assert calls[0][1]["timeout"] == 42


def test_screenshot_retention_never_deletes_inflight_frame(tmp_path):
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.screens_dir = tmp_path
    for index in range(31):
        screenshot = tmp_path / f"decision-old-{index:03d}.png"
        screenshot.write_bytes(b"old")
        os.utime(screenshot, ns=(index + 1, index + 1))
    current = tmp_path / "decision-new-run-00000001.png"
    current.write_bytes(b"current")

    runner._prune_decision_screenshots(current, keep=30)

    remaining = list(tmp_path.glob("decision-*.png"))
    assert current in remaining
    assert len(remaining) == 30
    assert not (tmp_path / "decision-old-000.png").exists()


def test_runtime_parser_and_command_support_supervision(tmp_path):
    args = build_parser().parse_args(
        [
            "supervise",
            "--rom",
            str(tmp_path / "Pokemon Red.gb"),
            "--runtime-dir",
            str(tmp_path),
            "--state-repo",
            str(tmp_path),
            "--port",
            "9999",
            "--youtube-chat-hints",
            "--stuck-web-research",
        ]
    )
    args.instance_id = "test-instance"

    command = runtime_command(args, open_viewer=True)

    assert args.command == "supervise"
    assert command[2] == "openrappter.agents.pokemon_agent"
    assert command[3] == "run"
    assert "--supervised" in command
    assert "--max-clips" in command
    assert "--max-storage-gb" in command
    assert "--state-repo" in command
    assert "--youtube-chat-hints" in command
    assert "--stuck-web-research" in command


def test_supervisor_restarts_failed_child_then_stops_cleanly(monkeypatch, tmp_path):
    exit_codes = iter([1, 0])
    children = []

    class FakeChild:
        def __init__(self, command, **kwargs):
            del kwargs
            self.command = command
            self.pid = 1000 + len(children)
            self.returncode = None
            children.append(self)

        def wait(self, timeout=None):
            del timeout
            if self.returncode is None:
                self.returncode = next(exit_codes)
            return self.returncode

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(pokemon_module.subprocess, "Popen", FakeChild)
    monkeypatch.setattr(pokemon_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pokemon_module.signal, "signal", lambda *args: None)
    args = build_parser().parse_args(
        [
            "supervise",
            "--rom",
            str(tmp_path / "Pokemon Red.gb"),
            "--runtime-dir",
            str(tmp_path),
            "--instance-id",
            "supervisor-test",
        ]
    )

    assert supervisor_main(args) == 0
    assert len(children) == 2
    assert json.loads((tmp_path / "desired.json").read_text())["running"] is False
    assert json.loads((tmp_path / "supervisor.json").read_text())["running"] is False


def test_supervisor_circuit_cools_down_then_retries(monkeypatch, tmp_path):
    exit_codes = iter([1] * 11 + [0])
    children = []

    class FakeChild:
        def __init__(self, command, **kwargs):
            del command, kwargs
            self.pid = 2000 + len(children)
            self.returncode = None
            children.append(self)

        def wait(self, timeout=None):
            del timeout
            if self.returncode is None:
                self.returncode = next(exit_codes)
            return self.returncode

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(pokemon_module.subprocess, "Popen", FakeChild)
    monkeypatch.setattr(pokemon_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pokemon_module.signal, "signal", lambda *args: None)
    monkeypatch.setattr(
        pokemon_module,
        "SUPERVISOR_RESTART_COOLDOWN_SECONDS",
        0,
    )
    args = build_parser().parse_args(
        [
            "supervise",
            "--rom",
            str(tmp_path / "Pokemon Red.gb"),
            "--runtime-dir",
            str(tmp_path),
            "--instance-id",
            "circuit-test",
        ]
    )

    assert supervisor_main(args) == 0
    assert len(children) == 12


def test_supervisor_does_not_retry_nonretryable_startup_failure(
    monkeypatch,
    tmp_path,
):
    children = []

    class ConfigFailure:
        def __init__(self, command, **kwargs):
            del command, kwargs
            self.pid = 4040
            self.returncode = None
            children.append(self)
            (tmp_path / "status.json").write_text(
                json.dumps(
                    {
                        "pid": self.pid,
                        "instance_id": "config-failure",
                        "lifecycle": "failed",
                        "restartable": False,
                        "failure_kind": "configuration",
                        "last_error": (
                            "Cannot bind authenticated viewer to "
                            "127.0.0.1:8765: address in use"
                        ),
                    }
                )
            )

        def wait(self, timeout=None):
            del timeout
            self.returncode = 1
            return self.returncode

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 1

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(pokemon_module.subprocess, "Popen", ConfigFailure)
    monkeypatch.setattr(pokemon_module.signal, "signal", lambda *args: None)
    args = build_parser().parse_args(
        [
            "supervise",
            "--rom",
            str(tmp_path / "Pokemon Red.gb"),
            "--runtime-dir",
            str(tmp_path),
            "--instance-id",
            "config-failure",
        ]
    )

    assert supervisor_main(args) == 1
    assert len(children) == 1
    status = json.loads((tmp_path / "status.json").read_text())
    assert "address in use" in status["last_error"]
    assert status["restartable"] is False


def test_runner_classifies_configuration_startup_failure(
    monkeypatch,
    tmp_path,
):
    class FailedRunner:
        stream_generation = None

        def __init__(self, args):
            del args
            self.stop_event = threading.Event()
            self.brain_ready = threading.Event()
            self.brain = None

        def run(self):
            raise StartupConfigurationError("fixed viewer port is unavailable")

    monkeypatch.setattr(pokemon_module, "PokemonRunner", FailedRunner)
    monkeypatch.setattr(pokemon_module.signal, "signal", lambda *args: None)

    assert runner_main(
        [
            "run",
            "--rom",
            str(tmp_path / "Pokemon Red.gb"),
            "--runtime-dir",
            str(tmp_path),
            "--instance-id",
            "configuration-runner",
        ]
    ) == 1
    status = json.loads((tmp_path / "status.json").read_text())
    assert status["restartable"] is False
    assert status["failure_kind"] == "configuration"
    assert status["last_error"] == "fixed viewer port is unavailable"


def test_outer_timeout_terminates_entire_isolated_process_group(monkeypatch):
    signals = []
    waits = []

    class HungGroupLeader:
        pid = 9001
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            waits.append(timeout)
            if len(waits) == 1:
                raise pokemon_module.subprocess.TimeoutExpired("supervisor", timeout)
            self.returncode = -9
            return self.returncode

        def terminate(self):
            raise AssertionError("must signal the isolated process group")

        def kill(self):
            raise AssertionError("must kill the isolated process group")

    monkeypatch.setattr(
        pokemon_module.os,
        "killpg",
        lambda pid, requested_signal: signals.append((pid, requested_signal)),
    )

    assert terminate_isolated_process_group(HungGroupLeader()) == -9
    assert signals == [
        (9001, pokemon_module.signal.SIGTERM),
        (9001, pokemon_module.signal.SIGKILL),
    ]
    assert waits[0] > pokemon_module.SUPERVISOR_SHUTDOWN_TIMEOUT_SECONDS
    assert waits[1] == 10


def test_retention_removes_only_old_generated_artifacts(tmp_path):
    clips_dir = tmp_path / "clips"
    states_dir = tmp_path / "states"
    screens_dir = tmp_path / "screens"
    clips_dir.mkdir()
    states_dir.mkdir()
    screens_dir.mkdir()
    for index in range(4):
        clip = clips_dir / f"clip-{index:04d}-20260711-120000.mp4"
        clip.write_bytes(b"clip")
        clip.with_suffix(".json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "name": clip.name,
                    "sha256": "clip-hash",
                    "reason": "routine",
                }
            )
        )
        state = states_dir / f"state-20260711-12000{index}-000000.state"
        state.write_bytes(b"state")
        state.with_suffix(".json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "sha256": file_sha256(state),
                    "rom_sha256": "rom-hash",
                    "reason": "routine",
                }
            )
        )
        os.utime(clip, ns=(index + 1, index + 1))
        os.utime(state, ns=(index + 1, index + 1))
    unknown = clips_dir / "user-note.txt"
    unknown.write_text("preserve me")
    unknown_clip = clips_dir / "clip-vacation.mp4"
    unknown_clip.write_bytes(b"user video")
    unknown_state = states_dir / "state-backup.state"
    unknown_state.write_bytes(b"user state")

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.states_dir = states_dir
    runner.screens_dir = screens_dir
    runner.recorder = SimpleNamespace(clips_dir=clips_dir, partial_path=None)
    runner.max_clips = 2
    runner.max_states = 2
    runner.max_storage_bytes = 1024**3
    runner.min_free_bytes = 0
    runner.status = {"rom_sha256": "rom-hash"}

    runner._enforce_retention()

    assert (
        len([path for path in clips_dir.glob("clip-*.mp4") if "20260711" in path.name])
        == 2
    )
    assert (
        len(
            [
                path
                for path in states_dir.glob("state-*.state")
                if "20260711" in path.name
            ]
        )
        == 2
    )
    assert unknown.read_text() == "preserve me"
    assert unknown_clip.read_bytes() == b"user video"
    assert unknown_state.read_bytes() == b"user state"
    assert runner.status["retained_clips"] == 2
    assert runner.status["retained_states"] == 2


def test_oversized_player_log_is_truncated_in_place(tmp_path):
    log_path = tmp_path / "player.log"
    log_path.write_bytes(b"x" * 64)
    descriptor = os.open(log_path, os.O_WRONLY | os.O_APPEND)
    try:
        assert pokemon_module.truncate_regular_file_if_oversized(
            log_path,
            16,
        )
        assert log_path.stat().st_size == 0
        os.write(descriptor, b"next")
    finally:
        os.close(descriptor)

    assert log_path.read_bytes() == b"next"


def test_latest_frame_recovers_once_after_storage_exhaustion(tmp_path):
    class Image:
        saves = 0

        def save(self, path, format):
            assert format == "PNG"
            self.saves += 1
            if self.saves == 1:
                raise OSError(errno.ENOSPC, "disk full")
            Path(path).write_bytes(b"png")

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.status = {}
    cleanup_calls = []
    runner._enforce_retention = lambda: cleanup_calls.append(True)

    assert runner._save_latest_frame(Image()) is True
    assert cleanup_calls == [True]
    assert (tmp_path / "latest.png").read_bytes() == b"png"
    assert runner.status["storage_write_error"] is None
    assert runner.status["storage_recovered_at"]


def test_decision_request_backs_off_when_screenshot_cannot_be_saved(
    tmp_path,
):
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.screens_dir = tmp_path
    runner.run_id = "storage"
    runner.decision_sequence = 0
    runner.status = {}
    runner.brain_requests = queue.Queue(maxsize=1)
    runner._save_png = lambda image, destination: False

    runner._request_decision(object(), {}, None)

    assert runner.brain_requests.empty()
    assert runner.decision_sequence == 0
    assert runner.status["brain_status"] == "storage-pressure"


def test_supervisor_escalates_hung_child_on_stop():
    stop_requested = threading.Event()
    stop_requested.set()

    class HungChild:
        terminated = False
        killed = False

        def poll(self):
            if self.killed:
                return -9
            if self.terminated:
                return 0
            return None

        def wait(self, timeout):
            if not self.terminated and not self.killed:
                raise pokemon_module.subprocess.TimeoutExpired("child", timeout)
            return -9 if self.killed else 0

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    child = HungChild()

    assert wait_for_supervised_child(child, stop_requested) == (0, False)
    assert child.terminated is True


def test_running_stop_waits_for_child_to_consume_control(tmp_path):
    (tmp_path / "desired.json").write_text(json.dumps({"running": True}))

    pokemon_module.append_control(tmp_path, {"action": "stop"})

    assert json.loads((tmp_path / "desired.json").read_text())["running"] is True
    assert json.loads((tmp_path / "control.jsonl").read_text())["action"] == "stop"


def test_new_supervisor_cursor_skips_historical_stop(tmp_path):
    control = tmp_path / "control.jsonl"
    control.write_text(
        '{"action":"checkpoint"}\n{"action":"stop"}\n',
        encoding="utf-8",
    )
    (tmp_path / pokemon_module.CONTROL_CURSOR_NAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "offset": len('{"action":"checkpoint"}\n'),
                "file_id": list(
                    (control.stat().st_dev, control.stat().st_ino)
                ),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ),
        encoding="utf-8",
    )

    pokemon_module.initialize_control_cursor_at_eof(tmp_path)

    cursor = json.loads(
        (tmp_path / pokemon_module.CONTROL_CURSOR_NAME).read_text()
    )
    assert cursor["offset"] == control.stat().st_size
    assert cursor["file_id"] == [control.stat().st_dev, control.stat().st_ino]


def test_agent_can_stop_supervisor_between_child_retries(tmp_path):
    (tmp_path / "desired.json").write_text(json.dumps({"running": True}))
    (tmp_path / "supervisor.json").write_text(
        json.dumps({"running": True, "pid": os.getpid()})
    )

    result = json.loads(
        PokemonAgent().perform(action="stop", runtime_dir=str(tmp_path))
    )

    assert result["status"] == "success"
    assert json.loads((tmp_path / "desired.json").read_text())["running"] is False


def test_start_reports_stopping_supervisor_as_retryable_not_running(
    monkeypatch,
    tmp_path,
):
    (tmp_path / "desired.json").write_text(json.dumps({"running": False}))
    (tmp_path / "supervisor.json").write_text(
        json.dumps({"running": True, "pid": 1234})
    )
    monkeypatch.setattr(pokemon_module, "process_is_alive", lambda _pid: True)
    monkeypatch.setattr(
        pokemon_module,
        "wait_for_stopping_supervisor",
        lambda _runtime_dir: False,
    )

    result = json.loads(
        PokemonAgent().perform(action="start", runtime_dir=str(tmp_path))
    )

    assert result["status"] == "error"
    assert result["retryable"] is True
    assert "still stopping" in result["message"]
    assert "already running" not in result["message"]


def test_stopping_supervisor_wait_is_bounded_and_observes_exit(
    monkeypatch,
    tmp_path,
):
    (tmp_path / "desired.json").write_text(json.dumps({"running": False}))
    (tmp_path / "supervisor.json").write_text(json.dumps({"pid": 1234}))
    alive = iter([True, True, False])
    sleeps: list[float] = []
    monkeypatch.setattr(
        pokemon_module,
        "process_is_alive",
        lambda _pid: next(alive),
    )
    monkeypatch.setattr(pokemon_module.time, "sleep", sleeps.append)
    monkeypatch.setattr(pokemon_module.time, "monotonic", lambda: 0.0)

    assert wait_for_stopping_supervisor(tmp_path, timeout_seconds=1) is True
    assert sleeps == [0.1]


def test_failed_child_termination_requests_restart(tmp_path):
    stop_requested = threading.Event()
    (tmp_path / "desired.json").write_text(json.dumps({"running": True}))
    (tmp_path / "status.json").write_text(
        json.dumps({"lifecycle": "failed", "pid": 1234})
    )

    class FailedChild:
        pid = 1234
        terminated = False
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            if self.returncode is None:
                raise pokemon_module.subprocess.TimeoutExpired("child", timeout)
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = 1

        def kill(self):
            self.returncode = -9

    child = FailedChild()

    assert wait_for_supervised_child(
        child,
        stop_requested,
        tmp_path,
    ) == (1, True)
    assert child.terminated is True
    assert not stop_requested.is_set()


def _paused_child_status(tmp_path, *, kind, expires_at):
    (tmp_path / "desired.json").write_text(json.dumps({"running": True}))
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "lifecycle": "ready",
                "pid": 1234,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "paused": True,
                "pause_kind": kind,
                "pause_owner": "someone",
                "pause_expires_at": expires_at,
            }
        )
    )


class _SupervisedChildSpy:
    pid = 1234

    def __init__(self, stop_after=None, stop_requested=None):
        self.returncode = None
        self.terminated = False
        self.waits = 0
        self.stop_after = stop_after
        self.stop_requested = stop_requested

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.waits += 1
        if (
            self.stop_after is not None
            and self.waits >= self.stop_after
            and self.stop_requested is not None
        ):
            self.stop_requested.set()
        if self.returncode is None:
            raise pokemon_module.subprocess.TimeoutExpired("child", timeout)
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1

    def kill(self):
        self.returncode = -9


def test_supervisor_restarts_overdue_automation_pause_despite_heartbeat(
    tmp_path,
):
    stop_requested = threading.Event()
    overdue = datetime.now(timezone.utc) - timedelta(seconds=120)
    _paused_child_status(
        tmp_path,
        kind="automation",
        expires_at=overdue.isoformat(),
    )
    child = _SupervisedChildSpy()

    assert wait_for_supervised_child(
        child,
        stop_requested,
        tmp_path,
    ) == (1, True)

    assert child.terminated is True
    request = json.loads(
        (tmp_path / pokemon_module.RESTART_REQUEST_NAME).read_text()
    )
    assert request["reason"] == "expired automation pause"


def test_supervisor_never_restarts_operator_hold_or_live_lease(tmp_path):
    for kind, expires_at in (
        ("operator_hold", None),
        (
            "automation",
            (
                datetime.now(timezone.utc) + timedelta(seconds=120)
            ).isoformat(),
        ),
    ):
        stop_requested = threading.Event()
        _paused_child_status(tmp_path, kind=kind, expires_at=expires_at)
        child = _SupervisedChildSpy(
            stop_after=3,
            stop_requested=stop_requested,
        )

        exit_code, restart_required = wait_for_supervised_child(
            child,
            stop_requested,
            tmp_path,
        )

        assert restart_required is False
        assert not (tmp_path / pokemon_module.RESTART_REQUEST_NAME).exists()


def test_failure_lifecycle_returns_nonzero_to_supervisor(monkeypatch, tmp_path):
    class FailedRunner:
        def __init__(self, args):
            del args
            self.status = {"lifecycle": "failed"}
            self.stream_generation = None
            self.stop_event = threading.Event()
            self.brain_ready = threading.Event()
            self.brain = None

        def run(self):
            return None

    monkeypatch.setattr(pokemon_module, "PokemonRunner", FailedRunner)
    monkeypatch.setattr(pokemon_module.signal, "signal", lambda *args: None)

    exit_code = runner_main(
        [
            "run",
            "--rom",
            str(tmp_path / "Pokemon Red.gb"),
            "--runtime-dir",
            str(tmp_path),
            "--instance-id",
            "failed-runner",
        ]
    )

    assert exit_code == 1


def test_active_recording_suspends_before_exceeding_storage_budget(tmp_path):
    clips_dir = tmp_path / "clips"
    states_dir = tmp_path / "states"
    screens_dir = tmp_path / "screens"
    clips_dir.mkdir()
    states_dir.mkdir()
    screens_dir.mkdir()
    partial = clips_dir / ".clip-0001-20260711-120000.mp4.partial.mp4"
    partial.write_bytes(b"active recording")

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.states_dir = states_dir
    runner.screens_dir = screens_dir
    runner.recorder = SimpleNamespace(clips_dir=clips_dir, partial_path=partial)
    runner.max_clips = 2
    runner.max_states = 2
    runner.max_storage_bytes = 1
    runner.min_free_bytes = 0
    runner.status = {"rom_sha256": "rom-hash"}

    runner._enforce_retention()

    assert partial.exists()
    assert runner.status["recording_suspended"] is True


def test_clip_indices_continue_beyond_four_digits(tmp_path):
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    clip = clips_dir / "clip-10000-20260711-120000.mp4"
    clip.write_bytes(b"video")
    clip.with_suffix(".json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": clip.name,
                "sha256": "hash",
            }
        )
    )
    recorder = ClipRecorder.__new__(ClipRecorder)
    recorder.clips_dir = clips_dir

    assert recorder._next_index() == 10001


def test_session_tried_seeded_from_persisted_memory_across_restart(tmp_path):
    path = tmp_path / "navigation-memory.json"
    memory = NavigationMemory(path)
    now = datetime.now(timezone.utc)
    memory.begin((0xC9, 15, 11), ["down"], phase="overworld")
    memory.finish((0xC9, 15, 12), now=now)
    memory.begin((0xC9, 15, 12), ["right"], phase="overworld")
    memory.finish((0xC9, 17, 13), now=now)
    before = memory.distinct_edge_count()
    assert before >= 2

    # A fresh process must not see well-known tiles as "new" edges — the
    # stall counter would never rise and auto-coverage would never engage.
    reloaded = NavigationMemory(path)
    assert reloaded.distinct_edge_count() == before
    assert (0xC9, 15, 11, "down") in reloaded.session_tried


def test_untried_frontier_waypoint_bias_targets_exit_corner(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    # Two known tiles: one near the player, one near the trusted stairs.
    memory.begin((0xC9, 10, 10), ["right"], phase="overworld")
    memory.finish((0xC9, 11, 10), now=now)
    memory.begin((0xC9, 18, 17), ["left"], phase="overworld")
    memory.finish((0xC9, 17, 17), now=now)

    near_player = memory.untried_frontier((0xC9, 11, 10))
    assert near_player[0]["origin"] in ([10, 10], [11, 10])

    toward_stairs = memory.untried_frontier((0xC9, 11, 10), toward=(19, 18))
    assert toward_stairs[0]["origin"] in ([18, 17], [17, 17])


def test_auto_coverage_falls_back_when_waypoint_entries_unreachable(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    # One walked tile near the player; an isolated known tile near the trusted
    # waypoint that BFS cannot reach (no connecting edges).
    memory.begin((0xC9, 10, 10), ["right"], phase="overworld")
    memory.finish((0xC9, 11, 10), now=now)
    memory.begin((0xC9, 18, 17), ["down"], phase="overworld")
    memory.finish((0xC9, 18, 17), now=now)  # no_progress: isolated tile

    runner = _coverage_runner(tmp_path, memory)
    issued = runner._advance_committed_route(
        {"map_id": 0xC9, "coordinates": {"x": 11, "y": 10}}
    )

    # Near-waypoint entries are unreachable walls; the fallback list still
    # commits a probe from the player's own reachable neighborhood.
    assert issued is True
    assert runner.status["auto_coverage_rides"] == 1


def test_walk_edges_survive_transition_fifo_churn(tmp_path):
    path = tmp_path / "navigation-memory.json"
    memory = NavigationMemory(path)
    now = datetime.now(timezone.utc)
    # Walk a two-step path, then churn the transition FIFO far past capacity.
    memory.begin((0xC9, 5, 5), ["right"], phase="overworld")
    memory.finish((0xC9, 6, 5), now=now)
    memory.begin((0xC9, 6, 5), ["right"], phase="overworld")
    memory.finish((0xC9, 7, 5), now=now)
    for i in range(50):
        memory.begin((0xC9, 20, 20 + (i % 3)), ["up"], phase="overworld")
        memory.finish((0xC9, 20, 19 + (i % 3)), now=now)

    # The FIFO no longer holds the original steps, but routing still works.
    route = memory.route_to((0xC9, 5, 5), [7, 5])
    assert route is not None and len(route) == 2

    # And it survives a process restart.
    reloaded = NavigationMemory(path)
    route = reloaded.route_to((0xC9, 5, 5), [7, 5])
    assert route is not None and len(route) == 2
    assert (0xC9, 5, 5, "right") in reloaded.session_tried


def test_navigation_edge_refresh_does_not_evict_unrelated_facts(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(pokemon_module, "NAVIGATION_SESSION_TRIED_LIMIT", 2)
    monkeypatch.setattr(pokemon_module, "NAVIGATION_WALK_EDGE_LIMIT", 2)
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)

    for origin, destination in (
        ((0xC9, 1, 1), (0xC9, 2, 1)),
        ((0xC9, 3, 1), (0xC9, 4, 1)),
        ((0xC9, 1, 1), (0xC9, 2, 1)),
        ((0xC9, 5, 1), (0xC9, 6, 1)),
    ):
        memory.begin(origin, ["right"], phase="overworld")
        memory.finish(destination, now=now)

    refreshed = (0xC9, 1, 1, "right")
    stale = (0xC9, 3, 1, "right")
    newest = (0xC9, 5, 1, "right")
    assert list(memory.walk_edges) == [refreshed, newest]
    assert list(memory.session_tried) == [refreshed, newest]
    assert stale not in memory.walk_edges
    assert stale not in memory.session_tried


def test_macro_edge_refresh_preserves_recent_fact_at_capacity(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(pokemon_module, "NAVIGATION_MACRO_EDGE_LIMIT", 2)
    memory = NavigationMemory(tmp_path / "navigation-memory.json")

    def record(x, destination_x):
        memory._record_macro_edge(
            (0xC9, x, 1),
            "right",
            (0xC9, destination_x, 1),
            [[destination_x, 1]],
            "2026-07-24T01:00:00Z",
        )

    record(1, 5)
    record(6, 10)
    record(1, 5)
    record(11, 15)

    assert [item["origin"] for item in memory.macro_edges] == [
        [0xC9, 1, 1],
        [0xC9, 11, 1],
    ]
    assert memory.macro_edges[0]["confirmed"] == 2
