"""Private read-only operator dashboard for the phone, served over the tailnet.

The public spectator page answers "what is happening in the game"; this answers
"is the run healthy" — stuck counters, brain latency, encoder state. It is
watch-only by construction: the server reads `status.json` and never writes to
the runtime directory, exposes no control endpoints, and rejects every method
other than GET and HEAD. Pair it with `tailscale serve` so the tailnet supplies
identity and transport instead of a per-session pairing handshake.
"""

from __future__ import annotations

import argparse
import http.server
import json
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

DEFAULT_RUNTIME_DIR = Path.home() / ".openrappter" / "pokemon-red"
DEFAULT_PORT = 8787
STATUS_NAME = "status.json"
ENCODER_LOG_NAME = "encoder.log"
MAX_STATUS_BYTES = 4 * 1024 * 1024
# A heartbeat older than this means the supervisor stopped writing status and
# every number on the page is a fossil. The phone says so rather than showing
# a confident stale reading.
STALE_HEARTBEAT_SECONDS = 90
ENCODER_STALL_SECONDS = 60


def _read_status(runtime_dir: Path) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    path = runtime_dir / STATUS_NAME
    try:
        if path.stat().st_size > MAX_STATUS_BYTES:
            return None, "status.json is implausibly large"
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError:
        return None, "no status.json yet — the player has never started"
    except (OSError, ValueError) as error:
        return None, f"status.json is unreadable: {error}"
    if not isinstance(value, dict):
        return None, "status.json is not an object"
    return value, None


def _age_seconds(timestamp: Any, now: datetime) -> Optional[float]:
    if not isinstance(timestamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed).total_seconds())


