# commission-ai hero v2 (1080p): build notes, 2026-10-04

Output: `out/hero-v2-1080.mp4` (60.000 s, 1920x1080, 30 fps, 1800 frames), copied to
`/workspace/videos/commission-ai-promo/cuts/hero-v2-1080.mp4`. Social master: `out/hero-v2-1080-social.mp4`.
Branch `hero-v2` was cut from `style-presets` (18e36ac), because that branch carries the current AGENTS.md/SKILL.md, the hero preset,
`promo/named.py` and `promo/lock.py`. It is not merged. No promo-reel code was changed. Project files only.

## Shot order (locked)
01 · 02 · 03 · 04 · 05 · 06 · 08(+09) · 10 · 12 · 15 · 11 · 16 · 14b · 17 (98 beats).

## Dropped / not used
- **13**: out, per the brief.
- **07**: dropped. The only shot-7 material is the old demo=1 card stills (`footage/shot-07-card-*.png`). They are readable, but they show the wrong run:
  PAY-104 as Claude, PAY-101/112/114, PRs #412–418, and Blocked/quota cards. That contradicts the PAY-103–110 / #431–438 run (Zen V7/V8).
- **talk-dag**: not used. It is a demo=1 board (PAY-101 Done #412, PAY-104 Running), so the same data contradicts the promo run wherever it is placed.
- **12 lead-in** (`shot-12-dpr2-pre`): not used. It is a full-frame drawer, so cutting into `shot-12-dpr2` would cause a framing jump.

## Deviations from the brief
- **12 push**: 1.2x top-left would cut the reviewer's reason line (it ends at src x 1695) and the "PR raised"/timestamp labels, so the push stops at 1.05x.
  The 10:40 PM divider lands at output y≈848. The caption "Reviewed, with the reason why." sits below it in the fixed zone.
- **Captions dropped** because the single fixed zone (x 400–1520, y 895–1025) would cover UI text:
  08 "Running checks" (over the drawer's Pull request text) and 10 "Only pings you…" (over the PAY-106 Needs-you card).
  05's rail lower-thirds were also removed, because they sat on the rows' text.
- **11 caption = "8 TASKS · ALL MERGED"**, shown over the header segment only.
  The header '8 in this run · 8 landed' measures 19.8–20.4 px and 'Landed' 19.8–20.4 px (≥18 px).
  Only the Claude and Codex logos are visible in that frame (Cursor's PAY-106 is below it), so "3 AGENTS" is not shown and is not claimed.
  The all-8 column fills the bottom-centre, so it carries no caption.
  The literal "Merged and closed" sub-title measures 16.3–16.8 px. MERGED rests on the 18+ px "8 landed" header and the Landed column.
- **16**: the badge flips Open→Merged at src 7.70 s (the change at 6.50 s is the stats/layout update). With t_in 7.05, Merged holds about 1.8 s. No push.
- **2**: the blur is now a transition: 1→4 frames over the last 0.35 s (project shot type `clip_tx`, which asserts the window is under 0.4 s).

## Flags for review
- **04**: "Split into 8 tasks." is supported by the 8 countable cards (4+3+1).
  The card IDs and the '4 tickets' label measure 14.5–14.7 px (under 18 even at 1.2x). The caption doesn't name them.
  From src 5.5 s, the Wave 2/3 cards show the real 'Blocked' dependency state.
- **14b**: Segment B (the Street glide in the right pane) is a 1.7x upscale of a DPR 1 take, which raises the check WARN `footage-dpr`.
  Closing the toast collapses the Workshop into the app layout in this take. That's why there are two segments.
- **03**: the composer still shows the amber Auto-approve pill from the old take.
- **16**: the drawer's real "Evidence: QA decision not recorded" block shows below the PR card. The UI is unedited.
- **15**: the float window's timeline shows Merged ticked from the start; the PR card badge flips Open→Merged only near the end of the shot (v1 design, unedited).
- **All footage is demo mode** (check WARN `footage-demo`).
- **9:16**: 48 px caption pills no longer fit the 608 px 9:16-safe column. A vertical cutdown needs its own caption size.

## Named-text measurement (`tools/named_v2.py`, `promo.named.element_px`, 1080 frame)
08 Running checks 21.1–22.2 px · Checks chip 20.0–21.1 · 10 Needs you 18.6–19.0 · 12 Approved line 22.1–23.1 ·
11 header 19.8–20.4 · Landed 19.8–20.4 · 16 Merged badge 18.0 (informational). Result: 0 FAILs.

## Lock
On this branch, promo takes `/tmp/commission-ai-cargo.lock` itself (`promo/lock.py`). It ran under `nice -n 10` without an outer `flock`,
because the SKILL warns that a second flock would deadlock.
