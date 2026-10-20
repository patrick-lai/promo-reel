# Reference: framefields (gatewai-dev)

https://github.com/gatewai-dev/framefields, read on 2026-10-20 at `4a26e73bc8331c77c14683880cf501b3e4096baf` (main, v2.3.2, 2026-10-19): API reads, then a shallow clone read with no install or build. Compared with promo-reel at `fd1e5b6`.
Rule used: skip an idea only where ours is actually better, or a rule or a missing use case blocks it. Otherwise harvest it.

## What it is
- A code-first video SDK: a TypeScript `Composition` rendered headless on native WebGPU (Dawn/Metal) in Node >= 22, encoded through FFmpeg (`README.md:21-25,91`; `plugins/framefields/skills/framefields-render/SKILL.md:12`). 74 packages in `nodes/`, four agent skills.
- Apache-2.0 (`LICENCE`, `packages/framefields/package.json:6`). No fonts, music or video in the repo. Vision weights download lazily from pinned Hugging Face revisions with a SHA-256 check (`packages/vision/src/model/registry.ts:3-12`); rtmdet-ins and RTMO-t are tagged apache-2.0 (checked), the Selfie Segmenter repo is **not checked**.
- Young, beta: created 2026-10-02, 193 commits (189 by one author), about 30 releases (`README.md:12`, `packages/framefields/CHANGELOG.md`). Expect API churn.
- Heavy install: skia-canvas, sharp, webgpu, onnxruntime-node, @napi-rs/webcodecs, @resvg/resvg-js (`packages/framefields/package.json:86-109`); skia-canvas needs an install script (`skills/framefields/SKILL.md:31`). The repo has no render-speed numbers; "12x slower" is its Linux CPU fallback only (`SKILL.md:24`).

## Ours vs theirs, area by area
| Area | Ours | Theirs | Verdict |
|---|---|---|---|
| Between-shot transitions | Hard concat (`assemble.py:105`); only in-shot flash/speed-lines (`shots/anime.py:346-370`) and plate fx in `mv`; "dissolves: not rendered by the engine yet" (`styles.py:139`) | 9 kinds: cut, crossfade, fadeThrough, push, slide, zoom, whip, wipe, iris (`packages/framefields/src/transitions.ts:76-223`) | **Theirs broader. Harvest crossfade + dip only** (item 3) |
| Output QA of the finished file | LUFS and true peak (`mix.py:68-100`), `static_runs`, `empty_fraction` (`generic_check.py:525,588`); no `blackdetect` / `silencedetect` / `freezedetect` / `astats` anywhere in `promo/`, `mods/`, `scripts/` (grep) | Black runs, frozen runs, silent runs, clipped samples (`packages/renderer/src/video-qa.ts:50-75`) | **Theirs covers more. Harvest** (item 1) |
| Looks and procedural plates | Small numpy set: lift/gamma/gain, vignette, bloom, grain, DoF (`grade.py:98-174`); no LUT, noise field, displacement or shader; particles only in `mv` (`shots/mv.py:124`) | About 74 GPU nodes: LUT, displacement, liquify, particles, procedural VFX, noise, blend modes (`nodes/`) | **Theirs far broader.** Rule 2 limits both to plates and backdrops, so harvest as plates (item 2), not a `grade.py` port |
| Text | PIL (`render.py:266-318`); per-word anims in cinema/horizon (`shots/cinema.py:434-465`); per-glyph only for lyrics. **RTL cannot work here**: Pillow 12.3.0 reports raqm, fribidi, harfbuzz all False | Slug GPU vector text, Arabic/Hebrew, `TextAnimator` presets (`framefields-compose/SKILL.md:87,138-164`; `examples/27_rtl_text`) | Theirs better for complex script only. Fix in ours if needed (Pillow with raqm); kinetic type is equal. **Your call** |
| SFX | 18 recipes synthesised from scratch, CC0 (`sfx.py:15`) | 5: whoosh, riser, impact, downshifter, glitch (`packages/framefields/src/audio/synth/sfx.ts:12`) | **Ours broader. Skip** |
| Mix and mastering | pyloudnorm loop plus 4x look-ahead limiter to -14 / -9 LUFS (`mix.py:68-100`) | Compressor, EQ, reverb, gate nodes; audio-reactive signals (`signals/audio.ts:18-28`) | **Ours covers delivery. Skip** |
| Camera and re-framing | `cam` keys, opt-in springs (`motion.py:77`); no auto-reframe | Smart framing follows tracked people/objects (`framefields-effects/SKILL.md:235-246`) | **Domain mismatch. Skip**: its models are people/COCO/selfie only (`registry.ts:73-173`), no screen UI |
| Vision | Depth Anything (`depth.py`), mediapipe (`prep.py`) | rtmdet-ins, RTMO, selfie matting | **Skip**, same reason |
| Renderer | CPU, per-frame PIL, 15-25 min per 60 s 1080 build (`AGENTS.md:137`); maths frozen (`render.py:1-8`) | GPU; speed **not measured** anywhere | Port would rewrite all 10 shot modules in `promo/shots/`. **Unknown speed: needs a spike** (question 2) |
| Authoring preview | Stills and 540p draft, no hot reload; draft player with time-only pins (`flow.py:1575`) | Browser player; notes keep a spot `x,y,w?,h?` and a marked frame (`preview/notes.ts:12-37`) | Take the **spot**, skip the player (item 4) |
| Lottie, physics, cloud render worker | none | present | **No use case / off-box**: the worker would ship real UI footage off this Mac. Skip |
| Its four skills | `cinetic`, `motionmaxxing` | API docs for framefields | Skip vendoring; the plates skill links the pinned upstream docs instead |

