# Harvest note: CodeVideoModel into `promo previz` (low-fidelity directing)

Upstream: https://github.com/code-video-model/CodeVideoModel, pinned at
**`404e03d67c2977b441622ce94411470bb84984a8`** (main, 2026-10-13). Read on 2026-10-20.

Goal: direct the film in cheap, editable code before any keyframe or draft costs money. Shapes and beats are enough; the picture
stays wireframe. This note is the proposal; the build lands on its own branch (`harvest/codevideomodel-previz`), nothing on main.

## What upstream does

An LLM agent writes a small three.js scene (`window.reconstruction.seek(t)`, `getCameraState()`) for a prompt, the pipeline renders it
with Playwright into a proxy MP4 plus a per-frame camera trajectory (`inference/render.py`), GPT-Image-2 paints a reference image of the
first frame (`cvm/reference.py`), and MiniMax-H3 video diffusion turns proxy + reference into the final clip (`cvm/video.py`). An edit
mode (`cvm/pair.py`) re-runs a variant against an anchor and refuses if the camera trajectory moved. The agent prompt
(`prompts/program_contract.md`) asks for four named refinement passes on a contact sheet before delivery.

The useful idea for us is the first half: **a deterministic code scene, rendered to a video and a camera record, is a cheap
directing artefact.** The second half (image + video generation of the subject) is what we do not want for product shots.

## Licence and terms

| Part | Terms | Our use |
|---|---|---|
| Code (`LICENSE`) | Apache-2.0 | Ideas and patterns ported, no file copied; `LICENSE` kept verbatim in `templates/previz/vendor/codevideomodel/` |
| `NOTICE` | **None at the pinned commit** (tree lists only `LICENSE`, `vendor/LICENSE.threejs`, `examples/LICENSES/*`) | Nothing to carry; VENDORED.md says so rather than inventing one |
| Example media (`examples/*`, 6 PNG + 6 MP4) | CC BY 4.0 (`examples/LICENSES/CC-BY-4.0.txt`) | Not vendored (no binary media) |
| `examples/LICENSES/CodeVideoBench-MIT.txt`, `THIRD_PARTY_NOTICES.md` | MIT / notices for the examples | Not vendored |
| three.js r160 (`vendor/`, twice more under `examples/`) | MIT | Not vendored: we already ship r160 in `templates/previz/vendor/` |
| MiniMax-H3 weights (`download_h3.py`, HF `MiniMaxAI/MiniMax-H3`, repo ~498 GB) | MiniMax H3 Community Licence: "Excluded Territories means the European Union, the United Kingdom, the Republic of Korea and the United States of America"; > USD 20M revenue needs written authorisation; "MiniMax H3" must be displayed | Skipped entirely |
| GPT-Image-2 (`cvm/reference.py`), OpenRouter judge (`cvm/evaluation.py`) | Paid APIs under the vendors' terms | Skipped |

## How its concepts map onto promo-reel (modules read before citing)

| Upstream | promo-reel today | Verdict |
|---|---|---|
| three.js proxy scene with `seek(t)` | `promo/previz.py` `layout()` + `templates/previz/viewer.js`: a JSON scene of wire boxes, one projection formula in Python and JS | Already ours. Keep. |
| Proxy MP4 (`inference/render.py` `render()`: seek determinism check, PNG pipe into one libx264 pass, contact sheet at fixed points) | `previz.strip()` / `render_pil()`: a PNG contact strip only, no video, no music | **Gap: build #1** |
| Camera trajectory export (`render.py` lines 111-149) and the pair camera lock (`cvm/pair.py` `prepare()`) | `previz.cinema_patches()` carries camera keys into designed cinema shots; flow keyframes (`flow.make_frames`) only check that a strip exists | **Gap: build #2** |
| Four refinement passes (`prompts/program_contract.md` lines 44-50) | `promo/rubric.py`, `evals/rubric.yaml` score drafts; previz has no review checklist | **Gap: build #3** (text) |
| Edit a variant, re-render | `promo previz cam/panel/type/dur` overrides; `promo build` / `promo shot` are per-shot and stamped (`promo/cache.py` `Stamps`) | Ours, but previz re-exports the whole strip; per-shot video rebuild is part of #1 |
| Stage placement | `promo/flow.py`: `previz` stage between `storyboard` and `assets`, no gate of its own; `PZ.plan_hash` is folded into `gate_hash("assets-approved")`, the one plan review | Already right. No new gate. |
| Promo spec as a source | `previz.targets()` reads `plan.designed` or flow storyboards only; a `promo new` project (shots with `beats`, `cam`, `overlays`) cannot be previsualised | **Gap: part of #1** |
| Evaluation rubric (`cvm/evaluation.py`, `cvm/evaluation_rubric.py`) | `promo/rubric.py`, `promo critique-pack`, council rounds | Skip: ours covers drafts, and a paid judge on wireframes is not worth it |

## Shortlist (ranked, each opt-in)

1. **Per-shot animatic on the music grid** (from `inference/render.py`). `promo previz animatic`: each shot of the scene renders to its own
   silent `shots/<id>.previz.mp4` (wire boxes, the caption zone, beat ticks, a camera-box minimap, a `PREVIZ · NOT FOOTAGE` watermark,
   `UI STAND-IN` on panels), keyed by a digest of that shot's own content so one spec edit rebuilds one shot and the run lists
   `rebuilt / kept / shifted`; then one `<name>.previz-animatic.mp4` with a beat click track (or the built music bed) and a
   `not_footage` sidecar. New source: a `promo new` spec (`shots[].beats`, `cam`, caption overlays) read through `load_spec`. On by
   default for the film-directing styles (horizon, cinematic-story, anime-mv), opt-in elsewhere; 2D (`ortho`) by default, 3D (`persp`)
   for cinematic-story. Shown in the existing plan review.
2. **Timing and camera handoff** (from the trajectory export and `cvm/pair.py`'s camera lock). `previz.timing_camera()` returns only
   `{id, t0, dur, cam keys}` of the approved scene; flow keyframe to-dos carry each frame's time and camera box from it, and
   `promo previz shots` prints a `shots:` skeleton (beats + `cam`) for drafts. Never visuals.
3. **Animatic review passes** (from `prompts/program_contract.md`). A four-pass checklist in `docs/previz.md` and the skill: order,
   timing on the grid, framing / camera box, caption zone and length.

## Skip

* `cvm/video.py`, `download_h3.py`, H3 config: GPU + hundreds of GB of weights, territory-limited licence, and it generates video of the
  subject, which for a product shot breaks AGENTS.md rule 1.
* `cvm/program.py`: a Copilot agent run on autopilot with every tool allowed; our agents already drive `promo previz`.
* `cvm/reference.py`: paid GPT-Image-2 frames; `promo gen` already covers non-UI plates.
* `cvm/evaluation*.py`: paid judging; see the table above.
* Upstream viewer and its three copies of three.js; all example media.

## Guardrails kept

Previz is never footage and never stands in for the product: files carry `.previz.` in the name and `not_footage` in metadata,
`promo footage add` refuses them and `promo check` fails a manifest that references one. UI shots still need real recordings.
