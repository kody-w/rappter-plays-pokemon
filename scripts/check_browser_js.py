#!/usr/bin/env python3
"""Extract and parse every browser script without making network calls."""

from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "pokemon_agent.py"
FIRST_PARTY_NAMES = ("VIEWER_JS", "SPECTATOR_JS")


def extracted_first_party_scripts() -> dict[str, str]:
    tree = ast.parse(AGENT.read_text(encoding="utf-8"), filename=str(AGENT))
    scripts: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in FIRST_PARTY_NAMES:
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, str):
            raise RuntimeError(f"{target.id} must be a literal JavaScript string")
        scripts[target.id] = value
    missing = sorted(set(FIRST_PARTY_NAMES) - scripts.keys())
    if missing:
        raise RuntimeError(f"Missing browser scripts: {', '.join(missing)}")
    return scripts


def browser_scripts() -> dict[str, str]:
    scripts = extracted_first_party_scripts()
    for path in sorted((ROOT / "vendor/browser").glob("*.js")):
        scripts[str(path.relative_to(ROOT))] = path.read_text(encoding="utf-8")
    return scripts


def check_with_node(node: str) -> None:
    failures: list[str] = []
    for name, source in browser_scripts().items():
        result = subprocess.run(
            [node, "--check", "-"],
            input=source,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            failures.append(f"{name}: {detail}")
    if failures:
        raise RuntimeError("\n".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-node",
        action="store_true",
        help="fail instead of skipping when Node.js is unavailable",
    )
    args = parser.parse_args()
    node = shutil.which("node")
    if node is None:
        message = "Node.js is unavailable; browser JavaScript syntax check skipped"
        if args.require_node:
            print(message, file=sys.stderr)
            return 2
        print(f"SKIP: {message}")
        return 0
    try:
        check_with_node(node)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Parsed {len(browser_scripts())} browser scripts with {node}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
