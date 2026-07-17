
const video = document.getElementById('stream');
const overlay = document.getElementById('overlay');
const headline = document.getElementById('headline');
const detail = document.getElementById('detail');
const connectionLabel = document.getElementById('connection');
const spinner = document.getElementById('spinner');
const playButton = document.getElementById('play-stream');
const retryButton = document.getElementById('retry-stream');
const detailsBanner = document.getElementById('details-banner');
const detailsHealth = document.getElementById('details-health');
const videoHealth = document.getElementById('video-health');
const videoAnnouncer = document.getElementById('video-announcer');
const detailsAnnouncer = document.getElementById('details-announcer');
const MAX_AUTOMATIC_RETRIES = 6;
const NOSTR_APP_ID = 'rappter-plays-pokemon-v2';
const REVIEWED_RELAYS = Object.freeze([
  'wss://communities.nos.social',
  'wss://purplerelay.com',
  'wss://bucket.coracle.social',
  'wss://relay.nostr.place',
  'wss://relay.damus.io'
]);
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
const MAX_TELEMETRY_BYTES = 4096;
const TELEMETRY_STALE_MILLISECONDS = 12000;
const VIDEO_STALL_MILLISECONDS = 8000;
const HOST_AUTH_DEADLINE_MILLISECONDS = 15000;
const TRANSPORT_DEADLINE_MILLISECONDS = 15000;
const MEDIA_DEADLINE_MILLISECONDS = 30000;
let peer = null;
let room = null;
let telemetryAction = null;
let mediaReadyAction = null;
let manualPeer = null;
let manualChannel = null;
let manualPair = '';
let manualAnswerResult = null;
let acceptedHost = null;
let pendingHost = null;
let relayTimer = null;
let relayFailureStartedAt = null;
const candidateTypes = new Set();
let dataConnection = null;
let mediaConnection = null;
let retryTimer = null;
let retries = 0;
let reconnectAllowed = true;
let terminal = false;
let attemptEpoch = 0;
let cleanupPromise = Promise.resolve(true);
let leaveFailed = false;
let hostAuthTimer = null;
let transportTimer = null;
let mediaTimer = null;
let mediaReadySent = false;
let telemetrySequence = -1;
let telemetryReceivedAt = null;
let detailState = 'waiting';
let staleDetailContext = '';
let videoState = 'connecting';
let lastVideoTime = null;
let lastVideoProgressAt = null;

function monotonicNow() {
  return globalThis.performance.now();
}

function showState(
  state,
  title,
  message,
  {showPlay = false, showRetry = false, loading = true} = {}
) {
  const changed = videoState !== state;
  videoState = state;
  connectionLabel.textContent = state.toUpperCase();
  connectionLabel.className = 'connection' + (state === 'live' ? ' live' : '');
  headline.textContent = title;
  detail.textContent = message;
  playButton.hidden = !showPlay;
  retryButton.hidden = !showRetry;
  spinner.classList.toggle('hidden', !loading);
  videoHealth.textContent = (
    state === 'live' ? 'Live' :
    state === 'ready' ? 'Ready' :
    state === 'reconnecting' ? 'Reconnecting' :
    state === 'offline' ? 'Offline' :
    state === 'error' ? 'Unavailable' : 'Connecting'
  );
  if (state === 'live') overlay.classList.add('ready');
  else overlay.classList.remove('ready');
  if (changed) {
    const announcement = `${title}. ${message}`;
    if (videoAnnouncer.textContent !== announcement) {
      videoAnnouncer.textContent = announcement;
    }
  }
}

function parseCapability() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (
    params.get('v') === '2' &&
    params.get('mode') === 'manual-offer'
  ) {
    return {version: 2, mode: 'manual-offer', fragment: location.hash.slice(1)};
  }
  if (params.get('v') === '2') {
    return typeof RppPairing === 'object'
      ? RppPairing.parseAutoFragment(location.hash)
      : null;
  }
  if ([...params.keys()].sort().join(',') !== 'host,v,watch') return null;
  const version = Number(params.get('v'));
  const host = params.get('host') || '';
  const watch = params.get('watch') || '';
  if (
    version !== 1 ||
    !/^[A-Za-z0-9_-]{8,128}$/.test(host) ||
    !/^[A-Za-z0-9_-]{32,128}$/.test(watch)
  ) {
    return null;
  }
  return {version, mode: 'peerjs', host, watch};
}

const invitationFragment = location.hash;
const capability = parseCapability();
if (capability && globalThis.history && typeof history.replaceState === 'function') {
  history.replaceState(null, '', location.pathname);
}

function createSpectatorPeerId() {
  const prefix = 'rpp-viewer-';
  if (
    globalThis.crypto &&
    typeof globalThis.crypto.randomUUID === 'function'
  ) {
    return prefix + globalThis.crypto.randomUUID().replaceAll('-', '');
  }
  if (
    globalThis.crypto &&
    typeof globalThis.crypto.getRandomValues === 'function'
  ) {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
    return prefix + Array.from(
      bytes,
      value => value.toString(16).padStart(2, '0')
    ).join('');
  }
  return null;
}

function setDetailState(state, message) {
  const changed = detailState !== state;
  detailState = state;
  detailsBanner.textContent = message;
  if (changed && detailsAnnouncer.textContent !== message) {
    detailsAnnouncer.textContent = message;
  }
  detailsBanner.className = 'details-banner ' + (
    state === 'fresh' ? 'fresh' : 'delayed'
  );
  detailsHealth.textContent = (
    state === 'fresh' ? 'Live' :
    state === 'stale' ? 'Last known' : 'Waiting'
  );
}

