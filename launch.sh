#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf 'error: this launcher currently supports macOS only\n' >&2
  exit 1
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  printf 'error: run ./bootstrap.sh --setup-only first\n' >&2
  exit 1
fi

IFS=$'\t' read -r ACTION ACTIVE <<< "$(
  "$VENV/bin/python" -c \
    'import sys
from rappter_plays_pokemon.cli import launch_preflight
action, active = launch_preflight(sys.argv[1:])
print(f"{action}\t{int(active)}")' \
    "$@"
)"

if [[ "$ACTION" == "start" ]]; then
  if [[ "$ACTIVE" == "1" ]]; then
    printf '%s\n' \
      'error: refusing to replace the registered agent while a player is running' \
      'checkpoint, stop, wait for status to report stopped, then start again' >&2
    exit 1
  fi
  "$VENV/bin/python" -m rappter_plays_pokemon.install_agent \
    --source "$ROOT/pokemon_agent.py" >/dev/null
fi
exec "$VENV/bin/python" -m rappter_plays_pokemon.cli "$@"
