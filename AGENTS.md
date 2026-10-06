# AGENTS.md: how to make a product promo video with promo-reel

Short version for agents: `skills/promo-reel/SKILL.md`. Capture-script contract: `capture/README.md`. Start a project from `templates/new-project` or `promo new <name> --style X` (example projects live in your projects dir, not in this repo). Where new projects are saved is a user setting, `promo config output` (e.g. `~/.promo-reel/{project}/{slug}`, `./promo-reel/{slug}` or a folder on an external drive); never write project files into the repo you are working in unless that is the chosen location.

This file is the operating manual for any AI agent (or human) picking up a promo-video job.
Read it top to bottom before touching footage. The pipeline is mechanical; taste and truth are not.
Where a step needs a human, it says **HUMAN**.

> **New videos run through `promo flow`** (gated: discover, scripts, pick, storyboard, asset plan, keyframes, confirm, drafts, <= 5 council rounds, final; the person
> approves every gate). See `skills/promo-reel/SKILL.md` THE FLOW and `evals/council-flow.md`. Sections 1-8 below are the details behind its stages. The person can ask the Stage for more at any time: a full script of any length, a shot list / edit plan / audio plan / capture checklist, the whole production pack (`promo flow plan pack`), more storyboard detail (`promo flow density --every 5`); see `skills/promo-reel/SKILL.md`.

