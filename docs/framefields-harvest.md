# Reference: framefields (gatewai-dev)

https://github.com/gatewai-dev/framefields, read on 2026-10-20 at `4a26e73bc8331c77c14683880cf501b3e4096baf` (main, v2.3.2, 2026-10-19) over the GitHub API.
Nothing was cloned, installed or run. Compared with promo-reel at `fd1e5b6`.
Verdict: a source of two small, opt-in additions. As an engine or an effects library it duplicates what we have or breaks AGENTS.md rules 1-2.

## What it is
- A code-first video SDK: a TypeScript `Composition` (layer tree, keyframes, flex layout) rendered headless on native WebGPU (Dawn) in Node >= 22, no browser, encoded through FFmpeg (`README.md:21-25,91`; `plugins/framefields/skills/framefields-render/SKILL.md:12`).
- 74 packages under `nodes/` (effects, 3D/PBR, physics, GPU particles, procedural VFX, audio DSP, ONNX vision) and four agent skills in `plugins/framefields/skills/`.
- Licence: Apache-2.0 (`LICENCE`, `packages/framefields/package.json:6`; no NOTICE file). No fonts, music or video in the repo. Binary assets are a test `model.glb`, two `.cube` LUTs and brand/showcase images (`assets/`, `apps/renderer-service/examples/`); we would vendor none of them. Vision weights download lazily from pinned Hugging Face revisions with a SHA-256 check, claimed all Apache-2.0 (`packages/vision/src/model/registry.ts:3-12`). The Hugging Face tags of rtmdet-ins and RTMO-t say apache-2.0 (checked); the Selfie Segmenter repo is **not checked**.
- Young and beta: created 2026-10-02, 193 commits (189 by one author), about 30 releases in `packages/framefields/CHANGELOG.md`, beta badge (`README.md:12`). Expect API churn.
- Heavy install: skia-canvas, sharp, webgpu, onnxruntime-node, @napi-rs/webcodecs, @resvg/resvg-js (`packages/framefields/package.json:86-109`). skia-canvas needs an install script (`skills/framefields/SKILL.md:31`). The "about 12x slower" figure is its CPU fallback on Linux (`SKILL.md:24`); this Mac has Metal, but a headless render here is **not verified**.

## Already in promo-reel (do not rebuild)
- Verification, lint and frame grids: `promo check` (loudness, true peak, `footage-glitch`, caption zone), `generic_check.py` (`empty_fraction` :525, `static_runs` :588), `contact.py`, `previews.py`, `promo peek`, `docs/previz.md`. framefields' lint codes (`low_contrast_text`, `offscreen_layer`, `static_track`: `packages/compositions/src/program/lint.ts:178,208,226`) are covered by these.
- Springs and eases: `promo/motion.py` (opt-in `motion:` block) and the vendored `motionmaxxing`.
- Beat grid, SFX, audio DSP: `music.py`, `sfx.py`, `audiofx.py`, `mix.py`.
- Vision and depth: `depth.py` (Depth Anything), `prep.py` (mediapipe), `screentrack.py`.
- Grain, vignette, LUT, bloom: `grade.py:36` (`protect_ui`), `editor.py:84`. Never on UI pixels.
- Code-made motion films: vendored `cinetic` (Remotion/HyperFrames) and `motionmaxxing`.
- Draft player with timeline pins `{id, at_s, scene, text, by}`: `mods/promo-flow`, `promo/flow.py:1575`.

## Take (2 items, both opt-in, no default dependency)
1. **`skills/framefields-plates`: a helper skill, no Python code.** Deterministic, free, offline UI-free plates (aurora, smoke, particles, 3D gradients, wipes) as an alternative to paid, non-repeatable generative plates. We have no shader or noise-field facility. The skill would say: check Node >= 22, install framefields in a scratch dir outside the repo (never in `pyproject.toml`), write a text-free, logo-free, screen-free `film.ts`, look at a frame grid, render, then `promo gen register out.mp4 -p promo.yaml --id ID --provider local:framefields --prompt "<film.ts + sha>" --shots NN` (`promo/genvideo.py:7`). The clip carries `generated:`, so `generated-plates` (FAIL on a UI shot) and `generated-review` (WARN) still apply (`genvideo.py:410-412`). Same pattern as `depth.py:12-13` (`local:depth-parallax`).
   - Router: `primary: false`, phrase triggers only (mesh-avatar precedent), one golden brief. `tests/test_skill_routing.py` asserts exact helper lists, so it needs updating.
   - Cost: 0 default dependencies, 0 render-time change. Scope strictly to plates; text, cards and UI stay with `cinetic` / promo-reel.
   - Trial first on a branch: one 4 s plate in a scratch dir, not landed until the person has seen it.
2. **Spot pins in the draft player.** framefields' preview notes keep the spot as fractions (`x`, `y`, optional `w`, `h`) plus a frame image with the spot marked (`packages/framefields/src/preview/notes.ts:12-37`; render `SKILL.md:134`). Our pins hold a time and words only, so "this logo is too small" cannot say where. Add an optional `spot: {x, y, w?, h?}` set by clicking or dragging the paused frame.
   - Files: `mods/promo-flow/app.js`, `logic.js` (+ its test), the pins action in `promo/flow.py`, tests. No dependencies.
   - Cost: moderate UI work; needs desktop and mobile screenshots and a written design critique of the schema before building. How `roundbrief.py` / `flowcheck.py` would use the spot is **not checked**.

## Skip, and why
- framefields as our renderer: Node >= 22, WebGPU and six native packages replace numpy/Pillow/ffmpeg, break the legacy-identical maths (`render.py:1-8`) and the `shot_digest` cache (`cli.py:80`), and add nothing to real-footage shots.
- Effects and styles on footage (VHS, CRT, glitch, datamosh, LUT, grain): on UI pixels this is rule 2 (`spec.py:20` forbidden keys); on plates `grade.py` already covers it.
- Smart re-framing and on-device vision (`framefields-effects/SKILL.md:235-246`): product UI has no people or objects to follow, and we have depth, mediapipe and `screentrack.py`.
- Audio DSP, procedural SFX, BeatGrid, verification ladder, live preview: present (above).
- Vendoring its four skills wholesale: duplicates `cinetic` and `motionmaxxing`, adds router noise.
- Lottie, physics, RTL text, the RunPod/Docker render worker: only reachable through item 1; the worker is off-box.

## Rules kept
Plates are `ui: false` and `generated:` (rule 1 carve-out). Nothing edits UI pixels (rule 2). No caption describes a plate as the product (rule 3). No audio is added without an `assets.yaml` licence (rule 4). Nothing is published (rule 5).

## Open questions
1. Trial item 1 (one 4 s plate)? It needs `npm install framefields` in a scratch dir and a WebGPU render on this Mac.
2. Is item 2 worth a UI change now?
