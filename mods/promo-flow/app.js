"use strict";
/* Promo flow mod, mounted by the host straight into its page inside a shadow root (protocol 2). It talks to the host only through ctx.post and receive.
   in:  init, state, media, result, theme     out: ready, media, action, title, open-url */
window.commissionMods = window.commissionMods || {};
window.commissionMods["promo-flow"] = function mount(ctx) {
  const STAGE_IDS = ["discover", "scripts", "pick", "storyboard", "assets", "keyframes", "confirm", "drafts", "review", "final"];
  const STAGE_LABEL = { discover: "Style & references", scripts: "Scripts", pick: "Pick stories", storyboard: "Storyboard", assets: "Asset plan", keyframes: "Keyframes", confirm: "Final confirmation", drafts: "First drafts", review: "Review rounds", final: "Final" };
  const SHORT = { discover: "Style", scripts: "Scripts", pick: "Pick", storyboard: "Storyboard", assets: "Assets", keyframes: "Keyframes", confirm: "Confirm", drafts: "Drafts", review: "Review", final: "Final" };
  const STAGE_TAB = { scripts: "scripts", pick: "scripts", storyboard: "storyboard", assets: "assets", keyframes: "storyboard", confirm: "storyboard", drafts: "draft", review: "draft", final: "draft" };
  const BADGE_TEXT = { working: "With the agent", waiting: "Your turn", done: "Done", attention: "Needs attention" };
  const ACTION_WORD = { approve: "your approval", pick: "your picks", changes: "your changes", feedback: "your feedback", generate: "your request", request: "your request", density: "your request", share: "your upload request", settings: "your folder choice" };
  const KIND_ICON = { script: "doc", treatment: "spark", shotlist: "table", direction: "film", edit: "cut", audio: "music", capture: "camera", schedule: "clock", deliverables: "download", risks: "shield", research: "link", review: "refresh", notes: "doc" };
  const QUICK = [["Full script", "Write the full script as a document I can read: voice-over, on-screen text and action for every scene."], ["Shot list", "Add a shot list: one row per shot with time, picture, camera, caption, voice and proof."],
    ["Edit plan", "Add an edit plan: the cut list on the timeline with transitions, rhythm and what holds still."], ["Audio plan", "Add an audio plan: voice lines, music cues, sound effects and mix targets."],
    ["Capture checklist", "Add a capture checklist: every recording and screenshot to make, how, and in what state."], ["Everything for production", "Build the whole production pack: treatment, director's notes, shot list, edit plan, audio plan, capture checklist, claims and risks, deliverables and schedule."]];
  const VERDICT = { yes: ["Intent matched", "ok"], partial: ["Partly matched", "warn"], no: ["Missed the intent", "bad"] };
  const KIND_LABEL = { screenshot: "Screenshot", image: "Image", recording: "Recording", video: "Video", music: "Music", voice: "Voice", sfx: "Sound effect" };
  const KIND_MEDIA = { screenshot: "image", image: "image", recording: "video", video: "video", music: "audio", voice: "audio", sfx: "audio" };
  const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || "");
  const MAX_NOTE = 1500, STALL_MS = 45000, BOOT_MS = 8000;
  const BIG_VIDEO = 24 * 1024 * 1024, BIG_AUDIO = 8 * 1024 * 1024, BIG_DRAFT = 60 * 1024 * 1024;

  const $ = (id) => ctx.root.getElementById(id);
  const root = ctx.root.host;
  const el = { sc: $("scroller"), app: $("app"), stepNo: $("stepNo"), badge: $("badge"), badgeText: $("badgeText"), stageName: $("stageName"), stepsBtn: $("stepsBtn"), settingsBtn: $("settingsBtn"), stateLine: $("stateLine"),
    stepper: $("stepper"), curLab: $("curLab"), stepsList: $("stepsList"), banners: $("banners"), job: $("job"), working: $("working"), tabs: $("tabs"), content: $("content"), gate: $("gate"), gateNote: $("gateNote"),
    compose: $("compose"), note: $("note"), noteLabel: $("noteLabel"), noteHint: $("noteHint"), gateErr: $("gateErr"), btn2: $("btnSecondary"), btn1: $("btnPrimary"),
    lb: $("lightbox"), toast: $("toast"), live: $("live") };

  const S = {
    booted: false, version: null, summary: {}, doc: {}, pending: null, offline: false, readonly: false,
    tab: null, userTab: false, stage: null, picks: new Set(), style: null, ownStyle: "", boardIdx: 0, draftSel: null, earlier: false, filter: null, checksOpen: false,
    seen: new Set(), ref: "", settingsOpen: false, setSel: null, setText: "", compose: false, composeKind: null, reader: null, sbView: "scenes", docGroup: null, docQ: "", docBase: null, docOpened: new Set(), reqHint: "", sending: null, justSent: null, stall: false, err: "", stale: null, stash: null, updated: false, stepsOpen: false, lastAction: null, title: "", lastBadge: "", noState: false,
  };

  /* ---------------- tiny DOM helper ---------------- */
  function h(tag, props, ...kids) {
    const n = document.createElement(tag);
    if (props) for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (k === "style") n.setAttribute("style", v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat(Infinity)) if (c != null && c !== false) n.append(c.nodeType ? c : document.createTextNode(String(c)));
    return n;
  }
  const ic = (n, c) => window.icon(n, c);
  const post = ctx.post;
  const clip = (s, n) => { s = String(s == null ? "" : s); return s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s; };
  const fmtSize = (b) => (b >= 1048576 ? (b / 1048576).toFixed(b >= 10485760 ? 0 : 1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");
  const fmtTime = (s) => { s = Math.max(0, Math.round(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
  const num = (x) => (Math.round(x * 10) / 10).toString();
  const arr = (x) => (Array.isArray(x) ? x : []);
  const cap = (s) => String(s || "").charAt(0).toUpperCase() + String(s || "").slice(1);
  const host = (u) => { try { const x = new URL(u); const p = x.pathname.length > 1 ? x.pathname : ""; return x.hostname.replace(/^www\./, "") + (p.length > 28 ? p.slice(0, 27) + "…" : p); } catch (_) { return clip(u, 40); } };
  const reduced = () => el.app.dataset.motion === "reduce" || (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  const say = (t) => { el.live.textContent = ""; setTimeout(() => { el.live.textContent = t; }, 30); };
  let toastTimer = 0;
  function toast(msg) { el.toast.textContent = msg; el.toast.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.toast.hidden = true; }, 6000); }
  const scrubPaths = (t) => String(t || "").replace(/\s*(?:Prompt in\s+)?\b(?:flow|footage|assets|audio|out|build|projects)\/[\w./-]+\.?/gi, "").trim();

  function fadeX(node) {
    node.classList.add("fade-x");
    const upd = () => {
      node.style.setProperty("--fl", node.scrollLeft > 2 ? "24px" : "0px");
      node.style.setProperty("--fr", node.scrollLeft + node.clientWidth < node.scrollWidth - 2 ? "24px" : "0px");
    };
    node.addEventListener("scroll", upd, { passive: true });
    if (window.ResizeObserver) new ResizeObserver(upd).observe(node);
    requestAnimationFrame(upd);
  }
  function revealX(box, child) {
    if (!box || !child) return;
    const l = child.offsetLeft, r = l + child.offsetWidth;
    if (l < box.scrollLeft + 24) box.scrollLeft = Math.max(0, l - 24);
    else if (r > box.scrollLeft + box.clientWidth - 24) box.scrollLeft = r - box.clientWidth + 24;
  }

  /* ---------------- media over the bridge ---------------- */
  const M = { seq: 0, waiting: new Map(), cache: new Map(), queue: [] };
  const PF = window.PF;
  const mref = PF.mref;
  const mkind = (r, fallback) => {
    const mt = (r && r.mime) || "";
    if (/^image\//.test(mt)) return "image";
    if (/^video\//.test(mt)) return "video";
    if (/^audio\//.test(mt)) return "audio";
    const nm = ((r && r.name) || "").toLowerCase();
    if (/\.(png|jpe?g|webp|gif|avif)$/.test(nm)) return "image";
    if (/\.(mp4|mov|webm|m4v)$/.test(nm)) return "video";
    if (/\.(wav|mp3|m4a|aac|ogg|flac)$/.test(nm)) return "audio";
    return fallback || "file";
  };
  /* A story has 30+ frames: asking the host for all of them at once made some time out on a cold load, so only a few requests are in flight. */
  const MAX_INFLIGHT = 6;
  const pumpMedia = () => { while (M.waiting.size < MAX_INFLIGHT && M.queue.length) M.queue.shift()(); };
  function getMedia(r) {
    const hit = M.cache.get(r.upload_id);
    if (hit) return hit.p;
    const entry = { kind: mkind(r), url: null };
    entry.p = new Promise((resolve, reject) => {
      const id = "m" + ++M.seq;
      M.queue.push(() => {
        const timer = setTimeout(() => { M.waiting.delete(id); reject(new Error("The host did not answer in time.")); pumpMedia(); }, 30000);
        M.waiting.set(id, { resolve, reject, timer, r });
        post({ type: "media", id, upload_id: r.upload_id });
      });
      pumpMedia();
    }).then((url) => { entry.url = url; return url; }, (e) => { M.cache.delete(r.upload_id); throw e; });
    M.cache.set(r.upload_id, entry);
    return entry.p;
  }
  /* A script or document arrives as text inside the state (the host copies only image, audio and video files). Its pages are kept per document
     so a refresh (the agent added a part, the step moved on) repaints the reader without re-paginating or flashing a skeleton. */
  const T = { cache: new Map() };
  function textPages(key, text) {
    const k = key + "|" + text.length;
    let hit = T.cache.get(k);
    if (!hit) { hit = { pages: PF.paginate(text) }; T.cache.set(k, hit); }
    return hit.pages;
  }
  function onMediaReply(m) {
    const w = M.waiting.get(m.id);
    if (!w) return;
    M.waiting.delete(m.id);
    clearTimeout(w.timer);
    pumpMedia();
    if (m.blob) {
      let b = m.blob;
      if (!b.type && w.r.mime) b = new Blob([b], { type: w.r.mime });
      w.resolve(URL.createObjectURL(b));
    } else w.reject(new Error(m.error || "The file is not available."));
  }
  function revoke(id) {
    const e = M.cache.get(id);
    if (!e) return;
    M.cache.delete(id);
    e.p.then((u) => { if (u) URL.revokeObjectURL(u); }, () => {});
  }
  function releaseHeavy() { for (const [id, e] of [...M.cache]) if (e.kind === "video" || e.kind === "audio") revoke(id); }
  function releaseUnused() {
    const live = new Set();
    (function walk(x) {
      if (Array.isArray(x)) x.forEach(walk);
      else if (x && typeof x === "object") { if (x.$media && x.$media.upload_id) live.add(x.$media.upload_id); else Object.values(x).forEach(walk); }
    })(S.doc);
    for (const id of [...M.cache.keys()]) if (!live.has(id)) revoke(id);
    const texts = new Set(readables().map((x) => { const b = PF.bodyOf(x); return b.text ? x.key + "|" + b.text.length : null; }));
    for (const k of [...T.cache.keys()]) if (!texts.has(k)) T.cache.delete(k);
  }

  const ioMap = new WeakMap();
  const io = "IntersectionObserver" in window ? new IntersectionObserver((es) => {
    for (const e of es) if (e.isIntersecting) { io.unobserve(e.target); const f = ioMap.get(e.target); if (f) f(); }
  }, { rootMargin: "300px 0px" }) : null;
  function whenVisible(node, fn) { if (!io) return fn(); ioMap.set(node, fn); io.observe(node); }

  /* Fill `slot` with build(url) once the media is loaded (lazily, when scrolled near); skeleton, then a retryable error. */
  function lazyInto(slot, r, build, opts = {}) {
    const run = () => {
      slot.replaceChildren(h("div", { class: "sk", style: "position:absolute;inset:0", "aria-hidden": "true" }));
      getMedia(r).then((u) => { slot.replaceChildren(build(u)); if (opts.done) opts.done(); }, () => {
        if (opts.compact) slot.replaceChildren(h("button", { class: "retry", type: "button", "aria-label": "Couldn't load. Try again", onclick: run }, ic("refresh"), h("span", { text: "Couldn't load" })));
        else slot.replaceChildren(h("div", { class: "mid bad", role: "alert" }, ic("alert"), h("span", { text: opts.errText || "Couldn't load this file." }),
          h("button", { class: "load", type: "button", text: "Try again", onclick: run })));
      });
    };
    if (opts.manual) slot.replaceChildren(h("div", { class: "mid" }, h("button", { class: "load", type: "button", text: opts.manualText || "Load (" + fmtSize(r.size) + ")", onclick: run })));
    else whenVisible(slot, run);
  }

  /* ---------------- theme ---------------- */
  let tokenNames = [];
  function applyTokens(t) {
    for (const n of tokenNames) root.style.removeProperty(n);
    tokenNames = [];
    for (const [k, v] of Object.entries(t || {})) {
      if (typeof v !== "string" && typeof v !== "number") continue;
      const name = k.startsWith("--") ? k : "--" + k;
      if (!/^--[a-z0-9-]+$/i.test(name)) continue;
      root.style.setProperty(name, String(v));
      tokenNames.push(name);
    }
    onAccent();
  }
  function onAccent() {
    try {
      const probe = h("span", { style: "color:" + (getComputedStyle(root).getPropertyValue("--c-accent").trim() || "#b4531f") + ";position:absolute;visibility:hidden" });
      ctx.root.append(probe);
      const m = getComputedStyle(probe).color.match(/[\d.]+/g) || [180, 83, 31];
      probe.remove();
      const lin = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
      const L = 0.2126 * lin(+m[0]) + 0.7152 * lin(+m[1]) + 0.0722 * lin(+m[2]);
      const white = 1.05 / (L + 0.05), dark = (L + 0.05) / (0.007 + 0.05);
      root.style.setProperty("--on-accent", dark > white ? "#1a1410" : "#ffffff");
    } catch (_) { /* keep the default */ }
  }
  function setTheme(dark, tokens, reduce) {
    root.dataset.theme = dark ? "dark" : "light";
    if (reduce != null) el.app.dataset.motion = reduce ? "reduce" : "";
    applyTokens(tokens);
  }

  /* ---------------- derived view data ---------------- */
  const hasDoc = () => Object.keys(S.doc || {}).length > 0;
  const readable = () => !hasDoc() || (typeof S.doc.stage === "string" && Array.isArray(S.doc.steps));
  const isStarting = () => !hasDoc();
  const hasSettings = () => !!(S.doc && S.doc.settings && S.doc.settings.output);
  const steps = () => (isStarting() ? STAGE_IDS.map((id, i) => ({ id, label: STAGE_LABEL[id], state: i === 0 ? "current" : "todo" })) : arr(S.doc.steps));
  const gate = () => (S.doc && S.doc.gate) || null;
  const stageIdx = () => STAGE_IDS.indexOf(S.doc.stage);
  const sceneIds = () => new Set(arr(S.doc.boards).flatMap((b) => arr(b.scenes).map((s) => String(s.id))));
  const captureNeeded = () => { const d = S.doc; return d.stage === "keyframes" && !gate() && d.summary && d.summary.badge === "waiting" ? arr(d.assets).filter((x) => (x.kind === "recording" || x.kind === "screenshot") && (x.state === "mock" || x.state === "todo")).length : 0; };
  const gTab = () => (captureNeeded() ? "assets" : STAGE_TAB[(gate() && gate().stage) || S.doc.stage]);
  const gateKey = () => (S.doc.stage || "") + "|" + (gate() ? gate().gate + "|" + gate().kind : "-");

  const curBoard = () => { const bs = arr(S.doc.boards); if (S.boardIdx >= bs.length) S.boardIdx = 0; return bs[S.boardIdx] || null; };
  const storyIds = () => new Set(arr((curBoard() || {}).scenes).map((x) => String(x.id)));
  const fileBad = PF.fileBad;
  const missingAll = () => PF.missingAll(S.doc);

  /* ONE derived model for the selected story: the asset rows used in it plus its keyframes still to make.
     Buckets are mutually exclusive (ready | mock | todo | missing), so tab badge, counter row and filters all read the same numbers. */
  const model = () => PF.model(S.doc, curBoard());

  function tabList() {
    const d = S.doc, t = [], b = curBoard();
    if (arr(d.scripts).length) t.push({ id: "scripts", label: "Scripts", n: d.scripts.length });
    if (b) t.push({ id: "storyboard", label: "Storyboard", n: arr(b.scenes).length });
    if (arr(d.assets).length) { const m = model(); t.push({ id: "assets", label: "Assets", n: m.total, title: "Assets: " + m.total + " rows for this story (" + m.n.ready + " ready, " + m.n.mock + " mock, " + m.n.todo + " to make" + (m.n.missing ? ", " + m.n.missing + " missing" : "") + ")" }); }
    if (arr(d.docs).length || (arr(d.scripts).length && stageIdx() >= STAGE_IDS.indexOf("scripts"))) t.push({ id: "plan", label: "Plan", n: arr(d.docs).length || null, title: "Plan: full scripts and production documents. Ask the agent to add more." });
    if (arr(d.drafts).length || arr(d.finals).length || arr(d.rounds).length || stageIdx() >= STAGE_IDS.indexOf("drafts")) t.push({ id: "draft", label: "Drafts", n: arr(d.drafts).length + arr(d.finals).length || null });
    return t;
  }

  /* "01-08, 11 (+2)": numeric ids collapse to ranges, long lists keep three groups */
  function sceneRange(ids) {
    const groups = [];
    for (const x of ids) {
      const n = /^\d+$/.test(x) ? +x : null;
      const g = groups[groups.length - 1];
      if (n != null && g && g.n != null && n === g.n + 1) { g.end = x; g.n = n; g.count++; } else groups.push({ start: x, end: x, n, count: 1 });
    }
    const tok = groups.map((g) => (g.start === g.end ? g.start : g.start + "–" + g.end));
    const hidden = groups.slice(3).reduce((a, g) => a + g.count, 0);
    return tok.slice(0, 3).join(", ") + (hidden ? " (+" + hidden + ")" : "");
  }

  /* ---------------- header ---------------- */
  function renderHeader() {
    const st = !hasDoc() ? [] : steps();
    const finished = st.length > 0 && st.every((x) => x.state === "done");
    const cur = finished ? st.length - 1 : Math.max(0, st.findIndex((x) => x.state === "current"));
    el.stepNo.textContent = finished ? "All " + st.length + " steps done" : "Step " + (cur + 1) + " of " + st.length;
    const noConn = S.noState && !hasDoc();
    if (noConn) el.stepNo.textContent = "Not connected";
    else if (isStarting()) el.stepNo.textContent = "Starting";
    el.stageName.textContent = noConn ? "Promo flow" : isStarting() ? "Promo flow" : S.doc.stage_label || STAGE_LABEL[S.doc.stage] || "Promo flow";
    const sm = S.summary || {};
    el.stateLine.textContent = noConn ? "No answer from the host yet." : S.readonly ? "Archived. Read only." : isStarting() ? "Setting up your video." : S.justSent || S.pending ? "Sent. Waiting for the agent to pick it up." : sm.status || "";
    /* Once the person has sent their answer the ball is with the agent, whatever the last summary says: never show "Your turn" with nothing left to do. */
    const sent = !!(S.pending || S.justSent || S.sending);
    const badge = noConn ? "attention" : isStarting() || (sent && sm.badge === "waiting") ? "working" : BADGE_TEXT[sm.badge] ? sm.badge : "working";
    const bt = noConn ? "Not connected" : S.readonly ? "Read only" : BADGE_TEXT[badge];
    el.badge.dataset.badge = S.readonly && !noConn ? "readonly" : badge;
    el.badgeText.textContent = bt;
    if (S.lastBadge && S.lastBadge !== bt) say("Status: " + bt);
    S.lastBadge = bt;
    const key = JSON.stringify(st);
    if (el.stepper.dataset.key !== key) {
      el.stepper.dataset.key = key;
      el.stepper.replaceChildren(...st.map((x) => h("li", { class: x.state + (x.stale && x.state === "current" ? " flag" : ""), title: x.label + (x.stale ? " (needs approval again)" : ""), "aria-current": x.state === "current" ? "step" : null },
        h("i", { class: "seg" }), h("span", { class: "lab", text: SHORT[x.id] || x.label }))));
      el.stepsList.replaceChildren(...st.map((x, i) => h("li", { class: x.state + (x.stale && x.state === "current" ? " flag" : ""), "aria-current": x.state === "current" ? "step" : null },
        h("span", { class: "mark" }, x.state === "done" ? ic("check") : x.stale ? ic("alert") : String(i + 1)), h("span", { text: x.label }), x.stale ? h("span", { class: "why", text: "Needs approval again" }) : null)));
    }
    /* While a run is on, the current segment fills with its real progress (done / total); otherwise it is solid. */
    const job = S.doc.job, p = job && job.state === "running" && job.total ? Math.min(1, (job.done || 0) / job.total) : 1;
    const curLi = el.stepper.querySelector("li.current");
    if (curLi) curLi.style.setProperty("--p", String(p));
    const c = st[cur];
    el.curLab.textContent = c ? SHORT[c.id] || c.label : "";
    el.curLab.style.setProperty("--i", String(cur));
    el.curLab.classList.toggle("right", cur >= 6);
    el.stepsBtn.replaceChildren(ic("chevron"));
    el.stepsBtn.hidden = !hasDoc();
    el.settingsBtn.hidden = !hasSettings();
    el.settingsBtn.setAttribute("aria-pressed", String(S.settingsOpen));
    el.stepsBtn.setAttribute("aria-expanded", String(S.stepsOpen));
    el.stepsList.hidden = !S.stepsOpen || !hasDoc();
    const title = clip("Promo flow: " + el.stageName.textContent, 40);
    if (title !== S.title) { S.title = title; post({ type: "title", text: title }); }
  }

  /* ---------------- working: what the agent is doing, and the history as dots ---------------- */
  const ACT_KIND = { capture: "Real app", render: "Rendering", voice: "Voices and sound", music: "Music", check: "Checks", plan: "Planning", other: "Other", milestone: "Flow step" };
  const ago = (iso) => {
    const s = Math.max(0, (Date.now() - Date.parse(iso)) / 1000);
    if (!(s >= 0)) return "";
    if (s < 60) return "just now";
    if (s < 3600) return Math.round(s / 60) + " min ago";
    return Math.floor(s / 3600) + " h " + (Math.round(s / 60) % 60) + " min ago";
  };
  const clock = (iso) => { const d = new Date(iso); return isNaN(d) ? "" : d.toTimeString().slice(0, 5); };
  const DOTS = 60, STALE_MIN = 12;
  function renderWorking() {
    const sm = S.summary || {};
    const on = hasDoc() && !isStarting() && !S.readonly && !(S.noState && !hasDoc()) && sm.badge === "working" && !jobRunning();
    el.working.hidden = !on;
    clearInterval(S.agoTimer); S.agoTimer = 0;
    if (!on) { el.working.dataset.key = ""; return; }
    const act = arr(S.doc.activity).filter((x) => x && x.text && x.at);
    const key = JSON.stringify([act.slice(-DOTS), sm.status, S.doc.stage_since]);
    if (el.working.dataset.key !== key) {
      el.working.dataset.key = key;
      const last = act[act.length - 1];
      const shown = act.slice(-DOTS);
      const dots = shown.map((x, i) => {
        const live = i === shown.length - 1 && !x.done && x.kind !== "milestone";
        return h("i", { class: "dt k-" + (ACT_KIND[x.kind] ? x.kind : "other") + (x.done ? " done" : "") + (live ? " live" : ""), title: clock(x.at) + " · " + x.text });
      });
      for (let i = shown.length; i < Math.min(DOTS, 24); i++) dots.push(h("i", { class: "dt empty", "aria-hidden": "true" }));
      const kinds = [...new Set(shown.map((x) => x.kind))].filter((k) => ACT_KIND[k]);
      const count = (k) => shown.filter((x) => x.kind === k).length;
      const feed = act.filter((x) => x.kind !== "milestone").slice(-3).reverse();
      el.working.replaceChildren(...[
        h("div", { class: "wk-head" }, h("i", { class: "wk-pulse", "aria-hidden": "true" }),
          h("div", { class: "wk-main" },
            h("div", { class: "wk-now", text: last ? last.text : "Starting to work on this step" }),
            h("div", { class: "wk-sub", id: "wkAgo" }))),
        act.length ? h("div", { class: "wk-map", role: "img", "aria-label": act.length + " steps so far. Hover a dot for what it was." }, dots) : null,
        kinds.length ? h("div", { class: "wk-legend" }, kinds.map((k) => h("span", null, h("i", { class: "dt k-" + k + " done" }), ACT_KIND[k] + " " + count(k)))) : null,
        feed.length ? h("ul", { class: "wk-feed" }, feed.map((x) => h("li", null, h("span", { class: "t", text: clock(x.at) }), h("i", { class: "dt k-" + (ACT_KIND[x.kind] ? x.kind : "other") + (x.done ? " done" : ""), "aria-hidden": "true" }), h("span", { text: x.text })))) : null,
        h("p", { class: "wk-note", id: "wkNote" })].filter(Boolean));       // replaceChildren turns a null into the text "null"
    }
    const tick = () => {
      const act = arr(S.doc.activity).filter((x) => x && x.at);
      const last = act[act.length - 1];
      const sub = ctx.root.getElementById("wkAgo"), note = ctx.root.getElementById("wkNote");
      if (!sub || !note) return;
      const since = S.doc.stage_since ? ago(S.doc.stage_since) : "";
      sub.textContent = (last ? "Updated " + ago(last.at) : "No update yet") + (since ? " · step started " + since : "");
      const quiet = last ? (Date.now() - Date.parse(last.at)) / 60000 : 0;
      note.textContent = quiet >= STALE_MIN ? "No update for " + Math.round(quiet) + " min. It may be on one long job. Ask the agent if you want to know." : "A fresh update appears every few minutes.";
      note.classList.toggle("warn", quiet >= STALE_MIN);
    };
    tick();
    S.agoTimer = setInterval(tick, 20000);
  }

  /* ---------------- live run: storyboard images or asset samples, each one shown the moment it lands ---------------- */
  const jobRunning = () => hasDoc() && !S.readonly && !!S.doc.job && S.doc.job.state === "running";
  const agoS = (s) => (s < 60 ? Math.round(s) + " s ago" : Math.round(s / 60) + " min ago");
  const ASSET_ICON = { music: "music", voice: "wave", sfx: "wave", recording: "film", video: "film", check: "shield", image: "image" };
  function jobTile(t, pop) {
    const x = t.item || {};
    const cls = "jb-tile " + t.type + (x.skipped ? " skip" : "") + (pop ? " pop" : "");
    /* Build steps are mostly icons (voice, music, mix): their name is the only way to tell them apart. Frames carry their scene in the picture. */
    const cap = () => (S.doc.job.kind === "build" ? h("span", { class: "jb-cap", "aria-hidden": "true", text: x.label }) : "");
    if (t.type === "queued") return h("div", { class: cls, "aria-hidden": "true" });
    if (t.type === "active") return h("div", { class: cls, title: "Making now: " + x.label }, h("i", { class: "spin", "aria-hidden": "true" }), cap());
    if (t.type === "failed") return h("div", { class: cls, title: x.label + ": couldn't be made" }, ic("alert"), cap());
    const r = mref(x.path);
    const slot = h("span", { class: "jb-slot" });
    const name = x.label + (x.skipped ? " (unchanged)" : "");
    /* A frame opens its scene, a sample the Assets tab; a build step has nowhere of its own to go, so it is only a picture. */
    const b = x.story ? h("button", { type: "button", class: cls, title: name, "aria-label": "Open " + name, onclick: () => goScene(x.story, x.scene) }, slot)
      : x.asset_kind && S.doc.job.kind === "samples" ? h("button", { type: "button", class: cls, title: name, "aria-label": "Open " + name, onclick: () => pickTab("assets") }, slot)
      : h("div", { class: cls, title: name, role: "img", "aria-label": name }, slot, cap());
    if (r && !r.error && /^image\//.test(r.mime || "image/")) lazyInto(slot, r, (u) => h("img", { src: u, alt: "", draggable: "false" }), { compact: true });
    else slot.replaceChildren(ic(ASSET_ICON[x.asset_kind] || "image"));
    return b;
  }
  function jobParts() {
    if (S.jobEls) return S.jobEls;
    const J = { icon: h("span", { class: "jb-icon", "aria-hidden": "true" }), title: h("div", { class: "jb-title" }), clock: h("div", { class: "jb-sub" }),
      done: h("b"), total: h("span"), fill: h("i"), now: h("p", { class: "jb-now" }), grid: h("div", { class: "jb-grid" }), more: h("p", { class: "jb-more" }),
      note: h("p", { class: "jb-note" }), act: h("div", { class: "jb-act" }), tiles: new Map() };
    J.bar = h("div", { class: "jb-bar", role: "progressbar", "aria-valuemin": "0" }, J.fill);
    el.job.replaceChildren(h("div", { class: "jb-head" }, J.icon, h("div", { class: "jb-main" }, J.title, J.clock), h("div", { class: "jb-count", "aria-hidden": "true" }, J.done, J.total)),
      J.bar, J.now, J.grid, J.more, J.note, J.act);
    S.jobEls = J;
    return J;
  }
  function renderJob() {
    const v = hasDoc() && !isStarting() && !S.readonly ? PF.jobView(S.doc.job, Date.now()) : null;
    clearInterval(S.jobTimer); S.jobTimer = 0;
    el.job.hidden = !v;
    if (!v) { el.job.replaceChildren(); S.jobEls = null; S.jobSaid = null; return; }
    const J = jobParts();
    const job = S.doc.job;
    const key = JSON.stringify([job.state, job.done, job.failed, job.total, arr(job.items).length, v.tiles.map((t) => t.type + (t.item ? t.item.id : t.n)), S.offline, !!S.pending, !!S.justSent, !!S.sending]);
    if (J.key !== key) {
      const animate = J.tiles.size > 0;
      const next = new Map();
      J.grid.replaceChildren(...v.tiles.map((t) => {
        const k = t.type + ":" + (t.item ? t.item.id : "q" + t.n);
        const n = J.tiles.get(k) || jobTile(t, animate && (t.type === "item" || t.type === "failed"));
        next.set(k, n);
        return n;
      }));
      J.tiles = next;
      if (J.done.textContent && J.done.textContent !== String(v.done)) { J.done.classList.remove("bump"); void J.done.offsetWidth; J.done.classList.add("bump"); }
      J.done.textContent = String(v.done);
      J.total.textContent = "/ " + v.total;
      J.title.textContent = v.title;
      J.fill.style.transform = "scaleX(" + v.pct + ")";
      J.bar.setAttribute("aria-label", v.title);
      J.bar.setAttribute("aria-valuemax", String(v.total));
      J.bar.setAttribute("aria-valuenow", String(v.done + v.failed));
      J.bar.setAttribute("aria-valuetext", v.done + " of " + v.total + " " + v.many + " made" + (v.failed ? ", " + v.failed + " failed" : ""));
      J.now.replaceChildren(...(v.state === "running" && v.active.length && !v.waiting ? [h("b", { text: "Making now: " }), v.active.map((x) => x.label).join(", ")] : []));
      const more = [v.earlier ? v.earlier + " earlier " + (v.earlier === 1 ? v.one : v.many) + " not shown" : "", v.moreQueued ? v.moreQueued + " more queued" : ""].filter(Boolean);
      J.more.textContent = more.length ? more.join(" · ") + "." : "";
      const blocked = S.readonly || S.offline || !!S.pending || !!S.justSent || !!S.sending;
      J.act.replaceChildren(...(v.state === "stopped" && v.resume ? [h("button", { class: "load", type: "button", disabled: blocked, text: "Ask the agent to carry on",
        onclick: () => send("resume", { what: v.title.toLowerCase() + ": " + job.label.toLowerCase(), command: v.resume }) })] : []));
      J.key = key;
      const said = v.state + v.done;
      if (S.jobSaid != null && S.jobSaid !== said && (v.state !== "running" || v.done % 5 === 0)) say(v.title + ": " + v.done + " of " + v.total + " " + v.many + " made.");
      S.jobSaid = said;
    }
    const tick = () => {
      const w = PF.jobView(S.doc.job, Date.now());
      if (!w) return;
      el.job.dataset.state = w.waiting ? "waiting" : w.stale ? "stale" : w.state;
      J.icon.replaceChildren(w.alive && !w.waiting ? h("i", { class: "jb-ring" }) : ic(w.state === "done" ? "check" : w.waiting ? "clock" : "alert"));
      J.clock.textContent = w.waiting ? "Queued " + PF.clockS(w.elapsed) + " · " + w.waiting
        : w.stale ? "No sign of life for " + Math.round(w.staleFor / 60) + " min"
        : w.state === "running" ? "Running " + PF.clockS(w.elapsed) + " · " + (w.done + w.failed ? "last " + w.one + " " + agoS(w.quiet) : "first " + w.one + " on its way") + (w.eta != null ? " · " + PF.aboutS(w.eta) + " left" : "")
        : w.state === "done" ? "Took " + PF.clockS(w.elapsed) : "Ran " + PF.clockS(w.elapsed) + ", then ended before it finished.";
      const cur = w.active[0] ? w.active[0].label : "the current " + w.one;
      J.note.textContent = w.stale ? "The run stopped checking in. It may have been stopped. Ask the agent in the chat."
        : w.slow ? cur + " has been going for " + Math.round(w.quiet / 60) + " min. Long ones take a while; the run is still checking in." : "";
      J.note.classList.toggle("warn", w.stale);
    };
    tick();
    if (v.state === "running") S.jobTimer = setInterval(tick, 1000);
  }

  /* ---------------- banners ---------------- */
  function bannerList() {
    const out = [];
    const tabs = tabList();
    if (S.offline) out.push({ id: "off", warn: true, icon: "offline", text: "You're offline. This is the last version we have, and sending is paused." });
    for (const x of arr(S.doc.stale_steps)) {
      const tb = STAGE_TAB[x.id];
      out.push({ id: "stale-" + x.id, warn: true, icon: "alert", text: "Approved earlier, but " + x.label + " changed since. Needs your approval again.",
        acts: tb && tb !== S.tab && tabs.some((t) => t.id === tb) ? [["Open " + x.label, "open:" + tb]] : null });
    }
    if (S.stash) out.push({ id: "stash", icon: "send", text: "Unsent note from " + S.stash.label + ":", snip: clip(S.stash.text, 80), acts: [["Restore", "restore"], ["Discard", "discard"]] });
    if (S.stale) out.push({ id: "edit", icon: "refresh", bold: "This updated while you were editing. ", text: S.stale.changedGate ? "The step changed, so please look again before you send." : "Your note is kept.", acts: [[S.stale.changedGate ? "Review" : "Dismiss", "stale"]] });
    if (S.updated) out.push({ id: "upd", icon: "refresh", text: "This changed since you last looked. Review before approving.", acts: [["Got it", "updated"]] });
    if (!readable()) out.push({ id: "bad", warn: true, icon: "alert", text: "This update has an unexpected shape, so it can't be shown. Ask the agent to publish it again." });
    return out;
  }
  function bannerAct(a) {
    if (a.startsWith("open:")) { S.tab = a.slice(5); S.userTab = true; S.updated = false; render(); el.sc.scrollTop = 0; return; }
    if (a === "restore") { const t = S.stash.text; S.stash = null; S.compose = true; el.note.value = t; render(); el.note.focus(); return; }
    if (a === "discard") S.stash = null;
    else if (a === "stale") S.stale = null;
    else if (a === "updated") S.updated = false;
    render();
  }
  function renderBanners() {
    const list = bannerList();
    const key = JSON.stringify(list);
    if (el.banners.dataset.key === key) return;
    el.banners.dataset.key = key;
    const ae = ctx.root.activeElement;
    const fk = ae && el.banners.contains(ae) ? ae.dataset.k : null;
    el.banners.replaceChildren(...list.map((b) => h("div", { class: "banner" + (b.warn ? " warn" : ""), role: b.warn ? "alert" : "status" }, ic(b.icon),
      h("div", { class: "grow" }, b.bold ? h("b", { text: b.bold }) : null, b.text, b.snip ? h("span", { class: "snip", text: b.snip }) : null),
      b.acts ? h("div", { class: "acts" }, b.acts.map(([label, a]) => h("button", { class: "link", type: "button", "data-k": "b-" + b.id + "-" + a, text: label, onclick: () => bannerAct(a) }))) : null)));
    if (fk) { const n = el.banners.querySelector('[data-k="' + fk + '"]'); if (n) n.focus({ preventScroll: true }); }
  }

  /* ---------------- tabs ---------------- */
  function renderTabs(list) {
    const show = list.length > 1;
    el.tabs.hidden = !show;
    el.sc.dataset.tabs = show ? "1" : "";
    const cur = gTab(), waiting = !!gate() && !S.readonly;
    const key = list.map((t) => t.id + t.n).join() + "|" + cur + waiting + S.readonly;
    if (el.tabs.dataset.key !== key) {
      el.tabs.dataset.key = key;
      el.tabs.style.position = "sticky";
      el.tabs.replaceChildren(...list.map((t) => h("button", { class: "tab", type: "button", role: "tab", id: "tab-" + t.id, "data-tab": t.id, "aria-controls": "content", onclick: () => pickTab(t.id), onkeydown: tabKey },
        t.label, t.n != null ? h("span", { class: "n", text: String(t.n), title: t.n + " " + ({ scripts: "scripts", storyboard: "scenes", assets: "assets", draft: "videos", plan: "documents" }[t.id] || "items") }) : null, t.id === cur && !S.readonly ? h("i", { class: "now" + (waiting ? "" : " idle"), role: "img", title: waiting ? "Waiting on you" : "Not waiting on you", "aria-label": waiting ? "Waiting on you" : "Not waiting on you" }) : null)));
      for (const b of el.tabs.children) { const t = list.find((x) => x.id === b.dataset.tab); b.title = S.readonly && b.dataset.tab === cur ? "Archived" : t && t.title ? t.title : ""; }
      if (!el.tabs.dataset.fade) { el.tabs.dataset.fade = "1"; fadeX(el.tabs); }
    }
    let sel = null;
    for (const b of el.tabs.children) { const on = b.dataset.tab === S.tab; b.setAttribute("aria-selected", String(on)); b.tabIndex = on ? 0 : -1; if (on) sel = b; }
    if (sel) revealX(el.tabs, sel);
  }
  function tabKey(e) {
    const bs = [...el.tabs.children];
    const i = bs.indexOf(e.currentTarget);
    let j = null;
    if (e.key === "ArrowRight") j = (i + 1) % bs.length;
    else if (e.key === "ArrowLeft") j = (i - 1 + bs.length) % bs.length;
    else if (e.key === "Home") j = 0;
    else if (e.key === "End") j = bs.length - 1;
    if (j == null) return;
    e.preventDefault();
    pickTab(bs[j].dataset.tab);
    bs[j].focus();
  }
  function pickTab(id) { if (S.tab === id && !S.reader && !S.settingsOpen) return; S.reader = null; S.settingsOpen = false; S.tab = id; S.userTab = true; S.updated = false; render(); el.sc.scrollTop = 0; }

  /* ---------------- content ---------------- */
  let lastSig = "", tick = 0;
  function sliceFor(tab, withChecks) {
    const d = S.doc;
    const common = withChecks ? [d.stage, d.checks, d.gate && d.gate.kind, d.gate && d.gate.picks_max, d.stale_steps, d.stage_since] : [d.stage];
    if (S.reader) { const it = findReadable(S.reader.key); return [it && [it.title, it.words, it.body, it.updated]]; }
    if (tab === "scripts") return [d.scripts, d.intent, common];
    if (tab === "storyboard") return [d.boards, d.stage === "confirm" ? d.assets.map((a) => [a.kind, a.source, a.scenes]) : 0, d.stage === "keyframes" ? d.to_make : 0, common];
    if (tab === "assets") return [d.assets, d.to_make, d.boards, common];
    if (tab === "draft") return [d.drafts, d.finals, d.rounds, d.rounds_used, d.rounds_max, d.share, common];
    if (tab === "plan") return [d.docs, d.scripts, d.boards && d.boards.map((b) => b.id), common];
    return [d.intent, d.style, common];
  }
  function renderContent(list, force) {
    let sig;
    if (S.reader && !findReadable(S.reader.key)) S.reader = null;
    if (S.noState && !hasDoc()) sig = "noconn";
    else if (!readable()) sig = "bad";
    else if (isStarting()) sig = "start";
    else if (S.settingsOpen) sig = "settings|" + JSON.stringify([S.doc.settings, S.readonly, S.offline, !!S.pending, !!S.justSent, !!S.sending, S.err]);
    else if (!list.length) sig = "overview|" + JSON.stringify([sliceFor(null, true), gate(), S.style, S.readonly, !!S.pending]);
    else if (S.reader) sig = "reader|" + S.reader.key + "|" + JSON.stringify(sliceFor(S.tab, false)) + S.readonly;
    else sig = S.tab + "|" + JSON.stringify(sliceFor(S.tab, true)) + "|" + [...S.picks].join() + "|" + S.style + S.boardIdx + S.draftSel + S.earlier + S.filter + S.readonly + !!S.pending + !!S.justSent + !!S.sending + S.sbView + S.docGroup + S.docQ + (S.compose ? S.composeKind : "") + jobRunning();
    if (!force && sig === lastSig) return;
    const keepScroll = sig.split("|")[0] === lastSig.split("|")[0] ? el.sc.scrollTop : 0;
    lastSig = sig;
    const ae = ctx.root.activeElement;
    const fk = ae && el.content.contains(ae) ? ae.dataset.k : null;
    releaseHeavy();
    S.scrollHook = null;
    let view;
    if (S.noState && !hasDoc()) view = viewNoConn();
    else if (!readable()) view = viewBad();
    else if (isStarting()) view = viewStarting();
    else if (S.settingsOpen) view = viewSettings();
    else if (!list.length) view = viewOverview();
    else if (S.reader) view = viewReader();
    else view = ({ scripts: viewScripts, storyboard: viewStoryboard, assets: viewAssets, draft: viewDraft, plan: viewPlan }[S.tab] || viewOverview)();
    el.content.replaceChildren(view);
    el.sc.scrollTop = keepScroll;
    el.content.setAttribute("aria-labelledby", S.tab ? "tab-" + S.tab : "");
    el.content.setAttribute("role", S.tab ? "tabpanel" : "region");
    el.content.setAttribute("aria-label", S.tab ? "" : "Overview");
    if (fk) { const n = el.content.querySelector('[data-k="' + fk + '"]'); if (n) n.focus({ preventScroll: true }); }
    if (S.scrollHook) S.scrollHook();
  }
  el.sc.addEventListener("scroll", () => { if (S.scrollHook) { cancelAnimationFrame(S.raf); S.raf = requestAnimationFrame(S.scrollHook); } }, { passive: true });

  function checksLine() {
    const cs = arr(S.doc.checks);
    if (!cs.length) return null;
    const done = cs.filter((c) => c.ok).length;
    const li = (c) => h("li", { class: c.ok ? "ok" : "" }, h("span", { class: "tick" }, c.ok ? ic("check") : null), h("span", { text: c.text }));
    if (cs.length <= 3) return h("div", { class: "checks inline" }, h("p", { class: "ck-h", text: "Before this step can finish" }), h("ul", null, cs.map(li)));
    const dt = h("details", { class: "checks", open: S.checksOpen, ontoggle: () => { S.checksOpen = dt.open; } }, h("summary", null, h("span", { text: "Before this step can finish: " + done + " of " + cs.length }), ic("chevron")), h("ul", null, cs.map(li)));
    return dt;
  }
  const showMore = (text, max, cls) => {
    const p = h("p", { class: "clamp " + (cls || ""), text });
    const b = h("button", { class: "more", type: "button", text: "Show more", "aria-expanded": "false", hidden: true, onclick: () => { const o = p.classList.toggle("open"); b.textContent = o ? "Show less" : "Show more"; b.setAttribute("aria-expanded", String(o)); } });
    const w = h("div", null, p, b);
    requestAnimationFrame(() => { if (p.scrollHeight > p.clientHeight + 1) b.hidden = false; });
    return w;
  };
  const linkBtn = (u) => h("button", { type: "button", title: u, onclick: () => { if (/^https:\/\//i.test(u)) post({ type: "open-url", url: u }); } }, h("span", { text: host(u) }), ic("link"));

  function viewBad() { return h("div", { class: "pane empty" }, h("div", { class: "ring" }, ic("alert")), h("h2", { text: "Can't read this update" }), h("p", { text: "The agent published something this view doesn't understand. Ask it to run the snapshot again and republish." })); }
  function viewNoConn() { return h("div", { class: "pane empty fill", role: "alert" }, h("div", { class: "ring" }, ic("offline")), h("h2", { text: "Can't reach the host" }), h("p", { text: "Nothing arrived yet. Check the connection, then try again." }), h("button", { class: "btn primary", type: "button", text: "Retry", onclick: () => { S.noState = false; startBootTimer(); render(true); post({ type: "ready" }); } })); }
  function viewStarting() {
    return h("div", { class: "pane empty fill prep", role: "status" }, h("div", { class: "ring" }, ic("spark")),
      h("h2", null, "Preparing", h("span", { class: "dots", "aria-hidden": "true" }, h("i", { text: "." }), h("i", { text: "." }), h("i", { text: "." }))),
      h("p", { text: "The plan appears here as soon as it is ready." }));
  }

  /* ---------------- settings: where videos are saved ---------------- */
  const OUTPUT_CHOICES = [
    { id: "home", title: "Your home folder", note: "Out of your repos, one folder for each project." },
    { id: "repo", title: "Inside this project", note: "A promo-reel folder in the repo you are working in." },
    { id: "custom", title: "A folder you choose", note: "For an external drive, or anywhere else." },
    { id: "default", title: "Where promo-reel keeps them", note: "The folder inside promo-reel itself. This is the default." },
  ];
  function openSettings() {
    const o = S.doc.settings.output;
    S.settingsOpen = true; S.err = ""; S.setSel = o.mode; S.setText = o.mode === "custom" ? o.template : "";
    render(true);
    el.sc.scrollTop = 0;
    const t = el.content.querySelector('[data-k="settings-title"]');
    if (t) t.focus({ preventScroll: true });
  }
  function closeSettings() { S.settingsOpen = false; render(true); el.settingsBtn.focus(); }
  el.settingsBtn.addEventListener("click", () => (S.settingsOpen ? closeSettings() : openSettings()));

  function viewSettings() {
    const d = S.doc.settings, o = d.output;
    const locked = S.readonly || o.locked;
    const waiting = !!(S.pending || S.justSent || S.sending);
    const radios = {};
    const field = h("input", { id: "where", type: "text", maxlength: "300", value: S.setText, disabled: locked, placeholder: "/Volumes/My Drive/promo-reel/{project}/{slug}", spellcheck: "false", autocomplete: "off", "data-k": "settings-field",
      oninput: (e) => { S.setText = e.target.value; S.setSel = "custom"; radios.custom.checked = true; update(); } });
    const problem = h("p", { class: "warnline", role: "alert", hidden: true }, ic("alert"), h("span"));
    const next = h("code", { class: "set-path", "aria-live": "polite" });
    const save = h("button", { class: "btn primary", type: "button", onclick: () => { if (!save.disabled) send("settings", { output: S.setSel === "custom" ? S.setText.trim() : S.setSel }); } });
    function update() {
      const custom = S.setSel === "custom";
      const bad = custom && S.setText.trim() ? PF.outputProblem(S.setText) : "";
      next.textContent = custom ? (S.setText.trim() && !bad ? PF.previewOutput(S.setText, o) : "") : o.presets[S.setSel].example;
      problem.hidden = !bad;
      problem.lastChild.textContent = bad;
      const dirty = PF.outputDirty(o, S.setSel, S.setText);
      save.disabled = locked || S.offline || waiting || !dirty || (custom && !!PF.outputProblem(S.setText));
      save.textContent = !dirty ? "Saved" : waiting ? "Sent to the agent" : "Save this folder";
    }
    const cards = OUTPUT_CHOICES.map((c) => {
      radios[c.id] = h("input", { type: "radio", name: "where", value: c.id, checked: S.setSel === c.id, disabled: locked, onchange: () => { S.setSel = c.id; update(); if (c.id === "custom") field.focus(); } });
      return h("label", { class: "card choice radio" }, radios[c.id], h("div", { class: "row" }, h("span", { class: "box" }, ic("check")),
        h("div", { class: "body" }, h("div", { class: "t" }, h("b", { text: c.title })), h("p", { class: "logline", text: c.note }),
          c.id === "custom" ? null : h("code", { class: "set-path", text: o.presets[c.id].example }))));
    });
    const box = h("div", { class: "stack", onkeydown: (e) => { if (e.key === "Escape") { e.preventDefault(); closeSettings(); } } },
      h("div", null, h("h2", { class: "h2", text: "Where files are saved", tabindex: "-1", "data-k": "settings-title" }),
        h("p", { class: "set-sub", text: "Every new video gets its own folder here: scripts, storyboards, recordings and renders. Videos you already started stay where they are." })),
      d.saved_in ? h("div", null, h("p", { class: "set-label", text: "This video is in" }), h("code", { class: "set-path", text: d.saved_in })) : null,
      o.available ? null : h("p", { class: "warnline", role: "alert" }, ic("alert"), h("span", { text: "The saved folder can't be reached right now. If it is on a drive, plug it in, or pick another folder." })),
      o.locked ? h("p", { class: "set-sub", text: "This computer sets the folder itself (PROMO_PROJECTS), so it can't be changed here." }) : null,
      h("div", { class: "choices", role: "radiogroup", "aria-label": "Where to save new videos" }, cards),
      h("div", { class: "own" }, h("label", { for: "where", text: "Your folder" }), field,
        h("p", { class: "set-sub", text: "{project} is the name of the repo you work in. {slug} is the video's short name; it is added at the end if you leave it out." })),
      problem,
      S.err ? h("p", { class: "warnline", role: "alert" }, ic("alert"), h("span", { text: S.err })) : null,
      h("div", null, h("p", { class: "set-label", text: "The next video goes to" }), next),
      h("div", { class: "set-actions" }, h("button", { class: "btn ghost", type: "button", text: "Close", onclick: closeSettings }), save));
    update();
    return h("div", { class: "pane" }, box);
  }

  /* A small drawn sample of each look, so the choice is not just a name. It is a hint of the style, not a frame of the video. */
  function styleArt(label) {
    const k = /hero/i.test(label) ? "hero" : /dialogue/i.test(label) ? "dialogue" : /horizon/i.test(label) ? "horizon" : /anime|kinetic/i.test(label) ? "kinetic" : "own";
    const inner = { hero: [h("i", { class: "win" }), h("i", { class: "pill" })], dialogue: [h("i", { class: "who a" }), h("i", { class: "who b" }), h("i", { class: "bub" })],
      horizon: [h("i", { class: "sun" }), h("i", { class: "hz" }), h("em", { text: "One line" })], kinetic: [h("i", { class: "ray" }), h("em", { text: "BOLD" })], own: [ic("film")] }[k];
    return h("div", { class: "sty sty-" + k, "aria-hidden": "true" }, ...inner);
  }
  function viewOverview() {
    const d = S.doc, g = gate();
    const box = h("div", { class: "stack" });
    /* The request is the brief: a quote card, dated from the first flow entry while the flow is still at its first step. */
    const asked = d.stage === "discover" && d.stage_since ? ago(d.stage_since) : "";
    box.append(h("div", { class: "card req" }, h("span", { class: "req-q", "aria-hidden": "true", text: "“" }), h("div", { class: "req-body" }, h("div", { class: "quote" }, showMore(d.intent || "", 280)),
      h("div", { class: "req-meta", text: "Your request" + (asked ? " · " + asked : "") }))));
    if (g && g.kind === "style" && !S.readonly) {
      /* Asked again (a style is on file, references are not): the style they chose stays selected, so one click answers the reference question. */
      if (!S.style && !S.ownStyle.trim() && d.style && d.style.style) S.style = d.style.style;
      box.append(h("div", null, h("h2", { class: "h2", text: "Pick a style" }),
        h("div", { class: "choices styles", role: "radiogroup", "aria-label": "Style", style: "margin-top:10px" }, arr(g.options).map((o) => {
          const th = o.thumb && mref(o.thumb);
          const tslot = th && !th.error ? h("div", { class: "thumb", style: "position:relative" }) : styleArt(o.label);
          if (th && !th.error) lazyInto(tslot, th, (u) => h("img", { src: u, alt: "" }), { compact: true });
          const inp = h("input", { type: "radio", name: "style", value: o.label, checked: S.style === o.label, disabled: !!S.pending, onchange: () => { S.style = o.label; S.ownStyle = ""; const oi = $("own"); if (oi) oi.value = ""; renderGate(); } });
          return h("label", { class: "card choice radio style" }, inp, h("div", { class: "row" }, h("span", { class: "box" }, ic("check")), tslot, h("div", { class: "body" }, h("div", { class: "t" }, h("b", { text: o.label })), h("p", { class: "logline", text: o.description || "" }))));
        })),
        h("div", { class: "own", style: "margin-top:12px" }, h("label", { for: "own", text: "Or describe your own style" }),
          h("input", { id: "own", type: "text", maxlength: "200", value: S.ownStyle, placeholder: "For example: slow, warm, no music", disabled: !!S.pending, oninput: (e) => {
            S.ownStyle = e.target.value;
            if (S.ownStyle.trim()) { S.style = null; for (const r of box.querySelectorAll("input[name=style]")) r.checked = false; }
            renderGate();
          }, onkeydown: (e) => { if (e.key === "Enter" && !el.btn1.disabled) el.btn1.click(); } })),
        h("div", { class: "own", style: "margin-top:10px" }, h("label", { for: "ref", text: "Add a reference link (optional)" }),
          h("input", { id: "ref", type: "url", maxlength: "300", value: S.ref, placeholder: "https://", disabled: !!S.pending, oninput: (e) => { S.ref = e.target.value; } }))));
    } else if (d.style && d.style.style) {
      const refs = arr(d.style.refs);
      box.append(h("div", null, h("h2", { class: "h2", text: "Style" }), h("div", { class: "chips", style: "margin-top:8px" }, h("span", { class: "chip accent", text: d.style.style }),
        d.style.no_refs ? h("span", { class: "chip", text: "No references" }) : null, refs.length ? h("span", { class: "chip", text: refs.length + (refs.length === 1 ? " reference" : " references") }) : null),
        refs.length ? h("div", { class: "links", style: "margin-top:8px" }, refs.map(linkBtn)) : null));
    }
    const c = checksLine();
    if (c) box.append(c);
    return h("div", { class: "pane" }, box);
  }

  /* ----- scripts ----- */
  function viewScripts() {
    const d = S.doc, g = gate();
    const pickMode = !!(g && g.kind === "pick" && !S.readonly && !S.pending && !S.justSent);
    const max = g && g.picks_max ? g.picks_max : 99;
    const box = h("div", { class: "stack" });
    const list = h("div", { class: "choices scripts" });
    for (const s of arr(d.scripts)) {
      const all = arr(s.beats), beats = all.length > 2 ? [all[0], all[all.length - 1]] : all;
      const board = arr(d.boards).find((x) => x.id === s.id);
      const strip = board && arr(board.scenes).some((x) => x.start && mref(x.start.path) && !(mref(x.start.path) || {}).error)
        ? h("div", { class: "strip", "aria-hidden": "true" }, arr(board.scenes).map((x) => tlThumb(x))) : null;
      const picked = s.picked || (!pickMode && S.sentPicks && S.sentPicks.has(s.id));
      const title = h("div", { class: "t" }, h("span", { class: "id", text: s.id }), h("b", { text: s.title }),
        picked && !pickMode ? h("span", { class: "chip ok" }, ic("check"), "Picked") : null, s.verdict ? h("span", { class: "chip", text: s.verdict }) : null);
      const read = PF.bodyOf(s).text ? h("button", { type: "button", class: "btn ghost sm read-btn", "data-k": "open-script:" + s.id, onclick: (e) => { e.preventDefault(); e.stopPropagation(); openReader("script:" + s.id); } }, ic("doc"), "Read the full script" + (s.words ? " \u00b7 " + wordsLabel(s.words) : "")) : null;
      const body = h("div", { class: "body" }, strip, title, h("div", { class: "logline" }, showMore(s.logline || "", 200, "c3")),
        read, beats.length ? h("ol", { class: "beats", "aria-label": all.length > 2 ? "Opening and closing beats" : "Beats" }, beats.map((b) => h("li", { text: b })), all.length > 2 ? h("li", { class: "more-beats", text: all.length + " beats in total" }) : null) : null);
      if (pickMode) {
        const inp = h("input", { type: "checkbox", value: s.id, checked: S.picks.has(s.id), "aria-label": s.id + ": " + s.title, onchange: () => {
          if (inp.checked) S.picks.add(s.id); else S.picks.delete(s.id);
          for (const o of list.querySelectorAll("input")) o.disabled = !o.checked && S.picks.size >= max;
          renderGate();
        }, disabled: !S.picks.has(s.id) && S.picks.size >= max });
        list.append(h("label", { class: "card choice" }, inp, h("div", { class: "row" }, h("span", { class: "box" }, ic("check")), body)));
      } else list.append(h("div", { class: "card choice static" + (picked ? " picked" : arr(d.scripts).some((o) => o.picked) ? " passed" : "") }, h("div", { class: "row" }, body)));
    }
    /* The council's note is context, not the decision: one folded row, so three script cards fit the first screen. */
    if (d.councils && d.councils.scripts) box.append(h("details", { class: "card council fold" }, h("summary", { text: "What the council said about the scripts" }), h("p", { text: d.councils.scripts })));
    if (!pickMode && d.stage === "storyboard" && !arr(d.boards).length) {
      box.append(h("div", { class: "card drawing", role: "status" }, h("div", { class: "dr-h" }, h("i", { class: "spin" }), h("b", { text: "Your storyboard is being drawn" })),
        h("p", { text: "The agent is turning your pick into scenes, each with a start and an end picture. They appear here as soon as they exist, and you approve them before anything else is made." }),
        h("div", { class: "dr-tiles", "aria-hidden": "true" }, [0, 1, 2, 3, 4].map(() => h("i", { class: "sk" })))));
    }
    box.append(list);
    const c = STAGE_TAB[d.stage] === "scripts" ? checksLine() : null;
    if (c) box.append(c);
    return h("div", { class: "pane" }, box);
  }

  /* ----- plan: scripts and production documents, read page by page ----- */
  /* Everything readable in one list: the scripts the agent wrote and the planning documents it added. */
  function readables() {
    const d = S.doc, out = [];
    for (const s of arr(d.scripts)) out.push({ src: "script", key: "script:" + s.id, id: s.id, title: s.title, kind: "script", kind_label: "Script · story " + s.id, group: "Script", words: s.words || 0, preview: s.logline, headings: arr(s.headings), body: s.body, body_note: s.body_note, story: s.id, picked: !!s.picked, updated: null });
    for (const x of arr(d.docs)) out.push({ ...x, src: "doc", key: "doc:" + x.id });
    return out;
  }
  const findReadable = (key) => readables().find((x) => x.key === key) || null;
  const GROUP_ORDER = ["Script", "Direction", "Edit", "Audio", "Capture", "Delivery", "Notes"];
  function openReader(key, page) {
    S.docOpened.add(key);
    S.reader = { key, page: page || 0, q: "", mi: null, from: S.tab, fresh: true, built: false };
    render(true);
    el.sc.scrollTop = 0;
  }
  function closeReader() {
    const from = S.reader && S.reader.from, key = S.reader && S.reader.key;
    S.reader = null;
    if (from && tabList().some((t) => t.id === from)) { S.tab = from; S.userTab = true; }
    render(true);
    const back = key && el.content.querySelector('[data-k="open-' + key + '"]');
    if (back) back.focus({ preventScroll: false });
  }
  const minutes = (w) => "~" + PF.readMinutes(w) + " min read";
  const wordsLabel = (w) => w.toLocaleString("en-US") + " words";

  function viewPlan() {
    const d = S.doc, all = readables();
    const box = h("div", { class: "stack" });
    const blocked = !canAsk();
    /* One row of requests: the documents, not the asking, own this tab. */
    const quick = h("div", { class: "ask-row", role: "group", "aria-label": "Ask the agent to add something" },
      QUICK.map(([label, text]) => h("button", { type: "button", class: "qchip", disabled: blocked, "data-k": "q-" + label, onclick: () => openRequest(text, "What should the agent add? Edit the request if you like.") }, ic("plus"), label)),
      h("button", { type: "button", class: "qchip other", disabled: blocked, "data-k": "q-other", text: "Something else…", onclick: () => openRequest("", "Say what you want the agent to add to the plan.") }));
    fadeX(quick);
    box.append(h("section", { class: "ask-card", "aria-label": "Ask the agent" },
      h("div", { class: "ask-h" }, ic("spark"), h("b", { text: "Ask the agent to add" })), quick));
    if (!all.length) {
      box.append(h("div", { class: "empty card" }, h("div", { class: "ring" }, ic("doc")), h("h2", { text: "Nothing here yet" }), h("p", { text: "Pick one of the requests above, or say what you need. Full scripts and plans show up in this tab as soon as the agent writes them." })));
      return h("div", { class: "pane" }, box);
    }
    const groups = GROUP_ORDER.filter((g) => all.some((x) => x.group === g));
    if (S.docGroup && !groups.includes(S.docGroup)) S.docGroup = null;
    const q = S.docQ.trim().toLowerCase();
    if (groups.length > 1 || all.length > 6) {
      const bar = h("div", { class: "doc-tools" });
      if (groups.length > 1) bar.append(h("div", { class: "seg-ctl wrap", role: "group", "aria-label": "Show" }, [null, ...groups].map((g) => h("button", { type: "button", "data-k": "g-" + (g || "all"), "aria-pressed": String(S.docGroup === g), onclick: () => { S.docGroup = g; render(true); } }, g || "All", h("span", { class: "n", text: String(g ? all.filter((x) => x.group === g).length : all.length) })))));
      if (all.length > 6) bar.append(h("div", { class: "find-wrap" }, ic("search"), h("input", { type: "search", class: "doc-find", "aria-label": "Search the documents", placeholder: "Search titles and summaries", value: S.docQ, "data-k": "doc-q", oninput: (e) => { S.docQ = e.target.value; clearTimeout(S.dq); S.dq = setTimeout(() => render(true), 160); } })));
      box.append(bar);
    }
    const shown = all.filter((x) => (!S.docGroup || x.group === S.docGroup) && (!q || ((x.title || "") + " " + (x.summary || "") + " " + (x.preview || "") + " " + (x.kind_label || "")).toLowerCase().includes(q)));
    if (!shown.length) box.append(h("p", { class: "muted", role: "status", text: "No document matches." }));
    for (const g of groups) {
      const inG = shown.filter((x) => x.group === g);
      if (!inG.length) continue;
      box.append(h("section", { class: "doc-group", "aria-label": g }, secH(g, inG.length), h("div", { class: "doc-list" }, inG.map(docCard))));
    }
    return h("div", { class: "pane" }, box);
  }
  /* One quiet heading style for every section of a page: small, muted, with the count beside it. */
  function secH(text, n, extra) { return h("h3", { class: "sec-h" }, h("span", { text }), n != null ? h("span", { class: "n", text: String(n) }) : null, extra || null); }
  function docCard(x) {
    const b = PF.bodyOf(x), bad = !!b.error;
    const fresh = S.docBase && !S.docBase.has(x.key) && !S.docOpened.has(x.key);
    const meta = [x.kind_label, x.words ? wordsLabel(x.words) : null, x.words ? minutes(x.words) : null].filter(Boolean).join(" · ");
    return h("button", { type: "button", class: "card doc-card" + (bad ? " bad" : ""), "data-k": "open-" + x.key, disabled: bad, "aria-label": "Read " + x.title + (fresh ? " (new)" : ""), onclick: () => openReader(x.key) },
      h("span", { class: "gl" }, ic(KIND_ICON[x.kind] || "doc")),
      h("span", { class: "dc-body" },
        h("span", { class: "dc-t" }, h("b", { text: x.title }), fresh ? h("span", { class: "chip new", text: "New" }) : null, x.picked ? h("span", { class: "chip ok" }, ic("check"), "Picked") : null, x.story && x.src === "doc" ? h("span", { class: "chip", text: "Story " + x.story }) : null),
        h("span", { class: "dc-m", text: meta + (x.updated ? " · " + ago(x.updated) : "") }),
        bad ? h("span", { class: "dc-p err", text: b.error }) : (x.summary || x.preview) ? h("span", { class: "dc-p", text: clip(x.summary || x.preview, 220) }) : null),
      h("span", { class: "dc-go" }, ic("right")));
  }

  /* markdown -> DOM (never innerHTML); `q` highlights the search term */
  function inlineNodes(text, q) {
    const mark = (t) => PF.markSplit(t, q).map((p) => (p.hit ? h("mark", { text: p.text }) : p.text));
    const out = [];
    String(text).split("\n").forEach((line, i) => {
      if (i) out.push(h("br"));
      for (const t of PF.inline(line)) {
        if (t.t === "b") out.push(h("strong", null, mark(t.text)));
        else if (t.t === "i") out.push(h("em", null, mark(t.text)));
        else if (t.t === "code") out.push(h("code", null, t.text));
        else if (t.t === "link") out.push(h("button", { type: "button", class: "lnk", title: t.url, onclick: () => { if (/^https:\/\//i.test(t.url)) post({ type: "open-url", url: t.url }); } }, mark(t.text)));
        else out.push(...mark(t.text));
      }
    });
    return out;
  }
  function blockNode(b, q) {
    if (b.t === "h") return h("h" + Math.min(b.level + 1, 5), { class: "md-h md-h" + b.level }, inlineNodes(b.text, q));
    if (b.t === "p") return h("p", { class: "md-p" }, inlineNodes(b.text, q));
    if (b.t === "quote") return h("blockquote", { class: "md-q" }, inlineNodes(b.text, q));
    if (b.t === "hr") return h("hr", { class: "md-hr" });
    if (b.t === "code") return h("pre", { class: "md-code", tabindex: "0" }, h("code", { text: b.text }));
    if (b.t === "list") {
      const count = {};
      return h("div", { class: "md-list", role: "list" }, b.items.map((it) => {
        let mk;
        if (it.check != null) mk = h("span", { class: "md-box" + (it.check ? " on" : ""), role: "img", "aria-label": it.check ? "Done" : "Not done" }, it.check ? ic("check") : null);
        else if (it.ordered) { count[it.depth] = (count[it.depth] || 0) + 1; Object.keys(count).forEach((k) => { if (+k > it.depth) delete count[k]; }); mk = h("span", { class: "md-n", text: count[it.depth] + "." }); }
        else { Object.keys(count).forEach((k) => { if (+k >= it.depth) delete count[k]; }); mk = h("span", { class: "md-dot", "aria-hidden": "true" }); }
        return h("div", { class: "md-li", role: "listitem", style: "margin-left:" + it.depth * 18 + "px" }, mk, h("span", { class: "md-lt" + (it.check ? " done" : "") }, inlineNodes(it.text, q)));
      }));
    }
    if (b.t === "table") {
      return h("div", { class: "md-tbl", tabindex: "0", role: "region", "aria-label": "Table" }, h("table", null,
        h("thead", null, h("tr", null, b.head.map((c) => h("th", { scope: "col" }, inlineNodes(c, q))))),
        h("tbody", null, b.rows.map((r) => h("tr", null, b.head.map((_, i) => h("td", null, inlineNodes(r[i] || "", q))))))));
    }
    return null;
  }

  function viewReader() {
    const R = S.reader, it = findReadable(R.key);
    const b = PF.bodyOf(it);
    /* A refresh (the agent added pages, the step moved on) rebuilds this view: keep the reader's place and the focus in the find box. */
    const keepY = R.built ? el.sc.scrollTop : null;
    const ae = ctx.root.activeElement;
    const keepFocus = R.built && ae && el.content.contains(ae) ? ae.dataset.k || null : null;
    R.built = true;
    const back = h("button", { type: "button", class: "rd-back", "data-k": "rd-back", onclick: closeReader }, ic("left"), h("span", { text: ({ plan: "Plan", scripts: "Scripts", storyboard: "Storyboard" })[R.from] || "Back" }));
    const meta = [it.kind_label, it.words ? wordsLabel(it.words) : null, it.words ? minutes(it.words) : null].filter(Boolean);
    const head = h("header", { class: "rd-head" }, back, h("h2", { class: "rd-title", text: it.title }),
      h("div", { class: "rd-meta" }, meta.map((m) => h("span", { class: "chip", text: m })),
        b.text ? downloadButton(it.title, PF.textFileName(it.title), () => Promise.resolve(URL.createObjectURL(new Blob([b.text], { type: "text/markdown" })))) : null));
    const body = h("div", { class: "rd-body" });
    const wrap = h("article", { class: "reader", "aria-label": it.title }, head, body);
    function load() {
      if (b.error) return body.replaceChildren(h("div", { class: "mid bad", role: "alert" }, ic("alert"), h("span", { text: b.error })));
      paint(textPages(it.key, b.text));
    }
    function paint(pages) {
      R.page = Math.max(0, Math.min(R.page, pages.length - 1));
      const outline = PF.outline(pages);
      const find = h("input", { type: "search", class: "rd-find", "aria-label": "Find in this document", placeholder: "Find in this document", value: R.q, "data-k": "rd-find" });
      const found = h("span", { class: "rd-found", role: "status" });
      const prevHit = h("button", { type: "button", class: "icon-btn sm", "aria-label": "Previous match", onclick: () => hit(-1) }, ic("left"));
      const nextHit = h("button", { type: "button", class: "icon-btn sm", "aria-label": "Next match", onclick: () => hit(1) }, ic("right"));
      const toc = pages.length > 1 ? h("select", { class: "rd-toc", "aria-label": "Jump to", "data-k": "rd-toc", onchange: (e) => { go(+e.target.value); } },
        outline.filter((o) => o.level <= 2 || pages.length < 14).map((o) => h("option", { value: String(o.page), selected: o.page === R.page }, (o.level > 1 ? "  " : "") + o.title + " · p." + (o.page + 1)))) : null;
      const tools = h("div", { class: "rd-tools" }, h("div", { class: "rd-findrow" }, find, prevHit, nextHit), found, toc);
      const page = h("div", { class: "doc-page", tabindex: "-1" });
      const pgBar = h("div", { class: "pg-bar", "aria-hidden": "true" }, h("i"));
      const top = h("nav", { class: "pager top", "aria-label": "Pages" }), bot = h("nav", { class: "pager bot", "aria-label": "Pages" });
      const navParts = (cls) => [h("button", { type: "button", class: "btn ghost sm", "data-k": "pg-prev-" + cls, disabled: R.page === 0, onclick: () => go(R.page - 1) }, ic("left"), "Previous"),
        h("span", { class: "pg-l", text: "Page " + (R.page + 1) + " of " + pages.length + (pages[R.page].title && !/^Page \d+$/.test(pages[R.page].title) ? " \u00b7 " + clip(pages[R.page].title, 36) : "") }),
        h("button", { type: "button", class: "btn ghost sm", "data-k": "pg-next-" + cls, disabled: R.page === pages.length - 1, onclick: () => go(R.page + 1) }, "Next", ic("right"))];
      const hits = () => PF.findPages(pages, R.q);
      const before = (pg) => hits().filter((x) => x.page < pg).reduce((n, x) => n + x.n, 0);
      /* Match by match through the whole document: R.mi is the index of the current match; a page with many matches is stepped through, not skipped. */
      function hit(d) {
        const hs = hits(), tot = hs.reduce((n, x) => n + x.n, 0);
        if (!tot) return;
        const onPage = R.mi != null && R.mi >= before(R.page) && R.mi < before(R.page) + ((hs.find((x) => x.page === R.page) || { n: 0 }).n);
        const base = onPage ? R.mi : d > 0 ? before(R.page) - 1 : before(R.page);
        R.mi = (base + d + tot) % tot;
        let acc = 0, pg = hs[0].page;
        for (const x of hs) { if (R.mi < acc + x.n) { pg = x.page; break; } acc += x.n; }
        R.page = pg;
        draw();
        const m = page.querySelectorAll("mark")[R.mi - acc];
        if (m) m.scrollIntoView({ block: "center", behavior: reduced() ? "auto" : "smooth" });
        say("Match " + (R.mi + 1) + " of " + tot + ", page " + (R.page + 1));
      }
      function go(i) {
        if (i < 0 || i >= pages.length) return;
        R.page = i;
        draw();
        el.sc.scrollTop = Math.max(0, wrap.getBoundingClientRect().top - el.sc.getBoundingClientRect().top + el.sc.scrollTop - (el.tabs.hidden ? 0 : el.tabs.offsetHeight) - 4);
        page.focus({ preventScroll: true });
        say("Page " + (i + 1) + " of " + pages.length);
      }
      function draw() {
        const p = pages[R.page];
        const nodes = p.blocks.map((b) => blockNode(b, R.q)).filter(Boolean);
        page.replaceChildren(...nodes);
        if (R.mi != null) { const k = R.mi - before(R.page), ms = page.querySelectorAll("mark"); if (k >= 0 && k < ms.length) ms[k].classList.add("cur"); }
        const hs = hits(), total = hs.reduce((a, x) => a + x.n, 0);
        found.textContent = R.q.trim().length < 2 ? "" : total ? total + " " + plural(total, "match", "matches") + " on " + hs.length + " " + plural(hs.length, "page", "pages") : "No match";
        found.classList.toggle("none", R.q.trim().length >= 2 && !total);
        prevHit.disabled = nextHit.disabled = !total;
        pgBar.firstChild.style.width = ((R.page + 1) / pages.length) * 100 + "%";
        if (toc) { const sel = outline.filter((o) => o.level <= 2 || pages.length < 14); const idx = sel.reduce((best, o, n) => (o.page <= R.page ? n : best), 0); toc.selectedIndex = idx; }
        top.replaceChildren(...navParts("top"));
        bot.replaceChildren(...navParts("bot"));
      }
      let ft = 0;
      find.addEventListener("input", () => { clearTimeout(ft); ft = setTimeout(() => { R.q = find.value; R.mi = null; const hs = hits(); if (hs.length && !hs.some((x) => x.page === R.page)) R.page = hs[0].page; draw(); if (hs.length) hit(1); }, 140); });
      find.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); hit(e.shiftKey ? -1 : 1); } else if (e.key === "Escape" && find.value) { find.value = ""; R.q = ""; R.mi = null; draw(); e.stopPropagation(); } });
      body.replaceChildren(...[tools, top, page, bot, pages.length > 1 ? pgBar : null].filter(Boolean));
      draw();
      if (keepY != null) el.sc.scrollTop = keepY;
      if (keepFocus) { const n = body.querySelector('[data-k="' + keepFocus + '"]'); if (n) n.focus({ preventScroll: true }); }
    }
    load();
    if (R.fresh) { R.fresh = false; requestAnimationFrame(() => back.focus({ preventScroll: true })); }
    return h("div", { class: "pane" }, wrap);
  }

  /* ----- storyboard ----- */
  /* Before the asset plan there is nothing to capture or mock yet: a scene only shows whether its frames are made, not a footage verdict. */
  const beforeAssets = () => stageIdx() < STAGE_IDS.indexOf("assets");
  const sceneStatus = (s) => PF.sceneStatus(beforeAssets() ? { ...s, source: "other" } : s, arr(S.doc.assets));
  const STILLS = "Frames are storyboard stills, not footage";
  function sourceChip(s) {
    const st = sceneStatus(s);
    if (!st.label) return null;
    return h("span", { class: "chip" + (st.kind === "todo" || st.kind === "mock" || st.kind === "gen" ? " warn" : ""), title: STILLS, text: st.label });
  }
  function storySwitch(boards) {
    const wrap = h("div", { class: "story-sw" });
    const sc = h("div", { class: "seg-ctl", role: "group", "aria-label": "Story", style: "position:relative" }, boards.map((x, i) =>
      h("button", { type: "button", "data-k": "story-" + x.id, "aria-pressed": String(i === S.boardIdx), title: x.title, onclick: () => { S.boardIdx = i; render(true); el.sc.scrollTop = 0; } }, x.id + ": " + x.title)));
    const sel = h("select", { class: "story-select", "aria-label": "Story", "data-k": "story-select", onchange: (e) => { S.boardIdx = +e.target.value; render(true); el.sc.scrollTop = 0; } },
      boards.map((x, i) => h("option", { value: String(i), selected: i === S.boardIdx }, x.id + " of " + boards.length + ": " + x.title)));
    fadeX(sc);
    requestAnimationFrame(() => revealX(sc, sc.children[S.boardIdx]));
    wrap.append(sc, sel);
    return wrap;
  }
  /* The one honest answer to a placeholder: ask the agent to make the real thing (frames as images, a sample of every asset). */
  function makeBanner(text, what) {
    const blocked = S.readonly || S.offline || !!S.pending || !!S.justSent || !!S.sending;
    if (jobRunning() && S.doc.job.kind !== "build") return h("div", { class: "warnline", role: "status" }, ic("alert"), h("span", { text: text + " Being made now: see the progress above." }));
    return h("div", { class: "warnline", role: "status" }, ic("alert"), h("span", { text }),
      h("button", { class: "load", type: "button", disabled: blocked, text: "Ask the agent to make them", onclick: () => send("generate", { what }) }));
  }
  function viewStoryboard() {
    const d = S.doc, boards = arr(d.boards), b = curBoard();
    const confirm = d.stage === "confirm";
    S.seen.add(PF.seenKey("storyboard", b.id));
    const box = h("div", { class: "stack" });
    const scenes = arr(b.scenes);
    const total = Math.max(b.duration_s || 0, ...scenes.map((x) => x.end_s || 0), 1);
    if (confirm) box.append(confirmCard(boards));
    box.append(h("div", { class: "board-row" }, boards.length > 1 ? storySwitch(boards) : h("div", { class: "ttl", text: b.title })));
    const unmade = PF.previewRule(d, "storyboard-approved");
    if (unmade && !confirm) box.append(makeBanner(unmade.note.replace(/ Ask the agent.*$/, ""), "storyboard frames"));
    if (scenes.length && !confirm) box.append(sbTools(b, scenes));
    /* The scenes are what the person came to see; the paced preview comes after them (`preview` below). */
    const preview = S.sbView !== "time" && scenes.some((x) => x.start && mref(x.start.path) && !(mref(x.start.path) || {}).error) ? animatic(b, scenes) : null;
    if (d.stage === "keyframes") box.append(keyframeGrid(b));
    if (b.logline && !confirm) box.append(h("div", { class: "sub" }, showMore(b.logline, 160, "c2")));
    if (!scenes.length) { box.append(h("div", { class: "empty card" }, h("div", { class: "ring" }, ic("scene")), h("h2", { text: "No scenes yet" }), h("p", { text: "This story has no scenes. The agent adds them when it writes the storyboard." }))); return h("div", { class: "pane" }, box); }
    if (S.sbView === "time" && !confirm) {
      box.append(timeFrames(b));
      const c0 = d.stage === "storyboard" ? checksLine() : null;
      if (c0) box.append(c0);
      return h("div", { class: "pane" }, box);
    }
    const tl = h("div", { class: "tlwrap" }, h("div", { class: "tl", role: "group", "aria-label": "Timeline: jump to a scene" }, scenes.map((x) =>
      h("button", { type: "button", class: "k-" + sceneStatus(x).cls, "data-sid": x.id, style: "flex:" + Math.max((x.end_s - x.start_s), 0.5) + " 1 0", title: "Scene " + x.id + " " + x.beat + ", " + num(x.start_s) + " to " + num(x.end_s) + " s. " + STILLS,
        "aria-label": "Scene " + x.id + ", " + x.beat, onclick: () => jumpScene(b.id, x.id) }, tlThumb(x), h("span", { class: "fill", text: x.id })))),
      confirm ? null : h("div", { class: "tl-leg" }, [["r", "real", "All real assets ready"], ["s", "stills", "Stills only"], ["m", "mock", "Mock in plan"], ["g", "gen", "Generated"], ["t", "todo", beforeAssets() ? "Frames not made yet" : "To capture / not made"]]
        .filter(([, k]) => scenes.some((x) => sceneStatus(x).cls === k)).map(([c, , label]) => h("span", null, h("i", { class: c }), label))),
      confirm ? null : h("p", { class: "tl-note", text: scenes.length + (scenes.length === 1 ? " scene" : " scenes") + " · " + num(total) + " s · " + (b.aspect || "16:9") + " · Frames are storyboard stills, not footage." }));
    if (!confirm) box.append(tl);
    const ar = String(b.aspect || "16:9").replace(":", "/");
    const flat = [];
    const grid = h("div", { class: "scenes" });
    for (const x of scenes) grid.append(sceneCard(b, x, flat, ar, confirm));
    box.append(grid);
    if (preview) box.append(preview);
    const c = d.stage === "storyboard" ? checksLine() : null;
    if (c) box.append(c);
    S.scrollHook = () => {
      const top = el.sc.getBoundingClientRect().top + (el.tabs.hidden ? 0 : el.tabs.offsetHeight) + tl.offsetHeight + 12;
      let cur = null;
      for (const n of grid.children) { if (n.getBoundingClientRect().top <= top) cur = n.dataset.sid; else break; }
      for (const bt of tl.querySelectorAll("button")) bt.setAttribute("aria-current", String(bt.dataset.sid === cur));
    };
    return h("div", { class: "pane" }, box);
  }
  /* View switch + "how many frames": the person asks for a cadence ("every 5 s") and the agent adds and draws those frames. */
  function sbTools(b, scenes) {
    const all = PF.frameTimeline(b), made = all.filter((x) => x.f && mref(x.f.path) && !mref(x.f.path).error).length;
    const view = h("div", { class: "seg-ctl", role: "group", "aria-label": "View" }, [["scenes", "Scenes", scenes.length], ["time", "Frames in time", all.length]].map(([k, l, n]) =>
      h("button", { type: "button", "data-k": "sbv-" + k, "aria-pressed": String(S.sbView === k), onclick: () => { S.sbView = k; render(true); el.sc.scrollTop = 0; } }, l, h("span", { class: "n", text: String(n) }))));
    const cur = b.density || 0;
    const choices = PF.DENSITY_CHOICES.slice();
    if (cur && !choices.some((c) => c.every === cur)) choices.push({ every: cur, label: "Every " + num(cur) + " s" });
    const ok = canAsk();
    const dens = h("div", { class: "dens" }, h("span", { class: "dens-l sr", id: "densL", text: "Frames" }),
      h("div", { class: "seg-ctl wrap", role: "group", "aria-labelledby": "densL" }, choices.map((c) => h("button", { type: "button", "data-k": "dens-" + c.every, "aria-pressed": String(c.every === cur), disabled: !ok && c.every !== cur, title: c.every ? "Ask the agent for a frame every " + num(c.every) + " seconds" : "Only the start and end of each scene",
        onclick: () => { if (c.every !== cur) send("density", { story: b.id, every: c.every, what: c.every ? "every " + num(c.every) + " seconds" : "back to just the start and end of each scene" }); } }, c.label)).concat(
        h("button", { type: "button", "data-k": "dens-custom", "aria-pressed": "false", disabled: !ok, text: "Other\u2026", title: "Ask for a different spacing", onclick: () => openRequest("Show me storyboard frames every  seconds" + (arr(S.doc.boards).length > 1 ? " for story " + b.id : "") + ".", "How often should there be a frame? Say the seconds.") }))));
    return h("div", { class: "sb-tools" }, view, dens, cur ? h("p", { class: "dens-note", role: "status", text: "A frame every " + num(cur) + " s: " + made + " of " + all.length + " frames drawn." }) : null);
  }
  /* The whole story as frames in time order: start frames, the frames on the cadence, end frames. */
  function timeFrames(b) {
    const items = PF.frameTimeline(b), ar = String(b.aspect || "16:9").replace(":", "/"), flat = [];
    if (!items.length) return h("div", { class: "empty card" }, h("div", { class: "ring" }, ic("image")), h("h2", { text: "No frames yet" }), h("p", { text: "Frames appear here as the agent draws them." }));
    const grid = h("div", { class: "tl-grid", role: "list", "aria-label": "Frames in time order" }, items.map((x) => {
      const t = PF.clockT(x.t), kind = x.kind === "mid" ? "frame at " + t : x.kind;
      return h("figure", { class: "tl-fig " + x.kind, role: "listitem" }, frameEl(x.f, t, ar, flat, { scene: x.scene, label: cap(kind), kind: x.kind }),
        h("figcaption", null, h("b", { text: x.scene.id }), " " + x.scene.beat, h("span", { class: "k", text: x.kind === "mid" ? (x.auto ? "on the cadence" : "mid") : x.kind })));
    }));
    return h("div", { class: "tl-time" }, h("p", { class: "tl-note", text: "Every frame of this story in time order. Frames are storyboard stills, not footage." }), grid);
  }
  /* Watch it: the storyboard stills played in order with the caption, the voice line and the music sample. A preview of the pacing, not footage. */
  function animatic(b, scenes) {
    const total = Math.max(b.duration_s || 0, ...scenes.map((x) => x.end_s || 0), 1);
    const music = arr(S.doc.assets).find((a) => a.kind === "music" && a.sample && mref(a.sample) && !mref(a.sample).error);
    const stage = h("div", { class: "an-stage", style: "--ar:" + String(b.aspect || "16:9").replace(":", "/") });
    const layers = scenes.map(() => ({ a: h("img", { alt: "" }), b: h("img", { alt: "" }) }));
    layers.forEach((l) => stage.append(l.a, l.b));
    const cap = h("div", { class: "an-cap" }), say = h("div", { class: "an-say" }), tag = h("span", { class: "an-tag" });
    const big = h("div", { class: "an-big", "aria-hidden": "true" }, ic("play"));
    stage.append(h("div", { class: "an-shade" }), tag, cap, say, big);
    stage.setAttribute("role", "button"); stage.tabIndex = 0; stage.setAttribute("aria-label", "Play or pause the storyboard preview");
    const pp = h("button", { type: "button", class: "an-pp", "aria-label": "Play the storyboard" }, ic("play", "ic-play"), ic("pause", "ic-pause"));
    const time = h("span", { class: "an-time" });
    let sound = true;
    const spk = h("button", { type: "button", class: "an-snd", "aria-pressed": "true", "aria-label": "Sound on", title: "Sound on or off", onclick: () => { sound = !sound; spk.setAttribute("aria-pressed", String(sound)); spk.setAttribute("aria-label", sound ? "Sound on" : "Sound off"); spk.classList.toggle("off", !sound); if (audio) audio.muted = !sound; } }, ic("music"));
    const seg = h("div", { class: "an-seg", role: "slider", tabindex: "0", "aria-label": "Position in the storyboard", "aria-valuemin": "0", "aria-valuemax": String(Math.round(total)) },
      scenes.map((x) => h("i", { style: "flex:" + Math.max(x.end_s - x.start_s, 0.5) + " 1 0", title: "Scene " + x.id + " " + x.beat })), h("b", { class: "an-head" }));
    seg.setAttribute("aria-valuetext", "0:00");
    const heads = seg.querySelector(".an-head"), segs = [...seg.querySelectorAll("i")];
    let audio = null;
    if (music) getMedia(mref(music.sample)).then((u) => { audio = new Audio(u); audio.loop = true; audio.volume = 0.6; audio.muted = !sound; }, () => {});
    scenes.forEach((x, i) => {
      for (const [k, f] of [["a", x.start], ["b", x.end]]) { const r = f && mref(f.path); if (r && !r.error) getMedia(r).then((u) => { layers[i][k].src = u; layers[i][k].classList.add("ok"); stage.classList.add("loaded"); }, () => {}); }
      if (!(x.end && mref(x.end.path))) layers[i].b = layers[i].a;
    });
    let t = 0, playing = false, last = 0, raf = 0;
    const show = () => {
      const i = Math.max(0, scenes.findIndex((x) => t < x.end_s)), x = scenes[i === -1 ? scenes.length - 1 : i] || scenes[scenes.length - 1];
      const idx = scenes.indexOf(x), p = Math.min(1, Math.max(0, (t - x.start_s) / Math.max(x.end_s - x.start_s, 0.1)));
      layers.forEach((l, j) => { const on = j === idx; l.a.style.opacity = on ? String(p < 0.45 ? 1 : p > 0.65 ? 0 : 1 - (p - 0.45) / 0.2) : "0"; l.b.style.opacity = on ? String(p < 0.45 ? 0 : p > 0.65 ? 1 : (p - 0.45) / 0.2) : "0";
        const sc = on && !reduced() ? "scale(" + (1 + 0.05 * p).toFixed(4) + ")" : "none"; l.a.style.transform = sc; l.b.style.transform = sc; });
      cap.textContent = x.caption || ""; cap.hidden = !x.caption;
      say.textContent = x.voice ? "\u201c" + x.voice + "\u201d" : ""; say.hidden = !x.voice;
      tag.textContent = x.id + "/" + scenes.length + " \u00b7 " + x.beat;
      seg.setAttribute("aria-valuetext", fmtT(t) + " of " + fmtT(total) + ", scene " + x.id);
      stage.classList.toggle("playing", playing); stage.classList.toggle("done", t >= total);
      segs.forEach((e, j) => e.classList.toggle("cur", j === idx));
      time.textContent = fmtT(t) + " / " + fmtT(total);
      heads.style.left = (t / total) * 100 + "%";
      seg.setAttribute("aria-valuenow", String(Math.round(t)));
    };
    const tick = (now) => { if (!playing) return; t += (now - last) / 1000; last = now; if (t >= total) { t = total; stop(); } if (audio) audio.volume = Math.max(0, Math.min(0.6, (total - t) / 2)); show(); if (playing) raf = requestAnimationFrame(tick); };
    function stop() { playing = false; cancelAnimationFrame(raf); pp.classList.remove("on"); pp.setAttribute("aria-label", "Play the storyboard"); if (audio) audio.pause(); }
    function start() { if (t >= total - 0.05) t = 0; playing = true; last = performance.now(); pp.classList.add("on"); pp.setAttribute("aria-label", "Pause"); if (audio) { audio.currentTime = t % (audio.duration || total); audio.volume = 0.6; audio.play().catch(() => {}); } raf = requestAnimationFrame(tick); show(); }
    const seek = (clientX) => { const r = seg.getBoundingClientRect(); t = Math.min(total, Math.max(0, ((clientX - r.left) / r.width) * total)); if (audio && playing) audio.currentTime = t % (audio.duration || total); if (!playing) last = performance.now(); show(); };
    pp.addEventListener("click", () => (playing ? stop() : start()));
    stage.addEventListener("click", () => (playing ? stop() : start()));
    let drag = false;
    seg.addEventListener("pointerdown", (e) => { drag = true; seg.setPointerCapture(e.pointerId); seek(e.clientX); });
    seg.addEventListener("pointermove", (e) => { if (drag) seek(e.clientX); });
    seg.addEventListener("pointerup", () => { drag = false; });
    seg.addEventListener("keydown", (e) => {
      if (e.key === " " || e.key === "Enter") { e.preventDefault(); playing ? stop() : start(); return; }
      const d = { ArrowRight: 2, ArrowLeft: -2, PageUp: -10, PageDown: 10 }[e.key];
      if (d == null && e.key !== "Home" && e.key !== "End") return;
      e.preventDefault(); t = e.key === "Home" ? 0 : e.key === "End" ? total : Math.min(total, Math.max(0, t + d));
      if (audio && playing) audio.currentTime = t % (audio.duration || total); last = performance.now(); show();
    });
    stage.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); playing ? stop() : start(); } });
    show();
    return h("section", { class: "card animatic", "aria-label": "Watch the storyboard" },
      h("div", { class: "an-top" }, h("b", { text: "Your promo, as a preview" }), h("span", { class: "chip", text: num(total) + " s \u00b7 " + (music ? "music sample on" : "no music sample yet") })),
      stage, h("div", { class: "an-bar" }, pp, seg, time, music ? spk : null), h("p", { class: "tl-note", text: "Paced stills with captions and voice lines. The final video uses real footage." }));
  }
  const fmtT = (s) => Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0");
  function tlThumb(x) {
    const r = x.start && mref(x.start.path);
    if (!r || r.error) return null;
    const im = h("img", { alt: "", class: "tl-th" });
    getMedia(r).then((u) => { im.src = u; }, () => {});
    return im;
  }
  function jumpScene(story, id) {
    const t = $("scene-" + story + "-" + id);
    if (!t) return;
    if (t.tagName === "DETAILS") t.open = true;
    t.scrollIntoView({ block: "start", behavior: reduced() ? "auto" : "smooth" });
    t.classList.add("hl");
    setTimeout(() => t.classList.remove("hl"), 1200);
  }
  function goScene(story, id) {
    S.tab = "storyboard"; S.userTab = true;
    const bi = arr(S.doc.boards).findIndex((x) => x.id === story);
    if (bi >= 0) S.boardIdx = bi;
    render(true);
    requestAnimationFrame(() => jumpScene(story, id));
  }
  function sceneCard(b, s, flat, ar, collapsed) {
    const mk = (f, label, extra) => frameEl(f, label, ar, flat, { scene: s, label: extra || label, kind: label === "START" ? "start" : label === "END" ? "end" : "mid" });
    const mids = arr(s.frames);
    const time = num(s.start_s) + "–" + num(s.end_s) + " s";
    const facts = [["Happens", s.action, "span"], ["Caption", s.caption, "main"], ["Voice", s.voice, "main"], ["Sound", s.sound, "minor"], ["Camera", s.camera, "minor"], ["Proof", s.proof, "minor"]].filter((r) => r[1]);
    const rows = [h("div", { class: "frames" }, mk(s.start, "START"), h("span", { class: "arr" }, ic("arrow")), mk(s.end, "END"))];
    if (mids.length > 2) {
      const film = h("div", { class: "frames film", role: "group", "aria-label": "Frames through the scene, " + mids.length });
      mids.forEach((m) => film.append(mk(m, typeof m.t === "number" ? PF.clockT(m.t) : m.label || "", "Mid \u00b7 " + (typeof m.t === "number" ? PF.clockT(m.t) : m.label || ""))));
      fadeX(film);
      rows.push(film);
    } else for (let i = 0; i < mids.length; i += 2) rows.push(h("div", { class: "frames mids" }, mk(mids[i], "Mid \u00b7 " + (mids[i].label || ""), "Mid"), h("span"), mids[i + 1] ? mk(mids[i + 1], "Mid \u00b7 " + (mids[i + 1].label || ""), "Mid") : h("span")));
    const body = [rows, facts.length ? h("dl", { class: "facts" }, facts.map((r) => h("div", { class: "fact " + r[2] }, h("dt", { class: "k", text: r[0] }), h("dd", { class: "v", text: r[1] })))) : null];
    const id = "scene-" + b.id + "-" + s.id;
    if (collapsed) {
      return h("details", { class: "card scene-d", id, "data-sid": s.id }, h("summary", null, h("span", { class: "num" }, s.id),
        h("h3", { text: s.beat }), sourceChip(s), h("span", { class: "time", text: time }), ic("chevron")), h("div", { class: "inner" }, body));
    }
    return h("article", { class: "card scene", id, "data-sid": s.id, "aria-label": "Scene " + s.id + ": " + s.beat },
      h("div", { class: "scene-h" }, h("span", { class: "num", text: s.id }), h("h3", { text: s.beat }), sourceChip(s), h("span", { class: "time", text: time })), body);
  }
  function confirmCard(boards) {
    const sc = boards.flatMap((b) => arr(b.scenes));
    const as = arr(S.doc.assets);
    const secs = Math.max(...boards.map((b) => b.duration_s || 0), 0);
    const real = (k) => as.filter((a) => a.kind === k && a.state === "ready").length;
    const open = as.filter((a) => a.state === "mock" || a.state === "todo").length + missingAll();
    const gen = sc.filter((x) => x.source === "generated").length;
    const tile = (icon, big, small, warn) => h("div", { class: "cf-tile" + (warn ? " warn" : "") }, ic(icon), h("b", { text: big }), h("span", { text: small }));
    const tiles = [tile("scene", String(sc.length), plural(sc.length, "scene", "scenes")), secs ? tile("film", num(secs) + " s", "runtime") : null,
      tile("film", String(real("recording") + real("screenshot")), "real recordings", !(real("recording") + real("screenshot"))),
      real("voice") ? tile("music", "Voice", "narration ready") : null, real("music") ? tile("music", "Music", "licensed track ready") : null, gen ? tile("image", String(gen), plural(gen, "generated plate", "generated plates")) : null].filter(Boolean);
    const max = S.doc.rounds_max || 5;
    const q = gate() && gate().question;
    return h("div", { class: "card confirm-card" }, h("div", { class: "cf-h" }, h("b", { text: "Before you generate" }), open ? h("span", { class: "chip warn", text: open + " not ready" }) : h("span", { class: "chip ok", text: "Everything is ready" })),
      h("div", { class: "cf-tiles" }, tiles),
      h("p", { class: "cf-next" }, h("b", { text: "What happens next: " }), "The agent renders the first draft video from these assets. You watch it, then ask for changes in up to " + max + " rounds until you are happy. Nothing is published."),
      q ? h("p", { class: "cf-q", text: q }) : null);
  }
  function keyframeGrid(b) {
    const cells = [];
    let total = 0, done = 0;
    for (const sc of arr(b.scenes)) {
      const main = [["Start", sc.start], ["End", sc.end]];
      const mids = arr(sc.frames);
      const mk = (label, f) => { const r = f && mref(f.path); const ok = !!(r && !r.error); total++; if (ok) done++; return { label, r, ok, prompt: f && f.prompt }; };
      cells.push({ sc, main: main.map(([l, f]) => mk(l, f)), mids: mids.map((f, i) => mk("Mid " + (i + 1), f)) });
    }
    const flat = [];
    const tile = (c, it) => {
      if (!it.ok) return h("div", { class: "fr empty", title: it.label }, "Not made");
      const kind = it.label === "Start" ? "start" : it.label === "End" ? "end" : "mid";
      const idx = flat.length;
      flat.push({ r: it.r, ctx: { scene: c.sc, label: it.label, kind }, prompt: it.prompt });
      const slot = h("span", { style: "position:absolute;inset:0;display:block" });
      lazyInto(slot, it.r, (u) => h("img", { src: u, alt: "Scene " + c.sc.id + " " + it.label, draggable: "false" }), { compact: true });
      return h("button", { type: "button", class: "fr", title: it.label, "aria-label": "Open scene " + c.sc.id + " " + it.label + " frame larger", onclick: () => openLightbox(flat, idx) }, slot);
    };
    const grid = h("div", { class: "kf-grid" }, cells.map((c) => {
      const mm = c.mids.filter((m) => m.ok).length;
      return h("div", { class: "card kf-cell" }, h("span", { class: "id", text: "Scene " + c.sc.id }), h("div", { class: "kf-row" }, c.main.map((it) => tile(c, it))),
        c.mids.length ? h("span", { class: "chip kf-mid" + (mm < c.mids.length ? " dashed" : ""), title: mm + " of " + c.mids.length + " mid frames made", text: "+" + c.mids.length + " mid" + (mm < c.mids.length ? " \u00b7 " + (c.mids.length - mm) + " not made" : "") }) : null);
    }));
    return h("div", null, h("div", { class: "h2", style: "margin-bottom:4px" }, "Keyframes", h("span", { class: "chip", text: "Story " + b.id + ": " + done + " of " + total + " made" })),
      grid);
  }

  function frameEl(f, label, ar, flat, ctx) {
    const st = "--ar:" + ar;
    const r = f && mref(f.path);
    const lab = h("span", { class: "lbl", text: label });
    if (!r) return h("div", { class: "fr empty", style: st }, lab, h("div", null, h("b", { text: f && f.slate ? "Placeholder, no image yet" : "No image yet" }), f && f.prompt ? h("div", { class: "p", text: f.prompt }) : null));
    if (r.error) return h("div", { class: "fr err", style: st }, lab, h("span", { text: r.error }));
    const idx = flat.length;
    flat.push({ r, ctx, prompt: f.prompt });
    const slot = h("span", { style: "position:absolute;inset:0;display:block" });
    const b = h("button", { type: "button", class: "fr", style: st, "aria-label": "Open " + ctx.label + " frame of scene " + ctx.scene.id + " larger", onclick: () => openLightbox(flat, idx) }, slot, lab);
    lazyInto(slot, r, (u) => h("img", { src: u, alt: "Scene " + ctx.scene.id + " " + ctx.label, draggable: "false" }), { compact: true });
    return b;
  }

  /* ----- lightbox ----- */
  const LB = { items: [], i: 0, opener: null, open: false, parts: null };
  const inertTargets = () => [el.sc, el.gate];
  function openLightbox(items, i) {
    LB.items = items; LB.i = i; LB.opener = ctx.root.activeElement; LB.open = true;
    const title = h("div", { class: "cap" }), cnt = h("span", { class: "cnt" });
    const prev = h("button", { class: "l nav prev", type: "button", "aria-label": "Previous frame", onclick: () => lbGo(-1) }, ic("left"));
    const next = h("button", { class: "l nav next", type: "button", "aria-label": "Next frame", onclick: () => lbGo(1) }, ic("right"));
    const close = h("button", { class: "l", type: "button", "aria-label": "Close", onclick: closeLightbox }, ic("close"));
    const img = h("div", { class: "lb-frame" });
    const frame = img;
    const tgS = h("button", { type: "button", text: "START", onclick: () => lbKind("start") }), tgE = h("button", { type: "button", text: "END", onclick: () => lbKind("end") });
    const tg = h("div", { class: "tg", role: "group", "aria-label": "Frame" }, tgS, tgE);
    const prompt = h("p");
    el.lb.replaceChildren(h("div", { class: "lb-top" }, title, cnt, close), h("div", { class: "lb-stage" }, frame, h("div", { class: "lb-info" }, tg, prompt)));
    LB.parts = { title, cnt, prev, next, close, img, prompt, tgS, tgE, tg };
    let x0 = null;
    frame.addEventListener("pointerdown", (e) => { x0 = e.clientX; });
    frame.addEventListener("pointerup", (e) => { if (x0 == null) return; const dx = e.clientX - x0; x0 = null; if (dx > 50) lbGo(-1); else if (dx < -50) lbGo(1); });
    el.lb.hidden = false;
    inertTargets().forEach((n) => n.setAttribute("inert", ""));
    lbShow();
    close.focus();
  }
  function lbKind(k) { const cur = LB.items[LB.i]; const j = LB.items.findIndex((x) => x.ctx.scene === cur.ctx.scene && x.ctx.kind === k); if (j >= 0) { LB.i = j; lbShow(); } }
  function lbShow() {
    const { title, cnt, prev, next, img, prompt, tgS, tgE, tg } = LB.parts;
    const it = LB.items[LB.i];
    const s = it.ctx.scene;
    title.replaceChildren("Scene " + s.id + " · " + s.beat, h("small", { text: num(s.start_s) + "–" + num(s.end_s) + " s" }),
      h("span", { class: "lb-chip", text: "Storyboard still" + (sceneStatus(s).label ? " \u00b7 " + sceneStatus(s).label : "") }));
    cnt.textContent = LB.i + 1 + " of " + LB.items.length + " frames";
    prev.disabled = LB.i === 0; next.disabled = LB.i === LB.items.length - 1;
    const hasS = LB.items.some((x) => x.ctx.scene === s && x.ctx.kind === "start"), hasE = LB.items.some((x) => x.ctx.scene === s && x.ctx.kind === "end");
    tgS.disabled = !hasS; tgE.disabled = !hasE;
    tgS.setAttribute("aria-pressed", String(it.ctx.kind === "start")); tgE.setAttribute("aria-pressed", String(it.ctx.kind === "end"));
    tg.hidden = !(hasS || hasE);
    prompt.replaceChildren(it.ctx.kind === "mid" ? h("b", { text: it.ctx.label + ". " }) : "", it.prompt ? h("span", null, h("b", { text: (it.method ? "How it is made: " : "Frame: ") }), it.prompt) : "",
      s.voice ? h("span", { class: "lb-say" }, h("b", { text: "Voice: " }), s.voice) : "", s.caption ? h("span", { class: "lb-say" }, h("b", { text: "Caption: " }), s.caption) : "");
    const my = LB.i;
    img.replaceChildren(h("div", { class: "sk", style: "position:absolute;inset:0;border-radius:6px" }), prev, next);
    getMedia(it.r).then((u) => { if (LB.open && LB.i === my) img.replaceChildren(h("img", { src: u, alt: "Scene " + s.id + " " + it.ctx.label }), prev, next); },
      () => { if (LB.open && LB.i === my) img.replaceChildren(h("span", { text: "Couldn't load this frame." }), prev, next); });
  }
  function lbGo(d) { const j = LB.i + d; if (j < 0 || j >= LB.items.length) return; LB.i = j; lbShow(); }
  function closeLightbox() {
    if (!LB.open) return;
    LB.open = false; el.lb.hidden = true; el.lb.replaceChildren();
    inertTargets().forEach((n) => n.removeAttribute("inert"));
    if (LB.opener && LB.opener.isConnected) LB.opener.focus();
  }
  /* A clip is looked at big and with controls (pause, seek, full screen): the tile is only a poster. Same overlay, focus handling and Esc as the frames. */
  function openPlayer(a, r, sampled) {
    LB.items = []; LB.i = 0; LB.opener = ctx.root.activeElement; LB.open = true; LB.parts = null;
    const close = h("button", { class: "l", type: "button", "aria-label": "Close", onclick: closeLightbox }, ic("close"));
    const stage = h("div", { class: "lb-frame" }, h("div", { class: "sk", style: "position:absolute;inset:0;border-radius:6px", "aria-hidden": "true" }));
    const how = scrubPaths(a.how);
    el.lb.replaceChildren(h("div", { class: "lb-top" }, h("div", { class: "cap" }, a.label || a.id, sampled ? h("span", { class: "lb-chip", text: "Sample" }) : null), close),
      h("div", { class: "lb-stage" }, stage, h("div", { class: "lb-info" }, sampled && a.sample_note ? h("p", null, h("b", { text: "Sample: " }), a.sample_note) : null, how ? h("p", { text: how }) : null)));
    el.lb.hidden = false;
    inertTargets().forEach((n) => n.setAttribute("inert", ""));
    getMedia(r).then((u) => { if (LB.open) stage.replaceChildren(h("video", { src: u, controls: "", autoplay: "", playsinline: "", "aria-label": a.label || a.id })); },
      () => { if (LB.open) stage.replaceChildren(h("span", { text: "Couldn't load this clip." })); });
    close.focus();
  }
  ctx.root.addEventListener("keydown", (e) => {
    if (!LB.open) return;
    if (e.key === "Escape") { e.preventDefault(); closeLightbox(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); lbGo(-1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); lbGo(1); }
    else if (e.key === "Tab") {
      const f = [...el.lb.querySelectorAll("button")].filter((b) => !b.disabled && b.offsetParent !== null);
      if (!f.length) return;
      const i = f.indexOf(ctx.root.activeElement);
      e.preventDefault();
      f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
    }
  });

  /* ----- assets ----- */
  const RANK = { missing: 0, mock: 1, ready: 2, todo: 3 };
  const KIND_GROUP = { recording: "footage", video: "footage", screenshot: "stills", image: "stills", music: "music", voice: "voice", sfx: "sfx" };
  const ASSET_GROUPS = [["footage", "Recordings"], ["stills", "Screenshots and pictures"], ["music", "Music"], ["voice", "Voice"], ["sfx", "Sound effects"], ["keyframes", "Keyframes"], ["other", "Other"]];
  const plural = (n, one, many) => (n === 1 ? one : many);
  function viewAssets() {
    const d = S.doc, boards = arr(d.boards);
    const m = model();
    if (curBoard()) S.seen.add(PF.seenKey("assets", curBoard().id));
    const box = h("div", { class: "stack" });
    if (boards.length > 1) box.append(storySwitch(boards));
    /* The counts are the filters: chips with the state's colour, pressed = showing only that state. */
    const btn = (k, label) => h("button", { type: "button", class: "c-" + k, "data-k": "f-" + k, "aria-pressed": String(S.filter === k), disabled: !m.n[k], onclick: () => { S.filter = S.filter === k ? null : k; render(true); } }, h("i", { class: "cdot", "aria-hidden": "true" }), h("b", { text: m.n[k] }), " " + label);
    const parts = [btn("ready", "ready"), btn("mock", "mock"), btn("todo", "to make")];
    if (m.n.missing) parts.push(btn("missing", plural(m.n.missing, "file missing", "files missing")));
    const cnt = h("div", { class: "counter", role: "group", "aria-label": "Filter by state", "data-total": String(m.total) }, parts);
    box.append(cnt);
    if (m.total) box.append(h("div", { class: "stackbar", "aria-hidden": "true" }, ["ready", "mock", "todo", "missing"].filter((k) => m.n[k]).map((k) => h("i", { class: "s-" + k, style: "flex:" + m.n[k] + " 1 0", title: m.n[k] + " " + k }))));
    const miss = missingAll(), here = m.n.missing, other = miss - here;
    if (miss) box.append(h("div", { class: "warnline", role: "alert" }, ic("alert"), h("span", { text: (here ? here + " " + plural(here, "file is", "files are") + " missing." : "No files missing in this story.") + (other > 0 ? " " + other + " " + plural(other, "file is", "files are") + " missing (other story)." : "") })));
    const bare = arr(d.assets).filter((a) => !PF.hasPreview(a)).length;
    if (bare) box.append(makeBanner(bare + " " + plural(bare, "asset has", "assets have") + " nothing to look at or hear yet.", "asset samples"));
    const shown = m.items.filter((x) => !S.filter || x.eff === S.filter).sort((a, b) => RANK[a.eff] - RANK[b.eff] || a.i - b.i);
    /* Grouped by what the thing is (recordings, pictures, music, voice, sounds, keyframes), each group one grid: the kind reads from the heading, the state from the chip. */
    const groupOf = (x) => (x.type === "keyframe" ? "keyframes" : KIND_GROUP[x.a.kind] || "other");
    for (const [gid, label] of ASSET_GROUPS) {
      const inG = shown.filter((x) => groupOf(x) === gid);
      if (!inG.length) continue;
      const open = inG.filter((x) => x.eff !== "ready").length;
      box.append(h("section", { class: "asset-group", "aria-label": label },
        secH(label, inG.length, open ? h("span", { class: "sec-open", text: open + " open" }) : null),
        h("div", { class: "gallery", "data-count": String(inG.length) }, inG.map((x) => (x.type === "keyframe" ? keyframeRow(x.t) : !PF.hasPreview(x.a) && (x.eff === "todo" || x.eff === "missing") ? assetRow(x) : assetTile(x))))));
    }
    const c = STAGE_TAB[d.stage] === "assets" ? checksLine() : null;
    if (c) box.append(c);
    return h("div", { class: "pane" }, box);
  }
  const glyphFor = (kind) => ic(kind === "audio" ? "music" : kind === "video" ? "film" : "image");
  function keyframeRow(t) {
    return h("article", { class: "card asset compact" }, h("div", { class: "gl" }, ic("image")),
      h("div", { class: "bd" }, h("div", { class: "nm", text: t.label }), t.at ? h("div", { class: "sc", text: t.at }) : null,
        h("div", { class: "kind" }, h("span", { class: "chip", text: "Keyframe" }), h("span", { class: "chip bad", text: "To make" }))),
      h("button", { class: "lk", type: "button", text: "Open scene", onclick: () => goScene(t.story, t.scene) }));
  }
  function assetRow(x) {
    const a = x.a;
    const sc = x.scenes;
    const fb = KIND_MEDIA[a.kind] || "file";
    return h("article", { class: "card asset compact" }, h("div", { class: "gl" }, glyphFor(fb)),
      h("div", { class: "bd" }, h("div", { class: "nm", title: a.id, text: a.label || a.id }), sc.length ? h("div", { class: "sc", text: (sc.length === 1 ? "Scene " : "Scenes ") + sceneRange(sc) }) : null,
        h("div", { class: "kind" }, h("span", { class: "chip", text: (KIND_LABEL[a.kind] || a.kind) + " \u00b7 " + a.source }), a.source === "licensed" && !a.licence ? h("span", { class: "chip warn", text: "No licence on file" }) : null, h("span", { class: "chip bad", text: x.eff === "missing" ? "File missing" : "To make" }))),
      a.how && a.source === "generated" ? h("details", { class: "prompt rw-how" }, h("summary", { text: "View prompt" }), h("p", { text: scrubPaths(a.how) })) : null);
  }
  /* Peaks of the sample, drawn as bars that fill as it plays; the strip itself seeks. */
  function waveform(u, a, host) {
    const cv = h("canvas", { class: "wave", "aria-hidden": "true" });
    host.replaceChildren(cv);
    let peaks = null;
    const draw = () => {
      const w = cv.clientWidth, ht = cv.clientHeight, dpr = window.devicePixelRatio || 1;
      if (!w || !ht) return;
      cv.width = w * dpr; cv.height = ht * dpr;
      const g = cv.getContext("2d"), n = Math.floor(w / 4), cs = getComputedStyle(cv);
      const dim = cs.getPropertyValue("--k").trim() || "#888", cur = a.duration ? a.currentTime / a.duration : 0;
      g.scale(dpr, dpr);
      for (let i = 0; i < n; i++) {
        const v = peaks ? peaks[Math.floor(i * peaks.length / n)] : 0.15 + 0.1 * Math.sin(i / 3);
        const bh = Math.max(3, v * (ht - 6));
        g.globalAlpha = i / n <= cur ? 1 : 0.38; g.fillStyle = dim;
        g.beginPath(); g.roundRect(i * 4, (ht - bh) / 2, 2.4, bh, 1.2); g.fill();
      }
    };
    fetch(u).then((r) => r.arrayBuffer()).then((buf) => new (window.AudioContext || window.webkitAudioContext)().decodeAudioData(buf)).then((ab) => {
      const ch = ab.getChannelData(0), n = 120, step = Math.floor(ch.length / n), out = [];
      for (let i = 0; i < n; i++) { let m = 0; for (let j = i * step; j < (i + 1) * step; j += 16) m = Math.max(m, Math.abs(ch[j] || 0)); out.push(m); }
      const mx = Math.max(...out, 0.01); peaks = out.map((v) => v / mx); draw();
    }).catch(() => {});
    cv.addEventListener("click", (e) => { if (!a.duration) return; const r = cv.getBoundingClientRect(); a.currentTime = a.duration * (e.clientX - r.left) / r.width; draw(); });
    a.addEventListener("timeupdate", draw);
    new ResizeObserver(draw).observe(cv);
    draw();
  }
  function audioControl(u, waveHost) {
    const a = new Audio(u);
    if (waveHost) waveform(u, a, waveHost);
    a.preload = "metadata";
    const pp = h("button", { class: "pp", type: "button", "aria-label": "Play" }, ic("play", "ic-play"), ic("pause", "ic-pause"));
    const rg = h("input", { type: "range", min: "0", max: "1000", value: "0", step: "1", "aria-label": "Seek" });
    const tm = h("span", { class: "tm", text: "0:00" });
    const upd = () => { rg.value = a.duration ? String(Math.round(1000 * a.currentTime / a.duration)) : "0"; tm.textContent = fmtTime(a.currentTime) + (a.duration ? " / " + fmtTime(a.duration) : ""); };
    pp.addEventListener("click", () => { if (a.paused) a.play().catch(() => {}); else a.pause(); });
    a.addEventListener("play", () => { pp.classList.add("on"); pp.setAttribute("aria-label", "Pause"); });
    a.addEventListener("pause", () => { pp.classList.remove("on"); pp.setAttribute("aria-label", "Play"); });
    a.addEventListener("ended", () => { a.currentTime = 0; upd(); });
    a.addEventListener("timeupdate", upd);
    a.addEventListener("loadedmetadata", upd);
    rg.addEventListener("input", () => { if (a.duration) a.currentTime = a.duration * rg.value / 1000; });
    return h("div", { class: "audio" }, pp, rg, tm);
  }
  const STATE_CHIP = { mock: ["Mock", "warn"], todo: ["To make", "bad"], missing: ["File missing", "bad"] };
  const stateChip = (eff, sampled) => (eff === "todo" && sampled ? ["To make", "warn"] : STATE_CHIP[eff]);
  function assetTile(x) {
    const a = x.a, eff = x.eff;
    const real = x.r && !x.r.error ? x.r : null;
    const src = real || (x.s && !x.s.error ? x.s : null);
    const sampled = !real && !!src;
    const fallback = KIND_MEDIA[a.kind] || "file";
    const kind = src ? mkind(src, fallback) : fallback;
    const isAudio = kind === "audio" && !!src;
    const pv = h("div", { class: "pv " + (!src ? "mock" : isAudio ? "lead" : "") });
    const slot = h("div", { class: "slot" });
    pv.append(slot);
    let prow = null;
    if (!src) slot.append(h("div", { class: "mid" }, glyphFor(fallback), h("span", { text: "No preview yet" })));
    else if (isAudio) {
      slot.append(h("div", { class: "mid" }, glyphFor("audio")));
      prow = h("div", { class: "prow" });
      lazyInto(prow, src, (u) => audioControl(u, slot), { manual: src.size > BIG_AUDIO, manualText: "Load audio (" + fmtSize(src.size) + ")" });
    } else if (kind === "image") lazyInto(slot, src, (u) => h("img", { src: u, alt: a.label || a.id, draggable: "false" }), { compact: true });
    else if (kind === "video") {
      const build = (u) => {
        const v = h("video", { src: u + "#t=0.1", preload: "metadata", playsinline: "", muted: "", "aria-hidden": "true", tabindex: "-1" });
        const open = () => openPlayer(a, src, sampled);
        v.addEventListener("click", open);
        return h("div", { style: "position:absolute;inset:0" }, v, h("button", { class: "play", type: "button", "aria-label": "Play " + (a.label || a.id) + " larger", onclick: open }, ic("play", "ic-play")));
      };
      lazyInto(slot, src, build, { manual: src.size > BIG_VIDEO, manualText: "Load video (" + fmtSize(src.size) + ")" });
    } else slot.append(h("div", { class: "mid" }, ic("scene"), h("span", { text: src.name || a.id })));
    if (sampled) pv.append(h("span", { class: "tag", text: "SAMPLE" }));
    else if (src && eff === "mock") pv.append(h("span", { class: "tag", text: "MOCK" }));
    const sc = x.scenes;
    const how = scrubPaths(a.how);
    const lic = [a.licence ? "Licence: " + a.licence : "", a.note && !/^https?:/i.test(a.note) ? a.note : ""].filter(Boolean).join(" · ");
    const url = a.note && /^https:\/\//i.test(a.note) ? a.note : "";
    const sc_ = stateChip(eff, sampled);
    const more = [sampled && a.sample_note ? h("div", { class: "how", text: "Sample: " + a.sample_note }) : null,
      how && !(( eff === "mock" || eff === "todo") && (a.kind === "recording" || a.kind === "screenshot")) ? (a.source === "generated" ? h("details", { class: "prompt" }, h("summary", { text: "View prompt" }), h("p", { text: how })) : h("div", { class: "how" }, showMore(how, 90, "c2"))) : null,
      lic || url ? h("div", { class: "lic" }, lic, lic && url ? " \u00b7 " : "", url ? h("button", { type: "button", text: host(url), title: url, onclick: () => post({ type: "open-url", url }) }) : null) : null].filter(Boolean);
    return h("article", { class: "card asset" + (isAudio ? " a-audio" : "") + (!src && fallback === "audio" ? " a-flat" : ""), "data-kind": a.kind }, pv, h("div", { class: "bd" }, h("div", { class: "nm", title: a.id, text: a.label || a.id }),
      h("div", { class: "kind" }, h("span", { class: "chip", text: (KIND_LABEL[a.kind] || a.kind) + (eff === "ready" ? " · " + a.source : "") }), sc_ ? h("span", { class: "chip " + sc_[1], text: sc_[0] }) : null,
        a.source === "licensed" && !a.licence ? h("span", { class: "chip warn", text: "No licence on file" }) : null),
      sc.length ? h("div", { class: "sc", text: (sc.length === 1 ? "Scene " : "Scenes ") + sceneRange(sc) }) : null,
      how && (eff === "mock" || eff === "todo") && (a.kind === "recording" || a.kind === "screenshot") ? h("div", { class: "torec" }, h("b", { text: "To record: " }), how) : null,
      more.length ? h("details", { class: "more" }, h("summary", { text: "Details" }), ...more) : null), prow);
  }

  /* ----- draft ----- */
  const hhmm = (iso) => { const t = Date.parse(iso || ""); if (isNaN(t)) return ""; const dt = new Date(t), tm = dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); return dt.toDateString() === new Date().toDateString() ? tm : dt.toLocaleDateString([], { day: "numeric", month: "short" }) + ", " + tm; };
  /* Saves the draft through the same blob the player uses: getMedia reuses the cached object URL or asks the host, even while the player still shows its manual load tile.
     The URL stays in the cache for the player, so it is never revoked here. */
  /* `getUrl` resolves to an object URL of the file to save as `name` (a draft from the host's blob, a document from its text). */
  function downloadButton(label, name, getUrl) {
    const btn = h("button", { type: "button", class: "dl", "aria-label": "Download " + label });
    const box = h("span", { class: "dl-box" }, btn);
    const paint = (state) => {
      btn.disabled = state === "busy";
      if (state === "busy") btn.setAttribute("aria-busy", "true");
      else btn.removeAttribute("aria-busy");
      btn.replaceChildren(ic(state === "error" ? "refresh" : "download"), h("span", { text: state === "busy" ? "Preparing…" : state === "error" ? "Try again" : "Download" }));
      box.querySelector(".dl-err")?.remove();
      if (state === "error") box.prepend(h("span", { class: "dl-err", role: "alert" }, ic("alert"), "Couldn't prepare the download."));
    };
    const save = (url) => {
      const a = h("a", { href: url, download: name, hidden: "" });
      ctx.root.append(a);
      a.click();
      a.remove();
    };
    const run = () => {
      /* Disabling the focused button drops keyboard focus, so hand it back once the button is enabled again. */
      const refocus = ctx.root.activeElement === btn;
      const settle = (state) => { paint(state); if (refocus && btn.isConnected) btn.focus(); };
      paint("busy");
      getUrl().then((u) => { save(u); say("Download started for " + label); settle("idle"); }, () => settle("error"));
    };
    btn.addEventListener("click", run);
    paint("idle");
    return box;
  }
  function viewDraft() {
    const d = S.doc;
    const drafts = arr(d.drafts), finals = arr(d.finals);
    const left = h("div", { class: "stack" });
    const getItem = (k) => { if (!k) return null; const i = +k.slice(1); return k[0] === "f" ? finals[i] && { ...finals[i], final: true } : drafts[i]; };
    let sel = S.draftSel;
    if (!getItem(sel)) sel = finals.length ? "f" + (finals.length - 1) : drafts.length ? "d" + (drafts.length - 1) : null;
    S.draftSel = sel;
    const it = getItem(sel);
    const pickBtn = (k, label, extra) => h("button", { type: "button", class: extra || "", "data-k": "dr-" + k, "aria-pressed": String(sel === k), onclick: () => { S.draftSel = k; render(true); } }, label);
    if (finals.length) {
      const seg = h("div", { class: "seg-ctl", role: "group", "aria-label": "Final and earlier drafts", style: "position:relative" },
        finals.map((f, i) => pickBtn("f" + i, f.label, "final")),
        drafts.length ? h("button", { type: "button", "data-k": "dr-earlier", "aria-pressed": String(S.earlier), "aria-expanded": String(S.earlier), onclick: () => { S.earlier = !S.earlier; render(true); } }, "Earlier drafts (" + drafts.length + ")") : null);
      fadeX(seg);
      left.append(seg);
      if (S.earlier) { const sg = h("div", { class: "seg-ctl", role: "group", "aria-label": "Earlier drafts", style: "position:relative" }, drafts.map((x, i) => pickBtn("d" + i, x.label))); fadeX(sg); left.append(sg); }
    } else if (drafts.length > 1) {
      const seg = h("div", { class: "seg-ctl", role: "group", "aria-label": "Drafts", style: "position:relative" }, drafts.map((x, i) => pickBtn("d" + i, x.label)));
      fadeX(seg); left.append(seg);
      requestAnimationFrame(() => revealX(seg, seg.children[+sel.slice(1)]));
    }
    if (it) {
      const dur = h("span", { class: "dur" });
      const player = h("div", { class: "player", style: "position:relative" });
      const r = it.path ? mref(it.path) : null;
      const delivered = d.stage === "final" && it.final && PF.finalState(d).ok;
      dur.textContent = r && !r.error ? fmtSize(r.size) : "";
      if (!r) player.append(h("div", { class: "mid" }, ic("film"), h("span", { text: "This video file is not available." })));
      else if (r.error) player.append(h("div", { class: "mid", role: "alert" }, ic("alert"), h("span", { text: r.error })));
      else lazyInto(player, r, (u) => {
        const v = h("video", { src: u + "#t=0.5", controls: "", preload: "metadata", playsinline: "", "aria-label": it.label });
        v.addEventListener("loadedmetadata", () => { if (v.duration && isFinite(v.duration)) dur.textContent = fmtTime(v.duration) + (v.videoWidth ? " · " + v.videoWidth + "×" + v.videoHeight : ""); });
        return v;
      }, { manual: r.size > BIG_DRAFT, manualText: "Load video (" + fmtSize(r.size) + ")" });
      /* The file is one unit: icon, name, facts, and its one action on the same row. */
      const dl = r && !r.error ? downloadButton(it.label, PF.downloadName(r, it.label), () => getMedia(r)) : null;
      const meta = h("div", { class: "file-id" }, h("span", { class: "file-ic", "aria-hidden": "true" }, ic("film")),
        h("span", { class: "file-main" }, h("b", { text: it.label + (it.after ? " \u00b7 after " + it.after : "") }), h("span", { class: "file-meta" }, dur, it.rel ? h("span", { class: "path", text: it.rel }) : null)),
        delivered ? null : dl);
      left.append(h("div", null, player, meta, it.note ? h("p", { class: "sub", style: "margin-top:4px", text: it.note }) : null));
      if (delivered) {
        /* Delivered: one block says it is ready and carries the one action; credits are quiet label / value rows. */
        const credits = arr(d.assets).filter((x) => x.licence && (x.kind === "music" || x.kind === "voice" || x.kind === "sfx"));
        left.prepend(h("div", { class: "card done-card" }, h("div", { class: "done-ic" }, ic("check")), h("div", { class: "done-main" }, h("b", { text: "Your promo is ready" }),
          h("p", { text: "Nothing has been published. Watch it once more with sound, then post it yourself. To change something, ask for changes and the agent starts another round." }),
          dl ? h("div", { class: "done-acts" }, dl) : null)));
        if (credits.length) left.append(h("section", { "aria-label": "Credits" }, secH("Credits to keep", credits.length),
          h("dl", { class: "credits" }, credits.map((x) => h("div", { class: "credit" }, h("dt", { text: (KIND_LABEL[x.kind] || x.kind) + (x.label ? " \u00b7 " + x.label : "") }), h("dd", { text: x.licence }))))));
      }
      if (d.stage === "review" || d.stage === "drafts") left.append(h("section", { "aria-label": "What to check" }, secH("What to check"),
        h("ul", { class: "watch-list" }, ["Does it match the storyboard you approved?", "Is every caption and voice line true for what is on screen?", "Does the pacing and music feel right with the sound on?"].map((t) => h("li", { text: t })))));
      left.append(shareBlock(it));
    } else {
      const since = d.stage === "drafts" ? hhmm(d.stage_since) : "";
      return h("div", { class: "pane empty fill" }, h("div", { class: "ring" }, ic("film")),
        h("h2", { text: d.stage === "drafts" ? "Drafts in progress" : "Drafts start after final confirmation" }),
        d.stage === "drafts" ? h("p", { text: since ? "Last update " + since + ". Nothing to watch yet." : "Nothing to watch yet." }) : null);
    }
    const rounds = arr(d.rounds);
    let right = null;
    if (rounds.length || d.stage === "review") {
      const used = d.rounds_used || 0, max = d.rounds_max;
      const op = rounds.find((r) => r.open);
      const chip = op ? "Round " + op.n + " of " + max + " in progress" : d.stage === "review" && used < max ? "Next: round " + (used + 1) + " of " + max : used + " of " + max + " rounds used";
      right = h("div", { class: "rounds-col" }, secH("Rounds", null, h("span", { class: "chip", text: chip })),
        rounds.length ? h("div", { class: "rounds" }, rounds.slice().reverse().map(roundCard)) : h("p", { class: "sub", text: "No feedback yet. Watch the draft, then approve it or send feedback." }));
    }
    return h("div", { class: "pane" }, h("div", { class: "draft-grid" + (right ? "" : " one") }, left, right));
  }
  /* Upload options appear only for destinations the host's twg can reach; the click goes to the agent, which runs `promo flow share`. */
  function shareBlock(it) {
    const rows = PF.shareRows(S.doc, it);
    if (!rows.length) return null;
    const blocked = S.readonly || S.offline || !!S.pending || !!S.justSent || !!S.sending;
    const kind = it.id.charAt(0) === "f" ? "final" : "draft", n = +it.id.slice(1);
    return h("section", { class: "share", "aria-label": "Upload " + it.label },
      secH("Upload " + it.label.toLowerCase(), null, it.share_as ? h("span", { class: "sub" }, "saved as ", h("span", { class: "as", text: it.share_as })) : null),
      rows.map((r) => h("div", { class: "share-row", "data-dest": r.dest, "data-state": r.state },
        r.state === "on" ? h("span", { class: "chip ok" }, ic("check"), "On " + r.label) : r.state === "new" ? h("span", { class: "chip", text: r.label }) : h("span", { class: "chip warn", text: r.label + " · edited since" }),
        r.url && r.state !== "new" ? linkChip(r.url) : null,
        r.action ? h("button", { type: "button", class: "btn ghost", "data-quiet": "1", disabled: blocked, text: r.action, onclick: () => send("share", { kind, n, item: it.label, dest: r.dest, dest_label: r.label }) }) : null,
        r.note ? h("span", { class: "sub", text: r.note }) : null)));
  }
  function linkChip(u) { return h("button", { type: "button", class: "lchip", title: u, onclick: () => { if (/^https:\/\//i.test(u)) post({ type: "open-url", url: u }); } }, h("span", { text: host(u) }), ic("link")); }
  function roundCard(r) {
    const v = r.open ? ["In progress", "accent"] : VERDICT[r.verdict] || [r.verdict ? "Intent: " + r.verdict : "Closed", ""];
    const sc = Object.entries(r.scores || {});
    const links = arr(r.research);
    const box = h("div", { class: "rlinks" }, links.slice(0, 3).map(linkChip));
    if (links.length > 3) { const more = h("button", { type: "button", class: "lchip more-chip", text: "+" + (links.length - 3) + " more", onclick: () => { more.replaceWith(...links.slice(3).map(linkChip)); } }); box.append(more); }
    return h("article", { class: "card round" }, h("div", { class: "round-h" }, h("b", { text: "Feedback from " + (r.cycle > 1 ? "cycle " + r.cycle + ", round " : "round ") + r.n }), h("span", { class: "chip " + v[1], text: v[0] }),
      sc.length ? h("span", { class: "chip", text: sc.map(([k, x]) => cap(k) + " " + x).join(" · ") }) : null),
      h("div", { class: "fb" }, showMore(r.feedback || "", 220)), links.length ? box : null);
  }

  /* ---------------- gate bar ---------------- */
  function editing() { return (S.compose && el.note.value.trim().length > 0) || S.picks.size > 0 || !!S.style || !!S.ownStyle.trim(); }
  const offlineBlocked = () => S.offline;

  function gateModel() {
    const d = S.doc, g = gate();
    if (S.noState && !hasDoc()) return { mode: "none" };
    if (S.readonly) return { mode: "readonly" };
    if (isStarting()) return { mode: "starting" };
    if (!readable()) return { mode: "none" };
    if (S.pending || S.justSent) return { mode: "wait", name: S.pending ? S.pending.name : S.justSent.name };
    const used = d.rounds_used || 0, max = d.rounds_max;
    const m = { mode: "gate", g, d, stage: (g && g.stage) || d.stage };
    if (!g) {
      const fin = PF.finalState(d);
      const done = d.stage === "final" && fin.ok;
      m.mode = "work"; m.done = done;
      const yours = !done && d.summary && d.summary.badge === "waiting";
      m.note = done ? "The final is delivered." : yours ? "Your turn: record " + captureNeeded() + " " + plural(captureNeeded(), "clip", "clips") + " from the real app." : fin.registered ? "A final is registered, but its file is missing." : "Waiting on the agent. Nothing for you to do yet.";
      m.secondary = done ? "Ask for changes" : yours ? "Send files" : "Add a note";
      m.changes = "changes"; m.placeholder = done ? "What should change in the final?" : yours ? "Where are the recordings? Paste the file paths, or say they are attached in the chat." : "Add a note for the agent."; m.sendLabel = yours ? "Send" : "Send note";
      return m;
    }
    m.changes = g.kind === "draft" && used < max ? "feedback" : "changes";
    m.secondary = g.kind === "draft" && used >= max ? "Restate direction" : g.kind === "style" ? "" : g.kind === "pick" ? "Ask for other stories" : g.changes_label || "Send changes";
    m.sendLabel = g.kind === "draft" ? (used >= max ? "Send direction" : "Send feedback") : g.kind === "style" ? "Send style" : "Send changes";
    m.placeholder = { style: "Describe the style you want, or paste a reference link.", approve: "What should change? Name the scene or asset if you can.", confirm: "What needs to happen before drafts?",
      draft: used >= max ? "All " + max + " rounds are used. Say what direction you want instead." : "What should change in the draft?" }[g.kind] || "What should change?";
    m.round = used + 1; m.max = max;
    m.note = { style: "Choose a style, or describe your own.", approve: g.stale ? "Look it over, then approve again or send changes." : "Approve to move on, or send changes.", confirm: "",
      draft: used >= max ? "All " + max + " rounds are used." : "Approve it, or send feedback for the next round.", pick: "" }[g.kind] || "";
    if (g.kind === "pick") {
      const n = S.picks.size;
      const lim = g.picks_max;
      /* The button says the outcome: what is about to happen, or what is needed before anything can. */
      m.primary = n ? "Storyboard " + (n === 1 ? "this story" : "these " + n) : lim && lim > 1 ? "Pick 1 or " + lim + " stories" : "Pick a story";
      m.primaryDisabled = n === 0;
      m.note = !n ? "Tick the stories to turn into storyboards." : lim && n >= lim ? n + " picked. That is the limit: untick one to swap." : n + " picked." + (lim ? " You can pick " + (lim - n) + " more." : "");
    } else if (g.kind === "style") {
      const name = S.ownStyle.trim() ? "this style" : S.style ? clip(S.style, 26) : "";
      m.primary = name ? "Use " + name + " and write scripts" : "Choose a style"; m.primaryDisabled = !name;
      if (m.primaryDisabled) m.note = "Choose a style, or describe your own";
    } else m.primary = g.approve_label || "Approve";
    const mr = PF.missingRule(d, g.gate) || PF.previewRule(d, g.gate);
    if (g.kind === "approve" && mr) { m.primaryDisabled = true; m.note = mr.note; }
    if (g.kind === "draft") {
      const ds = arr(d.drafts), latest = ds[ds.length - 1];
      if (latest) {
        const lr = latest.path ? mref(latest.path) : null;
        m.draftId = latest.id;
        if (!lr || lr.error) { m.primaryDisabled = true; m.note = "The latest draft file is missing."; }
        else if (S.tab === "draft" && S.draftSel && S.draftSel !== "d" + (ds.length - 1)) {
          const vi = S.draftSel[0] === "f" ? arr(d.finals)[+S.draftSel.slice(1)] : ds[+S.draftSel.slice(1)];
          m.primary = "Approve " + latest.label;
          m.note = "You're viewing " + (vi ? vi.label : "another draft") + ". Approving applies to " + latest.label + ".";
        }
      }
    }
    const tabs = tabList(), gt = gTab();
    if ((g.kind === "approve" || g.kind === "confirm" || g.kind === "draft") && gt && (gt !== S.tab || S.reader) && tabs.some((t) => t.id === gt)) {
      m.reviewTab = gt;
      m.primary = "Review " + tabs.find((t) => t.id === gt).label;
      m.primaryDisabled = false;
      m.note = "Open " + tabs.find((t) => t.id === gt).label + " before you decide.";
    }
    if (!m.reviewTab && (g.kind === "approve" || g.kind === "confirm")) {
      const un = PF.seenRule(d, g.gate, S.seen);
      if (un) { m.reviewStory = un; m.primary = "Review story " + un.board; m.primaryDisabled = false; m.note = "Open story " + un.board + " before you decide: you have only looked at the other " + (arr(d.boards).length === 2 ? "story" : "stories") + "."; }
    }
    if (S.stale && S.stale.changedGate) { m.primaryDisabled = true; m.note = "This step changed. Review the update first."; }
    return m;
  }

  function renderGate() {
    const m = gateModel();
    S.cur = m;
    if (S.compose && S.composeKind === "request") { m.sendLabel = "Send request"; m.placeholder = S.reqHint || "What should the agent add or change?"; }
    const busy = !!S.sending;
    const note = (txt, opts = {}) => {
      el.gateNote.className = "gate-note";
      el.gateNote.replaceChildren(...(opts.spin ? [h("i", { class: "spin" })] : []), ...(opts.dot ? [h("i", { class: "qdot" })] : []), ...(opts.lock ? [ic("lock")] : []), ...(opts.check ? [ic("check")] : []), ...(txt ? [h("span", { class: "txt", text: txt })] : []));
    };
    el.btn1.hidden = el.btn2.hidden = true;
    el.btn2.removeAttribute("data-quiet");
    /* The draft decision is two real choices, not approve-or-a-footnote: "Feedback and iterate" is a coloured button next to "Approve". */
    if (m.mode === "gate" && m.g && m.g.kind === "draft" && !S.compose) el.btn2.dataset.tone = "accent"; else el.btn2.removeAttribute("data-tone");
    el.gate.hidden = m.mode === "none" || (S.settingsOpen && (m.mode === "gate" || m.mode === "work"));
    el.gate.dataset.layout = "stack";
    el.gate.dataset.busy = jobRunning() ? "1" : "";          // while the agent's run is on, the bar is calm: the header already says whose turn it is
    el.btn1.removeAttribute("aria-describedby");
    if (m.mode === "readonly") { note("This thread is archived. You can read everything, but nothing can be sent.", { lock: true }); S.compose = false; }
    else if (m.mode === "starting") note("Preparing. The first step appears here when it is ready.", { dot: true });
    else if (m.mode === "wait") {
      const jv = jobRunning() ? PF.jobView(S.doc.job, Date.now()) : null;
      if (jv) note("Sent " + (ACTION_WORD[m.name] || "your reply") + ". The agent picks it up when the " + jv.many + " above are done (" + (jv.done + jv.failed) + " of " + jv.total + ").", { spin: true });
      else note(S.stall ? (S.pending ? "Still queued. Check the chat." : "Still waiting. Check the chat.") : "Sent " + (ACTION_WORD[m.name] || "your reply") + ". Waiting for the agent to pick it up.", { spin: !S.stall });
      if (!jv && S.stall && !S.pending && S.lastAction) { el.btn2.hidden = false; el.btn2.dataset.quiet = "1"; el.btn2.textContent = "Send again"; el.btn2.disabled = busy || offlineBlocked(); el.gate.dataset.layout = "bar"; }
    } else if (m.mode === "work") {
      el.gate.dataset.layout = "bar";
      el.btn2.hidden = false; el.btn2.dataset.quiet = "1";
      if (S.compose) { el.gate.dataset.layout = "stack"; el.btn2.removeAttribute("data-quiet"); }
      note(S.compose ? "" : m.note, { check: m.done, dot: !m.done });
    } else if (m.mode === "gate") {
      el.btn2.hidden = !m.secondary;
      if (S.compose) {
        note("");
        el.btn2.hidden = false; el.btn2.textContent = "Cancel"; el.btn2.disabled = busy;
      } else { el.btn2.textContent = m.secondary || ""; el.btn2.disabled = busy || offlineBlocked(); note(m.note); }
      el.btn1.hidden = false;
      el.btn1.setAttribute("aria-describedby", "gateNote");
      if (S.compose) { el.btn1.textContent = busy ? "Sending" : m.sendLabel; el.btn1.disabled = busy || !el.note.value.trim() || offlineBlocked() || !!(S.stale && S.stale.changedGate); }
      else { el.btn1.textContent = busy ? "Sending" : m.primary; el.btn1.disabled = busy || !!m.primaryDisabled || offlineBlocked(); }
    }
    if (m.mode === "work" && S.compose) { el.btn1.hidden = false; el.btn1.textContent = busy ? "Sending" : m.sendLabel; el.btn1.disabled = busy || !el.note.value.trim() || offlineBlocked(); el.btn2.textContent = "Cancel"; el.btn2.disabled = busy; }
    else if (m.mode === "work") { el.btn2.textContent = m.secondary; el.btn2.disabled = busy || offlineBlocked(); }
    const composing = S.compose && (m.mode === "gate" || m.mode === "work");
    el.compose.hidden = !composing;
    if (composing) {
      el.noteLabel.textContent = m.placeholder; el.note.placeholder = m.placeholder;
      el.noteHint.textContent = (IS_MAC ? "Cmd" : "Ctrl") + "+Enter to send. Esc to cancel.";
    }
    el.gateErr.hidden = !S.err;
    el.gateErr.textContent = S.err;
  }

  function openCompose() { S.compose = true; S.composeKind = null; renderGate(); el.note.focus(); }
  /* Ask the agent to add or change something (a document, a script, more frames). The text goes into the same note box as every other message, so dictation works. */
  function openRequest(text, hint) {
    if (S.readonly || S.pending || S.justSent || S.sending) return;
    S.compose = true; S.composeKind = "request"; S.reqHint = hint || "";
    el.note.value = text || "";
    renderGate();
    el.note.focus();
    el.note.setSelectionRange(el.note.value.length, el.note.value.length);
  }
  const canAsk = () => !(S.readonly || S.offline || S.pending || S.justSent || S.sending);
  function closeCompose() { S.compose = false; S.composeKind = null; S.err = ""; renderGate(); el.btn2.focus(); }
  el.btn2.addEventListener("click", () => {
    const m = S.cur;
    if (m && m.mode === "wait") { if (S.stall && !S.pending && S.lastAction) send(S.lastAction.name, S.lastAction.payload, true); return; }
    if (S.compose) closeCompose(); else openCompose();
  });
  el.note.addEventListener("input", renderGate);
  el.note.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); if (!el.btn1.disabled) el.btn1.click(); }
    else if (e.key === "Escape") { e.preventDefault(); closeCompose(); }
  });
  el.btn1.addEventListener("click", () => {
    const m = S.cur;
    if (!m || (m.mode !== "gate" && m.mode !== "work") || S.sending || S.offline) return;
    if (S.compose) {
      const text = el.note.value.trim().slice(0, MAX_NOTE);
      if (!text) return;
      if (S.composeKind === "request") return send("request", { text, where: ({ plan: "Plan", scripts: "Scripts", storyboard: "Storyboard", assets: "Assets", draft: "Drafts" })[S.tab] || "Stage" });
      if (m.g && m.g.kind === "style") return send("changes", { stage: "discover", text: "Style: " + text + refTail() });
      if (m.changes === "feedback") return send("feedback", { round: m.round, max_rounds: m.max, text });
      return send("changes", { stage: m.stage, text });
    }
    const g = m.g;
    if (m.reviewTab) { pickTab(m.reviewTab); return; }
    if (m.reviewStory) { const bi = arr(S.doc.boards).findIndex((x) => x.id === m.reviewStory.board); if (bi >= 0) { S.boardIdx = bi; S.tab = m.reviewStory.tab; S.userTab = true; render(true); el.sc.scrollTop = 0; } return; }
    if (g.kind === "pick") { S.sentPicks = new Set(S.picks); send("pick", { gate: g.gate, picks: [...S.picks].join(" ") }); }
    else if (g.kind === "style") send("changes", { stage: "discover", text: "Style: " + (S.ownStyle.trim() || S.style) + refTail() });
    else send("approve", m.draftId ? { gate: g.gate, draft: m.draftId } : { gate: g.gate });
  });

  const refTail = () => (/^https:\/\//i.test(S.ref.trim()) ? ". Reference: " + S.ref.trim() : ". No reference link.");
  function startStall() { clearTimeout(S.stallTimer); S.stall = false; S.stallTimer = setTimeout(() => { S.stall = true; renderGate(); }, STALL_MS); }
  function send(name, payload, again) {
    const id = "a" + ++M.seq;
    if (again && payload && typeof payload.text === "string" && !/^\(sent again\) /.test(payload.text)) payload = { ...payload, text: "(sent again) " + payload.text };
    S.lastAction = { name, payload };
    S.sending = { id, name, again, timer: setTimeout(() => { if (S.sending && S.sending.id === id) { S.sending = null; S.err = "No answer from the host. Check the chat before sending again."; render(); } }, 20000) };
    S.err = "";
    post({ type: "action", id, name, payload });
    render();
  }
  function onResult(m) {
    if (!S.sending || S.sending.id !== m.id) return;
    clearTimeout(S.sending.timer);
    const sent = S.sending;
    S.sending = null;
    if (m.ok) {
      S.err = "";
      S.justSent = { key: gateKey(), name: sent.name, saw: false };
      if (S.compose) { el.note.value = ""; S.compose = false; S.composeKind = null; }
      S.stale = null; S.stash = null; S.updated = false;
      startStall();
      render(true);
      el.gateNote.focus();
      say("Sent. Waiting for the agent to pick it up.");
    } else { S.err = m.error || "That didn't go through. Try again."; render(); }
  }

  /* ---------------- render + state ---------------- */
  function render(force) {
    if (!S.booted) return;
    el.app.dataset.boot = "ready";
    const list = tabList();
    const cur = gTab();
    if (S.stage !== S.doc.stage) { S.stage = S.doc.stage; S.userTab = false; S.sentPicks = null; S.draftSel = null; S.earlier = false; S.filter = null; S.boardIdx = 0; S.seen = new Set(); S.sbView = "scenes"; }
    if (!S.userTab || !list.some((t) => t.id === S.tab)) S.tab = list.some((t) => t.id === cur) ? cur : list.length ? list[list.length - 1].id : null;
    if (!list.length) S.tab = null;
    if (S.settingsOpen && !hasSettings()) S.settingsOpen = false;
    renderHeader();
    renderJob();
    renderWorking();
    renderBanners();
    renderTabs(list);
    renderContent(list, force);
    renderGate();
  }

  function onState(m) {
    const first = !(S.booted && hasDoc());
    const prevKey = first ? null : gateKey();
    const prevLabel = first ? "" : S.doc.stage_label || STAGE_LABEL[S.doc.stage] || "";
    const before = first ? null : JSON.stringify(sliceFor(S.tab, false));
    const changedVersion = S.version != null && m.version !== S.version;
    const wasSent = !!S.justSent;
    const wasEditing = editing() && !wasSent;
    S.version = m.version;
    S.summary = m.summary || {};
    S.doc = m.state && typeof m.state === "object" && !Array.isArray(m.state) ? m.state : {};
    S.pending = m.pending || null;
    S.offline = !!m.offline;
    S.readonly = !!m.readonly;
    S.noState = false;
    clearTimeout(S.bootTimer);
    const key = hasDoc() ? gateKey() : null;
    const gateChanged = prevKey != null && key != null && prevKey !== key;
    if (S.pending) { if (S.justSent) S.justSent.saw = true; if (!S.stallTimer || S.stall === false) { /* keep timer */ } }
    if (S.justSent) {
      const cleared = (key != null && key !== S.justSent.key) || (S.justSent.saw && !S.pending);
      if (cleared) { S.justSent = null; clearTimeout(S.stallTimer); S.stall = false; }
    }
    if (S.justSent && S.justSent.name === "settings" && hasSettings() && !PF.outputDirty(S.doc.settings.output, S.setSel, S.setText)) { S.justSent = null; clearTimeout(S.stallTimer); S.stall = false; }
    if (S.pending && !S.stallTimer) startStall();
    if (!S.pending && !S.justSent) { clearTimeout(S.stallTimer); S.stallTimer = 0; S.stall = false; }
    const g = gate();
    const ids = new Set(arr(S.doc.scripts).map((s) => s.id));
    let cleared = false;
    for (const p of [...S.picks]) if (!ids.has(p) || !g || g.kind !== "pick" || gateChanged) { S.picks.delete(p); cleared = true; }
    if ((S.style || S.ownStyle) && (!g || g.kind !== "style" || gateChanged)) { S.style = null; S.ownStyle = ""; S.ref = ""; cleared = true; }
    if (gateChanged) {
      if (S.compose && el.note.value.trim()) { S.stash = { text: el.note.value.trim(), label: prevLabel || "the previous step" }; el.note.value = ""; }
      if (S.compose) { S.compose = false; S.composeKind = null; }
      if (cleared && !wasSent) toast("Your picks were cleared because the step changed");
      if (wasEditing) S.stale = { changedGate: true };
    } else if (changedVersion && wasEditing) S.stale = S.stale || { changedGate: false };
    if (!wasEditing && !gateChanged) S.stale = null;
    if (!S.docBase && hasDoc()) S.docBase = new Set(readables().map((x) => x.key));
    S.booted = true;
    render();
    if (!first && !wasEditing && !gateChanged && changedVersion && g && !S.pending && !S.justSent && before !== JSON.stringify(sliceFor(S.tab, false))) { S.updated = true; renderBanners(); }
    if (!g) S.updated = false;
    releaseUnused();
  }

  function startBootTimer() { clearTimeout(S.bootTimer); S.bootTimer = setTimeout(() => { if (!S.booted) { S.noState = true; S.booted = true; el.app.dataset.boot = "ready"; render(true); } }, BOOT_MS); }

  function receive(m) {
    if (!m || typeof m !== "object") return;
    switch (m.type) {
      case "init": setTheme(!!m.dark, m.tokens, !!m.reduceMotion); break;
      case "theme": setTheme(!!m.dark, m.tokens, null); break;
      case "state": if (S.noState) S.booted = hasDoc(); onState(m); break;
      case "media": onMediaReply(m); break;
      case "result": onResult(m); break;
      default: break;
    }
  }
  function unmount() {
    clearTimeout(S.bootTimer); clearTimeout(S.stallTimer); clearInterval(S.agoTimer); clearInterval(S.jobTimer);
    if (S.sending) clearTimeout(S.sending.timer);
    for (const id of [...M.cache.keys()]) revoke(id);
  }
  el.stepsBtn.addEventListener("click", () => { S.stepsOpen = !S.stepsOpen; renderHeader(); });

  /* Loading skeleton until the first state; fixed size so nothing jumps. */
  el.content.replaceChildren(h("div", { class: "pane skel", "aria-busy": "true", "aria-label": "Loading" }, h("div", { class: "sk", style: "height:22px;width:55%" }), h("div", { class: "sk", style: "height:92px" }), h("div", { class: "sk", style: "height:92px" }), h("div", { class: "sk", style: "height:92px" })));
  el.stageName.textContent = "Promo flow";
  el.stepNo.textContent = "Loading";
  el.gate.hidden = true;
  el.stepsBtn.replaceChildren(ic("chevron"));
  el.settingsBtn.replaceChildren(ic("folder"));
  onAccent();
  startBootTimer();
  post({ type: "ready" });
  return { receive, unmount };
};
