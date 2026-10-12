---
name: promo-reel
description: Make or update a product promo / demo video from real app footage with the promo-reel repo (declarative promo.yaml, beat-locked edit, music + SFX + VO mix, QA gates), watch a reference video, and generate image/video plates (backgrounds, transitions). Use when asked to build, re-cut, caption, re-capture or check a promo reel, hero video or demo video, to copy the style of a video link, or to make a background / transition / b-roll image or clip.
---

# promo-reel

!`[ -n "$COMMISSION_THREAD_TOKEN" ] && commissionctl mod activate promo-flow >/dev/null 2>&1 && echo "Promo flow pane opened (Preparing). Publish a state to replace it."`

**First action, before any reading or planning:** inside CommissionAI the Promo flow pane and its chat card must exist the moment this skill runs. If the line above did not print "Promo flow pane opened", run `commissionctl mod activate promo-flow` yourself now (idempotent; skip outside CommissionAI). The pane shows an animated "Preparing…" until your first `commissionctl mod publish promo-flow`.

Start with THE FLOW (below). Everything lives in `<save location>/<name>/` (see `promo config output`; default `projects/`) (promo.yaml, assets.yaml, footage/manifest.yaml, shots.py plugin). Run commands from the repo root:
`promo -p projects/<name>/promo.yaml <cmd>` (venv python: `python -m promo ...`).

A thin prompt (`make a promo`) is not a spec. Before capture, run `promo plan <name> --prompt "<their words, verbatim>"`. That writes the one idea (≤10 words), preset (`hero` unless they asked for anime-opening, livestream, or vertical-short), five beats, 60 s master plus the ~20 s feed and ~30 s feature, a six-column shot list, capture defaults and the hook into `promo.yaml` under `plan:`. `vertical-short` / `vertical-short@1` is the locked 9:16 format shell (default an 11 s UI zoom, not the 60 s hero). Contract: `docs/PRODUCT-DEFAULTS.md` (lessons in `docs/lessons/`). Then `promo preview` (540p and stills only), `promo review status`, and `promo build --final` only after Marketing, Zen and Director have signed `reviews/round-N.md` (three rounds, then Patrick). Do not invent claims, URLs or UI to fill a blank. `promo flow` still has its own five council rounds; this gate is the plan's review file.

## THE FLOW (default: use it for every new video; the person stays in the loop)
`promo flow` is a gated state machine (`<project>/flow/flow.json`). It refuses to skip a stage; the person decides four things (style, which scripts go on, the ONE plan review, the draft) and a gate is approved only by their name
(`approve ... --by NAME`, an agent name is refused; an approval goes stale if the thing approved changes). Start: `promo flow init <name> --intent "<their words, exact>"`
(also locks the brief). Every turn: `promo flow status --json` -> do `next`, make what `needs` lists, then put `ask` to the person. **Inside CommissionAI the Stage pane is the question** (`ask_in_stage` true, the `promo-flow` mod open): publish the snapshot, offer `commissionctl next --status needs_you`, and end the turn; their click comes back as a `[mod:promo-flow]` message. Never AskUserQuestion there: it blocks the thread so the click can never arrive, and a second copy in the chat box stays open after they answer in the pane (the host owns the box; you cannot close it). Never sleep or poll for the answer. Outside CommissionAI, AskUserQuestion is the widget.

