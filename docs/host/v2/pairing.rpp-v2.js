(() => {
'use strict';

const VERSION = 2;
const OFFER_TTL_SECONDS = 300;
const MAX_SDP_BYTES = 128 * 1024;
const MAX_DECOMPRESSED_BYTES = 192 * 1024;
const MAX_ENCODED_BYTES = 512 * 1024;
const MAX_ANSWER_TEXT_BYTES = 384 * 1024;
const QR_CAPACITY_BYTES = 2200;
const ANSWER_PREFIX = 'rpp-answer-v2.';
const RTC_CONFIG = Object.freeze({
  iceServers: Object.freeze([
    Object.freeze({urls: 'stun:stun.l.google.com:19302'}),
    Object.freeze({
      urls: Object.freeze([
        'turn:us-0.turn.peerjs.com:3478',
        'turn:eu-0.turn.peerjs.com:3478'
      ]),
      username: 'peerjs',
      credential: 'peerjsp'
    })
  ])
});
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', {fatal: true});

function exactKeys(value, keys) {
  return Boolean(
    value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join(',') === [...keys].sort().join(',')
  );
}

function byteLength(value) {
  return encoder.encode(value).byteLength;
}

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

function concatBytes(...parts) {
  const length = parts.reduce((total, part) => total + part.byteLength, 0);
  const joined = new Uint8Array(length);
  let offset = 0;
  for (const part of parts) {
    joined.set(part, offset);
    offset += part.byteLength;
  }
  return joined;
}

function bytesToBase64Url(bytes) {
  let binary = '';
  for (let offset = 0; offset < bytes.byteLength; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary)
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replace(/=+$/, '');
}

function base64UrlToBytes(value, maximum = MAX_ENCODED_BYTES) {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > maximum ||
    !/^[A-Za-z0-9_-]+$/.test(value)
  ) {
    throw new Error('invalid base64url value');
  }
  const padding = '='.repeat((4 - value.length % 4) % 4);
  let binary;
  try {
    binary = atob(value.replaceAll('-', '+').replaceAll('_', '/') + padding);
  } catch (_error) {
    throw new Error('invalid base64url value');
  }
  const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
  if (bytesToBase64Url(bytes) !== value) {
    throw new Error('non-canonical base64url value');
  }
  return bytes;
}

function tokenBytes(value, length, name) {
  let bytes;
  try {
    bytes = base64UrlToBytes(value, 1024);
  } catch (_error) {
    throw new Error(`invalid ${name}`);
  }
  if (bytes.byteLength !== length) throw new Error(`invalid ${name}`);
  return bytes;
}

function randomToken(length) {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return bytesToBase64Url(bytes);
}

function canonicalJson(value) {
  const visit = item => {
    if (
      item === null ||
      typeof item === 'string' ||
      typeof item === 'boolean'
    ) return JSON.stringify(item);
    if (typeof item === 'number' && Number.isFinite(item)) {
      return JSON.stringify(item);
    }
    if (Array.isArray(item)) return `[${item.map(visit).join(',')}]`;
    if (item && typeof item === 'object') {
      return `{${Object.keys(item).sort().map(
        key => `${JSON.stringify(key)}:${visit(item[key])}`
      ).join(',')}}`;
    }
    throw new Error('value is not canonical JSON');
  };
  return visit(value);
}

function bytesToHex(bytes) {
  return Array.from(
    bytes,
    value => value.toString(16).padStart(2, '0')
  ).join('');
}

function hexToBytes(value, length) {
  if (
    typeof value !== 'string' ||
    value.length !== length * 2 ||
    !/^[a-f0-9]+$/.test(value)
  ) throw new Error('invalid hexadecimal value');
  return Uint8Array.from(
    value.match(/../g),
    pair => Number.parseInt(pair, 16)
  );
}

async function sha256Bytes(bytes) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
}

async function sha256Hex(bytes) {
  return bytesToHex(await sha256Bytes(bytes));
}

function validPublicJwk(value) {
  if (!exactKeys(value, ['crv', 'ext', 'key_ops', 'kty', 'x', 'y'])) {
    return false;
  }
  if (
    value.kty !== 'EC' ||
    value.crv !== 'P-256' ||
    value.ext !== true ||
    !Array.isArray(value.key_ops) ||
    value.key_ops.length !== 1 ||
    value.key_ops[0] !== 'verify'
  ) return false;
  try {
    tokenBytes(value.x, 32, 'host public key x');
    tokenBytes(value.y, 32, 'host public key y');
  } catch (_error) {
    return false;
  }
  return true;
}

