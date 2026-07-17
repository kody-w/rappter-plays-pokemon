"""A real OpenRappter agent that lets GitHub Copilot play Pokemon Red via PyBoy.

Users must explicitly provide their own legally obtained ROM. The ROM is never
copied, attached to Copilot, served by the viewer, or included in this project.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import http.server
import importlib.util
import io
import ipaddress
import json
import logging
import os
import queue
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import webbrowser
import zlib
from collections import deque
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Optional

from openrappter.agents.basic_agent import BasicAgent

try:
    import fcntl
except (
    ImportError
):  # pragma: no cover - OpenRappter's Pokemon runtime targets Unix/macOS
    fcntl = None


LOGGER = logging.getLogger("openrappter.pokemon")
MODULE_NAME = "openrappter.agents.pokemon_agent"
VALID_BUTTONS = ("a", "b", "start", "select", "up", "down", "left", "right")
BADGE_NAMES = (
    "Boulder",
    "Cascade",
    "Thunder",
    "Rainbow",
    "Soul",
    "Marsh",
    "Volcano",
    "Earth",
)
DEFAULT_RUNTIME_DIR = Path.home() / ".openrappter" / "pokemon-red"
DEFAULT_PORT = 8765
DEFAULT_SPECTATOR_PORT = 8766
DEFAULT_MAX_VIEWERS = 5
DEFAULT_LIVESTREAM_HOST = "kite"
DEFAULT_SIGNALING = "nostr"
DEFAULT_PAGES_WATCH_BASE = (
    "https://kody-w.github.io/rappter-plays-pokemon/watch/v2/"
)
DEFAULT_PAGES_HOST_BASE = (
    "https://kody-w.github.io/rappter-plays-pokemon/host/v2/"
)
DEFAULT_BRIDGE_STARTUP_TIMEOUT_SECONDS = 20.0
HARD_MAX_VIEWERS = 8
HARD_MAX_NEGOTIATING = 16
LEGACY_LIVESTREAM_PROTOCOL_VERSION = 1
LIVESTREAM_PROTOCOL_VERSION = 2
LIVESTREAM_FRAME_RATE = 10
MAX_WATCH_HELLO_BYTES = 512
TELEMETRY_VERSION = 1
MAX_TELEMETRY_BYTES = 4096
TELEMETRY_CHANGE_INTERVAL_SECONDS = 1
TELEMETRY_HEARTBEAT_SECONDS = 5
TELEMETRY_STALE_SECONDS = 12
DASHBOARD_SNAPSHOT_KEYS = (
    "location",
    "objective",
    "phase",
    "badges",
    "pokedex",
    "party",
    "completed",
    "player",
    "play_time",
    "session_elapsed_seconds",
    "checkpoint",
    "viewers",
)
TELEMETRY_MESSAGE_KEYS = (
    "v",
    "type",
    "telemetry_version",
    "sequence",
    "snapshot",
)
LIVESTREAM_LEASE_TTL_SECONDS = 120
LIVESTREAM_HEARTBEAT_SECONDS = 15
LIVESTREAM_REPORT_STALE_SECONDS = 120
KITE_HOST_REPORT_STALE_SECONDS = 10
KITE_STRING_SCHEMA_VERSION = 2
MAX_KITE_FRAME_BYTES = 128 * 1024
MAX_MANUAL_ANSWER_BYTES = 384 * 1024
MAX_MANUAL_RETURN_REQUEST_BYTES = 512 * 1024
MAX_MANUAL_RETURN_QUEUE = 32
SPECTATOR_MAX_CONNECTIONS = 16
SPECTATOR_SOCKET_TIMEOUT_SECONDS = 5
PEERJS_VERSION = "1.5.5"
QRIOUS_VERSION = "4.0.2"
TRYSTERO_NOSTR_VERSION = "0.25.3"
TRYSTERO_NOSTR_COMMIT = "f76eb4fca528a3253e2bdfd6d41b54c8131ca11e"
TRYSTERO_NOSTR_RUNTIME_SHA256_BYTES = (
    b"3a4f689e5cc156f92d118a1860bc0cd77a60db220b6521b9f60b3b6fb36b2b9d"
)
TRYSTERO_NOSTR_RUNTIME_SHA256 = TRYSTERO_NOSTR_RUNTIME_SHA256_BYTES.decode(
    "utf-8"
)
NOSTR_RELAY_URLS = (
    "wss://communities.nos.social",
    "wss://purplerelay.com",
    "wss://bucket.coracle.social",
    "wss://relay.nostr.place",
    "wss://relay.damus.io",
)
PEERJS_SHA256 = "7604d8c31bec4f134b0d15c2d80b1d095ea18af005354f439f14291fcd7b4168"
PEERJS_RUNTIME_SHA256 = (
    "95f57b9e94e1b96c829145b3f3ef0d04b332c9bda0567e144bed70d13712e3d0"
)
QRIOUS_SHA256 = "db99dcaf40a926181bce4522477c2efc5924f6c4b29111b6a97faea477c9528b"
QRIOUS_RUNTIME_SHA256 = (
    "c46f564908ff10943a59e6f56f5de4bc5b6e827813b4750eef55353e7085157c"
)
PEERJS_SIGNAL_HTTPS = "https://0.peerjs.com"
PEERJS_SIGNAL_WSS = "wss://0.peerjs.com"
PEERJS_ICE_CONFIG = {
    "iceServers": [
        {"urls": "stun:stun.l.google.com:19302"},
        {
            "urls": [
                "turn:us-0.turn.peerjs.com:3478",
                "turn:eu-0.turn.peerjs.com:3478",
            ],
            "username": "peerjs",
            "credential": "peerjsp",
        },
    ],
}
RTC_CONFIG = PEERJS_ICE_CONFIG
MAX_BUTTONS_PER_DECISION = 16
MAX_DECISIONS_PER_SESSION = 24
COPILOT_START_TIMEOUT_SECONDS = 90
COPILOT_STOP_TIMEOUT_SECONDS = 15
COPILOT_THREAD_SHUTDOWN_TIMEOUT_SECONDS = COPILOT_STOP_TIMEOUT_SECONDS * 3 + 5
COPILOT_DOWNLOAD_TIMEOUT_SECONDS = 180
RECORDER_QUEUE_SECONDS = 2
RECORDER_WRITER_TIMEOUT_SECONDS = 5
SUPERVISOR_SHUTDOWN_TIMEOUT_SECONDS = COPILOT_THREAD_SHUTDOWN_TIMEOUT_SECONDS + 40
DEFAULT_MAX_CLIPS = 200
DEFAULT_MAX_STATES = 256
DEFAULT_MAX_STORAGE_GB = 20.0
DEFAULT_MIN_FREE_GB = 2.0
STATUS_HEARTBEAT_FRESH_SECONDS = 15
SUPERVISOR_HEARTBEAT_TIMEOUT_SECONDS = 45
SUPERVISOR_STARTUP_TIMEOUT_SECONDS = 180
SUPERVISOR_STALE_HEARTBEAT_EXIT = 75
RESTART_REQUEST_NAME = "restart-request.json"
GENERATED_CLIP_RE = re.compile(r"^clip-\d{4,}-\d{8}-\d{6}(?:-\d{6})?\.mp4$")
GENERATED_STATE_RE = re.compile(r"^state-\d{8}-\d{6}-\d{6}\.state$")
GENERATED_PARTIAL_RE = re.compile(
    r"^\.clip-\d{4,}-\d{8}-\d{6}(?:-\d{6})?\.mp4\.partial\.mp4$"
)


# BEGIN GENERATED BROWSER ASSETS
PEERJS_MIN_JS = zlib.decompress(base64.b64decode(  # generated from peerjs-1.5.5.min.js
    b"eNrtvWlj2ziSMPx9f4XM7ddDjmlFsnM1FUaPO3Z6PJ1rY6fn8HodWoJtTmRSQ1JJ3DKf3/5WFW4S"
    b"lOV0Tz/X9u7EIlC4CkChqlBV8P0gfr68WGSTKs2zHvNZWIVZWATLt+f/YJOqP2UXacbeFfmcFdUN"
    b"ZS8vWRVlYQn/FiHLFtesSM5nLNoYhJM8u0gvF/K7DmpVdeWzYFmwalFAM5ubrH92xsrX+XQxY2OG"
    b"zSSLWRWxejJLyrKXLaGqsioWkyov/GBZXaVlf3K1yD6x6evjD/Hw8e5gEFLq2TSpkhf5IqviYajh"
    b"YgYDm7GqV8Unp2EWs/75TcVeseyyugqL+HVSXfUnLJ352YNG5UGYxoOwjAejC2h7VD7LRgHVlPNS"
    b"12nmw/C3WsUSaKScpRPml2EehJN4eXY2Z6zYhw5Gjb6GWZSG+BUlYZVXySwq6lHVny/KK38SQOt5"
    b"mG5t1QJhjcJbW2FV1wJVxTKZz1k2PTtfXFywAtFM4BczrCsQSJonRVXy6llQ8xIK9GyesgnT2aLo"
    b"Mr3wrfwZYe/5gKODxRn70vuQZtXTvaJIbizYYORoNzQhYFrqusqp6A+867Lek1NCPc1eL7/oGVUF"
    b"jFdWBSOBG7nCcDR8vgeqdIalWVBtxZkx/SPKavU+gGUxsBtmXSPtc2SHFVX79uICdoP44G0Eo6wP"
    b"abBhCqh3Kzbz5KxmNfRZ1FQ71jvLJvmUFdT4MftaHfDvJhbNGSakqj2XGnsOK8mxvUU2TyaffGNr"
    b"lhp1CJXAboGViEBMYRkqg/4l2YQBWoAcXKclG2f96oplPtKQqg9UQU5jEFmfYqHmS9k0R2pYxdRz"
    b"nnq2QPT6wQgX3bPhztNArn1M8Xd2Hv5XFTzb3RHJImF7d4eyGVCEAQLEw0eBuWlE5UXyBQcjQJ88"
    b"XgEKs5Bmlwb0w4croBNaDxp45+kK4OtkjqDll7Sa4BJeTpKS9Ybf70QSy4vZbCQSdyP6sTPckT9U"
    b"ykP545EoKMs8FN8bQ5kiITYGPGVnoBoze3Yxy5MKkC9gdl0w03wBZF0DPXQByVkUMI+6YIaPNdDj"
    b"LqDdHQ30pAvo8UMN9NQFZPfo+w4Qo0PDQQeM0Z/hsAPG6M5QDYzFrvGH7mUnCj/pLoz9WF346T1a"
    b"FntDlPz+Hs1aJXcG92hTbRtRdniPVptld+7RrtiBouTuPVrlJevaXufieNh59GiTgPGI/jllX07o"
    b"K82m7OvpyFwolATnN6sb3RQ1EVDBkqm/A+3HPtbMTganwR93Hj3eEp/D08BRabwDXEFjCK1aH1Kt"
    b"UM/jP2K1W1QZ1c1OdtSvXVen44d2/bjSW/U/5fXjf3e2IX89VL8eqV+P1a8nzr481X2xZsJFi+Qk"
    b"46kyZhHbhopre+d3lCaioIrv7jx5zCt4/OjRrllFE9VNGqaqGHx9OuD/UT2Dr0PxOahtEtJRG1EX"
    b"R20Du9aLxn+1tWEVX8f5uWcGXoFXuiryL72DogA+5OMPaZYUN++g6MsknS0KFvUIrpfCcb4gFqlI"
    b"skvW+26pK6nhi9UyibdRfwxGnMNQ24RzB4Jh1qVDqzeuqWd66hXd4+wLSi7GWmSSk/c8zsqnz9go"
    b"8Ku4OElPg2fAMYx9YHWQ0Q4iH45hzmFgor873ISPZ49vH+9uAvjW8BTA4h2AE5zI8DHBDR8R3HDn"
    b"1leQZrkdKrcL5QD4CYd9asMaZXessrtUFnZsuRUf0Uj7F8B5vQAm8F0Oi8HPOvBT1g1SKbi7PUk5"
    b"FX8MDG8GSMkAA9VJdmquN73QFLo5DRSVLeuOaqw67qpSMB53bx5/EMfs+fPd4XgYbQ+DP/pPd58+"
    b"fTx4sslu+a+nQDD++Edgwp4/39ndBEIZbA93nmzv7AZ1g4FZ0ZiDJ6VkmDysd7AJbM8TqHiws9vV"
    b"L384ePj00ROg07f812PesWx7ZxBsVeL3o50gqMUqXRo7g+aQeOAt9iw2dpDFT8pjpl8uzvkcg/SB"
    b"28XcvZ5j92KLYgub+9cLLPlDyoUEGAs5W+9Z3IFmL5xyoAYX5ygfRmv/G2KRkBOSpSE7LC0JmMtK"
    b"PyzSGchB/YbwWAuRBcmbxymDF8fVzZxxIRBraHBLbAZ8AIJni+tzVpjgJOrD6iR0xDDHY10BDJVd"
    b"kqgd6USxusxaz/N8xpLMrHZjoOtqDEcI5cCzB9HGEME2N1fCPdRNfc7TaY+qDlYW2TF6l5OGx+wc"
    b"pKIEsnY1YuGyvrF4cO0yU1ikObLWeEtwqhzCpVrvhozp6JJQVQS1HFa7bbEKddPnqMCxlywLDMT8"
    b"8Lfjg6Ozdwfvzw5eHbw+eHPspZm1gFwVSI0AMzUCptLJaMHq435SuRYnrG5O8/2ugj/M8nOJJdZP"
    b"zK3AcYYasLtGHa5Aaq0bruKYKwRvbyujZ33oTFGVf0mrK9+j3esF7anmC+23nmuLUTmGJdzzgOUw"
    b"Old7vSyvejfQm3Ixn+dFxaYfVxYW+8BdcLQKUwrDipozQfC4PgMVAhohnDEF/mOrMlD8LEa28tGq"
    b"nQeCnZgxk0W1K9Hc3+qavm/WBAedrMk6Rg6zz8kMyAsfj+dGRFMHWbv4M74mziqtyxI6LmTVUOmk"
    b"UZa5Ufbk8VamR5uthbLHDpTZlayLsicOlGW/EcoqgbIGy7bGMnr48N7LCDiR32gZ7Qy/eRlxzrEA"
    b"IgUtFs+qFuHw2UlhSLouDaRBMTK/2BoGQcT/1rXSXPoDgVp9bGOL7Hm8vbuzuQlsFvCJKweJQrdB"
    b"hJ/HAyqGPOaqYoOHTdw89e16gEN9ulYPBta+d9TEe3T3zA8eOWa+0SmSc6k+/HVHx75vdKxVHe/Z"
    b"mstp8NixnBrd01KvqPnJWpt30OjoqooHdgPN5NUNDRsNgcy+GiPrYaZFfIx6nRtNLHdPrH7Fn6pb"
    b"EvYMeuLjtRmLt5nckAbjSz9nORLwB/T71ZudQF6ecRCfPQCBJkPJx1BmcCyB9F09e7Y7vM22UGB6"
    b"9mxncFs8MMA2hag0Wjnw3fbEpe2k4v8zKhZDVoyHGLK40/zEbsq1T5ydp/c+cXZ2fqsTZ2f3m08c"
    b"HHERZ5y6Zs/kSDkqYGJA2idWvX+VlG+/ZOqGNw0CzTTC16hNlNPT+3ByhZ8hXZaXXvxTk+dCkWdJ"
    b"IJcrMMIMWKI0K4GfP3/qZnAtwl7btEZuj1u2aln6OINiFVfB8+fPdx6ubErBc2jFlHRAP36081SA"
    b"3j2EyhgCEQXJO5h7Da/AzS3yf87gwjV7mt2rp9n6Pc3W62mm2Yy7lrG58NZZyaIjLLjPilYLevUW"
    b"AZSRtmw9tLH10cbWQ5vRXXPxmvoXcx0H/72Qf4eF7LBGsOFJ5ydNEQyBrmmsUNfeAs4qFAQnlUeH"
    b"ySTeGIRz+GekLBCm3O6Iz30BQs91wm/I1SmxuVlI85M429ycJ0XJDrPKL+AcC4G309YMM1kXHFEb"
    b"rP/++MU7xooXeZYxAhBH1Eg21QLoz4u8ylEZAAwMIGY6PfjMsupVWlYsY8WonRRrGxQ0ncJjdSOO"
    b"K3kYpojcGdeLhklxubiGsiU/WUvDTgm1B6MKWLICDuVsOmPUyNj6ApxEKCwGtaX6P2OY+TqZx/bn"
    b"7e2yDu2kk+r09tZvpdHEwc+gDU6GLEVYAkNnjuSEheUp9IMPo+gX7Dr/zJq4cqSa6Mo0um5vN5qd"
    b"33B0vZ2GLAxwRRLd5Qp0F3G79CVr3aRY+VMGJRmAhKhgdWAn/YVtbnKodnEqZDKeNkQgVnVHBWHZ"
    b"wDgIxHXots0rQi/PvC1uoGdrzk+8M8o6rUMySuJbWqWiFMBvzVpzhRcLJmgQGv00UqWuurk1muVj"
    b"IPfrGw1eaQMmpUzfUPrqseB998Qc9zAj6kEzAmDL6/feQSEgQEiEkp6oo+8FkT+JWcjGXjJN5hXQ"
    b"v3+UPZB0LtPssjdNS+zL1ItcuSzjmUY3F//CbgKhZKHZjymbF2ySUMNfkiKDPpVQmQ9jMTqueml0"
    b"8wIWRUvr/yXNpvkXWAGT21tvkfE1NdXdx5MAerO56cl6dFmRhyLi5qbxIdasSDH2oNGZayTTwXKu"
    b"C+JgfEAGXi7LQbJp2Jtr1ADOMB/OJpZM++YUnBlTcMLH2OPb5NTTG1BRdqUm7k+S2YxsHmVNl/ZZ"
    b"lI29fFGd54Ca7aKaA2rTTH/BCSHo5khfnmjCL2jjiTJhYP2LvDhI4GxDsu9VBXA+2D/oEPQKzWIp"
    b"6XAK6EovUqCVUF0/nW5uauvMAIiCrKWCWnSdKO1lVBMUgyMzk7WpWgxLX2Hnu5Hd3hacggJEAEdD"
    b"QfQevwALoUm6skA1laJg2QeOQSj/D2GpjbHSitNTFBKh+siGKb0AegV5VpeNYlgGCAAsFDwbwpQ+"
    b"wtRmIj4nRe+G7p/laF7wxcQVGITGLPmcXibiPmoj61+zaZrss88p2qZaHIBpP2pci+n9e3uL/Eg2"
    b"xdpu8COfI3wyU5cvI3UjLlJsRYM1WGyiYP9cpAXDiQfsw+b+jFL0VH5TX4/yRTHhIHZ/2/d2wAKN"
    b"8Z9omU5ZMovwdz3iV4JwsBZ99jWZAF/RuuVUOTDn12kGkNfJVwnPD8zUPKwrbcE9ZltVf3KVFHsV"
    b"CPCwnT4A/1i8gI3qB5DDrTqGQeRNCeeHNLhq7JU0LPiMqnqkLi6pl9R5OJkUfmP98/YW9hC/tgcs"
    b"OwZChceonPA9GIoHS/dU1hnqepQlso8VBQSdfLWgg4gquauGuhu/Gw38jv1KL6C4MhcTcmf622yX"
    b"z0F0wkdDvTy1iIdu/4TRCb52G4w3AcX49mJ9uQKpGoV+38Z/gNe8QJN9DY/3h3VorZGUmxf1P7Oi"
    b"hJTn8eOhIofaTvbPR2/f9ImJ9+knvyhKL+hOEmhEe5H3k8U0zaV0aC5KpNWoi0K3gg0/o19QhY/b"
    b"IGbIggmWBX8Dv1rd3QHeGBy7iyr/MUkzEA6qIp/BPFzm+eVeIxWQ4DNZJMvTkh0t5nB+lYgAUeZN"
    b"M5nQjkXiQhYOamSFnYP/DMtQDB4kBv7Zv0gm0OfXIGaNyriEEbcKluNSEoWy5hs6j9XcPHv8GKeD"
    b"SgJ9xf0Ul3zhARVi2ee0yDM8uO0MDUo1u0D5RqLpsCgvEvkjeaX6gmRMwGNV4lG1DpwfGIOG6nN5"
    b"24zjkLPcwk7YPRZ3z8dVfOKd49EcAq1OCu80cmGogYiAlOkn3gVUWHlw/Ck+oDE4wf5WTCTI+/pM"
    b"SIJ5DD+z/kU6q/C2Kn7u0YjSbL6oOLPwCZg2WKXAqk0xH+htfs2QGQD2KzlnM6DHr/Ivkh7302wy"
    b"W0yhIZAbpaCzkSPSpfBRaRg+cBxMHmcnEmR7CAPKcVcJ9Eq6LvExXtKfSOfUcukZSbjqqTyter6q"
    b"QzgRJ1cFjACZ4vZuDFPieup2SalTXquCsLSOeqWo1oTq4ZhFyyyBavzlO1Zcp7RT91mWsinx8JH3"
    b"Jq/2ZjNALU/wQgMuLfFXN6hQ0R9VMPNdMGJFQPpL5DE1mP70Qr0hIOMIJIHyQvfwLYxnIgFUvcfI"
    b"Bx6hsYau8j3w0CgkCJDXeomiuRib7i/YcX50tahAPsgcfTUK/JTOZkfk1fDWBXmcnL8A+WVRyHHv"
    b"neeiJ154NCkYy7rzeQud+XCII7d3zU6RNcMf4TWQ2OSSRcC28V+hQkgVSWMl/MAS+usNltXmI5bl"
    b"Gda7xYVkUSeQaVhtwZaZVtfE02RIvj4AcSAMxb51WKF+CH4wYtW/sPNPafWjAU0wmIkaLx+5Rzqj"
    b"66B/jpsdGOQ2pVSFlbdSN4ioxuaHRysK6E2jub8UGXYgNpCkLY3o1KdzDAgzwzr28INWHpI4TkfQ"
    b"fog2rwT6GT8aQMIImfJVlsn7MNjg+RwtlEIUv/bfvj74OmHEqyAH1dgw2mK6RtSKq6p+weh2kHAM"
    b"WG5oKpVs8RmpBesTMmBtsOQ6tr5wEfF5NBK1OHm+Qq5wqSfhXEG2AmkwMjKr1JMBqjqFDIkD80l6"
    b"zMoJS4EI3N52uXB6BpQXLoEqLYDwgbxNKRFihv+skV4L87Muh9CV+lM1FIdOqn8mMi2dlEoV+iSX"
    b"SkoO2YIXesuW/skJvI4WaiQNcFYMECXl99BDPMrLSZHSChzdv4jeZG4UzfPZjVLaGmkxyv8Vnnaw"
    b"5hxjhxQxfMlbFKM7dN64596L+S+5naqZ4muuQ+gqlNICuCCUVtVHEC3pZySSaiFQ4o7lumwxNyAU"
    b"cAhZOEzVEoyLMDVXdazXaQGShxh6GZ9ILAh3yGlazvEOgTeEeoRQ4clFVX5H/JiYWQcn/xJs1F3b"
    b"BVJ40caWweWG4p5buV4bXqfHDYqnxRhERQu1KCV4yO+zbAoIvJvqwckLLAOyz8evX/JSdxdyyI1y"
    b"q4m5qELoRG9aXV/oTajMqoUDNmSisESnHCk0iBMf61y0hW70DW9sDADUEco7Fkyow7P5JGKcc9i4"
    b"c+kJLOGJtB5kJ2kpRb71hXJ+aKUIVY6458nu2BywemhrjdYDa1ycib3QcX8jmQ8ghGlc8WzlUy57"
    b"S9qZFHn+ep0bPnG+rNNnA9IWJFZcN1U2drlDxdsL1INsD/HOS1r4K2TPuTtUiCYyayKccxyjNeGs"
    b"vt+1EjL79gnveTp5Msc8qElCgnOP6VhrRCbovQZV3GNQrkkk+l6h1M0JNHpLjDpn0jn/VYATDFPc"
    b"7YzRQSvvQym/hVCKZt9Xc16AqDPSKVVSZRnUVVsrr0eURt9CvYTXljV72jzYullhfSCqNG0wuV33"
    b"pV2jCfl4GyzrnUcBJvNzvnkmiPgME8fRoAqtPiNwqajz9Uicrxvrr5rmnMpvybbIu/MRrxbxXyVV"
    b"+dvOeUXao99x3oP7HVnZnf1rH1ta4l55Zul+YbfCLpz2JeIdw4eytokCrCcJLhWIQJQuffQ64lz0"
    b"xgDF2u4plbP/LZOqGN71plWB/zYTG7YlX8kIEyBIWcXkYMZwFvD4CbuH/FvjfLga580pFxR9nakx"
    b"bgHX2XVY5Wg9MHPo0HW1flXAn81NlXYyODXMfi1NCO0NFdyFnLHNYtJhVspMYqsbJy6XZuWpWuDC"
    b"GmfxxiCCuSAJziVt6UXiM6tsxcsCroLQyIHVkN3eor1KMG6ogtq6pOMrVrBeAv+7zgs0ekmyXp6x"
    b"Hj/Qe3nRk+uuBx2BfIChM8ALpUn23mTCylJoooIIo13pNRRV48r8XLNDadnL8m/vhAor1SXMqbPm"
    b"E1d+3bGIXuWTZHYkZM9OeeMqvb5mUwu2M4duLdtWUw7IoE9e6dJj0AEBLB4G0KjX2jm/QoARJodZ"
    b"sBq7o29Eh7RfW33SdGMBFQ+n4+2hYmE6gRSbWgSKq+2EJUa/kOxLJ1x8AuQAeO+1xchfL9Xce711"
    b"iwEyYIZNtRxygNBcO/YtgvSSGTrg3/TY17QE8tqxP2tLeDTbHGV32zY2+ijvEPnEGxLoioV4wviU"
    b"sVN55V/8jvLbr6Qalh1l5+DCDrFdKuT+5VqDXzdIOL7WpI7m2cq3XjdmqtOWhiJbRQHQ+JWLuRnI"
    b"s+Fq0gLATlNXN2zdMDZ2nk7vuRrvDkNv8nJah5jjNbi+DVYR3CgM3jpUq3ESjr753GzLFA36XjDs"
    b"J7PXip0oKJp1ONoQfCOsubF/BUWujECSpb26ja7eb2DV/zakOtxw4rYi3C51pEmLU/at/itKbJaN"
    b"MydKxGmK969ZbWuyqtN7US8xnWYUSG1DWfXL6dxpzdieDrQMa1IZXE4tlJyG2DM1TLStOx2hpUvB"
    b"5rMEqMh7dnnwde6naHrqXXpBiCDykhdGdMSERYa6OPMpaENUkdFrCH2OMrIU+TWKw99oidq+EvYM"
    b"084DIcQ2p29jrF1o7EiD/0X8ULMJqwlTh/dlaKUPjTeZ5SU3TqV6y/Qyg32QXZIhS/cuAimk1eAf"
    b"yp5dHCWZP/AG/mDsMW0jozxZT075TQQ32FbHAZw7SOCHZIcpTQw2CmD4bQoh7+TIPHtlpw1Te4mU"
    b"Hl5+ASs1A9lvdiODgkA+jCa7nLFej+O69+UqnVzhmJKyzCcp2q/3vqTVFclk5ZxN0KZ7qqUztN+R"
    b"Zm5yuN0ETN8p3jGKexCw0W+66AX5sdcfUSwcVhqkap2hClwLu2U++8ykRoVCUjuuLY070oxd5lVK"
    b"PhAZY1Pu52DEJCocJBfp48jRs7hwE9rCpMLqWENO2DyK75ylOjwRWvi36D4H08C/9rLyC3xqm17z"
    b"vFyD24DhjO4CiP0l/KsYCr1pqrip43H6dzi0N71qbF8Kab6Ss6EhBv/A7ceBUJUdnmTotUS+CifD"
    b"002KYGnmI5Z0Wzunp0HUIegoc6NSXy3VAfGLwrr1TuMLYrruZa7RLGGyauiLAOcm5w8ljtrINTFJ"
    b"Z9XYN5Nin2sbzYmB5FAcxOHvfQIX6gROv+kEDsLcPX9BlK+SuxLpqAPbyghKIJtDX+DV9kazxlQB"
    b"gfsmu6VWPfI2SOwk7KCDPfe0L8+YRWqN1lLnf28xURk3/y8/hbmQdTafdLal/NuGGFewPVpjjL1p"
    b"zkoKspVez7mansKVFBewCHuWphy6g/G5jG5QLzY4Hjo7w0v3viS8GU5zp73zGyLb6Lkmu/WtB6ND"
    b"/m7K3Jm+FpcnjoMtqewDg6zIm6VI+w05XIljVsEpzNgwlpMiRrdYArvVmAypNg/C+x+6pjT+jgsQ"
    b"Gx03kNxG0pHl2otxJ7xzJxmS+7NHu5ubJ56DbMNEu2zvPPSunB6iiXE2TaewTH6nQ7l5WOA5AOj2"
    b"W90hzymq1kyOKKVNkAPrZAnCrEuNwo9NPX9fhACIV2vtuQ6ZOuhhvUA9rOK3xRrzT3Zw8W6Q+fML"
    b"aU4pbFrheMm2zz3UKLWyMY7gFPb7dZJV6aQMALys0A6TvN+apE7Z8ga2wS7zb2CCr9Jrg+nzQmQm"
    b"P8OakZlvs2N+a4gZ50bGj4qRQ2fFfbIAQJhjA4YDyNunH+W9HcEdGXB7gsl9rzcZVvoGRvuZcfBP"
    b"q8E50HsDyF5RPP+dyL9Iv77RE/ZGTBhCfLFHqKy6ee6LgHwpDyxfyq/dvpRhwROad34Oo/emzfs1"
    b"0A9ZjQUJ209ndFqheyvt3tHHkl/GovtoaKzJ548eAWfbdONKWy45nf5GgTzyf4XHGepq7muRTxhd"
    b"wyg/U17PTVuQzOFIlkkDfZ/5cDp1O8FlK53grvNf2j5wzM9W+MBBkbYLHDrOZYAfiu7RMAOpKnRs"
    b"l/YIHdmjjvSmMjW769oMNdiuYbVHTwN1j8cxcFi2ZA3QGCH1xVhnrmE2YUarMl0LwjZNQqMk14qg"
    b"tXDHUrjPGrjX7FuSJHI5nV4Y+5wqGcTI2h3cjGIfWJdZcsMpBllTuKG5p5C7Hr8rq99owEI5nYQZ"
    b"etRxzzTz3SCbMW3UQuohDMVN5XraG6lEplzHYzDMYtAXKW76hKEj05TFT8OGBQGT6goKPC26NxZ/"
    b"46Xhah5VdSTS+0ZyjLYta1Bo3MhBx+QdoijTaaxGRwjxmDCL0pJBGcPoXNNoZsO3nFhWAQfqqswl"
    b"ArpKNB1kTDtAbXAvOG7pKWNyUq/VvZTT68d3uv2wPuySNrsrb7G62GpXoU6e2tlC+N+88zfyzuJW"
    b"cCkighTVvBEdREYOoRwrjEg4kX2ZJ2kReepzG7+9kBQQKjHiColtleCFBc2FAcETDJA6LP51ZmIw"
    b"8hMWpmF5qjVWKliXbWB9e4tKvtOmq6C55jbSoCpulqzh5EeRTLIT/oP8O/EH7LSJCA9GW0yrB1Ap"
    b"QORRqAWqka6ReEPuOkjRrARNSEoUL3xUdIdck5WdVLK9SrSHlE2LHXwcMHRT+H37a41yAxyebaW7"
    b"nh3uPc0C/9sY99cY45qqf1KajNuGoaZRd/OKQwZZM1bOq99r5ThsSu+3dv7vtvntNPQ15tOYtj2c"
    b"tg4HXlMPd6fHxe2t/4331de+3VLoGVo9T5vLrjS0xdVk6hN1rAgxZssRV97dkU+6wsU/uJUovnP6"
    b"4iqBIczIuxsGZSX5zaTYKmNU+MN998S9rKM55ZAM3hqL2S5gLhqui2fVu6SAY6cCLIsdT0G/Gtdu"
    b"dPdlfvXRgpcCZZIwqx9xwR7FuC84zcSPfr/PTgNlkT0iMtAwfPGKdOoJtcSD/zpJtn8ZbH9/uhyE"
    b"w8f1dw/SfsVKjFQDUPLyWJ2dOoL0+8P9HrmE9wABKA5goDW6giiBBWHvkZItcPj7+ZfshxvZnk/C"
    b"40t6zgm2ogs0eB4PZcPv8dkh0TIBnxUK+gwDTpyd3/SuF2XVO2e953Fv2B+IXlwnX18isjGAirtx"
    b"EwLaHLjaBJizCwlkNjTAhurgDmtbVM8QMVtyI2wQnuKCrusuzcXgByOPyfkltRPq8EkJqpKV1QLG"
    b"crKirWkYZEZlbASgF0YOvsVkLyP5OpNzVQq/PDsT47rpm3dpQ2LXCmwPZ7pWwhhhvk368OHu7axP"
    b"M8dO7jid9Qj0Hr4T9I7DqMUu2PPHqbXG/omykBU4N9Bxe3uyrE8DOrw0Ll7+S0mbYWkwWhuy6xR0"
    b"riBxHLhXl7iMklwPWup0Qwfm68Hu22K8IINKbgybkC5iW+Ot1l0Go29+B+Rzw47R+qD/16O/cU1z"
    b"4LiJOUTd4UH3TcdrI5/vb/v25a2R776feWVBmFwT5u6ZuRaPwvP/YeTvWdwAz//ByP/RRBHP/mBk"
    b"vzCNgTDzZStT2AZR7hu75sYNzlc711KAEsA+v+L5xbri+e5+ERo4bMNe+dfztes6Ds0s43e/nYic"
    b"UthORttcUgityYiv6fy4vodQp4npt45IM+cM2ABHvoxu6Qi/ZNgkVNyGkvZpJkSlViSmVfD3NyZl"
    b"IfCvmX6MHjXl7eAB5ljG3z78yIVQdlqviF7ye4ls95h/K4BEAw3KRwM2JnfskeeUA9yIKaF0MIbE"
    b"N+oWE3mQMo31bomQcYlQn7Q/3zcIDBEYrmD+LSmMVWMniSlMqLEjLcITDslJnukAOXcTlOBbo2YZ"
    b"UXjckbMUQCt6lspZFdXdFeZHJQnSs07oLVVGhgdaO6iQSorZuqG7rMZiGQeOL3KXC4g9hWqjWakG"
    b"pbXSTVpj7y0bTJAcsVkNayk9ZNhhfTlUl4mV0Kb8r4s41uXt3sC4ILn3nCbzFqhqTVfFp4u154q5"
    b"Joq1Z0kGVEE5X8wTc05SJalfxyRlcpLwwrNhBMfjJMvTg3UEvvrxnqH+7iFbkGrBENnwnXNLiMC3"
    b"1ly2ymHJ01sLIMRAwI3bslHlFguVQVDRsht/Hu+MTdPtyLJfbgRzsp5zHPupuBEKXb4AQZSim5db"
    b"UDIslO7boaJpc3CfDgkj5aYtEEdN2owrpF6gHPuFtE/KnDUX9cg5e3ESumcv7upE+Ws6EbZWREcr"
    b"+a9pRW+YPxtvlbWC9lcNw4zq7rinNkgoGJ2GpRUGa1phWcXwJdG/UNzVjcrKanZhZZcoknpnGFh6"
    b"eaFaw6Ato/cQeMcr8/mMvxhOxIA7FQxehEYet643WbiknMh8AkJVcQa/x5ZFcwCTNl0A36jNXHSI"
    b"NgDHvQzEJcVHH/B3hP8CUUk3NzfMikqpuBw1AykBlc/HWWT3NAuXUA9GK6/DJSoVah3tOYiYRsDf"
    b"pCrnWwir68B0vEqEaxLm5ogVnynmHq/v5HQEx5fPyc9glD0zgeRgs60t/ZqVzsZXFxUCiv6imJVo"
    b"GQZ/x/6173EzBQ6LiV7YSiq9IPSLFfZaBZruISCvX5oi8o9KxmtAdQ3nXezeofOkTogrqc/FQ7Mi"
    b"zNwh/MWWIc0lcghAR14A25tepBOhs69W2uTYVbsrIbY44sorR76pcf3T/2PWRz+Zr0f/C5XF4hnl"
    b"YGkQnxxBjnOhgtuTxqau9Hhjw5neDH5h6NpMHztt3mjcA+v4a8FoYxh39ggfIgFpF8p95mE8p2nB"
    b"Bz2m83a/49OnYugE6uEGUqVinY6GOJPP9NOumU6ElXWnWTIhC/FG3Ub6RieagTvXDLqBMxmiLlyq"
    b"Go0uAlfbOXs/8zDdvjPdMXuULpnsu2aPSPp9Z0/0KLNnLzNmL7MxnHXPXrbG7GXW7N1RtzFL2X1m"
    b"jwZ1e5t1zB5HVNfsrR/J6a8mFbQfN6L1g0a87GtFkpeZoDxxzEQ4JfxfuNbZVOHuvTvkWufvUC39"
    b"i1a2K1FMQfxsQLxIZjN8dELn/mjktpXefzbLaoNZnvkXs2nj7PyARydB/M2A0AS4pdL/k9mKpn+v"
    b"2GUyueEgPxkgJnp47l+56v0/6MUi+wrkP8z+aWNFKsZQf9sB8Z7Nkpt3SJYnubiZYJUB/jr5+po/"
    b"RXCU/iLrywwA1PEd42W4NprjQIUBpI8A8rgREKmAEGqhr9V1MqdnHl6nX6W7CSuNavZsUeLNYjZ7"
    b"WxxczyuBPXz6QwGrG5MZ9P/IZYBKRRKO03+2cIpU5+/WJQdjFododkUYTJlJ6P+MxpnkQaNOdBPC"
    b"bTYlDNosKbqV0vXGmM2MTHRfyAhEJyg1h5fE9DLL3Q8YqbJWPeXinMP5O6T1N5o0wcynwrkrPfYc"
    b"VQz+PwPeqBqbbxQMFGPM0CcmDehP50sEBQkl9PpASvp5bUBa5Tiotr52qQ1eC90uuh2/TqeQxH/Q"
    b"9yto6hDxJpLVd4jv9qCV6MsiuUQ6CQDNpLoOC5P1zegFmRVrIjaVNWSpBly0Ya5bxc/9ysS3GyVV"
    b"6BmFBHJ4LING02ZtQfilSMljLvIuklnJ8Fy3xEWuIl53JxQWmVm9GW5vHaNlUq2nuyj9cFavIHMt"
    b"8W7wc5jz3Rak1cnYXw4ir0ISP4S/k7kX7kTeYjrH92FwatIcMHSDzyqfmra8BoaMEH4rREqvnFTz"
    b"NW4mvknvT3WvjjuMIGO0p470d63MlRp0ZoMrHmH1i+5vDEfGNODFUHXEu4G3OwinFDl9oMoX0I8w"
    b"449LafdPPYW0p1Choq/1PORDUv48KZ867njEg4nxwcJ8aYp29OL4nUcPEqRtz/eYOiVeg35wnf+S"
    b"zmZJv98//tPh0Rn8/9H+u733x3vb/n9Ot4IHgfkGJ1pvczr2bEf6jG7L4avno6uTIT0frUawEWfj"
    b"7WGUNZ+L4t15/OjR7mNpGHQBHNlF/pWP8hzO1JJR2FH0spG27U94wEU2Hj7effowGnx9ckH/PYo0"
    b"0OPB+NET7pzDU8bYzKOIGjOK0Ft7uTNkPu9XR4/syqGHHP6RfICa5pNQ/A6Kp1/5SgjhrLlOvm6L"
    b"p4228ZXjSLsh6diw41Sjk8Jb6ENm+H2AyI06OkZroqAOmaNM6zD5/S9BdIgy2FEUgTsUj4o1ep3p"
    b"GHFPHgsbQMN7OWK1En4aXs4j6QXNTTw7TgDk4L+ZEtz5tDL6ItpOLipgb5w2vV8wpEsQFnFuZVCE"
    b"l5jcyTinUozf0MOX/Xdvjw6PD38+ODt88/LwzeHx36IBf9KUQ71Oqis0ziRNYsS/Uq5XFIp14N/c"
    b"WEnoBUyLt1UKIFarRyBw6hJJ3pM7ZSKMjCnswdzB9kXAdsMa6O47X3FQqEYqy5+aTARH/E/zDs4O"
    b"l0x3FdI2tKBXxvHv+U3FXnEdI3GSc5ZJMTqZ3hDDjoppRMXmZvqc/+rbyGsb/4rMXpXnvRk69/d8"
    b"OGkpwnAv6UHp9HpxjWE9vC1njVteDztWBp5xgrhuy9ZxAmlhfXRP+Hu7hNAcydcCiJ8BFiOZSAsw"
    b"9DZAw2KREMoACPQ6lrGc0hU66dtbb9KQq+5cS+vfD4662cmmMGcRFX85yTECS8WmkQRFYW5yxSZw"
    b"cF+qRPiNrBTtM3yOz671VCgv2jl3UqSws+d5pvteYl2I/kvWZRHhBOa+Zy0bCSfsSnuJjq6srLAR"
    b"3K8TigmDmvbN+re0us7bZuG9nDxPW0+iABMIAtsI/+m0qXF2znrIrBMi1k+vmLFGqv7ZLCmrxgoj"
    b"p7/GKsfLNRdsG7JtE9CBc7o2bJkF6IcFO2YQ5aJVk9iJg2CV96lBc8qVMXCR6igmptJMjBHo9skQ"
    b"460kF0mRdgM9HjxyaD1+P/5MxJClk206F6wj/daSxH9mwDaSWmo7Qb3U9jUppgIrpikXehDYM6Nj"
    b"e86ipK0FVvbaD4L+P3LgVajcqMN7GHrXs95GcEKNm07LXYDOyGoRjQJjv9qn7AomJ9crxO92J7yT"
    b"oVnTfdPShCGDSHKfjIPn36u8g7aYyBv7dyzuZ0+ewto2hA8n0OOn7g0Q2GH7gB3EbCuSn9JGjFuW"
    b"Dl0RDCN/hT+Yjonosp2w9n3y+82qK2jifWf2jjCKTU+5wSmFE+0wpmJ9+VSVVm107QQepIrFfDMx"
    b"vZmoMHpzIzpKerzYd4XWW06SksmAVBF9XCWf2Tb3yKe7HDNZuOHP8ToBjfhFk7HHIUfnwKx+GgG3"
    b"kyxmlcoUwOo8wb7hS7BUZkPGFET1CgdUSePWE22RL4rpUIQ0LOMONzISuGlVYAYzVI76rbpbIT7+"
    b"ri7fD6eAbgxv6/JnIVkPMDLNrzHKq3xjefdxYKqkw+EOsC5/7xNmX+BzzLGrfj8AGCLjqH5yvuot"
    b"qbZF7UUodEXRa1mNVIG5a1JVXMeiEtp5KBI8H4w9SN2CdRWIWre8/yywNawcQ724lrtSJ/29qYLT"
    b"AgkQKNgEohYeb8vVyzvrUWq8CusytDzOpzB7JmLRCEmfkPxKQttb0ghtRW67Z2EWL/W1SuRXsV0N"
    b"HLtGBItgbN5QwGKQuO95QWRlDcysAIVlFGPyDJX5y2HkUYSNHfw7mXv1CWr5UERBZZ/UQEbVyc4p"
    b"LMVXOSz/F7B9AUdSTRwZ+sFd0g+G6RwKPDwN4YTCAEb8A+OFmbCPOCw/tk+enNb6PiR+OmLPpEZy"
    b"xLbiHUVzcGNxIlNg7V6UkW4b5LA93hgy21vDU0E6OCQ2bUC+g09Tq4nwpNc0ygAusGdYCn4ek61O"
    b"q+LFRZFcIgj9EADAiTYvSOyikpwpFVV2gsM6xVtz/kvAK445w+WDtxarlg+aWikzJb2OtBuDmvUR"
    b"TTk2PBYFhoGYfjNxR5k9UdgbUbNSSlf5h/lcrgYLgK8LI0msAzyL0rkJChMRqBcVSDRXW5FAPEjz"
    b"Am2IFXpXeYnHW0zv8tkzb6TgDJMJCa+FLxWjYbugyhArpQ2I9dEdoFgLcLYIbFkIMbaH0bpcSka1"
    b"ohqoEj6aqwXRRAvKrIQvNaOK7lKBcS0WoQqKM+M9T1Mh4BvfzleRcU09HprUQ1Xwvpq/TubuOwhV"
    b"9nuzKFK3eXIzy5MpDt2gBIrqwhastUKMIndhdFdSk/N6HggClvUncO59eo8boXU9gblc91TGu8Sj"
    b"CldPA3KHIKMhwILw/0KC65Kh3nMrxmoMaGSYBs3h0GBFAetG59NlhzvL2KKidYq5pvt1ezuU9yhJ"
    b"DHsXzlWc2C3A6xYPcbYFqIGfCitb3HF+jMlZ5HnyqFUTyE0S7jOBogfLdGpS8QFHuTa4oelSRxZM"
    b"GJz7jSmEeYq0UVK4KNKI5i6poNnzRcVKFNzID2snMFavmhFH5xV6uGQK6EFjzSkiUqH8cBpgqmGm"
    b"pHtB86ZNozg6DTMixCBhG3qLlei+jnm60XkHul9eV3P3ic8DT2mcG+c9jHlrqKZg5BkWA/EATshC"
    b"n5BbQXYC66vAV6hsbi7mW0ak4tEyVOHp9Rp39y/2PLILN5c5SAh3r/Ssa6WHWJl097WfZTJzgoZV"
    b"BRxt3aCme4zZNQVyUp2OC+HXsuUhC2pnBpHMJceVLZAw4otrjEK2ldGsF2IRjvTEynPKoIiT+cvz"
    b"OzZU5+Qa+0voMSRRVD2NKtdW6GzWMXXW1di3Th+yCS8Zm56LcDjmt5JvG8mW8yqhF7O3L84Vhvnp"
    b"v2XOLNaiPiQJ57AaJ8ZWE1w7TcZRWUyaoXX1fJhzgFuwBGhN08z5eoLOLXgs0SZV5SIPr/Wk/c3z"
    b"7eEYw7lKAmDNeLU1DAs8ksg6xcoqYP5J89FVMOCHkBrRj0W+uItkD3dda6pUF656YeGo8VtIenr8"
    b"OGC+wlCaSqdOGcq6AqfrbzgXPKQ0pHzWzzrqrj3W7MNL+GYFcIrAG98xnoeu8SSzS+Qxr675cWML"
    b"JtwOCOmczaPKIe1Xs9IV4sQQ7ZZFjuZBGMjVCy90Z8uoMfKtCsduQERC7G0P1Ni0K3vAeQGotYSu"
    b"iHOeVrgR98voke1/zGmX2R08miS2xFYjBOltoxfZi+JmDrgEefZbGIMquXRwBhOq82gBw+anPFBw"
    b"GntJQmVYclWuTBLn/q6BrY5eqROft0AjhS6IMRrNUorDjLCvejK2WvpJJvsGCMrU+gMJldVxQZis"
    b"NE2uXRxBo62mNRKnz4ripNkMxg+LSynwFrPZqD0xT9TE3OqJgX6/ZtVVPo1EPR5OwlECMihN0yy9"
    b"YMfptZif60/pz2IH7ZyOSfAXVfL9LeRWhONX627AoQRsTqR7yGptq85ueTSloqeIcdnPMQxuS38S"
    b"djGSleg4BXqVnROwMk9UqvvuKe0T790dhKHn3P9yBVpbXy9b2QJIXXfsemftsB+2SbLj+IejqBNs"
    b"/kUSYW1kVoyXLRvOzFYdAZNRll/ygoxCTcVRHfEbYTGBXQNQPIfV2a22kMo3gdFXOsx52y0qB0Cv"
    b"0ooEpy1ZNSwvxnWGocl6zVd2a4nRnicYliC8YsmUFSA/sAw3KqVdMOAVUPJKS4pdECJzgjEMwixu"
    b"qPgMOaZHruog/F+kM4y7uqMd3Yp4d1Q8y5Qrn/RuSwGsAIrnOj6VVJciuZLnaKkXhiF2Q3J7EYSa"
    b"aeVVjITKLDOYXWUkMzbkEh8fgAsikEQyi21zd1PybbwRc8FzVhRVFBzfSnfEZfmGwogr8d4f7Iv7"
    b"gA+v3r08eOHBCWDNh6jEVUNd144eSvnPDsxR9Zszzyu2pGHyY5X6qBWD/6N74Fp3JcZvdqCwxJQm"
    b"f6yfQkNFI6os5J2NmjtKVV8UxtSqQwkwkhGWugu3Vt3gNLwRsg2kmsc5DeFLDUHZLXrfA+UcUCYd"
    b"p2rp3956H/bfPTh+dfTg/fG7B0d7P797yYVlqyLBZd4he4zdyZElxxgqAUEzqFeT+PBN7/DdQwxK"
    b"iP+nc/jMRd/3XADO2YJSlvIHDfp1Gm0aK4WvAArsIpbPYOVqoLCLMCXX7DmadKJwIRNw/ornA5TC"
    b"qOsyHbZcIe9LwvZyxjva1hJ3D0ktdov3g4HKYHyriCnQxBN+BLVJL3d74IaqjV2sGBnc8OgKvRpK"
    b"EIMgzF37kOQ1fUfVlPlwG5vWChOkHVxXq0StIEziXK3uzc2cKDvUEE66Wty+RPErenm4b16PGcfl"
    b"E5Mp7hCrgtHEaHWCrYrPIf9EM4c4Jo/4mL6Hp/iyq2MN4XXv++O/8oG1yaNFPDDQgYpKweXdJKQ6"
    b"37lUss2SXDOLPv24WIHufBWVVLiElHI+RWebO72tYcpVF67l3EfAQcOe31rM5pBPnoVTr9Z106tw"
    b"/FEG9UogWhdTtqhN7L15ewLPY21pOdeX8HO6YJtbCsvz+Phw7wiv1xQ25rad9hNupu0qygt+/2jw"
    b"x67Cj6jw9vAx25V8dNamDD+kVUGqbXwcMLNUTKsZHc6y/Es2DHIk3C2XsmOh0cCQG1APvjwFf+46"
    b"PAs0zPWMk5KHTZiiVaziTZ4PiChfz/EOK+a+/zwH0q8XXztrhzwvMCqxlGSrGVeD7TS6pFhP3XlB"
    b"gBl2xM6GBJFpHHKIFHIXQ5wpeD4fWzwbjkrKpYQJV+a3WNzXpUsP457t65JUMfTSr7FjAqkLIudS"
    b"vF7Omgu7eU9MPsYkFdbdE3vPxYW9a64t7Kqe/XZH6YViWm4reqhVZZMupsdEm+WT42annR4dBvn2"
    b"jVvkwunMATSxfJO88cVDheR5Eoh3f12ohJ5v0z05n760hRP7Ej1tNLpDjepbeyAt11VoG58DzRau"
    b"LB0d4NwzSR+6eWFz1HRZGbj0QHYfmVQEqV4x0jI0O6XVBN3zp5nWEy3hxt4+Mp/kGrVhXsiOTzhT"
    b"S05VsMu+57pjkUtaocr45OxgBxtpTw6Wgx+izGm0VkO6wB2NiNs9UaLRyx55I/F2NaGpGh4G6mh0"
    b"ruKtquWQIAhOJlhrqRTh1kTC2vJwur6xkjRV8nfCHW6nxKeW1/RDDoJDMZ+5YiYJtd7nmJCSA159"
    b"NMxFq6q0FM+NA2Im4kLOBwHE0VMQD3m2RtG4inYwUWB+uPOEcD/EZoAfxT9VPOgNlJru0ohY0KGt"
    b"sZQDjdu5zLydk7K4Nl9B/a64e4yMBB5YQSSo2AUyQYVHiOTqxws/01FZXUyN7QEACTLuXMXwfkqz"
    b"qUsLt1LrYZMAPrlp+Z5e0GKu6kBsJHqvqgh3UD2oz7YOhbOrF0a7DsqD+4+rNJvGRsMGDSLVMxBH"
    b"Q+HcuF2jwm87u9YgnbBO1+mg1IfxTpZytXLFq/j8mVvaRi1rhTBj1TG3ltpVtlUiwTK2esQPw7T8"
    b"mR4m3n/XcqnnfbTMRLmtmcUqCAfY6o6FXpkLHS9/cE1Kb1LYujE9NYSJwOwXe5U/DHQD8r21Ovxn"
    b"/Hf+BsREd3f5BWY0/4JugvjoEMgNGHGBzJjRVQO/XnKDZfl5RKbJ5LchdqmDTRY2y6TcDIVlM9d0"
    b"6uttRAc5BKs4a/YX6Tb3gPAYd12iXnpvrpf0xGff40+eL1XZKKtjxl+tVLWgRxaSbSsBagTSWmrH"
    b"LFeujhNDmEkX13y/US5/BFqyD3Lg0hRcDd4Q/UQSyXzacP46/8WMLTL2jdFKm3H9Nlo8NYcWPhCT"
    b"9J8PyPf4P/sPQn71yYOlmBUDknkwm7Q8YpNFwUSUkBWPIlt9kQPr7ArhCE4NQFNg9GcnCCKnZbhR"
    b"WLpW783nM/YXdv5TWukaAqsbwkK+uxvOOgArKE/xt1XLDxla8E7fzZJMvexgBF5Bj8tFUeBakETe"
    b"fMDIgDQs2aPWIi3lS67mcq05TyzXyz6rknRWRhlajl7n2RFstOg/QpgWYL8rSbCm4RRO6PMZe5Vf"
    b"Rlfy4y9JkeEDD9GCDMn/WWu9tHQd4AeimLkITdBvYBnc9Nvx7SGZLrAFDQiWQMv4zx6m4iuQ9E46"
    b"D0c7xYAa9IK54Bt6BZsxaAvfaCFbzFr7wCtP5Val6NuJtU5RerwGGtiTW4SSEQZSL3WlaKrLG+z/"
    b"o1T5PT5AAAsLOXREZHwTktcJRp5J+F8+9B+tGIc63XhQ2Ey2MWXmiMcDzCTHK8qNphvvO5u57ped"
    b"JYTrfWUxPCb+VuJvKv6K3qKESH95XaalrSQxtDoOYBkcrFodgtzQTIrf37g+OqZSdKc9lwetuTzo"
    b"mMuDzkk7aE8aTzJfYjDT7Tce7BKuORJ51ssNZo79ZkNjGKa6V2cYMZ/aydxrorEG3HNvzrmgoTTl"
    b"v6i55Qc8TS3/+dvOLG+0PbG/tCb2l74rapaZ1wqEZWUacbzM9EaIMKutRnAwM88Zm8sEaK9Anm6G"
    b"4urYpiu3p7RmR6191jpMNjzjkSPFznn6qV5ljsGzxpz5ivgXPjg4j9mkLxq5vWWTEGQM9AOczJKy"
    b"XKYlnKHoECgbVpKp0YZic1vHe52WP4hJNirQIb5RSBIA6BWi0sSR50vGfmODO0PJSkQZKzA6Ru3X"
    b"HnhsXD3n1cGy46eNPEdNHzwLTJAyBafd8DDMJvcpLw/fHm1uGoX4JhFlgtockDK6mPftg15+1uZQ"
    b"u6HFcQgyBODT4FpaODUwqLEKzM2KGsmrzXBcBIbsmRNtWqTAEqYbIxTpwqEsRM1s8EXX5p/wFWIn"
    b"r7WK07JlqCKGH/hqq8+fuW6HTOqIRIlsGAgz/DkxYHhq8crQkkchm+Vk2aa2mFbAiOn6KCahjP6t"
    b"B/9JAeC7ZWsiagKQAoEGUAuAA9AKk9n0IdMbO1HDtLaoLNHce7pIe1fKMq71pcu5V1/9seZvhS8m"
    b"IH3Jlwip87GLTihBDR94Tt8lUy+EP1c5Wk7Bj3zqneqdrSVCVGiBaCyfhGhRg/hEi0pKUJG7+DR0"
    b"L9H40fehc8HHT3ZC5yZH//O6DvHFyPg5RrV68F8ne9t/Fw8cbvnj6KR3tn1qpgV//O6BePAQSO5V"
    b"TK9IrXBDFLb5IVvESx0AOTpZYihlIEzVIovwn/6sf5nnlzNyPoqG3+8Odrw65FAnHq7PiC22B338"
    b"1Z/DhvhHSZC7D588BdQQwKLsAjhVwekij+d54aRg5PuYzGTa3KtPQyvoEEw5rZJtjDAE/WEX+kTp"
    b"Mbw+nwI3sczyfA5rpT6f5efH+V5RJDc/LASHo3SAWPBlis834t279l7JM7xWtZQPMjoDkGdf/kaH"
    b"ZTjYArK9gSr2SqsdvP07hw1f3HDsN7ohFRrYiQ9pVj2lXF+pcVqht41429VJdhrvPHq0SV4nQImm"
    b"bA+jNOi7uXNqpZaCuD5Zr6pqDlgE2orOp9p3eZLPrH2Gr3AGS9gGTPzm6/XFq7cf9s/+9PboOPYG"
    b"xqR6Zva7t++P44cPd3na5GqRfTI20lLogIbhRPwQMSUEo8BjScVswVOlyMumjQPdyJSbh8Moosdh"
    b"5mgOVfLfi4y+UmuTt19KDA09E9TpImnhFyKMPLtFJEM6ACjgbbQxDDHGDv7ly+EHWJP4BWxtygOV"
    b"DEl3BUwyr1QppejUoTUw6jh6fLag5zpUc3DgUCnySGqGC/K9s3cHB+//fHR8cHTshcu8gHUPJJgi"
    b"pVR97CaUD3Fl867FGxuwHTgUr7bPx0BOlR7uLtST6HHFG4QQPFn0sec4AUk5I0/ANU/IqpZTSu+3"
    b"kqt0zGbiDR8idsf5JwYjv6obQVMxlCq7NnhPWCa9WX75in0GrLSeYePpdWkCGW9a8ZSY1fBTbBQ7"
    b"63m8KyLdnJElt78bElj9JSmyjhI7dokdUYJR2Cp3kaFdZCiKUASCy5etx7i4yT6rBTi9VKYv5Txc"
    b"WH8+inoepZ/aEU6zAG8rjJgfFE6LvF7Zaez53hbdZvAb8KAnPsXVVTBigJExkpccjhOBtSyIGL5h"
    b"IpMJN95f9t6/OXzzoxcqCDSuESAcGd7B+/dv3wsIF3OgpwgNmNkZ6p/ZpXxyVodquErKt18yGYkp"
    b"ZDex9z89I67uCzxB9Odnec1FjVxk8pGjiYgfXfHPHBCEoeBgV+uy57xsWIQp1+LLLINxaQcrO75i"
    b"vZmIsKOe7k16qiyPEVzy2CqfMb4cSFnQQpjH7GbMbraqqDIeg2efKeREfjo2P2Ak1nd8Yn6F5Wlk"
    b"QdPVJEb3sMqUofp8kS+yCg6p0HjDgh3zc3cQx9vbNqRumw/jRSRiSen6q1OjpiM1y1ap0EyjimHy"
    b"xYxzOoiRO14YcWytTBGKhNcFLNPZGQGenWGY8BsQANCD+MhYO9QQRm6wTg+iMyE3tEOSroMYGh1T"
    b"bgC0xVDvISVWARWwS/4QIeJMXQfDjMoLr2EQaR8mMQ6gaMZiPrq5Ps9n5TiTr/augkIzDwwEag1Q"
    b"rjvb5AYHWInFxSJ6rcnoOMwUHWRSNuNIyGCFyQT8zUkL1lTEA3o5SVgIlTHngVIY27OUbK/Lk+KU"
    b"LK+hnIrI2dFTPuv36616zQc7Nh5Gsi/RoNEIu06rxn03buaw5K3kuhV+lJvt5KdaoETgJJyE87gB"
    b"Ek5bLzxhTXNE3lKo3edEXKxXCVUALhYiqDArCDfQr5cr53vDSJnPXWR8Yc0l0QoAkjR2vZ0VUKEB"
    b"t7sSDnVMEvLhHZDoWydhH90Ji2RNQj9eAxpmBuBrXGqTeBgmYm1Nt4fBaPJsOprA6kpOJtvDUyMa"
    b"z+R0RFXyaDC6zgQO4lnJaKpn4VUsDRFHvHro1rMrqlFOFNS0eq4QoGu6RKYYGH7I2TJUrDBhnXCh"
    b"Dbm7CtJW3MKkrYTFCKa27hBXexIQs9BE8wzQPCM0z2w0zwDNohWBabOZRN1dbjR3YcOYQ9uc4AlL"
    b"wXv4zgR63So5YWuWHTTL2rPXogKcAqSrKEB6GhgsJs+XKXA2UuspZ27Fkd4ozk26gBTgPxsU9Rm4"
    b"rw3ObdzeAjut+JANCkSrax3RypUkNweSm6AZ+CRWZCZ/NhnlME++YAeM+jFBN4FfRisYN0zwA0jj"
    b"Rol0UGl0PsZbYZWZoB9aEukO1gZqnJjfm81edZ9GisEZ+yatb1B6kCdEgxUcdv6aHASfkuZSuriI"
    b"V6wPGziZTtXCaSxIDohWKAzkmBv8pEuAAzhqKgJH3pUdcenlk9vlDqW7mIK4esCCcb9p75o/IcJq"
    b"f4lq+PfuokKoPczQXjepUpT3PCH2bqdGKta8n5Yqaiq0Z3xh7mFGItnhPr4CQz+3UzPjJ+StZc4n"
    b"doNZb1j1JS8+xV7Gf2AayiAfsuRzks5I/CQ10PZCpyDQUTmzYMpy1gIhpRZx0fjmDX5sM/4ICGTm"
    b"k0+skpn00cx8gZLnVOWSIErjMRrGwRrNigFzVUDsgSSPhm5qDt6558C4bX0JFWGbmU7avqA0rFeL"
    b"/LJvOqCm7p9o7EtHY3n1ds6yv7EKWsmrbQypvH3DKr5ySFQ7zn9IL3EBcZvDKs+3z9NLXfNBx1Ii"
    b"BQCsHvqL9fGUD8cvn8rU7UV18RSz6MEL7x8lxmHFTmUwh0XyRTfy1d2I6KLq3d3LUsyxmlxCHWAO"
    b"/+jm9t3N/YklRXUOwkHs/elg7/3xDwd7x1SJCuPkvdh7s3+4v3d8gOn80TDv7cuXB+/xWzzl6e29"
    b"OfoLT0HkA8C7gzdG54QwC1tlepyg9sI73N8+3vuJA5n75/DNz3uvIPOng79h1iuWfIY+vDrY+5na"
    b"P/g6TwtIOPjru8P3B3J43CzrMPaG/Uf9R95IKEpfK10pO7OozhIk/EJE8uYEMQXiJILcfBS6+rNz"
    b"YBU+FLN6EzK/W7J6syLFC2TXH0fi6ON7R6oozKmR8YcFCNFf2Dd86/nZlrcpDW+8LXYoY56bNYBA"
    b"FppVADUVi0JH1CV9VWV6tDDScMGMX5MOwuNUoidK9sTzXFOKECF0UoAFCS2moldapRDzVKs4hmrq"
    b"FkoLPvsqlyzW1+wvLcJYPwlvDg+FTtlHgu/xHd7H6Lwynu6MJdli7rvRMwitfpjbJGj3BQkB3Ru4"
    b"+yKgYbn8x4It2FSMqvQNVPJuUpB2HaT+ik0XM6Y2Eo/s6UoX7X4p36GiPL2GfVOyCn/ki8o3eoad"
    b"MMqJkcyh1CGwJQXMEDZgAy01O/alxD3oK098Yr/lGGBjk00QhoK/ksXD3jmbJKRLNGfCExsrbnhJ"
    b"ieCb+5p61OLdeYltrN5nK3BUq14urQtqtaGG+mUEXqUOiF87Z0lcip+gXo/KibVbEqDW9MH8ybch"
    b"LAhkF1kQcJ05owdaazEM/ZqEuWZkzFWN+HRqodzRiHpgnAd4NsLCG0XkeibaGaotKfdiMOqcamEN"
    b"23pByjE5uPm55nnVdrhj/8E0KoilPX++a/d1UDMn0SDTVytH9NdKjLlsGYTYj0LupdZGszWohmIj"
    b"fsR25Q1Q0N5n8krFTXjaC8g6OGKfjb0vZRk9eOBF8AP/BhgshYIKFVvi+m/8Cc+9rbSuxbH1lh9P"
    b"5v2HvEcTQ8fsxhUJrQqpqVUBe+0ncauwCSC8udmnvnjmmGHtaL4jj7RE2OGVx7nZIQmGShNg84v0"
    b"EtgfwK2Kzm03hKaa6h5mg6mrl5oeOm9f4WR9YDfZDAXxDPZVluJ9afqLBZPKlXANHAU37OIKDL6L"
    b"AGo6Y0f773zNrWB84dqNPnUCkk0UGlq14x8reui+pWphv8jxucein/NIhn0euF9fYApiXy3mSvKj"
    b"6+26nWjOf2OCwxa2jZ+HU3xb3jHriPiO/o4kKngHyJwwL3qHLw56Kmxj2ScfwzwzXwqLuX9oxzN0"
    b"RrI8+D8K879po3JqD/ms6KP5rF0Qpn2ThqlzSHGrofDCj4yX5YwKeCzXIjTxgzrhaVmhpzC9CceH"
    b"5HyKgY5oofxijtcxhJ2wkGciicY2IBoDcqiQjloyvtVN9qocnaqC1nbFk4HfmrB3bakq9IwkfN1F"
    b"lxQ1bnmi2b7XrlyQV9PAUbABd4yEQ/2KkTTFvtB74ei55A7X6rklJK3qP5/aKTZjlulhy1fMRCHM"
    b"+xUNxsKQfG8FI4M3dgMtl7p2DZ26Qh14wdtH6uRYUHXo3ovIjPfkgzZ8IxpP3PB9KAqqLWaXUUFt"
    b"RcooFU9cKWoWZkEX6S06O8bjpff44SB6Ri6w7j41wFWneAK9m1TGrp6NyvbZpQ4sboB6nFO6UbAI"
    b"8SkFzbEoko8pOILFvGfTdLH6HFRXHgWrj1zO50nu7I7jmTieNk1dRZFaE6/QzRefYAjlRuYe31ZA"
    b"fDg90EqjNY6p8V4TXYHHGxuF9SqVUamZEYR+dXubBaZtQ1LeZJOeeVAv18FeWHWfUcpoJE6+JCnU"
    b"ZUbEbx3Fxgks3xcORtaJj1sei7roiywN7AMZQKIJHb4wK2+olYnwegXx6enpPF4HmIMGgE/+nCOO"
    b"Wo7X8QYDxjLScj/addj5IPRn4UeoWNojNlBff5RbcEkPlIjY5y72wTpCV/If16xKyDaoCSUzahfr"
    b"qnc3Ep6O9TKCjoK8V4TELQIFFlyjtDnSjGZYsoLoGA9dj9gzvoFIuxkLWk2KqSg4o+BCXKDNezwQ"
    b"yfgbgXTART1+OiMpKeWc8LXWQyT30M6e+wN8KXI08MddFPU+/Sn5zLhB/VvxbgTFZzCPzvdCE4sK"
    b"EznvVmvNBRL2PHrkTPf2HvUZG4zXU5sbW/hQ/Ot2tmygtW/5Ixr/r2/csGMJc7Rpxvg329j1Wrvh"
    b"t1ivv2a5itVhL1gtG3IVsBToHK82VTL2+R0LurhbnIKJJcFSMD1T86m2ylwimfP5LHy8U8pNuEaK"
    b"JkCESure6kUiZGHukcFb00K03GEa3cW9Zq/VZRfWjYeiNQfWyIr4A20KIatx33xnytf9+7g3nTal"
    b"y9UYMpZalzi/Nkoao5LY6NKpiAegZNcBqke8HMiKRX4tmGQQizFsfI31Y5cNCQWmd6Pqy8rVzfu1"
    b"tCj8W74opH9Fb5qz8g+VdK5tazP+XdbT7x1eZnlBkteIISvO++7r+IUZxS+UBfwMRxnUqzhxGqs5"
    b"0Pbg6HrXlL9gymz6QzRPNYLh4iwlX2sGY6ZUbK86b4aMyRV9lPaYdJjjTjVuHeStG12u7/kfcQd+"
    b"pLfaZUt7qiWqYNnQQwK7IEId6LNozNWRVRD5UjEpDNugRmDe1Q0/7whxSnpo/9BDe0UWwLmpZpeP"
    b"V0JaWyXaVIQyvJ8Xv8XiV/af4nGOLNQVqvsqydjFBo8nu/eD7t4/qHvYfcN3S0hz9aU8BcXstsyX"
    b"VRaBFobnYRPWzKs7JFq5WgyxRw7dSLJukeTy3X/x7y1qAquzN52Yq7dcTCZwuny0Vs+XdDYjlcfb"
    b"jNNOT1722I1yjfjarZJcRmTuo55JyR1Jc3Rz4zQEc3Iz5SK5voozsQiooZUihqFha07yxK2MGZqb"
    b"eAsj3v9I6dHoEoRbhSl2RTyCLa0E8sJQ51Yh56mslTcwzbtMjWBXTfq0yAwFY/M9t2tusP3xQ1aA"
    b"BH6ZwapRFzG0cvEgqTl9RiTLc0UeJnUiPYsx9p1xkWSs3+Y1HTcRJ05IksVkRvI1bJ20rEqum0rL"
    b"XoOq9nt7Bevd5AvB8+A0AgUF8aJXfUknbGy8z5HpWzCjK7jkxaOcJttr7ngrL7ZB5ZQYyG7eZCzl"
    b"9Zys7kysh1BcKETq/W913p7Rm2ninq+15ANxZ2evvEzeeYnl0bjs0j1UN1VGp5u3Xjor5hbUbcQZ"
    b"t1XWRtHpcjiyQT08blnVuEhoIMFsWKBOKLwUIuW9je9KtsuzTA1bEm5zP3PTkSDoPiH4hwMPrrbD"
    b"1pzZYGbO7S37oX+4f/bu/cHLw79usQvT58U5IXjyvjVRZvZHKgVXrUi58FqFQ32tRc5DdW32Lfau"
    b"J2fK1OTD8ux8kc6m79k/F9xL0bqxU5uHHNXG3EHNi+ivFy7xzTAQyigmFIpq1VWUYgT8qKztCsKc"
    b"u9K9f4W8RlVHDx58t8xqIDtF/d0yhf+V9QNiQtQtUw6NJsXkSoT8x6ezvar0Qii/j9cyWf4FjoPv"
    b"lpY3JfJWroLCZAVI/WEQXjAk4Hn/qmAX4VJERS7e5bN0chPZ47Yza6kRhC4WKfvMMBzaUsr9LDbl"
    b"EgurXjrl1987AxG9skqqRSl8Sjjb9pH+9HtHlIUykYAycAKHDgYTsO1fTD5P9gxJ6OE+iWe8a543"
    b"osa8B54yUJCDxHmTC06m4cxiTy8Mp0K8/4q93uEF0WqMLs/VP0nvI1bxEbnfG+TVSza72MYaIB+5"
    b"c27KE2LmH4CoJ7My72WMyxpYDY8pkQBXn1yzHtbV+3LFMi4J89MAVw9WhdoS4X/zIl/MphSbAhmp"
    b"JIMB8wMN7z+4HVDf29JiHHoi7M1mWEu55rThcVg6Zw5PxIcDHlBJJtmYVm4jJkrjBkrH3iGyiznI"
    b"SrP0Ex2Cf4CzcEH3UXSPM8sX0qqp3wNJiILmsGuQ1XoV7PX/ob08EZssQ6UhF7BwvPJ6g6Zl791h"
    b"DzZnH/YvViRnQJT5SE9Oc4MBaOzmIx7XK6YTiy7EpXXvAiYKCETfk5MDw0JJLfsDH54aXQ9fp4X+"
    b"FdcpqSywFuwodbmEKSz7PZq0dbeGfqsWbRZ9Sw6mWejeILpdYhedy8rom3ttuUQ3OeWGdPPyTvEB"
    b"ufr/Xbh8yX2YPD+3HnOy+aZ13xrtqgJ0S072eb+b9MB/cNMoNu5fzBblVduSiWsiz86wBpyHiGsl"
    b"BYNRK6ux34Id++34KwN7sjLH6tCcnXsSu/Kb1k3mWvwmJo0bqYGAsTG0BV8sNdYWhaRuiGwzM6Hp"
    b"+GJYTVuX7yJoEdbEqWZ5Rduae6MRScSd/BEBPvbIq6B3ziCZkYUhUgdpIwUnjqUHdMiI64mG5jHj"
    b"FBCFsFlxzXuXXLiyGi0dVndLh163dIjX+tQZT4uInrGr6vVY7LV555cm73wldwzditnlKOn2tlW7"
    b"8DPXnvFWKXWbtg4bvoLndkqAt7dLi+HW13hWn4gPf2ny4VPgw0NIer3317MfPqB++2D/bO/12w9v"
    b"juOnu0+fPh48lWz6G318vKTjg4eQwBDDTa2RzllxmvAN2Znf3v9mYIEEnch4M14bMplOSTGp/OkM"
    b"j4D4Oe8jX6zYpt5NQS26zqZHwnzVN0cEexJDlVEK8G4CJlC0hkNJQ9WwiYzYghJhPGqjJm2IjETB"
    b"CnrUxobo6N41eiI9d89h4JgWGAQeq27zaQNEGtBD90RIEjgiHw2CUAQ7avVIWPwaNyANLToenZHz"
    b"7OR8ETHcgvbhuWxjUPTbPEuhK9oR0OyojUge/9aFfMP0154dfBChOc/NaVbvya8xzW1cBr8xH8Cb"
    b"MwxpdX8G4vCTHMgaYVxWV9deK4rJ/EVTiTdLNUKzfe2gwOO+kIPasq4dO3JJtg+slsdcSkFz4qqv"
    b"0UH+4wJrAicU7xORNNZYFEM3jnDR3AvsBN5UGmwmd5argtqCMQ5b3bzyGDcGc1KdAj2mrqMbJW7P"
    b"CHCWVwmaWdDfmru9I8wJ62en7SA/3BEFb40pWELoaiXOAIDqoyETaLAU0RFcBcRCbwdNHljKzR4L"
    b"qi2o8PymYvwlvZGOh2T0ssL4ZQPLOwCK0g2sX6HzdoFvRBm1qJeJxdjl2l0x83WtGTBh2kBRqmVV"
    b"PSPkyDsMkFwyg287wwA0sD6iDQwUZ3TluRF5qJARiF4ffzCWDFVAU19iDUaGdUZkykRLN6jwKswW"
    b"iICv0brDBcLoRGVvddF+JfxZBFDD3NlswgrujTrsuySa4+KG305nU7pB5KSs7lFtJVALlNVMtw9G"
    b"vtFNtqww2TIlDfGe0ZISF2GWWVHMDoSLoJtaSHrznUlvVpIQUwAQ7rCBubgcuGVr0cpWv9FjUXXw"
    b"57U7aMwbd0cTQa/wKadC/EV2w0UBpUmhJn7ttSRNfZ2UrrnJOFDG2+Z/eX9M35iAkzFjYaNqadV6"
    b"tgQn06U09F5L5j/Pe+cp1xmhN45hd+veft8yRVhxaI6RFuIxTNUB/w5N5KvMfWZkKkw0nIZCPYWG"
    b"c6FaED82L5nTaZN/Tqc1v30mLr99AU3J9coLaszkNk3NbJ5KAIZhrDI+c0S9kVTjBKSqU2nxdWYU"
    b"DhidRkpFTJVPGWAkv2Gt0akMDmZYjrcgjbz6jHeJa/4s9xPtWMJe+65Lg7CtBW0k4fVB2FZJN5I+"
    b"sZsmkOlYqFXkeLZq507tw9kU32tu5a091jRocp6jm+170xs9tEqYPpuh5uFdzmiW2Y3wqw+9V4CH"
    b"hqOD1CtK8UvVRa6Zqmm6eO9s0zkA6Z7wAcNZz27onpw7TGIgZ3FJq/wUanLl0bKh1muit7HYf8Jk"
    b"T/ojWxND/saKg1vjUp0egS+LidSgVFp5gtodecWVlBVfgVKbkE7v0FeGAqypTuFGMU1c6bgEwNtd"
    b"l5fNUsIJvFnOCjsQfjzc73kybOq09hDFFRb72KpOuY83a9Q54UfU2v908DdVp7kheO0idEOrfvJB"
    b"j1ouSzNMVuoe0u/gNdzHhu8yavr9QiVqgtPnTK5ftJBKPu5Re9E3AkeEH7WOXdSrrMJ4TxoVk+lu"
    b"pJ7qsPU+KvCx5TDBXVUr/qyeEFiVVQTVpzzK6bAjCwXcF4YS8XA/4leSKAs0vDbUu8NI+H7w+akU"
    b"Li0jVBZKFVGUaWtyw7YIDlUZ7RKNzqwB2OZaaAzhYTQWChdDBz92aEMbmruMMfScXyczNHSAXybJ"
    b"4XYgvCppQs+HJPlffnKzojzJ7HP89NuGLAzepZukbdzeaELr0TJDibY+ylQWIc6SsXh50zwDPajb"
    b"phg8oL3Umy7N6GkNTKOOWS2oxMB3a59R+4Bw8hPUSLdXdele1WkwKjGYkG1HOm4akbAgSqUgBoyZ"
    b"Sk9hW2jtr93lrLdwaIMjbvlZ2/UYLDtsLYVEDNkIbcszyMoqKeb9yam2dTAyLzEzUA8tNybGMkhw"
    b"lFNuqWPfASOIFTKjAT49Lo9U07IpXtoL0RMzzoNt1mHrmKV7d43FCY9NYNAyfWGtIhTcECC5TFhH"
    b"u7KKImiYxx4+OjHlV69NNz7j+lFdBkt7cd0kdKCQjldhD6gb2VKpJNUiUdyUX+fDdkSLhl5a4S0s"
    b"sSNVCqUwpqUk3Io1sai7xQrJOA0GLlS3kgt8L0KPnS6nyUJYMj4yTIfWeLQJUdUkRJz7CKuGf7JN"
    b"Heh9hayWgRuB+TDN2v4PndvfbT6skGiS8Ilr9eOcL6+ElhMZefBoqOKKEl9C4taAVPeNYcz9h7L3"
    b"8dJ4PeNjX7lSinNVzC1a32XK0g6jdqycatR+1a3UhuV2w0KbzsCoZastGZPDqeAFHPyQTfbMnCbV"
    b"M/OaRK9129ugfK2ywp0T17BSHKg3k4Es0kPgGZlFzikwaRYOg3oFibTNE2v78GmqJxxjsaKL9lB6"
    b"tVRevQzfsLNbwasBZfA/MkrWIKnOEpBT9zhPjK27b00SBVCHGNhDfxvGUVQLrO8Nx45RfIMlYIxb"
    b"MlgktBIkQPtBrX4tzQwzPtDHfZ7GCS1tcuIppWzw0SHpdQUQkrU3pBx1m24ENLGQ3p4skBtKX2gO"
    b"LWafrWD2ZSwWFdSmGfrP110Qla1evWLh2n0NtOutiRM3nW7fH6XTkcK8gmwi39jE7uAolkuAM4SL"
    b"JYhK4RdkY20cITR8dsQztFVaPSb52Iya7UD5A1UVu54LNyyX2kCOsCfFRLOTXUOW14yGrN8uzGNU"
    b"9lR/Vd9MEy3vWDEU4sTU7Ab00TzbDqseUEyldjhnLNP6KnLWsZprazfoftayD3vHRUe5r9pdkAd1"
    b"WknTECtoQsO0a+Oj6IQmIIdo5ni1KIqbce8vDG30OHtUFaRNQb8fkPGpDoFM44DBt5os60NuKlVL"
    b"JjqZp33bOrEPFWXAmD6HCQmCvrjVldfnTo0Fa9s9C4JN4UlNBxmTn4qXRfIlYt+FaD4XsZ/FMwgR"
    b"+yW0QgNigjIg+aV2LXp7XxjpBvEarlyH1tYzaQbxA6+TuUN6UFk8bIvGQCzUqeMqZhGjUADMeEcZ"
    b"X51aTtn54jIahGTIbFlmcqNmlYSvZnADZ++BRybO7Mf+/sHLvQ+vjs9+OvhbSDqvqGX3zUPnYLr1"
    b"gEbYsDr2+FsI29yQZBsv47cnRV6WIsULjSmLlrUpmChrw8o1uyqsmJEaNp0ZjLw6dJkII34Mqy7D"
    b"oFU87aTeK8FEfGggCF1Gxj5UvuGyPz4ZnLbqx/QYCmy1k4Ows6J2krg72x66m9jCNmA5qNdpXVrs"
    b"deyjx66CCKIfeolcJsFNI2tnNRuDJkZn+hkJWPnX/cbLEp3A0uOTP8Jgg9F+uL2VRyEQJs6Jf/Cr"
    b"RvwysUU7rgXCDRiUfMHFeAAFDjgzY9rUXEl6YbJ+712xcEN6fkE8HWY5h/KnQ4V7KPdy5RbcGW9c"
    b"P0/iZ8EajavouVKzmzW1rtJY0ThFMznTSNpNbwFO2BUlt5Ts69P52iY+sXqkSexG/hkv8TQBQhUu"
    b"4KwCGlTL/HfkIfljHfjB6N8ePPj3XglS2YQBFcU7lQ/vX8XCrPw6zfr4J5n/2/8PFeo+mQ=="
))

PEERJS_RUNTIME_JS = zlib.decompress(base64.b64decode(  # generated from peerjs-1.5.5.runtime.min.js
    b"eNrtvftD20iyKPz7/SuM7nystAjHhrxGjuLLBDLLTl4nkNkHyyHCbkAbI3klOQljdP/2r6r6LbWM"
    b"yczOfZ05Z4PVXf2q7q6uqq6q9v0gfr68WGSTKs2zHvNZWIVZWATLt+f/ZJOqP2UXacbeFfmcFdUN"
    b"ZS8vWRVlYQn/FiHLFtesSM5nLNoYhJM8u0gvF/K7DmpVdeWzYFmwalFAM5ubrH92xsrX+XQxY2OG"
    b"zSSLWRWxejJLyrKXLaGqsioWkyov/GBZXaVlf3K1yD6x6evjD/Hw8e5gEFLq2TSpkhf5IqviYajh"
    b"YgYDm7GqV8Unp2EWs/75TcVeseyyugqL+HVSXfUnLJ352YNG5UGYxoOwjAejC2h7VD7LRgHVlPNS"
    b"12nmw/C3WsUSaKScpRPml2EehJN4eXY2Z6zYhw5Gjb6GWZSG+BUlYZVXySwq6lHVny/KK38SQOt5"
    b"mG5t1QJhjcJbW2FV1wJVxTKZz1k2PTtfXFywAtFM4BczrCsQSJonRVXy6llQ8xIK9GyesgnT2aLo"
    b"Mr3wrfwZYe/5gKODxRn70vuQZtXTvaJIbizYYORoNzQhYFrqusqp6A+867Lek1NCPc1eL7/oGVUF"
    b"jFdWBSOBG7nCcDR8vgeqdIalWVBtxZkx/SPKavU+gGUxsBtmXSPtc2SHFVX79uICdoP44G0Eo6wP"
    b"abBhCqh3Kzbz5KxmNfRZ1FQ71jvLJvmUFdT4MftaHfDvJhbNGSakqj2XGnsOK8mxvUU2TyaffGNr"
    b"lhp1CJXAboGViEBMYRkqg/4l2YQBWoAcXKclG2f96oplPtKQqg9UQU5jEFmfYqHmS9k0R2pYxdRz"
    b"nnq2QPT6wQgX3bPhztNArn1M8Xd2Hv5nFTzb3RHJImF7d4eyGVCEAQLEw0eBuWlE5UXyBQcjQJ88"
    b"XgEKs5Bmlwb0w4croBNaDxp45+kK4OtkjqDll7Sa4BJeTpKS9Ybf70QSy4vZbCQSdyP6sTPckT9U"
    b"ykP545EoKMs8FN8bQ5kiITYGPGVnoBoze3Yxy5MKkC9gdl0w03wBZF0DPXQByVkUMI+6YIaPNdDj"
    b"LqDdHQ30pAvo8UMN9NQFZPfo+w4Qo0PDQQeM0Z/hsAPG6M5QDYzFrvGH7mUnCj/pLoz9WF346T1a"
    b"FntDlPz+Hs1aJXcG92hTbRtRdniPVptld+7RrtiBouTuPVrlJevaXufieNh59GiTgPGI/jllX07o"
    b"K82m7OvpyFwolATnN6sb3RQ1EVDBkqm/A+3HPtbMTganwR93Hj3eEp/D08BRabwDXEFjCK1aH1Kt"
    b"UM/jP2K1W1QZ1c1OdtSvXVen44d2/bjSW/U/5fXjf3e2IX89VL8eqV+P1a8nzr481X2xZsJFi+Qk"
    b"46kyZhHbhopre+d3lCaioIrv7jx5zCt4/OjRrllFE9VNGqaqGHx9OuD/UT2Dr0PxOahtEtJRG1EX"
    b"R20Du9aLxn+1tWEVX8f5uWcGXoFXuiryL72DogA+5OMPaZYUN++g6MsknS0KFvUIrpfCcb4gFqlI"
    b"skvW+26pK6nhi9UyibdRfwxGnMNQ24RzB4Jh1qVDqzeuqWd66hXd4+wLSi7GWmSSk/c8zsqnz9go"
    b"8Ku4OElPg2fAMYx9YHWQ0Q4iH45hzmFgor873ISPZ49vH+9uAvjW8BTA4h2AE5zI8DHBDR8R3HDn"
    b"1leQZrkdKrcL5QD4CYd9asMaZXessrtUFnZsuRUf0Uj7F8B5vQAm8F0Oi8HPOvBT1g1SKbi7PUk5"
    b"FX8MDG8GSMkAA9VJdmquN73QFLo5DRSVLeuOaqw67qpSMB53bx5/EMfs+fPd4XgYbQ+DP/pPd58+"
    b"fTx4sslu+a+nQDD++Edgwp4/39ndBEIZbA93nmzv7AZ1g4FZ0ZiDJ6VkmDysd7AJbM8TqHiws9vV"
    b"L384ePj00ROg07f812PesWx7ZxBsVeL3o50gqMUqXRo7g+aQeOAt9iw2dpDFT8pjpl8uzvkcg/SB"
    b"28XcvZ5j92KLYgub+9cLLPlDyoUEGAs5W+9Z3IFmL5xyoAYX5ygfRmv/G2KRkBOSpSE7LC0JmMtK"
    b"PyzSGchB/YbwWAuRBcmbxymDF8fVzZxxIRBraHBLbAZ8AIJni+tzVpjgJOrD6iR0xDDHY10BDJVd"
    b"kqgd6USxusxaz/N8xpLMrHZjoOtqDEcI5cCzB9HGEME2N1fCPdRNfc7TaY+qDlYW2TF6l5OGx+wc"
    b"pKIEsnY1YuGyvrF4cO0yU1ikObLWeEtwqhzCpVrvhozp6JJQVQS1HFa7bbEKddPnqMCxlywLDMT8"
    b"8Lfjg6Ozdwfvzw5eHbw+eHPspZm1gFwVSI0AMzUCptLJaMHq435SuRYnrG5O8/2ugj/M8nOJJdZP"
    b"zK3AcYYasLtGHa5Aaq0bruKYKwRvbyujZ33oTFGVf0mrK9+j3esF7anmC+23nmuLUTmGJdzzgOUw"
    b"Old7vSyvejfQm3Ixn+dFxaYfVxYW+8BdcLQKUwrDipozQfC4PgMVAhohnDEF/mOrMlD8LEa28tGq"
    b"nQeCnZgxk0W1K9Hc3+qavm/WBAedrMk6Rg6zz8kMyAsfj+dGRFMHWbv4M74mziqtyxI6LmTVUOmk"
    b"UZa5Ufbk8VamR5uthbLHDpTZlayLsicOlGW/EcoqgbIGy7bGMnr48N7LCDiR32gZ7Qy/eRlxzrEA"
    b"IgUtFs+qFuHw2UlhSLouDaRBMTK/2BoGQcT/1rXSXPoDgVp9bGOL7Hm8vbuzuQlsFvCJKweJQrdB"
    b"hJ/HAyqGPOaqYoOHTdw89e16gEN9ulYPBta+d9TEe3T3zA8eOWa+0SmSc6k+/HVHx75vdKxVHe/Z"
    b"mstp8NixnBrd01KvqPnJWpt30OjoqooHdgPN5NUNDRsNgcy+GiPrYaZFfIx6nRtNLHdPrH7Fn6pb"
    b"EvYMeuLjtRmLt5nckAbjSz9nORLwB/T71ZudQF6ecRCfPQCBJkPJx1BmcCyB9F09e7Y7vM22UGB6"
    b"9mxncFs8MMA2hag0Wjnw3fbEpe2k4v8zKhZDVoyHGLK40/zEbsq1T5ydp/c+cXZ2fqsTZ2f3m08c"
    b"HHERZ5y6Zs/kSDkqYGJA2idWvX+VlG+/ZOqGNw0CzTTC16hNlNPT+3ByhZ8hXZaXXvxTk+dCkWdJ"
    b"IJcrMMIMWKI0K4GfP3/qZnAtwl7btEZuj1u2aln6OINiFVfB8+fPdx6ubErBc2jFlHRAP36081SA"
    b"3j2EyhgCEQXJO5h7Da/AzS3yf87gwjV7mt2rp9n6Pc3W62mm2Yy7lrG58NZZyaIjLLjPilYLevUW"
    b"AZSRtmw9tLH10cbWQ5vRXXPxmvoXcx0H/7WQf4eF7LBGsOFJ5ydNEQyBrmmsUNfeAs4qFAQnlUeH"
    b"ySTeGIRz+GekLBCm3O6Iz30BQs91wm/I1SmxuVlI85M429ycJ0XJDrPKL+AcC4G309YMM1kXHFEb"
    b"rP/++MU7xooXeZYxAhBH1Eg21QLoz4u8ylEZAAwMIGY6PfjMsupVWlYsY8WonRRrGxQ0ncJjdSOO"
    b"K3kYpojcGdeLhklxubiGsiU/WUvDTgm1B6MKWLICDuVsOmPUyNj6ApxEKCwGtaX6P2OY+TqZx/bn"
    b"7e2yDu2kk+r09tZvpdHEwc+gDU6GLEVYAkNnjuSEheUp9IMPo+gX7Dr/zJq4cqSa6Mo0um5vN5qd"
    b"33B0vZ2GLAxwRRLd5Qp0F3G79CVr3aRY+VMGJRmAhKhgdWAn/YVtbnKodnEqZDKeNkQgVnVHBWHZ"
    b"wDgIxHXots0rQi/PvC1uoGdrzk+8M8o6rUMySuJbWqWiFMBvzVpzhRcLJmgQGv00UqWuurk1muVj"
    b"IPfrGw1eaQMmpUzfUPrqseB998Qc9zAj6kEzAmDL6/feQSEgQEiEkp6oo+8FkT+JWcjGXjJN5hXQ"
    b"v3+WPZB0LtPssjdNS+zL1ItcuSzjmUY3F//GbgKhZKHZjymbF2ySUMNfkiKDPpVQmQ9jMTqueml0"
    b"8wIWRUvr/yXNpvkXWAGT21tvkfE1NdXdx5MAerO56cl6dFmRhyLi5qbxIdasSDH2oNGZayTTwXKu"
    b"C+JgfEAGXi7LQbJp2Jtr1ADOMB/OJpZM++YUnBlTcMLH2OPb5NTTG1BRdqUm7k+S2YxsHmVNl/ZZ"
    b"lI29fFGd54Ca7aKaA2rTTH/BCSHo5khfnmjCL2jjiTJhYP2LvDhI4GxDsu9VBXA+2D/oEPQKzWIp"
    b"6XAK6EovUqCVUF0/nW5uauvMAIiCrKWCWnSdKO1lVBMUgyMzk7WpWgxLX2Hnu5Hd3hacggJEAEdD"
    b"QfQevwALoUm6skA1laJg2QeOQSj/D2GpjbHSitNTFBKh+siGKb0AegV5VpeNYlgGCAAsFDwbwpQ+"
    b"wtRmIj4nRe+G7p/laF7wxcQVGITGLPmcXibiPmoj61+zaZrss88p2qZaHIBpP2pci+n9e3uL/Eg2"
    b"xdpu8COfI3wyU5cvI3UjLlJsRYM1WGyiYP9apAXDiQfsw+b+jFL0VH5TX4/yRTHhIHZ/2/d2wAKN"
    b"8Z9omU5ZMovwdz3iV4JwsBZ99jWZAF/RuuVUOTDn12kGkNfJVwnPD8zUPKwrbcE9ZltVf3KVFHsV"
    b"CPCwnT4A/1i8gI3qB5DDrTqGQeRNCeeHNLhq7JU0LPiMqnqkLi6pl9R5OJkUfmP98/YW9hC/tgcs"
    b"OwZChceonPA9GIoHS/dU1hnqepQlso8VBQSdfLWgg4gquauGuhu/Gw38jv1KL6C4MhcTcmf622yX"
    b"z0F0wkdDvTy1iIdu/4TRCb52G4w3AcX49mJ9uQKpGoV+38Z/gNe8QJN9DY/3h3VorZGUmxf1P7Oi"
    b"hJTn8eOhIofaTvbPR2/f9ImJ9+knvyhKL+hOEmhEe5H3k8U0zaV0aC5KpNWoi0K3gg0/o19QhY/b"
    b"IGbIggmWBX8Dv1rd3QHeGBy7iyr/MUkzEA6qIp/BPFzm+eVeIxWQ4DNZJMvTkh0t5nB+lYgAUeZN"
    b"M5nQjkXiQhYOamSFnYP/DMtQDB4kBv7Zv0gm0OfXIGaNyriEEbcKluNSEoWy5hs6j9XcPHv8GKeD"
    b"SgJ9xf0Ul3zhARVi2ee0yDM8uO0MDUo1u0D5RqLpsCgvEvkjeaX6gmRMwGNV4lG1DpwfGIOG6nN5"
    b"24zjkLPcwk7YPRZ3z8dVfOKd49EcAq1OCu80cmGogYiAlOkn3gVUWHlw/Ck+oDE4wf5WTCTI+/pM"
    b"SIJ5DD+z/kU6q/C2Kn7u0YjSbL6oOLPwCZg2WKXAqk0xH+htfs2QGQD2KzlnM6DHr/Ivkh7302wy"
    b"W0yhIZAbpaCzkSPSpfBRaRg+cBxMHmcnEmR7CAPKcVcJ9Eq6LvExXtKfSOfUcukZSbjqqTyter6q"
    b"QzgRJ1cFjACZ4vZuDFPieup2SalTXquCsLSOeqWo1oTq4ZhFyyyBavzlO1Zcp7RT91mWsinx8JH3"
    b"Jq/2ZjNALU/wQgMuLfFXN6hQ0R9VMPNdMGJFQPpL5DE1mP70Qr0hIOMIJIHyQvfwLYxnIgFUvcfI"
    b"Bx6hsYau8j3w0CgkCJDXeomiuRib7i/YcX50tahAPsgcfTUK/JTOZkfk1fDWBXmcnL8A+WVRyHHv"
    b"neeiJ154NCkYy7rzeQud+XCII7d3zU6RNcMf4TWQ2OSSRcC28V+hQkgVSWMl/MAS+usNltXmI5bl"
    b"Gda7xYVkUSeQaVhtwZaZVtfE02RIvj4AcSAMxb51WKF+CH4wYtW/sPNPafWjAU0wmIkaLx+5Rzqj"
    b"66B/jpsdGOQ2pVSFlbdSN4ioxuaHRysK6E2jub8UGXYgNpCkLY3o1KdzDAgzwzr28INWHpI4TkfQ"
    b"fog2rwT6GT8aQMIImfJVlsn7MNjg+RwtlEIUv/bfvj74OmHEqyAH1dgw2mK6RtSKq6p+weh2kHAM"
    b"WG5oKpVs8RmpBesTMmBtsOQ6tr5wEfF5NBK1OHm+Qq5wqSfhXEG2AmkwMjKr1JMBqjqFDIkD80l6"
    b"zMoJS4EI3N52uXB6BpQXLoEqLYDwgbxNKRFihv+skV4L87Muh9CV+lM1FIdOqn8mMi2dlEoV+iSX"
    b"SkoO2YIXesuW/skJvI4WaiQNcFYMECXl99BDPMrLSZHSChzdv4jeZG4UzfPZjVLaGmkxyv8Vnnaw"
    b"5hxjhxQxfMlbFKM7dN64596L+S+5naqZ4muuQ+gqlNICuCCUVtVHEC3pZySSaiFQ4o7lumwxNyAU"
    b"cAhZOEzVEoyLMDVXdazXaQGShxh6GZ9ILAh3yGlazvEOgTeEeoRQ4clFVX5H/JiYWQcn/xZs1F3b"
    b"BVJ40caWweWG4p5buV4bXqfHDYqnxRhERQu1KCV4yO+zbAoIvJvqwckLLAOyz8evX/JSdxdyyI1y"
    b"q4m5qELoRG9aXV/oTajMqoUDNmSisESnHCk0iBMf61y0hW70DW9sDADUEco7Fkyow7P5JGKcc9i4"
    b"c+kJLOGJtB5kJ2kpRb71hXJ+aKUIVY6458nu2BywemhrjdYDa1ycib3QcX8jmQ8ghGlc8WzlUy57"
    b"S9qZFHn+ep0bPnG+rNNnA9IWJFZcN1U2drlDxdsL1INsD/HOS1r4K2TPuTtUiCYyayKccxyjNeGs"
    b"vt+1EjL79gnveTp5Msc8qElCgnOP6VhrRCbovQZV3GNQrkkk+l6h1M0JNHpLjDpn0jn/VYATDFPc"
    b"7YzRQSvvQym/hVCKZt9Xc16AqDPSKVVSZRnUVVsrr0eURt9CvYTXljV72jzYullhfSCqNG0wuV33"
    b"pV2jCfl4GyzrnUcBJvNzvnkmiPgME8fRoAqtPiNwqajz9Uicrxvrr5rmnMpvybbIu/MRrxbxXyVV"
    b"+dvOeUXao99x3oP7HVnZnf1rH1ta4l55Zul+YbfCLpz2JeIdw4eytokCrCcJLhWIQJQuffQ64lz0"
    b"xgDF2u4plbP/LZOqGN71plWB/zYTG7YlX8kIEyBIWcXkYMZwFvD4CbuH/FvjfLga580pFxR9nakx"
    b"bgHX2XVY5Wg9MHPo0HW1flXAn81NlXYyODXMfi1NCO0NFdyFnLHNYtJhVspMYqsbJy6XZuWpWuDC"
    b"GmfxxiCCuSAJziVt6UXiM6tsxcsCroLQyIHVkN3eor1KMG6ogtq6pOMrVrBeAv+7zgs0ekmyXp6x"
    b"Hj/Qe3nRk+uuBx2BfIChM8ALpUn23mTCylJoooIIo13pNRRV48r8XLNDadnL8m/vhAor1SXMqbPm"
    b"E1d+3bGIXuWTZHYkZM9OeeMqvb5mUwu2M4duLdtWUw7IoE9e6dJj0AEBLB4G0KjX2jm/QoARJodZ"
    b"sBq7o29Eh7RfW33SdGMBFQ+n4+2hYmE6gRSbWgSKq+2EJUa/kOxLJ1x8AuQAeO+1xchfL9Xce711"
    b"iwEyYIZNtRxygNBcO/YtgvSSGTrg3/TY17QE8tqxP2tLeDTbHGV32zY2+ijvEPnEGxLoioV4wviU"
    b"sVN55V/8jvLbr6Qalh1l5+DCDrFdKuT+7VqDXzdIOL7WpI7m2cq3XjdmqtOWhiJbRQHQ+JWLuRnI"
    b"s+Fq0gLATlNXN2zdMDZ2nk7vuRrvDkNv8nJah5jjNbi+DVYR3CgM3jpUq3ESjr753GzLFA36XjDs"
    b"J7PXip0oKJp1ONoQfCOsubF/BUWujECSpb26ja7eb2DV/zakOtxw4rYi3C51pEmLU/at/itKbJaN"
    b"MydKxGmK969ZbWuyqtN7US8xnWYUSG1DWfXL6dxpzdieDrQMa1IZXE4tlJyG2DM1TLStOx2hpUvB"
    b"5rMEqMh7dnnwde6naHrqXXpBiCDykhdGdMSERYa6OPMpaENUkdFrCH2OMrIU+TWKw99oidq+EvYM"
    b"084DIcQ2p29jrF1o7EiD/0X8ULMJqwlTh/dlaKUPjTeZ5SU3TqV6y/Qyg32QXZIhS/cuAimk1eAf"
    b"yp5dHCWZP/AG/mDsMW0jozxZT075TQQ32FbHAZw7SOCHZIcpTQw2CmD4bQoh7+TIPHtlpw1Te4mU"
    b"Hl5+ASs1A9lvdiODgkA+jCa7nLFej+O69+UqnVzhmJKyzCcp2q/3vqTVFclk5ZxN0KZ7qqUztN+R"
    b"Zm5yuN0ETN8p3jGKexCw0W+66AX5sdcfUSwcVhqkap2hClwLu2U++8ykRoVCUjuuLY070oxd5lVK"
    b"PhAZY1Pu52DEJCocJBfp48jRs7hwE9rCpMLqWENO2DyK75ylOjwRWvi36D4H08C/9rLyC3xqm17z"
    b"vFyD24DhjO4CiP0l/KsYCr1pqrip43H6dzi0N71qbF8Kab6Ss6EhBv/A7ceBUJUdnmTotUS+CifD"
    b"002KYGnmI5Z0Wzunp0HUIegoc6NSXy3VAfGLwrr1TuMLYrruZa7RLGGyauiLAOcm5w8ljtrINTFJ"
    b"Z9XYN5Nin2sbzYmB5FAcxOHvfQIX6gROv+kEDsLcPX9BlK+SuxLpqAPbyghKIJtDX+DV9kazxlQB"
    b"gfsmu6VWPfI2SOwk7KCDPfe0L8+YRWqN1lLnf28xURk3/y8/hbmQdTafdLal/NuGGFewPVpjjL1p"
    b"zkoKspVez7mansKVFBewCHuWphy6g/G5jG5QLzY4Hjo7w0v3viS8GU5zp73zGyLb6Lkmu/WtB6ND"
    b"/m7K3Jm+FpcnjoMtqewDg6zIm6VI+w05XIljVsEpzNgwlpMiRrdYArvVmAypNg/C+x+6pjT+jgsQ"
    b"Gx03kNxG0pHl2otxJ7xzJxmS+7NHu5ubJ56DbMNEu2zvPPSunB6iiXE2TaewTH6nQ7l5WOA5AOj2"
    b"W90hzymq1kyOKKVNkAPrZAnCrEuNwo9NPX9fhACIV2vtuQ6ZOuhhvUA9rOK3xRrzT3Zw8W6Q+fML"
    b"aU4pbFrheMm2zz3UKLWyMY7gFPb7dZJV6aQMALys0A6TvN+apE7Z8ga2wS7zb2CCr9Jrg+nzQmQm"
    b"P8OakZlvs2N+a4gZ50bGj4qRQ2fFfbIAQJhjA4YDyNunH+W9HcEdGXB7gsl9rzcZVvoGRvuZcfBP"
    b"q8E50HsDyF5RPP+dyL9Iv77RE/ZGTBhCfLFHqKy6ee6LgHwpDyxfyq/dvpRhwROad34Oo/emzfs1"
    b"0A9ZjQUJ209ndFqheyvt3tHHkl/GovtoaKzJ548eAWfbdONKWy45nf5GgTzyf4XHGepq7muRTxhd"
    b"wyg/U17PTVuQzOFIlkkDfZ/5cDp1O8FlK53grvNf2j5wzM9W+MBBkbYLHDrOZYAfiu7RMAOpKnRs"
    b"l/YIHdmjjvSmMjW769oMNdiuYbVHTwN1j8cxcFi2ZA3QGCH1xVhnrmE2YUarMl0LwjZNQqMk14qg"
    b"tXDHUrjPGrjX7FuSJHI5nV4Y+5wqGcTI2h3cjGIfWJdZcsMpBllTuKG5p5C7Hr8rq99owEI5nYQZ"
    b"etRxzzTz3SCbMW3UQuohDMVN5XraG6lEplzHYzDMYtAXKW76hKEj05TFT8OGBQGT6goKPC26NxZ/"
    b"46Xhah5VdSTS+0ZyjLYta1Bo3MhBx+QdoijTaaxGRwjxmDCL0pJBGcPoXNNoZsO3nFhWAQfqqswl"
    b"ArpKNB1kTDtAbXAvOG7pKWNyUq/VvZTT68d3uv2wPuySNrsrb7G62GpXoU6e2tlC+F+88zfyzuJW"
    b"cCkighTVvBEdREYOoRwrjEg4kX2ZJ2kReepzG7+9kBQQKjHiColtleCFBc2FAcETDJA6LP59ZmIw"
    b"8hMWpmF5qjVWKliXbWB9e4tKvtOmq6C55jbSoCpulqzh5EeRTLIT/oP8O/EH7LSJCA9GW0yrB1Ap"
    b"QORRqAWqka6ReEPuOkjRrARNSEoUL3xUdIdck5WdVLK9SrSHlE2LHXwcMHRT+H37a41yAxyebaW7"
    b"nh3uPc0C/8sY99cY45qqf1KajNuGoaZRd/OKQwZZM1bOq99r5ThsSu+3dv7vtvntNPQ15tOYtj2c"
    b"tg4HXlMPd6fHxe2t/4331de+3VLoGVo9T5vLrjS0xdVk6hN1rAgxZssRV97dkU+6wsU/uZUovnP6"
    b"4iqBIczIuxsGZSX5zaTYKmNU+MN998S9rKM55ZAM3hqL2S5gLhqui2fVu6SAY6cCLIsdT0G/Gtdu"
    b"dPdlfvXRgpcCZZIwqx9xwR7FuC84zcSPfr/PTgNlkT0iMtAwfPGKdOoJtcSD/zxJtn8ZbH9/uhyE"
    b"w8f1dw/SfsVKjFQDUPLyWJ2dOoL0+8P9HrmE9wABKA5goDW6giiBBWHvkZItcPj7+ZfshxvZnk/C"
    b"40t6zgm2ogs0eB4PZcPv8dkh0TIBnxUK+gwDTpyd3/SuF2XVO2e953Fv2B+IXlwnX18isjGAirtx"
    b"EwLaHLjaBJizCwlkNjTAhurgDmtbVM8QMVtyI2wQnuKCrusuzcXgByOPyfkltRPq8EkJqpKV1QLG"
    b"crKirWkYZEZlbASgF0YOvsVkLyP5OpNzVQq/PDsT47rpm3dpQ2LXCmwPZ7pWwhhhvk368OHu7axP"
    b"M8dO7jid9Qj0Hr4T9I7DqMUu2PPHqbXG/omykBU4N9Bxe3uyrE8DOrw0Ll7+W0mbYWkwWhuy6xR0"
    b"riBxHLhXl7iMklwPWup0Qwfm68Hu22K8IINKbgybkC5iW+Ot1l0Go29+B+Rzw47R+qD/16O/cU1z"
    b"4LiJOUTd4UH3TcdrI5/vb/v25a2R776feWVBmFwT5u6ZuRaPwvP/aeTvWdwAz//ByP/RRBHP/mBk"
    b"vzCNgTDzZStT2AZR7hu75sYNzlc711KAEsA+v+L5xbri+e5+ERo4bMNe+dfztes6Ds0s43e/nYic"
    b"UthORttcUgityYiv6fy4vodQp4npt45IM+cM2ABHvoxu6Qi/ZNgkVNyGkvZpJkSlViSmVfD3NyZl"
    b"IfCvmX6MHjXl7eAB5ljG3z78yIVQdlqviF7ye4ls95h/K4BEAw3KRwM2JnfskeeUA9yIKaF0MIbE"
    b"N+oWE3mQMo31bomQcYlQn7Q/3zcIDBEYrmD+LSmMVWMniSlMqLEjLcITDslJnukAOXcTlOBbo2YZ"
    b"UXjckbMUQCt6lspZFdXdFeZHJQnSs07oLVVGhgdaO6iQSorZuqG7rMZiGQeOL3KXC4g9hWqjWakG"
    b"pbXSTVpj7y0bTJAcsVkNayk9ZNhhfTlUl4mV0Kb8r4s41uXt3sC4ILn3nCbzFqhqTVfFp4u154q5"
    b"Joq1Z0kGVEE5X8wTc05SJalfxyRlcpLwwrNhBMfjJMvTg3UEvvrxnqH+7iFbkGrBENnwnXNLiMC3"
    b"1ly2ymHJ01sLIMRAwI3bslHlFguVQVDRsht/Hu+MTdPtyLJfbgRzsp5zHPupuBEKXb4AQZSim5db"
    b"UDIslO7boaJpc3CfDgkj5aYtEEdN2owrpF6gHPuFtE/KnDUX9cg5e3ESumcv7upE+Ws6EbZWREcr"
    b"+a9pRW+YPxtvlbWC9lcNw4zq7rinNkgoGJ2GpRUGa1phWcXwJdG/UNzVjcrKanZhZZcoknpnGFh6"
    b"eaFaw6Ato/cQeMcr8/mMvxhOxIA7FQxehEYet643WbiknMh8AkJVcQa/x5ZFcwCTNl0A36jNXHSI"
    b"NgDHvQzEJcVHH/B3hP8CUUk3NzfMikqpuBw1AykBlc/HWWT3NAuXUA9GK6/DJSoVah3tOYiYRsDf"
    b"pCrnWwir68B0vEqEaxLm5ogVnynmHq/v5HQEx5fPyc9glD0zgeRgs60t/ZqVzsZXFxUCiv6imJVo"
    b"GQZ/x/6173EzBQ6LiV7YSiq9IPSLFfZaBZruISCvX5oi8o9KxmtAdQ3nXezeofOkTogrqc/FQ7Mi"
    b"zNwh/MWWIc0lcghAR14A25tepBOhs69W2uTYVbsrIbY44sorR76pcf3T/2PWRz+Zr0f/G5XF4hnl"
    b"YGkQnxxBjnOhgtuTxqau9Hhjw5neDH5h6NpMHztt3mjcA+v4a8FoYxh39ggfIgFpF8p95mE8p2nB"
    b"Bz2m83a/49OnYugE6uEGUqVinY6GOJPP9NOumU6ElXWnWTIhC/FG3Ub6RieagTvXDLqBMxmiLlyq"
    b"Go0uAlfbOXs/8zDdvjPdMXuULpnsu2aPSPp9Z0/0KLNnLzNmL7MxnHXPXrbG7GXW7N1RtzFL2X1m"
    b"jwZ1e5t1zB5HVNfsrR/J6a8mFbQfN6L1g0a87GtFkpeZoDxxzEQ4JfxfuNbZVOHuvTvkWufvUC39"
    b"i1a2K1FMQfxsQLxIZjN8dELn/mjktpXefzbLaoNZnvkXs2nj7PyARydB/M2A0AS4pdL/k9mKpn+v"
    b"2GUyueEgPxkgJnp47l+56v0/6MUi+wrkP8z+aWNFKsZQf9sB8Z7Nkpt3SJYnubiZYJUB/jr5+po/"
    b"RXCU/iLrywwA1PEd42W4NprjQIUBpI8A8rgREKmAEGqhr9V1MqdnHl6nX6W7CSuNavZsUeLNYjZ7"
    b"WxxczyuBPXz6QwGrG5MZ9P/IZYBKRRKO03+1cIpU5+/WJQdjFododkUYTJlJ6P+MxpnkQaNOdBPC"
    b"bTYlDNosKbqV0vXGmM2MTHRfyAhEJyg1h5fE9DLL3Q8YqbJWPeXinMP5O6T1N5o0wcynwrkrPfYc"
    b"VQz+vwLeqBqbbxQMFGPM0CcmDehP50sEBQkl9PpASvp5bUBa5Tiotr52qQ1eC90uuh2/TqeQxH/Q"
    b"9yto6hDxJpLVd4jv9qCV6MsiuUQ6CQDNpLoOC5P1zegFmRVrIjaVNWSpBly0Ya5bxc/9ysS3GyVV"
    b"6BmFBHJ4LING02ZtQfilSMljLvIuklnJ8Fy3xEWuIl53JxQWmVm9GW5vHaNlUq2nuyj9cFavIHMt"
    b"8W7wc5jz3Rak1cnYXw4ir0ISP4S/k7kX7kTeYjrH92FwatIcMHSDzyqfmra8BoaMEH4rREqvnFTz"
    b"NW4mvknvT3WvjjuMIGO0p470d63MlRp0ZoMrHmH1i+5vDEfGNODFUHXEu4G3OwinFDl9oMoX0I8w"
    b"449LafdPPYW0p1Choq/1PORDUv48KZ867njEg4nxwcJ8aYp29OL4nUcPEqRtz/eYOiVeg35wnf+S"
    b"zmZJv98//tPh0Rn8/9H+u733x3vb/j+mW8GDwHyDE623OR17tiN9Rrfl8NXz0dXJkJ6PViPYiLPx"
    b"9jDKms9F8e48fvRo97E0DLoAjuwi/8pHeQ5nasko7Ch62Ujb9ic84CIbDx/vPn0YDb4+uaD/HkUa"
    b"6PFg/OgJd87hKWNs5lFEjRlF6K293Bkyn/ero0d25dBDDv9IPkBN80kofgfF0698JYRw1lwnX7fF"
    b"00bb+MpxpN2QdGzYcarRSeEt9CEz/D5A5EYdHaM1UVCHzFGmdZj8/pcgOkQZ7CiKwB2KR8Uavc50"
    b"jLgnj4UNoOG9HLFaCT8NL+eR9ILmJp4dJwBy8N9MCe58Whl9EW0nFxWwN06b3i8Y0iUIizi3MijC"
    b"S0zuZJxTKcZv6OHL/ru3R4fHhz8fnB2+eXn45vD4b9GAP2nKoV4n1RUaZ5ImMeJfKdcrCsU68G9u"
    b"rCT0AqbF2yoFEKvVIxA4dYkk78mdMhFGxhT2YO5g+yJgu2ENdPedrzgoVCOV5U9NJoIj/qd5B2eH"
    b"S6a7CmkbWtAr4/j3/KZir7iOkTjJOcukGJ1Mb4hhR8U0omJzM33Of/Vt5LWNf0Vmr8rz3gyd+3s+"
    b"nLQUYbiX9KB0er24xrAe3pazxi2vhx0rA884QVy3Zes4gbSwPron/L1dQmiO5GsBxM8Ai5FMpAUY"
    b"ehugYbFICGUABHody1hO6Qqd9O2tN2nIVXeupfXvB0fd7GRTmLOIir+c5BiBpWLTSIKiMDe5YhM4"
    b"uC9VIvxGVor2GT7HZ9d6KpQX7Zw7KVLY2fM8030vsS5E/yXrsohwAnPfs5aNhBN2pb1ER1dWVtgI"
    b"7tcJxYRBTftm/VtaXedts/BeTp6nrSdRgAkEgW2E/3Ta1Dg7Zz1k1gkR66dXzFgjVf9slpRVY4WR"
    b"019jlePlmgu2Ddm2CejAOV0btswC9MOCHTOIctGqSezEQbDK+9SgOeXKGLhIdRQTU2kmxgh0+2SI"
    b"8VaSi6RIu4EeDx45tB6/H38mYsjSyTadC9aRfmtJ4h8ZsI2kltpOUC+1fU2KqcCKacqFHgT2zOjY"
    b"nrMoaWuBlb32g6D/zxx4FSo36vAeht71rLcRnFDjptNyF6AzslpEo8DYr/Ypu4LJyfUK8bvdCe9k"
    b"aNZ037Q0Ycggktwn4+D59yrvoC0m8sb+HYv72ZOnsLYN4cMJ9PipewMEdtg+YAcx24rkp7QR45al"
    b"Q1cEw8hf4Q+mYyK6bCesfZ/8frPqCpp435m9I4xi01NucErhRDuMqVhfPlWlVRtdO4EHqWIx30xM"
    b"byYqjN7ciI6SHi/2XaH1lpOkZDIgVUQfV8lnts098ukux0wWbvhzvE5AI37RZOxxyNE5MKufRsDt"
    b"JItZpTIFsDpPsG/4EiyV2ZAxBVG9wgFV0rj1RFvki2I6FCENy7jDjYwEbloVmMEMlaN+q+5WiI+/"
    b"q8v3wymgG8PbuvxZSNYDjEzza4zyKt9Y3n0cmCrpcLgDrMvf+4TZF/gcc+yq3w8Ahsg4qp+cr3pL"
    b"qm1RexEKXVH0WlYjVWDumlQV17GohHYeigTPB2MPUrdgXQWi1i3vHwW2hpVjqBfXclfqpL83VXBa"
    b"IAECBZtA1MLjbbl6eWc9So1XYV2Glsf5FGbPRCwaIekTkl9JaHtLGqGtyG33LMzipb5WifwqtquB"
    b"Y9eIYBGMzRsKWAwS9z0viKysgZkVoLCMYkyeoTJ/OYw8irCxg38nc68+QS0fiiio7JMayKg62TmF"
    b"pfgqh+X/ArYv4EiqiSNDP7hL+sEwnUOBh6chnFAYwIh/YLwwE/YRh+XH9smT01rfh8RPR+yZ1EiO"
    b"2Fa8o2gObixOZAqs3Ysy0m2DHLbHG0Nme2t4KkgHh8SmDch38GlqNRGe9JpGGcAF9gxLwc9jstVp"
    b"Vby4KJJLBKEfAgA40eYFiV1UkjOlospOcFineGvOfwl4xTFnuHzw1mLV8kFTK2WmpNeRdmNQsz6i"
    b"KceGx6LAMBDTbybuKLMnCnsjalZK6Sr/MJ/L1WAB8HVhJIl1gGdROjdBYSIC9aICieZqKxKIB2le"
    b"oA2xQu8qL/F4i+ldPnvmjRScYTIh4bXwpWI0bBdUGWKltAGxProDFGsBzhaBLQshxvYwWpdLyahW"
    b"VANVwkdztSCaaEGZlfClZlTRXSowrsUiVEFxZrznaSoEfOPb+SoyrqnHQ5N6qAreV/PXydx9B6HK"
    b"fm8WReo2T25meTLFoRuUQFFd2IK1VohR5C6M7kpqcl7PA0HAsv4Ezr1P73EjtK4nMJfrnsp4l3hU"
    b"4eppQO4QZDQEWBD+X0hwXTLUe27FWI0BjQzToDkcGqwoYN3ofLrscGcZW1S0TjHXdL9ub4fyHiWJ"
    b"Ye/CuYoTuwV43eIhzrYANfBTYWWLO86PMTmLPE8etWoCuUnCfSZQ9GCZTk0qPuAo1wY3NF3qyIIJ"
    b"g3O/MYUwT5E2SgoXRRrR3CUVNHu+qFiJghv5Ye0ExupVM+LovEIPl0wBPWisOUVEKpQfTgNMNcyU"
    b"dC9o3rRpFEenYUaEGCRsQ2+xEt3XMU83Ou9A98vrau4+8XngKY1z47yHMW8N1RSMPMNiIB7ACVno"
    b"E3IryE5gfRX4CpXNzcV8y4hUPFqGKjy9XuPu/sWeR3bh5jIHCeHulZ51rfQQK5PuvvazTGZO0LCq"
    b"gKOtG9R0jzG7pkBOqtNxIfxatjxkQe3MIJK55LiyBRJGfHGNUci2Mpr1QizCkZ5YeU4ZFHEyf3l+"
    b"x4bqnFxjfwk9hiSKqqdR5doKnc06ps66GvvW6UM24SVj03MRDsf8VvJtI9lyXiX0Yvb2xbnCMD/9"
    b"t8yZxVrUhyThHFbjxNhqgmunyTgqi0kztK6eD3MOcAuWAK1pmjlfT9C5BY8l2qSqXOThtZ60v3m+"
    b"PRxjOFdJAKwZr7aGYYFHElmnWFkFzD9pProKBvwQUiP6scgXd5Hs4a5rTZXqwlUvLBw1fgtJT48f"
    b"B8xXGEpT6dQpQ1lX4HT9DeeCh5SGlM/6WUfdtceafXgJ36wAThF44zvG89A1nmR2iTzm1TU/bmzB"
    b"hNsBIZ2zeVQ5pP1qVrpCnBii3bLI0TwIA7l64YXubBk1Rr5V4dgNiEiIve2BGpt2ZQ84LwC1ltAV"
    b"cc7TCjfifhk9sv2POe0yu4NHk8SW2GqEIL1t9CJ7UdzMAZcgz34LY1Allw7OYEJ1Hi1g2PyUBwpO"
    b"Yy9JqAxLrsqVSeLc3zWw1dErdeLzFmik0AUxRqNZSnGYEfZVT8ZWSz/JZN8AQZlafyChsjouCJOV"
    b"psm1iyNotNW0RuL0WVGcNJvB+GFxKQXeYjYbtSfmiZqYWz0x0O/XrLrKp5Gox8NJOEpABqVpmqUX"
    b"7Di9FvNz/Sn9WeygndMxCf6iSr6/hdyKcPxq3Q04lIDNiXQPWa1t1dktj6ZU9BQxLvs5hsFt6U/C"
    b"LkayEh2nQK+ycwJW5olKdd89pX3ivbuDMPSc+1+uQGvr62UrWwCp645d76wd9sM2SXYc/3AUdYLN"
    b"v0girI3MivGyZcOZ2aojYDLK8ktekFGoqTiqI34jLCawawCK57A6u9UWUvkmMPpKhzlvu0XlAOhV"
    b"WpHgtCWrhuXFuM4wNFmv+cpuLTHa8wTDEoRXLJmyAuQHluFGpbQLBrwCSl5pSbELQmROMIZBmMUN"
    b"FZ8hx/TIVR2E/4t0hnFXd7SjWxHvjopnmXLlk95tKYAVQPFcx6eS6lIkV/IcLfXCMMRuSG4vglAz"
    b"rbyKkVCZZQazq4xkxoZc4uMDcEEEkkhmsW3ubkq+jTdiLnjOiqKKguNb6Y64LN9QGHEl3vuDfXEf"
    b"8OHVu5cHLzw4Aaz5EJW4aqjr2tFDKf/ZgTmqfnPmecWWNEx+rFIftWLwf3QPXOuuxPjNDhSWmNLk"
    b"j/VTaKhoRJWFvLNRc0ep6ovCmFp1KAFGMsJSd+HWqhuchjdCtoFU8zinIXypISi7Re97oJwDyqTj"
    b"VC3921vvw/67B8evjh68P3734Gjv53cvubBsVSS4zDtkj7E7ObLkGEMlIGgG9WoSH77pHb57iEEJ"
    b"8f90Dp+56PueC8A5W1DKUv6gQb9Oo01jpfAVQIFdxPIZrFwNFHYRpuSaPUeTThQuZALOX/F8gFIY"
    b"dV2mw5Yr5H1J2F7OeEfbWuLuIanFbvF+MFAZjG8VMQWaeMKPoDbp5W4P3FC1sYsVI4MbHl2hV0MJ"
    b"YhCEuWsfkrym76iaMh9uY9NaYYK0g+tqlagVhEmcq9W9uZkTZYcawklXi9uXKH5FLw/3zesx47h8"
    b"YjLFHWJVMJoYrU6wVfE55J9o5hDH5BEf0/fwFF92dawhvO59f/xXPrA2ebSIBwY6UFEpuLybhFTn"
    b"O5dKtlmSa2bRpx8XK9Cdr6KSCpeQUs6n6Gxzp7c1TLnqwrWc+wg4aNjzW4vZHPLJs3Dq1bpuehWO"
    b"P8qgXglE62LKFrWJvTdvT+B5rC0t5/oSfk4XbHNLYXkeHx/uHeH1msLG3LbTfsLNtF1FecHvHw3+"
    b"2FX4ERXeHj5mu5KPztqU4Ye0Kki1jY8DZpaKaTWjw1mWf8uGQY6Eu+VSdiw0GhhyA+rBl6fgz12H"
    b"Z4GGuZ5xUvKwCVO0ilW8yfMBEeXrOd5hxdz3n+dA+vXia2ftkOcFRiWWkmw142qwnUaXFOupOy8I"
    b"MMOO2NmQIDKNQw6RQu5iiDMFz+dji2fDUUm5lDDhyvwWi/u6dOlh3LN9XZIqhl76NXZMIHVB5FyK"
    b"18tZc2E374nJx5ikwrp7Yu+5uLB3zbWFXdWz3+4ovVBMy21FD7WqbNLF9Jhos3xy3Oy006PDIN++"
    b"cYtcOJ05gCaWb5I3vniokDxPAvHurwuV0PNtuifn05e2cGJfoqeNRneoUX1rD6Tlugpt43Og2cKV"
    b"paMDnHsm6UM3L2yOmi4rA5ceyO4jk4og1StGWoZmp7SaoHv+NNN6oiXc2NtH5pNcozbMC9nxCWdq"
    b"yakKdtn3XHcsckkrVBmfnB3sYCPtycFy8EOUOY3WakgXuKMRcbsnSjR62SNvJN6uJjRVw8NAHY3O"
    b"VbxVtRwSBMHJBGstlSLcmkhYWx5O1zdWkqZK/k64w+2U+NTymn7IQXAo5jNXzCSh1vscE1JywKuP"
    b"hrloVZWW4rlxQMxEXMj5IIA4egriIc/WKBpX0Q4mCswPd54Q7ofYDPCj+KeKB72BUtNdGhELOrQ1"
    b"lnKgcTuXmbdzUhbX5iuo3xV3j5GRwAMriAQVu0AmqPAIkVz9eOFnOiqri6mxPQAgQcadqxjeT2k2"
    b"dWnhVmo9bBLAJzct39MLWsxVHYiNRO9VFeEOqgf12dahcHb1wmjXQXlw/3GVZtPYaNigQaR6BuJo"
    b"KJwbt2tU+G1n1xqkE9bpOh2U+jDeyVKuVq54FZ8/c0vbqGWtEGasOubWUrvKtkokWMZWj/hhmJY/"
    b"08PE++9aLvW8j5aZKLc1s1gF4QBb3bHQK3Oh4+UPrknpTQpbN6anhjARmP1ir/KHgW5AvrdWh/+K"
    b"/87fgJjo7i6/wIzmX9BNEB8dArkBIy6QGTO6auDXS26wLD+PyDSZ/DbELnWwycJmmZSbobBs5ppO"
    b"fb2N6CCHYBVnzf4i3eYeEB7jrkvUS+/N9ZKe+Ox7/MnzpSobZXXM+KuVqhb0yEKybSVAjUBaS+2Y"
    b"5crVcWIIM+nimu83yuWPQEv2QQ5cmoKrwRuin0gimU8bzl/nv5ixRca+MVppM67fRoun5tDCB2KS"
    b"/vGAfI//0X8Q8qtPHizFrBiQzIPZpOURmywKJqKErHgU2eqLHFhnVwhHcGoAmgKjPztBEDktw43C"
    b"0rV6bz6fsb+w85/SStcQWN0QFvLd3XDWAVhBeYq/rVp+yNCCd/pulmTqZQcj8Ap6XC6KAteCJPLm"
    b"A0YGpGHJHrUWaSlfcjWXa815Yrle9lmVpLMyytBy9DrPjmCjRf8RwrQA+11JgjUNp3BCn8/Yq/wy"
    b"upIff0mKDB94iBZkSP6vWuulpesAPxDFzEVogn4Dy+Cm345vD8l0gS1oQLAEWsZ/9jAVX4Gkd9J5"
    b"ONopBtSgF8wF39Ar2IxBW/hGC9li1toHXnkqtypF306sdYrS4zXQwJ7cIpSMMJB6qStFU13eYP+f"
    b"pcrv8QECWFjIoSMi45uQvE4w8kzC//Kh/2jFONTpxoPCZrKNKTNHPB5gJjleUW403Xjf2cx1v+ws"
    b"IVzvK4vhMfG3En9T8Vf0FiVE+svrMi1tJYmh1XEAy+Bg1eoQ5IZmUvz+xvXRMZWiO+25PGjN5UHH"
    b"XB50TtpBe9J4kvkSg5luv/Fgl3DNkcizXm4wc+w3GxrDMNW9OsOI+dRO5l4TjTXgnntzzgUNpSn/"
    b"Rc0tP+BpavnP33ZmeaPtif2lNbG/9F1Rs8y8ViAsK9OI42WmN0KEWW01goOZec7YXCZAewXydDMU"
    b"V8c2Xbk9pTU7au2z1mGy4RmPHCl2ztNP9SpzDJ415sxXxL/wwcF5zCZ90cjtLZuEIGOgH+BklpTl"
    b"Mi3hDEWHQNmwkkyNNhSb2zre67T8QUyyUYEO8Y1CkgBArxCVJo48XzL2GxvcGUpWIspYgdExar/2"
    b"wGPj6jmvDpYdP23kOWr64FlggpQpOO2Gh2E2uU95efj2aHPTKMQ3iSgT1OaAlNHFvG8f9PKzNofa"
    b"DS2OQ5AhAJ8G19LCqYFBjVVgblbUSF5thuMiMGTPnGjTIgWWMN0YoUgXDmUhamaDL7o2/4SvEDt5"
    b"rVWcli1DFTH8wFdbff7MdTtkUkckSmTDQJjhz4kBw1OLV4aWPArZLCfLNrXFtAJGTNdHMQll9N96"
    b"8J8UAL5btiaiJgApEGgAtQA4AK0wmU0fMr2xEzVMa4vKEs29p4u0d6Us41pfupx79dUfa/5W+GIC"
    b"0pd8iZA6H7vohBLU8IHn9F0y9UL4c5Wj5RT8yKfeqd7ZWiJEhRaIxvJJiBY1iE+0qKQEFbmLT0P3"
    b"Eo0ffR86F3z8ZCd0bnL0P6/rEF+MjJ9jVKsH/3myt/138cDhlj+OTnpn26dmWvDH7x6IBw+B5F7F"
    b"9IrUCjdEYZsfskW81AGQo5MlhlIGwlQtsgj/6c/6l3l+OSPno2j4/e5gx6tDDnXi4fqM2GJ70Mdf"
    b"/TlsiH+WBLn78MlTQA0BLMougFMVnC7yeJ4XTgpGvo/JTKbNvfo0tIIOwZTTKtnGCEPQH3ahT5Qe"
    b"w+vzKXATyyzP57BW6vNZfn6c7xVFcvPDQnA4SgeIBV+m+Hwj3r1r75U8w2tVS/kgozMAefblb3RY"
    b"hoMtINsbqGKvtNrB279z2PDFDcd+oxtSoYGd+JBm1VPK9ZUapxV624i3XZ1kp/HOo0eb5HUClGjK"
    b"9jBKg76bO6dWaimI65P1qqrmgEWgreh8qn2XJ/nM2mf4CmewhG3AxG++Xl+8evth/+xPb4+OY29g"
    b"TKpnZr97+/44fvhwl6dNrhbZJ2MjLYUOaBhOxA8RU0IwCjyWVMwWPFWKvGzaONCNTLl5OIwiehxm"
    b"juZQJf+9yOgrtTZ5+6XE0NAzQZ0ukhZ+IcLIs1tEMqQDgALeRhvDEGPs4F++HH6ANYlfwNamPFDJ"
    b"kHRXwCTzSpVSik4dWgOjjqPHZwt6rkM1BwcOlSKPpGa4IN87e3dw8P7PR8cHR8deuMwLWPdAgilS"
    b"StXHbkL5EFc271q8sQHbgUPxavt8DORU6eHuQj2JHle8QQjBk0Ufe44TkJQz8gRc84Ssajml9H4r"
    b"uUrHbCbe8CFid5x/YjDyq7oRNBVDqbJrg/eEZdKb5Zev2GfASusZNp5elyaQ8aYVT4lZDT/FRrGz"
    b"nse7ItLNGVly+7shgdVfkiLrKLFjl9gRJRiFrXIXGdpFhqIIRSC4fNl6jIub7LNagNNLZfpSzsOF"
    b"9eejqOdR+qkd4TQL8LbCiPlB4bTI65Wdxp7vbdFtBr8BD3riU1xdBSMGGBkjecnhOBFYy4KI4Rsm"
    b"Mplw4/1l7/2bwzc/eqGCQOMaAcKR4R28f//2vYBwMQd6itCAmZ2h/pldyidndaiGq6R8+yWTkZhC"
    b"dhN7/9Mz4uq+wBNEf36W11zUyEUmHzmaiPjRFf/MAUEYCg52tS57zsuGRZhyLb7MMhiXdrCy4yvW"
    b"m4kIO+rp3qSnyvIYwSWPrfIZ48uBlAUthHnMbsbsZquKKuMxePaZQk7kp2PzA0Zifccn5ldYnkYW"
    b"NF1NYnQPq0wZqs8X+SKr4JAKjTcs2DE/dwdxvL1tQ+q2+TBeRCKWlK6/OjVqOlKzbJUKzTSqGCZf"
    b"zDingxi544URx9bKFKFIeF3AMp2dEeDZGYYJvwEBAD2Ij4y1Qw1h5Abr9CA6E3JDOyTpOoih0THl"
    b"BkBbDPUeUmIVUAG75A8RIs7UdTDMqLzwGgaR9mES4wCKZizmo5vr83xWjjP5au8qKDTzwECg1gDl"
    b"urNNbnCAlVhcLKLXmoyOw0zRQSZlM46EDFaYTMDfnLRgTUU8oJeThIVQGXMeKIWxPUvJ9ro8KU7J"
    b"8hrKqYicHT3ls36/3qrXfLBj42Ek+xINGo2w67Rq3HfjZg5L3kquW+FHudlOfqoFSgROwkk4jxsg"
    b"4bT1whPWNEfkLYXafU7ExXqVUAXgYiGCCrOCcAP9erlyvjeMlPncRcYX1lwSrQAgSWPX21kBFRpw"
    b"uyvhUMckIR/eAYm+dRL20Z2wSNYk9OM1oGFmAL7GpTaJh2Ei1tZ0exiMJs+mowmsruRksj08NaLx"
    b"TE5HVCWPBqPrTOAgnpWMpnoWXsXSEHHEq4duPbuiGuVEQU2r5woBuqZLZIqB4YecLUPFChPWCRfa"
    b"kLurIG3FLUzaSliMYGrrDnG1JwExC000zwDNM0LzzEbzDNAsWhGYNptJ1N3lRnMXNow5tM0JnrAU"
    b"vIfvTKDXrZITtmbZQbOsPXstKsApQLqKAqSngcFi8nyZAmcjtZ5y5lYc6Y3i3KQLSAH+s0FRn4H7"
    b"2uDcxu0tsNOKD9mgQLS61hGtXElycyC5CZqBT2JFZvJnk1EO8+QLdsCoHxN0E/hltIJxwwQ/gDRu"
    b"lEgHlUbnY7wVVpkJ+qElke5gbaDGifm92exV92mkGJyxb9L6BqUHeUI0WMFh56/JQfApaS6li4t4"
    b"xfqwgZPpVC2cxoLkgGiFwkCOucFPugQ4gKOmInDkXdkRl14+uV3uULqLKYirBywY95v2rvkTIqz2"
    b"l6iGf+8uKoTawwztdZMqRXnPE2LvdmqkYs37aamipkJ7xhfmHmYkkh3u4ysw9HM7NTN+Qt5a5nxi"
    b"N5j1hlVf8uJT7GX8B6ahDPIhSz4n6YzET1IDbS90CgIdlTMLpixnLRBSahEXjW/e4Mc244+AQGY+"
    b"+cQqmUkfzcwXKHlOVS4JojQeo2EcrNGsGDBXBcQeSPJo6Kbm4J17Dozb1pdQEbaZ6aTtC0rDerXI"
    b"L/umA2rq/onGvnQ0lldv5yz7G6uglbzaxpDK2zes4iuHRLXj/If0EhcQtzms8nz7PL3UNR90LCVS"
    b"AMDqob9YH0/5cPzyqUzdXlQXTzGLHrzw/lliHFbsVAZzWCRfdCNf3Y2ILqre3b0sxRyrySXUAebw"
    b"j25u393cn1hSVOcgHMTenw723h//cLB3TJWoME7ei703+4f7e8cHmM4fDfPevnx58B6/xVOe3t6b"
    b"o7/wFEQ+ALw7eGN0TgizsFWmxwlqL7zD/e3jvZ84kLl/Dt/8vPcKMn86+BtmvWLJZ+jDq4O9n6n9"
    b"g6/ztICEg7++O3x/IIfHzbIOY2/Yf9R/5I2EovS10pWyM4vqLEHCL0Qkb04QUyBOIsjNR6GrPzsH"
    b"VuFDMas3IfO7Jas3K1K8QHb9cSSOPr53pIrCnBoZf1iAEP2FfcO3np9teZvS8MbbYocy5rlZAwhk"
    b"oVkFUFOxKHREXdJXVaZHCyMNF8z4NekgPE4leqJkTzzPNaUIEUInBViQ0GIqeqVVCjFPtYpjqKZu"
    b"obTgs69yyWJ9zf7SIoz1k/Dm8FDolH0k+B7f4X2Mzivj6c5Yki3mvhs9g9Dqh7lNgnZfkBDQvYG7"
    b"LwIalst/LNiCTcWoSt9AJe8mBWnXQeqv2HQxY2oj8ciernTR7pfyHSrK02vYNyWr8Ee+qHyjZ9gJ"
    b"o5wYyRxKHQJbUsAMYQM20FKzY19K3IO+8sQn9luOATY22QRhKPgrWTzsnbNJQrpEcyY8sbHihpeU"
    b"CL65r6lHLd6dl9jG6n22Ake16uXSuqBWG2qoX0bgVeqA+LVzlsSl+Anq9aicWLslAWpNH8yffBvC"
    b"gkB2kQUB15kzeqC1FsPQr0mYa0bGXNWIT6cWyh2NqAfGeYBnIyy8UUSuZ6KdodqSci8Go86pFtaw"
    b"rRekHJODm59rnldthzv2H0yjglja8+e7dl8HNXMSDTJ9tXJEf63EmMuWQYj9KOReam00W4NqKDbi"
    b"R2xX3gAF7X0mr1TchKe9gKyDI/bZ2PtSltGDB14EP/BvgMFSKKhQsSWu/8af8NzbSutaHFtv+fFk"
    b"3n/IezQxdMxuXJHQqpCaWhWw134StwqbAMKbm33qi2eOGdaO5jvySEuEHV55nJsdkmCoNAE2v0gv"
    b"gf0B3Kro3HZDaKqp7mE2mLp6qemh8/YVTtYHdpPNUBDPYF9lKd6Xpr9YMKlcCdfAUXDDLq7A4LsI"
    b"oKYzdrT/ztfcCsYXrt3oUycg2UShoVU7/rGih+5bqhb2ixyfeyz6OY9k2OeB+/UFpiD21WKuJD+6"
    b"3q7bieb8NyY4bGHb+Hk4xbflHbOOiO/o70iigneAzAnzonf44qCnwjaWffIxzDPzpbCY+4d2PENn"
    b"JMuD/6Mw/5s2Kqf2kM+KPprP2gVh2jdpmDqHFLcaCi/8yHhZzqiAx3ItQhM/qBOelhV6CtObcHxI"
    b"zqcY6IgWyi/meB1D2AkLeSaSaGwDojEghwrpqCXjW91kr8rRqSpobVc8GfitCXvXlqpCz0jC1110"
    b"SVHjliea7XvtygV5NQ0cBRtwx0g41K8YSVPsC70Xjp5L7nCtnltC0qr+86mdYjNmmR62fMVMFMK8"
    b"X9FgLAzJ91YwMnhjN9ByqWvX0Kkr1IEXvH2kTo4FVYfuvYjMeE8+aMM3ovHEDd+HoqDaYnYZFdRW"
    b"pIxS8cSVomZhFnSR3qKzYzxeeo8fDqJn5ALr7lMDXHWKJ9C7SWXs6tmobJ9d6sDiBqjHOaUbBYsQ"
    b"n1LQHIsi+ZiCI1jMezZNF6vPQXXlUbD6yOV8nuTO7jieieNp09RVFKk18QrdfPEJhlBuZO7xbQXE"
    b"h9MDrTRa45ga7zXRFXi8sVFYr1IZlZoZQehXt7dZYNo2JOVNNumZB/VyHeyFVfcZpYxG4uRLkkJd"
    b"ZkT81lFsnMDyfeFgZJ34uOWxqIu+yNLAPpABJJrQ4Quz8oZamQivVxCfnp7O43WAOWgA+OTPOeKo"
    b"5XgdbzBgLCMt96Ndh50PQn8WfoSKpT1iA/X1R7kFl/RAiYh97mIfrCN0Jf9xzaqEbIOaUDKjdrGu"
    b"encj4elYLyPoKMh7RUjcIlBgwTVKmyPNaIYlK4iO8dD1iD3jG4i0m7Gg1aSYioIzCi7EBdq8xwOR"
    b"jL8RSAdc1OOnM5KSUs4JX2s9RHIP7ey5P8CXIkcDf9xFUe/Tn5LPjBvUvxXvRlB8BvPofC80sagw"
    b"kfNutdZcIGHPo0fOdG/vUZ+xwXg9tbmxhQ/Fv29nywZa+5Y/ovH/+sYNO5YwR5tmjH+zjV2vtRt+"
    b"i/X6a5arWB32gtWyIVcBS4HO8WpTJWOf37Ggi7vFKZhYEiwF0zM1n2qrzCWSOZ/Pwsc7pdyEa6Ro"
    b"AkSopO6tXiRCFuYeGbw1LUTLHabRXdxr9lpddmHdeChac2CNrIg/0KYQshr3zXemfN2/j3vTaVO6"
    b"XI0hY6l1ifNro6QxKomNLp2KeABKdh2gesTLgaxY5NeCSQaxGMPG11g/dtmQUGB6N6q+rFzdvF9L"
    b"i8K/5YtC+lf0pjkr/1BJ59q2NuO/y3r6vcPLLC9I8hoxZMV5330dvzCj+IWygJ/hKIN6FSdOYzUH"
    b"2h4cXe+a8hdMmU1/iOapRjBcnKXka81gzJSK7VXnzZAxuaKP0h6TDnPcqcatg7x1o8v1Pf8j7sCP"
    b"9Fa7bGlPtUQVLBt6SGAXRKgDfRaNuTqyCiJfKiaFYRvUCMy7uuHnHSFOSQ/tn3por8gCODfV7PLx"
    b"Skhrq0SbilCG9/Pit1j8yv5TPM6RhbpCdV8lGbvY4PFk937Q3fsndQ+7b/huCWmuvpSnoJjdlvmy"
    b"yiLQwvA8bMKaeXWHRCtXiyH2yKEbSdYtkly++y/+e4uawOrsTSfm6i0XkwmcLh+t1fMlnc1I5fE2"
    b"47TTk5c9dqNcI752qySXEZn7qGdSckfSHN3cOA3BnNxMuUiur+JMLAJqaKWIYWjYmpM8cStjhuYm"
    b"3sKI9z9SejS6BOFWYYpdEY9gSyuBvDDUuVXIeSpr5Q1M8y5TI9hVkz4tMkPB2HzP7ZobbH/8kBUg"
    b"gV9msGrURQytXDxIak6fEcnyXJGHSZ1Iz2KMfWdcJBnrt3lNx03EiROSZDGZkXwNWyctq5LrptKy"
    b"16Cq/d5ewXo3+ULwPDiNQEFBvOhVX9IJGxvvc2T6FszoCi558SinyfaaO97Ki21QOSUGsps3GUt5"
    b"PSerOxPrIRQXCpF6/1udt2f0Zpq452st+UDc2dkrL5N3XmJ5NC67dA/VTZXR6eatl86KuQV1G3HG"
    b"bZW1UXS6HI5sUA+PW1Y1LhIaSDAbFqgTCi+FSHlv47uS7fIsU8OWhNvcz9x0JAi6Twj+4cCDq+2w"
    b"NWc2mJlze8t+6B/un717f/Dy8K9b7ML0eXFOCJ68b02Umf2RSsFVK1IuvFbhUF9rkfNQXZt9i73r"
    b"yZkyNfmwPDtfpLPpe/avBfdStG7s1OYhR7Uxd1DzIvrrhUt8MwyEMooJhaJadRWlGAE/Kmu7gjDn"
    b"rnTvXyGvUdXRgwffLbMayE5Rf7dM4X9l/YCYEHXLlEOjSTG5EiH/8elsryq9EMrv47VMln+B4+C7"
    b"peVNibyVq6AwWQFSfxiEFwwJeN6/KthFuBRRkYt3+Syd3ET2uO3MWmoEoYtFyj4zDIe2lHI/i025"
    b"xMKql0759ffOQESvrJJqUQqfEs62faQ//d4RZaFMJKAMnMChg8EEbPsXk8+TPUMSerhP4hnvmueN"
    b"qDHvgacMFOQgcd7kgpNpOLPY0wvDqRDvv2Kvd3hBtBqjy3P1T9L7iFV8RO73Bnn1ks0utrEGyEfu"
    b"nJvyhJj5ByDqyazMexnjsgZWw2NKJMDVJ9esh3X1vlyxjEvC/DTA1YNVobZE+N+8yBezKcWmQEYq"
    b"yWDA/EDD+w9uB9T3trQYh54Ie7MZ1lKuOW14HJbOmcMT8eGAB1SSSTamlduIidK4gdKxd4jsYg6y"
    b"0iz9RIfgH+AsXNB9FN3jzPKFtGrq90ASoqA57BpktV4Fe/1/aC9PxCbLUGnIBSwcr7zeoGnZe3fY"
    b"g83Zh/2LFckZEGU+0pPT3GAAGrv5iMf1iunEogtxad27gIkCAtH35OTAsFBSy/7Ah6dG18PXaaF/"
    b"xXVKKgusBTtKXS5hCst+jyZt3a2h36pFm0XfkoNpFro3iG6X2EXnsjL65l5bLtFNTrkh3by8U3xA"
    b"rv5/Fy5fch8mz8+tx5xsvmndt0a7qgDdkpN93u8mPfAf3DSKjfsXs0V51bZk4prIszOsAech4lpJ"
    b"wWDUymrst2DHfjv+ysCerMyxOjRn557ErvymdZO5Fr+JSeNGaiBgbAxtwRdLjbVFIakbItvMTGg6"
    b"vhhW09bluwhahDVxqlle0bbm3mhEEnEnf0SAjz3yKuidM0hmZGGI1EHaSMGJY+kBHTLieqKhecw4"
    b"BUQhbFZc894lF66sRkuH1d3SodctHeK1PnXG0yKiZ+yqej0We23e+aXJO1/JHUO3YnY5Srq9bdUu"
    b"/My1Z7xVSt2mrcOGr+C5nRLg7e3SYrj1NZ7VJ+LDX5p8+BT48BCSXu/99eyHD6jfPtg/23v99sOb"
    b"4/jp7tOnjwdPJZv+Rh8fL+n44CEkMMRwU2ukc1acJnxDdua3978ZWCBBJzLejNeGTKZTUkwqfzrD"
    b"IyB+zvvIFyu2qXdTUIuus+mRMF/1zRHBnsRQZZQCvJuACRSt4VDSUDVsIiO2oEQYj9qoSRsiI1Gw"
    b"gh61sSE6uneNnkjP3XMYOKYFBoHHqtt82gCRBvTQPRGSBI7IR4MgFMGOWj0SFr/GDUhDi45HZ+Q8"
    b"OzlfRAy3oH14LtsYFP02z1LoinYENDtqI5LHv3Uh3zD9tWcHH0RoznNzmtV78mtMcxuXwW/MB/Dm"
    b"DENa3Z+BOPwkB7JGGJfV1bXXimIyf9FU4s1SjdBsXzso8Lgv5KC2rGvHjlyS7QOr5TGXUtCcuOpr"
    b"dJD/uMCawAnF+0QkjTUWxdCNI1w09wI7gTeVBpvJneWqoLZgjMNWN688xo3BnFSnQI+p6+hGidsz"
    b"ApzlVYJmFvS35m7vCHPC+tlpO8gPd0TBW2MKlhC6WokzAKD6aMgEGixFdARXAbHQ20GTB5Zys8eC"
    b"agsqPL+pGH9Jb6TjIRm9rDB+2cDyDoCidAPrV+i8XeAbUUYt6mViMXa5dlfMfF1rBkyYNlCUallV"
    b"zwg58g4DJJfM4NvOMAANrI9oAwPFGV15bkQeKmQEotfHH4wlQxXQ1JdYg5FhnRGZMtHSDSq8CrMF"
    b"IuBrtO5wgTA6UdlbXbRfCX8WAdQwdzabsIJ7ow77LonmuLjht9PZlG4QOSmre1RbCdQCZTXT7YOR"
    b"b3STLStMtkxJQ7xntKTERZhlVhSzA+Ei6KYWkt58Z9KblSTEFACEO2xgLi4HbtlatLLVb/RYVB38"
    b"ee0OGvPG3dFE0Ct8yqkQf5HdcFFAaVKoiV97LUlTXyela24yDpTxtvlf3h/TNybgZMxY2KhaWrWe"
    b"LcHJdCkNvdeS+c/z3nnKdUbojWPY3bq337dMEVYcmmOkhXgMU3XAv0MT+SpznxmZChMNp6FQT6Hh"
    b"XKgWxI/NS+Z02uSf02nNb5+Jy29fQFNyvfKCGjO5TVMzm6cSgGEYq4zPHFFvJNU4AanqVFp8nRmF"
    b"A0ankVIRU+VTBhjJb1hrdCqDgxmW4y1II68+413imj/L/UQ7lrDXvuvSIGxrQRtJeH0QtlXSjaRP"
    b"7KYJZDoWahU5nq3auVP7cDbF95pbeWuPNQ2anOfoZvve9EYPrRKmz2aoeXiXM5pldiP86kPvFeCh"
    b"4egg9YpS/FJ1kWumapou3jvbdA5Auid8wHDWsxu6J+cOkxjIWVzSKj+Fmlx5tGyo9ZrobSz2nzDZ"
    b"k/7I1sSQv7Hi4Na4VKdH4MtiIjUolVaeoHZHXnElZcVXoNQmpNM79JWhAGuqU7hRTBNXOi4B8HbX"
    b"5WWzlHACb5azwg6EHw/3e54MmzqtPURxhcU+tqpT7uPNGnVO+BG19j8d/E3VaW4IXrsI3dCqn3zQ"
    b"o5bL0gyTlbqH9Dt4Dfex4buMmn6/UIma4PQ5k+sXLaSSj3vUXvSNwBHhR61jF/UqqzDek0bFZLob"
    b"qac6bL2PCnxsOUxwV9WKP6snBFZlFUH1KY9yOuzIQgH3haFEPNyP+JUkygINrw317jASvh98fiqF"
    b"S8sIlYVSRRRl2prcsC2CQ1VGu0SjM2sAtrkWGkN4GI2FwsXQwY8d2tCG5i5jDD3n18kMDR3gl0ly"
    b"uB0Ir0qa0PMhSf6Xn9ysKE8y+xw//bYhC4N36SZpG7c3mtB6tMxQoq2PMpVFiLNkLF7eNM9AD+q2"
    b"KQYPaC/1pkszeloD06hjVgsqMfDd2mfUPiCc/AQ10u1VXbpXdRqMSgwmZNuRjptGJCyIUimIAWOm"
    b"0lPYFlr7a3c56y0c2uCIW37Wdj0Gyw5bSyERQzZC2/IMsrJKinl/cqptHYzMS8wM1EPLjYmxDBIc"
    b"5ZRb6th3wAhihcxogE+PyyPVtGyKl/ZC9MSM82Cbddg6ZuneXWNxwmMTGLRMX1irCAU3BEguE9bR"
    b"rqyiCBrmsYePTkz51WvTjc+4flSXwdJeXDcJHSik41XYA+pGtlQqSbVIFDfl1/mwHdGioZdWeAtL"
    b"7EiVQimMaSkJt2JNLOpusUIyToOBC9Wt5ALfi9Bjp8tpshCWjI8M06E1Hm1CVDUJEec+wqrhn2xT"
    b"B3pfIatl4EZgPkyztv9D5/Z3mw8rJJokfOJa/Tjnyyuh5URGHjwaqriixJeQuDUg1X1jGHP/oex9"
    b"vDRez/jYV66U4lwVc4vWd5mytMOoHSunGrVfdSu1YbndsNCmMzBq2WpLxuRwKngBBz9kkz0zp0n1"
    b"zLwm0Wvd9jYoX6uscOfENawUB+rNZCCL9BB4RmaRcwpMmoXDoF5BIm3zxNo+fJrqCcdYrOiiPZRe"
    b"LZVXL8M37OxW8GpAGfyPjJI1SKqzBOTUPc4TY+vuW5NEAdQhBvbQ34ZxFNUC63vDsWMU32AJGOOW"
    b"DBYJrQQJ0H5Qq19LM8OMD/Rxn6dxQkubnHhKKRt8dEh6XQGEZO0NKUfdphsBTSyktycL5IbSF5pD"
    b"i9lnK5h9GYtFBbVphv7zdRdEZatXr1i4dl8D7Xpr4sRNp9v3R+l0pDCvIJvINzaxOziK5RLgDOFi"
    b"CaJS+AXZWBtHCA2fHfEMbZVWj0k+NqNmO1D+QFXFrufCDculNpAj7Ekx0exk15DlNaMh67cL8xiV"
    b"PdVf1TfTRMs7VgyFODE1uwF9NM+2w6oHFFOpHc4Zy7S+ipx1rOba2g26n7Xsw95x0VHuq3YX5EGd"
    b"VtI0xAqa0DDt2vgoOqEJyCGaOV4tiuJm3PsLQxs9zh5VBWlT0O8HZHyqQyDTOGDwrSbL+pCbStWS"
    b"iU7mad+2TuxDRRkwps9hQoKgL2515fW5U2PB2nbPgmBTeFLTQcbkp+JlkXyJ2Hchms9F7GfxDELE"
    b"fgmt0ICYoAxIfqldi97eF0a6QbyGK9ehtfVMmkH8wOtk7pAeVBYP26IxEAt16riKWcQoFAAz3lHG"
    b"V6eWU3a+uIwGIRkyW5aZ3KhZJeGrGdzA2XvgkYkz+7G/f/By78Or47OfDv4Wks4ratl989A5mG49"
    b"oBE2rI49/hbCNjck2cbL+O1JkZelSPFCY8qiZW0KJsrasHLNrgorZqSGTWcGI68OXSbCiB/Dqssw"
    b"aBVPO6n3SjARHxoIQpeRsQ+Vb7jsj08Gp636MT2GAlvt5CDsrKidJO7OtofuJrawDVgO6nValxZ7"
    b"HfvosasgguiHXiKXSXDTyNpZzcagidGZfkYCVv51v/GyRCew9PjkjzDYYLQfbm/lUQiEiXPiH/yq"
    b"Eb9MbNGOa4FwAwYlX3AxHkCBA87MmDY1V5JemKzfe1cs3JCeXxBPh1nOofzpUOEeyr1cuQV3xhvX"
    b"z5P4WbBG4yp6rtTsZk2tqzRWNE7RTM40knbTW4ATdkXJLSX7+nS+tolPrB5pEruRf8ZLPE2AUIUL"
    b"OKuABtUy/x15SP5YB34w+m//P5MfMO8="
))

QRIOUS_MIN_JS = zlib.decompress(base64.b64decode(  # generated from qrious-4.0.2.min.js
    b"eNq1XPtz2ziS/n3+CtlX5SJNSEOQFKmHaV+Syz7qnGR2Znbvqlw6FyPBFjcy6SXpeLK2//frrwG+"
    b"9EgmV3u1GYsEgUY/v26AxP54ejT4y89p/lAOPgcjd+QNngfWG3vguTIavNok5SpJi8E7VSxVQY/+"
    b"+NPl4LM/uEyXKivVD6+TUq0GeTb4e/mPQmXLfKXa8e6g+ue/q9/U8n45WuZ3u6NPf/zh6OYhW1Zp"
    b"nlmVUPbTcf7x72pZHcdx9eVe5TcD9dt9XlTlycnxQ7ZSN2mmVsdH9cO7fPWwURf6Z2S6xsqyZ8c1"
    b"2ZaSHn1yon9Hyd3qQl9ayp5VI60DDH6xqnVaioYx4uqhVIOyKlLibF63DyrN8uekGGTzQlUPRbZn"
    b"2g8s0GhZqKRSF1ncu7cqe2aVo/sir3L0jyuRxZl6HJSi25o9bDa2IN5T68gVGc0qspeGDxKA2kpR"
    b"aF7yGOzXDIHr7LZVGRGxipjIxxlNpURNvOW86Zr1unbUoUkP8lFyf7/5orWVFLcPdyqrSvvFFsSm"
    b"JJZyYklkXemsvL0TZe8heUhGzD4sq7zAhKMl+V55Havn59xcU2P5cK+K6zjvyp/CDiK1n27ywmJr"
    b"kDKS2BXr2EpjGpxsNlbDn/Bse7RR2W21nidn9J/j2E9lnF4lizkIEL1sUNrVyclRoYeWIrOfny11"
    b"lS3ikv7YL+3cUMcL5iy7CnoRRW3nVr51Un54zH4qcpKg+iLy+FVRJF86HcoNhQUxruaN8Mfv1ee0"
    b"PG4F11TpXv1WqWwVJ3NMviaF3cRr02h1Qwp6gYFG/yjYvyvBd2qjoA1ygO7tdqcs+bhRq/h1nm9U"
    b"klmp/SKeVkXyOGtngLC3qnqrCcx2vaRLibTYI0zOzPeEHCtVWLbd44YJv+PY/iX9p+pNCqlV3BFM"
    b"pLEa3SerFXn78zMFSfwuqdajm01ONrVIuURh6J2m9o/V6DFdVWvbRMiA+90lv1nksjbP+eHmplTV"
    b"759vnt5YiKKjOLUN0ZTtkukRPTGIGkXUHuay05qzH71d5lwKF3IrVlSPs65CKWCNPkHRsmvtkjT1"
    b"DcxHw5hWT0j2Wh7Xa6NoXsY3tWftWp8VI1KR9ZRTHhC8aNq1jtGm8apxQXr2Js8qmtA69lbHNgdl"
    b"PrpJN5tfqi8bwqsRtajbIqeEIPLR7Sb/mGxebe7XSe8RtxC8uXN1ZhQ7VxTrIJdSa9q0ptRajT4+"
    b"3Nyo4iqtreCoxcmJnvdnCjmrPFVOIcrTFH+NMbYUCF1UPT2or8tGTlSx8edqtKFM9F+YOJaCwJAC"
    b"ruB5XeGSelOC/44OiN1k+cnoQPV00H1kdNAKURPbZ+oO94bfuVEF0Vyr9Hbdk435hns8tMCDIBBP"
    b"ry8/vPnP2ZUrpBRyLORUeL7wIuHTbSjkRHiu8DzhBcILhde9bVom/ZamsdvSbey1LIipzV6mfpld"
    b"SdIAcRQJviB2XH3l8z+6mgqpH/pB/ZCooqfQfHr1UDTT1XjMUtJVoDnB04jl1ITNiInLkoKyVz/V"
    b"vAd6Wj2FdCc1lcDnDvQ/TDDRV5KZoKfhBG0YS7qVmgp0HeirMSuDriLWMNpgALSRYIEeK5k/Pds0"
    b"qmfzWf24lu1VKxvN5RMxdAz144DV4eorryZTMyhZkFBguGYw1CJ5mv2JxFjqJcYuKIMKZJzQHJMO"
    b"valXj63n5UmJcqRFMvSkG6ER1vEjdESzx8qWLDyrENaWxARPOBaBfi7pUsuiL3lKWHfClMboKXUb"
    b"q8vnjlGn45Q9krxdBCwh5DRiax/jKZk4+JxoJwuMO6G3py0HH2KZQFV6rJoplMPKZCdtuk5NV5/F"
    b"8/UlMaY9UkI/nsSldjOm4LcsMGMBd5AQ0Qg2Zt6MnQI2PJiM4JqeIRwaJoiFUGjP8KAPKLnuy8PY"
    b"RzVhPzCBEbDqJbHGViAZAq0SyfJoLkL2VtZayFxE+hK9x3XvhjSm12yw67mhcQXfkI4MsvgczK09"
    b"eJxWomQt1/BSC+j72s1rynAhVzuSZkOHrc/UPGN5jhMoUTPt43lgFOrL1oF8aXpHrDutRviVkZAd"
    b"WZOeGivRtbaPEWCKG6M+GlQbEdA7roX02SvGWkve1AgZAJ/a3jXjbDvZqsevnZTkaFxkiuumfxNR"
    b"kv3N6HBauz+LGoQtN2G3f00/CJrQGk+FNDqX7FXaUyQ7n5bVn7auAkyQjavAa3T/EB6nuweM+Ka7"
    b"CIOW99akTNHwMu10D1reGT5Nf2jVq/tPWm5Irb5n+jM2GicIYGXDjd96I80TRqIxJlQz4esJvMMI"
    b"G+CfYYf6G2EX4g9/fv/q8voPH35+9+rX2ZXvhiHkCJB0PRkhLCYRQFGSRr2xT8jsRRHDwBR4Jcdg"
    b"w40ixKScUIvvR0Q8miJAwvEU0/kRcrl0SRA/DKnd86eINRkBqCbjQEz9KcXaOCKlyekUAnvkv+Mo"
    b"nBKy0/PIn5JgoYu8MIV1iT0fwEswtBCXb//29vKX2dPlTIp3M0/8ZeaLP80ClBjX29n87X//9OH9"
    b"2/e/Ip8D0jlB+9qg2uXGE41XPgQjxn0uRCizRbChh8CaQrk6Nj2o1QXqIERCA+dkTRJIQspxBE+L"
    b"EBshgjECWhE0+xpiJFIlvB+1DhAEuMKxEcG5Tah6bHxMSeZBlwm8cQz56XqsQdNjnYop+OWkLKHJ"
    b"MeMXriaIQGRMoFftMKHLGcKDMsdAGeoAWKSsxRCPWICZyCG8MbIr0gxM64spunk6awDAEMZkafgi"
    b"KqAIHodM7td5g5QHJ/C0GemaWl2obApHDekpl2lwIjCPaIo4klFMgApkGlMCpIldWAcO5Zv4h64n"
    b"wG1SJEKMXAfuNGb8DcGCx8hCSR1oTOYEsQBxDyHI/tAjKZ1cWRK9caRRHU4BX55oAPQ4gABMpGn8"
    b"IG5JaHg16WCMMg8cgNYUnk4CIcWQWsdQHVSKQpEgGvDnAihAA+5ClygJYW+UEeEYtYMkhwnhhjAQ"
    b"6hzpggM4B5cPOtEj6DE1GAbwRQL8ktjwLdIs1A0fRC5HBg7gbmAfTIwBJ/CoiOKAGskPp4weVB+h"
    b"fgsYLxhvYB9AOHAW+YHIAdJd1AFTUx9RJ7gawgXeMkYGgKXhFxIl5zjQtSoSNGkbeEE8ERhdfvjj"
    b"7Ap6QmGDsZAXSWuKSgN+xxNOuG6F9ckCpMZA68TjOgBOBm2DHVjCxBSCBZ7lIgmDNclVjK9jAvLQ"
    b"fL5GaZ+jM4iYLTgTogM+hXiZMsxDrYgpZEhyYX/KKkUoMhgA0jiugJ1caARsjZD9BqqCzeHDcMmJ"
    b"Dj1P4wt8P9LVFqnaZ9CEyjhsWISQ0QbOw740mWr/kgz/iANSM3kE+XLIgA/vZx/32eCwKeaSuuCl"
    b"CAG2BGwpxBPAJdQ4wQAyZkSSXFfAgWhurAykdnU4DQcGWILf6ULEY/TzWIkuQyuixeegjwIGK0Q5"
    b"lDY10BJweMDtAVpSgy7HNIDPY0gBngQaa8jvfI1kiFYOQQQm9MummLDLMYQHgYZxAAdYB+DBT6Zm"
    b"7eLB+xn2Il5RUAPj8IRRgyByzPEER6UZwCCFFHIrox378YTTGuMI4ArxTLdIi3Aqj+t8RmmuIyaM"
    b"1KTViSk8ohp9EFLAAt/gLlYP5Ok0n06liGQELSejkGEOOYFTiI5Nj0MS4Yr8hIgl68ChoHYAMUOm"
    b"y1AvmUFPJzyuPwLOaMBHUjqH8Rir4tWBpbrPSBVwWSBZBcgqgHLkaQ9GpGAA2IDyFLrgrDmGvnyu"
    b"jZDnQqiRQclFsRLR3AGJFLhSY4PvUrxMiGEiQyAIzxpzuolQZIPhKZBhwrgALaKMIR0SM9QHAnze"
    b"t8nZ2YTCLjg2lEafk82Dqrd5seXDOxfXH5NVpsoyvlro3bDrjfqsNvFmpIuPq2rEDfXT+3zzJcvv"
    b"0mTTjmDK9Qx1mypKYiU225nXetP9Ne8o0ch5r9dZ4Nb7dHWT44gsDk6tDk9DaTsyPO33o0ZRErd6"
    b"M+OKxi1EsXWvtu7Tzv0CW/6nVukUtlMMfadP/Sye2uLIys/izLbntuF6lVTJ602+/FTvFV+r5VI3"
    b"pKYhq1tkXG43eXHBW6GJ3jvS+0kycoLT3tx6Mr0HF38eXevXI7xDbiWnid1Ovf1UOfQvtWup6p53"
    b"SflpuytRshIHisUWq+mYZqUqqj+k2FgtrX7rq016m/Fbg/qB2SWcOCA1nNiLWPZG/JrekeX/mNw3"
    b"lAoFEdU74meLuu77c/74Klu9yTcPd9lWh79p3TSt5Zds2aOzzDMiXr1Oq18qkvPOypsnyWb5sCHJ"
    b"f2pcuBmV3N9TAL1dLn/N/4OM25m0UsVGJZ8VW65Vxn2ybOe8SbO0XFt4FXCdrFaNimb9F3mwebMr"
    b"rLVW7wrrXVd+13JVOeWpghLTeOjN0zOPd2PRntITSw09VjE1DD1uoHZZNzl1U9NAD3UTD5u3e72a"
    b"rlGjqliL1VAKDBZbzQ41D3ebhyk1y93e1EwsvQijV6h01n8DIzKtDwYnYSKhAy5iHe/iBjNfEPPF"
    b"WTYviPn1VeoUC2poHyh+8JTeWFRuHcWxVcbXIyq/rtaki2LxPzRksbB5yzsndeREKTeU8qFcxHyx"
    b"+J/rUb2euqKIuctX7ymYkqtsmC/sxVxtSjXQJFIikTo1kRwEckcu5qCTgSCxEcdxeeHODtB0ieJL"
    b"o6vGB3f2obFxj93xPgTV/tS697vkt0sGecuu3avBJ437pKjqbBun5lXjDa3VLJNCbDIoYVvmxOVh"
    b"Et5BEo5sieCayGiBN1/gMbODiasXK3k3VsrHtFquMWCZkDHcGdgqia3yLJ+X5qUGpZ95RvcZAsgp"
    b"T+Tzs4nrEvMqyvnE1vOzVVBiKE/J7rG05x8JNz7Nmaz8Jll5Un4vUW8vUVi3Q1jgxYxPnoO30/SM"
    b"lPe98/gzE+yiM5dIzXygnRLtlGnDuP/SyYODQqZxeX4uT+TXJqRORwQ36ffOOv4ekb+hbys7IY+x"
    b"nSPrSD0TN9/LS/j/wItFLQoj7e/35ehfyU/Dh2NxYP1OfoBzu0B16BV5i3J10dfClbMNPvZOS3eu"
    b"NufvwdUGVeuhDai2CckkZ5erG0a/lOHuqU7aEk+oCp6rc3euhkPK2JTF8eeC/lAm2JdTdGpCp4VT"
    b"2YuZ7jnneb7S3dXdX1oojjU3xMgirntViwVUsFbLT691kb9XdoO0bo2v9YqgzsoGfdfblYr2ovVQ"
    b"buEiWoCMFqVLZ31aLk5OcCU712uUplSztE/0/fPzUTPq+bkdpa/bXv1Rto2vchwqbd97NlfWN6Yk"
    b"MCwyg0+19+dQrgsjGh9fM7sVuTM5dz29fZFTpeA4s/zKcVLY9saJSdnKvpAzkpDm09q6VZXRLj4G"
    b"uTnDSuYmHt5oTpY0y0N8w9w8OPHD2Zkn6A9VHg/n69P13H4YxvQrlo6jixgnXp6SIEGPt328d2X7"
    b"Ju/E9yGOTcAVcJWt2vlrXzUgVpryol6xdD4kMEUrzd5ZI46W66R4k6/Uq4qmZgUVe+q8ONMf/ljN"
    b"lxB7q5t5dR7nQw8rR/yK8nx6clJR5NWrK3yEQo1afcVV4nhQHi58FI3JcDi3VUz3C9P4jGrtRJ2d"
    b"BcJ0V+fnwby48syjSj+iWK/oAV2ROcLgmW6k94KqsJlK1lN5+6bytqeSzVSyP1UzQcDRTlI5/tAq"
    b"z6RrzxOCZxujHSoz/VCYSxmRLVsj77Mi+34v2ucmPc/VGTCMjacW5/EYOYFjSzpoGY5t09XHVyQU"
    b"CVTUeeg8JEljAB5Jd3Kif3UDQRo3oBzWPdDgn3abqMFyTXcyxLNy/PPq+Vl38omRAFcL0+K0LXbD"
    b"oN98IpSSAvSirIt4exytA3C1y83bpAAl+SroqGbSbFM0xaulKB1WtZt2wNay7TN8L0iKxpdRtoiO"
    b"kDBZt92l/S5bDSvpEefc7RmpMsrizaj7hotWG/2tkrMznxYq+jO8LowX2zBuBANbIjs/pyQtT8B2"
    b"eVUM5VA5k9OCM9tZeFHSIr/gtelMX1pKrzztDqVoDyXuWwwjR/GyVBGlsCFNtCJziSXj9pL7a/l6"
    b"dxXURaUmm3eT295lUr3+bMuLZv3ZlhPi5tCSdKce0JpITBgVCMobKhHUabroaGrdf56cpg76WLyc"
    b"f/md/ToMlMxAZ35na2TO48p6860Puaz6/g7PgXKhD/r9LQx89ncubc3Ug95lwyYbFf3DaD6v1YMb"
    b"dV4N/TaeOvsmWDJi243wBbtuaqihPCVkcqa2LmnTYf1JZn9oKJptil57KkKuPnt7Wwfroa+HjFa3"
    b"37M38rWQBGAV18jk7LbwzG2mb0tKz76OGt/WGzxIlSGnSjxMTXRxz6K7s4OG0DQ1DdjZ4aaws7Mj"
    b"ieJ4z85OZjZlxHYzb/jsezDetxPEs9IDkwXSGDtUQU+CequJefR25QgOyhGgqTVSs3H4FQjYxrGo"
    b"hdeG5wgfh/eb0uFktzGCwGSojo0nnS2NZntLRHt2vIjgbrOgZntLnu7m5r49nq7npfs9Lx3KgBmT"
    b"J9WF1Z9z4lTk6VuMhIKabXtmKYLiyglPuShUV6GTnmKE3WBvZ4/1u4KjQYN8Cw2K89CgwcqgAcUC"
    b"tuRl1PP/dv3g6yUn1XGSIulcyovi/JwKBW9GVRCV35RPxsPUyU8tb5hh0652rfoWj6gHCzXbUg+1"
    b"i2bYlpbqdoHBrA6zkt23j4uN9Fs9kOplflBXH4wCzY47lcBECvvFh+CUeKf/uihDWqTkS2kJf9ex"
    b"tZXtnH5+s/9Pq+OdRKSttJsaqMYylprAUqLC8sV+kt7kpKrh27wDyCmOE64HVvlTeZEPhzMrRzVw"
    b"4VIlk1wkaMjio0yEWLHkQ6ociQT1I1mn5KAJdSOZL6iOPdhxGE9sG1ubR+XL4zrdKGtr3yEXic1Y"
    b"33nP8LsgREfXdG/MT74JC4wBk22nmojK/gY+TQzuEMem6fc6XM/LCDpF8z7kOyAz7ViftxJUK52x"
    b"K8l2igp9WykKan7qvlDau9i46lY9enGRYnPE7dbrrWz7pK97VueKN6kqLGmxbYkPxrHDHKtT+kHV"
    b"iZuKCGLHpMcOeMCakVZXc1oyW1Y1xLV9fj6xHYvXXE0ME4H3cuaL9x7++LPAFe+DmXRfbHEffxZ3"
    b"B7//r08fmM/by2LZ+0K84r39v/58ae37Wn5n6PHxv/Kz9NtD52HwNoYHZMmdqusq0l96k+IQRXPa"
    b"pU6ZK3WTPGyqv/F737T7FvjXIslKUvSdLimfqvr+0NGRnWGHj42pCwp1nsyeVZDn0/a7++Rjf7Vr"
    b"jKkPolQXfHKE+uCIGdpehD6AtOVwZtQ3Tivpg1AcAyLL8/v+sZEq/+s9dXuTlOprHFWjTkfLcEWS"
    b"Pe5/qc8ay+9xW8aYBYc73ibL9cFeVxXbdIGIYM2RTdRvaVl9TVG98Qs+/7NfRY8MSdbWAFYJtb/a"
    b"bPbCQbc7pb+nF40OOGSW2p+MmqlgV4B83kU18wA0BJYENbsvghb51Wz7cNeeg3t6a/vTCJbSS3wq"
    b"ZNrDbV2WWhb6jIKbsq8cWtg8Mh5aOJzYjQpUl4/Nq/blUpUl9iOZvxq3S1YRM33kkspKtStKbzuc"
    b"TwdxO3fu67djlm3yJrMcegW7bXCUbUclJYAifxzg5OXboiDmj/+cUaymq4HuORscU+Go+3aw4uTk"
    b"KNsd+oGHDJZJluXV4KMa6AFUWmkqrT9pZWoZr/cICaVgzsocKzuStTXjI9kxaMeKbLpWg5moYDhQ"
    b"YouS7uv5y246M0bbmV2fYnu6VfuO9tURwamRULmrGCsb0fztoUjS/2Nt1Iy9PQVzOC1qsEcfxq0R"
    b"h5bFOpr5UN71wahUV8fXpFUd+HtNXwvR9hM47pnh0xmCpBqMzQk+wt1Z1fPudqMNB0BpEUBlWwnc"
    b"ehc/io97sKvZfFPF55T0SkFPmiYJftENB7NDPaB2S7XrW4bEIC0H2rmoch3cJVlyq1aDx7RaDyBg"
    b"39EUB9Du5NAiTbMz91dnTTbkMKsvB+dUzSZHh2IMB7HFaz7a/M66ws+tddweVDsmUBDHVOBW6tgW"
    b"O4/5HBv3keITklrTx5QE7aD2AKCm+XFDVPY9PkyTNxX16MtjetbJWk2fu/RO6S7pHenhx/vstp3E"
    b"HAvl55yr+/RRoeiJXXfrEdcHmu6xvbDFF9bYR/Fhf4p8PUJKMHWCrkwe7mnlpEYfU+rKOVAnACpr"
    b"cPqwVZhOkJSgvoxaz+zpE5ux6Sgt3yQEhSWVQxQZqTm3btqwMDG9/gw19DvppjoBLHnIz3yAFfUS"
    b"ybXUR8czZIT6GySM6XW6051wpjSO65pMS8kfIe2HJpaWM4KuA7bP874eNRmDexjMbOk2teu+0oH7"
    b"aoE6RW5lXgrDN4iCprVbykKoe+uJvWzGA/hSsO11A1++7NdcfVi62quy9ikw52GrIPsyaoHA4uOo"
    b"7yly8WkX4nO+D4hTVVofOof2nzQ3swN638txez7cAlvM8NcJ9GXqj3/RHv0q/iAu27B4MsJsHV5u"
    b"Hnf9tl+9dpy1/2APRVOu11FCspTbJPlEvImHfuvv4MYoYZUv+f+swARSLfyx1uuxfZDpb4xP724x"
    b"eC/Ttf6poCirJFuikPzTr+8udde39ZH8fZIdGso965EvTT56NSK/tBAGl7Z4Re0//PDjj/82KPOH"
    b"YqneJff3hJ0UT7FZ0N2l2ejv9JPc/y90LuNS"
))

QRIOUS_RUNTIME_JS = zlib.decompress(base64.b64decode(  # generated from qrious-4.0.2.runtime.min.js
    b"eNq1XGtz3LiV/Z5f0dIHFSmiewiSTfZDlNb2epLUyvZkZpLdKlVHRXdDasYtUiEpaxxJ/33vuQBf"
    b"/bDHW9mKR02CwMV9nnsBEvnh9Gjwl5/T/KEcfA5G7sgbPA+sN/bAc2U0eLVJylWSFoN3qliqgh79"
    b"8afLwWd/cJkuVVaqP7xOSrUa5NngH+U/C5Ut85Vqx7uD6l//oX5Ty/vlaJnf7Y4+/eEPRzcP2bJK"
    b"88yqhLKfjvOP/1DL6jiOqy/3Kr8ZqN/u86IqT06OH7KVukkztTo+qh/e5auHjbrQPyPTNVaWPTuu"
    b"ybaU9OiTE/07Su5WF/rSUvasGmkdYPCLVa3TUjSMEVcPpRqUVZESZ/O6fVBplj8nxSCbF6p6KLI9"
    b"035ggUbLQiWVusji3r1V2TOrHN0XeZWjf1yJLM7U46AU3dbsYbOxBfGeWkeuyGhWkb00fJAA1FaK"
    b"QvOSx2C/ZghcZ7etyoiIVcREPs5oKiVq4i3nTdes17WjDk16kI+S+/vNF62tpLh9uFNZVdovtiA2"
    b"JbGUE0si60pn5e2dKHsPyUMyYvZhWeUFJhwtyffK61g9P+fmmhrLh3tVXMd5V/4UdhCp/XSTFxZb"
    b"g5SRxK5Yx1Ya0+Bks7Ea/oRn26ONym6r9Tw5o/8cx34q4/QqWcxBgOhlg9KuTk6OCj20FJn9/Gyp"
    b"q2wRl/THfmnnhjpeMGfZVdCLKGo7t/Ktk/LDY/ZTkZME1ReRx6+KIvnS6VBuKCyIcTVvhD9+rz6n"
    b"5XEruKZK9+q3SmWrOJlj8jUp7CZem0arG1LQCww0+mfB/l0JvlMbBW2QA3RvtztlyceNWsWv83yj"
    b"ksxK7RfxtCqSx1k7A4S9VdVbTWC26yVdSqTFHmFyZr4n5FipwrLtHjdM+B3H9i/pv1RvUkit4o5g"
    b"Io3V6D5Zrcjbn58pSOJ3SbUe3WxysqlFyiUKQ+80tX+oRo/pqlrbJkIG3O8u+c0il7V5zg83N6Wq"
    b"fv988/TGQhQdxaltiKZsl0yP6IlB1Cii9jCXndac/eDtMudSuJBbsaJ6nHUVSgFr9AmKll1rl6Sp"
    b"b2A+Gsa0ekKy1/K4XhtF8zK+qT1r1/qsGJGKrKec8oDgRdOudYw2jVeNC9KzN3lW0YTWsbc6tjko"
    b"89FNutn8Un3ZEF6NqEXdFjklBJGPbjf5x2TzanO/TnqPuIXgzZ2rM6PYuaJYB7mUWtOmNaXWavTx"
    b"4eZGFVdpbQVHLU5O9Lw/U8hZ5alyClGepvhrjLGlQOii6ulBfV02cqKKjT9Xow1lov/GxLEUBIYU"
    b"cAXP6wqX1JsS/Hd0QOwmy09GB6qng+4jo4NWiJrYPlN3uDf8zo0qiOZapbfrnmzMN9zjoQUeBIF4"
    b"en354c1/za5cIaWQYyGnwvOFFwmfbkMhJ8JzhecJLxBeKLzubdMy6bc0jd2WbmOvZUFMbfYy9cvs"
    b"SpIGiKNI8AWx4+orn//R1VRI/dAP6odEFT2F5tOrh6KZrsZjlpKuAs0JnkYspyZsRkxclhSUvfqp"
    b"5j3Q0+oppDupqQQ+d6D/YYKJvpLMBD0NJ2jDWNKt1FSg60BfjVkZdBWxhtEGA6CNBAv0WMn86dmm"
    b"UT2bz+rHtWyvWtloLp+IoWOoHwesDldfeTWZmkHJgoQCwzWDoRbJ0+xPJMZSLzF2QRlUIOOE5ph0"
    b"6E29emw9L09KlCMtkqEn3QiNsI4foSOaPVa2ZOFZhbC2JCZ4wrEI9HNJl1oWfclTwroTpjRGT6nb"
    b"WF0+d4w6HafskeTtImAJIacRW/sYT8nEwedEO1lg3Am9PW05+BDLBKrSY9VMoRxWJjtp03Vquvos"
    b"nq8viTHtkRL68SQutZsxBb9lgRkLuIOEiEawMfNm7BSw4cFkBNf0DOHQMEEshEJ7hgd9QMl1Xx7G"
    b"PqoJ+4EJjIBVL4k1tgLJEGiVSJZHcxGyt7LWQuYi0pfoPa57N6QxvWaDXc8NjSv4hnRkkMXnYG7t"
    b"weO0EiVruYaXWkDf125eU4YLudqRNBs6bH2m5hnLc5xAiZppH88Do1Bftg7kS9M7Yt1pNcKvjITs"
    b"yJr01FiJrrV9jABT3Bj10aDaiIDecS2kz14x1lrypkbIAPjU9q4ZZ9vJVj1+7aQkR+MiU1w3/ZuI"
    b"kuxvRofT2v1Z1CBsuQm7/Wv6QdCE1ngqpNG5ZK/SniLZ+bSs/rR1FWCCbFwFXqP7h/A43T1gxDfd"
    b"RRi0vLcmZYqGl2mne9DyzvBp+kOrXt1/0nJDavU905+x0ThBACsbbvzWG2meMBKNMaGaCV9P4B1G"
    b"2AD/DDvU3wi7ED/++f2ry+sfP/z87tWvsyvfDUPIESDpejJCWEwigKIkjXpjn5DZiyKGgSnwSo7B"
    b"hhtFiEk5oRbfj4h4NEWAhOMppvMj5HLpkiB+GFK7508RazICUE3GgZj6U4q1cURKk9MpBPbIf8dR"
    b"OCVkp+eRPyXBQhd5YQrrEns+gJdgaCEu3/7t7eUvs6fLmRTvZp74y8wXf5oFKDGut7P52//56cP7"
    b"t+9/RT4HpHOC9rVBtcuNJxqvfAhGjPtciFBmi2BDD4E1hXJ1bHpQqwvUQYiEBs7JmiSQhJTjCJ4W"
    b"ITZCBGMEtCJo9jXESKRKeD9qHSAIcIVjI4Jzm1D12PiYksyDLhN44xjy0/VYg6bHOhVT8MtJWUKT"
    b"Y8YvXE0QgciYQK/aYUKXM4QHZY6BMtQBsEhZiyEesQAzkUN4Y2RXpBmY1hdTdPN01gCAIYzJ0vBF"
    b"VEARPA6Z3K/zBikPTuBpM9I1tbpQ2RSOGtJTLtPgRGAe0RRxJKOYABXINKYESBO7sA4cyjfxD11P"
    b"gNukSIQYuQ7cacz4G4IFj5GFkjrQmMwJYgHiHkKQ/aFHUjq5siR640ijOpwCvjzRAOhxAAGYSNP4"
    b"QdyS0PBq0sEYZR44AK0pPJ0EQoohtY6hOqgUhSJBNODPBVCABtyFLlESwt4oI8IxagdJDhPCDWEg"
    b"1DnSBQdwDi4fdKJH0GNqMAzgiwT4JbHhW6RZqBs+iFyODBzA3cA+mBgDTuBREcUBNZIfThk9qD5C"
    b"/RYwXjDewD6AcOAs8gORA6S7qAOmpj6iTnA1hAu8ZYwMAEvDLyRKznGga1UkaNI28IJ4IjC6/PDH"
    b"2RX0hMIGYyEvktYUlQb8jieccN0K65MFSI2B1onHdQCcDNoGO7CEiSkECzzLRRIGa5KrGF/HBOSh"
    b"+XyN0j5HZxAxW3AmRAd8CvEyZZiHWhFTyJDkwv6UVYpQZDAApHFcATu50AjYGiH7DVQFm8OH4ZIT"
    b"HXqexhf4fqSrLVK1z6AJlXHYsAghow2ch31pMtX+JRn+EQekZvII8uWQAR/ezz7us8FhU8wldcFL"
    b"EQJsCdhSiCeAS6hxggFkzIgkua6AA9HcWBlI7epwGg4MsAS/04WIx+jnsRJdhlZEi89BHwUMVohy"
    b"KG1qoCXg8IDbA7SkBl2OaQCfx5ACPAk01pDf+RrJEK0cgghM6JdNMWGXYwgPAg3jAA6wDsCDn0zN"
    b"2sWD9zPsRbyioAbG4QmjBkHkmOMJjkozgEEKKeRWRjv24wmnNcYRwBXimW6RFuFUHtf5jNJcR0wY"
    b"qUmrE1N4RDX6IKSABb7BXaweyNNpPp1KEckIWk5GIcMccgKnEB2bHockwhX5CRFL1oFDQe0AYoZM"
    b"l6FeMoOeTnhcfwSc0YCPpHQO4zFWxasDS3WfkSrgskCyCpBVAOXI0x6MSMEAsAHlKXTBWXMMfflc"
    b"GyHPhVAjg5KLYiWiuQMSKXClxgbfpXiZEMNEhkAQnjXmdBOhyAbDUyDDhHEBWkQZQzokZqgPBPi8"
    b"b5OzswmFXXBsKI0+J5sHVW/zYsuHdy6uPyarTJVlfLXQu2HXG/VZbeLNSBcfV9WIG+qn9/nmS5bf"
    b"pcmmHcGU6xnqNlWUxEpstjOv9ab7a95RopHzXq+zwK336eomxxFZHJxaHZ6G0nZkeNrvR42iJG71"
    b"ZsYVjVuIYutebd2nnfsFtvxPrdIpbKcY+k6f+lk8tcWRlZ/FmW3PbcP1KqmS15t8+aneK75Wy6Vu"
    b"SE1DVrfIuNxu8uKCt0ITvXek95Nk5ASnvbn1ZHoPLv48utavR3iH3EpOE7udevupcuhfatdS1T3v"
    b"kvLTdleiZCUOFIstVtMxzUpVVD+m2FgtrX7rq016m/Fbg/qB2SWcOCA1nNiLWPZG/JrekeX/mNw3"
    b"lAoFEdU74meLuu77c/74Klu9yTcPd9lWh79p3TSt5Zds2aOzzDMiXr1Oq18qkvPOypsnyWb5sCHJ"
    b"f2pcuBmV3N9TAL1dLn/N/5OM25m0UsVGJZ8VW65Vxn2ybOe8SbO0XFt4FXCdrFaNimb9F3mwebMr"
    b"rLVW7wrrXVd+13JVOeWpghLTeOjN0zOPd2PRntITSw09VjE1DD1uoHZZNzl1U9NAD3UTD5u3e72a"
    b"rlGjqliL1VAKDBZbzQ41D3ebhyk1y93e1EwsvQijV6h01n8DIzKtDwYnYSKhAy5iHe/iBjNfEPPF"
    b"WTYviPn1VeoUC2poHyh+8JTeWFRuHcWxVcbXIyq/rtaki2LxdxqyWNi85Z2TOnKilBtK+VAuYr5Y"
    b"/P16VK+nrihi7vLVewqm5Cob5gt7MVebUg00iZRIpE5NJAeB3JGLOehkIEhsxHFcXrizAzRdovjS"
    b"6KrxwZ19aGzcY3e8D0G1P7Xu/S757ZJB3rJr92rwSeM+Kao628apedV4Q2s1y6QQmwxK2JY5cXmY"
    b"hHeQhCNbIrgmMlrgzRd4zOxg4urFSt6NlfIxrZZrDFgmZAx3BrZKYqs8y+elealB6Wee0X2GAHLK"
    b"E/n8bOK6xLyKcj6x9fxsFZQYylOyeyzt+UfCjU9zJiu/SVaelN9L1NtLFNbtEBZ4MeOT5+DtND0j"
    b"5X3vPP7MBLvozCVSMx9op0Q7Zdow7r918uCgkGlcnp/LE/m1CanTEcFN+r2zjr9H5G/o28pOyGNs"
    b"58g6Us/EzffyEv4/8GJRi8JI+/t9Ofp38tPw4VgcWL+TH+DcLlAdekXeolxd9LVw5WyDj73T0p2r"
    b"zfl7cLVB1XpoA6ptQjLJ2eXqhtEvZbh7qpO2xBOqgufq3J2r4ZAyNmVx/LmgP5QJ9uUUnZrQaeFU"
    b"9mKme855nq90d3X3lxaKY80NMbKI617VYgEVrNXy02td5O+V3SCtW+NrvSKos7JB3/V2paK9aD2U"
    b"W7iIFiCjRenSWZ+Wi5MTXMnO9RqlKdUs7RN9//x81Ix6fm5H6eu2V3+UbeOrHIdK2/eezZX1jSkJ"
    b"DIvM4FPt/TmU68KIxsfXzG5F7kzOXU9vX+RUKTjOLL9ynBS2vXFiUrayL+SMJKT5tLZuVWW0i49B"
    b"bs6wkrmJhzeakyXN8hDfMDcPTvxwduYJ+kOVx8P5+nQ9tx+GMf2KpePoIsaJl6ckSNDjbR/vXdm+"
    b"yTvxfYhjE3AFXGWrdv7aVw2Ilaa8qFcsnQ8JTNFKs3fWiKPlOine5Cv1qqKpWUHFnjovzvSHP1bz"
    b"JcTe6mZencf50MPKEb+iPJ+enFQUefXqCh+hUKNWX3GVOB6UhwsfRWMyHM5tFdP9wjQ+o1o7UWdn"
    b"gTDd1fl5MC+uPPOo0o8o1it6QFdkjjB4phvpvaAqbKaS9VTevqm87alkM5XsT9VMEHC0k1SOP7TK"
    b"M+na84Tg2cZoh8pMPxTmUkZky9bI+6zIvt+L9rlJz3N1Bgxj46nFeTxGTuDYkg5ahmPbdPXxFQlF"
    b"AhV1HjoPSdIYgEfSnZzoX91AkMYNKId1DzT4p90marBc050M8awc/7x6ftadfGIkwNXCtDhti90w"
    b"6DefCKWkAL0o6yLeHkfrAFztcvM2KUBJvgo6qpk02xRN8WopSodV7aYdsLVs+wzfC5Ki8WWULaIj"
    b"JEzWbXdpv8tWw0p6xDl3e0aqjLJ4M+q+4aLVRn+r5OzMp4WK/gyvC+PFNowbwcCWyM7PKUnLE7Bd"
    b"XhVDOVTO5LTgzHYWXpS0yC94bTrTl5bSK0+7QynaQ4n7FsPIUbwsVUQpbEgTrchcYsm4veT+Wr7e"
    b"XQV1UanJ5t3ktneZVK8/2/KiWX+25YS4ObQk3akHtCYSE0YFgvKGSgR1mi46mlr3nyenqYM+Fi/n"
    b"X35nvw4DJTPQmd/ZGpnzuLLefOtDLqu+v8NzoFzog35/CwOf/Z1LWzP1oHfZsMlGRf8wms9r9eBG"
    b"nVdDv42nzr4JlozYdiN8wa6bGmooTwmZnKmtS9p0WH+S2R8aimaboteeipCrz97e1sF66Osho9Xt"
    b"9+yNfC0kAVjFNTI5uy08c5vp25LSs6+jxrf1Bg9SZcipEg9TE13cs+ju7KAhNE1NA3Z2uCns7OxI"
    b"ojjes7OTmU0Zsd3MGz77Hoz37QTxrPTAZIE0xg5V0JOg3mpiHr1dOYKDcgRoao3UbBx+BQK2cSxq"
    b"4bXhOcLH4f2mdDjZbYwgMBmqY+NJZ0uj2d4S0Z4dLyK42yyo2d6Sp7u5uW+Pp+t56X7PS4cyYMbk"
    b"SXVh9eecOBV5+hYjoaBm255ZiqC4csJTLgrVVeikpxhhN9jb2WP9ruBo0CDfQoPiPDRosDJoQLGA"
    b"LXkZ9fy/XT/4eslJdZykSDqX8qI4P6dCwZtRFUTlN+WT8TB18lPLG2bYtKtdq77FI+rBQs221EPt"
    b"ohm2paW6XWAwq8OsZPft42Ij/VYPpHqZH9TVB6NAs+NOJTCRwn7xITgl3um/LsqQFin5UlrC33Vs"
    b"bWU7p5/f7P/T6ngnEWkr7aYGqrGMpSawlKiwfLGfpDc5qWr4Nu8AcorjhOuBVf5UXuTD4czKUQ1c"
    b"uFTJJBcJGrL4KBMhViz5kCpHIkH9SNYpOWhC3UjmC6pjD3YcxhPbxtbmUfnyuE43ytrad8hFYjPW"
    b"d94z/C4I0dE13Rvzk2/CAmPAZNupJqKyv4FPE4M7xLFp+r0O1/Mygk7RvA/5DshMO9bnrQTVSmfs"
    b"SrKdokLfVoqCmp+6L5T2LjauulWPXlyk2Bxxu/V6K9s+6eue1bniTaoKS1psW+KDcewwx+qUflB1"
    b"4qYigtgx6bEDHrBmpNXVnJbMllUNcW2fn09sx+I1VxPDROC9nPnivYc//ixwxftgJt0XW9zHn8Xd"
    b"we//69MH5vP2slj2vhCveG//rz9fWvu+lt8Zenz87/ws/fbQeRi8jeEBWXKn6rqK9JfepDhE0Zx2"
    b"qVPmSt0kD5vqb/zeN+2+Bf61SLKSFH2nS8qnqr4/dHRkZ9jhY2PqgkKdJ7NnFeT5tP3uPvnYX+0a"
    b"Y+qDKNUFnxyhPjhihrYXoQ8gbTmcGfWN00r6IBTHgMjy/L5/bKTK/3pP3d4kpfoaR9Wo09EyXJFk"
    b"j/tf6rPG8nvcljFmweGOt8lyfbDXVcU2XSAiWHNkE/VbWlZfU1Rv/ILP/+xX0SNDkrU1gFVC7a82"
    b"m71w0O1O6e/pRaMDDpml9iejZirYFSCfd1HNPAANgSVBze6LoEV+Nds+3LXn4J7e2v40gqX0Ep8K"
    b"mfZwW5elloU+o+Cm7CuHFjaPjIcWDid2owLV5WPzqn25VGWJ/Ujmr8btklXETB+5pLJS7YrS2w7n"
    b"00Hczp37+u2YZZu8ySyHXsFuGxxl21FJCaDIHwc4efm2KIj54z9nFKvpaqB7zgbHVDjqvh2sODk5"
    b"ynaHfuAhg2WSZXk1+KgGegCVVppK609amVrG6z1CQimYszLHyo5kbc34SHYM2rEim67VYCYqGA6U"
    b"2KKk+3r+spvOjNF2Zten2J5u1b6jfXVEcGokVO4qxspGNH97KJL0/1gbNWNvT8EcTosa7NGHcWvE"
    b"oWWxjmY+lHd9MCrV1fE1aVUH/l7T10K0/QSOe2b4dIYgqQZjc4KPcHdW9by73WjDAVBaBFDZVgK3"
    b"3sWP4uMe7Go231TxOSW9UtCTpkmCX3TDwexQD6jdUu36liExSMuBdi6qXAd3SZbcqtXgMa3WAwjY"
    b"dzTFAbQ7ObRI0+zM/dVZkw05zOrLwTlVs8nRoRjDQWzxmo82v7Ou8HNrHbcH1Y4JFMQxFbiVOrbF"
    b"zmM+x8Z9pPiEpNb0MSVBO6g9AKhpftwQlX2PD9PkTUU9+vKYnnWyVtPnLr1Tukt6R3r44T67bScx"
    b"x0L5OefqPn1UKHpi1916xPWBpntsL2zxhTX2UXzYnyJfj5ASTJ2gK5OHe1o5qdHHlLpyDtQJgMoa"
    b"nD5sFaYTJCWoL6PWM3v6xGZsOkrLNwlBYUnlEEVGas6tmzYsTEyvP0MN/U66qU4ASx7yMx9gRb1E"
    b"ci310fEMGaH+Bgljep3udCecKY3juibTUvJHSPuhiaXljKDrgO3zvK9HTcbgHgYzW7pN7bqvdOC+"
    b"WqBOkVuZl8LwDaKgae2WshDq3npiL5vxAL4UbHvdwJcv+zVXH5au9qqsfQrMedgqyL6MWiCw+Djq"
    b"e4pcfNqF+JzvA+JUldaHzqH9J83N7IDe93Lcng+3wBYz/HUCfZn641+0R7+KP4jLNiyejDBbh5eb"
    b"x12/7VevHWftP9hD0ZTrdZSQLOU2ST4Rb+Kh3/o7uDFKWOVL/j8rMIFUC3+s9XpsH2T6G+PTu1sM"
    b"3st0rX8qKMoqyZYoJP/067tL3fVtfSR/n2SHhnLPeuRLk49ejcgvLYTBpS1eUfsf/hfmVdWO"
))

QRIOUS_SOURCE_JS = zlib.decompress(base64.b64decode(  # generated from qrious-4.0.2.js
    b"eNrtfftXG0eW8O/+Kyre78SSLYRegDDGGezghLO2STCezHwcvpyW1IK2hVrbLQGaCfu3733Uu6tb"
    b"wibZ7LczZ4Khu+rWvbfuux69+fSReCp+PknSRS6ue81Ws4MPXqezZZZcXM5F7XVddFrtHXEwifJR"
    b"lGTiXZwN4yzYqiVO0yvxf+NsMbyMoAU2Or1McjHL0ossuhLw6ziLY5Gn4/lNlMXPxTJdiGE0FVk8"
    b"SvJ5lgwW81gkcxFNR5tpJq7SUTJeIhx4tpiO4kzML2Mxj7OrXKRj+uOH9x/FD/E0zqKJ+GkxmCRD"
    b"8TYZxtM8FhEMjU/yy3gkBgQHe7xBHD5IHMSbFABH8ySdNkScwPtMXMdZDn+LrhpDAmyIlCivRXPE"
    b"PBPpDPvVAd2lmERz07VZQr6hciSSKcG+TGdA0SWABBpvkslEDGKxyOPxYtJAENBY/HJ0+uPxx1Nx"
    b"8P7v4peDk5OD96d/34PG88sU3sbXMYNKrmaTBCADXVk0nS8BfYTw7vDk9Y/Q5eDV0duj078DEeLN"
    b"0en7ww8fxJvjE3Egfjo4OT16/fHtwYn46ePJT8cfDptCfIgRrRgBVLB4TLMEbBzF8yiZ5Irwv8PE"
    b"5oDdZCQuo+sYJngYJ9eAWySGIDerJw+BRJN0ekFkQmPDSEDuaCym6bwhckDyxeV8Pnu+uXlzc9O8"
    b"mC6aaXaxOWEg+eZLRGjzUW28mA5xrkTtYpIOoklDjKPhPM2WdfHPR0LMl7MYUIpvZ2k2z8X+/r54"
    b"kg4+xcP5E/Htt+o1iONiEotv8C1K4ziZxqMn4jv5oqm7K+C1unhuoHMHBq7wIfD8ohldjQAW/1HT"
    b"6CEAiXRTaqoFv7736K6GzGkIi0YgCjCE6UFpAxr2HgGQTZgYsZZ2N8Q302T6KaL23OknULkkJ62A"
    b"iQAliQdLcYFSFo8arNVAIeh9dgFqMk9JJWagDNAhHYBoAMALOfkMkSQAYCljgDoPGpunwyRC9Ril"
    b"w8VVPJ2TaopxMolzUUOZeaxU93GdRhrF0YRBSo3Sqq0UJIuZD6TjyXQ4WYwSKVj4epJcJXIY7E68"
    b"yRkigF+g3iPaDWmO4N+YqJS2pWFpNUgkSTFbC2nF8ngiEQQwSawtl8KTGuJQM2TyXLItxyc3l2BR"
    b"HZoSidl4kU3ZsCELUmAjjY0ii0+wzzidTNIbpHSYTkcJEpg/t+b0FNpEgxS0c6hFArQKsGeESOXM"
    b"vMtX+WXENooZyYYs8inMEJl8DvKRgGqjWuDoPuVNG5sfD8WH4zenYN8OxdEH8dPJ8V+Pvj/8Xjw+"
    b"+AB/P25oK6gsoDh+Qxbx34/ef98Qh3/76QRN2vEJwzt699Pbo0N4cfT+9duP3x+9/0G8gs7vj0/F"
    b"26N3R6cA+fSYRpXwjg4/IETPWjYY2iqDCYh8D7DfH71/cwJDHb47fH/ahKHhmTj8K/whPvx48PYt"
    b"jscADz4CMSeIrnh9/NPfT45++PFU/Hj89vtDePjqEHA8ePX2kMcDGl+/PTh61xDfH7w7+OGQeh0D"
    b"KEkqtmVkxS8/HuJzHPkA/v/69Oj4PVL1+vj96Qn82QCiT051/1+OPhw2xMHJ0Qfkz5uT43eSXuQz"
    b"dDsmSND5/SGDwjlwpwqa4N8fPxxqqOL7w4O3APADdtYUqx486ZtskuTkH4gBiMPGIJ2C8IC0gj4t"
    b"0MKRf8kXGRh+MAroAOYpWlOR30SzGYi2LUF/mWXJNTSTf1lg5IhCXEcZ2D8Dfh9QAJUCOR0sJiK5"
    b"mKIrm8a3c2gulD1Fc3q356KbxWOwgVPQB1C2F8N0FL88JuVrahybl1F+fDP9KQMHn82XLzapVQXC"
    b"RNg/38hR7xykXViA94rRVqN7ADHC0uqfo9n6OiQJBOAWBL3nTPjrLAaYORgawX4WTF0yvARbAr4l"
    b"AR+KZuIiwciG0dXQAigeUxgGNghsM/YbEvCRgowBJtgrmNV4ivYKTCeFeTKwAGGaxcNkjJGTHguZ"
    b"CIYsyI8Ig7l/8gTcWTK5QcDM38BqMpNEEUWgAezCQM8MCucSbiqJFOaVHEETVjVAFs/BY5gR0PhP"
    b"45vJ0mveDMw6zq8OLrg5g6lpYhsWWhxSsUiA611M5nv0d7mq0etkDP6dIyUp3DyUFzAp6ELCNrrA"
    b"zQ1OdR72TsQTCIVUL0v9jYgCEP37ng8e2GT3qtX3VoCaLiYTOfYjTVqRP0LOnOQlQAI28qgOOx1Q"
    b"ch4NX+8cvTokiKw+th2lWAIVjLz6VQyRzwgjOSvg0uoQVjgZzfAw3CTHqGmolARRvk5ADm1tgUCd"
    b"206jKw2JQ3lq2/CyHgwBGXkISXOBvSgYkTocDYdxjq2ukwiiSVJcFf3xONTvVwslNpgythteJpCR"
    b"WIyBlA5twU2Sx/6wMlbJFwDB4aWNrgo883kcjZqkVRaIq2gJoVGeauIwToR4LItnMIEmuAWgCCIC"
    b"A61jpAKqogZE26TO0w8EThIL0TDmijTB8H8I1wT4SDC90WASq5jwRfJyAsboxWbyUqe5MOD7+DrJ"
    b"g/NmIXCv6fN8uKbIZjhMIKassQodLRaTrKZTNE9g1/M1ZkJPghfhFntVypISbey1vhiFHATPNdhy"
    b"FIV9nJYmC6ey6JagzI2IONwSfhCjoWsPLM6sNhp0GfvL3Q0r+3nBixXcjcx714IrLYSCyn/eD6Ry"
    b"XIbgU82dUhFV8ikkQIgrtZ9LsHYAf9+AqFKEoV0epW5Fj8dWuoYT1XBth+X+JKW27yMZcqNNlIK9"
    b"R767IxGgqgLLjOXjJNiQf7I9joWVej10BsYh1BsarsRLSYzszt+UuN+HQs0Os2UD7eZ8FjbRoi1l"
    b"wSPKLqhCkGuHfOfQ43jXMdhhf/p86GYW5RwNSxy8EwMVcHSDIicWCQJsuvxwGFboxSZEzqj47bci"
    b"i7hFcTw2adDT77HnRBbefJWHF37UPMfaz1xpoIrqVVBh6XwCKhWheR9b4UaeLrJhXBlLgHxiVYlb"
    b"oheSkQXIsXZNxhtxhDkKWeZBmk7iCCxJejMFyyTRh/BLgQGrxL4HS5UvBi+h3YvNwUubiHGWXoVR"
    b"T6fz1HHTNl/2LPfHr0kw5duwFWUA0oTKP5ykSRZarVTABdRsNo1FZmS1RWZmMrgc6025M1dYcmIb"
    b"TZWdEVEXIsyz1tdpMrpblUo4Cgo8bkjqGhItbU3lnyi7mEo2MSaoafVviI5SWDS7MysFloaYussm"
    b"Y4qk4GkC4FoNMYmnFyCj+2qQJj/Yg/cvhP792TPL8DHPdI+z5FzCltB1uACSzm1s04Zm9huUPFBe"
    b"N2lnuriHzgCWdbuzkCxSCeLyXONhHu3p5neP7H/vlD4j+cz8X9vQn391E3R0soMoV1EKiTtLG5b/"
    b"SIhzJXjc39U040vDlRgtBBR6UokFnnIcqm3cE/r7yZ5+o20YC83ev3Kff+U+/8p9/pX7/Cv3ebjc"
    b"R/yFUZV/XMVXgzhTeqLtN2sNW37tQn5t7yn3MsX38ILa6aeof1RRUw+18T6J8xnQkqC+IisyjGMy"
    b"XjT8+UQgaeKff5kk08/iDfA5vkN5jFQQOqQ1VtTmeBJjUGAL5YEEBqqARol4PoMn0XSuhNqMlmKQ"
    b"SWqqQGE0wozMTBv4O0EfGg8Xc7koCuqcZrji5WuhC1yBVao4wtJ8xtXbUZKDwcKWBqkY7WOCy2hY"
    b"3r5Mb+JrXKHFSDiaz+Or2VxgQIgdJGS5QJjJpUMNhiyGrGpCZALWaxDjWMnVVTxCPwgWJ56ixRzJ"
    b"BUANUraUoIJBNa9N34n/yGiNmoVezph6pwy9pfMukKd3esQNZ3wKO5UXj7VEJEqLFGYlgf6ZpOs8"
    b"HO6j25Conkhu3SFs2as6aA+qENk3+Xss4xJXgVAd1GCgEqgZUp30Qn6NedkwkigRUhGh1B4laCXc"
    b"bso2qulf0MCBjWJuWas6sqN+qlVf4flv8hUX7Mmsy+nel/MuA2EPseAslvDcaIs10WuT8PR+2CvE"
    b"9hWKe4V3qyn85TIme7FKjNYmQont/UiRmrsvXnH3mhIWSuMbIDI+4t9n0Y2fyyvNknKeWaGrtJW0"
    b"D2uyxBmyja1F2BEGNnrvBkV1BbZAVn21yOeUVqdg0TJwWU6ArkJyMLOYLGlDP0kvkmGRlTIyYNdA"
    b"aLsmSL6RPhcIn+q+hZy1ZHKiAbjaiFfU1pkWHOW5KW8RUpjnNAoTcUIY5OUW72t05WjsJz4YVmLS"
    b"A3FEXA6cnZEX55b5Ctv+4qCDeIzrezZBhC/SGdAENQVP72x70TSToW3rOowHf3jIEJ6HqouUgNs6"
    b"YyfYni6hm9hzXzKpZhXw7tEjp2ZpGw9ZjyzO+OtoMlxMaAmc9C/5Ryxq4JRnyW08ARVL5nkdhVVn"
    b"S7hSnkxHCYR2C4jU5VY0VBK560kpLibtI6mrarSAMjsJqzUVB1Mse03HycUCg5JZNJJ7pXj+41u5"
    b"6ccKL3hOiQYf2qnd4DqaLGINKZoLsFI5Cnrc4D2MQMkQsMcyVCyFhxgjs0JF4SiNOcUbJ7hpkjaM"
    b"zLEQ1DTDch44wliXoreII6QEI885JYXDSUI7SGg/G4gwzjftZLwAHcfdlyDheULBCkK7wXRWoZyn"
    b"qEzcWY0J6jKbREuTjCHan8DEQcg3mESgXfkMAONOtolZqx9Ew88XGW5BBSomMpn6EsNmFWjwpZQP"
    b"Yl9iUo0M92AWtG66QHVi1WMBpH4YhlOhVgLzBI0HU9M5TYE3OUozbumYxs0KQ7pafd/RiB8Ai4AB"
    b"leqGAZT2zVYssme9V+KrnHdTPfjtN9FyGiLZCOhdNL9sjidpmtVk+NUkZmyImur7VHTqdbHJk9G8"
    b"SUbzy/qeZwQIzFV0W2s3JOz6urYgHY/zeL6pRgtZBdpWkkMaiYJkLG3IBAR0X41bZgIqlPYfMG1o"
    b"P+ekoFRpEdF1lExIpRhzzDuT8draq0bVSiyOpLuZYqZDpgJ+vYBY4jpmdJr3U/BoNoujLGftnkZA"
    b"GOZSalz0XslcVY2okzJvWOkcJVlM4pc/lGpKLn2BVsqeqlKwhiLifH2dJh7TmL+PFmqlof0xstE3"
    b"vDIZWAzUvTy/i0NcaYOh0HCsiMTaRkoys1LjLahPHXVH9e+UK32rIcGXKz0zPLeqG6Xh9Sp9LlXk"
    b"e0bFfgxXFhjfKxZjoOXyQ4vOVbEYhD84gfVCFAbsLTzFkNub67vyGQAIeQnPISIZj1HxrzHSHYLb"
    b"51oU7mrPwMSAlMBzxbHS0PuPT4R+r2SG+O2G0wGeHk5zCBtzY49tDxCQ7KtoPrxU7VUlVAq6tTyz"
    b"ZmHj/y92u8EPLZBhIl/XxVTVk9bw1B9uVfVgSoeCDFOCPEGHcpNmn9WhCFVbjqbXkV7hklOWVyzz"
    b"BWpeahB3BzYBtopfhhJVAisWK/6iZmudHNuy80lDfNq7h7P6Ck+iWrPPDLSkGOdWN1VpLnR5zW9q"
    b"TzqjJ8avyPZNzBk+zJeT2LhQDPo4cdjzGvNZoYPJ7DIKNacX7no1rYTzgrfl5LxVb9n2E7f95Lf9"
    b"5LZlw84tBgswpdkZdHWdqHgmknO3k0vyCe4LcJ1wgr2Y4Q3PP3+yX5k39u+WuzBr44VV8saashcw"
    b"ifeQs7VlwXTJWSitIKUgKaDZ8S/IXWjX9iWD3BgxFQIU+H9O7MltxlRInElV15I401xKXMn8lqBy"
    b"n1koWEqLZ6bC69Zl1A5syfYbyTP1N9h/PA7lzJ7kuI49LVPsWjQyyO4jaZZFnMMM4TGrjavFZJ5s"
    b"UE0gfy4eg+A+plMx7jEJ4FYE7g5SkeRiSoTMcNUnw2IJ6OMVGfX7meTiMsSBBu6uQ2AcHqob08Gx"
    b"AkKDSTr8XAxB3WjRLC1a9W7OdM7OAwVvjZoz56/eHr/+9+fiTE4iyI9oQ6Ld3oL/dhui04X/dhqi"
    b"227IFu1teNOHp9C004H/evAfPOv4z+znfee5hERv7RZ2r9C7wnMCdO4JkKaTZEf/9bViA/qCi/5p"
    b"JpPYh5SaQ4T92oBeX3YKWJHo5IE6BB4LzbAStdCaTGcS9TlrgjdOshzCzZuUKqRDPDOCASSLFUY8"
    b"DJ8OB3FsOYrmkSCd58OXEHjaNQFscvj6Nbd4aJH2+FYU7A9GskGoWbpBqgVItPNsG3+0Gs6zrvph"
    b"nmFX0d5peCC7vWJ3FFCGaz3rqB/e0NDYA7m1he+2nKY9HKbDIDuqO1KC6mg/6/IwHsg+odBymnY7"
    b"xe4da5ieQ/i2D7Ld6jd8jHpdBYOfdRQh1jAdaWUsLFX37b5pqkbv7Bhe9uxplMPoZ1sOLxXInb4h"
    b"XDXttl2MaAZ77tBtzcttH+TuTpHIbt/Mbk8RGXrWC4JsI4FdxrKrQG673XtaYFrusw6jY4HsBHjZ"
    b"1tPDvNxWGFm83LanzPBS8a3fNqO35ehbxFAXIxb1vqamX47lbqc4uk+4pllivmNPWRHLdmtHy2Vf"
    b"Et7dMSD7CsuWGRqx6xXlsqsEARliEYns6dndodGWNz36mUv4lgTZtzDaUiDbBuSWNFT0Z9eA3CkH"
    b"uds33bEZYt/bMlOBRPgzruwczTgMY+n4lual7A5I0KxvWyClsNgz3pGWyZsehWUb+SMJ2pVTYcsl"
    b"dfWESGHtgewqQUAKLHlDPtn2EkHSn23zbFdOl6fj3QDhikc9qzsSveVPD4ZNrUZIe3pKxxXfdhps"
    b"Lzsultse4Uj0thIsMz0dKRxtpNQHaU2PMp02luivjKPo2ViyuLYdUUeW93YsjNo8DQ7h2/zME6Jt"
    b"TfiOBrmtQG55IH0sW1JWXcKV7rZb266Od10slXLZIPHvkKirkYgqw/aex0v8x5+ebrdhzHIAS2xr"
    b"je4rZF9OPsbZmpcdxsLDsiuDDJuXNIFdl5c96d58s9FtF0DuaCEyvqcjLYwzPdJ+OljuMvs9kFsa"
    b"S2MvSW9bnhChydjypqfLz/zp6TakThuQNAM4Rdb0oCa1PYXsdIO8VJriYNliAh3jhobKwxKp6W4F"
    b"QfqOguSp7YJErIl33vT0toOEb4dAeliiofMdxdauRMeVS5StHU/HSd623enp7hZ1HOW31w7qOKm+"
    b"BXJbRsU2SCKw5YFE394L8rKgPRIjh/DdAMhekJcqtrNBkmB1PJD9IuEoWNjOA4lezDduGBKQ9tiE"
    b"dxsFS4RYb+8UCVfGHlFVTfusu870AKiuPz0I0kwP58aNYNZIOZrg9FUMcN8H1aqvovyzqE3i63gi"
    b"XrwQXfEbPar/kWnbm6P3B29/fXN88u7g1CRvm5virapQ3O7sDNGB3e50xl36dxRF9G9/d4T/bm93"
    b"xvRvF1kH/w5RauHf3R3t5AHgOw1wq4cqAP+20frAv/HOkP4d9Ab4b29rvEv/tvAwEfw7xvgf/o2i"
    b"lgXwZw2wu7VFGHRb24RBd9wlDLoROq3Wbac3IAo67T5R0IlHREFnEI8sgD9qgO3tPmHQ7g4Ig/Yw"
    b"JgzauyMs+t22draJglZniyhojVpEQavfHZQJwgFM7gxT+svFVTTdyOJoRIv9mK2TDORfNO/yBokX"
    b"fG6hIUsHL+8pBm8P/3r4FrJ3VX98+1zoCtS750KH5z8/B9cgf//xuegFS4reQFQX8p7thYs+P0ST"
    b"FK/aS+LJ6CELPhLu+nUeBxG8HG2K9ULanfHQ2slDObNx+Lefjt8fvrcUEkSrzQJHP3ssbCSSJJCd"
    b"FisM/uzTz/aINYA0ldrH1H5Iz/sszqwNWksBAonxLrXsUMstgsD6s0PCHtOTISlIn/SuRXBY11gR"
    b"2BJ0CZNt+jlsmVHYbnRYqUnBdqkXm4Mewd+lEbv0ZJuejOjJgJ7sUN+Y+g6JM7uESadr0UL49Fkx"
    b"WU0JTpttAWG4RbhF9HOLsBpEbLtoROL2gH7fJvgjGjFqm1HY8rCZ2CZMhtRrl3qxZdyitwPCZJsw"
    b"GdIobGRa1KZNbbpDtqz4c2xxbEy4sREaEbcHZCq36eeIKB3Q6DsEbUzQYnoyoidRl00staT2O/Q2"
    b"7phRRoRPRO171L5PLdvUskN09Yh7/T6bPXpLtFCSc8v2l43kgL0D4QyGXI/SJ2htttiEJ5v/MfWN"
    b"qdeQeu0SDl3CeYcwianlkHjITqHbZR9Ez4fWKNSGAk+w90Q79R2wj6JR2AtE7GwIn92Y/QQ9IXr7"
    b"RFeboHWo/VbPjBIRtB5B22WfQtC2qG9EfdlFsM/s0dtdetvdZa9KdFHLEbUcEM47liTHRN2IsBpI"
    b"X0v00vNd9nX0fIfwHxOlMUEbEbQBe27i5Jh6janXeGyNQm1G1CZiR0w/d6k9e1R2exwP7BL8LsHf"
    b"pnFHNG7ETp2eR+zALX3pd9iRUl/6fZugDYmT/RG7V/opXS+1pLc7JFcx/RxRy4habhHmkWXHtgjb"
    b"iMMMGmtAv+/Q72P6nYOMmPg2JAi7A44KqBdRHQ05ICHcaAZbu2YUDmM6hH+PMNwl3LqE2w61H9Pb"
    b"MUEYE7YcRY1plJh+Dulnn3626GfboqXDwRHBH7Q4AiMIBD8mKoZEBUc3bYLQ3eZYjHhFfSPq1SMc"
    b"+sTbVmXU6vjASXrxh7m/t8c/2J5vzD6GA6+2kR72hSxDbINYH9gbsdVj68B+gvnCFortC8i38a89"
    b"I4ssYSx/bNdYLllWpP0aGt/D3oLtF8sx+2b2pjuW9LcsSWJPwB6CLTVLEvsDtkHs/9gO8pyxzRqz"
    b"j2cL1ZEyauRyZDwleyOWGPaj7HdZ+tm3sS/fVfKtPRDbtbhn7JStY+zv2R6x7LJ1YFvM+skRgPRe"
    b"HSu22DJWiSOYXcvH9PtmFJZj9igcE3BSwJEH2ya2Wexv2K6x5+b4hu0+6wbbEY4MepZ/Ze/LFp+9"
    b"I/tLtgus22xb2dKx3+XoSkYSPaOT7Hs4kuiOzCjs9TkaYFvDUYuMS7aMhWIbxLERxz1szdke7XSN"
    b"HZEWcMealx1jK4ctY3c4EuLokP1Hy/LQHHVxfMM+mC0++1qOJ9p931uwredYh2OyzrbxsjJqHJoY"
    b"gqMH9n8cbXS6Jn7leKhjxQrsXdi3sf/jCIZ9D0dUbPs4rmX7y9Etxwds99kzsV/UsZqxMB1j8Tm6"
    b"Yv8nI8XIRIccH3BMwLEae3H2QGxbObboKQ9kZGxsomqOrtguS38/MBEDxzrsZTmC4biBox+O8DjO"
    b"5qh0bGklW/yobSInjkU4LuHI245I2A9xjN634kiOL4dDE6VBJmAkeWA8q4yAWyaO54hKRtVt49XY"
    b"C7a3jedjH8l5Bfu5kSXJHJNxDMGxEXs7joc4GmavxrkN5zkcDbPf5VwlsmJ99qPROLiXgZ0RJaz8"
    b"a0mequ5g+B12tPxVgl4/V/WR+V12s0i0KveygB/hgHcgpYADa5mvcNgpCyd9qSpsgXY7UhHYOrOq"
    b"RW0Z21kqtBtxVMPGvM9+a4fVIpb6wq50zBrc6ssUkW2xNCRS3lggdkeW59xmx9pn272zK0WbrTGn"
    b"ERHHCFus4MPt3aAkSX6RKMnfXVniu+PndKmUFh7aqGj21fO2d72H3rozgM+2yEtUp9g4eLKdNsn/"
    b"J18ym9/Ji1hz51rWPHCi/f5SSwOVnQWXA9kXzOEullcopw0RD4fyt2Q6im8bYqqetK3fO+ZOJKL9"
    b"rbr7SAJv8vEaeevRI3O4+NdBNJriqZJ9cXZunZH+leuu+8VqVZOLYWcKMjV0us7SyXKaXuG9Iz5U"
    b"nhgPLaeB1u+W/ZjLd69ov6kESm/5pGvN7ftC9Fpmr6Dz7tkzczQF2QmwajWb4A3RrsNc9nDLac2D"
    b"K9+1t80+XjMZQVbxrp8zGurZM319k5m2+/TSQnGfTmqklX3Oi4wxAz4VNYvSZxYB9brzJ/Coi5zz"
    b"JmRf7NadM0G2kMJbGtLeMDzI4uizd9DDllqbF/p3W2AsutWv9mtn3swfwSYdu0knfA+C2XaGx7+0"
    b"STIfDan0NrZ7CTgXsh7uKYLNTfHm6G/vDp/Lgxn6OyNjXD6xzqny9R7zDIwNHrhoajOh9sUSseqP"
    b"9g5OXo82ylkTWA8TnVxFF2B/SSnvQ2LQgwaIJBwGSuepQfNXvvCGLiKvMdpPhXNSU89/uI+RHFRw"
    b"+y81xfX1xb1uCwytVwXHrGlM5S/PwJLU6ad93IzB8PnPNwmdIqs5I/ArvYeU3ipxOKJ3eLD5gi/a"
    b"idXp43gyafr8POsj+R5WG6Jfr5/z/vLCqKfJFYD+IZq5KGV4lDOP3wHtIVy510l6czAdvU4ni6tp"
    b"qJWMANxX+XI6LIIdplMYcP4qmX+YA4evbEviNlRnb3/S3siFhIdHp6PD4fA0/R6kwMcLYsVJHF3H"
    b"NNHePMyioYfWOMFvdtS8Gzl+jUYjPVvWRnbw4kvvLIt9GkCLvDVh9vui6mrbKmf31p7dpTOn1smQ"
    b"jQ4fDekUDoRYYBJHUJYgJB0tJIXm8NJrzgDa5V2ehbpUNSd4hS4+Undl52CKxEpxi+ckbUgERFaM"
    b"xl5po2fcaKOy0QaeUVpS3FAFKeHh2iUnG6WkopBaMoSWq0F+h4WfIkX6IZXBka9BMm8UDkw5cZof"
    b"ujnHU9zoqxiSlZ460ugUuG53P0NrjWeGTNhXMYOG5qLcJnOdm2KkevzDmTMOuWka6P8VEDg3ERDH"
    b"KAgMr0jubG25Z5n0cak2H5eyiCwclgoS+glFgu73DLwD3Jz+wtCjFj7PpI+5SkfvCc1n1lyeaXRg"
    b"lE/n9fOSo1HuxxMcugCCpowd47r0fSpQ9QkluwyHR1XiYNNB3KLZ5QkR34mWeH5fzrQsbgR1THuD"
    b"0lNHjqEmcdp375uwI1MvVrWbcXziuap30S1TXKt7bV2IJqItURE/yC2xecawWObE5J0m+axbqsE6"
    b"VAi7ZbKBb9yAu0KT/UD73miyGV4fVWy/Brq+ZEyWaKstmaB9SI5cZF1w6ll32RDo3B/Im+c3yXx4"
    b"Kbzh8CYd0Xrunt5cMleXwFV5bnPpqyq1u+V2t6bdbVGl6R6lGvkmiFO+xTD122/FNzI0ypEZ8Yij"
    b"GL+rG4IsdXAOVs1x6K4hKDEKThZIZLd/f7KXfyqCO19IMMgj34IdpBxFtYQB1BGMbLdIqITp01Tk"
    b"ITb8k/Cv6/EPVJT5EmQkqXDovDN1C3FFwnP9W3gy2Dr8756O3teKM/Mb+r18SVqK9v/35qmaZWDk"
    b"ch1uL/8s3N768wj/f5MlQif2rZAm/Zn4hpXhN5rK+p/GyG//a57ceapJk6VA42z9qdzyzr9mLDhH"
    b"zwRHjXKy/hwz5gX0xXQrmO3JC4Bq/oLDU/XIKRH7qQyVdwv5TQkipkRZnnd6tZuKnHDtAo/6ppOd"
    b"IIcrhaaaw2P4eZoFgspzLhirspBgXeEl3TOzseFKgAWDqgju3985f3NFwK2TVNcCnJqQA/qcKn3n"
    b"4nlxhL2QaPns+rJxW2rcQpK8uSk+goWZpBc58e2CV8JTZzrnqcjx6+tKhHCVLZ/Hs2Z45vbXm7pz"
    b"v3jmvCwrnQwv4+HnV7yMXCq/g4bAjTOXgfw4Gvk1FLMm7axRP1BWDQzmoj6uj+W4MI8XtC4yh3e+"
    b"HUd5KASnwdSSWxYsL4x6MJk4CzPOqMqw1spK+N9++6jEWLbXb+oWzaksvyZc3aEufvvN6SEp8y68"
    b"dSkTEHqVEeaBqyKsvGmAsDXhGsJ8j4SS+Uwt6L3vrLpiypbOGxZpI3F/E9lC3zS6Zu5z6QARSi3Y"
    b"7LR88zqoiAVcyga46F0yG3uPPHkckHMftAPMIWQuz3FPhcWZYl3ZNH727NJb2PGCCyRi4LwGVsIc"
    b"DMABtMFEb7SDNlnOFFuLi3gurVHtsniXN9F0A9xpOQsHOGEbg5vgFaRDEOp5wUYleO2p6YF/I6Lw"
    b"zwtcZbIev3hhe0O5ZQVfvBTuCrazknEhNvbd94Z0wsjwXWMr+cAIP1WS27MF8e9FQVwpMl8kiGuk"
    b"9v+DBPHLhE3GkNDDD/28ZWzLb05Kl+/K1g9wucZ6ZbZQOZs4bCF4zcOrL3fhFreE/gJUmqK/gX9R"
    b"8Rze/HyyQRvo7Me16eIqzpJhQ0R4BZz+C6b/czT9lNCNy/liht/NiUf1kqgk/BE+qstzLGLtGWsO"
    b"L6PsNeBxMK8l9aCarlyl5JUt/mi9u8JypTKBFWsylg2RXxd8uW91xrVxiw79AUKnhbfKqGbrpdh1"
    b"JZt7b2zslbsamMkPl8l4Lj/UsIH7EnDKeFeFGn+WxePktmknE3KHl7MdsBIdZ3mOuz8TnXM3VQw2"
    b"6vo2Qto/eu/nALx+W4TjWoOycX7jpcFveekWrHDPuRaynAZs/vKl6O2tXJns2KNI/noDOe0pE1Ki"
    b"4ozgNGNDettrid+MZL0U7Y6RdN+aBalprzMjnT9oRjpfNiPt+81I+54zUsLqXj2UiL3Bq9dBofBT"
    b"aHQnwSwaqY3kTW+7pIQFkogXjJu9qO1W3ff93OWFsQvVqvbsGeMcD/fWaNVul+RpxlWt8DaJl4ud"
    b"QMCwdopWloCW2Hry7NIpg80Hc+pttlDjm0Aco3ery4bYqjaRb169eQP/4UcckyleNjGKs4JH6toe"
    b"iVO4BMfslCKLtvycYxL9iITeSai8d25zqmKUNOc9Dx70Fc2fguw5XbzmmPmaLC3if3Cvu5WVSun+"
    b"TrxP8QZQcCPqk6GzeJjbOZ3Dii4j28LvbySkBC8VM508zOuDGL90EH4qemU9npX2qK+SmW6FiJgg"
    b"DTt5gRpv7AuWNdD7Yg0G/OsG7f2kj0oDt/gqZGf7eSg2kRtndThiZxyLLIuntEPMi/vYHrfc4IX2"
    b"nXZb8D8T5D1VBD8VH3FTqP4eq9wYzKaIv4MDapFmyQVdw3KQjRbJNJVf4cNvJoo4yiZLHgY/L/n4"
    b"Ik1HYBLTxcXlY/qEFH4rePpkLubZEocxI0diEKM40acq1Td34iV915A+2jFM8RLzW/4qYfQZy17T"
    b"C6OeaidwMXTsFywJTIf62pYR5w2rKpFcDaKJdbu8vb+Ed3hQZGmSLDMJJiy0al01uzHuwM1VF+aV"
    b"JJ0+16E+LQAP8/l3jkGxh3kh3K0e+D85vVazvYJ/ToJ+EnD6PsV5AcZnfFny4+Qx+rNI4LX2IPmj"
    b"FEUDh2gW9r6hPu94imWX1f2x6LMLNFFTvP56FuW5x+lBeWzuR+W2AT8BNIlxzIsol586xUtkXWGs"
    b"Jc24KSb4JSeQVCQdCNHph72pLwluM5JigJ1CiByMRtKF4Ie6oOWmvp1GDJbzWNMr56x44sK+T+iM"
    b"96f5x0/oriMr//36aufb9IbQa1bqUoOxfgnGte07PXrzrfByb5m566on7ne1s/h+3V8HYGg45nYh"
    b"jQ/sS0/qxSQ9mNWH9rSH9x1Xlu7wkqPk4rKSWTtfx6zwvvsdZ9Ozz64SVm2X8ns9du2s6rviGv3C"
    b"Jvm1F6++YI+kV+NYa/nrc9FTrpfmmx7OOaHCrspQw06xYedh9lIbHq36foO98bOwYxerK585WXCT"
    b"CBQH/JKDHqceXgArHa1zj9HsAzb2kOrEASLinM5BVa4I4u6B1O+C0t2910zLJ805YnQPnhrxtjDW"
    b"+2KruFdWK9vzFd49f1Sl8P4yX2lVci0v5pamXJNrX6uvDjWeycYW0ViP1vbWr1nv7bksvi1prFP4"
    b"W0CDchjfOMtYwjr4w9sd9op7KLAEkAS2QbhBVmADxi0uDSSltWuEvaRjlSAEuwXv4YN3+i4l6EeV"
    b"FG0zRZVtlg2xXd9b7UOs026VDuRBd1b7WtotqOcnt5K29GpmHMdgiOz5+U+u5BSdqenZcXsuy3r6"
    b"p6CWlF/bcQQesugW4wd/dWc7tBhoYDpLMJ+KAYHV1B36tiTUsjpsFztVdyiu02Kn7UKnuwC5bSZ3"
    b"K0Cue/qKBgLZck5fhZu1udntGk23ZNMVzW4N1K16NUEdJqh3j/kjdnWqedz5kpnsPcxM9gIzWWEh"
    b"9PHTUhvhW4dV2m+tT+4U1ibd2dpxzZ37Up+drWq0w0f8tHrXw3GDpav9wlx7BwcbFpTQqUILr4qG"
    b"DdOu7Phh2Une8pl4SCMd2l5T1AN2p4WkyyW2z9q+XaGX4Nj6nuoGUigrl3N0brtUD1zz1w8qTaX8"
    b"yyPSD+whHzIo2/aDMn3HixuSofhbYRmdo9y5p9PyFbgrt9kWNhUykm1cG8J9h+22+E4T/fIlH8Ts"
    b"iOeAL/5Vvid1Cxq65hWvurBVuh0ymxaEYnsHHA0QhBBM4X25pe4NEUBqr7JfsUNDMCrrbbgNS6zc"
    b"51t54p0Ll3Kr5AWj8yrxg2VZmzcXLGDRjJca2l5ygovf5dsPQ+efP9vMJnXwH4SE37JzVsDmdFu6"
    b"L0x16UhXTEa8kQLr3lhDxGp7bi/R670DtcIG5GdeyaP+dVuS77c3g6etmC+eJed75SWCPmWxDcGr"
    b"wIWYGXUUr94DNcXSayijqrzYoCSXoQVcYDCVo/GzhGKW5sncXMjCh0TTgMW4LlqCW3srRoVi3lp3"
    b"DNkgPxdBqlQNC9Kt0GtICvxRK0bWqWFnL/AGpf2bzwXUjPdEpdoOYxGg3s5adkOv7h6teiLJMDzQ"
    b"OhPCYulu76rkQxkXSnmwkgMl9FO63N9bTWpVOo9m55trt2zrXGzlHZxYGTJYl7I8WLhseeTd1aFp"
    b"/wECXDeG7ZfGsPDytmS4e8T4/fII3eGtbP8Avq3g1AouTV2B83vkPOE9md4k7QP4YvSlv+xeYpTD"
    b"JTFLOpbrfa73kXuZjnWj0n02sETYwb4zbm1fRz3PSm4lkZEJtdkrbLSRM75KSpxQGkuKy6KvvTW8"
    b"wolZujUpAuLvAqZ+yz3rz2fwN06O/YwWr7xGt37kpeFr6vBYi02XwdiURguXprBB3tpyacGmL0Gz"
    b"+djYt9SpjNG33teDN8VTuQ7/FKKneDxOhon+irl439Zf4njfMb92nwt1rfH73nPRbnnXUpLK0qWU"
    b"9Jt7JeWpdSkkXgcpBkv1xXVqfedcMYkXno3isfoCyZ1wLptUV0lm6QySO4DDsdSdUMvAp5fWp0+s"
    b"OyibpT35akXuWXr/5ebDfUQ+ubqo+oL8KSi9GMUzuhETIEuw7seT7+T9dPFtPFzM45H84GuUk83w"
    b"kcvx76XAdfokzs3nXj+evBXjLL3igfFxxvBHVd+751Fi2STPhuo90mteFMmUOKsx7nejraLcuR70"
    b"CC/SU29A+MznptVlof9c85vZoyy6CXoL51PkQKz3Aew53XoDjKx9wVe6S76VHhjyyZP/id8Ad6aH"
    b"rIPzxLUS38fjBKwS7puKrqNkQh8xYrMhDWQ0yXF71XScXCxo+/1lesMam9M3kVm+R6i+KIbzKMPt"
    b"Uil/yMgSNjYl+HXjhohA1cbRYjKXqg8Sj7ovL8QFYCDsNzFkQJGyDVk0zfFiXRA4OmVIzpU/Xp+l"
    b"E4GzQYiZq3B5VO4OyinRtDE6GotpGhgAWmtM5Leao+nSwk7xB3O0geHAKMGdM5Nlkw6YWSy6ihK6"
    b"alrdyZtOi6wSyTyPJ2OkPJJfaVjQRjhDkZji6T/eHx/LHb6RukJxQUtSwzSLbRJ/YeQVAJsyHAmc"
    b"I/yOc050KqvHU/UumoLYgNFTdGbxfyySjKc6mQ4ni1GM4/O+MWmGeFht7vmeT7SsKGajMOXUCLxF"
    b"7tMaugRZ+Q/iBV99TL8W7z3m9oM0ncTR9E6cGWJxFy6by3m2iJW9THjjqMbdxtnGF3h4iVsICzzY"
    b"k7MLULKbJFcmeQwapAZxcXsKWElF+CtKy7kkyFWOMsp4lv6Tep4a8QWY194jBbco6g9xWzTjUXZd"
    b"NE5OwxE0m+KG8HFVFtO7vJXmmGUMxMmR07v1LnOVglO8ypWhBO5ynfIt2FMVWjlIgWbhPBsFkEIx"
    b"iJVcaGlfQ6K+ijIl4vcgzcwHEPiK+9fMw5IbdF25/Cqcn94HW1ti8AZl60/n6ldflqCt/8i98dSm"
    b"T7XJ9fZxNpOsxARHWYo81RcYS8+lXMCaPAHPE/JslxHuuAWLbUYvAdigjczSLg/BqULTxQzlKjUQ"
    b"1WhFCpriWBmpRohAY/ExmbFdW2FytSVTAf3cC+gNgSPdSyZJ2A3lymoiuwLVAbSSNRx2s0zuqsVM"
    b"QbNiNxrHDeDmjmyFhW7PypFR1vE8gt1tH+JKNcYTO+lUiwemMaPQoIFKM03rTno/EmRKKQTkX93Y"
    b"T+0/jwIToLKKSj3gCXZlX3k9duOqJZjA68T/rAHKLW54FyWe7NEXipjvItWnEmRPV5M4X7xMhpdB"
    b"icv1leT+EGUyzJiF8lf9wZHFPAFfuRRX4ELSUc7GBANFcMTjBeTPlxluEE8Xc0J4kgyyKFt+7bdI"
    b"PtKomIqu9zUSJR6IQjTI0wmkvEo90X5dJNdgqviOdN8uUDrN5JF2ylRY0EHiKVY+0F9meNiABYd5"
    b"/y6aXzZhLG2HKAOJ8c54DoWBT4guh9XaOkW5a+qwiZ5Bc4bkH6D+ZQZM3mbviBg/AyTSvMCBRH1p"
    b"QyFRsG0K4mmQfQFZ01xw0B+HxbKU4Oaa34jR5lCLhWMQAeNyU2hbHvHNPk2J+E6o2VPNn9OL0hRa"
    b"ydeNjKRC5objI0X2JSVHOpyiBCjUCyM21Sei3Da9UR+7ETU87J1MYcQED3trcGWSoQpiMlmRX1vh"
    b"PzhJHl66YZ6WDTp+Y4nGihQm9RKQMBAlXzqxCWYypewjXng8LHDtgYQIBjy+sTeBMD4NIrcgTvLb"
    b"x4DaPEXH2eTuP6n5QXfhQigVrQM8crOB/bgUJy0R2Y9Rilm5VEgwSiAOlzAdhelXfMajR3cPw49p"
    b"mnobwgK4rwhEWXgsD7yYzbAQgte8sbnMYqw3oL1E9dvIo3FcJttKEuXFCiyL1i0LbmjmDFbgk4IV"
    b"RLMMihFVt0OS050Mv5d1m6cfEYXXgIE1H4xCQS4lP4yd4wdNC0jNM3ZeHKaRoFBM/+VGY1xuAa8J"
    b"qU0ymxTiFHRkeBzQChfwRMt0xDyVaTxW+TUEtyDt1LsPJqAREGPYJRdKTxNeMUDw+WWE1Z5BPL/B"
    b"pIRT1rxhwi+/uuWWd0h+r/J4ch3noUoOE3Z2/nt+ycqpZK35RSsv6fXLomXJuiqXrZf/+h96Zxgv"
    b"S7NiCT2QHCus9sGayGxYfa4KED2Mhpc+pV7NW7aWX8iiqse5/uaVMrEmB7mrihWVLzclx7WcNNZn"
    b"FZtX2aoSr+lpCwdt8W0C0R+dGc6/yp1GU38AAp2X+M89UwR0AzW7Frhuphqceh7eMl5Bl+rML0+s"
    b"NGMrozKTY0kG32c+pR2QrCRroF9x5OQkhA802xLdaXDc8oDdi/NkZc6J83C5zor0HL4gWqOCsV6Z"
    b"Hsi00QHlUxWUrRICv0qaLpw1MS7ZMvRilGZDoe0itaKU6d4rxSzS1xBAdKf4UDS5Xy9Q95heawVi"
    b"k+dnFiUZO7sVs+qb9acv7yAYhUD2kpaqZFymxMaBrlhgKP4dZvlgYt/Z6k8xnQylarf527gXe5rt"
    b"FlmcY1HY8j9yywopbKI8Qe5vgLeiIhnqK08sw3t3Yw4Pc6bcU0AOq0Sw6ioNhlwqqkcYE0WT5B9y"
    b"gaosIFhLPPnqCFqVs/YFJDyEjKrUwKj/ydQY22Rs8mIe2ZOKUPWFSrlYULqhuzHwiD87tKVtwHI1"
    b"WAg8p0wYj19F+IGPwFpxEINkep1i8EcrJErunTWEnNjBcSe8l1kpcoU+nVptEVzP6nJ9EOOlGnz1"
    b"AeR4mDriAIWADW/v+Lec9MKxtx4DAMuK0ZriALmpwlYVnas1cx2fW4suNCuXeB2LXj/Sq0Y85Umm"
    b"lovUyO6iKkEAsmBe8RuKQ7y2IZ+l0xHSaRdHedSiYaQ1iOElskBgGW5SWPkuLjFAeDfFzZqWF2QI"
    b"ZfaK51ENaTGAudUQgwVWUWCKEDQIGl68korrJFLCQnmFIv1JLrlVbeVd++tmFyG7a6ugm33AaPdx"
    b"JE49SEEybiPRlqQQfbyRNvlOnDFHf+QpUUu3ymarKLZ0PlIKVguctuapQpJXFD/IjEDaQxeF3KEE"
    b"BbVlqOrcEX5LG9BKRoVV/S/1YchCu6CkHAaT0RAO84wDsRZjnBa0jzu8HOO227eT+CYWcoKXOnLo"
    b"lJrFloIztL3oGh7Rbh50i6lafS9GYc7Gcc9f5tpfKnSb7rp8wXsWQMgNrsNhnOdppqGFZ2L1aX4y"
    b"wsUJxUSsPIz8IMsMf0SqAqpXsaJ6fxdcxGW1n8VFAnrJW7bkQ3QIauBhNEUI1YY/vNJVXH2QwYqf"
    b"mHAd3tvCpb2d3DLFxVZuo4bmpsqpUL1Krs80Ea3AULT7jMcrrvvaY1rOiuCayTIrc2SbyV5KRCLc"
    b"mQTu5Iq8jLdttWQ2s8CyhSN9tBNrsqRLzGgfV4lrxNFZSUa864vj0IfPiJMKb1axqqquxypNcsN0"
    b"fZG/DAvkenjcs5TzhVN0z5JOmav0ql7aPVLsRcGSo9UV6vxF7jMPJPrXjsEPlpDIXYRaVxtmK4Av"
    b"LOy5IcO9rLAMj52Q17Ew+X9/QqRGLrXX6xlqxEoZzXJ0Km23mxlUWXLXSlca9FWWvFgvrTLk2ndV"
    b"2vM/zpCzHi7LDHppskNX/NkmXQ1bbdm/LGn5PRMVG9q6BfKvY9cDmdf7ZSJilb3FisvX2lu35ObF"
    b"t+XmNhAM1/cKZ/uqjXmDCwQfp9bOTqfYV5k8WF/P8teNhDSg0/iGb42sPTly2PtcPMFrwcwivYn7"
    b"LYD2NlT87lYFtoER5b7joh0NDl5ZxbazoSoH9+uq+azkuEV5Htj4R5JemlXaFVdlYvZVn4esuuJM"
    b"+E4/WFkN0ermpgZPtBarC7HKFlSdp5TpZmEKVpYA6CbHOB9myQy/TrVvYXpRciSoetnDHTeU4Trn"
    b"JQsib49jEGtiuLtfuvVKQVtbgP3TrQ531AZTqd8lx1wLMikdFlfn1P6cmuK/tY7csAirF4+dlk5i"
    b"0SzS47Mnv6Jm2wvVlSYxzBFHIshDveeN/gXozjrIZKT2n0tkdNdz92bNG9VOQtJhS83fMMd/Pw8V"
    b"YKxz1/5oeCRBDuIff9WDY1lLYVy1N1gKkLVFWD5x96a8riw32tXG4jqoMgJgqiPv4E95mZeHtWq9"
    b"JXuGJbb/+dqW6sp9w+hATJQX2qscOqO0xrZiYkKIB3Yqfhk5DCk5MBeov/pHYcUgypMh5Ba8swVp"
    b"kcN+iLPrZBjf+bt/zMLEFX6hnqJk2pcrE56v3V4sx12x10Zpn/Iw1EdtXlmxucQqc2gieXc2s2G0"
    b"VsXv6+oreuAVC8G63Wmgr95V7uBdsQuzGO5O06+HWhbPujNZWEOWr0v3ntC1wdzG3L0jJzoQW8pX"
    b"laGeHFJtCwyQiXDXiPvkYKvrydXKpJbWJAZlhyXsYg+XLdzcRmITPCTxUBJaLQz+ELqzmsCNe3Pj"
    b"3mtIUUiSowmEe6NlqX4j3Q8s2nmZaDdEQUb1nSKeZK8rxYq8e8kwDhrUliIeeNeyLeruJSUmCnD5"
    b"QWGA+0i3TL2dlEiXF0PUzniXs34Dj56YL1o84cWchnhycwmu4Um9Udn8AD/Vpvu0G84CXDTIg93l"
    b"kfkwbPOdDYPKYAIDrmr+RajQVRhmoLdP3G7W7uFg96vkKja9EzzBvzmbXoRRnUUjrO7p9nykZx0s"
    b"8RoBQ1mrtV4vCmYMdk/q0OacBNYy/q6s+JImP0eiI5rDKcZOua4B6gs+IvHzCX/exXxamGtXdGT8"
    b"x9N3b7eCF2egVeZbL9T2fm8D8s8neJOCuuPkTsgdsPn5qo3IARs2XZbsHKFt2lQaaX55bMWYrrl/"
    b"2dHUJi6YW1UKsBX8s7mYjSCfbg4SAEWbe1XK4d5U4ULDvFcrmXMw0er1QTt/VxKaJniwNNV05+kz"
    b"F19gJcIF2UxyvpGlJp/XIYtSrZ/7jbliIDtY45AyrRiGrsy4xyjcvu4cRx46l8dIPXBvlAE94Cnh"
    b"ts5yt7xMzbtsBWF4N3xIENSyoajb1/Q5SPGs11bv5LbWbpQeWBua/C3wLKCFve+4L0ptPLmKRrG6"
    b"JESf3JOJIFX6ZRUvi8cTeKY3Qlkbq9RpAsHxVtkaUKEAXXq2J7xdU+1IpY1n8nCr2lK/MsJgTlRt"
    b"ry0UNwoqhrVfS7W+fnkN14KixTy9wkMytCOO5SAPTaJbzi9lKu9xW71+zVsBc3m0LR7HGQqQXINB"
    b"OSJUKMpT51b0gsScvsQ1T/h+j4i+ArWYTmOsAUaZoUIeUdHrSCxyZXG0b/erjp+EVkJWBrRrOAMU"
    b"4S9Z2w2JV6jolbuxqitiheUFMv9+SGmbiuLNgiX5OVsfec/Vkc6MpOuGiVfO3Fxuw6zCeOe+idAZ"
    b"dlLe+t3Ru0NBh2vUoIRL6Tm103JsJY5fNhv6biprThDP8FIP233rQitsil8l5Gs6kqpTjh8rdHiw"
    b"VDxHNkfkNpzb39RHeHWEFKJ81WHILJ2TqV6PMyxQpbdj0XcIpYeTN9vV7K8TQzj9nNlCvzf0K4pG"
    b"5Sv6XQmsf3ml65CbTHqNxtVSHvC6oYbe6oQ1K6+Vl3Tuawtn+t7BPTTovi1Wp/7KdGHNjF1uG9Ue"
    b"/AGydFrM12l6PLXjAzdRr9z1WXZykzngCpB7XNNPhb1o0+Tzqin6Viyh1+ompS9Wx0OrG5AO1Rgh"
    b"cz5ZTz6L1XPzpc2n1tcsbeNYdb0fFzrUVgeWOFslV4RcWjJCh4wqxm1aveyJqdBmegU+DEvZBLLw"
    b"9cvy9TRnldtTR+h1yEiV+RzSyrX5XHoV4u/J5OKgX8dhy4fdn8GuFavgr1cVYmR+bf8f/Doc/7H2"
    b"3aI2x0ovF3UjsNI7Qs9MNWj/MRWNHp/LK0OtD6UO00maeXfRyDzDdmfOCOpyjjOv3rTfDgwQ4Zt7"
    b"DoBXu0kBUBCVEFo2PyyEXN24ipYiTmhnEo47DWpxKhe7fOFr2iPWIBjUBzkoWx3RVUpxPKq6ofXM"
    b"FMD2H1OdTHPf+gDzV3HfK7EZ7lsDfAn3NQkUKew/fqsx5/1+Q/2RU+fG2nuDx/hs/7EuzulRTCxa"
    b"OtkceoYizjCrZIlPjSD/9AFgzjxLbuNJXgEKa3777VZLwcK/VSK5BhxNPcVa+4811YFrfO0zbA6N"
    b"m8rWqO/RG5tTckGpDnDozs9I3Rt5tcg5hYrnKoSquPbgKxY2vepb9TKlWZcxvkQFTqXBtZ2ZKGIr"
    b"Q6dokBMnStc5CmWI97TE4NxAEl4RsJcC9rylZ4Vb4abl0MXKqzkuR3F4fuhXEjVa5fx/TaZN7vXj"
    b"qJnrx7Ku6Ppjs8vWWyY3d0q7SNyJF4OXKG0vNgcvhbr+l2dYby3mqDfJ6JIdWZQZikl6kQxLp13G"
    b"D5D24ElFaZ/DON9DAlzkXUGwC6Mr76MpZStbsP9RXA2i/KBMPeIQdQVPw7dHB/XTrRnosvlX3aol"
    b"gdi3b0iB+9NMo9m8o8ImzmvdIOpr7sYqZ8Je5RW+Dyw2akXDmnW96vDPh5vfKcv+/+75lUz4g+fX"
    b"NwnW9Hq+14VDLth9tLf29xD86dNXRVHFPdfnSSIxwEoPCFI8vU6ydKot49r+2x3KceOvGHbBm/uE"
    b"3ve7AeUOzDWXo3S4IIK4g0p/n7CeP7nvxwNKTfx6o0J6du8hK82DO6xSHeWlQRhwcZz7H6pvDdxz"
    b"9HLhXWtw6u6O7cl8UERI9INvqB/lDE2Q4hrWiksg1OrFggZApb70QmKu3sGzuzr12dz8N5GniwxL"
    b"ibMZRLcfT97uy88ufMqbV9HsvwBSzkj/"
))

TRYSTERO_NOSTR_RUNTIME_JS = zlib.decompress(base64.b64decode(  # generated from trystero-nostr-0.25.3.iife.min.js
    b"eNq8vYtf2zizMPyvhLw8ee0iUqCX7TpVc4DSlhYKBXrlcKjjKIkhsVPbAdLE//s3M7pYdgK7+5zn"
    b"/bq/DbYk6zIazU2j0Y2f1E7G47NkmmYiiT/GaZZwx3H5q9kNZB1l/KhzJYKs2RW9MBLHSTwWSTZt"
    b"YeY01pl9kR3dRjrztUiDJBxncULFBvcU++iPREolOqbEOImzOJuORXPgp1ZZKnYbc0ewDPvWixMH"
    b"k6JaGNUy9yiDjIjNoAEvO48umIgmI5H4naHwVjZyN2fH8lsolOD3Yc/JGg1sKO7VMs7rMbVfn8+t"
    b"tN4kCrIwjuouNjcUWS2uQdYgdjLXXenEzcAfDqHW2G004hXOo0aDOhLLjiAQs/O43Bkn4VP4Hr5x"
    b"5/OkWWTlbisR2SSJaiKn0V7HXPBXx7EDdc5yVr+8FOlh3J0MRZ3B3AwncmhMuFS8F/JZ3rqNnV7I"
    b"ZjBZ/mSYnYihP/2cDFPqy3bGumE6jlNB6adxcC0ymXWaMegxJb8T/jAbUOp1ZFLtwl8Eu4rD6CSO"
    b"R/QexmzsT1StJyKIo0gQ3Cj3vWC/Jv4w7E0pX1aRxiwRKQx9+TdfBUvFsLffpbdvuRzhu0hjSS8R"
    b"4rdwZmNv46737/0T9Bts9SIW/XUtouP7ohuI537v6Qt/40mn0+tuPRMvgu7Gk+dPN59uRmzgwY/v"
    b"bUSs4/0Rsbd3UOsff3bE8+d/iN6f3aDT8YNnz/yN51t/PgvEiz82Oht/bGz92ekF3c4WVL31ovvn"
    b"sz97Wy82n3U2n/debP7x5wuoZgrVPH3xxO/6f/yx9dx/Ejx9/uxZ13/agw83xObmxgv/Ra+7+Ufn"
    b"KXTs+Ytnz55u/vln8PSP7saLXq+zudF92nkRAZYArE5hiXjfBXbtJsaaT2Po668o5+8ACII/2WIf"
    b"BH/+lF1mfDaedIZh8EFMvUisbTLz+jkK4tEYJi8VXe8DZqVhP/IBcQW8wrRBMnwRicdbOfsNa47X"
    b"6yzje0kS08LDVRTxSNzWYKVAtwJ/jN+eZn5wfZb4gfCSXJZuZYMkhmJyPSb2emw0Eidiv10W5eyM"
    b"lokAOpBmfhRg2c9hlL3YThJ/Op/Tn50JTGHSDNMvobiFZhsN0QSUA1I3CYBKNSOgRBwaKD6sY5Gd"
    b"72d7p5fHeyeXewd7h3sfz6DMJvOFoiQwMj2ihJ/FOBzoS7s5FFE/G7CQZ0ATbuKwW9toAb1ZSebz"
    b"UBKKzKWvUqQYP+ursyiv134yn4ftn0hgZAW11VmW//QAfAFP2j9lIl+dxZD4E6ECzwo4Iv/Jujxd"
    b"q4u7MawP0bVAUF/z1+qs1o+zWn0t0DQmaf92uuzEj/pCTo2H72dQnXzNDS1i3wQCGGesqBTH+jHS"
    b"1Fg0s/g0S8Ko72w+d5tjvwvTmWRA5eobdZddRVgBjTgDmLU0MY1wrL6AutxsjX+MYEq3DBHMcjYQ"
    b"fHa54T19wS7/9J79wba958/YG++PDVhmf/7Bet7mBuDYLtUuXvGBaF5uwLS9pKc/22KdUjyZta1z"
    b"3kCGgwnrmxuuyvR1Zk9l+pQp5459LvV/IO4A14D+ht06TqueghVeTwkGdVcN4TewiZbEd6GRIuHR"
    b"4y38LPrX1kK5mH8TTuIaAIV8g6UckOdl0grX1li6xrck5vh8N3IAhwd+sht3xXbmpK4LeLKQurbp"
    b"uticzzUqzueBeS71ID4PL7j/aPP5WqBnP87ZDswyTHF/GHf84dkgTNvNIJkCb28300knG4o2YFJd"
    b"JqmU2miSZrWOqEmRoctquNbCrkhq43g47YXDIWDFKiyjZrMpXAPajVaJzQrECkCP2FXAU7AEGGUu"
    b"AHKheNRMReYAZ4HcNR7rr9RYgFT8ypAeRdikszggF8UTWBHdePQFuWvqfCPcZAcZ3wn7+1HGXgsj"
    b"RPB6x+/WgHt3ROLV4kmGfUhwPSFRsJCiE/Zh2dQBSom1vrzsJReIdVFbeJhlLUW2R63wU1EQTPGv"
    b"zAzkFd+I2pGXrcGQJhni5h6U/w5L8qQQkBwkaBsRyDMv4Q9QPJilKEbMFUkqoMb6mlir10ZxF54M"
    b"nu7R5zA6EFDgM6BhwNRS/PHhlQDeilaw4pZERCBNjyOgPcm/Ijbh8Xr6KGBDHq77j4DUcGArvAs1"
    b"pVCRD/VMoJqhRq4EqWnU3oMZy5D8WN2rg8D2wV51R/G5uDCkQUloKyWOABWAyDgQaVOOLAKCB/gA"
    b"mAak5ChSEwegAZT6AMvEdfAV+B6rd8O+SLHka6sYSJ6jMBVNYHXx8Mb+xm1mAxGBIIdVJaUapKDy"
    b"OltgSWeC5rl+DIJTVtNkGpdBJCcQIP9IuI/E2i/o1CUlvgb0YzAJgAdsmJmUTZmyHdspOPsjKrPi"
    b"iMYm1PGe6ihIdjPuIdXeo8/eR84I+W97y3visq82qFcjZ5gR3kcwPWaNSZRwToHjR+7jp1ErfrWB"
    b"P6+gkBtDi42GA3z9UfIv7FzCE3rSU7bnRI8iFzkfTVT6K8kMEcWOO5ELGL3nrEeuFH7PBA+GfprW"
    b"xAxgmIVBbWf7dK+lnn/snRy1vrW+t360LDbuSOl+lsGibn7jlxHSCXr5zofYhHz5gTmwysqyJGa5"
    b"uap/9/PJlz3Hnanev4t0Rg+QYruHVM2RPHx250VsijJLsT5p4YGIQn/bR8JD3imAuyUwU65d1c40"
    b"AzIDNflC8QBb7rpH6IK2LmEuUL7QXCXl2fnGBSyuDEmwTxx6E/lBL3N8tgEoSkwg5KSjOCn83ZrP"
    b"8c8TV67jLv8aOYHbojQo0gVSsN51UaKRvQ9Yl3qvBolVJY0GFn8KxYtS1CIsiQ+ABVAeKmjHTZhI"
    b"UOK+4HSH2dSh1Y7kc4yrwaOlGke1YJLc4NK3APRO3CF4tDDSLID2GWfXzYFk1+6KmaIJzmI1RW7z"
    b"jgpM7y8wzQVqJ6mezm8A9u9ewn54MUwpFGaQFEJSCkl+zl9niFQBR4T2XYZgCh/FLtC+PSfBlCE8"
    b"pJCisQGZbbfRmMCfYR6mG5WuqNaPhJtHou9nosiXEJXIzGA2JCZrJHbzbgzoISr1+d2uQmV6+meD"
    b"2kBK/gsJOTwN8aeHPyMYUvfRE1g/Axp36LIbGm7qsjN4iHHcO5i1BsuqgyBZS90Wpuw86siUwdqN"
    b"LLOzrlKitVhynV36wDcQw8zOo12X7dJ3Z7J4Z12lJGsK3Cl8Qym7jyYy5QYLU8o6pPTgIcD2MWv0"
    b"6EymTNZ6qvB6T6bcYApO2+RRT45ssDaQDzf4cEb1qG6MsMIb3RZmDdbPKmU6mIWgusHCWPMQ6xlQ"
    b"V1V/dnSfJ+sqa+fRjezP7iPVsR5+JbFgwoasBysD5CvQkTJrTZhZp0lsaiRy8xHo/+F4OEWqyFc2"
    b"XDR5rMDqz4gsacnvSCBh2I6JVBJDdq2KSb610PQS2ILKvsJPmuOW5A1HAgjFpbAkV/o8Qx4R8rCp"
    b"cZVlkmFkwDDawCSo56HrRURDYvVqUCExo/gcpX5PVMdtjXFl082Lda3QPgMcjwDHE4n21eEcmeEA"
    b"Gd9AOr4R5VgosSEBeRlkQY6U0U9iYPrA5ArelsB6X8EviLlpEavgb1DDnpMhmZh6uIBiN8+rJFEx"
    b"E9kSr5Ap3dSQFqrkZZKlQkdXkRK28YuHyWoWK3ZD2FDmXYRElR5Z7cPk9oGBFcpZe1U4ezFy0dj1"
    b"4BnkiafwzPqov2BTZcJ9FTlqRJrjAQTYpSCucSacm5idxsgu2JFJg/kAuQYwtXUGmjgwf8QveETe"
    b"D/hGUsJhXMhrl6KCDoRMVmKEie7CMNkB6bcHmVPfuKuvOVco583nqLnCMsyKBg5A1CrYKwmCbDfm"
    b"W9GjR1vPnqOpjASuyAFNVotuuzDnH1CW2oktEQtqQrWXJMdUBACk2rWY1gu8h88zKdWxukKjWlGQ"
    b"1A3UpyyVQ0pNByDWn77bXof+1NlRzGeDkR+cDnx4306nUeD5+KtVBCny70QOymv1d4fbu3WYaP/W"
    b"DyG9GY7GcZKB8OHUE/+2zgSboZkE2AiK2Z58OYhgHlc22XkdrUD1CzMCUJ10RZgDKwalfBDrix5p"
    b"9Tqt9q8GkDLfY/eaUrx2DiKGsEztz+XAX0vwwtLFSdDqbftX5lyCSCREFzR9RqYGplXxlypnPtcp"
    b"rzY3tp4WKnFhTHn6Yh2zOnVbS2vJudxzDqja72J9s1ggsA4yFJQByalnmQH3a6SbqthMzmlF2PNw"
    b"peVyXL+rQjwKQE59Z/9448nTjceg6QDVfpXZKv8GQOgN4IE/uauzT/AQxaCC1NlbeIRiQxwrvO4T"
    b"ZoMCbqHCUQSiOQG3zn7jMjDjsXNWUZSN5KcwwDu7otemHM2nrkYqTNGS/FJlLvuYWctkh0xqES+t"
    b"bKKmCZAtEGWiB2lWyEGviIEyepMMpCfAG07kSQO/CyLQ+M5LAYOvqFkodiA1/i+RsU1cZc5+5ryl"
    b"LmLWj4jLRVTkS0S9s0t9o3n7iHpUc3zHDoA5xs43oG/fLQ2TaPAYR9PF0XzMLMwYeRJbdTbzMQHN"
    b"tEg5RWKB6QpbaWVK60DtChZcreeHQ1AWate1MK39FklcV/oFEn1SIqA9RFMzybMEs64hK2e4B1Ts"
    b"lqwiOYKyACCxBioezlQEJMOQJm0Bro2TuDsJQLFl+5o0c1iE0Gs93hGMB/oQMwS/D9Dn3yMFEdBf"
    b"ANRvIpaiMArthf+DlNJFMRsyPkUsYGTdwZ5OoKfDnIvE6aK09CUCGYkyRzwDGYRNWI+FBn9BLBmB"
    b"+hUDYf/tRFgKEDfmhhz+w26aGV/eWZP9YJdlqR8Pd1wWSpd0/52x9ZQMDcps0RZyzWWuR3b2pDSh"
    b"MynJEBP6gExIT2Adlw0qo0wR5/oIlE4fOQwsH4WBrG5oFSBVlkyVSRLGT8AATZJUI8XIfYABkMJF"
    b"xjtBsHVL6hqKyz204UmdFfjgUNk7iNz2ZKZULzG3p2wflDvigKhQ5RCqtkD4DuQUZ4RC9isl9dwA"
    b"+TjL+WHsdAHYSB0Grrsobq04K0BBzgDoNyDdDd3czQM/CwZKqlnZhIUSJ8V6ThIF4i+AJGliY5ed"
    b"+wNyP2fVrSzg630ReQcoQ2XHhhd8i2h/xduPGUiVYQ/oXkIpkl/e6WT5miY5AD7jL9gvEEyePWdh"
    b"wg/9bNAMRDh0fsWPu5m7tsneZXzr0SOnm61vAsmNycBLcyj4+QUwlEsQTXhmmX42WsnLMGkla2vu"
    b"DHKAh44n6QAFQmOC5Zut+OW7rBVDmQgpM6mfVskMErUaYO0u7EfszmwkKD6UGTXGbImivRPotC1F"
    b"7UfzubMf8Y+xQ8Yq0EES7HqMg+tmgMgx4CzIdTEO08cnGL7pMai7rQBHFeCopA3kI5lzHdEA9VWA"
    b"puKz7qt3GZpD1nnIxBoqBYRqEx48epcBssJq5ZM1grHfSWFhr2/CQg7+tYVGUkC57suNVhdJs9F2"
    b"7iJYy9n58MIFtUcBCtIGkNaDNAOaFUPPNZm9jfxenXbyQDFHMo0iwqw3jOPEW83YKIy8zzBk+PMB"
    b"2An2if3gdb2zD8KL0HDWezhNtMU7ai+gOfLHOGWrMa9vbG49efrs+R8v/tz2dzq7wevunnjTe9t/"
    b"N9gP3199uD4YHo4+Rkfx8fjTr5PkND3LPk++3Hy9/Xb3ffrjd50FJAufIH1B5FqNz1czh6CUkIHd"
    b"cR8933Iv2u163W3iZrIDD+wbD4SztQGKhODa/AoCS7MTRl1HJbjsa8aVBfgW0uPbl/VJnc1ElCWh"
    b"SL2RYCgj7anX3xmDlZV6QjDaMk+9jsjV2mNvJebnbJyBbAQdC7uAdXX2Djvv4AxEk+Gw0QiGwk/O"
    b"wpGIJ0RMMdVlv/S2GMmDzs/V2Y/cq63ORP7TZbdiKXWmori1qMhq2zx5esuAm30kKNcW3hdHtNuo"
    b"9T1QIxT75dwKynfZ+1iR3rtsLwpAKkzY1yLptZBJPZqi93FTUBkSNijpa9zsCp00pSS0giNfdxxJ"
    b"y7K16J4tvy255YezuV9s8Ag1x/8Fyb/jymo/x0IXsHYNGQr5B5CSYVk+2hRPNQkI1wGFQhA4YSh6"
    b"a4f2I2K1FRFyKJAAZsXr68itovP4ooU/8BReMPzhaV7sBvWzYjMHNEM5yqE/3Y2jXthvNyfJMAUK"
    b"k7R/o79GBjPf9Mfj/S6s28xtpkCgQUlllY8QTlEX5mbabgOd/8Lfnx59bMoJBTLNugTPGTJN1RMq"
    b"MPaTFOGtGIzc+f7l/JRSXC2La1SCCmscQzFNDkHRrebh9rfL0+03e5f7H8/23u6d0JjS8TDMcHmZ"
    b"OZQyQLSWlNUGtuH+K2N+wp/AP/Ym5s/FU/Yh47A+REYrgb3Xf4WcLJEBgDATcEutTweHB+VEjtQl"
    b"guU7ld5E+ltVV466w1dVz/us3QSuwN5kZekYWM8MJxw0zBB/UlmFj89Av0HGeNtKYFx+d1rqw5C/"
    b"6gLDVqQaXgPl8+PP50NY1oHS8lpYq5Is8PuvoiMdXVCi7jVBcRrGqeqj/Dq0vtxQUkeAJiORuQAO"
    b"KXRh+QmIHJp95VhuwD9k5wJIHveTVspTkWmKoouzMoEcuIy+4J9jZ/BoC2YEIISdUhSDj2AhOmoR"
    b"jppAulD6TJopjYD34BFQmPfwF767vEzG49NJOhZRV44IhuMAKDdYgHvLhto5JXKXugrqrpyCAio0"
    b"Fb0mvaDBUbdxQo49qgmoTs4WNDFRpeIohk4Uy33E41aM/eiiQUmO2U/0ZI8ajUhiBwwN+z5C9y85"
    b"6UBzMlT3NxuNHmUCFIEtqpU1QcOG1KM/2XoloFSkptu/PvTHsP5TlekDbQH5C0ZNHhu+q1dinVZ5"
    b"rRPH19dCjAHkNcC0FP8moh/CAvdxH7IGFKkmiwbDEHhSvZDkEZHNmFPshc8D/io9DxApZrrb6NqG"
    b"kp/P4IHcozwo5QNlC8hqFnInZT5uYWfnKQCKyW1vHxURv9DlqFMi8VRhtVmLn5idCcBmzKVZASZ5"
    b"BDIFSwOYG9Q3AQq2z9fvzBmhstjsDf0MYOY45/DpRVEz6j6m5vY55AYXF975RU6dDhKziL4q5xdp"
    b"6NvuxEkGxDNL4uFQJAZY3e7eDYDvAAcRgUhWj6MhyOZ1IBlsRurK0BNN+QAy75LyvZ784P3SDxyi"
    b"jT62XoijbyWyvAVpYHvvdP3t7mGdfYpxpt6S4NnJYl8tODLE7CryiXwBDYyIrpaZZsFlBvXmL7YI"
    b"62dxxyksyZUP9PaelMwU2S7ZekATb3bItwnUWcFt616lLqlHltw0tFUNBCYyA7hsW1WBBrhPsSRW"
    b"1niUWiscsjFu1tEYJ4VG7JaRB548dy2ZbljVg8p9qFoZH+intDga+2aO3f6JrNBDRykPvah+wiBk"
    b"sbeZskuCdIOV1VkdhBp6ugDlOynBaioqYyM7lxToTANYdzfh9dU6m8AfVmejci1KnFF9r/qSVOYD"
    b"hKZi2iW0Jom71k3W3sZLJ0uNw9HDY+GNB0KMLGqmEETZxU6dA+Zc4NYwSQJdYwGrjcVyvBBLmip3"
    b"HyiyrA06TSggJRC33T6/cItefQHVm2R8Vxmoo4w/+wPFix+gML4A+eIbaGsbrJ/I3f7ZyL8WR4jP"
    b"rXEcD0Ebpb9C2hJORQYc10/VK1AhGEgwBUIb9U0BZF7RZIzsKyEG0vKDLLwRyOhtXwGh/ARMiyCx"
    b"4F5xmG5T+eq+KiXmt34ymowd9a3qIzMvotsk5gmMB3SfbzErNwHUM072/GCAQpL8CJVjNBhajSAn"
    b"pNfSUIDG70dA0EGLkfJU0QPzhOpchvor0rYwfQ0ssu3YnesKQAeS60Hg9VY2YKqizM1VL2b6o/nc"
    b"/mjgp7QjQmkS/iatqF0PpQQM2oGBuU8HYQ9lKkX2YFpJctcE7qVoNIqKlDF+Q4n1kTU+WY/kzZHb"
    b"ARngurVkfOjpoe0OufEnBAwLRwfU/6Ir9qD6Uu5Dff+dcR1ReQZyWCHiHD7TlqpTgZpBSQUkl4qR"
    b"v6lycYYiozgT2kseUhD0XaBxSTw1No8cK7fQYmmZSosS3qCTALa8A+oDHDV1Zqpl7y0jWQ3+ClQa"
    b"vbfoPE4++YicDqCDshlKRr0Cwj2QdVBLV9A/HsvUcbNEj/bvdU6hBWgDpNo4kvGasmUloTIcC+gI"
    b"9f/I/DGrDVk1lTD0oNxKqQ4Us9DDuSS4z/5WKzkQPGgqGIjgmowIxAyVikNl9RIBIZHUgJF/h9rl"
    b"eqKFAHS4ajQSCVBQmYHALNAXqfGEigOkpCi5St2UYpralEMB1+zlOsUQUNyfjQXIjSmjGfcCRhDx"
    b"zPTYAILSal48e/pKJXLXq9SYSy0X5NmZ3pCvVLpkTaMeUqANA9Fc2wWcMhAwc8NVzuNBoQ3EwkmI"
    b"VYGsH6K7LDkP0ScpMcsSvbdmCsmxm5umZyVSvblIqrUGZcj1Qgl3CX2XKpZFygtOYS8X9peMx8ZH"
    b"XYkWBt4RahbV5eXipSqKZfhgV4pi6mu1c/kl47/QdBnECRTJamNg77dx0iUNKb4RyRCEZlKf4ngE"
    b"cuI0WVD9YaKqAllqCWRK4pM0a0orx+A90wr/ijAKew8RThlvBUqpLbW54swuLzNlJb0c33r2Nmng"
    b"TXK5cYb6NW7fyI98xYWG5sDQcMU6RDRslqpEApqIdAzyhyiOGA2bA8tpXCLsl0yZI2QziTOhdqgo"
    b"7xWFCsOC7Fi32rGuaaZrd6y72LFitMUnzWBZz+6DlxkaG3i631AFbpgYfXQSgVKJXozIgWBmxXye"
    b"tuV84QZRl03IXkBfx45MUHJkCuq/LpPrbf+cfbc1KTJ+1ifRdRTfRjXib4XqDaIvGifTr2E2QC/h"
    b"qJsOgFzU6rg5/LN413umJO7nbAAoOYujYyBe73QZT7A4Mm9kfPUyZqpQnOEw9SKG9ghT8jVOUlJO"
    b"O0ETBkAljkjk9DPhhfDyBnqBp2nS3DVWCVBBA+6gD5ixmfjnw4vWymg+7zUaoyZSWMSQ+XzU1CIs"
    b"sOgRKE/dgzjwh6bVY1iIOudEBAIKnpA8Qt0Bka6oACXRUbM0uIS/c6pJLguha7IPqIJ0qadspPs6"
    b"kH1FrBzM5wPTV70yscwN/x47IyDbMNdDdgPEnur45dxgjZP7xn7fwJ17Bo4jikEvZUMtjwz4q65q"
    b"SltbcZKQMhWIgcamMBJpirgBqDYoUA0LE+LQ7ilqiS4LqLcF8oNYhkjk6UFg97lkij2mO+0BL1na"
    b"Z5WxOFeYUZ4Jj0wQY9l/q5LpMPa7qQccw5T/CisLOB9aaAC3kHSXumjBeQQM7W9hAU7G8paVDMNL"
    b"6KR6QIokmtIL7QjmZACMBUmW00O1m0SAGvYGkCHwIwWLN0k8uq/Xao92xZHdL1ADJ4YRPVj2GSJp"
    b"Ca80ki5AoCIHGiQqsCaD7C4dDfF7MNIa8qtRinYEtYs4UAxrh3UK4pfA6xAScnZDNjPbrq1LSrdZ"
    b"0+Hd+Xy36PCs4wDnxddaN0yV8A8d6U6SElbXy/bpS757//xZitelO9uBH/3p7uKEkoQ6U+cmvB0m"
    b"Z9I74a86zgkyBfSX/fZy2KoesRC0+Afshp1pnyFpG6flpBbsjoY1CNY7rF6l3mRrQKkUEaRMfhep"
    b"Us+iShpDylRpVDiTaQnAUw9sJDKfHkc5DGiwBLMLqJ25szMzzhsDvcH9ICco3iwZi1z7QzWMniKG"
    b"QAB7NgHsLafvZO53hqhRSTlNpHzzmXjCspTjnw669QS4+z4QiC7oiy9AQiBhKEops9BkS7lJprVE"
    b"lkBBP0pv8TlO+WP7eNTjkN0melNxPPRh6T+uOf99uvbfzSHSPhdeumsunvKpDeI0e9xn9drm1h/N"
    b"Dfhvs7a6ZXJAavxBG0ag34TB9VDsBwKYcZIFcjcOeDA8H6sjZ8B9EeQqK2aXGUiyl3E0nF6OulH6"
    b"Dip8A4JQB8+hxgdxPMYnL8wLiz2sRDRnnZztItHZNVBwnRlA5RSEfSSoaYqqPuCqE5M1DF3C8ACu"
    b"YuJAg7v4M6HToUDBSZDv4c8IXwf4cyO3Ps7knx1M6hAxOAPCSz7upHruwDzv4Ix2QGj35U4MbpWg"
    b"2yHvI0VRBu+2fnD6rhdI1OpDqRMqhaO75bpISz/wA8i7hfoOXNaHH+i9sc00GsESug0fmBbxM/jk"
    b"EFsI27cJttxnn6lBXHOhETZBc9Bb74tnKPst2TusoChnJLtbWJ5WervvzQDcfWZSvFtgb6fYqkOH"
    b"Zb2+xDLL+NImG0e7nWQs7Y69Q2dZEcghQyZM5Gqxi9Pn6aIxhwobR9B2H5ROpFuPfQ7gWp/0Er/v"
    b"Oef/89/pxZr72G03zzcv2m2caOLeOXtD9Tv31dzW9f3PiD/uj6TJVR8EujLwXfK5q/2WFEzfSNJk"
    b"pgEqPzwAMWc/6oo7UAzk4cZ6o3GLE17Jf8Vvy/Ud8FXLc+oAP5ikIkEb8hsY8khE2bI0WASIWu/V"
    b"zkO/vDmuFAA0bMHi3tWzCsgEarkyI9ySGeF2iZtFnDZxkTu32snCNSEf7h1tMSip9iD+ZHprxb0f"
    b"uKjzKSmH8w2bifT5sFgr7FZbPwlmSBX70o54hQtmdisX54GLxuosjCYilzB4D2nzucnOb621ODRG"
    b"oVsA5bYFSqj4CoDlznQlfRc7qgiAYf8FRRgTAvXR5cZPpnheFSg5mvzlNlOd9dWGk+huj+JJlB3E"
    b"t2cDYGyDeNjlz589e/IMihR71LdqpRzwW9qhBuqCf9ryDwzE65oh0Ydma9jXFlOkaJQlt5136Zk0"
    b"PFDPpCXzNqcP6AVlCOHcsjo2UEPmFImh1gihkakFHrkOaJcAkU4CyUglyJrObfHrQH3yVVKAfhPm"
    b"9K3mlHovuo5KLsqrsHCAlCCi3Ijy5mQnYV9ddoCEukVG22XZX8k8U23+1pY7D5hA+xoIxcqIOnsH"
    b"q0FbvE9pQo8t1JXYOGmfOqmrFPWpZQm8xGXVz1ui7dwAYQtA68lIctqVQHQIpMB1x6iVeSlMAyYo"
    b"EMNkqCevT0zzhvehJPSBVsG16kdfmSQBM1PLJk7QI2sETjJIcRYRGCGL6+O5RcVcNLRXyFcKg6cA"
    b"rJdlqsowcznVx1OMQJY0mQHYHlTKKbZRx/1plAjqaDOTNASpACkSQJrK0SnsHLSUPVR/v61zJcCl"
    b"ERMlihNZB0V5UWYPXdWx4xbUr4r4hdOQrLFGY69J2cwtkAXlDZACcR4j0Y+zkFwYIiG6oltgzbUD"
    b"E8awEIp+mgLjbBseK+cbidhkPl/p28Tvln8uGEwWo/+SDaq2TnRcz66wYOnIkw/DricJdthlJbrt"
    b"Veg4q7IXb5Hj5G7rUs3qWLL8so8WLiGFtHfGa2EBV3GlK41jPl+aq5APcwFyuw9+vryAXguz3dKu"
    b"0PLWtJ53b3dUEghXD7RYquW+MpK+PVgGzeckx4E2+pd9t9XUByotFQN9CqTfs6oaPlMy83+woUZj"
    b"F72PsrTQl+WiWaoH8TuWLpL0KGV3chHh+c1rS+zuI+IJf5Seb5AyKqWZFb9JBRsNeJIF3FlPadaU"
    b"A4hNf5nMRRaoe6e+BXqgy9yieiALQuoteuRgXyRvkunYJauM7pY0VHzgom1zIih74iBrv7WpaJ9W"
    b"jutV1frCi7vR+DURE3EYBkmc+em1nLKV0SL15jZpX1kk3/jF/dwDc5cQNRgX+evi1Dj1hWykjRiR"
    b"iIhm1wPOJ5pRfAvShxWeKkXPKC1WFE4CNzmT3gO4N1okP0QY6Aui9t4CaxRG/2lf48as9yADayuW"
    b"jszc+5AzKeAYjQ8r7OvSlp+za/YFb7nlhUok1W3dGln5tgiPplnltvMZJvtv8SDpuCrl5ZrVuJZT"
    b"aJ/buWmXPfrqKAfi1PelzhOC9DfpitSp+zDg8cgfo6Gn6L9U+7T+hgOgg7z9AkgEhhEu+geEiJWB"
    b"a4Nf7XjEIAf+beGACp5U1QOAEYhpYgigsISBZcXKJ3/wEMSD4oMtEZQGnLqzAfqoFoLtvU2yoi0j"
    b"HAxIOPg7E0zOb3qCJWzr5PSHpnEyvAG5gPkl/8w+WnNpB5F2jJE7MMhTTqQsNU+FMYSor+XQ4Cni"
    b"qb36btHCcpDzfksdqfFTOnLqswMkeyiiNhpdS13qLjFdfEXqR5pJ0/kKEhtg/wlCxlHEdD43dBh9"
    b"TYvKeksq0yT6qybO14IkpIIwf2XXokSTr9FFIpc75Ip+eh/QrfFU1gBj7qODA4ZIu06doi2gwsRv"
    b"KAMmpo8+wETXiy9T/PIUwI9b3a72EoIvbzWXKddtFpvKdyvNyfpViy55X9KL5/SB1ZQ6hAnMKu8V"
    b"nG+hV4AeoOIcyDbRsENEqNocGkTJbFhqUimZy+qEqf1q1wmr5ECT14OmXRlxRsC1lM4knAjnCVM7"
    b"5z/TbAK0H35WZ9l8Xq/nzWGzH8f9ITr2jLzNP59sbP10Wd2UQ0SedHtDP5Elnjz940X9ghwQ8HDJ"
    b"DE8XeIAWMmJQmFohMo91DMyjnlP43LnsW4Yh+vyUb7Dv9Hic8CdPGejLoHRPIeU5eyf45vNHW48e"
    b"bW6sTzMWZ3zr2TMWpEozv8awVUp990l9H8a3dXaTKKZUZ6fwKHVlNkz5pnjKeulCMCMrpl57wcm1"
    b"6ioolMGAwcOU1BtYy+rlQLq2sG4qzzEMU3UMQ3OCFc0J0PGobHh4ycUDpoj2wt7CMv4iO6ulmsh4"
    b"HgDViaUcGaKL9izBcyCohYql+vx1gs7Xy/NuEubfl3dKee+cGPR88u5mKSkcIbJ85uvnTcJZsShV"
    b"6nYXMnSjCxmyxbgqNVMjLJP9XIA9sETqhOLX/2wiGg0aDe75oL0G0Rt37ARTT/vd1MuW7elFjAxw"
    b"+z1yEae4R8XJ1Rn6wc8QXuRGb7bH2UzRrmO5reKRjgv5aFEdtqUzc5hKzBy67aF3PrzwMjyrYTzb"
    b"1TnR2g3Hjd6RYcg37fMqUvWgwI3rXngOupbGQAxu/STSR8EiEH5wF+42zAY10N5XZ4O81gMAdYFS"
    b"oJ9scdrbvxbkLgT8bFuFQYXRyH6r7clQ7fbF8LfRGElXlg7H12ZMnJzim3SIz57FCgC4x7DSK6fN"
    b"552m2lT6OgAuXi66JMecgvjpU+coAlutvjob5nUU6TDQSAdlPBXw76eB2Yiku2FxjMKuwE/6E1TI"
    b"8YR6In5NwgRlcLUz2sNzvDiggUUpXn3LlvdFKu+6Sw5A2voq77g1cReAjJ/WMLU2DEcg7kCpb1nu"
    b"NmvvKFpKMIhjlM5qgLYJbteizaD501UbgbMSCL0FoLIlcPPugSduF1aoJAysdUYehgPZ4g4eulWe"
    b"a+QuEEe7SvH23rIYAyP3MSAYvMBXR0VmBzBGIoVJ452WtWO8qyOU4rnWYmed7Vryy1juQnqXbExr"
    b"1DspdjsPESk7ziU7YYe02Urtm/5Y7es03pHCoNJzOmyXya+RtDqHcsCf9anODs76Z6TRsFIkQtUX"
    b"EEgadw3qWSWpslP+eaU4SMlWecfmXzvDuMPe8FVYCPewtUpOmLIrfmmiubL3/E27lzqrynTXafrF"
    b"p47rdVwP0Pe0/cXp4AvuH1y1IeWLc4mHfumYiHUu+72Fq4/fCXfNuWpvehvufL7JxhzEkG3mTNmx"
    b"JgXX/BiAs72+ye5gwTpXjcYxbTmwD1WkmmZrzl07E22rgXZ7w7tu202uvxOPnO11aHTL24T+vbPi"
    b"fnwglDyDuunhfOfVqxdspxFnFyCCmFR1bPranaunO/fly0398gZetvTLKbw8uQDJxXwsD70hVXSc"
    b"47VN9/H2ozhzMWi2LnLVpkFURA3vfRGMxzle33QfvRPsGH5cOwcTGNWLOSAlQaVFpO0dvrO22QhS"
    b"ZvS8wNmV6rMFcWPXvs75MQBdBh5t3b3cbrkF/n7g4/M76U/wQbmmwzPI1tcV7vjq+gF26SpBVnao"
    b"mwJQKSAVtMJWDmS9ubTjC+jiTZkISdc/IPBIzI9VL46bWhFzPrjsbm1NGWY/nIvoot2Os9YJGoUe"
    b"xxmbsktU3KpMtNIKCK3AvkBZkVzHuwFmTCSK1jitfXwCInWozjarNItM2RSsyNVJ0IcBaXvGb6Pg"
    b"gxUc72Fgh7FwRsWc+ykip6tF++3h0Kn/90adDiXfAMMcyFmKoN6VFVA+1TiWcj7bln3GndH59wxg"
    b"tgFY/GIOb0+e0Bvb4SMQDvCZdeCRALvBdrnVK0S9S1ywOw2QtU7k05bLDuXTU5d9lk8v3FYKEKEz"
    b"gQyfoMPygKCkbCrp/IxSg8EkuiY3LhzUSfu0iYSad4UDQNmF5XzalEWk8XCX1O0C+E4H533I5GeA"
    b"Y5f2iFer0DaV6bPEV+w9BsFZswkK2wACck9JZ5WW9Ht25bLyV3j+WHt6FUOkbrzhh+1V73NbDmoV"
    b"BkV/cMA37uzG4nTOm2IsWl51fAlA3CaXBlTN3d5o7jZEE4KCXOHvk3szw/RkZo46euEshz44Vo+1"
    b"S80k5c82NthvUTno/quI71OLmtegm3LBIhl8nHQSX0q69XadZF7axa57sgSGOs8iE+Wq3VSFFWf8"
    b"LRzzOUOxXZ1H1Wno7CG9boxZT9hmvZWyaGztlIO0W3DS9gxE92aC4FL6qrymAZ1vR3W3PRtB9ggA"
    b"l+eSz43S/2ijJlvY2QKyhdXoINOQz4rpFOQaIgo5JsvZ9j9USfLKuXRSQ86S/5Vak6FzUMrD5qIS"
    b"gBHhmwUhBB1nZJzX4vPRRWtAR10GzUw6YA6UabPRGEj0UCYzfJc5S9VQiTh1Vv7ILEZsSXr1jtgA"
    b"ATCimNxGWDy/YWd0EPisKZcTwBydLgNYnOxM+3EOXDJwTUwtYdMsJDz73oV0ROLS3guTvrYLvozS"
    b"yW/IU6f+X5fG+7wIk9g0rMfB5kBHU3A746MU3e+Q/p/ZlG4HAAp9lZzBWdmZz3fUaICTDuQZrsCB"
    b"EjgkYSRBd7ajB4idl4/Y8bNmIUXlO0ZhxOPpLiN9T+t5Ghyg6TQa9RgQ5tcEY0mHUW2AE4d0Qp4f"
    b"kOlGFP6/KqUmReJUhl2fgA6Dn3g188X/1TrMoE21tdsmqhMoIilCf4cniE/QiR0a6o5u9uZe3W/0"
    b"V7rfTlN+kUtFdUa9umEyseSprOaKHJRVkoICJcV6ERmJYYAsrJIofahy9I3bZmMMctNWMtw2/B1k"
    b"zkwR++Mcsk1w/0u+jWboxfr4NvrHYV1sqtHnmHck3bbmo32SOFMp1beWVAOi1bbd+jhnx+3j5sib"
    b"unKL4szmxicooUDlJuoWNbvNacAKTHKgoBkYd6RtG5OP+Tb0owLZpUZqzQavNRu8K4jjByJ1Czt5"
    b"hVPusXNtD+suZx9c46Pb56+0QUQUwXEUotYkRUukT473E03WOTnmzCwl8ZhdK/OHFIXP5P4BJDcz"
    b"PwEqCw+6t2zXubagaOW48Cwpnys36ArCYPbotkmDtXKO3dk2CPpjx3xTmdPi2yUTrmurfgO1XsJP"
    b"cSDtzKZSMC52V8znbHEGSXS5s8QTPX3HevqugQUuJhZzepeXHL4/AKI8MMEfoE/WBF/n0L//zQSz"
    b"jqIHfMqQ2PAOQphNqS+HXC1pWlMKwz/T0nznbCv+Rug95gY0mkY0Q3T9OOo5225r/Gp9s9FYLKLw"
    b"f8w2XfQHtZa1xCuplDOQNMZMeLeoW+kVbhzLEUlXNXWZfYbm2APwG0O/1WwwDcRtxVNQlNk2SHqP"
    b"yFkUyJna6trG7WQVKsPEslBtyk3fqUShaXHFhxXBRA5Hz45EBdEtGU/kYlNAmTLTYQDMdlPVsN/N"
    b"i/O80OCpY4pZZQC85cO9pc6ryBuudnedHS6dNZq0gmYBPqwC/A/xuys1iVJNhzEfurPVgqht6wUw"
    b"RmBP74HxFHeTVIdhzRQd9JYEJ2GZOWOTQx/stQS06v99w1VXl8/ONdK3RaiyU0D0Y7Yw45PIvwFc"
    b"pr1ulMVS4ECLQCdCc1345GqER0uIJL3etCAqx7Ymf60R9Y66LE/Cfcj5mPyMI+cOFExcWhiIudBb"
    b"yiLfzyiuydO1Vev5NFfW2L6OE3dbivrkHLCvxkgmuF50U6aPohzooyhfranEWborz5IeRJ6zGxXI"
    b"KMCd66/OX6pZANE7kH2vRUmW5jeC3S3uxmjBG3JnGKSXPP1cFp/3LzhuGasldkCnzBFaB7lr7ecr"
    b"lriNa8AaQOL1YQzwy0Yo6wBvhCUCxFt5aWPtmgUdNBofjCwL3T6QlHbBqYpGf2BLump66wWSmdNO"
    b"5GX7wXg93iofggNXDUJWJt2qZ+pr771eDod+NPVsvEO8GWsmXhjqxkoMSGlLtSB+2iXk2Jp/dM+a"
    b"pF69NxniSRCcO3l/nvaKBsJvMBvQYfxXpHlskWYqb7C9/EGxCKwi6hPLPF76xlpOdiH1lTqasQxd"
    b"dWZeHLutjYmpppMhelEDFhyryTh2lSl5COLOIqcjy6WRdDVyz+crMlGt3WvlI1mU1FjRXoS9zsq9"
    b"onhp4S/5ppSfe4sFCn1LihrXywcOZAfWMp7M1OIcDbcQ4w4LoU3mgAR2yLfZm/+sCLiNIuD2fSJg"
    b"RdMgtaJ13GhcUQ6oDPB/UhKkMqElqTd4al/kbMlGYmqbUn3LejVR5qq9f9cudG3bYDAuPSSVjDSp"
    b"XUC6usD0QTraakolM7sk+WpQwUwXvMfYpNdj2eZ0mJRDrlOME9v2Np87kWYhFCtFRfOPchZFdjRc"
    b"O0hcVnqLdAgivNFNPcXmKbQCFNEGL3ql0PgxstshRh9i2uFGpWTkJiNwk0S6aCn3nSKagYzzhuHc"
    b"WICBQPAtgLdcXtJZ+QZPjqpQdu2247cTevELR/Jya8qZhhrTh/ERBkOufJl87csU5K1Y9QToMe7v"
    b"01sX3ya6XxPostWvonaoN7a7FVa7Rfgpv5IeYpEJS5GYp9g8hUXYCWB1aM7Do5foQy6Kk9V0uenp"
    b"wE9E91B0Q/8BY16EHnUpV8f+FTwJq2SKHIkUAX0u72WRZ0ph0C7egQV/2laQBWoQnRsX55YcFtQS"
    b"6DXDrrUG8NWABH1Zi94APeuxCbTpktOD6oE0Iv2TPkiPJ/nxX3ZClxiVS4yWdfNM+bhhxRM2UBEB"
    b"TD/ZjeXWcMZn19L6foM/vQq/9XoFrcRLcJYclx45Z2zHZQOnY4ebKBzn1NU5dGhYWw4I6cx6BGCx"
    b"YWFLgE7yV6OmqQGzZ6k3gaHmFdc6rJvCoAIYHYkGo6ZdAr7FaGjGPa5Al67TK/VGkwJsrVd0ZsTo"
    b"LLxxp8MGsTdD6A3Lyp0q2rinT6oKd8GF7m90a7isWyXfOdk1q0/E+yQcDgVu46meUWgpPIJsGa16"
    b"fE+HOlkpxYUY8Qj9dBaRuULzoN/AgaCPms1QXSN35iOKU97IGkGxOZTIrTazOdQrTlzTuP5fdl0C"
    b"TvdcsT3d8aDouPLiH6nBLR1HfP84yryhNJRJZSjJ+eSibc6t9xoNH8rLXgztZit123h0X+Uj0Dzs"
    b"ykeNRgBfjHTl8GRVb4kpxSYb9q7YlZhcaNmsII62572driUyq+TEnZXL8Ildn5ybheoo2a5NL6pZ"
    b"qQTUpaSrHXS5FL04EZMI7QN1NpZ+lXsUCbr+X5d4iUua6QCG7EiGSk2zUtwlPEXWp700B3JUnDd4"
    b"SsPfKgDugna5k0BdMtIpCF9WbDL12Xy+bDNIfgUL+LW5MWIhBk6yGAMnXhYDJ+TjFLgwBjFBNpwW"
    b"vnh2WJsZ8ocZbg2pht7HYWTz3APhw9eS5w75W9ZTgYG5g+afqrPCseXxN654/I3d9tg7H194AtSe"
    b"tu8FltvfterVHYec8+sLL4AfzXzuFn3/pg5abP++7991xfcPSOhuUogrjhT+R/AXjcEYlZT+uoUY"
    b"M+avVlYC6P4ycQYyfchSuyC4jbBt7Uuq2p0pDVpVofcp4VOAx5iylkZXkR+vrPTazcVsyqWQHjfL"
    b"tjB3INnawuyoUip3l+aQL4tXUncLXWhI9tglRVrYJbONOEZDh3FpGxtaQTC7WSiI4FqyMQKIcK1N"
    b"HcdF9BkszgZ2JRRmwTEmSHXKFYoRL7iez6eNxvUK51ObDKLPFvantSt7cW0FtbtrNCZNC+dBiBqD"
    b"XkctnUikPyTicAKU3imf6x1XjzG/l9YhdHpRQf8sU9kUCExh45myP/80h3mm7mzMp8UhUQzsbG32"
    b"wmBps/fY6vcu1IAG5jge1Yail8mDVEMH3ZrpVMpYWQzGueugn8uZsydgyumAoMtO9Xss31fVuzlL"
    b"wt7oFCLUmHKlUogzYsJ7lTBEwOEtGRV/zY3lDpobObnnyW8HqTrg/A8+3jbfkuf0P/pYU5ceH8Ba"
    b"Bfk3WTAFleku6cJxtVCVFOdLafGSeGSZkI5aS6KSbWsXLhOaTFGBGSIvnzKNqEisCU9zK3SZWRSX"
    b"6gkA9dm2dci6TjWK4l4BO10soJZ/93x60To2okO72G5hx43GyrHxZzVLdXqBgTqWVBhAFvBK+G3r"
    b"kChj7N2bxbKD5oIMSzmAfA8UNkKjKvt+sewlOu5JtUoTPlw1KhIiBlYUlY8Ilr12c1lYI5UPmLjY"
    b"0pJPaHod7FkVyggUpFzH5AGAFuWxJlxLFjt1WykAZPfGz/mYQZMq3BmUA+o1LseiJXMNUNgdyL12"
    b"zfkoC4AlqZ4KSQOEIzdIK+Wk+DWl3VO9+XBt5nlVItg1cigV/NZREzBm9zAdbUrESpZscdInemMT"
    b"Oifruia/Dhg7ndinked4Uw0o40PeT8mKfuhog/5bnGTbCaTDiGx5hwxporoFcawEaVxwhRfGvbsj"
    b"Y707MuXFydXyYcLSZokUMpTIQ7wQtQf2obB/3VIyMbNbm4VhLA+95dp3Wwe05XqrOekB23SZjk4y"
    b"n1vcE8RrbsKCUSsfcAXT1Q5yX+ZWpcmTWK07HZcEiIemFGMNxFs8EafYtDySuNxNCCRZA471aW7J"
    b"oyRma0HIvuYgUBH3z2F9ILPDv9ZB3gt55E0rVCjAkLg5sIwGuCjfUKerNgNTfDYo2wqwEal7l2wG"
    b"tLytBiTGUyoQIruF4oNKA+aTov6yAaDURkmrL7dTqEdI9gvtyGYGtnJEpcbuzM4HGjFuNARBWYsV"
    b"U9wuR4cYqwWSgBaboGS7DVnOaoQS+Pgh5XDwV8ohVFcuU66vohwOHlYOrcqkcjjWyuFBwjfZfsK3"
    b"2GVScRbtkaqWVB1wn6xFls/sWmY70Jpbk883LvhBwpLzzQtuF3/16tWLBh4ITM63yjkylUy3EXvi"
    b"qseMlZvD61TYNP17PX1a/rTUuX3VOXUoAG3f1R5ZfX3yQF+fUp8GqRUKduFEIm0+WxW8fKKPf5LI"
    b"jLnYKQ4wc9X5MkjZLPy8M+gcuXmH/MlabI7lvOQbGCHdqjiUcbzMqXDg5wx/z+JrEaHTclb4gz9h"
    b"IdAR7TVgZYSu8XtQd3vkqougS+wnlSaflsYiZ8R0WPVeOaknHObEbIIs9j4p9X4MlFrQzbH3jeAp"
    b"S0g9PaaSmYcwQ1tEnrM7c0HpzIqdkDF9kiLKuTCG3SJ+/oNhVLIHQ7BkD8dQub+AqSGqhiDAT2W4"
    b"lKVZFMLhXaJdsu9wV0dNBgYUGIp6yz48khVDlpH1l5y0bKM+E6V0cZBXHwKTgiZ+6csxOtPt8Zgu"
    b"CoIJOVbTo0UrTAcChZYMUQ5lTp/Jy1xmeU5B8qvRzk2R5nl2kcOMEt3z5SUH2gSC48PP3wl/mA2q"
    b"rZQ/aisI6EFg4IHFTi92ZNnI8DqojBWx9u8rw3lmNICHCuY5MjO7OzocP2Lirpx0PG+M8oTBTfVq"
    b"jtJMU7lpmMv9J6xhpoRkvb1kh/fXEGYxTwjKJFbF83lctKllLEiCvuo4u9YbbnyZ0ngcOQLtJ7b7"
    b"2Wio1+IyBnkjQEdARXiPIsb0dFvFM+19mbedKS10magcixBS+11pfjCG2OyChYZ94+1ZqbLyJGkR"
    b"h5Kl2rkIQVYEATbJpwqaS7JkMAKTkePYR2jtalo7hLQVaDWhum/tE8qwFCeagqUmS+BV0FbEvjLq"
    b"6OnK9T1a5vJcxSColFlveNeomtOQtKewNIWhPYUhTRA0GZkbDFrmOoAliISGglxdGUb3D3pCe5hl"
    b"9OBFTE8f7pZXphKTFiHkmd3rCnw8bYY2PZaW2BIuyCSpux3dRig86/pIV6uk0bR5tLOKtR6mXsIM"
    b"Gnsrm3lxKGZRV/TVtRIg149R7qfFR5vgSturFjiVWr3cJzcq34MQ3sy11uf/Ha3Pt+5vuKe6XCut"
    b"cu++1EEpFMptfURrQByesjSnW06Nxf21wMh6eOhdYVxkFingJR0EN5y/hGyRjWyzcRLfTT1YJPgX"
    b"oP5R3BLEJVWYJXI+hcXjaW7Nq45FkjG9vCsIZfns69VsJclVjAldOZ63TPZolutgB7PSwEBhlpda"
    b"JJOI0FLi0iAcg7AnjDG29A0sKdPfRiOqErNzKxu5RGiW+sNFWVShgJwL3FyvpAIhKepxQUqTJngQ"
    b"t/RNGmkwEN3JUOzreXEi2hbmJtRUJIm2epURpoykUugZupjJypcHo9LlZPryyFSRzTasUFQB+o1Q"
    b"lrkYKDBrrchUtjPM0rMe6Mi+BQyBFi6QelLpA7NxGVX46mXiWBUwiophRwxKka1YwYCCcjAgcq2e"
    b"5DyoBAMKDXvCeyWAT1op2qmuq+arN4Qu7sgZ/YTxylJ576wdm0d1206zbAKqUzXgmk2bTJKzS+DK"
    b"o8xIZSe8q7fwNlr6vixW+Ug6+nTJvUa1WxgaAlLmLQPDX7TdwrHbNxUVHSDkLn2iSgXYJWq3ZLAI"
    b"3LJ3A/ZRNT6Bxi1WYMatvMBgmnCKDbfBfb0JzXpagMMo/ipAXZfpIgZMdhMSSujL0S6AJGktdsxb"
    b"WDxLQgX1+KueCRVE87SkprxkbrHBvThiBW3ZbRvm5bES5O2v7wG86oS76MLxl7BHjjFxZ/c005K+"
    b"Xosfdq1J0zNRmbuWnhYtDgIUh9ZM4Q0Oi1OF/mJ5mRaVDE8S0hXfCZhEEiaMxBBKxsZ94AGSwwAr"
    b"LTEHHlbpOOhBeOz2Xp6pLvFV5CyydYJSzaC1FbcBFySLB2yRrwTQj5ZGkyUCq8YWKzRHWJKddYDn"
    b"rsSIhQrMTEoBs0xyF/c4JwUhtwgvLh/3QSJoJApfyxIbeb6EV5NiJ8rExOwhyotMZ6bTGVG8YimI"
    b"pUQoQV/NRSKUkIlXlPBrsaXSAqT2FhagWLYyqo1K3KQ280W2LqoqJIadMqKBCRqHd2aX0E/Y6Gdn"
    b"Vf3wrTvvlIYiryRHxV2oMzgXLTQvCLTULGvallzlx0yYQz4LeofqzWEqb0uTsrXCCnUBoiivLtc4"
    b"3RZLpVyChNeoXWW/RprN5Sg7ZeARfY7QCyFa+NK6yq7SFs+aUsQFfJQeJEvwWl4mODMCLllqMhU4"
    b"UCxRYTHuXzl9cYVFeCeuCiiIvsUwHSqQYFYEEhRLtd3F9PtDDEZ6C01Gx8pMhEFEfZYVAQbRpycv"
    b"KVG0RuVkDVJ0j5a3ahbXpUUmZqixBSIDMQa/tlhUr5HgR5YA6C0po2/ptIqxBww2BsUdg6jWp8zq"
    b"UOlIVmKhoCbD1nfSAGP0eXEfVbZ7iVcttGJ1s6g+3CcpxMK3aflbFpvOJQX+En5U3q2avWSRBxS5"
    b"eUXjpfnUdonqSl1YbgDOrKhC0jVlBquuPIVyiWSIVncVQlspOlRxtRC2BlWzhaK0OgrIlNHeDnec"
    b"aUSP8PCh2j/ppHzrCV4nfJvyzS12nPI/nsHbtU5OIl6/vByKvh9MLy/r7FZfUbNOkgYG3ME7DW5S"
    b"fq6vrjH31liBci/YaarNvNYhCXM/njpylGHUleJukswclciKExXtTJIh2sOcWab7vIiRvHgOo63d"
    b"38IisoUqhNYD0xWgHPDexh/tuH1GPb8BeMd4gTt8WAupFceqobh3BTgH1cjr5GVjfAATFrOQ/Iqb"
    b"Wbwbjge0bSMlpZSSwxQ33hDb3Pl8JcRfUHTZFyfGuP3dsStPeZ9Ird+Z6TM8yF/qSrkS2txEr9rQ"
    b"RC+n3bGdFYWZUcVM6jZNHejTGL8RE07E0J/KGAJUB2H+0sQdwLFh3DepVIiYcFFy724cJtOyUUxu"
    b"NBcdLyV9jgZkK5+ehkDR8FJALCIRDAC1UJ/JKeqTSae4vQKDKpQXcvU5EWMZQwSy1MoxV6SgnQbd"
    b"k2j6MZwpTJy5/ggJGaM0c1lSu1ncYYTZFxJhVKDSjNwpy86UGd6eCMjiypLA8B7/DzaRtr3Hobx4"
    b"JUJxcs9sGP4M4smwW8OQEWokFCBa0N1oIlfXpIk7iqSO8fxOXx+3IGsb2VNbBpWvZQM/q03jSVI7"
    b"+3zysZZSl2ufTw7SGowdrzzoArRCfwjvCV3dB9V1hqLWmdY6cTag9tK6h7HuYdwTKGNVlEqPigJU"
    b"tTipGSBZMKrnP9l1Zt1ZWlkBZrdKokJ5+6o0e3iL9n15MuZoHOHG+Z6Kv6zuPNlL0SLWlKNwmTIN"
    b"K5FOGYgjpg18SgzK6cS1CUxE1KLNT6RRhUicKPe7jcI4LlT7bgBsxkZVq5BJx0JmUeP2ibUgJcLs"
    b"4L21PnDV4msqoz7WaUQfctYxlG9WaV1u/DhWqrWwSLpelkHhUUvV0HrTibjiMAxsKu+IZsflqS7B"
    b"iBovpVi7RuX0wo2qkqNbf5B+yEK6S3FkQaRKtJCI49CXpGPb1mRACg2gnKQjHerGPhb+CaJdLcv5"
    b"LcxAHFGJnB0aZikWAYGGl/t3efXtSzJsub7D8eHL00u8FPVR9qkaeUuNTvOHlnqv4kk10UDKYjd6"
    b"omx0NkI5cEk84IaAiN0KnNG5SiXYfMhKtqZpobDiT1a6xDzrZYXzRcSM5vPD1LFK4XIzL9b0FGkG"
    b"R72suMHcqsC1e1ACh94l1D3vjkvvGvy4rsT9FE8tupztpkb6kJdXZ/es5OXpS7VnKenTRjVwqHNQ"
    b"A+QmbIVYx2XaAKDFENCxRRwajWvcSI+lVFus607mxIwwh9gVgFc50FKwi+sUfnZSFVihct911D6H"
    b"oUYX3jn8mDvCYro5UeopYaGnFIz+PJYbj9p25OrjMveU1RWnWHHoqtj/2qKf0knKz4Xgx6NMQ39h"
    b"fbTUZqie/tZimaWzEC7OQjifh9VZCHW9AH+YJScs45GaghCn4JNwQoOXwFjumwBQg9lRCa8yezmZ"
    b"kZhHQOKFWOLy6l7rQ3WzffGJEWBNhbnraQha1IR4/wKJqbj2x5BAk2SNr7igfpPRcgKdOZmO5Y6N"
    b"66rLZFbiIvyLdWHDEO8SwTNUWJjkIRk2V44rVKNJcx63rEHykJnR4Onp29RlxYh5ql/sZZ49tMyz"
    b"ewhciia6ljwhJN0+rE7Q/t1KtkDosqW4kSncyEq4gchR+ImSrzIh0RKUsSzNpb1p9S1tSRlapmvC"
    b"9V/smC1231k2cr0xVgZLhcN0+Su8xUbuAMjdbV9vXaOPfaLHXJnKJfiIRzFK8Xmy5bzONT2yclz2"
    b"ukTEmOR8ZB9AI6ifoS1enlEiv8cY7T9klLJtNIt0QF0NuoQUlAiyoQ16vt3ZRwR9Zt81FVbklBWU"
    b"UyxH5vOU+Re8uOJlWzj7dFFAHGdn8TgMjod+GGXiTkYHOEolsYFGLlREfkvit+xm/7jzJqHS1YUx"
    b"3SPmhcvFvGqlqEzA2grLOUVFFUp9h+PF0TISoaN4AkIone66AeWKNIfF9MPUfdT8U67eABZ5K1zE"
    b"Zmyri44WJHeWtKb7WIBiwj5hS5kx+Pp5Pu+SwXKldMnRfH6Fi6LLYA2wCRoelG70zawJU4N1bexE"
    b"qsfGWRzDrUmvcZAwpWqNMFoJq4QoLC122WGTSk4EpjkS4p2UfXmwT3IFq/e/7JXLApzmcBmBsYjI"
    b"8lkBykKdulxY24D3aXFs841w7HWL15kD2vtVLPcrS9Q6QhBgqGPfVhD9+xVEqt0JYNrdRuPbS2Oi"
    b"BvwB0u6XSLvaZAMYIbFCeqyFTdSSW5U+8i7zKwqf/xDH2sUl4QNIuqgvO75sbiK5lL+glnbp+rYK"
    b"gviLQqSPFBsER591l7Cm7r2sqft3eVJXrmPJMCaKYUxyte1LutaQaxkji4nu6butlF0Ur9ZKcnVI"
    b"cFZ0dqltog76apwkaOChQ4GIpbdx0q3dDkRU6woSVdDAoyr/u8YLi7h3le7i6r7YfKWnBvMwRW9V"
    b"iI9Tgadi4aNF446/oB4Q9dHa1MjQIWVMbjRG95OmEesBcSpuHTHEwMgeI7MRo+prO2W03WA36p0P"
    b"XO+muD2TD1gMVPbGkJ+YNhg1/aAsRUI43jlzkzN59+4yVDYgR+qnAtRrtcGE5tpJcTZQ/c3ZwVIZ"
    b"gRg/4Vx4D86pazkjg27W1KYL1CfDq3JgYaVtW5JPLYqbtNNmxcAccCheNmLJoJOwzit1LX484TE5"
    b"3kpwtGPPb7eDdrvbUlegTgxuSrcKqBvIlZMu0cfKQRtCg8UTDVj0PNpfQo/NtfQEyfS+1at3M8rL"
    b"93+7bHWt/8a6Dd2SFgN9HcHCSkVXyiX/QMjObP/OpQJ9TjVqvbaFt+8pDrZM7PTn85VlLKmQ0mKk"
    b"3kZBjMvCh79gVjGXCFb1og0pqCMj6aR4DVzxpaWFs7uUV00EpX5noDYnuP1WkZmSktwXoXkvjpzk"
    b"HjaCwfp0wCyJZbY0v1TGlaL7aQqyvhbYz9A9xM5PeZjBJNQlUtTddrtex3jmlKiuIoZVKN8VPrmw"
    b"+mSCdU8krDbrI6yKDbl0omY9io+eHk2yPmBzn5RfWO8A4BEWUYQNE6if6XyOwfa+2TrAgN3YOoDN"
    b"Kyg22LAnX5aI/PN5hMHBGw38c4NGNIuwjqSXR5Gwgm8ykgO8BEhPlfwrE/X1YnRD6rYSq9GLvkKx"
    b"rXoqt1OUkCO9YDv8rF3GDQrw3WicScJ0yd8lzg6N6xKZCx3VcGdnf8MIbS3oS3VVK8YUPc6cM+Bl"
    b"Onz1eg+0xXXKW1dWBrMGT6xTquyQ/0Wj7faJjJX9cNcO2cn64cvj1JxbXtafcRIP46gvuusFyajD"
    b"epNhymHOjdYqXeA0eQMK0kGDayVfHYfpEPDdAhjSkckqW3a6SRe9bTA4hoylpa5rAhk5RRFS4wtN"
    b"1S48dfQEVnlhijeLfHtJN4FdVuXxyyqhuFwuoONSOYFWLi2j70xGaf5LsQovSV4prRKqqCIDx86h"
    b"rfXkrs0hLitqq+5WNR00ZBTCLynCBMyMAwQclISuDNbfsf2PJB8yNd1rn0hZx+7JrvZJep0SIYZs"
    b"9ONAXUfnXOocn01AjpO5XXO9JOamGE+PycvMAp2zr78LKE+6M6QRf4ZuC+9Sfr4Ff9GXYRMSLtgv"
    b"5dnwEf0cyLXBjzDWHSg5HrQw6eBuSAfd9LVCDmy4a6j8X96dh76cvxKM04Z3e9H9DqSCnVBomJPC"
    b"gQzJMSSG5yfqgpohvqbmtcedE3bIPlOsBWt5nBTLg8hMoxE0F45hyS9zjOyjbgeDLsimZrkdhOQz"
    b"O73QcaZOYZHhtvJ290YkGR5tt8nirDjYsLp4quFNzk9xWlbdWQ9QcpWBDKzn/410brjCZrALzfPP"
    b"uNN12micWs6enF/hVRdEKKDPykHJBYZwOJ8f2s6AS/rZaGCrV9iqS14toAUY8MEsBPqE0Yl1A+sp"
    b"f9VzTqkQRvk5Qc0T+gfsBv/woHnPWbsTBm0B4Azcyhf9mCFgtJVUD7i1sgpS0RtQvWXKG/i5Z+0A"
    b"+FzaXj6jPsXwAR3zxoeS76NPVTlWpJ4TE6kntJ6xE7hbgop3B+3Cu3I36ZK/VXNUoBqRrHKo8xDG"
    b"X/NrUvOvjfxxzU9rMKW1XpjgpRnq8kEZ7Paz8br5vGK8bor6skEIUrC5r5Au2ujgXYGBLy9+Tmv6"
    b"G0I6KRef5vyErfLPbVvaBuhSQimyC7vCxMWoLS05UaYf1mDCtAYonJI0jq3BsMRQhe5dObRAQaSv"
    b"6Lt10SKUvLKjP6/I49iAtG+QsAjnCkScq5d8wy2qW+yjBY0xoDqFpoioItlEfH6KmHOoqW8NE+C1"
    b"deOcSkb3ngM3+cFOEfdAZQXu8h7j6kgu8559w2PSfJggDVEKCQmTVH7Ke4lDT8f8pHmJXieXcTSc"
    b"Xhacd58cWNvtjym7Rly640dK0q29RnsgKUqvScUmNUnyuCNnzF7Li8TxZr07Z5y4rA9/RwnGHTdL"
    b"89RlB0Q1f2QOSHAnbmt3Pid62k+cAznAr3yXXQupw9WOFCF+rZjpUXHQxgpUcaQPA72KlGfm6/n8"
    b"tTEiKAF6yeYOBSmgfR0gGHpvRy0X2WDfeQ3kBEYmo5sfsdeaN+yjPPHJlieO3Nb+fX4V+/fsxu4v"
    b"8auQu0vkOf5deY5/zAGIdObtkE3Za+vMm9n4SgS3e3N+hPHYKiItUODXysjqJEudKpK/61WRoKdD"
    b"jiMu1yLrZ/t/s5p9l31sNHYy5zuADzef9tlXPCcTE6zZvqJX1+7syDqma5k4vi9Mw2tCge/lDkiZ"
    b"bEfw2/PX8uoe0A6+L0BnRyjw7Fgu2WY1tiofAHIdgcR2ZM4T39PHj6bVj8jKC0b/cYkcHCjZ9xSn"
    b"eUHq/ailXgSb/Bx7geDRBjWrE4Czzmv2sezqC8rTx9ZHWHdB0xzYxcaOMMKa+gDwALQySP6IW2ex"
    b"QXyaCosV7pdxDga5v4hyACMHlIt9aEO6rqyLG2ImLJC3WoTQpZUTrYKyQ+U3sivYTcTfQqni9p5Q"
    b"AIv9VCh1Vl+OcAdlVEYGWw4CbCI5aL8q2e9XZf/9JVvP+7axY/8BBy3oxoa3rz2yuPLJMscoK/CC"
    b"KT0CNv/J0mw3YeBAMXaFyz4L0/939GaOft/gAeFDWN/WYc4B0nZhuVHjzRE5+6SPQp9qW9Mhk7zR"
    b"O2FFZ/Co6qKOgncNmEQvA6JvlHxvmyn7mfeBaT9Xr8+MOkO06dqKIRRaYaZhJpnF6UHgtNQ/L2DG"
    b"7OV9ZfZ2vQcCgN6u8H5kzDJjeX7MyoYtL4jZcgnMAzyrWHe8oFAIzM4d+rMubtt5aZSzvYzPDBwX"
    b"IGyPGgT/mH9InE+SOe1IYnTEUVlodXjFVfQIcMgD8i3jKgHXrXpUAEdCQQ+v4zqBRMBB7ZU68qMJ"
    b"blEVuzLtt16AAb8B3ECpvlpWla8YgnM0wWuFPi3uWPKOjOqEh0gjyZgPMysRCNBu5f2zQLnzNFKp"
    b"0jwm6UamuOmRsnsDHinlGCAD42H7/NVXw9pTIBXXgP17Gai6aGeC4tsX+ragc6jyYjktkk1+B6Kl"
    b"skEUx2EvpxdACMPKpqDy49sRZCcGbqFCgSF3AuqVCOwTDPz84wXfUCEg+7HS9yNOGe32Ruswkuek"
    b"KtODMU+PIqIaKvgfXiO+CTxhSVBUPSXqnonaem11diugObyaNf+pu3EYrW3mD45Vyeo76CKvZE0g"
    b"yEvmHKvbEXKyTyJ+aEZDDZ1AQ5S1HfHlH7fbacT2Iv4OlJHoovVZ4GdVj6Z9mp9cx0iH4qZXbbrd"
    b"eBRGzjbW43rbEer66pKBBO880tRQSofflejzUc3T9xYesHA+0mTBTKGS+KlqJZS13U9ZDfEtFst8"
    b"bi2WvyS6uDSEPW6gK79SvImi1HuNpwoV9QiQ8a5cwwRJqG+wfRC1oCQN5jRaXgcaWeT37LqC4urS"
    b"bairqJq4qIUojYZqBPVqecNjBnwXqNtojHsGvTjn0+UqxVnEe7HzxmWTmGNQzrOovRCJ8yzSN1Nc"
    b"laNxLom8eZWX+cVCwE5FUVaLjZjX+iys8/h/TI1q1Xi1x3STsSbPyoh2ZOg0hsEnpcvcGTyK+QQV"
    b"lXHMXycOKCAAiyN2tITgvF4QuF+3F1ytXi+TslMk4lr6IXy8RnqOUFeiTKgVwdZRCd0cxLejMo8v"
    b"bAD0zZEdlgHT0AwuHHxyq8E/KZGFVMgxZgVSOTHoS2h9Y6ITUiL7G4IWwOvf0IcqAFzZX+otLmnu"
    b"dylYOyvf5/PvWhiufIDYfZ9jeV4R/ai5UooR7avphYytlJZq1+VML9PvpN5D0UxsuMcF3GML7qV4"
    b"O5RREQsNwapSB9TYZ4owvHYdbHGli4Y0h8xEX+04pcpaBI9ngPx435k5g1c7FHz2VyFPpg/IWRVT"
    b"nid9gUokKGejGMbODwXGXUQ+X2j+h6KF+jwyOL0oYJYhBdZWYVs8YkPoOCxCfsg6wrktEHKfZP6F"
    b"g5UDPwVRq9EAgWpfH5WkWVlCHmnRKcsjU/PEx7E6WHf1lyfiPv//dyIO1LXonx57+0Ddu/r3jr2t"
    b"2uEEP6cqhCAeq/6AJ5H0IYVNFW4viJys2OjUMd5WnEjuDH5DX2IlkqFwtIHbOfSJ3vY0Cda2J95v"
    b"bK77XhGWLRI1lRr0G4r1p8YISBv2ePYZNJziJmSA3Wpiezs78hrerLJ1X9mxLxQkPGCs1SPcRWC9"
    b"6D9aXXfZNobMzth40hmG6UB/OYlKCbSn4UdLdkGkIEFOa/I+oyI0xjByuriB7OyyS7wiCUrBE4zK"
    b"mTAdcJyc3dzimgEgLAP5fIPPZ3wXdyZgsY6Qw+0Sx9uRpxqBpTgDXtVu8EhAylSTs5v53Mdn3PaB"
    b"2aGGASaqWaUTYBM9vstuGo0zZxcN62zgtibFRjBUIv1tVIi3jhKLMhq3hEDRoDOxt5BXU+cSkM5U"
    b"wG50bbpjpmc4c6pn2opIVeLIe9i3HkiBePtSsfFUAN41sVEA7EFx/xaVsL0eQY7yCbecLq4KWZFq"
    b"lqSspD2zdrN0C1B/Qs/wIbTgu4sfk1MkkbQvCf+U0V0aQBOCawFaz4+EPwMiz+t3dfYt4fW9L3sf"
    b"z+oYwD2AruLFXO9TiYQBvnxNc/45w/tK+gJtFeOIT4XzFeTg37SX9oZ+P9Hv+4RvPdtgb1O+CX++"
    b"pPD2nP1I+XPxlH2TF4BMIl5PxuN10qfWf4GWG/bCgO6TXL/ZrLOJwIr6FIzve1K6fexKmOtCzshr"
    b"8XsKYvWU6MV3edOXcNE9d5IM2UCuWCgQQVFatH4QiLE6OApsGJBCnZpVvbBfpjJIG5NAoxvuI3Xt"
    b"Ja77LBMjqirCyF4ddRxXLVTRxfslVBw4mOAfwiKsE3E+jaCfFzZ7UHODsbbUI22501M5BuemZhys"
    b"owZYmM/lmTi7E0tigggU0kS6nb3k1EipuIn/QUEwwsp5sh9C84QIg8IYqJUUFTsMN5656UQyKEO0"
    b"tKVsIUNG4L1/rkz/vWTtRwpYXv0+/C1efUlbRQC5UjagMcY9ioBfwB+6D7NVcPO44I1uB+B+3Vre"
    b"7RiX/tdkwVGpgFCigQLjNyeGknJl6n4+CmpHQXfkBevqckcMJ7AcZNoIHJ9H5N0eNzW0MBCmgRbe"
    b"Sre8Auj8KHowdrDCzf4w7vjDMwqegoY7usTuBNh1PPqCoEO5gE2pSnaSlbGclqHG8hW6cDAbYq+y"
    b"dpPWjIwstxT3s2ax3CijeG00+pGqu/0Plk3OjovjkeTSpPpjI2/ETzI1gSZfOijRBbEgxuDSQ9M+"
    b"Gva1VUDlurqYPD+CblSaNXfv7RbJjCaPor1/cc7ruwdHp3t1WQV6cGgPRhXiw4JuCZZOot6kaN8s"
    b"SBlSy8SgCYBLP9IpPoUwkGyezdchgoCkOgJugWlWYdcuvYB2KvaoywrRQFWIbO734irC4WknPwkZ"
    b"gHyGbwUa4FwAg1cDbjSOhX4mRZqq4AMULyMp7rNbG+M1yIE5EDVm9to9g7ZWrgQpFhGGddCLuVYV"
    b"caCpFgUHoZZ1KfWKv1haljAs4766LBDC+ivKIwKWp3JDkROSSXJ17aa+4QCPXsU8yPE+x5+rs0mU"
    b"e6uzUeQ82XLzn+j4AniD8qjka5nN12z4MsI8z65h8znWQIK4lzIpAeN9mMDV3bUtYO0kh0eZt9gs"
    b"bRNBdegMeR9hL1YLvcnVh4/WpdUKol5oLreOjbu4xn2fWQcJtUoWaANw7PhNGoI88oD9hSe63hfD"
    b"EmIsMYyB3gy7FluY2CrTygne3OnOjvEQBiKAosZ+U42ST6DGpTdK609AFqIoRXq5n+x9AsDIxc5I"
    b"t0i9c9mrC+ZPskGM8TjGaAXCXVfvGOWw8/r/qa/5oPudqxFd5HRFg0V2EHVUM4EmIboPdBKOhTmA"
    b"dzkbU5RFcjM57AQjPOCpYD1U23cuIpAkNkgsimOQFlZmImlXXNAutK/FdmHXpktydeMyzln07/SW"
    b"AIsiS9i1e48pCgcoWT1jMoKe0vABE4CigegASWMgO5XrgaNm5vdTdIylB2XugbKb9xQ937gwpeG5"
    b"+GDLSpWR7/3MTtq8oE7RdGvY2wT870DZLu1aTMGGsohVVAwtPxbXCk/QZNCK2hbhjcqENyPCS0wQ"
    b"xcg3yQN0V15ScHkJGsEnWxU46lBgEoNgD5XRo0742tr3dGnRt4U0kRQQigro0Dji8jgixUASHU08"
    b"a8YRbXsDacVnsloDScVn5WvLAnrDsPYt/SBP/eElcsMhVEfnh4zgAkwVr3bGfRRdO5X/jVGEsG0W"
    b"Wl/KUtRupVS6UEr1iMqVG/TtsiAYyX0Z2rPpDePY9sh5vCmeAKkidPiUynD6GR7eMkQ/ipcf65cm"
    b"EugdoK53fu5nTFxcMOXec+lnkohplkFWD7xMexzhpcSSWN8Jp376bnsdlMg6KM7nyAdlMWaiBkNN"
    b"TK5S+INtMbOOL4zyXoOPvyWM7hpjYdebogSPZ5XxSbb1WYYC2FY2lPeoRaMfXhIWw0PLSUzjzGKM"
    b"D0IK9lvSV+OwFLRBothbLabhngTRINqFptVbxAmfjNH0VcRDwoumZRGtC1ksOtIBqcmMlMQUciOH"
    b"oTzUvDoTXzrGYNpQSog8flyVr0y0YBMKQn1VqG9FZ1VQyTaUssZ0j9BcKoO1WK9KgI4l3U7tgPti"
    b"QUZOL9zitkIzZNdTsMEpjI3gn5WaMT0rJ1c3OrOFvrE4piVLcmUcW/StDHO68KICnrK+gSGqTBGp"
    b"m16ALIqxtzguEBO2IuQbrfBlpFhFK1zj70Eq1cHx5M0pIQvXIFV+1Mo0+JQTaqK/1UE1TIFxPIaW"
    b"QlJSKtANUfdICjNC6UCsruA8RQyHDjx/iqcLK2KNEWhgqMp844TkWJDB9GiRJi7kmRDlGOQcYbgU"
    b"sqQfWlDFuJRqQnwAE/so0K0mM9fSB1U7hpKbE1SKYj4LhnjzSNXEE/jQraESQUlpU0foKF166+Uo"
    b"fMs9bdRF6G4KB3GuFUs9rySZY5T9iPt0p4OsRX6r35SyGeIZV3mW6CZTy9OEzm6Zi3kx5CQQsZtM"
    b"UYlU6lfQqDSlhtBMzj5J5qsqQjHJ4uiZahh1sxvrqtycDUPeNSZm/qqPFH87Yz9IPJBzZ6D5JSm8"
    b"z+SFJW+wP4kscK6MlhcoW8uDU3iC7FvizvBGx/rRB/RhyELgY1CODi257GtivbbrWkKpe5Z1RB+2"
    b"V04WZE6kvWIMbYYnXmqrswgRJq+t1362xN904HCoVx+PzvZ39+rtkjtHsBa6XtHplbTi7hGs+aUT"
    b"HanZ90mLfZ9Go67YUz2EaXRnkRq6qx0p0tJl840GiLeR22gQTDCP1Y0Ep/yuNRMNcp6yLn+TnocX"
    b"8kDGrOv8xjfa5g9K3oMTXFGRoVWTtqYG6mJhPNmG50lJtFUnOuVbETRc3h/lY9iSdhOEU7zI1WIr"
    b"Q0gqQnDSK17+kKud8jd4IwAscvwFGQgPLhaGpwjFyIh91zdeAaeR5QOE10fhSlxHNbe8f1KSQ/Ta"
    b"Tuy1Hedc4LqVpvQZxtnS6w8ICQzoI4iDEWXnxW1Npsx8jgj8UbQlCfCcOASxOaPTqera6SIByVhp"
    b"+6YiK8lIwkXVosyCP5b9nJRclISwvhS2RAWqtCPvi6PiBvz9SkO5MLXSq6oNS9uMIdZHkMQx6mdJ"
    b"6BM6F/1FIB3ACKwkZ6bsOipuVIQ8UVzKqG4owCW6F0ETgGkqSajXidA3EQKULqxjoHKzMjK2Pv1U"
    b"uadq05gEGg00P4OuXLIorzgJfqsTXNsOofIs05a1OaAyCztNabOglItJrg5PeUybKQT/3XiC+Nhe"
    b"YrX2NvILOkqSapFaYcgvW3CY5S3c/JAqDzrqta6EHX5ZwQoWUETmwaVmR2n4B9HhNlKhxCVmaZsU"
    b"aAen0gDjKDeyjF9HD84hsvcrcUETB904hyULPWhbVkQk5sjZ2alyA5abOO/xPiNV4Y00KiO6uPZF"
    b"8LNia11oBe90kiJ42+VXit9GapRjjKYYKT3WSEZCFjXgsiuhjZM5e1vsNeEG0y8UIsJ4wdhQZoWt"
    b"X0rklUMp6mOFzBTyV5CO7BpvvgPhZG3ND7FDIPZ+/auxh4gBcoAnIp2M6GgsIIl3T/1KuR2Gqt8k"
    b"hr5NyJQJgsnsbaIFh19ijW8aZYAuYpXnElAzAhoBei0dYVB5NGP+4gXcgSz1S6GV8ylxgJWdokOU"
    b"dSt3qCcDeVLAu+ae7cUbWrulO7q77C1uSkP10qXQv3M24G19k9JkCHuryZwOG0qngQANXNqbIpYO"
    b"HtsZP693/DQdg7wSD5tx0q+zemdCSySIEx+mD1dMiPvh9WAQJxOQtIajOM1GAOswEqj63BR5/19X"
    b"17LcOghD9/2MrHqnE7nNsv0aXONADJZH4Dz69fcIXNvpzhwxkhAPiYdhulwpWk1zjDPCJXQFzJzT"
    b"xqTPE6yPLmDuJLfsjgaMytMFDfJlPWDioIlP5UNGDJ4ZipwxAbe5KUELKAOkoXryN/sx33ngRXUV"
    b"FTjUryzH9w+afUd8dXvoYQbv9EgTyhhXQuGtpW5V1C9cbuOGxnNaEZ8CXLjBEPKUMaFG2EhXnheJ"
    b"G2xDf+wQSUqEvfTNlZWUEScGXXeN1MqKXucw2bjwmGaZECwsqilSN4rhzuiHY+u1c8+dcFev1Nxy"
    b"yOTJdnNvIbMap3IxZxbUNqXJ6Ab5LzoCJs8bIBieEfz0hGps9caAlYRuYeQh3HLeS4SlIprAjgfG"
    b"QzTSHx43OQG8tFL1iMgKxlJuOIBnhNW8N5ZhhauBypnIZ6zDfO9Jl5EzJ+fp5scVS/7s806/9xMF"
    b"hL9/pZz2xkjfbmSR2qh1WjlQvNj7ki6Nmkw0o3Fk22DLKRwookTEhpp4mHZesmfp5UG6BuaY+47G"
    b"sKHJwTHtVNF/2JBaWmUyUW/xV5yncqtyxZECdqeBL15MVXkR2FxPh+p+4DAOt5Q+m+bwtu1lDvza"
    b"+39fOip8vfwH6BiUzQ=="
))

PEERJS_LICENSE = zlib.decompress(base64.b64decode(  # generated from peerjs-1.5.5.LICENSE
    b"eNpdUl9vmzAQf/enOOWplVC7TdrL3hxwGmsEI0OaZW8EnOCKYGSbRf32Ozvp2k5CQmff/f6dUzO9"
    b"Wn3qPdy19/Dty9fvsNFtr4ZBwXKGZuyAWd3C774ZTwn03k8/Hh8npeyLe2jNmZC7ulew4TXkulWj"
    b"U/eElMqetXPajKAd9MqqwyucbDN61SVwtEqBOULbN/akEvAGaV5hUtbhgDn4Ro96PJEGWhQXOn2P"
    b"MM4c/aWxKmpqnDOtbhAPOtPOZzX6xge+ox6UgzvfK7KobhOL+0jSqWYAPSKagrcruGjfm9mDVc6j"
    b"z4CRYFM7zF3Q8HY96LO+MYTxmJgLoLNDB0FnAmfT6WP4q2hrmg+Ddn1COh2gD7PHQxcOY0xJ8PFo"
    b"LDjMOiBo1B29vquLPchCphCov0UUeS+9OX92ghEdZzsipeqiXYORRcYX1fqAEtqPZhjMBa0h5djp"
    b"4Mj9ICTssDmYPyp6uT6I0XiUepUQFjC9b/V25foGtR8UuQaGvBhv88GODfTO4+I1Zj8ZG/n+t/mA"
    b"/GsGlVjVOyoZ8ApKKZ55xjJY0ArrRQI7Xq/FtgbskLSo9yBWQIs9/ORFlhD2q5SsqkBI4Jsy5yxL"
    b"gBdpvs148QRLnCsEvlCO7xRBawGB8AbFGc6tyIbJdI0lXfKc1/sEVrwuAuYKQSmUVNY83eZUQrmV"
    b"pagY0mekEAUvVhJZ2IYV9QOyIhWwZyygWtM8j1R0i+pl1JeKci/507qGtcgzhodLRnJOlzm7UqGp"
    b"NKd8k0BGN/SJxSmBKBJC203dbs3iEfJR/NKai4JgJqkoaollgi5l/W90xyuWAJW8CoGspED4ECdO"
    b"iAiCcwW7ooSo4dNGsCXU24q9a8kYzRGrCsMfmx/IX/yBYQI="
))

EVENTEMITTER3_LICENSE = zlib.decompress(base64.b64decode(  # generated from eventemitter3-4.0.7.LICENSE
    b"eNpdUltv2jAUfvevOOKplaLuoj3tzQ2mWA1x5JgyHkNiiKcQI9sMdb9+5wTabpOQ0Ll8t+OY3sJK"
    b"Gihca8do4Q6Le8Zyf3oN7tAnuGvv4evnL9+Ah9GfEzw3v+3R2cBYZcPRxej8CC5Cb4PdvcIhNGOy"
    b"XQb7YC34PbR9Ew42g+ShGV/hZENEgN+lxo1uPEADLWox3Ew90kS/T5cmWFzuoInRt65BPuh8ez7a"
    b"MTWJ9PZusBHuEpqf1TfE7H4S6WwzMDcCzd5GcHGpJ/PBxhRcSxwZuLEdzh15eBsP7uhuCgSfDhAZ"
    b"kp4jJiCfGRx95/b0b6dYp/NucLHPoHNEvTsnbEZqTvfMKMcnHyDaYWDI4ND3lPXD3bRD1k900HQ7"
    b"UaTOpffHf5O4yPbnMKKknTCdx5NNij9tm6hD63s/DP5C0Vo/do4Sxe+MGRw1O//LTlmu7zv6hFav"
    b"FugBTh+vehvFvhkG2NnbwVAXz9v8FSeQfEz48K4Z4OTDpPd/zAfUXwqo1cJsuBYga6i0epFzMYcZ"
    b"r7GeZbCRZqnWBnBD89JsQS2Al1t4luU8A/Gj0qKuQWkmV1UhBfZkmRfruSyf4BFxpcJPWeI3jKRG"
    b"AQneqKSoiWwldL7Ekj/KQpptxhbSlMS5UBo4VFwbma8LrqFa60rVAuXnSFvKcqFRRaxEaR5QFXsg"
    b"XrCAesmLgqQYX6N7Tf4gV9VWy6elgaUq5gKbjwKd8cdCXKUwVF5wucpgzlf8SUwohSya0drVHWyW"
    b"glqkx/GXG6lKipGr0mgsM0ypzTt0I2uRAdeypoMstFpljM6JCDWRIK4UVxY6NfzzIrhC9boW74Qw"
    b"F7xArprAFPFt+YH9Abc4WFA="
))

BINARYPACK_LICENSE = zlib.decompress(base64.b64decode(  # generated from peerjs-js-binarypack-2.1.0.LICENSE
    b"eNpdUl9v2jAQf/enOPHUShHd+rg3kzjFWogjJ5SxN5MY4irEKDZDfPudDV3bSZGis+9+/86pPV0n"
    b"c+g9PLSP8Pzt+zOwybTwu1fjIYHe+9OPp6edGdV0fXPz1h4JeWh6DSveQGFaPTr9SEilp6NxztgR"
    b"jINeT3p3hcOkRq+7BPaT1mD30PZqOugEvAU1XuGkJ4cDdueVGc14IApalBM6fY8wzu79RU0amztQ"
    b"ztnWKMSDzrbnox698oFvbwbt4MH3mszq+8TsMZJ0Wg1gRkTT8H4FF+N7e/YwaefRacBIsKkdzl3Q"
    b"8H49mKO5M4TxmJELoGeHDoLOBI62M/vw19HW6bwbjOsT0pkAvTt7PHThMMaUBB9PdgKnhyEgGNQd"
    b"vX6oiz3IQk4hUH+PKPJeenv86gQj2p+nESl1F+1ajCwyvunWB5TQvrfDYC9oDSnHzgRH7gchYYdq"
    b"Z//o6OX2BEbrUepNQljA6WOr9yvXK9S+0+QWGPJivOqTnSnQO4+LN5j9yU6R73+bc+RfMqhF3myo"
    b"ZMBrqKR45RnLYEZrrGcJbHizFOsGsEPSstmCyIGWW/jJyywh7FclWV2DkMBXVcFZlgAv02Kd8fIF"
    b"FjhXCnyhHN8pgjYCAuEdijOcy8mKyXSJJV3wgjfbBHLelAEzR1AKFZUNT9cFlVCtZSVqhvQZKUXJ"
    b"y1wiC1uxspkjK1IBe8UC6iUtikhF16heRn2pqLaSvywbWIoiY3i4YKTgdFGwGxWaSgvKVwlkdEVf"
    b"WJwSiCIhtN3VbZYsHiEfxS9tuCgJZpKKspFYJuhSNv9GN7xmCVDJ6xBILgXChzhxQkQQnCvZDSVE"
    b"DV82gi2hXtfsQ0vGaIFYdRj+3Dz/C+B4XGE="
))

WEBRTC_ADAPTER_LICENSE = zlib.decompress(base64.b64decode(  # generated from webrtc-adapter-9.0.1.LICENSE.md
    b"eNq1Uk2P2zYQvetXDHLKFoLbBD0EzYmWaJuALLkkta6PskSvGViiIdG72H+fR9qLddIC7aUXm+Jw"
    b"3tdM5s6vo306evrYPtDn3z79npI+GtqavdQZnUf3zbSemos/unGaETudKL6faDSTGZ9NN0uyn0G+"
    b"XEGarjl7M86+Tf8RKJGms5Mf7f7irRuoGTq6TIbsQJO7jK2JN3s7NOMrHdzYTym9WH8kN8Z/d/FJ"
    b"7zp7sG0TAFJqRkNnM/bWe9MFFc+2w8EfG48fA5DTyb3Y4YlaN3Q2NE2hKemN/yNJiH6hHzVN5A5v"
    b"YlrXGeovk4cF30BkQGz27jmUbpEAgmhw3rYmRd1OdAJaALknHLqf1ICyPTW2R3r/rAJsdzm8qYDB"
    b"7gJl/4cQUEaMUO9ce+nN4Ju3Mf2KCThURuobjNw2p+k97TgiFGP7vY2bt9LY2BqQh6Y3QdTSuacT"
    b"Pt37dYzeYmEg+AqBTQLfa8Tdm7AqkO/IDB0qJmwFNPTOG7oGg94O4rBrdEDhGsPkDv4ljDyg3LaI"
    b"prNpwxqh0YblGsMCDddVmqardL0SilS10FsmOeG8kdWjyHlO8x3pFaes2uykWK40raoi51IRK3Pc"
    b"llqKea0rqZIPTKHzQyywckf8r43kSlElSaw3hQAY0CUrteAqJVFmRZ2LcpkSAKisdFKItdB4pqs0"
    b"kv69jaoFrbnMVvhkc1EIvYt8C6HLwLWoZMJow6QWWV0wSZtabirFKdjKhcoKJtY8n4EdjMQfealJ"
    b"rVhR/OgyuboM2u890pxTIdi84IEpusyF5JkOdt5PGZKDviJN1IZnAgeEwWGGyV16w1T8zxqPUKSc"
    b"rdkS3j7+SySYSVZLvg6akYOq50oLXWtOy6rKY9CKy0eRcfWVikrFtGrF0yRnmkViQCAqlHGe10rE"
    b"0ESpuZT1RouqfMB8t4gFGhla85huVQarWBJeyV0ADRnE8FParjjuZQg0JsVCBAqJZfr+GfgQoE7e"
    b"PVLJl4VY8jLjoVoFlK1Q/AGzEio8EJEW0wdnHS2HGUFVEo93G5vGSZJYEMsfRZB9e4zZK3HbkxhZ"
    b"trrFPUu+A6+W7gI="
))

SDP_LICENSE = zlib.decompress(base64.b64decode(  # generated from sdp-3.2.0.LICENSE
    b"eNpdUUuPmzAQvvMrRjntSmj7uFTqzQFnsUowMs6mORJwgluCEXYa7b/vDEl2u5WQkGfme80kbnyd"
    b"7LEL8NA8wtfPX75B2dnejiNk9dD8NlFUmulkvbduAOuhM5PZv8Jxqodg2hgOkzHgDtB09XQ0MQQH"
    b"9fAKo5k8Atw+1HawwxFqaFAqwsnQIY13h3CpJ4PDLdTeu8bWyAeta84nM4Q6kN7B9sbDQ+gMLKob"
    b"YvE4i7Sm7iM7APXuLbjY0LlzgMn4MNmGOGKwQ9OfW/Jwb/f2ZG8KBJ/z+whJzx4TkM8YTq61B/qb"
    b"OdZ43vfWdzG0lqj354BFT8XGDITCHJ/cBN70fYQMFn3PWd/dzTNkfaSFhtuKPFUunTt9TGJ9dDhP"
    b"A0qaGdM6XNms+Ms0gSo0fnB97y4UrXFDaymR/x5FGlv13v0xc5breQcX0OrVAh1gfL/qreW7uu9h"
    b"b24LQ11cb/1PnInkfcDD27qH0U2z3v8xn1A/41DJld4yxUFUUCr5IlKewoJV+F7EsBU6kxsNOKFY"
    b"oXcgV8CKHfwQRRoD/1kqXlUgVSTWZS441kSR5JtUFM+wRFwhNeRiLTSSagkkeKMSvCKyNVdJhk+2"
    b"FLnQuzhaCV0Q50oqYFAypUWyyZmCcqNKWXGUT5G2EMVKoQpf80I/oSrWgL/gA6qM5TlJRWyD7hX5"
    b"g0SWOyWeMw2ZzFOOxSVHZ2yZ86sUhkpyJtYxpGzNnvmMksiiIhq7uoNtxqlEegy/RAtZUIxEFlrh"
    b"M8aUSr9Bt6LiMTAlKlrISsl1HNE6ESFnEsQV/MpCq4YPF8ERem8q/kYIKWc5clUEpoj34afoL0SM"
    b"UUU="
))

QRIOUS_LICENSE = zlib.decompress(base64.b64decode(  # generated from qrious-4.0.2.LICENSE.md
    b"eNqNkkGPmzAQhe/8infclSLYtodK26oSjZJdpGySAtEqvTkwYEvGRrYJ4t93YLfKoVXVG7bffPPe"
    b"DD9yZQcPRGvbT061MuBufY+PDx8+I9XC10I5vJCryP1N9IDSdvhJbqikYEFUSuXRO9s60YE/G0cE"
    b"b5swCkePmOyAShg4qpUPTl2GQFABwtSJdehsrZqJOXw1mJp7BkkI5DoP2yyHp/0JT2TICY3jcNGq"
    b"wk5VZDxBcOf5xkuqcZkxc8F2dlC8O8DWMlcEZc0KpPjd4UrO8xmffrd4561g58x3Isy2HWw/l92z"
    b"1wlahFtl/GfsW7oayixUaXuOIpnG4UalNS6EwVMz6BW3YS1es/L5cCqR7s94TfM83ZfnL6wN0vIr"
    b"XemNpLpeKwZzICdMmGbfiF42+fqZK9Lv2S4rz7P5bVbuN0WB7SFHimOal9n6tEtzHE/58VBsYqAg"
    b"WpiI/jHYZlkNT6+mIJT2HPjMi/RsS9eQ4kq80IrUlU0JVPyT/Me2EAltTbvEY+1tfuwqa2BsWMGz"
    b"u68yhP4xScZxjFszxNa1iX5j+ORbHP0CVUPsHw=="
))

QRIOUS_GPL_TERMS = zlib.decompress(base64.b64decode(  # generated from GPL-3.0.txt
    b"eNrFfVtz20iS7nv9CgRfLEXQ6nb3TM/OeKIjaJlu84wsaSW5PX47IFEUsQYBLi6Sub/+5JeZdQNJ"
    b"dce+nI7dGEsCqrKy8n5Dlh3+99v15+y3+fX8bnaV3X5+d7W4zOj/59f3c5Md/+9323ZlU2c/T7Of"
    b"/p79n6G22U8//vg3Y7LLZrdvy8dNn51dnvMvsw+ttdl9s+6f89ZmH5qhLvKe3p5mi3p1kf1z0/e7"
    b"7h8//LDu1hdN+/jDryabP9l239CqZZftbLst+94WWd9kK1o+y+siK8qub8vl0NuMnl3Sglv8sbSd"
    b"yZp11m/ozapc2bqzWdGshq2t+2lGz2erTV4/lvVjVvZYvm76LK+q5tkWF+bUefm/29bm22Vl8dTD"
    b"xgrabG3bvMpuhyXtll3pjrRunq3p3FOGuLLr3kOzblrTOWzgKE2/sW32rayLDqA/N+237sJtom91"
    b"eC3bNl2fHXl31+arvlwRHPxyhr8Wtisfa1sYwlqff6PHn/N9tm+GlgErmi3w2W3cSowWS4izCkGW"
    b"vdsT9HXf5l0/Nf0fnrise1sXck+PQ97m9LMd72gOdiTk4wpBT3z+nI7TPLb59vVrWmgL0LuBXqHr"
    b"au02L+kpLBdwCMxgkbLvsqGjlQj0L4R5QHya9uhJPGFeOJNHOUGFU7gd3wKWfLeriNpo567BufJ6"
    b"r7cB9BGolc07IAOUCNQv9wxhPvSbhmH82gzZKq95JfwNqzC29PwdHaFpmBK+bGydPRMidjb/BnCA"
    b"AQ/PFH/C+Vq7tm0L2ibMKc6noHCza+lMtOcNLX/8tCnVZAnq+03e4yLNJn8SEolIKOJEYcAD+LIz"
    b"ve72UcifVthm5RpLZs9ltzmf+i3oDCtbPuHloV1hycJmdA9A1KPtmWn5RfNM9EU/Rq/imYiM/fb0"
    b"Om6bYFsJdFikzmr7bBjOgG/A6Zf7VjfPft2iwZpMM4Rf5c8Gr/Z21QuVs9zr+DZqKzjctfaJJI9Q"
    b"BgiXcFbYeo87wiFkTXkRcObdN/0Tc+fQtmCpls8jT12wXKCbbnDxeBCXYla27Yk3CH3djhipXJZV"
    b"2eMyFM1HbynG0hTbl2tQIBF9Ua5Bkv84XI/Awu9w6JgQwCJ8RsbMB1rLfs+3u4rWfQmCblhtAscT"
    b"6jYWqxj6qS8ZI8zd2drqYbcD8eMu7+hvNWBhxNhVSQvWhEI+Ub61RuHqDgirUM7jhUYkTm/vmemm"
    b"7mkTkZ5gy1MlrTMjcvFAdRsiF6ZsJRTSW13WMYh7w8RE/yodmTCe3hN1VM0OpMEAqFASQXt7dYy8"
    b"iGH6TdY/E3X0lvSmOXtzTmRDcq9nXSPKF8hJLheUffbTOeGcRITQFwSTMr95LJ8c3VX2kYQDa92O"
    b"lbyq3Wl8g7TcDywdlVD8rWPXwp/qFe+rIu+VOw7LXz4mHXFFcrIl+We/7yoId+NuorWinkl4ttAl"
    b"eyYFhjqRLhey8ZLIT8Q/b2r8ph3dcdiutf89lK1VfDP8JbGqV0BLS0TRfqNf5Z0RYVJM5RYFrJLl"
    b"M5kBW1wFqR0YEPRW3ituioxkMNkuzdDRsaAZBBKQO8RBSX/w+zHe7pstI61cHZHCkBZyrixf0QPM"
    b"gYSnHiqPzt0OtTk8xoi58UJZMG0Rk+UVATQ8bviRbV4PazIfiAlao5Kua1jKQKcTsqEzYT7RhnTV"
    b"9arZ7og5CQNKirRIXkICGHe/REl6E5GeOCKZRZZl3Z5IeUtrrgytTHxTB9GwBEs0q9XQwsCQzcgO"
    b"E2Q2xbDqxTQi64lIuBhIHQPn9BaESUlLwISEhOgsgf8sdMWWH6v2oQZWd31O50lF67MVdRcuAwhR"
    b"DDsEg6RYzDcbEpEiI9Qas0qvDbGXA5V2WOjJPBHlLYFGv1vSldZ9qVhWW4JwB6ZgaPD3ggg4L0BW"
    b"xDAwtwQqWuypdMzKW7o3sdR6wO164jABdqKFjnWV01YibkaCXYwq5vCyBnzTzMJAd2IbyOw3BBgB"
    b"RAuRzchHqdjm8SS4w58h9+57+lcHeTlURbC/3QOqYYibCBIVJSA/FiVMDetg+zUQzWzOvN4N7Q4H"
    b"B30SG7admPtMNE2nEr5oWD3D6GDWfGrKQkiSNBrhPitApK087AASU48xJFa9P/gKRzCsRejyLclW"
    b"uvknEBo9QTaX7fN2f6GWglgCuK8gjkhwD04aGbcfcaEKlaGTbSMrwG1dN/VrwOI9BSVy1TtscTXE"
    b"FD3LA5AihDixZiTHQTCQlSI/VmwZ06O4jdO+0MP87tN9Nrt+n13eXL9fPCxuru/x8I8XpM7WZS07"
    b"8vuTh0jHTMQ85ft1XPSz56OTVrgs5N3KiRjcW5vTqby+e12VdAVV/qxyXUxq2ij1rQx7NlMVLUSC"
    b"dlsCScSaUGZkfHm4Lbl7jOgYbNj4fs+cJSBsffXRiDr1lsrOOOizbJ7TZvqIeIZFQVfesYrJJqRy"
    b"J/TURF+w3YSvZBKMmglBtgc1xDKO4CVfOa/L/8kDvonMJqKSaRGBTRDlPGe2P2FQFfmO2Q4/7PK2"
    b"d/eAdwyxDNF53m1wRaIwIdKDdRGMg6limLBeqzphAxZ+XG3IBFyJVaKSns49VKwfGLgStF5VwIQC"
    b"HimxicJkYB+Uzq9ia5D/NVmyf4UHsXH8FCNjlk1WDa1Fz+B3E0WFLRVg4q7a76mXHS3Pqxu1o/TP"
    b"Hsng7vyR2PUQzwWTCXsJoh9ZK+Tkp+CnZiA2j7D3zDKQBYjYyHTtEJwER2dBmqQd6MeqZGqD71TW"
    b"a9yGZZEoBMfyacVPhDsiZiAx/R26jf7HroZeYx7geeOEZOaNOPwVhnj5lIuFjju71XOCEEjzVwMp"
    b"Qy9HTCJHzviwtJweM4uFCjl4Shj5U15WDKoY72bH3C4GKhFeB1uIxGpNK8NF4MuCPn0S94NY5tlW"
    b"lb8JwtGTHZM7+BQ8r1aCPwLLBltje13agPjVreFbgEWlHqh4KYSFT2wz1ISunI1Xudec9SIUH2wp"
    b"k3vFQwq1BzBy47Bge7JfO9jdHN4QY1pDTwI/YUZotg77PFnZgH9BFpqF3CYbeU9CY7YT/YKrumJ7"
    b"/bqBydFNjPpEbB0I5Ym7q5eXy4516TQqLbQta8vqGjYEAlxrUuXeKYJ/4XeWcIXfO5Bbzft7P8P0"
    b"dEnijimWXjbqVZKeKcEqbcSH0BdKNZHZ4iGzxYUOnIDtWFgKVnkNXjcIZqdWBFJ22UgdlfZZL8YH"
    b"D4MAX6w5+BXugTRtJ4YBbSvhIT4kEQBZ04UI5x2L5aBrckMcO0zF2RWM08UgDiIihlfaWstOLARj"
    b"S39taQ0mjDcX5CWw63kJ19Pp/Enkj07UVY7FkZgFCAqRjKM/bxM5z/EtYcuYWcXD6KGUbpb/ZVmC"
    b"Y/nAW7A9ZGfjFs0TwXsPUzVvi2zhkBZejxAp/CgCueS/kXtawg4TYxcrFLApCHoyJXOwZvNIOo9+"
    b"dg+Qy9YUe0Qvpg6Vq1ysRL9RJ+YdS3pBErP9aqhyH23bAg0VWX9D/ohgSC3gGUTviNCqvRhj+bah"
    b"54KHy8dmyarixS0R7uie3RsiqGWbQ6hNRDuqVA5mhPKoVx+qW43XrfwUSIncmKaySvln+blEX/nt"
    b"wiGhposhuaD3Q3Ju9S1/FCH/Kf8vQsIliaum9mFx7yxBKgWTgDbgx030OPP48pw0VPsEQVqLrSWC"
    b"VU30ALA6iYTKg33B+kRqCBOJhZ8dEg5fmABHFoV/VnVSd6BQMlEooktCCBF4QMTGTEZQTJRswHIN"
    b"bfqd4FJSJebAo7DV2DFjCc8vmbNv5KXaCiK+LkiIiAsrqCHzlDSed8GF8lYZyCVnJSwPm7MSZLA/"
    b"h0aWA4rgTqmC/PtuKnYJti8r2zq3QN3KELSX54iLAtsKt5EQ6MN7WNPFbJhCL5tW4nwFwBNBk4iT"
    b"Ml2TiUqRVFVmFBiLHErxzXoEASViocSzFjjDWVlMnzNgWC3ejGOyjQs1haMKwTM+SVbu2HE0nK9o"
    b"KnX5gt1AV/+xeYbXOoU6LBorhO54zi37qjNjdmWkjp3MvmnECNc/EAcEQuT0hAsqO9pt1ZuLjE7C"
    b"KtEEkMkh+xHI4EoTXk7ZUqC9GEVaj92j8ao/MiS8n5aty4qtqq5ZQaMXwq56m/JHjdgr2iVEbsfM"
    b"JZmkgtSYok2ydPs63yIxVe1NVdYIq3XD0qPGWQXeG3DMwgiNo2Aatpsap06RTSGm3MIKKfKemWM7"
    b"1M6JZXdXSGGN2MKSTDJrNRRgYhiiLBpht0vQ6xjkGF4lxB/TkDf7XSi37Tig1lrHBoiENhzo4gOK"
    b"N3a4d7Kdke1ehiVl1bHck/gMCWBExsPJfrrI3uUdSaZb75CIGzkjv1CDzY+cxSuOGFBMlO7PzohD"
    b"7AHa5iAQfesC/BwPhhVIp3hqxGlxtpzQFaJDhYliF3h8a3sXknT7I2BMtgLs1pysBgQ9OEw+1FW5"
    b"LbFGGsN2suXQ61PnlJwWst/lVujhmpWliX1Idlj15+U+RQdrwVIuUFaaZo9kxEPSdiyXWOVxcKzs"
    b"h15t8bD4+HyksOvmmZzjRysnMy5NtCbnvJScFixNJiDwx1NeiX7uAkqX+9Qn5Avm/AeZyVsOjQMx"
    b"6gmIU5uAFWVQyLVFLlGMa+/PxmEmUn0V7KNc78LlvBnGZ0SnNIWLGAMRDeckHTRqtI82b3zuTGms"
    b"a0AyIocRytzkT8J0JLTZhUttWfIoqqGToByWILhYoiuGJJUImUeS0eW41hJXr4NY1sBRRKku50g6"
    b"GXFlWsE4DujGTgSY0jt6HHaB3GpLsc9UQwiGjTqFLLr8zTFtSBBz6HyMJQZydGlGjyqpKQ7pJ5gg"
    b"luALWtpNXq2nyt/8K4lBEO6MxhABypQZmc8modEo4L0VlnEOvsTIJL8n+Wx/DFuEgxPluJQEcmK2"
    b"kvvalDtRQfQm0+qlx5sGO3yefVW2q2ELPwAWflIpAhqBxY43jCAn0CgLGDo5opxZds/mIt0SG/FJ"
    b"PchbxGBYnbz5kYO8HWwHQjnyyB0iuwDw5wvIEZf3+Cx5D3HK74RhPwA9M9JWry8ZZMSBseqVsuN1"
    b"k1weVCmRyBJ6mmzdwqt9WEwuxEyXsdrUTdU8QpmQb5lzGjPgKAoKEdtn66EibV4x3dCBH5U79Hk4"
    b"Q2SEvXnjVNCXxe1NJDh6BPdpzYLcWo65ZT/9mL0nNGyX9Pqbv//9F/CU6UjwwqXiQKwjEUeqGtLn"
    b"SGKCBs31uDN0oeJBGIylQiorJRf8nAMROKzmLOnS2KMg4l+WpEPG2yQ4y9x+WRoyYQsjeRU+oCBe"
    b"BCqZre2qZIJRkXxEPTIR+0x5Y8YsKqpQE+OrChk0nISLaHpVWazInOPAVk0aqo/dLPYLxSanX9sa"
    b"0pWdSBLpML5jE5dtk6mwu+RUW6Ey4tpXikw9mcfmwaWZ49jk2/vLRcS3v7v6rEsJqMUaSG93VMLl"
    b"Dqb6+VWXmDSiXIwL06EEBBFrQh4xSzlsj4vputuRwy9JWc4PhzAW0jWQAt0GlG0Rr9c6sxeDXW/N"
    b"N2t3uDFEuXNJBXMOFyLGG4Kp0QTzp94bRFCcefLkczaF+u/5atW0zhRXEfS3kNQQUipeAEDxly/J"
    b"c11ZkR17H3N7y2A8MvOQ+xaVTxyPgdFTjYtmj6Ph/iKlugfbcK0R6Kpu9N9QRgGt8aXAkDCOEbCO"
    b"1Cd0w27XQOi1IVAYigdCTQiD8NeY2D45204t49/jRPuI6uJI/4GhqtbGODDmfe5SLcXkJY29uKBY"
    b"TLVORFjjTQR3tX85RrGa5rKapllrVUlQZP+QDF1+zsarRP2g7FeEsH0UZDxKlL7Kh1DFy5Qa19FC"
    b"kJwL2J5QYkXeldVs4PJ/tRdn2/l9XxR3zJ0Qzog1tfCDPKu44mX+5kxl9Qo5dqSn6bQiKPwBDpFD"
    b"NC4QK0xOMM5ED7o6DzVCzoZlFUHCr/WecBSJizJ/eN8dSnKGiCXSc7AVxQ0nvmi6znaukiAPObLR"
    b"Alxh0ruiBBEB05gfR6reSwuhjUJQSeKZiW7qpAdDHasPdcy0ipK90ale2WPeFhXqTmBrSxHTXkLw"
    b"HFLkgqrEcYFggR3F76c+WIxL561GhZP5XnP2IUIjxFmTa1OCELV2IiyqxWVcqdFZAlzkuSv2cmGu"
    b"LCvOUXrhN97k3QupFsIUyyuxniX5waucTLy8BW40vpQor/FOeiAfmdayBLY7dafTu4jO5iX4FD4G"
    b"wY4P2+JSviNxeAkYelshtaGEfgTzDnOahSvsDgUHde8S5mkYil1fWO21pInYcErqjhJDh+V7ugIB"
    b"tuSovsuQurCOmBtbZFagT3x0fgqHEc4uUtNPTTVsRauRpGlaIkL8LUlHOlMgSjHXZpI/PoKgkbct"
    b"HaQBRXz4vouy1EHlK+TGhVDFNGMlK1VZBEBiODUH67/S8mSztCQSgBKNfoW8vjq94sgg9VSzy3bs"
    b"+jhLT//nThRimqtcyggjloQciq2HkPsMtoJbiGnnl1inXpOxour0A13OCV2aBkqOBIy9BhRhZIIG"
    b"7EgyA/l/PakIo4TelhiTaOc1CqFY5h2NiI02G5s0Qk+1DYqVhE+kUi/9fqNgOhsG5PaQtmFbjRN6"
    b"m33HNrCWefEiZyE+HT1xhEbPp2zvbXd5Xbq4kkiJ46G+8rtYK3lWDK3Ez9zqsqBoMJJczVaqB5hm"
    b"OUYbygEJK1KQF1T7/9cz5yLUWvjvtViB04ylvlh7pIfJdOi5zsxme5u3ErqNHhHNGcWfnDG5E23V"
    b"Som1YCYyMiWwJEENfxQyJ5DeQQ5DnUynxVV1q6URY0ozmVyQK5fgjemX4rai4ePL8RSgEKkddTL4"
    b"OD1OD3IQRvifp4epy5Cy5a5afNtINYBGjYj1uqbWghNJgLs94UvFOQ21Z0L0y5vFTFUoSQ5lreoe"
    b"vET9MLlzV2EhGUimjrpRFyRYcErPkXRNvcv46rSiI7qwQ3rUCsknjVodBTC24fIKpaw5mxdl54JK"
    b"EihuVqu8Y8tM3FGk1JHBQGBBKizho2IVF1eOS9iPgy861DOP9yPlJPLE0hmIvyyDXXSC8ZfqjTE7"
    b"yx0p+iUzw3F6ptIKSaWzcc2+3Me5mJaCwRCljm79xQtXj0oyF/nelduEX8rmTAG8ynpoJToo1CCK"
    b"yttJ6hgkLQN/hu5GHnCEJinp5cQzQ6IehlsyFaXdAe1OT5KSMJ5U/gl7l8Ahh6iE7M8kMiTygOUd"
    b"0B6iOftzXoOFhwq7Lr4CLeSKIt+R/hWHHC5SKV4XF+qH6DDqhr/33qCITtnlvKqUWsOgKyVleBK7"
    b"hMK7xM1gy0gPuSEB0734+lR5A9C64KYYaSQbfRlT8EKjRC2rDa8yQt66AyVLtrlLvMlOucae5JqB"
    b"44I7a9vXffMa/yvlX77kz2GY1wHkZS3xAkkEWi4qEdwdyYSnuUEsoRSaxALp5aUVabtmhaHXpNlq"
    b"VyMRuEbDN+prR2KiUFdCPATWLkRGUfAxAhB+ApIUcdij1AwMDuzjJcdZDMyRJN9JCnrGXfpEdpFm"
    b"Uw5EYVSGhGA8/DDo0AmDEmlorh3shq04GfyIc3R8pZPp0SvKp6ZrYUcanpkl3ooLZlBpE+tV9zDp"
    b"0nxLGneKNqJNQ38nv7twyasuaECXOfYpb1bOVaGtDSTFCeu5xKJrLkMvUAWJskE4CfQerNyyVr6T"
    b"oklvPZRa9pccdmqKZlj266HieqkuZB3oaprqSfC8zp8aLltkyyN/dN02cQWV624I6olrtaISK7g9"
    b"02ySICqpqzb9fse2YiNVdERevoyIiHRV5V0XtXxMR2EJlzcefG/DaPNMDsEMknN7RSi4GT1q0Avj"
    b"oJQrst8RxGfNxuS8k0wAAc5tJlqVD8BQYeTNyKNoH0HuLitagwMGUTuICXYBlHoxwJoWVCGK7DcQ"
    b"cIeal2ZbAL+h/bRckTMQbE2AxjioKWEzqwWMDkPuLFwJv5C6HXGQFyyp+N+uPChmsahCcEvHaopu"
    b"CtpY2QKJgan2gWnFevbN7gW9IvjKsLYTuEXU6sRBBKkXstnRfqdDD5RpJwEQEsjkB+9LT2h32qKz"
    b"CXiICpluQKmiHasZTTb2ZT1AGAw1y1E1fENAGSzOQss4KYmG1EZKF7VVRMSAhIrkXFKaw6nNpWU3"
    b"P80HgXKWKHPZ5lokulgnSbT6QFTGoVgn9NXjw3aS1ourctbaTStuYIzdUBsUWfvSuUW+mU9iijrM"
    b"3VYRJ2rFyDqOjoamH7YBkttEWYtWVkc6zpt2Wl+1s/1Q9ntvlxrxoLlU5exoeDOFsGPlSD+RJfw/"
    b"WnBszVEVJudO49sOqRxKXNrY7zXi62eneAwt+IMmkOKIto/0cEzHkHNQq2LDXdeNJIAjO5De7rkZ"
    b"TJJCMPb2MW+NaFKbrsXyTjDOhXu+3CwOphqmO11QdMfdzadzX7YUwx/5UaeOflihl5vREo7L4uWc"
    b"Sw/bkcvRXfaICXrYIYQstRGa+2GeDWzj8dBGR9Fb8nQ1VVIyB+jx1Fz+0aJQFN4Byo3zCdTcLyyH"
    b"RZ43tj5IQkFQ2WrtCylcOrOALLNSDMXaisV9SB2L9HEbESxPZVNxIx4fbqikZI97OJsVqhvXqoxD"
    b"VV2+apuuixfSEo0XeEGkwsl7dtYwB+TivOdR5pHOJH7Zx0TEliU+cGM+CHM8cEDzI9moZvh0wbAZ"
    b"F86p78q7O8+RhLTrFUQb+jMAJkSRNmOaGGqkRTjxjgClFj+op8XY+ttFNgt5mQfrAqqT6LchwYF2"
    b"sNbGpTegca2XPghvurYz0KzW40hHhTQBcr1hbaXpp7VO7YWU24U5DoR21WkGSnNNrmxCcmIu3cFm"
    b"JEkDqRmRJrfQbkxmszTTxMXqcSArqcXwveCScJJY30HPE6raWNPlR2E3Evl2VepxDa3P22q7Z9s7"
    b"DmRTPuSTjBPocG+itSVddQQLblLJI0wSaV8wB+UhKJ4TBeSOffwEJwtiJFh1rDQGx8h1boC0opD4"
    b"3DZaLnN8G5fPznttUYKY44APkvqCNsNpibMTVKLIc1GzULer+aLmWcGg9+DE6cwK8T+e3QFHld4X"
    b"5yHZwCEWcwJ8yAkVilPNHWtchD2mNCeV1t1x+tCNeuB479G6j7Cb1m31uEbuRHGlb24gj+vHHucd"
    b"ZKiMK4JDHQtBegRAf4vcJaCGc1BGASZ4lJanCwi3uLXPXxQUaZkS/ykkP95rQRJ7k678Avkt5Ly4"
    b"TaZ0RoSPSblyZheoGRc5dNmbv7IwffPLGIa3sDFdEuLOt5uy29I+efUVWnii8LOk3HzZi6RGBV1+"
    b"IgPv7tyBUH/YutjiQbaVF9GMq8vJCuolPQfLIxdnu+wD9KtzsL+veSNK8b5XooPpJh/L2ju3gWYV"
    b"/NBxe2JGhRuO4M8ShlZorC7C0DO37XVR9NCHYQSQ3I9fCkcpzuly9LK1h08CG6wqcfEuhgFg6nwr"
    b"/5D0Ps+6iG/C++gO4LCRPUcZYSXIRLIFxDaqqmvJmcHxpI5R3Q9OI2yV1vCEQDENj4tzqZYg46cL"
    b"+65jSkPCe1snZXXhJNEAE3dlGpl1yN+nNR6Qzl1y3OzMddmOrlErb86FC2XWFkcfeC7AVtU2gxNZ"
    b"7SNjdO1wXe/j51RzSsnQ0XV9szEZSA1XsGu4GD8cRYDvDhApNypiG1ebsM5GeILsO8i1iYbmjS8F"
    b"ZfMGZ1dORPzA5Yh85W0IsDvlmhYAFly7pE6P0+6llNqL15OrgDhWlhQp6JM1b7k4i87gzLMjBwkC"
    b"W/WsXIDlrjPYJgfT6Dx8xi+YRQuyZSGFAPD+Qo2ytLYkNdGx6Rfp/2OKJRBlevIoKR/300az89LM"
    b"PJe5HYEafhvXsHcDMd6TFuycgj+OUTC4YuY2R4I5p3wDPq+RsVCwDnwRni9gi5uZplwyQijgG9Cg"
    b"wgHhpjMkhCH0dXYdlZyQWVwxRZmDZEdiKHsbf3ZQkBXxTzPmqKkzqLRkXRPDoeU2KnhyNlflM8Kt"
    b"ey3vIifgrZEYAEg0zmvocTWOQEqD4f2PC3ZQylriEXHdB/ej+Y6RMAtqdHPa0M0wQBl2ZEx7Sjos"
    b"A+ShWjBd6YZ2fdQ3Ik6+3834yVPgSExxEVeN6+XSLqteD2CTKVquNSDi+Lh6gUUJl4P7AYzjVigr"
    b"ERYEtnL6226TiK03Evr4GBWFsfGO+kcZecju91ETsVdLuDV+ZqTkXaNQ9dgAzDhGxPEFcYDPjTdC"
    b"JaGskWEOqJGzUh21I5Ouqrowaxn4E5CYNvaEXmBQbS5jBKahtkoXN7r4mjxvZm8w0FpzlvJsQAfP"
    b"DNra2IbhuDJmGErD8C8/ZgVbNeteb4L7MTyJfiLftmGsJ01IfwqJJkJidKaDI7k3+CSl7aKzmD8+"
    b"y1RuvBQ7YV22qGwptzbM8/PKTWUNLX2SYlw/rdin58GPM2NwQ9PBatAEY1jV4/fnGL9GKz4InJ13"
    b"nAUoCe4F+YC/HvBYGsjxYb3AlcCYZzIEf3UiB6wp9ss8Klz5ht+AD4rTHHLzhdMr/mFeiyNyfu9C"
    b"Sy/6+KojCphGbW/Zf5P9xH5p4yeE1PY5HdDqxw96LZtUL8OaAc7+fsHRvx23LsHTUGNU04cfpaNt"
    b"1C7haifj5IjMLjvoNSNFKeUqDlASmNzll1Qkhe7HWb0iuZlLKbeflnJYcsjRfDaZNQuRuxQXweQ6"
    b"Df4gAW4isBQeDG9iIe+pw4UNco+lqIEb5gVnS5PRQ3EBMiS1cGRafnxMg0jN+agN02ontniOMnAn"
    b"4n030VK69Y5cQjpJDsE4P2NHWg8FyQcNplMtCGC7QhVWwMEB38u4IS33haU8c5pPH1Fj+n3zTBSN"
    b"8cVEaK7whV/i4VRe8pzotUqzKol2dXKqiwzcQ//SOxNTbcSdemtBIs56KzLohffsBklFsP2VIDbl"
    b"BZ1OWrFZFNqepC+zZKwt92mHU2RDxjPGZnU2QRQPzlPI/0zE4o8zQj7nJPtIq6YMvIpHcokJloz1"
    b"g97HqE6puiWX0T3DFWpieByusbXto1BOPO+L5dspdjU6gxh1zK5qq84OT6dl7pIk6mXIpYnPCiEc"
    b"XXEsPqTSBMW5/gHU7YBFgzx3/QaSa5Fk+/4VT2QsuItSwjCc5CQvgoR0IQ4C5upxJG6IJt/p8Exv"
    b"cZH5XA2AS7sUx30VJxN18RE8uZ6ACeaMGf+di/r70WBibfnzqt6u1yi5OjCb1d+G5DniQnUu86Zt"
    b"hj73OWrJh8rnvvdThnQyGkKdQhPvHzgW03XbZp9XmilrohI66d4KsJg/HA0QrAx/YkybAIejzEzo"
    b"1STFwpxYei1tkHL/XJHKP3PSBy2lA0IlSJ89OifeRIa6PhwEdhGyIFPRSiRWpGpmGiobeRx7Xun8"
    b"4y1XN2nUKx4Kh31C4ZN2lbx5c5HdurGWbuRcLVHHpp24wpuRyQie8hFd7gk44saPlHQ0mC6ZFnMb"
    b"JnByG5soHqP8NnRhNmFohHAlCgomcWMMtR+/53tIkifDMJwY7ZqlgnxLfm1I8dgimsZRxSFsv/A0"
    b"FC1VMt80X6mRQ7cDRSqmvvvt1GkKDM/jtGB042xwkzFXw9z1LeHmsGR6PSYODhdKj7SmxcZImRpE"
    b"ZdQgdJlpOepJkDjxxAPARoaS4/1jLb1H9haONnHglQ8UhrlM9SKbahIGvoXCChde1Tmj0DteTjOP"
    b"CdIkZNfxI77gNQkVcKphpD3n0t4ZoI6MsJzjGn78AKYetlWBqVpe6ryWmTmJyx2J/pQIT9AgjAsj"
    b"Iy24Lgt3qYwu1e7M5cLiYeyLTKV4wSSR3fXgpwhDAlmu+xOV3iJEeFisU1ccfZqkhxQhUe9deMTQ"
    b"o1ajU5J+L3uJv2l/GYoDGnVfpuJKNWr3WPZuOXF65sfO1W7lA1tYpxS7d2S/J1vn0sjJH2sYNO4v"
    b"T8SzJ89lrO2E73niB7mnN8jFDWJd+AGZOnNdatVPnPbgXI404mZ2XvdYldPIfMUYFYKauwIrscHr"
    b"A1ClS+1kcWpsMLghEWkZMacAjJ+VzmOCUTfp+qKLP2xJ8rXtuXE1DdEmo5YHr6S5ygBPcjlJGUIM"
    b"pvcJVQRHo9JX1yB24qx0BsQcMR1ZNw+FqkgGPorjYTErVHwULkhRFC1tTQLJx1ZHBOFHuEdRGD+5"
    b"7Oxnv8M0lkjmT0ikwzICPx/bjZ42Vew2eY8otAJg4uG/xsTiBhf6yIxmUvxwHp3uCsXgQgAj0sp0"
    b"CkpUsmwOwts69FTsLxdzEcCkcfBYb6VJ3xTt4x3WuNSjRDsnqRkp4dZB05oUNbpA6LnTuAssWSGH"
    b"qrRPNhRhKNdNkQbshlwKssRspmPWNhmTCuVapUV1pMf0okW2RdMAYgeZfTdUkA7O16In1BOeHrjO"
    b"3L7O+cNjcojNgrg62HbqvB4boOMNND9ayFX7eticwjA+oYGzuml/sad04E3XR6iEP7wh4JfdKIQt"
    b"pKwhHwznCt0r6RZi+HEgnDPVfrSBGqyzMWJoqwnmj7Qlq5Sm3XNn7LEReZKnk2F/dLqoekgqw6d+"
    b"4ks3dl/Etu7CUK8wb0Esg+DojMqTwndPfAlSWo562gu5SJ2usXIQVGkkh43X4AZDMQXy9EnAqKBS"
    b"c4FGc01LWJBaRBraHTlO5j7AIQCGkhNWg7t8v+U6pyYkFHSHZCqFjqZx8VUdEriXwnwVK6MZffF+"
    b"47XFNpu6keZeVIfAq0gSF6c74A4XeJ1yW1JMPmOBz9NJD6VC2omXiDRfRKvFO2dSP1fyaN/Ch5dk"
    b"1D9+fS7KA0kIgoNbHKXEsy6Obe1Z1H8/QkwP16bdOZnI2dkjDKyJFMBmOUZQyEwHJdAg1kyTfEjA"
    b"4+Q5997zNETdf/qP7FPe0m3ho2muvmjjR8tGYT/fqcHD5NrB5/jUnY5KddhBRgFkybMZ1bV0tgO5"
    b"Dj5Mk8wV18IUkm3eREbpclw56cPucabTHVQHW7356QLDre79Z4zovm94mtsr/jJX0Wyd/Taa9ych"
    b"ikLnlGVnzj/kcXYDT4aRdEZkPwZgz10VGwofinLly/LdFsdSbns3344QCXWLfX1s6PS7F8H8lM82"
    b"OEGTqviu0fEGrrWsK7dD1efuOzFSqXcwmSsJCbgRKa5TDJEKPnp4TdXLQVw+Dv8ogPiGGQ8/uTj+"
    b"vSZGLQfwQk7cddfJt6tg65JHjxEqzo9jE8i3YHqLJ+JZeosEzDZS+WZUiqldKvq5OokFerTxZ350"
    b"Jf+hiwRL3gXnRMO6BRNLdaarUUubx+JpRm9+vkBFd7Ay8V2KGTzI5qXPU/yvCgG9QTkekVJ/U4mE"
    b"ERkH+QmnjZIvT2h96tHParwIfqbtZGKjmTCXI8x6jYcvjD7goL0xx0uQORUfF+knEyi4UMe30B3O"
    b"DHF1ta7W+tDc/xOnmxqfePuZ64FWtpWyvWiYv/e6vIslRQQRtIoXrR+X7iqhl79cZHeWbpjg/j35"
    b"9tIoPPLwwrcIpbJVB5C1upp+YAsZxrhg7A++wih8hnQOAKf/5QGHhONkHZwPFdpuXB8mJO3KtvTd"
    b"vFq16KNe7NwASikixAsFOkoq/oaOfM6Et/AfNRKbGOiO8kyOPAk3MhmVjQdQ00BHx724J+oBgwV9"
    b"5ZfxxeVaA+qsQV9CLC+kHV0jXJkRriYa1kUTRIh6+u868gz8wKUMhlRSc+wuivGc+OSOOtyuoMpB"
    b"aDyErZvLlkDgKCEEShO6MYFuDgvjvM0ueIK1m2LUmXqnSSiUj602jctSuEU4/uThM8fgi+jaqfYY"
    b"woMLJIr5vpcvLNJf4GawTJBPVpnx98xeIH0soYX7Uz/O4/v+VafBlLTsK02qBjTFJR9RjN6pO0EJ"
    b"r+7ecD5/rEau+EKdueUPAaw+aswkrpbk2UVanWviuv+ofqhukjciQ2FkLqFrWQugmyMVLmwZiBT3"
    b"7gQfy301lAmbrJeEKEXY/fXCl4YLKX3R4nARcR/nd/NscZ9d32RfZnd3s+uHr9mHmzv8Ibu9u/nt"
    b"bvZpmj3c8M/zfz/Mrx+y2/ndp8XDw/x99u6rmd3eXi0uZ++u5tnV7Au+nPTvy/ntQ/bl4/w6u8Hy"
    b"Xxb38+z+YYYXFtfZl7vFw+L6N17w8ub2693it48P5uPN1fv5HX+h6gfanV/Mbmd3D4v5PeD4ffF+"
    b"HsOUTWb3BPYk+7J4+Hjz+cEDb24+0CJfs38trt9Ps/mCF5r/+/Zufn9PANDai08E8Zz+uLi+vPr8"
    b"nmCZZu9oheubh+xqQSejxx5upga76bNudQBD63+a311+pB9n7xZXC8IXPqv1YfFwTVsw7mYC+eXn"
    b"q9mduf18d3tzP7/IBIW0CCH8bnH/r4xOoIj9z88zvxBhl9b4NLu+nGOv6MyGrgnHzb7efIaKoHNf"
    b"vU+QAkTNs/fzD/PLh8Xv8ymepG3uP3+aK77vH2hRM7u6yq7nlwTv7O5rdj+/+31xyXi4m9/OFnfA"
    b"0uXN3R1WubkWMvrlQorLfcLjylUti8S4BgXNfwd9fL6+Aibu5v/5mc4KKslSKsH6s9/u5ozoiCbM"
    b"lwUBhtvzhJEJYUz5FfpDIIyvRGI32aeb94sPuBYlnMub69/nX+9NjBXCcyDZ2bsbIOYdAbJgeAgC"
    b"YAn39n72afbb/D6iDOxp9Cvb0+z+dn65wD/o70SPRABXgqrrezorrpZ+oYtkM7pjrADilHs0n4kR"
    b"QIDXjnBob/wuBvYs7H1IlNnVzT0o0LyfPcwyhpj+990cT9/NrwlRzGOzy8vPd8RveAJvEDT3n4kD"
    b"F9dyGzgvs/ji7r1xTMZ0+2G2uPp8NyY87HxDKMSSTIDRTcgT9+dTg8vPFh9oq8uPem1Zwspfs490"
    b"Fe/m9Njs/e8LZkfdh4BcKE7odLyC4lGo728X8m0RfBLDU+D9QZNKrLyKROj5jhg8WCWEHMrv/ZAP"
    b"qbQNX/QTw6dqMOxAmldksrDWN6sUlnYpKRE2MAntswRAB4xwEf9fDFRdKX92zSKYylk10gmKxpbv"
    b"/I2EziCmteyaCv3zPDhZzA/Y6OVTWUWwH4mZRDZYKCRNeoNCY0GKiNDuLBnQg/KzjD9aTNp+PNb1"
    b"yH9El3zPJ75AGP77KN91mjGKpJzrwZWWf4XKuyZjVQHoogySfteHfYHn8FViV86gn5zWDIme45H7"
    b"HDvS3I3mX4Zu1Fs61cxI18sMIxTubTii7stANS9W9ib9dLaYQ/y5TYRG5XsS6Yd43ZdVfX6pi0vO"
    b"H7RGbIqi6lyDgcF8da1T3vJ3NYELjkN3+RpHA8T+7a17mCwq6bbgIqKozF6+19IlX8Q0bH9pNDOa"
    b"apgOJeaVeAn9PCjb3m76G7s/k1X4FmQlHjK+H7hr2KmT+IKbnrMe/GxX/pQtbFMlrn8Cnfy+m/EW"
    b"nf9Vx+1EuvSyLe0aGZTcDyfSAPnFrzqVyFlZZ5fn2T8xne5X2oGXaFz73q+y74N+r9WVbSTX/Q//"
    b"vfHkkss+/eCy9g0dzyi+aCXnXeJfaMPPaRt+6tyYg9BCqKOQ9qOztN30/NCzuTiOgHBO/+2qDdIL"
    b"rkmHvXGx7Ok6ZSot/FFnrkGDOJPtre+rxQQNGa6pwc8grKTtamx5EXJPGV5ZMLzurfUtji/54S6F"
    b"IW6ymxqFfERM176yOa2sO72wzpWLZpEFXIo7SMSOygeb/XPT97vuHz/88Pz8fPFYDxdN+/iDq/f4"
    b"4VeCaIbaPXTdxLNNMEVEhCcHwOXb4zz0HoG+tqkxNgofC8l3KF2hw8Wachc7olpmXcXRlqkTc+5r"
    b"KzkQ0vZGmZS/48qn4nZgTIbteXCjTDuNJ/Zico32rP5T9/31T7PiASHKbGZG6uzd/c3V54f51dfY"
    b"lXnLl6r3mfV7otD/y598f351EZYbM3TQHSzMbYV9JDKZ8DevIOzsu6J9KOFtvN3qVQwIIR+hpc1+"
    b"h3gj5wvDZwgdfAyDf1sJ0H2uPm51TifCngh4ZtnNmi0Rn9kOQtNtbbZ8BRhl4Rzbt6ref/u8COOP"
    b"9TsODNDAwYZsQhYT0cWy+T7xhZMKMhebotaSd7XE2M0eJQ0asA6fQXCf9LPtORd1wcElySHfW+O0"
    b"F0YgyQgwRy7ByJuEPL6f644RK/6jHx98Uj1lHPm0c/RdSTHR8At1qz1349PbxKXmj7lUYocvyBof"
    b"9JFat3hcGImJ+IJkdlj0ZWr3hy7qlogkc44SsbZBJtPqh7322m4ng3+5sxNMytgQAc21RQIJQtnS"
    b"yR121GRRr4FI/WqOLu4iWsJIz64a4VkLDPDxble5AoRcoRCsPRXfQ52QzYsj+RoM1eGeG9QPc0MW"
    b"imj+4C6eN/vXhOXX1eOuutj024ou5/8B9wd57A=="
))

TRYSTERO_LICENSE = zlib.decompress(base64.b64decode(  # generated from trystero-nostr-0.25.3.LICENSE
    b"eNpdkUGP2yAQhe/8ilFOu5K1bffYG7HJBtUxFiab5ujYJKZ1TASkq+2v74Czu22lSA7DzPvePHJ7"
    b"eXXmNAS46+7h8fPjFyjaCTY2/NbTQXc/tSOk1u5svDd2AuNh0E4fXuHk2inoPoOj0xrsEbqhdSed"
    b"QbDQTq9w0c7bidhDaM1kphO00CEsdoYBZbw9hpfWaWzuofXedqZFPehtdz3rKbQBeeRoRu3hLgwa"
    b"Fs1tYnGfIL1uRzATxLu3K3gxYbDXQJz2wZkuamTY1I3XPnq4XcNozmYmpPGUgI+iV68zEn1mcLa9"
    b"OcavTmtdrofR+CGD3kTpwzVg0cdipyecint8sg68HseoYNB32vXDXeqJlEsMNNwiStyXwZ5jL3nf"
    b"BCM6Xt2ESJ1meouRJeIP3YVYidJHO472BVdD5NSbuJH/SojCq/Zgf+mU+fzAkw1odbYQH+Dy8aq3"
    b"Kz+04wgHTebAkIvxxtLbOi7ifcCHN5j9xbrE+3/NB+SvGTRipXZUMuAN1FI884IVsKANnhcZ7Lha"
    b"i60C7JC0UnsQK6DVHr7xqsgI+15L1jQgJPBNXXJWZMCrvNwWvHqCJc5VQkHJN1yhqBIQgTcpzhqC"
    b"Yhsm8zUe6ZKXXO0zWHFVRc0VilKoqVQ835ZUQr2VtWgY4gtSiYpXK4kUtmGVekAqooA94wGaNS3L"
    b"hKJbdC+Tv1zUe8mf1oqsRVkwLC4ZOqPLks0oXCovKd9kUNANfWJpSqCKTG2zO7Jbs1RCHsVfrrio"
    b"Yia5qJTEY4ZbSvU+uuMNy4BK3qBVspIC5WOcOCGSCM5VbFaJUcM/L4It8bxt4l8yeykYLVGricN/"
    b"Nz+QPxnUUdo="
))

TRYSTERO_CORE_LICENSE = zlib.decompress(base64.b64decode(  # generated from trystero-core-0.25.3.LICENSE
    b"eNpdkUGP2yAQhe/8ilFOu5K1bffYG7HJBtUxFiab5ujYJKZ1TASkq+2v74Czu22lSA7DzPvePHJ7"
    b"eXXmNAS46+7h8fPjFyjaCTY2/NbTQXc/tSOk1u5svDd2AuNh0E4fXuHk2inoPoOj0xrsEbqhdSed"
    b"QbDQTq9w0c7bidhDaM1kphO00CEsdoYBZbw9hpfWaWzuofXedqZFPehtdz3rKbQBeeRoRu3hLgwa"
    b"Fs1tYnGfIL1uRzATxLu3K3gxYbDXQJz2wZkuamTY1I3XPnq4XcNozmYmpPGUgI+iV68zEn1mcLa9"
    b"OcavTmtdrofR+CGD3kTpwzVg0cdipyecint8sg68HseoYNB32vXDXeqJlEsMNNwiStyXwZ5jL3nf"
    b"BCM6Xt2ESJ1meouRJeIP3YVYidJHO472BVdD5NSbuJH/SojCq/Zgf+mU+fzAkw1odbYQH+Dy8aq3"
    b"Kz+04wgHTebAkIvxxtLbOi7ifcCHN5j9xbrE+3/NB+SvGTRipXZUMuAN1FI884IVsKANnhcZ7Lha"
    b"i60C7JC0UnsQK6DVHr7xqsgI+15L1jQgJPBNXXJWZMCrvNwWvHqCJc5VQkHJN1yhqBIQgTcpzhqC"
    b"Yhsm8zUe6ZKXXO0zWHFVRc0VilKoqVQ835ZUQr2VtWgY4gtSiYpXK4kUtmGVekAqooA94wGaNS3L"
    b"hKJbdC+Tv1zUe8mf1oqsRVkwLC4ZOqPLks0oXCovKd9kUNANfWJpSqCKTG2zO7Jbs1RCHsVfrrio"
    b"Yia5qJTEY4ZbSvU+uuMNy4BK3qBVspIC5WOcOCGSCM5VbFaJUcM/L4It8bxt4l8yeykYLVGricN/"
    b"Nz+QPxnUUdo="
))

NOBLE_SECP256K1_LICENSE = zlib.decompress(base64.b64decode(  # generated from noble-secp256k1-3.1.0.LICENSE
    b"eNpdUktu2zAQ3esUs3QAwWm7a3a0RMdE9QMlx/VSlmiLhSwKJFUjuxykvVxO0hnZSZACBgy+mXmf"
    b"GVWdglRUkOhGDU7BAh93QRCZ8dnqU+dh0dzBty9fv0NRTz2kuu+VhUXn/ege7u9HBM+I2WVjzjhX"
    b"KHvWzmkzgHbQKasOz3Cy9eBVG8LRKgXmCE1X25MKwRuoh2cYlXU4YA6+1oMeTlBDg/oBdvoOaZw5"
    b"+kttFTa3UDtnGl0jH7Smmc5q8LUnvaPulYOFx0CvL3/K28zry9+7WahVdR/oAaj+VoSL9p2ZPFjl"
    b"vNUN8YSgh6afWvLxVu71Wd9UaHxejAuQdHKYgryGcDatPtK/mqON06HXrguh1UR9mDyCjsB5zyFl"
    b"uTcWnOr7ABk0ep/zfribe8j6SEv1tzU5Qi6dOX9Ool1wnOyAkmqeaQ2ubVb8pRpPCLUfTd+bC0Vr"
    b"zNBqSuQegqDCUn0wv9Wc5Xr3wXi0erVARxg/Lnsrua7uezio28JQVw8BQW9xLMk7j8fXdQ+jsbPe"
    b"/zGXqL/hUObrasckB1FCIfMnEfOYDslKRPCKIexEtcm3FWCXZFm1h3wNLNvDD5HFIfCfheRlCbkM"
    b"RFokgiMmsijZxiJ7hBXOZTl+5gK/bySuciDRG5XgJZGlXEYbfLKVSES1D4O1qDLiXOcSGBRMViLa"
    b"JkxCsZVFXnKUj5E2E9laogpPeVYtURUx4E/4gHLDkoSkArZF95L8QZQXeykeNxVs8iTmCK44OmOr"
    b"hF+lMFSUMJGGELOUPfJ5KkcWGVDb1R3sNpwg0mP4iyqRZxQjyrNK4jPElLJ6H92JkofApChpIWuZ"
    b"p2FA68SJfCbBuYxfWWjV8Okq2ELvbcnfCSHmLEEuPFD26YTLfz/kZn4="
))

TRYSTERO_BUILD_PROVENANCE = zlib.decompress(base64.b64decode(  # generated from TRYSTERO_BUILD.json
    b"eNqtV21T4zgS/j6/QsWX+wCOLflF9lRRtUARXmaAMASOnasrSq+JiWN5bJmQbO1/35YdJtnZsLd3"
    b"t1UQkNRqtZ6n+2nllw8I7TViqubs6UXVTW7KvY8IH7jpiokZmygY7/1k62VjVW28ilR+aRpb73U2"
    b"mz17wYDEg7CfbiuwUGz+JMx8nlu3rGmieKQFi0nKQhKHinCpZSIjzONIpDjEgmGsdjp4auvCOZla"
    b"WzUffX+S22nLB7Doy7mxK/8tPr+39/+702pVKNYo+cS6UElAEi+gHg7HQfCRZB9D+rU3LHKhyqaD"
    b"5Opi3M/lZdXaBqb+BSOEfuk+/xp8nd1uCLslVotp/tK5aExbC9X42568zpPX7xrYyWqzszffhqxW"
    b"kxysl4Oymj83A1NP/B1h+Z7/vlPY+ZSXVk3q3C67oKYsxsQrvz5kw8I/e2ynF7PLu9v9xcVMXpkv"
    b"n2+wuRvff/b3X76aup0x86yO5E019hOsUp49rLhNP+OZvRqzs9Hp5fmCHJ/5x/HxyeK4XRwebl1n"
    b"ykicuCMzThShVLA0DFSCswALzrMgEaFKiYqTSOIU8zBKZCgYwxmllCgacCFjCgZqr3P568Ff5EqY"
    b"Wv0tVDlHfxdTzhcQ9a7L93gqbj9df/OnbP9lmMxuv9YVe7w8WxWr189DfzjNV2YZy8Xl/c+3xezb"
    b"l5qP2sq/NC/ktBo9+iejmjzua5qdvz6sTDlTZR5evc5P2tvdPGGcxWHEg4BEEdUZlVxHkkgVkIAx"
    b"EWZhxDARinIYRBEXgVZAEicpDsA20v+Zp9LwQvmNEhUcOcM7WQoHeBD8KUmdF++7F6/b8b8w9EM4"
    b"wM+fOn2Po/0hze+ovb9i12ePQmSP4eh5/vzS3paPp+3d88mX69XDwxF5PRKfHicnbBTI859X0d1w"
    b"aaPhp+tzpWlzM/L913xqFmJ5d3dHR5+yyW6OdCxjHdMgDTnFOApJBpXDRcZYpliUsiAMcRiGVGQh"
    b"6CYLsYRCygJCIh5TTaM1R/D5704JVQmYOMffs/V3WtItDwCwvY310yaaMJOgzQnTnCRUai5lHIYp"
    b"j7mMA0p5wlRCaJaKJAgkZlmYxDRLspBjnXLGOem9SlXnL8wCyzskWeeFej++uqoGttkFVAynaaWl"
    b"CBKaRDHICtOERjpKI46Vgr86TIOMsgT0iNGQSfhRlEUCdIdHcuOzauvK9A3kSMoGTVSpagjXlF7D"
    b"tEJNyxtR55WbQQK6UtlWB6hgjfVqY+YIOhVbIpk34IUVB4ibtpRKoqrl0Js6R8jWUCV5OTlArJTI"
    b"lOq71dZp3dTaXaMK7VW14QomvrV5DZuRemXCotOH0+sxYkKoyrJSqM7lOkgOHqUqAOp6iaxBdqrW"
    b"u966N7p2+CImWQVwD3bX9BspFbPwDtmSzS198wCJF+XpvGRFsRx0pjuJklqRSKeJVGmIIYkTnOqM"
    b"x3GGQyU4iAsLIhJGQqZZyqWgLMhwoF0OxSpS2U6irthMNcjBP+jCQLlU88pYSOAOjknLagalDEaF"
    b"EawAUNYC0fOxmKqyA6ffDQC52Vo9K2Gb/weUxoiZsl6RayWWkCzv46IiaIiS0yigKcWxTDCILwUE"
    b"oNpwGshURDrANIhigQllIohUKHVImY5dkgc7cTlxCVE0qFKldBlTK2HKEi6FbD4HDV7nSuPWG9QH"
    b"C5Ma7tHDAVndwXrghiXkTgU5nNti6VxB/lhAFFbmSBtIIrB3O59NXg5+VB7e5oV8ssa4V2IP4nav"
    b"UE1nsL7FH9p48rbwniifPbSr9n5hZTOZnoZGXGbHTTq6NkMcnl/fxuNHfpqTo+nLA09f7/HFwmZD"
    b"02TDUzbXRqn91h/fNCU9u/8nAFusoqQknI83ovzjs/LDOh+gX03aOaTZRsr2PI9D4RZvjxIYAzhz"
    b"Zg9zyILN5KQwnBVeyebq8EtVjdfpc7319ASrCiB12w95bRaN2lqxcLSyh6qBtzDZTM/zMtfLzbhQ"
    b"EzjFvbldlIcliM1mUUxZ3YCT1up07ztVprXwXn5fhd09BnDO4K1P9Bu2GwWLdJJmKhYCx4nOiMQ4"
    b"ZThN4AERCElBhgPJCQl4EhPMMw0LIU80DxNOeCbXb/62dGn6pF4hBpCVpxxquu6h7iMtocTdcG8M"
    b"yQpVCPkrvbxEFxfDU5RDJiNpRMcPCCHw5q1pdKr41oSQ0WtNfKMA9fdE67dIM0AXUBXraLal2J1Q"
    b"IlOtFRt0pQE210Xfx9NVmDRQJhArFA3wCRLtaqsX9spASMt/NCgH+Xdl6CTLLkBFitz9u/7eg761"
    b"DERk3T8GyN3XMT2HM2v1kqvF7+/Uf+NBjBsnZzX8VlC5yrUTCF22IudQwwv4joZGN3cXj6jTJQSp"
    b"2q5Wh8EAQZ0d9JN9j1rXZ++rgZzx2kpCtSNX0Q20MHDn7Ny6u2nrQOZLNIL6huVeTgDC0skQzJUW"
    b"FOLXD78BzbiK9Q=="
))

NOSTR_RELAY_POLICY = zlib.decompress(base64.b64decode(  # generated from NOSTR_RELAYS.json
    b"eNrNVk1z4zYMvedXYHK2pdj5bHrKJjlkut1kkrSdaafjgSjYZk2RKkk5cXf2v/eRkpN02ybb0/Zi"
    b"0dQTAD4AfPi4Q7Qb1FIanq3FB+3s7ilNR2nby1rLg9Qzjtjbne5Nj8Z7x+PJ8f3k8HR6cLq39/Nu"
    b"BrbOaLVJmMtHVtFsKC4lCM31Wsh5vdA2EHuh0LWt0VJTdHTvNyGKdwXddBW+J23XOnJEBDT3vGjE"
    b"xkCKrXWRuK5hiLy0hpXgaXgTit5714bohZtZcJ1XksJYxtiG07Jc6LjsqkK5pqwbF/8o4+C0rIyr"
    b"yvnxkVQHc8WH0xPenx7uy7Sq5/VRfTCpDg/UyWR/ongykbJlteKFhNI6+CqDV6W2tTwWMfQxRAlx"
    b"1khcujr5vxUjDAJ+79jouVb9qboggeKDo/RtK/ixkSrXYVGTAi848OmwoDOQVQXldZU+csQgRcKS"
    b"PNvaNdhptRptwe+oTRwGsA5g0AsLi5c/Xn64H6VU9HxR04WIZey8pevvKPpOkuV3BJNUi0G2fIZL"
    b"yiLJOpm+uiiVszEtgT3L9iyijksKOAKdv7++u+wt6ACkFRULusbxysv8xjgrVDtElhLZM7LJMWJl"
    b"FwWdX5EO5OZz/JXe0hbtOwt/eGsFvPkVJZ4Luu1s1I3QUtjkOFr2HAV1lynmJ1IDNzIOTq0kkmvF"
    b"5zywwRdmPm69q+Rb2OdIaAC1euF3qLPsG57HA8/+n/I6lGEQv9ZKZga8mVQE7xAryXzufOzTk0oc"
    b"lY0K6hSSIAXdg2yE8Rs4oyUn3+QeLNpwqVskF7x7ZGKUSv/u/VmKVdBFOgOxMXjuuwEuf8E/oo/5"
    b"F/t956VQHkLqBrRB01kdtYQChVyAGM0m2+jxmSHnZ4ar/ggfXKB/RXXevOy1Z4vlM/ipN2uZc2fS"
    b"PZLK7um9cYrNLGU1mXrBdC5eYqWkjWyVlEN9bp5ykFP27MmgAKzazJpExHT/JO9/Gr3OSNv51kjm"
    b"L10Sr1Fxk6F0m7Bvk/GZ4a/PyMH+5IsYqbrULIgZhWfkC0rkvEe+TclfTf4PGDn85osY6ZOYL/4i"
    b"3wpvNMwrsL93zBb89ek4Ov4vdNQMMSm0e42Li4R5m4Wtqa9Pwcn21sDvr/1g4/Wa+8kmNz5tD5EH"
    b"E3JVuvSFBtmDmtHVTZpVoNQQotGguz/cvscaigXAiKTFsAUrhnKxbKVhJRuAtpobyiyQSSWwq0BG"
    b"zHPYiFYYHkZZJVE4GsL8GOmRIi9CQXdbUR2I2Ao3BGM7bY1xXL9pYS2L9JMiZjH87LP05DS6OQtp"
    b"5YSJTjlDDfsVRoUUxDCOWGeDIEzMM5uYQraShgkm7/D26mLUL3DIXswubgq6SvMeRLoVGfgMURuD"
    b"FVQczmTMHdT9J6lu78/T+1rXoAHTiVqyXfSjQgN+kVlMNM8AzGGMBRf0vdSaM47T4DnMYZBUPEIa"
    b"FjC0+CS+vZNid+fTzp/lVZ/g"
))

BROWSER_PROVENANCE = zlib.decompress(base64.b64decode(  # generated from PROVENANCE.json
    b"eNqlWGlPatkS/d6/gvjVBvY89Esn7YCKKHhVvOrLi9kjHGTyDCB27n/vAido8Ur3SwwCZ586a9de"
    b"tWoVf/5SKm1lrhsG5m4S0iwZDbd+K+Ff51+bLAt5Bh//C59KpT8Xr/D92Lh70wlwYWscQtrLtn59"
    b"vfQeYgtXeIW/X8lGReoW93TzfJz9Vq2moZNkeTqrDMeDXlYZpZ3qc7hq+eVNeRGjknee3uPA4rtk"
    b"mIdOmuSzebisazgm5Uly2t472z8RexexVaDbhyt38GC/n183j+p2QvpnD02b7tZ79uAmjf1gW716"
    b"fsy6Z7HbGxbtvSx/cMnRVaEnV8eyd/Dw0EiqteLb77+/P3kQcuNNbu5i0l/a/AvIl6RUehls/+M9"
    b"gJJwMb9LSxx1QEGIGAzTTnmmuQnUCswsJkh7QoQgSmBjEfGBSxK1QFQQjoSgSyldi2OQDCvLJ/L+"
    b"YCkQ88pRbINjEVNmkcfcEa+QxR5pHgxWJiLEKWeRUR0xIxpH56VlWKj3mP3EhWG2ePZp/fLD9+sT"
    b"dFLfqzUvah9XL6WGIamQ9NbIyKSR2kZLjeNccu0F9VI6TSUO1iOBhecGaRq09DQojKiWW4vQP379"
    b"lK4PaTIq1tOVVVCF/EO6PocDuj6/KS9ibEbXx+9nx/W0gZ8KfjMeKq3i7lidH91fVnViH4or0pgQ"
    b"dlE9vtFXN7Xu6e5po0hx5+gqayXNdleeHZ3pYq8Ter3xbfuoXb++boza1c5P6boCcmO6OsvdnBBM"
    b"RKmNtjoQyiQVhjiuVKAKMawlRUI7b1xU2JroAlwmCgki5Ee6ruD4nK7eau2diQwZTQSGwC4wTggD"
    b"FpAQHdeEReGYBY5ibIXRMhqoqDlJOFH272e5Pg8rz35etwQBB8GdEPN/OnLsoDJ90DYIFkOMQiBO"
    b"ONPBK4U118bIYC3UqvHRKszXV8zh2UmZVlB5lJb7Jg/p5+WzAvSlfCoD/7MK4pIaA7CEClDdQhHN"
    b"OLWKw8E5ExSTUEVBgowo67CAY8JaGQ3nqyTGGpuPsQHhIHuD9AK+kj/mny19BwMVSbzTksE5Ma0j"
    b"itoSbyM8X4tITJDGg+DAl9R70EMvTFTCacgeFVqJl3KG1/8t+hEUXwbPGN3ZYugXeJ5rfLnC/3hd"
    b"VB6TcXU4gop9Abpc7JBQXqGvF4oxrApmcOdGg0GSzxcAxmBZdAaYZCjhNBDroxeeYcuZU5hiZzAO"
    b"ryE2kos12EA7Fv/Lz4iWtONT5RjeXumDfvXwuujW748vvm1P6/f+dHR+0sKji8v2SXV7cjtKi3sz"
    b"6oUd3xpfVoG/yuqrJ5urE3yfn16aw7Pa8dGU7B5Wd/nu3nS3mL4px5ZJXTeZvLPweWtZdRl8+TPQ"
    b"rzcvabolgUBNGkWh52GNsIMaQcKBaJPABfPz0qZMeOoM0FFKSYJE1nkuYcFbhj/I2RueFSxrdG2d"
    b"qgUVBCFGa+yhtUCviZ560LgQbHROSQ8NmUErBpUzHBHnqI8SGcGEMiFKtnruX2B6XlTJs7/d9Q4H"
    b"g3JijkFBiIxQMtGCnFJKNLRhq610TnhElCSSx4CdDJEBCFglEYnBx9fAP8eRJDGsCu6S3FIDVap0"
    b"4M5hLqImHoMbwErAUSCwABJkxVtCkBWcYKsjXADPMi9VS6x+VaUtH9JkYnIgwcIeJMNkYPqlNEyS"
    b"MA2+BH6h/KIXvgSnMgaYJTP0JTdKQ6kfzCSUYzI0/f6sNDY5GNPsP6XwaFxemm8uW6ztmqw7fwt3"
    b"jJPhECLZWeny/Obisnbeuttt10/2FwSovIJaa1g+6O36rK36ljWaa20El+S11NEYh3yImkOv4BIF"
    b"EjRk0rIARo6QSBWwyWs1Tyo4PBZwgCCvkW2R9P0bmDXbWV34DoAp7eD0jJdCBk+EilGFYKARAEsA"
    b"APQtFRQAoBHugI4g4BsKDJc+mIhfW/RWGvpmdjcewRZnbziarYvL87vz2snOzcUKipXV72CQldB8"
    b"YK9IzXNhjXUMDANiJoBogs8E3+uCgSJnat4pvcUI2qYXGoyu4GYu+j/Wyb2/82Echj4MXRJ+PpWs"
    b"Cu2cWWst30oX2FT55tE+Ct9a6YOOyucuGxHGZASfaiPz4OgRQUAUqikzmLggLXxgDMosBig2S8DM"
    b"wloWf+Ll3iAtw9nY0ymYJIAags8bMFgakFkvApLWSwMmyzLQFqOFdFgzgaPi3oATRxHWaMyi/+eT"
    b"wFq8G0wE/3dtfTUR/DEc2X6oZsGN4ZH3eC1RaAVX0Nc8WYQqv4UqL277iiSRex5hP4pasGAMNB+6"
    b"oXXQCjSYWWUQpZhSOp98wHwYij00R43AB1su3zvROpKsx7M5S8BuaBgQA+aMMwruzMOUSpXHLAAO"
    b"oxTULdEe+hN4YUSjijYoMHlSzCfaf8GS9YA3oAnVDGYCETjn4ClgfiSI2BAE1ZArAA5tlTMPfI/c"
    b"grHUAbJN/VxuKOYc4b87zefB9UV47vojd79i7cy00knybmGLLKRuBCZtmFfAPC5+tshef8WYLObe"
    b"6ku+y/Mo70lffcQ/0LYwgYcFsKlQTvTTSVZ+PYGqTnG0e7s3bQwPujf+KCWzrDj/Xksvp91Rk1yr"
    b"69rJeT89n44HMdyQXq9oN1luvp1m7ZNG+2qEG2x/ctvfRuNOnI1m2dHjZDCpTZcn0E2PfWVLi3FH"
    b"bnToJoBXIRbPJVNRYnmEA7Vi/qMFTGkChiAHHQ9GVQlnz0AUsGUM5ETCLARa/KU2vPx8AX8WHEk6"
    b"m19am3Gyqg+fZfymPt3b2x5fPo3pbqJ6Z3XdPmi0UI4uTkbicedkeHSfNPNq0j4YtNu3hyjWaoPa"
    b"7KAx6WX7jWlIDpL86eh81i26ojmZHd+yYfPxtPNvMr5uZ2WyabVpjmUQkQlLEQEhEIQh6G/MKAcN"
    b"JSoLnp4hEGSEFZLgHYWO2DMfOEzq1rAvEz8NNs1d+cUerk25Bqj465TjnW+tbc9q/Xh1cT17al5d"
    b"tsK0c3hZzXdGg+n0Kb+uikDzUT6ZzZ6uzybX9XrRbvd2BrPbQ9vYbdjb1rUpiuPR6HZAO6JeHBRJ"
    b"89snKd+92C/T8l7fgCx8nvvVzZUXG9lwukfIMOGEi47Mf2+A0UByBSIHGZcyYCgC0GsuYHxiMCsQ"
    b"7mmMIH/IOW+Eh/n0q8RnfvxJAySbENzL6f5ZZ/+K7u8nD0X/uNdIrogSfNrIjim7qW83989rdrB9"
    b"MLt4EN+LRiu5n86a39xg249Odm5xS/Rz30IXodEP5PF03KS7aedfSQpspLwAvQmfpQZ7TLhGJgqj"
    b"GFgdaHReWHA8VmNBHPRBGLKwwNB1EYvBwEG4AIMa5856vdQ9fvnxy18r+qYg"
))

KITE_STRING_JS = zlib.decompress(base64.b64decode(  # generated from kite_vtwin.js
    b"eNrtvftbI0fOKPw7f0XzvPOs7Y0xl5lks2ZJHgY8GzYw8AGTvHsY4mnsBjpjd/u421yW9f9+SlJd"
    b"VJduGzLJ7g/fec9mcJfqplKpJJVK+p/V9VkxXb9Ks/Uku4uyfJisNGZFEhXlNB2Uje2VlUGeFWV0"
    b"XUQ70TT5v7N0mjQbANe9LhqtbV08CZSvT6b5OC0SBnhblj4kfDQgud9VzlqYxOWtBwAfDchg+jgp"
    b"cw+IPhuwp2IS32ftCP85e8wGc7/KbToa9sU0BkmBY5BVz85PD97/vf9T7/Ts4Pi9qLalGv3h+Oy8"
    b"//bDweG++NqYTiZrn9MyWbvNi3LtbquhwI52/7f/7nT3qNd/+8/z3pmA3dz6NvpztLmx9UbBUPnB"
    b"+/Pe6U+7h/0jhNrYUMWnJ3v984Oj3vGHc11mSt8eH5+LUe6e9N8dHPZgLDiOqzwvxdrGk86vRZ41"
    b"7K6Odt8fvOuJ8VtVrqfxOLHBz3uHvaPe+ek/bcgyGSXjpJw+2tB7x0ei5X0bdpCPx3E2tCEReWfn"
    b"u+cfzmxoRF9RxuWssGscHvwkBnza2z1y643Su0TMNInHwYpvT49/Puud9o9/fi/+a+Nomt8XyXQt"
    b"v8+SqVdrd39vV46y59WLh4NYjjQJTO1gv/f+/OD8n4HJpcMkK9PSQZ3A2wex9Ke98w+n7/v7B6e9"
    b"vfPj03/qqgKFs3i0Nk3K2ZQh5XjvxwAw7OnspjPKB5816MnpMYxFLP3pjwwPmm4F6V+nI2cuNI13"
    b"B71TAbv+y8Xu2v+J1/61sfbX/trl0+Y3bUHK81frCpowfH78Y+89gcdr1wL28un1VvubNwyQiPDd"
    b"7sHhh9Ne//Dg6OBcVHjNt4zEx+77s59Fm2rrvP72jbN1AFat8Nn5fu/UAL/Z+Os3egv1fjro/dzb"
    b"Fwg+3P0nlB5f/ZoMys71NEn+lTQvVqKocV8U3fV1oNdZlpZpUnSyvOgU+SCNR422gZjMppNRMk1G"
    b"8WNHQPOiq9ngc1KKr9N4IJDp16Vaot1y2pmM4kHiFw7jsaDhNG+sXAIfup5lgzLNsyi+yqdlbzrN"
    b"p81W9CRq0dQS+CImlCX3EZU28kkyjU2dZAgMLSLITiY2Oaz8rm6uYQoHghdi4dvj0/O+wCaWEdUR"
    b"yPbKnI2pvBVb6OB6l7ppFulNFo9odOl11FylD9G//x3JPztyRC3ZKDSPjUSyXOxjQYFRKqYWZ4Mk"
    b"v6ZJRd87AF0LH/aoilGSTJrjdDQSZ5LA0rBoR3xo4VGzmQIuT+hIazanSZGP7pK2KASSaUU732Er"
    b"UTRKyqhMxwmifzYabeNXWhY5T1HSZDUILVRndYdqtSJBKvH0XHzMZyUVtrYlOPXZ/E3IkY3N6R81"
    b"4CIpVZf+CBW2dLPj/C7p3QnOdZgWZSLYZbOBXTTaaqZsyIivpuq2HfGVkF8DncTDYX0P7egpF7Pu"
    b"RuV0lsyxobmz8mKgcZoJ5nfEumwOk3g4SrOEVl+u8ZGQJDrj+KG50Y4UQLQW7QNDz/J7RBtvOnmI"
    b"B+WPyWPRvItHM0EOn8XfVotv81wsZNbECSJQ9Kc/Ec4fJ7BY9G1HrHsjR/bTUACru9Op2Pppgf9S"
    b"Dy1VKFnVZ913SzCWadlsdX7N06zZaDda2OhFp4NAl16xaMaZzVU+y4bJ8CArkxuBajmlscDdeDYW"
    b"f8QP8Ic1vfez8ZU4JtPiLL5OrIowUjm573ZUI+bb33ZUe842jYHN/isZEp0ie+Gc7bNYhkxQKnE4"
    b"0ZxEI2dVgEs67hpiF7CSbtRA3gWERicXHFuXT1vtNxviKOqUQmZoYg8txYuow06ZH+b3yXQvLiQN"
    b"02jGQjCMb4A7nmF/TT0s6lWVC15HJeKPxizDNhusnUJgTzQiwXGBxf7Cs6C5DgJy8X3347r4v7Ov"
    b"1m/SdtS4mE1Hl7iGHPJ/Ln75WFwKEAHxPxdCdLsZi73jw9lntjiJ51jlgsSQ6zSZBur88vFha2Pt"
    b"48NfkkuEVhDFKBXlYsNsbm1wfolz4vO1F3oST4tkd3ozgyEWzXh6c2fOCGwZPnVGSXYDIr9Y068V"
    b"7UPBxcYlLfTaWgoUE48E0Wg5qmGBbmrQ6SwDVrc2TKcNZx8i5NalTT0SBBQM2IdXgonNyqQpYVtW"
    b"L691LzfAqfCs1S0YoYmIDGu8uUT80FaUrFYiT/HdMeghUSM0xbZirTSn/XTapYEqXqtGqQDNsLqR"
    b"7N+cAfMqzMOJtCXGaWF+NYBOCcLRuSkhFTolyGoQn5uXHA90/jP5ZQY7oxtZnUa7b8+ODz8IUfxk"
    b"9/wH2lBzQ4FPEnuihjgw6vEkep8jgcaF0AUjI2AVQhkoT6bpnTgDRF3BdPPpY3Oo/uK8STYI53t8"
    b"H6eoGMPpO4LuWBXFgjQ8IIm16M1dDt3AREIaLKOrJBrEWZ6lAyFPWlypjIdxGVvjGIFaEhjEqoIW"
    b"C2Lm1wLKZCVnj+OrXGz0wzT7LE7BqkWqHmgcASJMgVksGERTdwVLFv0p2sg3/vKXFiJm4xm9CRlX"
    b"yGeFWLhCUGASZXkZTWjt7A4llUrdvnMjCCYd0v5VSw9716AAimE0do1noeI2FoMSv6+vhZ6QlRFq"
    b"mGpYPuUJfA3f0on8TihhTdDEnEN44XJDneBKY4v1i2wVFoL1RN/ZvQcmLSWICPqFgz4dkspxHYsP"
    b"Q2+Dyv1h5tfarkDEP4QEa2MANL8tqfhxbEzix5HQxDUy6tFoNo2Uw6J/nB2/7+Dh1JRNicNfnu6N"
    b"WXn9baNlMEqVBKIsYW6VC3OiMCTHVaIQ+o+osjJH+YjDNoLsqhQKyuDnqdDeGcqkQGaQJHgaHSeA"
    b"p0+vnnDSxKXT60cl+YEi0o62WvOP2Sc15bczIN/O1WOZHOIB0TRttQSFOGsSmCDZYyKhY0xmQlN9"
    b"GCQJkAySjpkojbNMxhOhNovNs0M8G6VXcyaLzQWqK9EOnXOfOq+esOxKyGqmcA6f5d6dpMN5pxxP"
    b"PpEIrDq7jbPhKLF2kVCaZXd6JNTLddHBSrGQXTrH/Z9Pj98f/jP6tzxpndK9097ueVXh+emH93tV"
    b"hb3/3TukDjfybzY21HhLgRDCLg2VRt65h2VHIjdrIgQ1ItptHx5Ih6TZudixQt0aBZsdjHIl9cLK"
    b"8KMN8WtQE2l+Y4AGt4KlSzrESThKhz7BkF49Sr1LC9HQTiRmNjYKqZZUIlkg1WYlYWgxRJe6MkgA"
    b"4opUtQaWa/nf2RoAztRVr5EMFSI8O7Ru9A7Et4SqtrRot7D9ue7FZiCyHVn/08WrJ/gi1NZJE7HF"
    b"dLz55SczVhyk0ZjMmCWr8ob26enVE9czsWOlR0J3EjwCtRcWx+ckoqA17756woFhAxfik5C1Psm6"
    b"fLDzT3ziHuMg5poWeKprskEESr7BtA/qkMjJUTxmV+KM+8f9Z05sltg9mN4JqfFkbevrb6SUnTyU"
    b"ZGGgn2IK/XxSdKOLxp3YadePjUtZUD6Kmr09We2hS6y380C/H9XvRxqtNSwSU543rqFqcLhonGBP"
    b"+QKjBGv1CSLwx+TxPP+cZIHRyjPiepqPm6HtrXkSO1mBW3/zRmi1jZbfo9hAN8lUYCgrm9YI2kyp"
    b"sYZAtz2dgTj9y+SHuLgV585tDIiTWutsIkSTpMmH+gns3nTXIJAluly72/q48erJdDH/uPFJDD4u"
    b"BmkqxIDKluxJWyM2k5fVh+kNKISN2+TB06hfbznIQJGqN9jL8+lQMGzRrY993TlbnqqmfhBDO5AK"
    b"pYI00xVsV1msJEW42EYhyDOCXeA0GoT8YT8Gc13j2qwh/GQ6svgFKOrLHdD/9f6zpEz5HXFHn+1P"
    b"gr7hUzG4TcZxX2xFkPyBf18a/ngdj4rEHPITtRBqch2nDwZK4/FhzTi36wx9HXtcyGudq0NpHXCR"
    b"i6DsZ4URwatG1gQFbtZlYvbLhViWO0CaYBXwj2QR+GeJ2HyA/wiOFmhH8myDGGVa0K0Ol2panrDK"
    b"uqJGJ7brHZ1IxOM0gO6vEkI3IXoiAMHeAvWDxbqyGDiWAgcNVA4V20czGwdNPjBJWcItW5uVUNrM"
    b"Jc+Zim7ZBN1+vaJwxx6Y7hlPDkapDgMyQ35oLQP1WAdlRvGwHNiSrQ1D+HjA+bHxB2AeHZhHe8s6"
    b"zAiBA0ekrt+yqzOeqKvys47tW5//Bq4ROoblBu2YLpAihb/tRG++VUCu2IqXH6QQu/Vb5hLB0UOT"
    b"rJhNE+t4MfY3/9QmhqtMmyfk5GEUPl7Vv0p3VCJ5A/qQFqWYu2UHwOOY99KONr9R+qoRlP2jUbVm"
    b"jVwfMap0mRaYAmB0pFk2ApMLH5nSAaJEHF+6iicTM+YPxKNRCGJymuEwGkydmAvpoBzcRvxehUbM"
    b"bknQfNF7fyxQ3FDGSHnNy3VzUAk0dqW8dZ9cyb+K2VU50gQLe4lOjydQGVH63D/bFccB/BzuzaZ3"
    b"iRZt53SqGDFWSq9tzQUvbcU9eZjgXSDtumiHifhMm60aItWGATZIxICJdcyWreiLeAR0ZgT3l/em"
    b"OY7TnV7PHblWtkzRdQQKwpchCvrtSDhdB2EcyIg2XXeqflti6N0Qu7Obl3YZxuu6HqNzBsR3WVuq"
    b"PorndJH8gSk1QX84ODuWKkRLaYDKMufsQIVKZw9XWKkU4Q6dfUWWTGbbbDiGEdcCZ7Mb9YtflKlv"
    b"tnye5dMxmnB+gOu/t3DxOI3vacPQqMHTQChMNvcTH6Tfx4fTQ6gh7Tty3/etje/OWujv0PyccY9P"
    b"Le92SHQhCDYv80E+ImaBN5RdbVsBgFmRoGmOf5vERXEvjmf+rUjiqRgY+3IrtLWaiyA9Rn2zkEUC"
    b"Z9MEsRjD4vxwfn5yFoFGaY9+lQZR3kIDnSQbFj+npdAM14UyFvGy6CsxqXXu5gKlWlmtsmBZChdY"
    b"SAvnRtO3Ers3Y44/1VfqUprUvBVml9J6jXvyDRPg4mDY5SqpHJWtZzNbj6zFhUOcgZIKIg0R1Nmx"
    b"grRKV5KbO/K5fyH8Q619wZ2qZcZeMFvPir/tWhJ5AwEDasXEV9XEbbOh6/qDsxva9wvMcu4NxjYh"
    b"UG3qjE1a2zKZDk6gz1P0dDtUGbWsVaZlueWgRa0qLcotBC1pVWlJZoSOxiIbUtqK14Otq6yirlIB"
    b"pC+klY5kOg0oBVT1obUM1GOralHlB4JbTPKq4tw3wRyhE+dePBpdxQPL9ldhXGnk0/QmRXEIHZ9D"
    b"tg53o9inAonx1IzNBSwjhsPpdxSn7zYMU0CGLfYsORACxObWXzob4v82HSg44M0XUjKaqqAFKsg3"
    b"X3/9+munkmLI2PQ6a3KVHR72Rzg/nE/6MLI/6/PI6pPwYhia+qCB6Ct5ouOwJnE6VV64RDAvZoJS"
    b"rkj+IdSeD9MRHfliDa/Tmy916PsDYDxKIKkUoqVp7QxRfAIlRVOhV1ooN9lNaEA02OGigfJpCy1H"
    b"cDHYAsOx59M4dEuY6ZCzIGp7eAcDnrQNZ74OaYNfnJkv3W+0LsM+dI3rSVvIg20B1Baib3ua5+P2"
    b"HSNG1tBNUjYbd6riVg0QtCLh5DTgSz8dVlcBe6dfAwwPlVXEuO0qvlnRryQmaVdy7RyVNa8ngYpM"
    b"9Gfbo8J0+qyFgebbd+17oHPmrVWxGpuVINCOPfBJkkzZWrgVqEerBn7qD+JJfJWOhDjv+1eqzf1W"
    b"PcPwrztHyU08AG2vyqgunyf0kfW3XSN7wKoOsgr8UP7ByrQOmOyDCCPKxvFD/y5N7sX06FgB/5T+"
    b"JEVrrsSEqucY28H8XsbTcjbpl+Q53JcetlDk4oRs80a9xZ365WfLLg+ca4fA7YFBDEcKNUEvLMQE"
    b"6HQmXOEnIl0xsJvE/1qC4GraqEEuevdDj1gmGYD+E0dYiXbF9OrWQOMbmbSkrj/9KVpFzNf48UgK"
    b"lfaGaJwWYyJ5Tx0M3nWs+ncdSsVZ9hajQiWCJyb4cITXVmvo1FXMXs9b/jYX16J1uPVjr1KclhUf"
    b"sBsODuz1lnz7wuu7O8B4fCInlPKlM17aFoHhSlzr427VHHfW0EIqqTpewObZWhIaTjy4OlwMHtgA"
    b"fs1KgbfjbDSrmmXh9rdfUJE2yPIrKKXiu+jrzS1rfLUqqHsIesRQSUMuIwoQUwXgauBSQNeJoueN"
    b"t81quptOF9mzCniudQzLCszAFHLVzXlppYrqahf5OOFTBdmzHaXZMHnAhykg8gaavkCISzOd8EZb"
    b"DT116DBOLTZJO/p2Abxh5Qi+Ff35z9HrzWgt2mw53tDe7UyIZqtuZ76Dyxk1kGfdzgRHwc/UmnFw"
    b"MDMSuCkJtlpxAEkOJZ2iqiZR20TLHldVR38zXur1gN/BQ4U6T3Nz+GFD5ElsXaYYlQn2GNhmQWHy"
    b"DbZsH4JgIuUPtExSQ6DNEYM6Rf50Qo9JqjiXOsitwztQPzCUlXqeqHiDFGSMfUOIN0Zml2KEUjTd"
    b"nltB4yo1hTbWymssv1cy74pmBOYj0wa7yrIs/UxlpikqSU45v1auNh7QsLxpSeKHe3M2d92whIJC"
    b"Uqq5EIEV7WpiaCswWqjo++jJx3jXW7h51I2e5i3f6Qpkm2E8Hb6lLbknfuGMi+Ztju8286IDfw3T"
    b"abPVjiajuLwWFBAZb3X1yRiWDBBsUNH6fZq5KvOFIor13clEnCKIn2L973l+M0qiPYFJ0btoJDpP"
    b"8G6zE08m63u54JFZWawfxYPjs2pg/X6lrvWFLVa1gqXpbBxqQJXpuo5nMa3qODHnZeP3mL86mb7E"
    b"KBbjqbo37MRpfCn00Zl6yRUCm6qEiDp7qCYqFXviBge6NnAXNFgOr+uvRiGwgbusfpF63N+wR65G"
    b"duk+7kwGM+wNfaoHatsx6yz7tsgEy15pXBf0PAOiTrBmt5VneTyATWuXtm3X8P/tH/9om279xx2g"
    b"5lW+7nixhXKYFoNcqHmSGTXh72k6FANMBA+d5hm852OsR3xtR/kE6QpusefWO/UHIDp08Fbt4FtJ"
    b"01Ln9OREP+aHV17qkOcwez+cHh/1VDF75Knab1lLwd5pWQ/BNDQ76xwiUFXrDjOyB82m8KiBkKSc"
    b"lmNOVGIYN7NRPEWn+Ybl8y1XQHVmixyaJACd1UcDNiTxjqcDYMY6KCwIvXMFlHtqKJcE4F5NZxCR"
    b"kADNiCyPkqrt02KeqvRJTdBDZZZHxWxCvgGKh4pBKBak8XsfF2J08gGJdTeLdQ5j8fvWPDaVcS3a"
    b"eGJ/ACEB32Kh8gSRDhqcRmNVrS+KiHt9WlsDG/Ya7Cx4h7iDb0ugyfknaa9ZW4P38WWyNkyuZjc3"
    b"4E0cD4diRYsdc0NSDQtT3tkwAFm+dp1Oi3IN3zKyr8PkOp6NSh22ZHCbDD4bCDHMtXE++LwmFMDB"
    b"bZyyysrgLjhqPk12hAiTDkyp2OawdGugjd9MAbVrGCRgDdaoLEfmBA8CwxzywWA0E0rTmhAthmJ0"
    b"PrxQn4bJVDRqVTRw8azMBRE+CnSIjfm4I+aLeAePabG/1vT7qBXJzYHuzFJyalxlgUhIN2dwgSeX"
    b"UgTUFIbQERn21FsaTRidyay4bQqq0JFTEHwNwQVxmK7mxiPBrQ7rmdxLZDU0bXJPEVPF9UCYAD4k"
    b"EzgrBVKnTYxexJ/LVYVFMRdLBdbEHaBvWKAVOErwj46EMK9I+OeO9Fw2Tyg137Whmg3YOWKOg9tZ"
    b"9pnHmdAj+PTqif6ev3qS1+4I3Jp/krdPa/wNH0V9sI5zCmDhxBOQQxANjr1gDuNcgOb6YJP40yOi"
    b"9hRvAHSBL5BAOwv0AV8pOsc7KjOmbuk4tGPHEelXBxKx2sHYVPBbBbiIZIMdPMJVtI55y+5QB0qw"
    b"Xk7JcfNwK8Z5pKRqNG0Vr8ONdkBgcs2+h8Wy4h3Mu9GrJ4LRD326dkgEKewYDOqtJwHYIWx8E1uq"
    b"hgpKY4q2faTpierHQUSHEDCk2cCqggYdBMl7GDwxen4YHcHPQEpmZzsGELNeuEa8uhqpkuqXDFyh"
    b"pX4ewEJ/7EYNvZNPdn9+b+noMJQmG0HL0Iw1/4cUrkSa0LAJhePgoZhdX6cPQA9YblY8unqM9M6U"
    b"lVkoiG9abOE/RfdpeRvhHF89aeOPMqbRwn4fqRAdKl6Eeg6G82EOYP4SwFSSoeAYOFrBY9mULdWd"
    b"VqltLAEH1+/wU7NlhbrRO4TOhWuzmSF2DSfdpvdqLgRMe8GHtXfZXKv+7gvoeKCYe1NG1auWqQeo"
    b"rg3pFv9CgpvTUcp7ktm1GDgdQw5Ah1CmrVUYdkdF42Gcj7fNwypFXgfL8r9QmyZS1JPeCzIaErMV"
    b"O3UqAiSxCkDRwUoWjB1AyZiYt9lQDD9VsnzkocyOrPRfNIG5+sNFen0QJvU5EIoJNqE+l12NWCy9"
    b"kFy1C7mkiQ4Qe9MQjWzHCc/lkJo5Kzz6dunZ2fbbjsIlRhR6EO2TIrBwa/qGJr2VWBQoSzfBzZs+"
    b"GwA0vcun+8ndeZ6Pil3x9S45AceIFXi0QjrNCkXzymclD3cFnznDWLE0HN2Q9epCa0kNv0cebkQH"
    b"ytphgbKir0LDgEr3txAcoslA/xbZwbh+79U2hKhJMb43D0UYs2V71I4iYVDWptcjxkwnh7DibC4p"
    b"V4hJYoTT+J75k8oHpVIs7RSTUVo21z9Ov/+YrTsNTGiVpP8cNnexcekAFTlEHJTPaAhm83KbcVU9"
    b"WCzkTr9b5to5cgOCTWi6bfLUa3HI9V8+rg+TuxKo5OO6PJc/skBTzJfZjE7fzlnckM5r6szAzm22"
    b"WmG7Wo50fgvxiLmuR+e3SeSLIRDgBSPOwJ1rcStK0rKAO4xJDpe5j0nZYUYen9ooROHXG22Hg7T0"
    b"h5ZlKamd5Utn6OgBTg3gem4jSrjZDlhwmPRjZEcfc4rBGGQB8xhCkJCgKtF4VhMN3xWrSEbizO2B"
    b"29G50KqTslniPwfZdV60wS4pipMh6N880g6QHO5fBt0RTLIUq0efxNFOPIZ+qUd6+KsDIj9J+Xix"
    b"5pSiF+fODu/ceeSnmqHOh67CoNddjpNd21Zef8Xjq/Rmls8K8sGK4CKqoDcv1E3h3YI5rdM70u/V"
    b"Z/DG7kqxUGB8MIqLItobTvbyLEsI+Rqh0xlERqKrfV+chdGmBaFF+bzKbz8nV2fIGQ7GE06l9vd/"
    b"/zu6GeVX8ejcqsPaUUdUwdow30R9O8wyqymFgB1nq0Id4yVOkNipFQ0Uv2fJA65htME+ThI0gUmd"
    b"8yie6DMLSkdSTigqyjFSCzTJbPdgaUIxAmPZ6GGzSVQcut5hq4jQX4DVoNEnQG3vhYrX+bWIdHVl"
    b"3gUL+SyL78Q2x+sdyxzODzU5c38QTUUsrRDuC7byxHiXDOcqDWNJWY5szJqBCUlRcHtRpryXoLYM"
    b"J8XlfAxvSg21HFUhYj2A9Gy+14SB/e1RWSM9ZB0pxdEEZBimReFhI4mEpsQfU9cbe/snbL2BChln"
    b"brGxoFgmV0oHHQoc9EqvmredTexIQVXRdr3BMiXpN8XUDamEz56Uqiqr+LoXYBDsNlVzQkpuGXFl"
    b"HtTLajpQhrGXLrEyhS0cwReK96ssPfUcrHK60t4IlsA7vLr8jsiqLwua+Lm1qBlcW401aoHW20EP"
    b"MenGwgbtZahp0MI3Mnxn6CwytWV95XqQse2yB2quCyY216FbbCfIrinp6li4+lvLVoZqZHc2SXUD"
    b"A5NVa8TiSRv2aeJkBaMRy7qdlF/aSmVKn7b88EUPf1aLk+uqhHEZuFV/KITLMgk1YXFzBW5zdXSj"
    b"kCXG0qC+BOxfNnD9AeA245qqUHiUw3bWpia0PK1QeZsPHTO4tnfrGPICtH/UO//heB9D/ff2G9ve"
    b"RKQ9LNG260AgBA5Nl/dq2NKqJOSwp7k3vzDZSOpWLcipcNdIe7nZPbiSyCIlGGkRzaIiahJDal5c"
    b"GpwqYA2Hz0wKGnxbD6hIMKTpwdCyD8E+p61ChxG/7WTSoD10W0w0ogabktoUakYK0eQM2eSb6L+c"
    b"mh2CMhQrEdayw82xueLM1BG6/HLLQ0Cvs17fJ+pxblh0njWJKNoaynZS4bJ+kLIYRclLJw2AdvaR"
    b"bVR02ih0G2YAhRke3KyDrYY8TAnOPIQiLY0+aOIEJS0bJkJK0DcsTLuyJTVZNaCMcMdcdjzVnezh"
    b"oCZaXdV2ZZ+tzN1X13x7mPfBXJUw4SPNR4xh+3gGaV/o5bOnnHSOT3rvV2xTV3h4DlsdGK1Z+hCh"
    b"+NcK6EcQvzj66iumW4bvbp/AXV0tPS3nnOVf0LzGZz+oAci/Lbv50rqUvKGC136zSUAwX3gsp0NH"
    b"/VGwjKssxWe+DKcxvOb5GpPEQpMrCwEpwpqxRySfXj3RUs6NUvXJkryfrx0FBlarhS476i+Rr4Qh"
    b"2uq2QNoQyoFDfTT/qbrf1mrE76CE2AzLZhCFGGbTCY2q/ByYiFMhFi/A/xchJOQ2MMyA+mb514Dt"
    b"jtRY7l1lCRxPHB8WHpZQgD1Fh7FApTotdU3Gjbsw6OEETh1mXH3JVdl/6K4reGEauKgSk+yoo7tB"
    b"cwe2eS4tuW0UK80pzf90rxxW/NssazDK3B0wpdM4O8xGTmKKbVdnhkUE1G6h9HO79pJkc+PL3JJ4"
    b"FsoKKzh6mMLxy71MybZ9kN2AW+feKAXrgWvbBrIzp2ZbRnY/GFombgEE5sPhhJsuq09dLFcNgQla"
    b"/slK1WYodOAwuM2T75q6xlirX6Br5EPtK+eButiv2qseEwIubAGhArV1ksCFLWjIQCu3ghuWVwkE"
    b"A1vQioYMtKIz9i3Gh4IMtEKveHaz4j6ZLmyIAwfaKm5n5TC/zxa2owBDbWB4fd6CVxkhkAs3eAIY"
    b"fVMARmGtHKi8CIxVcLneviCxVRg1gv1E7BQdUtimzwvq55K53AeqBRx0Z5nxDE9pC0qpttFyAi+Z"
    b"oCbaQ0PumK69lzSN+yNQRdoFt8syd2ncCCHmAq6/Lp6wcH7Z5rEepYjMI3QrEfrt409QwS4qxOGR"
    b"yYDePFtb8DRQjKRjqW5R1Dil4JkdWNV3cmLHGXv8pPDTtjQbzbLUV7Xo7nNAye0hkcOEkAaXtUX1"
    b"LdAniqgn18wIsCR4fAqoNoQjFFZlb3LyQsa3PnR0CDJLrVvVDbjR/3WBk7NDQtnvnxUwe/fsp8Nw"
    b"pDxdB5JjQPZJRwtcFjl6oMosSrv4U/jdCMH6j3cET88KOKfkoWV73NYmkORuubZN7+D93097Z2f9"
    b"89Pd92cHEDU0mB/SkdLgTn9we0Zk5h2TftJIo5eyJJFOHowQ+UspiLp7J3YgfdD0/6RbnqtPjhkj"
    b"wty6ZlMq7dLJXqkVGLH/dQsLw0GBMwlJGALfTNQtxcEFHD6KR2hdkPgS3ZS3icJUp0ICjkuAlWvM"
    b"hF+SZQJisFLGKmRfugI18gg9DzDYX16EvUqu86nJsVKzYFpsBQHSrJbyfei6zhDVq+d9sMfn8jPF"
    b"M2ioTIo1u94rIs+OVePZUQOqIhewJVjAExq+ODq4jbMb8H4hfNKCw7kUujmnUpaXLKQmENB5rraH"
    b"GU0VxvVpORJ1k4yfU0sqGZ5vgRopk35tM7yNojA7a0gcGaQo2xnuJBtDnKz93rcrmIs+VJOMXqOi"
    b"YsX416I5Sy4Lx1VcVq2M7kSCsUURxDOl3oSkx5xc+n14L/njwXmvj4Gyf9rq9/XmoePt79N8BiqA"
    b"l51cgaUZvtvaoxzdh2IWuycHXfJ8qJBarDJfbHkWatge1PjxpAse+lID6asfr7rSSPUu9U56fcPp"
    b"VNFq1qr7OGNJYpQRkXQgYXmyV1OktOZKODqCLR2TKfsa5a60VjkPzu3oyReIEf59sMzSpehSDgeF"
    b"SJXCq7HA/q6f7ph8qOaZi0km7YUYfylK0Wf8QfPGRpWRXyaEXxyqSoNezeARHADipnr74eBw3wPS"
    b"MagATv14BmenTgS2yKAi/rCDblXPRKvrk2ToJajg4aPUfhOLmN+/5bX8gK28nqkZih7IRsKKoUW/"
    b"VmVgnmUwJPYMvKQcwtsjnkhRz99HVAhDMDJkWECXVQCAjOVGpSXzONPCOYufVurck/YGH8ymU3op"
    b"X30mOzLQ4iP5haevYqVyTEGZxy+rFnoCsL9N6sniu/QGD8rhDDhwpcCjvMclT7B1Clzq+XZlHgRa"
    b"iHrFpBKHlZzOd3l42clB7+nRDC4ZXfUZ4iVtqLSS/6Q68bWFGh3hdzabk74xwt7PtbOz8dBVn3Ss"
    b"B6gwiovyXGGSudv+59+bvMR6b6K+BMz4uvBpbv721Jzgp4Duw6LC/BHW/lVl7udygrvaLesizY8W"
    b"FYPyU6kWNTxXkBc/tlAvGNNM2ZXY4eKSKLzqdVz0KWJ71eSeMTWdgSIo3gR2izOSqqdPnnLoGQ88"
    b"aZMbErQ6wlmF0iMMw1jiaRRGb08rdKE/djvYAzMntU/8JoChHH1gH4Sw5PZE0YRkR6Kac4IuoqOa"
    b"s8tXaisOsWXpUZke5EmspG8VF+ixUeF1Fz11Oh01mrYkoa6a6XyxLrFKRyzEB3KSFfkWyKBS4Z4Q"
    b"rPAPe5JljaHyVY45+rn4KzEtAxtyL/rKADrPuc60M3GcZDfNK7RuO0lMVqXNOy3oDw0lxT/6qVOL"
    b"Ra9fh0u+w4Ak7053j3oUh8QE2yS4YnYVo919A0JxdgQnEEJ7KFnHxcbDt39tRxsPsE4bD28S/O9f"
    b"4L8bQ/xvDP/djOnvSycYqOzOfY7Zjja3KFYu0dgP+6eNlUAyCCvAwH06LG+7qkmQzD4cZOXrrbe9"
    b"pmhJRgxM0pvbMgy0tRGK/4eZS63VWJzmVOUllbXsPKNVadbPKF4TXt6G87W1hVaaQdiVM+DMoO7u"
    b"RBv2G7ksvRY91SZxo1U/2n1/8K4nFGqdxU3eG0L/tfUbI4g2VXYmYBRkFSFEkp/xjQ+pjZcwJiS2"
    b"iTyOlU3kcUh+4wcZD4ThlnjAvwn3kDIGkY+Byu10pDxegsyLJbpdPnw2gTt6thU8OxiwVvYix4qP"
    b"eKWzPGzCs913vf7B+/Pe33unLbsnVQUSdLgrX9sXIrAtdn/b3edWaG8VNJmF9JYdIy5NuGwPg+p6"
    b"93GUx0Nr0flDbU1L/jBMI6R6PItwnGs+HDNxCqeE2m5VDH8oKDorpNKk+a6cVMsilFUGKxFovnSQ"
    b"8VCenG82AuXEdAjgjQ7hKzvisZrZ6ikoyX/UqBgYlSzkim5COiUZdsXaKi9ioqmuQ3ZtNoCu1al0"
    b"R85u+pSNqasn4+ZpagRYKpppzpWLCVKKl/54iRTHz2IOWTwpbvOylj3o54V/XFbhYGjr5TiF1ZGa"
    b"XzAxqS7kCed1qpdQmHFVQ/ey8KrdqYc5heSNO/fXOsSjA8+4k9l44nlsgRNkzXNk9JHcQVdJ5m+V"
    b"CuxNxQCsl8Tso2BjxHoAd6c/7R7ar4kHoxyejeqa9FtUkl7DxnhhvW4l5+Ipf4WsPom6xvc4/MDY"
    b"fo6cZu9GyCKsN670akDIrGdCXN2FwjWh2kDU7scAAEgg+nrYKePyglO8W5bJeCL2Q1V9DVDRCCwf"
    b"GsfuEhn6q3Ag1OxCPShfbQch/mNq5XmXnSpTjkK7/mSW7Ik5zApJdpyWdBZxt9naVwcIbX7jT3Uq"
    b"7qhXBhbmF8BaONCwTYss/vSnisra0Rq/O3nRXAwZIsPGWEkfuNdwBvFprRcE6iUSPWsyQOE3TYBm"
    b"m2jVh1IR/yofSDjS3SiGRDtHIGCO4we1GBuWGxTbwmtmCIPPYmRr7uZocbOZRVnWbnUeAlSQoMLX"
    b"cBoL2VfZeto07JbjsKegnoGthfgh8rNX/5l8xDwvC+1BTmcLGMIyoIw1SHAjpipWQOEZ5d414w7H"
    b"crSNZSFvO/Tqp03N7Tieb1r+ueW+C3A4pj/BOv5ZOb8wx+ZU68DVMs7Ao8vKSl8JsbIiQI9jyTGI"
    b"di58F7bsxuQKPrhQnJjWpS2XoK26bVd2tMwzjPX1SPL5/KoQfAGcSgdxBoaUK6E0fCbfLLEtRsna"
    b"Ne2CiRAxOo49rOa8rT+uqpjoPPwyo+qxZ+UG1oyDnpg4z05MQc3hOTeClhav9+IhEuoXkbReJiqR"
    b"0dKSzvQnURcc/Bi09hq3KvCvos7Xdh3YcnXyT6XwVCN4+WvExYkku0tG+SSxna5vaQxSZ+NmMkdc"
    b"VtWZxNwK9v2kINvYuOstXqZ4HLqPgVR99/AJCQ0qGdx9kFtJK7w0OzvyCE53lYtDsAj2vRsFiYYX"
    b"FrKN7x2i6HrLbvYDjMo76qO/6War5xN+xrjwqPSD01UdPQoHmhBecgpJmuX4fP5hohmHnvOObrJV"
    b"zW8CAmDg3oAhNnAEVG+hqvdhMrz97khw/+YkHTI93w14F8jsVJfpQQXO/5yORlR5o0LMfVGCbGr9"
    b"DMz/Oqs99uKz0GfPhniWJLhZltlaJYQ4hnwUqFaqH8wIx9nkpEDTLRjuMPnGpGhs10X/pN6U+D3R"
    b"zxAuGmuTRlsFE4F1akeNNXCDaYzwCmSnoe/WDF2LgyYHOuvKtN3m9k3I+MQNu9E3b6I/Y9hGdqNJ"
    b"p1w32hJs3aLDwFMHdQ8lf0tfOeBCGw5C9ZrKaegaQ9GZnQtQRn9Uv6bJZASRUNc/Fl+t34hJRwZS"
    b"x1n+dmOJRB40kkCe4UOxi48hND3PQxoyPFWYv6L6hJw8sSbPeqnqym+4ln11vY3AMvEo0bsHoOr7"
    b"5jYKz0/JXVzr1LJWs2XTU0rwl2SnrDO8BZPJ1VaoSUIn63mpD6gmYssZk2W0Cy+AHfrHQnK4gr4K"
    b"3BH0Gu4oRAl1/YTgrW60zc/h/SNF8gfFIbB/zMxQyUCdXYLAgQNAxV9Q4zaskPChmDXLrWIxcdNG"
    b"DGeS3wAeVaw2/tZXWNJtY6Tn08FDDZT8QJEml9YSCcGd8WtvYHX66O7s63D98g582hZVZvTL2wjx"
    b"IVkjTJaSQqxWwyDetMBVdYmm3QmZaqHeqkgwHqDgiCRV3KYTmBq721xxr0sqneqkIhS+IT083vux"
    b"v39w2ts7Pz79J1sVzYy4ndrwp0/qx9qrp8ZGA44heD2LAf3dpT1JuVee+cZTCIl1/bJbZCFN6q5f"
    b"RpV6GnZlCv7lD3bVbq/So0NWJecNg4hQ2Euz/0qZkEg7k0zjbJiP38rLOXX9z762mltvWuwGTN72"
    b"qwYpi416B2ufiV3nQJQxfDCTb+0tnryJS4fdiOOebzVna3TdVWyz/dWnlvQy8CKvGQv5BGpEki4u"
    b"ABgEmoCTg7NjiZaWygeCoZ1G9FYIzIho/NI//hZ9a36AHSoUmYjI57qYdMafIa8W7Mp29DTOh0k3"
    b"2sj/srFRFSBEudvl43Tw8zQtE7xzNtuZWmoQi/m1gMiqMlGVb6uqCNamk858evUEzc1lOgexuUtK"
    b"R+REqmQu/WZiAsfgEELjYfkgApDjpkyxAZFYBjNBWHfqUTMg24+ZwoVXGcik50QEiUK+XHNHRRZV"
    b"MQsrMVs3pI07t7ALvr73X7AG2hGAq79WpgVXcpA9WQmTLUd53OhoxpBCWRBM7AwEYtusEjR8krHa"
    b"jIsFW1joY+JWqH4Ao6K8+wp9YBEtclXfQgRbSaKqUjWRKohnkGnQUlFrLY4q5uuFjJKj6Sh2j/+6"
    b"hYp14792GEwFs+RzLOY42ev978FZlbdkwnfI0zzMxL7IHjJIhOo9F5HIoG8SfjMRYFc3zuuCtahp"
    b"1hzzbeJIWq3OGKQkZeOz+1f5Mn0eBOiDPr4To8DcH+Lvv0VbX2+0Alyz0m3UoXrmVm5RBlsyatDV"
    b"WyTajYxS6zAfZ3l5K6gHYzzhEQhkVKDxTMmevtuu9I0q41HCtyR+0PtR/CFPSLM1Q8ect0mxGZ8C"
    b"CMYjAcDERaP3/hice9uacC878rFqwStSqrBWAMGEGQYaficguQQOcUkWMa/ywB3ks9GQsn+S4O+s"
    b"AikBngsu8ehzkAqbYe1UatCOII01KrLwSW4RqtF0JM9nmACXNOzVmAeZxS9+yKUFaKc9uYH/Sltf"
    b"e0DPkV9u9FM2v2rT3+svZPpTATklPvJ7zMR1GYgmmmH+1BrboJMLxg1gjM9DZY6XDv5o8pQsxZ+b"
    b"H4dftT4WX5l/z74S/8j/DuV/u/J/9AvhOn9uvVoPvlLAbvzNBdOkwKMsmCtI8jJVDVa72LxkmXJg"
    b"gZ3yLV7uSvsE8voyaBttM9EXKUXBv7lUaxqMlSKGvdiEenFZYUKV7wS0OV6winw6rLakUrkyKNCv"
    b"l9smZf0XGidl7QrrpGc0lOAhq6FjmJSQqIBvLWXKVDVuaqqYVhFDrIpjU1QllL4qaEZE4SQtdq+K"
    b"fDQrk6ZdpRVucAnzZBByKcMk1XTJyTMNUVJSYtPX6U3bSfyllPWAzSh0I+Qkdw0tWKVBw8/AM0yH"
    b"PP1RFEcnB/uuSeNLmIDkJnqOGcNska5EXafaKVkC2PYNZghBtmZQtmJ4mfPRZWCOqYlhXYlx2mqi"
    b"lvR59gxjta5gTM9YTm6jku/azWIusl1wU6TKVEocBd96tOUacksvfbHFIHzuL6eCcUvkPOot9pVz"
    b"t7i5NicCqlVucBB0/eTeNnvghlCkCrtyRQ5ozj55C+MEjj90/w/IfC2VXQqWa+c7OK6I5TkskNn4"
    b"xGEzRNFNtixayIZWfad66jw0kA3UsTRVSKCdgJEhWI0/FKBFUCml5FCLHB4e4VBXpFDRkce5kfSd"
    b"JTMHRAjYWiB6R/K9xnkXR+EzY4HwcZqJ3bCvdgV7qS33B38GD6v3tYwRVsl6qRp3tVSOLcCEd1S7"
    b"HfotmKD8EOB7ClR+YDmnsCsuhLAs3h1Ik7un4hJADTdUL4Gh90Lj7ODv573To0ZNsF4uSNlcnrRd"
    b"3LE6d7CbWtgQ/sJdzl+PK1KhQzXogszUT205h0nxiwn43WquWYKHo6N79p5KW0/AUUVxZIYJjtOl"
    b"IyPwMML6fqseWUrekNsiGPgAN4JtqzBZA5ftQSHAneOPB4eHdhBOwPZ+xUxfaz86Ps0XTNSZKu9T"
    b"uqsHJjwPymIQCv6Y9X+KPVunGjIWfh2H7L721WLgIAwp0JUmNd2DZT7D/R22I4d2h7FwzDKBms+m"
    b"1d/uquTLtKM4HRPyDA/lKKlKYv1iZJKLN0kSHLWady6B07AF1bGfovgvDVLhhxCOhDWVaAgKWLMM"
    b"RmTfAb5cmKvtypPlZCw6GZzgRKlNDO+EQUsRiaJPKOTIw3hNCzhGrMZ8nZqrOFoZjwV0otSuZaej"
    b"GoGAULOyELOLVKCCosynOlOUmd0NMJBTssTQ5VCttKXkiTqRS03OPc10V02Tj9M5s1g+rnj6WZnz"
    b"rXRc+N0nV2M7MZvCQmw7Ojk9ht3QP9o9/VHL27qeDkG7TDauZddBmzFr0zjySFNIgnLdj3CuTZpy"
    b"m2YGLzfRWOxo5uwGjeAZy3MMFDaYdTnlWD4WBaJabt7WvuJzXn32gbrkGNChAMmNjSQYHkZ6DteJ"
    b"tWhRRQGQsrcqFW0eCoIbiBMEM2Wk/5tnpKwJILQ2HCM7c3ta6qzmlPESrumEPJH31F5iXDoyPRuh"
    b"TebSg1KS0Hv9IvD38bv8r/CRZHPFRt2Tw60+//QFvCuXcHqsssXdxNMrcYbs5SOItyOXrwgY40jq"
    b"+vty7loCcpomJqQm3YjFQ3Aa4cT6dJ+Wt/Ai/fxxkhT8loldHUBjj3B3IFsNvCpdRZhOWohWMZ7k"
    b"Y5NxT1V49ji+ykfp4BBEQVa+uv6LtUreOmxufasXghrLkJadHrKqRfeQJ9N7uzcLUiYWSn0Kb+Yr"
    b"5UE2hm2W7pKuc7cXH7gS0loeujXWfWvNsOp0NiPTdSrOYy7AVx7AVXHH1BKpMVetMSuvXOaag5hh"
    b"tGZlljKgaXSoS2JM3RWUwFwT0JJGIBqhO0TrOpetyRJXuuGXIwl4nB2RrCmxFuAL2jZfZ5C30Pd8"
    b"cduzYhtx21Uoa2hbyVVWqrh62dOMcymR0+Q82P6jCdiWJLUIuVjcu57BI06xepG8aYTYrrNMBp+1"
    b"hcBQbNel9oRlTf4dd8TCWIMBraoowVwmhA+xQ0KSpNxRmgCW2U/LKNWrllLtRTH1vS3NCDyHSwM6"
    b"uBWFBhRhGEj1LUY9gf+nrp+WvRDilytyJtvBG2zKbYT5K5WgSWN4iWQqSBGeRT5PLNVPeli8HDtG"
    b"zm+QVoNxcLxVsKGNl7yB1d9CT1jktMksdEWoaiwZYmejOsRO9XVx7K4cF4b48mk3rjJZZFDb3d/b"
    b"PTvvn53vnvdsk5qenrYLuoeMyhPlHBq6X89muZj6tFmNZfUxAzGmx7D8FHbSpmNPj0qLdIF2Wcuu"
    b"W6CVLpsVVXMxC8zWZtW7jLRMMRvuH8lWTNwtqdtLPNAPswUXXz2HeSlbfjlBzpXkpxCB30MTCym8"
    b"HZldJEfOiV7R5H8Co78LOp+xc2XmNo5uuY3sUJ83iU4E0FRIvbLwLhHokIqcmUzzMW9zzw5ztyiZ"
    b"z21Me+tJBtxEK5PJpUDo0b32ddv2QDoWNg24GZkDb68FRgTpi6UUgJsbX2q9YTX6s+lIF6sPVDyO"
    b"H/q3yWiU9zGkXjf6enPLlGTJTS52QIm+ixSJSKyt0K5NWKItRevwq3+XJvdgZv5ztNVqmXZ0skTV"
    b"C/BaUyxrdQMtSelC19e7Y5P7lMh6dNGn3vc3slyQTSNkekDe/oMo1lcWijraPpqZNK9dpiBWbR8d"
    b"iQb9zwm5FMiKbpFf+VqMMJlOxIYqvYqsTOoBnlzMZAKKu6sIe5gnFDWX3C69tBNWzMMo6nQ6RPh2"
    b"6jDyUyXc6XQ6eT7uowMRDVX+torFXO1y8UEnxHSm1q2as1XBILFbgVwbfJreic3T//X+c9ddKVNk"
    b"58XsQ8KYq3ggakD4Z01/VtncqUN47KPIy2jWKwtXA5ZWUQuKTAajUfwI+1RsiwszNPNZ+xlPy0Gf"
    b"SrvcI32QnFEIoK4WftGGTk02inKWdeE/nVHnJs9vRgmobN3Nv77e2GqwOOWR9XxAHBI0IuubkIxh"
    b"/N1ZsbbRgb86kySZ/lpgi6/f/IV7PHP4ZFYFb4Ff2rVBUc0oyStVc1oX+gcufjzSEBPeoHkzoT1v"
    b"zUo53HBr4823OhPlNC/zQT4yPGiLpyd19pezu6r5LIyQ7y35mxVKTdusLtC0mNsGQ5vJl5lPRdmb"
    b"N6/bzB4igNdNBlbQhZ1UnsPkanbTNcHl/n96+k30tMKoyiebTSq4By4tmMwkvkpH6H8pKcAt8MPD"
    b"woN5wZ+TeHyGDv6QNxKCqGsJifz+uYyDOZVQyIGj5CwpmzJGbH59DS4ooNKq/I7ZDUYxAeOK+Bfu"
    b"nfh31GIoLqxOhqLHgioWdQWxelSCI5SzwbWN/466pnftHKYAYO/0KbUkpkFiHcDZjoNrOR3zCXhB"
    b"frHLLq9By0CChuCgMziXHFVY5eJiMKgPf6tinegZcRBZpvfTElIcXpAKfIAVtfFccbxCPQEBh+gj"
    b"qJpIuxo+JadJwLd0eJOc0WoxATm+/qP1FBpJX64aG5dVHH7VLWdGpWaayhGxzelBWkksutxxc+lF"
    b"DuWaCDdbb1p6tc1W+qMIaynhWZ4hIKvIJvUXnY2tbUKq92UGdQnLvjnQbItqaL5tbeh4JnRFsfyD"
    b"fqhesNRpQcpKoep+kTvWfDYdJOIEjkdwGqrR8q8y9PPnhkA9/iMWdCR2kIoAjuTgtcC/LmhB7kHd"
    b"xEUDvY8lV6UsWW0wUN5M4yFZKIsyn0wAgD0ktHPr2Y1KleH7cCmMx7RuaMOZE/smZyQoheaEf3iE"
    b"zvQGhZaQIgYtyL/co5akWo0YZW6FjBqYtQZwQT8eJbpmmVWIIxP/XsHjTflJjpGMswZ/CjWsS2/P"
    b"8cKq7U0w0HH9FnfhcJt/XdGlAXO3OpUbJFR06lBHsBKNwKOVIGx4AALrz+5f11ncvQZ1ey/zEqSw"
    b"OkQjSC2OEcJF7xDv99jeTIejgEwkfwkKq9yRVkvuLK1CoCnqhg8Bt18tRXmAFSeHB+cdH8kwjYlf"
    b"1vfoAVb06MG5Peo77n5J3iPNYCZ72ZwD3dKC9veoEitBtgL60vKWlGmwyOL6nVjgW+TMgsdOr0cP"
    b"FM9N/oFkwheYLJUmN6g4OKZl03yAdxorLFEdWfKY2a9uj9jAdbctLjHZNQ2SjbVsySH4FZ4zDL+2"
    b"GYoOWbrsUPwKzxmKX9sMhbAVq3jcz1sev9rzF8pvo3pwEOa0G4Xzz9SP75ai50eNxqJRIKRJcULF"
    b"dR1b7Zh+PC5gAMzZ2bDksCVx70A/B+VOVYNpJfMtnieDrJgog/BmGrgtULl83RKT8bfm5qAOT36F"
    b"56DKr22whbq+qyRRkAHrffH3VpkVAJTh5Pe6YMKbGrhb+nCmLpdAY63xoVhxfNR5ZLqDn3pCpe3t"
    b"HtlNkoveQsML9Ft5K07duLeFpGm7F9ZOhvOAE5+VcUziX8Wv+XpzSwaSYFfaEkZIWMngcaDenpPm"
    b"wZJNQ2AMkN01WZqgsQS7qEV5b5r+C2jDVNbqjql/QSoOSewUmqvhy+q6+RZvTKpGNVfs6+vRrsle"
    b"LIlA+Uyh51Nxi+FPpFYU5dnokaLO6JOkYxt3jQIV8FU5QjV0NyuE8v3/zZJZciB4re00YG6EX+K8"
    b"EmPTvu+KkPMSQZnK37om0dMf76qimcoOpgiVP0I+KjS7mriqBECPdouf0/K22YDXzPR57W6r06jJ"
    b"xsSbwNxLwBePdt9/2D3s774/+7l3KtM8hobGEFwzPgbFgiq8+VZBSYacFu9ghySU8xmzqjW9BlqG"
    b"i1QTmbTufUEKc+kqLhbnDtPeUTia/7hvVC3BXYgNDExcuoBNk189dU62Qhb0KlYOPHo2TvhiFHWe"
    b"tirh+wqleeWJouxM5MrPtNIPSpLsae/8w+l7J4Qq2OLhKqOwPaDwU9CxX3f3Gx8W8jlth1O8qxn+"
    b"X2CMeA8Bo+pcj+LyKJ40yRHfeYItwwdBmQwftP6L3O3Nj8Onza156yMeea/W7TtuqinUxKcM06wY"
    b"QcoN9zO/lM/swSNRaYxic46VO6sjeUHR89LPWTWi7yxcrWhtsjlKroVaPaUcFAIR8NtUW6MS/aFl"
    b"ZKzXW+7rCxy+4F2E6lZArPA87dQ9oKIHtak/EfzaqycpoFmzaQnuNcQoKE1IRtvYaLTmuB6frFxT"
    b"XsqI5CEtSsq2EPDHo+E5Mfi0S16A/6nmDAu0R9kKhnuT74sNDszkqT4+LWh1cE/YWdNMvma2ka0+"
    b"t1eqwujN6x9VoMwyTgv08JYy4FgwbhkNb5xneZlnQozBxaWlFt9VfgzmCm1lk3rKP3eljhERV++C"
    b"SVU00Zib1ydEMLvyHK5INeUALX4BGsSruWOtOoe/es5j0GdM1HuoYk1IP9avkej00HlNHuBLcX1J"
    b"upww1HxcL38rJqGTUkUeHh1wSEG/eD2mRtu6Tl/i2k3uAqzdtSYgZSMT7XHJlFMnYmzgGYDZpaSM"
    b"zYgzHkzzooCoguuwFZIHegAPqdg7uhlMT+XskJXqIMScS6ixLHMtuSSGzGlhc3tL6+5GgRQ2cMdh"
    b"BAxQfbWEYRx7iCgDtZl9sxEPBgmYaRrMymgF4mM1qUk0UujuWmy1TUC6i1/itX+tXa7fpG1m0LCT"
    b"dojzRI11SYXd0MoX4q78qELJpVknurQcQ68SJdZ/kYcXiQpKUiAjD3s3Js25XvxDCi2q7R5CWNE4"
    b"WvvmDTtVlps1RRStmLFk2QtOFKaI2hJX0NagyIUJj8MEDgpRh156qqAWcpcVYh+XJ+QrZx48MUMF"
    b"iwqEe0c0gWxSwBsvXUYIC4wWb4+Pz8U23T1RVpvNb5TRwo5ecMtcNSOtAARvGVdo/1D/iRDSp4nl"
    b"6Ol7QnBXzxXaaF4WdGsA8ohoMm+sg9/iGGo18Czn0JWgg6h2/HT8Q62n9+yNupVwSnmh+Xk4vH7y"
    b"ezQTSYzq9/EpOaHGI/04a87JppzCu+WpdETavRJ7b09/bbJFf6L1ndOCS4BgsgZO1S/I2IBTtQph"
    b"7+koeC5C7F3Esi/47TwbdcvlXRjFYpffuhPHqLc6/K0JNoOxt3U6DybWQbF530lpmOCbinvyYTqy"
    b"vitPGjlYuyFZeCRk0zKfhgtPVZAbXjYYumOS4k7465n4n9ipB0NraALpN0np1LjWObTt7/rCyvku"
    b"TZH8jQ2lXhWMu0c2bwte2wjdtM/Y2O2sHIplDpUB78YE38eUpnO4FJCVvdGC2B18zvL7UTK8WdAU"
    b"B/Sa40lHAdjNuKpastLSV3W3R88/q4p/UKjbLd0i0un877rbU3Go+MVcUl8MUTWuc6Sjn+hME2Rm"
    b"t0JUdkCBVFwykcJtRan3ZIUIib1/y4FMpSSn7SBkY0eytJMgG1o18d8sQjUyodHiDBvtxMB3mwYI"
    b"fxNzUmk2xcb8viMztm6raxkZ/krIFkLd7GECVJJkYEBNfFhjgcnQekEg5bdXQFsdISU0BDMTGo1p"
    b"vQoMPVArAQFEhbJr60GEQA4wWnsQgnoDAXucNL38PCqvfQHkQCm4rbzZVqS0l54qVuy0AytFRuio"
    b"sZE7b2PwfyQxHmbMOw2k7BfI+hR65h9Va01GKex0OnwyTBOu9/k0mXROuEO8wZEJvY0LFgqGjkft"
    b"wTXKFcmwacVMVELpwrBvgaVY3G51WJZnIpL3vuzUzDmuZLqKUBB1Y2nbOT00MXSs5ywvGZ7H/ox+"
    b"sPiZ8OLmjZbwltLsZPl0DBeQyQ9lOSngY5ML0hB0QSjAKB7D3+qFlCX5KAvoqyfV8Px/7na2/qRo"
    b"dufVEwb2Tz6cHojjbpJngkybDmG3VPwEGqKKZSBEt7RAI4giP1lPuy6bx7+e2EXin1pMFu8V+xFo"
    b"GieHCKJiLRQmUgCbYbtinVv+hgZmmKNX3I3ALPrFmb8m6SRpsDcVw6SMIQE4c8wexaXQq8f08vg+"
    b"zV5vsTcWSXZHr68UuPgwD21tC4WC84tjAHSDeCKOxeQt/9y0cWYj0oioY/pLLYFdqW33FGxDpquS"
    b"Kr30i5DHHJnK7GqnTpTHeJA4Ic4q46xX7VyXPqrNkFbU7sXbPLDRtYNbpJSztsJh18HM0jzZel1+"
    b"pnwenpipDR7mcC9MZZ+13Ov1yyXm7c5cahzfdqvEcii3Sip81i2YkFe63bztes49wj2vcrvQdRhn"
    b"/uJ8srrY9k/23RA37IKQK1wlCPlLNZy23a+ee9eGiwWnQshVUdcJOQ/qwme+xn7Be2zt/SRd6eb8"
    b"sHcf2Cx5stp7tcNkGmsH8Ct1WvHnbSce+Btfak/hElM/k4ZGZ5O+hBL4EAXDAk1vGxuuCRZA95eJ"
    b"Au3UOTYhpRbxCl5bcJxJnrLwwvCfd/l0P7k7z/NRsYtBf05Ae1kJ8rVpMo5TsK4cpaNRKufWdCbS"
    b"YrZ8NtilsUw2i+Q+2htO9iRvMpdfn+6L7vr65tZfOhvi/za7ICjQrDrwPHPOfhfwXqGEm4z5p6Ag"
    b"3bRsPKJjhVehtD3NW65I7KUNOirYy31m71/QbseQkPhwerLXPz846h1/OO8fnfGLJB0HYLO9JOaZ"
    b"H3XokPdPRjG2DjB0tQRtZ9GWWy9U+VCbFTKLnX9RvjuUWjapUcZUB+mwBnqJI2xi2FAH+7xy2Gr/"
    b"D+HKQvCVomw2yLwg+Ey5L8U/+gJOM09KIlRRqX4jidKrz5JkMXc3/US3ZODWgFY1NlrN/JikaGss"
    b"rtL2vB1nUbc9N0NYtdd0wRxY2maoptyRn6xybj3UgIX6KLGqbIkagL7YpCSXUpmErvM9aV2HuG5w"
    b"OJYYbtmmMq7lShDWgrl7rgBQf1IYp9IawXBx7ZnQanhca7GySqzj2fkcI5edT9LdHSpIGzjBFnTf"
    b"kMV36U1csk2ir3RbNTjcB8fa/HEBBv2ZBZHRspSXhUN2NnXVeE/pdO8kD2gnzbM9svkVe0KQJo+y"
    b"Zt+MENyOJGV5/KYwhIjZSG3qbPnWRJbmYclRcYT+kcMiLU3dQU0Y87H8GJSIY8KUmIgFi4P+tK1b"
    b"s9ayXFFmmTJj6+SfAzdojDTUhbofTkVFfh2NDgzzofS+AtG3+bCtAzyBB9m1YII2wl2fD7zXDWDK"
    b"am2J3MpOul9SSxl3kJ+YO5844/pHvfMfjvf773YPDnv7DRt+1WIK5gB3kxZX0YY1Q2OPtqMnVGZR"
    b"nqMRM7Lvc8RiHcZwk/9OfVVzlhfhU8uh0MMwW7dmA4HFNsF/DYb9IyvPTtHloomQbemA0Y4CyXVN"
    b"VkbLx6PlxL9YdImDHQXcyirrynsdWe823vr6G7vWonsed8G2g7EuKiaoLjDQR3o2EewmAWf5VqCt"
    b"ynFAKvPa9NWVNb/bid6d7h71kIo/nPb6hwdHB+c2LQtqtinVSgFtL45zdDhBR3DRnW/ou4OMgwhQ"
    b"ySUy0/lUCN1wNI4eG17FrqyoOQ62UFTWabXCKxO0nVl3nmJC+jZtLwYdQJuGk+wuGQlpG3aOtUV0"
    b"A422Bmr5gvsfpBfTO5RluD7P3GOEfCvobMVZ4Rn7JPA7XMqm5Zlq8cdWdSxbKVs6SRDUWZJBEF2m"
    b"YcvR6xhnjGg5pTJvJS7fuqf3NruGqbhK5+5MZMaVMKCEtZ0uvIRUi9DJ84Shg9yyWomjmVRoJzUa"
    b"itFUhRKMmdCMetyqjk3kqtRo7wvbMGygpf0wtbgNgQptEdYGw5g6b5ngIgMbhhjAMxbEqE16UWy9"
    b"qYJcDHThk5dWoAwU16C0HMYakS8R2fw82QIJB53xa+XJSqnyt8mWHmYX41bPEgcdOPqXEjuVr6wv"
    b"f1bx/ajGFWF5CWDOeQ8wprUqBwlx6Dpp5is9KUQ7LjMgyjCvU0L2EvE/ZSd5NrPBp054Uw+3sj34"
    b"RW1xgpGDYMoymr0uLitYTmir4WJTb6Iq/mFU1NV6FbUm+jmjiarDgx/5QdWCMCElYnb1Kqj9akQk"
    b"wLERumSK6vlYpUfTi5iSwCQNVsiVtvwrn88Eu7IRSvVMnGz3aNheZvS18neVg1aV5K3Vl04xuxqn"
    b"UocIrWKlZrcM5pS65yl5u2+PT8/7vdNTP3S9eXpC7vuEffJVpRd2gziLrhLx/8v7JIH3VVl6nUDi"
    b"Mk0ORWcB53D8tyrYhuflZfEMm64XxPZ2GH/IA/m8d9gTiu/pP908ZPD/vpXOyL/tALCaRIZsOdDZ"
    b"jzetsLOO2uK8bvyu2hmvRqNRlyxKyneKnyW6LOXP476ocILLu3BZPClu81LDyd8W2NzWUgHJ/nPf"
    b"f5wdv5fhudLrx6ZWWfDpL74s86Ze59xoD3vbqamVI7W1dXc25Dx8cFfu92Vp7OV7Hnf9GYT3Mxoi"
    b"pC1Eg3w82o7u0mGS60dsRadCzTQ53BQmynTw2ShJteqZs1Hq3Pv5pjC8JeD8KdjL5sZGwL5d6Sxq"
    b"MZoah1Epp1Q8AF7mEOVf2MPgRX0//yytYMXc+5bw5PFh20HXQo3v9mwbbKSsLl3bNVeuiH3xXHlO"
    b"925WgpspdPFLX8YtxdIMO/OQYYG57hCVgkagFrlKBIWMtk9nKlCm/Bl4xLec9LBq8CvYiWtzcN+y"
    b"unWWt6abdXIGwKZmmpUoUW/idHBH+4j04K1IAEuIqBbFLDLMVra3vagRKScGl7ZGprf3sHaTD8tR"
    b"zIve5mvw5iOmUKosuoy1h2Qch+dSDmt2KdLBvC1p8Vm5hNpK+CKZj2fce77cF05JYVVkj49fKPmF"
    b"MsiwJG86iwxHgi7f/q8QD+ZVe1OP2Q63YWggFFbK2q2mBR4GK9iAArDq28scGM93Ve5d5uVd3UjC"
    b"3mScIioYB2AqNJyd6kgRC+xCeijidCoxbJFqNHm4jWdFaVsDbDmTUxez0Tt0ad/7BGWXkPQSRPxX"
    b"KsJ5JYJfuq9scgyueS0FhoyK8WQySpkt2mKFuglHnHiWnrSklmTEBH9iDj6Vx2MdYucvMVYqZCzF"
    b"wO06LzVwusRdTcneIwI9fV7j+afb0th57gk3j5JRkbisMxzKzx18KKifBbph/6wL9qe4lMU/ZXyr"
    b"WoYbzBYXYr/1fH9pTuzesNY3u+Nz6fBRU9nUs/g95/jV3L/ipcsX5bnPoJK6af92Lsxar4xxupSk"
    b"XNPQ7VLSMmvAE/7rRfm6Nty+XSnevTOtuP1+jj2g+ibcHiL/yq/DX2YfCN0XyAyutfJ1WLreOz46"
    b"2n2/70vVlkxdrfiZ8HRyDG0nQUwjHqgQdc/JLW9HQZQ5Wxy2qPLWLh2izq62bKg6u9Yy6TztGoQA"
    b"YtDX+UAcaDacc8joWT0ncJmDENvw7DzwruCG1Xd6mLxXcEH66YlXldfiv0HCCb9Ld+f3X3Uf8z6P"
    b"cHUjiT6wzUKYJSHyQ5ILSkYSNMQWoySZNLe+drw0TPAr81pcdW++1AcDpAbpCTnJiqu8Me7p5TaM"
    b"V6Omh+tUNDTScW/Bi1Y/p2YPrVVoHnWBZj1LpzEpRwYYjD2+qhhbXoAG24oZirylqvxBtkV3hIYw"
    b"29Fr81JnUXwu+SAhEiQzheakv34Bz9tuc3FixeAI0AkE33IjABgj/3QsVq5M9pMhXBCaR9S24xQ9"
    b"d2RRrZ4Gt5ha031pSa8eu3a9OYt8FX7jCIbrRa+SgTisZt2wTQIb+R0+glSzIDjrRLNakM9k3Q2l"
    b"ErhX0NtSyetfkMD+GecqdU7DRx7kvgD9XpZZB8ALM9hXHQYvyM1ewY41tc+dlXCn1dLYtr83zeN5"
    b"K+YDEMRhKnisgKsISrGwUjhEhanmVqgIWFFbIRC+Yh4IBQa7vSmOzzuI+Clbg58ynNmWjPCE0YI0"
    b"zWufQEPFgFoZPlU1I8WjopOJY61TTEapOOE7jdbFhpCr/hZtbTmultwY8B6q/FoIoEgcDBm85oXj"
    b"DU46zNBubTAdfKNAUw3+YZ63w2wkePPJzGGuIIeMGdCHzlifwzpaebKmwnM0XCaxXGg0A78g8Jgc"
    b"A7vs316xfNQ3tr0YiKGAbnbQ2436Y9sNOF8t98vQbs8V+91wbqyCDuy2BJc62O+9Pz94d9A7pUh9"
    b"vgxN2RhsLrX+y8Xu2v+J1/61sfbX/trl0+Y3bZbSwZWprXwOYT714tQDjg/pUmEpfy+bop1Fz83+"
    b"5UCFk+k5iilBmTR6xlWeupCMz/ZcCT/VNzlXdQ47T23xUtqB4vJta8X1ufchV1zveqffqkABi8IF"
    b"LAoasHzogCUDCCwRRmCJYAIVIQUqKKI+sMCC8AJLBxlYLtRAXcCBRWEHaoMPLBGCYIlABJXhCAKL"
    b"GIpB4DQkYw4UMZxK/0qGdFgSM3fy1i4bnNXXln1RiqzivYD6sJ9jOMfkYSL0AOOFjO8D0lGB5/rs"
    b"5hZixIhRhtQIJikBBBrJmp8g0+kwKu/TTBIuj3jYjV49BVEw/5h9sk+9TS32iCN9NoJ3kPDIXkUR"
    b"8fktsuy3Hw4O9+EXWD/ozRBGnYZP2vwEP2xJA4P6xxkE4I5HcCzABy+bPDbiSQDwFa4+3tnpzuHT"
    b"CXpaii7PVQQWL6wq//gPcQrJhw9+oCP4CkfBMNZxZPbUpTKO34k8hFMKBQ2CgsrgC9iL61INH62A"
    b"CPBBXrzsjSAHC2vTqVfxBASK6B02+4BrcpKh3dTxY9Zoshz54KvzWhA+uY+g2ib+mxVbTTd6mA8+"
    b"o/aAeRzUj4PiUGAFR+pEUWMNnsMQdUNOgB+aSCDyDxTkTDX9u9hr2GqlCi6bCkQ4g5JwjDIaZiBg"
    b"GB8vfyAh8e5/DVxz0JbxYzTBdzsAEy3tjU3zVRmXdG/G3K5HG4zaHiw1FUP+fG1K6EHMFCneYkk4"
    b"A6FbrcADVdI7cfk78BF1C+JIxFBRCxPs+TbJmmQEVG9Tddyrh7Tcw5IIACglBcR2/n+2cW22"
))

PAIRING_JS = zlib.decompress(base64.b64decode(  # generated from web/pages-v2/shared/pairing.js
    b"eNrVPWt33Lit3/MrlNPcjnQzHj+STdPZdfZ4HadJm2zc2N22N3EdWUPb2sxIU0kzideZ/34B8AVS"
    b"1Dyy2Xt623M2IxIkQQAEARCk4ziJ9p9Et3d6s1pEdVPlWdP79s6drCzqJvrp6M3Ji9c/RvvR3req"
    b"6PWzZ0dvzk9PX56fHB2+/vHpCVQ+2NnR1a8O/nF+8vT4/Id/nh5h1e7e4+i/o92dvYcc4ik0fXX8"
    b"5ujk5OipBf3jXgD06MfD108Z1De7IaiDH0/+jmgd/ePUQD54/NCD/Oub88OD44PDF6f/NFB7exZ5"
    b"1Qsg9uzFP6CuV02nW2lRfxTV1nxv0NNwb04Pz2Huz178CYBeX/wssmZwWQnxi4hv70RRnokTUc1F"
    b"VQ+92rdQG/ktZtUYAHt1MyuG+J/BeHBVlldjMcjKyXD3jw929nqLpB9qSmVRJHsIDYX/6zWzqhjO"
    b"6q2dAf4aTIWofq6p8wcP//C41/cgxawLUgGeJboJyExVpBMB6EtY01lWiZEomjwdm7qpbL9I7mAX"
    b"dxaJJqcosnIkKqBlIT5Gp+JTcyRLYgMyEj7IU1kS92bN5RZMIrq9TBscralmAvu+czkrsiYvi0h8"
    b"SrPmL+KmjufpeCb60Qf4nURIvUrgRKMfynIs0iImBAko+v3v6aO5mYryUpXt74NMlETmnga4e1BV"
    b"6c0gr+lfOUKiKxVLPpixk0FdVk2cDH4u8yLu9XsJdfp2MCCgs1Y1dANzWbDZXNw04qUorpprPRib"
    b"iCLlQP6rx7RN3K6K8uMJkLEY1bHTy6u0uR5cjsuyip+mjRgAHABsw1ra2fGwgdZZ2vwAA9QxTGKa"
    b"Vo0irWTcmIYFvlHNAKRilok4bkrgVZ8KSf/Qd3SfChi6/QjH030hUcRIycDf8qJ5LGkuxyDAsWii"
    b"8vKyhn/2ox0suSyrKJbtsXOojRiSkep0AC1iLO+r5tRbpPu6v+9jhtULSzHZS5tR9Wn5Q1qLRw//"
    b"Vo1jKpDjIp4XeZFWN6hmegZRD3/9+zvZGR+fobbz6TEyRk1IdQvlJ6DNiytQCOXk8DqtDlEigEey"
    b"q3p2kRL1ZD9905/uLvGmeNGUaSw7T2ggYOZ0nGbiYDyOe/dhBfa2eoGabaw592ri7f3797ahoudL"
    b"t6YWEI6ESi3ZSfopn8wmQJXWpiAnnl9GcXvF3sUVWxMdetHnz3Z9D7RgAsBOsOaJGVPV3t3+19uD"
    b"rf9Jt37Z2frj+dYZTGAAGDZqleFKVSxorqvyI0npUVXBIurlBcDkIzU7UNdyqJ6hsRbQ0QgwRZHY"
    b"7yGpRNrE8cNoy8Xsv6KHCf3nW0eS8KsBzjtisB+lTXkhUXTYsoVsud9LnMJzLNwGpXRf4yIxjGCN"
    b"Z9dRfC5wPr92miSAgJldwiSjSrj6UQbCChob1f0T+zHIlAwfNLGSTuR51ypDzjP9GMC2KIutLIX/"
    b"5hnonk6ctfhjt66sNuUHUThSOlZaC/dEttBlU4c7igRd4o5Wyyakf69Jf+8Wx168N+gbGjHlQcRR"
    b"WnPNrrqpUKXFqJycIi20Jmb6X0+0W2Vn1c20KQdXonlDPf2EFKgVG/2h24z2tiPNzz/XZcH3R4nN"
    b"PK9z1Kx5IybS7EViGtURqQqgTjEbj/XCNzrF1PoqJQBxIU0KafMkehJ/Pnn940A2zi9vYgRXOw0i"
    b"0eqkmE0uRIW2RvQj/QQ741leAIBsqsUhWt3/woziGiyqH9X+/dt7t1gymKTTmKjFbJHF2XuLKyEJ"
    b"eLVwVvZRC7X3t/duuT1EA2t7B4czZihUI3Pe37v1pgMVyWJ475YQow7eQtFZsniv2nJkF+/5xFur"
    b"X+4PeQ1GUGPFhgio1j6TPTmgFKfgJv9cfOLbu2rGdJtd9X1mZMIspWZuSrlZx7uPEjCiRicNmBvx"
    b"HmjjHWkDqon52+W1+ORpDr4Ev3BPtNoB/Kc9vv2lW5ew9wV3vs7NAFBMwXzPJ6mjWhWJ/D2AYTNB"
    b"xRdvDwbbV8rhmKY57QlqLYBJVosXBRpueQU685G1ltP6psgiQ6b6Ot375pGkU5tNnm5KP6agJJRa"
    b"AjOpAU9slF/hfHsnzw+2oCfYJmU3S0YLiwSTFzlOGzWPxUTF49nFOM/+/PED12nI3rst5+ZtL6vm"
    b"uI+Dk4T/wAo5L6c1/Wxu8J9P+J+b3plRHwq3y3RcC75vMGZAUyk4R4ee0MBosuaYKONWAg5UiU6Z"
    b"EaSAxzRQWCZuc1XKBXM3CPF250wiAV43aIreHaZzzbTs9uvv3INP/egBrrbrEs0wIjapoU89pT5b"
    b"LW46Wtz0lu3bIUqrMiRRiPNVPgcfbDnrLUHkQjEyMFpLEJBabXL9P5WAOr8qfiX/Jck3EgDW5Kaz"
    b"yairSQ1bT1p9PcmZanXxDHSqkqCW+ITFa5km99B2FLnEEkRhqOVAiiLwX8Zk5Kfi1hBEVC3VM1XR"
    b"3AxJtuTnp2GkOUPfN/r7Rm7N7dnCQpBGaHiengJdOU2zontLjVAv4BKyP32FTtvWcSfO6DEQyMiV"
    b"WWnB1kA0wPIXioOoqNhA/hsvdSaUTMqeoS2ZVvQV2z6ZLerORDaTXhVD4fPnyCevgrTmXyedfRJL"
    b"md7U1wxyiy0OTcr2Ng2Uy+fiObQHk/pKVCDZYEtgf4Y5/ehKFKJKEZ5JlBcIuN191N/de7zQVpFt"
    b"gwQCm23lJGwL31f++eMHGTxriYyDKIuSSVMFHf+WfeEJK+H0HmPc2NcWKk4gxNZ8793OvVuL0gI/"
    b"XXEArKTRnQQWB9o2EgkbZNoh8yxsLcGwyIRTcCTrrMqnYM8ZpYQhwptxmY6W6C0Lvbnywg7VCOjM"
    b"KP/kOq1ffyx0RV/uKSnMUSzhJQ3QmElE6bgS6egmgs6iNGI9uAwGK5fWk2GYa3jmkyl4SMBhya0e"
    b"UF5pSEYk+r5Vgfijw6cnBz0Zgxgdzqq5MBp5ISFpD9GGAm2XZ9JwNkpGI9uBFNbHwUFhstfwqc1k"
    b"NaCeo9oRlqlMze5EY6S3FwouK34Y/IZthewZ8wY0SRYh6ZObkCd/ng7wNhRpwkhfSlkibf9KnxIo"
    b"gOAhQaDxwJKeu2lBcwY3CgOuCzSp3b2DMzS8S9iB+xFwjm0EpsIPID162MYp2lCeHYmO1tBzGnJ9"
    b"aXfkPWJ2h4zMbGhy6UCtVBn7JJdEQAoXjATwQOjqgcMd1ZtLDonLl68ly7WNl1bXWlCaFYj9Q15g"
    b"CNhRxy431lTK3Ya43qRdlgfNV6dHjDQ5qGzExvbU09Hop1x8FNVxVZaXGGjydp4vUtZV+lGJNnMF"
    b"qG9yA2CoidyKXA3+/NXBYSf/VyrvKc5gpeJWg/wm6pkwGHJzwFPKBLBUIbeY8RvrYBbcun30cOHE"
    b"twaSotKUC2rijZQC9bZcXW+sQ62grSlqawrb19WdKzVgt1D6cU5JRZxc8kWaz3XGDmZN+axKryYC"
    b"HIBL9YOve4BKJ+YY483LE5FW2fUxlcYqcqvbKUGxJ53/+p086EycoMpbeVoOHchweNI++0cp1hy+"
    b"nPbBIu8jR0E79pGf/bljF+CJhRVGYvi+QhwPV2KSgV4i0bOAFGx34EhMfDDm07jQUNGGdlSz1wDQ"
    b"bze4tB6YB3455dDBEA4RA/wLJeeB8EtoITB/eKVntVzINeWdsCmfw1zyUh3IxyqrKuk6WO72J4P6"
    b"6sGegWRkTEKy4cRqMEEJ+hzqLC+17mD5gCIogAaVWopEXx29kT8sSmp9Ohaz3KgsLu2QTTYuC/Gm"
    b"yQ7L4jK/crNP1KEcS6Ky+VYDW0xnRjX9xjMBkwwF60qW9p3sKFf7S4gBViXR97QYWdFZNIzYp0pb"
    b"SgLTSMFCGoGmOoXNp0Zr5WQESI2mXHngxqR1xwmIQ+KlpYzzQmBaipIOaK1VSD0d5028/a76/l2x"
    b"bTxPFYJI983ow+1c8h+7Ajjot8mLmbLIjemSYR4OguijlXcXgNu7+j5J/Oe6uhx/+jyl/1ZinN4k"
    b"7y62c+YJUKtEzmcAFpMseLt7NmjKlyXs14fgWsStxBEkLrXRGs6lYVoDqZuneQV7tUM9fXKtkp1a"
    b"5EmiJ266YadrDhCR+JQJMaqhUgAtihnsrnhshOkW43ySN9ovDwQoYP/OGvAuOLPjacas32mGOCkL"
    b"ZJrhqj9p0qaWdojuqWfWY29WfCjKjwXTgDXB6w2f9RGbNA+NSLRvFjS1GoAwHaXAUNhygMDBg21Z"
    b"RXyQx7RGeLaQDCadLYpULwMzGsxMlxXlJAd/Q1CwRMM1GFGRp+KzDIksRr0kUefeDGcJT1Q2W+Fd"
    b"Uw8dwqTrrJmynwOKp9CkQoWoDU71R+LESeVR4YomRGOfu8fQMmZSTz3h6PDvYFyCTZHY2KIukoRF"
    b"ueScXfizXCYA1A+gLFmK+4ZuJYcwCL4YcctbNrMH8RIdRzE5KQs0r+9DYFQz5KjxZYpi+aysXmTi"
    b"sJxM0aKFJdCPmnwiylnzKh+P81rmEmIq7zcmIY1ImCHZ/5TC2kMcTqzEZKovuzTA5p9AT2A+1eV4"
    b"LmI+V1zSqj6OFUAfKtHMT6zYS3pm1ylsQCh4MatbgtDdIELf6oRWzOaYTbVkIE4MQZUuYFS+pApy"
    b"UzSn8iN20Qj0h9OImdrSuEQvDo+iK40sdT6KoMeeDuovgnxIOEZquBY1sLzSGKpODEpApkpMyrk4"
    b"moNh+zKvG9z24x7QzqBDy1/SutfXRHdpAt3AbvGFfagvSadFMG6BdAJu1K3zfVp7siDKgQppkeES"
    b"sZ4oWZat7KgnHTnqnfsLIKJQAMboXUW7gznsOWUZjdPqqp1VdqsbkiGGKWlC5xYswmcWgcn2I9aL"
    b"SZW0JGC1UshpmCWzqWdTVI9sMqyLnpNa9kXkdTAMYLARCQMpaXV6KUBX/bUKZEi3E7p1Kgzo0HZu"
    b"9Xf77VsDfhJ1NaHjsOdNM60xEE0Hcf1oOqumZe3kn2F6oXEiCcx1CqEePdumzMqxZNU1djo0MQwE"
    b"0En3vGwKVtTHshrxspqcVF6CTn4wWef9vVuF7SKazDBtT0RpEcEUTRo/CMPz09PjE8T8vd2/5eDN"
    b"NSIEzveo/nsOxMMc0iTidZiPDKVMmWOtSXsK5byATjhMx+OLNFsr66Ws8qu8wIwGHJOyW0IRcxjW"
    b"dSRdnsjoguzrC+MbzmUCh6P7mqNDY28RW8D6JhpR/e7eHwY78P9dAwO+3i44eu9Gtzt9G5uinsnu"
    b"UWAyK4qVg+w++uabB9/wsQw/aKxte42BSQwvQpFxCoz08UIjfmwkSUMahxNVg6gwTqpysHvbuOi3"
    b"JAl77ThNpiRhyRF/W16WHAcqF0B3+9sc8h92IY2CqIf+LU75dd9rnPNrO8CZk24fOPBX8G2SmzbK"
    b"8u8kvUvzTc/7g4zj0UVD1pBCeUWtX19eikrTDWxdXP/sKowfZm4rGx2VM1iA1gFViZ6RTLiagjtL"
    b"mVYsCoKf7KBfhyfo4PhcHnmcY2SKNBi4ZBitojmdT1MyjPQnBbZ6Otpl+gHPuOecVcMH7nb471za"
    b"/WdedpXM29K3/JwqcmhoC8IEAUn1rRIJZzajuyYn+QQ23BdFI640WQeKGsk6sIpciZ84RqXm8oPq"
    b"kXBqX0L0EtIk6BNi7v3owU646++oPlilm7ZH4t2titzJPlv5ICuieLIVD4m6zdwD49E0mNHboRMH"
    b"fJlulCK3OsqqVbpMxtVi3AXHhVkFZ9Xa1pYaifmSOK3sx1s+Cj5glTnD4pJqjUjrTHXgh6UMtZnu"
    b"vOtaDazrJGgUSQCyjVr2w5dn/XkuAlGK6bnWwUa3yvtPOezILvqwDvvszAOj0n3SPn2SLzoDEY08"
    b"B6ma/rz/Sz7thRPRFY9hA8kbuQrr7FpMUnQr1K7Sc9HdIHbPQRFJBd0LKkwOjPgmzB1bF3cVtW8h"
    b"L3kH3jvdkr01gfth5xmQCekPu45//Fj/sOvkpxXxH3ac4QROC4Zdp0M2598DIa3CYZTSHmoTmEND"
    b"HUhj3zGLhiHzjDfKDBKqpVxzBOgRtHFRkYDHoAI8OGEA9d0SphGJbWEN24LqOstqAQYVcXtQO7NV"
    b"Wjikg2Un7RMzaz2t2CJlB+sfcUl4ftC13MSQ8L6J4ZS6doBbtdwOWHvR0p22KK1EaNGC6kRHSYX+"
    b"/RCPvDnkG/1ctqSS0WIYuCArRVNFl+h3OMClkzrULWRRbeqb0Ezs1WlSRZslGlMr3+1IVlze3MyT"
    b"UOyR+LEQk8OZhZ9o0nIf5G6E4mGlCotoGdME7Kp2AZg9aMEcI5EBczPQQrvGIQP3rCHWxD2TdxrR"
    b"EYeFpE8HQK8GC6NLFFiAiQPXifQgqBML4RKQWYackFZTBeHR7mqBoybW0Hp9hdK+lekRIFXfqbJs"
    b"Um7uUp7clUMGk0xDQ8kJJUvVipRbyja2aZ1lhRe+6fJ42DCwNxz3l+fKSAySzbIFHGtH1oDFRzPs"
    b"W0axn88p3YhnqGOamMHEHrX7oX7y7PgyvKVTUCimFAWdqqASFdw0BcYg/GxxmQqcrGotoP07jglg"
    b"P1G88AvNWHQy8HfbusbSsjgWojosi0JkKo1GncRQrtXUqXyWZk1Jt/czSpBAOJSEN6eHbi+xrMfX"
    b"VIhPq7Ji1siJ4V2sbxtIKTNe1+iNXX37IWfMM5bUDhVwx/Se1FbG7ciTWXbaLwvhs8I1Cy7ddk6s"
    b"Jyt+XuwaGmfJRRPUKW76TNJx3yCn6HxzgwrAi4x1KIJphsfiIWmL/aQcauXLLSY+MLVynULFWJ60"
    b"y8X5NG3SQ1kcU+yoEWMxEWBGbM338J2esgKCiJF9qYfbGCwvpqlwFuWlWt5o65xiEbmr8kyRvmMC"
    b"7Csw7b7rNIpaNC/xrPupkHoXp2AqJcZSkSROy+Bxt3OiioEXmvbY616lKvjFGDsIhxZsUMHJXeAP"
    b"K+w+ciC0baUUaPsGjS+e+rh37ulvGUwaBoJ8NiU/N5lUNhGsnQHWUq/a0WPWyDAK7qwqXDdEnanL"
    b"jEvXYX5rOKCd6YYpa6tdpBkx9NU3A5iSsxZSFSrxy+GNstXX3UMtT7MPZDGrhF7HxOdmM2MwbpLe"
    b"PS7cJdvQSyM2jPVeDEPToXsTd1n+wbLsCkkaEIHpMCQGIAEdrOfSBSw3KDpmp0E0g27cgyCj+g2+"
    b"TRerwyzWAL/k06Fi0oCfpmvjD/EJ3DZSLWTOQUBcxnmBhzDv79127YGu7cB3QX0Kjr6fekZk8bt7"
    b"t5LZC/YUBzu1xvF0XlzgkaTV/hAh3D5v189oOCYhZnYY1kiN/9W0RktSmPAxY5KZky3N4cjQciUR"
    b"UAvHnVpBwyGp9O9/VxhzGLLMA+IEeycP1JuTS59mmYB9obhS5TZhxvixrhuLW6Qm8wC2aky1/Dbg"
    b"9C4YOG5xKyFJHqjMZEAae1vKxgE9gfiiuCxhwU3Ti3wMJseyd+fszVKlVMwjivIuqe6DnOPFu533"
    b"0X3ZxKlsXUE1NShefhkTJHk1tfvO7ys2K7xG4U9KPV0E6+7XXPRhuHVfxOg9/8vTZ73A1R6JKQxh"
    b"7/cE708YOHWJTImXvt1he4/8Ox5mC03HoBzZDQuGuF1d9qoFKB2QhOFS2VBpaSZ25V5wOjg62frT"
    b"4auefq1miFcOQ/ebQJxwsvSShZA/z9q5AVK4DtJRLIq5GJfTpW8iulu1cm6HkW46mPfvWLvIlOIn"
    b"D0ibCqvpeJzcVPsKjwh6LjlhgGyhilPzpDADxUopFS4o4IpiXMIZX/qKVv2oJJsUbYbbhXP4s459"
    b"IztJuFexnnkjgfM5ACoEBvDx+XPXI2DevbHdPXuudDeGlt1ZZ/ncv64KjVdEBOW0ohc/yRwozKJH"
    b"YuzuyX3fv7mtGWOOW3zjum1ayxGckw1Pq7VFKagQ28IUXLRtaeoycfJ5wLrJ5/rgJJ9eg8tCb3nY"
    b"Awzzeisyj3PfUVCqPqiejCLQimVutsfRKMeJggsF/uQwtMaNB5NevVRqZHfvMdc83P1eovM1O6wp"
    b"pzWuXXuGAHiDesWdc0MRJ4ym+wonpkjEjmU0WueZ8IVLceauJ2uXZKhsmpUS9axU2dwSk5BCGScm"
    b"16SdXuJkd80ptUunlzhV9iJC20pQMfmenyqGXjFFkp0V40LJe28uFJU5UPw2mwvLapwWzgU1twmv"
    b"ctpYQvpNrHvn5O4tz6RZDWpOuRw0dDbMd/s2HcYB0LF8D0ldHIR9IjsLvJJMGSnejQP/0bxZPlYG"
    b"9UswkwMbFL7w3IpocpZuGplcw0XucpBd91hlKBo9vVRBhxxWA+z5rui5dsxQKjMizJARyNykWdfX"
    b"bHW/OvTqe5yb+ptde62+vRJ2N1maC0KsOglQdg5ZMVaUKHh5Yo4GyuLQ+qgrovHhEP5XitEvP1b0"
    b"tYR7wrjsQIm19GLLfp/rHDDZ6HFfudTwo6yiWYHhRsFSZlYeq3Ui5tc6h2v62DCkZ9c726UIOdfO"
    b"oUPerxsVB4cbrMZKpt4KvPHiX0uSUWpdO5CfqGTdgrc7Z+wJFhnZNuIcs1D3wgwLkpTaeLw3uMya"
    b"pxE0DFjJTsFgnF6Isc35dOL2LH5EkQW35cogQ+TcppJlZkHGTmd2VvZUwI+Y+wLN8vJ44P+NmJSN"
    b"4JH/Wzfq7cY6oZO2HY1dO4G9TU4WlGL6zzlaUC7O/kYHAp5ZxmN8Hf6LTj3zjLB2FHDp7ulllIVV"
    b"gRMHXOkLrThsaFs/TDba1/yYByhZu5737XBE+RTunx653/YxNKrL/HLjGiX2fY7Wlt2QafUk/GdT"
    b"VoeJlQQR2t1xYvUIhTHx0GtaYvQRTt8ujzCryIWhg5yqkVrowQ3gvlwanrUwyXqR118dSpUpUlIo"
    b"jhT2ihmht5ob/XBqK7Eba/DWddXIw2tHdIylsC7Hl5oCHrOdzROTxKxP+yvvsDAuDmqwDoQ7K/X8"
    b"q3H5u2aiHySM+NLcLAHNhhD/D3LQFH0Nssuz0KyXb6SfOfomQkGXUdh9zZaDn89Xufmd10ZslDR0"
    b"c8SJlrYuj6jg17p3JwIh1MD1CaeHvb12a5XM1nXtgj32FAjHeg1Dodh1U7h9VnfkoLMIaWuRmOHz"
    b"OYXjWRqGE54KLq5AKMumgga1grbvQ6FUitmajnj9d/jQ54Zi35Ueyy9KW5HH2duxg2li8nDN2Yan"
    b"ghJ35F6z/NbXXQWLk1Q/8drjiH+b47tVcyX5Ay7r50CxI3dx6y6dbGTdrTP+vrr0wXYlVb3+7tSB"
    b"Ib5Sqtw83zfqJr1R7IFdbQC71iT27oG4qxJFyUyA5ZyGVj6HbafKhpYub2GswHWW6KgU8q9CyCdz"
    b"mmvgnk2gbwkA44p8uhnDyO6G6J+OeAd4LD5uI+SdMXIeJd8oTh6MlJtY+fJo+S3/4xxDQwR2KG9u"
    b"m6gqbu97d0habLRw6rYHEwpb514vUSABT8BJMQ1JgPTmjENg5Hnlo3Yh3rOnT1fIVTprrjFbL5Oi"
    b"e5nmY77YUHgkZMiaWuOOQOT/IQspdolvMofyWzrvAxgvYrPkf+NnbmZ8Kf/oa5pev45ny64H6MRq"
    b"7cb4165aC2GdRdC1ANYT/mWC712V8nYdHXNxrtO7h1L66Ng/lfo6lO5KX0dK+1EN2cQEfTr2SBY+"
    b"klEZu1eGY0Mq8qEPaWU8yI61WGrhO9vxkrgYFR2FcnWWbuWhZssJio+eZeVsPKK9DB/0mE7HuQiY"
    b"Vpax/DW7Ycfrdoz40va6GpcX6fgUtsnBm+n0WGWthf4wKos0BRM6ndfcdEFbLeka58BBF7ZMWaxo"
    b"PeGChY6HiQX2mUH8Mt4WfrA/SXnHu+2iq3m0hso8M5wuDdiUXvw0OZ344f4dBVviXEgIvYxsy/Wt"
    b"vH74sl6fHqMNhOkJl1YSMaEQOGiw5a20eKxyn1K2wF5h6+FVRdi2xPXbGoAQDj3LhxXt+Cp1zTdM"
    b"SYlWUdfVaRpOh474vRCX2od+qX9TgZr6N1gsVzyji4SwHVAk2XJjaX6/FjBknhM9Ww4S9eEcddBf"
    b"6F0k+DbP/wI6hwP9"
)).decode("utf-8")

HOST_HTML = zlib.decompress(base64.b64decode(  # generated from web/pages-v2/host/index.html
    b"eNqdWM1y4zYSvs9TILzksqTGmslWakZSlcv2ZF1xPF7Ls3PcAomWiDEJcABQGt32IfISeY68SZ4k"
    b"3QBJg5KseHMiCXR/6P9ucPad0IXbNcBKV1eLVzN6sIqr9TwBldACcIGPGhxnRcmNBTdPWrdKf0z6"
    b"ZcVrmCcbCdtGG5ewQisHCsm2UrhyLmAjC0j9xz+kkk7yKrUFr2B+todhYAXGgIkwlE6H1T3ipkkf"
    b"pYO01NaleSsrEfGNdzfTgbl0rknhays38+QiUKdLKFoj3S6905UsdhGMgBVvK5daU7DvlVbw/Xtm"
    b"CyObbslCtaIlt6tgtFKDkNyv5JXO370nSAVFYCMZ7LvJ5HXWAJgvNit0zbb2mSV8q1uyG9hMaZtZ"
    b"XaAJu82mNU0FBiq+i1jytngEhwuGFxWMOQItAjmTNRUvYLQueN3aTOr3LOcWUjTLoPdKmzrlhZNa"
    b"DWs6/9IrFZbIzk66Chb353d3Dgy7Q1jL7vTj77/VyPnH/35l5BjB3FYqRu6ZTQLHq1kl1SNDQeaJ"
    b"t6gtATCgSoyAeZJNiDYbHLuZZoW1dN6kC9Jcix25mUu1eMWYj10w9IofQm7CG743rKi4tRjjO8iN"
    b"3iaLnweJZpNmoCvPntECjzyL0KSYJz7OarCWryHp8W2bJ8xoDHVUiLvWJowbjItKbnCpwWhzkCw+"
    b"c3SuWpOBmSuBVRqzg11c3mFcGdzI2EMpLWsQmeFTKjCOtcrJiklHKw6QzYDIBuFnk0HfmW248iLS"
    b"qWnORSSg/2J6tULLoySfbh+uHv51dX91OZsQmzfj5MmOZMWeFQ2iW5f0h0AIjG6z4Eag9GSLwU4F"
    b"VxtuvSRrzOCEhfqQnP3zNfoY5LrEhDt7+7a3Ec8pEIbAuUcHkQZsZYh7MZsEwAF/IwVoD9/IJvVf"
    b"CNU6jVG+Y3VLHqZXKxVpG04ppRCg5okzrcf0bANkpC6VBPSkHUu3dAZ4zYbNnhN589Y5HQy/1t7j"
    b"CaNSi0b3OwkT0vK8ArH4SbMb3J9Nws5xEFCiQ+kk2nKjnoW8UuI0nAFndmNAXrln8e6J/DQiWd3p"
    b"9bp6GeKdLFxrMKIV615Pwxe6IXnV44vQL5Ca2QajkjtMK+Lbh49yZMhi0qHP1O4UpTFH/zqJD9Vh"
    b"OWBFBsv4hsuKxGJ8RbWEcrxLBhviB3GNs3H6dvnUfXKLYRnn1lNWldPF0lcJTCE0SInpOn2K36pn"
    b"CptxfJLyM+EWS92aAm2PrzMhvBWsX0o7niHhscIli5uPywckFouR+WI8L80Yzy/9Tbx7qnT1WEAT"
    b"1nrExefz64fr259OyyXXildkKN/p7AiQmu6A9vHDh5vr26uTaJfSoIdCmx8hhcbfQ11f3pzGOcf6"
    b"VHMnC2Zxuhpryfu945Z7iZi/cNViL1keYNd+4/8Exo/qKWEWM/SrRnsSHo1/aMJCo2eSxWsMYL+3"
    b"YJOoAXVElaxlR0Q9hoVlG3deKrw+ckhw7A6+Skf6Rb0kpFD61QwNZTqNGor/GJXsoSh80Zis/77H"
    b"6i2O9BNKO38AkXWFB9N0TQPwf3OckfHbjypK6wawJzOln0bVj7gU1R/q3bMJj7CbJ/2OVpwoMvxU"
    b"hG0e130HzGJLjfzTd+HIww2XlHwDeFjuTRpZBqtmvosDQxBbJHE53YucQBCHGOtOi4tQPG8FzT5Z"
    b"wBqICuHs9QgG5zwcYbYaRcWXFa+qnBePbFuSBYek/Qz5UtNUi/WUamtFHyJjV7woGXzDu4la+wkh"
    b"2AqbPDaitMWjuBJI0GDC2q4Ar2iMqKXCkcDGxhw3nE7RAsPLnWppiwtPwca5dtDK+pDuYHHmoovO"
    b"fmSPYzumjSP8TRzhb/YjvBMkpBXzzKfCHI/0jDR/7h3p4BvVA48QWqinHPESDWrMDwX23Ng5t2i2"
    b"HyhZuNCq2qEIPc8I6ND0ITs6Sz1v/xB6XspDux/3Kc0Sf4nrZwgdKX8Eu4lhv5o0TAujcB8H2F6h"
    b"PrQ8V3Y7mP5Dlw3vMLMsxljn00Bz4I2jvojxnpxBvQWnE7w7OtQYlUyoWlVVUULxOE8wC60X/dBT"
    b"R8wpa7r5dyedsui1JxzEP8iRkTX/3hw2qo2jKeqwEN3SJbgbB3AiM2bHQBVm19BV4an0UAHxNQes"
    b"Y7BakQpb6UosyGx5c56x//ibB5E5qKCmUZlGOgwehROpHxSWD59uU4p+KmT3DxcZO2c1whdSt3Sl"
    b"2/gLKI0huLyjeqWtnxKFFFRc6N8FvnAUAs8HbwdyIhZJbBE83L06f1q6MPbXyDB74Ql0UceSiw1a"
    b"4En+EmX3ZHal0e26ZJwhCaFSQcXuRhEYhL9AihrYJWweNN53+r8aePqoKfGx0/oL/AbvMNpMUGtQ"
    b"FsV0FJIne2qywKuvEdgajNtRA0RWOzRSfKHBONxSfV7NJuH2Pws/aZg1RXQw6ohJZHTq/36kr7Pp"
    b"D9mb1DTNWYbdIPuCESWog2MQBf7ngL4aclv6NkOIrBtGXwrRtUj/I2MzfQnHwX+PozyT7vfHJPzK"
    b"+xNc2Yap"
)).decode("utf-8")

HOST_CSS = zlib.decompress(base64.b64decode(  # generated from web/pages-v2/host/host.css
    b"eNqVVttu4zYQfc9XsAgKJAtTleSrrJcCBfq2L21/gBIpmxuKVEnKTrrYf+/woosvSdMXwyKHw5kz"
    b"Z+bwYa+Vsug7qpVQGpv6yFq2R5TolxI1SlrckJaLtz3qOW6VVKYjNVugP3//Ch/4D3boBdEL9JVJ"
    b"oRZotCjRj4cv4LZSr9jwf7g87OG/pkxjWHK7laJvYNASfeByj9IStVziM6f2uEfLPO3AqiL1y0Gr"
    b"XtI9ekxplmXbMkQK32zDaLN0rlrCpXf1OpzP0pV3MHgnvVUl6gilPpJ81fkYjoxARHCUctMJAlk2"
    b"gsEOEfwgMbesNXtUM2mZLtG33ljevOEaUIGlPfKJ4orZM2OyRAfSgefZtZCptaqFaHbxumwAGsJv"
    b"Gtqs6BRi3r2iFA2W+QgNtqrz8Px4SNgbq7Q6z7ysd2TTNLFUZ8YPRwhsl4K5YBbCxi5In3OS5awt"
    b"53hb9mqx1USaRmkIs+86pmtifPES01cLlEhl2ey6gpJtBZirE9ONUGd81i5rIt/OR6bDwXjERwSl"
    b"BzYlu1y7u2ETQFa9nSN+0BxQcL8Y8IY1ywBi0bcSsAdKQFWfPB0WKG/087CUb/xSBksR+gHlpCaa"
    b"OurNyZNtsirPy8hBMAa0jRKcosdlutws6bCFNaG8h6uz3LkbKZNtgvfHA2ldeiPR0p/LOfM2gXjE"
    b"dKy24Mxy5azQL6gop6QroeqXa367qvGWHBjWTEIo/t6OvzKHCfWXd7zDJ06Zggg6ZTh4h1o2YAP7"
    b"OlQ/dakE4sHfGJZP5hj54T+UI4aFWJI0gzwVdyzH7ATUhuylkqGaju1aCXPbJO431t/9xipsZ/z3"
    b"zA04Qr/3EJP0IyGUIL2BfHOJOACJstXNHMibXdZMc+B8hD6Fr14b9xkTCR2xR1wCL7mdAkiIsNfk"
    b"WBeb5aaZ2ZyJltdGlABNlpPRHuAglWCOasPlQH1MBPSFK8cE8Go9O9aoujdQRMPh8AKR6wXXlUSz"
    b"q3W4BPpGcAnttJy4OwyRuIdV0xg2VBiqVxF6YCPmI9BFUTiD26Exgr912GdzL4ngJ/Y+KNEI6CKB"
    b"+ODjxjQvCteBwyiBYT47B4G7BN6vTAKzWtjjnckxsm4yovx0y9dPze+BraMne2f6zbbppYQNlsum"
    b"KtbpPYTnZxOhzNx/s1tnq8I3ujkCB2DLz2gvR5MQuW0LDGnx3xfaFYdK7HiYk095mJtuSD1P7R/E"
    b"cIzaf/tuu2y02FhX1IlD9vEb9BmGkr3cEaPriD5Si5bInogrtQujPN4cVm7ndeRq3I+KPvjzAjqT"
    b"oExP4jfq8ubyjCAVE3cAHdKrC5rRorxQtu1Oz1XVz6wUrS8dDy19LRuaBS8Aj+U1EXflaWiBD2fl"
    b"7tOvpTAWk61T5P/9pvugkI8hVzeBIMr/IubyE8T0WIalT9Py15ZRTtDTTJC37qHwjL4/IBTfiZPC"
    b"RNIgND4EL15+XuEMlM4Gq+n18s5zBV4jznKKo9MM4DAg6LSvGQW0g2KH7xCVeyabGjRWwCw6khN3"
    b"9fI9+RNvO6UtkfbSKzzXnDNfWriVwLw9RWf+8bNAQWvg/XYpAHNi/UbkiZi/gJrB+b8ciALp"
)).decode("utf-8")

HOST_JS = zlib.decompress(base64.b64decode(  # generated from web/pages-v2/host/host.js
    b"eNrdfdlyG0mS4Du/ImnW1gC6QIiijlaDTZVRIlRitySySZZqemQcVBJIEtkEkajMBCW1hmbzEfMN"
    b"+wv7vp8yX7J+xOFxJABKVTO2O0eJiIzTw8PD3cOPjXa7k+w9T75stBZVllR1mY/q1u7GxqiYVXXy"
    b"4sfDNwfJXtIq5/Ot67zOtiZFVW/d7kAVrvF+cHJ6ePQO6uzoouOTo7Ojl0dvhu93ZPHZ4M3g7eDs"
    b"5O9D2+ah/vju6PTsZLh/fDw85PHS+bzOyq35NP1cbc2L6+ymmMlxT47eDIZvB6en+z/Av/v/Mnzx"
    b"97PBKY63/fiZqTR4fzj4aXAwPBm82f87fj26+Ec2qnuXZZb9M2t/2EiS1seq6j94MCpubhazvM6z"
    b"qjcrql5VjPJ02uraGvNFOZ9mZQYz6kFt+eliMbrOaigt09E0i7TlVtBvXfZgSaMs/DhObxZVLy9a"
    b"G+cdPX9c16uT/bcDs7qHO8+SPyQPt3ce6zo/HR6cvcYvT7d10evB4Q+vz7DssakG4D1898PwDcB5"
    b"+BZ7erK9bRqcHv148nIgPj4SH88G+ycHRz+9G/5wsg+V3vI0RIXX2Gz/x7PXw4PB/sGbw3exSmcn"
    b"++9Oj49OzvxKch5vBweH+14FnIqp8K+DkyPezGVjvdg/+IGgRfv7olhMx1nZ6iatl2k1SscZ/nk2"
    b"WcxU6Umazy6Kj7wlp1AbC9+mZTXBP94X01E6K/DPQVrWE9gfczyu0psMhhkXo8VNNqt7V1k9mGb4"
    b"54vPh+N2C7+3zG7ir5fFrM4+1dAIf2EDVdJu7YxhjC/pdD5J+8llOq2yO2gqGvXym/QqO70pinqS"
    b"z64Gs/Rimo2hK6qsR5nn8/f5OCuWzQvqbN1iJTs5KHqxqOtitqpdXVxdTTOn4Wmd1otqVcOKaglw"
    b"FKsHvCq2pvmtGC2bjVe3gkpeszKry8+rG1I1r+momK/REmtBw9m1bXiTzhbp9GWZpXW2ugOuvTWi"
    b"6kEna81Bd4FTKS4vAbm9bk4nabn+VCqsHe/o8GZelPXaPeVUfSudVR+5r43LxWxU59AYqHoBneSj"
    b"d8VHuIm+wBGETViUs+RqWlyk07NJXvXmWXlZlNDZKEt+//uk/jzPisuGCkBkPyZ7e3CF6DFa0GeS"
    b"fL+kfrtDVfrJAcCeC3Y37sQss0/pqP5r9rlq36bTRdZNruFvZ7YvimKapbM2dUSVYKb0Q82Wy2hi"
    b"Bd1BLV1hc78sgf7nFf3LI3T0R3VfXZuxO3C7lHW70/tHkc/arW6rQ51+6PWo0nnwGbrxVnNRIOkb"
    b"HwJRucpKvaSbfJbfLG7gj/QT/uEs793i5iIrYY6n6WXmNMSZqsU939Od2LI/7+n+onM4Q8qnJxAZ"
    b"10JttphOk3//96TdAFTkXGZXCNSE4XlZFjcaZNNsdlVPxGQiQPlcZ2+oml4XTgPIAf1rJjTLPiY4"
    b"6cFsVMD1AYDO6K/2X06P3vV4Evml3sVOz3a7C93cJaO0Hk2S9jAry6LsuH0fzi4BfPVnqulMrsqm"
    b"gAVF+QrW9KpMr/CEqdOiiHBapjdIgXF+P568Oc3ScjQ5ptL2tIBRoZveJK0mvWqaj7L2w04Hh8kv"
    b"kzaiDrdnNOuEOJRsIohzGAmPTPcWSjQ8YFt0R6oTIALt1q1utBPW5Snr3mDSsqEuhmaw262W7nzz"
    b"wb992N/613Trn9tbfxpunX95+LT79PHd7x706qyq27pZJxhN/dQVaNd5BhqqMIM4gDXRw5sL56ng"
    b"fZlf9al7ZBiusllWEnj7MFss0SP17QC0Evw2z7LSti2L4sb+qjMknYBx+yPuTn+4ycZ5epKl4+AL"
    b"4FuWii5u8wwobNUnNHibztsdLJ1lV0WdwxxnV94Xbo/XN8y2tYBzXU+Awx2buR7Ns5liRmjCyKli"
    b"2Us4vnU/2TaFfwM6D3gPQzR8yrNx8OWsqNOpU5DfOPDBsldpPl2UGUyyrLPxfu193p/NoNsRXTpi"
    b"plV+NYNhccUtXMg/KloTcHLjfAzLPQMCouB0CmhH0ODb6hi4hxBS4jI3H72GB3mF0spxmpcaFfjG"
    b"O8mw3GtzmZdVDah2k8lZF4tylJ1mvywyQqBtW/gazq7u9hKb7dd1dgMy0tir7n4Mmh2U6cdZrAl9"
    b"kNUNPnq1J0Bb6gsAhD/PyaIeF0HnF2WRjkdpVR9kVQ641QeiusicL16LaaogIzcbC08JEn7paz0f"
    b"/8OZOVB15JSdztJ5NSmin7IS5Lf8nzhZDxavQBRY+BMuAa8Bc/U5+pjmiCQtixrTz6d1MZ9jf3av"
    b"EaEJl0yRxjxTkPI2DubFaKLGqmG1COVjoFR5BcOpP3plVhXT26yN0CUMA37kNsPT4wwLXD9Mtv5M"
    b"9ESOjRcSLnfjTvJnsNnTevIeb7N2Pu4CXC+yaVcVf5ZXUMaM3xJ2MB/TnaMq9lCkIcmGGlHH8vMI"
    b"trB6k1dQkSSOdmsK4jOISJt6cPcC57v3NX9rExfocZcOZ0E0vefhD11ZxGko9gu72WqoC9yEK1R7"
    b"8+Fje//5aCxfORlTEWfiSPA0k7T6PBslZj5lNirK8UtJANvzEc+BLtj5CO8pxVmdzOdIyACifI0r"
    b"nlXfrrsOb8QIgC1hjSmiv2jf41swC4fepcbEgrQmvLetqrycfsI/5voPovKt814+G00X46xq4zgd"
    b"zTolCh4uYe+l4zHX4zHumnmvBw8SMzFYHAoquOi8SuDSvUKNTT4COj4GrM4q2II6gcOXwDXJ1zLc"
    b"8VWFvFXAs6WLuriB22JEUhcdt3azyKBWQcyF3m8u8+mn+9U5zvpT2wGNuQqZUSYlVEvVQLmIayEv"
    b"gsyz+hVe3MnzZNu06qt6mkegDx13avaGs+XyiNrqzknxehEsCs+fpPOQfxcS7tfDOgqqb94OuZBf"
    b"F0Sb3A3fGyFMqgZoRFHTbbqY44FA8lwW08qRNUpa295SmMbWF1mbvy5eQmJUQ71xXmkl1yaPCyRK"
    b"D2xREEstGnfsT33J7vLtGulVdALz2XQPw6a3dbbAditUS/Hphk2Mrs1pMM9HsDsgXR/zH6eLOVKj"
    b"bNzGBfHBDirp3cW5+d9QWgCGgCU9q8ZyBm1AhSSivXLaRY6bmiMvV0kicKL+mSXfqUIhiLgfHM6b"
    b"Pz3f88iYwq3vnZ/Q8tNQjQVEiQlUFJUZxxxEjt3JVj5l1ETZ0L/IZSVCaazkcx9USXJPLe5ni8vg"
    b"ZlMDfJ+0jv7agsm3+A5P8A43nyPd0EiiG54CdHM2OHs9OBkccGfEmpjOqFLQGYGrpdhX06XYRsnZ"
    b"Ah/2I/Cw5cu0yliGidViyknI39LHWeko4Iy9QS6PwLX8Zvre2/zIfSRusJ9/96Wx2l3ytx/33xy+"
    b"OhwcJP/nfydOTSPJ3iVHx4N3P4vrrW3+jkzBiLmiUtM8TF09kb/jtqw9E57Nz+tVZjWmVma6EHRu"
    b"ap5uC1u35KJdUoVVXh69ezd4eQZzJqw6evUK31xaHX3QPOTEUSxqmh3vepMQWGEI0DI9sqmk+zbK"
    b"K/NF83OmwJMvooRuw4DizeH7gQaF3P219h7ai72l56nk5OjHdwdbcAiPWxtyK9vihoF2P+0fInCT"
    b"V0cnYcMQ4grmcpnNclJ0yR3WLmrwM+VdQ4fvA56LNdT5lwfyyB0BKz4Z7B/83VnaruyieTlhd95a"
    b"iN1ZthSqYJdAPzvcrDfJx8C7Lb0SeZQxcH0jXB7qTd3LjpS+pEC9zKd1VjIawfAgKe095z963B6g"
    b"NCOpCGmk0k/bMazG7+vHsX1Eh+BpaHrsVFakzJbd8cNsQlv3s0deuCOXGnPZnX30TRQdGRz8HNIb"
    b"h1cIac7hwZtGgsMXGM3Uvb7E8rqSVXbGAuZMQJrlGxqiEYO4+dYICUCr4+I7DXNKF21kYdSvz1Vr"
    b"TGwUSzSQ2+upK1apLJ6Hj/mGb3MGadRBLNVDxLp3JcNGnl0yyshskyigiItWeb3Qope92TTrI1in"
    b"5L/+4z9B1J8jBww1SO3W81mieKWu6rdFGoKWRTn/NaY+tVJpewZI0AVEqqr0Sj0bRUTXBKsZ4qkr"
    b"NyIamdmoaj6i6bHsYb5Ix1dLKR8KzVtUqyVIGencKvWwAdhp9P8ArB/fGXayqx6pSGGo6HdXK36Q"
    b"irGaXRxb/oqD9tXVqvtwWpwMgjbF5SUwhJm4HbhcqycPBoBZB2ZSlVarwuYeHR9DOe4WrpAWG9Mx"
    b"Vh9wJ87pTUbeQNyArp93bNbRYrC2QExhjJuR5YZUQqjbX/7sozrLLpNVWOK30GRhf3Qnis+IqAoI"
    b"LSMPuyKMK97AZZCPD9JqclHAMdFabfmISdq94An7A9NO/TiI82QlH64FFXAT4PPxD4JCRUXFdTbO"
    b"WD0HROWz2gSY/s18mtX4bgRfgFViuxr8a4iCASn2WE82BE5qXmXjYYUwGVemi0k2up4X+Yy0gIpw"
    b"IkjP7YueMnMRJHMzeEbu6fV0k2fbhrZF6pm1dtFyallNAkQ3eWwrydfnnlk8K0ovWDlBsk904v5O"
    b"9Bi+sCEtoHMzBiJfMPBHjU9kreVAiNgPqE573KOZeORbrypugIYRxj9PNtl0SqAofOiY9voFKzYG"
    b"X6kIg9go6gVeQ9ntgVYrX/nVUWqo1Ny/VZQs618bJ8SniCvYjkOMNoMqPFt/e9Whwf0dpYurCau5"
    b"s2y27va6/fS4kwi0YmYdXqtusg3o/uSh3VG/d5zYffvGNmHPbh0LOqjUDDzdM1KXiNlHDNOprrVC"
    b"4d/C4uMpjhYB8GVRJm3NbqN1S2KONA8Po3441zyIt7UKLNxQsw0fWrN8dI0nhrZ4no3yrBrmdKCn"
    b"2W1GdoWTOf4X1Vbw1zmzGOHkxP57NImH7OmRusnOY8HCbervdvTIbgb7GTSCvYSenzzpxPqmtTi7"
    b"E++O6lFPD7e3oz1N5mt0M5kTcj198uRRfD4MzHuskxvQzIJexdQE75u4Q8W4YtvuuVtbs8D+Ht81"
    b"Ugy6QZFg3BRsrDpPF3BnrqATH1ppzriFcrJo1kXTjmvg2meS+ZBj9XCg+PWmKnBXa15xtiVd/wZc"
    b"yw+T18qeqgnIF8R/3OSzRc2siGEfkhZZL1TqVCGU7nWoPJKmR+/RoIR4eAwE1q1op+ZILZ/86R4N"
    b"1Yru35DXH7YLtlFNEIEUbOQyBHUuigY+bt07o6E5zf7Rw6c7O4+3kVasQC3LLd4Lt2wzi1wIExDX"
    b"bogsX+czptaCKQZByzCr66GWyx6aMXtmKIa+tlj02J1YA32dPU8ePxOIYawyX6HdYNYm81W4vKqs"
    b"3dyXQ0I/GPIlyMZNPoWqxYxIj9GG0alTJj5GUk5YuLnNys/8aF9clbDDJEygKKmFooDuiJkh0CPo"
    b"LjhwUTnK3lvsFDXFvq1zNSxrH8HOpvOiypRGziPsSqwhVlAz+KN0no5ykKXOjZIkOjOtS6KGNKFn"
    b"azZQA3htIr0itxRvGz4tk9R5iLZqJWx+1a74XyFwurya+Y56Hv5bMtw7ITT1A9tiRvaZ1OTD9rn9"
    b"RNXtp4fnuw3v/XYbsDeE/qKcVgLgWNzDMm1KvJj1qWzauyqKqykJef2Hf3q0vWOsAWynOCBtaZnR"
    b"6z8fIhoC/4X5EUtoh3Mhg81pcPPdlGgI4ax2gq8ADJ4vlvQX1dZ2j76xuSNN+dHjPz5rhQ0fyobZ"
    b"Yr2Gah3cUplUOjXs+mWdeasBeY7pLQh/V0uUFRZXmeSQauUyJ7XKOLtY0B/aeGie0rNTC5/NFZOw"
    b"KDOi2hGa7RxVxnvsiCe/LaDRcs8M9k6VHj9+5H1J1Wa1HnhteCb0De3z3I+0Dvq2HWKXVjLgohHL"
    b"cnPmBEb5p1E26tkWnYatOKlHL6mu3IjlJ0krke4zn9UTeYcvwOFUpllt7Batu5O0QBPmZnT/HS8u"
    b"pvkIZnoG8uesbXd3OKcvw+vss7Y/sx2LXhhFy/wWrtS/fLx2euDS4T8+XnesAOC3RT1/Op1epCPd"
    b"mC/Y4UiVdpY4BMQWe9ewJ6aui3DLLJkUtpZFXYyK6RB3BLcAa0rfTVXbN7zf2TFW99wR6u9R0CQr"
    b"905Ts8ePYs1gH8J26dYlNDr/8sgfieB/CavKStgFuLHuOaTaAgbjsEbc8LpweDe3+jy9CnxNBDjD"
    b"ykIJ8eThTpz6K1Dg+/LQuQT8D/Iu8Nxa9aemlhmyZ+YlCYq6CbBc2Sdy/IWfsT4/UI1z9/UmRix6"
    b"ZT0aMqVpOtV/QTcSVcXzquGbnOagXVdUTXI+wfl3Av4aCg3yMis9qet51ResNFYxN5ZTOk+r6mNR"
    b"jt3SivxlGvi6tZxssJfQv4bnrVYUPZPWkNW5j+iuW8Mxhz3d5t2rbNaFSl0gb108WN3bllRO+K45"
    b"2Ew9VYoT32lqgj2qVmot+sw3NICpROrjYW9oAPN3G1i/mqYmsFS3iUffm9pdziPNBFFxDS3uNiJ7"
    b"s/bOYN/d2+5HJPJiQ5Zsh5qUT5w78cbE+TirQbbF2RhZnefh1KeiITL6F/mUWX396LnUWU3cS8GB"
    b"h/upBtxO5/ISV0+O2VU6+owshHLPBgnSmNQOx2xTS69OprBSzhZUusinY6P0GZboK6tekCzC4Hfj"
    b"RgZ/a0piFK/ZdFoM0TPPPD9hsbBO1DWN24euzcX6earLTC6peLkf+lkwV6sEYmcbSedvOjWF3Njf"
    b"Cnr+2hXmigDT3x5y/nEwZYLv0S29E7cc8A73YwHv35qisrynf/3NUzsW2SF7d9IvJnXmT1qospw0"
    b"dx+JG5q+x3fZ3U0+CLCVAU9tj0jH2/xYbYMVxphkU3WNJsH0dYXoY7wUfa22evtCxCGKwcFAnI/W"
    b"iXPPOlE2sWMPn3Yf7jzzWDJB511OjD8HYKSRwlAiMfYtOB1Mk7XWs0F74r49BmdJa7629R9KCYeh"
    b"Ok73Xw2Gh+/OBj8MTgLOaaE0tXT0aCYPt30O0kFvqtPmjf++Kd5JH1nL5YoggfT05PFsdXVxmrrJ"
    b"Dr6Qd8KpeueLReLtPz31bZdoBcI+rEHSazC+ffBvGHqmWSTQ952LPLqti4CPdiII6FPdaE9LJKaH"
    b"Qc2IbqMnL4aOb7Dr8NfELbtBAELf9D8zqBsY7sHsNpsW80zTiHn6eQp4/FcTtGClkqX5MhV3CjFB"
    b"pud1tCwxE7eADBApoYohDxijOux4o4uWobY5w3gMGs5tRIjh+aJHBhqEOi4E9zE5VXQ/n10va4B3"
    b"pgkkkvjGqag8wmKs0JuU2aWxpfekJlPJtYBqrGsd3ZcHcuGgIDaUi7Kkpd+aQ+RfEeNIuDH3jbk3"
    b"AUK5ytJjfJrAsSLDffbsTkrcwy1gi+e9ltaAWNFRCIRrOG8lyaZ0SUwvs1dF+beyHQWIPpb1pCw+"
    b"krQ3QA6YN4cnnn0aZdm4Sv52khgNvpIYsP7fTvJiUbW1aKd8WvtL4Eq2glu/gEDYlTdQP75lug7a"
    b"3PSTnR1zG9Gbez9pvTVPNMhtXREo0TV5khu+j0wgMvPpYopsGcs8y/h/5XKGRWgj90u5tZilt2k+"
    b"Rd+gVigRXMSEAY00hhgA0d2Myg6e2PGluNZOy2iRWGE0BM8/qJVOyVZxy4w8B8YY7eqq0SS7SVt3"
    b"Gpmchn5sMB5+dyOCXkt1bN+bv2zoAduLpHMB6bPVRHAMl+TZKoEj4l4T2xNpox3YI400kbStPB92"
    b"tJFfOZLrCBlCbNNCzDZy/YhQz8aOKK11bLKn+U2+1CY74IaWm3orv4c5kwzoWBPhqL+otx7/yqA1"
    b"umbDGzEuUzOq32sXKmkO2l3WxBqjnikj3l7yk6Cu6LFM7piJVk+POe5DzxqutoyFNfo/Z3iB9pJT"
    b"4uqTH4rkTX6bJdDVCTJ9SV3AAawWqoOOuOvpjFKQh0QxSn0dJrCbkDjRZ1nizr1nxxlG0nmRVtnT"
    b"xz6xCKP+xN7QlQmoUrsC2xr98Dx5m9aT3ijLp20/wt6D5FEn+UPyOPkO/l/byEk+8rsH59/tfdnu"
    b"enyoY7GgQ8/4es4yRYfDtC4uBHXh9cEnMT13UkG/xuyb+W7WR4Ko/ox1yrYvNQCZutEjCip1ocH2"
    b"rvrzz4mtrMu+A57WaiVpDKUNhpZYfQQ4/RJ2ah/D7qAeOaIpo2artUh6Re6VMZ9dHQAdmFXEQFNX"
    b"HiZQmd3oR4/0XvF0t8/ZjPPTsz+RXRkVPtSFT7bd2jv6w+PM1n5kCv/o1n6sP2yPbe0npjB1az/V"
    b"Hx6mtvYfm2o/tFORE7dzeebVN5N5/FjUN7N5shNDS0YeJIIKdw7SOn0PPxnUIPFjzLeuAjL+9+jy"
    b"EqiXLHlj8Uuf+o/5uJ70qV8kpoiQj3baIDpiuJD8alIH33a2Ox4JmGSfDvIrPFVi19UAo/LzvC56"
    b"1eKinma9MVdrnb7e39p58rSlJgf0f5LN2vw12Xu+odW13hnhCp1zheVwLSiGA99ElOqhUBcHLAEE"
    b"nTFFIGqDNNzabnW0DKcUviLMWhh2IwO6SU7wUaK2GRXZPrTgEAwviBay5U2Kqzz3zGv1ZY0CoXK5"
    b"j8YGkqRMi9IiepbqjMZQ8q9EnBjTZQTBraLckozV0mnsefNuaoBxiGxlmteuCEDwD3KdQ3JEs+EA"
    b"tp5Q4AHIiooNUzOCguqT75fFHG6wDC5CbSTnhh1x3J98X/JkKxI7dQtj3souNCf9M81r63dfePy7"
    b"n9VL0jaZOuk2vidIQHjDvWJ2VzgLqVsjvG57Fucch0dNiqERN/7976M02mggRRPAJvurRzSCQMth"
    b"a92vTCboM4ew9W4LvfFtPBwt4/2JNxufZ/fS1URAhaTxacvq28mOhy97dkBriGjQa3MFejX2LDDM"
    b"6V9N3vpT8CnoLJsbAuIir4GWuYDgMgMIjjF6iMFkX9CXNhLHF1NgSz4QaM67yRfkteCUU8jZBwju"
    b"u869IMbY9avADJsq1o9X0htNiyrzonx2nI/6bKwFbwupe0Tb9auPgTUimLZ5HmRvB/9HiN7VCL3M"
    b"6OPXXCbOxgX+13Ut9seJHLeKkptochEqHsSGsXotS1VVALhogI4o7Q2aCtHdCau3ZOo21F5k2lZn"
    b"QdvGYRKqn3IgxPyotgVsga8eaa108W2K+LM0soYXAEiFr5FFKoSNLDJxHdYKaLQZFf6JLaCOrDdu"
    b"1EUxJg1WJmyeuwEeE6hYJhO+715sU6UcINdglYIAh4ZLWuZT2dMjdCQv7qrnn4dBarzXkq9mr3To"
    b"Uh2hEJAsFnrWznJ3Zbwbi9he1MTAuF5FxJ6ksysaWUzDEvNIGEUptOoQwXumn+/RP2g76SePKYa7"
    b"poW+m7mc2J91N4H5TBSY9Np9J2LBmRMf4kAzdQhCR9q6qiBWV+5U5UAkvrQ93CdyUKNQk/YUUGDH"
    b"X+NgmYgA9zlYWoGvKNKQJk+SCdHMIXEh9qd5JqJ2q89iEFTUd8j1XnLcUeiibXrQsa6O2gQu2ocx"
    b"wE2czxO6DJDytqSX2Ib7Muj39dya8no2jaHUJcYxopd8HNTT/2D1oV19D5AV9FWZjtn0g9zhPSdz"
    b"ZaUnt+1bhbtws5oPjafTjczGPQoyXEWMWCGPyyDbH42yee2yZN5NG8bXa9quKKOwvM1eM3MUa2gQ"
    b"KcYliWgXy1kWdxK7QQuXd7Ejy5qNjJOA/a4IOygArfm0u3Vg/d/OnHgWsBLJ/LBk9+RhODbFtY1d"
    b"nDTS3K6A3DBVoOt7oHQq2Z48eH/fgHr9KJKwlO8YA9A7h2FfxNt/w4XWoCqs7H1HvAa7mDVedMyj"
    b"qzbal8hEGRlxFPAwQo4KKaJeU/uNcf60NkMHzjV3r/dmTxE1itmLdHQ9R6e0BeBP25Y74fMRRffU"
    b"DSLq4G1gfynF6ClG80FSvS1UUvXItndCowSdAIqlL4HzmWXG0Cr+VQ2XjfdvVLwxO6paO71jAGja"
    b"uIAuzmId3jP5AyZlciPazMaW0cDODsdObGcOLeVtGpqUqrpRXPHRz3VX5j715Waa6QAO+uWcY1kV"
    b"47jjEYbE5CoChsC2kDFZEw74DTreTds0tvKQFGObC151qTaOyAzfeBw8GSbUkr6HClHcVu5201bD"
    b"bgZxCJfv64YfCVBGbF4tO0SkhkZun2dv5vBa3TJEX3QjtEHkepcFkCqDY3JWFBDJV5x6nZ/Cb2L7"
    b"UVLQN2WsY3FHJWKMO0fMaYjmjld6IxPpQ1HFYDJk7dYjWL6tWNe8YPaFcah60w2sHL3Ogu/+FbR8"
    b"Xd8lD1UDtb2ahCJIhPRqwlKtpiHxQODYn39qfDeH2yIf+/PlvBY9JEN6EqiCTEsgMf2Eacxdp0dq"
    b"M3voOHMdKaveE6nR1Miz4E8y4A6jc1Mn2k7OPZE0H4v1b3lmBkxu/14XlhzJVa2ORx5ZTojMKB1a"
    b"2u3PT0h1a+sLxFN0Y4ob24nMa4NO6dt/emphGFhNmW02h6YuimSKu9uKPWG4UnJEVvfRe4/fVCIE"
    b"KZC543QlJmg0UBclasjb0xfUqY2uynARwWY+8K52eYBzjDrjXKtSHUw9dVYTuuj9Hb6rs3r4pUFN"
    b"welo2c930FLuS/JqtTvtI/kXKxX3l0ZtDgxp+5pCCSLJsxWhBniG6ufdeqH94TSpcP7pop4UZQ7T"
    b"yG+zXqD5F2sR6u/mns8wA0A6xTRicKgEt4dDsQEa/FlM0dCmF3eT+Qm7fo0G31/hdwt8MrkZAKwo"
    b"YprrfYs+/ELYbAK7a2pP+RuQLLruSm44i3S+xAcSvgqnR8xV6X8OJxXYXy8zeg6uJWEvHzHcRQgu"
    b"5u+sNXtbH764HODyuTJcucfrsgG14mADkk/skRzBZXYUDcJcRx2aY4l5j4CEOF+sWkTOY5xhrDk7"
    b"FXe5wdVxXx7erktO2m3iT8G59jGc6lnjysRnDxhlOqvQsb65rVfFG7eB3bDnWxN0VD0Ag35T3GZs"
    b"jad6YAPcCNehL3mfENyJcDPUA+bbwSDr9iLEwdWw85EhK419MSlbl1mRvWuGZeUQ952SUBZwcH5h"
    b"AJHVbzkiM5l7W7asxcWSJipTQs4mkKTJJchik4RSS+7CT0TQBZJRKsEkXZhn5QLzsWDUKWOh6JB8"
    b"wXQ5oEin94RDhPI3tLtbppVfFqOT1UBoZhW9fH0NvICcG5JLTJVUFjEbyLCqNmaRCTHtu30jS4CU"
    b"7csdBQ+z9t2dmGRllSiHyF96s4zoZSVFm6SVoVbRFBKNFYJ0Es8jF4SotN6y11+wpqhfZGPkkGzC"
    b"reSqzLJa/K5thru7OIWvDEVWLKKUxRE/EcQ6aTdLDOvccrvLpAv9smgxpt2iqsBa8JidSA2Okrys"
    b"Bik+us5srRTecL1a3YJ827vndskN09IFn3beH4d7FrcuyQu1vnjkvO8H51VTJrZlq+ZxjBDUpaTc"
    b"vCMxcKJyEMBp7BR9oVshm2DQm4TJGHzEVaaAZJwyAk6185tAJZ/RaFsEndVbqZbr7OV9pmNR0YkK"
    b"H6Minmy2aiG+S1BsDfiQhZfVbsCoYKlh1HD2dKmZdcjg4t3kiwhAWaeIIf3ky0plVFKCdNHnIKVQ"
    b"EY7xnS9XxSWfVSvnUPyXlHWwtQrZcFm/dsfehgpiqsdBjsrNCurKf12xDV0nyYFJ2iDyJjLkNVtr"
    b"k0k6aj2ZVtP5wPqHfrKlc/8K1ywh7PO704bcHwdhfDl89f4bGRsfxFbu+b3oCHFg8gZp1NPpS0k3"
    b"0BfKygacOWZ8k9d8/pfKNImpKeSPpYSe79pFWUqnycbelZJEVcfHHv6zx+cYRcGUg8hu8kpJh9II"
    b"0juMo6yvAQEcjJ6FE3nJqnUAky6Rc6dzZeLP62DiOjy7MAvQjTsdZwt/w9XrD1JGtNTLkfgiVXdt"
    b"zeBjsidcY2QV79g6N4XRRccSY+oOOCem9Een/UAIvHQYZSo2zCbFQAjKhKRhPcDNwu6c492o0Vsi"
    b"gcQesO+CLKmwzrQcH+fHMr9ck+LJeMf5ueW0OayrI5rn8/f5OCtAwP5lkVX1sdfKMziNZCxML9My"
    b"X3Ny/qAfs4vrvFYtq2OQMWHm5Fj51gjRZmw98zVbt1sKAlv5bEv9GUQN8/vK6hWTCAGwLAmgmy02"
    b"to0YXDMCweVD6DSBjXBuN4wGKN6MHzobMKxXg8U+sEa32UYscsEYh2FsO1aDUybDFLoNleARwGfG"
    b"rsoR+wMLy0aVmqYhVGldpqPrKnErI8GkDs/oq2NVol6BxaHRz8YdZEJNYAnumBM10N9I8OkP+dJs"
    b"85JE8x8CsJ3IBSnterLXiA5uokovmRrVUamiWoNPeZ3oE57P9J8tlSiqFflkdI1L8F3fDjCJ00hE"
    b"gVi/qHxH1VGle0kuPif1BEovyuJjBZw0O6hbJRuv5CuH4sZBnw1I95WD0BY7YyztRttpRjq7gIvu"
    b"JoNpa2k5SS/rjF2DRynIXlWiDgKbttuoC2HeqtDRjdO1WTSLbq+hNbF8pQZOsadldl0xZwXjmbdd"
    b"OS5CojoOX9SYH1V1bohZBgjtX11tc1HTHnjTabjv2uETdIz02WmuvkEsL9II2+9RkiaPcQpBEBLK"
    b"WIQ7QSWWPHzdB3dHxWI6TpQmlzUKveQMNjS9SvNZLxIqIq3rdDTBOWhK+2UjiZHkPYWoXh4PJo70"
    b"oKpprya7VmuOZDMdjwe3MHPMM4jRF0D0mLEJrQGDl1sQ8e2CSG8MBwm7dA1Abc0PqCI2XAi8bdzP"
    b"Wgi5E9pktR2RNy33nGnJN35Lr+DkIje1x9csPRgRlsYxPcA2MqLMssNFqiysb2GIPxvgZz+5sHON"
    b"U5ewGl/LaMjcdPSQsMax1Udy6eNCFNW1aLMEJUCUDDVe3/iw+d/1akkqPxaET4DpNDGrxBrWexI3"
    b"yfs+zUHs49QgbhjDSKBDN3jhrKDIVrqneVkUlxz3b5rp+H8cBAvIRemFw2rxy6H7Kq/dHyJP85FQ"
    b"y/5DPIY+o7E9y2Yo4goslgefi5vwnd2L2PoVYbdk4OWg+yA0s9PUD80abx7GbtWm1QhuplD8yOTC"
    b"i+DOUYznc7hhgKiXBUWYg6bTS7++4/HxcO0w14QcXnQ4k4HjNL3MXBcVhYbe1qtS5O/JePdyWhQl"
    b"J+6YkenjA2XiGG3151Wtvkuebi81oIiHEWwKXoC7grHsXsPNUk3S66ydzYvRRJ/OLqkputqvyN5H"
    b"VEsITim79g6oGF8VrBuAIaS+1RjF4lcN+QG51WlwPfgVks1vNJjYauv1b394jC9QvxQgmz+a6DXq"
    b"OAcE1rFx3FYFMhsxPZVQIARVF25O/TcZk++Gvl2C2FJzS2y1NTYPJ0PaY2S2z9zwGKliO6QtGH6a"
    b"59OJL5hhSU8PCZFW469sI8n91pjjvdxuiAcBthxR6UYJzTmcW0EWtrQwpgHKZpf1/UKLvBGYpUYu"
    b"ZX25vD46PRvu/3j2engw2D/ALKTDt6fGavsr3oaBPszhj8xgi4x3l1/NXsPyztCGZlTm8zr0Rw6S"
    b"G/BMjXWzuK4cW2ZzR6kUr/ywxCk5VElx04/eRfzdXjf94ALiGuJa6S+/dbi+d5n0l141XaNvxe1s"
    b"uEDUih3TIBWOi5B62IQlNJj6KDYE9mFc3HByCoyQo1gaovL9lTT+0bZv//3QSHJrn6R7PsI34fPu"
    b"/c8goye9VGmk9XjCm2KW10V5QOp7vIA8rBecLXPFnklE+LLbsDb59KEePqxaf08YSpnSU+2yqBvk"
    b"ZOtrasLPl7HK0eTvOO3gDY85O/uCYx1HcsWzrPqon3s2hJRvWXhvDq6O5FvM8YQthfPRe55pfHTR"
    b"MOz4D8U+bNQrsOvjoxZPtij0yQBEPxqvfs70TPmbgu3cWftw2PFQmWAnRUjIzjBGudBZ0RrmvUYH"
    b"/GdgaIYvnUS46NQobg1jVGXjE0wL4chVhi9YQStkQAqULbCi7TOQ+KEmyieiCh4/nFDV7ijz93Px"
    b"is0NVhvtxWywUMwub3VAzbXEW2ZxZEO1QlHEZpciqGOsjoUa/RXAYTEDLof5t7VBodvcGxpLyPM6"
    b"3HIzU7zEDdNX9IyyqrrPYrnF1238fLTOSKyEHoXuW/fhAJmBEYdIx23JUsPYKHMcViuNuhurjEbo"
    b"8ZoU3k5xg8XIKnuRmLVIV+s7BSVewa66JFFzqmcn++9Oj49OzkJOVazl6/t/Ozg43F/FBccMeiwH"
    b"vIpfkM6PlA9SYg5QYGUJHrOsivF8wtJqw/i7BPxxjBdeh9u9P797T47X3mMEGJDnbvIKiP502ibw"
    b"dBylapMZTqOFwldZSJNg+tYcim/XAi5V/Vn93a+vs2NDNTdM03+vsu2b1WXhO7pSKYQbNOLoZ74z"
    b"vbYDx2/K/52CpPG33fs7pUR8xoV/ROSi3lyOUZ5ntHBP0RGrtaXQ1zq3+IWBJj9+EPjbCQbAVxWY"
    b"zYixZpKzMxWsasTCTVRbxc0Z6K7NEkaDYHvw5agto+uspkAQd7qstOs05fbN17YIEBVQhGB0ylVs"
    b"HDzZn3pCamysK/oPWGzXsKJZu2PiZvO8m+Lle8tOoou2jI0JHT728zXYtEQivA6WnRU1Jl0VTXVI"
    b"Z7fe0TybvaTgAk7dy3xa67AVlIrvuZ70B/h5judX/vaNTlD30IkP+DfgKfPLz4Ab6w0rIGOG9st6"
    b"v5hOTT7VVTPIs/GvPoFc5RNqHH9OSWAyK5fEJvRcRhFZHaCtoYtOY04MtucwplXLo+qo9Lokeuoo"
    b"U+5vttAVZqRymFMdW8qJkxuJek8XNJkqiTziNjOIJSgG0r2EKHmSzsaWGYaduUnzmeKze1GzBgG2"
    b"V2k+RQsjtG3Jxvu1o5bwQLw/Ax5mNqKXcT/mb1DBjQm6JKUAXttbygc+mqmgERAqyToCYvApryhQ"
    b"El0tCgaVAUKDi5y3vhAWXqS/lZDjGHVSS2PSPdmwffHWz/eSfx2cHHGmUcn4i2QtDaCOBmGObYi0"
    b"8/0N9uNiigRxvJssAMLK35FSPSQ6X4QbbFBkCzr92hw7trG5WmyRb6Cn50yTUoZVNkWEWJJ2AOG0"
    b"NnmVvDl8P5A5IbyMPcrCDk/vrrvyCd9oUKHKMOlknfkGZHGOh4zN6IZF/oPZHZ+B8e9iz9kxuKqR"
    b"nznRzI0w+l3RTF0tdMtXK9sqZb6K8UPmGq34yxfxRFsqINlW4K8WjYYiyJNS0RjuNKjA6OUwg40g"
    b"aYtnnSRJ5/PDcT95d3R6djLcPz4eHh50TeJQzpQbe7sx7yZcDZDBc4mhM8n53frCyh+Zlz7F42/g"
    b"bM5luIfxYjZOZyNfnA2SIts2H9NydjQ7EWRHzUsb2RsPnDIfXU+zQ3w8sdqSBENo6Vm7Y5pMjxui"
    b"n+ZHLb3kYua8n/eTNqwdBLCKZOvG93Vdycj3uoISOd4CFPE1yOR9KmaYN47QrZ+MsxoWX0m/ECuc"
    b"kYavUVeqmvY8Hw9l4qYaY/h3pSlUwonWgUqPjohSsrH3uw03yJWJn4w1t8zqt8yDsec1se7Dl54f"
    b"vUEIHRD67mftTsya7J6PW0KwkmLVsmMu5nEDi+TyNj2smspbtzuSVkRowZJehEpiRT+9YvbWBLYK"
    b"hH5sJ4Zh3Ea8S4ymAeC29htEtLs3uBNOf+u8P95DmyAkeh1ZR0Vu8BxJl3pKw2iKOR3px4flt4nl"
    b"5N121tLRKW8weRTYG6nu+bHZw7AXF+NRsBPo6ugB5En2ziTR3y1n/JY9yg0KDIkBUZ+nu7hMu5zy"
    b"e9JehFFtih7Pg1hXQDTeKm/TqXJ5IUCusxQmwEiLNQ2KSTyOWMUlLNCM0rlj6L+bCPE2m1HOGxDQ"
    b"hCRgkiJWNvHWejAHpgt1LpweGM/aKZmCKP2vYScMY4aZPd+Yyn+phMGxQtnjTOkZJY4qPa1WK5dZ"
    b"VUy10RK2bRjfNGz4ziqjxqkDdVa/2m01ZFfZF8lYCcyHU2PJgnNKDMWFAwdOFbSbMf9Cm1zE/t6D"
    b"WyD5RfmAHYi3HvaewP8q3q53k896KuGfaVjMEJJEUGle3kd9rhjneMptcduodM60B6cJcFuwh/pJ"
    b"W83QrAN48HEPEx7Oxi8n+XTc5lFESIFVQHbMMIi9RwKPWWIc9yHSl3DisZM3DVk0CTPLaY8jH6tc"
    b"CGp8LDcJlnyBwIssY8ISflkjX58WmzyBSPUR2tKXPNRBXpE5P4pvhurcyE/I7dsDQPUM/QwqEvsx"
    b"pxZ+GKWwrgbNqqVRdByRiNDcVms13EKAQGsVPUKNyTVIgFOeXl7v7itAnZcZA+wI+0Tihqvsbujo"
    b"bPjXF5VcRAWnJyir9arCO9J7brivBi5j6j5I0x2O4LSPujoeke+MF2uu7c91D5p7XVSOU7DgcaOG"
    b"7u432VHtafjJagWh4PkJqOr3jNekm62O2HRnxrYw7zThuQGmDv3nHzxVvhv1ADNHOYYn+AAl8WQu"
    b"o0cZPTcIAzMC25qYL3wt8V1p716IL6LosK/bus1/USPTA5Y+PXpLUCeieubV2PMTxUj33JuNhZ+r"
    b"TiPfuDPgVK/ImZxTT7s6CqlKrrM1VvhLuYU1FXQILnZIfcZ6v5Ro3u6fEC7VCL4s6zF37OU1lhB0"
    b"0xk/+k3SGScEk7izJKnp4RJmmJLDKIci4yTVeT0BATtTtp49iv2orex0HmtWi8FZmI0o5GPosNk8"
    b"vNMfdAB/YrBqExBNJ5vGrWXrIxCRRObpntLAwQpGxfwz53oFSkRz203yunF+EZt/ZoX48CKa+m5m"
    b"mwJJtTt1NG7Xb2eNHw1r3fxMak8WB6BTR2ucVzqll0k/5RHA1g8p5tLFe8nsDyvak8OXA8RrNl+s"
    b"/us//pekMOwYzFKA5xCuXz4JzNDx8UhcG37CWHspBibdcpuYxlqleJNh0mpb7CQJrUd8hd9vZ8Fy"
    b"TCYqf13PYls1YXv1v3y87q9jzc7xO5CGBPkFEJBD/bXrRLchO+14A64wrLGG2+gY2M2lbeYY5Vo1"
    b"+YfisfsBz911FInWtLhPFnCOgk9i1Hy064nv4gQg/qTjcduY2gbRR2ItFBNlhxHqFDejJSOtsUxe"
    b"x5TAe7DEys4hMtU240+Y3sPQV7JbSYzVag50xKwIM4f3DygU4XAFOxANr0NShQGvw8b6YXyivLq3"
    b"RsW5i1tId85zM9cP+iVE4nfOsuDRtWtzUmx3rZZY+a/9gTN9bSXWrUGLsD4nrcAa4qO5KjyAmdGM"
    b"KUgTE6oj7ETjl7acNy0GAIdgUEV4uZp7VS8sBwEEL2UQ/xeYiQHfqeF2QM93kjHQAaQn7PENArqm"
    b"It6Ufn5pXOhHGvRyZ/rJ774oEVofNdIlgFzKKQp1vHWMUYwFPAGbWPYhZmD+Wc0IiDLm0pGBv+1R"
    b"vw9JWDdiBHFbcoPuJw82yei+iIirX4t7XhZ4wmvZ/rIopy4Pe9eAVzGEUvEVAWsQmypUGt+oCtUk"
    b"y+peawmWkFrX3ecZZdHExexfFGVNiqNWc6jeFg8FCDqCDcSDjVwj4iwwlcqowjxR9lpx54iGTlkz"
    b"pbqEOeIDeS35WxgCwdWTof/vImqniOme0cCsGSMdG6wTJP2brDpZY6TUPU2OtPkN2mAzvPZnFTCx"
    b"77FxG8WBrkr7RM9dcKNlrUDPSuKuF+w32SSBFH7f2PAWwaYcY4fuBig3zJSmkVDarp4b5jaeEw7v"
    b"7M8tz1otn80X60jiPJoQxSlpM+UIHntZm7mQH1Q0t8uFDDmTmlCuf32iqghmnEB21oGDGt8HhVId"
    b"qvn3dDUj3H+Tnst67DEkTzKkdxwbGes3IsDZJK31Xk9ICiTbDRAzF1bAxPA9KPQi07wWLrBC5i5M"
    b"rXPfSKrBfPnJzfpFw6xQlN3lCaqFaHGWjxVKs2vM2QRlNdNm2B9SJ81CoX8VCLTkuN7yWGsmo5v4"
    b"2JnE9o+4cMvthUwbczYtoF6sVVXLunPePY3F9c+8ov7vvmC7u59jj6NeGFQVVd5Yc4z6ggc2QhMz"
    b"0H2fo75HeNTQ1+VXj49qbTtW+bys4ZWyzO/FeL6s8n1Za5y4/4vO4XW3uyKsrfVwSQKBJ3QujETk"
    b"/kp32WaXVml79z/tU2px2XS3JLRmg8vn2tDVtoSwK7ck6rkw9iTypcCW6eJ0KKRbimma1mk08L8X"
    b"88PWxnxeD7d3Hmu88rZRRhJWl07AgYm0j6JfxZL5HTaGEU78im6ivZj3hZdV7F4eGF7XMbz5tu1e"
    b"N8Dx6p7WjXws1BPrux2Hh/2D9onuGo9pYdMtdSCuK3vHjdjbGBTa1SYRj+i9OzbK35oX5nStiC0t"
    b"M+L3CQsZY80HgPyZK7No9v1TRtF5lViDi57tAM1ZuaVOzLpGQ6Hm8jfSD79J1NXPJvf/E4G8WxWB"
    b"OMxNbvgvDfLW3XLZ1tVqfVlDn+XrsYDjdRVYzelnesIFQXNY9EIddSbw9TMKmbRV4q+pj/FyD3P2"
    b"Yc/ElgHrPGZ/j8klyxtU5VD0R2MwaZkJX9OznAsWng2R6NJribqOXuerBUZmvpsEaUFjukaMdl+l"
    b"f1lkiwxNoVBZVFTptG1d5RQfXWa3+IJphLMaTuC4+DjTtkzSyo6z+1nBbqx6ReW76qcHcveszfDx"
    b"w5Ns8uDOG7p/G6uoT8JA1VVGi2ZL0jW45hHS8ze6SNwbtRTxyG+LJEh1U5tHG6UqY0DaegPUWWn0"
    b"+QzSaZvBnup88ChJUlzErpHHNNIp85DIm4FO+BhPAr6n+7HhovzXAtvYpB0XmC4iijIrZlI0yldM"
    b"wjURWfR+MRJlfT8R1NcnqLIOJ+F8aTqMQWKBSnSEFVqjfM2XXqMyrXPemKtAdoO6D6cTV69huvqy"
    b"tpwbGg8pymx0zHL8kd0kV0ftGeCsZUET1XUL+HnOVPK+NmakwfcG01PXhaP0PXl3fZNy1yfkm31G"
    b"VOZz67Ho+i8GHQqnRs++JfAw3V7pDLq9yllze7V9rzu9pb55jdbF1rp2z/FgRo6zvSyPaWCPDFfu"
    b"k46Ke75tDWZsqgv9MAmcxxhJY/F5OSrqiDoNlgTOo6nYWxEk2CKsDal836jJet4cPbkCQrsWDXIN"
    b"oQ3Z7yYyG3Jwezbc02ToqEr4Yi2u7ZXKgKBb8hWJNmi/VFwHdq/xe6xKLzOMj3eSoWbFqt+vpsVF"
    b"Oj2b5LC/RWCwr4sQDcjAN2qs79VqR/LyMsHF9/1XcAez2a+4xjWESo4H/MFjKhGZukmk8HB8TjPA"
    b"WBLjtskaJvO5OrlcDarwUB0LM/wZS30eZ2933ccLXV3qLEzfGmPVz6ZLiDyiwjtNXStildZtxMwS"
    b"hpUPqXyZJnXBtO93X1Siz58pfQbPR24OOh9NM9wcsTFdZZ1wbI62vRNMZkZZxY2l/IH9mqQjIFx+"
    b"H7OLsh5JSdyDLwK00/EshJTqtxmHpPhqo6nE9X4i12JnmYCvjAztVqwTfMsmGDdV/AxADanbHD4m"
    b"zCoXyR0Wb9GYR+wuyELuuqRoG335eOTuCwUGpl1lXY6Q6p5xLicSwUOOuaUM+/XD6Slc6YCfJ3ir"
    b"96zPffwFHS9C25VvqedcXTouSkMIAMeEj1A4jBTihv1wDHM8btodjN4YX5X4SG0/ICBZlhQWhJus"
    b"/jHlnqWfoCpX0FtPec+cWqOhkP56zksqEchWTmaWgCB4+IxGSt5XRinXOhMZRHR2WvIBDDJn9Jbm"
    b"C220UEy+kwKN80U5Vi4TdzwGR4g0wq5xDZekVcwQKeCQw3N9k9ghW8YqQH83tIi0TuS6FRnPOP4s"
    b"CEdVtxMzgeQLWwRBjgqtgSXapmnnGZhJFuGrLNR867b1DNKapU2jEBAzDufa8XmU5akV3VFjO2pj"
    b"LbT9d4YG13b5zhC8hI6zEu46nN8ra9sp86atY9Bp61mLUpspTexPUxgsMcOmGNbKYPSv2ecXOe3k"
    b"ikmGFqSrVmNn7DzkNUUAl/MHVL5BlroVmlb+T6NoU6bNfAxSVl5/Dh9uPNkkJNiu29gl3g/DUsc3"
    b"TZxsMCL71u4S+cXNuxWTYpZnf3FfSiSD5EpPQqceVYHZ/2m95OtB+3kqVbR3ybtN+N4RZRFH+btu"
    b"8oWjSludiCQAS06+s+Nh5I3dtdDBu1Vbyx7UmoiUdCL1724+vaEH6v8z50JrT9AvFd3g3XysUII2"
    b"90lYWszpAW+V/d9awb1dF7ndCDu01pXP0UvQ/CKHWv9MZZg0lUjX/7q7DiJa/0n/dK2DezFNVCTS"
    b"0frKOS+gUOwVjQkOc+onMVWdxzC7rVep7ISlc7PabglnFCpO7Ey9FXqKEt3VbhA54GtQbEnQL8VS"
    b"Lw+uBMy2kIx7bpQhEV6ILFaV1zxRUjK5LjN8hVVcaGCf7tqwMtyWkPCWVRwYDPc42GZi7hJyh0TH"
    b"xAOrLmhQyMbOg21ESYKVeQ/bF8vwGV9JMSO6DFvFjBIwZoq+bYTmJsHZ9fkF/0rxhTIOG8dPSxYB"
    b"iB8wsawqbT/diYDIagNaXSd8/POAvq4KmzHX4Q98ZRDhFj13H6R1Gk1p7qADIWXkmadxDSAA4uwp"
    b"xfJzTjSs2sSqw/GWCaHjmRLiWx0XOlfsqaDH/vb5AQWVFGgPv5zrbiKrGx8775HUrtXUbq9KaL6K"
    b"dWudOqH3DJI0KGlWH/noNmoFg8L552voGqPY4JghRffVRVLKvunS7xWA0fvExkLLlFRywaHCKp3P"
    b"p59Nt4fkB9seM9vVNflM0GiEjVX5kd1Va+mkhEpxRZzjBXsC2Oi/F+gGDMRJpeSyPW93ddIuzH51"
    b"uv9qMDx8dzb4YXBi3Vh1frA/7/kBM0/VJ6GXihsb6z62inKrGk2ym7QlopkH2rc9vZxInVOTrszM"
    b"bJk2aFP0xHoF/t1xjJgjW+w/1tPLBXRN+2ue6RNj7BPEl6RN63hebwGXEhmZ0EidcAo6il4Wnfso"
    b"R0SsoriaJGaZZJHCYCCmd6iVTBXTDZs0rpvicNnTREyf/RmwtQExxIXCig0sEpVIFmkfYM3oGimQ"
    b"Monj+IqO30xidWKOHrgp7OJaULiLhv62vatkcibHLwXaNk4ZxvlG9dY674hX/3uflzs75yjtYB8c"
    b"s39ugj/PAIjwuZH4NJCcpsP4fK+ZjtjLkcjpCqLXMMB3yUM1qQbnuUWNx8jfDhH8PNiTc0PivESI"
    b"htDpXn8lOud3h+9Uzsi2qnGLMTprPlEcV8mYC+Hb81zHV20kKOjKSrud8DsDQSvBSkTMKiaWkpg1"
    b"n4u+N+W72G7oUHnS6i26MREvNbZ085IU+Fsl0gRsxnIHuMFJuY0yko3ZiqNa4iz7VA9m6KxUtjsA"
    b"f/yrLVt2etacPHmuaJhQqCLi7787/WlwMjwb/MuZTSW5HGMElqh6TUZ9cjJdYw7snWpWvCqLTAZ3"
    b"SPbkE7o2LgnfmrVJ17kTGlw5zjyPm/N6ob/1C7mW379xMNuRN45jHHoL/VFIgPeDk9PDo3fMj14s"
    b"8um4n7z48fCNiumao2E4obTS3arf9qny6ePO6qR80l71maoPDFgNOIahx3BM5ZgphcKOeGRyg1Ow"
    b"UYjMpjdCqKk8eDf5rP2sG4ktorPPWKcyN9yCb6wj03n2ExViRuncbHgHLcbozIMlPjGgalpXsI+Z"
    b"XRuEeViye1MloqLwZxOJeehUjAZo7gp7XLd6GHNFDU6swZBZg37ivZ6i8q64Jjvgqc1Bw6TAtvFe"
    b"YqNtFBkWjXziLMDpVjJy4ffKPj7pu1afiZX++r5CsmsTJnjdLtdZ+q42EfMyoV+HmZlI81Lv3k9c"
    b"ZX6zMZtTTXSIFVrex76jn7QWcxI+Kr54qyNfATbcf/tSwmuEcEeCEL/qwxWbg6xrFxBp4S0/bAeQ"
    b"bGymd0C2qtEgrx+Y6MlEWgYBBBm3Smqr4PDB47ikfu+8eyOg8vHUQEkNRFisZi8GE9mu+FzqOh65"
    b"53omONAQL2U36rX0wKjOexXcfvpE8zOY0jcBEC0bosgPft/XnzVjFW87IbfKWDt0uJRtoqMclKll"
    b"3WTtoF+qaftUVMnvlIvdDjUBEz0qImZ6MwrzoEPhJir7BDwp64ssrYMG5ovbwDDfQ8WV9xvkdL+6"
    b"33/AxatcchyWWyg4HeMgDisMPI32kLgqOZHeET28A4iz7J8ZxXeK3fT+PW+uYvyhri7Fn5prq7ae"
    b"s+qT8ebBzwZO5vNrXUIj6GX2A+nQmvEzI9ePscZYSYsGXcXqL+CESFZuAxVICgDj7BJI2XEJ5Kus"
    b"P7c/5jNoCQzhcHhyfDz86+HZYEjplN/vDIctTtymgswpWHaZM6PEL/imIDxpstniJvMLP5Z5LYpo"
    b"LhtXhfKOiTkC5qNro4GLypkkaUA3IOd8SzcsnUI/JBl+64SUAATdzfP5ys7q4upqmh3nx1Bf+khg"
    b"7Xdo3IUOABuY2gVGysY6Sx45GaYztODHP/FfbXPUyvBFbp6P8G08n6k/sBZpd8IP2OZjdnGd1xgh"
    b"D1oTQ4qu7OztCNRfORnAgt7n46wI12Pmq/Op8oruNjB23kog+N48Qhmk+Ny1oshAd/OLAgTXHuJa"
    b"hrLYkii635bDpHXqJvmAdeY2QmFUQ/5Nw1HoF9aU75r4L16ikQsgqGP+goEMYQNNREJYcSRaX/OO"
    b"+AELTXsZR7O5uR+FyA7/NejAR0L7ut4/MO+u0Kotsq/HJW7eEJHopQ4F43hJOrjRWZbRLOzPbLh5"
    b"GqAIWDoYpYk9wyNRaAydMsHut+OC2AzyUFvQ2Q3MtQE9B59yaRLb9F7doH5qeghB3XKCofv0W0hU"
    b"oXS3wZdUZBnYdgK4D5XduUKzxkYXGQY3XVAg8VhDGcDeImOoB/E9d3GqXc4rv7sRJOnp4H//LxDn"
    b"CmU="
)).decode("utf-8")

SPECTATOR_HTML = zlib.decompress(base64.b64decode(  # generated from web/pages-v2/watch/index.html
    b"eNq1Wd122zYSvu9TYHnTm5CK3c2enkbSOa6b3WSPk7p2Nr3cA5KQiBgEGACUqrs+xD7DPlifpN+A"
    b"PwJlSXHa3RsLHMwMBt/8YADP/1Kawu8awSpfq+VXc/phiuv1IhE6IYLgJX5q4TkrKm6d8Iuk9av0"
    b"22Qga16LRbKRYtsY6xNWGO2FBttWlr5alGIjC5GGj2dSSy+5Sl3BlVhcPBuk0pX0i8JshB3VVt43"
    b"qfjUys0iue5UpveiaK30u/TWKFnsorVKseKt8qmzBftaGy2+fslcYWXTk5xQKyL5nRITSi1KyQMl"
    b"Vyb/7iWp1KLoxMgG991s9jxrhLAfXVaYmm3dCRJGdUsbFC7TxmXOFNhrP9m0tlHCCsV3kUjeFg/C"
    b"g2B5ocRUouOFIm+zRvFCTOglr1uXSfOS5dyJFLCM+14ZW6e88NLokWbyj8OmOtKB+6xYCWsB/x5S"
    b"bdKRCmYvvRLLa9NIZTy7hQ2O3ZoHUWOVO1Gy3379D7uRGzGfdZxfzZXUDwzWLpIAu6uEQHhUULpI"
    b"splrYBD3xma2adLNZVY4R+vM+pDLTbnrA1BYViju3CLxpsk5mcPYvJSbgZxbrstkeXd1e/v+1R2b"
    b"u4br5c2bD6/mszCcz8A8CslykfReBkTJoCQiLa9/fPfu1fX7N+/+0Yt2ZglLqHGpB5mSuyo33Jad"
    b"Sa6TH2bhtZ2waWFUW2MdbhFpiudCKVHmO4LFCl6nAa+gYLor5/l6oGNmI0thgvGdHBS2wANrsLr1"
    b"8AANndSAXURrUfac8pmCv3plwCgsMC43IEVJCcHRjqmN/WwKW33rIqZIg2skkLUj0MP33i2jCIwx"
    b"eh2kCG/aSrL8p0HZAHVv7W+//heeDbwT8SZIlghrqZLlLRI09SalRGUdelupFONNI7hlFbIxm8+a"
    b"aGNTe+Z56z2QIp1Nt8kOd6qYCLowi4CWZSn0ktBl94FjPuvmjquywtvP6LojlkMtkXXx8CDm+phy"
    b"bV1zu/fafLqz6iIKpCEAT8YJgv8iEm6WlOcst2brgGynBND6itlWsw5+l7EPAfKKO6YNYrWUJoZ7"
    b"AnbI2DFt4CR47/K2z95+y/1GQ6JNPrjDQuP+MU4t+X+SA8HiyLoh3eKIcWnOJ4E6JUOU8hmp/jNH"
    b"kUdAotCGoIwVh9BsjvsGmxHqSB3QZptSgEFnSmGP373jqstg4lGed2YbvIUP+Ohy72w1LLnCOeAO"
    b"cnc5L/3yxhScbIMbPAhlWET1xGT5L/2AFWm2PEzTUcWP4UwJJT/SYQbq05Tchho50dCXzdqU53Tg"
    b"Qx0Jjaej3liztsK5x5BH9S0IP+LYu+WxkjvEwm1PjZ0yrW45L9cCJ0OrfbKko3PGvmWB6A4r23TX"
    b"rYrklXR+jNaYFIf+kMg3gq9b0S8Sb0VJVnLP0zCzSL43rSqpPPeD+UzJ09zXHL0cOaofnOd+X7U6"
    b"6O4H57nvcNLmZgtMu8F57nuYmyzp73m+t+hiq2QZfs5zfjCq4Noky35wnvsVtx56w0/MOZ+16khm"
    b"jpGztrI8lqHXvF1XHoGB8Kca3GXIsiuVoYcJDFEQ9fUSIhcvLs5m3b0Q+ohGB/If0vea41w1K/Z3"
    b"NJOTXEari7b3MzXlz6cyMN+dLJ0Hs9ctWlqNY47Ik7JpVMQ/ya2INA2Afl7UjcdhG1SyVvMNjgKe"
    b"K+ov4kAwf26bw3l0aqOP5qkW/dARz50PjLyEwbEoHKqHlweeDR0RUZ9W5+8R6vKYHtdNfIGqG+48"
    b"LqOieGjQGfqZ4wdH0H7u/xl0QFn56qQzDqe71pC9DuQ/6o3QUk32GvratFuMWrjuDkP9wBkE7/b9"
    b"ykRZFEBBXd/onHesXGuuqB0KF9OpwkD6InU/SIsNsIYTSLFpgf5Fqj5IsRXWHcAVaMOZG4rcl0cG"
    b"aaq5bjm1BqpJDkKl6+IfR0wkcjJsjvK8DUR2X3ErAI20hw1fs7zCXbBG81YwNzpEOnrUKB5w00On"
    b"2upPUCJXUpQZu3IPzFeCVQa55A1zQhHsfYuyvEasesHidce25BkJamYa/JEI1xVOsQrFfyWoG9YP"
    b"+yb/CfBx7bZRx/00ADuhz0F4yNWhdxWo7HtePBwg2M0DqLAzXwG9TkXYFaPaBcC62w6Ib3nBcoEr"
    b"gAj0FTretJYaN/EeC/FLg5jFPeiNxyVIl47ojFpspXaEOYmVopToueGh4In+TjW5J6Hz2OAO9Xhn"
    b"n4Bb98aWfHP5HKgJiX6g/4g7wN6NfeAgT31rdRp29dMdyg21b/NZt864bJClK87hsl78gtp0tYcG"
    b"ZxzxjpLEACj5EZODLKNNLpK/YQDfGK12WH0QGrVEN2ZHnkkPImZycT7m3IPbc6SvMM3uvDpchXex"
    b"9x9p6ytl3Nx3N+7la/gxbfiaEtUhGFZwdx4MGjiiBuIRxpZvB5PQ9W6Z0IXdNRQfHfUA6xNoR1p6"
    b"sF+cBfs0PLGmIxANmxute/RkMcWpv29Pg0IbLz5358Y2lAhPYvTM1Ec3Ug4lwyjpQwA3R18KwutA"
    b"GDbRgQntaHOL+FXKpoTOMd0diaPAymKReNvulzt4QPjfqJ3P6I0RvysDaCyt8x614iM6mq4WUWlC"
    b"3eXrml7FST9KERxqWcEbnkuo32XsHT0d96cyJqzdReE0nhIv+6cxVCjmcQrU9PbEKJu6I5f9LPK7"
    b"99cZu21zheOl10cMuUDJEivEr++ef7Rh9zdXqHh6I2mRGisU0rSO0Rucw/eOyqJxAvboUpZ0yNAr"
    b"NN2jhmrKWzpfvOyeIrLwwjO+Gm+ELo1FU10Ijc4x81RPEMtr+r/Ev3PF9UPSvTlrQ3W8u2tKW6ah"
    b"hYeFUEx3bE4wD/jOu38VMGeLaBHggAS2Jg1v8Onz7PJF9k1qm+YiQ6HPPiIOS3ogh9M6+VOKPlnC"
    b"IP1rBhWZxe0Kre5TVfRFe3gkf4LEo4f1ozKz/n191v3n53cOAntP"
)).decode("utf-8")

SPECTATOR_CSS = zlib.decompress(base64.b64decode(  # generated from web/pages-v2/watch/spectator.css
    b"eNqtWctyqzga3ucpqEp1VTxlPIBvONlM9aJ3ZzM9LyBA2OoAogVO4j513n2+XxJYXOzkzHRcKYcf"
    b"6b/f8/CspGy97w+el8pCKr9JT7zkz17G1OsLoLmsWj9npSguz95Z+A2rGr/hSuRLr7k0LS/9s1h6"
    b"PqvrgvsGsvR+LUT1+o2lv+vn34ADp/ubhNf3a3YEnceABzwMDKg5q5ylBA1jfBIDVUw0PAMwCvDZ"
    b"GGAiVcYVgOsNPvZkeW71QZaxLIkNrOUfLUA853keGhBLU14R8BBu9rllpxBvRJgn6/XmYEBHKQnb"
    b"epes99yA3pmq6NSORev05eHHwz+8714iP/xG/CWq47Nn+AJ7Hy/ej4dTWxY4UIrKfxdZe3r21lFQ"
    b"41XC0tejkucKBN6YejLqWNCdRGYXusPUUYBW8DJznSAnLo4nSBEGwdvpDkZt1w5G2gBMvnGVF/Ld"
    b"/3j2TiLLeEWUV62sE6a0N9SyEa2QYKBpRfp6IfH/8kWVcVzZ0hMOE3f4y+VmuwN/gGWiqQsGn8kL"
    b"rgGsEMfKF3CH5tkj/XNF4D/OwJ9f/BQ+oo3S1PAAP+HtOwdXOHFkoBNGBm3NskzrOYQePK0MQF3Z"
    b"1TFhT9Fm6enf/dJbHXYLfaizTNvKEghwv5GFyKxmzOsF2XSVKFZlsIF2/ncr2SGAKQregnGfmNRs"
    b"rIKYl1p35g5eVOQRE2OQe0HxlgnFMnGGHjZkTE0F/gP3W+0jRfiM8f2C5yBMGr0KjisGAppQWsVT"
    b"MhNoDuysI2Exwr3TuAdCxSTUANOKOL2ie8zz3Xa/14cy1pwSyVSmPcR6JIz/FG42sMSSXPEXreve"
    b"eT12buXAH45KZNqs+IY7loC2HOYvzmXVaHQl+3gKgCxXi+5xHWj86x2+FhNvalqmWm04IgH1GmzD"
    b"wDNy4uiRjxxccbAAoWfZxBPcceK2FikJrNlpamgPZgVGgnr/9A5jx3wMAh0tXez1kQfG30TGJfh1"
    b"0XpOgONJJn8QiVwAQsHCBGJWlBDHVxxhqbR31OKDpOHZy5Q25H8k4pBvpAGWIBLgMcSeqBre2sC+"
    b"oY0+VqdhPFEUJRxfW8uF9t4cbWYiGMHBCv9I37jxlAqVFnyJ/L/Bh3nwDVs1vH30i47YTq6V4kxn"
    b"z57zSlZ8IHmtc+tHn1BjHRSzwdN5cYyQC6wDWTQ+HKk9Ny4lraMbinAZSM5IQJW2gA1znUlDmzi7"
    b"whY4OatLF7u5JNhfnOQcU+d0vFj53k/CWJmSwDNsfYLftH2dd7MCXTqrhm7VUhjDoThp5p9zmZ4b"
    b"/000IiHLsDGArM5giyEc2pLnFq0BstG6T7+Gp+6NL/NcO+Da5rimFkhN6hoc65jedMFhnqwi+9yu"
    b"gZ0mNz2px02ID+vTMBTvDyzfaWys+C1FIKsQbrYmgikvbDziGAVTVLmotBRXhlcmuud8EVkIuinR"
    b"7pRg/DLJU8PaOVs5P6ubtmoOSwepRddML4quCvq0Is5wfAq76mhqS7iKtk7hosQfeFui0Xca74o4"
    b"YtXlHT43q4b6VhFzWiHK8aKgnop0Y+joEjNMd1Ee5evtxIyHw2FScLc3imKvtT3FWNB5IxI1NaTF"
    b"baOZPGD0Hwz1H41bv8eQftY9o6bg3zNExpH5i8ZPmI0KRzmdw9+8P1LHfsDdgeQMJ/qJp/rZ26Zh"
    b"yMsqV7w56XZYUxmYklrpay/6GOc8SLI5JBmnEp7dQEPtt4Mmz7MwZsYrWMWnRpnmRDtiLH5eW/HQ"
    b"ll1+MoRPkWsKfKaajI0mpx1kZDtIjQmNNCMKbt6YSQMJazglny8mgthltieB+JOa0ueto2lLdarW"
    b"rHPKZhTSGi002s7UQicGhiFszmfiba5Fsy8xMa5qJY9wqsYnfAB9idUb/qobkRZNepNLhWx3rmuu"
    b"UqhxziQbaxLLSzblJXPsve76g3vJTqNCn12CSmtlH+vrbkscmh54FTt9MbXJqygnb73hHgPzj3gg"
    b"Gdz+TJG6zDDDMvSVhWhI5fSFfudS8K6EfY1vxWvO2ieMYcOmfmG52g0cg2ImGoRYMGalENMA/8kg"
    b"thWgSyB7/MTR0IF2xtcnbfqVMRQ2057MNLcGdr3Mi0LUjWhuB89AwBXaiWom/T2mh0MS8VH12CTr"
    b"Q7hx8yGPDuzGiDd04O8/Z8T1LSPG0+geRcpMlM+0tTOp2ux9Fo7i+zQ2jcV5kTEXXr7uxiTPfiTP"
    b"yBsNxpKXiSm+d1uAL024pnvRtDd9p/F/KMg79LmeWK1YySeMTpU19faf9mOrbP7GC0qX+ulU643T"
    b"31BiOnxApfVq1InAf5kfmrWrmHZ+thNxUK4gINDOHbZbG+dwJ8+AiahLv8i6uTv0uR64gie0l6+o"
    b"wjQKGBlLVp0Z1eui9mpMvfYZNewd7lf/L7js3YIlul3qXTYpZPr68mUzDUfjbZ8M5wvshHw3H45X"
    b"HghqTQZu14qUFT+f4IcTT3x31zq3GTWDse4iaN1dykpqZ1x6v//2DQ/+v/nxXDC19L7xqpBIi92J"
    b"GTG7UX8w6A9m0+ATAXRTHs1L0Q+rg+F+NNrPxPp4rJ/w7f+pZlzD2ffpLXS37utDzmQy1zOmk5nl"
    b"cW4Q+fGQS9nqtHqvPNuBbTBU2aF2c6sm96jZ/RHTXbjSsKd8WRUUsjOrst5x3W1E6FYPPxy3M9Ms"
    b"myKrUpFN26dA90DB4kYOdDzmx8O/XvklV0jtjVlFoI+j9aETfUq2qDpP612Q8SOlMLpV8kww78lZ"
    b"fx2oqVzoZZS73r1Vu1CxiDwOu4PwdZvyeZwaDWshZhnaxFeGun9HjBdekbHPiOVBIqG312XncAXS"
    b"STBewgw6aJq5fLNYdm5vLfk7eKarkWBrc/D0cD08u4oj56ij4XEH5Hn9wHtlLuzfDdr3+41dNNPY"
    b"aRxz88r9juYQ6fnkMJ5PwtzsLq72rhXPuWp8xbNzyjNk2W4TT8/W+tfFn7N4M43bdH3Xb/ZcMogE"
    b"wq6PgE3IQeXcYL/+u2bpzbbgS2+ysZ0pRr/qV/9Bzuk8crDOWFo7jWlos1+Z81lGY3yXQkmG/wKV"
    b"58wx"
)).decode("utf-8")

SPECTATOR_JS = zlib.decompress(base64.b64decode(  # generated from web/pages-v2/watch/spectator.js
    b"eNrNfdtyG0ey4Du/ohnrHQBjsEVRko+GtOSgKPqIc3Q7JO1Zr0JLNoEm0SbQDXc3SHNkRJx/2H3c"
    b"5/2Ffd9PmS/ZvNQlq7q6AdIzs+uJscGurHtW3ioza2NU5FUd3WTjtIheRONitJileR1fpfXhNMWf"
    b"r+6Oxv1eVZdpMusN9ja4QnGTltPkrquKArF1JmkynmZ52lVJw9ha47ROsmlXHYawNeDfeTqqsyJ/"
    b"m1yknVUtqK1ezTP4WHauBoPYOnOY6KtFXRd5VzWE2vJXskzrco26BNaozFOvXiWrRqwAty4Sd+Dq"
    b"+5s0mdaTdRqYEKRtgDBndXUCC1fez/NikY+6x8/1Ew3amMBajeg5BJp5t/9fzvZ/OP3wbv/06ODs"
    b"+PD0+OjwBNr6RgO8/3Byeny2//Hj2dFr+N4rk/m8Tsst3NNqa15cp7Mi37rZ6ekKx4c/Hh3+5fA1"
    b"NPZ2/yds68PFz4Br8WWZpn9N+582oqh3W1W7jx6NitlskWd1llZxXlRxVYyyZNobWoj5opxP0zKF"
    b"zmKAlkUXi9F1WsPXMhlN00BdrgXt1mUMox2lzcJxMltUcVb0Nj6bFTk+PTg7+PD++6N/bQz9C9TP"
    b"RulJWsIRr3YDE4v8GotyCoBARhb5Lv4rnsZXRXEFA4bp7D7+05Ptnd5yMAxVpW9RxC2EusJ/evWi"
    b"zHcX1dZ2jL/ieZqWP1fU+JOn//K8N/Qg00UbpAL8PNBVFlVa5sksheEzrGlsVKZjQC5Yb1M25/rL"
    b"wQY2sbF0EOz08O3hO0Ctn85e/XRK6PV0+08Gw2zpyen+28Ozd0dv3x6dHMIevEbQxzvb29sa9sej"
    b"14cfCO6tD/dcgL0BpEW0fnP2+nD/9duj981Wnwnw0+P99ycfPxyfrgf+7vD10X4r6JNtAp2mQB1T"
    b"Opf5YjrlD2VRzJwPdYrnFCjcPhFjp2yWjrPkGPhCsDDJF8n0o98Bfz6YILWbhiokGVbo9eTH/by6"
    b"TcvjtFpMa6dOMhqlcNjHb+AMOQXzNB9n+VXjO52q02zmTxs/fw8kaFGmJ3VSQpP7tqJiXgk0OU7q"
    b"9PRunlZYmN5GJ2ndH3AbUJQcGK7VXKiWMmIfoRHVZUbdbOsPiiXuT6fFbTqGkrpcpHqXylmWJ7ig"
    b"l8m0Ul+Tuk5n8/pwXowmtiGgRbCo849lMcsqZPnqV1ymVTG9SfvYrJoTgN6kuC7Un2h6Agu7v6gn"
    b"zYHXZZJX86Ksm0W0DC2fCY1O4My6/Rj0O0l/WaTAGaB467FXdpyO0uzG2TLaEGIqsJ011urdJkDH"
    b"8yuFWFWdTNPXBAEbU6e/1gLriKeZiloUMXWnSVX/iCA4F6dLUwJregXrWYkhbVwCZ6PtB35UgFCR"
    b"jd4Xt/1BhHQUthtIXnQ1LS6S6ekkq4D6lZdFCfg/SoFF3CKWLUUb1aS4pRH2oXaFP5D21Vk9pR8z"
    b"6Du5op9fEPQji4S0skOqfIwrZz9NiwQPjMKqJfz3y3KDx6bQH47sFaGBWJ3NFy+48z2Ac1bNfPVk"
    b"vhiXmlactprA4rr4YQ7zPUiqFOfZrDSCha3eJzNnP0A0jL6O+hX3CCPpTQELetF3US/iX0D8e9Se"
    b"Fl693mm5sJxRxStVa4jlVoqMJ9kYWAsUb+p13eP9K8MQtM4IokRTnsvbrKph2lfAZ0G0pgq9YbSp"
    b"dmFglpPlN29gfeJkoXm/5Wn75SUeLgI45l8BCIHlDCg/NOCLy0tSBhD0g/7dgErLsigJ5oc8uYEV"
    b"Ti6mvC0HtnGoRPPNLpt7OdDqjFi1ZExCN86D6qWAvwGwEsQ+IGYSEntQaMyYrXFbi50zXt/zr74Q"
    b"Zizj6KsvCguW53tUAdtwhWNnc/BAyNZ0P1HUUcmtwv0sN/D/8sTPk7JKD5J5cpFNs/quLw8nlCUz"
    b"zZN+OH57kiblaPKRvvanxSjBFuJJUk3iagoCYv/xwKwIdccNoFwOEj0sO23BTi/6wx8axbNinGoI"
    b"Zs9bgA0gsuNGqukqcvYFpVDoeTfaGUZYb9erMowuy+QKZ70bhYe53NvgxcChtozS67UG/lxcRsfz"
    b"OQoTRNQIZUlA1VLkd6I8pqUFdlZ8r0bjrtlA1dlVlNwO6FMcx2pQ1+ld1R98BjG/BJEg/rnI8n5v"
    b"CGNDlOghvxzeDG+TegRalh6pbk7pXLxYsIvvF7OLtPSnO7CgE5ZrJAB+gpZ/+424mAakDj1IPQgD"
    b"arBAjwCH/BjK6ePmo//2aX/rvyZbf93e+tPZ1ucvz4ePd54vv3oEOFzVfex30Ar7ZMcBpq4HTUSR"
    b"6+rhjkEcLeLT5Ic8syUxRZ5qlt9kNW2a3kWYt7OPVpLTh4hXxj1WextEJyzMH/4g+TL8vy5K+qoQ"
    b"TX0BikNK3ImlYfrsKgwNAfZx6kPYiKEd6zypJ6jXeCwflBqocDIHLE6gHRStQXd2yECZXma/khI8"
    b"n2/dZClIzVvuFouZjMq7eV3oI64m0yiPQZ4bF7MffkDt2plUcxtV/193tgKHQy0ASLL93lZvqLn0"
    b"8vcNFJD7mHr5MZkuUHRuGy0v1sVdTfL1yob6RFSzvH6+X5bJXf/xN3wUm9OmclCBi1lfkQzqRGul"
    b"N9hc9OIl/wD2f1Ij+cEGYc/HpHj0gVL2tntMcjQZscvjnBdHHkzr11beZUY61CJMWI6T8rEjyLmC"
    b"s/dZmbTaZSXBZfGQ+GagBrt0xhh1wzsdLRtjcsRE17AWkazoCyiXIKNPSEBRv3axHggS6djIJY4h"
    b"bpUkZhtsEcVI72AA0BWiaxDtc+r2L0o94W6dcw9aWPka6NdFkZT6wLea0jQV6Q28sYIMxr3tdVVn"
    b"Lkmy14Pqo6QMRIeFhAe1cJGMr9KtEex+3Wzhb//xP6JH0fOIgCpqCLQkQDg+0vg1AuJgGgelEXXH"
    b"KcypKInefEI9fYsgPwNPVVhHfwekR1j5HHBBnXeGcofE37BROIIx/WWQs9W4nSyuJnXHHLtXqErT"
    b"/MGVR8VsDqrqSgwp03ycliBCAk9EcjNYue1bNajDD9z0Co41DOn3NDGapKPrOdDL+oENML+s2pCO"
    b"V1YeTDjraX2qrRB9RZqwhjrMhJuoyETlIteE5G//8b+UPNBm3Ig6TRtRu+0iatAKAndZgzGEWPbg"
    b"TmuWlNdmVifYFx4v7IaHjQQ+OMAXPEQrFDjLs3pRJFPVZyg4VzUcK+bCJE5QYR0jQ38H4lM8S35l"
    b"4rzN3Jc+Xk6Louz3PfvLVmi5B7Djj7e3tweaDXirSI0qas49nFuCLmeGeBMt5mg4HIM6aUe6rGDY"
    b"BaqYajrL83VYjuym77Y3OA8wjo8g+aZkdKsU6xAEsyZjHBDMT45Bb+hZ8YbCdPdZby+hAX4ZcEdY"
    b"Wixq9U3vX9hQGLWZCaOQkVDOCQ7KIj0uitlbNE32i+kY//CE4JusWCAmuKbOeIQqQx9WAUQwMnsJ"
    b"jQotnWz/0vXjepLm/aS6y0cR17Hz3jT9ap2TTLEknoJuoHX+BI9apGBjMqb2FZZHzZrLiAYY9c/I"
    b"bmJNBwpSmUWNdWCgD7xjzVUT2bPCovkC68jTcTAEaivEcOzFX4MKqMU5a6M2IrTccVFsjrBv0+Yx"
    b"qyvq6fhdwyLu2cj3JPRr37Tu2todWHXjgNqi8/2YbzbwgsP5/k7eU9hLiwCMvbRwLjEM0gYM/FHb"
    b"rUDkXr1E7sVL1HrtErVfukShK5eo5cIlal63RF2XLVH4qiUKXrRErSb9KECTLJLpqxlFUI6A5JWg"
    b"KskSRuvGHU604gaHe2ji3SCAiyAFFtoOrWq5+DdoomSgDm7DQCNkPE6ruizuHAgHq/TBIvLRwDnT"
    b"foBILIXm7OBzS5M0njXaI4NlXJUjvtkVaxm+/4g6bz8a4oCgveMMOEFFOilTzBYiT304N1Kbuqog"
    b"d/aTox8nl+mPJOAd4zgcswluTpYn6jSdf/WlYYlZfvWlaV5ikzCxQTZJmGrKvhE0AkUNsL7on/km"
    b"27TDLeMVweqGEaqvmHCT7FcgK48X05TuJvaxrO9o4cTihAXst98kSYe/Nv3byIEQ21zzWYyqYMBa"
    b"bLDTXl1aVhi47BTcj5HE8C7+6FyIkXCm7yi0+aXH+C8ulyLUccYWYL+6joDrs3kVxaQkIoU+qoDE"
    b"TdOtBeyKauRkkpSoasJUYtPAF3V/s8ujXbIRJyTWaq6KV7wvX4SdXKwc/Y9YjBNyWIoW4mLGeE/Y"
    b"zTM2adi/HeOp8V3UI4KfLFBGqjNGuwgWjAg/iZXjCESDKL1J8+g2qye0rqc/HL9nSo0zmF4ko+s4"
    b"wkWXaw3DvMamkGzJxY57pv9d2KpFXcyg25G5Kae95OaCe4jtiq0yd3O7hHfmBjS0dx5GO4tixbRW"
    b"xVLh/SSdzkG5NNeDnjzno0jXtrfQTQcL6BAbEDi0gnTqQTeoYghXhTecdiWQkiIpRwbf3JvEocGz"
    b"DJl5uUAJwlE8LQ3mG2pW3rK8j8rX9jD6l2fb0R+j/k70xz/aMrXlw+jpYDDQ16+IA1podQRQZDtK"
    b"UvXleEN8NIXjCdItnpiipG4t0m3U7qBBpt8iG2vCo+jykOfs3+tL0uxSZWqjg3SHBHw1C7ymxtPW"
    b"F/Td4+9yjlaHYbxiULTxCAyx7inOvWhMF65sPAbKtoM2YFU/WSAm4uKSi4k5OGhwYLkBekCD+EAr"
    b"RMQHNZhAMhfFqC6uP+nu+EWaGuZq7sLEQCJOWNtqUk6+QPbppvf1p2JRRhdlcVsBVlwAI76GmQJ5"
    b"LLD3OGILZEReGNyAR4mwZA1CJPwQLoHaVB0sHsjhOyOFi333RHNk5h2YoMwEJawfbrYSR7wKSPBY"
    b"HlRw/sULcozuOn2+8NgNgWkI5x5LXZH6KDeIvhU3lzzuuCpm6NUEv/H081eJprAGjW/CB4FujkKH"
    b"o3lPuL7Yow6hq53BQJwPckB0jVyAutVzqZGn4cW48f0/n3x4H1d0u5Rd3hlPTaAheBVv/sLtxCt5"
    b"RIktF6Pxzj8rd4WaqAqWg/Dp5On4yimil9Qc/bEzffGr8SQeNOqrNE9LEkd25W7Yzxb0ElYnLeew"
    b"SLUDK75b4IrM4bvoNXBa3lXAOIr35LhbpdPLo7EYXVICzu46+rJeumH0JVS8HEgpoKE7Wy5izu9p"
    b"wO4mCvZsQw0rTJjsPXoUnYLQdFEsUIpSYtxYhwWU6SzJ8goGjTdDUZKDcHcLfxMnjBueKk16Tr34"
    b"aqNzhEeLsoTpYhF5Jmy3K5Su+Vayf8WNBKOgEzxUt3FDcmsCJoGsYZyVSJLRDLNVF1tkjuGhAJzW"
    b"pyQhNiY35sMefd0Lr8CRFXv67JxnXPOiifbN771aIG1AbrYef24Xt/w+fI1khWcZD8mdC9uuf7R1"
    b"1hQi1HWz3deuLQ/Q9jirvs/yDCbp4IbyAuh72KTuHhB1ZJcvPaz7OtqOtx9LDxQfK0XtPRdgBRKG"
    b"VLwN4/nlcxU9j1Drm3oyCqZxXxGq9LLV9VxMNoiXWoZhMQqvNKZSKUa6cKOKivkc5ZrxTZKP0KQc"
    b"3QpBi9WsyzIB7IulwMQNWjmGqAXjQDIeH4KKWOOlK5JovklUt1MeGYG6bZXslZaV8INzVZO8MAfO"
    b"ExZnRalnqyeCR7uja7Neq7reaF1kWmItPGZVBLutpFkaFi2rOyZVTyztilGS7O2McX0as9EQg9Us"
    b"WKA3g2nIuFGNUnkFSrERwvXQ1xB6V5Cq3kfuvXve7IHqz7sxbVfr0tNTY4Yhoc4cR1QKg1SaBPZr"
    b"yeQkqQ5/BQb5b+gHSA4+wwh9Ah3/bkUQyA/IdWdSvkHCUVEDbLJXUVax9xEBGjKopORr0+mg6YCI"
    b"jaKjIgI1/ROb/iZKCEDcvUJizXMBPTmbLWZ4LH/FH868DMV2Kg1I96OJgSaoGrDfvn2h2wr2fwrb"
    b"bToP9GlXTBP+fsuCsiCMCyo9tNRyTdP8CriwHUxzQQAyG5/kyRyQttZTM2cotPEc/mR9cYaRcKyB"
    b"P+Z4AYI/lB8LfipAZUx/pZ/odKGPlfLXYL2WvWv0rzPyloA/lPfEWTqFMabjs4pvhE0T1jMCgLWb"
    b"A8VBDRqXi4ZtbTb2IdbzGUbPt63PZxPOzHUYPf6mE5IWYhg9tUBy+2IzeVZ/LooCLVw9oZH5NjFa"
    b"UHQBQ2lQbcOrYjEd87IdJNUoGdOinU5wMPT1GKTbi+LWUDKAx8/vkrKakIGhmI6SvMCfh7A3E1o7"
    b"d7GaWMC+QBUgg/YiGuJuLngX6gJod++zXZvAKVctxFzdgAbKWMXNyfMNNFy7CHGWj6aLMToxokOp"
    b"aUPHLoX6iavsr6xvhnpS50UPuy99GzUozVIezW6g9m5YZtAN9Ls60WQlPFyczXZ4BWknCOB5EK86"
    b"91idWtxkduri40jRHM09divFXCOwTiEK7NUaRttwuJ49HrS2jqO4b9tYp9myC2PXC4BaV8yMBmlZ"
    b"gEqH0J1gLdPgvwWB/gZ7C5As4dAyS5ERRYaAcPfQ6yfHb8XdSq6Eewgy9jUeFNrFeToCpfIso4M7"
    b"TW9SIgqTOf4beMUZ/Po8WOWlIfDHI4Dca6y7HEY7Twd2mzZ1uR2Gs4reNjaAYQuhxWfPBqE2aTJr"
    b"NEdw1NLj7e1gS5P5Gs1M5oRT3zx79iQ8Hl7NNVpiQBpRo7W+McHYsfmalChVfXZAQOlLF1pBKOfs"
    b"xo4vV1ILYt+IaOQfS6yehFhBIz71kowxDA1vAgZ+LZQb42dL1mXDZHMMM1IFIEzw3cyUpGRTkwQN"
    b"s1TtB8kh86ai1gQ/9SbFoiRhB2TBRc1yj5FV0HkaWZY6XrgqvM6DwNEKHCqPouneY+qUEBCPg8C+"
    b"FfXUGKnmsz/do6Ka0f0r8vyb9Ro7qQaIi9TYy9WIqfptERrXZRkt1Wn0Tx5/s7PzFL0nByuwy4qm"
    b"90UvW9PiFy4LqNYzItHXWc6UWwjhyVVqhOP1sMsVR02fsemKN0CrGJ6oE6qgGdrL6OlzgRu+0es1"
    b"BsZScFK/vS2HmoqcC5Z4zEB1reoiJ2qT6EtzOniTRT1GaiIyMKA18SYt74jsKNsSKS/1hAP8KAGD"
    b"T33EyHDRAxgvJH4BHFQnLIIKSLFvAfxswdBw/QCCth0ZR2kPkHOlSZHwp+V6vEcYZaC+fTY6enBw"
    b"qi5LsTSm52tWUB14dQKtosgUrtui4lrnrE4d1/bHmPOpd0PSLpwU+q9u5Uz5STCVZw93+q00aTqB"
    b"XRqoGjydsID7hSOdYu98FE3/PQ/CH5cX5mgO4Elymfq0jkfvScT6c/RttB2kc5gSgCLA3HtDHXmG"
    b"ShiejMN8BIy77A/ilH7513e8G4MY670l4tFxk9OByNzvty+CKU9Y6vbtHLHeLA9f0Bb3oVRhFRJd"
    b"3BjcsBGGv36n/rsrwzNkH5T+oD5k/tIntUOgpHdIqNg/23o0TvyH8jdJ7kysAIcFsF7zKHr+DVR2"
    b"Ym1BfnBBFex/VrBQ6ck3Th0lO7TUImCo9M22uffA4Zjhnn/1Bf9eYrwA9b6cGFdD+ltCKgCMVOdO"
    b"l7Nz4Q157n5vru/+Vfr71pZkw4VYYHKsoal+i1M0gD8vYGUAqgHE62EHHNgUaGc5w3iJc7+y2oLO"
    b"2tQBrJGu3wnMDcLiM3RzxT4q92OfSroGyS7k43Zq8hFiUqciQfnMqT3+Ourt9qKvm+VqQ5tBo+1V"
    b"FPMLxpkO9jyjqpIsvxPjhIajvrbCYryiKfJDomzUmFLnrZ/tNCMn8fYgMqywhVDsqDPlSDxykj2Y"
    b"ZNMxtG7dQFzLghvbiz5PTgo8jp1WveG1sHYFIkg3cJQ+9WRx4+YBexaek7GCpgEnc/SJp/H2qXrr"
    b"7eCmNHD8Myfwvog+cl60KKPEEgBy/ykEzS5i0/VcQJqdrTUVBHRnwhjBrasBcpts6mxts5onuW4V"
    b"QUOtkp1HgIQie40tQFtphLmhwz7znTn0ep3xyJyfMGj0nzCriFd5eT6Qjl46KOnGzZLYMU2CDc2T"
    b"LVcSyI+oDtmEMED5JqagRxw6/jajJlCdEEUjQO1m+PNGapQJ45tS+/HaPNrJ3NnnyfzfaBlfhI06"
    b"LcYc2QcUoWODauc7r8Yu+4tqYEXCm+AEKlwdNUBjCC+jbfERPjzyAED8ineeCedHuxI2vc0UuKTn"
    b"FIRQVVrv10DWLxbCPzEps2RrimmSjCZnhw8szkfuZfTmo93LyXyJx9b8zaNcnqvIdQpsbGlD8fzz"
    b"Jt6iLW8tpJ3MwziwhX31DIznpCJnJ6bxqDELGOU5ypd2sD1BaSSVU+k2gmWE7m2FtDFthZP5oIWq"
    b"Iqj1hfDYpxHBjfD9wJB/V0rXrRm9Wwis5sauvZYBGTwwgYBpiS79lFsobKGpsYz+z/+GPXThlufK"
    b"M9SACTEblCVKEIaStnJYzii71DybFpz8lZw8Nqyf5K6KXaiT6xRtHaqQLaO7xq2AvyqsESoKbtmD"
    b"EyDYmUlzrFoJ3bOarp3bJ78aFn22q8A3XSIhoYF37/X+bskSFFuvDnXH6q4NtqsfSIfgJE9oZj8z"
    b"l6O6wfslW8C0HmYomPrtb//zv4vMb8sHpprYUJTPX0vv1vE7zrgA/QUBlyJZxfneQ1NCsGO6QYKW"
    b"20M7FCX5t9QYPDC3RHgU7i3j6jEg/OCBCSrcEVjfgO/wxGsvCdz693D279K6kcfCjoak1IdltKBR"
    b"eJqgc0LJOj94cLoL0b62fZjmW4zuNn+eWRxrV/c1pAcl0Hhf5GlUT7IqUkPoiUBFSRXQAOyRZEF5"
    b"3ym7tP6ujdNYZA3V2jdcW6tluJcp1eZrKDxRP6MqubHVtS17l5MZwk/h1ajlUST4xs6tysjYjVzE"
    b"rgdLYlLEQQyyLiaRmPenwCaQXfyzGXoAwNjCFYw1zoSghT2b1YbP8WU2BUmk/4pvghQNfche08yU"
    b"fxgy5DXoaEvmlAYNdczTLLA1y5SNeunZXthhvt1EHbZg//Zbw1b7opl3pWm5DaVmcRtqT9PSdA3u"
    b"SNjiSXwNo2szfQunmFI+7U6mEYxIXczR6xI9tuOeNOxwEEEzTohc+G0e2t8T0hKM5H1oeOr35PVK"
    b"HcAYf1lk8vTqSF4q5nnbCF0vBBRWgxWQKCEByYnf9WJC1w7f9QIOOkL/mpmZ/8nRmx1jU93aqERA"
    b"D876fJWM7jBPwMmozOa1TS7CyrVBHlyvtwb4z5VAInUBwMkovGh1hZJ+3mkz75b+BzahSbCcb1xa"
    b"hw57r/7q91WXQ2iRHYBNVKh6aYIqdymxBKDVWP4LHYrxXMePbuBQF+Ujzli59Th+Bv+Dg6rdCuKf"
    b"q55Tscg5qj9S4/IK6X4HbVI0Th4yJSU8xALQ/2jStNZ/PolAvoY9ZJ/l3sBnBJgJ2dFEuRem8QMn"
    b"a0zLIgeyyDAGMSb0U46Ybckj4JMTurJTqT3bYzCVG7f+8ygnao9R4ou8WswxjxBgNp7mNYL5kbU9"
    b"+OT7uL0ZzMTQTALUPCorkv54LukH6MNKkQGEKjgxd9ttQL3npi6903y/tDQY7kwBkYpuDYLB4JWb"
    b"hBTDZsLJSQ0p82qsvdUn6WgBhFrkbAhlLOhh+k4TQjHCdMq1JfvzMrvBX2YMUUavQ6DV+yG0v5Wg"
    b"tkYo/xlQDmM5MPSHX4rBzRnKPNiwpWUB+pnezyq7guXH7MS8iRalVMozsoXoZD9I3OBn31vmoUEn"
    b"PAUg026LVzWsMAzHZzd6+vSJ+ZDUEwB+ZIVt2gUVq6HTHaQXC1iubZM1osgvM/hgwzblSyT20ZLY"
    b"fo5nybxf0W+kbCLiM4riOOaSofjIT424vqMMFWPRAFTBT6YiffqMqrn907S1HOiszkv1LsjevU6F"
    b"Od1mG9wcP+Ezp5I+2UodF/mtBAD9gzJAjb+mCleCR95FWuwYOEmfI4iHjYRm9yMEgbRW1IEWJQSR"
    b"52TN1kd2muHBdTEJROgEGwTcudkNeHoAmy6wTs9gd8/dNHc0bfNswDWjjAN9+2HHnD3bfoYqTj0q"
    b"N7HSe6tyF7xh7rTIG3kLRHIVIDIUsiRTGLRPHT9BYybbsBOhzV+NWtThXOO6vln/GuXI4UdyW58+"
    b"An3huuIMBFkIa3J7ptxtd9nRPotCTuMWDKhspZK0WK8sO3NZLFmKbKxxCDFQr1IJTSodKjq9A1Fo"
    b"Om1hvI1A+dUpfRRiuTqTj0fiY0B/Up9/yHFOqAOh0OOX4myMMBTdJpWSLe+RRuc+yXSU87RYmCAF"
    b"DmA0ZStrnOZwBKNdZm/v6KQJOYIaHbfsWmPPAklRVZgg2sTqbDol5h6LJlbNqhmb+HeYVUus4j9k"
    b"Vvxvw1rEuyxDOSSY3KiRKc+rCsIrVoL/uHwJv5DI4tMpfnbgi8lYNZ3KHHxh7muuqonboNCK1czf"
    b"QBq+LGWiBf7eSSMNEHIoRR8Nk7rv+Ex6B5lr8H5NNBNRYj1luMQWEsruqJugT7gB6vnCoaZuHkL6"
    b"zfKCTKc+E2jmDOT2dHlb5sD7xdm7KWwprwvwKe5JJoyRx4YTvDQChAVh6rnJ4MjHg05mgAcQVSR4"
    b"IpI8bffMyXa+FPlIyTyWFApC2DK43mxRN8neqjh+J5rfSbvVpP40Dw4t53WEY4/iX1EmZQZ8DQcw"
    b"9ql97x1+7bXQ9DWmtchbJ/Z70kh1J5Nq5cVrJJbCZzvWSizl8jW5Gsv7J7EiPz3sLNhRI7OXKxea"
    b"k93OO9c91O3JbcNHXpZ2n52ipMWlbK10kNQZDnGvxsTa2ef/g4nx7q3Hh4PMc5xVqrbIJeF1cqJN"
    b"ApGE9vpwm9WLpEyIrpWTPp6SNK3vaxkOzhr9YFEb3wnS7jNSS7a1tQ1vKyxIu9PYaFIgoDpKgHVQ"
    b"ArhRwZeOJKBSZgyQLDE7E/uqrxJTnZXZcGiVn1vOGeI5mVUau4n51s2slwOn+fOBm5nbubqq62Q0"
    b"eU0JhzgzRp8Rnd8ysrl62cGbv+AmmN+kmLek0eriuffL1Nvktffjs9081uOvfw/e2uCrg72Ne/PT"
    b"bl7ayUcfxkNd/umRt3vyzN/HL9t5pSPmbzyMbekMWz73ovxZAfbViEdCTD8GuVpn1Zgrm2Ze0J2t"
    b"CDdRt95tkVpDc03fS3+dw7A43NTmecM/bYo4CvOGvs+oI2tkpm/zxcU0G51dpxQkh2I//xftqRjn"
    b"pHNKOBFPSLhhoKItzgMn46ZubHIO1THf7PshXpx21v0oTCLz+RYNygUg9eSFfomuUYi5510dh745"
    b"UHZ9fFhR4tQQC+xXkUVOHW+N/XpEEakUdtetyUtPFRhRvCWiBafilhx+oVA63gn2oaFfCsZ/525n"
    b"x7xxJ+bBVeidvYE/WO1WQDFoqqwjBE3hrdeM+koppG0kC4WO0pux+hGTcK1vV9X6OvpmW1d9eLAa"
    b"9rOz/fS5iTr0rg95pZHPvUnycTVJrlO2R9sTj3s71FTG8kqOcGgzXXPOEOfdAiCKzt+bBllskhH5"
    b"ogHAiz9jhVeilsithvc3t5G4lk2AAqKDAvrCaDEnmRKdjugt2LF1rVFRDYxs8mlKfjfvtLhOc3wn"
    b"zroPqHGhl5VDF4eRWrubtMwuM/RpZRtc87UG9ZcIdUun08L4I4hRAD9iRwOQF4pLad+HM6rN+zZL"
    b"pzKVG1rEX5URn7fbfCtmuz7d4aI1M3muncXToyy7rWSFwddK+Kmzeaod4INCu8CoyQdtd+Uxe7Kt"
    b"O2WysBs9NioCbwbdVdD+CBzQbNdsmfogH1eY446Ra4GCBZzWv8mTdm/9wyTRhw8B46AOoXW5NvXc"
    b"4NoatoFjhK93WPsU3wYip4N+6x7xvOT5o5gwid92gIOWZ0oCh5YOKnFLXjhtEbdHVTUV6/Nl7n9D"
    b"zlWjohyz4P8RUKA/H6mXv7zLXObfzXNXkTN2Oj6Qb89jK1YN+8QcHaWM8nLK+cP0D0q1L7OFYD8D"
    b"aVOUT9pT6AlBSItiq9Mfi3dbnDK04UUo8yfoyxocDL8tTS8sRn18D2DQM6EmFlarmwjNy0dRSPwz"
    b"+uoLQi5F4EnLFSqhxCi2ipxIpczm/94a6fu7J6rH1/ZsMyhVWV2URDto4pVmbnj1kornq2yGDlui"
    b"jwuJYzjuZlH4yHpJq+nJe8xKTk6rbObGbyYHLX+yeGmBGwQQn0fFiZwwiFYaTFP2/eVwvTcKsJkl"
    b"XD3L3FWtbx9j5iG33Z57k438qYrnqOb0HMPx4Y9Hh385fH12fPh2/6cT7VC7ofwOSFvlRj/Bn5+R"
    b"jsq//eThlBpLxXZaavzLAkikohprdMhjNv2JP2PRktLsvA5b8ZkOYgs6a5dd0/pSDJmic3C1lrRm"
    b"JhTbQNgcBN2PMYVfQwnWEdHU4TabRgsyAfopc8PVX0aPd4AF49q23bn9jlc91nBztc+YGH8f/XzA"
    b"Gp5sgbdooiN8pwg2C9luhRRe3eOBLAIEz5J8ew92kV5i1lv3MZc9qJBVUo/nnOA6FXgG0hFyQsQa"
    b"YpNI2R70vEo7uSSPpgaxHBqJXbz5h46XgjTCftq/cOewKaBUn7iqyd24iQy5kbLavJDse8moyXUL"
    b"SZ3EOmrTP5w0NDLQwNh5BVMN8DR2czAWZNsfwGaj9ODvAq5jbBpv4+iG3NcN3Dce/Wci3UJteGp9"
    b"F9K8ohISqlry7X3qKTfYoeH3QhhqruJgrXVQbaodC1gw1YH5S3pxfHpAznTt1wGslo0CFj87Nno+"
    b"mrESL8kZPQetFWHc69RVv/uDDpdeOoa+R6/MLudza/VMhcpg7Gaia3B25ht3LBV5nrTNukomdnoQ"
    b"4v9qT1JDYJUrdtiTNEBsmdLTgxhY/cGPfrkvhzjuwULmB60TdDMkD99bFbYv/c06tFYPwirL2trs"
    b"+zIINVkhdFglkga7WVbNyAuuS/Zex4lbPahnlSwn6TzbSHgjWG/HhNrAkFNOkU5j4PshO8+H+nTf"
    b"zwFyLR9gnb/Zmsv5S4szMBd+AKZKOApEJR8nOV6FjMo75BgRnzArKGimq3O4+FqlYD8BMR5LsUzv"
    b"j3DQm8+PxrvR+w8np8dn+x8/nh29ls/CVNUtEGDHfnIt8Q8hYGquj6cSCg8aTsLaqRf9dj2J+PPQ"
    b"cZnjBRmBROFLziz0SujbpMw/5MdC6LOveOjHWISfQja6nqZHo+aY65EesTihwEry9FgXGY1kGXg/"
    b"z5qz5AIXuWPt3I36MPmkvKpI3uiwh2owO8KJBlF89R0sJT+dJnpDjKPDvGtixQJ+F45PhGsFbSuK"
    b"+dggW+RfHaDKeIqwahCxEH00eWoz1KznHNfhIhk6iqKs3fMW6Y89oPaf831255Z+k3hDrG7S9RyZ"
    b"KMYVkK+0j1lwtwfLQXzuNNbmPeJcxj3UQZ34i5CG1TPUzmvYX5YdPmXqaWLbhB2IsFTEWfWRD750"
    b"vGowE0ZublM9daHohZvwpPkAsuhqBvjO3/tkZDbAWzc7Pfn6kftOckcL4jEp0YY3iLjI3/HDOiiL"
    b"q5tF9Xh741ZWfZdo797gd7lBK5OFGDCTDDzIkbnf8no0eLNKP1mhoUTRpjyFLd+t/VMANEnDpiEN"
    b"LWCNOxUjqdhjzezstizovmOlZqepOj57TJVWPXfc5XfuvXvN3WigdmqlXTlAwZ+E1B+3bE9E6Ziv"
    b"XosNzajlXcvVRKL1CsxdgVbHnaj5/Cs661wsapKcld5jxnu/52BBSGk8BdvyDKz1VhhGp8f7708+"
    b"fjg+PXt9uP/67dH7Q+cNpIHj8/X/wwoqW7ZdJTSp6WV0OZB6jS3j8J+kLPUjbPy4ZNsDuqGXioNr"
    b"9+7w9dH+inULcNUwP0WTlsc9dXyLhXmfXhV1lhDHTbS+fHL6w/utIp/eSc256bkV3cdG1E1O6Xnx"
    b"VnoqKFPXE4bBB4Va/fWFfWDiue6rB4zX89wPNNsUW7r8BD1Pn5YVUg85AbvTHmv6Ok+bDwf/ODbU"
    b"sgEORwolCJcxZVJq+7SGy0/YvedGZQt3niOR3agggZ1gmY0NYOebEIzwodls9a4JVZSKebtuH6zq"
    b"+9psdvjaGK7svd/Z7toYOoFkwOu2A7VJpj5rbKXd61NufzLt3LzNg/V9wecMdXLlr6itpFYz0wb2"
    b"euIb2c0Lmw8i4npph9Eb0NTx/fg3nUR8/RsUBSuWmnwjQULtO96ba91t6hOIWqlUZNaqvOJy975h"
    b"q207vE6sbasdJmTVdd/0Bt7J+7jP0Tf4KN60di4wktzN9Nly28ThOz3h3zFK8pukWrvq1i9ObZhj"
    b"un5dhO51Z7ZyK1Aax4FJq8nzjnlH3gKGC1eW5HaNcQCUswR0cZjcDrC63wv2TTZyXNrA/RwvnC3Y"
    b"VPV+KdH7zrQuP2rUQ33234+zYlGZ8OGUR7urmh3KZyB2mxM3gfWAWbvRkx1jrqFkk5gOy4hLKBZf"
    b"lShBYfTxJKutsRrJiim6mAJgz3Emxv0K3O+iMZzpScmX32RD5XVVhCcX4RgpUqFRTA8E//sxS6yU"
    b"d6eeJED6MHWnIXo6eQgFiTZShLWP51RSTjg38BPd0vGxUTGs9NdRmo4rQhkkR5SwEoakw3vjyMxr"
    b"VMzvoqzeg/+ThQYPc11Cywl5Y69MaVVhQ1veqTPIIq8m8uQmu8J4v5jqePcYocsVgnMIgkiXMhPf"
    b"jwltRCx2d1/Nq8yHHm9rSWbzkddv/8uinOq3weVQBYavxkGuqLasmqSp1oHi6ANjZcpLNW5Hyp7D"
    b"IBz+0Ow48qJbOIk0LuH+BWhgZKGyjijqjMB5HqV0d0cytsBG1MAA+fhGPBLJwI2HimpCX/4dIE46"
    b"MoJsLoMNw+Q8PcNAwndyjDjyUu5Bnh5R71VZXKflFFPfdZL0Ff5PyireW+/y42OZzhO6RlO3arwE"
    b"4gbkXxPMv4cQZpmsZnh0cKjFqXlZjBcjzpyiV9LehaBzE/dwYCRaF7P90pD/Hb2/wwv+AWWv78vk"
    b"ihJANS39l6roIbZaKaLwsHAAKJp5Y4zxDlJ6BzBjCQ2ds984VOZLY9S7jR5MEkRS/+z99y75WLx0"
    b"gkdooJzRZD7a829B8M4cT+quiCnuUBfIy8fWPQDxOUdOOOIfTeuMGjkXu5cAqo4fLt008klru9Me"
    b"Bk7zLwuqW23euAeTjRh9p/lUfChYtr119Zg7RvHd0JlbcXWjeAUBk4dvyxNV/E+rX7+t7zjzvwy9"
    b"HuNc4fhL7KbDCucAoSACfu1K9OuF7rZkyuJ/Hj2K9mEPp5g4E1Ux3XSklg9vG7KqmJJxBB8AVmY1"
    b"8zL1igDerh1yY2zbbX4s5eT4IvZY07+GAUjY6FpySdz3Cogt4UoGRa+X1dbwQGYBedxNW5JmOTKL"
    b"hrGecCENqM1PLmBZ1DkfFcuUz5FjohOQMZnZKqniFWzpEDlDrkVcI0ysEnTX8iDochXzzqRYOXE9"
    b"6hirDMT6fl1evfv4eK1d1fH3si9fupczD/X0WuHrpcVhY693D/y6dvxOI7zEK2uIN0vGtvhu63uv"
    b"4yJ3Pcu6JDdhBze7V4NQVqR7IFq3Q1w7Gg7ujTzSSa4NcwI2bJ866hhS9KFT5DFsuRZDepgr3Yom"
    b"1nSqC6siD5EDg9l0rdxjg8YthZf7t4rEL9dz0nrnur5p7FHF4aQBmuHC1HznB3wNfjV17VB+ZIbZ"
    b"wLKpvAbslOIu9Nf80ovzTV1Nr87JKzLMrhkqZbZPxzuJXL7qKR6Tz9cLYmpP+7tWwl8v6eo/Kamq"
    b"zrF5r+SqyjjkJp1elWbayVrsKMPrNJmj7TbclnR2bZiuHEgn063BWGkmt2zIeswGkoX7r083whZC"
    b"lV5GVvo+Od1/6/IVgUyB7F7a7NhMSI5RyhzMP0vuVMzARarSf8mzGUWLOQYQELAOytnbWA45mnFv"
    b"Y4NvQ0NicjYCXPJj/6EKstJXixqmfq9qlLx8ZT2d4hwq3NPcF0ploZsla4dnx9vo6gItkqt7sLMl"
    b"+mfxiAmUtnE/wP6+tyFTQP4zbIUwlflFkZTj+LbM6tQ+ArzSNHgQMpDBAmbGOAgdrbYHnq0yCPbI"
    b"JKftc/z0Dcl2ozZTHfl0aRPdutstry1WIZW/7/fdeacvs/FtW/97Nz+U6np9BOhAAViT4+RWXLqp"
    b"9WckINZDObBRGGcPcRQ55gmsqXUm6q3Isb0uRjiIoFs3JkcZ+TmQ2fGRdX+EYa0QWgKSXld+UNIR"
    b"RHLQ5cZtlo+L2wAtwTWZADEGcmIGAzVa4dmyuqBs9F4d7tU+FfB/AVc5/UY="
)).decode("utf-8")
# END GENERATED BROWSER ASSETS

THIRD_PARTY_BROWSER_LICENSES = (
    b"Browser asset provenance\n========================\n"
    + BROWSER_PROVENANCE
    + b"\n\nRuntime browser derivatives\n===========================\n"
    + b"The served PeerJS and QRious runtime files are the pinned upstream "
    + b"minified distributions with their trailing sourceMappingURL comments "
    + b"removed and final newlines normalized. Their SHA-256 digests are "
    + b"95f57b9e94e1b96c829145b3f3ef0d04b332c9bda0567e144bed70d13712e3d0 "
    + b"and "
    + b"c46f564908ff10943a59e6f56f5de4bc5b6e827813b4750eef55353e7085157c.\n"
    + b"The served Trystero Nostr IIFE is a deterministic self-contained "
    + b"bundle with SHA-256 "
    + TRYSTERO_NOSTR_RUNTIME_SHA256_BYTES
    + b".\n"
    + b"\n\nTrystero bundle build provenance\n"
    + b"================================\n"
    + TRYSTERO_BUILD_PROVENANCE
    + b"\n\nReviewed Nostr relay policy\n"
    + b"===========================\n"
    + NOSTR_RELAY_POLICY
    + b"\n\n@trystero-p2p/nostr 0.25.3\n"
    + b"================================\n"
    + TRYSTERO_LICENSE
    + b"\n\n@trystero-p2p/core 0.25.3\n"
    + b"===============================\n"
    + TRYSTERO_CORE_LICENSE
    + b"\n\n@noble/secp256k1 3.1.0\n"
    + b"===========================\n"
    + NOBLE_SECP256K1_LICENSE
    + b"\n\nPeerJS 1.5.5\n==============\n"
    + PEERJS_LICENSE
    + b"\n\neventemitter3 4.0.7 (bundled by PeerJS)\n"
    + b"========================================\n"
    + EVENTEMITTER3_LICENSE
    + b"\n\npeerjs-js-binarypack 2.1.0 (bundled by PeerJS)\n"
    + b"=================================================\n"
    + BINARYPACK_LICENSE
    + b"\n\nwebrtc-adapter 9.0.1 (bundled by PeerJS)\n"
    + b"===========================================\n"
    + WEBRTC_ADAPTER_LICENSE
    + b"\n\nsdp 3.2.0 (bundled by webrtc-adapter)\n"
    + b"=======================================\n"
    + SDP_LICENSE
    + b"\n\nQRious 4.0.2 upstream notice\n=============================\n"
    + b"Unminified distribution retained as "
    + b"vendor/browser/qrious-4.0.2.js in the source repository.\n\n"
    + QRIOUS_LICENSE
    + b"\n\nGNU General Public License version 3\n"
    + b"====================================\n"
    + QRIOUS_GPL_TERMS
)


MAP_NAMES = {
    0x00: "Pallet Town",
    0x01: "Viridian City",
    0x02: "Pewter City",
    0x03: "Cerulean City",
    0x04: "Lavender Town",
    0x05: "Vermilion City",
    0x06: "Celadon City",
    0x07: "Fuchsia City",
    0x08: "Cinnabar Island",
    0x09: "Indigo Plateau",
    0x0A: "Saffron City",
    0x0C: "Route 1",
    0x0D: "Route 2",
    0x0E: "Route 3",
    0x0F: "Route 4",
    0x10: "Route 5",
    0x11: "Route 6",
    0x12: "Route 7",
    0x13: "Route 8",
    0x14: "Route 9",
    0x15: "Route 10",
    0x16: "Route 11",
    0x17: "Route 12",
    0x18: "Route 13",
    0x19: "Route 14",
    0x1A: "Route 15",
    0x1B: "Route 16",
    0x1C: "Route 17",
    0x1D: "Route 18",
    0x1E: "Route 19",
    0x1F: "Route 20",
    0x20: "Route 21",
    0x21: "Route 22",
    0x22: "Route 23",
    0x23: "Route 24",
    0x24: "Route 25",
    0x25: "Player's House 1F",
    0x26: "Player's House 2F",
    0x27: "Rival's House",
    0x28: "Oak's Lab",
    0x29: "Viridian Pokemon Center",
    0x2A: "Viridian Mart",
    0x2D: "Viridian Gym",
    0x33: "Viridian Forest",
    0x36: "Pewter Gym",
    0x3A: "Pewter Pokemon Center",
    0x3B: "Mt. Moon 1F",
    0x3C: "Mt. Moon B1F",
    0x3D: "Mt. Moon B2F",
    0x40: "Cerulean Pokemon Center",
    0x41: "Cerulean Gym",
    0x44: "Mt. Moon Pokemon Center",
    0x52: "Rock Tunnel 1F",
    0x53: "Power Plant",
    0x58: "Bill's House",
    0x59: "Vermilion Pokemon Center",
    0x5C: "Vermilion Gym",
    0x5E: "Vermilion Dock",
    0x5F: "S.S. Anne 1F",
    0x60: "S.S. Anne 2F",
    0x61: "S.S. Anne 3F",
    0x62: "S.S. Anne B1F",
    0x65: "S.S. Anne Captain's Room",
    0x6C: "Victory Road 1F",
    0x71: "Lance",
    0x76: "Hall of Fame",
    0x78: "Champion's Room",
    0x85: "Celadon Pokemon Center",
    0x86: "Celadon Gym",
    0x87: "Game Corner",
    0x8D: "Lavender Pokemon Center",
    0x8E: "Pokemon Tower 1F",
    0x8F: "Pokemon Tower 2F",
    0x90: "Pokemon Tower 3F",
    0x91: "Pokemon Tower 4F",
    0x92: "Pokemon Tower 5F",
    0x93: "Pokemon Tower 6F",
    0x94: "Pokemon Tower 7F",
    0x9A: "Fuchsia Pokemon Center",
    0x9C: "Safari Zone Entrance",
    0x9D: "Fuchsia Gym",
    0xA5: "Pokemon Mansion 1F",
    0xA6: "Cinnabar Gym",
    0xAB: "Cinnabar Pokemon Center",
    0xAE: "Indigo Plateau Lobby",
    0xB2: "Saffron Gym",
    0xB5: "Silph Co. 1F",
    0xB6: "Saffron Pokemon Center",
    0xC0: "Seafoam Islands 1F",
    0xC2: "Victory Road 2F",
    0xC5: "Diglett's Cave",
    0xC6: "Victory Road 3F",
    0xC7: "Rocket Hideout B1F",
    0xC8: "Rocket Hideout B2F",
    0xC9: "Rocket Hideout B3F",
    0xCA: "Rocket Hideout B4F",
    0xCF: "Silph Co. 2F",
    0xD0: "Silph Co. 3F",
    0xD1: "Silph Co. 4F",
    0xD2: "Silph Co. 5F",
    0xD3: "Silph Co. 6F",
    0xD4: "Silph Co. 7F",
    0xD5: "Silph Co. 8F",
    0xD9: "Safari Zone East",
    0xDA: "Safari Zone North",
    0xDB: "Safari Zone West",
    0xDC: "Safari Zone Center",
    0xE8: "Rock Tunnel B1F",
    0xE9: "Silph Co. 9F",
    0xEA: "Silph Co. 10F",
    0xEB: "Silph Co. 11F",
    0xF5: "Lorelei",
    0xF6: "Bruno",
    0xF7: "Agatha",
}


VIEWER_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Copilot Plays Pokemon Red</title>
<link rel="stylesheet" href="/viewer.css">
</head>
<body>
<main>
<header>
  <div>
    <h1>Copilot Plays Pokemon Red</h1>
    <p>Authenticated local host. Manual buttons temporarily take priority.</p>
  </div>
  <span id="live-badge" class="badge offline">OFFLINE</span>
</header>
<div class="grid">
  <section class="card">
    <canvas id="game" width="160" height="144" aria-label="Pokemon Red live frame"></canvas>
    <video id="pip-video" autoplay muted playsinline aria-hidden="true"></video>
    <div class="controls">
      <button data-action="manual">Take Over</button>
      <button data-action="autonomy">Return to AI</button>
      <button class="alt" data-action="pause">Pause</button>
      <button class="alt" data-action="resume">Resume</button>
      <button data-action="checkpoint">Save + New Clip</button>
      <button id="pip-toggle" class="alt" type="button" disabled>Picture in Picture</button>
      <button id="stop-runtime" class="warn" data-action="stop">Stop</button>
    </div>
    <p id="pip-status" class="note" role="status" aria-live="polite">Picture in Picture is available while the livestream is active.</p>
  </section>
  <section class="card">
    <section id="livestream" hidden>
      <div class="stream-heading">
        <h2>Peer-to-peer livestream</h2>
        <strong id="stream-state">Offline</strong>
      </div>
      <p><span id="viewer-count">0</span> / <span id="viewer-limit">0</span> viewers</p>
      <div class="share">
        <canvas id="stream-qr" width="220" height="220" aria-label="Spectator join QR code"></canvas>
        <div>
          <a id="join-link" target="_blank" rel="noopener noreferrer">Open spectator page</a>
          <button id="copy-link" class="alt" type="button">Copy join link</button>
        </div>
      </div>
      <div class="controls">
        <button id="go-live" type="button">Go Live</button>
        <button id="end-live" class="warn" type="button">End</button>
        <button id="retry-live" class="alt" type="button">Retry</button>
      </div>
      <p id="stream-message" class="note" role="status" aria-live="polite" aria-atomic="true">Livestream is offline.</p>
      <p class="note">Anyone with this bearer link can watch. Media is sent directly with WebRTC.</p>
      <p class="note"><strong>Keep this stream window open.</strong> Background tabs are tolerated; use Picture in Picture to keep the game visible while working elsewhere.</p>
      <a class="note" href="/vendor/licenses.txt" target="_blank" rel="noopener">Third-party notices</a>
    </section>
    <div class="dpad">
      <span></span><button data-button="up">Up</button><span></span>
      <button data-button="left">Left</button><button data-button="a">A</button><button data-button="right">Right</button>
      <button data-button="b">B</button><button data-button="down">Down</button><button data-button="start">Start</button>
    </div>
    <div class="center"><button data-button="select">Select</button></div>
    <pre id="status">Connecting...</pre>
  </section>
</div>
<section class="card spaced clips">
  <h2>Saved clips</h2>
  <div id="clips"></div>
</section>
</main>
<script src="/vendor/peerjs.min.js" defer></script>
<script src="/vendor/qrious.min.js" defer></script>
<script src="/viewer.js" defer></script>
</body>
</html>
"""


VIEWER_CSS = """
:root { color-scheme: dark; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
body { margin: 0; background: #10141f; color: #eef3ff; }
main { max-width: 1050px; margin: auto; padding: 20px; }
header { display: flex; align-items: start; justify-content: space-between; gap: 18px; }
h1 { color: #ffdf4d; margin: 0 0 8px; }
h2 { margin: 0; font-size: 1rem; }
.grid { display: grid; grid-template-columns: minmax(320px, 2fr) minmax(280px, 1fr); gap: 18px; }
.card { background: #192235; border: 1px solid #34445f; border-radius: 12px; padding: 16px; }
#game { width: 100%; max-width: 640px; image-rendering: pixelated; background: black; aspect-ratio: 10 / 9; }
#pip-video { position: fixed; right: 0; bottom: 0; width: 2px; height: 2px; opacity: .01; pointer-events: none; }
#status { white-space: pre-wrap; overflow-wrap: anywhere; min-height: 250px; }
button { background: #2c6bed; color: white; border: 0; border-radius: 6px; padding: 10px 14px; margin: 3px; cursor: pointer; }
button:focus-visible, a:focus-visible { outline: 3px solid #ffdf4d; outline-offset: 2px; }
button:disabled { cursor: not-allowed; opacity: .45; }
button.alt { background: #59677f; }
button.warn { background: #bd3d45; }
.dpad { display: grid; grid-template-columns: repeat(3, 55px); justify-content: center; }
.clips a { color: #8fc5ff; display: block; margin: 6px 0; }
.controls { margin-top: 10px; }
.center { text-align: center; }
.spaced { margin-top: 18px; }
.badge { border-radius: 999px; font-weight: 800; padding: 7px 11px; }
.badge.live { background: #df2538; color: white; }
.badge.connecting { background: #d99d27; color: #111; }
.badge.offline { background: #59677f; }
.stream-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.share { display: grid; grid-template-columns: 140px 1fr; align-items: center; gap: 12px; }
#stream-qr { width: 140px; height: 140px; background: white; border-radius: 8px; }
#join-link { color: #8fc5ff; display: block; overflow-wrap: anywhere; margin-bottom: 8px; }
.note { color: #afbdd2; font-size: .82rem; overflow-wrap: anywhere; }
@media (max-width: 760px) {
  .grid { grid-template-columns: 1fr; }
  header { align-items: center; }
  .share { grid-template-columns: 110px 1fr; }
  #stream-qr { width: 110px; height: 110px; }
}
"""


VIEWER_JS = """
const game = document.getElementById('game');
const gameContext = game.getContext('2d', {alpha: false});
gameContext.imageSmoothingEnabled = false;
let frameLoading = false;
let statusRefreshInFlight = false;

function refreshFrame() {
  if (frameLoading) return;
  frameLoading = true;
  const frame = new Image();
  frame.onload = () => {
    gameContext.imageSmoothingEnabled = false;
    gameContext.drawImage(frame, 0, 0, game.width, game.height);
    frameLoading = false;
  };
  frame.onerror = () => { frameLoading = false; };
  frame.src = '/frame.png?t=' + Date.now();
}

async function control(action, button) {
  const response = await fetch('/api/control', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({action, button})
  });
  if (!response.ok) throw new Error(`control failed: ${response.status}`);
}
function press(button) { return control('press', button); }
document.querySelectorAll('[data-action]').forEach(
  element => element.addEventListener('click', async () => {
    const action = element.dataset.action;
    if (action === 'stop') {
      teardownBroadcast('Runtime stop requested.', 'offline', true);
    }
    try {
      await control(action);
    } catch (error) {
      document.getElementById('status').textContent = 'Control failed: ' + error;
    }
  })
);
document.querySelectorAll('[data-button]').forEach(
  element => element.addEventListener('click', () => {
    press(element.dataset.button).catch(error => {
      document.getElementById('status').textContent = 'Control failed: ' + error;
    });
  })
);

async function refreshStatus() {
  if (statusRefreshInFlight) return;
  statusRefreshInFlight = true;
  try {
    const response = await fetch('/api/status?t=' + Date.now());
    if (!response.ok) throw new Error(`status failed: ${response.status}`);
    const data = await response.json();
    noteBackendSuccess();
    noteCoreControlSuccess('status');
    if (broadcast.config) {
      const reportedGeneration = data.livestream && data.livestream.generation;
      const generationChanged = (
        reportedGeneration &&
        reportedGeneration !== broadcast.config.generation
      );
      const terminal = (
        data.running === false ||
        ['stopped', 'failed'].includes(data.lifecycle)
      );
      if (generationChanged || terminal) {
        teardownBroadcast(
          generationChanged
            ? 'The runtime restarted; open its new stream window.'
            : 'The runtime has stopped.',
          'offline',
          false
        );
      }
    }
    const view = {
      lifecycle: data.lifecycle, running: data.running, control: data.control_mode,
      paused: data.paused, brain: data.brain_status,
      location: data.game_state && data.game_state.location,
      coordinates: data.game_state && data.game_state.coordinates,
      badges: data.game_state && data.game_state.badges,
      party: data.game_state && data.game_state.party,
      phase: data.phase, objective: data.objective, observation: data.observation,
      reason: data.reason,
      last_action: data.last_action, model_calls: data.model_calls,
      current_clip: data.current_clip, last_error: data.last_error
    };
    document.getElementById('status').textContent = JSON.stringify(view, null, 2);
    const clips = document.getElementById('clips');
    clips.replaceChildren();
    for (const clip of data.clips || []) {
      const link = document.createElement('a');
      link.href = '/clips/' + encodeURIComponent(clip.name);
      link.target = '_blank';
      link.rel = 'noopener';
      link.textContent = `${clip.name} (${clip.megabytes} MB)`;
      clips.appendChild(link);
    }
    if (!clips.childElementCount) clips.textContent = 'No completed clips yet.';
  } catch (error) {
    noteCoreControlFailure(
      'status',
      'The local runtime status channel is repeatedly unavailable.'
    );
    document.getElementById('status').textContent = 'Viewer disconnected: ' + error;
  } finally {
    statusRefreshInFlight = false;
  }
}

const broadcast = {
  config: null,
  peer: null,
  stream: null,
  viewers: new Map(),
  negotiating: new Map(),
  owner: createOwnerId(),
  lease: null,
  heartbeatTimer: null,
  heartbeatInFlight: false,
  reconnectTimer: null,
  leaseRecoveryTimer: null,
  leaseRecoveryInFlight: false,
  leaseRecoveryAttempts: 0,
  leaseRecoveryPending: false,
  leaseRecoveryDeadlineAt: null,
  backendFailures: 0,
  coreStatusFailures: 0,
  coreLeaseFailures: 0,
  starting: false,
  pageEnding: false,
  manuallyStopped: false,
  state: 'offline',
  telemetrySequence: 0
};
let streamStateUpdate = Promise.resolve();
const dashboardCache = {
  snapshot: null,
  serialized: '',
  inFlight: false,
  available: false,
  lastSuccessAt: null
};

function monotonicNow() {
  if (globalThis.performance && typeof globalThis.performance.now === 'function') {
    return globalThis.performance.now();
  }
  return 0;
}

function hasExactKeys(value, keys) {
  return (
    value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join(',') === [...keys].sort().join(',')
  );
}

function boundedInteger(value, minimum, maximum) {
  return Number.isInteger(value) && value >= minimum && value <= maximum;
}

function boundedText(value, maximum) {
  return value === null || (
    typeof value === 'string' && Array.from(value).length <= maximum
  );
}

function validDashboardSnapshot(value) {
  if (!hasExactKeys(value, [
    'location', 'objective', 'phase', 'badges', 'pokedex', 'party',
    'completed', 'player', 'play_time', 'session_elapsed_seconds',
    'checkpoint', 'viewers'
  ])) return false;
  if (
    !boundedText(value.location, 80) ||
    !boundedText(value.objective, 160) ||
    !boundedText(value.phase, 40) ||
    typeof value.completed !== 'boolean'
  ) return false;
  if (!hasExactKeys(value.badges, ['earned', 'count', 'total'])) return false;
  const badgeNames = [
    'Boulder', 'Cascade', 'Thunder', 'Rainbow',
    'Soul', 'Marsh', 'Volcano', 'Earth'
  ];
  if (
    !Array.isArray(value.badges.earned) ||
    value.badges.earned.some(name => !badgeNames.includes(name)) ||
    new Set(value.badges.earned).size !== value.badges.earned.length ||
    !(
      value.badges.count === null ||
      value.badges.count === value.badges.earned.length
    ) ||
    (value.badges.count === null && value.badges.earned.length !== 0) ||
    value.badges.total !== 8
  ) return false;
  if (!hasExactKeys(value.pokedex, ['caught', 'seen', 'total'])) return false;
  if (
    !(value.pokedex.caught === null ||
      boundedInteger(value.pokedex.caught, 0, 151)) ||
    !(value.pokedex.seen === null ||
      boundedInteger(value.pokedex.seen, 0, 151)) ||
    value.pokedex.total !== 151
  ) return false;
  if (!(value.party === null || (
    Array.isArray(value.party) && value.party.length <= 6
  ))) return false;
  for (const member of value.party || []) {
    if (!hasExactKeys(member, ['nickname', 'species_id', 'level', 'hp', 'max_hp'])) {
      return false;
    }
    if (
      !boundedText(member.nickname, 24) ||
      !(member.species_id === null || boundedInteger(member.species_id, 1, 255)) ||
      !(member.level === null || boundedInteger(member.level, 1, 100)) ||
      !(member.hp === null || boundedInteger(member.hp, 0, 65535)) ||
      !(member.max_hp === null || boundedInteger(member.max_hp, 1, 65535)) ||
      (
        member.hp !== null &&
        member.max_hp !== null &&
        member.hp > member.max_hp
      )
    ) return false;
  }
  if (!hasExactKeys(value.player, ['mode', 'paused'])) return false;
  if (
    !['ai', 'manual', 'paused', 'unknown'].includes(value.player.mode) ||
    typeof value.player.paused !== 'boolean'
  ) return false;
  if (value.play_time !== null) {
    if (!hasExactKeys(
      value.play_time,
      ['hours', 'minutes', 'seconds', 'frames', 'maxed']
    )) return false;
    if (
      !boundedInteger(value.play_time.hours, 0, 255) ||
      !boundedInteger(value.play_time.minutes, 0, 59) ||
      !boundedInteger(value.play_time.seconds, 0, 59) ||
      !boundedInteger(value.play_time.frames, 0, 59) ||
      typeof value.play_time.maxed !== 'boolean'
    ) return false;
  }
  if (
    !(value.session_elapsed_seconds === null ||
      boundedInteger(value.session_elapsed_seconds, 0, 316224000))
  ) return false;
  if (value.checkpoint !== null) {
    if (!hasExactKeys(
      value.checkpoint,
      ['timestamp', 'kind', 'location', 'age_seconds']
    )) return false;
    if (
      typeof value.checkpoint.timestamp !== 'string' ||
      value.checkpoint.timestamp.length > 48 ||
      !Number.isFinite(Date.parse(value.checkpoint.timestamp)) ||
      ![
        'manual', 'milestone', 'automatic', 'shutdown',
        'recovery', 'progress', 'other'
      ].includes(value.checkpoint.kind) ||
      !boundedText(value.checkpoint.location, 80) ||
      !(value.checkpoint.age_seconds === null ||
        boundedInteger(value.checkpoint.age_seconds, 0, 316224000))
    ) return false;
  }
  return (
    hasExactKeys(value.viewers, ['count', 'capacity']) &&
    boundedInteger(value.viewers.count, 0, 8) &&
    boundedInteger(value.viewers.capacity, 0, 8) &&
    value.viewers.count <= value.viewers.capacity
  );
}

async function refreshDashboard() {
  if (dashboardCache.inFlight) return;
  dashboardCache.inFlight = true;
  try {
    const response = await fetch('/api/dashboard?t=' + Date.now());
    if (!response.ok) throw new Error(`dashboard failed: ${response.status}`);
    const snapshot = await response.json();
    if (!validDashboardSnapshot(snapshot)) {
      throw new Error('dashboard schema mismatch');
    }
    const serialized = JSON.stringify(snapshot);
    const maximum = Math.min(4096, Math.max(
      512,
      Number(broadcast.config && broadcast.config.max_telemetry_bytes) || 4096
    ));
    if (new TextEncoder().encode(serialized).byteLength > maximum) {
      throw new Error('dashboard snapshot too large');
    }
    dashboardCache.snapshot = snapshot;
    dashboardCache.serialized = serialized;
    dashboardCache.available = true;
    dashboardCache.lastSuccessAt = monotonicNow();
    fanoutTelemetry();
  } catch (_error) {
    dashboardCache.available = false;
    // Dashboard details may become stale; video and gameplay continue.
  } finally {
    dashboardCache.inFlight = false;
  }
}

function viewerDashboardSnapshot() {
  if (!dashboardCache.snapshot || !broadcast.config) return null;
  const snapshot = JSON.parse(dashboardCache.serialized);
  snapshot.viewers = {
    count: broadcast.viewers.size,
    capacity: broadcast.config.max_viewers
  };
  return snapshot;
}

function connectionIsBackpressured(connection) {
  const maximum = Math.min(4096, Math.max(
    512,
    Number(broadcast.config && broadcast.config.max_telemetry_bytes) || 4096
  ));
  const peerBuffer = Number(connection && connection.bufferSize) || 0;
  const rtcBuffer = Number(
    connection &&
    connection.dataChannel &&
    connection.dataChannel.bufferedAmount
  ) || 0;
  return Math.max(peerBuffer, rtcBuffer) > maximum * 2;
}

function sendTelemetryToViewer(peerId, force = false) {
  const entry = broadcast.viewers.get(peerId);
  if (!entry || !entry.connection || !entry.connection.open) return;
  const now = monotonicNow();
  const heartbeatSeconds = Math.max(
    4,
    Number(broadcast.config.telemetry_heartbeat_seconds) || 5
  );
  const staleSeconds = Math.min(
    30,
    Math.max(8, Number(broadcast.config.telemetry_stale_seconds) || 12)
  );
  if (
    !dashboardCache.available ||
    dashboardCache.lastSuccessAt === null ||
    now - dashboardCache.lastSuccessAt > staleSeconds * 1000
  ) return;
  const snapshot = viewerDashboardSnapshot();
  if (!snapshot) return;
  const serialized = JSON.stringify(snapshot);
  const changed = serialized !== entry.telemetryHash;
  const changeSeconds = Math.max(
    1,
    Number(broadcast.config.telemetry_change_seconds) || 1
  );
  const elapsed = now - entry.telemetrySentAt;
  if (!force && changed && elapsed < changeSeconds * 1000) {
    entry.telemetryPending = true;
    return;
  }
  if (!force && !changed && elapsed < heartbeatSeconds * 1000) return;
  if (connectionIsBackpressured(entry.connection)) {
    entry.telemetryPending = true;
    return;
  }
  if (broadcast.telemetrySequence >= Number.MAX_SAFE_INTEGER) return;
  const sequence = broadcast.telemetrySequence + 1;
  const message = {
    v: broadcast.config.protocol_version,
    type: 'telemetry',
    telemetry_version: broadcast.config.telemetry_version || 1,
    sequence,
    snapshot
  };
  let bytes;
  try {
    bytes = new TextEncoder().encode(JSON.stringify(message)).byteLength;
  } catch (_error) {
    return;
  }
  const maximum = Math.min(4096, Math.max(
    512,
    Number(broadcast.config.max_telemetry_bytes) || 4096
  ));
  if (bytes > maximum) return;
  try {
    entry.connection.send(message);
  } catch (_error) {
    closeViewer(peerId);
    return;
  }
  broadcast.telemetrySequence = sequence;
  entry.telemetryHash = serialized;
  entry.telemetrySentAt = now;
  entry.telemetryPending = false;
}

function fanoutTelemetry(force = false) {
  for (const peerId of broadcast.viewers.keys()) {
    sendTelemetryToViewer(peerId, force);
  }
}

function createOwnerId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  if (globalThis.crypto && typeof globalThis.crypto.getRandomValues === 'function') {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(18));
    let raw = '';
    for (const byte of bytes) raw += String.fromCharCode(byte);
    return btoa(raw).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '');
  }
  return '';
}

function streamElements() {
  return {
    section: document.getElementById('livestream'),
    badge: document.getElementById('live-badge'),
    state: document.getElementById('stream-state'),
    message: document.getElementById('stream-message'),
    count: document.getElementById('viewer-count'),
    limit: document.getElementById('viewer-limit'),
    go: document.getElementById('go-live'),
    end: document.getElementById('end-live'),
    retry: document.getElementById('retry-live')
  };
}

const pipVideo = document.getElementById('pip-video');
const pipButton = document.getElementById('pip-toggle');
const pipStatus = document.getElementById('pip-status');
let pipFailureMessage = '';
let pipMetadataReady = false;

function standardPiPSupported() {
  return Boolean(
    document.pictureInPictureEnabled &&
    pipVideo &&
    typeof pipVideo.requestPictureInPicture === 'function'
  );
}

function safariPiPSupported() {
  return Boolean(
    pipVideo &&
    typeof pipVideo.webkitSupportsPresentationMode === 'function' &&
    pipVideo.webkitSupportsPresentationMode('picture-in-picture') &&
    typeof pipVideo.webkitSetPresentationMode === 'function'
  );
}

function pictureInPictureActive() {
  return Boolean(
    (standardPiPSupported() && document.pictureInPictureElement === pipVideo) ||
    (
      safariPiPSupported() &&
      pipVideo.webkitPresentationMode === 'picture-in-picture'
    )
  );
}

function pictureInPictureStreamReady() {
  const stream = broadcast.stream;
  if (
    !stream ||
    pipVideo.srcObject !== stream ||
    !pipMetadataReady ||
    Number(pipVideo.readyState) < 1
  ) {
    return false;
  }
  const tracks = typeof stream.getVideoTracks === 'function'
    ? stream.getVideoTracks()
    : stream.getTracks().filter(track => track.kind === 'video');
  return tracks.some(track => track.readyState === 'live');
}

function updatePictureInPicture() {
  const supported = standardPiPSupported() || safariPiPSupported();
  const active = pictureInPictureActive();
  const available = pictureInPictureStreamReady();
  pipButton.disabled = !supported || (!available && !active);
  pipButton.textContent = active
    ? 'Exit Picture in Picture'
    : 'Picture in Picture';
  if (!supported) {
    pipStatus.textContent = 'Picture in Picture is not supported by this browser.';
  } else if (active) {
    pipStatus.textContent = 'Picture in Picture is active.';
  } else if (pipFailureMessage && available) {
    pipStatus.textContent = pipFailureMessage;
  } else if (available) {
    pipStatus.textContent = 'Picture in Picture is ready.';
  } else {
    pipStatus.textContent =
      'Start the livestream to make Picture in Picture available.';
  }
}

function attachPictureInPictureStream(stream) {
  pipMetadataReady = false;
  pipVideo.srcObject = stream;
  for (const track of stream.getTracks()) {
    track.addEventListener('ended', updatePictureInPicture);
    track.addEventListener('mute', updatePictureInPicture);
    track.addEventListener('unmute', updatePictureInPicture);
  }
  if (typeof pipVideo.play === 'function') {
    try {
      const playback = pipVideo.play();
      if (playback && typeof playback.catch === 'function') {
        playback.catch(() => {});
      }
    } catch (_error) {
      // The button can retry playback through its user gesture.
    }
  }
  updatePictureInPicture();
}

function cleanupPictureInPicture() {
  if (
    standardPiPSupported() &&
    document.pictureInPictureElement === pipVideo &&
    typeof document.exitPictureInPicture === 'function'
  ) {
    try {
      const exit = document.exitPictureInPicture();
      if (exit && typeof exit.catch === 'function') exit.catch(() => {});
    } catch (_error) {
      // Continue detaching the ended capture stream.
    }
  }
  if (
    safariPiPSupported() &&
    pipVideo.webkitPresentationMode === 'picture-in-picture'
  ) {
    try {
      pipVideo.webkitSetPresentationMode('inline');
    } catch (_error) {
      // Continue detaching the ended capture stream.
    }
  }
  pipVideo.srcObject = null;
  pipMetadataReady = false;
  updatePictureInPicture();
}

function togglePictureInPicture() {
  const active = pictureInPictureActive();
  if (!active && !pictureInPictureStreamReady()) return;
  if (!active && typeof pipVideo.play === 'function') {
    try {
      const playback = pipVideo.play();
      if (playback && typeof playback.catch === 'function') {
        playback.catch(() => {
          if (!pictureInPictureActive()) {
            pipFailureMessage =
              'Picture in Picture could not start video playback. Try again.';
            updatePictureInPicture();
          }
        });
      }
    } catch (_error) {
      pipFailureMessage =
        'Picture in Picture could not start video playback. Try again.';
      updatePictureInPicture();
      return;
    }
  }
  if (standardPiPSupported()) {
    try {
      const request = active
        ? document.exitPictureInPicture()
        : pipVideo.requestPictureInPicture();
      if (request && typeof request.then === 'function') {
        request.then(() => {
          if (!active) pipFailureMessage = '';
          updatePictureInPicture();
        }).catch(() => {
          pipFailureMessage =
            'Picture in Picture could not be opened. Try again.';
          updatePictureInPicture();
        });
      } else {
        if (!active) pipFailureMessage = '';
        updatePictureInPicture();
      }
    } catch (_error) {
      pipFailureMessage = 'Picture in Picture could not be opened. Try again.';
      updatePictureInPicture();
    }
    return;
  }
  if (safariPiPSupported()) {
    try {
      pipVideo.webkitSetPresentationMode(
        active ? 'inline' : 'picture-in-picture'
      );
      if (!active && pictureInPictureActive()) pipFailureMessage = '';
      updatePictureInPicture();
    } catch (_error) {
      pipFailureMessage = 'Picture in Picture could not be opened. Try again.';
      updatePictureInPicture();
    }
  }
}

pipButton.addEventListener('click', togglePictureInPicture);
pipVideo.addEventListener('enterpictureinpicture', updatePictureInPicture);
pipVideo.addEventListener('leavepictureinpicture', updatePictureInPicture);
pipVideo.addEventListener('webkitpresentationmodechanged', updatePictureInPicture);
for (const eventName of ['loadedmetadata', 'canplay', 'playing']) {
  pipVideo.addEventListener(eventName, () => {
    pipMetadataReady = true;
    updatePictureInPicture();
  });
}
pipVideo.addEventListener('emptied', () => {
  pipMetadataReady = false;
  updatePictureInPicture();
});
updatePictureInPicture();

function noteBackendSuccess() {
  broadcast.backendFailures = 0;
}

function noteCoreControlSuccess(channel) {
  if (channel === 'status') broadcast.coreStatusFailures = 0;
  if (channel === 'lease') broadcast.coreLeaseFailures = 0;
}

function noteCoreControlFailure(channel, message) {
  if (!broadcast.lease && !broadcast.peer && !broadcast.stream) return;
  if (channel === 'status') broadcast.coreStatusFailures += 1;
  if (channel === 'lease') broadcast.coreLeaseFailures += 1;
  if (
    broadcast.coreStatusFailures < 3 ||
    broadcast.coreLeaseFailures < 3
  ) return;
  teardownBroadcast(
    message + ' Broadcasting stopped to avoid a frozen stale stream.',
    'error',
    true,
    true
  );
}

function noteBackendFailure(message) {
  if (!broadcast.lease && !broadcast.peer && !broadcast.stream) return;
  broadcast.backendFailures += 1;
  if (broadcast.backendFailures >= 3) {
    streamElements().message.textContent =
      message + ' Video remains active; recovery is automatic when possible.';
  }
}

function clearLeaseRecovery() {
  if (broadcast.leaseRecoveryTimer) clearTimeout(broadcast.leaseRecoveryTimer);
  broadcast.leaseRecoveryTimer = null;
}

function cancelLeaseRecovery() {
  clearLeaseRecovery();
  broadcast.leaseRecoveryPending = false;
  broadcast.leaseRecoveryAttempts = 0;
  broadcast.leaseRecoveryDeadlineAt = null;
}

function beginLeaseRecovery(message, immediate = false) {
  if (broadcast.pageEnding || broadcast.manuallyStopped) return;
  const now = monotonicNow();
  if (
    broadcast.leaseRecoveryPending &&
    broadcast.leaseRecoveryDeadlineAt !== null &&
    broadcast.leaseRecoveryDeadlineAt <= now
  ) {
    cancelLeaseRecovery();
    setStreamState(
      'offline',
      'Automatic lease recovery ended. Select Go Live to try again.',
      false
    );
    return;
  }
  if (!broadcast.leaseRecoveryPending) {
    const ttlSeconds = Math.max(
      120,
      Number(broadcast.config && broadcast.config.lease_ttl_seconds) || 120
    );
    broadcast.leaseRecoveryPending = true;
    broadcast.leaseRecoveryAttempts = 0;
    broadcast.leaseRecoveryDeadlineAt = now + (ttlSeconds + 15) * 1000;
  }
  if (message) streamElements().message.textContent = message;
  scheduleLeaseRecovery(immediate);
}

function scheduleLeaseRecovery(immediate = false) {
  if (
    !broadcast.leaseRecoveryPending ||
    broadcast.pageEnding ||
    broadcast.manuallyStopped ||
    document.hidden ||
    broadcast.leaseRecoveryTimer ||
    broadcast.leaseRecoveryInFlight ||
    broadcast.peer ||
    broadcast.starting
  ) return;
  const remaining = broadcast.leaseRecoveryDeadlineAt - monotonicNow();
  if (remaining <= 0) {
    cancelLeaseRecovery();
    setStreamState(
      'offline',
      'Automatic lease recovery ended. Select Go Live to try again.',
      false
    );
    return;
  }
  const delay = immediate
    ? 0
    : Math.min(
      remaining,
      15000,
      1000 * (2 ** Math.min(broadcast.leaseRecoveryAttempts, 4))
    );
  broadcast.leaseRecoveryTimer = setTimeout(async () => {
    broadcast.leaseRecoveryTimer = null;
    if (
      !broadcast.leaseRecoveryPending ||
      broadcast.pageEnding ||
      broadcast.manuallyStopped ||
      document.hidden
    ) return;
    if (monotonicNow() >= broadcast.leaseRecoveryDeadlineAt) {
      cancelLeaseRecovery();
      setStreamState(
        'offline',
        'Automatic lease recovery ended. Select Go Live to try again.',
        false
      );
      return;
    }
    broadcast.leaseRecoveryInFlight = true;
    broadcast.leaseRecoveryAttempts += 1;
    try {
      await startBroadcast();
      if (broadcast.lease && broadcast.peer) {
        cancelLeaseRecovery();
        streamElements().message.textContent =
          'Livestream recovered after the browser lease was reacquired.';
      }
    } finally {
      broadcast.leaseRecoveryInFlight = false;
    }
    if (broadcast.leaseRecoveryPending) {
      scheduleLeaseRecovery();
    }
  }, delay);
}

function handleLeaseLoss() {
  if (broadcast.pageEnding) return;
  teardownBroadcast(
    'Browser lease expired. Select Go Live, or return to this tab to recover.',
    'offline',
    false,
    false
  );
  beginLeaseRecovery(
    'Browser lease expired. Waiting to reacquire this stream window…',
    true
  );
}

async function leaseRequest(action, {keepalive = false} = {}) {
  const body = {
    action,
    owner: broadcast.owner,
    generation: broadcast.config && broadcast.config.generation
  };
  if (action !== 'acquire') body.lease = broadcast.lease;
  const response = await fetch('/api/livestream/lease', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify(body),
    keepalive
  });
  let data = {};
  try {
    data = await response.json();
  } catch (_error) {
    // The HTTP status remains authoritative.
  }
  if (!response.ok) {
    const error = new Error(data.message || `lease failed: ${response.status}`);
    error.status = response.status;
    error.reason = data.message;
    throw error;
  }
  return data;
}

function stopLeaseHeartbeat() {
  if (broadcast.heartbeatTimer) clearInterval(broadcast.heartbeatTimer);
  broadcast.heartbeatTimer = null;
  broadcast.heartbeatInFlight = false;
}

async function heartbeatLease() {
  if (!broadcast.lease || broadcast.heartbeatInFlight || broadcast.pageEnding) return;
  const expectedLease = broadcast.lease;
  broadcast.heartbeatInFlight = true;
  try {
    const data = await leaseRequest('heartbeat');
    if (
      broadcast.lease !== expectedLease ||
      data.owner !== broadcast.owner ||
      data.generation !== broadcast.config.generation
    ) {
      throw new Error('generation-mismatch');
    }
    noteBackendSuccess();
    noteCoreControlSuccess('lease');
  } catch (error) {
    if (broadcast.lease === expectedLease) {
      if ([409, 410].includes(error.status)) {
        handleLeaseLoss();
      } else {
        noteCoreControlFailure(
          'lease',
          'The local runtime and lease control channels are unavailable.'
        );
        noteBackendFailure('The local lease heartbeat is temporarily unavailable.');
      }
    }
  } finally {
    broadcast.heartbeatInFlight = false;
  }
}

async function acquireLease() {
  if (broadcast.lease) return true;
  if (!broadcast.owner) {
    setStreamState('error', 'Secure browser randomness is unavailable.', false);
    return false;
  }
  try {
    const data = await leaseRequest('acquire');
    if (
      data.owner !== broadcast.owner ||
      data.generation !== broadcast.config.generation ||
      !/^[A-Za-z0-9_-]{32,128}$/.test(data.lease || '')
    ) {
      throw new Error('Invalid lease response');
    }
    if (
      broadcast.pageEnding ||
      broadcast.manuallyStopped ||
      document.hidden
    ) {
      releaseGrantedLease(data);
      if (document.hidden && !broadcast.pageEnding && !broadcast.manuallyStopped) {
        beginLeaseRecovery(
          'Livestream start paused while this stream window is hidden.'
        );
      }
      return false;
    }
    broadcast.lease = data.lease;
    cancelLeaseRecovery();
    noteBackendSuccess();
    noteCoreControlSuccess('lease');
    stopLeaseHeartbeat();
    const heartbeatSeconds = Math.max(10, Number(data.heartbeat_seconds) || 15);
    broadcast.heartbeatTimer = setInterval(
      heartbeatLease,
      heartbeatSeconds * 1000
    );
    return true;
  } catch (error) {
    const activeOwner = error.status === 409 && error.reason === 'owner-active';
    setStreamState(
      activeOwner ? 'offline' : 'error',
      activeOwner
        ? 'Another stream window currently owns this runtime.'
        : 'Could not acquire the browser stream lease. Select Go Live to retry.',
      false
    );
    if (activeOwner) {
      beginLeaseRecovery(
        'Another stream window owns this runtime. Waiting to take over safely…'
      );
    }
    return false;
  }
}

function releaseGrantedLease(data) {
  const body = {
    action: 'release',
    owner: broadcast.owner,
    generation: data.generation,
    lease: data.lease
  };
  return fetch('/api/livestream/lease', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify(body),
    keepalive: true
  }).catch(() => {});
}

function releaseLease() {
  if (!broadcast.lease) {
    stopLeaseHeartbeat();
    return Promise.resolve();
  }
  const lease = broadcast.lease;
  stopLeaseHeartbeat();
  broadcast.lease = null;
  return releaseGrantedLease({
    generation: broadcast.config.generation,
    lease
  });
}

function publishStreamState(state) {
  if (!broadcast.config || !broadcast.lease) return;
  const snapshot = {
    owner: broadcast.owner,
    generation: broadcast.config.generation,
    lease: broadcast.lease
  };
  const viewerCount = broadcast.viewers.size;
  streamStateUpdate = streamStateUpdate.then(async () => {
    if (broadcast.lease !== snapshot.lease) return;
    const response = await fetch('/api/livestream/state', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({
        state,
        viewer_count: viewerCount,
        ...snapshot
      })
    });
    if (!response.ok) {
      if (
        broadcast.lease === snapshot.lease &&
        [401, 403, 409, 410].includes(response.status)
      ) {
        handleLeaseLoss();
        return;
      }
      throw new Error(`state update failed: ${response.status}`);
    }
    noteBackendSuccess();
  }).catch(() => {
    if (broadcast.lease === snapshot.lease) {
      noteBackendFailure('Repeated stream backend failures ended broadcasting.');
    }
  });
}

function setStreamState(state, message, publish = true) {
  broadcast.state = state;
  const elements = streamElements();
  const labels = {
    offline: 'Offline',
    connecting: 'Connecting',
    live: 'LIVE',
    reconnecting: 'Reconnecting',
    error: 'Error'
  };
  elements.state.textContent = labels[state] || 'Offline';
  elements.message.textContent = message || labels[state] || 'Offline';
  elements.badge.textContent = state === 'live' ? 'LIVE' : labels[state].toUpperCase();
  elements.badge.className = 'badge ' + (
    state === 'live' ? 'live' :
    (state === 'connecting' || state === 'reconnecting' ? 'connecting' : 'offline')
  );
  elements.count.textContent = String(broadcast.viewers.size);
  elements.go.disabled = state !== 'offline';
  elements.end.disabled = !broadcast.lease && !broadcast.peer && !broadcast.stream;
  elements.retry.hidden = state !== 'error';
  if (publish) publishStreamState(state);
}

function closeViewer(peerId) {
  const entry = broadcast.viewers.get(peerId);
  if (!entry) return;
  broadcast.viewers.delete(peerId);
  if (entry.mediaTimer) clearTimeout(entry.mediaTimer);
  try {
    entry.call.close();
  } catch (_error) {
    // Continue closing the paired data connection.
  }
  try {
    entry.connection.close();
  } catch (_error) {
    // The failed connection is already removed from admission accounting.
  }
  streamElements().count.textContent = String(broadcast.viewers.size);
  publishStreamState(broadcast.state);
  fanoutTelemetry();
}

function cleanupNegotiating(peerId, connection) {
  const entry = broadcast.negotiating.get(peerId);
  if (!entry || entry.connection !== connection) return null;
  if (entry.helloTimer) clearTimeout(entry.helloTimer);
  broadcast.negotiating.delete(peerId);
  return entry;
}

function rejectConnection(connection, reason) {
  try {
    if (connection.open) {
      connection.send({v: 1, type: 'reject', reason});
    }
  } catch (_error) {
    // Closing is the authoritative rejection.
  }
  try {
    connection.close();
  } catch (_error) {
    // A malformed incoming offer is still discarded.
  }
}

function validWatchHello(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const keys = Object.keys(value).sort().join(',');
  if (keys !== 'cap,type,v') return false;
  if (
    value.v !== broadcast.config.protocol_version ||
    value.type !== 'watch' ||
    typeof value.cap !== 'string' ||
    value.cap.length > 128 ||
    value.cap !== broadcast.config.watch_capability
  ) {
    return false;
  }
  let encoded;
  try {
    encoded = new TextEncoder().encode(JSON.stringify(value));
  } catch (_error) {
    return false;
  }
  return encoded.byteLength <= broadcast.config.max_hello_bytes;
}

function acceptDataConnection(connection) {
  if (
    !connection ||
    typeof connection.peer !== 'string' ||
    typeof connection.on !== 'function'
  ) {
    rejectConnection(connection || {}, 'unavailable');
    return;
  }
  const peerId = connection.peer;
  const maxNegotiating = Math.min(
    16,
    Math.max(1, Number(broadcast.config.max_negotiating) || 1)
  );
  if (
    broadcast.negotiating.has(peerId) ||
    broadcast.viewers.has(peerId) ||
    broadcast.negotiating.size >= maxNegotiating
  ) {
    rejectConnection(connection, 'unavailable');
    return;
  }
  const entry = {
    connection,
    opened: false,
    greeted: false,
    helloTimer: null
  };
  broadcast.negotiating.set(peerId, entry);

  const closed = () => {
    cleanupNegotiating(peerId, connection);
    closeViewer(peerId);
  };
  connection.on('close', closed);
  connection.on('error', closed);
  connection.on('open', () => {
    if (broadcast.negotiating.get(peerId) !== entry) {
      rejectConnection(connection, 'unavailable');
      return;
    }
    entry.opened = true;
    entry.helloTimer = setTimeout(() => {
      cleanupNegotiating(peerId, connection);
      rejectConnection(connection, 'hello-timeout');
    }, 5000);
  });
  connection.on('data', value => {
    if (entry.greeted) {
      closeViewer(peerId);
      return;
    }
    if (!entry.opened || !validWatchHello(value)) {
      cleanupNegotiating(peerId, connection);
      rejectConnection(connection, 'invalid-hello');
      return;
    }
    entry.greeted = true;
    cleanupNegotiating(peerId, connection);
    if (broadcast.viewers.size >= broadcast.config.max_viewers) {
      rejectConnection(connection, 'capacity');
      return;
    }
    let call;
    try {
      call = broadcast.peer.call(peerId, broadcast.stream, {
        metadata: {v: broadcast.config.protocol_version, role: 'spectator'}
      });
    } catch (_error) {
      rejectConnection(connection, 'media-failed');
      return;
    }
    if (!call) {
      rejectConnection(connection, 'media-failed');
      return;
    }
    broadcast.viewers.set(peerId, {
      connection,
      call,
      mediaTimer: null,
      telemetryHash: '',
      telemetrySentAt: -Infinity,
      telemetryPending: false
    });
    try {
      connection.send({v: broadcast.config.protocol_version, type: 'ready'});
    } catch (_error) {
      closeViewer(peerId);
      return;
    }
    call.on('close', () => closeViewer(peerId));
    call.on('error', () => closeViewer(peerId));
    const admitted = broadcast.viewers.get(peerId);
    admitted.mediaTimer = setTimeout(() => {
      const current = broadcast.viewers.get(peerId);
      if (!current || current.call !== call) return;
      current.mediaTimer = null;
      if (!call.open) closeViewer(peerId);
    }, 15000);
    call.on('iceStateChanged', state => {
      if (!['connected', 'completed'].includes(state)) return;
      const current = broadcast.viewers.get(peerId);
      if (!current || current.call !== call || !current.mediaTimer) return;
      clearTimeout(current.mediaTimer);
      current.mediaTimer = null;
    });
    streamElements().count.textContent = String(broadcast.viewers.size);
    publishStreamState('live');
    if (dashboardCache.snapshot) {
      sendTelemetryToViewer(peerId, true);
    }
    const currentViewer = broadcast.viewers.get(peerId);
    if (!currentViewer || !Number.isFinite(currentViewer.telemetrySentAt)) {
      refreshDashboard().then(() => {
        const current = broadcast.viewers.get(peerId);
        if (current && !Number.isFinite(current.telemetrySentAt)) {
          sendTelemetryToViewer(peerId, true);
        }
      });
    }
  });
}

function teardownBroadcast(
  message = 'Livestream ended.',
  state = 'offline',
  releaseToServer = true,
  manual = true
) {
  broadcast.manuallyStopped = manual;
  broadcast.starting = false;
  if (broadcast.reconnectTimer) clearTimeout(broadcast.reconnectTimer);
  broadcast.reconnectTimer = null;
  clearLeaseRecovery();
  if (manual) {
    cancelLeaseRecovery();
  }

  const negotiating = [...broadcast.negotiating.values()];
  broadcast.negotiating.clear();
  for (const entry of negotiating) {
    if (entry.helloTimer) clearTimeout(entry.helloTimer);
    try {
      entry.connection.close();
    } catch (_error) {
      // Continue tearing down all resources.
    }
  }
  const viewers = [...broadcast.viewers.values()];
  broadcast.viewers.clear();
  for (const entry of viewers) {
    if (entry.mediaTimer) clearTimeout(entry.mediaTimer);
    try {
      entry.call.close();
    } catch (_error) {
      // Continue tearing down the paired connection.
    }
    try {
      entry.connection.close();
    } catch (_error) {
      // Continue tearing down all viewers.
    }
  }
  const peer = broadcast.peer;
  broadcast.peer = null;
  if (peer) {
    try {
      peer.destroy();
    } catch (_error) {
      // PeerJS may already have closed its transports.
    }
  }
  const stream = broadcast.stream;
  broadcast.stream = null;
  cleanupPictureInPicture();
  if (stream) {
    for (const track of stream.getTracks()) {
      try {
        track.stop();
      } catch (_error) {
        // Continue stopping the remaining capture tracks.
      }
    }
  }
  let release = Promise.resolve();
  if (releaseToServer) {
    release = releaseLease();
  } else {
    stopLeaseHeartbeat();
    broadcast.lease = null;
  }
  broadcast.coreStatusFailures = 0;
  broadcast.coreLeaseFailures = 0;
  setStreamState(state, message, false);
  return release;
}

function endBroadcast() {
  return teardownBroadcast('Livestream ended.', 'offline', true);
}

function peerErrorTarget(error) {
  const direct = [
    error && error.peer,
    error && error.peerId,
    error && error.remotePeer
  ].find(value => typeof value === 'string');
  if (direct) return direct;
  const message = error && error.message;
  if (typeof message !== 'string') return null;
  for (const peerId of [
    ...broadcast.viewers.keys(),
    ...broadcast.negotiating.keys()
  ]) {
    if (message === `Could not connect to peer ${peerId}`) return peerId;
  }
  return null;
}

function closePeerErrorTarget(peerId) {
  if (broadcast.viewers.has(peerId)) {
    closeViewer(peerId);
    return true;
  }
  const entry = broadcast.negotiating.get(peerId);
  if (!entry) return false;
  cleanupNegotiating(peerId, entry.connection);
  rejectConnection(entry.connection, 'media-failed');
  return true;
}

function handleHostPeerError(error, activePeer) {
  if (broadcast.manuallyStopped || broadcast.peer !== activePeer) return;
  const type = error && error.type;
  if (['peer-unavailable', 'webrtc'].includes(type)) {
    const target = peerErrorTarget(error);
    if (target) closePeerErrorTarget(target);
    return;
  }
  const hostFatal = new Set([
    'browser-incompatible',
    'invalid-id',
    'invalid-key',
    'network',
    'ssl-unavailable',
    'server-error',
    'socket-error',
    'socket-closed',
    'unavailable-id'
  ]);
  if (!hostFatal.has(type)) return;
  teardownBroadcast(
    'Livestream connection failed. Select Retry.',
    'error',
    true
  );
}

async function startBroadcast() {
  if (!broadcast.config || broadcast.peer || broadcast.starting) return;
  if (typeof Peer !== 'function' || typeof game.captureStream !== 'function') {
    setStreamState(
      'error',
      'This browser cannot start the PeerJS canvas stream.',
      false
    );
    return;
  }
  const iceServers = (
    broadcast.config.peer_options &&
    broadcast.config.peer_options.config &&
    broadcast.config.peer_options.config.iceServers
  );
  if (!Array.isArray(iceServers) || !iceServers.length) {
    setStreamState('error', 'The stream ICE configuration is invalid.', false);
    return;
  }

  broadcast.starting = true;
  broadcast.manuallyStopped = false;
  setStreamState('connecting', 'Acquiring the browser stream lease…', false);
  if (!await acquireLease()) {
    broadcast.starting = false;
    if (broadcast.leaseRecoveryPending) scheduleLeaseRecovery();
    return;
  }
  if (
    broadcast.pageEnding ||
    broadcast.manuallyStopped ||
    document.hidden
  ) {
    broadcast.starting = false;
    await releaseLease();
    if (document.hidden && !broadcast.pageEnding && !broadcast.manuallyStopped) {
      beginLeaseRecovery(
        'Livestream start paused while this stream window is hidden.'
      );
    }
    return;
  }
  try {
    broadcast.stream = game.captureStream(broadcast.config.frame_rate);
    attachPictureInPictureStream(broadcast.stream);
    for (const track of broadcast.stream.getTracks()) {
      track.addEventListener('ended', () => {
        if (broadcast.stream) {
          teardownBroadcast('Canvas capture ended.', 'error', true);
        }
      }, {once: true});
    }
    broadcast.peer = new Peer(
      broadcast.config.peer_id,
      broadcast.config.peer_options
    );
  } catch (_error) {
    teardownBroadcast(
      'Could not initialize the browser livestream.',
      'error',
      true
    );
    return;
  }
  broadcast.starting = false;
  const activePeer = broadcast.peer;
  setStreamState('connecting', 'Connecting to PeerJS signaling…');
  activePeer.on('open', () => {
    if (broadcast.peer !== activePeer) return;
    if (broadcast.reconnectTimer) clearTimeout(broadcast.reconnectTimer);
    broadcast.reconnectTimer = null;
    setStreamState('live', 'Live and ready for spectators.');
  });
  activePeer.on('connection', connection => {
    if (broadcast.peer === activePeer) acceptDataConnection(connection);
    else connection.close();
  });
  activePeer.on('call', call => call.close());
  activePeer.on('disconnected', () => {
    if (broadcast.manuallyStopped || broadcast.peer !== activePeer) return;
    setStreamState('reconnecting', 'Signaling disconnected; reconnecting…');
    if (broadcast.reconnectTimer) return;
    broadcast.reconnectTimer = setTimeout(() => {
      broadcast.reconnectTimer = null;
      if (broadcast.peer === activePeer && activePeer.disconnected) {
        try {
          activePeer.reconnect();
        } catch (_error) {
          teardownBroadcast(
            'Signaling reconnection failed. Select Retry.',
            'error',
            true
          );
        }
      }
    }, 1000);
  });
  activePeer.on('error', error => handleHostPeerError(error, activePeer));
  activePeer.on('close', () => {
    if (broadcast.peer !== activePeer) return;
    if (!broadcast.manuallyStopped) {
      teardownBroadcast(
        'Livestream closed unexpectedly. Select Retry.',
        'error',
        true
      );
    }
  });
}

async function configureLivestream() {
  let config;
  try {
    const response = await fetch('/api/livestream');
    if (!response.ok) throw new Error(`configuration failed: ${response.status}`);
    config = await response.json();
  } catch (_error) {
    return;
  }
  if (
    !config.enabled ||
    !/^[A-Za-z0-9_-]{16,128}$/.test(config.generation || '')
  ) {
    return;
  }
  broadcast.config = config;
  const elements = streamElements();
  elements.section.hidden = false;
  elements.limit.textContent = String(config.max_viewers);
  const link = document.getElementById('join-link');
  link.href = config.join_url;
  link.textContent = config.join_url;
  document.getElementById('copy-link').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(config.join_url);
      elements.message.textContent = 'Join link copied.';
    } catch (_error) {
      elements.message.textContent = 'Copy failed; select and copy the link.';
    }
  });
  elements.go.addEventListener('click', () => { startBroadcast(); });
  elements.end.addEventListener('click', endBroadcast);
  elements.retry.addEventListener('click', () => {
    teardownBroadcast('Retrying…', 'offline', true);
    startBroadcast();
  });
  try {
    new QRious({
      element: document.getElementById('stream-qr'),
      value: config.join_url,
      size: 220,
      level: 'M',
      background: 'white',
      foreground: 'black'
    });
  } catch (_error) {
    setStreamState('error', 'Could not render the local QR code.');
    return;
  }
  await startBroadcast();
}

setInterval(refreshFrame, 100);
setInterval(refreshStatus, 500);
setInterval(refreshDashboard, 1000);
setInterval(fanoutTelemetry, 250);
refreshFrame();
refreshStatus();
refreshDashboard();
configureLivestream();

function handlePageExit() {
  if (broadcast.pageEnding) return;
  broadcast.pageEnding = true;
  teardownBroadcast('Stream window closed.', 'offline', true);
}

window.addEventListener('pagehide', handlePageExit);
window.addEventListener('beforeunload', handlePageExit);
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    clearLeaseRecovery();
    if (broadcast.state === 'live') {
      streamElements().message.textContent =
        'Live in the background. Picture in Picture can keep the game visible.';
    }
    return;
  }
  if (!document.hidden && broadcast.leaseRecoveryPending) {
    scheduleLeaseRecovery(true);
  } else if (!document.hidden && broadcast.lease) {
    heartbeatLease();
    publishStreamState(broadcast.state);
  }
});
"""
















def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_livestream_port(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        port = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error
    if not 0 <= port <= 65535:
        raise ValueError(f"{name} must be 0-65535")
    return port


def validate_advertised_host(value: str) -> str:
    host = value.strip()
    if not host or any(character.isspace() for character in host):
        raise ValueError("advertised_host must be a bare hostname or IP address")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        pass
    else:
        if address.version != 4:
            raise ValueError(
                "advertised_host must be IPv4 because the spectator server "
                "binds IPv4 only"
            )
        return str(address)
    if (
        len(host) > 253
        or not re.fullmatch(
            r"(?=.{1,253}\Z)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?",
            host,
        )
        or ".." in host
    ):
        raise ValueError("advertised_host must be a bare hostname or IP address")
    return host


def discover_lan_host() -> str:
    candidates: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            candidates.append(str(probe.getsockname()[0]))
    except OSError:
        pass
    try:
        candidates.append(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not address.is_loopback and not address.is_unspecified:
            return str(address)
    return "127.0.0.1"


def url_host(host: str) -> str:
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return host
    return f"[{address}]" if address.version == 6 else str(address)


def validate_external_join_base(value: str) -> str:
    base = value.strip()
    try:
        parsed = urllib.parse.urlsplit(base)
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"join_base is not a valid URL: {error}") from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or port == 0
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "join_base must be an HTTPS URL without credentials, query, or fragment"
        )
    path = parsed.path if parsed.path.endswith("/") else f"{parsed.path}/"
    return urllib.parse.urlunsplit(parsed._replace(path=path))


def decode_urlsafe_token(value: str, size: int, name: str) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError(f"Invalid {name}")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as error:
        raise ValueError(f"Invalid {name}") from error
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if len(decoded) != size or not secrets.compare_digest(canonical, value):
        raise ValueError(f"Invalid {name}")
    return decoded


def parse_host_public_key(host_public_key: str) -> dict[str, Any]:
    encoded = decode_urlsafe_token_variable(
        host_public_key,
        64,
        1024,
        "host public key",
    )
    try:
        serialized = encoded.decode("utf-8")
        value = json.loads(serialized)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid host public key") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"crv", "ext", "key_ops", "kty", "x", "y"}
        or value.get("crv") != "P-256"
        or value.get("kty") != "EC"
        or value.get("ext") is not True
        or value.get("key_ops") != ["verify"]
        or json.dumps(value, sort_keys=True, separators=(",", ":")) != serialized
    ):
        raise ValueError("Invalid host public key")
    decode_urlsafe_token(value.get("x"), 32, "host public key x")
    decode_urlsafe_token(value.get("y"), 32, "host public key y")
    return value


def decode_urlsafe_token_variable(
    value: str,
    minimum: int,
    maximum: int,
    name: str,
) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError(f"Invalid {name}")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as error:
        raise ValueError(f"Invalid {name}") from error
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if (
        not minimum <= len(decoded) <= maximum
        or not secrets.compare_digest(canonical, value)
    ):
        raise ValueError(f"Invalid {name}")
    return decoded


def derive_host_fingerprint(host_public_key: str, generation: str) -> str:
    public_jwk = parse_host_public_key(host_public_key)
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", generation):
        raise ValueError("Invalid generation")
    digest = hashlib.sha256(
        b"rpp-host-signing-v2\0"
        + generation.encode("ascii")
        + b"\0"
        + json.dumps(
            public_jwk,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return digest[:32]


def validate_host_identity(value: Any, generation: str) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "created_at",
        "fingerprint",
        "generation",
        "host_private_jwk",
        "host_public_jwk",
        "host_public_key",
        "schema_version",
    }:
        return False
    public_jwk = value.get("host_public_jwk")
    private_jwk = value.get("host_private_jwk")
    if (
        value.get("schema_version") != KITE_STRING_SCHEMA_VERSION
        or value.get("generation") != generation
        or not isinstance(public_jwk, dict)
        or not isinstance(private_jwk, dict)
        or set(private_jwk)
        != {"crv", "d", "ext", "key_ops", "kty", "x", "y"}
        or private_jwk.get("crv") != "P-256"
        or private_jwk.get("kty") != "EC"
        or private_jwk.get("ext") is not True
        or private_jwk.get("key_ops") != ["sign"]
    ):
        return False
    try:
        parsed_public = parse_host_public_key(value.get("host_public_key"))
        if parsed_public != public_jwk:
            return False
        for coordinate in ("x", "y"):
            if private_jwk.get(coordinate) != public_jwk.get(coordinate):
                return False
            decode_urlsafe_token(
                private_jwk.get(coordinate),
                32,
                f"host private key {coordinate}",
            )
        decode_urlsafe_token(private_jwk.get("d"), 32, "host private key scalar")
        expected = derive_host_fingerprint(value["host_public_key"], generation)
    except (TypeError, ValueError):
        return False
    created_at = value.get("created_at")
    if not isinstance(created_at, str) or len(created_at) > 48:
        return False
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return bool(
        secrets.compare_digest(str(value.get("fingerprint", "")), expected)
    )


def build_join_url(
    base: str,
    peer_or_room: str,
    capability_or_key: str,
    *,
    signaling: Optional[str] = None,
    generation: Optional[str] = None,
    host_fingerprint: Optional[str] = None,
    host_public_key: Optional[str] = None,
) -> str:
    try:
        parsed = urllib.parse.urlsplit(base)
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"Invalid spectator page base URL: {error}") from error
    mode = signaling or (
        "nostr"
        if any(
            value is not None
            for value in (generation, host_fingerprint, host_public_key)
        )
        else "peerjs"
    )
    if mode not in {"nostr", "peerjs"}:
        raise ValueError("Invalid signaling mode")
    if mode == "nostr" and parsed.scheme != "https":
        raise ValueError("Nostr spectator page base URL must use HTTPS")
    if (
        parsed.scheme not in ({"https"} if mode == "nostr" else {"http", "https"})
        or not parsed.hostname
        or port == 0
        or parsed.fragment
        or parsed.query
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Invalid spectator page base URL")
    if mode == "nostr":
        decode_urlsafe_token(peer_or_room, 16, "room ID")
        decode_urlsafe_token(capability_or_key, 32, "room key")
        if not isinstance(generation, str):
            raise ValueError("Invalid generation")
        expected_fingerprint = derive_host_fingerprint(
            host_public_key if isinstance(host_public_key, str) else "",
            generation,
        )
        if (
            not isinstance(host_fingerprint, str)
            or not re.fullmatch(r"[a-f0-9]{32}", host_fingerprint)
            or not secrets.compare_digest(host_fingerprint, expected_fingerprint)
        ):
            raise ValueError("Invalid host fingerprint")
        fields = {
            "v": LIVESTREAM_PROTOCOL_VERSION,
            "room": peer_or_room,
            "key": capability_or_key,
            "gen": generation,
            "pub": host_public_key,
            "fp": host_fingerprint,
        }
    else:
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", peer_or_room):
            raise ValueError("Invalid PeerJS host ID")
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", capability_or_key):
            raise ValueError("Invalid watch capability")
        fields = {
            "v": LEGACY_LIVESTREAM_PROTOCOL_VERSION,
            "host": peer_or_room,
            "watch": capability_or_key,
        }
    fragment = urllib.parse.urlencode(
        fields,
        quote_via=urllib.parse.quote,
        safe="",
    )
    return f"{base}#{fragment}"


def validate_watch_hello(value: Any, watch_capability: str) -> bool:
    if not isinstance(value, dict) or set(value) != {"v", "type", "cap"}:
        return False
    capability = value.get("cap")
    if not (
        value.get("v") == LEGACY_LIVESTREAM_PROTOCOL_VERSION
        and value.get("type") == "watch"
        and isinstance(capability, str)
        and len(capability) <= 128
        and secrets.compare_digest(capability, watch_capability)
    ):
        return False
    try:
        encoded = json.dumps(
            value,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return False
    return len(encoded) <= MAX_WATCH_HELLO_BYTES


def watch_admission_decision(
    value: Any,
    watch_capability: str,
    viewer_count: int,
    max_viewers: int,
) -> str:
    if not validate_watch_hello(value, watch_capability):
        return "invalid-hello"
    if viewer_count >= min(max(1, max_viewers), HARD_MAX_VIEWERS):
        return "capacity"
    return "accept"


class LivestreamLeaseError(RuntimeError):
    def __init__(self, reason: str, status_code: int):
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class StartupConfigurationError(RuntimeError):
    pass


class LivestreamLeaseManager:
    def __init__(
        self,
        generation: str,
        *,
        ttl_seconds: float = LIVESTREAM_LEASE_TTL_SECONDS,
        clock: Any = time.monotonic,
    ):
        self.generation = generation
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self.lock = threading.Lock()
        self.owner: Optional[str] = None
        self.lease: Optional[str] = None
        self.last_seen = 0.0

    @staticmethod
    def _valid_identifier(value: Any) -> bool:
        return isinstance(value, str) and bool(
            re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value)
        )

    def _expire_locked(self, now: float) -> None:
        if self.lease and now - self.last_seen >= self.ttl_seconds:
            self.owner = None
            self.lease = None
            self.last_seen = 0.0

    def acquire(self, owner: Any, generation: Any) -> dict[str, Any]:
        if generation != self.generation:
            raise LivestreamLeaseError("generation-mismatch", 409)
        if not self._valid_identifier(owner):
            raise LivestreamLeaseError("invalid-owner", 400)
        now = float(self.clock())
        with self.lock:
            self._expire_locked(now)
            if self.lease and self.owner != owner:
                raise LivestreamLeaseError("owner-active", 409)
            self.owner = owner
            self.lease = secrets.token_urlsafe(32)
            self.last_seen = now
            return {
                "owner": owner,
                "generation": self.generation,
                "lease": self.lease,
                "ttl_seconds": self.ttl_seconds,
                "heartbeat_seconds": LIVESTREAM_HEARTBEAT_SECONDS,
            }

    def validate(
        self,
        owner: Any,
        generation: Any,
        lease: Any,
        *,
        touch: bool = True,
    ) -> None:
        if generation != self.generation:
            raise LivestreamLeaseError("generation-mismatch", 409)
        now = float(self.clock())
        with self.lock:
            self._expire_locked(now)
            valid = bool(
                self.lease
                and isinstance(owner, str)
                and isinstance(lease, str)
                and self.owner == owner
                and secrets.compare_digest(self.lease, lease)
            )
            if not valid:
                raise LivestreamLeaseError("lease-lost", 409)
            if touch:
                self.last_seen = now

    def release(self, owner: Any, generation: Any, lease: Any) -> None:
        if generation != self.generation:
            raise LivestreamLeaseError("generation-mismatch", 409)
        now = float(self.clock())
        with self.lock:
            self._expire_locked(now)
            if not (
                self.lease
                and isinstance(owner, str)
                and isinstance(lease, str)
                and self.owner == owner
                and secrets.compare_digest(self.lease, lease)
            ):
                raise LivestreamLeaseError("lease-lost", 409)
            self.owner = None
            self.lease = None
            self.last_seen = 0.0

    def revoke(self) -> None:
        with self.lock:
            self.owner = None
            self.lease = None
            self.last_seen = 0.0


def _fresh_livestream_report(
    raw: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> bool:
    updated_at = raw.get("updated_at")
    if not isinstance(updated_at, str):
        return False
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if updated.tzinfo is None:
        return False
    current = now or datetime.now(timezone.utc)
    age = (current - updated.astimezone(timezone.utc)).total_seconds()
    return -5 <= age <= LIVESTREAM_REPORT_STALE_SECONDS


def livestream_public_state(
    runtime_dir: Path,
    *,
    expected_generation: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    raw = read_json(runtime_dir / "livestream-status.json")
    state = str(raw.get("state", "offline"))
    fresh = _fresh_livestream_report(raw, now=now)
    generation_matches = (
        expected_generation is None
        or raw.get("generation") == expected_generation
    )
    if (
        state not in {"offline", "connecting", "live", "reconnecting", "error"}
        or not fresh
        or not generation_matches
    ):
        state = "offline"
    try:
        viewer_count = max(0, min(HARD_MAX_VIEWERS, int(raw.get("viewer_count", 0))))
    except (TypeError, ValueError):
        viewer_count = 0
    if state == "offline":
        viewer_count = 0
    return {
        "state": state,
        "viewer_count": viewer_count,
        "updated_at": raw.get("updated_at"),
    }


def kite_host_public_state(
    runtime_dir: Path,
    *,
    expected_generation: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    raw = read_json(runtime_dir / "kite-host-status.json")
    updated_at = raw.get("updated_at")
    fresh = False
    if isinstance(updated_at, str):
        try:
            updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            if updated.tzinfo is not None:
                age = (
                    (now or datetime.now(timezone.utc))
                    - updated.astimezone(timezone.utc)
                ).total_seconds()
                fresh = -5 <= age <= KITE_HOST_REPORT_STALE_SECONDS
    generation_matches = (
        expected_generation is None
        or raw.get("generation") == expected_generation
    )
    if not fresh or not generation_matches:
        return {
            "bridge_state": "degraded",
            "share_ready": False,
            "automatic_share_ready": False,
            "manual_share_ready": False,
            "source_health": "lost",
            "string_health": "lost",
            "runtime_health": "degraded",
            "peer_health": "offline",
            "relay_health": "offline",
            "relay_open_count": 0,
            "relay_qualifying_count": 0,
            "relay_qualified_count": 0,
            "relay_total": 0,
            "direct_health": "idle",
            "direct_peer_count": 0,
            "media_ready_count": 0,
            "candidate_types": [],
            "first_frame": False,
        }
    source_ok = raw.get("source_health") == "ok"
    string_ok = raw.get("string_health") == "ok"
    runtime_ready = raw.get("runtime_health") == "ready"
    peer_open = raw.get("peer_health") == "open"
    signaling = raw.get("signaling", "peerjs")
    relay_health = (
        raw.get("relay_health")
        if raw.get("relay_health")
        in {
            "qualified",
            "qualifying",
            "unqualified",
            "open",
            "blocked",
            "offline",
        }
        else ("open" if peer_open else "offline")
    )
    direct_health = (
        raw.get("direct_health")
        if raw.get("direct_health") in {"idle", "connecting", "connected"}
        else "idle"
    )
    try:
        relay_open_count = max(
            0,
            min(len(NOSTR_RELAY_URLS), int(raw.get("relay_open_count", 0))),
        )
        relay_total = max(
            0,
            min(len(NOSTR_RELAY_URLS), int(raw.get("relay_total", 0))),
        )
        relay_qualifying_count = max(
            0,
            min(
                len(NOSTR_RELAY_URLS),
                int(raw.get("relay_qualifying_count", 0)),
            ),
        )
        relay_qualified_count = max(
            0,
            min(
                len(NOSTR_RELAY_URLS),
                int(raw.get("relay_qualified_count", 0)),
            ),
        )
        direct_peer_count = max(
            0,
            min(HARD_MAX_VIEWERS, int(raw.get("direct_peer_count", 0))),
        )
        media_ready_count = max(
            0,
            min(HARD_MAX_VIEWERS, int(raw.get("media_ready_count", 0))),
        )
    except (TypeError, ValueError):
        relay_open_count = 0
        relay_total = 0
        relay_qualifying_count = 0
        relay_qualified_count = 0
        direct_peer_count = 0
        media_ready_count = 0
    candidate_types = raw.get("candidate_types")
    if not (
        isinstance(candidate_types, list)
        and all(
            item in {"host", "srflx", "prflx", "relay"}
            for item in candidate_types
        )
    ):
        candidate_types = []
    first_frame = raw.get("first_frame") is True
    automatic_share_ready = bool(
        raw.get("automatic_share_ready") is True
        and source_ok
        and string_ok
        and runtime_ready
        and (
            (signaling == "nostr" and relay_qualified_count > 0)
            or (signaling != "nostr" and peer_open)
        )
        and first_frame
    )
    manual_share_ready = bool(
        raw.get("manual_share_ready") is True
        and signaling == "nostr"
        and source_ok
        and string_ok
        and runtime_ready
        and first_frame
    )
    return {
        "bridge_state": (
            raw.get("bridge_state")
            if raw.get("bridge_state") in {"starting", "ready", "degraded"}
            else "degraded"
        ),
        "share_ready": automatic_share_ready,
        "automatic_share_ready": automatic_share_ready,
        "manual_share_ready": manual_share_ready,
        "source_health": "ok" if source_ok else "lost",
        "string_health": "ok" if string_ok else "lost",
        "runtime_health": (
            raw.get("runtime_health")
            if raw.get("runtime_health")
            in {"starting", "ready", "degraded", "stopping"}
            else "degraded"
        ),
        "peer_health": "open" if peer_open else "offline",
        "relay_health": relay_health,
        "relay_open_count": relay_open_count,
        "relay_qualifying_count": relay_qualifying_count,
        "relay_qualified_count": relay_qualified_count,
        "relay_total": relay_total,
        "direct_health": direct_health,
        "direct_peer_count": direct_peer_count,
        "media_ready_count": media_ready_count,
        "candidate_types": sorted(set(candidate_types)),
        "first_frame": first_frame,
    }


def livestream_share_info(runtime_dir: Path) -> Optional[dict[str, Any]]:
    private = read_json(runtime_dir / "livestream-auth.json")
    join_url = private.get("join_url")
    if not private.get("enabled") or not isinstance(join_url, str) or not join_url:
        return None
    generation = private.get("generation")
    state = livestream_public_state(
        runtime_dir,
        expected_generation=generation if isinstance(generation, str) else None,
    )
    host_mode = private.get("livestream_host", "local")
    host = (
        kite_host_public_state(
            runtime_dir,
            expected_generation=(
                generation if isinstance(generation, str) else None
            ),
        )
        if host_mode == "kite"
        else {"share_ready": True, "bridge_state": "ready"}
    )
    result = {
        "enabled": True,
        "available": host["share_ready"],
        "automatic_available": host["share_ready"],
        "manual_available": host.get("manual_share_ready", False),
        "livestream_host": host_mode,
        "signaling": private.get("signaling", "peerjs"),
        "state": state["state"],
        "viewer_count": state["viewer_count"],
        "max_viewers": private.get("max_viewers"),
        "spectator_port": private.get("spectator_port"),
        "bridge_state": host["bridge_state"],
        "relay_health": host.get("relay_health", "offline"),
        "relay_open_count": host.get("relay_open_count", 0),
        "relay_qualifying_count": host.get("relay_qualifying_count", 0),
        "relay_qualified_count": host.get("relay_qualified_count", 0),
        "relay_total": host.get("relay_total", 0),
        "direct_health": host.get("direct_health", "idle"),
        "direct_peer_count": host.get("direct_peer_count", 0),
        "media_ready_count": host.get("media_ready_count", 0),
        "candidate_types": host.get("candidate_types", []),
    }
    if host["share_ready"]:
        result["join_url"] = join_url
    return result


def fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(value, indent=2, sort_keys=True).encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
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
    fsync_directory(path.parent)


def atomic_write_bytes(path: Path, payload: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        mode,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    os.chmod(path, mode)
    fsync_directory(path.parent)


def read_json(path: Path, default: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (
        FileNotFoundError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        OSError,
    ):
        return dict(default or {})
    return value if isinstance(value, dict) else dict(default or {})


def process_is_alive(pid: Any) -> bool:
    try:
        numeric_pid = int(pid)
        if numeric_pid <= 0:
            return False
        os.kill(numeric_pid, 0)
        return True
    except (TypeError, ValueError, ProcessLookupError, PermissionError, OSError):
        return False


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class KiteBroadcaster:
    """Supervise the nonfatal local CDP string and its dedicated browser."""

    OWNER_FILE = "kite-browser-owner.json"
    IDENTITY_FILE = "kite-host-identity.json"
    MANUAL_RETURN_DIRECTORY = "kite-manual-return"
    PRIVATE_FILES = (
        "kite-bootstrap.json",
        OWNER_FILE,
        "kite-broadcast-state.json",
        "kite-command.json",
        "kite-frame.json",
        "kite-host-status.json",
        IDENTITY_FILE,
        "kite-string-v1.cjs",
        "kite-string-v2.cjs",
        "kite-telemetry.json",
    )
    PRIVATE_TEMP_RE = re.compile(
        r"^\.(?:kite-(?:bootstrap|browser-owner|broadcast-state|command|frame|"
        r"host-status|telemetry)\.json"
        r"|kite-(?:host-identity\.json|string-v[12]\.cjs)"
        r"|livestream-status\.json)\.\d+\.tmp$"
    )

    def __init__(
        self,
        runtime_dir: Path,
        generation: str,
        startup_timeout: float,
    ):
        self.runtime_dir = runtime_dir
        self.generation = generation
        self.startup_timeout = startup_timeout
        self.script_path = runtime_dir / "kite-string-v2.cjs"
        self.profile_path = runtime_dir / f"kite-profile-{generation}"
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.process: Optional[subprocess.Popen[Any]] = None
        self.process_lock = threading.Lock()
        self.browser_records: dict[str, dict[str, Any]] = {}
        self.failures = 0

    @staticmethod
    def _node_executable() -> Optional[str]:
        node = shutil.which("node")
        if not node:
            return None
        try:
            result = subprocess.run(
                [node, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            match = re.fullmatch(r"v(\d+)(?:\.\d+){2}\s*", result.stdout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode or not match or int(match.group(1)) < 22:
            return None
        return node

    @classmethod
    def initialize_identity(
        cls,
        runtime_dir: Path,
        generation: str,
    ) -> dict[str, Any]:
        script_path = runtime_dir / "kite-string-v2.cjs"
        atomic_write_bytes(script_path, KITE_STRING_JS, 0o600)
        node = cls._node_executable()
        if not node:
            raise StartupConfigurationError(
                "Node.js 22 or newer is required for the v2 host identity"
            )
        try:
            result = subprocess.run(
                [
                    node,
                    str(script_path),
                    "--initialize-identity",
                    "--runtime-dir",
                    str(runtime_dir),
                    "--generation",
                    generation,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise StartupConfigurationError(
                "Could not initialize the generation host identity"
            ) from error
        identity_path = runtime_dir / cls.IDENTITY_FILE
        identity = read_json(identity_path)
        if result.returncode or not validate_host_identity(identity, generation):
            raise StartupConfigurationError(
                "The generation host identity failed validation"
            )
        try:
            metadata = identity_path.lstat()
        except OSError as error:
            raise StartupConfigurationError(
                "The generation host identity is unavailable"
            ) from error
        if (
            identity_path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise StartupConfigurationError(
                "The generation host identity is not a private regular file"
            )
        return identity

    def _safe_error(self, message: str) -> str:
        return re.sub(r"[^A-Za-z0-9 .:_-]", "", message)[:120]

    def _publish_degraded(self, message: str) -> None:
        current = read_json(self.runtime_dir / "kite-host-status.json")
        bootstrap = read_json(self.runtime_dir / "kite-bootstrap.json")
        instance = bootstrap.get("instance")
        if not isinstance(instance, str):
            instance = ""
        atomic_write_json(
            self.runtime_dir / "kite-host-status.json",
            {
                "schema_version": KITE_STRING_SCHEMA_VERSION,
                "generation": self.generation,
                "instance": instance[:64],
                "bridge_state": "degraded",
                "bridge_pid": (
                    current.get("bridge_pid")
                    if isinstance(current.get("bridge_pid"), int)
                    else None
                ),
                "browser_pid": None,
                "state": "error",
                "viewer_count": 0,
                "max_viewers": (
                    current.get("max_viewers")
                    if isinstance(current.get("max_viewers"), int)
                    else 0
                ),
                "peer_open": False,
                "first_frame": False,
                "share_ready": False,
                "automatic_share_ready": False,
                "manual_share_ready": False,
                "source_health": "lost",
                "string_health": "lost",
                "runtime_health": "degraded",
                "peer_health": "offline",
                "signaling": bootstrap.get("signaling", "peerjs"),
                "relay_health": "offline",
                "relay_open_count": 0,
                "relay_qualifying_count": 0,
                "relay_qualified_count": 0,
                "relay_total": (
                    len(NOSTR_RELAY_URLS)
                    if bootstrap.get("signaling") == "nostr"
                    else 0
                ),
                "direct_health": "idle",
                "direct_peer_count": 0,
                "media_ready_count": 0,
                "candidate_types": [],
                "frame_sequence": 0,
                "telemetry_sequence": 0,
                "heartbeat_sequence": 0,
                "error": self._safe_error(message),
                "updated_at": utc_now(),
            },
        )

    def _remember_browser(self) -> None:
        report = read_json(self.runtime_dir / "kite-browser-owner.json")
        token = report.get("token")
        profile = report.get("profile")
        if not (
            report.get("schema_version") == KITE_STRING_SCHEMA_VERSION
            and report.get("generation") == self.generation
            and isinstance(report.get("instance"), str)
            and isinstance(token, str)
            and re.fullmatch(r"[a-f0-9]{32,64}", token)
            and isinstance(profile, str)
            and profile == str(self.profile_path)
            and isinstance(report.get("pid"), int)
            and isinstance(report.get("pgid"), int)
            and report["pid"] == report["pgid"]
            and report["pid"] > 1
            and isinstance(report.get("start_identity"), str)
            and len(report["start_identity"]) <= 80
        ):
            return
        self.browser_records[token] = dict(report)

    @staticmethod
    def _process_rows() -> list[dict[str, Any]]:
        try:
            result = subprocess.run(
                [
                    "/bin/ps",
                    "-axo",
                    "pid=,pgid=,lstart=,command=",
                ],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode:
            return []
        rows: list[dict[str, Any]] = []
        pattern = re.compile(
            r"^\s*(\d+)\s+(\d+)\s+"
            r"(\S+\s+\S+\s+\d+\s+\d+:\d+:\d+\s+\d+)\s+(.*)$"
        )
        for line in result.stdout.splitlines():
            match = pattern.match(line)
            if not match:
                continue
            rows.append(
                {
                    "pid": int(match.group(1)),
                    "pgid": int(match.group(2)),
                    "start_identity": " ".join(match.group(3).split()),
                    "command": match.group(4),
                }
            )
        return rows

    def _owned_group_members(
        self,
        record: dict[str, Any],
    ) -> list[dict[str, Any]]:
        token = record.get("token")
        profile = record.get("profile")
        pid = record.get("pid")
        pgid = record.get("pgid")
        start_identity = record.get("start_identity")
        if not (
            isinstance(token, str)
            and re.fullmatch(r"[a-f0-9]{32,64}", token)
            and profile == str(self.profile_path)
            and isinstance(pid, int)
            and isinstance(pgid, int)
            and pid == pgid
            and pid > 1
            and isinstance(start_identity, str)
        ):
            return []
        members = [
            row for row in self._process_rows() if row["pgid"] == pgid
        ]
        leader = next((row for row in members if row["pid"] == pid), None)
        if (
            leader is not None
            and start_identity
            and leader["start_identity"] != start_identity
        ):
            return []
        profile_argument = f"--user-data-dir={profile}"
        token_argument = f"--rpp-kite-owner-token={token}"
        if not any(
            profile_argument in row["command"]
            and token_argument in row["command"]
            for row in members
        ):
            return []
        return members

    @staticmethod
    def _terminate_group(
        process: subprocess.Popen[Any],
        timeout: float = 8,
    ) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                process.terminate()
            except ProcessLookupError:
                return
        try:
            process.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except ProcessLookupError:
                return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass

    def _terminate_known_browsers(self) -> None:
        for token, record in list(self.browser_records.items()):
            try:
                if not self._owned_group_members(record):
                    continue
                try:
                    os.killpg(record["pgid"], signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    continue
                deadline = time.monotonic() + 1
                while (
                    time.monotonic() < deadline
                    and self._owned_group_members(record)
                ):
                    time.sleep(0.05)
                if not self._owned_group_members(record):
                    continue
                try:
                    os.killpg(record["pgid"], signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    continue
            finally:
                self.browser_records.pop(token, None)

    def _supervise(self, node: str) -> None:
        while not self.stop_event.is_set():
            try:
                process = subprocess.Popen(
                    [
                        node,
                        str(self.script_path),
                        "--runtime-dir",
                        str(self.runtime_dir),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as error:
                self.failures += 1
                self._publish_degraded(f"string launch failed: {type(error).__name__}")
                if self.stop_event.wait(min(30, 2 ** min(self.failures, 5))):
                    return
                continue
            with self.process_lock:
                self.process = process
            while process.poll() is None and not self.stop_event.wait(0.2):
                self._remember_browser()
            self._remember_browser()
            if self.stop_event.is_set():
                if process.stdin:
                    try:
                        process.stdin.close()
                    except OSError:
                        pass
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self._terminate_group(process)
                with self.process_lock:
                    self.process = None
                return
            returncode = process.poll()
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            with self.process_lock:
                self.process = None
            self.failures += 1
            self._terminate_known_browsers()
            self._publish_degraded(
                f"string exited with code {returncode}"
            )
            if self.stop_event.wait(min(30, 2 ** min(self.failures, 5))):
                return

    def start(self) -> bool:
        atomic_write_bytes(self.script_path, KITE_STRING_JS, 0o600)
        node = self._node_executable()
        if not node:
            self._publish_degraded("Node.js 22 or newer was not found")
            return False
        self.thread = threading.Thread(
            target=self._supervise,
            args=(node,),
            name="pokemon-kite-string",
            daemon=True,
        )
        self.thread.start()
        return True

    def stop(self) -> None:
        self.stop_event.set()
        with self.process_lock:
            process = self.process
        if process and process.stdin:
            try:
                process.stdin.close()
            except OSError:
                pass
        if self.thread:
            self.thread.join(timeout=12)
        with self.process_lock:
            process = self.process
        if process:
            self._terminate_group(process)
        self._terminate_known_browsers()
        if (
            self.profile_path.parent == self.runtime_dir
            and self.profile_path.name == f"kite-profile-{self.generation}"
        ):
            try:
                profile_metadata = self.profile_path.lstat()
            except OSError:
                profile_metadata = None
            marker = read_json(
                self.profile_path / "rpp-kite-profile.json"
            )
            if (
                profile_metadata is not None
                and stat.S_ISDIR(profile_metadata.st_mode)
                and not self.profile_path.is_symlink()
                and marker.get("schema_version") == KITE_STRING_SCHEMA_VERSION
                and marker.get("generation") == self.generation
                and isinstance(marker.get("token"), str)
                and re.fullmatch(r"[a-f0-9]{32,64}", marker["token"])
            ):
                shutil.rmtree(self.profile_path, ignore_errors=True)
        for name in self.PRIVATE_FILES:
            if name == self.OWNER_FILE:
                continue
            (self.runtime_dir / name).unlink(missing_ok=True)
        manual_return = self.runtime_dir / self.MANUAL_RETURN_DIRECTORY
        if manual_return.is_dir() and not manual_return.is_symlink():
            shutil.rmtree(manual_return, ignore_errors=True)
        for candidate in self.runtime_dir.iterdir():
            if (
                self.PRIVATE_TEMP_RE.fullmatch(candidate.name)
                and candidate.is_file()
                and not candidate.is_symlink()
            ):
                candidate.unlink(missing_ok=True)
        self.thread = None
        self.process = None


def ensure_copilot_runtime(
    timeout_seconds: int = COPILOT_DOWNLOAD_TIMEOUT_SECONDS,
) -> None:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "copilot", "download-runtime"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Copilot SDK runtime download exceeded {timeout_seconds} seconds"
        ) from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            "Copilot SDK runtime preparation failed"
            + (f": {detail[-1000:]}" if detail else "")
        )


def rom_title(path: Path) -> str:
    if is_cloud_placeholder(path):
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0x134)
            title = handle.read(16).split(b"\x00", 1)[0]
        return title.decode("ascii", errors="ignore").strip()
    except OSError:
        return ""


def is_cloud_placeholder(path: Path) -> bool:
    try:
        flags = path.stat().st_flags
    except (AttributeError, FileNotFoundError, OSError):
        return False
    return bool(flags & getattr(stat, "SF_DATALESS", 0x40000000))


def is_pokemon_red_rom(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != ".gb" or is_cloud_placeholder(path):
        return False
    title = rom_title(path).upper()
    return "POKEMON RED" in title


def discover_pokemon_red_rom(
    explicit: Optional[str] = None,
    runtime_dir: Optional[Path] = None,
) -> Path:
    if explicit:
        resolved = Path(explicit).expanduser().resolve()
        if is_cloud_placeholder(resolved):
            raise FileNotFoundError(
                f"Pokemon Red ROM is still a cloud placeholder: {resolved}"
            )
        if is_pokemon_red_rom(resolved):
            return resolved
        raise FileNotFoundError(f"Not a readable Pokemon Red Game Boy ROM: {explicit}")

    candidates: list[Path] = []

    configured = os.environ.get("OPENRAPPTER_POKEMON_ROM")
    if configured:
        candidates.append(Path(configured).expanduser())

    configured_runtime = (
        Path(runtime_dir).expanduser()
        if runtime_dir is not None
        else DEFAULT_RUNTIME_DIR
    )
    runtime_config = read_json(configured_runtime / "config.json")
    if runtime_config.get("rom_path"):
        candidates.append(Path(str(runtime_config["rom_path"])).expanduser())

    seen: set[Path] = set()
    placeholders: list[Path] = []
    resolved_candidates = sorted(
        (candidate.expanduser().resolve() for candidate in candidates),
        key=lambda path: (is_cloud_placeholder(path), str(path)),
    )
    for resolved in resolved_candidates:
        if resolved in seen:
            continue
        seen.add(resolved)
        if is_cloud_placeholder(resolved):
            placeholders.append(resolved)
            continue
        if is_pokemon_red_rom(resolved):
            return resolved

    if placeholders:
        raise FileNotFoundError(
            "Pokemon Red was found, but every copy is still a cloud placeholder: "
            + ", ".join(str(path) for path in placeholders)
        )
    raise FileNotFoundError(
        "No Pokemon Red ROM was configured. Pass rom_path or set "
        "OPENRAPPTER_POKEMON_ROM to your own legally obtained .gb file."
    )


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, character in enumerate(cleaned):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("Copilot response did not contain a JSON object")


def normalize_brain_decision(text: str) -> dict[str, Any]:
    raw = extract_json_object(text)
    raw_buttons = raw.get("buttons", [])
    if isinstance(raw_buttons, str):
        raw_buttons = [raw_buttons]
    if not isinstance(raw_buttons, list):
        raise ValueError("Copilot response field 'buttons' must be an array")

    buttons = [
        str(button).lower()
        for button in raw_buttons
        if str(button).lower() in VALID_BUTTONS
    ][:MAX_BUTTONS_PER_DECISION]
    if not buttons:
        raise ValueError("Copilot response did not contain a valid button")

    return {
        "phase": str(raw.get("phase", "unknown"))[:80],
        "observation": str(raw.get("observation", ""))[:500],
        "objective": str(raw.get("objective", ""))[:500],
        "reason": str(raw.get("reason", ""))[:500],
        "buttons": buttons,
        "checkpoint": raw.get("checkpoint") is True,
    }


def parse_agent_action(query: str) -> tuple[str, Optional[str]]:
    normalized = query.strip().lower()
    button_match = re.search(
        r"\bpress\s+(a|b|start|select|up|down|left|right)\b", normalized
    )
    if button_match:
        return "press", button_match.group(1)
    if any(word in normalized for word in ("checkpoint", "new clip", "save state")):
        return "checkpoint", None
    if "pause" in normalized:
        return "pause", None
    if any(
        phrase in normalized for phrase in ("take over", "manual control", "my control")
    ):
        return "manual", None
    if any(
        phrase in normalized
        for phrase in (
            "return to ai",
            "return to copilot",
            "autonomy",
            "continue playing",
        )
    ):
        return "autonomy", None
    if "resume" in normalized:
        return "resume", None
    if any(
        phrase in normalized
        for phrase in ("go live", "retry livestream", "retry stream")
    ):
        return "go-live", None
    if any(word in normalized for word in ("stop", "quit", "end session")):
        return "stop", None
    if any(phrase in normalized for phrase in ("share", "join link", "qr code")):
        return "share", None
    if any(phrase in normalized for phrase in ("host tab", "stream host")):
        return "host", None
    if any(word in normalized for word in ("watch", "viewer", "open window")):
        return "view", None
    if "status" in normalized or "progress" in normalized:
        return "status", None
    return "start", None


def set_desired_running(runtime_dir: Path, running: bool) -> None:
    desired_path = runtime_dir / "desired.json"
    if not desired_path.exists():
        return
    desired = read_json(desired_path)
    desired["running"] = running
    desired["updated_at"] = utc_now()
    atomic_write_json(desired_path, desired)


def wait_for_stopping_supervisor(
    runtime_dir: Path,
    timeout_seconds: float = 10,
) -> bool:
    """Wait briefly for a supervisor that has already accepted a stop."""
    desired = read_json(runtime_dir / "desired.json")
    supervisor = read_json(runtime_dir / "supervisor.json")
    supervisor_pid = supervisor.get("pid")
    if desired.get("running") is not False or not process_is_alive(supervisor_pid):
        return True
    deadline = time.monotonic() + max(0, timeout_seconds)
    while process_is_alive(supervisor_pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def seed_legacy_ram_provenance(runtime_dir: Path) -> None:
    legacy = runtime_dir / "pokemon-red.ram"
    provenance_path = runtime_dir / "legacy-ram-provenance.json"
    if not legacy.exists() or provenance_path.exists():
        return
    previous_config = read_json(runtime_dir / "config.json")
    previous_status = read_json(runtime_dir / "status.json")
    atomic_write_json(
        provenance_path,
        {
            "rom_path": previous_config.get("rom_path"),
            "rom_sha256": (
                previous_config.get("rom_sha256")
                or previous_status.get("rom_sha256")
            ),
            "recorded_at": utc_now(),
        },
    )


def append_control(runtime_dir: Path, command: dict[str, Any]) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime_dir, 0o700)
    command = {**command, "timestamp": utc_now()}
    if command.get("action") == "stop":
        set_desired_running(runtime_dir, False)
    control_path = runtime_dir / "control.jsonl"
    descriptor = os.open(control_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(command, separators=(",", ":")) + "\n")


def list_clips(runtime_dir: Path) -> list[dict[str, Any]]:
    clips = []
    for clip in sorted((runtime_dir / "clips").glob("*.mp4"), reverse=True):
        if (
            clip.name.startswith(".")
            or clip.is_symlink()
            or not GENERATED_CLIP_RE.fullmatch(clip.name)
        ):
            continue
        try:
            size = clip.stat().st_size
        except OSError:
            continue
        manifest = read_json(clip.with_suffix(".json"))
        if not (
            manifest.get("schema_version") == 1
            and manifest.get("name") == clip.name
            and manifest.get("sha256")
        ):
            continue
        clips.append(
            {
                "name": clip.name,
                "megabytes": round(size / 1_048_576, 2),
                "duration_seconds": manifest.get("duration_seconds"),
                "reason": manifest.get("reason"),
                "location": manifest.get("game_state", {}).get("location")
                if isinstance(manifest.get("game_state"), dict)
                else None,
            }
        )
    return clips[:100]


def heartbeat_age_seconds(status: dict[str, Any]) -> Optional[float]:
    heartbeat = (
        status.get("heartbeat_at")
        or status.get("updated_at")
        or status.get("started_at")
    )
    if not heartbeat:
        return None
    try:
        updated = datetime.fromisoformat(str(heartbeat))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return max(
        0.0,
        (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds(),
    )


_CHECKPOINT_KINDS = {
    "manual",
    "milestone",
    "automatic",
    "shutdown",
    "recovery",
    "progress",
    "other",
}
_DASHBOARD_MAX_ELAPSED_SECONDS = 10 * 366 * 24 * 60 * 60


def _dashboard_now(value: Optional[datetime]) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _bounded_dashboard_text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(
        "".join(
            character if character.isprintable() else " "
            for character in value[: limit * 8]
        )
        .strip()
        .split()
    )
    return cleaned[:limit] or None


def _bounded_dashboard_int(
    value: Any,
    minimum: int,
    maximum: int,
) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if minimum <= value <= maximum else None


def _dashboard_timestamp(value: Any) -> tuple[Optional[str], Optional[datetime]]:
    if not isinstance(value, str) or not 1 <= len(value) <= 48:
        return None, None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, None
    if parsed.tzinfo is None or not 2000 <= parsed.year <= 2100:
        return None, None
    utc = parsed.astimezone(timezone.utc)
    return utc.isoformat().replace("+00:00", "Z"), utc


def checkpoint_kind(value: Any) -> str:
    if isinstance(value, str) and value in _CHECKPOINT_KINDS:
        return value
    reason = value[:256].lower() if isinstance(value, str) else ""
    if "manual" in reason:
        return "manual"
    if any(
        marker in reason
        for marker in ("badge", "hall of fame", "champion", "elite four")
    ):
        return "milestone"
    if "automatic" in reason:
        return "automatic"
    if "recover" in reason or "interrupted" in reason:
        return "recovery"
    if "copilot checkpoint" in reason:
        return "progress"
    if any(
        marker in reason
        for marker in ("stopped", "shutdown", "window closed", "runtime stop")
    ):
        return "shutdown"
    return "other"


def sanitize_checkpoint_summary(
    value: Any,
    *,
    now: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    timestamp, parsed = _dashboard_timestamp(
        value.get("timestamp") or value.get("created_at")
    )
    if timestamp is None or parsed is None:
        return None
    current = _dashboard_now(now)
    age = (current - parsed).total_seconds()
    age_seconds = (
        int(max(0, age))
        if -5 <= age <= _DASHBOARD_MAX_ELAPSED_SECONDS
        else None
    )
    game_state = value.get("game_state")
    manifest_location = (
        game_state.get("location") if isinstance(game_state, dict) else None
    )
    return {
        "timestamp": timestamp,
        "kind": checkpoint_kind(value.get("kind") or value.get("reason")),
        "location": _bounded_dashboard_text(
            value.get("location") or manifest_location,
            80,
        ),
        "age_seconds": age_seconds,
    }


def _dashboard_party(value: Any) -> Optional[list[dict[str, Any]]]:
    if not isinstance(value, list):
        return None
    party: list[dict[str, Any]] = []
    for raw in value[:6]:
        if not isinstance(raw, dict):
            continue
        species_id = _bounded_dashboard_int(raw.get("species_id"), 1, 255)
        level = _bounded_dashboard_int(raw.get("level"), 1, 100)
        hp = _bounded_dashboard_int(raw.get("hp"), 0, 65535)
        max_hp = _bounded_dashboard_int(raw.get("max_hp"), 1, 65535)
        if hp is not None and max_hp is not None and hp > max_hp:
            hp = None
            max_hp = None
        party.append(
            {
                "nickname": _bounded_dashboard_text(raw.get("nickname"), 24),
                "species_id": species_id,
                "level": level,
                "hp": hp,
                "max_hp": max_hp,
            }
        )
    return party


def _dashboard_play_time(value: Any) -> Optional[dict[str, Any]]:
    if not isinstance(value, dict):
        return None
    hours = _bounded_dashboard_int(value.get("hours"), 0, 255)
    minutes = _bounded_dashboard_int(value.get("minutes"), 0, 59)
    seconds = _bounded_dashboard_int(value.get("seconds"), 0, 59)
    frames = _bounded_dashboard_int(value.get("frames"), 0, 59)
    maxed = value.get("maxed")
    if (
        hours is None
        or minutes is None
        or seconds is None
        or frames is None
        or not isinstance(maxed, bool)
    ):
        return None
    return {
        "hours": hours,
        "minutes": minutes,
        "seconds": seconds,
        "frames": frames,
        "maxed": maxed,
    }


def project_dashboard_snapshot(
    status: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Project private runtime state into the exact public dashboard schema."""
    current = _dashboard_now(now)
    game_state = (
        status.get("game_state")
        if isinstance(status.get("game_state"), dict)
        else {}
    )

    raw_badges = game_state.get("badges")
    badge_set = (
        {badge for badge in raw_badges[:64] if isinstance(badge, str)}
        if isinstance(raw_badges, list)
        else set()
    )
    earned_badges = [badge for badge in BADGE_NAMES if badge in badge_set]

    raw_pokedex = game_state.get("pokedex")
    pokedex = raw_pokedex if isinstance(raw_pokedex, dict) else {}
    caught = _bounded_dashboard_int(pokedex.get("caught"), 0, 151)
    seen = _bounded_dashboard_int(pokedex.get("seen"), 0, 151)
    raw_started_at, started_at = _dashboard_timestamp(status.get("started_at"))
    del raw_started_at
    session_elapsed_seconds: Optional[int] = None
    if started_at is not None:
        elapsed = (current - started_at).total_seconds()
        if -5 <= elapsed <= _DASHBOARD_MAX_ELAPSED_SECONDS:
            session_elapsed_seconds = int(max(0, elapsed))

    raw_livestream = status.get("livestream")
    livestream = raw_livestream if isinstance(raw_livestream, dict) else {}
    viewer_count = _bounded_dashboard_int(
        livestream.get("viewer_count"),
        0,
        HARD_MAX_VIEWERS,
    )
    viewer_capacity = _bounded_dashboard_int(
        livestream.get("max_viewers"),
        0,
        HARD_MAX_VIEWERS,
    )
    if viewer_capacity is None:
        viewer_capacity = 0
    if viewer_count is None or viewer_count > viewer_capacity:
        viewer_count = 0

    mode = status.get("control_mode")
    if mode not in {"ai", "manual", "paused"}:
        mode = "unknown"
    paused = status.get("paused")
    if not isinstance(paused, bool):
        paused = mode == "paused"

    badges_available = (
        isinstance(raw_badges, list)
        and game_state.get("badge_bits", 0) is not None
    )
    raw_party = game_state.get("party")
    party_available = (
        isinstance(raw_party, list)
        and game_state.get("party_count", len(raw_party)) is not None
    )

    snapshot = {
        "location": _bounded_dashboard_text(game_state.get("location"), 80),
        "objective": _bounded_dashboard_text(status.get("objective"), 160),
        "phase": _bounded_dashboard_text(status.get("phase"), 40),
        "badges": {
            "earned": earned_badges if badges_available else [],
            "count": len(earned_badges) if badges_available else None,
            "total": len(BADGE_NAMES),
        },
        "pokedex": {
            "caught": caught,
            "seen": seen,
            "total": 151,
        },
        "party": _dashboard_party(raw_party) if party_available else None,
        "completed": bool(
            status.get("completed") is True
            or game_state.get("hall_of_fame") is True
        ),
        "player": {
            "mode": mode,
            "paused": paused,
        },
        "play_time": _dashboard_play_time(game_state.get("play_time")),
        "session_elapsed_seconds": session_elapsed_seconds,
        "checkpoint": sanitize_checkpoint_summary(
            status.get("last_checkpoint"),
            now=current,
        ),
        "viewers": {
            "count": viewer_count,
            "capacity": viewer_capacity,
        },
    }
    encoded = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_TELEMETRY_BYTES:
        raise RuntimeError("Dashboard snapshot exceeded its public size bound")
    return snapshot


def dashboard_snapshot(
    runtime_dir: Path = DEFAULT_RUNTIME_DIR,
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    current = _dashboard_now(now)
    status = read_json(runtime_dir / "status.json", {"running": False})
    raw_livestream = status.get("livestream")
    if isinstance(raw_livestream, dict) and raw_livestream.get("enabled"):
        livestream = dict(raw_livestream)
        generation = livestream.get("generation")
        livestream.update(
            livestream_public_state(
                runtime_dir,
                expected_generation=(
                    generation if isinstance(generation, str) else None
                ),
                now=current,
            )
        )
        if livestream.get("host") == "kite":
            host_state = kite_host_public_state(
                runtime_dir,
                expected_generation=(
                    generation if isinstance(generation, str) else None
                ),
                now=current,
            )
            livestream.update(host_state)
            if (
                host_state["bridge_state"] == "degraded"
                and livestream.get("state")
                in {"connecting", "live", "reconnecting"}
            ):
                livestream.update({"state": "error", "viewer_count": 0})
        status["livestream"] = livestream
    return project_dashboard_snapshot(status, now=current)


def runtime_status(runtime_dir: Path = DEFAULT_RUNTIME_DIR) -> dict[str, Any]:
    status = read_json(runtime_dir / "status.json", {"running": False})
    lifecycle = status.get("lifecycle")
    alive = process_is_alive(status.get("pid"))
    heartbeat_age = heartbeat_age_seconds(status)
    fresh_heartbeat = bool(
        heartbeat_age is not None and heartbeat_age < STATUS_HEARTBEAT_FRESH_SECONDS
    )
    initializing = bool(
        lifecycle == "initializing"
        and heartbeat_age is not None
        and heartbeat_age < SUPERVISOR_STARTUP_TIMEOUT_SECONDS
    )
    status["running"] = bool(
        alive
        and status.get("running", True)
        and (
            initializing
            or (lifecycle == "ready" and fresh_heartbeat)
            or lifecycle is None
        )
    )
    status["clips"] = list_clips(runtime_dir)
    status["viewer_url"] = f"http://127.0.0.1:{status.get('port', DEFAULT_PORT)}"
    livestream = status.get("livestream")
    if isinstance(livestream, dict) and livestream.get("enabled"):
        generation = livestream.get("generation")
        livestream.update(
            livestream_public_state(
                runtime_dir,
                expected_generation=(
                    generation if isinstance(generation, str) else None
                ),
            )
        )
        if livestream.get("host") == "kite":
            host_state = kite_host_public_state(
                runtime_dir,
                expected_generation=(
                    generation if isinstance(generation, str) else None
                ),
            )
            livestream.update(host_state)
            if (
                host_state["bridge_state"] == "degraded"
                and livestream.get("state")
                in {"connecting", "live", "reconnecting"}
            ):
                livestream.update({"state": "error", "viewer_count": 0})
        status["livestream"] = livestream
    return status


def heartbeat_is_stale(status: dict[str, Any], threshold_seconds: int = 30) -> bool:
    age = heartbeat_age_seconds(status)
    return age is None or age > threshold_seconds


def authenticated_viewer_url(
    runtime_dir: Path,
    status: Optional[dict[str, Any]] = None,
) -> str:
    current = status or runtime_status(runtime_dir)
    base = f"http://127.0.0.1:{current.get('port', DEFAULT_PORT)}"
    auth = read_json(runtime_dir / "viewer-auth.json")
    token = auth.get("token")
    if not isinstance(token, str) or not token:
        return base
    return f"{base}/?token={urllib.parse.quote(token, safe='')}"


def public_runtime_status(runtime_dir: Path = DEFAULT_RUNTIME_DIR) -> dict[str, Any]:
    status = runtime_status(runtime_dir)
    for key in (
        "pid",
        "rom_path",
        "rom_sha256",
        "runtime_dir",
        "loaded_state",
        "instance_id",
        "join_url",
        "peer_id",
        "watch_capability",
        "room_id",
        "room_key",
        "host_fingerprint",
    ):
        status.pop(key, None)
    current_clip = status.get("current_clip")
    if current_clip:
        status["current_clip"] = Path(str(current_clip)).name
    checkpoint = status.get("last_checkpoint")
    if isinstance(checkpoint, dict):
        status["last_checkpoint"] = {
            key: value for key, value in checkpoint.items() if key != "path"
        }
    livestream = status.get("livestream")
    if isinstance(livestream, dict):
        status["livestream"] = {
            key: value
            for key, value in livestream.items()
            if key
            in {
                "enabled",
                "state",
                "viewer_count",
                "max_viewers",
                "spectator_port",
                "updated_at",
                "generation",
                "host",
                "signaling",
                "bridge_state",
                "share_ready",
                "source_health",
                "string_health",
                "runtime_health",
                "peer_health",
                "relay_health",
                "relay_open_count",
                "relay_qualifying_count",
                "relay_total",
                "direct_health",
                "direct_peer_count",
                "candidate_types",
                "first_frame",
            }
        }
    elif livestream is not None:
        status.pop("livestream", None)
    return status


def acquire_runtime_lock(
    runtime_dir: Path,
    instance_id: str,
    lock_name: str = "player.lock",
) -> Any:
    if fcntl is None:
        raise RuntimeError("Pokemon runtime locking is unavailable on this platform")
    runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime_dir, 0o700)
    lock_path = runtime_dir / lock_name
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    handle = os.fdopen(descriptor, "r+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        handle.close()
        raise RuntimeError(
            "Another Pokemon player owns this runtime directory"
        ) from error
    handle.seek(0)
    handle.truncate()
    handle.write(instance_id)
    handle.flush()
    os.fsync(handle.fileno())
    return handle


class PokemonAgent(BasicAgent):
    def __init__(self):
        self.name = "Pokemon"
        self.metadata = {
            "name": self.name,
            "description": (
                "Let GitHub Copilot play a local Pokemon Red ROM through PyBoy. "
                "Starts a live localhost viewer, records rotating MP4 clips, and "
                "supports status, share, pause, resume, checkpoint, manual button, "
                "view, host, go-live, and stop actions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "start",
                            "status",
                            "manual",
                            "autonomy",
                            "pause",
                            "resume",
                            "checkpoint",
                            "press",
                            "view",
                            "host",
                            "go-live",
                            "share",
                            "stop",
                        ],
                        "description": "Player lifecycle or control action",
                    },
                    "query": {
                        "type": "string",
                        "description": "Natural-language player command",
                    },
                    "rom_path": {
                        "type": "string",
                        "description": "Optional local path to a Pokemon Red .gb ROM",
                    },
                    "button": {
                        "type": "string",
                        "enum": list(VALID_BUTTONS),
                        "description": "Button for the press action",
                    },
                    "visible": {
                        "type": "boolean",
                        "description": "Show the native PyBoy window in addition to the browser viewer",
                    },
                    "clip_minutes": {
                        "type": "number",
                        "description": "Automatic clip duration in minutes",
                    },
                    "port": {
                        "type": "integer",
                        "description": "Local viewer port; 0 chooses an available port",
                    },
                    "livestream": {
                        "type": "boolean",
                        "description": "Enable the direct browser-to-browser livestream",
                    },
                    "livestream_host": {
                        "type": "string",
                        "enum": ["kite", "local"],
                        "description": "Pages kited twin host (default) or legacy local browser host",
                    },
                    "signaling": {
                        "type": "string",
                        "enum": ["nostr", "peerjs"],
                        "description": "Encrypted Nostr signaling (kite default) or legacy PeerJS",
                    },
                    "browser_path": {
                        "type": "string",
                        "description": "Dedicated Chrome/Chromium executable override",
                    },
                    "host_base": {
                        "type": "string",
                        "description": "HTTPS Pages kited-host base",
                    },
                    "bridge_startup_timeout": {
                        "type": "number",
                        "description": "Bounded seconds for the Pages/CDP string bootstrap",
                    },
                    "spectator_port": {
                        "type": "integer",
                        "description": "Read-only LAN spectator asset port; 0 chooses an available port",
                    },
                    "advertised_host": {
                        "type": "string",
                        "description": "LAN hostname or IP placed in spectator join links",
                    },
                    "join_base": {
                        "type": "string",
                        "description": "Optional externally hosted HTTPS spectator page base",
                    },
                    "max_viewers": {
                        "type": "integer",
                        "description": "Peer-to-peer spectator fanout, capped at 8",
                    },
                    "open_viewer": {
                        "type": "boolean",
                        "description": "Open the authenticated loopback viewer after startup",
                    },
                    "resume": {
                        "type": "boolean",
                        "description": "Resume the newest valid checkpoint for this ROM",
                    },
                    "model": {
                        "type": "string",
                        "description": "Copilot model (defaults to gpt-5.6-sol)",
                    },
                    "decision_timeout": {
                        "type": "integer",
                        "description": "Maximum seconds for one Copilot decision",
                    },
                    "startup_timeout": {
                        "type": "number",
                        "description": "Seconds to wait for emulator, recorder, brain, and viewer readiness",
                    },
                    "max_clips": {
                        "type": "integer",
                        "description": "Maximum generated clips retained locally",
                    },
                    "max_states": {
                        "type": "integer",
                        "description": "Maximum generated save states retained locally",
                    },
                    "max_storage_gb": {
                        "type": "number",
                        "description": "Maximum storage used by generated Pokemon artifacts",
                    },
                    "min_free_gb": {
                        "type": "number",
                        "description": "Minimum free disk space preserved",
                    },
                },
                "required": [],
            },
        }
        super().__init__(name=self.name, metadata=self.metadata)

    def perform(self, **kwargs):
        runtime_dir = Path(
            str(kwargs.get("runtime_dir", DEFAULT_RUNTIME_DIR))
        ).expanduser()
        query = str(kwargs.get("query", "start"))
        inferred_action, inferred_button = parse_agent_action(query)
        action = str(kwargs.get("action") or inferred_action).lower()

        if action == "status":
            return json.dumps({"status": "success", **runtime_status(runtime_dir)})

        if action == "share":
            status = runtime_status(runtime_dir)
            if not status["running"]:
                return json.dumps(
                    {"status": "error", "message": "Pokemon player is not running"}
                )
            livestream_status = status.get("livestream")
            if not (
                isinstance(livestream_status, dict)
                and livestream_status.get("enabled")
            ):
                return json.dumps(
                    {
                        "status": "error",
                        "message": "Pokemon livestreaming is not enabled",
                    }
                )
            share = livestream_share_info(runtime_dir)
            if share is None:
                return json.dumps(
                    {
                        "status": "error",
                        "message": "Pokemon livestreaming is not enabled",
                    }
                )
            if not share.get("available"):
                return json.dumps(
                    {
                        "status": "error",
                        "message": (
                            "The kited twin is not ready to share; "
                            "check livestream health and retry"
                        ),
                        **share,
                    }
                )
            return json.dumps(
                {
                    "status": "success",
                    "message": "Private spectator join link",
                    **share,
                }
            )

        if action == "host":
            status = runtime_status(runtime_dir)
            if not status["running"]:
                return json.dumps(
                    {"status": "error", "message": "Pokemon player is not running"}
                )
            private = read_json(runtime_dir / "livestream-auth.json")
            if (
                not private.get("enabled")
                or private.get("livestream_host") != "kite"
            ):
                return json.dumps(
                    {
                        "status": "error",
                        "message": (
                            "The managed Pages host is available only when "
                            "livestream_host is kite"
                        ),
                    }
                )
            generation = private.get("generation")
            instance = private.get("instance")
            if not (
                isinstance(generation, str)
                and isinstance(instance, str)
            ):
                return json.dumps(
                    {
                        "status": "error",
                        "message": "The kited twin bootstrap is unavailable",
                    }
                )
            previous = read_json(runtime_dir / "kite-command.json")
            try:
                sequence = max(0, int(previous.get("sequence", 0))) + 1
            except (TypeError, ValueError):
                sequence = 1
            atomic_write_json(
                runtime_dir / "kite-command.json",
                {
                    "schema_version": KITE_STRING_SCHEMA_VERSION,
                    "generation": generation,
                    "instance": instance,
                    "sequence": sequence,
                    "action": "focus",
                },
            )
            return json.dumps(
                {
                    "status": "success",
                    "message": "Asked the managed browser to focus the Pages host",
                    "livestream": status.get("livestream"),
                }
            )

        if action == "go-live":
            status = runtime_status(runtime_dir)
            if not status["running"]:
                return json.dumps(
                    {"status": "error", "message": "Pokemon player is not running"}
                )
            private = read_json(runtime_dir / "livestream-auth.json")
            generation = private.get("generation")
            instance = private.get("instance")
            if not (
                private.get("enabled")
                and private.get("livestream_host") == "kite"
                and isinstance(generation, str)
                and isinstance(instance, str)
            ):
                return json.dumps(
                    {
                        "status": "error",
                        "message": (
                            "Go Live is available only for the managed "
                            "Pages livestream host"
                        ),
                    }
                )
            desired_path = runtime_dir / "kite-broadcast-state.json"
            previous = read_json(desired_path)
            if (
                previous.get("generation") != generation
                or previous.get("instance") != instance
            ):
                previous = {}
            try:
                sequence = max(0, int(previous.get("sequence", 0))) + 1
            except (TypeError, ValueError):
                sequence = 1
            atomic_write_json(
                desired_path,
                {
                    "schema_version": KITE_STRING_SCHEMA_VERSION,
                    "generation": generation,
                    "instance": instance,
                    "sequence": sequence,
                    "desired": True,
                    "updated_at": utc_now(),
                },
            )
            return json.dumps(
                {
                    "status": "success",
                    "message": "Asked the managed Pages host to go live",
                    "livestream": status.get("livestream"),
                }
            )

        if action == "view":
            status = runtime_status(runtime_dir)
            if not status["running"]:
                return json.dumps(
                    {"status": "error", "message": "Pokemon player is not running"}
                )
            viewer_url = authenticated_viewer_url(runtime_dir, status)
            webbrowser.open(viewer_url)
            return json.dumps(
                {
                    "status": "success",
                    "message": "Opened the local Pokemon viewer",
                    "viewer_url": viewer_url,
                }
            )

        if action in {
            "manual",
            "autonomy",
            "pause",
            "resume",
            "checkpoint",
            "stop",
            "press",
        }:
            status = runtime_status(runtime_dir)
            if action == "stop" and not status["running"]:
                desired = read_json(runtime_dir / "desired.json")
                supervisor = read_json(runtime_dir / "supervisor.json")
                supervisor_alive = process_is_alive(supervisor.get("pid"))
                if desired.get("running") or supervisor_alive:
                    set_desired_running(runtime_dir, False)
                    return json.dumps(
                        {
                            "status": "success",
                            "message": "Pokemon supervisor accepted stop",
                            "viewer_url": authenticated_viewer_url(runtime_dir, status),
                        }
                    )
            if not status["running"]:
                return json.dumps(
                    {"status": "error", "message": "Pokemon player is not running"}
                )
            button = str(kwargs.get("button") or inferred_button or "").lower()
            if action == "press" and button not in VALID_BUTTONS:
                return json.dumps(
                    {
                        "status": "error",
                        "message": f"button must be one of: {', '.join(VALID_BUTTONS)}",
                    }
                )
            append_control(runtime_dir, {"action": action, "button": button or None})
            return json.dumps(
                {
                    "status": "success",
                    "message": f"Pokemon player accepted {action}",
                    "viewer_url": authenticated_viewer_url(runtime_dir, status),
                }
            )

        if action != "start":
            return json.dumps(
                {"status": "error", "message": f"Unknown Pokemon action: {action}"}
            )

        stopping = (
            read_json(runtime_dir / "desired.json").get("running") is False
            and process_is_alive(
                read_json(runtime_dir / "supervisor.json").get("pid")
            )
        )
        if stopping and not wait_for_stopping_supervisor(runtime_dir):
            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        "Pokemon player is still stopping; start can be retried "
                        "when shutdown completes"
                    ),
                    "retryable": True,
                }
            )

        existing = runtime_status(runtime_dir)
        if existing["running"]:
            return json.dumps(
                {
                    "status": "success",
                    "message": "Pokemon player is already running",
                    **existing,
                    "viewer_url": authenticated_viewer_url(runtime_dir, existing),
                }
            )

        try:
            rom = discover_pokemon_red_rom(kwargs.get("rom_path"), runtime_dir)
        except (FileNotFoundError, OSError) as error:
            return json.dumps({"status": "error", "message": str(error)})

        if importlib.util.find_spec("pyboy") is None:
            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        "PyBoy is not installed in this Python environment. "
                        'Install runtime dependencies with pip install -e ".[runtime]".'
                    ),
                }
            )
        if sys.version_info < (3, 11) or importlib.util.find_spec("copilot") is None:
            return json.dumps(
                {
                    "status": "error",
                    "message": (
                        "The Pokemon player requires Python 3.11+ and the "
                        "github-copilot-sdk package"
                    ),
                }
            )
        if not shutil.which("ffmpeg"):
            return json.dumps({"status": "error", "message": "ffmpeg is not installed"})
        try:
            ensure_copilot_runtime()
        except RuntimeError as error:
            return json.dumps({"status": "error", "message": str(error)})

        try:
            port = validate_livestream_port(kwargs.get("port", DEFAULT_PORT), "port")
            livestream_value = kwargs.get("livestream", False)
            if not isinstance(livestream_value, bool):
                raise ValueError("livestream must be a boolean")
            livestream_enabled = livestream_value
            livestream_host = str(
                kwargs.get("livestream_host", DEFAULT_LIVESTREAM_HOST)
            ).lower()
            if livestream_host not in {"kite", "local"}:
                raise ValueError("livestream_host must be kite or local")
            signaling_value = kwargs.get("signaling")
            signaling = (
                str(signaling_value).lower()
                if signaling_value is not None
                else (
                    DEFAULT_SIGNALING
                    if livestream_host == "kite"
                    else "peerjs"
                )
            )
            if signaling not in {"nostr", "peerjs"}:
                raise ValueError("signaling must be nostr or peerjs")
            if livestream_host == "local" and signaling != "peerjs":
                raise ValueError(
                    "local livestream hosting supports signaling peerjs only"
                )
            spectator_port = validate_livestream_port(
                kwargs.get("spectator_port", DEFAULT_SPECTATOR_PORT),
                "spectator_port",
            )
            max_viewers_value = kwargs.get("max_viewers", DEFAULT_MAX_VIEWERS)
            if isinstance(max_viewers_value, bool):
                raise ValueError("max_viewers must be an integer")
            max_viewers = int(max_viewers_value)
            advertised_host_value = kwargs.get("advertised_host")
            advertised_host = (
                validate_advertised_host(str(advertised_host_value))
                if advertised_host_value
                else None
            )
            join_base_value = kwargs.get("join_base")
            join_base = (
                validate_external_join_base(str(join_base_value))
                if join_base_value
                else None
            )
            host_base_value = kwargs.get("host_base", DEFAULT_PAGES_HOST_BASE)
            host_base = validate_external_join_base(str(host_base_value))
            browser_path_value = (
                kwargs.get("browser_path")
                or os.environ.get("RPP_BROWSER_PATH")
                or os.environ.get("CHROME_PATH")
            )
            browser_path = (
                str(Path(str(browser_path_value)).expanduser().resolve())
                if browser_path_value
                else ""
            )
            bridge_startup_timeout = float(
                kwargs.get(
                    "bridge_startup_timeout",
                    DEFAULT_BRIDGE_STARTUP_TIMEOUT_SECONDS,
                )
            )
            clip_minutes = float(kwargs.get("clip_minutes", 10))
            startup_timeout_requested = float(
                kwargs.get("startup_timeout", SUPERVISOR_STARTUP_TIMEOUT_SECONDS)
            )
            max_clips = int(kwargs.get("max_clips", DEFAULT_MAX_CLIPS))
            max_states = int(kwargs.get("max_states", DEFAULT_MAX_STATES))
            max_storage_gb = float(kwargs.get("max_storage_gb", DEFAULT_MAX_STORAGE_GB))
            min_free_gb = float(kwargs.get("min_free_gb", DEFAULT_MIN_FREE_GB))
            decision_timeout = int(kwargs.get("decision_timeout", 180))
        except (TypeError, ValueError) as error:
            return json.dumps(
                {
                    "status": "error",
                    "message": f"Invalid Pokemon configuration: {error}",
                }
            )
        if not 1 <= max_viewers <= HARD_MAX_VIEWERS:
            return json.dumps(
                {
                    "status": "error",
                    "message": f"max_viewers must be 1-{HARD_MAX_VIEWERS}",
                }
            )
        if (
            clip_minutes <= 0
            or max_clips < 1
            or max_states < 2
            or max_storage_gb <= 0
            or min_free_gb < 0
            or decision_timeout < 10
            or not 2 <= bridge_startup_timeout <= 120
        ):
            return json.dumps(
                {
                    "status": "error",
                    "message": "Retention, timing, and storage values must be positive",
                }
            )

        runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(runtime_dir, 0o700)
        atomic_write_json(
            runtime_dir / "runtime-owner.json",
            {
                "product": "rappter-plays-pokemon",
                "created_at": utc_now(),
            },
        )
        previous_config = read_json(runtime_dir / "config.json")
        seed_legacy_ram_provenance(runtime_dir)
        atomic_write_json(
            runtime_dir / "config.json",
            {
                "rom_path": str(rom),
                "rom_sha256": file_sha256(rom),
                "previous_rom_path": previous_config.get("rom_path"),
                "previous_rom_sha256": previous_config.get("rom_sha256"),
                "updated_at": utc_now(),
            },
        )
        log_descriptor = os.open(
            runtime_dir / "player.log",
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        log_handle = os.fdopen(log_descriptor, "a", encoding="utf-8")
        instance_id = uuid.uuid4().hex
        command = [
            sys.executable,
            "-m",
            MODULE_NAME,
            "supervise",
            "--rom",
            str(rom),
            "--runtime-dir",
            str(runtime_dir),
            "--port",
            str(port),
            "--clip-minutes",
            str(clip_minutes),
            "--model",
            str(kwargs.get("model", "gpt-5.6-sol")),
            "--decision-timeout",
            str(decision_timeout),
            "--instance-id",
            instance_id,
            "--max-clips",
            str(max_clips),
            "--max-states",
            str(max_states),
            "--max-storage-gb",
            str(max_storage_gb),
            "--min-free-gb",
            str(min_free_gb),
            "--livestream-host",
            livestream_host,
            "--signaling",
            signaling,
            "--browser-path",
            browser_path,
            "--host-base",
            host_base,
            "--bridge-startup-timeout",
            str(bridge_startup_timeout),
        ]
        if livestream_enabled:
            command.extend(
                [
                    "--livestream",
                    "--spectator-port",
                    str(spectator_port),
                    "--max-viewers",
                    str(max_viewers),
                ]
            )
            if advertised_host:
                command.extend(["--advertised-host", advertised_host])
            if join_base:
                command.extend(["--join-base", join_base])
        if (
            kwargs.get("open_viewer", True)
            or (livestream_enabled and livestream_host == "local")
        ):
            command.append("--open-viewer")
        if kwargs.get("visible", False):
            command.append("--visible")
        if kwargs.get("resume", True) is False:
            command.append("--no-resume")
        process = subprocess.Popen(
            command,
            cwd=str(runtime_dir),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log_handle.close()
        minimum_startup_timeout = (
            COPILOT_START_TIMEOUT_SECONDS + COPILOT_STOP_TIMEOUT_SECONDS * 2 + 10
        )
        startup_timeout = max(
            startup_timeout_requested,
            minimum_startup_timeout,
        )
        deadline = time.monotonic() + startup_timeout
        viewer_url = f"http://127.0.0.1:{port}"
        while time.monotonic() < deadline:
            child_status = read_json(runtime_dir / "status.json")
            child_instance = child_status.get("instance_id")
            lifecycle = child_status.get("lifecycle")
            if child_instance == instance_id and lifecycle == "ready":
                viewer_url = authenticated_viewer_url(runtime_dir, child_status)
                return json.dumps(
                    {
                        "status": "success",
                        "message": "Copilot Plays Pokemon Red is ready",
                        "pid": child_status.get("pid"),
                        "supervisor_pid": process.pid,
                        "rom_title": rom_title(rom),
                        "viewer_url": viewer_url,
                        "recordings": str(runtime_dir / "clips"),
                        "brain_backend": child_status.get("brain_backend"),
                        "livestream": child_status.get(
                            "livestream",
                            {"enabled": False},
                        ),
                    }
                )
            if (
                child_instance
                and child_instance != instance_id
                and lifecycle == "ready"
                and process_is_alive(child_status.get("pid"))
            ):
                viewer_url = authenticated_viewer_url(runtime_dir, child_status)
                return json.dumps(
                    {
                        "status": "success",
                        "message": "Pokemon player is already running",
                        "viewer_url": viewer_url,
                    }
                )
            if process.poll() is not None:
                detail = (
                    child_status.get("last_error")
                    if child_instance == instance_id
                    else None
                )
                return json.dumps(
                    {
                        "status": "error",
                        "message": detail
                        or f"Pokemon player exited with code {process.returncode}",
                    }
                )
            time.sleep(0.2)
        set_desired_running(runtime_dir, False)
        terminate_isolated_process_group(process)
        final_status = read_json(runtime_dir / "status.json")
        detail = (
            final_status.get("last_error")
            if final_status.get("instance_id") == instance_id
            else None
        )
        return json.dumps(
            {
                "status": "error",
                "message": (
                    str(detail)
                    if detail
                    else "Pokemon player did not become ready before the startup timeout"
                ),
            }
        )


class PokemonMemoryReader:
    def __init__(self, memory: Any):
        self.memory = memory

    def _read_optional(self, address: int) -> Optional[int]:
        try:
            raw = self.memory[address]
            if isinstance(raw, bool):
                return None
            value = int(raw)
            if raw != value or not 0 <= value <= 0xFF:
                return None
            return value
        except (
            IndexError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
            AttributeError,
            RuntimeError,
        ):
            return None

    def _read(self, address: int, default: int = 0) -> int:
        value = self._read_optional(address)
        return default if value is None else value

    def _bitfield_count(self, start: int) -> Optional[int]:
        values = [self._read_optional(start + offset) for offset in range(19)]
        if any(value is None for value in values):
            return None
        bitfield = [int(value) for value in values if value is not None]
        return sum(
            1
            for index in range(151)
            if bitfield[index // 8] & (1 << (index % 8))
        )

    def pokedex_counts(self) -> dict[str, Optional[int]]:
        return {
            "caught": self._bitfield_count(0xD2F7),
            "seen": self._bitfield_count(0xD30A),
        }

    def play_time(self) -> Optional[dict[str, Any]]:
        values = [
            self._read_optional(address)
            for address in (0xDA41, 0xDA42, 0xDA43, 0xDA44, 0xDA45)
        ]
        if any(value is None for value in values):
            return None
        hours, max_flag, minutes, seconds, frames = values
        if (
            max_flag not in {0, 0xFF}
            or minutes is None
            or not 0 <= minutes <= 59
            or seconds is None
            or not 0 <= seconds <= 59
            or frames is None
            or not 0 <= frames <= 59
        ):
            return None
        return {
            "hours": hours,
            "minutes": minutes,
            "seconds": seconds,
            "frames": frames,
            "maxed": max_flag == 0xFF,
        }

    def _text(self, start: int, length: int) -> str:
        output = []
        for address in range(start, start + length):
            value = self._read(address)
            if value == 0x50:
                break
            if 0x80 <= value <= 0x99:
                output.append(chr(value - 0x80 + ord("A")))
            elif 0xA0 <= value <= 0xB9:
                output.append(chr(value - 0xA0 + ord("a")))
            elif 0xF6 <= value <= 0xFF:
                output.append(str(value - 0xF6))
            elif value == 0x7F:
                output.append(" ")
            elif value in (0xE8, 0xE9):
                output.append(".")
            elif value == 0xE6:
                output.append("?")
            elif value == 0xE7:
                output.append("!")
            elif value == 0xF4:
                output.append(",")
            elif value == 0xE3:
                output.append("-")
        return "".join(output).strip()

    def _screen_text(self) -> str:
        lines: list[str] = []
        current: list[str] = []
        spaces = 0
        for address in range(0xC3A0, 0xC507):
            value = self._read(address)
            character = ""
            if 0x80 <= value <= 0x99:
                character = chr(value - 0x80 + ord("A"))
            elif 0xA0 <= value <= 0xB9:
                character = chr(value - 0xA0 + ord("a"))
            elif 0xF6 <= value <= 0xFF:
                character = str(value - 0xF6)
            elif value == 0x7F:
                character = " "
            elif value in (0xE8, 0xE9):
                character = "."
            elif value == 0xE6:
                character = "?"
            elif value == 0xE7:
                character = "!"
            elif value == 0xF4:
                character = ","
            elif value == 0xE3:
                character = "-"
            elif value in (0x4E, 0x7C):
                if "".join(current).strip():
                    lines.append("".join(current).strip())
                current = []
                spaces = 0
                continue

            if character:
                current.append(character)
                spaces = spaces + 1 if character == " " else 0
                if spaces > 10:
                    if "".join(current).strip():
                        lines.append("".join(current).strip())
                    current = []
                    spaces = 0
        if "".join(current).strip():
            lines.append("".join(current).strip())
        deduplicated = list(dict.fromkeys(line for line in lines if len(line) > 1))
        return " | ".join(deduplicated[-8:])[:600]

    def snapshot(self) -> dict[str, Any]:
        map_id = self._read_optional(0xD35E)
        badge_byte = self._read_optional(0xD356)
        raw_party_count = self._read_optional(0xD163)
        party_count = (
            raw_party_count
            if raw_party_count is not None and 0 <= raw_party_count <= 6
            else None
        )
        party = []
        bases = (0xD16B, 0xD197, 0xD1C3, 0xD1EF, 0xD21B, 0xD247)
        nicknames = (0xD2B5, 0xD2C0, 0xD2CB, 0xD2D6, 0xD2E1, 0xD2EC)
        for index in range(party_count or 0):
            base = bases[index]
            party.append(
                {
                    "nickname": self._text(nicknames[index], 11),
                    "species_id": self._read(base),
                    "level": self._read(base + 0x21),
                    "hp": (self._read(base + 1) << 8) + self._read(base + 2),
                    "max_hp": (self._read(base + 0x22) << 8) + self._read(base + 0x23),
                }
            )
        return {
            "map_id": map_id,
            "location": (
                MAP_NAMES.get(map_id, f"Map 0x{map_id:02X}")
                if map_id is not None
                else None
            ),
            "coordinates": {
                "x": self._read(0xD362),
                "y": self._read(0xD361),
            },
            "player_name": self._text(0xD158, 11),
            "rival_name": self._text(0xD34A, 8),
            "badges": [
                name
                for bit, name in enumerate(BADGE_NAMES)
                if badge_byte is not None and badge_byte & (1 << bit)
            ],
            "badge_bits": badge_byte,
            "party_count": party_count,
            "party": party,
            "pokedex": {
                **self.pokedex_counts(),
                "total": 151,
            },
            "play_time": self.play_time(),
            "screen_text": self._screen_text(),
            "hall_of_fame": map_id == 0x76 if map_id is not None else False,
        }


def collision_ascii(pyboy: Any) -> Optional[str]:
    try:
        collision = pyboy.game_wrapper.game_area_collision()
        rows, columns = collision.shape
        if rows < 9 or columns < 10:
            return None
        row_step = max(1, rows // 9)
        column_step = max(1, columns // 10)
        output = []
        for row in range(9):
            characters = []
            for column in range(10):
                if row == 4 and column == 4:
                    characters.append("P")
                    continue
                values = collision[
                    row * row_step : min(rows, (row + 1) * row_step),
                    column * column_step : min(columns, (column + 1) * column_step),
                ]
                characters.append("." if bool(values.any()) else "#")
            output.append("".join(characters))
        return "\n".join(output)
    except (AttributeError, IndexError, TypeError, ValueError):
        return None


def rock_tunnel_route_guidance(game_state: dict[str, Any]) -> Optional[str]:
    map_id = game_state.get("map_id")
    coordinates = game_state.get("coordinates")
    if not isinstance(coordinates, dict):
        return None
    x = coordinates.get("x")
    y = coordinates.get("y")
    if not isinstance(x, int) or not isinstance(y, int):
        return None
    if map_id == 232:
        if x >= 24 or y >= 20:
            return (
                "Authoritative route stage: navigate to B1F ladder (27,3). "
                "Do not use Dig and do not route toward (3,33)."
            )
        return (
            "Authoritative route stage: navigate to B1F ladder (3,3), "
            "then take it to Rock Tunnel 1F. Never use Dig."
        )
    if map_id == 82:
        if x <= 10:
            return "Authoritative route stage: navigate to 1F ladder (17,11)."
        if x >= 30 and y >= 12:
            return (
                "Authoritative final stage: navigate to the south exit at "
                "(15,33) or (15,35), then continue south toward Lavender Town."
            )
        if y <= 8:
            return "Authoritative route stage: navigate to 1F ladder (37,3)."
        return (
            "Authoritative final stage: navigate to the south exit at "
            "(15,33) or (15,35)."
        )
    return None


def celadon_route_guidance(game_state: dict[str, Any]) -> Optional[str]:
    badges = game_state.get("badges")
    if isinstance(badges, list) and "Rainbow" in badges:
        return None
    map_id = game_state.get("map_id")
    if map_id == 6:
        return (
            "Authoritative Celadon objective: the Gym entrance warp is exactly "
            "at (12,27). Navigate to (12,27); if the hedge immediately north "
            "blocks entry, use Cut once and step south into the warp."
        )
    if map_id == 134:
        return (
            "Authoritative Celadon Gym objective: reach Erika at (4,3), "
            "defeat her, and obtain the Rainbow Badge."
        )
    return None


class ClipRecorder:
    def __init__(self, runtime_dir: Path, fps: int = 30):
        self.clips_dir = runtime_dir / "clips"
        self.clips_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.clips_dir, 0o700)
        self.fps = fps
        self.process: Optional[subprocess.Popen[bytes]] = None
        self.stderr_handle: Optional[Any] = None
        self.partial_path: Optional[Path] = None
        self.final_path: Optional[Path] = None
        self.frames_written = 0
        self.frames_dropped = 0
        self.started_at: Optional[str] = None
        self.frame_queue: "queue.Queue[Optional[bytes]]" = queue.Queue(
            maxsize=max(1, fps * RECORDER_QUEUE_SECONDS)
        )
        self.writer_thread: Optional[threading.Thread] = None
        self.writer_error: Optional[Exception] = None

    def _next_index(self) -> int:
        indexes = []
        for path in self.clips_dir.glob("clip-*.mp4"):
            match = re.match(r"clip-(\d+)-", path.name)
            manifest = read_json(path.with_suffix(".json"))
            if (
                match
                and GENERATED_CLIP_RE.fullmatch(path.name)
                and manifest.get("schema_version") == 1
                and manifest.get("name") == path.name
                and manifest.get("sha256")
            ):
                indexes.append(int(match.group(1)))
        for path in self.clips_dir.glob(".clip-*.partial.mp4"):
            match = re.match(r"\.clip-(\d+)-", path.name)
            if match and GENERATED_PARTIAL_RE.fullmatch(path.name):
                indexes.append(int(match.group(1)))
        return max(indexes, default=0) + 1

    def start(self) -> Path:
        if self.process:
            raise RuntimeError("Recorder is already running")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required for Pokemon recording")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        index = self._next_index()
        while True:
            self.final_path = self.clips_dir / f"clip-{index:04d}-{timestamp}.mp4"
            self.partial_path = self.clips_dir / f".{self.final_path.name}.partial.mp4"
            if not self.final_path.exists() and not self.partial_path.exists():
                break
            index += 1
        error_path = self.clips_dir / f".{self.final_path.name}.ffmpeg.log"
        self.stderr_handle = error_path.open("ab")
        self.process = subprocess.Popen(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-s",
                "160x144",
                "-r",
                str(self.fps),
                "-i",
                "pipe:0",
                "-an",
                "-vf",
                "scale=640:576:flags=neighbor",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(self.partial_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self.stderr_handle,
            bufsize=0,
        )
        self.frames_written = 0
        self.frames_dropped = 0
        self.started_at = utc_now()
        self.frame_queue = queue.Queue(
            maxsize=max(1, self.fps * RECORDER_QUEUE_SECONDS)
        )
        self.writer_error = None
        self.writer_thread = threading.Thread(
            target=self._writer_loop,
            name="pokemon-ffmpeg-writer",
            daemon=False,
        )
        self.writer_thread.start()
        return self.final_path

    def _writer_loop(self) -> None:
        process = self.process
        if not process or not process.stdin:
            self.writer_error = RuntimeError("ffmpeg writer started without stdin")
            return
        try:
            while True:
                payload = self.frame_queue.get()
                if payload is None:
                    return
                remaining = memoryview(payload)
                while remaining:
                    written = process.stdin.write(remaining)
                    if not written:
                        raise BrokenPipeError("ffmpeg accepted zero frame bytes")
                    remaining = remaining[written:]
        except (BrokenPipeError, OSError) as error:
            self.writer_error = error

    def write(self, image: Any) -> bool:
        if not self.process or not self.process.stdin:
            raise RuntimeError("Recorder has not started")
        if self.writer_error:
            raise RuntimeError("ffmpeg frame writer failed") from self.writer_error
        exit_code = self.process.poll()
        if exit_code is not None:
            raise RuntimeError(f"ffmpeg exited unexpectedly with code {exit_code}")
        try:
            self.frame_queue.put_nowait(image.convert("RGB").tobytes())
        except queue.Full:
            self.frames_dropped += 1
            return False
        self.frames_written += 1
        return True

    def _stop_writer(self, process: subprocess.Popen[bytes]) -> None:
        while True:
            try:
                self.frame_queue.put_nowait(None)
                break
            except queue.Full:
                try:
                    self.frame_queue.get_nowait()
                    self.frames_dropped += 1
                except queue.Empty:
                    continue
        if self.writer_thread:
            self.writer_thread.join(timeout=RECORDER_WRITER_TIMEOUT_SECONDS)
            if self.writer_thread.is_alive():
                process.terminate()
                try:
                    process.wait(timeout=RECORDER_WRITER_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=RECORDER_WRITER_TIMEOUT_SECONDS)
                self.writer_thread.join(timeout=RECORDER_WRITER_TIMEOUT_SECONDS)
            if self.writer_thread.is_alive():
                raise RuntimeError(
                    "ffmpeg writer did not stop after process termination"
                )

    def finish(self) -> Optional[Path]:
        process = self.process
        partial_path = self.partial_path
        final_path = self.final_path
        if not process:
            return None
        self._stop_writer(process)
        if process.stdin and not process.stdin.closed:
            try:
                process.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        try:
            exit_code = process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                exit_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                exit_code = process.wait(timeout=5)
        if self.stderr_handle:
            self.stderr_handle.close()
        self.process = None
        self.stderr_handle = None
        self.partial_path = None
        self.final_path = None
        self.writer_thread = None
        if exit_code != 0:
            raise RuntimeError(f"ffmpeg failed to finalize clip with code {exit_code}")
        if self.writer_error:
            raise RuntimeError("ffmpeg frame writer failed") from self.writer_error
        if not partial_path or not final_path or self.frames_written == 0:
            if partial_path:
                partial_path.unlink(missing_ok=True)
            return None
        os.replace(partial_path, final_path)
        os.chmod(final_path, 0o600)
        fsync_directory(final_path.parent)
        return final_path


GAME_SYSTEM_PROMPT = f"""You are the autonomous player in Copilot Plays Pokemon Red.
Your long-term goal is to finish Pokemon Red and enter the Hall of Fame.
Each user message includes the current game state and a PNG screenshot.
Never use tools. Return only the requested JSON object.

Make progress deliberately:
- Advance title screens and dialogue with A or Start.
- Prefer Squirtle if choosing a starter, but adapt to existing progress.
- In battle, read the screen before choosing Fight, a move, an item, or Run.
- In the overworld, use the local collision grid and coordinates to avoid loops.
- Never use Dig outside battle while traversing a cave; it returns to the
  entrance and discards traversal progress.
- Follow Rock Tunnel's verified warp sequence from the north entrance:
  1F ladder (37,3) -> B1F ladder (27,3) -> 1F ladder (17,11) ->
  B1F ladder (3,3) -> 1F south exit (15,33) or (15,35).
  B1F (3,33) is not an exit; do not route there.
- Do not issue more than {MAX_BUTTONS_PER_DECISION} buttons. Repeated directions
  are allowed, but avoid long blind walks.
- Set checkpoint true after a badge, major story event, new important location,
  or other moment worth ending the current recording clip.

Valid buttons are: {", ".join(VALID_BUTTONS)}."""


class CopilotBrain:
    def __init__(
        self,
        model: str,
        runtime_dir: Path,
        timeout_seconds: int = 180,
        max_decisions_per_session: int = MAX_DECISIONS_PER_SESSION,
    ):
        self.model = model
        self.runtime_dir = runtime_dir
        self.timeout_seconds = timeout_seconds
        self.max_decisions_per_session = max_decisions_per_session
        if sys.version_info < (3, 11) or importlib.util.find_spec("copilot") is None:
            raise RuntimeError(
                "Copilot Plays Pokemon requires Python 3.11+ and github-copilot-sdk"
            )
        self.backend = "sdk"
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.client: Any = None
        self.session: Any = None
        self.session_decisions = 0
        self.current_task: Optional[asyncio.Task[Any]] = None

    def _run_operation(self, operation: Any, timeout: float) -> Any:
        if not self.loop:
            raise RuntimeError("Copilot SDK event loop is not running")
        task = self.loop.create_task(operation)
        self.current_task = task
        try:
            return self.loop.run_until_complete(asyncio.wait_for(task, timeout=timeout))
        finally:
            self.current_task = None

    def cancel(self) -> None:
        if self.loop and self.current_task and not self.current_task.done():
            self.loop.call_soon_threadsafe(self.current_task.cancel)

    def start(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self._run_operation(
                self._start_sdk(),
                timeout=COPILOT_START_TIMEOUT_SECONDS,
            )
        except (Exception, asyncio.CancelledError) as error:
            try:
                if self.client:
                    self._run_operation(
                        self.client.force_stop(),
                        timeout=COPILOT_STOP_TIMEOUT_SECONDS,
                    )
            except (Exception, asyncio.CancelledError) as cleanup_error:
                LOGGER.error(
                    "Failed to clean up partial Copilot SDK client: %s",
                    cleanup_error,
                )
            self.client = None
            self.session = None
            self.loop.close()
            self.loop = None
            raise RuntimeError(f"Copilot SDK startup failed: {error}") from error

    async def _start_sdk(self) -> None:
        from copilot import CopilotClient

        copilot_home = self.runtime_dir / "copilot"
        copilot_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(copilot_home, 0o700)
        self.client = CopilotClient(
            mode="empty",
            base_directory=str(copilot_home),
            working_directory=str(self.runtime_dir),
            log_level="error",
            session_idle_timeout_seconds=0,
        )
        await self.client.start()
        await self._create_sdk_session()

    async def _create_sdk_session(self) -> None:
        self.session = await self.client.create_session(
            model=self.model,
            reasoning_effort="max",
            system_message={"mode": "replace", "content": GAME_SYSTEM_PROMPT},
            available_tools=[],
            skip_custom_instructions=True,
            enable_session_store=False,
            enable_session_telemetry=False,
            enable_config_discovery=False,
            enable_on_demand_instruction_discovery=False,
            enable_skills=False,
            infinite_sessions={"enabled": False},
            memory={"enabled": False},
        )
        self.session_decisions = 0

    def decide(
        self,
        screenshot: Path,
        game_state: dict[str, Any],
        collision_map: Optional[str],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = self._prompt(game_state, collision_map, history)
        if not self.loop or not self.session:
            raise RuntimeError("Copilot SDK session is not running")
        return self._run_operation(
            self._decide_sdk(screenshot, prompt),
            timeout=float(self.timeout_seconds + COPILOT_STOP_TIMEOUT_SECONDS),
        )

    async def _decide_sdk(self, screenshot: Path, prompt: str) -> dict[str, Any]:
        if self.session_decisions >= self.max_decisions_per_session:
            await self.session.disconnect()
            await self._create_sdk_session()

        attachment = {
            "type": "blob",
            "data": base64.b64encode(screenshot.read_bytes()).decode("ascii"),
            "mimeType": "image/png",
        }
        response = await self.session.send_and_wait(
            prompt,
            attachments=[attachment],
            timeout=float(self.timeout_seconds),
        )
        if response is None or not hasattr(response.data, "content"):
            raise RuntimeError("Copilot SDK returned no assistant message")
        self.session_decisions += 1
        return normalize_brain_decision(response.data.content)

    def close(self) -> None:
        if not self.loop:
            return
        cleanup_failed = False
        try:
            if self.session:
                try:
                    self._run_operation(
                        self.session.disconnect(),
                        timeout=COPILOT_STOP_TIMEOUT_SECONDS,
                    )
                except (Exception, asyncio.CancelledError):
                    cleanup_failed = True
                    LOGGER.exception("Copilot session disconnect failed")
            if self.client:
                try:
                    self._run_operation(
                        self.client.stop(),
                        timeout=COPILOT_STOP_TIMEOUT_SECONDS,
                    )
                except (Exception, asyncio.CancelledError):
                    cleanup_failed = True
                    LOGGER.exception("Copilot client stop failed")
                if cleanup_failed:
                    try:
                        self._run_operation(
                            self.client.force_stop(),
                            timeout=COPILOT_STOP_TIMEOUT_SECONDS,
                        )
                    except (Exception, asyncio.CancelledError):
                        LOGGER.exception("Copilot client force-stop failed")
        finally:
            self.session = None
            self.client = None
            if self.current_task and not self.current_task.done():
                self.current_task.cancel()
            self.current_task = None
            if self.loop.is_running():
                self.loop.stop()
            if not self.loop.is_closed():
                self.loop.close()
            self.loop = None

    def recover(self) -> None:
        self.close()
        self.start()

    @staticmethod
    def _prompt(
        game_state: dict[str, Any],
        collision_map: Optional[str],
        history: list[dict[str, Any]],
    ) -> str:
        history_json = json.dumps(history[-8:], separators=(",", ":"))
        state_json = json.dumps(game_state, separators=(",", ":"))
        collision = collision_map or "Unavailable; rely on the screenshot."
        return f"""The attached image is the current 160x144 game screen.

Pokemon RAM snapshot:
{state_json}

Local collision grid (# blocked, . walkable, P player at center):
{collision}

Recent decisions:
{history_json}

Return only one JSON object with exactly this shape:
{{"phase":"intro|menu|dialogue|overworld|battle|other",
"observation":"what is visibly happening",
"objective":"the immediate goal and relevant longer-term plan",
"reason":"brief reason for this input sequence",
"buttons":["a","up"],
"checkpoint":false}}"""


class ActionPlayer:
    def __init__(self):
        self.pending: deque[str] = deque()
        self.current: Optional[str] = None
        self.hold_frames = 0
        self.gap_frames = 0

    @property
    def idle(self) -> bool:
        return not self.pending and self.current is None and self.gap_frames == 0

    def replace(self, buttons: list[str]) -> None:
        self.pending.clear()
        self.pending.extend(button for button in buttons if button in VALID_BUTTONS)

    def append(self, button: str) -> None:
        if button in VALID_BUTTONS:
            self.pending.append(button)

    def tick(self, pyboy: Any) -> Optional[str]:
        if self.current:
            self.hold_frames -= 1
            if self.hold_frames <= 0:
                pyboy.button_release(self.current)
                completed = self.current
                self.current = None
                self.gap_frames = 18
                return completed
            return None
        if self.gap_frames > 0:
            self.gap_frames -= 1
            return None
        if self.pending:
            self.current = self.pending.popleft()
            pyboy.button_press(self.current)
            self.hold_frames = 8
        return None

    def release(self, pyboy: Any) -> None:
        if self.current:
            pyboy.button_release(self.current)
            self.current = None
        self.pending.clear()
        self.gap_frames = 0

    def release_and_flush(self, pyboy: Any, require_running: bool = True) -> None:
        self.pending.clear()
        self.current = None
        self.gap_frames = 0
        for button in VALID_BUTTONS:
            pyboy.button_release(button)
        if not pyboy.tick() and require_running:
            raise RuntimeError("PyBoy stopped while normalizing controller input")


class BoundedThreadingHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True
    request_queue_size = SPECTATOR_MAX_CONNECTIONS

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[http.server.BaseHTTPRequestHandler],
        *,
        max_workers: Optional[int] = None,
        socket_timeout: Optional[float] = None,
    ):
        self.max_workers = max_workers or SPECTATOR_MAX_CONNECTIONS
        self.socket_timeout = (
            SPECTATOR_SOCKET_TIMEOUT_SECONDS
            if socket_timeout is None
            else socket_timeout
        )
        self._request_slots = threading.BoundedSemaphore(self.max_workers)
        self._last_handler_warning = 0.0
        self._handler_warning_lock = threading.Lock()
        super().__init__(server_address, handler_class)

    def get_request(self) -> tuple[socket.socket, Any]:
        request, client_address = super().get_request()
        request.settimeout(self.socket_timeout)
        return request, client_address

    @staticmethod
    def _reject_overload(request: socket.socket) -> None:
        try:
            request.sendall(
                b"HTTP/1.0 503 Service Unavailable\r\n"
                b"Connection: close\r\n"
                b"Content-Type: text/plain; charset=utf-8\r\n"
                b"Content-Length: 12\r\n\r\n"
                b"Unavailable\n"
            )
        except OSError:
            pass
        finally:
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            request.close()

    def process_request(self, request: socket.socket, client_address: Any) -> None:
        if not self._request_slots.acquire(blocking=False):
            self._reject_overload(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(
        self,
        request: socket.socket,
        client_address: Any,
    ) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()

    def handle_error(self, request: Any, client_address: Any) -> None:
        del request, client_address
        now = time.monotonic()
        with self._handler_warning_lock:
            if now - self._last_handler_warning < 60:
                return
            self._last_handler_warning = now
        LOGGER.warning("Malformed spectator request was dropped")


class SpectatorServer:
    def __init__(
        self,
        port: int,
        advertised_host: Optional[str] = None,
        join_base: Optional[str] = None,
    ):
        self.port = port
        try:
            self.advertised_host = (
                validate_advertised_host(advertised_host) if advertised_host else None
            )
            self.external_join_base = (
                validate_external_join_base(join_base) if join_base else None
            )
        except ValueError as error:
            raise StartupConfigurationError(
                f"Invalid spectator configuration: {error}"
            ) from error
        self.page_base: Optional[str] = None
        self.server: Optional[http.server.ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        assets = {
            "/": (SPECTATOR_HTML.encode("utf-8"), "text/html; charset=utf-8"),
            "/index.html": (
                SPECTATOR_HTML.encode("utf-8"),
                "text/html; charset=utf-8",
            ),
            "/spectator.css": (
                SPECTATOR_CSS.encode("utf-8"),
                "text/css; charset=utf-8",
            ),
            "/spectator.js": (
                SPECTATOR_JS.encode("utf-8"),
                "text/javascript; charset=utf-8",
            ),
            "/pairing.js": (
                PAIRING_JS.encode("utf-8"),
                "text/javascript; charset=utf-8",
            ),
            "/vendor/peerjs.min.js": (
                PEERJS_RUNTIME_JS,
                "text/javascript; charset=utf-8",
            ),
            "/vendor/trystero-nostr.min.js": (
                TRYSTERO_NOSTR_RUNTIME_JS,
                "text/javascript; charset=utf-8",
            ),
            "/vendor/qrious.min.js": (
                QRIOUS_RUNTIME_JS,
                "text/javascript; charset=utf-8",
            ),
            "/vendor/licenses.txt": (
                THIRD_PARTY_BROWSER_LICENSES,
                "text/plain; charset=utf-8",
            ),
        }

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format_string: str, *args: Any) -> None:
                del format_string, args

            def _security_headers(self) -> None:
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; media-src blob:; "
                    f"connect-src {PEERJS_SIGNAL_HTTPS} {PEERJS_SIGNAL_WSS}; "
                    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'; "
                    "object-src 'none'",
                )
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                self.send_header("Cross-Origin-Opener-Policy", "same-origin")
                self.send_header(
                    "Permissions-Policy",
                    "camera=(), microphone=(), geolocation=(), payment=()",
                )

            def _respond(
                self,
                status_code: int,
                payload: bytes,
                content_type: str,
                *,
                include_body: bool,
                allow: Optional[str] = None,
            ) -> None:
                self.send_response(status_code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                if allow:
                    self.send_header("Allow", allow)
                self._security_headers()
                self.end_headers()
                if include_body:
                    try:
                        self.wfile.write(payload)
                    except (BrokenPipeError, ConnectionResetError, socket.timeout):
                        return

            def _serve(self, *, include_body: bool) -> None:
                try:
                    request_parts = self.requestline.split()
                    if (
                        len(request_parts) != 3
                        or request_parts[1] != self.path
                        or len(self.path) > 2048
                        or not self.path.startswith("/")
                        or self.path.startswith("//")
                    ):
                        raise ValueError("request target is not origin-form")
                    parsed = urllib.parse.urlsplit(self.path)
                    if (
                        parsed.scheme
                        or parsed.netloc
                        or parsed.query
                        or parsed.fragment
                        or parsed.path != self.path
                    ):
                        raise ValueError("request target is not a fixed path")
                except (TypeError, ValueError):
                    self._respond(
                        400,
                        b"Bad request\n",
                        "text/plain; charset=utf-8",
                        include_body=include_body,
                    )
                    return
                asset = assets.get(parsed.path)
                if asset is None:
                    self._respond(
                        404,
                        b"Not found\n",
                        "text/plain; charset=utf-8",
                        include_body=include_body,
                    )
                    return
                payload, content_type = asset
                self._respond(
                    200,
                    payload,
                    content_type,
                    include_body=include_body,
                )

            def do_GET(self) -> None:
                self._serve(include_body=True)

            def do_HEAD(self) -> None:
                self._serve(include_body=False)

            def _method_not_allowed(self) -> None:
                self._respond(
                    405,
                    b"Method not allowed\n",
                    "text/plain; charset=utf-8",
                    include_body=True,
                    allow="GET, HEAD",
                )

            do_POST = _method_not_allowed
            do_PUT = _method_not_allowed
            do_PATCH = _method_not_allowed
            do_DELETE = _method_not_allowed
            do_OPTIONS = _method_not_allowed
            do_TRACE = _method_not_allowed
            do_CONNECT = _method_not_allowed

        try:
            self.server = BoundedThreadingHTTPServer(
                ("0.0.0.0", self.port),
                Handler,
            )
        except OSError as error:
            raise StartupConfigurationError(
                f"Cannot bind read-only spectator server to 0.0.0.0:{self.port}: "
                f"{error}"
            ) from error
        try:
            self.port = int(self.server.server_address[1])
            host = self.advertised_host or discover_lan_host()
            local_base = f"http://{url_host(host)}:{self.port}"
            self.page_base = self.external_join_base or local_base
            self.thread = threading.Thread(
                target=self.server.serve_forever,
                name="pokemon-spectator-assets",
                daemon=True,
            )
            self.thread.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        server, thread = self.server, self.thread
        self.server = None
        self.thread = None
        if server:
            try:
                if thread and thread.is_alive():
                    server.shutdown()
            finally:
                server.server_close()
        if thread and thread.ident is not None:
            thread.join(timeout=3)


PAIR_RETURN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Deliver Manual Share answer</title></head>
<body><main><h1>Delivering answer locally</h1>
<p id="status" role="status" aria-live="polite">Checking the fragment-only answer…</p>
<button id="deliver" type="button" hidden>Deliver answer</button>
<p>This loopback-only page can submit pairing answers, never gameplay controls.</p>
</main><script src="/pair-return.js" defer></script></body></html>
"""

PAIR_RETURN_JS = """
(() => {
'use strict';
const status = document.getElementById('status');
const button = document.getElementById('deliver');
const maximum = 512 * 1024;
let payload = null;

function parse() {
  const fragment = location.hash.slice(1);
  if (!fragment || fragment.length > maximum) throw new Error('Invalid answer link.');
  const params = new URLSearchParams(fragment);
  if (
    [...params.keys()].sort().join(',') !==
      'answer,cb,gen,mode,rt,v' ||
    params.get('v') !== '2' ||
    params.get('mode') !== 'manual-return' ||
    !/^[A-Za-z0-9_-]{16,128}$/.test(params.get('gen') || '') ||
    !/^[A-Za-z0-9_-]{43}$/.test(params.get('rt') || '') ||
    !(params.get('answer') || '').startsWith('rpp-answer-v2.')
  ) throw new Error('Invalid answer link.');
  payload = {
    action: 'deliver',
    generation: params.get('gen'),
    token: params.get('rt'),
    answer: params.get('answer')
  };
  if (history && typeof history.replaceState === 'function') {
    history.replaceState(null, '', location.pathname);
  }
}

async function request(value) {
  const response = await fetch('/api/kite/manual-answer', {
    method: 'POST',
    credentials: 'omit',
    cache: 'no-store',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(value)
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message || 'Answer rejected.');
  return result;
}

async function poll(sequence) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    await new Promise(resolve => setTimeout(resolve, 500));
    const result = await request({
      action: 'status',
      generation: payload.generation,
      token: payload.token,
      sequence
    });
    if (result.status === 'delivered') {
      status.textContent = 'Delivered to the dedicated streamer host.';
      button.hidden = true;
      return;
    }
    if (result.status === 'rejected') {
      status.textContent = 'Rejected. Ask the streamer to create a fresh offer.';
      button.hidden = true;
      return;
    }
  }
  status.textContent =
    'Queued locally. Keep the streamer running while delivery completes.';
}

async function deliver() {
  button.disabled = true;
  status.textContent = 'Delivering to the dedicated streamer host…';
  try {
    const result = await request(payload);
    button.hidden = true;
    status.textContent = 'Queued locally for cryptographic validation…';
    await poll(result.sequence);
  } catch (error) {
    status.textContent = String(error && error.message || error).slice(0, 160);
    button.hidden = false;
    button.disabled = false;
  }
}

try {
  parse();
  button.hidden = false;
  void deliver();
} catch (error) {
  status.textContent = String(error && error.message || error).slice(0, 160);
}
button.addEventListener('click', deliver);
})();
"""


class ViewerServer:
    def __init__(
        self,
        runtime_dir: Path,
        port: int,
        controls: "queue.Queue[dict[str, Any]]",
        livestream: Optional[dict[str, Any]] = None,
        manual_return: Optional[dict[str, str]] = None,
    ):
        self.runtime_dir = runtime_dir
        self.port = port
        self.controls = controls
        self.livestream = livestream or {"enabled": False}
        self.manual_return = dict(manual_return or {})
        try:
            manual_return_valid = not self.manual_return or (
                set(self.manual_return) == {"generation", "token"}
                and bool(
                    re.fullmatch(
                        r"[A-Za-z0-9_-]{16,128}",
                        self.manual_return.get("generation", ""),
                    )
                )
                and len(
                    decode_urlsafe_token(
                        self.manual_return.get("token", ""),
                        32,
                        "manual return token",
                    )
                )
                == 32
            )
        except ValueError:
            manual_return_valid = False
        if not manual_return_valid:
            raise StartupConfigurationError(
                "Invalid generation-scoped manual return configuration"
            )
        self.manual_return_lock = threading.Lock()
        self.manual_return_sequence = 0
        self.manual_return_digests: set[str] = set()
        self.manual_return_attempts: deque[float] = deque()
        if self.livestream.get("enabled"):
            peer_options = dict(self.livestream.get("peer_options") or {})
            peer_options["config"] = {
                "iceServers": [
                    dict(server)
                    for server in PEERJS_ICE_CONFIG["iceServers"]
                ]
            }
            self.livestream["peer_options"] = peer_options
            self.livestream.setdefault("generation", secrets.token_urlsafe(24))
            self.livestream.setdefault("telemetry_version", TELEMETRY_VERSION)
            self.livestream.setdefault("max_telemetry_bytes", MAX_TELEMETRY_BYTES)
            self.livestream.setdefault(
                "telemetry_change_seconds",
                TELEMETRY_CHANGE_INTERVAL_SECONDS,
            )
            self.livestream.setdefault(
                "telemetry_heartbeat_seconds",
                TELEMETRY_HEARTBEAT_SECONDS,
            )
            self.livestream.setdefault(
                "telemetry_stale_seconds",
                TELEMETRY_STALE_SECONDS,
            )
            self.livestream.setdefault(
                "lease_ttl_seconds",
                LIVESTREAM_LEASE_TTL_SECONDS,
            )
            self.livestream.setdefault(
                "max_negotiating",
                min(
                    HARD_MAX_NEGOTIATING,
                    max(
                        2,
                        int(
                            self.livestream.get(
                                "max_viewers",
                                DEFAULT_MAX_VIEWERS,
                            )
                        )
                        * 2,
                    ),
                ),
            )
        generation = self.livestream.get("generation")
        self.lease_manager = (
            LivestreamLeaseManager(generation)
            if self.livestream.get("enabled") and isinstance(generation, str)
            else None
        )
        self.token = secrets.token_urlsafe(32)
        self.server: Optional[http.server.ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        runtime_dir = self.runtime_dir
        controls = self.controls
        livestream = self.livestream
        lease_manager = self.lease_manager
        token = self.token
        manual_return = self.manual_return
        manual_return_lock = self.manual_return_lock
        manual_return_attempts = self.manual_return_attempts
        manual_return_digests = self.manual_return_digests
        server_owner = self
        manual_return_dir = (
            runtime_dir / KiteBroadcaster.MANUAL_RETURN_DIRECTORY
        )
        if manual_return:
            manual_return_dir.mkdir(mode=0o700, exist_ok=True)
            os.chmod(manual_return_dir, 0o700)

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format_string: str, *args: Any) -> None:
                LOGGER.debug("viewer: " + format_string, *args)

            def _security_headers(self) -> None:
                connect_sources = "'self'"
                if livestream.get("enabled"):
                    connect_sources += (
                        f" {PEERJS_SIGNAL_HTTPS} {PEERJS_SIGNAL_WSS}"
                    )
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; img-src 'self' data:; "
                    "media-src 'self' blob:; style-src 'self'; script-src 'self'; "
                    f"connect-src {connect_sources}; frame-ancestors 'none'; "
                    "base-uri 'none'; form-action 'none'; object-src 'none'",
                )
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Cross-Origin-Resource-Policy", "same-origin")

            def _allowed_origins(self) -> set[str]:
                port = self.server.server_address[1]
                return {
                    f"http://127.0.0.1:{port}",
                    f"http://localhost:{port}",
                }

            def _host_allowed(self) -> bool:
                port = self.server.server_address[1]
                return self.headers.get("Host", "") in {
                    f"127.0.0.1:{port}",
                    f"localhost:{port}",
                }

            def _return_host_allowed(self) -> bool:
                port = self.server.server_address[1]
                return self.headers.get("Host", "") == f"127.0.0.1:{port}"

            def _return_origin_allowed(self) -> bool:
                port = self.server.server_address[1]
                return (
                    self.headers.get("Origin", "")
                    == f"http://127.0.0.1:{port}"
                )

            def _manual_rate_allowed(self, limit: int) -> bool:
                now = time.monotonic()
                with manual_return_lock:
                    while (
                        manual_return_attempts
                        and now - manual_return_attempts[0] > 60
                    ):
                        manual_return_attempts.popleft()
                    if len(manual_return_attempts) >= limit:
                        return False
                    manual_return_attempts.append(now)
                    return True

            def _authenticated(self) -> bool:
                if not self._host_allowed():
                    return False
                cookie = SimpleCookie()
                try:
                    cookie.load(self.headers.get("Cookie", ""))
                except ValueError:
                    return False
                supplied = cookie.get("openrappter_pokemon")
                return bool(supplied and secrets.compare_digest(supplied.value, token))

            def _forbidden(self) -> None:
                payload = b'{"status":"error","message":"forbidden"}'
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self._security_headers()
                self.end_headers()
                self.wfile.write(payload)

            def _json(self, status_code: int, value: dict[str, Any]) -> None:
                payload = json.dumps(value).encode("utf-8")
                self._bytes(status_code, payload, "application/json")

            def _bytes(
                self,
                status_code: int,
                payload: bytes,
                content_type: str,
            ) -> None:
                self.send_response(status_code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self._security_headers()
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path in {"/pair-return", "/pair-return.js"}:
                    if (
                        not manual_return
                        or not self._return_host_allowed()
                        or parsed.params
                        or parsed.query
                        or parsed.fragment
                    ):
                        self._forbidden()
                        return
                    if parsed.path == "/pair-return":
                        self._bytes(
                            200,
                            PAIR_RETURN_HTML.encode("utf-8"),
                            "text/html; charset=utf-8",
                        )
                    else:
                        self._bytes(
                            200,
                            PAIR_RETURN_JS.encode("utf-8"),
                            "text/javascript; charset=utf-8",
                        )
                    return
                if parsed.path == "/":
                    if not self._host_allowed():
                        self._forbidden()
                        return
                    if not self._authenticated():
                        supplied = urllib.parse.parse_qs(
                            parsed.query,
                            keep_blank_values=True,
                        ).get("token", [""])[0]
                        if not secrets.compare_digest(supplied, token):
                            self._forbidden()
                            return
                        self.send_response(303)
                        self.send_header("Location", "/")
                        self.send_header("Content-Length", "0")
                        self.send_header(
                            "Set-Cookie",
                            "openrappter_pokemon="
                            f"{token}; Path=/; HttpOnly; SameSite=Strict",
                        )
                        self.send_header("Cache-Control", "no-store")
                        self._security_headers()
                        self.end_headers()
                        return
                    self._bytes(
                        200,
                        (
                            VIEWER_HTML
                            if livestream.get("enabled")
                            else VIEWER_HTML.replace(
                                '<script src="/vendor/peerjs.min.js" defer></script>\n',
                                "",
                            ).replace(
                                '<script src="/vendor/qrious.min.js" defer></script>\n',
                                "",
                            )
                        ).encode("utf-8"),
                        "text/html; charset=utf-8",
                    )
                    return
                if not self._authenticated():
                    self._forbidden()
                    return
                if parsed.path == "/viewer.css":
                    self._bytes(
                        200,
                        VIEWER_CSS.encode("utf-8"),
                        "text/css; charset=utf-8",
                    )
                    return
                if parsed.path == "/viewer.js":
                    self._bytes(
                        200,
                        VIEWER_JS.encode("utf-8"),
                        "text/javascript; charset=utf-8",
                    )
                    return
                if parsed.path == "/vendor/peerjs.min.js":
                    self._bytes(
                        200,
                        PEERJS_RUNTIME_JS,
                        "text/javascript; charset=utf-8",
                    )
                    return
                if parsed.path == "/vendor/qrious.min.js":
                    self._bytes(
                        200,
                        QRIOUS_RUNTIME_JS,
                        "text/javascript; charset=utf-8",
                    )
                    return
                if parsed.path == "/vendor/qrious.js":
                    self._bytes(
                        200,
                        QRIOUS_SOURCE_JS,
                        "text/javascript; charset=utf-8",
                    )
                    return
                if parsed.path == "/vendor/licenses.txt":
                    self._bytes(
                        200,
                        THIRD_PARTY_BROWSER_LICENSES,
                        "text/plain; charset=utf-8",
                    )
                    return
                if parsed.path == "/api/status":
                    self._json(200, public_runtime_status(runtime_dir))
                    return
                if parsed.path == "/api/dashboard":
                    self._json(200, dashboard_snapshot(runtime_dir))
                    return
                if parsed.path == "/api/livestream":
                    self._json(200, livestream)
                    return
                if parsed.path == "/frame.png":
                    self._send_file(runtime_dir / "latest.png", "image/png")
                    return
                if parsed.path.startswith("/clips/"):
                    name = urllib.parse.unquote(parsed.path.removeprefix("/clips/"))
                    if Path(name).name != name or not GENERATED_CLIP_RE.fullmatch(name):
                        self.send_error(400)
                        return
                    self._send_file(runtime_dir / "clips" / name, "video/mp4")
                    return
                self.send_error(404)

            def _send_file(self, path: Path, content_type: str) -> None:
                try:
                    if path.is_symlink():
                        raise OSError("symlinks are not served")
                    size = path.stat().st_size
                except OSError:
                    self.send_error(404)
                    return
                start = 0
                end = size - 1
                range_header = self.headers.get("Range")
                if range_header:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
                    if not match or not any(match.groups()):
                        self.send_error(416)
                        return
                    if match.group(1):
                        start = int(match.group(1))
                    if match.group(2):
                        end = min(end, int(match.group(2)))
                if start < 0 or end < start or start >= size:
                    self.send_error(416)
                    return
                length = end - start + 1
                self.send_response(206 if range_header else 200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Accept-Ranges", "bytes")
                if range_header:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Cache-Control", "no-store")
                self._security_headers()
                self.end_headers()
                try:
                    with path.open("rb") as handle:
                        handle.seek(start)
                        remaining = length
                        while remaining:
                            chunk = handle.read(min(64 * 1024, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def do_POST(self) -> None:
                path = urllib.parse.urlparse(self.path).path
                if path == "/api/kite/manual-answer":
                    if (
                        not manual_return
                        or not self._return_host_allowed()
                        or not self._return_origin_allowed()
                    ):
                        self._forbidden()
                        return
                    if not self._manual_rate_allowed(120):
                        self._json(
                            429,
                            {"status": "error", "message": "Rate limit exceeded"},
                        )
                        return
                    content_type = self.headers.get(
                        "Content-Type",
                        "",
                    ).split(";", 1)[0]
                    if content_type.strip().lower() != "application/json":
                        self._forbidden()
                        return
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        if not 1 <= length <= MAX_MANUAL_RETURN_REQUEST_BYTES:
                            raise OverflowError
                        value = json.loads(self.rfile.read(length).decode("utf-8"))
                    except OverflowError:
                        self._json(
                            413,
                            {"status": "error", "message": "Request too large"},
                        )
                        return
                    except (
                        ValueError,
                        json.JSONDecodeError,
                        UnicodeDecodeError,
                    ):
                        self._json(
                            400,
                            {"status": "error", "message": "Invalid JSON"},
                        )
                        return
                    if not isinstance(value, dict):
                        self._json(
                            400,
                            {"status": "error", "message": "Expected object"},
                        )
                        return
                    supplied_token = value.get("token")
                    supplied_generation = value.get("generation")
                    if (
                        not isinstance(supplied_token, str)
                        or not isinstance(supplied_generation, str)
                        or not secrets.compare_digest(
                            supplied_token,
                            manual_return["token"],
                        )
                        or not secrets.compare_digest(
                            supplied_generation,
                            manual_return["generation"],
                        )
                    ):
                        self._forbidden()
                        return
                    action = value.get("action")
                    if action == "status":
                        if set(value) != {
                            "action",
                            "generation",
                            "sequence",
                            "token",
                        }:
                            self._json(
                                400,
                                {"status": "error", "message": "Invalid status"},
                            )
                            return
                        sequence = value.get("sequence")
                        if (
                            isinstance(sequence, bool)
                            or not isinstance(sequence, int)
                            or not 1 <= sequence <= 999_999_999_999
                        ):
                            self._json(
                                400,
                                {"status": "error", "message": "Invalid status"},
                            )
                            return
                        suffix = f"{sequence:012d}.json"
                        status_value = read_json(
                            manual_return_dir / f"status-{suffix}"
                        )
                        if (
                            status_value.get("generation")
                            == manual_return["generation"]
                            and status_value.get("sequence") == sequence
                            and status_value.get("status")
                            in {"delivered", "rejected"}
                        ):
                            self._json(
                                200,
                                {
                                    "status": status_value["status"],
                                    "sequence": sequence,
                                },
                            )
                            return
                        queued = manual_return_dir / f"answer-{suffix}"
                        self._json(
                            200 if queued.is_file() else 404,
                            {
                                "status": (
                                    "queued" if queued.is_file() else "rejected"
                                ),
                                "sequence": sequence,
                            },
                        )
                        return
                    if action != "deliver" or set(value) != {
                        "action",
                        "answer",
                        "generation",
                        "token",
                    }:
                        self._json(
                            400,
                            {"status": "error", "message": "Invalid delivery"},
                        )
                        return
                    answer = value.get("answer")
                    if (
                        not isinstance(answer, str)
                        or not answer.startswith("rpp-answer-v2.")
                        or len(answer.encode("utf-8"))
                        > MAX_MANUAL_ANSWER_BYTES
                    ):
                        self._json(
                            413,
                            {"status": "error", "message": "Invalid answer"},
                        )
                        return
                    digest = hashlib.sha256(answer.encode("utf-8")).hexdigest()
                    with manual_return_lock:
                        queued_count = sum(
                            1
                            for candidate in manual_return_dir.glob(
                                "answer-*.json"
                            )
                            if candidate.is_file() and not candidate.is_symlink()
                        )
                        if digest in manual_return_digests:
                            self._json(
                                409,
                                {
                                    "status": "error",
                                    "message": "Duplicate answer",
                                },
                            )
                            return
                        if queued_count >= MAX_MANUAL_RETURN_QUEUE:
                            self._json(
                                429,
                                {"status": "error", "message": "Queue is full"},
                            )
                            return
                        server_owner.manual_return_sequence += 1
                        sequence = server_owner.manual_return_sequence
                        atomic_write_json(
                            manual_return_dir
                            / f"answer-{sequence:012d}.json",
                            {
                                "schema_version": KITE_STRING_SCHEMA_VERSION,
                                "generation": manual_return["generation"],
                                "sequence": sequence,
                                "answer": answer,
                                "received_at": utc_now(),
                            },
                        )
                        manual_return_digests.add(digest)
                    self._json(
                        202,
                        {"status": "queued", "sequence": sequence},
                    )
                    return
                if path not in {
                    "/api/control",
                    "/api/livestream/lease",
                    "/api/livestream/state",
                }:
                    self.send_error(404)
                    return
                if not self._authenticated():
                    self._forbidden()
                    return
                if self.headers.get("Origin") not in self._allowed_origins():
                    self._forbidden()
                    return
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
                if content_type.strip().lower() != "application/json":
                    self._forbidden()
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 1 <= length <= 4096:
                        raise ValueError("invalid request length")
                    value = json.loads(self.rfile.read(length).decode("utf-8"))
                except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                    self._json(400, {"status": "error", "message": "Invalid JSON"})
                    return
                if not isinstance(value, dict):
                    self._json(400, {"status": "error", "message": "Expected object"})
                    return
                if path in {"/api/livestream/lease", "/api/livestream/state"}:
                    if not livestream.get("enabled"):
                        self._json(
                            404,
                            {"status": "error", "message": "Livestream is disabled"},
                        )
                        return
                    if lease_manager is None:
                        self._json(
                            503,
                            {"status": "error", "message": "Lease unavailable"},
                        )
                        return
                if path == "/api/livestream/lease":
                    action = value.get("action")
                    expected_keys = (
                        {"action", "owner", "generation"}
                        if action == "acquire"
                        else {"action", "owner", "generation", "lease"}
                    )
                    if action not in {"acquire", "heartbeat", "release"} or set(
                        value
                    ) != expected_keys:
                        self._json(
                            400,
                            {"status": "error", "message": "Invalid lease request"},
                        )
                        return
                    try:
                        if action == "acquire":
                            lease = lease_manager.acquire(
                                value.get("owner"),
                                value.get("generation"),
                            )
                            atomic_write_json(
                                runtime_dir / "livestream-status.json",
                                {
                                    "state": "offline",
                                    "viewer_count": 0,
                                    "owner": lease["owner"],
                                    "generation": lease["generation"],
                                    "updated_at": utc_now(),
                                },
                            )
                            self._json(200, {"status": "success", **lease})
                            return
                        if action == "release":
                            lease_manager.release(
                                value.get("owner"),
                                value.get("generation"),
                                value.get("lease"),
                            )
                            atomic_write_json(
                                runtime_dir / "livestream-status.json",
                                {
                                    "state": "offline",
                                    "viewer_count": 0,
                                    "owner": None,
                                    "generation": lease_manager.generation,
                                    "updated_at": utc_now(),
                                },
                            )
                            self._json(200, {"status": "success"})
                            return
                        lease_manager.validate(
                            value.get("owner"),
                            value.get("generation"),
                            value.get("lease"),
                        )
                    except LivestreamLeaseError as error:
                        self._json(
                            error.status_code,
                            {"status": "error", "message": error.reason},
                        )
                        return
                    current = read_json(runtime_dir / "livestream-status.json")
                    if (
                        current.get("generation") != lease_manager.generation
                        or current.get("owner") != value.get("owner")
                    ):
                        current = {"state": "offline", "viewer_count": 0}
                    atomic_write_json(
                        runtime_dir / "livestream-status.json",
                        {
                            "state": current.get("state", "offline"),
                            "viewer_count": current.get("viewer_count", 0),
                            "owner": value.get("owner"),
                            "generation": lease_manager.generation,
                            "updated_at": utc_now(),
                        },
                    )
                    self._json(
                        200,
                        {
                            "status": "success",
                            "owner": value.get("owner"),
                            "generation": lease_manager.generation,
                            "ttl_seconds": lease_manager.ttl_seconds,
                            "heartbeat_seconds": LIVESTREAM_HEARTBEAT_SECONDS,
                        },
                    )
                    return
                if path == "/api/livestream/state":
                    if set(value) != {
                        "state",
                        "viewer_count",
                        "owner",
                        "generation",
                        "lease",
                    }:
                        self._json(
                            400,
                            {"status": "error", "message": "Invalid stream state"},
                        )
                        return
                    try:
                        lease_manager.validate(
                            value.get("owner"),
                            value.get("generation"),
                            value.get("lease"),
                        )
                    except LivestreamLeaseError as error:
                        self._json(
                            error.status_code,
                            {"status": "error", "message": error.reason},
                        )
                        return
                    state = value.get("state")
                    viewer_count = value.get("viewer_count")
                    if (
                        state
                        not in {
                            "offline",
                            "connecting",
                            "live",
                            "reconnecting",
                            "error",
                        }
                        or isinstance(viewer_count, bool)
                        or not isinstance(viewer_count, int)
                        or not 0
                        <= viewer_count
                        <= int(livestream.get("max_viewers", DEFAULT_MAX_VIEWERS))
                    ):
                        self._json(
                            400,
                            {"status": "error", "message": "Invalid stream state"},
                        )
                        return
                    atomic_write_json(
                        runtime_dir / "livestream-status.json",
                        {
                            "state": state,
                            "viewer_count": viewer_count,
                            "owner": value.get("owner"),
                            "generation": lease_manager.generation,
                            "updated_at": utc_now(),
                        },
                    )
                    self._json(200, {"status": "success"})
                    return
                action = str(value.get("action", "")).lower()
                button = str(value.get("button", "")).lower()
                if action not in {
                    "manual",
                    "autonomy",
                    "pause",
                    "resume",
                    "checkpoint",
                    "stop",
                    "press",
                }:
                    self._json(400, {"status": "error", "message": "Invalid action"})
                    return
                if action == "press" and button not in VALID_BUTTONS:
                    self._json(400, {"status": "error", "message": "Invalid button"})
                    return
                if action == "stop":
                    set_desired_running(runtime_dir, False)
                controls.put({"action": action, "button": button or None})
                self._json(200, {"status": "success", "action": action})

        class LoopbackServer(http.server.ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        try:
            self.server = LoopbackServer(("127.0.0.1", self.port), Handler)
        except OSError as error:
            raise StartupConfigurationError(
                f"Cannot bind authenticated viewer to 127.0.0.1:{self.port}: {error}"
            ) from error
        try:
            self.port = int(self.server.server_address[1])
            atomic_write_json(
                runtime_dir / "viewer-auth.json",
                {
                    "token": token,
                    "port": self.port,
                    "created_at": utc_now(),
                },
            )
            self.thread = threading.Thread(
                target=self.server.serve_forever,
                name="pokemon-viewer",
                daemon=True,
            )
            self.thread.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self.lease_manager:
            self.lease_manager.revoke()
            try:
                atomic_write_json(
                    self.runtime_dir / "livestream-status.json",
                    {
                        "state": "offline",
                        "viewer_count": 0,
                        "owner": None,
                        "generation": self.lease_manager.generation,
                        "updated_at": utc_now(),
                    },
                )
            except OSError:
                LOGGER.debug("Could not publish terminal livestream state")
        server, thread = self.server, self.thread
        self.server = None
        self.thread = None
        if server:
            try:
                if thread and thread.is_alive():
                    server.shutdown()
            finally:
                server.server_close()
        if thread and thread.ident is not None:
            thread.join(timeout=3)
        (self.runtime_dir / "viewer-auth.json").unlink(missing_ok=True)
        manual_return_dir = (
            self.runtime_dir / KiteBroadcaster.MANUAL_RETURN_DIRECTORY
        )
        if manual_return_dir.is_dir() and not manual_return_dir.is_symlink():
            shutil.rmtree(manual_return_dir, ignore_errors=True)
        self.manual_return.clear()
        self.manual_return_digests.clear()
        self.manual_return_attempts.clear()


class PokemonRunner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.run_id = uuid.uuid4().hex[:12]
        self.rom = Path(args.rom).expanduser().resolve()
        self.runtime_dir = Path(args.runtime_dir).expanduser().resolve()
        self.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.runtime_dir, 0o700)
        (self.runtime_dir / "livestream-auth.json").unlink(missing_ok=True)
        (self.runtime_dir / "livestream-status.json").unlink(missing_ok=True)
        for private_name in KiteBroadcaster.PRIVATE_FILES:
            if private_name == KiteBroadcaster.OWNER_FILE:
                continue
            (self.runtime_dir / private_name).unlink(missing_ok=True)
        manual_return_dir = (
            self.runtime_dir / KiteBroadcaster.MANUAL_RETURN_DIRECTORY
        )
        if manual_return_dir.is_dir() and not manual_return_dir.is_symlink():
            shutil.rmtree(manual_return_dir, ignore_errors=True)
        for candidate in self.runtime_dir.iterdir():
            if (
                KiteBroadcaster.PRIVATE_TEMP_RE.fullmatch(candidate.name)
                and candidate.is_file()
                and not candidate.is_symlink()
            ):
                candidate.unlink(missing_ok=True)
        self.states_dir = self.runtime_dir / "states"
        self.screens_dir = self.runtime_dir / "screens"
        self.states_dir.mkdir(exist_ok=True, mode=0o700)
        self.screens_dir.mkdir(exist_ok=True, mode=0o700)
        os.chmod(self.states_dir, 0o700)
        os.chmod(self.screens_dir, 0o700)
        self.status_path = self.runtime_dir / "status.json"
        self.control_path = self.runtime_dir / "control.jsonl"
        self.control_path.write_text("", encoding="utf-8")
        os.chmod(self.control_path, 0o600)
        self.controls: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.brain_requests: "queue.Queue[Optional[dict[str, Any]]]" = queue.Queue(
            maxsize=1
        )
        self.brain_results: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.stop_event = threading.Event()
        self.brain_ready = threading.Event()
        self.brain_available = threading.Event()
        self.brain: Optional[CopilotBrain] = None
        self.brain_thread: Optional[threading.Thread] = None
        self.paused = False
        self.emulator_pause_requested = False
        self.control_mode = "ai"
        self.resume_mode = "ai"
        self.control_generation = 0
        self.decision_sequence = 0
        self.pending_decision_id: Optional[int] = None
        self.player = ActionPlayer()
        brain_data = read_json(self.runtime_dir / "brain.json", {"history": []})
        self.history: list[dict[str, Any]] = brain_data.get("history", [])
        if not isinstance(self.history, list):
            self.history = []
        self.total_decisions = int(brain_data.get("total_decisions", len(self.history)))
        self.rom_sha256 = self._rom_sha256()
        self.ram_path = (
            self.runtime_dir
            / f"pokemon-red-{self.rom_sha256[:16]}.ram"
        )
        self.status: dict[str, Any] = {
            "running": True,
            "pid": os.getpid(),
            "instance_id": args.instance_id,
            "port": args.port,
            "lifecycle": "initializing",
            "started_at": utc_now(),
            "updated_at": utc_now(),
            "rom_title": rom_title(self.rom),
            "rom_sha256": self.rom_sha256,
            "rom_path": str(self.rom),
            "runtime_dir": str(self.runtime_dir),
            "paused": False,
            "control_mode": "ai",
            "brain_status": "starting",
            "model": args.model,
            "model_calls": 0,
            "actions_taken": 0,
            "observation": "",
            "phase": "other",
            "reason": "",
            "objective": "Start Pokemon Red and work toward the Hall of Fame",
            "last_action": [],
            "last_error": None,
            "game_state": {},
            "current_clip": None,
            "last_checkpoint": None,
            "completed": False,
            "clips": [],
        }
        self.livestream_enabled = bool(getattr(args, "livestream", False))
        self.livestream_host = str(
            getattr(args, "livestream_host", DEFAULT_LIVESTREAM_HOST)
        ).lower()
        if self.livestream_host not in {"kite", "local"}:
            raise StartupConfigurationError(
                "livestream_host must be kite or local"
            )
        requested_signaling = getattr(args, "signaling", None)
        if requested_signaling is None:
            requested_signaling = (
                DEFAULT_SIGNALING
                if self.livestream_host == "kite"
                else "peerjs"
            )
        self.signaling = str(requested_signaling).lower()
        if self.signaling not in {"nostr", "peerjs"}:
            raise StartupConfigurationError(
                "signaling must be nostr or peerjs"
            )
        if self.livestream_host == "local" and self.signaling != "peerjs":
            raise StartupConfigurationError(
                "legacy local livestream hosting supports --signaling peerjs; "
                "the kited Pages host supports nostr"
            )
        try:
            self.host_base = validate_external_join_base(
                str(getattr(args, "host_base", DEFAULT_PAGES_HOST_BASE))
            )
        except ValueError as error:
            raise StartupConfigurationError(
                f"Invalid kited host configuration: {error}"
            ) from error
        self.browser_path = str(getattr(args, "browser_path", "") or "")
        self.bridge_startup_timeout = float(
            getattr(
                args,
                "bridge_startup_timeout",
                DEFAULT_BRIDGE_STARTUP_TIMEOUT_SECONDS,
            )
        )
        if not 2 <= self.bridge_startup_timeout <= 120:
            raise StartupConfigurationError(
                "bridge_startup_timeout must be 2-120 seconds"
            )
        self.max_viewers = min(
            HARD_MAX_VIEWERS,
            max(1, int(getattr(args, "max_viewers", DEFAULT_MAX_VIEWERS))),
        )
        self.stream_peer_id: Optional[str] = None
        self.watch_capability: Optional[str] = None
        self.stream_room_id: Optional[str] = None
        self.stream_room_key: Optional[str] = None
        self.host_public_key: Optional[str] = None
        self.host_fingerprint: Optional[str] = None
        self.manual_return_token: Optional[str] = None
        self.stream_generation: Optional[str] = None
        self.kite_instance: Optional[str] = None
        self.kite_sidecar: Optional[KiteBroadcaster] = None
        self.kite_frame_sequence = 0
        self.kite_telemetry_sequence = 0
        self.livestream_config: dict[str, Any] = {"enabled": False}
        self.spectator: Optional[SpectatorServer] = None
        if self.livestream_enabled:
            self.stream_generation = secrets.token_urlsafe(24)
            if self.signaling == "nostr":
                self.stream_room_id = secrets.token_urlsafe(16)
                self.stream_room_key = secrets.token_urlsafe(32)
                self.manual_return_token = secrets.token_urlsafe(32)
            else:
                self.stream_peer_id = f"rpp-{secrets.token_hex(16)}"
                self.watch_capability = secrets.token_urlsafe(32)
            if self.livestream_host == "kite":
                self.kite_instance = secrets.token_urlsafe(18)
            self.livestream_config.update(
                {
                    "enabled": True,
                    "signaling": self.signaling,
                    "generation": self.stream_generation,
                    "protocol_version": (
                        LIVESTREAM_PROTOCOL_VERSION
                        if self.signaling == "nostr"
                        else LEGACY_LIVESTREAM_PROTOCOL_VERSION
                    ),
                    "max_hello_bytes": (
                        2048
                        if self.signaling == "nostr"
                        else MAX_WATCH_HELLO_BYTES
                    ),
                    "telemetry_version": TELEMETRY_VERSION,
                    "max_telemetry_bytes": MAX_TELEMETRY_BYTES,
                    "telemetry_change_seconds": TELEMETRY_CHANGE_INTERVAL_SECONDS,
                    "telemetry_heartbeat_seconds": TELEMETRY_HEARTBEAT_SECONDS,
                    "telemetry_stale_seconds": TELEMETRY_STALE_SECONDS,
                    "lease_ttl_seconds": LIVESTREAM_LEASE_TTL_SECONDS,
                    "max_viewers": self.max_viewers,
                    "max_negotiating": min(
                        HARD_MAX_NEGOTIATING,
                        max(2, self.max_viewers * 2),
                    ),
                    "frame_rate": LIVESTREAM_FRAME_RATE,
                }
            )
            if self.signaling == "nostr":
                self.livestream_config.update(
                    {
                        "room_id": self.stream_room_id,
                        "room_key": self.stream_room_key,
                        "relay_urls": list(NOSTR_RELAY_URLS),
                        "rtc_config": RTC_CONFIG,
                    }
                )
            else:
                self.livestream_config.update(
                    {
                        "peer_id": self.stream_peer_id,
                        "watch_capability": self.watch_capability,
                        "peer_options": {
                            "host": "0.peerjs.com",
                            "port": 443,
                            "path": "/",
                            "secure": True,
                            "debug": 0,
                            "config": PEERJS_ICE_CONFIG,
                        },
                    }
                )
            if self.livestream_host == "local":
                self.spectator = SpectatorServer(
                    int(getattr(args, "spectator_port", DEFAULT_SPECTATOR_PORT)),
                    getattr(args, "advertised_host", None),
                    getattr(args, "join_base", None),
                )
        self.status["livestream"] = {
            "enabled": self.livestream_enabled,
            "host": self.livestream_host if self.livestream_enabled else None,
            "signaling": self.signaling if self.livestream_enabled else None,
            "state": "offline",
            "viewer_count": 0,
            "max_viewers": self.max_viewers if self.livestream_enabled else 0,
            "spectator_port": None,
            "generation": self.stream_generation,
        }
        self.pyboy: Any = None
        self.recorder = ClipRecorder(self.runtime_dir)
        self.viewer = ViewerServer(
            self.runtime_dir,
            args.port,
            self.controls,
            (
                self.livestream_config
                if self.livestream_host == "local"
                else {"enabled": False}
            ),
            manual_return=(
                {
                    "generation": self.stream_generation,
                    "token": self.manual_return_token,
                }
                if (
                    self.livestream_enabled
                    and self.livestream_host == "kite"
                    and self.signaling == "nostr"
                )
                else None
            ),
        )
        self.last_badges = 0
        self.last_decision_requested = 0.0
        self.last_decision_finished = 0.0
        self.decision_pending = False
        self.clip_started = 0.0
        self.next_record_at = 0.0
        self.frames = 0
        self.control_offset = 0
        self.max_clips = max(1, int(args.max_clips))
        self.max_states = max(2, int(args.max_states))
        self.max_storage_bytes = max(
            1,
            int(float(args.max_storage_gb) * 1024**3),
        )
        self.min_free_bytes = max(
            0,
            int(float(args.min_free_gb) * 1024**3),
        )
        self.status.update(
            {
                "storage_max_bytes": self.max_storage_bytes,
                "storage_reserve_bytes": self.min_free_bytes,
            }
        )

    def _rom_sha256(self) -> str:
        digest = hashlib.sha256()
        with self.rom.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _start_web_servers(self) -> None:
        livestream_enabled = getattr(
            self,
            "livestream_enabled",
            self.spectator is not None,
        )
        host_mode = getattr(self, "livestream_host", "local")
        signaling = getattr(self, "signaling", "peerjs")
        try:
            self.viewer.start()
            self.status["port"] = self.viewer.port
            if livestream_enabled:
                if not self.stream_generation:
                    raise RuntimeError("Livestream credentials are unavailable")
                if signaling == "nostr":
                    if not (
                        self.stream_room_id
                        and self.stream_room_key
                        and self.manual_return_token
                    ):
                        raise RuntimeError("Nostr room credentials are unavailable")
                    if host_mode != "kite":
                        raise RuntimeError(
                            "Nostr hosting requires the kited Pages host"
                        )
                    identity = KiteBroadcaster.initialize_identity(
                        self.runtime_dir,
                        self.stream_generation,
                    )
                    self.host_public_key = identity["host_public_key"]
                    self.host_fingerprint = identity["fingerprint"]
                    self.livestream_config.update(
                        {
                            "host_public_key": self.host_public_key,
                            "host_fingerprint": self.host_fingerprint,
                        }
                    )
                elif not (self.stream_peer_id and self.watch_capability):
                    raise RuntimeError("PeerJS credentials are unavailable")
                spectator_port: Optional[int] = None
                if host_mode == "local":
                    if not self.spectator:
                        raise RuntimeError("Legacy spectator server is unavailable")
                    self.spectator.start()
                    if not self.spectator.page_base:
                        raise RuntimeError(
                            "Spectator server did not produce a join URL"
                        )
                    watch_base = self.spectator.page_base
                    spectator_port = self.spectator.port
                else:
                    raw_watch_base = (
                        getattr(self.args, "join_base", None)
                        or DEFAULT_PAGES_WATCH_BASE
                    )
                    try:
                        watch_base = validate_external_join_base(
                            str(raw_watch_base)
                        )
                    except ValueError as error:
                        raise StartupConfigurationError(
                            f"Invalid Pages watch configuration: {error}"
                        ) from error
                if signaling == "nostr":
                    join_url = build_join_url(
                        watch_base,
                        self.stream_room_id,
                        self.stream_room_key,
                        signaling="nostr",
                        generation=self.stream_generation,
                        host_fingerprint=self.host_fingerprint,
                        host_public_key=self.host_public_key,
                    )
                else:
                    join_url = build_join_url(
                        watch_base,
                        self.stream_peer_id,
                        self.watch_capability,
                        signaling="peerjs",
                    )
                self.livestream_config["join_url"] = join_url
                private_auth: dict[str, Any] = {
                    "enabled": True,
                    "join_url": join_url,
                    "signaling": signaling,
                    "generation": self.stream_generation,
                    "instance": getattr(self, "kite_instance", None),
                    "max_viewers": self.max_viewers,
                    "spectator_port": spectator_port,
                    "livestream_host": host_mode,
                    "created_at": utc_now(),
                }
                if signaling == "nostr":
                    private_auth.update(
                        {
                            "room_id": self.stream_room_id,
                            "host_public_key": self.host_public_key,
                            "host_fingerprint": self.host_fingerprint,
                        }
                    )
                else:
                    private_auth.update(
                        {
                            "peer_id": self.stream_peer_id,
                            "watch_capability": self.watch_capability,
                        }
                    )
                atomic_write_json(
                    self.runtime_dir / "livestream-auth.json",
                    private_auth,
                )
                atomic_write_json(
                    self.runtime_dir / "livestream-status.json",
                    {
                        "state": "offline",
                        "viewer_count": 0,
                        "owner": None,
                        "generation": self.stream_generation,
                        "updated_at": utc_now(),
                    },
                )
                self.status["livestream"].update(
                    {
                        "spectator_port": spectator_port,
                        "bridge_state": (
                            "starting"
                            if host_mode == "kite"
                            else "ready"
                        ),
                        "share_ready": host_mode == "local",
                    }
                )
                if host_mode == "kite":
                    if not getattr(self, "kite_instance", None):
                        raise RuntimeError("Kited host selector is unavailable")
                    kite_bootstrap: dict[str, Any] = {
                        "schema_version": KITE_STRING_SCHEMA_VERSION,
                        "generation": self.stream_generation,
                        "instance": self.kite_instance,
                        "host_base": self.host_base,
                        "join_url": join_url,
                        "max_viewers": self.max_viewers,
                        "browser_path": self.browser_path,
                        "startup_timeout_seconds": self.bridge_startup_timeout,
                        "parent_pid": os.getpid(),
                        "created_at": utc_now(),
                    }
                    if signaling == "nostr":
                        callback = {
                            "origin": f"http://127.0.0.1:{self.viewer.port}",
                            "path": "/pair-return",
                        }
                        return_page = urllib.parse.urljoin(
                            self.host_base,
                            "return/",
                        )
                        kite_bootstrap.update(
                            {
                                "signaling": "nostr",
                                "room_id": self.stream_room_id,
                                "room_key": self.stream_room_key,
                                "host_public_key": self.host_public_key,
                                "host_fingerprint": self.host_fingerprint,
                                "manual_callback": callback,
                                "manual_return_token": self.manual_return_token,
                                "manual_return_page": return_page,
                                "relay_urls": list(NOSTR_RELAY_URLS),
                            }
                        )
                    else:
                        kite_bootstrap.update(
                            {
                                "peer_id": self.stream_peer_id,
                                "watch_capability": self.watch_capability,
                            }
                        )
                    atomic_write_json(
                        self.runtime_dir / "kite-bootstrap.json",
                        kite_bootstrap,
                    )
                    atomic_write_json(
                        self.runtime_dir / "kite-broadcast-state.json",
                        {
                            "schema_version": KITE_STRING_SCHEMA_VERSION,
                            "generation": self.stream_generation,
                            "instance": self.kite_instance,
                            "sequence": 0,
                            "desired": True,
                            "updated_at": utc_now(),
                        },
                    )
        except Exception:
            self.viewer.stop()
            if self.spectator:
                self.spectator.stop()
            (self.runtime_dir / "livestream-auth.json").unlink(missing_ok=True)
            (self.runtime_dir / "livestream-status.json").unlink(missing_ok=True)
            for private_name in (
                KiteBroadcaster.IDENTITY_FILE,
                "kite-string-v2.cjs",
                "kite-bootstrap.json",
                "kite-broadcast-state.json",
            ):
                (self.runtime_dir / private_name).unlink(missing_ok=True)
            raise

    def _start_kite_sidecar(self) -> None:
        if (
            not self.livestream_enabled
            or self.livestream_host != "kite"
            or not self.stream_generation
        ):
            return
        self.kite_sidecar = KiteBroadcaster(
            self.runtime_dir,
            self.stream_generation,
            self.bridge_startup_timeout,
        )
        try:
            started = self.kite_sidecar.start()
        except OSError as error:
            LOGGER.warning("Could not start the kited twin string: %s", error)
            started = False
        if not started:
            self.status["livestream"].update(
                {
                    "state": "error",
                    "bridge_state": "degraded",
                    "share_ready": False,
                }
            )

    def _write_status(self) -> None:
        livestream = self.status.get("livestream")
        if isinstance(livestream, dict) and livestream.get("enabled"):
            generation = livestream.get("generation")
            livestream.update(
                livestream_public_state(
                    self.runtime_dir,
                    expected_generation=(
                        generation if isinstance(generation, str) else None
                    ),
                )
            )
            if self.livestream_host == "kite":
                host_state = kite_host_public_state(
                    self.runtime_dir,
                    expected_generation=(
                        generation if isinstance(generation, str) else None
                    ),
                )
                livestream.update(host_state)
                if (
                    host_state["bridge_state"] == "degraded"
                    and livestream.get("state")
                    in {"connecting", "live", "reconnecting"}
                ):
                    livestream.update({"state": "error", "viewer_count": 0})
        self.status.update(
            {
                "updated_at": utc_now(),
                "heartbeat_at": utc_now(),
                "running": not self.stop_event.is_set(),
                "paused": self.paused,
                "control_mode": self.control_mode,
                "clips": list_clips(self.runtime_dir),
            }
        )
        atomic_write_json(self.status_path, self.status)
        if (
            self.livestream_enabled
            and self.livestream_host == "kite"
            and self.stream_generation
            and not self.stop_event.is_set()
        ):
            try:
                snapshot = project_dashboard_snapshot(self.status)
                self.kite_telemetry_sequence += 1
                atomic_write_json(
                    self.runtime_dir / "kite-telemetry.json",
                    {
                        "schema_version": KITE_STRING_SCHEMA_VERSION,
                        "generation": self.stream_generation,
                        "sequence": self.kite_telemetry_sequence,
                        "snapshot": snapshot,
                        "updated_at": utc_now(),
                    },
                )
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                LOGGER.warning("Safe kite telemetry publication failed: %s", error)

    @staticmethod
    def _milestone_artifact(path: Path) -> bool:
        manifest = read_json(path.with_suffix(".json"))
        reason = str(manifest.get("reason", "")).lower()
        return any(
            marker in reason
            for marker in ("badge", "hall of fame", "champion", "elite four")
        )

    @staticmethod
    def _verified_generated_clip(path: Path) -> bool:
        if not GENERATED_CLIP_RE.fullmatch(path.name):
            return False
        manifest = read_json(path.with_suffix(".json"))
        return bool(
            manifest.get("schema_version") == 1
            and manifest.get("name") == path.name
            and manifest.get("sha256")
        )

    def _verified_generated_state(self, path: Path) -> bool:
        if not GENERATED_STATE_RE.fullmatch(path.name):
            return False
        manifest = read_json(path.with_suffix(".json"))
        metadata_valid = bool(
            manifest.get("schema_version") == 1
            and manifest.get("sha256")
            and manifest.get("rom_sha256") == self.status.get("rom_sha256")
        )
        if not metadata_valid:
            return False
        try:
            return file_sha256(path) == manifest["sha256"]
        except OSError:
            return False

    def _recover_orphaned_states(self) -> None:
        for state in self.states_dir.glob("state-*.state"):
            if not GENERATED_STATE_RE.fullmatch(state.name):
                continue
            manifest_path = state.with_suffix(".json")
            if manifest_path.exists():
                state.with_suffix(".pending.json").unlink(missing_ok=True)
                manifest = read_json(manifest_path)
                if (
                    manifest.get("schema_version") == 1
                    and manifest.get("rom_sha256")
                    == self.status.get("rom_sha256")
                    and manifest.get("sha256")
                ):
                    try:
                        valid_hash = file_sha256(state) == manifest["sha256"]
                    except OSError:
                        valid_hash = False
                    if not valid_hash:
                        self._quarantine_state(
                            state,
                            state.with_suffix(".pending.json"),
                            "Checkpoint checksum validation failed",
                        )
                continue
            pending_path = state.with_suffix(".pending.json")
            pending = read_json(pending_path)
            recoverable = bool(
                pending.get("schema_version") == 1
                and pending.get("state_name") == state.name
                and pending.get("rom_sha256") == self.status.get("rom_sha256")
                and pending.get("created_at")
            )
            if not recoverable:
                self._quarantine_state(
                    state,
                    pending_path,
                    "Checkpoint provenance is missing or belongs to another ROM",
                )
                continue
            try:
                metadata = state.stat()
                atomic_write_json(
                    manifest_path,
                    {
                        "schema_version": 1,
                        "created_at": pending["created_at"],
                        "reason": pending.get(
                            "reason",
                            "recovered after interrupted checkpoint",
                        ),
                        "kind": checkpoint_kind(
                            pending.get("kind")
                            or pending.get(
                                "reason",
                                "recovered after interrupted checkpoint",
                            )
                        ),
                        "rom_sha256": pending["rom_sha256"],
                        "sha256": file_sha256(state),
                        "bytes": metadata.st_size,
                        "game_state": {},
                        "recovered": True,
                    },
                )
                pending_path.unlink(missing_ok=True)
            except OSError as error:
                LOGGER.warning("Could not recover interrupted checkpoint: %s", error)

    def _quarantine_state(
        self,
        state: Path,
        pending_path: Path,
        reason: str,
    ) -> None:
        quarantine_dir = self.runtime_dir / "quarantine"
        quarantine_dir.mkdir(exist_ok=True, mode=0o700)
        os.chmod(quarantine_dir, 0o700)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = quarantine_dir / f"{state.name}.{timestamp}.orphan"
        os.replace(state, destination)
        if pending_path.exists():
            os.replace(
                pending_path,
                quarantine_dir / f"{pending_path.name}.{timestamp}.orphan",
            )
        atomic_write_json(
            quarantine_dir / f"{destination.name}.reason.json",
            {"reason": reason, "quarantined_at": utc_now()},
        )

    def _remove_generated_clip(self, clip: Path) -> None:
        clip.unlink(missing_ok=True)
        clip.with_suffix(".json").unlink(missing_ok=True)
        (clip.parent / f".{clip.name}.ffmpeg.log").unlink(missing_ok=True)

    def _remove_generated_state(self, state: Path) -> None:
        state.unlink(missing_ok=True)
        state.with_suffix(".json").unlink(missing_ok=True)

    def _generated_artifact_bytes(self) -> int:
        total = 0
        generated_paths: list[Path] = []
        for clip in self.recorder.clips_dir.glob("clip-*.mp4"):
            if self._verified_generated_clip(clip):
                generated_paths.extend([clip, clip.with_suffix(".json")])
                generated_paths.append(clip.parent / f".{clip.name}.ffmpeg.log")
        for state in self.states_dir.glob("state-*.state"):
            if self._verified_generated_state(state):
                generated_paths.extend([state, state.with_suffix(".json")])
        for partial in self.recorder.clips_dir.glob(".clip-*.partial.mp4"):
            if GENERATED_PARTIAL_RE.fullmatch(partial.name):
                generated_paths.append(partial)
        generated_paths.extend(self.screens_dir.glob("decision-*.png"))
        for path in generated_paths:
            try:
                if path.is_file():
                    total += path.stat().st_size
            except FileNotFoundError:
                continue
        return total

    def _prune_stale_partials(self) -> None:
        now = time.time()
        current = self.recorder.partial_path
        for partial in self.recorder.clips_dir.glob(".clip-*.partial.mp4"):
            if partial == current or not GENERATED_PARTIAL_RE.fullmatch(partial.name):
                continue
            try:
                if now - partial.stat().st_mtime < 3600:
                    continue
            except FileNotFoundError:
                continue
            partial.unlink(missing_ok=True)
            log_name = partial.name.removeprefix(".").removesuffix(".partial.mp4")
            (partial.parent / f".{log_name}.ffmpeg.log").unlink(missing_ok=True)

    def _enforce_retention(self) -> None:
        self._prune_stale_partials()
        clips = sorted(
            (
                path
                for path in self.recorder.clips_dir.glob("clip-*.mp4")
                if self._verified_generated_clip(path)
            ),
            key=lambda path: path.stat().st_mtime_ns,
        )
        states = sorted(
            (
                path
                for path in self.states_dir.glob("state-*.state")
                if self._verified_generated_state(path)
            ),
            key=lambda path: path.stat().st_mtime_ns,
        )

        while len(clips) > self.max_clips:
            removable = next(
                (clip for clip in clips if not self._milestone_artifact(clip)),
                None,
            )
            if removable is None:
                break
            self._remove_generated_clip(removable)
            clips.remove(removable)

        newest_state = states[-1] if states else None
        while len(states) > self.max_states:
            removable = next(
                (
                    state
                    for state in states
                    if state != newest_state and not self._milestone_artifact(state)
                ),
                None,
            )
            if removable is None:
                break
            self._remove_generated_state(removable)
            states.remove(removable)

        artifact_bytes = self._generated_artifact_bytes()
        free_bytes = shutil.disk_usage(self.runtime_dir).free
        while (
            artifact_bytes > self.max_storage_bytes or free_bytes < self.min_free_bytes
        ):
            candidates = [
                path
                for path in [*clips, *states]
                if path != newest_state and not self._milestone_artifact(path)
            ]
            if not candidates:
                break
            oldest = min(candidates, key=lambda path: path.stat().st_mtime_ns)
            if oldest.suffix == ".mp4":
                self._remove_generated_clip(oldest)
                clips.remove(oldest)
            else:
                self._remove_generated_state(oldest)
                states.remove(oldest)
            artifact_bytes = self._generated_artifact_bytes()
            free_bytes = shutil.disk_usage(self.runtime_dir).free

        self.status.update(
            {
                "storage_artifact_bytes": artifact_bytes,
                "storage_free_bytes": free_bytes,
                "retained_clips": len(clips),
                "retained_states": len(states),
                "recording_suspended": (
                    artifact_bytes > self.max_storage_bytes
                    or free_bytes < self.min_free_bytes
                ),
            }
        )

    def _brain_loop(self) -> None:
        try:
            brain = CopilotBrain(
                self.args.model,
                self.runtime_dir,
                self.args.decision_timeout,
            )
            self.brain = brain
            brain.start()
        except RuntimeError as error:
            self.status["brain_status"] = "error"
            self.status["last_error"] = str(error)
            self.brain_ready.set()
            return
        self.status["brain_backend"] = brain.backend
        self.status["brain_status"] = "idle"
        self.brain_available.set()
        self.brain_ready.set()
        try:
            while not self.stop_event.is_set():
                request = self.brain_requests.get()
                if request is None:
                    break
                try:
                    decision = brain.decide(
                        screenshot=Path(request["screenshot"]),
                        game_state=request["game_state"],
                        collision_map=request.get("collision_map"),
                        history=request["history"],
                    )
                    self.brain_results.put(
                        {
                            "decision": decision,
                            "decision_id": request["decision_id"],
                            "generation": request["generation"],
                        }
                    )
                except ValueError as error:
                    self.brain_results.put(
                        {
                            "error": str(error),
                            "decision_id": request["decision_id"],
                            "generation": request["generation"],
                        }
                    )
                except Exception as error:
                    # The SDK emits base Exception for session.error notifications.
                    LOGGER.exception("Copilot worker failure")
                    self.status["brain_failure_count"] = (
                        int(self.status.get("brain_failure_count", 0)) + 1
                    )
                    self.brain_results.put(
                        {
                            "error": str(error),
                            "decision_id": request["decision_id"],
                            "generation": request["generation"],
                        }
                    )
                    self.brain_available.clear()
                    self.status["brain_status"] = "recovering"
                    try:
                        brain.recover()
                        self.status["brain_backend"] = brain.backend
                        self.status["brain_status"] = "idle"
                        self.brain_available.set()
                    except Exception as recovery_error:
                        LOGGER.exception("Copilot worker recovery failed")
                        self.status["brain_status"] = "failed"
                        self.status["last_error"] = (
                            f"Copilot recovery failed: {recovery_error}"
                        )
                        self.status["lifecycle"] = "failed"
                        self.stop_event.set()
                        break
        finally:
            try:
                brain.close()
            except Exception:
                LOGGER.exception("Copilot worker shutdown failed")
            self.brain = None

    def _stop_brain_worker(self) -> None:
        self.stop_event.set()
        if self.brain:
            self.brain.cancel()
        try:
            self.brain_requests.put_nowait(None)
        except queue.Full:
            try:
                self.brain_requests.get_nowait()
            except queue.Empty:
                pass
            self.brain_requests.put_nowait(None)
        if not self.brain_thread:
            return
        self.brain_thread.join(timeout=COPILOT_THREAD_SHUTDOWN_TIMEOUT_SECONDS)
        if self.brain_thread.is_alive():
            self.status["last_error"] = (
                "Copilot worker exceeded its bounded shutdown window"
            )
            self.status["lifecycle"] = "failed"
            LOGGER.error("%s", self.status["last_error"])
            try:
                self._write_status()
            except OSError:
                LOGGER.exception("Failed to publish Copilot shutdown failure")
            self.brain_thread.join()

    def _load_latest_state(self) -> Optional[Path]:
        self.status["last_checkpoint"] = None
        if not self.args.resume:
            return None
        state_errors: tuple[type[BaseException], ...] = (
            OSError,
            EOFError,
            RuntimeError,
            ValueError,
        )
        try:
            from pyboy.utils import PyBoyException
        except ImportError:
            pass
        else:
            state_errors += (PyBoyException,)

        self._recover_orphaned_states()

        def checkpoint_timestamp(path: Path) -> float:
            created_at = read_json(path.with_suffix(".json")).get("created_at")
            if created_at:
                try:
                    parsed = datetime.fromisoformat(str(created_at))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return parsed.timestamp()
                except ValueError:
                    pass
            return path.stat().st_mtime

        states = sorted(
            (
                path
                for path in self.states_dir.glob("*.state")
                if self._verified_generated_state(path)
            ),
            key=checkpoint_timestamp,
            reverse=True,
        )
        if not states:
            return None
        baseline = io.BytesIO()
        self.pyboy.save_state(baseline)
        baseline_bytes = baseline.getvalue()
        for state_path in states:
            manifest = read_json(state_path.with_suffix(".json"))
            if manifest.get("rom_sha256") not in (None, self.status["rom_sha256"]):
                LOGGER.warning("Skipping checkpoint for another ROM: %s", state_path)
                continue
            expected_hash = manifest.get("sha256")
            try:
                if expected_hash and file_sha256(state_path) != expected_hash:
                    raise ValueError("checkpoint hash mismatch")
                with state_path.open("rb") as handle:
                    self.pyboy.load_state(handle)
            except state_errors as error:
                LOGGER.warning("Skipping invalid checkpoint %s: %s", state_path, error)
                try:
                    self._quarantine_state(
                        state_path,
                        state_path.with_suffix(".pending.json"),
                        f"Checkpoint validation failed: {type(error).__name__}",
                    )
                except OSError:
                    LOGGER.exception("Could not quarantine invalid checkpoint")
                self.pyboy.load_state(io.BytesIO(baseline_bytes))
                continue
            self.player.release_and_flush(self.pyboy)
            game_state = (
                manifest.get("game_state")
                if isinstance(manifest.get("game_state"), dict)
                else {}
            )
            self.status["last_checkpoint"] = {
                "path": str(state_path),
                "reason": manifest.get("reason"),
                "kind": checkpoint_kind(
                    manifest.get("kind") or manifest.get("reason")
                ),
                "timestamp": manifest.get("created_at"),
                "sha256": manifest.get("sha256"),
                "location": game_state.get("location"),
            }
            self._restore_completed_state(game_state)
            return state_path
        return None

    def _save_checkpoint(self, reason: str, allow_stopped: bool = False) -> Path:
        self.player.release_and_flush(
            self.pyboy,
            require_running=not allow_stopped,
        )
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        state_path = self.states_dir / f"state-{timestamp}.state"
        temporary = self.states_dir / f".{state_path.name}.tmp"
        created_at = utc_now()
        pending_path = state_path.with_suffix(".pending.json")
        atomic_write_json(
            pending_path,
            {
                "schema_version": 1,
                "state_name": state_path.name,
                "created_at": created_at,
                "reason": reason,
                "kind": checkpoint_kind(reason),
                "rom_sha256": self.status["rom_sha256"],
            },
        )
        try:
            with temporary.open("wb") as handle:
                self.pyboy.save_state(handle)
                handle.flush()
                os.fsync(handle.fileno())
            if temporary.stat().st_size == 0:
                raise RuntimeError("PyBoy produced an empty checkpoint")
            os.replace(temporary, state_path)
            os.chmod(state_path, 0o600)
            fsync_directory(self.states_dir)
        except Exception:
            temporary.unlink(missing_ok=True)
            if not state_path.exists():
                pending_path.unlink(missing_ok=True)
            raise
        game_state = PokemonMemoryReader(self.pyboy.memory).snapshot()
        manifest = {
            "schema_version": 1,
            "created_at": created_at,
            "reason": reason,
            "kind": checkpoint_kind(reason),
            "rom_sha256": self.status["rom_sha256"],
            "sha256": file_sha256(state_path),
            "bytes": state_path.stat().st_size,
            "game_state": game_state,
        }
        atomic_write_json(state_path.with_suffix(".json"), manifest)
        pending_path.unlink(missing_ok=True)
        self.status["last_checkpoint"] = {
            "path": str(state_path),
            "reason": reason,
            "kind": checkpoint_kind(reason),
            "timestamp": manifest["created_at"],
            "sha256": manifest["sha256"],
            "location": game_state.get("location"),
        }
        return state_path

    def _write_clip_manifest(
        self,
        clip: Path,
        reason: str,
        frames_written: int,
        started_at: Optional[str],
    ) -> None:
        game_state = (
            self.status.get("game_state")
            if isinstance(self.status.get("game_state"), dict)
            else {}
        )
        manifest = {
            "schema_version": 1,
            "name": clip.name,
            "started_at": started_at,
            "completed_at": utc_now(),
            "reason": reason,
            "frames": frames_written,
            "fps": self.recorder.fps,
            "duration_seconds": round(frames_written / self.recorder.fps, 3),
            "bytes": clip.stat().st_size,
            "sha256": file_sha256(clip),
            "game_state": game_state,
        }
        atomic_write_json(clip.with_suffix(".json"), manifest)

    def _rotate_clip(self, reason: str) -> None:
        frames_written = self.recorder.frames_written
        started_at = self.recorder.started_at
        self._save_checkpoint(reason)
        finished = self.recorder.finish()
        if finished:
            self._write_clip_manifest(finished, reason, frames_written, started_at)
        self.status["last_completed_clip"] = str(finished) if finished else None
        next_clip = self.recorder.start()
        self.status["current_clip"] = str(next_clip)
        self.clip_started = time.monotonic()
        self.next_record_at = self.clip_started
        try:
            self._enforce_retention()
        except OSError as error:
            self.status["last_error"] = f"Artifact retention failed: {error}"
            LOGGER.exception("Artifact retention failed")
        self._write_status()

    def _record_due_frames(self, image: Any) -> None:
        now = time.monotonic()
        interval = 1 / self.recorder.fps
        if self.status.get("recording_suspended"):
            self.next_record_at = now + interval
            return
        if self.next_record_at <= 0:
            self.next_record_at = now
        if now < self.next_record_at:
            return
        due = int((now - self.next_record_at) / interval) + 1
        max_catchup = self.recorder.fps * 2
        write_count = min(due, max_catchup)
        for _ in range(write_count):
            if not self.recorder.write(image):
                self.status["recording_frames_dropped"] = (
                    int(self.status.get("recording_frames_dropped", 0)) + 1
                )
        if due > max_catchup:
            self.status["recording_frames_skipped"] = (
                int(self.status.get("recording_frames_skipped", 0)) + due - max_catchup
            )
            self.next_record_at = now + interval
        else:
            self.next_record_at += due * interval

    def _ram_pair_valid(self, ram_path: Path, manifest_path: Path) -> bool:
        if not ram_path.exists() or not manifest_path.exists():
            return False
        manifest = read_json(manifest_path)
        if not (
            manifest.get("schema_version") == 1
            and manifest.get("rom_sha256") == self.rom_sha256
            and manifest.get("sha256")
        ):
            return False
        try:
            return file_sha256(ram_path) == manifest["sha256"]
        except OSError:
            return False

    def _ram_backup_paths(self) -> tuple[Path, Path]:
        return (
            self.ram_path.with_name(f".{self.ram_path.name}.backup"),
            self.ram_path.with_name(
                f".{self.ram_path.with_suffix('.json').name}.backup"
            ),
        )

    def _ram_pending_path(self) -> Path:
        return self.ram_path.with_name(f".{self.ram_path.name}.pending.json")

    def _quarantine_ram_pair(
        self,
        ram_path: Path,
        manifest_path: Path,
        reason: str,
    ) -> None:
        if not ram_path.exists() and not manifest_path.exists():
            return
        quarantine_dir = self.runtime_dir / "quarantine"
        quarantine_dir.mkdir(exist_ok=True, mode=0o700)
        os.chmod(quarantine_dir, 0o700)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = quarantine_dir / f"{ram_path.name}.{timestamp}.invalid"
        if ram_path.exists():
            os.replace(ram_path, destination)
        if manifest_path.exists():
            os.replace(
                manifest_path,
                quarantine_dir / f"{manifest_path.name}.{timestamp}.invalid",
            )
        atomic_write_json(
            quarantine_dir / f"{destination.name}.reason.json",
            {"reason": reason, "quarantined_at": utc_now()},
        )
        self.status["ram_warning"] = reason

    def _quarantine_ram(self, reason: str) -> None:
        self._quarantine_ram_pair(
            self.ram_path,
            self.ram_path.with_suffix(".json"),
            reason,
        )

    def _recover_ram_transaction(self) -> None:
        backup_ram, backup_manifest = self._ram_backup_paths()
        current_manifest = self.ram_path.with_suffix(".json")
        pending_path = self._ram_pending_path()
        temporary = self.runtime_dir / f".{self.ram_path.name}.tmp"

        def clear_transaction_files() -> None:
            pending_path.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)

        if self._ram_pair_valid(self.ram_path, current_manifest):
            backup_ram.unlink(missing_ok=True)
            backup_manifest.unlink(missing_ok=True)
            clear_transaction_files()
            fsync_directory(self.runtime_dir)
            return
        if self._ram_pair_valid(self.ram_path, pending_path):
            atomic_write_json(current_manifest, read_json(pending_path))
            backup_ram.unlink(missing_ok=True)
            backup_manifest.unlink(missing_ok=True)
            clear_transaction_files()
            fsync_directory(self.runtime_dir)
            return
        if self._ram_pair_valid(temporary, pending_path):
            self._quarantine_ram("Discarded incomplete RAM transaction")
            os.replace(temporary, self.ram_path)
            os.chmod(self.ram_path, 0o600)
            fsync_directory(self.runtime_dir)
            atomic_write_json(current_manifest, read_json(pending_path))
            backup_ram.unlink(missing_ok=True)
            backup_manifest.unlink(missing_ok=True)
            clear_transaction_files()
            fsync_directory(self.runtime_dir)
            return
        if self._ram_pair_valid(backup_ram, current_manifest):
            if self.ram_path.exists():
                self._quarantine_ram_pair(
                    self.ram_path,
                    self.runtime_dir / ".no-ram-manifest",
                    "Discarded incomplete RAM transaction",
                )
            os.replace(backup_ram, self.ram_path)
            backup_manifest.unlink(missing_ok=True)
            clear_transaction_files()
            fsync_directory(self.runtime_dir)
            return
        if self._ram_pair_valid(self.ram_path, backup_manifest):
            current_manifest.unlink(missing_ok=True)
            os.replace(backup_manifest, current_manifest)
            self._quarantine_ram_pair(
                backup_ram,
                self.runtime_dir / ".no-ram-manifest",
                "Preserved incomplete RAM transaction data",
            )
            clear_transaction_files()
            fsync_directory(self.runtime_dir)
            return
        if self._ram_pair_valid(backup_ram, backup_manifest):
            self._quarantine_ram("Recovered previous RAM after interrupted commit")
            os.replace(backup_ram, self.ram_path)
            os.replace(backup_manifest, current_manifest)
            clear_transaction_files()
            fsync_directory(self.runtime_dir)
            return
        if backup_ram.exists() or backup_manifest.exists():
            self._quarantine_ram_pair(
                backup_ram,
                backup_manifest,
                "Invalid interrupted RAM backup",
            )
        if self.ram_path.exists() or current_manifest.exists():
            self._quarantine_ram("Ignored incomplete RAM transaction")
        clear_transaction_files()
        fsync_directory(self.runtime_dir)

    def _adopt_legacy_ram(self) -> None:
        if self.ram_path.exists():
            return
        legacy = self.runtime_dir / "pokemon-red.ram"
        if not legacy.exists():
            return
        legacy_manifest_path = legacy.with_suffix(".json")
        legacy_manifest = read_json(legacy_manifest_path)
        try:
            manifest_matches = bool(
                legacy_manifest.get("rom_sha256") == self.rom_sha256
                and legacy_manifest.get("sha256")
                and file_sha256(legacy) == legacy_manifest["sha256"]
            )
        except OSError:
            manifest_matches = False
        provenance = read_json(
            self.runtime_dir / "legacy-ram-provenance.json"
        )
        previous_hash = provenance.get("rom_sha256")
        format_matches = bool(
            not legacy_manifest_path.exists()
            and previous_hash == self.rom_sha256
            and self.status.get("rom_title", "").upper().startswith("POKEMON RED")
            and legacy.stat().st_size == 32768
        )
        if not (manifest_matches or format_matches):
            self.status["ram_warning"] = (
                "Preserved legacy cartridge RAM because ROM provenance did not match"
            )
            return
        manifest = {
            "schema_version": 1,
            "created_at": utc_now(),
            "rom_sha256": self.rom_sha256,
            "sha256": file_sha256(legacy),
            "bytes": legacy.stat().st_size,
            "migrated_from": legacy.name,
        }
        pending_path = self._ram_pending_path()
        try:
            atomic_write_json(pending_path, manifest)
            os.replace(legacy, self.ram_path)
            os.chmod(self.ram_path, 0o600)
            fsync_directory(self.runtime_dir)
            atomic_write_json(self.ram_path.with_suffix(".json"), manifest)
            legacy_manifest_path.unlink(missing_ok=True)
            pending_path.unlink(missing_ok=True)
            fsync_directory(self.runtime_dir)
        except Exception:
            if self.ram_path.exists() and not legacy.exists():
                os.replace(self.ram_path, legacy)
            self.ram_path.with_suffix(".json").unlink(missing_ok=True)
            pending_path.unlink(missing_ok=True)
            fsync_directory(self.runtime_dir)
            raise

    def _validated_ram_path(self) -> Optional[Path]:
        self._recover_ram_transaction()
        if not any(path.exists() for path in self._ram_backup_paths()):
            self._adopt_legacy_ram()
        if not self.ram_path.exists():
            return None
        if not self._ram_pair_valid(
            self.ram_path,
            self.ram_path.with_suffix(".json"),
        ):
            self._quarantine_ram("Ignored invalid or unverified cartridge RAM")
            return None
        return self.ram_path

    def _save_ram_and_stop(self) -> None:
        temporary = self.runtime_dir / f".{self.ram_path.name}.tmp"
        manifest_path = self.ram_path.with_suffix(".json")
        backup_ram, backup_manifest = self._ram_backup_paths()
        pending_path = self._ram_pending_path()
        self._recover_ram_transaction()
        backed_up = self._ram_pair_valid(self.ram_path, manifest_path)
        backup_started = False
        backup_installed = False
        try:
            with temporary.open("w+b") as ram_output:
                self.pyboy.stop(save=True, ram_file=ram_output)
                ram_output.flush()
                os.fsync(ram_output.fileno())
            manifest = {
                "schema_version": 1,
                "created_at": utc_now(),
                "rom_sha256": self.rom_sha256,
                "sha256": file_sha256(temporary),
                "bytes": temporary.stat().st_size,
            }
            atomic_write_json(pending_path, manifest)
            if backed_up:
                backup_started = True
                os.replace(self.ram_path, backup_ram)
                os.replace(manifest_path, backup_manifest)
                backup_installed = True
                fsync_directory(self.runtime_dir)
            os.replace(temporary, self.ram_path)
            os.chmod(self.ram_path, 0o600)
            fsync_directory(self.runtime_dir)
            atomic_write_json(manifest_path, manifest)
        except Exception:
            if backup_installed:
                failed_path = self.ram_path.with_name(
                    f".{self.ram_path.name}.{uuid.uuid4().hex}.failed"
                )
                if self.ram_path.exists():
                    os.replace(self.ram_path, failed_path)
                manifest_path.unlink(missing_ok=True)
                os.replace(backup_ram, self.ram_path)
                os.replace(backup_manifest, manifest_path)
                pending_path.unlink(missing_ok=True)
                temporary.unlink(missing_ok=True)
                fsync_directory(self.runtime_dir)
            elif backup_started:
                try:
                    self._recover_ram_transaction()
                except Exception:
                    LOGGER.exception("Could not recover partial RAM backup")
            elif backed_up:
                pending_path.unlink(missing_ok=True)
                temporary.unlink(missing_ok=True)
                fsync_directory(self.runtime_dir)
            elif not pending_path.exists():
                temporary.unlink(missing_ok=True)
            raise
        else:
            backup_ram.unlink(missing_ok=True)
            backup_manifest.unlink(missing_ok=True)
            pending_path.unlink(missing_ok=True)
            fsync_directory(self.runtime_dir)

    def _read_external_controls(self) -> None:
        try:
            with self.control_path.open("r", encoding="utf-8") as handle:
                handle.seek(self.control_offset)
                for line in handle:
                    try:
                        command = json.loads(line)
                    except json.JSONDecodeError:
                        LOGGER.warning("Ignored malformed control line")
                        continue
                    if isinstance(command, dict):
                        self.controls.put(command)
                self.control_offset = handle.tell()
        except OSError as error:
            self.status["last_error"] = f"Control queue error: {error}"

    def _set_control_mode(self, mode: str) -> None:
        if mode not in {"ai", "manual", "paused"}:
            raise ValueError(f"Unknown control mode: {mode}")
        if mode == "paused":
            if self.control_mode != "paused":
                self.resume_mode = self.control_mode
        else:
            self.resume_mode = mode
        self.control_generation += 1
        self.control_mode = mode
        self.paused = mode == "paused"
        self._sync_emulator_pause()
        self.player.release(self.pyboy)
        if mode == "ai":
            self.last_decision_finished = 0
            self.status["brain_status"] = (
                "thinking" if self.decision_pending else "idle"
            )
        elif mode == "manual":
            self.status["brain_status"] = "manual"
        else:
            self.status["brain_status"] = "paused"

    def _set_emulator_paused(self, paused: bool) -> None:
        if paused == self.emulator_pause_requested:
            return
        from pyboy.utils import WindowEvent

        self.pyboy.send_input(WindowEvent.PAUSE if paused else WindowEvent.UNPAUSE)
        self.emulator_pause_requested = paused

    def _sync_emulator_pause(self) -> None:
        should_pause = self.control_mode == "paused" or (
            self.control_mode == "ai" and self.decision_pending
        )
        self._set_emulator_paused(should_pause)

    def _process_controls(self) -> None:
        while True:
            try:
                command = self.controls.get_nowait()
            except queue.Empty:
                break
            action = str(command.get("action", "")).lower()
            if action == "pause":
                self._set_control_mode("paused")
            elif action == "resume":
                self._set_control_mode(self.resume_mode)
            elif action == "manual":
                self._set_control_mode("manual")
            elif action == "autonomy":
                self._set_control_mode("ai")
            elif action == "checkpoint":
                self._rotate_clip("manual checkpoint")
            elif action == "press":
                button = str(command.get("button", "")).lower()
                if button in VALID_BUTTONS:
                    self._set_control_mode("manual")
                    self.player.append(button)
            elif action == "stop":
                self.stop_event.set()

    def _save_latest_frame(self, image: Any) -> None:
        temporary = self.runtime_dir / ".latest.png.tmp"
        image.save(temporary, format="PNG")
        latest = self.runtime_dir / "latest.png"
        os.replace(temporary, latest)
        os.chmod(latest, 0o600)
        if not (
            self.livestream_enabled
            and self.livestream_host == "kite"
            and self.stream_generation
        ):
            return
        payload = latest.read_bytes()
        valid_png = bool(
            33 <= len(payload) <= MAX_KITE_FRAME_BYTES
            and payload.startswith(b"\x89PNG\r\n\x1a\n")
            and payload[12:16] == b"IHDR"
            and int.from_bytes(payload[16:20], "big") == 160
            and int.from_bytes(payload[20:24], "big") == 144
        )
        if not valid_png:
            LOGGER.warning("Latest frame did not meet the kite PNG contract")
            return
        self.kite_frame_sequence += 1
        atomic_write_json(
            self.runtime_dir / "kite-frame.json",
            {
                "schema_version": KITE_STRING_SCHEMA_VERSION,
                "generation": self.stream_generation,
                "sequence": self.kite_frame_sequence,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
                "updated_at": utc_now(),
            },
        )

    def _request_decision(
        self, image: Any, game_state: dict[str, Any], collision_map: Optional[str]
    ) -> None:
        screenshot = (
            self.screens_dir
            / f"decision-{self.run_id}-{self.decision_sequence + 1:08d}.png"
        )
        image.save(screenshot, format="PNG")
        decision_state = dict(game_state)
        route_guidance = (
            rock_tunnel_route_guidance(game_state)
            or celadon_route_guidance(game_state)
        )
        if route_guidance:
            decision_state["route_guidance"] = route_guidance
        request = {
            "decision_id": self.decision_sequence + 1,
            "generation": self.control_generation,
            "screenshot": str(screenshot),
            "game_state": decision_state,
            "collision_map": collision_map,
            "history": list(self.history[-8:]),
        }
        self.decision_sequence += 1
        self.pending_decision_id = request["decision_id"]
        self.decision_pending = True
        self._sync_emulator_pause()
        try:
            self.brain_requests.put_nowait(request)
        except queue.Full as error:
            self.decision_pending = False
            self.pending_decision_id = None
            self._sync_emulator_pause()
            raise RuntimeError("Copilot request queue is unexpectedly full") from error
        self.last_decision_requested = time.monotonic()
        self.status["brain_status"] = "thinking"
        self.status["model_calls"] += 1

        self._prune_decision_screenshots(screenshot)

    def _prune_decision_screenshots(
        self,
        current_screenshot: Path,
        keep: int = 30,
    ) -> None:
        candidates = [
            path
            for path in self.screens_dir.glob("decision-*.png")
            if path != current_screenshot
        ]
        candidates.sort(key=lambda path: path.stat().st_mtime_ns)
        retained_old_count = max(0, keep - 1)
        stale = candidates[:-retained_old_count] if retained_old_count else candidates
        for old_screenshot in stale:
            old_screenshot.unlink(missing_ok=True)

    def _apply_brain_result(self) -> None:
        try:
            result = self.brain_results.get_nowait()
        except queue.Empty:
            return
        decision_id = result.get("decision_id")
        generation = result.get("generation")
        if decision_id == self.pending_decision_id:
            self.decision_pending = False
            self.pending_decision_id = None
            self._sync_emulator_pause()
        self.last_decision_finished = time.monotonic()
        if generation != self.control_generation or self.control_mode != "ai":
            self.status["last_discarded_decision"] = {
                "decision_id": decision_id,
                "reason": "control ownership changed",
                "timestamp": utc_now(),
            }
            self.status["brain_status"] = (
                "manual" if self.control_mode == "manual" else self.control_mode
            )
            return
        if result.get("error"):
            self.status["brain_status"] = "error"
            self.status["last_error"] = str(result["error"])
            LOGGER.error("Copilot decision error: %s", result["error"])
            return

        decision = result["decision"]
        self.status["brain_status"] = "acting"
        self.status["last_error"] = None
        self.status["observation"] = decision["observation"]
        self.status["phase"] = decision["phase"]
        self.status["objective"] = decision["objective"]
        self.status["reason"] = decision["reason"]
        self.status["last_action"] = decision["buttons"]
        self.player.replace(decision["buttons"])
        history_item = {
            "timestamp": utc_now(),
            "location": self.status.get("game_state", {}).get("location"),
            **decision,
        }
        self.history.append(history_item)
        self.history = self.history[-50:]
        self.total_decisions += 1
        atomic_write_json(
            self.runtime_dir / "brain.json",
            {
                "history": self.history,
                "total_decisions": self.total_decisions,
                "updated_at": utc_now(),
            },
        )
        if decision["checkpoint"]:
            self._rotate_clip(f"Copilot checkpoint: {decision['objective'][:120]}")

    def _maybe_milestone(self, game_state: dict[str, Any]) -> None:
        badge_count = len(game_state.get("badges", []))
        if badge_count > self.last_badges:
            self.last_badges = badge_count
            self._rotate_clip(f"Badge milestone: {game_state['badges'][-1]}")
        if game_state.get("hall_of_fame") and not self.status["completed"]:
            self.status["completed"] = True
            self._rotate_clip("Pokemon Red completed: Hall of Fame")
            self._set_control_mode("paused")

    def _restore_completed_state(self, game_state: dict[str, Any]) -> bool:
        if game_state.get("hall_of_fame") is not True:
            return False
        self.status["completed"] = True
        if getattr(self, "control_mode", None) != "paused":
            self._set_control_mode("paused")
        return True

    def _tick_emulator(self) -> bool:
        should_apply_input = self.control_mode != "paused" and not (
            self.control_mode == "ai" and self.decision_pending
        )
        if should_apply_input:
            self.player.tick(self.pyboy)
        return bool(self.pyboy.tick())

    def _shutdown_runtime(self, reason: str) -> None:
        cleanup_errors: list[str] = []
        self.stop_event.set()
        kite_sidecar = getattr(self, "kite_sidecar", None)
        if kite_sidecar:
            try:
                kite_sidecar.stop()
            except Exception as error:
                cleanup_errors.append(f"kited twin string: {error}")
                LOGGER.exception("Kited twin string shutdown failed")
            self.kite_sidecar = None
        try:
            self.player.release(self.pyboy)
        except Exception as error:
            cleanup_errors.append(f"controller release: {error}")
            LOGGER.exception("Controller release failed during shutdown")

        try:
            self._save_checkpoint(reason, allow_stopped=True)
        except Exception as error:
            cleanup_errors.append(f"checkpoint: {error}")
            LOGGER.exception("Checkpoint shutdown failed")

        try:
            frames_written = self.recorder.frames_written
            started_at = self.recorder.started_at
            finished = self.recorder.finish()
            if finished:
                self._write_clip_manifest(
                    finished,
                    reason,
                    frames_written,
                    started_at,
                )
            self.status["last_completed_clip"] = (
                str(finished) if finished else self.status.get("last_completed_clip")
            )
        except Exception as error:
            cleanup_errors.append(f"recorder: {error}")
            LOGGER.exception("Recorder shutdown failed")

        try:
            self._stop_brain_worker()
        except Exception as error:
            cleanup_errors.append(f"Copilot worker: {error}")
            LOGGER.exception("Copilot worker shutdown failed")

        try:
            self.viewer.stop()
        except Exception as error:
            cleanup_errors.append(f"viewer: {error}")
            LOGGER.exception("Viewer shutdown failed")

        spectator = getattr(self, "spectator", None)
        if spectator:
            try:
                spectator.stop()
            except Exception as error:
                cleanup_errors.append(f"spectator server: {error}")
                LOGGER.exception("Spectator server shutdown failed")
        (self.runtime_dir / "livestream-auth.json").unlink(missing_ok=True)
        (self.runtime_dir / "livestream-status.json").unlink(missing_ok=True)
        for private_name in KiteBroadcaster.PRIVATE_FILES:
            if private_name == KiteBroadcaster.OWNER_FILE:
                continue
            (self.runtime_dir / private_name).unlink(missing_ok=True)
        self.manual_return_token = None
        livestream = self.status.get("livestream")
        if isinstance(livestream, dict):
            livestream.update({"state": "offline", "viewer_count": 0})

        try:
            self._save_ram_and_stop()
        except Exception as error:
            cleanup_errors.append(f"cartridge RAM: {error}")
            LOGGER.exception("Cartridge RAM shutdown failed")

        try:
            self._enforce_retention()
        except Exception as error:
            cleanup_errors.append(f"retention: {error}")
            LOGGER.exception("Artifact retention failed during shutdown")

        self.status["current_clip"] = None
        self.status["running"] = False
        self.status["stopped_at"] = utc_now()
        if cleanup_errors:
            previous_error = self.status.get("last_error")
            errors = ([str(previous_error)] if previous_error else []) + cleanup_errors
            self.status["last_error"] = "; ".join(errors)
            self.status["lifecycle"] = "failed"
        elif self.status.get("lifecycle") != "failed":
            self.status["lifecycle"] = "stopped"
        try:
            self._write_status()
        except OSError:
            LOGGER.exception("Failed to publish terminal Pokemon status")
        (self.runtime_dir / "pid").unlink(missing_ok=True)

    def run(self) -> None:
        if not is_pokemon_red_rom(self.rom):
            raise StartupConfigurationError(f"Not a Pokemon Red ROM: {self.rom}")
        existing = read_json(self.status_path)
        if (
            process_is_alive(existing.get("pid"))
            and int(existing["pid"]) != os.getpid()
        ):
            raise RuntimeError(
                f"Pokemon player is already running as PID {existing['pid']}"
            )

        from pyboy import PyBoy

        emulator_errors: tuple[type[BaseException], ...] = (OSError, ValueError)
        try:
            from pyboy.utils import PyBoyException
        except ImportError:
            pass
        else:
            emulator_errors += (PyBoyException,)

        window = "SDL2" if self.args.visible else "null"

        def create_emulator(ram_path: Optional[Path]) -> Any:
            ram_input = ram_path.open("rb") if ram_path else None
            try:
                with self.rom.open("rb") as rom_input:
                    return PyBoy(
                        rom_input,
                        window=window,
                        scale=4,
                        sound_volume=0,
                        sound_emulated=False,
                        ram_file=ram_input,
                    )
            finally:
                if ram_input:
                    ram_input.close()

        validated_ram = self._validated_ram_path()
        try:
            self.pyboy = create_emulator(validated_ram)
        except emulator_errors as ram_error:
            if validated_ram is None:
                raise
            try:
                self.pyboy = create_emulator(None)
            except emulator_errors as retry_error:
                raise retry_error from ram_error
            self._quarantine_ram(f"PyBoy rejected cartridge RAM: {ram_error}")
        self.pyboy.set_emulation_speed(1)
        for _ in range(90):
            if not self.pyboy.tick():
                raise RuntimeError("PyBoy stopped during startup")

        loaded_state = self._load_latest_state()
        self.status["loaded_state"] = str(loaded_state) if loaded_state else None
        reader = PokemonMemoryReader(self.pyboy.memory)
        initial_state = reader.snapshot()
        self._restore_completed_state(initial_state)
        self.last_badges = len(initial_state.get("badges", []))
        self.status["game_state"] = initial_state
        initial_image = self.pyboy.screen.image.copy()
        self._save_latest_frame(initial_image)

        self.brain_thread = threading.Thread(
            target=self._brain_loop,
            name="pokemon-copilot-brain",
            daemon=False,
        )
        try:
            self._start_web_servers()
            self._write_status()
            self._start_kite_sidecar()
            self.brain_thread.start()
            startup_wait = (
                COPILOT_START_TIMEOUT_SECONDS + COPILOT_STOP_TIMEOUT_SECONDS + 5
            )
            if not self.brain_ready.wait(timeout=startup_wait):
                raise RuntimeError(
                    f"Copilot brain did not initialize within {startup_wait} seconds"
                )
            if self.stop_event.is_set():
                raise RuntimeError("Pokemon startup was cancelled")
            if self.status.get("brain_status") == "error":
                raise RuntimeError(
                    str(self.status.get("last_error", "Copilot brain failed"))
                )
            clip = self.recorder.start()
            self.status["current_clip"] = str(clip)
            self.clip_started = time.monotonic()
            self.next_record_at = self.clip_started
            self._record_due_frames(initial_image)
            self._enforce_retention()
            self.status["lifecycle"] = "ready"
            self._write_status()

            if self.args.open_viewer or (
                self.args.livestream and self.livestream_host == "local"
            ):
                viewer_url = authenticated_viewer_url(
                    self.runtime_dir,
                    {"port": self.viewer.port},
                )
                threading.Timer(
                    1.0,
                    lambda: webbrowser.open(viewer_url),
                ).start()
        except Exception:
            self._shutdown_runtime("startup failed")
            raise

        last_status_write = 0.0
        last_retention_check = 0.0
        try:
            while not self.stop_event.is_set():
                self._read_external_controls()
                self._process_controls()
                self._apply_brain_result()

                if not self._tick_emulator():
                    self.stop_event.set()
                    break

                self.frames += 1
                image = self.pyboy.screen.image.copy()
                self._record_due_frames(image)
                if self.frames % 6 == 0:
                    self._save_latest_frame(image)

                game_state = reader.snapshot()
                if self.frames % 30 == 0:
                    self.status["game_state"] = game_state
                    self._maybe_milestone(game_state)

                if (
                    self.control_mode == "ai"
                    and self.brain_available.is_set()
                    and not self.decision_pending
                    and self.player.idle
                    and time.monotonic() - self.last_decision_finished >= 1.0
                ):
                    self._request_decision(
                        image, game_state, collision_ascii(self.pyboy)
                    )

                if time.monotonic() - self.clip_started >= self.args.clip_minutes * 60:
                    self._rotate_clip("automatic clip boundary")

                if time.monotonic() - last_retention_check >= 30:
                    try:
                        self._enforce_retention()
                    except OSError as error:
                        self.status["last_error"] = (
                            f"Artifact retention failed: {error}"
                        )
                        LOGGER.exception("Artifact retention failed")
                    last_retention_check = time.monotonic()

                if (
                    self.frames % 30 == 0
                    and time.monotonic() - last_status_write >= 0.5
                ):
                    self.status["actions_taken"] = self.total_decisions
                    self._write_status()
                    last_status_write = time.monotonic()
        finally:
            self._shutdown_runtime("session stopped")


def add_runtime_arguments(
    parser: argparse.ArgumentParser,
    *,
    include_supervised: bool = False,
) -> None:
    def port_value(value: str) -> int:
        try:
            return validate_livestream_port(value, "port")
        except ValueError as error:
            raise argparse.ArgumentTypeError(str(error)) from error

    def max_viewers_value(value: str) -> int:
        try:
            count = int(value)
        except ValueError as error:
            raise argparse.ArgumentTypeError("max viewers must be an integer") from error
        if not 1 <= count <= HARD_MAX_VIEWERS:
            raise argparse.ArgumentTypeError(
                f"max viewers must be 1-{HARD_MAX_VIEWERS}"
            )
        return count

    parser.add_argument("--rom", required=True)
    parser.add_argument("--runtime-dir", default=str(DEFAULT_RUNTIME_DIR), type=Path)
    parser.add_argument("--port", type=port_value, default=DEFAULT_PORT)
    parser.add_argument("--livestream", action="store_true")
    parser.add_argument(
        "--livestream-host",
        choices=("kite", "local"),
        default=DEFAULT_LIVESTREAM_HOST,
    )
    parser.add_argument(
        "--signaling",
        choices=("nostr", "peerjs"),
        default=None,
    )
    parser.add_argument("--browser-path", default="")
    parser.add_argument("--host-base", default=DEFAULT_PAGES_HOST_BASE)
    parser.add_argument(
        "--bridge-startup-timeout",
        type=float,
        default=DEFAULT_BRIDGE_STARTUP_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--spectator-port",
        type=port_value,
        default=DEFAULT_SPECTATOR_PORT,
    )
    parser.add_argument("--advertised-host")
    parser.add_argument("--join-base")
    parser.add_argument(
        "--max-viewers",
        type=max_viewers_value,
        default=DEFAULT_MAX_VIEWERS,
    )
    parser.add_argument("--clip-minutes", type=float, default=10)
    parser.add_argument("--model", default="gpt-5.6-sol")
    parser.add_argument("--decision-timeout", type=int, default=180)
    parser.add_argument("--instance-id", default=None)
    parser.add_argument("--max-clips", type=int, default=DEFAULT_MAX_CLIPS)
    parser.add_argument("--max-states", type=int, default=DEFAULT_MAX_STATES)
    parser.add_argument(
        "--max-storage-gb",
        type=float,
        default=DEFAULT_MAX_STORAGE_GB,
    )
    parser.add_argument("--min-free-gb", type=float, default=DEFAULT_MIN_FREE_GB)
    parser.add_argument("--visible", action="store_true")
    parser.add_argument("--open-viewer", action="store_true")
    parser.add_argument(
        "--no-resume", action="store_false", dest="resume", default=True
    )
    if include_supervised:
        parser.add_argument("--supervised", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Copilot Plays Pokemon Red")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run the persistent player")
    add_runtime_arguments(run_parser, include_supervised=True)
    supervisor_parser = subparsers.add_parser(
        "supervise",
        help="Run and restart the player after unexpected child failures",
    )
    add_runtime_arguments(supervisor_parser)
    return parser


def runtime_command(args: argparse.Namespace, *, open_viewer: bool) -> list[str]:
    command = [
        sys.executable,
        "-m",
        MODULE_NAME,
        "run",
        "--rom",
        str(args.rom),
        "--runtime-dir",
        str(args.runtime_dir),
        "--port",
        str(args.port),
        "--clip-minutes",
        str(args.clip_minutes),
        "--model",
        str(args.model),
        "--decision-timeout",
        str(args.decision_timeout),
        "--instance-id",
        str(args.instance_id),
        "--max-clips",
        str(args.max_clips),
        "--max-states",
        str(args.max_states),
        "--max-storage-gb",
        str(args.max_storage_gb),
        "--min-free-gb",
        str(args.min_free_gb),
        "--livestream-host",
        str(args.livestream_host),
        "--browser-path",
        str(args.browser_path),
        "--host-base",
        str(args.host_base),
        "--bridge-startup-timeout",
        str(args.bridge_startup_timeout),
        "--supervised",
    ]
    if args.signaling:
        command.extend(["--signaling", str(args.signaling)])
    if args.livestream:
        command.extend(
            [
                "--livestream",
                "--spectator-port",
                str(args.spectator_port),
                "--max-viewers",
                str(args.max_viewers),
            ]
        )
        if args.advertised_host:
            command.extend(["--advertised-host", str(args.advertised_host)])
        if args.join_base:
            command.extend(["--join-base", str(args.join_base)])
    if args.visible:
        command.append("--visible")
    if (open_viewer and args.open_viewer) or (
        args.livestream and args.livestream_host == "local"
    ):
        command.append("--open-viewer")
    if not args.resume:
        command.append("--no-resume")
    return command


def terminate_isolated_process_group(
    process: subprocess.Popen[Any],
    *,
    graceful_timeout: float = SUPERVISOR_SHUTDOWN_TIMEOUT_SECONDS + 10,
    kill_timeout: float = 10,
) -> int:
    returncode = process.poll()
    if returncode is not None:
        return int(returncode)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except (AttributeError, PermissionError):
        process.terminate()
    try:
        return int(process.wait(timeout=graceful_timeout))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except (AttributeError, PermissionError):
            process.kill()
        return int(process.wait(timeout=kill_timeout))


def terminate_supervised_child(child: subprocess.Popen[Any]) -> int:
    returncode = child.poll()
    if returncode is not None:
        return int(returncode)
    child.terminate()
    try:
        return child.wait(timeout=SUPERVISOR_SHUTDOWN_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        child.kill()
        return child.wait(timeout=10)


def wait_for_supervised_child(
    child: subprocess.Popen[Any],
    stop_requested: threading.Event,
    runtime_dir: Optional[Path] = None,
) -> tuple[int, bool]:
    while True:
        try:
            return child.wait(timeout=1), False
        except subprocess.TimeoutExpired:
            if runtime_dir:
                desired_running = read_json(
                    runtime_dir / "desired.json",
                    {"running": True},
                ).get("running", True)
                if not desired_running:
                    stop_requested.set()
                status = read_json(runtime_dir / "status.json")
                status_matches_child = status.get("pid") == child.pid
                failed = status_matches_child and status.get("lifecycle") == "failed"
                stale = status_matches_child and (
                    (
                        status.get("lifecycle") == "ready"
                        and heartbeat_is_stale(
                            status,
                            SUPERVISOR_HEARTBEAT_TIMEOUT_SECONDS,
                        )
                    )
                    or (
                        status.get("lifecycle") == "initializing"
                        and heartbeat_is_stale(
                            status,
                            SUPERVISOR_STARTUP_TIMEOUT_SECONDS,
                        )
                    )
                )
                if (failed or stale) and not stop_requested.is_set():
                    reason = "failed" if failed else "stale heartbeat"
                    LOGGER.error(
                        "Supervisor terminating Pokemon child after %s",
                        reason,
                    )
                    atomic_write_json(
                        runtime_dir / RESTART_REQUEST_NAME,
                        {
                            "child_pid": child.pid,
                            "reason": reason,
                            "requested_at": utc_now(),
                        },
                    )
                    return terminate_supervised_child(child), True
            if not stop_requested.is_set():
                continue
            return terminate_supervised_child(child), False


def supervisor_main(args: argparse.Namespace) -> int:
    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime_dir, 0o700)
    if not args.instance_id:
        args.instance_id = uuid.uuid4().hex
    try:
        lock_handle = acquire_runtime_lock(
            runtime_dir,
            f"supervisor-{args.instance_id}",
            "supervisor.lock",
        )
    except RuntimeError:
        LOGGER.error("Another Pokemon supervisor owns this runtime directory")
        return 2

    desired = {
        "running": True,
        "instance_id": args.instance_id,
        "updated_at": utc_now(),
        "config": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in vars(args).items()
            if key != "command"
        },
    }
    atomic_write_json(runtime_dir / "desired.json", desired)
    stop_requested = threading.Event()
    child: Optional[subprocess.Popen[Any]] = None
    supervisor_exit_code = 0

    def request_stop(signum: int, frame: Any) -> None:
        del signum, frame
        stop_requested.set()
        set_desired_running(runtime_dir, False)
        if child and child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    restart_times: deque[float] = deque()
    first_launch = True
    try:
        while not stop_requested.is_set():
            (runtime_dir / RESTART_REQUEST_NAME).unlink(missing_ok=True)
            child = subprocess.Popen(
                runtime_command(args, open_viewer=first_launch),
                stdin=subprocess.DEVNULL,
            )
            first_launch = False
            atomic_write_json(
                runtime_dir / "supervisor.json",
                {
                    "running": True,
                    "pid": os.getpid(),
                    "child_pid": child.pid,
                    "instance_id": args.instance_id,
                    "restart_timestamps": [
                        datetime.fromtimestamp(value, timezone.utc).isoformat()
                        for value in restart_times
                    ],
                    "updated_at": utc_now(),
                },
            )
            exit_code, restart_required = wait_for_supervised_child(
                child,
                stop_requested,
                runtime_dir,
            )
            child_pid = child.pid
            child = None
            if not read_json(
                runtime_dir / "desired.json",
                {"running": True},
            ).get("running", True):
                stop_requested.set()
            if stop_requested.is_set() or (exit_code == 0 and not restart_required):
                break
            child_status = read_json(runtime_dir / "status.json")
            nonretryable = exit_code == 2 or (
                child_status.get("pid") == child_pid
                and child_status.get("restartable") is False
            )
            if nonretryable:
                supervisor_exit_code = exit_code or 1
                LOGGER.error(
                    "Pokemon child has a non-retryable startup failure: %s",
                    child_status.get("last_error", f"exit code {exit_code}"),
                )
                break

            now = time.time()
            restart_times.append(now)
            while restart_times and now - restart_times[0] > 600:
                restart_times.popleft()
            if len(restart_times) > 10:
                LOGGER.error("Pokemon supervisor restart circuit opened")
                return 1
            time.sleep(min(30, 2 ** min(len(restart_times), 4)))
    finally:
        if child and child.poll() is None:
            terminate_supervised_child(child)
        desired["running"] = False
        desired["updated_at"] = utc_now()
        atomic_write_json(runtime_dir / "desired.json", desired)
        atomic_write_json(
            runtime_dir / "supervisor.json",
            {
                "running": False,
                "pid": os.getpid(),
                "instance_id": args.instance_id,
                "stopped_at": utc_now(),
            },
        )
        (runtime_dir / RESTART_REQUEST_NAME).unlink(missing_ok=True)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()
    return supervisor_exit_code


def runner_main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    os.umask(0o077)
    if args.command == "supervise":
        return supervisor_main(args)
    if not args.instance_id:
        args.instance_id = uuid.uuid4().hex
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    runtime_dir = Path(args.runtime_dir).expanduser().resolve()
    try:
        lock_handle = acquire_runtime_lock(runtime_dir, args.instance_id)
    except RuntimeError as error:
        LOGGER.error("%s", error)
        return 2

    runner: Optional[PokemonRunner] = None
    try:
        runner = PokemonRunner(args)

        def request_stop(signum: int, frame: Any) -> None:
            del signum, frame
            if runner:
                runner.stop_event.set()
                runner.brain_ready.set()
                if runner.brain:
                    runner.brain.cancel()

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        atomic_write_json(
            runtime_dir / "status.json",
            {
                "running": True,
                "pid": os.getpid(),
                "instance_id": args.instance_id,
                "port": args.port,
                "lifecycle": "initializing",
                "brain_status": "starting",
                "livestream": {
                    "enabled": bool(args.livestream),
                    "host": args.livestream_host if args.livestream else None,
                    "signaling": (
                        args.signaling
                        or (
                            DEFAULT_SIGNALING
                            if args.livestream_host == "kite"
                            else "peerjs"
                        )
                    ) if args.livestream else None,
                    "state": "offline",
                    "viewer_count": 0,
                    "max_viewers": args.max_viewers if args.livestream else 0,
                    "spectator_port": None,
                    "generation": runner.stream_generation,
                },
                "started_at": utc_now(),
            },
        )
        pid_descriptor = os.open(
            runtime_dir / "pid",
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(pid_descriptor, "w", encoding="ascii") as pid_handle:
            pid_handle.write(str(os.getpid()))
        runner.run()
        return 1 if runner.status.get("lifecycle") == "failed" else 0
    except Exception as error:
        LOGGER.exception("Pokemon player failed")
        status = runtime_status(runtime_dir)
        status.update(
            {
                "running": False,
                "pid": os.getpid(),
                "instance_id": args.instance_id,
                "lifecycle": "failed",
                "last_error": str(error),
                "restartable": not isinstance(error, StartupConfigurationError),
                "failure_kind": (
                    "configuration"
                    if isinstance(error, StartupConfigurationError)
                    else "runtime"
                ),
                "stopped_at": utc_now(),
            }
        )
        atomic_write_json(runtime_dir / "status.json", status)
        return 1
    finally:
        (runtime_dir / "pid").unlink(missing_ok=True)
        if fcntl is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(runner_main())