## Take, ranked (all opt-in, no new default dependency)
1. **Master QA gates.** `promo check` gains `black-frames`, `silent-gap` and `clipping` on the finished master using ffmpeg's `blackdetect`, `silencedetect` and `astats`, WARN first. Catches a render that produced a black run or dropped audio. One module, tests, no dependency, no render-time cost.
2. **`skills/framefields-plates`: helper skill, no Python.** UI-free plates (aurora, smoke, particles, glass, 3D gradients) rendered deterministically and free in a scratch dir outside the repo, then `promo gen register --provider local:framefields` (`genvideo.py:7`; same pattern as `depth.py:12-13`). `generated:` stays on the clip, so `generated-plates` and `generated-review` apply (`genvideo.py:410-412`). Router: `primary: false`, phrase triggers, `tests/test_skill_routing.py` updated. Trial one 4 s plate first on a branch.
3. **Crossfade and dip-to-colour between shots, built at assemble time** (not framefields code; only its vocabulary). A design critique ruled out per-shot handles: they break the frame-count assert (`assemble.py:101-102`), the shot digest (`cli.py:124`) and the beat-grid gate. The safe route: blend inside the existing final re-encode (`assemble.py:74-91`), replacing the last L frames of shot A with a blend against B's held boundary frame, so every segment keeps exactly `n` frames. L <= 12, off by default, enabled per style via `transitions.allowed`. About 7-9 files (`assemble.py`, `cli.py`, `styles.py`, `style_check.py`, spec lint, `editor.py`, EDL, tests); `render.py` is untouched. Start smaller: add `color` to the existing `fade` post key (`cli.py:29`). Whip, push, slide, zoom and iris are skipped: no motion blur, ethereal FAILs whip (`designed.py:986`), and `mv` already has iris/ink on plates. Unverified: the exact ffmpeg `xfade` frame count at offset 0, and whether a held boundary frame looks acceptable over live video.
4. **Spot pins** in the draft player: optional `spot: {x, y, w?, h?}` on a pin. Touches `mods/promo-flow` (`app.js`, `logic.js`), `promo/flow.py`, tests; needs desktop and mobile screenshots. How `roundbrief.py` / `flowcheck.py` would use it is **not checked**.

## Corrections to the first version of this note
- framefields' `low_contrast_text` lint (`packages/compositions/src/program/lint.ts:178`) is **not** covered by us: no contrast gate exists outside `lyrics.py:443`. Risk is small because captions sit on fixed pills.
- Transitions: 9 kinds including `cut`, not 8.

## Rules kept
Plates are `ui: false` and `generated:` (rule 1 carve-out). A transition blends whole frames at a cut and edits no UI pixel (rule 2; `critique.py:49` allows effects "between shots, at the cut"). No caption describes a plate as the product (rule 3). No audio is added without an `assets.yaml` licence (rule 4). Nothing is published (rule 5).

## Open questions
1. Do you need Arabic, Hebrew or other complex-script promos? Pillow here has no raqm, so they cannot render today; fixing that costs a system library, not framefields.
2. Is render time a pain worth a spike? One 4 s clip shot rendered both ways in a scratch dir, comparing wall time and pixels. It needs `npm install framefields` (install scripts, untrusted), so I will not run it without your go.
3. Order: 1 and 2 first (cheapest, no rule friction), then 3, then 4?
