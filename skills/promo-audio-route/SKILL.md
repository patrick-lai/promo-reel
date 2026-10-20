---
name: promo-audio-route
description: Pick a voice for promo-reel VO lines by quality, price and licence (free local Ming-3.0-tts or Kokoro vs Gemini 3.8 Flash TTS vs Eleven v4 vs Fish Drama 3 on OpenRouter), direct the read, make takes and pick one by ear, and read the VO audio gates (vo-fit, vo-clip, vo-tail). Use when a voice sounds robotic, artifacty or cut off, when asked which TTS model to use, when voicing a hero / podcast / explainer, or when the user runs /promo-audio-route.
---

# promo-audio-route

promo-reel voices every VO line with `promo vo` (promo/vo.py). This skill picks **which voice**, how to **direct** it and how to
**choose a take**. Rule 4 (AGENTS.md) still holds: every voice has an assets.yaml entry with its licence and source.
Research behind it (Oct 2026 leaderboards, prices, what to add next): `docs/audio-stack-2026-10.md`.

## Pick the voice

First question: does this board hold the person's OpenRouter key (`commissionctl secret list` names `OPENROUTER_API_KEY`)?
Keys are saved per board in CommissionAI; there is no app-wide key yet, so a new board starts without one.
- **No key, or they don't want to pay**: the free local voice, `engine: mlx`. Never block on a key; offer the hosted voice as an upgrade.
- **Key saved**: Gemini 3.8 by default, Eleven v4 for hero lines. A missing key on a paid line refuses the run before anything is
  sent and names the local voice.

| Need | Engine / model | Price | Notes |
|---|---|---|---|
| **Free, good** (the default without a key) | `mlx`: Ming-3.0-tts-0.5B (MIT) on this Mac | free | #1 open weights on the AA pronunciation board (Oct 2026). Voices `UK_Charlotte`, `UK_George`, `US_Emma`, `US_James`, `US_Stella`, or `instructions` for a voice designed from words. ~0.6-0.8x real time on an M5 Max, 44.1 kHz. Pitch moves about twice as much as Kokoro's. A faint noise floor (~-50 dB) in pauses; mishears a word now and then, so use `takes: 2-3` on long lines |
| Free, zero setup | `kokoro` (Kokoro-82M, Apache-2.0) | free | Speech Arena Elo ~1065 (Jan 2025). Fast and clean, but flat: reads ~3 words/s with little pitch movement |
| Default paid voice | `openrouter`, `google/gemini-3.8-flash-tts` | ~$0.02 / 1k chars | Elo ~1279. 30 voices (`Kore`, `Puck`, ...). Direct it with `instructions`. Its output can arrive clipped: watch `vo-clip` |
| Hero lines, the voice that sells | `openrouter`, `elevenlabs/eleven-v4` | $0.08 / 1k chars (`-turbo` $0.04) | #1 on the Speech Arena (Elo ~1328, Sep 2026). Voices: `alice`, `george`, `sarah`, ... Direct it with inline tags |
| Cheap, open weights | `openrouter`, `fish-audio/drama-3` | ~$0.002 / 1k chars | #1 open-weights model (Elo ~1247). Its weights' community licence (free under $500k revenue, a "Built with Fish Audio" credit) is not the API's terms; check both |
| The person's own voice | Chatterbox / Qwen3-TTS (local, see the own-avatar section of `skills/promo-reel/SKILL.md`) | free | consent in brief.yaml first (rule 1 carve-out) |

`promo vo voices` lists every OpenRouter speech model with its price per 1,000 characters (public catalogue, no key);
`promo vo voices --model M` lists all its voices. Hosted voices read 25-45 % slower than Kokoro, so a script timed on Kokoro
will overlap when it moves to them: re-run `promo check` and read `vo-fit`.

## Set it up

**Local voice** (one time per Mac, ~20 s when the model is already cached, else a ~3 GB download): `promo vo setup`. It makes a
venv of exact versions in `~/.promo-tools/venv-mlx-tts-<pin>`, fetches the model at a pinned revision and reads a test line;
running it again does nothing. `promo vo voices --local` lists the voices and says whether it is set up.

```yaml
vo:
  engine: mlx
  voice: UK_Charlotte                      # or instructions: "A calm, warm narrator ..." (not both)
  asset: local-voice
  lines: [...]
# assets.yaml
  - id: local-voice
    kind: vo_model
    path: build/vo
    licence: "Ming-3.0-tts-0.5B weights: MIT (inclusionAI). Terms of its built-in speakers are not documented beyond that; confirm before publishing."
    source_url: https://huggingface.co/inclusionAI/Ming-3.0-tts-0.5B
    status: draft
```

