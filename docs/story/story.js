'use strict';

const STORY_SOURCE = 'https://raw.githubusercontent.com/kody-w/rappter-plays-pokemon/refs/heads/story-archive/v1/story.json';
const MAX_STORY_BYTES = 1024 * 1024;
const MAX_EVENTS = 512;
const EVENT_SECONDS = 8;
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

function timestamp(value) {
  return boundedText(value, 48) && Number.isFinite(Date.parse(value));
}

function validateEvent(event, seenIds, previous) {
  if (!exactKeys(event, EVENT_KEYS) ||
      !/^event-\d{6,}$/u.test(event.id) ||
      seenIds.has(event.id) ||
      !Number.isInteger(event.sequence) ||
      event.sequence < 1 ||
      !timestamp(event.observed_at) ||
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
  if (event.video !== null) {
    if (!exactKeys(event.video, ['youtube_id', 'start_seconds', 'end_seconds']) ||
        !/^[A-Za-z0-9_-]{11}$/u.test(event.video.youtube_id) ||
        !Number.isInteger(event.video.start_seconds) ||
        !Number.isInteger(event.video.end_seconds) ||
        event.video.start_seconds < 0 ||
        event.video.end_seconds <= event.video.start_seconds ||
        event.video.end_seconds > event.video.start_seconds + 1200 ||
        event.video.end_seconds > 10001200) {
      throw new Error('The story contains an invalid theater clip.');
    }
  }
  const order = `${event.observed_at}\n${String(event.sequence).padStart(8, '0')}`;
  if (previous !== null && order <= previous) {
    throw new Error('The story events are not ordered.');
  }
  seenIds.add(event.id);
  return order;
}

function validateStory(value) {
  if (!exactKeys(value, STORY_KEYS) ||
      value.schema_version !== 1 ||
      value.story_id !== 'rappter-plays-pokemon-main-run' ||
      !/^sha256:[0-9a-f]{64}$/u.test(value.revision) ||
      !timestamp(value.updated_at) ||
      !['in_progress', 'completed'].includes(value.status) ||
      !boundedText(value.summary, 1000) ||
      !exactKeys(value.coverage, COVERAGE_KEYS) ||
      !timestamp(value.coverage.first_observed_at) ||
      !timestamp(value.coverage.last_observed_at) ||
      typeof value.coverage.incomplete_before !== 'boolean' ||
      typeof value.coverage.continuous_source !== 'boolean' ||
      !Array.isArray(value.events) ||
      value.events.length < 1 ||
      value.events.length > MAX_EVENTS ||
      value.coverage.event_count !== value.events.length) {
    throw new Error('The public story archive has an invalid schema.');
  }
  const ids = new Set();
  let previous = null;
  for (const event of value.events) {
    previous = validateEvent(event, ids, previous);
  }
  return value;
}

function formatPlayTime(seconds) {
  if (!Number.isInteger(seconds) || seconds < 0) return 'Unknown';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${String(minutes).padStart(2, '0')}m`;
}

function initializeStoryPlayer() {
  const elements = {
    status: document.getElementById('story-status'),
    player: document.getElementById('story-player'),
    fallback: document.getElementById('story-fallback'),
    retry: document.getElementById('retry-story'),
    storySummary: document.getElementById('story-summary'),
    coverage: document.getElementById('coverage-note'),
    chapter: document.getElementById('event-chapter'),
    title: document.getElementById('event-title'),
    counter: document.getElementById('event-counter'),
    summary: document.getElementById('event-summary'),
    gap: document.getElementById('event-gap'),
    theaterFrame: document.getElementById('theater-frame'),
    theaterPlaceholder: document.getElementById('theater-placeholder'),
    location: document.getElementById('event-location'),
    badges: document.getElementById('event-badges'),
    pokedex: document.getElementById('event-pokedex'),
    playTime: document.getElementById('event-play-time'),
    progress: document.getElementById('story-progress'),
    previous: document.getElementById('previous-event'),
    play: document.getElementById('play-story'),
    next: document.getElementById('next-event'),
    list: document.getElementById('event-list')
  };
  let story = null;
  let selected = 0;
  let playing = false;
  let timer = null;
  let timelineButtons = [];

  function stopPlayback(message) {
    playing = false;
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    elements.play.textContent = 'Play story';
    if (message) elements.status.textContent = message;
  }

  function scheduleNext() {
    if (!playing || !story) return;
    if (selected >= story.events.length - 1) {
      stopPlayback('You are caught up with the published story.');
      return;
    }
    timer = setTimeout(() => {
      selectEvent(selected + 1);
      scheduleNext();
    }, EVENT_SECONDS * 1000);
  }

  function selectEvent(index) {
    if (!story || index < 0 || index >= story.events.length) return;
    selected = index;
    const event = story.events[index];
    elements.chapter.textContent = event.chapter;
    elements.title.textContent = event.title;
    elements.counter.textContent = `${index + 1} / ${story.events.length}`;
    elements.summary.textContent = event.summary;
    elements.gap.hidden = !event.coverage_gap_before;
    if (event.video === null) {
      elements.theaterFrame.removeAttribute('src');
      elements.theaterFrame.hidden = true;
      elements.theaterPlaceholder.hidden = false;
    } else {
      const video = event.video;
      elements.theaterFrame.src =
        `https://www.youtube-nocookie.com/embed/${video.youtube_id}` +
        `?start=${video.start_seconds}&end=${video.end_seconds}&rel=0`;
      elements.theaterFrame.hidden = false;
      elements.theaterPlaceholder.hidden = true;
    }
    elements.location.textContent = event.location;
    elements.badges.textContent = event.badges.length
      ? event.badges.join(', ')
      : 'None recorded';
    const seen = event.pokedex.seen === null ? '—' : event.pokedex.seen;
    const caught = event.pokedex.caught === null ? '—' : event.pokedex.caught;
    elements.pokedex.textContent = `${caught} caught · ${seen} seen`;
    elements.playTime.textContent = formatPlayTime(event.play_time_seconds);
    elements.progress.value = String(index);
    elements.previous.disabled = index === 0;
    elements.next.disabled = index === story.events.length - 1;
    timelineButtons.forEach((button, buttonIndex) => {
      if (buttonIndex === index) {
        button.setAttribute('aria-current', 'true');
      } else {
        button.removeAttribute('aria-current');
      }
    });
  }

  function renderTimeline() {
    timelineButtons = story.events.map((event, index) => {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      const title = document.createElement('span');
      title.className = 'timeline-title';
      title.textContent = event.title;
      const chapter = document.createElement('span');
      chapter.className = 'timeline-chapter';
      chapter.textContent = event.chapter;
      button.append(title, chapter);
      button.addEventListener('click', () => {
        stopPlayback('Story paused.');
        selectEvent(index);
      });
      item.append(button);
      elements.list.append(item);
      return button;
    });
  }

  function renderStory(value) {
    story = value;
    selected = 0;
    stopPlayback('');
    elements.status.hidden = true;
    elements.fallback.hidden = true;
    elements.player.hidden = false;
    elements.storySummary.textContent = story.summary;
    const coverageNotes = [];
    if (story.coverage.incomplete_before) {
      coverageNotes.push(
        'The earliest retained source starts after the run began; the archive never invents missing opening events.'
      );
    }
    if (!story.coverage.continuous_source) {
      coverageNotes.push(
        'Some source clips are no longer retained, so the timeline marks known coverage gaps.'
      );
    }
    elements.coverage.textContent = coverageNotes.length
      ? coverageNotes.join(' ')
      : 'The retained source is continuous from the opening of this published story.';
    elements.progress.max = String(story.events.length - 1);
    elements.list.replaceChildren();
    renderTimeline();
    selectEvent(0);
  }

  async function loadStory() {
    stopPlayback('');
    elements.status.hidden = false;
    elements.status.textContent = 'Loading the public story archive…';
    elements.player.hidden = true;
    elements.fallback.hidden = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(`${STORY_SOURCE}?v=${Date.now()}`, {
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
      elements.status.hidden = true;
      elements.player.hidden = true;
      elements.fallback.hidden = false;
    } finally {
      clearTimeout(timeout);
    }
  }

  elements.previous.addEventListener('click', () => {
    stopPlayback('Story paused.');
    selectEvent(selected - 1);
  });
  elements.next.addEventListener('click', () => {
    stopPlayback('Story paused.');
    selectEvent(selected + 1);
  });
  elements.progress.addEventListener('input', () => {
    stopPlayback('Story paused.');
    selectEvent(Number(elements.progress.value));
  });
  elements.play.addEventListener('click', () => {
    if (playing) {
      stopPlayback('Story paused.');
      return;
    }
    if (selected >= story.events.length - 1) selectEvent(0);
    playing = true;
    elements.play.textContent = 'Pause story';
    elements.status.hidden = false;
    elements.status.textContent = 'Playing the story from this chapter.';
    scheduleNext();
  });
  elements.retry.addEventListener('click', loadStory);
  loadStory();
}

if (typeof globalThis.__RPP_STORY_TEST_HOOK__ === 'function') {
  globalThis.__RPP_STORY_TEST_HOOK__({validateStory, formatPlayTime});
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', initializeStoryPlayer);
}
