#!/usr/bin/env python3
"""Drive YouTube Studio in real Safari via safaridriver (W3C WebDriver).

Safari carries the user's genuine Google session, so Studio loads signed-in
without tripping the automation block that rejects Chrome-for-Testing.

Studio is a Polymer app that buries its controls in nested shadow roots, so
element lookup is done with injected JS that walks shadow boundaries rather
than CSS selectors, which cannot pierce them.

  safari_studio.py find      # report the auto-start/auto-stop toggles found
  safari_studio.py enable    # actually click them on, then save

Defaults to a dry run: `find` never clicks. Requires Safari > Develop >
"Allow Remote Automation".
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RUNTIME = Path.home() / ".openrappter/pokemon-red"
SHOTS = RUNTIME / "probe-shots"
CHANNEL_ID = os.environ.get("RPP_YT_CHANNEL_ID", "UCz0Tfe07OAwnQR-fd3E1y4Q")
STUDIO_LIVE = f"https://studio.youtube.com/channel/{CHANNEL_ID}/livestreaming"

# Walks the whole element tree including shadow roots, finds rows mentioning
# auto-start / auto-stop, and pairs each with its nearest toggle control.
FIND_TOGGLES_JS = r"""
const out = [];
function collect(root, acc) {
  const kids = root.querySelectorAll('*');
  for (const el of kids) {
    acc.push(el);
    if (el.shadowRoot) collect(el.shadowRoot, acc);
  }
  return acc;
}
const all = collect(document, []);
const WANT = /auto[-\s]?(start|stop)/i;
const TOGGLE = 'tp-yt-paper-toggle-button,[role="switch"],[role="checkbox"],input[type="checkbox"]';

