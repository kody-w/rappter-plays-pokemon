from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import zipfile
from pathlib import Path

import pytest

from rappter_plays_pokemon.chrome_for_testing import (
    GOOGLE_STORAGE_PREFIX,
    STABLE_MANIFEST_URL,
    archive_binary_path,
    chrome_platform,
    parse_stable_manifest,
    provision_chrome_for_testing,
    validate_archive,
    validate_code_signature,
)


def manifest(version: str = "126.0.6478.0") -> bytes:
    platform = "mac-arm64"
    url = f"{GOOGLE_STORAGE_PREFIX}{version}/{platform}/chrome-{platform}.zip"
    return json.dumps(
        {
            "timestamp": "2026-07-17T00:00:00.000Z",
            "channels": {
                "Stable": {
                    "channel": "Stable",
                    "version": version,
                    "revision": "123",
                    "downloads": {
                        "chrome": [
                            {"platform": "linux64", "url": "https://example.invalid"},
                            {"platform": platform, "url": url},
                        ]
                    },
                }
            },
        }
    ).encode()


def chrome_archive(*, unsafe_name: str | None = None) -> bytes:
    output = io.BytesIO()
    binary = str(archive_binary_path("mac-arm64"))
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        executable = zipfile.ZipInfo(unsafe_name or binary)
        executable.create_system = 3
        executable.external_attr = (stat.S_IFREG | 0o755) << 16
        bundle.writestr(executable, b"synthetic chrome")
        resource = zipfile.ZipInfo(
            "chrome-mac-arm64/"
            "Google Chrome for Testing.app/Contents/Info.plist"
        )
        resource.create_system = 3
        resource.external_attr = (stat.S_IFREG | 0o644) << 16
        bundle.writestr(resource, b"synthetic plist")
    return output.getvalue()


def write_archive(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    os.chmod(path, 0o600)


def test_stable_manifest_parser_accepts_only_canonical_platform_url():
    download = parse_stable_manifest(manifest(), "mac-arm64")

    assert download.version == "126.0.6478.0"
    assert download.platform == "mac-arm64"
    assert download.url.endswith("/mac-arm64/chrome-mac-arm64.zip")
    assert chrome_platform("arm64", "Darwin") == "mac-arm64"
    assert chrome_platform("x86_64", "Darwin") == "mac-x64"
    with pytest.raises(RuntimeError, match="macOS only"):
        chrome_platform("arm64", "Linux")

    changed = json.loads(manifest())
    changed["channels"]["Stable"]["downloads"]["chrome"][1]["url"] = (
        "https://attacker.invalid/chrome.zip"
    )
    with pytest.raises(RuntimeError, match="canonical"):
        parse_stable_manifest(json.dumps(changed).encode(), "mac-arm64")


def test_archive_parser_rejects_traversal_and_accepts_expected_shape(tmp_path):
    archive = tmp_path / "chrome.zip"
    write_archive(archive, chrome_archive())
    assert validate_archive(archive, "mac-arm64") == archive_binary_path(
        "mac-arm64"
    )

    write_archive(archive, chrome_archive(unsafe_name="../escape"))
    with pytest.raises(RuntimeError, match="unsafe path"):
        validate_archive(archive, "mac-arm64")


def test_code_signature_requires_valid_google_team(tmp_path):
    codesign = tmp_path / "codesign"
    codesign.write_text("synthetic")
    app = tmp_path / "Chrome.app"
    app.mkdir()
    calls = 0

    def valid_runner(*args, **kwargs):
        nonlocal calls
        del kwargs
        calls += 1
        output = (
            ""
            if "--verify" in args[0]
            else "TeamIdentifier=EQHXZ8M8AV\n"
        )
        return subprocess.CompletedProcess(args[0], 0, "", output)

    validate_code_signature(app, codesign=codesign, runner=valid_runner)
    assert calls == 2

    def wrong_team(*args, **kwargs):
        del kwargs
        output = "" if "--verify" in args[0] else "TeamIdentifier=WRONG\n"
        return subprocess.CompletedProcess(args[0], 0, "", output)

    with pytest.raises(RuntimeError, match="not Google"):
        validate_code_signature(app, codesign=codesign, runner=wrong_team)


def test_provision_uses_private_locked_cache_and_atomic_version_install(tmp_path):
    cache = tmp_path / "cft"
    archive_payload = chrome_archive()
    fetches: list[str] = []

    def fetch(url: str, maximum: int) -> bytes:
        fetches.append(url)
        assert maximum > 0
        if url == STABLE_MANIFEST_URL:
            return manifest()
        return archive_payload

    def extract(archive: Path, destination: Path) -> None:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)
        binary = destination.joinpath(*archive_binary_path("mac-arm64").parts)
        os.chmod(binary, 0o755)

    signed: list[Path] = []
    binary = provision_chrome_for_testing(
        cache,
        target_platform="mac-arm64",
        fetch=fetch,
        extractor=extract,
        signature_validator=signed.append,
    )

    assert binary.is_file()
    assert os.access(binary, os.X_OK)
    assert len(signed) == 1
    assert signed[0].name == "Google Chrome for Testing.app"
    assert ".extract" in str(signed[0])
    assert stat.S_IMODE(cache.stat().st_mode) == 0o700
    assert stat.S_IMODE((cache / "provision.lock").stat().st_mode) == 0o600
    current = json.loads((cache / "current.json").read_text())
    assert current["platform"] == "mac-arm64"
    assert not Path(current["binary"]).is_absolute()
    assert fetches[0] == STABLE_MANIFEST_URL
    assert len(fetches) == 2

    second = provision_chrome_for_testing(
        cache,
        target_platform="mac-arm64",
        fetch=fetch,
        extractor=lambda *_: pytest.fail("existing install should be reused"),
        signature_validator=lambda *_: pytest.fail(
            "existing install should be reused"
        ),
    )
    assert second == binary
    assert len(fetches) == 3