function clearDashboard() {
  document.getElementById('location').textContent = 'Unknown';
  document.getElementById('objective').textContent = 'Unknown';
  document.getElementById('player-mode').textContent = 'Unknown';
  document.getElementById('badge-count').textContent = '— / 8 badges';
  for (const badge of document.querySelectorAll('[data-badge]')) {
    badge.classList.remove('earned');
    badge.textContent = badge.dataset.badge;
  }
  document.getElementById('caught-count').textContent = '—';
  document.getElementById('seen-count').textContent = '—';
  document.getElementById('completion').textContent = 'Unknown';
  renderParty(null);
  document.getElementById('play-time').textContent = 'Unknown';
  document.getElementById('session-time').textContent = 'Unknown';
  document.getElementById('checkpoint').textContent = 'Unknown';
  document.getElementById('viewers').textContent = '— / —';
}

function resetTelemetry(message = 'Waiting for live run details…') {
  telemetrySequence = -1;
  telemetryReceivedAt = null;
  staleDetailContext = '';
  clearDashboard();
  setDetailState('waiting', message);
}

function markTelemetryStale(context) {
  if (telemetryReceivedAt === null) {
    resetTelemetry('Waiting for live run details…');
    return;
  }
  staleDetailContext = context;
  const ageSeconds = Math.max(
    0,
    Math.floor((monotonicNow() - telemetryReceivedAt) / 1000)
  );
  setDetailState(
    'stale',
    `Last known run details — updated ${ageSeconds}s ago. ${context}`
  );
  detailsHealth.textContent = `Last known (${ageSeconds}s)`;
}

function clearPhaseTimers() {
  for (const timer of [hostAuthTimer, transportTimer, mediaTimer]) {
    if (timer) clearTimeout(timer);
  }
  hostAuthTimer = null;
  transportTimer = null;
  mediaTimer = null;
}

function queueRoomLeave(oldRoom) {
  const previous = cleanupPromise.catch(() => false);
  const leaving = previous.then(async () => {
    if (!oldRoom) return true;
    try {
      await oldRoom.leave();
      return true;
    } catch (_error) {
      return false;
    }
  });
  cleanupPromise = leaving;
  return leaving;
}

async function cleanup() {
  attemptEpoch += 1;
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  const oldMediaConnection = mediaConnection;
  const oldDataConnection = dataConnection;
  const oldPeer = peer;
  const oldRoom = room;
  const oldManualPeer = manualPeer;
  const oldManualChannel = manualChannel;
  mediaConnection = null;
  dataConnection = null;
  peer = null;
  room = null;
  telemetryAction = null;
  mediaReadyAction = null;
  manualPeer = null;
  manualChannel = null;
  manualPair = '';
  manualAnswerResult = null;
  acceptedHost = null;
  pendingHost = null;
  mediaReadySent = false;
  clearPhaseTimers();
  if (relayTimer) clearInterval(relayTimer);
  relayTimer = null;
  relayFailureStartedAt = null;
  if (oldMediaConnection) oldMediaConnection.close();
  if (oldDataConnection) oldDataConnection.close();
  if (oldPeer) oldPeer.destroy();
  if (oldManualChannel) {
    try { oldManualChannel.close(); } catch (_error) {}
  }
  if (oldManualPeer) {
    try { oldManualPeer.close(); } catch (_error) {}
  }
  video.srcObject = null;
  lastVideoTime = null;
  lastVideoProgressAt = null;
  resetTelemetry();
  const disposed = await queueRoomLeave(oldRoom);
  leaveFailed = !disposed;
  return disposed;
}

function safeViewerReset() {
  const destination = `${location.pathname}${invitationFragment}`;
  if (typeof location.replace === 'function') {
    location.replace(destination);
  } else if (typeof location.reload === 'function') {
    location.reload();
  }
}

async function scheduleRetryAsync(message) {
  if (!capability || retryTimer || !reconnectAllowed) return;
  if (capability.mode === 'manual-offer') {
    terminal = true;
    reconnectAllowed = false;
    await cleanup();
    showState(
      'offline',
      'Manual connection ended',
      'Ask the host for a fresh single-use Manual Share offer.',
      {loading: false}
    );
    return;
  }
  if (retries >= MAX_AUTOMATIC_RETRIES) {
    reconnectAllowed = false;
    await cleanup();
    showState(
      'offline',
      'Stream unavailable',
      capability.version === 2
        ? 'Host authentication or media timed out even with the TURN relay fallback. Ask for a fresh link or try Manual Share.'
        : 'Automatic retries ended. Ask the host for a fresh link.',
      {showRetry: true, loading: false}
    );
    if (capability.version === 2) {
      document.getElementById('manual-help').hidden = false;
    }
    return;
  }
  reconnectAllowed = false;
  const disposed = await cleanup();
  if (!disposed || leaveFailed) {
    safeViewerReset();
    return;
  }
  const retryEpoch = attemptEpoch;
  showState('reconnecting', 'Stream interrupted', message);
  const delay = Math.min(10000, 750 * (2 ** Math.min(retries, 4)));
  retries += 1;
  retryTimer = setTimeout(() => {
    if (terminal || retryEpoch !== attemptEpoch) return;
    retryTimer = null;
    reconnectAllowed = true;
    void connect();
  }, delay);
}

function scheduleRetry(message) {
  void scheduleRetryAsync(message);
}

async function attemptPlayback() {
  if (!video.srcObject) return;
  try {
    await video.play();
    retries = 0;
    if (video.readyState >= 2 && video.paused !== true) {
      markVideoPlaying();
    } else {
      showState('connecting', 'Video received', 'Waiting for playback…');
    }
  } catch (_error) {
    showState(
      'ready',
      'Stream ready',
      'Your browser blocked autoplay. Select Play Stream.',
      {showPlay: true, loading: false}
    );
    playButton.focus();
  }
}

