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
GitHub Pages `/host/v2/` tab owns Trystero/Nostr signaling and canvas capture. A
local Node.js CDP **string** tethers that public static tab to atomic private
frame and telemetry files. GitHub Pages does not relay those bytes and cannot
fetch localhost. This project requires neither Azure nor an owned signaling
server.
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
desired broadcast state, one bounded pairing-only manual-answer ingress,
shutdown, and bounded nonsecret status. It validates generation/instance,
monotonic sequences, PNG signature/160×144 dimensions/128 KiB size/SHA-256,
and the strict Python dashboard projection. The Pages host has no inverse
command queue, localhost requests, gameplay controls, arbitrary evaluation
surface, analytics, storage, or service worker. Local `host` requests can only
ask the already managed CDP connection to activate its exact target.

The v2 share URL carries independently generated 128-bit room and 256-bit
admission/encryption key values, a generation, ECDSA P-256 public JWK, and host
fingerprint only in its fragment. The local Node string generates and persists
the generation-private JWK in mode-`0600` state and injects it only into host
page memory. Treat the complete URL and QR code as bearer secrets.
URL fragments are processed by the spectator JavaScript and are not included
in HTTP requests, so the private values do not reach GitHub Pages or normal
HTTP access logs. The host target URL contains only a nonsecret instance
selector. Room identity, key, generation, fingerprint, and invitation are
created in mode-`0600` runtime state and injected into page memory only after
exact target/build verification. They are never browser arguments, query
parameters, CDP debug URLs, or general logs.
The active host accepts only passive viewers that complete a bounded,
versioned role/capability handshake. The shared room key authenticates viewer
admission only. Host proofs are asymmetric ECDSA signatures over room,
generation, pinned public key/fingerprint, both ephemeral peer IDs, role,
viewer/host nonces, target, expiry, and sequence; an invited viewer cannot
forge them. The host tracks negotiations immediately and enforces hard
negotiating/viewer caps before targeting media. Passive viewers do not connect
to one another. Host messages carry independently
versioned full dashboard snapshots built by a strict Python projector. The
allowlist excludes paths, hashes, IDs, capabilities, logs, errors, screen text,
model reasoning, raw actions, and arbitrary runtime dictionaries. Messages are
sequence checked, at most 4096 UTF-8 bytes, rate limited, and rendered only
through safe DOM text/properties. Spectators track a verified pending host but promote it only after Trystero's
authenticated peer activation; failed/retried pending proofs are cleared.
They accept media only from the activated peer that proves the
generation-scoped host identity pinned by the fragment.

`passive:true` is cooperative and does not provide pre-SDP isolation. A
malicious holder of a valid invitation can trigger encrypted signaling and
candidate exchange before application role authentication, so invited peers
may observe candidate metadata. The application mitigates this with one
pending/accepted host, hard connection bounds, strict target IDs, no
viewer-to-viewer application actions, asymmetric host pinning before
media/telemetry acceptance, and direct-peer cleanup. It does not claim that
candidate metadata is hidden before authentication.

Five explicitly allowlisted public Nostr relays redundantly carry encrypted
Trystero discovery/SDP only. They are best effort and have no SLA. Their
operators can observe source IP, relay URL, timing, ephemeral Nostr public
keys, event IDs/signatures, `created_at`, kind, and the plaintext `x` tag with
a deterministic topic hash. The room password encrypts EVENT signaling
content/SDP; it is not sent as plaintext application
data. Once connected, video uses direct WebRTC/DTLS-SRTP and telemetry uses
direct SCTP/DTLS. Relay loss alone does not close established media.
An open relay socket is diagnostic, not healthy signaling. The vendored
adapter sends one bounded random self-probe per socket generation and requires
NIP-01 `OK true` plus delivery of that exact event through its exact
subscription. Probe content has only a protocol marker and random nonsecret
bytes, never room/key/SDP. This operational check is separate from the
two-client release qualification. Automatic sharing becomes ready only after
that round trip. A bounded
zero-qualified-relay interval announces Manual Share without closing existing
direct peers. Host authentication, transport, and media/playback have separate
deadlines. A targeted `media-ready` action is sent only after a live remote
track is received and playable. Serialized `room.leave()` disposal precedes
all retries; the documented derivative guarantees local deregistration even
when leave signaling rejects and suspends all sockets/reconnect timers after
the last room.

