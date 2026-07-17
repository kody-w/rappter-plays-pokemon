# Vendored browser libraries

The kited host and read-only spectator pages execute pinned local assets;
they do not load scripts from a CDN at runtime.

| Asset | Version | Upstream package file | SHA-256 | License |
| --- | --- | --- | --- | --- |
| PeerJS | 1.5.5 | `peerjs/dist/peerjs.min.js` | `7604d8c31bec4f134b0d15c2d80b1d095ea18af005354f439f14291fcd7b4168` | MIT |
| PeerJS runtime | 1.5.5 | pinned minified file with its trailing `sourceMappingURL` removed and final newline normalized | `95f57b9e94e1b96c829145b3f3ef0d04b332c9bda0567e144bed70d13712e3d0` | MIT |
| QRious | 4.0.2 | `qrious/dist/qrious.min.js` | `db99dcaf40a926181bce4522477c2efc5924f6c4b29111b6a97faea477c9528b` | GPL-3.0-or-later |
| QRious runtime | 4.0.2 | pinned minified file with its trailing `sourceMappingURL` removed and final newline normalized | `c46f564908ff10943a59e6f56f5de4bc5b6e827813b4750eef55353e7085157c` | GPL-3.0-or-later |

QRious's unminified distribution is included as
`qrious-4.0.2.js`. Its release package metadata, top-level notice, and
distribution header all specify GPL-3.0; the MIT notice on internal utility
code does not relicense the complete QR generator. The complete GPLv3 terms are
retained in `GPL-3.0.txt`.
The `*.runtime.min.js` files are deterministic byte-for-byte derivatives of
the retained minified distributions with their trailing `sourceMappingURL`
comments removed and final newlines normalized. Pages and the local host serve those
pinned derivatives so opening developer tools cannot trigger missing
source-map requests; the untouched upstream files remain available for
provenance and review.

PeerJS's browser bundle contains these exact production dependencies from the
v1.5.5 lock file. Their notices are embedded and served with the top-level
notices:

| Bundled package | Version | License |
| --- | --- | --- |
| eventemitter3 | 4.0.7 | MIT |
| peerjs-js-binarypack | 2.1.0 | MIT |
| webrtc-adapter | 9.0.1 | BSD-3-Clause |
| sdp | 3.2.0 | MIT |

`PROVENANCE.json` records npm integrity values, source URLs, exact versions,
and SHA-256 hashes for the upstream distributions and notices. Package
metadata is retained for both top-level dependencies; the derived runtime hash
is pinned by `scripts/update_browser_assets.py`.

After deliberately updating a pinned file and its expected digest, regenerate
the embedded copies in the single-file agent:

```bash
python scripts/update_browser_assets.py
python scripts/update_browser_assets.py --check
```

The check also validates `PROVENANCE.json` and every referenced local hash.
