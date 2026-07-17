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
    b"e77bfc06dffc27f310d43e09734d274993b80a98d0a9a10f5505efda5242d99d"
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
    "iceServers": [{"urls": "stun:stun.l.google.com:19302"}],
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
    b"eNq9vWl727iSMPr9/gpZ10cvGcOK7SydpoJovCVOYsduL9k8HocSIYmxRCokZVuR+N9vVWEhSMnu"
    b"PjPz3vTTMgmAWAqF2lAo3PpJ7XQ8Pk+maSaS+FOcZgl3HJe/md1C1nbGjzs/RTdrBqIXRuIkicci"
    b"yaYtzIxindkX2fFdpDP3RNpNwnEWJ1QseaDYJ38kUioRmxLjJM7ibDoWzYGfWmWpWBpzR7AM+9aL"
    b"E4e6UAujWuZuZ5ARsRk04GWX0RUT0WQkEr8zFN7KRu7mzJffQqEEvw97TtZoYENxr5ZxXo+p/fp8"
    b"bqX1JlE3C+Oo7mJzQ5HV0hpkJbGTue5KHDe7/nAItaZuo5GucB41GtSRVHYEgZhdpuXOOAmP4Hv4"
    b"xp3Pk2aRlbutRGSTJKqJnEYbxlzwN37sQJ2znNWvr0V6FAeToagzmJvhRA6NCZeKf075LG+lsfMZ"
    b"mofJ8ifD7FQM/elFMkypL7cZC8J0HKeC0s/i7o3IZNZJxqDHlHwg/GE2oNQviUm1C78T7GccRqdx"
    b"PKL3twkb+xNV66noxlEkCG6U+0uwRKQwyuXZHwFcYth7H9Db91wO5jTSCNFLhPgtnNnY27jv/ff+"
    b"CfrtbvUiFv19LaLj+yLoipd+7/krf+NZp9MLtl6IV91g49nL55vPNyM28ODH9zYi1vH+iNi7e6j1"
    b"jz874uXLP0Tvz6Db6fjdFy/8jZdbf77oild/bHQ2/tjY+rPT6wadLah661Xw54s/e1uvNl90Nl/2"
    b"Xm3+8ecrqGYK1Tx/9cwP/D/+2HrpP+s+f/niReA/78GHG2Jzc+OV/6oXbP7ReQ4de/nqxYvnm3/+"
    b"2X3+R7DxqtfrbG4EzzuvIkAIgNUtrAbvL4Fd68ZY8zCGvm5HOT8FIAj+bIv9FPzlc3aU8dl40hmG"
    b"3Y9i6kVibZOZ14uoG4/GMHmpCLyfmJWG/cgHHBXwCtMGyfBFJJ5u5ewLLC9er7OM7ydJTGsMF0zE"
    b"I3FXg0UB3er6Y/z2LPO7N+eJ3xVeksvSrWyQxFBMLr3EXnqNRuJE7IvLopz1aEUIWPJp5kddLHsR"
    b"Rtmr7STxp/M5/dmZwBQmzTD9HIo7aLbREE1AOaBqky4QpGYERIdDA8WHdSyy8+18/+z6ZP/0ev9w"
    b"/2j/0zmU2WShUEQDRqZHlPBejMNJuWg3hyLqZwPm8wyW/20cBrWNFpCWlWQ+9yVNyFz6Kkbi8KO+"
    b"Oovyeu0HC7nf/oG0RFZQW51l+Q8PwNflSfuHTOSrsxQSfyBU4FkBR+Q/2ITHa3VxP4b1IQILBPW1"
    b"cK3Oav04q9XXupqcJO0vzoSd+lFfyKnx8P0cqpOvuSE77LNAAOOMFZXiWPcjTXhFM4vPsiSM+s7m"
    b"S7c59gOYziQDglbfqLvsKMIKaMQZwKyl6WaEYw0F1OVma3w/gindMvQuy4HM8Nn1hvf8Fbv+03vx"
    b"B9v2Xr5gb70/NmCZ/fkH63mbG4BjA6pdvOF90bzegGl7TU9/tsU6pXgya1vnvIUMBxPWNzdclenr"
    b"zJ7K9ClTzh3bLfV/IO4B14DUhkEdp1VPwQqvpwSDuquG8AU4Qkviu9BIAYT+6RZ+Fv1ra6Fcyj8L"
    b"J3ENgHy+wWK+0fJfJy1/bY3Fa3xLYk7IB5EDODzwk904EMAMYtcFPFlIXdt0XWwu5BoV5/OueS71"
    b"IL30r3j4ZPPlWlfPfpqzO5hlmOL+MO74w/NBmLab3WQKbLzdTCedbCjagEl1maRSaqNJmtU6oial"
    b"g4DVcK2FgUhq43g47YXDIWDFBSyjZrMpXAPajVaJowrECkCP1FXAU7AEGGUuAHKheNRMReakwMtZ"
    b"ssZT/ZUaC5CKwwzpUYRNOosDclESgRURxKPPyEhT5zPhJtvN+E7Yfx9l7FgYeYHXO35QA0bdEYlX"
    b"iycZCQG4npAoWEjRCfuwbOoApcRaX172mgvEuqgtPMyyliLbp1b4rSgIpvhXZgbyhm9E7cjL1mBI"
    b"YYa4uQ/l/4IlOSlkIQcJ2kYEostr+AMUD2YpihFzRZIKqLG+JtbqtVEcwJPB0336HEYHsgh8BjQM"
    b"mFqMPyG8EsBb0QpW3JKICKTpaQS0J/lXxAKersdPumzI/fXwCZAaDmyFT6CmGCoKoZ4Aqhlq5EqQ"
    b"mkbtfZixDMmP1b06yGbH9qq7iy/FlSENShhbKXEEqACkw4FIm3JkERA8wAfANCAlJ5GaOAANoNQx"
    b"LBPXwVfge6wehH2RYskbqxgImaMwFU1gdfHw1v7GbWYDEYHMhlUlpRqkoLKfLbCkjqB5rp+AjJTV"
    b"NJmGJnciOYEA+SfCfSLWtqFTt5R4DOjHYBIAD1icmZRNmTKK7RSc/S6VWXFEYxPq2KM6CpLdjHtI"
    b"tcf02V7kdJH/tre8Zy47tEG9EzlxRngfwfSYNSZRwrkFjh+5T59HrfTNBv68gUJuCi02Gg7w9SfJ"
    b"v7BzCU/oSU/ZvhM9iVzkfDRR6a8kM0QUO+5ELmD0vrMeuVLO7QjeHfppWhMzgGEWdms722f7LfX8"
    b"ff/0uPW19a31vWWxcUcK8rMMFnXzK7+NkE7QyzceYxPy5TvmwCory5KY5eaq/t2L08/7jjtTvT+N"
    b"dEYPkGK7h1TNkTx8du9FbIoyS7E+aeGBiEJ/27vCQ94pgLslMFOuXdXONAMyAzWFQvEAW+56QOiC"
    b"to5gLlC+0Fwl5tnlxhUsrgxJsE8cehP5QZo5IdsAFCUm4HNSR5wY/m7N5/jnmSvX8YQfAkq4LUqD"
    b"IhMgBesTFyUa2fsum1Dv1SCxqqTRwOLPoXhRilqEJfETsADKQwXttAkTCfraZ5zuMJs6tNqRfI5x"
    b"NXi0VOOo1p0kt7j0LQAdiHsEjxZGmgXQdnF23RxIdu2+mCma4CxWU+Q276nA9OEC01z8mvjDVE/n"
    b"VwD7Ny9h370UphQKM0jyISmGpBAk0wyRqssRoUMguPDgP0ldoH37ToIpQ3iIIUVjAzLbSaMRwJ9h"
    b"HqYbla6o1neFm0ei72eiyJcQlcjMYDYkJmskdvMgBvQQlfr8IFCoTE//3qA2kJJvIyGHpyH+9PBn"
    b"BEOaPHkG62dA4/Zd1qHhxi47h4cUx32MWWuwrO4QJGux28KU4yd3MmWw1pFljtdVSrSWSq6zSx+E"
    b"BmKYefdkF/gufXcui9+tq5RkTYE7hm8oZfdJIFM6WJhS1iGlBw9dbB+zRk/OZUqw1lOF13sypYMp"
    b"OG3Bk54c2WBtIB86+HBO9ahujLDCjm4Lswbr55Uyd5iFoOpgYax5iPUMqKuqP8e6z8G6yjp+0pH9"
    b"2X2iOtbDryQWBGzIerAyQL4CHSmz1oSZdZrEpkYiNx+Bqh+Oh1Okinxlw0Xrxgqs/ozIkpb8dgUS"
    b"hlFMpJIYsmtVTPKthaY7wBY0RcdPmuOW5A27oPnxHWFJrvR5hjzC535T4yrLJMPIgGG0gUlQz33X"
    b"i4iGpOrVoEJiRnERpX5PVMdtjXFl082Lda3QPgMcjwDHE4n21eHsmuEAGd9AOr4R5VgosSEBeRlk"
    b"QY6U0ScxMH1gcgVvS2C9r+AXxNy0iFXwN6hh38mQTEw9XECwOvMqSVTMRLbEK2RKNxXTQpW8TLJU"
    b"6OgOUsI2fvE4Wc1ixW4IG8q8i5Co0iOrfZjcMTCwQjlrXwhnHCMXTV0PnkGeeA7PbIz6CzZVJtxH"
    b"kaNGpDkeQIDtCOIaHWAbMRvGyC7YrkmD+QC5BjC11QFNHJg/4hc8Iu8HfCMpoR8X8tqOqKADIZOV"
    b"GGGiuzBMtkf67W7m1Dfu62vOEcp58zlqrjCirGhgD0Stgr2SIMimMd+KnjzZevESuLWsJ3JAk9Wi"
    b"2xRI5E+UpQaxJWJBTaj2kuSYii4AqXYjpvUC7+HzTEp1rK7QqFYUJHUD9SlL5VBSE4j1Zwfb69Cf"
    b"OruL+Www8rtnAx/et9Np1PV8/NUqghT57yIH5bX6wdH2bh0m2r/zQ0hvhqNxnGQgfDj1xL+rM8Fm"
    b"aCYBNoJitidfOhHM48omu6yjFah+ZUYAqpOuCHNgxaCUD2J90SOtXqfV/tUAUuZ77F5TitdOJ2II"
    b"y9T+XA78RIIXli5OglZv24eZcwQikRABaPqMTA1Mq+KvVc58rlPebG5sPS9U4sKY8vzVOmZ16raW"
    b"1pJzue/sUbV/ifXNYoHAOshQUM7ZDfUsM+A+Qbqpis3knFaEPQ9XWi7HdV0V4lEAcuo77082nj3f"
    b"eAqaDlDtN5mt8m8AhO4BD/zJfZ0dwEMUgwpSZ+/hEYoNcazwekyYDQq4hQonEYjmBNw6u8ZlYMZj"
    b"51ygKBvJT2GAO3ZFN6YczaeuRipM0ZL8UmUuu86sZTIgk1rESyubqGkCZAtEmehRmuVzYJQpUEYv"
    b"zEB6ArrJiTxp4AcgAo3vvRgw+J6ahWJ7UuP/FBnbxH3mHGfOe+oiZv2MuFxERb5E1B271AXN2zXq"
    b"Uc3xPbuN+U3sXAB9+2VpmESDxziaAEdznVmYMfIktups5mMCmmmRcn60FbZ7bKWVKa0DtStYcLWe"
    b"Hw5BWajd1MK09lskcV3pF0j0SYmA9hBNzSTPEsy6gaycrUb2xsgFkiMoCwASa6Di4Ux9AHQypElb"
    b"gGvjJA4mXVBsWUeTZg6LEHqtxzuC8UAfUobg9wH6/FekIAL6C4D6PmIxCqPQnv9fSCldFLMh4yBi"
    b"oF6gdQd7GkBPhzn/GDkTlJY+RSAjUeaIr0bOkAWsx3yDv18iZwTqVwqE/YvzAZoa5ews5oYc/pvd"
    b"NDO+vLMm+9Euy1I/H++4LPR2SffPja2nZGhQZou2kGsucz2ys/8uTehMSjLEhH4iE9ITWMdlg8oo"
    b"U8S5PgKl00cOA8tHYSCrG1oFSJUlU2WShPETMECTJNVIMfIQYACkcJHxBgi2SUldQ3E5RRue1FmB"
    b"Dw6VvYPIbU9mSvUSc3vK9kG5I45SCXwCVVsgPAc5xRmhkP1GST0dIB/nOe/HzgSAjdRh4LqL4taK"
    b"swIU5ByA3gHpbujmbt71s+5ASTUrm7BQvljr+bfCECAfLnsb2dhl5/6E3IOsupUFfL0vImBquLt2"
    b"YnjBRUT7K14nBiAkYW/qfZEpkl+e6WT5+hZ3evyMv2KnIJi8eMneRfzIzwbNrgiHzmn81M/ctU22"
    b"l/GtJ08cP1vfdNl2TAZemkPBL6+AoeyAaMIzy/Sz0Upev4taydqaO4Mc4KHjSTpAgdCYYPlmK329"
    b"l7VSKBMhZSb10yqZQaJWA6zdhbOInZuNBMWHMqPGmN1PtHfmbN+Wos6i+dw5i/h27JCxCnSQBLue"
    b"4uD8DBA5BZwFuS7FYYb4BMM3PQZ1t9XFUXVxVNIG8onMuY5ogPoqQFMJ2eTNXobmkHXuM7GGSgGh"
    b"WsC7T/YyQFZYrTxYIxj7nRQW9vomLOTuv7bQSAooN3m90ZogaTbazjmu5exyeOWC2qMABWkDSOtB"
    b"mgHNiqHnmszeRX6vTjt5oJgjmUYRYdYbxnHifcrYKIy8oxiQI/J2gV5hn9hfvK438evsTGg46z2c"
    b"JtriHbUX0Bz5Y5yy45jXNza3nj1/8fKPV39u+zud3e5esC/e9t71Dwbvww8/P94cDo9Gn6Lj+GT8"
    b"16/T5Cw9zy4mn2+/3H29/zb9/rvOuiQLnyF9QeQ6ji8/gSiGUErIwO64T15uuVftdr3uNnHf2IEH"
    b"9p13hbO1AaRGcG1+BYGl2QmjwFEJwFszrizAd5Ae372uT+psJqIsCUXqBYKhjLSvXn9lDFZW6gnB"
    b"aHc89aYiV2uPfZaYn7NhBrIRdCwMAOtAVMLOOzgD0WQ4bDS6Q+En5+FIgNxNIgmkgpCgt8VIHnR+"
    b"rM7+yr3a6kzkP4DYiKXUmYri1qIiq23z5OktA272kaBcW3hfHdFuw7QMH6kRin1yBoLyXbYTE+k9"
    b"F/fZftQFqTBhe0XSnpBJPZqinbgpqAyOa0JJe3EzEDrpjpLQCo583XEkLcvWoge2/Lbklh/O5mGx"
    b"wSPUHP8HJseV1X6Jha5g7Roy5PNdkJJhWT7ZFM8NJ1wHFPJB4Exh0aitHdqPSNVWhM+hQAKYla6v"
    b"I7eKLtOrFv7Ak3/F8IfHebEb1MuKzRzQDOUoh/50N456Yb/dnCTDFChM0j5E14wAZr7pj8fvA1i3"
    b"mdtMgUCDksoqHyGcogDmZtpuA53/yj+cHX9qygkFMs1GBM8ZMk3VEyow9pMU4a0YjNz5/uT8kFJc"
    b"LYtrVIIKaxwD7hPIISi61Tza/np9tv12//r9p/P9d/unNKZ0PAQOh+tMz6GUAaK1pKw2sA33X7Am"
    b"Iv4M/rHrmL8Uz9n7jMP6+C5oJbCfmfz7S8jJ+i4AQN+lyq7Wp4PDg3IiR+oSwfKdSsch/a2qK0fd"
    b"4aOq52fWbjr4npWlY2A9M5xw0DB9/IllFSE+A/0GGeNzK4Fx+cG01IchfzMBhq1INbx2lXtPOJ8P"
    b"YVl3lZbXwlqVZIHffxEd6dOCEnWvCYrTME5VH+XXvvXlhpI6umgy+i5cAIcUurB8ACKHZl85lhvw"
    b"99mlAJLHP0etmKci0xRFF2dlAjlwGX3Bj2Jn8GQLZgQghJ1SFIOPYCE6ahGOmkC6fFj8STOlEfAe"
    b"PAIK8x7+wnfX18l4fDZJxyIK1Ihg8gCUG6yLe8uG2jklche7CuqunIICKjQVvSa9oMFRt3FKjj2q"
    b"CahOzhY0EahScRRDJ4rlPuJpK8V+TNCgJMf8OdKTPWo0IokdMDTs+wg9veSkA83JUN3fbDR6lAlQ"
    b"BLaoVlaAhg2pR6/aeiWgVKSm27858sew/mOVGQJtAfkLRk0eG6GrV2KdVnmtE8c3N0KMAeQ1wLQU"
    b"/yaiH8IC93EfsgYUqSaLdoch8KS6EWFCRGQz5hh7EfIufxNfdhEpZrrb6MWGkl/I4IHcozwoFQJl"
    b"65LVzOdOzELcws4u4ysQUeS2d4iKSFjoctQpkXiqsNqsxU/MzgRgM+bSrACTPAaZgqVdmBvUNwEK"
    b"tnvXr8wJUFls9oZ+BjBznEv49KqoGXUfU3P7EnK7V1fe5VVOnf4rMovoQjm/SKqx3YmTDIhnlsTD"
    b"oUgMsQ+C/VsA3yEOIgKRrB5HQ5DN60Ay2IzUlaEnmvIBZd7F8r2e/ODX0g8coo0+tl6Io58lsnwA"
    b"aWB7/2z93e5Rnd3TTB2Q4NnJYl8tODLE7CryiXwBDYyIrpaZZsFlBvXm97YI62dxxyksyZUP9Pae"
    b"lMwU2S7ZekATb3bItyln14Lb1r1KXVKPLLlpaKsaCExkBnDZuaoCDXD3sSRW1nhkHdfCIRvjZh2N"
    b"cVJoxG4ZeeDZS9eW6ap6ULkPVSvjI/2UFkdj38yx2z+QFXroKOWhF9UPGIQs9iFTdkmQbrCyOquD"
    b"UENPV8CWoxKs7kRlbGTnkgKdaQDr/hbx+iqMO+FQH8sSvsSeqvpe9SWpzAcITcW0S2iJxF37Fq0d"
    b"xEsnS43D0cNj4a0HQowsaqYQKNtipy4Bc65wa5gkgW+FlXIiluOFWNJUuftAkWVt0GlCASmBuO32"
    b"5ZVb9Oo9qN4k47vKQP1V8Bd/oHjxKeabr0C++Al66gZLErnbPxv5N+IY8bk1juMhaKP0VwREK85E"
    b"BhzXT9UrUCEYSHcKhDbqmwLIvKLJGNlXQgyk5Xez8FYgo7d9BYTyEzAtgsSCe8Vhuk3lq/uqlJjf"
    b"+cloMnbUt6qPzLyIoEnMExgP6D4/Y1ZuAqhnnOz73QEKSfIjVI7RYGg1gpyQXktDARr/PgKCDlqM"
    b"lKeKHpgnVOcy1F+RtoXpHrDItmN3LhCADiTXg8DrrWzAVH0FoVP1YqY/ms/tjwZ+SjsilCbhb9KK"
    b"2vVQSsCgHRiY+3QQ9lCmUmQPppUkd03gXotGo6hIGeM3lFgfWeOT9UjeHLkdkAFuWkvGh54e2u6Q"
    b"G39CwLBwdEj9L7piD6ov5T7U998b1xGVZyCHFSLO4TNtqToVqBmUVEByqRj5myoXZygyijOhHeIh"
    b"BUEfAI1L4qmxeeRYuYUWS8tUWpTwBp0EsOUAqA9w1NSZqZa9z4xkNfgrUGn0PqOfOLnfI3I6gA7K"
    b"ZigZ9UoGI2qiWrqCrvBYpo6bJXq0/6xzCi1AGyDVxpGM15QtKwmV4VhAR6j/r8wfs9qQVVMJQw/K"
    b"rZTqQDELPZxLgvvsH7WSA8GDproD0b0hIwIxQ6XiUFm9REBIJDVg5N+jdrmeaCEAHa4ajUQCFFRm"
    b"IDBplb5IjcdXHCAmRclV6qYU09SmHAq4Zi/XKYaA4v5sLEBujBnNuNdlBBHPTI8NICit5sWzp69U"
    b"Ine9So251HJBnp3pDflKpUvWNOohBdowEM21qOiUgYCZG65yHu8W2kAsnIRYFcj6PrrLkvMQfZIS"
    b"syzRe2umkBy7uWl6ViLVm4ukWmtQhlwvlHCX0HepYlmkvOAU9nJhf8t4bHzUlWhh4D2hZlFdXi5e"
    b"qqJYho92pSimvlY7l78z/glNl904gSJZbQzs/S5OAtKQ4luRDEFoJvUpjke4u5AsqP4wUVWBLLYE"
    b"MiXxSZp1RyvH4D3TCv+K0Ao7vHTligvQzAhSaksuhtiZXV9nykp6Pb7z7G3SrhfkcuMM9WvcvpEf"
    b"hYoLDc3ZoOGKdV5o2CxViQQ0EekY5A9RnCYaNgeW07hE2N+ZMkfIZhInoHaoKO8VhQrDguzYpNqx"
    b"iWlmYndsstixYrTFJ83usp49BC8zNDbwdL+hCtwwMfroJAKlEr0YkQPBzIr5PG7L+cINogkLcMbk"
    b"16kjE5QcGYP6r8vkets/Zxe2JkXGz/okuoniu6hG/K1QvUH0ReNk+iXMBuglHAXpAMhFrY6bwz+K"
    b"d71nSuI+qOuAkrM4OgHidaDLeILFkXkj46uXMVOF4gxHqRcxtEeYkns4SUk57RRNGACVOCKR08+E"
    b"58PLW+gFnqaJc9dYJUAF7XIHfcCMzSS8HF61Vkbzea/RGDWRwiKGzOejphZhgUWPQHkKDuOuPzSt"
    b"nsBC1Dmnoiug4CnJI9QdEOmKClASHTVLg0v4e6eaBPMEXZN9QBVkQj1lI93XgewrYuVgPh+YvuqV"
    b"iWU6/CJ2RkC2Ya6HrAP0gOr45HSwxuChsT80cOeBgeOIUtBL2VDLIwP+ZqKa0tZWnCSkTAVioLEp"
    b"jESaIm4Aqg0KVMPChDi0e4paosu61NsC+UEsQyTy9CCw+1wyxR7TnfaAlyzts8pYnCvMKM+ERyaI"
    b"sey/Vcl0GPtB6gHHMOW/wMoCzocWGsAtJN2lLlpwHgFD+0dYgJOxvGUlw/ASOqkekCKJpvRCO4I5"
    b"GQBjQZLlAByZFAFq2BtAhq4fKVi8TeLRQ71We7Qrjux+gRo4MYzowbLPEElLeKWRdAECFTnQIFGB"
    b"NRlkB3Q0xO/BSGvIr0Yp2hHULuJAMaxjdlcQvwReh5CQsw7ZzGy7ti4p3WZNh3fn892iw7M7Bzgv"
    b"vtaCMFXCP3QkmCQlrK6X7dOHfPfh+bMUr0N3dgw/+tPdxQklCXWmzk14x0zOpHfK39w5p8gU0F/2"
    b"++thq3rEQtDiH7AOO9c+Q9I2TstJLdhjDWsQrI9ZvUq9ydaAUikiSJn8LlKlnkWVNIaUqdKocCbT"
    b"EoCnHthIZD49ojcGHyzB7AJq5+7s3IyzY6A3eBjkBMXOkrHItT9Uw+gpYggEsGcTwN5y+k7mfmeI"
    b"GpWU037FfPOFeMY+xhz/+Amvw2rsgwoiEF3QF1+AhEDC0GpMmYUmW8r9JrSWyD5AQT9K7/D5d8yf"
    b"2sejnoYsTPSm4njow9J/WnP+82ztP5tDpH0uvARrLp7yqQ3iNHvaZ/Xa5tYfzQ34b7O2umVyQGr8"
    b"QhtGoN+E3ZuheN8VwIyTrCt344AHw/OJOnIG3BdBrrJSdp2BJHsdR8Pp9SiI0gOo8C0IQh08hxof"
    b"xvEYnzw/Lyz2sBLRnHV6votEZ9dAwXVmAJUzEPaRoH6JUdUHXHVSsoahSxi6ZSgmDjR4gj8BnQ4F"
    b"Ck6CfA9/Rvg6wJ+O3Po4l3+OMemOiME5EF7ycSfV8xjm+Rhn9A6E9lDuxOBWCSDNIe8jo1EG77Z+"
    b"cPqu15Wo1YdSp1QKR3fCdZGWfuDXkHcC9V27rA8/0Htjm2k0ukvoNnxgWsTP4JMjbMFvhwm23Ge/"
    b"ZLdgzflG2ATNQW+9L56h7LdU76CColzhlwjL00pv970ZgLvPTIp3AuztDFt16LCs15dYZhlf2mTj"
    b"aLe/gW4fjL0jZ1kRyCFDJkzkarGL0+fxojGHCusO9tt9UDqRbj31OYBrfdJL/L7nXP7Xf6ZXa+5T"
    b"t9283Lxqt3GiiXvn7C3V7zxUc1vX918j/rQ/kiZXfRDowsB3yeeu9ltSMH0rSZOZBqj86BDEnPdR"
    b"IO5BMZCHG+uNxglOeCX/DT8p13fNVy3PqWv8YJKKBG3Ib2HIIxFly9JgESBqfVA7D/3y5rhSANCw"
    b"BYt7V88qIBOo5cqMcEJmhJMlbha/4yYucudEO1m4JrrDg6MtBiXVHsSfTG+tuA8DF3U+JeVwvmEz"
    b"kT4fFmuFnWjrJ8EMqWJf2hEvcMHMTuTivHbRWJ2F0UTkEgYfIG0+N9n5ibUWh8YodAKg3LZAiftt"
    b"ACx3pivpu9hRRQAM+y8owpgQqI8uN34yxfOqQMnR5C+3meqsrzacRLA9iidRdhjfnQ+AsQ3iYcBf"
    b"vnjx7AUUKfaoT9RKueYntEMN1AX/tOUfGIg3MUOiD83WcKgtpkjRKEtuO+/SM2l4oJ5JS+ZJTh/Q"
    b"C8oQwjlhdWyghswpEkOtEUIjUws8ch3QLgEinQSSkUqQNV3a4te1+uS3pAD9JszpO80p9V50HZVc"
    b"lFdh4QApQUS5FeXNST9hv112jYS6RUbbZdm/yTxTbf7Eljuv2S+0r4FQrIyos/ewGrTF+4wm9MZC"
    b"XYmNQfvMiV2lqE8tS+AhLqt+3hJtpwOErQtaT0aS064EokMgBa47Rq3Mi2EaMEGBGCZDPXl9Ypod"
    b"3oeS0AdaBbeqH31lkgTMjC2bOEGPrBE4ySDFWURghCyuj+cWFXPR0F4hXymMkwKwXpapKsPM5VQf"
    b"5uubaDQ0mQHYHlbKKbZRx/1plAjqaDOTNASpACkSQJrK0SnsHLSUPVZ/v61zJcClERMlilNZBwV0"
    b"UWYPXdWN41rUr4L4hdOQrLFGY69J2cwtkAXlDZACcR4j0Y+zkFwYIiECERRYc+vAhDEshKKfpsA4"
    b"24bHyvlGIobbAn2b+J3wXwWDyWL0X7JB1daJjuvZFRYsHXnyURh4kmCHASvRba9Cx1mVvXiLHCd3"
    b"W4dqVocZsfyyjxYuIYW0B8ZrYQFXcaUrjWM+X5qrkA9zAXK7j36+vIBeC7Pd0q7Q8ta0nvdgd1QS"
    b"CFePtFiq5aEykr49WgbN5yTHgTb6t3231dRHKi0VA30KpN/zqho+UzLz/2JDjcYu+abFhb4sF81S"
    b"PYgfsHiRpK/G7EAuIjy/eWOJ3X1EPOGP0ssNUkalNLMSNqlgowFPsoA76ynNmnIAsekvk7nIAg2Y"
    b"ZQ7QA13mBNUDWRBST9AjB/sieZNMxy5ZZXS3pKHiIxdtmxNB2VMHWfuJTUX7tHJcr6rWF17cjcav"
    b"iZiIo7CbxJmf3sgpWxktUm9uk/aVRfKNXzzMPTB3CVGDcZG/Lk6NU1/IRtqIEYmIaAYecD7RjGLU"
    b"razwVOSfr8WKwkmgkzPpPYB7o0XyY4SBviBq7y2wRmH0n/Ytbsx6jzKwtmLpyMy9jzmTAo7R+LDC"
    b"vi5t+Tm7Zl/whFteqERS3daJkZVPikhomlVuO79gsv8RD5KOq1JerlmNazmF9rmdTrvs0VdHORCn"
    b"vi91nhCkv0kgUqfu8yQbj/wxGnqK/ku1T+tvOAA6yNsvgERgGOGif0SIWBm4Nvj1jgfIgf9YOKCC"
    b"p1X1AGAEYpoYAigsYWBZsfLJn4xOsj0iPtgSgT3gD7E7G6CPaiHYPtgkK9oywsGAhIN/MsHk/KYn"
    b"WMK2Tk5/aBonwxuQC5hf8s/sozWXdhBpxxi5A4M85UQKwNNPhTGEqK/l0OAp4qm9+k7QwnKd835L"
    b"HanxUzpyGrJrJHsoojYaE0tdmiwxXfxG6keaSdP5DRIbYP8pQsZRxHQ+N3QYfU2LynpLKtMk+rch"
    b"zkJKSIYw/2YnokyT0UUilzvkin56H9Gt8UzWAGPuo4MDhki7SZ2iLaDCxG8oAyamjz7ARNeLL8kb"
    b"7QzAj1vdrvYSgi9PNJcp120Wm8p3K83J+lWLLnlf0ovn9IHVlDqECcwq7xWcb6FXgB6g4lzLNtGw"
    b"Q0So2hwaRMlsWGpSKZnL6oSp/W3XCavkWpPX66ZdGXHGnH2J6UzCmXCeMbVz/iPNcAMTflZn2Xxe"
    b"r+fNYbMfx/0hOvaMvM0/n21s/XBZ3ZRDRJ4EvaGfyBLPnv/xqn5FDgh4uGSGpws8QAsZMeitHQ3z"
    b"RIe7PAbt3fjcuexthiH63sV8g72jx27Cnz1nn+H5BZvA70t2L/jmyydbT55sbqxPMiYyvvXiBfsc"
    b"K818iGGrlPruk/o+jO/qrJcoplRnATxKXZn9FfNN8Zx9X4yvZ8XUay84uVZdBYUyGDB4mJJ6A2tZ"
    b"vRxK1xb2VZ4J4X/F6hiG5gQrmhOg41HZ8PCai0dMEe2FvYVl/EV2Vks1kfE8AKqTSjnSRxftWYLn"
    b"QFALFUv1+WGCztfL83oJCx/KCyjvvZOCnk/e3UyexfOR5bNQP28SzopFqVK3u5ChG13IkC2mVamZ"
    b"GmGZ7OcC7N2Z7ITi1//eRIDEgKMBxjhBew2iN+7YCaae3geply3b04sYGeDe98hFnOIeFSdXZ+gH"
    b"P0N4kRu92R5nM0W7TuS2ikc6LuSjRXXYls7MYSoxc+i2h97l8MrL8KyG8WxX50RrHY4bvSPDkDvt"
    b"yypS9aBAx3WvPAddS2MgBnd+EumjYBEIP7gLdxdmgxpo76uzQV7rAYACoBToJ1uc9vZvBLkLAT/b"
    b"VmFQYTSy32p70le7fSn8bTRG0pXljuNrMyZOTvFN7ojPnscKALjHsNIrp83nd021qfRlAFy8XHRJ"
    b"jjkF8cOnzlEEtlp9dTbM6yjSYaCRDsp4KuDfDwOzEUl3w+IYhV2Bn/QnqJDjCfVE/JqECcrgame0"
    b"h+d4cUADi1K8eZst74tU3nWXHIC09VXecWvivgsyflrD1NowHIG4A6XeZrnbrB1QtJTuII5ROqsB"
    b"2ia4XYs2g+YPV20Ezkog9BaAypbAzXsAnrhdWKGSMLDWOXkYDmSLx3joVkVhJHeBONpVirf3mcUY"
    b"A7mPAcHgBb46LjLvAGMkUpg0fteydox3dYTSRsOxdtbZriW/jOUupHfIxrRGvdNit/MIkfLOOWSn"
    b"7Ig2W6l90x+rfZ3G76QwqPScO7bL5NdIWp0jOeBf5lQnzvovpNGwUiRC1RcQSBp3DepZJamyM/5r"
    b"pThIyVb5nc2/doZxh73lq7AQHmBrlZy3MbvghyaaK/vA37a/x86qMt3dNf3iU8f17lwP0Pes/dW5"
    b"wxfcP7hoQ8pX5xAP/dIxEetc9gcLV5/eC3fNuWhvehvufL7JxhzEkG3mTNmNJgW3HAWZ7fVNdgAL"
    b"1rloNG5oy4F9rCLVJFtzDtqZaFsNtNsb3m3bbnL9Xjxxtteh0S1vE/p3b8X9+EgoeQ5108Pl8Zs3"
    b"r9hxQ2RXIIKYVHVs+tadq6cD9/XrTf3yFl629MsZvDy7AsnFfCwPvSFVdJybtU336fYTkblXINbo"
    b"IhdtGkRF1PA+FMF4nJv1TffJvWA38OPaOZjAqF7MASkJKi2Cah/z47XNxueYGT2v6+xK9dmCuLFr"
    b"3+b8BoAuA4+2Dl5vt9wCfz/y8eWB9Cf4qFzT4fm20bitcMc3t4+wS1cJsrJDX2MAKgWkglbYyrWs"
    b"N5d2fAFd7JSJkHT9AwKPxPxG9eKmqRUx56PLDtbWlGH24+Xn7KrdFlnrFBWQpyCVTdkhKm5VJlpp"
    b"BYRWYF/AfCXX8TrAjIlE0RqntY9PQKSO1NlmlWaRKZuCFbk6CfowIG3P+G0UfLCC4z0M7DARzqiY"
    b"83cxIqerRfvt4dCp/+dGnQ4ld4BhDuQsYbCNlRVQPtU4lnI+25Z9zp3R5TuE2QZg8as5vD17Rm/s"
    b"mI8uuwk+szt4JMBusF1u9QpR7xAX7HEDZK1T+bTlsiP59Nxlv+TTK7cVA0ToTCDDJ+iwPCAoKZtK"
    b"ujyn1O5gEt2QGxcO6rR91kRCzUfCAaDswnI+a8oi0ni4S+p2AXznDud9yORngGOH9ohXq9A2lemz"
    b"xBfsAwaIWbMJCtsAAvJASWeVlvQHduGy8ld4/lh7ehVDpG685UftVe9XWw5qFQZFf3DAHXfWsTid"
    b"87YYi5ZXnVACELfJpQFVc7e3mrsN0YSgIFf4++TezDA9mZmjjl44y6EPjtVj7VLzLeYvNjbYqqgc"
    b"dP9UxPepRc0b0E25YJEMPk46iS8l3Xq7TjIv7WLXPVkCQ53/lZkoV+2mKqw446pwzOcMxXZ1HlWn"
    b"Qb9H0uvGmPWEbdZbKYvG1k45SLsFJ23PQHRvJggupa/KGxnQ+XZUd9uzEWSPAHB5LvmcSP9XGzXZ"
    b"ws4WkC2sRkeZhnxWTKcg1xBRyDFZzsb/pkqSV86lkxoySf5Has1fGRoNud9cVAIw0lCzIISg44yM"
    b"81p6ObpqDeioy6CZSQfMgTJtNhoDiR7KZIbvMmepGioRp87KH5nFiC1Jr94RG7iE8hiT2wiLlx12"
    b"TgeBz5tyOQHM0emyC4uTnWs/zoFLBq7A1OI3zULCs+8TSEckLu29MOlru+DLKJ38hjx26v9xbbzP"
    b"zeIaNg3rcbA50NEU3M65SNH9Dun/uU3pjgGg0FfJGZyV4/n8WI0GOOlAnuHqOlAChySMJOjOjvUA"
    b"sfPyETt+3iykqPzYKIx4PN1lpO9pPU+BAzWdRqMeA8L8mmAs6TCqDXDikE7I8wMy3YjC/0el1KRI"
    b"nMqw6xPQYfATr2a++D9ahxm0qbZ220R1AkUE3a6BfyWIT9CJYxrqsW6286DuN/o73e+4Kb/IpaI6"
    b"o151mEwseSqruSIHZZWkoEBJsV5ERmIYIAurJEofqhx947bZGIPctJUMtw1/R5kzU8T+Bta9a4L7"
    b"H/JtNEMv1se30T8O62JTjT43/E7SbWs+2qPEmUqpvrWkGhCttu3Wxzm7ad80R97UlVsU5zY3PkUJ"
    b"BSo3Ubeo2W1OA1ZgkgMFzcC4I23bmHzDt6EfFcguNVJrNnir2eBBQRw/Eqlb2MkrnHJvnFt7WAc5"
    b"++gaH90+f6MNIqIIjqMQtSYpWiJ9crwfaLLOyTFnZimJN+xWmT+kKHwu9w8guZn5CVBZeNC9ZbvO"
    b"rQVFK8eFZ0n5XLlBVxAGs0e3TRqslXPjzrZB0B875pvKnBbfLplwXVv1G6j1EH6KA2nnNpWCcbGD"
    b"Yj5nizNIosuBJZ7o6bvR03cLLHAxsZjTg7zk8P0REOWRCf4IfbIm+DaH/v1PJpjdKXrApwyJDb9D"
    b"CLMp9eWIqyVNa0ph+C9amu+dbcXfCL3H3IBG04hmiK4fxz1n222N36xvNhqLRRT+j9mmi/6g1rKW"
    b"eCWVcgaSxpgJb4C6lV7hxrEckXRVU5fZL2iOPQK/MfRbzQbTQNxWPAVFmW2DpA+InEWBnKmtrm3c"
    b"TlahMkwsC9Wm3PSdShSaFld8WBFM5HD07EhUEEHJeCIXmwLKlJkOA2C2m6qG90FenOeFBs8cU8wq"
    b"A+AtH+4tdV5F3nC1u+vsaOms0aQVNAvwYRXgf4TfXahJlGo6jPnIna0WRG1bL4AxAnv6AIynuJuk"
    b"OgxrpuigtyQ4CcvMGZsc+mCvJaBV//cbrrq6/HJukb4tQpWdAaLfsIUZn0T+LeAy7XUDBL/FwIEW"
    b"gU6E5rbwydUIj5YQSXq9aUFUbmxN/lYj6gF1WZ6E+5jzMTK6vzLnABRMXFoYiLnQW8oi348orsnT"
    b"tVXr+TRX1ti+jhN3Uor65Fyz35pTnwiuF92U6aMo1/ooym9rKnGWDsqzpAeRY1wciZ5d3Ln+7fyt"
    b"mgUQPQDZ90SUZGl+I9jB4m6MFrwhd4ZBesnTz2XpZf+K45axWmLXdMocoXWdu9Z+vmKJ27gGrAEk"
    b"Xh/GAL9shLIO8EZYIkC8lZc21q5Z0HWj8dHIstDta0lpF5yqaPTXtqSrprdeIJk57UReth+N1+OJ"
    b"8iG4dtUgZGXSrXqmvvY+6OVw5EdTz8Y7xJuxZuKFoW6sxICUtlQL4qddQm6s+Uf3rEnq1XuTIZ4E"
    b"wbmTV+Vpr2gg/AazAR3Gf0eaxxZppvIG28sfFIvAKqI+sczjpW+s5WQXUl+poxnL0FVn5sWx29qY"
    b"mGo6GaIXNWDBjZqMG1eZkocg7ixyOrJcGklXI/d8viIT1dq9VT6SRUmNFe1F2Ous3CuKlxb+km9K"
    b"+bm3WKDQt6Socbt84EB2YC3jyUwtztFwCzHuqBDaZA5IYEd8m7393xUBt1EE3H5IBKxoGqRWtG4a"
    b"jQvKAZUB/k9KglQmtCT1Fk/ti5wt2UiMbVNqaFmvAmWu6v937UI3tg0G49JDUslIk9oFpKsLTB+k"
    b"o62mVDKzS5KvBhXMdMEHjE16PZZtTtOkHHKdYpzYtrf53Ik0C6FYKSqaf5Sz75kdDdcOEpeV3iId"
    b"gghvdFNPqXnyrQBFtMGLXik0fozsNsXoQ0w73KiUjNxkBG6SSBct5b5TRDOQcd4wnBvrYiAQfOvC"
    b"Wy7v46x8gydHVSi7dtsJ2wm9hIUjebk15UxDjenD+AiDIVe+TKH2ZermrVT1BOjxpNHw6W2Cb4Hu"
    b"VwBdtvpV1A71pna3/Gq3CD/lV9JDLDJhKRLzlJonvwg7kbMBmvPw6CX6kIviZDXdY3o28BMRHIkg"
    b"9B8x5n1H8Snm6ti/gidhlUyRI5EiYMjlvSzyTCkM2sU7sOBP2wqyQA2ic+Pi3JLDgloCvWYYWGsA"
    b"Xw1I0Je16A3Qsx4LoE2XnB5UD6QR6d/pg/R4kh//bSd0iVG5xGhZN8+VjxtWHLCBighg+sk6llvD"
    b"OZ/dSOt7B396FX7r9QpaiZfgLDkuPXLO2bHLBs6dHW6icJxTV+fQoWFtOSCkM+sRgMWGhS0BOsnf"
    b"jJqmBsyepV4AQ80rrnVYN/YEo5Q7Eg1GTbsEfIvR0Ix7XIEuE6dX6o0mBdhar+jMiNFZeONOhw1i"
    b"b4bQG5aVO1W08UCfVBXuggvdP+jWcFm3Sr5zsmtWn4j3STgcCdzGUz2j0FJ4BNkyWvV4X4c6WSnF"
    b"hRjxCP10FpG5QvOg38CBoI+azVBdI3cWIopT3sgaQbE5lMitNrM51CtOXNO4/m92XQJO91yxPd3x"
    b"btFx5cU/UoNbOo704XGUeUNpKEFlKMllcNU259Z7jUYI5WUvhnazlbptPHqo8hFoHnblo0ajC1+M"
    b"dOXwZFVviSnFJhv2rtiVCK60bFYQR9vz3k7XEplVMnBn5TI8sOuTc7NQHSXbtelFNSuVgLqUdHWH"
    b"LpeiFydiEqF9oM6ylPwqTykSdP0/rukSl0wHMGQnMhB2lpXiLlGIe9pLcyBHxXmDpzT8rQLgLmiX"
    b"dwnUJSOdzrLMjk0mP5vPl20Gya9gAd/ogExsIQZOshgDJ10WA8fnWQpcGIOYIBuOC188O6zNDPnD"
    b"DLeGVEMf4jCyee6h8OFryXOH/DPrqcDA3EHzT9VZ4cby+BtXPP7GbnvsXY6vPAFqTzv0upbb363q"
    b"1QGHnMvbK68LP5r5HCz6/k0dtNj+c9+/24rvH5DQQVKIK44U/kfwF43B8Dilv24hxoz5m5WVLnR/"
    b"mTgDmSFkqV0Q3EYYW/uSqnZnSoNWVeh9SvgU4DGmrKXRVeTHKyu9dnMxm3IppEdn2RbmMSRbW5h3"
    b"qpTK3aU55MvildTdQhcakj12SZEWdslsI47R0GFc2saGVhDMOtWCEwTXko0RQIRbbeq4KaLPYHE2"
    b"sCuhMAuOMUFKhRrbJV5wO59PG43bFc6nNhlEny3sT2tX9uLWCmp30GgETQvnQYgaw3Kllk4l0h8R"
    b"cTgFSu+Uz/WOq8eYP0jrEDq9qKB/lqlsCmJ4YeOZsj//NId5pu5szKfmHEiAgZ2tzV4YLG323lj9"
    b"3oUa0MAcx6PaUPQyeZBq6KBbM51KGSuLwTh3HfRzOXdOBUw5HRB02Zl+j+X7qno3Z0nYW51ChBpT"
    b"LlQKcUZM+KAShgg4vCWj4q+5sdxBcyMn9zz57SBVB5z/jY+3zbfkOf1vfaypS4+nsFZB/k0WTEFl"
    b"uku68IK9qEqK86W0eEk8skxIR60lUcm2tQuXCU2mqMAMkZdPmUZUJNaEp7kVuswsikP1BID6Zds6"
    b"ZF1nGkVxr4CdLRZQy39yOb1q3RjRoV1stzA8IXlj/FnNUp1eYaCOJRV2IQukGvht65AoY+zd28Wy"
    b"g+aCDEs5gHyPFDZCoyr7YbHsISwXpVZpwoerRkVCxMCKovIRwbLXbi4La6TyARMXW1ryCU2vgz2r"
    b"QhmBgpTrhjwA0KI81oRryWKnbisFgOze+DkfM2hShTuDckC9xuVYtGSuAQp7jDBwtU3h1gJgSaqn"
    b"QtIA4cgN0ko5KX5NafdUbz7cmnlelQh2ixxKBb911ASM2QNMR5sSsZIlW5z0id7YhM7Jum7JrwPG"
    b"Tif2aeQ53lQDyviQRylZ0Y8cbdD/jJNsO4HcMSJb3hFDmqhuQRwrQRoXXOGF8eDuyFjvjkx5cXK1"
    b"fJiwtFkihQwl8hAvRO2BfSzsXyeUTMzsxGZhGMtDb7n23dY1bbmeaE56zTZdpqOTzOcW9wTxmpuw"
    b"YNTKR1zBdLWD3Jc5UWm3dBKrdaDjkgDx0JRirIF4gifiFJuWRxKXuwm5rADH+jS35FHsQqwFIfua"
    b"g66KuH8J6wOZHf61DvJeySNvWqFCAYbEzYFlNMBF+ZY6XbUZmOKzQdlWgI1I3btkM6DlbTUgMZ5S"
    b"gRDZLRQfVBownxT1lw0ApTZKWn25nUI9QrJfaEc2M7CVIyo1dmd2PtCIcaMhCMparJjidjk6xFgt"
    b"kAS02AQl223IclYjlMDHjymHg79TDqG6cplyfRXlcPC4cmhVJpXDsVYOOwnfZGcJ32K3ScVZtEeq"
    b"WlJ1wH22Flk+s2uZ7UBrbk2+3LjinYQll5tX3C7+5s2bVw08EJhcbpVzZCqZbiP2zFWPGSs3h9ep"
    b"sCT9Zz19Xv601Lkz1Tl1KABt39UeWX199khfn1Of4tQKBbtwIpGCXFkVvH6mj3+SyIy52CkOMHPV"
    b"+TJI2Sz8vDPoHLl5+/zZWmqO5bzmGxgh3arYl3G8zKlw4OcMf8/jGxGh03JW+IM/Y3hdj/YasDJ8"
    b"1/g9qLs9ctVF0CXOkkqTz0tjkTNiOqx6r5zUEw5zYjZBFnuflHo/Bkot6ObYh0bwnCWknp5QycxD"
    b"mKEtIs/ZeaInZGbFTsiYPkkR5VwYw24RP//RMCrZoyFYssdjqDxcwNQQVUMQ4KcyXMrSLArhcJpo"
    b"l+xz3NVRk4EBBYai3rIPj2TFkGVk/SUnLduoz0QpXRzk1YfApKCJbX05Rme6PR7TRUEwISdqerRo"
    b"helAoNCSIcqhzOkzeZnLLM8pSH412rkp0rzMrnKYUaJ7vrzkQO9V4vjw8wPhD7NBtZXyR20FAT0I"
    b"DDyw2OnFjiwbGV4HlbEi1v5DZTjPjAbwWME8R2Zmd0eH40dM3JWTjueNUZ4wuKlezVEaEGZp0zCX"
    b"+09Yw0wJyXp7yQ7vryHMUp4QlEmsSufztGhTy1iQBH3VcXatN9z4MqXxOHIE2k9q97PRUK/FZQzy"
    b"RoCpgIrwHkWM6em2imfa+zJvO1Na6DJRORYhpN4H0vxgDLHZFfMN+8bbs2Jl5UnSIg4li7VzEYKs"
    b"CAJsks8UNJdkyWAEJiPHsY/Q2tW0dghpK9BqQnXf2ieUYSlONQUrNg4FXgVtRewro46erlzfo2Uu"
    b"z1UMgkqZ9YZ3jao59Ul78ktT6NtT6NMEQZORucGgZa4DWIJIaCjI1ZVhdP+gJ7SHWUYPXsT09OFu"
    b"eWUqMWkRQp7Zva7Ax9NmaNNjaYkt4YJMkrrb8V2EwrOuj3S1ShpNm0c7q1jrUeolzKCxt7KZF4di"
    b"FnXFUF0rAXL9GOV+Wny0Ca60vWqBM6nVy31yo/I9CuHNXGt94T/R+kLr/oYHqsu10ir37ksdlEKh"
    b"3NZHtAbE4TGLc7rl1Fjc9wRG1sND7wrjIrNIAS/pILjh/CVki2xkm42T+H7qwSLBvwD1T+KOIC6p"
    b"wiyR8yksHk9za151LJKM6eVdQSjLZ1+vZitJrmJMCOR4PjPZo1mugx3MSgMDhVleapFMIkJLiUuD"
    b"cAzCnjDG2NI3sKRMfxuNqErMLq1s5BK+WeqPF2VRhQJyLnBzvZIKhKSoxwUpTZrgQdzSN2mk3YEI"
    b"JkPxXs+Lg3wDwxboUFORJNrqVUaYMpJKoWfoYiYrXx6MSpeT6csjU0U227BCUXXRb4SyzMVAXbPW"
    b"ikxlO8MsPetdHdm3gKE78xdIPan0XbNxGVX46m3iWBUwiophRwyKkaxbwYC65WBAE7SQBjnvVoIB"
    b"+YY94b0SE5jHIkU71U3UfPWG0MUdOaN/YbyylO6dLcXmUd220yybgOpUbQKr1iaT5OzSdeVRZqSy"
    b"AZ/oLbyN1kTv61U+ko4+E3KvUe0WhoYuKfOWgeFv2m7h2CfWbmDRAULu0ieqVBe7RO2WDBZdt+zd"
    b"gH1UjYO40LRYgRm38gKDacIpNtwG9/UCmvW0AIdR/FWAugnTRQyY7CYklNCXo10ASdJa7Ji3sHiW"
    b"hArq8Tc9EyqI5mlJTXnJ3GKDe3HECtqy2zbMy2MlyNtfPwB41Ql30YXjb2GPHCNwZw8005K+Xosf"
    b"TqxJ0zNRmbuWnhYtDgIUh9ZM4Q0Oi1OF/mJ5mRaVDE8S0hXfCZhEEiaMxOBLxsZD4AGSwwArLTEH"
    b"7lfpOOhBeOz2QZ6ZyfMUipxFtk5Qqhm0tuI24IJk8S5b5Ctd6EdLo8kSgVVjixWawy/JzjrA80Ri"
    b"xEIFZialgFkmuYt7nEFByC3Ci8vHfZQIGoki1LLERp4v4dWk2IkyMTF7iPIi05npdEYUr1gKYikR"
    b"StBXc5EIJWTiFSX8WmyptACpvYUFKJatjGqjEjepzXyRrYuqColhp4xoYILGzed4Z6CFfsJGPzur"
    b"6odv3XmnNBR5JTkq7kKdwblqoXlBoKVmWdO25Co/ZsIc8lnQO1RvjlJ5W5qUrRVWqAsQRXl1ucbp"
    b"tlgq5RIkvEbtKvs10mwuRzktA4/oc4ReCNHCl9ZVdpW2eNaUIi7go/QgWYLX8jLBmRFwyVKTqcCB"
    b"YokKi3H/yumLKyzCO3FVQEH0LYbpUIEEsyKQoFiq7S6mPxxiMNJbaDI6VmYiDCLqs6wIMIg+PXlJ"
    b"iaI1KicrTtE9Wt6qWVyXFpmYocYWiAzEGPzaYlG9RoIfWQKgt6SMvqXTKsYeMdgYFHcMolqfMqtD"
    b"pSNZiYWCmgxb30kDjNHnxUNU2e4lXrXQUgekIn24T1KIhW/T8rcsNZ1LCvwl/Ki8WzV7ySIPKHLz"
    b"isZL86ntEtWVurDcAJxZUYWka8oMVl15CuUSyRCt7iqEtlJ0qOJqIWwNqmYLRWl1FJApo70d7jjT"
    b"iB7h4UO1f5KmfOsZXifsp3xzC1gS/+MFvHV18teM16+vh6Lvd6fX13XWz9QVNeskaWDAHbzTYJjy"
    b"S311jbm3xgqUe8V6qTbzWockzP146shRhlFXirtJMnNUIitOVLQzSYZoD3Nmme7zIkby4jmMtnZ/"
    b"i4rIFqoQWg9MV4BywHsbf7TjdkA9HwK8Y+gd3tRdC6kVx6qhuHcFOAfVyPHSZnZkfAATljKf/Iqb"
    b"Wbwbjge0bSMlpZiSwxQ33hDb3Pl8xcdfUHTZVyfFuP3B2JWnvCepvN5kps/wIH+pK+VKaHMTvWpD"
    b"E72cBWM7Kwozo4qZ1G2aOtCnVzZlwqkY+lMZQ4DqIMxfmrgDODaM+yaVChETLkru34/DZFo2ismN"
    b"5qLjpaSLaEC28ulZCBQNLwWkkJLUSwDUQn0mp6hPJp3h9goMqlBeyNXnVIxlDBHIUivHXJGCdhoQ"
    b"jEY0/RjOFCbOXH+EhIxRmrksqd0s7jDC7CuJMCpQaUbulGVnygxvTwRkcWVJYHhP/wubSNve01Be"
    b"vBKhODk2G4Y/uvFkGNQwZIQaCQWIFnQ3msjVNWniniKpYzy/s72TFmSNkD21ZVD5Wjbws9o0niS1"
    b"84vTT7WUuly7OD1MazB2vPIgAGiF/hDeE7q6D6rrDEWtM6114mxA7aV1D2Pdw7gnUMaqKJUeFQWo"
    b"anFSM0CyYFTPf7BBZt1ZWlkBZrdKokJ5+6o0e3iL9kN5MuZoHOHG+b6Kv6zuPBmnaBFrylGA1C9N"
    b"w0qkUwbiiGkDnxKDctQcP5jAREQt2nySklGFSJwo97uNwjguVPtuAGzGRlWrkEnHQmZR4/aJtSAl"
    b"wuzgvbU+cNXiayqjPtZpRB9yNjaUb1ZpXW78OFaqtbBIul6WQeFRS9XIeEXNYsVRGFh5RzSblqe6"
    b"BCNqvJRi7RqV0ws3qkqObv1R+iEL6S59syFSJVpIxHHoS9KxbWsyIIUGUE7SkQ51Y/uFf4JoV8ty"
    b"3ocZ+CY3FnPWN8xSLAICDS8P7/Lq25dk2HJ9h+Pjl6eXeCnqo+x3NfKWGp3mDy31XsWTaqKBlMVu"
    b"9ETZ6GyEcuCS0CgBInUrcEbnKpVg8yEr2ZqmhcKKP1npEvOslxXOFxEzms/7qWOVwuVmXqzpKdIM"
    b"jnpZcYO5VYFr96AEDr1LqHsejEvvGvy4rsTDFE8tOlhzqZE+5OXV2QMreXn6Uu1ZSvq0UQ0c6hLU"
    b"ALkJWyHWaZk2AGgxBHRqEYdGY0DTLKXaYl2PMydlhDnErgC8yoGWgl10U/gZ6IuqK/ddR+1LkJdA"
    b"dLuEH3NHWEo3J0o9xS/0lILRX6Zy41Hbjlx9XOaBsrriGCv2XRX7X1v0YzpJuVsIfvyr0NBfWB8t"
    b"tRmqp7+1WGbpLPiLs+DP5351FnxdL8AfZsnxy3ikpsDHKfgtHN/gJTCWhyYA1GB2V8KrzF5OZiTm"
    b"EZB4IZa4vLrX+lDdbF98YgRYU2HuehqCFjUh3r9AYiqu/dBdOUnW+IoL6jcZLSfQmZPpWO7YuK66"
    b"TGYlLcK/WBc2DPEuEQxaiIVJHpJhc+W4fDWaOOdpyxok95kZDZ6e9lOXFSPmsX6xl3n22DLPHiBw"
    b"KZroWvKEkHT7sDpB+3cr2QKhy5biRqZwIyvhBiJH4SdKvsqEREtQxrI0l/am1be0JWVoma4J13+x"
    b"Y7bYfWfZyPXGWBksFQ4z4W8mIALKHQC5ux3qrWuQ9ncTPebKVC7BRzyKUYrPky3nda7pkZXjspMS"
    b"EWOS85F9AI2gfoa2eHlGifweY7T/kFHKttEs0gF1NegSUlAiyIY26Pl2Z/sI+sy+a8qvyCkrKKdY"
    b"jsyXMQuveHHFy7lwDumigDjOzuNx2D0Z+mGUiXsZHeAulcQGGrlSEfktid+ym/3bnTcJla5Wx+Q/"
    b"IOb5y8W8aqV0+Tms23JOUVGFUp/heHG0jEToKJ6AEEqnu25BuSLNYTH9KHWfNP+Uq7cLi7zlL2Iz"
    b"tjVBRwuSO0ta00MsQDHhkLClzBhC/TyfT8hguVK65Gg+P8JFMWEx8OoADQ9KN/pu1oSpwbo2NpDq"
    b"sXEWx3Br0mscJEypWiOMVvwqIfJLi1122KSSE4FpjmKnOzH7+mif5ApW73/bK5d1cZr9ZQTGIiLL"
    b"ZwUoywQ7dbOwtgHv4+LY5gfh2OsWrzMHtA+rWB5Wlqh1hKCLoY5DW0EMH1YQqXanC9PuNhrfXxsT"
    b"NeAPkPawRNrVJhvACIkV0mMtbKKW3Kr0kU9YWFH4wsc41hSXRAggmaC+7ISyuUBFYlxQSyd0fVsF"
    b"QcJFITJEig2CY4j1LrCmyYOsafJPedJErmPJMALFMEAkkdu+pGsNuZYxspjonr7bStlF8WqtJFeH"
    b"BGdFZ5faJuqgr8ZJggYeOhSIWHoXJ0HtbiCiWiBIVEEDj6r8nxovLOI+UbqLq/ti85WeGszjFL1V"
    b"IT5OBZ6KhY8WjTvhgnowQeqjtamRoUPKmNxojB4mTSPWA+JU3DpiiIGRPUZmI0bV13bKaLvBOuqd"
    b"D1yvU9yeyQcsBSrbMeQnpQ1GTT8oS5EQjnfOdHIm795dhsoG5Ej9JIAnWm0wobkGKc4Gqr85u10q"
    b"IxDjlwdVH8A5dS1nZNDNmtp4gfpkeFUOLKy4bUvysUVxk3bcrBiYuxyKl41YMujkhK9U6lr8GMBI"
    b"jrcSHO3UC9vtbrs9aakrUAODm9KtAur+mrWceIk+Vg7aUMRzCDRg0fOos4Qem2vpCZLxQ6tX72aU"
    b"l+//dNnqWv8b69Z3S1oM9HUECysVgZRL/g0hO7P9O5cK9DnVqPXaFt6+pzjYMrEznM9XlrGkQkpL"
    b"kXobBTEtCx/hglnFiIRVvWhDCurISNIUr4ErvrS0cHaW8qqJoNTvDNTmBLffKjJTUpL7IjTvfcuc"
    b"5AE2Avh1rANmSSyzpfmlMq4U3XspyPpaYA/QPcTOj3mUwSTUJVLU3Xa7Xod1KhPVVcSwCuW7wicX"
    b"Vp9MsO6JhNVmfYRVMeBVBAfWo/jo6fEk6wM290n5hfUOAB5hEUXYMIH6Gc/nMbx9t3WAAevYOoDN"
    b"Kyg22LAnX5aI/PN5hMHBGw3800EjmkVYR9LLo0hYwTcZyQFeukhPlfwrE/X1YnRD6rYSq9GLvkKx"
    b"rXoqt1OUkCO+Ysf8vF3GDQrw3WicS8J0yE8T55jGdYjMhY5quLPzf2CEthb0obqqFWOKTjPnHHiZ"
    b"Dl+93gNtcZ3y1pWVwazBU+uUKjvif9Nou30qY2U/3rUjdrp+9DrUntGtpf0ZJ/EwjvoiWC9IRh3W"
    b"mwxTDnNutFbpAqfJG1CQOzS4VvLVcZg7Ar5bAEM6Mllly0438aK3DbvTMXvVdU0gI8coQmp8oana"
    b"hac7PYFVXhjjzSLfX8c0p1V5/LBKKA6XC+i4VE6hlUPL6DuTUZr/VqzCS5JXSquEKqrIwKlzZGs9"
    b"uWtziMOK2qq7VU0HDRmF8EOKMAEz4wABByVhIoP139n+R5IPmZoetE/E7M7uya72STpJiRBDNvpx"
    b"oK6jc250TsgCkONk7kTn3mJujPH0mLzMrKtzOvq7LuVJdwYR8RfotnCe8sst+Iu+DJuQcMVOlWfD"
    b"Nvo5kGtDFmGsO1ByPMHSSQd3Qzropq8VcmDDgaHyf3t3HgUdTjBOGwaeofsdSAU7pdAwp4UDGZJj"
    b"SPQvT9UFNUN8jc1rjzun7Ij9olgL1vI4LZYHkZlGo9tcOIYlv8wxso+6HSwQjmxqlttBSH6xsysd"
    b"Z+oMFhluK28HtyLJ8Gi7TRZnxcGG1cVTDW9zfobTsurOeoCSqwxkYD3/b6VzwwVGmsMuNC9/4U7X"
    b"WaNxZjl7cn6BV10QoYA+KwclFxjCEYj3tjPgkn42GtjqBbbqklcLaAEGfDALXX3C6NS6gfWMv+k5"
    b"Z1QIo/ycIhigf8Bu8A/vNh84a3fKoC0AnIFb+aIfMwSMthLrAbdWVkEqeguqt0x5Cz8PrB0An0vb"
    b"y+fUpxQ+oGPe+FDyfQypKseK1HNqIvX41jN2AoUTVLzv0C68K3eTDvlnNUcFqhHJKoc6D2H8Nb8m"
    b"Nf/ayB/X/LQGU1rrhQlemqEuH5TBbn8Zr5tfK8brpqgvG4QgBZv7CumijQ7eFdj15cXPaU1/Q0gn"
    b"5eKznJ+yVf6rbUvbAF1KKEV2YReYuBi1pSUnyvTDGkyY1gCFU5LGsTUYlhiq0L0rRxYoiPQVfbcu"
    b"WoSSF3b05xV5HBuQ9i0SFuFcgIhz8ZpvuEV1i320oDEGVKfQFBFVJJtIL88Qc4409a1hAry2Os6Z"
    b"ZHQfOHCTv9gZ4h7G4hHOB4qrQ1zmA/uOPiT8e4Q0RCkkJExS+Sn/Gjn0dMNPm9fodXIdR8PpdcF5"
    b"35MDa7u9nbJbxKUDvqMk3doe2gNJUdojFZvUJMnjdpwx25MXiePNegdOlLisD3+zBOOOm6V55rJr"
    b"oppfMgckuFO3tTufEz1NEudaDvA332UnQupwtR1FiPcUM90pDtpYgSp29GGgN1/lAfaVvfl8zxgR"
    b"lAC9ZHOHghTQvg4QDL23o5aLbLDv7AE5gZHJ6OY7bE/zhnuUJ97Z8sSO27p/yK/i/oHd2PslfhVy"
    b"d4k8x78pz/GfOQCRzrwdsSnbs868mY2vRHC7N5c7GI+tItICBd5TRlYnWepUkfxTr4oEPR1yHHG5"
    b"Flk/u/+H1dy77GejcZo53wB8uPl0z34DHXuXEKzZvaJXt+5sxzqma5k4vi1Mwx6hwLdyB5RMJvjJ"
    b"5R5psEegHXxbgM6RUOA5slyyzWpsVT4A5NoBiW3HnCd+oI8/Tas/kZUXjP7nEjm4q2TfM5zmBan3"
    b"p5Z6EWzyc+wFgkcb1KxOAM46e+xn2dUXlKefrZ+w7rpNc2AXG9vBCGvqA8AD0Mog+SdMxufEID5N"
    b"hcUK78s4B4O8X0Q5gJEDysU9tCFdV9bFLTETpm618KFLK6daBWXbym9kX7BexD9DqeL2Hl8Ai31X"
    b"KHVWX3ZwByUoI4MtBwE2kRx0X5Xs76uy//2Sred729hx/4iDFnRjw7vXHllc+WSZY5QVeMGU7gCb"
    b"f2dptpswcKAY+8Jln4Tp/3t6M0e/exHM7jasb+swJ4g7kGS5UePNEbCW9FHoM21rOmKSN3qnrOgM"
    b"HlVd1FHwrgGT6GVA9I2S720zZT/zPjLt5+r1mVFniDbdWjGEfCvMNMwkszg9CJyW+ud1mTF7eb+Z"
    b"vV3vnUAlarvC+5Ixy4zlvUtY2bDlfU7YcgnMAzmiYt3xkkIhMDt36M+6uG3niShnnYzPDBwXIGyP"
    b"Omd/Jfw4cd5J5nQsidEOR2WhdccrrqI7gEMekG8ZVwm4btWjAjgSCnp4HdcpJAIOaq/UkR9NcIuq"
    b"2JVpf/b+wriCAG6gVL8tq8pvDME5muC1Qu8Wdyz5nYzqhNbCSF0TnFmJQIDOK++fBMqdQaRSpXlM"
    b"0o1McdMdZfcGPJIP2wAZGA+7529+G9aeAqk4AezvZKDqop0Jim9f6duCLqHKq+W0SDb5DYiWygZR"
    b"HIe9nF4AIfQrm4LKj+9IkJ0YuIUKBYbcCahXIrBPMPDLn1d8Q4WAzGI5ndOIU0a7vdGaRvKcVGV6"
    b"MObpcURUQwX/w2vEN4EnLAmKqqdE3TNRW8cr0QU0h1ez5j90N6bR2mb+6FiVrH6ELvJK1gSCvGTO"
    b"sbojISd7FPEzPRp64CNoSF4qFfHlH7fbQHP6AIb0chRdtT4J/Kzq0XRP85PrGOlQ3PSqTbcbjzAK"
    b"FtbjeuMIdH1gAfRhgnceaWoopcNvSvT5qebpW+sW/eh/0mTBTKGS+K5qJZS1PUxZDfEtFst8bi2W"
    b"vyW6sBSgDmvcQFdOU7yJotR7jacaFdUIkPGu3MIESahvsHsQtaCkvBAyWl4HbhXI79ltFcXlpdtQ"
    b"V1E1cVELURoN1Qjq1fThaQZ8F6jbaIx7Bt+TnMfJUpViEvHveGs1+5pwDMo5idoLkTgnkb6Z4qIc"
    b"jXNJ5M2LvMwvFgJ2KoqyWmzE7OmzsM7T/zI1qlXj1Z7STcaaPCsj2o6h0xgGn5Quc2fwt4QHqKiI"
    b"mN8kDiggAIsdtrOE4OwtCNx77QVXq71lUnaKRFxLP4SPt0jPEepKlPG1ItjaKaGbg/i2U+bxhQ2A"
    b"vtmxwzJgGprBhYNPbjX4JyUynwo5xqxAKicGffGtb0x0Qkpk/0DQAnj9N/ShCgBX7pd6i0ua+00K"
    b"1s7Kt/n8mxaGKx8gdj/kWJ5XRD9qrpRiRPtqeiFjK6Wl2nU508v0O6n3UDQTG+5pAffUgnsp3g5l"
    b"VMRCQ7Cq1AE19pkiDHuugy2uTNCQ5pCZ6Lcdp1RZi+DxHJAfsPKrcT6rbQs++7uQJ9NH5KyKKc+T"
    b"vkAlEpSzbwmMnW8LjLuIfL7Q/LdFC/V5ZHB6UcAsQwqsrcK2uMOG0HFYhBw0ZOGcFAh5TzL/wsHK"
    b"gZ+CqNVogMZzr49K0qwsIY+06JTlkal54iJWB+v2//ZE3NH/fyfichZF/+6xt13q3v5/79jbsR1O"
    b"8ChVIQTxWPUunkTShxQ2Vbi9KHKyYqNTx3hbcSK5M/gdfYmVSIbCEaD+ivxEb3uaBGvbE32VIw3i"
    b"FWHZIlFTqUG/oVh/aoyAtGGPZ59BwyluQgbY7SS2t7Mjr+HNKlv3lR37QkHCA8ZaPcJdBOBe/6vV"
    b"pcu2MWR2xsaTzjBMB/rLSVRKoD2NLFqyCyIFCXJak/cZFaExQBid4Aays8sO8YokKAVPMConYDrg"
    b"ODm7ucU1A0BYBvK5g8/nfBeqw/3dEW3lyy10eaoRWIoz4FXtBo8ExEw1OevM5yE+47YPzA41DDBR"
    b"zSqdAJvo8V3WaTTOnV00rLOB2wqKjWAgHUQFj1WItzslFmU0bgmBokEnsLeQj1PnEJDOVMA6ujbd"
    b"MdMznDnVM21FpCpx5D3sWw+kQLx9qdh4KgDvmtgo8Fm3uH+LSthejyBHhYRbzgRXhaxINUtSVtKe"
    b"WbtZugWoP5HPkQMthO7ix+QUSSTtU8JXM7pLA2hC90aA1vMz4S+g37x+X2cXCa/vf97/dF7HAO5d"
    b"6CpezLWTSiTs4stemvODDO8r6Qu0VRyCSglSD8jB17Srdk+/B/S7l/CtFxvsfco34c+nFN5esp8p"
    b"fymes/cCS9xkdJvHzO92xVgd4gSWCBOkTrD+Ar037IXyRXYZQ7/JJSACvLlBRVjDUNM2ydIjZBF/"
    b"Ly5Fc5IM9U0WKxFGMZHZQIyytinAb/CONC/KWZfojq6kHPlys32B9FCyzMPiUBhWgyHV6RN1Io/S"
    b"ZLV4W7skHNa2vzy5Zg9oSeQOgaKUSLez11hnpbiJ0oGaxK9qYNpupCk3DdrAs6RO2MGy6WRMJEMn"
    b"REtbyhYyZJzch2fR9N9L1n6mgIvV78Pf4s2ntFWEeStlA7JhdKIIqDr8oVsrWwXPTQsO5nZgnm5a"
    b"y7ud4gK9ThbciQoIJQYokWPO9STlytQtehR6jkLjyGvQ1RWMeOh/Oci0qRZ9kZBuJOpv2tRQw7CV"
    b"BmpoyC8miz4oV6xCOOKYfiXq0KpGnEziYkZ4R8cXEDXukyWrQ4YFvr5OxuO/ZGtdusz1uENHgQ2a"
    b"PFYGe1dZQUooyJpxRJZhltAzKXaMzkpFyh2lZcpwH3p3iM4hUA86tkV408pwCJiF/n/m+4VyyUI5"
    b"VTeVFKX1mNplc/ZR3jNEBoreMI7t7aenm+KZy1YJagepjB0boKfypnjurm0BDftouSQWK05KA6t0"
    b"v2Hm91Pv8tKPmLi6Ymo369rPvI8YGI8kFYwZjAQN7448TEHgUTzsWjj1s4PtdaCZdeATlxty0eFF"
    b"UVGzqAlesD0MLgVtqTBPUOmV4VU1+PgiYajFRywMvDuK6ANsHp9kWwfy5Ns2DSZhO+i4eqX8Md4S"
    b"oV4tH0OUS+OtnnTUskHyQGp8ecVIOCsiX07GKMwVJ/zx6kRZRNONPl66RCgFAo6KjUGC0YeEDpHm"
    b"7MOjzatTXiXHPNOGWrDyQE3REtD9CFNUc+Zwo/qqIHVFZ1WYpDaUssaEFcGocIcHl6Q2DpXKYC3W"
    b"qzxSBGkSZnYIWXkZiQNTVt89PD7br7P4yi3u3zFDdj0FGwROwYGyUjOmZ+XkqukuW+gb+01xjhkq"
    b"RvBs0Y0yzCmEcwU89jREHIMumCKSjl8BiuMBN45rwBzE9PlGy38dKeW45a/xPSDHOtyLjAUOIt0a"
    b"pMqPWpkGn3KrSPS3+pioKTCOx9ASxTGqQtcH6OZJwXJLRzx0BZcxYjh04OVz9Jc3dZzu/1UHEY8W"
    b"PGA+LjAZDs7xyVS+Cn2FgeLWqJeyy/r/W1/zoyvPz6+k2e93uhSyqCHaUMVIS2pCvqR8gx0I+LnL"
    b"zEWrb6s8n2YVKQnKTHzWHWIsbRCbrHWW4TGfrsB7oJFBk3ijnMIpXe4/o0SrrLSwOBKKtuwgzrVS"
    b"KRGVrh7HuLERDylKsaxFfqvfhpJV+HhqQ3rH3mVqeZpgkC1z1RwGUULraqaoROySZyg0KpUDH5oB"
    b"QVMip6oIQ/xYTDBTDaP76J11+VvO3qU8NUoTf9NDsn6bgSyMxgCau+Lm3E9JsZ8qQ3B/xP4kssCl"
    b"EsOvUMuXrsDoE32RuDPaJTz+CJr5NQaBgWLkhduua45fty5v1qfF1C4B7S+QsRNjc6DLZm0VBEHA"
    b"j7y2XvvREv9wB8KhTnw6Pn+/u19vl/Yjumu+6xV9XIkr+xXdtbDkkhgbw0VsX45cVwynHsKsuTNd"
    b"pHRHKtQMEqWrAIF5rG5EHeUupJlhN+cxm/D79NK/kn6Es4lzjW9kne6WNr0DXDaRIUhBWy95dR8e"
    b"OmTjMQjkjfoggnwrYl3Kaw983A1rNy83r/D+MYt3DCGpiBxFrxizOFcG3nsMZAsr2UFPe8NyZepb"
    b"jE5yIFyJtrguysp9SRLVyzSxlykoWwKXoNTzZhgEQi8lkGWg2wegyUaUXdwRW5SZzxEXD0RbrmbP"
    b"WU2BvWd0dEJ2/0ORgBSpZFuonM+XYe6KqkWZmx6UN+GUFPMRI8QrnIisS3Mj76ujDrX980p9ucbw"
    b"VgpAIb0B5tt49gvjPEhI4hj1s6TZCR3aeSdwSWN4MJILU/Ylsa+7fieKG4NU+FxcfvsRNAH4pJKE"
    b"en0v9DU5AKUr64yCtKRpLRNj1sqnyiUKm+ZKkEYDtS6XXZYUqRUnwW91gmvrVSrPpLi2tqwyC30v"
    b"vyLHxBPldPEL48arwZBGlTo4cte+cHNWmDCF1gDOJike4GmXXylOBknxjj5eg6D+lWh4EeunBqAP"
    b"7xNzjTjG//2C/OztomJWpsqtLzpIJfC/tbUvKdYOktXHvxsIKgG+7O2pSCcjOk+Aa1VKke9S1S5J"
    b"NO8TMiADj5u9TzQP+iLW+KaRK+mWKum0leI12QcCj3Sgf5fKIwCHi7cTdmWpL+quUucgcYCpneBu"
    b"kXVloa8hiJSvyyfmEsLF66smpQsMJ+w9xluB6uV+q3/vbMDb+ialKdAVTebkiS0tql08B69NzamU"
    b"+28zflnv+Gk6BtYXD5tx0q+zemdC5pBunPgg7iJOh2gsrHcHcTIBXXY4itNsBGAPI4FS9G2RN/55"
    b"2xwJfI9HowlwXlg/oGmlRSW9bAzQB3z175vJXTZY96Eiiuv6FMplaH0fQE/ClB6SCBZvBh3pg8Im"
    b"sqfEECHnBlqD6cm6cRhl9/FNrLqOTQ3joXzKkvWNzeYkDJrx7cBOmvo34QD3e2CMI5NBdeOoO9iU"
    b"TqZQhdDjSWpSwnQIjMKHNV4qmMKMxH4SUOzlUZEshr31AISSZATwCmCgJisDkWOIB6tHzU5iUm8n"
    b"w7EYqTrGk2QMLEl1DVPoeR3IafN3POqEuCInQRIHMt5QUSIZh00RTHoC2pTAkbX4/TiB2W6mYx+t"
    b"hzo1guRmGBcJCZBnYLG9JkxjB49TmSxYFn4yTeJOnNktAqRGgAJWHUBTAUl/g05vkoZQF04q2s9N"
    b"4ojGDXypnBIjeO/i5MYkSwDRhnE5LQDVodSXKM7idBA278LIpIH6G2ZW/za2mkMQraqtbNnASLuD"
    b"KE4SidSoodw0Rz/FvXonpG76Iz/yB03RGQraooCOYCZIIPgy9TsTVTxLesm0iRfgDOK4FzSjYZGa"
    b"DoB1WF1BB194U1iZ+iMMcYrp8ZhCzsl0eIO0++ZN/DNMfNll1eDT2636FfEtvH35Lk29p0/ra8Ue"
    b"VRg7n1O3hVSh9f/8f6ht0YQ="
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
    b"eNqtV21v2zgS/t5fQfhrIksUJVMqEOCSIE6TNonTODlvD4eAL0NbsSyqerFjL/a/30hyam/P2du7"
    b"WyARQHL4cPjMzMPxrx8I6ZVqBgvxvISiTGzW+0jocTOdCzUXU8Bx729VsS4rKKyT+7mb2bIqeq3N"
    b"bk/P6/thn3XTdY4WIBbPyi4WSdUsGz4AGRglQj8SzA8Z+FIbPdABlWGgIsqoEpTCQYDnukgbkFlV"
    b"5eVH150m1ayWfVx09cJWG/fNP7ezd/+70wpIQZSgn0Xrqu/5A8fjDmVjz/voxx8Z/9YZpomCrGwp"
    b"ubkad3NJltdViVP/wBEhv7bfP0dfa3eYwnZJFGqWLFuI0taFgtLdR3JaJKfb1a+mm93OznyfsgKm"
    b"CVqv+1m+eCn7tpi6B9xyHfd9UNz5nGQVTIukWrdOzURIfSf79hQPU/dyUs+u5tcP90erq7m+sV+/"
    b"3FH7MH784h4tv9mingv7Aqf6Lh+7AwqRjJ82soq+0Hl1MxaXo4vrTyv/7NI9C8/OV2f16uRk7zoz"
    b"4YeD5shY+uBzrkTEPBjQ2KNKytgbKAaRD+Eg0DSikgUDzZQQNOac+8A9qXTI0QB6LeRvx38yVsoW"
    b"8JeEqgH6qyLVYGGg3oV8L07p/efb7+5MHC2Hg/n9tyIXk+vLTbp5/TJ0h7NkY9ehXl0//nKfzr9/"
    b"LeSozt1ru/Qv8tHEPR8V/uTI8PjT69PGZnPIEnbzujiv7w/HidI4ZIH0PD8IuIm5libQvgbP94RQ"
    b"LGaBoL4CLnEQBFJ5BjBI0o+oh7aB+c9xyqxMwS1B5XjknB6MEuvTvveHQWpRnB8oTrvjf4nQT+5g"
    b"fP4Q9L0YHQ158sCrxxtxezlRKp6w0cviZVnfZ5OL+uHl/Ovt5unp1H89VZ8n03Mx8vSnXzbBw3Bd"
    b"BcPPt5/A8PJu5Lqvycyu1Prh4YGPPsfTwzEyoQ5NyL2ISU5pwPwYK0eqWIgYRBAJjzHKGOMqZqib"
    b"glGNhRR7vh/IkBsebGOE33+2SggZctIA/8jW32lJu9xHwno76+edNxB5PIiCEATXA8pjnzKf0tDD"
    b"P4i5UZEIFeZOyIMAAqaUDMIQcE0IMTAiHnSoGopkKSqM8gFJNkkK7/tX5Hm/Kg8RJQxDidGSDbgQ"
    b"MsR3JIg4RCC90Hgc5UWh3DAUHCW1p1F3RKg1cCOZx4xvwh1mXhe57R6QU61LMoUMCnTXZk4pDJCy"
    b"lqUqkryZIQpfpazOj0kqysoprF0QfKnEmuikRBSRHhNp60yDJnkt8W1qgUhVYJUk2fSYiEyT0qo5"
    b"VE6pbI52F08Xt2MilIK8EpkCV0OKXBVr8r0WaWJ+YFhSzYDAq1AVeXuMyW1DFxFa5Mhe/3CJvnGc"
    b"iwrbij0V3JMrBy+2BMckmUjTdb81PcR7qA34gYkGGiJGMScHNDKxDMOYMlAStUJ4gc8CpaM4klpx"
    b"4cXUM5KaKIQA4oO834g5lKRhs9+6QRINi9xWmI8tYdNaFAIrE41Sq0RKMKW6eu+oWc0ga8npdiNB"
    b"zWwBL6Cq8v8hZRspjAKoNcb+fV4gwPdNSx54POI0xHJBLeXIgMC7R56OVGA8yr0gVNTnQnkBMG0Y"
    b"FyY0WGLeQV7Om3xIS5JDpjF78EbKZhleilTJAiW1y6a6bNbLbVrhpMF7dHRgkra0HjfDDHMnx5RM"
    b"qnTdQGH+VMgoriyIsZhEaN/sfLFJ1v9ZSGSdpPq5srZp+joS96UfytZge4t/e5UHbwvvaezlU72p"
    b"H1eVLqezC2bVdXxWRqNbO6Ts0+19OJ7Ii8Q/nS2fZPT6SK9WVTy0ZTy8EAtjAY5qd3xXZvzy8e9I"
    b"bLoJBpkv5XinsT93iR+2+YDPz7ReYJrtlKnnOBILOH3rMXCM5CxEdZJgFuwmp6mVInUysYCTr3k+"
    b"3qbP7V4niVY5UtpsP5GFXZWwt1Lh0VCdQImtrb+bXiRZYta7cQpTPKVpoRsvTzKb7fmgZqIoEaSu"
    b"TNT7ESpbV9j+vi+qzT36eE7/Tfa7Dfu6z7k0CuXVGOVzw6inAwZezBk2DDyIYyYjT8SRxo/A6g5D"
    b"LwSjsbMPfB3HetvC11mTps/wij6grDwnWNNFR3XnaYYl3gx7Y0xWrELMX+0kGbm6Gl6QBDOZaKva"
    b"+KBOYtycbRg12b0pxJqtJr6FgHT3JNvWouyTBr4hdoHSUcAygdXvIbrfC0RI26hHgf85FgraFJAX"
    b"VtcqkVgyK/yFQ0Z3D1cT0soAwcyoN5sTr08wrY+7yU7ht+XQYZUYIqfONRYXaQqoJDZDuMauWUcS"
    b"SN3cSa7JCMsJl7vqRf6ypupxLquwIH/78C+OckM2"
))

