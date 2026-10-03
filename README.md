# promo-reel

A declarative, agent-runnable pipeline for **product promo videos made from real app footage**: a beat-locked edit with eased crops and push-ins, captions in a fixed 9:16-safe zone, a licensed music edit, synthesised UI SFX, TTS voiceover, ducking and loudness mastering, and automated QA gates. It uses Python, Pillow and ffmpeg.

- **Agents start here:** [`skills/promo-reel/SKILL.md`](skills/promo-reel/SKILL.md) (short) and [`AGENTS.md`](AGENTS.md) (the full workflow, team rules, and what still needs a human).
- **Capture handoff:** [`capture/README.md`](capture/README.md) and `projects/<name>/footage/manifest.yaml`.
- **Worked example:** [`projects/commission-ai-hero/`](projects/commission-ai-hero/), the commission-ai 60 s hero v1. `examples/commission-ai-hero` is a symlink to it.

## Install
```
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[vo,asr]'        # vo = kokoro-onnx TTS, asr = faster-whisper (the VO check gate is skipped without it)
# needs ffmpeg/ffprobe on PATH and the font named in style.font (Inter, OFL)
```

## Layout
```
promo/                    engine + CLI (spec, render, shots/, overlays, events, sfx, vo, music, mix, assemble, contact, check, assets, cache, compare)
projects/<name>/
  promo.yaml              the declarative spec: output, timeline (BPM/beats), style, shots, music edit, VO lines, SFX, mix, QA thresholds
  assets.yaml             licence manifest: music / VO model / SFX / font, each with licence + source_url (+ fetch_url, sha256)
  footage/manifest.yaml   capture handoff: clip id -> absolute box path, sha256, app commit, capture URL, framing, resolution, DPR
  footage/manifest.md     human notes for the capturing agent
  shots.py                optional project plugin: bespoke shot types (@shot_type)
  docs/                   brief, shot list, VO script, captions, review notes
  media/ build/ out/      gitignored: fetched assets, intermediates, deliverables
capture/                  capture-script contract (product repos PR their capture scripts here)
skills/promo-reel/        agent skill
templates/new-project/    scaffold used by `promo new`
tests/                    fast unit tests (python tests/test_core.py)
```

## CLI
```
promo new <name>                         scaffold projects/<name>/
promo -p projects/<name>/promo.yaml <cmd>
  status [--json]                        what is up to date, stale or missing, step by step
  assets [--json] | fetch                licence gate | download music/models (sha256-verified)
  footage list|verify [--json]           footage manifest; verify = exists + sha256
  footage add <abs path> --id ID --shots 05 --commit SHA --capture URL --framing ... --dpr 2 [--demo]
  build [--shots 05 06] [--force]        sfx -> vo -> music -> changed shots -> events -> mix -> assemble -> contact
  shot <id...> | sfx | vo | music | events | mix | assemble | contact     individual steps
  timeline [--json]                      shot table: beats, seconds, frames
  check [--json]                         QA gates (exit 1 on FAIL)
  compare <ref.mp4> [--json]             per-shot PSNR + audio diff against a reference render
  peek <clip> <t> [box] | segpeek <shot> [t..] | mpeek out.png clip:t[:box] ...   framing helpers (build/peek/)
  --scale 2                              3840x2160 from the same spec (needs DPR2 sources to be sharp)
promo live2d fetch | models | render --model hiyori --wav a.wav --out a.mov | lag    Live2D hosts (prototype, live2d/README.md)
```

### Live2D talk-show hosts (prototype)
Shot type `livestream` puts the app screen (at least 55 % of the frame) next to one or two Live2D hosts, which are
lip-synced offline from a WAV per host, plus a chat strip of up to 4 lines. Hosts stay on one side for the whole show
(`livestream.hosts_side: left|right`), with at most one slide of 0.5 s or more on a beat change. `keep_clear`
rectangles on the app screen may not be covered by anything. `promo check` gates all of this. The Cubism Core and
the sample models are fetched from live2d.com and never committed. Licences and the required notice are in
[`docs/live2d-licences.md`](docs/live2d-licences.md). Example: `projects/live2d-demo/`.
With `--json`, only JSON goes to stdout and it always has `ok`; logs go to stderr. This keeps the CLI ready to wrap as an MCP server later.

Builds are **idempotent**. Each step stamps a hash of its inputs (spec subtree, input files, code, scale) and is skipped when nothing has changed. Editing one shot re-renders only that shot, then re-runs events, mix and assemble only if their inputs changed.

## QA gates (`promo check`)
| Gate | FAIL when |
|---|---|
| assets | a music, VO-model or SFX asset has no licence or source_url, or the spec references an unknown asset; spec lint finds a UI-editing key (`debubble`, `paint_out`, `inpaint`, `ui_edit`) |
| footage | a referenced clip is missing or its sha256 differs from the manifest. WARN for DPR1 sources pushed past 1.5x and for demo-mode footage |
| duration | an output is not `output.duration` (±1 frame) or has no audio |
| format | width/height, fps or frame count is wrong |
| loudness | integrated loudness is off target by more than the tolerance, or true peak exceeds `max_true_peak` (ffmpeg ebur128 on the final mp4s) |
| beat grid | shots don't tile 0..beats on the beat grid, or a segment's frame count differs from the timeline |
| caption hold | a caption is visible for less than 2.0 s (anchored labels only WARN) |
| caption safe zone | a caption pill falls outside the fixed lower-middle 9:16-safe zone or is wider than `max_w` |
| contact sheet | the contact sheet is missing, or doesn't have one tile per shot |
| VO vs script | the whisper read-back of a VO line doesn't match the script word for word (normalised, with per-line aliases). WARN and skip if whisper isn't installed |
| freshness | WARN if an output is stale against its inputs |
| livestream-* | (livestream specs only) a host is not a Live2D Original Character; the screen is under 55 % of the frame; chat `max_lines` > 4; `hosts_side` is not left/right, there is more than one move, a move is shorter than 0.5 s or off a beat change, or a per-shot side flip; anything drawn above the screen (hosts, header, chat strip, overlays) covers a `keep_clear` rectangle on any frame |

## Licences
Music is **never committed**: for example, the Pixabay Content License forbids redistributing the file standalone. `assets.yaml` holds the track page, licence, `fetch_url` and `sha256`; run `promo fetch`. The Kokoro VO model is Apache-2.0 and fetched the same way. SFX are synthesised by `promo sfx` (no samples). Raw footage stays on the box and is tracked by sha256 in the footage manifest. It never goes in git, including Git LFS.

## Team rules
Real footage only. Never edit the app's UI in post; reshoot instead. No invented claims. Licensed audio only. A human approves before anything is published. See [`AGENTS.md`](AGENTS.md).
