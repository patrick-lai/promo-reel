"use strict";
/* The Stage's timeline editor: a bin of everything the video can use, a viewer that plays the edit as it stands, an inspector for what is selected
   and a multitrack timeline (picture, captions, voice, music, sound effects). Every change is an op of the edit language (PF.editParse /
   promo/editor.py); the ops apply here at once to a copy of the timeline (PF.editApply) for the preview, and one Render sends them to the agent.
   Playback: the clock is the AudioContext's; picture comes from two <video> elements taking turns (each shot's rendered segment, or its source
   footage at t_in with a "Not rendered yet" badge), sound from decoded buffers: the music edit (or another track from its offset), each voice line
   and each sound effect at its time, with the bus levels and a simple duck under the voice. It is a rough mix: Render makes the real one. */
(function (root) {
  const PF = root.PF;
  const arr = (x) => (Array.isArray(x) ? x : []);
  const dbg = (db) => Math.pow(10, (+db || 0) / 20);
  /* Zoom is a factor of Fit (the whole film across the timeline), so 2x means the same on a 15 s cut and a 60 s one. */
  const ZOOM_STEPS = [1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32];
  const ZOOM_PRESETS = [[1, "Fit"], [2, "2×"], [4, "4×"], [8, "8×"]];
  const PPS_MAX = 600;
  const LANES = [["v", "Picture"], ["cap", "Captions"], ["vo", "Voice"], ["music", "Music"], ["sfx", "Sound effects"]];
  const AUDIO_LANES = ["vo", "music", "sfx"];
  const KIND_ICON = { footage: "film", plate: "image", music: "music", sfx: "wave", voice: "wave", script: "doc", draft: "film" };
  const BIN_GROUPS = [["footage", "Footage"], ["plate", "Plates"], ["music", "Music"], ["voice", "Voice"], ["sfx", "Sound effects"], ["script", "Scripts"], ["draft", "Drafts"]];
  const two = (n) => String(n).padStart(2, "0");
  const clock = (s) => { s = Math.max(0, s || 0); const t = Math.floor(s * 10 + 1e-6); return Math.floor(t / 600) + ":" + two(Math.floor(t / 10) % 60) + "." + (t % 10); };
  const same = (a, b, skip) => JSON.stringify(strip(a, skip)) === JSON.stringify(strip(b, skip));
  function strip(x, skip) { if (!x || typeof x !== "object") return x; const o = {}; for (const k of Object.keys(x).sort()) if (!skip.includes(k)) o[k] = x[k]; return o; }
  const beatsOf = (s) => ("beats" in s ? [+s.beats[0], +s.beats[1]] : [s.bars[0] * 4, s.bars[1] * 4]);
  const captionOf = (s) => { const c = arr(s.overlays).find((v) => v && v.type === "caption"); return c ? c : null; };

  function create(o) {
    const { h, ic } = o;
    let edit = o.edit || {}, bin = o.bin || {}, readonly = !!o.readonly;
    let stack = { done: [], undone: [] }, sent = null, sentSig = null, trying = null, err = "", hidden = new Set();
    let sel = null, pps = 36, zf = 1, playhead = 0, playing = null, raf = 0, dragging = null, binTab = "here", binQ = "", binOpen = false, showPending = false;
    const mon = { v: { mute: false, solo: false }, vo: { mute: false, solo: false }, music: { mute: false, solo: false }, sfx: { mute: false, solo: false } };
    const urls = new Map(), bufs = new Map();
    let ctx = null;

    /* ---------- the derived timeline: the published spec with the person's pending edits (and a suggestion being tried) applied ---------- */
    const B = () => edit.beat_s || 0.5;
    const sugOps = (id) => { const s = arr(edit.suggestions).find((x) => x.id === id); if (!s) return []; try { return PF.editParse(s.text); } catch (e) { return []; } };
    function derive(extra) {
      const ops = [...stack.done, ...(extra || [])];
      return PF.editApply(edit.spec || {}, ops, B(), edit.beats_per_bar || 4);
    }
    let D = null;
    function rebuild() {
      let r;
      try { r = derive(trying ? sugOps(trying) : null); }
      catch (e) { err = e.message; trying = null; r = derive(); }
      const raw = r.raw, origin = r.origin;
      const view = new Map(arr(edit.shots).map((s) => [String(s.id), s]));
      const specShots = new Map(arr((edit.spec || {}).shots).map((s) => [String(s.id), s]));
      const shots = arr(raw.shots).map((s, i) => {
        const [b0, b1] = beatsOf(s), id = String(s.id), oid = view.has(id) ? id : origin[id] || null;
        return { id, i, b0, b1, t0: b0 * B(), t1: b1 * B(), cfg: s, v: oid ? view.get(oid) : null, spec: oid ? specShots.get(oid) : null, idx: oid ? arr(edit.shots).findIndex((x) => String(x.id) === oid) : -1 };
      });
      for (const s of shots) s.media = clipMedia(s);
      const startOf = new Map(shots.map((s) => [s.id, s]));
      const vo = arr((raw.vo || {}).lines).map((ln) => {
        const lid = String(ln.id != null ? ln.id : ln.shot), v = arr((edit.vo || {}).lines).find((x) => x.id === lid) || {}, sh = startOf.get(String(ln.shot));
        const file = ln.file && v.file && specLine(lid) && specLine(lid).file !== ln.file ? takeMedia(ln.file) : v.file;
        return { id: lid, shot: String(ln.shot), at: +ln.at || 0, t: sh ? sh.t0 + (+ln.at || 0) : null, dur: v.dur || 1.5, text: ln.text, muted: !!ln.mute, db: +ln.db || 0,
          gain: (v.gain_db != null ? v.gain_db - (v.db || 0) : 0) + (+ln.db || 0), file, changed: !v.id || v.muted !== !!ln.mute || v.at !== ln.at || String(v.shot) !== String(ln.shot) || (v.db || 0) !== (+ln.db || 0) };
      });
      const sfx = [];
      for (const s of shots) arr(s.cfg.sfx).forEach((e, k) => { if ("at" in e) sfx.push({ shot: s.id, i: k + 1, name: e.sfx, at: +e.at, t: s.t0 + +e.at, db: +e.db || 0 }); });
      const m = raw.music || null, m0 = (edit.spec || {}).music || null;
      const noGains = (e) => JSON.stringify({ ...(e || {}), gains: null });
      const g0 = arr(((m0 || {}).edit || {}).gains).map((g) => JSON.stringify(g));
      const music = m ? { asset: m.asset, offset: +m.track_offset || 0, edited: !m0 || m.asset !== m0.asset || noGains(m.edit) !== noGains(m0.edit) || m.track_offset !== m0.track_offset,
        gains: arr((m.edit || {}).gains).filter((g) => !g0.includes(JSON.stringify(g))), fx: !!m.fx !== !!(m0 || {}).fx || JSON.stringify(m.fx) !== JSON.stringify((m0 || {}).fx) } : null;
      const buses = { ...(edit.buses || {}), ...(((raw.mix || {}).bus_db) || {}) };
      const dur = shots.length ? shots[shots.length - 1].t1 : edit.duration || 0;
      D = { raw, shots, vo, sfx, music, buses, dur, origin };
      if (playhead > dur) playhead = dur;
    }
    const specLine = (lid) => arr(((edit.spec || {}).vo || {}).lines).find((x) => String(x.id != null ? x.id : x.shot) === lid);
    function binItem(key) {
      for (const it of arr(bin.here)) if (it.key === key) return it;
      const i = key.indexOf(":"), kind = key.slice(0, i), id = key.slice(i + 1);
      for (const p of arr(bin.projects)) for (const it of arr(p.items)) if (it.kind === kind || (kind === "footage" && it.kind === "plate")) if (PF.localId(p.name + ":" + it.id) === id) return it;
      return null;
    }
    const takeMedia = (file) => { const it = arr(bin.here).find((x) => x.kind === "voice" && x.id === file); return it ? it.media : null; };
    /* What plays for a shot: its rendered segment when the shot is as rendered (moved or trimmed at the end is fine), the same segment further in for
       the second half of a split, else its source footage at t_in. */
    function clipMedia(s) {
      const v = s.v, cfg = s.cfg, sp = s.spec;
      if (v && v.seg && sp && same(cfg, sp, ["beats", "bars", "id"]) && s.id === v.id) return { ref: v.seg, off: 0, speed: 1, rendered: Math.abs((s.t1 - s.t0) - (v.end_s - v.start_s)) < 1e-6, kind: "video" };
      if (v && v.seg && sp && same(cfg, sp, ["beats", "bars", "id", "t_in"])) return { ref: v.seg, off: ((+cfg.t_in || 0) - (+sp.t_in || 0)) / (+cfg.speed || 1), speed: 1, rendered: false, kind: "video" };
      const src = cfg.source;
      const it = src ? binItem("footage:" + src) || binItem("plate:" + src) : null;
      const ref = (it && it.media) || (v && v.source === src && v.src_preview) || null;
      if (ref) { const r = PF.mref(ref); const still = r && /^image\//.test(r.mime || "") || /\.(png|jpe?g|webp)$/i.test((r && r.name) || ""); return { ref, off: +cfg.t_in || 0, speed: +cfg.speed || 1, rendered: false, kind: still ? "image" : "video", poster: it && it.poster }; }
      return { ref: null, rendered: false, kind: "none", poster: it && it.poster };
    }

    /* ---------- ops ---------- */
    function push(op) {
      if (readonly) return false;
      try { derive([op]); } catch (e) { flash(e.message); return false; }
      stack = PF.editPush(stack, op); err = "";
      changed();
      return true;
    }
    function changed() { rebuild(); paint(); if (o.onOps) o.onOps(stack.done); }
    const undo = () => { if (!stack.done.length) return; stack = PF.editUndo(stack); changed(); };
    const redo = () => { if (!stack.undone.length) return; stack = PF.editRedo(stack); changed(); };

    /* ---------- DOM ---------- */
    const binBox = h("aside", { class: "ed-bin", "aria-label": "Bin" });
    const vA = h("video", { muted: "", playsinline: "", preload: "auto", "aria-hidden": "true" }), vB = h("video", { muted: "", playsinline: "", preload: "auto", "aria-hidden": "true" });
    vA.muted = vB.muted = true;
    const still = h("img", { alt: "", hidden: true });
    const slate = h("div", { class: "ed-slate", hidden: true });
    const badge = h("span", { class: "ed-badge", hidden: true }, ic("clock"), h("span", { text: "Not rendered yet" }));
    const capOv = h("div", { class: "ed-cap", hidden: true });
    const tcode = h("span", { class: "ed-tc", "aria-live": "off" });
    const playBtn = h("button", { type: "button", class: "ed-b", "data-k": "ed-play", "aria-label": "Play (Space)", title: "Play (Space)", onclick: () => toggle() }, ic("play"));
    const stage = h("div", { class: "ed-stage" }, vA, vB, still, slate, capOv, badge);
    const viewer = h("section", { class: "ed-viewer", "aria-label": "Viewer" }, stage,
      h("div", { class: "ed-vbar" }, playBtn, tcode, h("span", { class: "ed-rough", text: "Rough mix. Render for the final mix." })));
    const insp = h("aside", { class: "ed-insp", "aria-label": "Inspector" });
    const heads = h("div", { class: "ed-heads" });
    const lanes = h("div", { class: "ed-lanes", tabindex: "0", role: "application", "aria-label": "Timeline. Space plays, B splits, Delete removes, Cmd+Z undoes, + and − zoom, 0 fits, Z zooms to the shot." });
    const scroller = h("div", { class: "ed-scroll" }, lanes);
    const tl = h("div", { class: "ed-tl" }, heads, scroller);
    const zbar = h("div", { class: "ed-zbar", role: "toolbar", "aria-label": "Timeline zoom" });
    const tlw = h("div", { class: "ed-tlw" }, zbar, tl);
    const foot = h("div", { class: "ed-foot" });
    const note = h("p", { class: "ed-note", role: "status" });
    const binBtn = h("button", { type: "button", class: "ed-binbtn btn ghost sm", "data-k": "ed-bin-toggle", "aria-expanded": "false", onclick: () => { binOpen = !binOpen; paintBin(); } }, ic("folder"), h("span", { text: "Bin" }));
    const el = h("div", { class: "ed", "data-k": "editor" }, h("div", { class: "ed-top" }, binBtn, note), h("div", { class: "ed-grid" }, binBox, viewer, insp), tlw, foot);
    let flashTimer = 0;
    function flash(t) { err = t; paintNote(); clearTimeout(flashTimer); flashTimer = setTimeout(() => { err = ""; paintNote(); }, 7000); }

    /* ---------- media ---------- */
    function urlOf(ref) {
      const r = PF.mref(ref);
      if (!r || r.error) return Promise.reject(new Error("no file"));
      if (!urls.has(r.upload_id)) urls.set(r.upload_id, o.getMedia(r));
      return urls.get(r.upload_id);
    }
    function audioCtx() { if (!ctx) { const C = root.AudioContext || root.webkitAudioContext; ctx = C ? new C() : null; } return ctx; }
    function bufferOf(ref) {
      const r = PF.mref(ref);
      if (!r || r.error || !audioCtx()) return Promise.resolve(null);
      if (!bufs.has(r.upload_id)) bufs.set(r.upload_id, urlOf(ref).then((u) => fetch(u)).then((x) => x.arrayBuffer()).then((ab) => ctx.decodeAudioData(ab)).catch(() => null));
      return bufs.get(r.upload_id);
    }
    const audible = (lane) => { const solo = AUDIO_LANES.concat(["v"]).some((k) => mon[k].solo); return !mon[lane].mute && (!solo || mon[lane].solo); };

    /* ---------- playback ---------- */
    function musicSource() {
      const m = D.music;
      if (!m) return null;
      if (!m.edited && edit.music && edit.music.file) return { ref: edit.music.file, off: 0 };
      const it = binItem("music:" + m.asset);
      const ref = (it && it.media) || (edit.music && edit.music.asset === m.asset ? edit.music.raw : null);
      return ref ? { ref, off: m.offset } : null;
    }
    async function start() {
      if (playing || !D) return;
      const c = audioCtx();
      if (c && c.state === "suspended") await c.resume().catch(() => {});
      if (playhead >= D.dur - 0.05) playhead = 0;
      const token = {};
      playing = token;
      paint();
      const from = playhead;
      const ms = musicSource();
      const need = [ms && bufferOf(ms.ref), ...D.vo.filter((l) => !l.muted && l.file).map((l) => bufferOf(l.file)),
        ...D.sfx.map((e) => { const f = sfxRef(e.name); return f ? bufferOf(f) : null; })];
      note.textContent = "Loading sound…";
      await Promise.all(need.filter(Boolean));
      if (playing !== token) return;
      paintNote();
      const now = c ? c.currentTime + 0.08 : 0;
      token.c0 = now; token.t0 = from; token.nodes = [];
      if (c) {
        const master = c.createGain(); master.connect(c.destination); token.nodes.push(master);
        const bus = (lane) => { const g = c.createGain(); g.gain.value = audible(lane) ? dbg(D.buses[lane]) : 0; g.connect(master); token[lane] = g; token.nodes.push(g); return g; };
        const gM = bus("music"), gV = bus("vo"), gS = bus("sfx");
        const at = (t) => now + Math.max(0, t - from);
        const play = (buf, dest, t, gain, offset) => {
          if (!buf) return;
          const off = (offset || 0) + Math.max(0, from - t);
          if (off >= buf.duration) return;
          const s = c.createBufferSource(); s.buffer = buf;
          const g = c.createGain(); g.gain.value = gain; s.connect(g); g.connect(dest);
          s.start(at(t), off); token.nodes.push(s, g);
          return g;
        };
        if (ms) {
          const gg = c.createGain(); gg.connect(gM); token.nodes.push(gg);           /* level changes not in the built music edit yet (gain music ...) */
          for (const r of D.music.gains) {
            const a = +r.beats[0] * B(), b = +r.beats[1] * B(), ramp = +r.ramp || 0;
            if (b <= from) continue;
            if (ramp && a - ramp > from) gg.gain.setValueAtTime(1, at(a - ramp));
            gg.gain.linearRampToValueAtTime(dbg(r.db), at(a)); gg.gain.setValueAtTime(dbg(r.db), at(Math.max(a, from))); gg.gain.setValueAtTime(1, at(b));
          }
          const g = play(await bufferOf(ms.ref), gg, 0, 1, ms.off);
          if (g) {
            const dk = edit.duck || {}, down = dbg(-(dk.db || 7));
            for (const l of D.vo) if (!l.muted && l.t != null) {
              const a = l.t - (dk.pre || 0.12), b = l.t + l.dur + (dk.post || 0.1);
              if (b <= from) continue;
              g.gain.setTargetAtTime(down, at(a), 0.04); g.gain.setTargetAtTime(1, at(b), 0.12);
            }
          }
        }
        for (const l of D.vo) if (!l.muted && l.file && l.t != null) play(await bufferOf(l.file), gV, l.t, dbg(l.gain));
        for (const e of D.sfx) { const f = sfxRef(e.name); if (f) play(await bufferOf(f), gS, e.t, dbg(e.db)); }
      }
      token.started = performance.now();
      raf = requestAnimationFrame(tick);
    }
    const sfxRef = (name) => { const s = arr(edit.sfx_lib).find((x) => x.name === name); if (s && s.file) return s.file; const it = binItem("sfx:" + name); return it ? it.media : null; };
    function now() { if (!playing || playing.c0 == null) return playhead; const c = ctx; return playing.t0 + (c ? Math.max(0, c.currentTime - playing.c0) : (performance.now() - playing.started) / 1000); }
    function stop() {
      if (!playing) return;
      const p = playing;
      playhead = now();
      playing = null;
      cancelAnimationFrame(raf);
      for (const n of p.nodes || []) { try { if (n.stop) n.stop(); n.disconnect(); } catch (_) { /* already ended */ } }
      vA.pause(); vB.pause();
      paint();
    }
    function toggle() { if (playing) stop(); else start(); }
    function tick() {
      if (!playing) return;
      const t = now();
      if (t >= D.dur) { playhead = D.dur; stop(); return; }
      playhead = t;
      showAt(t, true);
      paintHead();
      raf = requestAnimationFrame(tick);
    }
    const shotAt = (t) => D.shots.find((s) => t >= s.t0 - 1e-6 && t < s.t1 - 1e-6) || D.shots[D.shots.length - 1];
    const vKey = (v) => v.dataset.key || "";
    async function load(v, ref) {
      const r = PF.mref(ref);
      if (vKey(v) === r.upload_id) return v;
      v.dataset.key = r.upload_id;
      const u = await urlOf(ref).catch(() => null);
      if (u && vKey(v) === r.upload_id) v.src = u;
      return v;
    }
    let cur = vA;
    function showAt(t, live) {
      const s = shotAt(t);
      if (!s) return;
      const m = s.media, lt = t - s.t0;
      badge.hidden = m.rendered;
      const cap = captionOf(s.cfg);
      const showCap = !m.rendered && cap && (!Array.isArray(cap.t) || (lt >= +cap.t[0] && lt < +cap.t[1]));
      capOv.hidden = !showCap; if (showCap) capOv.textContent = cap.text;
      const vis = mon.v.mute ? false : true;
      /* a grade or fade not rendered yet: shown with CSS on the picture (rough; the render uses ffmpeg's filters) */
      const look = [];
      const gr = !m.rendered && s.cfg.grade;
      if (gr) { if (gr.brightness != null) look.push("brightness(" + (1 + +gr.brightness) + ")"); if (gr.contrast != null) look.push("contrast(" + gr.contrast + ")"); if (gr.saturation != null) look.push("saturate(" + gr.saturation + ")");
        if (gr.temperature) look.push((+gr.temperature < 6500 ? "sepia(" : "hue-rotate(") + (+gr.temperature < 6500 ? Math.min(0.6, (6500 - gr.temperature) / 6500) : Math.min(20, (gr.temperature - 6500) / 200) + "deg") + ")"); }
      const fd = !m.rendered && s.cfg.fade, dur = s.t1 - s.t0;
      const op = fd ? Math.min(fd.in ? Math.min(1, lt / fd.in) : 1, fd.out ? Math.min(1, (dur - lt) / fd.out) : 1) : 1;
      for (const x of [vA, vB, still]) { x.style.filter = look.join(" "); x.style.opacity = String(Math.max(0, op)); }
      if (m.kind === "image" && vis) {
        urlOf(m.ref).then((u) => { if (still.src !== u) still.src = u; });
        still.hidden = false; slate.hidden = true; vA.hidden = vB.hidden = true; vA.pause(); vB.pause();
        return;
      }
      still.hidden = true;
      if (m.kind !== "video" || !vis) {
        slate.hidden = false; vA.hidden = vB.hidden = true; vA.pause(); vB.pause();
        slate.replaceChildren(ic("film"), h("b", { text: "Shot " + s.id }), h("span", { text: m.kind === "none" ? "Nothing to show yet: Render makes this shot." : "Picture off (muted)" }));
        return;
      }
      slate.hidden = true;
      const want = m.off + lt * (m.speed || 1);
      const r = PF.mref(m.ref);
      const v = vKey(vA) === r.upload_id ? vA : vKey(vB) === r.upload_id ? vB : (cur === vA ? vB : vA);
      if (vKey(v) !== r.upload_id) load(v, m.ref);
      if (v !== cur) { cur.pause(); cur = v; }
      vA.hidden = cur !== vA; vB.hidden = cur !== vB;
      cur.playbackRate = m.speed || 1;
      if (cur.readyState >= 1) {
        if (Math.abs(cur.currentTime - want) > (live ? 0.25 : 0.02)) cur.currentTime = Math.min(Math.max(0, want), Math.max(0, (cur.duration || want) - 0.04));
        if (live && cur.paused) cur.play().catch(() => {});
        if (!live && !cur.paused) cur.pause();
      } else if (!v.dataset.wait) {
        v.dataset.wait = "1";
        v.addEventListener("loadedmetadata", () => { delete v.dataset.wait; if (cur === v) showAt(playing ? now() : playhead, !!playing); }, { once: true });
      }
      if (live) {                       /* the next shot's file goes into the other element ahead of the cut */
        const nx = D.shots[s.i + 1];
        if (nx && nx.media.kind === "video" && nx.t0 - t < 1.5) {
          const other = cur === vA ? vB : vA, nr = PF.mref(nx.media.ref);
          if (nr && vKey(other) !== nr.upload_id && vKey(cur) !== nr.upload_id) load(other, nx.media.ref).then((ov) => { const go = () => { ov.currentTime = nx.media.off; }; if (ov.readyState >= 1) go(); else ov.addEventListener("loadedmetadata", go, { once: true }); });
        }
      }
    }
    function seek(t) { const was = !!playing; if (was) stop(); playhead = Math.max(0, Math.min(D.dur, t)); showAt(playhead, false); paintHead(); if (was) start(); }

    /* ---------- painting ---------- */
    function paintNote() {
      const n = stack.done.length;
      const parts = [];
      if (err) parts.push(h("span", { class: "ed-err", role: "alert" }, ic("alert"), h("span", { text: err })));
      else if (edit.error) parts.push(h("span", { class: "ed-err" }, ic("alert"), h("span", { text: edit.error })));
      else if (trying) parts.push(h("span", { text: "Trying the agent's suggestion. Keep it or put it back." }));
      else if (sent) parts.push(h("span", { text: "Sent " + sent.length + " edit" + (sent.length === 1 ? "" : "s") + " to render. The new draft shows up when it is built." }));
      else parts.push(h("span", { text: n ? n + " edit" + (n === 1 ? "" : "s") + " not rendered yet" : edit.fresh ? "This is the latest draft as built." : "Some parts are not built yet." }));
      if (edit.generated) parts.push(h("span", { class: "ed-gen", title: "promo.yaml is generated by " + edit.generated + "; your edits are logged and put back on top with `promo flow edit replay` after it runs again." }, " · made by " + edit.generated + ": edits are replayed after it runs"));
      if (edit.files_note) parts.push(h("span", { class: "ed-gen" }, " · " + edit.files_note));
      note.replaceChildren(...parts);
    }
    function paintHead() {
      tcode.textContent = clock(playhead) + " / " + clock(D ? D.dur : 0);
      const ph = lanes.querySelector(".ed-ph");
      if (ph) ph.style.transform = "translateX(" + playhead * pps + "px)";
      if (playing) {                    /* keep the playhead in view */
        const x = playhead * pps, l = scroller.scrollLeft, w = scroller.clientWidth;
        if (x > l + w - 40 || x < l) scroller.scrollLeft = Math.max(0, x - 60);
      }
      playBtn.replaceChildren(ic(playing ? "pause" : "play"));
      playBtn.setAttribute("aria-label", playing ? "Pause (Space)" : "Play (Space)");
    }
    function paint() {
      if (!D) return;
      paintNote(); paintBin(); paintInsp(); paintLanes(); paintFoot(); paintHead();
      if (!playing) showAt(playhead, false);
    }
    function paintBin() {
      binBtn.setAttribute("aria-expanded", String(binOpen));
      el.classList.toggle("bin-open", binOpen);
      const q = binQ.trim().toLowerCase();
      const tabs = h("div", { class: "seg-ctl ed-bintabs", role: "group", "aria-label": "Which project" },
        h("button", { type: "button", "aria-pressed": String(binTab === "here"), "data-k": "bin-here", onclick: () => { binTab = "here"; paintBin(); } }, "This video"),
        h("button", { type: "button", "aria-pressed": String(binTab === "earlier"), "data-k": "bin-earlier", onclick: () => { binTab = "earlier"; paintBin(); } }, "Earlier (" + arr(bin.projects).length + ")"));
      const find = h("input", { type: "search", class: "ed-find", placeholder: "Find", "aria-label": "Find in the bin", value: binQ, "data-k": "bin-find" });
      find.addEventListener("input", () => { binQ = find.value; const at = find.selectionStart; paintBin(); const f = binBox.querySelector(".ed-find"); if (f) { f.focus(); f.setSelectionRange(at, at); } });
      const body = h("div", { class: "ed-binlist" });
      const row = (it, proj) => {
        const key = proj ? it.kind + ":" + proj + ":" + it.id : it.key;
        const used = arr(it.used_in);
        const drag = ["footage", "plate", "music", "sfx", "voice"].includes(it.kind) && !readonly;
        const r = h("li", { class: "ed-item", draggable: drag ? "true" : null, "data-key": key, "data-kind": it.kind, title: it.licence ? it.label + " · " + it.licence : it.label },
          it.poster ? h("img", { class: "ed-thumb", alt: "", loading: "lazy" }) : h("span", { class: "ed-ic" }, ic(KIND_ICON[it.kind] || "doc")),
          h("span", { class: "ed-iname" }, h("b", { text: it.label }), h("small", { text: [it.dur ? clock(it.dur) : null, used.length ? "in " + used.slice(0, 3).join(", ") + (used.length > 3 ? "…" : "") : null, it.kind === "plate" ? "plate (non-UI)" : null].filter(Boolean).join(" · ") })),
          it.media && ["music", "sfx", "voice"].includes(it.kind) ? h("button", { type: "button", class: "icon-btn ed-aud", "aria-label": "Listen to " + it.label, onclick: (e) => { e.stopPropagation(); audition(it); } }, ic("play")) : null);
        if (it.poster) { const im = r.querySelector("img"); urlOf(it.poster).then((u) => { im.src = u; }, () => im.remove()); }
        if (drag) r.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/x-pf-bin", key); e.dataTransfer.effectAllowed = "copy"; dragging = { bin: key, kind: it.kind }; lanes.dataset.dropKind = it.kind; });
        r.addEventListener("dragend", () => { dragging = null; delete lanes.dataset.dropKind; });
        r.addEventListener("click", () => { if (it.kind === "draft" && o.onDraft) o.onDraft(it.id); else if (it.kind === "script" && o.onScript) o.onScript(it.id); else if (["footage", "plate"].includes(it.kind) && sel && sel.kind === "shot") inspSwapTo(key); });
        return r;
      };
      const match = (it) => !q || (it.label + " " + it.id).toLowerCase().includes(q);
      if (binTab === "here") {
        for (const [k, label] of BIN_GROUPS) {
          const items = arr(bin.here).filter((x) => x.kind === k && match(x));
          if (items.length) body.append(h("section", { class: "ed-bgroup" }, h("h4", null, label, h("span", { class: "n", text: String(items.length) })), h("ul", null, items.map((x) => row(x)))));
        }
        if (!body.children.length) body.append(h("p", { class: "sub", text: q ? "Nothing matches." : "Nothing in the bin yet." }));
      } else {
        for (const p of arr(bin.projects)) {
          const counts = Object.entries(p.counts || {}).map(([k, v]) => v + " " + k).join(", ");
          const items = arr(p.items).filter(match);
          body.append(h("section", { class: "ed-bgroup ed-proj" }, h("h4", { title: p.title || p.name }, p.name),
            h("p", { class: "sub", text: p.error || counts || "Nothing to use" }),
            p.open ? h("ul", null, items.map((x) => row(x, p.name))) : p.error ? null : h("button", { type: "button", class: "btn ghost sm", "data-k": "bin-open:" + p.name, disabled: readonly || (o.canSend && !o.canSend()), onclick: () => o.onOpenProject && o.onOpenProject(p.name) }, "Open")));
        }
        if (!arr(bin.projects).length) body.append(h("p", { class: "sub", text: "No earlier projects on this Mac." }));
      }
      const imp = readonly ? null : h("button", { type: "button", class: "btn ghost sm ed-import", "data-k": "ed-import", onclick: () => importDialog() }, ic("plus"), h("span", { text: "Import a file" }));
      binBox.replaceChildren(h("div", { class: "ed-binhead" }, tabs, find), body, imp);
    }
    let aud = null;
    function audition(it) {
      if (aud) { aud.pause(); aud = null; }
      urlOf(it.media).then((u) => { aud = new Audio(u); aud.play().catch(() => {}); });
    }
    function paintInsp() {
      const parts = [];
      const s = sel && sel.kind === "shot" ? D.shots.find((x) => x.id === sel.id) : null;
      const l = sel && sel.kind === "vo" ? D.vo.find((x) => x.id === sel.id) : null;
      const e = sel && sel.kind === "sfx" ? D.sfx.find((x) => x.shot === sel.shot && x.i === sel.i) : null;
      const field = (label, input) => h("label", { class: "ed-f" }, h("span", { text: label }), input);
      const dis = readonly;
      if (s) {
        const foot = arr(bin.here).filter((x) => x.kind === "footage" || x.kind === "plate");
        const srcSel = h("select", { "data-k": "ins-source", disabled: dis || !("source" in s.cfg) }, foot.map((x) => h("option", { value: x.id, selected: x.id === s.cfg.source }, x.label + (x.kind === "plate" ? " (plate)" : ""))));
        if (s.cfg.source && !foot.some((x) => x.id === s.cfg.source)) srcSel.prepend(h("option", { value: s.cfg.source, selected: true }, s.cfg.source));
        srcSel.addEventListener("change", () => push({ op: "swap", shot: s.id, source: srcSel.value }));
        const tin = h("input", { type: "number", step: "0.1", min: "0", value: String(+s.cfg.t_in || 0), "data-k": "ins-tin", disabled: dis || !("source" in s.cfg) });
        tin.addEventListener("change", () => push({ op: "swap", shot: s.id, source: s.cfg.source, t_in: Math.max(0, +tin.value || 0) }));
        const cap = captionOf(s.cfg);
        const capIn = h("input", { type: "text", value: cap ? cap.text : "", placeholder: "No caption", maxlength: "80", "data-k": "ins-caption", disabled: dis });
        capIn.addEventListener("change", () => push({ op: "caption", shot: s.id, text: capIn.value.trim() }));
        parts.push(h("h3", { class: "ed-ih" }, "Shot " + s.id, h("small", { text: (s.cfg.type || "clip") + " · " + clock(s.t0) + "–" + clock(s.t1) + " · beats " + s.b0 + "–" + s.b1 })),
          s.media.rendered ? h("p", { class: "ed-ok" }, ic("check"), "Rendered") : h("p", { class: "ed-warn" }, ic("clock"), "Not rendered yet: the viewer shows the source footage"),
          field("Footage", srcSel), field("Starts at (s into the footage)", tin), field("Caption", capIn),
          s.cfg.ui === false ? h("p", { class: "sub", text: "A generated non-UI plate. It never stands for the product." }) : null,
          h("div", { class: "ed-acts" },
            h("button", { type: "button", class: "btn ghost sm", "data-k": "ins-split", disabled: dis || !(playhead > s.t0 + B() / 2 && playhead < s.t1 - B() / 2), onclick: () => split(s) }, ic("cut"), "Split at playhead"),
            h("button", { type: "button", class: "btn ghost sm", "data-k": "ins-delete", disabled: dis || D.shots.length < 2, onclick: () => push({ op: "delete", shot: s.id }) && (sel = null) }, ic("close"), "Delete")));
        parts.push(askBox("shot " + s.id + ", " + clock(s.t0) + "–" + clock(s.t1) + (s.cfg.source ? ", source " + s.cfg.source : "")));
      } else if (l) {
        const at = h("input", { type: "number", step: "0.05", value: String(l.at), "data-k": "ins-vo-at", disabled: dis });
        at.addEventListener("change", () => push({ op: "vo", line: l.id, at: Math.round((+at.value || 0) * 100) / 100 }));
        const db = h("input", { type: "range", min: "-24", max: "12", step: "0.5", value: String(l.db), "data-k": "ins-vo-db", disabled: dis, "aria-label": "Level of this line" });
        const dbv = h("output", { text: (l.db > 0 ? "+" : "") + l.db + " dB" });
        db.addEventListener("input", () => { dbv.textContent = (+db.value > 0 ? "+" : "") + db.value + " dB"; });
        db.addEventListener("change", () => push({ op: "vo", line: l.id, db: +db.value }));
        parts.push(h("h3", { class: "ed-ih" }, "Voice " + l.id, h("small", { text: "shot " + l.shot + " · " + clock(l.t) })), h("blockquote", { class: "ed-quote", text: l.text || "" }),
          field("Starts (s into shot " + l.shot + ")", at), field("Level", h("span", { class: "ed-row" }, db, dbv)),
          h("div", { class: "ed-acts" }, h("button", { type: "button", class: "btn ghost sm", "data-k": "ins-vo-mute", "aria-pressed": String(l.muted), disabled: dis, onclick: () => push({ op: "vo", line: l.id, mute: !l.muted }) }, ic(l.muted ? "vol" : "mute"), l.muted ? "Unmute" : "Mute")),
          askBox("voice line " + l.id + " (“" + (l.text || "") + "”) at " + clock(l.t)));
      } else if (e) {
        const at = h("input", { type: "number", step: "0.05", value: String(e.at), "data-k": "ins-sfx-at", disabled: dis });
        at.addEventListener("change", () => push({ op: "sfx", shot: e.shot, act: "set", i: e.i, at: Math.round((+at.value || 0) * 100) / 100 }));
        const db = h("input", { type: "number", step: "0.5", value: String(e.db), "data-k": "ins-sfx-db", disabled: dis });
        db.addEventListener("change", () => push({ op: "sfx", shot: e.shot, act: "set", i: e.i, db: +db.value }));
        parts.push(h("h3", { class: "ed-ih" }, "Sound: " + e.name, h("small", { text: "shot " + e.shot + " · " + clock(e.t) })), field("At (s into the shot)", at), field("Level (dB)", db),
          h("div", { class: "ed-acts" }, h("button", { type: "button", class: "btn ghost sm", "data-k": "ins-sfx-rm", disabled: dis, onclick: () => { push({ op: "sfx", shot: e.shot, act: "rm", i: e.i }); sel = null; paint(); } }, ic("close"), "Remove")),
          askBox("sound " + e.name + " at " + clock(e.t)));
      } else if (sel && sel.kind === "music" && D.music) {
        const it = binItem("music:" + D.music.asset);
        const off = h("input", { type: "number", step: "0.1", min: "0", value: String(D.music.offset), "data-k": "ins-music-offset", disabled: dis });
        off.addEventListener("change", () => push({ op: "music", asset: D.music.asset, offset: Math.max(0, +off.value || 0) }));
        parts.push(h("h3", { class: "ed-ih" }, "Music", h("small", { text: it ? it.label : D.music.asset })), it && it.licence ? h("p", { class: "sub", text: "Licence: " + it.licence }) : null,
          field("Laid from (s into the track)", off), h("p", { class: "sub", text: "Drop another track from the bin on the Music lane to try it." }), askBox("the music (" + D.music.asset + ")"));
      } else {
        parts.push(h("h3", { class: "ed-ih" }, "Inspector"), h("p", { class: "sub", text: "Select a shot, a voice line, a sound or the music to change it. Drag from the bin onto the timeline to swap footage or music." }));
        parts.push(askBox("the whole video"));
      }
      const pv = arr(edit.previews).filter((x) => PF.mref(x.file) && !PF.mref(x.file).error);
      if (pv.length) parts.push(h("section", { class: "ed-sugs ed-pvs", "aria-label": "Preview clips from the agent" }, h("h4", { text: "Preview clips" }), pv.map((x) => {
        const box = h("div", { class: "ed-pv", "data-pv": x.id }, h("b", { text: clock(x.start) + "\u2013" + clock(x.end) + " \u00b7 shot" + (x.shots.length > 1 ? "s " : " ") + x.shots.join(", ") }), x.note ? h("span", { class: "sub", text: x.note }) : null);
        const v = h("video", { controls: "", playsinline: "", preload: "metadata", "aria-label": "Preview " + x.id });
        urlOf(x.file).then((u) => { v.src = u; }, () => v.remove());
        box.append(v);
        return box;
      })));
      const lineFx = (lid) => JSON.stringify((arr((D.raw.vo || {}).lines).find((z) => String(z.id != null ? z.id : z.shot) === lid) || {}).fx);
      const fxNote = (D.music && D.music.fx) || JSON.stringify((D.raw.vo || {}).fx) !== JSON.stringify(((edit.spec || {}).vo || {}).fx) || D.vo.some((l) => JSON.stringify((specLine(l.id) || {}).fx) !== lineFx(l.id));
      if (fxNote) parts.push(h("p", { class: "sub", text: "Sound effects on the voice or music play after Render; the preview is dry." }));
      const sugs = arr(edit.suggestions).filter((x) => !x.kept && !hidden.has(x.id));
      if (sugs.length) parts.push(h("section", { class: "ed-sugs", "aria-label": "Suggestions from the agent" }, h("h4", { text: "From the agent" }), sugs.map((x) => {
        let bad = null; try { derive(PF.editParse(x.text)); } catch (er) { bad = er.message; }
        return h("div", { class: "ed-sug", "data-sid": x.id, "data-on": trying === x.id ? "1" : null }, h("b", { text: x.note }), h("pre", { text: x.text }), bad ? h("p", { class: "ed-err", text: bad }) : null,
          h("div", { class: "ed-acts" },
            h("button", { type: "button", class: "btn ghost sm", "data-k": "sug-try:" + x.id, "aria-pressed": String(trying === x.id), disabled: !!bad, onclick: () => { trying = trying === x.id ? null : x.id; rebuild(); paint(); } }, trying === x.id ? "Stop trying" : "Try it"),
            h("button", { type: "button", class: "btn primary sm", "data-k": "sug-keep:" + x.id, disabled: !!bad || readonly, onclick: () => keepSug(x) }, "Keep"),
            h("button", { type: "button", class: "btn ghost sm", "data-k": "sug-hide:" + x.id, onclick: () => { hidden.add(x.id); if (trying === x.id) trying = null; rebuild(); paint(); } }, "Dismiss")));
      })));
      insp.replaceChildren(...parts.filter(Boolean));
    }
    function keepSug(x) {
      const ops = PF.editParse(x.text).map(({ _n, ...op }) => op);
      for (const op of ops) stack = PF.editPush(stack, op);
      trying = null; hidden.add(x.id);
      changed();
      if (o.onKeep) o.onKeep(x);
    }
    function askBox(where) {
      if (readonly) return null;
      return h("button", { type: "button", class: "btn ghost sm ed-ask", "data-k": "ed-ask", onclick: () => o.onAsk && o.onAsk("editor: " + where + (stack.done.length ? "; with " + stack.done.length + " unrendered edit(s): " + PF.editText(stack.done).split("\n").join(" ; ") : "")) }, ic("comment"), "Ask the agent about this");
    }
    function split(s) {
      const k = Math.round((playhead - s.t0) / B());
      if (k > 0 && s.b0 + k < s.b1) push({ op: "split", shot: s.id, at: k });
    }
    function inspSwapTo(key) {
      const s = D.shots.find((x) => x.id === sel.id);
      const ref = refFor(key);
      if (s && ref) push({ op: "swap", shot: s.id, source: ref });
    }
    /* bin key -> the id an op takes: this project's own id, or `project:id` for an earlier project's */
    function refFor(key) {
      const parts = key.split(":");
      if (parts.length === 3) return parts[1] + ":" + parts[2];
      return parts.slice(1).join(":");
    }

    /* ---------- the timeline ---------- */
    const W = () => Math.max(scroller.clientWidth - 8, Math.ceil(D.dur * pps) + 60);
    function paintLanes() {
      const width = W();
      lanes.style.width = width + "px";
      const ruler = h("div", { class: "ed-ruler", "aria-hidden": "true" });
      const bar = (edit.beats_per_bar || 4) * B(), step = pps >= 60 ? 1 : pps >= 24 ? 2 : pps >= 10 ? 5 : 10;
      for (let t = 0; t <= D.dur + 1e-6; t += step) ruler.append(h("i", { style: "left:" + t * pps + "px" }, h("span", { text: clock(t).replace(/\.0$/, "") })));
      const grid = h("div", { class: "ed-grid-b", "aria-hidden": "true" });
      if (pps * B() >= 5) for (let t = 0; t <= D.dur + 1e-6; t += B()) grid.append(h("i", { class: Math.abs(t / bar - Math.round(t / bar)) < 1e-6 ? "bar" : "", style: "left:" + t * pps + "px" }));
      const lv = h("div", { class: "ed-lane", "data-lane": "v" }), lc = h("div", { class: "ed-lane", "data-lane": "cap" }), lo = h("div", { class: "ed-lane", "data-lane": "vo" }),
        lm = h("div", { class: "ed-lane", "data-lane": "music" }), ls = h("div", { class: "ed-lane", "data-lane": "sfx" });
      const rows = Math.max(1, arr(edit.shots).length);
      for (const s of D.shots) {
        const w = (s.t1 - s.t0) * pps, isSel = sel && sel.kind === "shot" && sel.id === s.id;
        const c = h("div", { class: "ed-clip" + (s.media.rendered ? "" : " stale") + (isSel ? " sel" : "") + (s.cfg.ui === false ? " plate" : ""), "data-shot": s.id, tabindex: "-1", role: "button",
          "aria-label": "Shot " + s.id + ", " + clock(s.t0) + " to " + clock(s.t1) + (s.media.rendered ? "" : ", not rendered yet"), style: "left:" + s.t0 * pps + "px;width:" + w + "px" });
        if (s.idx >= 0 && s.media.ref === (s.v && s.v.seg) && edit.strip) for (let k = 0; k < (edit.strip_cols || 3); k++) c.append(h("i", { class: "ed-fr", "data-strip": "1", style: "background-position:" + (k / Math.max(1, (edit.strip_cols || 3) - 1)) * 100 + "% " + (rows > 1 ? (s.idx / (rows - 1)) * 100 : 0) + "%;background-size:" + (edit.strip_cols || 3) * 100 + "% " + rows * 100 + "%" }));
        else if (s.media.poster) c.append(h("i", { class: "ed-fr ed-poster", "data-poster": "1" }));
        c.append(h("span", { class: "ed-cl" }, h("b", { text: s.id }), w > 90 && s.cfg.source ? h("small", { text: s.cfg.source }) : null), h("span", { class: "ed-edge", "aria-hidden": "true" }));
        if (!s.media.rendered) c.append(h("i", { class: "ed-dot", title: "Not rendered yet" }));
        lv.append(c);
        const cap = captionOf(s.cfg);
        if (cap) {
          const a = Array.isArray(cap.t) ? Math.max(0, +cap.t[0]) : 0, b = Array.isArray(cap.t) ? Math.min(s.t1 - s.t0, +cap.t[1]) : s.t1 - s.t0;
          if (b > a) lc.append(h("div", { class: "ed-capb", "data-shot": s.id, title: cap.text, style: "left:" + (s.t0 + a) * pps + "px;width:" + (b - a) * pps + "px" }, h("span", { text: cap.text })));
        }
      }
      paintStrips(lv);
      for (const l of D.vo) if (l.t != null) lo.append(h("div", { class: "ed-vob" + (l.muted ? " muted" : "") + (l.changed ? " changed" : "") + (sel && sel.kind === "vo" && sel.id === l.id ? " sel" : ""), "data-vo": l.id, tabindex: "-1", role: "button",
        "aria-label": "Voice " + l.id + " at " + clock(l.t) + (l.muted ? ", muted" : ""), title: l.text, style: "left:" + l.t * pps + "px;width:" + Math.max(6, l.dur * pps) + "px" }, h("span", { text: l.text || l.id })));
      if (D.music) {
        const mb = h("div", { class: "ed-mus" + (sel && sel.kind === "music" ? " sel" : "") + (D.music.edited ? " changed" : ""), "data-music": "1", tabindex: "-1", role: "button", "aria-label": "Music: " + D.music.asset, style: "width:" + D.dur * pps + "px" });
        const cv = h("canvas", { height: "36", width: String(Math.min(4000, Math.ceil(D.dur * pps))) });
        mb.append(cv, h("span", { class: "ed-mlab", text: (binItem("music:" + D.music.asset) || {}).label || D.music.asset }));
        lm.append(mb);
        drawWave(cv);
      }
      for (const e of D.sfx) ls.append(h("div", { class: "ed-sfx" + (sel && sel.kind === "sfx" && sel.shot === e.shot && sel.i === e.i ? " sel" : ""), "data-sfx": e.shot + "/" + e.i, tabindex: "-1", role: "button", title: e.name + " at " + clock(e.t), "aria-label": "Sound " + e.name + " at " + clock(e.t), style: "left:" + e.t * pps + "px" }, h("span", { text: e.name })));
      lanes.replaceChildren(ruler, grid, lv, lc, lo, lm, ls, h("div", { class: "ed-ph", "aria-hidden": "true" }));
      paintZoom();
      heads.replaceChildren(h("div", { class: "ed-hr" }),
        ...LANES.map(([k, label]) => h("div", { class: "ed-head", "data-lane": k }, h("span", { class: "ed-hl", text: label }),
          k === "cap" ? null : h("span", { class: "ed-ms" },
            h("button", { type: "button", class: "ed-m", "aria-pressed": String(mon[k].mute), "aria-label": "Mute " + label, "data-k": "mute-" + k, onclick: () => monitor(k, "mute") }, "M"),
            h("button", { type: "button", class: "ed-m", "aria-pressed": String(mon[k].solo), "aria-label": "Solo " + label, "data-k": "solo-" + k, onclick: () => monitor(k, "solo") }, "S")),
          AUDIO_LANES.includes(k) ? level(k) : null)));
    }
    function paintStrips(lv) {
      if (!edit.strip) return;
      urlOf(edit.strip).then((u) => { for (const x of lv.querySelectorAll("[data-strip]")) x.style.backgroundImage = "url(\"" + u + "\")"; }, () => {});
      for (const x of lv.querySelectorAll("[data-poster]")) {
        const s = D.shots.find((z) => z.id === x.parentElement.dataset.shot);
        if (s && s.media.poster) urlOf(s.media.poster).then((u) => { x.style.backgroundImage = "url(\"" + u + "\")"; }, () => {});
      }
    }
    function level(k) {
      const v = +D.buses[k] || 0;
      const r = h("input", { type: "range", class: "ed-lvl", min: "-30", max: "6", step: "0.5", value: String(v), "aria-label": k + " level (dB)", title: (v > 0 ? "+" : "") + v + " dB", "data-k": "level-" + k, disabled: readonly });
      r.addEventListener("input", () => { r.title = r.value + " dB"; if (playing && playing[k]) playing[k].gain.value = audible(k) ? dbg(r.value) : 0; });
      r.addEventListener("change", () => push({ op: "bus", bus: k, db: +r.value }));
      return r;
    }
    function monitor(k, what) {
      mon[k][what] = !mon[k][what];
      if (playing) for (const x of AUDIO_LANES) if (playing[x]) playing[x].gain.value = audible(x) ? dbg(D.buses[x]) : 0;
      paintLanes(); if (!playing) showAt(playhead, false);
    }
    const peaksCache = new Map();
    function drawWave(cv) {
      const g = cv.getContext && cv.getContext("2d");
      if (!g) return;
      const draw = (pk) => {
        g.clearRect(0, 0, cv.width, cv.height);
        g.fillStyle = getComputedStyle(cv).color || "#8ab";
        const n = pk.length, w = cv.width, hh = cv.height;
        if (!n) return;
        for (let x = 0; x < w; x++) { const v = pk[Math.min(n - 1, Math.floor((x / w) * n))] || 0; const y = Math.max(1, v * hh); g.fillRect(x, (hh - y) / 2, 1, y); }
      };
      if (!D.music.edited && edit.music && arr(edit.music.peaks).length) {
        const full = edit.music.peaks, frac = Math.min(1, D.dur / (edit.duration || D.dur));   /* a ripple delete ends the music sooner: draw only what plays */
        return draw(full.slice(0, Math.max(1, Math.round(full.length * frac))));
      }
      const ms = musicSource();
      if (!ms) return draw([]);
      const key = PF.mref(ms.ref) && PF.mref(ms.ref).upload_id + "|" + ms.off + "|" + D.dur;
      if (peaksCache.has(key)) return draw(peaksCache.get(key));
      bufferOf(ms.ref).then((buf) => {
        if (!buf) return;
        const ch = buf.getChannelData(0), sr = buf.sampleRate, n = 400, out = [];
        for (let i = 0; i < n; i++) {
          const a = Math.floor((ms.off + (i / n) * D.dur) * sr), b = Math.floor((ms.off + ((i + 1) / n) * D.dur) * sr);
          let m = 0; for (let j = Math.max(0, a); j < Math.min(ch.length, b); j += 16) m = Math.max(m, Math.abs(ch[j]));
          out.push(m);
        }
        peaksCache.set(key, out);
        if (cv.isConnected) draw(out);
      });
    }
    /* ---------- zoom: a factor of Fit; buttons and presets keep the playhead where it is on screen, the wheel the point under the cursor ---------- */
    const fitPps = () => (D && D.dur && scroller.clientWidth > 100 ? (scroller.clientWidth - 24) / D.dur : 36);
    const maxZoom = () => Math.max(1, PPS_MAX / fitPps());
    function setZoom(f, anchorT, anchorX) {
      f = Math.max(1, Math.min(maxZoom(), f));
      const t = anchorT != null ? anchorT : playhead;
      const x = anchorX != null ? anchorX : t * pps - scroller.scrollLeft;
      zf = f; pps = fitPps() * zf;
      paintLanes(); paintHead();
      scroller.scrollLeft = Math.max(0, t * pps - (x >= 0 && x <= scroller.clientWidth ? x : scroller.clientWidth / 2));
    }
    function zoom(d) {
      const next = d > 0 ? ZOOM_STEPS.find((z) => z > zf + 1e-3) : [...ZOOM_STEPS].reverse().find((z) => z < zf - 1e-3);
      setZoom(next != null ? next : d > 0 ? maxZoom() : 1);
    }
    function zoomToShot() {
      const s = sel && sel.kind === "shot" ? D.shots.find((z) => z.id === sel.id) : shotAt(playhead);
      if (!s) return;
      const f = (scroller.clientWidth - 48) / Math.max(0.2, s.t1 - s.t0) / fitPps();
      setZoom(f, s.t0, 24);
    }
    let fitted = false;
    function fit() { if (!D || !D.dur || scroller.clientWidth < 100) return false; pps = fitPps() * zf; fitted = true; return true; }
    const zOut = h("button", { type: "button", class: "ed-zb", "aria-label": "Zoom out (−)", title: "Zoom out (−)", "data-k": "ed-zoom-out", onclick: () => zoom(-1) }, h("span", { text: "−" }));
    const zIn = h("button", { type: "button", class: "ed-zb", "aria-label": "Zoom in (+)", title: "Zoom in (+)", "data-k": "ed-zoom-in", onclick: () => zoom(1) }, ic("plus"));
    const zSlider = h("input", { type: "range", class: "ed-zslider", min: "0", max: "1000", step: "1", value: "0", "aria-label": "Zoom", "data-k": "ed-zoom-slider" });
    zSlider.addEventListener("input", () => setZoom(Math.exp((+zSlider.value / 1000) * Math.log(maxZoom()))));
    const zPre = ZOOM_PRESETS.map(([f, l]) => h("button", { type: "button", class: "ed-zp", "data-f": String(f), "data-k": "ed-zoom-" + (f === 1 ? "fit" : f), title: f === 1 ? "The whole film (0)" : "Zoom " + l, onclick: () => setZoom(f) }, l));
    const zLab = h("span", { class: "ed-zlab", "aria-live": "polite" });
    zbar.append(zOut, zSlider, zIn, h("span", { class: "ed-zpre", role: "group", "aria-label": "Zoom presets" }, ...zPre,
      h("button", { type: "button", class: "ed-zp", "data-k": "ed-zoom-shot", title: "Zoom to the selected shot (Z)", onclick: zoomToShot }, "Shot")), zLab);
    function paintZoom() {
      const mz = maxZoom(), span = scroller.clientWidth / pps;
      zLab.textContent = (zf < 1.05 ? "Fit" : (Math.round(zf * 10) / 10) + "×") + " \u00b7 " + (span >= 60 ? clock(span).replace(/\.\d$/, "") : Math.round(span * 10) / 10 + " s") + " on screen";
      if (root.document.activeElement !== zSlider && el.getRootNode().activeElement !== zSlider) zSlider.value = String(Math.round(1000 * Math.log(zf) / Math.log(Math.max(1.0001, mz))));
      zOut.disabled = zf <= 1.001; zIn.disabled = zf >= mz - 1e-3;
      for (const b of zPre) { const f = +b.dataset.f; b.hidden = f > mz + 1e-3; b.setAttribute("aria-pressed", String(Math.abs(zf - f) / f < 0.04)); }
    }

    /* ---------- pointer: select, seek, trim, reorder, move voice and sound ---------- */
    const tAt = (clientX) => (clientX - lanes.getBoundingClientRect().left) / pps;
    const snapBeat = (t) => Math.round(t / B());
    let gesture = null;
    lanes.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      lanes.focus({ preventScroll: true });
      const clip = e.target.closest(".ed-clip"), vo = e.target.closest(".ed-vob"), sx = e.target.closest(".ed-sfx"), mu = e.target.closest(".ed-mus");
      const x0 = e.clientX;
      if (clip) {
        const s = D.shots.find((z) => z.id === clip.dataset.shot);
        sel = { kind: "shot", id: s.id };
        const edge = e.target.classList.contains("ed-edge") || clip.getBoundingClientRect().right - e.clientX < 7;
        gesture = { kind: edge ? "trim" : "move", s, x0, el: clip, moved: false };
      } else if (vo) { const l = D.vo.find((z) => z.id === vo.dataset.vo); sel = { kind: "vo", id: l.id }; gesture = { kind: "vo", l, x0, el: vo, moved: false }; }
      else if (sx) { const [shot, i] = sx.dataset.sfx.split("/"); sel = { kind: "sfx", shot, i: +i }; gesture = { kind: "sfx", e: D.sfx.find((z) => z.shot === shot && z.i === +i), x0, el: sx, moved: false }; }
      else if (mu) { sel = { kind: "music" }; gesture = { kind: "seek" }; seek(tAt(e.clientX)); }
      else { gesture = { kind: "seek" }; seek(tAt(e.clientX)); }
      if (gesture && gesture.kind !== "seek" && !readonly) try { lanes.setPointerCapture(e.pointerId); } catch (_) { /* a pointer the browser no longer tracks */ }
      paintInsp();
      for (const x of lanes.querySelectorAll(".sel")) x.classList.remove("sel");
      const se = clip || vo || sx || mu; if (se) se.classList.add("sel");
    });
    lanes.addEventListener("pointermove", (e) => {
      const g = gesture;
      if (!g || readonly) return;
      if (g.kind === "seek") { if (e.buttons) seek(tAt(e.clientX)); return; }
      const dx = e.clientX - g.x0;
      if (!g.moved && Math.abs(dx) < 4) return;
      g.moved = true;
      if (g.kind === "trim") {
        const nb = Math.max(g.s.b0 + 1, snapBeat(g.s.t1 + dx / pps)), nx = D.shots[g.s.i + 1];
        g.to = nx ? Math.min(nx.b1 - 1, nb) : nb;
        g.el.style.width = (g.to - g.s.b0) * B() * pps + "px";
        g.el.classList.add("drag");
      } else if (g.kind === "move") {
        g.el.style.transform = "translateX(" + dx + "px)"; g.el.classList.add("drag");
        const t = (g.s.t0 + g.s.t1) / 2 + dx / pps;
        const others = D.shots.filter((z) => z.id !== g.s.id);
        const k = others.findIndex((z) => t < (z.t0 + z.t1) / 2);
        g.to = k < 0 ? { after: others[others.length - 1].id } : { before: others[k].id };
        for (const x of lanes.querySelectorAll(".ed-clip.ins")) x.classList.remove("ins");
        const tgt = lanes.querySelector('.ed-clip[data-shot="' + (g.to.before || g.to.after) + '"]');
        if (tgt) { tgt.classList.add("ins"); tgt.dataset.side = g.to.before ? "l" : "r"; }
      } else if (g.kind === "vo" || g.kind === "sfx") {
        const t0 = (g.kind === "vo" ? g.l.t : g.e.t) + dx / pps;
        g.to = Math.max(0, Math.min(D.dur - 0.05, t0));
        g.el.style.left = g.to * pps + "px"; g.el.classList.add("drag");
      }
    });
    const endGesture = () => {
      const g = gesture;
      gesture = null;
      if (!g || !g.moved || g.to == null) return;
      if (g.kind === "trim" && g.to !== g.s.b1) push({ op: "trim", shot: g.s.id, end: g.to });
      else if (g.kind === "move") {
        const ids = D.shots.map((z) => z.id), i = ids.indexOf(g.s.id), tgt = g.to.before || g.to.after, j = ids.indexOf(tgt);
        const noop = (g.to.before && j === i + 1) || (g.to.after && j === i - 1);
        if (!noop) push({ op: "move", shot: g.s.id, ...g.to }); else paint();
      } else if (g.kind === "vo") {
        const s = shotAt(g.to), at = Math.round((g.to - s.t0) * 100) / 100;
        push(s.id !== g.l.shot ? { op: "vo", line: g.l.id, shot: s.id, at } : { op: "vo", line: g.l.id, at });
      } else if (g.kind === "sfx") {
        const s = D.shots.find((z) => z.id === g.e.shot);
        push({ op: "sfx", shot: g.e.shot, act: "set", i: g.e.i, at: Math.max(0, Math.round((g.to - s.t0) * 100) / 100) });
      } else paint();
    };
    lanes.addEventListener("pointerup", endGesture);
    lanes.addEventListener("pointercancel", () => { gesture = null; paint(); });
    /* Ctrl / Cmd + wheel, and a trackpad pinch (which arrives as ctrl + wheel), zoom smoothly around the point under the cursor */
    scroller.addEventListener("wheel", (e) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const x = e.clientX - scroller.getBoundingClientRect().left, t = (scroller.scrollLeft + x) / pps;
      setZoom(zf * Math.exp(-Math.max(-60, Math.min(60, e.deltaY)) * 0.01), t, x);
    }, { passive: false });
    /* drops from the bin: footage on a shot swaps it, music on the music lane, a sound on a shot at that moment, a voice take on a voice line */
    lanes.addEventListener("dragover", (e) => { if (dragging && !readonly) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } });
    lanes.addEventListener("drop", (e) => {
      const key = e.dataTransfer.getData("text/x-pf-bin") || (dragging && dragging.bin);
      dragging = null; delete lanes.dataset.dropKind;
      if (!key || readonly) return;
      e.preventDefault();
      const kind = key.split(":")[0], ref = refFor(key), t = tAt(e.clientX);
      const lane = e.target.closest(".ed-lane"), clip = e.target.closest(".ed-clip"), vo = e.target.closest(".ed-vob");
      if ((kind === "footage" || kind === "plate") && (clip || (lane && lane.dataset.lane === "v"))) { const s = clip ? D.shots.find((z) => z.id === clip.dataset.shot) : shotAt(t); if (s) { sel = { kind: "shot", id: s.id }; push({ op: "swap", shot: s.id, source: ref }); } }
      else if (kind === "music") { sel = { kind: "music" }; push({ op: "music", asset: ref, offset: 0 }); }
      else if (kind === "sfx") { const s = shotAt(t); if (s) push({ op: "sfx", shot: s.id, act: "add", sfx: ref, at: Math.max(0, Math.round((t - s.t0) * 100) / 100) }); }
      else if (kind === "voice" && vo) push({ op: "vo", line: vo.dataset.vo, take: ref });
      else flash(kind === "voice" ? "Drop a voice take on a voice line." : "Drop footage on a shot, music on the Music lane, a sound on the shot where it should play.");
    });
    el.addEventListener("keydown", (e) => {
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      const mod = e.metaKey || e.ctrlKey;
      if (e.key === " " && !mod) { e.preventDefault(); if (!e.repeat) toggle(); }
      else if (mod && (e.key === "z" || e.key === "Z")) { e.preventDefault(); if (e.shiftKey) redo(); else undo(); }
      else if (mod && e.key === "y") { e.preventDefault(); redo(); }
      else if (e.key === "+" || e.key === "=") { e.preventDefault(); zoom(1); }
      else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoom(-1); }
      else if (e.key === "0" && !mod) { e.preventDefault(); setZoom(1); }
      else if ((e.key === "z" || e.key === "Z") && !mod) { e.preventDefault(); zoomToShot(); }
      else if ((e.key === "b" || e.key === "B") && !mod) { const s = sel && sel.kind === "shot" ? D.shots.find((z) => z.id === sel.id) : shotAt(playhead); if (s) { e.preventDefault(); split(s); } }
      else if ((e.key === "Delete" || e.key === "Backspace") && sel) {
        e.preventDefault();
        if (sel.kind === "shot" && D.shots.length > 1) { push({ op: "delete", shot: sel.id }); sel = null; paintInsp(); }
        else if (sel.kind === "vo") { const l = D.vo.find((z) => z.id === sel.id); if (l) push({ op: "vo", line: l.id, mute: !l.muted }); }
        else if (sel.kind === "sfx") { push({ op: "sfx", shot: sel.shot, act: "rm", i: sel.i }); sel = null; paintInsp(); }
      }
      else if (e.key === "Home") { e.preventDefault(); seek(0); }
      else if (e.key === "End") { e.preventDefault(); seek(D.dur); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); const d = e.key === "ArrowLeft" ? -1 : 1; seek(playhead + d * (e.shiftKey ? B() : 1 / (edit.fps || 30))); }
      else if ((e.key === "m" || e.key === "M") && sel && sel.kind === "vo") { const l = D.vo.find((z) => z.id === sel.id); if (l) { e.preventDefault(); push({ op: "vo", line: l.id, mute: !l.muted }); } }
    });

    /* ---------- the footer: pending edits, undo / redo, export, render ---------- */
    function paintFoot() {
      const n = stack.done.length, sm = PF.editSummary(stack.done, edit);
      const exp = h("details", { class: "ed-export" }, h("summary", { "data-k": "ed-export" }, ic("download"), "Export"), h("div", { class: "ed-exlist" }, exports()));
      const list = showPending && n ? h("ol", { class: "ed-pending", "aria-label": "Edits not rendered yet" }, PF.editText(stack.done).split("\n").map((t) => h("li", null, h("code", { text: t })))) : null;
      foot.replaceChildren(
        h("div", { class: "ed-fl" },
          h("button", { type: "button", class: "btn ghost sm", "data-k": "ed-pending", "aria-expanded": String(showPending), disabled: !n, onclick: () => { showPending = !showPending; paintFoot(); } }, "Edits (" + n + ")"),
          h("button", { type: "button", class: "icon-btn", "data-k": "ed-undo", "aria-label": "Undo (Cmd+Z)", title: "Undo (Cmd+Z)", disabled: !n, onclick: undo }, ic("undo")),
          h("button", { type: "button", class: "icon-btn", "data-k": "ed-redo", "aria-label": "Redo (Shift+Cmd+Z)", title: "Redo (Shift+Cmd+Z)", disabled: !stack.undone.length, onclick: redo }, ic("redo")),
          exp),
        h("div", { class: "ed-fr2" }, h("span", { class: "ed-sum", text: n ? sm.line : "" }),
          o.onPreview ? h("button", { type: "button", class: "btn ghost", "data-k": "ed-preview", disabled: !n || readonly || !!sent || (o.canSend && !o.canSend()),
            title: "Apply the edits and build only " + previewSpan().where + " into a short clip with the new mix, without a whole draft", onclick: () => quickPreview() }, ic("play"), "Quick preview") : null,
          h("button", { type: "button", class: "btn primary", "data-k": "ed-render", disabled: !n || readonly || !!sent || (o.canSend && !o.canSend()), title: n ? "Builds only what changed: " + sm.line : "",
            onclick: () => render() }, ic("refresh"), n ? "Render draft" : "No edits to render")),
        list || "");
    }
    /* What a quick preview builds: the selected shot, else every shot the edits change (as the timeline stands after them). */
    function previewSpan() {
      if (!D) return { where: "the changed shots", args: "" };
      const sm = PF.editSummary(stack.done, edit);
      const pick = sel && sel.kind === "shot" ? [sel.id] : sm.shots.filter((id) => D.shots.some((z) => z.id === id));
      const ss = D.shots.filter((z) => pick.includes(z.id));
      if (ss.length === 1) return { where: "shot " + ss[0].id, args: "--shot " + ss[0].id };
      if (ss.length) { const a = Math.min(...ss.map((z) => z.t0)), b = Math.max(...ss.map((z) => z.t1)); return { where: clock(a) + "\u2013" + clock(b), args: "--from " + (Math.round(a * 1000) / 1000) + " --to " + (Math.round(b * 1000) / 1000) }; }
      const t = Math.max(0, playhead - 2);
      return { where: clock(t) + "\u2013" + clock(Math.min(D.dur, t + 6)), args: "--from " + (Math.round(t * 1000) / 1000) + " --to " + (Math.round(Math.min(D.dur, t + 6) * 1000) / 1000) };
    }
    function quickPreview() {
      const ops = stack.done.slice();
      if (!ops.length || !o.onPreview) return;
      stop();
      if (o.onPreview(PF.editText(ops), ops, previewSpan()) !== false) { sent = ops; sentSig = edit.sig; paint(); }
    }
    function render() {
      const ops = stack.done.slice();
      if (!ops.length || !o.onRender) return;
      stop();
      if (o.onRender(PF.editText(ops), ops, PF.editSummary(ops, edit)) !== false) { sent = ops; sentSig = edit.sig; paint(); }
    }
    function exports() {
      const out = [];
      const add = (label, name, ref) => { if (ref && PF.mref(ref) && !PF.mref(ref).error && o.download) out.push(h("div", { class: "ed-exrow" }, h("span", { text: label }), o.download(label, name, () => urlOf(ref)))); };
      for (const [k, ref] of Object.entries(edit.masters || {})) add("Mix (" + k + " master)", "mix-" + k + ".wav", ref);
      for (const [k, ref] of Object.entries(edit.stems || {})) add("Stem: " + k, "stem-" + k + ".wav", ref);
      if (edit.music) add("Music edit", "music-edit.wav", edit.music.file);
      for (const l of arr((edit.vo || {}).lines)) add("Voice " + l.id, "voice-" + l.id + ".wav", l.file);
      for (const s of arr(edit.shots)) add("Shot " + s.id, "shot-" + s.id + ".mp4", s.seg);
      const txt = (label, name, text, type) => { if (text && o.download) out.push(h("div", { class: "ed-exrow" }, h("span", { text: label }), o.download(label, name, () => Promise.resolve(URL.createObjectURL(new Blob([text], { type })))))); };
      txt("Edit decision list", "EDL.md", edit.edl, "text/markdown");
      txt("Your edits (edit language)", "edits.txt", stack.done.length ? PF.editText(stack.done) + "\n" : "", "text/plain");
      if (!out.length) out.push(h("p", { class: "sub", text: "Nothing to export yet." }));
      return out;
    }
    function importDialog() {
      if (!o.onImport) return;
      const file = h("input", { type: "file", accept: "audio/*,video/*", "data-k": "imp-file" });
      const kind = h("select", { "data-k": "imp-kind" }, [["music", "Music"], ["sfx", "Sound effect"], ["voice", "Voice take"], ["video", "Video footage"]].map(([v, l]) => h("option", { value: v }, l)));
      const own = h("input", { type: "checkbox", "data-k": "imp-own" });
      const lic = h("input", { type: "text", placeholder: "e.g. CC0-1.0, or the licence's name", "data-k": "imp-licence" });
      const src = h("input", { type: "text", placeholder: "Where it came from: a URL, or who made it", "data-k": "imp-source" });
      const why = h("p", { class: "ed-err", role: "alert", hidden: true });
      own.addEventListener("change", () => { lic.disabled = src.disabled = own.checked; });
      file.addEventListener("change", () => { const f = file.files[0]; if (f) kind.value = /^video\//.test(f.type) ? "video" : kind.value; });
      const box = h("div", { class: "ed-dlg", role: "dialog", "aria-modal": "true", "aria-label": "Import a file" },
        h("h3", { text: "Import a file" }),
        h("p", { class: "sub", text: "Every file needs its licence and where it came from (team rule 4). Videos must be real recordings of the product, or non-UI plates." }),
        h("label", { class: "ed-f" }, h("span", { text: "File (100 MB at most)" }), file), h("label", { class: "ed-f" }, h("span", { text: "What it is" }), kind),
        h("label", { class: "ed-own" }, own, h("span", { text: "My own recording" })),
        h("label", { class: "ed-f" }, h("span", { text: "Licence" }), lic), h("label", { class: "ed-f" }, h("span", { text: "Source" }), src), why,
        h("div", { class: "ed-acts" }, h("button", { type: "button", class: "btn ghost", "data-k": "imp-cancel", onclick: () => box.remove() }, "Cancel"),
          h("button", { type: "button", class: "btn primary", "data-k": "imp-send", onclick: () => {
            const f = file.files[0];
            const problem = !f ? "Choose a file." : f.size > 100 * 1048576 ? "Over the 100 MB limit." : !own.checked && (!lic.value.trim() || !src.value.trim()) ? "Say its licence and where it came from, or tick My own recording." : null;
            if (problem) { why.hidden = false; why.textContent = problem; return; }
            if (o.onImport(f, kind.value, own.checked ? "My own recording" : lic.value.trim(), own.checked ? "recorded by the person" : src.value.trim()) !== false) box.remove();
          } }, "Send to the agent")));
      box.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); box.remove(); } });
      el.append(box);
      file.focus();
    }

    /* ---------- life cycle ---------- */
    function update(n) {
      const sig0 = edit.sig;
      edit = n.edit || edit; bin = n.bin || bin; readonly = !!n.readonly;
      if (sent && edit.sig !== sentSig) { stack = { done: stack.done.filter((x) => !sent.includes(x)), undone: [] }; sent = null; }
      else if (sent && n.sendFailed) sent = null;
      if (edit.sig !== sig0) for (const v of [vA, vB]) { v.dataset.key = ""; }
      if (!playing) { rebuild(); paint(); } else rebuild();
    }
    rebuild();
    requestAnimationFrame(() => { fit(); paint(); });
    if (root.ResizeObserver) new ResizeObserver(() => { if (D && !gesture) { fit(); paintLanes(); paintHead(); } }).observe(scroller);
    return {
      el, update,
      busy: () => !!playing || !!gesture || stack.done.length > 0 || !!el.querySelector(".ed-dlg"),
      playing: () => !!playing, toggle, pending: () => stack.done.slice(), failed: () => { sent = null; paint(); },
      destroy: () => { stop(); if (ctx) ctx.close().catch(() => {}); },
    };
  }
  root.PFEditor = { create };
})(window);
