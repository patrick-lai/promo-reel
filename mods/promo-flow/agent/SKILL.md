---
name: commissionai-mod-promo-flow
description: Publish the promo flow to the person's Stage pane (the promo-flow mod) and react to their clicks, including requests for scripts, plans and denser storyboards.
---
# promo-flow mod: publishing contract
The person sees and decides in the Stage pane; you do the work with `promo flow` (see the promo-reel skill, THE FLOW).

**Starting.** The pane must be open before you do anything else: `commissionctl mod activate promo-flow` (idempotent; it shows "Preparing…" and the chat card at once, and a first publish replaces it). If the person typed `/promo-flow <request>` or clearly asked for a produced video (promo, hero, demo, trailer), go ahead. Otherwise ask first with the ask
widget ("Use the promo flow for this?") and start only on yes. Then `promo flow init <name> --intent "<their words, exact>"` and publish. The project folder comes from the person's save location (`promo config output`, the folder button in the Stage), not from the repo you are working in; never `cd` into the repo to scaffold or write project files there.

**Publish after every change** (a stage advanced, a script/board/asset/draft/round was added, an approval landed):
1. `promo flow snapshot --out /tmp/promo-flow.json` (run it in the project; media become `{"$file": abs path}` objects)
2. `commissionctl mod publish promo-flow --file /tmp/promo-flow.json`
Never edit the JSON by hand. The first publish activates the mod in this thread. `summary` drives the chat card; `gate` is what the person is being asked.

**Their clicks arrive as chat messages** starting `[mod:promo-flow]`:
- `approved <gate>` or `picked scripts A B`: run the exact `promo flow approve ... --by "NAME"` the message names (NAME is the person), `promo flow advance`, then publish.
  If the approve command says the gate belongs to a later stage, `promo flow advance` first, then approve.
- `wants the real thing made, not placeholders: <what>`: run `promo flow make` (storyboard frames as real images, then a sample of every asset: concept still, short clip, audio excerpt), publish. If a sample fails (no source file for the music, no generator logged in), say exactly what is missing instead of publishing a placeholder.
- `chose where new videos are saved: <where>`: run the exact `promo config output "<where>"` the message names, then publish. It only changes where NEW videos go; never move the current one. If the command refuses (a drive that is not plugged in, a bad path), say why in one sentence in the chat and publish nothing new.
- `asked for changes on <stage>: <text>` (also "Style: ..." from the discover step): do the work, regenerate what changed, `promo flow board`, publish. Do not approve.
  A "Style: X. Reference: URL" message is `promo flow discover --style "X" --ref URL`; "Style: X. No reference link." is `promo flow discover --style "X" --no-refs`; then `promo flow advance`.
- `sent draft feedback (round n of 5): <text>`: `promo flow round start --feedback "<text verbatim>"`, council, one batch, one draft, `round close`, publish.

- `wants <item> uploaded to <destination>`: the person clicked Upload on a draft or the final. The Stage only offers it where their `twg` is signed in and the product is there (`promo flow share detect` refreshes that, e.g. after they sign in). Run the exact `promo flow share draft|final N --to artifacts|loom --by "NAME"` from the message, then publish. It is private to them; widen with `--access open` only when they ask.
  Names are canonical: draft N is `<project>_draft_N` (edited and shared again, Artifacts refreshes the same link; Loom cannot replace, so it adds a copy and keeps the old links in the record), a final is `<project>_final_vN` (each `final add` is the next version and is never overwritten). Tell them the link it printed. If it fails, say the reason it printed; an error that says to check Artifacts or Loom may have landed, so do not retry blindly.
  Never upload on your own (rule 5).
- `asked you to add to the plan (looking at the <tab> tab): <text>`: the person wants content in the Stage, in whatever size they ask for. Do it, then publish. Do not approve anything. With several picked stories, do it for each (document ids end in the story letter, e.g. `shotlist-a`) unless they named one. Pick the command from what they asked:
  - "the full script" / a longer script: `promo flow doc add full-script-a --kind script --title "Full script: <title>" --story A --file -` (pipe the text in; write a very long script in parts with `doc append` or `script append A --file -`). Any length is fine: the Stage paginates by `<!-- page: Title -->` markers, else by headings and length, with a contents list and find. Use markdown: headings, **Picture:** / **Voice:** / **Sound:** lines, tables, `- [ ]` checklists.
  - a shot list, edit plan, audio plan, capture checklist, claims, deliverables, schedule, treatment, director's notes: `promo flow doc new <kind> [--story A]` builds it from the real board and asset plan; then refine it (`doc add <kind> --force --file -`) so it is complete, not a template with holes.
  - "everything you need to direct / storyboard / workshop / edit": `promo flow plan pack` (the nine documents above, per story), then fill every `*( ... )*` hole and tell them what you assumed. `promo flow doc templates` lists the kinds; `doc list`, `doc rm ID` manage them.
  - changes to the storyboard itself: `promo flow story`, `scene add|set|rm|list` (no hand-edited JSON; `--redraw start|end|mid|all` re-makes a frame), then `promo flow frames` for new pictures. The storyboard approval goes stale on purpose: say so.
  - "more detail" / "frames every 5 seconds": `promo flow density --every 5 [--story A] [--scene 03]` (or `--clear`), then `promo flow frames` to draw them.
  Everything you write must be true to the footage (rule 3); put evidence in `proof` or the claims document. Add a `promo flow note` while a long document is being written.
- `wants storyboard frames <what> for story <S>`: `promo flow density --story S --every N` (N = 0 means `--clear`), then `promo flow frames`, publish. The Storyboard tab's cadence buttons send this; its Frames in time view shows every frame in time order.

**Before you ask for a decision**, `promo flow make`: the person decides by looking and listening, so every frame must be an image and every asset needs its real file or a sample. A text slate or an empty MOCK tile is not a preview, and the Approve button stays disabled while any exist.

**While you work (anything over ~2 minutes: captures, renders, voices, builds).** The person is waiting and cannot see your tools. Every ~3 minutes, and at each new sub-step:
`promo flow note "Rendering screenshots for scene 4" --kind render` (kinds: capture | render | voice | music | check | plan | other; add `--done` when that sub-step is finished), then publish.
Write it as plain words about the video ("Taking snapshots of the real app", "Designing the voice for the opening line"), never a command or a path. `promo flow make` notes itself.
The Stage shows the latest note, how long ago it was, and one dot per past note; the chat card status reads "Now: <note>".

**Never approve yourself** (an agent name is refused). Never send an action for them. If `commissionctl mod status promo-flow` shows nothing new, wait.
A thread that is archived shows the last state read only; nothing more to do.

At Keyframes, real recordings and screenshots are the person's to capture (rule 1: real footage only). While any are still `mock` or `todo`, the Stage shows "Your turn: N recordings to capture" and opens on the Assets tab with the `how` text as the shot brief. Do not advance until the person has sent the files; register each with `promo flow asset add --force --source real --path FILE --how "..."`.
