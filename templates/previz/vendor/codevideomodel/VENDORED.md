# CodeVideoModel (ideas harvested into `promo previz animatic`)

- Source: https://github.com/code-video-model/CodeVideoModel
- Pinned commit: `404e03d67c2977b441622ce94411470bb84984a8` (main, 2026-10-13)
- Licence: Apache-2.0. `LICENSE` here is the upstream file byte for byte at that commit
  (`gh api repos/code-video-model/CodeVideoModel/contents/LICENSE?ref=404e03d6… -H 'Accept: application/vnd.github.raw' | diff - LICENSE` prints nothing).
- NOTICE: upstream has **no NOTICE file** at the pinned commit (the contents API answers 404 for `NOTICE`), so there is none to carry.
- Proposal and comparison: `docs/codevideomodel-harvest.md`.

## What was taken

No upstream file is copied. Three ideas are reimplemented in `promo/previz.py`:

| Upstream | Here |
|---|---|
| `inference/render.py` `render()`: a code scene encoded frame by frame through one libx264 pipe, a contact sheet beside it | `animatic()`, `_encode()`: each previz shot piped into its own `shots/<id>.previz.mp4`, joined into `<name>.previz-animatic.mp4`; the strip is refreshed |
| `render.py` camera trajectory export, `cvm/pair.py` camera lock | `timing_camera()` / `blocking()`: the approved scene's timing and camera box (never pictures) for keyframes and `promo previz shots` |
| `prompts/program_contract.md` four refinement passes | the four animatic review passes in `docs/previz.md` |

## Changes

- Python + Pillow + ffmpeg instead of Playwright + three.js for the video; the three.js viewer stays ours (`templates/previz/viewer.*`).
- The camera is promo-reel's `(cx, cy, w)` box, not a position + quaternion trajectory.
- Per-shot clips keyed by a digest of each shot's own content, so one spec edit re-renders one shot; upstream renders the whole scene.
- Played against the music grid: beat ticks, an accented click track (or the built music bed).
- Every output is labelled previz / not footage (file name, MP4 comment, sidecar `not_footage: true`) and is refused as footage.

## Omitted

- `cvm/video.py`, `download_h3.py`, MiniMax-H3 config: video diffusion of the subject (AGENTS.md rule 1), GPU + hundreds of GB of
  weights, and the MiniMax H3 Community Licence excludes the EU, the UK, the Republic of Korea and the USA.
- `cvm/reference.py` (paid GPT-Image-2), `cvm/evaluation*.py` (paid OpenRouter judge), `cvm/program.py` (Copilot agent on autopilot).
- Upstream viewer, prompts, and its three copies of three.js (we ship r160 already).
- All example media (`examples/`, CC BY 4.0) and badges: no binary media is vendored.
