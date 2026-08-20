from __future__ import annotations

import json
import os
import queue
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from types import SimpleNamespace

import pytest
from openrappter.agents.pokemon_agent import (
    BAG_ITEM_CAPACITY,
    LIFT_KEY_ITEM_ID,
    LIVESTREAM_HEARTBEAT_SECONDS,
    LIVESTREAM_LEASE_TTL_SECONDS,
    LIVESTREAM_REPORT_STALE_SECONDS,
    MAX_TELEMETRY_BYTES,
    SILPH_SCOPE_ITEM_ID,
    SPECTATOR_CSS,
    SPECTATOR_HTML,
    SPECTATOR_JS,
    TELEMETRY_VERSION,
    VIEWER_HTML,
    VIEWER_JS,
    ActionPlayer,
    PokemonGoldMemoryReader,
    PokemonMemoryReader,
    PokemonRunner,
    ViewerServer,
    file_sha256,
    project_dashboard_snapshot,
    sanitize_checkpoint_summary,
)


def set_dex_bit(memory: bytearray, start: int, dex_number: int) -> None:
    index = dex_number - 1
    memory[start + index // 8] |= 1 << (index % 8)


def set_bag(memory: bytearray, items: list[tuple[int, int]]) -> None:
    memory[0xD31D] = len(items)
    for index, (item_id, quantity) in enumerate(items):
        memory[0xD31E + index * 2] = item_id
        memory[0xD31F + index * 2] = quantity
    memory[0xD31E + len(items) * 2] = 0xFF


def set_event(memory: bytearray, event: int) -> None:
    memory[0xD747 + event // 8] |= 1 << (event % 8)


def test_key_item_state_uses_validated_bag_pairs_and_terminator():
    memory = bytearray(65536)
    set_bag(
        memory,
        [
            (0x14, 74),
            (LIFT_KEY_ITEM_ID, 1),
            (SILPH_SCOPE_ITEM_ID, 1),
        ],
    )

    assert PokemonMemoryReader(memory).key_items() == {
        "silph_scope": True,
        "poke_flute": False,
        "lift_key": True,
        "card_key": False,
        "master_ball": False,
        "secret_key": False,
        "hm_fly": False,
        "hm_surf": False,
        "hm_strength": False,
    }

    memory[0xD31E + 6] = LIFT_KEY_ITEM_ID
    assert PokemonMemoryReader(memory).key_items() == {
        "silph_scope": None,
        "poke_flute": None,
        "lift_key": None,
        "card_key": None,
        "master_ball": None,
        "secret_key": None,
        "hm_fly": None,
        "hm_surf": None,
        "hm_strength": None,
    }


def test_key_item_state_handles_capacity_and_invalid_bags():
    memory = bytearray(65536)
    items = [(1 + index, 1) for index in range(BAG_ITEM_CAPACITY)]
    items[-1] = (LIFT_KEY_ITEM_ID, 1)
    set_bag(memory, items)
    memory[0xD347] = SILPH_SCOPE_ITEM_ID

    assert PokemonMemoryReader(memory).key_items() == {
        "silph_scope": False,
        "poke_flute": False,
        "lift_key": True,
        "card_key": False,
        "master_ball": True,
        "secret_key": False,
        "hm_fly": False,
        "hm_surf": False,
        "hm_strength": False,
    }

    memory[0xD31D] = BAG_ITEM_CAPACITY + 1
    assert PokemonMemoryReader(memory).key_items() == {
        "silph_scope": None,
        "poke_flute": None,
        "lift_key": None,
        "card_key": None,
        "master_ball": None,
        "secret_key": None,
        "hm_fly": None,
        "hm_surf": None,
        "hm_strength": None,
    }


def test_seafoam_boulder_progress_reads_event_pairs():
    memory = bytearray(65536)
    reader = PokemonMemoryReader(memory)

    assert reader.seafoam_boulders() == {
        "one_to_b1f": False,
        "b1f_to_b2f": False,
        "b2f_to_b3f": False,
        "b3f_to_b4f": False,
    }
    assert reader.seafoam_boulder_events()["b2f_to_b3f_1"] is False

    for event in (0x50E, 0x50F, 0x9C0, 0x9C1, 0x9C8, 0x9C9, 0x9D0, 0x9D1):
        set_event(memory, event)

    assert reader.seafoam_boulders() == {
        "one_to_b1f": True,
        "b1f_to_b2f": True,
        "b2f_to_b3f": True,
        "b3f_to_b4f": True,
    }
    assert all(
        value is True for value in reader.seafoam_boulder_events().values()
    )


def test_mansion_switch_state_reads_shared_event():
    memory = bytearray(65536)
    reader = PokemonMemoryReader(memory)

    assert reader.snapshot()["mansion_switch_on"] is False

    set_event(memory, 0x278)

    assert reader.snapshot()["mansion_switch_on"] is True


def test_victory_road_switch_state_reads_event():
    memory = bytearray(65536)
    reader = PokemonMemoryReader(memory)

    assert reader.snapshot()["victory_road_1_switch_on"] is False
    assert reader.snapshot()["victory_road_1_boulder"] is None
    assert reader.snapshot()["strength_active"] is False

    memory[0xD35E] = 0x6C
    memory[0xC254] = 15 + 4
    memory[0xC255] = 5 + 4

    assert reader.snapshot()["victory_road_1_boulder"] == {"x": 5, "y": 15}

    memory[0xD728] |= 0x01

    assert reader.snapshot()["strength_active"] is True

    set_event(memory, 0x917)

    assert reader.snapshot()["victory_road_1_switch_on"] is True


def test_victory_road_2_switches_and_boulders_read_memory():
    memory = bytearray(65536)
    memory[0xD35E] = 0xC2
    for index, (x, y) in zip(
        (11, 12, 13),
        ((4, 14), (5, 5), (23, 16)),
        strict=True,
    ):
        memory[0xC200 + 16 * index + 4] = y + 4
        memory[0xC200 + 16 * index + 5] = x + 4
    reader = PokemonMemoryReader(memory)

    assert reader.snapshot()["victory_road_2_boulders"] == [
        {"x": 4, "y": 14},
        {"x": 5, "y": 5},
        {"x": 23, "y": 16},
    ]
    assert reader.snapshot()["victory_road_2_switches"] == {
        "one": False,
        "two": False,
    }

    set_event(memory, 0x538)

    assert reader.snapshot()["victory_road_2_switches"]["one"] is True


def test_victory_road_3_events_read_memory():
    memory = bytearray(65536)
    memory[0xD35E] = 0xC6
    for index, (x, y) in zip(
        (7, 8, 9, 10),
        ((22, 3), (13, 12), (24, 10), (22, 15)),
        strict=True,
    ):
        memory[0xC200 + 16 * index + 4] = y + 4
        memory[0xC200 + 16 * index + 5] = x + 4
    reader = PokemonMemoryReader(memory)

    assert reader.snapshot()["victory_road_3_events"] == {
        "switch": False,
        "hole_boulder": False,
    }
    assert reader.snapshot()["victory_road_3_boulders"] == [
        {"x": 22, "y": 3},
        {"x": 13, "y": 12},
        {"x": 24, "y": 10},
        {"x": 22, "y": 15},
    ]

    set_event(memory, 0x660)
    set_event(memory, 0x666)

    assert reader.snapshot()["victory_road_3_events"] == {
        "switch": True,
        "hole_boulder": True,
    }


def test_pokedex_counts_ignore_padding_and_include_dex_151():
    memory = bytearray(65536)
    for dex_number in (1, 151):
        set_dex_bit(memory, 0xD2F7, dex_number)
        set_dex_bit(memory, 0xD30A, dex_number)
    set_dex_bit(memory, 0xD30A, 8)
    memory[0xD2F7 + 18] |= 0x80
    memory[0xD30A + 18] |= 0x80

    snapshot = PokemonMemoryReader(memory).snapshot()

    assert snapshot["pokedex"] == {"caught": 2, "seen": 3, "total": 151}


def test_mewtwo_capture_requires_owned_dex_150_bit():
    memory = bytearray(65536)
    reader = PokemonMemoryReader(memory)

    assert reader.snapshot()["mewtwo_caught"] is False
    assert reader.snapshot()["mewtwo_encounter_resolved"] is False

    set_event(memory, 0x8C1)

    assert reader.snapshot()["mewtwo_caught"] is False
    assert reader.snapshot()["mewtwo_encounter_resolved"] is True

    set_dex_bit(memory, 0xD2F7, 150)

    assert reader.snapshot()["mewtwo_caught"] is True


def test_surfing_state_reads_walk_bike_surf_memory():
    memory = bytearray(65536)
    reader = PokemonMemoryReader(memory)

    assert reader.snapshot()["surfing"] is False

    memory[0xD700] = 2

    assert reader.snapshot()["surfing"] is True


def test_mewtwo_battle_and_master_ball_cursor_read_memory():
    memory = bytearray(65536)
    memory[0xD057] = 1
    memory[0xD059] = 0x83
    memory[0xCC36] = 13
    memory[0xCC26] = 2
    memory[0xD31D] = 2
    memory[0xD31E] = 0x30
    memory[0xD31F] = 1
    memory[0xD320] = 0x01
    memory[0xD321] = 1
    memory[0xD322] = 0xFF

    snapshot = PokemonMemoryReader(memory).snapshot()

    assert snapshot["in_battle"] is True
    assert snapshot["enemy_species_id"] == 0x83
    assert snapshot["menu_cursor_index"] == 15
    assert snapshot["master_ball_bag_index"] == 1


def test_gold_reader_exposes_verified_generation_two_progress():
    memory = bytearray(65536)
    memory[0xDA00] = 0x18
    memory[0xDA01] = 0x04
    memory[0xDA02] = 5
    memory[0xDA03] = 6
    memory[0xDA22] = 1
    memory[0xDA23] = 158
    memory[0xDA24] = 0xFF
    memory[0xDA2A] = 158
    memory[0xDA2A + 0x1F] = 5
    memory[0xDA2A + 0x22] = 0
    memory[0xDA2A + 0x23] = 20
    memory[0xDA2A + 0x24] = 0
    memory[0xDA2A + 0x25] = 20
    memory[0xD57C] = 0xFF
    memory[0xD57D] = 0xFF
    memory[0xD5E1] = 0
    memory[0xD5E2] = 0xFF
    memory[0xD116] = 1
    memory[0xD0EF] = 16
    memory[0xD6A8] = 6
    memory[0xDBE4] = 0b00000001
    memory[0xDBE4 + 31] = 0b00000100
    memory[0xDC04] = 0b00000011
    memory[0xDC04 + 31] = 0b00000100
    memory[0xD1EA] = 0
    memory[0xD1EB] = 0x02
    memory[0xD1EC] = 0x58
    memory[0xD1ED] = 34
    memory[0xD1EE] = 56
    memory[0xD1EF] = 12
    memory[0xD7B7 + 0x0044 // 8] |= 1 << (0x0044 % 8)
    memory[0xD7B7 + 0x0762 // 8] |= 1 << (0x0762 % 8)
    memory[0xD7B7 + 0x001A // 8] |= 1 << (0x001A % 8)
    memory[0xD7B7 + 0x001E // 8] |= 1 << (0x001E % 8)
    memory[0xD7B7 + 0x0014 // 8] |= 1 << (0x0014 % 8)
    memory[0xD7B7 + 0x0010 // 8] |= 1 << (0x0010 % 8)
    memory[0xD7B7 + 0x0647 // 8] |= 1 << (0x0647 % 8)
    memory[0xD7B7 + 0x0411 // 8] |= 1 << (0x0411 % 8)
    memory[0xD7B7 + 0x03FB // 8] |= 1 << (0x03FB % 8)
    memory[0xD7B7 + 0x03FC // 8] |= 1 << (0x03FC % 8)
    memory[0xD7B7 + 0x002B // 8] |= 1 << (0x002B % 8)
    memory[0xD7B7 + 0x0029 // 8] |= 1 << (0x0029 % 8)
    memory[0xD7B7 + 0x0535 // 8] |= 1 << (0x0535 % 8)
    memory[0xD7B7 + 0x04E4 // 8] |= 1 << (0x04E4 % 8)
    memory[0xD7B7 + 0x044C // 8] |= 1 << (0x044C % 8)
    memory[0xD7B7 + 0x06FA // 8] |= 1 << (0x06FA % 8)
    memory[0xD7B7 + 0x053C // 8] |= 1 << (0x053C % 8)

    snapshot = PokemonGoldMemoryReader(memory).snapshot()

    assert snapshot["map_id"] == 0x1804
    assert snapshot["location"] == "New Bark Town"
    assert snapshot["coordinates"] == {"x": 6, "y": 5}
    assert snapshot["underground_switch_position"] == 6
    assert len(snapshot["badges"]) == 16
    assert snapshot["party"] == [{
        "nickname": "",
        "species_id": 158,
        "level": 5,
        "hp": 20,
        "max_hp": 20,
    }]
    assert snapshot["in_battle"] is True
    assert snapshot["enemy_species_id"] == 16
    assert snapshot["pokedex"] == {"caught": 2, "seen": 3, "total": 251}
    assert snapshot["play_time"] == {
        "hours": 600,
        "minutes": 34,
        "seconds": 56,
        "frames": 12,
        "maxed": False,
    }
    assert snapshot["elite_four_completed"] is True
    assert snapshot["red_defeated"] is True
    assert snapshot["ultimate_run_completed"] is True
    assert snapshot["story_events"] == {
        "got_hm_flash": True,
        "got_hm_cut": True,
        "got_hm_fly": False,
        "got_starter": True,
        "got_mystery_egg": True,
        "gave_mystery_egg_to_elm": False,
        "beat_sage_chow": True,
        "beat_bird_keeper_rod": True,
        "beat_bird_keeper_abe": True,
        "cleared_slowpoke_well": True,
        "herded_farfetchd": True,
        "beat_hiker_daniel": True,
        "beat_pokemaniac_larry": True,
        "beat_firebreather_ray": True,
        "kurt_left_for_well": True,
        "beat_bug_catcher_benny": True,
        "sprout_1f_parlyz_heal_collected": True,
        "farfetchd_position": None,
        "beat_beauty_victoria": False,
        "beat_beauty_samantha": False,
        "beat_lass_carrie": False,
        "beat_lass_bridget": False,
        "beat_whitney": False,
        "made_whitney_cry": False,
        "fought_sudowoodo": False,
        "got_hm_surf": False,
        "beat_camper_ivan": False,
        "released_the_beasts": False,
        "beat_morty": False,
        "beat_kimono_naoko": False,
        "beat_kimono_sayo": False,
        "beat_kimono_zuki": False,
        "beat_kimono_kuni": False,
        "beat_kimono_miki": False,
        "got_tm_rock_smash": False,
        "got_hm_strength": False,
        "jasmine_explained_sickness": False,
        "jasmine_returned_to_gym": False,
        "cleared_radio_tower": False,
        "cleared_rocket_hideout": False,
        "used_radio_tower_card_key": False,
        "used_basement_key": False,
        "received_card_key": False,
        "refused_to_help_lance": False,
        "decided_to_help_lance": False,
        "got_secret_potion": False,
        "beat_jasmine": False,
        "beat_chuck": False,
        "beat_pryce": False,
        "beat_clair": False,
        "got_hm_whirlpool": False,
        "got_hm_waterfall": False,
        "beat_rocket_gruntm18": False,
        "met_rival_rocket_base": False,
        "beat_rival_underground": False,
        "beat_rocket_commander": False,
        "learned_hail_giovanni": False,
        "opened_rocket_transmitter_door": False,
        "learned_slowpoketail": False,
        "learned_raticate_tail": False,
        "opened_giovanni_office": False,
        "rocket_electrode_1": False,
        "rocket_electrode_2": False,
        "rocket_electrode_3": False,
    }


def test_gold_reader_does_not_decode_overworld_tiles_as_text():
    memory = bytearray(65536)
    memory[0xDA00] = 0x18
    memory[0xDA01] = 0x03
    memory[0xDA02] = 6
    memory[0xDA03] = 33
    memory[0xDA22] = 0
    memory[0xD5E1] = 0
    memory[0xD5E2] = 0xFF
    memory[0xD15F] = 0
    memory[0xD116] = 0
    memory[0xC4A0 : 0xC4A0 + 360] = bytes([0xF6]) * 360

    assert PokemonGoldMemoryReader(memory).snapshot()["screen_text"] == ""


def test_project_dashboard_projects_gold_badges_and_party():
    snapshot = project_dashboard_snapshot({
        "game_id": "gold",
        "game_state": {
            "game_id": "gold",
            "location": "Union Cave 1F",
            "badges": ["Zephyr", "Hive"],
            "johto_badge_bits": 3,
            "kanto_badge_bits": 0,
            "party_count": 1,
            "party": [{
                "nickname": "CROCONAW",
                "species_id": 159,
                "level": 18,
                "hp": 50,
                "max_hp": 54,
            }],
            "pokedex": {"caught": None, "seen": None, "total": 251},
            "play_time": {
                "hours": 600,
                "minutes": 34,
                "seconds": 56,
                "frames": 12,
                "maxed": False,
            },
            "red_defeated": False,
        },
    })

    assert snapshot["badges"] == {
        "earned": ["Zephyr", "Hive"],
        "count": 2,
        "total": 16,
    }
    assert snapshot["pokedex"]["total"] == 251
    assert snapshot["play_time"]["hours"] == 600
    assert snapshot["party"][0]["nickname"] == "CROCONAW"


def test_hall_of_fame_completion_event_persists_postgame():
    memory = bytearray(65536)
    reader = PokemonMemoryReader(memory)

    assert reader.snapshot()["hall_of_fame"] is False
    assert reader.snapshot()["hall_of_fame_completed"] is False

    set_event(memory, 0x000)

    assert reader.snapshot()["hall_of_fame"] is False
    assert reader.snapshot()["hall_of_fame_completed"] is True


@pytest.mark.parametrize(
    ("address", "value"),
    [
        (0xDA42, 1),
        (0xDA42, 2),
        (0xDA43, 60),
        (0xDA44, 60),
        (0xDA45, 60),
    ],
)
def test_play_clock_rejects_malformed_wram(address, value):
    memory = bytearray(65536)
    memory[0xDA41] = 23
    memory[0xDA42] = 0
    memory[0xDA43] = 58
    memory[0xDA44] = 59
    memory[0xDA45] = 30
    reader = PokemonMemoryReader(memory)
    assert reader.play_time() == {
        "hours": 23,
        "minutes": 58,
        "seconds": 59,
        "frames": 30,
        "maxed": False,
    }

    memory[address] = value

    assert PokemonMemoryReader(memory).play_time() is None


def test_unavailable_wram_reports_unknown_counts_and_clock():
    snapshot = PokemonMemoryReader({}).snapshot()

    assert snapshot["pokedex"] == {"caught": None, "seen": None, "total": 151}
    assert snapshot["play_time"] is None
    assert snapshot["location"] is None
    assert snapshot["badge_bits"] is None
    assert snapshot["party_count"] is None
    projected = project_dashboard_snapshot({"game_state": snapshot})
    assert projected["badges"]["count"] is None
    assert projected["party"] is None


def test_terminal_play_clock_uses_canonical_ff_max_flag():
    memory = bytearray(65536)
    memory[0xDA41] = 255
    memory[0xDA42] = 0xFF
    memory[0xDA43] = 59
    memory[0xDA44] = 59
    memory[0xDA45] = 59

    assert PokemonMemoryReader(memory).play_time() == {
        "hours": 255,
        "minutes": 59,
        "seconds": 59,
        "frames": 59,
        "maxed": True,
    }


def test_owned_pokedex_count_may_exceed_seen_count():
    snapshot = project_dashboard_snapshot(
        {
            "game_state": {
                "pokedex": {"caught": 30, "seen": 12},
            }
        }
    )

    assert snapshot["pokedex"] == {"caught": 30, "seen": 12, "total": 151}


def test_invalid_party_count_is_unavailable_not_six_fabricated_members():
    memory = bytearray(65536)
    memory[0xD163] = 7
    game_state = PokemonMemoryReader(memory).snapshot()

    assert game_state["party_count"] is None
    assert game_state["party"] == []
    assert project_dashboard_snapshot({"game_state": game_state})["party"] is None


def test_dashboard_projection_is_exact_bounded_and_secret_free():
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    checkpoint = {
        "timestamp": "2026-07-16T23:59:00+00:00",
        "reason": "Copilot checkpoint: private free-form reasoning",
        "location": "Pewter Gym",
        "path": "/private/checkpoint.state",
        "sha256": "secret-checkpoint-hash",
    }
    status = {
        "started_at": "2026-07-16T23:00:00+00:00",
        "objective": "Reach the next objective\n" + "x" * 300,
        "phase": "exploration",
        "control_mode": "ai",
        "paused": False,
        "completed": False,
        "last_checkpoint": checkpoint,
        "rom_path": "/private/Pokemon Red.gb",
        "rom_sha256": "secret-rom-hash",
        "runtime_dir": "/private/runtime",
        "clips": [{"name": "secret-clip"}],
        "last_error": "secret-error",
        "pid": 98765,
        "instance_id": "secret-instance",
        "reason": "secret model reasoning",
        "observation": "secret model observation",
        "last_action": ["secret-action"],
        "screen_text": "secret screen text",
        "game_state": {
            "location": "Pewter Gym",
            "badges": ["Boulder", "Boulder", "not-a-badge"],
            "pokedex": {"caught": 12, "seen": 30, "species": ["secret"]},
            "party": [
                {
                    "nickname": "<img src=x onerror=alert(1)>",
                    "species_id": 25,
                    "level": 12,
                    "hp": 20,
                    "max_hp": 35,
                    "moves": ["secret"],
                }
            ],
            "play_time": {
                "hours": 10,
                "minutes": 2,
                "seconds": 3,
                "frames": 4,
                "maxed": False,
            },
            "screen_text": "private observation",
        },
        "livestream": {
            "viewer_count": 2,
            "max_viewers": 5,
            "generation": "secret-generation",
            "lease": "secret-lease",
            "peer_id": "secret-peer",
            "watch_capability": "secret-capability",
            "join_url": "https://secret-join",
        },
    }

    snapshot = project_dashboard_snapshot(status, now=now)
    serialized = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    envelope = {
        "v": 1,
        "type": "telemetry",
        "telemetry_version": TELEMETRY_VERSION,
        "sequence": 1,
        "snapshot": snapshot,
    }

    assert set(snapshot) == {
        "location",
        "objective",
        "phase",
        "badges",
        "pokedex",
        "party",
        "completed",
        "player",
        "play_time",
        "session_elapsed_seconds",
        "checkpoint",
        "viewers",
    }
    assert snapshot["badges"] == {
        "earned": ["Boulder"],
        "count": 1,
        "total": 8,
    }
    assert len(snapshot["objective"]) == 160
    assert snapshot["checkpoint"] == {
        "timestamp": "2026-07-16T23:59:00Z",
        "kind": "progress",
        "location": "Pewter Gym",
        "age_seconds": 60,
    }
    assert snapshot["session_elapsed_seconds"] == 3600
    assert len(
        json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode()
    ) <= MAX_TELEMETRY_BYTES
    for canary in (
        "/private/",
        "secret-rom-hash",
        "secret-checkpoint-hash",
        "private free-form reasoning",
        "private observation",
        "secret-clip",
        "secret-error",
        "secret-instance",
        "secret model observation",
        "secret-action",
        "secret-generation",
        "secret-lease",
        "secret-peer",
        "secret-capability",
        "secret-join",
    ):
        assert canary not in serialized


class ResumeEmulator:
    def __init__(self):
        self.memory = bytearray(65536)
        self.loaded: list[bytes] = []

    def save_state(self, handle):
        handle.write(b"baseline")

    def load_state(self, handle):
        self.loaded.append(handle.read())

    def button_release(self, button):
        del button

    def tick(self):
        return True


def test_resume_restores_sanitized_checkpoint_truth_and_no_resume_clears_it(tmp_path):
    state = tmp_path / "state-20260716-220000-000001.state"
    state.write_bytes(b"verified state")
    state.with_suffix(".json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-07-16T22:00:00+00:00",
                "reason": "Badge milestone: Boulder",
                "rom_sha256": "rom-hash",
                "sha256": file_sha256(state),
                "game_state": {"location": "Pewter Gym"},
            }
        )
    )
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.args = SimpleNamespace(resume=True)
    runner.runtime_dir = tmp_path
    runner.states_dir = tmp_path
    runner.pyboy = ResumeEmulator()
    runner.player = ActionPlayer()
    runner.status = {"rom_sha256": "rom-hash", "last_checkpoint": None}

    assert runner._load_latest_state() == state
    public = sanitize_checkpoint_summary(
        runner.status["last_checkpoint"],
        now=datetime(2026, 7, 16, 22, 1, tzinfo=timezone.utc),
    )
    assert public == {
        "timestamp": "2026-07-16T22:00:00Z",
        "kind": "milestone",
        "location": "Pewter Gym",
        "age_seconds": 60,
    }
    assert "reason" not in public
    assert "sha256" not in public
    assert "path" not in public

    runner.args.resume = False
    assert runner._load_latest_state() is None
    assert runner.status["last_checkpoint"] is None


def test_resume_of_completed_checkpoint_restores_paused_completion(tmp_path):
    state = tmp_path / "state-20260716-220000-000001.state"
    state.write_bytes(b"completed state")
    state.with_suffix(".json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "created_at": "2026-07-16T22:00:00+00:00",
                "reason": "Pokemon Red completed: Hall of Fame",
                "rom_sha256": "rom-hash",
                "sha256": file_sha256(state),
                "game_state": {
                    "location": "Hall of Fame",
                    "hall_of_fame": True,
                },
            }
        )
    )
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.args = SimpleNamespace(resume=True)
    runner.runtime_dir = tmp_path
    runner.states_dir = tmp_path
    runner.pyboy = ResumeEmulator()
    runner.player = ActionPlayer()
    runner.status = {
        "rom_sha256": "rom-hash",
        "last_checkpoint": None,
        "completed": False,
    }
    restored_modes: list[str] = []
    runner._set_control_mode = restored_modes.append

    assert runner._load_latest_state() == state
    assert runner.status["completed"] is True
    assert restored_modes == ["paused"]


def test_resume_of_mewtwo_checkpoint_restores_paused_postgame(tmp_path):
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.status = {"completed": False, "mewtwo_caught": False}
    restored_modes: list[str] = []
    runner._set_control_mode = restored_modes.append

    assert runner._restore_completed_state({"mewtwo_caught": True}) is True
    assert runner.status["completed"] is True
    assert runner.status["mewtwo_caught"] is True
    assert restored_modes == ["paused"]


def test_resume_of_postgame_checkpoint_restores_completion_without_pause():
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.status = {"completed": False, "mewtwo_caught": False}
    restored_modes: list[str] = []
    runner._set_control_mode = restored_modes.append

    assert runner._restore_completed_state({
        "hall_of_fame": False,
        "hall_of_fame_completed": True,
    }) is True
    assert runner.status["completed"] is True
    assert restored_modes == []


def test_gold_restore_rejects_pre_mt_silver_red_visibility_flag():
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.game_id = "gold"
    runner.control_mode = "ai"
    runner.status = {"completed": False}
    restored_modes: list[str] = []
    runner._set_control_mode = restored_modes.append

    assert runner._restore_completed_state({
        "badges": [],
        "elite_four_completed": False,
        "red_defeated": True,
    }) is False
    assert runner.status["completed"] is False
    assert restored_modes == []

    assert runner._restore_completed_state({
        "badges": [f"badge-{index}" for index in range(16)],
        "elite_four_completed": True,
        "red_defeated": True,
    }) is True
    assert runner.status["completed"] is True
    assert restored_modes == ["paused"]


def test_dashboard_endpoint_is_authenticated_and_allowlisted(tmp_path):
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "running": True,
                "pid": os.getpid(),
                "started_at": "2026-07-16T22:00:00+00:00",
                "game_state": {"location": "Pallet Town"},
                "rom_path": "/private/owned.gb",
                "reason": "private reasoning",
            }
        )
    )
    server = ViewerServer(tmp_path, 0, queue.Queue())
    server.start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as forbidden:
            urllib.request.urlopen(base + "/api/dashboard")
        assert forbidden.value.code == 403

        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )
        opener.open(base + f"/?token={server.token}").close()
        with opener.open(base + "/api/dashboard") as response:
            snapshot = json.load(response)
        serialized = json.dumps(snapshot)
        assert snapshot["location"] == "Pallet Town"
        assert "/private/owned.gb" not in serialized
        assert "private reasoning" not in serialized
    finally:
        server.stop()


def test_dashboard_markup_transport_pip_and_resilience_contracts():
    for heading in (
        "Now Playing",
        "Run Progress",
        "Current Party",
        "Run Details",
        "Stream Health",
    ):
        assert heading in SPECTATOR_HTML
    assert "<aside" in SPECTATOR_HTML
    assert "document.createElement('progress')" in SPECTATOR_JS
    assert 'aria-live="polite"' in SPECTATOR_HTML
    assert "Video has no audio." in SPECTATOR_HTML
    assert "@media (max-width: 480px)" in SPECTATOR_CSS
    assert "@media (prefers-reduced-motion: reduce)" in SPECTATOR_CSS
    assert "@media (forced-colors: active)" in SPECTATOR_CSS
    assert "min-width: 320px" in SPECTATOR_CSS

    assert SPECTATOR_JS.count("dataConnection.send(") == 1
    assert "type: 'watch'" in SPECTATOR_JS
    assert "globalThis.performance.now()" in SPECTATOR_JS
    assert "value.sequence <= telemetrySequence" in SPECTATOR_JS
    assert "textContent" in SPECTATOR_JS
    assert "innerHTML" not in SPECTATOR_JS
    assert "getDisplayMedia" not in VIEWER_JS
    assert "/api/dashboard" in VIEWER_JS
    assert "connectionIsBackpressured" in VIEWER_JS
    assert "requestPictureInPicture" in VIEWER_JS
    assert "webkitSetPresentationMode" in VIEWER_JS
    assert 'id="pip-toggle"' in VIEWER_HTML
    assert "Caught / owned" in SPECTATOR_HTML
    assert 'id="badge-count">— / 8 badges' in SPECTATOR_HTML
    assert 'id="completion">Unknown' in SPECTATOR_HTML
    assert "0 / 8 badges" not in SPECTATOR_HTML
    assert 'id="completion">Not yet' not in SPECTATOR_HTML
    assert SPECTATOR_HTML.count('aria-live="polite"') == 3
    assert "Last known run details" in SPECTATOR_JS
    for event in ("playing", "waiting", "stalled", "pause", "error"):
        assert f"video.addEventListener('{event}'" in SPECTATOR_JS

    assert LIVESTREAM_HEARTBEAT_SECONDS >= 15
    assert LIVESTREAM_LEASE_TTL_SECONDS >= 120
    assert LIVESTREAM_REPORT_STALE_SECONDS >= 90
