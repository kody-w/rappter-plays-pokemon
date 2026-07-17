from __future__ import annotations

import hashlib
import json
import os
import queue
import socket
import stat
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path

import openrappter.agents.pokemon_agent as pokemon_module
import pytest
from openrappter.agents.pokemon_agent import (
    HARD_MAX_NEGOTIATING,
    HARD_MAX_VIEWERS,
    LIVESTREAM_REPORT_STALE_SECONDS,
    PEERJS_ICE_CONFIG,
    PEERJS_MIN_JS,
    PEERJS_SHA256,
    QRIOUS_MIN_JS,
    QRIOUS_SHA256,
    SPECTATOR_HTML,
    SPECTATOR_JS,
    THIRD_PARTY_BROWSER_LICENSES,
    VIEWER_HTML,
    VIEWER_JS,
    LivestreamLeaseError,
    LivestreamLeaseManager,
    PokemonAgent,
    PokemonRunner,
    SpectatorServer,
    ViewerServer,
    build_join_url,
    build_parser,
    livestream_public_state,
    public_runtime_status,
    runtime_command,
    validate_advertised_host,
    validate_external_join_base,
    validate_watch_hello,
    watch_admission_decision,
)

ROOT = Path(__file__).resolve().parents[1]


def authenticated_opener(server: ViewerServer) -> urllib.request.OpenerDirector:
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar())
    )
    opener.open(
        f"http://127.0.0.1:{server.port}/?token={server.token}"
    ).close()
    return opener


def post_json(
    opener: urllib.request.OpenerDirector,
    base: str,
    path: str,
    value: dict[str, object],
) -> dict[str, object]:
    request = urllib.request.Request(
        base + path,
        data=json.dumps(value).encode(),
        headers={"Content-Type": "application/json", "Origin": base},
        method="POST",
    )
    with opener.open(request) as response:
        return json.load(response)


def test_join_link_secrets_are_fragment_only():
    peer_id = "rpp-" + "a" * 32
    capability = "b" * 43

    join_url = build_join_url(
        "http://192.168.1.20:45678/",
        peer_id,
        capability,
    )
    parsed = urllib.parse.urlsplit(join_url)
    fragment = urllib.parse.parse_qs(parsed.fragment)

    assert parsed.scheme == "http"
    assert parsed.netloc == "192.168.1.20:45678"
    assert parsed.query == ""
    assert peer_id not in join_url.split("#", 1)[0]
    assert capability not in join_url.split("#", 1)[0]
    assert fragment == {"v": ["1"], "host": [peer_id], "watch": [capability]}
    assert (
        validate_external_join_base("https://watch.example.test/live/")
        == "https://watch.example.test/live/"
    )
    with pytest.raises(ValueError, match="HTTPS"):
        validate_external_join_base("http://watch.example.test")
    with pytest.raises(ValueError, match="valid URL"):
        validate_external_join_base("https://watch.example.test:70000/live")
    with pytest.raises(ValueError, match="valid URL"):
        validate_external_join_base("https://[broken/live")
    with pytest.raises(ValueError, match="IPv4"):
        validate_advertised_host("2001:db8::1")


def test_watch_protocol_rejects_control_shapes_and_enforces_cap():
    capability = "c" * 43
    hello = {"v": 1, "type": "watch", "cap": capability}

    assert validate_watch_hello(hello, capability)
    assert watch_admission_decision(hello, capability, 4, 5) == "accept"
    assert watch_admission_decision(hello, capability, 5, 5) == "capacity"
    assert (
        watch_admission_decision(hello, capability, HARD_MAX_VIEWERS, 99)
        == "capacity"
    )
    assert not validate_watch_hello({**hello, "action": "press"}, capability)
    assert not validate_watch_hello({"v": 1, "type": "watch", "cap": "wrong"}, capability)
    assert not validate_watch_hello(
        {"v": 1, "type": "watch", "cap": capability, "padding": "x" * 600},
        capability,
    )
    assert "keys !== 'cap,type,v'" in VIEWER_JS
    assert "call.peer !== capability.host" in SPECTATOR_JS


