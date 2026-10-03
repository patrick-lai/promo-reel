# commission-ai anime opening — v2 → v3 (Direction 2, style preset `anime-opening`)

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

## Text map (cards all in the fixed lower-third band y 800-1040)
| Shot | Beats | Picture | Card |
|---|---|---|---|
| 01 | 0-4 | dusk Workshop (shot-01-dusk), held | — |
| 01b | 4-8 | dusk Workshop, steady push-in from the intro hit; flash + speed lines at head | commission-ai / Your AI dev crew (slam) |
| 02 | 8-20 | night Workshop (shot-03-night, frame 12+), push continues | commission-ai / Your AI dev crew (carried over) |
| 03 | 20-36 | PLACEHOLDER S3 composer | ONE ASK. → TONIGHT. |
| 04 | 36-52 | PLACEHOLDER shot-11 full board (DPR 2) | `claims.plan_count` → '8 TASKS.' if 8 cards legible, else 'THE PLAN.' (Marketing to confirm) |
| 05-07 | 52-76 | shot-10-dpr2 frozen, push on PAY-103/104/106 cards | CLAUDE CODE / CODEX / CURSOR + "on the job" |
| 08-11 | 76-108 | shot-08 PR card, push-in on the active chip (Coding→PR raised) | CODING. / CHECKS. / PUSHED. / PR RAISED. |
| 12 | 108-132 | shot-10-dpr2 needs-you card | …ONLY WHEN IT NEEDS YOU. |
| 13 | 132-148 | shot-12 reviewer thread, top-left to the 10:40 PM divider (aspect 1.6, brand pillars) | REVIEWED, WITH THE REASON WHY. |
| 14 | 148-160 | shot-15-prcard (DPR 2): PAY-110 PR card Open→Merged, push ≤ 1.2x | MERGED. |
| 15 | 160-180 | PLACEHOLDER shot-11 board all landed | `claims.merged_count` → currently ALL MERGED. |
| 16-17 | 180-200 | PLACEHOLDER 14b dusk retake: Street glide + stop-time freeze | — |
| 18 | 200-212 | morning Workshop (shot-15-morning) | GOOD MORNING. |
| 19 | 212-224.767 | dusk freeze, blur/dim (ends with the music, 76.192 s) | commission-ai / Your AI dev crew, on your Mac. / macOS alpha (no URL) |

## Shot-11 claim (config table, `claims.merged_count`)
Selected by `shot11_legible: {cards: N, logos: N}` (fill in from v1-1080 `manifest.md` "### Shot 11" once captured):
8 cards + 3 logos → `8 TASKS · 3 AGENTS · ALL MERGED`; 3 logos only → `3 AGENTS · ALL MERGED`;
8 cards only → `8 TASKS · ALL MERGED`; neither / unknown → `ALL MERGED.` (current). `promo check` WARNs until filled
and FAILs if the selected row claims more than the manifest entry says. Same selector is reusable (`promo/claims.py`) for the hero caption.

## Placeholders waiting on footage
S3 composer (03); shot-11 full board DPR 2 (04 and 15, + fill `shot11_legible` from its manifest.md count);
shot-14b dusk retake: Street glide (16) and freeze (17). Also pending: 08-dpr2 take (shot-08 in use) and the shot-12 DPR 2 swap (1x in use).
v4 wired in `shot-15-prcard` (14). `talk-dag-tight` is deliberately not used (3 cards, different demo board).

## Script vs footage mismatches
- v1-1080 numbering ≠ script S-numbers: shot-03 is the night Workshop (no composer take; the sent ask is visible in shot-10-dpr2); shot-15 is the morning Workshop, not the merge (that is shot-16, uncaptured).
- "Robot's light flicks on" in the night Workshop is not verified in shot-03 (lamp lights by frame 12; shot starts after it).
- Marketing's final map drops "THE COMMANDER PLANS." — dropped.
- Roll call wants rail rows lighting; footage only has board-card logos. Agent per card confirmed from demoPromo.ts (see Roll call source); shot-08 spells "Codex".
- 14b take (08:02) exists but its Street notice sits under an achievements toast — not used; waiting for the 14b dusk retake.
- shot-12 shows demo persona "Maya's" in the sidebar; board reflow ghosts at source 3-4 s (avoided).
- v3: timeline trimmed to the music master (76.192 s); the v2 0.08 s tail silence is gone.
- Direction 2 "on the job" subtitles kept although the Marketing final map doesn't list them.
- End-card URL off per team decision.
- All footage is demo-mode (`footage-demo` WARN).

## Licence / fonts
- Music: Pixabay 324102 (Pixabay Content License), sha256 60269db3…aebea, source URL in assets.yaml.
- Barlow Condensed (cards) and Inter (sub lines): SIL OFL 1.1, verified from the embedded name tables.