function validPrivateJwk(value) {
  if (!exactKeys(
    value,
    ['crv', 'd', 'ext', 'key_ops', 'kty', 'x', 'y']
  )) return false;
  if (
    value.kty !== 'EC' ||
    value.crv !== 'P-256' ||
    value.ext !== true ||
    !Array.isArray(value.key_ops) ||
    value.key_ops.length !== 1 ||
    value.key_ops[0] !== 'sign'
  ) return false;
  try {
    tokenBytes(value.x, 32, 'host private key x');
    tokenBytes(value.y, 32, 'host private key y');
    tokenBytes(value.d, 32, 'host private key scalar');
  } catch (_error) {
    return false;
  }
  return true;
}

function publicJwkFromPrivate(value) {
  if (!validPrivateJwk(value)) throw new Error('invalid host private key');
  return {
    crv: 'P-256',
    ext: true,
    key_ops: ['verify'],
    kty: 'EC',
    x: value.x,
    y: value.y
  };
}

function publicKeyToken(value) {
  if (!validPublicJwk(value)) throw new Error('invalid host public key');
  return bytesToBase64Url(encoder.encode(canonicalJson(value)));
}

function parsePublicKeyToken(value) {
  let parsed;
  try {
    const serialized = decoder.decode(base64UrlToBytes(value, 1024));
    parsed = JSON.parse(serialized);
    if (canonicalJson(parsed) !== serialized || !validPublicJwk(parsed)) {
      throw new Error('invalid public key');
    }
  } catch (_error) {
    throw new Error('invalid host public key');
  }
  return parsed;
}

async function deriveHostFingerprint(hostPublicKey, generation) {
  if (!/^[A-Za-z0-9_-]{16,128}$/.test(generation || '')) {
    throw new Error('invalid generation');
  }
  const jwk = parsePublicKeyToken(hostPublicKey);
  const digest = await sha256Bytes(encoder.encode(
    `rpp-host-signing-v2\0${generation}\0${canonicalJson(jwk)}`
  ));
  return bytesToHex(digest.subarray(0, 16));
}

async function signHostTranscript(privateJwk, payload) {
  if (!validPrivateJwk(privateJwk)) throw new Error('invalid host private key');
  if (payload && Object.hasOwn(payload, 'signature')) {
    throw new Error('host transcript already has a signature');
  }
  const material = await crypto.subtle.importKey(
    'jwk',
    privateJwk,
    {name: 'ECDSA', namedCurve: 'P-256'},
    false,
    ['sign']
  );
  const signature = await crypto.subtle.sign(
    {name: 'ECDSA', hash: 'SHA-256'},
    material,
    encoder.encode(canonicalJson(payload))
  );
  return {...payload, signature: bytesToBase64Url(new Uint8Array(signature))};
}

async function verifyHostTranscript(hostPublicKey, value) {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    typeof value.signature !== 'string'
  ) return false;
  let signature;
  let material;
  try {
    signature = base64UrlToBytes(value.signature, 256);
    if (signature.byteLength !== 64) return false;
    material = await crypto.subtle.importKey(
      'jwk',
      parsePublicKeyToken(hostPublicKey),
      {name: 'ECDSA', namedCurve: 'P-256'},
      false,
      ['verify']
    );
  } catch (_error) {
    return false;
  }
  const payload = {...value};
  delete payload.signature;
  return crypto.subtle.verify(
    {name: 'ECDSA', hash: 'SHA-256'},
    material,
    signature,
    encoder.encode(canonicalJson(payload))
  );
}

async function verifyPrivateKeyBinding(privateJwk, hostPublicKey) {
  if (!validPrivateJwk(privateJwk)) return false;
  try {
    return publicKeyToken(publicJwkFromPrivate(privateJwk)) === hostPublicKey;
  } catch (_error) {
    return false;
  }
}

