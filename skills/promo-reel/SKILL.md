---
name: promo-reel
description: Make or update a product promo / demo video from real app footage with the promo-reel repo (declarative promo.yaml, beat-locked edit, music + SFX + VO mix, QA gates). Use when asked to build, re-cut, caption, re-capture or check a promo reel, hero video or demo video.
---

# promo-reel

Everything lives in `projects/<name>/` (promo.yaml, assets.yaml, footage/manifest.yaml, shots.py plugin). Run commands from the repo root:
`promo -p projects/<name>/promo.yaml <cmd>` (venv python: `python -m promo ...`).

## Workflow
1. **Brief**: audience, length, claims, tone. Only claims the footage shows. Write it in `projects/<name>/docs/`.
2. **Shot list**: one line per shot with beats (BPM grid), what the UI shows, caption (short: fits the 608 px 9:16-safe column at 32 px, ~35 chars), SFX/VO. Cuts on beats.
3. **Capture handoff**: give the capturing agent the shot ids + app commit; they follow `capture/README.md` and register each take with
   `promo footage add` (sha256, commit, URL params, dpr). Reference clips by id; never by path.
4. **Spec**: `promo new <name>` scaffolds `projects/<name>/`. Fill `promo.yaml` (timeline, shots, overlays, sfx, vo, mix, qa) and
   `assets.yaml` (music/vo/sfx/font with licence + source_url). Custom shot types go in the project `shots.py` via `@shot_type`.
5. **Build**: `promo build` (idempotent; only changed shots re-render). Iterate on one shot with `promo shot 05`, look with `promo segpeek 05`.
6. **Check**: `promo check` (exit 1 on FAIL). Fix FAILs; read WARNs (soft upscale, demo footage, short labels) and decide.
7. **Review**: open `out/<name>-1080-contact.png` and the mp4. A human watches every frame that has text, captions or pushes.
8. **Deliver**: only after human approval. Re-render at 4K with `--scale 2` if asked. Never publish or upload on your own.

## CLI cheat-sheet
- `promo status [--json]` what is up-to-date / stale / missing; `promo timeline`, `promo assets`, `promo footage list|verify|add`
- `promo build [--shots 05 06] [--force] [--scale 2]`; `promo shot <id...>`; `promo sfx|vo|music|events|mix|assemble|contact`
- `promo check [--json]`; `promo compare <ref.mp4> [--json]` (per-shot PSNR + audio diff vs a reference)
- `promo peek <clip-id> <t> [x0 y0 x1 y1]`, `promo segpeek <shot> [t...]`, `promo mpeek out.png clip:t[:box] ...` (output in build/peek/)
- `--json` prints only JSON on stdout (always has `ok`), logs go to stderr. `promo fetch` downloads licensed assets (sha256 checked).

## Team rules
- **Real footage only.** No invented UI, no generated screens, no stock "app" shots.
- **Never edit the app's UI in post** (no paint-out, inpaint, masking). The spec lint rejects `debubble`/`paint_out`/`inpaint`/`ui_edit`. Reshoot instead.
- **No invented claims**: captions and VO must match what the frame shows (8 tasks = 8 tickets on screen).
- **Licensed audio only**, declared in `assets.yaml` with licence + source_url. `promo build/mix/check` refuse otherwise.
- **Footage is never committed** (no LFS). Provenance lives in `footage/manifest.yaml`; a sha256 mismatch is a stop, not a warning.
- Captions hold >= 2.0 s inside the safe zone; no per-caption overrides to make the gate pass: retime the caption.
- **A human approves before anything is published.**
- Render one shot at a time (ffmpeg `-threads 2`); never two renders at once. No git commit/push unless asked.

## Needs human judgement
Story and claims, caption wording, whether a push-in is soft, whether demo-mode UI is acceptable for the audience, music choice and
licence reading, VO tone, the final watch-through, and publishing. Agents prepare and check; people sign off.
