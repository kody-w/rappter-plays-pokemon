
(() => {
'use strict';

const BUILD = 'rpp-kite-host-v2';
const VERSION = 2;
const PROTOCOL_V2 = 2;
const TELEMETRY_VERSION = 1;
const NOSTR_APP_ID = 'rappter-plays-pokemon-v2';
const ROLE_MESSAGE_MAX_BYTES = 2048;
const REVIEWED_RELAYS = Object.freeze([
  'wss://communities.nos.social',
  'wss://purplerelay.com',
  'wss://bucket.coracle.social',
  'wss://relay.nostr.place',
  'wss://relay.damus.io'
]);
const MAX_FRAME_BYTES = 128 * 1024;
const WIDTH = 160;
const HEIGHT = 144;
const STRING_LOST_MS = 5000;
const SOURCE_LOST_MS = 3000;
const TEARDOWN_GRACE_MS = 12000;
const HOST_AUTH_DEADLINE_MS = 12000;
const TRANSPORT_DEADLINE_MS = 15000;
const MEDIA_DEADLINE_MS = 30000;
const ZERO_RELAY_DEADLINE_MS = 12000;
const BADGES = [
  'Boulder', 'Cascade', 'Thunder', 'Rainbow',
  'Soul', 'Marsh', 'Volcano', 'Earth'
];

const game = document.getElementById('game');
const gameContext = game.getContext('2d', {alpha: false});
gameContext.imageSmoothingEnabled = false;
const pipVideo = document.getElementById('pip-video');
const pipButton = document.getElementById('pip-toggle');
const pipStatus = document.getElementById('pip-status');
const goButton = document.getElementById('go-live');
const endButton = document.getElementById('end-live');
const retryButton = document.getElementById('retry-live');
const copyButton = document.getElementById('copy-link');
const manualCreateButton = document.getElementById('manual-create');
const manualCopyButton = document.getElementById('manual-copy-offer');
const manualShareButton = document.getElementById('manual-share-offer');
const manualImportButton = document.getElementById('manual-import-answer');

function monotonicNow() {
  return globalThis.performance && typeof globalThis.performance.now === 'function'
    ? globalThis.performance.now()
    : Date.now();
}

function exactKeys(value, keys) {
  return Boolean(
    value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join(',') === [...keys].sort().join(',')
  );
}

function boundedInteger(value, minimum, maximum) {
  return Number.isSafeInteger(value) && value >= minimum && value <= maximum;
}

function boundedText(value, maximum) {
  return value === null || (
    typeof value === 'string' && Array.from(value).length <= maximum
  );
}

function byteLength(value) {
  try {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength;
  } catch (_error) {
    return Infinity;
  }
}

function selectorFromFragment() {
  const params = new URLSearchParams(location.hash.slice(1));
  if ([...params.keys()].sort().join(',') !== 'instance,v') return null;
  if (params.get('v') !== '2') return null;
  const instance = params.get('instance') || '';
  if (!/^[A-Za-z0-9_-]{16,64}$/.test(instance)) return null;
  return instance;
}

const selector = selectorFromFragment();
const state = {
  config: null,
  generation: '',
  instance: selector || '',
  peer: null,
  room: null,
  telemetryAction: null,
  mediaReadyAction: null,
  stream: null,
  viewers: new Map(),
  negotiating: new Map(),
  streamState: 'untethered',
  peerOpen: false,
  relayOpenCount: 0,
  relayQualifiedCount: 0,
  relayTotal: 0,
  relayTimer: null,
  relayFailureStartedAt: null,
  relayAnnouncement: false,
  signaling: 'peerjs',
  candidateTypes: new Set(),
  manualPending: new Map(),
  manualCreating: new Set(),
  manualDisplayPair: '',
  answerReplay: new Set(),
  firstFrame: false,
  sourceSequence: 0,
  sourceHash: '',
  frameAttemptedSequence: 0,
  frameAttemptedHash: '',
  frameDrawnSequence: 0,
  frameDrawnHash: '',
  telemetrySequence: 0,
  heartbeatSequence: 0,
  shutdownSequence: 0,
  broadcastDesired: true,
  broadcastSequence: 0,
  lastFrameAt: null,
  lastSourceAt: null,
  lastHeartbeatAt: null,
  lastTelemetryAt: null,
  telemetrySnapshot: null,
  telemetrySerialized: '',
  telemetryFanoutSequence: 0,
  runtimeState: 'waiting',
  manuallyStopped: false,
  starting: false,
  ending: false,
  attemptEpoch: 0,
  teardownPromise: Promise.resolve(true),
  leaveFailed: false,
  identityReady: false,
  error: ''
};

function healthValue(id, label, healthy) {
  const element = document.getElementById(id);
  element.textContent = label;
  element.classList.toggle('lost', !healthy);
}

function stringHealthy(now = monotonicNow()) {
  return state.lastHeartbeatAt !== null &&
    now - state.lastHeartbeatAt <= STRING_LOST_MS;
}

function sourceHealthy(now = monotonicNow()) {
  return state.lastSourceAt !== null &&
    now - state.lastSourceAt <= SOURCE_LOST_MS;
}

async function recordCandidateType(pc) {
  if (!pc || typeof RppPairing !== 'object') return;
  try {
    const type = await RppPairing.selectedCandidateType(pc);
    if (['host', 'srflx', 'prflx'].includes(type)) {
      state.candidateTypes.add(type);
    } else if (type === 'relay') {
      state.error = 'relay-candidate-rejected';
      try { pc.close(); } catch (_error) {}
    }
  } catch (_error) {
    // Candidate reporting is diagnostic and does not own the media session.
  }
}

function automaticShareReady() {
  return Boolean(
    state.config &&
    state.broadcastDesired &&
    state.identityReady &&
    (
      state.signaling === 'nostr'
        ? state.room && state.relayQualifiedCount > 0
        : state.peerOpen
    ) &&
    state.firstFrame &&
    stringHealthy() &&
    sourceHealthy() &&
    state.streamState === 'live'
  );
}

function manualShareReady() {
  return Boolean(
    state.config &&
    state.signaling === 'nostr' &&
    state.broadcastDesired &&
    state.identityReady &&
    state.stream &&
    state.firstFrame &&
    stringHealthy() &&
    sourceHealthy() &&
    !state.ending
  );
}

function shareReady() {
  return automaticShareReady();
}

function updateControls() {
  const ready = Boolean(
    state.config && state.firstFrame && stringHealthy() && sourceHealthy()
  );
  goButton.disabled = !ready || Boolean(state.peer || state.room) || state.starting;
  endButton.disabled = !state.peer && !state.room && !state.stream && !state.starting;
  retryButton.disabled = !ready || state.starting;
  pipButton.disabled = !pictureInPictureSupported() ||
    (!pictureInPictureReady() && !pictureInPictureActive());
  copyButton.disabled = !automaticShareReady();
  manualCreateButton.disabled = !manualShareReady() ||
    state.viewers.size + state.negotiating.size + state.manualPending.size >= (
      state.config ? state.config.max_viewers : 0
    );
}

function updateHealth() {
  const now = monotonicNow();
  const source = sourceHealthy(now);
  const string = stringHealthy(now);
  healthValue('source-health', source ? 'OK' : 'SOURCE LOST', source);
  healthValue('string-health', string ? 'TETHERED' : 'STRING LOST', string);
  healthValue(
    'runtime-health',
    state.runtimeState.toUpperCase(),
    state.runtimeState === 'ready'
  );
  const peerLabel = state.signaling === 'nostr'
    ? `${state.relayQualifiedCount} QUALIFIED · ${state.relayOpenCount} OPEN`
    : (
      state.peerOpen
        ? 'OPEN'
        : (state.starting ? 'CONNECTING' : 'OFFLINE')
    );
  healthValue('peer-health', peerLabel, state.peerOpen);
  const automatic = document.getElementById('automatic-health');
  if (automatic) {
    automatic.textContent = automaticShareReady()
      ? 'LIVE'
      : (state.room ? 'WAITING FOR RELAY ROUND-TRIP' : 'OFFLINE');
    automatic.classList.toggle('lost', !automaticShareReady());
  }
  const manual = document.getElementById('manual-health');
  if (manual) {
    manual.textContent = manualShareReady() ? 'READY' : 'OFFLINE';
    manual.classList.toggle('lost', !manualShareReady());
  }
  const share = document.getElementById('share');
  if (share) share.hidden = !automaticShareReady();
  const direct = [...state.viewers.values()].filter(
    entry => entry.directConnected
  ).length;
  const mediaReady = [...state.viewers.values()].filter(
    entry => entry.mediaReady
  ).length;
  const directLabel = mediaReady
    ? `${mediaReady} MEDIA READY`
    : (
      direct
        ? `${direct} TRANSPORT CONNECTED`
        : (state.viewers.size ? 'CONNECTING' : 'IDLE')
    );
  healthValue(
    'media-health',
    directLabel,
    !state.viewers.size || mediaReady > 0
  );
  document.getElementById('viewer-count').textContent =
    String(state.viewers.size);
  updateControls();
  if (
    state.config &&
    (
      (state.lastHeartbeatAt !== null &&
        now - state.lastHeartbeatAt > TEARDOWN_GRACE_MS) ||
      (state.lastSourceAt !== null &&
        now - state.lastSourceAt > TEARDOWN_GRACE_MS)
    ) &&
    (state.peer || state.room || state.stream)
  ) {
    teardownBroadcast(
      string ? 'SOURCE LOST — capture stopped.' : 'STRING LOST — capture stopped.',
      'error'
    );
  }
}

function setStreamState(next, message) {
  state.streamState = next;
  if (message) document.getElementById('host-message').textContent = message;
  const badge = document.getElementById('live-badge');
  const labels = {
    untethered: 'UNTETHERED',
    ready: 'READY',
    connecting: 'CONNECTING',
    live: 'LIVE',
    reconnecting: 'RECONNECTING',
    offline: 'OFFLINE',
    error: 'DEGRADED',
    stopped: 'STOPPED'
  };
  badge.textContent = labels[next] || 'OFFLINE';
  badge.className = 'badge ' + (
    next === 'live'
      ? 'live'
      : (['connecting', 'reconnecting'].includes(next) ? 'connecting' : 'offline')
  );
  updateHealth();
}

function validDashboardSnapshot(value) {
  if (!exactKeys(value, [
    'location', 'objective', 'phase', 'badges', 'pokedex', 'party',
    'completed', 'player', 'play_time', 'session_elapsed_seconds',
    'checkpoint', 'viewers'
  ])) return false;
  if (
    !boundedText(value.location, 80) ||
    !boundedText(value.objective, 160) ||
    !boundedText(value.phase, 40) ||
    typeof value.completed !== 'boolean'
  ) return false;
  if (!exactKeys(value.badges, ['earned', 'count', 'total'])) return false;
  if (
    !Array.isArray(value.badges.earned) ||
    value.badges.earned.some(name => !BADGES.includes(name)) ||
    new Set(value.badges.earned).size !== value.badges.earned.length ||
    !(value.badges.count === null ||
      value.badges.count === value.badges.earned.length) ||
    (value.badges.count === null && value.badges.earned.length !== 0) ||
    value.badges.total !== 8
  ) return false;
  if (!exactKeys(value.pokedex, ['caught', 'seen', 'total'])) return false;
  if (
    !(value.pokedex.caught === null ||
      boundedInteger(value.pokedex.caught, 0, 151)) ||
    !(value.pokedex.seen === null ||
      boundedInteger(value.pokedex.seen, 0, 151)) ||
    value.pokedex.total !== 151
  ) return false;
  if (!(value.party === null || (
    Array.isArray(value.party) && value.party.length <= 6
  ))) return false;
  for (const member of value.party || []) {
    if (!exactKeys(
      member,
      ['nickname', 'species_id', 'level', 'hp', 'max_hp']
    )) return false;
    if (
      !boundedText(member.nickname, 24) ||
      !(member.species_id === null ||
        boundedInteger(member.species_id, 1, 255)) ||
      !(member.level === null || boundedInteger(member.level, 1, 100)) ||
      !(member.hp === null || boundedInteger(member.hp, 0, 65535)) ||
      !(member.max_hp === null ||
        boundedInteger(member.max_hp, 1, 65535)) ||
      (member.hp !== null && member.max_hp !== null &&
        member.hp > member.max_hp)
    ) return false;
  }
  if (!exactKeys(value.player, ['mode', 'paused'])) return false;
  if (
    !['ai', 'manual', 'paused', 'unknown'].includes(value.player.mode) ||
    typeof value.player.paused !== 'boolean'
  ) return false;
  if (value.play_time !== null) {
    if (!exactKeys(
      value.play_time,
      ['hours', 'minutes', 'seconds', 'frames', 'maxed']
    )) return false;
    if (
      !boundedInteger(value.play_time.hours, 0, 255) ||
      !boundedInteger(value.play_time.minutes, 0, 59) ||
      !boundedInteger(value.play_time.seconds, 0, 59) ||
      !boundedInteger(value.play_time.frames, 0, 59) ||
      typeof value.play_time.maxed !== 'boolean'
    ) return false;
  }
  if (
    !(value.session_elapsed_seconds === null ||
      boundedInteger(value.session_elapsed_seconds, 0, 316224000))
  ) return false;
  if (value.checkpoint !== null) {
    if (!exactKeys(
      value.checkpoint,
      ['timestamp', 'kind', 'location', 'age_seconds']
    )) return false;
    if (
      typeof value.checkpoint.timestamp !== 'string' ||
      value.checkpoint.timestamp.length > 48 ||
      !Number.isFinite(Date.parse(value.checkpoint.timestamp)) ||
      ![
        'manual', 'milestone', 'automatic', 'shutdown',
        'recovery', 'progress', 'other'
      ].includes(value.checkpoint.kind) ||
      !boundedText(value.checkpoint.location, 80) ||
      !(value.checkpoint.age_seconds === null ||
        boundedInteger(value.checkpoint.age_seconds, 0, 316224000))
    ) return false;
  }
  return (
    exactKeys(value.viewers, ['count', 'capacity']) &&
    boundedInteger(value.viewers.count, 0, 8) &&
    boundedInteger(value.viewers.capacity, 0, 8) &&
    value.viewers.count <= value.viewers.capacity
  );
}

function validPeerOptions(value) {
  if (!exactKeys(
    value,
    ['config', 'debug', 'host', 'path', 'port', 'secure']
  )) return false;
  if (
    value.host !== '0.peerjs.com' ||
    value.port !== 443 ||
    value.path !== '/' ||
    value.secure !== true ||
    value.debug !== 0 ||
    !exactKeys(value.config, ['iceServers']) ||
    !Array.isArray(value.config.iceServers) ||
    value.config.iceServers.length !== 1
  ) return false;
  const server = value.config.iceServers[0];
  return exactKeys(server, ['urls']) &&
    server.urls === 'stun:stun.l.google.com:19302';
}

function validRtcConfig(value) {
  return Boolean(
    exactKeys(value, ['iceServers']) &&
    Array.isArray(value.iceServers) &&
    value.iceServers.length === 1 &&
    exactKeys(value.iceServers[0], ['urls']) &&
    value.iceServers[0].urls === 'stun:stun.l.google.com:19302'
  );
}

function validNostrConfig(value) {
  let identity = false;
  try {
    RppPairing.parsePublicKeyToken(value.host_public_key);
    identity = RppPairing.validPrivateJwk(value.host_private_jwk) &&
      RppPairing.validateCallback(value.manual_callback);
  } catch (_error) {
    identity = false;
  }
  return Boolean(
    identity &&
    value.signaling === 'nostr' &&
    value.protocol_version === PROTOCOL_V2 &&
    /^[A-Za-z0-9_-]{22}$/.test(value.room_id || '') &&
    /^[A-Za-z0-9_-]{43}$/.test(value.room_key || '') &&
    /^[a-f0-9]{32}$/.test(value.host_fingerprint || '') &&
    /^[A-Za-z0-9_-]{43}$/.test(value.manual_return_token || '') &&
    typeof value.manual_return_page === 'string' &&
    value.manual_return_page.length <= 512 &&
    Array.isArray(value.relay_urls) &&
    value.relay_urls.length === REVIEWED_RELAYS.length &&
    value.relay_urls.every(
      (url, index) => url === REVIEWED_RELAYS[index]
    ) &&
    validRtcConfig(value.rtc_config)
  );
}

function validJoin(config) {
  try {
    const url = new URL(config.join_url);
    if (
      url.protocol !== 'https:' ||
      url.username ||
      url.password ||
      url.search
    ) return false;
    const params = new URLSearchParams(url.hash.slice(1));
    if (config.signaling === 'nostr') {
      return (
        [...params.keys()].sort().join(',') === 'fp,gen,key,pub,room,v' &&
        params.get('v') === String(PROTOCOL_V2) &&
        params.get('room') === config.room_id &&
        params.get('key') === config.room_key &&
        params.get('gen') === config.generation &&
        params.get('pub') === config.host_public_key &&
        params.get('fp') === config.host_fingerprint
      );
    }
    return (
      [...params.keys()].sort().join(',') === 'host,v,watch' &&
      params.get('v') === String(config.protocol_version) &&
      params.get('host') === config.peer_id &&
      params.get('watch') === config.watch_capability
    );
  } catch (_error) {
    return false;
  }
}

function validBootstrap(value) {
  const legacyKeys = [
    'broadcast_desired', 'broadcast_sequence', 'build', 'frame_rate',
    'generation', 'instance', 'join_url', 'max_hello_bytes',
    'max_negotiating', 'max_telemetry_bytes', 'max_viewers', 'peer_id',
    'peer_options', 'protocol_version', 'telemetry_version',
    'watch_capability'
  ];
  const nostrKeys = [
    'broadcast_desired', 'broadcast_sequence', 'build', 'frame_rate',
    'generation', 'host_fingerprint', 'host_private_jwk',
    'host_public_key', 'instance', 'join_url', 'manual_callback',
    'manual_return_page', 'manual_return_token', 'max_hello_bytes',
    'max_negotiating', 'max_telemetry_bytes', 'max_viewers',
    'protocol_version', 'relay_urls', 'room_id', 'room_key',
    'rtc_config', 'signaling', 'telemetry_version'
  ];
  const legacy = exactKeys(value, legacyKeys);
  const nostr = exactKeys(value, nostrKeys);
  if (!legacy && !nostr) return false;
  return (
    selector !== null &&
    value.build === BUILD &&
    value.instance === selector &&
    /^[A-Za-z0-9_-]{16,128}$/.test(value.generation || '') &&
    value.telemetry_version === TELEMETRY_VERSION &&
    typeof value.broadcast_desired === 'boolean' &&
    boundedInteger(
      value.broadcast_sequence,
      0,
      Number.MAX_SAFE_INTEGER
    ) &&
    value.frame_rate === 10 &&
    value.max_hello_bytes === (nostr ? ROLE_MESSAGE_MAX_BYTES : 512) &&
    boundedInteger(value.max_viewers, 1, 8) &&
    boundedInteger(value.max_negotiating, 2, 16) &&
    value.max_telemetry_bytes === 4096 &&
    (
      nostr
        ? validNostrConfig(value)
        : (
          /^rpp-[a-f0-9]{32}$/.test(value.peer_id || '') &&
          /^[A-Za-z0-9_-]{32,128}$/.test(value.watch_capability || '') &&
          value.protocol_version === 1 &&
          validPeerOptions(value.peer_options)
        )
    ) &&
    validJoin(value) &&
    byteLength(value) <= 4096
  );
}

function validEnvelope(value, payloadKeys) {
  if (!exactKeys(
    value,
    ['generation', 'instance', 'sequence', ...payloadKeys]
  )) return false;
  return (
    state.config &&
    value.generation === state.generation &&
    value.instance === state.instance &&
    boundedInteger(value.sequence, 1, Number.MAX_SAFE_INTEGER)
  );
}

function configureShare() {
  const share = document.getElementById('share');
  const link = document.getElementById('join-link');
  share.hidden = true;
  link.href = state.config.join_url;
  link.textContent = state.config.join_url;
  const status = document.getElementById('share-status');
  if (status) {
    status.textContent =
      'Automatic link waiting for a verified relay round-trip.';
  }
  try {
    if (
      state.signaling === 'nostr' &&
      !RppPairing.safeForQr(state.config.join_url)
    ) throw new Error('join link exceeds QR capacity');
    new QRious({
      element: document.getElementById('stream-qr'),
      value: state.config.join_url,
      size: 220,
      level: 'M',
      background: 'white',
      foreground: 'black'
    });
  } catch (_error) {
    state.error = 'qr-unavailable';
  }
}

function bootstrap(value) {
  if (state.config || !validBootstrap(value)) {
    return {ok: false, reason: state.config ? 'already-bootstrapped' : 'schema'};
  }
  state.config = Object.freeze(value);
  state.signaling = value.signaling === 'nostr' ? 'nostr' : 'peerjs';
  state.generation = value.generation;
  state.instance = value.instance;
  state.broadcastDesired = value.broadcast_desired;
  state.broadcastSequence = value.broadcast_sequence;
  state.manuallyStopped = !value.broadcast_desired;
  state.identityReady = value.signaling !== 'nostr';
  state.runtimeState = 'starting';
  document.getElementById('viewer-limit').textContent =
    String(value.max_viewers);
  document.getElementById('manual-pairing').hidden =
    state.signaling !== 'nostr';
  configureShare();
  setStreamState(
    value.broadcast_desired ? 'ready' : 'offline',
    value.broadcast_desired
      ? 'Tethered. Waiting for the first validated frame.'
      : 'Broadcast is ended. Select Go Live or Retry to resume.'
  );
  return {ok: true, version: VERSION, build: BUILD};
}

function decodeBase64(value) {
  if (
    typeof value !== 'string' ||
    value.length < 16 ||
    value.length > Math.ceil(MAX_FRAME_BYTES / 3) * 4 + 4 ||
    !/^[A-Za-z0-9+/]+={0,2}$/.test(value)
  ) return null;
  try {
    const raw = atob(value);
    if (raw.length > MAX_FRAME_BYTES) return null;
    const bytes = new Uint8Array(raw.length);
    for (let index = 0; index < raw.length; index += 1) {
      bytes[index] = raw.charCodeAt(index);
    }
    return bytes;
  } catch (_error) {
    return null;
  }
}

function pngDimensions(bytes) {
  if (
    bytes.length < 33 ||
    bytes[0] !== 0x89 || bytes[1] !== 0x50 ||
    bytes[2] !== 0x4e || bytes[3] !== 0x47 ||
    bytes[4] !== 0x0d || bytes[5] !== 0x0a ||
    bytes[6] !== 0x1a || bytes[7] !== 0x0a ||
    bytes[12] !== 0x49 || bytes[13] !== 0x48 ||
    bytes[14] !== 0x44 || bytes[15] !== 0x52
  ) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return {width: view.getUint32(16), height: view.getUint32(20)};
}

function hexDigest(bytes) {
  return crypto.subtle.digest('SHA-256', bytes).then(digest =>
    [...new Uint8Array(digest)]
      .map(value => value.toString(16).padStart(2, '0'))
      .join('')
  );
}

async function receiveFrame(value) {
  if (
    !validEnvelope(value, ['png_base64', 'sha256']) ||
    value.sequence <= state.frameAttemptedSequence ||
    !/^[a-f0-9]{64}$/.test(value.sha256 || '')
  ) return {ok: false, reason: 'sequence-or-schema'};
  state.frameAttemptedSequence = value.sequence;
  state.frameAttemptedHash = value.sha256;
  const rejected = reason => {
    if (
      value.sequence === state.frameAttemptedSequence &&
      reason !== 'superseded'
    ) {
      state.lastSourceAt = monotonicNow() - TEARDOWN_GRACE_MS - 1;
      state.error = `frame-${reason}`.slice(0, 80);
      updateHealth();
    }
    return {ok: false, reason};
  };
  const bytes = decodeBase64(value.png_base64);
  const dimensions = bytes && pngDimensions(bytes);
  if (!dimensions || dimensions.width !== WIDTH || dimensions.height !== HEIGHT) {
    return rejected('png');
  }
  let digest;
  try {
    digest = await hexDigest(bytes);
  } catch (_error) {
    return rejected('hash');
  }
  if (value.sequence !== state.frameAttemptedSequence) {
    return rejected('superseded');
  }
  if (digest !== value.sha256) return rejected('hash');
  let bitmap;
  try {
    bitmap = await createImageBitmap(new Blob([bytes], {type: 'image/png'}));
  } catch (_error) {
    return rejected('decode');
  }
  if (value.sequence !== state.frameAttemptedSequence) {
    if (typeof bitmap.close === 'function') bitmap.close();
    return rejected('superseded');
  }
  try {
    gameContext.imageSmoothingEnabled = false;
    gameContext.drawImage(bitmap, 0, 0, WIDTH, HEIGHT);
  } catch (_error) {
    if (typeof bitmap.close === 'function') bitmap.close();
    return rejected('draw');
  }
  if (typeof bitmap.close === 'function') bitmap.close();
  state.frameDrawnSequence = value.sequence;
  state.frameDrawnHash = value.sha256;
  state.firstFrame = true;
  state.lastFrameAt = monotonicNow();
  state.lastSourceAt = state.lastFrameAt;
  state.sourceSequence = value.sequence;
  state.sourceHash = value.sha256;
  if (state.error.startsWith('frame-')) state.error = '';
  if (
    state.config &&
    stringHealthy() &&
    state.runtimeState === 'ready' &&
    !state.peer &&
    !state.room &&
    !state.starting &&
    state.broadcastDesired &&
    !state.manuallyStopped
  ) startBroadcast();
  updateHealth();
  return {ok: true, sequence: value.sequence};
}

function receiveTelemetry(value) {
  if (
    !validEnvelope(value, ['snapshot']) ||
    value.sequence <= state.telemetrySequence ||
    !validDashboardSnapshot(value.snapshot) ||
    byteLength(value) > state.config.max_telemetry_bytes
  ) return {ok: false, reason: 'sequence-or-schema'};
  const serialized = JSON.stringify(value.snapshot);
  const now = monotonicNow();
  if (state.lastTelemetryAt !== null) {
    const changed = serialized !== state.telemetrySerialized;
    const minimum = changed ? 1000 : 4000;
    if (now - state.lastTelemetryAt < minimum) {
      return {ok: false, reason: 'rate'};
    }
  }
  state.telemetrySequence = value.sequence;
  state.telemetrySnapshot = value.snapshot;
  state.telemetrySerialized = serialized;
  state.lastTelemetryAt = now;
  fanoutTelemetry(true);
  return {ok: true, sequence: value.sequence};
}

function receiveHeartbeat(value) {
  if (
    !validEnvelope(value, [
      'runtime_state', 'source_hash', 'source_sequence'
    ]) ||
    value.sequence <= state.heartbeatSequence ||
    !boundedInteger(value.source_sequence, 0, Number.MAX_SAFE_INTEGER) ||
    !(
      (value.source_sequence === 0 && value.source_hash === '') ||
      (
        value.source_sequence > 0 &&
        /^[a-f0-9]{64}$/.test(value.source_hash || '')
      )
    ) ||
    !['starting', 'ready', 'degraded', 'stopping'].includes(value.runtime_state)
  ) return {ok: false, reason: 'sequence-or-schema'};
  state.heartbeatSequence = value.sequence;
  state.runtimeState = value.runtime_state;
  state.lastHeartbeatAt = monotonicNow();
  let sourceAccepted = false;
  if (
    state.firstFrame &&
    value.source_sequence > state.sourceSequence &&
    value.source_sequence >= state.frameDrawnSequence &&
    value.source_hash === state.frameDrawnHash
  ) {
    state.sourceSequence = value.source_sequence;
    state.sourceHash = value.source_hash;
    state.lastSourceAt = state.lastHeartbeatAt;
    sourceAccepted = true;
  }
  if (
    state.firstFrame &&
    !state.peer &&
    !state.room &&
    !state.starting &&
    state.broadcastDesired &&
    !state.manuallyStopped &&
    value.runtime_state === 'ready'
  ) startBroadcast();
  updateHealth();
  return {
    ok: true,
    sequence: value.sequence,
    source_accepted: sourceAccepted,
    source_sequence: sourceAccepted ? value.source_sequence : state.sourceSequence
  };
}

function viewerSnapshot() {
  if (!state.telemetrySnapshot) return null;
  const snapshot = JSON.parse(state.telemetrySerialized);
  snapshot.viewers = {
    count: state.viewers.size,
    capacity: state.config.max_viewers
  };
  return snapshot;
}

function connectionBackpressured(connection) {
  const peer = Number(connection && connection.bufferSize) || 0;
  const rtc = Number(
    connection && connection.dataChannel &&
    connection.dataChannel.bufferedAmount
  ) || 0;
  return Math.max(peer, rtc) > state.config.max_telemetry_bytes * 2;
}

function sendTelemetry(peerId) {
  const entry = state.viewers.get(peerId);
  const snapshot = viewerSnapshot();
  if (
    !entry ||
    !snapshot ||
    (
      entry.mode === 'peerjs' &&
      (!entry.connection.open || connectionBackpressured(entry.connection))
    ) ||
    (
      entry.mode === 'manual' &&
      (
        entry.channel.readyState !== 'open' ||
        Number(entry.channel.bufferedAmount || 0) >
          state.config.max_telemetry_bytes * 2
      )
    )
  ) return;
  const serialized = JSON.stringify(snapshot);
  const changed = serialized !== entry.telemetryHash;
  if (!changed && !entry.forceTelemetry) return;
  if (monotonicNow() - entry.telemetrySentAt < 1000) {
    entry.forceTelemetry = true;
    return;
  }
  if (state.telemetryFanoutSequence >= Number.MAX_SAFE_INTEGER) return;
  const message = {
    v: state.config.protocol_version,
    type: 'telemetry',
    telemetry_version: state.config.telemetry_version,
    sequence: state.telemetryFanoutSequence + 1,
    snapshot
  };
  if (byteLength(message) > state.config.max_telemetry_bytes) return;
  try {
    if (entry.mode === 'nostr') {
      void state.telemetryAction.send(message, {target: peerId}).catch(
        () => closeViewer(peerId)
      );
    } else if (entry.mode === 'manual') {
      entry.channel.send(serializedMessage(message));
    } else {
      entry.connection.send(message);
    }
  } catch (_error) {
    closeViewer(peerId);
    return;
  }

  function serializedMessage(value) {
    const serialized = JSON.stringify(value);
    if (new TextEncoder().encode(serialized).byteLength > 4096) {
      throw new Error('telemetry message too large');
    }
    return serialized;
  }
  state.telemetryFanoutSequence += 1;
  entry.telemetryHash = serialized;
  entry.telemetrySentAt = monotonicNow();
  entry.forceTelemetry = false;
}

function fanoutTelemetry(force = false) {
  for (const [peerId, entry] of state.viewers) {
    if (force) entry.forceTelemetry = true;
    sendTelemetry(peerId);
  }
}

function rejectConnection(connection, reason) {
  try {
    if (connection.open) {
      connection.send({
        v: state.config ? state.config.protocol_version : 1,
        type: 'reject',
        reason
      });
    }
  } catch (_error) {
    // Closing is authoritative.
  }
  try {
    connection.close();
  } catch (_error) {
    // The malformed connection is already isolated.
  }
}

function validWatchHello(value) {
  return Boolean(
    exactKeys(value, ['cap', 'type', 'v']) &&
    value.v === state.config.protocol_version &&
    value.type === 'watch' &&
    typeof value.cap === 'string' &&
    value.cap.length <= 128 &&
    value.cap === state.config.watch_capability &&
    byteLength(value) <= state.config.max_hello_bytes
  );
}

function cleanupNegotiating(peerId, connection) {
  const entry = state.negotiating.get(peerId);
  if (!entry || entry.connection !== connection) return;
  if (entry.timer) clearTimeout(entry.timer);
  state.negotiating.delete(peerId);
}

function closeViewer(peerId) {
  const entry = state.viewers.get(peerId);
  if (!entry) return;
  state.viewers.delete(peerId);
  if (entry.mediaTimer) clearTimeout(entry.mediaTimer);
  if (entry.transportTimer) clearTimeout(entry.transportTimer);
  if (entry.mode === 'nostr') {
    try {
      entry.room.removeStream(entry.stream, {target: peerId});
    } catch (_error) {}
    if (!entry.leaving) {
      try { entry.pc.close(); } catch (_error) {}
    }
  } else if (entry.mode === 'manual') {
    try { entry.channel.close(); } catch (_error) {}
    try { entry.pc.close(); } catch (_error) {}
    if (!state.ending) {
      setManualStatus(
        'Manual connection ended. Create a fresh offer; a consumed offer cannot be reused.'
      );
    }
  } else {
    try { entry.call.close(); } catch (_error) {}
    try { entry.connection.close(); } catch (_error) {}
  }
  fanoutTelemetry(true);
  updateHealth();
}

function acceptDataConnection(connection) {
  if (
    !connection ||
    typeof connection.peer !== 'string' ||
    typeof connection.on !== 'function'
  ) {
    rejectConnection(connection || {}, 'unavailable');
    return;
  }
  const peerId = connection.peer;
  if (
    state.negotiating.has(peerId) ||
    state.viewers.has(peerId) ||
    state.negotiating.size >= state.config.max_negotiating
  ) {
    rejectConnection(connection, 'unavailable');
    return;
  }
  const entry = {connection, opened: false, greeted: false, timer: null};
  state.negotiating.set(peerId, entry);
  const closed = () => {
    cleanupNegotiating(peerId, connection);
    closeViewer(peerId);
  };
  connection.on('close', closed);
  connection.on('error', closed);
  connection.on('open', () => {
    if (state.negotiating.get(peerId) !== entry) {
      rejectConnection(connection, 'unavailable');
      return;
    }
    entry.opened = true;
    entry.timer = setTimeout(() => {
      cleanupNegotiating(peerId, connection);
      rejectConnection(connection, 'hello-timeout');
    }, 5000);
  });
  connection.on('data', value => {
    if (entry.greeted) {
      closeViewer(peerId);
      return;
    }
    if (!entry.opened || !validWatchHello(value)) {
      cleanupNegotiating(peerId, connection);
      rejectConnection(connection, 'invalid-hello');
      return;
    }
    entry.greeted = true;
    cleanupNegotiating(peerId, connection);
    if (state.viewers.size >= state.config.max_viewers) {
      rejectConnection(connection, 'capacity');
      return;
    }
    let call;
    try {
      call = state.peer.call(peerId, state.stream, {
        metadata: {v: state.config.protocol_version, role: 'spectator'}
      });
    } catch (_error) {
      rejectConnection(connection, 'media-failed');
      return;
    }
    if (!call) {
      rejectConnection(connection, 'media-failed');
      return;
    }
    state.viewers.set(peerId, {
      mode: 'peerjs',
      connection,
      call,
      directConnected: false,
      mediaTimer: null,
      telemetryHash: '',
      telemetrySentAt: -Infinity,
      forceTelemetry: true
    });
    try {
      connection.send({v: state.config.protocol_version, type: 'ready'});
    } catch (_error) {
      closeViewer(peerId);
      return;
    }
    call.on('close', () => closeViewer(peerId));
    call.on('error', () => closeViewer(peerId));
    const admitted = state.viewers.get(peerId);
    admitted.mediaTimer = setTimeout(() => {
      const current = state.viewers.get(peerId);
      if (current && current.call === call && !call.open) closeViewer(peerId);
    }, 15000);
    call.on('iceStateChanged', iceState => {
      if (!['connected', 'completed'].includes(iceState)) return;
      const current = state.viewers.get(peerId);
      if (current && current.call === call && current.mediaTimer) {
        clearTimeout(current.mediaTimer);
        current.mediaTimer = null;
        current.directConnected = true;
        void recordCandidateType(current.pc || (
          call.peerConnection || call._negotiator && call._negotiator.connection
        ));
      }
    });
    sendTelemetry(peerId);
    fanoutTelemetry(true);
    updateHealth();
  });
}

function standardPiPSupported() {
  return Boolean(
    document.pictureInPictureEnabled &&
    typeof pipVideo.requestPictureInPicture === 'function'
  );
}

function safariPiPSupported() {
  return Boolean(
    typeof pipVideo.webkitSupportsPresentationMode === 'function' &&
    pipVideo.webkitSupportsPresentationMode('picture-in-picture') &&
    typeof pipVideo.webkitSetPresentationMode === 'function'
  );
}

function pictureInPictureSupported() {
  return standardPiPSupported() || safariPiPSupported();
}

function pictureInPictureActive() {
  return Boolean(
    (standardPiPSupported() && document.pictureInPictureElement === pipVideo) ||
    (safariPiPSupported() &&
      pipVideo.webkitPresentationMode === 'picture-in-picture')
  );
}

function pictureInPictureReady() {
  if (!state.stream || pipVideo.srcObject !== state.stream) return false;
  const tracks = state.stream.getVideoTracks();
  return Number(pipVideo.readyState) >= 1 &&
    tracks.some(track => track.readyState === 'live');
}

function updatePiP() {
  const active = pictureInPictureActive();
  pipButton.textContent = active
    ? 'Exit Picture in Picture'
    : 'Picture in Picture';
  if (!pictureInPictureSupported()) {
    pipStatus.textContent = 'Picture in Picture is not supported by this browser.';
  } else if (active) {
    pipStatus.textContent = 'Picture in Picture is active.';
  } else if (pictureInPictureReady()) {
    pipStatus.textContent = 'Picture in Picture is ready.';
  } else {
    pipStatus.textContent =
      'Picture in Picture becomes available after the canvas stream starts.';
  }
  updateControls();
}

async function togglePiP() {
  if (!pictureInPictureActive() && !pictureInPictureReady()) return;
  try {
    await pipVideo.play();
    if (standardPiPSupported()) {
      if (pictureInPictureActive()) await document.exitPictureInPicture();
      else await pipVideo.requestPictureInPicture();
    } else if (safariPiPSupported()) {
      pipVideo.webkitSetPresentationMode(
        pictureInPictureActive() ? 'inline' : 'picture-in-picture'
      );
    }
    updatePiP();
  } catch (_error) {
    pipStatus.textContent = 'Picture in Picture could not be opened. Try again.';
  }
}

function attachPiP(stream) {
  pipVideo.srcObject = stream;
  for (const track of stream.getTracks()) {
    track.addEventListener('ended', updatePiP);
  }
  const playback = pipVideo.play();
  if (playback && typeof playback.catch === 'function') playback.catch(() => {});
  updatePiP();
}

function cleanupPiP() {
  if (
    standardPiPSupported() &&
    document.pictureInPictureElement === pipVideo &&
    typeof document.exitPictureInPicture === 'function'
  ) {
    const exit = document.exitPictureInPicture();
    if (exit && typeof exit.catch === 'function') exit.catch(() => {});
  }
  if (
    safariPiPSupported() &&
    pipVideo.webkitPresentationMode === 'picture-in-picture'
  ) {
    try { pipVideo.webkitSetPresentationMode('inline'); } catch (_error) {}
  }
  pipVideo.srcObject = null;
  updatePiP();
}

function closeNegotiating(peerId) {
  const entry = state.negotiating.get(peerId);
  if (!entry) return;
  if (entry.timer) clearTimeout(entry.timer);
  state.negotiating.delete(peerId);
}

function validViewerRole(value, peerId) {
  return Boolean(
    exactKeys(value, [
      'expires', 'fingerprint', 'generation', 'host_public_key', 'nonce',
      'proof', 'role', 'room', 'sender', 'sequence', 'target', 'type', 'v'
    ]) &&
    value.v === PROTOCOL_V2 &&
    value.type === 'rpp-role' &&
    value.role === 'viewer' &&
    value.room === state.config.room_id &&
    value.generation === state.generation &&
    value.fingerprint === state.config.host_fingerprint &&
    value.host_public_key === state.config.host_public_key &&
    value.sender === peerId &&
    value.target === RppTrysteroNostr.selfId &&
    value.sequence === 1 &&
    /^[A-Za-z0-9_-]{22}$/.test(value.nonce || '') &&
    Number.isSafeInteger(value.expires) &&
    value.expires >= Math.floor(Date.now() / 1000) &&
    value.expires <= Math.floor(Date.now() / 1000) + 60 &&
    byteLength(value) <= ROLE_MESSAGE_MAX_BYTES
  );
}

async function hostPeerHandshake(epoch, peerId, send, receive) {
  if (epoch !== state.attemptEpoch || !state.room) {
    throw new Error('host attempt ended');
  }
  if (
    state.viewers.size + state.negotiating.size + state.manualPending.size >=
      state.config.max_viewers ||
    state.negotiating.size >= state.config.max_negotiating
  ) throw new Error('host capacity reached');
  const received = await receive();
  const hello = received && received.data;
  if (
    !validViewerRole(hello, peerId) ||
    !await RppPairing.verifyViewerProof(state.config.room_key, hello)
  ) throw new Error('viewer role proof rejected');
  if (epoch !== state.attemptEpoch || !state.room) {
    throw new Error('host attempt ended');
  }
  const entry = {
    mode: 'nostr',
    epoch,
    nonce: hello.nonce,
    timer: setTimeout(
      () => closeNegotiating(peerId),
      HOST_AUTH_DEADLINE_MS
    )
  };
  state.negotiating.set(peerId, entry);
  const response = await RppPairing.signHostTranscript(
    state.config.host_private_jwk,
    {
    v: PROTOCOL_V2,
    type: 'rpp-role',
    role: 'host',
    room: state.config.room_id,
    generation: state.generation,
    fingerprint: state.config.host_fingerprint,
    host_public_key: state.config.host_public_key,
    sender: RppTrysteroNostr.selfId,
    target: peerId,
    viewer_nonce: hello.nonce,
    host_nonce: RppPairing.randomToken(16),
    expires: Math.floor(Date.now() / 1000) + 30,
    sequence: 1
    }
  );
  if (epoch !== state.attemptEpoch || state.negotiating.get(peerId) !== entry) {
    closeNegotiating(peerId);
    throw new Error('host attempt ended');
  }
  await send(response);
}

function monitorDirectPeer(peerId, entry) {
  const update = () => {
    if (state.viewers.get(peerId) !== entry) return;
    const connection = entry.pc.connectionState;
    const ice = entry.pc.iceConnectionState;
    entry.directConnected = (
      connection === 'connected' ||
      ice === 'connected' ||
      ice === 'completed'
    );
    if (entry.directConnected) {
      if (entry.transportTimer) clearTimeout(entry.transportTimer);
      entry.transportTimer = null;
      void recordCandidateType(entry.pc);
    }
    if (connection === 'failed' || connection === 'closed' || ice === 'failed') {
      closeViewer(peerId);
    } else {
      updateHealth();
    }
  };
  entry.pc.addEventListener('connectionstatechange', update);
  entry.pc.addEventListener('iceconnectionstatechange', update);
  update();
}

function admitNostrPeer(epoch, joinedRoom, peerId) {
  if (
    epoch !== state.attemptEpoch ||
    state.room !== joinedRoom
  ) {
    const stale = joinedRoom.getPeers()[peerId];
    try { stale.close(); } catch (_error) {}
    return;
  }
  const reservation = state.negotiating.get(peerId);
  if (
    !reservation ||
    reservation.mode !== 'nostr' ||
    reservation.epoch !== epoch
  ) {
    const unproved = joinedRoom.getPeers()[peerId];
    try { unproved.close(); } catch (_error) {}
    return;
  }
  closeNegotiating(peerId);
  if (
    state.viewers.size + state.manualPending.size >=
    state.config.max_viewers
  ) {
    const excess = joinedRoom.getPeers()[peerId];
    try { excess.close(); } catch (_error) {}
    return;
  }
  const pc = joinedRoom.getPeers()[peerId];
  if (!pc) return;
  const entry = {
    mode: 'nostr',
    epoch,
    room: joinedRoom,
    stream: state.stream,
    pc,
    directConnected: false,
    mediaReady: false,
    telemetryHash: '',
    telemetrySentAt: -Infinity,
    forceTelemetry: true,
    transportTimer: setTimeout(
      () => closeViewer(peerId),
      TRANSPORT_DEADLINE_MS
    ),
    mediaTimer: setTimeout(
      () => closeViewer(peerId),
      MEDIA_DEADLINE_MS
    )
  };
  state.viewers.set(peerId, entry);
  monitorDirectPeer(peerId, entry);
  const sends = joinedRoom.addStream(state.stream, {
    target: peerId,
    metadata: {
      v: PROTOCOL_V2,
      role: 'host',
      generation: state.generation,
      fingerprint: state.config.host_fingerprint,
      host_public_key: state.config.host_public_key
    }
  });
  Promise.all(sends).catch(() => closeViewer(peerId));
  sendTelemetry(peerId);
  fanoutTelemetry(true);
  updateHealth();
}

function validMediaReady(value, peerId) {
  return Boolean(
    exactKeys(value, [
      'fingerprint', 'generation', 'sender', 'target', 'type', 'v'
    ]) &&
    value.v === PROTOCOL_V2 &&
    value.type === 'media-ready' &&
    value.generation === state.generation &&
    value.fingerprint === state.config.host_fingerprint &&
    value.sender === peerId &&
    value.target === RppTrysteroNostr.selfId
  );
}

function receiveMediaReady(value, context) {
  const peerId = context && context.peerId;
  const entry = state.viewers.get(peerId);
  if (
    !entry ||
    entry.mode !== 'nostr' ||
    !validMediaReady(value, peerId)
  ) return;
  entry.mediaReady = true;
  if (entry.mediaTimer) clearTimeout(entry.mediaTimer);
  entry.mediaTimer = null;
  updateHealth();
}

function updateRelayHealth(epoch = state.attemptEpoch, joinedRoom = state.room) {
  if (
    !joinedRoom ||
    state.room !== joinedRoom ||
    epoch !== state.attemptEpoch ||
    state.signaling !== 'nostr'
  ) return;
  let sockets = {};
  let relayHealth = {};
  try {
    sockets = RppTrysteroNostr.getRelaySockets();
    relayHealth = typeof RppTrysteroNostr.getRelayHealth === 'function'
      ? RppTrysteroNostr.getRelayHealth()
      : {};
  } catch (_error) {
    sockets = {};
    relayHealth = {};
  }
  const configured = state.config.relay_urls;
  state.relayTotal = configured.length;
  state.relayOpenCount = configured.filter(
    url => sockets[url] && sockets[url].readyState === 1
  ).length;
  state.relayQualifiedCount = configured.filter(
    url => relayHealth[url] && relayHealth[url].qualified === true
  ).length;
  state.peerOpen = state.relayQualifiedCount > 0;
  const now = monotonicNow();
  if (state.relayQualifiedCount > 0) {
    if (
      state.stream &&
      state.broadcastDesired &&
      ['connecting', 'reconnecting', 'error'].includes(state.streamState)
    ) {
      setStreamState(
        'live',
        'Automatic signaling qualified. Media and telemetry remain direct.'
      );
    }
    state.relayFailureStartedAt = null;
    if (state.relayAnnouncement) {
      state.relayAnnouncement = false;
      document.getElementById('host-message').textContent =
        'Automatic signaling recovered. Existing media remains direct.';
    }
  } else {
    if (state.relayFailureStartedAt === null) {
      state.relayFailureStartedAt = now;
    }
    if (
      now - state.relayFailureStartedAt >= ZERO_RELAY_DEADLINE_MS &&
      !state.relayAnnouncement
    ) {
      state.relayAnnouncement = true;
      document.getElementById('host-message').textContent =
        'Automatic signaling blocked; use Manual Share pairing';
    }
  }
  const shareStatus = document.getElementById('share-status');
  if (shareStatus) {
    shareStatus.textContent = automaticShareReady()
      ? 'Automatic spectator link is LIVE.'
      : 'Automatic link is not live; Manual Share health is separate.';
  }
  updateHealth();
}

function startNostrRoom(epoch) {
  if (
    !RppTrysteroNostr ||
    typeof RppTrysteroNostr.joinRoom !== 'function' ||
    typeof RppPairing !== 'object'
  ) throw new Error('nostr-runtime-unavailable');
  state.telemetryAction = null;
  state.mediaReadyAction = null;
  const joinedRoom = RppTrysteroNostr.joinRoom(
    {
      appId: NOSTR_APP_ID,
      password: state.config.room_key,
      passive: false,
      relayConfig: {
        urls: [...state.config.relay_urls],
        redundancy: state.config.relay_urls.length,
        warnOnRelayFailure: false
      },
      trickleIce: true,
      rtcConfig: state.config.rtc_config
    },
    state.config.room_id,
    {
      onPeerHandshake: (...args) => hostPeerHandshake(epoch, ...args),
      handshakeTimeoutMs: 10000,
      onJoinError: details => {
        const pending = state.negotiating.get(details.peerId);
        if (pending && pending.epoch === epoch) {
          closeNegotiating(details.peerId);
        }
        state.error = 'peer-handshake-rejected';
      }
    }
  );
  if (epoch !== state.attemptEpoch) {
    void joinedRoom.leave().catch(() => {});
    throw new Error('host attempt ended');
  }
  state.room = joinedRoom;
  state.telemetryAction = joinedRoom.makeAction('rpp-telemetry-v2');
  state.mediaReadyAction = joinedRoom.makeAction('rpp-media-ready-v2');
  state.mediaReadyAction.onMessage = receiveMediaReady;
  joinedRoom.onPeerJoin = peerId => admitNostrPeer(epoch, joinedRoom, peerId);
  joinedRoom.onPeerLeave = peerId => {
    closeNegotiating(peerId);
    const entry = state.viewers.get(peerId);
    if (entry) entry.leaving = true;
    closeViewer(peerId);
  };
  state.relayTotal = state.config.relay_urls.length;
  state.relayFailureStartedAt = monotonicNow();
  state.relayTimer = setInterval(
    () => updateRelayHealth(epoch, joinedRoom),
    1000
  );
  setStreamState(
    'connecting',
    'Media capture is ready; qualifying encrypted signaling round-trips.'
  );
  updateRelayHealth(epoch, joinedRoom);
}

let legacyPeerScriptPromise = null;
function loadLegacyPeerJs() {
  if (typeof Peer === 'function') return Promise.resolve();
  if (legacyPeerScriptPromise) return legacyPeerScriptPromise;
  legacyPeerScriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = './vendor/peerjs-1.5.5.runtime.min.js';
    script.onload = resolve;
    script.onerror = () => reject(new Error('legacy PeerJS asset failed'));
    document.head.appendChild(script);
  });
  return legacyPeerScriptPromise;
}

