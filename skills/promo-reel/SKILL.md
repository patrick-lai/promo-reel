---
name: promo-reel
description: Make or update a product promo / demo video from real app footage with the promo-reel repo (declarative promo.yaml, beat-locked edit, music + SFX + VO mix, QA gates), watch a reference video, and generate image/video plates (backgrounds, transitions). Use when asked to build, re-cut, caption, re-capture or check a promo reel, hero video or demo video, to copy the style of a video link, or to make a background / transition / b-roll image or clip.
---

# promo-reel

!`[ -n "$COMMISSION_THREAD_TOKEN" ] && commissionctl mod activate promo-flow >/dev/null 2>&1 && echo "Promo flow pane opened (Preparing). Publish a state to replace it."`

**First action, before any reading or planning:** inside CommissionAI the Promo flow pane and its chat card must exist the moment this skill runs. If the line above did not print "Promo flow pane opened", run `commissionctl mod activate promo-flow` yourself now (idempotent; skip outside CommissionAI). The pane shows an animated "Preparing…" until your first `commissionctl mod publish promo-flow`.

Start with THE FLOW (below). Everything lives in `<save location>/<name>/` (see `promo config output`; default `projects/`) (promo.yaml, assets.yaml, footage/manifest.yaml, shots.py plugin). Run commands from the repo root:
`promo -p projects/<name>/promo.yaml <cmd>` (venv python: `python -m promo ...`).

## THE FLOW (default: use it for every new video; the person stays in the loop)
`promo flow` is a gated state machine (`<project>/flow/flow.json`). It refuses to skip a stage; human gates are approved only by the person's name
(`approve ... --by NAME`, an agent name is refused; an approval goes stale if the thing approved changes). Start: `promo flow init <name> --intent "<their words, exact>"`
(also locks the brief). Every turn: `promo flow status --json` -> do `next`, make what `needs` lists, and put `ask` to the person with AskUserQuestion **unless `ask_in_stage` is true and the `promo-flow` mod is open**: then the Stage pane's gate is that question, and a second copy in the chat box stays open after they answer in the pane (the host owns the box; you cannot close it). Pane first, no duplicate.

| # | stage | you do | the person decides |
|---|---|---|---|
| 1 | **discover** | ask style + references (`promo flow discover`, `promo refs add`) | style, refs |
| 2 | **scripts** | write 3+ different scripts; council spars 1-2 rounds (`evals/council-flow.md`); `promo flow script add`, `council scripts` | |
| 3 | **pick** | present the ranked scripts | which 1-2 go on (`approve scripts-picked`) |
| 4 | **storyboard** | per story `flow/boards/<id>/board.json`: every scene with beat, time, action, caption/VO/sound/camera/proof and a **START and END frame**; **MAKE the frames as real images** with `promo flow frames` (a text slate is not a frame and counts as missing); `promo flow board`, SHOW the page | iterate until `approve storyboard-approved` |
| 5 | **assets** | list ALL assets the cut will use (screenshots, pictures, recordings, music, voice, sfx) with `promo flow asset add`, then **MAKE a real sample of each** with `promo flow asset make`: a concept still, a ~7 s clip, a 20 s music excerpt, a voice read-through, the sfx hits. The person must be able to look at / hear every asset before deciding; a placeholder is not a preview, and `approve assets-approved` is refused until every asset has one | `approve assets-approved` |
| 6 | **keyframes** | generate the remaining keyframes, replace every mock (`promo flow needs`) | |
| 7 | **confirm** | summary of board + assets | the explicit go (`approve final-confirmation`) |
| 8 | **drafts** | build first drafts, `promo flow draft add`, SHOW them (SendUserFile) | |
| 9 | **review** | <= 5 rounds: `round start --feedback "<verbatim>"`, council (lens 0 intent + web research of the topic and examples of good videos), one batch, one draft, `round close` | feedback or `approve draft-approved` |
| 10 | **final** | `final add`; further feedback = `promo flow revise` (new cycle, council again) | |

