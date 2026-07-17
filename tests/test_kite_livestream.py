from __future__ import annotations

import hashlib
import json
import queue
import signal
import stat
from pathlib import Path
from types import SimpleNamespace

import openrappter.agents.pokemon_agent as pokemon_module
from openrappter.agents.pokemon_agent import (
    DEFAULT_PAGES_HOST_BASE,
    DEFAULT_PAGES_WATCH_BASE,
    KITE_STRING_JS,
    KITE_STRING_SCHEMA_VERSION,
    KiteBroadcaster,
    PokemonAgent,
    PokemonRunner,
    ViewerServer,
    build_join_url,
    livestream_share_info,
)

from rappter_plays_pokemon import cli

ROOT = Path(__file__).resolve().parents[1]


def synthetic_png() -> bytes:
    payload = bytearray(33)
    payload[:8] = b"\x89PNG\r\n\x1a\n"
    payload[12:16] = b"IHDR"
    payload[16:20] = (160).to_bytes(4, "big")
    payload[20:24] = (144).to_bytes(4, "big")
    return bytes(payload)


def test_cli_defaults_to_kited_twin_and_supports_all_overrides(tmp_path):
    args = cli.build_parser().parse_args(
        [
            "start",
            "--runtime-dir",
            str(tmp_path),
            "--livestream",
            "--browser-path",
            "/Applications/Test Chrome",
            "--host-base",
            "https://host.example.test/",
            "--bridge-startup-timeout",
            "12",
        ]
    )
    values = cli.agent_kwargs(args, {})

    assert values["livestream_host"] == "kite"
    assert values["browser_path"] == "/Applications/Test Chrome"
    assert values["host_base"] == "https://host.example.test/"
    assert values["bridge_startup_timeout"] == 12
    assert "host" in cli.ACTIONS
    assert "go-live" in cli.ACTIONS
    assert "provision-browser" in cli.ACTIONS


def test_kite_mode_creates_private_bootstrap_without_lan_server(tmp_path):
    generation = "generation-" + "g" * 24
    peer_id = "rpp-" + "a" * 32
    capability = "w" * 43
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.args = SimpleNamespace(join_base=None)
    runner.livestream_enabled = True
    runner.livestream_host = "kite"
    runner.host_base = DEFAULT_PAGES_HOST_BASE
    runner.browser_path = ""
    runner.bridge_startup_timeout = 20.0
    runner.stream_peer_id = peer_id
    runner.watch_capability = capability
    runner.stream_generation = generation
    runner.kite_instance = "instance-" + "i" * 24
    runner.max_viewers = 5
    runner.livestream_config = {"enabled": True}
    runner.status = {
        "livestream": {
            "enabled": True,
            "host": "kite",
            "state": "offline",
            "viewer_count": 0,
            "max_viewers": 5,
            "spectator_port": None,
            "generation": generation,
        }
    }
    runner.spectator = None
    runner.viewer = ViewerServer(tmp_path, 0, queue.Queue(), {"enabled": False})

    runner._start_web_servers()
    try:
        private = json.loads((tmp_path / "livestream-auth.json").read_text())
        bootstrap = json.loads((tmp_path / "kite-bootstrap.json").read_text())
        desired = json.loads(
            (tmp_path / "kite-broadcast-state.json").read_text()
        )
        assert private["livestream_host"] == "kite"
        assert private["spectator_port"] is None
        assert private["join_url"] == build_join_url(
            DEFAULT_PAGES_WATCH_BASE,
            peer_id,
            capability,
        )
        assert bootstrap["join_url"] == private["join_url"]
        assert bootstrap["host_base"] == DEFAULT_PAGES_HOST_BASE
        assert bootstrap["instance"] == runner.kite_instance
        assert desired == {
            "schema_version": KITE_STRING_SCHEMA_VERSION,
            "generation": generation,
            "instance": runner.kite_instance,
            "sequence": 0,
            "desired": True,
            "updated_at": desired["updated_at"],
        }
        assert stat.S_IMODE(
            (tmp_path / "livestream-auth.json").stat().st_mode
        ) == 0o600
        assert stat.S_IMODE(
            (tmp_path / "kite-bootstrap.json").stat().st_mode
        ) == 0o600
        assert runner.status["livestream"]["spectator_port"] is None
    finally:
        runner.viewer.stop()


