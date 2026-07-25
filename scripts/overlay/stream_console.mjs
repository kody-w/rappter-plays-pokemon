#!/usr/bin/env node
// Drives the YouTube Studio + Twitch dashboards in a real browser using a
// persistent profile, so the one-time human login is the ONLY manual step.
//
//   node stream_console.mjs login            # headful; sign in to Google + Twitch once
//   node stream_console.mjs twitch-key       # scrape the stream key -> mode-600 file
//   node stream_console.mjs youtube-autostart# enable Auto-start/Auto-stop on the key
//   node stream_console.mjs status           # report what's logged in / configured
//
// The profile lives outside the repo and holds real session cookies - it is
// treated like a credential. The Twitch key is written straight to disk and is
// never printed to stdout.

import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { createRequire } from 'node:module';

const require_ = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require_('playwright'));
} catch {
  ({ chromium } = createRequire(path.join(process.cwd(), 'noop.js'))('playwright'));
}

const RUNTIME = path.join(os.homedir(), '.openrappter/pokemon-red');
const PROFILE_DIR = path.join(RUNTIME, 'browser-profile');
const TWITCH_KEY_FILE = path.join(RUNTIME, 'twitch-key.txt');
const SHOTS = path.join(RUNTIME, 'probe-shots');
const CHANNEL_ID = process.env.RPP_YT_CHANNEL_ID || 'UCz0Tfe07OAwnQR-fd3E1y4Q';

const STUDIO_LIVE = `https://studio.youtube.com/channel/${CHANNEL_ID}/livestreaming`;
const TWITCH_STREAM_SETTINGS = 'https://dashboard.twitch.tv/settings/stream';

const cmd = process.argv[2] || 'status';
fs.mkdirSync(PROFILE_DIR, { recursive: true });
fs.mkdirSync(SHOTS, { recursive: true });

const shot = (name) => path.join(SHOTS, `${name}-${new Date().toISOString().replace(/[:.]/g, '-')}.png`);

async function open({ headless }) {
  return chromium.launchPersistentContext(PROFILE_DIR, {
    headless,
    viewport: { width: 1440, height: 900 },
    args: ['--autoplay-policy=no-user-gesture-required', '--mute-audio'],
  });
}

// --- login -----------------------------------------------------------------

async function login() {
  const ctx = await open({ headless: false });
  const yt = ctx.pages()[0] || (await ctx.newPage());
  await yt.goto(STUDIO_LIVE, { waitUntil: 'domcontentloaded' }).catch(() => {});
  const tw = await ctx.newPage();
  await tw.goto(TWITCH_STREAM_SETTINGS, { waitUntil: 'domcontentloaded' }).catch(() => {});

  console.log(
    [
      '',
      'A browser window is open with two tabs:',
      '  1. YouTube Studio -> Live control room',
      '  2. Twitch -> Settings -> Stream',
      '',
      'Sign in to both. Close the window when done; the session is saved to',
      `  ${PROFILE_DIR}`,
      'and every later run reuses it with no login.',
      '',
    ].join('\n')
  );

  await new Promise((resolve) => ctx.on('close', resolve));
  console.log('profile saved');
}

// --- twitch ----------------------------------------------------------------

