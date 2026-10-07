"use strict";
/* Resume-a-promo picker, mounted by the host straight into its page inside a shadow root (protocol 2). It talks to the host only through ctx.post and receive.
   in:  init, state, media, result, theme     out: ready, media, action, title */
window.commissionMods = window.commissionMods || {};
window.commissionMods["promo-projects"] = function mount(ctx) {
  const PP = window.PP;
  const BADGE_TEXT = { working: "With the agent", waiting: "Your turn", done: "Done", attention: "Needs attention" };
  const ROW_BADGE = { working: "In progress", waiting: "Your turn", done: "Delivered", attention: "Needs attention" };
  const FILTERS = [["all", "All"], ["turn", "Your turn"], ["progress", "In progress"], ["done", "Delivered"]];
  const BOOT_MS = 8000, SEND_MS = 20000, MAX_NOTE = 600;
  const ICONS = {
    back: '<path d="M12.5 4l-6 6 6 6"/>',
    chevron: '<path d="M7.5 4l6 6-6 6"/>',
    play: '<path d="M7 4.5v11l9-5.5z" fill="currentColor" stroke="none"/>',
    film: '<rect x="3" y="4" width="14" height="12" rx="2"/><path d="M7 4v12M13 4v12M3 8h4M13 8h4M3 12h4M13 12h4"/>',
    check: '<path d="M4 10.5l4 4 8-9"/>',
    alert: '<path d="M10 3l8 14H2z"/><path d="M10 8v4M10 14.5v.5"/>',
    folder: '<path d="M3 6a1.5 1.5 0 0 1 1.5-1.5h3.5l2 2h5.5A1.5 1.5 0 0 1 17 8v6.5A1.5 1.5 0 0 1 15.5 16h-11A1.5 1.5 0 0 1 3 14.5z"/>',
    search: '<circle cx="9" cy="9" r="5"/><path d="M13 13l4 4"/>',
    resume: '<path d="M4 10h11M11 5.5l4.5 4.5-4.5 4.5"/>',
  };

  const $ = (id) => ctx.root.getElementById(id);
  const root = ctx.root.host;
  const el = { app: $("app"), heading: $("heading"), badge: $("badge"), badgeText: $("badgeText"), q: $("q"), slashKey: $("slashKey"), filters: $("filters"),
    banner: $("banner"), list: $("list"), peek: $("peek"), live: $("live") };
  const S = { booted: false, version: null, summary: {}, doc: {}, pending: null, offline: false, readonly: false, q: "", qSeeded: false, filter: "all",
    sel: null, view: "list", sending: null, err: "", finding: false, peekKey: "", noState: false };

  function h(tag, props, ...kids) {
    const n = document.createElement(tag);
    if (props) for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat(Infinity)) if (c != null && c !== false) n.append(c.nodeType ? c : document.createTextNode(String(c)));
    return n;
  }
  function ic(name, cls) {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 20 20"); s.setAttribute("width", "16"); s.setAttribute("height", "16"); s.setAttribute("aria-hidden", "true");
    s.setAttribute("fill", "none"); s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", "1.6"); s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round");
    s.setAttribute("class", "ic" + (cls ? " " + cls : ""));
    s.innerHTML = ICONS[name] || "";
    return s;
  }
  const arr = (x) => (Array.isArray(x) ? x : []);
  const post = ctx.post;
  const say = (t) => { el.live.textContent = ""; setTimeout(() => { el.live.textContent = t; }, 30); };
  const fmtSize = (b) => (b >= 1048576 ? Math.round(b / 1048576) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB");
  const projects = () => arr(S.doc.projects);
  const resumed = () => (S.doc.resumed && S.doc.resumed.id) || null;
  const canSend = () => !S.readonly && !S.offline && !S.sending && !S.pending && S.doc.pickable === true;
  function highlight(text) { return PP.marks(text, S.q).map(([t, hit]) => (hit ? h("mark", { text: t }) : t)); }

  /* ---------------- media over the bridge ---------------- */
  const M = { seq: 0, waiting: new Map(), cache: new Map() };
  function mref(x) {
    if (!x || typeof x !== "object") return null;
    if (x.$media && x.$media.upload_id) return x.$media;
    if ("$media" in x) return { error: x.$error || "This file could not be attached." };
    return null;
  }
  function getMedia(r) {
    const hit = M.cache.get(r.upload_id);
    if (hit) return hit;
    const p = new Promise((resolve, reject) => {
      const id = "m" + ++M.seq;
      const timer = setTimeout(() => { M.waiting.delete(id); reject(new Error("The host did not answer in time.")); }, 30000);
      M.waiting.set(id, { resolve, reject, timer, r });
      post({ type: "media", id, upload_id: r.upload_id });
    });
    p.catch(() => M.cache.delete(r.upload_id));
    M.cache.set(r.upload_id, p);
    return p;
  }
  function onMediaReply(m) {
    const w = M.waiting.get(m.id);
    if (!w) return;
    M.waiting.delete(m.id);
    clearTimeout(w.timer);
    if (!m.blob) return w.reject(new Error(m.error || "The file is not available."));
    const b = !m.blob.type && w.r.mime ? new Blob([m.blob], { type: w.r.mime }) : m.blob;
    w.resolve(URL.createObjectURL(b));
  }
  const io = "IntersectionObserver" in window ? new IntersectionObserver((es) => {
    for (const e of es) if (e.isIntersecting) { io.unobserve(e.target); const f = e.target._load; if (f) f(); }
  }, { rootMargin: "200px 0px" }) : null;
  /* An image slot that loads when scrolled near; a file the host could not attach shows as such instead of an endless skeleton. */
  function still(x, alt, cls) {
    const r = mref(x);
    const slot = h("div", { class: "still " + (cls || "") });
    if (!r) { slot.append(ic("film")); return slot; }
    if (r.error) { slot.classList.add("bad"); slot.append(ic("alert")); slot.title = "This frame could not be attached"; return slot; }
    slot.classList.add("sk");
    slot._load = () => getMedia(r).then((u) => { slot.classList.remove("sk"); slot.replaceChildren(h("img", { src: u, alt: alt || "", decoding: "async" })); },
      () => { slot.classList.remove("sk"); slot.classList.add("bad"); slot.replaceChildren(ic("alert")); slot.title = "This frame did not load"; });
    if (io) io.observe(slot); else slot._load();
    return slot;
  }

  /* ---------------- theme ---------------- */
  let tokenNames = [];
  function setTheme(dark, tokens, reduce) {
    root.dataset.theme = dark ? "dark" : "light";
    if (reduce != null) el.app.dataset.motion = reduce ? "reduce" : "";
    for (const n of tokenNames) root.style.removeProperty(n);
    tokenNames = [];
    for (const [k, v] of Object.entries(tokens || {})) {
      if (typeof v !== "string" && typeof v !== "number") continue;
      const name = k.startsWith("--") ? k : "--" + k;
      if (!/^--[a-z0-9-]+$/i.test(name)) continue;
      root.style.setProperty(name, String(v));
      tokenNames.push(name);
    }
  }

  /* ---------------- header, filters, banner ---------------- */
  function renderHeader() {
    const sm = S.summary || {};
    const badge = S.readonly ? "readonly" : sm.badge || "working";
    el.badge.dataset.badge = badge;
    el.badgeText.textContent = S.readonly ? "Read only" : BADGE_TEXT[badge] || "With the agent";
    const c = PP.counts(projects());
    el.filters.replaceChildren(...FILTERS.map(([id, label]) => h("button", { type: "button", "aria-pressed": String(S.filter === id), disabled: id !== "all" && !c[id] ? true : null,
      onclick: () => { S.filter = id; S.view = "list"; render(); } }, label, h("span", { class: "n", text: String(c[id]) }))));
  }
  function renderBanner() {
    const r = S.doc.resumed;
    let node = null;
    if (r) node = h("div", { class: "msg ok" }, ic("check"), h("div", { class: "grow" }, h("b", { text: "Carrying on with " + r.title + "." }), " It picks up at " + r.stage_label + " in the Promo flow pane of this thread."));
    else if (S.sending || S.pending) node = h("div", { class: "msg" }, h("i", { class: "spin", "aria-hidden": "true" }), h("div", { class: "grow", text: "Sent. Waiting for the agent to open it in this thread." }));
    else if (S.err) node = h("div", { class: "msg bad", role: "alert" }, ic("alert"), h("div", { class: "grow", text: S.err }));
    else if (S.offline) node = h("div", { class: "msg bad" }, ic("alert"), h("div", { class: "grow", text: "Offline. You can look around; picking a project needs the connection back." }));
    el.banner.hidden = !node;
    el.banner.replaceChildren(...(node ? [node] : []));
  }

  /* ---------------- list ---------------- */
  function bar(p) {
    return h("ol", { class: "bar", "aria-hidden": "true" }, arr(p.steps).map((s) => h("li", { class: s.state })));
  }
  function meter(p) {
    const steps = arr(p.steps);
    const i = steps.findIndex((s) => s.state === "current");
    const pct = steps.length ? Math.round(100 * (i < 0 ? steps.length : i + 1) / steps.length) : 0;
    return h("span", { class: "meter", "aria-hidden": "true" }, h("i", { style: "width:" + pct + "%" }));
  }
  function stepText(p) {
    const steps = arr(p.steps);
    const i = steps.findIndex((s) => s.state === "current");
    return i < 0 ? "All " + steps.length + " steps done" : "Step " + (i + 1) + " of " + steps.length + ": " + p.stage_label;
  }
  /* "3 scripts · 5 scenes · 4/9 assets ready · 1 draft": only what is there, zeros left out. */
  function countsLine(c) {
    const parts = [c.scripts ? c.scripts + (c.scripts === 1 ? " script" : " scripts") : "", c.scenes ? c.scenes + (c.scenes === 1 ? " scene" : " scenes") : "",
      c.assets ? c.assets_ready + "/" + c.assets + " assets ready" : "", c.drafts ? c.drafts + (c.drafts === 1 ? " draft" : " drafts") : "", c.finals ? c.finals + (c.finals === 1 ? " final" : " finals") : ""].filter(Boolean);
    return parts.length ? h("span", { class: "row-counts", text: parts.join(" · ") }) : null;
  }
  function row(p, shownSel) {
    const now = Date.now();
    const isSel = p.id === shownSel;
    const tag = p.id === resumed() ? h("span", { class: "chip ok", text: "Resumed here" }) : p.error ? h("span", { class: "chip bad", text: "Can't read" }) : h("span", { class: "chip " + PP.bucket(p), text: ROW_BADGE[p.badge] || "In progress" });
    const frames = arr(p.frames).slice(0, 3);
    /* The row carries its real frames (none drawn = none shown), the step as a thin bar, honest counts, and on the selected row the one action itself. */
    const go = isSel && !p.error && !resumed() ? h("button", { class: "btn primary row-go", type: "button", disabled: !canSend() ? true : null, "aria-label": "Resume " + (p.title || p.name) + " in this thread",
      onclick: () => send("resume", { pickable: true, id: p.id, title: p.title, stage_label: p.stage_label }) }, S.sending || S.pending ? "Opening…" : "Resume", ic("resume")) : null;
    return h("li", { class: "rowwrap" + (isSel ? " sel" : "") }, h("button", { type: "button", class: "row", "data-id": p.id, "aria-current": isSel ? "true" : null, onclick: () => open(p.id), onkeydown: rowKeys },
      h("span", { class: "row-main" },
        h("span", { class: "row-head" }, h("span", { class: "row-title" }, highlight(p.title || p.name)), h("span", { class: "row-tag", text: p.stage_label || "" }), p.updated ? h("span", { class: "row-when", text: PP.ago(p.updated, now) }) : null),
        frames.length ? h("span", { class: "row-frames", "data-n": String(frames.length), "aria-hidden": "true" }, frames.map((f) => still(f, "", "fr"))) : null,
        p.error ? h("span", { class: "row-status", text: p.error }) : [h("span", { class: "row-status" }, highlight(p.question || p.status)), countsLine(p.counts || {})],
        h("span", { class: "row-foot" }, tag, h("span", { class: "row-name mono" }, highlight(p.name))),
        bar(p)),
      ic("chevron", "chev")), go);
  }
  function visible() { return PP.search(projects(), S.q, S.filter); }
  function renderList() {
    const all = projects();
    const vis = visible();
    const shownSel = currentSel(vis);
    el.app.dataset.empty = all.length ? "" : "1";
    if (!all.length) {
      el.list.replaceChildren(h("div", { class: "empty" }, h("div", { class: "ring" }, ic("folder")), h("h2", { text: "No past promo projects yet" }),
        h("p", { text: "Projects you start with /promo-flow show up here, with where each one stopped." }), findCard()));
      return;
    }
    const kids = [];
    if (!vis.length) {
      kids.push(h("div", { class: "empty" }, h("h2", { text: S.q ? "Nothing matches “" + S.q + "”" : "No projects here" }),
        h("p", { text: S.q ? "Try fewer words, a folder name, or a step such as storyboard." : "Pick another filter." }),
        S.q || S.filter !== "all" ? h("button", { class: "btn ghost", type: "button", text: "Show all projects", onclick: () => { S.q = ""; el.q.value = ""; S.filter = "all"; render(); el.q.focus(); } }) : null));
    } else kids.push(h("ul", { class: "rows", "aria-label": vis.length + " projects" }, vis.map((p) => row(p, shownSel))));
    kids.push(findCard());
    el.list.replaceChildren(...kids);
  }
  function rowKeys(e) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const rows = [...el.list.querySelectorAll(".row")];
    const i = rows.indexOf(e.currentTarget);
    const next = rows[i + (e.key === "ArrowDown" ? 1 : -1)];
    e.preventDefault();
    if (next) next.focus(); else if (e.key === "ArrowUp") el.q.focus();
  }

  /* "Not in the list?": the person describes it and the agent goes looking (older flows outside the projects dir are not remembered). */
  function findCard() {
    if (resumed()) return null;
    if (!S.finding) return h("p", { class: "find-link" }, "Not in the list? ", h("button", { class: "link", type: "button", text: "Ask the agent to look for it", disabled: !canSend() ? true : null, onclick: () => { S.finding = true; renderList(); const t = el.list.querySelector("textarea"); if (t) t.focus(); } }));
    const box = h("textarea", { rows: "3", maxlength: String(MAX_NOTE), "data-dictate": true, "aria-label": "Where is it, or what was it about?", placeholder: "Where is it, or what was it about? For example: the launch video on my external drive" });
    if (S.q) box.value = S.q;
    const go = h("button", { class: "btn primary", type: "button", text: "Send to the agent", onclick: () => { const text = box.value.trim(); if (text) send("find", { pickable: true, text }); } });
    return h("div", { class: "find card" }, box, h("div", { class: "find-foot" }, h("slot", { name: "dictate" }), h("button", { class: "btn ghost", type: "button", text: "Cancel", onclick: () => { S.finding = false; renderList(); } }), go));
  }

  /* ---------------- peek ---------------- */
  function currentSel(vis) {
    if (S.sel && projects().some((p) => p.id === S.sel)) return S.sel;
    const r = resumed();
    /* Nothing chosen yet: the first project that waits on the person, so the outlined row and the "Your turn" badge agree. */
    const turn = vis.find((p) => PP.bucket(p) === "turn");
    return r || (turn && turn.id) || (vis[0] && vis[0].id) || null;
  }
  function open(id) {
    S.sel = id;
    S.view = "peek";
    render();
    el.peek.focus({ preventScroll: true });
    el.peek.scrollTop = 0;
  }
  function back() {
    const id = S.sel;
    S.view = "list";
    render();
    const btn = id && el.list.querySelector('.row[data-id="' + id + '"]');
    if (btn) btn.focus();
  }
  function fact(label, value) { return value == null || value === "" ? null : h("div", { class: "fact" }, h("dt", { text: label }), h("dd", { text: String(value) })); }
  function cutPlayer(p) {
    const r = mref(p.video);
    if (!p.video_label) return null;
    const slot = h("div", { class: "cut" });
    const label = h("div", { class: "cut-label" }, ic("film"), h("span", { text: "Latest cut: " + p.video_label }));
    if (!r) { slot.append(label, h("p", { class: "muted small", text: "Open the project to watch it; only the six most recent projects bring their video here." })); return slot; }
    if (r.error) { slot.append(label, h("p", { class: "muted small", text: "The video could not be attached here (it may be too large). It is in the project's folder." })); return slot; }
    const play = h("button", { class: "btn ghost", type: "button" }, ic("play"), "Play (" + fmtSize(r.size || 0) + ")");
    play.onclick = () => {
      play.disabled = true;
      play.textContent = "Loading…";
      getMedia(r).then((u) => { slot.replaceChildren(label, h("video", { src: u, controls: true, playsinline: true, preload: "metadata", "aria-label": p.video_label })); },
        () => { play.disabled = false; play.textContent = "Couldn't load. Try again"; });
    };
    slot.append(label, play);
    return slot;
  }
  function resumeBar(p) {
    const r = resumed();
    if (p.error) return h("footer", { class: "go" }, h("p", { class: "muted small", text: "This project can't be opened as it is. Ask the agent to look at its folder." }));
    if (r === p.id) return h("footer", { class: "go" }, h("p", { class: "ok-line" }, ic("check"), "This thread now carries on with it."));
    if (r) return h("footer", { class: "go" }, h("p", { class: "muted small", text: "This thread already carries on another project. Type /promo-resume in a new thread to pick this one up." }));
    const busy = !!(S.sending || S.pending);
    const why = S.readonly ? "This thread is archived." : S.offline ? "Offline." : "";
    return h("footer", { class: "go" },
      h("p", { class: "muted small", text: why || "Opens it in this thread at " + p.stage_label + ". Nothing is changed or approved." }),
      h("button", { class: "btn primary", type: "button", disabled: !canSend() ? true : null, onclick: () => send("resume", { pickable: true, id: p.id, title: p.title, stage_label: p.stage_label }) },
        busy ? "Opening…" : "Resume here", ic("resume")));
  }
  function renderPeek() {
    const vis = visible();
    const id = currentSel(vis);
    const p = projects().find((x) => x.id === id);
    const key = [S.version, id, S.q, !!S.sending, !!S.pending, S.readonly, S.offline].join("|");
    if (key === S.peekKey) return;
    S.peekKey = key;
    if (!p) { el.peek.replaceChildren(); return; }
    const now = Date.now();
    const c = p.counts || {};
    const frames = arr(p.frames);
    const when = [p.started ? "Started " + PP.day(p.started, now) : "", p.updated ? "last active " + PP.ago(p.updated, now) : ""].filter(Boolean).join(", ");
    const body = p.error ? [h("p", { class: "msg bad" }, ic("alert"), h("span", { text: p.error }))] : [
      frames.length ? h("div", { class: "frames", "data-n": String(frames.length) }, frames.map((f, i) => still(f, "Storyboard frame " + (i + 1) + " of " + p.title))) : null,
      cutPlayer(p),
      h("section", { class: "card where" },
        h("h3", { text: "Where it stopped" }),
        bar(p),
        h("p", { class: "step", text: stepText(p) }),
        p.question ? h("p", { class: "ask" }, h("b", { text: "Waiting on you: " }), p.question) : h("p", { class: "muted", text: p.status }),
        arr(p.open).length ? h("ul", { class: "open" }, arr(p.open).map((t) => h("li", null, h("i", { class: "dot", "aria-hidden": "true" }), t))) : null),
      h("section", { class: "card" },
        h("h3", { text: "What it is" }),
        h("p", { class: "brief" }, highlight(p.intent || "")),
        arr(p.picked).length ? h("div", { class: "chips" }, h("span", { class: "muted small", text: "Stories picked" }), arr(p.picked).map((t) => h("span", { class: "chip" }, highlight(t)))) : null,
        h("dl", { class: "facts" },
          fact("Style", p.style),
          fact("Scripts", c.scripts),
          fact("Scenes", c.scenes || null),
          fact("Assets ready", c.assets ? c.assets_ready + " of " + c.assets : null),
          fact("Drafts", c.drafts || null),
          fact("Review rounds", c.rounds_used ? c.rounds_used + " of " + c.rounds_max : null),
          fact("Finals", c.finals || null))),
      arr(p.approvals).length ? h("section", { class: "card" }, h("h3", { text: "Your approvals" }),
        h("ul", { class: "approvals" }, arr(p.approvals).map((a) => h("li", { class: a.fresh ? "" : "stale" }, a.fresh ? ic("check") : ic("alert"),
          h("span", { class: "grow" }, h("b", { text: a.label }), " by " + a.by), h("span", { class: "muted small", text: a.fresh ? PP.day(a.at, now) : "changed since" }))))) : null,
      arr(p.notes).length ? h("section", { class: "card" }, h("h3", { text: "Latest from the agent" }),
        h("ul", { class: "notes" }, arr(p.notes).map((n) => h("li", null, h("span", { text: n.text }), h("span", { class: "muted small", text: PP.ago(n.at, now) }))))) : null,
    ];
    el.peek.replaceChildren(
      h("div", { class: "peek-scroll" },
        h("button", { class: "back", type: "button", onclick: back }, ic("back"), "All projects"),
        h("h2", { class: "peek-title" }, highlight(p.title || p.name)),
        h("p", { class: "peek-sub" }, h("span", { class: "mono" }, highlight(p.name)), when ? " · " + when : ""),
        body,
        h("p", { class: "path" }, ic("folder"), h("span", { class: "mono", text: p.path }))),
      resumeBar(p));
  }

  /* ---------------- actions ---------------- */
  function send(name, payload) {
    if (!canSend()) return;
    const id = "a" + ++M.seq;
    S.err = "";
    S.sending = { id, timer: setTimeout(() => { if (S.sending && S.sending.id === id) { S.sending = null; S.err = "No answer from the host. Check the chat before sending again."; render(); } }, SEND_MS) };
    post({ type: "action", id, name, payload });
    render();
  }
  function onResult(m) {
    if (!S.sending || S.sending.id !== m.id) return;
    clearTimeout(S.sending.timer);
    S.sending = null;
    if (m.ok) { S.finding = false; S.err = ""; say("Sent. The agent is opening it in this thread."); }
    else S.err = m.error || "That didn't go through. Try again.";
    render();
  }

  /* ---------------- render + state ---------------- */
  function render() {
    if (!S.booted) return;
    el.app.dataset.boot = "ready";
    el.app.dataset.view = S.view;
    renderHeader();
    renderBanner();
    renderList();
    renderPeek();
  }
  function onState(m) {
    S.version = m.version;
    S.summary = m.summary || {};
    S.doc = m.state && typeof m.state === "object" && !Array.isArray(m.state) ? m.state : {};
    S.pending = m.pending || null;
    S.offline = !!m.offline;
    S.readonly = !!m.readonly;
    S.noState = false;
    clearTimeout(S.bootTimer);
    if (!S.qSeeded && typeof S.doc.query === "string" && S.doc.projects) {
      S.qSeeded = true;
      S.q = S.doc.query;
      el.q.value = S.q;
    }
    if (resumed() && S.view === "list" && !S.booted) S.sel = resumed();
    S.booted = true;
    if (!S.doc.projects) return renderStarting();
    render();
  }
  function renderStarting() {
    el.app.dataset.boot = "ready";
    renderHeader();
    renderBanner();
    el.list.replaceChildren(h("div", { class: "empty", "aria-busy": "true" }, h("i", { class: "spin", "aria-hidden": "true" }), h("p", { text: S.noState ? "Nothing arrived from the host yet." : "Gathering your past projects…" })));
    el.peek.replaceChildren();
  }

  el.q.addEventListener("input", () => { S.q = el.q.value; S.view = "list"; render(); });
  el.q.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { const r = el.list.querySelector(".row"); if (r) { e.preventDefault(); r.focus(); } }
    else if (e.key === "Enter") { const r = el.list.querySelector(".row"); if (r) { e.preventDefault(); open(r.dataset.id); } }
    else if (e.key === "Escape" && el.q.value) { e.preventDefault(); el.q.value = ""; S.q = ""; render(); }
  });
  el.app.addEventListener("keydown", (e) => {
    const t = ctx.root.activeElement;
    const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA");
    if (e.key === "/" && !typing && !e.metaKey && !e.ctrlKey) { e.preventDefault(); el.q.focus(); el.q.select(); }
    else if (e.key === "Escape" && S.view === "peek" && !typing) { e.preventDefault(); back(); }
  });

  function receive(m) {
    if (!m || typeof m !== "object") return;
    switch (m.type) {
      case "init": setTheme(!!m.dark, m.tokens, !!m.reduceMotion); break;
      case "theme": setTheme(!!m.dark, m.tokens, null); break;
      case "state": onState(m); break;
      case "media": onMediaReply(m); break;
      case "result": onResult(m); break;
      default: break;
    }
  }
  function unmount() {
    clearTimeout(S.bootTimer);
    if (S.sending) clearTimeout(S.sending.timer);
    if (io) io.disconnect();
    for (const p of M.cache.values()) p.then((u) => URL.revokeObjectURL(u), () => {});
    M.cache.clear();
  }

  S.bootTimer = setTimeout(() => { if (!S.booted) { S.noState = true; S.booted = true; renderStarting(); } }, BOOT_MS);
  el.list.replaceChildren(h("div", { class: "empty", "aria-busy": "true" }, h("i", { class: "spin", "aria-hidden": "true" }), h("p", { text: "Loading…" })));
  post({ type: "ready" });
  return { receive, unmount };
};
