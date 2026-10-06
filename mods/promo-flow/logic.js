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

  /* File name for a saved draft: the host's own file name when it carries an extension, else the label as a slug plus .mp4. */
  function downloadName(r, label) {
    const name = String((r && r.name) || "").trim();
    if (/^.+\.[A-Za-z][A-Za-z0-9]{0,7}$/.test(name)) return name;
    const slug = String(label || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-+|-+$/g, "").slice(0, 60).replace(/-+$/, "");
    return (slug || "promo") + ".mp4";
  }

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

  const api = { arr, mref, fileBad, missingFile, missingAll, hasPreview, noFrame, sceneStatus, model, finalState, seenRule, seenKey, missingRule, previewRule, downloadName, shareRows };
  root.PF = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
