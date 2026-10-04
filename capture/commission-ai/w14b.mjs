// 14b: in-app Workshop, full screen, Outside -> demo control "Finish 5 rooms" -> 'now a Street' notice -> Room view Street. DRY=1 for snapshots only.
import fs from "node:fs";
import { launch, open, dismiss, COMMIT } from "./lib.mjs";
import { Recorder, FOOT, flush } from "./rec.mjs";
const DRY = !!process.env.DRY;
const HOUR = process.env.HOUR || "19:30";
const F = (s) => Math.round(s * 60);
const HIDE_MONEY = "section.glass-pop:has(.heading.tabular){visibility:hidden!important} section.glass-pop span.text-meta.tabular.text-dim:has(> .tabular){visibility:hidden!important}";
const q = `?demo=promo&pause=1&workshopHour=${HOUR}`;
const b = await launch();
const jsClick = (loc) => loc.evaluate((e) => e.click());
const overlayRadio = (p, n) => p.locator("[role=toolbar][aria-label=Workshop]").last().locator("[role=radio]").filter({ hasText: n }).first();
try {
  const { page: p } = await open(b, { q, clock: true, seed: true, css: HIDE_MONEY, prefsExtra: { workshopQuality: "hd", stage: { "ws-pay": "workshop" } } });
  p.setDefaultTimeout(240000); p.on("pageerror", (e) => console.log("PAGEERR", String(e).slice(0, 200)));
  await p.waitForTimeout(9000); await dismiss(p);
  const rec = new Recorder(p); await rec.begin();
  const snap = async (n) => { fs.writeFileSync(`probe/${n}.png`, await rec.shot()); console.log("snap", n, rec.ms); };
  console.log("expand?", await p.getByRole("button", { name: "Expand workshop" }).count());
  await jsClick(p.getByRole("button", { name: "Expand workshop" }).first()); await rec.skip(3000);
  console.log("radios", await p.locator("[role=toolbar][aria-label=Workshop] [role=radio]").allInnerTexts());
  await jsClick(overlayRadio(p, "Outside")); await rec.skip(4000);
  if (DRY) await snap("d14b-outside");
  console.log("crew pill", await p.locator("[aria-label^='Crew:']").allInnerTexts().catch(() => []), await p.locator("[aria-label^='Crew:']").evaluateAll((es) => es.map((e) => e.getAttribute("aria-label"))));
  const settings = () => p.getByRole("button", { name: "Workshop settings" }).last();
  if (DRY) {
    await jsClick(settings()); await rec.skip(700); await snap("d14b-settings");
    console.log("finish btn", await p.getByRole("button", { name: /Finish 5 rooms/ }).count());
    await jsClick(p.getByRole("button", { name: /Finish 5 rooms/ }).first()); await rec.skip(100); await jsClick(settings()); await rec.skip(2500); await snap("d14b-notice");
    await jsClick(overlayRadio(p, "Street")); await rec.skip(3500); await snap("d14b-street");
    console.log("TEXT", (await p.locator("body").innerText()).replace(/\n+/g, " | ").slice(0, 800));
  } else {
    let toast = -1, earnedSeen = -1, earnedClosed = -1, toastsAfter = null;
    const CLOSE_EARNED = !!process.env.CLOSE_EARNED, STREET_AT = Number(process.env.STREET_AT || 5.5), OUT = process.env.OUT || "shot-14b";
    const earned = () => p.locator("[data-sonner-toast]").filter({ hasText: "achievements earned" }).first();
    const n = await rec.record(OUT, F(Number(process.env.SECS || 15)), async (i) => {
      if (i === F(1)) await jsClick(settings());
      if (i === F(1.7)) await jsClick(p.getByRole("button", { name: /Finish 5 rooms/ }).first());
      if (i === F(1.8) && (await p.getByRole("button", { name: /Finish 5 rooms/ }).count()) > 0) await p.keyboard.press("Escape");
      if (toast < 0 && i > F(1.7) && (await p.locator("[data-sonner-toast]").count()) > 0) { toast = i; console.log("toast at", i, await p.locator("[data-sonner-toast]").first().innerText()); }
      // retake: dismiss the 'achievements earned' toast with its real close control (mouse hover + click), so the Street notice reads clearly
      if (CLOSE_EARNED && earnedSeen < 0 && i > F(1.7) && (await earned().count()) > 0) { earnedSeen = i; console.log("earned toast at", i); }
      if (CLOSE_EARNED && earnedSeen > 0 && i === earnedSeen + 30) { const bb = await earned().boundingBox(); if (bb) await p.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2); }
      if (CLOSE_EARNED && earnedSeen > 0 && i === earnedSeen + 45) { const cb = earned().locator("[data-close-button]").first(); const bb = await cb.boundingBox(); console.log("close btn", bb, await cb.getAttribute("aria-label")); if (bb) { await p.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2); await p.mouse.down(); await p.mouse.up(); earnedClosed = i; } }
      if (CLOSE_EARNED && earnedClosed > 0 && i === earnedClosed + 20) { await p.mouse.move(1919, 700); }
      if (process.env.REEXPAND && earnedClosed > 0 && i === earnedClosed + 24) { const ex = p.getByRole("button", { name: "Expand workshop" }).first(); const bb = await ex.boundingBox().catch(() => null); console.log("re-expand", bb); if (bb) { await p.mouse.move(bb.x + bb.width / 2, bb.y + bb.height / 2); await p.mouse.down(); await p.mouse.up(); await p.mouse.move(1919, 700); } }
      if (CLOSE_EARNED && earnedClosed > 0 && i === earnedClosed + 60) { toastsAfter = await p.locator("[data-sonner-toast]").allInnerTexts(); console.log("toasts after close", JSON.stringify(toastsAfter)); }
      if (i === F(STREET_AT)) await jsClick(overlayRadio(p, "Street"));
    }, { poster: F(9) });
    fs.appendFileSync(`${FOOT}/capture-log.jsonl`, JSON.stringify({ at: new Date().toISOString(), commit: COMMIT, shot: OUT, frames: n, url: q, toastFrame: toast, earnedSeen, earnedClosed, toastsAfter, streetAt: STREET_AT, notes: "in-app Workshop full screen (stage pref ws-pay=workshop, Expand workshop), Outside; 1.0 s Workshop settings, 1.7 s Demo controls > Finish 5 rooms, 1.8 s popover closed (Escape if still open); 'now a Street' notice; 5.5 s Room view > Street. Wallet + mora hidden by capture CSS" }) + "\n");
  }
} finally { await b.close(); }
await flush();
