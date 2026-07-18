"""Convert opt-in YouTube Top Chat ballots into one private route advisory."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - the supported runtime is macOS
    fcntl = None


SCHEMA_VERSION = 1
DEFAULT_RUNTIME_DIR = Path.home() / ".openrappter" / "pokemon-red"
DEFAULT_STATE_DIR = Path.home() / ".openrappter" / "youtube-chat"
ADVISORY_NAME = "youtube-chat-advisory.json"
STATUS_NAME = "status.json"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
HINT_RE = re.compile(r"^!hint (up|down|left|right)$", re.ASCII)
DIRECTIONS = ("up", "down", "left", "right")
MAX_RAW_CHAT_BYTES = 4 * 1024 * 1024
MAX_RAW_LINE_BYTES = 1024 * 1024
MAX_RENDERER_NODES = 20000
MAX_SEEN_EVENTS = 4096
BALLOT_TTL_SECONDS = 90
ADVISORY_TTL_SECONDS = 45
AUTHOR_CHANGE_COOLDOWN_SECONDS = 15
MIN_DISTINCT_VOTERS = 2
DEFAULT_POLL_SECONDS = 30
MAX_ADVISORY_BYTES = 2048


class ChatBridgeError(RuntimeError):
    """Raised for bounded collector or publication failures."""


@dataclass(frozen=True)
class ChatVote:
    event_token: str
    author_token: str
    direction: str
    observed_at: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hint(text: Any) -> str | None:
    if not isinstance(text, str):
        return None
    match = HINT_RE.fullmatch(text)
    return match.group(1) if match else None


def _renderer_text(renderer: dict[str, Any]) -> str | None:
    message = renderer.get("message")
    if not isinstance(message, dict):
        return None
    runs = message.get("runs")
    if not isinstance(runs, list) or not runs:
        return None
    text: list[str] = []
    for run in runs:
        if not isinstance(run, dict) or set(run) != {"text"}:
            return None
        value = run.get("text")
        if not isinstance(value, str):
            return None
        text.append(value)
    return "".join(text)


def _text_renderers(value: Any) -> Iterable[dict[str, Any]]:
    stack = [value]
    visited = 0
    while stack:
        current = stack.pop()
        visited += 1
        if visited > MAX_RENDERER_NODES:
            raise ChatBridgeError("live_chat_structure_limit")
        if isinstance(current, dict):
            renderer = current.get("liveChatTextMessageRenderer")
            if isinstance(renderer, dict):
                yield renderer
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def extract_votes(
    payload: bytes,
    *,
    author_key: bytes,
    now: datetime | None = None,
) -> list[ChatVote]:
    if len(payload) > MAX_RAW_CHAT_BYTES:
        raise ChatBridgeError("live_chat_payload_too_large")
    current = now or utc_now()
    votes: list[ChatVote] = []
    for raw_line in payload.splitlines():
        if not raw_line:
            continue
        if len(raw_line) > MAX_RAW_LINE_BYTES:
            continue
        try:
            value = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for renderer in _text_renderers(value):
            direction = canonical_hint(_renderer_text(renderer))
            message_id = renderer.get("id")
            author_id = renderer.get("authorExternalChannelId")
            timestamp_usec = renderer.get("timestampUsec")
            if (
                direction is None
                or not isinstance(message_id, str)
                or not 1 <= len(message_id) <= 256
                or not isinstance(author_id, str)
                or not 1 <= len(author_id) <= 256
                or not isinstance(timestamp_usec, str)
                or not timestamp_usec.isdigit()
            ):
                continue
            observed_at = datetime.fromtimestamp(
                int(timestamp_usec) / 1_000_000,
                tz=timezone.utc,
            )
            age = (current - observed_at).total_seconds()
            if not -5 <= age <= BALLOT_TTL_SECONDS:
                continue
            votes.append(
                ChatVote(
                    event_token=hmac.new(
                        author_key,
                        message_id.encode("utf-8"),
                        hashlib.sha256,
                    ).hexdigest(),
                    author_token=hmac.new(
                        author_key,
                        author_id.encode("utf-8"),
                        hashlib.sha256,
                    ).hexdigest(),
                    direction=direction,
                    observed_at=observed_at,
                )
            )
    votes.sort(key=lambda vote: (vote.observed_at, vote.event_token))
    return votes


class HintAccumulator:
    def __init__(self):
        self.seen_order: deque[str] = deque()
        self.seen: set[str] = set()
        self.ballots: dict[str, tuple[str, datetime]] = {}

    def add(self, votes: Iterable[ChatVote], *, now: datetime | None = None) -> None:
        current = now or utc_now()
        self._prune(current)
        for vote in votes:
            if vote.event_token in self.seen:
                continue
            self.seen.add(vote.event_token)
            self.seen_order.append(vote.event_token)
            while len(self.seen_order) > MAX_SEEN_EVENTS:
                self.seen.discard(self.seen_order.popleft())
            previous = self.ballots.get(vote.author_token)
            if previous is not None:
                previous_direction, previous_at = previous
                if previous_direction == vote.direction:
                    if vote.observed_at > previous_at:
                        self.ballots[vote.author_token] = (
                            vote.direction,
                            vote.observed_at,
                        )
                    continue
                if (
                    vote.observed_at - previous_at
                ).total_seconds() < AUTHOR_CHANGE_COOLDOWN_SECONDS:
                    continue
            self.ballots[vote.author_token] = (
                vote.direction,
                vote.observed_at,
            )
        self._prune(current)

    def _prune(self, now: datetime) -> None:
        stale = [
            author
            for author, (_, observed_at) in self.ballots.items()
            if (now - observed_at).total_seconds() > BALLOT_TTL_SECONDS
        ]
        for author in stale:
            self.ballots.pop(author, None)

    def snapshot(
        self,
        *,
        now: datetime | None = None,
    ) -> tuple[str, str | None, datetime | None]:
        current = now or utc_now()
        self._prune(current)
        if len(self.ballots) < MIN_DISTINCT_VOTERS:
            return ("waiting", None, None)
        counts = {direction: 0 for direction in DIRECTIONS}
        newest: dict[str, datetime] = {}
        for direction, observed_at in self.ballots.values():
            counts[direction] += 1
            newest[direction] = max(newest.get(direction, observed_at), observed_at)
        ranked = sorted(
            DIRECTIONS,
            key=lambda direction: (-counts[direction], DIRECTIONS.index(direction)),
        )
        winner = ranked[0]
        support = counts[winner]
        total = sum(counts.values())
        if support < MIN_DISTINCT_VOTERS or support * 2 <= total:
            return ("mixed", None, None)
        return ("eligible", winner, newest[winner])


def advisory_document(
    *,
    video_id: str,
    sequence: int,
    state: str,
    direction: str | None,
    observed_at: datetime | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or utc_now()
    advisory = None
    if state == "eligible" and direction in DIRECTIONS and observed_at is not None:
        advisory = {
            "kind": "overworld_direction",
            "direction": direction,
            "observed_at": utc_text(observed_at),
        }
    value = {
        "schema_version": SCHEMA_VERSION,
        "source": "youtube-top-chat",
        "video_id": video_id,
        "sequence": sequence,
        "generated_at": utc_text(current),
        "expires_at": utc_text(current + timedelta(seconds=ADVISORY_TTL_SECONDS)),
        "state": state,
        "advisory": advisory,
    }
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(payload) > MAX_ADVISORY_BYTES:
        raise ChatBridgeError("advisory_size_limit")
    return value


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    payload = (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class YtDlpSampler:
    def __init__(self, state_dir: Path, video_id: str):
        executable = shutil.which("yt-dlp")
        if executable is None:
            raise ChatBridgeError("yt_dlp_unavailable")
        if not VIDEO_ID_RE.fullmatch(video_id):
            raise ChatBridgeError("invalid_video_id")
        self.executable = executable
        self.state_dir = state_dir.expanduser().resolve()
        self.video_id = video_id
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)
        self.output = self.state_dir / "chat-sample.live_chat.json"

    def _cleanup(self) -> None:
        for candidate in self.state_dir.glob("chat-sample.live_chat.json*"):
            try:
                metadata = candidate.lstat()
            except OSError:
                continue
            if stat.S_ISREG(metadata.st_mode) or candidate.is_symlink():
                candidate.unlink(missing_ok=True)

    def sample(self) -> bytes:
        self._cleanup()
        command = [
            self.executable,
            "--ignore-config",
            "--no-cache-dir",
            "--quiet",
            "--no-warnings",
            "--no-progress",
            "--no-playlist",
            "--skip-download",
            "--write-subs",
            "--sub-langs",
            "live_chat",
            "--sub-format",
            "json",
            "--force-overwrites",
            "--socket-timeout",
            "15",
            "--retries",
            "2",
            "--fragment-retries",
            "2",
            "--test",
            "--output",
            str(self.state_dir / "chat-sample.%(ext)s"),
            f"https://www.youtube.com/watch?v={self.video_id}",
        ]
        environment = {
            "HOME": str(self.state_dir),
            "PATH": os.environ.get("PATH", ""),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", ""),
            "TMPDIR": str(self.state_dir),
        }
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
                timeout=60,
                check=False,
            )
            if result.returncode:
                raise ChatBridgeError("yt_dlp_failed")
            metadata = self.output.lstat()
            if (
                self.output.is_symlink()
                or not stat.S_ISREG(metadata.st_mode)
                or not 0 <= metadata.st_size <= MAX_RAW_CHAT_BYTES
            ):
                raise ChatBridgeError("yt_dlp_output_invalid")
            return self.output.read_bytes()
        except subprocess.TimeoutExpired as error:
            raise ChatBridgeError("yt_dlp_timeout") from error
        except OSError as error:
            raise ChatBridgeError("yt_dlp_io_error") from error
        finally:
            self._cleanup()


class ChatBridge:
    def __init__(
        self,
        *,
        video_id: str,
        runtime_dir: Path,
        state_dir: Path,
        poll_seconds: int,
    ):
        if not VIDEO_ID_RE.fullmatch(video_id):
            raise ChatBridgeError("invalid_video_id")
        if not 10 <= poll_seconds <= 300:
            raise ChatBridgeError("poll_seconds_out_of_range")
        self.video_id = video_id
        self.runtime_dir = runtime_dir.expanduser().resolve()
        self.state_dir = state_dir.expanduser().resolve()
        self.poll_seconds = poll_seconds
        self.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_dir, 0o700)
        self.sampler = YtDlpSampler(self.state_dir, video_id)
        self.accumulator = HintAccumulator()
        self.author_key = secrets.token_bytes(32)
        self.sequence = self._previous_sequence()
        self.stop_event = threading.Event()
        self.failures = 0

    def _previous_sequence(self) -> int:
        path = self.runtime_dir / ADVISORY_NAME
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            sequence = value.get("sequence")
            return sequence if isinstance(sequence, int) and sequence >= 0 else 0
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            return 0

    def stop(self, *_: object) -> None:
        self.stop_event.set()

    def poll(self) -> dict[str, Any]:
        payload = self.sampler.sample()
        now = utc_now()
        votes = extract_votes(payload, author_key=self.author_key, now=now)
        self.accumulator.add(votes, now=now)
        state, direction, observed_at = self.accumulator.snapshot(now=now)
        self.sequence += 1
        document = advisory_document(
            video_id=self.video_id,
            sequence=self.sequence,
            state=state,
            direction=direction,
            observed_at=observed_at,
            now=now,
        )
        atomic_write_json(self.runtime_dir / ADVISORY_NAME, document)
        self.failures = 0
        self._write_status(
            state="ready",
            advisory_state=state,
            error_code=None,
        )
        return {
            "status": "success",
            "state": state,
            "advisory": direction is not None,
            "sequence": self.sequence,
        }

    def _write_status(
        self,
        *,
        state: str,
        advisory_state: str | None,
        error_code: str | None,
    ) -> None:
        atomic_write_json(
            self.state_dir / STATUS_NAME,
            {
                "schema_version": SCHEMA_VERSION,
                "running": not self.stop_event.is_set(),
                "state": state,
                "video_id": self.video_id,
                "advisory_state": advisory_state,
                "failures": self.failures,
                "error_code": error_code,
                "updated_at": utc_text(utc_now()),
            },
        )

    def watch(self) -> None:
        backoff = self.poll_seconds
        while not self.stop_event.is_set():
            try:
                result = self.poll()
                print(json.dumps(result, sort_keys=True), flush=True)
                backoff = self.poll_seconds
            except ChatBridgeError as error:
                self.failures += 1
                code = str(error)
                self._write_status(
                    state="degraded",
                    advisory_state=None,
                    error_code=code,
                )
                print(
                    json.dumps(
                        {
                            "status": "error",
                            "error_code": code,
                            "failures": self.failures,
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                backoff = min(300, max(self.poll_seconds, backoff * 2))
            self.stop_event.wait(backoff)
        self._write_status(
            state="stopped",
            advisory_state=None,
            error_code=None,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish strict opt-in YouTube chat route advisories"
    )
    parser.add_argument("action", choices=("once", "watch"), nargs="?", default="watch")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    return parser


def run(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    old_umask = os.umask(0o077)
    try:
        bridge = ChatBridge(
            video_id=args.video_id,
            runtime_dir=args.runtime_dir,
            state_dir=args.state_dir,
            poll_seconds=args.poll_seconds,
        )
        lock_path = bridge.state_dir / "bridge.lock"
        with lock_path.open("a+", encoding="utf-8") as lock:
            os.chmod(lock_path, 0o600)
            if fcntl is not None:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ChatBridgeError("bridge_already_running") from error
            signal.signal(signal.SIGINT, bridge.stop)
            signal.signal(signal.SIGTERM, bridge.stop)
            if args.action == "once":
                return bridge.poll()
            bridge.watch()
            return {"status": "success", "state": "stopped"}
    finally:
        os.umask(old_umask)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        result = run(argv)
    except (ChatBridgeError, OSError) as error:
        result = {"status": "error", "error_code": str(error)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
