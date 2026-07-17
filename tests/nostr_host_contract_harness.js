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

class Element {
  constructor(id) {
    this.id = id;
    this.textContent = '';
    this.className = '';
    this.hidden = false;
    this.disabled = false;
    this.href = '';
    this.value = '';
    this.readyState = 1;
    this.srcObject = null;
    this.listeners = new Map();
    this.classList = {toggle: () => {}};
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  async emit(name, value = {}) {
    for (const listener of this.listeners.get(name) || []) {
      await listener(value);
    }
  }

  getContext() {
    return {
      imageSmoothingEnabled: false,
      drawImage: () => {},
      clearRect: () => {}
    };
  }

  captureStream() {
    return new FakeStream();
  }

  play() {
    return Promise.resolve();
  }

  webkitSupportsPresentationMode() {
    return false;
  }
}

class FakeTrack {
  constructor() {
    this.readyState = 'live';
    this.listeners = new Map();
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  stop() {
    this.readyState = 'ended';
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

class FakePc {
  constructor() {
    this.connectionState = 'connected';
    this.iceConnectionState = 'connected';
    this.listeners = new Map();
    this.closed = false;
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  close() {
    this.closed = true;
    this.connectionState = 'closed';
  }

  async getStats() {
    return new Map();
  }
}

function pngFrame() {
  const bytes = Buffer.alloc(33);
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
    .copy(bytes);
  bytes.write('IHDR', 12, 'ascii');
  bytes.writeUInt32BE(160, 16);
  bytes.writeUInt32BE(144, 20);
  return bytes;
}

async function hostIdentity(pairing) {
  const keys = await crypto.webcrypto.subtle.generateKey(
    {name: 'ECDSA', namedCurve: 'P-256'},
    true,
    ['sign', 'verify']
  );
  const pub = await crypto.webcrypto.subtle.exportKey('jwk', keys.publicKey);
  const priv = await crypto.webcrypto.subtle.exportKey('jwk', keys.privateKey);
  const publicJwk = {
    crv: 'P-256',
    ext: true,
    key_ops: ['verify'],
    kty: 'EC',
    x: pub.x,
    y: pub.y
  };
  const privateJwk = {
    crv: 'P-256',
    d: priv.d,
    ext: true,
    key_ops: ['sign'],
    kty: 'EC',
    x: priv.x,
    y: priv.y
  };
  return {
    publicKey: pairing.publicKeyToken(publicJwk),
    privateJwk
  };
}

async function run() {
  require('../docs/host/v2/pairing.rpp-v2.js');
  const pairing = global.RppPairing;
  const plain = value => JSON.parse(JSON.stringify(value));
  const ids = [
    'game', 'pip-video', 'pip-toggle', 'pip-status', 'go-live', 'end-live',
    'retry-live', 'copy-link', 'source-health', 'string-health',
    'runtime-health', 'peer-health', 'media-health', 'automatic-health',
    'manual-health', 'viewer-count', 'viewer-limit', 'share', 'share-status',
    'join-link', 'stream-qr', 'host-message', 'live-badge',
    'manual-pairing', 'manual-create', 'manual-copy-offer',
    'manual-share-offer', 'manual-import-answer', 'manual-offer',
    'manual-offer-text', 'manual-offer-qr', 'manual-qr-note',
    'manual-answer-text', 'manual-status'
  ];
  const elements = new Map(ids.map(id => [id, new Element(id)]));
  const instance = `instance-${'i'.repeat(24)}`;
  const generation = `generation-${'g'.repeat(24)}`;
  const roomId = Buffer.alloc(16, 3).toString('base64url');
  const roomKey = Buffer.alloc(32, 4).toString('base64url');
  const identity = await hostIdentity(pairing);
  const fingerprint = await pairing.deriveHostFingerprint(
    identity.publicKey,
    generation
  );
  const returnToken = Buffer.alloc(32, 7).toString('base64url');
  const relays = [
    'wss://communities.nos.social',
    'wss://purplerelay.com',
    'wss://bucket.coracle.social',
    'wss://relay.nostr.place',
    'wss://relay.damus.io'
  ];
  const sockets = Object.fromEntries(
    relays.map(url => [url, {readyState: 1}])
  );
  const health = Object.fromEntries(
    relays.map(url => [url, {
      accepted: false,
      delivered: false,
      qualified: false,
      qualifying: false
    }])
  );
  let clock = 1000;
  const intervals = [];
  const timers = [];
  const streamCalls = [];
  const removeCalls = [];
  const telemetryCalls = [];
  const shareCalls = [];
  const rooms = [];
  let cachedRoom = null;
  let pendingLeave = null;
  let joinCount = 0;
  let qualificationCalls = 0;
  let qualifyFirstRelay = null;

  function makeRoom() {
    const peers = {};
    const actions = {};
    const room = {
      peers,
      actions,
      isPassive: () => false,
      makeAction(name) {
        const action = {
          onMessage: null,
          send: async (value, options) => {
            if (name === 'rpp-telemetry-v2') {
              telemetryCalls.push({value, options});
            }
          }
        };
        actions[name] = action;
        return action;
      },
      getPeers: () => peers,
      addStream(stream, options) {
        streamCalls.push({stream, options});
        return [Promise.resolve()];
      },
      removeStream(stream, options) {
        removeCalls.push({stream, options});
      },
      leave() {
        if (!pendingLeave) {
          pendingLeave = {};
          pendingLeave.promise = new Promise(resolve => {
            pendingLeave.resolve = () => {
              cachedRoom = null;
              resolve();
            };
          });
        }
        return pendingLeave.promise;
      }
    };
    rooms.push(room);
    return room;
  }

  let joinConfig = null;
  let joinCallbacks = null;
  const trystero = {
    selfId: 'host-self-identifier',
    getRelaySockets: () => sockets,
    getRelayHealth: () => health,
    qualifyRelays() {
      qualificationCalls += 1;
      for (const relayHealth of Object.values(health)) {
        relayHealth.qualifying = true;
      }
      const pending = new Promise(() => {});
      qualifyFirstRelay = () => {
        health[relays[0]].accepted = true;
        health[relays[0]].delivered = true;
        health[relays[0]].qualified = true;
        health[relays[0]].qualifying = false;
      };
      return pending;
    },
    joinRoom(config, id, callbacks) {
      joinCount += 1;
      assert.equal(id, roomId);
      joinConfig = config;
      joinCallbacks = callbacks;
      cachedRoom ||= makeRoom();
      return cachedRoom;
    }
  };
  const document = {
    pictureInPictureEnabled: false,
    pictureInPictureElement: null,
    getElementById: id => elements.get(id),
    head: {appendChild: () => {}}
  };
  const window = {addEventListener: () => {}};
  const location = {
    hash: `#v=2&instance=${instance}`,
    reloadCalled: false,
    reload() {
      this.reloadCalled = true;
    }
  };
  const context = {
    window,
    document,
    location,
    performance: {now: () => clock},
    crypto: global.crypto,
    TextEncoder,
    TextDecoder,
    URL,
    URLSearchParams,
    Blob,
    Uint8Array,
    DataView,
    atob,
    btoa,
    setInterval: callback => {
      intervals.push(callback);
      return callback;
    },
    clearInterval: () => {},
    setTimeout: (callback, delay) => {
      const timer = {callback, delay};
      timers.push(timer);
      return timer;
    },
    clearTimeout: timer => {
      if (timer) timer.cleared = true;
    },
    createImageBitmap: async () => ({close: () => {}}),
    navigator: {
      clipboard: {writeText: async () => {}},
      share: async value => {
        shareCalls.push(value);
      }
    },
    QRious: class {},
    RppPairing: {
      ...pairing,
      async createManualOffer() {
        return {
          pc: new FakePc(),
          channel: {close: () => {}, readyState: 'connecting'},
          pair: Buffer.alloc(16, 9).toString('base64url'),
          expires: Math.floor(Date.now() / 1000) + 300,
          link: 'https://example.test/watch/v2/#manual-offer',
          qrSafe: false,
          used: false
        };
      }
    },
    RppTrysteroNostr: trystero,
    console
  };
  context.globalThis = context;
  vm.runInNewContext(source, context, {filename: 'HOST_JS'});
  const ingress = window.__RPP_KITE_HOST_V2__;
  assert(ingress);
  const joinUrl =
    `https://example.test/watch/v2/#v=2&room=${roomId}&key=${roomKey}` +
    `&gen=${generation}&pub=${identity.publicKey}&fp=${fingerprint}`;
  const bootstrap = {
    build: 'rpp-kite-host-v2',
    broadcast_desired: true,
    broadcast_sequence: 0,
    frame_rate: 10,
    generation,
    host_fingerprint: fingerprint,
    host_private_jwk: identity.privateJwk,
    host_public_key: identity.publicKey,
    instance,
    join_url: joinUrl,
    manual_callback: {
      origin: 'http://127.0.0.1:45678',
      path: '/pair-return'
    },
    manual_return_page: 'https://example.test/host/v2/return/',
    manual_return_token: returnToken,
    max_hello_bytes: 2048,
    max_negotiating: 4,
    max_telemetry_bytes: 4096,
    max_viewers: 2,
    protocol_version: 2,
    relay_urls: relays,
    room_id: roomId,
    room_key: roomKey,
    rtc_config: {
      iceServers: [
        {urls: 'stun:stun.l.google.com:19302'},
        {
          urls: [
            'turn:us-0.turn.peerjs.com:3478',
            'turn:eu-0.turn.peerjs.com:3478'
          ],
          username: 'peerjs',
          credential: 'peerjsp'
        }
      ]
    },
    signaling: 'nostr',
    telemetry_version: 1
  };
  assert.equal(ingress.bootstrap(bootstrap).ok, true);
  assert.equal(ingress.status().share_ready, false);
  assert.equal(ingress.heartbeat({
    generation,
    instance,
    sequence: 1,
    runtime_state: 'ready',
    source_hash: '',
    source_sequence: 0
  }).ok, true);
  const png = pngFrame();
  const digest = crypto.createHash('sha256').update(png).digest('hex');
  assert.equal((await ingress.frame({
    generation,
    instance,
    sequence: 1,
    png_base64: png.toString('base64'),
    sha256: digest
  })).ok, true);
  await new Promise(resolve => setTimeout(resolve, 25));

  assert.equal(joinCount, 1, JSON.stringify(ingress.status()));
  assert.equal(joinConfig.passive, false);
  assert.equal(joinConfig.password, roomKey);
  assert.equal(joinConfig.trickleIce, true);
  assert.deepEqual(plain(joinConfig.relayConfig.urls), relays);
  assert.equal(typeof joinCallbacks.onPeerHandshake, 'function');
  assert.equal(qualificationCalls, 1);
  assert.equal(ingress.status().relay_health, 'qualifying');
  assert.equal(ingress.status().relay_qualifying_count, relays.length);
  assert.equal(ingress.status().automatic_share_ready, false);
  assert.equal(ingress.status().manual_share_ready, true);
  assert.equal(Object.keys(rooms[0].peers).length, 0);
  qualifyFirstRelay();
  intervals.at(-1)();
  assert.equal(ingress.status().relay_health, 'qualified');
  assert.equal(ingress.status().relay_qualified_count, 1);
  assert.equal(ingress.status().automatic_share_ready, true);
  assert.equal(ingress.status().manual_share_ready, true);
  assert.equal(Object.keys(rooms[0].peers).length, 0);
  await elements.get('manual-create').emit('click');
  await elements.get('manual-share-offer').emit('click');
  assert.deepEqual(JSON.parse(JSON.stringify(shareCalls)), [
    {url: 'https://example.test/watch/v2/#manual-offer'}
  ]);
  const expiredOffer = timers.find(timer => timer.delay > 200000);
  assert(expiredOffer);
  expiredOffer.callback();
  assert.equal(elements.get('manual-offer').hidden, true);
  await elements.get('manual-create').emit('click');
  assert.equal(elements.get('manual-offer').hidden, false);

  const viewerId = 'viewer-self-identifier';
  const nonce = pairing.randomToken(16);
  const hello = await pairing.addViewerProof(roomKey, {
    v: 2,
    type: 'rpp-role',
    role: 'viewer',
    room: roomId,
    generation,
    fingerprint,
    host_public_key: identity.publicKey,
    sender: viewerId,
    target: trystero.selfId,
    nonce,
    expires: Math.floor(Date.now() / 1000) + 30,
    sequence: 1
  });
  let hostProof = null;
  await joinCallbacks.onPeerHandshake(
    viewerId,
    async value => {
      hostProof = value;
    },
    async () => ({data: hello}),
    false
  );
  assert.equal(
    await pairing.verifyHostTranscript(identity.publicKey, hostProof),
    true
  );
  assert.equal(hostProof.viewer_nonce, nonce);

  const room = rooms[0];
  room.peers[viewerId] = new FakePc();
  room.onPeerJoin(viewerId);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(streamCalls.length, 1);
  assert.equal(streamCalls[0].options.target, viewerId);
  assert.equal(streamCalls[0].options.metadata.host_public_key, identity.publicKey);
  assert(telemetryCalls.every(call => call.options.target === viewerId));
  assert.equal(ingress.status().viewer_count, 1);
  assert.equal(ingress.status().media_ready_count, 0);
  room.actions['rpp-media-ready-v2'].onMessage({
    v: 2,
    type: 'media-ready',
    generation,
    fingerprint,
    sender: viewerId,
    target: trystero.selfId
  }, {peerId: viewerId});
  assert.equal(ingress.status().media_ready_count, 1);

  for (const url of relays) {
    sockets[url].readyState = 3;
    health[url].qualified = false;
    health[url].qualifying = false;
  }
  clock += 13000;
  ingress.heartbeat({
    generation,
    instance,
    sequence: 2,
    runtime_state: 'ready',
    source_hash: digest,
    source_sequence: 2
  });
  intervals.at(-1)();
  clock += 13000;
  ingress.heartbeat({
    generation,
    instance,
    sequence: 3,
    runtime_state: 'ready',
    source_hash: digest,
    source_sequence: 3
  });
  intervals.at(-1)();
  assert.equal(ingress.status().relay_health, 'blocked');
  assert.equal(ingress.status().viewer_count, 1);
  assert.equal(room.peers[viewerId].closed, false);
  assert.equal(
    elements.get('host-message').textContent,
    'Automatic signaling blocked; use Manual Share pairing'
  );

  const end = ingress.broadcast({
    generation,
    instance,
    sequence: 1,
    desired: false
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ingress.status().broadcast_desired, false);
  const retry = ingress.broadcast({
    generation,
    instance,
    sequence: 2,
    desired: true
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(
    joinCount,
    1,
    'retry must not rejoin the cache-faithful dying room'
  );
  pendingLeave.resolve();
  await end;
  await retry;
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(joinCount, 2);
  assert.notEqual(rooms[0], rooms[1]);
  assert.equal(location.reloadCalled, false);
  assert.equal(elements.get('manual-offer').hidden, true);

  rooms[1].leave = async () => {
    throw new Error('synthetic leave rejection');
  };
  await elements.get('retry-live').emit('click');
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(location.reloadCalled, true);
  assert.equal(
    joinCount,
    2,
    'a rejected leave must reset the page rather than reuse the dead singleton'
  );

  process.stdout.write('nostr host contracts passed\n');
}
