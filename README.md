# promo-reel

A declarative, agent-runnable pipeline for **product promo videos made from real app footage**: a beat-locked edit with eased crops and push-ins, captions in a fixed 9:16-safe zone, a licensed music edit, synthesised UI SFX, TTS voiceover, ducking and loudness mastering, and automated QA gates. It uses Python, Pillow and ffmpeg.

- **Agents start here:** [`skills/promo-reel/SKILL.md`](skills/promo-reel/SKILL.md) (short), [`skills/promo-video-route/SKILL.md`](skills/promo-video-route/SKILL.md) (which video model / Higgsfield vs Runway), and [`AGENTS.md`](AGENTS.md) (the full workflow, team rules, and what still needs a human).
- **Capture handoff:** [`capture/README.md`](capture/README.md) and `projects/<name>/footage/manifest.yaml`.
- **Starting a project:** [`templates/new-project/`](templates/new-project/) or `promo new <name> --style hero|anime-opening|livestream|horizon|cinematic-story`. Example projects live in your projects dir (`promo config projects-dir`; by default the gitignored `projects/`), not in this repo.

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
capture/                  capture-script contract (product-specific capture scripts live in your projects dir)
skills/promo-reel/        agent skill (flow, ingest, gates)
skills/promo-video-route/  pick Runway vs Higgsfield and a model for generated plates
templates/new-project/    scaffold used by `promo new`
evals/rubric.yaml         UX reviewer's scoring rubric (versioned): read by `promo critique-pack` and `promo rubric`
tests/                    fast unit tests (.venv/bin/python tests/test_<name>.py; needs the deps above, incl. pyyaml)
```

## CLI
```
promo new <name> [--style hero|anime-opening|livestream|cinematic-story|horizon]   scaffold projects/<name>/ for a style preset
promo styles                             list style presets (pacing, band, typography, transitions, checks)
promo -p projects/<name>/promo.yaml <cmd>
  status [--json]                        what is up to date, stale or missing, step by step
  assets [--json] | fetch                licence gate | download music/models (sha256-verified)
  footage list|verify [--json]           footage manifest; verify = exists + sha256
  footage add <abs path> --id ID --shots 05 --commit SHA --capture URL --framing ... --dpr 2 [--demo]
  build [--shots 05 06] [--force]        sfx -> vo -> music -> changed shots -> events -> mix -> assemble -> contact
  shot <id...> | sfx | vo | music | events | mix | assemble | contact     individual steps
  timeline [--json]                      shot table: beats, seconds, frames
  grid [--json]                          bar/beat table + markers of the music grid (timeline.grid)
  critique-pack [project] [--out D] [--no-check] [--video]   review folder for a reviewer model (BRIEF.md, stills + size sidecars, contact,
                                         copy, footage manifest.md, reviews, check output, VO transcript); config: critique: in promo.yaml
  check [--json]                         QA gates (exit 1 on FAIL; WARNs never fail)
  compare <ref.mp4> [--json]             per-shot PSNR + audio diff against a reference render
  peek <clip> <t> [box] | segpeek <shot> [t..] | mpeek out.png clip:t[:box] ...   framing helpers (build/peek/)
  --scale 2                              3840x2160 from the same spec (needs DPR2 sources to be sharp)
