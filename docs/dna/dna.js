'use strict';

const STORY_SOURCE =
  'https://raw.githubusercontent.com/kody-w/rappter-plays-pokemon/' +
  'refs/heads/story-archive/v1/story.json';
const MAX_STORY_BYTES = 1024 * 1024;
const MAX_EVENTS = 512;
const STORY_KEYS = [
  'schema_version', 'story_id', 'revision', 'updated_at', 'status', 'summary',
  'coverage', 'events'
];
const COVERAGE_KEYS = [
  'first_observed_at', 'last_observed_at', 'incomplete_before',
  'continuous_source', 'event_count'
];
const EVENT_KEYS = [
  'id', 'sequence', 'observed_at', 'kind', 'chapter', 'title', 'summary',
  'location', 'badges', 'party_size', 'highest_level', 'pokedex',
  'play_time_seconds', 'coverage_gap_before', 'video'
];
const EVENT_KINDS = new Set([
  'opening', 'badge', 'completion', 'party', 'pokedex', 'journey', 'progress',
  'continuity'
]);
const BADGES = new Set([
  'Boulder', 'Cascade', 'Thunder', 'Rainbow', 'Soul', 'Marsh', 'Volcano',
  'Earth'
]);
const COLORS = {
  opening: '#ffffff',
  badge: '#ffcc33',
  completion: '#ff647c',
  party: '#a78bfa',
  pokedex: '#6ee7ff',
  journey: '#6f83a8',
  progress: '#4ade80',
  continuity: '#fb7185'
};

function exactKeys(value, keys) {
  return value !== null && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).sort().join('\n') === [...keys].sort().join('\n');
}

function boundedText(value, maximum) {
  return typeof value === 'string' && value.length > 0 &&
    value.length <= maximum && !/[\u0000-\u001f]/u.test(value);
}

function nullableInteger(value, minimum, maximum) {
  return value === null || (
    Number.isInteger(value) && value >= minimum && value <= maximum
  );
}

function validTimestamp(value) {
  return boundedText(value, 48) && Number.isFinite(Date.parse(value));
}

function validateEvent(event, ids, previousOrder) {
  if (!exactKeys(event, EVENT_KEYS) ||
      !/^event-\d{6,}$/u.test(event.id) ||
      ids.has(event.id) ||
      !Number.isInteger(event.sequence) ||
      event.sequence < 1 ||
      !validTimestamp(event.observed_at) ||
      !EVENT_KINDS.has(event.kind) ||
      !boundedText(event.chapter, 100) ||
      !boundedText(event.title, 120) ||
      !boundedText(event.summary, 800) ||
      !boundedText(event.location, 80) ||
      !Array.isArray(event.badges) ||
      event.badges.length > 8 ||
      new Set(event.badges).size !== event.badges.length ||
      event.badges.some(badge => !BADGES.has(badge)) ||
      !nullableInteger(event.party_size, 0, 6) ||
      !nullableInteger(event.highest_level, 1, 100) ||
      !exactKeys(event.pokedex, ['seen', 'caught']) ||
      !nullableInteger(event.pokedex.seen, 0, 151) ||
      !nullableInteger(event.pokedex.caught, 0, 151) ||
      (event.pokedex.seen !== null && event.pokedex.caught !== null &&
        event.pokedex.caught > event.pokedex.seen) ||
      !nullableInteger(event.play_time_seconds, 0, 100000000) ||
      typeof event.coverage_gap_before !== 'boolean') {
    throw new Error('The story contains an invalid event.');
  }
  if (event.video !== null &&
      (!exactKeys(event.video, ['youtube_id', 'start_seconds', 'end_seconds']) ||
       !/^[A-Za-z0-9_-]{11}$/u.test(event.video.youtube_id) ||
       !Number.isInteger(event.video.start_seconds) ||
       !Number.isInteger(event.video.end_seconds) ||
       event.video.start_seconds < 0 ||
       event.video.end_seconds <= event.video.start_seconds ||
       event.video.end_seconds > event.video.start_seconds + 1200)) {
    throw new Error('The story contains an invalid theater clip.');
  }
  const order = [Date.parse(event.observed_at), event.sequence];
  if (previousOrder !== null && (
    order[0] < previousOrder[0] ||
    (order[0] === previousOrder[0] && order[1] <= previousOrder[1])
  )) {
    throw new Error('The story events are not ordered.');
  }
  ids.add(event.id);
  return order;
}

