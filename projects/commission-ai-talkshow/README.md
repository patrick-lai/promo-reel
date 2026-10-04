# commission-ai-talkshow: Direction 3 "Building in Public, episode one"

Two Live2D Original Character hosts (Hiyori on top, Mao below, left column for the whole show, no move) sit beside the
full-height stream screen (1440x1032), which plays real app takes. There is no chat strip: HIYORI's two scripted
asides were cut on the UX review (T2/T3). Every on-screen element a line names gets a push-in that `promo check`
measures. There's an EP 1 tag (no LIVE badge, no viewer counts), and the show ends on two Live2D credits cards.

| File | What it is |
|---|---|
| `plan.yaml` | Hand-edited beat-to-shot plan (clip ids, cams, sync points, named elements, time-of-day fallback). **Edit this file.** |
| `make_spec.py` | Reads `plan.yaml` plus the VO's `lines.json` (exact durations) and writes `promo.yaml` (`--check` = staleness test). |
| `promo.yaml` | GENERATED. Frame-exact timeline (`bpm: 1800` at 30 fps, so 1 timeline beat = 1 frame) and sha256-pinned VO lines. |
| `assets.yaml` | Every asset with its licence: the Kokoro VO files (Apache-2.0), the Kokoro model and voices (from talkshow/LICENSE.md), the CC0 self-synthesised swell, the Hiyori and Mao Live2D models (Free Material License, Original Characters; `status: draft` until the JPY 10M revenue condition is confirmed) and Cubism Core. No music bed. |
| `make_preview.py` | DRAFT timing preview only. It swaps each missing take for a labelled PLACEHOLDER card in a gitignored `preview/` spec and copies the mp4 and contact sheet to `/workspace/promo-reel-evals/`. Never a deliverable. |

```
python projects/commission-ai-talkshow/make_spec.py           # after the VO is re-rendered or plan.yaml is edited
nice -n 10 python -m promo -p projects/commission-ai-talkshow/promo.yaml build   # reports missing takes; no placeholders
nice -n 10 python projects/commission-ai-talkshow/make_preview.py                # draft preview with placeholder cards
python -m promo -p projects/commission-ai-talkshow/promo.yaml check
```

## Timing rules

The room has dropped the script's fixed ~2:00 slots. Each beat runs for its real VO plus a screen hold, and no voice is time-stretched.

- Lines inside a beat are 0.20 s apart.
- Each beat's screen cuts 0.15 s before its first line and holds 1.5 s after its last (beat 1: 2.0 s; beat 9: 0.6 s,
  room-directed, so the street tail is trimmed and beat 10 plays over the end card).
- There's a 1.5 s intro sting (card plus swell) and two 3.0 s credits cards (notice + licence line, then the model credits).
- Total: 107.30 s (1:47). The title card cuts to the dusk Workshop at 4.0 s.
- Sync points use `hold_in`, which holds the clip's first frame and then plays at 1x. A clip that runs out holds its last frame. There's no slow-mo and no mid-clip edit.

### Beat 7 automatic take

`make_spec.py` measures shot 12's "Approved..." line through the segment's cam on the 1440x1032 screen (`livestream.text_height`, the same measurement as the `promo check` gate `livestream-text-size`).

- **At least 24 px:** MAO's full `beat07_line02` is used. This is the current result: 24.8 px.
- **Under 24 px:** the line is cut at the silence after "...tells you why it passes." (3.11 s, 40 ms fade). "See? Approved, with the reason right there." is dropped, and `text` becomes that prefix while the full line stays in `script_text`.

The take that was used is written in the `promo.yaml` header.

## Named-element push-ins (UX review T1/T4)

Each take's `profiles` entry lists the elements its lines name (`named`: box in source px, clip time). `promo check`:

- `livestream-named` FAILs when an element renders under 18 px (ascender-top to baseline; glyph height for a badge) or
  isn't fully inside the screen crop (`min_px: 0` = a container that only has to be in frame, e.g. the whole card).
- `named-upscale` WARNs when its effective scale (output px / source px) is above 1.0: upscaled, soft text.
- `livestream-cam` FAILs on a cam whose crop at the 1440x1032 aspect would be taller than the clip (16:9 takes: w <= 0.785).

