import fs from "node:fs";
import { launch, open, dismiss, COMMIT, CSS, markCursorOverlay } from "./lib.mjs";
import { Recorder, FOOT, flush } from "./rec.mjs";
const SHOT = process.argv[2];
const DRY = !!process.env.DRY;
const MAXF = process.env.MAXF ? Number(process.env.MAXF) : Infinity;
const F = (s) => Math.round(s * 60);
const log = (o) => fs.appendFileSync(`${FOOT}/capture-log.jsonl`, JSON.stringify({ at: new Date().toISOString(), commit: COMMIT, ...o }) + "\n");
const b = await launch();
const CURSOR = () => { const c = document.createElement("div"); c.id = "cap-cursor"; c.style.cssText = "position:fixed;left:0;top:0;width:34px;height:34px;z-index:2147483647;pointer-events:none;transform:translate(-100px,-100px)"; c.innerHTML = '<svg width="34" height="34" viewBox="0 0 28 28"><path d="M5 3 L5 22 L10 17.5 L13.5 25 L16.8 23.6 L13.3 16.2 L20 16.2 Z" fill="#fff" stroke="#000" stroke-width="1.4" stroke-linejoin="round"/></svg>'; document.body.appendChild(c); addEventListener("pointermove", (e) => { c.style.transform = `translate(${e.clientX - 6}px, ${e.clientY - 4}px)`; }, true); };
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
async function start(opts = {}) {
  const r = await open(b, { clock: "paused", q: "?demo=1&still=1", css: CSS.NO_TOASTS, ...opts });
  r.page.setDefaultTimeout(40000); r.page.on("pageerror", (e) => console.log("PAGEERR", String(e).slice(0, 200)));
  await r.page.waitForTimeout(9000); await dismiss(r.page);
  const rec = new Recorder(r.page); await rec.begin({ paused: true }); await rec.skip(5000); await dismiss(r.page); await rec.skip(1000);
  return { p: r.page, rec };
}
const center = async (loc) => { const bb = await loc.boundingBox(); if (!bb) throw new Error("no box"); return [bb.x + bb.width / 2, bb.y + bb.height / 2]; };
const clickAt = async (p, loc) => { const [x, y] = await center(loc); await p.mouse.click(x, y); await p.mouse.move(1919, 1079); };
async function activateProvider(p, rec) {
  await clickAt(p, p.locator("button[aria-label*=ettings]").last()); await rec.skip(1200);
  await clickAt(p, p.getByText("Suggestions", { exact: true }).first()); await rec.skip(800);
  await clickAt(p, p.getByRole("button", { name: /Turn on/ }).first()); await rec.skip(1200);
  await clickAt(p, p.getByRole("combobox").first()); await rec.skip(500);
  await clickAt(p, p.getByRole("option", { name: "TypeSafe" })); await rec.skip(800);
  await p.getByPlaceholder("Enter API key").fill("demo-key"); await rec.skip(300);
  await clickAt(p, p.getByRole("button", { name: "Test and activate" })); await rec.skip(2500);
  await p.keyboard.press("Escape"); await rec.skip(800);
}

