export const { chromium } = await import("/workspace/wt-promo-v1-1004/clients/web/node_modules/@playwright/test/index.mjs");
import fs from "node:fs";
export const BASE = process.env.BASE || "http://127.0.0.1:6460/";
export const COMMIT = process.env.COMMIT || "4a427fc05f829d7b2e4ed7ea642d77340554f7f8";
export async function launch() {
  return chromium.launch({ executablePath: "/opt/google/chrome/chrome", args: ["--hide-scrollbars", "--force-color-profile=srgb", "--disable-lcd-text", "--font-render-hinting=none", "--enable-unsafe-swiftshader", "--use-angle=swiftshader"] });
}
export function prefs(extra = {}) {
  return { theme: "dark", reduceMotion: false, endSoundOn: false, conversationWidth: 460, boardView: "dag", stage: {}, lastWorkspace: null, setupAcknowledged: true, tourSeen: true, introSeen: true, workshopIntroDone: true, ...extra };
}
export async function open(browser, { q = "?demo=1", hash = "", dpr = 1, prefsExtra = {}, clock = false, css = "", time = "2026-10-01T22:40:00+10:00", seed = false, base = BASE } = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: dpr, colorScheme: "dark", reducedMotion: "no-preference" });
  const page = await ctx.newPage();
  await page.addInitScript(([p, css]) => {
    if (!sessionStorage.getItem("cap-init")) { localStorage.setItem("commission.prefs.v1", JSON.stringify({ state: p, version: 1 })); sessionStorage.setItem("cap-init", "1"); }
    const add = () => { const s = document.createElement("style"); s.id = "cap-css"; s.textContent = "html,body,*{cursor:none!important}\n" + css; (document.head || document.documentElement).appendChild(s); };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", add); else add();
  }, [prefs(prefsExtra), css]);
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
