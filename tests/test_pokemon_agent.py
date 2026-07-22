import asyncio
import json
import os
import queue
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
    ActionPlayer,
    ClipRecorder,
    CopilotBrain,
    NavigationMemory,
    PokemonAgent,
    PokemonRunner,
    StartupConfigurationError,
    ViewerServer,
    acquire_runtime_lock,
    build_parser,
    celadon_route_guidance,
    collision_allows_direction,
    discover_pokemon_red_rom,
    ensure_copilot_runtime,
    file_sha256,
    is_cloud_placeholder,
    is_pokemon_red_rom,
    list_clips,
    normalize_brain_decision,
    normalize_web_research,
    overworld_action_buttons,
    parse_agent_action,
    precision_route_buttons,
    public_runtime_status,
    read_youtube_chat_advisory,
    rock_tunnel_route_guidance,
    rocket_hideout_route_guidance,
    runner_main,
    runtime_command,
    runtime_status,
    search_pokemon_web,
    seed_legacy_ram_provenance,
    supervisor_main,
    terminate_isolated_process_group,
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
    assert "manual" in agent.metadata["parameters"]["properties"]["action"]["enum"]
    assert "autonomy" in agent.metadata["parameters"]["properties"]["action"]["enum"]


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
    assert "down once, west to (20,7), then south to (20,9)" in guidance
    assert "never descend at x>=22" in guidance
    assert "exit-only" in guidance
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


def _activated_memory(tmp_path):
    memory = NavigationMemory(tmp_path / "navigation-memory.json")
    now = datetime.now(timezone.utc)
    a = (0xC9, 15, 11)
    b = (0xC9, 15, 13)
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


def test_stop_control_sets_supervisor_owned_desired_state(tmp_path):
    (tmp_path / "desired.json").write_text(json.dumps({"running": True}))

    pokemon_module.append_control(tmp_path, {"action": "stop"})

    assert json.loads((tmp_path / "desired.json").read_text())["running"] is False
    assert json.loads((tmp_path / "control.jsonl").read_text())["action"] == "stop"


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
