#!/usr/bin/env python3
"""Build the checked-in GitHub Pages spectator site without importing the agent.

Canonical direction:

* ``vendor/browser`` feeds the embedded browser assets via
  ``update_browser_assets.py``.
* ``vendor/browser/pages-v1`` retains the immutable rollback first-party files.
* The v2 literals embedded from ``web/pages-v2`` into ``pokemon_agent.py`` are
  the canonical current first-party sources.
* This script is the only writer for both root v1 and side-by-side v2 trees.

The restricted AST reader below evaluates only literals, byte/string
concatenation, and the two compression calls used by the embedded assets. It
does not execute ``pokemon_agent.py`` or import optional runtime dependencies.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import shutil
import stat
import sys
import zlib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "pokemon_agent.py"
WATCH = ROOT / "docs" / "watch"
HOST = ROOT / "docs" / "host"
V1 = ROOT / "vendor" / "browser" / "pages-v1"
V2 = ROOT / "web" / "pages-v2"
FILE_MODE = 0o644
DIRECTORY_MODE = 0o755
V1_MANIFEST = ROOT / "vendor" / "browser" / "PAGES_V1.json"


def display_path(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


def verify_v1_manifest() -> None:
    value = json.loads(V1_MANIFEST.read_text(encoding="utf-8"))
    if (
        value.get("schema_version") != 1
        or value.get("protocol_version") != 1
        or not isinstance(value.get("files"), list)
    ):
        raise RuntimeError("Immutable v1 Pages manifest is invalid")
    for item in value["files"]:
        if not isinstance(item, dict):
            raise RuntimeError("Immutable v1 Pages manifest item is invalid")
        source = ROOT / str(item.get("source", ""))
        if (
            not source.is_file()
            or source.is_symlink()
            or hashlib.sha256(source.read_bytes()).hexdigest()
            != item.get("sha256")
        ):
            raise RuntimeError(f"Immutable v1 Pages input changed: {source}")


class CanonicalReader:
    """Read selected top-level constants through a deliberately tiny AST."""

    def __init__(self, source_path: Path):
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"),
            filename=str(source_path),
        )
        self.assignments: dict[str, ast.expr] = {}
        self.values: dict[str, Any] = {}
        self.resolving: set[str] = set()
        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            if target.id in self.assignments:
                raise RuntimeError(f"Duplicate canonical constant: {target.id}")
            self.assignments[target.id] = node.value

    def read(self, name: str, expected_type: type[Any]) -> Any:
        value = self._resolve(name)
        if not isinstance(value, expected_type):
            raise RuntimeError(
                f"{name} must be {expected_type.__name__}, "
                f"not {type(value).__name__}"
            )
        return value

    def _resolve(self, name: str) -> Any:
        if name in self.values:
            return self.values[name]
        if name in self.resolving:
            raise RuntimeError(f"Cyclic canonical constant: {name}")
        expression = self.assignments.get(name)
        if expression is None:
            raise RuntimeError(f"Missing canonical constant: {name}")
        self.resolving.add(name)
        try:
            value = self._evaluate(expression)
        finally:
            self.resolving.remove(name)
        self.values[name] = value
        return value

    def _evaluate(self, node: ast.expr) -> Any:
        if isinstance(node, ast.Constant) and isinstance(
            node.value, (bytes, str, int)
        ):
            return node.value
        if isinstance(node, ast.Name):
            return self._resolve(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self._evaluate(node.left)
            right = self._evaluate(node.right)
            if type(left) is not type(right) or not isinstance(left, (bytes, str)):
                raise RuntimeError("Canonical concatenation must use bytes or strings")
            return left + right
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "decode"
                and not node.keywords
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "utf-8"
            ):
                payload = self._evaluate(node.func.value)
                if not isinstance(payload, bytes):
                    raise RuntimeError("Canonical decode requires bytes")
                return payload.decode("utf-8")
            return self._call(node)
        raise RuntimeError(
            f"Unsupported canonical expression: {type(node).__name__}"
        )

    def _call(self, node: ast.Call) -> bytes:
        if (
            len(node.args) != 1
            or node.keywords
            or not isinstance(node.func, ast.Attribute)
            or not isinstance(node.func.value, ast.Name)
        ):
            raise RuntimeError("Unsupported canonical function call")
        function_name = (node.func.value.id, node.func.attr)
        functions = {
            ("base64", "b64decode"): base64.b64decode,
            ("zlib", "decompress"): zlib.decompress,
        }
        function = functions.get(function_name)
        if function is None:
            raise RuntimeError(
                f"Disallowed canonical function: {'.'.join(function_name)}"
            )
        argument = self._evaluate(node.args[0])
        if not isinstance(argument, bytes):
            raise RuntimeError("Canonical compression calls require bytes")
        return function(argument)


def canonical_files() -> dict[Path, bytes]:
    verify_v1_manifest()
    reader = CanonicalReader(AGENT)
    html = reader.read("SPECTATOR_HTML", str).encode("utf-8")
    css = reader.read("SPECTATOR_CSS", str).encode("utf-8")
    javascript = reader.read("SPECTATOR_JS", str).encode("utf-8")
    pairing = reader.read("PAIRING_JS", str).encode("utf-8")
    peerjs = reader.read("PEERJS_RUNTIME_JS", bytes)
    trystero = reader.read("TRYSTERO_NOSTR_RUNTIME_JS", bytes)
    qrious = reader.read("QRIOUS_RUNTIME_JS", bytes)
    notices = reader.read("THIRD_PARTY_BROWSER_LICENSES", bytes)
    peerjs_version = reader.read("PEERJS_VERSION", str)
    peerjs_sha256 = reader.read("PEERJS_RUNTIME_SHA256", str)
    trystero_version = reader.read("TRYSTERO_NOSTR_VERSION", str)
    trystero_sha256 = reader.read("TRYSTERO_NOSTR_RUNTIME_SHA256", str)
    qrious_version = reader.read("QRIOUS_VERSION", str)
    qrious_sha256 = reader.read("QRIOUS_RUNTIME_SHA256", str)

    vendor_peerjs = (
        ROOT
        / "vendor"
        / "browser"
        / f"peerjs-{peerjs_version}.runtime.min.js"
    ).read_bytes()
    if peerjs != vendor_peerjs:
        raise RuntimeError(
            "Embedded PeerJS differs from vendor/browser; run "
            "scripts/update_browser_assets.py"
        )
    actual_sha256 = hashlib.sha256(peerjs).hexdigest()
    if actual_sha256 != peerjs_sha256:
        raise RuntimeError(
            f"PeerJS has SHA-256 {actual_sha256}, expected {peerjs_sha256}"
        )
    vendor = ROOT / "vendor" / "browser"
    if trystero != (
        vendor / f"trystero-nostr-{trystero_version}.iife.min.js"
    ).read_bytes():
        raise RuntimeError("Embedded Trystero differs from vendor/browser")
    if hashlib.sha256(trystero).hexdigest() != trystero_sha256:
        raise RuntimeError("Embedded Trystero digest does not match its pin")
    if qrious != (
        vendor / f"qrious-{qrious_version}.runtime.min.js"
    ).read_bytes():
        raise RuntimeError("Embedded QRious differs from vendor/browser")
    if hashlib.sha256(qrious).hexdigest() != qrious_sha256:
        raise RuntimeError("Embedded QRious digest does not match its pin")

    v1 = {
        Path("index.html"): (V1 / "watch/index.html").read_bytes(),
        Path("spectator.css"): (V1 / "watch/spectator.css").read_bytes(),
        Path("spectator.js"): (V1 / "watch/spectator.js").read_bytes(),
        Path("vendor/peerjs.min.js"): peerjs,
        Path("vendor/licenses.txt"): (V1 / "watch/licenses.txt").read_bytes(),
    }
    v2 = {
        Path("v2/index.html"): html,
        Path("v2/spectator.rpp-v2.css"): css,
        Path("v2/spectator.rpp-v2.js"): javascript,
        Path("v2/pairing.rpp-v2.js"): pairing,
        Path("v2/vendor/peerjs-1.5.5.runtime.min.js"): peerjs,
        Path("v2/vendor/trystero-nostr-0.25.3-rpp1.min.js"): trystero,
        Path("v2/vendor/qrious-4.0.2.runtime.min.js"): qrious,
        Path("v2/vendor/licenses.txt"): notices,
    }
    return {**v1, **v2}


def canonical_host_files() -> dict[Path, bytes]:
    verify_v1_manifest()
    reader = CanonicalReader(AGENT)
    html = reader.read("HOST_HTML", str).encode("utf-8")
    css = reader.read("HOST_CSS", str).encode("utf-8")
    javascript = reader.read("HOST_JS", str).encode("utf-8")
    pairing = reader.read("PAIRING_JS", str).encode("utf-8")
    peerjs = reader.read("PEERJS_RUNTIME_JS", bytes)
    trystero = reader.read("TRYSTERO_NOSTR_RUNTIME_JS", bytes)
    qrious = reader.read("QRIOUS_RUNTIME_JS", bytes)
    notices = reader.read("THIRD_PARTY_BROWSER_LICENSES", bytes)
    peerjs_sha256 = reader.read("PEERJS_RUNTIME_SHA256", str)
    peerjs_version = reader.read("PEERJS_VERSION", str)
    trystero_sha256 = reader.read("TRYSTERO_NOSTR_RUNTIME_SHA256", str)
    trystero_version = reader.read("TRYSTERO_NOSTR_VERSION", str)
    qrious_sha256 = reader.read("QRIOUS_RUNTIME_SHA256", str)
    qrious_version = reader.read("QRIOUS_VERSION", str)

    vendor = ROOT / "vendor" / "browser"
    if peerjs != (vendor / f"peerjs-{peerjs_version}.runtime.min.js").read_bytes():
        raise RuntimeError("Embedded PeerJS runtime differs from vendor/browser")
    if qrious != (
        vendor / f"qrious-{qrious_version}.runtime.min.js"
    ).read_bytes():
        raise RuntimeError("Embedded QRious runtime differs from vendor/browser")
    if trystero != (
        vendor / f"trystero-nostr-{trystero_version}.iife.min.js"
    ).read_bytes():
        raise RuntimeError("Embedded Trystero runtime differs from vendor/browser")
    if hashlib.sha256(peerjs).hexdigest() != peerjs_sha256:
        raise RuntimeError("Embedded PeerJS digest does not match its pin")
    if hashlib.sha256(qrious).hexdigest() != qrious_sha256:
        raise RuntimeError("Embedded QRious digest does not match its pin")
    if hashlib.sha256(trystero).hexdigest() != trystero_sha256:
        raise RuntimeError("Embedded Trystero digest does not match its pin")
    v1 = {
        Path("index.html"): (V1 / "host/index.html").read_bytes(),
        Path("host.css"): (V1 / "host/host.css").read_bytes(),
        Path("host.js"): (V1 / "host/host.js").read_bytes(),
        Path("vendor/peerjs.min.js"): peerjs,
        Path("vendor/qrious.min.js"): qrious,
        Path("vendor/licenses.txt"): (V1 / "host/licenses.txt").read_bytes(),
    }
    v2 = {
        Path("v2/index.html"): html,
        Path("v2/host.rpp-kite-v2.css"): css,
        Path("v2/host.rpp-kite-v2.js"): javascript,
        Path("v2/pairing.rpp-v2.js"): pairing,
        Path("v2/vendor/peerjs-1.5.5.runtime.min.js"): peerjs,
        Path("v2/vendor/trystero-nostr-0.25.3-rpp1.min.js"): trystero,
        Path("v2/vendor/qrious-4.0.2.runtime.min.js"): qrious,
        Path("v2/vendor/licenses.txt"): notices,
        Path("v2/return/index.html"): (V2 / "return/index.html").read_bytes(),
        Path("v2/return/return.rpp-v2.css"): (
            V2 / "return/return.css"
        ).read_bytes(),
        Path("v2/return/return.rpp-v2.js"): (
            V2 / "return/return.js"
        ).read_bytes(),
    }
    return {**v1, **v2}


def drift(
    expected: dict[Path, bytes],
    site: Path | None = None,
) -> list[str]:
    site = WATCH if site is None else site
    issues: list[str] = []
    if not site.is_dir() or site.is_symlink():
        return [f"missing generated directory: {display_path(site)}"]

    expected_nodes = set(expected)
    for relative_path in expected:
        expected_nodes.update(relative_path.parents)
    expected_nodes.discard(Path("."))
    actual_nodes = {
        path.relative_to(site)
        for path in site.rglob("*")
    }
    for path in sorted(expected_nodes - actual_nodes):
        issues.append(f"missing: {display_path(site / path)}")
    for path in sorted(actual_nodes - expected_nodes):
        issues.append(f"unexpected: {display_path(site / path)}")

    for relative_path, payload in expected.items():
        path = site / relative_path
        if not path.is_file() or path.is_symlink():
            issues.append(f"not a regular file: {display_path(path)}")
            continue
        if path.read_bytes() != payload:
            issues.append(f"content differs: {display_path(path)}")
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != FILE_MODE:
            issues.append(
                f"mode differs: {display_path(path)} "
                f"({mode:#o}, expected {FILE_MODE:#o})"
            )
    return issues


def write_site(
    expected: dict[Path, bytes],
    site: Path | None = None,
) -> None:
    site = WATCH if site is None else site
    if site.is_symlink() or site.is_file():
        site.unlink()
    elif site.exists():
        shutil.rmtree(site)
    site.mkdir(parents=True)
    site.chmod(DIRECTORY_MODE)
    for relative_path, payload in expected.items():
        path = site / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(DIRECTORY_MODE)
        path.write_bytes(payload)
        path.chmod(FILE_MODE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if root v1 and side-by-side v2 Pages trees drift",
    )
    args = parser.parse_args()
    try:
        sites = {
            WATCH: canonical_files(),
            HOST: canonical_host_files(),
        }
        if args.check:
            issues = [
                issue
                for site, expected in sites.items()
                for issue in drift(expected, site)
            ]
            if issues:
                print("GitHub Pages site is out of date:", file=sys.stderr)
                for issue in issues:
                    print(f"  - {issue}", file=sys.stderr)
                return 1
            print("GitHub Pages watch and host sites are in sync")
            return 0
        for site, expected in sites.items():
            write_site(expected, site)
    except (OSError, RuntimeError, SyntaxError, zlib.error) as error:
        print(f"Cannot build GitHub Pages sites: {error}", file=sys.stderr)
        return 2
    count = sum(len(expected) for expected in sites.values())
    print(f"Wrote {count} files under docs/watch and docs/host")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
