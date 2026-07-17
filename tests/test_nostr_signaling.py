from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import pytest
from openrappter.agents.pokemon_agent import (
    DEFAULT_PAGES_HOST_BASE,
    NOSTR_RELAY_URLS,
    PAIRING_JS,
    RTC_CONFIG,
    SPECTATOR_JS,
    THIRD_PARTY_BROWSER_LICENSES,
    TRYSTERO_NOSTR_COMMIT,
    TRYSTERO_NOSTR_RUNTIME_JS,
    TRYSTERO_NOSTR_RUNTIME_SHA256,
    TRYSTERO_NOSTR_VERSION,
    PokemonRunner,
    build_join_url,
    decode_urlsafe_token,
    derive_host_fingerprint,
)

from rappter_plays_pokemon import cli

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "browser"


def fixed_host_public_key() -> str:
    value = {
        "crv": "P-256",
        "ext": True,
        "key_ops": ["verify"],
        "kty": "EC",
        "x": "TZoJKyIkF2MGUB0oEgsu9pZThxyOBzpjHiAnjVX_k8k",
        "y": "xG9WvTCyfXBbP4J8hovLGTYYYdRf0whrzcKwIjrxWxk",
    }
    return base64.urlsafe_b64encode(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).decode().rstrip("=")


def test_v2_invitation_is_exact_fragment_only_and_generation_bound():
    room = "A" * 22
    key_bytes = bytes([4]) * 32
    key = base64.urlsafe_b64encode(key_bytes).decode().rstrip("=")
    generation = "generation-" + "g" * 24
    public_key = fixed_host_public_key()
    fingerprint = derive_host_fingerprint(public_key, generation)

    url = build_join_url(
        "https://watch.example.test/watch/",
        room,
        key,
        signaling="nostr",
        generation=generation,
        host_fingerprint=fingerprint,
        host_public_key=public_key,
    )
    parsed = urllib.parse.urlsplit(url)

    assert parsed.query == ""
    assert parsed.fragment == (
        f"v=2&room={room}&key={key}&gen={generation}"
        f"&pub={urllib.parse.quote(public_key)}&fp={fingerprint}"
    )
    assert all(
        secret not in url.split("#", 1)[0]
        for secret in (room, key, generation, fingerprint)
    )
    assert decode_urlsafe_token(room, 16, "room") == b"\0" * 16
    assert decode_urlsafe_token(key, 32, "key") == key_bytes
    assert derive_host_fingerprint(
        public_key,
        "generation-abcdefghijklmnopqrstuvwx",
    ) == "4c143f3e55267a85d5f83ae03b385af1"

    with pytest.raises(ValueError, match="HTTPS"):
        build_join_url(
            "http://watch.example.test/",
            room,
            key,
            signaling="nostr",
            generation=generation,
            host_fingerprint=fingerprint,
            host_public_key=public_key,
        )
    with pytest.raises(ValueError, match="fingerprint"):
        build_join_url(
            "https://watch.example.test/",
            room,
            key,
            signaling="nostr",
            generation=generation,
            host_fingerprint="0" * 32,
            host_public_key=public_key,
        )
    with pytest.raises(ValueError, match="room ID"):
        build_join_url(
            "https://watch.example.test/",
            "short",
            key,
            signaling="nostr",
            generation=generation,
            host_fingerprint=fingerprint,
            host_public_key=public_key,
        )


def test_kite_defaults_to_nostr_while_local_defaults_to_legacy_peerjs(tmp_path):
    kite = cli.build_parser().parse_args(
        ["start", "--runtime-dir", str(tmp_path), "--livestream"]
    )
    kite_values = cli.agent_kwargs(kite, {})
    assert kite_values["livestream_host"] == "kite"
    assert kite_values["signaling"] == "nostr"

    local = cli.build_parser().parse_args(
        [
            "start",
            "--runtime-dir",
            str(tmp_path),
            "--livestream",
            "--livestream-host",
            "local",
        ]
    )
    assert cli.agent_kwargs(local, {})["signaling"] == "peerjs"

    rollback = cli.build_parser().parse_args(
        [
            "start",
            "--runtime-dir",
            str(tmp_path),
            "--livestream",
            "--signaling",
            "peerjs",
        ]
    )
    assert cli.agent_kwargs(rollback, {})["signaling"] == "peerjs"
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["start", "--signaling", "https://arbitrary.example"]
        )