async function sendMediaReady() {
  if (mediaReadySent || !video.srcObject) return;
  const tracks = typeof video.srcObject.getVideoTracks === 'function'
    ? video.srcObject.getVideoTracks()
    : video.srcObject.getTracks();
  if (
    Number(video.readyState) < 1 ||
    !tracks.some(track => !track.readyState || track.readyState === 'live')
  ) return;
  try {
    if (capability && capability.mode === 'manual-offer') {
      if (!manualChannel || manualChannel.readyState !== 'open') return;
      manualChannel.send(JSON.stringify({
        v: 2,
        type: 'media-ready',
        pair: manualPair
      }));
    } else {
      if (!mediaReadyAction || !acceptedHost) return;
      await mediaReadyAction.send({
        v: 2,
        type: 'media-ready',
        generation: capability.generation,
        fingerprint: capability.fingerprint,
        sender: RppTrysteroNostr.selfId,
        target: acceptedHost
      }, {target: acceptedHost});
    }
    mediaReadySent = true;
    if (mediaTimer) clearTimeout(mediaTimer);
    mediaTimer = null;
  } catch (_error) {
    // The bounded media deadline remains active and owns retry.
  }
}

function markVideoPlaying() {
  lastVideoTime = Number(video.currentTime) || 0;
  lastVideoProgressAt = monotonicNow();
  retries = 0;
  showState('live', 'Live', 'Receiving direct peer-to-peer video.', {
    loading: false
  });
  void sendMediaReady();
}

function markVideoInterrupted(title, message, health = 'Buffering') {
  if (!video.srcObject) return;
  showState('reconnecting', title, message, {loading: false});
  videoHealth.textContent = health;
}

function updateVideoHealth() {
  if (!video.srcObject) return;
  const currentTime = Number(video.currentTime);
  if (
    Number.isFinite(currentTime) &&
    (lastVideoTime === null || currentTime > lastVideoTime + 0.01)
  ) {
    lastVideoTime = currentTime;
    lastVideoProgressAt = monotonicNow();
    return;
  }
  if (
    videoState === 'live' &&
    lastVideoProgressAt !== null &&
    monotonicNow() - lastVideoProgressAt > VIDEO_STALL_MILLISECONDS
  ) {
    markVideoInterrupted(
      'Video stalled',
      'The video stopped advancing; waiting for fresh frames.',
      'Stalled'
    );
  }
}

video.addEventListener('playing', markVideoPlaying);
video.addEventListener('waiting', () => {
  markVideoInterrupted('Video buffering', 'Waiting for more video frames.');
});
video.addEventListener('stalled', () => {
  markVideoInterrupted(
    'Video stalled',
    'The browser is not receiving fresh video frames.',
    'Stalled'
  );
});
video.addEventListener('pause', () => {
  if (!video.srcObject) return;
  showState(
    'ready',
    'Video paused',
    'Select Play Stream to resume playback.',
    {showPlay: true, loading: false}
  );
  videoHealth.textContent = 'Paused';
});
video.addEventListener('error', () => {
  if (video.srcObject) scheduleRetry('Video playback failed. Retrying…');
});

function hasExactKeys(value, keys) {
  return (
    value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join(',') === [...keys].sort().join(',')
  );
}

function boundedInteger(value, minimum, maximum) {
  return Number.isInteger(value) && value >= minimum && value <= maximum;
}

function boundedText(value, maximum) {
  return value === null || (
    typeof value === 'string' && Array.from(value).length <= maximum
  );
}