## 0. Team rules (non-negotiable)
1. **Real footage only.** Every UI frame comes from a real screen recording of the product (a real run, or the product's built-in demo mode, labelled internally as demo). No mock-ups, no AI-generated UI, no generative video of the product.
   **Carve-out (Patrick, 5 Oct 2026):** AI-generated *non-UI plates* (backgrounds, transitions, scenery, macro textures; no text, logos, screens or anything that reads as the product) are allowed via `promo gen`. Video plates go through this ACP agent's Higgsfield or Runway connectors (`skills/promo-video-route/SKILL.md`); grok / codex CLIs remain the headless fallback. They sit only on shots marked `ui: false`, carry `generated:` in the footage manifest, are flagged for human review by `promo check` (`generated-plates` FAIL on a UI shot, `generated-review` WARN), and are never described in captions as the product.
2. **Never edit the app's UI in post.** No paint-outs, inpainting, retouching text/numbers, hiding elements by cloning. If something on screen is wrong or distracting (a bug, a stray badge, wrong project, a speech bubble), **reshoot** or **reframe** (crop it out with the camera box). The spec linter rejects `debubble` / `paint_out` / `inpaint` / `ui_edit` keys.
3. **No invented claims.** Captions and VO may only state what the footage shows or what the product verifiably does today. Numbers ("8 tasks · 3 agents") must be true for the recorded run. No benchmarks, no "24/7", no features that are not shipped. Keep a note of the evidence (commit, run, screenshot) next to each claim in the shot list.
4. **Licensed audio only.** Every music track, VO model/voice and SFX has an entry in `assets.yaml` with a licence and a source URL; `promo build` and `promo check` fail otherwise. Do not commit files whose licence forbids standalone redistribution (e.g. Pixabay music): store the manifest entry + `fetch_url` + `sha256`, and run `promo fetch`.
5. **A human approves before anything is published.** Agents build and check drafts; they never upload, post, or send the video anywhere. Deliver files + the check report + contact sheet and ask for review.
   **Carve-out (requested 6 Oct 2026):** the person can put a draft or the final on their own Atlassian Artifacts or Loom from the Stage, when their `twg` is signed in and the product is there (`promo flow share ... --by NAME`; an agent name is refused). The agent runs it only on their click or explicit request, access stays private unless they ask for more, and nothing is posted anywhere else.

6. **The brief and the references outrank your own summary.** Paste the user's request verbatim into `projects/<name>/brief.yaml`
   (`promo brief init`), study each reference for real (`promo refs add`: transcript, audio, sheets, a filled DOSSIER.md), and put every
   clash between a reference and rules 1-5 to the user as a question with the answer recorded (`promo brief conflict`) BEFORE any spec. Never confirm
   the brief yourself. Every review round starts by re-reading it and ends with the Intent & Reference lens's `intent-check:` line.

## 1. Brief (HUMAN input, agent drafts)
Step 0, before this section: `promo brief init`, `promo refs add`, filled dossiers, conflicts decided (see `skills/promo-reel/SKILL.md` STEP 0).
Get or write a one-page brief (its source of truth is `brief.yaml`, the user's exact words, never your paraphrase): product, audience, the one idea (e.g. "tell it at night, wake up to merged PRs"), length (default 60 s 16:9 master; cutdowns later), platforms, tone, must-show features, must-not-claim list, end-card text (name, tagline, requirements, URL or "URL off").
Draft it yourself from the product README/repo if needed, then get the app owner to confirm the claims list.

## 2. Shot list
Write `shot-list.md`: one row per shot with time, beats, the real screen to capture, the on-screen caption, the camera move, the music moment, and **the evidence** for any claim. Start from `templates/new-project` / `promo new <name> --style X`; a finished project's `docs/` in your projects dir is the best worked example.
- Plan cuts on the music's beat grid (pick the track first, or pick a BPM: 98 BPM -> 0.612 s per beat; 60 s = 98 beats).
- Captions: short (<= ~35 characters so they fit the 9:16-safe 608 px column at 32 px), each held >= 2 s, one fixed lower-middle zone; dark see-through pill on UI shots, white pill over scenic/illustrative shots.
- Mark every caption/VO line with what proves it.

## 3. Capture (ask the app owner; **HUMAN** usually records)
What to ask for, per shot:
- **Resolution:** record at **2x device-pixel density** (Retina / DPR 2) with the window sized so the capture is **3840x2160** (or larger). Push-ins of 2-3x on 1080p sources are upscales and look soft; DPR2 sources keep text sharp at 1080 and allow a native **4K** master (`--scale 2`).
- **Frame rate:** 60 fps screen capture (30 fps output; the renderer picks frames / blends for speed-ups).
- **State:** a real run or the documented demo mode with true numbers; clean data (right project name, no test junk, no personal data, no API keys/emails); notifications off; cursor hidden unless the shot is about a click; system clock/theme consistent across takes.
- **Dwell:** start each take ~1 s before the action and hold ~2 s after it (captions need >= 2 s holds; the editor needs handles).
- **Distractions:** if the UI shows something that must not appear (bubbles, badges, cost counters, wrong project), ask for a reshoot with it disabled, or plan a crop that excludes it. Never fix it in post.
- **Stills:** full-resolution PNG screenshots for card/tile shots.
- **Handoff = the footage manifest.** Media stays on the box (never git, never LFS). The capturing agent registers every take in `projects/<name>/footage/manifest.yaml` with `promo footage add <abs path> --id ... --shots ... --commit <full app SHA> --capture '<URL params>' --framing '...' --dpr 2 [--demo]` (computes sha256, probes resolution/fps, refreshes the table in `manifest.md`). Capture scripts follow `capture/README.md`. `promo build` refuses to run if a referenced clip is missing or its sha256 changed.

## 4. Spec
Pick the **style preset** first (`promo styles`): `hero` (calm VO-led hero), `anime-opening` (kinetic cards, bar-snapped cuts from a music grid, one fixed lower-third band, flashes/speed lines only at cuts), `livestream` (long holds, chyron, no flashes). `cinematic-story` (short-film look: real UI as a contained depth-of-field panel over a blurred copy of itself, warm low-key grade/bloom/grain on the backdrop only so UI pixels are never graded, slow camera, fades, sparse serif copy; shot type `cinema`, look in `promo/grade.py`). `promo new my-promo --style anime-opening` scaffolds a working spec for that look; the preset's gates run in `promo check`. `horizon` (Opus-5.5-style film: rapid cuts of real surfaces each framed on a real edge, one serif line on the horizon across the cuts, held dawn end card; `promo/shots/horizon.py`). Do not write a bespoke renderer for a style: extend the preset (`promo/styles.py`, `promo/shots/anime.py`) with a test.
`promo new my-promo` scaffolds `projects/my-promo/` (`promo.yaml`, `assets.yaml`, `footage/manifest.yaml` + `manifest.md`). Fill in:
- `output` (name, resolution 1080|2160, fps, duration), `timeline` (bpm, beats), `style` (font, caption zone).
- `shots`: id, `beats: [start, end]`, `type` (`clip`, `card`, or a project plugin type from `shots.py`), `source: <clip id from footage/manifest.yaml>` + `t_in`/`speed` or `segs`, camera keys `cam: [[t, cx, cy, w], ...]` (normalised: centre x/y and box width as a fraction of the source width; smaller w = tighter), overlays (`caption`, `text`, `pill`, `scrim`), `sfx` events, `contact_at`.
- `music` (asset, bpm, track grid, edit segments on bar lines), `vo` (engine, voice, lines with shot + `at`), `sfx` library, `mix` (bus levels, ducking, masters), `qa` thresholds.
Talk-show layouts with Live2D hosts use the `livestream` shot type plus a show-level `livestream:` block. See
`projects/live2d-demo/promo.yaml`, `live2d/README.md` and **`docs/live2d-licences.md`**. Only Live2D Original
Characters are allowed; the copyright notice goes on the `live2d_credits` end card (gated) and in the description.
Never fake an audience: chat lines are the hosts' own asides (or the strip carries a visible `scripted_label`), no
LIVE badge, no viewer counts. **HUMAN:** confirm that the publisher
is a General User or Small-Scale Enterprise (sales below JPY 10M) or holds Live2D's written approval.
Use `promo peek <src> <t>` / `promo mpeek` (normalised grid overlays) to read coordinates for camera boxes and anchors off real frames. Bespoke shot types go in the project's `shots.py` (see the example's composer / rail_labels / tilt_card / float_window / tiles).

## 5. Build
```
promo -p projects/<name>/promo.yaml assets        # licence gate (fails on missing licence/source URL)
promo -p projects/<name>/promo.yaml fetch         # download music/models listed with fetch_url (sha256-verified)
promo -p projects/<name>/promo.yaml build         # sfx -> vo -> music -> changed shots -> events -> mix -> assemble -> contact
promo -p projects/<name>/promo.yaml shot 05 10    # iterate on single shots, then `build` again (only changed steps rerun)
promo -p projects/<name>/promo.yaml --scale 2 build   # 3840x2160 master from the same spec
```
Builds are idempotent: each step stamps a hash of its inputs and is skipped when nothing changed. `--force` rebuilds.

## 6. Check (automated gates)
`promo check` must pass (exit 0) before review. Gates: asset licences + spec lint, footage present + sha256 match (WARN on DPR1 sources pushed >1.5x and on demo-mode footage), duration, resolution/fps/frame count, loudness and true peak per master, every cut on the beat grid, caption hold >= 2 s, captions inside the safe zone, contact sheet generated, VO transcribed back and matched word-for-word to the script (skipped with a warning if whisper is not installed), and build freshness. Report: `out/<name>-<tag>-check.json`; `promo check --json` / `promo status --json` print machine-readable results (stdout only, always with `ok`).

## 7. Review (**HUMAN / visual judgement**; the agent prepares, does not decide)
Look at the contact sheet and watch the whole video with sound before asking for review. Things no gate can judge:
- Is every caption/VO claim true for this footage? Does any frame show something wrong (wrong project/PR, stale data, errors, personal data, cost figures)?
- Legibility: is UI text sharp enough at the push-in used (upscale softness)? Do captions cover anything important?
- Pacing and taste: does each cut land on a musical moment, does VO sit clear of the music, is the SFX tasteful, does the story read with the sound off?
- Colour/brand: fonts, colours, end card text and URL.
Write a short review note (open items, what's demo footage, what's old footage) like the `docs/` review notes of an earlier project in your projects dir.
For a reviewer model (e.g. Claude in Cursor), `promo critique-pack projects/<name>` writes `out/critique-pack/`: BRIEF.md (rubric:
hook, legibility, story, pacing, calm composition, style fidelity, polish 1-5 + truth pass/fail; pass = truth pass, nothing under 3,
average >= 4.2; the hard rules), TEXT-LINES.md, full-res stills per shot and per text card with sidecar JSON (measured cap-height px
and effective scale of every card and `named:` element), the contact sheet, copy files, footage manifest.md, earlier reviews, the full
`promo check` output and the VO whisper transcript. The agent prepares the pack; it does not run the reviewer.

## 8. Deliver
Hand over: `out/<name>-1080.mp4` (web, -14 LUFS), `out/<name>-1080-social.mp4` (~-9 LUFS), optional 2160 master, contact sheet, check report, EDL.md, licence/credit lines from `assets.yaml`. **Do not publish**; a human approves and posts.

## What is mechanical vs what needs judgement
| Mechanical (pipeline does it) | Needs a human / visual judgement |
|---|---|
| Beat-locked timeline, frame-exact segments | Choosing the story, shots and music |
| Eased crop/push-in, captions in the fixed zone | Picking camera boxes that frame the right UI and exclude distractions |
| Music edit to length on bar lines, ducking, mastering | Whether the edit points sound musical |
| SFX placement from declared events | Which moments deserve a sound |
| TTS VO from the locked script, ASR read-back | Whether the voice sounds natural; script truthfulness |
| Licence manifest gate | Reading the actual licence terms when adding a new asset |
| QA gates, contact sheet | Final approval to publish |

## Operational notes for agents on the shared box
- Heavy steps take a box-wide lock other heavy jobs on the machine can share (set `PROMO_HEAVY_LOCK` to the same path as e.g. your test gates, or `promo config heavy-lock PATH`; default `/tmp/promo-reel-heavy.lock`) (`promo/lock.py`) and wait while it is held. Never SIGCONT or kill a render that something else paused.
- Use the project venv (`pip install -e .[vo,asr]` installs every dependency).
- Render one shot at a time (ffmpeg `-threads 2`); never run two renders at once. Heavy renders hold
  the box-wide heavy lock (`promo` takes it itself; see above). A full 1080 build takes ~15-25 min on 8 cores.
- Do not commit media, builds or the music file; `.gitignore` covers `media/`, `build/`, `out/`, `*.mov`, `*.mp4`, `*.wav`, `*.mp3`, models.
- Do not git push or publish unless the human asked for that specific action.
