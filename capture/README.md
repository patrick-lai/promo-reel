# capture/: the capture-script contract

A capture script records real product footage for a promo project and hands it to the pipeline through the **footage manifest**.
This directory holds the contract and the shared, paint-safe capture kit (`capture/lib/`). Product take scripts live in
`capture/<product>/` (e.g. `capture/commission-ai/`) or with the project that uses them (`<projects-dir>/<name>/capture/`).
Nothing a capture script does may edit UI pixels, and no media is ever committed (no Git LFS either).

## Inputs
- A shot list or shot ids (e.g. `05 06 10`) from the project's `docs/` or the spec's `shots:`.
- The product **app commit** (full 40-char SHA) to capture from, ideally a clean detached worktree with no app changes.
- The project: `<projects-dir>/<name>/` (its `promo.yaml`, `footage/manifest.yaml`, `footage/manifest.md`).

## Recording requirements
- Headless browser (e.g. Playwright), deterministic: clock paused and stepped per frame, CSS/WAAPI animations seeked to
  virtual time, `Math.random` seeded, fixed viewport (1920x1080 CSS px).
- **DPR 2, 60 fps, 3840x2160 preferred.** DPR 1 footage is allowed but gets a soft-upscale WARN when a shot pushes in more than 1.5x.
- Lossless or near-lossless master (`.mov`, H.264 `-qp 0`, yuv444p), sound off. Dark theme unless the brief says otherwise.
- Locked framing, 1 s handles before/after the beat. Demo mode is fine but must be flagged (`demo: true`); the check gate reports it.
- **Never edit UI pixels** (no paint-out, inpaint, masking of app UI in post). If something in the UI is wrong, fix the demo state or
  reshoot. Capture-only overlays (e.g. a cursor arrow because headless Chrome draws none) must be recorded in `notes`/`framing`.
- Record the **app commit and URL params** (demo flags, clock/seed, start offsets) for every take.

## Paint-safe capture (read this before writing a recorder)
A headless-browser screenshot can be taken before the compositor has finished painting the frame. The result is a half-painted
frame: tiles of a panel's background missing so the layer behind shows through, a header gone for one frame. In a recording that
is a one-frame glitch, and it is invisible until someone watches the draft. Measured on the CommissionAI task drawer (Oct 2026):
with screenshots rescaled by CDP (`clip.scale` 4 on a DPR 2 page) about 1 first capture in 3 was half-painted, and the page kept
flickering between painted and half-painted for over 350 ms, because every rescaled screenshot re-rasterises the whole page.

`capture/lib/` prevents it; use it instead of a hand-rolled recorder:
- `browser.mjs`: `launch()` (GPU raster by default, `CAPTURE_GL=swiftshader` for boxes without one) and `open()` (viewport,
  dpr, paused clock, capture-only CSS, seeded `Math.random`).
- `recorder.mjs`: `Recorder`. Two rules:
  1. **Never rescale a screenshot.** Shots are taken at the page's own device pixel ratio. To get a 3120 px picture of a
     780 css px clip, open the page with `dpr: 4`. A `clip.scale` above the page's dpr throws with that advice.
  2. **Keep a frame only when it is settled:** `STABLE_N` (default 3) consecutive captures must be byte-identical, with a short
     back-off. Frames that never settle are listed in the take's `<name>.meta.json` (`stable.unsettled`) and logged as a WARN.
- `capture/commission-ai/app.mjs` shows the app layer (saved prefs, CSS snippets, first-run dialogs);
  `capture/commission-ai/drawer-pay103.mjs` is a complete take script.

Independent check: `promo footage add` scans every capture for one-frame glitches (a frame that differs from both neighbours
while they match each other) and records them as `glitches:`; `promo footage scan [ids]` re-runs it; `promo check` fails
`footage-glitch` while a referenced clip has any. The fix is a re-take, never a pixel edit (rule 2). A reviewed false positive
(a real one-frame flash in the product) goes in the clip's `glitch_ok: [frame, ...]`.