def test_frame_manifest_is_generation_bound_atomic_and_hash_exact(tmp_path):
    class Image:
        def save(self, path: Path, format: str) -> None:
            assert format == "PNG"
            path.write_bytes(synthetic_png())

    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.livestream_enabled = True
    runner.livestream_host = "kite"
    runner.stream_generation = "generation-" + "g" * 24
    runner.kite_frame_sequence = 0

    runner._save_latest_frame(Image())
    first = json.loads((tmp_path / "kite-frame.json").read_text())
    runner._save_latest_frame(Image())
    second = json.loads((tmp_path / "kite-frame.json").read_text())

    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert first["generation"] == runner.stream_generation
    assert first["bytes"] == len(synthetic_png())
    assert first["sha256"] == hashlib.sha256(synthetic_png()).hexdigest()
    assert stat.S_IMODE((tmp_path / "latest.png").stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))


def test_share_waits_for_kite_peer_and_first_frame(tmp_path):
    generation = "generation-" + "g" * 24
    join_url = build_join_url(
        DEFAULT_PAGES_WATCH_BASE,
        "rpp-" + "a" * 32,
        "w" * 43,
    )
    (tmp_path / "livestream-auth.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "livestream_host": "kite",
                "join_url": join_url,
                "generation": generation,
                "max_viewers": 5,
                "spectator_port": None,
            }
        )
    )
    (tmp_path / "livestream-status.json").write_text(
        json.dumps(
            {
                "state": "connecting",
                "viewer_count": 0,
                "generation": generation,
                "updated_at": pokemon_module.utc_now(),
            }
        )
    )
    base_status = {
        "schema_version": KITE_STRING_SCHEMA_VERSION,
        "generation": generation,
        "instance": "instance-" + "i" * 24,
        "bridge_state": "ready",
        "share_ready": False,
        "automatic_share_ready": False,
        "manual_share_ready": True,
        "source_health": "ok",
        "string_health": "ok",
        "runtime_health": "ready",
        "peer_health": "offline",
        "signaling": "nostr",
        "relay_health": "blocked",
        "relay_qualified_count": 0,
        "first_frame": True,
        "updated_at": pokemon_module.utc_now(),
    }
    (tmp_path / "kite-host-status.json").write_text(json.dumps(base_status))

    unavailable = livestream_share_info(tmp_path)
    assert unavailable["available"] is False
    assert unavailable["automatic_available"] is False
    assert unavailable["manual_available"] is True
    assert "join_url" not in unavailable

    base_status.update(
        {
            "share_ready": True,
            "automatic_share_ready": True,
            "peer_health": "open",
            "relay_health": "qualified",
            "relay_qualified_count": 1,
            "updated_at": pokemon_module.utc_now(),
        }
    )
    (tmp_path / "kite-host-status.json").write_text(json.dumps(base_status))
    available = livestream_share_info(tmp_path)
    assert available["available"] is True
    assert available["join_url"] == join_url

    base_status.update(
        {
            "share_ready": True,
            "source_health": "lost",
            "updated_at": pokemon_module.utc_now(),
        }
    )
    (tmp_path / "kite-host-status.json").write_text(json.dumps(base_status))
    rejected = livestream_share_info(tmp_path)
    assert rejected["available"] is False
    assert "join_url" not in rejected


