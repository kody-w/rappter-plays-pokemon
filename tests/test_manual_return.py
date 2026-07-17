from __future__ import annotations

import base64
import http.client
import json
import os
import queue
import stat
import time
from types import SimpleNamespace

import pytest
from openrappter.agents.pokemon_agent import (
    KITE_STRING_SCHEMA_VERSION,
    MAX_MANUAL_RETURN_REQUEST_BYTES,
    PAIR_RETURN_JS,
    KiteBroadcaster,
    PokemonRunner,
    ViewerServer,
    derive_host_fingerprint,
    validate_host_identity,
)


def request_json(
    server: ViewerServer,
    value: dict[str, object],
    *,
    host: str | None = None,
    origin: str | None = None,
) -> tuple[int, dict[str, object]]:
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=2)
    body = json.dumps(value).encode()
    connection.request(
        "POST",
        "/api/kite/manual-answer",
        body=body,
        headers={
            "Host": host or f"127.0.0.1:{server.port}",
            "Origin": origin or f"http://127.0.0.1:{server.port}",
            "Content-Type": "application/json",
        },
    )
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    return response.status, payload


def test_generation_host_identity_is_private_persistent_and_rotates(tmp_path):
    os.chmod(tmp_path, 0o700)
    first_generation = "generation-" + "a" * 24
    second_generation = "generation-" + "b" * 24

    first = KiteBroadcaster.initialize_identity(tmp_path, first_generation)
    repeated = KiteBroadcaster.initialize_identity(tmp_path, first_generation)
    identity_path = tmp_path / KiteBroadcaster.IDENTITY_FILE

    assert first == repeated
    assert validate_host_identity(first, first_generation)
    assert stat.S_IMODE(identity_path.stat().st_mode) == 0o600
    assert first["host_private_jwk"]["d"] not in first["host_public_key"]
    assert first["fingerprint"] == derive_host_fingerprint(
        first["host_public_key"],
        first_generation,
    )

    rotated = KiteBroadcaster.initialize_identity(tmp_path, second_generation)
    assert validate_host_identity(rotated, second_generation)
    assert rotated["host_public_key"] != first["host_public_key"]
    assert rotated["host_private_jwk"]["d"] != first["host_private_jwk"]["d"]


