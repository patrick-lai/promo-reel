import fs from "node:fs";
import { launch, open, dismiss } from "./lib.mjs";
import { Recorder } from "./rec.mjs";
const [q, out, settle = "12000", skips = "0,4000", quality = "hd"] = process.argv.slice(2);
const b = await launch();
try {
  const t0 = Date.now();
  const { page: p } = await open(b, { q, clock: true, seed: true, time: "2026-10-01T22:40:00+10:00", prefsExtra: { workshopQuality: quality } });
  p.setDefaultTimeout(180000);
  p.on("pageerror", (e) => console.log("PAGEERR", String(e).slice(0, 200)));
  await p.waitForTimeout(Number(settle)); await dismiss(p);
  const rec = new Recorder(p); await rec.begin();
  let el = 0;
  for (const s of skips.split(",").map(Number)) { if (s > el) await rec.skip(s - el); el = s; await rec.step(); fs.writeFileSync(`probe/${out}-${s}.png`, await rec.shot()); console.log("snap", s, ((Date.now() - t0) / 1000).toFixed(0)); }
  console.log("TEXT", (await p.locator("body").innerText()).replace(/\n+/g, " | ").slice(0, 600));
} finally { await b.close(); }
