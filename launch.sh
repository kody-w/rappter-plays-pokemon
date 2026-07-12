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

"$VENV/bin/python" -m rappter_plays_pokemon.install_agent \
  --source "$ROOT/pokemon_agent.py" >/dev/null
exec "$VENV/bin/python" -m rappter_plays_pokemon.cli "$@"
