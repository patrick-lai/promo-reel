# capture/commission-ai: deterministic commission-ai promo captures (v1-1080 pass)

Scripts that recorded the `commission-ai-hero` v1 footage from commission-ai `main` @ `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (shot-12 retake: main @ `4ccfa5be580eb3dbbaf8cb1138b0e4f55f544636`)
(`?demo=promo` scenario from commission-ai PR #86, plus `?demo=1&still=1` for the talk-show DAG). They follow `capture/README.md`:
real app only, no UI pixel edits, media written outside git, every take registered with `promo footage add`.

## Setup (on the box)
1. Detached worktree of the app commit, no app changes: `git -C <commission-ai> worktree add --detach /workspace/wt-promo-v1-1004 <sha>`.
2. `cd clients/web && pnpm install --frozen-lockfile && npx vite build && npx vite preview --port 6460 --strictPort --host 127.0.0.1`.
3. Point the scripts at your machine with env vars (see **Configuration**); nothing machine-specific is hardcoded.
   Chrome: system Chrome/Chromium with SwiftShader WebGL (no GPU needed).

## Configuration
All paths are env vars / CLI args with defaults; the repo root is always derived from the script location.

| setting | used by | default |
|---|---|---|
| `PLAYWRIGHT_MODULE` | `lib.mjs` | path to `@playwright/test/index.mjs` (or a package name). Else `$APP_DIR/clients/web/node_modules/@playwright/test/index.mjs` when `APP_DIR` is set (e.g. `APP_DIR=/workspace/wt-promo-v1-1004`), else plain `@playwright/test` |
| `CHROME_PATH` | `lib.mjs` | `/opt/google/chrome/chrome` if present, else Playwright's bundled Chromium |
| `BASE`, `COMMIT` | `lib.mjs` | `http://127.0.0.1:6460/`, `4a427fc0...` |
| `FOOTAGE_DIR` | `rec.mjs`, `enc.sh`, `mk_manifest.py` / `register.py` (`--footage-dir` overrides) | `<repo>/../videos/commission-ai-promo/footage/v1-1080` (outside git) |
| `--manifest-md` | `mk_manifest.py` | `<footage-dir>/../manifest.md` |
| `PROMO_PYTHON` / `--python` | `register.py` | the interpreter running `register.py` (use the promo venv's python) |
| `QUEUE`, `QUEUE_MEM_MB`, `QUEUE_MEM_WAIT` | `queue.sh` | `queue.txt` (git-ignored; start from `queue.example.txt`), 5500 MiB, 3600 s |

## Capture truth (per clip)
`lib.mjs` injects `cursor:none` on every take plus the named capture CSS passed to `open()`: `NO_TOASTS` (Sonner toaster hidden; every
`pshots.mjs` take) and `HIDE_MONEY` (wallet/mora figures hidden; `w14b.mjs`). `pshots.mjs` shot 10 adds the capture-overlay cursor
(`markCursorOverlay`). `rec.mjs` writes these flags with the take's params to `.frames/<clip>/meta.json` and, after encoding, to
`<footage>/<clip>.meta.json`; `register.py` reads that (falling back to `inject` in `notes.json` for older takes) and records it in
manifest.yaml `capture` (HIDE_MONEY and the overlay also in `framing`).

## Frame cache
`.frames/<clip>/` is only reused (crash resume) when its `meta.json` params hash (clip name, frame count, start frame, URL, commit,
viewport, DPR, clip rect, injected CSS, cursor overlay) matches the new take; otherwise (or with no `meta.json`) the folder is wiped first.

## Files
| file | what |
|---|---|
| `lib.mjs` | launch Chrome, open a page with seeded prefs (Dark theme, intro/tour done), optional Playwright clock install/pause, `Math.random` seed, capture-only CSS |
| `rec.mjs` | `Recorder`: steps the paused Playwright clock 1/60 s per frame, seeks CSS/WAAPI animations to virtual time, CDP screenshots (optional `clip` = pre-framed CSS rect), resumes after crashes from frames on disk; `flush()` encodes after the browser is closed (H.264 `-qp 0` yuv444p `.mov` + crf 16 preview + poster) |
| `pshots.mjs` | app shots from `?demo=promo`: `08` (PAY-104 drawer chips), `10` / `10b` (PAY-106 Needs you + real Allow once click, DPR1 full / DPR2 1.5x clip), `12` / `12b` (reviewer approval thread), `04`, `05`, `06` (+ shot-07 card stills), `11` (+ `16a`, all-8 and list takes), `15pr` (PAY-110 PR card), `03c` (composer typing, Access switched off Bypass via the real menu; optional real send), `11c` (zoomed/panned run-complete board under the header), `04p` (promo plan DAG), `talk-dag` (`?demo=1&still=1` board DAG) |
| `wshots.mjs` | standalone Workshop page `?demo=promo&view=workshop&workshop=fast&workshopHour=HH:MM` (note: `workshopHour` must be `HH:MM`; a bare `22` is ignored) |
| `w14b.mjs` | in-app Workshop full screen, Outside -> demo control "Finish 5 rooms" -> "now a Street" notice -> Street. Env: `HOUR`, `OUT`, `SECS`, `STREET_AT`, `CLOSE_EARNED=1` (close the '2 achievements earned' toast with its own close button, real mouse), `REEXPAND=1` (re-click Expand workshop after that close collapses it) |
| `enc.sh` | `enc.sh NAME POSTER [DIR] [START] [FRAMES]`: hand-encode a recorded `.frames/<name>` dir with the same settings as `rec.mjs` (`-start_number`, `-frames:v`, aspect-preserving scale + pad; used when a session died after recording) |
| `queue.sh` / `queue.example.txt` | one-capture-at-a-time queue with memory wait (`waitmem.sh MB SECONDS`, default 5500 / 3600) and 3 retries; a line failing all 3 goes to `logs/queue-failed.txt` and the queue exits 1. Your run list is `queue.txt` (git-ignored) |
| `bg.sh` | run a command detached with a log + pid file in `logs/` (creates `logs/` and `probe/`; both git-ignored, like `.frames/`) |
| `grid.sh` | contact grid of a clip at given times (used for the bubble / Blocked / blocker checks) |
| `mk_manifest.py`, `notes.json`, `capmeta.py` | writes `footage/v1-1080/manifest.md` (sha256, duration, fps, URL, beat, framing, injected CSS / cursor, Zen checks) |
| `register.py` | runs `promo footage add` for every clip in `notes.json` (`--dry-run` prints the commands and writes nothing) |

## Framing convention
`clip` takes keep the normal 1920x1080 CSS layout, render it at deviceScaleFactor 2 and capture a CSS rectangle scaled to
1920x1080 output (crisp text, pre-framed so the edit needs <= ~1.2x). For a 4K pass use the same CSS rect with DPR 4, or full frames at
1920x1080 CSS DPR 2. Each take's rect is in `framing` in `footage/manifest.yaml`.

## Env overrides
- `BASE`, `COMMIT` (lib.mjs): point at another preview server/commit. The shot-12 retake used a second worktree at main `4ccfa5be` (Z179) served on :6461 with `SUFFIX=-z179 node pshots.mjs 12b`.
- `CLIP='{"x":..,"y":..,"width":..,"height":..}'` + `OUT=name` for `08`, `05`, `03c`, `15pr` (e.g. `shot-16-prcard-tight`, `shot-08-dpr2`, `shot-05-rail`).
- `talk-dag`: `FULL=1 ZOOM=<target %> ID=<out> UNION=PAY-101,PAY-104,...` (real ctrl+wheel zoom, auto 16:9 clip around the union). Keep the target <= ~180%: higher zoom makes SwiftShader rendering stall.
- `03c`: `CHARF` (frames per typed char, 6 = 10 chars/s at 60 fps), `LEAD`, `TAIL`; `SEND=1` presses Enter `SENDGAP` frames after the last char (real send; under `pause=1` the demo answers with its generic no-board reply); `PANY`/`PANSTART`/`PANDUR` ease the crop's y to `PANY` after the send (a crop move only, so the sent message is in frame); `DRY=1 SEND=1` saves probe frames to `probe/`.
- `11c`: `ZOOMTO` (real ctrl+wheel zoom target, steps may overshoot), `TX`/`TY` (real wheel pan so the Landed column's top-left sits at that CSS point), `CLIP`, `OUT`. Used for shot-11-dpr2-r2/r3/r4/r4-wide.
- `04p`: promo plan-of-8 DAG hold (`T0`, `PAD`, `HEADS`, `OUT`, `FREEZE`).
- `11b`: run-complete holds only (all-8 cards, header counts, List view). The full-window DPR2 board renders at 5-10 s/frame, so the long landing take is impractical.

## Gotchas
- Full-viewport `Page.captureScreenshot` (and `page.screenshot`) can return a stale surface while the clock is paused; clipped captures (`rec.clip` / `clipShot`) force a fresh frame. Probe with clipped shots.

## Run
`cp queue.example.txt queue.txt` (edit it), `./bg.sh queue ./queue.sh`, or one shot: `node pshots.mjs 10b`, `node wshots.mjs shot-03-night 22:00 9`.
Then `python3 mk_manifest.py && <promo venv>/bin/python register.py --dry-run [clip-id ...]`, and again without `--dry-run`.
Tests: `python tests/test_core.py` from the repo root (covers `mk_manifest.py` and `register.py --dry-run`).
