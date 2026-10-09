"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../logic.js");

const ok = (id) => ({ $media: { upload_id: id, name: id + ".png", mime: "image/png", size: 10 } });
const bad = { $media: null, $error: "gone" };
const frames = { start: { path: ok("s") }, end: { path: ok("e") } };
const asset = (id, kind, source, state, scenes, path) => ({ id, kind, source, state, scenes, path: path === undefined ? (state === "ready" ? ok(id) : null) : path });
const scene = (id, source, extra) => ({ id, source, ...frames, ...extra });

test("a script or document reads from its inline text; a missing or too-long one shows the agent's note instead", () => {
  assert.deepEqual(L.bodyOf({ body: "# A\n\nOne." }), { text: "# A\n\nOne." });
  assert.equal(L.bodyOf({ body: null, body_note: "Too long to show here (120,000 words). Ask the agent to split it into parts." }).error, "Too long to show here (120,000 words). Ask the agent to split it into parts.");
  assert.match(L.bodyOf({ body: { $file: "/x/A.md" } }).error, /Ask the agent/);          // an older state shape never reads as text
  assert.equal(L.textFileName("Full script: Wake up to merged PRs"), "full-script-wake-up-to-merged-prs.md");
});

test("real scene covered by a mock asset is Mock in plan, never Captured", () => {
  const as = [asset("a", "recording", "real", "ready", ["03"]), asset("b", "recording", "real", "mock", ["03"])];
  assert.equal(L.sceneStatus(scene("03", "real"), as).label, "Mock in plan");
  assert.equal(L.sceneStatus(scene("03", "real"), as).cls, "mock");
});
test("real scene: no real asset, a todo or a missing file read To capture", () => {
  assert.equal(L.sceneStatus(scene("01", "real"), []).label, "To capture");
  assert.equal(L.sceneStatus(scene("01", "real"), [asset("a", "recording", "real", "todo", ["01"])]).label, "To capture");
  assert.equal(L.sceneStatus(scene("01", "real"), [asset("a", "recording", "real", "ready", ["01"], bad)]).label, "To capture");
  assert.equal(L.sceneStatus(scene("01", "real"), [asset("a", "screenshot", "real", "ready", ["01"]), asset("g", "video", "generated", "todo", ["01"])]).label, "To capture");
});
test("real scene: screenshots alone are stills, a recording is Captured", () => {
  assert.deepEqual(L.sceneStatus(scene("01", "real"), [asset("a", "screenshot", "real", "ready", ["01"])]).kind, "stills");
  const s = L.sceneStatus(scene("01", "real"), [asset("a", "screenshot", "real", "ready", ["01"]), asset("r", "recording", "real", "ready", ["01"])]);
  assert.equal(s.label, "Captured");
  assert.equal(s.cls, "real");
});
test("audio assets do not change what a scene looks like", () => {
  const as = [asset("r", "recording", "real", "ready", ["01"]), asset("m", "music", "licensed", "mock", ["01"]), asset("v", "voice", "generated", "todo", ["01"])];
  assert.equal(L.sceneStatus(scene("01", "real"), as).label, "Captured");
});
test("generated scene: unmade plate, mock, or ready", () => {
  assert.equal(L.sceneStatus(scene("04", "generated"), [asset("p", "video", "generated", "todo", ["04"])]).label, "Plate to generate");
  assert.equal(L.sceneStatus(scene("08", "generated"), [asset("c", "image", "generated", "mock", ["08"])]).label, "Mock in plan");
  assert.equal(L.sceneStatus(scene("08", "generated"), [asset("c", "image", "generated", "mock", ["08"]), asset("p", "video", "generated", "todo", ["08"])]).label, "Plate to generate");
  assert.equal(L.sceneStatus(scene("01", "generated"), [asset("p", "image", "generated", "ready", ["01"])]).label, "Generated plate");
});
test("scene with an unmade keyframe is a dashed mark whatever its label", () => {
  const s = { id: "01", source: "generated", start: { path: ok("s") }, end: { path: null } };
  assert.equal(L.sceneStatus(s, []).cls, "todo");
  assert.equal(L.sceneStatus({ id: "x" }, []).label, "");
});

