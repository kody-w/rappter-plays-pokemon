#!/usr/bin/env python3
"""Build the checked-in GitHub Pages spectator site without importing the agent.

Canonical direction:

* ``vendor/browser`` feeds the embedded browser assets via
  ``update_browser_assets.py``.
* ``SPECTATOR_HTML``, ``SPECTATOR_CSS``, and ``SPECTATOR_JS`` in
  ``pokemon_agent.py`` are the canonical spectator sources.
* This script is the only writer for ``docs/watch``.

The restricted AST reader below evaluates only literals, byte/string
concatenation, and the two compression calls used by the embedded assets. It
does not execute ``pokemon_agent.py`` or import optional runtime dependencies.
"""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import shutil
import stat
import sys
import zlib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "pokemon_agent.py"
WATCH = ROOT / "docs" / "watch"
FILE_MODE = 0o644
DIRECTORY_MODE = 0o755


def display_path(path: Path) -> Path:
    try:
        return path.relative_to(ROOT)
    except ValueError:
        return path


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
    reader = CanonicalReader(AGENT)
    html = reader.read("SPECTATOR_HTML", str).encode("utf-8")
    css = reader.read("SPECTATOR_CSS", str).encode("utf-8")
    javascript = reader.read("SPECTATOR_JS", str).encode("utf-8")
    peerjs = reader.read("PEERJS_MIN_JS", bytes)
    notices = reader.read("THIRD_PARTY_BROWSER_LICENSES", bytes)
    peerjs_version = reader.read("PEERJS_VERSION", str)
    peerjs_sha256 = reader.read("PEERJS_SHA256", str)

    vendor_peerjs = (
        ROOT / "vendor" / "browser" / f"peerjs-{peerjs_version}.min.js"
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

    return {
        Path("index.html"): html,
        Path("spectator.css"): css,
        Path("spectator.js"): javascript,
        Path("vendor/peerjs.min.js"): peerjs,
        Path("vendor/licenses.txt"): notices,
    }


def drift(expected: dict[Path, bytes]) -> list[str]:
    issues: list[str] = []
    if not WATCH.is_dir() or WATCH.is_symlink():
        return [f"missing generated directory: {display_path(WATCH)}"]

    expected_nodes = set(expected)
    for relative_path in expected:
        expected_nodes.update(relative_path.parents)
    expected_nodes.discard(Path("."))
    actual_nodes = {
        path.relative_to(WATCH)
        for path in WATCH.rglob("*")
    }
    for path in sorted(expected_nodes - actual_nodes):
        issues.append(f"missing: {display_path(WATCH / path)}")
    for path in sorted(actual_nodes - expected_nodes):
        issues.append(f"unexpected: {display_path(WATCH / path)}")

    for relative_path, payload in expected.items():
        path = WATCH / relative_path
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


def write_site(expected: dict[Path, bytes]) -> None:
    if WATCH.is_symlink() or WATCH.is_file():
        WATCH.unlink()
    elif WATCH.exists():
        shutil.rmtree(WATCH)
    WATCH.mkdir(parents=True)
    WATCH.chmod(DIRECTORY_MODE)
    for relative_path, payload in expected.items():
        path = WATCH / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.parent.chmod(DIRECTORY_MODE)
        path.write_bytes(payload)
        path.chmod(FILE_MODE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if docs/watch is not the exact canonical build",
    )
    args = parser.parse_args()
    try:
        expected = canonical_files()
        if args.check:
            issues = drift(expected)
            if issues:
                print("GitHub Pages spectator site is out of date:", file=sys.stderr)
                for issue in issues:
                    print(f"  - {issue}", file=sys.stderr)
                return 1
            print("GitHub Pages spectator site is in sync")
            return 0
        write_site(expected)
    except (OSError, RuntimeError, SyntaxError, zlib.error) as error:
        print(f"Cannot build GitHub Pages spectator site: {error}", file=sys.stderr)
        return 2
    print(f"Wrote {len(expected)} files under {display_path(WATCH)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
