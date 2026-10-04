// node explore.mjs '<q>' 'JS body using p, rec, snap(name), clickAt(loc), vis(loc)'
import fs from "node:fs";
import { launch, open, dismiss, CSS } from "./lib.mjs";
import { Recorder } from "./rec.mjs";
const [q, body] = process.argv.slice(2);
const b = await launch();
try {
  const t0 = Date.now();
  const { page: p } = await open(b, { q, clock: "paused", css: CSS.NO_TOASTS });
  p.setDefaultTimeout(60000); p.on("pageerror", (e) => console.log("PAGEERR", String(e).slice(0, 200)));
  await p.waitForTimeout(8000); await dismiss(p);
  const rec = new Recorder(p); await rec.begin({ paused: true });
  const snap = async (n) => { await p.screenshot({ path: `probe/${n}.png` }); console.log("snap", n, rec.ms, ((Date.now() - t0) / 1000).toFixed(0) + "s"); };
  const center = async (loc) => { const bb = await loc.boundingBox(); return [bb.x + bb.width / 2, bb.y + bb.height / 2]; };
  const clickAt = async (loc) => { const [x, y] = await center(loc); await p.mouse.click(x, y); await p.mouse.move(1919, 1079); };
  const vis = (loc) => loc.isVisible().catch(() => false);
  const text = async (loc = p.locator("body")) => (await loc.innerText()).replace(/\n+/g, " | ");
  await eval(`(async () => { ${body} })()`);
} finally { await b.close(); }
