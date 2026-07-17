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
    PAIR_RETURN_JS,
    PAIRING_JS,
    SPECTATOR_JS,
    TRYSTERO_NOSTR_RUNTIME_JS,
    VIEWER_JS,
)

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_browser_js.py"


def test_first_party_javascript_extraction_is_deterministic():
    checker = runpy.run_path(str(CHECKER))
    scripts = checker["extracted_first_party_scripts"]()

    assert set(scripts) == {
        "VIEWER_JS",
        "SPECTATOR_JS",
        "HOST_JS",
        "PAIRING_JS",
        "PAIR_RETURN_JS",
    }
    assert scripts["VIEWER_JS"] == VIEWER_JS
    assert scripts["HOST_JS"] == HOST_JS
    assert scripts["PAIRING_JS"] == PAIRING_JS
    assert scripts["PAIR_RETURN_JS"] == PAIR_RETURN_JS
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

    pairing_contract = subprocess.run(
        [node, str(ROOT / "tests" / "pairing_contract_harness.js")],
        cwd=ROOT,
        input=PAIRING_JS,
        text=True,
        capture_output=True,
        check=False,
    )
    assert pairing_contract.returncode == 0, (
        pairing_contract.stderr or pairing_contract.stdout
    )

    nostr_host_contract = subprocess.run(
        [node, str(ROOT / "tests" / "nostr_host_contract_harness.js")],
        cwd=ROOT,
        input=HOST_JS,
        text=True,
        capture_output=True,
        check=False,
    )
    assert nostr_host_contract.returncode == 0, (
        nostr_host_contract.stderr or nostr_host_contract.stdout
    )

    nostr_spectator_contract = subprocess.run(
        [node, str(ROOT / "tests" / "nostr_spectator_contract_harness.js")],
        cwd=ROOT,
        input=SPECTATOR_JS,
        text=True,
        capture_output=True,
        check=False,
    )
    assert nostr_spectator_contract.returncode == 0, (
        nostr_spectator_contract.stderr
        or nostr_spectator_contract.stdout
    )

    manual_share_contract = subprocess.run(
        [node, str(ROOT / "tests" / "manual_share_ux_harness.js")],
        cwd=ROOT,
        input=SPECTATOR_JS,
        text=True,
        capture_output=True,
        check=False,
    )
    assert manual_share_contract.returncode == 0, (
        manual_share_contract.stderr or manual_share_contract.stdout
    )

    return_page_contract = subprocess.run(
        [node, str(ROOT / "tests" / "return_page_contract_harness.js")],
        cwd=ROOT,
        input=(
            ROOT / "web/pages-v2/return/return.js"
        ).read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=False,
    )
    assert return_page_contract.returncode == 0, (
        return_page_contract.stderr or return_page_contract.stdout
    )

    trystero_cleanup_contract = subprocess.run(
        [node, str(ROOT / "tests" / "trystero_cleanup_harness.js")],
        cwd=ROOT,
        input=TRYSTERO_NOSTR_RUNTIME_JS.decode("utf-8"),
        text=True,
        capture_output=True,
        check=False,
    )
    assert trystero_cleanup_contract.returncode == 0, (
        trystero_cleanup_contract.stderr or trystero_cleanup_contract.stdout
    )
