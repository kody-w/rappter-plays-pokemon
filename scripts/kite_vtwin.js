#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawn, spawnSync} = require('node:child_process');

const STRING_VERSION = 2;
const HOST_BUILD = 'rpp-kite-host-v2';
const MAX_FRAME_BYTES = 128 * 1024;
const FRAME_INTERVAL_MS = 100;
const RPC_TIMEOUT_MS = 10000;
const BOOTSTRAP_FILE = 'kite-bootstrap.json';
const FRAME_MANIFEST_FILE = 'kite-frame.json';
const TELEMETRY_FILE = 'kite-telemetry.json';
const COMMAND_FILE = 'kite-command.json';
const HOST_STATUS_FILE = 'kite-host-status.json';
const LIVESTREAM_STATUS_FILE = 'livestream-status.json';
const BROWSER_OWNER_FILE = 'kite-browser-owner.json';
const BROADCAST_STATE_FILE = 'kite-broadcast-state.json';
const HOST_IDENTITY_FILE = 'kite-host-identity.json';
const MANUAL_RETURN_DIRECTORY = 'kite-manual-return';
const LOCK_DIRECTORY = 'kite-string.lock';
const PROFILE_MARKER_FILE = 'rpp-kite-profile.json';
const IDENTIFIER = /^[A-Za-z0-9_-]{16,128}$/;
const OWNER_TOKEN = /^[a-f0-9]{32,64}$/;
const FRAME_FAILURE_LIMIT = 3;
const MAX_MANUAL_ANSWER_BYTES = 384 * 1024;
const MAX_BROWSER_STDERR_BYTES = 4096;
const REVIEWED_RELAYS = Object.freeze([
  'wss://communities.nos.social',
  'wss://purplerelay.com',
  'wss://bucket.coracle.social',
  'wss://relay.nostr.place',
  'wss://relay.damus.io'
]);

function abortError() {
  const error = new Error('operation aborted');
  error.name = 'AbortError';
  error.code = 'ABORT_ERR';
  return error;
}

function throwIfAborted(signal) {
  if (!signal || !signal.aborted) return;
  throw signal.reason instanceof Error ? signal.reason : abortError();
}

function sleep(milliseconds, signal) {
  throwIfAborted(signal);
  return new Promise((resolve, reject) => {
    let timer = null;
    const aborted = () => {
      if (timer !== null) clearTimeout(timer);
      reject(signal.reason instanceof Error ? signal.reason : abortError());
    };
    timer = setTimeout(() => {
      if (signal) signal.removeEventListener('abort', aborted);
      resolve();
    }, milliseconds);
    if (signal) signal.addEventListener('abort', aborted, {once: true});
  });
}

function remainingMilliseconds(deadline) {
  return Math.max(0, deadline - Date.now());
}

function exactKeys(value, keys) {
  return Boolean(
    value &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join(',') === [...keys].sort().join(',')
  );
}

function boundedInteger(value, minimum, maximum) {
  return Number.isSafeInteger(value) && value >= minimum && value <= maximum;
}

function sanitizedError(error) {
  const known = error && typeof error.code === 'string' ? error.code : '';
  if (/^[A-Z0-9_]{2,40}$/.test(known)) return known.toLowerCase();
  const message = String(error && error.message || error || 'unknown');
  const safe = message
    .replace(/https?:\/\/\S+/gi, '[url]')
    .replace(/#[^\s]+/g, '#[fragment]')
    .replace(/[A-Za-z0-9_-]{32,}/g, '[identifier]')
    .replace(/[^\x20-\x7e]/g, '')
    .slice(0, 120);
  return safe || 'unknown';
}

function parseArguments(argv) {
  if (
    argv.length === 5 &&
    argv[0] === '--initialize-identity' &&
    argv[1] === '--runtime-dir' &&
    typeof argv[2] === 'string' &&
    path.isAbsolute(argv[2]) &&
    argv[3] === '--generation' &&
    IDENTIFIER.test(argv[4] || '')
  ) {
    return {
      mode: 'initialize-identity',
      runtimeDir: path.resolve(argv[2]),
      generation: argv[4]
    };
  }
  if (
    argv.length !== 2 ||
    argv[0] !== '--runtime-dir' ||
    typeof argv[1] !== 'string' ||
    !path.isAbsolute(argv[1])
  ) {
    throw new Error('usage: --runtime-dir ABSOLUTE_PATH');
  }
  return {mode: 'run', runtimeDir: path.resolve(argv[1])};
}

async function assertPrivateDirectory(directory) {
  const resolved = await fsp.realpath(directory);
  if (resolved !== directory) throw new Error('runtime directory must be canonical');
  const metadata = await fsp.lstat(directory);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new Error('runtime directory must be a real directory');
  }
  if ((metadata.mode & 0o077) !== 0) {
    throw new Error('runtime directory permissions are not private');
  }
  if (typeof process.getuid === 'function' && metadata.uid !== process.getuid()) {
    throw new Error('runtime directory has a different owner');
  }
}

async function readBoundedFile(file, maximum) {
  const metadata = await fsp.lstat(file);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > maximum) {
    throw new Error('bounded file validation failed');
  }
  return fsp.readFile(file);
}

async function readJson(file, maximum = 32 * 1024) {
  const payload = await readBoundedFile(file, maximum);
  const value = JSON.parse(payload.toString('utf8'));
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('JSON object required');
  }
  return value;
}

async function atomicWriteJson(file, value) {
  const serialized = `${JSON.stringify(value, null, 2)}\n`;
  if (Buffer.byteLength(serialized) > 32 * 1024) {
    throw new Error('status output exceeded bound');
  }
  const temporary = path.join(
    path.dirname(file),
    `.${path.basename(file)}.${process.pid}.tmp`
  );
  const handle = await fsp.open(
    temporary,
    fs.constants.O_WRONLY |
      fs.constants.O_CREAT |
      fs.constants.O_TRUNC |
      fs.constants.O_EXCL,
    0o600
  );
  try {
    await handle.writeFile(serialized, 'utf8');
    await handle.sync();
  } finally {
    await handle.close();
  }
  await fsp.rename(temporary, file);
  await fsp.chmod(file, 0o600);
}

function canonicalJson(value) {
  const visit = item => {
    if (
      item === null ||
      typeof item === 'string' ||
      typeof item === 'boolean'
    ) return JSON.stringify(item);
    if (typeof item === 'number' && Number.isFinite(item)) {
      return JSON.stringify(item);
    }
    if (Array.isArray(item)) return `[${item.map(visit).join(',')}]`;
    if (item && typeof item === 'object') {
      return `{${Object.keys(item).sort().map(
        key => `${JSON.stringify(key)}:${visit(item[key])}`
      ).join(',')}}`;
    }
    throw new Error('value is not canonical JSON');
  };
  return visit(value);
}

function publicJwk(value) {
  return {
    crv: 'P-256',
    ext: true,
    key_ops: ['verify'],
    kty: 'EC',
    x: value.x,
    y: value.y
  };
}

function privateJwk(value) {
  return {
    crv: 'P-256',
    d: value.d,
    ext: true,
    key_ops: ['sign'],
    kty: 'EC',
    x: value.x,
    y: value.y
  };
}

function hostPublicKeyToken(value) {
  return Buffer.from(canonicalJson(value), 'utf8').toString('base64url');
}

function hostFingerprint(hostPublicKey, generation) {
  return crypto.createHash('sha256')
    .update(Buffer.from(`rpp-host-signing-v2\0${generation}\0`, 'ascii'))
    .update(Buffer.from(canonicalJson(hostPublicKey), 'utf8'))
    .digest('hex')
    .slice(0, 32);
}

function validEcCoordinate(value) {
  return canonicalToken(value, 32);
}

function validHostIdentity(value, generation = value && value.generation) {
  if (!exactKeys(value, [
    'created_at', 'fingerprint', 'generation', 'host_private_jwk',
    'host_public_jwk', 'host_public_key', 'schema_version'
  ])) return false;
  const publicKey = value.host_public_jwk;
  const privateKey = value.host_private_jwk;
  return Boolean(
    value.schema_version === STRING_VERSION &&
    value.generation === generation &&
    IDENTIFIER.test(value.generation || '') &&
    exactKeys(publicKey, ['crv', 'ext', 'key_ops', 'kty', 'x', 'y']) &&
    exactKeys(
      privateKey,
      ['crv', 'd', 'ext', 'key_ops', 'kty', 'x', 'y']
    ) &&
    publicKey.crv === 'P-256' &&
    privateKey.crv === 'P-256' &&
    publicKey.kty === 'EC' &&
    privateKey.kty === 'EC' &&
    publicKey.ext === true &&
    privateKey.ext === true &&
    Array.isArray(publicKey.key_ops) &&
    publicKey.key_ops.length === 1 &&
    publicKey.key_ops[0] === 'verify' &&
    Array.isArray(privateKey.key_ops) &&
    privateKey.key_ops.length === 1 &&
    privateKey.key_ops[0] === 'sign' &&
    validEcCoordinate(publicKey.x) &&
    validEcCoordinate(publicKey.y) &&
    validEcCoordinate(privateKey.x) &&
    validEcCoordinate(privateKey.y) &&
    validEcCoordinate(privateKey.d) &&
    privateKey.x === publicKey.x &&
    privateKey.y === publicKey.y &&
    value.host_public_key === hostPublicKeyToken(publicKey) &&
    value.fingerprint === hostFingerprint(publicKey, value.generation) &&
    typeof value.created_at === 'string' &&
    value.created_at.length <= 48 &&
    Number.isFinite(Date.parse(value.created_at))
  );
}

