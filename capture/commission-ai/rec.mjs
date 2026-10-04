import fs from "node:fs";
import { spawn } from "node:child_process";
export const FOOT = "/workspace/videos/commission-ai-promo/footage/v1-1080";
// Seek every CSS/WAAPI animation to the virtual clock. Finite animations past their end are finished so promises resolve.
const SEEK = `(() => { const T = window.__capT || 0; for (const a of document.getAnimations()) { try {
  if (!a.__cap) a.__cap = { start: T, base: Number(a.currentTime) || 0 };
  const target = a.__cap.base + (T - a.__cap.start);
  const end = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming().endTime : Infinity;
  if (Number.isFinite(end) && target >= end) { if (a.playState !== "finished") a.finish(); continue; }
  if (a.playState !== "paused") a.pause();
  a.currentTime = target; } catch (e) {} } })()`;
const timeout = (p, ms, what) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error("timeout " + what)), ms))]);
function run(cmd, args) { return new Promise((res, rej) => { const p = spawn(cmd, args, { stdio: "inherit" }); p.on("close", (c) => (c === 0 ? res() : rej(new Error(cmd + " " + c)))); }); }
export const PENDING = [];
// Encode after the browser is closed (keeps Chrome and ffmpeg from overlapping in memory).
export async function flush() { while (PENDING.length) { const [r, ...a] = PENDING.shift(); await r.encode(...a); } }
export class Recorder {
  constructor(page) { this.page = page; this.t = 0; this.crashed = false; page.on("crash", () => { this.crashed = true; console.log("PAGE CRASHED"); }); }
  async begin({ paused = false } = {}) {
    const page = this.page;
    if (!paused) { for (let k = 0; ; k++) { const now = await page.evaluate(() => Date.now()); try { await page.clock.pauseAt(new Date(now + 3000 * (k + 1))); break; } catch (e) { if (k >= 5) throw e; } } }
    this.t = 0;
    await page.evaluate(`window.__capT = 0; ${SEEK}`);
  }
  // Jump the virtual clock forward without capturing (coarse chunks), keeping frame accounting exact.
  async skip(ms) {
    const frames = Math.round(ms * 60 / 1000); const from = Math.round(this.t * 1000 / 60); this.t += frames; const to = Math.round(this.t * 1000 / 60);
    for (let done = from; done < to; ) { const n = Math.min(250, to - done); await timeout(this.page.clock.runFor(n), 180000, "runFor"); done += n; }
    await this.page.evaluate(`window.__capT = ${to}; ${SEEK}`);
  }
  get ms() { return Math.round(this.t * 1000 / 60); }
  async advance(ms) { const n = Math.round(ms * 60 / 1000); for (let i = 0; i < n; i++) await this.step(); }
  async step() {
    if (this.crashed) throw new Error("page crashed");
    const prev = Math.round(this.t * 1000 / 60); this.t += 1; const next = Math.round(this.t * 1000 / 60);
    await timeout(this.page.clock.runFor(next - prev), 180000, "runFor");
    await timeout(this.page.evaluate(`window.__capT = ${next}; ${SEEK}`), 120000, "seek");
  }
  async shot() {
    if (!this.cdp) this.cdp = await this.page.context().newCDPSession(this.page);
    for (let k = 0; k < 3; k++) {
      if (this.crashed) throw new Error("page crashed");
      try { const { data } = await timeout(this.cdp.send("Page.captureScreenshot", { format: "png", optimizeForSpeed: true, clip: this.clip || { x: 0, y: 0, width: 1920, height: 1080, scale: 1 } }), 150000, "screenshot"); return Buffer.from(data, "base64"); }
      catch (e) { console.log("shot retry", k, String(e.message).slice(0, 80)); await new Promise((r) => setTimeout(r, 2000)); }
    }
    throw new Error("screenshot failed");
  }
  async clipShot(c) { c = { scale: 1, ...c };
    if (!this.cdp) this.cdp = await this.page.context().newCDPSession(this.page);
    const { data } = await timeout(this.cdp.send("Page.captureScreenshot", { format: "png", clip: c }), 150000, "clip");
    return Buffer.from(data, "base64");
  }
  // Records frames; onFrame(i) runs actions before frame i (return "stop" to end early). Frames already on disk from a crashed
  // attempt are not re-shot, but the clock is still stepped through them, so the replay is identical (deterministic).
  async record(name, frames, onFrame = async () => {}, { poster = Math.floor(frames / 2), startFn = null } = {}) {
    const dir = `${FOOT}/.frames/${name}`; fs.mkdirSync(dir, { recursive: true });
    const t0 = Date.now(); let tA = 0, tS = 0, tC = 0;
    for (let i = 0; i < frames; i++) {
      const a0 = Date.now(); const r = await onFrame(i);
      const a1 = Date.now(); await this.step();
      const a2 = Date.now();
      const file = `${dir}/${String(i).padStart(5, "0")}.png`;
      if (!(fs.existsSync(file) && fs.statSync(file).size > 1000)) { const png = await this.shot(); fs.writeFileSync(file + ".tmp", png); fs.renameSync(file + ".tmp", file); }
      tA += a1 - a0; tS += a2 - a1; tC += Date.now() - a2;
      if (i % 60 === 0) console.log(name, `frame ${i}/${frames}`, `${((Date.now() - t0) / 1000).toFixed(0)}s`, `act ${tA} step ${tS} shot ${tC}`);
      if (r === "stop") { frames = i + 1; break; }
    }
    const start = startFn ? Math.max(0, startFn()) : 0;
    PENDING.push([this, name, frames, poster, start]);
    return frames - start;
  }
  async encode(name, frames, poster, start = 0) {
    const dir = `${FOOT}/.frames/${name}`;
    const posterFrame = Math.max(start, Math.min(frames - 1, poster === 9999 ? frames - 61 : start + poster));
    fs.copyFileSync(`${dir}/${String(posterFrame).padStart(5, "0")}.png`, `${FOOT}/${name}-poster.png`);
    await run("nice", ["-n", "5", "ffmpeg", "-y", "-loglevel", "error", "-framerate", "60", "-start_number", String(start), "-i", `${dir}/%05d.png`, "-frames:v", String(frames - start), "-vf", "scale=1920:1080:flags=lanczos", "-c:v", "libx264", "-preset", "medium", "-qp", "0", "-pix_fmt", "yuv444p", "-threads", "4", "-r", "60", "-movflags", "+faststart", `${FOOT}/${name}.mov`]);
    await run("nice", ["-n", "10", "ffmpeg", "-y", "-loglevel", "error", "-i", `${FOOT}/${name}.mov`, "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-threads", "4", "-movflags", "+faststart", `${FOOT}/${name}-preview.mp4`]);
    fs.rmSync(dir, { recursive: true, force: true });
    console.log(name, "encoded", frames - start, "frames from", start);
  }
}