function manualJoinBase() {
  const url = new URL(state.config.join_url);
  url.hash = '';
  return url.toString();
}

function setManualStatus(message) {
  document.getElementById('manual-status').textContent = message;
}

function clearManualDisplay(pair = state.manualDisplayPair) {
  if (pair && state.manualDisplayPair !== pair) return;
  state.manualDisplayPair = '';
  document.getElementById('manual-offer').hidden = true;
  document.getElementById('manual-offer-text').value = '';
  manualShareButton.hidden = true;
}

function retireManualOffer(
  pair,
  reason,
  {close = true, clearDisplay = true} = {}
) {
  const pending = state.manualPending.get(pair);
  if (!pending) return false;
  state.manualPending.delete(pair);
  pending.used = true;
  if (pending.timer) clearTimeout(pending.timer);
  pending.timer = null;
  if (close) {
    try { pending.channel.close(); } catch (_error) {}
    try { pending.pc.close(); } catch (_error) {}
  }
  if (clearDisplay) clearManualDisplay(pair);
  if (reason) setManualStatus(reason);
  updateControls();
  return true;
}

function renderManualOffer(pending) {
  const container = document.getElementById('manual-offer');
  const text = document.getElementById('manual-offer-text');
  const canvas = document.getElementById('manual-offer-qr');
  text.value = pending.link;
  container.hidden = false;
  state.manualDisplayPair = pending.pair;
  manualShareButton.hidden = typeof navigator.share !== 'function';
  const note = document.getElementById('manual-qr-note');
  canvas.hidden = !pending.qrSafe;
  if (pending.qrSafe) {
    new QRious({
      element: canvas,
      value: pending.link,
      size: 320,
      level: 'M',
      background: 'white',
      foreground: 'black'
    });
    note.textContent =
      'Open or share this offer link with one viewer. The complete link was not truncated.';
  } else {
    note.textContent =
      'The complete uncompressed offer exceeds conservative QR capacity. Share or copy the full link; it was not truncated.';
  }
}

