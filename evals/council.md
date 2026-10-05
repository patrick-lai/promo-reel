# Critique council: hill-climbing a promo cheaply

Rubric: `evals/rubric.yaml` v2 (9 scores + truth; pass = truth PASS, **intent >= 4 and reference >= 4 (hard gates, never averaged away)**, none < 3,
mean >= 4.2). The yardsticks are the user's own words and the references themselves, from `projects/<p>/brief.yaml`:
`intent_verbatim`, `must_have` / `must_not`, and `reference/<id>/DOSSIER.md` + transcript + audio.

**Never let the agent's own style summary replace the reference.** A preset, a style note or a "look" the editor wrote is a hypothesis about
the reference, not the reference. Every lens that judges fidelity reads the user's words and the reference's own artefacts (transcript, audio
numbers, sheets, the dossier written from them) and the `promo compare-ref` output, not the editor's retelling. A film with people, dialogue
and sound design is judged on its story, performance, voice, sound and pacing, not only on how it looks.

## Why a council
One reviewer finds the problems it is tuned to see. Four reviewers with different lenses find different problems, and they all read
the SAME cheap artefacts, so a round costs one render. Reviewers never edit; the editor (main agent) merges and applies.

## Lenses (one sub-agent each, run in parallel, fresh context each round)
| lens | reads | scores / finds |
|---|---|---|
| **0. Intent & Reference (MANDATORY, runs first)** | `intent_verbatim`, `must_have` / `must_not`, decided `conflicts`, every reference `DOSSIER.md` + `transcript.json` + audio metrics (`WATCH.md`), `promo compare-ref` output (sheet rows + speech / LUFS / tempo / cut-rate table), the draft (`promo watch` of it incl. ITS transcript and audio) | `intent` and `reference` scores, **would they say yes?** with quoted evidence, narrative / people / dialogue / sound / pacing gaps. Must READ the transcript comparison and listen to / read the audio numbers, not only look at stills. |
| **Reference match** | project `promo watch` output next to the reference's `promo watch` output (sheets, cut-rate curve, shot lengths, loudness); numbers only, lens 0 owns fidelity of story / people / sound | style fidelity, pacing, hook; numeric gaps ("ref median shot 1.75 s, ours 3.2 s") |
| **Legibility and polish** | full-res stills per shot + per card (critique pack), `promo check` WARNs | legibility, polish: soft upscales, clipped text, empty frames, jitter, banding |
| **Story and truth** | shot list, copy, footage manifest, stills | story, truth: every word true of the frame it sits on; wrong scenes; claim without evidence |
| **Taste (outsider)** | ONLY the contact sheet and the one-sentence brief | hook, calm, "would I watch to the end?"; cold read, no spec access |

## Round protocol (hill climb)
0. **Start every round by re-reading the brief verbatim**: `promo brief show --project projects/<p>` (the editor and every lens; paste the
   intent into each lens prompt unedited). If `promo refs check` or `promo brief check` FAILs, fix that before rendering anything.
1. Build a **draft once** (`promo preview`, 540p; full-res only for the final). Make a critique pack and a `promo watch` of the draft.
2. Spawn the lenses in one message (lens 0 included, always). Each returns JSON: `{scores: {intent, reference, hook..polish}, truth, changes: [{id, shot, severity 1-3, what, fix, effort S|M|L}]}` (max 12 changes, no praise).
3. Editor merges: dedupe by (shot, what), sort by severity x (1/effort), **apply every accepted change in one batch** (spec edits, new takes requested, copy), reject with a one-line reason the rest.
4. Re-render once. Score again with the same four lenses (new instances; they get last round's change list so they check it landed).
5. Accept the round only if the mean rubric score rises by >= 0.2 or a lens-flagged FAIL is cleared and nothing drops by > 0.3 (else revert to the previous spec: `git checkout` of the project dir). Plateau (two rounds < 0.2) or round 3 -> stop and hand to the human.
6. Keep `projects/<p>/rounds/<n>/{scores.json,changes.md,decision.md}`. **`decision.md` must contain the Intent & Reference lens's verdict as one line**
   (printed by `promo brief show`; `promo check` gate `intent-review` FAILs when the newest round lacks it, quotes another intent hash, or says NO):

   `intent-check: intent_sha=<12 hex of intent_verbatim> verdict=<YES|PARTIAL|NO> intent=<1-5> reference=<1-5> lens=intent-reference`

   followed by the lens's quoted evidence. The editor never writes this line itself and never accepts a round whose verdict is not YES.
   A round does not "rise" while `intent` or `reference` is under 4, whatever the mean says.

## Cost rules
- Never render between feedback and the batch. Never one-fix-per-render.
- Reviewers read stills and sheets, not the mp4, unless the lens is pacing/motion (then the `promo watch` metrics + sheet, not frames).
  Exception: lens 0 must read the transcript + audio comparison (text and numbers, cheap) and, for a reference with speech, the draft's own transcript.
- Cheapest model that can see images for lenses 2-4; strongest for lens 0 and the Reference-match lens.
