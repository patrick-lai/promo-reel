// usage: node probe.mjs "<query+hash>" outprefix [ms list comma] [paused-clock]
import { launch, open, dismiss, CSS } from "./lib.mjs";
const [q, out, times = "0"] = process.argv.slice(2);
const b = await launch();
try {
  const { page } = await open(b, { q, clock: "paused", css: CSS.NO_TOASTS });
  page.on("pageerror", (e) => console.log("PAGEERR", String(e).slice(0, 200)));
  page.on("console", (m) => { if (m.type() === "error") console.log("CONSOLE", m.text().slice(0, 200)); });
  await page.waitForTimeout(8000); await dismiss(page);
  let t = 0;
  for (const ms of times.split(",").map(Number)) { if (ms > t) { for (let d = t; d < ms; d += 250) await page.clock.runFor(Math.min(250, ms - d)); t = ms; } await page.waitForTimeout(300); await page.screenshot({ path: `${out}-${ms}.png` }); console.log("shot", ms); }
  console.log("TEXT", (await page.locator("body").innerText()).slice(0, 1500).replace(/\n+/g, " | "));
} finally { await b.close(); }
