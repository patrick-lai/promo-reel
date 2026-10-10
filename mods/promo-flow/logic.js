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

  /* Approve at the assets gate is not backed while a ready asset has no file. */
  function missingRule(doc, gateName) {
    if (gateName !== "assets-approved") return null;
    const n = missingAll(doc);
    return n ? { disabled: true, count: n, note: n + " " + (n === 1 ? "file is" : "files are") + " missing. Add changes so the agent attaches " + (n === 1 ? "it" : "them") + "." } : null;
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

  /* Notes on a draft's timeline. The person adds, rewords, moves and removes notes locally, as often as they like; one Send hands every change to
     the agent at once (`pins` action). A note is keyed by its pin id (n3) once the flow has it, by a local key (l1) before. `ops` are the unsent
     changes, `sent` the ones the agent has not published back yet. */
  const noteText = (t) => String(t == null ? "" : t).trim().replace(/\s+/g, " ");
  const noteAt = (t) => Math.max(0, Math.round((+t || 0) * 100) / 100);
  function noteChange(ops, pins, ch) {
    const list = arr(ops).slice(), i = list.findIndex((o) => o.key === ch.key), was = i < 0 ? null : list[i];
    if (i >= 0) list.splice(i, 1);
    const pin = arr(pins).find((p) => p.id === ch.key);
    let next = null;
    if (ch.op === "remove") next = pin ? { key: ch.key, op: "remove" } : null;
    else {
      next = was && was.op !== "remove" ? { ...was } : pin ? { key: ch.key, op: "edit" } : { key: ch.key, op: "add", at: 0, text: "" };
      if (ch.at != null) next.at = noteAt(ch.at);
      if (ch.text != null) next.text = noteText(ch.text);
      if (pin && next.at === pin.at_s) delete next.at;
      if (pin && next.text === pin.text) delete next.text;
      if ((next.op === "edit" && next.at == null && next.text == null) || (next.op === "add" && !next.text)) next = null;
    }
    if (next) list.splice(i < 0 ? list.length : i, 0, next);
    return list;
  }
  function notesView(pins, ops, sent) {
    const mine = new Map(arr(ops).map((o) => [o.key, o])), gone = new Map(arr(sent).map((o) => [o.key, o]));
    const out = arr(pins).map((p) => {
      const o = mine.get(p.id) || gone.get(p.id);
      return { key: p.id, id: p.id, at: o && o.at != null ? o.at : p.at_s, text: o && o.text != null ? o.text : p.text, scene: p.scene || null, by: p.by || "",
        state: !o ? "saved" : o.op === "remove" ? "removed" : "edited", sent: !!o && !mine.has(p.id), was: o ? { at: p.at_s, text: p.text } : null };
    });
    for (const [o, isSent] of [...arr(sent).map((o) => [o, true]), ...arr(ops).map((o) => [o, false])])
      if (o.op === "add") out.push({ key: o.key, id: null, at: o.at, text: o.text, scene: null, by: "", state: "new", sent: isSent, was: null });
    return out.sort((a, b) => a.at - b.at || String(a.key).localeCompare(String(b.key)));
  }
  /* What the agent has not published back yet: an added note shows up as a pin with its words near its time, an edit as the pin's new values, a removal
     as the pin gone. */
  function notesUnsettled(sent, pins) {
    const ps = arr(pins);
    return arr(sent).filter((o) => {
      if (o.op === "add") return !ps.some((p) => noteText(p.text) === o.text && Math.abs(p.at_s - o.at) <= 0.06);
      const p = ps.find((x) => x.id === o.key);
      if (o.op === "remove" || !p) return !!p;
      return (o.at != null && Math.abs(p.at_s - o.at) > 0.06) || (o.text != null && noteText(p.text) !== o.text);
    });
  }
  function notesMessage(ops, pins) {
    const q = (t) => "\u201c" + t + "\u201d";
    return arr(ops).map((o, i) => {
      const p = arr(pins).find((x) => x.id === o.key);
      const line = o.op === "add" ? "new note at " + clockT(o.at) + " (--at " + o.at + "): " + q(o.text)
        : o.op === "remove" ? "remove " + o.key + " (" + q(p ? p.text : "") + ")"
        : "change " + o.key + (o.at != null ? ": move to " + clockT(o.at) + " (--at " + o.at + ")" : "") + (o.text != null ? (o.at != null ? ", " : ": ") + "new words " + q(o.text) : "");
      return "(" + (i + 1) + ") " + line;
    }).join(" ");
  }

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
  const JOB_TILES = 24, JOB_QUEUE_TILES = 0, JOB_DONE_SHOWN_MIN = 10;
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
    const eta = job.state === "running" && finished >= 3 ? Math.round((elapsed / finished) * (job.total - finished)) : null;
    const n = (k) => k + " " + (k === 1 ? one : many);
    const title = job.state === "running" ? job.label
      : job.state === "done" ? (job.kind === "build" ? "Finished " + n(job.done) + (skipped ? ", " + skipped + " unchanged" : "") : "Made " + n(job.done)) + (job.failed ? ", " + job.failed + " failed" : "")
      : "Stopped after " + job.done + " of " + n(job.total);
    return { state: job.state, title, done: job.done, failed: job.failed, total: job.total, pct: Math.min(1, job.done / job.total), failPct: Math.min(1, job.failed / job.total), one, many, elapsed, quiet, eta,
      alive, stale: job.state === "running" && !alive, staleFor: Math.max(0, (now - t(job.updated)) / 1000), waiting: alive ? job.waiting || null : null,
      slow: alive && !job.waiting && quiet >= (JOB_SLOW_S[job.kind] || JOB_SLOW_DEFAULT_S), resume: job.resume || null, tiles, earlier: Math.max(0, items.length - shown.length) + Math.max(0, finished - items.length),
      moreQueued: job.state === "running" ? queued - queuedShown : 0, active };
  }
  /* 74 -> "1:14", 3725 -> "1:02:05": a running clock. */
  const clockS = (s) => { s = Math.floor(Math.max(0, s)); const hh = Math.floor(s / 3600), mm = Math.floor(s / 60) % 60, ss = String(s % 60).padStart(2, "0"); return hh ? hh + ":" + String(mm).padStart(2, "0") + ":" + ss : mm + ":" + ss; };
  const aboutS = (s) => (s < 50 ? "under a minute" : s < 90 ? "about a minute" : "about " + Math.round(s / 60) + " min");

  /* What waits on the person outside the step's own gate: blind picks not answered yet, the agent's choices they have not overturned, and an
     autopilot run while it is on (or ended, until the review moves on). A pick needs both sides to load before it can be answered. */
  const AP_LIVE = { running: 1, paused: 1 };
  function forYou(doc) {
    const pairs = arr(doc.pairs).filter((p) => !p.answered).map((p) => ({ ...p, ready: usable(p.left) && usable(p.right) }));
    const assumptions = arr(doc.assumptions).filter((a) => !a.overturned);
    const ap = doc.autopilot || null;
    const autopilot = ap && (AP_LIVE[ap.state] || doc.stage === "drafts" || doc.stage === "review") ? { ...ap, live: !!AP_LIVE[ap.state], pct: Math.min(1, Math.max(0, (ap.used_min || 0) / Math.max(1, ap.minutes || 1))) } : null;
    return { pairs, assumptions, autopilot };
  }
  /* The autopilot offer: on the latest draft, while nothing runs, once that draft has checks it can be held to. */
  function canAutopilot(doc, it) {
    const ds = arr(doc.drafts);
    if (!it || it !== ds[ds.length - 1] || !(doc.stage === "drafts" || doc.stage === "review")) return false;
    if (doc.autopilot && AP_LIVE[doc.autopilot.state]) return false;
    return !!(it.board && it.board.total);
  }

  /* The comments the person left on scenes: `open` still wait for the agent, `total` also counts the answered ones. */
  function commentCount(doc) {
    const notes = arr(doc && doc.boards).flatMap((b) => arr(b.scenes)).flatMap((s) => arr(s.notes));
    return { open: notes.filter((n) => !n.answer).length, total: notes.length };
  }

  /* ---- dynamic widgets: panels the agent builds (blocks the Stage draws itself, or HTML run in a sandboxed frame) ---- */
  const WIDGET_TAB = "widgets";
  const WIDGET_PX = { s: 180, m: 300, l: 440, xl: 620 };
  const WIDGET_AUTO = { min: 120, max: 700 };
  /* The widgets that belong to a tab: the workbench tab shows the ones placed there, every other tab the ones pinned to its top. Order is the agent's. */
  function widgetsFor(doc, place) {
    return arr(doc && doc.widgets).filter((w) => w.place === place);
  }
  const widgetHeight = (w, reported, big) => {
    if (big) return WIDGET_PX.xl;
    if (w.height !== "auto") return WIDGET_PX[w.height] || WIDGET_PX.m;
    return Math.min(WIDGET_AUTO.max, Math.max(WIDGET_AUTO.min, Math.ceil(reported || WIDGET_PX.s)));
  };
  /* A widget cannot reach the network or the Stage: the frame has an opaque origin and this policy only allows what it ships with and what it is handed. */
  const WIDGET_CSP = "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob:; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; worker-src blob:; connect-src blob: data:";
  const THEME_VARS = { ink: "--pf-ink", dim: "--pf-dim", well: "--pf-well", raised: "--pf-raised", line: "--pf-line", accent: "--pf-accent" };
  const cssValue = (v) => String(v == null ? "" : v).replace(/[^\w #%.,()/-]/g, "");
  function themeCss(theme) {
    const t = theme || {};
    return ":root{color-scheme:" + (t.dark ? "dark" : "light") + ";" + Object.keys(THEME_VARS).map((k) => THEME_VARS[k] + ":" + cssValue(t[k])).join(";") + "}";
  }
  /* What the frame's script offers the widget (promo.ready, promo.data, promo.file, promo.url, promo.theme, promo.onTheme, promo.tell) and how it answers the Stage. */
  const WIDGET_RUNTIME = "(function(){var q={},fns=[],up=false;var P=window.promo={data:{},names:[],files:{},theme:{},onTheme:null," +
    "ready:function(f){up?f(P):fns.push(f)}," +
    "file:function(n){return new Promise(function(ok,no){if(P.files[n])return ok(P.files[n]);(q[n]=q[n]||[]).push([ok,no])})}," +
    "url:function(n){return P.file(n).then(function(b){return URL.createObjectURL(b)})}," +
    "tell:function(t){parent.postMessage({pf:'tell',text:String(t).slice(0,1500)},'*')}};" +
    "function css(t){var r=document.documentElement.style;P.theme=t||{};r.colorScheme=P.theme.dark?'dark':'light';" +
    "[['ink','--pf-ink'],['dim','--pf-dim'],['well','--pf-well'],['raised','--pf-raised'],['line','--pf-line'],['accent','--pf-accent']].forEach(function(p){if(P.theme[p[0]])r.setProperty(p[1],P.theme[p[0]])})}" +
    "addEventListener('message',function(e){var m=e.data;if(e.source!==parent||!m||typeof m!=='object')return;" +
    "if(m.pf==='init'){P.data=m.data||{};P.names=m.names||[];css(m.theme);up=true;fns.splice(0).forEach(function(f){f(P)})}" +
    "else if(m.pf==='file'){var w=q[m.name]||[];delete q[m.name];if(m.blob){P.files[m.name]=m.blob;w.forEach(function(x){x[0](m.blob)})}else w.forEach(function(x){x[1](new Error(m.error||'file not available'))})}" +
    "else if(m.pf==='theme'){css(m.theme);if(P.onTheme)P.onTheme(P.theme)}});" +
    "function bad(t){parent.postMessage({pf:'error',text:String(t).slice(0,300)},'*')}" +
    "addEventListener('error',function(e){bad(e.message||'script error')});addEventListener('unhandledrejection',function(e){bad(e.reason&&e.reason.message||e.reason)});" +
    "function size(){parent.postMessage({pf:'size',h:Math.ceil(document.body.getBoundingClientRect().height)},'*')}" +
    "addEventListener('load',function(){size();if(window.ResizeObserver)new ResizeObserver(size).observe(document.documentElement)});})();";
  /* The whole document for the sandboxed frame: policy first (a policy in the widget's own HTML can only tighten it), then theme, then runtime, then the agent's HTML. */
  function widgetDoc(html, theme) {
    return '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="' + WIDGET_CSP + '"><meta name="viewport" content="width=device-width,initial-scale=1">' +
      "<style>" + themeCss(theme) + "html,body{margin:0;background:transparent;color:var(--pf-ink);font:14px/1.45 ui-sans-serif,-apple-system,system-ui,sans-serif}*{box-sizing:border-box}</style>" +
      "<script>" + WIDGET_RUNTIME + "</script></head><body>" + String(html || "") + "</body></html>";
  }
  /* A frame message is the widget's only way to speak: accept the shapes the runtime sends and nothing else. */
  function widgetMessage(d) {
    if (!d || typeof d !== "object") return null;
    if (d.pf === "size" && Number.isFinite(d.h)) return { kind: "size", h: d.h };
    if (d.pf === "error" && typeof d.text === "string") return { kind: "error", text: d.text.slice(0, 300) };
    if (d.pf === "tell" && typeof d.text === "string" && d.text.trim()) return { kind: "tell", text: d.text.trim().slice(0, 1500) };
    return null;
  }

  /* How long a repaint of the open tab waits, in ms (0 = now). The person's own clicks always repaint at once; an update from the agent never
     rebuilds a clip being watched, and while the agent works it repaints at most once per `gap` so the page does not jump around. */
  const SETTLE_GAP_MS = 12000, PREVIEW_POLL_MS = 1500;
  function settleWait(o) {
    if (o.userChanged) return 0;
    if (o.previewing) return PREVIEW_POLL_MS;
    if (o.working) return Math.max(0, SETTLE_GAP_MS - Math.max(0, o.sinceBuild || 0));
    return 0;
  }

  /* Files the person adds in the Stage. Same limits as a chat attachment (the host refuses anything else): 10 files, 100 MB a video, 20 MB the rest. */
  const FILES_MAX = 10, FILE_MB = 20, VIDEO_MB = 100, FILES_TAB = "files";
  const isVideoFile = (f) => /^video\//.test(f.type || "") || /\.(mov|mp4|m4v|webm)$/i.test(f.name || "");
  function fileProblem(f) {
    if (!f || !f.size) return "The file is empty";
    const mb = isVideoFile(f) ? VIDEO_MB : FILE_MB;
    return f.size > mb * 1048576 ? "Over the " + mb + " MB limit" : null;
  }
  /* Add dropped / picked files to the staged ones: no duplicates (same name, size and date), at most FILES_MAX. Returns {files, skipped}. */
  function addFiles(have, more) {
    const key = (f) => f.name + "|" + f.size + "|" + (f.lastModified || 0);
    const out = have.slice(), seen = new Set(out.map(key));
    let skipped = 0;
    for (const f of more) {
      if (seen.has(key(f))) continue;
      if (out.length >= FILES_MAX) { skipped++; continue; }
      seen.add(key(f)); out.push(f);
    }
    return { files: out, skipped };
  }
  /* The message the agent gets with the files. The host attaches them, so the agent finds each under .commission/attachments/<name>. */
  function filesMessage(files, note, open) {
    const names = files.map((f) => f.name).join(", ");
    const rows = arr(open).filter((a) => a && a.id).map((a) => a.id + (a.kind ? " (" + a.kind + ")" : ""));
    const t = (note || "").trim().replace(/\s+/g, " ");
    return "[mod:promo-flow] The person added " + files.length + (files.length === 1 ? " file" : " files") + " from the Stage (attached, they are real footage or references they made): " + names + "."
      + (t ? " Their note: " + t + "." : "")
      + (rows.length ? " Asset rows still waiting for footage: " + rows.join(", ") + "." : "")
      + " Copy each into the project's footage folder, register real footage with promo footage add (and promo flow asset add --force --source real --path FILE --how \"...\" for the matching row), look at it, then publish the new state. Do not approve anything.";
  }

  /* Space plays or pauses the video the person is watching: the lightbox clip, else one that is playing, else the last one they played. Before anything has played, space keeps scrolling the page. */
  function spaceVideo(vids, lightbox, last) {
    const live = arr(vids).filter((v) => v && v.isConnected !== false);
    if (lightbox) return lightbox;
    return live.find((v) => !v.paused && !v.ended) || (last && last.isConnected !== false ? last : null);
  }
  /* Space belongs to the thing that has focus when it types or presses (and to a video's own controls); a bare page or the open clip's Close button hands it to the video. */
  function spaceFree(tag, editable, lightboxOpen) {
    const t = String(tag || "").toUpperCase();
    if (editable || t === "INPUT" || t === "TEXTAREA" || t === "SELECT" || t === "VIDEO" || t === "AUDIO" || t === "A" || t === "SUMMARY") return false;
    if (t === "BUTTON") return !!lightboxOpen;
    return true;
  }

  /* ---- the editor: the same edit language and the same edits as promo/editor.py, so the preview is what the render makes (tests/edit-cases.json runs both) ---- */
  const EDIT_OPS = ["swap", "trim", "move", "split", "delete", "caption", "music", "bus", "vo", "sfx", "grade", "fade", "speed", "fx", "gain", "import"];
  const GRADE_KEYS = ["brightness", "contrast", "saturation", "gamma", "temperature", "vignette"];
  const GRADE_RANGE = { brightness: [-0.5, 0.5], contrast: [0.5, 2], saturation: [0, 2.5], gamma: [0.5, 2], temperature: [2500, 10000], vignette: [0, 1] };
  const FX_PRESETS = ["radio", "tape", "vintage", "telephone", "vinyl", "crackle", "none"];
  const BUSES = ["music", "sfx", "vo", "amb"];
  const IMPORT_KINDS = ["music", "sfx", "voice", "video"];
  class EditError extends Error {}
  const eerr = (n, m) => { throw new EditError("line " + n + ": " + m); };
  const n6 = (x) => Math.round(+x * 1e6) / 1e6;
  /* Tokens like Python's shlex (posix, whitespace split): quotes group words, a backslash escapes inside double quotes, `;` outside quotes ends an op. */
  function editTokens(line, n) {
    const out = [[]];
    let cur = null, q = null;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (q) {
        if (c === q) q = null;
        else if (c === "\\" && q === '"' && (line[i + 1] === '"' || line[i + 1] === "\\")) cur += line[++i];
        else cur += c;
      } else if (c === '"' || c === "'") { q = c; cur = cur == null ? "" : cur; }
      else if (c === "\\" && i + 1 < line.length) { cur = (cur == null ? "" : cur) + line[++i]; }
      else if (/\s/.test(c)) { if (cur != null) { out[out.length - 1].push(cur); cur = null; } }
      else if (c === ";") { if (cur != null) { out[out.length - 1].push(cur); cur = null; } out.push([]); }
      else cur = (cur == null ? "" : cur) + c;
    }
    if (q) throw new EditError("line " + n + ": No closing quotation in '" + line.trim() + "' (a quote is not closed)");
    if (cur != null) out[out.length - 1].push(cur);
    return out.filter((t) => t.length);
  }
  const numOf = (v, what, n) => { const x = Number(v); if (v == null || String(v).trim() === "" || !isFinite(x)) eerr(n, what + " must be a number, not '" + v + "'"); return x; };
  function kvOf(toks, n, allowed, flags) {
    const kv = {}, fl = [];
    for (const t of toks) {
      const i = t.indexOf("=");
      if (i >= 0) { const k = t.slice(0, i); if (!allowed.includes(k)) eerr(n, "unknown setting " + k + "= (use " + allowed.map((x) => x + "=").join(", ") + ")"); kv[k] = t.slice(i + 1); }
      else if ((flags || []).includes(t)) fl.push(t);
      else eerr(n, "did not understand '" + t + "'");
    }
    return { kv, fl };
  }
  function editParse(text) {
    const ops = [];
    String(text || "").split(/\r?\n/).forEach((raw, k) => {
      const n = k + 1;
      if (!raw.trim() || raw.trim().startsWith("#")) return;
      for (const t of editTokens(raw, n)) {
        const op = t[0].toLowerCase(), a = t.slice(1);
        const need = (i, what) => (a.length > i ? a[i] : eerr(n, "`" + op + "` needs " + what));
        let o;
        if (op === "swap") {
          const sid = need(0, "a shot id"), src = need(1, "a footage id"), { kv } = kvOf(a.slice(2), n, ["t_in"]);
          o = { op, shot: sid, source: src };
          if ("t_in" in kv) o.t_in = numOf(kv.t_in, "t_in", n);
        } else if (op === "trim") {
          const sid = need(0, "a shot id"), { kv } = kvOf(a.slice(1), n, ["end", "start"]), ks = Object.keys(kv);
          if (ks.length !== 1) eerr(n, "trim takes one of end=BEAT or start=BEAT");
          o = { op, shot: sid, [ks[0]]: numOf(kv[ks[0]], ks[0], n) };
        } else if (op === "move") {
          const sid = need(0, "a shot id"), { kv } = kvOf(a.slice(1), n, ["before", "after"]);
          if (Object.keys(kv).length !== 1) eerr(n, "move takes one of before=SHOT or after=SHOT");
          o = { op, shot: sid, ...kv };
        } else if (op === "split") {
          const sid = need(0, "a shot id"), { kv } = kvOf(a.slice(1), n, ["at"]);
          if (!("at" in kv)) eerr(n, "split needs at=BEATS (how far into the shot)");
          o = { op, shot: sid, at: numOf(kv.at, "at", n) };
        } else if (op === "delete") {
          o = { op, shot: need(0, "a shot id") };
          if (a.length > 1) eerr(n, "delete takes only a shot id");
        } else if (op === "caption") {
          const sid = need(0, "a shot id");
          if (a.length !== 2) eerr(n, 'caption takes a shot id and the words in quotes, e.g. caption 07 "Tell it what to ship."');
          o = { op, shot: sid, text: a[1].split(/\s+/).filter(Boolean).join(" ") };
        } else if (op === "music") {
          o = { op, asset: need(0, "an asset id") };
          const { kv } = kvOf(a.slice(1), n, ["offset"]);
          if ("offset" in kv) o.offset = numOf(kv.offset, "offset", n);
        } else if (op === "bus") {
          const b = need(0, "a bus (music, sfx, vo or amb)");
          if (!BUSES.includes(b)) eerr(n, "bus is one of " + BUSES.join(", ") + ", not '" + b + "'");
          if (a.length !== 2) eerr(n, "bus takes a bus and a level in dB, e.g. bus music -3");
          o = { op, bus: b, db: numOf(a[1], "the level", n) };
        } else if (op === "vo") {
          const lid = need(0, "a voice line id"), { kv, fl } = kvOf(a.slice(1), n, ["at", "shot", "db", "take"], ["mute", "unmute"]);
          if (!Object.keys(kv).length && !fl.length) eerr(n, "vo " + lid + " needs at=, shot=, db=, take=, mute or unmute");
          if (fl.includes("mute") && fl.includes("unmute")) eerr(n, "mute or unmute, not both");
          o = { op, line: lid };
          for (const k of ["at", "db"]) if (k in kv) o[k] = numOf(kv[k], k, n);
          for (const k of ["shot", "take"]) if (k in kv) o[k] = kv[k];
          if (fl.length) o.mute = fl[0] === "mute";
        } else if (op === "sfx") {
          const sid = need(0, "a shot id"), act = need(1, "add, rm or set");
          if (act === "add") {
            const { kv } = kvOf(a.slice(3), n, ["at", "db"]);
            o = { op, shot: sid, act, sfx: need(2, "a sound name"), at: numOf(kv.at == null ? 0 : kv.at, "at", n) };
            if ("db" in kv) o.db = numOf(kv.db, "db", n);
          } else if (act === "rm" || act === "set") {
            const i = numOf(need(2, "the number of the sound (1 = the first)"), "the sound number", n);
            if (!Number.isInteger(i) || i < 1) eerr(n, "sounds are numbered from 1");
            const { kv } = kvOf(a.slice(3), n, act === "set" ? ["at", "db"] : []);
            if (act === "set" && !Object.keys(kv).length) eerr(n, "sfx set needs at= or db=");
            o = { op, shot: sid, act, i };
            for (const k of Object.keys(kv)) o[k] = numOf(kv[k], k, n);
          } else eerr(n, "sfx takes add, rm or set, not '" + act + "'");
        } else if (op === "grade") {
          const sid = need(0, "a shot id");
          if (a.length === 2 && a[1] === "off") o = { op, shot: sid, off: true };
          else {
            const { kv } = kvOf(a.slice(1), n, GRADE_KEYS);
            if (!Object.keys(kv).length) eerr(n, "grade needs one of " + GRADE_KEYS.map((k) => k + "=").join(", ") + ", or off");
            o = { op, shot: sid };
            for (const [k, v] of Object.entries(kv)) { const x = numOf(v, k, n), [lo, hi] = GRADE_RANGE[k]; if (x < lo || x > hi) eerr(n, k + " must be between " + lo + " and " + hi); o[k] = x; }
          }
        } else if (op === "fade") {
          const sid = need(0, "a shot id");
          if (a.length === 2 && a[1] === "off") o = { op, shot: sid, off: true };
          else {
            const { kv } = kvOf(a.slice(1), n, ["in", "out"]);
            if (!Object.keys(kv).length) eerr(n, "fade needs in=SECONDS and/or out=SECONDS, or off");
            o = { op, shot: sid };
            for (const [k, v] of Object.entries(kv)) o[k] = numOf(v, k, n);
            if (Object.keys(kv).some((k) => o[k] < 0)) eerr(n, "a fade cannot be negative");
          }
        } else if (op === "speed") {
          const sid = need(0, "a shot id");
          if (a.length !== 2) eerr(n, "speed takes a shot id and a factor, e.g. speed 07 1.5");
          const x = numOf(a[1], "the speed", n);
          if (x < 0.1 || x > 8) eerr(n, "speed must be between 0.1 and 8");
          o = { op, shot: sid, speed: x };
        } else if (op === "fx") {
          const tgt = need(0, "what it applies to: music, vo, vo:LINE or mix");
          if (!(["music", "vo", "mix"].includes(tgt) || tgt.startsWith("vo:"))) eerr(n, "fx applies to music, vo, vo:LINE or mix, not '" + tgt + "'");
          const pre = need(1, "a preset (" + FX_PRESETS.join(", ") + ") or off");
          if (pre !== "off" && !FX_PRESETS.includes(pre)) eerr(n, "fx preset is one of " + FX_PRESETS.join(", ") + " (or off), not '" + pre + "'");
          const { kv } = kvOf(a.slice(2), n, ["amount"]);
          o = { op, target: tgt, preset: pre };
          if ("amount" in kv) { o.amount = numOf(kv.amount, "amount", n); if (o.amount < 0 || o.amount > 1) eerr(n, "amount is between 0 and 1"); }
        } else if (op === "gain") {
          if (need(0, "music") !== "music") eerr(n, "gain works on the music (gain music from=BEAT to=BEAT db=DB)");
          if (a.length === 2 && a[1] === "clear") o = { op, clear: true };
          else {
            const { kv } = kvOf(a.slice(1), n, ["from", "to", "db", "ramp"]);
            if (!["from", "to", "db"].every((k) => k in kv)) eerr(n, "gain music needs from=BEAT to=BEAT db=DB");
            o = { op };
            for (const k of ["from", "to", "db", "ramp"]) if (k in kv) o[k] = numOf(kv[k], k, n);
            if (o.to <= o.from) eerr(n, "gain to= must be after from=");
          }
        } else if (op === "import") {
          const path = need(0, "a file path"), { kv } = kvOf(a.slice(1), n, ["kind", "licence", "source", "id"]);
          if (!IMPORT_KINDS.includes(kv.kind)) eerr(n, "import needs kind= one of " + IMPORT_KINDS.join(", "));
          for (const k of ["licence", "source"]) if (!String(kv[k] || "").trim()) eerr(n, "import needs " + k + '="..." (rule 4: every file carries a licence and where it came from; "My own recording" is fine for the person\'s own)');
          o = { op, path, ...kv };
        } else eerr(n, "unknown edit '" + t[0] + "' (one of " + EDIT_OPS.join(", ") + ")");
        o._n = n;
        ops.push(o);
      }
    });
    if (!ops.length) throw new EditError("no edits: write one edit per line, e.g. `swap 07 rec-w-ask` or `music music-eternal-hope`");
    return ops;
  }
  const qtok = (s) => (/^[\w.:/@+-]+$/.test(String(s)) ? String(s) : '"' + String(s).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"');
  const fnum = (x) => { const v = n6(x); return Number.isInteger(v) ? String(v) : String(v); };
  /* Ops back to edit text: one per line, the same text promo/editor.py's text_of writes. */
  function editText(ops) {
    return arr(ops).map((o) => {
      const x = o.op;
      if (x === "swap") return "swap " + o.shot + " " + o.source + ("t_in" in o ? " t_in=" + fnum(o.t_in) : "");
      if (x === "trim") return "trim " + o.shot + " " + ("end" in o ? "end=" + fnum(o.end) : "start=" + fnum(o.start));
      if (x === "move") return "move " + o.shot + " " + ("before" in o ? "before=" + o.before : "after=" + o.after);
      if (x === "split") return "split " + o.shot + " at=" + fnum(o.at);
      if (x === "delete") return "delete " + o.shot;
      if (x === "caption") return "caption " + o.shot + ' "' + String(o.text).replace(/\\/g, "\\\\").replace(/"/g, '\\"') + '"';
      if (x === "music") return "music " + o.asset + ("offset" in o ? " offset=" + fnum(o.offset) : "");
      if (x === "bus") return "bus " + o.bus + " " + fnum(o.db);
      if (x === "vo") return "vo " + o.line + " " + [...["at", "shot", "db", "take"].filter((k) => k in o).map((k) => k + "=" + (k === "at" || k === "db" ? fnum(o[k]) : qtok(o[k]))), ...("mute" in o ? [o.mute ? "mute" : "unmute"] : [])].join(" ");
      if (x === "sfx") return o.act === "add" ? "sfx " + o.shot + " add " + o.sfx + " at=" + fnum(o.at) + ("db" in o ? " db=" + fnum(o.db) : "") : "sfx " + o.shot + " " + o.act + " " + o.i + ["at", "db"].filter((k) => k in o).map((k) => " " + k + "=" + fnum(o[k])).join("");
      if (x === "grade") return "grade " + o.shot + " " + (o.off ? "off" : GRADE_KEYS.filter((k) => k in o).map((k) => k + "=" + fnum(o[k])).join(" "));
      if (x === "fade") return "fade " + o.shot + " " + (o.off ? "off" : ["in", "out"].filter((k) => k in o).map((k) => k + "=" + fnum(o[k])).join(" "));
      if (x === "speed") return "speed " + o.shot + " " + fnum(o.speed);
      if (x === "fx") return "fx " + o.target + " " + o.preset + ("amount" in o ? " amount=" + fnum(o.amount) : "");
      if (x === "gain") return o.clear ? "gain music clear" : "gain music " + ["from", "to", "db", "ramp"].filter((k) => k in o).map((k) => k + "=" + fnum(o[k])).join(" ");
      if (x === "import") return "import " + qtok(o.path) + " kind=" + o.kind + " licence=" + qtok(o.licence) + " source=" + qtok(o.source) + (o.id ? " id=" + qtok(o.id) : "");
      return "";
    }).join("\n");
  }
  const localId = (ref) => { ref = String(ref); const i = ref.indexOf(":"); if (i < 0) return ref; const p = ref.slice(0, i), id = ref.slice(i + 1); return id.startsWith(p + "-") ? id : p + "-" + id; };
  const takeFile = (ref) => { ref = String(ref); const i = ref.indexOf(":"); if (i < 0) return ref; return "takes/" + ref.slice(0, i) + "-" + ref.slice(i + 1).split("/").pop(); };
  const clone = (x) => JSON.parse(JSON.stringify(x == null ? null : x));
  const beatsOf = (s) => ("beats" in s ? [+s.beats[0], +s.beats[1]] : [s.bars[0] * 4, s.bars[1] * 4]);
  const setBeats = (s, b0, b1) => { delete s.bars; s.beats = [n6(b0), n6(b1)]; };
  function findShot(shots, sid, n) { const i = shots.findIndex((s) => String(s.id) === String(sid)); if (i < 0) eerr(n, "there is no shot " + sid); return i; }
  const lineId = (l) => String(l.id != null ? l.id : l.shot);
  function voLine(raw, lid, n) {
    const lines = arr((raw.vo || {}).lines);
    const ln = lines.find((x) => lineId(x) === String(lid));
    if (!ln) eerr(n, "there is no voice line " + lid + (lines.length ? " (lines: " + lines.map(lineId).join(", ") + ")" : " (this video has no voice-over)"));
    return ln;
  }
  function retimeOk(s, b0, b1, bpb, n) {
    if (arr(s.segs).length && s.segs.some((g) => "dur" in g)) eerr(n, "shot " + s.id + " has explicit segs durations, so its length cannot change here: ask the agent to re-time it");
    const bars = (b1 - b0) / bpb;
    for (const c of arr(s.cards)) if (c.bars && c.bars[1] !== "end" && +c.bars[1] > bars + 1e-9) eerr(n, "shot " + s.id + " card '" + (c.text || c.text_from) + "' runs to bar " + c.bars[1] + ", past the " + n6(bars) + "-bar shot");
  }
  function rebeat(shots) { let cur = 0; for (const s of shots) { const [b0, b1] = beatsOf(s); setBeats(s, cur, cur + (b1 - b0)); cur += b1 - b0; } return cur; }
  function setLength(raw, beats, B) {
    (raw.timeline = raw.timeline || {}).beats = n6(beats);
    (raw.output = raw.output || {}).duration = n6(Math.round(beats * B * 1000) / 1000);
    const m = raw.music;
    if (m && m.edit && typeof m.edit === "object") {
      const e = m.edit;
      e.segments = arr(e.segments).filter(([t0]) => t0 < beats).map(([t0, k0, k1]) => [n6(t0), n6(k0), n6(Math.min(k1, k0 + beats - t0))]);
      if (e.silence_from_beat != null && e.silence_from_beat >= beats) delete e.silence_from_beat;
      e.gains = arr(e.gains).filter((g) => g.beats[0] < beats).map((g) => ({ ...g, beats: [n6(g.beats[0]), n6(Math.min(g.beats[1], beats))] }));
    }
  }
  function shiftItems(items, key, cut, first) {
    const out = [];
    for (const it0 of arr(items)) {
      const it = clone(it0);
      if (key === "t" && Array.isArray(it.t) && it.t.length === 2) {
        const a = +it.t[0], b = +it.t[1];
        if (first && a < cut) out.push(it);
        else if (!first && b > cut) { it.t = [n6(Math.max(0, a - cut)), n6(b - cut)]; out.push(it); }
      } else if (key === "at" && "at" in it) {
        if (first === (+it.at < cut)) { if (!first) it.at = n6(Math.round((+it.at - cut) * 1000) / 1000); out.push(it); }
      } else out.push(it);
    }
    return out;
  }
  /* The spec data (promo.yaml as JSON) after `ops`, and {new shot id: the shot it was split from}; throws an EditError naming the line. */
  function editApply(raw0, ops, B, bpb) {
    bpb = bpb || 4;
    const raw = clone(raw0) || {}, origin = {};
    const shots = (raw.shots = raw.shots || []);
    for (const o of arr(ops)) {
      const n = o._n || "?", x = o.op;
      if (x === "swap") {
        const s = shots[findShot(shots, o.shot, n)];
        if (!("source" in s)) eerr(n, "shot " + o.shot + " (" + (s.type || "clip") + ") has no footage to swap");
        s.source = localId(o.source);
        if ("t_in" in o) s.t_in = o.t_in;
      } else if (x === "trim") {
        let i = findShot(shots, o.shot, n), nw;
        if ("start" in o) { if (i === 0) eerr(n, "the first shot starts at beat 0"); i -= 1; nw = +o.start; } else nw = +o.end;
        const a = shots[i], [a0] = beatsOf(a);
        if (i === shots.length - 1) {
          if (!(nw > a0)) eerr(n, "shot " + a.id + " would end before it starts (it starts at beat " + n6(a0) + ")");
          retimeOk(a, a0, nw, bpb, n); setBeats(a, a0, nw); setLength(raw, nw, B); continue;
        }
        const b = shots[i + 1], [, b1] = beatsOf(b);
        if (!(a0 < nw && nw < b1)) eerr(n, "the cut between " + a.id + " and " + b.id + " must stay between beats " + n6(a0) + " and " + n6(b1));
        retimeOk(a, a0, nw, bpb, n); retimeOk(b, nw, b1, bpb, n);
        setBeats(a, a0, nw); setBeats(b, nw, b1);
      } else if (x === "move") {
        const i = findShot(shots, o.shot, n), ref = "before" in o ? o.before : o.after;
        if (String(ref) === String(o.shot)) eerr(n, "a shot cannot move next to itself");
        const [s] = shots.splice(i, 1);
        shots.splice(findShot(shots, ref, n) + ("after" in o ? 1 : 0), 0, s);
        rebeat(shots);
      } else if (x === "split") {
        const i = findShot(shots, o.shot, n), s = shots[i], [b0, b1] = beatsOf(s), k = +o.at;
        if (!(k > 0 && k < b1 - b0)) eerr(n, "split at= must be inside the shot (between 0 and " + n6(b1 - b0) + " beats)");
        if (arr(s.segs).length) eerr(n, "shot " + s.id + " is made of segs: split it by hand");
        const ids = new Set(shots.map((z) => String(z.id)));
        const nid = String(s.id) + [..."bcdefghijklmnopqrstuvwxyz"].find((c) => !ids.has(String(s.id) + c));
        const cut = n6(k * B), t = clone(s);
        t.id = nid;
        setBeats(s, b0, b0 + k); setBeats(t, b0 + k, b1);
        if ("source" in t) t.t_in = n6(Math.round((+(s.t_in || 0) + cut * +(s.speed || 1)) * 1000) / 1000);
        for (const [key, field] of [["overlays", "t"], ["sfx", "at"]]) if (key in s) {
          const all = s[key];
          s[key] = shiftItems(all, field, cut, true); t[key] = shiftItems(all, field, cut, false);
          for (const part of [s, t]) if (!part[key].length) delete part[key];
        }
        shots.splice(i + 1, 0, t);
        origin[nid] = origin[String(s.id)] || String(s.id);
        for (const ln of arr((raw.vo || {}).lines)) if (String(ln.shot) === String(s.id) && +(ln.at || 0) >= cut) { ln.shot = nid; ln.at = n6(Math.round((+(ln.at || 0) - cut) * 1000) / 1000); }
      } else if (x === "delete") {
        const i = findShot(shots, o.shot, n);
        if (shots.length === 1) eerr(n, "the video's only shot cannot be deleted");
        const [s] = shots.splice(i, 1);
        if (raw.vo && arr(raw.vo.lines).length) raw.vo.lines = raw.vo.lines.filter((ln) => String(ln.shot) !== String(s.id));
        setLength(raw, rebeat(shots), B);
      } else if (x === "caption") {
        const s = shots[findShot(shots, o.shot, n)], ovs = arr(s.overlays), caps = ovs.filter((v) => v && v.type === "caption");
        if (!o.text) { s.overlays = ovs.filter((v) => !caps.includes(v)); if (!s.overlays.length) delete s.overlays; }
        else if (caps.length) caps[0].text = o.text;
        else { const [b0, b1] = beatsOf(s); s.overlays = [...ovs, { type: "caption", text: o.text, t: [0, n6(Math.round((b1 - b0) * B * 1000) / 1000)] }]; }
      } else if (x === "music") {
        let m = raw.music || {};
        const aid = localId(o.asset), beats = +((raw.timeline || {}).beats || 0);
        if (aid !== m.asset || !m.edit) m = { ...m, asset: aid, bpm: n6(60 / B), track_beat: n6(B), track_offset: n6(o.offset || 0), edit: { segments: [[0, 0, n6(beats)]], crossfade: 0.03, gains: [] } };
        else if ("offset" in o) m.track_offset = n6(o.offset);
        raw.music = m;
      } else if (x === "bus") {
        raw.mix = raw.mix || {}; raw.mix.bus_db = raw.mix.bus_db || {}; raw.mix.bus_db[o.bus] = o.db;
      } else if (x === "vo") {
        const ln = voLine(raw, o.line, n);
        if ("shot" in o) { findShot(shots, o.shot, n); ln.shot = String(o.shot); }
        if ("at" in o) ln.at = o.at;
        if ("db" in o) ln.db = o.db;
        if ("take" in o) {
          if ((raw.vo || {}).engine !== "files") eerr(n, "this voice-over is synthesised, so a recorded take cannot replace a line");
          ln.file = takeFile(o.take); delete ln.sha256;
        }
        if (o.mute === true) ln.mute = true; else if (o.mute === false) delete ln.mute;
      } else if (x === "grade") {
        const s = shots[findShot(shots, o.shot, n)];
        if (o.off) delete s.grade;
        else {
          if (s.ui !== false) eerr(n, "shot " + o.shot + " shows the product, and its pixels are never graded (rule 2); grade plates (ui: false) only");
          s.grade = { ...(s.grade || {}) }; for (const k of GRADE_KEYS) if (k in o) s.grade[k] = o[k];
        }
      } else if (x === "fade") {
        const s = shots[findShot(shots, o.shot, n)];
        if (o.off) delete s.fade;
        else {
          const [b0, b1] = beatsOf(s), f = s.fade || {};
          if (["in", "out"].reduce((t, k) => t + +(k in o ? o[k] : f[k] || 0), 0) > (b1 - b0) * B + 1e-6) eerr(n, "the fades are longer than shot " + o.shot);
          s.fade = { ...f }; for (const k of ["in", "out"]) if (k in o) s.fade[k] = o[k];
        }
      } else if (x === "speed") {
        const s = shots[findShot(shots, o.shot, n)];
        if (!("source" in s)) eerr(n, "shot " + o.shot + " has no footage to speed up or slow down");
        s.speed = o.speed;
      } else if (x === "fx") {
        const fx = "amount" in o ? { preset: o.preset, amount: o.amount } : o.preset;
        if (o.target.startsWith("vo:")) { const ln = voLine(raw, o.target.slice(3), n); if (o.preset === "off") delete ln.fx; else ln.fx = fx; }
        else {
          if (o.target !== "mix" && !raw[o.target]) eerr(n, "this video has no " + (o.target === "vo" ? "voice-over" : o.target));
          raw[o.target] = raw[o.target] || {};
          if (o.preset === "off") delete raw[o.target].fx; else raw[o.target].fx = fx;
        }
      } else if (x === "gain") {
        const m = raw.music || {};
        if (!m.edit || typeof m.edit !== "object") eerr(n, "this video has no music edit to change the level of");
        if (o.clear) m.edit.gains = [];
        else { const g = { beats: [o.from, o.to], db: o.db }; if ("ramp" in o) g.ramp = o.ramp; m.edit.gains = [...arr(m.edit.gains), g]; }
      } else if (x === "sfx") {
        const s = shots[findShot(shots, o.shot, n)];
        let lst = arr(s.sfx);
        if (o.act === "add") {
          const name = localId(o.sfx);
          raw.sfx = raw.sfx || {}; raw.sfx.library = raw.sfx.library || {};
          if (!(name in raw.sfx.library)) raw.sfx.library[name] = { asset: name };
          const e = { sfx: name, at: o.at };
          if ("db" in o) e.db = o.db;
          s.sfx = [...lst, e];
        } else {
          if (!(o.i >= 1 && o.i <= lst.length)) eerr(n, "shot " + o.shot + " has " + lst.length + " sound" + (lst.length !== 1 ? "s" : "") + ", so there is no number " + o.i);
          if (o.act === "rm") { lst = [...lst.slice(0, o.i - 1), ...lst.slice(o.i)]; if (lst.length) s.sfx = lst; else delete s.sfx; }
          else { const e = lst[o.i - 1]; for (const k of ["at", "db"]) if (k in o) e[k] = o[k]; }
        }
      }
    }
    return { raw, origin };
  }
  /* The person's edits as a stack: every change is one op; undo moves the last one aside, redo puts it back, a new change drops what was undone. */
  const editPush = (st, op) => ({ done: [...arr(st && st.done), op], undone: [] });
  const editUndo = (st) => { const d = arr(st && st.done); return d.length ? { done: d.slice(0, -1), undone: [...arr(st.undone), d[d.length - 1]] } : st; };
  const editRedo = (st) => { const u = arr(st && st.undone); return u.length ? { done: [...arr(st.done), u[u.length - 1]], undone: u.slice(0, -1) } : st; };
  /* What a Render will redo, from the edits and the editor state: the shots whose picture changes, the sound steps, and about how long it takes
     (the per-step seconds the last build stamped). Built-in shot types draw in shot-local time, so moving one does not re-render it. */
  function editSummary(ops, edit) {
    ops = arr(ops); edit = edit || {};
    const est = edit.estimate || {}, byId = new Map(arr(edit.shots).map((s) => [String(s.id), s]));
    const local = (id) => { const s = byId.get(String(id)); return !!(s && s.local); };
    const shots = new Set(), steps = new Set();
    const after = (id) => { const ids = arr(edit.shots).map((s) => String(s.id)), i = ids.indexOf(String(id)); return i < 0 ? [] : ids.slice(i); };
    for (const o of ops) {
      if (o.op === "swap" || o.op === "caption" || o.op === "speed") shots.add(String(o.shot));
      else if (o.op === "grade" || o.op === "fade") { shots.add(String(o.shot)); steps.add("grade"); }
      else if (o.op === "gain" || (o.op === "fx" && o.target === "music")) steps.add("music");
      else if (o.op === "fx" && o.target !== "mix") steps.add("vo");
      else if (o.op === "trim") { const ids = arr(edit.shots).map((s) => String(s.id)), i = ids.indexOf(String(o.shot)); if ("start" in o) { if (i > 0) shots.add(ids[i - 1]); } else if (i + 1 < ids.length) shots.add(ids[i + 1]); shots.add(String(o.shot)); }
      else if (o.op === "split") { shots.add(String(o.shot)); shots.add(String(o.shot) + "b"); for (const id of after(o.shot)) if (!local(id)) shots.add(id); }
      else if (o.op === "move" || o.op === "delete") { for (const s of arr(edit.shots)) if (!local(s.id)) shots.add(String(s.id)); if (o.op === "delete") { shots.delete(String(o.shot)); steps.add("music"); } }
      else if (o.op === "music") steps.add("music");
      else if (o.op === "vo") { steps.add("events"); if ("take" in o) steps.add("vo"); }
      else if (o.op === "sfx") steps.add("events");
      else if (o.op === "import") steps.add("import");
      if (!["import", "grade", "fade"].includes(o.op)) steps.add("mix");
    }
    if (shots.size) steps.add("events");
    const graded = ops.filter((o) => o.op === "grade" || o.op === "fade").map((o) => String(o.shot)), full = [...shots].filter((id) => !graded.includes(id) || ops.some((o) => o.op !== "grade" && o.op !== "fade" && String(o.shot) === id));
    const n = shots.size;
    const secs = full.length * (est.shot || 30) + (n - full.length) * 6 + [...steps].reduce((a, k) => a + (+est[k] || 0), 0) + (ops.length ? (+est.assemble || 20) + (+est.contact || 8) : 0);
    const parts = [n ? n + " shot" + (n === 1 ? "" : "s") : null, steps.has("music") ? "music" : null, steps.has("vo") ? "voice" : null, steps.has("mix") ? "mix" : null].filter(Boolean);
    return { shots: [...shots], steps: [...steps], secs: Math.round(secs), line: parts.length ? parts.join(" + ") + ", " + aboutS(secs) : "nothing to render" };
  }

  /* The `edit` action's message is the mod.json template with the ops in it, at most 2000 characters: longer edit lists go as edit.txt. */
  const EDIT_INLINE_MAX = 1400;
  const editInline = (opsLine) => String(opsLine || "").length <= EDIT_INLINE_MAX;
  const editFilesMessage = (count, line) => "[mod:promo-flow] The person rendered " + count + " edits from the Stage's editor (" + line + "). They are attached as edit.txt, one per line. Run: promo flow edit render --file .commission/attachments/edit.txt --by \"<their name>\", then publish. Do not approve anything.";
  const shq = (t) => '"' + String(t || "").replace(/["\\$`]/g, "\\$&") + '"';
  const importMessage = (name, kind, licence, source) => "[mod:promo-flow] The person imported a " + kind + " file in the Stage's editor (attached): " + name + ". Licence: " + licence + ". Source: " + source + ". Run: promo flow edit import .commission/attachments/" + name + " --kind " + kind
    + " --licence " + shq(licence) + " --source " + shq(source) + " --by \"<their name>\" (rule 4: it is refused without both), then publish. It shows up in the editor's bin. Do not approve anything.";

  const api = { EDIT_INLINE_MAX, editInline, editFilesMessage, importMessage, EditError, editParse, editText, editApply, editPush, editUndo, editRedo, editSummary, localId, takeFile, spaceVideo, spaceFree, FILES_TAB, FILES_MAX, fileProblem, addFiles, filesMessage, isVideoFile, WIDGET_TAB, WIDGET_PX, widgetsFor, widgetHeight, widgetDoc, themeCss, widgetMessage, settleWait, SETTLE_GAP_MS, PREVIEW_POLL_MS, commentCount, forYou, canAutopilot, jobView, clockS, aboutS, arr, mref, fileBad, missingFile, missingAll, hasPreview, noFrame, sceneStatus, model, finalState, missingRule, previewRule, bodyOf, downloadName, textFileName, wordsOf, parseBlocks, inline, plain, paginate, outline, findPages, markSplit, readMinutes, frameTimeline, DENSITY_CHOICES, clockT, noteChange, notesView, notesUnsettled, notesMessage, shareRows, outputProblem, previewOutput, outputDirty };
  root.PF = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