### Fan out: spec once, build in parallel, agents review, then the person
The loop is **spec -> parallel build -> agent review -> (repeat) -> person**; the person chooses whether to go round again. Do not do these one at a time.
1. **Spec up front (one batch).** Collect everything in a single `commissionctl ask` / AskUserQuestion (with the mod open, leave out what the pane's gate already asks, e.g. the style; ask only the rest): style, references, must-show, must-not-claim, length, platforms, end card. Do not drip questions across stages. Then run reference study (`promo refs add`, one sub-agent per reference) in parallel with writing scripts.
2. **Build in parallel.** Spawn independent sub-agents in ONE message: one script writer per angle; one board per picked story; per-asset-kind makers (stills, clips, voices, music, sfx). `promo flow make --jobs N` already draws frames and asset samples N at a time (default 3). Captures of the real app are the person's: ask for the whole list at once, and keep generating everything else while they record. Renders are different: ffmpeg shots run one at a time under the heavy lock, but prepare sfx, VO and music alongside shot renders.
3. **Agent review before the person sees it.** Run the council lenses as parallel sub-agents, merge into ONE batch, rebuild, re-check. Repeat up to 2 internal passes (they do not use the person's 5 rounds) until no high-severity finding is left and `promo check` passes. Post `promo flow note` lines for each pass.
4. **Person review.** Show the draft. They approve, or send feedback: that starts `promo flow round start` and goes back to step 2 for the changed parts only. Never start another loop on your own.
Post a `promo flow note` at every fan-out and fan-in so the Stage shows what is running.

**Content on request (the person is in charge of size and detail).** The Stage's Plan tab and Storyboard tab let them ask for more, and you answer with real content, any length:
`promo flow script add|append` (a script in as many parts as it needs, `--file -` for stdin), `promo flow doc add|append|new|list|rm|templates` (planning documents: full script, shot list, edit plan, audio plan, capture checklist, claims, deliverables, schedule, treatment, director's notes; `doc new KIND` builds one from the real board and assets), `promo flow plan pack` (all of them at once, per story), `promo flow story|scene add|set|rm|list` (edit a storyboard without JSON), `promo flow density --every 5` (frames on a time grid; then `promo flow frames`). Details and the exact reaction to each `[mod:promo-flow]` message: `mods/promo-flow/agent/SKILL.md`. Documents are not gates, but every claim in them follows rule 3.

**Never ask for a decision on a placeholder.** `promo flow make` makes everything the person has to see (frames, then asset samples) in one go via the logged-in grok / codex CLIs (`promo gen detect`; ~25 s per image, 3 at a time); `promo flow needs` lists what is still missing. Samples are planning material, labelled SAMPLE in the Stage, and never enter the footage manifest. If the person clicks "Ask the agent to make them" you get `[mod:promo-flow] ... wants the real thing made`: run `promo flow make`, publish.

Session UI: `status --json` carries the `ask` payload (question + options) for AskUserQuestion, and `ask_in_stage` (the Stage pane already asks the same thing: do not ask in chat too); `promo flow board` writes the dashboard HTML (stepper, scripts, storyboards with
start->end frames, the asset gallery, drafts, rounds): publish it as an Artifact or show it as a widget so the person SEES the plan. Inside CommissionAI the widget is the `promo-flow` mod (`mods/promo-flow/`, README there): `promo flow snapshot --out f.json` then `commissionctl mod publish promo-flow --file f.json`; the person's clicks arrive as `[mod:promo-flow] ...` messages. Slash command: `/promo-flow` (`.claude/commands/promo-flow.md`).
**Resume a past project.** `/promo-resume [words]` opens the `promo-projects` mod (`mods/promo-projects/`): every past flow project with a search and a peek at where it stopped. `promo flow projects --out f.json` builds it (`--query` with their words), publish it as `promo-projects`; on `[mod:promo-projects] ... picked` run `promo flow resume <id>`, then carry on with `--project <dir>` on every flow command (`mods/promo-projects/agent/SKILL.md`).
**Upload (only when the person asks).** Where their `twg` is signed in and Atlassian Artifacts or Loom is on their site (`promo flow share detect`; the snapshot checks it), the Drafts tab offers Upload per draft and final. The click reaches you as `[mod:promo-flow] ... wants Draft 5 uploaded to ...`: run `promo flow share draft|final N --to artifacts|loom --by "NAME"` and publish. One canonical name per item: draft N is `<project>_draft_N` (edited and shared again it refreshes the same Artifacts link; Loom cannot replace, so it adds a copy), a final is `<project>_final_vN` (every `final add` is the next version, never overwritten). Private unless they ask for `--access open`. Never upload on your own.
Projects live where the person chose, never in the repo you are working in unless they picked that: `promo config output` shows it (home `~/.promo-reel/{project}/{slug}`, repo `./promo-reel/{slug}`, any folder such as an external drive, or promo-reel's own `projects/`); in the Stage it is the folder button. `promo flow init` and `promo new` use it, and a bare project name finds a video there. The older STEP 0 / Workflow sections below are the details behind stages 1, 6-9.

## The handoff: promo-reel asks, YOU deliver (it never decides how)
Run `promo -p projects/<n>/promo.yaml needs [--json]` at the start and after every change. It lists what is still missing and the exact command that
ingests each answer: `capture` (real footage the spec references but the manifest lacks, or a placeholder slate), `generate` (a `broll:` plate with a
ready-to-use guard prompt), `review` (HUMAN look at generated plates). Fulfil each with whatever you are harnessed with: your own image/video tools,
grok, codex/GPT, a person with a recorder. promo-reel only specifies, ingests and gates. Footage must be real; plates must be text- and UI-free.

## Eyes and hands: watch references, generate plates (use these before you design anything)
- **Watch any video (file or URL, e.g. YouTube):** `promo watch <url|file> [--out DIR]` downloads (yt-dlp), then writes `build/watch/<id>/`:
  time-stamped `sheets/sheet-NN.png` (READ THESE FIRST: open them as images), one still per cut, `WATCH.md` (shot table: length, palette, words),
  cut-rate curve per fifth, shot-length stats, loudness, tempo guess, transcript. Set `PROMO_WATCH_ASR=0` to skip the (slow) transcript ONLY for your own drafts; for a REFERENCE the transcript is mandatory (`promo refs add`).
  Do this for the reference AND for your own draft, then compare numbers (median shot length, cut-rate curve, LUFS) as well as how it looks.
  Write what you learn to the project's `docs/reference-study/<date>-<name>.md`; presets come from measurements, not vibes.
- **Generated images / video for NON-UI plates (YOU generate, promo-reel ingests):** the calling agent makes the asset with whatever it has
  (Higgsfield/Runway ACP connectors — pick model with `skills/promo-video-route/SKILL.md` — its own image/video tool, `grok -p "..."`, `codex exec "..."`, a person) and hands the file down:
  1. Declare what you need in `promo.yaml`: `broll: [{id, kind: video|image, prompt, seconds, aspect}]`; `promo gen plan [--json]` lists the open
     requests with the full guard-prefixed prompt (no people / text / UI / logos), target path and size.
  2. Generate each one yourself and save it to the `out` path (video 4 s, 16:9, >= 720p; a corner logo is fine, see `--watermark br`).
  3. `promo gen register <file> -p projects/<n>/promo.yaml --id bg-night --prompt "..." --provider <who made it> --shots 03 [--watermark br]`
     probes it, crops a Grok corner logo + upscales to 1080p (raw kept), writes the `.gen.json` sidecar and the footage-manifest entry with `generated:`.
  4. Reference it as `source: bg-night` on a shot with `ui: false`. `promo gen detect` shows which built-in runners exist here; `promo gen video|image "..." --out F`
     and `promo gen plan --run` are the optional fallback that drives those CLIs headless (one-shot, ~1 min each) when you have no generator of your own.
  USE FOR: backgrounds, scenery, macro textures, light leaks / bokeh overlays, dawn/night skies, transition plates between real shots.
  NEVER FOR: app UI, anything that reads as the product, text, logos, people-as-users. `promo check` FAILs a generated clip on a UI shot
  (`generated-plates`) and WARNs for human review (`generated-review`). Image-to-video / reference images are not wired; describe the look in words.

## Pick a style preset first (do not write your own renderer)
Every look is a **style preset**: pacing rules, a caption/card band, typography, transitions and the `promo check` gates
for them. `promo styles` lists them. Scaffold with the one that matches the brief:
- `promo new <name> --style hero`: calm product hero (VO, dark pills in the 9:16-safe zone, cuts on beats). Example projects live in your projects dir.
- `promo new <name> --style anime-opening`: kinetic anime-opening cards on real footage.
- `promo new <name> --style livestream`: talk-show/livestream composite (long holds, lower-left chyron, no flashes).
- `promo new <name> --style horizon`: 20-25 s horizon film (rapid cuts of real surfaces, each shot `type: horizon` with `anchor: {src: [x, y], out_y: 0.58}` putting a real edge on the horizon; show-level `horizon_text: [{words, beats}]` is the ONE serif line that persists across cuts; end with `type: dawn`). A burst (half beats ok) must be followed by a hold >= 3 s. Template: `templates/styles/horizon/promo.yaml`.

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

## STEP 0: Lock the brief and study the references (before any shot list or spec)
A cut that passes every gate can still miss what the person asked for, because it was judged against the agent's OWN summary of the
reference. Structurally prevent that:
1. `promo brief init --project projects/<name> --intent "<the user's request, pasted EXACTLY, never paraphrased>"`. Then fill `must_have` /
   `must_not` / `deliverables` from their words only. `promo brief show` re-prints it: re-read it at the start of every round.
2. For EVERY reference they gave: `promo refs add <url|file> --project projects/<name> --id <id> --why "<their words about it>"`.
   It watches with the transcript (do NOT set `PROMO_WATCH_ASR=0`; without ASR `refs check` FAILs) into `reference/<id>/` and scaffolds `DOSSIER.md`.
3. Fill each dossier by actually reading: every contact sheet, the whole `transcript.json`, the audio metrics (and listen if you can), N full-res cut
   stills. Replace every `TODO:` line with timestamps and quotes; tick the Evidence boxes only for what you did. Sections: narrative beats, people &
   performance, dialogue/VO verbatim, music & sound design, camera & motion, grade & light, on-screen text, pacing numbers, THE one thing that makes
   it work, what is transferable, what is NOT transferable and why. A live-action short with people, voices and sound design is not a "look".
4. **Surface every NOT-transferable item and every clash with the team rules (AGENTS.md: real footage only, no invented claims, ...) to the user as an
   explicit question, and record their answer BEFORE any spec**: `promo brief conflict add --project ... --ref <id> --what ... --rule ...`, ask, then
   `promo brief conflict decide N --decision "<their words>" --by <their name>`. Never decide a conflict yourself, never pick the "closest we can do"
   silently.
5. A human confirms the brief: `promo brief confirm --by <name> --hash <hash from brief show>`. **An agent must never run `confirm` (or `conflict decide`)
   on its own behalf**; ask the person to read the brief and confirm.
6. `promo brief check --project projects/<name>` and `promo refs check --project projects/<name>` must have no FAIL. `promo check` runs the same gates
   (`brief`, `references`, `intent-review`) for every project that has a brief.yaml (WARN without one; FAIL if `style.require_brief: true`).
7. Each draft: `promo compare-ref out/<name>-1080.mp4 --project projects/<name>` (reference row above draft row, speech / LUFS / tempo / cut-rate
   table). The Intent & Reference lens of `evals/council.md` reads it and writes the `intent-check:` line into `rounds/<n>/decision.md`.
   Rubric v2 hard gates: `intent >= 4` and `reference >= 4`.

## Workflow
1. **Brief** (after STEP 0): audience, length, claims, tone. Only claims the footage shows. Write it in `projects/<name>/docs/`.
2. **Shot list**: one line per shot with beats (BPM grid), what the UI shows, caption (short: fits the 608 px 9:16-safe column at 32 px, ~35 chars), SFX/VO. Cuts on beats.
3. **Capture handoff**: give the capturing agent the shot ids + app commit; they follow `capture/README.md` and register each take with
   `promo footage add` (sha256, commit, URL params, dpr). Reference clips by id; never by path.
4. **Spec**: `promo new <name>` scaffolds `projects/<name>/`. Fill `promo.yaml` (timeline, shots, overlays, sfx, vo, mix, qa) and
   `assets.yaml` (music/vo/sfx/font with licence + source_url). Custom shot types go in the project `shots.py` via `@shot_type`.
5. **Build**: `promo build` (idempotent; only changed shots re-render). Iterate on one shot with `promo shot 05`, look with `promo segpeek 05`.
   Heavy steps (build/shot/sfx/music/mix/assemble/contact/check) take a box-wide lock other heavy jobs on the machine can share (set `PROMO_HEAVY_LOCK` to the same path as e.g. your test gates, or `promo config heavy-lock PATH`; default `/tmp/promo-reel-heavy.lock`)
   themselves (`promo/lock.py`) and wait while another job holds it. Run them niced (`nice -n 10 python -m promo ...`);
   do not wrap them in another `flock` and never SIGCONT a paused render.
6. **Check**: `promo check` (exit 1 on FAIL). Fix FAILs; read WARNs (soft upscale, demo footage, short labels) and decide.
7. **Review**: open `out/<name>-1080-contact.png` and the mp4. A human watches every frame that has text, captions or pushes.
   For the final reviewer model, run `promo critique-pack projects/<name>` and hand over the folder it prints
   (`out/critique-pack/`: BRIEF.md with the rubric + hard rules, stills with size sidecars, contact sheet, copy, footage
   manifest.md, earlier reviews, full check output, VO transcript). Do not run or impersonate the reviewer yourself.
   Per-project sources: `critique: {copy: [...], reviews: [...], footage_md: [...]}` in promo.yaml (project-relative paths; no defaults,
   so list the caption / VO-script files and any earlier reviews yourself).
8. **Deliver**: only after human approval. Re-render at 4K with `--scale 2` if asked. Never publish or upload on your own; the one exception is the person's own click to put a draft or final on their Artifacts or Loom (THE FLOW, Upload).

## CLI cheat-sheet
- `promo styles`; `promo new <name> --style hero|anime-opening|livestream`; `promo grid` (bars, beats, markers of `timeline.grid`)
- `promo status [--json]` what is up-to-date / stale / missing; `promo timeline`, `promo assets`, `promo footage list|verify|add`
- `promo build [--shots 05 06] [--force] [--scale 2]`; `promo shot <id...>`; `promo sfx|vo|music|events|mix|assemble|contact`
- `promo brief init|show|check|confirm|conflict --project projects/<name>`; `promo refs add|check|show`; `promo compare-ref <draft.mp4> --project projects/<name>` (STEP 0)
- `promo critique-pack [projects/<name>] [--out DIR] [--no-check] [--video]` (review folder for a reviewer model; holds the lock)
- `promo flow share detect|draft|final [N] --to artifacts|loom --by NAME [--access private|open|shared]` (the person's upload; see THE FLOW)
- `promo check [--json]`; `promo compare <ref.mp4> [--json]` (per-shot PSNR + audio diff vs a reference)
- `promo peek <clip-id> <t> [x0 y0 x1 y1]`, `promo segpeek <shot> [t...]`, `promo mpeek out.png clip:t[:box] ...` (output in build/peek/)
- `promo live2d fetch|render|lag`: offline Live2D hosts for the `livestream` shot type (hosts on one side, screen >= 55 %,
  chat <= 4 lines of host asides only, neutral EP tag, no LIVE/viewer counts, keep-clear rects, `live2d_credits` end card).
  Only Live2D Original Characters; notice + licence rules in `docs/live2d-licences.md`. Heavy renders hold
  the box-wide heavy lock; `--debug` draws keep-clear outlines.
- `--json` prints only JSON on stdout (always has `ok`), logs go to stderr. `promo fetch` downloads licensed assets (sha256 checked).

## Team rules
- **Real footage only.** No invented UI, no generated screens, no stock "app" shots.
- **Never edit the app's UI in post** (no paint-out, inpaint, masking). The spec lint rejects `debubble`/`paint_out`/`inpaint`/`ui_edit`. Reshoot instead.
- **No invented claims**: captions and VO must match what the frame shows (8 tasks = 8 tickets on screen).
- **Licensed audio only**, declared in `assets.yaml` with licence + source_url. `promo build/mix/check` refuse otherwise.
- **Footage is never committed** (no LFS). Provenance lives in `footage/manifest.yaml`; a sha256 mismatch is a stop, not a warning.
- Captions hold >= 2.0 s inside the safe zone (hero); anime cards hold >= 1 bar in the fixed band. No per-caption overrides to make a gate pass: retime it.
- **The user's words and references outrank the agent's summary of them**: brief.yaml `intent_verbatim`, dossiers read from transcript + audio + sheets; conflicts with team rules are the user's call.
- **A human approves before anything is published.**
- Render one shot at a time (ffmpeg `-threads 2`); never two renders at once. No git commit/push unless asked.

## Needs human judgement
Story and claims, caption wording, whether a push-in is soft, whether demo-mode UI is acceptable for the audience, music choice and
licence reading, VO tone, the final watch-through, and publishing. Agents prepare and check; people sign off.
