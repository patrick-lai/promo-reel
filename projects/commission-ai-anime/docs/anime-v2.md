# commission-ai anime opening — v2 (Direction 2, style preset `anime-opening`)

Built with `promo new --style anime-opening` + the `anime` shot type; no bespoke renderer.
Output: `out/anime-v2-1080.mp4` (1920x1080 30 fps, 2288 frames, 76.267 s, web master -14 LUFS / -2.2 dBTP).
Music: Pixabay 324102 edit-v1 (`anime/music/edit-v1-master.wav`), grid `edit-v1.json` (177 BPM, 1 bar = 1.356 s);
every cut is on a bar line; intro_hit, lift, peak_start, seam_A_to_B_outro, final_hit all land on cuts.

## Text map (cards all in the fixed lower-third band y 800-1040)
| Shot | Beats | Picture | Card |
|---|---|---|---|
| 01 | 0-4 | dusk Workshop (shot-01-dusk) | — |
| 02 | 4-20 | night Workshop (shot-03-night), flash + speed lines at head | commission-ai / Your AI dev crew |
| 03 | 20-36 | PLACEHOLDER S3 composer | ONE ASK. → TONIGHT. |
| 04 | 36-52 | PLACEHOLDER S4 board / talk-dag | 8 TASKS. (evidence: shot-10-dpr2 "eight checkout tickets", "0 / 8 tasks done") |
| 05-07 | 52-76 | shot-10-dpr2 frozen, push on PAY-103/104/106 cards | CLAUDE CODE / CODEX / CURSOR + "on the job" |
| 08-11 | 76-108 | shot-08 PR card stepping Coding→PR raised | CODING. / CHECKS. / PUSHED. / PR RAISED. |
| 12 | 108-132 | shot-10-dpr2 needs-you card | …ONLY WHEN IT NEEDS YOU. |
| 13 | 132-148 | shot-12 Zen review (contain, 1.2x) | REVIEWED, WITH THE REASON WHY. |
| 14 | 148-160 | PLACEHOLDER shot-16 PR Open→Merged | MERGED. |
| 15 | 160-180 | PLACEHOLDER shot-11 board all landed | `claims.merged_count` → currently ALL MERGED. |
| 16-17 | 180-200 | PLACEHOLDER shot-14b Street glide + freeze | — |
| 18 | 200-212 | morning Workshop (shot-15-morning) | GOOD MORNING. |
| 19 | 212-225 | dusk freeze, blur/dim | commission-ai / Your AI dev crew, on your Mac. / macOS alpha (no URL) |

## Shot-11 claim (config table, `claims.merged_count`)
Selected by `shot11_legible: {cards: N, logos: N}` (fill in from v1-1080 `manifest.md` "### Shot 11" once captured):
8 cards + 3 logos → `8 TASKS · 3 AGENTS · ALL MERGED`; 3 logos only → `3 AGENTS · ALL MERGED`;
8 cards only → `8 TASKS · ALL MERGED`; neither / unknown → `ALL MERGED.` (current). `promo check` WARNs until filled
and FAILs if the selected row claims more than the manifest entry says. Same selector is reusable (`promo/claims.py`) for the hero caption.

## Placeholders waiting on footage
S3 composer (03); S4 board / talk-dag (04); shot-16 PR Open→Merged (14); shot-11 board all landed (15, + fill `shot11_legible`);
shot-14b Street glide (16) and freeze (17). Also pending: shot-12 DPR2 retake (1x in use).

## Script vs footage mismatches
- v1-1080 numbering ≠ script S-numbers: shot-03 is the night Workshop (no composer take; the sent ask is visible in shot-10-dpr2); shot-15 is the morning Workshop, not the merge (that is shot-16, uncaptured).
- "Robot's light flicks on" in the night Workshop is not verified in shot-03 (lamp lights by frame 12; shot starts after it).
- Marketing's final map drops "THE COMMANDER PLANS." — dropped.
- Roll call wants rail rows lighting; footage only has board-card logos. Names come from the capture manifest (shot-08 spells "Codex"); shot-12 1x rail rows too small to enlarge.
- 14b take (08:02) exists but its Street notice sits under an achievements toast — treated as not captured.
- shot-12 shows demo persona "Maya's" in the sidebar; board reflow ghosts at source 3-4 s (avoided).
- Music master 76.19 s vs 225-beat timeline 76.27 s → 0.08 s tail silence.
- Direction 2 "on the job" subtitles kept although the Marketing final map doesn't list them.
- End-card URL off per team decision.
- All footage is demo-mode (`footage-demo` WARN).

## Licence / fonts
- Music: Pixabay 324102 (Pixabay Content License), sha256 60269db3…aebea, source URL in assets.yaml.
- Barlow Condensed (cards) and Inter (sub lines): SIL OFL 1.1, verified from the embedded name tables.
