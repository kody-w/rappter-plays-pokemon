# RAPPter Plays Pokémon

Run a real, single-file OpenRappter agent that lets GitHub Copilot autonomously
attempt a full playthrough of Pokémon Red in a local PyBoy emulator. It can
persist progress for long-running sessions, record segmented MP4 clips, expose
an authenticated local viewer, and hand control to you at any time.

> [!IMPORTANT]
> This repository is **ROM-free**. You must supply your own legally obtained
> Pokémon Red Game Boy (`.gb`) ROM. The project never downloads, searches for,
> copies, uploads, or distributes a ROM. Do not open an issue asking for one.

This is an experimental autonomous player. It attempts to reach the Hall of
Fame, but **it is not guaranteed to beat the game**.

## What you get

- **A RAPP agent, not a skill:** [`pokemon_agent.py`](pokemon_agent.py) contains
  the complete native `BasicAgent` contract, metadata, deterministic runtime,
  and `perform()` implementation.
- **GitHub Copilot SDK brain:** defaults to `gpt-5.6-sol` with
  `reasoning_effort="max"`.
- **Tool isolation:** the SDK session has zero tools, no skill/config discovery,
  no memory/session store, and receives only PNG screenshots as attachments.
- **Durable PyBoy runtime:** atomic checkpoints, cartridge RAM persistence,
  hash-checked resume, and supervised recovery after failures or stale
  heartbeats.
- **Local viewer and takeover:** authenticated browser session on
  `127.0.0.1`, strict same-origin controls, pause/resume, manual buttons, and
  return-to-autonomy.
- **Bounded recording:** local, rotating H.264 MP4 clips with manifests,
  retention limits, a disk budget, and a free-space reserve.
- **Local-only state:** ROM path, screenshots, saves, logs, and videos stay in a
  private local runtime directory.

## Prerequisites

The supported path is **macOS**. The launcher fails clearly on other platforms.

