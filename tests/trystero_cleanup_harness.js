'use strict';

const assert = require('node:assert/strict');
const vm = require('node:vm');

let source = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  source += chunk;
});
process.stdin.on('end', () => run().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
}));

async function run() {
  const sockets = [];
  const reconnectTimers = new Set();
  let captureReconnectTimer = false;
  const managedSetTimeout = (callback, delay) => {
    if (captureReconnectTimer) {
      const handle = {callback};
      reconnectTimers.add(handle);
      return handle;
    }
    return setTimeout(callback, delay);
  };
  const managedClearTimeout = handle => {
    if (reconnectTimers.delete(handle)) return;
    clearTimeout(handle);
  };
  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.sent = [];
      sockets.push(this);
      queueMicrotask(() => {
        if (this.readyState !== 0) return;
        this.readyState = 1;
        if (this.onopen) this.onopen();
      });
    }

    send(value) {
      this.sent.push(value);
    }

    close() {
      if (this.readyState === 3) return;
      this.readyState = 3;
      if (this.onclose) this.onclose();
    }
  }
  class FakeDataChannel {
    constructor() {
      this.readyState = 'connecting';
      this.bufferedAmount = 0;
    }

    send() {}

    close() {
      this.readyState = 'closed';
      if (this.onclose) this.onclose();
    }
  }
  class FakeRTCPeerConnection {
    constructor() {
      this.connectionState = 'new';
      this.iceConnectionState = 'new';
      this.iceGatheringState = 'complete';
      this.signalingState = 'stable';
      this.localDescription = null;
      this.remoteDescription = null;
    }

    addEventListener() {}

    removeEventListener() {}

    createDataChannel() {
      return new FakeDataChannel();
    }

    async createOffer() {
      return {type: 'offer', sdp: 'v=0\r\n'};
    }

    async setLocalDescription(description) {
      if (description && description.type === 'rollback') {
        this.localDescription = null;
        return;
      }
      this.localDescription = description || {
        type: this.remoteDescription ? 'answer' : 'offer',
        sdp: 'v=0\r\n'
      };
    }

    async setRemoteDescription(description) {
      this.remoteDescription = description;
    }

    async addIceCandidate() {}

    close() {
      this.connectionState = 'closed';
    }
  }

  const listeners = new Map();
  const deterministicMath = Object.create(Math);
  deterministicMath.random = () => 0;
  const context = {
    WebSocket: FakeWebSocket,
    crypto: global.crypto,
    TextEncoder,
    TextDecoder,
    Uint8Array,
    ArrayBuffer,
    DataView,
    Math: deterministicMath,
    Date,
    JSON,
    Promise,
    AbortController,
    Blob,
    Event: global.Event,
    RTCPeerConnection: FakeRTCPeerConnection,
    setTimeout: managedSetTimeout,
    clearTimeout: managedClearTimeout,
    setInterval,
    clearInterval,
    queueMicrotask,
    console,
    window: {},
    addEventListener(name, listener) {
      listeners.set(name, listener);
    },
    removeEventListener(name) {
      listeners.delete(name);
    }
  };
  context.globalThis = context;
  vm.runInNewContext(source, context, {filename: 'trystero-nostr-rpp.js'});
  const api = context.RppTrysteroNostr;
  assert(api);
  assert.equal(typeof api.disposeRelaySockets, 'function');
  assert.equal(typeof api.getRelayHealth, 'function');

  const relays = [
    'wss://communities.nos.social',
    'wss://purplerelay.com',
    'wss://bucket.coracle.social',
    'wss://relay.nostr.place',
    'wss://relay.damus.io'
  ];
  const config = {
    appId: 'rappter-plays-pokemon-v2',
    password: 'room-key',
    passive: true,
    relayConfig: {
      urls: relays,
      redundancy: relays.length,
      warnOnRelayFailure: false
    },
    rtcConfig: {
      iceServers: [{urls: 'stun:stun.l.google.com:19302'}]
    }
  };
  const first = api.joinRoom(config, 'cleanup-room');
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(sockets.length, 5);
  assert(sockets.every(socket => socket.readyState === 1));

  sockets[0].readyState = 3;
  assert.equal(typeof sockets[0].__rppSuspend, 'function');
  captureReconnectTimer = true;
  sockets[0].onclose();
  captureReconnectTimer = false;
  assert.equal(reconnectTimers.size, 1);
  await first.leave();
  assert.equal(reconnectTimers.size, 0);
  assert.equal(
    sockets.length,
    5,
    'last-room leave cancels an already scheduled relay reconnect'
  );
  assert(sockets.every(socket => socket.readyState === 3));
  const afterEnd = sockets.length;
  await new Promise(resolve => setTimeout(resolve, 50));
  assert.equal(
    sockets.length,
    afterEnd,
    'last-room disposal must leave no relay reconnect activity'
  );

  const second = api.joinRoom(config, 'cleanup-room');
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(sockets.length, 10);
  assert(sockets.slice(5).every(socket => socket.readyState === 1));
  assert.notEqual(first, second);
  await second.leave();
  assert(sockets.slice(5).every(socket => socket.readyState === 3));

  await testDelayedReadyRetry();
  await testQualificationLifecycle();
  await testPublishedEventBound();
  process.stdout.write('trystero cleanup contracts passed\n');
}

