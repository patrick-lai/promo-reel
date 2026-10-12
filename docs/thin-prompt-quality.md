# Thin-prompt quality: from two lines and a few stills to a designed promo

Craft only. The reference promos behind this (a kinetic launch trailer and a quiet conceptual-minimalist film) are studied for
structure, rhythm, type and framing. Nothing of their art style, assets or words is used, and nothing here changes the locked
commission-ai cuts.

## Diagnosis

A thin prompt is two or three lines, a couple of stills and a rough length (`60s promo for my AI coding crew. Go to bed. Wake up to
merged PRs.`). Before this change `promo plan` filled the structure (idea, five beats, length, shot list, capture defaults) and then
stopped. A build from that plan came out as a flat stitch of screen recordings:

| What reads as premium in the references | What a thin prompt produced |
|---|---|
| Real product shown as floating rounded panels over designed plates | Raw fullscreen desktop, edge to edge |
| Type that carries the beat and reads with the sound off | A tiny caption pill, or nothing |
| A camera that does one or two things on purpose | The same slow push on every shot |
| One idea per beat, a held end card with a verb and a place | Five beats with the same weight, an end card with nothing on it |
| One look across every cut (grade, plates) | Whatever each recording looked like |
| Pacing with a shape (hold, build, burst or breathe) | An even cut rate |

The fix is a **designed composition plan** (`plan.designed`) written by `promo plan` when the prompt is thin and stills are
supplied (or with `--designed`). It decides the craft the person did not specify and refuses to decide anything else.

## What the person supplies, what the system invents

| The person supplies (thin prompt) | The system invents (craft, editable in `plan.designed`) |
|---|---|
| Feature outline (a line or two) | Backdrop plates (non-UI, `ui: false`) and their one shared look |
| Raw UI stills or clips | Which still floats, which sits in a device, which is cropped toward a corner when re-used |
| Must-keep claims, each with what proves it | Type curves: snap, cascade, pop, slide, scale; sizes; brackets, anchors, an inline thumb |
| The end-card words (or a team default passed with `--default`) | Beat sync (half-beat grid), the camera, the montage burst or the held payoff |
| Their own mood words (`night`, `calm`, `punchy`) | The dialect (ethereal unless the words say kinetic) |

What it never invents: product claims, counts, metrics, URLs, app UI, features. See "No invention" below.

## Structure (the reference spine, scaled to your length)

The 90 s reference runs: 0-7 s action hook, 8-14 s title and value, 15-36 s feature pairs, 37-43 s social proof, 44-63 s depth and
niche, 64-79 s recap montage, 80-90 s CTA. `plan.designed.spine` scales those proportions to the master and tags each segment with
the five-beat name it serves (`hook`, `problem`, `demo`, `payoff`, `ask`). `plan.designed.length_band` picks the class:

- short (< 25 s): hook, title, feature pairs, CTA. No montage.
- standard (25-75 s): all five beats.
- long (> 75 s): adds the social-proof and depth runs.

## The framing hierarchy (per shot: `framing`)

1. **floating** (primary): a rounded panel with a drop shadow over a plate. Real pixels, never graded, never edited.
2. **fullscreen**: peak action only, real footage only (a still is never fullscreen), at most a quarter of the UI shots. Never in ethereal.
3. **device**: context (a phone, a terminal). A bezel drawn outside the UI pixels, nothing drawn on them. Portrait stills get a portrait panel.
4. **plate**: kinetic type over a generated plate, no UI (the hook, the end card).

A still shown again is cropped toward a different corner (`motion.focus`), a placeholder the person aims with `promo peek`.

## The two dialects

