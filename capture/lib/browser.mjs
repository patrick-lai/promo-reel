// Browser side of the paint-safe capture kit: resolve Playwright, launch Chrome with capture flags, open a page with a fixed
// viewport, device pixel ratio, paused clock and capture-only CSS. App-specific bits (prefs, dismissing dialogs, CSS snippets)
// live next to the app's take scripts (capture/<app>/app.mjs).
//
// Environment (nothing machine-specific is hardcoded):
//   PLAYWRIGHT_MODULE  path to @playwright/test/index.mjs (or a package name); else APP_DIR/clients/web/node_modules/@playwright/test; else "@playwright/test"
//   CHROME_PATH        Chrome/Chromium executable; else Playwright's bundled Chromium
//   CAPTURE_GL         "gpu" (default) or "swiftshader" (software GL for boxes without a GPU; slower raster, so more paint races to wait out)
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

function playwrightSpec() {
  const env = process.env.PLAYWRIGHT_MODULE;
  if (env) return env.startsWith("/") ? pathToFileURL(env).href : env;
  if (process.env.APP_DIR) {
    const p = path.join(process.env.APP_DIR, "clients/web/node_modules/@playwright/test/index.mjs");
    if (fs.existsSync(p)) return pathToFileURL(p).href;
  }
  return "@playwright/test";
}
export const { chromium } = await import(playwrightSpec());
export const CHROME = process.env.CHROME_PATH || undefined;
export const VIEWPORT = { width: 1920, height: 1080 };
export const COMMIT = process.env.COMMIT || "unknown";
// Every take hides the CSS cursor; a take that is about a click draws its own overlay cursor (markCursorOverlay).
export const BASE_CSS = "html,body,*{cursor:none!important}";

export async function launch() {
  const gl = process.env.CAPTURE_GL === "swiftshader" ? ["--enable-unsafe-swiftshader", "--use-angle=swiftshader"] : [];
  // --disable-checker-imaging: decode images before the frame that shows them instead of drawing a blank placeholder first.
  return chromium.launch({ executablePath: CHROME, args: ["--hide-scrollbars", "--force-color-profile=srgb", "--disable-lcd-text", "--font-render-hinting=none", "--disable-checker-imaging", ...gl] });
}

// Per-page capture facts (viewport, dpr, injected css, cursor overlay) the Recorder writes into each take's meta.json.
const INFO = new WeakMap();
export const capInfo = (page) => INFO.get(page) || { viewport: VIEWPORT, dpr: 1, css: "", cssFlags: [], cursorHidden: true, cursorOverlay: false };
export function markCursorOverlay(page) { INFO.set(page, { ...capInfo(page), cursorOverlay: true }); }

// Names of the known snippets in an injected css string (+ "CUSTOM" for anything else), so the manifest says what was hidden.
export function cssFlags(css = "", known = {}) {
  let rest = css; const flags = [];
  for (const [k, v] of Object.entries(known)) if (rest.includes(v)) { flags.push(k); rest = rest.split(v).join(""); }
  if (rest.trim()) flags.push("CUSTOM");
  return flags;
}

// dpr is the capture resolution: a clip of W css px comes out W x dpr px wide (the Recorder never asks Chrome to rescale).
export async function open(browser, { url, dpr = 2, clock = false, time = "2026-10-01T22:40:00+10:00", css = "", knownCss = {}, init = null, seed = false,
  colorScheme = "dark", gotoTimeout = Number(process.env.GOTO_TIMEOUT || 30000) } = {}) {
  const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: dpr, colorScheme, reducedMotion: "no-preference" });
  const page = await ctx.newPage();
  INFO.set(page, { viewport: VIEWPORT, dpr, css, cssFlags: cssFlags(css, knownCss), cursorHidden: true, cursorOverlay: false });
  await page.addInitScript(([css, base]) => {
    const add = () => { const s = document.createElement("style"); s.id = "cap-css"; s.textContent = base + "\n" + css; (document.head || document.documentElement).appendChild(s); };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add); else add();
  }, [css, BASE_CSS]);
  if (init) await page.addInitScript(init.fn, init.arg);
  if (seed) await page.addInitScript(() => { let a = 0x9e3779b9; Math.random = () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; });
  const T0 = new Date(time);
  if (clock) await page.clock.install({ time: T0 });
  if (clock === "paused") await page.clock.pauseAt(new Date(T0.getTime() + 500));
  await page.goto(url, { timeout: gotoTimeout });
  return { ctx, page };
}