async function addViewerProof(key, payload) {
  const material = await crypto.subtle.importKey(
    'raw',
    tokenBytes(key, 32, 'room key'),
    {name: 'HMAC', hash: 'SHA-256'},
    false,
    ['sign']
  );
  const proof = await crypto.subtle.sign(
    'HMAC',
    material,
    encoder.encode(canonicalJson(payload))
  );
  return {...payload, proof: bytesToHex(new Uint8Array(proof))};
}

async function verifyViewerProof(key, value) {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    !/^[a-f0-9]{64}$/.test(value.proof || '')
  ) return false;
  const payload = {...value};
  delete payload.proof;
  let material;
  try {
    material = await crypto.subtle.importKey(
      'raw',
      tokenBytes(key, 32, 'room key'),
      {name: 'HMAC', hash: 'SHA-256'},
      false,
      ['verify']
    );
  } catch (_error) {
    return false;
  }
  return crypto.subtle.verify(
    'HMAC',
    material,
    hexToBytes(value.proof, 32),
    encoder.encode(canonicalJson(payload))
  );
}

function parseAutoFragment(fragment) {
  const params = new URLSearchParams(String(fragment || '').replace(/^#/, ''));
  if (
    [...params.keys()].sort().join(',') !==
      'fp,gen,key,pub,room,v'
  ) return null;
  const room = params.get('room') || '';
  const key = params.get('key') || '';
  const generation = params.get('gen') || '';
  const hostPublicKey = params.get('pub') || '';
  const fingerprint = params.get('fp') || '';
  try {
    tokenBytes(room, 16, 'room');
    tokenBytes(key, 32, 'room key');
    parsePublicKeyToken(hostPublicKey);
  } catch (_error) {
    return null;
  }
  if (
    params.get('v') !== String(VERSION) ||
    !/^[A-Za-z0-9_-]{16,128}$/.test(generation) ||
    !/^[a-f0-9]{32}$/.test(fingerprint)
  ) return null;
  return {
    version: VERSION,
    mode: 'nostr',
    room,
    key,
    generation,
    hostPublicKey,
    fingerprint
  };
}

function cloneRtcConfig() {
  return {
    iceServers: RTC_CONFIG.iceServers.map(server => ({
      ...server,
      urls: Array.isArray(server.urls) ? [...server.urls] : server.urls
    }))
  };
}

function candidateTypesFromSdp(sdp) {
  const types = new Set();
  for (const line of String(sdp || '').split(/\r?\n/)) {
    if (!/^a=candidate:/i.test(line)) continue;
    const match = line.match(/\btyp\s+(host|srflx|prflx|relay)\b/i);
    if (match) types.add(match[1].toLowerCase());
  }
  return [...types].sort();
}

function assertDirectSdp(sdp) {
  if (byteLength(String(sdp || '')) > MAX_SDP_BYTES) {
    throw new Error('SDP exceeds the manual pairing limit');
  }
}

async function selectedCandidateType(pc) {
  if (!pc || typeof pc.getStats !== 'function') return 'unknown';
  const stats = await pc.getStats();
  let selected = null;
  stats.forEach(report => {
    if (
      report.type === 'candidate-pair' &&
      (report.selected || (report.nominated && report.state === 'succeeded'))
    ) selected = report;
  });
  if (!selected && pc.sctp && pc.sctp.transport && pc.sctp.transport.iceTransport) {
    const pair = pc.sctp.transport.iceTransport.getSelectedCandidatePair();
    if (pair && pair.local) return pair.local.type || 'unknown';
  }
  if (!selected) return 'unknown';
  const local = stats.get(selected.localCandidateId);
  return local && typeof local.candidateType === 'string'
    ? local.candidateType
    : 'unknown';
}

function waitForIceComplete(pc, timeoutMilliseconds = 15000) {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve, reject) => {
    const changed = () => {
      if (pc.iceGatheringState !== 'complete') return;
      cleanup();
      resolve();
    };
    const timeout = setTimeout(() => {
      cleanup();
      reject(new Error('complete ICE gathering timed out'));
    }, timeoutMilliseconds);
    const cleanup = () => {
      clearTimeout(timeout);
      pc.removeEventListener('icegatheringstatechange', changed);
    };
    pc.addEventListener('icegatheringstatechange', changed);
    changed();
  });
}

