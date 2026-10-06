"use strict";
/* Pure derivations for the promo-flow mod (no DOM, no bridge): what each scene's footage status is, the one derived asset model with its exclusive
   buckets, and the gate rules. Loaded as a classic script (window.PF) and by `node --test` (module.exports). */
(function (root) {
  const arr = (x) => (Array.isArray(x) ? x : []);
  const VISUAL = { screenshot: 1, image: 1, recording: 1, video: 1 };

  /* The host turns {"$file"} into {"$media": {...}} or {"$media": null, "$error"}; anything else is "no file". */
  function mref(x) {
    if (!x || typeof x !== "object") return null;
    if (x.$media && x.$media.upload_id) return x.$media;
    if ("$media" in x) return { error: x.$error || "This file could not be attached." };
    return null;
  }
  function fileBad(a) {
    if (!a.path) return true;
    const r = mref(a.path);
    return !r || !!r.error;
  }
  const missingFile = (a) => a.state === "ready" && fileBad(a);
  /* What the person can open or play: the asset's real file, else the sample the agent made of it. A frame is an image only when its file loads. */
  const usable = (x) => { const r = x ? mref(x) : null; return !!r && !r.error; };
  const hasPreview = (a) => usable(a.path) || usable(a.sample);
  const noFrame = (f) => !(f && usable(f.path));
  const missingAll = (doc) => arr(doc.assets).filter(missingFile).length;

  /* Footage status of one scene, read by BOTH the chip and the timeline mark.
     Only visual assets (screenshot, image, recording, video) count: a mock or missing music/voice/sfx file does not change what a scene looks like.
     real:      no real asset, or any covering visual asset to make / missing  -> To capture;  any mock -> Mock in plan;
                else Captured (screenshots and images alone: Captured stills, never footage)
     generated: any covering visual asset to make / missing -> Plate to generate; any mock -> Mock in plan; else Generated plate */
  function sceneStatus(s, assets) {
    const made = !!(s.start && mref(s.start.path)) && !!(s.end && mref(s.end.path));
    const id = String(s.id);
    const cov = arr(assets).filter((a) => VISUAL[a.kind] && arr(a.scenes).map(String).includes(id));
    const bad = cov.some((a) => a.state === "todo" || missingFile(a));
    const mock = cov.some((a) => a.state === "mock");
    let kind, label;
    if (s.source === "real") {
      const real = cov.filter((a) => a.source === "real");
      if (!real.length || bad) { kind = "todo"; label = "To capture"; }
      else if (mock) { kind = "mock"; label = "Mock in plan"; }
      else if (real.every((a) => a.kind === "screenshot" || a.kind === "image")) { kind = "stills"; label = "Captured stills"; }
      else { kind = "real"; label = "Captured"; }
    } else if (s.source === "generated") {
      if (bad) { kind = "todo"; label = "Plate to generate"; }
      else if (mock) { kind = "mock"; label = "Mock in plan"; }
      else { kind = "gen"; label = "Generated plate"; }
    } else if (s.source === "mock") { kind = "mock"; label = "Mock in plan"; }
    else return { kind: "other", label: "", cls: made ? "none" : "todo" };
    return { kind, label, cls: made ? kind : "todo" };
  }

  /* ONE derived model for a selected story: the asset rows used in its scenes + its keyframes still to make; buckets are exclusive. */
  function model(doc, board) {
    const ids = new Set(arr((board || {}).scenes).map((x) => String(x.id)));
    const items = [];
    arr(doc.assets).forEach((a, i) => {
      const scenes = arr(a.scenes).map(String).filter((x) => ids.has(x));
      if (!scenes.length && arr(a.scenes).length) return;
      items.push({ type: "asset", a, r: a.path ? mref(a.path) : null, s: a.sample ? mref(a.sample) : null, eff: missingFile(a) ? "missing" : a.state, scenes, i });
    });
    if (board) arr(doc.to_make).forEach((t, i) => { if (t.kind === "keyframe" && t.story === board.id) items.push({ type: "keyframe", t, eff: "todo", i: 1000 + i }); });
    const n = { ready: 0, mock: 0, todo: 0, missing: 0 };
    items.forEach((x) => { n[x.eff]++; });
    return { items, n, total: items.length };
  }

  /* done only when a final exists, every final file resolves, and no approval is stale */
  function finalState(doc) {
    const fs = arr(doc.finals);
    if (!fs.length) return { registered: false, ok: false };
    const ok = fs.every((f) => { const r = mref(f.path); return !!r && !r.error; }) && !arr(doc.stale_steps).length;
    return { registered: true, ok };
  }

  /* With more than one story the person must have opened every story in the tab the gate decides on before the primary says Approve. */
  const SEEN_TAB = { "storyboard-approved": "storyboard", "assets-approved": "assets", "final-confirmation": "storyboard" };
  const seenKey = (tab, id) => tab + ":" + id;
  function seenRule(doc, gateName, seen) {
    const tab = SEEN_TAB[gateName];
    const boards = arr(doc.boards);
    if (!tab || boards.length < 2) return null;
    const un = boards.find((b) => !seen.has(seenKey(tab, b.id)));
    return un ? { board: un.id, tab } : null;
  }

  /* Approve at the assets gate is not backed while a ready asset has no file. */
  function missingRule(doc, gateName) {
    if (gateName !== "assets-approved") return null;
    const n = missingAll(doc);
    return n ? { disabled: true, count: n, note: n + " " + (n === 1 ? "file is" : "files are") + " missing. Send changes so the agent attaches " + (n === 1 ? "it" : "them") + "." } : null;
  }

  /* Nobody approves what they cannot see: a placeholder is not a preview. The storyboard gate needs every START/END/mid frame as an image,
     the assets gate needs every asset to have its file or a sample. `ask` names what the agent is asked to make. */
  function previewRule(doc, gateName) {
    const plural = (n, one, many) => (n === 1 ? one : many);
    if (gateName === "storyboard-approved") {
      const by = {};
      arr(doc.boards).forEach((b) => arr(b.scenes).forEach((s) => { const k = [s.start, s.end, ...arr(s.frames)].filter(noFrame).length; if (k) by[b.id] = (by[b.id] || 0) + k; }));
      const n = Object.values(by).reduce((a, b) => a + b, 0);
      const where = arr(doc.boards).length > 1 ? " (" + Object.entries(by).map(([id, k]) => "story " + id + ": " + k).join(", ") + ")" : "";
      return n ? { disabled: true, count: n, by, ask: "frames", note: n + " " + plural(n, "frame is", "frames are") + " not a real image yet" + where + ". Ask the agent to make " + plural(n, "it", "them") + "." } : null;
    }
    if (gateName === "assets-approved") {
      const n = arr(doc.assets).filter((a) => !hasPreview(a)).length;
      return n ? { disabled: true, count: n, ask: "samples", note: n + " " + plural(n, "asset has", "assets have") + " nothing to look at or hear yet. Ask the agent to make " + plural(n, "a sample", "samples") + "." } : null;
    }
    return null;
  }

  /* The text of a script or planning document travels inline (the host copies only image, audio and video files): {text} when it is there,
     else {error} with the agent's note (the file is missing, or it was too long for the state). */
  function bodyOf(x) {
    if (x && typeof x.body === "string") return { text: x.body };
    return { error: (x && x.body_note) || "This document has no text yet. Ask the agent to add it again." };
  }

  const slugOf = (label) => String(label || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "").slice(0, 60).replace(/-+$/, "");
  /* File name for a saved draft: the host's own file name when it carries an extension, else the label as a slug plus .mp4. */
  function downloadName(r, label) {
    const name = String((r && r.name) || "").trim();
    if (/^.+\.[A-Za-z][A-Za-z0-9]{0,7}$/.test(name)) return name;
    return (slugOf(label) || "promo") + ".mp4";
  }
  const textFileName = (label) => (slugOf(label) || "document") + ".md";

  /* Where a draft or final can be uploaded and where it already is, one row per destination the host's twg can reach (`doc.share.destinations`).
     `edited` = the file changed after the upload. A draft is the same item when edited: Artifacts refreshes it behind the same link, Loom cannot replace so it adds a copy.
     A final is a numbered revision and is never overwritten, so an edited one only says to register the new file. */
  function shareRows(doc, it) {
    if (!it || fileBad(it)) return [];
    const isFinal = String(it.id).charAt(0) === "f";
    return arr((doc.share || {}).destinations).map((d) => {
      const rec = (it.shared || {})[d.id] || null;
      const row = { dest: d.id, label: d.label, url: rec && rec.url ? rec.url : null, state: "new", action: "Upload to " + d.label, note: d.note || "" };
      if (!rec) return row;
      if (!rec.edited) return { ...row, state: "on", action: "", note: "" };
      if (isFinal) return { ...row, state: "locked", action: "", note: "Changed since it was uploaded. Register the new file as a new final and it goes up as the next version." };
      return { ...row, state: "edited", action: (d.in_place ? "Update on " : "Upload again to ") + d.label, note: d.in_place ? "Same link, new file." : d.label + " keeps the earlier copy." };
    });
  }


  /* ---------- reading long documents: a small markdown reader, pagination, search ---------- */
  const wordsOf = (t) => (String(t || "").match(/\S*[\p{L}\p{N}_]\S*/gu) || []).length;
  const PAGE_LINE = /^\s*<!--\s*page(?:\s*:\s*(.*?))?\s*-->\s*$/;
  const LIST_LINE = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
  const isTableSep = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l) && l.includes("-");
  const cells = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

  /* Lines -> blocks: h{level,text} p{text} list{items:[{text,depth,ordered,check}]} quote{text} hr code{text} table{head,rows,align} page{title}. Nothing here touches HTML. */
  function parseBlocks(text) {
    const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    let i = 0;
    const special = (l) => /^\s*```/.test(l) || /^\s*#{1,4}\s/.test(l) || PAGE_LINE.test(l) || /^\s*([-*_])\1\1+\s*$/.test(l) || LIST_LINE.test(l) || /^\s*>/.test(l) || /^\s*\|/.test(l);
    while (i < lines.length) {
      const l = lines[i];
      if (!l.trim()) { i++; continue; }
      const pm = l.match(PAGE_LINE);
      if (pm) { out.push({ t: "page", title: (pm[1] || "").trim() }); i++; continue; }
      if (/^\s*```/.test(l)) {
        const body = []; i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i++]);
        i++;
        out.push({ t: "code", text: body.join("\n") });
        continue;
      }
      const hm = l.match(/^\s*(#{1,4})\s+(.*?)(?:\s+#+)?\s*$/);
      if (hm) { out.push({ t: "h", level: hm[1].length, text: hm[2] }); i++; continue; }
      if (/^\s*([-*_])\1\1+\s*$/.test(l)) { out.push({ t: "hr" }); i++; continue; }
      if (/^\s*\|/.test(l) && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        const head = cells(l); i += 2;
        const rows = [];
        while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(cells(lines[i++]));
        out.push({ t: "table", head, rows });
        continue;
      }
      if (/^\s*>/.test(l)) {
        const q = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
        out.push({ t: "quote", text: q.join("\n") });
        continue;
      }
      if (LIST_LINE.test(l)) {
        const items = [];
        while (i < lines.length) {
          const m = lines[i].match(LIST_LINE);
          if (m) {
            const cm = m[3].match(/^\[([ xX])\]\s+(.*)$/);
            items.push({ depth: Math.min(3, Math.floor(m[1].replace(/\t/g, "  ").length / 2)), ordered: /\d/.test(m[2]), text: cm ? cm[2] : m[3], check: cm ? cm[1] !== " " : null });
            i++;
          } else if (lines[i].trim() && /^\s{2,}\S/.test(lines[i]) && items.length) { items[items.length - 1].text += "\n" + lines[i].trim(); i++; }
          else break;
        }
        out.push({ t: "list", items });
        continue;
      }
      const para = [l];
      i++;
      while (i < lines.length && lines[i].trim() && !special(lines[i])) para.push(lines[i++]);
      out.push({ t: "p", text: para.join("\n") });
    }
    return out;
  }

  /* Inline markup -> tokens {t: text|b|i|code|link, text, url}. A link is only ever an https URL (the reader opens it through the host). */
  function inline(text) {
    const out = [];
    const re = /(\*\*[^*\n]+?\*\*|__[^_\n]+?__|`[^`\n]+`|\*[^*\s][^*\n]*?\*|\[[^\]\n]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s)<>\]]*[^\s)<>\].,;:!?])/g;
    let last = 0, m;
    const str = String(text == null ? "" : text);
    while ((m = re.exec(str))) {
      if (m.index > last) out.push({ t: "text", text: str.slice(last, m.index) });
      const x = m[0];
      if (x.startsWith("**") || x.startsWith("__")) out.push({ t: "b", text: x.slice(2, -2) });
      else if (x[0] === "`") out.push({ t: "code", text: x.slice(1, -1) });
      else if (x[0] === "[") { const mm = x.match(/^\[([^\]]+)\]\((.+)\)$/); out.push({ t: "link", text: mm[1], url: mm[2] }); }
      else if (x[0] === "*") out.push({ t: "i", text: x.slice(1, -1) });
      else out.push({ t: "link", text: x, url: x });
      last = m.index + x.length;
    }
    if (last < str.length) out.push({ t: "text", text: str.slice(last) });
    return out;
  }
  const plain = (text) => inline(text).map((x) => x.text).join("");

  function blockText(b) {
    if (b.t === "h" || b.t === "p" || b.t === "quote" || b.t === "code") return plain(b.text);
    if (b.t === "list") return b.items.map((x) => plain(x.text)).join("\n");
    if (b.t === "table") return [b.head, ...b.rows].map((r) => r.map(plain).join(" ")).join("\n");
    return "";
  }
  const blockWords = (b) => wordsOf(blockText(b));

  /* Pages: explicit `<!-- page -->` markers win; otherwise about `target` words per page, starting a new page at a heading once the page is a third full,
     never inside a block (a table or a code block stays whole). Every page keeps its blocks, its title (first heading) and its words. */
  function paginate(text, opts) {
    const target = (opts && opts.target) || 650;
    const blocks = parseBlocks(text);
    const pages = [];
    let cur = null;
    const open = (title) => { cur = { title: title || "", blocks: [], words: 0, explicit: !!title }; pages.push(cur); };
    const marked = blocks.some((b) => b.t === "page");
    for (const b of blocks) {
      if (b.t === "page") { if (cur && !cur.blocks.length) cur.title = b.title || cur.title; else open(b.title); continue; }
      const w = blockWords(b);
      if (!cur) open();
      else if (!marked && cur.words > 0 && ((b.t === "h" && b.level <= 2 && cur.words >= target * 0.35) || cur.words + w > target * 1.35)) open();
      cur.blocks.push(b);
      cur.words += w;
    }
    if (!pages.length) open();
    pages.forEach((p, i) => {
      const hd = p.blocks.find((b) => b.t === "h" && b.level <= 3);
      p.title = p.title || (hd ? plain(hd.text) : "Page " + (i + 1));
      p.text = p.blocks.map(blockText).join("\n");
      p.headings = p.blocks.filter((b) => b.t === "h" && b.level <= 3).map((b) => ({ level: b.level, title: plain(b.text) }));
    });
    return pages;
  }
  /* Contents list: every heading of level 1..3 with the page it is on (a page with no heading is listed under its own title). */
  function outline(pages) {
    const out = [];
    pages.forEach((p, i) => {
      if (p.headings.length) p.headings.forEach((h) => out.push({ level: h.level, title: h.title, page: i }));
      else out.push({ level: 1, title: p.title, page: i });
    });
    return out;
  }
  const escRe = (x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const qre = (q) => { q = String(q || "").trim(); return q.length < 2 ? null : new RegExp(escRe(q), "giu"); };
  /* [{page, n}] for the pages that contain `q` (case-insensitive, at least 2 characters). */
  function findPages(pages, q) {
    const re = qre(q);
    if (!re) return [];
    const out = [];
    pages.forEach((p, i) => { const n = (p.text.match(re) || []).length; if (n) out.push({ page: i, n }); });
    return out;
  }
  /* Split `text` around case-insensitive matches of `q`: [{text, hit}] (the reader wraps the hits in <mark>). */
  function markSplit(text, q) {
    const re = qre(q);
    text = String(text);
    if (!re) return [{ text, hit: false }];
    const out = [];
    let at = 0, m;
    while ((m = re.exec(text))) { if (m.index > at) out.push({ text: text.slice(at, m.index), hit: false }); out.push({ text: m[0], hit: true }); at = m.index + m[0].length; if (!m[0].length) re.lastIndex++; }
    if (at < text.length) out.push({ text: text.slice(at), hit: false });
    return out.length ? out : [{ text, hit: false }];
  }
  const readMinutes = (words) => Math.max(1, Math.round((words || 0) / 200));

  /* ---------- the storyboard on a time line ---------- */
  /* Every frame of a story in time order: each scene's START at its start, its mid frames at their own times, its END at its end. Ties keep scene order,
     so the END of one scene sits before the START of the next. */
  function frameTimeline(board) {
    const out = [];
    arr((board || {}).scenes).forEach((s) => {
      if (s.start) out.push({ t: s.start_s, kind: "start", scene: s, f: s.start });
      arr(s.frames).forEach((f, i) => out.push({ t: typeof f.t === "number" ? f.t : s.start_s, kind: "mid", scene: s, f, i, auto: !!f.auto }));
      if (s.end) out.push({ t: s.end_s, kind: "end", scene: s, f: s.end });
    });
    return out.map((x, n) => ({ x, n })).sort((a, b) => a.x.t - b.x.t || a.n - b.n).map((o) => o.x);
  }
  const DENSITY_CHOICES = [{ every: 0, label: "Start and end" }, { every: 10, label: "Every 10 s" }, { every: 5, label: "Every 5 s" }, { every: 2, label: "Every 2 s" }];
  const clockT = (s) => { const t = Math.round(Math.max(0, s || 0) * 10), m = Math.floor(t / 600), rem = t - m * 600, sec = Math.floor(rem / 10), fr = rem % 10; return m + ":" + String(sec).padStart(2, "0") + (fr ? "." + fr : ""); };

  /* The settings pane's "where are videos saved" field. promo/home.py (parse_output) has the final say; this only keeps a bad value from being sent
     and shows where the next video would go. */
  const withSlug = (t) => { t = String(t || "").trim().replace(/\/+$/, ""); return t.endsWith("/{slug}") ? t : t + "/{slug}"; };
  function outputProblem(text) {
    const t = String(text || "").trim();
    if (!t) return "Type the folder to save into.";
    if (/["`$\\\u0000-\u001f]/.test(t)) return "The folder can't contain quotes, backticks, $ or backslashes.";
    const bad = (t.match(/\{[^}]*\}/g) || []).find((x) => x !== "{project}" && x !== "{slug}");
    if (bad) return "Only {project} and {slug} can be used, not " + bad + ".";
    if (t.includes("{slug}") && !(t.endsWith("/{slug}") && t.split("{slug}").length === 2)) return "{slug} has to be the last folder.";
    return "";
  }
  /* `out` is the snapshot's settings.output (project, repo, home). A relative folder is relative to the repo, like the CLI. */
  function previewOutput(text, out) {
    const t = withSlug(text).replace(/\{project\}/g, out.project).replace(/\{slug\}/g, "<slug>");
    if (t.startsWith("~/")) return out.home + t.slice(1);
    return t.startsWith("/") ? t : out.repo + "/" + t.replace(/^\.\//, "");
  }
  const outputDirty = (out, sel, text) => sel !== out.mode || (sel === "custom" && withSlug(text) !== out.template);

  /* The live panel for a preview run (snapshot `job`, promo/flowjob.py). `now` is ms since the epoch, passed in so the clock is the caller's.
     Tiles fill left to right: made (or failed) items, then the ones being made now, then a row of the queue; a long run keeps its newest pictures. */
  const JOB_NOUN = { frames: ["image", "images"], samples: ["sample", "samples"], build: ["step", "steps"] };
  const JOB_TILES = 24, JOB_QUEUE_TILES = 6, JOB_DONE_SHOWN_MIN = 10;
  /* A run writes a heartbeat every minute (promo/flowjob.py HEARTBEAT_S): three missed beats and it is no longer shown as alive. A rendered
     shot can take many minutes, so "slow" (a gentle note, spinner kept) waits longer for builds than for one generated picture. */
  const JOB_ALIVE_S = 180, JOB_SLOW_S = { build: 900 }, JOB_SLOW_DEFAULT_S = 240;
  function jobView(job, now) {
    if (!job || !job.total) return null;
    const t = (iso) => Date.parse(iso);
    const items = arr(job.items), active = arr(job.active);
    const [one, many] = JOB_NOUN[job.kind] || ["item", "items"];
    const finished = job.done + job.failed;
    if (job.state === "done" && now - t(job.finished || job.updated) > JOB_DONE_SHOWN_MIN * 60000) return null;
    const end = job.state === "running" ? now : t(job.finished || job.updated);
    const elapsed = Math.max(0, (end - t(job.started)) / 1000);
    const lastAt = items.length ? t(items[items.length - 1].at) : t(job.started);
    const quiet = Math.max(0, (now - lastAt) / 1000);
    const queued = Math.max(0, job.total - finished - active.length);
    const alive = job.state === "running" && (now - t(job.updated)) / 1000 < JOB_ALIVE_S;
    const skipped = items.filter((x) => x.skipped).length;
    const queuedShown = Math.min(queued, JOB_QUEUE_TILES);
    const room = Math.max(0, JOB_TILES - active.length - queuedShown);
    const shown = items.slice(-room);
    const tiles = [...shown.map((x) => ({ type: x.ok ? "item" : "failed", item: x })), ...active.map((x) => ({ type: "active", item: x })),
      ...Array.from({ length: job.state === "running" ? queuedShown : 0 }, (_, i) => ({ type: "queued", n: i }))];
    const eta = job.state === "running" && finished >= 2 ? Math.round((elapsed / finished) * (job.total - finished)) : null;
    const n = (k) => k + " " + (k === 1 ? one : many);
    const title = job.state === "running" ? job.label
      : job.state === "done" ? (job.kind === "build" ? "Finished " + n(job.done) + (skipped ? ", " + skipped + " unchanged" : "") : "Made " + n(job.done)) + (job.failed ? ", " + job.failed + " failed" : "")
      : "Stopped after " + job.done + " of " + n(job.total);
    return { state: job.state, title, done: job.done, failed: job.failed, total: job.total, pct: Math.min(1, finished / job.total), one, many, elapsed, quiet, eta,
      alive, stale: job.state === "running" && !alive, staleFor: Math.max(0, (now - t(job.updated)) / 1000), waiting: alive ? job.waiting || null : null,
      slow: alive && !job.waiting && quiet >= (JOB_SLOW_S[job.kind] || JOB_SLOW_DEFAULT_S), resume: job.resume || null, tiles, earlier: Math.max(0, items.length - shown.length) + Math.max(0, finished - items.length),
      moreQueued: job.state === "running" ? queued - queuedShown : 0, active };
  }
  /* 74 -> "1:14", 3725 -> "1:02:05": a running clock. */
  const clockS = (s) => { s = Math.floor(Math.max(0, s)); const hh = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60, ss = String(s % 60).padStart(2, "0"); return hh ? hh + ":" + String(mm).padStart(2, "0") + ":" + ss : mm + ":" + ss; };
  const aboutS = (s) => (s < 50 ? "under a minute" : s < 90 ? "about a minute" : "about " + Math.round(s / 60) + " min");

  const api = { jobView, clockS, aboutS, arr, mref, fileBad, missingFile, missingAll, hasPreview, noFrame, sceneStatus, model, finalState, seenRule, seenKey, missingRule, previewRule, bodyOf, downloadName, textFileName, wordsOf, parseBlocks, inline, plain, paginate, outline, findPages, markSplit, readMinutes, frameTimeline, DENSITY_CHOICES, clockT, shareRows, outputProblem, previewOutput, outputDirty };
  root.PF = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