| Shot | Take (source) | Cam w (push) | Element: measured px (effective scale) |
|---|---|---|---|
| 03 | talk-dag-tight-v1080 (1920x1080, DPR 2, still) | 0.785 (1.27x, widest) | PAY-101 / PAY-104 ids 27.7 px (0.96); the whole fan in frame |
| 02 | shot-03 (3840x2160, DPR 2) | 0.375 (2.67x) | composer text 20 px (1.00); whole composer in frame |
| 04 | shot-05-v1 (3840x2160, DPR 2) | 0.375 (2.67x) | card titles 19 px; Claude Code / Codex badge tiles 28 px; **Cursor badge 13 px** (dark tile, only the cube glyph reads) (1.00); whole PAY-106 card in frame |
| 05 | shot-08-v1080 (1920x1080) | 0.667 (1.50x) | Coding / Checks / Pushed / PR raised 19.1 px (**1.12**, upscaled) |
| 06a/b | shot-10-dpr2-v1080 (1920x1080, DPR 2, 1.5x pre-framed) | 0.60 (1.67x) | Needs you 20 px, Allow once 20 px (**1.25**); whole PAY-106 card in frame |
| 07 | shot-12-v1080 (1920x1080, DPR 1) | 0.333 (3.00x) | Approved line 24.8 px (**2.25**) |
| 08a | shot-16-prcard-v1080 (1920x1080, DPR 2, 1.6x pre-framed) | 0.654 (1.2x on the full-height fit, the room's cap) | Done 24.1 px; **Merged step label 16.1 px, Merged PR pill 13.8 px** (**1.15**); PR card in frame |

S05's DPR 2 take (Commission-ai) is the one-line `takes: chips:` swap: the profile is keyed by role, and its boxes are in
a `src_px`-tall frame, so the same framing at 2x pixels needs no other change (a differently pre-framed take needs new
boxes; the gate fails loudly if they miss).

## Dusk-to-day dissolve (T5)

`shot-14b-v1080` cuts from the dusk Outside view to the daylit Street at 5.50 s (luma 61.6 -> 108.2). Segment 09b gets
a 0.4 s `dissolve` over it. It's driven by the take's `time_of_day` field in the footage manifest (`dusk` = constant,
no dissolve; `dusk -> day @ 5.50` or `{from, to, at}` = a change); with no field, the plan profile's `time_of_day`
(the current take's fallback) applies. Commission-ai's dusk retake records `dusk` there and the dissolve goes away.

## v3 (UX review 2026-10-04 talkshow-v2, Zen 3.43 FAIL)

- **Hook**: S01b trimmed to 3.5 s (4.0-7.5); beat 1's VO carries over S02, which starts at an absolute 7.5 s
  (`from: {t: 7.5}`). First app UI at 7.5 s. S02 holds its first frame ~10.7 s until the typing sync.
- **Beat 8**: +1.0 s screen hold after the PR pill flips to Merged (7.70 s in the clip); beat 8 VO timing unchanged.
- **Badges**: the three agent badges are logos, not text, so they are no longer named elements in beat 4. Gate:
  a named element must be `kind: text|container`; `logo|icon` FAILs (`livestream-named`).
- **Edge slivers**: new WARN gate `livestream-edges` (short bright runs on the crop's left/right edge column, matte
  aware, `edge_check: false` opts a shot out). S02 left edge moved into the gap left of the Commander panel; 06
  re-cropped to clean columns (source x 690-1910). 05 (stepper) has no crop that keeps both edges clean with every
  named label >= 18 px, so it takes a promo matte (right 14 px, bottom 21 px) filled with the panel's own background
  colour; app pixels inside are untouched. 03 (dependency fan) still WARNs on the right edge: the source is 1080 tall,
  so the crop is at most 1507 src px wide and cannot hold PAY-101 and the whole PAY-104 card; a matte would hide the
  PAY-104 id. Needs a tighter capture.
- **06b cursor**: source frames end at 3.35 s, before the cursor covers "Allow once"; the hold is kept.
- **Beat 8a take swap**: `shot-16-prcard-tight-v1080` (landed 10:55) replaces shot-15-prcard. It holds only the PR
  card (1810 px wide), so the crop keeps its left part (x 30-1180, y 135-959, scale 1.25): 'Merged' pill 22.5 px, PR
  title 32.6 px. Pill flips Open -> Merged at 7.70 s, synced to MAO's "merged"; 2.1 s of Merged on screen before 08b.
  The stepper / 'Done' heading are not in this take and are no longer named.
- **Beat 3 tightened**: the new MAO line is 2.46 s shorter, so the beat is 8.6 s; the 6.0 s take plays at 0.692x
  (`fit_clip: true`) instead of freezing for 2.6 s.
- **Beat 3**: no overlay names ticket ids. PAY-105 is cut in the source itself, so the full top card cannot be framed.
- **VO**: Mao's re-voiced beat 3 / beat 4 lines (10:28, Whisper-checked) replace the v1 takes (in `vo/superseded/`);
  beat 3 is 2.46 s shorter and is tightened to match, beat 4 0.17 s longer. Runtime 106.00 s.
- **Style preset** (`plan.yaml` -> `style:`; `make_preview.py --style=framed-glow`): `plain` (default) or
  `framed-glow`: 2 px accent border (end-card violet 139,124,255), 12 px glow at 25 %, 12 px radius around the app
  panel; HIYORI / MAO lower-third nameplates (22 px cap height, translucent dark pill, accent bar) replace the 20 px
  tags; thin border on the host tiles; static diagonal navy-to-violet gradient with faint grain and a faint 48 px grid.
  Everything is drawn around the footage (`ring_layer` never covers the box).

## Beat to shot map (v2)

| Shot | Beat | Role in `takes:` | Screen | Status |
|---|---|---|---|---|
| 01 | 1 | n/a | Title card "Building in Public / episode one" + swell, 0-4.0 s | ok |
| 01b | 1 | workshop | `shot-01-dusk-v1080`, wide (header bar cropped), from 0.3 s (after the brightness dip) | ok |
| 02 | 2 | composer | `shot-03` (legacy 4K), 2.67x push-in on the composer | legacy take |
| 03 | 3 | dag | `talk-dag-tight-v1080`: PAY-101 fanning into PAY-104 / PAY-105 | ok (MAO's "eight tasks ... waves" not shown: flag) |
| 04 | 4 | rail | `shot-05-v1` (legacy 4K), 2.67x on the Wave 1 cards | legacy take; Cursor badge < 18 px |
| 05 | 5 | chips | `shot-08-v1080`, 1.5x on the stepper | ok (upscaled 1.12x; DPR 2 take queued) |
| 06a/06b | 6 | needs_you | `shot-10-dpr2-v1080`, 1.67x on the PAY-106 card | ok |
| 07 | 7 | review | `shot-12-v1080`, 2.25x push-in, auto take | ok (1x; DPR2 retake queued) |
| 08a | 8 | merged | `shot-16-prcard-v1080`, 1.2x; Merged flip (6.50 s) on MAO's "merged" | ok (the app's PR card shows #438) |
| 08b | 8 | landed | `shot-11-v1080`, last 0.6 s of the beat (08a holds until the PR pill reads Merged at 7.70 s) | **missing** |
| 09a | 9 | workshop | `shot-01-dusk-v1080`, tighter 1.27x push-in on the room vs 01b, later section (from 5.0 s) | ok |
| 09b | 9 | street | `shot-14b-v1080`, 0.4 s dissolve over the dusk-to-day cut, tail trimmed | ok (achievements pop-up covers the notice) |
| 10 | 10 | n/a | End card (no URL / price / dates / PR numbers) | ok |
| 11a/11b | n/a | n/a | Live2D credits: notice + licence line, then model credits (3 s each, 30 px) | ok |

**Beat 8 line:** `shot11_legible` in `plan.yaml` stands in for the `shot11_legible` selector on branch `style-presets` until that branch merges. It picks MAO's line and WAV:

| Legible in shot 11 | Line | WAV |
|---|---|---|
| 8 cards and 3 logos | "All eight tasks, three agents, all merged." | `full` |
| 3 logos only | "Three agents, and every task merged." | `agents` |
| 8 cards only | "All eight tasks, merged." | `tasks` |
| Neither, or not recorded (`null`, the default) | "Every one of them, merged." | `all` |

If the selected WAV is missing, the existing take is used as a labelled placeholder and the VO-vs-script check fails until the real one lands.

**VO files:** new takes in `vo/` win. Old takes may sit in `vo/superseded/` (`<name>.wav` or `<stem>.vN.wav`). A line whose re-voiced take hasn't landed uses the old take as a labelled placeholder, with the script text kept as the reference. Every line is sha256-pinned and the build finds the pinned bytes in either place, so a move mid-build doesn't break it.

## Capture checklist (one line each in `plan.yaml` -> `takes:`; then `make_spec.py`, build)

Each item: register the take with `promo footage add`, then set the role to its clip id.

- [x] **`talk-dag-tight-v1080`** -> `takes.dag` (beat 3).
- [x] **`shot-16-prcard-v1080`** (file `shot-15-prcard.mov`) -> `takes.merged` (beat 8a). No PR number in dialogue or card text.
- [ ] **shot 4** (board planning, S4): not used by Direction 3, which uses `talk-dag` for beat 3. It's the fallback for `takes.dag`.
- [ ] **shot 11** (board all Landed) -> `takes.landed` (expects `shot-11-v1080`). Then fill in `shot11_legible` from its `manifest.md` entry; the beat 8 line follows.
- [ ] **14b retake with the achievements pop-up closed** -> `takes.street`. Copy the `shot-14b-v1080` profile line under the new id if the Street switch is still at 5.5 s.
- [ ] **12 retake at DPR 2** (Z179, PR #95) -> `takes.review`. Add a profile with its cam, the `text_check` box of the "Approved." line and its `named` entry. Without a box, the auto take trims the line (safe default).
- [ ] **S05 chips take at DPR 2** (Commission-ai) -> `takes.chips` (one line; see push-ins above).
- [ ] **14b dusk retake** -> record `time_of_day: dusk` in its manifest entry (no dissolve then).
- [ ] Composer / rail: keep the legacy 4K takes (native 2x for the push-ins). A fresh take must be DPR 2 (or 4K), with a profile carrying the sync and `named` boxes.

## Script vs footage flags (script wording unchanged)

- The script's shot numbers (S3, S4 ...) are the hero shot list. Only S8, S10, S12 and the Workshop exist as v1-1080 takes. S3 composer and S5 rail use legacy 4K demo takes (older app commits). There's no S6 TaskNode-worktree take (only a legacy still), so it isn't used.
- Beat 4: the rail shows each agent's logo on its card, not the words "Claude Code / Codex / Cursor". At the widest
  push-in that keeps the Wave 1 column and the whole PAY-106 card in frame without upscaling (2.67x on the 4K take),
  the Claude Code and Codex badge tiles are 28 px, but Cursor's dark tile doesn't read and its glyph is 13 px
  (`livestream-named` FAIL). Marketing to change the line.
- Beat 3: MAO's line ("splits the ask into eight tasks ... runs the independent ones in waves") claims a task count
  and waves; the talk-dag-tight frame shows 3 cards and no wave headings. Marketing to change the line (or use the
  wider talk-dag take).
- Beat 8a: the app's own PR card shows "#438" (real UI, not our text). At the room's <= 1.2x cap the "Merged" step
  label (16.1 px) and the PR card's "Merged" pill (13.8 px) are under 18 px (`livestream-named` FAIL); "Done" reads at
  24 px. They'd need ~1.35x / ~1.57x.
- HIYORI's chat asides ("which AIs is it using?", "do I have to read every diff?") are cut (UX review T2/T3); the spoken lines are unchanged.
- Beat 7: the take shows only the reviewer's "Approved..." line plus its reason. The new MAO line (Marketing) fits. HIYORI's line and chat aside make no panel claims. The old line's "About this change" / findings / "ask the reviewer" claims are gone.
- The ~2:00 / timecodes in the script table no longer apply (the room's call: real VO plus holds, 1:46).
- Beat 9 / shot 14b: the script's note says the Street line needs the notice popping up top right. In the v1-1080 take the "Your workshop is now a Street" toast (1.85 s) is stacked under a "2 achievements earned" toast, so the notice itself isn't legible. The cut instead lands MAO's line on the visible Outside to Street switch, with the Street tab and HUD showing "Street".
- Shot 12 (1x) is pushed in 2.25x: `footage-dpr` and `named-upscale` WARN (soft upscale). It's readable at 24.8 px; the DPR2 retake fixes this.
