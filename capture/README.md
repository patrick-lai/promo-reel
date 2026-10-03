# capture/: the capture-script contract

The product repo (commission-ai) will later PR its capture scripts into `capture/<product>/` here (e.g. `capture/commission-ai/`).
A capture script records real app footage for a promo project and hands it to the pipeline through the **footage manifest**.
Nothing in here may edit UI pixels, and no media is ever committed (no Git LFS either).

## Inputs
- A shot list or shot ids (e.g. `05 06 10`) from `projects/<name>/docs/` or the spec's `shots:`.
- The product **app commit** (full 40-char SHA) to capture from, ideally a clean detached worktree with no app changes.
- The project: `projects/<name>/` (its `promo.yaml`, `footage/manifest.yaml`, `footage/manifest.md`).

## Recording requirements
- Headless browser (Playwright), deterministic: Playwright clock paused and stepped per frame, CSS/WAAPI animations seeked to
  virtual time, `Math.random` seeded, fixed viewport (1920x1080 CSS px).
- **DPR 2, 60 fps, 3840x2160 preferred.** DPR 1 footage is allowed but gets a soft-upscale WARN when a shot pushes in more than 1.5x.
- Lossless or near-lossless master (`.mov`, H.264 `-qp 0`, yuv444p), sound off. Dark theme unless the brief says otherwise.
- Locked framing, 1 s handles before/after the beat. Demo mode is fine but must be flagged (`demo: true`); the check gate reports it.
- **Never edit UI pixels** (no paint-out, inpaint, masking of app UI in post). If something in the UI is wrong, fix the demo state or
  reshoot. Capture-only overlays (e.g. a cursor arrow because headless Chrome draws none) must be recorded in `notes`/`framing`.
- Record the **app commit and URL params** (`?demo=promo&...`, clock/seed, start offsets) for every take.

## Outputs
1. Media written to a box path **outside git** (e.g. `/workspace/videos/<project>/footage/<id>.mov`).
2. An entry in `projects/<name>/footage/manifest.yaml`: either `promo footage add` (computes sha256, probes resolution/fps) or write the same schema:
   ```
   promo -p projects/<name>/promo.yaml footage add /abs/path/shot-05.mov --id shot-05-v2 --shots 05 \
         --commit <full sha> --capture '?demo=promo&startMs=5600' --framing '1920x1080 CSS at DPR 2, rail crop later' --dpr 2 --demo
   ```
3. A human line in `projects/<name>/footage/manifest.md` (`footage add` regenerates the table there; add caveats in prose).
4. Nothing else in git: scripts, manifest, notes only.

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
