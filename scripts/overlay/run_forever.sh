#!/usr/bin/env bash
# Keep the overlay encoder alive indefinitely on an always-on Mac.
#
# Waits for the agent's frame contract to exist, runs the encoder under
# caffeinate so the machine never idles to sleep mid-broadcast, and restarts
# the encoder on any exit. Pair with YouTube's "Enable Auto-start/Auto-stop"
# stream-key setting so reconnects publish without a click.
#
# Usage: scripts/overlay/run_forever.sh [key-file]
set -u
cd "$(dirname "$0")"
KEY_FILE="${1:-$HOME/.openrappter/pokemon-red/rtmp-key.txt}"
RUNTIME_DIR="${RPP_RUNTIME_DIR:-$HOME/.openrappter/pokemon-red}"
OBS_MIRROR_URL="${RPP_OBS_MIRROR_URL-udp://127.0.0.1:23000?pkt_size=1316}"

if [ ! -f "$KEY_FILE" ]; then
  printf 'error: no stream key at %s\n' "$KEY_FILE" >&2
  exit 1
fi

while true; do
  until [ -f "$RUNTIME_DIR/latest.png" ]; do
    printf 'waiting for the agent frame contract in %s…\n' "$RUNTIME_DIR" >&2
    sleep 10
  done
  MIRROR_ARGS=()
  if [ -n "$OBS_MIRROR_URL" ]; then
    MIRROR_ARGS=(--mirror-url "$OBS_MIRROR_URL")
  fi
  caffeinate -i node stream_overlay.mjs \
    --key-file "$KEY_FILE" \
    --runtime-dir "$RUNTIME_DIR" \
    "${MIRROR_ARGS[@]}"
  printf 'encoder exited; restarting in 10s\n' >&2
  sleep 10
done
