"""Deterministic private Chrome-for-Testing provisioning for macOS."""

from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - this project supports macOS
    fcntl = None

STABLE_MANIFEST_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/"
    "last-known-good-versions-with-downloads.json"
)
GOOGLE_STORAGE_PREFIX = (
    "https://storage.googleapis.com/chrome-for-testing-public/"
)
GOOGLE_TEAM_ID = "EQHXZ8M8AV"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 750 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20_000


@dataclass(frozen=True)
class ChromeDownload:
    version: str
    platform: str
    url: str


def default_cache_dir() -> Path:
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Caches"
            / "rappter-plays-pokemon"
            / "chrome-for-testing"
        )
    return (
        Path.home()
        / ".cache"
        / "rappter-plays-pokemon"
        / "chrome-for-testing"
    )


def chrome_platform(
    machine: str | None = None,
    system: str | None = None,
) -> str:
    current_system = system or platform.system()
    current_machine = (machine or platform.machine()).lower()
    if current_system != "Darwin":
        raise RuntimeError("Chrome-for-Testing provisioning supports macOS only")
    if current_machine in {"arm64", "aarch64"}:
        return "mac-arm64"
    if current_machine in {"x86_64", "amd64"}:
        return "mac-x64"
    raise RuntimeError(f"Unsupported macOS architecture: {current_machine}")


def parse_stable_manifest(
    payload: bytes,
    target_platform: str,
) -> ChromeDownload:
    if not 1 <= len(payload) <= MAX_MANIFEST_BYTES:
        raise RuntimeError("Chrome-for-Testing manifest size is invalid")
    try:
        root = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Chrome-for-Testing manifest is invalid JSON") from error
    if not isinstance(root, dict) or not isinstance(root.get("channels"), dict):
        raise RuntimeError("Chrome-for-Testing manifest schema changed")
    stable = root["channels"].get("Stable")
    if not isinstance(stable, dict) or stable.get("channel") != "Stable":
        raise RuntimeError("Chrome-for-Testing stable channel is unavailable")
    version = stable.get("version")
    if not (
        isinstance(version, str)
        and 1 <= len(version) <= 40
        and all(part.isdigit() for part in version.split("."))
        and len(version.split(".")) == 4
    ):
        raise RuntimeError("Chrome-for-Testing stable version is invalid")
    downloads = stable.get("downloads")
    chrome = downloads.get("chrome") if isinstance(downloads, dict) else None
    if not isinstance(chrome, list):
        raise RuntimeError("Chrome-for-Testing downloads are unavailable")
    matches = [
        item
        for item in chrome
        if isinstance(item, dict) and item.get("platform") == target_platform
    ]
    if len(matches) != 1:
        raise RuntimeError("Chrome-for-Testing platform download is ambiguous")
    url = matches[0].get("url")
    expected_prefix = f"{GOOGLE_STORAGE_PREFIX}{version}/{target_platform}/"
    if not (
        isinstance(url, str)
        and url.startswith(expected_prefix)
        and url
        == f"{expected_prefix}chrome-{target_platform}.zip"
    ):
        raise RuntimeError("Chrome-for-Testing download URL is not canonical")
    return ChromeDownload(version=version, platform=target_platform, url=url)


def archive_binary_path(target_platform: str) -> PurePosixPath:
    root = f"chrome-{target_platform}"
    return PurePosixPath(
        root,
        "Google Chrome for Testing.app",
        "Contents",
        "MacOS",
        "Google Chrome for Testing",
    )


def _safe_link_target(
    member: PurePosixPath,
    raw_target: bytes,
    expected_root: str,
) -> bool:
    try:
        target_text = raw_target.decode("utf-8")
    except UnicodeDecodeError:
        return False
    target = PurePosixPath(target_text)
    if (
        not target_text
        or len(target_text) > 1024
        or target.is_absolute()
        or "\\" in target_text
    ):
        return False
    parts: list[str] = list(member.parent.parts)
    for part in target.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if len(parts) <= 1:
                return False
            parts.pop()
        else:
            parts.append(part)
    return bool(parts and parts[0] == expected_root)


