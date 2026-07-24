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
//   node scripts/overlay/stream_overlay.mjs --key-file key.txt \
//     --mirror-url 'udp://127.0.0.1:23000?pkt_size=1316'
//
// Requires: ffmpeg on PATH, and `playwright` resolvable from the working
// directory (npm install playwright).

import {createServer} from 'node:http';
import {readFile, readdir, stat} from 'node:fs/promises';
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
const FRAME_RATE = 20;
const VIDEO_MAX_CATCHUP_FRAMES = FRAME_RATE * 2;
const STALL_EXIT_MS = 60000;
const BACKPRESSURE_EXIT_MS = 30000;

function parseArgs(argv) {
  const args = {
    runtimeDir: path.join(homedir(), '.openrappter', 'pokemon-red'),
    ingest: 'rtmp://a.rtmp.youtube.com/live2',
    rtmp: '',
    keyFile: '',
    testOutput: '',
    mirrorUrl: '',
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
      case '--mirror-url': args.mirrorUrl = value(); break;
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

function outputTargetArgs(primaryTarget, mirrorUrl) {
  if (!mirrorUrl) return ['-f', 'flv', primaryTarget];
  return [
    '-map', '0:v:0',
    '-map', '1:a:0',
    '-f', 'tee',
    // use_fifo decouples the branches: without it tee writes synchronously,
    // so RTMP backpressure makes the UDP mirror bursty — OBS then hits "max
    // audio buffering / restarting source audio" and the relayed stream
    // crackles. The primary branch still fails ffmpeg on YouTube ingest
    // death so run_forever's restart loop re-triggers auto-start; only the
    // mirror is onfail=ignore.
    `[f=flv:use_fifo=1]${primaryTarget}|` +
      `[f=mpegts:use_fifo=1:onfail=ignore]${mirrorUrl}`
  ];
}

const overlayHtml = await readFile(path.join(SCRIPT_DIR, 'overlay.html'));
const qriousRuntime = await readFile(
  path.join(
    SCRIPT_DIR,
    '..',
    '..',
    'vendor',
    'browser',
    'qrious-4.0.2.runtime.min.js'
  )
);
const encoderMetrics = {
  audioSent: 0,
  audioWindow: [],
  captureTimes: [],
  encoderStartedAt: 0,
  audioBackpressureAt: 0,
  videoBackpressureAt: 0,
  lastShotAt: 0,
  piped: 0
};

function tuningSnapshot(sourceAgeMs) {
  const now = Date.now();
  const recentAudio = encoderMetrics.audioWindow
    .filter(sample => sample.at >= now - 10000);
  encoderMetrics.audioWindow = recentAudio;
  const audioTotal = recentAudio.reduce((total, sample) => total + sample.total, 0);
  const audioReal = recentAudio.reduce((total, sample) => total + sample.real, 0);
  const captureTimes = encoderMetrics.captureTimes
    .filter(timestamp => timestamp >= now - 5000);
  encoderMetrics.captureTimes = captureTimes;
  const captureSpan = captureTimes.length > 1
    ? (captureTimes[captureTimes.length - 1] - captureTimes[0]) / 1000
    : 0;
  const audioClock = encoderMetrics.audioSent > 0
    ? encoderMetrics.audioSent / (48000 * 2 * 2) * 1000
    : null;
  const videoClock = encoderMetrics.piped > 0
    ? encoderMetrics.piped / FRAME_RATE * 1000
    : null;
  return {
    schema_version: 1,
    av_clock_drift_ms:
      audioClock === null || videoClock === null
        ? null
        : Math.round(audioClock - videoClock),
    configured_audio_delay_ms: 200,
    audio_fill_percent:
      audioTotal > 0 ? Math.round(audioReal / audioTotal * 1000) / 10 : null,
    source_age_ms:
      Number.isFinite(sourceAgeMs) ? Math.max(0, Math.round(sourceAgeMs)) : null,
    capture_age_ms:
      encoderMetrics.lastShotAt
        ? Math.max(0, Math.round(now - encoderMetrics.lastShotAt))
        : null,
    capture_fps:
      captureSpan > 0
        ? Math.round((captureTimes.length - 1) / captureSpan * 10) / 10
        : null,
    encoder_uptime_seconds:
      encoderMetrics.encoderStartedAt
        ? Math.max(0, Math.round((now - encoderMetrics.encoderStartedAt) / 1000))
        : null,
    encoder_state: encoderMetrics.encoderStartedAt ? 'up' : 'starting'
  };
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
  try {
    if (url.pathname === '/') {
      response.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
      response.end(overlayHtml);
    } else if (url.pathname === '/vendor/qrious.js') {
      response.writeHead(200, {
        'Content-Type': 'text/javascript; charset=utf-8',
        'Cache-Control': 'public, max-age=31536000, immutable'
      });
      response.end(qriousRuntime);
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
      const host = {
        brain_status: 'idle',
        actions_taken: null,
        clips_count: null,
        latest_clip_location: null,
        brain_recent: [],
        emulation_speed: null,
        decision_latency_seconds: null,
        reasoning_effort: null,
        crowd_hints_enabled: false,
        crowd_hints_state: 'off',
        crowd_hints_count: 0,
        navigation_memory_count: 0,
        web_research_enabled: false,
        web_research_state: 'off',
        web_research_source_count: 0,
        tuning: null
      };
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
        host.brain_status =
          brain.updated_at &&
          Date.now() - Date.parse(brain.updated_at) < 120000
            ? 'active' : 'idle';
        host.actions_taken = brain.total_decisions ?? null;
        host.clips_count = newest
          ? Number((newest.match(/^clip-0*(\d+)/) || [])[1]) || metas.length
          : null;
        host.latest_clip_location =
          latest && latest.game_state ? latest.game_state.location ?? null : null;
        host.brain_recent = Array.isArray(brain.history)
          ? brain.history.slice(-3).reverse().map(entry => ({
              reason: entry.reason || '',
              at: entry.timestamp || null
            }))
          : [];
      } catch (_error) {}
      try {
        const agentStatus = JSON.parse(
          await readFile(path.join(runtimeDir, 'status.json'), 'utf-8')
        );
        host.emulation_speed = agentStatus.emulation_speed ?? null;
        host.decision_latency_seconds =
          agentStatus.decision_latency_seconds ?? null;
        host.reasoning_effort = agentStatus.reasoning_effort ?? null;
        host.crowd_hints_enabled =
          agentStatus.crowd_hints_enabled === true;
        host.crowd_hints_state =
          agentStatus.crowd_hints_state ?? 'off';
        host.crowd_hints_count =
          Number.isInteger(agentStatus.crowd_hints_count)
            ? agentStatus.crowd_hints_count : 0;
        host.navigation_memory_count =
          Number.isInteger(agentStatus.navigation_memory_count)
            ? agentStatus.navigation_memory_count : 0;
        host.web_research_enabled =
          agentStatus.web_research_enabled === true;
        host.web_research_state =
          agentStatus.web_research_state ?? 'off';
        host.web_research_source_count =
          Number.isInteger(agentStatus.web_research_source_count)
            ? agentStatus.web_research_source_count : 0;
      } catch (_error) {}
      let sourceAgeMs = null;
      try {
        const source = await stat(path.join(runtimeDir, 'latest.png'));
        sourceAgeMs = Date.now() - source.mtimeMs;
      } catch (_error) {}
      host.tuning = tuningSnapshot(sourceAgeMs);
      telemetry.host = host;
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

let stopping = false;
const stop = () => { stopping = true; };
process.on('SIGINT', stop);
process.on('SIGTERM', stop);

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
  ...outputTargetArgs(target, args.mirrorUrl)
], {stdio: ['pipe', 'inherit', 'inherit', 'pipe']});
encoderMetrics.encoderStartedAt = Date.now();

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
  const audioPipe = ffmpeg.stdio[3];
  if (audioPipe && audioPipe.writableNeedDrain) {
    if (!encoderMetrics.audioBackpressureAt) {
      encoderMetrics.audioBackpressureAt = Date.now();
    } else if (
      Date.now() - encoderMetrics.audioBackpressureAt > BACKPRESSURE_EXIT_MS
    ) {
      stopping = true;
    }
    return;
  }
  encoderMetrics.audioBackpressureAt = 0;
  const due = Math.floor((Date.now() - audioStartedAt) / 1000 * AUDIO_BYTES_PER_SECOND) & ~3;
  let deficit = due - audioSent;
  if (deficit <= 0 || !audioPipe || ffmpeg.exitCode !== null) return;
  let tickReal = 0;
  let tickTotal = 0;
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
      audioPipe.write(Buffer.from(audioChunk.subarray(0, want)));
    } catch (_error) {
      return;
    }
    audioSent += want;
    tickReal += got;
    tickTotal += want;
    deficit -= want;
  }
  encoderMetrics.audioSent = audioSent;
  encoderMetrics.audioWindow.push({
    at: Date.now(),
    real: tickReal,
    total: tickTotal
  });
  if (encoderMetrics.audioWindow.length > 400) {
    encoderMetrics.audioWindow.splice(
      0,
      encoderMetrics.audioWindow.length - 400
    );
  }
}, 50);