test("buckets are exclusive and sum to the total, scoped to the selected story", () => {
  const A = { id: "A", scenes: [{ id: "01" }, { id: "02" }] }, B = { id: "B", scenes: [{ id: "11" }] };
  const doc = {
    assets: [asset("a", "image", "real", "ready", ["01", "11"]), asset("b", "music", "licensed", "ready", ["02"], bad), asset("c", "sfx", "generated", "todo", ["01"]),
      asset("d", "image", "real", "mock", ["11"]), asset("e", "image", "real", "ready", ["99"])],
    to_make: [{ kind: "keyframe", story: "A", scene: "02" }, { kind: "keyframe", story: "B", scene: "11" }, { kind: "asset", id: "c" }],
  };
  const a = L.model(doc, A), b = L.model(doc, B);
  assert.deepEqual(a.n, { ready: 1, mock: 0, todo: 2, missing: 1 });
  assert.equal(a.total, 4);
  assert.equal(Object.values(a.n).reduce((x, y) => x + y, 0), a.total);
  assert.deepEqual(b.n, { ready: 1, mock: 1, todo: 1, missing: 0 });
  assert.equal(Object.values(b.n).reduce((x, y) => x + y, 0), b.total);
});

test("a final is done only when every final file resolves and nothing is stale", () => {
  assert.deepEqual(L.finalState({ finals: [] }), { registered: false, ok: false });
  assert.equal(L.finalState({ finals: [{ path: ok("f") }] }).ok, true);
  assert.deepEqual(L.finalState({ finals: [{ path: null }] }), { registered: true, ok: false });
  assert.equal(L.finalState({ finals: [{ path: bad }] }).ok, false);
  assert.equal(L.finalState({ finals: [{ path: ok("f") }], stale_steps: [{ id: "storyboard" }] }).ok, false);
});

test("missing-file rule: Approve is blocked at the assets gate, plural-correct", () => {
  const one = { assets: [asset("a", "image", "real", "ready", ["01"], bad)] };
  const two = { assets: [asset("a", "image", "real", "ready", ["01"], bad), asset("b", "music", "licensed", "ready", ["01"], null)] };
  assert.equal(L.missingRule(one, "assets-approved").note, "1 file is missing. Add changes so the agent attaches it.");
  assert.equal(L.missingRule(two, "assets-approved").note, "2 files are missing. Add changes so the agent attaches them.");
  assert.equal(L.missingRule(one, "storyboard-approved"), null);
  assert.equal(L.missingRule({ assets: [asset("a", "image", "real", "ready", ["01"])] }, "assets-approved"), null);
});

test("nobody approves a placeholder: unmade frames and previewless assets block their gates", () => {
  const doc = { boards: [{ scenes: [{ id: "01", start: { path: ok("s") }, end: { path: null, slate: true } }, { id: "02", start: { path: ok("a") }, end: { path: ok("b") } }] }],
    assets: [asset("r", "recording", "mock", "mock", ["01"]), asset("m", "music", "licensed", "todo", ["01"]), { ...asset("v", "voice", "licensed", "todo", ["01"]), sample: ok("v") }] };
  assert.equal(L.previewRule(doc, "storyboard-approved").count, 1);
  assert.match(L.previewRule({ ...doc, boards: [{ id: "B", scenes: [] }, { id: "D", scenes: doc.boards[0].scenes }] }, "storyboard-approved").note, /story D: 1/);
  assert.equal(L.previewRule(doc, "assets-approved").count, 2);
  assert.equal(L.previewRule(doc, "draft-approved"), null);
  doc.boards[0].scenes[0].end.path = ok("e");
  doc.assets[0].sample = ok("clip");
  doc.assets[1].sample = ok("track");
  assert.equal(L.previewRule(doc, "storyboard-approved"), null);
  assert.equal(L.previewRule(doc, "assets-approved"), null);
});
test("a sample that failed to attach is no preview", () => {
  assert.equal(L.hasPreview({ ...asset("m", "music", "licensed", "todo", ["01"]), sample: bad }), false);
  assert.equal(L.hasPreview({ ...asset("m", "music", "licensed", "todo", ["01"]), sample: ok("t") }), true);
});