async function twitchKey() {
  const ctx = await open({ headless: true });
  const page = ctx.pages()[0] || (await ctx.newPage());
  const out = { ok: false };
  try {
    await page.goto(TWITCH_STREAM_SETTINGS, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(4000);

    if (/\/login/.test(page.url()) || (await page.locator('input[type="password"]').count())) {
      out.error = 'not signed in to Twitch - run: node stream_console.mjs login';
      out.screenshot = shot('twitch-settings');
      await page.screenshot({ path: out.screenshot });
      return out;
    }

    // The key renders masked with a "Show" toggle beside it; until that is
    // clicked the input holds bullet characters rather than the real value.
    for (const sel of ['text=Show', 'button:has-text("Show")', 'a:has-text("Show")']) {
      try {
        const link = page.locator(sel).first();
        if (await link.isVisible({ timeout: 2000 })) {
          await link.click({ timeout: 3000 });
          await page.waitForTimeout(1800);
          break;
        }
      } catch {
        /* already revealed */
      }
    }

    let key = null;
    const candidates = page.locator('input[type="password"], input[readonly], input[value^="live_"]');
    const n = await candidates.count();
    for (let i = 0; i < n; i++) {
      const v = await candidates.nth(i).inputValue().catch(() => '');
      if (v && /^live_/.test(v)) {
        key = v;
        break;
      }
    }
    if (!key) {
      const bodyKey = await page.evaluate(() => {
        const m = (document.body.innerText || '').match(/live_[0-9]{6,}_[A-Za-z0-9]+/);
        return m ? m[0] : null;
      });
      if (bodyKey) key = bodyKey;
    }

    if (!key) {
      out.error = 'could not locate the stream key field';
      out.screenshot = shot('twitch-settings');
      await page.screenshot({ path: out.screenshot });
      return out;
    }

    fs.writeFileSync(TWITCH_KEY_FILE, key + '\n', { mode: 0o600 });
    fs.chmodSync(TWITCH_KEY_FILE, 0o600);
    out.ok = true;
    out.wrote = TWITCH_KEY_FILE;
    out.keyPreview = key.slice(0, 9) + '...' + key.slice(-4); // never the whole key
  } catch (err) {
    out.error = String(err.message || err);
  } finally {
    await ctx.close();
  }
  return out;
}

// --- youtube ---------------------------------------------------------------

async function youtubeAutostart() {
  const ctx = await open({ headless: true });
  const page = ctx.pages()[0] || (await ctx.newPage());
  const out = { ok: false, changed: [] };
  try {
    await page.goto(STUDIO_LIVE, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(6000);

    if (/accounts\.google\.com/.test(page.url())) {
      out.error = 'not signed in to Google - run: node stream_console.mjs login';
      out.screenshot = shot('yt-studio');
      await page.screenshot({ path: out.screenshot });
      return out;
    }

    // Studio hides these behind the stream's edit dialog; open it if present.
    for (const sel of ['#edit-button', 'button:has-text("Edit")', 'ytls-edit-button']) {
      try {
        const b = page.locator(sel).first();
        if (await b.isVisible({ timeout: 2000 })) {
          await b.click({ timeout: 4000 });
          await page.waitForTimeout(2500);
          break;
        }
      } catch {
        /* dialog not present */
      }
    }

    for (const label of ['auto-start', 'auto start', 'autostart', 'auto-stop', 'auto stop', 'autostop']) {
      const row = page
        .locator(`//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'${label}')]`)
        .last();
      try {
        if (!(await row.isVisible({ timeout: 1500 }))) continue;
        const toggle = row.locator('tp-yt-paper-toggle-button, [role="switch"], input[type="checkbox"]').first();
        if (!(await toggle.count())) continue;
        const on = await toggle.evaluate(
          (el) =>
            el.getAttribute('aria-checked') === 'true' ||
            el.getAttribute('aria-pressed') === 'true' ||
            el.checked === true ||
            el.hasAttribute('checked')
        );
        if (!on) {
          await toggle.click({ timeout: 4000 });
          await page.waitForTimeout(1200);
          out.changed.push(label);
        }
      } catch {
        /* selector miss - screenshot below shows the truth */
      }
    }

    for (const sel of ['button:has-text("Save")', '#save-button', 'ytcp-button:has-text("Save")']) {
      try {
        const b = page.locator(sel).first();
        if (await b.isVisible({ timeout: 1500 })) {
          await b.click({ timeout: 4000 });
          out.saved = true;
          await page.waitForTimeout(2500);
          break;
        }
      } catch {
        /* nothing to save */
      }
    }

    out.ok = true;
    out.screenshot = shot('yt-studio');
    await page.screenshot({ path: out.screenshot, fullPage: true });
  } catch (err) {
    out.error = String(err.message || err);
  } finally {
    await ctx.close();
  }
  return out;
}

// --- status ----------------------------------------------------------------

async function status() {
  const out = {
    profileDir: PROFILE_DIR,
    profileExists: fs.existsSync(path.join(PROFILE_DIR, 'Default')),
    twitchKeyFile: fs.existsSync(TWITCH_KEY_FILE),
  };
  if (!out.profileExists) {
    out.next = 'node stream_console.mjs login';
    return out;
  }
  const ctx = await open({ headless: true });
  const page = ctx.pages()[0] || (await ctx.newPage());
  try {
    await page.goto(STUDIO_LIVE, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(4000);
    out.googleSignedIn = !/accounts\.google\.com/.test(page.url());
    await page.goto(TWITCH_STREAM_SETTINGS, { waitUntil: 'domcontentloaded', timeout: 45000 });
    await page.waitForTimeout(4000);
    out.twitchSignedIn = !/\/login/.test(page.url());
  } catch (err) {
    out.error = String(err.message || err);
  } finally {
    await ctx.close();
  }
  return out;
}

const handlers = { login, 'twitch-key': twitchKey, 'youtube-autostart': youtubeAutostart, status };
if (!handlers[cmd]) {
  console.error(`unknown command ${cmd}; expected one of ${Object.keys(handlers).join(', ')}`);
  process.exit(2);
}
const result = await handlers[cmd]();
if (result) console.log(JSON.stringify(result, null, 2));
process.exit(result && result.ok === false ? 1 : 0);