Seeds make takes (take k is `seed + k`) and the same seed gives the same audio on this install. Ming tags inside `tts:`
text: `[Breathing]`, `[Sigh]`, `[Laughter]`, `[Uhm]`, ... (keep `text:` plain for the ASR gate). Write numbers as words.

**Hosted voice:**

```yaml
vo:
  engine: openrouter
  model: google/gemini-3.8-flash-tts      # default; elevenlabs/eleven-v4 for hero lines
  voice: Kore
  instructions: "A calm, warm narrator for a product film: unhurried, natural pauses at the full stops."
  asset: openrouter-voice                  # the licence entry below
  max_usd: 0.50                            # most one `promo vo` run may spend (also --max-usd)
  lines: [...]
```

```yaml
# assets.yaml
  - id: openrouter-voice
    kind: vo_model
    path: build/vo
    licence: "Hosted TTS via OpenRouter: the model provider's API terms (Google Gemini API / ElevenLabs); confirm they cover this use"
    source_url: https://openrouter.ai/collections/text-to-speech-models
    status: draft            # until the person confirms the provider's terms cover this use
```

Run it under the key: `commissionctl secret exec OPENROUTER_API_KEY -- promo -p <project> vo`. A missing key: request it
(`commissionctl secret request OPENROUTER_API_KEY --reason ...`), keep working on the rest, rerun once it is saved.
The whole run is priced from the live catalogue before the first call and refused over `max_usd` or the daily cap
(`PROMO_GEN_DAILY_USD`, default $2, shared with video jobs). The ledger (`promo gen spend`) keeps each take's estimate, and
its billed cost once OpenRouter reports it (settled at the end of the run). Takes are cached raw: a change to the trim,
the mix or a pick never pays again; a change to the text, voice, model or instructions does.

A host or a single line can use another voice: `voice: {engine: openrouter, model: elevenlabs/eleven-v4, voice: alice, asset: openrouter-voice}`.

## Direct the read

- **Gemini**: `instructions` carries the delivery (tone, pace, accent, who they are talking to). Never write directions into the
  line's `text`: they get spoken.
- **Eleven v4**: no `instructions`; put audio tags inside the `tts:` text, e.g. `tts: "[warmly] Small decisions, made fast. [pause] And always yours to override."`
  Keep `text:` as the plain script line, since the ASR gate checks `text`. SSML `<break>` is not supported on v4.
- **Pace** comes from punctuation: full stops and commas give pauses; split a long line in two rather than asking for speed.
- Numbers and names: write them as they should be said in `tts:` ("twenty-four seven", "J-E-V"), and add an `asr_aliases` entry
  when whisper hears them another way (`"4": "Four"`).

## Takes: let the person pick by ear

`takes: 3` on a line (or the vo block) makes three takes on mlx, openrouter or voicestudio (kokoro and say repeat themselves, so they refuse).
Each take is scored: whisper WER against the script, the tail energy, the spread of the pitch. A take that misreads its words or
ends mid-sound is **rejected**. The rest are not ranked: the line uses the first take that passed until the person picks.
Auditions: `build/vo/takes/<id>-<k>.wav`. `promo vo takes <id>` shows the table; `promo vo takes <id> --pick 2` writes `take: 2`
into promo.yaml and re-voices the line from the cache. Send the person the auditions; do not pick for them by score (the "best"
score drifts to the flattest read).

## Read the gates (`promo check`)

| Gate | Means | Fix |
|---|---|---|
| `vo-fit` FAIL | a line ends after the film's end: the mix cuts it off | move the line earlier, shorten it, or lengthen the shot |
| `vo-fit` WARN | a line runs > 0.25 s into the next one | move `at`, split the line, or pick a shorter take |
| `vo-clip` WARN | flat-topped samples: the take itself clipped | re-voice (another take, or another voice); nothing in post can un-clip it |
| `vo-tail` WARN | the take ends mid-sound (a cut word, or a `files` trim inside speech) | re-voice, or move the `trim: end` into a silence |
| `vo-script` FAIL | whisper heard other words | a mis-read take: re-voice or pick another take; an alias if only the spelling differs |

## Not yet built (draft tickets)

Per-line `direction:` translated per engine, a pronunciation lexicon, a VO polish chain (high-pass, de-ess, room tone),
speech-band ducking and a denoise for the local voice's noise floor, generated SFX (MOSS-SoundEffect, ElevenLabs SFX v2) and music
(ElevenLabs Music v2.5), an app-wide OpenRouter key in CommissionAI.
See `docs/audio-stack-2026-10.md`. Until then: SFX stay `promo sfx` / licensed files, music stays a licensed track (rule 4).