def test_host_action_uses_generation_bound_focus_file(
    tmp_path,
    monkeypatch,
):
    generation = "generation-" + "g" * 24
    instance = "instance-" + "i" * 24
    (tmp_path / "livestream-auth.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "livestream_host": "kite",
                "generation": generation,
                "instance": instance,
            }
        )
    )
    monkeypatch.setattr(
        pokemon_module,
        "runtime_status",
        lambda _runtime_dir: {
            "running": True,
            "livestream": {"enabled": True, "host": "kite"},
        },
    )

    result = json.loads(PokemonAgent().perform(action="host", runtime_dir=tmp_path))
    command = json.loads((tmp_path / "kite-command.json").read_text())

    assert result["status"] == "success"
    assert command == {
        "schema_version": KITE_STRING_SCHEMA_VERSION,
        "generation": generation,
        "instance": instance,
        "sequence": 1,
        "action": "focus",
    }
    assert stat.S_IMODE((tmp_path / "kite-command.json").stat().st_mode) == 0o600


def test_go_live_explicitly_clears_generation_bound_end_latch(
    tmp_path,
    monkeypatch,
):
    generation = "generation-" + "g" * 24
    instance = "instance-" + "i" * 24
    (tmp_path / "livestream-auth.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "livestream_host": "kite",
                "generation": generation,
                "instance": instance,
            }
        )
    )
    (tmp_path / "kite-broadcast-state.json").write_text(
        json.dumps(
            {
                "schema_version": KITE_STRING_SCHEMA_VERSION,
                "generation": generation,
                "instance": instance,
                "sequence": 7,
                "desired": False,
                "updated_at": pokemon_module.utc_now(),
            }
        )
    )
    monkeypatch.setattr(
        pokemon_module,
        "runtime_status",
        lambda _runtime_dir: {
            "running": True,
            "livestream": {"enabled": True, "host": "kite"},
        },
    )

    result = json.loads(
        PokemonAgent().perform(action="go-live", runtime_dir=tmp_path)
    )
    desired = json.loads((tmp_path / "kite-broadcast-state.json").read_text())

    assert result["status"] == "success"
    assert desired["generation"] == generation
    assert desired["instance"] == instance
    assert desired["sequence"] == 8
    assert desired["desired"] is True
    assert stat.S_IMODE(
        (tmp_path / "kite-broadcast-state.json").stat().st_mode
    ) == 0o600


def test_missing_node_degrades_sidecar_without_exposing_bootstrap(
    tmp_path,
    monkeypatch,
):
    generation = "generation-" + "g" * 24
    instance = "instance-" + "i" * 24
    (tmp_path / "kite-bootstrap.json").write_text(
        json.dumps({"instance": instance})
    )
    sidecar = KiteBroadcaster(tmp_path, generation, 10)
    monkeypatch.setattr(sidecar, "_node_executable", lambda: None)

    assert sidecar.start() is False
    status = json.loads((tmp_path / "kite-host-status.json").read_text())
    assert status["bridge_state"] == "degraded"
    assert status["share_ready"] is False
    assert stat.S_IMODE(sidecar.script_path.stat().st_mode) == 0o600
    assert sidecar.script_path.read_bytes() == KITE_STRING_JS
    assert KITE_STRING_JS == (ROOT / "scripts" / "kite_vtwin.js").read_bytes()
    assert generation not in status["error"]
    sidecar.stop()
    assert not sidecar.script_path.exists()


