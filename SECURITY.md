# Security Policy

## Supported versions

Security fixes are applied to the latest release on the default branch.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository:

<https://github.com/kody-w/rappter-plays-pokemon/security/advisories/new>

Do not open a public issue for a vulnerability. Do not include ROMs, save
states, screenshots, recordings, tokens, cookies, authenticated viewer URLs,
spectator join links/QR codes, or personal paths in a report. A minimal
synthetic reproduction is preferred.

Include:

- affected revision and macOS/Python versions
- expected and actual behavior
- a synthetic proof of concept
- impact and suggested mitigation, if known

## Security boundaries

The viewer is designed for one local user and binds exclusively to
`127.0.0.1`. Authentication, Host checks, and same-origin mutation checks are
defense in depth; the authenticated viewer must not be exposed through a proxy
or tunnel.

When explicitly enabled, livestreaming starts a second server on the LAN. That
server is a separate trust boundary: it serves only fixed spectator HTML, CSS,
and pinned PeerJS JavaScript through GET/HEAD. It has no status, frame, clip,
filesystem, cookie, bootstrap, control, or mutation routes. Unsupported methods
return 405, and private-looking paths return 404. Request workers, the listen
backlog, and socket time are bounded; only exact origin-form asset paths are
accepted. Do not add control behavior or proxy the loopback viewer through this
server.

The share URL carries a random PeerJS host ID and independent watch capability
only in its fragment. Treat the complete URL and QR code as bearer secrets.
URL fragments are processed by the spectator JavaScript and are not included
in HTTP requests, so the private values do not reach the local asset server,
GitHub Pages, or normal HTTP access logs.
The host accepts one bounded, versioned data-channel hello, rejects extra or
control-shaped fields, tracks every negotiating offer immediately, and
enforces hard negotiating and viewer caps before initiating media. After
admission the channel is host-to-spectator only; later spectator data closes
that viewer and never maps to controls. Host messages carry independently
versioned full dashboard snapshots built by a strict Python projector. The
allowlist excludes paths, hashes, IDs, capabilities, logs, errors, screen text,
model reasoning, raw actions, and arbitrary runtime dictionaries. Messages are
sequence checked, at most 4096 UTF-8 bytes, rate limited, and rendered only
through safe DOM text/properties. Spectators accept media only from the host ID
in the fragment.

PeerJS Cloud is used for signaling only. Video is sent browser-to-browser with
WebRTC/DTLS-SRTP, but WebRTC peers may learn network metadata and IP candidates.
Both constructors receive the same explicit ICE configuration containing only
Google `stun:stun.l.google.com:19302`; there are no TURN URLs or relays. The
STUN service observes metadata needed for candidate discovery. Direct
connectivity can fail behind some NATs. Media contains video without emulator
audio; allowlisted status uses the paired DataConnection. The mesh has linear
host upload cost and is not suitable for untrusted or large audiences.

Only one authenticated viewer tab may own a generation-scoped, server-issued
broadcast lease. It heartbeats and signs state updates with its owner,
generation, and lease token. Competing fresh owners and stale-generation
updates are rejected. The 15-second heartbeat, 120-second lease, and bounded
report freshness tolerate normal background timer throttling. An expired lease
is reacquired with guarded retries when its configured host page becomes
visible; an active competing owner remains authoritative. Explicit Stop/End,
page exit, capture end, lifecycle termination, or an authoritative lease loss
destroys PeerJS, peer connections, and capture tracks. Dashboard-only failures
degrade details but do not stop video/gameplay. Repeated simultaneous loss of
runtime status and lease heartbeat is a separate core-control failure that
stops capture rather than broadcasting a frozen canvas. A closed page releases
promptly; a crashed page can remain last-known only until the bounded stale
interval.

The checked-in `docs/watch/` GitHub Pages surface is static and read-only. It
contains the same spectator HTML, CSS, JavaScript, pinned PeerJS 1.5.5 bundle,
and notices as the local server, with no runtime APIs, controls, credentials,
analytics, or service worker. PeerJS Cloud remains signaling-only; game video
and dashboard data do not pass through GitHub Pages. The static JavaScript
receives dashboard snapshots only from the authenticated host peer. The local
LAN asset server still starts as a fallback/static source when an external join
base is configured. Do not port-forward the authenticated control viewer.

GitHub Pages does not let this repository configure the local server's custom
HTTP response headers. The published spectator HTML therefore carries a strict
meta CSP limited to self assets, media blobs, and the exact PeerJS Cloud
HTTPS/WSS signaling origins. `frame-ancestors` is intentionally absent because
browsers do not enforce it from a meta CSP; the Pages surface cannot reproduce
the local server's response-header anti-framing, nosniff, CORP, COOP, and
Permissions-Policy protections. It has no privileged controls, but this
residual hosting limitation must not be mistaken for header parity.

The Copilot SDK session has no tools and only gameplay PNG screenshots are
attached. Local filesystem compromise, a malicious OpenRappter installation,
or a modified Python environment is outside this project's threat model.

The bootstrap downloads Python packages and a pinned OpenRappter Git commit over
TLS. Review changes before overriding `OPENRAPPTER_REF` or using
`--openrappter-source`.
