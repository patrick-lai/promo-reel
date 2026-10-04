// usage: node wshots.mjs NAME HOUR [seconds] [extra query] [settleMs]
import fs from "node:fs";
import { launch, open, dismiss, COMMIT } from "./lib.mjs";
import { Recorder, FOOT, flush } from "./rec.mjs";
const [name, hour, secs = "9", extra = "", settle = "15000"] = process.argv.slice(2);
const F = (s) => Math.round(s * 60);
const q = `?demo=promo&view=workshop&workshop=fast&workshopHour=${hour}${extra}`;
const b = await launch();
try {
  const { page: p } = await open(b, { q, clock: true, seed: true, time: "2026-10-01T22:40:00+10:00", prefsExtra: { workshopQuality: "hd" } });
  p.setDefaultTimeout(240000); p.on("pageerror", (e) => console.log("PAGEERR", String(e).slice(0, 200)));
  await p.waitForTimeout(Number(settle)); await dismiss(p);
  const rec = new Recorder(p); await rec.begin();
  const n = await rec.record(name, F(Number(secs)), async () => {}, { poster: F(Number(secs) / 2) });
  const hud = (await p.locator("body").innerText()).replace(/\n+/g, " | ").slice(0, 200);
  fs.appendFileSync(`${FOOT}/capture-log.jsonl`, JSON.stringify({ at: new Date().toISOString(), commit: COMMIT, shot: name, frames: n, url: q, settleMs: Number(settle), hud, notes: "standalone Workshop preview (view=workshop), locked camera, seeded Math.random, HD quality, Playwright clock 2026-10-01 22:40 AEST" }) + "\n");
} finally { await b.close(); }
await flush();