async function createManualPair() {
  if (
    !manualShareReady() ||
    state.viewers.size + state.negotiating.size + state.manualPending.size >=
      state.config.max_viewers
  ) return;
  const epoch = state.attemptEpoch;
  manualCreateButton.disabled = true;
  setManualStatus('Gathering complete direct ICE candidates…');
  const activeStream = state.stream;
  let creatingPc = null;
  try {
    const pending = await RppPairing.createManualOffer({
      stream: state.stream,
      room: state.config.room_id,
      key: state.config.room_key,
      generation: state.generation,
      fingerprint: state.config.host_fingerprint,
      hostPublicKey: state.config.host_public_key,
      hostPrivateJwk: state.config.host_private_jwk,
      callback: state.config.manual_callback,
      returnToken: state.config.manual_return_token,
      returnPage: state.config.manual_return_page,
      joinBase: manualJoinBase(),
      onPeerConnection: pc => {
        creatingPc = pc;
        state.manualCreating.add(pc);
      }
    });
    state.manualCreating.delete(creatingPc);
    if (
      state.ending ||
      epoch !== state.attemptEpoch ||
      state.stream !== activeStream ||
      !state.broadcastDesired
    ) {
      try { pending.channel.close(); } catch (_error) {}
      pending.pc.close();
      return;
    }
    const timeout = setTimeout(() => {
      const current = state.manualPending.get(pending.pair);
      if (current !== pending || pending.used) return;
      retireManualOffer(
        pending.pair,
        'The pending manual offer expired. Create a fresh one.'
      );
    }, Math.max(0, pending.expires * 1000 - Date.now()));
    pending.timer = timeout;
    state.manualPending.set(pending.pair, pending);
    renderManualOffer(pending);
    setManualStatus(
      'Manual Share offer ready. Share the link; it expires in five minutes and can be used once.'
    );
  } catch (error) {
    setManualStatus(`Could not create a manual offer: ${String(
      error && error.message || error
    ).slice(0, 120)}`);
  } finally {
    if (creatingPc) state.manualCreating.delete(creatingPc);
  }
  updateControls();
}

