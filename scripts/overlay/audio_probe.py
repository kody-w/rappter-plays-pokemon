#!/usr/bin/env python3
"""Objective audio-defect measurement for the livestream.

Built because the audio problem survived several rounds of plausible-sounding
fixes: the only way to know whether a change helped is to measure the same
defects the same way before and after, from the actual broadcast a listener
hears rather than from the pipeline's own self-reporting.

Measured, in priority order for this stream's failure mode:

  clicks_per_sec   Impulse discontinuities - the audible "random static".
                   Detected as second-difference outliers against a LOCAL
                   robust scale (median absolute deviation), so loud passages
                   of legitimate square-wave music do not count as defects.
  silence_pct      Runs of exact digital zero >= 1ms. The encoder pads silence
                   whenever the agent starves it, and each edge is a click.
  longest_gap_ms   Worst single dropout.
  fill_percent     The encoder's own audio_fill_percent (upstream cause).

Also reported for context (level/tone sanity, not pass/fail):
  peak, rms, crest, dc_offset, clipped_samples, flatness, hf_energy_pct.

  audio_probe.py --source twitch --seconds 30
  audio_probe.py --source youtube --seconds 30
  audio_probe.py --source file --path capture.wav
  audio_probe.py --source twitch --label after-fix --save

Compare runs with --compare BASELINE_JSON. Exit code is 0 when every gate
passes, 1 otherwise, so it can gate a change.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

RUNTIME = Path.home() / ".openrappter/pokemon-red"
RESULTS_DIR = RUNTIME / "audio-probes"
TWITCH_URL = os.environ.get("RPP_TWITCH_URL", "https://www.twitch.tv/rappterone")
YT_URL = os.environ.get(
    "RPP_YT_CHANNEL_URL",
    "https://www.youtube.com/channel/UCz0Tfe07OAwnQR-fd3E1y4Q/live",
)

# MEASURED 2026-07-25, and the whole reason this tool is differential:
# running the analyser on PyBoy's own output - no FIFO, no ffmpeg, no AAC -
# still scores 29.7 clicks/sec. Square-wave chiptune genuinely contains step
# edges, so an absolute click threshold measures the music, not the defect.
# Only the EXCESS over a same-content control is pipeline damage.
#
#   control (pyboy direct) 29.7 clicks/s   <- floor for this content
#   broadcast (live twitch) 72.4 clicks/s  <- +42.7 of pipeline damage
#
# Gate on the excess. Absolute numbers are reported for context only.
GATES = {
    "clicks_excess_vs_control": 5.0,  # broadcast should nearly match control
    "silence_pct": 0.50,              # sub-half-percent dropout
    "longest_gap_ms": 120.0,          # no gap long enough to read as a cutout
}
# Absolute click rate is deliberately NOT gated - see above.
CONTEXT_ONLY = {"clicks_per_sec"}


def _run(cmd: list[str], timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def capture(source: str, seconds: int, path: Path) -> dict:
    """Pull `seconds` of mono 48k PCM from the live stream into `path`."""
    if source == "file":
        raise ValueError("capture() not used for --source file")
    url = TWITCH_URL if source == "twitch" else YT_URL
    if not shutil.which("yt-dlp") or not shutil.which("ffmpeg"):
        raise RuntimeError("yt-dlp and ffmpeg are both required")
    got = _run(["yt-dlp", "--socket-timeout", "20", "-f", "best", "-g", url], timeout=180)
    stream = (got.stdout or "").strip().splitlines()
    if not stream:
        raise RuntimeError(f"{source} is not live or yt-dlp failed: {got.stderr.strip()[:200]}")
    res = _run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", stream[0],
         "-t", str(seconds), "-vn", "-ac", "1", "-ar", "48000",
         "-c:a", "pcm_s16le", "-y", str(path)],
        timeout=seconds * 8 + 120,
    )
    if not path.exists() or path.stat().st_size < 1000:
        raise RuntimeError(f"capture failed: {res.stderr.strip()[:200]}")
    return {"source": source, "url": url}


def capture_control(seconds: int, path: Path) -> dict:
    """Render the SAME content locally through PyBoy only - no FIFO, no ffmpeg.

    This is the floor: whatever click rate this scores is inherent to the
    music, so the broadcast can never legitimately beat it. Everything above
    it is damage the streaming path introduced.
    """
    import numpy as np

    from pyboy import PyBoy  # noqa: PLC0415 - optional, control mode only

    rom = RUNTIME / "Pokemon_Red.gb"
    if not rom.exists():
        raise RuntimeError(f"ROM not found at {rom}")
    pb = PyBoy(str(rom), window="null", sound_volume=0, sound_emulated=True)
    pb.set_emulation_speed(0)
    states = sorted(RUNTIME.glob("**/*.state"))
    loaded = None
    if states:
        try:
            with open(states[-1], "rb") as fh:
                pb.load_state(fh)
            loaded = states[-1].name
        except Exception:
            loaded = None

    chunks: list = []
    dc = None
    last_frame = None
    # 60 fps of emulated frames; run a little long and trim.
    for _ in range(int(seconds * 60 * 1.05)):
        pb.tick()
        frame = pb.frame_count
        if frame == last_frame:
            continue
        last_frame = frame
        arr = pb.sound.ndarray
        if arr is None or not len(arr):
            continue
        blk = arr.astype(np.float32)
        level = float(blk.mean())
        dc = level if dc is None else dc + 0.05 * (level - dc)
        chunks.append(np.clip((blk - dc) * 512.0, -32768, 32767).astype(np.int16))
    pb.stop(save=False)
    if not chunks:
        raise RuntimeError("PyBoy produced no audio (check sound_emulated)")

    pcm = np.concatenate(chunks)
    mono = pcm.mean(axis=1).astype(np.int16) if pcm.ndim == 2 else pcm
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(mono.tobytes())
    return {"source": "pyboy-control", "url": f"local PyBoy (state={loaded})"}


def encoder_fill_percent() -> float | None:
    """Read audio_fill_percent straight off the running encoder, if reachable."""
    try:
        pids = _run(["pgrep", "-f", "node stream_overlay[.]mjs"], timeout=20).stdout.split()
        if not pids:
            return None
        lsof = _run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-a", "-p", pids[0]], timeout=20)
        port = None
        for line in lsof.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 9 and ":" in parts[8]:
                port = parts[8].rsplit(":", 1)[-1]
                break
        if not port:
            return None
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/overlay", timeout=8) as r:
            data = json.loads(r.read())
        host = data.get("host") or {}
        return host.get("audio_fill_percent")
    except Exception:
        return None


def analyse(path: Path) -> dict:
    import numpy as np

    with wave.open(str(path)) as w:
        sr = w.getframerate()
        frames = w.getnframes()
        raw = w.readframes(frames)
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    if x.size == 0:
        raise RuntimeError("empty capture")
    dur = x.size / sr

    peak = float(np.abs(x).max())
    rms = float(np.sqrt((x ** 2).mean()))
    dc = float(x.mean())
    clipped = int((np.abs(x) >= 32700).sum())

    # --- clicks: second-difference outliers vs a LOCAL robust scale ---------
    # A global threshold would flag ordinary loud square-wave edges; scaling by
    # local MAD only flags samples that are anomalous for their own neighbourhood.
    d2 = np.abs(np.diff(x, n=2))
    win = int(sr * 0.05)
    pad = np.pad(d2, (0, (-len(d2)) % win), constant_values=0)
    blocks = pad.reshape(-1, win)
    med = np.median(blocks, axis=1, keepdims=True)
    mad = np.median(np.abs(blocks - med), axis=1, keepdims=True) + 1e-9
    score = (blocks - med) / mad
    hits = np.zeros_like(pad, dtype=bool)
    hits.reshape(-1, win)[:] = score > 12.0
    hits = hits[: len(d2)]
    # Collapse adjacent flagged samples: one impulse = one click, not many.
    idx = np.where(hits)[0]
    clicks = 0 if idx.size == 0 else 1 + int((np.diff(idx) > int(sr * 0.002)).sum())

    # --- dropouts: runs of exact digital zero ------------------------------
    z = (x == 0).astype(np.int8)
    edges = np.diff(np.concatenate(([0], z, [0])))
    starts, ends = np.where(edges == 1)[0], np.where(edges == -1)[0]
    runs = ends - starts
    gaps = runs[runs >= sr // 1000]  # >= 1ms
    silence_pct = float(gaps.sum() / x.size * 100) if gaps.size else 0.0
    longest_gap_ms = float(gaps.max() / sr * 1000) if gaps.size else 0.0

    # --- tone/noise context -------------------------------------------------
    X = np.abs(np.fft.rfft(x * np.hanning(x.size))) ** 2 + 1e-12
    f = np.fft.rfftfreq(x.size, 1 / sr)
    flatness = float(np.exp(np.log(X).mean()) / X.mean())
    hf = float(X[f >= 10000].sum() / X.sum() * 100)

    return {
        "duration_s": round(dur, 1),
        "clicks_per_sec": round(clicks / dur, 3),
        "clicks_total": clicks,
        "silence_pct": round(silence_pct, 3),
        "longest_gap_ms": round(longest_gap_ms, 1),
        "peak": round(peak),
        "rms": round(rms),
        "crest": round(peak / (rms + 1e-9), 2),
        "dc_offset": round(dc, 1),
        "clipped_samples": clipped,
        "flatness": round(flatness, 5),
        "hf_energy_pct_above_10k": round(hf, 2),
    }


def verdict(metrics: dict) -> tuple[bool, list[str]]:
    fails = []
    for key, limit in GATES.items():
        val = metrics.get(key)
        if val is None:
            continue  # excess is absent unless a control was measured
        if val > limit:
            fails.append(f"{key}={val} exceeds {limit}")
    return (not fails), fails


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--source", choices=["twitch", "youtube", "file", "control"], default="twitch"
    )
    ap.add_argument("--path", help="wav file when --source file")
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument(
        "--with-control",
        action="store_true",
        help="also render a local PyBoy control and gate on the click EXCESS "
        "over it (the only number that isolates pipeline damage)",
    )
    ap.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="capture N times and report median/worst. MEASURED 2026-07-25: two "
        "captures 5 minutes apart gave 72 clicks/0%% silence and 25 clicks/29%% "
        "silence - this pipeline fails intermittently, so a single window is "
        "noise. Use >=5 before trusting any before/after comparison.",
    )
    ap.add_argument("--label", default="run", help="name recorded in the result")
    ap.add_argument("--save", action="store_true", help="persist result JSON")
    ap.add_argument("--compare", help="baseline JSON to diff against")
    args = ap.parse_args()

    tmp = None
    try:
        if args.source == "file":
            if not args.path:
                print("--path is required with --source file", file=sys.stderr)
                return 2
            wav = Path(args.path)
            meta = {"source": "file", "url": str(wav)}
        elif args.source == "control":
            tmp = Path(tempfile.mkdtemp()) / "control.wav"
            meta = capture_control(args.seconds, tmp)
            wav = tmp
        else:
            tmp = Path(tempfile.mkdtemp()) / "cap.wav"
            meta = capture(args.source, args.seconds, tmp)
            wav = tmp

        metrics = analyse(wav)

        if args.with_control and args.source != "control":
            ctl_tmp = Path(tempfile.mkdtemp()) / "control.wav"
            try:
                capture_control(args.seconds, ctl_tmp)
                ctl = analyse(ctl_tmp)
                metrics["control_clicks_per_sec"] = ctl["clicks_per_sec"]
                metrics["clicks_excess_vs_control"] = round(
                    metrics["clicks_per_sec"] - ctl["clicks_per_sec"], 3
                )
            except Exception as exc:
                metrics["control_error"] = str(exc)
            finally:
                if ctl_tmp.exists():
                    try:
                        ctl_tmp.unlink()
                        ctl_tmp.parent.rmdir()
                    except OSError:
                        pass
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2
    finally:
        if tmp and tmp.exists():
            try:
                tmp.unlink()
                tmp.parent.rmdir()
            except OSError:
                pass

    # Repeat captures: this pipeline's defects come and go, so aggregate.
    if args.repeat > 1 and args.source in ("twitch", "youtube"):
        import statistics

        runs = [metrics]
        for _ in range(args.repeat - 1):
            rep_tmp = Path(tempfile.mkdtemp()) / "cap.wav"
            try:
                capture(args.source, args.seconds, rep_tmp)
                runs.append(analyse(rep_tmp))
            except Exception:
                continue
            finally:
                if rep_tmp.exists():
                    try:
                        rep_tmp.unlink()
                        rep_tmp.parent.rmdir()
                    except OSError:
                        pass
        agg = {"captures": len(runs)}
        for key in ("clicks_per_sec", "silence_pct", "longest_gap_ms"):
            vals = [r[key] for r in runs if key in r]
            if vals:
                agg[f"{key}_median"] = round(statistics.median(vals), 3)
                agg[f"{key}_worst"] = round(max(vals), 3)
        metrics["aggregate"] = agg
        # Gate on the WORST window: an intermittent 2.6s dropout is exactly the
        # failure a median would hide, and it is what a listener notices.
        for key in ("silence_pct", "longest_gap_ms"):
            if f"{key}_worst" in agg:
                metrics[key] = agg[f"{key}_worst"]

    metrics["encoder_fill_percent"] = encoder_fill_percent()
    ok, fails = verdict(metrics)
    result = {
        "label": args.label,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **meta,
        "metrics": metrics,
        "gates": GATES,
        "pass": ok,
        "failures": fails,
    }

    if args.compare:
        try:
            base = json.loads(Path(args.compare).read_text())
            bm = base.get("metrics", {})
            result["delta_vs_baseline"] = {
                k: round(metrics[k] - bm[k], 3)
                for k in ("clicks_per_sec", "silence_pct", "longest_gap_ms")
                if k in bm and isinstance(metrics.get(k), (int, float))
            }
            result["baseline_label"] = base.get("label")
        except Exception as exc:
            result["compare_error"] = str(exc)

    print(json.dumps(result, indent=2))

    if args.save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"{args.label}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        out.write_text(json.dumps(result, indent=2))
        print(f"\nsaved {out}", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