async function compressBytes(bytes) {
  if (!(bytes instanceof Uint8Array) || bytes.byteLength > MAX_DECOMPRESSED_BYTES) {
    throw new Error('uncompressed pairing payload is too large');
  }
  return {compression: 'none', bytes};
}

async function decompressBytes(bytes, compression, maximum) {
  if (compression !== 'none') {
    throw new Error('unsupported pairing compression');
  }
  if (!(bytes instanceof Uint8Array) || bytes.byteLength > maximum) {
    throw new Error('pairing payload is too large');
  }
  return bytes;
}

function safeForQr(value) {
  return typeof value === 'string' && byteLength(value) <= QR_CAPACITY_BYTES;
}

function normalizeHttpsBase(base, purpose) {
  const url = new URL(base);
  if (
    url.protocol !== 'https:' ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) throw new Error(`${purpose} must be an uncredentialed HTTPS URL`);
  if (!url.pathname.endsWith('/')) url.pathname += '/';
  return url.toString();
}

function validateCallback(value) {
  if (!exactKeys(value, ['origin', 'path'])) return false;
  let url;
  try {
    url = new URL(value.origin);
  } catch (_error) {
    return false;
  }
  return Boolean(
    url.protocol === 'http:' &&
    url.hostname === '127.0.0.1' &&
    /^[1-9]\d{0,4}$/.test(url.port) &&
    Number(url.port) <= 65535 &&
    url.pathname === '/' &&
    !url.search &&
    !url.hash &&
    !url.username &&
    !url.password &&
    url.origin === value.origin &&
    value.path === '/pair-return'
  );
}

function callbackToken(value) {
  if (!validateCallback(value)) throw new Error('invalid manual callback');
  return bytesToBase64Url(encoder.encode(canonicalJson(value)));
}

function parseCallbackToken(value) {
  let callback;
  try {
    const serialized = decoder.decode(base64UrlToBytes(value, 1024));
    callback = JSON.parse(serialized);
    if (
      canonicalJson(callback) !== serialized ||
      !validateCallback(callback)
    ) throw new Error('invalid callback');
  } catch (_error) {
    throw new Error('invalid manual callback');
  }
  return callback;
}

function validateManualOffer(value, now = nowSeconds()) {
  if (
    !exactKeys(value, [
      'callback', 'created', 'expires', 'fingerprint', 'generation',
      'host_public_key', 'pair', 'return_page', 'return_token', 'room',
      'sdp', 'signature', 'type', 'v'
    ]) ||
    value.v !== VERSION ||
    value.type !== 'rpp-manual-offer' ||
    !Number.isSafeInteger(value.created) ||
    !Number.isSafeInteger(value.expires) ||
    value.expires - value.created !== OFFER_TTL_SECONDS ||
    value.created > now + 30 ||
    value.expires < now ||
    value.expires > now + OFFER_TTL_SECONDS + 30 ||
    !/^[A-Za-z0-9_-]{16,128}$/.test(value.generation || '') ||
    !/^[a-f0-9]{32}$/.test(value.fingerprint || '') ||
    typeof value.sdp !== 'string' ||
    !validateCallback(value.callback)
  ) return false;
  try {
    tokenBytes(value.room, 16, 'room');
    tokenBytes(value.pair, 16, 'pair');
    tokenBytes(value.return_token, 32, 'manual return token');
    parsePublicKeyToken(value.host_public_key);
    normalizeHttpsBase(value.return_page, 'manual return page');
    assertDirectSdp(value.sdp);
    if (!new URL(value.return_page).pathname.endsWith('/return/')) return false;
  } catch (_error) {
    return false;
  }
  return true;
}

