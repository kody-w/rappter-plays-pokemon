#!/usr/bin/env python3
"""Push the live Game Boy frames to an RTMP ingest (YouTube Live).

Reads the kite frame file the agent already writes at ~10 fps, deduplicates
by sequence, and pipes PNG frames into ffmpeg, which upscales with
nearest-neighbor (crisp pixels), adds the silent audio track YouTube
requires, and publishes to the given RTMP URL.

Usage:
  python3 scripts/stream_to_youtube.py --key-file ~/.openrappter/pokemon-red/rtmp-key.txt
  python3 scripts/stream_to_youtube.py --rtmp rtmp://a.rtmp.youtube.com/live2/xxxx-xxxx
  python3 scripts/stream_to_youtube.py --key-file key.txt --test-output /tmp/test.flv

The stream key is read from --key-file (or the RPP_RTMP_KEY environment
variable) and appended to --ingest. It is never logged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_FRAME_FILE = Path(
    "~/.openrappter/pokemon-red/kite-frame.json"
).expanduser()
DEFAULT_INGEST = "rtmp://a.rtmp.youtube.com/live2"
FRAME_RATE = 10
STALL_EXIT_SECONDS = 60


def read_frame(path: Path, last_sequence: int) -> tuple[int, bytes] | None:
    """Return the newest frame using the metadata file's sequence + sha256.

    latest.png is replaced atomically ~10x/second; the sibling metadata file
    carries the digest, so a read that races a replacement is detected and
    simply retried on the next tick.
    """
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        sequence = int(value["sequence"])
        if sequence <= last_sequence:
            return None
        png = (path.parent / "latest.png").read_bytes()
        if not png.startswith(b"\x89PNG"):
            return None
        if hashlib.sha256(png).hexdigest() != value.get("sha256"):
            return None
        return sequence, png
    except (OSError, ValueError, KeyError, TypeError):
        return None


def resolve_target(args: argparse.Namespace) -> str:
    if args.rtmp:
        return args.rtmp
    key = os.environ.get("RPP_RTMP_KEY", "")
    if args.key_file:
        key = Path(args.key_file).expanduser().read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit(
            "error: provide --rtmp, --key-file, or RPP_RTMP_KEY with the stream key"
        )
    return f"{args.ingest.rstrip('/')}/{key}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame-file", type=Path, default=DEFAULT_FRAME_FILE)
    parser.add_argument("--ingest", default=DEFAULT_INGEST)
    parser.add_argument("--rtmp", help="complete RTMP URL including stream key")
    parser.add_argument("--key-file", help="file containing only the stream key")
    parser.add_argument(
        "--test-output",
        help="write to this local file instead of streaming (pipeline test)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="stop after this many seconds (0 = run until interrupted)",
    )
    args = parser.parse_args()

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("error: ffmpeg is required (brew install ffmpeg)")
    if not args.frame_file.is_file():
        raise SystemExit(f"error: no frame file at {args.frame_file} — is the agent running with --livestream?")

    target = args.test_output or resolve_target(args)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "warning",
        "-stats",
        "-f", "image2pipe",
        "-framerate", str(FRAME_RATE),
        "-i", "-",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=stereo",
        "-vf", "scale=640:576:flags=neighbor,format=yuv420p",
        "-r", "30",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-tune", "zerolatency",
        "-b:v", "1500k",
        "-maxrate", "1500k",
        "-bufsize", "3000k",
        "-g", "60",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        "-f", "flv",
        target,
    ]
    if args.test_output:
        command.insert(1, "-y")
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert process.stdin is not None
    print(
        "streaming"
        + (" (pipeline test)" if args.test_output else " to RTMP ingest"),
        file=sys.stderr,
    )

    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))

    started = time.monotonic()
    last_sequence = -1
    last_frame: bytes | None = None
    last_fresh_at = time.monotonic()
    next_tick = time.monotonic()
    sent = 0
    try:
        while not stop["flag"]:
            if args.duration and time.monotonic() - started >= args.duration:
                break
            fresh = read_frame(args.frame_file, last_sequence)
            if fresh:
                last_sequence, last_frame = fresh
                last_fresh_at = time.monotonic()
            elif time.monotonic() - last_fresh_at > STALL_EXIT_SECONDS:
                print("error: frame source stalled; exiting", file=sys.stderr)
                break
            if last_frame:
                try:
                    process.stdin.write(last_frame)
                except BrokenPipeError:
                    print("error: ffmpeg exited", file=sys.stderr)
                    break
                sent += 1
            next_tick += 1.0 / FRAME_RATE
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            else:
                next_tick = time.monotonic()
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    print(f"frames piped: {sent}", file=sys.stderr)
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
