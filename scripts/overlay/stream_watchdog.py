#!/usr/bin/env python3
"""Liveness watchdog for the dual-destination Pokemon livestream.

Two independent arms:

  YouTube  ffmpeg inside stream_overlay.mjs pushes RTMP directly to YouTube.
           run_forever.sh is the supervisor. Healing = recycle the encoder.

  Twitch   OBS ingests the encoder's local MPEG-TS mirror (udp://127.0.0.1:23000)
           and pushes to Twitch. Healing = put OBS on the dedicated Pokemon
           profile/collection and start the stream.

`--check` reports state as JSON and exits. `--heal` also remediates what it can.
Exit code is 0 when both destinations are live, 1 otherwise, so a loop can
trigger on it directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import obs_control  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_DIR = Path(
    os.environ.get(
        "RPP_RUNTIME_DIR",
        Path.home() / ".openrappter/pokemon-red",
    )
).expanduser().resolve()
ENCODER_LOG = RUNTIME_DIR / "encoder.log"
WATCHDOG_LOG = RUNTIME_DIR / "watchdog.log"
TWITCH_KEY_FILE = Path(
    os.environ.get("RPP_TWITCH_KEY_FILE", RUNTIME_DIR / "twitch-key.txt")
)
RUN_FOREVER = REPO_ROOT / "scripts/overlay/run_forever.sh"

YT_CHANNEL_URL = os.environ.get(
    "RPP_YT_CHANNEL_URL",
    "https://www.youtube.com/channel/UCz0Tfe07OAwnQR-fd3E1y4Q/live",
)
TWITCH_URL = os.environ.get("RPP_TWITCH_URL", "https://www.twitch.tv/rappterone")

# encoder.log is appended on every ffmpeg stats line (sub-second cadence), so
# anything older than this means the encoder is wedged rather than just quiet.
LOG_STALE_SECS = 120

# How long to wait before re-trying the "recycle to republish" trick. Long,
# because if YouTube Auto-start is off no amount of recycling will help.
RECYCLE_COOLDOWN_SECS = 30 * 60
RECYCLE_STAMP = RUNTIME_DIR / ".watchdog-last-recycle"


def _last_recycle() -> float:
    try:
        return float(RECYCLE_STAMP.read_text().strip())
    except (OSError, ValueError):
        return 0.0


def _mark_recycle() -> None:
    try:
        RECYCLE_STAMP.parent.mkdir(parents=True, exist_ok=True)
        RECYCLE_STAMP.write_text(str(time.time()))
    except OSError:
        pass


def log(msg: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {msg}"
    print(line, flush=True)
    try:
        WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with WATCHDOG_LOG.open("a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _ps_lines() -> list[str]:
    out = subprocess.run(
        ["ps", "-Ao", "pid=,command="], capture_output=True, text=True, timeout=20
    )
    return out.stdout.splitlines()


def _pids_matching(pattern: str) -> list[int]:
    rx = re.compile(pattern)
    pids = []
    for line in _ps_lines():
        line = line.strip()
        if not line:
            continue
        pid, _, cmd = line.partition(" ")
        if rx.search(cmd):
            try:
                pids.append(int(pid))
            except ValueError:
                continue
    return pids


def _rtmp_established(pid: int) -> bool:
    try:
        out = subprocess.run(
            ["lsof", "-nP", "-i", "-a", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False
    return ":1935" in out.stdout and "ESTABLISHED" in out.stdout


BROWSER_PROBE = REPO_ROOT / "scripts/overlay/browser_probe.mjs"


def browser_probe(urls: list[str]) -> dict[str, dict]:
    """Load each URL in real headless Chromium and report what a viewer sees.

    yt-dlp reports what YouTube/Twitch's API claims; this reports whether a
    player actually renders and advances. Returns {} if the probe can't run,
    which callers treat as "no opinion" rather than "down".
    """
    if not BROWSER_PROBE.exists() or not shutil.which("node"):
        return {}
    try:
        out = subprocess.run(
            ["node", str(BROWSER_PROBE), *urls],
            cwd=str(BROWSER_PROBE.parent),
            capture_output=True,
            text=True,
            timeout=240,
        )
    except subprocess.TimeoutExpired:
        return {}
    try:
        payload = json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}
    return {r["url"]: r for r in payload.get("results", [])}


def _is_live(url: str) -> bool | None:
    """True/False if yt-dlp answered, None if the probe itself failed."""
    if not shutil.which("yt-dlp"):
        return None
    try:
        out = subprocess.run(
            ["yt-dlp", "--no-warnings", "--socket-timeout", "15", "-g", url],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        return None
    if out.returncode == 0 and out.stdout.strip():
        return True
    if "not currently live" in (out.stderr or "").lower():
        return False
    if "offline" in (out.stderr or "").lower():
        return False
    return None


# --- YouTube arm ----------------------------------------------------------


def youtube_state() -> dict:
    supervisor = _pids_matching(r"run_forever\.sh")
    overlay = _pids_matching(r"node .*stream_overlay\.mjs")
    ffmpeg = _pids_matching(r"ffmpeg .*rtmp://a\.rtmp\.youtube\.com")

    log_age = None
    if ENCODER_LOG.exists():
        log_age = time.time() - ENCODER_LOG.stat().st_mtime

    return {
        "supervisor_pids": supervisor,
        "overlay_pids": overlay,
        "ffmpeg_pids": ffmpeg,
        "encoder_log_age_secs": None if log_age is None else round(log_age, 1),
        "encoder_log_stale": log_age is None or log_age > LOG_STALE_SECS,
        "rtmp_established": any(_rtmp_established(p) for p in ffmpeg),
        "ytdlp_live": _is_live(YT_CHANNEL_URL),
    }


def heal_youtube(state: dict) -> list[str]:
    actions: list[str] = []

    if not state["supervisor_pids"]:
        if not RUN_FOREVER.exists():
            actions.append(f"CANNOT HEAL: {RUN_FOREVER} missing")
            return actions
        WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ENCODER_LOG.open("a") as logfh:
            subprocess.Popen(
                ["/bin/bash", str(RUN_FOREVER)],
                cwd=str(REPO_ROOT),
                stdout=logfh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        actions.append("started run_forever.sh (supervisor was gone)")
        return actions

    if state["encoder_log_stale"] or not state["overlay_pids"]:
        for pid in state["overlay_pids"]:
            try:
                os.kill(pid, 15)
                actions.append(f"killed wedged stream_overlay.mjs pid {pid}")
            except ProcessLookupError:
                pass
        actions.append("run_forever.sh will respawn the encoder within ~10s")
        return actions

    if state["live"] is False:
        # Encoder is fine but YouTube isn't publishing - the auto-stop case,
        # where the broadcast ended and the encoder kept pushing into a dead
        # key. A fresh RTMP handshake republishes it *if* Auto-start is on, so
        # try exactly that, but on a long cooldown: when Auto-start is off,
        # recycling can never help and would just thrash a healthy encoder.
        # An established RTMP session means YouTube is accepting our bytes, so
        # the gap is purely Studio-side (broadcast sitting in preview waiting on
        # GO LIVE). Recycling then is worse than useless: it tears down a
        # working feed and resets the buffer YouTube is accumulating to publish.
        if state["rtmp_established"]:
            actions.append(
                "NEEDS A HUMAN: YouTube is accepting the RTMP feed but has not "
                "published it - the broadcast is sitting in 'Preparing stream'. "
                "Click GO LIVE in Studio, and enable Auto-start so future "
                "reconnects publish themselves. Not recycling: the encoder is "
                "healthy and a restart would only reset YouTube's buffer."
            )
            return actions

        since = time.time() - _last_recycle()
        if since >= RECYCLE_COOLDOWN_SECS:
            for pid in state["overlay_pids"]:
                try:
                    os.kill(pid, 15)
                except ProcessLookupError:
                    continue
            _mark_recycle()
            actions.append(
                "recycled the encoder to force a fresh RTMP handshake "
                "(republishes the broadcast if Auto-start is on)"
            )
        else:
            wait = int((RECYCLE_COOLDOWN_SECS - since) / 60)
            actions.append(
                "NEEDS A HUMAN: encoder is healthy and pushing RTMP, but YouTube "
                "is not publishing, and a recycle already failed to fix it. Turn "
                "on Enable Auto-start/Auto-stop for the stream key in YouTube "
                f"Studio, or click GO LIVE once. (next auto-retry in ~{wait}m)"
            )

    return actions


# --- Twitch arm -----------------------------------------------------------


def twitch_key() -> str | None:
    if not TWITCH_KEY_FILE.exists():
        return None
    key = TWITCH_KEY_FILE.read_text().strip()
    return key or None


def _obs_running() -> list[int]:
    return _pids_matching(r"/Applications/OBS\.app/Contents/MacOS/OBS")


async def _obs_status() -> dict | None:
    try:
        client = await obs_control.connect()
        async with client as obs:
            return await obs.status()
    except Exception as exc:  # noqa: BLE001 - report, never crash the watchdog
        return {"error": str(exc)}


def twitch_state() -> dict:
    obs_pids = _obs_running()
    obs = asyncio.run(_obs_status()) if obs_pids else None
    return {
        "obs_pids": obs_pids,
        "obs": obs,
        "key_configured": twitch_key() is not None,
        "ytdlp_live": _is_live(TWITCH_URL),
    }


async def _heal_twitch_async(state: dict, key: str) -> list[str]:
    actions: list[str] = []
    client = await obs_control.connect()
    async with client as obs:
        status = await obs.status()

        # Already doing the right thing: OBS is streaming the Pokemon profile.
        # The browser probe can fail transiently (slow player, rate limit) and
        # report "down" for a stream that is fine - acting on that would mean
        # reconfiguring OBS mid-broadcast, which drops the very stream we are
        # trying to protect. OBS's own output state is the authority here.
        if status["streaming"] and status["profile"] == obs_control.POKEMON_PROFILE:
            actions.append(
                "no action: OBS is already streaming the Pokemon profile "
                f"(congestion={status['stream_congestion']}, "
                f"skipped_frames={status['stream_skipped_frames']}). "
                "Treating the probe's 'down' as a transient false negative."
            )
            return actions

        # Hard guard: if OBS is actively streaming or recording, it is in use
        # (very likely the Private Coding setup). Never yank it out from under.
        if status["recording"] or status["streaming"]:
            actions.append(
                f"SKIPPED: OBS is busy (profile={status['profile']!r}, "
                f"streaming={status['streaming']}, recording={status['recording']}) "
                "- refusing to switch profiles"
            )
            return actions

        actions += await obs.ensure_pokemon_profile(key)

        status = await obs.status()
        if not status["streaming"]:
            await obs.start_stream()
            actions.append("started OBS stream to Twitch")
        else:
            actions.append("OBS was already streaming on the Pokemon profile")
    return actions


def heal_twitch(state: dict) -> list[str]:
    key = twitch_key()
    if key is None:
        return [
            f"CANNOT HEAL: no Twitch key at {TWITCH_KEY_FILE}. Create it with: "
            f"umask 077 && printf '%s\\n' '<twitch-key>' > {TWITCH_KEY_FILE}"
        ]

    if not state["obs_pids"]:
        subprocess.run(["open", "-a", "OBS"], timeout=30)
        time.sleep(12)
        if not _obs_running():
            return ["CANNOT HEAL: launched OBS but it did not come up"]

    try:
        return asyncio.run(_heal_twitch_async(state, key))
    except Exception as exc:  # noqa: BLE001
        return [f"CANNOT HEAL: {exc}"]


# --- entry point ----------------------------------------------------------


def reconcile(report: dict, use_browser: bool) -> None:
    """Settle each arm's `live` verdict, confirming optimism with a real browser.

    yt-dlp is the cheap first pass. Whenever it claims live - or can't tell -
    we open the page in Chromium and believe what a viewer would see, because a
    stale manifest can outlive the actual feed. A yt-dlp "not live" is trusted
    as-is: it has no false negatives worth a browser launch.
    """
    arms = {
        "youtube": YT_CHANNEL_URL,
        "twitch": TWITCH_URL,
    }
    need_browser = [
        url
        for arm, url in arms.items()
        if not report[arm].get("skipped") and report[arm]["ytdlp_live"] is not False
    ]

    probes = browser_probe(need_browser) if (use_browser and need_browser) else {}

    for arm, url in arms.items():
        state = report[arm]
        if state.get("skipped"):
            continue
        probe = probes.get(url)
        if probe is not None:
            state["browser"] = probe
            state["live"] = bool(probe.get("live"))
            state["verdict_source"] = "browser"
            # Live but wrong-shaped is still broken for viewers, so surface it
            # rather than letting a green "live" hide a mangled canvas.
            aspect = probe.get("videoAspect")
            if aspect and abs(aspect - 16 / 9) > 0.15:
                state["aspect_warning"] = (
                    f"delivered frame is {probe.get('videoWidth')}x"
                    f"{probe.get('videoHeight')} (aspect {aspect}), not 16:9. "
                    "On YouTube this is usually the Dual stream toggle padding "
                    "the canvas to 1:1 - turn it off in Studio > Stream settings."
                )
        else:
            state["live"] = state["ytdlp_live"]
            state["verdict_source"] = (
                "yt-dlp" if state["ytdlp_live"] is not None else "unknown"
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="report only (the default)")
    ap.add_argument("--heal", action="store_true", help="remediate, not just report")
    ap.add_argument(
        "--skip-twitch", action="store_true", help="only watch the YouTube arm"
    )
    ap.add_argument(
        "--no-browser",
        action="store_true",
        help="trust yt-dlp alone; skip the headless-Chromium confirmation",
    )
    args = ap.parse_args()

    report: dict = {"checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    report["youtube"] = youtube_state()
    report["twitch"] = (
        {"skipped": True} if args.skip_twitch else twitch_state()
    )
    reconcile(report, use_browser=not args.no_browser)

    if args.heal:
        yt_actions = heal_youtube(report["youtube"])
        report["youtube"]["actions"] = yt_actions
        for a in yt_actions:
            log(f"youtube: {a}")

        if not args.skip_twitch and report["twitch"]["live"] is not True:
            tw_actions = heal_twitch(report["twitch"])
            report["twitch"]["actions"] = tw_actions
            for a in tw_actions:
                log(f"twitch: {a}")

    print(json.dumps(report, indent=2))

    yt_ok = report["youtube"]["live"] is True
    tw_ok = args.skip_twitch or report["twitch"]["live"] is True
    return 0 if (yt_ok and tw_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
