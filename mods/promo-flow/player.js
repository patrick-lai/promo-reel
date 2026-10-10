"use strict";
/* The draft player: our own controls so notes live on the timeline. A mark sits on the seek bar at each note; hover reads it, click edits it, drag
   moves it, N (or + Note) adds one where the playhead is. Scenes from the storyboard run under the bar, hovering the bar shows the frame there, and the
   keys an editor expects work while the player has focus (? lists them). Notes change only through `onChange`; the caller owns them. */
(function (root) {
  const RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
  const FLASH_MS = 2600;
  const CLUSTER_PX = 14;
  const DRAG_PX = 4;
  const KEYS = [
    ["Space / K", "Play or pause"], ["J / L", "Back / forward 5 s"], ["← / →", "Back / forward 1 s (Shift: 5 s)"], [", / .", "One frame back / forward"],
    ["[ / ]", "Previous / next note"], ["N", "New note at the playhead"], ["E", "Edit the note at the playhead"], ["I / O", "Loop from / to here"],
    ["X", "Clear the loop"], ["M", "Mute"], ["F", "Full screen"], ["0–9", "Jump to 0%–90%"], ["Home / End", "Start / end"], ["?", "This list"]];

  const two = (n) => String(n).padStart(2, "0");
  function clock(s) {
    s = Math.max(0, s || 0);
    const t = Math.floor(s * 10 + 1e-6);
    return Math.floor(t / 600) + ":" + two(Math.floor(t / 10) % 60) + "." + (t % 10);
  }
  function timecode(s, fps) {
    const f = Math.floor(Math.max(0, s || 0) * fps + 1e-6);
    return two(Math.floor(f / fps / 60)) + ":" + two(Math.floor(f / fps) % 60) + ":" + two(f % fps);
  }

  function create(o) {
    const { h, ic } = o;
    const fps = o.fps || 30;
    let notes = o.notes || [], scenes = o.scenes || [], editable = !!o.editable;
    let fmt = "clock", loop = null, editing = null, drag = null, flashTimer = 0, raf = 0, lastT = 0, thumb = null, thumbWant = null, thumbBusy = false;

    const video = h("video", { src: o.src, preload: "metadata", playsinline: "", "aria-label": o.label });
    const bigPlay = h("button", { type: "button", class: "pfp-big", "aria-label": "Play", tabindex: "-1" }, ic("play"));
    const flash = h("div", { class: "pfp-flash", "aria-live": "polite", hidden: true });
    const help = h("div", { class: "pfp-help", role: "dialog", "aria-label": "Keyboard shortcuts", hidden: true },
      h("div", { class: "pfp-help-h" }, h("b", { text: "Keys while the player has focus" }), h("button", { type: "button", class: "pfp-x", "aria-label": "Close", onclick: () => toggleHelp(false) }, ic("close"))),
      h("dl", null, KEYS.map(([k, v]) => h("div", null, h("dt", null, h("kbd", { text: k })), h("dd", { text: v })))));
    const stage = h("div", { class: "pfp-stage" }, video, bigPlay, flash, help);

    const buf = h("i", { class: "pfp-buf" }), prog = h("i", { class: "pfp-prog" }), loopBand = h("i", { class: "pfp-loopband", hidden: true }), head = h("i", { class: "pfp-head" });
    const track = h("div", { class: "pfp-track", role: "slider", tabindex: "-1", "aria-label": "Seek", "aria-valuemin": "0" }, buf, loopBand, prog, head);
    const lane = h("div", { class: "pfp-lane", role: "list", "aria-label": "Notes on the timeline" });
    const strip = h("div", { class: "pfp-scenes", "aria-hidden": "true" });
    const tipTime = h("span", { class: "pfp-tip-t" }), tipScene = h("span", { class: "pfp-tip-s" });
    const canvas = h("canvas", { width: "160", height: "90", class: "pfp-thumb" });
    const tip = h("div", { class: "pfp-tip", hidden: true, "aria-hidden": "true" }, canvas, h("div", { class: "pfp-tip-row" }, tipTime, tipScene));
    const card = h("div", { class: "pfp-card", hidden: true, role: "tooltip" });
    const editor = h("form", { class: "pfp-edit", hidden: true, "aria-label": "Note" });
    const tl = h("div", { class: "pfp-tl" }, lane, track, strip, tip, card, editor);

    const btn = (icon, label, fn, cls) => h("button", { type: "button", class: "pfp-b" + (cls ? " " + cls : ""), "aria-label": label, title: label, onclick: fn }, ic(icon));
    const playBtn = btn("play", "Play (Space)", () => toggle());
    const timeBtn = h("button", { type: "button", class: "pfp-time", title: "Switch between seconds and timecode", onclick: () => { fmt = fmt === "clock" ? "tc" : "clock"; paint(); } });
    const addBtn = h("button", { type: "button", class: "pfp-add", title: "New note at the playhead (N)", onclick: () => openEditor(null) }, ic("plus"), h("span", { text: "Note" }));
    const loopBtn = btn("loop", "Loop (I and O set a range, X clears)", () => { loop = loop ? null : { a: 0, b: video.duration || 0 }; paint(); }, "pfp-loop");
    const rate = h("select", { class: "pfp-rate", "aria-label": "Speed", title: "Speed" }, RATES.map((r) => h("option", { value: String(r), selected: r === 1 }, r + "×")));
    rate.addEventListener("change", () => { video.playbackRate = +rate.value; });
    const muteBtn = btn("vol", "Mute (M)", () => { video.muted = !video.muted; });
    const vol = h("input", { type: "range", class: "pfp-vol", min: "0", max: "1", step: "0.05", value: "1", "aria-label": "Volume" });
    vol.addEventListener("input", () => { video.volume = +vol.value; video.muted = +vol.value === 0; });
    const fsBtn = btn("expand", "Full screen (F)", () => fullscreen());
    const ctl = h("div", { class: "pfp-ctl" },
      h("div", { class: "pfp-grp" }, playBtn, btn("stepL", "One frame back (,)", () => step(-1)), btn("stepR", "One frame forward (.)", () => step(1)),
        btn("left", "Previous note ([)", () => jumpNote(-1), "pfp-nav"), btn("right", "Next note (])", () => jumpNote(1), "pfp-nav"), timeBtn),
      h("div", { class: "pfp-grp" }, addBtn, loopBtn, rate, h("span", { class: "pfp-volw" }, muteBtn, vol), btn("keys", "Keyboard shortcuts (?)", () => toggleHelp()), fsBtn));
    const err = h("p", { class: "pfp-err", role: "alert", hidden: true });

    const el = h("div", { class: "pfp", tabindex: "0", role: "region", "aria-label": "Player: " + o.label + ". Press ? for keys.", "data-k": "player" }, stage, h("div", { class: "pfp-bar" }, tl, ctl), err);

    const dur = () => (isFinite(video.duration) && video.duration > 0 ? video.duration : 0);
    const pct = (t) => (dur() ? Math.min(100, Math.max(0, (t / dur()) * 100)) : 0);
    const tAt = (clientX) => { const r = track.getBoundingClientRect(); return dur() * Math.min(1, Math.max(0, (clientX - r.left) / r.width)); };
    const fmtT = (t) => (fmt === "tc" ? timecode(t, fps) : clock(t));
    const sceneAt = (t) => scenes.find((s) => t >= s.start_s && t < s.end_s) || null;
    const seek = (t) => { video.currentTime = Math.min(dur() || t, Math.max(0, t)); paint(); };
    const play = () => video.play().catch((e) => { if (e.name !== "AbortError") showErr("This video can't play here: " + e.message); });
    function toggle() { if (video.paused || video.ended) play(); else video.pause(); }
    function step(n) { video.pause(); seek(Math.round(video.currentTime * fps + n) / fps + 1e-4); }
    function showErr(t) { err.textContent = t; err.hidden = false; }

    function paint() {
      const t = video.currentTime, d = dur();
      prog.style.width = pct(t) + "%";
      head.style.left = pct(t) + "%";
      timeBtn.textContent = fmtT(t) + " / " + fmtT(d);
      track.setAttribute("aria-valuemax", String(Math.round(d * 10) / 10));
      track.setAttribute("aria-valuenow", String(Math.round(t * 10) / 10));
      track.setAttribute("aria-valuetext", clock(t) + " of " + clock(d));
      const on = !video.paused && !video.ended;
      playBtn.replaceChildren(ic(on ? "pause" : "play"));
      playBtn.setAttribute("aria-label", on ? "Pause (Space)" : "Play (Space)");
      el.classList.toggle("playing", on);
      muteBtn.replaceChildren(ic(video.muted || video.volume === 0 ? "mute" : "vol"));
      loopBtn.setAttribute("aria-pressed", String(!!loop));
      loopBand.hidden = !loop || !d;
      if (loop && d) { loopBand.style.left = pct(loop.a) + "%"; loopBand.style.width = (pct(loop.b) - pct(loop.a)) + "%"; }
      if (video.buffered.length && d) buf.style.width = pct(video.buffered.end(video.buffered.length - 1)) + "%";
    }
    function tick() {
      const t = video.currentTime;
      if (loop && loop.b > loop.a && t >= loop.b) video.currentTime = loop.a;
      else if (t > lastT && t - lastT < 1) { const hit = notes.find((n) => n.state !== "removed" && n.at > lastT && n.at <= t); if (hit) showFlash(hit); }
      lastT = video.currentTime;
      paint();
      raf = !video.paused && !video.ended ? requestAnimationFrame(tick) : 0;
    }
    function showFlash(n) {
      flash.replaceChildren(h("span", { class: "pfp-flash-t", text: clock(n.at) }), h("span", { text: n.text }));
      flash.hidden = false;
      clearTimeout(flashTimer);
      flashTimer = setTimeout(() => { flash.hidden = true; }, FLASH_MS);
    }
    for (const ev of ["play", "pause", "seeked", "loadedmetadata", "volumechange", "progress", "ended", "ratechange"]) video.addEventListener(ev, () => {
      if (ev === "loadedmetadata") { drawNotes(); drawScenes(); }
      if (ev === "seeked") lastT = video.currentTime;
      if (ev === "play") el.classList.add("started");
      if (ev === "play" && !raf) { lastT = video.currentTime; raf = requestAnimationFrame(tick); }
      if (ev === "ratechange") rate.value = String(video.playbackRate);
      if (ev === "volumechange") vol.value = String(video.muted ? 0 : video.volume);
      paint();
    });
    video.addEventListener("error", () => showErr("This video file could not be read. Ask the agent to render the draft again."));
    video.addEventListener("click", () => { el.focus({ preventScroll: true }); toggle(); });
    video.addEventListener("dblclick", () => fullscreen());
    bigPlay.addEventListener("click", () => { el.focus({ preventScroll: true }); play(); });

    /* ---- the bar: seek by click or drag, preview on hover ---- */
    track.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      track.setPointerCapture(e.pointerId);
      const was = !video.paused;
      video.pause();
      seek(tAt(e.clientX));
      const mv = (ev) => { seek(tAt(ev.clientX)); hover(ev.clientX); };
      const up = () => { track.removeEventListener("pointermove", mv); track.removeEventListener("pointerup", up); track.removeEventListener("pointercancel", up); if (was) play(); };
      track.addEventListener("pointermove", mv);
      track.addEventListener("pointerup", up);
      track.addEventListener("pointercancel", up);
    });
    track.addEventListener("dblclick", (e) => openEditor(null, tAt(e.clientX)));
    for (const n of [track, strip]) {
      n.addEventListener("pointermove", (e) => hover(e.clientX));
      n.addEventListener("pointerleave", () => { tip.hidden = true; });
    }
    function place(node, clientX) {
      const r = tl.getBoundingClientRect(), w = node.offsetWidth;
      node.style.left = Math.min(r.width - w, Math.max(0, clientX - r.left - w / 2)) + "px";
    }
    function hover(clientX) {
      if (!dur()) return;
      const t = tAt(clientX), s = sceneAt(t);
      tipTime.textContent = fmtT(t);
      tipScene.textContent = s ? "Scene " + s.id + (s.beat ? " · " + s.beat : "") : "";
      tip.hidden = false;
      place(tip, clientX);
      thumbAt(t);
    }
    /* A second, silent copy of the clip seeks to the hovered moment; the newest wish wins and the frame is drawn when it lands. */
    function thumbAt(t) {
      if (!thumb) {
        thumb = h("video", { src: o.src, preload: "auto", muted: "", playsinline: "", "aria-hidden": "true", tabindex: "-1", class: "pfp-thumbsrc" });
        thumb.muted = true;
        thumb.addEventListener("seeked", () => {
          canvas.getContext("2d").drawImage(thumb, 0, 0, canvas.width, canvas.height);
          thumbBusy = false;
          if (thumbWant != null) { const w = thumbWant; thumbWant = null; thumbAt(w); }
        });
        thumb.addEventListener("loadedmetadata", () => { if (thumbWant != null) { const w = thumbWant; thumbWant = null; thumbAt(w); } });
        el.append(thumb);
      }
      if (thumbBusy || thumb.readyState < 1) { thumbWant = t; return; }
      thumbBusy = true;
      thumb.currentTime = t;
    }
    function drawScenes() {
      const d = dur();
      const w = track.clientWidth || 600;
      strip.replaceChildren(...(d ? scenes.filter((s) => s.start_s < d) : []).map((s) => {
        const span = pct(Math.min(s.end_s, d)) - pct(s.start_s);
        return h("span", { class: "pfp-sc", style: "left:" + pct(s.start_s) + "%;width:" + span + "%", title: "Scene " + s.id + (s.beat ? ": " + s.beat : "") }, (span / 100) * w >= 8 * String(s.id).length + 8 ? h("b", { text: s.id }) : null);
      }));
      strip.hidden = !strip.childElementCount;
    }

    /* ---- notes on the bar ---- */
    function clusters() {
      const w = track.clientWidth || 600, d = dur(), out = [];
      for (const n of notes) {
        const x = d ? (n.at / d) * w : 0, last = out[out.length - 1];
        if (last && x - last.x < CLUSTER_PX) last.items.push(n); else out.push({ x, items: [n] });
      }
      return out;
    }
    function drawNotes() {
      lane.replaceChildren(...(dur() ? clusters() : []).map((c) => {
        const n = c.items[0], many = c.items.length > 1;
        const state = many ? (c.items.some((x) => x.state !== "saved") ? "mixed" : "saved") : n.state + (n.sent ? " sent" : "");
        const g = h("button", { type: "button", class: "pfp-mark", role: "listitem", "data-state": state, style: "left:" + pct(n.at) + "%",
          "aria-label": many ? c.items.length + " notes near " + clock(n.at) : "Note at " + clock(n.at) + ": " + n.text + (n.state === "removed" ? " (to be removed)" : "") },
          ic("comment"), many ? h("b", { class: "pfp-count", text: String(c.items.length) }) : null);
        g.addEventListener("pointerenter", () => showCard(c.items, g));
        g.addEventListener("focus", () => showCard(c.items, g));
        g.addEventListener("pointerleave", () => hideCardSoon());
        g.addEventListener("blur", () => hideCardSoon());
        g.addEventListener("keydown", (e) => { if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); if (!many && canEdit(n)) change({ op: "remove", key: n.key }); } });
        g.addEventListener("pointerdown", (e) => startDrag(e, c, g));
        return g;
      }));
    }
    const canEdit = (n) => editable && !n.sent;
    function startDrag(e, c, g) {
      if (e.button !== 0) return;
      e.preventDefault();
      const n = c.items[0], x0 = e.clientX;
      g.setPointerCapture(e.pointerId);
      drag = { moved: false };
      const mv = (ev) => {
        if (c.items.length > 1 || !canEdit(n) || n.state === "removed") return;
        if (!drag.moved && Math.abs(ev.clientX - x0) < DRAG_PX) return;
        drag.moved = true;
        hideCard();
        g.classList.add("drag");
        g.style.left = pct(tAt(ev.clientX)) + "%";
        hover(ev.clientX);
      };
      const up = (ev) => {
        g.removeEventListener("pointermove", mv); g.removeEventListener("pointerup", up); g.removeEventListener("pointercancel", up);
        const moved = drag.moved;
        drag = null;
        tip.hidden = true;
        if (moved && ev.type === "pointerup") { const t = tAt(ev.clientX); seek(t); change({ op: "edit", key: n.key, at: t }); return; }
        if (moved) { drawNotes(); return; }
        seek(n.at);
        if (c.items.length === 1) openEditor(n); else showCard(c.items, g, true);
      };
      g.addEventListener("pointermove", mv); g.addEventListener("pointerup", up); g.addEventListener("pointercancel", up);
    }
    let cardTimer = 0, cardPinned = false;
    function showCard(items, g, pinned) {
      if (drag || editing) return;
      clearTimeout(cardTimer);
      cardPinned = !!pinned;
      const STATE = { new: "New, not sent", edited: "Changed, not sent", removed: "To be removed, not sent", saved: "" };
      card.replaceChildren(...items.map((n) => h("div", { class: "pfp-card-n" },
        h("div", { class: "pfp-card-h" }, h("b", { text: clock(n.at) }), n.scene ? h("span", { text: "Scene " + n.scene }) : null, n.by ? h("span", { text: n.by }) : null,
          n.sent ? h("em", { text: "Sent, waiting for the agent" }) : STATE[n.state] ? h("em", { text: STATE[n.state] }) : null),
        h("p", { class: n.state === "removed" ? "gone" : "", text: n.text }),
        n.was && n.was.text !== n.text ? h("p", { class: "pfp-was", text: "Was: " + n.was.text }) : null,
        canEdit(n) ? h("div", { class: "pfp-card-a" },
          h("button", { type: "button", text: n.state === "removed" ? "Keep it" : "Edit", onclick: () => (n.state === "removed" ? change({ op: "edit", key: n.key, at: n.at }) : openEditor(n)) }),
          items.length > 1 ? h("button", { type: "button", text: "Go to", onclick: () => seek(n.at) }) : null) : null)),
      items.every(canEdit) && items.length === 1 && items[0].state !== "removed" ? h("p", { class: "pfp-card-tip", text: "Click to edit · drag to move" }) : null);
      card.hidden = false;
      const r = g.getBoundingClientRect();
      place(card, r.left + r.width / 2);
    }
    function hideCard() { clearTimeout(cardTimer); card.hidden = true; cardPinned = false; }
    function hideCardSoon() { if (cardPinned) return; clearTimeout(cardTimer); cardTimer = setTimeout(hideCard, 160); }
    card.addEventListener("pointerenter", () => clearTimeout(cardTimer));
    card.addEventListener("pointerleave", () => hideCardSoon());

    /* ---- the note editor: a new note (n = null) or an existing one ---- */
    function openEditor(n, at) {
      if (!editable || (n && !canEdit(n))) return;
      hideCard();
      video.pause();
      const t = n ? n.at : at != null ? at : video.currentTime;
      editing = { n, at: Math.round(t * 100) / 100 };
      if (!n) seek(t);
      const when = h("b", { class: "pfp-when" });
      const sc = h("span", { class: "pfp-ed-sc" });
      const showWhen = () => { when.textContent = clock(editing.at); const s = sceneAt(editing.at); sc.textContent = s ? "Scene " + s.id : ""; };
      showWhen();
      const ta = h("textarea", { rows: "3", maxlength: "1500", placeholder: "What should change here?", "aria-label": "Note", "data-dictate": "" });
      ta.value = n ? n.text : "";
      const save = h("button", { type: "submit", class: "pfp-save", text: n ? "Save" : "Add note" });
      const sync = () => { save.disabled = !ta.value.trim(); };
      ta.addEventListener("input", sync);
      sync();
      editor.replaceChildren(
        h("div", { class: "pfp-ed-h" }, h("span", null, n ? "Note at " : "New note at ", when), sc,
          h("button", { type: "button", class: "pfp-mini", title: "Move the note to the playhead", text: "Use playhead", onclick: () => { editing.at = Math.round(video.currentTime * 100) / 100; showWhen(); } })),
        ta,
        h("div", { class: "pfp-ed-a" },
          n ? h("button", { type: "button", class: "pfp-del", text: "Delete", onclick: () => { closeEditor(); change({ op: "remove", key: n.key }); } }) : null,
          h("span", { class: "pfp-ed-k", text: "↵ saves · Shift+↵ new line · Esc cancels" }),
          h("button", { type: "button", class: "pfp-cancel", text: "Cancel", onclick: () => closeEditor() }), save));
      editor.onsubmit = (e) => {
        e.preventDefault();
        if (!ta.value.trim()) return;
        const ed = editing;
        closeEditor();
        change(ed.n ? { op: "edit", key: ed.n.key, at: ed.at, text: ta.value } : { op: "add", key: o.newKey(), at: ed.at, text: ta.value });
      };
      ta.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); editor.requestSubmit(); }
        else if (e.key === "Escape") { e.preventDefault(); closeEditor(); }
        e.stopPropagation();
      });
      editor.hidden = false;
      const r = track.getBoundingClientRect();
      place(editor, r.left + (pct(editing.at) / 100) * r.width);
      ta.focus();
    }
    function closeEditor() { editing = null; editor.hidden = true; editor.replaceChildren(); el.focus({ preventScroll: true }); }
    function change(ch) { o.onChange(ch); }
    function jumpNote(dir) {
      const t = video.currentTime, list = notes.filter((n) => n.state !== "removed");
      const n = dir > 0 ? list.find((x) => x.at > t + 0.05) : list.slice().reverse().find((x) => x.at < t - 0.05);
      if (!n) return;
      video.pause();
      seek(n.at);
      const g = [...lane.children].find((x) => x.style.left === pct(n.at) + "%");
      if (g) showCard([n], g);
    }

    function fullscreen() {
      const rootNode = el.getRootNode();
      if (rootNode.fullscreenElement === el) return document.exitFullscreen();
      if (el.classList.contains("max")) { el.classList.remove("max"); return; }
      if (!el.requestFullscreen) { el.classList.add("max"); return; }
      el.requestFullscreen().catch(() => el.classList.add("max"));   // the host's frame may not allow full screen: fill the pane instead
    }
    function toggleHelp(on) { help.hidden = on == null ? !help.hidden : !on; }

    el.addEventListener("keydown", (e) => {
      const t = e.target, tag = t.tagName;
      if (tag === "TEXTAREA" || tag === "INPUT" || tag === "SELECT" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (tag === "BUTTON" && (e.key === " " || e.key === "Enter")) return;
      const d = dur(), k = e.key;
      const act = {
        " ": toggle, k: toggle, j: () => seek(video.currentTime - 5), l: () => seek(video.currentTime + 5),
        ArrowLeft: () => seek(video.currentTime - (e.shiftKey ? 5 : 1)), ArrowRight: () => seek(video.currentTime + (e.shiftKey ? 5 : 1)),
        ",": () => step(-1), ".": () => step(1), "[": () => jumpNote(-1), "]": () => jumpNote(1), n: () => openEditor(null),
        e: () => { const n = notes.find((x) => Math.abs(x.at - video.currentTime) < 0.5 && canEdit(x)); if (n) openEditor(n); },
        i: () => { loop = { a: video.currentTime, b: loop && loop.b > video.currentTime ? loop.b : d }; paint(); },
        o: () => { loop = { a: loop && loop.a < video.currentTime ? loop.a : 0, b: video.currentTime }; paint(); },
        x: () => { loop = null; paint(); }, m: () => { video.muted = !video.muted; }, f: fullscreen, "?": () => toggleHelp(),
        Home: () => seek(0), End: () => seek(d), Escape: () => { if (!help.hidden) toggleHelp(false); else if (el.classList.contains("max")) el.classList.remove("max"); else return false; },
      }[k.length === 1 ? k.toLowerCase() : k] || (/^[0-9]$/.test(k) ? () => seek((d * +k) / 10) : null);
      if (!act || act() === false) return;
      e.preventDefault();
      e.stopPropagation();
    });
    document.addEventListener("fullscreenchange", () => fsBtn.replaceChildren(ic(el.getRootNode().fullscreenElement === el ? "shrink" : "expand")));
    new ResizeObserver(() => { if (!drag) drawNotes(); drawScenes(); }).observe(track);

    addBtn.disabled = !editable;
    paint();
    return {
      el, video,
      update(next) {
        if (next.notes) notes = next.notes;
        if (next.scenes) scenes = next.scenes;
        if (next.editable != null) editable = next.editable;
        addBtn.disabled = !editable;
        if (!drag) drawNotes();
        drawScenes();
      },
      busy: () => !!editing || !!drag,
      seek: (t) => { seek(t); el.focus({ preventScroll: true }); },
      edit: (key) => { const n = notes.find((x) => x.key === key); if (n) { seek(n.at); openEditor(n); } },
      addAt: (t) => openEditor(null, t == null ? video.currentTime : t),
    };
  }

  root.PFPlayer = { create };
})(typeof window !== "undefined" ? window : globalThis);