async function shareManualOffer() {
  const pending = state.manualPending.get(state.manualDisplayPair);
  if (!pending || typeof navigator.share !== 'function') return;
  try {
    await navigator.share({url: pending.link});
    setManualStatus('Manual Share offer opened in the system Share sheet.');
  } catch (error) {
    if (error && error.name === 'AbortError') {
      setManualStatus('Share canceled. Copy and QR remain available.');
    } else {
      setManualStatus('Share failed. Copy or use the complete QR link.');
    }
  }
}

function manualMediaReady(value, pair) {
  return Boolean(
    exactKeys(value, ['pair', 'type', 'v']) &&
    value.v === PROTOCOL_V2 &&
    value.type === 'media-ready' &&
    value.pair === pair
  );
}

async function importManualAnswerValue(text, source = 'paste') {
  if (typeof text !== 'string' || !text.trim()) {
    setManualStatus('Paste the complete viewer answer first.');
    return {ok: false, reason: 'empty'};
  }
  const input = document.getElementById('manual-answer-text');
  let decoded;
  try {
    decoded = RppPairing.decodeAnswerEnvelope(text.trim());
  } catch (error) {
    setManualStatus(String(error.message || error));
    return {ok: false, reason: 'envelope'};
  }
  const pair = decoded.envelope.pair;
  const pending = state.manualPending.get(pair);
  if (!pending || state.answerReplay.has(pair)) {
    setManualStatus('That answer has no live unused offer on this host.');
    return {ok: false, reason: 'offer'};
  }
  if (state.viewers.size >= state.config.max_viewers) {
    setManualStatus('Viewer capacity is full; this answer was not imported.');
    return {ok: false, reason: 'capacity'};
  }
  manualImportButton.disabled = true;
  try {
    await RppPairing.acceptManualAnswer(pending, text.trim());
    state.answerReplay.add(pair);
    retireManualOffer(pair, '', {close: false});
    const peerId = `manual:${pair}`;
    const entry = {
      mode: 'manual',
      pc: pending.pc,
      channel: pending.channel,
      directConnected: false,
      mediaReady: false,
      telemetryHash: '',
      telemetrySentAt: -Infinity,
      forceTelemetry: true,
      transportTimer: setTimeout(
        () => closeViewer(peerId),
        TRANSPORT_DEADLINE_MS
      ),
      mediaTimer: setTimeout(
        () => closeViewer(peerId),
        MEDIA_DEADLINE_MS
      )
    };
    state.viewers.set(peerId, entry);
    pending.channel.addEventListener('open', () => {
      if (state.viewers.get(peerId) !== entry) return;
      entry.directConnected = true;
      if (entry.transportTimer) clearTimeout(entry.transportTimer);
      entry.transportTimer = null;
      void recordCandidateType(pending.pc);
      sendTelemetry(peerId);
      updateHealth();
    });
    pending.channel.addEventListener('message', event => {
      if (
        state.viewers.get(peerId) !== entry ||
        typeof event.data !== 'string' ||
        byteLength(event.data) > 1024
      ) return;
      try {
        if (!manualMediaReady(JSON.parse(event.data), pair)) return;
      } catch (_error) {
        return;
      }
      entry.mediaReady = true;
      if (entry.mediaTimer) clearTimeout(entry.mediaTimer);
      entry.mediaTimer = null;
      updateHealth();
    });
    pending.channel.addEventListener('close', () => closeViewer(peerId));
    pending.channel.addEventListener('error', () => closeViewer(peerId));
    pending.pc.addEventListener('connectionstatechange', () => {
      if (['failed', 'closed'].includes(pending.pc.connectionState)) {
        closeViewer(peerId);
      }
    });
    input.value = '';
    setManualStatus(
      source === 'return'
        ? 'Shared answer delivered. Direct media is connecting.'
        : 'Answer accepted. Direct media is connecting.'
    );
    if (pending.channel.readyState === 'open') {
      entry.directConnected = true;
      if (entry.transportTimer) clearTimeout(entry.transportTimer);
      entry.transportTimer = null;
      void recordCandidateType(pending.pc);
      sendTelemetry(peerId);
    }
    fanoutTelemetry(true);
    return {ok: true, reason: 'accepted'};
  } catch (error) {
    if (pending.used) {
      retireManualOffer(
        pair,
        'That manual offer ended. Create a fresh offer.',
        {close: true}
      );
    }
    setManualStatus(`Answer rejected: ${String(
      error && error.message || error
    ).slice(0, 120)}`);
    return {
      ok: false,
      reason: pending.used ? 'terminal' : 'rejected'
    };
  } finally {
    manualImportButton.disabled = false;
    updateHealth();
  }
}

