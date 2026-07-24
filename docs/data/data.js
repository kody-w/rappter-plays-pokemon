'use strict';

const rawBase =
  'https://raw.githubusercontent.com/kody-w/rappter-plays-pokemon/' +
  'refs/heads/story-warehouse';
const registryUrl = rawBase + '/registry.json';

function text(id, value) {
  document.getElementById(id).textContent = String(value);
}

function link(id, value) {
  const element = document.getElementById(id);
  element.href = value;
  element.rel = 'noopener noreferrer';
}

function validRegistry(value) {
  return Boolean(
    value &&
    value.schema === 'rapp-static-api/1.0' &&
    Array.isArray(value.entries) &&
    value.entries.some(entry =>
      entry &&
      entry.name === 'warehouse' &&
      /^[0-9a-f]{64}$/.test(entry.sha256)
    )
  );
}

async function load() {
  const response = await fetch(registryUrl, {
    cache: 'no-store',
    credentials: 'omit',
    referrerPolicy: 'no-referrer'
  });
  if (!response.ok) throw new Error('Warehouse registry is unavailable.');
  const registry = await response.json();
  if (!validRegistry(registry)) throw new Error('Warehouse registry is invalid.');
  const entry = registry.entries.find(item => item.name === 'warehouse');
  const statusResponse = await fetch(entry.status_url, {
    cache: 'no-store',
    credentials: 'omit',
    referrerPolicy: 'no-referrer'
  });
  if (!statusResponse.ok) throw new Error('Warehouse status is unavailable.');
  const status = await statusResponse.json();
  if (
    status.schema !== 'rappter-pokemon-warehouse-status/1.0' ||
    status.database_sha256 !== entry.sha256
  ) {
    throw new Error('Warehouse status failed its integrity contract.');
  }

  text('state', status.status);
  text('source', status.source_head.slice(0, 12));
  text('commits', status.counts.source_commits);
  text('events', status.counts.logical_events);
  text('receipts', status.counts.execution_receipts);
  text('digest', entry.sha8);
  link('database-link', entry.src_url);
  link('manifest-link', entry.manifest_url);
  link(
    'datasette-link',
    'https://lite.datasette.io/?url=' + encodeURIComponent(entry.src_url)
  );
}

load().catch(error => {
  text('state', 'unavailable');
  text('error', error instanceof Error ? error.message : 'Warehouse unavailable.');
});