def _encoder_health(runtime_dir: Path, now: datetime) -> dict[str, Any]:
    """Liveness for the YouTube encoder, which status.json knows nothing about."""
    log = runtime_dir / ENCODER_LOG_NAME
    try:
        modified = log.stat().st_mtime
        age = max(0.0, now.timestamp() - modified)
    except OSError:
        age = None
    try:
        completed = subprocess.run(
            ["/usr/bin/pgrep", "-f", "stream_overlay.mjs"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        running = completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        running = None
    if running is None:
        state = "unknown"
    elif not running:
        state = "down"
    elif age is not None and age > ENCODER_STALL_SECONDS:
        state = "stalled"
    else:
        state = "publishing"
    return {"state": state, "process_alive": running, "log_age_seconds": age}


def _party(status: dict[str, Any]) -> list[dict[str, Any]]:
    game_state = status.get("game_state")
    party = game_state.get("party") if isinstance(game_state, dict) else None
    members = []
    for member in party or []:
        if not isinstance(member, dict):
            continue
        hp = member.get("hp")
        max_hp = member.get("max_hp")
        fraction = (
            hp / max_hp
            if isinstance(hp, int) and isinstance(max_hp, int) and max_hp > 0
            else None
        )
        members.append(
            {
                "nickname": member.get("nickname"),
                "level": member.get("level"),
                "hp": hp,
                "max_hp": max_hp,
                "hp_fraction": fraction,
                "fainted": hp == 0,
            }
        )
    return members


def project(
    status: dict[str, Any],
    encoder: dict[str, Any],
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Reduce a full status document to the four operator tabs.

    Only fields the phone renders are copied through, so the payload stays a
    few kilobytes instead of the 26 KB status document (whose bulk is the clip
    list) and no unreviewed field can leak onto the page by accident.
    """
    now = now or datetime.now(timezone.utc)
    game_state = status.get("game_state")
    game_state = game_state if isinstance(game_state, dict) else {}
    heartbeat_age = _age_seconds(status.get("heartbeat_at"), now)
    party = _party(status)
    weakest = min(
        (m["hp_fraction"] for m in party if m["hp_fraction"] is not None),
        default=None,
    )
    return {
        "generated_at": now.isoformat(),
        "heartbeat_age_seconds": heartbeat_age,
        "stale": heartbeat_age is None or heartbeat_age > STALE_HEARTBEAT_SECONDS,
        "running": status.get("running"),
        "headline": {
            "location": game_state.get("location"),
            "stuck": bool(status.get("stuck_state")),
            "stuck_decision_count": status.get("stuck_decision_count"),
            "encoder": encoder.get("state"),
            "weakest_hp_fraction": weakest,
        },
        "stuck": {
            "stuck_state": status.get("stuck_state"),
            "stuck_decision_count": status.get("stuck_decision_count"),
            "stuck_reasons": status.get("stuck_reasons"),
            "recovery_stage": status.get("recovery_stage"),
            "navigation_mode": status.get("navigation_mode"),
            "navigation_memory_count": status.get("navigation_memory_count"),
            "objective": status.get("objective"),
            "observation": status.get("observation"),
            "reason": status.get("reason"),
            "last_action": status.get("last_action"),
            "improvement_cycle": status.get("improvement_cycle"),
        },
        "run": {
            "location": game_state.get("location"),
            "coordinates": game_state.get("coordinates"),
            "badges": game_state.get("badges"),
            "key_items": game_state.get("key_items"),
            "pokedex": game_state.get("pokedex"),
            "play_time": game_state.get("play_time"),
            "hall_of_fame": game_state.get("hall_of_fame") is True,
            "hall_of_fame_completed": (
                game_state.get("hall_of_fame_completed") is True
            ),
            "mewtwo_caught": game_state.get("mewtwo_caught") is True,
            "mewtwo_encounter_resolved": (
                game_state.get("mewtwo_encounter_resolved") is True
            ),
            "party": party,
            "completed": status.get("completed"),
            "actions_taken": status.get("actions_taken"),
        },
        "brain": {
            "brain_backend": status.get("brain_backend"),
            "brain_status": status.get("brain_status"),
            "model": status.get("model"),
            "model_calls": status.get("model_calls"),
            "decision_latency_seconds": status.get("decision_latency_seconds"),
            "reasoning_effort": status.get("reasoning_effort"),
            "emulation_speed": status.get("emulation_speed"),
            "control_mode": status.get("control_mode"),
            "phase": status.get("phase"),
            "web_research_state": status.get("web_research_state"),
        },
        "infra": {
            "lifecycle": status.get("lifecycle"),
            "encoder": encoder,
            "livestream": status.get("livestream"),
            "storage_free_bytes": status.get("storage_free_bytes"),
            "storage_artifact_bytes": status.get("storage_artifact_bytes"),
            "storage_max_bytes": status.get("storage_max_bytes"),
            "retained_clips": status.get("retained_clips"),
            "retained_states": status.get("retained_states"),
            "last_error": status.get("last_error"),
            "evidence_events": status.get("evidence_events"),
            "heartbeat_at": status.get("heartbeat_at"),
        },
    }


def metrics(runtime_dir: Path, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    status, error = _read_status(runtime_dir)
    if status is None:
        return {"error": error, "generated_at": now.isoformat(), "stale": True}
    return project(status, _encoder_health(runtime_dir, now), now)


def attention_event(
    payload: dict[str, Any],
    *,
    stuck_threshold: int = 40,
) -> Optional[dict[str, Any]]:
    """Return the first condition that needs an autonomous operator."""
    run = payload.get("run")
    run = run if isinstance(run, dict) else {}
    brain = payload.get("brain")
    brain = brain if isinstance(brain, dict) else {}
    infra = payload.get("infra")
    infra = infra if isinstance(infra, dict) else {}
    headline = payload.get("headline")
    headline = headline if isinstance(headline, dict) else {}
    stuck = payload.get("stuck")
    stuck = stuck if isinstance(stuck, dict) else {}
    encoder = infra.get("encoder")
    encoder = encoder if isinstance(encoder, dict) else {}

    event = None
    if run.get("mewtwo_caught") is True:
        event = "mewtwo_caught"
    elif run.get("hall_of_fame") is True:
        event = "elite_four_beaten"
    elif payload.get("error"):
        event = "status_unavailable"
    elif (
        payload.get("stale") is True
        or payload.get("running") is not True
        or infra.get("lifecycle") in {"failed", "stopped"}
    ):
        event = "player_unhealthy"
    elif encoder.get("state") != "publishing":
        event = "encoder_unhealthy"
    elif brain.get("control_mode") != "ai":
        event = "control_conflict"
    elif (
        headline.get("stuck") is True
        and isinstance(headline.get("stuck_decision_count"), int)
        and headline["stuck_decision_count"] >= stuck_threshold
        and brain.get("phase") != "battle"
    ):
        event = "stuck"
    if event is None:
        return None
    return {
        "event": event,
        "generated_at": payload.get("generated_at"),
        "location": headline.get("location"),
        "stuck_decision_count": headline.get("stuck_decision_count"),
        "stuck_reasons": stuck.get("stuck_reasons"),
        "badges": run.get("badges"),
        "lifecycle": infra.get("lifecycle"),
        "encoder": encoder.get("state"),
        "control_mode": brain.get("control_mode"),
    }


def progress_event(
    payload: dict[str, Any],
    baseline: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Report durable game milestones reached after a watcher starts."""
    current = payload.get("run")
    current = current if isinstance(current, dict) else {}
    initial = baseline.get("run")
    initial = initial if isinstance(initial, dict) else {}
    current_badges = current.get("badges")
    current_badges = current_badges if isinstance(current_badges, list) else []
    initial_badges = initial.get("badges")
    initial_badges = initial_badges if isinstance(initial_badges, list) else []
    if len(current_badges) > len(initial_badges):
        return {
            "event": "badge_earned",
            "generated_at": payload.get("generated_at"),
            "location": payload.get("headline", {}).get("location"),
            "badges": current_badges,
        }
    current_items = current.get("key_items")
    current_items = current_items if isinstance(current_items, dict) else {}
    initial_items = initial.get("key_items")
    initial_items = initial_items if isinstance(initial_items, dict) else {}
    acquired = sorted(
        name
        for name, owned in current_items.items()
        if owned is True and initial_items.get(name) is not True
    )
    if acquired:
        return {
            "event": "key_item_acquired",
            "generated_at": payload.get("generated_at"),
            "location": payload.get("headline", {}).get("location"),
            "key_items": acquired,
            "badges": current_badges,
        }
    return None


def wait_for_attention(
    runtime_dir: Path,
    *,
    stuck_threshold: int = 40,
    poll_seconds: float = 30,
    timeout_seconds: float = 0,
) -> dict[str, Any]:
    """Block read-only until health, control, progress, or stuck state needs review."""
    started = time.monotonic()
    baseline = metrics(runtime_dir)
    while True:
        payload = metrics(runtime_dir)
        event = attention_event(payload, stuck_threshold=stuck_threshold)
        if event is None:
            event = progress_event(payload, baseline)
        if event is not None:
            return event
        elapsed = time.monotonic() - started
        if timeout_seconds > 0 and elapsed >= timeout_seconds:
            return {
                "event": "timeout",
                "generated_at": payload.get("generated_at"),
                "location": payload.get("headline", {}).get("location"),
            }
        delay = max(0.1, poll_seconds)
        if timeout_seconds > 0:
            delay = min(delay, max(0.1, timeout_seconds - elapsed))
        threading.Event().wait(delay)


PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark light">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>RPP ops</title>
<style>
:root{--bg:#0b0f14;--card:#151b23;--line:#232c38;--ink:#e6edf3;--dim:#8b98a5;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;--accent:#58a6ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 -apple-system,
BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;
padding:env(safe-area-inset-top) env(safe-area-inset-right)
env(safe-area-inset-bottom) env(safe-area-inset-left)}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
padding:12px 16px 0;z-index:2}
h1{margin:0 0 8px;font-size:15px;font-weight:600;letter-spacing:.02em;
display:flex;align-items:center;gap:8px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--ok);flex:none}
.dot.bad{background:var(--bad)}.dot.warn{background:var(--warn)}
.sub{color:var(--dim);font-size:12px;font-weight:400;margin-left:auto}
nav{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav button{flex:none;background:none;border:0;border-bottom:2px solid transparent;
color:var(--dim);font:inherit;font-size:14px;padding:8px 12px;cursor:pointer}
nav button[aria-selected=true]{color:var(--ink);border-bottom-color:var(--accent)}
main{padding:14px 16px 40px;max-width:720px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:14px;margin:0 0 12px}
.row{display:flex;justify-content:space-between;gap:12px;padding:7px 0;
border-bottom:1px solid var(--line);font-size:14px}
.row:last-child{border-bottom:0}
.row dt{color:var(--dim);margin:0;flex:none}
.row dd{margin:0;text-align:right;font-variant-numeric:tabular-nums;
word-break:break-word}
dl{margin:0}
.big{font-size:30px;font-weight:650;letter-spacing:-.02em;
font-variant-numeric:tabular-nums}
.tiles{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:0 0 12px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:12px 14px}
.tile .k{color:var(--dim);font-size:11px;text-transform:uppercase;
letter-spacing:.07em;margin-bottom:3px}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
.bar{height:6px;border-radius:3px;background:var(--line);overflow:hidden;
margin-top:5px}
.bar i{display:block;height:100%;background:var(--ok)}
.bar i.warn{background:var(--warn)}.bar i.bad{background:var(--bad)}
.mon{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;
color:var(--dim);white-space:pre-wrap}
.banner{background:#2d1418;border:1px solid var(--bad);color:#ffb4ae;
border-radius:10px;padding:10px 12px;margin:0 0 12px;font-size:13px}
[hidden]{display:none!important}
</style></head><body>
<header>
<h1><span class="dot" id="dot"></span><span id="title">connecting…</span>
<span class="sub" id="age"></span></h1>
<nav id="tabs" role="tablist"></nav>
</header>
<main><div class="banner" id="banner" hidden></div><div id="view"></div></main>
<script>
const TABS=[['stuck','Stuck'],['run','Run'],['brain','Brain'],['infra','Infra']];
let active=location.hash.slice(1)||'stuck';
const el=(t,c,x)=>{const n=document.createElement(t);if(c)n.className=c;
if(x!==undefined)n.textContent=x;return n};
const fmt=v=>v===null||v===undefined?'—':Array.isArray(v)?(v.length?v.join(', '):'—')
:typeof v==='boolean'?(v?'yes':'no')
:typeof v==='number'?(Number.isInteger(v)?v.toLocaleString():v.toFixed(2)):String(v);
const bytes=v=>typeof v!=='number'?'—':v>=1e9?(v/1073741824).toFixed(1)+' GB'
:(v/1048576).toFixed(0)+' MB';
const dur=v=>typeof v!=='number'?'—':v<60?Math.round(v)+'s'
:v<3600?Math.round(v/60)+'m':Math.round(v/3600)+'h';
function rows(pairs){const dl=el('dl');for(const [k,v] of pairs){
const r=el('div','row');r.append(el('dt','',k),el('dd','',v));dl.append(r)}return dl}
function card(children){const c=el('div','card');
for(const n of [].concat(children))c.append(n);return c}
function tile(k,v,cls){const t=el('div','tile');t.append(el('div','k',k));
const b=el('div','big '+(cls||''),v);t.append(b);return t}
function renderTabs(){const nav=document.getElementById('tabs');nav.replaceChildren();
for(const [id,label] of TABS){const b=el('button','',label);
b.setAttribute('role','tab');b.setAttribute('aria-selected',id===active);
b.onclick=()=>{active=id;location.hash=id;renderTabs();draw(window.__m)};
nav.append(b)}}
function hpClass(f){return f===null||f===undefined?'':f<=0?'bad':f<0.34?'bad'
:f<0.67?'warn':'ok'}
function draw(m){if(!m)return;window.__m=m;const view=document.getElementById('view');
const banner=document.getElementById('banner');
const dot=document.getElementById('dot');const title=document.getElementById('title');
if(m.error){banner.hidden=false;banner.textContent=m.error;
dot.className='dot bad';title.textContent='unavailable';view.replaceChildren();return}
const h=m.headline||{};
const bad=m.stale||m.running===false;
dot.className='dot'+(bad?' bad':(h.stuck||h.encoder!=='publishing'?' warn':''));
title.textContent=h.location||'—';
document.getElementById('age').textContent=
 m.stale?'STALE':dur(m.heartbeat_age_seconds)+' ago';
banner.hidden=!m.stale;
if(m.stale)banner.textContent=
 'No heartbeat for '+dur(m.heartbeat_age_seconds)+' — these numbers are frozen.';
view.replaceChildren();
if(active==='stuck'){const s=m.stuck||{};
 const t=el('div','tiles');
 t.append(tile('Stuck',s.stuck_state?'YES':'no',s.stuck_state?'bad':'ok'));
 t.append(tile('Decisions',fmt(s.stuck_decision_count),
  s.stuck_decision_count>40?'bad':s.stuck_decision_count>10?'warn':''));
 view.append(t);
 view.append(card(rows([['reasons',fmt(s.stuck_reasons)],
  ['recovery stage',fmt(s.recovery_stage)],['nav mode',fmt(s.navigation_mode)],
  ['nav memory',fmt(s.navigation_memory_count)],
  ['last action',fmt(s.last_action)]])));
 const ic=s.improvement_cycle||{};
 view.append(card([el('div','k',''),rows([['strategy',fmt(ic.strategy)],
  ['verdict',fmt(ic.verdict)]])]));
 view.append(card([el('div','mon','OBJECTIVE\\n'+fmt(s.objective)+
  '\\n\\nREASON\\n'+fmt(s.reason)+'\\n\\nOBSERVED\\n'+fmt(s.observation))]));
}else if(active==='run'){const r=m.run||{};
 const t=el('div','tiles');
 t.append(tile('Badges',(r.badges||[]).length+'/8'));
 t.append(tile('Actions',fmt(r.actions_taken)));
 view.append(t);
 const pc=el('div','card');
 for(const p of r.party||[]){const row=el('div');
  const head=el('div','row');
  head.append(el('dt','',(p.nickname||'?')+' L'+fmt(p.level)),
   el('dd',hpClass(p.hp_fraction),fmt(p.hp)+'/'+fmt(p.max_hp)));
  row.append(head);const bar=el('div','bar');const i=el('i',hpClass(p.hp_fraction));
  i.style.width=Math.round(100*(p.hp_fraction||0))+'%';bar.append(i);row.append(bar);
  pc.append(row)}
 if(!(r.party||[]).length)pc.append(el('div','mon','no party data'));
 view.append(pc);
 const pt=r.play_time||{};const kx=r.key_items||{};
 view.append(card(rows([['location',fmt(r.location)],
  ['coords',r.coordinates?r.coordinates.x+','+r.coordinates.y:'—'],
  ['badges',fmt(r.badges)],
  ['key items',fmt(Object.keys(kx).filter(k=>kx[k]))],
  ['pokedex',(r.pokedex||{}).caught+' caught / '+(r.pokedex||{}).seen+' seen'],
  ['play time',fmt(pt.hours)+'h '+fmt(pt.minutes)+'m'],
  ['completed',fmt(r.completed)]])));
}else if(active==='brain'){const b=m.brain||{};
 const t=el('div','tiles');
 t.append(tile('Latency',dur(b.decision_latency_seconds),
  b.decision_latency_seconds>25?'bad':b.decision_latency_seconds>12?'warn':'ok'));
 t.append(tile('Calls',fmt(b.model_calls)));
 view.append(t);
 view.append(card(rows([['status',fmt(b.brain_status)],['backend',fmt(b.brain_backend)],
  ['model',fmt(b.model)],['effort',fmt(b.reasoning_effort)],
  ['control',fmt(b.control_mode)],['phase',fmt(b.phase)],
  ['emu speed',fmt(b.emulation_speed)+'x'],['research',fmt(b.web_research_state)]])));
}else{const i=m.infra||{};const e=i.encoder||{};const ls=i.livestream||{};
 const t=el('div','tiles');
 t.append(tile('Encoder',e.state||'—',
  e.state==='publishing'?'ok':e.state==='unknown'?'warn':'bad'));
 t.append(tile('Free',bytes(i.storage_free_bytes),
  i.storage_free_bytes<3e9?'bad':''));
 view.append(t);
 view.append(card(rows([['lifecycle',fmt(i.lifecycle)],
  ['encoder log age',dur(e.log_age_seconds)],
  ['p2p bridge',fmt(ls.bridge_state)],['p2p state',fmt(ls.state)],
  ['viewers',fmt(ls.viewer_count)],
  ['artifacts',bytes(i.storage_artifact_bytes)],
  ['clips kept',fmt(i.retained_clips)],['states kept',fmt(i.retained_states)],
  ['evidence',fmt(i.evidence_events)],
  ['last error',fmt(i.last_error)]])));}
}
async function poll(){try{const r=await fetch('api/metrics',{cache:'no-store'});
draw(await r.json())}catch(e){const d=document.getElementById('dot');
d.className='dot bad';document.getElementById('title').textContent='unreachable'}
finally{setTimeout(poll,4000)}}
renderTabs();poll();
</script></body></html>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    runtime_dir = DEFAULT_RUNTIME_DIR
    server_version = "rpp-ops"
    sys_version = ""

    def log_message(self, format_string: str, *args: Any) -> None:
        del format_string, args

    def _headers(self, content_type: str, length: int) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'",
        )

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self._headers(content_type, len(body))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/metrics":
            payload = json.dumps(metrics(self.runtime_dir)).encode("utf-8")
            self._send(200, payload, "application/json")
            return
        self._send(404, b'{"error":"not found"}', "application/json")

    def do_HEAD(self) -> None:  # noqa: N802 - stdlib naming
        self.do_GET()

    def _reject(self) -> None:
        """This dashboard is watch-only; there is nothing to write."""
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_PUT = do_DELETE = do_PATCH = _reject


class OpsServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(
    runtime_dir: Path, host: str, port: int
) -> tuple[OpsServer, threading.Thread]:
    handler = type("Handler", (_Handler,), {"runtime_dir": runtime_dir})
    server = OpsServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Private read-only operator dashboard for the phone"
    )
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address; keep loopback and publish with `tailscale serve`",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="print one metrics document and exit",
    )
    mode.add_argument(
        "--wait-for-attention",
        action="store_true",
        help="wait read-only for a stuck, unhealthy, manual, or completed run",
    )
    parser.add_argument("--stuck-threshold", type=int, default=40)
    parser.add_argument("--poll-seconds", type=float, default=30)
    parser.add_argument("--timeout-seconds", type=float, default=0)
    arguments = parser.parse_args(argv)
    if arguments.once:
        print(json.dumps(metrics(arguments.runtime_dir), indent=2))
        return 0
    if arguments.wait_for_attention:
        if arguments.stuck_threshold < 1:
            parser.error("--stuck-threshold must be positive")
        if arguments.poll_seconds <= 0 or arguments.timeout_seconds < 0:
            parser.error("poll and timeout seconds cannot be negative")
        event = wait_for_attention(
            arguments.runtime_dir,
            stuck_threshold=arguments.stuck_threshold,
            poll_seconds=arguments.poll_seconds,
            timeout_seconds=arguments.timeout_seconds,
        )
        print(json.dumps(event, indent=2), flush=True)
        return 0
    server, _thread = serve(arguments.runtime_dir, arguments.host, arguments.port)
    hostname = socket.gethostname()
    print(
        json.dumps(
            {
                "status": "success",
                "message": "operator dashboard ready (read-only)",
                "local_url": f"http://{arguments.host}:{arguments.port}/",
                "runtime_dir": str(arguments.runtime_dir),
                "hostname": hostname,
                "publish": (
                    "tailscale serve --bg "
                    f"--https 443 http://127.0.0.1:{arguments.port}"
                ),
            },
            indent=2,
        ),
        flush=True,
    )
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
