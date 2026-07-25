#!/usr/bin/env bash
# Private read-only operator dashboard, published to your tailnet.
#
# Watch-only by construction: it reads status.json and serves GET/HEAD only.
# The tailnet supplies identity and transport, so there is no pairing step and
# nothing to re-scan after a restart.
#
# Usage:
#   ./ops.sh                 # serve on loopback and publish over the tailnet
#   ./ops.sh --no-publish    # loopback only
#   ./ops.sh --once          # print one metrics document and exit
#   ./ops.sh --unpublish     # withdraw the tailnet route
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/.venv"
PORT="${RPP_OPS_PORT:-8787}"
TAILSCALE="${RPP_TAILSCALE:-$HOME/.local/bin/tailscale}"
TAILSCALE_SOCKET="${RPP_TAILSCALE_SOCKET:-$HOME/.local/share/tailscale-user/tailscaled.sock}"

if [[ ! -x "$VENV/bin/python" ]]; then
  printf 'error: run ./bootstrap.sh --setup-only first\n' >&2
  exit 1
fi

ts() {
  if [[ -S "$TAILSCALE_SOCKET" ]]; then
    "$TAILSCALE" --socket="$TAILSCALE_SOCKET" "$@"
  else
    "$TAILSCALE" "$@"
  fi
}

if [[ "${1:-}" == "--unpublish" ]]; then
  ts serve --http="$PORT" off
  printf 'tailnet route withdrawn\n'
  exit 0
fi

if [[ "${1:-}" == "--once" ]]; then
  exec "$VENV/bin/python" -m rappter_plays_pokemon.ops --once --port "$PORT"
fi

PUBLISH=1
[[ "${1:-}" == "--no-publish" ]] && PUBLISH=0

"$VENV/bin/python" -m rappter_plays_pokemon.ops --port "$PORT" &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

# The publish step is idempotent: re-running it replaces the existing route
# rather than stacking another one.
#
# Plain HTTP on the tailnet, not --https 443: the tailnet is already
# WireGuard-encrypted end to end, and `serve --https` blocks indefinitely
# provisioning a cert unless HTTPS Certificates are enabled for the tailnet.
# Turn that on in the admin console and this can become --https 443.
if [[ "$PUBLISH" == "1" ]]; then
  if ts serve --bg --http "$PORT" "http://127.0.0.1:$PORT" >/dev/null 2>&1; then
    HOSTNAME_FQDN="$(ts status --json | "$VENV/bin/python" -c \
      'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
    printf 'phone URL: http://%s:%s/\n' "$HOSTNAME_FQDN" "$PORT"
  else
    printf 'warning: tailscale serve failed; loopback only at http://127.0.0.1:%s/\n' \
      "$PORT" >&2
  fi
fi

wait "$SERVER_PID"
