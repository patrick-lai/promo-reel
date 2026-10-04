import fs from "node:fs";
import { launch, open, dismiss, COMMIT } from "./lib.mjs";
import { Recorder, FOOT, flush } from "./rec.mjs";
const SHOT = process.argv[2];
const DRY = !!process.env.DRY;
const F = (s) => Math.round(s * 60);
const NO_TOASTS = "[data-sonner-toaster]{display:none!important}";
const log = (o) => fs.appendFileSync(`${FOOT}/capture-log.jsonl`, JSON.stringify({ at: new Date().toISOString(), commit: COMMIT, ...o }) + "\n");
const b = await launch();
async function start(opts = {}) {
  const r = await open(b, { clock: "paused", q: "?demo=promo", css: NO_TOASTS, ...opts });
  r.page.setDefaultTimeout(240000); r.page.on("pageerror", (e) => console.log("PAGEERR", String(e).slice(0, 200)));
  await r.page.waitForTimeout(9000); await dismiss(r.page);
  const rec = new Recorder(r.page); await rec.begin({ paused: opts.clock !== true });
  return { p: r.page, rec };
}
const center = async (loc) => { const bb = await loc.boundingBox(); if (!bb) throw new Error("no box"); return [bb.x + bb.width / 2, bb.y + bb.height / 2]; };
const clickAt = async (p, loc) => { const [x, y] = await center(loc); await p.mouse.click(x, y); await p.mouse.move(1919, 1079); };
const snap = async (p, rec, n) => { await p.screenshot({ path: `probe/${n}.png` }); console.log("snap", n, rec.ms); };
// capture-only cursor overlay (headless Chrome draws no OS cursor); follows the real pointer
const CURSOR = () => { const c = document.createElement("div"); c.id = "cap-cursor"; c.style.cssText = "position:fixed;left:0;top:0;width:34px;height:34px;z-index:2147483647;pointer-events:none;transform:translate(-100px,-100px)"; c.innerHTML = '<svg width="34" height="34" viewBox="0 0 28 28"><path d="M5 3 L5 22 L10 17.5 L13.5 25 L16.8 23.6 L13.3 16.2 L20 16.2 Z" fill="#fff" stroke="#000" stroke-width="1.4" stroke-linejoin="round"/></svg>'; document.body.appendChild(c); addEventListener("pointermove", (e) => { c.style.transform = `translate(${e.clientX - 6}px, ${e.clientY - 4}px)`; }, true); };
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
async function zoomOn(p, rec, loc, steps, target) {
  let [x, y] = await center(loc); await p.mouse.move(x, y);
  for (let k = 0; k < steps; k++) { await p.keyboard.down("Control"); await p.mouse.wheel(0, -25); await p.keyboard.up("Control"); await rec.skip(200); }
  [x, y] = await center(loc); await p.mouse.move(target[0], target[1]); await p.mouse.wheel(x - target[0], y - target[1]); await rec.skip(400);
  await p.mouse.move(1919, 1079); await rec.skip(200);
}
async function fullBoard(p, rec, showDone = true) {
  await clickAt(p, p.getByRole("button", { name: "Full window" }).first()); await rec.skip(800);
  const done = p.getByRole("button", { name: /^Show \d+ done/ }).first();
  if (showDone && await done.isVisible().catch(() => false)) { await clickAt(p, done); await rec.skip(600); }
  await clickAt(p, p.getByRole("button", { name: "Fit to screen" }).first()); await rec.skip(1200);
}
const node = (p, key) => p.locator(`[data-task-node='${key}']`).first();
const shots = {
  // 10: PAY-106 flips live to Needs you (21.25 s), cursor hovers its card, real click on the card's Allow once (~23.8 s); scenario resolves at 24.25 s
  async "10"() { return shot10(false); },
  async "10b"() { return shot10(true); },
};
async function shot10(hi) {
  {
    const { p, rec } = await start(hi ? { dpr: 2 } : {});
    await rec.skip(19000);
    await zoomOn(p, rec, node(p, "PAY-106"), 2, [1200, 600]);
    await p.evaluate(CURSOR);
    const s0 = rec.ms;
    if (DRY) { await rec.skip(21700 - rec.ms); await snap(p, rec, "d10"); }
    const allow = () => node(p, "PAY-106").getByRole("button", { name: /^Allow once/ }).first();
    let from = [1560, 930], to = null, clickAt_ = -1;
    if (hi) rec.clip = { x: 290, y: 88, width: 1280, height: 720, scale: 1.5 };
    const name = hi ? "shot-10-dpr2" : "shot-10";
    const n = await rec.record(name, F(26.2) - F(s0 / 1000), async (i) => {
      const t = rec.ms;
      if (t >= 22300 && !to) { const bb = await node(p, "PAY-106").boundingBox(); to = [bb.x + bb.width * 0.55, bb.y + bb.height * 0.62]; to.f0 = i; await p.mouse.move(...from); }
      if (to && !to.a2 && i > to.f0) { const k = Math.min(1, (i - to.f0) / F(1.0)); await p.mouse.move(from[0] + (to[0] - from[0]) * ease(k), from[1] + (to[1] - from[1]) * ease(k)); if (k >= 1) to.a2 = i; }
      if (to && to.a2 && !to.b2 && i >= to.a2 + F(0.25)) { const [x, y] = await center(allow()); to.b2 = i; to.bf = [x, y]; to.from2 = [from[0] + (to[0] - from[0]), from[1] + (to[1] - from[1])]; }
      if (to && to.b2 && clickAt_ < 0) { const k = Math.min(1, (i - to.b2) / F(0.4)); const x = to.from2[0] + (to.bf[0] - to.from2[0]) * ease(k), y = to.from2[1] + (to.bf[1] - to.from2[1]) * ease(k); await p.mouse.move(x, y); if (k >= 1 && t >= 23700) { await p.mouse.down(); await p.mouse.up(); clickAt_ = t; console.log("clicked at", t); } }
    }, { poster: F(3.6) });
    log({ shot: name, frames: n, url: "?demo=promo", startMs: s0, clickMs: clickAt_, framing: hi ? "DPR2, clip x290 y88 1280x720 CSS (1.5x)" : "DPR1 full", notes: "Board zoomed 2 in-app steps on PAY-106. PAY-106 Running -> Needs you live at 21.25 s (bell, rail 'Needs you', '2 need you' header pill, Commander Needs you card). Capture-overlay cursor hovers the card, real click on the card's 'Allow once'; card resolves, scenario timeout at 24.25 s returns PAY-106 to Running." });
  }
}
Object.assign(shots, {
  // 8 (+9): PAY-104 (Codex) drawer, right half framed at 2x (960x540 CSS @ DPR2). Coding -> Checks 13.1 -> Pushed 16.0 -> PR raised 18.9; Verifying card during checks
  async "08"() {
    const { p, rec } = await start({ dpr: 2 });
    await rec.skip(9000);
    await clickAt(p, p.locator("[aria-label^='PAY-104 ']:not([data-session-navigation])").first());
    await rec.skip(11100 - rec.ms);
    const C8 = process.env.CLIP ? JSON.parse(process.env.CLIP) : { x: 960, y: 0, width: 960, height: 540 }; const OUT8 = process.env.OUT || "shot-08";
    rec.clip = { ...C8, scale: 1920 / C8.width };
    const s = rec.ms; if (DRY) { await snap(p, rec, "d08"); return; }
    const agent = (await p.locator("body").innerText()).match(/(Claude Code|Codex|Cursor|Claude)\s*\n?\s*·?\s*Board run/);
    const n = await rec.record(OUT8, F(20.4) - F(s / 1000), async () => {}, { poster: F(3.5) });
    rec.clip = null; fs.writeFileSync(`${FOOT}/${OUT8}-still-fullframe.png`, await rec.shot());
    log({ shot: OUT8, frames: n, url: "?demo=promo", startMs: s, framing: `clip ${JSON.stringify(C8)} CSS @ DPR2 (${(1920 / C8.width).toFixed(2)}x)`, agentText: agent && agent[0], scenario: "PAY-104 drawer opened by clicking its node at 9.0 s; Checks 13.1 s (Verifying card), Pushed 16.0 s, PR raised #432 18.9 s" });
  },
  // 12: no-blocker review moment on the promo PR: PAY-104 drawer -> Review thread (reviewer agent approves #432)
  async "12"() {
    const { p, rec } = await start();
    await rec.skip(24000);
    await clickAt(p, p.locator("[aria-label^='PAY-104 ']:not([data-session-navigation])").first());
    await rec.skip(25200 - rec.ms);
    if (DRY) { await rec.skip(1500); await snap(p, rec, "d12a"); const l = p.getByRole("button", { name: /Review thread/ }).first(); await clickAt(p, l); await rec.skip(1500); await snap(p, rec, "d12b"); return; }
    const s = rec.ms; let clicked = -1;
    const n = await rec.record("shot-12", F(31.5) - F(s / 1000), async (i) => {
      if (clicked < 0 && rec.ms >= 26700) { const l = p.getByRole("button", { name: /Review thread/ }).first(); if (await l.isVisible().catch(() => false)) { await clickAt(p, l); clicked = rec.ms; } }
    }, { poster: 9999 });
    log({ shot: "shot-12", frames: n, url: "?demo=promo", startMs: s, clickMs: clicked, scenario: "PAY-104 drawer during the review beat; 'Review thread' clicked -> reviewer agent's 'Approved' turn + 'Review approved' card for PR #432" });
  },
  // 4: plan graph, board area framed ~1.8x (DPR2 clip)
  async "04"() {
    const { p, rec } = await start({ dpr: 2 });
    rec.clip = { x: 800, y: 300, width: 1060, height: 596, scale: 1920 / 1060 };
    if (DRY) { await rec.skip(6500); await snap(p, rec, "d04"); return; }
    const n = await rec.record("shot-04", F(8.4), async () => {}, { poster: 9999 });
    log({ shot: "shot-04", frames: n, url: "?demo=promo", framing: "clip x800 y300 1060x596 CSS @ DPR2 (1.81x)", scenario: "S 0-8.4 s: empty Checkout Revamp board, plan streams, 8 tickets pop into Wave 1/2/3 2.8-5.8 s with edges, run starts 6.2 s, PAY-103 claims 6.7 s" });
  },
  // 5: rail + Commander, framed 1.92x, cost figure out of frame
  async "05"() {
    const { p, rec } = await start({ dpr: 2 });
    await rec.skip(5600);
    const C5 = process.env.CLIP ? JSON.parse(process.env.CLIP) : { x: 0, y: 85, width: 1000, height: 562.5 }; const OUT5 = process.env.OUT || "shot-05"; rec.clip = { ...C5, scale: 1920 / C5.width };
    if (DRY) { await rec.skip(3500); await snap(p, rec, "d05"); return; }
    const n = await rec.record(OUT5, F(12), async () => {}, { poster: F(4.5) });
    log({ shot: OUT5, frames: n, url: "?demo=promo", startMs: 5600, framing: `clip ${JSON.stringify(C5)} CSS @ DPR2 (${(1920 / C5.width).toFixed(2)}x)`, scenario: "S 5.6-17.6 s: rail PAY-103 (Claude Code) 6.7 s, PAY-104 (Codex) 7.7 s, PAY-106 (Cursor) 8.7 s go to Coding; Checks from 12.6 s" });
  },
  // 11 + 16a: full-window board, Show done, Fit; 2x framing on header counts + Landed column; PAY-108 lands 65.5, PAY-110 67.5, run complete 72.3
  async "11"() {
    const { p, rec } = await start({ dpr: 2 });
    await rec.skip(62000);
    await fullBoard(p, rec);
    await p.mouse.move(1919, 1079);
    const s = rec.ms;
    if (DRY) { await snap(p, rec, "d11a"); await rec.skip(8000); await snap(p, rec, "d11b"); return; }
    rec.clip = { x: 10, y: 45, width: 960, height: 540, scale: 2 };
    const counts = [];
    const n = await rec.record("shot-11", F(74.5) - F(s / 1000), async (i) => { if (i % 30 === 0) counts.push([rec.ms, (await p.locator("body").innerText()).match(/\d+ in this run[^\n]*|\d+\/8 landed|All done[^\n]*/g)]); }, { poster: 9999 });
    const m = await rec.record("shot-16a", F(6), async () => {}, { poster: F(3) });
    rec.clip = null; fs.writeFileSync(`${FOOT}/shot-11-still-fullframe.png`, await rec.shot());
    const KEYS = ["PAY-103", "PAY-104", "PAY-105", "PAY-106", "PAY-107", "PAY-108", "PAY-109", "PAY-110"];
    const fit169 = (bbs, m = 24) => { let x0 = Math.min(...bbs.map((b) => b.x)) - m, y0 = Math.min(...bbs.map((b) => b.y)) - m, x1 = Math.max(...bbs.map((b) => b.x + b.width)) + m, y1 = Math.max(...bbs.map((b) => b.y + b.height)) + m; let w = x1 - x0, h = y1 - y0; if (w / h < 16 / 9) { const nw = h * 16 / 9; x0 -= (nw - w) / 2; w = nw; } else { const nh = w * 9 / 16; y0 -= (nh - h) / 2; h = nh; } x0 = Math.max(0, Math.min(1920 - w, x0)); y0 = Math.max(0, Math.min(1080 - h, y0)); return { x: x0, y: y0, width: w, height: h, scale: 1920 / w }; };
    // take B: all 8 Landed cards in frame (graph)
    const bbs = []; for (const k of KEYS) { const bb = await node(p, k).boundingBox(); if (bb) bbs.push(bb); }
    const cardText = await p.locator("[data-task-node]").evaluateAll((es) => es.map((e) => e.innerText.replace(/\n+/g, " ").slice(0, 80)));
    rec.clip = fit169(bbs);
    const mb = await rec.record("shot-11-all8", F(5), async () => {}, { poster: F(2.5) });
    log({ shot: "shot-11-all8", frames: mb, url: "?demo=promo", framing: `DPR2, Full window, Show done, Fit; clip ${JSON.stringify(rec.clip)} (union of the 8 cards, 16:9)`, cards: bbs.length, cardText });
    // take C: List view of the same board
    rec.clip = null;
    const list = p.getByRole("button", { name: /^List$/ }).or(p.getByRole("radio", { name: /^List$/ })).or(p.getByRole("tab", { name: /^List$/ })).first();
    if (await list.isVisible().catch(() => false)) {
      await clickAt(p, list); await rec.skip(1500);
      fs.writeFileSync(`${FOOT}/shot-11-still-list-fullframe.png`, await rec.shot());
      const rows = []; for (const k of KEYS) { const r = p.getByText(k, { exact: true }).first(); const bb = await r.boundingBox().catch(() => null); if (bb) rows.push(bb); }
      const rowBoxes = await p.evaluate((keys) => keys.map((k) => { const el = [...document.querySelectorAll("*")].find((e) => e.childElementCount === 0 && e.textContent.trim() === k); if (!el) return null; let r = el; for (let i = 0; i < 6 && r.parentElement; i++) { r = r.parentElement; if (r.getBoundingClientRect().width > 500) break; } const b = r.getBoundingClientRect(); return { x: b.x, y: b.y, width: b.width, height: b.height, text: r.innerText.replace(/\n+/g, " ").slice(0, 120) }; }).filter(Boolean), KEYS);
      if (rowBoxes.length) {
        rec.clip = fit169(rowBoxes, 20);
        const mc = await rec.record("shot-11-list", F(5), async () => {}, { poster: F(2.5) });
        log({ shot: "shot-11-list", frames: mc, url: "?demo=promo", framing: `DPR2, Full window, List view; clip ${JSON.stringify(rec.clip)}`, rows: rowBoxes.map((r) => r.text) });
      }
    } else console.log("no List toggle");
    const text = (await p.locator("body").innerText()).replace(/\n+/g, " | ").slice(0, 400);
    log({ shot: "shot-11", frames: n, url: "?demo=promo", startMs: s, framing: "clip x10 y45 960x540 CSS @ DPR2 (2x)", counts, endText: text });
    log({ shot: "shot-16a", frames: m, url: "?demo=promo", startMs: s + n * 1000 / 60, framing: "same as shot-11", scenario: "run complete, all 8 in Landed; locked hold" });
  },
  // 11b: run-complete end state only (holds), ordered by priority: all-8 board, header counts, List view
  async "11b"() {
    const { p, rec } = await start({ dpr: 2 });
    await rec.skip(72600);
    await fullBoard(p, rec);
    await p.mouse.move(1919, 1079); await rec.skip(1000);
    const KEYS = ["PAY-103", "PAY-104", "PAY-105", "PAY-106", "PAY-107", "PAY-108", "PAY-109", "PAY-110"];
    const fit169 = (bbs, m = 24) => { let x0 = Math.min(...bbs.map((b) => b.x)) - m, y0 = Math.min(...bbs.map((b) => b.y)) - m, x1 = Math.max(...bbs.map((b) => b.x + b.width)) + m, y1 = Math.max(...bbs.map((b) => b.y + b.height)) + m; let w = x1 - x0, h = y1 - y0; if (w / h < 16 / 9) { const nw = h * 16 / 9; x0 -= (nw - w) / 2; w = nw; } else { const nh = w * 9 / 16; y0 -= (nh - h) / 2; h = nh; } w = Math.min(w, 1920); h = w * 9 / 16; x0 = Math.max(0, Math.min(1920 - w, x0)); y0 = Math.max(0, Math.min(1080 - h, y0)); return { x: x0, y: y0, width: w, height: h, scale: 1920 / w }; };
    const bbs = []; for (const k of KEYS) { const bb = await node(p, k).boundingBox(); if (bb) bbs.push(bb); }
    const cards = await p.locator("[data-task-node]").evaluateAll((es) => es.map((e) => ({ key: e.getAttribute("data-task-node"), text: e.innerText.replace(/\n+/g, " ").slice(0, 120), logos: [...e.querySelectorAll("img,svg,[aria-label],[title]")].map((x) => x.getAttribute("alt") || x.getAttribute("aria-label") || x.getAttribute("title")).filter(Boolean), b: (({ x, y, width, height }) => ({ x, y, width, height }))(e.getBoundingClientRect()) })));
    const header = ((await p.locator("body").innerText()).match(/All done[^\n]*|\d+ in this run[^\n]*|\d+ landed[^\n]*/g) || []);
    console.log("CARDS", JSON.stringify(cards)); console.log("HEADER", JSON.stringify(header));
    fs.writeFileSync(`${FOOT}/shot-11-still-fullframe.png`, await rec.shot());
    rec.clip = fit169(bbs);
    const ma = await rec.record("shot-11-all8", F(5), async () => {}, { poster: F(2.5) });
    log({ shot: "shot-11-all8", frames: ma, url: "?demo=promo", startMs: 72600, framing: `DPR2, Full window, Show done, Fit; clip ${JSON.stringify(rec.clip)} (union of the 8 cards, 16:9)`, cards, header });
    rec.clip = { x: 10, y: 45, width: 960, height: 540, scale: 2 };
    const mh = await rec.record("shot-11", F(3), async () => {}, { poster: F(1.5) });
    log({ shot: "shot-11", frames: mh, url: "?demo=promo", framing: "DPR2, Full window, Show done, Fit; clip x10 y45 960x540 CSS (2x) on header counts + Landed column", header });
    rec.clip = null;
    const list = p.getByRole("button", { name: /^List$/ }).or(p.getByRole("radio", { name: /^List$/ })).or(p.getByRole("tab", { name: /^List$/ })).first();
    if (await list.isVisible().catch(() => false)) {
      await clickAt(p, list); await p.mouse.move(1919, 1079); await rec.skip(1500);
      fs.writeFileSync(`${FOOT}/shot-11-still-list-fullframe.png`, await rec.shot());
      const rowBoxes = await p.evaluate((keys) => keys.map((k) => { const el = [...document.querySelectorAll("*")].find((e) => e.childElementCount === 0 && e.textContent.trim() === k); if (!el) return null; let r = el; for (let i = 0; i < 6 && r.parentElement; i++) { r = r.parentElement; if (r.getBoundingClientRect().width > 500) break; } const b = r.getBoundingClientRect(); return { x: b.x, y: b.y, width: b.width, height: b.height, text: r.innerText.replace(/\n+/g, " ").slice(0, 160), logos: [...r.querySelectorAll("img,svg,[aria-label],[title]")].map((x) => x.getAttribute("alt") || x.getAttribute("aria-label") || x.getAttribute("title")).filter(Boolean) }; }).filter(Boolean), KEYS);
      console.log("ROWS", JSON.stringify(rowBoxes));
      if (rowBoxes.length) { rec.clip = fit169(rowBoxes, 20); const mc = await rec.record("shot-11-list", F(5), async () => {}, { poster: F(2.5) }); log({ shot: "shot-11-list", frames: mc, url: "?demo=promo", framing: `DPR2, Full window, List view; clip ${JSON.stringify(rec.clip)}`, rows: rowBoxes }); }
    } else console.log("no List toggle");
  },
  // 11c: run complete; real wheel-pan of the board so the Landed column sits right next to the header counts; DPR2 ~900 px clip
  async "11c"() {
    const { p, rec } = await start({ dpr: 2 });
    await rec.skip(72600);
    await fullBoard(p, rec);
    const KEYS = ["PAY-103", "PAY-104", "PAY-105", "PAY-106", "PAY-107", "PAY-108", "PAY-109", "PAY-110"];
    const TX = Number(process.env.TX || 640), TY = Number(process.env.TY || 108);
    const col = async () => { const h = await p.getByText("Landed", { exact: true }).first().boundingBox(); const c = await node(p, "PAY-103").boundingBox(); return { x: Math.min(h.x, c.x), y: h.y }; };
    const ZT = Number(process.env.ZOOMTO || 0);
    const zoomNow = async () => parseInt(await p.getByText(/^\d+%$/).first().innerText({ timeout: 3000 }).catch(() => "0"));
    for (let k = 0; ZT && k < 8; k++) { const z = await zoomNow(); console.log("zoom", z); if (z >= ZT) break; const c = await node(p, "PAY-103").boundingBox(); await p.mouse.move(c.x + c.width / 2, c.y + 10); await p.keyboard.down("Control"); await p.mouse.wheel(0, -60); await p.keyboard.up("Control"); await rec.skip(250); }
    for (let k = 0; k < 8; k++) { const c = await col(); const dx = c.x - TX, dy = c.y - TY; console.log("col", c); if (Math.abs(dx) < 6 && Math.abs(dy) < 6) break; await p.mouse.move(1200, 600); await p.mouse.wheel(dx * 2, dy * 2); await rec.skip(300); }
    await p.mouse.move(1919, 1079); await rec.skip(800);
    const C = process.env.CLIP ? JSON.parse(process.env.CLIP) : { x: 10, y: 40, width: 900, height: 506.25 };
    const hdr = await p.getByText(/^\d+ in this run/).first().boundingBox().catch(() => null);
    const vis = []; for (const k of KEYS) { const b = await node(p, k).boundingBox(); if (b && b.y + b.height <= C.y + C.height && b.x + b.width <= C.x + C.width) vis.push(k); }
    console.log("HDR", JSON.stringify(hdr), "VISIBLE", JSON.stringify(vis), "col", JSON.stringify(await col()));
    if (DRY) { fs.writeFileSync("probe/d11c.png", await rec.shot()); return; }
    rec.clip = { ...C, scale: 1920 / C.width };
    const OUT11 = process.env.OUT || "shot-11-dpr2";
    const n = await rec.record(OUT11, F(5), async () => {}, { poster: F(2.5) });
    log({ shot: OUT11, frames: n, url: "?demo=promo", startMs: 72600, framing: `DPR2, Full window, Show done, Fit, board wheel-panned so the Landed column sits beside the header; clip ${JSON.stringify(C)} (${(1920 / C.width).toFixed(3)}x)`, header: hdr, fullyVisible: vis });
  },
  // 04p: ?demo=promo plan of 8 (PAY-103..110) as a DAG, DPR2 clip fitted to the 8 cards + wave headings, from 5.9 s (all 8 placed) for 6 s (run starts 6.2 s)
  async "04p"() {
    const { p, rec } = await start({ dpr: 2 });
    await rec.skip(Number(process.env.T0 || 5900));
    const KEYS = ["PAY-103", "PAY-104", "PAY-105", "PAY-106", "PAY-107", "PAY-108", "PAY-109", "PAY-110"];
    const bbs = []; for (const k of KEYS) { const b = await node(p, k).boundingBox(); if (b) bbs.push(b); }
    if (process.env.HEADS !== "0") for (const h of ["Wave 1", "Wave 2", "Wave 3"]) { const b = await p.getByText(h, { exact: true }).first().boundingBox().catch(() => null); if (b) bbs.push(b); }
    const m = Number(process.env.PAD || 20); const OUT4 = process.env.OUT || "shot-04-dpr2-promo";
    let x0 = Math.min(...bbs.map((b) => b.x)) - m, y0 = Math.min(...bbs.map((b) => b.y)) - m, x1 = Math.max(...bbs.map((b) => b.x + b.width)) + m, y1 = Math.max(...bbs.map((b) => b.y + b.height)) + m;
    let w = x1 - x0, h = y1 - y0; if (w / h < 16 / 9) { const nw = h * 16 / 9; x0 -= (nw - w) / 2; w = nw; } else { const nh = w * 9 / 16; y0 -= (nh - h) / 2; h = nh; }
    const C = { x: Math.round(x0), y: Math.round(y0), width: Math.round(w), height: Math.round(w * 9 / 16) };
    const idPx = await node(p, "PAY-103").evaluate((e) => { const t = [...e.querySelectorAll("*")].find((x) => x.childElementCount === 0 && /^PAY-103$/.test(x.textContent.trim())); if (!t) return null; const b = t.getBoundingClientRect(); return [parseFloat(getComputedStyle(t).fontSize), b.height]; }).catch(() => null);
    const cards = await p.locator("[data-task-node]").evaluateAll((es) => es.map((e) => e.innerText.replace(/\n+/g, " ").slice(0, 90)));
    console.log("CLIP04", JSON.stringify(C), "scale", (1920 / C.width).toFixed(3), "id", idPx, "cards", JSON.stringify(cards));
    if (DRY) { fs.writeFileSync("probe/d04p.png", await rec.shot()); return; }
    if (process.env.FREEZE) { // one real DPR2 capture held as a still (scenario clock not advanced), encoded by enc.sh after the browser closes
      const png = await rec.clipShot({ ...C, scale: 1920 / C.width }); const dir = `${FOOT}/.frames/${OUT4}`; fs.mkdirSync(dir, { recursive: true });
      const N = F(Number(process.env.FREEZE)); for (let i = 0; i < N; i++) fs.writeFileSync(`${dir}/${String(i).padStart(5, "0")}.png`, png);
      log({ shot: OUT4, frames: N, url: "?demo=promo", startMs: rec.ms, freeze: true, framing: `DPR2, clip ${JSON.stringify(C)} (${(1920 / C.width).toFixed(3)}x) fitted to the 8 cards${process.env.HEADS === "0" ? "" : " + Wave headings"}; still hold`, idFont: idPx, cards });
      console.log("FREEZE frames", N, "-> run enc.sh", OUT4); return;
    }
    rec.clip = { ...C, scale: 1920 / C.width };
    const n = await rec.record(OUT4, F(6), async () => {}, { poster: F(1) });
    log({ shot: OUT4, frames: n, url: "?demo=promo", startMs: Number(process.env.T0 || 5900), framing: `DPR2, clip ${JSON.stringify(C)} (${(1920 / C.width).toFixed(3)}x) fitted to the 8 cards + Wave headings`, idFont: idPx, cards });
  },
  // 15-pr: PAY-110 drawer framed on status + PR card (card ~60% of width): Checks 62.3, Pushed 63.1, PR raised 63.9 (#438), Merged 67.5
  async "15pr"() {
    const { p, rec } = await start({ dpr: 2 });
    await rec.skip(59000);
    await clickAt(p, p.locator("[aria-label^='PAY-110 ']:not([data-session-navigation])").first()); await rec.skip(2000);
    const s = rec.ms;
    const CP = process.env.CLIP ? JSON.parse(process.env.CLIP) : { x: 720, y: 122, width: 1200, height: 675 }; const OUTP = process.env.OUT || "shot-15-prcard";
    rec.clip = { ...CP, scale: 1920 / CP.width };
    if (DRY) { await rec.skip(7000); await snap(p, rec, "d15"); return; }
    const n = await rec.record(OUTP, F(70.5) - F(s / 1000), async () => {}, { poster: 9999 });
    if (process.env.OUT) {
      const meas = await p.evaluate(() => { const find = (re) => { const el = [...document.querySelectorAll("body *")].find((e) => e.childElementCount === 0 && re.test(e.textContent.trim())); if (!el) return null; const b = el.getBoundingClientRect(); const cs = getComputedStyle(el); return { text: el.textContent.trim().slice(0, 60), x: b.x, y: b.y, width: b.width, height: b.height, fontSize: cs.fontSize, lineHeight: cs.lineHeight }; };
        const badge = find(/^Merged$/); const title = find(/^PAY-110 Remove legacy pricing module$/); const builds = find(/^Builds pass$/); const appr = find(/^1 approval$/); const num = find(/^#438$/);
        let card = null; if (num) { let e = [...document.querySelectorAll("body *")].find((x) => x.childElementCount === 0 && x.textContent.trim() === "#438"); for (let i = 0; i < 8 && e; i++) { e = e.parentElement; const b = e.getBoundingClientRect(); if (b.width > 450) { card = { x: b.x, y: b.y, width: b.width, height: b.height }; break; } } }
        return { badge, title, builds, appr, num, card }; });
      console.log("PRCARD", JSON.stringify(meas));
      log({ shot: OUTP, frames: n, url: "?demo=promo", startMs: s, clip: CP, scale: 1920 / CP.width, measCss: meas });
      return;
    }
    rec.clip = null; fs.writeFileSync(`${FOOT}/shot-15-still-drawer-fullframe.png`, await rec.shot());
    const pill = await p.locator("body").innerText().then((t) => (t.match(/In Progress|To Do|Done/g) || []).slice(0, 5));
    // In Progress check: open PAY-109's drawer for the first time after it merged
    await p.keyboard.press("Escape"); await rec.skip(600);
    try { p.setDefaultTimeout(20000); await clickAt(p, p.locator("[aria-label^='PAY-109 ']:not([data-session-navigation])").first()); await rec.skip(2000);
      fs.writeFileSync(`${FOOT}/shot-16-still-PAY-109-first-open-after-merge.png`, await rec.shot()); } catch (e) { console.log("PAY-109 still skipped:", String(e).slice(0, 200)); fs.writeFileSync(`probe/15pr-after-esc.png`, await rec.shot()); }
    log({ shot: "shot-15-prcard", frames: n, url: "?demo=promo", startMs: s, framing: "clip x720 y122 1200x675 CSS @ DPR2 (1.6x); header status pill out of frame", statusWords: pill, scenario: "PAY-110 drawer opened at 59 s; Checks 62.3, Pushed 63.1, PR raised #438 63.9, Merged 67.5" });
  },
  // 6 + 7: PAY-103 node close-up hold and 4 promo cards (no Blocked cards), ~12-20 s
  async "06"() {
    const { p, rec } = await start({ dpr: 2 });
    await rec.skip(17500);
    const box = await node(p, "PAY-103").boundingBox();
    const m = 60; const w = 640, h = 360; const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
    rec.clip = { x: cx - w / 2, y: cy - h / 2, width: w, height: h, scale: 3 };
    if (DRY) { await snap(p, rec, "d06"); }
    await p.mouse.move(1919, 1079);
    const n = await rec.record("shot-06", F(4), async () => {}, { poster: F(2) });
    rec.clip = null;
    const out = [];
    for (const key of ["PAY-103", "PAY-104", "PAY-106", "PAY-105"]) {
      const bb = await node(p, key).boundingBox(); if (!bb) continue;
      fs.writeFileSync(`${FOOT}/shot-07-card-${key}.png`, await rec.clipShot({ x: bb.x - 16, y: bb.y - 16, width: bb.width + 32, height: bb.height + 32, scale: 2 }));
      out.push(key);
    }
    fs.writeFileSync(`${FOOT}/shot-07-still-board.png`, await rec.shot());
    await clickAt(p, p.locator("[aria-label^='PAY-103 ']:not([data-session-navigation])").first()); await rec.skip(1500);
    fs.writeFileSync(`${FOOT}/shot-06-still-drawer-branch.png`, await rec.shot());
    log({ shot: "shot-06", frames: n, url: "?demo=promo", startMs: 17500, framing: "clip 640x360 CSS around PAY-103 node @ DPR2, scale 3 (slight upsample over DPR2)", stills: out, notes: "shot-07 cards = PAY-103/104/106/105 at ~17.6 s (no Blocked cards); shot-06-still-drawer-branch.png shows PAY-103 drawer with its branch line" });
  },

  // 3c: Commander composer typing (promo held on the empty board), Access switched from 'Bypass permissions' (amber) to 'Edits' through the real Access menu first
  async "03c"() {
    const { p, rec } = await start({ q: "?demo=promo&pause=1", dpr: 2 });
    await rec.skip(1500);
    const acc = p.locator("[aria-label^='Access:']").first();
    const before = await acc.getAttribute("aria-label");
    await clickAt(p, acc); await rec.skip(600);
    if (DRY) await snap(p, rec, "d03c-menu");
    await clickAt(p, p.getByRole("menuitemradio", { name: /^Edits/ }).or(p.getByRole("menuitem", { name: /^Edits/ })).first()); await rec.skip(800);
    const after = await acc.getAttribute("aria-label");
    console.log("access", before, "->", after);
    await clickAt(p, p.locator("textarea[data-composer]").first()); await p.mouse.move(1919, 1079); await rec.skip(500);
    const C3 = process.env.CLIP ? JSON.parse(process.env.CLIP) : { x: 30, y: 540, width: 960, height: 540 }; rec.clip = { ...C3, scale: 1920 / C3.width };
    if (DRY && process.env.SEND) {
      await p.keyboard.type("Ship the checkout revamp tonight."); await p.keyboard.press("Shift+Enter"); await p.keyboard.type("No broken builds."); await rec.skip(300);
      fs.writeFileSync("probe/d03s-typed.png", await rec.shot()); console.log("val", JSON.stringify(await p.locator("textarea[data-composer]").first().inputValue()));
      const sb = p.locator("button[aria-label^='Send']").first(); console.log("send btn", await sb.count(), await sb.getAttribute("aria-label").catch(() => null));
      await p.keyboard.press("Enter");
      for (const t of [200, 800, 1000, 2000, 3000]) { await rec.skip(t); fs.writeFileSync(`probe/d03s-${rec.ms}.png`, await rec.shot()); fs.writeFileSync(`probe/d03s-col-${rec.ms}.png`, await rec.clipShot({ x: 280, y: 0, width: 480, height: 1080, scale: 1 })); }
      const msgs = await p.evaluate(() => [...document.querySelectorAll("p,div,span,li")].filter((e) => /Ship the checkout/.test(e.textContent || "") && ![...e.children].some((k) => /Ship the checkout/.test(k.textContent || ""))).map((e) => { const r = e.getBoundingClientRect(); return { tag: e.tagName, t: (e.textContent || "").slice(0, 60), x: r.x, y: r.y, w: r.width, h: r.height }; })); console.log("msgs", JSON.stringify(msgs));
      const ta = await p.locator("textarea[data-composer]").first().boundingBox(); console.log("composer bb", JSON.stringify(ta));
      return;
    }
    if (DRY) { await snap(p, rec, "d03c"); return; }
    const text1 = "Ship the checkout revamp tonight.", text2 = "No broken builds.";
    const CF = Number(process.env.CHARF || 10), LEAD = Number(process.env.LEAD || 60), TAIL = Number(process.env.TAIL || 120);
    const plan = []; let f = LEAD; for (const ch of text1) { plan.push([f, () => p.keyboard.type(ch)]); f += CF; } f += 12; plan.push([f, () => p.keyboard.press("Shift+Enter")]); f += Math.round(42 * CF / 10); for (const ch of text2) { plan.push([f, () => p.keyboard.type(ch)]); f += CF; } const SEND = !!process.env.SEND; let sendF = -1; if (SEND) { f += Number(process.env.SENDGAP || 30); sendF = f; plan.push([f, () => p.keyboard.press("Enter")]); } const end = f + TAIL;
    const at = new Map(plan.map(([k, fn]) => [k, fn]));
    const OUT3 = process.env.OUT || "shot-03-composer";
    const PANY = process.env.PANY ? Number(process.env.PANY) : null, PANS = Number(process.env.PANSTART || 15), PAND = Number(process.env.PANDUR || 36);
    const n = await rec.record(OUT3, end, async (i) => { const fn = at.get(i); if (fn) await fn();
      if (PANY !== null && sendF >= 0 && i >= sendF + PANS) { const u = Math.min(1, (i - sendF - PANS) / PAND), e = u * u * (3 - 2 * u); rec.clip = { ...rec.clip, y: C3.y + (PANY - C3.y) * e }; }
    }, { poster: 9999 });
    log({ shot: OUT3, frames: n, charFrames: CF, sent: SEND, sendFrame: sendF, url: "?demo=promo&pause=1", framing: `clip ${JSON.stringify(C3)} CSS @ DPR2 (${(1920 / C3.width).toFixed(2)}x)`, access: [before, after], notes: `typed at ${(60 / CF).toFixed(1).replace(/\.0$/, "")} chars/s (charFrames ${CF} at 60 fps), ${SEND ? `sent with Enter at frame ${sendF} (${(sendF / 60).toFixed(2)} s)${PANY !== null ? `; crop pans y ${C3.y} -> ${PANY} CSS over frames ${sendF + PANS}-${sendF + PANS + PAND}` : ""}` : "not sent"}; Access changed to Edits via the real Access menu before rolling` });
  },

  // 12b: same review beat, conversation pane widened to 940 px (real pref), DPR2, framed on the reviewer thread (2x)
  async "12b"() {
    const { p, rec } = await start({ dpr: 2, prefsExtra: { conversationWidth: 940 } });
    await rec.skip(24000);
    await clickAt(p, p.locator("[aria-label^='PAY-104 ']:not([data-session-navigation])").first());
    await rec.skip(25200 - rec.ms);
    if (DRY) { await snap(p, rec, "d12b-0"); }
    const s = rec.ms; let clicked = -1;
    const SFX = process.env.SUFFIX || "";
    const n = await rec.record("shot-12-dpr2-pre" + SFX, F(26.6) - F(s / 1000), async () => {}, { poster: 9999 });
    const l = p.getByRole("button", { name: /Review thread/ }).first(); await clickAt(p, l); clicked = rec.ms; await rec.skip(300);
    const box = await p.locator("[aria-label='Resize conversation']").boundingBox().catch(() => null);
    console.log("divider", box);
    rec.clip = { x: 290, y: 0, width: 960, height: 540, scale: 2 };
    if (DRY) { await rec.skip(1500); await snap(p, rec, "d12b-1"); return; }
    const stars = await p.evaluate(() => { const out = []; for (const e of document.querySelectorAll("body *")) { if (e.childElementCount === 0 && /\*\*/.test(e.textContent)) out.push(e.textContent.slice(0, 120)); } return out; });
    console.log("double-asterisks in DOM:", JSON.stringify(stars));
    const m = await rec.record("shot-12-dpr2" + SFX, F(5.5), async () => {}, { poster: F(3) });
    log({ shot: "shot-12-dpr2" + SFX, frames: m, url: "?demo=promo", startMs: clicked + 300, prefs: { conversationWidth: 940 }, framing: "DPR2, clip x290 y0 960x540 CSS (2x) on the conversation pane", scenario: "reviewer thread for PAY-104 / PR #432 opened from the drawer's 'Review thread' at 26.6 s: 'Approved. Cart summary uses the pricing engine matches the plan...' + '1 task approved'" });
    log({ shot: "shot-12-dpr2-pre" + SFX, frames: n, url: "?demo=promo", startMs: s, framing: "DPR2 full frame (no clip)", scenario: "PAY-104 drawer, In review, before the Review thread click (25.2-26.6 s)" });
  },

  // talk-dag: ?demo=1&still=1 Board graph, full window, in-app zoom, DPR2 tight clip on PAY-101..104 + wave headings; 6 s hold with a slow pan
  async "talk-dag"() {
    // UI ops in real time (clock running), then pause the virtual clock and record
    const q = "?demo=1&still=1";
    const r = await open(b, { q, clock: true, css: NO_TOASTS, dpr: 2 });
    const p = r.page; p.setDefaultTimeout(120000);
    await p.waitForTimeout(9000); await dismiss(p);
    const rec = new Recorder(p);
    const realClick = async (loc) => { const [x, y] = await center(loc); await p.mouse.click(x, y); await p.mouse.move(1919, 1079); await p.waitForTimeout(1500); };
    if (process.env.FULL) await realClick(p.getByRole("button", { name: "Full window" }).first());
    const done = p.getByRole("button", { name: /^Show \d+ done/ }).first();
    if (await done.isVisible().catch(() => false)) await realClick(done);
    const ZOOM = Number(process.env.ZOOM || 0); // target zoom percent (ctrl+wheel), 0 = leave
    const zoomNow = async () => { const z = parseInt(await p.getByText(/^\d+%$/).first().innerText({ timeout: 3000 }).catch(() => "0")); console.log("zoom", z); return z; };
    const UN = (process.env.UNION || "PAY-101,PAY-102,PAY-104,Landed,Wave 1").split(",");
    const union = async () => { const bs = []; for (const k of UN.filter((x) => x.startsWith("PAY-"))) bs.push(await node(p, k).boundingBox()); for (const h of UN.filter((x) => !x.startsWith("PAY-"))) bs.push(await p.getByText(h, { exact: true }).first().boundingBox()); const x0 = Math.min(...bs.map((b) => b.x)), y0 = Math.min(...bs.map((b) => b.y)), x1 = Math.max(...bs.map((b) => b.x + b.width)), y1 = Math.max(...bs.map((b) => b.y + b.height)); return { x0, y0, x1, y1 }; };
    p.setDefaultTimeout(60000); for (let k = 0; ZOOM && k < 16 && (await zoomNow()) < ZOOM; k++) { const u = await union(); await p.mouse.move((u.x0 + u.x1) / 2, (u.y0 + u.y1) / 2); await p.keyboard.down("Control"); await p.mouse.wheel(0, -100); await p.keyboard.up("Control"); await p.waitForTimeout(700); }
    for (let k = 0; k < 4; k++) { const u = await union(); const dx = (u.x0 + u.x1) / 2 - 960, dy = (u.y0 + u.y1) / 2 - 560; if (Math.abs(dx) < 20 && Math.abs(dy) < 20) break; await p.mouse.move(960, 560); await p.mouse.wheel(dx, dy); await p.waitForTimeout(900); }
    await p.mouse.move(1919, 1079); await p.waitForTimeout(1500);
    const boxes = {};
    for (const k of ["PAY-101", "PAY-102", "PAY-103", "PAY-104"]) boxes[k] = await node(p, k).boundingBox();
    const heads = await p.getByText(/^(Wave \d|Landed)$/).evaluateAll((es) => es.map((e) => [e.textContent, ...Object.values(e.getBoundingClientRect().toJSON()).slice(0, 4).map(Math.round)]));
    const idPx = await node(p, "PAY-101").evaluate((e) => { const t = [...e.querySelectorAll("*")].find((x) => x.childElementCount === 0 && /^PAY-101$/.test(x.textContent.trim())); if (!t) return null; const b = t.getBoundingClientRect(); return [parseFloat(getComputedStyle(t).fontSize), Math.round(b.height * 10) / 10]; }).catch(() => null);
    const zoomText = await p.getByText(/^\d+%$/).first().innerText().catch(() => "?");
    const u = await union(); const pad = Number(process.env.PAD || 28); let w = Math.max(u.x1 - u.x0 + 2 * pad, ((u.y1 - u.y0 + 2 * pad) * 16) / 9, 960); w = Math.min(w, 1920); const h = (w * 9) / 16;
    const C = process.env.CLIP ? JSON.parse(process.env.CLIP) : { x: Math.round(Math.max(0, Math.min(1920 - w, (u.x0 + u.x1) / 2 - w / 2))), y: Math.round(Math.max(0, Math.min(1080 - h, (u.y0 + u.y1) / 2 - h / 2))), width: Math.round(w), height: Math.round(h) };
    console.log("boxes", JSON.stringify(boxes), "heads", JSON.stringify(heads), "id", idPx, "zoom", zoomText, "union", JSON.stringify(u), "clip", JSON.stringify(C), "idOut", idPx && Math.round(idPx[1] * 1920 / C.width));
    if (DRY) { await p.screenshot({ path: `probe/dtalk-${process.env.ID||"talk-dag"}-z${ZOOM}.png` }); await p.screenshot({ path: `probe/dtalk-${process.env.ID||"talk-dag"}-z${ZOOM}-clip.png`, clip: C }); return; }
    await rec.begin();
    rec.clip = { ...C, scale: 1920 / C.width };
    const ID = process.env.ID || "talk-dag";
    const n = await rec.record(ID, F(6), async () => {}, { poster: F(3) });
    log({ shot: ID, union: UN, frames: n, url: q, framing: `DPR2, board ${process.env.FULL ? "Full window, " : ""}Show done, ctrl+wheel zoom to ${zoomText}; clip ${JSON.stringify(C)} CSS`, idFont: idPx, notes: "Board graph (DAG) with Wave headings and PAY-101..104 dependency edges; locked hold" });
  },


});
try { if (!shots[SHOT]) throw new Error("unknown " + SHOT); await shots[SHOT](); } finally { await b.close(); }
await flush();
process.exit(0);
