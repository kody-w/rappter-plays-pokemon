'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {EventEmitter} = require('node:events');
const {PassThrough} = require('node:stream');
const {
  validateBootstrap,
  selectExactTarget,
  discoverBrowser,
  standardBrowserCandidates,
  chromeLaunchArguments,
  waitForDevToolsActivePort,
  CdpConnection,
  waitForVersionedIngress,
  LatestFramePump,
  TelemetryCadence,
  acquireOwnership,
  ownedBrowserGroup,
  terminateDedicatedBrowser,
  reclaimRecordedBrowser,
  garbageCollectProfiles,
  prepareManagedProfile,
  readBroadcastState,
  writeBroadcastState,
  monitorBrowser,
  captureBrowserStderr,
  runString,
  parsePng,
  pageBootstrap,
  sanitizedError
} = require('../scripts/kite_vtwin.js');

const generation = `generation-${'a'.repeat(24)}`;
const instance = `instance-${'b'.repeat(24)}`;
const peerId = `rpp-${'c'.repeat(32)}`;
const capability = 'd'.repeat(43);
const joinUrl =
  `https://example.test/watch/#v=1&host=${peerId}&watch=${capability}`;
const bootstrap = {
  schema_version: 1,
  generation,
  instance,
  host_base: 'https://example.test/host/',
  join_url: joinUrl,
  peer_id: peerId,
  watch_capability: capability,
  max_viewers: 5,
  browser_path: '',
  startup_timeout_seconds: 20,
  parent_pid: process.pid,
  created_at: '2026-07-17T00:00:00.000Z'
};

assert.equal(validateBootstrap(bootstrap).generation, generation);
assert.throws(
  () => validateBootstrap({...bootstrap, extra: true}),
  /schema/
);
assert.throws(
  () => validateBootstrap({...bootstrap, join_url: `${joinUrl}&action=press`}),
  /invitation/
);

const expectedUrl = `https://example.test/host/#v=1&instance=${instance}`;
const exact = {targetId: 'host', type: 'page', url: expectedUrl};
assert.equal(
  selectExactTarget([
    {targetId: 'distractor', type: 'page', url: 'https://example.test/'},
    {targetId: 'worker', type: 'service_worker', url: expectedUrl},
    exact
  ], expectedUrl),
  exact
);
assert.equal(selectExactTarget([], expectedUrl), null);
assert.throws(
  () => selectExactTarget([exact, {...exact, targetId: 'duplicate'}], expectedUrl),
  /ambiguous/
);

const launchArgs = chromeLaunchArguments('/private/profile', expectedUrl);
assert(launchArgs.includes('--remote-debugging-address=127.0.0.1'));
assert(launchArgs.includes('--remote-debugging-port=0'));
assert(launchArgs.includes('--disable-background-timer-throttling'));
assert(launchArgs.includes('--use-mock-keychain'));
assert(launchArgs.includes('--password-store=basic'));
assert(
  chromeLaunchArguments('/private/profile', expectedUrl, 'f'.repeat(48))
    .includes(`--rpp-kite-owner-token=${'f'.repeat(48)}`)
);
assert(launchArgs.includes(expectedUrl));
assert(!launchArgs.some(value => value.includes('no-sandbox')));
assert(!launchArgs.some(value => value.includes('disable-web-security')));
assert(!launchArgs.some(value => value.includes(capability)));
assert.equal(discoverBrowser(process.execPath, {}), path.resolve(process.execPath));
assert.throws(
  () => discoverBrowser('/definitely/missing/chrome', {}),
  /executable/
);
assert(
  standardBrowserCandidates('/Users/example', 'darwin')
    .some(value => value.includes('Chrome for Testing.app'))
);

const pageConfig = pageBootstrap(bootstrap);
assert.equal(pageConfig.peer_id, peerId);
assert.equal(pageConfig.watch_capability, capability);
assert.deepEqual(
  pageConfig.peer_options.config.iceServers,
  [{urls: 'stun:stun.l.google.com:19302'}]
);

const png = Buffer.alloc(33);
Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
  .copy(png, 0);
