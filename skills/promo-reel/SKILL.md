---
name: promo-reel
description: Make or update a product promo / demo video from real app footage with the promo-reel repo (declarative promo.yaml, beat-locked edit, music + SFX + VO mix, QA gates). Use when asked to build, re-cut, caption, re-capture or check a promo reel, hero video or demo video.
---

# promo-reel

Everything lives in `projects/<name>/` (promo.yaml, assets.yaml, footage/manifest.yaml, shots.py plugin). Run commands from the repo root:
`promo -p projects/<name>/promo.yaml <cmd>` (venv python: `python -m promo ...`).

## Pick a style preset first (do not write your own renderer)
Every look is a **style preset**: pacing rules, a caption/card band, typography, transitions and the `promo check` gates
for them. `promo styles` lists them. Scaffold with the one that matches the brief:
- `promo new <name> --style hero`: calm product hero (VO, dark pills in the 9:16-safe zone, cuts on beats). Example: `projects/commission-ai-hero/`.
- `promo new <name> --style anime-opening`: kinetic anime-opening cards on real footage. Example: `projects/commission-ai-anime/`.
- `promo new <name> --style livestream`: talk-show/livestream composite (long holds, lower-left chyron, no flashes).

If the brief says "anime", "opening", "kinetic titles", "J-rock", "speed lines" or "title cards", it is **anime-opening**:
- `timeline: {grid: <music JSON>, beats: N}` loads tempo, bars and markers from the music analysis JSON; `promo grid` prints the bar table. Plan cuts on bar lines; `qa.cut_markers: [intro_hit, ...]` must land on cuts.
- Shots are `type: anime`. Set `ui: true|false` on every shot. UI shots hold >= 1 bar and are framed above the band (`layout: band`; `fit: contain` keeps a 16:9 crop); text-free shots (scenery, robots) may hold 1/2 bar and run full-bleed.
- Words go in `cards: [{row: title|sub|tag, text: ..., bars: [a, b]}]`: held >= 1 bar, start on a bar line, all in ONE fixed lower-third band (no per-card positions). Full-bleed UI shots must list `ui_text` rects (source coords) and no card may cover them.
- Flashes / speed lines: `fx_in` / `fx_out` (`kind: flash|speed_lines`, <= 6 frames) only, i.e. at a cut. On UI shots they draw in the band only; <= 3 flashes per second.
- Numbers on cards come from `claims` tables (`text_from: claims.<table>`), selected by what the footage manifest says is legible; a literal number needs `evidence:`.
  A softened fallback row that is not signed-off copy carries `confirm: Marketing`: check WARNs and the critique pack flags it.
- App text a card names (a chip label, a reviewer line) goes in the shot's `named: [{name, box: [x0, y0, x1, y1]}]` (source px).
  Gate `named` FAILs under 18 px cap height at 1080p (measured at the shot head, middle and last frame); `named-upscale` WARNs
  when the effective scale is > 1.0 (push-in on a 1x take: swap in the DPR 2 take). Same contract as the talk show.
  `fit: contain` + `aspect: 1.6` frames one panel without a neighbour sliver; `pillar_fill: brand` fills the pillarbox with the
  opening's night-sky brand background so a narrow crop reads as a deliberate panel.
- A shot that is not captured yet is `placeholder: {id, label, expects}` (a labelled slate). Swapping in the real take = replace it with `source:` + `cam:`.
Need something the preset can't do? Extend the preset or the `anime` shot type in `promo/` (with a test), not a one-off renderer in the project.

## Workflow
1. **Brief**: audience, length, claims, tone. Only claims the footage shows. Write it in `projects/<name>/docs/`.
2. **Shot list**: one line per shot with beats (BPM grid), what the UI shows, caption (short: fits the 608 px 9:16-safe column at 32 px, ~35 chars), SFX/VO. Cuts on beats.
3. **Capture handoff**: give the capturing agent the shot ids + app commit; they follow `capture/README.md` and register each take with
   `promo footage add` (sha256, commit, URL params, dpr). Reference clips by id; never by path.
4. **Spec**: `promo new <name>` scaffolds `projects/<name>/`. Fill `promo.yaml` (timeline, shots, overlays, sfx, vo, mix, qa) and
   `assets.yaml` (music/vo/sfx/font with licence + source_url). Custom shot types go in the project `shots.py` via `@shot_type`.
