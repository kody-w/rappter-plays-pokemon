'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const vm = require('node:vm');

let source = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  source += chunk;
});
process.stdin.on('end', () => run().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
}));

class ClassList {
  constructor() {
    this.values = new Set();
  }

  toggle(name, enabled) {
    if (enabled) this.values.add(name);
    else this.values.delete(name);
  }
}

class Element {
  constructor(id) {
    this.id = id;
    this.textContent = '';
    this.className = '';
    this.classList = new ClassList();
    this.hidden = false;
    this.disabled = false;
    this.href = '';
    this.readyState = 1;
    this.srcObject = null;
    this.webkitPresentationMode = 'inline';
    this.listeners = new Map();
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  emit(name, value = {}) {
    for (const listener of this.listeners.get(name) || []) listener(value);
  }

  click() {
    this.emit('click');
  }

  getContext() {
    return {
      imageSmoothingEnabled: false,
      drawImage: () => {
        this.draws = (this.draws || 0) + 1;
      }
    };
  }

  captureStream() {
    this.stream = new FakeStream();
    return this.stream;
  }

  play() {
    return Promise.resolve();
  }

  requestPictureInPicture() {
    document.pictureInPictureElement = this;
    this.emit('enterpictureinpicture');
    return Promise.resolve();
  }

  webkitSupportsPresentationMode(mode) {
    return mode === 'picture-in-picture';
  }

  webkitSetPresentationMode(mode) {
    this.webkitPresentationMode = mode;
    this.emit('webkitpresentationmodechanged');
  }
}

class FakeTrack {
  constructor() {
    this.kind = 'video';
    this.readyState = 'live';
    this.listeners = new Map();
    this.stopped = false;
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  stop() {
    this.stopped = true;
    this.readyState = 'ended';
    for (const listener of this.listeners.get('ended') || []) listener();
  }
}

class FakeStream {
  constructor() {
    this.track = new FakeTrack();
  }

  getTracks() {
    return [this.track];
  }

  getVideoTracks() {
    return [this.track];
  }
}

class Emitter {
  constructor() {
    this.listeners = new Map();
  }

  on(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  emit(name, ...values) {
    for (const listener of this.listeners.get(name) || []) listener(...values);
  }
}

class FakeCall extends Emitter {
  constructor(peer) {
    super();
    this.peer = peer;
    this.open = true;
    this.closed = false;
  }

  close() {
    this.closed = true;
  }
}

class FakeConnection extends Emitter {
  constructor(peer) {
    super();
    this.peer = peer;
    this.open = false;
    this.closed = false;
    this.sent = [];
    this.bufferSize = 0;
    this.dataChannel = {bufferedAmount: 0};
  }

  send(value) {
    this.sent.push(value);
  }

  close() {
    this.closed = true;
  }
}

class FakePeer extends Emitter {
  static instances = [];

  constructor(id, options) {
    super();
    this.id = id;
    this.options = options;
    this.destroyed = false;
    this.disconnected = false;
    this.calls = [];
    FakePeer.instances.push(this);
  }

  call(peer, stream, options) {
    const call = new FakeCall(peer);
    this.calls.push({peer, stream, options, call});
    return call;
  }

  destroy() {
    this.destroyed = true;
  }

