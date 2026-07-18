from __future__ import annotations

import asyncio
import base64
import json
import os
import stat
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import openrappter.agents.pokemon_agent as pokemon_module
import pytest
from openrappter.agents.pokemon_agent import (
    CopilotBrain,
    PokemonAgent,
    ViewerServer,
    authenticated_viewer_url,
    discover_pokemon_red_rom,
    heartbeat_is_stale,
    runner_main,
    runtime_status,
    wait_for_supervised_child,
)

from rappter_plays_pokemon import cli
from rappter_plays_pokemon.install_agent import install_agent, sha256

ROOT = Path(__file__).resolve().parents[1]


def test_rom_discovery_does_not_scan_user_directories(monkeypatch, tmp_path):
    monkeypatch.setattr(pokemon_module, "DEFAULT_RUNTIME_DIR", tmp_path)
    monkeypatch.delenv("OPENRAPPTER_POKEMON_ROM", raising=False)
    scanned: list[Path] = []
    original_is_file = Path.is_file

    def record_is_file(path: Path) -> bool:
        scanned.append(path)
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", record_is_file)

    with pytest.raises(FileNotFoundError, match="legally obtained"):
        discover_pokemon_red_rom()

    assert all("Downloads" not in str(path) for path in scanned)
    assert all("Documents" not in str(path) for path in scanned)


def test_rom_discovery_reads_the_active_runtime_config(tmp_path):
    rom = tmp_path / "owned.gb"
    data = bytearray(256 * 1024)
    data[0x134 : 0x134 + len(b"POKEMON RED")] = b"POKEMON RED"
    rom.write_bytes(data)
    custom_runtime = tmp_path / "custom-runtime"
    custom_runtime.mkdir()
    (custom_runtime / "config.json").write_text(
        json.dumps({"rom_path": str(rom)}),
        encoding="utf-8",
    )

    assert discover_pokemon_red_rom(runtime_dir=custom_runtime) == rom.resolve()


def test_copilot_session_has_zero_tools_and_no_discovery(tmp_path):
    captured: dict[str, object] = {}

    class Client:
        async def create_session(self, **kwargs):
            captured.update(kwargs)
            return object()

    brain = CopilotBrain.__new__(CopilotBrain)
    brain.model = "gpt-5.6-sol"
    brain.reasoning_effort = "medium"
    brain.client = Client()
    brain.session = None
    brain.session_decisions = 99

    asyncio.run(brain._create_sdk_session())

    assert captured["model"] == "gpt-5.6-sol"
    assert captured["reasoning_effort"] == "medium"
    assert captured["available_tools"] == []
    assert captured["skip_custom_instructions"] is True
    assert captured["enable_config_discovery"] is False
    assert captured["enable_on_demand_instruction_discovery"] is False
    assert captured["enable_skills"] is False
    assert captured["enable_session_store"] is False
    assert captured["enable_session_telemetry"] is False
    assert captured["memory"] == {"enabled": False}


def test_copilot_attaches_only_current_screenshot(tmp_path):
    screenshot = tmp_path / "frame.png"
    screenshot.write_bytes(b"synthetic-png")
    captured: dict[str, object] = {}

    class Session:
        async def send_and_wait(self, prompt, attachments, timeout):
            captured.update(
                prompt=prompt,
                attachments=attachments,
                timeout=timeout,
            )
            return SimpleNamespace(
                data=SimpleNamespace(content='{"buttons":["a"],"checkpoint":false}')
            )

    brain = CopilotBrain.__new__(CopilotBrain)
    brain.session = Session()
    brain.session_decisions = 0
    brain.max_decisions_per_session = 24
    brain.timeout_seconds = 30

    result = asyncio.run(brain._decide_sdk(screenshot, "game state only"))

    assert result["buttons"] == ["a"]
    assert captured["prompt"] == "game state only"
    attachments = captured["attachments"]
    assert isinstance(attachments, list)
    assert attachments == [
        {
            "type": "blob",
            "data": base64.b64encode(b"synthetic-png").decode("ascii"),
            "mimeType": "image/png",
        }
    ]