test("download name: the host's file name wins when it has an extension", () => {
  assert.equal(L.downloadName({ name: "promo-1080.mp4" }, "Final"), "promo-1080.mp4");
  assert.equal(L.downloadName({ name: "draft v2.webm" }, "Draft 2"), "draft v2.webm");
});
test("download name: no extension falls back to the label as a slug plus .mp4", () => {
  assert.equal(L.downloadName({ name: "final" }, "Draft 2 · after round 1"), "draft-2-after-round-1.mp4");
  assert.equal(L.downloadName({ name: "promo-1.0" }, "Final 1080"), "final-1080.mp4");
  assert.equal(L.downloadName({}, "Zweiter Entwurf: Überarbeitung"), "zweiter-entwurf-überarbeitung.mp4");
  assert.equal(L.downloadName(null, " · ! "), "promo.mp4");
  assert.equal(L.downloadName({ name: "x." }, "a".repeat(80) + " tail").length, 60 + ".mp4".length);
});

test("share rows: new, on, edited draft (in place or a copy) and a locked final", () => {
  const doc = { share: { destinations: [{ id: "artifacts", label: "Atlassian Artifacts", note: "Private to you.", in_place: true }, { id: "loom", label: "Loom", note: "Goes to your library." }] } };
  const file = { path: ok("v") };
  const rec = (edited) => ({ url: "https://x/y", name: "p_draft_1", edited });
  const rows = (it) => Object.fromEntries(L.shareRows(doc, it).map((r) => [r.dest, r]));
  assert.deepEqual(L.shareRows({ share: { destinations: [] } }, { id: "d1", ...file }), []);
  assert.deepEqual(L.shareRows(doc, { id: "d1", path: bad }), []);
  let r = rows({ id: "d1", ...file, shared: {} });
  assert.equal(r.artifacts.state, "new");
  assert.equal(r.artifacts.action, "Upload to Atlassian Artifacts");
  r = rows({ id: "d1", ...file, shared: { artifacts: rec(false), loom: rec(true) } });
  assert.deepEqual([r.artifacts.state, r.artifacts.url, r.artifacts.action], ["on", "https://x/y", ""]);
  assert.deepEqual([r.loom.state, r.loom.action, r.loom.note], ["edited", "Upload again to Loom", "Loom keeps the earlier copy."]);
  assert.equal(rows({ id: "d1", ...file, shared: { artifacts: rec(true) } }).artifacts.action, "Update on Atlassian Artifacts");
  r = rows({ id: "f2", ...file, shared: { artifacts: rec(true) } });
  assert.deepEqual([r.artifacts.state, r.artifacts.action], ["locked", ""]);
});

