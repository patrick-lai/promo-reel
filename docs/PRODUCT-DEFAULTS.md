# Promo-reel product defaults (from lessons 1–6)

A thin prompt still has to become a full project. Run:

```
promo plan <name> --prompt "<their words, verbatim>"
```

That writes every fill below into `promo.yaml` under `plan:` (and sets `style.preset` plus `style.version: 2` when the file has no locked version). Edit those fills. Then:

```
promo preview -p <project>/promo.yaml          # 540p + stills only
promo review status -p <project>/promo.yaml    # Marketing / Zen / Director slots in reviews/round-N.md
promo build --final -p <project>/promo.yaml    # above 540p; refuses while a beat is empty or a sign-off is missing
```

Three review rounds, then hand the cut to Patrick. Source lessons: [hook](lessons/01-hook.md), [one idea](lessons/02-one-idea.md), [five beats](lessons/03-five-beats.md), [length](lessons/04-length.md), [shot list](lessons/05-shot-list.md), [screen recording](lessons/06-screen-recording.md).

Patrick's ask (12 Oct 2026): thin user prompts must still produce a full project. The agent using promo-reel fills gaps from these defaults. Numbers that came from the reference study are marked in the lessons.

## Planner contract

When the prompt is under-specified, fill in this order and write every fill into `promo.yaml` (or the project file) so the user can see and edit it:

1. **One idea** (lesson 2) — ≤10 words. Everything else is evidence for this sentence.
2. **Format → preset** — `hero` | `anime-opening` | `livestream` (talk show) | `vertical-short` (locked `@1`, 9:16). Pick from prompt keywords; default `hero`. `vertical-short` does not opt into `@2`.
3. **Five beats** (lesson 3) — five single lines: hook, problem, demo, payoff, CTA. Refuse `--final` if any beat is empty.
4. **Length** (lesson 4) — job decides length, not how much footage you have:
   - hero master: **60 s**
   - feed / X / Shorts cut: **~20 s** (hook + demo + payoff + ask)
   - single-feature clip: **~30 s**
   - `vertical-short@1`: the shell's own band inside about **6–20 s** (UI zoom defaults to 11 s)
   Plan all cuts in the shot list before capture.
5. **Shot list** (lesson 5) — one row per shot, six columns:
   - beat (hook | problem | demo | payoff | ask)
   - what's on screen
   - one thing the viewer must notice
   - on-screen text
   - length in seconds
   - app state needed
   Every beat needs ≥1 row on a hero, anime, or livestream plan. A `vertical-short` plan keeps the five beat lines and uses the format shell instead (one row, or two for before/after). Cap density with the preset cut-rate curve.
6. **Capture defaults** (lesson 6) — apply before `footage add`:
   - capture at **2× deliverable** (4K for 1080p)
   - clean demo state (e.g. `?demo=promo`), fixed window, no debug chrome
   - cursor only when the click is the point; pause before click; no circling
   - one push-in per shot, landed on the "notice" target
   - **never paint out UI** — reshoot from a clean moment

## Hook defaults (lesson 1)

- On-screen promise a stranger understands with sound off by **~0.5 s**
- Logo / wordmark may wait until **~8 s**
- Prefer opening on the payoff evidence over a brand label
- Opening must match the title and thumbnail promise

## Structure defaults (lesson 3)

Rough 60 s hero slots (from style guide / reference study):

| Beat | Window |
|---|---|
| Hook | 0–4 s |
| Problem + first UI | 4–20 s |
| Features as evidence | 20–42 s |
| Montage peak | 42–52 s |
| End card | from 52 s, hold ≥6 s |

- Payoff is the **last spoken line** (nothing between payoff and end card)
- CTA needs one verb + one real destination (waitlist / download / repo). If none exists yet, end card may only name the product — do not invent a URL
- Problem line must be true viewer pain (not a feature list). An option for one product (not a default): evening spent babysitting agents → sets up a morning-after payoff. Do not copy that line into a project the prompt did not ask for.

## Vertical short (`vertical-short@1`)