function validSnapshot(value) {
  if (!hasExactKeys(value, [
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
  const badgeNames = [
    'Boulder', 'Cascade', 'Thunder', 'Rainbow',
    'Soul', 'Marsh', 'Volcano', 'Earth'
  ];
  if (
    !hasExactKeys(value.badges, ['earned', 'count', 'total']) ||
    !Array.isArray(value.badges.earned) ||
    value.badges.earned.some(name => !badgeNames.includes(name)) ||
    new Set(value.badges.earned).size !== value.badges.earned.length ||
    !(
      value.badges.count === null ||
      value.badges.count === value.badges.earned.length
    ) ||
    (value.badges.count === null && value.badges.earned.length !== 0) ||
    value.badges.total !== 8
  ) return false;
  if (
    !hasExactKeys(value.pokedex, ['caught', 'seen', 'total']) ||
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
    if (!hasExactKeys(member, ['nickname', 'species_id', 'level', 'hp', 'max_hp'])) {
      return false;
    }
    if (
      !boundedText(member.nickname, 24) ||
      !(member.species_id === null || boundedInteger(member.species_id, 1, 255)) ||
      !(member.level === null || boundedInteger(member.level, 1, 100)) ||
      !(member.hp === null || boundedInteger(member.hp, 0, 65535)) ||
      !(member.max_hp === null || boundedInteger(member.max_hp, 1, 65535)) ||
      (
        member.hp !== null &&
        member.max_hp !== null &&
        member.hp > member.max_hp
      )
    ) return false;
  }
  if (
    !hasExactKeys(value.player, ['mode', 'paused']) ||
    !['ai', 'manual', 'paused', 'unknown'].includes(value.player.mode) ||
    typeof value.player.paused !== 'boolean'
  ) return false;
  if (value.play_time !== null) {
    if (!hasExactKeys(
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
    if (!hasExactKeys(
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
    hasExactKeys(value.viewers, ['count', 'capacity']) &&
    boundedInteger(value.viewers.count, 0, 8) &&
    boundedInteger(value.viewers.capacity, 0, 8) &&
    value.viewers.count <= value.viewers.capacity
  );
}

function validTelemetry(value) {
  if (!hasExactKeys(
    value,
    ['v', 'type', 'telemetry_version', 'sequence', 'snapshot']
  )) return false;
  if (
    value.v !== capability.version ||
    value.type !== 'telemetry' ||
    value.telemetry_version !== 1 ||
    !Number.isSafeInteger(value.sequence) ||
    value.sequence < 0
  ) return false;
  let bytes;
  try {
    bytes = new TextEncoder().encode(JSON.stringify(value)).byteLength;
  } catch (_error) {
    return false;
  }
  return bytes <= MAX_TELEMETRY_BYTES && validSnapshot(value.snapshot);
}

function textOrUnknown(value) {
  return typeof value === 'string' && value ? value : 'Unknown';
}

function formatElapsed(total) {
  if (!boundedInteger(total, 0, 316224000)) return 'Unknown';
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function formatAge(total) {
  if (!boundedInteger(total, 0, 316224000)) return 'time unknown';
  if (total < 60) return 'just now';
  if (total < 3600) return `${Math.floor(total / 60)}m ago`;
  if (total < 86400) return `${Math.floor(total / 3600)}h ago`;
  return `${Math.floor(total / 86400)}d ago`;
}

function formatPlayTime(value) {
  if (value === null) return 'Unknown';
  const formatted = (
    String(value.hours) + ':' +
    String(value.minutes).padStart(2, '0') + ':' +
    String(value.seconds).padStart(2, '0')
  );
  return value.maxed ? formatted + ' (maximum)' : formatted;
}

function renderParty(party) {
  const list = document.getElementById('party-list');
  list.replaceChildren();
  if (party === null) {
    const empty = document.createElement('li');
    empty.className = 'empty';
    empty.textContent = 'Party unavailable.';
    list.appendChild(empty);
    return;
  }
  if (!party.length) {
    const empty = document.createElement('li');
    empty.className = 'empty';
    empty.textContent = 'No Pokemon in party.';
    list.appendChild(empty);
    return;
  }
  for (const member of party) {
    const item = document.createElement('li');
    item.className = 'party-member';
    const name = document.createElement('span');
    name.className = 'party-name';
    name.textContent = (
      member.nickname ||
      (member.species_id === null ? 'Unknown Pokemon' : `Species #${member.species_id}`)
    );
    const level = document.createElement('span');
    level.className = 'party-level';
    level.textContent = member.level === null ? 'Lv. —' : `Lv. ${member.level}`;
    const meter = document.createElement('progress');
    meter.className = 'party-hp';
    const hpKnown = member.hp !== null && member.max_hp !== null;
    meter.max = hpKnown ? member.max_hp : 1;
    meter.value = hpKnown ? member.hp : 0;
    if (hpKnown && member.max_hp > 0 && member.hp / member.max_hp <= .25) {
      meter.classList.add('low');
    }
    meter.setAttribute(
      'aria-label',
      hpKnown ? `${name.textContent} HP ${member.hp} of ${member.max_hp}` :
        `${name.textContent} HP unknown`
    );
    const hp = document.createElement('span');
    hp.className = 'party-hp-text';
    hp.textContent = hpKnown ? `${member.hp} / ${member.max_hp} HP` : 'HP unknown';
    item.appendChild(name);
    item.appendChild(level);
    item.appendChild(meter);
    item.appendChild(hp);
    list.appendChild(item);
  }
}

function renderSnapshot(snapshot) {
  document.getElementById('location').textContent = textOrUnknown(snapshot.location);
  const objective = textOrUnknown(snapshot.objective);
  document.getElementById('objective').textContent = snapshot.phase
    ? `${objective} · ${snapshot.phase}`
    : objective;
  const modeLabels = {
    ai: 'Copilot playing',
    manual: 'Host takeover',
    paused: 'Paused',
    unknown: 'Unknown'
  };
  document.getElementById('player-mode').textContent = snapshot.player.paused
    ? 'Paused'
    : modeLabels[snapshot.player.mode];
  const earned = new Set(snapshot.badges.earned);
  for (const badge of document.querySelectorAll('[data-badge]')) {
    const isEarned = earned.has(badge.dataset.badge);
    badge.classList.toggle('earned', isEarned);
    badge.textContent = badge.dataset.badge + (isEarned ? ' ✓' : '');
  }
  document.getElementById('badge-count').textContent =
    `${snapshot.badges.count === null ? '—' : snapshot.badges.count} / 8 badges`;
  document.getElementById('caught-count').textContent =
    snapshot.pokedex.caught === null ? '—' : String(snapshot.pokedex.caught);
  document.getElementById('seen-count').textContent =
    snapshot.pokedex.seen === null ? '—' : String(snapshot.pokedex.seen);
  document.getElementById('completion').textContent =
    snapshot.completed ? 'Completed' : 'Not yet';
  renderParty(snapshot.party);
  document.getElementById('play-time').textContent =
    formatPlayTime(snapshot.play_time);
  document.getElementById('session-time').textContent =
    formatElapsed(snapshot.session_elapsed_seconds);
  if (snapshot.checkpoint === null) {
    document.getElementById('checkpoint').textContent = 'None this session';
  } else {
    const kindLabels = {
      manual: 'Manual',
      milestone: 'Milestone',
      automatic: 'Automatic',
      shutdown: 'Shutdown save',
      recovery: 'Recovered',
      progress: 'Progress',
      other: 'Checkpoint'
    };
    const parts = [
      kindLabels[snapshot.checkpoint.kind],
      snapshot.checkpoint.location,
      formatAge(snapshot.checkpoint.age_seconds)
    ].filter(Boolean);
    document.getElementById('checkpoint').textContent = parts.join(' · ');
  }
  document.getElementById('viewers').textContent =
    `${snapshot.viewers.count} / ${snapshot.viewers.capacity}`;
}

function acceptTelemetry(value) {
  if (!validTelemetry(value) || value.sequence <= telemetrySequence) return false;
  telemetrySequence = value.sequence;
  telemetryReceivedAt = monotonicNow();
  staleDetailContext = '';
  renderSnapshot(value.snapshot);
  setDetailState('fresh', 'Live run details are up to date.');
  return true;
}

async function retryNow() {
  if (capability && capability.mode === 'manual-offer') {
    terminal = true;
    await cleanup();
    showState(
      'offline',
      'Fresh offer required',
      'Manual offers are single-use. Ask the host to create a new Manual Share link.',
      {loading: false}
    );
    return;
  }
  retries = 0;
  reconnectAllowed = true;
  terminal = false;
  const disposed = await cleanup();
  if (!disposed || leaveFailed) {
    safeViewerReset();
    return;
  }
  reconnectAllowed = true;
  await connect();
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

async function connectLegacy(epoch) {
  if (!capability || capability.mode !== 'peerjs') {
    showState(
      'error',
      'Invalid or unsupported link',
      'Ask the host for a fresh join link.',
      {loading: false}
    );
    return;
  }
  if (typeof Peer !== 'function') {
    try {
      await loadLegacyPeerJs();
    } catch (_error) {
      scheduleRetry('Could not load the legacy PeerJS fallback. Retrying…');
      return;
    }
    if (epoch !== attemptEpoch || terminal) return;
  }
  const spectatorPeerId = createSpectatorPeerId();
  if (!spectatorPeerId) {
    showState(
      'error',
      'Secure connection unavailable',
      'This browser cannot create a private spectator identity.',
      {loading: false}
    );
    return;
  }
  reconnectAllowed = true;
  showState('connecting', 'Joining livestream…', 'Connecting through PeerJS signaling.');
  try {
    const activePeer = new Peer(spectatorPeerId, {
      host: '0.peerjs.com',
      port: 443,
      path: '/',
      secure: true,
      debug: 0,
      config: {
        iceServers: RTC_CONFIG.iceServers.map(server => ({
          ...server,
          urls: Array.isArray(server.urls) ? [...server.urls] : server.urls
        }))
      }
    });
    if (epoch !== attemptEpoch || terminal) {
      activePeer.destroy();
      return;
    }
    peer = activePeer;
  } catch (_error) {
    scheduleRetry('Could not initialize PeerJS. Retrying…');
    return;
  }
  peer.on('open', () => {
    if (epoch !== attemptEpoch || terminal) return;
    dataConnection = peer.connect(capability.host, {
      reliable: true,
      metadata: {v: capability.version, role: 'spectator'}
    });
    dataConnection.on('open', () => {
      dataConnection.send({
        v: capability.version,
        type: 'watch',
        cap: capability.watch
      });
      showState('connecting', 'Host found', 'Waiting for authenticated video…');
    });
    dataConnection.on('data', value => {
      if (!value || value.v !== capability.version || typeof value.type !== 'string') return;
      if (value.type === 'telemetry') {
        acceptTelemetry(value);
        return;
      }
      if (value.type === 'reject') {
        if (value.reason === 'capacity' || value.reason === 'unavailable') {
          scheduleRetry('The stream is currently full. Retrying…');
        } else {
          reconnectAllowed = false;
          cleanup();
          showState(
            'offline',
            'Unable to join',
            'The join link was rejected. Ask the host for a fresh link.',
            {showRetry: true, loading: false}
          );
        }
      }
    });
    dataConnection.on('close', () => {
      if (!video.srcObject) {
        scheduleRetry('Host connection closed. Retrying…');
      } else {
        markTelemetryStale('Video is still live.');
      }
    });
    dataConnection.on('error', () => {
      if (!video.srcObject) {
        scheduleRetry('Host connection failed. Retrying…');
      } else {
        markTelemetryStale('Video is still live.');
      }
    });
  });
  peer.on('connection', connection => connection.close());
  peer.on('call', call => {
    if (call.peer !== capability.host) {
      call.close();
      return;
    }
    const metadata = call.metadata || {};
    if (metadata.v !== capability.version || metadata.role !== 'spectator') {
      call.close();
      return;
    }
    if (mediaConnection) {
      call.close();
      return;
    }
    mediaConnection = call;
    call.answer();
    call.on('stream', stream => {
      if (mediaConnection !== call) return;
      video.srcObject = stream;
      lastVideoTime = null;
      lastVideoProgressAt = monotonicNow();
      for (const track of stream.getTracks()) {
        track.addEventListener(
          'ended',
          () => scheduleRetry('The host ended the video. Retrying…'),
          {once: true}
        );
        track.addEventListener('mute', () => {
          markVideoInterrupted(
            'Video interrupted',
            'The host video track is temporarily muted.',
            'Muted'
          );
        });
        track.addEventListener('unmute', () => {
          if (video.readyState >= 2 && video.paused !== true) {
            markVideoPlaying();
          } else {
            showState('connecting', 'Video restored', 'Waiting for playback…');
          }
        });
      }
      showState('connecting', 'Video received', 'Starting playback…');
      attemptPlayback();
    });
    call.on('close', () => {
      if (mediaConnection !== call) return;
      mediaConnection = null;
      video.srcObject = null;
      scheduleRetry('The host ended or restarted the stream. Retrying…');
    });
    call.on('error', () => {
      if (mediaConnection !== call) return;
      mediaConnection = null;
      video.srcObject = null;
      scheduleRetry('Video connection failed. Retrying…');
    });
  });
  peer.on('disconnected', () => scheduleRetry('Signaling disconnected. Retrying…'));
  peer.on('error', error => {
    const errorType = String(error && error.type || 'unknown');
    if (errorType === 'peer-unavailable') {
      scheduleRetry(
        'The host is offline or restarted, so this link is no longer valid. Ask the host for a fresh link. Retrying…'
      );
    } else {
      scheduleRetry(`Peer connection failed (${errorType}). Retrying…`);
    }
  });
}

function attachDirectStream(stream, hostPeer) {
  if (hostPeer && hostPeer !== acceptedHost) return;
  video.srcObject = stream;
  lastVideoTime = null;
  lastVideoProgressAt = monotonicNow();
  for (const track of stream.getTracks()) {
    track.addEventListener(
      'ended',
      () => scheduleRetry('The host ended the video. Retrying…'),
      {once: true}
    );
    track.addEventListener('mute', () => {
      markVideoInterrupted(
        'Video interrupted',
        'The host video track is temporarily muted.',
        'Muted'
      );
    });
    track.addEventListener('unmute', () => {
      if (video.readyState >= 2 && video.paused !== true) {
        markVideoPlaying();
      }
    });
  }
  showState('connecting', 'Video received', 'Starting direct playback…');
  void attemptPlayback();
}

function validHostRole(value, peerId, nonce) {
  return Boolean(
    hasExactKeys(value, [
      'expires', 'fingerprint', 'generation', 'host_nonce',
      'host_public_key', 'role', 'room', 'sender', 'sequence', 'signature',
      'target', 'type', 'v', 'viewer_nonce'
    ]) &&
    value.v === 2 &&
    value.type === 'rpp-role' &&
    value.role === 'host' &&
    value.room === capability.room &&
    value.generation === capability.generation &&
    value.fingerprint === capability.fingerprint &&
    value.host_public_key === capability.hostPublicKey &&
    value.sender === peerId &&
    value.target === RppTrysteroNostr.selfId &&
    value.viewer_nonce === nonce &&
    /^[A-Za-z0-9_-]{22}$/.test(value.host_nonce || '') &&
    value.sequence === 1 &&
    Number.isSafeInteger(value.expires) &&
    value.expires >= Math.floor(Date.now() / 1000) &&
    value.expires <= Math.floor(Date.now() / 1000) + 60 &&
    new TextEncoder().encode(JSON.stringify(value)).byteLength <= 2048
  );
}

async function viewerPeerHandshake(epoch, peerId, send, receive) {
  if (
    epoch !== attemptEpoch ||
    (acceptedHost && acceptedHost !== peerId) ||
    (pendingHost && pendingHost.peerId !== peerId)
  ) {
    throw new Error('a different host is already pinned');
  }
  const nonce = RppPairing.randomToken(16);
  const pending = {peerId, nonce, epoch, verified: false};
  pendingHost = pending;
  const hello = await RppPairing.addViewerProof(capability.key, {
    v: 2,
    type: 'rpp-role',
    role: 'viewer',
    room: capability.room,
    generation: capability.generation,
    fingerprint: capability.fingerprint,
    host_public_key: capability.hostPublicKey,
    sender: RppTrysteroNostr.selfId,
    target: peerId,
    nonce,
    expires: Math.floor(Date.now() / 1000) + 30,
    sequence: 1
  });
  await send(hello);
  const received = await receive();
  const proof = received && received.data;
  if (
    epoch !== attemptEpoch ||
    pendingHost !== pending ||
    !validHostRole(proof, peerId, nonce) ||
    !await RppPairing.verifyHostTranscript(capability.hostPublicKey, proof)
  ) {
    if (pendingHost === pending) pendingHost = null;
    throw new Error('host role proof rejected');
  }
  pending.verified = true;
}

async function recordDirectPath(pc) {
  try {
    const type = await RppPairing.selectedCandidateType(pc);
    if (['host', 'srflx', 'prflx', 'relay'].includes(type)) {
      candidateTypes.add(type);
    }
    document.getElementById('direct-health').textContent = (
      type === 'relay' ? 'Relayed (TURN)' :
      type === 'unknown' ? 'Direct' : `Direct ${type}`
    );
  } catch (_error) {
    if (pc.connectionState !== 'closed') {
      document.getElementById('direct-health').textContent = 'Direct';
    }
  }
}

function monitorNostrRelays(epoch, joinedRoom) {
  if (
    !joinedRoom ||
    room !== joinedRoom ||
    epoch !== attemptEpoch
  ) return;
  let sockets = {};
  let health = {};
  try {
    sockets = RppTrysteroNostr.getRelaySockets();
    health = typeof RppTrysteroNostr.getRelayHealth === 'function'
      ? RppTrysteroNostr.getRelayHealth()
      : {};
  } catch (_error) {
    sockets = {};
    health = {};
  }
  const open = REVIEWED_RELAYS.filter(
    url => sockets[url] && sockets[url].readyState === 1
  ).length;
  const qualified = REVIEWED_RELAYS.filter(
    url => health[url] && health[url].qualified === true
  ).length;
  document.getElementById('relay-health').textContent =
    `${qualified} qualified · ${open} open`;
  if (qualified) {
    relayFailureStartedAt = null;
    return;
  }
  if (relayFailureStartedAt === null) relayFailureStartedAt = monotonicNow();
  if (monotonicNow() - relayFailureStartedAt > 12000 && !video.srcObject) {
    document.getElementById('manual-help').hidden = false;
    showState(
      'offline',
      'Automatic signaling blocked',
      'Ask the host for a fresh Manual Share offer. Invited peers can still expose candidate metadata before authentication; existing direct media remains independent of relays.',
      {showRetry: true, loading: false}
    );
  }
}

function monitorNostrPeer(epoch, joinedRoom, peerId) {
  const pc = joinedRoom && joinedRoom.getPeers()[peerId];
  if (!pc) return;
  const changed = () => {
    if (
      epoch !== attemptEpoch ||
      room !== joinedRoom ||
      acceptedHost !== peerId
    ) return;
    const connected = (
      pc.connectionState === 'connected' ||
      pc.iceConnectionState === 'connected' ||
      pc.iceConnectionState === 'completed'
    );
    if (connected) {
      if (transportTimer) clearTimeout(transportTimer);
      transportTimer = null;
      void recordDirectPath(pc);
    }
    if (
      ['failed', 'closed'].includes(pc.connectionState) ||
      pc.iceConnectionState === 'failed'
    ) scheduleRetry('The direct WebRTC path failed. Retrying…');
  };
  pc.addEventListener('connectionstatechange', changed);
  pc.addEventListener('iceconnectionstatechange', changed);
  changed();
}

async function connectNostr(epoch) {
  if (
    typeof RppTrysteroNostr !== 'object' ||
    typeof RppTrysteroNostr.qualifyRelays !== 'function' ||
    typeof RppPairing !== 'object'
  ) {
    showState(
      'error',
      'Signaling runtime unavailable',
      'Ask the host for a manual pairing offer.',
      {loading: false}
    );
    return;
  }
  try {
    if (
      await RppPairing.deriveHostFingerprint(
        capability.hostPublicKey,
        capability.generation
      ) !== capability.fingerprint
    ) throw new Error('host fingerprint mismatch');
  } catch (_error) {
    showState(
      'error',
      'Invitation rejected',
      'The pinned host public key does not match this generation.',
      {loading: false}
    );
    return;
  }
  if (epoch !== attemptEpoch || terminal) return;
  reconnectAllowed = true;
  showState(
    'connecting',
    'Joining livestream…',
    'Opening redundant encrypted Nostr signaling relays.'
  );
  try {
    const joinedRoom = RppTrysteroNostr.joinRoom(
      {
        appId: NOSTR_APP_ID,
        password: capability.key,
        passive: true,
        relayConfig: {
          urls: [...REVIEWED_RELAYS],
          redundancy: REVIEWED_RELAYS.length,
          warnOnRelayFailure: false
        },
        trickleIce: true,
        rtcConfig: RppPairing.cloneRtcConfig()
      },
      capability.room,
      {
        onPeerHandshake: (...args) => viewerPeerHandshake(epoch, ...args),
        handshakeTimeoutMs: 10000,
        onJoinError: details => {
          if (
            pendingHost &&
            pendingHost.epoch === epoch &&
            pendingHost.peerId === details.peerId
          ) pendingHost = null;
          if (!video.srcObject) {
            showState(
              'connecting',
              'Waiting for authenticated host…',
              `A peer was rejected (${String(details.error).slice(0, 60)}).`
            );
          }
        }
      }
    );
    if (epoch !== attemptEpoch || terminal) {
      await joinedRoom.leave().catch(() => {});
      return;
    }
    room = joinedRoom;
    if (!joinedRoom.isPassive()) {
      throw new Error('viewer room is not passive');
    }
    telemetryAction = joinedRoom.makeAction('rpp-telemetry-v2');
    mediaReadyAction = joinedRoom.makeAction('rpp-media-ready-v2');
    telemetryAction.onMessage = (value, context) => {
      if (context.peerId === acceptedHost) acceptTelemetry(value);
    };
    joinedRoom.onPeerJoin = peerId => {
      if (
        epoch !== attemptEpoch ||
        room !== joinedRoom ||
        !pendingHost ||
        !pendingHost.verified ||
        pendingHost.epoch !== epoch ||
        pendingHost.peerId !== peerId
      ) {
        const wrong = joinedRoom.getPeers()[peerId];
        try { wrong.close(); } catch (_error) {}
        return;
      }
      acceptedHost = peerId;
      pendingHost = null;
      if (hostAuthTimer) clearTimeout(hostAuthTimer);
      hostAuthTimer = null;
      transportTimer = setTimeout(() => {
        if (epoch !== attemptEpoch || acceptedHost !== peerId) return;
        scheduleRetry(
          'Host authenticated, but the WebRTC transport timed out even with the TURN relay fallback. Try a fresh link or Manual Share.'
        );
      }, TRANSPORT_DEADLINE_MILLISECONDS);
      mediaTimer = setTimeout(() => {
        if (epoch !== attemptEpoch || acceptedHost !== peerId) return;
        scheduleRetry(
          'Direct transport opened, but authenticated media did not arrive and play. Ask for a fresh link or Manual Share offer.'
        );
      }, MEDIA_DEADLINE_MILLISECONDS);
      showState(
        'connecting',
        'Authenticated host found',
        'Negotiating a direct STUN-only WebRTC path…'
      );
      monitorNostrPeer(epoch, joinedRoom, peerId);
    };
    joinedRoom.onPeerLeave = peerId => {
      if (peerId !== acceptedHost) return;
      if (video.srcObject) {
        scheduleRetry('The direct host connection ended. Retrying…');
      } else {
        scheduleRetry('The authenticated host disconnected. Retrying…');
      }
    };
    joinedRoom.onPeerStream = (stream, peerId, metadata) => {
      if (
        epoch !== attemptEpoch ||
        room !== joinedRoom ||
        peerId !== acceptedHost ||
        !hasExactKeys(
          metadata,
          ['fingerprint', 'generation', 'host_public_key', 'role', 'v']
        ) ||
        metadata.v !== 2 ||
        metadata.role !== 'host' ||
        metadata.generation !== capability.generation ||
        metadata.fingerprint !== capability.fingerprint ||
        metadata.host_public_key !== capability.hostPublicKey
      ) return;
      attachDirectStream(stream, peerId);
    };
    void RppTrysteroNostr.qualifyRelays().catch(() => {});
    hostAuthTimer = setTimeout(() => {
      if (epoch !== attemptEpoch || acceptedHost) return;
      pendingHost = null;
      scheduleRetry(
        'No host signed the complete handshake before the authentication deadline. Ask for a fresh link or Manual Share offer.'
      );
    }, HOST_AUTH_DEADLINE_MILLISECONDS);
    relayFailureStartedAt = monotonicNow();
    relayTimer = setInterval(
      () => monitorNostrRelays(epoch, joinedRoom),
      1000
    );
    monitorNostrRelays(epoch, joinedRoom);
  } catch (_error) {
    if (epoch !== attemptEpoch || terminal) return;
    pendingHost = null;
    scheduleRetry('Could not initialize encrypted Nostr signaling. Retrying…');
  }
}

function showManualAnswer(result) {
  const panel = document.getElementById('manual-answer');
  const canvas = document.getElementById('manual-answer-qr');
  const note = document.getElementById('manual-answer-note');
  document.getElementById('manual-answer-text').value = result.returnLink;
  const raw = document.getElementById('manual-raw-answer');
  if (raw) raw.value = result.text;
  panel.hidden = false;
  canvas.hidden = !result.qrSafe;
  if (result.qrSafe) {
    new QRious({
      element: canvas,
      value: result.returnLink,
      size: 320,
      level: 'M',
      background: 'white',
      foreground: 'black'
    });
    note.textContent =
      'Share or open this answer link on the streamer Mac. The QR transfers that same complete return link.';
  } else {
    note.textContent =
      'The complete uncompressed answer link exceeds conservative QR capacity. Share or copy it; it was not truncated.';
  }
  document.getElementById('share-manual-answer').hidden =
    typeof navigator.share !== 'function';
}

async function shareManualAnswer() {
  if (!manualAnswerResult || typeof navigator.share !== 'function') return;
  const note = document.getElementById('manual-answer-note');
  try {
    await navigator.share({url: manualAnswerResult.returnLink});
    note.textContent =
      'Answer Share sheet opened. Open the shared link on the streamer Mac.';
  } catch (error) {
    note.textContent = error && error.name === 'AbortError'
      ? 'Share canceled. The answer link and QR remain available.'
      : 'Share failed. Copy the complete answer link instead.';
  }
}

async function connectManual(epoch) {
  document.getElementById('relay-health').textContent = 'Brokerless';
  document.getElementById('direct-health').textContent = 'Pairing';
  showState(
    'connecting',
    'Preparing manual answer…',
    'Gathering complete STUN-only ICE before producing the answer.'
  );
  let manualCapability;
  try {
    manualCapability = await RppPairing.parseManualOfferFragment(
      capability.fragment
    );
    if (epoch !== attemptEpoch || terminal) return;
    manualPair = manualCapability.pair;
    const result = await RppPairing.createManualAnswer({
      capability: manualCapability,
      onPeerConnection: pc => {
        manualPeer = pc;
      },
      onStream: stream => attachDirectStream(stream, null),
      onChannel: channel => {
        if (manualChannel) {
          channel.close();
          return;
        }
        manualChannel = channel;
        channel.addEventListener('open', () => {
          void sendMediaReady();
        });
        channel.addEventListener('message', event => {
          if (
            typeof event.data !== 'string' ||
            new TextEncoder().encode(event.data).byteLength > MAX_TELEMETRY_BYTES
          ) return;
          try {
            acceptTelemetry(JSON.parse(event.data));
          } catch (_error) {
            // A malformed telemetry message is isolated from media playback.
          }
        });
        channel.addEventListener('close', () => scheduleRetry(
          'The consumed manual connection ended.'
        ));
      }
    });
    if (epoch !== attemptEpoch || terminal) {
      try { result.pc.close(); } catch (_error) {}
      return;
    }
    manualPeer = result.pc;
    manualAnswerResult = result;
    showManualAnswer(result);
    showState(
      'connecting',
      'Manual answer ready',
      'Use Share Answer Back, then open the shared answer link on the streamer Mac.',
      {loading: false}
    );
    const changed = () => {
      if (
        manualPeer &&
        (
          manualPeer.connectionState === 'connected' ||
          manualPeer.iceConnectionState === 'connected' ||
          manualPeer.iceConnectionState === 'completed'
        )
      ) {
        if (transportTimer) clearTimeout(transportTimer);
        transportTimer = null;
        if (!mediaTimer) {
          mediaTimer = setTimeout(() => {
            scheduleRetry(
              'Manual transport connected, but media did not arrive and play.'
            );
          }, MEDIA_DEADLINE_MILLISECONDS);
        }
        void recordDirectPath(manualPeer);
      }
      if (
        manualPeer &&
        (
          ['failed', 'closed'].includes(manualPeer.connectionState) ||
          manualPeer.iceConnectionState === 'failed'
        )
      ) {
        scheduleRetry('The consumed manual direct path ended.');
      }
    };
    manualPeer.addEventListener('connectionstatechange', changed);
    manualPeer.addEventListener('iceconnectionstatechange', changed);
  } catch (error) {
    if (epoch !== attemptEpoch || terminal) return;
    terminal = true;
    if (manualPeer) {
      try { manualPeer.close(); } catch (_error) {}
    }
    showState(
      'error',
      'Manual pairing failed',
      String(error && error.message || error).slice(0, 160),
      {loading: false}
    );
  }
}

async function connect() {
  if (terminal) return;
  const epoch = attemptEpoch + 1;
  attemptEpoch = epoch;
  const disposed = await cleanupPromise;
  if (
    epoch !== attemptEpoch ||
    terminal ||
    !disposed ||
    leaveFailed
  ) {
    if (!disposed || leaveFailed) safeViewerReset();
    return;
  }
  if (!capability) {
    showState(
      'error',
      'Invalid or unsupported link',
      'Ask the host for a fresh private join link.',
      {loading: false}
    );
  } else if (capability.mode === 'manual-offer') {
    await connectManual(epoch);
  } else if (capability.mode === 'nostr') {
    await connectNostr(epoch);
  } else {
    await connectLegacy(epoch);
  }
}

setInterval(() => {
  if (
    telemetryReceivedAt !== null &&
    monotonicNow() - telemetryReceivedAt > TELEMETRY_STALE_MILLISECONDS
  ) {
    markTelemetryStale(
      staleDetailContext || 'Video may still be live.'
    );
  }
  updateVideoHealth();
}, 1000);

video.addEventListener('click', attemptPlayback);
playButton.addEventListener('click', attemptPlayback);
retryButton.addEventListener('click', retryNow);
document.getElementById('share-manual-answer').addEventListener(
  'click',
  shareManualAnswer
);
document.getElementById('copy-manual-answer').addEventListener('click', async () => {
  const value = document.getElementById('manual-answer-text').value;
  if (!value) return;
  const note = document.getElementById('manual-answer-note');
  try {
    await navigator.clipboard.writeText(value);
    note.textContent =
      'Complete answer link copied. Open it on the streamer Mac.';
  } catch (_error) {
    note.textContent = 'Copy failed. Select and copy the complete answer text.';
  }
});
document.getElementById('copy-manual-raw-answer').addEventListener(
  'click',
  async () => {
    const value = document.getElementById('manual-raw-answer').value;
    if (!value) return;
    const note = document.getElementById('manual-answer-note');
    try {
      await navigator.clipboard.writeText(value);
      note.textContent =
        'Raw encrypted answer copied for the live host page paste fallback.';
    } catch (_error) {
      note.textContent = 'Copy failed. Select the complete fallback answer.';
    }
  }
);
function leavePage() {
  if (terminal) return;
  terminal = true;
  reconnectAllowed = false;
  void cleanup();
}
window.addEventListener('pagehide', leavePage);
window.addEventListener('beforeunload', leavePage);
void connect();