| # | stage | you do | the person decides |
|---|---|---|---|
| 1 | **discover** | ask style + references (`promo flow discover`, `promo refs add`) | style, refs |
| 2 | **scripts** | write 3+ different scripts; council spars 1-2 rounds (`evals/council-flow.md`); `promo flow script add`, `council scripts` | |
| 3 | **pick** | present the ranked scripts and recommend ONE with `promo flow recommend ID --why "..."` (a pill on its card, your reason in the tooltip; say what it does better than the others, never a claim the footage cannot back) | which 1-2 go on (`approve scripts-picked`) |
| 4 | **storyboard** | per story `flow/boards/<id>/board.json`: every scene with beat, time, action, caption/VO/sound/camera/proof and a **START and END frame**; **MAKE the frames as real images** with `promo flow frames` (a text slate is not a frame and counts as missing); `promo flow board`, SHOW the page | **nothing to approve here.** They can comment on any scene in the Stage at any time (`promo flow scene note`): answer each one by changing the scene, then `scene resolve STORY SCENE --note N --text "what changed"`; open comments block leaving the stage and the plan approval. With the frames real and no comment open, `advance` and go on |
| 5 | **assets** | list ALL assets the cut will use (screenshots, pictures, recordings, music, voice, sfx) with `promo flow asset add`, then **MAKE a real sample of each** with `promo flow asset make`: a concept still, a ~7 s clip, a 20 s music excerpt, a voice read-through, the sfx hits. The person must be able to look at / hear every asset before deciding; a placeholder is not a preview, and `approve assets-approved` is refused until every asset has one | **ONE plan review**: storyboard + assets + the go for drafts. `approve assets-approved --by NAME` (the older `storyboard-approved` / `final-confirmation` names mean the same). Making a planned asset real does not stale it; changing what is planned or the board does |
| 6 | **keyframes** | generate the remaining keyframes, replace every mock (`promo flow needs`) | |
| 7 | **confirm** | no question: the plan approval already was the go; `advance` and build the drafts | |
| 8 | **drafts** | build first drafts, `promo flow draft add`, SHOW them (SendUserFile). From here the Stage's **Edit** tab lets the person cut, swap footage or music, move or mute voice lines and hear it at once; their Render arrives as `promo flow edit render` (only what changed rebuilds; promo/editor.py has the edit language, `edit suggest` answers their "try ..." with edits to preview) | |
| 9 | **review** | <= 5 rounds: `round start --feedback "<verbatim>"`, every note becomes a check, council (lens 0 intent + web research of the topic and examples of good videos), one batch, one draft, measure it, blind-compare it, `round close` (see "Every draft is held to every note" below); at the cap their restated direction is `promo flow revise --feedback "<verbatim>"` (a new cycle) | feedback or `approve draft-approved` |
| 10 | **final** | `final add`; further feedback = `promo flow revise` (new cycle, council again) | |

### Every draft is held to every note (checks, round brief, blind comparison)
- **Notes become checks.** After `round start`, turn each thing the person said into `promo flow check add --what "<what must be true>" --scene ID --source feedback --by NAME`
  (a pin from the Stage, `promo flow pin add`, and an overturned choice, `promo flow assume overturn`, already are one). `--kind gate --gate NAME` reads a `promo check` gate;
  `promo flow look` adds the reference-look check. Only the person retires a check (`check retire ID --why --by NAME`).
- **The round brief.** `flow/rounds/<c>-<n>/BRIEF.md` is rewritten on every change: their words on top, the scoreboard, the drafts that lost, the look, what this
  person said in earlier videos (`promo flow lessons`), recipes that fit (`promo flow recipe list --for ...`; mark one you apply with `recipe use ID`). Every
  maker and reviewer sub-agent reads it FIRST.
