# Running the 24/7 YouTube stream

This runbook takes a fresh Mac from `git clone` to an unattended
"Copilot Plays Pokémon Red" broadcast with the live overlay
(game screen + current goal, party HP, badges, Pokédex, play time).

**Permanent live URL:** <https://www.youtube.com/channel/UCz0Tfe07OAwnQR-fd3E1y4Q/live>

Nothing secret lives in this repository. Two private inputs come from the
stream operator directly:

- **the ROM** (`Pokemon Red.gb`) — never committed
- **the YouTube stream key** — never committed; kept in a local file

## One-time setup

```bash
git clone https://github.com/kody-w/rappter-plays-pokemon.git
cd rappter-plays-pokemon
./bootstrap.sh --setup-only          # venv + dependencies + Copilot runtime
./launch.sh provision-browser        # dedicated Chrome for Testing
brew install ffmpeg yt-dlp           # encoder + stream checks/crowd-hint bridge
(cd scripts/overlay && npm install && npx playwright install chromium)
```

Place the private inputs (ask the operator for both):

```bash
mkdir -p ~/.openrappter/pokemon-red
cp "/path/to/Pokemon Red.gb" ~/.openrappter/pokemon-red/Pokemon_Red.gb
umask 077 && printf '%s\n' 'STREAM-KEY-HERE' > ~/.openrappter/pokemon-red/rtmp-key.txt
```

In YouTube Studio → Go Live → stream settings, turn on **Enable
Auto-start** and **Enable Auto-stop** for the stream key. Without
auto-start, every encoder reconnect waits for a manual GO LIVE click —
with it, the broadcast publishes itself, which is what makes the stream
survive reboots unattended.

## Start everything

```bash
./launch.sh start --rom ~/.openrappter/pokemon-red/Pokemon_Red.gb --livestream
scripts/overlay/run_forever.sh       # stays in the foreground; use tmux/nohup
```

`run_forever.sh` waits for the agent's frame contract, runs the encoder
under `caffeinate` so the Mac never idles to sleep mid-broadcast, and
restarts the encoder if it ever exits. The permanent share link is the
channel's live URL (`https://www.youtube.com/channel/<CHANNEL-ID>/live`);
it survives restarts, unlike per-session P2P links.

## Self-healing layers

The unattended broadcast recovers without resetting game progress:

1. The Pokémon supervisor restarts a failed/stale player and resumes the newest
   valid checkpoint.
2. `stream_overlay.mjs` exits if Chromium capture stalls for 60 seconds,
   ffmpeg exits, or either audio/video pipe remains backpressured for 30
   seconds.
3. `run_forever.sh` waits ten seconds and starts a fresh encoder under
   `caffeinate`.
4. YouTube **Enable Auto-start** republishes the reconnected RTMP feed without
   a Studio click.

Run the watchdog detached:

```bash
nohup scripts/overlay/run_forever.sh \
  >> ~/.openrappter/pokemon-red/encoder.log 2>&1 &
```

This survives encoder, network, browser, and game-process failures. A full Mac
reboot still needs `run_forever.sh` launched at login (for example through a
user LaunchAgent); the game checkpoint and fixed YouTube URL survive that
reboot.

## Game audio

Emulation free-runs at real time, TPP-style: the world keeps ticking (music
playing, character idle) while the brain thinks, and heavy captures are
decimated or run off the tick thread so the loop fits the 60fps frame budget.

The agent emulates Game Boy sound (PyBoy `sound_emulated=True`) and writes
s16le 48 kHz stereo PCM into `~/.openrappter/pokemon-red/audio.fifo`. The
encoder paces that FIFO into ffmpeg against the wall clock and pads silence
for any gap, so agent stalls or restarts only mute the stream — they never
break it.

## Screenshot diagnostics and QR

The bottom-edge `TUNE1` watermark is intentionally low opacity. It makes a
single stream screenshot useful for diagnosing timing without distracting
viewers:

| Label | Meaning |
| --- | --- |
| `SYNC` | Audio/video encoder input-clock drift; near zero is healthiest |
| `DLY` | Intentional audio alignment delay applied by ffmpeg |
| `AUDIO` | Real game-audio share over the last ten seconds; the rest is padded silence |
| `SRC` | Age of the newest frame written by the game runtime |
| `SHOT` | Age of the newest Chromium screencast frame |
| `CAP` | Recent Chromium capture rate |
| `AI` / `EFF` | Last Copilot response latency and reasoning effort |
| `EMU` | Measured emulation speed relative to real time |
| `ENC` | Encoder state and current-process uptime |

