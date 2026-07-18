'use strict';

const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(0, 'utf8');
let api = null;
const context = {
  Date,
  Math,
  Number,
  RegExp,
  Set,
  String,
  URLSearchParams,
  Error,
  globalThis: null,
  __RPP_DIAGNOSTICS_TEST_HOOK__(value) {
    api = value;
  }
};
context.globalThis = context;
vm.runInNewContext(source, context, {filename: 'diagnostics.js'});

if (!api || typeof api.parseDiagnostic !== 'function') {
  throw new Error('diagnostics test API was not exposed');
}

const fragment =
  '#v=1&s=4&d=200&a=99.5&f=20&h=8&c=20.0&i=3.4&e=1.00&u=120' +
  '&r=medium&t=1784394163&g=p&q=3&w=r&z=2';
const snapshot = api.parseDiagnostic(fragment);
if (
  snapshot.sync !== 4 ||
  snapshot.reasoning !== 'medium' ||
  snapshot.hintState !== 'prompted' ||
  snapshot.navigation !== 3 ||
  snapshot.webState !== 'ready' ||
  snapshot.webSources !== 2
) {
  throw new Error('valid diagnostics were not decoded');
}
if (api.metricHealth(snapshot) !== 'good') {
  throw new Error('healthy diagnostics were misclassified');
}
if (api.metricHealth(api.parseDiagnostic('#v=1')) !== 'unknown') {
  throw new Error('missing diagnostics were misclassified as healthy');
}
const issue = new URL(api.buildIssueUrl(snapshot));
if (
  issue.origin !== 'https://github.com' ||
  issue.pathname !== '/kody-w/rappter-plays-pokemon/issues/new' ||
  !issue.searchParams.get('body').includes('A/V clock drift: 4 ms') ||
  !issue.searchParams.get('body').includes('Reasoning effort: medium') ||
  !issue.searchParams.get('body').includes('Crowd hint gate: prompted') ||
  !issue.searchParams.get('body').includes('Navigation memory entries: 3') ||
  !issue.searchParams.get('body').includes('Autonomous web recovery: ready')
) {
  throw new Error('draft issue URL is incomplete');
}

for (const hostile of [
  '#v=2',
  '#v=1&token=secret',
  '#v=1&s=99999',
  '#v=1&r=unbounded',
  '#v=1&g=hostile',
  '#v=1&q=1000',
  '#v=1&w=hostile',
  '#v=1&z=11',
  '#v=1&t=1'
]) {
  let rejected = false;
  try {
    api.parseDiagnostic(hostile);
  } catch (_error) {
    rejected = true;
  }
  if (!rejected) throw new Error(`hostile fragment was accepted: ${hostile}`);
}