NOSTR_RELAY_POLICY = zlib.decompress(base64.b64decode(  # generated from NOSTR_RELAYS.json
    b"eNrNVlFT4zYQfudX7PAcbBISoLkn4HhgSg+GS9uZdjoZWV7HamTJJ8mB3M39936SY7hep0Cf6Ist"
    b"y593V9/u+tsve0T7XtbciOWGnVfW7M9pMorbjjeK77lcioC9/cnh5Pjg8ORgfLIYz+aT6fzw8Lf9"
    b"BGytVnIbMZcPQga9pVCzZ6rUhsk6tVLGk3BMvmtbrbikYGnhtj6wsxnddgW+J2U2KoiACKhyYtWw"
    b"CZ6kMMYGEmUJQ+S41UIy7lpsfdZ771ofHItm6W3nJMcw6hBaP8/zlQp1V2TSNnnZ2PA5DzuneaFt"
    b"kVcnx1xMKylmk1NxNJkd8aQoq/K4nI6L2VSejo/GUozHnLdCrsWKfW4sfOXeyVyZkh+y4PsYAvuw"
    b"bDjUtoz+71izAAGfOqFVpWR/qs6zp3BvKX7bMi4mUGE7LEqS4AUHnu8WdAayCi+dKuJHlgRIYV+T"
    b"E6a0DXZaJUcD+JzayKEH6wB6tTKwePnL5YfFKKai54uazgcsQ+cM3fxIwXUcLZ8TTFLJGtlyCc4x"
    b"i8SbaPrqfS6tCXEJ7FmyZxB1qMnjCHRxffPxsregPJCGZcjoBsfLL9MbbQ1TaRFZTGTPyDbFiJVZ"
    b"ZXRxRcqTrSo8cm9pQLvOwB/eGgZvbk2R53dxO6iGqWahUxytcCIw6s7xp06BJ7KFZ7cZWCAhJbdB"
    b"GNk7eKT28dzbXTHFr5TkpcbpdUzlOTwSV5V1oSc5FirqE3XQSVDJGS1AWevsnzg51SJGTvbeoJlq"
    b"1SJFYM+Bz1Es4I/XZ+8ig+gFlYDY2Hnuaxouf8cT0Zd0xX7fPzGUex9rGsXcdEYFxT5DOWbeSiV0"
    b"stHjWwYZ1i21KPojfLCe/hXVOf1txzxZzJ/Ajx1WciU6Hf8GsXge32srhV7G3ERTyNTBri6/Jz8f"
    b"2I4VmToEfx65fvKkkUYjt8smEjE5Ok37X0fPM9J2rtWc+Iut/hwVtwlKdxH7MhnfGX57RqZH41cx"
    b"UnRyzQExo/A0v6JELnrky5T83eT/gJHZD69ipE9i+n1nSUNeaJhnYP/smAH89nQcn/wXOkoBSciU"
    b"fY6L9xHzMguDqben4HT4a+D6Rz+eOLUR/XySGp+GQ6TxYpAK2okXNImubuPEAR2BYo926vnz3TXW"
    b"0B0ARsQtRiZY0ZSKZZCGNW8BGpTT50nmokpgV4KMkKapEa0xAoySFEW9RfEoSOxDoAcKYpUkAzsx"
    b"EgGBwsACp8oHOEi6H1WmznY8DeoshXPQhMe56gCUuG0Lj9+K7VUcsrDVMu+OD7NaY4XpBCrGB6KD"
    b"pP7Kxd3iIr4vVYmoMRLIWphVL58N6EAiMEY8ATD8CCxERj9xqUTCiTjt7YYfKCBuPg5BmBRc1Mre"
    b"Sba/93XvL/3RbsU="
))