def test_authenticated_viewer_url_uses_private_token_file(tmp_path):
    controls = pokemon_module.queue.Queue()
    server = ViewerServer(tmp_path, 0, controls)
    server.start()
    try:
        auth_path = tmp_path / "viewer-auth.json"
        mode = stat.S_IMODE(auth_path.stat().st_mode)
        url = authenticated_viewer_url(tmp_path, {"port": server.port})
        assert mode == 0o600
        assert url.startswith(f"http://127.0.0.1:{server.port}/?token=")
        assert server.token in url
        assert server.token not in json.dumps(
            pokemon_module.public_runtime_status(tmp_path)
        )
    finally:
        server.stop()
    assert not (tmp_path / "viewer-auth.json").exists()


def test_old_status_cannot_kill_new_supervised_child(tmp_path):
    (tmp_path / "desired.json").write_text('{"running":true}', encoding="utf-8")
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "pid": 111,
                "lifecycle": "failed",
                "heartbeat_at": "2000-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    class Child:
        pid = 222
        calls = 0
        terminated = False

        def wait(self, timeout):
            del timeout
            self.calls += 1
            if self.calls == 1:
                raise pokemon_module.subprocess.TimeoutExpired("child", 1)
            return 0

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

    child = Child()
    assert wait_for_supervised_child(child, threading.Event(), tmp_path) == (0, False)
    assert child.terminated is False


def test_stale_matching_heartbeat_requests_restart(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    (tmp_path / "desired.json").write_text('{"running":true}', encoding="utf-8")
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "pid": 333,
                "lifecycle": "ready",
                "heartbeat_at": old,
            }
        ),
        encoding="utf-8",
    )

    class Child:
        pid = 333
        returncode = None

        def wait(self, timeout):
            if self.returncode is None:
                raise pokemon_module.subprocess.TimeoutExpired("child", timeout)
            return self.returncode

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def kill(self):
            self.returncode = -9

    assert heartbeat_is_stale({"heartbeat_at": old}, 45)
    assert wait_for_supervised_child(Child(), threading.Event(), tmp_path) == (0, True)
    restart = json.loads((tmp_path / pokemon_module.RESTART_REQUEST_NAME).read_text())
    assert restart["child_pid"] == 333
    assert restart["reason"] == "stale heartbeat"


def test_stale_initializing_status_is_not_running(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "running": True,
                "lifecycle": "initializing",
                "started_at": old,
            }
        ),
        encoding="utf-8",
    )
    assert runtime_status(tmp_path)["running"] is False


def test_installer_atomically_copies_single_file_agent(tmp_path):
    destination = install_agent(ROOT / "pokemon_agent.py", tmp_path)

    assert destination == tmp_path / "pokemon_agent.py"
    assert sha256(destination) == sha256(ROOT / "pokemon_agent.py")
    assert list(tmp_path.glob("*.tmp")) == []


def test_cli_config_and_agent_dispatch(monkeypatch, tmp_path):
    rom = tmp_path / "Pokemon - Red Version (UE)[!].gb"
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "rom_path": str(rom),
                "runtime_dir": str(tmp_path / "runtime"),
                "max_clips": 12,
                "open_viewer": False,
                "livestream": True,
                "youtube_chat_hints": True,
                "stuck_web_research": True,
                "spectator_port": 0,
                "advertised_host": "pokemon.local",
                "max_viewers": 4,
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def perform(self, **kwargs):
        del self
        captured.update(kwargs)
        return '{"status":"success","message":"mocked"}'

    monkeypatch.setattr(PokemonAgent, "perform", perform)
    exit_code, result = cli.run(["start", "--config", str(config)])

    assert exit_code == 0
    assert result["message"] == "mocked"
    assert captured["rom_path"] == str(rom)
    assert captured["max_clips"] == 12
    assert captured["open_viewer"] is False
    assert captured["livestream"] is True
    assert captured["youtube_chat_hints"] is True
    assert captured["stuck_web_research"] is True
    assert captured["spectator_port"] == 0
    assert captured["advertised_host"] == "pokemon.local"
    assert captured["max_viewers"] == 4
    assert captured["model"] == "gpt-5.6-sol"
    assert captured["reasoning_effort"] == "medium"


