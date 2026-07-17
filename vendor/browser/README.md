# Vendored browser libraries

The privileged host and read-only spectator pages execute pinned local assets;
they do not load scripts from a CDN at runtime.

| Asset | Version | Upstream package file | SHA-256 | License |
| --- | --- | --- | --- | --- |
| PeerJS | 1.5.5 | `peerjs/dist/peerjs.min.js` | `7604d8c31bec4f134b0d15c2d80b1d095ea18af005354f439f14291fcd7b4168` | MIT |
| QRious | 4.0.2 | `qrious/dist/qrious.min.js` | `db99dcaf40a926181bce4522477c2efc5924f6c4b29111b6a97faea477c9528b` | GPL-3.0-or-later |

QRious's unminified distribution is included as
`qrious-4.0.2.js`. Its release package metadata, top-level notice, and
distribution header all specify GPL-3.0; the MIT notice on internal utility
code does not relicense the complete QR generator. The complete GPLv3 terms are
retained in `GPL-3.0.txt`.

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
and SHA-256 hashes for every served distribution and notice. Package metadata
is retained for both top-level dependencies.

After deliberately updating a pinned file and its expected digest, regenerate
the embedded copies in the single-file agent:

```bash
python scripts/update_browser_assets.py
python scripts/update_browser_assets.py --check
```

The check also validates `PROVENANCE.json` and every referenced local hash.
