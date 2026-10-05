"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../logic.js");

const ok = (id) => ({ $media: { upload_id: id, name: id + ".png", mime: "image/png", size: 10 } });
const bad = { $media: null, $error: "gone" };
const frames = { start: { path: ok("s") }, end: { path: ok("e") } };
const asset = (id, kind, source, state, scenes, path) => ({ id, kind, source, state, scenes, path: path === undefined ? (state === "ready" ? ok(id) : null) : path });
const scene = (id, source, extra) => ({ id, source, ...frames, ...extra });

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

test("seen-story rule: every story must be opened in the tab the gate decides on", () => {
  const doc = { boards: [{ id: "A" }, { id: "B" }] };
  assert.deepEqual(L.seenRule(doc, "storyboard-approved", new Set()), { board: "A", tab: "storyboard" });
  assert.deepEqual(L.seenRule(doc, "storyboard-approved", new Set(["storyboard:A"])), { board: "B", tab: "storyboard" });
  assert.equal(L.seenRule(doc, "storyboard-approved", new Set(["storyboard:A", "storyboard:B"])), null);
  assert.deepEqual(L.seenRule(doc, "assets-approved", new Set(["storyboard:A", "storyboard:B", "assets:A"])), { board: "B", tab: "assets" });
  assert.deepEqual(L.seenRule(doc, "final-confirmation", new Set(["assets:A", "assets:B", "storyboard:A"])), { board: "B", tab: "storyboard" });
  assert.equal(L.seenRule({ boards: [{ id: "A" }] }, "storyboard-approved", new Set()), null);
  assert.equal(L.seenRule(doc, "draft-approved", new Set()), null);
});

test("missing-file rule: Approve is blocked at the assets gate, plural-correct", () => {
  const one = { assets: [asset("a", "image", "real", "ready", ["01"], bad)] };
  const two = { assets: [asset("a", "image", "real", "ready", ["01"], bad), asset("b", "music", "licensed", "ready", ["01"], null)] };
  assert.equal(L.missingRule(one, "assets-approved").note, "1 file is missing. Send changes so the agent attaches it.");
  assert.equal(L.missingRule(two, "assets-approved").note, "2 files are missing. Send changes so the agent attaches them.");
  assert.equal(L.missingRule(one, "storyboard-approved"), null);
  assert.equal(L.missingRule({ assets: [asset("a", "image", "real", "ready", ["01"])] }, "assets-approved"), null);
});