async function importManualAnswer() {
  const input = document.getElementById('manual-answer-text');
  await importManualAnswerValue(input.value, 'paste');
}

function queueRoomDisposal(room) {
  const previous = state.teardownPromise.catch(() => false);
  const disposal = previous.then(async () => {
    if (!room) return true;
    try {
      await room.leave();
      return true;
    } catch (_error) {
      return false;
    }
  });
  state.teardownPromise = disposal;
  return disposal;
}

function teardownBroadcast(
  message = 'Livestream ended.',
  nextState = 'offline',
  manual = false
) {
  state.attemptEpoch += 1;
  state.manuallyStopped = manual || !state.broadcastDesired;
  state.starting = false;
  for (const entry of state.negotiating.values()) {
    if (entry.timer) clearTimeout(entry.timer);
    if (entry.connection) {
      try { entry.connection.close(); } catch (_error) {}
    }
  }
  state.negotiating.clear();
  for (const peerId of [...state.viewers.keys()]) closeViewer(peerId);
  for (const pair of [...state.manualPending.keys()]) {
    retireManualOffer(pair, '', {close: true, clearDisplay: true});
  }
  for (const pc of state.manualCreating) {
    try { pc.close(); } catch (_error) {}
  }
  state.manualCreating.clear();
  if (state.relayTimer) clearInterval(state.relayTimer);
  state.relayTimer = null;
  const room = state.room;
  state.room = null;
  state.telemetryAction = null;
  state.mediaReadyAction = null;
  const peer = state.peer;
  state.peer = null;
  state.peerOpen = false;
  state.relayOpenCount = 0;
  state.relayQualifiedCount = 0;
  state.relayFailureStartedAt = null;
  state.relayAnnouncement = false;
  state.relayTotal = state.signaling === 'nostr'
    ? (state.config ? state.config.relay_urls.length : 5)
    : 0;
  if (peer) {
    try { peer.destroy(); } catch (_error) {}
  }
  const stream = state.stream;
  state.stream = null;
  cleanupPiP();
  if (stream) {
    for (const track of stream.getTracks()) {
      try { track.stop(); } catch (_error) {}
    }
  }
  setStreamState(nextState, message);
  const disposal = queueRoomDisposal(room);
  disposal.then(ok => {
    state.leaveFailed = !ok;
  });
  return disposal;
}

