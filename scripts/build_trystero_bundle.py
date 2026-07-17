#!/usr/bin/env python3
"""Rebuild the pinned, self-contained Trystero Nostr browser IIFE."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "browser"
WORK = ROOT / ".work-trystero-build"
PROVENANCE = VENDOR / "TRYSTERO_BUILD.json"
PATCHES = (
    VENDOR / "patches" / "trystero-core-0.25.3-leave-finally.patch",
    VENDOR / "patches" / "trystero-core-0.25.3-socket-lifecycle.patch",
)
ADAPTER = VENDOR / "trystero-nostr-0.25.3.rpp.ts"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_inputs(
    record: dict[str, object],
    *,
    verify_derivatives: bool,
) -> None:
    inputs = record.get("inputs")
    if not isinstance(inputs, list):
        raise RuntimeError("Trystero provenance inputs are invalid")
    for item in inputs:
        if not isinstance(item, dict):
            raise RuntimeError("Trystero provenance input is invalid")
        path = VENDOR / str(item.get("archive", ""))
        expected = item.get("sha256")
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"Pinned bundle input failed verification: {path}")
    entry = VENDOR / str(record.get("entry", ""))
    if not entry.is_file() or sha256(entry) != record.get("entry_sha256"):
        raise RuntimeError("Pinned Trystero bundle entry failed verification")
    if verify_derivatives:
        derivatives = record.get("derivatives")
        if not isinstance(derivatives, list):
            raise RuntimeError("Trystero derivative provenance is invalid")
        for item in derivatives:
            if not isinstance(item, dict):
                raise RuntimeError("Trystero derivative provenance item is invalid")
            path = VENDOR / str(item.get("file", ""))
            if not path.is_file() or sha256(path) != item.get("sha256"):
                raise RuntimeError(
                    f"Pinned Trystero derivative failed verification: {path}"
                )


def rebuild(*, check: bool) -> bool:
    record = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    verify_inputs(record, verify_derivatives=check)
    derivatives = record.get("derivatives")
    if not isinstance(derivatives, list):
        raise RuntimeError("Trystero derivative provenance is invalid")
    if not check:
        for item in derivatives:
            if not isinstance(item, dict):
                raise RuntimeError("Trystero derivative provenance item is invalid")
            path = VENDOR / str(item.get("file", ""))
            if not path.is_file():
                raise RuntimeError(f"Missing Trystero derivative: {path}")
            item["sha256"] = sha256(path)
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is required only when rebuilding browser assets")
    patch_tool = shutil.which("patch")
    if patch_tool is None:
        raise RuntimeError("POSIX patch is required only when rebuilding assets")
    if WORK.exists():
        if WORK.is_symlink() or not WORK.is_dir():
            raise RuntimeError(f"Unsafe build workspace: {WORK}")
        shutil.rmtree(WORK)
    WORK.mkdir(mode=0o700)
    try:
        (WORK / "package.json").write_text(
            json.dumps(
                {
                    "name": "rpp-trystero-asset-build",
                    "private": True,
                    "version": "0.0.0",
                },
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        inputs = [
            str((VENDOR / item["archive"]).resolve())
            for item in record["inputs"]
        ]
        tool = record["build_tool"]
        subprocess.run(
            [
                npm,
                "install",
                "--save-exact",
                "--no-audit",
                "--no-fund",
                *inputs,
                f"{tool['package']}@{tool['version']}",
            ],
            cwd=WORK,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        for patch in PATCHES:
            subprocess.run(
                [
                    patch_tool,
                    "--batch",
                    "--forward",
                    "--fuzz=0",
                    "-p1",
                    "-i",
                    str(patch.resolve()),
                ],
                cwd=WORK,
                check=True,
                stdout=subprocess.DEVNULL,
            )
        entry = WORK / "entry.mjs"
        entry.write_bytes((VENDOR / record["entry"]).read_bytes())
        (WORK / "nostr-patched.ts").write_bytes(ADAPTER.read_bytes())
        output = WORK / "bundle.js"
        esbuild = WORK / "node_modules" / ".bin" / "esbuild"
        subprocess.run(
            [
                str(esbuild),
                str(entry),
                *record["arguments"],
                f"--outfile={output}",
            ],
            cwd=WORK,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        expected = VENDOR / record["output"]
        changed = output.read_bytes() != expected.read_bytes()
        actual_hash = sha256(output)
        if check and actual_hash != record["output_sha256"]:
            raise RuntimeError(
                f"Rebuilt Trystero digest is {actual_hash}, "
                f"expected {record['output_sha256']}"
            )
        if check:
            return changed
        if changed:
            expected.write_bytes(output.read_bytes())
        record["output_sha256"] = actual_hash
        serialized = json.dumps(record, indent=2) + "\n"
        provenance_changed = serialized != PROVENANCE.read_text(encoding="utf-8")
        if provenance_changed:
            PROVENANCE.write_text(serialized, encoding="utf-8")
        return changed or provenance_changed
    finally:
        shutil.rmtree(WORK, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        changed = rebuild(check=args.check)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Cannot rebuild Trystero browser asset: {error}")
        return 2
    if args.check and changed:
        print("Trystero browser asset differs from its deterministic rebuild")
        return 1
    print("Trystero browser asset is reproducible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
