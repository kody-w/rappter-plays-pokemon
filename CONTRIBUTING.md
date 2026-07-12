# Contributing

Thanks for improving RAPPter Plays Pokémon.

## Non-negotiable content rules

Never commit, upload, paste, or link to:

- ROM bytes or download/search instructions
- save states, cartridge RAM, screenshots, or gameplay recordings
- credentials, Copilot/GitHub tokens, viewer URLs, or auth cookies
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
bash -n bootstrap.sh launch.sh uninstall.sh
```

No test may contact GitHub Copilot, require authentication, start a GUI, invoke
ffmpeg, or use a copyrighted ROM. Mock those boundaries. A generated
zero-filled file with only the minimum test header is acceptable and must stay
inside pytest's temporary directory.

## Agent contract

`pokemon_agent.py` is intentionally a single-file OpenRappter RAPP agent. Keep
its `PokemonAgent(BasicAgent)` metadata and `perform(**kwargs)` contract intact.
Do not convert it into a skill or split runtime behavior into hidden generated
files.

Changes to lifecycle, checkpointing, viewer authentication, retention, or SDK
isolation require focused regression tests. Preserve zero SDK tools and
screenshot-only attachments.

## Pull requests

- Explain behavior and failure modes, not just implementation.
- Include tests for fixes.
- Keep commits focused and avoid generated files.
- Confirm the ROM-free/content scan in CI passes.
- Do not weaken loopback binding, same-origin checks, file permissions, or
  retention safeguards.