BROWSER_PROVENANCE = zlib.decompress(base64.b64decode(  # generated from PROVENANCE.json
    b"eNqlWGtPKtkS/T6/gvjVAfb7MTeTjA9URMGj4lFvbsx+QiPQSHeDODn/fQp8wYhHZm5iEOjd1WvX"
    b"XrVqFX/+UiptZa4bBuZuEsZZkg63fivhX+dfmywLeQYf/wufSqU/F6/w/ci4e9MJcGFrFMK4l239"
    b"+nrpPcQWrvAKf7+SpcXYLe7p5vko+61aHYdOkuXjWWU4GvSySjruVJ/DVcsvb8qLGJW88/QeBxbf"
    b"JcM8dMZJPpuHy7qGY1KeJKftvbP9E7F3EVsFun24cgcP9vv5dfOobiekf/bQtOPdes8e3IxjP9hW"
    b"r54fs+5Z7PaGRXsvyx9ccnRV6MnVsewdPDw0kmqt+Pb77+9PHoTceJObu5j0lzb/AvIlKZVeBtv/"
    b"eA+gJFzM79ISRx1QECIGw7RTnmluArUCM4sJ0p4QIYgS2FhEfOCSRC0QFYQjIehSStfiGCTDyvKJ"
    b"vD9YCsS8chTb4FjElFnkMXfEK2SxR5oHg5WJCHHKWWRUR8yIxtF5aRkW6j1mP3FhmC2efVq//PD9"
    b"+gSd1PdqzYvax9VLqWFIKiS9NTIyaaS20VLjOJdce0G9lE5TiYP1SGDhuUGaBi09DQojquXWIvSP"
    b"Xz+l68M4SYv1dGUVVCH/kK7P4YCuz2/Kixib0fXx+9lxfdzATwW/GQ2VVnF3pM6P7i+rOrEPxRVp"
    b"TAi7qB7f6KubWvd097RRjHHn6CprJc12V54dnelirxN6vdFt+6hdv75upO1q56d0XQG5MV2d5W5O"
    b"CCai1EZbHQhlkgpDHFcqUIUY1pIioZ03LipsTXQBLhOFBBHyI11XcHxOV2+19s5EhowmAkNgFxgn"
    b"hAELSIiOa8KicMwCRzG2wmgZDVTUnCScKPv3s1yfh5VnP69bgoCD4E6I+T8dOXZQmT5oGwSLIUYh"
    b"ECec6eCVwpprY2SwFmrV+GgV5usr5vDspEwrqJyOy32Th/Hn5bMC9KV8KgP/swrikhoDsIQKUN1C"
    b"Ec04tYrDwTkTFJNQRUGCjCjrsIBjwloZDeerJMYam4+xAeEge4P0Ar6SP+afLX0HAxVJvNOSwTkx"
    b"rSOK2hJvIzxfi0hMkMaD4MCX1HvQQy9MVMJpyB4VWomXcobX/y36ERRfBs9I72wx9As8zzW+XOF/"
    b"vC4qj8ioOkyhYl+ALhc7JJRX6OuFYgSrghncuXQwSPL5AsAYLIvOAJMMJZwGYn30wjNsOXMKU+wM"
    b"xuE1xEZysQYbaMfif/kZ0ZJ2fKocw9srfdCvHl4X3fr98cW37Wn93p+m5yctnF5ctk+q25PbdFzc"
    b"m7QXdnxrdFkF/iqrr55srk7wfX56aQ7PasdHU7J7WN3lu3vT3WL6phxbZuy6yeSdhc9by6rL4Muf"
    b"gX69eUnTLQkEatIoCj0Pa4Qd1AgSDkSbBC6Yn5c2ZcJTZ4COUkoSJLLOcwkL3jL8Qc7e8KxgWaNr"
    b"61QtqCAIMVpjD60Fek301IPGhWCjc0p6aMgMWjGonOGIOEd9lMgIJpQJUbLVc/8C0/OiSp797a53"
    b"OBiUE3MMCkJkhJKJFuSUUqKhDVttpXPCI6IkkTwG7GSIDEDAKolIDD6+Bv45jiSJYVVwl+Q2SAlb"
    b"R8LH6AAExcgzGhBIO/NEQvmCjIASKw8vBqPIOeIheigQRjwo9WtEH8bJxORAgoU9SIbJwPRL4zBJ"
    b"wjT4EviF8ote+BKcyghglszQl1w6DqV+MJNQjsnQ9Puz0sjkYEyz/5TCo3F5ab65bLG2a7Lu/C3c"
    b"MUqGQ4hkZ6XL85uLy9p56263XT/ZXxCg8gpqrWH5oLfrs7bqW9ZorrURXJLXUkdjHPIhag69gksU"
    b"SNBRE8sCGDlCIlXAJq+VEsiCw2MBBwjyGtkWSd+/gVmzndWFSzqLBWUhSKqwRMBjhGKMFktgLLQB"
    b"46BVRnCacJKWgxJLZZBxgmNOQP9BdF/jjkPfzO5GKWxx9oaj2bq4PL87r53s3FysoFhZ/Q7GGKph"
    b"qxxBLUcOFR6gz+j5RoVygoW5xXUGeScxVDrWkDeQBeyYkxYYFuei/2Od3Ps7H0Zh6MPQJeHnU8mq"
    b"0M6ZtdbyrXSBTZVvHu2j8K2VPuiofO6yEWFMRvCpNkIteSADAqJQTZnBxAUJR0QZsw7FALpnCZhZ"
    b"WMviT7zcG6RlOBt7OgWTBAiI4PMGDJYGZNaLgKT10oDJsgy0xWghHdZM4Ki4N+DEUYQ1GrPo//kk"
    b"sBbvBhPB/11bX00EfwxT2w/VLLgRPPIeryUKreAK+poni1Dlt1DlxW1fkSRyzyPsR1ELFoyB5kM3"
    b"tA5agQYzC6VKKaaUzicfMB+GYg/NUSPwwZbL9060jiTr8WzOErAbGgbEgDnjjIJQeJhSqfKYBcBh"
    b"lAK7S6CArQQvjGhU0QaoYC3FfKL9FyxZD3gDmlDNYCYQgfO54sD8SBCxIQiqIVcAHNoqZx74HrkF"
    b"Y6kDZJt6IjjsAxoZ/rvTfB5cX4Tnrp+6+xVrZ6aVTpJ3C1tkYexSMGnDvALmcfGzRfb6K8ZkMfdW"
    b"X/Jdnkd5T/rqI/6BtoUJPCyATYVyop9OsvLrCVR1iqPd271pY3jQvfFHYzLLivPvtfHltJs2ybW6"
    b"rp2c98fn09EghhvS6xXtJsvNt9OsfdJoX6W4wfYnt/1tNOrEWTrLjh4ng0ltujyBbnrsK1tajDty"
    b"o0M3wTlMLJ5LpqJk3ty4sWL+owVMaQKGIEcjgVFVwtkzEAVsGQM5kTALgRZ/qQ0vP1/AnwVHMp7N"
    b"L63NOFnVh88yflOf7u1tjy6fRnQ3Ub2zum4fNFooRxcnqXjcORke3SfNvJq0Dwbt9u0hirXaoDY7"
    b"aEx62X5jGpKDJH86Op91i65oTmbHt2zYfDzt/JuMr9tZmWxabZpj6NmRCUsRASEQhCHob8woBw0l"
    b"KgueniEQZIQVks5LoSP2zAcOk7o17MvET4Md5678Yg/XplwDVPx1yvHOt9a2Z7V+vLq4nj01ry5b"
    b"Ydo5vKzmO+lgOn3Kr6si0DzNJ7PZ0/XZ5LpeL9rt3s5gdntoG7sNe9u6NkVxnKa3A9oR9eKgSJrf"
    b"Pkn57sV+mZb3+gZk4fPcr26uvNjIhtM9QoYJJxw49PnvDTAaSK5A5CDjUgYMRQB6zQWMTwxmBcI9"
    b"jRHkDznnjfAwn36V+MyPPmmAZBOCezndP+vsX9H9/eSh6B/3GskVUYJPG9kxZTf17eb+ec0Otg9m"
    b"Fw/ie9FoJffTWfObG2z79GTnFrdEP/ctdBEa/UAeT0dNujvu/CtJgY2UF6A34bPUCmZRrpGJwigG"
    b"VgcanRcWHI/VWBAHfRCGLCwwdF3EYjBwEA6GH8e5s14vdY9ffvzyF2zXpQI="
))

