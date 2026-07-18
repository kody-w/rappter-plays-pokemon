# Running the 24/7 YouTube stream

This runbook takes a fresh Mac from `git clone` to an unattended
"Copilot Plays Pokémon Red" broadcast with the live overlay
(game screen + current goal, party HP, badges, Pokédex, play time).

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
brew install ffmpeg yt-dlp           # encoder (yt-dlp optional, for checks)
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

## Game audio

Emulation free-runs at real time, TPP-style: the world keeps ticking (music
playing, character idle) while the brain thinks, and heavy captures are
decimated or run off the tick thread so the loop fits the 60fps frame budget.

The agent emulates Game Boy sound (PyBoy `sound_emulated=True`) and writes
s16le 48 kHz stereo PCM into `~/.openrappter/pokemon-red/audio.fifo`. The
encoder paces that FIFO into ffmpeg against the wall clock and pads silence
for any gap, so agent stalls or restarts only mute the stream — they never
break it.

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
yt-dlp -g "https://www.youtube.com/channel/<CHANNEL-ID>/live"  # errors when not live
```