  reconnect() {
    this.disconnected = false;
  }
}

const elementIds = [
  'game', 'pip-video', 'pip-toggle', 'pip-status', 'go-live', 'end-live',
  'retry-live', 'copy-link', 'source-health', 'string-health',
  'runtime-health', 'peer-health', 'viewer-count', 'viewer-limit',
  'share', 'join-link', 'stream-qr', 'host-message', 'live-badge'
];
const elements = new Map(elementIds.map(id => [id, new Element(id)]));
let now = 0;
const intervals = [];
const windowListeners = new Map();
const document = {
  pictureInPictureEnabled: true,
  pictureInPictureElement: null,
  getElementById: id => elements.get(id),
  exitPictureInPicture: async () => {
    document.pictureInPictureElement = null;
  }
};
const window = {
  addEventListener(name, listener) {
    const listeners = windowListeners.get(name) || [];
    listeners.push(listener);
    windowListeners.set(name, listeners);
  }
};
let qrCount = 0;
let bitmapFactory = async () => ({close() {}});
const context = {
  window,
  document,
  location: {
    hash: `#v=1&instance=instance-${'i'.repeat(24)}`
  },
  performance: {now: () => now},
  crypto: crypto.webcrypto,
  TextEncoder,
  URL,
  URLSearchParams,
  Blob,
  atob: value => Buffer.from(value, 'base64').toString('binary'),
  navigator: {
    clipboard: {
      writeText: async value => {
        context.copied = value;
      }
    }
  },
  Peer: FakePeer,
  QRious: class {
    constructor(options) {
      qrCount += 1;
      this.options = options;
    }
  },
  createImageBitmap: (...args) => bitmapFactory(...args),
  setInterval: callback => {
    intervals.push(callback);
    return intervals.length;
  },
  clearInterval: () => {},
  setTimeout: () => ({timer: true}),
  clearTimeout: () => {},
  console
};
context.globalThis = context;

function snapshot() {
  return {
    location: 'Pallet Town',
    objective: 'Begin',
    phase: 'overworld',
    badges: {earned: [], count: 0, total: 8},
    pokedex: {caught: 1, seen: 1, total: 151},
    party: [],
    completed: false,
    player: {mode: 'ai', paused: false},
    play_time: {
      hours: 0, minutes: 1, seconds: 2, frames: 3, maxed: false
    },
    session_elapsed_seconds: 10,
    checkpoint: null,
    viewers: {count: 0, capacity: 5}
  };
}

function pngFrame() {
  const png = Buffer.alloc(33);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
    .copy(png, 0);
  png.write('IHDR', 12, 'ascii');
  png.writeUInt32BE(160, 16);
  png.writeUInt32BE(144, 20);
  return png;
}

async function run() {
  vm.runInNewContext(source, context, {filename: 'HOST_JS'});
  const ingress = window.__RPP_KITE_HOST_V1__;
  assert(ingress);
  assert.equal(FakePeer.instances.length, 0);
  assert.equal(ingress.status().bootstrapped, false);

  const generation = `generation-${'g'.repeat(24)}`;
  const instance = `instance-${'i'.repeat(24)}`;
  const peerId = `rpp-${'a'.repeat(32)}`;
  const capability = 'w'.repeat(43);
  const joinUrl =
    `https://example.test/watch/#v=1&host=${peerId}&watch=${capability}`;
  const bootstrap = {
    build: 'rpp-kite-host-v1',
    broadcast_desired: true,
    broadcast_sequence: 0,
    frame_rate: 10,
    generation,
    instance,
    join_url: joinUrl,
    max_hello_bytes: 512,
    max_negotiating: 10,
    max_telemetry_bytes: 4096,
    max_viewers: 5,
    peer_id: peerId,
    peer_options: {
      host: '0.peerjs.com',
      port: 443,
      path: '/',
      secure: true,
      debug: 0,
      config: {iceServers: [{urls: 'stun:stun.l.google.com:19302'}]}
    },
    protocol_version: 1,
    telemetry_version: 1,
    watch_capability: capability
  };
  assert.equal(ingress.bootstrap({...bootstrap, extra: true}).ok, false);
  assert.equal(ingress.bootstrap(bootstrap).ok, true);
  assert.equal(qrCount, 1);
  assert.equal(FakePeer.instances.length, 0);
  assert.equal(elements.get('join-link').href, joinUrl);

  assert.equal(ingress.heartbeat({
    generation,
    instance,
    sequence: 1,
    source_sequence: 0,
    source_hash: '',
    runtime_state: 'ready'
  }).ok, true);
  const png = pngFrame();
  const hash = crypto.createHash('sha256').update(png).digest('hex');
  assert.equal((await ingress.frame({
    generation,
    instance,
    sequence: 1,
    sha256: hash,
    png_base64: png.toString('base64')
  })).ok, true);
  assert.equal(FakePeer.instances.length, 1);
  const peer = FakePeer.instances[0];
  peer.emit('open', peerId);
  assert.equal(ingress.status().share_ready, true);

  assert.equal((await ingress.frame({
    generation,
    instance,
    sequence: 1,
    sha256: hash,
    png_base64: png.toString('base64')
  })).ok, false);

  const resolvers = [];
  bitmapFactory = () => new Promise(resolve => {
    resolvers.push(resolve);
  });
  const secondPng = Buffer.from(png);
  secondPng[32] = 2;
  const thirdPng = Buffer.from(png);
  thirdPng[32] = 3;
  const thirdHash = crypto.createHash('sha256').update(thirdPng).digest('hex');
  const secondFrame = ingress.frame({
    generation,
    instance,
    sequence: 2,
    sha256: crypto.createHash('sha256').update(secondPng).digest('hex'),
    png_base64: secondPng.toString('base64')
  });
  while (resolvers.length < 1) {
    await new Promise(resolve => setImmediate(resolve));
  }
  const thirdFrame = ingress.frame({
    generation,
    instance,
    sequence: 3,
    sha256: thirdHash,
    png_base64: thirdPng.toString('base64')
  });
  while (resolvers.length < 2) {
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.equal(resolvers.length, 2);
  resolvers[1]({close() {}});
  assert.equal((await thirdFrame).ok, true);
  resolvers[0]({close() {}});
  assert.equal((await secondFrame).reason, 'superseded');
  assert.equal(ingress.status().frame_sequence, 3);
  bitmapFactory = async () => ({close() {}});

  assert.equal(ingress.telemetry({
    generation,
    instance,
    sequence: 1,
    snapshot: snapshot()
  }).ok, true);
  assert.equal(ingress.telemetry({
    generation,
    instance,
    sequence: 1,
    snapshot: snapshot()
  }).ok, false);

  const first = new FakeConnection('viewer-one');
  const second = new FakeConnection('viewer-two');
  peer.emit('connection', first);
  peer.emit('connection', second);
  first.open = true;
  second.open = true;
  first.emit('open');
  second.emit('open');
  first.emit('data', {v: 1, type: 'watch', cap: capability});
  second.emit('data', {v: 1, type: 'watch', cap: capability});
  assert.equal(ingress.status().viewer_count, 2);
  assert(first.sent.some(value => value.type === 'ready'));
  assert(first.sent.some(value => value.type === 'telemetry'));
  const secondTelemetryBefore = second.sent.filter(
    value => value.type === 'telemetry'
  ).length;
  second.dataChannel.bufferedAmount = 9000;
  const changed = snapshot();
  changed.objective = 'Changed';
  now += 1000;
  assert.equal(ingress.telemetry({
    generation,
    instance,
    sequence: 2,
    snapshot: changed
  }).ok, true);
  assert.equal(
    second.sent.filter(value => value.type === 'telemetry').length,
    secondTelemetryBefore
  );
  second.dataChannel.bufferedAmount = 0;
  now += 5000;
  assert.equal(ingress.telemetry({
    generation,
    instance,
    sequence: 3,
    snapshot: changed
  }).ok, true);
  assert(
    second.sent.filter(value => value.type === 'telemetry').length >
      secondTelemetryBefore
  );

  peer.emit('error', {
    type: 'peer-unavailable',
    peer: 'viewer-one'
  });
  assert.equal(first.closed, true);
  assert.equal(second.closed, false);
  assert.equal(ingress.status().viewer_count, 1);
  second.emit('data', {v: 1, type: 'watch', cap: capability});
  assert.equal(second.closed, true);
  assert.equal(ingress.status().viewer_count, 0);

  elements.get('pip-video').srcObject = elements.get('game').stream;
  elements.get('pip-video').emit('loadedmetadata');
  elements.get('pip-toggle').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(document.pictureInPictureElement, elements.get('pip-video'));
  document.pictureInPictureElement = null;
  document.pictureInPictureEnabled = false;
  elements.get('pip-toggle').click();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(
    elements.get('pip-video').webkitPresentationMode,
    'picture-in-picture'
  );

  elements.get('end-live').click();
  assert.equal(ingress.status().peer_open, false);
  assert.equal(ingress.status().broadcast_desired, false);
  assert.equal(ingress.status().broadcast_sequence, 1);
  assert.equal(elements.get('join-link').href, joinUrl);
  assert.equal(elements.get('share').hidden, false);

  const refreshed = ingress.heartbeat({
    generation,
    instance,
    sequence: 2,
    source_sequence: 4,
    source_hash: thirdHash,
    runtime_state: 'ready'
  });
  assert.equal(refreshed.ok, true);
  assert.equal(refreshed.source_accepted, true);
  assert.equal(ingress.status().peer_open, false);
  elements.get('retry-live').click();
  const replacement = FakePeer.instances.at(-1);
  replacement.emit('open', peerId);
  assert.equal(ingress.status().peer_open, true);
  assert.equal(ingress.status().broadcast_desired, true);
  assert.equal(ingress.status().broadcast_sequence, 2);

  bitmapFactory = async () => {
    throw new Error('synthetic decode rejection');
  };
  const rejectedPng = Buffer.from(png);
  rejectedPng[32] = 4;
  const rejectedHash = crypto
    .createHash('sha256')
    .update(rejectedPng)
    .digest('hex');
  const rejected = await ingress.frame({
    generation,
    instance,
    sequence: 4,
    sha256: rejectedHash,
    png_base64: rejectedPng.toString('base64')
  });
  assert.equal(rejected.ok, false);
  assert.equal(rejected.reason, 'decode');
  assert.equal(ingress.status().frame_sequence, 3);
  assert.equal(ingress.status().frame_hash, thirdHash);
  assert.equal(ingress.status().frame_attempted_sequence, 4);
  assert.equal(ingress.status().source_health, 'lost');
  assert.equal(ingress.status().share_ready, false);
  assert.equal(replacement.destroyed, true);
  bitmapFactory = async () => ({close() {}});
  const rejectedHeartbeat = ingress.heartbeat({
    generation,
    instance,
    sequence: 3,
    source_sequence: 5,
    source_hash: rejectedHash,
    runtime_state: 'ready'
  });
  assert.equal(rejectedHeartbeat.ok, true);
  assert.equal(rejectedHeartbeat.source_accepted, false);
  assert.equal(ingress.status().share_ready, false);

  now += 13_000;
  for (const interval of intervals) interval();
  const lost = ingress.status();
  assert.equal(lost.string_health, 'lost');
  assert.equal(lost.state, 'error');
  assert.equal(replacement.destroyed, true);

  assert.equal(ingress.shutdown({
    generation,
    instance,
    sequence: 1
  }).ok, true);
  assert.equal(ingress.status().state, 'stopped');
  process.stdout.write('host contracts passed\n');
}
