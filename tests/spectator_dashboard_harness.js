"use strict";

const fs = require("fs");
const assert = require("assert");
const spectatorSource = fs.readFileSync(0, "utf8");

class Element {
  constructor(id) {
    this.id = id;
    this.hidden = false;
    this.textContent = "";
    this.className = "";
    this.dataset = {};
    this.children = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this.classNames = new Set();
    this.classList = {
      add: (name) => this.classNames.add(name),
      remove: (name) => this.classNames.delete(name),
      toggle: (name, enabled) => {
        if (enabled) this.classNames.add(name);
        else this.classNames.delete(name);
      },
    };
  }

  addEventListener(name, callback) {
    this.listeners.set(name, callback);
  }

  replaceChildren() {
    this.children = [];
  }

  appendChild(child) {
    this.children.push(child);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  focus() {}
}

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, new Element(id));
  return elements.get(id);
}

const badgeNames = [
  "Boulder", "Cascade", "Thunder", "Rainbow",
  "Soul", "Marsh", "Volcano", "Earth",
];
const badges = badgeNames.map((name) => {
  const badge = new Element(`badge-${name}`);
  badge.dataset.badge = name;
  badge.textContent = name;
  return badge;
});

const video = element("stream");
video.readyState = 3;
video.paused = false;
video.currentTime = 0;
video.play = async () => {};

global.document = {
  getElementById: element,
  querySelectorAll: (selector) => selector === "[data-badge]" ? badges : [],
  createElement: (name) => new Element(name),
};
const windowListeners = new Map();
global.window = {
  addEventListener: (name, callback) => windowListeners.set(name, callback),
};
global.location = {
  hash: "#v=1&host=rpp-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&watch=" +
    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
};
let generatedPeerIds = 0;
Object.defineProperty(global, "crypto", {
  value: {
    randomUUID: () => {
      generatedPeerIds += 1;
      return `00000000-0000-4000-8000-${String(generatedPeerIds).padStart(12, "0")}`;
    },
  },
  configurable: true,
});

let clock = 0;
Object.defineProperty(global, "performance", {
  value: {now: () => clock},
  configurable: true,
});

const intervals = [];
const timeouts = [];
global.setInterval = (callback, delay) => {
  intervals.push({callback, delay});
  return {callback, delay};
};
global.clearInterval = () => {};
global.setTimeout = (callback, delay) => {
  const timer = {callback, delay, cleared: false};
  timeouts.push(timer);
  return timer;
};
global.clearTimeout = (timer) => {
  if (timer) timer.cleared = true;
};

class FakeConnection {
  constructor(peer) {
    this.peer = peer;
    this.listeners = new Map();
    this.sent = [];
    this.closed = false;
  }

  on(name, callback) {
    this.listeners.set(name, callback);
  }

  emit(name, value) {
    const callback = this.listeners.get(name);
    if (callback) callback(value);
  }

  send(value) {
    this.sent.push(value);
  }

  close() {
    this.closed = true;
  }
}

class FakeCall {
  constructor(peer) {
    this.peer = peer;
    this.metadata = {v: 1, role: "spectator"};
    this.listeners = new Map();
    this.answered = false;
    this.closed = false;
  }

  on(name, callback) {
    this.listeners.set(name, callback);
  }

  emit(name, value) {
    const callback = this.listeners.get(name);
    if (callback) callback(value);
  }

  answer() {
    this.answered = true;
  }

  close() {
    this.closed = true;
  }
}

const peers = [];
class FakePeer {
  constructor(id, options) {
    this.id = id;
    this.options = options;
    this.listeners = new Map();
    this.connections = [];
    this.destroyed = false;
    peers.push(this);
  }

  on(name, callback) {
    this.listeners.set(name, callback);
  }

  emit(name, value) {
    const callback = this.listeners.get(name);
    if (callback) callback(value);
  }

  connect(peer) {
    const connection = new FakeConnection(peer);
    this.connections.push(connection);
    return connection;
  }

  destroy() {
    this.destroyed = true;
  }
}
global.Peer = FakePeer;

function snapshot(locationValue) {
  return {
    location: locationValue,
    objective: "Reach Pewter Gym",
    phase: "exploration",
    badges: {earned: ["Boulder"], count: 1, total: 8},
    pokedex: {caught: 12, seen: 9, total: 151},
    party: [{
      nickname: "<img src=x onerror=x>",
      species_id: 25,
      level: 12,
      hp: 20,
      max_hp: 35,
    }],
    completed: false,
    player: {mode: "ai", paused: false},
    play_time: {
      hours: 5,
      minutes: 4,
      seconds: 3,
      frames: 2,
      maxed: false,
    },
    session_elapsed_seconds: 3600,
    checkpoint: {
      timestamp: "2026-07-16T22:00:00Z",
      kind: "milestone",
      location: "Pewter Gym",
      age_seconds: 60,
    },
    viewers: {count: 1, capacity: 5},
  };
}