KITE_STRING_JS = zlib.decompress(base64.b64decode(  # generated from kite_vtwin.js
    b"eNrNfWtbI0eu8Hd+RfPsPLG9MeYyk2zWLMnDMJ6EDQy8wCQnhyGexm6gM3a3j7vNZVn/97ck1UV1"
    b"6bYhk+yeSwZ3qW4qlUpSqaS/rK7Piun6ZZqtJ9ltlOXDZKUxK5KoKKfpoGxsr6wM8qwoo6si2omm"
    b"yf/N0mnSbABc96potLZ18SRQvj6Z5uO0SBjgTVn6kPDRgOR+VzlrYRKXNx4AfDQgg+nDpMw9IPps"
    b"wB6LSXyXtSP85/QhG8z9KjfpaNgX0xgkBY5BVj09O9l/933/p97J6f7RO1FtSzX6w9HpWf/1+/2D"
    b"N+JrYzqZrH1Ky2TtJi/KtduthgI73P2f/tuT3cNe//UvZ71TAbu59U3012hzY+uVgqHy/XdnvZOf"
    b"dg/6hwi1saGKT473+mf7h72j92e6zJS+Pjo6E6PcPe6/3T/owVhwHJd5Xoq1jSed34o8a9hdHe6+"
    b"23/bE+O3qlxN43Fig5/1DnqHvbOTX2zIMhkl46ScPtjQe0eHouU3NuwgH4/jbGhDIvJOz3bP3p/a"
    b"0Ii+oozLWWHXONj/SQz4pLd76NYbpbeJmGkSj4MVX58c/XzaO+kf/fxO/NfG0TS/K5LpWn6XJVOv"
    b"1u6bvV05yp5XLx4OYjnSJDC1/Te9d2f7Z78EJpcOk6xMSwd1Am/vxdKf9M7en7zrv9k/6e2dHZ38"
    b"oqsKFM7i0do0KWdThpSjvR8DwLCns+vOKB980qDHJ0cwFrH0Jz8yPGi6FaR/lY6cudA03u73TgTs"
    b"+q/nu2v/G6/9a2Pt7/21i8fNr9uClOcv1hU0Yfjs6MfeOwKP164E7MXjy632168YIBHh2939g/cn"
    b"vf7B/uH+majwkm8ZiY/dd6c/izbV1nn5zStn6wCsWuHTsze9EwP8auPvX+st1Ptpv/dz741A8MHu"
    b"L1B6dPlbMig7V9Mk+VfSPF+JosZdUXTX14FeZ1lapknRyfKiU+SDNB412gZiMptORsk0GcUPHQHN"
    b"iy5ng09JKb5O44FApl+Xaol2y2lnMooHiV84jMeChtO8sXIBfOhqlg3KNM+i+DKflr3pNJ82W9Gj"
    b"qEVTS+CLmFCW3EVU2sgnyTQ2dZIhMLSIIDuZ2OSw8ru6uYYpHAheiIWvj07O+gKbWEZURyDbK3M2"
    b"pvJGbKH9q13qplmk11k8otGlV1FzlT5E//53JP/syBG1ZKPQPDYSyXKxjwUFRqmYWpwNkvyKJhV9"
    b"5wB0LXzYoypGSTJpjtPRSJxJAkvDoh3xoYVHzWYKuDymI63ZnCZFPrpN2qIQSKYV7XyLrUTRKCmj"
    b"Mh0niP7ZaLSNX2lZ5DxFSZPVILRQndUdqtWKBKnE0zPxMZ+VVNjaluDUZ/N3IUc2Nqd/1ICLpFRd"
    b"+iNU2NLNjvPbpHcrONdBWpSJYJfNBnbRaKuZsiEjvpqq23bEV0J+DXQSD4f1PbSjx1zMuhuV01ky"
    b"x4bmzsqLgcZpJpjfIeuyOUzi4SjNElp9ucaHQpLojOP75kY7UgDRWvQGGHqW3yHaeNPJfTwof0we"
    b"iuZtPJoJcvgk/rZafJ3nYiGzJk4QgaIvviCcP0xgsejbjlj3Ro7sp6EAVnenU7H10wL/pR5aqlCy"
    b"qk+675ZgLNOy2er8lqdZs9FutLDR804HgS68YtGMM5vLfJYNk+F+VibXAtVySmOBu/FsLP6I7+EP"
    b"a3rvZuNLcUymxWl8lVgVYaRyct/uqEbMt3/sqPacbRoDm/1XMiQ6RfbCOdsnsQyZoFTicKI5iUbO"
    b"qgCXdNw1xC5gJd2ogbwLCI1OLji2Lh632q82xFHUKYXM0MQeWooXUYedMj/I75LpXlxIGqbRjIVg"
    b"GF8DdzzF/pp6WNSrKhe8jkrEH41Zhm02WDuFwJ5oRILjAov9hWdBcx0E5OK77od18b+nX65fp+2o"
    b"cT6bji5wDTnkX85//VBcCBAB8ZdzIbpdj8Xe8eHsM1ucxHOsck5iyFWaTAN1fv1wv7Wx9uH+b8kF"
    b"QiuIYpSKcrFhNrc2OL/EOfH52gs9iadFsju9nsEQi2Y8vb41ZwS2DJ86oyS7BpFfrOlXivah4Hzj"
    b"ghZ6bS0FiolHgmi0HNWwQDc16HSWAatbG6bThrMPEXLrwqYeCQIKBuzDS8HEZmXSlLAtq5eXupdr"
    b"4FR41uoWjNBERIY1Xl0gfmgrSlYrkaf47hj0kKgRmmJbsVaa05t02qWBKl6rRqkAzbC6kezfnAHz"
    b"KszDibQlxmlhfjWATgnC0bkpIRU6JchqEJ+bFxwPdP4z+WUGO6MbWZ1Gu69Pjw7eC1H8ePfsB9pQ"
    b"c0OBjxJ7ooY4MOrxJHqfI4HGhdAFIyNgFUIZKI+n6a04A0RdwXTz6UNzqP7ivEk2COd7fBenqBjD"
    b"6TuC7lgVxYI0PCCJtejNXQ7dwERCGiyjyyQaxFmepQMhT1pcqYyHcRlb4xiBWhIYxKqCFgti5tcC"
    b"ymQlpw/jy1xs9IM0+yROwapFqh5oHAEiTIFZLBhEU3cFSxZ9EW3kG3/7WwsRs/GE3oSMK+SzQixc"
    b"ISgwibK8jCa0dnaHkkqlbt+5FgSTDmn/qqWHvWtQAMUwGrvGk1BxE4tBid9XV0JPyMoINUw1LJ/y"
    b"BL6Gr+lEfiuUsCZoYs4hvHC5oU5wpbHF+kW2CgvBeqJv7d4Dk5YSRAT9wkGfDknluIrFh6G3QeX+"
    b"MPNrbVcg4p9CgrUxAJrfllT8ODYm8cNIaOIaGfVoNJtGymHRP0+P3nXwcGrKpsThL0/3xqy8+qbR"
    b"MhilSgJRljC3yoU5URiS4ypRCP1HVFmZo3zEYRtBdlUKBWXw81Ro7wxlUiAzSBI8jY4TwNPHF484"
    b"aeLS6dWDkvxAEWlHW635h+yjmvLrGZBv5/KhTA7wgGiatlqCQpw1CUyQ7DGR0DEmM6Gp3g+SBEgG"
    b"ScdMlMZZJuOJUJvF5tkhno3SqzmTxeYC1ZVoh865j50Xj1h2KWQ1UziHz3LvTtLhvFOOJx9JBFad"
    b"3cTZcJRYu0gozbI7PRLq5aroYKVYyC6do/7PJ0fvDn6J/i1PWqd076S3e1ZVeHby/t1eVWHvf/YO"
    b"qMON/OuNDTXeUiCEsEtDpZF37mDZkcjNmghBjYh224cH0iFpdi52rFC3RsFmB6NcSb2wMvxoQ/wa"
    b"1ESa3xigwY1g6ZIOcRKO0qFPMKRXj1Jv00I0tBOJmY2NQqollUgWSLVZSRhaDNGlrgwSgLgkVa2B"
    b"5Vr+d7YGgDN11WskQ4UIzw6tG70F8S2hqi0t2i1sf657sRmIbEfW/3j+4hG+CLV10kRsMR1vfvHR"
    b"jBUHaTQmM2bJqryhfXx88cj1TOxY6ZHQnQSPQO2FxfE5iShozbsvHnFg2MC5+CRkrY+yLh/s/COf"
    b"uMc4iLmmBZ7qmmwQgZJvMO2DOiRychSP2aU44/5594kTmyV2D6a3Qmo8Xtv66mspZSf3JVkY6KeY"
    b"Qj+fFN3ovHErdtrVQ+NCFpQPomZvT1a77xLr7dzT7wf1+4FGaw2LxJSnjWuoGhwuGifYUz7DKMFa"
    b"fYwI/DF5OMs/JVlgtPKMuJrm42Zoe2uexE5W4NZfvxJabaPl9yg20HUyFRjKyqY1gjZTaqwh0G1P"
    b"ZyBO/zL5IS5uxLlzEwPipNY6mwjRJGnyoX4EuzfdNQhkiS7Xbrc+bLx4NF3MP2x8FIOPi0GaCjGg"
    b"siV70taIzeRl9WF6DQph4ya59zTql1sOMlCk6g328nw6FAxbdOtjX3fOlqeqqR/E0PalQqkgzXQF"
    b"21UWK0kRLrZRCPKMYOc4jQYhf9iPwVzXuDJrCD+Zjix+AYr6cgf0f7v7JClTfkfc0Wf7k6Bv+FQM"
    b"bpJx3BdbESR/4N8Xhj9exaMiMYf8RC2EmlzH6YOB0nh8WDPO7TpDX8ceF/Ja5+pQWgdc5CIo+1lh"
    b"RPCqkTVBgZt1mZj9ci6W5RaQJlgF/CNZBP5ZIjbv4T+CowXakTzbIEaZFnSrw6Waliessq6o0Ynt"
    b"eksnEvE4DaD7q4TQTYieCECwt0D9YLGuLAaOpcBBA5VDxfbRzMZBkw9MUpZwy9ZmJZQ2c8lzpqJb"
    b"NkG3X68o3LEHpnvGk4NRqsOAzJDvW8tAPdRBmVHcLwe2ZGvDED7ucX5s/AGYBwfmwd6yDjNC4MAR"
    b"qeu37OqMJ+qq/Kxj+9bnv4FrhI5huUE7pgukSOEfO9GrbxSQK7bi5QcpxG79lrlEcPTQJCtm08Q6"
    b"Xoz9zT+1ieEq0+YxOXkYhY9X9a/SHZVI3oDep0Up5m7ZAfA45r20o82vlb5qBGX/aFStWSPXR4wq"
    b"XaYFpgAYHWmWjcDkwkemdIAoEceXruLJxIz5A/FoFIKYnGY4jAZTJ+ZCOigHNxG/V6ERs1sSNF/0"
    b"3h0JFDeUMVJe83LdHFQCjV0pb90ll/KvYnZZjjTBwl6i0+MRVEaUPt+c7orjAH4O92bT20SLtnM6"
    b"VYwYK6XXtuaCF7bintxP8C6Qdl20w0R8ps1WDZFqwwAbJGLAxDpmy1b0RTwCOjOC+/N70xzH6U6v"
    b"545cK1um6DoCBeHLEAX9diScroMwDmREm647Vb8tMfRuiN3ZzUu7DON1XY/ROQPiu6wtVR/Fc7pI"
    b"/sCUmqA/7J8eSRWipTRAZZlzdqBCpbOHK6xUinCHzr4iSyazbTYcw4hrgbPZjfrFL8rUN1s+z/Lp"
    b"GE04P8D132u4eJzGd7RhaNTgaSAUJpv7iQ/S7+P9yQHUkPYdue/71sZ3Zy30d2h+zrjHx5Z3OyS6"
    b"EASbl/kgHxGzwBvKrratAMCsSNA0x79N4qK4E8cz/1Yk8VQMjH25EdpazUWQHqO+WcgigbNpgliM"
    b"YXF+ODs7Po1Ao7RHv0qDKG+ggU6SDYuf01JohutCGYt4WfSlmNQ6d3OBUq2sVlmwLIULLKSFc6Pp"
    b"W4ndmzHHn+pLdSlNat4Ks0tpvcY9+YYJcHEw7HKVVI7K1rOZrUfW4sIhzkBJBZGGCOrsWEFapSvJ"
    b"zR353L8Q/qHWvuBO1TJjL5itZ8Xfdi2JvIGAAbVi4qtq4rbZ0HX9wdkN7fsFZjn3BmObEKg2dcYm"
    b"rW2ZTAcn0Kcperodqoxa1irTstxy0KJWlRblFoKWtKq0JDNCR2ORDSltxevB1lVWUVepANIX0kpH"
    b"Mp0GlAKqet9aBuqhVbWo8gPBLSZ5VXHum2AO0YlzLx6NLuOBZfurMK408ml6naI4hI7PIVuHu1Hs"
    b"U4HEeGrG5gKWEcPh9DuK03cbhikgwxZ7lhwIAWJz62+dDfG/mw4UHPDmCykZTVXQAhXk66++evmV"
    b"U0kxZGx6nTW5yg4P+yOcH84nfRjZn/V5ZPVJeDEMTX3QQPSVPNFxWJM4nSovXCKYZzNBKVck/xRq"
    b"z/vpiI58sYZX6fXnOvT9ATAeJZBUCtHStHaKKD6GkqKp0CstlJvsJjQgGuxw0UD5tIWWI7gYbIHh"
    b"2PNpHLolzHTIWRC1PbyDAU/ahjNfh7TBL87Ml+43WhdhH7rG1aQt5MG2AGoL0bc9zfNx+5YRI2vo"
    b"OimbjVtVcasGCFqRcHIa8KWfDqurgL3TrwGGh8oqYtx2Fd+s6FcSk7QruXaOyppXk0BFJvqz7VFh"
    b"On3SwkDz7dv2HdA589aqWI3NShBoxx74JEmmbC3cCtSjVQM/9QfxJL5MR0Kc9/0r1eZ+rZ5h+Ned"
    b"o+Q6HoC2V2VUl88T+sj6266RPWBVB1kFfij/YGVaB0z2QYQRZeP4vn+bJndienSsgH9Kf5KiNVdi"
    b"QtVzjO1gfi/jaTmb9EvyHO5LD1socnFCtnmj3uJO/fyzZZcHzrVD4PbAIIYjhZqgFxZiAnQ6E67w"
    b"E5GuGNh14n8tQXA1bdQgF737oUcskwxA/4kjrES7Ynp1a6DxjUxaUtcXX0SriPkaPx5JodLeEI3T"
    b"Ykwk76mDwbuOVf+uQ6k4y95iVKhE8MQEH47w2moNnbqK2et5y9/m4lq0Drd+7FWK07LiA3bDwYG9"
    b"3JJvX3h9dwcYj0/khFK+dMZL2yIwXIlrfdytmuPOGlpIJVXHC9g8W0tCw4kHV4eLwQMbwK9ZKfB2"
    b"nI1mVbMs3P72CyrSBll+BaVUfBt9tbllja9WBXUPQY8YKmnIZUQBYqoAXA1cCug6UfS08bZZTXfT"
    b"6SJ7VgHPtY5hWYEZmEKuujkvrVRRXe0iHyd8qiB7tqM0Gyb3+DAFRN5A0+cIcWGmE95oq6GnDh3G"
    b"qcUmaUffLIA3rBzBt6K//jV6uRmtRZstxxvau50J0WzV7cy3cDmjBvKk25ngKPiZWjMODmZGAjcl"
    b"wVYrDiDJoaRTVNUkapto2eOq6ugfxku9HvBbeKhQ52luDj9siDyJrcsUozLBHgPbLChMvsGW7UMQ"
    b"TKT8gZZJagi0OWJQJ8ifjukxSRXnUge5dXgH6geGslLPExVvkIKMsW8I8cbI7FKMUIqm23MraFyl"
    b"ptDGWnmN5fdK5l3RjMB8ZNpgV1mWpZ+pzDRFJckp59fK1cYDGpY3LUn8cG/O5q4bllBQSEo1FyKw"
    b"ol1NDG0FRgsVfRc9+hjvegs3j7rR47zlO12BbDOMp8PXtCX3xC+ccdG8yfHdZl504K9hOm222tFk"
    b"FJdXggIi462uPhnDkgGCDSpav0szV2U+V0SxvjuZiFME8VOsf5/n16Mk2hOYFL2LRqKzBO82O/Fk"
    b"sr6XCx6ZlcX6YTw4Oq0G1u9X6lpf2GJVK1iazsahBlSZrut4FtOqjhNzXjb+iPmrk+lzjGIxnqp7"
    b"w06cxpdCH52pF1whsKlKiKiz+2qiUrEnrnGgawN3QYPl8Lr+chQCG7jL6hepx/0Ne+RqZBfu485k"
    b"MMPe0Kd6oLYds86yb4tMsOyVxlVBzzMg6gRrdlt5lscD2LR2adt2Df+f/tGPtunWf9wBal7l645n"
    b"WyiHaTHIhZonmVET/p6mQzHARPDQaZ7Bez7GesTXdpRPkK7gFntuvVO/B6JDB2/VDr6VNC11To6P"
    b"9WN+eOWlDnkOs/fDydFhTxWzR56q/Za1FOydlvUQTEOzs84hAlW17jAje9BsCo8aCEnKaTnmRCWG"
    b"cT0bxVN0mm9YPt9yBVRntsihSQLQWX00YEMS73g6AGasg8KC0DtXQLmnhnJJAO7VdAYRCQnQjMjy"
    b"KKnaPi3mqUqf1AQ9VGZ5VMwm5BugeKgYhGJBGr93cSFGJx+QWHezWOcgFr9vzGNTGdeijSf2exAS"
    b"8C0WKk8Q6aDBaTRW1fqiiLjXx7U1sGGvwc6Cd4g7+LYEmpx/lPaatTV4H18ma8PkcnZ9Dd7E8XAo"
    b"VrTYMTck1bAw5Z0NA5Dla1fptCjX8C0j+zpMruLZqNRhSwY3yeCTgRDDXBvng09rQgEc3MQpq6wM"
    b"7oKj5tNkR4gw6cCUim0OS7cG2vj1FFC7hkEC1mCNynJkTvAgMMwhHwxGM6E0rQnRYihG58ML9WmY"
    b"TEWjVkUDF8/KXBDhg0CH2JgPO2K+iHfwmBb7a02/j1qR3Bzoziwlp8ZVFoiEdHMGF3hyKUVATWEI"
    b"HZFhT72l0YTRmcyKm6agCh05BcHXEFwQh+lqbjwS3OqwnsmdRFZD0yb3FDFVXA+ECeBDMoHTUiB1"
    b"2sToRfy5XFVYFHOxVGBN3AH6hgVagaME/+hICPOKhH/uSM9l84RS810bqtmAnSPmOLiZZZ94nAk9"
    b"go8vHunv+YtHee2OwK35R3n7tMbf8FHUB+s4pwAWTjwBOQTR4NgL5jDOBWiuDzaJPz0iak/xBkAX"
    b"+AIJtLNAH/CVonO8pTJj6paOQzt2HJF+dSARqx2MTQW/VYCLSDbYwSNcReuYt+wOdaAE6+WUHDcP"
    b"t2KcR0qqRtNW8TrcaAcEJtfsO1gsK97BvBu9eCQY/dCna4dEkMKOwaDeehKAHcLGN7GlaqigNKZo"
    b"20eanqh+HER0CAFDmg2sKmjQQZC8h8ETo+eH0RH8DKRkdrZjADHrhWvEq6uRKql+ycAVWurnASz0"
    b"x27U0Dv5ePfnd5aODkNpshG0DM1Y879P4UqkCQ2bUDgOHorZ1VV6D/SA5WbFo8uHSO9MWZmFgvi6"
    b"xRb+Y3SXljcRzvHFozb+KGMaLex3kQrRoeJFqOdgOB/mAOYvAUwlGQqOgaMVPJZN2VLdaZXaxhKw"
    b"f/UWPzVbVqgbvUPoXLgymxli13DSbXqv5kLAtBd8WHuXzbXq776AjgeKuTdlVL1qmXqA6tqQbvHP"
    b"Jbg5HaW8J5ldi4HTMeQAdAhl2lqFYXdUNB7G+XjbPKxS5HWwLP8LtWkiRT3qvSCjITFbsVOnIkAS"
    b"qwAUHaxkwdgBlIyJeZsNxfBTJctHHsrsyEr/RROYqz9cpNcHYVKfA6GYYBPqc9nViMXSC8lVu5BL"
    b"mugAsTcN0ch2nPBcDqmZs8Kjb5eenW2/7ShcYkShB9E+KQILt6ZvaNJbiUWBsnQT3LzpswFA09t8"
    b"+ia5PcvzUbErvt4mx+AYsQKPVkinWaFoXvms5OGu4DNnGCuWhqMbsl5daC2p4ffIw43oQFk7LFBW"
    b"9GVoGFDp7gaCQzQZ6D8iOxjXH73ahhA1KcZ35qEIY7Zsj9pRJAzK2vR6xJjp5BBWnM0l5QoxSYxw"
    b"Gt8xf1L5oFSKpZ1iMkrL5vqH6XcfsnWngQmtkvSfw+bONy4coCKHiIPyGQ3BbF5sM66qB4uF3Ol3"
    b"y1w7R25AsAlNt02eei0Ouf7rh/VhclsClXxYl+fyBxZoivkym9Hp2zmLG9J5TZ0Z2LnNVitsV8uR"
    b"zu8hHjHX9ejsJol8MQQCvGDEGbhzLW5ESVoWcIcxyeEy9yEpO8zI41MbhSj8aqPtcJCW/tCyLCW1"
    b"s3zuDB09wKkBXM9tRAk32wELDpN+jOzoY04xGIMsYB5DCBISVCUaT2qi4btiFclInLk9cDs6E1p1"
    b"UjZL/Gc/u8qLNtglRXEyBP2bR9oBksP9y6A7gkmWYvXokzjaicfQL/VID391QOQnKR8v1pxS9OLc"
    b"2eGdO4/8VDPU+dBVGPS6y3Gya9vK6694fJlez/JZQT5YEVxEFfTmhbopvFswp3V6R/qd+gze2F0p"
    b"FgqMD0ZxUUR7w8lenmUJIV8jdDqDyEh0te+LszDatCC0KJ9X+e3n5PIUOcP+eMKp1P7+739H16P8"
    b"Mh6dWXVYO+qIKlgb5puob4dZZjWlELDjbFWoY7zECRI7taKB4vcsucc1jDbYx0mCJjCpcx7GE31m"
    b"QelIyglFRTlGaoEmme0eLE0oRmAsGz1sNomKQ9c7bBUR+guwGjT6BKjtnVDxOr8Vka6uzLtgIZ9l"
    b"8a3Y5ni9Y5nD+aEmZ+4PoqmIpRXCfcFWnhjvkuFcpWEsKcuRjVkzMCEpCm4vypT3EtSW4aS4nI/h"
    b"TamhlqMqRKwHkJ7N95owsL8/Kmukh6wjpTiagAzDtCg8bCSR0JT4Y+p6Y+/NMVtvoELGmVtsLCiW"
    b"yZXSQYcCB73Sq+ZtZxM7UlBVtF1vsExJ+l0xdUMq4ZMnparKKr7uBRgEu03VnJCSW0ZcmQf1spoO"
    b"lGHsuUusTGELR/CZ4v0qS089B6ucrrQ3giXwFq8uvyWy6suCJn5uLWoG11ZjjVqg9XbQQ0y6sbBB"
    b"exlqGrTwjQzfGTqLTG1ZX7keZGy77IGa64KJzXXoFtsJsmtKujoWrv7WspWhGtmdTVLdwMBk1Rqx"
    b"eNKGfZo4WcFoxLJuJ+WXtlKZ0qctP3zRw5/V4uS6KmFcBm7VHwrhskxCTVjcXIHbXB3dKGSJsTSo"
    b"LwH7lw1cfwC4zbimKhQe5bCdtakJLU8rVN7kQ8cMru3dOoa8AO0f9s5+OHqDof57bxrb3kSkPSzR"
    b"tutAIAQOTZf3atjSqiTksMe5N78w2UjqVi3IqXDXSHu52T24ksgiJRhpEc2iImoSQ2qeXxicKmAN"
    b"h89MChp8Ww+oSDCk6f7Qsg/BPqetQocRv+1k0qA9dFtMNKIGm5LaFGpGCtHkDNnkm+i/nJodgjIU"
    b"KxHWssPNsbnizNQRuvxyy0NAr7Ne30fqcW5YdJ41iSjaGsp2UuGyfpCyGEXJSycNgHb2kW1UdNoo"
    b"dBtmAIUZHtysg62GPEwJzjyEIi2NPmjiBCUtGyZCStA3LEy7siU1WTWgjHDHXHY81Z3s4aAmWl3V"
    b"dmWfrczdV9d8e5j3wVyVMOEjzUeMYftwCmlf6OWzp5x0jo5771ZsU1d4eA5bHRitWfoQofjXCuhH"
    b"EL84+vJLpluG724fwV1dLT0t55zlX9C8xmc/qAHIvy27+dK6lLyhgtd+s0lAMF94LKdDR/1RsIyr"
    b"LMVnPg+nMbzm6RqTxEKTKwsBKcKasUckH1880lLOjVL10ZK8n64dBQZWq4UuO+rPka+EIdrqtkDa"
    b"EMqBQ300/6m639ZqxB+ghNgMy2YQhRhm0wmNqvwcmIhTIRYvwP9nISTkNjDMgPpm+deA7Y7UWO5d"
    b"ZQkcjxwfFh6WUIA9RYexQKU6LXVNxo27MOjhBE4dZlx9zlXZf+iuK3hhGrioEpPsqKO7QXMHtnkm"
    b"LbltFCvNKc3/dK8cVvzbLGswytwdMKXTODvMRk5iim1XZ4ZFBNRuofRzu/aSZHPj89ySeBbKCis4"
    b"epjC8cu9TMm2vZ9dg1vn3igF64Fr2wayM6dmW0Z23x9aJm4BBObD4YSbLqtPXSxXDYEJWv7JStVm"
    b"KHTgMLjNk++ausZYq1+ga+RD7UvngbrYr9qrHhMCLmwBoQK1dZLAhS1oyEArN4IblpcJBANb0IqG"
    b"DLSiM/YtxoeCDLRCr3h2s+IumS5siAMH2ipuZuUwv8sWtqMAQ21geH3eglcZIZALN3gCGH1TAEZh"
    b"rRyovAiMVXC53r4gsVUYNYI3idgpOqSwTZ/n1M8Fc7kPVAs46M4y4xme0haUUm2j5QReMkFNtIeG"
    b"3DFdey9pGvdHoIq0C26XZe7SuBFCzDlcf50/YuH8os1jPUoRmUfoViL064efoIJdVIjDI5MBvXm2"
    b"tuBpoBhJx1LdoqhxQsEzO7Cqb+XEjjL2+Enhp21pNpplqa9q0d3ngJLbQyKHCSENLmuL6lugjxRR"
    b"T66ZEWBJ8PgYUG0IRyisyt7k5IWMb33o6BBkllq3qhtwo//rAidnh4Sy3z8rYPbu2U+H4Uh5ug4k"
    b"x4Dsk44WuCxy9ECVWZR28cfwuxGC9R/vCJ6eFXBOyUPL9ritTSDJ3XJtm97+u+9Peqen/bOT3Xen"
    b"+xA1NJgf0pHS4E5/cHNKZOYdk37SSKOXsiSRTh6MEPlLKYi6eyt2IH3Q9P+oW56rT44ZI8LcumZT"
    b"Ku3SyV6pFRix/3ULC8NBgTMJSRgC30zULcXBBRw+ikdoXZD4Et2UN4nCVKdCAo5LgJVrzIRfkmUC"
    b"YrBSxipkX7oCNfIIPQ8w2F9ehL1MrvKpybFSs2BabAUB0qyW8n3ous4Q1avnfbDH5/IzxTNoqEyK"
    b"NbveKyLPjlXj2VEDqiIXsCVYwBMavjg6uImza/B+IXzSgsO5FLo5p1KWlyykJhDQWa62hxlNFcb1"
    b"aTkSdZOMn1NLKhmeb4EaKZN+bTO8jaIwO2tIHBmkKNsZ7iQbQ5ys/d63K5iLPlSTjF6jomLF+Nei"
    b"OUsuC8dVXFatjO5EgrFFEcQzpd6EpMecXPp9eC/54/5Zr4+Bsn/a6vf15qHj7ftpPgMVwMtOrsDS"
    b"DN9t7VGO7gMxi93j/S55PlRILVaZL7Y8CTVsD2r8eNIFD32pgfTVj1ddaaR6l3onvb7hdKpoNWvV"
    b"fZyxJDHKiEg6kLA82aspUlpzJRwdwZaOyZR9jXJXWqucB+d29OQLxAj/Plhm6VJ0KYeDQqRK4dVY"
    b"YH/XT3dMPlTzzMUkk/ZCjD8Xpegzfq95Y6PKyC8Twi8OVaVBL2fwCA4AcVO9fr9/8MYD0jGoAE79"
    b"eAJnp04EtsigIv6wg25Vz0Sr65Nk6CWo4OGj1H4Ti5jfvea1/ICtvJ6pGYoeyEbCiqFFv1ZlYJ5l"
    b"MCT2DLykHMLbI55IUc/fR1QIQzAyZFhAl1UAgIzlRqUl8zjTwjmLn1bq3JP2Bh/MplN6KV99Jjsy"
    b"0OIj+Zmnr2KlckxBmccvqxZ6ArC/T+rJ4tv0Gg/K4Qw4cKXAo7zHJU+wdQpc6vl2ZR4EWoh6xaQS"
    b"h5Wcznd5eN7JQe/p0QwuGV31GeIlbai0kv+kOvG1hRod4Q82m5O+McLez7Szs/HQVZ90rAeoMIqL"
    b"8kxhkrnb/uffmzzHem+ivgTM+LrwcW7+9tSc4KeA7sOiwvwZ1v5VZe7ncoK72i3rIs2PFhWD8lOp"
    b"FjU8V5BnP7ZQLxjTTNmV2OHikii86nVc9Clie9XknjA1nYEiKN4EdoszkqqnT55y6BkPPGmTGxK0"
    b"OsJZhdIjDMNY4mkURm9PK3ShP3c72AMzJ7VP/CaAoRx9YB+EsOT2RNGEZEeimnOCLqKjmrPLV2or"
    b"DrFl6VGZHuRJrKRvFRfooVHhdRc9djodNZq2JKGumul8sS6xSkcsxAdykhX5FsigUuGeEKzwT3uS"
    b"ZY2h8lWOOfq5+CsxLQMbci/6ygA6T7nOtDNxHGfXzUu0bjtJTFalzTst6A8NJcU/+qlTi0UvX4ZL"
    b"vsWAJG9Pdg97FIfEBNskuGJ2GaPdfQNCcXYEJxBCeyhZx/nG/Td/b0cb97BOG/evEvzv3+C/G0P8"
    b"bwz/3Yzp7wsnGKjszn2O2Y42tyhWLtHYD29OGiuBZBBWgIG7dFjedFWTIJm938/Kl1uve03RkowY"
    b"mKTXN2UYaGsjFP8PM5daq7E4zanKSypr2XlGq9Ksn1K8Jry8DedrawutNIOwK6fAmUHd3Yk27Ddy"
    b"WXoleqpN4karfrj7bv9tTyjUOoubvDeE/mvrN0YQbarsTMAoyCpCiCQ/4xsfUhsvYUxIbBN5HCub"
    b"yOOQ/MYPMh4Iwy3xgH8T7iFlDCIfA5Xb6Uh5vASZF0t0u3z4bAJ39GwreHYwYK3sRY4VH/FKZ3nY"
    b"hKe7b3v9/Xdnve97Jy27J1UFEnS4K1/bFyKwLXZ/293nVmhvFTSZhfSWHSMuTbhsD4PqevdhlMdD"
    b"a9H5Q21NS/4wTCOkejyJcJxrPhwzcQqnhNpuVQx/KCg6K6TSpPmunFTLIpRVBisRaL50kPFQnpyv"
    b"NwLlxHQI4JUO4Ss74rGa2eopKMl/1KgYGJUs5IpuQjolGXbF2iovYqKprkN2bTaArtWpdEfOrvuU"
    b"jamrJ+PmaWoEWCqaac6UiwlSipf+eIkUx09iDlk8KW7yspY96OeFf15W4WBo6+U4hdWRml8wMaku"
    b"5AnndaqXUJhxVUP3svCq3amHOYXkjTv31zrAowPPuOPZeOJ5bIETZM1zZPSR3EFXSeZvlQrsTcUA"
    b"rJfE7KNgY8R6AHcnP+0e2K+JB6Mcno3qmvRbVJJew8Z4Yb1uJefiKX+FrD6Jusb3OPzA2H6OnGZv"
    b"R8girDeu9GpAyKynQlzdhcI1odpA1O6HAABIIPp62Cnj8oJTvFuWyXgi9kNVfQ1Q0QgsHxrHbhMZ"
    b"+qtwINTsQj0oX20HIf5jauV5l50oU45Cu/5kluyROcwKSXaclnQWcbfZ2lcHCG1+4091Ku6oVwYW"
    b"5hfAWjjQsE2LLL74oqKydrTG705eNBdDhsiwMVbSB+41nEF8WusFgXqJRM+aDFD4TROg2SZa9aFU"
    b"xL/KBxKOdDeKIdHOIQiY4/heLcaG5QbFtvCaGcLgkxjZmrs5WtxsZlGWtVudhwAVJKjwNZzGQvZV"
    b"tp42DbvlOOwpqCdgayF+iPzs1X8iHzHPy0J7kNPZAoawDChjDRLciKmKFVB4Rrl3zbjDsRxtY1nI"
    b"2w69+mlTczuO55uWf2q57wIcjulPsI5/Vs4vzLE51TpwtYwz8OiystKXQqysCNDjWHIMop0L34Ut"
    b"uzG5gg8uFCemdWnLJWirbtuVHS3zDGN9PZJ8Pr8sBF8Ap9JBnIEh5VIoDZ/IN0tsi1GydkW7YCJE"
    b"jI5jD6s5b+uPqyomOg+/zKh67Fm5gTXjoCcmzrMTU1BzeM6NoKXF6714iIT6WSSt54lKZLS0pDP9"
    b"SdQFBz8Grb3GrQr8q6jzlV0Htlyd/FMpPNUIXv4acXEiyW6TUT5JbKfrGxqD1Nm4mcwRl1V1JjG3"
    b"gn0/Ksg2Nu56i5cpHofuYyBV3z18QkKDSgZ3F+RW0govzc6OPILTXeXiECyCfe9GQaLhhYVs4zuH"
    b"KLrespv9AKPyjvroH7rZ6vmEnzEuPCr94HRVR4/CgSaE55xCkmY5Pp9+mGjGoee8o5tsVfObgAAY"
    b"uDdgiA0cAdVbqOp9mAxvvzsS3L85SYdMz3cD3gUyO9VlelCB8z+loxFV3qgQc5+VIJtaPwXzv85q"
    b"j734LPTJsyGeJQlulmW2VgkhjiEfBaqV6gczwnE2OSnQdAuGO0y+MSka23XRP6k3JX5P9DOE88ba"
    b"pNFWwURgndpRYw3cYBojvALZaei7NUPX4qDJgc66Mm23uX0TMj5xw2709avorxi2kd1o0inXjbYE"
    b"W7foMPDUQd1Dyd/SVw640IaDUL2mchq6xlB0ZucClNEf1a9pMhlBJNT1D8WX69di0pGB1HGWv9lY"
    b"IpEHjSSQZ/hA7OIjCE3P85CGDE8V5q+oPiEnT6zJs16quvIbrmVfXW8jsEw8SvTuAaj6vrmNwvNT"
    b"chfXOrWs1WzZ9JQS/DnZKesMb8FkcrUVapLQyXpe6gOqidhyxmQZ7cILYIf+sZAcrqCvAncEvYY7"
    b"ClFCXT8heKsbbfNzeP9Ikfx+cQDsHzMzVDJQZ5cgcOAAUPEX1LgNKyR8KGbNcqtYTNy0EcOZ5DeA"
    b"RxWrjb/1FZZ02xjp+XTwUAMlP1CkyaW1REJwZ/zaG1idPro7+zpcv7wDn7ZFlRn98jZCfEjWCJOl"
    b"pBCr1TCINy1wVV2iaXdCplqotyoSjAcoOCJJFTfpBKbG7jZX3OuSSqc6qQiFb0gPjvZ+7L/ZP+nt"
    b"nR2d/MJWRTMjbqc2/Omj+rH24rGx0YBjCF7PYkB/d2mPU+6VZ77xFEJiXT/vFllIk7rr51GlnoZd"
    b"mYJ/+YNdtdur9OiQVcl5wyAiFPbS7L9SJiTSziTTOBvm49fyck5d/7OvrebWqxa7AZO3/apBymKj"
    b"3sHaZ2LXORBlDB/M5Ft7iydv4tJhN+K451vN2RpddxXbbH/1qSW9DLzIa8ZCPoEakaSLCwAGgSbg"
    b"ZP/0SKKlpfKBYGinEb0VAjMiGr/0j39E35gfYIcKRSYi8rkqJp3xJ8irBbuyHT2O82HSjTbyv21s"
    b"VAUIUe52+Tgd/DxNywTvnM12ppYaxGJ+KyCyqkxU5duqKoK16aQzH188QnNzmc5BbO6S0hE5kSqZ"
    b"S7+ZmMAxOITQeFg+iADkuClTbEAklsFMENatetQMyPZjpnDhVQYy6TkRQaKQL9fcUZFFVczCSszW"
    b"DWnjzi3sgq/v/ResgXYE4OqvlWnBlRxkT1bCZMtRHjc6mjGkUBYEEzsDgdg2qwQNn2SsNuNiwRYW"
    b"+pi4FaofwKgo775CH1hEi1zVtxDBVpKoqlRNpAriCWQatFTUWoujivl6IaPkaDqK3eO/bqFi3fiv"
    b"HQZTwSz5HIs5TvZ6/7N/WuUtmfAd8jgPM7HPsocMEqF6z0UkMujrhN9MBNjVtfO6YC1qmjXHfJs4"
    b"klarMwYpSdn47P5VvkyfBwH6oI9vxSgw94f4+x/R1lcbrQDXrHQbdaieuZVblMGWjBp09RaJdiOj"
    b"1DrMx1le3gjqwRhPeAQCGRVoPFOyp++2K32jyniU8C2JH/R+FH/IE9JszdAx521SbManAILxSAAw"
    b"cd7ovTsC5962JtyLjnysWvCKlCqsFUAwYYaBht8JSC6BQ1ySRcyrPHAH+Ww0pOyfJPg7q0BKgOeC"
    b"Szz6DKTCZlg7lRq0I0hjjYosfJJbhGo0HcnzCSbAJQ17NeZBZvGL73NpAdppT67hv9LW1x7Qc+Tn"
    b"G/2Uza/a9PfyM5n+VEBOiY/8DjNxXQSiiWaYP7XGNujkgnEDGOPzUJnjpYM/mjwlS/HX5ofhl60P"
    b"xZfm39MvxT/yv0P53678f/qFcJ2/tl6sB18pYDf+5oJpUuBRFswVJHmZqgarnW9esEw5sMBO+RYv"
    b"d6V9Anl5EbSNtpnoi5Si4F9dqDUNxkoRw15sQj2/qDChyncC2hwvWEU+HVZbUqlcGRTo1/Ntk7L+"
    b"M42TsnaFddIzGkrwkNXQMUxKSFTAt5YyZaoa1zVVTKuIIVbFsSmqEkpfFTQjonCSFruXRT6alUnT"
    b"rtIKN7iEeTIIuZRhkmq65OSZhigpKbHpq/S67ST+Usp6wGYUuhFykruGFqzSoOFn4BmmQ57+KIqj"
    b"4/03rknjc5iA5CZ6ihnDbJGuRF2n2ilZAtj2DWYIQbZmULZieJnz0WVgjqmJYV2Jcdpqopb0afYM"
    b"Y7WuYExPWE5uo5Lv2s1iLrJdcFOkylRKHAXferTlGnJLL32xxSB87i+ngnFL5DzqLfaVc7e4uTYn"
    b"AqpVbnAQdP3k3jZ74IZQpAq7ckUOaM4+eQvjBI4/dP8PyHwtlV0KlmvnWziuiOU5LJDZ+MRhM0TR"
    b"TbYsWsiGVn2neuo8NJAN1LE0VUignYCRIViNPxSgRVAppeRQixweHuFQV6RQ0ZHHuZH0nSUzB0QI"
    b"2FogekfyncZ5F0fhM2OB8HGaid3wRu0K9lJb7g/+DB5W7ysZI6yS9VI17mqpHFuACe+odjv0WzBB"
    b"+SHA9xSo/MByTmFXXAhhWbw7kCZ3T8UlgBpuqF4CQ++Fxun+92e9k8NGTbBeLkjZXJ60XdyxOnew"
    b"m1rYEP7CXc5fjytSoUM16ILM1E9tOYdJ8YsJ+N1qrlmCh6Oje/aeSltPwFFFcWSGCY7TpSMj8DDC"
    b"+n6rHllK3pDbIhj4ADeCbaswWQOX7UEhwJ3jj/sHB3YQTsD2m4qZvtR+dHyaz5ioM1Xep3RXD0x4"
    b"HpTFIBT8Eev/BHu2TjVkLPw6Dtl97avFwEEYUqArTWq6B8t8hvs7bEcO7Q5j4ZhlAjWfTKu/31XJ"
    b"l2lHcTom5BkeylFSlcT62cgkF2+SJDhqNe9cAqdhC6pjP0XxXxqkwg8hHAlrKtEQFLBmGYzIvgN8"
    b"vjBX25Uny8lYdDI4wbFSmxjeCYOWIhJFH1HIkYfxmhZwjFiN+To1V3G0Mh4L6FipXctORzUCAaFm"
    b"ZSFmF6lABUWZT3WmKDO7a2AgJ2SJocuhWmlLyRN1IpeanHua6a6aJh+nc2axfFzx9JMy51vpuPC7"
    b"T67GdmI2hYXYdnR8cgS7oX+4e/Kjlrd1PR2CdplsXMuugzZj1qZx5JGmkATluh/iXJs05TbNDF5u"
    b"orHY0czZDRrBM5bnGChsMOtyyrF8LApEtdy8rX3F57z65AN1yTGgQwGSGxtJMDyM9ByuE2vRoooC"
    b"IGVvVSraPBQENxAnCGbKSP93z0hZE0BobThGdub2tNRZzSnjOVzTCXki76m9xLh0ZHo2QpvMpQel"
    b"JKF3+kXgH+N3+V/hI8nmio26J4dbff7xM3hXLuH0WGWLu46nl+IM2ctHEG9HLl8RMMaR1PX9cu5a"
    b"AnKaJiakJt2IxUNwGuHE+niXljfwIv3sYZIU/JaJXR1AYw9wdyBbDbwqXUWYTlqIVjGe5EOTcU9V"
    b"ePowvsxH6eAAREFWvrr+q7VK3jpsbn2jF4Iay5CWnR6yqkX3kCfTe7s3C1ImFkp9Cm/mK+VBNoZt"
    b"lu6SrnO3Fx+4EtJaHro11n1rzbDqdDYj03UqzmMuwFcewFVxx9QSqTFXrTErr1zmmoOYYbRmZZYy"
    b"oGl0qEtiTN0VlMBcE9CSRiAaoTtE6zqXrckSV7rhlyMJeJwdkqwpsRbgC9o2X2eQt9D3dHHbs2Ib"
    b"cdtVKGtoW8lVVqq4etnTjHMpkdPkPNj+swnYliS1CLlY3LuawSNOsXqRvGmE2K6zTAaftYXAUGzX"
    b"pfaEZU3+A3fEwliDAa2qKMFcJoQPsUNCkqTcUZoAltlPyyjVq5ZS7UUx9b0tzQg8h0sDOrgRhQYU"
    b"YRhI9S1GPYH/p66flr0Q4pcrcibbwRtsym2E+SuVoEljeI5kKkgRnkU+TSzVT3pYvBw7Rs7vkFaD"
    b"cXC8VbChjZe8gdXfQk9Y5LTJLHRJqGosGWJnozrETvV1ceyuHBeG+PJpN64yWWRQ232zt3t61j89"
    b"2z3r2SY1PT1tF3QPGZUnyjk0dL+ezXIx9WmzGsvqYwZiTI9h+SnspE3Hnh6VFukC7bKWXbdAK102"
    b"K6rmYhaYrc2qdxlpmWI23D+TrZi4W1K3l3igH2YLLr56DvNStvxygpwryU8hAr+DJhZSeDsyu0iO"
    b"nBO9osn/BEb/EHQ+YefKzG0c3XIb2aE+rxOdCKCpkHpp4V0i0CEVOTOZ5mPe5p4d5m5RMp+bmPbW"
    b"owy4iVYmk0uB0KN77eu27YF0LGwacDMyB95eC4wI0hdLKQA3Nz7XesNq9GfTkS5WH6h4HN/3b5LR"
    b"KO9jSL1u9NXmlinJkutc7IASfRcpEpFYW6Fdm7BEW4rW4Vf/Nk3uwMz812ir1TLt6GSJqhfgtaZY"
    b"1uoGWpLSha6vd8cm9ymR9eiiT73vb2S5IJtGyPSAvP0HUayvLBR1tH00M2leu0xBrNo+OhIN+p8S"
    b"cimQFd0iv/KVGGEynYgNVXoVWZnUAzy5mMkEFHdXEfYwTyhqLrldemknrJiHUdTpdIjw7dRh5KdK"
    b"uNPpdPJ83EcHIhqq/G0Vi7na5eKDTojpTK1bNWergkFitwK5Nvg0vRWbp//b3aeuu1KmyM6L2YeE"
    b"MZfxQNSA8M+a/qyyuVOH8NhHkZfRrFcWrgYsraIWFJkMRqP4Afap2BbnZmjms/YznpaDPpV2uUf6"
    b"IDmlEECQ7pHaaRTlLOvCfzqjznWeX48S0NO6m39/ubHVmGtHVDNwhzlsbbz6RidmnOZlPshHZktu"
    b"8WydDrk5xFbNdiZJMuWkJn+zQql4msnCEovJbSDsbxA9aWzSR+ZTUfbq1cs2Mw8I4HWTkBRUQyez"
    b"5TC5nF13Tay1z4veFYZkH4ubVHAHe1iQ4CS+TEfonScR4hb4wUPhObXYvUk8PkX3b8gqCCG29flJ"
    b"XuH8BMSMO3gEAqM5TcqmjCCaX12BgwIoPCr7X3aNMS5A9Rb/wq0E/44yLkUN1aky9FhQAKeuIJKL"
    b"Sn+DUhg4PvHfUdf0rl2HFACQUp8SD2KSHNYBcH4cXMvpmE/ACwGLXXZ5DVoGOobE/poB13IUJZWp"
    b"icGgtvSNioShZ8RBZJkmryXOeLw+E/gAG1vjqcJahfAKxx/RR1BwlVYXfGhMk4Bv6fA6OaXVYuJT"
    b"fPVnS7E0kr5cNTYuqzj85lfOjErNNJWbWpvTg9ShLbrccTOtRQ7lmvgnW69aerXNVvqzCGsp0Uqy"
    b"VDjJZJP6i87V1TYBt/syv7aEZd8caLZFNTTftjZ0PBOahFj+QT9UL1jqtCBP0lB1v8gdaz6bDhJx"
    b"IMUjOBzUaPlXGRj4U0OgHv8RCzoSO0jFh0Zy8FrgXxe0IPegbuK8gb6pkqtSDqU2mK+up/GQ7FdF"
    b"mU8mAMCemdmZ1+xGpUD5XbgUxmNaN7ThzIl9kzMSlEJzwj88QmdSpUJLSEyHFuRfogk6yRVqUObR"
    b"iFHGOMi3gDlN0BqXWT9xLOLfS3jMJz/JUZGxzmBMIYN14u0yXli1oQkGOq7f1C4cbuyvKro0YO7m"
    b"pnI96Yo+HXII1aH+PdoIgbq9l3kZj+rniSC1U0QId3ZDvG5hmyEdjgJCiPwlFrhyC1gtubO0CmFJ"
    b"qRs+BKT32gX1ACtYtQfn8etkmMbEoOp79AArevTg3B71lWO/pMv8ZjCxuGzOgW5pYfg71FCU5FgB"
    b"fWE5r8msRGQA+1Ys8A2yQsHUplejewqvBX+wdSV7kcnQKBj0tGyaD+Atv8LShZE9hRlf6raGDVxn"
    b"83ZpyK5pcGtsFksOwa/wlGH4tc1QdODIZYfiV3jKUPzaZiiErVhFRX7a8vjVnr5QfhvVg4Ngk90o"
    b"nAWkfnw3FMM8ajQWjQIhTaIJKq7r2GrH9ONtfgNgTqyGJe8siXsH+ikod6oaTCvZavE8GWTFRBmE"
    b"N9OAzVZlVHVLTN7VGvttHZ78Ck9BlV/bYAt1alcZoafe1ivP76wyKwwjw8kfZeZHezlY+N+fKhM/"
    b"aIY1N9krjqcwjw+2/1NPqI693UO7SXKUWmjggH4r7yapG/fOhjRa99rQyTMdcKWy8j5J/KsoIl9t"
    b"bsnn/OxiUcIIwSoZPAzUC2CS8FnKXwhPADKyJksTupNgF7Uob6/Sf1FqelVZqxWm/jmpEiQnU4Ck"
    b"hi8h6+ZbvDGpgtRcdK6vR7smh6wkAuW5gv4nxQ0GoZDaR5RnoweK/aFPko5tUzSKSsBj4BDVvd2s"
    b"EEru/5sls2Rf8Fr76tbcyz3HhSDGpn0PAiHeJYIylddrTbqdP99hQDOVHUzUKH+EPAVodjXRLQmA"
    b"nk4WP6flTbMBb0rp89rtVqdRkxOHN4EZcIAvHu6+e7970N99d/pz70Qm2wsNjSG4ZnwMij1tf/WN"
    b"gpIMOS3ewg5JKPMu5rZqeg20DBepJjJpRfuMFObSVVwszuCkfVRwNP9xD5VagjsXGxiYuHTEmSa/"
    b"eVqcbIUs1VWsHHj0bJzwxSjq/B1V2u0VSrbJ0/XY+aCVt1+lN4ok2ZPe2fuTd04gS7B5g0tfYfuh"
    b"4Kege7Xu7nc+7+Jz2g4n2lYz/D9gjGjvh1F1rkZxeRhPmuQO7TyElUFcoEwGcVn/Ve725ofh4+bW"
    b"vPUBj7wX6/ZNI9UU2uFjhskujCDlBl2ZX8jHzuAXphRFsTnHyqnQkbyg6GlJwKwa0bcWrla0Ntkc"
    b"JVdCm55SJgCBCPhtqq1Rif7QMjLWyy3XBx6HL3gXoboVECs8fyd1/aToQW3qjwS/9uJRCmjWbFqC"
    b"ew0xFkUTUoI2NhqtOa7HRyvjjxe4P7lPi5Ji3ge8omh4TiQ07RgV4H+qOcMC7VG2gkG35CtPgwMz"
    b"eaqPDt6tDu4JO3eVyZrLNrLV5/ZKVTCzeb1rO8os47RAP1spA44F45YxycZ5lpd5JsQYXFxaavFd"
    b"ZSlgDqlWTp/H/FNX6hgRcfUu2DFFE425eQNABLMrz+GKhD8O0OJ3eEG8mod3Vefwl095kveEiXrP"
    b"BawJ6SfTNRKdHjqvycMsKa4vSZcThpqP62ttRYZzElvIw6MDbgHonazH1GhbMfaWuN6SuwBrd60J"
    b"SNnIxNxbMvHPsRgbXEhjjh8pYzPijAfTvCggtts6bIXknp4hQ0Lsjm4GkwQ5O2SlOhQs5xJqLMtc"
    b"/y2JIXNa2Nze0rq7USCRCNwlGAEDVF8tYRj3CiLKQG1m1mzEg0ECZpoGszJa4dBYTWoSjRS6uxZb"
    b"bRMW7PzXeO1faxfr12mbGTTs1AniPFFjXVJhN7TymbgrP6pQcmnWiS4tx76rRIn1X+XhRaKCkhTI"
    b"yMNe70hzrheFjgI8aruHEFY0jta+fsVOleVmTXEdK2YsWfaCE4UporbEFbQ1KHJhwuMwgYNC1KH3"
    b"diq0gNxlhdjH5TF5LJlnJ8xQwWKz4N4RTSCbFPDGV5InjK83Wrw+OjoT23T3WFltNr9WRgv7DfkN"
    b"c5iLtAIQvM1bof1D/SdCSJ8mlrud73HAHe5WaKN5uaitAcgjosmcgPZ/j3ue1cCTXPRWgm562v3O"
    b"8dKzHkCzl8JW2h/l/ORnQ/D6ye/QTCQxql8pp+QKGI/0E5k5J5tyCq9Hp9LhZ/dS7L09/bXJFv2R"
    b"1ndOCy4BgiHzOVU/I24+TtUqhL2nY5G5CLF3EYuB77fzZNQtF/1+FItdfuNOHGOP6iCkJuQHRkDW"
    b"SRWYWAfF5pUdJcOBbyr6xPvpyPquPFbkYO2GZOGhkE3LfBouPFGhRnjZYOiOSYo74a+n4v/FTt0f"
    b"WkMTSL9OSqfGlc5kbH/XF1bOd2mK5C8dKAGmYNw9snlb8NpG6CbfxcZuZuVQLHOoDHg3plk+omSJ"
    b"w6WArBx6FsTu4FOW342S4fWCpjig1xxP/QjAbt5L1ZKVHLyquz16hFdV/INC3W7pFpFO53/X3Z6I"
    b"Q8Uv5pL6YoiqcZ0hHf1EZ5ogM7sVorJ9CmfhkokUbitKvYcDREjsFVIOZColOW0HIRs7kqWditbQ"
    b"qonCZRGqkQmNFmfYaCcGvts0QPibmJNKdig25ncdmTdzW13LyCBEQrYQ6mYP01CSJAMDauLzBgtM"
    b"BjgLAin/uALa6ggpoSGYmdBoTOtVYOjpWQkIICqgWFsPIgSyjzGzgxDUGwjY46TpZUlR2cULIAdK"
    b"hGxlL7biVT33VLEiWO1biQpCR42N3HkbQ7AjifFgT95pIGW/QO6d0GPrqFprMkphp9Phk2GacL1v"
    b"pclncsz9sA2OTABkXLBQSGo8avevUK5Ihk0rcp0SShcG3wosxeJ2q4NjPBGRvPdlp2bOcSXTVTzI"
    b"rxtL286soImhYz0qeM7wPPZn9IPFjzUXN2+0hNeU7CTLp2O4gEx+KMtJAR+bXJCGp+9CAUbxGP5W"
    b"71QsyUdZQF88qobnf7nd2fpC0ezOi0cMr568P9kXx90kzwSZNh3CbqlX7DRE9aJciG5pgUYQRX6y"
    b"nnYRNk8wPbGLxD+1mCzqJvYj0DRODhBEvXgvzHttNsN2xTq3/A0NzDBHZ7hrgVl0hzN/TdJJYmLP"
    b"A32UMaRhZg7Qo7gUevWY3n/epdnLLRaJPslu6Q2MAhcf5qGtbaFQcH5xDIBuEE/EsZi85p+bNs5s"
    b"RBoRdUx/qSWwK7XtnoJtyKRBUqWXfhHymCNTmV3txIm1Fw8SJ9BUZbTrqp3r0ke1GdKKnbx4mwc2"
    b"unZwi5Ry1lY47DqYWZonW298T5XPwyMztYnTwnK+VPZZy41dP5hhXuXMpcbxIbdKLMdtq6TCN9yC"
    b"CXl/283bLt7c89rz3rYLXcds5pfNJ6uLba9g3w1xwy4IucJVgpC/VMNp2/3quXdtuFhwKoRcFXWd"
    b"kPOgLnzim9hnvIrV3k/SlW7OD3v3IcuSJ6u9VztMprF2AL9SpxV/2nbi4ZfxvewULjH1Y1VodDbp"
    b"SyiBD1EwLND0trHhmmAB9M0ysXidOkcmsM8iXsFrC44zyVMW5BX+8zafvkluz/J8VOxi6JVj0F5W"
    b"gnxtmozjFKwrh+lolMq5NZ2JtJgtnw12aSyTzSK5i/aGkz3Jm8zl18e7oru+vrn1t86G+N/NLggK"
    b"NKsOvAqcs98FvBIo4SZj/jEoSDctG4/oWOFVKG2P85YrEnvJWw4L9n6a2fsXtNsxJCQ+nBzv9c/2"
    b"D3tH78/6h6f8Ikm/xt5sL4l55kcdOuT9k1GMrQMMXS1B21m05dYLVT7UZoXMYmfBk+/7pJZNapQx"
    b"1UFSooFe4gibGDbUwT6vHLba/0O4shB8pSibDTIvCD5TvpHiH30Bp5lHJRGq2EC/k0TpdWVJspi7"
    b"m36iWzJwa0CrGhutZn5MUrQ1Fldpe9qOs6jbnpshrNprumAmIm0zVFPuyE9WObceasBCfZRYVbZE"
    b"DUBfbFKSS6lMQlf5nrSuQ3QtOBxLDHprUxnXciUIa8HcPVcAqD8pmE5pjWC4uPZMaDU8urBYWSXW"
    b"8RxpjpHLzurn7g4VKgucYAu6b8ji2/Q6Ltkm0Ve6rRocvgHH2vxhAQb9mQWR0bKUl4VDdjZ11XhP"
    b"6HTvJPdoJ82zPbL5FXtCkCaPsmbfjBDcjiRlefymMISIOSFt6mz51kQWbH/JUXGE/pnDIi1N3UFN"
    b"GPOx/BiUiGOCRZiH8otDr7StW7PWslxR5voxY+vknwI3aIw01IW6H9RCxd8cjfYN86EkqwLRN/mw"
    b"rcPsgAfZlWCCNsJdnw+81w1gymptiQy3TtJVUksZd5CfmDufOOP6h72zH47e9N/u7h/03jRs+FWL"
    b"KZgD3E0dW0Ub1gyNPZrnF6zJZTtHI2Zk3+eIxTqI4Sb/rfqq5iwvwqeWQ6GHYbZuzQYCi22C/xoM"
    b"+0dWnp2gy0UTIdvSAaMdBVKcmtx4lo+HDRQtvMTBjgJuZZV15b2OrHcTb331tV1r0T2Pu2D823zR"
    b"BNUFBvpIzyaC3STgLN8KtFU5DkgoXZtEuLLmtzvR25Pdwx5S8fuTXv9g/3D/zKZlQc02pVqJeO3F"
    b"cY4Oq0zuIucb+u4g4yACVHKJzDdNSeOT4eih4VXsyoqa42ALRWWdViu8MkHbmXXnKSakb9P2YtAB"
    b"tGk4yW6TkZC2YedYW0Q30GhroJYvuP9JejG9Q1mG6/P8KUbIt0J/VpwVnrFPAr/FpWxanqkWf2xV"
    b"RxSVsqUTil6dJRmEMmUathy9jjTFiNbPaI7uRVy+dU/vbXYNU3GVzt2ZyIwrYUAJaztdeGmBFqGT"
    b"Z2tCB7lltRJHM6nQTmo0FKOpCiUY81EZ9bjFgZzt76jUaO8L2zBsoKX9MLW4DeHibBHWBsPYNa+Z"
    b"4CLDy4UYwBMWxKhNelFsvamCXAx04ZOXVqAMFNegtBzGGpEvEdn8WoG09NMEnfFr5clKqfL3yZYe"
    b"ZhfjVs8SBx04+pcSO5WvrC9/VvH9qMYVYXkJYM55DzCmtSoHCXHoOsm+Kz0pRDsuMyDKMK9TQvYS"
    b"8f/KTvJkZoNPnfCmHm5le/CL2uIEIwfBlGU0e51fVLCc0FbDxabeRFX8w6ioq/Uqak0MakYTVYcH"
    b"P/LDqegRE1IiZlevgtovR0QCHBuhS6aono9VejQ9iykJTNJghVxpy7/y+UywKxuhVM9EK3aPhu1l"
    b"Rl8rf1c5aFVJ3lp96RSzy3EqdYjQKlZqdstgTql7npK3+/ro5KzfOznxA4ibpyfkvk/YJ19VemE3"
    b"iLPoMhH/V94lCbyvytKrBNJHaXIoOgs4h+O/VcE2PC8vi2fYdL0gwrLD+EMeyGe9g55QfE9+cbNB"
    b"wf98I52Rf98BYDWJDNlyoLMfb1rBPx21xXnd+G21M16NRqMuWZSU7xQ/SXRZyp/HfVHhhPh24bJ4"
    b"UtzkpYaTvy2wua2lApL9577/PD16J8NgpVcPTa2y4NNffFnmTb3OudEe9rZTUytHamvr7mzIefjg"
    b"rtzvy9LY8/c87vpTCKNnNERIHocG+Xi0Hd2mwyTXj9iKToWaaTJpKUyU6eCTUZJq1TNno9S59/NN"
    b"YXhLwPlTsJfNjY2AfbvSWdRiNDUOo1JOqXgAvMwhyr+wh8GL+n76WVrBirn3LeHJ48O2g66FGt/t"
    b"2TbYSFldurZrrlwR++Kp8pzu3awEN1Po4ue+jFuKpRl25iHDAnPdISoFjUAtcpUIChltn85UQEr5"
    b"M/CIbznpYdXgV7AT1+bgvmV16yxvTTfr5AyATc00K1Gi3sTpIIr2EenBW5EAlhBRLYpZZJitbG97"
    b"USNSTgwubY1Mb+9h7SYflqOYF73N1+DNR0whS1l0GWsPyTgOT6Uc1uxSpIPZM9Lik3IJtZXwRTIf"
    b"z3v2dLkvnBjAqsgeHz9T8gvl8WCptnQuD44EXb79XyEezKv2ph6zHW7D0EAorJS1W00LPAxWsAEF"
    b"YNW3lzkwnm+r3LvMy7u6kYS9yThFVDAOwFRoODvVkSIW2IX0UMTpVGLYItVocn8Tz4rStgbYcian"
    b"Lmajd+jSvvcJyi4h6SWI+C9VJPFKBD93X9nkGFzzWgoMGRXjyWSUMlu0xQp1E4448SQ9aUktyYgJ"
    b"/sQcfCqPxzrEzp9jrFTIWIqB23Wea+B0ibuakr1HBHr6vMbTT7elsfPUE24eJaMicVlnOJSfO/hQ"
    b"UD8LdMP+WRfsT3Epi3/K+Fa1DDeYsyvEfuv5/tKc2L1hrW92x+fS4aOmsqkn8XvO8au5f8VLl8/K"
    b"c59AJXXT/v1cmLVeGeN0KUm5pqGbpaRl1oAn/NeL8nVtuH27Urx7Z1px+/0Ue0D1Tbg9RP6VX4c/"
    b"zz4Qui+QeTRr5euwdL13dHi4++6NL1VbMnW14mfC08kxmAB1KhDiQIWoe0qGbzsKIv3PhcMWVfbQ"
    b"pUPU2dWWDVVn11omqaJdgxBADPoqH4gDzYZzDhk9q6cELnMQYhuenQfeFdyw+k4PU6gKLkg/PfGq"
    b"8lr8d0g44Xfp7vz+q+5j3uURrm4k0Qe2WQizJER+SCZBST+ChthilCST5tZXjpeGCX5lXour7s2X"
    b"+mCA1CA9ISdZcZU3xj293IbxatT0cJWKhkY67i140ern1OyhtQrNoy7QrGfpNCblyACDscdXFWPL"
    b"C9BgWzFDkbdUlT/JtuiO0BBmO3ppXuosis8lHyREgmSm0Jz01y/gedtNLk6sGBwBOoHgW24EAGPk"
    b"n47FypXJm2QIF4TmEbXtOEXPHVlUq8fBDSY4dF9a0qvHrl1vziJfhd84guF60atkIA6rWTdsk8BG"
    b"fouPINUsCM460awW5DNZd0OpNNoV9LZUCvFnpBF/wrlKndPwkQe5L0C/k2XWAfDMPOJVh8EzMmRX"
    b"sGNN7XNnJdxptTS27e9N83jeivkABHGQCh4r4CqCUiysFA5RYaq5FSoCVtRWCISvmAdCgcFub4rj"
    b"8xYifsrW4KcMZ7YlIzxhtCBN89on0FAxoFaGT1XNSPGo6GTiWOsUk1EqTvhOo3W+IeSqf0RbWzVZ"
    b"1t9Bld8KARSJgyGD17xwvMFJh3myQ+njIVbyEAOXij/M83aYjQRvPpo5zBXkkDED+tAZ63NYRytP"
    b"1lR4jobLJJYLjWbgFwQek2Ngl/3bK5aP+oafWT4U0M0OertRf2y7Aeer5X4Z2u2pYr8bzo1V0IHd"
    b"luBS+29678723+73TihSny9DUzYGm0ut/3q+u/a/8dq/Ntb+3l+7eNz8us1SOrgytZXPIcynnp16"
    b"wPEhXSos5R9lU7Sz1blZthyocNI6RzElKJOuzrjKUxeS8dmeK+Gn+ibVp84V56ktXuo4UFy+aa24"
    b"Pvc+5IrrXe/0WxUoYFG4gEVBA5YPHbBkAIElwggsEUygIqRABUXUBxZYEF5g6SADy4UaqAs4sCjs"
    b"QG3wgSVCECwRiKAyHEFgEUMxCJyGZMyBIoZT6V/JkA5LYuY25NLBWX1t2RelyCreC6gPb3IM55jc"
    b"T4QeYLyQ8X1AOirwXJ9d30CMGDHKkBrBJCWAQCNZ8yNkFB1G5V2aScLlEQ+70YvHIArmH7KP9qm3"
    b"qcUecaTPRvAOEh7ZqygiPr+1s6uD9YPeDGHUafikzU/ww5Y0MKh/nEEA7ngExwJ88HJ6YyOeBABf"
    b"4erjrZ10Gj4do6el6PJMRWDxwqryj/8Up5B8+OAHOoKvcBQMYx1HZk9dKuP4nchDOKVQ0CAoqAy+"
    b"gL24LtXw0QqIAB/kxcveCHKwsDadehVPQKCI3mGzD7gmxxnaTR0/Zo0my5EPvjqvBeGT+wiqbeK/"
    b"WbHVdKMH+eATag+Yx0H92C8OBFZwpE4UNdbgGQxRN+QE+KGJBCL/QEHOVNPvxV7DVitVcNlUIMIZ"
    b"lIRjlNEwAwHD+Hj5AwmJd/9r4JqDtowfowm+2wGYaGmvbZqvyrikezPmdj3aYNT2YKmpGPLna1NC"
    b"D2KmSPEWS8IZCN1qBR6okt6Jy9+Bj6hbEEcihopamGDPN0nWJCOgepuq417dp+UelkQAQCkpILbz"
    b"/wfwscxu"
))