def test_loopback_manual_answer_endpoint_is_strict_atomic_and_replay_safe(
    tmp_path,
):
    generation = "generation-" + "g" * 24
    token = base64.urlsafe_b64encode(bytes([13]) * 32).decode().rstrip("=")
    controls: queue.Queue[dict[str, object]] = queue.Queue()
    server = ViewerServer(
        tmp_path,
        0,
        controls,
        manual_return={"generation": generation, "token": token},
    )
    server.start()
    answer = "rpp-answer-v2." + "e" * 120
    deliver = {
        "action": "deliver",
        "generation": generation,
        "token": token,
        "answer": answer,
    }
    try:
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            server.port,
            timeout=2,
        )
        connection.request(
            "GET",
            "/pair-return",
            headers={"Host": f"127.0.0.1:{server.port}"},
        )
        response = connection.getresponse()
        assert response.status == 200
        assert b"fragment-only answer" in response.read()
        connection.close()

        status, queued = request_json(server, deliver)
        assert status == 202
        assert queued == {"status": "queued", "sequence": 1}
        queue_dir = tmp_path / KiteBroadcaster.MANUAL_RETURN_DIRECTORY
        queued_path = queue_dir / "answer-000000000001.json"
        queued_value = json.loads(queued_path.read_text())
        assert queued_value == {
            "schema_version": KITE_STRING_SCHEMA_VERSION,
            "generation": generation,
            "sequence": 1,
            "answer": answer,
            "received_at": queued_value["received_at"],
        }
        assert stat.S_IMODE(queue_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(queued_path.stat().st_mode) == 0o600
        assert not list(queue_dir.glob("*.tmp"))
        assert controls.empty()

        replay_status, _ = request_json(server, deliver)
        assert replay_status == 409

        queued_status, queued_result = request_json(
            server,
            {
                "action": "status",
                "generation": generation,
                "token": token,
                "sequence": 1,
            },
        )
        assert queued_status == 200
        assert queued_result == {"status": "queued", "sequence": 1}

        (queue_dir / "status-000000000001.json").write_text(
            json.dumps(
                {
                    "schema_version": KITE_STRING_SCHEMA_VERSION,
                    "generation": generation,
                    "sequence": 1,
                    "status": "delivered",
                    "reason": "accepted",
                    "updated_at": queued_value["received_at"],
                }
            )
        )
        delivered_status, delivered_result = request_json(
            server,
            {
                "action": "status",
                "generation": generation,
                "token": token,
                "sequence": 1,
            },
        )
        assert delivered_status == 200
        assert delivered_result == {"status": "delivered", "sequence": 1}
        assert "Delivered to the dedicated streamer host." in PAIR_RETURN_JS
        assert "/api/kite/manual-answer" in PAIR_RETURN_JS

        wrong_token, _ = request_json(server, {**deliver, "token": "x" * 43})
        wrong_generation, _ = request_json(
            server,
            {**deliver, "generation": "generation-" + "x" * 24},
        )
        wrong_origin, _ = request_json(
            server,
            deliver,
            origin="http://localhost:1",
        )
        wrong_host, _ = request_json(
            server,
            deliver,
            host=f"localhost:{server.port}",
        )
        assert {
            wrong_token,
            wrong_generation,
            wrong_origin,
            wrong_host,
        } == {403}

        connection = http.client.HTTPConnection(
            "127.0.0.1",
            server.port,
            timeout=2,
        )
        connection.putrequest(
            "POST",
            "/api/kite/manual-answer",
            skip_host=True,
        )
        connection.putheader("Host", f"127.0.0.1:{server.port}")
        connection.putheader("Origin", f"http://127.0.0.1:{server.port}")
        connection.putheader("Content-Type", "application/json")
        connection.putheader(
            "Content-Length",
            str(MAX_MANUAL_RETURN_REQUEST_BYTES + 1),
        )
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 413
        response.read()
        connection.close()

        server.manual_return_attempts.clear()
        server.manual_return_attempts.extend([time.monotonic()] * 120)
        limited, _ = request_json(
            server,
            {**deliver, "answer": answer + "new"},
        )
        assert limited == 429
    finally:
        server.stop()

    assert not (tmp_path / KiteBroadcaster.MANUAL_RETURN_DIRECTORY).exists()
    assert server.manual_return == {}


@pytest.mark.parametrize(
    "host_base",
    (
        "https://example.test/host/v2",
        "https://example.test/host/v2/",
    ),
)
def test_new_kited_runner_issues_v2_public_identity_and_exact_callback(
    tmp_path,
    host_base,
):
    rom = tmp_path / "owned.gb"
    rom.write_bytes(bytes(0x200))
    runtime = tmp_path / "runtime"
    runner = PokemonRunner(
        SimpleNamespace(
            rom=str(rom),
            runtime_dir=runtime,
            port=0,
            instance_id="manual-return-runner",
            livestream=True,
            livestream_host="kite",
            signaling="nostr",
            host_base=host_base,
            browser_path="",
            bridge_startup_timeout=20,
            max_viewers=5,
            spectator_port=0,
            advertised_host=None,
            join_base=None,
            model="test",
            max_clips=2,
            max_states=2,
            max_storage_gb=1,
            min_free_gb=0,
        )
    )

    runner._start_web_servers()
    try:
        bootstrap = json.loads((runtime / "kite-bootstrap.json").read_text())
        identity = json.loads((runtime / "kite-host-identity.json").read_text())
        private = json.loads((runtime / "livestream-auth.json").read_text())

        assert bootstrap["schema_version"] == KITE_STRING_SCHEMA_VERSION
        assert bootstrap["host_base"] == "https://example.test/host/v2/"
        assert bootstrap["join_url"].split("#", 1)[0].endswith("/watch/v2/")
        assert "&pub=" in bootstrap["join_url"]
        assert "manual_return_token" not in bootstrap["join_url"]
        assert "manual_callback" not in bootstrap["join_url"]
        assert "host_private_jwk" not in bootstrap
        assert bootstrap["host_public_key"] == identity["host_public_key"]
        assert bootstrap["host_fingerprint"] == identity["fingerprint"]
        assert bootstrap["manual_callback"] == {
            "origin": f"http://127.0.0.1:{runner.viewer.port}",
            "path": "/pair-return",
        }
        assert (
            bootstrap["manual_return_page"]
            == "https://example.test/host/v2/return/"
        )
        assert private["host_public_key"] == identity["host_public_key"]
        assert "host_private_jwk" not in private
    finally:
        runner.viewer.stop()