Locked at version 1. There is no `@2`. `promo plan` with this preset writes `version: 1` and a **format shell** (timing, picture, one caption, logo rule). It does not write a content batch, and it does not expand a 60 s hero into ~28 shots.

Audience: builders and engineers who care about UI craft. Not generic AI news. Visual language: Apple-clean motion, intentional UI zooms, quiet pacing. Captions only, so the cut reads with the sound off. One idea. Aspect **9:16** (1080×1920 at the 1080 deliverable; capture at 2×, 2160×3840).

Outer length is about **6–20 s**. The shell in use has its own band. Logo or wordmark is omitted, or occupies the **last 1 s at most**.

| Shell | Rank | Length | Picture |
|---|---|---|---|
| UI zoom | primary, the plan default | 10–12 s (default 11 s) | Real screen capture. One deliberate zoom on one control. One caption. |
| Craft loop | secondary | 8–15 s (default 12 s) | A UI-detail loop, or licensed generative motion, teaching one interaction. Not a product tour. |
| Before/after polish | tertiary | 12 s | Two frames of the same UI. One craft change. A diagram is allowed. |

Quote card and talking head are parked. They are not planned.

Opus/Claude-style generative motion is an optional design source when it is licensed and on-brief. It is never required, it does not replace real app footage, and it never paints out real UI. Capture defaults still apply: 2× deliverable, clean demo state, intentional cursor, one zoom target. Review rounds are unchanged (540p preview, feedback, gated `--final`, max 3).

The five beat lines are still filled, so an empty beat still refuses `--final`. The shot list is the shell (one row for UI zoom and craft loop, two for before/after), not a cut-rate expansion.

## Pacing targets from reference study (for presets `@2`)

Locked v1 presets stay as they are. `style.version: 2` or `style.preset: hero@2` (same for `anime-opening` and `livestream`) opts into these targets.

**Hero** (Lovable / Cursor / Devin):
- ~0.35–0.45 cuts/s overall; montage peak ~0.6–0.8
- Text by 0.5 s; logo ~8 s
- Hero words ~8–15% of frame height; cards hold ~2–3 s; ≤5 captions
- End card ≥6 s

**Anime opening**:
- Cut-rate **curve**, not a flat number: ~0.3 early → peak ~1.0 between **45–67%** of runtime
- Median shot ~1.2–1.5 s; allow **one** planned hold 7–12 s (mark `hold: planned`, exempt from over-long-hold WARN; max one per video)
- Loudness target for web: **−14 LUFS** (refs were louder; we don't match that)

**Talk show / livestream**:
- Layout change every **5–7 s**
- WARN if a speaker turn > ~12 s
- ~165–180 wpm; ~4–5 jokes per 100 s; planned bit in first 15 s + end callback reusing exact words
- Captions bottom-centre ~3–4% frame height, 2.0–4.5 s per line
- Demo intro cue → demo on screen within ~1 s

**Beat sync:** snap cuts to **musical phrases** by default; strict per-beat lock is optional (`pacing.strict_beat: true`).

## Review rounds

1. `promo preview` → stills + contact sheets + **540p** only
2. One feedback file per round (`reviews/round-N.md`); Marketing / Zen / Director each one list + `signed-off:`
3. `promo build --final` refuses without all three sign-offs; anything >540p requires `--final`
4. Max **3 rounds**, then hand to Patrick
5. Shot QA at `footage add`: 18 px named text, mostly-empty frame, caption≠badge, edge-clipped text → WARN/FAIL before edit

Projects that never went through `promo plan` (no `plan.review.required`) keep the previous build behaviour.

## Spine options (not decisions)

Examples a human might choose for one product. The planner must not write these into a project unless the prompt already says them.

- One idea a team has used: a night-to-morning payoff about merged work.
- An anime spine that is already a clean pair of title cards.
- A talk-show cold open that moves the strongest line to 0 s.

## Do not invent

Features, counts, metrics, testimonials, URLs, or app UI. Confirm claims with the product owner before any of them go on screen. Licences required for music, fonts, voices, Live2D models.