def test_generation_scoped_browser_lease_rejects_competitors_and_expires():
    now = [100.0]
    generation = "generation-" + "a" * 24
    first_owner = "owner-" + "b" * 24
    second_owner = "owner-" + "c" * 24
    manager = LivestreamLeaseManager(
        generation,
        ttl_seconds=10,
        clock=lambda: now[0],
    )

    first = manager.acquire(first_owner, generation)
    with pytest.raises(LivestreamLeaseError, match="owner-active"):
        manager.acquire(second_owner, generation)
    with pytest.raises(LivestreamLeaseError, match="generation-mismatch"):
        manager.validate(first_owner, "old-generation-" + "x" * 16, first["lease"])

    now[0] += 11
    second = manager.acquire(second_owner, generation)
    assert second["owner"] == second_owner
    with pytest.raises(LivestreamLeaseError, match="lease-lost"):
        manager.validate(first_owner, generation, first["lease"])


def test_stale_or_wrong_generation_stream_reports_are_offline(tmp_path):
    generation = "generation-" + "d" * 24
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    status_path = tmp_path / "livestream-status.json"
    status_path.write_text(
        json.dumps(
            {
                "state": "live",
                "viewer_count": 4,
                "generation": generation,
                "updated_at": (
                    now - timedelta(seconds=LIVESTREAM_REPORT_STALE_SECONDS + 1)
                ).isoformat(),
            }
        )
    )

    assert livestream_public_state(
        tmp_path,
        expected_generation=generation,
        now=now,
    )["state"] == "offline"
    assert livestream_public_state(
        tmp_path,
        expected_generation=generation,
        now=now,
    )["viewer_count"] == 0

    status_path.write_text(
        json.dumps(
            {
                "state": "live",
                "viewer_count": 2,
                "generation": generation,
                "updated_at": now.isoformat(),
            }
        )
    )
    assert livestream_public_state(
        tmp_path,
        expected_generation="different-" + "e" * 24,
        now=now,
    )["state"] == "offline"
    assert livestream_public_state(
        tmp_path,
        expected_generation=generation,
        now=now,
    )["state"] == "live"


def test_supervisor_propagates_livestream_configuration(tmp_path):
    args = build_parser().parse_args(
        [
            "supervise",
            "--rom",
            str(tmp_path / "owned.gb"),
            "--runtime-dir",
            str(tmp_path),
            "--port",
            "0",
            "--livestream",
            "--spectator-port",
            "0",
            "--advertised-host",
            "pokemon.local",
            "--join-base",
            "https://watch.example.test/live",
            "--max-viewers",
            "4",
        ]
    )
    args.instance_id = "livestream-test"

    command = runtime_command(args, open_viewer=False)

    assert command[3] == "run"
    assert command[command.index("--port") + 1] == "0"
    assert command[command.index("--spectator-port") + 1] == "0"
    assert command[command.index("--advertised-host") + 1] == "pokemon.local"
    assert (
        command[command.index("--join-base") + 1]
        == "https://watch.example.test/live"
    )
    assert command[command.index("--max-viewers") + 1] == "4"
    assert "--livestream" in command
    assert "--open-viewer" in command


def test_vendored_peerjs_and_qrious_are_pinned_and_embedded():
    vendor = ROOT / "vendor" / "browser"
    provenance = json.loads((vendor / "PROVENANCE.json").read_text())

    assert hashlib.sha256(PEERJS_MIN_JS).hexdigest() == PEERJS_SHA256
    assert hashlib.sha256(QRIOUS_MIN_JS).hexdigest() == QRIOUS_SHA256
    assert PEERJS_MIN_JS == (vendor / "peerjs-1.5.5.min.js").read_bytes()
    assert QRIOUS_MIN_JS == (vendor / "qrious-4.0.2.min.js").read_bytes()
    assert b"Peer" in PEERJS_MIN_JS
    assert b"QRious" in QRIOUS_MIN_JS
    assert "MIT License" in (vendor / "peerjs-1.5.5.LICENSE").read_text()
    assert "GNU General Public License" in (
        vendor / "qrious-4.0.2.LICENSE.md"
    ).read_text()
    assert (vendor / "qrious-4.0.2.js").is_file()
    assert provenance["assets"][1]["license"] == "GPL-3.0-or-later"
    assert {
        item["package"]: item["version"]
        for item in provenance["peerjs_bundled_dependencies"]
    } == {
        "eventemitter3": "4.0.7",
        "peerjs-js-binarypack": "2.1.0",
        "webrtc-adapter": "9.0.1",
        "sdp": "3.2.0",
    }
    assert b"The MIT License" in THIRD_PARTY_BROWSER_LICENSES
    assert b"GNU General Public License" in THIRD_PARTY_BROWSER_LICENSES
    assert b"eventemitter3 4.0.7" in THIRD_PARTY_BROWSER_LICENSES
    assert b"peerjs-js-binarypack 2.1.0" in THIRD_PARTY_BROWSER_LICENSES
    assert b"webrtc-adapter 9.0.1" in THIRD_PARTY_BROWSER_LICENSES
    assert b"sdp 3.2.0" in THIRD_PARTY_BROWSER_LICENSES
    assert b"Version 3, 29 June 2007" in THIRD_PARTY_BROWSER_LICENSES