/* ---- reading long documents ---- */
test("markdown blocks: headings, lists with checks, tables, quotes, code, page markers", () => {
  const b = L.parseBlocks("# Title\n\nFirst line\nsecond line\n\n- one\n  - nested\n- [x] done\n- [ ] open\n\n1. a\n2. b\n\n> quoted\n> more\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```\ncode # not heading\n```\n\n<!-- page: Act two -->\n---\n");
  assert.deepEqual(b.map((x) => x.t), ["h", "p", "list", "list", "quote", "table", "code", "page", "hr"]);
  assert.equal(b[1].text, "First line\nsecond line");
  assert.deepEqual(b[2].items.map((x) => [x.depth, x.check]), [[0, null], [1, null], [0, true], [0, false]]);
  assert.equal(b[3].items[1].ordered, true);
  assert.deepEqual(b[5].head, ["A", "B"]);
  assert.deepEqual(b[5].rows, [["1", "2"]]);
  assert.equal(b[6].text, "code # not heading");
  assert.equal(b[7].title, "Act two");
});
test("inline markup: bold, italic, code, https links, trailing punctuation stays out of the link", () => {
  const t = L.inline("a **b** and *c* and `d` see [site](https://x.dev/a) or https://y.dev/z. Done");
  assert.deepEqual(t.map((x) => x.t), ["text", "b", "text", "i", "text", "code", "text", "link", "text", "link", "text"]);
  assert.equal(t[9].url, "https://y.dev/z");
  assert.equal(t[10].text, ". Done");
  assert.equal(L.plain("**x** *y* [z](https://a.b)"), "x y z");
  assert.deepEqual(L.inline("javascript:alert(1) [x](javascript:alert(1))").map((x) => x.t), ["text"]);
});
const longDoc = (sections, words) => Array.from({ length: sections }, (_, i) => "## Section " + (i + 1) + "\n\n" + Array.from({ length: words / 50 }, () => "word ".repeat(50).trim() + ".").join("\n\n")).join("\n\n");
test("pagination: explicit markers win, otherwise ~650 words per page and a new page at a heading, never inside a block", () => {
  const marked = L.paginate("intro\n\n<!-- page: One -->\nalpha\n\n<!-- page -->\nbeta\n");
  assert.deepEqual(marked.map((p) => p.title), ["Page 1", "One", "Page 3"]);
  const pages = L.paginate(longDoc(6, 500));
  assert.ok(pages.length >= 4 && pages.length <= 6, "pages " + pages.length);
  assert.ok(pages.every((p) => p.words > 0 && p.words <= 900));
  assert.equal(pages.map((p) => p.words).reduce((a, b) => a + b, 0), 3000 + 12, "every word lands on exactly one page");
  assert.ok(pages[1].title.startsWith("Section"));
  const table = "| a | b |\n|--|--|\n" + "| x y z | q |\n".repeat(900);
  assert.equal(L.paginate(table).length, 1, "a table is one block");
  assert.equal(L.paginate("").length, 1);
});
test("a 30 000 word script paginates and searches fast", () => {
  const t0 = Date.now();
  const pages = L.paginate(longDoc(60, 500));
  assert.ok(pages.length > 40);
  assert.equal(L.outline(pages).filter((o) => o.level === 2).length, 60);
  assert.ok(Date.now() - t0 < 1500);
});
test("outline and find", () => {
  const pages = L.paginate("# Doc\n\nhello Needle\n\n<!-- page -->\n## Two\n\nneedle needle\n");
  assert.deepEqual(L.outline(pages).map((o) => [o.title, o.page]), [["Doc", 0], ["Two", 1]]);
  assert.deepEqual(L.findPages(pages, "needle"), [{ page: 0, n: 1 }, { page: 1, n: 2 }]);
  assert.deepEqual(L.findPages(pages, "n"), []);
  assert.deepEqual(L.markSplit("A Needle b", "needle"), [{ text: "A ", hit: false }, { text: "Needle", hit: true }, { text: " b", hit: false }]);
});
test("frame timeline: every frame in time order, a scene's END before the next scene's START", () => {
  const sc = (id, a, b, mids) => ({ id, start_s: a, end_s: b, start: { id: id + "s" }, end: { id: id + "e" }, frames: (mids || []).map((t) => ({ t })) });
  const tl = L.frameTimeline({ scenes: [sc("01", 0, 5, [2.5]), sc("02", 5, 12, [7, 10])] });
  assert.deepEqual(tl.map((x) => [x.scene.id, x.kind, x.t]), [["01", "start", 0], ["01", "mid", 2.5], ["01", "end", 5], ["02", "start", 5], ["02", "mid", 7], ["02", "mid", 10], ["02", "end", 12]]);
  assert.equal(L.clockT(65.5), "1:05.5");
  assert.equal(L.clockT(5), "0:05");
});