const seen = new Set();
for (const el of all) {
  const own = Array.from(el.childNodes)
    .filter(n => n.nodeType === 3)
    .map(n => n.textContent)
    .join(' ')
    .trim();
  if (!own || !WANT.test(own)) continue;

  // Climb to a container that actually holds a toggle.
  let node = el, toggle = null, hops = 0;
  while (node && hops < 6 && !toggle) {
    toggle = node.querySelector ? node.querySelector(TOGGLE) : null;
    if (!toggle) { node = node.parentElement || (node.getRootNode() || {}).host; hops++; }
  }
  if (!toggle || seen.has(toggle)) continue;
  seen.add(toggle);

  const on =
    toggle.getAttribute('aria-checked') === 'true' ||
    toggle.getAttribute('aria-pressed') === 'true' ||
    toggle.checked === true ||
    toggle.hasAttribute('checked');
  out.push({ label: own.slice(0, 80), tag: toggle.tagName.toLowerCase(), on });
  toggle.setAttribute('data-rpp-toggle', String(out.length - 1));
}
return JSON.stringify(out);
"""

CLICK_TOGGLE_JS = r"""
const idx = arguments[0];
function collect(root, acc) {
  for (const el of root.querySelectorAll('*')) {
    acc.push(el);
    if (el.shadowRoot) collect(el.shadowRoot, acc);
  }
  return acc;
}
for (const el of collect(document, [])) {
  if (el.getAttribute && el.getAttribute('data-rpp-toggle') === String(idx)) {
    el.click();
    return 'clicked';
  }
}
return 'not-found';
"""

# Clicks the first button-like element whose visible text matches a pattern,
# searching through shadow roots. Returns the text it clicked, or null.
CLICK_BY_TEXT_JS = r"""
const pattern = new RegExp(arguments[0], 'i');
function collect(root, acc) {
  for (const el of root.querySelectorAll('*')) {
    acc.push(el);
    if (el.shadowRoot) collect(el.shadowRoot, acc);
  }
  return acc;
}
const CLICKABLE = new Set(['button', 'ytcp-button', 'a', 'tp-yt-paper-button']);
for (const el of collect(document, [])) {
  const tag = el.tagName.toLowerCase();
  if (!CLICKABLE.has(tag)) continue;
  const t = (el.innerText || el.textContent || '').trim();
  if (!t || t.length > 40 || !pattern.test(t)) continue;
  if (el.hasAttribute('disabled') || el.getAttribute('aria-disabled') === 'true') continue;
  const box = el.getBoundingClientRect();
  if (!box.width || !box.height) continue;   // skip hidden/detached
  el.click();
  return t;
}
return null;
"""

# Reports the Dual stream control's state without changing it. Dual stream
# re-canvases the broadcast to 1:1 unless it is in Auto mode.
FIND_DUAL_STREAM_JS = r"""
function collect(root, acc) {
  for (const el of root.querySelectorAll('*')) {
    acc.push(el);
    if (el.shadowRoot) collect(el.shadowRoot, acc);
  }
  return acc;
}
const all = collect(document, []);
const out = [];
for (const el of all) {
  const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
    .map(n => n.textContent).join(' ').trim();
  if (!/dual\s*(stream|format)/i.test(own)) continue;
  let node = el, toggle = null, hops = 0;
  while (node && hops < 6 && !toggle) {
    toggle = node.querySelector
      ? node.querySelector('tp-yt-paper-toggle-button,[role="switch"],input[type="checkbox"]')
      : null;
    if (!toggle) { node = node.parentElement || (node.getRootNode() || {}).host; hops++; }
  }
  if (!toggle) continue;
  const on = toggle.getAttribute('aria-checked') === 'true' ||
             toggle.getAttribute('aria-pressed') === 'true' ||
             toggle.checked === true || toggle.hasAttribute('checked');
  out.push({ label: own.slice(0, 60), on });
  toggle.setAttribute('data-rpp-dual', String(out.length - 1));
}
return JSON.stringify(out);
"""

SAVE_JS = r"""
function collect(root, acc) {
  for (const el of root.querySelectorAll('*')) {
    acc.push(el);
    if (el.shadowRoot) collect(el.shadowRoot, acc);
  }
  return acc;
}
for (const el of collect(document, [])) {
  const t = (el.textContent || '').trim();
  const tag = el.tagName.toLowerCase();
  if ((tag === 'button' || tag === 'ytcp-button') && /^save$/i.test(t)) {
    el.click();
    return 'saved';
  }
}
return 'no-save-button';
"""


class Driver:
    """Minimal W3C WebDriver client - stdlib only, no selenium needed."""

    def __init__(self, port: int = 4577):
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        self.session = None
        self.proc = None

    def _rq(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(json.loads(e.read() or b"{}")) from None

    def start(self) -> None:
        self.proc = subprocess.Popen(
            ["safaridriver", "--port", str(self.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            with socket.socket() as s:
                s.settimeout(0.5)
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    break
            time.sleep(0.4)
        res = self._rq(
            "POST", "/session", {"capabilities": {"alwaysMatch": {"browserName": "safari"}}}
        )
        self.session = res["value"]["sessionId"]

    def goto(self, url: str) -> None:
        self._rq("POST", f"/session/{self.session}/url", {"url": url})

    def current_url(self) -> str:
        return self._rq("GET", f"/session/{self.session}/url")["value"]

    def js(self, script: str, args: list | None = None):
        return self._rq(
            "POST",
            f"/session/{self.session}/execute/sync",
            {"script": script, "args": args or []},
        )["value"]

    def screenshot(self, path: Path) -> None:
        b64 = self._rq("GET", f"/session/{self.session}/screenshot")["value"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(b64))

    def quit(self) -> None:
        try:
            if self.session:
                self._rq("DELETE", f"/session/{self.session}")
        except Exception:
            pass
        if self.proc:
            self.proc.terminate()


def run(apply_changes: bool) -> dict:
    out: dict = {"applied": apply_changes}
    d = Driver()
    try:
        d.start()
    except Exception as exc:
        return {
            "error": f"safaridriver session failed: {exc}",
            "hint": "Safari > Settings > Advanced > 'Show features for web developers', "
            "then Develop > 'Allow Remote Automation'",
        }

    try:
        d.goto(STUDIO_LIVE)
        time.sleep(9)  # Studio is slow to hydrate its shadow trees
        url = d.current_url()
        out["url"] = url
        if "accounts.google.com" in url:
            out["error"] = "Safari is not signed in to the Google account that owns the channel"
            return out

        found = json.loads(d.js(FIND_TOGGLES_JS) or "[]")
        out["toggles"] = found

        if not found:
            out["error"] = (
                "no auto-start/auto-stop toggles visible on the live dashboard - "
                "they may sit behind the stream's edit dialog"
            )
        elif apply_changes:
            changed = []
            for i, t in enumerate(found):
                if not t["on"]:
                    if d.js(CLICK_TOGGLE_JS, [i]) == "clicked":
                        changed.append(t["label"])
                        time.sleep(1.2)
            out["changed"] = changed
            if changed:
                out["save"] = d.js(SAVE_JS)
                time.sleep(3)
                out["toggles_after"] = json.loads(d.js(FIND_TOGGLES_JS) or "[]")

        shot = SHOTS / f"safari-studio-{time.strftime('%Y%m%d-%H%M%S')}.png"
        d.screenshot(shot)
        out["screenshot"] = str(shot)
    except Exception as exc:
        out["error"] = str(exc)
    finally:
        d.quit()
    return out


def go_live() -> dict:
    """Publish a broadcast parked in 'Preparing stream' by clicking GO LIVE."""
    out: dict = {}
    d = Driver()
    try:
        d.start()
    except Exception as exc:
        return {
            "error": f"safaridriver session failed: {exc}",
            "hint": "Safari > Settings > Advanced > 'Show features for web developers', "
            "then Develop > 'Allow Remote Automation'",
        }
    try:
        d.goto(STUDIO_LIVE)
        time.sleep(9)
        if "accounts.google.com" in d.current_url():
            out["error"] = "Safari is not signed in to the Google account that owns the channel"
            return out

        out["dual_stream"] = json.loads(d.js(FIND_DUAL_STREAM_JS) or "[]")
        clicked = d.js(CLICK_BY_TEXT_JS, [r"^go live$"])
        out["clicked"] = clicked
        if clicked:
            time.sleep(4)
            # Studio often raises a confirmation dialog behind GO LIVE.
            out["confirmed"] = d.js(CLICK_BY_TEXT_JS, [r"^(go live|start|confirm|yes)$"])
            time.sleep(4)
        else:
            out["note"] = (
                "no enabled GO LIVE button found - the broadcast may already be "
                "live, or Studio may be showing a different control"
            )
        shot = SHOTS / f"safari-golive-{time.strftime('%Y%m%d-%H%M%S')}.png"
        d.screenshot(shot)
        out["screenshot"] = str(shot)
    except Exception as exc:
        out["error"] = str(exc)
    finally:
        d.quit()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "action", choices=["find", "enable", "golive"], nargs="?", default="find"
    )
    args = ap.parse_args()
    if args.action == "golive":
        result = go_live()
    else:
        result = run(apply_changes=args.action == "enable")
    print(json.dumps(result, indent=2))
    return 1 if result.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