5. **Build**: `promo build` (idempotent; only changed shots re-render). Iterate on one shot with `promo shot 05`, look with `promo segpeek 05`.
   Heavy steps (build/shot/sfx/music/mix/assemble/contact/check) take the box-wide lock `/tmp/commission-ai-cargo.lock`
   themselves (`promo/lock.py`) and wait while a Commission-ai cargo test gate holds it. Run them niced (`nice -n 10 python -m promo ...`);
   do not wrap them in another `flock` and never SIGCONT a paused render.
6. **Check**: `promo check` (exit 1 on FAIL). Fix FAILs; read WARNs (soft upscale, demo footage, short labels) and decide.
7. **Review**: open `out/<name>-1080-contact.png` and the mp4. A human watches every frame that has text, captions or pushes.
   For the final reviewer model, run `promo critique-pack projects/<name>` and hand over the folder it prints
   (`out/critique-pack/`: BRIEF.md with the rubric + hard rules, stills with size sidecars, contact sheet, copy, footage
   manifest.md, Zen's reviews, full check output, VO transcript). Do not run or impersonate the reviewer yourself.
   Per-project sources: `critique: {copy: [...], reviews: [...], footage_md: [...]}` in promo.yaml (defaults by kind:
   hero = captions-v1-cut.md + vo-script-v1.md; anime / talk show = scripts-3-directions-v1.md; talk show also gets Zen's
   talkshow-preview REVIEW.md).
8. **Deliver**: only after human approval. Re-render at 4K with `--scale 2` if asked. Never publish or upload on your own.

## CLI cheat-sheet
- `promo styles`; `promo new <name> --style hero|anime-opening|livestream`; `promo grid` (bars, beats, markers of `timeline.grid`)
- `promo status [--json]` what is up-to-date / stale / missing; `promo timeline`, `promo assets`, `promo footage list|verify|add`
- `promo build [--shots 05 06] [--force] [--scale 2]`; `promo shot <id...>`; `promo sfx|vo|music|events|mix|assemble|contact`
- `promo critique-pack [projects/<name>] [--out DIR] [--no-check] [--video]` (review folder for a reviewer model; holds the lock)
- `promo check [--json]`; `promo compare <ref.mp4> [--json]` (per-shot PSNR + audio diff vs a reference)
- `promo peek <clip-id> <t> [x0 y0 x1 y1]`, `promo segpeek <shot> [t...]`, `promo mpeek out.png clip:t[:box] ...` (output in build/peek/)
- `promo live2d fetch|render|lag`: offline Live2D hosts for the `livestream` shot type (hosts on one side, screen >= 55 %,
  chat <= 4 lines of host asides only, neutral EP tag, no LIVE/viewer counts, keep-clear rects, `live2d_credits` end card).
  Only Live2D Original Characters; notice + licence rules in `docs/live2d-licences.md`. Heavy renders hold
  `/tmp/commission-ai-cargo.lock` (shared with Commission-ai cargo test gates); `--debug` draws keep-clear outlines.
- `--json` prints only JSON on stdout (always has `ok`), logs go to stderr. `promo fetch` downloads licensed assets (sha256 checked).

## Team rules
- **Real footage only.** No invented UI, no generated screens, no stock "app" shots.
- **Never edit the app's UI in post** (no paint-out, inpaint, masking). The spec lint rejects `debubble`/`paint_out`/`inpaint`/`ui_edit`. Reshoot instead.
- **No invented claims**: captions and VO must match what the frame shows (8 tasks = 8 tickets on screen).
- **Licensed audio only**, declared in `assets.yaml` with licence + source_url. `promo build/mix/check` refuse otherwise.
- **Footage is never committed** (no LFS). Provenance lives in `footage/manifest.yaml`; a sha256 mismatch is a stop, not a warning.
- Captions hold >= 2.0 s inside the safe zone (hero); anime cards hold >= 1 bar in the fixed band. No per-caption overrides to make a gate pass: retime it.
- **A human approves before anything is published.**
- Render one shot at a time (ffmpeg `-threads 2`); never two renders at once. No git commit/push unless asked.

## Needs human judgement
Story and claims, caption wording, whether a push-in is soft, whether demo-mode UI is acceptable for the audience, music choice and
licence reading, VO tone, the final watch-through, and publishing. Agents prepare and check; people sign off.
