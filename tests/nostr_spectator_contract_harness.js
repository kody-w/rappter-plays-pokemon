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
    this.hidden = false;
    this.disabled = false;
    this.textContent = '';
    this.className = '';
    this.value = '';
    this.srcObject = null;
    this.readyState = 0;
    this.dataset = {};
    this.children = [];
    this.listeners = new Map();
    this.classList = {
      add: () => {},
      remove: () => {},
      toggle: () => {}
    };
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  replaceChildren() {
    this.children = [];
  }

  appendChild(child) {
    this.children.push(child);
  }

  setAttribute() {}
  focus() {}
}

class FakePc {
  constructor() {
    this.connectionState = 'connected';
    this.iceConnectionState = 'connected';
    this.closed = false;
    this.listeners = new Map();
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

async function identity(pairing) {
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
  return {
    publicKey: pairing.publicKeyToken(publicJwk),
    privateJwk: {
      crv: 'P-256',
      d: priv.d,
      ext: true,
      key_ops: ['sign'],
      kty: 'EC',
      x: priv.x,
      y: priv.y
    }
  };
}

async function run() {
  require('../docs/watch/v2/pairing.rpp-v2.js');
  const pairing = global.RppPairing;
  const roomId = Buffer.alloc(16, 5).toString('base64url');
  const roomKey = Buffer.alloc(32, 6).toString('base64url');
  const generation = `generation-${'s'.repeat(24)}`;
  const hostIdentity = await identity(pairing);
  const fingerprint = await pairing.deriveHostFingerprint(
    hostIdentity.publicKey,
    generation
  );
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
    relays.map(url => [url, {qualified: true}])
  );
  const peers = {};
  const actions = {};
  let joinConfig = null;
  let joinCallbacks = null;
  let joinCount = 0;
  let leaveResolve = null;
  const room = {
    isPassive: () => true,
    getPeers: () => peers,
    makeAction(name) {
      const action = {
        onMessage: null,
        sent: [],
        async send(value, options) {
          this.sent.push({value, options});
        }
      };
      actions[name] = action;
      return action;
    },
    leave() {
      return new Promise(resolve => {
        leaveResolve = resolve;
      });
    }
  };
  const trystero = {
    selfId: 'viewer-self-identifier',
    getRelaySockets: () => sockets,
    getRelayHealth: () => health,
    joinRoom(config, joinedRoom, callbacks) {
      joinCount += 1;
      assert.equal(joinedRoom, roomId);
      joinConfig = config;
      joinCallbacks = callbacks;
      return room;
    }
  };
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  const badges = [
    'Boulder', 'Cascade', 'Thunder', 'Rainbow',
    'Soul', 'Marsh', 'Volcano', 'Earth'
  ].map(name => {
    const badge = new Element(`badge-${name}`);
    badge.dataset.badge = name;
    return badge;
  });
  const video = element('stream');
  video.readyState = 3;
  video.paused = false;
  video.currentTime = 0;
  video.play = async () => {};
  const intervals = [];
  const timers = [];
  let clock = 0;
  let clearedAddress = null;
  let replacedAddress = null;
  const location = {
    hash:
      `#v=2&room=${roomId}&key=${roomKey}&gen=${generation}` +
      `&pub=${hostIdentity.publicKey}&fp=${fingerprint}`,
    pathname: '/watch/v2/',
    replace(value) {
      replacedAddress = value;
    }
  };
  const context = {
    document: {
      getElementById: element,
      querySelectorAll: selector => selector === '[data-badge]' ? badges : [],
      createElement: name => new Element(name),
      head: {appendChild: () => {}}
    },
    window: {addEventListener: () => {}},
    location,
    history: {
      replaceState: (_state, _title, value) => {
        clearedAddress = value;
      }
    },
    performance: {now: () => clock},
    crypto: global.crypto,
    TextEncoder,
    TextDecoder,
    URL,
    URLSearchParams,
    Blob,
    Uint8Array,
    atob,
    btoa,
    setInterval: callback => {
      intervals.push(callback);
      return callback;
    },
    clearInterval: () => {},
    setTimeout: (callback, delay) => {
      const timer = {callback, delay, cleared: false};
      timers.push(timer);
      return timer;
    },
    clearTimeout: timer => {
      if (timer) timer.cleared = true;
    },
    navigator: {
      clipboard: {writeText: async () => {}},
      share: async () => {}
    },
    QRious: class {},
    RppPairing: pairing,
    RppTrysteroNostr: trystero,
    console
  };
  context.globalThis = context;
  vm.runInNewContext(source, context, {filename: 'SPECTATOR_JS'});
  await new Promise(resolve => setTimeout(resolve, 25));

  assert.equal(clearedAddress, '/watch/v2/');
  assert.equal(joinCount, 1);
  assert.equal(joinConfig.passive, true);
  assert.equal(joinConfig.password, roomKey);
  assert.equal(joinConfig.trickleIce, true);
  assert.deepEqual(
    JSON.parse(JSON.stringify(joinConfig.relayConfig.urls)),
    relays
  );

  const hostId = 'host-self-identifier';
  let viewerHello = null;
  await joinCallbacks.onPeerHandshake(
    hostId,
    async value => {
      viewerHello = value;
    },
    async () => {
      assert(viewerHello);
      return {
        data: await pairing.signHostTranscript(hostIdentity.privateJwk, {
          v: 2,
          type: 'rpp-role',
          role: 'host',
          room: roomId,
          generation,
          fingerprint,
          host_public_key: hostIdentity.publicKey,
          sender: hostId,
          target: trystero.selfId,
          viewer_nonce: viewerHello.nonce,
          host_nonce: pairing.randomToken(16),
          expires: Math.floor(Date.now() / 1000) + 30,
          sequence: 1
        })
      };
    },
    false
  );
  assert.equal(await pairing.verifyViewerProof(roomKey, viewerHello), true);

  const media = {
    getTracks: () => [{
      readyState: 'live',
      addEventListener: () => {}
    }],
    getVideoTracks: () => [{
      readyState: 'live',
      addEventListener: () => {}
    }]
  };
  room.onPeerStream(media, hostId, {
    v: 2,
    role: 'host',
    generation,
    fingerprint,
    host_public_key: hostIdentity.publicKey
  });
  assert.equal(
    video.srcObject,
    null,
    'a verified pending host is not promoted before onPeerJoin'
  );

  peers[hostId] = new FakePc();
  room.onPeerJoin(hostId);
  room.onPeerStream(media, hostId, {
    v: 2,
    role: 'host',
    generation,
    fingerprint,
    host_public_key: hostIdentity.publicKey
  });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(video.srcObject, media);
  assert.equal(actions['rpp-media-ready-v2'].sent.length, 1);
  assert.equal(
    actions['rpp-media-ready-v2'].sent[0].options.target,
    hostId
  );

  const wrongId = 'second-host-identifier';
  peers[wrongId] = new FakePc();
  room.onPeerJoin(wrongId);
  assert.equal(peers[wrongId].closed, true);

  for (const url of relays) {
    sockets[url].readyState = 3;
    health[url].qualified = false;
  }
  clock = 13000;
  for (const interval of intervals) interval();
  assert.equal(video.srcObject, media);
  assert.equal(peers[hostId].closed, false);

  const forged = await pairing.addViewerProof(roomKey, {
    v: 2,
    type: 'rpp-role',
    role: 'host',
    room: roomId,
    generation,
    fingerprint,
    host_public_key: hostIdentity.publicKey,
    sender: 'attacker-identifier',
    target: trystero.selfId,
    viewer_nonce: pairing.randomToken(16),
    host_nonce: pairing.randomToken(16),
    expires: Math.floor(Date.now() / 1000) + 30,
    sequence: 1
  });
  await assert.rejects(
    joinCallbacks.onPeerHandshake(
      'attacker-identifier',
      async () => {},
      async () => ({data: forged}),
      false
    ),
    /pinned|proof/
  );

  room.onPeerLeave(hostId);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(joinCount, 1);
  assert(leaveResolve, 'retry cleanup must await room.leave');
  assert.equal(
    timers.some(timer =>
      !timer.cleared && timer.delay >= 750 && timer.delay <= 10000
    ),
    false,
    'retry timer must not start while the cached room is dying'
  );
  leaveResolve();
  await new Promise(resolve => setImmediate(resolve));
  const retryTimer = timers.find(timer =>
    !timer.cleared && timer.delay >= 750 && timer.delay <= 10000
  );
  assert(retryTimer);
  retryTimer.callback();
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(joinCount, 2);
  assert.equal(replacedAddress, null);

  process.stdout.write('nostr spectator contracts passed\n');
}