def test_sidecar_cleanup_targets_only_tracked_process_groups(
    tmp_path,
    monkeypatch,
):
    generation = "generation-" + "g" * 24
    instance = "instance-" + "i" * 24
    sidecar = KiteBroadcaster(tmp_path, generation, 10)
    sidecar.profile_path.mkdir()
    (sidecar.profile_path / "rpp-kite-profile.json").write_text(
        json.dumps(
            {
                "schema_version": KITE_STRING_SCHEMA_VERSION,
                "generation": generation,
                "instance": instance,
                "token": "a" * 48,
                "created_at": pokemon_module.utc_now(),
            }
        )
    )
    sidecar.script_path.write_text("synthetic")
    (tmp_path / "kite-bootstrap.json").write_text("{}")

    class Input:
        closed = False

        def close(self):
            self.closed = True

    class Process:
        pid = 32123
        stdin = Input()

        def poll(self):
            return None

        def wait(self, timeout):
            assert timeout == 8
            return 0

    process = Process()
    sidecar.process = process
    sidecar.browser_records["b" * 48] = {
        "schema_version": KITE_STRING_SCHEMA_VERSION,
        "generation": generation,
        "instance": instance,
        "token": "b" * 48,
        "pid": 32124,
        "pgid": 32124,
        "start_identity": "Fri Jul 17 01:00:00 2026",
        "profile": str(sidecar.profile_path),
        "created_at": pokemon_module.utc_now(),
    }
    rows = [
        {
            "pid": 32125,
            "pgid": 32124,
            "start_identity": "Fri Jul 17 01:00:01 2026",
            "command": (
                f"chrome --user-data-dir={sidecar.profile_path} "
                f"--rpp-kite-owner-token={'b' * 48}"
            ),
        }
    ]
    signals: list[tuple[int, signal.Signals]] = []

    def kill_group(pid, sent):
        signals.append((pid, sent))
        if pid == 32124:
            rows.clear()

    monkeypatch.setattr(pokemon_module.os, "killpg", kill_group)
    monkeypatch.setattr(sidecar, "_process_rows", lambda: list(rows))

    sidecar.stop()

    assert process.stdin.closed is True
    assert (32123, signal.SIGTERM) in signals
    assert (32124, signal.SIGTERM) in signals
    assert sidecar.browser_records == {}
    assert not sidecar.profile_path.exists()
    assert not sidecar.script_path.exists()


def test_sidecar_never_kills_reused_browser_pid(tmp_path, monkeypatch):
    generation = "generation-" + "g" * 24
    instance = "instance-" + "i" * 24
    sidecar = KiteBroadcaster(tmp_path, generation, 10)
    token = "c" * 48
    sidecar.browser_records[token] = {
        "schema_version": KITE_STRING_SCHEMA_VERSION,
        "generation": generation,
        "instance": instance,
        "token": token,
        "pid": 43210,
        "pgid": 43210,
        "start_identity": "Fri Jul 17 01:00:00 2026",
        "profile": str(sidecar.profile_path),
        "created_at": pokemon_module.utc_now(),
    }
    monkeypatch.setattr(
        sidecar,
        "_process_rows",
        lambda: [
            {
                "pid": 43210,
                "pgid": 43210,
                "start_identity": "Fri Jul 17 02:00:00 2026",
                "command": (
                    f"chrome --user-data-dir={sidecar.profile_path} "
                    f"--rpp-kite-owner-token={token}"
                ),
            }
        ],
    )
    signals: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(
        pokemon_module.os,
        "killpg",
        lambda pid, sent: signals.append((pid, sent)),
    )

    sidecar._terminate_known_browsers()

    assert signals == []
    assert sidecar.browser_records == {}


def test_python_sidecar_never_unlinks_string_ownership_lock(tmp_path):
    generation = "generation-" + "g" * 24
    sidecar = KiteBroadcaster(tmp_path, generation, 10)
    lock = tmp_path / "kite-string.lock"
    lock.mkdir()
    (lock / "owner.json").write_text(
        json.dumps(
            {
                "schema_version": KITE_STRING_SCHEMA_VERSION,
                "token": "d" * 48,
                "generation": generation,
                "instance": "instance-" + "i" * 24,
                "pid": 99999,
            }
        )
    )
    browser_owner = tmp_path / "kite-browser-owner.json"
    browser_owner.write_text(
        json.dumps(
            {
                "schema_version": KITE_STRING_SCHEMA_VERSION,
                "token": "e" * 48,
                "generation": generation,
                "instance": "instance-" + "i" * 24,
                "pid": 99998,
                "pgid": 99998,
                "profile": str(tmp_path / f"kite-profile-{generation}"),
            }
        )
    )

    sidecar.stop()

    assert lock.is_dir()
    assert (lock / "owner.json").is_file()
    assert browser_owner.is_file()