A thin prompt picks one (`plan.designed.dialect`; `promo/designed.py` `DIALECTS`). Selection, in order: `--dialect`, a co-spec
`dialect` answer, a `dialect:` line in the prompt, then the prompt's own words. Kinetic words only (`kinetic`, `punchy`, `launch
trailer`, `hype`, `fast cuts`, `big type` ...) pick kinetic; ethereal words only (`calm`, `airy`, `minimal`, `conceptual`, `pastel`,
`apple`, `opus`, `lo-fi` ...) pick ethereal; both is ambiguous, defaults to ethereal and costs one co-spec question; **no style words at
all is ethereal** (Patrick's Opus / Apple taste).

| | ethereal (default) | kinetic |
|---|---|---|
| Pace | Breathable holds, about 5 s a shot, 0.1-0.25 cuts/s, a 6 s end card. Micro snaps (type and selection boxes appear in one frame, zero blur). No recap burst: the payoff holds | Denser: 0.3-0.6 cuts/s. Words pop, slide and scale in on the half-beat. The payoff recap accelerates from 2.0 s to 0.75 s shots |
| Camera | Locked, or a slow linear push-in (a few percent). No whip pan, no shake, no heavy motion blur (gate `designed-camera` FAILs them) | Slow push-ins with continuous micro-animation; limits are looser (WARN) |
| Type | Light / Medium sans, sentence case, ink colour, no outline, no shadow, 4-9 % of the frame height, up to 8 words. Typography as UI: `[ ]` brackets, selection anchors, an inline thumb of a real still | Bold blocky sans, white with a dark outline and shadow, 8-15 % of the frame height, up to 4 words, the VO reads it nearly verbatim |
| UI | Small real panels floating in air, no fullscreen chrome (gate `designed-framing` FAILs it). Abstraction is done in type, never by drawing UI | Floating panels over plates, fullscreen only for peak action with real footage |
| Plates | Surreal pastel: halftone sky, empty pastel room, a gradient field. 6 s plates | Graded cinematic backdrops, 4 s plates |
| Grade | Soft pastels, airy, low contrast, light grain, no vignette, no glow spill | Warm low-key (the preset look) |
| Sound | Music-led, no VO. Ambient / lo-fi bed, soft ASMR clicks on snaps, a soft whoosh on a resolve. Quiet until the end card | VO locked to the cards, music on the beat grid |
| Transitions | Mosaic resolve on the backdrop of the first shot of each beat, a cascade for the hook and end-card words, hard cuts otherwise | Hard cuts on the half-beat; the accelerating montage |

The renderer pieces (`promo/shots/cinema.py`, documented in its docstring): `kinetic_copy` items with `anim: snap | cascade | pop |
slide | scale`, `weight`, `outline` / `shadow` flags, `brackets`, `anchors`, `thumb`; `resolve: {kind: mosaic}` (never the UI panel);
`look.plate_fill` and `look.backdrop.fill` (a pastel placeholder world until a plate is registered); `panel.aspect` for device panels.
Images are sources (`render.probe` / `Source` treat a still as a never-ending clip).

## Co-spec: at most three questions

A thin prompt is drafted without asking (draft, then iterate). `promo cospec` lists the few decisions that would cost a full
re-render when guessed wrong, at most three, in this priority, skipping any the prompt already answers:

1. `dialect`, only when the words point both ways.
2. `cta`: the end card, GitHub vs a landing page vs name only. A URL is never guessed.
3. `promise`: the ONE line the cut is built on, when the prompt holds several candidates.
4. `audience`, when the prompt does not say.
5. then `world`, `features`, `must_keep`, `still_roles` (only reached when the first ones are answered).

Each question carries `saves:` (what it avoids re-rendering) and what happens if it stays open. Answers land under
`plan.cospec.answers` and trigger a re-plan (`promo cospec NAME --answer cta="..." --answer promise="..."`).

**Team default CTA.** `promo plan ... --default cta="Your AI dev crew, on your Mac."` fills the end card only when nothing else does
(order: a co-spec answer, a `cta:` line, then the default). It is stored under `plan.cospec.defaults`, counts as the person's own
words for grounding, is flagged `needs: confirm` for the product owner, and is never applied to a project it was not passed for.

## No invention (the refusal)

- Every word on a card is a contiguous run of words from the prompt, a co-spec answer or a passed team default. `promo plan` refuses
  to write a plan otherwise; `promo designed apply` re-checks; `promo check` repeats it as the `designed-grounded` gate.
- A beat with no words of the person's gets a `needs-copy` placeholder (ethereal leaves the problem and demo beats quiet instead).
- URLs and numbers nobody gave are refused. A `must_keep` claim without evidence never becomes a card. A `must_not` phrase blocks cards.
- Plates carry `No text, no logos, no screens, no devices, no people, no user interface.`, are `ui: false` and carry no digits or URLs.
  They are generated only through the existing `promo gen` carve-out and sit only on shots marked `ui: false`.
- Real product UI comes only from the stills and clips the person supplied, registered in the footage manifest as "supplied by the
  person" (confirm it is the real UI). Nothing is ever drawn on or generated for the UI.

### Open conflict for Patrick: abstracted UI vs rule 1

The ethereal reference shows *abstracted* conceptual UI (a lone search bar, stylized loading nodes). Drawing or generating product UI
breaks AGENTS.md rules 1 and 2, so the plan does not. It abstracts with type (brackets, anchors, an inline thumb of a real still),
with small panels of the real stills floating in air, and with tight crops. The question is recorded in
`plan.designed.conflicts` (`abstracted-ui-vs-rule-1`, decision `pending`); record the answer with `promo brief conflict` before a final.

## Using it

```bash
promo plan NAME --prompt "60s promo for my AI coding crew. Go to bed. Wake up to merged PRs." \
    --stills a.png b.png c.png [--dialect ethereal|kinetic] [--default cta="..."] [--answer key=value]