- **Measure the new draft.** `draft add FILE --report out/<name>-<tag>-check.json` (the report must be of that file), `promo flow look`, then every judge check marked by
  the council (`check marks --file F --draft N --family claude --by LENS`, JSON lines `{"id","status":"pass|fail","evidence"}`), the hidden control included;
  `promo flow second-opinion` adds grok as a second family (any family's fail wins). A family that calls the control true is discarded until it looks again.
- **Blind comparison.** `promo flow ab drafts` writes two order sheets; give each to a fresh judge sub-agent with QUESTION.md, record `ab judge ID --order 1|2 --pick ...`.
- `round close` refuses while a note is not a check, a check is unmeasured, something the reviewed draft got right broke, the control was not caught, or both orders
  preferred the reviewed draft. Fix it, or `promo flow restore --draft N [--scene ID] --by NAME` (the person's call; `--undo K` reverses a restore).
- **For the person:** `promo flow ab add --question Q --a F --b F` is a blind pick in the Stage; `promo flow assume add "<choice; say so to swap>"` records a choice you
  made without asking as a card they can overturn; `promo flow scout add --story A --scene ID --file PNG --url U` puts the REAL screen in as an app scene's frame
  (`scout miss --why` when it cannot be reached). The person can start `promo flow autopilot` from the Stage: work in passes (`autopilot pass begin` / `pass end`)
  until it reports done, blocked (one `autopilot replan --note` after two passes that fixed nothing) or out of time. `NOTES.md` in the project is the video's
  living memory (`promo flow notes add TEXT` for your own lines): read it first when you resume. `promo flow calibration` says how often the council's verdict
  matched what the person did next.

### After the first draft: edit surgically, never rebuild the video
From the drafts stage on the Stage is an editor (Edit tab: bin, viewer, timeline, inspector) and you edit the same timeline from the CLI. Change only
what the note is about, look and listen to that part, and leave the rest of the film alone:
- **Read**: `promo flow edit timeline` (every shot with beats, times, source, caption, grade, fade, sounds; every voice line; the music and mix; what is built).
- **See**: `promo flow edit look --shot 07` / `--at 41.2` / `--from 40 --to 44 --frames 6`, then read the PNG (a NOT BUILT tile shows the source at t_in).
- **Hear**: `promo flow edit listen --from 40 --to 44 [--stem vo|music|sfx]`: a WAV, loudness, a 0.25 s envelope and the voice lines and sounds in the span.
- **Edit**: `promo flow edit apply --dry-run --file -` first (the promo.yaml diff and the exact build steps that will run), then `apply --by NAME`.
  The language (one per line): swap, trim, move, split, delete, caption, music, bus, vo (at/shot/db/mute/take), sfx add|rm|set, grade (plates only, `ui: false`:
  never the app's pixels), fade, speed, fx (music, vo, vo:LINE, mix), gain (music over beats), import. Full reference: `promo/editor.py`.
- **Check one part fast**: `promo flow edit preview --shot 07` or `--from 38 --to 44` builds only those shots and the sound and cuts a clip with the new mix
  (about 10 s for one changed shot); it shows in the editor for the person. A grade or fade re-encodes the cached render, it never re-renders the shot.
- **Draft**: `promo flow edit render --by NAME` (or `--file -` with edits): only what changed rebuilds, `promo check` runs, the file is kept as
  flow/drafts/dN.mp4 and registered. Moving a built-in shot does not re-render it; swapping back is instant (segment cache).
- **Offer options instead of asking**: `promo flow edit suggest --file - --note "Brighter track, 3 dB lower"`, one per option; the person tries and keeps them.
- A GENERATED promo.yaml: after its generator runs again, `promo flow edit replay --by NAME` puts the logged edits back on top.

### Fan out: spec once, build in parallel, agents review, then the person
The loop is **spec -> parallel build -> agent review -> (repeat) -> person**; the person chooses whether to go round again. Do not do these one at a time.
1. **Spec up front (one batch).** Collect everything in a single `commissionctl ask` / AskUserQuestion (with the mod open, leave out what the pane's gate already asks, e.g. the style; ask only the rest): style, references, must-show, must-not-claim, length, platforms, end card. Do not drip questions across stages. Then run reference study (`promo refs add`, one sub-agent per reference) in parallel with writing scripts.
2. **Build in parallel.** Spawn independent sub-agents in ONE message: one script writer per angle; one board per picked story; per-asset-kind makers (stills, clips, voices, music, sfx). `promo flow make --jobs N` already draws frames and asset samples N at a time (default 3). Captures of the real app are the person's: ask for the whole list at once, and keep generating everything else while they record. Renders are different: ffmpeg shots run one at a time under the heavy lock, but prepare sfx, VO and music alongside shot renders.
3. **Agent review before the person sees it.** Run the council lenses as parallel background sub-agents, merge into ONE batch, rebuild, re-check. Repeat up to 2 internal passes (they do not use the person's 5 rounds) until no high-severity finding is left and `promo check` passes. Post `promo flow note` lines for each pass. Their reports arrive as notifications: never `sleep`, never poll their output files in a loop; do other work (the next script, the board) or end the turn with a note until they return.
4. **Person review.** Show the draft. They approve, or send feedback: that starts `promo flow round start` and goes back to step 2 for the changed parts only. Never start another loop on your own.
Post a `promo flow note` at every fan-out and fan-in so the Stage shows what is running.

**Content on request (the person is in charge of size and detail).** The Stage's Plan tab and Storyboard tab let them ask for more, and you answer with real content, any length:
`promo flow script add|append` (a script in as many parts as it needs, `--file -` for stdin), `promo flow doc add|append|new|list|rm|templates` (planning documents: full script, shot list, edit plan, audio plan, capture checklist, claims, deliverables, schedule, treatment, director's notes; `doc new KIND` builds one from the real board and assets), `promo flow plan pack` (all of them at once, per story), `promo flow widget add|layout|list|rm|example` (dynamic panels in the Stage for what the fixed tabs do not show, e.g. a Blender render queue or a model viewer: `blocks` JSON the Stage draws, or sandboxed `html`; you choose place, span, height, order; `widget example blocks|html` prints a starter), `promo flow story|scene add|set|rm|list` (edit a storyboard without JSON), `promo flow density --every 5` (frames on a time grid; then `promo flow frames`). Details and the exact reaction to each `[mod:promo-flow]` message: `mods/promo-flow/agent/SKILL.md`. Documents are not gates, but every claim in them follows rule 3.

**Never ask for a decision on a placeholder.** `promo flow make` makes everything the person has to see (frames, then asset samples) in one go via the logged-in grok / codex CLIs (`promo gen detect`; ~25 s per image, 3 at a time); `promo flow needs` lists what is still missing. Samples are planning material, labelled SAMPLE in the Stage, and never enter the footage manifest. If the person clicks "Ask the agent to make them" you get `[mod:promo-flow] ... wants the real thing made`: run `promo flow make`, publish.

Session UI: `status --json` carries the `ask` payload (question + options) for the host's question widget outside CommissionAI, and `ask_in_stage` (the Stage pane already asks the same thing: do not ask in chat too); `promo flow board` writes the dashboard HTML (stepper, scripts, storyboards with
start->end frames, the asset gallery, drafts, rounds): publish it as an Artifact or show it as a widget so the person SEES the plan. Inside CommissionAI the widget is the `promo-flow` mod (`mods/promo-flow/`, README there): every `promo flow` command that changes the flow publishes the new state itself (`Stage updated`), `promo flow publish` does it on demand, and the person's clicks arrive as `[mod:promo-flow] ...` messages. Slash command: `/promo-flow` (`.claude/commands/promo-flow.md`).
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
  5. Seedance on the person's OpenRouter key (pay per job, never picked by `auto`): `promo gen models` (prices), then
     `commissionctl secret exec OPENROUTER_API_KEY -- promo gen video "..." --out F --provider openrouter [--model M --res 480p --seconds 4 --first-frame IMG]`
     (`--dry-run` prices it without sending). If the key is not saved, that command opens the secure key box for the person by itself; never wait for them to ask for it. Each job is refused over `--max-usd` (default $0.50) or the daily cap (PROMO_GEN_DAILY_USD, default $2);
     `promo gen spend` shows the ledger. Draft at 480p, then the final from the same prompt and `--seed` (`--last-frame IMG` on models that list one).
     In the flow the person does this themselves in the Stage's **Studio** tab (promo/studio.py): takes are samples until registered.
     `promo flow studio run` (`--start` / `--end` frames), `rerun --take tN --res 720p` (the final: the take's stored request resent, only
     the resolution changed; the Stage confirms the price first), `restyle --take tN --prompt "make it dusk"` (FLUX Video Edit; Studio takes
     and generated plates only, a screen recording is refused), `swap --take tN|FILE --prompt "who goes in" [--prep face_mesh|depth|depth_mesh|none]`
     (local prep on this Mac, then Seedance 2.5 on OpenRouter; Higgsfield is not used; any clip but the product's own recordings), `frame` / `suggest --frame ID --prompt "..."` (on "Describe this frame" you
     write the frame's setting: place, light, lens, mood, never screens, text or logos), `use`. A picked frame must be ticked as checked
     before Generate turns on. The Studio also lists "Grok (your subscription)" (`--model cli:grok`, the default when grok is logged in):
     the grok CLI animates a still on the person's own plan, nothing billed per clip. Codex has an image tool only (no video): use it for stills and start frames.
  6. Depth on this Mac (free, nothing sent): `promo depth map IMG` (Depth Anything V2 Small, ONNX) and `promo depth parallax IMG --out F.mp4
     [--move push|pull|orbit|pan_left|pan_right|crane|handheld|static --amount 1 --focus 0.5 --blur 4 --size 1920x1080]`: a 2.5D camera move
     over a generated still (it needs the still's `.gen.json` sidecar; a screenshot is refused) with its own generated sidecar, ~10 s of render
     per second of 1080p. In the Studio it is the model "Depth parallax" (`--model local:depth --start STORY/SCENE/start`).
  USE FOR: backgrounds, scenery, macro textures, light leaks / bokeh overlays, dawn/night skies, transition plates between real shots.
  NEVER FOR: app UI, anything that reads as the product, text, logos, people-as-users. `promo check` FAILs a generated clip on a UI shot
  (`generated-plates`) and WARNs for human review (`generated-review`). Image to video is the Studio's start frame (`--first-frame` on
  `promo gen video`); reference images (style guidance) are not wired, so describe the look in words.

## Thin prompt + stills: the designed plan (`promo plan --stills`)
A few lines of prompt, two or three real stills and a length is enough. `promo plan NAME --prompt "..." --stills a.png b.png` writes
`plan.designed`: per-shot framing (floating panel primary, device for context, fullscreen only for real peak action, plate for type),
kinetic cards (only the person's own words), non-UI plate prompts (`promo gen plan`), the length band and the spine, plus at most
**three** co-spec questions (`promo cospec`: the dialect only if ambiguous, the end card GitHub vs landing, the one promise, the audience).
`promo designed apply NAME` compiles it to `cinema` shots; `promo check` adds the `designed-*` gates.
Two dialects: **ethereal** (default for a thin prompt: breathable holds, micro snaps, sparse type as UI, small panels on pastel plates,
music-led, no fullscreen, no whip / shake / blur) and **kinetic** (dense cuts, big type locked to the VO, accelerating recap). Pick with
`--dialect`, a `dialect:` line or the prompt's words. `--default cta="..."` is a team default for the end card, flagged for the product
owner to confirm. Never invent claims, numbers, URLs or UI; abstraction is done in type, never by drawing UI (an open question for
Patrick is recorded in `plan.designed.conflicts`). Details, the runbook and the evals: `docs/thin-prompt-quality.md`.

## Pick a style preset first (do not write your own renderer)
Every look is a **style preset**: pacing rules, a caption/card band, typography, transitions and the `promo check` gates
for them. `promo styles` lists them. Scaffold with the one that matches the brief:
- `promo new <name> --style hero`: calm product hero (VO, dark pills in the 9:16-safe zone, cuts on beats). Example projects live in your projects dir.
- `promo new <name> --style anime-opening`: kinetic anime-opening cards on real footage.
- `promo new <name> --style livestream`: talk-show/livestream composite (long holds, lower-left chyron, no flashes).
- `promo new <name> --style podcast`: Live2D hosts talking over the real app, overlaid on the picture with no box (see "Podcast / VTuber videos" below).
- `promo new <name> --style horizon`: 20-25 s horizon film (rapid cuts of real surfaces, each shot `type: horizon` with `anchor: {src: [x, y], out_y: 0.58}` putting a real edge on the horizon; show-level `horizon_text: [{words, beats}]` is the ONE serif line that persists across cuts; end with `type: dawn`). A burst (half beats ok) must be followed by a hold >= 3 s. Template: `templates/styles/horizon/promo.yaml`.

- `promo new <name> --style anime-mv`: an anime MUSIC VIDEO for a song (no app footage): letterboxed drawn shots, lyrics under the picture (see "Anime music videos" below).
- `promo new <name> --style vertical-short`: locked `vertical-short@1` format shell. 9:16, captions only, about 6–20 s. The plan default is a 10–12 s UI zoom (one real capture, one zoom, one caption; logo never, or the last 1 s). Craft loop and before/after are the other shells. Quote card and talking head are parked. No content batch. See `docs/PRODUCT-DEFAULTS.md`.

If the brief says "anime", "opening", "kinetic titles", "J-rock", "speed lines" or "title cards", it is **anime-opening** (a music video for a song, MV, PV or lyric video is **anime-mv**):
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

## Podcast / VTuber videos (style `podcast`)
If the request says **podcast, vtuber, live2d, avatar(s), hosts, co-hosts or talk show**, it is the `podcast` style (in THE FLOW the
style card "Podcast with animated hosts" is marked suggested for such a request). Recipe:
1. `promo new <name> --style podcast`, then add real footage (`promo footage add`, or copy an earlier project's manifest entry) and list it
   under `podcast.screens` in the order the talk needs it. Set the hosts: `podcast.hosts: [{id, model, name, color, voice: {engine, voice}}]`.
2. Write the dialogue from the prompt as a YAML list and store it: `promo podcast script --file lines.yaml` (or `-` for stdin). One line =
   `{host, text, mood?, gesture?, look?, react?, pause?, scene?, evidence?, claim?}`.
   - mood: neutral | happy | laugh | excited | thinking | surprised | smug | sad | serious (`happy:0.6` = lighter). Eased in, held through the line.
   - gesture: nod | shake | tilt | lean_in | laugh_bounce | shrug | look_away, or `motion:<name>` (the model's own motions: `promo live2d models`).
   - look: camera | partner | screen | away. `react: happy` = how the OTHER host reacts while this line is spoken.
   - scene: `{layout: two-shot, next_screen: true}` or `{screen: <clip id>}` starts a new shot at this line.
   - Rule 3 holds: a line with a number or an absolute claim needs `evidence:` (what on screen proves it, with a time); banter gets `claim: false`.
3. `promo podcast plan`: voices every line (per-host voices, cached per text), lays them back to back on a half-beat grid, writes vo.lines,
   the timeline and the shots (the show layout, a new shot per `scene:`, a speaker cam on short laugh / surprised / excited lines, the credits
   card). It runs once; `--force` re-plans from `podcast.script`. Then promo.yaml is an ordinary spec: line up footage with what is said
   (`t_in`, `speed`), check where lines fall against what the take shows.
4. `promo podcast preview --layouts`: REAL previews in flow/podcast/ (Live2D renders over a real frame, a mood sheet and a voice sample per host).
   Look at them before asking anything. Publish: the Stage's Cast card shows them.
5. `promo build`, `promo check` (gates `podcast-licence`, `podcast-framing` (no head clipped, no face covered, hosts and subtitles off
   `keep_clear`, measured on each host's real outline), `podcast-subtitles` (<= 35 chars, >= 2 s), `podcast-lint` (no LIVE, no viewer
   counts), `podcast-voice-licence`, `podcast-truth`; WARN `draft-voice`, `voice-licence-open`, `podcast-overlap`).
Layouts: `overlay` (default: hosts stand on the app at the bottom corners, the bust cut by the frame edge, no panel), `boxed` (app window +
host panels, the livestream look), `two-shot` (both hosts big, app in a window), `speaker` (one host big, cuts to whoever talks at line starts).
A box is a choice, never the default: `frame: card | circle | soft` (show or shot), `edge: shadow | glow | rim | none` (drawn from the avatar's
own alpha). Small edits: `promo podcast set host a place=bottom-right size=xl | layout speaker --shot 03 | frame card | backdrop blur | subtitles off`.
The Stage's Cast card sends exactly those as the `podcast` action; run them, re-run preview, publish.
Voices: `kokoro` (Apache-2.0, the publishable default), `say` (macOS, drafts only: needs an assets entry, WARNs), `voicestudio` (a local
profile; the model is CC-BY-NC, an open licence question: WARNs). Every voice has an assets.yaml licence entry (rule 4).
Characters: the free Live2D samples (Mao: A/I/U/E/O vowel mouth shapes + 8 expressions; Hiyori: standard parameters) look good but are not
commissioned-VTuber art. For that level the person brings their own model: `promo live2d add <model3.json|dir> --id ID --name N --type
own|commissioned|original --licence TEXT --source URL [--credit T]` registers it (files stay where they are, never committed), measures its
framing anchors from renders and maps moods by expression names; check it with `promo live2d stills --model ID --moods --out sheet.png`.
Collaboration and third-party characters are refused. Sample models need the `live2d_credits` end card (gated); so does any credited model.

## The person as a corner avatar (own voice + own face)
For "my voice and my face in a small box over the screen" (AGENTS.md rule 1 own-likeness carve-out; consent first, as a `brief conflict`).
Worked example and tools: `projects/me-avatar-poc` (`tools/narration.py`, `tools/avatar.sh`, NOTES.md) and `~/work/avatar-poc` (venvs, patched Ditto).
1. Voice: clone from a 5-8 s cut of whole sentences of their recording. Chatterbox (MIT, PyTorch MPS; `exaggeration`, Turbo `[chuckle]`
   tags) or Qwen3-TTS 1.7B Base (Apache-2.0, MLX, fastest). Make several takes per line, keep those that read back word for word, pick by ear.
   The takes go in through `vo: {engine: files}`.
2. Face: one sharp frontal selfie (`osxphotos export --selfie --download-missing --use-photokit`, rank by face size, sharpness and yaw).
   Ditto (Apache-2.0) on MPS with `DITTO_FACE_INIT=mediapipe` (its InsightFace finder is non-commercial), driven by the whole narration
   laid on the show timeline, ~3.7x real time at 768². Register it with `generated: {likeness: own, consent: "<who, when>"}`.
3. Put it on any shot as `{type: avatar, source: <id>, t_in: <show time at the shot's start>, label: "AI voice + face"}`; `promo check`
   `generated-plates` FAILs a likeness anywhere else or without consent. Re-render the avatar whenever VO timing changes.

## Anime music videos (style `anime-mv`)
If the request is a **music video, MV, PV, lyric video or a song told in pictures** (in THE FLOW the "Anime music video" card is marked
suggested), it is `anime-mv`. Measured on Eve 「心海」: a 2.35:1 picture band on a cream page (y 131-949 of 1080), ONE small tracked Mincho
lyric line under it (ink y 996-1028), flat-cel characters over painted backgrounds, drawings held on 2s, median shot ~1.5 s with half-beat
bursts, petals / bubbles, whiteouts and ink wipes on big cuts. No product UI ever (every shot `type: mv`, gate mv-shots). Recipe:
1. `promo new <name> --style anime-mv`; the song in assets.yaml. A song the person has no licence for may go in as `test_only: true` for an
   internal test only: `promo check` WARNs test-audio, the assembled video carries a burned-in TEST watermark, share / final are refused.
2. `promo music analyse song.wav --from S --to S [--bpm 143] --mark verse=40.9 --mark chorus=79.0 --out music/grid.json`: the beat grid
   (comb fit on the onset envelope; `beat contrast` well above 1 = on the beat), bars, sections by ear (the loudness guess is weak on
   compressed pop), and the `music:` block that cuts the excerpt on bar lines. Then `timeline: {grid: music/grid.json, beats: N}`.
3. Lyrics: `promo lyrics import song.srt|.lrc|.txt -p promo.yaml` (music-file times mapped through the edit), then `promo lyrics align`
   (faster-whisper large-v3, Japanese, fuzzy per-character match: ASR kanji mistakes only cost the characters they touch; `--words asr.json`
   reuses a run). On a full mix Whisper's line starts drift 0.5-1 s on singing: `--separate` transcribes the HTDemucs vocal stem
   (needs demucs + torch on PYTHONPATH) and moves each phrase start past the breath Whisper glues onto its first word; start lines on
   that measure (`lyric N at=`) so they are never late. Lines under 0.8 s fail lyrics-hold: merge them into the next line. Layouts band | center | vertical (tategaki) | big;
   anims fade | type | ink | none. Gates: lyrics-glyphs (no tofu), lyrics-safe, lyrics-hold, lyrics-overlap, lyrics-sync (> 0.25 s off the voice).
4. The look bible BEFORE any shot: one style paragraph + the cast + palette + a character sheet and a style frame drawn first (grok
   image_edit from a first sheet keeps the heroine on-model; crop the generator's corner logo off the refs). Words alone give
   generic TV-anime shading; to reach a reference's look, give 2-3 of its stills as `--ref style=...` (style-only refs, internal
   tests) and redraw the character sheet through them first, then draw every plate from that sheet. Watch for borrowed details
   (a badge, a hairstyle) and prompt them away. `promo mv bible --prompt ...
   --ref character=bible/sheet.png --ref style=bible/style.png --cast hero="..."`. Every plate prompt is bible + cast + scene.
5. Shots: `{type: mv, beats, plate: {kind: video|still, cast: [hero], prompt, motion}, fill: [r,g,b] (shown until a take exists),
   cam (stills drift), frame_step: 2, particles: {kind: petals|bubbles|motes|snow|rain}, fx_in / fx_out: whiteout|flash|ink|iris|smear|rgb,
   frame: full (title cards), words: [{text, t, layout: big}]}`. Vary the framing on purpose (extreme close-ups of hands / eyes / feet, high
   and low angles, the heroine off-centre or small): the character sheet pulls every keyframe towards a centred front view.
6. `promo mv gen -p promo.yaml --missing --jobs 4`: per shot a keyframe (`key-tN.png`) then, for `kind: video`, grok image_to_video at 720p
   (`clip-tN.mp4`), registered as footage `k<shot>-tN` / `v<shot>-tN` with the bible id. A shot's first take goes in; later takes wait for
   `promo mv use SHOT TAKE` (or the Stage); after a bible change and a full `promo mv gen`, `promo mv use --latest` adopts every new take. ~25 s per keyframe, ~80 s per clip, 4 at a time. `promo mv plan` lists prompts, takes, stale takes.
7. `promo build`, `promo check` (mv-shots, mv-cuts, mv-hold, mv-median, mv-flashes, mv-plates, look-bible, the lyric gates, test-audio).
The Stage editor shows a Lyrics lane (drag / trim snaps to 1/4 beat, Alt = free; double-click edits the words), the song's sections and bar
numbers on the ruler, and for an mv shot its takes, plate prompt, "Generate another take" (action `plate_gen`) and look keys; the look bible
card sends `bible`. Edit language: `lyric add|N ...|N rm|N sync`, `plate SHOT take=|prompt=|motion=|kind=`, `look SHOT step= particles=
fx_in= fx_out= frame=`, `marker NAME at=|rm`. Be honest about the ceiling: generated motion is limited (hair, cloth, blinks, camera), so the
edit, the lyrics and the frame carry the music; say so in the review note.

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
3. **Capture**: the agent records (never the person): shot ids + app commit go to the capturing agent (you, or a sub-agent); it follows `capture/README.md` and register each take with
   `promo footage add` (sha256, commit, URL params, dpr). Reference clips by id; never by path. Record with the paint-safe kit
   (`capture/lib/`: native-DPR screenshots, settled frames); `footage add` warns and `promo check` fails `footage-glitch` on
   one-frame half-painted frames, and the fix is a re-take (`promo footage scan` to re-check).
4. **Spec**: `promo new <name>` scaffolds `projects/<name>/`. Fill `promo.yaml` (timeline, shots, overlays, sfx, vo, mix, qa) and
   `assets.yaml` (music/vo/sfx/font with licence + source_url). Custom shot types go in the project `shots.py` via `@shot_type`.
   **Sound character** (old radio, tape, telephone, vinyl): never hand-roll it in a project script or fake it with a noise bed. Set `fx:` on
   `vo` (or one line), `music` or `mix` (the whole mix): `fx: vintage`, or `{preset: radio, amount: [[0, 1], [35, 0]], hiss: {db: -48}}`
   (amount keyframes in film seconds; `promo fx list` shows each preset's stages). A steady light crackle under everything = `mix: {fx: crackle}`. The character is in the sound itself, the noise stays
   50-60 dB under it. Before you commit to one, `promo fx audition <voice.wav>` renders every preset to compare by ear.
5. **Build**: `promo build` (idempotent; only changed shots re-render). It starts with a quick look: the start, middle and end of every shot
   that will render, drawn without encoding (~1 min for a whole cut), then replaces each still with the render's own frame as it gets there
   (`build/thumbs/<id>-a|b|c.jpg`). `promo strip --out shots/strip.png` puts every scene's three stills in one image: post it in the chat as soon
   as the quick look lands and again every few scenes, so the person can stop a scene they dislike before the whole draft renders.
   `promo build --look` draws only the quick look; `--no-look` skips it. Iterate on one shot with `promo shot 05`, look with `promo segpeek 05`.
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
- `promo styles`; `promo new <name> --style hero|anime-opening|livestream|podcast`; `promo grid` (bars, beats, markers of `timeline.grid`)
- `promo podcast script|plan|set|preview|status -p <project>`: a podcast / VTuber show from a script (section above)
- `promo status [--json]` what is up-to-date / stale / missing; `promo timeline`, `promo assets`, `promo footage list|verify|add`
- `promo build [--shots 05 06] [--force] [--scale 2] [--look | --no-look]`; `promo strip [--shots ..] [--out F.png]`; `promo shot <id...>`; `promo sfx|vo|music|events|mix|assemble|contact`
- `promo fx list | apply IN OUT --preset P [--amount A] [--set stage.param=V] | audition IN [--out DIR]` (radio / tape / vintage / telephone / vinyl / crackle on any file)
- `promo brief init|show|check|confirm|conflict --project projects/<name>`; `promo refs add|check|show`; `promo compare-ref <draft.mp4> --project projects/<name>` (STEP 0)
- `promo critique-pack [projects/<name>] [--out DIR] [--no-check] [--video]` (review folder for a reviewer model; holds the lock)
- `promo flow share detect|draft|final [N] --to artifacts|loom --by NAME [--access private|open|shared]` (the person's upload; see THE FLOW)
- `promo check [--json]`; `promo compare <ref.mp4> [--json]` (per-shot PSNR + audio diff vs a reference)
- `promo peek <clip-id> <t> [x0 y0 x1 y1]`, `promo segpeek <shot> [t...]`, `promo mpeek out.png clip:t[:box] ...` (output in build/peek/)
- `promo live2d models | add | stills --model ID --moods`: models (samples + your own), register your own, a real mood sheet.
- `promo live2d fetch|render|lag`: offline Live2D hosts for the `livestream` and `podcast` shot types (livestream: hosts on one side, screen >= 55 %,
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
