"""Minimal obs-websocket v5 client for the livestream watchdog.

Reads the websocket password straight out of the local OBS plugin config so no
secret ever lands in the repo. Only the handful of requests the watchdog needs
are wrapped; everything else goes through `request()`.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path

OBS_CONFIG = Path.home() / (
    "Library/Application Support/obs-studio/plugin_config/obs-websocket/config.json"
)
POKEMON_PROFILE = "Rappter Plays Pokemon"
POKEMON_COLLECTION = "Rappter Plays Pokemon"


class ObsError(RuntimeError):
    pass


def load_ws_config() -> tuple[str, str | None]:
    """Return (url, password) for the local obs-websocket server."""
    if not OBS_CONFIG.exists():
        raise ObsError(f"obs-websocket config not found at {OBS_CONFIG}")
    cfg = json.loads(OBS_CONFIG.read_text())
    if not cfg.get("server_enabled"):
        raise ObsError("obs-websocket server is disabled in OBS settings")
    port = cfg.get("server_port", 4455)
    password = cfg.get("server_password") if cfg.get("auth_required") else None
    return f"ws://127.0.0.1:{port}", password


def _auth_string(password: str, salt: str, challenge: str) -> str:
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest())
    return base64.b64encode(
        hashlib.sha256(secret + challenge.encode()).digest()
    ).decode()


class ObsClient:
    """Async context manager holding one identified obs-websocket session."""

    def __init__(self, url: str, password: str | None):
        self.url = url
        self.password = password
        self._ws = None
        self._seq = 0

    async def __aenter__(self) -> "ObsClient":
        import websockets

        self._ws = await websockets.connect(
            self.url, open_timeout=8, close_timeout=4, max_size=8 * 1024 * 1024
        )
        hello = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=8))
        if hello.get("op") != 0:
            raise ObsError(f"expected Hello, got op={hello.get('op')}")
        payload = {"rpcVersion": hello["d"].get("rpcVersion", 1)}
        auth = hello["d"].get("authentication")
        if auth:
            if not self.password:
                raise ObsError("OBS requires a websocket password but none is stored")
            payload["authentication"] = _auth_string(
                self.password, auth["salt"], auth["challenge"]
            )
        await self._ws.send(json.dumps({"op": 1, "d": payload}))
        ident = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=8))
        if ident.get("op") != 2:
            raise ObsError(f"obs-websocket identify failed: {ident}")
        return self

    async def __aexit__(self, *exc) -> None:
        if self._ws is not None:
            await self._ws.close()

    async def request(self, request_type: str, data: dict | None = None) -> dict:
        self._seq += 1
        request_id = f"wd-{self._seq}"
        await self._ws.send(
            json.dumps(
                {
                    "op": 6,
                    "d": {
                        "requestType": request_type,
                        "requestId": request_id,
                        "requestData": data or {},
                    },
                }
            )
        )
        # Events (op 5) can interleave with responses; skip until ours arrives.
        while True:
            msg = json.loads(await asyncio.wait_for(self._ws.recv(), timeout=20))
            if msg.get("op") != 7:
                continue
            body = msg["d"]
            if body.get("requestId") != request_id:
                continue
            status = body.get("requestStatus", {})
            if not status.get("result"):
                raise ObsError(
                    f"{request_type} failed: "
                    f"{status.get('code')} {status.get('comment')}"
                )
            return body.get("responseData") or {}

    # -- the specific calls the watchdog needs -----------------------------

    async def status(self) -> dict:
        stream = await self.request("GetStreamStatus")
        record = await self.request("GetRecordStatus")
        profiles = await self.request("GetProfileList")
        collections = await self.request("GetSceneCollectionList")
        return {
            "streaming": bool(stream.get("outputActive")),
            "stream_congestion": stream.get("outputCongestion"),
            "stream_skipped_frames": stream.get("outputSkippedFrames"),
            "stream_total_frames": stream.get("outputTotalFrames"),
            "recording": bool(record.get("outputActive")),
            "profile": profiles.get("currentProfileName"),
            "profiles": profiles.get("profiles", []),
            "collection": collections.get("currentSceneCollectionName"),
            "collections": collections.get("sceneCollections", []),
        }

    async def ensure_pokemon_profile(self, twitch_key: str) -> list[str]:
        """Switch OBS onto the dedicated Pokemon profile + collection.

        Returns a list of the actions actually taken. Creates the profile on
        first run; the Private Coding profile is never modified.
        """
        actions: list[str] = []
        state = await self.status()

        if POKEMON_PROFILE not in state["profiles"]:
            await self.request("CreateProfile", {"profileName": POKEMON_PROFILE})
            actions.append(f"created OBS profile {POKEMON_PROFILE!r}")
            state = await self.status()

        if state["profile"] != POKEMON_PROFILE:
            await self.request("SetCurrentProfile", {"profileName": POKEMON_PROFILE})
            actions.append(f"switched OBS profile to {POKEMON_PROFILE!r}")

        # Always (re)assert the service settings: a freshly created profile has
        # no key, and this is scoped to the Pokemon profile we just selected.
        await self.request(
            "SetStreamServiceSettings",
            {
                "streamServiceType": "rtmp_common",
                "streamServiceSettings": {
                    "service": "Twitch",
                    "server": "auto",
                    "key": twitch_key,
                },
            },
        )
        actions.append("applied Twitch service settings to the Pokemon profile")

        if POKEMON_COLLECTION not in state["collections"]:
            raise ObsError(
                f"scene collection {POKEMON_COLLECTION!r} is missing from OBS "
                f"(have: {', '.join(state['collections'])})"
            )
        if state["collection"] != POKEMON_COLLECTION:
            await self.request(
                "SetCurrentSceneCollection",
                {"sceneCollectionName": POKEMON_COLLECTION},
            )
            actions.append(f"switched scene collection to {POKEMON_COLLECTION!r}")
            # Collection swaps reload sources; give the UDP relay a moment.
            await asyncio.sleep(3)

        return actions

    async def start_stream(self) -> None:
        await self.request("StartStream")


async def connect() -> ObsClient:
    url, password = load_ws_config()
    return ObsClient(url, password)


async def _export_key(dest: Path) -> dict:
    """Copy the current profile's Twitch key into `dest` (mode 600).

    Saves scraping the key out of the Twitch dashboard: OBS already stores it
    for whichever Twitch profile is loaded, and a channel has one key.
    """
    client = await connect()
    async with client as obs:
        state = await obs.status()
        svc = await obs.request("GetStreamServiceSettings")
        settings = svc.get("streamServiceSettings", {})
        key = settings.get("key")
        info = {
            "source_profile": state["profile"],
            "service": settings.get("service"),
            "type": svc.get("streamServiceType"),
        }
        if not key:
            info["error"] = f"profile {state['profile']!r} has no stream key stored"
            return info
        if settings.get("service") != "Twitch":
            info["error"] = f"profile streams to {settings.get('service')!r}, not Twitch"
            return info
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(key + "\n")
        dest.chmod(0o600)
        info["wrote"] = str(dest)
        info["key_preview"] = key[:9] + "..." + key[-4:]  # never the whole key
        return info


if __name__ == "__main__":
    import asyncio as _asyncio
    import sys as _sys

    if len(_sys.argv) > 1 and _sys.argv[1] == "export-key":
        target = Path(
            _sys.argv[2]
            if len(_sys.argv) > 2
            else Path.home() / ".openrappter/pokemon-red/twitch-key.txt"
        )
        print(json.dumps(_asyncio.run(_export_key(target)), indent=2))
    else:
        print("usage: obs_control.py export-key [dest]")
