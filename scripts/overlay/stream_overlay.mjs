// Stream a composed 1280x720 overlay scene (game + live run telemetry) to an
// RTMP ingest (YouTube Live).
//
// Data flows straight from the agent runtime directory — latest.png (~10 fps)
// and kite-telemetry.json — through a private localhost server into
// overlay.html, rendered by headless Chromium, captured via CDP screencast,
// and piped into ffmpeg.
//
// Usage:
//   node scripts/overlay/stream_overlay.mjs --key-file ~/.openrappter/pokemon-red/rtmp-key.txt
//   node scripts/overlay/stream_overlay.mjs --test-output /tmp/overlay.flv --duration 15
//
// Requires: ffmpeg on PATH, and `playwright` resolvable from the working
// directory (npm install playwright).

import {createServer} from 'node:http';
import {readFile, readdir} from 'node:fs/promises';
import {readFileSync, existsSync, openSync, readSync, closeSync, constants as fsConstants} from 'node:fs';
import {spawn} from 'node:child_process';
import {homedir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';

let chromium;
try {
  ({chromium} = createRequire(import.meta.url)('playwright'));
} catch (_error) {
  ({chromium} = createRequire(path.join(process.cwd(), 'noop.js'))('playwright'));
}

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const FRAME_RATE = 10;
const STALL_EXIT_MS = 60000;

function parseArgs(argv) {
  const args = {
    runtimeDir: path.join(homedir(), '.openrappter', 'pokemon-red'),
    ingest: 'rtmp://a.rtmp.youtube.com/live2',
    rtmp: '',
    keyFile: '',
    testOutput: '',
    duration: 0,
    scale: 1.5
  };
  for (let index = 2; index < argv.length; index += 1) {
    const value = () => argv[++index];
    switch (argv[index]) {
      case '--runtime-dir': args.runtimeDir = value(); break;
      case '--ingest': args.ingest = value(); break;
      case '--rtmp': args.rtmp = value(); break;
      case '--key-file': args.keyFile = value(); break;
      case '--test-output': args.testOutput = value(); break;
      case '--duration': args.duration = Number(value()); break;
      case '--scale': args.scale = Number(value()); break;
      default:
        console.error(`unknown argument: ${argv[index]}`);
        process.exit(2);
    }
  }
  return args;
}

function resolveTarget(args) {
  if (args.testOutput) return args.testOutput;
  if (args.rtmp) return args.rtmp;
  let key = process.env.RPP_RTMP_KEY || '';
  if (args.keyFile) {
    key = readFileSync(
      args.keyFile.replace(/^~/, homedir()),
      'utf-8'
    ).trim();
  }
  if (!key) {
    console.error('error: provide --rtmp, --key-file, or RPP_RTMP_KEY');
    process.exit(2);
  }
  return `${args.ingest.replace(/\/+$/, '')}/${key}`;
}

const args = parseArgs(process.argv);
const runtimeDir = args.runtimeDir.replace(/^~/, homedir());
if (!existsSync(path.join(runtimeDir, 'latest.png'))) {
  console.error(`error: no latest.png in ${runtimeDir} — is the agent running?`);
  process.exit(1);
}
const target = resolveTarget(args);
const overlayHtml = await readFile(path.join(SCRIPT_DIR, 'overlay.html'));

const server = createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
  try {
    if (url.pathname === '/') {
      response.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
      response.end(overlayHtml);
    } else if (url.pathname === '/frame.png') {
      const png = await readFile(path.join(runtimeDir, 'latest.png'));
      response.writeHead(200, {
        'Content-Type': 'image/png',
        'Cache-Control': 'no-store'
      });
      response.end(png);
    } else if (url.pathname === '/api/overlay') {
      const telemetry = JSON.parse(
        await readFile(path.join(runtimeDir, 'kite-telemetry.json'), 'utf-8')
      );
      try {
        const brain = JSON.parse(
          await readFile(path.join(runtimeDir, 'brain.json'), 'utf-8')
        );
        const metas = (await readdir(path.join(runtimeDir, 'clips')))
          .filter(name => name.endsWith('.json')).sort();
        const newest = metas[metas.length - 1];
        const latest = newest
          ? JSON.parse(
              await readFile(path.join(runtimeDir, 'clips', newest), 'utf-8')
            )
          : null;
        telemetry.host = {
          brain_status:
            brain.updated_at &&
            Date.now() - Date.parse(brain.updated_at) < 120000
              ? 'active' : 'idle',
          actions_taken: brain.total_decisions ?? null,
          clips_count: newest
            ? Number((newest.match(/^clip-0*(\d+)/) || [])[1]) || metas.length
            : null,
          latest_clip_location:
            latest && latest.game_state ? latest.game_state.location ?? null : null,
          brain_recent: Array.isArray(brain.history)
            ? brain.history.slice(-3).reverse().map(entry => ({
                reason: entry.reason || '',
                at: entry.timestamp || null
              }))
            : []
        };
      } catch (_error) {}
      response.writeHead(200, {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store'
      });
      response.end(JSON.stringify(telemetry));
    } else {
      response.writeHead(404);
      response.end();
    }
  } catch (_error) {
    response.writeHead(503);
    response.end();
  }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;

const width = Math.round(1280 * args.scale);
const height = Math.round(720 * args.scale);
const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: {width, height},
  deviceScaleFactor: 1
});
await page.goto(
  `http://127.0.0.1:${port}/?scale=${args.scale}`,
  {waitUntil: 'load'}
);
await page.waitForTimeout(1500);

