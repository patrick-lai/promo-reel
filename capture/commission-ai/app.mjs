// CommissionAI web client specifics for take scripts: saved prefs that skip the intro, capture-only CSS snippets, dismissing
// first-run dialogs. Generic launch / recorder: capture/lib. BASE is the web client's URL (a Vite dev server of the app at COMMIT).
import { launch, open as openPage, markCursorOverlay, COMMIT } from "../lib/browser.mjs";
export { launch, markCursorOverlay, COMMIT };
export const BASE = process.env.BASE || "http://127.0.0.1:20362/";
export const CSS = {
  NO_TOASTS: "[data-sonner-toaster]{display:none!important}",
  HIDE_MONEY: "section.glass-pop:has(.heading.tabular){visibility:hidden!important} section.glass-pop span.text-meta.tabular.text-dim:has(> .tabular){visibility:hidden!important}",
};
export function prefs(extra = {}) {
  return { theme: "dark", reduceMotion: false, endSoundOn: false, conversationWidth: 460, boardView: "dag", stage: {}, lastWorkspace: null, setupAcknowledged: true,
    tourSeen: true, introSeen: true, workshopIntroDone: true, ...extra };
}
const seedPrefs = (p) => { if (!sessionStorage.getItem("cap-init")) { localStorage.setItem("commission.prefs.v1", JSON.stringify({ state: p, version: 1 })); sessionStorage.setItem("cap-init", "1"); } };
export function open(browser, { q = "?demo=1", hash = "", base = BASE, prefsExtra = {}, ...rest } = {}) {
  return openPage(browser, { url: base + q + hash, knownCss: CSS, init: { fn: seedPrefs, arg: prefs(prefsExtra) }, ...rest });
}
export async function dismiss(page) {
  for (const n of [/^(Continue|Continue anyway|Open CommissionAI)$/i, /^Not now$/i, /^Got it$/i]) {
    const l = page.getByRole("button", { name: n }).first();
    if (await l.isVisible().catch(() => false)) { await l.click().catch(() => {}); await page.waitForTimeout(400); }
  }
}
// Steps the clock past the first-run setup screens of a fresh demo session.
export async function passSetup(page, rec, maxSteps = 300) {
  const gate = () => page.evaluate(() => /Welcome to|Checking your setup|Required to continue|Checking required setup/.test(document.body.innerText));
  for (let g = 0; g < maxSteps && (await gate()); g++) await rec.step();
}
export const hideWorkshopTab = (page) => page.evaluate(() => document.querySelectorAll("[role=tab]").forEach((e) => { if (/workshop/i.test(e.textContent || "")) e.style.visibility = "hidden"; }));
