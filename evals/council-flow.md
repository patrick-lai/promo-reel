# Council for the gated flow (`promo flow`)

Same rules as `council.md` (reviewers never edit, the editor merges, one batch per round, the user's verbatim words and the references outrank
the editor's summary). The flow asks for the council at four points. Every council file you record starts with the `intent-check:` line of
lens 0 and says per lens what it found and what the editor changed (>= 200 chars or `promo flow council` refuses it).

| point | lenses (parallel sub-agents, fresh each time) | output |
|---|---|---|
| **Scripts** (1-2 spar rounds, before the person sees them) | **0 Intent & Reference** (does each script answer the person's words and their references? which would they say yes to?), **Story** (hook, the one idea, escalation, payoff, is every claim provable on screen), **Feasibility** (what must be captured / generated, cost, risk, rule clashes with AGENTS.md), **Outsider** (cold read of the loglines only: would I watch?) | round 1: each lens critiques all scripts, ranks them. Editor rewrites. round 2 (spar): lenses read each other's critiques, argue, re-rank. Record `promo flow council scripts --file F`. Offer the person the top 2-3 with the council's one-line verdicts. |
| **Storyboard** | 0 Intent, **Continuity** (END frame of scene n flows into START frame of n+1: set, wardrobe, light, direction), **Pacing** (beats vs the music grid, scene lengths), **Proof** (each caption/VO line has evidence on the frame it sits on) | per-scene fixes; record with `promo flow council storyboard` |
| **Assets** | 0 Intent, **Truth & licence** (UI is real, generated only where allowed, licences + source URLs, no personal data), **Consistency** (voices, faces, set, grade across assets), **Replace plan** (every MOCK has a way to become real) | record with `promo flow council assets` |
| **Each review round (max 5 per cycle)** | **0 Intent & Reference (mandatory)**, **Research** (see below), **Reference match** (numbers: shot length, cut rate, LUFS vs the references), **Legibility & polish** (full-res stills), **Story & truth** | `intent-check:` line + changes; `promo flow round close --council F --research R` |

## Research lens (every review round)
Do **web research** on the topic of this video and write `research.md` with >= 3 distinct source URLs (`promo flow round close` counts them):
1. 2-3 *examples of good videos* in this genre or about this subject (watch them: `promo watch <url>`; sheets + transcript + numbers, not just the title).
2. What they do that this draft does not, as concrete, copyable techniques (shot lengths, hook, sound design, pacing, framing, on-screen text).
3. Facts about the topic worth getting right (terminology, how the product is really used, claims people actually care about).
Each finding is a URL + one or two lines. The editor turns accepted findings into spec changes in the same batch; rejected ones get a one-line reason.
Research never overrides the person's words: if a technique clashes with their intent, it is raised to them as a question, not applied.

## Round protocol (hill climb, max 5)
1. The person's feedback, verbatim: `promo flow round start --feedback "<their words>"`. Re-read `promo brief show` first.
2. Run all lenses in one message (lens 0 + research always). Merge, dedupe, sort by severity x 1/effort, apply the accepted changes in ONE batch.
3. Build ONE draft, `promo flow draft add`, `promo compare-ref` against the references, then `promo flow round close`.
4. Show the draft and the change list; ask: approve, or feedback (next round). Rounds are not for you to burn: stop early on the person's yes; at the cap,
   put it to them (approve / restate the direction).
After the final, new feedback is `promo flow revise --feedback "..."` and the same council protocol runs again (a new cycle, 5 more rounds).
