// PAY-103 task drawer take (commission-teaser-45, podcast-demo): the drawer opened by a route change in the promo demo, the
// stepper running Coding > Checks > PR raised > Merged, 13 s at 30 fps. Clip: the drawer's stepper + pull request box.
// Paint-safe: rendered at dpr 4 so the 780 css px clip is captured natively at 3120 px (no rescaled screenshots), every frame
// settled (capture/lib/recorder.mjs).
//   BASE=http://127.0.0.1:20362/ COMMIT=<full app SHA> FOOTAGE_DIR=<project>/footage OUT_W=3840 node capture/commission-ai/drawer-pay103.mjs [name]
import { launch, open, dismiss, passSetup, hideWorkshopTab, CSS } from "./app.mjs";
import { Recorder, flush } from "../lib/recorder.mjs";

const NAME = process.argv[2] || "rec-drawer-pay103";
const FRAMES = Number(process.env.MAXF || 390);
const b = await launch();
try {
  const { page: p } = await open(b, { clock: "paused", q: "?demo=promo&speed=2", hash: "#/w/ws-pay", dpr: 4, css: CSS.NO_TOASTS + " " + CSS.HIDE_MONEY });
  p.setDefaultTimeout(60000);
  await p.waitForTimeout(9000); await dismiss(p);
  const rec = new Recorder(p); await rec.begin({ paused: true });
  await passSetup(p, rec);
  await rec.skip(2800);
  await p.evaluate(() => { location.hash = "#/w/ws-pay/task/PAY-103"; });
  await rec.skip(800);
  await hideWorkshopTab(p);
  rec.clip = { x: 1128, y: 12, width: 780, height: 540 };
  await rec.record(NAME, FRAMES, async (i) => { if (i % 8 === 0) await hideWorkshopTab(p); }, { every: 2, poster: 375 });
} finally { await b.close(); }
await flush();
