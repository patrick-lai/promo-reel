# Music grid: "Floating Cities" (Kevin MacLeod)

Asset `music-floating-cities` (`media/music/floating-cities.mp3`, 184 s; incompetech lists 120 BPM). Times are in the `librosa.load` timeline, the same
decode `promo/music.py` uses. Method: spectral-flux onset envelope (44.1 kHz, hop 256 = 5.8 ms), comb search over BPM 110-125 (step 0.001) and
phase (1 ms), cross-check with the median residual of 193 on-beat onsets, librosa beat tracker, per-10-s phase drift, per-beat low-band / onset /
chroma statistics for bar phase.

## Grid (rock steady: a sequenced loop)
- **bpm = 120.000** (`track_beat` = 0.5 s). Best-fit BPM over the whole 184 s is 120.000; the beat tracker says 120.19 (a quantisation of its 5.8 ms frames, not real drift). The phase drift between 10 s windows is 0 to 2 ms over the whole track, so one grid fits the entire file. The earlier librosa-default 117.45 BPM was an estimate error.
- **beat-0 offset (`track_offset`) = 0.037 s**, +-3 ms (onset-median 0.0369, MAD 1.9 ms over 193 onsets; comb search 0.039). The first beat is the first sound (the file starts on beat 0).
- Bar phase: beat index mod 4 == 0 is the strongest beat (onset +0.45 sd vs -0.45 on beat 1, +-0.02 on 2 and 3; low band +0.27 on beat 0). 4/4 (the mod-3 statistics are flat). So **the first strong downbeat is bar-aligned**: bars start at 0.037 + 2.0 n s, and the file already begins on a downbeat. Confidence: good.

## Structure (per-bar levels; bars are 2.0 s)
Overall level is flat (about -22 to -26 dB RMS), so "builds" here are layer entries rather than loudness ramps:
| time | bar | event |
|---|---|---|
| 0.04-8.04 | 0-3 | sparse intro: sub/low drone + faint mid (5 dB), -25.5 dB |
| **8.04** | 4 | biggest novelty in the file: mid layer enters (+12 dB mid band, +2.5 dB overall) |
| 28.0 | 14 | high-band layer wavers in and out |
| 64.0 | 32 | bass lifts (+5 dB low band) |
| 76.0 / 96.0 / 108.0 | 38 / 48 / 54 | smaller section changes |
| **132.0** | 66 | percussion/high-frequency density up (flux 0.8 -> 1.1); stays until the fade-out at about 180 s |
| 180-184 | 90 | ending decay |

## 20 s excerpt with a clean build (recommended)
Track 0.037-20.037 s = 10 bars = 40 beats. Sparse drone for 4 bars, the whole bed arrives on bar 5 (edit beat 16 = 8.0 s = 40% of the excerpt) and stays for 6 bars.
```yaml
timeline: {bpm: 120, beats: 40}            # 20.000 s
music:
  asset: music-floating-cities
  bpm: 120
  track_beat: 0.5
  track_offset: 0.037
  edit:
    segments: [[0, 0, 40]]
    gains: [{beats: [38, 40], db: -18, ramp: 1.0}]     # optional 1 s duck at the end
    silence_from_beat: 40
```
The cut is bar-aligned at both ends; the excerpt ends mid-texture (no natural cadence), hence the optional gain dip.
Alternative (lower confidence, listened by metrics only): track 116.037-136.037 s (`segments: [[0, 232, 272]]`) puts the bar-66 percussion step at edit beat 32 (16 s, 80%); the level is flat there, so the build is rhythmic density, not loudness.
