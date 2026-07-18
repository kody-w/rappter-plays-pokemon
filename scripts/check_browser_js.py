#!/usr/bin/env python3
"""Extract and parse every browser script without making network calls."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pages_site import CanonicalReader

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "pokemon_agent.py"
FIRST_PARTY_NAMES = (
    "VIEWER_JS",
    "SPECTATOR_JS",
    "HOST_JS",
    "PAIRING_JS",
    "PAIR_RETURN_JS",
)


def extracted_first_party_scripts() -> dict[str, str]:
    reader = CanonicalReader(AGENT)
    return {
        name: reader.read(name, str)
        for name in FIRST_PARTY_NAMES
    }


def browser_scripts() -> dict[str, str]:
    scripts = extracted_first_party_scripts()
    kite_string = ROOT / "scripts" / "kite_vtwin.js"
    scripts[str(kite_string.relative_to(ROOT))] = kite_string.read_text(
        encoding="utf-8"
    )
    return_page = ROOT / "web/pages-v2/return/return.js"
    scripts[str(return_page.relative_to(ROOT))] = return_page.read_text(
        encoding="utf-8"
    )
    story_player = ROOT / "docs/story/story.js"
    scripts[str(story_player.relative_to(ROOT))] = story_player.read_text(
        encoding="utf-8"
    )
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
