# capture/: the capture-script contract

A capture script records real product footage for a promo project and hands it to the pipeline through the **footage manifest**.
This directory holds only the contract. Product-specific capture scripts live with the project that uses them (for example
`<projects-dir>/<name>/capture/` or a shared `<projects-dir>/<product>-shared/capture/`), never in this repo.
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
| `lib` | launch the browser, open the app at the pinned commit with seeded state, install the paused clock, seed `Math.random`, inject capture-only CSS (hide toasts, hide figures that must not show) |
| `rec` | recorder: step the paused clock 1/60 s per frame, seek animations to virtual time, grab frames (optionally a pre-framed CSS clip rect), resume after a crash from frames on disk, encode the lossless master after the browser closes |
| `shots` | one function per shot id: drive the real UI (real clicks and typing), hold for the dwell, return; record each take's params (URL, injected CSS, cursor overlay) in a sidecar `<clip>.meta.json` |
| `register` | read the sidecars and call `promo footage add` per take (`--dry-run` prints the commands and writes nothing) |

## Checklist before handing off
- [ ] Captured from the pinned app commit; the full SHA is recorded on every take.
- [ ] 3840x2160 (DPR 2) or the DPR is flagged; 60 fps; sound off; dwell of ~1 s before and ~2 s after the action.
- [ ] No notifications, personal data, API keys, cost figures or wrong-project data on screen; anything distracting is hidden by capture-only CSS and noted in `framing`, or the take is reshot.
- [ ] Every take registered with `promo footage add`; `promo footage verify --json` is ok.
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
| `dpr` | device pixel ratio of the capture (1 or 2) |
| `fps` | frames per second (null for stills) |
| `captured_at` | ISO 8601 time |
| `notes` | anything the editor needs to know |
| `demo` | true for demo-mode footage |

Unreferenced manifest entries are fine. After capturing, run `promo footage verify --json`, then point the shot's `source:` at the new id.
