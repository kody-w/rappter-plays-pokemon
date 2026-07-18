# Contributing

Thanks for improving RAPPter Plays Pokémon.

## Non-negotiable content rules

Never commit, upload, paste, or link to:

- ROM bytes or download/search instructions
- save states, cartridge RAM, screenshots, or gameplay recordings
- credentials, Copilot/GitHub tokens, viewer URLs, spectator join links/QR
  codes, or auth cookies
- local runtime artifacts or personal filesystem paths

Issues and pull requests containing game content or secrets will be removed.
Use synthetic byte arrays and mocks in tests.

The public story archive is a narrow metadata-only exception. It may contain
only the schema-validated projection produced by
`rappter_plays_pokemon.story`; never commit source manifests, screenshots,
audio, video, model prompts, or arbitrary runtime dictionaries. Public story
updates belong on the isolated `story-archive` branch, not `main`.

Never commit `*.live_chat.json` or `youtube-chat-advisory.json`. Chat tests use
synthetic renderer objects only and may assert only the closed direction enum;
raw text, identities, URLs, payment metadata, or arbitrary suggestions must
not enter the gameplay prompt or fixtures derived from real users.

Web-research tests must mock the exact Bulbapedia API boundary. Do not contact
the network in pytest. Preserve the separation between the zero-tool gameplay
session and the one-shot researcher; only the researcher may register the
single `pokemon_web_search` tool, and its output must retain exact source
allowlisting, response bounds, context/TTL checks, and optional-evidence
wording.

## Development setup

Python 3.11+ is required.

```bash
python3.11 -m venv .venv-dev
.venv-dev/bin/pip install -e ".[dev]"
```

Run every check before submitting:

```bash
.venv-dev/bin/ruff check .
.venv-dev/bin/python -m compileall -q pokemon_agent.py src tests
.venv-dev/bin/pytest
.venv-dev/bin/python scripts/update_browser_assets.py --check
.venv-dev/bin/python scripts/build_pages_site.py --check
.venv-dev/bin/python scripts/check_browser_js.py
bash -n bootstrap.sh chat.sh launch.sh story.sh uninstall.sh
```

No test may contact GitHub Copilot, PeerJS Cloud, a Nostr relay, STUN, the
Chrome-for-Testing manifest/storage service, require authentication, start a
browser/GUI, invoke ffmpeg, or use a copyrighted ROM. Mock those boundaries.
Live relay review is an explicit maintainer task and is never CI. A generated
synthetic file with only the minimum test header is acceptable and must stay
inside pytest's temporary directory.

## Agent contract

`pokemon_agent.py` is intentionally a single-file OpenRappter RAPP agent. Keep
its `PokemonAgent(BasicAgent)` metadata and `perform(**kwargs)` contract intact.
Do not convert it into a skill or split runtime behavior into hidden generated
files.

Changes to lifecycle, checkpointing, viewer authentication, retention, or SDK
isolation require focused regression tests. Preserve zero SDK tools and
screenshot-only attachments.

## Browser dependencies

The host and spectator pages must not execute runtime CDN scripts. Exact
Trystero Nostr 0.25.3/core/noble archives and sources, the deterministic
self-contained IIFE, PeerJS rollback, QRious, metadata, provenance, relay
policy, and license notices live in `vendor/browser/`. Their runtime bytes are
embedded in `pokemon_agent.py`, so the registered single-file RAPP agent
remains self-contained.

The source direction is deliberate: `vendor/browser/` feeds dependency bytes
and the immutable `pages-v1/` rollback snapshot; `web/pages-v2/` contains the
reviewable current first-party Pages sources;
`scripts/update_browser_assets.py` embeds those v2 sources as
`SPECTATOR_*`, `HOST_*`, and `PAIRING_JS`; and
`scripts/build_pages_site.py` deterministically writes root v1 plus
side-by-side `docs/watch/v2/` and `docs/host/v2/`. Never edit either generated
tree manually. `PAGES_V1.json` hash-locks rollback inputs. Versioned v2 asset
filenames must change before an incompatible protocol change.
`scripts/kite_vtwin.js` is the reviewable
zero-dependency CDP string source; `scripts/update_browser_assets.py` embeds
its exact bytes as `KITE_STRING_JS` so the registered RAPP agent stays
self-contained. After changing any of these sources, rebuild and check them:

