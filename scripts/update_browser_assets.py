#!/usr/bin/env python3
"""Embed pinned browser assets and the reviewed CDP string into the RAPP agent."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import textwrap
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "pokemon_agent.py"
START = "# BEGIN GENERATED BROWSER ASSETS"
END = "# END GENERATED BROWSER ASSETS"
ASSETS = (
    (
        "PEERJS_MIN_JS",
        ROOT / "vendor/browser/peerjs-1.5.5.min.js",
        "7604d8c31bec4f134b0d15c2d80b1d095ea18af005354f439f14291fcd7b4168",
    ),
    (
        "PEERJS_RUNTIME_JS",
        ROOT / "vendor/browser/peerjs-1.5.5.runtime.min.js",
        "95f57b9e94e1b96c829145b3f3ef0d04b332c9bda0567e144bed70d13712e3d0",
    ),
    (
        "QRIOUS_MIN_JS",
        ROOT / "vendor/browser/qrious-4.0.2.min.js",
        "db99dcaf40a926181bce4522477c2efc5924f6c4b29111b6a97faea477c9528b",
    ),
    (
        "QRIOUS_RUNTIME_JS",
        ROOT / "vendor/browser/qrious-4.0.2.runtime.min.js",
        "c46f564908ff10943a59e6f56f5de4bc5b6e827813b4750eef55353e7085157c",
    ),
    (
        "QRIOUS_SOURCE_JS",
        ROOT / "vendor/browser/qrious-4.0.2.js",
        "d1e65c661e659f51c226de9be64feff66052549ed881959aa7ebb960adfb8158",
    ),
    (
        "TRYSTERO_NOSTR_RUNTIME_JS",
        ROOT / "vendor/browser/trystero-nostr-0.25.3.iife.min.js",
        "3a4f689e5cc156f92d118a1860bc0cd77a60db220b6521b9f60b3b6fb36b2b9d",
    ),
    (
        "PEERJS_LICENSE",
        ROOT / "vendor/browser/peerjs-1.5.5.LICENSE",
        "9407807dba7f47a79bfb3ac55759d63d77c9371ebd0616d5a093e97d3e810397",
    ),
    (
        "EVENTEMITTER3_LICENSE",
        ROOT / "vendor/browser/eventemitter3-4.0.7.LICENSE",
        "3aecc12b1cb28832b5f65ab64291de96568c3f236a74d646281b4491f7bcadbf",
    ),
    (
        "BINARYPACK_LICENSE",
        ROOT / "vendor/browser/peerjs-js-binarypack-2.1.0.LICENSE",
        "9517e6f46b30231a62407f94a8c7adf8b4d14038c01807cd769f1d4de5911ba4",
    ),
    (
        "WEBRTC_ADAPTER_LICENSE",
        ROOT / "vendor/browser/webrtc-adapter-9.0.1.LICENSE.md",
        "00a46c6cfc219593b97586398b477e188391556e70487225d3ff9d60ccda6dce",
    ),
    (
        "SDP_LICENSE",
        ROOT / "vendor/browser/sdp-3.2.0.LICENSE",
        "798e82590af6a84bfbde3d6bb0fb9162c519edf16122404fea00acefdc55cbd9",
    ),
    (
        "QRIOUS_LICENSE",
        ROOT / "vendor/browser/qrious-4.0.2.LICENSE.md",
        "573aa60568eb0d6829453b85a9bcae84763de76638bc16e6a198a9535871191a",
    ),
    (
        "QRIOUS_GPL_TERMS",
        ROOT / "vendor/browser/GPL-3.0.txt",
        "3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986",
    ),
    (
        "TRYSTERO_LICENSE",
        ROOT / "vendor/browser/trystero-nostr-0.25.3.LICENSE",
        "bbf91fd979faac0def9551c570e2e9f92b4e02d22f38ca5d98860b6284e1ea25",
    ),
    (
        "TRYSTERO_CORE_LICENSE",
        ROOT / "vendor/browser/trystero-core-0.25.3.LICENSE",
        "bbf91fd979faac0def9551c570e2e9f92b4e02d22f38ca5d98860b6284e1ea25",
    ),
    (
        "NOBLE_SECP256K1_LICENSE",
        ROOT / "vendor/browser/noble-secp256k1-3.1.0.LICENSE",
        "394c2e6e5552e5dba202bee6390b9d6aa2754d657f5b9869e83b3d265a315501",
    ),
    (
        "TRYSTERO_BUILD_PROVENANCE",
        ROOT / "vendor/browser/TRYSTERO_BUILD.json",
        "489ca4fad767ed268ff8eeaaa64f79f91c28e8d223f25694561c23ae37deaf17",
    ),
    (
        "NOSTR_RELAY_POLICY",
        ROOT / "vendor/browser/NOSTR_RELAYS.json",
        "0b768e2f308c0debabc434704ae1311d066fcea72e4860addb107ebd6957265a",
    ),
    (
        "BROWSER_PROVENANCE",
        ROOT / "vendor/browser/PROVENANCE.json",
        "7234485caaedb986c11f6e6385298f239d28623f92149c741ea7bbba0d154a85",
    ),
    (
        "KITE_STRING_JS",
        ROOT / "scripts/kite_vtwin.js",
        None,
    ),
)
TEXT_ASSETS = (
    ("PAIRING_JS", ROOT / "web/pages-v2/shared/pairing.js"),
    ("HOST_HTML", ROOT / "web/pages-v2/host/index.html"),
    ("HOST_CSS", ROOT / "web/pages-v2/host/host.css"),
    ("HOST_JS", ROOT / "web/pages-v2/host/host.js"),
    ("SPECTATOR_HTML", ROOT / "web/pages-v2/watch/index.html"),
    ("SPECTATOR_CSS", ROOT / "web/pages-v2/watch/spectator.css"),
    ("SPECTATOR_JS", ROOT / "web/pages-v2/watch/spectator.js"),
)

EXPECTED_BUNDLED_DEPENDENCIES = {
    "eventemitter3": "4.0.7",
    "peerjs-js-binarypack": "2.1.0",
    "webrtc-adapter": "9.0.1",
    "sdp": "3.2.0",
}
EXPECTED_TRYSTERO_DEPENDENCIES = {
    "@trystero-p2p/core": "0.25.3",
    "@noble/secp256k1": "3.1.0",
}


def render_asset(
    name: str,
    path: Path,
    expected_sha256: str | None,
) -> str:
    payload = path.read_bytes()
    actual = hashlib.sha256(payload).hexdigest()
    if expected_sha256 is not None and actual != expected_sha256:
        raise RuntimeError(f"{path} has SHA-256 {actual}, expected {expected_sha256}")
    encoded = base64.b64encode(zlib.compress(payload, level=9)).decode("ascii")
    lines = "\n".join(f'    b"{part}"' for part in textwrap.wrap(encoded, 76))
    return (
        f"{name} = zlib.decompress(base64.b64decode(  # generated from {path.name}\n"
        f"{lines}\n"
        "))"
    )


def render_text_asset(name: str, path: Path) -> str:
    payload = path.read_bytes()
    payload.decode("utf-8")
    encoded = base64.b64encode(zlib.compress(payload, level=9)).decode("ascii")
    lines = "\n".join(f'    b"{part}"' for part in textwrap.wrap(encoded, 76))
    return (
        f"{name} = zlib.decompress(base64.b64decode(  "
        f"# generated from {path.relative_to(ROOT)}\n"
        f"{lines}\n"
        ')).decode("utf-8")'
    )


def verify_provenance() -> None:
    vendor = ROOT / "vendor/browser"
    provenance = json.loads((vendor / "PROVENANCE.json").read_text())
    metadata = {
        item["package"]: json.loads((vendor / item["metadata_file"]).read_text())
        for item in provenance["assets"]
    }
    if (
        metadata["peerjs"].get("version") != "1.5.5"
        or metadata["peerjs"].get("license") != "MIT"
        or metadata["qrious"].get("version") != "4.0.2"
        or metadata["qrious"].get("license") != "GPL-3.0"
    ):
        raise RuntimeError("Vendored package metadata or licensing changed")
    trystero = provenance.get("trystero_bundle", {})
    trystero_metadata = json.loads(
        (vendor / str(trystero.get("metadata_file", ""))).read_text()
    )
    if (
        trystero.get("version") != "0.25.3"
        or trystero.get("upstream_commit")
        != "f76eb4fca528a3253e2bdfd6d41b54c8131ca11e"
        or trystero_metadata.get("version") != "0.25.3"
        or trystero_metadata.get("license") != "MIT"
    ):
        raise RuntimeError("Vendored Trystero pin or licensing changed")
    peer_dependencies = metadata["peerjs"].get("dependencies", {})
    for package in (
        "eventemitter3",
        "peerjs-js-binarypack",
        "webrtc-adapter",
    ):
        if package not in peer_dependencies:
            raise RuntimeError(f"PeerJS metadata no longer includes {package}")
    dependencies = {
        item["package"]: item["version"]
        for item in provenance["peerjs_bundled_dependencies"]
    }
    if dependencies != EXPECTED_BUNDLED_DEPENDENCIES:
        raise RuntimeError(
            "PeerJS bundled dependency versions do not match the verified lock"
        )
    trystero_dependencies = {
        item["package"]: item["version"]
        for item in provenance.get("trystero_bundled_dependencies", [])
    }
    if trystero_dependencies != EXPECTED_TRYSTERO_DEPENDENCIES:
        raise RuntimeError(
            "Trystero bundled dependency versions do not match the verified lock"
        )
    for item in [
        *provenance["assets"],
        *provenance["peerjs_bundled_dependencies"],
        trystero,
        *provenance.get("trystero_bundled_dependencies", []),
    ]:
        for path_key, hash_key in (
            ("file", "sha256"),
            ("archive_file", "archive_sha256"),
            ("metadata_file", "metadata_sha256"),
            ("source_file", "source_sha256"),
            ("license_file", "license_sha256"),
            ("license_terms_file", "license_terms_sha256"),
            ("build_file", "build_sha256"),
            ("relay_policy_file", "relay_policy_sha256"),
        ):
            path_name = item.get(path_key)
            if not path_name:
                continue
            actual = hashlib.sha256((vendor / path_name).read_bytes()).hexdigest()
            if actual != item[hash_key]:
                raise RuntimeError(
                    f"{path_name} has SHA-256 {actual}, expected {item[hash_key]}"
                )
    for original_name, runtime_name, marker in (
        (
            "peerjs-1.5.5.min.js",
            "peerjs-1.5.5.runtime.min.js",
            b"\n//# sourceMappingURL=peerjs.min.js.map",
        ),
        (
            "qrious-4.0.2.min.js",
            "qrious-4.0.2.runtime.min.js",
            b"\n//# sourceMappingURL=qrious.min.js.map",
        ),
    ):
        original = (vendor / original_name).read_bytes()
        head, separator, tail = original.rpartition(marker)
        if not separator or tail not in {b"", b"\n"}:
            raise RuntimeError(f"{original_name} source-map trailer changed")
        if (vendor / runtime_name).read_bytes() != head.rstrip(b"\n") + b"\n":
            raise RuntimeError(
                f"{runtime_name} must remove the source-map trailer "
                "and normalize its final newline"
            )


def update(*, check: bool) -> bool:
    verify_provenance()
    source = AGENT.read_text(encoding="utf-8")
    before, marker, remainder = source.partition(START)
    if not marker:
        raise RuntimeError(f"Missing {START!r} in {AGENT}")
    _old, marker, after = remainder.partition(END)
    if not marker:
        raise RuntimeError(f"Missing {END!r} in {AGENT}")
    generated = "\n\n".join(
        [
            *(render_asset(*asset) for asset in ASSETS),
            *(render_text_asset(*asset) for asset in TEXT_ASSETS),
        ]
    )
    updated = f"{before}{START}\n{generated}\n{END}{after}"
    changed = updated != source
    if changed and not check:
        AGENT.write_text(updated, encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed = update(check=args.check)
    if args.check and changed:
        print("embedded browser assets are out of date")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