const mkPlan = (p, start = [1500, 760]) => {
  const m = new Map(); const st = { cur: start.slice() };
  const at = (f, fn) => { if (!m.has(f)) m.set(f, []); m.get(f).push(fn); };
  const glide = (f0, dur, getTo) => {
    const g = {};
    at(f0, async () => { g.to = await getTo(); g.from = st.cur.slice(); });
    for (let k = 1; k <= dur; k++) at(f0 + k, async () => { const e = ease(k / dur); st.cur = [g.from[0] + (g.to[0] - g.from[0]) * e, g.from[1] + (g.to[1] - g.from[1]) * e]; await p.mouse.move(st.cur[0], st.cur[1]); });
  };
  const click = (f) => at(f, async () => { await p.mouse.down(); await p.mouse.up(); });
  const type = (f0, text, cf) => { let f = f0; for (const ch of text) { at(f, () => p.keyboard.type(ch)); f += cf; } return f; };
  return { m, at, glide, click, type, st, run: async (i) => { for (const fn of m.get(i) || []) await fn(); } };
};
const toCenter = (loc) => async () => center(loc);
const toNearestY = (p, sel, ref) => async () => {
  const rb = await ref.boundingBox(); const y = rb.y + rb.height / 2; const items = p.locator(sel); const n = await items.count(); let best = null;
  for (let i = 0; i < n; i++) { const bb = await items.nth(i).boundingBox(); if (!bb) continue; const d = Math.abs(bb.y + bb.height / 2 - y); if (!best || d < best.d) best = { d, c: [bb.x + bb.width / 2, bb.y + bb.height / 2] }; }
  if (!best) throw new Error("no mark near " + sel); return best.c;
};
async function toTicketForm(p, rec) {
  await clickAt(p, p.getByText("Build", { exact: true }).first()); await rec.skip(2500);
  await clickAt(p, p.getByRole("button", { name: /^New/ }).filter({ hasText: /New/ }).last()); await rec.skip(800);
  await clickAt(p, p.getByText("Write a ticket").first()); await rec.skip(3500);
  await clickAt(p, p.getByText("New ticket", { exact: true }).first()); await rec.skip(1500);
  await clickAt(p, p.getByPlaceholder(/What should change/).first()); await rec.skip(600);
  const focused = await p.evaluate(() => document.activeElement && document.activeElement.getAttribute("placeholder"));
  if (!/What should change/.test(focused || "") || (await p.locator("[role=menu]").count()) > 0) throw new Error("summary not focused or menu open: " + focused);
}
const meta = (name, framing, notes) => log({ shot: name, url: "?demo=1&still=1", framing, notes, jev_fixture_patch: "dev/demo.ts, demoWorkshopMind.ts, demoPrReview.ts by JEV" });
const shots = {
  async ticket() {
    const { p, rec } = await start({ dpr: 2 });
    await activateProvider(p, rec);
    await clickAt(p, p.getByText("Build", { exact: true }).first()); await rec.skip(2500);
    await clickAt(p, p.getByRole("button", { name: /^New/ }).filter({ hasText: /New/ }).last()); await rec.skip(800);
    await clickAt(p, p.getByText("Write a ticket").first()); await rec.skip(3500);
    if (DRY) { for (const k of [0, 1, 2]) { fs.writeFileSync(`${FOOT}/dbg-${k}.png`, await rec.shot()); await rec.skip(1500); } console.log("menus", await p.locator("[role=menu]").count()); return; }
    await clickAt(p, p.getByText("New ticket", { exact: true }).first()); await rec.skip(1500);
    await clickAt(p, p.getByPlaceholder(/What should change/).first()); await rec.skip(600);
    const focused = await p.evaluate(() => document.activeElement && document.activeElement.getAttribute("placeholder"));
    if (!/What should change/.test(focused || "") || (await p.locator("[role=menu]").count()) > 0) throw new Error("summary not focused or menu open: " + focused);
    await p.evaluate(CURSOR); markCursorOverlay(p);
    const text = process.env.TEXT || "Apple Pay express checkout button on the review step";
    const CF = Number(process.env.CHARF || 5);
    const plan = new Map(); let f = F(0.8); for (const ch of text) { plan.set(f, () => p.keyboard.type(ch)); f += CF; }
    const tabF = f + F(0.4); plan.set(tabF, () => p.keyboard.press("Tab"));
    const panF = tabF + F(3), panDur = F(1.0), clickF = panF + panDur + F(1.4);
    const A = { x: 628, y: 150, width: 1280, height: 720 }, B = { x: 628, y: 330, width: 1280, height: 720 }, G = { x: 640, y: 250, width: 1280, height: 720 };
    rec.clip = { ...A, scale: 1.5 };
    let moveFrom = null, target = null, saved = -1;
    const total = Math.min(MAXF, clickF + F(1.6) + F(5.5));
    const n = await rec.record(process.env.OUT || "jev-ticket-place", total, async (i) => {
      const fn = plan.get(i); if (fn) await fn();
      if (i >= panF && i < panF + panDur) { const e = ease((i - panF) / panDur); rec.clip = { x: A.x, y: A.y + (B.y - A.y) * e, width: 1280, height: 720, scale: 1.5 }; }
      if (i === panF + panDur) rec.clip = { ...B, scale: 1.5 };
      if (i === clickF - F(1.0)) { target = await center(p.getByRole("button", { name: "Save draft" })); moveFrom = [1500, 760]; await p.mouse.move(...moveFrom); }
      if (target && i >= clickF - F(1.0) && i < clickF) { const k = ease((i - (clickF - F(1.0))) / F(1.0)); await p.mouse.move(moveFrom[0] + (target[0] - moveFrom[0]) * k, moveFrom[1] + (target[1] - moveFrom[1]) * k); }
      if (i === clickF) { await p.mouse.down(); await p.mouse.up(); saved = rec.ms; }
      if (saved >= 0 && i === clickF + F(1.6)) { await p.mouse.move(1919, 1079); rec.clip = { ...G, scale: 1.5 }; }
    }, { poster: clickF - F(1) });
    log({ shot: "jev-ticket-place", frames: n, url: "?demo=1&still=1", framing: "DPR2, clips 1280x720 CSS at 1.5x: A typing, pan to B, G graph after Save draft", notes: `Settings > Suggestions > TypeSafe demo key activated first (synthetic demo test). Typed '${text}' at ${CF} frames per char, Tab to settle, JEV suggestions and Possible duplicate note, real click on Save draft, graph slots the draft (dotted JEV edge). Capture-overlay cursor.`, jev_fixture_patch: "dev/demo.ts by JEV" });
  },
  async shop() {
    const { p, rec } = await start({ dpr: 2 });
    await clickAt(p, p.getByText("Build", { exact: true }).first()); await rec.skip(2500);
    await clickAt(p, p.getByRole("tab", { name: /orkshop/ })); await rec.skip(6000);
    await clickAt(p, p.getByRole("button", { name: /^Shop$/ }).first()); await rec.skip(2500);
    await p.evaluate(CURSOR); markCursorOverlay(p);
    const buy = p.getByRole("button", { name: /^Buy/ }).first();
    const C = { x: 628, y: 20, width: 1280, height: 720 };
    rec.clip = { ...C, scale: 1.5 };
    let to = null;
    const total = Math.min(MAXF, F(7));
    const n = await rec.record(process.env.OUT || "jev-shop-next", total, async (i) => {
      if (i === F(2.0)) { to = await center(buy); await p.mouse.move(1700, 700); }
      if (to && i >= F(2.0) && i < F(3.2)) { const k = ease((i - F(2.0)) / F(1.2)); await p.mouse.move(1700 + (to[0] - 1700) * k, 700 + (to[1] - 700) * k); }
    }, { poster: F(4) });
    log({ shot: "jev-shop-next", frames: n, url: "?demo=1&still=1", framing: "DPR2, clip 1280x720 CSS at 1.5x, Workshop tab, Shop panel", notes: "Suggested next with the JEV mark; cursor hovers Buy without clicking (a click would spend the demo wallet)." });
  },
  async why() {
    const { p, rec } = await start({ dpr: 2 });
    await activateProvider(p, rec); await toTicketForm(p, rec);
    await p.evaluate(CURSOR); markCursorOverlay(p);
    const pl = mkPlan(p); const F4 = 4;
    const typed = pl.type(F(0.6), "Apple Pay express checkout button on the review step", F4);
    const tab = typed + F(0.4); pl.at(tab, () => p.keyboard.press("Tab"));
    const P1 = tab + F(2.4), panDur = F(1.0);
    const typeBox = () => p.getByRole("combobox", { name: "Issue type" });
    const C0 = P1 + F(1.5); pl.glide(C0, F(0.7), toNearestY(p, ".ai-mark", typeBox()));
    const D0 = C0 + F(0.7) + F(3.2); pl.glide(D0, F(0.6), async () => { const c = await center(typeBox()); return [c[0] - 100, c[1]]; });
    pl.click(D0 + F(0.7));
    const E0 = D0 + F(0.7) + F(0.9); pl.glide(E0, F(0.5), async () => center(p.getByRole("option", { name: "Bug" }).first()));
    pl.click(E0 + F(0.6));
    const R0 = E0 + F(0.6) + F(1.5); pl.glide(R0, F(0.6), async () => center(p.locator(".ai-revert").first()));
    const R1 = R0 + F(0.6) + F(2.4); pl.click(R1);
    const total = Math.min(MAXF, R1 + F(2.0));
    const A = { x: 628, y: 150, width: 1280, height: 720 }, B = { x: 628, y: 330, width: 1280, height: 720 };
    rec.clip = { ...A, scale: 1.5 };
    const n = await rec.record(process.env.OUT || "jev-ticket-why", total, async (i) => {
      await pl.run(i);
      if (i >= P1 && i < P1 + panDur) { const e = ease((i - P1) / panDur); rec.clip = { x: A.x, y: A.y + (B.y - A.y) * e, width: 1280, height: 720, scale: 1.5 }; }
      if (i === P1 + panDur) rec.clip = { ...B, scale: 1.5 };
    }, { poster: C0 + F(2.0) });
    meta("jev-ticket-why", "DPR2, clip 1280x720 at 1.5x, pan A to B", "Ticket form: hover the JEV mark on Type (source and confidence tooltip), change Type to Bug (revert pill with 'You picked something else' tooltip), click the pill to take the suggestion back. Capture-overlay cursor.");
  },
  async review() {
    const { p, rec } = await start({ dpr: 2 });
    await activateProvider(p, rec);
    await clickAt(p, p.getByText("Build", { exact: true }).first()); await rec.skip(2500);
    const ops = p.getByText("ops-toolkit", { exact: true }).first(); await ops.scrollIntoViewIfNeeded(); await rec.skip(500);
    await clickAt(p, ops); await rec.skip(3000);
    await clickAt(p, p.getByRole("tab", { name: /^Review/ }).first()); await rec.skip(3000);
    for (let k = 0; k < 40 && (await p.locator(".ai-mark").count()) === 0; k++) await rec.skip(500);
    if ((await p.locator(".ai-mark").count()) === 0) { fs.writeFileSync(`${FOOT}/dbg-review.png`, await rec.shot()); console.log("BODY", (await p.locator("body").innerText()).slice(0, 700).replace(/\n+/g, " | ")); throw new Error("review pick mark never appeared"); }
    await p.evaluate(CURSOR); markCursorOverlay(p);
    const pl = mkPlan(p, [1700, 900]);
    const mark = () => p.locator(".ai-mark").first();
    pl.glide(F(0.8), F(0.8), toCenter(mark()));
    const total = Math.min(MAXF, F(0.8) + F(0.8) + F(5.0));
    rec.clip = { x: 640, y: 330, width: 1280, height: 720, scale: 1.5 };
    const n = await rec.record(process.env.OUT || "jev-review-pick", total, async (i) => { await pl.run(i); }, { poster: F(4) });
    meta("jev-review-pick", "DPR2, clip (640,330) 1280x720 at 1.5x, ops-toolkit Review pane", "Waiting on you: PR #121 with the JEV mark; hover shows source, confidence and the batched assessments of urgency, coverage, changes and risk.");
  },
  async worknext() {
    const { p, rec } = await start({ dpr: 2 });
    await activateProvider(p, rec);
    await clickAt(p, p.getByText("Build", { exact: true }).first()); await rec.skip(2500);
    await clickAt(p, p.getByRole("button", { name: /^New/ }).filter({ hasText: /New/ }).last()); await rec.skip(800);
    await clickAt(p, p.getByText("Work on a ticket").first()); await rec.skip(3000);
    await p.evaluate(CURSOR); markCursorOverlay(p);
    const pl = mkPlan(p, [1500, 900]);
    pl.glide(F(0.8), F(0.8), toCenter(p.getByText("JEV", { exact: true }).first()));
    const T0 = F(0.8) + F(0.8) + F(3.0);
    pl.glide(T0, F(0.7), toCenter(p.getByPlaceholder("Paste or type related details")));
    pl.click(T0 + F(0.8));
    const typed = pl.type(T0 + F(1.0), "refund receipts rounding", 4);
    const U0 = typed + F(0.6); pl.glide(U0, F(0.6), toCenter(p.getByRole("button", { name: "Use text for suggestion" })));
    pl.click(U0 + F(0.7));
    const total = Math.min(MAXF, U0 + F(0.7) + F(3.0));
    rec.clip = { x: 480, y: 190, width: 1280, height: 720, scale: 1.5 };
    const n = await rec.record(process.env.OUT || "jev-worknext", total, async (i) => { await pl.run(i); }, { poster: F(3) });
    meta("jev-worknext", "DPR2, clip (480,190) 1280x720 at 1.5x", "New > Work on a ticket: Suggested next with the JEV mark, hover tooltip, optional context typed and Use text for suggestion clicked.");
  },
  async settings() {
    const { p, rec } = await start({ dpr: 2 });
    await p.evaluate(CURSOR); markCursorOverlay(p);
    const pl = mkPlan(p, [1500, 900]);
    const gear = () => p.locator("button[aria-label*=ettings]").last();
    pl.glide(F(0.5), F(0.7), toCenter(gear())); pl.click(F(1.3));
    const S0 = F(2.8); pl.glide(S0, F(0.6), toCenter(p.getByText("Suggestions", { exact: true }).first())); pl.click(S0 + F(0.7));
    const T0 = S0 + F(0.7) + F(2.2); pl.glide(T0, F(0.6), toCenter(p.getByRole("button", { name: /Turn on/ }).first())); pl.click(T0 + F(0.7));
    const C0 = T0 + F(0.7) + F(4.0); pl.glide(C0, F(0.6), toCenter(p.getByRole("combobox").first())); pl.click(C0 + F(0.7));
    const O0 = C0 + F(0.7) + F(1.0); pl.glide(O0, F(0.5), toCenter(p.getByRole("option", { name: "TypeSafe" }))); pl.click(O0 + F(0.6));
    const K0 = O0 + F(0.6) + F(2.4); pl.glide(K0, F(0.5), toCenter(p.getByPlaceholder("Enter API key"))); pl.click(K0 + F(0.6));
    const typed = pl.type(K0 + F(0.8), "demo-key", 5);
    const B0 = typed + F(0.5); pl.glide(B0, F(0.6), toCenter(p.getByRole("button", { name: "Test and activate" }))); pl.click(B0 + F(0.7));
    const total = Math.min(MAXF, B0 + F(0.7) + F(3.5));
    rec.clip = { x: 480, y: 160, width: 1280, height: 720, scale: 1.5 };
    const n = await rec.record(process.env.OUT || "jev-settings", total, async (i) => { await pl.run(i); }, { poster: C0 + F(1) });
    meta("jev-settings", "DPR2, clip (480,160) 1280x720 at 1.5x", "Settings > Suggestions: off state, Turn on shows the local Laya decision model description, pick TypeSafe, demo key, Test and activate (synthetic demo test).");
  },
};
try { if (!shots[SHOT]) throw new Error("unknown " + SHOT); await shots[SHOT](); } finally { await b.close(); }
await flush();
process.exit(0);
