'use strict';

const vm = require('node:vm');

let hooks = null;
const source = require('node:fs').readFileSync(0, 'utf8');
vm.runInNewContext(source, {
  console,
  setTimeout,
  clearTimeout,
  globalThis: {
    __RPP_DNA_TEST_HOOK__(value) {
      hooks = value;
    }
  }
});

if (!hooks) throw new Error('Journey DNA test hook was not exposed.');

function event(index, overrides = {}) {
  return {
    id: `event-${String(index + 1).padStart(6, '0')}`,
    sequence: index + 1,
    observed_at: new Date(Date.UTC(2026, 6, 17, index)).toISOString(),
    kind: index === 0 ? 'opening' : 'journey',
    chapter: 'Setting Out',
    title: `Event ${index + 1}`,
    summary: 'A verified public event.',
    location: index === 0 ? 'Pallet Town' : 'Route 1',
    badges: [],
    party_size: 1,
    highest_level: 5,
    pokedex: {seen: 2, caught: 1},
    play_time_seconds: index * 600,
    coverage_gap_before: false,
    video: null,
    ...overrides
  };
}

const events = [
  event(0),
  event(1, {
    kind: 'badge',
    location: 'Pewter Gym',
    badges: ['Boulder'],
    coverage_gap_before: true
  }),
  event(2, {kind: 'party', badges: ['Boulder'], party_size: 2})
];
const story = {
  schema_version: 1,
  story_id: 'rappter-plays-pokemon-main-run',
  revision: `sha256:${'a'.repeat(64)}`,
  updated_at: '2026-07-17T03:00:00.000Z',
  status: 'in_progress',
  summary: 'A verified story.',
  coverage: {
    first_observed_at: events[0].observed_at,
    last_observed_at: events[2].observed_at,
    incomplete_before: false,
    continuous_source: false,
    event_count: events.length
  },
  events
};

hooks.validateStory(story);
const offsetOrdered = structuredClone(story);
offsetOrdered.events[0].observed_at = '2026-07-17T01:00:00+02:00';
offsetOrdered.events[1].observed_at = '2026-07-17T00:00:00Z';
offsetOrdered.events[2].observed_at = '2026-07-17T01:00:00Z';
hooks.validateStory(offsetOrdered);
const first = hooks.buildRunprint(story, 900, 600);
const second = hooks.buildRunprint(story, 900, 600);
if (JSON.stringify(first) !== JSON.stringify(second)) {
  throw new Error('Runprint geometry is not deterministic.');
}
if (first.signature !== 'AAAAAAAAAAAA') {
  throw new Error('Archive signature is incorrect.');
}
if (!first.points[1].milestone || !first.points[1].gap) {
  throw new Error('Badge and gap signals were not encoded.');
}
const nearest = hooks.nearestPoint(
  first.points,
  first.points[1].x,
  first.points[1].y,
  'gaps'
);
if (!nearest || nearest.index !== 1) {
  throw new Error('Point hit testing did not respect the active filter.');
}
if (hooks.formatClock(3660) !== '1h 01m') {
  throw new Error('Game clock formatting is incorrect.');
}

const invalid = structuredClone(story);
invalid.events[0].unexpected = 'must be rejected';
let rejected = false;
try {
  hooks.validateStory(invalid);
} catch (_error) {
  rejected = true;
}
if (!rejected) throw new Error('Unknown event fields were accepted.');

process.stdout.write('journey dna contract ok\n');