async function ensureHostIdentity(runtimeDir, generation) {
  const identityPath = path.join(runtimeDir, HOST_IDENTITY_FILE);
  try {
    const existing = await readJson(identityPath, 16 * 1024);
    if (validHostIdentity(existing, generation)) return existing;
    if (validHostIdentity(existing)) {
      await fsp.unlink(identityPath);
    } else {
      throw new Error('generation host identity is invalid');
    }
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  const keys = await crypto.webcrypto.subtle.generateKey(
    {name: 'ECDSA', namedCurve: 'P-256'},
    true,
    ['sign', 'verify']
  );
  const exportedPublic = publicJwk(
    await crypto.webcrypto.subtle.exportKey('jwk', keys.publicKey)
  );
  const exportedPrivate = privateJwk(
    await crypto.webcrypto.subtle.exportKey('jwk', keys.privateKey)
  );
  const identity = {
    schema_version: STRING_VERSION,
    generation,
    host_public_jwk: exportedPublic,
    host_private_jwk: exportedPrivate,
    host_public_key: hostPublicKeyToken(exportedPublic),
    fingerprint: hostFingerprint(exportedPublic, generation),
    created_at: new Date().toISOString()
  };
  if (!validHostIdentity(identity, generation)) {
    throw new Error('generated host identity failed validation');
  }
  await atomicWriteJson(identityPath, identity);
  return identity;
}

function normalizeHttpsBase(raw, name) {
  let url;
  try {
    url = new URL(raw);
  } catch (_error) {
    throw new Error(`${name} is invalid`);
  }
  if (
    url.protocol !== 'https:' ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new Error(`${name} must be an uncredentialed HTTPS base`);
  }
  if (!url.pathname.endsWith('/')) url.pathname += '/';
  return url.toString();
}

function canonicalToken(value, bytes) {
  if (
    typeof value !== 'string' ||
    !/^[A-Za-z0-9_-]+$/.test(value)
  ) return false;
  try {
    const decoded = Buffer.from(value, 'base64url');
    return decoded.length === bytes &&
      decoded.toString('base64url') === value;
  } catch (_error) {
    return false;
  }
}

function parseHostPublicKeyToken(value) {
  try {
    const serialized = Buffer.from(value, 'base64url').toString('utf8');
    if (
      Buffer.from(serialized, 'utf8').toString('base64url') !== value
    ) return null;
    const parsed = JSON.parse(serialized);
    if (
      canonicalJson(parsed) !== serialized ||
      !exactKeys(parsed, ['crv', 'ext', 'key_ops', 'kty', 'x', 'y']) ||
      parsed.crv !== 'P-256' ||
      parsed.kty !== 'EC' ||
      parsed.ext !== true ||
      !Array.isArray(parsed.key_ops) ||
      parsed.key_ops.length !== 1 ||
      parsed.key_ops[0] !== 'verify' ||
      !validEcCoordinate(parsed.x) ||
      !validEcCoordinate(parsed.y)
    ) return null;
    return parsed;
  } catch (_error) {
    return null;
  }
}

function validManualCallback(value) {
  if (!exactKeys(value, ['origin', 'path'])) return false;
  try {
    const url = new URL(value.origin);
    return Boolean(
      url.protocol === 'http:' &&
      url.hostname === '127.0.0.1' &&
      url.port &&
      Number(url.port) <= 65535 &&
      url.pathname === '/' &&
      !url.search &&
      !url.hash &&
      !url.username &&
      !url.password &&
      url.origin === value.origin &&
      value.path === '/pair-return'
    );
  } catch (_error) {
    return false;
  }
}

function validateJoinUrl(raw, config) {
  let url;
  try {
    url = new URL(raw);
  } catch (_error) {
    return false;
  }
  const parameters = new URLSearchParams(url.hash.slice(1));
  if (!(
    url.protocol === 'https:' &&
    !url.username &&
    !url.password &&
    !url.search
  )) return false;
  if (config.signaling === 'nostr') {
    return Boolean(
      [...parameters.keys()].sort().join(',') === 'fp,gen,key,pub,room,v' &&
      parameters.get('v') === '2' &&
      parameters.get('room') === config.room_id &&
      parameters.get('key') === config.room_key &&
      parameters.get('gen') === config.generation &&
      parameters.get('pub') === config.host_public_key &&
      parameters.get('fp') === config.host_fingerprint
    );
  }
  return Boolean(
    [...parameters.keys()].sort().join(',') === 'host,v,watch' &&
    parameters.get('v') === '1' &&
    parameters.get('host') === config.peer_id &&
    parameters.get('watch') === config.watch_capability
  );
}

function validateBootstrap(value) {
  const legacy = exactKeys(value, [
    'browser_path', 'created_at', 'generation', 'host_base', 'instance',
    'join_url', 'max_viewers', 'parent_pid', 'peer_id',
    'schema_version', 'startup_timeout_seconds', 'watch_capability'
  ]);
  const nostr = exactKeys(value, [
    'browser_path', 'created_at', 'generation', 'host_base',
    'host_fingerprint', 'host_public_key', 'instance', 'join_url',
    'manual_callback', 'manual_return_page', 'manual_return_token',
    'max_viewers', 'parent_pid', 'relay_urls', 'room_id', 'room_key',
    'schema_version', 'signaling', 'startup_timeout_seconds'
  ]);
  if (!legacy && !nostr) {
    throw new Error('bootstrap schema mismatch');
  }
  if (
    value.schema_version !== STRING_VERSION ||
    !IDENTIFIER.test(value.generation || '') ||
    !/^[A-Za-z0-9_-]{16,64}$/.test(value.instance || '') ||
    (
      legacy &&
      (
        !/^rpp-[a-f0-9]{32}$/.test(value.peer_id || '') ||
        !/^[A-Za-z0-9_-]{32,128}$/.test(value.watch_capability || '')
      )
    ) ||
    (
      nostr &&
      (
        value.signaling !== 'nostr' ||
        !canonicalToken(value.room_id, 16) ||
        !canonicalToken(value.room_key, 32) ||
        !canonicalToken(value.manual_return_token, 32) ||
        !validManualCallback(value.manual_callback) ||
        typeof value.manual_return_page !== 'string' ||
        value.manual_return_page.length > 512 ||
        !parseHostPublicKeyToken(value.host_public_key) ||
        !/^[a-f0-9]{32}$/.test(value.host_fingerprint || '') ||
        value.host_fingerprint !== hostFingerprint(
          parseHostPublicKeyToken(value.host_public_key),
          value.generation
        ) ||
        !Array.isArray(value.relay_urls) ||
        value.relay_urls.length !== REVIEWED_RELAYS.length ||
        value.relay_urls.some(
          (url, index) => url !== REVIEWED_RELAYS[index]
        )
      )
    ) ||
    !boundedInteger(value.max_viewers, 1, 8) ||
    !boundedInteger(value.parent_pid, 1, 2 ** 31 - 1) ||
    typeof value.created_at !== 'string' ||
    value.created_at.length > 48 ||
    !Number.isFinite(Date.parse(value.created_at)) ||
    typeof value.browser_path !== 'string' ||
    value.browser_path.length > 1024 ||
    typeof value.startup_timeout_seconds !== 'number' ||
    !Number.isFinite(value.startup_timeout_seconds) ||
    value.startup_timeout_seconds < 2 ||
    value.startup_timeout_seconds > 120
  ) {
    throw new Error('bootstrap values are invalid');
  }
  const hostBase = normalizeHttpsBase(value.host_base, 'host base');
  let manualReturnPage = value.manual_return_page;
  if (nostr) {
    manualReturnPage = normalizeHttpsBase(
      value.manual_return_page,
      'manual return page'
    );
    if (!new URL(manualReturnPage).pathname.endsWith('/return/')) {
      throw new Error('manual return page must end in /return/');
    }
  }
  if (!validateJoinUrl(value.join_url, value)) {
    throw new Error('watch invitation is invalid');
  }
  return {
    ...value,
    host_base: hostBase,
    ...(nostr ? {manual_return_page: manualReturnPage} : {})
  };
}

function standardBrowserCandidates(home = os.homedir(), platform = process.platform) {
  if (platform === 'darwin') {
    return [
      '/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
      '/Applications/Chromium.app/Contents/MacOS/Chromium',
      path.join(
        home,
        'Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'
      ),
      path.join(
        home,
        'Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
      ),
      path.join(home, 'Applications/Chromium.app/Contents/MacOS/Chromium')
    ];
  }
  if (platform === 'linux') {
    return [
      '/usr/bin/google-chrome',
      '/usr/bin/google-chrome-stable',
      '/usr/bin/chromium',
      '/usr/bin/chromium-browser'
    ];
  }
  return [];
}

function executableFile(candidate) {
  if (!candidate) return false;
  try {
    const metadata = fs.lstatSync(candidate);
    fs.accessSync(candidate, fs.constants.X_OK);
    return metadata.isFile() && !metadata.isSymbolicLink();
  } catch (_error) {
    return false;
  }
}

function discoverBrowser(override, environment = process.env, options = {}) {
  const explicit = override || environment.RPP_BROWSER_PATH ||
    environment.CHROME_PATH || '';
  if (explicit) {
    const resolved = path.resolve(explicit);
    if (!executableFile(resolved)) {
      throw new Error('configured browser is not an executable regular file');
    }
    return resolved;
  }
  const candidates = standardBrowserCandidates(
    options.home || os.homedir(),
    options.platform || process.platform
  );
  for (const candidate of candidates) {
    if (executableFile(candidate)) return candidate;
  }
  throw new Error('no supported Chrome or Chromium browser was found');
}

function chromeLaunchArguments(profile, hostUrl, ownerToken = '') {
  const arguments_ = [
    `--user-data-dir=${profile}`,
    '--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0',
    '--no-first-run',
    '--no-default-browser-check',
    '--use-mock-keychain',
    '--password-store=basic',
    '--disable-background-timer-throttling',
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--autoplay-policy=no-user-gesture-required'
  ];
  if (ownerToken) {
    if (!OWNER_TOKEN.test(ownerToken)) throw new Error('invalid browser owner token');
    arguments_.push(`--rpp-kite-owner-token=${ownerToken}`);
  }
  arguments_.push('--new-window', hostUrl);
  return arguments_;
}

function captureBrowserStderr(child, maximum = MAX_BROWSER_STDERR_BYTES) {
  let stderr = '';
  if (child && child.stderr && typeof child.stderr.on === 'function') {
    child.stderr.on('data', chunk => {
      stderr = `${stderr}${String(chunk)}`.slice(-maximum);
    });
  }
  return () => sanitizedError(stderr.trim());
}

function monitorBrowser(child, stderr = () => '') {
  let failure = null;
  let rejectFailure;
  const failed = new Promise((_resolve, reject) => {
    rejectFailure = reject;
  });
  failed.catch(() => {});
  const fail = error => {
    if (failure) return;
    const detail = stderr();
    const message = detail
      ? `${error.message}: ${detail}`
      : error.message;
    failure = new Error(message);
    if (error.code) failure.code = error.code;
    rejectFailure(failure);
  };
  child.once('error', error => {
    const launchError = new Error('dedicated browser spawn failed');
    launchError.code = (
      error && typeof error.code === 'string'
        ? error.code
        : 'BROWSER_SPAWN'
    );
    fail(launchError);
  });
  child.once('exit', (code, signal) => {
    const suffix = signal
      ? ` by ${String(signal).slice(0, 16)}`
      : ` with code ${Number.isInteger(code) ? code : 'unknown'}`;
    fail(new Error(`dedicated browser exited${suffix}`));
  });
  return {
    failed,
    throwIfFailed() {
      if (failure) throw failure;
    },
    failure() {
      return failure;
    },
    detail() {
      return stderr();
    }
  };
}

async function raceBrowser(promise, options = {}) {
  const contenders = [promise];
  if (options.monitor) contenders.push(options.monitor.failed);
  let abortListener = null;
  if (options.signal) {
    contenders.push(new Promise((_resolve, reject) => {
      if (options.signal.aborted) {
        reject(
          options.signal.reason instanceof Error
            ? options.signal.reason
            : abortError()
        );
        return;
      }
      abortListener = () => {
        reject(
          options.signal.reason instanceof Error
            ? options.signal.reason
            : abortError()
        );
      };
      options.signal.addEventListener('abort', abortListener, {once: true});
    }));
  }
  try {
    const result = await Promise.race(contenders);
    throwIfAborted(options.signal);
    if (options.monitor) options.monitor.throwIfFailed();
    return result;
  } finally {
    if (options.signal && abortListener) {
      options.signal.removeEventListener('abort', abortListener);
    }
  }
}

async function waitForDevToolsActivePort(
  profile,
  timeoutMilliseconds,
  options = {}
) {
  const activePort = path.join(profile, 'DevToolsActivePort');
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    throwIfAborted(options.signal);
    if (options.monitor) options.monitor.throwIfFailed();
    try {
      const raw = await raceBrowser(
        readBoundedFile(activePort, 1024),
        options
      );
      const lines = raw.toString('ascii').trim().split(/\r?\n/);
      const port = Number(lines[0]);
      const socketPath = lines[1];
      if (
        lines.length === 2 &&
        boundedInteger(port, 1, 65535) &&
        /^\/devtools\/browser\/[A-Za-z0-9-]+$/.test(socketPath)
      ) {
        return {port, socketPath};
      }
    } catch (_error) {
      throwIfAborted(options.signal);
      if (options.monitor) options.monitor.throwIfFailed();
      // The dedicated browser has not published its endpoint yet.
    }
    await raceBrowser(sleep(50, options.signal), options);
  }
  throwIfAborted(options.signal);
  if (options.monitor) options.monitor.throwIfFailed();
  const detail = options.monitor && options.monitor.detail();
  throw new Error(
    detail
      ? `dedicated browser DevTools endpoint timed out: ${detail}`
      : 'dedicated browser DevTools endpoint timed out'
  );
}