The small **Scan · Learn More** QR remains a user-facing project link. It opens
the Pages introduction, live/catch-up links, and project explanation first.
Every 15 seconds the QR also refreshes a nonsecret tuning snapshot in its URL
fragment. The fragment is decoded locally by the Pages diagnostics section and
is not sent in the HTTP request. A viewer can optionally open a prefilled
GitHub issue draft containing those metrics, then review, edit, and attach a
screenshot before submitting; nothing is submitted automatically.

## Optional crowd route hints

The chat bridge is disabled unless the game starts with
`--youtube-chat-hints`. It reads credential-free YouTube **Top Chat** through
`yt-dlp` and accepts only exact opt-in direction ballots:

```text
!hint up
!hint down
!hint left
!hint right
```

Run the bridge independently:

```bash
mkdir -p ~/.openrappter/youtube-chat
chmod 700 ~/.openrappter/youtube-chat
nohup ./chat.sh watch --video-id CURRENT_VIDEO_ID \
  >> ~/.openrappter/youtube-chat/bridge.log 2>&1 &
```

Raw chat exists only in a short-lived mode-`0600` sample inside the bridge's
private mode-`0700` directory and is deleted after each poll. Message text,
names, channel IDs, avatars, payment status, and vote totals are never written
to the game advisory, logs, status, overlay, story archive, or model prompt.
The bridge requires at least two distinct recent viewers and a strict majority;
ties and contradictory directions produce no advisory.

Even an eligible direction reaches Copilot only after four decisions at the
same overworld coordinates, only if the adjacent collision tile is open, and
only once for that position. It is labeled an untrusted hypothesis that may be
ignored. The gameplay agent retains sole control of every button.

## Autonomous stuck research

`--stuck-web-research` enables an independent recovery path. Repeated failed
attempts and detected route cycles are persisted in bounded private navigation
memory. Once that deterministic evidence says the run is stuck, a separate
one-shot Copilot session receives the current screenshot and safe map context.
It has exactly one custom tool, restricted to Bulbapedia search and plaintext
extracts, and returns bounded source-cited route facts. A known authoritative
local route rule suppresses the search instead of risking contradictory web
guidance.

The gameplay session itself remains zero-tool. Research runs asynchronously,
is cached for 30 minutes, applies only near the same map coordinates, and is
presented as untrusted optional evidence. A failed search, malformed result,
network outage, stale location, or conflict with local game evidence is simply
ignored while gameplay continues.

One quirk: save-states recorded by builds without sound carry a suspended
audio counter. The first session resumed from such a state stays silent for
roughly eight minutes, then sound starts and the next checkpoint saves clean
values. This happens once per upgrade, not per restart.

## What survives a restart

- **Game progress** — the agent checkpoints PyBoy save-states
  automatically (about every ten minutes, plus milestones and shutdown)
  and resumes from the newest checkpoint by default. Stopping the agent,
  pulling new code, and starting again continues the same run.
- **The YouTube URL** — the channel live URL never changes. Each new
  broadcast gets a fresh watch id, but `/live` always points at it.
- **Not** the P2P spectator link: that rotates per agent session by
  design; the dashboard QR on the host page always shows the current one.

## Updating the machine

```bash
./launch.sh stop
git pull
./launch.sh start --rom ~/.openrappter/pokemon-red/Pokemon_Red.gb --livestream
```

The encoder loop notices the frame contract disappear and reappear and
reattaches on its own. Keep the resolution constant across encoder
restarts within one broadcast — YouTube locks the canvas at the first
frames it ingests; when changing resolution, end the broadcast first and
let auto-start open a fresh one.

## Health checks

```bash
./launch.sh status                   # game, brain, livestream state
tail -f nohup.out                    # encoder frame counter, if using nohup
yt-dlp -g "https://www.youtube.com/channel/UCz0Tfe07OAwnQR-fd3E1y4Q/live"  # errors when not live
```

## Publish the story so far

The story curator runs independently from both the game and encoder. It
publishes only a sanitized JSON timeline; local recordings, screenshots,
runtime paths, ROM data, and raw model output remain private.

```bash
./story.sh build
./story.sh publish \
  --youtube-video-id CURRENT_VIDEO_ID \
  --youtube-started-at UTC_BROADCAST_START
nohup ./story.sh watch --interval 600 \
  --youtube-video-id CURRENT_VIDEO_ID \
  --youtube-started-at UTC_BROADCAST_START \
  >> ~/.openrappter/pokemon-red/story-publisher.log 2>&1 &
```

The public player is
<https://kody-w.github.io/rappter-plays-pokemon/story/>. The publisher merges
new events with the existing `story-archive` branch so earlier chapters remain
available after local clip retention rotates their source manifests away. The
static theater reads its program from raw GitHub JSON and plays the
corresponding bounded segments from YouTube. GitHub never serves the gameplay
video bytes.
