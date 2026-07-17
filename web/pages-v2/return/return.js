(() => {
'use strict';

const MAX_FRAGMENT_LENGTH = 512 * 1024;
const status = document.getElementById('return-status');
const handoff = document.getElementById('handoff');

function decodeBase64Url(value) {
  if (
    typeof value !== 'string' ||
    value.length < 1 ||
    value.length > 1024 ||
    !/^[A-Za-z0-9_-]+$/.test(value)
  ) throw new Error('invalid callback');
  const padding = '='.repeat((4 - value.length % 4) % 4);
  return atob(value.replaceAll('-', '+').replaceAll('_', '/') + padding);
}

function callbackFromToken(value) {
  let callback;
  try {
    callback = JSON.parse(decodeBase64Url(value));
  } catch (_error) {
    throw new Error('invalid callback');
  }
  if (
    !callback ||
    Array.isArray(callback) ||
    Object.keys(callback).sort().join(',') !== 'origin,path' ||
    callback.path !== '/pair-return'
  ) throw new Error('invalid callback');
  const origin = new URL(callback.origin);
  if (
    origin.protocol !== 'http:' ||
    origin.hostname !== '127.0.0.1' ||
    !origin.port ||
    Number(origin.port) > 65535 ||
    origin.pathname !== '/' ||
    origin.search ||
    origin.hash ||
    origin.username ||
    origin.password ||
    origin.origin !== callback.origin
  ) throw new Error('invalid callback');
  return callback;
}

function prepareHandoff() {
  const fragment = location.hash.slice(1);
  if (!fragment || fragment.length > MAX_FRAGMENT_LENGTH) {
    throw new Error('The answer link is missing or too large.');
  }
  const params = new URLSearchParams(fragment);
  if (
    [...params.keys()].sort().join(',') !==
      'answer,cb,gen,mode,rt,v' ||
    params.get('v') !== '2' ||
    params.get('mode') !== 'manual-return' ||
    !/^[A-Za-z0-9_-]{16,128}$/.test(params.get('gen') || '') ||
    !/^[A-Za-z0-9_-]{43}$/.test(params.get('rt') || '') ||
    !(params.get('answer') || '').startsWith('rpp-answer-v2.')
  ) throw new Error('The answer link is invalid.');
  const callback = callbackFromToken(params.get('cb') || '');
  const destination = `${callback.origin}${callback.path}#${fragment}`;
  handoff.href = destination;
  handoff.hidden = false;
  status.textContent =
    'Handing this answer to the loopback-only streamer service. If navigation is blocked, use the button.';
  if (globalThis.history && typeof history.replaceState === 'function') {
    history.replaceState(null, '', location.pathname);
  }
  setTimeout(() => {
    location.replace(destination);
  }, 250);
}

try {
  prepareHandoff();
} catch (error) {
  status.textContent = String(error && error.message || error).slice(0, 160);
  handoff.hidden = true;
}
})();