def test_spectator_server_is_read_only_and_route_isolated():
    server = SpectatorServer(0, advertised_host="127.0.0.1")
    server.start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        assert server.port > 0
        assert server.page_base == base
        with urllib.request.urlopen(base + "/") as response:
            body = response.read().decode()
            csp = response.headers["Content-Security-Policy"]
            assert "Copilot Plays Pokemon Red" in body
            assert "https://0.peerjs.com" in csp
            assert "wss://0.peerjs.com" in csp
            assert "*" not in csp
            assert response.headers["Referrer-Policy"] == "no-referrer"
            assert response.headers["Permissions-Policy"].startswith("camera=()")

        request = urllib.request.Request(base + "/spectator.js", method="HEAD")
        with urllib.request.urlopen(request) as response:
            assert response.status == 200
            assert response.read() == b""

        with urllib.request.urlopen(base + "/vendor/peerjs.min.js") as response:
            assert hashlib.sha256(response.read()).hexdigest() == PEERJS_SHA256
        with urllib.request.urlopen(base + "/vendor/licenses.txt") as response:
            assert b"PeerJS 1.5.5" in response.read()

        for private_path in (
            "/api/status",
            "/api/control",
            "/frame.png",
            "/viewer.js",
            "/vendor/qrious.min.js",
            "/clips/clip-0001-20260711-120000.mp4",
        ):
            with pytest.raises(urllib.error.HTTPError) as missing:
                urllib.request.urlopen(base + private_path)
            assert missing.value.code == 404
            assert missing.value.headers["X-Frame-Options"] == "DENY"

        post = urllib.request.Request(base + "/", data=b"{}", method="POST")
        with pytest.raises(urllib.error.HTTPError) as rejected:
            urllib.request.urlopen(post)
        assert rejected.value.code == 405
        assert rejected.value.headers["Allow"] == "GET, HEAD"

        with socket.create_connection(("127.0.0.1", server.port), timeout=1) as raw:
            raw.sendall(
                b"GET http://[malformed HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nConnection: close\r\n\r\n"
            )
            assert b" 400 " in raw.recv(1024)
    finally:
        server.stop()
    assert server.server is None
    assert server.thread is None
    assert "/api/" not in SPECTATOR_HTML
    assert "/api/" not in SPECTATOR_JS
    assert "data-action" not in SPECTATOR_HTML


def test_spectator_server_bounds_slow_unauthenticated_clients(
    monkeypatch,
):
    monkeypatch.setattr(pokemon_module, "SPECTATOR_MAX_CONNECTIONS", 1)
    monkeypatch.setattr(pokemon_module, "SPECTATOR_SOCKET_TIMEOUT_SECONDS", 0.1)
    server = SpectatorServer(0, advertised_host="127.0.0.1")
    server.start()
    first = socket.create_connection(("127.0.0.1", server.port), timeout=1)
    try:
        assert server.server.max_workers == 1
        first.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Hold:")
        time.sleep(0.03)
        with socket.create_connection(
            ("127.0.0.1", server.port),
            timeout=1,
        ) as excess:
            excess.sendall(
                b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n"
            )
            assert b"503 Service Unavailable" in excess.recv(1024)
        first.settimeout(1)
        assert first.recv(1024) == b""
    finally:
        first.close()
        server.stop()


