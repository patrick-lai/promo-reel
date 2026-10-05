# Music grid: "Eternal Hope" (Kevin MacLeod)

Asset `music-eternal-hope` (`media/music/eternal-hope.mp3`, 284.06 s). All times are in the `librosa.load(sr=...)` timeline, i.e. the same
decode `promo/music.py` uses, so they can be pasted into `music:` as is. Method: spectral-flux onset envelope (44.1 kHz, hop 256 = 5.8 ms),
comb-filter search over BPM (step 0.001) and phase (1 ms), cross-checked with onset residuals (median of on-beat onsets), librosa beat tracker,
per-window phase drift, per-beat low-band energy / chroma change for bar phase.

## Verdict: not a rigid-tempo track
It is an expressive piano/strings piece with rubato and real pauses, not a click-locked loop. A single global grid is only good locally:

| section (track time) | tempo | note |
|---|---|---|
| 0.00-1.50 | silence (about -99 dB), a 0.03 s tick at the very start | first piano note at 1.521 s |
| 1.5-39.3 | 100.43 BPM (T = 0.59741 s) | steady piano. Onsets sit within +-10 ms (MAD 11 ms) of the grid in 1.5-11 and 21-39 s; the 11.5-21.5 s window sits about 80 ms early (rubato). 24 of 66 detected onsets fall on a beat, the rest are off-beat eighths |
| 39.35-41.55 | pause | 2.2 s of near silence (-71 dB) |
| 41.6-50.3 | 102.05 BPM | |
| 50.3-51.0, 59.9-60.35 | short pauses | |
| 60.4-83 | about 94-97 BPM | slower, sparse, drifting |
| 83.5-100 | 102.46 BPM | after the entry |
| 100-280 | 101-120 BPM, accelerating | not usable with a constant grid |

## Grid to use (section 1.5-39.3 s, extended by fractional beats elsewhere)
- `bpm` = **100.434** (`track_beat` = 0.597408 s)
- beat-0 offset (`track_offset`) = **0.038 s** (+-10 ms in the steady stretches; comb search alone gave 0.043, onset median 0.038)
- Bar phase: beat index mod 4 == 0 is the likely downbeat (low-band energy +0.55 sd vs <= +0.16 on the others, chroma change peaks on beats 0 and 2). Confidence: moderate, the piano is arpeggiated and soft. The first bar downbeat with sound is track beat 4 = 2.427 s (the piano starts 0.9 s earlier with a three-note pick-up at 1.521 / 1.852 / 2.136 s), so start the edit at track beat 4, not 0.
- Tempo beyond about 40 s differs from this grid, so beats there are not beat-locked: use fractional track beats `(t - 0.038) / 0.597408` to land on a chosen moment, never count integer beats across the pauses.

## Intro and swell
- Intro: sparse solo piano 1.5-39.3 s, pause 39.35-41.55 s.
- Swell: a soft chord strike at **82.735 s** (-52 -> -30 dB), then the full strings/choir entry at **83.78 s** (-42 -> -25 dB, about +17 dB over the preceding bed; level stays at -25 to -36 dB afterwards, 104-112 s reaches -25). That is the "big entry" (the earlier 82.5 s estimate was the precursor). It is not on the 100.43 BPM grid (track beat 140.18); the section after it fits 102.46 BPM with the entry about 160 ms after its nearest beat.

## Proposed ~60 s edit (swell at 75% of the runtime)
```yaml
timeline: {bpm: 100.434, beats: 100}      # 100 beats = 59.741 s; 100.434 beats = 60.0 s exactly
music:
  asset: music-eternal-hope
  bpm: 100.434
  track_beat: 0.597408
  track_offset: 0.038
  edit:
    # seg 1: track beats 4-52 = 2.427-31.10 s (bar-aligned start, steady piano section), ends on a piano onset (6 ms)
    # seg 2: starts at track beat 113.176 = 67.650 s so that the 83.78 s entry lands exactly on edit beat 75 (44.806 s);
    #        runs 52 beats to 98.7 s (still inside the loud, fuller section)
    segments: [[0, 4, 52], [48, 113.176, 165.176]]
    crossfade: 0.030
    gains: [{beats: [98.5, 100], db: -30, ramp: 2.4}]    # about 3.5 s fade-down at the end
    silence_from_beat: 100
```
As [[0,0,N],[N,swell_beat,M]]: N = 48, swell track beat = 113.176 (start of seg 2), M = 165.176; the first segment starts at track beat 4, not 0, because beats 0-3 are silence plus a pick-up.
Rendered with `promo.music.edit` on this asset (scratch run, not committed): length 59.741 s; the join at edit beat 48 (28.68 s) has no click (max sample step 0.003 over +-4 ms); the 83.78 s entry lands at edit 44.806 s (= beat 75.0) with the 100 ms RMS rising about 6x (0.0083 -> 0.0510); the precursor chord lands at 43.77 s (beat 73.3). Unverified by ear: the musical quality of the join at 31.10 s -> 67.65 s (both sides are sustained piano; it is not placed on an onset on the seg 2 side, the nearest onset there is 71 ms away).
Variant: to land the precursor chord (82.735 s) instead of the entry on edit beat 75, start seg 2 at track beat `(82.735 - 0.038)/0.597408 - 27` = 111.43 (and end it at 163.43); the entry then falls 1.04 s (1.74 beats) later.

Cuts on this music should be placed on edit beats 1-bar apart from 0 (bar downbeats at edit beats 0, 4, 8, ... in seg 1; in seg 2 the bars are NOT locked to the same phase, treat seg 2 as free time and cut on the swell (beat 75) and on beats 75 + n).
