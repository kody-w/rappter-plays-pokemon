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
      this.url = new URL(url).href;
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
  assert.equal(typeof api.qualifyRelays, 'function');

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
  await testEmptyRoomQualification();
  await testPartialAndInvalidProofs();
  await testRejectAndTimeoutCleanup();
  await testQualificationReconnect();
  await testPublishedEventBound();
  process.stdout.write('trystero cleanup contracts passed\n');
}

function createRuntime({
  autoOpen = true,
  interceptAnnouncements = false,
  interceptProbeTimeouts = false,
  initialNow = Date.now()
} = {}) {
  const sockets = [];
  const reconnectTimers = new Set();
  const announceTimers = [];
  const probeTimers = [];
  let captureReconnectTimer = false;
  let nowMs = initialNow;

  const managedSetTimeout = (callback, delay) => {
    if (captureReconnectTimer) {
      const handle = {callback};
      reconnectTimers.add(handle);
      return handle;
    }
    if (interceptProbeTimeouts && delay === 10000) {
      const handle = {callback, delay};
      probeTimers.push(handle);
      return handle;
    }
    if (interceptAnnouncements && delay >= 200) {
      const handle = {callback, delay};
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
    const probeIndex = probeTimers.indexOf(handle);
    if (probeIndex >= 0) {
      probeTimers.splice(probeIndex, 1);
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
      this.url = new URL(url).href;
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
    probeTimers,
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

const probeMarker = 'rpp-relay-qualification-v1:';

function qualificationEvents(socket) {
  return publishedEvents(socket).filter(
    value => value[1].content.startsWith(probeMarker)
  );
}

function qualificationTraffic(socket) {
  const event = qualificationEvents(socket).at(-1)?.[1];
  assert(event, 'qualification EVENT is missing');
  const topic = event.tags[0][1];
  const request = socket.sent.map(value => JSON.parse(value)).find(value =>
    value[0] === 'REQ' &&
    value[2] &&
    Array.isArray(value[2]['#x']) &&
    value[2]['#x'][0] === topic
  );
  assert(request, 'qualification REQ is missing');
  return {event, request, subId: request[1], topic};
}

function deliverQualification(socket, traffic, event = traffic.event) {
  socket.message(['EVENT', traffic.subId, event]);
}

function qualify(socket, traffic = qualificationTraffic(socket)) {
  socket.message(['OK', traffic.event.id, true, '']);
  deliverQualification(socket, traffic);
}

function fireProbeTimeout(runtime, index = 0) {
  const timer = runtime.probeTimers[index];
  assert(timer, 'qualification timeout is missing');
  timer.callback();
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

async function testEmptyRoomQualification() {
  const runtime = createRuntime();
  const relay = 'wss://empty-room.example';
  const room = runtime.api.joinRoom(
    relayConfig([relay], false),
    'empty-room'
  );
  const qualification = runtime.api.qualifyRelays();
  await waitFor(
    () => qualificationEvents(runtime.sockets[0]).length === 1,
    'empty room did not send an explicit qualification probe'
  );
  const socket = runtime.sockets[0];
  const traffic = qualificationTraffic(socket);
  assert.match(traffic.event.id, /^[a-f0-9]{64}$/);
  assert.match(traffic.event.sig, /^[a-f0-9]{128}$/);
  assert.equal(
    traffic.event.id,
    crypto.createHash('sha256').update(JSON.stringify([
      0,
      traffic.event.pubkey,
      traffic.event.created_at,
      traffic.event.kind,
      traffic.event.tags,
      traffic.event.content
    ])).digest('hex'),
    'probe EVENT ID must commit to the exact Nostr payload'
  );
  assert.match(traffic.topic, /^rpp-relay-qualification-v1:[a-f0-9]{64}$/);
  assert.match(
    traffic.event.content,
    /^rpp-relay-qualification-v1:[a-f0-9]{64}$/
  );
  assert.deepEqual(traffic.request[2].authors, [traffic.event.pubkey]);
  assert.deepEqual(traffic.request[2].kinds, [traffic.event.kind]);
  assert.equal(
    runtime.api.getRelayHealth()[new URL(relay).href],
    undefined,
    'health must retain the configured relay key, not WebSocket URL normalization'
  );
  assert.equal(runtime.api.getRelayHealth()[relay].qualifying, true);
  socket.message(['OK', traffic.event.id, true, '']);
  assert.equal(
    runtime.api.getRelayHealth()[relay].qualified,
    false,
    'OK without subscribed delivery must not qualify'
  );
  deliverQualification(socket, traffic);
  await qualification;
  assert.equal(runtime.api.getRelayHealth()[relay].qualified, true);
  assert.equal(runtime.api.getRelayHealth()[relay].qualifying, false);
  assert(socket.sent.some(value => {
    const message = JSON.parse(value);
    return message[0] === 'CLOSE' && message[1] === traffic.subId;
  }));
  await runtime.api.qualifyRelays();
  assert.equal(
    qualificationEvents(socket).length,
    1,
    'a socket generation gets at most one qualification probe'
  );
  await room.leave();
}

async function testPartialAndInvalidProofs() {
  const runtime = createRuntime({interceptProbeTimeouts: true});
  const relays = [
    'wss://ok-only.example',
    'wss://delivery-only.example',
    'wss://invalid-proof.example'
  ];
  const room = runtime.api.joinRoom(
    relayConfig(relays, false),
    'partial-proof-room'
  );
  const qualification = runtime.api.qualifyRelays();
  await waitFor(
    () => runtime.sockets.every(
      socket => qualificationEvents(socket).length === 1
    ),
    'partial-proof probes were not sent'
  );
  const [okSocket, deliverySocket, invalidSocket] = runtime.sockets;
  const okTraffic = qualificationTraffic(okSocket);
  const deliveryTraffic = qualificationTraffic(deliverySocket);
  const invalidTraffic = qualificationTraffic(invalidSocket);

  okSocket.message(['OK', okTraffic.event.id, true, '']);
  deliverQualification(deliverySocket, deliveryTraffic);
  invalidSocket.message(['OK', 'f'.repeat(64), true, '']);
  invalidSocket.message([
    'EVENT',
    invalidTraffic.subId,
    {...invalidTraffic.event, id: 'e'.repeat(64)}
  ]);
  invalidSocket.message([
    'EVENT',
    `${invalidTraffic.subId}-wrong`,
    invalidTraffic.event
  ]);
  invalidSocket.message([
    'EVENT',
    invalidTraffic.subId,
    {
      ...invalidTraffic.event,
      tags: [['x', `${invalidTraffic.topic}-wrong`]]
    }
  ]);
  for (const relay of relays) {
    assert.equal(runtime.api.getRelayHealth()[relay].qualified, false);
  }
  assert.equal(runtime.api.getRelayHealth()[relays[0]].accepted, true);
  assert.equal(runtime.api.getRelayHealth()[relays[0]].delivered, false);
  assert.equal(runtime.api.getRelayHealth()[relays[1]].accepted, false);
  assert.equal(runtime.api.getRelayHealth()[relays[1]].delivered, true);
  for (const timer of [...runtime.probeTimers]) timer.callback();
  await qualification;
  assert.equal(runtime.probeTimers.length, 0);
  for (const [index, relay] of relays.entries()) {
    const health = runtime.api.getRelayHealth()[relay];
    assert.equal(health.qualified, false);
    assert.equal(health.qualifying, false);
    const traffic = [okTraffic, deliveryTraffic, invalidTraffic][index];
    assert(runtime.sockets[index].sent.some(value => {
      const message = JSON.parse(value);
      return message[0] === 'CLOSE' && message[1] === traffic.subId;
    }));
  }
  await room.leave();
}

async function testRejectAndTimeoutCleanup() {
  const runtime = createRuntime({interceptProbeTimeouts: true});
  const relays = [
    'wss://reject.example',
    'wss://timeout.example'
  ];
  const room = runtime.api.joinRoom(
    relayConfig(relays, false),
    'failed-proof-room'
  );
  const qualification = runtime.api.qualifyRelays();
  await waitFor(
    () => runtime.sockets.every(
      socket => qualificationEvents(socket).length === 1
    ),
    'failure probes were not sent'
  );
  const rejected = qualificationTraffic(runtime.sockets[0]);
  const timedOut = qualificationTraffic(runtime.sockets[1]);
  runtime.sockets[0].message([
    'OK',
    rejected.event.id,
    false,
    'rejected'
  ]);
  assert.equal(runtime.probeTimers.length, 1);
  fireProbeTimeout(runtime);
  await qualification;
  assert.equal(runtime.probeTimers.length, 0);
  for (const [index, relay] of relays.entries()) {
    const health = runtime.api.getRelayHealth()[relay];
    assert.equal(health.qualified, false);
    assert.equal(health.qualifying, false);
    const traffic = [rejected, timedOut][index];
    assert(runtime.sockets[index].sent.some(value => {
      const message = JSON.parse(value);
      return message[0] === 'CLOSE' && message[1] === traffic.subId;
    }));
  }
  await runtime.api.qualifyRelays();
  assert(runtime.sockets.every(
    socket => qualificationEvents(socket).length === 1
  ));
  await room.leave();
}

async function testQualificationReconnect() {
  const runtime = createRuntime();
  const relay = 'wss://qualification-reconnect.example';
  const room = runtime.api.joinRoom(
    relayConfig([relay], false),
    'qualification-reconnect-room'
  );
  const initialQualification = runtime.api.qualifyRelays();
  await waitFor(
    () => qualificationEvents(runtime.sockets[0]).length === 1,
    'initial reconnect probe was not sent'
  );
  const firstSocket = runtime.sockets[0];
  const firstTraffic = qualificationTraffic(firstSocket);
  void runtime.api.qualifyRelays();
  assert.equal(qualificationEvents(firstSocket).length, 1);

  runtime.captureReconnect(() => firstSocket.close());
  await initialQualification;
  assert.equal(runtime.api.getRelayHealth()[relay].qualified, false);
  assert.equal(runtime.reconnectTimers.size, 1);
  const reconnect = [...runtime.reconnectTimers][0];
  runtime.reconnectTimers.delete(reconnect);
  reconnect.callback();
  await waitFor(
    () => runtime.sockets.length === 2 && runtime.sockets[1].readyState === 1,
    'relay did not reconnect'
  );
  const secondSocket = runtime.sockets[1];
  await waitFor(
    () => qualificationEvents(secondSocket).length === 1,
    'replacement socket did not send a fresh probe'
  );
  const secondTraffic = qualificationTraffic(secondSocket);
  assert.notEqual(secondTraffic.event.id, firstTraffic.event.id);
  assert.notEqual(secondTraffic.topic, firstTraffic.topic);
  qualify(firstSocket, firstTraffic);
  secondSocket.message(['OK', firstTraffic.event.id, true, '']);
  secondSocket.message([
    'EVENT',
    firstTraffic.subId,
    firstTraffic.event
  ]);
  assert.equal(
    runtime.api.getRelayHealth()[relay].qualified,
    false,
    'old-socket proofs must not qualify a replacement socket'
  );
  void runtime.api.qualifyRelays();
  assert.equal(qualificationEvents(secondSocket).length, 1);
  qualify(secondSocket, secondTraffic);
  assert.equal(runtime.api.getRelayHealth()[relay].qualified, true);
  secondSocket.fail();
  assert.equal(runtime.api.getRelayHealth()[relay].qualified, false);
  await room.leave();
}

async function testPublishedEventBound() {
  const runtime = createRuntime({
    interceptProbeTimeouts: true,
    initialNow: Date.parse('2026-07-17T00:00:00.000Z')
  });
  const relay = 'wss://bounded-publications.example';
  const config = relayConfig([relay], false);
  const rooms = Array.from(
    {length: 300},
    (_, index) => runtime.api.joinRoom(
      config,
      `bounded-publications-room-${index}`
    )
  );
  const socket = runtime.sockets[0];
  await waitFor(
    () => socket.readyState === 1,
    'bounded-state relay did not open'
  );
  const qualification = runtime.api.qualifyRelays();
  await waitFor(
    () => qualificationEvents(socket).length === 1,
    'bounded-state probe was not sent'
  );
  const ordinaryEvents = () => publishedEvents(socket).filter(
    value => !value[1].content.startsWith(probeMarker)
  );
  await waitFor(
    () => ordinaryEvents().length >= 300,
    '300 distinct signaling publications were not sent'
  );
  assert.equal(
    runtime.api.getRelayHealth()[relay].pendingPublicationCount,
    256
  );
  const events = ordinaryEvents();
  socket.message(['OK', events[0][1].id, true, '']);
  socket.message(['EVENT', 'ordinary-delivery', events[0][1]]);
  assert.equal(
    runtime.api.getRelayHealth()[relay].pendingPublicationCount,
    256,
    'the oldest of 300 publications must be outside the 256-entry window'
  );
  const newest = events.at(-1)[1];
  socket.message(['OK', newest.id, true, '']);
  socket.message(['EVENT', 'ordinary-delivery', newest]);
  assert.equal(
    runtime.api.getRelayHealth()[relay].pendingPublicationCount,
    255
  );
  assert.equal(
    runtime.api.getRelayHealth()[relay].qualified,
    false,
    'signaling publications must not replace the explicit probe'
  );
  runtime.advance(60_001);
  assert.equal(
    runtime.api.getRelayHealth()[relay].pendingPublicationCount,
    0,
    'published IDs must expire'
  );
  assert.equal(qualificationEvents(socket).length, 1);
  qualify(socket);
  await qualification;
  assert.equal(runtime.api.getRelayHealth()[relay].qualified, true);
  assert.equal(runtime.probeTimers.length, 0);
  await Promise.all(rooms.map(room => room.leave()));
}