PAIRING_JS = zlib.decompress(base64.b64decode(  # generated from web/pages-v2/shared/pairing.js
    b"eNrVPWtz20aS3/0r4FrfAjhT1MOPc5jIW4osx87asdbSZrNnayUIHEqISYAHgLQVmf/9unveD/Dh"
    b"OFd7laqYmOmZ6enu6enu6RklSRrtP41u78SzhkVNWxd5G397505elU0b/Xz09uTlm5+i/WjvW1H0"
    b"5vnzo7fnp6evzk+ODt/89OwEKh/s7Mjq1we/nJ88Oz7//p+nR1i1u/ck+s9od2fvoQnxDJq+Pn57"
    b"dHJy9EyDfrMXAD366fDNMwPq0W4I6uCnk38gWke/nCrIB08eOpB/e3t+eHB8cPjy9J8Kam9PIy96"
    b"AcSev/wF6uJ6Ot3KyuYjq7fme/1Ywr09PTyHuT9/+QMAvbn8leVtf1Qz9htLbu9EUZGzE1bPWd0M"
    b"nNp3UBu5LWb1GADjpp2VA/xff9y/qqqrMevn1WSw+82Dnb14kULLs/TOIpU4sDKvhqwGBEr2MTpl"
    b"n9ojXpIokCFzQZ7xkiSetaOtJ3Evuh1lbTYeRG09Y9j3ndGszNuiKiP2Kcvbv7KbJpln4xnrRR/g"
    b"dxrh/GrWzuoy+r6qxiwrE5oTAUV//jN9tDdTVo1E2f4+ELKiKccS4O5BXWc3/aKhf/kIqawU5Pmg"
    b"xk77TVW3Sdr/tSrKJO7FKXX6rt8noDOvGrqBuSyM2VzetOwVK6/aazmYMRFByj7/V46pm9hdldXH"
    b"EyBjOWwSq5fXWXvdH42rqk6eZS3rAxwAbIMA7uw42EDrPGu/hwGaBCYxzepWkJYzbkzDAt+opl+z"
    b"4SxnSdJWwKseFdKipe/oPhUY6PYiHE/2hURhQyEDfy/K9gmnOR+DAMesjarRqIF/9qMdLBlVdZTw"
    b"9tg51EYGkpHotA8tEizviebUWyT7ur/vYobVC00x3ovPqOa0+j5r2OOHf6/HCRXwcRHPy6LM6htc"
    b"m7FC1MFf/v6Od2aOb6C28+kJMkZMSHQL5SegAssrWJzV5PA6qw9RIoBHvKtmdpkR9Xg/PdWf7C51"
    b"pnjZVlnCO09pIGDmdJzl7GA8TuL7sALjrThQs401505Nsr1//942VMSudEtqAeFIqMSSnWSfisls"
    b"AlTxNCmfeDGKEn/F3sUV2xAd4ujzZ72++1IwAWAnWPNUjSlq727/693B1n9nW7/tbH1zvnUGE+gD"
    b"hq1YZbhSBQva67r6SFJ6VNewiOKiBJhiKGYHWpIPFSsaSwEdDgFTFIn9GEnFsjZJHkZbNmb/ET1M"
    b"6X/fWpKEXy1w3hKD/Shrq0uOosWWLWTL/Ti1Cs+xcBuU0n2JC8cwgjWeX0fJOcP5/N5pkgACZnoJ"
    b"k4wK4epFOQgraGxU90/1Rz8XMnzQJkI6keddqww5b+jHALZlVW7lGfy/yEH3dOIsxR+7tWW1rT6w"
    b"0pLSsdBaZTZhxkLnTS3uCBJ0iTtu9ZuQ/kKS/t4tjr24UOgrGhnKg4gjtOaaXXVToc7KYTU5RVpI"
    b"TWzofznRbpWd1zfTtupfsfYt9fQzUqARbHSH9hntbEeSnz82VWnujxybedEUqFmLlk24rYjEVKoj"
    b"EhVAnXI2HsuFr3SKqnVVSgDikpsUMdWnchI/nrz5qc8bF6ObBMHFToNIeJ2Us8klq9HWiH6in2Bn"
    b"PC9KAOBNpThEq/tfqFFsg0X0I9pfvLt3iyX9STZNiFqGLbI4u9C4EpKAl4ezsI881C5u792a9hAN"
    b"LO0dHE6AR2ieIXMu7t0604GKdDG4d0uIUQfvoOgsXVyItiayiwtz4t7q5/tD0YAR1GqxIQKKtW/I"
    b"Hh+Qi1Nwk3/BPpnbu2hm6Da96nuGkQmz5Jq5rfhmnew+TsGIGp60YG4ke6CNd7gNKCbmbpfX7JOj"
    b"Ocwl+IV7otYO4HTsmdtftjWCvS+483VuBoBiBuZ7Mcks1SpI5O4BBjYTVHzJdr+/fZVyok2zgvYE"
    b"sRbAJGvYyxINt6IGnflYW8tZc1PmkSJTc53tPXrM6eSzydFN2ccMlIRQS2AmteC+DIsrnG988uJg"
    b"C3qCbZJ3s2S0sEgY8sLH8VFzWExUPJ5djov8x48fTJ2G7L3rOTfv4rye4z4OThL+AyvkvJo29LO9"
    b"wX8+4f9u4jOlPgRuo2zcMHPfMJgBTbngHB06QgOj8ZpjooxdCThQJTplSpACHlNfYJnazUWpKZi7"
    b"QYh3O2ccCXBVQVPEdwydq6alt1935+5/6kUPcLVdV2iGEbFJDX2Khfr0Wtx0tLiJl+3bIUqLMiRR"
    b"iPN1MQcfbDnrNUH4QlEyMFxLEJBaPrn+n0pAU1yVv5P/nOQbCYDR5KazybCrSQNbT1Z/PcmZSnXx"
    b"HHSqkCBPfMLitUyTO2hbipxjCaIwkHLARRH4z2My/FNwawAiKpbqmahobwYkW/zz0yCSnKHvG/l9"
    b"w7dmf7awELgRGp6no0BXTlOt6HipEeoEXEL2p6vQads67sQZPQYCGdoyyy3YBogGWP5GcRARFevz"
    b"f5OlzoSQSd4ztCXTir4S3adhi9oz4c24V2Wg8Plz5JJXQGrzr5POLom5TG/qawa5ZSwOSUp/mwbK"
    b"FXP2AtqDSX3FapBssCWwP8WcXnTFSlZnCG9IlBMIuN193Nvde7KQVpFugwQCm23lJHQL11f+9eMH"
    b"HjzzRMZC1IiScVMFHX/PvnCElXC6wMAw9rWFihMIsTXfe79z71ajtMBPWxwAK250p4HFgbYNR0IH"
    b"mXbIPAtbSzAsMuEUHMkmr4sp2HNKKWGI8GZcZcMlektDb668sEMxAjozwj+5zpo3H0tZ0eN7SgZz"
    b"ZEt4SQO0ahJRNq5ZNryJoLMoi4webAaDlUvrSTHMNjyLyRQ8JOAw51YMlBca0iASfZO3Tir02clB"
    b"zGMQw8NZPWdKIy84JO0h0lCg7fKMG85KyUhkO5DC+iQ4KEz2Gj6lmSwGlHMUO8IylSnZnUqM5PZC"
    b"wWXBD4XfwFfIjjGvQNN0EZI+vgk58ufoAGdD4SYM96WEJeL7V/KUQAAEDwkCjfua9KabFjRncKNQ"
    b"4LJAktreO0yGhncJPXAvAs4ZG4GqcANIjx/6OEUbyrMl0dEaek5Cri/tlrxHht3BIzMbmlwyUMtV"
    b"xj7JJRGQwgVDBjxgsrpvcUf0ZpOD4/Lla0lzbeOl1bUWhGYFYn9flBgCttSxzY01lXK3IS43aZvl"
    b"QfPV6hEjTRYqG7HRn3o2HP5csI+sPq6raoSBJmfn+SJlXWcfhWgbrgD1TW4ADDXhW5GtwV+8Pjjs"
    b"5P9K5T3FGaxU3GKQP0Q9EwYD0xxwlDIBLFXIHjP+YB1sBLduHz9cWPGtPqcoN+WCmngjpUC9LVfX"
    b"G+tQLWhritqawvZ1dedKDdgtlG6ck1MRJ5d+keaznbGDWVs9r7OrCQMHYCR+mOseoLKJOsZ4++qE"
    b"ZXV+fUyliYjcynZCUPRJ57/+xA86Uyuo8o6flkMHPBye+mf/KMWSw6NpDyzyHnIUtGMP+dmbW3YB"
    b"nlhoYSSG7wvE8XAlIRmIU46eBqRguwVHYuKCGT6NDQ0VPrSlmp0GgL7fYKQ9MAd8NDWhgyEcIgb4"
    b"F0LOA+GX0EIw/OGVntVyIZeUt8Km5hzmnJfiQD4RqUhp18Fytz8Z1FcP9hSkQcY0JBtWrAazeqDP"
    b"gUyNEusOlg8oghJoUIulSPSV0Rv+Q6Mk1qdlMfONSuPih2zycVWyt21+WJWj4srOPrk1k47eiZwi"
    b"nafU19Xvds76WL04W3jHgMNiCBrkFDaFBq2Ik+E0aYZTc1HjhiHX9AmwKXXSRcZFyTBdRHANWsul"
    b"3UzHRZtsv6//8r7cVh6hCA1k+2r0wXbB+YJdARz02xblTFjKyqTIMT8GQeSRx/tLwO19c58k8XNT"
    b"j8afPk/p/zUbZzfp+8vtwrDQqVXK59MHS4YXvNs967fVqwr20UMw+RMvoQM1ELWRmsemYdY0rG6f"
    b"FTXsoRb15ImySELyyJNGT+3cuU6XGSAi9ilnbNhAJQNalDPY9fA4B9MgxsWkaGPrJLubsf2izMez"
    b"ISz2mIi0xFOn+ujl4ZGWE3DRwTnCo8Apq2HUlg3lwIGIBWzoOUAcmsgk09wwh6c5EkOYJNMc1cBJ"
    b"m7UNN0xkT7FaoPGs/FBWH0tDJTYELy0Ao49E5X1IRKJ9tcKpVR+k+CgDSYI9CDgbPOnmVSQA/NxW"
    b"0WIL6a/y26JI9NJXo8HMZFlZTQpwQBhFTyRciyEWfkw+y5G7SMxUHIQbOHN4orLaG++qeugQJt3k"
    b"7dT42acAC00qVIi64VR+pFbglJ8drmhCNHa5ewwtE2O5UU84OvzbH1dgZKQ62CiLOGFxQZicXbiz"
    b"XCYA1A+gzFmKG4lsxYdQCL4cmqY4b6ZP5jk61sKxchhoXn8JgVHNwETN1A8ols+r+mXODqvJFE1c"
    b"WAK9qC0mrJq1r4vxuGh4ciEmxD5SGWpEwhzJ/kMGix5xONESk4u+9NIAJ2ACPYE91VTjOUvMueKi"
    b"FvVJIgB6UIl2f6rFntMzv85gR0LBS4y6JQjdDSL0rWiWY3rHbColA3EyEBT5A2qv4VRBbrL2lH8k"
    b"NhqB/nAaiaG4JC6ku64kstT5MIIeYxnlXwT5kJoYieE8amB5LTEUnSiUgEw1m1RzdjQHS/dV0bRo"
    b"ByQx0E6hQ8uf0zruSaLbNIFuYJv6wj7EF6fTIhjIQDoBNxrvwJ/WHi+ICqBCVua4RLRrSqamly71"
    b"tCPTu3OHAUQECsAYuZ1J/7CAza6qonFWX/lpZreyIVlmmKPGZLLBInyIEZhsLzJ6UbmTmgRGLRdy"
    b"GmbJbJrZFNWjMRmjC3uH/iLyWhgGMNiIhIEctSYbMdBVf6sDKdN+hrfMjQEd6idbf7fv5967WdX1"
    b"hM7HXrTttMHINJ3M9aLprJ5WjZWQhvmGyqskMNtLhHp0ddsqr8acVdfY6UAFNRBgBoYaevNm2RTM"
    b"t49VPTTLGvJazRL0+oPZOxf3bgW2i2gywzw+FmVlBFOsYTsHKzYbgzC8OD09PkHML/T+zQdvrxEh"
    b"8MaHzT8KIB4mlaaRWYcJylBqKHOsVXlQoSQY0AmH2Xh8meVrpcFUdXFVlJjigGNSuksohA7D2p6l"
    b"zRMebuB9fWHAw7pdYHF0X3J0oOwtYguY/UQjqt/d+6/+Dvy3q2DA+dsFz+/98Hanp4NV1DPZPQKM"
    b"p0kZ5SC7jx89evDIHEvxg8ba1vcaDIkxi1BkrAIlfWahEj9jJE5DGsckqgQRcZ1MJGXH27jotzgJ"
    b"Yz9wkwtJWHLm78vLkvNB4XvIbv+YU//DLqRREOXQf8Sxv+x7jYN/aQdYc5LtAxkAAt4nuWojLP9O"
    b"0ts03zQBIMg4M9yoyBpSKK+p9ZvRiNWSbmDr4vo37sa4cWdf2cgwncICtA6oSvSMeAbWFPxoSr0y"
    b"wiL4aZz8yygrnSSf8zOQcwxVkQYDlwzDVzSn82lGhpH8pEhXLMNfqh9wi2Pr8Bo+cLfDf+fc7j9z"
    b"0q14Ipe8K2dVkUNDWxBmDHCqb1VIOLUZ3VVJyiew4b4sW3YlydoX1EjXgRXkSt1MMipVtyFEj4ST"
    b"f5XPyVDjoE+JufejBzvhrr+j+mCVbOqPZHa3KpTH+/QSRFaE9XgrM0ZqN7NPkIfTYIpvh07sm8t0"
    b"o5y51WFXqdJ5dq4U4y44U5hFtFasbWmpkZgvCdzyfpzlI+ADVpk1LC4pb0RaZ6IDNx6mqG3ozru2"
    b"1WB0nQaNIg5AtpFnP3x5GqDjIhClDD3nnXR0q7x/l9OP/LIH67BnHIJgmLpH2qdH8kWHIqzlByN1"
    b"25v3fiumcTgzXfAYNpCi5auwya/ZJEO3QuwqsY3uBsF8ExSRFNBxUGGawIhvarhj6+Iuwvge8px3"
    b"4L3TtdlbFckfdB4KqRj/oOs8yA3+D7qOgrwjgEHHoU7g+GDQdVykLwE4IKRVTBihtAfSBDahoQ6k"
    b"sWeZRYOQeWY2yhUSoiVfcwToELS1UeGAx6ACHDimAOVlE0MjEtvCGtaD6jrc8gCDitgfVM9slRYO"
    b"6WDeiX+Epq2nFVsk72D9My8Ob558LTcxOLxrYlilth1gVy23A9ZetHTJjQ4dAosWVCc6SiL074Z4"
    b"+FUi1+g3ZYsrGSmGgRuzXDRFdIl+hwNcMstDXEtm9aa+Cc1E36UmVbRZ5jG1ct2OdMVtzs08CcEe"
    b"jp8RYrI4s3AzTzz3ge9GKB5aqrCIljFNQK9qG8CwBzWYZSQawKYZqKFt49AAd6who4l9SG81oiMO"
    b"DUmfFoBcDRpGlgiwABP7thPpQFAnGsImoGEZmoTUmioIj3aXB46aWELL9RXKAxemR4BUPatKs0m4"
    b"uUt5cpcPGcw6DQ3FJ5QuVStcbin9WOd5VjXeAKfb5GHDQF953F+ePMMxSDdLH7CsHV4DFh/NsKcZ"
    b"Zfx8QflHZso65o0pTFKVQuCG+smzM5fhLZ2CQjHlLMjcBZG5YOctGAzCT4/LVGClWUsB7d2xTAD9"
    b"ieKFX2jGopOBv33rGkur8pix+rAqS5aLvBpxEkPJV1Or8nmWtxVd588pYwLhUBLenh7avSS8Hp9X"
    b"IT6tSpNZI0nG7GJ924BLmfK6hm/16tsPOWOOsSR2qIA7JvckXxn7kSe17KRfFsJnhWsWXLp+kqwj"
    b"K26i7BoaZ8nNE9Qpdj5N2nEBoaDofHuDCsCJjHUogmmOx+IhaUvcLB1q5cotJj4YauU6g4oxP2nn"
    b"i/NZ1maHvDih2FHLxmzCwIzYmu/hwz1VDQRhQ/10j2ljGAk5bY2zqEZieaOtc4pF5K7yM0X6Tgiw"
    b"J8Ck+y7TKBrWvsKz7meM612cgqrkGHNFklotg8fd1okqBl5o2mOne5Gq4BZj7CAcWtBBBSt3wXxp"
    b"YfexBSFtK6FA/Ss1rnjK4965o795MGkQCPLpHP2ilr91ZpifEuapV+noGdbIIArurCJcN0CdKcuU"
    b"S9dhfks4oJ3qxlDWWrtwM2Lgqm8DYErOWkhV8ENsmzfCVl93D9U8zT+QxSwyfC0T3zSbDQbjJulc"
    b"7MJd0odeGrExWO/EMCQdujdxm+UfNMuukKQBEZgOQmIAEtDBelO6gOUKRcvsVIjm0I19EKRUv8K3"
    b"7WJ1mMUS4LdiOhBM6pun6dL4Q3wC149EC55zEBCXcVHiIczFvduuPdC2HcxdUJ6Co+8n3hVZ/One"
    b"LWf2wnibwzi1xvFkQl7g1aTV/hAh7J+3y3c1LJMQMzsUa7jG/2paw5MUQ/gMY9IwJz3NYcnQciUR"
    b"UAvHnVpBwiGp5O//qTHmMDAyD4gTsnrWoHqzkuuzPGewL5RXolwnzCg/1nZjcYuUZO7DVo05nt8G"
    b"nN6FAY5b3EpIkgcqUxmQyt7msnFADwm+LEcVLLhpdlmMweRY9hCdvmoqlIp6ipBfLpV9kHO8eL9z"
    b"Ed3nTaxK706qqkHxcssMQeJ3VbsvAb82ZoX3KtxJibeMYN39nps/Bm7dNzPiF3999jwO3PXhmMIQ"
    b"+sJP8EKFghO3yoR4yeseuvfIvfShttBsDMrRuHJhIK5Xl757AUoHJGGwVDZEWpqKXdk3ng6OTrZ+"
    b"OHwdy+drBngHMXThCcQJJ0tPWzD+88zPDeDCdZANE1bO2biaLn0k0d6qhXM7iGTT/rx3R9tFqhQ/"
    b"zYC0qtCazoyTq2pX4RFBzzknFJAuFHFqMylMQRmllAoXFHBBMVPCDb70BK16UUU2KdoMtwvr8Gcd"
    b"+4Z3kppexXrmDQcu5gAoEOjDx+fPXa+CORfJdvf0udLdBFp2Z50Vc/f+KjReERHk04pe/sxzoDB9"
    b"H4mxu8f3ffcqt2SMOm5xjWvftOYjWCcbjlbzRSmoEH1hCi5aX5q6TJxiHrBuirk8OCmm1+Cy0OMe"
    b"+gBDPeeKzDO5bykoUR9UT0oRSMUyV9vjcFjgRMGFAn9yEFrjyoPJrl4JNbK798TUPKb7vUTnS3Zo"
    b"U05qXL32FAHwSvWKS+iKIlYYTfYVTkzhiB3zaLTMMzEXLsWZu96wXZKhsmlWShRrqdK5JSohhTJO"
    b"VK6Jn15iZXfNKbVLppdYVfoigm8liJh87KaKoVdMkWRrxdhQ/CKcDUVlFpR5vc2GNWqsFtaNNbuJ"
    b"WWW10YR0m2j3zsrdW55JsxpUnXJZaMhsmO/2dTqMBSBj+Q6SsjgI+5R3Fng2mTJSnBsH7it6s2Is"
    b"DOpXYCYHNih88tmLaJos3TQyuYaL3OUg2+6xyFBUenqpgg45rArY8V3Rc+2YIVdmRJiBQSB1k2Zd"
    b"X9PrfnXo1fU4N/U3u/ZaeXsl7G4aaS4IseokQNg5ZMVoUaLg5Yk6GqjKQ+2jrojGh0P4XylGv/xY"
    b"0dUS9gnjsgMlo6UTW3b7XOeASUePe8Klhh9VHc1KDDcyI2Vm5bFaJ2JurXW4Jo8NQ3p2vbNdipCb"
    b"2jl0yPt1o+LgcIPVWPPUW4Y3XtxrSTxKLWv7/BOVrF3wbufMeJOFR7aVOCdGqHuhhgVJynQ83hmc"
    b"Z83TCBIGrGSroD/OLtlY53xacXsjfkSRBbvlyiBDZN2m4mVqQSZWZ3pW+lTAjZi7Am3k5ZmB/7ds"
    b"UrXMjPzf2lFvO9YJnfh2NHZtBfY2OVkQiunf52hBuDj7Gx0IOGaZGePr8F9k6pljhPlRwKW7p5NR"
    b"FlYFVhxwpS+04rDBt34M2fCv+RkeIGftet63xRHhU9h/wOO+72NIVJf55co1SvWDHd6W3ZJp9TT8"
    b"x0dWh4mFBBHa3XFi8SqFMvHQa1pi9BFO3y6PMIvIhaIDn6qSWujBDuC+Whqe1TDpepHX3x1K5SlS"
    b"XCiOBPaCGaHHm1v5kqqX2I01eOu6bvnhtSU6ylJYl+NLTQGH2dbmiUli2qf9nXdYDC72G7AOmD0r"
    b"8R6scvm7ZiJfKIzMpblZApoOIf4f5KAJ+ipkl2ehaS9fSb/h6KsIBV1GMe5reg5+MV/l5ndeG9FR"
    b"0tDNESta6l0eEcGvde9OBEKogesTVg97e35rkczWde3CeP0pEI51GoZCseumcLus7shBNyKk3iJR"
    b"wxdzCscbaRhWeCq4uAKhLJ0KGtQK0r4PhVIpZqs6Muu/w5c/NxT7rvRY86K0FnmcvR47mCbGD9es"
    b"bXjKKHGH7zXLb33dFbA4SfETrz0OzW91fLdqriR/wGX5Pih2ZC9u2aWVjSy7tcbfF5c+jF1JVK+/"
    b"O3VgiM+WCjfP9Y26Sa8Ue2BX68OuNUmceyD2qkRRUhMwck5DK9+E9VNlQ0vXbKGswHWW6LBi/M9E"
    b"8Ld62mvgnk6g9wTA4Ap/yxnDyPaG6J6OOAd4RnxcR8g7Y+RmlHyjOHkwUq5i5cuj5bfmX+sYKCIY"
    b"h/LqtomoMu195w6Jx0YNJ257GEKh6+zrJQIk4AlYKaYhCeDenHIIlDyvfOUuxHvjLdQVcpXN2mvM"
    b"1su56I6yYmwuNhQeDhmypta4IxC5f9mCi13qmsyh/JbO+wDKi9gs+V/5mZsZX8I/+pqm1+/j2bLr"
    b"ATKxWrox7rUrbyGsswi6FsB6wr9M8J2rUs6uI2Mu1nV6+1BKHh27p1Jfh9Jd6etIaTeqwZuooE/H"
    b"HmmEj3hURu+V4diQiHzIQ1oeD9JjLZZa+NZ2vCQuRkVHoVydpVt5qNlyguJra3k1Gw9pL8MHPabT"
    b"ccECppVmrPna2qDjWT2D+Nz2uhpXl9n4FLbJ/tvp9FhkrYX+vKgRaQomdFrPyMkCXy3JGuvAQRZ6"
    b"pixWeE+4YKHlYWKBfnQQv5S3hR/G36i849x2kdVmtIbKHDOcLg3olF78VDmd+GH/YQVdYl1ICD2V"
    b"rMvlrbxe+LJej16nDYTpCRcviZhQCBw06HIvLR6r7LeVNbBT6L3EKgjrS1zP1wCEcOhZPqzw46vU"
    b"tblhckp4RV1Xp2k4GToy74XY1D50S92bCtTUvcGiueIYXSSEfkCRZMuOpbn9asCQeU709Bwk6sM6"
    b"6qA/2btI8W2e/wVDgdXC"
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
    b"eNrdfdlyG0mS4Du/ImnW1gC6QBR1jhosSkaJUIndksgmWarpkXFRSSBJZBNEojITlNgams1H7Dfs"
    b"L+z7fsp8yfoRh8eRAChVzdhuH1VEZJweHh7uHn5stNudZPd58mWjtaiypKrLfFS3djY2RsWsqpOX"
    b"Px283U92k1Y5n29d5XW2NSmqeuvmIVThGh8GxycHh++hzkNddHR8eHr46vDt8MNDWXw6eDt4Nzg9"
    b"/vvQtnmgP74/PDk9Hu4dHQ0PeLx0Pq+zcms+TW+rrXlxlV0XMznu8eHbwfDd4ORk70f4996/Dl/+"
    b"/XRwguNtP35mKg0+HAx+HuwPjwdv9/6OXw/P/5GN6t5FmWX/zNofN5Kk9amq+t9/PyqurxezvM6z"
    b"qjcrql5VjPJ02uraGvNFOZ9mZQYz6kFt+el8MbrKaigt09E0i7TlVtBvXfZgSaMs/DhOrxdVLy9a"
    b"G2cdPX9c1+vjvXcDs7oHD58lf0oebD98rOv8fLB/+ga/PN3WRW8GBz++OcWyx6YagPfg/Y/DtwDn"
    b"4Tvs6cn2tmlwcvjT8auB+PhIfDwd7B3vH/78fvjj8R5UesfTEBXeYLO9n07fDPcHe/tvD97HKp0e"
    b"770/OTo8PvUryXm8G+wf7HkVcCqmwr8Njg95M5eN9XJv/0eCFu3vy2IxHWdlq5u0XqXVKB1n+Ofp"
    b"ZDFTpcdpPjsvPvGWnEBtLHyXltUE//hQTEfprMA/B2lZT2B/zPG4TK8zGGZcjBbX2azuXWb1YJrh"
    b"ny9vD8btFn5vmd3EX6+KWZ19rqER/sIGqqTdejiGMb6k0/kk7ScX6bTK7qCpaNTLr9PL7OS6KOpJ"
    b"PrsczNLzaTaGrqiyHmWezz/k46xYNi+os3WDlezkoOjloq6L2ap2dXF5Oc2chid1Wi+qVQ0rqiXA"
    b"Uawe8LLYmuY3YrRsNl7dCip5zcqsLm9XN6RqXtNRMV+jJdaChrMr2/A6nS3S6asyS+tsdQdce2tE"
    b"1YNO1pqD7gKnUlxcAHJ73ZxM0nL9qVRYO97RwfW8KOu1e8qp+lY6qz5xXxsXi9mozqExUPUCOslH"
    b"74tPcBN9gSMIm7AoZ8nltDhPp6eTvOrNs/KiKKGzUZb88Y9JfTvPiouGCkBkPyW7u3CF6DFa0GeS"
    b"vFhSv92hKv1kH2DPBTsbd2KW2ed0VP81u63aN+l0kXWTK/jbme3Lophm6axNHVElmCn9ULPlMppY"
    b"QXdQS1fY3CtLoP95Rf/mETr6o7qvrszYHbhdyrrd6f2jyGftVrfVoU4/9npU6Sz4DN14qzkvkPSN"
    b"D4CoXGalXtJ1PsuvF9fwR/oZ/3CW935xfZ6VMMeT9CJzGuJM1eKe7+pObNkPu7q/6BxOkfLpCUTG"
    b"tVCbLabT5N//PWk3ABU5l9klAjVheF6UxbUG2TSbXdYTMZkIUG7r7C1V0+vCaQA5oH+bCc2yTwlO"
    b"ejAbFXB9AKAz+qv9l5PD9z2eRH6hd7HTs93uQDd3ySitR5OkPczKsig7bt8HswsAX31LNZ3JVdkU"
    b"sKAoX8OaXpfpJZ4wdVoUEU7L9BopMM7vp+O3J1lajiZHVNqeFjAqdNObpNWkV03zUdZ+0OngMPlF"
    b"0kbU4faMZp0Qh5JNBHEOI+GR6d5AiYYHbIvuSHUCRKDdutGNHoZ1ecq6N5i0bKiLoRnsdqulO9/8"
    b"/n983Nv6t3Trn9tbfx5unX158LT79PHdH77v1VlVt3WzTjCa+qkr0K7zDDRUYQZxAGuihzcXzlPB"
    b"+yK/7FP3yDBcZrOsJPD2YbZYokfq2wFoJfhtnmWlbVsWxbX9VWdIOgHj9kbcnf5wnY3z9DhLx8EX"
    b"wLcsFV3c5BlQ2KpPaPAunbc7WDrLLos6hznOLr0v3B6vb5htawHnup4Ahzs2cz2cZzPFjNCEkVPF"
    b"sldwfOt+sm0K/wZ0Pr/Is3Hw5bSo06lTkF87QMCy12k+XZQZzKSss/Fe7X3em82g2xHdLGI6VX45"
    b"g2FxWS2c7T8qmjiwa+N8DGs6BSqhgHECuEVL5ivpCFiEEBzixjYfvYb7eYUiyVGal3q/+Vo7zrDc"
    b"a3ORl1UN+HSdyVkXi3KUnWS/LjLCkm1b+AYOqO72Apvt1XV2DYLQ2Kvufgya7Zfpp1msCX2Q1Q3S"
    b"ebUnQEDqcwCEP8/Joh4XQefnZZGOR2lV72dVDgjUB8q5yJwvXotpqiAjNxsLTwgSfukbPR//w6k5"
    b"NXXkKJ3M0nk1KaKfshKEtPyfOFkPFq+B31/4Ey4BrwFz9WH5lOaIJC2LGtPbk7qYz7E/u9eI0IRL"
    b"pkhjnilIeRsH82I0UWPVsFqE8hGQo7yC4dQfvTKriulN1kboEoYB03GT4elxhgXWHiZb3xLRkGPj"
    b"rYPL3biTTBhs9rSefMArq52PuwDX82zaVcW38p7JmLtbwvPlY7pYVMUeyi0kvlAj6lh+HsEWVm/z"
    b"CiqSWNFuTUFGBjloUw/u3tJ8wb7hb21i9TwW0mEfiHD3PPyhe4nYCcVjYTdbDXWBZXAlZ28+fGzv"
    b"Px+N5SsnYyriTBwxnWaSVrezUWLmU2ajohy/kgSwPR/xHOgWnY/wMlLs0/F8joQMIMp3tWJM9RW6"
    b"4zBAjADYEtaYIvqL9j2+6rJw6B1qTHxGa8J726rKi+ln/GNOf5z18tlouhhnVRu772i2KFFgcOl5"
    b"Lx2PuR53fQfIVGU0Ak8OV0K3RsvviNA/0Z+3TL9bZfYPmn1rR9WnZSfzESBoUWXACURYtzsevpmt"
    b"+/77xIADQIoyEII6rxK4zy9RGZSP4PYYw1nKKtj4OoEjn8ANzDc+sA9VhWxbwA6mi7q4hjtqRAId"
    b"HfJ2szSigEh8i8YyLvOptvvVISL6U9sBqLmAGeqk32qpGihycS1kc5AvV79CdiF5nmybVn1VT7Mf"
    b"9KHjTs3eq7ZcEgZb3TmfXi+C++H5k+AfigZCeP56WEdB9c3bIRfy24JoUx0Zuq1CmFQN0Iiiptt0"
    b"MccDgZdCWUwrR4wpaW27S2EaW19kbf66eAmJ0Tr1xnml9WebPC4QRj2wRUEstWjcsT/11b7Dd3qk"
    b"V9EJzGfTPQyb3tbZAtut0FrFpxs2MWo8p8E8H8HugOB+xH+cLOZIjbJxGxfEBzuopHcX5+Z/Q0EE"
    b"2BAWIq2GzBm0ARWSiGLMaRc5bmqOvFwl5MCJ+meWfKcKhYzjfnD4ff70fNcjYwq3Xjg/oeXnoRoL"
    b"iBITqCgqM445iBzjBKzoy6iJYqfPPshKhNJYyed5qJLk2VrczxaXwcWqBniRtA7/2oLJt5hzSJBz"
    b"MJ8j3dBIohueAnRzOjh9Mzge7HNnxBCZzqhS0BmBq6WYZtOl2EbJTwP39xNwzuWrFC/bplr6agec"
    b"aOnjrNQfcMbeIm9J4Fp+M71IfvnDl8ar6C752097bw9eHwz2k//zvxOnphF875LDo8H7X5TS0MUl"
    b"59ri8VpYuyUuuLZ7brHKq8P37wevTgGuBOLD16/xbaPV0Vjn7RSOYvfJLL/rTUKAyJzGZfpaU0n3"
    b"bZRE5otmbkyBx+JHT/2GAcXbgw8DDQoDCKKJ8PHnvQOEQPL68DihR57k+PCn9/tbgG9HLlh2vDk0"
    b"yxHR+XRYxaZhwzRiDUW2DxUu1iDhXx48ItQMVno82Nv/u7OkHdlF83LC7ry10MW8bClUwS6Bfna4"
    b"WW+Sj4HLWEq8eZQx8CcjXB4qD12yTJpP0iJe5NM6K/l4wPDAUu8+5z963B6gNCO+G0+zUtLaMaza"
    b"6+vHsX1Eh+BpaMrhVFaEwpbd8etkQlvnn33uSJx5aMpld/blM1GHfLD/S0gMnFstJAgH+28bqQGT"
    b"WpqpS2jF8rqSqXPGAjZCQJo5cRqiEYO4+dYISWGr4+I7DXNCV0JkYdSvz/9pTGxkoDWQ2+uJ86tE"
    b"+ufhi7bhMJxBGmX0pXJ6rHtXhmnkLiVLh2whMa2KuGiV0EstJNhrR1/S4pJP/vM//icIpXPk1aAG"
    b"qaV6/uUdr9RV/bZIlm1ZlPOfJOoTKz+1Z4AEXUCkqkov1dtJRMhKsJohnrpyI6KRrYmq5iOaHsse"
    b"5vN0fLmU8qF4t0W1WoKUkU6qUtp9wE6jBAdg/fTeMD5d9VJDCjVFv7taMYJUjNXQ4tjyVxy0r+49"
    b"3YfT4ngQtCkuLoB1ycTtwOVafbc/AMzaN5OqtNoRNvfw6AjKcbdwhbTYmA6u+og7cUYPE/IG4gZ0"
    b"/bxn24YWg7UFDDVj3IzMF6S4rK52+bOP6h67TNT1yGVLlQ/2R3ei+IyIqoDQMpKby2y7jDhcBvl4"
    b"P60m5wUcE631lS95pP0K3nE/Mu3UL2Q4T1aC4VpQQTUBjhT/IChUVFRcZeOM1VdAVG7VJsD0r+fT"
    b"DJVI+AXYRTYuwb+GyMKS4os1OkPgJudVNh5WCJNxZbqYZKOreZHPSEumCCeC9Mw+aylbD0EyN4O3"
    b"1J5eTzd5tm1oW6SeWWsXzYeW1SRAdJPHtpJ8gu2ZxbMi8ZzFaOLSoxP3d6LH8IUNaQGdmzEQ+YKB"
    b"P2p8QmotB0LkEV112uMezcQj33pVcQ00jDD+ebLJ9kMCReFDx7TXLzyxMfhKRRjERlHP0BrKbg+0"
    b"WvnUrY5SQ6Xm/q1Iv6x//UIfnyKuYDsOMdoMqvBs/e1Vhwb3d5QuLiesBs6y2brb6/bT404i0IrZ"
    b"Nnitusk2oPuTB3ZH/d5xYvftG9uEPbt1LOigUjPwdM9IXSK2DzFMp7rWFIN/C7OHpzhaBMAXRZm0"
    b"NbuNJh6JOdI8PIz68UzzIN7WKrBwQ802fGzN8tEVnhja4nk2yrNqmNOBnmY3GRnXTeb4T1SwwF9n"
    b"zGKEkxP779EkHrKnR+omDx8LFm5Tf7ejR3Yz2M+gEewl9PzkSSfWN63F2Z14d1SPenqwvR3taTJf"
    b"o5vJnJDr6ZMnj+LzYWDeY53cgGYW9CqmJnjfxB0qxhXbds/d2poF9vf4rpFi0A2KBOO6YIvNebqA"
    b"O3MFnfjYSnPGLZSTRbMu2jdcAdc+k8yHHKuHA8WvN1WBu1rzirMt6fo34Fp+mLxW9lRNQL4g/uM6"
    b"ny1qZkUM+5C06HW/UqcKoXSvQ+WRND16jwYlxMNjILBuRTs1R2r55M/3aKhWdP+GvP6wXbCNaoII"
    b"pGAjlyGoc1E08HHr3hkNzWn2jx48ffjw8TbSihWoZbnFe+GWbWaRC2EC4to1keWrfMbUWjDFIGgZ"
    b"ZnU91HLZQzNmzwzF0Ndmex67E2ugr7PnyeNnAjGMaeJrNJ7L2mTDCZdXlbWb+3JI6EdDvgTZuM6n"
    b"ULWYEekx2jA6dcoExkjKCQs3N1l5y4/axWUJO0zCBIqSWigK6I6YGQI9gu6CAxeVo+y9xU5RU+zb"
    b"OlfDsvYR7Gw6L6pMaeQ8wq7EGmIFNYM/SufpKAdZ6swoSaIz07okakgTerZmAzWA1ybSK3JL8bbh"
    b"IyhJnUeka8ff1RJ50w7HWEPS8UVOkvE4O1/QH9o+Yp6SWr+Fb3SKzi/KjA7essuPp42d8Nna7rFR"
    b"HHmr+BxpyZUeP37kfUkV+9/63mvDs6BvaH7kfqQ1sNhguGp/53nFuPE52r+VNyjdnlkuPMbYqrc4"
    b"28BjrYPvUoKJ89ja+BOrJ7tN/XzcPhPWo3Yp3A4XsSinlUBY/tDDUm2RvJj18R+9ae+yKC6nJCb3"
    b"H/z50Ta6MQWIdFyPXtEsJBrFjAxCLYYHUDWjGDwlIJ1DEEIQF/FAV/L30gFUBBqRWuuCpuGcvccn"
    b"vBBA06w25m7WFUYaLgkrJboWjhbn03wEazkFsWzWtqdmOKcvw6vsVpst2Y5FL3zsy/wGbpq/fLpy"
    b"euDS4T8+XXUsX+y3RfV3Op2epyPdmO+d4UiVdpYYi8cWe9eAKaausytLTVEUFSiLuhgV0yHuHW4B"
    b"1pR+faq2b5T98KGxyOaOUK2N8hdZQHeamj1+FGsG+xC2S7cuoNHZl0f+SAT/C1hVVsIuACG/55Bq"
    b"CxiMwxpxw+vCYWnc6vP0MvBDEOAMKwvZ/MmDh8tOLD09D/HseIfLfpAn1nN51J+aWmbItZgHFijq"
    b"JsCJZJ/JKRR+xvr8SDXO3EeNGAnrlfVoyJS103Cq/4IuBqqK53HBdJrmoN0aVE1yTMD5dwK2EwoN"
    b"8vI1NqnredUXHCZWATmuJHWfUzpPq+pTUY7d0op8KRrYnbUcMLCX0PeC561WFD2T1n7R4aiIf1jD"
    b"aYO9oObdy2zWhUpdIG9dPFjdm5aU2X23DWymXvDEie80NcEeVSu1Fn3mGxrAVCL18bA3NID5uw2s"
    b"z0VTE1iq28Sj703tLuaRZoKoqEba9HQjsjdr7wz23b3pfkIiLzZkyXaoSfnEuRNvTNyksxpkB52N"
    b"kdV5Hk59Khoi/3ueT5kD1m+BSx2ZxL0UHHi4n2rA7XQuL3H1EpddpqNbZDKU6y4IVsYmcjhmo0h6"
    b"jDGFlbLRp9JFPh0bXciwRD9K9bBiEQa/Gxcj+FtTEqOPzKbTYoheW+ZVBouFeZmuabwFdG0u1q82"
    b"XXZJIc0n90M/C5YUlJzobCOpwk2nppAb+1tBr0I7wt4MYPr7Q84/DqZM8D26pXfilgPe4X4s4P1b"
    b"U1SW9/Rvv3lqxyI7ZO9O+sWkzvxJC1Wmb+buIxFO0/f4Lru7yQcBtjLg9O0R6XibH6ttsMLYWGyq"
    b"rtGmk76GN5pDzowHm6/sVU9CiDhEMThQhMv8Gwe/Xetg18SOPXjaffDwmceSCTrvcmL8OQAjjRSG"
    b"mYixb8HpYJqslYENSgX3SS44S1ohtK3/ULopDONwsvd6MDx4fzr4cXAccE4LpcCko8eC17bPQTro"
    b"TXXavPEvmmJh9JG1XK4fEUhPLwHPVlcXp6mbPMSH4044Ve980XQfb//5qW/SQysQZlMNkp40lzJ/"
    b"IxJhWJJmkUDfdy7y6LYuAj56GEFAn+pGe1oiMT0Iakb0RT15MdildiL8NXHLroN46Lf8A4O6geEe"
    b"zG6yaTHPNI2Yp7dTwOO/Gof2lYqr5stU3CnEBJmeGzRXLqmJWH4FZIBICVUMecAY1WHPCV20DLXN"
    b"GcZj0HBuI0IMzxdN6tFO0rEBv48lpqL7+exqWQO8M02QicS32USlHBZjhd6kzC6MMbQnNZlKrmFQ"
    b"Y13rBL08yAcHjLBhPpSBKf3WHCL/itgMwo25Z0yUCRDKw5LeqNMEjhVZabNDcFLiHm4BWzzvtbQG"
    b"xIqOQiBcw/smSTalJ1t6kb0uyr+V7ShA9LGsJ2XxiaS9AXLAvDk88ezzKMvGVfK348QotpXEgPX/"
    b"dpwXi6qtRTvlCtlfAlcyodv6FQTCrryB+vEt03XQFKWfPHxobiN6iu4nrXfm5QK5rUsCJXq0TnLD"
    b"95FlQGY+nU+RLWOZZxn/77nZ/VpuLWbpTZpP0bmjFUoE5zFhQCONIQZAdDejsoMndnwprrSvKxrq"
    b"Vegp7zl4tNIpmfBtmZHnwBijuVk1mmTXaetOI5PT0I8bxcPvbETQa6mO7YX5y3qs214knQtIn60m"
    b"Aie4JM9WCTzJdpvYnkgb7fccaaSJpG3luT6j6fjKkVxPthBimxZitpHrCIJ6NnaeaK1jqjzNr/Ol"
    b"psoBN7TcAlq5A8yZZEDHmghHHf689fhXBq3RtabdiHGZmlF9oX1gpJVkd1kTa6N5qmxbe8nPgrqi"
    b"yyn50yVaPT3mcAE9a8/ZMobH6MCa4QXaS06Iq09+LJK3+U2WQFfHyPQldQEHsFqoDjrirqczSrEB"
    b"EsUo9XUIuW5C4kSfZYk7954dZxhl5WVaZU8f+8QijAgTe1pWlpFK7Qpsa/TD8+RdWk96oyyftv3o"
    b"a98njzrJn5LHyXfwf/1oJfnI774/+273y3bX40Odh3wdlsTXc5YpeoyldXEuqAuvDz6J6bmTCvo1"
    b"1tDMd7M+EkT1Z6xTtn2pAcgCjB5RUKkLDbZ31J8/JLayLvsOeFqrlaQxlDYYWmL1EeD0K9ipPQzJ"
    b"gnrkiKaMmq3WIukVuVfGfHa5D3RgVhEDTV15mEBldqMfmQdOnu72GT9Tfn72ZzK3osIHuvDJtlv7"
    b"of7wOLO1H5nCf3FrP9Yftse29hNTmLq1n+oPD1Jb+1+aaj+wU5ETt3N55tU3k3n8WNQ3s3nyMIaW"
    b"jDxIBBXu7Kd1+gF+MqhB4sd4YF0FZPzn4cUFUC9Z8tbilz71n/JxPelTv0hMESEfPWyD6IhRJvLL"
    b"SR18e7jd8UjAJPu8n1/iqRK7rgYYlbfzuuhVi/N6mvXGXK118mZv6+GTpy01OaD/k2zW5q/J7vMN"
    b"ra71zghX6JwpLIdrQTEc+CaiVA+FujhgCSDojClwTRuk4dZ2q6NlOKXwFSG4wmgNGdBN8mKOErXN"
    b"qMj2sQWHYHhOtJANUlJc5VnHf69X9/gPmrePh5SRpEyL0iKykuqMxlDyr0ScGNNlBMGtotySjNXS"
    b"aex6825qgOFrbGWa147wIOdIDkiOaDYc3NQTCjwAWVGxYWpGUFB98v2ymMMNlsFFqG3H3GgTjleQ"
    b"7wycbEXiam5hPNRYwIpfaF5bf/jC49/9ol6StskCSLfxHSQCwhvuFbO7wodG3RrhdduzOOf4AWpS"
    b"DI248R//GKXRRgMpmgA22V89ohEEWg5p6n5lMkGfObypd1vojW/j4WgZp0i82fg8u5euJgIqkolP"
    b"W1bfTnY8fNmzA1r7PINemyvQq7FngWFO/2ry1s2AT0Fn2dwQEOd5DbTMBQSXGUBw/MkDDDT6kr60"
    b"kTi+nAJb8pFAc9ZNviCvBaecwpF+j+C+69wLYoxdvwnMdNgXYP14JRyxxYsA2XE+6rOxFrwtpO4R"
    b"idWvPgbWiGDa5nmQGRr8jxC9qxF6mdHHb7lMnI0L/K/rWuyPE3BsFSU3QcgiVDwI7mH1Wpaqqrhh"
    b"0QgLUdobNBWiuxONbcnUbYS2yLStzoK2jV37q59zIMT8qLYFbIGvHmmt9HxtCtmyNDSCF8FFxR+R"
    b"RSoGiSwysQjWikizGRX+iS2gjqyTatRzLyYNVibamrsBHhOoWCYT9e1ebFOl/ALXYJWCuHiGS1rm"
    b"atjTI3QkL+6q55+HUUa815KvZq+MZaMKbAdIFgtLame5szJgiUVsL9heYHOuoiVP0tkljSymYYl5"
    b"JPqeFFp1+Nhd088LdJvZTvrJY4rvrWmh730tJ/aD7iYwn4kCk1677yy3ZJV/IQ40U4cg4qCtqwpi"
    b"deVOVQ5E4kvbxX0ivy2KUGhPAcUD/C0OlnGUv8/B0gp8RZGGNHmSTIhmDokLsT/NMxG1W30Wg1iU"
    b"vp+q95LjjkIXbdODjvUA1CZw0T6IvG5b9zqxLqa8Lek8teG+DPp9PU+25bPgUqlLjGNEL/k4qKf/"
    b"0epDu/oeIMvyyzIds+kHeYl7vtfKSk9u27cKd+FmNR8aT6cbmY17FGQUhxixQh6XQbY3GmXz2mXJ"
    b"vJs2DJDWtF1RRmF5m91m5ijW0CBSjEsSQSCWsyzuJHaCFi7vYkeWNRsZJwH7HRE3TgBa82l368D6"
    b"v5w58SxgJZL5caXuycNwyIYrG/I2aaS5XQG5YapA1/dA6VSyPXnwftGAev0okrCU7xgD0DuHYV/E"
    b"23/DhdagKqzsfUe8BnteNV50zKOrNtrFxgTfGHHw6DBwjIq0oV5T+42B2rQ2Q8dbNXev92ZPgSaK"
    b"2ct0dDVHX60F4E/bljuh1TNyE+EbRNTB28D+UorREwxyg6R6W6ik6pFt70QMCToBFEtfAeczy4yh"
    b"VfyrGi4b710jyDb4LuBR1drpHQNA08YFdHEW6/CeyZ8wYY8b6GU2towGdnYwdkICc8Qlb9PQpFTV"
    b"jeKKj36uFy/3qS8300zHNdAv5xziqRirE6weVO3l2uaOegKGwLaQMVkTDvgNOt5N2zS2chwUY5sL"
    b"XnWpNo7IDN94HHMXJtSSLnkKUdxW7nbTVsNuCtOidfbV5R3EPb+e7BCRGhq5fZ69mcMbdcsQfdGN"
    b"0AaR610UQKoMjslZUZwgX3HqdX4Cv4ntR0lB35SxjsUdlYgx7hwxpyEIOF7pjUykD0UVmsiQtRuP"
    b"YPm2Yl3zgtkXxqHqTTewcvQ6C777V9DydX2XPFAN1PZqEoogEdKrida0mobE40djf/6p8d0cbop8"
    b"7M+Xcx70kAzpSaAKMi2BxPQTpjF3nR6pzeyh46xmpKz6QKRGUyPPgt8Gj2440XZy7omk+Visf8cz"
    b"M2By+/e6sORIrkpo7Bu0gJHlhMiM0qGl3f78hFS3tr5APEU3pj+xncicJ+irvf3npxaGgdWU2WZz"
    b"aOqiSKa4u63YE4YrJUdkdR+9d/lNJUKQApk7TldigkYDdVGihrw9fUGd2uiqDBcRg+Uj72qXBzjD"
    b"YCzOtSrVwdRTZzWhi97f4bs6q4dfGdQUnI6W/XwHLeW+JK9Wu9M+kn+xUnF/adjdwJC2rymUIJI8"
    b"W+GBzzNUP+9WHyWMzQ6nScVjTxf1pChzmEZ+k/UCzb9Yi1B/N/d8iiHc0ymmmIJDJbg9HIoN0ODP"
    b"YoqGNr24m8zP2PUbNPj+Cm9g4JPJzQBgRYHEAr/cGyFsNoHdNbU3kfVddyU3ykM6X+IDCV+F0yPm"
    b"MfQ/h5MK7K+XGT0H15Kwl48Y7iIEF/P31pq9rQ9fXA5w+VwZb9rjddmAWnGwAckn9kiO4DI7igZh"
    b"ipwOzbHEdDlAQpwvVi0i5zHOMASbnYq73ODquC8Pb9clJ+028afgXPsYZfS0cWXisweMMp1VGLCg"
    b"ua1XxRu3gd2w51sTdFQ9AIN+XdxkbI2nemAD3AjXoS/5eGoIC7AepmnBKNn2IqQEE/xx/TQT6zIr"
    b"snfNsKwc4r5TEsoCjq4uDCCy+h0HKiZzb8uWtbhY0kRlSsjh4JM0uQBZbJJQ2sEd+IkIukAySiWY"
    b"2wkTZZxjQg0MxmQsFB2SL5guBxTp9J5wiFD+hnZ3y7Tyy0JXshoIzayil6+vgReQcyNViamSyiJm"
    b"AxlW1cYsMlmifbdvZAmQsn25o5ha1r67E5OsrBLlAPlLb5YRvaykaJO0MtQqmgOgsUKQD+B55IIQ"
    b"ldZb9voL1hT1i2yMHJLN05RclllWi9+1TYx2F6fwlaHIikWUsjjiJ4JYJ3RmiWGdW25nmXShXxYt"
    b"xrRbVBVYCx6zE6nBwYOX1SDFR9eZrZXCG65Xq1uQb3v33C65YVq64NPO++Nwz+LWJXmh1hePnPf9"
    b"4LxqysS2bNU8jhGCupSwmXckBk5UDgI4jZ2iL3QrZBMMepMwGYOPuMoUkIxTRsCpdn4XqOQzGm2L"
    b"oLN6K9Vynb28z3QsKjrB0mNUxJPNVi3EdwmKrQEfsvCy2gkYFSw1jBrOni41sw4Zc7ubfBFxGesU"
    b"MaSffFmpjEpKkC76HLsTKsIxvvPlqrjks2rlHKH+gpLVtVYhGy7rt+7Y21BBTPU4yFG5ySRd+a8r"
    b"tqHrxP43uQxEuj2GvGZrbQ5CR60nszE6H1j/0E+2dF5Y4ZolhH1+d9qQ++MgjC+Hr95/I2Pjg9jK"
    b"Pb8XHSEOTN4gjXo6fSnpBvpCWdmAs52Mr/Oaz/9SmSYxNYX8sZTQ8127KEvpNNnYu1KSqOr42MN/"
    b"9vgcoyiYcmzVTV4p6VAaQXqH4YX1NSCAg3G2cCKvWLUOYNIlcu50rkxYdh1jW0ctF2YBunGn42zh"
    b"77h6/UHKiJZ6ORJfpOqOrRl8THaFa4ys4h1b56YwuuhYPkXdAadSlP7otB8IgVcOo0zFhtmkGAhB"
    b"mZA0rAe4Wdidc7wbNXpLJJDYA/ZdkFwT1pmW46P8SCYIa1I8Ge84PzmYNod1dUTzfP4hH2cFCNi/"
    b"LrKqPvJahUnb/emlF2mZrzk5f9BP2flVXquW1RHImDBzcqx8Z4RoM7ae+Zqt2y0Fga18tqX+DKKG"
    b"+X1l9YpJhABYlsXNTTIa20bMLRKB4PIhdJ63Rji3G0YDFG/GD51EFtarwWIfWKPbbCMWuWCMwzC2"
    b"HavBKbMZCt2GytAH4DNjV+WI/YGFZaPK2NIQbbIu09FVlbiVkWBSh6f01bEqUa/A4tDoZ+MOMqEm"
    b"sAR3zPkL6G8k+PSHfGm26TqiCewA2E7kgpR2HROzN6CDm2nQSwBGdVQGpdbgc14n+oTnM/1nS+VP"
    b"akU+GV3jEnzXtwNM4iQSUSDWLyrfUXVU6V6S89uknkDpeVl8qoCTZgd1q2TjlXzlUNw46LMB6b5y"
    b"ENpiZ4yl3Wg7zUhn53DRXWcwbS0tJ+lFnbFr8CgF2atSyeLZOKqyURfCdE6hoxtnMbNoFt1eQ2ti"
    b"CScNnGJPy+y6Ys4Khvluu3JchER1HL6oMcGl6twQswwQ2r+62uaipj3wptNw37XDJ+gY6bPTXH2D"
    b"WF6kEbYvUJImj3EKQRASyliEO0Elljx83Qd3R8ViOk6UJpc1Cr3kFDY0vUzzWS8SKiKt63Q0wTlo"
    b"SvtlI4mR5F2FqF56CyaO9KCqaa8mu1ZrjmQzHY8HNzBzTL+H0RdA9JixCa0Bg5dyD/HtnEhvDAcJ"
    b"u3QNQG3ND6giNlwIvG3cz1oIuRPaZLUdkTct95xpyTd+S6/g5CI3tcfXLD0YEZbGMT3ANjKizLLD"
    b"RaosrG9hiD8b4Gc/ubBzjVOXsBpfy2jIlG2cRHz1sdVHcunjQhTVtWizBCVAlAw1Xt/4sPlf9WpJ"
    b"Kj8WhI+B6TQxq8Qa1nsSNzntPs9B7OOMGW4Yw0igQzd44aygyFa6p3lZFBcc92+a6fh/HAQLyEXp"
    b"hcNq8cuh+yqv3R8iT/ORUMv+QzyGPqOxPctmKOIKLJYHn4vr8J3di9j6FWG3ZODloPsgNLPT1A/N"
    b"Gm8exm7VptUIbqZQ/MjkwovgzlGM53O4YYColwVFmIOm0wu/vuPx8WDtMNeEHF50OJOY4iS9yFwX"
    b"FYWG3tarUuTvyXj3YloUJeezmJHp4/fKxDHa6odVrb5Lnm4vNaCIhxFsCl6Au4Kx7N7AzVJN0qus"
    b"nc2L0USfzi6pKbrar8jeR1RLCE4pu/YOqBhfFWS2dUVIfasxynGgGvIDcqvT4HrwG2QL32gwsdXW"
    b"69/+8BhfoH4pQDZ/NNFr1HEOCKxj47itCmSSXnoqoUAIqi7cnPpvMibfCX27BLGl5pbYamtsHk6G"
    b"tMfIbLfc8AipYjukLRh+mufTiS+YYUlPDwmRVuOvbCPJ/d6Y473cbogHAbYcUVk4Cc05nFtBFra0"
    b"MKYBymaX9f1Ci7wRmKVGLmV9ubw5PDkd7v10+ma4P9jbx+Scw3cnxmr7K96GgT7M4Y/MYIuMd5df"
    b"zt7A8k7RhmZU5vM69EcOkhvwTI11s7iuHFtmc0epzKf8sMRpTlRJcd2P3kX83V43/eAC4hriWukv"
    b"v3W4vneZ9JdeNV2jb8XtbLhA1Iod0yAVjouQetiEJTSY+ig2BPZhXFxzcgqMkKNYGqLy/ZU0/tG2"
    b"b//9wEhya5+kez7CN+Hzzv3PIKMnvVRppPV4wutiltdFuU/qe7yAPKwXnC1zxZ5JRPiy27A2+fSh"
    b"Hj6sWn9XGEqZ0hPtsqgb5GTra2rCz1exytGc6Djt4A2POTv7gmMdR3LFs6z6qJ97NoSUb1l4bw6u"
    b"juRbzPGELYXz0XueaXx00TDs+A/FPmzUK7Dr46MWT7Yo9MkARD8ar37O9Ez5m4Lt3Fn7cNjxUJlg"
    b"J0VIyM4wRrnQWdEa5r1GB/xnYGiGL51EuOjUKG4NY1Rl42NMC+HIVYYvWEErZEAKlC2wou0zkPih"
    b"JsonogoeP5xQ1e4o8/cz8YrNDVYb7cVssFDMLm90QM21xFtmcWRDtUJRxGaXIqhjrI6FGv0VwGEx"
    b"Ay6H+be1QaHb3BsaS8jzOtxyM1O8xA3TV/SMsqq6z2K5xddt/Hy0zkishB6F7lv34QCZgRGHSMdt"
    b"yVLD2ChzHFYrjbobq4xG6PH6mDPNi+IGi5FV9iIxa5Gu1ncKSryCXXVJouZUT4/33p8cHR6fhpyq"
    b"WMvX9/9usH+wt4oLjhn0WA54Fb8gnR8pTaLEHKDAyhI8ZlkV4/mEpdWG8XcJ+OMYL7wOt3t/fvee"
    b"HK+9xwgwIM9d5xUQ/em0TeDpOErVJjOcRguFr7KQJsH0nTkU364FXKr6s/q7315nx4Zqbpim/1pl"
    b"2zery8J3dKVSCDdoxNHPfGd6bQeO35T/OwVJ428793dKifiMC/+IyEW9uRyjPM9o4Z6iI1ZrS6Gv"
    b"dW7xCwNNfvwg8LdjDICvKjCbEWPNJGdnKljViIWbqLaKmzPQXZsljAbB9uDLUVtGV1lNgSDudFlp"
    b"12nK7ZuvbREgKqAIweiEq9g4eLI/9YTU2FhX9B+w2K5hRbN2x8TN5nk3xcv3lp1EF20ZGxM6fOzn"
    b"a7BpiUR4HSw7LYCBTnZFUx3S2a13OM9mryi4gFP3Ip/WOmwFpeJ7rif9EX6e4fmVv32jE8rAGh/w"
    b"b8BTUkaH9UYVgDEj+2W9X3WfNLiyiw3Hn1MKlsxKBbEJPZcxPFaHR2vootOYkYKtKYxh0/KYNiph"
    b"MAl+OsaT+5vtY4URpxzmREd2cqLURmLO0/VIhkIiubXNy2GPs4F0LyE6moC0bllR2JnrNJ8pLrcX"
    b"NSoQYHsNQjja96BlSTbeqx2lgAfivRlwELMRvUv7EXeDCm5EziUB/fHS3FIe6NE8AY2AUJm/ERCD"
    b"zyCnYxkRdgWDygChwUHNW18ICy/O3krIcYQ4qSMxyZZs0Lx46+e7yb8Njg85z6dku0WqlAZQR0Mg"
    b"xzZEWtn+DvtxPkVyNN5JFgBh5W1IiRYSna3BDfUncvWcfG2GG9vYEHZb5JvH6TnTpJRZk03QIJak"
    b"3S84qUxeJW8PPgxkRgYvX46yb8PTu+OufML3CVSoMkz5WGe++Vac3yBTL7rf8PZnZsNnH/yb0HM1"
    b"DC5K5CaONWshTG6DZkodrqLkkMFDK/52RFzFlgrptRV4fEXjiQgSo5Qchr8LKjCKOOxU47La4mEk"
    b"SdL5/ABk+/eHJ6fHw72jo+HBftek3uRcs7HXD/PywNVgQz2nEjpXnCGtL+zk8frvU0T7Bt7gTAZM"
    b"GC9m43Q28gXCIK2wbfMpLWeHs2NBOtS8tJm68WEp89HVNDvA5werb0gwCJWetTumyZW4IfppfhbS"
    b"Sy5mzgt0P2nD2kGEqUg6bXyh1pWMhKwrKKb9HUAR31NM5qRihpnXCN36yRgk/BwzmT+XLgpKvCEd"
    b"WaO2UTXteV4SykhMNcYA6krXpth7rUWUPhERtV5j73cbbpgoE4EYa26Z1W+ZJ1fP72DdpyM9P9Li"
    b"Cy0Ker9n7U7MHuuez0NCNJGCybJjLuZxDYvk8jY9TZrKWzcPJa2I0IIlvQihfkU/vWL2zoSGCsRm"
    b"bCeGYdxGvEuMrA5wW1uLH+3uLe6E0986L3j3kMeFTKxj06jYB54rZrOvcUR4WU6gvEYRnqgpTDgP"
    b"Yn2+0EqnvEmnyreBk6DHhW4Jc0VIkGTooxJjrh0OnkuYdx6lc8eie0ex17cItmxGyU1AFhBMp8l+"
    b"V9kMS+tMlO53FK45DyyixAm9+StFn7n1DA+AKRzfmsp/qYRlqbqrjzKlUJL2l0ohp/WHZVYVU22d"
    b"gm0bxjcNG76zbqBx6kBE1K92Ww3ZVYYk0imeWT5qLLk9zn2gGD5g9qiC9iflX2h8iYSz9/0NUKai"
    b"/J49Rbce9J7AfxUL0rvOZz2V2c00LGYISTr3NC/voybJjHM85bYgiipvL+3BSQJMAeyhfrtUMzTr"
    b"AHZv3MPMdrPxq0k+Hbd5FOE7vgrIzns7cZJIhzAdiOMnQqK5znjfkC6RMLOc9jjErQp6r8bHcpNJ"
    b"x+c9vRAiJv7clzUSs2kO3eO9VR+h0XTJQ+3nFdlto6RgqM61/IRMqT0AVA81IPGKdEvOqYUfLyes"
    b"q0GzamkUBkVknDNEda2GWwgQaK3CBKgxuQbJCsqlx+vdVffWINAywA6xTyRuuMruhg7DhX99UVkk"
    b"VBRygrJaryq8IwXXhqsedvkn9+WRrhoEp32904FnfK+rWHNtaKx70EzWonK8PwUrFrVodr/JjmpP"
    b"lUvmCQgFzyBcVb9nYB7dbHVonjsztoV5pwnPDTB1jDf/4KnynairjznKMTzBlwaJJ3MZJsgoNIFn"
    b"nRHY1sR84VSHDwi790J8ES6FnZrWbf6rGpleKvTp0VuC4rfqmVdjz08UI91zbzYWfq46jXzjgoSb"
    b"X5LXMOcYdkVpqbWsszVW+Gu5hTUVdAgudkh9xnq/lmjH7J8QLtUIviy9LXfsJbCVEHTz1j76XfLW"
    b"JgSTuFccaYThEmaYkmcgx5zibMR5PQE5MFNGfT0K8qfNqXTCYtbAwFmYjSi2X+iZ1zy80x90AH9i"
    b"VGIT+UpnFcatZTMT4ORFiuGeUvbACkbF/JaTegIlorntJHndOL+IcTezQnx4EU19f6JNgaTabzYa"
    b"oOn3M7uOxi9ufg+zJ4sjjamjNc4rnbvJ5BnyCGDrxxSTpuK9ZPaHdbrJwasB4jXbqVX/+R//S1IY"
    b"9gBlKcDz/NVPXARm6PhoJK4NPzOovRQD2125TUxjrf61yQJltdFtkoRmAr5e6vczVTgiW4S/rmea"
    b"q5qwYfJfPl311zFb5kANSEOCQPIIyKH+2nXCmJBBbrwBVxjWWMNtdATs5tI2cwxnrJr8Q/HY/YDn"
    b"7jr6LmtD2idTJ0cPJTFqPtrxND/iBCD+pONx29hUBmEmYi0UE2WHEVK/m7qQkdaYoK7zZuy9jWFl"
    b"5xCZapvx1zLvDeIr2a0kxmo1R7RhVoSZw/tHjolwuIIdiMZRIanCgNdhY/14LVFe3Vuj4tzFLaQ7"
    b"57mZ6wcN0COBGmdZ8L7XtckHtrtWmakclf7EKZ22Emu/rkVYn5NWYA3x0VwVHsDMaObNv4kJ1aFU"
    b"ooEqW87zCQOAfe1VEV6u5l7VC8tBAMFLGcT/BYbcxydRuB3QxZlkDLT07wnDa4OArk2AN6VfXhlf"
    b"6ZEGvdyZfvKHL0qE1keNdAkgl3IuOh1YG4PRYgFPwGYQfYCpdn9RMwKijElTZIRne9TvQxLWDQ1A"
    b"3JbcoPvJg00yui8i4urX4p6XRRjwWra/LMqpy8PeNeBVDKFUID3AGsSmCl+TrlWFapJlda+1BEtI"
    b"y+ru84zSJeJi9s6LsibFUas5JmuLhwIEHcEG4sFGrhFxFphK9X5vXtJ6rbgVfEOnrJlSXcIc8S22"
    b"lvwtDIHg6skY73cRtVPERstoYNYMho0N1omG/U3me6wxUuqeJo/J/BqNbRlee7MKmNgP2LiN4kBX"
    b"5fehVxm40bJWoGclcdeL6ppskkAKv69tHINgU46wQ3cDlL9dStNIKD9Tz41nGk/+hXf2bcszS8pn"
    b"88U6kjiPJkRxys5LyWDHXnpeLuSXVs3tciFDzuSgk+tfn6gqghknkJ114KDG90GhVIdq/j1dzQj3"
    b"36Tnsq5ZDMnjDOkdB8HF+o0IcDpJa73XE5ICyUwAxMyFFTAxTgsKvcg0r4ULrJC5C3Oo3DdkZjBf"
    b"fhmyDrAwKxRld3iCaiFanOVjhdLsGnM20TfNtBn2B9RJs1DoXwUCLTmAszzWmsnoJj52JrH9Iy7c"
    b"cnsh08acTQuoF2tV1bLunOc5Y1r7C6+o/4cv2O7ul9gbnhfvUoUPN0YHo77ggY3QxAx03+eo7xEH"
    b"M3Rq+M0DYVoThFXODWu4HyxzcDAuDqucHNYaJ+7ooJM13e2siF9qXRmSQOAJvcgioZe/0i+y2XdR"
    b"mnn9dzsPWlw23S2Jodjg27c2dLXZGuzKDYl6Low9iXwpsGVeMB3z5oaCV6Z1Go3w7gV3sLUxcdOD"
    b"7YePNV552yhDxqpLJ+DARH4/0a9iyfwOG+PFJn5FN6NazMzeSx91L1N7r+sY3nzbdq8byXZ1T+uG"
    b"uBXqifX9S8PD/lE7v3aNa6wwH5Y6ENdnueOGZm2M/utqk4hH9N4dG+VvzQtzXk7ElpYZ8UXCQsZY"
    b"8wEgf+bKApedvJT9bV4l1uCiZztAy0luqTNwrtFQqLn8jfTjLBJ19dOG/f9EIO9WhZoNk1Ab/kuD"
    b"vHW3XLZ1tVpf1tBn+Xos4HhdBVZznpGesHbXHBa9UEft1n39jEImbTz3W+pjvCSznGbWswRlwDqP"
    b"2S8wi2B5jaocCvNn7PosM+FrepZzwcKIPhJGeC1R19HrfLXAyMx3kyAtaEzXiNHuq/Svi2yRoSkU"
    b"KouKKp22rU+U4qPL7AZfMBObsz4tx8WnmbZlklaMnMbNCnZj1Ssq31U/PZC7Z22Gjx+HYpMHd97Q"
    b"/dtYhfcRdpSuMlo0WxKX3zWPkC6e0UXi3qiliEd+WyRBqpvahMkoVRk7x9ZboM5Ko89nkE7bDPZU"
    b"J/5GSZIC4HWNPKaRTpmHRN4MdGa/eLbnXd2PjQvkvxbYxia/tMB0ETqSWTGTi0++YhKuiRCS9wuG"
    b"J+v7GX++PhOR9W0I50vTYQwSC1SiI6zQ2o5rvvQKlWmds8ag9LIb1H04nbh6DdPVl7Xl3NB4SFFm"
    b"o2OW44/sJrk6as8AZy0LmqiuW8DP89uR97UxIw2+N5ieup4Gpe+yueNbPruuC9/s2qBSXFvnONdV"
    b"LuhQ+M959i2BK+H2Kq+/7dXWu+7gS528Gm2Hre3sruOIivxke1k6ysDaGC7UJx0VvnrbmsPYjAX6"
    b"2RH4ijESvuJ2OaLpwCgNdgLOk6jYORHr1aKjjYx73+C3et4cBLcCMroWhXHNnA1R7yYyqW1wNzbc"
    b"wmTGqEr42iyu7IXJgKA78DUJLmidVFwFVq3xW6pKLzIMc3acod7EKtcvp8V5Oj2d5LC/xUg722tp"
    b"WxchGpD5rvdWxDPzarUj6VWZnOLr/Wu4YdmoV1zSGkIlh3X96LGMnMI9UngwPqMZYEiAcdskf5Jp"
    b"OZ2UnAZVeKiOhRn+jGWwjjOvO+7ThK4uNRKmb42x6mfTFUNuOeGNpS4NsUrru2BmCcPKZ1K+KpO6"
    b"YMr2hy8qX+MvlAWB5yM3Bz1gphlujtiYrrI9ODJH21J8k2BPVnFD4n5k5xrpjQZX26fsvKxHUs72"
    b"4IsA7XQ8+x+l2G3GISmc2qAYca2eSJnXWSa+KxNCuxXrxFCyeaJNFT+RS0MGLodLCZODRVJAxVs0"
    b"poO6C5JJu05F2gJfPg25+0LxXWlXWVMjZLZnnJKHBOyQH24ps339LHoCFzbg5zHe2T3rvB1/H8eL"
    b"0Hbl2+E5V5cOb9HgS+4Y6BEKhwEf3OgNjtmNxyu7g9EL4usSn6DtBwQkS4rCPnCTlTum3LPjE1Tl"
    b"EnrrKd+YE2sSFNJfz6tN5XPYysmIEhAED5/RN8n7yqjcWqciEYROMkqOaEEChN7StI+N9ofJd1Jc"
    b"cb4o775lwozH4AiBRVgtruFwtIoZIvUa8m+u5xF79kqnd2CKyN7ReiPrVmQa43irIBxV3U7MwJEv"
    b"bBHLNiqSBnZmm6adZz4mWYSvsj/zbdfWMzdrliWNuC9mHM614/MoyzPkuaPGdtQ67bf9V4QG/2r5"
    b"ihC8c46zEu46nN9ra7kp01+tY65p61l7UZvwSuxPUzQjMcOmUMTKHPSv2e3LnHZyxSRD+9BVq7Ez"
    b"dp7pmgI5y/kDKl9TCvXQcPK/G0WbEibmY5Cy8vo2fJbxZJOQYLtOYRd4PwxLHaYycZJ6iCRKO0vk"
    b"Fzd9UkyKWZ7Ew30HkQySKz0JjXlUwWX/03rF14P24lSKZu+Sd5vwvSPKIt7ad93kCwcHthoPSQCW"
    b"nHxnx8MQDjtroYN3q7aWPZc1ESnpIurf3Xx6Q//S/2fOhdaNoNcp+mK7aTWhBC3qk7C0mNPz3Crr"
    b"vrViNLsOcDsRdmitK59DaKBxRQ61/pnKaFcqH6r/dWcdRLTekf7pWgf3YnqmSMic9VVvXmSa2BsZ"
    b"Exzm1I9jijiPYXZbr1LICTvmZqXcEs4oVJzYmXor9BQluivnyfGrUWxJ9CjFUi+P0gPMtpCMe264"
    b"GhGnhuxRlU88UVIyqC4zfGNVXGhgfe5aqDLclpDwllUcGAz3ONhmYu4ScodEx8QDqy5oULfGzoNt"
    b"JPOms/WwjOHwlRQzosuwVcwoAWOm6NtGaEwSnF2fX/CvFF8o4/hj/HBkEYD4ARMUqdLW0Z0IiKw2"
    b"oNV1ooA/D+jrbhxGhmzNdXADXxlEuEWP2ftpnUYzUzvoQEgZecRpXAMIgDh7ypT7nPPFqjax6nC8"
    b"ZV7feMD7+FbHhc4Veyrosb99fmQ6JQXawy/nupPI6saDznsCtWs1tdur8lKvYt1aJ04MN4MkDUqa"
    b"1Uc+uo1awaBw/vkausYoNjhGRtF9dZGUkii69HsFYPQ+sSnQMiWVXHCosErn8+mt6faAvFzbY2a7"
    b"uiYtBZqEsCkqP6G7ai2dW04prohzPGc7fxvE9RydfIE4qcxKtuftrs69hEmMTvZeD4YH708HPw6O"
    b"rZOqTvP0w64fefFEfRJ6qbgpse5jqyi3qtEku05bIn5NoH3b1cuJ1DkxWafMzJZpgzZFT6xX4N8d"
    b"x0Q5ssX+Uzy9XEDXtL/mET4xpjxBoELatI7n0xZwKZGRCY3UCe/q3PKd+yhHrFjWoCaJ2R1ZpDAY"
    b"iFH6ayVTxXTDJhvnpjhc9jQR02d/BmxtQAxxobBiA4tE5QNF2gdYM7pCCqQM3jhQn+MVk1idmKMH"
    b"borftxYU7qIRnG3vKieYSdVK8ZKNy4VxrVG9tc464k3/3uflzs45SjvYw8bsn5unzTPvIXxuJD4N"
    b"JKfpMD7fbaYj9nIkcrqC6DUM8F3yQE2qwTVuUeMx8rdDxLAO9uTMkDgvn50hdLrX34jO+d3hO5Uz"
    b"sq1qnF6MzppPFEdNMsZA+PY814E6GwkKOqrSbif8zkDQSrASEbOKiaUkZs3nou9N+S62Gzpem7Rp"
    b"i25MxAeN7di8WPP+Volo75uxEPBuhExuo0xgY5bgqJY4zT7Xgxm6IpXtDsAf/2rLlp2eNRZPnisa"
    b"JhSqiPh7709+HhwPTwf/emozAi7HGIElql6TyZ6cTNcY+/qZ2knxquwtGdwh2ZNP6Nq4JHxr1gZb"
    b"Z06MaeUW8zxurOvFkNYv5Fp+/8bBbEfeOI7p5w30Rw7/HwbHJweH75kfPV/k03E/efnTwVsVWDRH"
    b"s29CaaW7Vb/tU+XTx53VudWkNeozVR8YsBpwDAOL4ZjK7VIKhR3xyOSGnmCjEJkUbYRQU+nMrvNZ"
    b"+1k3EjlEJxGxLmNuMAXfWEdmZewnKoCM0rnZ4A1ajNEJ5Ep8YkDVtK5gHzO7NprvsGTnpUrEPOHP"
    b"JqTv0KkYjfTbFda2bvUwoooanFiDIbMG/cR7PUXlXXFFVr5Tm0qESYFt473ERtsoMiwa+cRZgNOt"
    b"ZOTCF8r6Pem7Np2Jlf76vkKya+Pee90u11n6jjQR8zKhX4eZmZDlUu/edzSJ1nIN6i9mtkVCwYQo"
    b"snTLffMRXSwFQ0euE7/qExAbXtY1k4g0cJcrW9Vo/dYP7OFk8iEDbUEzrUbYahP8ZTrenS+cR2Zc"
    b"cD6emtWqgQhl1OzFYCJDEB8CXcejrVzPxNkZ4g3oxjmWzgzVWa+Cq0YfH35zUsodAKK989VZx+97"
    b"+rPmYuJtJ+ShGGuHvouyTXSU/TK1fJKsHfRLNW2figT4nXKx26GmFqJHRTFMb0Y7HXQoPC5ln4An"
    b"ZX2epXXQwHxxGxhOd6hY4H6DUOxX9/sPWGaVf4sDMQttomOJw4FkgYHQzgaXJScf47TpAOIs+2dG"
    b"oZJi16p/qZp7D3+oe0Ixg+aOqK0TqvpkHGPws4GT+fxGl9AIepn9QBSzFvHMNfVjfChW0nx4V/HV"
    b"Czghkm/aQG2NAsA4uwCSdFQCGSrr2/anfAYtgfsaDo+PjoZ/PTgdDCkF7YeHw2GLk12peG0Kll1m"
    b"gyhdByrwhVNKNltcZ37hpzKvRRHNZeOyUI4mMZ+6fHRl1F1RoY7YeugGhIpv6YZFQeiHxLBvnZCS"
    b"NqC7eT5f2VldXF5Os6P8COpLdwOs/R4tqdCWfgMTcsBI2VhnFiN/vXSGxvD4J/5bG/i0Mnz+mucj"
    b"fIjOZ+oPrEWqlPADtvmUnV/lNQabg9bE/aFXODsOAvVX9vqwoA/5OCvC9Zj56hyUvKK7DQxDtxII"
    b"vmOM0LwopnKtgCzQ3fy8ACmxh7iWoeCzJCDtt2WeaJ24qRlgnbkN9hdVR3/TcBRFhdXSOyaUipce"
    b"4hwI6pi/YExA2EAT3A9WHAl817wjfuw/016GpGxu7gf0scN/DTrwkdBuo/ePcbsjVFiL7OtxiZs3"
    b"BPd5paOqOA6HDm50lmWBCvszG2708BRMSsd1NGFceCSKMqGD5Nv9drz5mkEeiuadncA2GtBz8DmX"
    b"9qdNj8MNup6mVwdU5CYYBU8/PES1N3cbfElFloFtJ4D7UNmdKzRrbHSeYZzQBcXkjjWUseAtMoZK"
    b"B98JFqfa5VzcOxtBapUO/vP/AkXTnWQ="
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
    b"eNrNfdt2G0eS4Du/onjGawBtsETRllZNWvKhKLrFHonSkLR7vTpasggUibKAKriqQJot45z5h5nH"
    b"fd5f2Pf9lP6SjUteIrOyCiDd3bvu0zZYGXmLjIxbRkZujIq8qqObbJwW0fNoXIwWszSv4+u0Ppym"
    b"+PPl3dG436vqMk1mvcHeBlcobtJymtx1VVEgts4kTcbTLE+7KmkYW2uc1kk27arDELYG/DtPR3VW"
    b"5G+Sy7SzqgW11at5Bh/LTmwwiK0zh4m+XNR1kXdVQ6gtH5NlWpdr1CWwRmWeevUyWTViBbh1mbgD"
    b"V99fp8m0nqzTwIQgbQNEOaurE1i48n6eF4t81D1+rp9o0MYE1mpEzyHQzNv9/3a+/8PZu7f7Z0cH"
    b"5yeHZydHh6fQ1lMNcPzu9OzkfP/9+/OjV/C9VybzeZ2WW7im1da8+JTOinzrZqenK5wc/nh0+JfD"
    b"V9DYm/2fsK13lz8DrcVXZZr+Ne1/2Iii3m1V7T56NCpms0We1VlaxXlRxVUxypJpb2gh5otyPk3L"
    b"FDqLAVoWXS5Gn9IavpbJaJoG6nItaLcuYxjtKG0WjpPZooqzorfx0WDk5Ozg/ODd8fdHf2oM/TPU"
    b"z0bpaVrCFq92AxOL/BqLcgqAwEYW+S7+K57G10VxDQOG6ew+/uPX2zu95QBqfhxsLJ1VOTt8c/gW"
    b"1uOn85c/ndGafLP9R7MstvT0bP/N4fnbozdvjk4PYeCvEPTxzvb2tob98ejV4TuCe+PDPRNgr2Gl"
    b"kRZen7863H/15ui42eoTAX52sn98+v7dydl64G8PXx3tt4J+vU2g0xRYSkrEnC+mU/5QFsXM+VCn"
    b"SNzAFvaJgzlls3ScJSfATIOFSb5Ipu/9DvjzwQRZxDRUIcmwQq8nP+7n1W1anqTVYlo7dZLRKIUd"
    b"Mn4NhOcUzNN8nOXXje9EimfZzJ82fv4e9u2iTE/rpIQm921FxfETaHKc1OnZ3TytsDC9jU7Tuj/g"
    b"NqAoOTCsvomoljLiuaER1WVG3WzrD0qO7E+nxW06hpK6XKR6lcpZlieI0KtkWqmvSV2ns3l9OC9G"
    b"E9sQbGBA6vx9WcyyCuWk+hWXaVVMb9I+NqvmBKA3KeKF+hNNTwCx+4t60hx4XSZ5NS/KullEaGj5"
    b"TGR0ClzU7ceQ32n6yyIFdgrFW4+9spN0lGY3zpLRghAnhuWssVbvNgHml18rwqrqZJq+IghYmDr9"
    b"tRZUR4LAVNTy29SdJlX9I4LgXJwuTQng9BrwWYkhbVyBOKDlByZegCTORsfFbX8QIaeD5V6UeXQ9"
    b"LS6T6dkkq+J5Wl4VJdD/KAW+eotUthRtVJPilkbYh9oV/kCGW2f1lH7MoO/kmn5+RtD3rEcRZodU"
    b"+QQxZz9NiwQ3jKKqJfz383KDx6bIH7bsNZGBwM7m8+fc+R7AOVgzXz1FKUZUE8ZpqQksrosf5jDf"
    b"g6RKcZ7NSiNAbHWczJz1AH0q+irqV9wjjKQ3BSroRd9FvYh/gTDoUXta4/N6J3RhOZOKV6pwiOVW"
    b"9Yon2Xic4hbe1Hjd4/UrwxCEZwRR+hzP5U1W1TDtaxBOoI9Shd4w2lSrMDDoZKXHG1ifhF9o3m94"
    b"2n55iZuLAE74VwBCUDkDyg8N+OLqijRoBH2nfzeg0rIsSoL5IU9uAMPJ5ZSX5cA2DpVovtlVcy0H"
    b"2gYQWEvGpKniPKheCvQbACtBVwJmJiGxB0XGTNmatrWuNmP8XnzxmShjGUdffFZUsLzYowrYhqtR"
    b"OouDG0K2pvuJoo5KbhXuZ7mB/5c7fp6UVXqQzJPLbJrVd325OaEsmWmZ9MPJm9M0KUeT9/S1Py1G"
    b"CbYQT5JqEldT0Kr6jwcGI9QdN4DKLKjBgHZagp1e9OWXjeJZMU41BIvnLaAG0HNxIdV0FTv7jKob"
    b"9Lwb7QwjrLfrVRlGV2VyjbPejcLDXO5tMDJwqC2j9HqtQT4XV9HJfI7KBDE1IllSFntqOb4T5TGh"
    b"FsRZ8b0ajYuzgaqzqzi5HdCHOI7VoD6ld1V/8BF04xJUgvjnIsv7vSGMDUmih/JyeDO8TeoRmCZ6"
    b"pLo5ZagwsmAVjxezy7T0pzuwoBPWayQAfoKWf/uNpJgGpA49SD0IA2qoQI8Ah/wYyunj5qP/8WF/"
    b"678nW3/d3vrj+dbHz8+Gj3eeLb94BDRc1X3sd9AK+/WOA0xdD5qEIvHq0Y4hHNRVf66AZAiXPLMl"
    b"CUWeapbfZDUtml5FmLezjlaT05uIMeNuq70N4hMW5ssvpVyG/9dFSV8VoakvwHHI8jm1PEzvXUWh"
    b"IcA+Tn0ICzG0Y50n9SQHYeeJ/BGwsjo9nQMVJ9AOqtZgcDpsoEyvsl/JcpzPt26yFLTmLXeJxUxG"
    b"5d28LvQWV5NplMegz42L2Q8/oEnqTKq5jKr/rzpbgc2hEACabL+31RtqKb38fQMF4j6hXn5MpgtU"
    b"ndtGy8i6vKtJv17ZUJ+YapbXz/bLMrnrP37KW7E5bSoHc7SY9RXLoE6GWgRgc9HzF/wDxP9pjewH"
    b"G4Q1H5Ph0QdO2dvuMcvRbMSix9kvjj6Y1q+svsuCdKhVmLAeJ/VjR5FzFWfvs/IDtetKQsriJvF9"
    b"Jw1x6Ywx6oZ3Olo2xuSoia43KiJd0VdQrkBHn5CCon7tYj1QJNKx0Usc79UqTcw22KKKkd3BAGAr"
    b"RJ9Atc+p278o84S7dfY9WGHlK+Bfl0VS6g3f6n/SXKQ38MYKOhj3ttdVnaUk6V4Pqo+aMjAdVhIe"
    b"1MJlMr5Ot0aw+nWzhb/9+39Gj6JnEQFV1BBYSUBwvKXxawTMwTQORiPajlOYU1ESv/mAdvoWQX4E"
    b"maqojv4OaI+A+RxoQe13hnKHxN+wUdiCMf1liLPVI5wsrid1xxy7MVSlaf7gyqNiNgdTdSWFlGk+"
    b"TktQIUEmIrsZrFz2rRrM4QcuegXbGob0e5oYTdLRpznwy/qBDbC8rNqIjjErNybs9bQ+016IvmJN"
    b"WENtZqJNNGSicpFrRvK3f/9fSh9oc25Ena6NqN13ETV4BYG7osE4Qqx4cKc1S8pPZlan2BduL+yG"
    b"h40MPjjA5zxEqxQ46FmNFClU9R4KzlUNx6q5MIlTNFjHKNDfgvoUz5JfmTlvs/Slj1fToij7fc//"
    b"shVC9wBW/PH29vZAiwEPi9So4ubcw4Vl6HJmSDfRYo6OwzGYk3akywqGXaCJqaazvFhH5Mhu+m57"
    b"g4uA4HgPmm9KTrdKiQ7BMGtyxgHD/OA49IaeF28oXHcf9fISGeCXAXeEpcWiVt/0+oUdhVGbmzAK"
    b"OQnlnGCjLNKTopi9Qddkv5iO8Q9PCb7JigVSguvqjEdoMvQBC6CCkdtLWFTo6WT/l64f15M07yfV"
    b"XT6KuI6d96bpV9uc5Iol9RRsA23zJ7jVIgUbkzO1r6g8atZcRjTAqH9OfhPrOlCQyi1qvAMDveEd"
    b"b66ayJ5VFs0XwCNPx6EQqK0Iw/EXfwUmoFbnrI/aqNByxUWx2cK+T5vHrM51p+O3DY+45yPfk9Cv"
    b"fNe662t3YNWJA1qLzvcTPtnAAw7n+1t5TmEPLQIw9tDCOcQwRBtw8EdtpwKRe/QSuQcvUeuxS9R+"
    b"6BKFjlyilgOXqHncEnUdtkTho5YoeNAStbr0owBPskSmj2YUQzkClleCqSRLmKwbZzjRihMc7qFJ"
    b"d4MALYIWWGg/tKrl0t+gSZKBOrgMA02Q8Tit6rK4cyAcqtIbi9hHg+ZM+wEmsRSWs0PPLU3SeNZo"
    b"jxyWcVWO+JRV4DJ8/hF1nn401AHBe8cZSIKKbFLmmC1MnvpwTqQ2dVXB7uwnxz5OrtIfScE7wXE4"
    b"bhNcnCxP1G66+OJzwxOz/OJz073ELmESg+ySMNWUfyPoBIoaYH3RP8tN9mmHW8YjgtUNI1RfCeEm"
    b"269AVx4vpimdTexjWd+xwknECQ/Yb79Jlg5/bfqnkQOhtrnusxhNwYC32FCnPbq0ojBw2CmkHxOJ"
    b"kV380TkQI+VMn1Fo90uP6V8cLkVo44wtwH71KQKpz+5VVJOSiAz6qAIWN023FrAqqpHTSVKiqQlT"
    b"iU0Dn9X5zS6PdslOnJBaq6UqHvG+eB6ODLF69D8CGacU5RMtxMGMLhOLZ3zSsH47qhid5z1i+MkC"
    b"daQ6Y7KLAGHjrEReQfyftMtxBBpCHCFmJUJhLJ+GxJkkPofYBNlx0fH+2aMraOw2mU4BepbVFeyG"
    b"SQpIz6ooL6KzH06OB3HPjGkXlm9RFzMYysicntP6cu/BdcVhiOUz53W7RIvmVDS0nh6VO4iyqlur"
    b"san2wiSdzsHgNEeGno7nk00XKbTwUocyaGMbENjIgp3qQTc4ZYh+RViZDi+Q2iMZTIYG3dPFoaG9"
    b"DAV8uUCtwjFGLV/mU2s26LK8jwbZ9jD6r0+2oz9E/Z3oD3+wZWrJh9E3g8FAH8kiDWhF1lFKURQp"
    b"7dXX7Q1D0lyPJ0gne2KKkuO1aLxRe9AGuYOLbKyZkeLVQ56zf9Yv2bXLqamNDnYeUvrVLPDo+jIZ"
    b"feoLnu/JfDlHa9cwXTEo+n0EhdiQFeesNKZDWHYoA7fbQb+wqp8skBIRuRR2YjYOOiFYl4Ae0Ek+"
    b"0EYSyUYNJojMJTGqi/gnex6/SPfDXM1duB1I7QlbYE1uyofKPi/1vv5ULMrosixuK6CKSxDOn2Cm"
    b"wDIL7D2O2CsZUWQGN+BxIixZgxGJ2IQr4DZVh9gHdvjWaOZi3T11HQV8ByUo10EJ+MPFViqKVwEZ"
    b"HuuICs4/jEEp0l2nz4cguyEwDeGcbaljU5/kBtG34jSTxx1XxQwjneA37n7+KskUcND4JuIS6DQp"
    b"tDmaZ4frq0JqE7oWGwzE+SAHREfLBZhgPZcbeVZfjAvf//Ppu+O4ohOn7Oqu/9lIzhs8njd/4XLi"
    b"MT2SxJZL0RgHkJW7wnRUBctBeHfydHyDFclLWpP+2Jm/+NV4Eg8a9XWapyWpKLtyNexnC3oF2EnL"
    b"OSCpdmDFdwtckYt8FyMJzsq7CgRHcUwRsFU6vToai9ElJdDsrmNDa9QNo8+h4uVAagENe9pKEbN/"
    b"zwK+OFGwZxtqeGbCbO/Ro+gMlKbLYoFalNLpxjq+vkxnSZZXMGg8LYqSHDS9W/ibJGHciF5p8nPq"
    b"xTclnS08WpQlTBeLKFphu93IdF26UvwraSQEBe3goTqhG1KoEwgJFA1Ke0XXzFZdbJGLhocCcNrG"
    b"kozYuOFYDnv8dS+MgSOr9vQ5YM+E60UTHeTee7lA3oDSbD353K5u+X34VsqKaDMekjsX9mf/aOus"
    b"qUSoI2i7rl1LHuDtcVZ9n+UZTNKhDRUZ0PeoSZ1HIOnILl94VPdVtB1vP5ZRKT5Vitp7LsAKIgyZ"
    b"fRsmGsyXKnoeodY39WQUTOMMI1TpRWs4uphskC61DsNqFB5zTKWhjHzhRhUV8znqNeObJB+hmzm6"
    b"FYoWm1lXZQLUF0uFiRu0egxxC6aBZDw+vAF040Essmg+XVQnVh4bgbptlewxl9Xwg3NVk7w0G85T"
    b"FmdFqWerJ4Jbu6Nrg69VXW+0IplQrJVHsnhrpc3SsAit7phUPYHaFaMk3dsZ4/o8ZqOhBqtZsEJv"
    b"BtPQcaMatfIKjGKjhOuhr6H0rmBVvffce/e8OSrVn3dj2q7VpaenxgxDQps5jqgUBqksCezXsslJ"
    b"Uh3+CgLyXzE2kIJ+hhHGCTox34ohUGyQG+Kk4oVE8KIG2ORIo6ziiCQCNGxQacmfTKeDZlAiNorB"
    b"iwjUjFlsxqAoJQBp9xqZNc8F7ORstpjhtvwVfzjzMhzbqTQg248mBpagasB++/a5bivY/xkst+k8"
    b"0KfFmGb8/RaEsiKMCJVRWwpd0zS/BilsB9NECEBm49M8mQPR1npqZg+FFp6vLNn4nGEkgm3gjzke"
    b"iuAPFduCnwowGdNf6ScGYuhtpWI42K7liBv965wiKOAPFVFxnk5hjOn4vOJTYtOEjZYAYB36QHej"
    b"Bo0DRyO2NhvrEOv5DKNn2zYOtAln5jqMHj/thCREDKNvLJBcvthMns2fy6JAD1dPWGS+T4wQimFh"
    b"qA2qZXhZLKZjRttBUo2SMSHtbIKDoa8noN1eFreGkwE8fn6blNWEHAzFdJTkBf48hLWZEO5cZDWp"
    b"gOODKiAGHVk0xNVc8CrUBfDu3keLm8AuVy3EXN2ABsrYxM0pGg4sXIuEOMtH08UYAxsxyNS0oe8z"
    b"hfqJq+yvbG+GelL7RQ+7L+MdNSjNUm7NbqD2blhn0A30uzrRbCU8XJzNdhiDtBIE8CxIV51rrHYt"
    b"LjIHevF2pBsezTV2K8VcI4CnEAf2ag2jbdhcTx4PWlvHUdy3bazTbNmFsfgCoFaMmdEgLwtw6RC5"
    b"E6wVGvy3YNBPsbcAyxJBLrMUBVFkGAh3D71+cGJZ3KXkSriGoGN/wo1CqzhPR2BUnme0cafpTUpM"
    b"YTLHf4OsOIdfHwerIjcE/XgMkHuNdZfDaOebgV2mTV1uh+Fg0VvGBjAsIbT45Mkg1CZNZo3mCI5a"
    b"ery9HWxpMl+jmcmcaOrpkydfh8fD2FyjJQakETVa6xsXjB2bb0mJUtVnBwSUvnChFYQK2G6s+HIl"
    b"tyDxjYRGMbMk6kmJFTziQy/JmMLQ8SZg4NdChTZ+tGxdNkw+x7AgVQDCBd8tTElLNjVJ0TCoat9I"
    b"Dps3FbUl+KE3KRYlKTugCy5q1nuMroIB1Siy1PZCrDCeB4GtFdhUHkfTvcfUKREgbgdBfSvqqTFS"
    b"zSd/vEdFNaP7V+T5N+s1VlINEJHUWMvVhKn6bVEa1xUZLdVp9F8/frqz8w1GVA5WUJdVTe9LXram"
    b"pS9EC5jWM2LRn7KcObdQwpPr1CjH61GXq46aPmPTFS+ANjE8VSdUQQu0F9E3zwRt+E6vV3hZli4s"
    b"9dvbcrjpB8PABPOYgela1UVO3CbRh+a08SaLeozcxPquyZt4k5Z3xHaUb4mMFzyN1+fvDe4jRoZI"
    b"D1C80PgFcNCcsAQqIMW6BeizhULD9QME2rZlHKM9wM6VJUXKn9br8RxhlIH59tHY6MHBqbqsxdKY"
    b"nq1ZQXXg1Qm0iipTuG6LiWsDtjptXNsfU86H3g1pu7BT6L+6lXMVJ8FcnqPe6beypGkHdlmgavC0"
    b"wwLhF452ir3zVjT99zwIf1ze1UezAU+Tq9TndTx6TyPWn6Nvo+0gn8M0AXQrzD031LfR0AjDnXGY"
    b"j0Bwl/1BnNIv//iOV2MQY703xDw6TnI6CJn7/fZ5MA0Ka92+nyPWi+XRC/ri3pXqqoUkF/debtgJ"
    b"w1+/U//dlVc2ZB+UEqE+ZPnSJ7NDkKS3SajY39t6NM6dEBVvktyZ+wN8VYDtmkfRs6dQ2bl/C/qD"
    b"C6pg/4uChUpfP3XqKN2hpRYBQ6Wn2+bcA4djhnvxxWf8e4l3CKj35cSEH9LfElIB4O117nQ5uxAR"
    b"khfu9yZ+96/T34db0g0XAsEUWENT/RanaAB/XgBmAKoBxPiwAw4sCrSznOEdigu/slqCztrUAeBI"
    b"1+8E5gYB+QzdxNh7FZLsc0nXIdlFfNxOTTFCzOrU7VDec2qNv4p6u73oq2a5WtDmRdL2Kkr4Be+e"
    b"DvY8p6rSLL8T44SGo772wuIdRlPkX5OyN8mUOW9jb6cZBY63XyzDClsIxYE6U76dR4GzB5NsOobW"
    b"bRiI61lw7/tizJOTS47vU6ve8FhYhwIRpHuZlD71ZHHj5AF7FtGUsYKmASdzjJOn8fapeuvp4KZ0"
    b"cPwzJ3BcRO85wViUUbIJALn/FIJuF7Hoei6gzc7WmgoCujNhiuDW1QC5TXZ1trZZzZNct4qgoVbJ"
    b"zyNAQrd9jS9Ae2mEu6HDP/Od2fQaz7hlLk4ZNPoXzDTiVV5eDGSgl76odOOmG+yYJsGG5smeKwnk"
    b"37IO+YTw0vJNTBchcej424yaQHWSFE0AtZsqzxupMSZMbErt3+Hm0U7mzjpP5v9KaHweduq0OHNk"
    b"H1CEgQ2qne+8GrscL6qBFQtvghOoCHXUAI0hvIi2xUf48MgDAPUr3nkigh8tJmzKmylISS8oCKGq"
    b"tN6vga1fLkR8YlJmydYUUycZS84OH0ScT9zL6PV7u5aT+RK3rfmbR7m8ULfZ6bJjSxtK5l806RZ9"
    b"eWsR7WQepoEt7KtnYLwgFTk7MY1HjVnAKC9Qv7SD7QlOI7mcSsERLCNybyukhWkrnMwHLVwVQW0s"
    b"hCc+jQpulO8HpgFwtXTdmrG7hcJqTuzaaxmQwQOTCpiW6NBPhYXCEpoay+j//G9YQxdueaEiQw2Y"
    b"ULPBWKKkYahpq4DljDJOzbNpwVlUKchjw8ZJ7qr7DHXyKUVfhypkz+iuCSvgr4pqhImCS/bgpAh2"
    b"ZtIdqzChe1bTtXP74FfDoo8WC3zSJZIUGnj3XO/vlkBBifXqUHesztpgufqBFAlOQoVmRjRzOKob"
    b"vF8CBkz1YYaC6eD+9j//Q2SDWz4w/cSG4nw+Lr1Tx+84CwP0FwRcigQWF3sPTRPBgemGCFpOD+1Q"
    b"lObfUmPwwHwT4VG4p4yrx4DwgwcmrXBHYGMDvsMdr6MkcOmPYe/fpXUjt4UdDWmpD8tyQaPwLEFn"
    b"h5J3fvDgFBiife37MM23ON1tTj2DHOtX9y2kByXVOC7yNKonWRWpIfTE5UXJFdAB7LFkwXnfKr+0"
    b"/q6d01hkHdU6Nlx7q+V1L1Oq3ddQeKp+RlVyY6trX/YuJziEnyKqUeujyPCNn1uVkbMbpYjFB2ti"
    b"UsVBCrIhJpGY94fAIpBf/KMZegDA+MIVjHXOhKCFP5vNho/xVTYFTaT/kk+CFA99yFrTzFR8GArk"
    b"NfhoSzaVBg913NOssDXLlI966fleOGC+3UUd9mD/9lvDV/u8mYul6bkNpWtxG2pP3dIMDe5I4uJp"
    b"fA2nazOlC6edUjHtTvYRvKW6mGPUJUZsxz3p2OFLBM17QhTCb3PT/p4rLcHbvQ+9svo9Rb1SBzDG"
    b"XxaZ3L36di8V87ztrV3vCihggw2QKCEFybnT690JXftKr3fhoOPqXzNb8z/59mbH2FS39lYikAdn"
    b"gr5ORneYO+B0VGbz2iYcYePaEA/i640B/nMliEgdAHCCCu8GuyJJPxe1mXdL/wOb5CRYzicurUOH"
    b"tVd/9fuqyyG0yAHA5laoerKBKncZsQSgzVj+CwOKcV/Hj25gUxflI85iufU4fgL/g42qwwrin6ue"
    b"U7HI+aZ/pMblFdL5DvqkaJw8ZEpUeIgFYP/RpAnXfz6NQL+GNeSY5d7AFwSYHdmxRLkX5vEDJ5NM"
    b"C5IDmWWYgpgS+infmG3JLeCzEzqyU+k+2+9gqjBu/edRTtweb5Av8moxx9xCQNm4m9e44I+i7cE7"
    b"36ftzWB2hmZioOZWWZEIyAtJP8AYVroZQKSCE3OXHQY+pQh7P0xdRqf5cWlp8LozXYhUfGsQvAxe"
    b"uYlJ8dpMOGGpYWVejbWX+jQdLYBRizwOoSwGPUzpaa5QjDDFcm3Z/rzMbvCXGUOUjTGVAXq9H8L7"
    b"Wxlq6w3lPwPJ4V0OvPrDT67g4gxlbmxY0rIA+0yvZ5VdA/oxYzEvoiUplQaNfCE6ARAyN/jZ99A8"
    b"NOSEuwB02u2Y95p59IOUYdg+u9E333xtPiT1BIAfWWWbVkHd1dDpDtLLBaBr22SSKPKrDD7Ya5vy"
    b"SQ8bnAK4XuvxDlPho74+ycQrcjKsQ75mGxp8uQl6wptDZWyylTpO3Ft3KgbyZLCGf03Vogb3pktd"
    b"2DGw/D5f9R02spHdb8cGclJRB1rmC27MmZZtMOs0wx3mLjnougk2CIt8sxsIyQB5WmCdniHDnrto"
    b"7mja5tmAa14HDvTt3w/m1Nf2M1Rx6lG5udS8tyrJwGsWI4u8kWBAZEYBbkB3i2Sugfap4ydozKQK"
    b"dq5S81djv3REwbgxajYQRkVc+FeubfAdgT53Y2YGYv+GTa49U+62u+xon3UWp3ELBuywUtlUbPiU"
    b"nbkslrxfNtbYhHijrlKZRyp9p3N6BzrLdNoiIRs32lfn41GE5Ro3Ph2JjwFDR33+Icc5obGC2olf"
    b"irMxWkt0m1RKCbxHvpv7ZL1RUc4CMUEOHKBoSjXW2M3hq4YWzd7a0U4TAp8aHbesWmPNAhlN1X0+"
    b"dF7VGaUYutHW8Vqzal4i/DvMquVS4T9kVvxvI1rEoypDOSSY3KiR5s6rClomVsJMTY5cwi+kW/h8"
    b"it8M+GzSTU2nMoFeWPqaM2WSNqhdYjXzN7CGz0uZEYG/d/JIA4QSSvFHI6TuOz6Th0EmCrxfE80s"
    b"klhPeRixhYRSM+om6BMugHqwb6i5m0eQfrOMkOnUFwLNhH/cni5vS/t3vwvxbv5ZSsACcop7kpld"
    b"5LbhTCyNm7yCMfXcTG4UjEE7MyADiCsSPDFJnra752Q7n4t8pHQeywoFI2wZXG+2qJtsb9WFe+fa"
    b"vZMfq8n9aR58B5zxCNse1b+iTMoM5BoOYOxz+95b/Npr4elrTGuRt07s9+R76s761CqL18gAhW9u"
    b"rJUBypVrEhvL+2ebooA67CzYUSMFl6sXmp3dLjvX3dTtmWnDW16Wdu+doiTkUqpV2khqD4ekV2Ni"
    b"7eLz/8HEePXWk8NB4TnOKlVbJH3wOjnVtnskob0+3GZdJHntkZW/asxehDaQXTKavKIsN5yOoc+L"
    b"xo/q2KSxHFXMX3Dzmt9kZLbkbuqSH/dLGduUG/eTGd3ywpMVfw850ZARg72Ne8uGbrnQKRMeJg9c"
    b"WeBt1Xvy/9/H+9v5vqOybjyMBeu0Tj4npqRNAVbcuASDlH4COqJO5TBXjrS8oINCccdBHbW2XQ8a"
    b"Gp9XL/11DsPiO442uRj+afOS0d1i6PucOrKeTfo2X1xOs9H5p5RuZqEKy/9FJx5ertGJDJxrNsiE"
    b"YKCiLU4+Ji/r3NiMEKpjPk727xVxrlP3ozDv5/MtGpQLQKr2c/0kWqMQk6C7+jp9c6AsfnxYUeLU"
    b"EAj2q8gip46HY78ecUQqhdV1azLqqQITiociQjgVtySOC93f4pXgwA36pWD8B9d2dsxja2IeXIUe"
    b"fBv4g9Vn2XTxSZV13HtSdOs1o75SLmN7fYLuK9Ljpfo1jXCtb1fV+ip6uq2rPvyGFPazs/3NM3PV"
    b"zTuzYkyjnHud5ONqknxK2bdqdzyu7VBzGSsrOay+zQ3LiSqcBPrAFJ2/Nw2x2MwWMrU+wIs/Y0VX"
    b"opZI6IWHBreROAtMgAPiqTgGYJCQAMGQTIlPR/Qo6djGc6hQeiY2+UYiP+B2VnxKc3ywzJ5Zq3Fh"
    b"aI/DF4eRwh1Y3NlVhoGU7E9qPhug/hL3q9LptDCH4GIUII/4dBv0heJK+qphj2pXtU0Nqdy+hhfx"
    b"V+WQ5uU234rZrs93uGjN9JFrp470OMtuK1th8LWyTOoUkmoFeKPQKjBp8kbbXbnNvt7WnTJb2I0e"
    b"G3WXF4P87rQ+gga02DVLpj7ILP9zXDE6z1awQNP6N4Vv7q2/mST58CZgGtT3Nl2pTT03pLaGbdAY"
    b"0esd1j7DR2ropLvfukY8L7n/6CKSpG87wEHLexmBTUsblaQlI057d+1WVU3Fen+ZQ8dQRM+oKMes"
    b"+L8HEujPR+oJKu8EkeV3c99VFAGcjg/kI+jYinW5Sc8+KFO9NZKgs2K2xRkmmwGGJ2rK/LhHT6uE"
    b"85HvSmsgjyrYF9s95EmX3QfWQ1A3Kq+mnGqLfogb7TgzsC3cB+DpUgaVrAir65ykyCigTzPUk4Df"
    b"RT1eL7prwz+jLz4jJF+zaTl5JOobxdYyFKmC2Wv+d1gZNbK2p4rBfsvqoiQ2dYJLUWk5iicWqXiy"
    b"yWagsCV6Z5Lmh+NuFoW5g5eUmZ55x6zbFJTJ3mF6u17nWOVPdgtY4AavxSdBcSKnDKJJzzRl3xwO"
    b"13utAJtZsNVTxF3V+vYBYh5y26GzN9nIn6p4gmlOzw2cHP54dPiXw1fnJ4dv9n861QGjfM+hJHe+"
    b"avQD/PkRWbb820+OTamf1N1Fy/h/WQA3VgxqjQ55zKY/8WcsWlJGpNdhKz0TQ+jagxdffDatL8WQ"
    b"6fYJYmtJODNXjQ2EvWPf/QBR+AWQYB1xWzjcZtM/Qp4zPyVsuPqL6PEOSHvEbdtR1e94tWKNME77"
    b"TIeJZ9Hp8deI1Aq8vxId4ds8sFgo4Svk0+r4C9QeYHhCDpjjosv0CrO6ug+Y7EGFrJIuA855rVNd"
    b"Z6CIodBFqiGJjJztQc+HtLNLithpMMuhMQ7EO3cYWChYI6yn/QtXDpsCTvWBq5rchJso+xspmc2r"
    b"wH5wiZpctz7WyayjNlPHSbMiA+mNe1Rcug3INI4OMI5X2x/AZqP04O8Cru+QNN5+0Q252fvddw39"
    b"pxHdQqO+tL2FaF4JCelvLfnkPvRUmOfQyHuhyjSxOFgLD6pNtWIBZ6naMH9JL0/ODihYrN2Lzhbg"
    b"KOBctGOjJ5OZKvFsmclz0FoRxr1OXfW7P+gIWaVt6EesyuxpvrRWzzCoDL1upjWrQjtQwlpYHe1o"
    b"mKQKFw5HOwYYJnNrerQBqz/4sSr3dQsnhFWYCGCkgimHW/x7a/H2ZahVh5HrQVjbWjun/WN8YVUr"
    b"ogxbUNK/N8uqGQWADfbu89hLM9BYPQRnzQonMTq7VHgh2MzHpM8gVFNO401j4ItTdp4PjTu+X+zf"
    b"WnGqOsew9a7zl5aAVS58B4KRaBQYQz5Ocjw5GZV3yPUj3iVW2GvBqfOM+EaoECEBVRxLsUyvj4hN"
    b"m8+PxrvR8bvTs5Pz/ffvz49eyadLquoWmKjjbvkk6Q8hYGpueKNS7A4agaykr2IQaxzHnlb7cehE"
    b"izFCRqAV+NovK64S+jYp83f5iVDc7EsT+sEQcUSfjT5N06NRc8z1KDRiJ/hWRdwCuz4/eHf8/dGf"
    b"Ylv8YftjjMXLj814r8ArcdZXJpejyB1X6m7UB1Ql5XVFGkaHs1WD2flMNIiSpG9h4PwYmOgN6ZO2"
    b"/q65/RQIUHCCB1wXa1tRzJsMBSH/6gBVnlmEVYOIhbKjmVmbF2i9KLKOWMLQxhVl7SGqyK3sdrb/"
    b"XOxz3LMMMMR3p9VdXj1HZqFxBcwu7WNe1+3BchBfOI21hVk4J30PjeQmaST0X/XYsvPm8+dlR/CV"
    b"eoDXNmEHInwTcVa9ZzYhI5QaooeJm9tUjzco7uJ6oJrP/IquZkDv/L1PHmwDvHWz05Pv+bivAXe0"
    b"IJ5HEm14g4iL/K15yV4fW5oH4L0jX/Vdkr0bHtAVL6ycFGLAzDJwI0fm8Mzr0dDNKotkhU0SRZty"
    b"F7Z8t85VAdBkDZuGNbSANQ5sjF5jtzULv9uyoMOUlbaclgH4uC9VWvWob1eAtve6M3djHK6t3ErH"
    b"iZgX3j2Dxy3bE/dOQm/CB22hlpcaVzOJ1vM1FwN+NJAMKvQfOU3Hw+hyUXvGjhmyfPAUdBYn6hrD"
    b"paTrYo+Cp0CAU4KV4/0zUAvv9K1Wetx0GN1OMpiK4h8YOyGeO7UBEsPo7GT/+PT9u5Oz81eH+6/e"
    b"HB0fOm/9DJyQqf8f8Kq82RZx6FrTyHXlknp1LOPbM0lZ6sfG+BHF0LuyPqq14RPE3dvDV0f7K/AW"
    b"kLVhKYuuLU+m6ushFuY4vS7qLCE5nGhSOj374XiryKd30oJGebzhDfkevqJuJktPa7dyWcGvup7q"
    b"Cz6c0xruLvwEEy/yXT3Uu17ge6DZpjLTFWbnBRe1YEg9WARCUAfJ6RNE7UYc/OOEU8sCOHIqlAhb"
    b"XsmSutyHNaKMwhFFNz1rBAxk/16M/U6wzIbWc7xPCEaE7Wy2BvSEKkrjvt0/EKzqh/dsdoT3GFnt"
    b"vVPZHk0Z2oG+1GtlwOuzX39E7YK6hRdj1kfaLGicqzhH7fK0Rpf2ltcT32NunoN8ECfW+BlGr8Fk"
    b"xwfQX3dy4vWPQxSsQDXFVILy2XeiPtc6qNTbCA1OaaOsVXnFSe19r262rfA6901bHTIhF637ADUI"
    b"QF7Hfb6Bgi+4TWvnNCLJ3bSULUdHfIWlJ+JCRkl+k1RrV936xakNc0zXr4vQve40TG4Fyjk4MDkg"
    b"ed4xr8gboHARApPcrjEOgHJQQKeAye0Aq/u9YN/k8EbUBg7bGHG2YFPV+6XEqD3TuvyoSQ9N1X87"
    b"yYpFZa7QpjzaXdXsUL5ZsNucuLkFDpS1G329YzwxlBkRczcZnQfDaq9LVIPwBu4kq63XGtmKKbqc"
    b"AmDPCULG9QoGTPQUPyn5JJucqYxXxXhycSUhRS40iuk12387YbWTksTUkwRYH+aZNExPZ7qgi5KN"
    b"fFbt4zmTnBP2DfzEcHZ8GVMMK/11lKbjikgG2REp/zAkfcU1jsy8RsX8LsrqPfg/OV9wM9cltJxQ"
    b"FPfK/EsVNrTl7TpDLPKMIk9usmu88xZTHS99ReikhOAchiBye8zE9xMiG3Efubuv5rnkQ7e3/1q9"
    b"128fnZ/6IWs5VEHhq2mQK6olqyZpqg2ZOHrHVJkyqsbtRNlzBIQjH5odR5z15csv+UfMGY8RhfuX"
    b"YEaR88lGlag9Avt5lNJBHCnKghrRjALi4+PtSGSuNuEmqgl9kneANOnoCLK5DBYMM8n02t6fV+o4"
    b"E448YXtQ2EbUe1kWn9JyinnaOln6imAmdYDVW+8U5H2ZzhM6T1PHa4wCcRTypwSTxSGEQZM1744O"
    b"DrU6NS+L8WLEaT40Ju2hCEYqqVfcjVrqUrZfGorbo8diGOHvUPf6vkyuKVtR04l/pYoe4oaVKop9"
    b"HR5VM2+MMR5GyqN+FiyhoXOqFofLfG6MerfRg8nYRzacPczepYCJF86lExooZ/WYj/b8Aw48AMed"
    b"uivu1Xbo/BSyY+segPqcoyQc8Y+mi0WNnItd/76q48c5Nv130pHutIeXh/mXBdWtNo/Pgwk3TPRB"
    b"813z0IXR9tbVy+PQQXpDe27FqYySFQRMkcEt7ynxP633AWx95xLAi9BTJ87pjI9iN3dTOA8GXT7g"
    b"p5lEv9711Za0TvzPo0fRPqzhFLM8oimmm9YPt6MjMKuKKXk48LVa5RszzyivuMTatULuPdN2xx1r"
    b"OTk+3zzW/K/hxRGOtpZ8Cvc93WEnt9JBRfhvh6M7cLtebnfTluRZjs6iYWxYW8gCagt6C7gHdYJC"
    b"JTLl29mY7AN0TBa2Sqt4CUs6RMmQaxXXKBOrFN21Qgm64r68PSkwJ04+HY+TgVg/SMurd5+ArbWr"
    b"OsFb9plG99zloWFbKwK3tDpsnO7uhl/XGd/pSZd0Zb3pBmXsUO92ofc6zmjXc49LdhOOVrNrNQhl"
    b"BroHoXVHt7WT4eDexCMj3tooJ+CI9rmjvnuKAXGKPYbdz2JID4uLW9HEmhFyYVPkIXpgMPWr1Xvs"
    b"ZXPL4eX6rWLxy/Witd66MXCaelSximLwzCotcGFqflwDPl2+mrt2GD8yHWoAbSp7P8ebuIj+ip8l"
    b"cb6pU+fVCWRFOtQ1r1iZ5dP3pETiWfVujEk+611+as9Ru1Z2Wi9D6D8pA6hOCHmvTKDKOeRmSF6V"
    b"E9lJsesYw+s0maPvNtyWjFxtuK4cSCctq6FY6Sa3YsiGvwYyW/tPJTfuIIQqvYis9n16tv/GlSuC"
    b"mAIZrrTbsZk9G283cxIAPEnnCwCXqUqBJfdmFC3meBuAgPUNm72N5ZBvQe5tbPCRZkhNzkZAS37O"
    b"AKiCovTlooap36saZdpeWU/n44YK93T3hVJg6GbJ2+H58Ta6ukCP5Ooe7GyJ/1k6YgalfdwP8L/v"
    b"bcg0iP8MXyFMZX5ZJOU4vi2zOrUv1q50DR6EHGSAwMw4B6Gj1f7A81UOwR655LR/jt9pId1u1Oaq"
    b"o3At7aJbd7nlscUqovLX/b4r7/RlFr5t6X/v4ofyMq9PAB0kADg5SW7FoZvCPxMBiR5K2IzKOIeK"
    b"o8oxTwCnNm9zb0VC6HUpwiEE3bpxOcprnAOZyh1F93sY1gqlJaDpdeXIJBtBJMhcbtxm+bi4DfAS"
    b"xMkEmDGwEzMYqNEKz57VBaVO9+pwrzav/f8F3YRdhg=="
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
  const hasTurn = Array.isArray(iceServers) && iceServers.some(server => {
    const urls = Array.isArray(server.urls) ? server.urls : [server.urls];
    return urls.some(url => typeof url === 'string' && /^turns?:/i.test(url));
  });
  if (!Array.isArray(iceServers) || hasTurn) {
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
        in {"qualified", "unqualified", "open", "blocked", "offline"}
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
        relay_qualified_count = 0
        direct_peer_count = 0
        media_ready_count = 0
    candidate_types = raw.get("candidate_types")
    if not (
        isinstance(candidate_types, list)
        and all(item in {"host", "srflx", "prflx"} for item in candidate_types)
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
                    {"urls": server["urls"]}
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