test("non-Latin scripts count words and paginate", () => {
  assert.equal(L.wordsOf("Привет мир, это сценарий"), 4);
  assert.equal(L.wordsOf("日本語 の 台本"), 3);
  const ru = L.paginate(Array.from({ length: 40 }, (_, i) => "## Акт " + i + "\n\n" + "слово ".repeat(60)).join("\n\n"));
  assert.ok(ru.length > 2, "pages " + ru.length);
});
test("a heading keeps its own # (C#), only a closing run of # is dropped", () => {
  assert.equal(L.parseBlocks("# C#")[0].text, "C#");
  assert.equal(L.parseBlocks("## Title ##")[0].text, "Title");
});
test("search ignores case and survives characters whose lower case is longer", () => {
  assert.deepEqual(L.markSplit("Stra\u00dfe \u0130stanbul", "stanbul").map((x) => [x.text, x.hit]), [["Stra\u00dfe \u0130", false], ["stanbul", true]]);
  assert.deepEqual(L.markSplit("a.b a+b", "a+b").map((x) => x.hit), [false, true]);
  assert.deepEqual(L.findPages(L.paginate("one Needle\n\nNEEDLE two"), "needle"), [{ page: 0, n: 2 }]);
});
test("clock times never print 0:010 or 0:60", () => {
  assert.equal(L.clockT(9.96), "0:10");
  assert.equal(L.clockT(59.96), "1:00");
  assert.equal(L.clockT(0), "0:00");
  assert.equal(L.clockT(125), "2:05");
  assert.equal(L.clockT(14.5), "0:14.5");
});

