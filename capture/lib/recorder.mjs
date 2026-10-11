// Paint-safe frame recorder: steps the page's paused clock one frame at a time and screenshots each frame, so a take is
// deterministic and frame-exact. Two rules keep half-painted frames out (see capture/README.md "Paint-safe capture"):
//   1. Never ask Chrome to rescale a screenshot. CDP's clip.scale re-rasterises the whole page at that scale for every shot,
//      and the shot races the raster: tiles of a panel's background go missing and the layer behind shows through. Shots are
//      taken at the page's own device pixel ratio (open the page with dpr = the resolution you need); ffmpeg scales to OUT_W.
//   2. A frame is kept only after STABLE_N consecutive captures are byte-identical. Frames that never settle are listed in
//      the take's meta.json (`stable.unsettled`) and the take is reported as unstable.
// `promo footage add` / `promo check` scan the encoded clip for one-frame glitches as an independent check.
//
// Environment: FOOTAGE_DIR (default ./footage), OUT_W (1920 | 3840), STABLE_N (default 3), STABLE_MAX (default 24 captures),
// SETTLE_MS (real-time wait after each clock step, default 40), TIMEOUT_SCALE (raise on a contended box).
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import { COMMIT, VIEWPORT, capInfo } from "./browser.mjs";

export const FOOT = path.resolve(process.env.FOOTAGE_DIR || "footage");
export const OUT_W = Number(process.env.OUT_W || 1920), OUT_H = Math.round(OUT_W * 9 / 16);
// Fit inside the 16:9 output (no stretch) and pad, so a non-16:9 clip is letterboxed instead of distorted.
export const VF = `scale=${OUT_W}:${OUT_H}:force_original_aspect_ratio=decrease:flags=lanczos,pad=${OUT_W}:${OUT_H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1`;
export const RECORDER = "paint-safe-1";
const STABLE_N = Number(process.env.STABLE_N || 3), STABLE_MAX = Number(process.env.STABLE_MAX || 24), SETTLE_MS = Number(process.env.SETTLE_MS || 40);
const TSCALE = Number(process.env.TIMEOUT_SCALE || 1);

const canon = (v) => (Array.isArray(v) ? `[${v.map(canon).join(",")}]` : v && typeof v === "object" ? `{${Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canon(v[k])).join(",")}}` : JSON.stringify(v ?? null));
export const paramsHash = (params) => crypto.createHash("sha256").update(canon(params)).digest("hex").slice(0, 16);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const timeout = (p, ms, what) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timeout " + what)), ms * TSCALE))]);
function run(cmd, args) { return new Promise((res, rej) => { const p = spawn(cmd, args, { stdio: "inherit" }); p.on("close", (c) => (c === 0 ? res() : rej(new Error(cmd + " " + c)))); }); }

// Frames on disk are reused only when meta.json's params hash matches this take; anything else is wiped first, so a stale
// frame can never leak into a new take.
export function prepareFrames(dir, params) {
  const hash = paramsHash(params); const mf = `${dir}/meta.json`;
  let old = null; try { old = JSON.parse(fs.readFileSync(mf, "utf8")); } catch (e) {}
  if (fs.existsSync(dir) && (!old || old.hash !== hash)) { console.log("frames:", old ? `params changed (${old.hash} -> ${hash})` : "no meta.json", "-> wiping", dir); fs.rmSync(dir, { recursive: true, force: true }); old = null; }
  fs.mkdirSync(dir, { recursive: true });
  if (!old) fs.writeFileSync(mf, JSON.stringify({ hash, params, createdAt: new Date().toISOString() }, null, 1) + "\n");
  return hash;
}

// Seek every CSS/WAAPI animation to the virtual clock (Playwright's clock does not drive them). Finite animations past
// their end are finished so their promises resolve.
const SEEK = `(() => { const T = window.__capT || 0; for (const a of document.getAnimations()) { try {
  if (!a.__cap) a.__cap = { start: T, base: Number(a.currentTime) || 0 };
  const target = a.__cap.base + (T - a.__cap.start);
  const end = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming().endTime : Infinity;
  if (Number.isFinite(end) && target >= end) { if (a.playState !== "finished") a.finish(); continue; }
  if (a.playState !== "paused") a.pause();
  a.currentTime = target; } catch (e) {} } })()`;