## Outputs
1. Media written to a path **outside git** (e.g. `<footage-dir>/<id>.mov`); every machine-specific path comes from an env var or CLI arg, never hardcoded.
2. An entry in `<project>/footage/manifest.yaml`: either `promo footage add` (computes sha256, probes resolution/fps) or write the same schema:
   ```
   promo -p <project>/promo.yaml footage add /abs/path/shot-05.mov --id shot-05-v2 --shots 05 \
         --commit <full sha> --capture '<URL params, clock/seed>' --framing '1920x1080 CSS at DPR 2, rail crop later' --dpr 2 [--demo]
   ```
3. A human line in `<project>/footage/manifest.md` (`footage add` regenerates the table there; add caveats in prose).
4. Nothing else in git: scripts, manifest, notes only.

## Skeleton of a capture script set
A small set of files is enough; names are suggestions.
| file | job |
|---|---|
| `capture/lib/browser.mjs` | launch the browser, open the app at the pinned commit with seeded state, install the paused clock, seed `Math.random`, inject capture-only CSS (hide toasts, hide figures that must not show) |
| `capture/lib/recorder.mjs` | step the paused clock 1/60 s per frame, seek animations to virtual time, grab settled frames at native dpr (optionally a pre-framed CSS clip rect), resume after a crash from frames on disk, encode the lossless master after the browser closes |
| `app` | the product layer: saved prefs, capture-only CSS snippets, first-run dialogs (`capture/commission-ai/app.mjs`) |
| `shots` | one function per shot id: drive the real UI (real clicks and typing), hold for the dwell, return; record each take's params (URL, injected CSS, cursor overlay) in a sidecar `<clip>.meta.json` |
| `register` | read the sidecars and call `promo footage add` per take (`--dry-run` prints the commands and writes nothing) |

## Checklist before handing off
- [ ] Captured from the pinned app commit; the full SHA is recorded on every take.
- [ ] 3840x2160 (DPR 2) or the DPR is flagged; 60 fps; sound off; dwell of ~1 s before and ~2 s after the action.
- [ ] No notifications, personal data, API keys, cost figures or wrong-project data on screen; anything distracting is hidden by capture-only CSS and noted in `framing`, or the take is reshot.
- [ ] Recorded with `capture/lib/recorder.mjs` (or the same two rules); no take logged unsettled frames.
- [ ] Every take registered with `promo footage add`; `promo footage verify --json` is ok and `promo footage scan` is clean.
- [ ] Demo-mode takes carry `demo: true`; cursor overlays and injected CSS are written in `capture` / `framing` / `notes`.
- [ ] No media, frame caches or logs staged in git.

## Manifest schema (`footage/manifest.yaml`, `clips:` list)
| key | meaning |
|---|---|
| `id` | file key that shots reference (`source: shot-10-v1080`), unique |
| `shots` | shot ids that use the clip |
| `path` | ABSOLUTE path on the box; `${VAR:-default}` expansion allowed |
| `sha256` | content hash; `promo build/shot/check` fail on mismatch or missing file |
| `app_commit` | full commit SHA of the product the take was shot on (`unknown` if truly unknown) |
| `capture` | URL / params, clock + seed notes |
| `framing` | viewport, in-app zoom, crop notes |
| `resolution` | `WxH` of the file |
| `dpr` | device pixel ratio of the capture (1, 2, or higher for a small clip rendered natively at 4K) |
| `fps` | frames per second (null for stills) |
| `captured_at` | ISO 8601 time |
| `notes` | anything the editor needs to know |
| `demo` | true for demo-mode footage |
| `glitches` | one-frame paint glitches found by `promo footage add` (frame numbers); re-take the clip |
| `glitch_ok` | frames reviewed as real product behaviour, not glitches; kept while the sha256 is unchanged |

Unreferenced manifest entries are fine. After capturing, run `promo footage verify --json`, then point the shot's `source:` at the new id.
