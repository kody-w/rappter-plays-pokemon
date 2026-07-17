from __future__ import annotations

import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from openrappter.agents.pokemon_agent import (
    HOST_JS,
    KITE_STRING_JS,
    SPECTATOR_JS,
    VIEWER_JS,
)

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_browser_js.py"


def test_first_party_javascript_extraction_is_deterministic():
    checker = runpy.run_path(str(CHECKER))
    scripts = checker["extracted_first_party_scripts"]()

    assert set(scripts) == {"VIEWER_JS", "SPECTATOR_JS", "HOST_JS"}
    assert scripts["VIEWER_JS"] == VIEWER_JS
    assert scripts["HOST_JS"] == HOST_JS
    for source in (*scripts.values(), KITE_STRING_JS.decode("utf-8")):
        assert "sourceMappingURL" not in source


def test_node_parses_all_browser_javascript_and_runs_contracts():
    node = shutil.which("node")
    if node is None:
        pytest.skip(
            "Node.js is optional on Python-only developer systems; CI requires it"
        )

    syntax = subprocess.run(
        [sys.executable, str(CHECKER), "--require-node"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr or syntax.stdout

    contract = subprocess.run(
        [node, str(ROOT / "tests" / "browser_contract_harness.js")],
        cwd=ROOT,
        input=VIEWER_JS,
        text=True,
        capture_output=True,
        check=False,
    )
    assert contract.returncode == 0, contract.stderr or contract.stdout

    spectator_contract = subprocess.run(
        [node, str(ROOT / "tests" / "spectator_dashboard_harness.js")],
        cwd=ROOT,
        input=SPECTATOR_JS,
        text=True,
        capture_output=True,
        check=False,
    )
    assert spectator_contract.returncode == 0, (
        spectator_contract.stderr or spectator_contract.stdout
    )

    host_contract = subprocess.run(
        [node, str(ROOT / "tests" / "host_contract_harness.js")],
        cwd=ROOT,
        input=HOST_JS,
        text=True,
        capture_output=True,
        check=False,
    )
    assert host_contract.returncode == 0, (
        host_contract.stderr or host_contract.stdout
    )

    string_contract = subprocess.run(
        [node, str(ROOT / "tests" / "kite_string_harness.js")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert string_contract.returncode == 0, (
        string_contract.stderr or string_contract.stdout
    )
