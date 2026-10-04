# commission-ai hero v3 (1080p): build notes, 2026-10-04

v3 = v2 plus Zen's notes on v2 (3.86, Truth PASS). Same branch/worktree (`hero-v2`). No promo-reel code changed.
Output: `out/hero-v3-1080.mp4`, copied to `/workspace/videos/commission-ai-promo/cuts/hero-v3-1080.mp4`.

## Fixes
1. **S15 (Story)**: the shot now uses `shot-15-prcard` (manifest id `shot-16-prcard-v1080`) in the morning float window.
   - **Measured, not 6.5 s:** in this take the badge flips Open→Merged at **src 7.70 s**. The change at 6.50 s is the drawer status flipping to Done, plus the layout shift. Frame grabs at 7.0 and 7.5 s still read "Open". Merged holds only 7.70–9.50 s (1.8 s).
   - **Start time:** t_in is 5.83, the latest start that fills the 3.67 s slot inside the 9.50 s take (a 6.3 s start would run past the end).
   - **Merged frames in the output:** frames 1232–1285, which is 41.067–42.867 s (Sydney cut time). Frame 1231 still reads Open. Checked by frame grab.
   - **Line moved to S16:** with only 1.8 s of Merged (under the 2.0 s caption gate) and the S15 badge at 12.7 px (under 18 px), "Wake up to merged PRs." moved to S16's flip as VO. It starts at S16 0.52 s, and the flip is at 0.65 s.
   - **No caption on S15 or S16:** the S16 fixed caption zone would cover the drawer's Evidence description text. S15 keeps the VO "Go to bed." with no caption.
   - **Right-edge clip fixed:** the window now holds the whole drawer width (src x 670–1890), so the PR card's "Open" link is no longer cut.
2. **S11 (Calm)**: the header segment is held at the 1.2x cap, anchored top-right, for the whole segment (v2 was 1.16→1.2x). all8 goes 1.14→1.2x on the column plus the Plan more card.
   - **Not fully fixable:** the header and the Landed column sit about 700 source px apart, so at ≤1.2x roughly half the frame is still the dotted canvas. Filling the frame needs a recapture (a narrower viewport, or a crop of only the header and column), or a push above 1.2x.
   - **Caption:** "8 TASKS · ALL MERGED" is unchanged and clear of the UI. It sits at output x≈660–1260; the column starts at x≈1416.
3. **S05**: the crop's right edge now sits on the Commander pane edge, so the message actions and the pane's ⋯ menu are no longer cut (0.39→0.38 width; v2 was 0.37→0.345).
4. **S14b**: now uses `shot-14b-dusk-r2`, registered with `promo footage add` (sha 91cd3b33…). It uses 0.13–2.50 s and 3.70–7.47 s, so the 2.7–3.5 s collapse/re-expand flicker is cut.
   - Both segments are full-screen, at 1.25–1.3x, cropped clear of the toasts, top bar and HUD. The 1.7x soft enlargement and its check WARN are gone.
5. **S04**: kept the current take.
   - `shot-04-dpr2.mov` appeared at 12:29 but was not in `footage/v1-1080/manifest.md` when checked.
   - Its capture log shows `?demo=1&still=1`: the demo=1 board with PAY-101/102, #412/#413 and "2 need you". So it shows the wrong run and doesn't show the 8-task plan.
   - Recapture on `?demo=promo` for the S04 swap.

## Also changed
- **S12**: now uses `shot-12-dpr2-z179` (registered). The manifest says it REPLACES `shot-12-dpr2`; the old take showed literal `**` around the request text. The framing is the same, and the reviewer line is 22–23 px.

## Named text (tools/named_v3.py, promo.named.element_px)
- S11: the header '8 in this run · 8 landed' measures 20.4 px and 'Landed' 20.4 px (PASS). 'Merged and closed' is 16.8 px (INFO).
- S16: the 'Merged' badge measures 18.0 px (PASS; VO names it).
- S15: the 'Merged' badge measures 12.7 px (INFO; nothing names it in v3).
- S04: the card IDs and '4 tickets' measure 14.5–14.7 px (INFO; the caption rests on the 8 countable cards, as in v2).
- 08/10/12 are unchanged and PASS. Result: 0 FAILs.
