
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
const MAX_TELEMETRY_BYTES = 4096;
const TELEMETRY_STALE_MILLISECONDS = 12000;
const VIDEO_STALL_MILLISECONDS = 8000;
let peer = null;
let dataConnection = null;
let mediaConnection = null;
let retryTimer = null;
let retries = 0;
let reconnectAllowed = true;
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
  return {version, host, watch};
}

const capability = parseCapability();

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

function cleanup() {
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  const oldMediaConnection = mediaConnection;
  const oldDataConnection = dataConnection;
  const oldPeer = peer;
  mediaConnection = null;
  dataConnection = null;
  peer = null;
  if (oldMediaConnection) oldMediaConnection.close();
  if (oldDataConnection) oldDataConnection.close();
  if (oldPeer) oldPeer.destroy();
  video.srcObject = null;
  lastVideoTime = null;
  lastVideoProgressAt = null;
  resetTelemetry();
}

function scheduleRetry(message) {
  if (!capability || retryTimer || !reconnectAllowed) return;
  if (retries >= MAX_AUTOMATIC_RETRIES) {
    reconnectAllowed = false;
    cleanup();
    showState(
      'offline',
      'Stream unavailable',
      'Automatic retries ended. Ask the host for a fresh link.',
      {showRetry: true, loading: false}
    );
    return;
  }
  reconnectAllowed = false;
  cleanup();
  showState('reconnecting', 'Stream interrupted', message);
  const delay = Math.min(10000, 750 * (2 ** Math.min(retries, 4)));
  retries += 1;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    reconnectAllowed = true;
    connect();
  }, delay);
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

function markVideoPlaying() {
  lastVideoTime = Number(video.currentTime) || 0;
  lastVideoProgressAt = monotonicNow();
  retries = 0;
  showState('live', 'Live', 'Receiving direct peer-to-peer video.', {
    loading: false
  });
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
    value.v !== 1 ||
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

function retryNow() {
  retries = 0;
  reconnectAllowed = true;
  cleanup();
  connect();
}

function connect() {
  if (!capability || typeof Peer !== 'function') {
    showState(
      'error',
      'Invalid or unsupported link',
      'Ask the host for a fresh join link.',
      {loading: false}
    );
    return;
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
    peer = new Peer(spectatorPeerId, {
      host: '0.peerjs.com',
      port: 443,
      path: '/',
      secure: true,
      debug: 0,
      config: {
        iceServers: [
          {urls: 'stun:stun.l.google.com:19302'}
        ]
      }
    });
  } catch (_error) {
    scheduleRetry('Could not initialize PeerJS. Retrying…');
    return;
  }
  peer.on('open', () => {
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
  peer.on('error', () => scheduleRetry('Peer connection failed. Retrying…'));
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
function leavePage() {
  reconnectAllowed = false;
  cleanup();
}
window.addEventListener('pagehide', leavePage);
window.addEventListener('beforeunload', leavePage);
connect();