function selectExactTarget(targetInfos, expectedUrl) {
  const matches = targetInfos.filter(target =>
    target &&
    target.type === 'page' &&
    target.url === expectedUrl &&
    typeof target.targetId === 'string'
  );
  if (matches.length > 1) {
    throw new Error('ambiguous exact Pages host targets');
  }
  return matches.length === 1 ? matches[0] : null;
}

class CdpConnection {
  constructor(url, options = {}) {
    this.url = url;
    this.WebSocketImpl = options.WebSocketImpl || globalThis.WebSocket;
    this.timeoutMs = options.timeoutMs || RPC_TIMEOUT_MS;
    this.signal = options.signal || null;
    this.socket = null;
    this.nextId = 0;
    this.pending = new Map();
    this.listeners = new Map();
    this.closed = false;
  }

  async open(signal = this.signal) {
    throwIfAborted(signal);
    if (typeof this.WebSocketImpl !== 'function') {
      throw new Error('Node.js WebSocket support is unavailable');
    }
    const socket = new this.WebSocketImpl(this.url);
    this.socket = socket;
    await new Promise((resolve, reject) => {
      let settled = false;
      const finish = callback => value => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (signal) signal.removeEventListener('abort', aborted);
        callback(value);
      };
      const timer = setTimeout(() => {
        finish(reject)(new Error('CDP WebSocket open timed out'));
        try { socket.close(); } catch (_error) {}
      }, this.timeoutMs);
      const aborted = () => {
        finish(reject)(
          signal.reason instanceof Error ? signal.reason : abortError()
        );
        try { socket.close(); } catch (_error) {}
      };
      socket.addEventListener('open', () => {
        finish(resolve)();
      }, {once: true});
      socket.addEventListener('error', () => {
        finish(reject)(new Error('CDP WebSocket failed'));
      }, {once: true});
      if (signal) signal.addEventListener('abort', aborted, {once: true});
    });
    throwIfAborted(signal);
    socket.addEventListener('message', event => this._message(event));
    socket.addEventListener('close', () => this._close('CDP WebSocket closed'));
    socket.addEventListener('error', () => this._close('CDP WebSocket failed'));
  }

  _message(event) {
    let message;
    try {
      message = JSON.parse(
        typeof event.data === 'string' ? event.data : String(event.data)
      );
    } catch (_error) {
      this._close('invalid CDP message');
      return;
    }
    if (Number.isSafeInteger(message.id)) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (pending.signal && pending.aborted) {
        pending.signal.removeEventListener('abort', pending.aborted);
      }
      if (message.error) {
        const error = new Error('CDP method failed');
        error.code = 'CDP_METHOD_FAILED';
        pending.reject(error);
      } else {
        pending.resolve(message.result || {});
      }
      return;
    }
    if (typeof message.method !== 'string') return;
    for (const listener of this.listeners.get(message.method) || []) {
      listener(message.params || {}, message.sessionId);
    }
  }

  _close(reason) {
    if (this.closed) return;
    this.closed = true;
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      if (pending.signal && pending.aborted) {
        pending.signal.removeEventListener('abort', pending.aborted);
      }
      pending.reject(new Error(reason));
    }
    this.pending.clear();
    for (const listener of this.listeners.get('close') || []) listener({reason});
  }

  on(method, listener) {
    const listeners = this.listeners.get(method) || [];
    listeners.push(listener);
    this.listeners.set(method, listeners);
  }

  request(
    method,
    params = {},
    sessionId = undefined,
    timeoutMs = this.timeoutMs,
    signal = this.signal
  ) {
    try {
      throwIfAborted(signal);
    } catch (error) {
      return Promise.reject(error);
    }
    if (
      this.closed ||
      !this.socket ||
      this.socket.readyState !== this.WebSocketImpl.OPEN
    ) {
      return Promise.reject(new Error('CDP connection is not open'));
    }
    const id = ++this.nextId;
    const message = {id, method, params};
    if (sessionId) message.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      const cleanup = () => {
        const pending = this.pending.get(id);
        if (pending && pending.signal && pending.aborted) {
          pending.signal.removeEventListener('abort', pending.aborted);
        }
      };
      const timer = setTimeout(() => {
        cleanup();
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, timeoutMs);
      const aborted = () => {
        cleanup();
        clearTimeout(timer);
        this.pending.delete(id);
        reject(signal.reason instanceof Error ? signal.reason : abortError());
      };
      this.pending.set(id, {resolve, reject, timer, signal, aborted});
      if (signal) signal.addEventListener('abort', aborted, {once: true});
      try {
        this.socket.send(JSON.stringify(message));
      } catch (_error) {
        clearTimeout(timer);
        cleanup();
        this.pending.delete(id);
        reject(new Error('CDP send failed'));
      }
    });
  }

  close() {
    if (!this.closed) {
      try { this.socket.close(); } catch (_error) {}
      this._close('CDP connection closed');
    }
  }
}

async function waitForExactTarget(
  cdp,
  expectedUrl,
  timeoutMilliseconds,
  options = {}
) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    throwIfAborted(options.signal);
    const result = await raceBrowser(
      cdp.request('Target.getTargets', {}, undefined, undefined, options.signal),
      options
    );
    const target = selectExactTarget(result.targetInfos || [], expectedUrl);
    if (target) return target;
    await raceBrowser(sleep(100, options.signal), options);
  }
  throwIfAborted(options.signal);
  throw new Error('exact Pages host target was not found');
}

class IngressClient {
  constructor(cdp, sessionId, objectId) {
    this.cdp = cdp;
    this.sessionId = sessionId;
    this.objectId = objectId;
    this.functions = {
      bootstrap: 'function(value) { return this.bootstrap(value); }',
      frame: 'function(value) { return this.frame(value); }',
      telemetry: 'function(value) { return this.telemetry(value); }',
      heartbeat: 'function(value) { return this.heartbeat(value); }',
      broadcast: 'function(value) { return this.broadcast(value); }',
      manualAnswer: 'function(value) { return this.manualAnswer(value); }',
      shutdown: 'function(value) { return this.shutdown(value); }',
      status: 'function() { return this.status(); }'
    };
  }

  async call(method, value = undefined, timeoutMs = RPC_TIMEOUT_MS) {
    const functionDeclaration = this.functions[method];
    if (!functionDeclaration) throw new Error('unsupported ingress method');
    const parameters = {
      objectId: this.objectId,
      functionDeclaration,
      arguments: value === undefined ? [] : [{value}],
      awaitPromise: true,
      returnByValue: true,
      silent: true
    };
    const result = await this.cdp.request(
      'Runtime.callFunctionOn',
      parameters,
      this.sessionId,
      timeoutMs
    );
    if (result.exceptionDetails) {
      throw new Error(`host ingress ${method} failed`);
    }
    const returned = result.result && result.result.value;
    if (
      !returned ||
      typeof returned !== 'object' ||
      Array.isArray(returned) ||
      Buffer.byteLength(JSON.stringify(returned)) > 4096
    ) {
      throw new Error(`host ingress ${method} returned invalid status`);
    }
    return returned;
  }
}

function transientIngressError(message) {
  const error = new Error(message);
  error.code = 'INGRESS_TRANSIENT';
  return error;
}

async function detachSession(cdp, sessionId, signal) {
  if (!sessionId) return;
  try {
    await cdp.request(
      'Target.detachFromTarget',
      {sessionId},
      undefined,
      1000,
      signal && !signal.aborted ? signal : undefined
    );
  } catch (_error) {
    // Target or connection teardown already detached the session.
  }
}

async function attachIngress(
  cdp,
  target,
  expectedUrl,
  instance,
  options = {}
) {
  let sessionId = '';
  try {
    throwIfAborted(options.signal);
    const before = await cdp.request(
      'Target.getTargetInfo',
      {targetId: target.targetId},
      undefined,
      undefined,
      options.signal
    );
    if (
      !before.targetInfo ||
      before.targetInfo.type !== 'page' ||
      before.targetInfo.url !== expectedUrl
    ) {
      throw new Error('Pages host target changed before attachment');
    }
    const attached = await cdp.request('Target.attachToTarget', {
      targetId: target.targetId,
      flatten: true
    }, undefined, undefined, options.signal);
    if (typeof attached.sessionId !== 'string') {
      throw transientIngressError('target attachment is not ready');
    }
    sessionId = attached.sessionId;
    await cdp.request('Runtime.enable', {}, sessionId, undefined, options.signal);
    const evaluated = await cdp.request('Runtime.evaluate', {
      expression: 'globalThis.__RPP_KITE_HOST_V2__',
      objectGroup: 'rpp-kite-host-v2',
      includeCommandLineAPI: false,
      returnByValue: false,
      silent: true
    }, sessionId, undefined, options.signal);
    if (
      evaluated.exceptionDetails ||
      !evaluated.result ||
      evaluated.result.type !== 'object' ||
      typeof evaluated.result.objectId !== 'string'
    ) {
      throw transientIngressError('versioned host ingress is not ready');
    }
    const ingress = new IngressClient(
      cdp,
      sessionId,
      evaluated.result.objectId
    );
    let status;
    try {
      status = await ingress.call('status');
    } catch (error) {
      if (error && error.code === 'ABORT_ERR') throw error;
      throw transientIngressError('versioned host ingress context changed');
    }
    if (
      status.version !== STRING_VERSION ||
      status.build !== HOST_BUILD ||
      status.instance !== instance
    ) {
      throw new Error('Pages host build or selector mismatch');
    }
    if (
      status.bootstrapped === true &&
      (
        options.allowBootstrapped !== true ||
        (
          options.generation &&
          status.generation !== options.generation
        )
      )
    ) {
      throw new Error('Pages host is owned by a different bootstrap');
    }
    if (status.bootstrapped !== false && status.bootstrapped !== true) {
      throw new Error('Pages host returned an invalid bootstrap state');
    }
    const current = await cdp.request('Target.getTargetInfo', {
      targetId: target.targetId
    }, undefined, undefined, options.signal);
    if (
      !current.targetInfo ||
      current.targetInfo.type !== 'page' ||
      current.targetInfo.url !== expectedUrl
    ) {
      throw new Error('Pages host navigated during attachment');
    }
    return {ingress, sessionId, status};
  } catch (error) {
    await detachSession(cdp, sessionId, options.signal);
    if (error && error.code === 'CDP_METHOD_FAILED') {
      throw transientIngressError('versioned host execution context is not ready');
    }
    throw error;
  }
}

