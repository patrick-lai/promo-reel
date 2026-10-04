# commission-ai anime opening — v2 → v3 (Direction 2, style preset `anime-opening`)

## v6 (2026-10-04): Zen v5 review (3.00; Polish 2) — fixes that need no new footage
- **A4 band (Calm):** the caption band is a style-preset parameter now (`style.band.frac`, rows placed relative to it;
  `promo/styles.py layout_band`). anime-opening default **15% = 162 px (y 918-1080)**, was 280 px (26%). Rows: title 71 px
  (cap 50), sub 34 px, tag 28 px (right of the sub; cap >= 18 enforced by gate `card-band`). UI shots are framed in the
  1920x918 area above it. `named` now FAILs an element "hidden by the caption band" (box below band y0, any layout).
  Re-framed every UI shot whose crop edge cut a line or card: 04 (bottom edge between PAY-104 and PAY-105), 05-07 roll call
  (edges in the gaps between board cards; 06/07 now show two whole cards), 08-11 chips (centre y 470: edges stay in text
  gaps for the whole push; 08 moved right so the board sliver is out), 14 (crop ends above the Evidence 'QA decision' box).
- **A3 (shot 15):** 5 bars -> **2 bars (2.71 s)**, on the bar. Picture is a header-only crop of the `shot-11` header take
  (src x 540-1490, 2.02x): the only text in frame is 'All done · Plan next · 8 in this run · 8 landed' at **34.4 px** —
  the frame now shows the claim the card makes. shot-11-all8 is no longer used. Freed 3 bars: 13 +1 (reason reads longer),
  14 +1 (Merged lingers), 16 +1 (0.10-0.95 s clean dusk Outside, then 3.60-7.45 s at 0.65x). Runtime unchanged (76.192 s):
  the music master is one mastered edit; the stop-time seam (beat 196) and final hit stay on their markers.
- **03 slot (A1, still a placeholder):** swap recipe in promo.yaml + `promo move-cut <beat> <new_beat>` (moves one cut,
  keeps comments; refuses unsafe moves). `promo move-cut 20 12` lands 03 (first real UI) at 4.07 s; 02's cards run to `end`.
- **A2** (04 '8 TASKS.' card) left as is; waiting on shot-03-composer-dpr2 and shot-04b-ready8-dpr2.

## v5 (2026-10-04)
New v1-1080 takes registered with `promo footage add` (sha256 match manifest.md): shot-16-prcard-tight, shot-08-dpr2,
shot-12-dpr2-z179, shot-14b-dusk-r2, shot-11, shot-11-all8. Output `anime-v5`.
1. **PR payoff (14):** `shot-16-prcard-tight` (776x436.5 CSS clip, DPR 2, 2.474x). Flip verified on the frames: 'Open' at
   src frame 461, 'Merged' at frame 462 = **7.700 s** (same as the older take); the PR card first lays out at frame 390
   (6.50 s), so the shot starts at 6.52. Flip lands at shot 1.17 s (output frame 1540), 6 frames (0.2 s) before 'MERGED.' (bar 1, frame 1546). Push 1.0x -> **1.05x**
   landing on the flip: 1.05x is the most that keeps the whole card in frame (outline src x 56-1866 = 1811 of 1920 px;
   1.1x would cut ~47 src px per side). Badge 18 src px -> **18.9 px** (clears the named FAIL; the 20 px target would
   need ~1.11x and cut the card). Title 27.3 px, 'Builds pass · 1 approval' 24.1 px.
2. **Chips (08-11):** `shot-08-dpr2` (2.13x clip, whole stepper). Boxes re-found per state (the stepper sits lower while
   Running): Coding 32.3, Checks 30.6, Pushed 29.0, PR raised 29.0 px at the 1.61x start of the push.
3. **Peak (13):** `shot-12-dpr2-z179` full width (no pillars/brand fill); crop x 0-1856 drops the next pane's sliver
   (1.034x). 'Approved. ...' line 22 src px -> 22.8 px.