png.write('IHDR', 12, 'ascii');
png.writeUInt32BE(160, 16);
png.writeUInt32BE(144, 20);
assert.deepEqual(parsePng(png), {width: 160, height: 144});
assert.equal(parsePng(Buffer.alloc(33)), null);

class FakeWebSocket {
  static OPEN = 1;

  constructor() {
    this.readyState = FakeWebSocket.OPEN;
    this.listeners = new Map();
    this.sent = [];
    queueMicrotask(() => this.emit('open', {}));
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  emit(name, value) {
    for (const listener of this.listeners.get(name) || []) listener(value);
  }

  send(raw) {
    this.sent.push(JSON.parse(raw));
  }

  close() {
    this.readyState = 3;
    this.emit('close', {});
  }
}

async function testCdp() {
  const cdp = new CdpConnection('ws://127.0.0.1/devtools', {
    WebSocketImpl: FakeWebSocket,
    timeoutMs: 30
  });
  await cdp.open();
  const first = cdp.request('First.method');
  const second = cdp.request('Second.method');
  assert.equal(cdp.socket.sent[0].id, 1);
  assert.equal(cdp.socket.sent[1].id, 2);
  cdp.socket.emit('message', {
    data: JSON.stringify({id: 2, result: {value: 'second'}})
  });
  cdp.socket.emit('message', {
    data: JSON.stringify({id: 1, result: {value: 'first'}})
  });
  assert.deepEqual(await first, {value: 'first'});
  assert.deepEqual(await second, {value: 'second'});

  const timedOut = cdp.request('Never.responds', {}, undefined, 1);
  await assert.rejects(timedOut, /timed out/);
  assert.equal(cdp.pending.size, 0);

  const controller = new AbortController();
  const cancelled = cdp.request(
    'Cancel.pending',
    {},
    undefined,
    30_000,
    controller.signal
  );
  controller.abort();
  await assert.rejects(cancelled, error => error.name === 'AbortError');
  assert.equal(cdp.pending.size, 0);

  const closing = cdp.request('Close.pending');
  cdp.close();
  await assert.rejects(closing, /closed/);
  assert.equal(cdp.pending.size, 0);
}

async function testDelayedIngress() {
  let evaluations = 0;
  let attachments = 0;
  let detachments = 0;
  const cdp = {
    async request(method) {
      if (method === 'Target.getTargets') {
        return {targetInfos: [{targetId: 'host', type: 'page', url: expectedUrl}]};
      }
      if (method === 'Target.getTargetInfo') {
        return {targetInfo: {targetId: 'host', type: 'page', url: expectedUrl}};
      }
      if (method === 'Target.attachToTarget') {
        attachments += 1;
        return {sessionId: `session-${attachments}`};
      }
      if (method === 'Target.detachFromTarget') {
        detachments += 1;
        return {};
      }
      if (method === 'Runtime.enable') return {};
      if (method === 'Runtime.evaluate') {
        evaluations += 1;
        if (evaluations < 3) return {result: {type: 'undefined'}};
        return {result: {type: 'object', objectId: 'ingress-object'}};
      }
      if (method === 'Runtime.callFunctionOn') {
        return {
          result: {
            value: {
              version: 1,
              build: 'rpp-kite-host-v1',
              instance,
              generation: '',
              bootstrapped: false
            }
          }
        };
      }
      throw new Error(`unexpected method ${method}`);
    }
  };
  const attached = await waitForVersionedIngress(
    cdp,
    expectedUrl,
    instance,
    500
  );
  assert.equal(attached.target.targetId, 'host');
  assert.equal(evaluations, 3);
  assert.equal(attachments, 3);
  assert.equal(detachments, 2);
}

async function testStartupCancellation() {
  const directory = fs.mkdtempSync(
    path.join(process.cwd(), '.kite-cancel-contract-')
  );
  fs.chmodSync(directory, 0o700);
  try {
    const child = new EventEmitter();
    child.stderr = new PassThrough();
    const stderr = captureBrowserStderr(child);
    const monitor = monitorBrowser(child, stderr);
    child.stderr.write(`startup failed near ${joinUrl}\n`);
    await assert.rejects(
      waitForDevToolsActivePort(directory, 5, {monitor}),
      error => {
        assert.match(error.message, /DevTools endpoint timed out/);
        assert(!error.message.includes(capability));
        assert(!error.message.includes('example.test'));
        return true;
      }
    );

    const controller = new AbortController();
    const started = Date.now();
    const waiting = waitForDevToolsActivePort(directory, 120_000, {
      signal: controller.signal
    });
    setTimeout(() => controller.abort(), 5);
    await assert.rejects(waiting, error => error.name === 'AbortError');
    assert(Date.now() - started < 500);
  } finally {
    fs.rmSync(directory, {recursive: true, force: true});
  }
}

async function testParentEofCancelsWholeStartup() {
  const directory = fs.mkdtempSync(
    path.join(process.cwd(), '.kite-parent-contract-')
  );
  fs.chmodSync(directory, 0o700);
  const token = Buffer.alloc(24, 4).toString('hex');
  const profile = path.join(directory, `kite-profile-${generation}`);
  const child = new EventEmitter();
  child.pid = 54321;
  child.exitCode = null;
  child.stderr = new PassThrough();
  child.kill = () => {
    child.exitCode = 0;
  };
  let rows = [{
    pid: child.pid,
    pgid: child.pid,
    start_identity: `identity-${child.pid}`,
    command:
      `chrome --user-data-dir=${profile} --rpp-kite-owner-token=${token}`
  }];
  const signals = [];
  fs.writeFileSync(
    path.join(directory, 'kite-bootstrap.json'),
    JSON.stringify({
      ...bootstrap,
      browser_path: process.execPath,
      startup_timeout_seconds: 120,
      parent_pid: process.pid
    })
  );
  const started = Date.now();
  const originalOn = process.stdin.on;
  const originalResume = process.stdin.resume;
  let eofHandler = null;
  process.stdin.on = function(name, listener) {
    if (name === 'end') eofHandler = listener;
    if (name === 'end' || name === 'error') return this;
    return originalOn.call(this, name, listener);
  };
  process.stdin.resume = function() {
    return this;
  };
  try {
    const running = runString(directory, {
      spawn: () => child,
      processIdentity: pid => `identity-${pid}`,
      processAlive: async () => true,
      randomBytes: () => Buffer.alloc(24, 4),
      processTable: () => rows,
      kill(pid, signal) {
        signals.push([pid, signal]);
        rows = [];
        child.exitCode = 0;
      }
    });
    const owner = path.join(directory, 'kite-browser-owner.json');
    const hostStatus = path.join(directory, 'kite-host-status.json');
    const deadline = Date.now() + 1000;
    while (
      (!fs.existsSync(owner) || !fs.existsSync(hostStatus)) &&
      Date.now() < deadline
    ) {
      await new Promise(resolve => setTimeout(resolve, 2));
    }
    assert.equal(fs.existsSync(owner), true);
    assert.equal(fs.existsSync(hostStatus), true);
    assert.equal(typeof eofHandler, 'function');
    eofHandler();
    await running;
    assert(Date.now() - started < 500);
    assert.deepEqual(signals, [[-child.pid, 'SIGTERM']]);
    assert.equal(fs.existsSync(path.join(directory, 'kite-string.lock')), false);
    assert.equal(fs.existsSync(profile), false);
  } finally {
    process.stdin.on = originalOn;
    process.stdin.resume = originalResume;
    fs.rmSync(directory, {recursive: true, force: true});
  }
}

async function testOwnershipAndProfiles() {
  const directory = fs.mkdtempSync(
    path.join(process.cwd(), '.kite-owner-contract-')
  );
  fs.chmodSync(directory, 0o700);
  const identity = pid => (
    pid === process.pid ? 'self-start' : 'parent-start'
  );
  const options = {
    instance,
    parentPid: process.ppid,
    processIdentity: identity,
    processAlive: async () => true,
    randomBytes: () => Buffer.alloc(24, 1)
  };
  try {
    const release = await acquireOwnership(directory, generation, options);
    await assert.rejects(
      acquireOwnership(directory, generation, options),
      /another CDP string/
    );
    assert.equal(await release(), true);

    const lock = path.join(directory, 'kite-string.lock');
    fs.mkdirSync(lock);
    fs.writeFileSync(path.join(lock, 'owner.json'), JSON.stringify({
      schema_version: 1,
      token: 'a'.repeat(48),
      generation,
      instance,
      pid: process.pid,
      process_start_identity: 'reused-pid-start',
      parent_pid: process.ppid,
      parent_start_identity: 'parent-start',
      created_at: new Date().toISOString()
    }));
    const reclaimed = await acquireOwnership(directory, generation, {
      ...options,
      randomBytes: () => Buffer.alloc(24, 2)
    });
    assert.equal(await reclaimed(), true);

    const guarded = await acquireOwnership(directory, generation, {
      ...options,
      randomBytes: () => Buffer.alloc(24, 3)
    });
    const guardedOwnerPath = path.join(
      directory,
      'kite-string.lock',
      'owner.json'
    );
    const replacedOwner = JSON.parse(fs.readFileSync(guardedOwnerPath));
    replacedOwner.token = 'f'.repeat(48);
    fs.writeFileSync(guardedOwnerPath, JSON.stringify(replacedOwner));
    assert.equal(await guarded(), false);
    assert.equal(
      fs.existsSync(path.join(directory, 'kite-string.lock')),
      true
    );
    fs.rmSync(
      path.join(directory, 'kite-string.lock'),
      {recursive: true, force: true}
    );

    const current = await prepareManagedProfile(
      directory,
      bootstrap,
      'b'.repeat(48),
      {processTable: () => []}
    );
    const oldGeneration = `generation-${'z'.repeat(24)}`;
    const old = path.join(directory, `kite-profile-${oldGeneration}`);
    fs.mkdirSync(old);
    fs.writeFileSync(
      path.join(old, 'rpp-kite-profile.json'),
      JSON.stringify({
        schema_version: 1,
        generation: oldGeneration,
        instance,
        token: 'c'.repeat(48),
        created_at: new Date().toISOString()
      })
    );
    const staleRecord = {
      schema_version: 1,
      generation: oldGeneration,
      instance,
      token: 'c'.repeat(48),
      pid: 6200,
      pgid: 6200,
      start_identity: 'Fri Jul 17 01:00:00 2026',
      profile: old,
      created_at: new Date().toISOString()
    };
    fs.writeFileSync(
      path.join(directory, 'kite-browser-owner.json'),
      JSON.stringify(staleRecord)
    );
    let staleRows = [{
      pid: 6201,
      pgid: 6200,
      start_identity: 'Fri Jul 17 01:00:01 2026',
      command:
        `chrome --user-data-dir=${old} ` +
        `--rpp-kite-owner-token=${'c'.repeat(48)}`
    }];
    await reclaimRecordedBrowser(directory, {
      processTable: () => staleRows,
      kill() {
        staleRows = [];
      }
    });
    assert.equal(
      fs.existsSync(path.join(directory, 'kite-browser-owner.json')),
      false
    );
    const unowned = path.join(
      directory,
      `kite-profile-generation-${'u'.repeat(24)}`
    );
    fs.mkdirSync(unowned);
    const arbitrary = path.join(directory, 'user-chrome-profile');
    fs.mkdirSync(arbitrary);
    await garbageCollectProfiles(directory, generation, {
      processTable: () => []
    });
    assert.equal(fs.existsSync(old), false);
    assert.equal(fs.existsSync(current), true);
    assert.equal(fs.existsSync(unowned), true);
    assert.equal(fs.existsSync(arbitrary), true);

    const initial = await readBroadcastState(directory, bootstrap);
    assert.equal(initial.desired, true);
    const ended = await writeBroadcastState(
      directory,
      bootstrap,
      1,
      false
    );
    assert.equal(ended.desired, false);
    assert.equal(
      pageBootstrap(bootstrap, ended).broadcast_desired,
      false
    );
    fs.writeFileSync(
      path.join(directory, 'kite-broadcast-state.json'),
      '{"corrupt":true}'
    );
    assert.equal(
      (await readBroadcastState(directory, bootstrap)).desired,
      false
    );
  } finally {
    fs.rmSync(directory, {recursive: true, force: true});
  }
}

async function testBrowserLifecycle() {
  const token = 'e'.repeat(48);
  const profile = '/private/kite-profile';
  const record = {
    schema_version: 1,
    generation,
    instance,
    token,
    pid: 4100,
    pgid: 4100,
    start_identity: 'Fri Jul 17 01:00:00 2026',
    profile,
    created_at: new Date().toISOString()
  };
  const ownedCommand =
    `chrome --user-data-dir=${profile} --rpp-kite-owner-token=${token}`;
  const reused = ownedBrowserGroup(record, {
    processTable: () => [{
      pid: 4100,
      pgid: 4100,
      start_identity: 'Fri Jul 17 02:00:00 2026',
      command: ownedCommand
    }]
  });
  assert.deepEqual(reused, []);
  const orphanedChildren = [{
    pid: 4101,
    pgid: 4100,
    start_identity: 'Fri Jul 17 01:00:01 2026',
    command: ownedCommand
  }];
  assert.equal(
    ownedBrowserGroup(record, {
      processTable: () => orphanedChildren
    }).length,
    1
  );
  let rows = [...orphanedChildren];
  const signals = [];
  await terminateDedicatedBrowser(
    {child: {exitCode: 0}, record},
    20,
    {
      processTable: () => rows,
      kill(pid, signal) {
        signals.push([pid, signal]);
        rows = [];
      }
    }
  );
  assert.deepEqual(signals, [[-4100, 'SIGTERM']]);

  const child = new EventEmitter();
  child.stderr = new PassThrough();
  const stderr = captureBrowserStderr(child);
  const monitor = monitorBrowser(child, stderr);
  child.stderr.write(`failed ${joinUrl}\n`);
  child.emit('error', {code: 'ENOENT'});
  await assert.rejects(monitor.failed, error => {
    assert.equal(error.code, 'ENOENT');
    assert(!error.message.includes(capability));
    assert(!error.message.includes('example.test'));
    return true;
  });
}

async function testLatestWins() {
  const sends = [];
  let release;
  const firstPending = new Promise(resolve => {
    release = resolve;
  });
  const pump = new LatestFramePump(async frame => {
    sends.push(frame.sha256);
    if (sends.length === 1) await firstPending;
    return {ok: true};
  }, {intervalMs: 1});
  pump.submit({sha256: 'a'});
  await new Promise(resolve => setTimeout(resolve, 2));
  pump.submit({sha256: 'b'});
  pump.submit({sha256: 'c'});
  pump.submit({sha256: 'c'});
  assert.deepEqual(sends, ['a']);
  release();
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.deepEqual(sends, ['a', 'c']);
  pump.submit({sha256: 'c'});
  await new Promise(resolve => setTimeout(resolve, 2));
  assert.deepEqual(sends, ['a', 'c']);
  pump.close();
}

async function testTelemetryCadence() {
  let now = 0;
  const sent = [];
  const cadence = new TelemetryCadence(async envelope => {
    sent.push(envelope.sequence);
    return {ok: true};
  }, {clock: () => now, changeMs: 1000, heartbeatMs: 5000});
  cadence.submit({sequence: 1, snapshot: {value: 1}});
  assert.equal(await cadence.tick(), true);
  cadence.submit({sequence: 2, snapshot: {value: 2}});
  now = 999;
  assert.equal(await cadence.tick(), false);
  now = 1000;
  assert.equal(await cadence.tick(), true);
  cadence.submit({sequence: 3, snapshot: {value: 2}});
  now = 5999;
  assert.equal(await cadence.tick(), false);
  now = 6000;
  assert.equal(await cadence.tick(), true);
  assert.deepEqual(sent, [1, 2, 3]);
}

async function main() {
  await testCdp();
  await testDelayedIngress();
  await testStartupCancellation();
  await testParentEofCancelsWholeStartup();
  await testOwnershipAndProfiles();
  await testBrowserLifecycle();
  await testLatestWins();
  await testTelemetryCadence();
  const sanitized = sanitizedError(
    `failed https://example.test/#watch=${capability}`
  );
  assert(!sanitized.includes(capability));
  assert(!sanitized.includes('example.test'));
  assert.equal(path.isAbsolute(__filename), true);
  process.stdout.write('kite string contracts passed\n');
}

main().catch(error => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
