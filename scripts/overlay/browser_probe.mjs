#!/usr/bin/env node
// Real-browser liveness probe for the stream destinations.
//
// yt-dlp tells you what the API thinks; this tells you what a viewer actually
// sees. Loads the page in headless Chromium, waits for the player, samples the
// <video> element twice to confirm playback is advancing, reads the platform's
// live/offline markers, and writes a screenshot for eyeball confirmation.
//
//   node browser_probe.mjs <url> [<url>...] [--shots-dir DIR] [--headful]
//
// Prints one JSON object: { results: [ { url, platform, live, ... } ] }

import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { createRequire } from 'node:module';

let chromium;
try {
  ({ chromium } = createRequire(import.meta.url)('playwright'));
} catch {
  ({ chromium } = createRequire(path.join(process.cwd(), 'noop.js'))('playwright'));
}

const argv = process.argv.slice(2);
const urls = argv.filter((a) => a.startsWith('http'));
const headful = argv.includes('--headful');
const shotsIdx = argv.indexOf('--shots-dir');
const shotsDir =
  shotsIdx >= 0 && argv[shotsIdx + 1]
    ? argv[shotsIdx + 1]
    : path.join(os.homedir(), '.openrappter/pokemon-red/probe-shots');

if (urls.length === 0) {
  console.error('usage: browser_probe.mjs <url> [<url>...] [--shots-dir DIR]');
  process.exit(2);
}
fs.mkdirSync(shotsDir, { recursive: true });

const platformOf = (url) =>
  url.includes('twitch.tv') ? 'twitch' : url.includes('youtu') ? 'youtube' : 'unknown';

// Sampled inside the page: everything we can learn from the DOM in one pass.
function readPlayerState() {
  const video = document.querySelector('video');
  const text = (document.body.innerText || '').slice(0, 4000).toLowerCase();

  const ytLiveBadge = document.querySelector('.ytp-live-badge');
  const ytBadgeVisible =
    !!ytLiveBadge && !!ytLiveBadge.offsetParent && !ytLiveBadge.classList.contains('ytp-live-badge-is-disabled');

  const twGate = document.querySelector('[data-a-target="player-overlay-content-gate"]');
  const twLiveIndicator = document.querySelector(
    '.tw-channel-status-text-indicator, [data-a-target="animated-channel-viewers-count"]'
  );

  return {
    videoPresent: !!video,
    videoPaused: video ? video.paused : null,
    videoTime: video ? video.currentTime : null,
    videoReadyState: video ? video.readyState : null,
    // Delivered frame geometry. A stream can be perfectly "live" and still be
    // unwatchable if the platform re-canvases it - e.g. YouTube's Dual stream
    // pads a 16:9 feed to 1:1, which double-letterboxes it in a 16:9 player.
    videoWidth: video ? video.videoWidth : null,
    videoHeight: video ? video.videoHeight : null,
    videoAspect:
      video && video.videoHeight ? +(video.videoWidth / video.videoHeight).toFixed(3) : null,
    // A live HLS stream reports a seekable range whose end tracks wall clock;
    // Infinity duration is the classic live marker.
    videoDuration: video ? (Number.isFinite(video.duration) ? video.duration : 'Infinity') : null,
    ytLiveBadgeVisible: ytBadgeVisible,
    twitchOfflineGate: !!twGate,
    twitchLiveIndicator: !!twLiveIndicator,
    mentionsOffline: /is offline|stream is offline|currently offline/.test(text),
    mentionsWasLive: /streamed live|was live/.test(text),
    title: document.title,
  };
}

const results = [];
const browser = await chromium.launch({
  headless: !headful,
  args: ['--autoplay-policy=no-user-gesture-required', '--mute-audio'],
});

for (const url of urls) {
  const platform = platformOf(url);
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const shot = path.join(shotsDir, `${platform}-${stamp}.png`);
  const entry = { url, platform, screenshot: shot };

  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    userAgent:
      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 ' +
      '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    locale: 'en-US',
  });
  const page = await context.newPage();

  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });

    // Dismiss consent walls that would otherwise hide the player entirely.
    for (const sel of [
      'button[aria-label*="Accept all" i]',
      'button:has-text("Accept all")',
      'button:has-text("I Accept")',
      '[data-a-target="consent-banner-accept"]',
    ]) {
      try {
        const btn = page.locator(sel).first();
        if (await btn.isVisible({ timeout: 1200 })) await btn.click({ timeout: 2500 });
      } catch {
        /* no banner, fine */
      }
    }

    await page.waitForSelector('video', { timeout: 25000 }).catch(() => {});
    await page.waitForTimeout(4000);

    const first = await page.evaluate(readPlayerState);
    await page.waitForTimeout(4000);
    const second = await page.evaluate(readPlayerState);

    const advanced =
      first.videoTime !== null && second.videoTime !== null && second.videoTime > first.videoTime + 0.4;

    Object.assign(entry, second, { videoTimeAdvanced: advanced });

    // Conservative verdict: playback must actually be moving AND the platform
    // must be flagging it as live. Either signal alone is not enough - a VOD
    // also advances, and a stale badge can outlive the feed.
    if (platform === 'youtube') {
      entry.live = advanced && second.ytLiveBadgeVisible && !second.mentionsWasLive;
    } else if (platform === 'twitch') {
      entry.live = advanced && !second.twitchOfflineGate && !second.mentionsOffline;
    } else {
      entry.live = advanced;
    }

    await page.screenshot({ path: shot, fullPage: false });
  } catch (err) {
    entry.live = false;
    entry.error = String(err && err.message ? err.message : err);
    try {
      await page.screenshot({ path: shot, fullPage: false });
    } catch {
      entry.screenshot = null;
    }
  } finally {
    await context.close();
  }

  results.push(entry);
}

await browser.close();
console.log(JSON.stringify({ results }, null, 2));
process.exit(results.every((r) => r.live) ? 0 : 1);
