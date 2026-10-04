import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
// Paths come from env (documented in README "Configuration"); nothing machine-specific is hardcoded here.
//   PLAYWRIGHT_MODULE  path to @playwright/test/index.mjs (or a package name); else APP_DIR/clients/web/node_modules/@playwright/test; else "@playwright/test"
//   CHROME_PATH        Chrome/Chromium executable; else /opt/google/chrome/chrome when present; else Playwright's bundled Chromium
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
export const CHROME = process.env.CHROME_PATH || (fs.existsSync("/opt/google/chrome/chrome") ? "/opt/google/chrome/chrome" : undefined);
export const BASE = process.env.BASE || "http://127.0.0.1:6460/";
export const COMMIT = process.env.COMMIT || "4a427fc05f829d7b2e4ed7ea642d77340554f7f8";
export const VIEWPORT = { width: 1920, height: 1080 };
// Capture-only CSS. Every take gets BASE_CSS (no CSS cursor); named snippets are recorded per clip (meta.json -> manifest.yaml).
export const BASE_CSS = "html,body,*{cursor:none!important}";
export const CSS = {
  NO_TOASTS: "[data-sonner-toaster]{display:none!important}",
  HIDE_MONEY: "section.glass-pop:has(.heading.tabular){visibility:hidden!important} section.glass-pop span.text-meta.tabular.text-dim:has(> .tabular){visibility:hidden!important}",
};
// Names of the known snippets contained in a css string (+ "CUSTOM" when anything else is injected).
export function cssFlags(css = "") {
  let rest = css; const flags = [];
  for (const [k, v] of Object.entries(CSS)) if (rest.includes(v)) { flags.push(k); rest = rest.split(v).join(""); }
  if (rest.trim()) flags.push("CUSTOM");
  return flags;
}
// Per-page capture facts (viewport, dpr, injected css, cursor overlay) read by Recorder for meta.json.
const INFO = new WeakMap();
export const capInfo = (page) => INFO.get(page) || { viewport: VIEWPORT, dpr: 1, css: "", cssFlags: [], cursorHidden: true, cursorOverlay: false };
export function markCursorOverlay(page) { INFO.set(page, { ...capInfo(page), cursorOverlay: true }); }
export async function launch() {
  return chromium.launch({ executablePath: CHROME, args: ["--hide-scrollbars", "--force-color-profile=srgb", "--disable-lcd-text", "--font-render-hinting=none", "--enable-unsafe-swiftshader", "--use-angle=swiftshader"] });
}
export function prefs(extra = {}) {
  return { theme: "dark", reduceMotion: false, endSoundOn: false, conversationWidth: 460, boardView: "dag", stage: {}, lastWorkspace: null, setupAcknowledged: true, tourSeen: true, introSeen: true, workshopIntroDone: true, ...extra };
}
export async function open(browser, { q = "?demo=1", hash = "", dpr = 1, prefsExtra = {}, clock = false, css = "", time = "2026-10-01T22:40:00+10:00", seed = false, base = BASE } = {}) {
  const ctx = await browser.newContext({ viewport: VIEWPORT, deviceScaleFactor: dpr, colorScheme: "dark", reducedMotion: "no-preference" });
  const page = await ctx.newPage();
  INFO.set(page, { viewport: VIEWPORT, dpr, css, cssFlags: cssFlags(css), cursorHidden: true, cursorOverlay: false });
  await page.addInitScript(([p, css, base]) => {
    if (!sessionStorage.getItem("cap-init")) { localStorage.setItem("commission.prefs.v1", JSON.stringify({ state: p, version: 1 })); sessionStorage.setItem("cap-init", "1"); }
    const add = () => { const s = document.createElement("style"); s.id = "cap-css"; s.textContent = base + "\n" + css; (document.head || document.documentElement).appendChild(s); };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add); else add();
  }, [prefs(prefsExtra), css, BASE_CSS]);
  const T0 = new Date(time);
  if (seed) await page.addInitScript(() => { let a = 0x9e3779b9; Math.random = () => { a |= 0; a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; });
  if (clock) await page.clock.install({ time: T0 });
  if (clock === "paused") await page.clock.pauseAt(new Date(T0.getTime() + 500));
  await page.goto(base + q + hash);
  return { ctx, page };
}
export async function dismiss(page) {
  for (const n of [/^(Continue|Continue anyway|Open CommissionAI)$/i, /^Not now$/i, /^Got it$/i]) {
    const l = page.getByRole("button", { name: n }).first();
    if (await l.isVisible().catch(() => false)) { await l.click().catch(() => {}); await page.waitForTimeout(400); }
  }
}
export const tab = (page, name) => page.locator(`[aria-label=Stage] [role=tab]`).filter({ hasText: name }).first();
