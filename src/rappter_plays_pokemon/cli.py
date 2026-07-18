"""Command-line adapter for the registered Pokemon OpenRappter agent."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Sequence

ACTIONS = (
    "start",
    "status",
    "manual",
    "autonomy",
    "pause",
    "resume",
    "checkpoint",
    "press",
    "view",
    "host",
    "go-live",
    "share",
    "provision-browser",
    "stop",
)
BUTTONS = ("a", "b", "start", "select", "up", "down", "left", "right")
DEFAULT_RUNTIME_DIR = Path.home() / ".openrappter" / "pokemon-red"


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        value = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cannot read config {path}: {error}") from error
    if not isinstance(value, dict):
        raise RuntimeError("Config must contain one JSON object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch or control the Pokemon OpenRappter agent"
    )
    parser.add_argument("action", nargs="?", choices=ACTIONS, default="start")
    parser.add_argument("button", nargs="?", choices=BUTTONS)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--rom", dest="rom_path")
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        help="Local private state directory (default: ~/.openrappter/pokemon-red)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Authenticated loopback viewer port; 0 selects an available port",
    )
    livestream_group = parser.add_mutually_exclusive_group()
    livestream_group.add_argument(
        "--livestream",
        action="store_true",
        dest="livestream",
        help="Enable direct browser-to-browser video broadcasting",
    )
    livestream_group.add_argument(
        "--no-livestream",
        action="store_false",
        dest="livestream",
        help="Disable livestreaming configured in JSON",
    )
    parser.add_argument(
        "--spectator-port",
        type=int,
        help="Read-only LAN spectator page port; 0 selects an available port",
    )
    parser.add_argument(
        "--advertised-host",
        help="LAN hostname or IP placed in the spectator join link",
    )
    parser.add_argument(
        "--join-base",
        help="Compatible externally hosted HTTPS spectator page base",
    )
    parser.add_argument(
        "--livestream-host",
        choices=("kite", "local"),
        help="Pages kited twin (recommended) or legacy local browser host",
    )
    parser.add_argument(
        "--signaling",
        choices=("nostr", "peerjs"),
        help="Encrypted Nostr signaling (kite default) or legacy PeerJS",
    )
    parser.add_argument(
        "--browser-path",
        help="Dedicated Chrome/Chromium executable override",
    )
    parser.add_argument(
        "--host-base",
        help="HTTPS GitHub Pages kited-host base",
    )
    parser.add_argument("--bridge-startup-timeout", type=float)
    parser.add_argument(
        "--browser-cache",
        type=Path,
        help="Private Chrome-for-Testing cache for provision-browser",
    )
    parser.add_argument(
        "--max-viewers",
        type=int,
        help="P2P viewer fanout (default 5, hard limit 8)",
    )
    parser.add_argument("--clip-minutes", type=float)
    parser.add_argument("--model")
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "max"),
    )
    chat_group = parser.add_mutually_exclusive_group()
    chat_group.add_argument(
        "--youtube-chat-hints",
        action="store_true",
        dest="youtube_chat_hints",
    )
    chat_group.add_argument(
        "--no-youtube-chat-hints",
        action="store_false",
        dest="youtube_chat_hints",
    )
    research_group = parser.add_mutually_exclusive_group()
    research_group.add_argument(
        "--stuck-web-research",
        action="store_true",
        dest="stuck_web_research",
    )
    research_group.add_argument(
        "--no-stuck-web-research",
        action="store_false",
        dest="stuck_web_research",
    )
    parser.add_argument("--decision-timeout", type=int)
    parser.add_argument("--startup-timeout", type=float)
    parser.add_argument("--max-clips", type=int)
    parser.add_argument("--max-states", type=int)
    parser.add_argument("--max-storage-gb", type=float)
    parser.add_argument("--min-free-gb", type=float)
    parser.add_argument("--visible", action="store_true", default=None)
    parser.add_argument("--no-open-viewer", action="store_false", dest="open_viewer")
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    parser.set_defaults(
        open_viewer=None,
        resume=None,
        livestream=None,
        youtube_chat_hints=None,
        stuck_web_research=None,
    )
    return parser


def _configured(
    args: argparse.Namespace,
    config: dict[str, Any],
    name: str,
    default: Any = None,
) -> Any:
    argument = getattr(args, name, None)
    if argument is not None:
        return argument
    return config.get(name, default)


def agent_kwargs(args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    runtime = _configured(args, config, "runtime_dir", str(DEFAULT_RUNTIME_DIR))
    kwargs: dict[str, Any] = {
        "action": args.action,
        "runtime_dir": str(Path(str(runtime)).expanduser()),
    }
    if args.action == "press":
        if not args.button:
            raise RuntimeError("press requires a button")
        kwargs["button"] = args.button
    if args.action != "start":
        return kwargs

    livestream_host = _configured(
        args,
        config,
        "livestream_host",
        "kite",
    )
    signaling = _configured(args, config, "signaling")
    if signaling is None:
        signaling = "nostr" if livestream_host == "kite" else "peerjs"
    values = {
        "rom_path": _configured(
            args,
            config,
            "rom_path",
            os.environ.get("OPENRAPPTER_POKEMON_ROM"),
        ),
        "port": _configured(args, config, "port", 8765),
        "livestream": _configured(args, config, "livestream", False),
        "livestream_host": livestream_host,
        "signaling": signaling,
        "browser_path": _configured(
            args,
            config,
            "browser_path",
            os.environ.get("RPP_BROWSER_PATH")
            or os.environ.get("CHROME_PATH"),
        ),
        "host_base": _configured(
            args,
            config,
            "host_base",
            "https://kody-w.github.io/rappter-plays-pokemon/host/v2/",
        ),
        "bridge_startup_timeout": _configured(
            args,
            config,
            "bridge_startup_timeout",
            20,
        ),
        "spectator_port": _configured(args, config, "spectator_port", 8766),
        "advertised_host": _configured(args, config, "advertised_host"),
        "join_base": _configured(args, config, "join_base"),
        "max_viewers": _configured(args, config, "max_viewers", 5),
        "clip_minutes": _configured(args, config, "clip_minutes", 10),
        "model": _configured(args, config, "model", "gpt-5.6-sol"),
        "reasoning_effort": _configured(
            args,
            config,
            "reasoning_effort",
            "medium",
        ),
        "youtube_chat_hints": _configured(
            args,
            config,
            "youtube_chat_hints",
            False,
        ),
        "stuck_web_research": _configured(
            args,
            config,
            "stuck_web_research",
            False,
        ),
        "decision_timeout": _configured(args, config, "decision_timeout", 180),
        "startup_timeout": _configured(args, config, "startup_timeout", 180),
        "max_clips": _configured(args, config, "max_clips", 200),
        "max_states": _configured(args, config, "max_states", 256),
        "max_storage_gb": _configured(args, config, "max_storage_gb", 20),
        "min_free_gb": _configured(args, config, "min_free_gb", 2),
        "visible": _configured(args, config, "visible", False),
        "open_viewer": _configured(args, config, "open_viewer", True),
        "resume": _configured(args, config, "resume", True),
    }
    kwargs.update({key: value for key, value in values.items() if value is not None})
    return kwargs


def launch_preflight(argv: Sequence[str] | None = None) -> tuple[str, bool]:
    """Return the parsed action and whether installing would hot-swap a runner."""
    args = build_parser().parse_args(argv)
    if args.action != "start":
        return args.action, False
    config = load_config(args.config)
    runtime_dir = Path(agent_kwargs(args, config)["runtime_dir"]).expanduser()
    agent_running = False
    try:
        from openrappter.agents.pokemon_agent import PokemonAgent

        result = json.loads(
            PokemonAgent().perform(
                action="status",
                runtime_dir=runtime_dir,
            )
        )
        if isinstance(result, dict):
            agent_running = result.get("running") is True
    except (ImportError, json.JSONDecodeError, RuntimeError):
        pass
    if agent_running:
        return args.action, True
    try:
        status = json.loads(
            (runtime_dir / "status.json").read_text(encoding="utf-8")
        )
        pid = int(status.get("pid", 0))
        if pid > 1 and status.get("running") is True:
            os.kill(pid, 0)
            return args.action, True
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ProcessLookupError,
        PermissionError,
        OSError,
    ):
        pass
    try:
        supervisor = json.loads(
            (runtime_dir / "supervisor.json").read_text(encoding="utf-8")
        )
        supervisor_pid = int(supervisor.get("pid", 0))
        if supervisor_pid > 1 and supervisor.get("running") is True:
            os.kill(supervisor_pid, 0)
            return args.action, True
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ProcessLookupError,
        PermissionError,
        OSError,
    ):
        pass
    return args.action, False


def run(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any]]:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.action == "provision-browser":
            from rappter_plays_pokemon.chrome_for_testing import (
                default_cache_dir,
                provision_chrome_for_testing,
            )

            cache = args.browser_cache or default_cache_dir()
            try:
                browser = provision_chrome_for_testing(cache)
            except OSError as error:
                raise RuntimeError(
                    f"Cannot provision Chrome for Testing: {error}"
                ) from error
            result = {
                "status": "success",
                "message": "Chrome for Testing is ready",
                "browser_path": str(browser),
            }
            return 0, result
        kwargs = agent_kwargs(args, config)
        from openrappter.agents.pokemon_agent import PokemonAgent

        raw = PokemonAgent().perform(**kwargs)
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise RuntimeError("Pokemon agent returned a non-object response")
    except (ImportError, json.JSONDecodeError, RuntimeError) as error:
        result = {"status": "error", "message": str(error)}
    return (0 if result.get("status") == "success" else 1), result


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, result = run(argv)
    print(json.dumps(result, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