function createRuntime({
  autoOpen = true,
  interceptAnnouncements = false,
  initialNow = Date.now()
} = {}) {
  const sockets = [];
  const reconnectTimers = new Set();
  const announceTimers = [];
  let captureReconnectTimer = false;
  let nowMs = initialNow;

  const managedSetTimeout = (callback, delay) => {
    if (captureReconnectTimer) {
      const handle = {callback};
      reconnectTimers.add(handle);
      return handle;
    }
    if (interceptAnnouncements && delay >= 200) {
      const handle = {callback};
      announceTimers.push(handle);
      return handle;
    }
    return setTimeout(callback, delay);
  };
  const managedClearTimeout = handle => {
    if (reconnectTimers.delete(handle)) return;
    const announceIndex = announceTimers.indexOf(handle);
    if (announceIndex >= 0) {
      announceTimers.splice(announceIndex, 1);
      return;
    }
    clearTimeout(handle);
  };
  class FakeDate extends Date {
    static now() {
      return nowMs;
    }
  }
  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 0;
      this.sent = [];
      this.onerror = null;
      sockets.push(this);
      if (autoOpen) queueMicrotask(() => this.open());
    }

    open() {
      if (this.readyState !== 0) return;
      this.readyState = 1;
      if (this.onopen) this.onopen();
    }

    send(value) {
      this.sent.push(value);
    }

    message(value) {
      if (this.onmessage) {
        this.onmessage({data: JSON.stringify(value)});
      }
    }

    fail() {
      if (this.onerror) this.onerror(new Error('relay error'));
    }

    close() {
      if (this.readyState === 3) return;
      this.readyState = 3;
      if (this.onclose) this.onclose();
    }
  }
  class FakeDataChannel {
    constructor() {
      this.readyState = 'connecting';
      this.bufferedAmount = 0;
    }

    send() {}

    close() {
      this.readyState = 'closed';
      if (this.onclose) this.onclose();
    }
  }
  class FakeRTCPeerConnection {
    constructor() {
      this.connectionState = 'new';
      this.iceConnectionState = 'new';
      this.iceGatheringState = 'complete';
      this.signalingState = 'stable';
      this.localDescription = null;
      this.remoteDescription = null;
    }

    addEventListener() {}

    removeEventListener() {}

    createDataChannel() {
      return new FakeDataChannel();
    }

    async createOffer() {
      return {type: 'offer', sdp: 'v=0\r\n'};
    }

    async setLocalDescription(description) {
      if (description && description.type === 'rollback') {
        this.localDescription = null;
        return;
      }
      this.localDescription = description || {
        type: this.remoteDescription ? 'answer' : 'offer',
        sdp: 'v=0\r\n'
      };
    }

    async setRemoteDescription(description) {
      this.remoteDescription = description;
    }

    async addIceCandidate() {}

    close() {
      this.connectionState = 'closed';
    }
  }

  const listeners = new Map();
  const context = {
    WebSocket: FakeWebSocket,
    crypto: global.crypto,
    TextEncoder,
    TextDecoder,
    Uint8Array,
    ArrayBuffer,
    DataView,
    Math,
    Date: FakeDate,
    JSON,
    AbortController,
    Blob,
    Event: global.Event,
    RTCPeerConnection: FakeRTCPeerConnection,
    setTimeout: managedSetTimeout,
    clearTimeout: managedClearTimeout,
    setInterval,
    clearInterval,
    queueMicrotask,
    console,
    window: {},
    addEventListener(name, listener) {
      listeners.set(name, listener);
    },
    removeEventListener(name) {
      listeners.delete(name);
    }
  };
  context.globalThis = context;
  vm.runInNewContext(source, context, {filename: 'trystero-nostr-rpp.js'});

  return {
    api: context.RppTrysteroNostr,
    sockets,
    reconnectTimers,
    announceTimers,
    advance(milliseconds) {
      nowMs += milliseconds;
    },
    captureReconnect(callback) {
      captureReconnectTimer = true;
      try {
        callback();
      } finally {
        captureReconnectTimer = false;
      }
    }
  };
}