async function waitForVersionedIngress(
  cdp,
  expectedUrl,
  instance,
  timeoutMilliseconds,
  options = {}
) {
  const deadline = Date.now() + timeoutMilliseconds;
  let selectedTargetId = options.targetId || '';
  let lastTransient = null;
  while (Date.now() < deadline) {
    throwIfAborted(options.signal);
    if (options.monitor) options.monitor.throwIfFailed();
    const result = await raceBrowser(
      cdp.request(
        'Target.getTargets',
        {},
        undefined,
        undefined,
        options.signal
      ),
      options
    );
    const target = selectExactTarget(result.targetInfos || [], expectedUrl);
    if (!target) {
      if (selectedTargetId) {
        throw new Error('managed Pages host target changed');
      }
      await raceBrowser(sleep(50, options.signal), options);
      continue;
    }
    if (selectedTargetId && target.targetId !== selectedTargetId) {
      throw new Error('managed Pages host target identity changed');
    }
    selectedTargetId = target.targetId;
    try {
      const attached = await attachIngress(
        cdp,
        target,
        expectedUrl,
        instance,
        options
      );
      const verified = await cdp.request(
        'Target.getTargets',
        {},
        undefined,
        undefined,
        options.signal
      );
      const current = selectExactTarget(
        verified.targetInfos || [],
        expectedUrl
      );
      if (!current || current.targetId !== selectedTargetId) {
        await detachSession(cdp, attached.sessionId, options.signal);
        throw new Error('managed Pages host changed during ingress discovery');
      }
      return {...attached, target: current};
    } catch (error) {
      if (!error || error.code !== 'INGRESS_TRANSIENT') throw error;
      lastTransient = error;
    }
    await raceBrowser(sleep(50, options.signal), options);
  }
  throwIfAborted(options.signal);
  if (lastTransient) {
    throw new Error('versioned Pages host ingress startup timed out');
  }
  throw new Error('exact Pages host target was not found');
}

function parsePng(buffer) {
  if (
    !Buffer.isBuffer(buffer) ||
    buffer.length < 33 ||
    buffer.length > MAX_FRAME_BYTES ||
    !buffer.subarray(0, 8).equals(
      Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
    ) ||
    buffer.toString('ascii', 12, 16) !== 'IHDR'
  ) return null;
  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20)
  };
}

function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

async function readStableFrame(runtimeDir, generation, minimumSequence = 0) {
  const manifestPath = path.join(runtimeDir, FRAME_MANIFEST_FILE);
  const framePath = path.join(runtimeDir, 'latest.png');
  const first = await readJson(manifestPath, 4096);
  if (!exactKeys(first, [
    'bytes', 'generation', 'schema_version', 'sequence', 'sha256', 'updated_at'
  ])) return null;
  if (
    first.schema_version !== STRING_VERSION ||
    first.generation !== generation ||
    !boundedInteger(first.sequence, 1, Number.MAX_SAFE_INTEGER) ||
    first.sequence <= minimumSequence ||
    !boundedInteger(first.bytes, 33, MAX_FRAME_BYTES) ||
    !/^[a-f0-9]{64}$/.test(first.sha256 || '')
  ) return null;
  const payload = await readBoundedFile(framePath, MAX_FRAME_BYTES);
  const second = await readJson(manifestPath, 4096);
  if (JSON.stringify(first) !== JSON.stringify(second)) return null;
  const dimensions = parsePng(payload);
  if (
    !dimensions ||
    dimensions.width !== 160 ||
    dimensions.height !== 144 ||
    payload.length !== first.bytes ||
    sha256(payload) !== first.sha256
  ) return null;
  return {
    generation,
    instance: '',
    sequence: first.sequence,
    sha256: first.sha256,
    png_base64: payload.toString('base64')
  };
}

function validTelemetryFile(value, generation) {
  if (!exactKeys(value, [
    'generation', 'schema_version', 'sequence', 'snapshot', 'updated_at'
  ])) return false;
  return Boolean(
    value.schema_version === STRING_VERSION &&
    value.generation === generation &&
    boundedInteger(value.sequence, 1, Number.MAX_SAFE_INTEGER) &&
    value.snapshot &&
    typeof value.snapshot === 'object' &&
    !Array.isArray(value.snapshot) &&
    Buffer.byteLength(JSON.stringify(value.snapshot)) <= 4096
  );
}

class LatestFramePump {
  constructor(send, options = {}) {
    this.send = send;
    this.intervalMs = options.intervalMs || FRAME_INTERVAL_MS;
    this.clock = options.clock || (() => Date.now());
    this.setTimer = options.setTimer || setTimeout;
    this.pending = null;
    this.inFlight = false;
    this.lastSentAt = -Infinity;
    this.lastSentHash = '';
    this.lastSentSequence = 0;
    this.lastAttemptedHash = '';
    this.lastAttemptedSequence = 0;
    this.consecutiveFailures = 0;
    this.inFlightHash = '';
    this.timer = null;
    this.closed = false;
    this.onResult = options.onResult || (() => {});
  }

  submit(frame) {
    if (
      this.closed ||
      !frame ||
      frame.sha256 === this.lastSentHash ||
      frame.sha256 === this.inFlightHash ||
      (this.pending && frame.sha256 === this.pending.sha256)
    ) return false;
    this.pending = frame;
    this._schedule();
    return true;
  }

  _schedule() {
    if (this.closed || this.inFlight || this.timer || !this.pending) return;
    const delay = Math.max(
      0,
      this.intervalMs - (this.clock() - this.lastSentAt)
    );
    this.timer = this.setTimer(() => {
      this.timer = null;
      this._drain();
    }, delay);
  }

  async _drain() {
    if (this.closed || this.inFlight || !this.pending) return;
    const frame = this.pending;
    this.pending = null;
    this.inFlight = true;
    this.inFlightHash = frame.sha256;
    this.lastAttemptedHash = frame.sha256;
    this.lastAttemptedSequence = frame.sequence || 0;
    let result = null;
    let failure = null;
    try {
      result = await this.send(frame);
      if (result && result.ok) {
        this.lastSentHash = frame.sha256;
        this.lastSentSequence = frame.sequence || 0;
        this.lastSentAt = this.clock();
        this.consecutiveFailures = 0;
      } else {
        this.consecutiveFailures += 1;
      }
    } catch (error) {
      failure = error;
      this.consecutiveFailures += 1;
    } finally {
      try {
        this.onResult(frame, result, failure, this.consecutiveFailures);
      } catch (_error) {
        // Result observers cannot break the single-flight pump.
      }
      this.inFlight = false;
      this.inFlightHash = '';
      this._schedule();
    }
  }

  close() {
    this.closed = true;
    this.pending = null;
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
}

class TelemetryCadence {
  constructor(send, options = {}) {
    this.send = send;
    this.clock = options.clock || (() => Date.now());
    this.changeMs = options.changeMs || 1000;
    this.heartbeatMs = options.heartbeatMs || 5000;
    this.lastHash = '';
    this.lastSentAt = -Infinity;
    this.inFlight = false;
    this.pending = null;
  }

  submit(envelope) {
    const hash = sha256(Buffer.from(JSON.stringify(envelope.snapshot)));
    this.pending = {envelope, hash};
  }

