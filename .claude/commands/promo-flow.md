---
description: Run the gated promo flow (scripts -> storyboard -> assets -> drafts -> council rounds) with the person in the loop
argument-hint: <what the video is for, in the person's own words> | status
---

Run the promo-reel gated flow for: $ARGUMENTS

1. If a flow exists (`promo projects`, `promo flow status`), resume it; else `promo flow init <name> --intent "<their words, exact>"`.
2. Loop: run `promo flow status --json`. Do the work in `next`; use `needs` for what to generate or capture; when `ask` is set, put it to the person with
   AskUserQuestion (never answer a gate yourself: `approve ... --by <their name>` only after they said yes in chat).
3. Show, don't describe: after storyboard / assets / drafts changes run `promo flow board`, then show the page (publish it as an Artifact, or show the
   widget) and the draft mp4 (SendUserFile). Use the council in `evals/council-flow.md` at every point it lists.
4. Never skip a stage or fake a gate; `promo flow advance` refuses. Full rules: `skills/promo-reel/SKILL.md` (THE FLOW) and AGENTS.md.