function relayConfig(relays, passive) {
  return {
    appId: 'rappter-plays-pokemon-v2',
    password: 'room-key',
    passive,
    relayConfig: {
      urls: relays,
      redundancy: relays.length,
      warnOnRelayFailure: false
    },
    rtcConfig: {
      iceServers: [{urls: 'stun:stun.l.google.com:19302'}]
    }
  };
}

const wait = milliseconds =>
  new Promise(resolve => setTimeout(resolve, milliseconds));

async function waitFor(predicate, message, timeoutMs = 1500) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() >= deadline) throw new Error(message);
    await wait(2);
  }
}

function publishedEvents(socket) {
  return socket.sent.map(value => JSON.parse(value)).filter(
    value => value[0] === 'EVENT' && value[1] && value[1].id
  );
}

function qualify(socket, event) {
  socket.message(['OK', event.id, true, '']);
  socket.message(['EVENT', 'delivery-proof', event]);
}

async function testDelayedReadyRetry() {
  const runtime = createRuntime({autoOpen: false});
  const relay = 'wss://ready-delay.example';
  const config = relayConfig([relay], true);
  const first = runtime.api.joinRoom(config, 'ready-delay-room');
  assert.equal(
    runtime.api.joinRoom(config, 'ready-delay-room'),
    first,
    'an occupied room remains cache-stable before leave'
  );
  await first.leave();
  assert.equal(runtime.sockets.length, 1);
  assert.equal(runtime.sockets[0].readyState, 3);

  const replacement = runtime.api.joinRoom(config, 'ready-delay-room');
  assert.notEqual(replacement, first);
  assert.equal(runtime.sockets.length, 2);
  runtime.sockets[1].open();
  await waitFor(
    () => runtime.sockets[1].sent.some(
      value => JSON.parse(value)[0] === 'REQ'
    ),
    'replacement subscription was not installed after delayed readiness'
  );
  const controls = runtime.sockets[1].sent.map(value => JSON.parse(value));
  const latestRequest = controls.findLastIndex(value => value[0] === 'REQ');
  const laterClose = controls.findIndex(
    (value, index) => index > latestRequest && value[0] === 'CLOSE'
  );
  assert.equal(
    laterClose,
    -1,
    'stale cleanup must not close the replacement subscription'
  );
  await replacement.leave();
}

