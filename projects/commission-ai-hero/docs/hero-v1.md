# commission-ai 60 s hero promo: v1 draft (1080p), internal review only

- `cuts/hero-v1-1080.mp4`: 1920x1080, 30 fps (1800 frames), H.264 High CRF 16, AAC 320k 48 kHz stereo, 60.000 s, faststart. **-14.0 LUFS, -1.2 dBTP.**
- `cuts/hero-v1-1080-social.mp4`: same picture, **-9.1 LUFS, -0.9 dBTP** after AAC (the WAV master is limited to -1.8 dBTP).
- `cuts/hero-v1-contact.png`: one labelled frame per shot.
- Built 4 Oct 2026 ~04:25 AEDT. Not published or uploaded anywhere.

## EDL (98 beats at 98 BPM = 60 s; every cut sits on a beat)
| # | Time (s) | Source (NEW/OLD) | Source in-out | Move | Caption |
|---|---|---|---|---|---|
| 01 | 0.00-2.45 | OLD shot-01-v1.mov (0a3c3acd) | 1.00-3.43 | push-in 1.25x→1.47x, robot bubbles painted out | wordmark + "Your AI dev crew" |
| 02 | 2.45-4.90 | OLD shot-02.mov | 0.90-5.83 (2x, blended) | push. Crop excludes the amber robots pill and HUD | – |
| 03 | 4.90-9.80 | OLD shot-03.mov composer over a **dark-gradient plate** | typing 1.10-9.35 in 3.9 s, then hold | floating rounded composer, slow scale-up | (typed ask) |
| 04 | 9.80-15.31 | OLD shot-04-v1.mov (planning board) | 12.50-19.49 (1.27x) | 1.6x→1.7x | "Split into 8 tasks." |
| 05 | 15.31-20.20 | OLD shot-05-v1.mov (promo take bc10d245) | 0.60-5.50 | push ~2.9x on the rail | lower thirds Claude Code / Codex / Cursor |
| 06 | 20.20-23.27 | OLD shot-06 stills | stills | 3D tilt card | "Each task gets its own worktree." |
| 08 | 23.27-25.71 | OLD shot-08-v1.mov (PAY-104 drawer) | 2.95-6.38 (1.41x) | macro on the pipeline chips, 3.7x→4.0x | "Running checks" |
| 09 | 25.71-27.55 | OLD shot-09-v1.mov (PAY-105 drawer) | 0.50-2.37 | 2.5x→2.7x | – |
| 10 | 27.55-33.06 | **NEW** v1-1080/shot-10.mov (4a427fc0, ?demo=promo) | 0.55-6.05 | 2.6x→3.0x on the PAY-106 card | "Only pings you when it matters." |
| 12 | 33.06-39.18 | OLD shot-12-v1.mov (PR #121) | 4.20-5.55 (0.84x), then 5.55-6.64 held (0.24x) | 2.3x→2.4x on "About this change" | "Every change explained." |
| 15 | 39.18-42.86 | OLD shot-15.mov (promo) over a **dark-gradient plate** | 5.90-9.57 | floating window. A: chips Pushed→PR raised→Merged, then a dissolve to B: PR #438 Open→Merged | caption on the plate |
| 11 | 42.86-45.92 | OLD shot-11-v1.mov (promo) | 10.80-13.87 | pull-out 2.5x→1.28x, Landed column to the board | "8 tasks · 3 agents · all merged" |
| 16 | 45.92-48.98 | OLD stills (16a Landed, 14b street, 15 PR #438 Merged) | stills | 3 tiles slide in | – |
| 14b | 48.98-55.10 | OLD shot-14b.mov | 7.40-13.53 | glide 0.74→0.60, bubbles painted out | "Every token builds something." |
| 17 | 55.10-60.00 | shot-01 frame, blurred and darkened | held | 3% push | wordmark, "Your AI dev crew, on your Mac.", "macOS alpha" (URL off) |

Shot 07 is dropped (no new promo cards). Shot 13 is benched. Full machine-readable EDL: `cuts/work/hero/edl-hero-v1.json`.

**New vs old footage:** only **shot 10 is new** (the only file in `footage/v1-1080/` as of ~04:25, with no manifest). Every other shot uses the previous takes listed above.

## Shots 3 and 15 (Workshop plates)
Neither the night (workshopHour=22) nor the morning (7) plate has been captured, so both shots use the **dark-gradient fallback**: the UI floats as a rounded window over `dark_plate()`. Nothing was brightened. When the plates arrive, check night-plate legibility at 1080p first. If it fails, use the morning plate or keep the fallback. To swap, add `plate-night` / `plate-morning` to `sources.json`.

## Shot 11 caption check
The frame shows 8 tickets (PAY-103…110), all "Done" in "Landed · Merged and closed", with Claude / Codex / Cursor logos. That is 3 agents and all merged, so "8 tasks · 3 agents · all merged" matches. No change was needed. The final framing is wide enough that the caption clears the card column. The "8 in this run · 8 landed" header sits just above the frame.

## Music
"Upbeat Hip-Hop Beat" by **BombinSound**, Pixabay id 491119, https://pixabay.com/music/upbeat-upbeat-hip-hop-beat-491119/
- Licence: **Pixabay Content License**, commercial use allowed, no attribution required. Optional credit: "Music by BombinSound from Pixabay". Not Content ID registered, not AI-generated.
- Saved with LICENSE.md in `audio/music/491119/`. Alternatives: `audio/music/588369/` and `audio/music/525029/`. (FreePD.com has permanently closed.)
- Edit (`audio/music_edit.py`): 98 BPM, re-cut on bar lines to exactly 60 s.
  - drop at 9.80 s (start of shot 04)
  - filtered breather at 34.3-39.2 s
  - re-drop at 39.18 s (shot 15 Merged)
  - hard stop at 58.78 s

## Voiceover
- **Kokoro-82M v1.0** (Apache-2.0), voice **bf_emma** (en-GB, warm/confident), speed 0.95, rendered offline via kokoro-onnx. Licence and source: `audio/vo/LICENSE.md`.
- Script: the locked `promo/marketing/vo-script-v1.md`, verbatim. Line 5 is split across shots 05/06. There is no VO over shots 11 and 16.
- The ASR read-back is word-correct, and on listening the voice sounds natural, not robotic, so it ships in the mix. Stems are kept separately: `audio/vo/stems/` and `audio/mix/stem-vo.wav`.
- Kokoro has no en-AU voice, so en-GB is used.

## Mix
- Levels: music bus -5 dB, SFX -8 dB, VO lines levelled to -16 LUFS then +1.5 dB.
- Ducking: **music ducks 7 dB under VO** (120 ms attack / 350 ms release) and 3 dB under the chime.
- Limiting: true-peak limiter.
- Stems are in `audio/mix/`; see `mix-report.json`.

### SFX (synthesized, `audio/sfx/make_sfx.py`; no third-party samples)
| t (s) | SFX | Moment |
|---|---|---|
| 2.60 | long whoosh | shot 02 fly-through |
| 4.93→ | typing patter | shot 03 |
| 10.58, 11.45, 12.33, 13.20, 14.06 | ticks | shot 04 plan nodes pop |
| 15.81, 16.81, 17.81 | ticks | shot 05 rail rows light |
| 20.08 | short whoosh | shot 06 |
| 23.30 | tick | shot 08 Coding→Checks |
| **28.25** | **chime (the only chime)** | **shot 10 Needs you** |
| 30.95, 31.25 | ticks | shot 10 Allow once click, back to Running |
| 34.45 | soft tick | shot 12 explanation appears |
| 39.38, 40.28 | subtle swell + tick | shot 15 Merged (no chime) |
| 41.48 | tick | shot 15 PR badge flips to Merged |
| 45.82 | short whoosh | shot 16 tiles |

## Loudness (measured by ffmpeg ebur128 on the final MP4s)
| File | Integrated | True peak |
|---|---|---|
| web | -14.0 LUFS | -1.2 dBTP |
| social | -9.1 LUFS | -0.9 dBTP |

## Changes vs rough v0
- New beat-locked timeline: 98 BPM, all cuts on beats, exactly 1800 frames.
- Licensed music edit in place of the temp track.
- Kokoro VO from the locked script.
- Synth SFX with the chime only on shot 10.
- New shot-10 capture.
- Placeholder labels removed. Shots 3/15 float over a dark plate.
- Robot bubbles painted out on 01, 14b, 16 and 17.
- Crops remove the amber robots pill, HUDs, "$" spend, the "Blocked" card, the Review chip/button and the "YOUR MOVE / Waiting for you" headers.
- Shot 07 dropped, shot 13 benched.
- New captions in a fixed, 9:16-safe zone.

## Open items
1. **Old footage on 14 of 15 shots**, waiting on the v1-1080 recapture (no manifest yet). Data mismatches on old takes:
   - 04: the plan board is a different capture of the checkout plan
   - 08: PAY-104 drawer, agent Claude
   - 12: **ops-toolkit PR #121 "Round refunds per line in cents"**, the wrong project. Only the "About this change" explanation is shown, held; "Blockers found" and Findings are out of frame or out of time
   - 15/16: PR #438
2. **Shot 03:** the composer shows the amber "Auto-approve" toggle, from the old take. Decide whether that's OK or recapture with it off.
3. **4K:** the edit rebuilds at 3840x2160 (`HERO_SCALE=2`), but the new v1-1080 footage is DPR1. Pushes up to 3x are upscales (soft even at 1080 on shot 10 and on 08 at 4x). **A 4K final needs DPR2 recaptures.**
4. Bubble paint-out can leave faint smudges on 01/14b/16/17; a clean capture with bubbles disabled would be better.
5. Shot 12 is a time-stretched hold (0.24x over a static panel). Fine visually, but a new capture with a longer "About this change" dwell is preferred.
6. URL line on the end card is off (URL undecided). Social true peak is -0.9 dBTP after AAC (the target was ≤ -1). If a platform is strict, re-run `build_mix.py` with a lower social ceiling.
7. Workshop night/morning plates are still needed for 3 and 15 (see above).

## To rebuild
```
cd cuts/work/hero
../../../.venv/bin/python build_hero.py 01 02 03 04 05 06 08 09 10 12 15 11 16 14b 17   # one shot at a time, -threads 2
../../../.venv/bin/python make_events.py && ../../../.venv/bin/python ../../../audio/build_mix.py
../../../.venv/bin/python assemble_hero.py        # concat + mux + contact sheet
HERO_SCALE=2 ...                                  # same commands -> segs-3840 / hero-v1-2160*.mp4
```
