'use strict';

const ALLOWED_KEYS = new Set([
  'v', 's', 'd', 'a', 'f', 'h', 'c', 'i', 'e', 'u', 'r', 't', 'g', 'q',
  'w', 'z'
]);
const REASONING = new Set(['low', 'medium', 'high', 'max']);
const HINT_STATES = {
  o: 'off',
  w: 'waiting',
  e: 'eligible',
  m: 'mixed',
  a: 'armed',
  p: 'prompted',
  c: 'consumed',
  b: 'collision blocked',
  x: 'context blocked',
  i: 'invalid',
  n: 'missing',
  u: 'unknown'
};
const WEB_STATES = {
  o: 'off',
  i: 'idle',
  s: 'searching',
  r: 'ready',
  f: 'failed',
  u: 'unknown'
};
const ISSUE_BASE =
  'https://github.com/kody-w/rappter-plays-pokemon/issues/new';

function boundedNumber(params, key, minimum, maximum) {
  if (!params.has(key)) return null;
  const raw = params.get(key);
  if (!/^-?\d+(?:\.\d{1,2})?$/u.test(raw)) {
    throw new Error(`Invalid metric: ${key}`);
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value < minimum || value > maximum) {
    throw new Error(`Out-of-range metric: ${key}`);
  }
  return value;
}