Host and viewer explicitly pass one ICE server, Google
`stun:stun.l.google.com:19302`, with no TURN URL bundled (no anonymous public
TURN service remains in operation). Relay candidates are no longer rejected:
an operator who supplies their own TURN service gets a fallback path whose
media stays protected by DTLS-SRTP — a relay forwards encrypted packets it
cannot read, while observing relay metadata. The STUN service observes
candidate-discovery metadata, peers may learn network/IP candidates, and
restrictive NAT/UDP policy without TURN can prevent media.
The mesh has linear host upload cost and is not suitable for untrusted or large
audiences.

Manual Share pairing is the always-available signaling fallback. Each pending
viewer gets a unique five-minute pair ID and raw `RTCPeerConnection` with
complete non-trickle ICE. The fragment-only offer contains the bearer key,
callback descriptor, pairing-only return token, signed host transcript, and
bounded uncompressed SDP (`zip=none`). The viewer's answer is
encrypted/authenticated with
HKDF-SHA-256 and AES-256-GCM using the key plus offer hash, with pair,
generation, fingerprint, expiry, and offer binding as authenticated data.
Offers are single-use; tamper, replay, expiry, oversize, invalid candidate, and
SDP-apply failures retire and close them. QR rendering is preflighted and
falls back to a complete Share-sheet/copy link rather than truncating. The
second pass is required because the viewer's candidates and answer cannot be
precomputed. The answer Share URL is static `/host/v2/return/#…`; Pages reads
the fragment locally and performs only a user-visible top-level handoff, never
a localhost fetch. The loopback-only `/pair-return` page POSTs same-origin to
`/api/kite/manual-answer`, which requires exact 127.0.0.1 Host/Origin, current
generation/token, JSON/size/rate/queue bounds, and can invoke no gameplay
control. The CDP string consumes monotonic answers and calls only the exact
host pairing ingress. Tokens and queue files are removed on stop/rollover.

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
`SOURCE LOST`/`STRING LOST`; after a bounded grace the page destroys signaling
rooms, viewer connections, Picture in Picture, and canvas tracks. Explicit Stop/End,
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
They contain pinned `@trystero-p2p/nostr` 0.25.3, PeerJS 1.5.5 rollback, and
QRious 4.0.2 assets and notices, with no runtime APIs, gameplay controls,
credentials, analytics, storage, or service worker. Runtime copies require no
CDN/npm. Nostr relays remain signaling-only; game video and dashboard data do
not pass through GitHub Pages or those relays. Spectator JavaScript receives dashboard
snapshots only from the admitted host peer. Do not port-forward the
authenticated control viewer or the CDP endpoint.

GitHub Pages does not let this repository configure the local server's custom
HTTP response headers. The published spectator HTML therefore carries a strict
meta CSP limited to self assets, media blobs, five exact reviewed Nostr WSS
origins, and the exact legacy PeerJS origin. `frame-ancestors` is intentionally absent because
browsers do not enforce it from a meta CSP; the Pages surfaces cannot reproduce
the local server's response-header anti-framing, nosniff, CORP, COOP, and
Permissions-Policy protections. They have no gameplay or local-runtime controls, but this
residual hosting limitation must not be mistaken for header parity.

The application does not use iframes, injected JS/WASM/bytecode, workers,
service workers, CDN/version swaps, or similar techniques to evade browser or
managed-network WSS enforcement. If managed Edge or network policy blocks all
automatic relay sockets, the attended manual flow is the compliant fallback.
PeerJS and v1 links remain legacy rollback behavior, not the default.

The Copilot SDK session has no tools and only gameplay PNG screenshots are
attached. Local filesystem compromise, a malicious OpenRappter installation,
or a modified Python environment is outside this project's threat model.

The bootstrap downloads Python packages and a pinned OpenRappter Git commit over
TLS. Review changes before overriding `OPENRAPPTER_REF` or using
`--openrappter-source`. Browser provisioning is separate and explicit. Its
macOS helper accepts only the official stable Chrome-for-Testing manifest and
canonical Google Storage URL, validates ZIP paths/shape/CRC/expansion, extracts
atomically under a private lock, and verifies either Google's code-signing team
or the exact official CfT ad-hoc testing identity where `codesign` is
available. Tests and CI never invoke that download.