def test_host_assets_and_livestream_state_remain_authenticated(tmp_path):
    peer_id = "rpp-" + "d" * 32
    capability = "e" * 43
    generation = "generation-" + "f" * 24
    join_url = build_join_url("http://127.0.0.1:43210", peer_id, capability)
    config = {
        "enabled": True,
        "peer_id": peer_id,
        "watch_capability": capability,
        "generation": generation,
        "join_url": join_url,
        "protocol_version": 1,
        "max_hello_bytes": 512,
        "max_viewers": 5,
        "frame_rate": 10,
        "peer_options": {
            "host": "0.peerjs.com",
            "port": 443,
            "path": "/",
            "secure": True,
            "debug": 0,
        },
    }
    controls: queue.Queue[dict[str, object]] = queue.Queue()
    server = ViewerServer(tmp_path, 0, controls, config)
    server.start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        for path in (
            "/api/livestream",
            "/vendor/peerjs.min.js",
            "/vendor/qrious.min.js",
        ):
            with pytest.raises(urllib.error.HTTPError) as forbidden:
                urllib.request.urlopen(base + path)
            assert forbidden.value.code == 403

        opener = authenticated_opener(server)
        with opener.open(base + "/") as response:
            body = response.read().decode()
            csp = response.headers["Content-Security-Policy"]
            assert "/vendor/peerjs.min.js" in body
            assert "/vendor/qrious.min.js" in body
            assert "https://0.peerjs.com" in csp
            assert "wss://0.peerjs.com" in csp
            assert "*" not in csp
        with opener.open(base + "/api/livestream") as response:
            returned_config = json.load(response)
            assert returned_config["join_url"] == join_url
            assert returned_config["peer_options"]["config"] == PEERJS_ICE_CONFIG
        with opener.open(base + "/vendor/qrious.min.js") as response:
            assert hashlib.sha256(response.read()).hexdigest() == QRIOUS_SHA256
        with opener.open(base + "/vendor/qrious.js") as response:
            assert b"QRious v4.0.2" in response.read(200)

        owner = "owner-" + "g" * 24
        lease = post_json(
            opener,
            base,
            "/api/livestream/lease",
            {"action": "acquire", "owner": owner, "generation": generation},
        )
        assert lease["generation"] == generation

        with pytest.raises(urllib.error.HTTPError) as competing:
            post_json(
                opener,
                base,
                "/api/livestream/lease",
                {
                    "action": "acquire",
                    "owner": "owner-" + "h" * 24,
                    "generation": generation,
                },
            )
        assert competing.value.code == 409

        with pytest.raises(urllib.error.HTTPError) as mismatch:
            post_json(
                opener,
                base,
                "/api/livestream/lease",
                {
                    "action": "heartbeat",
                    "owner": owner,
                    "generation": "generation-" + "z" * 24,
                    "lease": lease["lease"],
                },
            )
        assert mismatch.value.code == 409

        state = {
            "state": "live",
            "viewer_count": 2,
            "owner": owner,
            "generation": generation,
            "lease": lease["lease"],
        }
        assert post_json(
            opener,
            base,
            "/api/livestream/state",
            state,
        )["status"] == "success"
        assert json.loads(
            (tmp_path / "livestream-status.json").read_text()
        )["viewer_count"] == 2

        post_json(
            opener,
            base,
            "/api/livestream/lease",
            {
                "action": "release",
                "owner": owner,
                "generation": generation,
                "lease": lease["lease"],
            },
        )
        next_owner = "owner-" + "i" * 24
        next_lease = post_json(
            opener,
            base,
            "/api/livestream/lease",
            {
                "action": "acquire",
                "owner": next_owner,
                "generation": generation,
            },
        )
        with pytest.raises(urllib.error.HTTPError) as stale:
            post_json(opener, base, "/api/livestream/state", state)
        assert stale.value.code == 409

        control_shape = urllib.request.Request(
            base + "/api/livestream/state",
            data=json.dumps(
                {
                    "state": "live",
                    "viewer_count": 2,
                    "owner": next_owner,
                    "generation": generation,
                    "lease": next_lease["lease"],
                    "action": "press",
                }
            ).encode(),
            headers={"Content-Type": "application/json", "Origin": base},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as malformed:
            opener.open(control_shape)
        assert malformed.value.code == 400
        assert controls.empty()
    finally:
        server.stop()


def test_browser_contract_has_explicit_ice_bounded_admission_and_teardown():
    readme = (ROOT / "README.md").read_text()
    security = (ROOT / "SECURITY.md").read_text()
    serialized_ice = json.dumps(PEERJS_ICE_CONFIG).lower()
    assert "stun:stun.l.google.com:19302" in serialized_ice
    assert "turn:" not in serialized_ice
    assert "turns:" not in serialized_ice
    spectator_constructor = SPECTATOR_JS[
        SPECTATOR_JS.index("peer = new Peer(") : SPECTATOR_JS.index(
            "peer.on('open'"
        )
    ].lower()
    assert "config:" in spectator_constructor
    assert "stun:stun.l.google.com:19302" in spectator_constructor
    assert "turn:" not in spectator_constructor
    assert "turns:" not in spectator_constructor
    for documentation in (readme, security):
        assert "stun:stun.l.google.com:19302" in documentation
        assert "no TURN" in documentation
    assert "background tabs" in readme
    assert "10 fps is not guaranteed" in readme

    tracked = VIEWER_JS.index("broadcast.negotiating.set(peerId, entry)")
    opened = VIEWER_JS.index("connection.on('open'", tracked)
    hello_timeout = VIEWER_JS.index("entry.helloTimer = setTimeout", opened)
    assert tracked < opened < hello_timeout
    assert "broadcast.negotiating.size >= maxNegotiating" in VIEWER_JS
    assert f"HARD_MAX_NEGOTIATING = {HARD_MAX_NEGOTIATING}" in (
        ROOT / "pokemon_agent.py"
    ).read_text()
    assert "connection.on('open', () => rejectConnection" not in VIEWER_JS

    assert "window.addEventListener('pagehide', handlePageExit)" in VIEWER_JS
    assert "window.addEventListener('beforeunload', handlePageExit)" in VIEWER_JS
    assert "data.running === false" in VIEWER_JS
    assert "reportedGeneration !== broadcast.config.generation" in VIEWER_JS
    assert "track.addEventListener('ended'" in VIEWER_JS
    assert "peer.destroy()" in VIEWER_JS
    assert "track.stop()" in VIEWER_JS
    assert "releaseLease()" in VIEWER_JS
    assert 'id="stop-runtime"' in VIEWER_HTML

    assert 'id="play-stream" type="button"' in SPECTATOR_HTML
    assert 'role="status"' in SPECTATOR_HTML
    assert "await video.play()" in SPECTATOR_JS
    assert "MAX_AUTOMATIC_RETRIES = 6" in SPECTATOR_JS
    assert "Automatic retries ended. Ask the host for a fresh link." in SPECTATOR_JS


def test_stream_secrets_are_private_and_redacted_from_status(tmp_path):
    peer_id = "rpp-" + "f" * 32
    capability = "g" * 43
    join_url = build_join_url("http://127.0.0.1:43210", peer_id, capability)
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "running": True,
                "pid": os.getpid(),
                "lifecycle": None,
                "port": 12345,
                "livestream": {
                    "enabled": True,
                    "join_url": join_url,
                    "peer_id": peer_id,
                    "watch_capability": capability,
                    "max_viewers": 5,
                },
            }
        )
    )
    (tmp_path / "livestream-auth.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "join_url": join_url,
                "peer_id": peer_id,
                "watch_capability": capability,
            }
        )
    )
    os.chmod(tmp_path / "livestream-auth.json", 0o600)

    serialized = json.dumps(public_runtime_status(tmp_path))

    assert stat.S_IMODE((tmp_path / "livestream-auth.json").stat().st_mode) == 0o600
    assert join_url not in serialized
    assert peer_id not in serialized
    assert capability not in serialized


