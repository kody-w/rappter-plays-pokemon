'use strict';

const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(0, 'utf8');
let api = null;
const context = {
  Set,
  Date,
  Number,
  String,
  Array,
  Object,
  RegExp,
  Error,
  globalThis: null,
  __RPP_STORY_TEST_HOOK__(value) {
    api = value;
  }
};
context.globalThis = context;
vm.runInNewContext(source, context, {filename: 'story.js'});

if (!api || typeof api.validateStory !== 'function') {
  throw new Error('story test API was not exposed');
}

const event = {
  id: 'event-000001',
  sequence: 1,
  observed_at: '2026-07-18T00:00:00Z',
  kind: 'opening',
  chapter: 'Setting Out',
  title: 'Earliest retained chapter',
  summary: '<img src=x onerror=alert(1)> remains literal text',
  location: 'Pallet Town',
  badges: [],
  party_size: 1,
  highest_level: 5,
  pokedex: {seen: 2, caught: 1},
  play_time_seconds: 60,
  coverage_gap_before: false,
  video: null
};
const story = {
  schema_version: 1,
  story_id: 'rappter-plays-pokemon-main-run',
  revision: `sha256:${'a'.repeat(64)}`,
  updated_at: event.observed_at,
  status: 'in_progress',
  summary: 'A grounded story.',
  coverage: {
    first_observed_at: event.observed_at,
    last_observed_at: event.observed_at,
    incomplete_before: false,
    continuous_source: true,
    event_count: 1
  },
  events: [event]
};

if (api.validateStory(story) !== story) {
  throw new Error('valid story was not accepted');
}
if (api.formatPlayTime(3660) !== '1h 01m') {
  throw new Error('play time formatting failed');
}

for (const mutate of [
  value => { value.events[0].raw_manifest = '/private/path'; },
  value => { value.events[0].id = '../escape'; },
  value => { value.events[0].pokedex.caught = 99; },
  value => {
    value.events[0].video = {
      youtube_id: '../hostile',
      start_seconds: 0,
      end_seconds: 30
    };
  },
  value => { value.coverage.event_count = 2; },
  value => { value.schema_version = 2; }
]) {
  const hostile = JSON.parse(JSON.stringify(story));
  mutate(hostile);
  let rejected = false;
  try {
    api.validateStory(hostile);
  } catch (_error) {
    rejected = true;
  }
  if (!rejected) throw new Error('hostile story was accepted');
}
