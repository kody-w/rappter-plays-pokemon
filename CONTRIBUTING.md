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
bash -n bootstrap.sh launch.sh uninstall.sh
```

No test may contact GitHub Copilot, PeerJS Cloud, the Chrome-for-Testing
manifest/storage service, require authentication, start a browser/GUI, invoke
ffmpeg, or use a copyrighted ROM. Mock those boundaries. A generated synthetic
file with only the minimum test header is acceptable and must stay inside
pytest's temporary directory.

## Agent contract

`pokemon_agent.py` is intentionally a single-file OpenRappter RAPP agent. Keep
its `PokemonAgent(BasicAgent)` metadata and `perform(**kwargs)` contract intact.
Do not convert it into a skill or split runtime behavior into hidden generated
files.

Changes to lifecycle, checkpointing, viewer authentication, retention, or SDK
isolation require focused regression tests. Preserve zero SDK tools and
screenshot-only attachments.

## Browser dependencies

The host and spectator pages must not execute runtime CDN scripts. Pinned
PeerJS and QRious distributions, package metadata, QRious source, and their
license notices live in `vendor/browser/`. Their compressed copies are embedded
in `pokemon_agent.py` so the registered single-file RAPP agent remains
self-contained.

The source direction is deliberate: `vendor/browser/` feeds the embedded
browser bytes; the literal `SPECTATOR_*` and `HOST_*` constants in
`pokemon_agent.py` define the two Pages routes; and
`scripts/build_pages_site.py` copies those exact canonical constants into the
checked-in `docs/watch/` and `docs/host/` publication trees. Never edit either
generated tree manually. `scripts/kite_vtwin.js` is the reviewable
zero-dependency CDP string source; `scripts/update_browser_assets.py` embeds
its exact bytes as `KITE_STRING_JS` so the registered RAPP agent stays
self-contained. After changing any of these sources, rebuild and check them:

```bash
.venv-dev/bin/python scripts/build_pages_site.py
.venv-dev/bin/python scripts/build_pages_site.py --check
```

The Pages trees must remain static: no runtime APIs, gameplay controls,
analytics, service workers, storage, CDN scripts, or localhost access. The
bare host must remain inert until exact versioned CDP bootstrap. Keep spectator
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

Node.js is optional for Python-only local development; the JavaScript checker
prints an explicit skip when it is absent. CI installs Node and requires every
first-party and vendored browser script to parse.

Livestream changes require ROM-free tests for both Pages builds, inert host
bootstrap, exact target selection (including distractors/ambiguity/navigation),
CDP RPC timeout/close cleanup, capability redaction, bounded protocol
admission, frame dedup/latest-wins/backpressure, heartbeat loss, process/profile
cleanup, and legacy local mode. Dashboard changes must keep
`project_dashboard_snapshot` as the sole strict public projector, enforce
exact/versioned message keys and the 4096-byte bound, use inert DOM rendering,
and cover sequence/cadence/staleness with synthetic memory and fake clocks.
PiP tests must cover standard and Safari APIs without screen capture.
Chrome-for-Testing tests use synthetic manifests/archives and injected
extract/signature functions; tests must never download or connect to signaling.

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
