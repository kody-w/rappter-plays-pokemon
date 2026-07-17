'use strict';

const assert = require('node:assert/strict');
const vm = require('node:vm');

let source = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => {
  source += chunk;
});
process.stdin.on('end', () => run().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
}));

function base64url(value) {
  return Buffer.from(JSON.stringify(value)).toString('base64url');
}

async function run() {
  assert(!source.includes('fetch('));
  assert(!source.includes('XMLHttpRequest'));
  const callback = {
    origin: 'http://127.0.0.1:45678',
    path: '/pair-return'
  };
  const params = new URLSearchParams({
    v: '2',
    mode: 'manual-return',
    gen: `generation-${'g'.repeat(24)}`,
    cb: base64url(callback),
    rt: Buffer.alloc(32, 8).toString('base64url'),
    answer: 'rpp-answer-v2.encrypted'
  });
  const fragment = `#${params}`;
  const elements = new Map([
    ['return-status', {textContent: ''}],
    ['handoff', {href: '', hidden: true}]
  ]);
  let historyValue = null;
  let replaced = null;
  const location = {
    hash: fragment,
    pathname: '/host/v2/return/',
    replace(value) {
      replaced = value;
    }
  };
  const timers = [];
  const context = {
    document: {getElementById: id => elements.get(id)},
    location,
    history: {
      replaceState(_state, _title, value) {
        historyValue = value;
      }
    },
    URL,
    URLSearchParams,
    atob,
    setTimeout(callback, delay) {
      timers.push({callback, delay});
    }
  };
  context.globalThis = context;
  vm.runInNewContext(source, context, {filename: 'RETURN_JS'});

  const expected =
    `http://127.0.0.1:45678/pair-return${fragment}`;
  assert.equal(elements.get('handoff').href, expected);
  assert.equal(elements.get('handoff').hidden, false);
  assert.equal(historyValue, '/host/v2/return/');
  assert.equal(timers.length, 1);
  assert.equal(timers[0].delay, 250);
  timers[0].callback();
  assert.equal(replaced, expected);
  assert(
    expected.slice(0, expected.indexOf('#')).endsWith('/pair-return'),
    'the Pages request URL never contains the fragment payload'
  );

  process.stdout.write('return page contracts passed\n');
}