def validate_archive(
    archive: Path,
    target_platform: str,
) -> PurePosixPath:
    expected_binary = archive_binary_path(target_platform)
    expected_root = expected_binary.parts[0]
    try:
        metadata = archive.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or archive.is_symlink()
            or not 1 <= metadata.st_size <= MAX_ARCHIVE_BYTES
        ):
            raise RuntimeError("Chrome-for-Testing archive file is invalid")
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if not 1 <= len(members) <= MAX_ARCHIVE_MEMBERS:
                raise RuntimeError("Chrome-for-Testing archive member count is invalid")
            total = 0
            names: set[PurePosixPath] = set()
            for member in members:
                name = PurePosixPath(member.filename)
                if (
                    name.is_absolute()
                    or not name.parts
                    or name.parts[0] != expected_root
                    or any(part in {"", ".", ".."} for part in name.parts)
                    or "\\" in member.filename
                    or member.flag_bits & 0x1
                ):
                    raise RuntimeError(
                        "Chrome-for-Testing archive contains an unsafe path"
                    )
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    if member.file_size > 1024 or not _safe_link_target(
                        name,
                        bundle.read(member),
                        expected_root,
                    ):
                        raise RuntimeError(
                            "Chrome-for-Testing archive contains an unsafe link"
                        )
                total += member.file_size
                if (
                    total > MAX_EXTRACTED_BYTES
                    or member.file_size > MAX_EXTRACTED_BYTES
                    or (
                        member.file_size > 10 * 1024 * 1024
                        and member.compress_size > 0
                        and member.file_size / member.compress_size > 1000
                    )
                ):
                    raise RuntimeError(
                        "Chrome-for-Testing archive expansion is unsafe"
                    )
                names.add(name)
            if expected_binary not in names:
                raise RuntimeError(
                    "Chrome-for-Testing archive is missing its browser executable"
                )
            if bundle.testzip() is not None:
                raise RuntimeError("Chrome-for-Testing archive checksum failed")
    except (OSError, zipfile.BadZipFile) as error:
        raise RuntimeError("Chrome-for-Testing archive is invalid") from error
    return expected_binary


