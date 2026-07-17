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
HARD_MAX_VIEWERS = 8
HARD_MAX_NEGOTIATING = 16
LIVESTREAM_PROTOCOL_VERSION = 1
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
SPECTATOR_MAX_CONNECTIONS = 16
SPECTATOR_SOCKET_TIMEOUT_SECONDS = 5
PEERJS_VERSION = "1.5.5"
QRIOUS_VERSION = "4.0.2"
PEERJS_SHA256 = "7604d8c31bec4f134b0d15c2d80b1d095ea18af005354f439f14291fcd7b4168"
QRIOUS_SHA256 = "db99dcaf40a926181bce4522477c2efc5924f6c4b29111b6a97faea477c9528b"
PEERJS_SIGNAL_HTTPS = "https://0.peerjs.com"
PEERJS_SIGNAL_WSS = "wss://0.peerjs.com"
PEERJS_ICE_CONFIG = {
    "iceServers": [{"urls": "stun:stun.l.google.com:19302"}],
}
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

BROWSER_PROVENANCE = zlib.decompress(base64.b64decode(  # generated from PROVENANCE.json
    b"eNqdVmlTIkcY/r6/wvKrC/R9pCoflGPBUcADFkmlrD5hEBiYA8RU/nsadKNEXc1WUTBMz7z99tPP"
    b"0X99OTg4zMzYzdTtyqVZnMwPfzuAX7e3VZa5PAt//wj/Dg7+2n2H+wtl7tTIhYHDhXPpJDv8+mPo"
    b"ucQhLNMyfR7JkiI1u3fGeb7IfqtUUjeKszzdlOeL2SQrJ+mo8liuUnq6KO1qlPPRw3Od8PBtPM/d"
    b"KI3zzbZcNlYUotIqPu9Vu7UzVr3ynQIMl33TWOrvl4N2s6VXaNpdtnV60proxk3qp053Jq38lIy7"
    b"fjyZF71qli9N3OwXctU/5ZPGchnFlXpx8fvvzzPPXK6sytWtj6cvFv/U5BMo5UkWlv/6ndAlomz7"
    b"luTQSwccY94pIo2wRFLlsGaQaIiAtAgxhgSDSgNkHeXISwYwQxQwhl9A+mYfs3hefrkjzxNzBogV"
    b"BkPtDPEQEw0spAZZATS0QFKnoFAeAIop8QRLDwmS0BvLNYFMPNecxsbNs93c563rV/ffBuisVa23"
    b"r+qvn34BDQFcAG614p5wxaX2GitDKafSMmw5NxJz6LQFDDJLFZDYSW6xExBgyQ93pf/++i5dl2mc"
    b"FG/TlZRBGf1Puj6WC3R9vCjtanyOrvffu6etNIIPBb1ZzIUU/mQhLpt31xUZ62XRR9EKkavK6Y3s"
    b"39TH5yfnUZHCUbOfdeJ2b8y7za4sqiM3mSyGvWavNRhESa8y+ild95r8NF2NpmZLCMI8l0pq6RAm"
    b"HDOFDBXCYQEIlBwDJo1VxguolTcuDCMBGGL8NV33+nifrlZLaY3yBCiJGAyFjSMUIRJYgJw3VCLi"
    b"mSE6cBRCzZTkXgVFbUlCkdD/3cu3cdib+/G5Fy1Ax6hhbPsjPYUmKNM6qR0j3nnPGKCIEumsEFBS"
    b"qRR3WgetKuu1gPRtxXzrnpVwGZSStDRVuUvfl89eo0/yKc/szxREOVYqtMWEC+pmAklCsRY0bJxR"
    b"ThAeVOR4sBGhDWRhm6AUSob9FRxCCdXr2qHDWfZvS0/Nl/P7/L1Hn5sJikTWSE7CPhEpPfBSI6t9"
    b"mF8yj5TjygbDCTextcEPLVNeMCMDephJwZ7kHL7/3OXRo53c6mJup+52mpi7PX2qdXkU5+NCF5lL"
    b"TRJEN8/LJpntwiT7kS2rnRtVnvhf2lZ5FsH+FPbWuoWbWzc3sft5DrpVmMzN4jxggN/1F/6xL4hR"
    b"0TwZVtfRvDG+sc0UbbLi8ns9vV6PkzYaiEH97HKaXq4XM+9u0GRS9NokVxfnWe8s6vUTGJHaajg9"
    b"AouR3ySbrHm/mq3q65e+8Fnz3lvSjoT8Mx6OlTMGIg2NRkJgpKlnVGm2jZKgHRaoabBHwUA4sYyE"
    b"oIOakBAzPDA0kONDD38KlfDR8Vylm+3Qm4ijMiyDjxG/aa2r1aPF9cMCn8Ri0m3JXiPqgBxcnSXs"
    b"/vhs3ryL23kl7jVmvd7wG/D1+qy+aUSrSVaL1i5uxPlD83IzLsasvdqcDsm8fX8++hXE31pZabeK"
    b"T4UnhdwxT5jGAGGoGApp6iVRwgSdeaGJhQRgYQAMGRtCnYWAtyQcMIJ/akU+BH7tdJqbUgiIxZ5t"
    b"vYBchlbhx5DD44vOkSX1qe9fDTYP7f51x61H364r+XEyW68f8kGFOZwn+WqzeRh0V4NWq+j1Jsez"
    b"zfCbjk4iPewMVFGcJslwhkesVTSKuH3xDuQnV7USLlWnKtjC+9jvL660W8gnPRcARZhhxhu0TQGs"
    b"JaeCYRkQ59zBIAIJKWWOAyI4QtRi78NxBpgQmMyGQ8ZHwGd28SbaOMTCJwhu+brWHdX6uFaLl8X0"
    b"dBLF/XC8pOsoO8XkpnXUrl3W9eyosblasu9F1Inv1pv2hZkd2eTseAg7bJrbDrhy0dSh+/NFG5+k"
    b"o1+ylLCQ0q7pz/CZS+EEohIoz5Qg4ShoHbZMa+C1hCwcP2BIXg8ZDGcCEAJZhY0wzttwXjTayhfp"
    b"8eXvL/8AyC2m+w=="
))
# END GENERATED BROWSER ASSETS