function safeHostReset() {
  if (globalThis.location && typeof location.reload === 'function') {
    location.reload();
  }
}

function viewerPeerFromError(error) {
  const direct = [error && error.peer, error && error.peerId]
    .find(value => typeof value === 'string');
  if (direct) return direct;
  const message = error && error.message;
  if (typeof message !== 'string') return null;
  return [...state.viewers.keys(), ...state.negotiating.keys()]
    .find(peerId => message === `Could not connect to peer ${peerId}`) || null;
}

function handlePeerError(error, activePeer) {
  if (state.peer !== activePeer) return;
  if (['peer-unavailable', 'webrtc'].includes(error && error.type)) {
    const peerId = viewerPeerFromError(error);
    if (peerId) {
      if (state.viewers.has(peerId)) closeViewer(peerId);
      const negotiating = state.negotiating.get(peerId);
      if (negotiating) {
        cleanupNegotiating(peerId, negotiating.connection);
        rejectConnection(negotiating.connection, 'media-failed');
      }
    }
    return;
  }
  state.error = String(error && error.type || 'peer-error').slice(0, 80);
  void teardownBroadcast('PeerJS failed. Select Retry.', 'error');
}

async function startBroadcast() {
  if (
    !state.config ||
    !state.broadcastDesired ||
    state.peer ||
    state.room ||
    state.stream ||
    state.starting ||
    !state.firstFrame ||
    !stringHealthy() ||
    !sourceHealthy()
  ) return;
  if (typeof game.captureStream !== 'function') {
    state.error = 'browser-incompatible';
    setStreamState('error', 'This browser cannot host the canvas stream.');
    return;
  }
  const epoch = state.attemptEpoch + 1;
  state.attemptEpoch = epoch;
  state.manuallyStopped = false;
  state.starting = true;
  setStreamState(
    'connecting',
    state.signaling === 'nostr'
      ? 'Opening encrypted Nostr signaling relays…'
      : 'Opening the legacy PeerJS host…'
  );
  try {
    const disposed = await state.teardownPromise;
    if (
      !disposed ||
      state.leaveFailed ||
      epoch !== state.attemptEpoch ||
      state.ending ||
      !state.broadcastDesired
    ) {
      state.starting = false;
      if (!disposed || state.leaveFailed) safeHostReset();
      return;
    }
    if (
      state.signaling === 'nostr' &&
      (
        typeof RppPairing !== 'object' ||
        await RppPairing.deriveHostFingerprint(
          state.config.host_public_key,
          state.generation
        ) !== state.config.host_fingerprint ||
        !await RppPairing.verifyPrivateKeyBinding(
          state.config.host_private_jwk,
          state.config.host_public_key
        )
      )
    ) throw new Error('host fingerprint mismatch');
    if (
      epoch !== state.attemptEpoch ||
      state.ending ||
      !state.broadcastDesired
    ) {
      state.starting = false;
      return;
    }
    state.identityReady = true;
    state.stream = game.captureStream(state.config.frame_rate);
    attachPiP(state.stream);
    for (const track of state.stream.getTracks()) {
      track.addEventListener('ended', () => {
        if (state.stream) {
          void teardownBroadcast(
            'Canvas capture ended. Select Retry.',
            'error'
          );
        }
      }, {once: true});
    }
    if (state.signaling === 'nostr') {
      startNostrRoom(epoch);
      state.starting = false;
      state.error = '';
      updateHealth();
      return;
    }
    if (typeof Peer !== 'function') await loadLegacyPeerJs();
    if (
      epoch !== state.attemptEpoch ||
      state.ending ||
      !state.broadcastDesired
    ) {
      state.starting = false;
      return;
    }
    state.peer = new Peer(state.config.peer_id, state.config.peer_options);
  } catch (error) {
    if (epoch !== state.attemptEpoch || state.ending) return;
    state.error = state.signaling === 'nostr'
      ? 'nostr-initialization'
      : 'peer-initialization';
    if (state.signaling === 'nostr' && state.stream) {
      state.starting = false;
      state.peerOpen = false;
      if (state.relayTimer) clearInterval(state.relayTimer);
      state.relayTimer = null;
      const failedRoom = state.room;
      state.room = null;
      state.telemetryAction = null;
      state.mediaReadyAction = null;
      const disposed = await queueRoomDisposal(failedRoom);
      state.leaveFailed = !disposed;
      if (epoch !== state.attemptEpoch || state.ending) return;
      setStreamState(
        'error',
        'Automatic signaling is unavailable. Manual Share is separate and ready; Retry can reopen relays.'
      );
    } else {
      await teardownBroadcast(
        'Could not initialize legacy PeerJS. Select Retry.',
        'error'
      );
    }
    return;
  }
  const activePeer = state.peer;
  state.starting = false;
  activePeer.on('open', openedId => {
    if (
      epoch !== state.attemptEpoch ||
      state.peer !== activePeer ||
      openedId !== state.config.peer_id
    ) return;
    state.peerOpen = true;
    state.error = '';
    setStreamState('live', 'Live and ready for spectators.');
  });
  activePeer.on('connection', connection => {
    if (epoch === state.attemptEpoch && state.peer === activePeer) {
      acceptDataConnection(connection);
    }
    else connection.close();
  });
  activePeer.on('call', call => call.close());
  activePeer.on('disconnected', () => {
    if (state.peer !== activePeer || state.manuallyStopped) return;
    state.peerOpen = false;
    setStreamState('reconnecting', 'PeerJS signaling disconnected; reconnecting…');
    try {
      activePeer.reconnect();
    } catch (_error) {
      void teardownBroadcast(
        'Signaling reconnection failed. Select Retry.',
        'error'
      );
    }
  });
  activePeer.on('error', error => handlePeerError(error, activePeer));
  activePeer.on('close', () => {
    if (state.peer === activePeer && !state.ending) {
      void teardownBroadcast('PeerJS closed. Select Retry.', 'error');
    }
  });
}