promo cospec NAME                     # at most three optional questions; --answer KEY=VALUE re-plans
promo designed show NAME              # the plan: framing per shot, cards, plates, needs, conflicts
promo designed apply NAME             # writes cinema shots into promo.yaml (stills registered in the footage manifest)
promo -p NAME --scale 0.5 build --look   # quick-look stills strip in about 10 s, no music needed
promo -p NAME strip --out strip.png
promo -p NAME preview                 # 540p draft + stills + contact sheet (needs a music asset, see the runbook)
promo -p NAME check                   # includes designed-grounded / -kinetic / -clear / -framing / -camera / -pace
promo designed eval                   # thin prompt -> plan assertions (evals/thin-prompt-designed.yaml)
```

Plates: `promo gen plan` lists the plate prompts (also written as `broll:` between `# promo:designed` markers); make each, then
`promo gen register <file> --id plate-a ... --shots 02 03`. Re-run `promo designed apply` and the shots pick the plates up. Until a
plate exists the preview uses a designed placeholder world (ethereal: a pastel gradient; kinetic: the dim blurred copy).

## RUNBOOK: thin-prompt e2e on the box (commission-ai)

Stills live on the shared box under `/workspace/videos/commission-ai-promo/footage/` (not in git). Recipe, also in
`docs/examples/commission-ai-thin-prompt/run.sh`:

```bash
F=/workspace/videos/commission-ai-promo/footage
promo plan commission-thin \
  --prompt "60s promo for my AI coding crew. Go to bed. Wake up to merged PRs." \
  --stills $F/shot-01-v1-poster.png $F/shot-06-still-board.png $F/shot-12-ask-the-reviewer-v1-poster.png \
  --dialect ethereal --default cta="Your AI dev crew, on your Mac."
promo cospec commission-thin          # <= 3 questions: end card (GitHub vs landing), the one promise, the audience
promo cospec commission-thin --answer cta="..." --answer audience="..."   # optional; re-plans
promo designed apply commission-thin
promo -p commission-thin --scale 0.5 build --look && promo -p commission-thin strip --out strip.png   # post this first
promo gen plan -p commission-thin          # plates: make them, `promo gen register`, re-run `designed apply`
promo -p commission-thin preview           # 540p draft; needs a music asset in assets.yaml (below)
promo -p commission-thin check
```

1. **Music.** A draft needs `media/music/track.mp3`: a licensed ambient / lo-fi bed with `licence`, `source_url` (and `fetch_url` +
   `sha256` for `promo fetch`) in `assets.yaml`. For an internal test only, `test_only: true` (burned-in TEST watermark, refused by
   `flow share` / `flow final add`). Nothing is bundled.
2. **Review rounds** stay 540p first: `promo review round` writes `reviews/round-N.md` (Marketing / Zen / Director), at most three, then
   Patrick. Anything above 540p needs `promo build --final` after sign-off. Director owns review, Reel merges.
3. **Captions** are in craft-note form: the person's words only (`Go to bed` / `Wake up to merged PRs` / the end card), no invented
   counts or badges. The end card is `Your AI dev crew, on your Mac.` unless the person named another ask.
4. Confirm the team-default CTA with the product owner (`needs: confirm`), and decide the abstracted-UI conflict above.
5. Nothing is uploaded or posted: a human approves before anything is published.

Verified here with synthetic placeholder stills of the same names: plan, `designed apply`, quick look (about 7 s), a full 540p draft
(about 3 min on this box) and `promo check` (every `designed-*` gate PASS). Run it with the real stills for a real draft.

## Tests and evals

- `tests/test_designed.py`: plan shape, floating primary, fullscreen only with real footage, montage, cards, plates, `broll:`, no
  invention, must_not and evidence, co-spec and its CLI, apply and gates, the kinetic renderer, stills as sources.
- `tests/test_dialects.py`: dialect selection (words, flag, label, answer, ambiguous), ethereal defaults from a thin prompt, kinetic
  differences, the team-default CTA, the commission-ai recipe (three questions, three cards), compiled ethereal shots, dialect gates,
  and the ethereal renderer moves (snap, cascade, brackets, anchors, thumb, mosaic).
- `promo designed eval` (`evals/thin-prompt-designed.yaml`): four thin prompts through `promo plan`, asserted with no model in the
  loop. `evals/thin-prompt-designed.md` is the Sonnet judge rubric for what an assertion cannot score.