async function testQualificationLifecycle() {
  const runtime = createRuntime();
  const relay = 'wss://qualification.example';
  const room = runtime.api.joinRoom(
    relayConfig([relay], false),
    'qualification-room'
  );
  await waitFor(
    () => publishedEvents(runtime.sockets[0]).length > 0,
    'initial qualification publication was not sent'
  );
  const firstSocket = runtime.sockets[0];
  const firstEvent = publishedEvents(firstSocket).at(-1)[1];
  qualify(firstSocket, firstEvent);
  assert.equal(runtime.api.getRelayHealth()[relay].qualified, true);

  runtime.captureReconnect(() => firstSocket.close());
  assert.deepEqual(
    {...runtime.api.getRelayHealth()[relay]},
    {accepted: false, delivered: false, qualified: false}
  );
  assert.equal(runtime.reconnectTimers.size, 1);
  const reconnect = [...runtime.reconnectTimers][0];
  runtime.reconnectTimers.delete(reconnect);
  reconnect.callback();
  await waitFor(
    () => runtime.sockets.length === 2 && runtime.sockets[1].readyState === 1,
    'relay did not reconnect'
  );
  const secondSocket = runtime.sockets[1];
  assert.deepEqual(
    {...runtime.api.getRelayHealth()[relay]},
    {accepted: false, delivered: false, qualified: false}
  );
  qualify(secondSocket, firstEvent);
  assert.equal(
    runtime.api.getRelayHealth()[relay].qualified,
    false,
    'old-socket proofs must not qualify a replacement socket'
  );
  await waitFor(
    () => publishedEvents(secondSocket).length > 0,
    'replacement socket did not publish a fresh qualification event'
  );
  const secondEvent = publishedEvents(secondSocket).at(-1)[1];
  qualify(secondSocket, secondEvent);
  assert.equal(runtime.api.getRelayHealth()[relay].qualified, true);
  secondSocket.fail();
  assert.deepEqual(
    {...runtime.api.getRelayHealth()[relay]},
    {accepted: false, delivered: false, qualified: false}
  );
  await room.leave();
}

async function testPublishedEventBound() {
  const runtime = createRuntime({
    interceptAnnouncements: true,
    initialNow: Date.parse('2026-07-17T00:00:00.000Z')
  });
  const relay = 'wss://bounded-publications.example';
  const room = runtime.api.joinRoom(
    relayConfig([relay], false),
    'bounded-publications-room'
  );
  const socket = runtime.sockets[0];
  await waitFor(
    () => publishedEvents(socket).length > 0,
    'initial bounded-state publication was not sent'
  );
  while (publishedEvents(socket).length < 300) {
    await waitFor(
      () => runtime.announceTimers.length > 0,
      'next qualification publication was not scheduled'
    );
    const timer = runtime.announceTimers.shift();
    const before = publishedEvents(socket).length;
    runtime.advance(1001);
    timer.callback();
    await waitFor(
      () => publishedEvents(socket).length > before,
      'scheduled qualification publication was not sent'
    );
  }
  const events = publishedEvents(socket);
  qualify(socket, events[0][1]);
  assert.deepEqual(
    {...runtime.api.getRelayHealth()[relay]},
    {accepted: false, delivered: false, qualified: false},
    'the oldest of 300 publications must be outside the 256-entry window'
  );

  const newest = events.at(-1)[1];
  runtime.advance(60_001);
  runtime.api.getRelayHealth();
  qualify(socket, newest);
  assert.equal(
    runtime.api.getRelayHealth()[relay].qualified,
    false,
    'expired publication IDs must not qualify a relay'
  );

  const timer = runtime.announceTimers.shift();
  assert(timer);
  const before = publishedEvents(socket).length;
  runtime.advance(1001);
  timer.callback();
  await waitFor(
    () => publishedEvents(socket).length > before,
    'fresh post-expiry publication was not sent'
  );
  qualify(socket, publishedEvents(socket).at(-1)[1]);
  assert.equal(runtime.api.getRelayHealth()[relay].qualified, true);
  await room.leave();
}