export const PENDING = [];
// Encode after the browser is closed (keeps Chrome and ffmpeg from overlapping in memory).
export async function flush() { while (PENDING.length) { const [r, ...a] = PENDING.shift(); await r.encode(...a); } }

export class Recorder {
  constructor(page) { this.page = page; this.t = 0; this.crashed = false; this.clip = null; page.on("crash", () => { this.crashed = true; console.log("PAGE CRASHED"); }); }
  async begin({ paused = false } = {}) {
    const page = this.page;
    if (!paused) { for (let k = 0; ; k++) { const now = await page.evaluate(() => Date.now()); try { await page.clock.pauseAt(new Date(now + 3000 * (k + 1))); break; } catch (e) { if (k >= 5) throw e; } } }
    this.t = 0;
    await page.evaluate(`window.__capT = 0; ${SEEK}`);
  }
  get ms() { return Math.round(this.t * 1000 / 60); }
  // Jump the virtual clock forward without capturing (coarse chunks), keeping frame accounting exact (60 steps per second).
  async skip(ms) {
    const frames = Math.round(ms * 60 / 1000); const from = this.ms; this.t += frames; const to = this.ms;
    for (let done = from; done < to; ) { const n = Math.min(250, to - done); await timeout(this.page.clock.runFor(n), 180000, "runFor"); done += n; }
    await this.page.evaluate(`window.__capT = ${to}; ${SEEK}`);
  }
  async step() {
    if (this.crashed) throw new Error("page crashed");
    const prev = this.ms; this.t += 1; const next = this.ms;
    await timeout(this.page.clock.runFor(next - prev), 180000, "runFor");
    await timeout(this.page.evaluate(`window.__capT = ${next}; ${SEEK}`), 120000, "seek");
  }
  async advance(ms) { const n = Math.round(ms * 60 / 1000); for (let i = 0; i < n; i++) await this.step(); }

  // The screenshot region in css px and the scale handed to Chrome: always the page's own dpr (rule 1).
  region() {
    const { dpr } = capInfo(this.page);
    const c = this.clip || { x: 0, y: 0, width: VIEWPORT.width, height: VIEWPORT.height };
    const want = c.scale ? c.scale * OUT_W / 1920 : null;
    if (want && want > dpr + 1e-6) throw new Error(`clip.scale asks for ${want}x but the page renders at dpr ${dpr}: open the page with dpr ${want} instead `
      + "(a screenshot at another scale re-rasterises the page and catches half-painted layers)");
    return { x: c.x, y: c.y, width: c.width, height: c.height, scale: dpr };
  }
  async rawShot() {
    if (!this.cdp) this.cdp = await this.page.context().newCDPSession(this.page);
    for (let k = 0; k < 3; k++) {
      if (this.crashed) throw new Error("page crashed");
      try { const { data } = await timeout(this.cdp.send("Page.captureScreenshot", { format: "png", clip: this.region() }), 150000, "screenshot"); return Buffer.from(data, "base64"); }
      catch (e) { if (/clip.scale asks/.test(e.message)) throw e; console.log("shot retry", k, String(e.message).slice(0, 80)); await sleep(2000); }
    }
    throw new Error("screenshot failed");
  }
  // Rule 2: capture until STABLE_N consecutive captures are byte-identical. {png, captures, settled}
  async shot() {
    await sleep(SETTLE_MS);
    let prev = null, same = 1, n = 0;
    for (; n < STABLE_MAX; n++) {
      const png = await this.rawShot();
      if (prev && Buffer.compare(prev, png) === 0) { if (++same >= STABLE_N) return { png, captures: n + 1, settled: true }; }
      else same = 1;
      prev = png;
      if (n >= STABLE_N - 1) await sleep(Math.min(400, 40 * (n + 1)));     // back off while the compositor catches up
    }
    return { png: prev, captures: n, settled: false };
  }