def test_launchers_preserve_rom_paths_as_single_arguments():
    launch = (ROOT / "launch.sh").read_text()
    bootstrap = (ROOT / "bootstrap.sh").read_text()
    story = (ROOT / "story.sh").read_text()
    chat = (ROOT / "chat.sh").read_text()

    assert 'rappter_plays_pokemon.cli "$@"' in launch
    assert 'rappter_plays_pokemon.story "$@"' in story
    assert 'rappter_plays_pokemon.youtube_chat "$@"' in chat
    assert '"${LAUNCH_ARGS[@]}"' in bootstrap
    assert 'if [[ "$ACTION" == "start" ]]' in launch
    assert launch.index('if [[ "$ACTION" == "start" ]]') < launch.index(
        "rappter_plays_pokemon.install_agent"
    )
    assert "refusing to replace the registered agent" in launch


def test_raw_chat_artifacts_are_ignored_and_rejected_by_ci():
    ignore = (ROOT / ".gitignore").read_text()
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    for pattern in (
        "*.live_chat.json*",
        "youtube-chat-advisory.json",
        "navigation-memory.json",
        "web-research.json",
    ):
        assert pattern in ignore
        assert pattern in workflow


def test_launch_preflight_bypasses_controls_and_blocks_live_start(
    monkeypatch,
    tmp_path,
):
    assert cli.launch_preflight(
        ["stop", "--runtime-dir", str(tmp_path)]
    ) == ("stop", False)

    monkeypatch.setattr(
        PokemonAgent,
        "perform",
        lambda self, **kwargs: json.dumps(
            {
                "status": "success",
                "running": kwargs["action"] == "status",
            }
        ),
    )
    assert cli.launch_preflight(
        ["start", "--runtime-dir", str(tmp_path)]
    ) == ("start", True)

    monkeypatch.setattr(
        PokemonAgent,
        "perform",
        lambda self, **kwargs: json.dumps(
            {"status": "success", "running": False}
        ),
    )
    (tmp_path / "supervisor.json").write_text(
        json.dumps({"running": True, "pid": os.getpid()}),
        encoding="utf-8",
    )
    assert cli.launch_preflight(
        ["start", "--runtime-dir", str(tmp_path)]
    ) == ("start", True)


@pytest.mark.parametrize(
    ("preflight", "action", "expected_install", "expected_code"),
    [
        ("stop\t0", "stop", False, 0),
        ("start\t0", "start", True, 0),
        ("start\t1", "start", False, 1),
    ],
)
def test_launch_shell_never_installs_for_controls_or_live_start(
    tmp_path,
    preflight,
    action,
    expected_install,
    expected_code,
):
    launcher = tmp_path / "launch.sh"
    launcher.write_bytes((ROOT / "launch.sh").read_bytes())
    launcher.chmod(0o755)
    (tmp_path / "pokemon_agent.py").write_text("synthetic", encoding="utf-8")
    python = tmp_path / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    log = tmp_path / "python.log"
    python.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {str(log)!r}\n"
        'if [[ "$1" == "-c" ]]; then\n'
        f"  printf '%b\\n' {preflight!r}\n"
        "fi\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uname = bin_dir / "uname"
    uname.write_text(
        "#!/usr/bin/env bash\nprintf 'Darwin\\n'\n",
        encoding="utf-8",
    )
    uname.chmod(0o755)

    result = subprocess.run(
        [str(launcher), action],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == expected_code
    invocations = log.read_text(encoding="utf-8")
    assert ("rappter_plays_pokemon.install_agent" in invocations) is expected_install
    if action == "stop":
        assert "rappter_plays_pokemon.cli stop" in invocations


def test_rom_free_runner_smoke_uses_mock_runtime(monkeypatch, tmp_path):
    class MockRunner:
        def __init__(self, args):
            del args
            self.status = {"lifecycle": "stopped"}
            self.stream_generation = None
            self.stop_event = threading.Event()
            self.brain_ready = threading.Event()
            self.brain = None

        def run(self):
            return None

    monkeypatch.setattr(pokemon_module, "PokemonRunner", MockRunner)
    monkeypatch.setattr(pokemon_module.signal, "signal", lambda *args: None)

    assert (
        runner_main(
            [
                "run",
                "--rom",
                str(tmp_path / "not-read.gb"),
                "--runtime-dir",
                str(tmp_path),
                "--instance-id",
                "rom-free-smoke",
            ]
        )
        == 0
    )
