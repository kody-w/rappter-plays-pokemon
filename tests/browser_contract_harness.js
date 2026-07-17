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

  setAttribute(name, value) {
    this[name] = String(value);
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

const captures = [];
function makeCapture() {
  const track = {
    kind: "video",
    readyState: "live",
    stopped: false,
    listeners: new Map(),
    addEventListener(name, callback) {
      this.listeners.set(name, callback);
    },
    emit(name) {
      const callback = this.listeners.get(name);
      if (callback) callback();
    },
    stop() {
      this.stopped = true;
      this.readyState = "ended";
    },
  };
  const capture = {
    track,
    getTracks: () => [track],
    getVideoTracks: () => [track],
  };
  captures.push(capture);
  return capture;
}
const game = element("game");
game.width = 160;
game.height = 144;
game.getContext = () => ({
  imageSmoothingEnabled: true,
  drawImage: () => {},
});
game.captureStream = () => makeCapture();
const pipVideo = element("pip-video");
pipVideo.readyState = 0;
pipVideo.play = async () => {};

const documentListeners = new Map();
global.document = {
  hidden: false,
  pictureInPictureEnabled: true,
  pictureInPictureElement: null,
  getElementById: element,
  querySelectorAll: () => [],
  createElement: (name) => new Element(name),
  addEventListener: (name, callback) => documentListeners.set(name, callback),
  exitPictureInPicture: async () => {
    global.document.pictureInPictureElement = null;
    const callback = pipVideo.listeners.get("leavepictureinpicture");
    if (callback) callback();
  },
};
let rejectStandardPiP = false;
pipVideo.requestPictureInPicture = async () => {
  if (rejectStandardPiP) throw new Error("simulated PiP rejection");
  global.document.pictureInPictureElement = pipVideo;
  const callback = pipVideo.listeners.get("enterpictureinpicture");
  if (callback) callback();
  return pipVideo;
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
const timeouts = [];
global.setInterval = (callback, delay) => {
  intervalCallbacks.push({callback, delay});
  return {callback, delay};
};
global.clearInterval = () => {};
global.setTimeout = (callback, delay) => {
  timeoutDelays.push(delay);
  const timer = {callback, delay, cleared: false};
  timeouts.push(timer);
  return timer;
};
global.clearTimeout = (timer) => {
  if (timer) timer.cleared = true;
};
let clock = 0;
Object.defineProperty(global, "performance", {
  value: {now: () => clock},
  configurable: true,
});

class FakeConnection {
  constructor(peer) {
    this.peer = peer;
    this.open = false;
    this.closed = false;
    this.listeners = new Map();
    this.sent = [];
    this.bufferSize = 0;
    this.failTelemetry = false;
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

  send(value) {
    if (this.failTelemetry && value && value.type === "telemetry") {
      throw new Error("simulated telemetry failure");
    }
    this.sent.push(value);
  }
}

class FakeCall {
  constructor(peer) {
    this.peer = peer;
    this.listeners = new Map();
    this.closed = false;
    this.open = false;
  }

  on(name, callback) {
    this.listeners.set(name, callback);
  }

  emit(name, value) {
    const callback = this.listeners.get(name);
    if (callback) callback(value);
  }

  close() {
    this.closed = true;
  }
}

const peers = [];
const calls = [];
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

  call(peer) {
    const call = new FakeCall(peer);
    calls.push(call);
    return call;
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
  telemetry_version: 1,
  max_telemetry_bytes: 4096,
  telemetry_change_seconds: 1,
  telemetry_heartbeat_seconds: 5,
  lease_ttl_seconds: 120,
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

let dashboard = {
  location: "Pallet Town",
  objective: "Begin the adventure",
  phase: "exploration",
  badges: {earned: [], count: 0, total: 8},
  pokedex: {caught: 4, seen: 2, total: 151},
  party: [],
  completed: false,
  player: {mode: "ai", paused: false},
  play_time: {
    hours: 1,
    minutes: 2,
    seconds: 3,
    frames: 4,
    maxed: false,
  },
  session_elapsed_seconds: 60,
  checkpoint: null,
  viewers: {count: 0, capacity: 2},
};
let heartbeatFailure = null;
let rejectDashboard = false;
let rejectStatus = false;
let runtimeStopped = false;
let ownerActiveAcquires = 1;
let deferNextAcquire = false;
let resolveDeferredAcquire = null;
const leaseRequests = [];

function response(value, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => value,
  };
}

global.fetch = async (url, options = {}) => {
  if (url.startsWith("/api/status")) {
    if (rejectStatus) throw new Error("simulated status transport outage");
    return response({
      running: !runtimeStopped,
      lifecycle: runtimeStopped ? "stopped" : "ready",
      livestream: {enabled: true, generation},
      clips: [],
    });
  }
  if (url.startsWith("/api/dashboard")) {
    if (rejectDashboard) throw new Error("simulated dashboard outage");
    return response(dashboard);
  }
  if (url === "/api/livestream" && !options.method) return response(config);
  if (url === "/api/livestream/lease") {
    const request = JSON.parse(options.body);
    leaseRequests.push({request, options});
    if (request.action === "acquire") {
      if (deferNextAcquire) {
        deferNextAcquire = false;
        return await new Promise((resolve) => {
          resolveDeferredAcquire = () => resolve(response({
            status: "success",
            owner: request.owner,
            generation,
            lease: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            heartbeat_seconds: 4,
          }));
        });
      }
      if (ownerActiveAcquires > 0) {
        ownerActiveAcquires -= 1;
        return response({status: "error", message: "owner-active"}, 409);
      }
      return response({
        status: "success",
        owner: request.owner,
        generation,
        lease: "ddddddddddddddddddddddddddddddddddddddddddd",
        heartbeat_seconds: 4,
      });
    }
    if (request.action === "heartbeat" && heartbeatFailure === "network") {
      throw new Error("simulated lease transport outage");
    }
    if (request.action === "heartbeat" && heartbeatFailure === "lost") {
      return response({status: "error", message: "lease-lost"}, 409);
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

  assert.strictEqual(
    peers.length,
    0,
    "an owner-active standby must not create capture or PeerJS"
  );
  let recoveryElapsed = 0;
  while (peers.length === 0) {
    const takeoverTimer = [...timeouts].reverse().find(
      ({cleared}) => !cleared
    );
    assert(takeoverTimer, "owner-active starts bounded guarded recovery");
    recoveryElapsed += takeoverTimer.delay;
    clock = recoveryElapsed;
    await takeoverTimer.callback();
    await flush();
  }
  assert.strictEqual(
    recoveryElapsed,
    1000,
    "standby takes over promptly after the active owner releases"
  );
  assert.strictEqual(
    peers.length,
    1,
    "standby takes over after the prior owner releases"
  );
  clock = 0;
  const host = peers[0];
  const ice = JSON.stringify(host.options.config).toLowerCase();
  assert(ice.includes("stun:stun.l.google.com:19302"));
  assert(!ice.includes("turn:"));
  assert(!ice.includes("turns:"));

  const first = new FakeConnection("spectator-first");
  let second = new FakeConnection("spectator-second");
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
  first.emit("data", {
    v: 1,
    type: "watch",
    cap: config.watch_capability,
  });
  await flush();
  assert.strictEqual(calls.length, 1, "valid hello starts one media call");
  calls[0].open = true;
  calls[0].emit("iceStateChanged", "connected");
  assert.strictEqual(
    first.sent[0].type,
    "ready",
    "legacy-ready precedes independently versioned telemetry"
  );
  assert.strictEqual(first.sent[1].type, "telemetry");
  assert.strictEqual(first.sent[1].telemetry_version, 1);
  assert.strictEqual(
    first.sent[1].snapshot.pokedex.caught,
    4,
    "host validator accepts Gen-I Owned greater than Seen"
  );
  assert.strictEqual(first.sent[1].snapshot.viewers.count, 1);
  assert(
    Buffer.byteLength(JSON.stringify(first.sent[1]), "utf8") <= 4096,
    "telemetry stays within the UTF-8 message bound"
  );

  second.emit("open");
  second.emit("data", {
    v: 1,
    type: "watch",
    cap: config.watch_capability,
  });
  await flush();
  assert.strictEqual(calls.length, 2, "multiple admitted viewers get separate calls");
  assert.strictEqual(second.sent[1].snapshot.viewers.count, 2);
  const unavailable = new Error("Could not connect to peer spectator-second");
  unavailable.type = "peer-unavailable";
  host.emit("error", unavailable);
  assert.strictEqual(second.closed, true, "bad media target closes only that viewer");
  assert.strictEqual(first.closed, false, "one bad viewer cannot disconnect another");
  assert.strictEqual(host.destroyed, false, "peer-unavailable is not host-fatal");

  const timedOut = new FakeConnection("spectator-timeout");
  host.emit("connection", timedOut);
  timedOut.emit("open");
  timedOut.emit("data", {
    v: 1,
    type: "watch",
    cap: config.watch_capability,
  });
  await flush();
  const mediaTimeout = [...timeouts].reverse().find(
    ({delay, cleared}) => delay === 15000 && !cleared
  );
  assert(mediaTimeout, "unanswered media negotiation has a bounded timeout");
  mediaTimeout.callback();
  assert.strictEqual(timedOut.closed, true);
  assert.strictEqual(first.closed, false);

  second = new FakeConnection("spectator-replacement");
  host.emit("connection", second);
  second.emit("open");
  second.emit("data", {
    v: 1,
    type: "watch",
    cap: config.watch_capability,
  });
  await flush();
  calls.at(-1).open = true;
  calls.at(-1).emit("iceStateChanged", "connected");

  const dashboardInterval = intervalCallbacks.find(({delay}) => delay === 1000);
  const telemetryInterval = intervalCallbacks.find(({delay}) => delay === 250);
  second.bufferSize = 10000;
  dashboard = {...dashboard, location: "Viridian City"};
  clock = 1001;
  await dashboardInterval.callback();
  await flush();
  assert.strictEqual(
    second.sent.length,
    2,
    "backpressured viewers do not queue stale snapshots"
  );
  second.bufferSize = 0;
  clock = 2002;
  telemetryInterval.callback();
  assert.strictEqual(
    second.sent.at(-1).snapshot.location,
    "Viridian City",
    "the latest snapshot replaces skipped intermediate work"
  );

  second.failTelemetry = true;
  dashboard = {...dashboard, location: "Pewter City"};
  clock = 3003;
  await dashboardInterval.callback();
  await flush();
  assert.strictEqual(second.closed, true, "send failure removes only that viewer");
  assert.strictEqual(first.closed, false, "other admitted viewers stay connected");
  clock = 4004;
  telemetryInterval.callback();
  assert.strictEqual(
    first.sent.at(-1).snapshot.viewers.count,
    1,
    "remaining viewers receive the latest admitted count"
  );
  const firstCount = first.sent.length;
  clock = 8000;
  telemetryInterval.callback();
  assert.strictEqual(
    first.sent.length,
    firstCount,
    "unchanged snapshots do not send before the heartbeat"
  );
  clock = 9105;
  telemetryInterval.callback();
  assert.strictEqual(first.sent.length, firstCount + 1);
  assert(
    first.sent.at(-1).sequence > first.sent.at(-2).sequence,
    "heartbeat snapshots retain monotonic sequence numbers"
  );
  rejectDashboard = true;
  await dashboardInterval.callback();
  await flush();
  assert.strictEqual(
    host.destroyed,
    false,
    "dashboard failure must not stop video or PeerJS"
  );
  assert.strictEqual(first.closed, false);
  rejectDashboard = false;

  first.emit("data", {v: 1, type: "control", action: "press"});
  assert.strictEqual(first.closed, true, "post-hello spectator data closes the viewer");

  const pipButton = element("pip-toggle");
  assert.strictEqual(
    pipButton.disabled,
    true,
    "srcObject alone does not make PiP ready before metadata"
  );
  pipVideo.readyState = 1;
  pipVideo.listeners.get("loadedmetadata")();
  assert.strictEqual(pipButton.disabled, false, "active capture enables PiP");
  rejectStandardPiP = true;
  pipButton.listeners.get("click")();
  await flush();
  assert(element("pip-status").textContent.includes("could not be opened"));
  const standardFailure = element("pip-status").textContent;
  pipVideo.listeners.get("canplay")();
  assert.strictEqual(
    element("pip-status").textContent,
    standardFailure,
    "readiness events must not overwrite a failed standard PiP request"
  );
  rejectStandardPiP = false;
  pipButton.listeners.get("click")();
  await flush();
  assert.strictEqual(global.document.pictureInPictureElement, pipVideo);
  assert.strictEqual(
    element("pip-status").textContent,
    "Picture in Picture is active.",
    "a successful retry clears the standard PiP failure"
  );
  assert.strictEqual(pipButton.textContent, "Exit Picture in Picture");
  pipButton.listeners.get("click")();
  await flush();
  assert.strictEqual(global.document.pictureInPictureElement, null);

  global.document.pictureInPictureEnabled = false;
  pipVideo.requestPictureInPicture = undefined;
  pipVideo.webkitPresentationMode = "inline";
  pipVideo.webkitSupportsPresentationMode = (mode) =>
    mode === "picture-in-picture";
  let rejectSafariPiP = true;
  pipVideo.webkitSetPresentationMode = (mode) => {
    if (rejectSafariPiP) throw new Error("simulated Safari PiP rejection");
    pipVideo.webkitPresentationMode = mode;
    const callback = pipVideo.listeners.get("webkitpresentationmodechanged");
    if (callback) callback();
  };
  pipVideo.listeners.get("webkitpresentationmodechanged")();
  pipButton.listeners.get("click")();
  assert(element("pip-status").textContent.includes("could not be opened"));
  const safariFailure = element("pip-status").textContent;
  pipVideo.listeners.get("playing")();
  assert.strictEqual(element("pip-status").textContent, safariFailure);
  rejectSafariPiP = false;
  pipButton.listeners.get("click")();
  assert.strictEqual(
    pipVideo.webkitPresentationMode,
    "picture-in-picture",
    "Safari presentation mode is used when standard PiP is unavailable"
  );
  assert.strictEqual(pipButton.textContent, "Exit Picture in Picture");
  pipButton.listeners.get("click")();
  assert.strictEqual(pipVideo.webkitPresentationMode, "inline");

  global.document.hidden = true;
  heartbeatFailure = "lost";
  const heartbeatInterval = intervalCallbacks.find(({delay}) => delay === 10000);
  const timeoutCountBeforeHiddenLoss = timeouts.length;
  await heartbeatInterval.callback();
  await flush();
  assert.strictEqual(
    element("stream-state").textContent,
    "Offline",
    "an authoritative expired lease has a recoverable offline state"
  );
  assert(element("stream-message").textContent.includes("reacquire"));
  assert.strictEqual(
    timeouts.length,
    timeoutCountBeforeHiddenLoss,
    "hidden standby recovery does not leave an active retry timer"
  );
  const peerCountBeforeRecovery = peers.length;
  heartbeatFailure = null;
  global.document.hidden = false;
  documentListeners.get("visibilitychange")();
  const recovery = [...timeouts].reverse().find(
    ({delay, cleared}) => delay === 0 && !cleared
  );
  assert(recovery, "becoming visible schedules one guarded recovery");
  await recovery.callback();
  await flush();
  assert.strictEqual(
    peers.length,
    peerCountBeforeRecovery + 1,
    "visible lease recovery creates one replacement host"
  );
  assert.strictEqual(
    pipButton.disabled,
    true,
    "replacement capture waits for fresh metadata rather than reusing readiness"
  );
  pipVideo.listeners.get("loadedmetadata")();
  assert.strictEqual(pipButton.disabled, false);

  const statusInterval = intervalCallbacks.find(({delay}) => delay === 500);
  const terminalPeer = peers.at(-1);
  const terminalCapture = captures.at(-1);
  runtimeStopped = true;
  await statusInterval.callback();
  await flush();
  assert.strictEqual(
    terminalPeer.destroyed,
    true,
    "runtime shutdown destroys the current Peer"
  );
  assert.strictEqual(
    terminalCapture.track.stopped,
    true,
    "runtime shutdown stops the current capture track"
  );
  runtimeStopped = false;
  element("go-live").listeners.get("click")();
  await flush();

  const corePeer = peers.at(-1);
  const coreCapture = captures.at(-1);
  const coreViewer = new FakeConnection("spectator-core-watchdog");
  corePeer.emit("connection", coreViewer);
  coreViewer.emit("open");
  coreViewer.emit("data", {
    v: 1,
    type: "watch",
    cap: config.watch_capability,
  });
  await flush();
  calls.at(-1).open = true;
  calls.at(-1).emit("iceStateChanged", "connected");
  rejectStatus = true;
  for (let index = 0; index < 3; index += 1) {
    await statusInterval.callback();
    await flush();
  }
  heartbeatFailure = "network";
  for (let index = 0; index < 2; index += 1) {
    await heartbeatInterval.callback();
    await flush();
  }
  assert.strictEqual(corePeer.destroyed, false, "transient core loss is tolerated");
  assert.strictEqual(coreCapture.track.stopped, false);
  await heartbeatInterval.callback();
  await flush();
  assert.strictEqual(
    corePeer.destroyed,
    true,
    "repeated total control-plane loss destroys the current Peer"
  );
  assert.strictEqual(
    coreCapture.track.stopped,
    true,
    "core watchdog stops the current capture track"
  );
  assert.strictEqual(coreViewer.closed, true);
  rejectStatus = false;
  heartbeatFailure = null;

  element("retry-live").listeners.get("click")();
  await flush();
  const pagePeer = peers.at(-1);
  const pageCapture = captures.at(-1);
  assert.notStrictEqual(pagePeer, corePeer);
  assert.strictEqual(pagePeer.destroyed, false);
  assert.strictEqual(pageCapture.track.stopped, false);
  const pageFirst = new FakeConnection("spectator-page-first");
  const pageSecond = new FakeConnection("spectator-page-second");
  pagePeer.emit("connection", pageFirst);
  pagePeer.emit("connection", pageSecond);
  for (const connection of [pageFirst, pageSecond]) {
    connection.emit("open");
    connection.emit("data", {
      v: 1,
      type: "watch",
      cap: config.watch_capability,
    });
  }
  await flush();
  assert.strictEqual(pageFirst.closed, false);
  assert.strictEqual(pageSecond.closed, false);

  windowListeners.get("pagehide")();
  assert.strictEqual(pagePeer.destroyed, true, "pagehide destroys the latest PeerJS");
  assert.strictEqual(
    pageCapture.track.stopped,
    true,
    "pagehide stops the fresh current capture track"
  );
  assert.strictEqual(pageFirst.closed, true, "pagehide closes current viewers");
  assert.strictEqual(pageSecond.closed, true, "pagehide closes every current viewer");

  ownerActiveAcquires = 100;
  clock = 200000;
  const recoveryDeadlineStart = clock;
  const peerCountBeforeExpiredRecovery = peers.length;
  eval(viewerSource);
  await flush();
  let expirySteps = 0;
  while (!element("stream-message").textContent.includes(
    "Automatic lease recovery ended"
  )) {
    const timer = [...timeouts].reverse().find(({cleared}) => !cleared);
    assert(timer, "finite recovery keeps one bounded timer");
    timer.cleared = true;
    clock += timer.delay;
    await timer.callback();
    await flush();
    expirySteps += 1;
    assert(expirySteps < 20, "recovery must terminate without an unbounded loop");
  }
  assert.strictEqual(peers.length, peerCountBeforeExpiredRecovery);
  assert.strictEqual(
    clock - recoveryDeadlineStart,
    135000,
    "recovery deadline covers the 120-second TTL plus a bounded grace period"
  );

  ownerActiveAcquires = 0;
  deferNextAcquire = true;
  resolveDeferredAcquire = null;
  const peerCountBeforePendingExit = peers.length;
  const captureCountBeforePendingExit = captures.length;
  eval(viewerSource);
  await flush();
  assert(resolveDeferredAcquire, "the second host is waiting on lease acquisition");
  windowListeners.get("pagehide")();
  resolveDeferredAcquire();
  await flush();
  assert.strictEqual(
    peers.length,
    peerCountBeforePendingExit,
    "a lease granted after pagehide must not create PeerJS"
  );
  assert.strictEqual(
    captures.length,
    captureCountBeforePendingExit,
    "a lease granted after pagehide must not start capture"
  );
  const lateRelease = leaseRequests.find(
    ({request}) =>
      request.action === "release" &&
      request.lease === "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
  );
  assert(lateRelease, "a late lease grant is released");
  assert.strictEqual(
    lateRelease.options.keepalive,
    true,
    "late page-exit lease release uses keepalive"
  );
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
