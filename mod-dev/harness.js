"use strict";
/* Plays the host for mods/promo-flow: mounts it in this page inside a shadow root (protocol 2), canned states from serve.py. */
(() => {
  const q = new URLSearchParams(location.search);
  const $ = (id) => document.getElementById(id);
  const pane = $("pane");
  let mod = null, shadow = null;
  const MOD = q.get("mod") || "promo-flow";
  /* Stages named picker* are states of the promo-projects mod; the rest are promo-flow's. */
  const mine = (id) => (MOD === "promo-projects") === id.startsWith("picker");
  const LIGHT = { "--ink": "#1c1a16", "--dim": "#6b665c", "--well": "#f4f2ed", "--raised": "#ffffff", "--accent": "#b4531f", "--line": "#e2ded3", "--radius": "12px", "--font": 'ui-sans-serif, -apple-system, "Segoe UI", system-ui, sans-serif' };
  const DARK = { "--ink": "#ece8df", "--dim": "#9d978a", "--well": "#15130f", "--raised": "#1f1c17", "--accent": "#e58c55", "--line": "#35312a", "--radius": "12px", "--font": LIGHT["--font"] };
  const H = { stage: q.get("stage") || (MOD === "promo-projects" ? "picker" : "discover"), dark: q.get("dark") === "1", width: +q.get("w") || 520, offline: false, readonly: false, reduce: false, hold: false, noPending: false, mediaErr: false, slow: false,
    version: 1, pending: null, stages: [], docs: {}, manifest: null, ready: false };

  const log = (t) => { const d = document.createElement("div"); d.textContent = new Date().toTimeString().slice(0, 8) + "  " + t; $("log").prepend(d); if ($("log").children.length > 80) $("log").lastChild.remove(); };
  const post = (m) => mod && mod.receive(m);

  const isLive = (id) => H.stages.some((s) => s.id === id && s.live);
  async function stageDoc(id) {
    if (!H.docs[id] || isLive(id)) H.docs[id] = await (await fetch("/api/state/" + id)).json();
    return H.docs[id];
  }
  async function sendState() {
    if (!H.ready || H.hold) return;
    const d = await stageDoc(H.stage);
    $("ver").textContent = H.version;
    post({ type: "state", version: H.version, updated_at: new Date().toISOString(), summary: d.summary, state: d.state, pending: H.pending, offline: H.offline, readonly: H.readonly });
  }
  const tokens = () => (H.dark ? DARK : LIGHT);
  const sendInit = () => post({ type: "init", protocol: 1, dark: H.dark, tokens: tokens(), reduceMotion: H.reduce });

  function ptr(doc, p) { return p.split("/").slice(1).reduce((o, k) => (o == null ? o : o[k]), doc); }
  const render = (tpl, vars) => tpl.replace(/\{(\w+)\}/g, (_, k) => { const v = vars[k]; return v == null ? "" : Array.isArray(v) ? v.join(", ") : String(v); });

  async function onAction(m) {
    const a = H.manifest && H.manifest.actions[m.name];
    const by = "Sam";
    if (!a) { post({ type: "result", id: m.id, ok: false, error: "Unknown action " + m.name }); return log("action " + m.name + " REJECTED 404"); }
    const d = await stageDoc(H.stage);
    if (a.guard && String(ptr(d.state, a.guard.state)) !== String(m.payload[a.guard.payload])) {
      post({ type: "result", id: m.id, ok: false, error: "That step has moved on. The view was refreshed." });
      return log("action " + m.name + " REJECTED 409 guard " + a.guard.state + " != " + m.payload[a.guard.payload]);
    }
    if (H.readonly) { post({ type: "result", id: m.id, ok: false, error: "This thread is archived" }); return log("action REJECTED 409 archived"); }
    log("action " + m.name + " -> " + render(a.message, { ...m.payload, by }).slice(0, 400));
    if (isLive(H.stage)) {
      const r = await (await fetch("/api/action", { method: "POST", body: JSON.stringify({ name: m.name, payload: m.payload }) })).json();
      log("live " + m.name + (r.ok ? " ok: " + (r.message || "ran the flow command") : " REFUSED: " + r.error));
      if (!r.ok) return post({ type: "result", id: m.id, ok: false, error: r.error });
      post({ type: "result", id: m.id, ok: true });
      H.pending = r.pending ? { name: m.name } : null; H.version++;
      return sendState();
    }
    setTimeout(() => { post({ type: "result", id: m.id, ok: true }); H.pending = H.noPending ? null : { name: m.name }; sendState(); }, 250);
  }
  async function onMedia(m) {
    if (H.slow) await new Promise((r) => setTimeout(r, 1500));
    if (H.mediaErr) { post({ type: "media", id: m.id, blob: null, error: "Simulated media failure" }); return log("media " + m.upload_id.slice(0, 8) + " FAILED (simulated)"); }
    try {
      const r = await fetch("/media/" + m.upload_id);
      if (!r.ok) throw new Error(r.status);
      const blob = await r.blob();
      post({ type: "media", id: m.id, blob });
      log("media " + m.upload_id.slice(0, 8) + " " + (blob.size >> 10) + " KB " + blob.type);
    } catch (e) { post({ type: "media", id: m.id, blob: null, error: String(e) }); }
  }

  function onModMessage(m) {
    if (m.type === "ready") { H.ready = true; log("ready"); sendInit(); sendState(); }
    else if (m.type === "media") onMedia(m);
    else if (m.type === "action") { log("action request " + m.name + " " + JSON.stringify(m.payload).slice(0, 160)); onAction(m); }
    else if (m.type === "title") log("title: " + m.text + (m.text.length > 40 ? "  (TOO LONG)" : ""));
    else if (m.type === "open-url") log("open-url " + m.url + (/^https:\/\//i.test(m.url) ? "" : "  (REFUSED: not https)"));
    else log("? " + JSON.stringify(m).slice(0, 120));
  }

  /* Stands in for Commission's voice button, slotted into the mod's dictate slot: it writes into the [data-dictate] field the way the host's dictation does. */
  function fakeMic() {
    const b = Object.assign(document.createElement("button"), { type: "button", slot: "dictate", textContent: "Mic", title: "Fake dictation (harness)" });
    b.onclick = () => {
      const t = shadow.querySelector("[data-dictate]");
      t.value += (t.value && !/\s$/.test(t.value) ? " " : "") + "make the second scene shorter";
      t.dispatchEvent(new Event("input", { bubbles: true }));
      t.focus();
    };
    return b;
  }

  async function load() {
    H.ready = false; H.pending = null;
    if (mod) mod.unmount();
    mod = null;
    const base = new URL("/mods/" + MOD + "/", location.href);
    const doc = new DOMParser().parseFromString(await (await fetch(new URL("index.html", base), { cache: "no-store" })).text(), "text/html");
    const host = document.createElement("div");
    host.style.height = "100%";
    shadow = host.attachShadow({ mode: "open" });
    for (const l of doc.querySelectorAll('link[rel="stylesheet"]')) shadow.append(Object.assign(document.createElement("link"), { rel: "stylesheet", href: new URL(l.getAttribute("href"), base).href }));
    const scripts = [...doc.body.querySelectorAll("script[src]")].map((x) => { x.remove(); return new URL(x.getAttribute("src"), base).href; });
    shadow.append(...doc.body.childNodes);
    host.append(fakeMic());
    pane.replaceChildren(host);
    for (const x of document.head.querySelectorAll("script[data-mod]")) x.remove();
    for (const src of scripts) {
      const tag = Object.assign(document.createElement("script"), { src: src + "?" + Date.now() });
      tag.dataset.mod = MOD;
      await new Promise((ok, fail) => { tag.onload = ok; tag.onerror = () => fail(new Error("Could not load " + src)); document.head.append(tag); });
    }
    // Mod messages are handled after the call returns, as the host does, so "ready" sent during mount finds mod.receive in place.
    mod = window.commissionMods[MOD]({ root: shadow, post: (m) => queueMicrotask(() => onModMessage(m)) });
    window.harness.root = shadow;
  }
  function paintControls() {
    $("dark").setAttribute("aria-pressed", H.dark);
    pane.style.width = q.get("bare") ? "" : H.width + "px";
    for (const b of $("widths").children) b.setAttribute("aria-pressed", String(+b.dataset.w === H.width));
    for (const b of $("stages").children) b.setAttribute("aria-pressed", String(b.dataset.id === H.stage));
  }
  function setStage(id) { H.stage = id; H.pending = null; H.version++; paintControls(); sendState(); }

  async function boot() {
    if (q.get("bare")) document.body.classList.add("bare");
    H.manifest = await (await fetch("/mods/" + MOD + "/mod.json")).json();
    H.stages = (await (await fetch("/api/stages")).json()).filter((s) => mine(s.id));
    for (const s of H.stages) $("stages").append(Object.assign(document.createElement("button"), { type: "button", textContent: s.id, onclick: () => setStage(s.id), className: "", innerHTML: `<span>${s.id}</span><small>${s.badge}</small>` }, { }));
    [...$("stages").children].forEach((b, i) => { b.dataset.id = H.stages[i].id; });
    for (const w of [380, 520, 900]) $("widths").append(Object.assign(document.createElement("button"), { type: "button", textContent: w + " px", onclick: () => { H.width = w; paintControls(); } }));
    [...$("widths").children].forEach((b, i) => { b.dataset.w = [380, 520, 900][i]; });
    $("dark").onclick = () => { H.dark = !H.dark; paintControls(); post({ type: "theme", dark: H.dark, tokens: tokens() }); };
    $("reload").onclick = load;
    for (const [id, key] of [["offline", "offline"], ["readonly", "readonly"], ["hold", "hold"], ["mediaErr", "mediaErr"], ["slow", "slow"], ["noPending", "noPending"]]) $(id).onchange = (e) => { H[key] = e.target.checked; H.version += key === "hold" ? 0 : 0; sendState(); };
    $("reduce").onchange = (e) => { H.reduce = e.target.checked; sendInit(); };
    $("bump").onclick = () => { H.version++; sendState(); log("version -> " + H.version); };
    if (isLive(H.stage)) setInterval(() => { H.version++; sendState(); }, 15000);
    $("bumpGate").onclick = () => { const i = H.stages.findIndex((s) => s.id === H.stage); H.stage = H.stages[Math.min(i + 1, 9)].id; H.version++; paintControls(); sendState(); log("step changed under the person -> " + H.stage); };
    $("respond").onclick = () => { const i = H.stages.findIndex((s) => s.id === H.stage); H.pending = null; H.stage = H.stages[Math.min(i + 1, 9)].id; H.version++; paintControls(); sendState(); };
    if (q.get("offline")) { H.offline = true; $("offline").checked = true; }
    if (q.get("readonly")) { H.readonly = true; $("readonly").checked = true; }
    if (q.get("reduce")) { H.reduce = true; $("reduce").checked = true; }
    if (q.get("hold")) { H.hold = true; $("hold").checked = true; }
    paintControls();
    window.harness = { H, setStage, sendState, load, post };
    load();
  }
  boot();
})();
