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

  const api = { spaceVideo, spaceFree, FILES_TAB, FILES_MAX, fileProblem, addFiles, filesMessage, isVideoFile, WIDGET_TAB, WIDGET_PX, widgetsFor, widgetHeight, widgetDoc, themeCss, widgetMessage, settleWait, SETTLE_GAP_MS, PREVIEW_POLL_MS, commentCount, forYou, canAutopilot, jobView, clockS, aboutS, arr, mref, fileBad, missingFile, missingAll, hasPreview, noFrame, sceneStatus, model, finalState, missingRule, previewRule, bodyOf, downloadName, textFileName, wordsOf, parseBlocks, inline, plain, paginate, outline, findPages, markSplit, readMinutes, frameTimeline, DENSITY_CHOICES, clockT, noteChange, notesView, notesUnsettled, notesMessage, shareRows, outputProblem, previewOutput, outputDirty };
  root.PF = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
