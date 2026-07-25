"""The operator dashboard must stay read-only and must never lie about staleness."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from rappter_plays_pokemon import ops


def write_status(tmp_path, **overrides):
    now = datetime.now(timezone.utc)
    status = {
        "heartbeat_at": now.isoformat(),
        "running": True,
        "stuck_state": False,
        "stuck_decision_count": 3,
        "stuck_reasons": [],
        "objective": "Climb Pokemon Tower",
        "model_calls": 12,
        "decision_latency_seconds": 6.5,
        "storage_free_bytes": 15_000_000_000,
        "last_error": None,
        "game_state": {
            "location": "Pokemon Tower 4F",
            "badges": ["Boulder", "Cascade"],
            "party": [
                {"nickname": "BLASTOISE", "level": 43, "hp": 71, "max_hp": 142},
                {"nickname": "ODDISH", "level": 16, "hp": 0, "max_hp": 42},
            ],
        },
    }
    status.update(overrides)
    (tmp_path / "status.json").write_text(json.dumps(status), encoding="utf-8")
    return status


def test_metrics_projects_the_four_tabs_and_computes_hp(tmp_path):
    write_status(tmp_path)

    payload = ops.metrics(tmp_path)

    assert set(payload) >= {"stuck", "run", "brain", "infra", "headline"}
    assert payload["stale"] is False
    assert payload["run"]["party"][0]["hp_fraction"] == pytest.approx(71 / 142)
    assert payload["run"]["party"][1]["fainted"] is True
    # The headline surfaces the weakest member, which is the whole point of
    # glancing at a phone instead of the stream.
    assert payload["headline"]["weakest_hp_fraction"] == 0.0
    assert payload["brain"]["model_calls"] == 12


def test_stale_heartbeat_is_reported_rather_than_shown_as_current(tmp_path):
    old = datetime.now(timezone.utc) - timedelta(seconds=600)
    write_status(tmp_path, heartbeat_at=old.isoformat())

    payload = ops.metrics(tmp_path)

    assert payload["stale"] is True
    assert payload["heartbeat_age_seconds"] > ops.STALE_HEARTBEAT_SECONDS


def test_missing_status_reports_an_error_instead_of_empty_metrics(tmp_path):
    payload = ops.metrics(tmp_path)

    assert payload["stale"] is True
    assert "status.json" in payload["error"]


def test_projection_drops_fields_that_were_not_reviewed(tmp_path):
    write_status(tmp_path, rtmp_key="super-secret", clips=[{"name": "c.mp4"}])

    payload = ops.metrics(tmp_path)

    flattened = json.dumps(payload)
    assert "super-secret" not in flattened
    assert "c.mp4" not in flattened


def _serve(tmp_path):
    server, _thread = ops.serve(tmp_path, "127.0.0.1", 0)
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_dashboard_serves_page_and_metrics(tmp_path):
    write_status(tmp_path)
    server, base = _serve(tmp_path)
    try:
        with urllib.request.urlopen(f"{base}/") as response:  # noqa: S310
            assert response.status == 200
            assert b"RPP ops" in response.read()
        with urllib.request.urlopen(f"{base}/api/metrics") as response:  # noqa: S310
            assert json.load(response)["run"]["location"] == "Pokemon Tower 4F"
    finally:
        server.shutdown()


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_dashboard_refuses_every_write_method(tmp_path, method):
    """Watch-only is a property of the server, not just of the UI."""
    write_status(tmp_path)
    server, base = _serve(tmp_path)
    try:
        request = urllib.request.Request(  # noqa: S310
            f"{base}/api/metrics", method=method, data=b"{}"
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)  # noqa: S310
        assert caught.value.code == 405
    finally:
        server.shutdown()


def test_unknown_paths_are_not_served_from_disk(tmp_path):
    write_status(tmp_path)
    (tmp_path / "rtmp-key.txt").write_text("secret", encoding="utf-8")
    server, base = _serve(tmp_path)
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{base}/rtmp-key.txt")  # noqa: S310
        assert caught.value.code == 404
    finally:
        server.shutdown()
