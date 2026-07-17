
(() => {
'use strict';

const BUILD = 'rpp-kite-host-v1';
const VERSION = 1;
const MAX_FRAME_BYTES = 128 * 1024;
const WIDTH = 160;
const HEIGHT = 144;
const STRING_LOST_MS = 5000;
const SOURCE_LOST_MS = 3000;
const TEARDOWN_GRACE_MS = 12000;
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
  if (params.get('v') !== '1') return null;
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
  stream: null,
  viewers: new Map(),
  negotiating: new Map(),
  streamState: 'untethered',
  peerOpen: false,
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

function shareReady() {
  return Boolean(
    state.config &&
    state.broadcastDesired &&
    state.peerOpen &&
    state.firstFrame &&
    stringHealthy() &&
    sourceHealthy() &&
    state.streamState === 'live'
  );
}

function updateControls() {
  const ready = Boolean(
    state.config && state.firstFrame && stringHealthy() && sourceHealthy()
  );
  goButton.disabled = !ready || Boolean(state.peer) || state.starting;
  endButton.disabled = !state.peer && !state.stream && !state.starting;
  retryButton.disabled = !ready || state.starting;
  pipButton.disabled = !pictureInPictureSupported() ||
    (!pictureInPictureReady() && !pictureInPictureActive());
  copyButton.disabled = !state.config;
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
  const peerLabel = state.peerOpen
    ? 'OPEN'
    : (state.starting ? 'CONNECTING' : 'OFFLINE');
  healthValue('peer-health', peerLabel, state.peerOpen);
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
    (state.peer || state.stream)
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
  if (!exactKeys(value, [
    'broadcast_desired', 'broadcast_sequence', 'build', 'frame_rate',
    'generation', 'instance', 'join_url', 'max_hello_bytes',
    'max_negotiating', 'max_telemetry_bytes', 'max_viewers', 'peer_id',
    'peer_options', 'protocol_version', 'telemetry_version',
    'watch_capability'
  ])) return false;
  return (
    selector !== null &&
    value.build === BUILD &&
    value.instance === selector &&
    /^[A-Za-z0-9_-]{16,128}$/.test(value.generation || '') &&
    /^rpp-[a-f0-9]{32}$/.test(value.peer_id || '') &&
    /^[A-Za-z0-9_-]{32,128}$/.test(value.watch_capability || '') &&
    value.protocol_version === VERSION &&
    value.telemetry_version === VERSION &&
    typeof value.broadcast_desired === 'boolean' &&
    boundedInteger(
      value.broadcast_sequence,
      0,
      Number.MAX_SAFE_INTEGER
    ) &&
    value.frame_rate === 10 &&
    value.max_hello_bytes === 512 &&
    boundedInteger(value.max_viewers, 1, 8) &&
    boundedInteger(value.max_negotiating, 2, 16) &&
    value.max_telemetry_bytes === 4096 &&
    validPeerOptions(value.peer_options) &&
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
  share.hidden = false;
  link.href = state.config.join_url;
  link.textContent = state.config.join_url;
  try {
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
  state.generation = value.generation;
  state.instance = value.instance;
  state.broadcastDesired = value.broadcast_desired;
  state.broadcastSequence = value.broadcast_sequence;
  state.manuallyStopped = !value.broadcast_desired;
  state.runtimeState = 'starting';
  document.getElementById('viewer-limit').textContent =
    String(value.max_viewers);
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
    !entry.connection.open ||
    !snapshot ||
    connectionBackpressured(entry.connection)
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
    entry.connection.send(message);
  } catch (_error) {
    closeViewer(peerId);
    return;
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
      connection.send({v: VERSION, type: 'reject', reason});
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
  try { entry.call.close(); } catch (_error) {}
  try { entry.connection.close(); } catch (_error) {}
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
      connection,
      call,
      mediaTimer: null,
      telemetryHash: '',
      telemetrySentAt: -Infinity,
      forceTelemetry: true
    });
    try {
      connection.send({v: VERSION, type: 'ready'});
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

function teardownBroadcast(
  message = 'Livestream ended.',
  nextState = 'offline',
  manual = false
) {
  state.manuallyStopped = manual || !state.broadcastDesired;
  state.starting = false;
  for (const entry of state.negotiating.values()) {
    if (entry.timer) clearTimeout(entry.timer);
    try { entry.connection.close(); } catch (_error) {}
  }
  state.negotiating.clear();
  for (const peerId of [...state.viewers.keys()]) closeViewer(peerId);
  const peer = state.peer;
  state.peer = null;
  state.peerOpen = false;
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
  teardownBroadcast('PeerJS failed. Select Retry.', 'error');
}

function startBroadcast() {
  if (
    !state.config ||
    !state.broadcastDesired ||
    state.peer ||
    state.starting ||
    !state.firstFrame ||
    !stringHealthy() ||
    !sourceHealthy()
  ) return;
  if (typeof Peer !== 'function' || typeof game.captureStream !== 'function') {
    state.error = 'browser-incompatible';
    setStreamState('error', 'This browser cannot host the canvas stream.');
    return;
  }
  state.manuallyStopped = false;
  state.starting = true;
  setStreamState('connecting', 'Opening the PeerJS host…');
  try {
    state.stream = game.captureStream(state.config.frame_rate);
    attachPiP(state.stream);
    for (const track of state.stream.getTracks()) {
      track.addEventListener('ended', () => {
        if (state.stream) {
          teardownBroadcast('Canvas capture ended. Select Retry.', 'error');
        }
      }, {once: true});
    }
    state.peer = new Peer(state.config.peer_id, state.config.peer_options);
  } catch (_error) {
    state.error = 'peer-initialization';
    teardownBroadcast('Could not initialize PeerJS. Select Retry.', 'error');
    return;
  }
  const activePeer = state.peer;
  state.starting = false;
  activePeer.on('open', openedId => {
    if (state.peer !== activePeer || openedId !== state.config.peer_id) return;
    state.peerOpen = true;
    state.error = '';
    setStreamState('live', 'Live and ready for spectators.');
  });
  activePeer.on('connection', connection => {
    if (state.peer === activePeer) acceptDataConnection(connection);
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
      teardownBroadcast('Signaling reconnection failed. Select Retry.', 'error');
    }
  });
  activePeer.on('error', error => handlePeerError(error, activePeer));
  activePeer.on('close', () => {
    if (state.peer === activePeer && !state.ending) {
      teardownBroadcast('PeerJS closed. Select Retry.', 'error');
    }
  });
}

function applyBroadcastIntent(desired, sequence, retry = false) {
  if (
    typeof desired !== 'boolean' ||
    !boundedInteger(sequence, 0, Number.MAX_SAFE_INTEGER) ||
    sequence <= state.broadcastSequence
  ) return {ok: false, reason: 'sequence-or-schema'};
  state.broadcastDesired = desired;
  state.broadcastSequence = sequence;
  state.manuallyStopped = !desired;
  if (!desired) {
    teardownBroadcast('Livestream ended locally.', 'offline', true);
  } else {
    if (retry) teardownBroadcast('Retrying…', 'ready');
    else if (!state.peer && !state.stream) {
      setStreamState('ready', 'Broadcast requested; checking source health.');
    }
    startBroadcast();
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
  applyBroadcastIntent(desired, state.broadcastSequence + 1, retry);
}

function shutdown(value) {
  if (
    !validEnvelope(value, []) ||
    value.sequence <= state.shutdownSequence
  ) return {ok: false, reason: 'sequence-or-schema'};
  state.shutdownSequence = value.sequence;
  state.ending = true;
  state.runtimeState = 'stopping';
  teardownBroadcast('The local string shut down.', 'stopped', true);
  return {ok: true, sequence: value.sequence};
}

function publicStatus() {
  updateHealth();
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
    source_health: sourceHealthy() ? 'ok' : 'lost',
    string_health: stringHealthy() ? 'ok' : 'lost',
    runtime_health: state.runtimeState,
    peer_health: state.peerOpen ? 'open' : 'offline',
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
  shutdown,
  status: publicStatus
});
Object.defineProperty(window, '__RPP_KITE_HOST_V1__', {
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
window.addEventListener('pagehide', () => {
  state.ending = true;
  teardownBroadcast('Host page closed.', 'stopped', true);
});
setInterval(() => {
  updateHealth();
  fanoutTelemetry();
}, 1000);
updateHealth();
})();