const out = { project: "shop", repo: "/work/shop", home: "/Users/me", mode: "home", template: "~/.promo-reel/{project}/{slug}" };
test("save folder: values the CLI would refuse never get sent", () => {
  assert.equal(L.outputProblem("/Volumes/Drive/promo-reel/{project}/{slug}"), "");
  assert.equal(L.outputProblem("/Volumes/My Drive/promo-reel"), "");
  assert.match(L.outputProblem("  "), /Type the folder/);
  assert.match(L.outputProblem('/Volumes/x"; rm -rf ~; "'), /can't contain/);
  assert.match(L.outputProblem("/x/$HOME"), /can't contain/);
  assert.match(L.outputProblem("/x/{who}/{slug}"), /Only \{project\} and \{slug\}.*\{who\}/);
  assert.match(L.outputProblem("/x/{slug}/more"), /last folder/);
});
test("save folder: the preview shows where the next video lands", () => {
  assert.equal(L.previewOutput("/Volumes/Drive/{project}", out), "/Volumes/Drive/shop/<slug>");
  assert.equal(L.previewOutput("~/clips/{slug}", out), "/Users/me/clips/<slug>");
  assert.equal(L.previewOutput("./promo-reel", out), "/work/shop/promo-reel/<slug>");
});
test("save folder: Save is offered only when the choice differs from what is saved", () => {
  assert.equal(L.outputDirty(out, "home", ""), false);
  assert.equal(L.outputDirty(out, "repo", ""), true);
  assert.equal(L.outputDirty(out, "custom", "/Volumes/D"), true);
  const custom = { ...out, mode: "custom", template: "/Volumes/D/{slug}" };
  assert.equal(L.outputDirty(custom, "custom", "/Volumes/D"), false);
  assert.equal(L.outputDirty(custom, "custom", "/Volumes/E"), true);
});

const T0 = Date.parse("2026-10-07T10:00:00+11:00");
const at = (s) => new Date(T0 + s * 1000).toISOString();
const run = (extra) => ({ kind: "frames", label: "Generating storyboard images", state: "running", done: 0, failed: 0, total: 6, started: at(0), updated: at(0), finished: null, active: [], items: [], ...extra });
const made = (id, s, ok = true) => ({ id, label: "Scene " + id, at: at(s), ok, path: ok ? { $media: { upload_id: id, mime: "image/png" } } : null });
test("a running job fills tiles in order: made, being made, queued, with a time estimate", () => {
  const v = L.jobView(run({ done: 2, failed: 1, items: [made("1", 30), made("2", 60), made("3", 90, false)], active: [{ id: "4", label: "Scene 4" }] }), T0 + 100000);
  /* queued items are a count, not blank tiles: made, failed and being-made tiles plus "N more queued" sum to the total */
  assert.deepEqual(v.tiles.map((t) => t.type), ["item", "item", "failed", "active"]);
  assert.equal(v.moreQueued, 2);
  assert.equal(v.title, "Generating storyboard images");
  /* the bar is the made count; a failed item is its own red segment, so bar and "8 / 20" label agree */
  assert.equal(v.pct, 2 / 6);
  assert.equal(v.failPct, 1 / 6);
  assert.equal(v.eta, 100);
  assert.equal(v.quiet, 10);
  assert.equal(v.slow, false);
});
test("a slow run that still checks in is alive; one that stopped checking in is stale", () => {
  const now = T0 + 20 * 60000;
  const slowBuild = run({ kind: "build", label: "Building the video", done: 3, items: [made("vo", 60)], active: [{ id: "shot 05", label: "Shot 05" }] });
  assert.deepEqual([L.jobView({ ...slowBuild, updated: at(19 * 60) }, now)].map((v) => [v.alive, v.slow, v.stale]), [[true, true, false]]);
  assert.deepEqual([L.jobView({ ...slowBuild, updated: at(10 * 60) }, now)].map((v) => [v.alive, v.slow, v.stale]), [[false, false, true]]);
  const queued = L.jobView({ ...slowBuild, updated: at(19 * 60), waiting: "Waiting for another render on this Mac to finish" }, now);
  assert.equal(queued.waiting, "Waiting for another render on this Mac to finish");
  assert.equal(queued.slow, false);
});
test("a long run keeps its newest pictures", () => {
  const items = Array.from({ length: 40 }, (_, i) => made(String(i), i));
  const v = L.jobView(run({ total: 100, done: 40, items, active: [{ id: "40", label: "Scene 40" }], updated: at(39) }), T0 + 40000);
  assert.equal(v.tiles.length, 24);
  /* no queued tiles: the room goes to the newest pictures */
  assert.equal(v.tiles[0].item.id, "17");
  assert.equal(v.earlier, 17);
  assert.equal(v.moreQueued, 59);
});
test("a finished run reads Made N and fades out after ten minutes; a stopped run stays", () => {
  const done = run({ state: "done", done: 6, finished: at(300), items: [made("1", 300)] });
  assert.equal(L.jobView(done, T0 + 301000).title, "Made 6 images");
  const built = run({ kind: "build", state: "done", done: 5, finished: at(300), items: [{ ...made("sfx", 10), skipped: true }, made("shot 01", 200)] });
  assert.equal(L.jobView(built, T0 + 301000).title, "Finished 5 steps, 1 unchanged");
  assert.equal(L.jobView(done, T0 + 300000 + 11 * 60000), null);
  const stopped = L.jobView(run({ state: "stopped", done: 2, updated: at(60) }), T0 + 3600000);
  assert.equal(stopped.title, "Stopped after 2 of 6 images");
  assert.deepEqual(stopped.tiles.map((t) => t.type), []);
});

test("what waits on the person: unanswered blind picks (answerable once both sides load), choices not overturned, a live autopilot run", () => {
  const doc = { stage: "review",
    pairs: [{ id: "p1", left: ok("l"), right: ok("r"), answered: null }, { id: "p2", left: ok("l"), right: bad, answered: null }, { id: "p3", left: ok("l"), right: ok("r"), answered: { side: "left" } }],
    assumptions: [{ id: "a1", text: "Calm piano", overturned: null }, { id: "a2", text: "Old", overturned: { by: "Sam" } }],
    autopilot: { state: "running", minutes: 60, used_min: 15 } };
  const fy = L.forYou(doc);
  assert.deepEqual(fy.pairs.map((p) => [p.id, p.ready]), [["p1", true], ["p2", false]]);
  assert.deepEqual(fy.assumptions.map((a) => a.id), ["a1"]);
  assert.equal(fy.autopilot.live, true);
  assert.equal(fy.autopilot.pct, 0.25);
  assert.equal(L.forYou({ ...doc, stage: "final", autopilot: { state: "done", minutes: 60, used_min: 20 } }).autopilot, null);   // an ended run leaves with the review
});
test("the agent may be left to work alone only on the latest draft, when it has checks and nothing is running", () => {
  const d1 = { id: "d1", board: { total: 2 } }, d2 = { id: "d2", board: { total: 2 } };
  const doc = { stage: "review", drafts: [d1, d2], autopilot: null };
  assert.equal(L.canAutopilot(doc, d2), true);
  assert.equal(L.canAutopilot(doc, d1), false);
  assert.equal(L.canAutopilot({ ...doc, autopilot: { state: "paused" } }, d2), false);
  const bare = { id: "d2", board: { total: 0 } };
  assert.equal(L.canAutopilot({ ...doc, drafts: [d1, bare] }, bare), false);
});

test("the comment count separates the scene comments still open from the answered ones", () => {
  const doc = { boards: [{ scenes: [{ notes: [{ answer: null }, { answer: "done" }] }, {}] }, { scenes: [{ notes: [{ answer: null }] }] }] };
  assert.deepEqual(L.commentCount(doc), { open: 2, total: 3 });
  assert.deepEqual(L.commentCount({}), { open: 0, total: 0 });
});

test("an update from the agent never repaints under a clip being watched, and while it works repaints at most once per gap; the person's own clicks are instant", () => {
  assert.equal(L.settleWait({ userChanged: true, previewing: true, working: true, sinceBuild: 0 }), 0);
  assert.equal(L.settleWait({ userChanged: false, previewing: true, working: false, sinceBuild: 99999 }), L.PREVIEW_POLL_MS);
  assert.equal(L.settleWait({ userChanged: false, previewing: false, working: true, sinceBuild: 2000 }), L.SETTLE_GAP_MS - 2000);
  assert.equal(L.settleWait({ userChanged: false, previewing: false, working: true, sinceBuild: L.SETTLE_GAP_MS + 1 }), 0);
  assert.equal(L.settleWait({ userChanged: false, previewing: false, working: false, sinceBuild: 0 }), 0);
});

const widget = (id, place, extra) => ({ id, place, title: id, kind: "blocks", span: 12, height: "m", ...extra });

test("a tab shows the widgets placed on it, and nothing else", () => {
  const doc = { widgets: [widget("a", "workbench"), widget("b", "assets"), widget("c", "workbench")] };
  assert.deepEqual(L.widgetsFor(doc, "workbench").map((w) => w.id), ["a", "c"]);
  assert.deepEqual(L.widgetsFor(doc, "assets").map((w) => w.id), ["b"]);
  assert.deepEqual(L.widgetsFor({}, "workbench"), []);
});

test("a widget's height is its preset, taller when enlarged, and follows the content only when auto (within limits)", () => {
  assert.equal(L.widgetHeight(widget("a", "workbench", { height: "l" }), 0, false), L.WIDGET_PX.l);
  assert.equal(L.widgetHeight(widget("a", "workbench", { height: "l" }), 0, true), L.WIDGET_PX.xl);
  const auto = widget("a", "workbench", { height: "auto" });
  assert.equal(L.widgetHeight(auto, 0, false), L.WIDGET_PX.s);
  assert.equal(L.widgetHeight(auto, 41, false), 120);
  assert.equal(L.widgetHeight(auto, 333.2, false), 334);
  assert.equal(L.widgetHeight(auto, 5000, false), 700);
});

test("the frame document carries the policy before anything the agent wrote, and the theme cannot break out of its style block", () => {
  const doc = L.widgetDoc("<p id=x>hi</p>", { dark: true, ink: "#eee", accent: "red;}</style><script>alert(1)</script>" });
  assert.ok(doc.indexOf("Content-Security-Policy") < doc.indexOf("<p id=x>"));
  assert.match(doc, /default-src 'none'/);
  assert.match(doc, /connect-src blob: data:/);
  assert.ok(!doc.includes("<script>alert(1)"), "a theme value is plain CSS text");
  assert.match(doc, /--pf-ink:#eee/);
});

test("only the messages the frame runtime sends are accepted from a frame", () => {
  assert.deepEqual(L.widgetMessage({ pf: "size", h: 120 }), { kind: "size", h: 120 });
  assert.deepEqual(L.widgetMessage({ pf: "tell", text: "  Render it  " }), { kind: "tell", text: "Render it" });
  assert.equal(L.widgetMessage({ pf: "tell", text: "x".repeat(5000) }).text.length, 1500);
  assert.deepEqual(L.widgetMessage({ pf: "error", text: "x is not defined" }), { kind: "error", text: "x is not defined" });
  assert.equal(L.widgetMessage({ pf: "tell", text: "   " }), null);
  assert.equal(L.widgetMessage({ pf: "size", h: "tall" }), null);
  assert.equal(L.widgetMessage({ pf: "open-url", url: "https://x" }), null);
  assert.equal(L.widgetMessage("tell"), null);
});

test("added files keep the host's limits: 10 at a time, no duplicates, 100 MB a video and 20 MB the rest, never empty", () => {
  const f = (name, size, type) => ({ name, size, type: type || "", lastModified: 1 });
  assert.equal(L.fileProblem(f("a.mov", 0)), "The file is empty");
  assert.equal(L.fileProblem(f("a.mov", 99 * 1048576, "video/quicktime")), null);
  assert.equal(L.fileProblem(f("a.mov", 101 * 1048576)), "Over the 100 MB limit");        // a .mov is a video even when the browser gives no type
  assert.equal(L.fileProblem(f("a.png", 21 * 1048576, "image/png")), "Over the 20 MB limit");
  const first = L.addFiles([], [f("a.png", 5), f("a.png", 5), f("b.png", 5)]);
  assert.deepEqual(first.files.map((x) => x.name), ["a.png", "b.png"]);
  const many = L.addFiles(first.files, Array.from({ length: 12 }, (_, i) => f("c" + i + ".png", 1)));
  assert.equal(many.files.length, L.FILES_MAX);
  assert.equal(many.skipped, 4);
});

test("the message for the agent names the files, the note and the rows still waiting, and never approves", () => {
  const m = L.filesMessage([{ name: "board.mov" }, { name: "login.png" }], "  the real run\nfrom today ", [{ id: "rec-a", kind: "recording" }, { id: "" }, null]);
  assert.match(m, /^\[mod:promo-flow\] The person added 2 files/);
  assert.match(m, /board\.mov, login\.png\./);
  assert.match(m, /Their note: the real run from today\./);
  assert.match(m, /still waiting for footage: rec-a \(recording\)\./);
  assert.match(m, /Do not approve anything\.$/);
  assert.doesNotMatch(L.filesMessage([{ name: "a.mov" }], "", []), /note|waiting/);
});
