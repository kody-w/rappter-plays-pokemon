from __future__ import annotations

import base64
import hashlib
import json
import runpy
import stat
import subprocess
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

from openrappter.agents.pokemon_agent import (
    HOST_CSS,
    HOST_HTML,
    HOST_JS,
    NOSTR_RELAY_URLS,
    PAIRING_JS,
    PEERJS_RUNTIME_JS,
    PEERJS_RUNTIME_SHA256,
    PEERJS_SHA256,
    PEERJS_VERSION,
    QRIOUS_RUNTIME_JS,
    SPECTATOR_CSS,
    SPECTATOR_HTML,
    SPECTATOR_JS,
    THIRD_PARTY_BROWSER_LICENSES,
    TRYSTERO_NOSTR_RUNTIME_JS,
    TRYSTERO_NOSTR_RUNTIME_SHA256,
    build_join_url,
    derive_host_fingerprint,
    validate_external_join_base,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
WATCH = DOCS / "watch"
HOST = DOCS / "host"
WATCH_V2 = WATCH / "v2"
HOST_V2 = HOST / "v2"
BUILDER = ROOT / "scripts" / "build_pages_site.py"
PAGES_JOIN_BASE = "https://kody-w.github.io/rappter-plays-pokemon/watch/v2/"
PAGES_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "media-src blob:; connect-src https://0.peerjs.com wss://0.peerjs.com "
    + " ".join(NOSTR_RELAY_URLS)
    + "; "
    "base-uri 'none'; form-action 'none'; object-src 'none'"
)


class ParsedHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.tags.append(
            (
                tag,
                {
                    name: value if value is not None else ""
                    for name, value in attrs
                },
            )
        )

    def attributes(self, tag: str) -> list[dict[str, str]]:
        return [attributes for name, attributes in self.tags if name == tag]


def generated_v2_files() -> dict[Path, bytes]:
    return {
        Path("index.html"): SPECTATOR_HTML.encode(),
        Path("spectator.rpp-v2.css"): SPECTATOR_CSS.encode(),
        Path("spectator.rpp-v2.js"): SPECTATOR_JS.encode(),
        Path("pairing.rpp-v2.js"): PAIRING_JS.encode(),
        Path("vendor/peerjs-1.5.5.runtime.min.js"): PEERJS_RUNTIME_JS,
        Path(
            "vendor/trystero-nostr-0.25.3-rpp1.min.js"
        ): TRYSTERO_NOSTR_RUNTIME_JS,
        Path("vendor/qrious-4.0.2.runtime.min.js"): QRIOUS_RUNTIME_JS,
        Path("vendor/licenses.txt"): THIRD_PARTY_BROWSER_LICENSES,
    }


def generated_v2_host_files() -> dict[Path, bytes]:
    return {
        Path("index.html"): HOST_HTML.encode(),
        Path("host.rpp-kite-v2.css"): HOST_CSS.encode(),
        Path("host.rpp-kite-v2.js"): HOST_JS.encode(),
        Path("pairing.rpp-v2.js"): PAIRING_JS.encode(),
        Path("vendor/peerjs-1.5.5.runtime.min.js"): PEERJS_RUNTIME_JS,
        Path(
            "vendor/trystero-nostr-0.25.3-rpp1.min.js"
        ): TRYSTERO_NOSTR_RUNTIME_JS,
        Path("vendor/qrious-4.0.2.runtime.min.js"): QRIOUS_RUNTIME_JS,
        Path("vendor/licenses.txt"): THIRD_PARTY_BROWSER_LICENSES,
    }


