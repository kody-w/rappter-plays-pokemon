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
    LIVESTREAM_HEARTBEAT_SECONDS,
    LIVESTREAM_LEASE_TTL_SECONDS,
    LIVESTREAM_REPORT_STALE_SECONDS,
    MAX_TELEMETRY_BYTES,
    SPECTATOR_CSS,
    SPECTATOR_HTML,
    SPECTATOR_JS,
    TELEMETRY_VERSION,
    VIEWER_HTML,
    VIEWER_JS,
    ActionPlayer,
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
    assert SPECTATOR_HTML.count('aria-live="polite"') == 2
    assert "Last known run details" in SPECTATOR_JS
    for event in ("playing", "waiting", "stalled", "pause", "error"):
        assert f"video.addEventListener('{event}'" in SPECTATOR_JS

    assert LIVESTREAM_HEARTBEAT_SECONDS >= 15
    assert LIVESTREAM_LEASE_TTL_SECONDS >= 120
    assert LIVESTREAM_REPORT_STALE_SECONDS >= 90