promo brief init|show|check|confirm|conflict --project projects/<name>   the locked brief: the user's verbatim request, references + why, must-have/must-not, conflicts and their decisions (STEP 0)
promo refs add <url|file> --project projects/<name> [--id ID --why "..."] | check | show   watch a reference WITH transcript + audio, scaffold DOSSIER.md; check = dossier complete
promo compare-ref <draft.mp4> --project projects/<name>   reference row above draft row + metrics (cuts/s, median shot, LUFS, tempo, speech) -> out/compare/
promo rubric <scores.yaml|review.md> [--json] [--legacy]   PASS/FAIL of a review against evals/rubric.yaml (exit 1 FAIL, 3 INCOMPLETE = hard gates intent/reference not scored)
promo live2d fetch | models | render --model hiyori --wav a.wav --out a.mov | lag    Live2D hosts (prototype, live2d/README.md)
```

### Live2D talk-show hosts (prototype)
Shot type `livestream` puts the app screen (at least 55 % of the frame) next to one or two Live2D hosts, which are
lip-synced offline from a WAV per host and stacked `slot_gap` px apart (default 16, minimum 12), plus a chat strip of
up to 4 lines. Nothing fakes an audience: chat lines are the hosts' own asides (author = a host's id or name) unless
`chat.scripted_label` is set and shown on the strip; the header has a neutral `tag` ("EP 1"), never a LIVE badge or
viewer counts. Hosts stay on one side (`hosts_side: left|right`) with no slide by default; an optional single `move`
(>= 0.5 s, on a beat change) slides them off the frame edge, never behind the screen. `keep_clear` rectangles on
the app screen may not be covered by anything (their outlines are drawn only with `promo --debug`). Every host sits
in its own panel and is framed by per-model head/chest anchors (`live2d/assets.yaml`), so all hosts get the same
mid-chest-up crop, head height and scale; a taller silhouette (a hat, `top` anchor) breaks out above its panel,
and `promo check` keeps that clear of everything else. The Live2D
credit is a `live2d_credits` end card (full notice + model credits, >= 28 px, >= 2 s). `promo check` gates all of
this. The Cubism Core and the sample models are fetched from live2d.com and never committed. Licences and the
required notice are in [`docs/live2d-licences.md`](docs/live2d-licences.md). Example: `projects/live2d-demo/`.

**Shared heavy-work lock:** `promo build|shot|vo|music|sfx|mix|events|assemble|contact`, Live2D host renders and the
livestream compositor hold a box-wide lock other heavy jobs on the machine can share (set `PROMO_HEAVY_LOCK` to the same path as e.g. your test gates, or `promo config heavy-lock PATH`; default `/tmp/promo-reel-heavy.lock`) for their whole run, so two heavy jobs never overlap. They block until it is free and log
every 30 s while waiting (`promo/lock.py`; re-entrant within one process). Path: `$PROMO_HEAVY_LOCK`, else `heavy_lock:` in the user config, else the default.
With `--json`, only JSON goes to stdout and it always has `ok`; logs go to stderr. This keeps the CLI ready to wrap as an MCP server later.

Builds are **idempotent**. Each step stamps a hash of its inputs (spec subtree, input files, code, scale) and is skipped when nothing has changed. Editing one shot re-renders only that shot, then re-runs events, mix and assemble only if their inputs changed.

## Watch, ask, generate (agent tools)
- `promo watch <url|file>`: download (yt-dlp) and "watch" any video: time-stamped contact sheets, a still per cut, shot table, cut-rate curve, loudness/tempo, optional transcript (`PROMO_WATCH_ASR=0` skips it). Use it on the reference AND on your own draft, compare the numbers.
- `promo -p <promo.yaml> needs [--json]`: the handoff. promo-reel lists what it still needs (real footage to capture, plates to generate, human review) and the command that ingests each answer; the calling agent decides how (its own tools, grok, codex, a human).
- `promo gen plan|register|detect|image|video`: generated images/video for NON-UI plates only (backgrounds, transitions, textures). `register` ingests an agent-supplied file (corner-watermark crop, `generated:` manifest entry); `promo check` fails a generated clip on a UI shot.
- `--scale 0.5` renders a 540p draft for review rounds; `python -m promo.score <name> out.wav` makes the original (CC0) scores. Council loop: `evals/council.md`.

## Style presets
`style: {preset: <name>}` in promo.yaml (or `promo new <name> --style <name>`) pulls in a named bundle of editorial
rules; anything the spec sets under `style:` wins (deep merge). `promo styles` prints them (`promo/styles.py`).

| Preset | Look | Gates it adds |
|---|---|---|
| (none) / `hero` | calm product hero: eased push-ins on real UI, dark caption pills in one fixed lower-middle zone held >= 2 s, cuts on beats | the base gates + the generic gates below |
| `anime-opening` | kinetic title cards on real footage: cuts on bar lines from a music grid (`timeline.grid`), UI shots >= 1 bar, cards >= 1 bar in ONE fixed lower band (`band.frac`, 15 %) that never covers app text, flashes / speed lines only at cuts; shot type `anime` | grid, bar-cuts, shot-hold, card-hold, card-band, card-ui-clear, fx-between, flash-rate, claims, named, markers, placeholders |
| `livestream` | talk show / livestream composite (shot type `livestream`, Live2D hosts beside the app screen): long holds, chyron band, cuts only | shot-hold (>= 4 s), no-fx + the `livestream-*` gates |
| `horizon` | Opus-5.5-style horizon film (shot types `horizon`, `dawn`): rapid cuts of real surfaces each framed on a real edge (`anchor`), ONE serif line on the horizon (show-level `horizon_text`) whose words change across cuts, a burst then a hold >= 3 s, a held dawn end card; cuts only | horizon-shot-hold, horizon-cuts, horizon-burst-hold, horizon-text, horizon-text-fit, horizon-edge, horizon-transitions, horizon-dawn, horizon-text-ui, horizon-wordless-open, horizon-sky |

Claim tables (`claims:`, `promo/claims.py`) pick a card / caption line from the legibility record of the evidence shot,
so a number on screen can never outrun the frame (`text_from: claims.<table>`; `confirm: <who>` marks provisional copy).

## Running tests and checks

```bash
PY=.venv/bin/python                      # the venv with pyyaml etc.; system python3 lacks pyyaml; no pytest needed
for t in tests/test_*.py; do nice -n 10 $PY "$t" || echo "FAILED: $t"; done   # each file is a plain script
$PY -m promo -p projects/<name>/promo.yaml check     # QA gates on the existing render (no re-render); exit 1 on any FAIL
```

`promo check` samples frames with ffmpeg (`-threads 2`) under the shared heavy-work lock (`promo config heavy-lock`),
so it may wait for other heavy jobs. Talk-show tests and specs read the hero footage manifest via
`HERO_FOOTAGE_MANIFEST` (tests that need a local example project skip when it is absent).

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
| style: anime-opening | grid (music JSON present, no drift); bar-cuts (cuts on bar lines, half bars only beside text-free shots; cards start on bars); shot-hold (UI >= 1 bar, text-free >= 1/2 bar, `ui:` set); card-hold (>= 1 bar, words >= 0.6 s); card-band (one fixed band, no per-card positions or free overlays); card-ui-clear (no card over `ui_text`, UI shots framed above the band); fx-between (fx_in/fx_out only, <= 6 frames, never full-frame on UI shots); flash-rate (<= 3/s); claims (numbers come from claim tables or cite evidence); named (app text a card names, `named:` boxes, renders >= 18 px cap height at 1080p; `named-upscale` WARNs above 1.0x); markers (listed grid markers land on cuts); placeholders (WARN) |
| style: livestream | shot-hold (>= 4 s), no-fx |
| style: horizon | horizon-shot-hold (each shot >= 0.3 s FAIL, < 0.4 s WARN); horizon-cuts (whole beats, half beats only inside the burst window); horizon-burst-hold (the burst is followed by one shot held >= 3 s); horizon-text (each word spans >= 2 shots or >= 1.2 s, >= 0.5 s, never overlapping, only over horizon shots, no per-shot overlays); horizon-text-fit; horizon-edge (anchored camera box stays inside the source, sky only above the top edge and < 60 %); horizon-transitions (cut only unless `transitions.allowed` lists flash_dip); horizon-dawn (end card held >= 3 s, has a name); horizon-text-ui (FAIL: no word over real app footage unless the shot sets `text_over_ui: true`); horizon-wordless-open (WARN: no word in the first 40 % of the burst); horizon-sky (WARN: flat sky > 8 % of the frame height) |
| named (every project) | text a caption / card / VO line names (`named:` boxes on the shot, QA-only: never forces a re-render) renders under 18 px cap height at 1080p or is not fully in frame; `named-upscale` WARNs above 1.0x. Anime shots use the anime gate, livestream shots `livestream-named`; clip / plugin shots (the hero) use the generic one (`t` may be a list of shot-local times; `info: true` rows are reported, not gated). Folded in from the hero's `tools/named_v5.py` |
| claims (every project) | projects whose preset does not run it (no preset = the hero): `promo.claims.audit` on the claim tables, every `text_from` resolves, and a literal caption that is a claim-table row must be the row the table selects. Folded in from the hero's `tools/claims_v5.py` |
| text-edge (WARN) | text or cards clipped by the output frame / crop edge: a `named` box crossing the crop, or, on UI shots, glyph-sized ink touching the left / right footage viewport edge (the anime band, the livestream screen; 32 px corners ignored) at the same spot on >= 2 of 3 sampled frames. More than 3 spots on one edge = a push-in cropping a whole pane, treated as framing. `edges: [top, bottom]` opts in to the stroke test on those edges |
| empty-frame (WARN) | a UI shot whose largest flat region (blurred blocks, so dotted canvas counts) of one background level, not counting blocks next to content, is over `max_frac` (40 %) of the footage viewport. Scenery captures (`non_ui_capture`: Workshop / Outside views), shots with no footage and `ui: false` shots are skipped |
| caption-truth (WARN) | a caption / card count claim ('8 TASKS', 'ALL LANDED', '3 AGENTS') disagrees with the claim table it selects from or with the footage manifest notes of the clip on screen, or nothing backs it |
| long-hold (WARN) | the footage viewport does not change (<= 0.05 % of pixels move > 10 levels at 384 px wide, so typing and badge flips count as change) for longer than `max_s` (hero 3.5 s, anime-opening 2.8 s, livestream 6 s; specs with a `livestream:` block and no preset use livestream). Cards, credits and blank screens are skipped |

| brief (every project with `brief.yaml`) | `brief.yaml` is missing, `intent_verbatim` is empty, a reference has no `why`, a conflict is still `pending` or has no `decided_by`. WARN when not human-confirmed (or edited since). A project without `brief.yaml` WARNs, and FAILs when `style.require_brief: true` |
| references | a reference listed in the brief has no `reference/<id>/DOSSIER.md`, a `TODO:` remains, a section is empty, contact sheets / transcript.json / audio metrics are missing, an Evidence read box is unticked, or a NOT-transferable item has no `conflicts` entry (`ref: <id>`) |
| intent-review | the newest `rounds/<n>/decision.md` lacks the `intent-check: intent_sha=<hash> verdict=YES|PARTIAL|NO intent=<n> reference=<n>` line from the Intent & Reference lens, quotes another intent hash, or says NO / a score under the rubric's hard_min (PARTIAL WARNs) |

The four WARN rules are configured per preset in `promo/generic_check.py` (`WARN_RULES`) and per project with
`qa: {warn_rules: {long_hold: {max_s: 5}, text_edge: {on: false}, ...}}`. Frame sampling (ffmpeg `-threads 2`) runs
inside `promo check`'s hold of the shared heavy-work lock.

| livestream-* | (livestream specs only) `licence`: a host is not a Live2D Original Character, or there is no `live2d_credits` end card with text >= 28 px held >= 2 s at full opacity; `screen`: under 55 % of the frame; `chat`: `max_lines` > 4; `chat-truth`: a chat author is not a host and no `chat.scripted_label` is set; `lint`: on-screen text says LIVE or shows a viewer count; `side`: `hosts_side` not left/right, `slot_gap` < 12, more than one move, a move shorter than 0.5 s or off a beat change, or a per-shot side flip; `keep-clear`: anything drawn (hosts, header, chat strip, overlays) covers a `keep_clear` rectangle on any frame |

## Review: critique pack + rubric
`promo critique-pack [project]` writes one self-contained folder for a final reviewer (default `out/critique-pack/`):
`BRIEF.md` (rubric, hard rules, what to return, shot table), `TEXT-LINES.md`, full-res stills with size sidecars
(cards, captions, `named` app text: cap px at 1080p, effective scale), the contact sheet, `CHECK.txt/json`, the VO
transcript, and the copy / footage manifests / earlier reviews named under `critique:` in promo.yaml. It calls no model.

The rubric is **the UX reviewer's**, versioned in [`evals/rubric.yaml`](evals/rubric.yaml) (BRIEF.md reads it; override
with `critique.rubric:` or `$PROMO_RUBRIC`): nine 1-5 scores (intent, reference, hook, legibility, story, pacing, calm, style, polish)
plus Truth PASS/FAIL. **Pass bar:** intent >= 4 and reference >= 4 (hard gates), average >= 4.2, no score under 3, Truth PASS. `promo rubric <scores>` computes
the verdict from a YAML/JSON scores file or a review in markdown (a `| Rubric | Score |` table plus a `**Truth:** PASS` line); `promo.rubric.evaluate()` is the same in code. Bump `version` (+ changelog) when the rubric changes.

**Rubric v2 (hard gates).** `intent` ("would the person who wrote the request say this is what they asked for, in their words?") and
`reference` ("does it feel like the supplied references in narrative, people, motion, light, sound and pacing, not just look?") come first.
`pass.hard_min: {intent: 4, reference: 4}` cannot be averaged away. A v1 review (seven scores) still parses; its missing gates are reported as
"not evaluated" and the verdict is INCOMPLETE (exit 3), never PASS (`--legacy` for archived reviews). The council's first lens
(`evals/council.md`) judges these two against `projects/<name>/brief.yaml`, the reference dossiers and `promo compare-ref`; `promo critique-pack`
copies all three into the pack and lists both as hard gates in BRIEF.md.

## Licences
Music is **never committed**: for example, the Pixabay Content License forbids redistributing the file standalone. `assets.yaml` holds the track page, licence, `fetch_url` and `sha256`; run `promo fetch`. The Kokoro VO model is Apache-2.0 and fetched the same way. SFX are synthesised by `promo sfx` (no samples). Raw footage stays on the box and is tracked by sha256 in the footage manifest. It never goes in git, including Git LFS.

## Team rules
Real footage only. Never edit the app's UI in post; reshoot instead. No invented claims. Licensed audio only. The user's verbatim brief and references (dossiers read from transcript + audio) outrank an agent's summary. A human approves before anything is published. See [`AGENTS.md`](AGENTS.md).
