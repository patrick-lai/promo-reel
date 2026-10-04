// promo-reel Live2D renderer: deterministic frame-by-frame capture from headless Chromium.
//   node render.mjs job.json > frames.rgba      (raw RGBA, straight alpha, top-down rows, job.width x job.height)
// job.json: {modelDir, model3, core, width, height, fps, frames, seed, warmup, frame:{zoom,at_x,at_y} (or legacy {zoom,cy,dx}), tracks:{ParamId:{v:[..], mode:set|add}}}
// The model clock advances exactly 1/fps per frame (performance.now is virtualised in page.html); wall clock is
// never read, so the same job gives the same pixels. Progress + stats go to stderr; frames go to stdout.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const W = job.width, H = job.height;

const MIME = { ".js": "text/javascript", ".json": "application/json", ".png": "image/png", ".html": "text/html", ".moc3": "application/octet-stream" };
const roots = {
  "/lib/pixi.min.js": path.join(HERE, "node_modules/pixi.js/dist/browser/pixi.min.js"),
  "/lib/cubism4.min.js": path.join(HERE, "node_modules/pixi-live2d-display/dist/cubism4.min.js"),
  "/core/live2dcubismcore.min.js": job.core,
  "/page.html": path.join(HERE, "page.html"),
};
const server = http.createServer((req, res) => {
  const u = decodeURIComponent(new URL(req.url, "http://x").pathname);
  let file = roots[u];
  if (!file && u.startsWith("/model/")) {
    file = path.join(job.modelDir, u.slice(7));
    if (!file.startsWith(job.modelDir)) file = null;          // no path escapes
  }
  if (!file || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "content-type": MIME[path.extname(file)] || "application/octet-stream" });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const port = server.address().port;

const exe = job.chromium || process.env.PROMO_CHROMIUM || undefined;
const browser = await chromium.launch({
  executablePath: exe,
  args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--use-gl=angle", "--ignore-gpu-blocklist",
         "--disable-gpu-vsync", "--disable-background-timer-throttling", "--renderer-process-limit=1",
         "--js-flags=--max-old-space-size=1024"],
});
const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") process.stderr.write(`[page ${m.type()}] ${m.text()}\n`); });
page.on("pageerror", (e) => process.stderr.write(`[pageerror] ${e}\n`));
await page.goto(`http://127.0.0.1:${port}/page.html?seed=${job.seed || 1}`);
await page.waitForFunction(() => window.__ready === true);
const modelUrl = `/model/${job.model3}`;
const info = await page.evaluate((j) => window.L2D.init(j), { ...job, modelUrl });
process.stderr.write(`live2d: model ${info.width.toFixed(0)}x${info.height.toFixed(0)}, ${info.params} params, ${info.gl}; missing params: ${info.missing.join(",") || "none"}\n`);

const t0 = Date.now();
const out = Buffer.alloc(W * H * 4);
const readback = [];
for (let i = 0; i < job.frames; i++) {
  const { b64, rb } = await page.evaluate((k) => window.L2D.frame(k), i);
  readback.push(rb);
  const px = Buffer.from(b64, "base64");
  // flip rows (GL is bottom-up) and un-premultiply alpha
  for (let y = 0; y < H; y++) {
    const src = (H - 1 - y) * W * 4, dst = y * W * 4;
    for (let x = 0; x < W * 4; x += 4) {
      const a = px[src + x + 3];
      if (a === 0) { out[dst + x] = out[dst + x + 1] = out[dst + x + 2] = out[dst + x + 3] = 0; continue; }
      if (a === 255) { out[dst + x] = px[src + x]; out[dst + x + 1] = px[src + x + 1]; out[dst + x + 2] = px[src + x + 2]; out[dst + x + 3] = 255; continue; }
      const k = 255 / a;
      out[dst + x] = Math.min(255, Math.round(px[src + x] * k));
      out[dst + x + 1] = Math.min(255, Math.round(px[src + x + 1] * k));
      out[dst + x + 2] = Math.min(255, Math.round(px[src + x + 2] * k));
      out[dst + x + 3] = a;
    }
  }
  if (!process.stdout.write(out)) await new Promise((r) => process.stdout.once("drain", r));
  if (i % 30 === 29) process.stderr.write(`live2d: frame ${i + 1}/${job.frames} (${((Date.now() - t0) / (i + 1)).toFixed(0)} ms/frame)\n`);
}
const secs = (Date.now() - t0) / 1000;
process.stderr.write(`live2d: done ${job.frames} frames in ${secs.toFixed(1)} s (${(secs / (job.frames / job.fps)).toFixed(2)} s per output second)\n`);
if (job.readbackPath) fs.writeFileSync(job.readbackPath, JSON.stringify({ frames: readback, secs, info }));
await browser.close();
server.close();