let latestShot = null;
let lastShotAt = Date.now();
encoderMetrics.lastShotAt = lastShotAt;
const cdp = await page.context().newCDPSession(page);
cdp.on('Page.screencastFrame', event => {
  latestShot = Buffer.from(event.data, 'base64');
  lastShotAt = Date.now();
  encoderMetrics.lastShotAt = lastShotAt;
  encoderMetrics.captureTimes.push(lastShotAt);
  if (encoderMetrics.captureTimes.length > 600) {
    encoderMetrics.captureTimes.splice(
      0,
      encoderMetrics.captureTimes.length - 600
    );
  }
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
    : args.mirrorUrl
      ? 'streaming overlay to RTMP ingest and local mirror'
      : 'streaming overlay to RTMP ingest'
);

const startedAt = Date.now();
let piped = 0;
let videoStartedAt = 0;
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
      const now = Date.now();
      if (!videoStartedAt) videoStartedAt = now;
      const dueFrames =
        Math.floor((now - videoStartedAt) / 1000 * FRAME_RATE) + 1;
      let deficit = dueFrames - piped;
      if (deficit > VIDEO_MAX_CATCHUP_FRAMES) {
        videoStartedAt = now - piped / FRAME_RATE * 1000;
        deficit = 1;
      }
      while (deficit > 0) {
        if (ffmpeg.stdin.writableNeedDrain) {
          if (!encoderMetrics.videoBackpressureAt) {
            encoderMetrics.videoBackpressureAt = Date.now();
          } else if (
            Date.now() - encoderMetrics.videoBackpressureAt >
              BACKPRESSURE_EXIT_MS
          ) {
            stopping = true;
          }
          return;
        }
        encoderMetrics.videoBackpressureAt = 0;
        try {
          ffmpeg.stdin.write(latestShot);
          piped += 1;
          encoderMetrics.piped = piped;
          deficit -= 1;
        } catch (_error) {
          clearInterval(timer);
          resolve();
          return;
        }
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