def test_ephemeral_servers_flow_actual_ports_and_cleanup(tmp_path):
    runner = PokemonRunner.__new__(PokemonRunner)
    runner.runtime_dir = tmp_path
    runner.stream_peer_id = "rpp-" + "1" * 32
    runner.watch_capability = "h" * 43
    runner.stream_generation = "generation-" + "j" * 24
    runner.max_viewers = 5
    runner.livestream_config = {
        "enabled": True,
        "peer_id": runner.stream_peer_id,
        "watch_capability": runner.watch_capability,
        "generation": runner.stream_generation,
        "protocol_version": 1,
        "max_hello_bytes": 512,
        "max_viewers": 5,
        "frame_rate": 10,
        "peer_options": {},
    }
    runner.status = {
        "lifecycle": "ready",
        "livestream": {
            "enabled": True,
            "state": "offline",
            "viewer_count": 0,
            "max_viewers": 5,
            "spectator_port": None,
        },
    }
    runner.spectator = SpectatorServer(0, advertised_host="127.0.0.1")
    runner.viewer = ViewerServer(
        tmp_path,
        0,
        queue.Queue(),
        runner.livestream_config,
    )

    runner._start_web_servers()
    viewer_port = runner.viewer.port
    spectator_port = runner.spectator.port
    assert viewer_port > 0
    assert spectator_port > 0
    assert viewer_port != spectator_port
    assert runner.status["port"] == viewer_port
    assert runner.status["livestream"]["spectator_port"] == spectator_port
    private = json.loads((tmp_path / "livestream-auth.json").read_text())
    assert f":{spectator_port}#" in private["join_url"]
    assert (
        stat.S_IMODE((tmp_path / "livestream-auth.json").stat().st_mode)
        == 0o600
    )

    class Player:
        def release(self, pyboy):
            del pyboy

    class Recorder:
        frames_written = 0
        started_at = None

        def finish(self):
            return None

    runner.stop_event = threading.Event()
    runner.player = Player()
    runner.pyboy = object()
    runner.recorder = Recorder()
    runner._save_checkpoint = lambda *args, **kwargs: None
    runner._stop_brain_worker = lambda: None
    runner._save_ram_and_stop = lambda: None
    runner._enforce_retention = lambda: None
    runner._write_status = lambda: None

    runner._shutdown_runtime("test")

    assert runner.viewer.server is None
    assert runner.spectator.server is None
    assert not (tmp_path / "viewer-auth.json").exists()
    assert not (tmp_path / "livestream-auth.json").exists()
    assert not (tmp_path / "livestream-status.json").exists()