const ffmpeg = spawn('ffmpeg', [
  '-hide_banner',
  '-loglevel', 'warning',
  '-stats',
  ...(args.testOutput ? ['-y'] : []),
  '-f', 'image2pipe',
  '-framerate', String(FRAME_RATE),
  '-i', '-',
  '-f', 's16le',
  '-ar', '48000',
  '-ac', '2',
  '-i', 'pipe:3',
  '-vf', 'format=yuv420p',
  '-af', 'highpass=f=10,aresample=async=1:first_pts=0,adelay=200|200',
  '-r', '30',
  '-c:v', 'libx264',
  '-preset', 'veryfast',
  '-tune', 'zerolatency',
  '-b:v', height > 720 ? '4500k' : '2500k',
  '-maxrate', height > 720 ? '4500k' : '2500k',
  '-bufsize', height > 720 ? '9000k' : '5000k',
  '-g', '60',
  '-c:a', 'aac',
  '-b:a', '128k',
  '-shortest',
  '-f', 'flv',
  target
], {stdio: ['pipe', 'inherit', 'inherit', 'pipe']});

// Audio pacer: the encoder is the audio clock master. Wall-clock time decides
// exactly how many PCM bytes ffmpeg gets; whatever the agent's FIFO can't
// supply is padded with silence, so agent stalls and restarts never stall the
// mux — the stream just goes quiet, like the anullsrc it replaced.
const AUDIO_BYTES_PER_SECOND = 48000 * 2 * 2;
const audioFifoPath = path.join(runtimeDir, 'audio.fifo');
let audioFifoFd = null;
let audioFifoRetryAt = 0;
let audioSent = 0;
const audioStartedAt = Date.now();
const audioChunk = Buffer.alloc(AUDIO_BYTES_PER_SECOND / 10);
const audioTimer = setInterval(() => {
  const due = Math.floor((Date.now() - audioStartedAt) / 1000 * AUDIO_BYTES_PER_SECOND) & ~3;
  let deficit = due - audioSent;
  if (deficit <= 0 || !ffmpeg.stdio[3] || ffmpeg.exitCode !== null) return;
  while (deficit > 0) {
    const want = Math.min(deficit, audioChunk.length);
    let got = 0;
    if (audioFifoFd === null && Date.now() >= audioFifoRetryAt) {
      try {
        audioFifoFd = openSync(audioFifoPath, fsConstants.O_RDONLY | fsConstants.O_NONBLOCK);
      } catch (_error) {
        audioFifoRetryAt = Date.now() + 3000;
      }
    }
    if (audioFifoFd !== null) {
      try {
        got = readSync(audioFifoFd, audioChunk, 0, want, null);
      } catch (error) {
        if (error.code !== 'EAGAIN') {
          try { closeSync(audioFifoFd); } catch (_error) {}
          audioFifoFd = null;
          audioFifoRetryAt = Date.now() + 3000;
        }
      }
    }
    if (got < want) audioChunk.fill(0, got, want);
    try {
      ffmpeg.stdio[3].write(Buffer.from(audioChunk.subarray(0, want)));
    } catch (_error) {
      return;
    }
    audioSent += want;
    deficit -= want;
  }
}, 50);

let latestShot = null;
let lastShotAt = Date.now();
const cdp = await page.context().newCDPSession(page);
cdp.on('Page.screencastFrame', event => {
  latestShot = Buffer.from(event.data, 'base64');
  lastShotAt = Date.now();
  cdp.send('Page.screencastFrameAck', {sessionId: event.sessionId}).catch(() => {});
});
await cdp.send('Page.startScreencast', {
  format: 'png',
  everyNthFrame: 1,
  maxWidth: width,
  maxHeight: height
});

console.error(
  args.testOutput
    ? 'rendering overlay (pipeline test)'
    : 'streaming overlay to RTMP ingest'
);

let stopping = false;
const stop = () => { stopping = true; };
process.on('SIGINT', stop);
process.on('SIGTERM', stop);

const startedAt = Date.now();
let piped = 0;
await new Promise(resolve => {
  const timer = setInterval(() => {
    if (
      stopping ||
      (args.duration && Date.now() - startedAt >= args.duration * 1000) ||
      Date.now() - lastShotAt > STALL_EXIT_MS ||
      ffmpeg.exitCode !== null
    ) {
      clearInterval(timer);
      resolve();
      return;
    }
    if (latestShot) {
      try {
        ffmpeg.stdin.write(latestShot);
        piped += 1;
      } catch (_error) {
        clearInterval(timer);
        resolve();
      }
    }
  }, 1000 / FRAME_RATE);
});

clearInterval(audioTimer);
if (audioFifoFd !== null) { try { closeSync(audioFifoFd); } catch (_error) {} }
try { ffmpeg.stdio[3].end(); } catch (_error) {}
try { ffmpeg.stdin.end(); } catch (_error) {}
await new Promise(resolve => {
  const kill = setTimeout(() => { ffmpeg.kill('SIGKILL'); resolve(); }, 10000);
  ffmpeg.on('close', () => { clearTimeout(kill); resolve(); });
  if (ffmpeg.exitCode !== null) { clearTimeout(kill); resolve(); }
});
await browser.close();
server.close();
console.error(`frames piped: ${piped}`);
process.exit(piped ? 0 : 1);