async function applyBroadcastIntent(desired, sequence, retry = false) {
  if (
    typeof desired !== 'boolean' ||
    !boundedInteger(sequence, 0, Number.MAX_SAFE_INTEGER) ||
    sequence <= state.broadcastSequence
  ) return {ok: false, reason: 'sequence-or-schema'};
  state.broadcastDesired = desired;
  state.broadcastSequence = sequence;
  state.manuallyStopped = !desired;
  if (!desired) {
    await teardownBroadcast('Livestream ended locally.', 'offline', true);
  } else {
    if (retry) {
      const disposed = await teardownBroadcast('Retrying…', 'ready');
      if (!disposed || state.leaveFailed) {
        safeHostReset();
        return {ok: true, sequence, desired, reset: true};
      }
    }
    else if (!state.peer && !state.room && !state.stream) {
      setStreamState('ready', 'Broadcast requested; checking source health.');
    }
    await startBroadcast();
  }
  updateHealth();
  return {ok: true, sequence, desired};
}

function receiveBroadcast(value) {
  if (!validEnvelope(value, ['desired'])) {
    return {ok: false, reason: 'sequence-or-schema'};
  }
  return applyBroadcastIntent(value.desired, value.sequence);
}

function localBroadcastIntent(desired, retry = false) {
  if (state.broadcastSequence >= Number.MAX_SAFE_INTEGER) return;
  void applyBroadcastIntent(desired, state.broadcastSequence + 1, retry);
}