4. **Street (16) + stop-time (17):** `shot-14b-dusk-r2`, only 3.60-7.45 s (0.71x) for 16 (notice alone on dusk Outside, then
   Street glide); 17 freezes on 7.45 s (16's last frame). Full frame (no cards), tab bar cropped, notice in frame.
   0-2.5 s is allowed but unused (settings popover 1.0-1.8 s, toast stack 2.0-2.5 s).
5. **Plan (04):** `shot-11` header take, slow push 1.19x -> 1.28x. Header digits ('8 in this run · 8 landed') 17 src px ->
   **20.2-21.8 px**, so `shot11_legible: {cards: 8, logos: null}` and the card reads **'8 TASKS.'**; the shot 04 `named`
   entries keep that >= 18 px. Evidence section is now `Shot 11 (header counts)` (claims.py: a full heading selects one
   take's section; '8 in this run' counts as the card count). shot-11-all8 is never the claim source.
   **15 (peak claim):** `shot-11-all8` (visual only), 1.2x tilt down the Landed column; card = `8 TASKS · ALL MERGED`.
6. **Placeholders left:** 03 only (S3 composer: no composer take in v1-1080).

## v4 (2026-10-04)
Output `out/anime-v4-1080.mp4`.
1. **Peak crop (13):** same narrow shot-12 crop; the pillars now use `pillar_fill: brand` (the opening's night-sky brand
   background, sampled from the shot-03 night plate) instead of the flat band colour. A commented one-line swap in
   promo.yaml switches to a full-width crop when shot-12-dpr2 is approved.
2. **PR payoff (14, 'MERGED.'):** real take `shot-15-prcard` (v1-1080 "Shot 16 (PR-card payoff)", DPR 2, registered with
   `promo footage add`, sha256 matches manifest.md). The PR badge flips Open -> Merged at src 7.70 s (frame 462); it lands
   at shot 1.20 s, 5 frames before the card (bar 1). Real time to just after the flip, then the static Merged hold at 0.6x.
   Push-in 1.0x -> 1.3x (the cap) lands with the flip and holds; crop src x 443-1920, so the whole PR card (src x 694-1862,
   y 447-647, incl. the 'Builds pass · 1 approval' row) stays in frame. No PR number in any card (#438 is only in the app frame).
   **Re-measured** on full-res 1920x1080 source frames at 8.0 / 8.75 / 9.4 s: 'Merged' cap height = 12 px (rows 478-489,
   stable over thr 80-130), PR title = 17 px (rows 513-529). The take is 1.6x CSS (DPR 2 of a 1200x675 clip), so the 12 CSS
   px badge font is ~19 px — but that is the font size; cap height is ~0.63 em. The `named` code reads the clip's native
   frame and has no CSS/DPR assumption (regression test `test_named_measures_native_frame_pixels_not_css_or_preview`).
   **Open issue:** at 1.3x the badge renders 15.6 px (title 22.1 px), so `named` FAILs (min 18, not overridden). Clearing
   18 px needs >= 1.5x (cuts the card's right edge ~9 px at 1.5625x) or a closer / higher-DPR retake of the PR card.
3. **'8 TASKS.' (04):** stays a placeholder for the shot-11 full board (DPR 2). `talk-dag-tight` is not used (3 cards from
   another demo board). The card text now comes from `claims.plan_count`: '8 TASKS.' only if `shot11_legible.cards == 8`,
   else 'THE PLAN.', a softened fallback flagged `confirm: Marketing` (check WARNs, critique pack marks it provisional).
   **Marketing to confirm 'THE PLAN.'** (not final copy).

## v3: director's notes on v2 (applied 2026-10-04)
Output now `out/anime-v3-1080.mp4` (2286 frames). What changed:
1. **Tail:** the timeline ends where the music master ends: 76.192188 s = 224.76695 beats; the end card (19) is trimmed,
   not padded. At 30 fps the last video frame ends at 76.200 s (frame grid); audio stops at 76.192 s, no silence added.
2. **Opening 0–6 s:** 01 = dusk plate held (0–1.36 s); 01b = the same dusk plate, frame-continuous, steady linear
   push-in starting on the 1.36 s intro hit (logo slam + flash there); 02 = cut on the next bar (2.71 s) to the shot-03 night
   plate from frame 12 (lamp lit; Zen: frame 8 or later), push continues; the logo card carries over without a re-slam.
3. **Chip montage 25.8–36.6 s (08–11):** steady push-in centred on the active stepper chip (w 0.62 → 0.54 of source width,
   band layout). Each chip label is a `named:` element: `promo check` gate `named` requires >= 18 px cap height (same
   minimum as the talk show) and `named-upscale` WARNs: the labels measure 27–29 px at x1.61 (upscaled from the
   shot-08 take). When the 08-dpr2 take lands: `source: shot-08` → `source: shot-08-dpr2` on 08–11 (one line each), re-run check.
4. **Peak 44.7–50.2 s (13):** shot-12 1x, top-left crop down to the 10:40 PM divider (src x 0–745, y 0–466:
   sidebar + conversation pane), pillarboxed at aspect 1.6 so there is no board sliver. The reviewer's 'Approved. …' line
   is a `named:` element: 18.9 px at x1.72 (passes, upscale WARN). Card stays in the band and `ui_text` keeps it off the
   line. When the DPR 2 retake is approved, swap to `shot-12-dpr2` (+ its own cam / named box). Note: a `shot-12-dpr2`
   take is already registered in v1-1080 `manifest.md` ("Shot 12 (DPR2, preferred)"); per the director it is not used yet.
5. **Stop-time:** 16/17 stay placeholders until the 14b **dusk retake** lands; the old 14b (08:02) is not used. Then
   18 = morning Workshop under 'GOOD MORNING.', 19 = dusk end card (bookend).
6. **Roll call (confirmed by Commission-ai):** see "Roll call source" below.

## Roll call source
CLAUDE CODE is over PAY-103, CODEX over PAY-104, CURSOR over PAY-106. Source: Commission-ai's demo scenario
`clients/web/src/dev/demoPromo.ts` (Commission-ai repo), checked at the capture commit `4a427fc0` and at main `00429ca5`:
line 61 `key: "PAY-103" … agent: "claude"`, line 62 `key: "PAY-104" … agent: "codex"`, line 64 `key: "PAY-106" … agent: "cursor"`.
Confirmed by Commission-ai on 2026-10-04. The frames show the agents' logos on those board cards (shot-10-dpr2 frozen at 0.20 s), not the words.

Built with `promo new --style anime-opening` + the `anime` shot type; no bespoke renderer.
v2 output was `out/anime-v2-1080.mp4` (1920x1080 30 fps, 2288 frames, 76.267 s, web master -14 LUFS / -2.2 dBTP); v3 see above.
Music: Pixabay 324102 edit-v1 (`anime/music/edit-v1-master.wav`), grid `edit-v1.json` (177 BPM, 1 bar = 1.356 s);
every cut is on a bar line; intro_hit, lift, peak_start, seam_A_to_B_outro, final_hit all land on cuts.

## Text map (cards all in the fixed band y 918-1076 since v6; v1-v5: y 800-1040 + 280 px solid band)
| Shot | Beats | Picture | Card |
|---|---|---|---|
| 01 | 0-4 | dusk Workshop (shot-01-dusk), held | — |
| 01b | 4-8 | dusk Workshop, steady push-in from the intro hit; flash + speed lines at head | commission-ai / Your AI dev crew (slam) |
| 02 | 8-20 | night Workshop (shot-03-night, frame 12+), push continues | commission-ai / Your AI dev crew (carried over) |
| 03 | 20-36 | PLACEHOLDER S3 composer | ONE ASK. → TONIGHT. |
| 04 | 36-52 | shot-11 header take (DPR 2): 'All done · Plan next · 8 in this run · 8 landed', push 1.19→1.28x | `claims.plan_count` → 8 TASKS. |
| 05-07 | 52-76 | shot-10-dpr2 frozen, push on PAY-103/104/106 cards | CLAUDE CODE / CODEX / CURSOR + "on the job" |
| 08-11 | 76-108 | shot-08-dpr2 PAY-104 drawer stepper, push-in on the active chip (Coding→PR raised) | CODING. / CHECKS. / PUSHED. / PR RAISED. |
| 12 | 108-132 | shot-10-dpr2 needs-you card | …ONLY WHEN IT NEEDS YOU. |
| 13 | 132-152 | shot-12-dpr2-z179 reviewer thread, full width (x 0-1856, 1.03x) | REVIEWED, WITH THE REASON WHY. |
| 14 | 152-168 | shot-16-prcard-tight (DPR 2): PAY-110 PR card Open→Merged (7.70 s), push 1.0→1.05x, whole card in | MERGED. |
| 15 | 168-176 | shot-11 header-only crop (2.02x): '8 in this run · 8 landed' | `claims.merged_count` → 8 TASKS · ALL MERGED |
| 16-17 | 176-200 | shot-14b-dusk-r2 0.10-0.95 + 3.60-7.45 s: Street notice → Street glide; 17 freezes on 7.45 s | — |
| 18 | 200-212 | morning Workshop (shot-15-morning) | GOOD MORNING. |
| 19 | 212-224.767 | dusk freeze, blur/dim (ends with the music, 76.192 s) | commission-ai / Your AI dev crew, on your Mac. / macOS alpha (no URL) |

## Shot-11 claim (config table, `claims.merged_count`)
Selected by `shot11_legible: {cards: N, logos: N}` (v5: `{cards: 8, logos: null}` from "### Shot 11 (header counts)"):
8 cards + 3 logos → `8 TASKS · 3 AGENTS · ALL MERGED`; 3 logos only → `3 AGENTS · ALL MERGED`;
8 cards only → `8 TASKS · ALL MERGED`; neither / unknown → `ALL MERGED.`; v5 selects `8 TASKS · ALL MERGED`. `promo check` WARNs until filled
and FAILs if the selected row claims more than the manifest entry says. Same selector is reusable (`promo/claims.py`) for the hero caption.

## Placeholders waiting on footage
S3 composer (03) only. v5 wired in shot-11 (04), shot-08-dpr2 (08-11), shot-12-dpr2-z179 (13), shot-16-prcard-tight (14),
shot-11-all8 (15), shot-14b-dusk-r2 (16, 17). `talk-dag-tight` is deliberately not used (3 cards, different demo board).

## Script vs footage mismatches
- v1-1080 numbering ≠ script S-numbers: shot-03 is the night Workshop (no composer take; the sent ask is visible in shot-10-dpr2); shot-15 is the morning Workshop, not the merge (that is shot-16, uncaptured).
- "Robot's light flicks on" in the night Workshop is not verified in shot-03 (lamp lights by frame 12; shot starts after it).
- Marketing's final map drops "THE COMMANDER PLANS." — dropped.
- Roll call wants rail rows lighting; footage only has board-card logos. Agent per card confirmed from demoPromo.ts (see Roll call source); shot-08 spells "Codex".
- 14b take (08:02) exists but its Street notice sits under an achievements toast — not used; v5 uses shot-14b-dusk-r2. The Street view still renders bright at 19:30 (real app).
- shot-12 shows demo persona "Maya's" in the sidebar; board reflow ghosts at source 3-4 s (avoided).
- v3: timeline trimmed to the music master (76.192 s); the v2 0.08 s tail silence is gone.
- Direction 2 "on the job" subtitles kept although the Marketing final map doesn't list them.
- End-card URL off per team decision.
- All footage is demo-mode (`footage-demo` WARN).

## Licence / fonts
- Music: Pixabay 324102 (Pixabay Content License), sha256 60269db3…aebea, source URL in assets.yaml.
- Barlow Condensed (cards) and Inter (sub lines): SIL OFL 1.1, verified from the embedded name tables.
