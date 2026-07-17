from __future__ import annotations

import hashlib
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
    PEERJS_RUNTIME_JS,
    PEERJS_RUNTIME_SHA256,
    PEERJS_SHA256,
    PEERJS_VERSION,
    QRIOUS_RUNTIME_JS,
    SPECTATOR_CSS,
    SPECTATOR_HTML,
    SPECTATOR_JS,
    THIRD_PARTY_BROWSER_LICENSES,
    build_join_url,
    validate_external_join_base,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
WATCH = DOCS / "watch"
HOST = DOCS / "host"
BUILDER = ROOT / "scripts" / "build_pages_site.py"
PAGES_JOIN_BASE = "https://kody-w.github.io/rappter-plays-pokemon/watch/"
PAGES_CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; "
    "media-src blob:; connect-src https://0.peerjs.com wss://0.peerjs.com; "
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


def generated_files() -> dict[Path, bytes]:
    return {
        Path("index.html"): SPECTATOR_HTML.encode(),
        Path("spectator.css"): SPECTATOR_CSS.encode(),
        Path("spectator.js"): SPECTATOR_JS.encode(),
        Path("vendor/peerjs.min.js"): PEERJS_RUNTIME_JS,
        Path("vendor/licenses.txt"): THIRD_PARTY_BROWSER_LICENSES,
    }


def generated_host_files() -> dict[Path, bytes]:
    return {
        Path("index.html"): HOST_HTML.encode(),
        Path("host.css"): HOST_CSS.encode(),
        Path("host.js"): HOST_JS.encode(),
        Path("vendor/peerjs.min.js"): PEERJS_RUNTIME_JS,
        Path("vendor/qrious.min.js"): QRIOUS_RUNTIME_JS,
        Path("vendor/licenses.txt"): THIRD_PARTY_BROWSER_LICENSES,
    }


def test_pages_build_exactly_matches_canonical_sources_and_is_checked_in():
    expected = generated_files()
    builder = runpy.run_path(str(BUILDER))

    assert builder["canonical_files"]() == expected
    assert {
        path.relative_to(WATCH)
        for path in WATCH.rglob("*")
        if path.is_file()
    } == set(expected)
    for relative_path, payload in expected.items():
        path = WATCH / relative_path
        assert path.read_bytes() == payload
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
    expected_host = generated_host_files()
    assert builder["canonical_host_files"]() == expected_host
    assert {
        path.relative_to(HOST)
        for path in HOST.rglob("*")
        if path.is_file()
    } == set(expected_host)
    for relative_path, payload in expected_host.items():
        path = HOST / relative_path
        assert path.read_bytes() == payload
        assert stat.S_IMODE(path.stat().st_mode) == 0o644

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
        "connect-src": ["https://0.peerjs.com", "wss://0.peerjs.com"],
        "base-uri": ["'none'"],
        "form-action": ["'none'"],
        "object-src": ["'none'"],
    }
    assert {link["href"] for link in parser.attributes("link")} == {
        "./spectator.css"
    }
    assert {script["src"] for script in parser.attributes("script")} == {
        "./vendor/peerjs.min.js",
        "./spectator.js",
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
    ) == "rpp-kite-host-v1"
    assert {script["src"] for script in parser.attributes("script")} == {
        "./vendor/peerjs.min.js",
        "./vendor/qrious.min.js",
        "./host.js",
    }
    assert {link["href"] for link in parser.attributes("link")} == {
        "./host.css"
    }
    assert "window.__RPP_KITE_HOST_V1__" not in HOST_JS
    assert "'__RPP_KITE_HOST_V1__'" in HOST_JS
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
        "token",
        "rom_path",
        "/status",
        "document.cookie",
        "localstorage",
        "sessionstorage",
        "serviceworker",
        "analytics",
        "data-action",
        "go live",
        "manual mode",
        "return to autonomy",
    ):
        assert forbidden not in first_party
    assert "fetch(" not in SPECTATOR_JS
    assert SPECTATOR_JS.count("dataConnection.send(") == 1
    assert "type: 'watch'" in SPECTATOR_JS
    assert "127.0.0.1" not in first_party
    assert "192.168." not in first_party
    assert "localhost" not in first_party


def test_pages_peerjs_pin_notices_and_fragment_only_join_contract():
    peerjs = (WATCH / "vendor" / "peerjs.min.js").read_bytes()
    host_qrious = (HOST / "vendor" / "qrious.min.js").read_bytes()
    notices = (WATCH / "vendor" / "licenses.txt").read_bytes()
    assert PEERJS_VERSION == "1.5.5"
    assert PEERJS_SHA256 == (
        "7604d8c31bec4f134b0d15c2d80b1d095ea18af005354f439f14291fcd7b4168"
    )
    assert hashlib.sha256(peerjs).hexdigest() == PEERJS_RUNTIME_SHA256
    assert b"sourceMappingURL" not in peerjs
    assert host_qrious == QRIOUS_RUNTIME_JS
    assert b"sourceMappingURL" not in host_qrious
    assert notices == THIRD_PARTY_BROWSER_LICENSES
    for notice in (
        b"PeerJS 1.5.5",
        b"MIT License",
        b"eventemitter3 4.0.7",
        b"peerjs-js-binarypack 2.1.0",
        b"webrtc-adapter 9.0.1",
        b"sdp 3.2.0",
    ):
        assert notice in notices

    host = "rpp-" + "h" * 32
    capability = "w" * 43
    assert validate_external_join_base(PAGES_JOIN_BASE) == PAGES_JOIN_BASE
    join_url = build_join_url(PAGES_JOIN_BASE, host, capability)
    parsed = urllib.parse.urlsplit(join_url)
    assert join_url.split("#", 1)[0] == PAGES_JOIN_BASE
    assert parsed.path == "/rappter-plays-pokemon/watch/"
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
    assert SPECTATOR_HTML.count('aria-live="polite"') == 2


def test_pages_landing_is_static_and_does_not_claim_an_invitation():
    landing = (DOCS / "index.html").read_text(encoding="utf-8")
    parser = ParsedHTML()
    parser.feed(landing)

    assert "No livestream invitation is embedded on this page." in landing
    assert "ask the host" in landing
    assert not parser.attributes("script")
    assert not any(
        meta.get("http-equiv", "").lower() == "refresh"
        for meta in parser.attributes("meta")
    )
    links = {anchor["href"] for anchor in parser.attributes("a")}
    assert all(link.startswith("https://github.com/") for link in links)
    assert any(link.endswith("#browser-livestream") for link in links)