async function shutdown(value) {
  if (
    !validEnvelope(value, []) ||
    value.sequence <= state.shutdownSequence
  ) return {ok: false, reason: 'sequence-or-schema'};
  state.shutdownSequence = value.sequence;
  state.ending = true;
  state.runtimeState = 'stopping';
  await teardownBroadcast('The local string shut down.', 'stopped', true);
  return {ok: true, sequence: value.sequence};
}

async function receiveManualAnswer(value) {
  if (
    !exactKeys(value, ['answer', 'generation']) ||
    value.generation !== state.generation ||
    typeof value.answer !== 'string' ||
    new TextEncoder().encode(value.answer).byteLength >
      RppPairing.MAX_ANSWER_TEXT_BYTES
  ) return {ok: false, reason: 'schema'};
  return importManualAnswerValue(value.answer, 'return');
}

function publicStatus() {
  updateHealth();
  const directCount = [...state.viewers.values()].filter(
    entry => entry.directConnected
  ).length;
  const mediaReadyCount = [...state.viewers.values()].filter(
    entry => entry.mediaReady
  ).length;
  return {
    version: VERSION,
    build: BUILD,
    instance: state.instance.slice(0, 64),
    generation: state.generation.slice(0, 128),
    bootstrapped: Boolean(state.config),
    state: state.streamState,
    viewer_count: Math.min(8, state.viewers.size),
    max_viewers: state.config ? state.config.max_viewers : 0,
    peer_open: state.peerOpen,
    first_frame: state.firstFrame,
    share_ready: shareReady(),
    automatic_share_ready: automaticShareReady(),
    manual_share_ready: manualShareReady(),
    source_health: sourceHealthy() ? 'ok' : 'lost',
    string_health: stringHealthy() ? 'ok' : 'lost',
    runtime_health: state.runtimeState,
    peer_health: state.peerOpen ? 'open' : 'offline',
    signaling: state.signaling,
    relay_health: state.signaling === 'nostr'
      ? (
        state.relayQualifiedCount
          ? 'qualified'
          : (state.relayOpenCount ? 'unqualified' : 'blocked')
      )
      : (state.peerOpen ? 'open' : 'offline'),
    relay_open_count: state.relayOpenCount,
    relay_qualified_count: state.relayQualifiedCount,
    relay_total: state.relayTotal,
    direct_health: directCount
      ? 'connected'
      : (state.viewers.size ? 'connecting' : 'idle'),
    direct_peer_count: directCount,
    media_ready_count: mediaReadyCount,
    candidate_types: [...state.candidateTypes].sort(),
    frame_attempted_sequence: state.frameAttemptedSequence,
    frame_attempted_hash: state.frameAttemptedHash,
    frame_sequence: state.frameDrawnSequence,
    frame_hash: state.frameDrawnHash,
    source_sequence: state.sourceSequence,
    source_hash: state.sourceHash,
    telemetry_sequence: state.telemetrySequence,
    heartbeat_sequence: state.heartbeatSequence,
    broadcast_desired: state.broadcastDesired,
    broadcast_sequence: state.broadcastSequence,
    error: state.error.slice(0, 80)
  };
}

const ingress = Object.freeze({
  version: VERSION,
  build: BUILD,
  bootstrap,
  frame: receiveFrame,
  telemetry: receiveTelemetry,
  heartbeat: receiveHeartbeat,
  broadcast: receiveBroadcast,
  manualAnswer: receiveManualAnswer,
  shutdown,
  status: publicStatus
});
Object.defineProperty(window, '__RPP_KITE_HOST_V2__', {
  value: ingress,
  configurable: false,
  enumerable: false,
  writable: false
});

goButton.addEventListener('click', () => localBroadcastIntent(true));
endButton.addEventListener('click', () => localBroadcastIntent(false));
retryButton.addEventListener('click', () => localBroadcastIntent(true, true));
pipButton.addEventListener('click', togglePiP);
for (const eventName of [
  'loadedmetadata', 'canplay', 'playing',
  'enterpictureinpicture', 'leavepictureinpicture',
  'webkitpresentationmodechanged'
]) {
  pipVideo.addEventListener(eventName, updatePiP);
}
copyButton.addEventListener('click', async () => {
  if (!state.config) return;
  try {
    await navigator.clipboard.writeText(state.config.join_url);
    document.getElementById('host-message').textContent =
      'Spectator link copied.';
  } catch (_error) {
    document.getElementById('host-message').textContent =
      'Copy failed; use the spectator link beside the QR code.';
  }
});
manualCreateButton.addEventListener('click', createManualPair);
manualShareButton.addEventListener('click', shareManualOffer);
manualCopyButton.addEventListener('click', async () => {
  const value = document.getElementById('manual-offer-text').value;
  if (!value) return;
  try {
    await navigator.clipboard.writeText(value);
    setManualStatus('Complete manual offer link copied.');
  } catch (_error) {
    setManualStatus('Copy failed. Select and copy the complete offer text.');
  }
});
manualImportButton.addEventListener('click', importManualAnswer);
function handlePageExit() {
  if (state.ending) return;
  state.ending = true;
  void teardownBroadcast('Host page closed.', 'stopped', true);
}
window.addEventListener('pagehide', handlePageExit);
window.addEventListener('beforeunload', handlePageExit);
setInterval(() => {
  updateHealth();
  fanoutTelemetry();
}, 1000);
updateHealth();
})();
