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
  process.exitCode = 1;
}));

class FakeChannel {
  constructor(label) {
    this.label = label;
    this.readyState = 'connecting';
    this.bufferedAmount = 0;
    this.listeners = new Map();
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  close() {
    this.readyState = 'closed';
  }
}

class FakePeerConnection {
  constructor(config) {
    assert.deepEqual(config, {
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
    });
    this.iceGatheringState = 'complete';
    this.connectionState = 'new';
    this.iceConnectionState = 'new';
    this.localDescription = null;
    this.remoteDescription = null;
    this.listeners = new Map();
    this.channels = [];
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  removeEventListener() {}

  createDataChannel(label) {
    const channel = new FakeChannel(label);
    this.channels.push(channel);
    return channel;
  }

  addTrack() {}

  async createOffer() {
    return {
      type: 'offer',
      sdp: 'v=0\r\na=candidate:1 1 UDP 1 192.0.2.1 10000 typ host\r\n'
    };
  }

  async createAnswer() {
    return {
      type: 'answer',
      sdp: 'v=0\r\na=candidate:2 1 UDP 1 198.51.100.1 10001 typ srflx\r\n'
    };
  }

  async setLocalDescription(description) {
    this.localDescription = description;
  }

  async setRemoteDescription(description) {
    this.remoteDescription = description;
  }

  close() {
    this.connectionState = 'closed';
  }
}

const stream = {
  getTracks: () => [{kind: 'video'}]
};

function factory(connections) {
  return config => {
    const pc = new FakePeerConnection(config);
    connections.push(pc);
    return pc;
  };
}

async function identity(api) {
  const keys = await crypto.subtle.generateKey(
    {name: 'ECDSA', namedCurve: 'P-256'},
    true,
    ['sign', 'verify']
  );
  const exportedPublic = await crypto.subtle.exportKey('jwk', keys.publicKey);
  const exportedPrivate = await crypto.subtle.exportKey('jwk', keys.privateKey);
  const publicJwk = {
    crv: 'P-256',
    ext: true,
    key_ops: ['verify'],
    kty: 'EC',
    x: exportedPublic.x,
    y: exportedPublic.y
  };
  const privateJwk = {
    crv: 'P-256',
    d: exportedPrivate.d,
    ext: true,
    key_ops: ['sign'],
    kty: 'EC',
    x: exportedPrivate.x,
    y: exportedPrivate.y
  };
  return {
    publicJwk,
    privateJwk,
    publicKey: api.publicKeyToken(publicJwk)
  };
}

async function makePair(api, now = 1_800_000_000) {
  const hostConnections = [];
  const viewerConnections = [];
  const room = api.randomToken(16);
  const key = api.randomToken(32);
  const generation = api.randomToken(24);
  const hostIdentity = await identity(api);
  const fingerprint = await api.deriveHostFingerprint(
    hostIdentity.publicKey,
    generation
  );
  const callback = {
    origin: 'http://127.0.0.1:45678',
    path: '/pair-return'
  };
  const returnToken = api.randomToken(32);
  const pending = await api.createManualOffer({
    stream,
    room,
    key,
    generation,
    fingerprint,
    hostPublicKey: hostIdentity.publicKey,
    hostPrivateJwk: hostIdentity.privateJwk,
    callback,
    returnToken,
    returnPage: 'https://example.test/host/v2/return/',
    joinBase: 'https://example.test/watch/v2/',
    now,
    peerConnectionFactory: factory(hostConnections)
  });
  const capability = await api.parseManualOfferFragment(
    new URL(pending.link).hash,
    now
  );
  const result = await api.createManualAnswer({
    capability,
    onStream: () => {},
    onChannel: () => {},
    now,
    peerConnectionFactory: factory(viewerConnections)
  });
  return {
    room,
    key,
    generation,
    hostIdentity,
    fingerprint,
    callback,
    returnToken,
    pending,
    capability,
    result,
    hostConnections,
    viewerConnections
  };
}

async function run() {
  vm.runInThisContext(source, {filename: 'PAIRING_JS'});
  const api = global.RppPairing;
  assert(api);
  assert.deepEqual(api.cloneRtcConfig(), {
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
  });
  assert(source.includes('turn:us-0.turn.peerjs.com:3478'));
  assert(source.includes('turn:eu-0.turn.peerjs.com:3478'));
  assert(!source.includes('turns:'));
  assert(!source.includes('WebSocket'));
  assert(!source.includes('fetch('));
  assert(!source.includes("new CompressionStream('gzip')"));

  const hostIdentity = await identity(api);
  const generation = `generation-${'g'.repeat(24)}`;
  const fingerprint = await api.deriveHostFingerprint(
    hostIdentity.publicKey,
    generation
  );
  assert.match(fingerprint, /^[a-f0-9]{32}$/);
  const transcript = {
    v: 2,
    type: 'rpp-role',
    role: 'host',
    generation,
    nonce: api.randomToken(16)
  };
  const signed = await api.signHostTranscript(
    hostIdentity.privateJwk,
    transcript
  );
  assert.equal(
    await api.verifyHostTranscript(hostIdentity.publicKey, signed),
    true
  );
  assert.equal(
    await api.verifyHostTranscript(
      hostIdentity.publicKey,
      {...signed, nonce: api.randomToken(16)}
    ),
    false
  );

  const roomKey = api.randomToken(32);
  const forgedWithSharedKey = await api.addViewerProof(roomKey, transcript);
  assert.equal(
    await api.verifyHostTranscript(hostIdentity.publicKey, forgedWithSharedKey),
    false,
    'a viewer possessing the room key cannot forge the host signature'
  );

  const bytes = new TextEncoder().encode('same-wire-format');
  const originalCompression = global.CompressionStream;
  global.CompressionStream = function availableButUnused() {};
  const capable = await api.compressBytes(bytes);
  global.CompressionStream = undefined;
  const incapable = await api.compressBytes(bytes);
  global.CompressionStream = originalCompression;
  assert.equal(capable.compression, 'none');
  assert.equal(incapable.compression, 'none');
  assert.deepEqual(capable.bytes, incapable.bytes);
  assert.deepEqual(
    await api.decompressBytes(capable.bytes, 'none', bytes.byteLength),
    bytes
  );
  await assert.rejects(
    api.decompressBytes(bytes, 'gzip', bytes.byteLength),
    /unsupported/
  );

  let websocketCalls = 0;
  let fetchCalls = 0;
  const originalWebSocket = global.WebSocket;
  const originalFetch = global.fetch;
  global.WebSocket = function forbiddenWebSocket() {
    websocketCalls += 1;
  };
  global.fetch = async () => {
    fetchCalls += 1;
  };
  const first = await makePair(api);
  global.WebSocket = originalWebSocket;
  global.fetch = originalFetch;
  assert.equal(websocketCalls, 0);
  assert.equal(fetchCalls, 0);
  assert.equal(new URL(first.pending.link).search, '');
  assert.equal(new URL(first.result.returnLink).search, '');
  assert.equal(
    new URL(first.result.returnLink).origin +
      new URL(first.result.returnLink).pathname,
    'https://example.test/host/v2/return/'
  );
  const returnParams = new URL(first.result.returnLink).hash.slice(1);
  const parsedReturn = new URLSearchParams(returnParams);
  assert.deepEqual([...parsedReturn.keys()].sort(), [
    'answer', 'cb', 'gen', 'mode', 'rt', 'v'
  ]);
  assert.equal(parsedReturn.get('answer'), first.result.text);
  assert.equal(parsedReturn.get('rt'), first.returnToken);
  assert.deepEqual(
    api.parseCallbackToken(parsedReturn.get('cb')),
    first.callback
  );
  assert.equal(first.pending.offer.signature.length, 86);
  assert.equal(first.pending.offer.expires - first.pending.offer.created, 300);
  assert.equal(first.pending.offer.sdp.includes('typ host'), true);
  assert.equal(first.result.answer.sdp.includes('typ srflx'), true);

  await api.acceptManualAnswer(
    first.pending,
    first.result.text,
    first.pending.offer.created
  );
  assert.equal(first.pending.used, true);
  await assert.rejects(
    api.acceptManualAnswer(
      first.pending,
      first.result.text,
      first.pending.offer.created
    ),
    /already used/
  );

  const forgedOffer = await makePair(api);
  const url = new URL(forgedOffer.pending.link);
  const params = new URLSearchParams(url.hash.slice(1));
  const offerBytes = api.base64UrlToBytes(params.get('offer'));
  const offer = JSON.parse(new TextDecoder().decode(offerBytes));
  offer.sdp += 'a=x-forged\r\n';
  params.set(
    'offer',
    api.bytesToBase64Url(
      new TextEncoder().encode(api.canonicalJson(offer))
    )
  );
  await assert.rejects(
    api.parseManualOfferFragment(`#${params}`, forgedOffer.pending.offer.created),
    /signature|binding/
  );

  const tampered = await makePair(api);
  const decoded = api.decodeAnswerEnvelope(tampered.result.text);
  const ciphertext = new Uint8Array(decoded.ciphertext);
  ciphertext[0] ^= 1;
  const changed = {
    ...decoded.envelope,
    ciphertext: api.bytesToBase64Url(ciphertext)
  };
  const changedText = api.ANSWER_PREFIX + api.bytesToBase64Url(
    new TextEncoder().encode(api.canonicalJson(changed))
  );
  await assert.rejects(
    api.acceptManualAnswer(
      tampered.pending,
      changedText,
      tampered.pending.offer.created
    ),
    /authentication failed/
  );
  assert.equal(tampered.pending.used, false);

  const expired = await makePair(api);
  await assert.rejects(
    api.acceptManualAnswer(
      expired.pending,
      expired.result.text,
      expired.pending.expires + 1
    ),
    /expired/
  );
  assert.equal(expired.pending.used, true);

  const sdpFailure = await makePair(api);
  sdpFailure.pending.pc.setRemoteDescription = async () => {
    throw new Error('synthetic SDP failure');
  };
  await assert.rejects(
    api.acceptManualAnswer(
      sdpFailure.pending,
      sdpFailure.result.text,
      sdpFailure.pending.offer.created
    ),
    /could not be applied/
  );
  assert.equal(sdpFailure.pending.used, true);
  assert.equal(sdpFailure.pending.pc.connectionState, 'closed');

  const sequential = await makePair(api);
  await api.acceptManualAnswer(
    sequential.pending,
    sequential.result.text,
    sequential.pending.offer.created
  );
  assert.equal(sequential.pending.used, true);

  api.assertDirectSdp(
    'v=0\r\na=candidate:3 1 UDP 1 203.0.113.1 10002 typ relay\r\n'
  );
  assert.deepEqual(
    api.candidateTypesFromSdp(
      'v=0\r\na=candidate:3 1 UDP 1 203.0.113.1 10002 typ relay\r\n'
    ),
    ['relay']
  );
  assert.equal(api.safeForQr('x'.repeat(api.QR_CAPACITY_BYTES)), true);
  assert.equal(api.safeForQr('x'.repeat(api.QR_CAPACITY_BYTES + 1)), false);

  process.stdout.write('manual pairing contracts passed\n');
}
