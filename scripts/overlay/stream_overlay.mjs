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
import {readFile} from 'node:fs/promises';
import {readFileSync, existsSync} from 'node:fs';
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
  '-f', 'lavfi',
  '-i', 'anullsrc=r=44100:cl=stereo',
  '-vf', 'format=yuv420p',
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
], {stdio: ['pipe', 'inherit', 'inherit']});

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
