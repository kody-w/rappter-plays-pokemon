#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
OPENRAPPTER_REF="${OPENRAPPTER_REF:-444feeca3f5c05c9742646e1dfd35749d007f580}"
OPENRAPPTER_SOURCE="${OPENRAPPTER_SOURCE:-}"
ROM=""
SETUP_ONLY=0
LAUNCH_ARGS=()

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  fail "this launcher currently supports macOS only"
fi

while (($#)); do
  case "$1" in
    --rom)
      (($# >= 2)) || fail "--rom requires a path"
      ROM="$2"
      shift 2
      ;;
    --openrappter-source)
      (($# >= 2)) || fail "--openrappter-source requires a checkout path"
      OPENRAPPTER_SOURCE="$2"
      shift 2
      ;;
    --setup-only)
      SETUP_ONLY=1
      shift
      ;;
    --)
      shift
      LAUNCH_ARGS+=("$@")
      break
      ;;
    *)
      LAUNCH_ARGS+=("$1")
      shift
      ;;
  esac
done

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
    "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
[[ -n "$PYTHON" ]] || fail "Python 3.11+ is required"
command -v git >/dev/null 2>&1 || fail "git is required"
command -v ffmpeg >/dev/null 2>&1 ||
  fail "ffmpeg is required; install it with Homebrew: brew install ffmpeg"

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --disable-pip-version-check --quiet \
  --upgrade "pip>=24,<27"

if [[ -n "$OPENRAPPTER_SOURCE" ]]; then
  OPENRAPPTER_SOURCE="$(cd "$OPENRAPPTER_SOURCE" && pwd)"
  if [[ -f "$OPENRAPPTER_SOURCE/python/pyproject.toml" ]]; then
    OPENRAPPTER_PACKAGE="$OPENRAPPTER_SOURCE/python"
  elif [[ -f "$OPENRAPPTER_SOURCE/pyproject.toml" ]]; then
    OPENRAPPTER_PACKAGE="$OPENRAPPTER_SOURCE"
  else
    fail "OpenRappter checkout has no Python pyproject.toml"
  fi
  "$VENV/bin/python" -m pip install --disable-pip-version-check --quiet \
    "$OPENRAPPTER_PACKAGE"
else
  "$VENV/bin/python" -m pip install --disable-pip-version-check --quiet \
    "git+https://github.com/kody-w/openrappter.git@${OPENRAPPTER_REF}#subdirectory=python"
fi

"$VENV/bin/python" -m pip install --disable-pip-version-check --quiet \
  -e "$ROOT[runtime]"
"$VENV/bin/python" -m rappter_plays_pokemon.install_agent \
  --source "$ROOT/pokemon_agent.py"
"$VENV/bin/python" -m copilot download-runtime
"$VENV/bin/python" -c \
  'from openrappter.agents.pokemon_agent import PokemonAgent; assert PokemonAgent().name == "Pokemon"'

if ((SETUP_ONLY)); then
  printf 'Setup complete. Start with: ./launch.sh --rom "/path/to/Pokemon Red.gb"\n'
  exit 0
fi

[[ -n "$ROM" ]] || fail "--rom is required unless --setup-only is used"
exec "$ROOT/launch.sh" start --rom "$ROM" "${LAUNCH_ARGS[@]}"
