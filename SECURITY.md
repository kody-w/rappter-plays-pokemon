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

The default livestream architecture starts no LAN server. A dedicated
GitHub Pages `/host/` tab owns PeerJS and canvas capture. A local Node.js CDP
**string** tethers that public static tab to atomic private frame and telemetry
files. GitHub Pages does not relay those bytes and cannot fetch localhost.
Explicit `--livestream-host local` remains a rollback path; only that mode
starts the bounded GET/HEAD-only LAN spectator asset server.

Chrome DevTools Protocol is an unauthenticated same-user local authority. The
string must launch or attach only to its generation-owned Chrome/Chromium
process, private `0700` profile, and loopback DevTools endpoint. Never
port-forward, proxy, or expose that endpoint, and never point this feature at a
personal browser profile. The string discovers `DevToolsActivePort` inside its
own profile, selects one exact Pages origin/path/nonsecret instance fragment,
rejects ambiguity and navigation, and verifies the versioned host build. It
never falls back to the first page.

After attachment, the string holds one persistent CDP WebSocket and uses only
fixed `Runtime.callFunctionOn` methods on the versioned host ingress.
The ingress accepts exact schemas for bootstrap, frame, telemetry, heartbeat,
desired broadcast state, shutdown, and bounded nonsecret status. It validates generation/instance,
monotonic sequences, PNG signature/160×144 dimensions/128 KiB size/SHA-256,
and the strict Python dashboard projection. The Pages host has no inverse
command queue, localhost requests, gameplay controls, arbitrary evaluation
surface, analytics, storage, or service worker. Local `host` requests can only
ask the already managed CDP connection to activate its exact target.

The share URL carries a random PeerJS host ID and independent watch capability
only in its fragment. Treat the complete URL and QR code as bearer secrets.
URL fragments are processed by the spectator JavaScript and are not included
in HTTP requests, so the private values do not reach GitHub Pages or normal
HTTP access logs. The host target URL contains only a nonsecret instance
selector. Peer identity, watch capability, generation, and invitation are
created in mode-`0600` runtime state and injected into page memory only after
exact target/build verification. They are never browser arguments, query
parameters, CDP debug URLs, or general logs.
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

The dedicated browser profile and tokenized bridge ownership lock allow one
kited host per generation. Lock and browser records bind PID/PGID to process
start identity, parent, instance, profile, and random launch token; cleanup
revalidates the process group even if its leader exited and never signals a
reused PID. Under that exclusive ownership, startup removes only inactive old
profiles carrying the exact managed marker and leaves symlinks, active
profiles, and arbitrary user directories untouched.

The string deduplicates exact frames, limits unique frame
injection to 10 fps, permits one frame CDP call in flight, and retains only a
latest-wins pending slot. Telemetry changes at most once per second and
heartbeats around five seconds. A one-second string heartbeat carries only
bounded runtime/source health. Attempted frame sequence/hash are distinct from
host-acknowledged state; only an `{ok:true}` draw or same-hash host
acknowledgement refreshes source health. Rejected frames retain the last canvas
but immediately make the stream unshareable and repeated failures restart the
bounded sidecar/browser recovery path. Missing source or string heartbeats show
`SOURCE LOST`/`STRING LOST`; after a bounded grace the page destroys PeerJS,
viewer connections, Picture in Picture, and canvas tracks. Explicit Stop/End,
target navigation, capture end, browser exit, or page exit does the same.
End also writes a generation-bound desired-state latch through the string, so
browser recovery cannot reopen broadcasting until Go Live, Retry, or the
explicit local CLI action clears it.

Browser/string/signaling failure is a nonfatal sidecar failure. Gameplay,
Copilot, recording, and checkpointing continue. Redacted mode-`0600` host
status reports degraded health; fresh status is required before `share`
returns the invitation. The Python sidecar tracks exact string/browser process
groups and generation profile, restarts independently with capped backoff, and
never uses name-based process killing.

The checked-in `docs/watch/` and `docs/host/` GitHub Pages surfaces are static.
They contain pinned PeerJS 1.5.5/QRious 4.0.2 assets and notices, with no
runtime APIs, gameplay controls, credentials, analytics, storage, or service
worker. Runtime copies omit only upstream `sourceMappingURL` trailers so no
source-map request is generated. PeerJS Cloud remains signaling-only; game video and dashboard data do
not pass through GitHub Pages. Spectator JavaScript receives dashboard
snapshots only from the admitted host peer. Do not port-forward the
authenticated control viewer or the CDP endpoint.

GitHub Pages does not let this repository configure the local server's custom
HTTP response headers. The published spectator HTML therefore carries a strict
meta CSP limited to self assets, media blobs, and the exact PeerJS Cloud
HTTPS/WSS signaling origins. `frame-ancestors` is intentionally absent because
browsers do not enforce it from a meta CSP; the Pages surfaces cannot reproduce
the local server's response-header anti-framing, nosniff, CORP, COOP, and
Permissions-Policy protections. They have no gameplay or local-runtime controls, but this
residual hosting limitation must not be mistaken for header parity.

The Copilot SDK session has no tools and only gameplay PNG screenshots are
attached. Local filesystem compromise, a malicious OpenRappter installation,
or a modified Python environment is outside this project's threat model.

The bootstrap downloads Python packages and a pinned OpenRappter Git commit over
TLS. Review changes before overriding `OPENRAPPTER_REF` or using
`--openrappter-source`. Browser provisioning is separate and explicit. Its
macOS helper accepts only the official stable Chrome-for-Testing manifest and
canonical Google Storage URL, validates ZIP paths/shape/CRC/expansion, extracts
atomically under a private lock, and verifies the Google code-signing team
where `codesign` is available. Tests and CI never invoke that download.
