---
name: commissionai-mod-promo-flow
description: Publish the promo flow to the person's Stage pane (the promo-flow mod) and react to their clicks.
---
# promo-flow mod: publishing contract
The person sees and decides in the Stage pane; you do the work with `promo flow` (see the promo-reel skill, THE FLOW).

**Starting.** If the person typed `/promo-flow <request>` or clearly asked for a produced video (promo, hero, demo, trailer), go ahead. Otherwise ask first with the ask
widget ("Use the promo flow for this?") and start only on yes. Then `promo flow init <name> --intent "<their words, exact>"` and publish.

**Publish after every change** (a stage advanced, a script/board/asset/draft/round was added, an approval landed):
1. `promo flow snapshot --out /tmp/promo-flow.json` (run it in the project; media become `{"$file": abs path}` objects)
2. `commissionctl mod publish promo-flow --file /tmp/promo-flow.json`
Never edit the JSON by hand. The first publish activates the mod in this thread. `summary` drives the chat card; `gate` is what the person is being asked.

**Their clicks arrive as chat messages** starting `[mod:promo-flow]`:
- `approved <gate>` or `picked scripts A B`: run the exact `promo flow approve ... --by "NAME"` the message names (NAME is the person), `promo flow advance`, then publish.
  If the approve command says the gate belongs to a later stage, `promo flow advance` first, then approve.
- `wants the real thing made, not placeholders: <what>`: run `promo flow make` (storyboard frames as real images, then a sample of every asset: concept still, short clip, audio excerpt), publish. If a sample fails (no source file for the music, no generator logged in), say exactly what is missing instead of publishing a placeholder.
- `asked for changes on <stage>: <text>` (also "Style: ..." from the discover step): do the work, regenerate what changed, `promo flow board`, publish. Do not approve.
  A "Style: X. Reference: URL" message is `promo flow discover --style "X" --ref URL`; "Style: X. No reference link." is `promo flow discover --style "X" --no-refs`; then `promo flow advance`.
- `sent draft feedback (round n of 5): <text>`: `promo flow round start --feedback "<text verbatim>"`, council, one batch, one draft, `round close`, publish.

**Before you ask for a decision**, `promo flow make`: the person decides by looking and listening, so every frame must be an image and every asset needs its real file or a sample. A text slate or an empty MOCK tile is not a preview, and the Approve button stays disabled while any exist.

**Never approve yourself** (an agent name is refused). Never send an action for them. If `commissionctl mod status promo-flow` shows nothing new, wait.
A thread that is archived shows the last state read only; nothing more to do.

At Keyframes, real recordings and screenshots are the person's to capture (rule 1: real footage only). While any are still `mock` or `todo`, the Stage shows "Your turn: N recordings to capture" and opens on the Assets tab with the `how` text as the shot brief. Do not advance until the person has sent the files; register each with `promo flow asset add --force --source real --path FILE --how "..."`.
