# Audio stack for promo-reel (research, 20 Oct 2026)

Why: our videos look better than they sound. Generated voices came out flat, sometimes artifacty, sometimes cut off.
This note is the research behind `skills/promo-audio-route/SKILL.md` and the order of the work that follows it.
Prices and rankings move monthly; re-check the sources before relying on a number.

## What was wrong in our own pipeline (measured on 6 real projects)

- **Clipping.** The VO cache was written as PCM_16, which hard-clips any sample over ±1.0. Kokoro peaks a little over 1 on loud
  lines (commission-ai-jev line 18: 1.021, stored as 1.000). Takes are now cached as raw float.
- **Clicks and lost soft endings.** The trim used an absolute floor (0.01, about -40 dBFS) with no fade: a quiet take lost its
  last soft sounds, and every take started and ended on a hard cut (first 5 ms at -41 to -56 dB against the line's loudest window).
  The trim is now relative to the take's own peak (-45 dB), keeps 20 ms before and 100 ms after, and fades both edges
  (first / last 5 ms now -62 to -79 dB). The cache holds the untrimmed take, so a trim change never re-synthesises (or re-bills).
- **Music click.** `silence_from_beat` dropped the music to zero in one sample; it now fades over 30 ms.
- **No gate on fit or damage.** A line running past the film's end was silently truncated by the mix. New `promo check` gates:
  `vo-fit` (FAIL past the end, WARN > 0.25 s into the next line), `vo-clip` (flat-topped samples), `vo-tail` (ends mid-sound).
- **One take per line.** Now `takes: N` with automatic rejects (whisper WER, tail energy) and a pick by ear.
- **A gate turned off.** commission-ai-hero runs its VO lines at `max_wer` 0.5-1.0, so the read-back gate would let a cut-off
  line through there. Left as is (a project choice), flagged here.

No project had a line past the film's end, an overlap, or a dropped last word, so "cut off" was most likely the trim and the
missing fades rather than the timeline.

## Voices (Artificial Analysis Speech Arena and the OpenRouter speech catalogue, both fetched 20 Oct 2026)

| Model | Elo | Price | Released | Route |
|---|---|---|---|---|
| Eleven v4 / v4 Turbo | 1328 / 1330 | $80 / $40 per 1M chars | 28 Sep 2026 | OpenRouter `elevenlabs/eleven-v4`, or the ElevenLabs API |
| Qwen-Audio-3.1-TTS-Plus | 1298 | ~$19 per 1M chars | Sep 2026 | Alibaba (3.0 is on OpenRouter) |
| Gemini 3.8 Flash TTS | 1279 | $0.5 / 1M input tokens + $9 / 1M audio tokens (25 per second) | Sep 2026 | OpenRouter `google/gemini-3.8-flash-tts` |
| Fish Audio Drama 3 | 1247 (#1 open weights) | ~$2 per 1M chars | Oct 2026 | OpenRouter `fish-audio/drama-3` |
| Kokoro-82M (our default) | 1065 | free, local | Jan 2025 | `kokoro` engine |

- **Eleven v4**: inline audio tags (`[whispers]`, `[sighs]`, `[pause]`), no SSML `<break>`; stable voice across regenerations.
  The ElevenLabs API itself adds `previous_text` / `next_text`, 48 kHz pcm and character timestamps (not on OpenRouter).
- **Gemini 3.8**: delivery goes in `instructions`; directions written into the text are spoken. Only pcm output. Multi-speaker turns.
- **Fish Drama 3**: 35B-A3B, community licence on the weights (free under $500k revenue, "Built with Fish Audio" notice). Does
  not fit this Mac at bf16 and has no MLX port, so it is OpenRouter-only for us.
- **Local and licence-clean**: Qwen3-TTS 1.7B (Apache-2.0) and Chatterbox Multilingual (MIT) via mlx-audio, both proven in
  `~/work/avatar-poc`. Step-Audio-EditX (Apache-2.0) re-edits the emotion and breaths of an existing take.

### Measured here (three commission-ai-jev lines, each voiced four ways; the WAVs are kept out of git)

| | Kokoro before | Kokoro after | Gemini 3.8 (Kore) | Eleven v4 (alice) |
|---|---|---|---|---|
| words / s | 2.6-3.2 | 2.6-3.2 | 1.7-2.4 | 2.1-2.5 |
| pitch spread (semitones) | 2.0-2.3 | 2.1-4.2 | 4.8-5.8 | 4.4-5.6 |
| edge (first/last 5 ms, dB) | -41 to -56 | -70 to -74 | -62 to -79 | -72 to -78 |
| whisper WER | 0 | 0 | 0 | 0 |
| clipped | line 18 (cut to 1.000) | none (1.021 kept) | 2 of 3 lines arrive clipped | none |
| billed for the 3 lines | free | free | $0.0058 (+ 2 extra takes $0.0025) | $0.0250 |

The hosted voices move their pitch about twice as much as Kokoro (a rough sign of a less flat read) and read 25-45 % slower,
so a script timed on Kokoro overlaps on them (`vo-fit` WARNs). Gemini's output sometimes clips at the provider; `vo-clip`
catches it and the fix is another take. Which one sounds best is a listening call for the person, not a number.

### OpenRouter `/api/v1/audio/speech` (what the code relies on)

- Body: `model`, `input`, `voice`, `instructions` (Gemini, Fish, OpenAI), `speed`, `response_format` (`pcm` default, or `mp3`;
  Gemini refuses mp3), `input_references` (cloning), `provider.options`.
- Response: raw audio; `Content-Type: audio/pcm;rate=24000;channels=1` carries the format (16-bit little-endian);
  `X-Generation-Id` names the generation.
- Billing: `GET /api/v1/generation?id=...` → `data.total_cost`; the record lands some time after the audio (still missing 10 s later in real runs), so `promo vo`
  settles costs once at the end of the run.

## Other layers (not built yet; draft tickets)

| Layer | Best now | Notes |
|---|---|---|
| Direction | per-engine translation of one `direction:` per line; a pronunciation lexicon; neighbouring-line context | Eleven tags, Gemini instructions, Fish tags |
| VO polish + mix | high-pass, de-ess, glue compression, room tone; speech-band (1-5 kHz) ducking; Sidon (ICASSP 2026: denoise, dereverb, bandwidth extension to 48 kHz) | a `vo-mix-asr` gate: whisper on the mixed voice, not just the stem |
| Scoring | UTMOSv2 / `utmos` (MPS), DNSMOS | advisory only: scores favour flat reads |
| ASR | whisper large-v3-turbo, Parakeet TDT | better word timings for lip-sync and lyric sync |
| SFX | MOSS-SoundEffect v2.0 (Apache-2.0, 48 kHz, MLX 4-bit port); ElevenLabs `eleven_text_to_sound_v2` (0.5-30 s, loops) | Stable Audio 3 Small-SFX: sources disagree on its licence |
| Music | ElevenLabs Music v2.5 (11 Sep 2026, ~$0.15/min, sections with `duration_ms`, so cuts can sit on our bars); Lyria 3.5 | Suno v6: no API and open litigation, skip |
| Stems | Mel-band / BS-RoFormer, SAM Audio | for re-cutting licensed tracks |
| Local voices | an `mlx` engine for Qwen3-TTS / Chatterbox | the free offline step up from Kokoro |

## Skills on the web

- `elevenlabs/skills` (official, MIT): TTS, SFX, music, voice isolator, voice changer, STT. A good API reference.
- OpenMontage `hyperframes-media`: AGPL-3.0, so nothing is copied from it.
- Community voice-audio-engineer and pexo audio-studio skills.

None knows promo-reel's licence gate (rule 4), evidence rule (rule 3) or gates, so we wrote our own: `skills/promo-audio-route/`.

## Sources

- Artificial Analysis Speech Arena: https://artificialanalysis.ai/text-to-speech/leaderboard and
  https://artificialanalysis.ai/text-to-speech/leaderboard/provider-voice/open-weights
- TTS models ranked, Sep 2026: https://www.digitalapplied.com/blog/best-text-to-speech-models-september-2026-ranked-priced
- Eleven v4: https://elevenlabs.io/v4
- Gemini 3.8 Flash TTS: https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts
- Fish Audio Drama 3: https://explainx.ai/blog/fish-audio-drama-3-open-weights-35b-a3b-word-level-editing-how-to-run-2026
- OpenRouter speech: https://openrouter.ai/docs/features/multimodal/tts and https://openrouter.ai/collections/text-to-speech-models
- ElevenLabs skills: https://github.com/elevenlabs/skills
- MOSS-SoundEffect: https://huggingface.co/ilintar/moss-soundeffect-gguf
- Music models, 2026: https://www.teamday.ai/blog/best-ai-music-models-2026
