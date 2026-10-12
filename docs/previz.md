# Previz: block the film out as wireframes before any keyframe or render

The directing gap: the storyboard gives each scene a start and an end still, and the thin-prompt path goes from `designed apply` straight
to a quick look. Nobody iterated the camera, the panel placement, the type or the timing while that was still cheap, so the first real
look was a stills slideshow and every fix was a re-render. Previz is that step: a JSON scene of wire boxes drawn by a small Three.js
viewer, re-exported as a contact strip in about a second.

```bash
promo previz build            # previz/scene.json + previz/viewer.html (from plan.designed, else the picked storyboards)
promo previz strip            # previz/strip.png: one tile per shot, labelled with the camera move and the time
promo previz show             # shots, scene hash, strip status
promo previz open             # the viewer in a browser (--print: just the path)
promo previz cam 03 push --amount 0.15 --strip    # nudge, then re-export the strip
promo previz panel 05 ui-1 --cx 0.4 --w 0.55 --z 0.1 --strip
promo previz type 05 c1 --cy 0.86 --size 6 --strip
promo previz dur 05 7 --strip
promo previz sync             # re-derive from the plan / storyboard; your nudges (`overrides`) stay
promo previz apply            # carry the directed camera / panel into the cinema shots (runs `promo designed apply`)
```

`promo -p NAME previz ...` works too. `strip --shot 05` (start / middle / end of one shot), `--at 12.5 30`, `--n 8` and `--ends` are cheap
looks that never satisfy a gate.

## Where it sits

discover, scripts, pick, storyboard, **previz**, assets, keyframes, confirm, drafts, review, final (`promo flow`), and in the thin-prompt
path plan, cospec, designed apply, **previz strip**, look / strip, gen plates, preview.

Why between storyboard and assets, not storyboard and keyframes: the person's one plan review is the `assets-approved` gate, and a plan
that has been blocked out is a better plan to approve: it now covers storyboard, previz strip and assets, and the approval goes stale if
the scene hash changes (`flow.gate_hash`). Keyframes are the first expensive thing, so they are the thing the gate holds back
(`make_frames` refuses at keyframes or later while the strip is missing or stale).

## What the scene holds

`previz/scene.json` (`promo-previz@1`), one shot per scene or designed shot:

| key | meaning |
|---|---|
| `camera.keys` | `[{t, cx, cy, w, ease}]`: the visible box as the cinema `cam` is (`w` = width as a fraction of the frame, smaller = pushed in). `mode` is derived: locked / push / pullback / parallax. `projection`: `ortho` (pure 2D) or `persp` (floating panels get real parallax). |
| `panels` | `floating`, `device` or `fullscreen` wire quads on `z` (0 = the plane, up to 0.3 in front). Optional `source` = a supplied still from `stills`, textured at low opacity with `--stills`. `crop` is where a panel shot's cinema `cam` looks into the still. |
| `type` | placeholder boxes standing in for cards and brackets: `text`, `at`, `dur`, `size_pct`, `cx`, `cy`. Not final typography. |
| `plate` | the backdrop plane. `ui` is always `false`. |
| `t0`, `dur` | timing; the timeline is the sum of the shots. |
| `overrides` | the agent's edits by shot id (camera keys, panels, type, `dur`) and scene-wide `projection`. `sync` never touches them; an override of a shot that no longer exists is reported as an orphan. |

The scene hash covers the effective scene (generated shots with overrides applied) and not notes or labels, so renaming a note does not
stale a strip but moving a panel does.

Compile sources: `from_designed` reuses `designed.compile_shots` (so the framing hierarchy and dialect camera limits are the plan's own;
exceeding them is a warning), `from_storyboard` reads the scene's `camera` words and caption. The perspective maths is one function in
Python (`previz.project`) and one in `templates/previz/viewer.js`.

## Viewer and strip

`viewer.html` is self-contained (three.js r160, MIT, vendored in `templates/previz/vendor/`; no network). Space plays, arrow keys scrub
(a frame; shift = 1 s), `[` and `]` jump shots, `O` flips orthographic / perspective, `S` toggles stills, `G` the guides. `promo previz strip` loads
it in headless Chrome (SwiftShader WebGL; set `PROMO_CHROME` to choose a binary) and cuts one PNG. No Chrome, or no WebGL: `--engine pil`
draws the same wireframes with Pillow (`render_pil`), which is also what the unit tests use. `templates/previz/sample/scene.json` is a
hand-written scene to try the viewer on.

## Gates

* `promo flow advance` from previz needs a built scene in step with its source and a strip of the current scene hash.
* `promo flow frames` (keyframes) is refused while the strip is missing or stale.
* `promo build` / `promo preview` of a designed plan above the quick look needs the strip (`promo build --look` does not).
* `promo check` `previz-ready`: PASS with a current strip; WARN on a 540p preview without one; FAIL above 540p, in a flow at keyframes or later.
* A person who handed over exact boxes can write `previz: {skip: "reason"}` in `promo.yaml`: the gate is a WARN that carries the reason.

## Rules it keeps

Previz never draws product UI: a panel is a labelled box, a still is only what the person supplied, plates are `ui: false` (the scene
linter refuses anything else), and nothing is generated or uploaded. Real footage still decides what the video shows (AGENTS.md rules 1-3).

## Alternatives taken

* The camera is a cinema-compatible box `(cx, cy, w)`, not free `position + lookAt`: a directed move can then be carried to `cinema` shot
  `cam` keys exactly. Perspective shots add depth through panel `z` and the lateral parallax drift.
* Designed panel shots keep the cinema `cam` as a crop into the still (`panel.crop`) and lock the world camera, because that is what
  `cinema.py` does; previz `apply` folds the world camera and the crop back into one `cam`.
* `pane3d.py` (final PIL perspective panes) is not reused for drawing: it renders pixels, previz only needs rectangles. The two share the
  idea (panel on a plane, perspective camera), not code.
* A Pillow wireframe fallback instead of making Chrome a hard dependency; the Chrome strip is the default.
* The scene lives in `previz/` in the project, not under `flow/boards`, so thin-prompt projects (no flow) use the same files. A flow with
  several picked stories gets `previz/<story>/`.