  async tick() {
    if (!this.pending || this.inFlight) return false;
    const now = this.clock();
    const changed = this.pending.hash !== this.lastHash;
    const required = changed ? this.changeMs : this.heartbeatMs;
    if (now - this.lastSentAt < required) return false;
    const pending = this.pending;
    this.inFlight = true;
    try {
      const result = await this.send(pending.envelope);
      if (result && result.ok) {
        this.lastHash = pending.hash;
        this.lastSentAt = this.clock();
        if (this.pending === pending) this.pending = null;
        return true;
      }
      return false;
    } finally {
      this.inFlight = false;
    }
  }
}

async function processAlive(pid) {
  if (!boundedInteger(pid, 1, 2 ** 31 - 1)) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (_error) {
    return false;
  }
}

function processStartIdentity(pid, options = {}) {
  if (!boundedInteger(pid, 1, 2 ** 31 - 1)) return '';
  const runner = options.spawnSync || spawnSync;
  const ps = options.psPath || '/bin/ps';
  try {
    const result = runner(
      ps,
      ['-p', String(pid), '-o', 'lstart='],
      {
        encoding: 'utf8',
        maxBuffer: 64 * 1024,
        timeout: 2000
      }
    );
    if (result.error || result.status !== 0) return '';
    return String(result.stdout || '')
      .trim()
      .replace(/\s+/g, ' ')
      .slice(0, 80);
  } catch (_error) {
    return '';
  }
}

function validLockOwner(value) {
  return Boolean(
    exactKeys(value, [
      'created_at', 'generation', 'instance', 'parent_pid',
      'parent_start_identity', 'pid', 'process_start_identity',
      'schema_version', 'token'
    ]) &&
    value.schema_version === STRING_VERSION &&
    IDENTIFIER.test(value.generation || '') &&
    /^[A-Za-z0-9_-]{16,64}$/.test(value.instance || '') &&
    boundedInteger(value.pid, 1, 2 ** 31 - 1) &&
    boundedInteger(value.parent_pid, 1, 2 ** 31 - 1) &&
    OWNER_TOKEN.test(value.token || '') &&
    typeof value.process_start_identity === 'string' &&
    value.process_start_identity.length <= 80 &&
    typeof value.parent_start_identity === 'string' &&
    value.parent_start_identity.length <= 80
  );
}

async function lockOwnerIsLive(owner, options = {}) {
  if (!validLockOwner(owner)) return false;
  const identity = options.processIdentity || processStartIdentity;
  const alive = options.processAlive || processAlive;
  if (!await alive(owner.pid) || !await alive(owner.parent_pid)) {
    return false;
  }
  const processIdentity = await identity(owner.pid, options);
  const parentIdentity = await identity(owner.parent_pid, options);
  return Boolean(
    owner.process_start_identity &&
    owner.parent_start_identity &&
    processIdentity === owner.process_start_identity &&
    parentIdentity === owner.parent_start_identity
  );
}

async function acquireOwnership(
  runtimeDir,
  generation,
  options = {}
) {
  const lock = path.join(runtimeDir, LOCK_DIRECTORY);
  const instance = options.instance || `instance-${'0'.repeat(16)}`;
  const parentPid = options.parentPid || process.ppid;
  const identity = options.processIdentity || processStartIdentity;
  const processIdentity = await identity(process.pid, options);
  const parentIdentity = await identity(parentPid, options);
  if (!processIdentity || !parentIdentity) {
    throw new Error('process start identity is unavailable');
  }
  const token = (options.randomBytes || crypto.randomBytes)(24).toString('hex');
  const owner = {
    schema_version: STRING_VERSION,
    token,
    generation,
    instance,
    pid: process.pid,
    process_start_identity: processIdentity,
    parent_pid: parentPid,
    parent_start_identity: parentIdentity,
    created_at: new Date().toISOString()
  };
  for (let attempt = 0; attempt < 8; attempt += 1) {
    try {
      await fsp.mkdir(lock, {mode: 0o700});
      try {
        await atomicWriteJson(path.join(lock, 'owner.json'), owner);
      } catch (error) {
        const failed = `${lock}.failed-${token}`;
        try {
          await fsp.rename(lock, failed);
          await fsp.rm(failed, {recursive: true, force: true});
        } catch (_cleanupError) {}
        throw error;
      }
      const release = async () => {
        try {
          const current = await readJson(path.join(lock, 'owner.json'), 4096);
          if (
            !validLockOwner(current) ||
            current.token !== token ||
            current.pid !== process.pid ||
            current.process_start_identity !== processIdentity ||
            current.generation !== generation ||
            current.instance !== instance
          ) return false;
          const released = `${lock}.released-${token}`;
          await fsp.rename(lock, released);
          await fsp.rm(released, {recursive: true, force: true});
          return true;
        } catch (_error) {
          return false;
        }
      };
      release.token = token;
      release.owner = owner;
      return release;
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      let current = {};
      try {
        current = await readJson(path.join(lock, 'owner.json'), 4096);
      } catch (_readError) {
        let age = 0;
        try {
          age = Date.now() - (await fsp.lstat(lock)).mtimeMs;
        } catch (_metadataError) {}
        if (age >= 0 && age < 250) {
          await sleep(50, options.signal);
          continue;
        }
      }
      if (await lockOwnerIsLive(current, options)) {
        throw new Error('another CDP string owns this runtime');
      }
      const stale = `${lock}.stale-${token}-${attempt}`;
      try {
        await fsp.rename(lock, stale);
      } catch (renameError) {
        if (['ENOENT', 'EEXIST'].includes(renameError.code)) continue;
        throw renameError;
      }
      await fsp.rm(stale, {recursive: true, force: true});
    }
  }
  throw new Error('could not acquire CDP string ownership');
}

function processTable(options = {}) {
  if (typeof options.processTable === 'function') {
    return options.processTable();
  }
  const runner = options.spawnSync || spawnSync;
  try {
    const result = runner(
      options.psPath || '/bin/ps',
      ['-axo', 'pid=,pgid=,lstart=,command='],
      {
        encoding: 'utf8',
        maxBuffer: 4 * 1024 * 1024,
        timeout: 3000
      }
    );
    if (result.error || result.status !== 0) return [];
    const rows = [];
    for (const line of String(result.stdout || '').split(/\r?\n/)) {
      const match = line.match(
        /^\s*(\d+)\s+(\d+)\s+(\S+\s+\S+\s+\d+\s+\d+:\d+:\d+\s+\d+)\s+(.*)$/
      );
      if (!match) continue;
      rows.push({
        pid: Number(match[1]),
        pgid: Number(match[2]),
        start_identity: match[3].replace(/\s+/g, ' '),
        command: match[4]
      });
    }
    return rows;
  } catch (_error) {
    return [];
  }
}

function validBrowserIdentity(record) {
  return Boolean(
    record &&
    record.schema_version === STRING_VERSION &&
    IDENTIFIER.test(record.generation || '') &&
    /^[A-Za-z0-9_-]{16,64}$/.test(record.instance || '') &&
    OWNER_TOKEN.test(record.token || '') &&
    boundedInteger(record.pid, 2, 2 ** 31 - 1) &&
    boundedInteger(record.pgid, 2, 2 ** 31 - 1) &&
    record.pid === record.pgid &&
    typeof record.profile === 'string' &&
    path.isAbsolute(record.profile) &&
    typeof record.start_identity === 'string' &&
    record.start_identity.length <= 80
  );
}

async function recordBrowserIdentity(
  runtimeDir,
  child,
  config,
  profile,
  token,
  options = {}
) {
  if (!boundedInteger(child && child.pid, 2, 2 ** 31 - 1)) {
    throw new Error('dedicated browser did not publish a PID');
  }
  const identity = options.processIdentity || processStartIdentity;
  const record = {
    schema_version: STRING_VERSION,
    generation: config.generation,
    instance: config.instance,
    token,
    pid: child.pid,
    pgid: child.pid,
    start_identity: await identity(child.pid, options),
    profile,
    created_at: new Date().toISOString()
  };
  if (!validBrowserIdentity(record)) {
    throw new Error('dedicated browser identity is invalid');
  }
  await atomicWriteJson(path.join(runtimeDir, BROWSER_OWNER_FILE), record);
  return record;
}

function ownedBrowserGroup(record, options = {}) {
  if (!validBrowserIdentity(record)) return [];
  const profileArgument = `--user-data-dir=${record.profile}`;
  const tokenArgument = `--rpp-kite-owner-token=${record.token}`;
  const members = processTable(options).filter(row => row.pgid === record.pgid);
  const leader = members.find(row => row.pid === record.pid);
  if (
    leader &&
    record.start_identity &&
    leader.start_identity !== record.start_identity
  ) return [];
  return members.some(row =>
    row.command.includes(profileArgument) &&
    row.command.includes(tokenArgument)
  ) ? members : [];
}

async function terminateDedicatedBrowser(
  browser,
  timeoutMs = 5000,
  options = {}
) {
  if (!browser) return;
  const child = browser.child || browser;
  const record = browser.record || null;
  if (!record) {
    if (child.exitCode === null) {
      try { child.kill('SIGTERM'); } catch (_error) {}
    }
    return;
  }
  const signalGroup = signal => {
    const members = ownedBrowserGroup(record, options);
    if (!members.length) return false;
    try {
      (options.kill || process.kill)(-record.pgid, signal);
      return true;
    } catch (_error) {
      return false;
    }
  };
  signalGroup('SIGTERM');
  const deadline = Date.now() + timeoutMs;
  while (
    ownedBrowserGroup(record, options).length &&
    Date.now() < deadline
  ) await sleep(50);
  if (ownedBrowserGroup(record, options).length) {
    signalGroup('SIGKILL');
    const killDeadline = Date.now() + 3000;
    while (
      ownedBrowserGroup(record, options).length &&
      Date.now() < killDeadline
    ) await sleep(50);
  }
}

async function removeOwnedBrowserRecord(runtimeDir, token) {
  const ownerPath = path.join(runtimeDir, BROWSER_OWNER_FILE);
  try {
    const current = await readJson(ownerPath, 4096);
    if (current.token !== token) return false;
    await fsp.unlink(ownerPath);
    return true;
  } catch (_error) {
    return false;
  }
}

async function reclaimRecordedBrowser(runtimeDir, options = {}) {
  const ownerPath = path.join(runtimeDir, BROWSER_OWNER_FILE);
  let record;
  try {
    record = await readJson(ownerPath, 4096);
  } catch (error) {
    if (error.code === 'ENOENT') return false;
    throw new Error('recorded browser identity is unreadable');
  }
  if (!validBrowserIdentity(record)) {
    throw new Error('recorded browser identity is invalid');
  }
  const expectedProfile = path.join(
    runtimeDir,
    `kite-profile-${record.generation}`
  );
  if (record.profile !== expectedProfile) {
    throw new Error('recorded browser profile is outside managed storage');
  }
  const groupRows = () => processTable(options).filter(
    row => row.pgid === record.pgid
  );
  const members = groupRows();
  if (members.length) {
    let marker;
    try {
      marker = await readJson(
        path.join(record.profile, PROFILE_MARKER_FILE),
        4096
      );
    } catch (_error) {
      throw new Error('recorded browser profile ownership is unavailable');
    }
    if (
      !validProfileMarker(marker, path.basename(record.profile)) ||
      marker.token !== record.token ||
      marker.instance !== record.instance
    ) {
      throw new Error('recorded browser profile ownership is invalid');
    }
    if (!ownedBrowserGroup(record, options).length) {
      throw new Error('recorded browser process group ownership changed');
    }
    await terminateDedicatedBrowser(
      {child: null, record},
      1000,
      options
    );
    if (groupRows().length) {
      throw new Error('recorded browser process group did not exit');
    }
  }
  if (!await removeOwnedBrowserRecord(runtimeDir, record.token)) {
    throw new Error('recorded browser identity changed during cleanup');
  }
  return true;
}

function validProfileMarker(value, profileName) {
  return Boolean(
    exactKeys(value, [
      'created_at', 'generation', 'instance', 'schema_version', 'token'
    ]) &&
    value.schema_version === STRING_VERSION &&
    IDENTIFIER.test(value.generation || '') &&
    profileName === `kite-profile-${value.generation}` &&
    /^[A-Za-z0-9_-]{16,64}$/.test(value.instance || '') &&
    OWNER_TOKEN.test(value.token || '')
  );
}

async function garbageCollectProfiles(
  runtimeDir,
  currentGeneration,
  options = {}
) {
  const entries = await fsp.readdir(runtimeDir, {withFileTypes: true});
  for (const entry of entries) {
    if (
      !entry.isDirectory() ||
      entry.isSymbolicLink() ||
      !/^kite-profile-[A-Za-z0-9_-]{16,128}$/.test(entry.name) ||
      entry.name === `kite-profile-${currentGeneration}`
    ) continue;
    const candidate = path.join(runtimeDir, entry.name);
    let metadata;
    let marker;
    try {
      metadata = await fsp.lstat(candidate);
      marker = await readJson(path.join(candidate, PROFILE_MARKER_FILE), 4096);
    } catch (_error) {
      continue;
    }
    if (
      !metadata.isDirectory() ||
      metadata.isSymbolicLink() ||
      !validProfileMarker(marker, entry.name)
    ) continue;
    const profileArgument = `--user-data-dir=${candidate}`;
    if (processTable(options).some(row =>
      row.command.includes(profileArgument)
    )) continue;
    await fsp.rm(candidate, {recursive: true, force: true});
  }
}

async function prepareManagedProfile(
  runtimeDir,
  config,
  token,
  options = {}
) {
  const profile = path.join(
    runtimeDir,
    `kite-profile-${config.generation}`
  );
  try {
    const metadata = await fsp.lstat(profile);
    const marker = await readJson(
      path.join(profile, PROFILE_MARKER_FILE),
      4096
    );
    if (
      !metadata.isDirectory() ||
      metadata.isSymbolicLink() ||
      !validProfileMarker(marker, path.basename(profile))
    ) {
      throw new Error('refusing to replace an unowned browser profile');
    }
    const profileArgument = `--user-data-dir=${profile}`;
    if (processTable(options).some(row =>
      row.command.includes(profileArgument)
    )) {
      throw new Error('managed browser profile is still active');
    }
    await fsp.rm(profile, {recursive: true, force: true});
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  await fsp.mkdir(profile, {mode: 0o700});
  await fsp.chmod(profile, 0o700);
  await atomicWriteJson(path.join(profile, PROFILE_MARKER_FILE), {
    schema_version: STRING_VERSION,
    generation: config.generation,
    instance: config.instance,
    token,
    created_at: new Date().toISOString()
  });
  return profile;
}

function validBroadcastState(value, config) {
  return Boolean(
    exactKeys(value, [
      'desired', 'generation', 'instance', 'schema_version',
      'sequence', 'updated_at'
    ]) &&
    value.schema_version === STRING_VERSION &&
    value.generation === config.generation &&
    value.instance === config.instance &&
    typeof value.desired === 'boolean' &&
    boundedInteger(value.sequence, 0, Number.MAX_SAFE_INTEGER)
  );
}

async function readBroadcastState(runtimeDir, config) {
  const statePath = path.join(runtimeDir, BROADCAST_STATE_FILE);
  let desired = true;
  try {
    const value = await readJson(statePath, 4096);
    if (validBroadcastState(value, config)) return value;
    desired = false;
  } catch (_error) {
    try {
      await fsp.lstat(statePath);
      desired = false;
    } catch (metadataError) {
      if (metadataError.code !== 'ENOENT') throw metadataError;
    }
  }
  const initial = {
    schema_version: STRING_VERSION,
    generation: config.generation,
    instance: config.instance,
    sequence: 0,
    desired,
    updated_at: new Date().toISOString()
  };
  await atomicWriteJson(statePath, initial);
  return initial;
}

async function writeBroadcastState(runtimeDir, config, sequence, desired) {
  const value = {
    schema_version: STRING_VERSION,
    generation: config.generation,
    instance: config.instance,
    sequence,
    desired,
    updated_at: new Date().toISOString()
  };
  await atomicWriteJson(path.join(runtimeDir, BROADCAST_STATE_FILE), value);
  return value;
}

function pageBootstrap(config, broadcastState = {
  sequence: 0,
  desired: true
}, identity = null) {
  const shared = {
    build: HOST_BUILD,
    broadcast_desired: broadcastState.desired,
    broadcast_sequence: broadcastState.sequence,
    frame_rate: 10,
    generation: config.generation,
    instance: config.instance,
    join_url: config.join_url,
    max_hello_bytes: 512,
    max_negotiating: Math.min(16, Math.max(2, config.max_viewers * 2)),
    max_telemetry_bytes: 4096,
    max_viewers: config.max_viewers,
    telemetry_version: 1
  };
  if (config.signaling === 'nostr') {
    if (
      !validHostIdentity(identity, config.generation) ||
      identity.host_public_key !== config.host_public_key ||
      identity.fingerprint !== config.host_fingerprint
    ) throw new Error('generation host identity does not match bootstrap');
    return {
      ...shared,
      signaling: 'nostr',
      room_id: config.room_id,
      room_key: config.room_key,
      host_fingerprint: config.host_fingerprint,
      host_public_key: config.host_public_key,
      host_private_jwk: identity.host_private_jwk,
      manual_callback: {...config.manual_callback},
      manual_return_token: config.manual_return_token,
      manual_return_page: config.manual_return_page,
      relay_urls: [...config.relay_urls],
      rtc_config: {
        iceServers: [{urls: 'stun:stun.l.google.com:19302'}]
      },
      max_hello_bytes: 2048,
      protocol_version: 2
    };
  }
  return {
    ...shared,
    max_hello_bytes: 512,
    peer_id: config.peer_id,
    peer_options: {
      host: '0.peerjs.com',
      port: 443,
      path: '/',
      secure: true,
      debug: 0,
      config: {
        iceServers: [{urls: 'stun:stun.l.google.com:19302'}]
      }
    },
    protocol_version: 1,
    watch_capability: config.watch_capability
  };
}

function livestreamStatusFromPage(config, status) {
  const allowed = new Set([
    'offline', 'connecting', 'live', 'reconnecting', 'error'
  ]);
  let streamState = allowed.has(status.state) ? status.state : 'offline';
  if (!status.share_ready && streamState === 'live') streamState = 'connecting';
  return {
    state: streamState,
    viewer_count: boundedInteger(status.viewer_count, 0, 8)
      ? status.viewer_count
      : 0,
    generation: config.generation,
    owner: 'kite',
    updated_at: new Date().toISOString()
  };
}

async function writeHostStatus(runtimeDir, config, browserPid, status, bridgeState) {
  const safe = {
    schema_version: STRING_VERSION,
    generation: config.generation,
    instance: config.instance,
    bridge_state: bridgeState,
    bridge_pid: process.pid,
    browser_pid: browserPid || null,
    state: typeof status.state === 'string'
      ? status.state.slice(0, 24)
      : 'offline',
    viewer_count: boundedInteger(status.viewer_count, 0, 8)
      ? status.viewer_count
      : 0,
    max_viewers: config.max_viewers,
    peer_open: status.peer_open === true,
    first_frame: status.first_frame === true,
    share_ready: status.share_ready === true,
    automatic_share_ready: status.automatic_share_ready === true,
    manual_share_ready: status.manual_share_ready === true,
    source_health: status.source_health === 'ok' ? 'ok' : 'lost',
    string_health: status.string_health === 'ok' ? 'ok' : 'lost',
    runtime_health: ['starting', 'ready', 'degraded', 'stopping'].includes(
      status.runtime_health
    ) ? status.runtime_health : 'degraded',
    peer_health: status.peer_health === 'open' ? 'open' : 'offline',
    signaling: status.signaling === 'nostr' ? 'nostr' : 'peerjs',
    relay_health: [
      'qualified', 'unqualified', 'open', 'blocked', 'offline'
    ].includes(status.relay_health)
      ? status.relay_health
      : 'offline',
    relay_open_count: boundedInteger(status.relay_open_count, 0, 5)
      ? status.relay_open_count
      : 0,
    relay_qualified_count: boundedInteger(
      status.relay_qualified_count, 0, 5
    ) ? status.relay_qualified_count : 0,
    relay_total: boundedInteger(status.relay_total, 0, 5)
      ? status.relay_total
      : 0,
    direct_health: ['idle', 'connecting', 'connected'].includes(
      status.direct_health
    ) ? status.direct_health : 'idle',
    direct_peer_count: boundedInteger(status.direct_peer_count, 0, 8)
      ? status.direct_peer_count
      : 0,
    media_ready_count: boundedInteger(status.media_ready_count, 0, 8)
      ? status.media_ready_count
      : 0,
    candidate_types: (
      Array.isArray(status.candidate_types)
        ? [...new Set(status.candidate_types)].filter(
          value => ['host', 'srflx', 'prflx'].includes(value)
        ).sort()
        : []
    ),
    frame_sequence: boundedInteger(
      status.frame_sequence, 0, Number.MAX_SAFE_INTEGER
    ) ? status.frame_sequence : 0,
    telemetry_sequence: boundedInteger(
      status.telemetry_sequence, 0, Number.MAX_SAFE_INTEGER
    ) ? status.telemetry_sequence : 0,
    heartbeat_sequence: boundedInteger(
      status.heartbeat_sequence, 0, Number.MAX_SAFE_INTEGER
    ) ? status.heartbeat_sequence : 0,
    frame_attempted_sequence: boundedInteger(
      status.frame_attempted_sequence, 0, Number.MAX_SAFE_INTEGER
    ) ? status.frame_attempted_sequence : 0,
    frame_attempted_hash: /^[a-f0-9]{64}$/.test(
      status.frame_attempted_hash || ''
    ) ? status.frame_attempted_hash : '',
    frame_hash: /^[a-f0-9]{64}$/.test(status.frame_hash || '')
      ? status.frame_hash
      : '',
    source_sequence: boundedInteger(
      status.source_sequence, 0, Number.MAX_SAFE_INTEGER
    ) ? status.source_sequence : 0,
    source_hash: /^[a-f0-9]{64}$/.test(status.source_hash || '')
      ? status.source_hash
      : '',
    broadcast_desired: status.broadcast_desired !== false,
    broadcast_sequence: boundedInteger(
      status.broadcast_sequence, 0, Number.MAX_SAFE_INTEGER
    ) ? status.broadcast_sequence : 0,
    error: typeof status.error === 'string' ? status.error.slice(0, 80) : '',
    updated_at: new Date().toISOString()
  };
  await atomicWriteJson(path.join(runtimeDir, HOST_STATUS_FILE), safe);
  await atomicWriteJson(
    path.join(runtimeDir, LIVESTREAM_STATUS_FILE),
    livestreamStatusFromPage(config, safe)
  );
}

async function runtimeState(runtimeDir) {
  try {
    const status = await readJson(path.join(runtimeDir, 'status.json'), 512 * 1024);
    if (status.lifecycle === 'ready' && status.running !== false) return 'ready';
    if (status.lifecycle === 'initializing') return 'starting';
    if (['stopped', 'failed'].includes(status.lifecycle)) return 'stopping';
  } catch (_error) {
    // A transient atomic replacement should degrade only this heartbeat.
  }
  return 'degraded';
}

function validManualAnswerQueueItem(value, config, sequence) {
  return Boolean(
    exactKeys(value, [
      'answer', 'generation', 'received_at', 'schema_version', 'sequence'
    ]) &&
    value.schema_version === STRING_VERSION &&
    value.generation === config.generation &&
    value.sequence === sequence &&
    typeof value.answer === 'string' &&
    value.answer.startsWith('rpp-answer-v2.') &&
    Buffer.byteLength(value.answer) <= MAX_MANUAL_ANSWER_BYTES &&
    typeof value.received_at === 'string' &&
    value.received_at.length <= 48 &&
    Number.isFinite(Date.parse(value.received_at))
  );
}

function validManualAnswerStatus(value, config, sequence) {
  return Boolean(
    exactKeys(value, [
      'generation', 'reason', 'schema_version', 'sequence',
      'status', 'updated_at'
    ]) &&
    value.schema_version === STRING_VERSION &&
    value.generation === config.generation &&
    value.sequence === sequence &&
    ['delivered', 'rejected'].includes(value.status)
  );
}

async function consumeManualAnswers(
  runtimeDir,
  config,
  ingress,
  lastSequence = 0
) {
  const directory = path.join(runtimeDir, MANUAL_RETURN_DIRECTORY);
  let names;
  try {
    names = await fsp.readdir(directory);
  } catch (error) {
    if (error.code === 'ENOENT') return lastSequence;
    throw error;
  }
  const queued = names.flatMap(name => {
    const match = name.match(/^answer-(\d{12})\.json$/);
    return match ? [{name, sequence: Number(match[1])}] : [];
  }).filter(item =>
    boundedInteger(item.sequence, 1, Number.MAX_SAFE_INTEGER) &&
    item.sequence > lastSequence
  ).sort((left, right) => left.sequence - right.sequence).slice(0, 32);
  for (const item of queued) {
    const statusPath = path.join(
      directory,
      `status-${String(item.sequence).padStart(12, '0')}.json`
    );
    try {
      const existing = await readJson(statusPath, 4096);
      if (validManualAnswerStatus(existing, config, item.sequence)) {
        await fsp.unlink(path.join(directory, item.name)).catch(() => {});
        lastSequence = item.sequence;
        continue;
      }
    } catch (_error) {
      // A missing status means this monotonic queue item is pending.
    }
    let result = {ok: false, reason: 'queue'};
    let queuedAnswer = null;
    try {
      queuedAnswer = await readJson(
        path.join(directory, item.name),
        MAX_MANUAL_ANSWER_BYTES + 4096
      );
    } catch (_error) {
      result = {ok: false, reason: 'queue'};
    }
    if (
      queuedAnswer &&
      validManualAnswerQueueItem(
        queuedAnswer,
        config,
        item.sequence
      )
    ) {
      try {
        result = await ingress.call('manualAnswer', {
          generation: config.generation,
          answer: queuedAnswer.answer
        });
      } catch (_error) {
        // Preserve the atomic queue item across CDP/context recovery.
        break;
      }
    }
    await atomicWriteJson(statusPath, {
      schema_version: STRING_VERSION,
      generation: config.generation,
      sequence: item.sequence,
      status: result && result.ok ? 'delivered' : 'rejected',
      reason: result && result.ok
        ? 'accepted'
        : String(result && result.reason || 'rejected')
          .replace(/[^a-z-]/gi, '')
          .slice(0, 32),
      updated_at: new Date().toISOString()
    });
    await fsp.unlink(path.join(directory, item.name)).catch(() => {});
    const statuses = (await fsp.readdir(directory)).filter(
      name => /^status-\d{12}\.json$/.test(name)
    ).sort();
    for (const stale of statuses.slice(0, -64)) {
      await fsp.unlink(path.join(directory, stale)).catch(() => {});
    }
    lastSequence = item.sequence;
  }
  return lastSequence;
}

async function runString(runtimeDir, dependencies = {}) {
  await assertPrivateDirectory(runtimeDir);
  const config = validateBootstrap(
    await readJson(path.join(runtimeDir, BOOTSTRAP_FILE), 16 * 1024)
  );
  const hostIdentity = config.signaling === 'nostr'
    ? await ensureHostIdentity(runtimeDir, config.generation)
    : null;
  if (
    hostIdentity &&
    (
      hostIdentity.host_public_key !== config.host_public_key ||
      hostIdentity.fingerprint !== config.host_fingerprint
    )
  ) throw new Error('bootstrap host identity changed');
  if (!await processAlive(config.parent_pid)) {
    throw new Error('owning runtime process is not alive');
  }
  const controller = new AbortController();
  const {signal} = controller;
  const identity = dependencies.processIdentity || processStartIdentity;
  const parentStartIdentity = identity(config.parent_pid, dependencies);
  if (!parentStartIdentity) {
    throw new Error('owning runtime process identity is unavailable');
  }
  const launch = dependencies.spawn || spawn;
  let releaseOwnership = null;
  let profile = '';
  let expectedUrl = '';
  let browserProcess = null;
  let browserMonitor = null;
  let browserRecord = null;
  let cdp = null;
  let ingress = null;
  let ingressSessionId = '';
  let target = null;
  let framePump = null;
  let telemetry = null;
  let stopped = false;
  let fatalError = null;
  let heartbeatSequence = 0;
  let shutdownSequence = 0;
  let lastFrameObservedSequence = 0;
  let lastFrameObservedHash = '';
  let lastFrameAcknowledgedSequence = 0;
  let lastFrameAcknowledgedHash = '';
  let consecutiveFrameFailures = 0;
  let lastTelemetryFileSequence = 0;
  let lastCommandSequence = 0;
  let lastHeartbeatAt = 0;
  let lastStatusAt = 0;
  let lastTelemetryReadAt = 0;
  let lastManualAnswerReadAt = 0;
  let lastManualAnswerSequence = 0;
  let lastTargetValidationAt = 0;
  let targetInvalid = false;
  let contextInvalid = false;
  let broadcastState = null;

  const stop = reason => {
    if (stopped) return;
    stopped = true;
    fatalError = reason || null;
    controller.abort(reason || abortError());
    cdp?.close();
  };
  const onStdinEnd = () => stop(null);
  const onSignal = () => stop(null);
  process.stdin.on('end', onStdinEnd);
  process.stdin.on('error', onStdinEnd);
  process.on('SIGTERM', onSignal);
  process.on('SIGINT', onSignal);
  process.stdin.resume();
  const parentTimer = setInterval(() => {
    const currentIdentity = identity(config.parent_pid, dependencies);
    if (currentIdentity !== parentStartIdentity) stop(null);
  }, 250);

  try {
    releaseOwnership = await acquireOwnership(
      runtimeDir,
      config.generation,
      {
        ...dependencies,
        instance: config.instance,
        parentPid: config.parent_pid,
        signal
      }
    );
    throwIfAborted(signal);
    await reclaimRecordedBrowser(runtimeDir, dependencies);
    throwIfAborted(signal);
    await garbageCollectProfiles(
      runtimeDir,
      config.generation,
      dependencies
    );
    throwIfAborted(signal);
    profile = await prepareManagedProfile(
      runtimeDir,
      config,
      releaseOwnership.token,
      dependencies
    );
    throwIfAborted(signal);
    broadcastState = await readBroadcastState(runtimeDir, config);
    throwIfAborted(signal);
    const hostBase = normalizeHttpsBase(config.host_base, 'host base');
    expectedUrl =
      `${hostBase}#v=2&instance=${encodeURIComponent(config.instance)}`;
    const browser = discoverBrowser(config.browser_path);
    browserProcess = launch(
      browser,
      chromeLaunchArguments(profile, expectedUrl, releaseOwnership.token),
      {
        stdio: ['ignore', 'ignore', 'pipe'],
        detached: process.platform !== 'win32',
        env: {...process.env}
      }
    );
    const browserStderr = captureBrowserStderr(browserProcess);
    browserMonitor = monitorBrowser(browserProcess, browserStderr);
    browserMonitor.failed.catch(error => stop(error));
    browserRecord = await raceBrowser(
      recordBrowserIdentity(
        runtimeDir,
        browserProcess,
        config,
        profile,
        releaseOwnership.token,
        dependencies
      ),
      {signal, monitor: browserMonitor}
    );
    throwIfAborted(signal);
    const initialStatus = {
      state: 'connecting',
      viewer_count: 0,
      peer_open: false,
      first_frame: false,
      share_ready: false,
      automatic_share_ready: false,
      manual_share_ready: false,
      source_health: 'lost',
      string_health: 'lost',
      runtime_health: 'starting',
      peer_health: 'offline',
      frame_sequence: 0,
      frame_attempted_sequence: 0,
      frame_attempted_hash: '',
      frame_hash: '',
      source_sequence: 0,
      source_hash: '',
      telemetry_sequence: 0,
      heartbeat_sequence: 0,
      broadcast_desired: broadcastState.desired,
      broadcast_sequence: broadcastState.sequence,
      error: ''
    };
    await writeHostStatus(
      runtimeDir,
      config,
      browserProcess.pid,
      initialStatus,
      'starting'
    );
    throwIfAborted(signal);
    const timeoutMs = Math.round(config.startup_timeout_seconds * 1000);
    const startupDeadline = Date.now() + timeoutMs;
    const startupOptions = {signal, monitor: browserMonitor};
    const endpoint = await waitForDevToolsActivePort(
      profile,
      remainingMilliseconds(startupDeadline),
      startupOptions
    );
    throwIfAborted(signal);
    cdp = new CdpConnection(
      `ws://127.0.0.1:${endpoint.port}${endpoint.socketPath}`,
      {
        ...(dependencies.cdpOptions || {}),
        signal,
        timeoutMs: Math.min(
          (dependencies.cdpOptions || {}).timeoutMs || RPC_TIMEOUT_MS,
          Math.max(1, remainingMilliseconds(startupDeadline))
        )
      }
    );
    await raceBrowser(cdp.open(signal), startupOptions);
    throwIfAborted(signal);
    cdp.on('close', () => {
      if (!stopped) stop(new Error('CDP connection closed'));
    });
    await raceBrowser(
      cdp.request('Target.setDiscoverTargets', {discover: true}),
      startupOptions
    );
    throwIfAborted(signal);
    const attached = await waitForVersionedIngress(
      cdp,
      expectedUrl,
      config.instance,
      remainingMilliseconds(startupDeadline),
      {
        ...startupOptions,
        generation: config.generation
      }
    );
    ingress = attached.ingress;
    ingressSessionId = attached.sessionId;
    target = attached.target;
    cdp.on('Target.targetInfoChanged', parameters => {
      if (
        parameters.targetInfo &&
        parameters.targetInfo.targetId === target.targetId &&
        parameters.targetInfo.url !== expectedUrl
      ) {
        targetInvalid = true;
        stop(new Error('managed Pages host navigated'));
      }
    });
    cdp.on('Target.targetDestroyed', parameters => {
      if (parameters.targetId === target.targetId) {
        stop(new Error('managed Pages host closed'));
      }
    });
    cdp.on('Runtime.executionContextsCleared', (_parameters, sessionId) => {
      if (sessionId === ingressSessionId) contextInvalid = true;
    });
    cdp.on('Runtime.executionContextDestroyed', (_parameters, sessionId) => {
      if (sessionId === ingressSessionId) contextInvalid = true;
    });
    const bootstrapped = await ingress.call(
      'bootstrap',
      pageBootstrap(config, broadcastState, hostIdentity)
    );
    throwIfAborted(signal);
    if (!bootstrapped.ok) throw new Error('Pages host rejected bootstrap');
    const callIngress = async (method, value = undefined) => {
      try {
        return await ingress.call(method, value);
      } catch (error) {
        if (
          error &&
          error.code === 'CDP_METHOD_FAILED' &&
          !targetInvalid
        ) {
          contextInvalid = true;
          return null;
        }
        throw error;
      }
    };

    framePump = new LatestFramePump(
      async frame => {
        return await callIngress('frame', frame);
      },
      {
        onResult(frame, result, error) {
          if (result && result.ok) {
            lastFrameAcknowledgedSequence = frame.sequence;
            lastFrameAcknowledgedHash = frame.sha256;
            consecutiveFrameFailures = 0;
            return;
          }
          if (result && result.reason === 'superseded') return;
          consecutiveFrameFailures += 1;
          if (
            consecutiveFrameFailures >= FRAME_FAILURE_LIMIT &&
            !contextInvalid
          ) {
            stop(new Error(
              error
                ? 'host frame ingress failed repeatedly'
                : 'host rejected frames repeatedly'
            ));
          }
        }
      }
    );
    telemetry = new TelemetryCadence(
      envelope => callIngress('telemetry', envelope)
    );
    await writeHostStatus(
      runtimeDir,
      config,
      browserProcess.pid,
      initialStatus,
      'ready'
    );
    throwIfAborted(signal);

    while (!stopped) {
      throwIfAborted(signal);
      browserMonitor.throwIfFailed();
      if (targetInvalid) throw new Error('managed target changed');
      const now = Date.now();

      if (contextInvalid) {
        const staleSessionId = ingressSessionId;
        ingressSessionId = '';
        await detachSession(cdp, staleSessionId, signal);
        throwIfAborted(signal);
        const recovered = await waitForVersionedIngress(
          cdp,
          expectedUrl,
          config.instance,
          Math.min(5000, timeoutMs),
          {
            signal,
            monitor: browserMonitor,
            generation: config.generation,
            targetId: target.targetId,
            allowBootstrapped: true
          }
        );
        throwIfAborted(signal);
        ingress = recovered.ingress;
        ingressSessionId = recovered.sessionId;
        target = recovered.target;
        if (!recovered.status.bootstrapped) {
          const rebound = await ingress.call(
            'bootstrap',
            pageBootstrap(config, broadcastState, hostIdentity)
          );
          throwIfAborted(signal);
          if (!rebound.ok) {
            throw new Error('Pages host rejected recovery bootstrap');
          }
        }
        contextInvalid = false;
        consecutiveFrameFailures = 0;
      }

      if (now - lastTargetValidationAt >= 250) {
        lastTargetValidationAt = now;
        const targets = await cdp.request('Target.getTargets');
        throwIfAborted(signal);
        const exact = selectExactTarget(
          targets.targetInfos || [],
          expectedUrl
        );
        if (!exact || exact.targetId !== target.targetId) {
          throw new Error('managed Pages host target changed');
        }
      }

      try {
        const frame = await readStableFrame(
          runtimeDir,
          config.generation,
          lastFrameObservedSequence
        );
        throwIfAborted(signal);
        if (frame && frame.sequence > lastFrameObservedSequence) {
          frame.instance = config.instance;
          lastFrameObservedSequence = frame.sequence;
          lastFrameObservedHash = frame.sha256;
          framePump.submit(frame);
        }
      } catch (error) {
        throwIfAborted(signal);
        if (error && error.code === 'ABORT_ERR') throw error;
        // Atomic frame publication can be between manifest generations.
      }

      if (now - lastTelemetryReadAt >= 250) {
        lastTelemetryReadAt = now;
        try {
          const value = await readJson(
            path.join(runtimeDir, TELEMETRY_FILE),
            8 * 1024
          );
          throwIfAborted(signal);
          if (
            validTelemetryFile(value, config.generation) &&
            value.sequence > lastTelemetryFileSequence
          ) {
            const envelope = {
              generation: config.generation,
              instance: config.instance,
              sequence: value.sequence,
              snapshot: value.snapshot
            };
            if (Buffer.byteLength(JSON.stringify(envelope)) <= 4096) {
              lastTelemetryFileSequence = value.sequence;
              telemetry.submit(envelope);
            }
          }
        } catch (error) {
          throwIfAborted(signal);
          if (error && error.code === 'ABORT_ERR') throw error;
          // Safe telemetry is optional; video continues.
        }
      }
      await telemetry.tick();
      throwIfAborted(signal);

      if (
        config.signaling === 'nostr' &&
        now - lastManualAnswerReadAt >= 100
      ) {
        lastManualAnswerReadAt = now;
        lastManualAnswerSequence = await consumeManualAnswers(
          runtimeDir,
          config,
          ingress,
          lastManualAnswerSequence
        );
        throwIfAborted(signal);
      }

      if (now - lastHeartbeatAt >= 1000) {
        lastHeartbeatAt = now;
        heartbeatSequence += 1;
        const runtime = await runtimeState(runtimeDir);
        throwIfAborted(signal);
        const heartbeat = await callIngress('heartbeat', {
          generation: config.generation,
          instance: config.instance,
          sequence: heartbeatSequence,
          source_sequence: lastFrameObservedSequence,
          source_hash: lastFrameObservedHash,
          runtime_state: runtime
        });
        throwIfAborted(signal);
        if (!heartbeat && contextInvalid) continue;
        if (!heartbeat.ok) throw new Error('Pages host rejected heartbeat');
        if (
          heartbeat.source_accepted === true &&
          heartbeat.source_sequence === lastFrameObservedSequence
        ) {
          lastFrameAcknowledgedSequence = lastFrameObservedSequence;
          lastFrameAcknowledgedHash = lastFrameObservedHash;
        }
      }

      if (now - lastStatusAt >= 250) {
        lastStatusAt = now;
        let pageStatus = await callIngress('status');
        throwIfAborted(signal);
        if (!pageStatus && contextInvalid) continue;
        let diskState = broadcastState;
        try {
          const candidate = await readJson(
            path.join(runtimeDir, BROADCAST_STATE_FILE),
            4096
          );
          throwIfAborted(signal);
          if (validBroadcastState(candidate, config)) diskState = candidate;
        } catch (error) {
          throwIfAborted(signal);
          if (error && error.code === 'ABORT_ERR') throw error;
        }
        if (
          diskState.sequence === pageStatus.broadcast_sequence &&
          diskState.desired !== pageStatus.broadcast_desired &&
          (
            diskState.sequence > broadcastState.sequence ||
            diskState.desired !== broadcastState.desired
          )
        ) {
          if (diskState.sequence >= Number.MAX_SAFE_INTEGER) {
            throw new Error('broadcast intent sequence exhausted');
          }
          diskState = await writeBroadcastState(
            runtimeDir,
            config,
            diskState.sequence + 1,
            diskState.desired
          );
          throwIfAborted(signal);
        }
        if (diskState.sequence > pageStatus.broadcast_sequence) {
          const applied = await callIngress('broadcast', {
            generation: config.generation,
            instance: config.instance,
            sequence: diskState.sequence,
            desired: diskState.desired
          });
          throwIfAborted(signal);
          if (!applied && contextInvalid) continue;
          if (!applied.ok) {
            throw new Error('Pages host rejected broadcast intent');
          }
          broadcastState = diskState;
          pageStatus = await callIngress('status');
          throwIfAborted(signal);
          if (!pageStatus && contextInvalid) continue;
        } else if (
          boundedInteger(
            pageStatus.broadcast_sequence,
            0,
            Number.MAX_SAFE_INTEGER
          ) &&
          typeof pageStatus.broadcast_desired === 'boolean' &&
          (
            pageStatus.broadcast_sequence > broadcastState.sequence ||
            (
              pageStatus.broadcast_sequence === broadcastState.sequence &&
              pageStatus.broadcast_desired !== broadcastState.desired
            )
          )
        ) {
          broadcastState = await writeBroadcastState(
            runtimeDir,
            config,
            pageStatus.broadcast_sequence,
            pageStatus.broadcast_desired
          );
          throwIfAborted(signal);
        }
        pageStatus.frame_attempted_sequence = lastFrameObservedSequence;
        pageStatus.frame_attempted_hash = lastFrameObservedHash;
        pageStatus.source_sequence = lastFrameAcknowledgedSequence;
        pageStatus.source_hash = lastFrameAcknowledgedHash;
        await writeHostStatus(
          runtimeDir,
          config,
          browserProcess.pid,
          pageStatus,
          'ready'
        );
        throwIfAborted(signal);
      }

      try {
        const command = await readJson(
          path.join(runtimeDir, COMMAND_FILE),
          4096
        );
        if (
          exactKeys(command, [
            'action', 'generation', 'instance', 'schema_version', 'sequence'
          ]) &&
          command.schema_version === STRING_VERSION &&
          command.generation === config.generation &&
          command.instance === config.instance &&
          command.action === 'focus' &&
          boundedInteger(command.sequence, 1, Number.MAX_SAFE_INTEGER) &&
          command.sequence > lastCommandSequence
        ) {
          await cdp.request('Target.activateTarget', {
            targetId: target.targetId
          });
          throwIfAborted(signal);
          lastCommandSequence = command.sequence;
        }
      } catch (error) {
        throwIfAborted(signal);
        if (error && error.code === 'ABORT_ERR') throw error;
        // No focus request is the steady state.
      }
      await sleep(25, signal);
    }
    if (fatalError) throw fatalError;
  } catch (error) {
    if (signal.aborted && !fatalError) return;
    throw fatalError || error;
  } finally {
    clearInterval(parentTimer);
    framePump?.close();
    if (ingress && !signal.aborted) {
      try {
        shutdownSequence += 1;
        await ingress.call('shutdown', {
          generation: config.generation,
          instance: config.instance,
          sequence: shutdownSequence
        }, 3000);
      } catch (_error) {
        // Browser teardown remains authoritative.
      }
    }
    cdp?.close();
    await terminateDedicatedBrowser(
      browserRecord
        ? {child: browserProcess, record: browserRecord}
        : browserProcess,
      1000,
      dependencies
    );
    if (browserRecord) {
      await removeOwnedBrowserRecord(runtimeDir, browserRecord.token);
    }
    if (profile) {
      try {
        const marker = await readJson(
          path.join(profile, PROFILE_MARKER_FILE),
          4096
        );
        if (
          marker.token === releaseOwnership?.token &&
          validProfileMarker(marker, path.basename(profile))
        ) {
          await fsp.rm(profile, {recursive: true, force: true});
        }
      } catch (_error) {}
    }
    if (releaseOwnership) await releaseOwnership();
    process.stdin.removeListener('end', onStdinEnd);
    process.stdin.removeListener('error', onStdinEnd);
    process.removeListener('SIGTERM', onSignal);
    process.removeListener('SIGINT', onSignal);
  }
}

async function main(argv = process.argv.slice(2)) {
  let runtimeDir = '';
  try {
    if (Number(process.versions.node.split('.')[0]) < 22) {
      throw new Error('Node.js 22 or newer is required');
    }
    const parsed = parseArguments(argv);
    ({runtimeDir} = parsed);
    if (parsed.mode === 'initialize-identity') {
      await assertPrivateDirectory(runtimeDir);
      await ensureHostIdentity(runtimeDir, parsed.generation);
      return 0;
    }
    await runString(runtimeDir);
    return 0;
  } catch (error) {
    if (runtimeDir) {
      try {
        const config = await readJson(
          path.join(runtimeDir, BOOTSTRAP_FILE),
          16 * 1024
        );
        if (
          IDENTIFIER.test(config.generation || '') &&
          /^[A-Za-z0-9_-]{16,64}$/.test(config.instance || '')
        ) {
          await atomicWriteJson(path.join(runtimeDir, HOST_STATUS_FILE), {
            schema_version: STRING_VERSION,
            generation: config.generation,
            instance: config.instance,
            bridge_state: 'degraded',
            bridge_pid: process.pid,
            browser_pid: null,
            state: 'error',
            viewer_count: 0,
            max_viewers: boundedInteger(config.max_viewers, 1, 8)
              ? config.max_viewers
              : 0,
            peer_open: false,
            first_frame: false,
            share_ready: false,
            automatic_share_ready: false,
            manual_share_ready: false,
            source_health: 'lost',
            string_health: 'lost',
            runtime_health: 'degraded',
            peer_health: 'offline',
            frame_sequence: 0,
            frame_attempted_sequence: 0,
            frame_attempted_hash: '',
            frame_hash: '',
            source_sequence: 0,
            source_hash: '',
            telemetry_sequence: 0,
            heartbeat_sequence: 0,
            broadcast_desired: false,
            broadcast_sequence: 0,
            error: sanitizedError(error),
            updated_at: new Date().toISOString()
          });
        }
      } catch (_statusError) {
        // Do not expose bootstrap details through stderr.
      }
    }
    process.stderr.write(`kited twin string unavailable: ${sanitizedError(error)}\n`);
    return 1;
  }
}

module.exports = {
  STRING_VERSION,
  HOST_BUILD,
  MAX_FRAME_BYTES,
  exactKeys,
  parseArguments,
  canonicalJson,
  validHostIdentity,
  ensureHostIdentity,
  hostFingerprint,
  hostPublicKeyToken,
  validateBootstrap,
  validateJoinUrl,
  normalizeHttpsBase,
  standardBrowserCandidates,
  discoverBrowser,
  chromeLaunchArguments,
  waitForDevToolsActivePort,
  selectExactTarget,
  CdpConnection,
  IngressClient,
  waitForExactTarget,
  waitForVersionedIngress,
  attachIngress,
  parsePng,
  readStableFrame,
  validTelemetryFile,
  LatestFramePump,
  TelemetryCadence,
  processStartIdentity,
  validLockOwner,
  lockOwnerIsLive,
  acquireOwnership,
  processTable,
  validBrowserIdentity,
  recordBrowserIdentity,
  ownedBrowserGroup,
  terminateDedicatedBrowser,
  reclaimRecordedBrowser,
  garbageCollectProfiles,
  prepareManagedProfile,
  validBroadcastState,
  readBroadcastState,
  writeBroadcastState,
  captureBrowserStderr,
  monitorBrowser,
  pageBootstrap,
  livestreamStatusFromPage,
  writeHostStatus,
  validManualAnswerQueueItem,
  validManualAnswerStatus,
  consumeManualAnswers,
  runString,
  sanitizedError,
  main
};

if (require.main === module) {
  main().then(code => {
    process.exitCode = code;
  });
}
