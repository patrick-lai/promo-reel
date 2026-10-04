# commission-ai hero v5 (1080p): build notes, 2026-10-04

v5 = v4 with only S11 changed (Zen v4: 4.14, Truth PASS; S11 had about 65% empty canvas and a clipped 'L' at the right edge).
Output: `out/hero-v5-1080.mp4` (60.000 s), copied to `/workspace/videos/commission-ai-promo/cuts/hero-v5-1080.mp4`.
Every frame outside S11 is identical to v4 (a sampled frame from each shot has mean abs diff 0.0); all other steps were up to date.

## Code base
`style-presets` (645b598, Reel Engineer: claims.landed_count, the ALL LANDED audit rule) was merged INTO `hero-v2` (e586b04). No promo-reel code was edited.
NOTE: the claims gate only runs inside `style_check.anime_gates` (preset `anime-opening`). The hero has no preset, so `promo check` does not run it here.
`tools/claims_v5.py` runs the same `promo.claims.audit` on the hero spec and asserts that the S11 caption equals the selected row:
0 FAILs. A negative test confirms it catches mismatches: with landed=7 the row FAILs, and with legible landed=7 it FAILs against the manifest.

## S11
- **Take:** `shot-11-dpr2-r2` (registered with `promo footage add`; sha 90ff6b72…1689 matches manifest.md).
- **Frame:** a static crop at **1.557x**: src x 646–1879, y 27–721.
  - **Left:** 6 src px (9 output px) after the search box, before the 'All done · Plan next' pill.
  - **Right:** 9 src px (14 output px) after the cards; the card's right border is at output x≈1906.
  - **Top:** above the header row.
  - **Bottom:** in the PAY-104 / PAY-105 gap.
  - No clipped text on any edge, and the stray 'L' (the Later column) is gone.
- **Why not ≤1.25x:** at 1.25x the left edge would cut the search box and the bottom edge a card.
- **Softness:** 1.557x on a DPR 2 take is crisp enough. Text renders at 25–33 px, and the `footage-dpr` gate passes.
- **Caption:** "8 TASKS · ALL LANDED" (pill x 657–1263). The column's card border starts at x≈1270, a 7 px gap; card text is 37 px or more away.
- **Empty canvas:** the lower-left block (left of the column, below the header) is **58%** of the frame. v4 was 59.5% by the same measure.
  - The r2 layout (header across the top, column at the right) sets this. With clean edges and the fixed caption zone, no crop gets it lower:
  - The tighter 2.2x crop (left edge in the pill / header-text gap) would be about 40% empty, but the fixed caption would sit on PAY-103's card.
  - `shot-11-dpr2-r3` (column under the header, queued per manifest.md) is the real fix.
- **Named text (tools/named_v5.py):**
  - Header '8 in this run · 8 landed': 32.7 px.
  - 'Landed': 31.1 px.
  - 'Merged and closed': 26.5 px.
  - Smallest UI text in the crop (card ID 'PAY-103'): 24.9 px.
  - Result: 0 FAILs.
