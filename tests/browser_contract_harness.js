"use strict";

const fs = require("fs");
const assert = require("assert");
const viewerSource = fs.readFileSync(0, "utf8");

class Element {
  constructor(id) {
    this.id = id;
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.className = "";
    this.dataset = {};
    this.children = [];
    this.listeners = new Map();
    this.classList = {
      add: () => {},
      remove: () => {},
      toggle: () => {},
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

  focus() {}

  get childElementCount() {
    return this.children.length;
  }
}

const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, new Element(id));
  return elements.get(id);
}

const track = {
  stopped: false,
  listeners: new Map(),
  addEventListener(name, callback) {
    this.listeners.set(name, callback);
  },
  stop() {
    this.stopped = true;
  },
};
const capture = {getTracks: () => [track]};
const game = element("game");
game.width = 160;
game.height = 144;
game.getContext = () => ({
  imageSmoothingEnabled: true,
  drawImage: () => {},
});
game.captureStream = () => capture;

const documentListeners = new Map();
global.document = {
  hidden: false,
  getElementById: element,
  querySelectorAll: () => [],
  createElement: (name) => new Element(name),
  addEventListener: (name, callback) => documentListeners.set(name, callback),
};
const windowListeners = new Map();
global.window = {
  addEventListener: (name, callback) => windowListeners.set(name, callback),
};
Object.defineProperty(global, "navigator", {
  value: {clipboard: {writeText: async () => {}}},
  configurable: true,
});
global.Image = class {
  set src(_value) {}
};
global.QRious = class {};

const intervalCallbacks = [];
const timeoutDelays = [];
global.setInterval = (callback, delay) => {
  intervalCallbacks.push({callback, delay});
  return {callback, delay};
};
global.clearInterval = () => {};
global.setTimeout = (callback, delay) => {
  timeoutDelays.push(delay);
  return {callback, delay};
};
global.clearTimeout = () => {};

class FakeConnection {
  constructor(peer) {
    this.peer = peer;
    this.open = false;
    this.closed = false;
    this.listeners = new Map();
  }

  on(name, callback) {
    this.listeners.set(name, callback);
  }

  emit(name, value) {
    if (name === "open") this.open = true;
    const callback = this.listeners.get(name);
    if (callback) callback(value);
  }

  close() {
    this.closed = true;
  }

  send() {}
}

const peers = [];
class FakePeer {
  constructor(id, options) {
    this.id = id;
    this.options = options;
    this.listeners = new Map();
    this.destroyed = false;
    this.disconnected = false;
    peers.push(this);
  }

  on(name, callback) {
    this.listeners.set(name, callback);
  }

  emit(name, value) {
    const callback = this.listeners.get(name);
    if (callback) callback(value);
  }

  call() {
    return null;
  }

  destroy() {
    this.destroyed = true;
  }

  reconnect() {}
}
global.Peer = FakePeer;

const generation = "generation-aaaaaaaaaaaaaaaaaaaaaaaa";
const config = {
  enabled: true,
  generation,
  peer_id: "rpp-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  watch_capability: "ccccccccccccccccccccccccccccccccccccccccccc",
  join_url: "http://127.0.0.1:8766/#test",
  protocol_version: 1,
  max_hello_bytes: 512,
  max_viewers: 2,
  max_negotiating: 2,
  frame_rate: 10,
  peer_options: {
    host: "0.peerjs.com",
    port: 443,
    path: "/",
    secure: true,
    debug: 0,
    config: {
      iceServers: [{urls: "stun:stun.l.google.com:19302"}],
    },
  },
};

function response(value, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => value,
  };
}

global.fetch = async (url, options = {}) => {
  if (url.startsWith("/api/status")) {
    return response({
      running: true,
      lifecycle: "ready",
      livestream: {enabled: true, generation},
      clips: [],
    });
  }
  if (url === "/api/livestream" && !options.method) return response(config);
  if (url === "/api/livestream/lease") {
    const request = JSON.parse(options.body);
    if (request.action === "acquire") {
      return response({
        status: "success",
        owner: request.owner,
        generation,
        lease: "ddddddddddddddddddddddddddddddddddddddddddd",
        heartbeat_seconds: 4,
      });
    }
    return response({
      status: "success",
      owner: request.owner,
      generation,
      heartbeat_seconds: 4,
    });
  }
  if (url === "/api/livestream/state") return response({status: "success"});
  throw new Error(`unexpected fetch: ${url}`);
};

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
  await Promise.resolve();
}

(async () => {
  eval(viewerSource);
  await flush();

  assert.strictEqual(peers.length, 1, "the lease owner should create one Peer");
  const host = peers[0];
  const ice = JSON.stringify(host.options.config).toLowerCase();
  assert(ice.includes("stun:stun.l.google.com:19302"));
  assert(!ice.includes("turn:"));
  assert(!ice.includes("turns:"));

  const first = new FakeConnection("spectator-first");
  const second = new FakeConnection("spectator-second");
  const excess = new FakeConnection("spectator-excess");
  host.emit("connection", first);
  host.emit("connection", second);
  host.emit("connection", excess);
  assert.strictEqual(excess.closed, true, "excess negotiating offers close immediately");
  assert.strictEqual(
    timeoutDelays.filter((delay) => delay === 5000).length,
    0,
    "hello timeout must not start before the data channel opens"
  );
  first.emit("open");
  assert.strictEqual(
    timeoutDelays.filter((delay) => delay === 5000).length,
    1,
    "hello timeout starts after open"
  );

  windowListeners.get("pagehide")();
  assert.strictEqual(host.destroyed, true, "pagehide destroys PeerJS");
  assert.strictEqual(track.stopped, true, "pagehide stops canvas capture");
  assert.strictEqual(first.closed, true, "pagehide closes negotiating connections");
  assert.strictEqual(second.closed, true, "pagehide closes all negotiating connections");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
