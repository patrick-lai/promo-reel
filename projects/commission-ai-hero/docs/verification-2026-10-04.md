# promo-reel port: end-to-end verification (4 Oct 2026, ~05:40 AEDT)

Clean build from scratch: `promo fetch` (music re-downloaded from the Pixabay CDN, sha256 matched), then `promo build` (8.5 min on 8 cores), then `promo check`.
Output: `out/hero-v1-1080.mp4` and `out/hero-v1-1080-social.mp4`, 1920x1080, 30 fps, 1800 frames, 60.000 s. **`promo check` passes** (exit 0).
- Web: -14.0 LUFS / -1.2 dBTP. Social: -9.1 LUFS / -1.2 dBTP.
- WARNs, left for a human: shot 10 is DPR1 footage pushed 3.0x (soft); all footage is demo mode; the shot 05 rail labels show for 1.9 s each.

## `promo compare` against the legacy `cuts/hero-v1-1080.mp4`
| Shot | PSNR | Why |
|---|---|---|
| 02 03 04 05 06 08 09 10 12 15 16 14b | inf (identical) | faithful port |
| 01 | 38.3 dB | no robot-bubble paint-out (team rule: no UI edits in post) + the caption "Your AI dev crew" now enters at 0.40 s instead of 0.55 s so it holds 2.05 s |
| 11 | 41.9 dB | the caption "8 tasks · 3 agents · all merged" now enters at 1.00 s instead of 1.35 s so it holds 2.06 s. It overlaps the card column for ~0.3 s during the pull-out: needs a visual OK |
| 17 | 52.3 dB | no bubble paint-out on the end-card background (blurred, so the difference is tiny) |

Audio: web master identical (max |diff| 0). The music edit, SFX, VO stems (Kokoro re-rendered) and events.json are all bit-identical to legacy.
Social master: same WAV as legacy. The AAC encode now uses an 18 kHz cutoff (`aac_cutoff`), because legacy measured -0.9 dBTP after AAC, over the -1 dBTP gate. Lowering the WAV ceiling to -2.3 made it worse (-0.3 dBTP).

Open (needs a human): reshoot 01/17 with the bubbles disabled (or accept the bubbles), shot 10 at DPR2, and everything in `hero-v1.md` "Open items".
4K: `--scale 2` was checked on shot 09 (3840x2160, 56 frames). The full 4K build was not run.
