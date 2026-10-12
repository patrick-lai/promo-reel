# Thin-prompt designed plan: judge rubric (Sonnet)

`promo designed eval` asserts the mechanical part with no model in the loop (`evals/thin-prompt-designed.yaml`): designed fields
present, floating primary, fullscreen earned, five beats, seconds add up, at most three co-spec questions, the expected dialect,
only the person's words on cards, no invented claims / numbers / URLs, plates guarded and `ui: false`, the compiled shots load and
the `designed-*` gates do not FAIL.

A model judge scores what an assertion cannot. Give it the prompt, the stills list, `promo designed show --json` and the quick-look
strip (`promo strip`). Score 1-5, pass = no truth failure, nothing under 3, average >= 4.

| Lens | Question |
|---|---|
| Truth (pass / fail) | Is every word on screen, in a plate prompt and in `needs` the person's own (prompt, co-spec answer, passed default)? Any invented feature, count, badge, URL, testimonial, UI? Any plate that could read as the product? |
| Dialect fit | Does the plan read as the dialect it declares? Ethereal: air, long holds, sparse type as UI, small floating panels, no fullscreen chrome, no whip / shake / blur, music-led. Kinetic: dense cuts, big type locked to the VO, floating panels, an accelerating recap |
| Hierarchy | Are floating panels primary, device only for context, fullscreen only for peak action with real footage? |
| Spine | One idea per beat, a hook that lands the promise early, a held end card with a verb and a place |
| Co-spec | At most three questions, each one that saves a full re-render, none answerable from the prompt |
| Honesty about gaps | Does it list what it is waiting on (copy, plates, evidence, audio, the CTA confirm) instead of filling it? Is the abstracted-UI vs rule 1 conflict put to the person? |

The judge never rewrites the plan; it lists defects, and each defect becomes either a code fix with a test or a note for the person.