async function parseManualOfferFragment(fragment, now = nowSeconds()) {
  const params = new URLSearchParams(String(fragment || '').replace(/^#/, ''));
  if (
    [...params.keys()].sort().join(',') !==
      'cb,exp,fp,gen,key,mode,offer,pair,pub,ret,room,rt,v,zip'
  ) throw new Error('manual invitation schema is invalid');
  if (
    params.get('v') !== String(VERSION) ||
    params.get('mode') !== 'manual-offer' ||
    params.get('zip') !== 'none'
  ) throw new Error('manual invitation version is invalid');
  const outer = {
    room: params.get('room') || '',
    key: params.get('key') || '',
    generation: params.get('gen') || '',
    fingerprint: params.get('fp') || '',
    hostPublicKey: params.get('pub') || '',
    pair: params.get('pair') || '',
    expires: Number(params.get('exp')),
    callback: parseCallbackToken(params.get('cb') || ''),
    returnToken: params.get('rt') || '',
    returnPage: params.get('ret') || ''
  };
  tokenBytes(outer.room, 16, 'room');
  tokenBytes(outer.key, 32, 'room key');
  tokenBytes(outer.pair, 16, 'pair');
  tokenBytes(outer.returnToken, 32, 'manual return token');
  parsePublicKeyToken(outer.hostPublicKey);
  if (
    !/^[A-Za-z0-9_-]{16,128}$/.test(outer.generation) ||
    !/^[a-f0-9]{32}$/.test(outer.fingerprint) ||
    !Number.isSafeInteger(outer.expires) ||
    outer.expires < now ||
    outer.expires > now + OFFER_TTL_SECONDS + 30
  ) throw new Error('manual invitation values are invalid');
  const plain = await decompressBytes(
    base64UrlToBytes(params.get('offer') || '', MAX_ENCODED_BYTES),
    'none',
    MAX_DECOMPRESSED_BYTES
  );
  let offer;
  try {
    const serialized = decoder.decode(plain);
    offer = JSON.parse(serialized);
    if (canonicalJson(offer) !== serialized) throw new Error('non-canonical');
  } catch (_error) {
    throw new Error('manual offer payload is invalid');
  }
  if (
    !validateManualOffer(offer, now) ||
    offer.room !== outer.room ||
    offer.generation !== outer.generation ||
    offer.fingerprint !== outer.fingerprint ||
    offer.host_public_key !== outer.hostPublicKey ||
    offer.pair !== outer.pair ||
    offer.expires !== outer.expires ||
    canonicalJson(offer.callback) !== canonicalJson(outer.callback) ||
    offer.return_token !== outer.returnToken ||
    offer.return_page !== outer.returnPage ||
    await deriveHostFingerprint(
      outer.hostPublicKey,
      outer.generation
    ) !== outer.fingerprint ||
    !await verifyHostTranscript(outer.hostPublicKey, offer)
  ) throw new Error('manual offer host signature or binding is invalid');
  const canonical = encoder.encode(canonicalJson(offer));
  return {
    version: VERSION,
    mode: 'manual-offer',
    ...outer,
    offer,
    offerHash: await sha256Hex(canonical)
  };
}

async function createManualOffer({
  stream,
  room,
  key,
  generation,
  fingerprint,
  hostPublicKey,
  hostPrivateJwk,
  callback,
  returnToken,
  returnPage,
  joinBase,
  now = nowSeconds(),
  onPeerConnection = () => {},
  peerConnectionFactory = config => new RTCPeerConnection(config)
}) {
  tokenBytes(room, 16, 'room');
  tokenBytes(key, 32, 'room key');
  tokenBytes(returnToken, 32, 'manual return token');
  const normalizedReturnPage = normalizeHttpsBase(
    returnPage,
    'manual return page'
  );
  if (
    !validateCallback(callback) ||
    !new URL(normalizedReturnPage).pathname.endsWith('/return/') ||
    !await verifyPrivateKeyBinding(hostPrivateJwk, hostPublicKey) ||
    await deriveHostFingerprint(hostPublicKey, generation) !== fingerprint
  ) throw new Error('host identity or manual callback is invalid');
  const pc = peerConnectionFactory(cloneRtcConfig());
  onPeerConnection(pc);
  const channel = pc.createDataChannel('rpp-telemetry-v2', {ordered: true});
  try {
    for (const track of stream.getTracks()) pc.addTrack(track, stream);
    await pc.setLocalDescription(await pc.createOffer());
    await waitForIceComplete(pc);
    const sdp = pc.localDescription && pc.localDescription.sdp;
    assertDirectSdp(sdp);
    const pair = randomToken(16);
    const offer = await signHostTranscript(hostPrivateJwk, {
      v: VERSION,
      type: 'rpp-manual-offer',
      pair,
      room,
      generation,
      fingerprint,
      host_public_key: hostPublicKey,
      created: now,
      expires: now + OFFER_TTL_SECONDS,
      sdp,
      callback,
      return_token: returnToken,
      return_page: normalizedReturnPage
    });
    const plain = encoder.encode(canonicalJson(offer));
    const packed = await compressBytes(plain);
    const offerHash = await sha256Hex(plain);
    const params = new URLSearchParams({
      v: String(VERSION),
      mode: 'manual-offer',
      room,
      key,
      gen: generation,
      fp: fingerprint,
      pub: hostPublicKey,
      pair,
      exp: String(offer.expires),
      cb: callbackToken(callback),
      rt: returnToken,
      ret: normalizedReturnPage,
      zip: packed.compression,
      offer: bytesToBase64Url(packed.bytes)
    });
    const link = `${normalizeHttpsBase(
      joinBase,
      'manual pairing base'
    )}#${params}`;
    if (byteLength(link) > MAX_ENCODED_BYTES) {
      throw new Error('manual offer link is too large');
    }
    return {
      pc,
      channel,
      pair,
      room,
      generation,
      fingerprint,
      hostPublicKey,
      key,
      offer,
      offerHash,
      expires: offer.expires,
      callback,
      returnToken,
      returnPage: normalizedReturnPage,
      link,
      qrSafe: safeForQr(link),
      used: false,
      accepting: false
    };
  } catch (error) {
    try { channel.close(); } catch (_error) {}
    try { pc.close(); } catch (_error) {}
    throw error;
  }
}

function manualAnswerInfo(capability) {
  return encoder.encode(
    `rpp-manual-answer-v2\0${capability.room}\0` +
    `${capability.generation}\0${capability.pair}\0${capability.fingerprint}`
  );
}

async function deriveManualAnswerKey(capability) {
  const base = await crypto.subtle.importKey(
    'raw',
    tokenBytes(capability.key, 32, 'room key'),
    'HKDF',
    false,
    ['deriveKey']
  );
  return crypto.subtle.deriveKey(
    {
      name: 'HKDF',
      hash: 'SHA-256',
      salt: hexToBytes(capability.offerHash, 32),
      info: manualAnswerInfo(capability)
    },
    base,
    {name: 'AES-GCM', length: 256},
    false,
    ['encrypt', 'decrypt']
  );
}

function answerAad(envelope) {
  return encoder.encode(canonicalJson({
    v: envelope.v,
    type: envelope.type,
    pair: envelope.pair,
    generation: envelope.generation,
    offer_hash: envelope.offer_hash,
    compression: envelope.compression
  }));
}

async function encryptManualAnswer(capability, answer, options = {}) {
  const plain = encoder.encode(canonicalJson(answer));
  const packed = await compressBytes(plain);
  const iv = options.iv || crypto.getRandomValues(new Uint8Array(12));
  if (!(iv instanceof Uint8Array) || iv.byteLength !== 12) {
    throw new Error('manual answer IV must contain 12 bytes');
  }
  const envelope = {
    v: VERSION,
    type: 'rpp-manual-answer',
    pair: capability.pair,
    generation: capability.generation,
    offer_hash: capability.offerHash,
    compression: packed.compression,
    iv: bytesToBase64Url(iv),
    ciphertext: ''
  };
  const encrypted = await crypto.subtle.encrypt(
    {
      name: 'AES-GCM',
      iv,
      additionalData: answerAad(envelope),
      tagLength: 128
    },
    await deriveManualAnswerKey(capability),
    packed.bytes
  );
  envelope.ciphertext = bytesToBase64Url(new Uint8Array(encrypted));
  return envelope;
}

function validateAnswerPayload(value, capability, now) {
  return Boolean(
    exactKeys(value, [
      'created', 'expires', 'fingerprint', 'generation', 'offer_hash',
      'pair', 'room', 'sdp', 'type', 'v'
    ]) &&
    value.v === VERSION &&
    value.type === 'rpp-manual-answer-payload' &&
    value.pair === capability.pair &&
    value.room === capability.room &&
    value.generation === capability.generation &&
    value.fingerprint === capability.fingerprint &&
    value.offer_hash === capability.offerHash &&
    Number.isSafeInteger(value.created) &&
    Number.isSafeInteger(value.expires) &&
    value.created <= now + 30 &&
    value.expires === capability.expires &&
    value.expires >= now &&
    typeof value.sdp === 'string'
  );
}

function buildReturnLink(capability, answerText) {
  tokenBytes(capability.returnToken, 32, 'manual return token');
  const params = new URLSearchParams({
    v: String(VERSION),
    mode: 'manual-return',
    gen: capability.generation,
    cb: callbackToken(capability.callback),
    rt: capability.returnToken,
    answer: answerText
  });
  const link = `${normalizeHttpsBase(
    capability.returnPage,
    'manual return page'
  )}#${params}`;
  if (byteLength(link) > MAX_ENCODED_BYTES) {
    throw new Error('manual return link is too large');
  }
  return link;
}

async function createManualAnswer({
  capability,
  onStream,
  onChannel,
  onPeerConnection = () => {},
  now = nowSeconds(),
  peerConnectionFactory = config => new RTCPeerConnection(config)
}) {
  if (
    !validateManualOffer(capability.offer, now) ||
    !await verifyHostTranscript(capability.hostPublicKey, capability.offer)
  ) throw new Error('manual offer is invalid, expired, or unsigned');
  if (await deriveHostFingerprint(
    capability.hostPublicKey,
    capability.generation
  ) !== capability.fingerprint) {
    throw new Error('manual offer host fingerprint is invalid');
  }
  const pc = peerConnectionFactory(cloneRtcConfig());
  onPeerConnection(pc);
  pc.ontrack = event => {
    const stream = event.streams && event.streams[0];
    if (stream) onStream(stream);
  };
  pc.ondatachannel = event => {
    if (!event.channel || event.channel.label !== 'rpp-telemetry-v2') {
      try { event.channel.close(); } catch (_error) {}
      return;
    }
    onChannel(event.channel);
  };
  try {
    assertDirectSdp(capability.offer.sdp);
    await pc.setRemoteDescription({
      type: 'offer',
      sdp: capability.offer.sdp
    });
    await pc.setLocalDescription(await pc.createAnswer());
    await waitForIceComplete(pc);
    const sdp = pc.localDescription && pc.localDescription.sdp;
    assertDirectSdp(sdp);
    const answer = {
      v: VERSION,
      type: 'rpp-manual-answer-payload',
      pair: capability.pair,
      room: capability.room,
      generation: capability.generation,
      fingerprint: capability.fingerprint,
      offer_hash: capability.offerHash,
      created: now,
      expires: capability.expires,
      sdp
    };
    const envelope = await encryptManualAnswer(capability, answer);
    const text = ANSWER_PREFIX + bytesToBase64Url(
      encoder.encode(canonicalJson(envelope))
    );
    if (byteLength(text) > MAX_ANSWER_TEXT_BYTES) {
      throw new Error('manual answer text is too large');
    }
    const returnLink = buildReturnLink(capability, text);
    return {
      pc,
      answer,
      envelope,
      text,
      returnLink,
      qrSafe: safeForQr(returnLink)
    };
  } catch (error) {
    try { pc.close(); } catch (_error) {}
    throw error;
  }
}

function decodeAnswerEnvelope(text) {
  if (
    typeof text !== 'string' ||
    !text.startsWith(ANSWER_PREFIX) ||
    byteLength(text) > MAX_ANSWER_TEXT_BYTES
  ) throw new Error('manual answer text is invalid');
  let envelope;
  try {
    const serialized = decoder.decode(base64UrlToBytes(
      text.slice(ANSWER_PREFIX.length),
      MAX_ANSWER_TEXT_BYTES
    ));
    envelope = JSON.parse(serialized);
    if (canonicalJson(envelope) !== serialized) throw new Error('non-canonical');
  } catch (_error) {
    throw new Error('manual answer envelope is invalid');
  }
  if (
    !exactKeys(envelope, [
      'ciphertext', 'compression', 'generation', 'iv', 'offer_hash',
      'pair', 'type', 'v'
    ]) ||
    envelope.v !== VERSION ||
    envelope.type !== 'rpp-manual-answer' ||
    !/^[A-Za-z0-9_-]{16,128}$/.test(envelope.generation || '') ||
    !/^[A-Za-z0-9_-]{22}$/.test(envelope.pair || '') ||
    !/^[a-f0-9]{64}$/.test(envelope.offer_hash || '') ||
    envelope.compression !== 'none'
  ) throw new Error('manual answer envelope schema is invalid');
  const iv = base64UrlToBytes(envelope.iv, 32);
  const ciphertext = base64UrlToBytes(
    envelope.ciphertext,
    MAX_ANSWER_TEXT_BYTES
  );
  if (iv.byteLength !== 12 || ciphertext.byteLength < 16) {
    throw new Error('manual answer envelope values are invalid');
  }
  return {envelope, iv, ciphertext};
}

async function acceptManualAnswer(pending, text, now = nowSeconds()) {
  if (!pending || pending.used || pending.accepting) {
    throw new Error('manual pair is already used');
  }
  if (pending.expires < now) {
    pending.used = true;
    try { pending.pc.close(); } catch (_error) {}
    throw new Error('manual pair has expired');
  }
  const {envelope, iv, ciphertext} = decodeAnswerEnvelope(text.trim());
  if (
    envelope.pair !== pending.pair ||
    envelope.generation !== pending.generation ||
    envelope.offer_hash !== pending.offerHash
  ) throw new Error('manual answer does not match this pair');
  pending.accepting = true;
  let packed;
  try {
    packed = await crypto.subtle.decrypt(
      {
        name: 'AES-GCM',
        iv,
        additionalData: answerAad(envelope),
        tagLength: 128
      },
      await deriveManualAnswerKey({
        key: pending.key,
        room: pending.room,
        generation: pending.generation,
        pair: pending.pair,
        fingerprint: pending.fingerprint,
        offerHash: pending.offerHash
      }),
      ciphertext
    );
  } catch (_error) {
    pending.accepting = false;
    throw new Error('manual answer authentication failed');
  }
  let answer;
  try {
    const plain = await decompressBytes(
      new Uint8Array(packed),
      envelope.compression,
      MAX_DECOMPRESSED_BYTES
    );
    const serialized = decoder.decode(plain);
    answer = JSON.parse(serialized);
    if (canonicalJson(answer) !== serialized) throw new Error('non-canonical');
  } catch (_error) {
    pending.accepting = false;
    throw new Error('manual answer payload is invalid');
  }
  const capability = {
    room: pending.room,
    generation: pending.generation,
    pair: pending.pair,
    fingerprint: pending.fingerprint,
    offerHash: pending.offerHash,
    expires: pending.expires
  };
  if (!validateAnswerPayload(answer, capability, now)) {
    pending.accepting = false;
    throw new Error('manual answer binding is invalid');
  }
  assertDirectSdp(answer.sdp);
  pending.used = true;
  try {
    await pending.pc.setRemoteDescription({type: 'answer', sdp: answer.sdp});
  } catch (_error) {
    try { pending.channel.close(); } catch (_closeError) {}
    try { pending.pc.close(); } catch (_closeError) {}
    throw new Error('manual answer SDP could not be applied');
  }
  return {answer, candidateTypes: candidateTypesFromSdp(answer.sdp)};
}

globalThis.RppPairing = Object.freeze({
  VERSION,
  OFFER_TTL_SECONDS,
  MAX_SDP_BYTES,
  MAX_DECOMPRESSED_BYTES,
  MAX_ENCODED_BYTES,
  MAX_ANSWER_TEXT_BYTES,
  QR_CAPACITY_BYTES,
  ANSWER_PREFIX,
  RTC_CONFIG,
  exactKeys,
  byteLength,
  canonicalJson,
  bytesToBase64Url,
  base64UrlToBytes,
  randomToken,
  sha256Hex,
  validPublicJwk,
  validPrivateJwk,
  publicJwkFromPrivate,
  publicKeyToken,
  parsePublicKeyToken,
  deriveHostFingerprint,
  signHostTranscript,
  verifyHostTranscript,
  verifyPrivateKeyBinding,
  addViewerProof,
  verifyViewerProof,
  parseAutoFragment,
  candidateTypesFromSdp,
  assertDirectSdp,
  selectedCandidateType,
  waitForIceComplete,
  compressBytes,
  decompressBytes,
  parseManualOfferFragment,
  safeForQr,
  callbackToken,
  parseCallbackToken,
  validateCallback,
  createManualOffer,
  deriveManualAnswerKey,
  encryptManualAnswer,
  buildReturnLink,
  createManualAnswer,
  decodeAnswerEnvelope,
  acceptManualAnswer,
  cloneRtcConfig
});
})();