1. Python 3.11 or newer
2. `git`
3. [`ffmpeg`](https://ffmpeg.org/) (`brew install ffmpeg`)
4. A GitHub account with an active Copilot entitlement
5. GitHub Copilot CLI/SDK authentication already available to your user
6. Your own legally obtained Pokémon Red `.gb` ROM stored locally

The bootstrap installs a private `.venv`, a pinned OpenRappter revision,
`github-copilot-sdk>=1.0.6,<2`, and `PyBoy>=2.6.1,<3`. It does not install or
locate game content.

## Quickstart

```bash
git clone https://github.com/kody-w/rappter-plays-pokemon.git
cd rappter-plays-pokemon
./bootstrap.sh --rom "/absolute/path/to/your/Pokemon Red.gb"
```

That one bootstrap command creates the environment, installs OpenRappter and
runtime dependencies, atomically registers `pokemon_agent.py` in that isolated
OpenRappter installation, prepares the Copilot SDK runtime, launches the
supervisor, and opens the authenticated viewer.

Use an existing OpenRappter checkout instead:

```bash
./bootstrap.sh \
  --openrappter-source "/path/to/openrappter" \
  --rom "/absolute/path/to/your/Pokemon Red.gb"
```

Setup without launching:

```bash
./bootstrap.sh --setup-only
```

## Commands

All commands operate on the default private runtime directory,
`~/.openrappter/pokemon-red`.

```bash
./launch.sh --rom "/absolute/path/to/your/Pokemon Red.gb"  # start/resume
./launch.sh status                                         # progress
./launch.sh view                                           # authenticated viewer
./launch.sh pause                                          # freeze emulation
./launch.sh resume                                         # resume prior mode
./launch.sh manual                                         # take control
./launch.sh press up                                       # up/down/left/right
./launch.sh press a                                        # a/b/start/select
./launch.sh autonomy                                       # return control to Copilot
./launch.sh checkpoint                                     # save + rotate clip
./launch.sh stop                                           # checkpoint and stop cleanly
```

Useful start options:

```bash
./launch.sh start \
  --rom "/absolute/path/to/your/Pokemon Red.gb" \
  --clip-minutes 10 \
  --max-clips 200 \
  --max-states 256 \
  --max-storage-gb 20 \
  --min-free-gb 2 \
  --port 8765
```

`--visible` also opens PyBoy's native SDL window. The browser viewer works
without it. `--no-open-viewer` prevents automatic browser launch.
`--no-resume` deliberately starts without loading a checkpoint; it does not
delete existing saves.

To use a config file, copy the safe template outside version control, fill in
your local ROM path, and pass it explicitly:

```bash
cp config.example.json config.json
./launch.sh start --config config.json
```

## Runtime files and recording

Default private state lives under `~/.openrappter/pokemon-red/` with mode `0700`;
files containing local state are mode `0600`.

| Path | Purpose |
| --- | --- |
| `clips/*.mp4` | Completed local recording segments |
| `clips/*.json` | Clip hashes, timing, and game-state manifests |
| `states/*.state` | Atomic PyBoy checkpoints |
| `states/*.json` | Checkpoint hash and matching-ROM manifest |
| `pokemon-red.ram` | Atomic cartridge RAM |
| `screens/` | Bounded decision screenshots |
| `brain.json` | Recent decisions and progress context |
| `player.log` | Local supervisor/player diagnostics |
| `runtime-owner.json` | Safety marker required for explicit purge |

The original ROM remains at the path you supplied. It is not copied into the
runtime directory. On resume, the runner verifies checkpoint hashes and the ROM
hash, skips corrupt or mismatched checkpoints, and falls back to the newest
valid state.

The defaults retain up to 200 generated clips and 256 states, cap generated
artifacts at 20 GiB, and preserve 2 GiB of free disk space. Milestone artifacts
are protected where possible; if nothing safe can be pruned, recording suspends
instead of consuming the reserve. Unknown/user-created files are never selected
for retention deletion.

## Architecture

```mermaid
flowchart LR
    U[launch.sh / OpenRappter] --> A[PokemonAgent.perform]
    A --> S[Supervisor]
    S -->|restart on failure or stale heartbeat| R[PokemonRunner]
    R --> P[PyBoy]
    R --> F[ffmpeg segment recorder]
    R --> V[127.0.0.1 authenticated viewer]
    R --> B[CopilotBrain]
    B -->|PNG screenshot only| C[GitHub Copilot SDK<br/>gpt-5.6-sol / max]
    C -->|JSON buttons, zero tools| R
    R --> L[Local private states, RAM, manifests]
```

The emulator pauses while each model decision is pending. A generation counter
discards stale AI decisions after manual takeover. The supervisor distinguishes
intentional stops from failures, restarts failed children with exponential
backoff, detects stale ready/startup heartbeats, and opens a restart circuit
after repeated crashes.

## Privacy and security model

- **No game data in Git:** `.gitignore` blocks ROMs, saves, video, screenshots,
  logs, and runtime state. CI uses generated synthetic bytes and mocks only.
- **Explicit ROM only:** the agent accepts the path argument, environment
  variable, or private runtime config; it does not scan Downloads, Documents,
  Spotlight, or the network.
- **Inference isolation:** `CopilotClient(mode="empty")`; `available_tools=[]`;
  custom instructions, skills, config discovery, memory, telemetry, and session
  persistence are disabled. The only SDK attachment is the current PNG frame.
  ROMs, RAM, save states, clips, and logs are never attached.
- **Viewer isolation:** the server binds only to `127.0.0.1`. A random,
  process-local bootstrap token establishes an HttpOnly, SameSite=Strict cookie.
  API, frame, script, stylesheet, and clip requests require that cookie.
  Mutating requests additionally require an exact loopback Origin and JSON
  content type. Host checks mitigate DNS rebinding.
- **Local secrets:** the short-lived viewer bootstrap token is written only to
  a mode-`0600` runtime file and removed on clean shutdown. Never paste a viewer
  URL into chat, logs, or bug reports.
- **No inbound network exposure:** do not reverse-proxy, port-forward, or change
  the loopback bind.

The model still sees screenshots of gameplay and structured RAM-derived game
state. GitHub's Copilot service terms and privacy policy apply to that inference.

## Troubleshooting

### `ffmpeg is required`

```bash
brew install ffmpeg
```

Then rerun `./bootstrap.sh`.

### Copilot SDK startup/authentication fails

Confirm the same macOS user is authenticated for GitHub Copilot, then rerun:

```bash
./.venv/bin/python -m copilot download-runtime
./launch.sh --rom "/absolute/path/to/your/Pokemon Red.gb"
```

See `~/.openrappter/pokemon-red/player.log` for local diagnostics. Remove tokens,
ROM paths, screenshots, and game artifacts before sharing excerpts.

### ROM is rejected

The file must be a local, readable `.gb` file whose cartridge title identifies
Pokémon Red. Cloud placeholder files must be downloaded locally first. This
project cannot obtain or validate the legality of your copy.

### Viewer says forbidden

Open it with `./launch.sh view`; the bare port intentionally cannot mint an
authenticated session. Do not reuse an old viewer URL after a restart.

### A stale process keeps restarting

```bash
./launch.sh stop
./launch.sh status
```

The stop command changes supervisor-owned desired state before terminating the
child, so it will not restart. If the process crashed, the supervisor preserves
checkpoints and uses bounded exponential restart.

## Uninstall and cleanup

Remove only the private virtual environment and registration while **preserving
all saves and recordings**:

```bash
./uninstall.sh
```

The script reports the preserved runtime path. To explicitly delete all local
Pokemon state, including saves and recordings:

```bash
./uninstall.sh --purge-data
```

`--purge-data` is the only project command that removes user saves. Back up any
states or clips you want first.

## Development

```bash
python3.11 -m venv .venv-dev
.venv-dev/bin/pip install -e ".[dev]"
.venv-dev/bin/ruff check .
.venv-dev/bin/python -m compileall -q pokemon_agent.py src tests
.venv-dev/bin/pytest
bash -n bootstrap.sh launch.sh uninstall.sh
```

Tests never require a commercial ROM, credentials, Copilot calls, a GUI, or
ffmpeg. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md).

## License and trademarks

Code in this repository is available under the [MIT License](LICENSE).
Pokémon and related names are trademarks of their respective owners. This
independent project is not affiliated with or endorsed by Nintendo, The Pokémon
Company, Game Freak, GitHub, or PyBoy.
