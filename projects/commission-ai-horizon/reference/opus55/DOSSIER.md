# DOSSIER: opus55

- source: /Users/patricklai/promo-ref/1f13Bl1sYkw.mp4
- why the user gave it (their words): another one in another style (Anthropic 'Introducing Claude Opus 5.5', the film I must match, not my summary of it)
- artefacts: `projects/commission-ai-horizon/reference/opus55/` (WATCH.md, watch.json, sheets/, cuts/, audio.wav, transcript.json)
- 1920x1080 @ 25.00 fps, 20.021 s, audio yes

Rules: replace every TODO line with what you actually saw and heard (timestamps, quotes). Do not summarise the
reference into a style name. Do not tick an Evidence box you did not do. A reference that is live action with people,
dialogue and sound design is not a 'look'.

## 1. Narrative beats

A single idea told by objects: "There's more to discover." Beats: 0:00-0:03 slow held limb of a dawn horizon (blue to orange band over black). 0:03.3-0:15.8 about 30 cuts of specimens, each framed as a curved planet-like horizon; the line appears at 0:09: "There's" (0:09-0:10.5), "more to" (0:11-0:12.5), "discover" (0:12.5-0:15.8), persisting across 3-7 cuts each. 0:15.8 cut to a quiet dark navy card: "Opus 5.5" then "Claude" with the sunrise limb glowing at the bottom, a slow rise, ~4 s hold, fade to silence at 20 s.

## 2. People & performance

None. Looked at every contact sheet: no human appears; the only 'performer' is the camera sliding along an edge. The feeling is wonder.

## 3. Dialogue/VO

No speech. transcript.json contains a single music-note glyph ("🎵" 11.38-12.78 s) and nothing else: no voice-over, no dialogue.

<!-- data (auto): transcript.json: 1 words -->

## 4. Music & sound design

From the audio metrics (I did not listen in real time): -20.5 LUFS integrated, peak -1.9 dBFS. The 2 s RMS curve is a long crescendo: -31.5, -29.6 (open, almost silent) -> -22 -> -16.8 -> -13.4 dB at 12-16 s (peak, under the fast cuts and the word 'discover') -> -21.6, -22.7 (end card) -> -70.9 (silence) at 20 s. 66 onsets in 20 s; cuts only loosely line up with them (27% within 60 ms, median 80 ms): it is a swelling score with a rhythmic pulse, not a per-cut foley design. Whisper's only token is a music note, so the track is instrumental. Shape to match: near-silent hold -> rise -> peak during the burst -> drop -> silence tail.

<!-- data (auto): LUFS -20.5; peak -1.9 dBFS; tempo guess 133.9 BPM; rms curve per 2 s [-31.5, -29.6, -22.2, -21.1, -16.8, -15.5, -14.3, -13.4, -21.6, -22.7, -70.9] -->

## 5. Camera & motion

Every shot is a slow slide or push along the curved edge of a specimen against a flat backdrop (black, white, magenta, ochre); the horizon crest is centred and sits at roughly 45-50% of frame height; motion is smooth, a few % of frame per shot; backdrops flip black/white/colour on nearly every cut, which is the energy. No handheld, no cuts on action.

## 6. Grade & light

Hard-saturated and high contrast, not a unified grade: honey-brown crust on pale grey, marbled ink in monochrome on black, terracotta Greek pottery on black, a feather in inverted false colour (green/magenta), agate slice (pink/teal) on flat magenta, ochre paper, cream. Texture is fine grain. The end card is dark navy with a thin blue-to-orange sunrise rim at the bottom.

## 7. On-screen text & graphics

One serif sentence ('There's' / 'more to' / 'discover'), about 7-10% of frame height, white or near-black chosen for contrast, centred, baseline just above the edge, persisting across cuts; end card 'Opus 5.5' then '* Claude' wordmark, centred at ~47% height. No UI, no captions, no logos until the end.

## 8. Pacing numbers

30 cuts in 20 s detected (scene threshold 0.28): mean shot 0.65 s, median 0.48 s, min 0.28 s, max 4.26 s (the end card). Between 3.3 s and 15.8 s the shots run 0.6 s at first and tighten to 0.28-0.44 s (about 2.7 cuts/s); open 3.3 s and end card 4.3 s are the holds. Cut rate per fifth 0.75 / 1.75 / 2.25 / 2.75 / 0.0.

<!-- data (auto): duration 20.021 s; 30 cuts; cuts/s 1.498; shot mean 0.65 median 0.48 min 0.28 max 4.26; cut-rate curve per fifth [0.75, 1.75, 2.25, 2.75, 0.0]; motion/s [0.0047, 0.1025, 0.029, 0.2881, 0.1457, 0.2209, 0.1193, 0.1574, 0.163, 0.1241, 0.1661, 0.2325, 0.2735, 0.2081, 0.4692, 0.2671, 0.0007, 0.0014, 0.0214, 0.1511] -->

## 9. The ONE thing that makes it work

Every cut is a different discovered thing (pottery, cell, ink, feather, agate) in the same simple frame (a curved edge with the sentence resting on it), so the viewer feels the sentence's meaning ('there's more to discover') before reading it, and a swelling score carries them to a quiet card.

## 10. What is transferable to this product

- The frame rule (curved edge, sentence on it, persisting across cuts) and the open/burst/card shape with a score that builds, peaks and falls to silence.
- The subject matter principle: the cuts must be *discoveries* (specimens: pottery shard, plant-cell slide, marbled ink, engraved coin, fossil, geode, a feather in negative colour), not generic textures; we can generate these as UI-free plates.
- For commission-ai the sentence must be about this product but keep the discovery spirit, e.g. "Tell it at night. / Wake up to merged PRs." (our product pitch) and the end card 'commission-ai'.

## 11. What is NOT transferable and why

- The reference sells a model without showing any product UI; our promo must still say what commission-ai is, so one or two real product frames (the Merged stepper) have to appear: decision needed on how much product to show.
- Real macro photography of museum/lab specimens: we generate the specimens with Grok video (conflicts with the team's real-footage-only rule; decision needed).
- Anthropic's sound production (a commissioned score): we use licensed library music (Kevin MacLeod, CC BY 4.0, attribution required) plus built risers and an impact.

## 12. Evidence read

Opened: sheets/sheet-01.png, sheet-02.png, transcript.json, WATCH.md, watch.json (numbers above incl. audio metrics and onsets), cuts/cut-003.jpg, cut-006.jpg, cut-010.jpg, cut-014.jpg, cut-022.jpg, cut-031.jpg (viewed together at 640 px each).

- [x] contact sheet read: sheets/sheet-01.png
- [x] contact sheet read: sheets/sheet-02.png
- [x] transcript.json read in full (1 words)
- [x] audio read: listened to audio.wav (or read the audio metrics + rms curve) and noted music/SFX/silence
- [x] 6 full-res stills examined (name them here, cuts/cut-NNN.jpg): cuts/cut-003.jpg cuts/cut-006.jpg cuts/cut-010.jpg cuts/cut-014.jpg cuts/cut-022.jpg cuts/cut-031.jpg 