def _response_bytes(
    url: str,
    maximum: int,
    *,
    timeout: float = 60,
) -> bytes:
    parsed_request = urllib.parse.urlsplit(url)
    if (
        parsed_request.scheme != "https"
        or parsed_request.hostname
        not in {
            "googlechromelabs.github.io",
            "storage.googleapis.com",
        }
    ):
        raise RuntimeError("Chrome-for-Testing URL is not allowlisted")
    request = urllib.request.Request(  # noqa: S310 - exact HTTPS hosts above
        url,
        headers={"User-Agent": "rappter-plays-pokemon-cft/1"},
    )
    with urllib.request.urlopen(  # noqa: S310 - redirects are checked below
        request,
        timeout=timeout,
    ) as response:
        final = response.geturl()
        parsed = urllib.parse.urlsplit(final)
        if (
            parsed.scheme != "https"
            or parsed.hostname != parsed_request.hostname
        ):
            raise RuntimeError("Chrome-for-Testing download left its HTTPS host")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > maximum:
            raise RuntimeError("Chrome-for-Testing download is oversized")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                raise RuntimeError("Chrome-for-Testing download is oversized")
            chunks.append(chunk)
    return b"".join(chunks)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.download")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def cache_lock(cache: Path) -> Iterator[BinaryIO]:
    if fcntl is None:
        raise RuntimeError("Chrome-for-Testing cache locking is unavailable")
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(cache, 0o700)
    lock_path = cache / "provision.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    handle = os.fdopen(descriptor, "r+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield handle
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def extract_archive(archive: Path, destination: Path) -> None:
    ditto = Path("/usr/bin/ditto")
    if not ditto.is_file():
        raise RuntimeError("macOS ditto is unavailable")
    result = subprocess.run(
        [str(ditto), "-x", "-k", str(archive), str(destination)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("Chrome-for-Testing archive extraction failed")


def validate_code_signature(
    app: Path,
    *,
    codesign: Path = Path("/usr/bin/codesign"),
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    if not codesign.is_file():
        return
    verification = runner(
        [str(codesign), "--verify", "--deep", "--strict", str(app)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if verification.returncode:
        raise RuntimeError("Chrome-for-Testing code signature is invalid")
    details = runner(
        [str(codesign), "-dv", "--verbose=4", str(app)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = f"{details.stdout}\n{details.stderr}"
    if details.returncode or f"TeamIdentifier={GOOGLE_TEAM_ID}" not in output:
        raise RuntimeError("Chrome-for-Testing signer is not Google")


def _installed_binary(
    install: Path,
    relative_binary: PurePosixPath,
) -> Path | None:
    binary = install.joinpath(*relative_binary.parts)
    try:
        metadata = binary.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(metadata.st_mode) or binary.is_symlink():
        return None
    try:
        os.access(binary, os.X_OK)
    except OSError:
        return None
    return binary if os.access(binary, os.X_OK) else None


def provision_chrome_for_testing(
    cache: Path,
    *,
    target_platform: str | None = None,
    fetch: Callable[[str, int], bytes] | None = None,
    extractor: Callable[[Path, Path], None] = extract_archive,
    signature_validator: Callable[[Path], None] = validate_code_signature,
) -> Path:
    target = target_platform or chrome_platform()
    cache = cache.expanduser().resolve()
    fetch_bytes = fetch or (lambda url, maximum: _response_bytes(url, maximum))
    with cache_lock(cache):
        manifest_path = cache / "stable-manifest.json"
        try:
            manifest_payload = fetch_bytes(
                STABLE_MANIFEST_URL,
                MAX_MANIFEST_BYTES,
            )
            download = parse_stable_manifest(manifest_payload, target)
            _atomic_bytes(manifest_path, manifest_payload)
        except Exception as error:
            try:
                cached = manifest_path.read_bytes()
                download = parse_stable_manifest(cached, target)
            except (OSError, RuntimeError) as cached_error:
                raise RuntimeError(
                    "Could not obtain a valid Chrome-for-Testing manifest"
                ) from (error if isinstance(error, Exception) else cached_error)

        versions = cache / "versions"
        downloads = cache / "downloads"
        versions.mkdir(mode=0o700, exist_ok=True)
        downloads.mkdir(mode=0o700, exist_ok=True)
        install_name = f"{download.version}-{download.platform}"
        install = versions / install_name
        relative_binary = archive_binary_path(download.platform)
        existing = _installed_binary(install, relative_binary)
        if existing:
            return existing

        archive = downloads / f"{install_name}.zip"
        try:
            validate_archive(archive, download.platform)
        except RuntimeError:
            archive.unlink(missing_ok=True)
            payload = fetch_bytes(download.url, MAX_ARCHIVE_BYTES)
            _atomic_bytes(archive, payload)
            validate_archive(archive, download.platform)

        staging = versions / f".{install_name}.{os.getpid()}.extract"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        try:
            extractor(archive, staging)
            binary = _installed_binary(staging, relative_binary)
            if binary is None:
                raise RuntimeError(
                    "Extracted Chrome-for-Testing executable is invalid"
                )
            app = staging / relative_binary.parts[0] / relative_binary.parts[1]
            signature_validator(app)
            if install.exists():
                shutil.rmtree(install)
            os.replace(staging, install)
            binary = _installed_binary(install, relative_binary)
            if binary is None:
                raise RuntimeError("Installed Chrome-for-Testing is invalid")
            current = {
                "schema_version": 1,
                "version": download.version,
                "platform": download.platform,
                "binary": str(binary.relative_to(cache)),
            }
            _atomic_bytes(
                cache / "current.json",
                json.dumps(current, indent=2, sort_keys=True).encode("utf-8"),
            )
            return binary
        finally:
            if staging.exists():
                shutil.rmtree(staging)