THIRD_PARTY_BROWSER_LICENSES = (
    b"Browser asset provenance\n========================\n"
    + BROWSER_PROVENANCE
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
    + b"Unminified distribution: /vendor/qrious.js\n\n"
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


SPECTATOR_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; media-src blob:; connect-src https://0.peerjs.com wss://0.peerjs.com; base-uri 'none'; form-action 'none'; object-src 'none'">
<meta name="referrer" content="no-referrer">
<title>Copilot Plays Pokemon Red — Live</title>
<link rel="stylesheet" href="./spectator.css">
</head>
<body>
<header class="topbar">
  <div class="brand">RAPPTER <span>LIVE</span></div>
  <div id="connection" class="connection">CONNECTING</div>
</header>
<main class="dashboard">
  <section class="player-column" aria-labelledby="stream-title">
    <div class="stage">
      <video id="stream" autoplay muted playsinline aria-label="Copilot Plays Pokemon Red livestream"></video>
      <div id="overlay">
        <div class="overlay-status">
          <div id="spinner" class="spinner"></div>
          <strong id="headline">Joining livestream…</strong>
          <p id="detail">Peer-to-peer video will appear here.</p>
        </div>
        <button id="play-stream" type="button" hidden>Play Stream</button>
        <button id="retry-stream" type="button" hidden>Retry</button>
      </div>
    </div>
    <section class="stream-summary">
      <div>
        <h1 id="stream-title">Copilot Plays Pokemon Red</h1>
        <p>Live browser stream with run details. Video has no audio.</p>
      </div>
      <span class="pill">P2P</span>
    </section>
  </section>
  <aside class="side-rail" aria-label="Live run details">
    <p id="details-banner" class="details-banner delayed">Waiting for live run details…</p>
    <section class="panel" aria-labelledby="now-playing-heading">
      <h2 id="now-playing-heading">Now Playing</h2>
      <dl class="facts">
        <div><dt>Location</dt><dd id="location">Unknown</dd></div>
        <div><dt>Objective</dt><dd id="objective">Unknown</dd></div>
        <div><dt>Player</dt><dd id="player-mode">Unknown</dd></div>
      </dl>
    </section>
    <section class="panel" aria-labelledby="progress-heading">
      <div class="panel-heading">
        <h2 id="progress-heading">Run Progress</h2>
        <strong id="badge-count">— / 8 badges</strong>
      </div>
      <ul id="badge-list" class="badge-list" aria-label="Pokemon League badges">
        <li data-badge="Boulder">Boulder</li>
        <li data-badge="Cascade">Cascade</li>
        <li data-badge="Thunder">Thunder</li>
        <li data-badge="Rainbow">Rainbow</li>
        <li data-badge="Soul">Soul</li>
        <li data-badge="Marsh">Marsh</li>
        <li data-badge="Volcano">Volcano</li>
        <li data-badge="Earth">Earth</li>
      </ul>
      <dl class="progress-grid">
        <div><dt>Caught / owned</dt><dd><span id="caught-count">—</span> / 151</dd></div>
        <div><dt>Seen</dt><dd><span id="seen-count">—</span> / 151</dd></div>
        <div><dt>Hall of Fame</dt><dd id="completion">Unknown</dd></div>
      </dl>
    </section>
    <section class="panel" aria-labelledby="party-heading">
      <h2 id="party-heading">Current Party</h2>
      <ol id="party-list" class="party-list">
        <li class="empty">Party unavailable.</li>
      </ol>
    </section>
    <section class="panel" aria-labelledby="details-heading">
      <h2 id="details-heading">Run Details</h2>
      <dl class="facts compact">
        <div><dt>Pokemon time</dt><dd id="play-time">Unknown</dd></div>
        <div><dt>Session time</dt><dd id="session-time">Unknown</dd></div>
        <div><dt>Last checkpoint/save</dt><dd id="checkpoint">Unknown</dd></div>
      </dl>
    </section>
    <section class="panel" aria-labelledby="health-heading">
      <h2 id="health-heading">Stream Health</h2>
      <dl class="facts compact">
        <div><dt>Video</dt><dd id="video-health">Connecting</dd></div>
        <div><dt>Run details</dt><dd id="details-health">Waiting</dd></div>
        <div><dt>Viewers</dt><dd id="viewers">— / —</dd></div>
      </dl>
    </section>
  </aside>
  <p id="video-announcer" class="sr-only" aria-live="polite" aria-atomic="true"></p>
  <p id="details-announcer" class="sr-only" aria-live="polite" aria-atomic="true"></p>
</main>
<footer>
  The join link is a bearer capability. Do not share it unintentionally.
  <a href="./vendor/licenses.txt" target="_blank" rel="noopener">Third-party notices</a>
</footer>
<script src="./vendor/peerjs.min.js" defer></script>
<script src="./spectator.js" defer></script>
</body>
</html>
"""


SPECTATOR_CSS = """
:root {
  color-scheme: dark;
  font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  --page: #0e0e10;
  --surface: #18181b;
  --raised: #202024;
  --border: #34343b;
  --muted: #adadb8;
  --text: #efeff1;
  --accent: #9147ff;
  --live: #eb3349;
  --good: #36b37e;
  --warn: #e6a23c;
}
* { box-sizing: border-box; }
html { min-width: 320px; background: var(--page); }
body { margin: 0; min-width: 320px; min-height: 100vh; background: var(--page); color: var(--text); overflow-x: hidden; }
.topbar {
  position: sticky;
  z-index: 5;
  top: 0;
  min-height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 20px;
  background: rgba(24, 24, 27, .96);
  border-bottom: 1px solid var(--border);
}
.brand { font-weight: 900; letter-spacing: .08em; }
.brand span { background: var(--live); border-radius: 4px; font-size: .72rem; margin-left: 6px; padding: 4px 6px; }
.connection { color: var(--muted); font-size: .76rem; font-weight: 800; }
.connection.live { color: #ff6577; }
.dashboard {
  width: min(1440px, 100%);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 360px);
  align-items: start;
}
.player-column { min-width: 0; }
.stage {
  position: relative;
  display: grid;
  place-items: center;
  width: 100%;
  aspect-ratio: 10 / 9;
  background: #000;
  overflow: hidden;
}
video { width: 100%; height: 100%; object-fit: contain; image-rendering: pixelated; background: #000; }
#overlay {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  justify-items: center;
  text-align: center;
  padding: 24px;
  background: radial-gradient(circle, #24242a 0, #0e0e10 72%);
}
#overlay.ready { display: none; }
#overlay p { max-width: 38rem; color: var(--muted); margin: 8px 0 0; }
.overlay-status { display: grid; justify-items: center; }
#overlay button {
  margin-top: 16px;
  border: 0;
  border-radius: 6px;
  padding: 10px 16px;
  background: var(--accent);
  color: white;
  font: inherit;
  font-weight: 800;
  cursor: pointer;
}
button:focus-visible, a:focus-visible { outline: 3px solid white; outline-offset: 3px; }
.spinner { width: 38px; height: 38px; margin-bottom: 18px; border: 4px solid #41414a; border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; }
.spinner.hidden { display: none; }
.stream-summary { min-width: 0; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 20px 22px; border-bottom: 1px solid var(--border); }
.stream-summary h1 { font-size: 1.25rem; margin: 0 0 5px; overflow-wrap: anywhere; }
.stream-summary p { color: var(--muted); margin: 0; }
.pill { flex: 0 0 auto; background: #2f2f35; border-radius: 999px; font-size: .75rem; font-weight: 800; padding: 7px 10px; }
.side-rail { min-width: 0; display: grid; gap: 10px; padding: 12px; background: #111113; border-left: 1px solid var(--border); }
.details-banner { margin: 0; border: 1px solid var(--border); border-radius: 7px; padding: 9px 11px; font-size: .78rem; font-weight: 700; }
.details-banner.fresh { border-color: var(--good); color: #8fe0bd; }
.details-banner.delayed { border-color: var(--warn); color: #ffd18a; }
.panel { min-width: 0; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 13px; }
.panel h2 { margin: 0 0 11px; font-size: .88rem; letter-spacing: .02em; }
.panel-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.panel-heading strong { color: var(--muted); font-size: .72rem; white-space: nowrap; }
.facts { display: grid; gap: 10px; margin: 0; }
.facts div { min-width: 0; }
.facts dt, .progress-grid dt { color: var(--muted); font-size: .7rem; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }
.facts dd, .progress-grid dd { margin: 3px 0 0; overflow-wrap: anywhere; }
.facts.compact div { display: grid; grid-template-columns: minmax(100px, .8fr) minmax(0, 1.2fr); align-items: baseline; gap: 8px; }
.facts.compact dd { text-align: right; }
.badge-list { list-style: none; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; margin: 0 0 12px; padding: 0; }
.badge-list li { min-width: 0; border: 1px solid var(--border); border-radius: 999px; color: #777782; font-size: .62rem; overflow: hidden; padding: 5px 3px; text-align: center; text-overflow: ellipsis; white-space: nowrap; }
.badge-list li.earned { border-color: #c99b2e; background: #4b3914; color: #ffe29a; font-weight: 800; }
.progress-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 0; }
.progress-grid div { min-width: 0; border-radius: 6px; background: var(--raised); padding: 8px; }
.progress-grid dd { font-weight: 800; }
.party-list { list-style: none; display: grid; gap: 7px; margin: 0; padding: 0; }
.party-member { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px 10px; border-radius: 6px; background: var(--raised); padding: 8px 9px; }
.party-name { min-width: 0; font-weight: 800; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.party-level, .party-hp-text { color: var(--muted); font-size: .72rem; white-space: nowrap; }
.party-hp { grid-column: 1; width: 100%; height: 8px; accent-color: var(--good); }
.party-hp.low { accent-color: var(--live); }
.party-hp-text { grid-column: 2; align-self: center; }
.party-list .empty { color: var(--muted); font-size: .8rem; }
footer { color: #777782; font-size: .75rem; padding: 12px 20px 24px; text-align: center; }
footer a { color: var(--muted); margin-left: 6px; }
.sr-only { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 900px) {
  .dashboard { grid-template-columns: 1fr; }
  .side-rail { border-top: 1px solid var(--border); border-left: 0; }
}
@media (max-width: 480px) {
  .topbar { padding: 10px 12px; }
  .dashboard { width: 100%; }
  #overlay { padding: 18px; }
  .stream-summary { align-items: flex-start; padding: 15px 12px 18px; }
  .stream-summary h1 { font-size: 1.05rem; }
  .stream-summary p { font-size: .82rem; }
  .side-rail { padding: 8px; }
  .panel { padding: 11px; }
  .badge-list { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .facts.compact div { grid-template-columns: minmax(92px, .9fr) minmax(0, 1.1fr); }
}
@media (prefers-reduced-motion: reduce) {
  .spinner { animation: none; border-top-color: #41414a; }
}
@media (forced-colors: active) {
  .brand span, .badge-list li.earned, #overlay button { border: 1px solid ButtonText; }
  .details-banner, .panel, .badge-list li { forced-color-adjust: auto; }
}
"""


SPECTATOR_JS = """
const video = document.getElementById('stream');
const overlay = document.getElementById('overlay');
const headline = document.getElementById('headline');
const detail = document.getElementById('detail');
const connectionLabel = document.getElementById('connection');
const spinner = document.getElementById('spinner');
const playButton = document.getElementById('play-stream');
const retryButton = document.getElementById('retry-stream');
const detailsBanner = document.getElementById('details-banner');
const detailsHealth = document.getElementById('details-health');
const videoHealth = document.getElementById('video-health');
const videoAnnouncer = document.getElementById('video-announcer');
const detailsAnnouncer = document.getElementById('details-announcer');
const MAX_AUTOMATIC_RETRIES = 6;
const MAX_TELEMETRY_BYTES = 4096;
const TELEMETRY_STALE_MILLISECONDS = 12000;
const VIDEO_STALL_MILLISECONDS = 8000;
let peer = null;
let dataConnection = null;
let mediaConnection = null;
let retryTimer = null;
let retries = 0;
let reconnectAllowed = true;
let telemetrySequence = -1;
let telemetryReceivedAt = null;
let detailState = 'waiting';
let staleDetailContext = '';
let videoState = 'connecting';
let lastVideoTime = null;
let lastVideoProgressAt = null;

function monotonicNow() {
  return globalThis.performance.now();
}

function showState(
  state,
  title,
  message,
  {showPlay = false, showRetry = false, loading = true} = {}
) {
  const changed = videoState !== state;
  videoState = state;
  connectionLabel.textContent = state.toUpperCase();
  connectionLabel.className = 'connection' + (state === 'live' ? ' live' : '');
  headline.textContent = title;
  detail.textContent = message;
  playButton.hidden = !showPlay;
  retryButton.hidden = !showRetry;
  spinner.classList.toggle('hidden', !loading);
  videoHealth.textContent = (
    state === 'live' ? 'Live' :
    state === 'ready' ? 'Ready' :
    state === 'reconnecting' ? 'Reconnecting' :
    state === 'offline' ? 'Offline' :
    state === 'error' ? 'Unavailable' : 'Connecting'
  );
  if (state === 'live') overlay.classList.add('ready');
  else overlay.classList.remove('ready');
  if (changed) {
    const announcement = `${title}. ${message}`;
    if (videoAnnouncer.textContent !== announcement) {
      videoAnnouncer.textContent = announcement;
    }
  }
}

function parseCapability() {
  const params = new URLSearchParams(location.hash.slice(1));
  if ([...params.keys()].sort().join(',') !== 'host,v,watch') return null;
  const version = Number(params.get('v'));
  const host = params.get('host') || '';
  const watch = params.get('watch') || '';
  if (
    version !== 1 ||
    !/^[A-Za-z0-9_-]{8,128}$/.test(host) ||
    !/^[A-Za-z0-9_-]{32,128}$/.test(watch)
  ) {
    return null;
  }
  return {version, host, watch};
}

const capability = parseCapability();

function createSpectatorPeerId() {
  const prefix = 'rpp-viewer-';
  if (
    globalThis.crypto &&
    typeof globalThis.crypto.randomUUID === 'function'
  ) {
    return prefix + globalThis.crypto.randomUUID().replaceAll('-', '');
  }
  if (
    globalThis.crypto &&
    typeof globalThis.crypto.getRandomValues === 'function'
  ) {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
    return prefix + Array.from(
      bytes,
      value => value.toString(16).padStart(2, '0')
    ).join('');
  }
  return null;
}

function setDetailState(state, message) {
  const changed = detailState !== state;
  detailState = state;
  detailsBanner.textContent = message;
  if (changed && detailsAnnouncer.textContent !== message) {
    detailsAnnouncer.textContent = message;
  }
  detailsBanner.className = 'details-banner ' + (
    state === 'fresh' ? 'fresh' : 'delayed'
  );
  detailsHealth.textContent = (
    state === 'fresh' ? 'Live' :
    state === 'stale' ? 'Last known' : 'Waiting'
  );
}

function clearDashboard() {
  document.getElementById('location').textContent = 'Unknown';
  document.getElementById('objective').textContent = 'Unknown';
  document.getElementById('player-mode').textContent = 'Unknown';
  document.getElementById('badge-count').textContent = '— / 8 badges';
  for (const badge of document.querySelectorAll('[data-badge]')) {
    badge.classList.remove('earned');
    badge.textContent = badge.dataset.badge;
  }
  document.getElementById('caught-count').textContent = '—';
  document.getElementById('seen-count').textContent = '—';
  document.getElementById('completion').textContent = 'Unknown';
  renderParty(null);
  document.getElementById('play-time').textContent = 'Unknown';
  document.getElementById('session-time').textContent = 'Unknown';
  document.getElementById('checkpoint').textContent = 'Unknown';
  document.getElementById('viewers').textContent = '— / —';
}

function resetTelemetry(message = 'Waiting for live run details…') {
  telemetrySequence = -1;
  telemetryReceivedAt = null;
  staleDetailContext = '';
  clearDashboard();
  setDetailState('waiting', message);
}

function markTelemetryStale(context) {
  if (telemetryReceivedAt === null) {
    resetTelemetry('Waiting for live run details…');
    return;
  }
  staleDetailContext = context;
  const ageSeconds = Math.max(
    0,
    Math.floor((monotonicNow() - telemetryReceivedAt) / 1000)
  );
  setDetailState(
    'stale',
    `Last known run details — updated ${ageSeconds}s ago. ${context}`
  );
  detailsHealth.textContent = `Last known (${ageSeconds}s)`;
}

function cleanup() {
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  const oldMediaConnection = mediaConnection;
  const oldDataConnection = dataConnection;
  const oldPeer = peer;
  mediaConnection = null;
  dataConnection = null;
  peer = null;
  if (oldMediaConnection) oldMediaConnection.close();
  if (oldDataConnection) oldDataConnection.close();
  if (oldPeer) oldPeer.destroy();
  video.srcObject = null;
  lastVideoTime = null;
  lastVideoProgressAt = null;
  resetTelemetry();
}

function scheduleRetry(message) {
  if (!capability || retryTimer || !reconnectAllowed) return;
  if (retries >= MAX_AUTOMATIC_RETRIES) {
    reconnectAllowed = false;
    cleanup();
    showState(
      'offline',
      'Stream unavailable',
      'Automatic retries ended. Ask the host for a fresh link.',
      {showRetry: true, loading: false}
    );
    return;
  }
  reconnectAllowed = false;
  cleanup();
  showState('reconnecting', 'Stream interrupted', message);
  const delay = Math.min(10000, 750 * (2 ** Math.min(retries, 4)));
  retries += 1;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    reconnectAllowed = true;
    connect();
  }, delay);
}

async function attemptPlayback() {
  if (!video.srcObject) return;
  try {
    await video.play();
    retries = 0;
    if (video.readyState >= 2 && video.paused !== true) {
      markVideoPlaying();
    } else {
      showState('connecting', 'Video received', 'Waiting for playback…');
    }
  } catch (_error) {
    showState(
      'ready',
      'Stream ready',
      'Your browser blocked autoplay. Select Play Stream.',
      {showPlay: true, loading: false}
    );
    playButton.focus();
  }
}

function markVideoPlaying() {
  lastVideoTime = Number(video.currentTime) || 0;
  lastVideoProgressAt = monotonicNow();
  retries = 0;
  showState('live', 'Live', 'Receiving direct peer-to-peer video.', {
    loading: false
  });
}

function markVideoInterrupted(title, message, health = 'Buffering') {
  if (!video.srcObject) return;
  showState('reconnecting', title, message, {loading: false});
  videoHealth.textContent = health;
}

function updateVideoHealth() {
  if (!video.srcObject) return;
  const currentTime = Number(video.currentTime);
  if (
    Number.isFinite(currentTime) &&
    (lastVideoTime === null || currentTime > lastVideoTime + 0.01)
  ) {
    lastVideoTime = currentTime;
    lastVideoProgressAt = monotonicNow();
    return;
  }
  if (
    videoState === 'live' &&
    lastVideoProgressAt !== null &&
    monotonicNow() - lastVideoProgressAt > VIDEO_STALL_MILLISECONDS
  ) {
    markVideoInterrupted(
      'Video stalled',
      'The video stopped advancing; waiting for fresh frames.',
      'Stalled'
    );
  }
}

video.addEventListener('playing', markVideoPlaying);
video.addEventListener('waiting', () => {
  markVideoInterrupted('Video buffering', 'Waiting for more video frames.');
});
video.addEventListener('stalled', () => {
  markVideoInterrupted(
    'Video stalled',
    'The browser is not receiving fresh video frames.',
    'Stalled'
  );
});
video.addEventListener('pause', () => {
  if (!video.srcObject) return;
  showState(
    'ready',
    'Video paused',
    'Select Play Stream to resume playback.',
    {showPlay: true, loading: false}
  );
  videoHealth.textContent = 'Paused';
});
video.addEventListener('error', () => {
  if (video.srcObject) scheduleRetry('Video playback failed. Retrying…');
});

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

function validSnapshot(value) {
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
  const badgeNames = [
    'Boulder', 'Cascade', 'Thunder', 'Rainbow',
    'Soul', 'Marsh', 'Volcano', 'Earth'
  ];
  if (
    !hasExactKeys(value.badges, ['earned', 'count', 'total']) ||
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
  if (
    !hasExactKeys(value.pokedex, ['caught', 'seen', 'total']) ||
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
  if (
    !hasExactKeys(value.player, ['mode', 'paused']) ||
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

function validTelemetry(value) {
  if (!hasExactKeys(
    value,
    ['v', 'type', 'telemetry_version', 'sequence', 'snapshot']
  )) return false;
  if (
    value.v !== 1 ||
    value.type !== 'telemetry' ||
    value.telemetry_version !== 1 ||
    !Number.isSafeInteger(value.sequence) ||
    value.sequence < 0
  ) return false;
  let bytes;
  try {
    bytes = new TextEncoder().encode(JSON.stringify(value)).byteLength;
  } catch (_error) {
    return false;
  }
  return bytes <= MAX_TELEMETRY_BYTES && validSnapshot(value.snapshot);
}

function textOrUnknown(value) {
  return typeof value === 'string' && value ? value : 'Unknown';
}

function formatElapsed(total) {
  if (!boundedInteger(total, 0, 316224000)) return 'Unknown';
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function formatAge(total) {
  if (!boundedInteger(total, 0, 316224000)) return 'time unknown';
  if (total < 60) return 'just now';
  if (total < 3600) return `${Math.floor(total / 60)}m ago`;
  if (total < 86400) return `${Math.floor(total / 3600)}h ago`;
  return `${Math.floor(total / 86400)}d ago`;
}

function formatPlayTime(value) {
  if (value === null) return 'Unknown';
  const formatted = (
    String(value.hours) + ':' +
    String(value.minutes).padStart(2, '0') + ':' +
    String(value.seconds).padStart(2, '0')
  );
  return value.maxed ? formatted + ' (maximum)' : formatted;
}

function renderParty(party) {
  const list = document.getElementById('party-list');
  list.replaceChildren();
  if (party === null) {
    const empty = document.createElement('li');
    empty.className = 'empty';
    empty.textContent = 'Party unavailable.';
    list.appendChild(empty);
    return;
  }
  if (!party.length) {
    const empty = document.createElement('li');
    empty.className = 'empty';
    empty.textContent = 'No Pokemon in party.';
    list.appendChild(empty);
    return;
  }
  for (const member of party) {
    const item = document.createElement('li');
    item.className = 'party-member';
    const name = document.createElement('span');
    name.className = 'party-name';
    name.textContent = (
      member.nickname ||
      (member.species_id === null ? 'Unknown Pokemon' : `Species #${member.species_id}`)
    );
    const level = document.createElement('span');
    level.className = 'party-level';
    level.textContent = member.level === null ? 'Lv. —' : `Lv. ${member.level}`;
    const meter = document.createElement('progress');
    meter.className = 'party-hp';
    const hpKnown = member.hp !== null && member.max_hp !== null;
    meter.max = hpKnown ? member.max_hp : 1;
    meter.value = hpKnown ? member.hp : 0;
    if (hpKnown && member.max_hp > 0 && member.hp / member.max_hp <= .25) {
      meter.classList.add('low');
    }
    meter.setAttribute(
      'aria-label',
      hpKnown ? `${name.textContent} HP ${member.hp} of ${member.max_hp}` :
        `${name.textContent} HP unknown`
    );
    const hp = document.createElement('span');
    hp.className = 'party-hp-text';
    hp.textContent = hpKnown ? `${member.hp} / ${member.max_hp} HP` : 'HP unknown';
    item.appendChild(name);
    item.appendChild(level);
    item.appendChild(meter);
    item.appendChild(hp);
    list.appendChild(item);
  }
}

function renderSnapshot(snapshot) {
  document.getElementById('location').textContent = textOrUnknown(snapshot.location);
  const objective = textOrUnknown(snapshot.objective);
  document.getElementById('objective').textContent = snapshot.phase
    ? `${objective} · ${snapshot.phase}`
    : objective;
  const modeLabels = {
    ai: 'Copilot playing',
    manual: 'Host takeover',
    paused: 'Paused',
    unknown: 'Unknown'
  };
  document.getElementById('player-mode').textContent = snapshot.player.paused
    ? 'Paused'
    : modeLabels[snapshot.player.mode];
  const earned = new Set(snapshot.badges.earned);
  for (const badge of document.querySelectorAll('[data-badge]')) {
    const isEarned = earned.has(badge.dataset.badge);
    badge.classList.toggle('earned', isEarned);
    badge.textContent = badge.dataset.badge + (isEarned ? ' ✓' : '');
  }
  document.getElementById('badge-count').textContent =
    `${snapshot.badges.count === null ? '—' : snapshot.badges.count} / 8 badges`;
  document.getElementById('caught-count').textContent =
    snapshot.pokedex.caught === null ? '—' : String(snapshot.pokedex.caught);
  document.getElementById('seen-count').textContent =
    snapshot.pokedex.seen === null ? '—' : String(snapshot.pokedex.seen);
  document.getElementById('completion').textContent =
    snapshot.completed ? 'Completed' : 'Not yet';
  renderParty(snapshot.party);
  document.getElementById('play-time').textContent =
    formatPlayTime(snapshot.play_time);
  document.getElementById('session-time').textContent =
    formatElapsed(snapshot.session_elapsed_seconds);
  if (snapshot.checkpoint === null) {
    document.getElementById('checkpoint').textContent = 'None this session';
  } else {
    const kindLabels = {
      manual: 'Manual',
      milestone: 'Milestone',
      automatic: 'Automatic',
      shutdown: 'Shutdown save',
      recovery: 'Recovered',
      progress: 'Progress',
      other: 'Checkpoint'
    };
    const parts = [
      kindLabels[snapshot.checkpoint.kind],
      snapshot.checkpoint.location,
      formatAge(snapshot.checkpoint.age_seconds)
    ].filter(Boolean);
    document.getElementById('checkpoint').textContent = parts.join(' · ');
  }
  document.getElementById('viewers').textContent =
    `${snapshot.viewers.count} / ${snapshot.viewers.capacity}`;
}

function acceptTelemetry(value) {
  if (!validTelemetry(value) || value.sequence <= telemetrySequence) return false;
  telemetrySequence = value.sequence;
  telemetryReceivedAt = monotonicNow();
  staleDetailContext = '';
  renderSnapshot(value.snapshot);
  setDetailState('fresh', 'Live run details are up to date.');
  return true;
}

function retryNow() {
  retries = 0;
  reconnectAllowed = true;
  cleanup();
  connect();
}

function connect() {
  if (!capability || typeof Peer !== 'function') {
    showState(
      'error',
      'Invalid or unsupported link',
      'Ask the host for a fresh join link.',
      {loading: false}
    );
    return;
  }
  const spectatorPeerId = createSpectatorPeerId();
  if (!spectatorPeerId) {
    showState(
      'error',
      'Secure connection unavailable',
      'This browser cannot create a private spectator identity.',
      {loading: false}
    );
    return;
  }
  reconnectAllowed = true;
  showState('connecting', 'Joining livestream…', 'Connecting through PeerJS signaling.');
  try {
    peer = new Peer(spectatorPeerId, {
      host: '0.peerjs.com',
      port: 443,
      path: '/',
      secure: true,
      debug: 0,
      config: {
        iceServers: [
          {urls: 'stun:stun.l.google.com:19302'}
        ]
      }
    });
  } catch (_error) {
    scheduleRetry('Could not initialize PeerJS. Retrying…');
    return;
  }
  peer.on('open', () => {
    dataConnection = peer.connect(capability.host, {
      reliable: true,
      metadata: {v: capability.version, role: 'spectator'}
    });
    dataConnection.on('open', () => {
      dataConnection.send({
        v: capability.version,
        type: 'watch',
        cap: capability.watch
      });
      showState('connecting', 'Host found', 'Waiting for authenticated video…');
    });
    dataConnection.on('data', value => {
      if (!value || value.v !== capability.version || typeof value.type !== 'string') return;
      if (value.type === 'telemetry') {
        acceptTelemetry(value);
        return;
      }
      if (value.type === 'reject') {
        if (value.reason === 'capacity' || value.reason === 'unavailable') {
          scheduleRetry('The stream is currently full. Retrying…');
        } else {
          reconnectAllowed = false;
          cleanup();
          showState(
            'offline',
            'Unable to join',
            'The join link was rejected. Ask the host for a fresh link.',
            {showRetry: true, loading: false}
          );
        }
      }
    });
    dataConnection.on('close', () => {
      if (!video.srcObject) {
        scheduleRetry('Host connection closed. Retrying…');
      } else {
        markTelemetryStale('Video is still live.');
      }
    });
    dataConnection.on('error', () => {
      if (!video.srcObject) {
        scheduleRetry('Host connection failed. Retrying…');
      } else {
        markTelemetryStale('Video is still live.');
      }
    });
  });
  peer.on('connection', connection => connection.close());
  peer.on('call', call => {
    if (call.peer !== capability.host) {
      call.close();
      return;
    }
    const metadata = call.metadata || {};
    if (metadata.v !== capability.version || metadata.role !== 'spectator') {
      call.close();
      return;
    }
    if (mediaConnection) {
      call.close();
      return;
    }
    mediaConnection = call;
    call.answer();
    call.on('stream', stream => {
      if (mediaConnection !== call) return;
      video.srcObject = stream;
      lastVideoTime = null;
      lastVideoProgressAt = monotonicNow();
      for (const track of stream.getTracks()) {
        track.addEventListener(
          'ended',
          () => scheduleRetry('The host ended the video. Retrying…'),
          {once: true}
        );
        track.addEventListener('mute', () => {
          markVideoInterrupted(
            'Video interrupted',
            'The host video track is temporarily muted.',
            'Muted'
          );
        });
        track.addEventListener('unmute', () => {
          if (video.readyState >= 2 && video.paused !== true) {
            markVideoPlaying();
          } else {
            showState('connecting', 'Video restored', 'Waiting for playback…');
          }
        });
      }
      showState('connecting', 'Video received', 'Starting playback…');
      attemptPlayback();
    });
    call.on('close', () => {
      if (mediaConnection !== call) return;
      mediaConnection = null;
      video.srcObject = null;
      scheduleRetry('The host ended or restarted the stream. Retrying…');
    });
    call.on('error', () => {
      if (mediaConnection !== call) return;
      mediaConnection = null;
      video.srcObject = null;
      scheduleRetry('Video connection failed. Retrying…');
    });
  });
  peer.on('disconnected', () => scheduleRetry('Signaling disconnected. Retrying…'));
  peer.on('error', () => scheduleRetry('Peer connection failed. Retrying…'));
}

setInterval(() => {
  if (
    telemetryReceivedAt !== null &&
    monotonicNow() - telemetryReceivedAt > TELEMETRY_STALE_MILLISECONDS
  ) {
    markTelemetryStale(
      staleDetailContext || 'Video may still be live.'
    );
  }
  updateVideoHealth();
}, 1000);

video.addEventListener('click', attemptPlayback);
playButton.addEventListener('click', attemptPlayback);
retryButton.addEventListener('click', retryNow);
function leavePage() {
  reconnectAllowed = false;
  cleanup();
}
window.addEventListener('pagehide', leavePage);
window.addEventListener('beforeunload', leavePage);
connect();
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
    return base


def build_join_url(base: str, peer_id: str, watch_capability: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(base)
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"Invalid spectator page base URL: {error}") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or port == 0
        or parsed.fragment
        or parsed.query
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Invalid spectator page base URL")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", peer_id):
        raise ValueError("Invalid PeerJS host ID")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", watch_capability):
        raise ValueError("Invalid watch capability")
    fragment = urllib.parse.urlencode(
        {
            "v": LIVESTREAM_PROTOCOL_VERSION,
            "host": peer_id,
            "watch": watch_capability,
        },
        quote_via=urllib.parse.quote,
        safe="",
    )
    return f"{base}#{fragment}"


def validate_watch_hello(value: Any, watch_capability: str) -> bool:
    if not isinstance(value, dict) or set(value) != {"v", "type", "cap"}:
        return False
    capability = value.get("cap")
    if not (
        value.get("v") == LIVESTREAM_PROTOCOL_VERSION
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
    return {
        "enabled": True,
        "join_url": join_url,
        "state": state["state"],
        "viewer_count": state["viewer_count"],
        "max_viewers": private.get("max_viewers"),
        "spectator_port": private.get("spectator_port"),
    }


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
    if any(word in normalized for word in ("stop", "quit", "end session")):
        return "stop", None
    if any(phrase in normalized for phrase in ("share", "join link", "qr code")):
        return "share", None
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
        livestream.update(livestream_public_state(runtime_dir))
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
                "view, and stop actions."
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
                        "description": "Enable the browser-hosted PeerJS livestream",
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
            return json.dumps(
                {
                    "status": "success",
                    "message": "Private spectator join link",
                    **share,
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
        if livestream_enabled or kwargs.get("open_viewer", True):
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
            "/vendor/peerjs.min.js": (
                PEERJS_MIN_JS,
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


class ViewerServer:
    def __init__(
        self,
        runtime_dir: Path,
        port: int,
        controls: "queue.Queue[dict[str, Any]]",
        livestream: Optional[dict[str, Any]] = None,
    ):
        self.runtime_dir = runtime_dir
        self.port = port
        self.controls = controls
        self.livestream = livestream or {"enabled": False}
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
                        PEERJS_MIN_JS,
                        "text/javascript; charset=utf-8",
                    )
                    return
                if parsed.path == "/vendor/qrious.min.js":
                    self._bytes(
                        200,
                        QRIOUS_MIN_JS,
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
        self.max_viewers = min(
            HARD_MAX_VIEWERS,
            max(1, int(getattr(args, "max_viewers", DEFAULT_MAX_VIEWERS))),
        )
        self.stream_peer_id: Optional[str] = None
        self.watch_capability: Optional[str] = None
        self.stream_generation: Optional[str] = None
        self.livestream_config: dict[str, Any] = {"enabled": False}
        self.spectator: Optional[SpectatorServer] = None
        if self.livestream_enabled:
            self.stream_peer_id = f"rpp-{secrets.token_hex(16)}"
            self.watch_capability = secrets.token_urlsafe(32)
            self.stream_generation = secrets.token_urlsafe(24)
            self.livestream_config.update(
                {
                    "enabled": True,
                    "peer_id": self.stream_peer_id,
                    "watch_capability": self.watch_capability,
                    "generation": self.stream_generation,
                    "protocol_version": LIVESTREAM_PROTOCOL_VERSION,
                    "max_hello_bytes": MAX_WATCH_HELLO_BYTES,
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
            self.spectator = SpectatorServer(
                int(getattr(args, "spectator_port", DEFAULT_SPECTATOR_PORT)),
                getattr(args, "advertised_host", None),
                getattr(args, "join_base", None),
            )
        self.status["livestream"] = {
            "enabled": self.livestream_enabled,
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
            self.livestream_config,
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
        try:
            if self.spectator:
                self.spectator.start()
                if (
                    not self.spectator.page_base
                    or not self.stream_peer_id
                    or not self.watch_capability
                    or not self.stream_generation
                ):
                    raise RuntimeError("Spectator server did not produce a join URL")
                join_url = build_join_url(
                    self.spectator.page_base,
                    self.stream_peer_id,
                    self.watch_capability,
                )
                self.livestream_config["join_url"] = join_url
                atomic_write_json(
                    self.runtime_dir / "livestream-auth.json",
                    {
                        "enabled": True,
                        "join_url": join_url,
                        "peer_id": self.stream_peer_id,
                        "watch_capability": self.watch_capability,
                        "generation": self.stream_generation,
                        "max_viewers": self.max_viewers,
                        "spectator_port": self.spectator.port,
                        "created_at": utc_now(),
                    },
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
                    {"spectator_port": self.spectator.port}
                )
            self.viewer.start()
            self.status["port"] = self.viewer.port
        except Exception:
            self.viewer.stop()
            if self.spectator:
                self.spectator.stop()
            (self.runtime_dir / "livestream-auth.json").unlink(missing_ok=True)
            (self.runtime_dir / "livestream-status.json").unlink(missing_ok=True)
            raise

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
        os.replace(temporary, self.runtime_dir / "latest.png")

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

            if self.args.open_viewer or self.args.livestream:
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
        "--supervised",
    ]
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
    if (open_viewer and args.open_viewer) or args.livestream:
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
