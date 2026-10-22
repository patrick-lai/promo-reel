"use strict";
/* Promo Reel home (Start / Voices / Projects), with or without a thread.
   Inside a thread, app.js adds a Flow tab while a live stage is published.
   Pane -> host: {type:"call", id, method, params} and {type:"cancel", id}.
   Host -> pane: accepted, progress {pct 0..100, note}, result {ok, value|error}.
   Jobs run with or without a thread. Agent actions stay disabled when thread_id is null (see app.js). */
window.PFVoices = (function () {
  const MOODS = ["neutral", "excited", "calm", "warm"];
  const LABEL = { neutral: "Neutral", excited: "Excited", calm: "Calm", warm: "Warm" };
  const TITLES = ["Intro", "The idea", "How it works", "The picture", "Wrap up"];
  const SAMPLE = "Commission a feature tonight, and wake up to a reviewed pull request.";
  const LONG = { "voices.sample": 1, "voices.save": 1, "voices.model.download": 1, "voices.render": 1 };
  /* Host hard deadline is 15 min. This only unblocks the pane if that result never arrives. */
  const JOB_MS = 15 * 60 * 1000 + 15000;
  const HOST_MSG = {
    "host.no_worker": "The voice worker isn't running. Turn Promo flow off and on in Settings, then try again.",
    "host.idle_timeout": "That paused too long without an update, so it was stopped. Try again.",
    "host.deadline": "That ran longer than 15 minutes and was stopped.",
    "host.cancelled": "Cancelled.",
    "host.worker_exited": "The voice worker stopped before it finished. Try again.",
    "host.too_many_jobs": "Four jobs are already running. Wait for one to finish, then try again.",
    "host.path_escape": "That file isn't in the folder the host allows.",
    "host.file_too_large": "That file is larger than 100 MB.",
    "host.file_not_found": "That audio file isn't in the host data folder.",
    "network.unreachable": "Can't reach the app right now. Try again once it's back.",
  };
  const MIC_NOTE = "If no microphone prompt appears, the Mac app still needs microphone permission.";
  const AUDIO_NOTE = "A long recording may be too big to send in one message. Audio files in the host data folder come in a later update.";
  const KICKOFF_NOTE = "Opening a thread with this voice comes in a later update.";
  let api = null;
  let alive = true;
  let seq = 0;
  const calls = new Map();
  let meterTimer = 0;
  let live = null;
  const state = {
    tab: "start", booted: false, voices: null, script: null, model: null, err: "", note: "", busy: "",
    pct: null, long: false,
    brief: "", voice: "", flow: null, arm: null, renaming: null, renameText: "",
    sampleText: SAMPLE, mood: "excited", strength: 65, audio: null, projects: null,
  };

  const h = (...a) => api.h(...a);
  const ic = (n) => (api.ic ? api.ic(n) : null);

  function explain(e) {
    if (!e) return "Something went wrong.";
    if (typeof e === "string") return e;
    const code = e.code || "";
    if (Object.prototype.hasOwnProperty.call(HOST_MSG, code)) return HOST_MSG[code];
    return e.message || code || "Something went wrong.";
  }

  function anyLong() {
    for (const c of calls.values()) if (c.long) return true;
    return false;
  }

  function call(method, params, opts) {
    opts = opts || {};
    const long = !!(opts.long || opts.slow || LONG[method]);
    return new Promise((resolve, reject) => {
      const id = "v" + ++seq;
      const timer = setTimeout(() => {
        const c = calls.get(id);
        if (!c) return;
        calls.delete(id);
        state.long = anyLong();
        if (api && api.post) api.post({ type: "cancel", id });
        reject({ code: "host.deadline", message: HOST_MSG["host.deadline"] });
      }, JOB_MS);
      calls.set(id, { resolve, reject, timer, long, onProgress: opts.onProgress || null });
      if (long) {
        state.long = true;
        if (state.pct == null) state.pct = 0;
        if (!state.busy) state.busy = "Working…";
      }
      api.post({ type: "call", id, method, params: params || {} });
    });
  }

  function cancelLong() {
    let id = null;
    for (const [k, c] of calls) if (c.long) id = k;
    if (!id || !api) return;
    state.busy = "Cancelling…";
    const node = api.content && api.content.querySelector("[data-reel-busy]");
    if (node) node.textContent = progressLabel();
    api.post({ type: "cancel", id });
  }

  function progressLabel() {
    const pct = typeof state.pct === "number" ? " " + Math.round(Math.max(0, Math.min(100, state.pct))) + "%" : "";
    return (state.busy || "Working…") + pct;
  }

  function onAccepted(m) {
    const c = m && calls.get(m.id);
    if (!c) return false;
    c.job = m.job;
    return true;
  }

  function onResult(m) {
    if (!m || !calls.has(m.id)) return false;
    const c = calls.get(m.id);
    clearTimeout(c.timer);
    calls.delete(m.id);
    state.long = anyLong();
    if (!state.long) state.pct = null;
    if (m.ok) c.resolve(m.value);
    else c.reject(m.error || { message: "That didn't go through." });
    return true;
  }

  function onProgress(m) {
    const c = m && calls.get(m.id);
    if (!c) return;
    if (typeof m.pct === "number" && isFinite(m.pct)) state.pct = Math.max(0, Math.min(100, m.pct));
    if (m.note) state.busy = m.note;
    if (c.onProgress) c.onProgress(m);
    if (!alive || !api || !api.content) return;
    const node = api.content.querySelector("[data-reel-busy]");
    if (node) node.textContent = progressLabel();
    const bar = api.content.querySelector("[data-reel-jobbar]");
    if (bar && state.pct != null) bar.style.width = Math.max(0, Math.min(100, state.pct)) + "%";
  }

  function fail(e) {
    if (!e || e.silent || !alive) return;
    state.busy = "";
    if (!anyLong()) { state.pct = null; state.long = false; }
    if (e.code === "host.cancelled") { state.err = ""; state.note = "Cancelled."; }
    else { state.note = ""; state.err = explain(e); }
    paint();
  }

  function ensure() {
    if (state.booted) return;
    state.booted = true;
    call("voices.script").then((s) => { state.script = s; paint(); }).catch(fail);
    call("voices.list").then((v) => { state.voices = Array.isArray(v) ? v : []; paint(); }).catch(fail);
    call("voices.model.status").then((m) => { state.model = m; paint(); }).catch(() => {});
  }

  function fmt(s) {
    s = Math.max(0, Math.round(s || 0));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  function scriptSeconds() {
    const f = state.flow;
    if (!f) return 0;
    return (f.clips || []).reduce((a, c) => a + ((c && c.dur) || 0), 0);
  }

  function concat(chunks) {
    let n = 0;
    chunks.forEach((c) => { n += c.length; });
    const out = new Float32Array(n);
    let o = 0;
    chunks.forEach((c) => { out.set(c, o); o += c.length; });
    return out;
  }

  function encodeWav(samples, sr) {
    const n = samples.length;
    const buf = new ArrayBuffer(44 + n * 2);
    const v = new DataView(buf);
    const w = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
    w(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    w(36, "data"); v.setUint32(40, n * 2, true);
    let o = 44;
    for (let i = 0; i < n; i++) {
      const x = Math.max(-1, Math.min(1, samples[i]));
      v.setInt16(o, x < 0 ? x * 0x8000 : x * 0x7fff, true);
      o += 2;
    }
    return new Blob([buf], { type: "audio/wav" });
  }

  function stopLive() {
    if (!live) return null;
    const rec = live;
    live = null;
    clearInterval(meterTimer);
    try { rec.proc.disconnect(); rec.src.disconnect(); rec.gain.disconnect(); } catch (_) { /* already stopped */ }
    rec.stream.getTracks().forEach((t) => t.stop());
    const sr = rec.ctx.sampleRate || 48000;
    rec.ctx.close();
    const pcm = concat(rec.chunks);
    const blob = encodeWav(pcm, sr);
    return { blob, dur: pcm.length / (sr || 1), url: URL.createObjectURL(blob) };
  }

  function haltPlayback() {
    if (state.audio) { state.audio.pause(); state.audio = null; }
    stopLive();
  }

  async function startLive() {
    if (live) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      state.err = "This browser can't use the microphone.";
      paint();
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      state.err = e && e.name === "NotAllowedError" ? "Microphone access was denied. " + MIC_NOTE : "No microphone is available.";
      paint();
      return;
    }
    if (!state.flow) { stream.getTracks().forEach((t) => t.stop()); return; }
    const ctx = new AudioContext();
    if (typeof ctx.createScriptProcessor !== "function") {
      stream.getTracks().forEach((t) => t.stop());
      ctx.close();
      state.err = "This browser can't record audio here.";
      paint();
      return;
    }
    const src = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const gain = ctx.createGain();
    gain.gain.value = 0;
    const chunks = [];
    proc.onaudioprocess = (ev) => { if (live) chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0))); };
    src.connect(proc);
    proc.connect(gain);
    gain.connect(ctx.destination);
    live = { stream, ctx, src, proc, gain, chunks, t0: Date.now() };
    clearInterval(meterTimer);
    meterTimer = setInterval(tickMeter, 200);
    paint();
  }

  function tickMeter() {
    if (!api || !api.content) return;
    const now = scriptSeconds() + (live && state.flow && state.flow.step === 1 ? (Date.now() - live.t0) / 1000 : 0);
    const m = api.content.querySelector("[data-reel-meter]");
    const sub = api.content.querySelector("[data-reel-sub]");
    const bar = api.content.querySelector("[data-reel-bar]");
    if (m) m.textContent = fmt(now);
    if (bar) bar.style.width = Math.min(100, (now / 30) * 100) + "%";
    if (sub) {
      const left = Math.max(0, 30 - now);
      sub.textContent = live ? (left > 0.4 ? "Recording… " + Math.ceil(left) + " more seconds to go" : "Recording… that's enough of the script") : (now >= 30 ? "Script length is enough." : "Need " + fmt(left) + " more.");
    }
  }

  function keepLive() {
    if (!live || !state.flow) return;
    const clip = stopLive();
    if (state.flow.step === 2 && state.flow.mood) state.flow.moods[state.flow.mood] = clip;
    else state.flow.clips[state.flow.part] = clip;
    state.flow.mood = null;
  }

  function blobB64(blob) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(",")[1] || "");
      r.onerror = () => reject(new Error("Could not read the recording."));
      r.readAsDataURL(blob);
    });
  }

  function playUrl(url) {
    if (state.audio) state.audio.pause();
    const a = new Audio(url);
    state.audio = a;
    a.play().catch(() => { state.err = "Couldn't play that clip."; paint(); });
  }

  function beginRecord() {
    keepLive();
    state.flow = { step: 1, part: 0, clips: [], moods: {}, name: "", mood: null };
    state.tab = "voices";
    state.err = "";
    paint();
  }

  function paragraphs() {
    return (state.script && state.script.paragraphs) || [];
  }

  function emotionLine(emo) {
    const map = (state.script && state.script.emotions) || {};
    return map[emo] || "";
  }

  function modelButton() {
    const ready = !!(state.model && state.model.ready);
    const size = (state.model && state.model.size) || "~3 GB";
    return h("button", {
      type: "button", class: "btn ghost", disabled: ready,
      onclick: () => {
        if (ready || state.busy) return;
        state.err = "";
        state.busy = "Downloading the model (" + size + ")…";
        state.pct = 0;
        state.long = true;
        paint();
        call("voices.model.download", { yes: true }, { slow: true }).then((st) => {
          state.model = st; state.busy = ""; paint();
        }).catch(fail);
      },
    }, ready ? "Model ready" : "Download model (" + size + ")");
  }

  function tabs() {
    if (state.hideTabs) return null;
    const items = [["start", "Start"], ["voices", "Voices"], ["projects", "Projects"]];
    return h("div", { class: "reel-tabs", role: "tablist", "aria-label": "Promo Reel" }, items.map(([id, label]) => h("button", {
      type: "button", class: "reel-tab" + (state.tab === id ? " on" : ""), role: "tab",
      "aria-selected": state.tab === id ? "true" : "false",
      onclick: () => { keepLive(); state.tab = id; state.err = ""; paint(); },
    }, label)));
  }

  function banner() {
    const job = state.busy ? h("div", { class: "reel-card" },
      h("div", { class: "reel-row" },
        h("p", { class: "reel-dim reel-grow", "data-reel-busy": "1", text: progressLabel() }),
        state.long ? h("button", { type: "button", class: "btn ghost sm", onclick: cancelLong }, "Cancel") : null),
      state.pct != null ? h("div", { class: "reel-meter", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(state.pct || 0)), "aria-label": state.busy || "Working" },
        h("i", { "data-reel-jobbar": "1", style: "width:" + Math.max(0, Math.min(100, state.pct || 0)) + "%" })) : null) : null;
    return [
      state.err ? h("p", { class: "reel-err", role: "alert", text: state.err }) : null,
      state.note ? h("p", { class: "reel-note", text: state.note }) : null,
      job,
    ];
  }

  function viewStart() {
    const voices = state.voices || [];
    const sel = h("select", { class: "reel-select", "aria-label": "Voiceover", onchange: (e) => { state.voice = e.target.value; } },
      h("option", { value: "", text: voices.length ? "None" : "No voice yet" }),
      voices.map((v) => h("option", { value: v.id, text: v.name + (v.default ? " · default" : "") })));
    sel.value = state.voice || "";
    const chosen = voices.find((v) => v.id === state.voice);
    return h("div", { class: "reel-stack" },
      h("h2", { class: "reel-h", text: "Make a promo video" }),
      h("p", { class: "reel-dim", text: "Say what it's for. A promo session starts in a new thread and asks you at each step." }),
      h("textarea", { class: "reel-brief", rows: "4", placeholder: "e.g. a 30 s clip showing how fishStack keeps two Claude sessions apart", oninput: (e) => { state.brief = e.target.value; } }, state.brief),
      h("div", { class: "reel-row" },
        h("span", { class: "reel-dim", text: "Voiceover" }),
        sel,
        chosen && chosen.sample_b64 ? h("button", { type: "button", class: "icon-btn", "aria-label": "Hear it", onclick: () => playUrl("data:audio/wav;base64," + chosen.sample_b64) }, ic("play")) : null,
        h("button", { type: "button", class: "btn primary", onclick: startPromo }, "Start")),
      h("p", { class: "reel-dim", text: KICKOFF_NOTE }),
      h("p", { class: "reel-dim", text: "Moods are picked per line later. You can change the voice any time." }),
      h("p", { class: "reel-kicker", text: "Before you start (optional)" }),
      h("button", { type: "button", class: "reel-card reel-link", onclick: beginRecord },
        ic("vol"),
        h("span", {}, h("b", { text: "Record your voice" }), h("span", { class: "reel-dim", text: "About a minute. Use it as the voiceover in any promo." })),
        h("span", { class: "reel-go", text: "Voices" })),
      h("button", { type: "button", class: "reel-card reel-link", onclick: () => { state.tab = "projects"; paint(); } },
        ic("film"),
        h("span", {}, h("b", { text: "Carry on a past promo" }), h("span", { class: "reel-dim", text: "Same picker as /promo-resume." })),
        h("span", { class: "reel-go", text: "Projects" })),
      h("p", { class: "reel-dim", text: "No promo session is running." }));
  }

  function startPromo() {
    const brief = state.brief.trim();
    if (!brief) { state.err = "Say what the video is for."; state.note = ""; paint(); return; }
    state.err = "";
    state.note = "";
    state.busy = "Checking…";
    paint();
    call("promo.start", { brief, voice: state.voice || null }).then((r) => {
      state.busy = "";
      state.note = r && r.voice
        ? "Checked, with voice " + r.voice + ". " + KICKOFF_NOTE
        : "Checked. Opening a thread comes in a later update.";
      paint();
    }).catch(fail);
  }

  function viewEmpty() {
    return h("div", { class: "reel-empty" },
      h("h2", { class: "reel-h", text: "Your voice, for your videos" }),
      h("p", { class: "reel-dim", text: "Read a short script out loud (about 30 seconds) and four quick lines in different moods. We make a voice that sounds like you and can narrate any promo." }),
      h("button", { type: "button", class: "btn primary", onclick: beginRecord }, "Record my voice"),
      h("p", { class: "reel-dim", text: "You'll need: a quiet room · any mic (AirPods are fine) · 2 minutes" }),
      h("p", { class: "reel-dim", text: "Recordings and voices stay on this Mac. Model: Chatterbox (MIT)." }),
      h("p", { class: "reel-dim", text: MIC_NOTE }),
      modelButton());
  }

  function viewList() {
    const voices = state.voices || [];
    return h("div", { class: "reel-stack" },
      h("div", { class: "reel-row" },
        h("div", {}, h("h2", { class: "reel-h", text: "Your voices" }), h("p", { class: "reel-dim", text: "Pick one when you start a promo. Kept on this Mac." })),
        h("button", { type: "button", class: "btn primary", onclick: beginRecord }, "New voice")),
      voices.map(voiceCard),
      h("div", { class: "reel-row" }, modelButton(), h("span", { class: "reel-dim", text: "Licence: Chatterbox, MIT · your own voice, consent recorded. Perth watermark stays on every take." })));
  }

  function voiceCard(v) {
    const hear = () => {
      state.busy = "Making a sample…";
      state.pct = 0;
      state.long = true;
      state.err = "";
      paint();
      call("voices.sample", { id: v.id, text: state.sampleText || SAMPLE, emotion: state.mood, intensity: state.strength / 100 }, { slow: true }).then((r) => {
        state.busy = "";
        if (r && r.wav_base64) playUrl("data:audio/wav;base64," + r.wav_base64);
        else if (v.sample_b64) playUrl("data:audio/wav;base64," + v.sample_b64);
        paint();
      }).catch(fail);
    };
    const renaming = state.renaming === v.id;
    return h("article", { class: "reel-card" },
      h("div", { class: "reel-row" },
        h("button", { type: "button", class: "reel-play", "aria-label": "Play sample", onclick: () => { if (v.sample_b64) playUrl("data:audio/wav;base64," + v.sample_b64); else hear(); } }, ic(state.audio ? "play" : "play")),
        h("div", { class: "reel-grow" },
          renaming
            ? h("input", { class: "reel-inline", value: state.renameText, "aria-label": "Voice name", oninput: (e) => { state.renameText = e.target.value; } })
            : h("b", { text: v.name }),
          h("div", { class: "reel-dim", text: v.default ? "Default voice" : "On this Mac" })),
        h("div", { class: "reel-wave", "aria-hidden": "true" }, Array.from({ length: 18 }, () => h("i"))),
        renaming
          ? h("button", { type: "button", class: "btn ghost sm", onclick: () => call("voices.rename", { id: v.id, name: state.renameText }).then(() => refresh("Renamed.")).catch(fail) }, "Save")
          : h("button", { type: "button", class: "btn ghost sm", onclick: () => { state.renaming = v.id; state.renameText = v.name; state.arm = null; paint(); } }, "Rename"),
        state.arm === v.id
          ? h("span", { class: "reel-row" },
            h("button", { type: "button", class: "btn ghost sm reel-bad", onclick: () => call("voices.delete", { id: v.id }).then(() => { state.arm = null; refresh("Deleted " + v.name + "."); }).catch(fail) }, "Delete"),
            h("button", { type: "button", class: "btn ghost sm", onclick: () => { state.arm = null; paint(); } }, "Cancel"))
          : h("button", { type: "button", class: "btn ghost sm reel-bad", onclick: () => { state.arm = v.id; state.renaming = null; paint(); } }, "Delete")),
      h("label", { class: "reel-check" },
        h("input", { type: "checkbox", checked: v.default ? "checked" : null, onchange: (e) => { if (v.default) { e.target.checked = true; return; } call("voices.default", { id: v.id }).then(() => refresh("")).catch(fail); } }),
        "Default for new promos"),
      h("label", { class: "sr", for: "reel-sample-" + v.id, text: "Sample line" }),
      h("input", { id: "reel-sample-" + v.id, class: "reel-inline", value: state.sampleText, oninput: (e) => { state.sampleText = e.target.value; } }),
      h("div", { class: "reel-row" },
        h("span", { class: "reel-dim", text: "Mood" }),
        h("div", { class: "reel-seg", role: "group", "aria-label": "Mood" }, MOODS.map((emo) => h("button", {
          type: "button", class: state.mood === emo ? "on" : "", "aria-pressed": state.mood === emo ? "true" : "false",
          onclick: () => { state.mood = emo; paint(); },
        }, LABEL[emo]))),
        h("span", { class: "reel-dim", text: "Strength" }),
        h("input", { type: "range", min: "0", max: "100", value: String(state.strength), "aria-label": "Strength", oninput: (e) => { state.strength = +e.target.value; } }),
        h("button", { type: "button", class: "btn ghost sm", onclick: hear }, "Hear")));
  }

  function refresh(note) {
    state.busy = "";
    state.renaming = null;
    if (note) state.note = note;
    return call("voices.list").then((v) => { state.voices = Array.isArray(v) ? v : []; paint(); });
  }

  function viewRecord() {
    const f = state.flow;
    const paras = paragraphs();
    const part = paras.length ? Math.min(f.part, paras.length - 1) : 0;
    const title = TITLES[part] || ("Part " + (part + 1));
    const total = scriptSeconds();
    const now = total + (live && f.step === 1 ? (Date.now() - live.t0) / 1000 : 0);
    const moodsReady = MOODS.every((emo) => f.moods[emo]);
    const canSave = total >= 30 && moodsReady && !live;
    if (f.step === 1) {
      return h("div", { class: "reel-stack" },
        h("div", { class: "reel-row" },
          h("div", {}, h("div", { class: "reel-dim", text: "New voice · Step 1 of 2" }), h("h2", { class: "reel-h", text: "Read each part out loud" })),
          h("button", { type: "button", class: "btn ghost", onclick: () => { haltPlayback(); state.flow = null; paint(); } }, "Cancel")),
        h("div", { class: "reel-card" },
          h("div", { class: "reel-dim", text: "Part " + (part + 1) + " of " + (paras.length || 5) + " · " + title }),
          h("p", { class: "reel-read", text: paras[part] || "Loading the script…" }),
          h("p", { class: "reel-dim", text: MIC_NOTE }),
          h("div", { class: "reel-row" },
            h("button", { type: "button", class: "reel-rec" + (live ? " on" : ""), "aria-label": live ? "Stop" : "Record", onclick: () => togglePart() }, live ? ic("pause") : null),
            h("div", {},
              h("div", { class: "reel-time" }, h("span", { "data-reel-meter": "1", text: fmt(now) }), h("span", { class: "reel-dim", text: " of 0:30 needed" })),
              h("div", { class: "reel-dim", "data-reel-sub": "1", text: "" })),
            h("button", { type: "button", class: "btn ghost sm", disabled: part >= paras.length - 1, onclick: () => { keepLive(); f.part = Math.min(paras.length - 1, part + 1); paint(); } }, "Next part")),
          h("div", { class: "reel-meter", "aria-hidden": "true" }, h("i", { "data-reel-bar": "1", style: "width:" + Math.min(100, (now / 30) * 100) + "%" }))),
        h("div", { class: "reel-card reel-list" }, paras.map((text, i) => h("div", { class: "reel-sec" },
          h("span", { class: "reel-dot" + (f.clips[i] ? " ok" : i === part ? " now" : ""), text: f.clips[i] ? "✓" : "" }),
          h("span", { class: "reel-grow", text: TITLES[i] || ("Part " + (i + 1)) }),
          f.clips[i] ? h("button", { type: "button", class: "btn ghost sm", onclick: () => { f.part = i; paint(); } }, "Redo") : h("span", { class: "reel-dim", text: i === part && live ? "now" : "" })))),
        h("div", { class: "reel-card" },
          h("p", { class: "reel-dim", text: "Then step 2 · four moods, a few seconds each" }),
          MOODS.map((emo) => h("div", { class: "reel-sec" }, h("span", { class: "reel-dot", text: "" }), h("span", { class: "reel-grow", text: LABEL[emo] }), h("span", { class: "reel-dim", text: "after the script" }))),
          h("p", { class: "reel-dim", text: 'e.g. Excited: "It shipped overnight, and the tests pass!"' })),
        h("button", { type: "button", class: "btn primary", disabled: !f.clips.some(Boolean), onclick: () => { keepLive(); f.step = 2; paint(); } }, "Continue to moods"));
    }
    return h("div", { class: "reel-stack" },
      h("div", { class: "reel-row" },
        h("div", {}, h("div", { class: "reel-dim", text: "New voice · Step 2 of 2" }), h("h2", { class: "reel-h", text: "Say one line in each mood" })),
        h("button", { type: "button", class: "btn ghost", onclick: () => { keepLive(); f.step = 1; paint(); } }, "Back")),
      h("p", { class: "reel-dim", text: total >= 30 ? "Script is " + fmt(total) + ". That's enough." : "Script is " + fmt(total) + " of 0:30. Record a bit more before saving." }),
      MOODS.map((emo) => h("div", { class: "reel-card" },
        h("div", { class: "reel-row" },
          h("b", { text: LABEL[emo] }),
          h("button", { type: "button", class: "btn ghost sm", onclick: () => toggleMood(emo) }, live && f.mood === emo ? "Stop" : (f.moods[emo] ? "Redo" : "Record")),
          f.moods[emo] ? h("button", { type: "button", class: "btn ghost sm", onclick: () => playUrl(f.moods[emo].url) }, "Play") : null),
        h("p", { class: "reel-read", text: emotionLine(emo) }))),
      h("label", { class: "reel-dim", text: "Name" }),
      h("input", { class: "reel-inline", placeholder: "My voice", value: f.name, "aria-label": "Voice name", oninput: (e) => { f.name = e.target.value; } }),
      h("button", { type: "button", class: "btn primary", disabled: !canSave, onclick: saveFlow }, canSave ? "Save voice" : "Need 30 s and all four moods"),
      h("p", { class: "reel-dim", text: AUDIO_NOTE }));
  }

  function togglePart() {
    const f = state.flow;
    if (live) {
      f.clips[f.part] = stopLive();
      paint();
      return;
    }
    f.mood = null;
    startLive();
  }

  function toggleMood(emo) {
    const f = state.flow;
    if (live && f.mood === emo) {
      f.moods[emo] = stopLive();
      f.mood = null;
      paint();
      return;
    }
    keepLive();
    f.mood = emo;
    f.step = 2;
    startLive();
  }

  async function saveFlow() {
    const f = state.flow;
    if (!f) return;
    keepLive();
    state.busy = "Saving…";
    state.pct = 0;
    state.long = true;
    state.err = "";
    paint();
    try {
      const script = [];
      for (let i = 0; i < f.clips.length; i++) {
        if (!f.clips[i]) continue;
        script.push({ name: String(i + 1).padStart(2, "0") + ".wav", base64: await blobB64(f.clips[i].blob) });
      }
      const moods = {};
      for (const emo of MOODS) moods[emo] = { name: emo + ".wav", base64: await blobB64(f.moods[emo].blob) };
      const rec = await call("voices.save", { name: (f.name || "My voice").trim() || "My voice", script, moods }, { slow: true });
      state.flow = null;
      state.voice = rec && rec.id ? rec.id : state.voice;
      state.note = "Saved " + ((rec && rec.name) || "your voice") + ".";
      await refresh("");
      state.tab = "voices";
      paint();
    } catch (e) { fail(e); }
  }

  function viewProjects() {
    const rows = state.projects || [];
    return h("div", { class: "reel-stack" },
      h("h2", { class: "reel-h", text: "Projects" }),
      h("p", { class: "reel-dim", text: "Past promos open with /promo-resume. That is the promo-projects pane, the same picker as today." }),
      rows.length ? rows.map((p) => h("div", { class: "reel-card" }, h("b", { text: p.title || p.name || "Project" }), h("div", { class: "reel-dim", text: p.name || "" }))) : h("p", { class: "reel-dim", text: "Nothing is loaded in this pane yet." }));
  }

  function viewVoices() {
    if (state.flow) return viewRecord();
    if (!state.voices) return h("p", { class: "reel-dim", text: "Loading voices…" });
    if (!state.voices.length) return viewEmpty();
    return viewList();
  }

  function paint() {
    if (!alive || !api || !api.content) return;
    const body = state.tab === "start" ? viewStart() : state.tab === "projects" ? viewProjects() : viewVoices();
    api.content.replaceChildren(h("div", { class: "reel" }, tabs(), banner(), body));
    tickMeter();
  }

  function active() {
    return !!live || !!state.flow || !!state.busy || anyLong();
  }

  function select(id) {
    if (id !== "start" && id !== "voices" && id !== "projects") return;
    keepLive();
    state.tab = id;
    state.err = "";
  }

  function current() { return state.tab || "start"; }

  function halt() { haltPlayback(); }

  function render(opts) {
    alive = true;
    api = opts;
    state.projects = opts.projects || null;
    state.hideTabs = !!opts.hideTabs;
    ensure();
    paint();
  }

  function stop() {
    alive = false;
    haltPlayback();
    const post = api && api.post;
    for (const [id, c] of [...calls]) {
      clearTimeout(c.timer);
      if (post) post({ type: "cancel", id });
      c.reject({ code: "host.cancelled", silent: true });
    }
    calls.clear();
    state.booted = false;
    state.busy = "";
    state.pct = null;
    state.long = false;
  }

  return { render, onAccepted, onResult, onProgress, stop, select, current, active, halt };
})();