function parseDiagnostic(fragment) {
  const params = new URLSearchParams(fragment.replace(/^#/, ''));
  if (params.get('v') !== '1') throw new Error('Unsupported diagnostic version.');
  for (const key of params.keys()) {
    if (!ALLOWED_KEYS.has(key)) throw new Error('Unexpected diagnostic field.');
  }
  const reasoning = params.get('r');
  if (reasoning !== null && !REASONING.has(reasoning)) {
    throw new Error('Invalid reasoning effort.');
  }
  const hintCode = params.get('g');
  if (hintCode !== null && !Object.hasOwn(HINT_STATES, hintCode)) {
    throw new Error('Invalid crowd hint state.');
  }
  const webCode = params.get('w');
  if (webCode !== null && !Object.hasOwn(WEB_STATES, webCode)) {
    throw new Error('Invalid web research state.');
  }
  return {
    sync: boundedNumber(params, 's', -5000, 5000),
    delay: boundedNumber(params, 'd', 0, 5000),
    audio: boundedNumber(params, 'a', 0, 100),
    source: boundedNumber(params, 'f', 0, 86400000),
    captureAge: boundedNumber(params, 'h', 0, 86400000),
    captureFps: boundedNumber(params, 'c', 0, 120),
    ai: boundedNumber(params, 'i', 0, 600),
    emulation: boundedNumber(params, 'e', 0, 10),
    uptime: boundedNumber(params, 'u', 0, 315360000),
    navigation: boundedNumber(params, 'q', 0, 999),
    webSources: boundedNumber(params, 'z', 0, 10),
    capturedAt: boundedNumber(params, 't', 1700000000, 2200000000),
    reasoning,
    hintState: hintCode === null ? null : HINT_STATES[hintCode],
    webState: webCode === null ? null : WEB_STATES[webCode]
  };
}

function metricHealth(snapshot) {
  const levels = [];
  const add = (value, good, warn, direction = 'maximum') => {
    if (value === null) return;
    const score = direction === 'minimum'
      ? (value >= good ? 0 : value >= warn ? 1 : 2)
      : (value <= good ? 0 : value <= warn ? 1 : 2);
    levels.push(score);
  };
  if (snapshot.sync !== null) {
    add(Math.abs(snapshot.sync), 100, 250);
  }
  add(snapshot.audio, 95, 70, 'minimum');
  add(snapshot.source, 250, 1000);
  add(snapshot.captureAge, 250, 1000);
  add(snapshot.captureFps, 18, 10, 'minimum');
  add(snapshot.ai, 10, 30);
  if (snapshot.emulation !== null) {
    add(Math.abs(snapshot.emulation - 1), 0.03, 0.1);
  }
  const worst = levels.length ? Math.max(...levels) : 3;
  return ['good', 'warn', 'bad', 'unknown'][worst];
}

function formatMetric(value, suffix, digits = 0) {
  return value === null ? 'Unknown' : `${value.toFixed(digits)}${suffix}`;
}

function buildIssueUrl(snapshot) {
  const value = (metric, suffix = '') =>
    metric === null ? 'unknown' : `${metric}${suffix}`;
  const captured = snapshot && snapshot.capturedAt !== null
    ? new Date(snapshot.capturedAt * 1000).toISOString()
    : 'unknown';
  const body = [
    '## What happened',
    '',
    '<!-- Describe what you saw and attach the screenshot containing the QR. -->',
    '',
    '## Stream snapshot',
    '',
    `- Captured at: ${captured}`,
    '- Broadcast: https://www.youtube.com/channel/UCz0Tfe07OAwnQR-fd3E1y4Q/live',
    `- A/V clock drift: ${value(snapshot && snapshot.sync, ' ms')}`,
    `- Configured audio delay: ${value(snapshot && snapshot.delay, ' ms')}`,
    `- Real audio fill: ${value(snapshot && snapshot.audio, '%')}`,
    `- Source frame age: ${value(snapshot && snapshot.source, ' ms')}`,
    `- Capture frame age: ${value(snapshot && snapshot.captureAge, ' ms')}`,
    `- Capture rate: ${value(snapshot && snapshot.captureFps, ' fps')}`,
    `- AI response latency: ${value(snapshot && snapshot.ai, ' s')}`,
    `- Reasoning effort: ${(snapshot && snapshot.reasoning) || 'unknown'}`,
    `- Emulation speed: ${value(snapshot && snapshot.emulation, 'x')}`,
    `- Encoder uptime: ${value(snapshot && snapshot.uptime, ' s')}`,
    `- Crowd hint gate: ${(snapshot && snapshot.hintState) || 'unknown'}`,
    `- Navigation memory entries: ${value(snapshot && snapshot.navigation)}`,
    `- Autonomous web recovery: ${(snapshot && snapshot.webState) || 'unknown'}`,
    `- Web sources accepted: ${value(snapshot && snapshot.webSources)}`,
    '',
    '## Additional context',
    '',
    '<!-- Include device/browser details only if they seem relevant. -->'
  ].join('\n');
  const params = new URLSearchParams({
    title: '[Live stream] ',
    body
  });
  return `${ISSUE_BASE}?${params.toString()}`;
}

function initializeDiagnostics() {
  let snapshot;
  try {
    snapshot = parseDiagnostic(location.hash);
  } catch (_error) {
    document.getElementById('report-issue').href = buildIssueUrl(null);
    return;
  }
  document.getElementById('report-issue').href = buildIssueUrl(snapshot);
  const health = metricHealth(snapshot);
  const labels = {
    good: ['Healthy snapshot', 'Healthy'],
    warn: ['Snapshot needs attention', 'Watch'],
    bad: ['Snapshot indicates a problem', 'Investigate'],
    unknown: ['Partial diagnostic snapshot', 'Partial']
  };
  document.getElementById('snapshot-title').textContent = labels[health][0];
  const badge = document.getElementById('health-badge');
  badge.className = `health ${health}`;
  badge.textContent = labels[health][1];
  document.getElementById('sync-value').textContent =
    formatMetric(snapshot.sync, ' ms');
  document.getElementById('delay-value').textContent =
    formatMetric(snapshot.delay, ' ms');
  document.getElementById('audio-value').textContent =
    formatMetric(snapshot.audio, '%', 1);
  document.getElementById('source-value').textContent =
    formatMetric(snapshot.source, ' ms');
  document.getElementById('capture-age-value').textContent =
    formatMetric(snapshot.captureAge, ' ms');
  document.getElementById('capture-fps-value').textContent =
    formatMetric(snapshot.captureFps, ' fps', 1);
  const effort = snapshot.reasoning ? ` · ${snapshot.reasoning}` : '';
  document.getElementById('ai-value').textContent =
    formatMetric(snapshot.ai, ' s', 1) + effort;
  document.getElementById('emulation-value').textContent =
    formatMetric(snapshot.emulation, 'x', 2);
  document.getElementById('uptime-value').textContent =
    formatMetric(snapshot.uptime, ' s');
  document.getElementById('hint-value').textContent =
    snapshot.hintState === null ? 'Unknown' : snapshot.hintState;
  document.getElementById('navigation-value').textContent =
    formatMetric(snapshot.navigation, '');
  document.getElementById('web-value').textContent =
    snapshot.webState === null
      ? 'Unknown'
      : `${snapshot.webState} · ${formatMetric(snapshot.webSources, '')} sources`;
  document.getElementById('no-snapshot').hidden = true;
  document.getElementById('metrics').hidden = false;
}

if (typeof globalThis.__RPP_DIAGNOSTICS_TEST_HOOK__ === 'function') {
  globalThis.__RPP_DIAGNOSTICS_TEST_HOOK__({
    parseDiagnostic,
    metricHealth,
    buildIssueUrl
  });
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', initializeDiagnostics);
}
