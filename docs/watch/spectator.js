
const video = document.getElementById('stream');
const overlay = document.getElementById('overlay');
const headline = document.getElementById('headline');
const detail = document.getElementById('detail');
const connectionLabel = document.getElementById('connection');
const spinner = document.getElementById('spinner');
const playButton = document.getElementById('play-stream');
const retryButton = document.getElementById('retry-stream');
const MAX_AUTOMATIC_RETRIES = 6;
let peer = null;
let dataConnection = null;
let mediaConnection = null;
let retryTimer = null;
let retries = 0;
let reconnectAllowed = true;

function showState(
  state,
  title,
  message,
  {showPlay = false, showRetry = false, loading = true} = {}
) {
  connectionLabel.textContent = state.toUpperCase();
  connectionLabel.className = 'connection' + (state === 'live' ? ' live' : '');
  headline.textContent = title;
  detail.textContent = message;
  playButton.hidden = !showPlay;
  retryButton.hidden = !showRetry;
  spinner.classList.toggle('hidden', !loading);
  if (state === 'live') overlay.classList.add('ready');
  else overlay.classList.remove('ready');
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

function cleanup() {
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  if (mediaConnection) mediaConnection.close();
  if (dataConnection) dataConnection.close();
  if (peer) peer.destroy();
  mediaConnection = null;
  dataConnection = null;
  peer = null;
  video.srcObject = null;
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
    showState('live', 'Live', 'Receiving direct peer-to-peer video.', {
      loading: false
    });
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
  reconnectAllowed = true;
  showState('connecting', 'Joining livestream…', 'Connecting through PeerJS signaling.');
  try {
    peer = new Peer({
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
      if (!value || value.v !== capability.version || typeof value.type !== 'string') {
        scheduleRetry('The host sent an invalid response. Retrying…');
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
      if (!video.srcObject) scheduleRetry('Host connection closed. Retrying…');
    });
    dataConnection.on('error', () => scheduleRetry('Host connection failed. Retrying…'));
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
      video.srcObject = stream;
      for (const track of stream.getTracks()) {
        track.addEventListener(
          'ended',
          () => scheduleRetry('The host ended the video. Retrying…'),
          {once: true}
        );
      }
      showState('connecting', 'Video received', 'Starting playback…');
      attemptPlayback();
    });
    call.on('close', () => {
      video.srcObject = null;
      scheduleRetry('The host ended or restarted the stream. Retrying…');
    });
    call.on('error', () => {
      video.srcObject = null;
      scheduleRetry('Video connection failed. Retrying…');
    });
  });
  peer.on('disconnected', () => scheduleRetry('Signaling disconnected. Retrying…'));
  peer.on('error', () => scheduleRetry('Peer connection failed. Retrying…'));
}

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
