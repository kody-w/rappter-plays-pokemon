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

class Element {
  constructor(id) {
    this.id = id;
    this.hidden = false;
    this.disabled = false;
    this.textContent = '';
    this.className = '';
    this.value = '';
    this.dataset = {};
    this.children = [];
    this.listeners = new Map();
    this.srcObject = null;
    this.readyState = 0;
    this.paused = true;
    this.currentTime = 0;
    this.classList = {add: () => {}, remove: () => {}, toggle: () => {}};
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  async emit(name) {
    for (const listener of this.listeners.get(name) || []) {
      await listener({});
    }
  }

  replaceChildren() {
    this.children = [];
  }

  appendChild(child) {
    this.children.push(child);
  }

  setAttribute() {}
  focus() {}
  async play() {}
}

class FakePc {
  constructor() {
    this.connectionState = 'new';
    this.iceConnectionState = 'new';
    this.listeners = new Map();
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  close() {
    this.connectionState = 'closed';
  }
}

async function run() {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  const badges = [
    'Boulder', 'Cascade', 'Thunder', 'Rainbow',
    'Soul', 'Marsh', 'Volcano', 'Earth'
  ].map(name => {
    const badge = new Element(name);
    badge.dataset.badge = name;
    return badge;
  });
  const shareCalls = [];
  const returnLink =
    'https://example.test/host/v2/return/#v=2&mode=manual-return&answer=x';
  const rawAnswer = 'rpp-answer-v2.encrypted';
  const pc = new FakePc();
  const channel = {
    label: 'rpp-telemetry-v2',
    readyState: 'connecting',
    listeners: new Map(),
    addEventListener(name, listener) {
      const listeners = this.listeners.get(name) || [];
      listeners.push(listener);
      this.listeners.set(name, listeners);
    },
    emit(name) {
      for (const listener of this.listeners.get(name) || []) listener({});
    },
    close: () => {},
    send: () => {}
  };
  const pairing = {
    async parseManualOfferFragment() {
      return {pair: 'pair-token', expires: 1_900_000_000};
    },
    async createManualAnswer(options) {
      options.onPeerConnection(pc);
      options.onChannel(channel);
      return {
        pc,
        text: rawAnswer,
        returnLink,
        qrSafe: true
      };
    },
    async selectedCandidateType() {
      return 'host';
    }
  };
  const location = {
    hash: '#v=2&mode=manual-offer&fragment-only=yes',
    pathname: '/watch/v2/'
  };
  const context = {
    document: {
      getElementById: element,
      querySelectorAll: selector => selector === '[data-badge]' ? badges : [],
      createElement: name => new Element(name),
      head: {appendChild: () => {}}
    },
    window: {addEventListener: () => {}},
    location,
    history: {replaceState: () => {}},
    performance: {now: () => 0},
    crypto: global.crypto,
    TextEncoder,
    TextDecoder,
    URL,
    URLSearchParams,
    Blob,
    Uint8Array,
    atob,
    btoa,
    setInterval: () => ({}),
    clearInterval: () => {},
    setTimeout,
    clearTimeout,
    navigator: {
      clipboard: {writeText: async () => {}},
      share: async value => {
        shareCalls.push(value);
      }
    },
    QRious: class {
      constructor(options) {
        assert.equal(options.value, returnLink);
      }
    },
    RppPairing: pairing,
    console
  };
  context.globalThis = context;
  vm.runInNewContext(source, context, {filename: 'SPECTATOR_JS'});
  await new Promise(resolve => setTimeout(resolve, 20));

  assert.equal(element('manual-answer-text').value, returnLink);
  assert.equal(element('manual-raw-answer').value, rawAnswer);
  assert.equal(element('manual-answer').hidden, false);
  await element('share-manual-answer').emit('click');
  assert.deepEqual(
    JSON.parse(JSON.stringify(shareCalls)),
    [{url: returnLink}]
  );
  assert.match(
    element('manual-answer-note').textContent,
    /streamer Mac/
  );
  channel.emit('close');
  await new Promise(resolve => setImmediate(resolve));
  assert.match(element('headline').textContent, /Manual connection ended/);
  assert.match(element('detail').textContent, /fresh single-use/);

  process.stdout.write('manual share UX contracts passed\n');
}