function telemetry(sequence, locationValue) {
  return {
    v: 1,
    type: "telemetry",
    telemetry_version: 1,
    sequence,
    snapshot: snapshot(locationValue),
  };
}

(async () => {
  eval(spectatorSource);

  assert.strictEqual(peers.length, 1);
  const peer = peers[0];
  assert.match(peer.id, /^rpp-viewer-[0-9a-f]{32}$/);
  assert.strictEqual(peer.id, "rpp-viewer-00000000000040008000000000000001");
  assert.strictEqual(peer.options.host, "0.peerjs.com");
  peer.emit("open");
  const data = peer.connections[0];
  data.emit("open");
  assert.deepStrictEqual(data.sent, [{
    v: 1,
    type: "watch",
    cap: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  }]);

  data.emit("data", telemetry(1, "<script>alert(1)</script>"));
  assert.strictEqual(
    element("location").textContent,
    "<script>alert(1)</script>",
    "untrusted text must remain inert textContent",
  );
  assert.strictEqual(element("details-health").textContent, "Live");
  assert.strictEqual(element("party-list").children.length, 1);
  assert.strictEqual(
    element("party-list").children[0].children[0].textContent,
    "<img src=x onerror=x>",
  );
  assert(badges[0].classNames.has("earned"));
  assert(badges[0].textContent.includes("✓"));

  data.emit("data", telemetry(0, "out-of-order"));
  assert.notStrictEqual(element("location").textContent, "out-of-order");
  const malformed = telemetry(2, "malformed");
  malformed.snapshot.secret = "must reject";
  data.emit("data", malformed);
  assert.notStrictEqual(element("location").textContent, "malformed");

  const call = new FakeCall("rpp-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  peer.emit("call", call);
  assert.strictEqual(call.answered, true);
  const track = {
    kind: "video",
    readyState: "live",
    listeners: new Map(),
    addEventListener(name, callback) {
      this.listeners.set(name, callback);
    },
    emit(name) {
      const callback = this.listeners.get(name);
      if (callback) callback();
    },
  };
  call.emit("stream", {getTracks: () => [track]});
  await Promise.resolve();
  await Promise.resolve();
  assert.strictEqual(element("video-health").textContent, "Live");
  video.listeners.get("waiting")();
  assert.strictEqual(element("video-health").textContent, "Buffering");
  video.listeners.get("playing")();
  assert.strictEqual(element("video-health").textContent, "Live");
  video.listeners.get("stalled")();
  assert.strictEqual(element("video-health").textContent, "Stalled");
  video.listeners.get("playing")();
  video.listeners.get("pause")();
  assert.strictEqual(element("video-health").textContent, "Paused");
  video.listeners.get("playing")();
  track.emit("mute");
  assert.strictEqual(element("video-health").textContent, "Muted");
  track.emit("unmute");
  assert.strictEqual(element("video-health").textContent, "Live");

  clock = 9001;
  intervals.find((entry) => entry.delay === 1000).callback();
  assert.strictEqual(
    element("video-health").textContent,
    "Stalled",
    "the bounded progress watchdog detects frozen video"
  );
  clock = 9002;
  video.listeners.get("playing")();
  clock = 13001;
  intervals.find((entry) => entry.delay === 1000).callback();
  assert.strictEqual(element("details-health").textContent, "Last known (13s)");
  assert(element("details-banner").textContent.includes("updated 13s ago"));
  assert(element("details-banner").textContent.includes("Last known"));
  assert.strictEqual(
    element("location").textContent,
    "<script>alert(1)</script>",
    "retained telemetry is visibly labeled last known rather than current"
  );

  data.emit("data", telemetry(2, "Cerulean City"));
  assert.strictEqual(element("location").textContent, "Cerulean City");
  assert.strictEqual(element("details-health").textContent, "Live");
  assert.strictEqual(data.sent.length, 1, "the watch hello is the only outbound data");

  call.emit("close");
  assert.strictEqual(element("details-health").textContent, "Waiting");
  assert.strictEqual(element("location").textContent, "Unknown");
  const retry = timeouts.find((entry) => !entry.cleared);
  assert(retry && retry.delay >= 750);
  retry.callback();
  assert.strictEqual(peers.length, 2, "media reconnect should create a fresh Peer");
  assert.notStrictEqual(peers[1].id, peer.id, "retries use a fresh local peer ID");

  windowListeners.get("pagehide")();
  assert.strictEqual(peers[1].destroyed, true);
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