function validateStory(value) {
  if (!exactKeys(value, STORY_KEYS) ||
      value.schema_version !== 1 ||
      value.story_id !== 'rappter-plays-pokemon-main-run' ||
      !/^sha256:[0-9a-f]{64}$/u.test(value.revision) ||
      !validTimestamp(value.updated_at) ||
      !['in_progress', 'completed'].includes(value.status) ||
      !boundedText(value.summary, 1000) ||
      !exactKeys(value.coverage, COVERAGE_KEYS) ||
      !validTimestamp(value.coverage.first_observed_at) ||
      !validTimestamp(value.coverage.last_observed_at) ||
      typeof value.coverage.incomplete_before !== 'boolean' ||
      typeof value.coverage.continuous_source !== 'boolean' ||
      !Array.isArray(value.events) ||
      value.events.length < 1 ||
      value.events.length > MAX_EVENTS ||
      value.coverage.event_count !== value.events.length) {
    throw new Error('The public story archive has an invalid schema.');
  }
  const ids = new Set();
  let previousOrder = null;
  for (const event of value.events) {
    previousOrder = validateEvent(event, ids, previousOrder);
  }
  return value;
}

function hash32(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function buildRunprint(story, width, height) {
  const safeWidth = Math.max(320, width);
  const safeHeight = Math.max(320, height);
  const centerX = safeWidth / 2;
  const centerY = safeHeight / 2;
  const outerRadius = Math.max(110, Math.min(safeWidth, safeHeight) / 2 - 42);
  const count = story.events.length;
  const points = story.events.map((event, index) => {
    const progress = count === 1 ? 0 : index / (count - 1);
    const noise = hash32(`${event.id}:${event.location}`);
    const angle = -Math.PI / 2 + index * 0.425 + (noise % 37 - 18) / 180;
    const radius = 18 + Math.pow(progress, 0.35) * (outerRadius - 18);
    const badgeBefore = index === 0 ? 0 : story.events[index - 1].badges.length;
    const milestone = event.kind === 'opening' ||
      event.kind === 'completion' ||
      event.badges.length > badgeBefore;
    return {
      index,
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius,
      radius: milestone ? 6.5 : event.coverage_gap_before ? 4.5 : 2.25,
      color: COLORS[event.kind],
      milestone,
      gap: event.coverage_gap_before
    };
  });
  return {
    width: safeWidth,
    height: safeHeight,
    centerX,
    centerY,
    outerRadius,
    points,
    signature: story.revision.slice(7, 19).toUpperCase()
  };
}

function visiblePoint(point, filter) {
  if (filter === 'milestones') return point.milestone;
  if (filter === 'gaps') return point.gap;
  return true;
}

function nearestPoint(points, x, y, filter, maximumDistance = 24) {
  let match = null;
  let bestDistance = maximumDistance;
  for (const point of points) {
    if (!visiblePoint(point, filter)) continue;
    const distance = Math.hypot(point.x - x, point.y - y);
    if (distance <= bestDistance) {
      bestDistance = distance;
      match = point;
    }
  }
  return match;
}

function formatClock(seconds) {
  if (!Number.isInteger(seconds)) return 'Unknown';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${String(minutes).padStart(2, '0')}m`;
}

function initializeJourneyDna() {
  const elements = {
    status: document.getElementById('dna-status'),
    experience: document.getElementById('dna-experience'),
    fallback: document.getElementById('dna-fallback'),
    retry: document.getElementById('retry-dna'),
    canvas: document.getElementById('run-canvas'),
    trace: document.getElementById('trace-run'),
    filters: [...document.querySelectorAll('[data-filter]')],
    signature: document.getElementById('run-signature'),
    number: document.getElementById('event-number'),
    kind: document.getElementById('event-kind'),
    chapter: document.getElementById('event-chapter'),
    title: document.getElementById('event-title'),
    summary: document.getElementById('event-summary'),
    location: document.getElementById('event-location'),
    badges: document.getElementById('event-badges'),
    party: document.getElementById('event-party'),
    pokedex: document.getElementById('event-pokedex'),
    clock: document.getElementById('event-clock'),
    signal: document.getElementById('event-signal'),
    scrubber: document.getElementById('event-scrubber'),
    previous: document.getElementById('previous-event'),
    next: document.getElementById('next-event'),
    statEvents: document.getElementById('stat-events'),
    statLocations: document.getElementById('stat-locations'),
    statBadges: document.getElementById('stat-badges'),
    statHours: document.getElementById('stat-hours'),
    archiveNote: document.getElementById('archive-note'),
    legendKinds: [...document.querySelectorAll('[data-kind]')],
    legendGap: document.querySelector('[data-gap]')
  };
  const context = elements.canvas.getContext('2d');
  let story = null;
  let runprint = null;
  let selected = 0;
  let filter = 'all';
  let tracing = false;
  let traceTimer = null;
  let drawFrame = null;
  let resizeFrame = null;
  let backingWidth = 0;
  let backingHeight = 0;
  const reducedMotion = window.matchMedia(
    '(prefers-reduced-motion: reduce)'
  );

  function stopTrace(message = '') {
    tracing = false;
    if (traceTimer !== null) {
      clearTimeout(traceTimer);
      traceTimer = null;
    }
    elements.trace.textContent = 'Trace the run';
    if (message) {
      elements.status.hidden = false;
      elements.status.textContent = message;
    } else {
      elements.status.hidden = true;
      elements.status.textContent = '';
    }
  }

  function draw() {
    if (!story || !runprint) return;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = runprint.width;
    const height = runprint.height;
    const nextWidth = Math.round(width * ratio);
    const nextHeight = Math.round(height * ratio);
    if (backingWidth !== nextWidth || backingHeight !== nextHeight) {
      elements.canvas.width = nextWidth;
      elements.canvas.height = nextHeight;
      backingWidth = nextWidth;
      backingHeight = nextHeight;
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    context.strokeStyle = 'rgba(110, 231, 255, 0.07)';
    context.lineWidth = 1;
    for (let ring = 1; ring <= 4; ring += 1) {
      context.beginPath();
      context.arc(
        runprint.centerX,
        runprint.centerY,
        runprint.outerRadius * ring / 4,
        0,
        Math.PI * 2
      );
      context.stroke();
    }

    context.strokeStyle = 'rgba(169, 181, 205, 0.15)';
    context.lineWidth = 1;
    context.beginPath();
    runprint.points.forEach((point, index) => {
      if (index === 0) {
        context.moveTo(point.x, point.y);
        return;
      }
      const previous = runprint.points[index - 1];
      if (point.gap) {
        context.stroke();
        context.save();
        context.beginPath();
        context.setLineDash([3, 7]);
        context.moveTo(previous.x, previous.y);
        context.lineTo(point.x, point.y);
        context.strokeStyle = 'rgba(255, 100, 124, 0.28)';
        context.stroke();
        context.restore();
        context.beginPath();
        context.moveTo(point.x, point.y);
      } else {
        context.lineTo(point.x, point.y);
      }
    });
    context.stroke();

    for (const point of runprint.points) {
      const visible = visiblePoint(point, filter);
      context.globalAlpha = visible ? 0.92 : 0.08;
      if (point.gap) {
        context.beginPath();
        context.arc(point.x, point.y, point.radius + 5, 0.2, Math.PI * 1.55);
        context.strokeStyle = '#ff647c';
        context.lineWidth = 1.5;
        context.stroke();
      }
      if (point.milestone && visible) {
        const glow = context.createRadialGradient(
          point.x, point.y, 0, point.x, point.y, point.radius * 4
        );
        glow.addColorStop(0, point.color);
        glow.addColorStop(1, 'rgba(0,0,0,0)');
        context.fillStyle = glow;
        context.beginPath();
        context.arc(point.x, point.y, point.radius * 4, 0, Math.PI * 2);
        context.fill();
      }
      context.fillStyle = point.color;
      context.beginPath();
      context.arc(point.x, point.y, point.radius, 0, Math.PI * 2);
      context.fill();
    }
    context.globalAlpha = 1;

    const active = runprint.points[selected];
    context.beginPath();
    context.arc(active.x, active.y, active.radius + 8, 0, Math.PI * 2);
    context.strokeStyle = '#ffffff';
    context.lineWidth = 2;
    context.stroke();
    context.beginPath();
    context.arc(active.x, active.y, active.radius + 13, 0, Math.PI * 2);
    context.strokeStyle = 'rgba(110, 231, 255, 0.42)';
    context.lineWidth = 1;
    context.stroke();
  }

  function requestDraw() {
    if (drawFrame !== null) return;
    drawFrame = window.requestAnimationFrame(() => {
      drawFrame = null;
      draw();
    });
  }

  function resize() {
    if (!story) return;
    const bounds = elements.canvas.getBoundingClientRect();
    runprint = buildRunprint(story, bounds.width, bounds.height);
    elements.signature.textContent = runprint.signature;
    requestDraw();
  }

  function requestResize() {
    if (resizeFrame !== null) return;
    resizeFrame = window.requestAnimationFrame(() => {
      resizeFrame = null;
      resize();
    });
  }

  function selectEvent(index) {
    if (!story || index < 0 || index >= story.events.length) return;
    selected = index;
    const event = story.events[index];
    elements.number.textContent =
      `Signal ${String(index + 1).padStart(3, '0')} / ${story.events.length}`;
    elements.kind.textContent = event.kind;
    elements.chapter.textContent = event.chapter;
    elements.title.textContent = event.title;
    elements.summary.textContent = event.summary;
    elements.location.textContent = event.location;
    elements.badges.textContent = event.badges.length
      ? event.badges.join(', ')
      : 'None';
    elements.party.textContent = event.party_size === null
      ? 'Unknown'
      : `${event.party_size} · peak Lv. ${event.highest_level ?? '—'}`;
    elements.pokedex.textContent =
      `${event.pokedex.caught ?? '—'} caught · ${event.pokedex.seen ?? '—'} seen`;
    elements.clock.textContent = formatClock(event.play_time_seconds);
    elements.signal.textContent = event.coverage_gap_before
      ? 'Resumes after a source gap'
      : event.kind === 'badge'
        ? 'Major milestone'
        : 'Continuous observation';
    elements.scrubber.value = String(index);
    elements.scrubber.setAttribute(
      'aria-valuetext',
      `Signal ${index + 1} of ${story.events.length} — ${event.title}`
    );
    elements.previous.disabled = index === 0;
    elements.next.disabled = index === story.events.length - 1;
    requestDraw();
  }

  function scheduleTrace() {
    if (!tracing || !story) return;
    if (selected >= story.events.length - 1) {
      stopTrace('The complete verified runprint is now visible.');
      return;
    }
    const step = story.events.length > 180 ? 3 : 1;
    traceTimer = setTimeout(() => {
      selectEvent(Math.min(selected + step, story.events.length - 1));
      scheduleTrace();
    }, 90);
  }

  function renderStory(value) {
    story = value;
    selected = 0;
    filter = 'all';
    stopTrace();
    elements.status.hidden = true;
    elements.fallback.hidden = true;
    elements.experience.hidden = false;
    elements.scrubber.max = String(story.events.length - 1);
    elements.statEvents.textContent = story.events.length.toLocaleString('en-US');
    elements.statLocations.textContent =
      new Set(story.events.map(event => event.location)).size.toLocaleString('en-US');
    elements.statBadges.textContent =
      Math.max(...story.events.map(event => event.badges.length));
    const clocks = story.events
      .map(event => event.play_time_seconds)
      .filter(Number.isInteger);
    const finalClock = clocks.length ? Math.max(...clocks) : null;
    elements.statHours.textContent = formatClock(finalClock);
    const kinds = new Set(story.events.map(event => event.kind));
    elements.legendKinds.forEach(item => {
      item.hidden = !kinds.has(item.dataset.kind);
    });
    const hasGaps = story.events.some(event => event.coverage_gap_before);
    elements.legendGap.hidden = !hasGaps;
    const gapFilter = elements.filters.find(
      button => button.dataset.filter === 'gaps'
    );
    gapFilter.disabled = !hasGaps;
    const updated = new Date(story.updated_at).toLocaleString('en-US', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: 'UTC'
    });
    const coverage = [];
    if (story.coverage.incomplete_before) {
      coverage.push('The earliest retained event begins after the run started.');
    }
    if (!story.coverage.continuous_source) {
      coverage.push('Broken paths mark intervals whose source was not retained.');
    }
    coverage.push(
      `This ${story.status === 'completed' ? 'completed' : 'in-progress'} ` +
      `public archive was updated ${updated} UTC.`
    );
    elements.archiveNote.textContent = coverage.join(' ');
    elements.filters.forEach(button => {
      const active = button.dataset.filter === 'all';
      button.classList.toggle('active', active);
      button.setAttribute('aria-pressed', String(active));
    });
    resize();
    selectEvent(story.events.length - 1);
  }

  async function loadStory() {
    const restoreRetryFocus = document.activeElement === elements.retry;
    stopTrace();
    elements.status.hidden = false;
    elements.status.textContent = 'Sequencing the public story archive…';
    elements.experience.hidden = true;
    elements.fallback.hidden = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(STORY_SOURCE, {
        cache: 'no-store',
        credentials: 'omit',
        redirect: 'error',
        referrerPolicy: 'no-referrer',
        signal: controller.signal
      });
      if (!response.ok) throw new Error(`Story request failed (${response.status}).`);
      const text = await response.text();
      if (text.length > MAX_STORY_BYTES) {
        throw new Error('The story archive is too large.');
      }
      renderStory(validateStory(JSON.parse(text)));
    } catch (_error) {
      elements.status.hidden = false;
      elements.status.textContent =
        'Sequencing failed. The public archive may be temporarily unavailable.';
      elements.experience.hidden = true;
      elements.fallback.hidden = false;
      if (restoreRetryFocus) {
        window.requestAnimationFrame(() => elements.retry.focus());
      }
    } finally {
      clearTimeout(timeout);
    }
  }

  elements.filters.forEach(button => {
    button.addEventListener('click', () => {
      filter = button.dataset.filter;
      elements.filters.forEach(item => {
        const active = item === button;
        item.classList.toggle('active', active);
        item.setAttribute('aria-pressed', String(active));
      });
      requestDraw();
    });
  });
  elements.trace.addEventListener('click', () => {
    if (tracing) {
      stopTrace('Run tracing paused.');
      return;
    }
    if (reducedMotion.matches) {
      selectEvent(story.events.length - 1);
      elements.status.hidden = false;
      elements.status.textContent =
        'Trace animation skipped because reduced motion is enabled.';
      return;
    }
    if (selected >= story.events.length - 1) selectEvent(0);
    tracing = true;
    elements.trace.textContent = 'Pause trace';
    elements.status.hidden = false;
    elements.status.textContent = 'Tracing the journey from origin to now…';
    scheduleTrace();
  });
  elements.scrubber.addEventListener('input', () => {
    stopTrace();
    selectEvent(Number(elements.scrubber.value));
  });
  elements.previous.addEventListener('click', () => {
    stopTrace();
    selectEvent(selected - 1);
  });
  elements.next.addEventListener('click', () => {
    stopTrace();
    selectEvent(selected + 1);
  });
  elements.canvas.addEventListener('pointerdown', event => {
    if (!runprint) return;
    const bounds = elements.canvas.getBoundingClientRect();
    const point = nearestPoint(
      runprint.points,
      event.clientX - bounds.left,
      event.clientY - bounds.top,
      filter
    );
    if (point) {
      stopTrace();
      selectEvent(point.index);
    }
  });
  elements.canvas.addEventListener('keydown', event => {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      stopTrace();
      if (event.key === 'Home') selectEvent(0);
      else if (event.key === 'End') selectEvent(story.events.length - 1);
      else selectEvent(selected + (event.key === 'ArrowLeft' ? -1 : 1));
    }
  });
  elements.retry.addEventListener('click', loadStory);
  window.addEventListener('resize', requestResize);
  loadStory();
}

if (typeof globalThis.__RPP_DNA_TEST_HOOK__ === 'function') {
  globalThis.__RPP_DNA_TEST_HOOK__({
    validateStory,
    hash32,
    buildRunprint,
    nearestPoint,
    formatClock
  });
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', initializeJourneyDna);
}