  params(name, frames, extra = {}) {
    const info = capInfo(this.page);
    return { name, frames, startFrame: this.t, url: this.page.url(), commit: COMMIT, viewport: info.viewport, dpr: info.dpr, clip: this.clip ? this.region() : null,
      css: info.cssFlags, cssSha: crypto.createHash("sha256").update(info.css || "").digest("hex").slice(0, 12), cursorHidden: info.cursorHidden,
      cursorOverlay: info.cursorOverlay, outW: OUT_W, recorder: RECORDER, stableN: STABLE_N, ...extra };
  }
  frameDir(name, frames, extra = {}) { const dir = `${FOOT}/.frames/${name}`; prepareFrames(dir, this.params(name, frames, extra)); return dir; }

  // Records `frames` frames, `every` 1/60 s clock steps apart (every: 2 = 30 fps). onFrame(i) runs actions before frame i
  // (return "stop" to end early). Frames already on disk from a crashed attempt of the SAME take are not re-shot, but the
  // clock is still stepped through them, so the replay is identical.
  async record(name, frames, onFrame = async () => {}, { poster = Math.floor(frames / 2), startFn = null, every = 1 } = {}) {
    const dir = this.frameDir(name, frames, every > 1 ? { every } : {});
    const t0 = Date.now(); const stats = { frames: 0, retried: 0, captures: 0, unsettled: [] };
    for (let i = 0; i < frames; i++) {
      const r = await onFrame(i);
      for (let k = 0; k < every; k++) await this.step();
      const file = `${dir}/${String(i).padStart(5, "0")}.png`;
      if (!(fs.existsSync(file) && fs.statSync(file).size > 1000)) {
        const { png, captures, settled } = await this.shot();
        stats.frames++; stats.captures += captures; if (captures > STABLE_N) stats.retried++; if (!settled) stats.unsettled.push(i);
        fs.writeFileSync(file + ".tmp", png); fs.renameSync(file + ".tmp", file);
      }
      if (i % 60 === 0) console.log(name, `frame ${i}/${frames}`, `${((Date.now() - t0) / 1000).toFixed(0)}s`, `retried ${stats.retried}`, `unsettled ${stats.unsettled.length}`);
      if (r === "stop") { frames = i + 1; break; }
    }
    if (stats.unsettled.length) console.warn(`WARN ${name}: ${stats.unsettled.length} frames never gave ${STABLE_N} identical captures (frames ${stats.unsettled.slice(0, 12).join(", ")}); `
      + "check them before using the take, or re-run with a larger STABLE_MAX");
    const start = startFn ? Math.max(0, startFn()) : 0;
    PENDING.push([this, name, frames, poster, start, { fps: 60 / every, stable: stats }]);
    return frames - start;
  }

  async encode(name, frames, poster, start = 0, { fps = 60, stable = null } = {}) {
    const dir = `${FOOT}/.frames/${name}`;
    const posterFrame = Math.max(start, Math.min(frames - 1, start + poster));
    await run("ffmpeg", ["-v", "error", "-y", "-i", `${dir}/${String(posterFrame).padStart(5, "0")}.png`, "-vf", VF, `${FOOT}/${name}-poster.png`]);
    await run("nice", ["-n", "5", "ffmpeg", "-y", "-loglevel", "error", "-framerate", String(fps), "-start_number", String(start), "-i", `${dir}/%05d.png`, "-frames:v", String(frames - start),
      "-vf", VF, "-c:v", "libx264", "-preset", "medium", "-qp", "0", "-pix_fmt", "yuv444p", "-threads", "4", "-r", String(fps), "-movflags", "+faststart", `${FOOT}/${name}.mov`]);
    await run("nice", ["-n", "10", "ffmpeg", "-y", "-loglevel", "error", "-i", `${FOOT}/${name}.mov`, "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
      "-threads", "4", "-movflags", "+faststart", `${FOOT}/${name}-preview.mp4`]);
    let m = {}; try { m = JSON.parse(fs.readFileSync(`${dir}/meta.json`, "utf8")); } catch (e) {}
    fs.writeFileSync(`${FOOT}/${name}.meta.json`, JSON.stringify({ ...m, encodedFrames: frames - start, startNumber: start, posterFrame, fps, stable, encodedAt: new Date().toISOString() }, null, 1) + "\n");
    fs.rmSync(dir, { recursive: true, force: true });
    console.log(name, "encoded", frames - start, "frames from", start, stable ? `(retried ${stable.retried}, unsettled ${stable.unsettled.length})` : "");
  }
}
