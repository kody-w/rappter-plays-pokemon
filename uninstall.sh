#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
RUNTIME_DIR="${HOME}/.openrappter/pokemon-red"
PURGE=0

while (($#)); do
  case "$1" in
    --purge-data)
      PURGE=1
      shift
      ;;
    --runtime-dir)
      (($# >= 2)) || { printf 'error: --runtime-dir requires a path\n' >&2; exit 1; }
      RUNTIME_DIR="$2"
      shift 2
      ;;
    *)
      printf 'error: unknown option: %s\n' "$1" >&2
      exit 1
      ;;
  esac
done

if [[ -x "$VENV/bin/python" ]]; then
  "$VENV/bin/python" -m rappter_plays_pokemon.cli \
    stop --runtime-dir "$RUNTIME_DIR" >/dev/null 2>&1 || true
fi

if ((PURGE)); then
  PYTHON="$(command -v python3 || true)"
  [[ -n "$PYTHON" ]] || {
    printf 'error: Python is required to validate the purge path\n' >&2
    exit 1
  }
  RUNTIME_DIR="$("$PYTHON" -c \
    'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' \
    "$RUNTIME_DIR")"
  case "$RUNTIME_DIR" in
    "/"|"${HOME}"|"$ROOT")
      printf 'error: refusing unsafe runtime directory: %s\n' "$RUNTIME_DIR" >&2
      exit 1
      ;;
  esac
  if [[ -d "$RUNTIME_DIR" ]]; then
    "$PYTHON" - "$RUNTIME_DIR/runtime-owner.json" <<'PY'
import json
import sys
from pathlib import Path

marker = Path(sys.argv[1])
try:
    value = json.loads(marker.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    raise SystemExit(
        "error: refusing to purge a directory without a valid runtime-owner.json"
    )
if value.get("product") != "rappter-plays-pokemon":
    raise SystemExit("error: runtime ownership marker does not match this project")
PY
  fi
fi

if [[ "$VENV" == "$ROOT/.venv" && -d "$VENV" ]]; then
  rm -rf -- "$VENV"
fi

if ((PURGE)); then
  if [[ -d "$RUNTIME_DIR" ]]; then
    rm -rf -- "$RUNTIME_DIR"
  fi
  printf 'Removed environment and explicitly requested local Pokemon data.\n'
else
  printf 'Removed environment. Preserved saves and recordings in %s\n' "$RUNTIME_DIR"
fi