def test_runner_generates_independent_exact_entropy_room_and_key(tmp_path):
    rom = tmp_path / "owned.gb"
    rom.write_bytes(bytes(0x200))
    args = SimpleNamespace(
        rom=str(rom),
        runtime_dir=tmp_path / "runtime",
        port=0,
        instance_id="test-instance",
        livestream=True,
        livestream_host="kite",
        signaling="nostr",
        host_base=DEFAULT_PAGES_HOST_BASE,
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

    runner = PokemonRunner(args)

    room = decode_urlsafe_token(runner.stream_room_id, 16, "room")
    key = decode_urlsafe_token(runner.stream_room_key, 32, "key")
    assert len(room) == 16
    assert len(key) == 32
    assert runner.stream_room_id != runner.stream_room_key
    assert runner.host_fingerprint is None
    assert runner.host_public_key is None
    assert decode_urlsafe_token(
        runner.manual_return_token,
        32,
        "manual return token",
    )
    assert runner.stream_peer_id is None
    assert runner.watch_capability is None
    assert runner.livestream_config["relay_urls"] == list(NOSTR_RELAY_URLS)
    assert runner.livestream_config["rtc_config"] == RTC_CONFIG
    assert "turnConfig" not in runner.livestream_config


def test_trystero_bundle_sources_licenses_and_policy_are_exact():
    provenance = json.loads((VENDOR / "PROVENANCE.json").read_text())
    build = json.loads((VENDOR / "TRYSTERO_BUILD.json").read_text())
    policy = json.loads((VENDOR / "NOSTR_RELAYS.json").read_text())
    bundle = VENDOR / "trystero-nostr-0.25.3.iife.min.js"

    assert TRYSTERO_NOSTR_VERSION == "0.25.3"
    assert TRYSTERO_NOSTR_COMMIT == (
        "f76eb4fca528a3253e2bdfd6d41b54c8131ca11e"
    )
    assert bundle.read_bytes() == TRYSTERO_NOSTR_RUNTIME_JS
    assert hashlib.sha256(bundle.read_bytes()).hexdigest() == (
        TRYSTERO_NOSTR_RUNTIME_SHA256
    )
    assert build["runtime_external_imports"] == []
    assert build["output_sha256"] == TRYSTERO_NOSTR_RUNTIME_SHA256
    assert provenance["trystero_bundle"]["sha256"] == (
        TRYSTERO_NOSTR_RUNTIME_SHA256
    )
    assert (
        b"The served Trystero Nostr IIFE is a deterministic self-contained "
        b"bundle with SHA-256 "
        + TRYSTERO_NOSTR_RUNTIME_SHA256.encode("ascii")
        + b".\n"
        in THIRD_PARTY_BROWSER_LICENSES
    )
    assert build["upstream_commit"] == TRYSTERO_NOSTR_COMMIT
    assert not re.search(rb"^\s*import\s", bundle.read_bytes())
    assert b"sourceMappingURL" not in bundle.read_bytes()
    assert len(build["derivatives"]) == 3
    assert b"disposeRelaySockets" in bundle.read_bytes()
    assert b"getRelayHealth" in bundle.read_bytes()
    for derivative in build["derivatives"]:
        path = VENDOR / derivative["file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == (
            derivative["sha256"]
        )
    assert "finally" in (
        VENDOR / "patches/trystero-core-0.25.3-leave-finally.patch"
    ).read_text()

    for item in build["inputs"]:
        archive = VENDOR / item["archive"]
        assert archive.is_file()
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == item["sha256"]
    assert provenance["trystero_bundle"]["version"] == "0.25.3"
    assert {
        item["package"]: item["version"]
        for item in provenance["trystero_bundled_dependencies"]
    } == {
        "@trystero-p2p/core": "0.25.3",
        "@noble/secp256k1": "3.1.0",
    }
    assert tuple(item["origin"] for item in policy["relays"]) == NOSTR_RELAY_URLS
    assert all(item["upstream_default"] for item in policy["relays"])
    assert all(
        "EVENT acceptance/delivery" in item["local_test"]
        for item in policy["relays"]
    )
    assert "two independent" in policy["test_method"]
    assert "no SLA" in policy["service_level"]


def test_nostr_and_manual_contracts_are_direct_stun_only():
    serialized_rtc = json.dumps(RTC_CONFIG).lower()
    assert serialized_rtc == (
        '{"iceservers": [{"urls": "stun:stun.l.google.com:19302"}]}'
    )
    assert "turn:" not in serialized_rtc
    assert "turns:" not in serialized_rtc
    assert "passive: true" in SPECTATOR_JS
    assert "target: peerId" in SPECTATOR_JS
    assert "rtcConfig:" in SPECTATOR_JS
    assert "turnConfig" not in SPECTATOR_JS
    assert "new RTCPeerConnection(config)" in PAIRING_JS
    assert "new WebSocket" not in PAIRING_JS
    assert "fetch(" not in PAIRING_JS
    assert "compression: 'none'" in PAIRING_JS
    assert "new CompressionStream('gzip')" not in PAIRING_JS
    assert "unsupported pairing compression" in PAIRING_JS
    assert "name: 'HKDF'" in PAIRING_JS
    assert "name: 'AES-GCM'" in PAIRING_JS
    assert "relay ICE candidates are not permitted" in PAIRING_JS
    assert "signHostTranscript" in PAIRING_JS
    assert "verifyHostTranscript" in PAIRING_JS