def test_spectator_port_conflict_is_clear():
    blocker = socket.socket()
    blocker.bind(("0.0.0.0", 0))
    blocker.listen()
    port = blocker.getsockname()[1]
    try:
        with pytest.raises(RuntimeError, match="spectator server.*0.0.0.0"):
            SpectatorServer(port, advertised_host="127.0.0.1").start()
    finally:
        blocker.close()


def test_authenticated_viewer_port_conflict_is_clear(tmp_path):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    port = blocker.getsockname()[1]
    try:
        with pytest.raises(RuntimeError, match="authenticated viewer.*127.0.0.1"):
            ViewerServer(tmp_path, port, queue.Queue()).start()
    finally:
        blocker.close()


@pytest.mark.parametrize("server_type", ["viewer", "spectator"])
def test_server_stop_closes_bound_only_server_without_shutdown(
    server_type,
    tmp_path,
):
    class BoundOnly:
        shutdown_called = False
        close_called = False

        def shutdown(self):
            self.shutdown_called = True

        def server_close(self):
            self.close_called = True

    bound = BoundOnly()
    if server_type == "viewer":
        server = ViewerServer(tmp_path, 0, queue.Queue())
    else:
        server = SpectatorServer(0, advertised_host="127.0.0.1")
    server.server = bound
    server.thread = None

    server.stop()

    assert bound.shutdown_called is False
    assert bound.close_called is True
    assert server.server is None


def test_agent_share_is_explicit_and_local(tmp_path, monkeypatch):
    join_url = build_join_url(
        "http://127.0.0.1:45678",
        "rpp-" + "2" * 32,
        "i" * 43,
    )
    (tmp_path / "livestream-auth.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "join_url": join_url,
                "max_viewers": 5,
                "spectator_port": 45678,
            }
        )
    )
    monkeypatch.setattr(
        pokemon_module,
        "runtime_status",
        lambda runtime_dir: {"running": True, "livestream": {"enabled": True}},
    )

    result = json.loads(PokemonAgent().perform(action="share", runtime_dir=tmp_path))

    assert result["status"] == "success"
    assert result["join_url"] == join_url

    monkeypatch.setattr(
        pokemon_module,
        "runtime_status",
        lambda runtime_dir: {"running": True, "livestream": {"enabled": False}},
    )
    disabled = json.loads(
        PokemonAgent().perform(action="share", runtime_dir=tmp_path)
    )
    assert disabled["status"] == "error"
    assert "join_url" not in disabled
