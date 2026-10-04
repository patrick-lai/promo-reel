# commission-ai hero v4 (1080p): build notes, 2026-10-04

v4 = v3 plus Zen's notes on v3 (4.00, Truth PASS). Same branch/worktree (`hero-v2`). No promo-reel code changed.
Output: `out/hero-v4-1080.mp4`, copied to `/workspace/videos/commission-ai-promo/cuts/hero-v4-1080.mp4`.
New takes registered with `promo footage add`: `shot-04-dpr2-promo-v1080`, `shot-11-dpr2-v1080`, `shot-16-prcard-tighter-v1080`.

## Changes
1. **S15**: the shot is now the night Workshop (`shot-03-night`) as a plain clip, unblurred, from 2.0 s (the lamp is lit).
   - It's framed tight on the lamp, window and desk (1.43→1.47x, DPR 1, under the 1.5x line, header bar excluded). S03 only shows this take blurred behind the composer, and S01 is the whole room at dusk.
   - VO "Go to bed." with no caption. S16 is now the only PR shot.
2. **S16**: now uses `shot-16-prcard-tighter` (2.55x: the Done stepper and the PR card, with Evidence out of frame), from t_in 7.05 with no push.
   - **Flip:** frame grab puts the badge flip at **src 7.70 s** (7.683 s still reads Open; the 6.50 s change is the Done reflow). In the output, frame 1415 (47.167 s) is the last Open frame and **frame 1416 (47.200 s)** is the first Merged frame. Merged holds through frame 1468 (the end of S16 at 48.98 s), 53 frames or 1.77 s. Checked by frame grab.
   - **VO:** "Wake up to merged PRs." starts at 0.52 s (47.05 s in the cut).
   - **Badge size:** 'Merged' measures 20.0 px (PASS).
   - **No caption:** the fixed zone (y 895–1025, pill about x 650–1270) would sit on the 'Builds pass · 1 approval · 1 comment' chips (y ≈940–995). So it's VO only.
3. **S04**: now two segments.
   - **A:** the old take's plan landing, src 2.65–5.80 (cut before its 5.82 s Wave-1 reorder animation).
   - **B:** `shot-04-dpr2-promo` from 0.42 s (its layout settles at 0.40 s) to 2.77 s.
   - **Caption:** "Split into 8 tasks." runs on B only, for 2.35 s. All 8 cards are in frame at 1.0→1.04x, and the pill sits in the empty canvas below Wave 2, clear of every card.
   - **Deviation:** B runs past the brief's "first 0.8 s", because the caption needs 2.0 s or more. PAY-103 turns Running at about 0.73 s (real). Wave 2/3 show the real Blocked padlock.
4. **S11**: the header segment now uses `shot-11-dpr2`, 1.22→1.25x, top-anchored. The header and the Landed column sit side by side.
   - The crop keeps the column right of the caption pill: the pill ends at x≈1264 and the column starts at x≈1308.
   - The search box is cut at the left edge, and the lower-left is still dotted canvas (layout).
   - `shot-11-dpr2-r2` was not in the manifest at build time.

## Named text (tools/named_v4.py, promo.named.element_px, 1080 frame)
- S04 (B): card IDs 16.0–16.7 px, titles about 18.4–18.75 px, the 'Wave 1' heading 20.0–20.8 px. All INFO, since the caption counts the cards and names none of them.
- S11: the header '8 in this run · 8 landed' measures 22.0–22.5 px and 'Landed' 22.0–22.5 px (PASS). 'Merged and closed' is 17.1–17.5 px (INFO).
- S16: the 'Merged' badge measures 20.0 px (PASS).
- 08/10/12 are unchanged and PASS. Result: 0 FAILs.