def test_pages_build_exactly_matches_canonical_sources_and_is_checked_in():
    builder = runpy.run_path(str(BUILDER))
    expected = builder["canonical_files"]()
    assert {
        path.relative_to(WATCH)
        for path in WATCH.rglob("*")
        if path.is_file()
    } == set(expected)
    for relative_path, payload in expected.items():
        path = WATCH / relative_path
        assert path.read_bytes() == payload
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
    expected_host = builder["canonical_host_files"]()
    assert {
        path.relative_to(HOST)
        for path in HOST.rglob("*")
        if path.is_file()
    } == set(expected_host)
    for relative_path, payload in expected_host.items():
        path = HOST / relative_path
        assert path.read_bytes() == payload
        assert stat.S_IMODE(path.stat().st_mode) == 0o644

    for relative_path, payload in generated_v2_files().items():
        assert (WATCH_V2 / relative_path).read_bytes() == payload
    for relative_path, payload in generated_v2_host_files().items():
        assert (HOST_V2 / relative_path).read_bytes() == payload

    manifest = json.loads(
        (ROOT / "vendor/browser/PAGES_V1.json").read_text()
    )
    for item in manifest["files"]:
        target = DOCS / item["target"]
        assert hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"]

    check = subprocess.run(
        [sys.executable, str(BUILDER), "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert check.returncode == 0, check.stderr or check.stdout
    assert "in sync" in check.stdout
    assert (DOCS / ".nojekyll").read_bytes() == b""


def test_pages_builder_rebuilds_deterministically_and_reports_drift(
    tmp_path,
    monkeypatch,
    capsys,
):
    builder = runpy.run_path(str(BUILDER))
    expected = builder["canonical_files"]()
    site = tmp_path / "watch"
    globals_ = builder["main"].__globals__
    monkeypatch.setitem(globals_, "WATCH", site)

    builder["write_site"](expected)
    first = {
        path.relative_to(site): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in site.rglob("*")
        if path.is_file()
    }
    builder["write_site"](expected)
    second = {
        path.relative_to(site): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        for path in site.rglob("*")
        if path.is_file()
    }
    assert first == second
    assert builder["drift"](expected) == []

    (site / "spectator.js").write_text("manual drift", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(BUILDER), "--check"])
    assert builder["main"]() == 1
    assert "content differs: " in capsys.readouterr().err


def test_pages_spectator_uses_relative_assets_and_strict_meta_csp():
    parser = ParsedHTML()
    parser.feed(SPECTATOR_HTML)

    metas = parser.attributes("meta")
    csp = next(
        meta["content"]
        for meta in metas
        if meta.get("http-equiv") == "Content-Security-Policy"
    )
    assert csp == PAGES_CSP
    assert "frame-ancestors" not in csp
    assert next(meta["content"] for meta in metas if meta.get("name") == "referrer") == (
        "no-referrer"
    )

    directives = {
        fields[0]: fields[1:]
        for fields in (directive.split() for directive in csp.split("; "))
    }
    assert directives == {
        "default-src": ["'none'"],
        "script-src": ["'self'"],
        "style-src": ["'self'"],
        "media-src": ["blob:"],
        "connect-src": [
            "https://0.peerjs.com",
            "wss://0.peerjs.com",
            *NOSTR_RELAY_URLS,
        ],
        "base-uri": ["'none'"],
        "form-action": ["'none'"],
        "object-src": ["'none'"],
    }
    assert {link["href"] for link in parser.attributes("link")} == {
        "./spectator.rpp-v2.css"
    }
    assert {script["src"] for script in parser.attributes("script")} == {
        "./vendor/trystero-nostr-0.25.3-rpp1.min.js",
        "./vendor/qrious-4.0.2.runtime.min.js",
        "./pairing.rpp-v2.js",
        "./spectator.rpp-v2.js",
    }
    assert {
        anchor["href"]
        for anchor in parser.attributes("a")
        if "href" in anchor
    } == {"./vendor/licenses.txt"}


def test_pages_host_is_inert_versioned_and_uses_only_pinned_assets():
    parser = ParsedHTML()
    parser.feed(HOST_HTML)
    metas = parser.attributes("meta")
    csp = next(
        meta["content"]
        for meta in metas
        if meta.get("http-equiv") == "Content-Security-Policy"
    )
    assert csp == PAGES_CSP
    assert next(
        meta["content"]
        for meta in metas
        if meta.get("name") == "rpp-kite-host-build"
    ) == "rpp-kite-host-v2"
    assert {script["src"] for script in parser.attributes("script")} == {
        "./vendor/trystero-nostr-0.25.3-rpp1.min.js",
        "./vendor/qrious-4.0.2.runtime.min.js",
        "./pairing.rpp-v2.js",
        "./host.rpp-kite-v2.js",
    }
    assert {link["href"] for link in parser.attributes("link")} == {
        "./host.rpp-kite-v2.css"
    }
    assert "window.__RPP_KITE_HOST_V2__" not in HOST_JS
    assert "'__RPP_KITE_HOST_V2__'" in HOST_JS
    assert "new Peer(" in HOST_JS
    assert HOST_JS.index("function bootstrap(") < HOST_JS.index("new Peer(")
    assert "fetch(" not in HOST_JS
    assert "XMLHttpRequest" not in HOST_JS
    assert "WebSocket" not in HOST_JS
    assert "localhost" not in HOST_JS.lower()
    assert "127.0.0.1" not in HOST_JS
    assert "serviceWorker" not in HOST_JS
    assert "localStorage" not in HOST_JS
    assert "sessionStorage" not in HOST_JS
    assert "data-action" not in HOST_HTML
    for gameplay in ("Take Over", "Return to AI", "Pause", "Resume", "press"):
        assert gameplay not in HOST_HTML
    for stream_control in (
        "Go Live",
        "End",
        "Retry",
        "Picture in Picture",
        "Copy spectator link",
    ):
        assert stream_control in HOST_HTML


def test_pages_spectator_has_no_private_or_privileged_surface():
    first_party = f"{SPECTATOR_HTML}\n{SPECTATOR_JS}".lower()
    for forbidden in (
        "/api/",
        "frame.png",
        "status.json",
        "viewer-auth",
        "livestream-auth",
        "rom_path",
        "/status",
        "document.cookie",
        "localstorage",
        "sessionstorage",
        "serviceworker",
        "analytics",
        "data-action",
        "go live",
        "return to autonomy",
    ):
        assert forbidden not in first_party
    assert "fetch(" not in SPECTATOR_JS
    assert SPECTATOR_JS.count("dataConnection.send(") == 1
    assert "type: 'watch'" in SPECTATOR_JS
    assert "127.0.0.1" not in first_party
    assert "192.168." not in first_party
    assert "localhost" not in first_party


def test_pages_signaling_pins_notices_and_fragment_only_join_contract():
    peerjs = (
        WATCH_V2 / "vendor" / "peerjs-1.5.5.runtime.min.js"
    ).read_bytes()
    host_qrious = (
        HOST_V2 / "vendor" / "qrious-4.0.2.runtime.min.js"
    ).read_bytes()
    trystero = (
        WATCH_V2 / "vendor" / "trystero-nostr-0.25.3-rpp1.min.js"
    ).read_bytes()
    notices = (WATCH_V2 / "vendor" / "licenses.txt").read_bytes()
    assert PEERJS_VERSION == "1.5.5"
    assert PEERJS_SHA256 == (
        "7604d8c31bec4f134b0d15c2d80b1d095ea18af005354f439f14291fcd7b4168"
    )
    assert hashlib.sha256(peerjs).hexdigest() == PEERJS_RUNTIME_SHA256
    assert b"sourceMappingURL" not in peerjs
    assert host_qrious == QRIOUS_RUNTIME_JS
    assert b"sourceMappingURL" not in host_qrious
    assert hashlib.sha256(trystero).hexdigest() == TRYSTERO_NOSTR_RUNTIME_SHA256
    assert notices == THIRD_PARTY_BROWSER_LICENSES
    for notice in (
        b"PeerJS 1.5.5",
        b"MIT License",
        b"eventemitter3 4.0.7",
        b"peerjs-js-binarypack 2.1.0",
        b"webrtc-adapter 9.0.1",
        b"sdp 3.2.0",
        b"@trystero-p2p/nostr 0.25.3",
        b"@noble/secp256k1 3.1.0",
    ):
        assert notice in notices

    host = "rpp-" + "h" * 32
    capability = "w" * 43
    assert validate_external_join_base(PAGES_JOIN_BASE) == PAGES_JOIN_BASE
    join_url = build_join_url(PAGES_JOIN_BASE, host, capability)
    parsed = urllib.parse.urlsplit(join_url)
    assert join_url.split("#", 1)[0] == PAGES_JOIN_BASE
    assert parsed.path == "/rappter-plays-pokemon/watch/v2/"
    assert parsed.query == ""
    assert urllib.parse.parse_qs(parsed.fragment) == {
        "v": ["1"],
        "host": [host],
        "watch": [capability],
    }
    assert host not in join_url.split("#", 1)[0]
    assert capability not in join_url.split("#", 1)[0]
    assert "new URLSearchParams(location.hash.slice(1))" in SPECTATOR_JS
    assert "location.search" not in SPECTATOR_JS
    assert "document.referrer" not in SPECTATOR_JS

    room = "A" * 22
    key = "A" * 43
    generation = "generation-" + "g" * 24
    public_jwk = {
        "crv": "P-256",
        "ext": True,
        "key_ops": ["verify"],
        "kty": "EC",
        "x": "TZoJKyIkF2MGUB0oEgsu9pZThxyOBzpjHiAnjVX_k8k",
        "y": "xG9WvTCyfXBbP4J8hovLGTYYYdRf0whrzcKwIjrxWxk",
    }
    host_public_key = base64.urlsafe_b64encode(
        json.dumps(
            public_jwk,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).decode().rstrip("=")
    fingerprint = derive_host_fingerprint(host_public_key, generation)
    v2_url = build_join_url(
        PAGES_JOIN_BASE,
        room,
        key,
        signaling="nostr",
        generation=generation,
        host_fingerprint=fingerprint,
        host_public_key=host_public_key,
    )
    parsed_v2 = urllib.parse.urlsplit(v2_url)
    assert parsed_v2.query == ""
    assert urllib.parse.parse_qs(parsed_v2.fragment) == {
        "v": ["2"],
        "room": [room],
        "key": [key],
        "gen": [generation],
        "pub": [host_public_key],
        "fp": [fingerprint],
    }
    assert key not in v2_url.split("#", 1)[0]


def test_pages_dashboard_is_semantic_responsive_and_status_only():
    parser = ParsedHTML()
    parser.feed(SPECTATOR_HTML)

    assert parser.attributes("aside")
    assert len(
        [
            attributes
            for attributes in parser.attributes("li")
            if "data-badge" in attributes
        ]
    ) == 8
    assert all(
        heading in SPECTATOR_HTML
        for heading in (
            "Now Playing",
            "Run Progress",
            "Current Party",
            "Run Details",
            "Stream Health",
        )
    )
    assert "@media (max-width: 480px)" in SPECTATOR_CSS
    assert "@media (prefers-reduced-motion: reduce)" in SPECTATOR_CSS
    assert "@media (forced-colors: active)" in SPECTATOR_CSS
    assert "min-width: 320px" in SPECTATOR_CSS
    assert "innerHTML" not in SPECTATOR_JS
    assert "Caught / owned" in SPECTATOR_HTML
    assert 'id="badge-count">— / 8 badges' in SPECTATOR_HTML
    assert 'id="completion">Unknown' in SPECTATOR_HTML
    assert SPECTATOR_HTML.count('aria-live="polite"') == 3


def test_pages_landing_features_public_stream_and_story_without_inline_code():
    landing = (DOCS / "index.html").read_text(encoding="utf-8")
    parser = ParsedHTML()
    parser.feed(landing)

    assert not parser.attributes("script")
    assert not any(
        meta.get("http-equiv", "").lower() == "refresh"
        for meta in parser.attributes("meta")
    )
    csp = next(
        meta["content"]
        for meta in parser.attributes("meta")
        if meta.get("http-equiv") == "Content-Security-Policy"
    )
    assert csp == (
        "default-src 'none'; base-uri 'none'; form-action 'none'; "
        "object-src 'none'; style-src 'self'; "
        "frame-src https://www.youtube-nocookie.com; img-src 'self'; "
        "connect-src 'none'; script-src 'none'"
    )
    links = {anchor["href"] for anchor in parser.attributes("a")}
    assert "https://www.youtube.com/watch?v=NBSKt_dou6o" in links
    assert "./story/" in links
    assert {link["href"] for link in parser.attributes("link")} >= {
        "./site.css"
    }
    assert {frame["src"] for frame in parser.attributes("iframe")} == {
        "https://www.youtube-nocookie.com/embed/NBSKt_dou6o"
    }
    assert (DOCS / "site.css").is_file()


def test_pages_story_player_has_a_strict_public_data_boundary():
    story_dir = DOCS / "story"
    html = (story_dir / "index.html").read_text(encoding="utf-8")
    css = (story_dir / "story.css").read_text(encoding="utf-8")
    javascript = (story_dir / "story.js").read_text(encoding="utf-8")
    parser = ParsedHTML()
    parser.feed(html)

    csp = next(
        meta["content"]
        for meta in parser.attributes("meta")
        if meta.get("http-equiv") == "Content-Security-Policy"
    )
    assert csp == (
        "default-src 'none'; base-uri 'none'; form-action 'none'; "
        "object-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src https://raw.githubusercontent.com; "
        "frame-src https://www.youtube-nocookie.com"
    )
    assert {script["src"] for script in parser.attributes("script")} == {
        "./story.js"
    }
    assert {link["href"] for link in parser.attributes("link")} >= {
        "./story.css"
    }
    assert (
        "https://raw.githubusercontent.com/kody-w/rappter-plays-pokemon/"
        "refs/heads/story-archive/v1/story.json"
    ) in javascript
    for forbidden in (
        "innerHTML",
        "eval(",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "serviceWorker",
        "127.0.0.1",
        "localhost",
        "/api/",
        "rom_path",
        "screen_text",
        "raw_manifest",
    ):
        assert forbidden not in javascript
    assert "textContent" in javascript
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (forced-colors: active)" in css
    assert "min-width: 320px" in css


def test_pages_qr_destination_is_project_first_and_fragment_only():
    diagnostics_dir = DOCS / "d"
    html = (diagnostics_dir / "index.html").read_text(encoding="utf-8")
    css = (diagnostics_dir / "diagnostics.css").read_text(encoding="utf-8")
    javascript = (diagnostics_dir / "diagnostics.js").read_text(encoding="utf-8")
    parser = ParsedHTML()
    parser.feed(html)

    csp = next(
        meta["content"]
        for meta in parser.attributes("meta")
        if meta.get("http-equiv") == "Content-Security-Policy"
    )
    assert csp == (
        "default-src 'none'; base-uri 'none'; form-action 'none'; "
        "object-src 'none'; script-src 'self'; style-src 'self'"
    )
    assert {script["src"] for script in parser.attributes("script")} == {
        "./diagnostics.js"
    }
    assert "Meet the agent playing Pokémon Red." in html
    assert html.index("How the autonomous run works") < html.index(
        "Optional technical snapshot"
    )
    links = {anchor["href"] for anchor in parser.attributes("a")}
    assert "../" in links
    assert "../story/" in links
    assert "https://github.com/kody-w/rappter-plays-pokemon" in links
    assert (
        "https://github.com/kody-w/rappter-plays-pokemon/issues/new"
        in links
    )
    assert "location.hash" in javascript
    assert "buildIssueUrl" in javascript
    assert "NBSKt_dou6o" in javascript
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "innerHTML",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "serviceWorker",
    ):
        assert forbidden not in javascript
    assert "textContent" in javascript
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (forced-colors: active)" in css


def test_v1_rollback_and_v2_return_trees_are_cache_isolated():
    old_host = (HOST / "index.html").read_text()
    old_watch = (WATCH / "index.html").read_text()
    old_host_js = (HOST / "host.js").read_text()
    new_host = (HOST_V2 / "index.html").read_text()
    new_watch = (WATCH_V2 / "index.html").read_text()
    return_html = (HOST_V2 / "return/index.html").read_text()
    return_js = (HOST_V2 / "return/return.rpp-v2.js").read_text()

    assert 'content="rpp-kite-host-v1"' in old_host
    assert "'__RPP_KITE_HOST_V1__'" in old_host_js
    assert "trystero" not in old_host
    assert "pairing" not in old_watch
    assert 'content="rpp-kite-host-v2"' in new_host
    assert "host.rpp-kite-v2.js" in new_host
    assert "spectator.rpp-v2.js" in new_watch
    assert "host.js" not in new_host
    assert "spectator.js" not in new_watch
    assert "fetch(" not in return_js
    assert "XMLHttpRequest" not in return_js
    assert "top-level handoff" in return_html
    assert "scan the answer on host" not in (
        new_host + new_watch
    ).lower()
