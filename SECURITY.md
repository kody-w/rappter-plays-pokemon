# Security Policy

## Supported versions

Security fixes are applied to the latest release on the default branch.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository:

<https://github.com/kody-w/rappter-plays-pokemon/security/advisories/new>

Do not open a public issue for a vulnerability. Do not include ROMs, save
states, screenshots, recordings, tokens, cookies, authenticated viewer URLs, or
personal paths in a report. A minimal synthetic reproduction is preferred.

Include:

- affected revision and macOS/Python versions
- expected and actual behavior
- a synthetic proof of concept
- impact and suggested mitigation, if known

## Security boundaries

The viewer is designed for one local user and binds exclusively to
`127.0.0.1`. Authentication, Host checks, and same-origin mutation checks are
defense in depth; the viewer must not be exposed through a proxy or tunnel.

The Copilot SDK session has no tools and only gameplay PNG screenshots are
attached. Local filesystem compromise, a malicious OpenRappter installation,
or a modified Python environment is outside this project's threat model.

The bootstrap downloads Python packages and a pinned OpenRappter Git commit over
TLS. Review changes before overriding `OPENRAPPTER_REF` or using
`--openrappter-source`.
