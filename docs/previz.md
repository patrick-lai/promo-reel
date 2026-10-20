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

## Animatic: the cut against the beat

```bash
promo previz animatic                 # shots/<id>.previz.mp4 per shot + <name>.previz-animatic.mp4 + animatic.previz.json
promo previz animatic --shot 03       # re-render 03 even if unchanged
promo previz animatic --audio none    # auto (the built music bed, else a beat click) | click | music | none
promo previz shots                    # a promo.yaml shots: skeleton (beats + cam) for drafts
```

Each shot renders on its own (Pillow wireframes, the caption zone dashed, a minimap of the camera box, beat ticks with the downbeat
long and a flash as each beat lands, `PREVIZ · NOT FOOTAGE`, `UI STAND-IN` on panels), keyed by a digest of that shot's own content,
frame count, beat phase and the drawing code, never its start time. The run lists `rebuilt`, `kept` and `shifted` (only moved in time,
clip kept). A gap between shots becomes a red GAP slate and a note; overlapping shots are refused before anything renders. The joined
video is one re-encode cut to the exact frame count, so it runs as long as the timeline (a `promo new` spec: `timeline.beats`).

Sources: everything previz blocks out, plus a `promo new` / hand-written `promo.yaml` shot list: `beats` give the timing, `cam` the
camera box over the recording, captions sit in the style's caption zone, `text` / `lower_copy` / `title_bloom` are type boxes. A
UI shot is a fullscreen stand-in (a cinema UI shot a floating panel with `cam` as its crop), `ui: false` and cards are plates. That
scene is the spec's: change the shot in `promo.yaml` and re-run (`cam` / `panel` / `type` / `dur` nudges are refused there).

Per style (`PREVIZ_DEFAULTS`; `previz: {animatic: true|false, projection: ortho|persp}` in promo.yaml, or `animatic --require on|off`
for a flow without one, overrides):

| style | animatic in the flow | default blockout |
|---|---|---|
| horizon, anime-mv | required at the previz step | 2D (ortho) |
| cinematic-story | required at the previz step | 3D (persp: the panel floats in front of its backdrop) |
| every other style | opt-in | 2D (ortho) |

It plays in the Stage's Rough layout card, inside the one plan review (`assets-approved`): there is no new gate, and the scene hash the
approval covers is the one the animatic was cut from. After approval the keyframes read it for timing and camera only: each start /
end frame's prompt and to-do get the camera box (`previz.blocking`); nothing visual is handed on.

**Four review passes** (watch with sound; fix, re-run, the run says what it rebuilt):
1. Order: does the story read in this shot order with the sound off?
2. Timing: does each cut land on a beat or bar, is any shot shorter than the style's minimum, are there gaps?
3. Framing: does the camera box frame the thing the shot is about, does the move have a reason?
4. Words: is every caption inside the caption zone, short enough, held for 2 s or more?

Previz is never footage: file names carry `.previz.`, the MP4 comment and `animatic.previz.json` (`not_footage: true`) say so,
`promo footage add` refuses them and `promo check` `previz-not-footage` FAILs a manifest that points at one.

The idea of encoding a code scene frame by frame with its camera kept beside it comes from CodeVideoModel (Apache-2.0;
`templates/previz/vendor/codevideomodel/`, `docs/codevideomodel-harvest.md`).

## Gates

* `promo flow advance` from previz needs a built scene in step with its source and a strip of the current scene hash, and for the
  film styles an animatic of it.
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