```bash
.venv-dev/bin/python scripts/build_pages_site.py
.venv-dev/bin/python scripts/build_pages_site.py --check
```

The root `docs/index.html`, `docs/site.css`, `docs/story/`, and `docs/d/` files are
hand-authored public entry points. They must remain separate from the generated
host/watch protocol trees. The story page may connect only to the exact
`raw.githubusercontent.com` story URL and must render every archive string via
safe DOM text properties. The QR destination must remain project-first,
fragment-only for diagnostics, and incapable of automatically submitting an
issue.

The Pages trees must remain static: no gameplay controls, analytics, service
workers, storage, CDN scripts, or Pages-to-localhost requests. The v2 static
return page may perform only a visible top-level handoff to the exact
fragment-carried loopback callback. The bare host must remain inert until exact
versioned CDP bootstrap. Keep spectator
capability parsing fragment-only and the host target fragment nonsecret.
Because GitHub Pages cannot set the local server's response headers, retain
the strict meta CSP without an ineffective `frame-ancestors` directive.

After an intentional dependency update, verify its upstream release and
license, update the pinned digest and provenance table, then run:

```bash
.venv-dev/bin/python scripts/update_browser_assets.py
.venv-dev/bin/python scripts/update_browser_assets.py --check
.venv-dev/bin/python scripts/build_pages_site.py
.venv-dev/bin/python scripts/build_pages_site.py --check
.venv-dev/bin/python scripts/check_browser_js.py
```

For an intentional Trystero update, first review the exact upstream commit,
source, types, defaults, dependencies, and licenses. Put only reviewed package
archives in `vendor/browser/sources/`. Any derivative must be minimal,
MIT-license compliant, documented and hash-pinned in `TRYSTERO_BUILD.json`;
patches apply with `patch --fuzz=0`. Then run
`python scripts/build_trystero_bundle.py --check`. That command may use npm as
an asset-build tool; Pages and the runtime never do. Do not run it in CI.
`NOSTR_RELAYS.json` must retain exactly five reviewed upstream-default origins,
operator links where known, review date, two-client EVENT acceptance/delivery
procedure (open/EOSE alone is insufficient), privacy warning,
and best-effort/no-SLA language. Public links may never supply relay URLs.

Node.js is optional for Python-only local development; the JavaScript checker
prints an explicit skip when it is absent. CI installs Node and requires every
first-party and vendored browser script to parse.

Livestream changes require ROM-free tests for both Pages builds, inert host
bootstrap, exact target selection (including distractors/ambiguity/navigation),
CDP RPC timeout/close cleanup, capability redaction, bounded protocol
admission, frame dedup/latest-wins/backpressure, heartbeat loss, process/profile
cleanup, asynchronous leave/cache races, last-room socket/timer disposal,
ECDSA host proof and shared-key forgery rejection, pending-host promotion,
targeted media-ready actions, separate auth/transport/media deadlines, relay
qualification/loss with surviving media, one-bad-peer isolation, Share-sheet
offer/answer links, static-to-loopback return handoff, strict return endpoint,
atomic queue/CDP delivery/replay, manual retire/capacity/tamper/expiry/size
state machines, mixed compression capability, QR capacity fallback, and
legacy v1/local mode. Dashboard changes must keep
`project_dashboard_snapshot` as the sole strict public projector, enforce
exact/versioned message keys and the 4096-byte bound, use inert DOM rendering,
and cover sequence/cadence/staleness with synthetic memory and fake clocks.
PiP tests must cover standard and Safari APIs without screen capture.
Chrome-for-Testing tests use synthetic manifests/archives and injected
extract/signature functions; tests must never download or connect to signaling.
Never add TURN, arbitrary relay URLs, iframe/worker/service-worker policy
bypasses, or network access to the manual pairing path.

Treat CDP as unauthenticated same-user local authority. Never add first-page
fallback, personal-profile reuse, remote-debug forwarding, arbitrary
evaluation/commands, `--no-sandbox`, `--disable-web-security`, or certificate
bypass. Browser/string failures must remain nonfatal to gameplay.

## Pull requests

- Explain behavior and failure modes, not just implementation.
- Include tests for fixes.
- Keep commits focused; `docs/watch/` and `docs/host/` are the required
  checked-in generated browser trees.
- Confirm the ROM-free/content scan in CI passes.
- Do not weaken loopback binding, same-origin checks, file permissions, or
  retention safeguards.
