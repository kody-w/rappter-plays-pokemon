#!/usr/bin/env python3
"""Provision the official stable macOS Chrome for Testing in a private cache."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rappter_plays_pokemon.chrome_for_testing import (  # noqa: E402
    default_cache_dir,
    provision_chrome_for_testing,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=default_cache_dir())
    args = parser.parse_args()
    try:
        browser = provision_chrome_for_testing(args.cache)
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
