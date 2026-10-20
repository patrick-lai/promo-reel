---
name: mesh-avatar
description: Turn ONE front-facing character illustration (PNG) into an animated 2D mesh avatar that blinks, talks, turns its head, breathes and sways its hair, with Mesh Avatar Studio (shinshin86/mesh-avatar-studio, MIT). Use when the person has a drawing but no Live2D model and wants it to move - "make an avatar from this illustration", "animate my character PNG", "mesh avatar", ".mavatar". A helper next to promo-reel; AGENTS.md rules 1-5 win.
---

# mesh-avatar

Mesh Avatar Studio rigs one illustration in about 5-10 minutes of agent work to a reviewed rig (drawn variants add 7-10 minutes
each through grok, run in parallel): the agent reads coordinates off zoomed grids, the
tool cuts eye layers and a hair mask, and a WebGL runtime (`mesh-avatar` on npm) animates it with idle motion, blinks, five
vowel mouths from a voice level, expressions (smile, wink, surprise, sad, angry, shy) and motions (nod, greet, tilt, giggle ...).
It is a lighter cousin of Live2D: no artist-made parts, one picture in. Upstream's own guide is the procedure; this file is
how it fits promo-reel.

## What promo-reel can do with it today
- Make and review an avatar (this skill), show the person stills and a test clip, hand over the project and a `.mavatar`.
- The person can stream with it from Studio's Live page (OBS Browser Source) outside promo-reel.
- **Not yet:** put it in a promo-reel video. No shot or overlay composites it: the `avatar` overlay is only for the person's own
  likeness and draws an opaque rounded box, podcast hosts are Live2D models, and there is no gated asset kind for a mesh
  character. Do not route its render into a build as a workaround; say it needs the mesh backend (a second renderer behind
  `promo/live2d.py` `render_host`, driven by `promo/perform.py`, plus a licence-gated asset kind) and offer that as the next step.

## Rules here
- The illustration must be original, the person's own, or commissioned with a licence that allows animation. Never a
  character someone else owns. Upstream's Miko sample (`samples/miko-qipao/`) is under AITuber OnAir's terms, not MIT: use it
  to learn the editor, never in anything published.
- A generated illustration (grok / Codex images) is a generated asset: record the prompt and tool next to the project.
- An anime version drawn from the person's own photo (grok `image_edit` with the photo as reference) is their own likeness:
  only theirs, made because they asked, and under the AGENTS.md own-likeness carve-out (consent in `brief.yaml`) if it ever
  goes into a published video. Never draw anyone else from a photo.
- Drawn variants (step 6) send `source.png` and a mask to an image generator. Ask first unless the picture was generated for
  this job. If they decline, the avatar still works from mesh deformation alone.
- Projects (the picture and everything built from it) live under the Studio checkout's `projects/`, never in this repo.

## Install (once per machine)
```sh
git clone https://github.com/shinshin86/mesh-avatar-studio ~/.promo-reel/tools/mesh-avatar-studio
cd ~/.promo-reel/tools/mesh-avatar-studio && git checkout 784b8abc3c80bc3915b4cd9894f20859a0949936
npm install && npx playwright install chromium && npm run doctor   # needs Node 22.17+, uv, Python 3.10+
```
Run every command below from that folder. Its `AGENTS.md` and `docs/agent-guide.md` are the procedure; read the guide before
step 1. Field meanings: `docs/rig-fields.md`.

## Procedure (upstream guide, with what we learned)
0. Vision check: `uv run tools/vision-check.py make work/vision-check`, read the markers, `... score work/vision-check answer.json`.
   Stop if it fails. Claude Opus 5.5 scored median 0.73 px / max 1.37 px (pass is <= 4 / <= 10).
1. The picture: front-facing, head and shoulders, nothing over the face, transparent background. A generator gives a white
   background and a corner logo: crop the logo off and flood-fill the background to alpha from the top and side edges only
   (the clothes touch the bottom edge), then check it over magenta. `uv run tools/new-project.py <png> <name>`.
2. Survey: `uv run tools/grid.py projects/<name> --step 50 --out projects/<name>/work/grid-full.png`; list hats, glasses,
   held objects and hoods (they move rigidly).
3. Draft `rig.draft.json` part by part from zoomed grids (`--region x0,y0,x1,y1 --step 5` for eyes). Eye `opening` 14-20 points
   on the eye white from the outer corner; `roi` 10-20 px outside the lashes. Then `npm run validate-rig -- projects/<name>/rig.draft.json`
   and `uv run tools/overlay.py ... [--part eyes --zoom]`; look at every overlay.
4. `uv run --with numpy --with pillow --with opencv-python-headless tools/build-layers.py projects/<name> --rig rig.draft.json`;
   look at `built/hairmask.png` and the eye layers.
5. `npm run render-poses -- projects/<name>` and look at `review/contact-sheet.png` plus every eye and mouth crop. Three rounds max.
   Where the `roi` has to touch side hair, closed and smiling eyes pick up a hair-coloured smudge at the outer corner; drawn
   variants hide it.
6. Drawn variants: `uv run tools/variant-requests.py projects/<name>`, generate each into `projects/<name>/variants/<variant>.png`
   (grok `image_edit` with `source.png` as the reference and the mask described in words works headless; Codex image
   generation does not run headless here), then `uv run tools/build-sprites.py projects/<name>` and render the poses again.
   It rejects shifted or redrawn results; regenerate those. grok sometimes returns a JPEG at another size (848x1216): the
   importer refuses the aspect ratio, so regenerate rather than stretch.
   **All or nothing (upstream 784b8ab):** once any drawing is imported, the runtime turns off the mesh eyelids and mouth
   (`createMeshAvatar.js` `sprites ? 1 : v`). Mouths alone make every blink, smile and half-lid erase the eyes. Import
   `eyes_closed`, `eyes_half` and `eyes_smile` together with the four mouths (`mouth_a`, `mouth_a_half`, `mouth_i`,
   `mouth_o`), or none, and check `eyes-closed` and `angry` in the pose review.
7. Hand over: `npm run dev` -> Open project; `npm run pack-avatar -- projects/<name>` for a `.mavatar`; say which parts are least sure.

## Showing the person
Stills from `review/` are the quick look. For a moving test, drive the runtime headless: `createMeshAvatar(canvas, {rig, assets,
manual: true})`, then per frame `setSpeaking`, `setVoiceLevel(rms)`, `setEmotion` / `setExpression` / `play(motion)` and
`advance(1/fps, fps)`, reading `canvas.toDataURL()` (see `tools/render-poses.mjs` for the page and asset loading). About 40 ms
a frame at 1080p on this Mac. Idle and blinks use unseeded `Math.random`, so two renders differ.
