"use strict";
/* Promo flow mod: talks to the host only through the postMessage bridge (protocol 1).
   in:  init, state, media, result, theme     out: ready, media, action, title, open-url */
(() => {
  const STAGE_IDS = ["discover", "scripts", "pick", "storyboard", "assets", "keyframes", "confirm", "drafts", "review", "final"];
  const STAGE_LABEL = { discover: "Style & references", scripts: "Scripts", pick: "Pick stories", storyboard: "Storyboard", assets: "Asset plan", keyframes: "Keyframes", confirm: "Final confirmation", drafts: "First drafts", review: "Review rounds", final: "Final" };
  const SHORT = { discover: "Style", scripts: "Scripts", pick: "Pick", storyboard: "Storyboard", assets: "Assets", keyframes: "Keyframes", confirm: "Confirm", drafts: "Drafts", review: "Review", final: "Final" };
  const STAGE_TAB = { scripts: "scripts", pick: "scripts", storyboard: "storyboard", assets: "assets", keyframes: "storyboard", confirm: "storyboard", drafts: "draft", review: "draft", final: "draft" };
  const BADGE_TEXT = { working: "With the agent", waiting: "Your turn", done: "Done", attention: "Needs attention" };
  const ACTION_WORD = { approve: "your approval", pick: "your picks", changes: "your changes", feedback: "your feedback", generate: "your request" };
  const VERDICT = { yes: ["Intent matched", "ok"], partial: ["Partly matched", "warn"], no: ["Missed the intent", "bad"] };
  const KIND_LABEL = { screenshot: "Screenshot", image: "Image", recording: "Recording", video: "Video", music: "Music", voice: "Voice", sfx: "Sound effect" };
  const KIND_MEDIA = { screenshot: "image", image: "image", recording: "video", video: "video", music: "audio", voice: "audio", sfx: "audio" };
  const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || "");
  const MAX_NOTE = 1500, STALL_MS = 45000, BOOT_MS = 8000;
  const BIG_VIDEO = 24 * 1024 * 1024, BIG_AUDIO = 8 * 1024 * 1024, BIG_DRAFT = 60 * 1024 * 1024;

  const $ = (id) => document.getElementById(id);
  const root = document.documentElement;
  const el = { sc: $("scroller"), app: $("app"), stepNo: $("stepNo"), badge: $("badge"), badgeText: $("badgeText"), stageName: $("stageName"), stepsBtn: $("stepsBtn"), stateLine: $("stateLine"),
    stepper: $("stepper"), curLab: $("curLab"), stepsList: $("stepsList"), banners: $("banners"), tabs: $("tabs"), content: $("content"), gate: $("gate"), gateNote: $("gateNote"),
    compose: $("compose"), note: $("note"), noteLabel: $("noteLabel"), noteHint: $("noteHint"), gateErr: $("gateErr"), btn2: $("btnSecondary"), btn1: $("btnPrimary"),
    lb: $("lightbox"), toast: $("toast"), live: $("live") };

  const S = {
    booted: false, version: null, summary: {}, doc: {}, pending: null, offline: false, readonly: false,
    tab: null, userTab: false, stage: null, picks: new Set(), style: null, ownStyle: "", boardIdx: 0, draftSel: null, earlier: false, filter: null, checksOpen: false,
    seen: new Set(), ref: "", compose: false, sending: null, justSent: null, stall: false, err: "", stale: null, stash: null, updated: false, stepsOpen: false, lastAction: null, title: "", lastBadge: "", noState: false,
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
  const post = (m) => { try { window.parent.postMessage(m, "*"); } catch (_) { /* no host */ } };
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
  }
  window.addEventListener("pagehide", () => { for (const id of [...M.cache.keys()]) revoke(id); });

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
      document.body.append(probe);
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
  const steps = () => (isStarting() ? STAGE_IDS.map((id, i) => ({ id, label: STAGE_LABEL[id], state: i === 0 ? "current" : "todo" })) : arr(S.doc.steps));
  const gate = () => (S.doc && S.doc.gate) || null;
  const stageIdx = () => STAGE_IDS.indexOf(S.doc.stage);
  const sceneIds = () => new Set(arr(S.doc.boards).flatMap((b) => arr(b.scenes).map((s) => String(s.id))));
  const gTab = () => STAGE_TAB[(gate() && gate().stage) || S.doc.stage];
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
    el.stageName.textContent = noConn ? "Promo flow" : isStarting() ? "Getting started" : S.doc.stage_label || STAGE_LABEL[S.doc.stage] || "Promo flow";
    const sm = S.summary || {};
    el.stateLine.textContent = noConn ? "No answer from the host yet." : S.readonly ? "Archived. Read only." : isStarting() ? "Waiting on the agent." : sm.status || "";
    const badge = noConn ? "attention" : isStarting() ? "working" : BADGE_TEXT[sm.badge] ? sm.badge : "working";
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
    const c = st[cur];
    el.curLab.textContent = c ? SHORT[c.id] || c.label : "";
    el.curLab.style.setProperty("--i", String(cur));
    el.curLab.classList.toggle("right", cur >= 6);
    el.stepsBtn.replaceChildren(ic("chevron"));
    el.stepsBtn.hidden = !hasDoc();
    el.stepsBtn.setAttribute("aria-expanded", String(S.stepsOpen));
    el.stepsList.hidden = !S.stepsOpen || !hasDoc();
    const title = clip("Promo flow: " + el.stageName.textContent, 40);
    if (title !== S.title) { S.title = title; post({ type: "title", text: title }); }
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
    const ae = document.activeElement;
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
        t.label, t.n != null ? h("span", { class: "n", text: String(t.n) }) : null, t.id === cur && !S.readonly ? h("i", { class: "now" + (waiting ? "" : " idle"), role: "img", title: waiting ? "Waiting on you" : "Not waiting on you", "aria-label": waiting ? "Waiting on you" : "Not waiting on you" }) : null)));
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
  function pickTab(id) { if (S.tab === id) return; S.tab = id; S.userTab = true; S.updated = false; render(); el.sc.scrollTop = 0; }

  /* ---------------- content ---------------- */
  let lastSig = "", tick = 0;
  function sliceFor(tab, withChecks) {
    const d = S.doc;
    const common = withChecks ? [d.stage, d.checks, d.gate && d.gate.kind, d.gate && d.gate.picks_max, d.stale_steps, d.stage_since] : [d.stage];
    if (tab === "scripts") return [d.scripts, d.intent, common];
    if (tab === "storyboard") return [d.boards, d.stage === "confirm" ? d.assets.map((a) => [a.kind, a.source, a.scenes]) : 0, d.stage === "keyframes" ? d.to_make : 0, common];
    if (tab === "assets") return [d.assets, d.to_make, d.boards, common];
    if (tab === "draft") return [d.drafts, d.finals, d.rounds, d.rounds_used, d.rounds_max, common];
    return [d.intent, d.style, common];
  }
  function renderContent(list, force) {
    let sig;
    if (S.noState && !hasDoc()) sig = "noconn";
    else if (!readable()) sig = "bad";
    else if (isStarting()) sig = "start";
    else if (!list.length) sig = "overview|" + JSON.stringify([sliceFor(null, true), gate(), S.style, S.readonly, !!S.pending]);
    else sig = S.tab + "|" + JSON.stringify(sliceFor(S.tab, true)) + "|" + [...S.picks].join() + "|" + S.style + S.boardIdx + S.draftSel + S.earlier + S.filter + S.readonly + !!S.pending + !!S.justSent;
    if (!force && sig === lastSig) return;
    const keepScroll = sig.split("|")[0] === lastSig.split("|")[0] ? el.sc.scrollTop : 0;
    lastSig = sig;
    const ae = document.activeElement;
    const fk = ae && el.content.contains(ae) ? ae.dataset.k : null;
    releaseHeavy();
    S.scrollHook = null;
    let view;
    if (S.noState && !hasDoc()) view = viewNoConn();
    else if (!readable()) view = viewBad();
    else if (isStarting()) view = viewStarting();
    else if (!list.length) view = viewOverview();
    else view = ({ scripts: viewScripts, storyboard: viewStoryboard, assets: viewAssets, draft: viewDraft }[S.tab] || viewOverview)();
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
    return h("div", { class: "pane empty fill" }, h("div", { class: "ring" }, ic("spark")), h("h2", { text: "Your request is with the agent" }),
      h("p", { text: "Steps appear here as the agent publishes them." }));
  }

  function viewOverview() {
    const d = S.doc, g = gate();
    const box = h("div", { class: "stack" });
    box.append(h("div", null, h("h2", { class: "h2", text: "Your request" }), h("div", { class: "quote", style: "margin-top:8px" }, showMore(d.intent || "", 280))));
    if (g && g.kind === "style" && !S.readonly) {
      box.append(h("div", null, h("h2", { class: "h2", text: "Pick a style" }),
        h("div", { class: "choices", role: "radiogroup", "aria-label": "Style", style: "margin-top:10px" }, arr(g.options).map((o) => {
          const th = o.thumb && mref(o.thumb);
          const tslot = th && !th.error ? h("div", { class: "thumb", style: "position:relative" }) : h("div", { class: "glyph" }, ic("film"));
          if (th && !th.error) lazyInto(tslot, th, (u) => h("img", { src: u, alt: "" }), { compact: true });
          const inp = h("input", { type: "radio", name: "style", value: o.label, checked: S.style === o.label, disabled: !!S.pending, onchange: () => { S.style = o.label; S.ownStyle = ""; const oi = $("own"); if (oi) oi.value = ""; renderGate(); } });
          return h("label", { class: "card choice radio" }, inp, h("div", { class: "row" }, h("span", { class: "box" }, ic("check")), tslot, h("div", { class: "body" }, h("div", { class: "t" }, h("b", { text: o.label })), h("p", { class: "logline", text: o.description || "" }))));
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
      const beats = arr(s.beats).slice(0, 2);
      const title = h("div", { class: "t" }, h("span", { class: "id", text: s.id }), h("b", { text: s.title }),
        s.picked && !pickMode ? h("span", { class: "chip ok" }, ic("check"), "Picked") : null, s.verdict ? h("span", { class: "chip", text: s.verdict }) : null);
      const body = h("div", { class: "body" }, title, h("div", { class: "logline" }, showMore(s.logline || "", 200, "c2")),
        beats.length ? h("ol", { class: "beats", "aria-label": "First beats" }, beats.map((b) => h("li", { text: b }))) : null);
      if (pickMode) {
        const inp = h("input", { type: "checkbox", value: s.id, checked: S.picks.has(s.id), "aria-label": s.id + ": " + s.title, onchange: () => {
          if (inp.checked) S.picks.add(s.id); else S.picks.delete(s.id);
          for (const o of list.querySelectorAll("input")) o.disabled = !o.checked && S.picks.size >= max;
          renderGate();
        }, disabled: !S.picks.has(s.id) && S.picks.size >= max });
        list.append(h("label", { class: "card choice" }, inp, h("div", { class: "row" }, h("span", { class: "box" }, ic("check")), body)));
      } else list.append(h("div", { class: "card choice static" + (s.picked ? " picked" : "") }, h("div", { class: "row" }, body)));
    }
    box.append(list);
    const c = STAGE_TAB[d.stage] === "scripts" ? checksLine() : null;
    if (c) box.append(c);
    return h("div", { class: "pane" }, box);
  }

  /* ----- storyboard ----- */
  const sceneStatus = (s) => PF.sceneStatus(s, arr(S.doc.assets));
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
    const chips = confirm ? null : h("div", { class: "chips" }, h("span", { class: "chip", text: scenes.length + (scenes.length === 1 ? " scene" : " scenes") }), h("span", { class: "chip", text: num(total) + " s" }), h("span", { class: "chip", text: b.aspect || "16:9" }));
    if (confirm) box.append(confirmCard(boards));
    box.append(h("div", { class: "board-row" }, boards.length > 1 ? storySwitch(boards) : h("div", { class: "ttl", text: b.title }), chips));
    const unmade = PF.previewRule(d, "storyboard-approved");
    if (unmade && !confirm) box.append(makeBanner(unmade.note.replace(/ Ask the agent.*$/, ""), "storyboard frames"));
    if (d.stage === "keyframes") box.append(keyframeGrid(b));
    if (b.logline && !confirm) box.append(h("div", { class: "sub" }, showMore(b.logline, 160, "c2")));
    if (!scenes.length) { box.append(h("div", { class: "empty card" }, h("div", { class: "ring" }, ic("scene")), h("h2", { text: "No scenes yet" }), h("p", { text: "This story has no scenes. The agent adds them when it writes the storyboard." }))); return h("div", { class: "pane" }, box); }
    const tl = h("div", { class: "tlwrap" }, h("div", { class: "tl", role: "group", "aria-label": "Timeline: jump to a scene" }, scenes.map((x) =>
      h("button", { type: "button", class: "k-" + sceneStatus(x).cls, "data-sid": x.id, style: "flex:" + Math.max((x.end_s - x.start_s), 0.5) + " 1 0", title: "Scene " + x.id + " " + x.beat + ", " + num(x.start_s) + " to " + num(x.end_s) + " s. " + STILLS,
        "aria-label": "Scene " + x.id + ", " + x.beat, onclick: () => jumpScene(b.id, x.id) }, h("span", { class: "fill", text: x.id })))),
      confirm ? null : h("div", { class: "tl-leg" }, [["r", "real", "All real assets ready"], ["s", "stills", "Stills only"], ["m", "mock", "Mock in plan"], ["g", "gen", "Generated"], ["t", "todo", "To capture / not made"]]
        .filter(([, k]) => scenes.some((x) => sceneStatus(x).cls === k)).map(([c, , label]) => h("span", null, h("i", { class: c }), label))),
      confirm ? null : h("p", { class: "tl-note", text: "Frames are storyboard stills, not footage." }));
    if (!confirm) box.append(tl);
    const ar = String(b.aspect || "16:9").replace(":", "/");
    const flat = [];
    const grid = h("div", { class: "scenes" });
    for (const x of scenes) grid.append(sceneCard(b, x, flat, ar, confirm));
    box.append(grid);
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
  function jumpScene(story, id) {
    const t = document.getElementById("scene-" + story + "-" + id);
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
    for (let i = 0; i < mids.length; i += 2) rows.push(h("div", { class: "frames mids" }, mk(mids[i], "Mid \u00b7 " + (mids[i].label || ""), "Mid"), h("span"), mids[i + 1] ? mk(mids[i + 1], "Mid \u00b7 " + (mids[i + 1].label || ""), "Mid") : h("span")));
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
    const gen = sc.filter((x) => x.source === "generated").length;
    const as = arr(S.doc.assets);
    const first = boards.length > 1 ? sc.length + " scenes across " + boards.length + " stories (" + boards.map((b) => b.id + ": " + arr(b.scenes).length).join(", ") + ")" : sc.length + (sc.length === 1 ? " scene" : " scenes");
    const parts = [first, gen + (gen === 1 ? " generated plate" : " generated plates")];
    for (const k of ["voice", "music"]) {
      const xs = as.filter((a) => a.kind === k);
      if (!xs.length) continue;
      parts.push(xs.some((a) => a.state === "todo" || (a.state === "ready" && fileBad(a))) ? k + " (to make)" : xs.some((a) => a.state === "mock") ? k + " (mock)" : k);
    }
    const nm = as.filter((a) => a.state === "mock").length, nt = as.filter((a) => a.state === "todo").length, nx = missingAll();
    const kf = arr(S.doc.to_make).filter((t) => t.kind === "keyframe").length;
    const open = [nm ? nm + " mock" : "", nt + kf ? nt + kf + " to make" : "", nx ? nx + " missing" : ""].filter(Boolean);
    const q = gate() && gate().question;
    return h("div", { class: "card confirm-card" }, h("b", { text: "Before you generate" }), h("div", { class: "what", text: parts.join(" \u00b7 ") }), h("p", { class: "tl-note", text: "Frames are storyboard stills, not footage." }), h("p", { text: open.length ? "Still open: " + open.join(" \u00b7 ") : "Every planned asset has its file." }), q ? h("p", { text: q }) : null);
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
    LB.items = items; LB.i = i; LB.opener = document.activeElement; LB.open = true;
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
    if (LB.opener && document.contains(LB.opener)) LB.opener.focus();
  }
  /* A clip is looked at big and with controls (pause, seek, full screen): the tile is only a poster. Same overlay, focus handling and Esc as the frames. */
  function openPlayer(a, r, sampled) {
    LB.items = []; LB.i = 0; LB.opener = document.activeElement; LB.open = true; LB.parts = null;
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
  document.addEventListener("keydown", (e) => {
    if (!LB.open) return;
    if (e.key === "Escape") { e.preventDefault(); closeLightbox(); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); lbGo(-1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); lbGo(1); }
    else if (e.key === "Tab") {
      const f = [...el.lb.querySelectorAll("button")].filter((b) => !b.disabled && b.offsetParent !== null);
      if (!f.length) return;
      const i = f.indexOf(document.activeElement);
      e.preventDefault();
      f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
    }
  });

  /* ----- assets ----- */
  const RANK = { missing: 0, mock: 1, ready: 2, todo: 3 };
  const plural = (n, one, many) => (n === 1 ? one : many);
  function viewAssets() {
    const d = S.doc, boards = arr(d.boards);
    const m = model();
    if (curBoard()) S.seen.add(PF.seenKey("assets", curBoard().id));
    const box = h("div", { class: "stack" });
    if (boards.length > 1) box.append(storySwitch(boards));
    const btn = (k, label) => h("button", { type: "button", "data-k": "f-" + k, "aria-pressed": String(S.filter === k), disabled: !m.n[k], onclick: () => { S.filter = S.filter === k ? null : k; render(true); } }, h("b", { text: m.n[k] }), " " + label);
    const parts = [btn("ready", "ready"), btn("mock", "mock"), btn("todo", "to make")];
    if (m.n.missing) parts.push(btn("missing", plural(m.n.missing, "file missing", "files missing")));
    const cnt = h("div", { class: "counter", role: "group", "aria-label": "Filter by state", "data-total": String(m.total) });
    parts.forEach((p, i) => { if (i) cnt.append(h("span", { class: "sep", "aria-hidden": "true", text: "·" })); cnt.append(p); });
    box.append(cnt);
    const miss = missingAll(), here = m.n.missing, other = miss - here;
    if (miss) box.append(h("div", { class: "warnline", role: "alert" }, ic("alert"), h("span", { text: (here ? here + " " + plural(here, "file is", "files are") + " missing." : "No files missing in this story.") + (other > 0 ? " " + other + " " + plural(other, "file is", "files are") + " missing (other story)." : "") })));
    const bare = arr(d.assets).filter((a) => !PF.hasPreview(a)).length;
    if (bare) box.append(makeBanner(bare + " " + plural(bare, "asset has", "assets have") + " nothing to look at or hear yet.", "asset samples"));
    const shown = m.items.filter((x) => !S.filter || x.eff === S.filter).sort((a, b) => RANK[a.eff] - RANK[b.eff] || a.i - b.i);
    box.append(h("div", { class: "gallery", "data-count": String(shown.length) }, shown.map((x) => (x.type === "keyframe" ? keyframeRow(x.t) : !PF.hasPreview(x.a) && (x.eff === "todo" || x.eff === "missing") ? assetRow(x) : assetTile(x)))));
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
  function audioControl(u) {
    const a = new Audio(u);
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
      lazyInto(prow, src, (u) => audioControl(u), { manual: src.size > BIG_AUDIO, manualText: "Load audio (" + fmtSize(src.size) + ")" });
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
    const sc_ = STATE_CHIP[eff];
    return h("article", { class: "card asset" + (isAudio ? " a-audio" : "") }, pv, h("div", { class: "bd" }, h("div", { class: "nm", title: a.id, text: a.label || a.id }),
      h("div", { class: "kind" }, h("span", { class: "chip", text: (KIND_LABEL[a.kind] || a.kind) + (eff === "ready" ? " · " + a.source : "") }), sc_ ? h("span", { class: "chip " + sc_[1], text: sc_[0] }) : null,
        a.source === "licensed" && !a.licence ? h("span", { class: "chip warn", text: "No licence on file" }) : null),
      sc.length ? h("div", { class: "sc", text: (sc.length === 1 ? "Scene " : "Scenes ") + sceneRange(sc) }) : null,
      sampled && a.sample_note ? h("div", { class: "how", text: "Sample: " + a.sample_note }) : null,
      how ? (a.source === "generated" ? h("details", { class: "prompt" }, h("summary", { text: "View prompt" }), h("p", { text: how })) : h("div", { class: "how" }, showMore(how, 90, "c2"))) : null,
      lic || url ? h("div", { class: "lic" }, lic, lic && url ? " · " : "", url ? h("button", { type: "button", text: host(url), title: url, onclick: () => post({ type: "open-url", url }) }) : null) : null), prow);
  }

  /* ----- draft ----- */
  const hhmm = (iso) => { const t = Date.parse(iso || ""); if (isNaN(t)) return ""; const dt = new Date(t), tm = dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); return dt.toDateString() === new Date().toDateString() ? tm : dt.toLocaleDateString([], { day: "numeric", month: "short" }) + ", " + tm; };
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
      dur.textContent = r && !r.error ? fmtSize(r.size) : "";
      if (!r) player.append(h("div", { class: "mid" }, ic("film"), h("span", { text: "This video file is not available." })));
      else if (r.error) player.append(h("div", { class: "mid", role: "alert" }, ic("alert"), h("span", { text: r.error })));
      else lazyInto(player, r, (u) => {
        const v = h("video", { src: u, controls: "", preload: "metadata", playsinline: "", "aria-label": it.label });
        v.addEventListener("loadedmetadata", () => { if (v.duration && isFinite(v.duration)) dur.textContent = fmtTime(v.duration) + (v.videoWidth ? " · " + v.videoWidth + "×" + v.videoHeight : ""); });
        return v;
      }, { manual: r.size > BIG_DRAFT, manualText: "Load video (" + fmtSize(r.size) + ")" });
      const meta = h("div", { class: "filerow" }, h("span", { text: it.label + (it.after ? " · after " + it.after : "") }), dur, it.final && it.rel ? h("span", { class: "path", text: it.rel }) : null);
      left.append(h("div", null, player, meta, it.note ? h("p", { class: "sub", style: "margin-top:4px", text: it.note }) : null));
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
      right = h("div", { class: "rounds-col" }, h("div", { class: "h2", style: "margin-bottom:8px" }, "Rounds", h("span", { class: "chip", text: chip })),
        rounds.length ? h("div", { class: "rounds" }, rounds.slice().reverse().map(roundCard)) : h("p", { class: "sub", text: "No feedback yet. Watch the draft, then approve it or send feedback." }));
    }
    return h("div", { class: "pane" }, h("div", { class: "draft-grid" + (right ? "" : " one") }, left, right));
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
      m.note = done ? "The final is delivered." : fin.registered ? "A final is registered, but its file is missing." : "Waiting on the agent. Nothing for you to do yet.";
      m.secondary = done ? "Ask for changes" : "Add a note";
      m.changes = "changes"; m.placeholder = done ? "What should change in the final?" : "Add a note for the agent."; m.sendLabel = "Send note";
      return m;
    }
    m.changes = g.kind === "draft" && used < max ? "feedback" : "changes";
    m.secondary = g.kind === "draft" && used >= max ? "Restate direction" : g.kind === "style" ? "" : g.changes_label || "Send changes";
    m.sendLabel = g.kind === "draft" ? (used >= max ? "Send direction" : "Send feedback") : g.kind === "style" ? "Send style" : "Send changes";
    m.placeholder = { style: "Describe the style you want, or paste a reference link.", approve: "What should change? Name the scene or asset if you can.", confirm: "What needs to happen before drafts?",
      draft: used >= max ? "All " + max + " rounds are used. Say what direction you want instead." : "What should change in the draft?" }[g.kind] || "What should change?";
    m.round = used + 1; m.max = max;
    m.note = { style: "Choose a style, or describe your own.", approve: g.stale ? (STAGE_LABEL[g.stage] || "This step") + " changed since you approved it." : "Approve to move on, or send changes.", confirm: "",
      draft: used >= max ? "All " + max + " rounds are used." : "Approve it, or send feedback for the next round.", pick: "" }[g.kind] || "";
    if (g.kind === "pick") {
      const n = S.picks.size;
      m.primary = n ? "Continue with " + n : "Continue";
      m.primaryDisabled = n === 0;
      m.note = n ? n + " picked" + (g.picks_max ? ". You can take up to " + g.picks_max + "." : ".") : "Pick at least one script";
    } else if (g.kind === "style") {
      m.primary = g.approve_label || "Use this style"; m.primaryDisabled = !(S.style || S.ownStyle.trim());
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
    if ((g.kind === "approve" || g.kind === "confirm" || g.kind === "draft") && gt && gt !== S.tab && tabs.some((t) => t.id === gt)) {
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
    const busy = !!S.sending;
    const note = (txt, opts = {}) => {
      el.gateNote.className = "gate-note";
      el.gateNote.replaceChildren(...(opts.spin ? [h("i", { class: "spin" })] : []), ...(opts.dot ? [h("i", { class: "qdot" })] : []), ...(opts.lock ? [ic("lock")] : []), ...(opts.check ? [ic("check")] : []), ...(txt ? [h("span", { class: "txt", text: txt })] : []));
    };
    el.btn1.hidden = el.btn2.hidden = true;
    el.btn2.removeAttribute("data-quiet");
    el.gate.hidden = m.mode === "none";
    el.gate.dataset.layout = "stack";
    el.btn1.removeAttribute("aria-describedby");
    if (m.mode === "readonly") { note("This thread is archived. You can read everything, but nothing can be sent.", { lock: true }); S.compose = false; }
    else if (m.mode === "starting") note("Waiting on the agent for the first step.", { dot: true });
    else if (m.mode === "wait") {
      note(S.stall ? (S.pending ? "Still queued. Check the chat." : "Still waiting. Check the chat.") : "Sent " + (ACTION_WORD[m.name] || "your reply") + ". Waiting for the agent to pick it up.", { spin: !S.stall });
      if (S.stall && !S.pending && S.lastAction) { el.btn2.hidden = false; el.btn2.dataset.quiet = "1"; el.btn2.textContent = "Send again"; el.btn2.disabled = busy || offlineBlocked(); el.gate.dataset.layout = "bar"; }
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

  function openCompose() { S.compose = true; renderGate(); el.note.focus(); }
  function closeCompose() { S.compose = false; S.err = ""; renderGate(); el.btn2.focus(); }
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
      if (m.g && m.g.kind === "style") return send("changes", { stage: "discover", text: "Style: " + text + refTail() });
      if (m.changes === "feedback") return send("feedback", { round: m.round, max_rounds: m.max, text });
      return send("changes", { stage: m.stage, text });
    }
    const g = m.g;
    if (m.reviewTab) { pickTab(m.reviewTab); return; }
    if (m.reviewStory) { const bi = arr(S.doc.boards).findIndex((x) => x.id === m.reviewStory.board); if (bi >= 0) { S.boardIdx = bi; S.tab = m.reviewStory.tab; S.userTab = true; render(true); el.sc.scrollTop = 0; } return; }
    if (g.kind === "pick") send("pick", { gate: g.gate, picks: [...S.picks].join(" ") });
    else if (g.kind === "style") send("changes", { stage: "discover", text: "Style: " + (S.ownStyle.trim() || S.style) + refTail() });
    else send("approve", m.draftId ? { gate: g.gate, draft: m.draftId } : { gate: g.gate });
  });

  const refTail = () => (/^https:\/\//i.test(S.ref.trim()) ? ". Reference: " + S.ref.trim() : "");
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
      if (S.compose) { el.note.value = ""; S.compose = false; }
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
    if (S.stage !== S.doc.stage) { S.stage = S.doc.stage; S.userTab = false; S.draftSel = null; S.earlier = false; S.filter = null; S.boardIdx = 0; S.seen = new Set(); }
    if (!S.userTab || !list.some((t) => t.id === S.tab)) S.tab = list.some((t) => t.id === cur) ? cur : list.length ? list[list.length - 1].id : null;
    if (!list.length) S.tab = null;
    renderHeader();
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
    if (S.pending && !S.stallTimer) startStall();
    if (!S.pending && !S.justSent) { clearTimeout(S.stallTimer); S.stallTimer = 0; S.stall = false; }
    const g = gate();
    const ids = new Set(arr(S.doc.scripts).map((s) => s.id));
    let cleared = false;
    for (const p of [...S.picks]) if (!ids.has(p) || !g || g.kind !== "pick" || gateChanged) { S.picks.delete(p); cleared = true; }
    if ((S.style || S.ownStyle) && (!g || g.kind !== "style" || gateChanged)) { S.style = null; S.ownStyle = ""; S.ref = ""; cleared = true; }
    if (gateChanged) {
      if (S.compose && el.note.value.trim()) { S.stash = { text: el.note.value.trim(), label: prevLabel || "the previous step" }; el.note.value = ""; }
      if (S.compose) S.compose = false;
      if (cleared && !wasSent) toast("Your picks were cleared because the step changed");
      if (wasEditing) S.stale = { changedGate: true };
    } else if (changedVersion && wasEditing) S.stale = S.stale || { changedGate: false };
    if (!wasEditing && !gateChanged) S.stale = null;
    S.booted = true;
    render();
    if (!first && !wasEditing && !gateChanged && changedVersion && g && !S.pending && !S.justSent && before !== JSON.stringify(sliceFor(S.tab, false))) { S.updated = true; renderBanners(); }
    if (!g) S.updated = false;
    releaseUnused();
  }

  function startBootTimer() { clearTimeout(S.bootTimer); S.bootTimer = setTimeout(() => { if (!S.booted) { S.noState = true; S.booted = true; el.app.dataset.boot = "ready"; render(true); } }, BOOT_MS); }

  window.addEventListener("message", (e) => {
    if (e.source !== window.parent) return;
    const m = e.data;
    if (!m || typeof m !== "object") return;
    switch (m.type) {
      case "init": setTheme(!!m.dark, m.tokens, !!m.reduceMotion); break;
      case "theme": setTheme(!!m.dark, m.tokens, null); break;
      case "state": if (S.noState) S.booted = hasDoc(); onState(m); break;
      case "media": onMediaReply(m); break;
      case "result": onResult(m); break;
      default: break;
    }
  });
  el.stepsBtn.addEventListener("click", () => { S.stepsOpen = !S.stepsOpen; renderHeader(); });

  /* Loading skeleton until the first state; fixed size so nothing jumps. */
  el.content.replaceChildren(h("div", { class: "pane skel", "aria-busy": "true", "aria-label": "Loading" }, h("div", { class: "sk", style: "height:22px;width:55%" }), h("div", { class: "sk", style: "height:92px" }), h("div", { class: "sk", style: "height:92px" }), h("div", { class: "sk", style: "height:92px" })));
  el.stageName.textContent = "Promo flow";
  el.stepNo.textContent = "Loading";
  el.gate.hidden = true;
  el.stepsBtn.replaceChildren(ic("chevron"));
  onAccent();
  startBootTimer();
  post({ type: "ready" });
})();
