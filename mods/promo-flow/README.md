# promo-flow mod

**Host-agnostic by design:** this mod speaks the mod protocol (v2: mounted in the host's page, inside a shadow root) described in the host's own docs (`docs/mods.md` of the host), and `mod-dev/` plays a minimal host for it. CommissionAI was the first host.

The promo flow (`promo flow ...`, see `promo/flow.py`) as a mod: a web app that the host mounts into its own page and shows in its Stage (right pane, about 380 to 900 px wide, full height),
with a short summary card in the chat. The agent publishes state; the person's clicks come back to the agent as `[mod:promo-flow] ...` messages. In CommissionAI the agent publishes with `commissionctl mod publish promo-flow --file F`.

    mod.json        manifest: slash command, activation message, actions approve | pick | changes | feedback | generate | share, agent skill
    index.html      shell (header + stepper, tabs, content, sticky gate bar, lightbox)
    app.js          registers window.commissionMods["promo-flow"] = mount({root, post}) -> {receive, unmount}; rendering, lazy media; icons.js inline SVG icons; style.css
    agent/SKILL.md  what the agent learns (publish with `promo flow snapshot`, react to `[mod:promo-flow]`)

No build step, no network, no storage. Classic scripts, loaded once into the host's window; everything they define lives inside `mount`, so the only globals are `commissionMods`, `PF` and `icon`.
The app talks only through the bridge: `receive` takes `init state media result theme`, `post` sends `ready media action title open-url`. All DOM access goes through the shadow root (`root.getElementById`, `root.activeElement`),
the CSS styles `:host`, and every width rule is a container query on the host (an `inline-size` container), because media queries would measure the host's whole window, not the pane.

**Downloads:** the Drafts tab has a Download button on every draft and final whose file loads. It saves the same bridge blob the player uses through a temporary `<a download>` click (name: the file's own name, else the label as a slug plus `.mp4`); there is no new bridge message and nothing is published.

**Voice input** is the host's, not ours: the note box is marked `data-dictate` and the compose row has `<slot name="dictate">`. CommissionAI renders its own voice button into that slot (Mac app only) and dictates
straight into the box, which fires `input` like typing. Nothing to do in the mod beyond the marker and the slot.
Media arrive as Blobs on request, by upload id, only for tiles near the viewport; the app makes and revokes its own object URLs. Only `opacity` and `transform` animate; `reduceMotion` is honoured.

## State schema (`promo flow snapshot`, `promo.flow.snapshot()`)
Every path below that says `file` is `{"$file": "<absolute path>"}` (the host turns it into `{"$media": {upload_id, name, mime, size}}`, or `{"$media": null, "$error": "..."}`); a missing file is `null`.

    summary    {title<=80, status<=140, badge: working|waiting|done|attention, progress: {done, total: 10}, primary?<=24}
    title, intent, stage (discover|scripts|pick|storyboard|assets|keyframes|confirm|drafts|review|final), stage_label, stage_since (ISO, last flow log entry), cycle, rounds_used, rounds_max
    steps      [{id, label, state: done|current|todo|stale, stale}]  (10, one per stage; `stale` = its approval no longer matches what was approved; never `done` then)
    stale_steps [{id, gate, label}]                            approvals that went stale; the mod shows "Approved earlier, but <step> changed since."
    style      {style, refs[], no_refs} | null
    scripts    [{id, title, logline, picked, verdict, beats[<=2]}]       beats = first two list items of the script file
    councils   {scripts?: text}                                    the latest council note per kind (<= 900 chars): shown as "What the council said" above the scripts
    boards     [{id, title, logline, aspect, duration_s, scenes: [{id, beat, start_s, end_s, action, caption, voice, sound, camera, proof,
                 source: real|generated|mock|other, generated, start: {label, path: file|null, prompt}, end: {...}, frames: [{label, path, prompt}]}]}]
                 The frames are storyboard stills, not footage. One function derives the scene chip and the timeline mark: for source=real, "Captured" only when every real asset covering the scene is ready and its file loads
                 (screenshots alone read "Captured stills", never green); any mock reads "Mock in plan"; any to-make or missing file, or no asset, reads "To capture";
                 "Generated plate" for generated; no chip for `other` (a scene with no `source` is `other`, never real). Legend: "All real assets ready"
    assets     [{id, label, kind, source, state: ready|mock|todo, scenes[] (only ids that exist in a board), how, licence, note, path: file|null, sample: file|null, sample_note}]
                 `sample` is what `promo flow asset make` made so the person can look at / hear the asset before it exists (image, ~7 s mp4, mp3): the tile plays it labelled SAMPLE and the
                 state stays mock / to make. The Approve button at the storyboard gate stays disabled while any frame is not an image (`start|end.slate` = a text slate, path null) and at the assets gate
                 while any asset has neither `path` nor `sample`; the banner's "Ask the agent to make them" sends the `generate` action (`promo flow make`)
                 the mod shows a `ready` asset whose file is missing or failed as "File missing", never as ready, and disables Approve at the assets gate while any file is missing.
                 `label` is the human title (explicit `label`, else the first clause of `how`, else the id made readable); the raw `id` is only a tooltip
    to_make    [{kind: keyframe|asset, id, label, at?, detail, story?, scene?, which?, asset_kind?, source?}]   what `promo flow needs` lists; keyframe label is "Scene 03 · mid frame 1", at is "t=14.5 s"
    drafts     [{id, label, note, path, name, rel, after, share_as, shared}]   after = "round 2" when the draft was made for that round; finals [{id, label, path, name, rel, share_as, shared}]
    share      {destinations: [{id: artifacts|loom, label, note, in_place}]}   what `promo flow share detect` found for the host's twg user (an hour's cache; empty = no upload row at all).
                 Per draft/final: `share_as` is the canonical name it uploads as (`<project>_draft_N`, `<project>_final_vN`), `shared` is `{dest: {url, name, at, edited}}` for what is already up;
                 `edited` = the file changed since. The Drafts tab shows one row per destination: Upload; Update (Artifacts refreshes the same link); Upload again (Loom cannot replace, it adds a copy);
                 a final is a numbered revision, never overwritten (an edited one says to register the new file). `PF.shareRows` derives the rows
    rounds     [{cycle, n, feedback, verdict: yes|partial|no|null, open, scores{}, research[urls], drafts_at_start}]
    activity   [{at, text<=120, kind: capture|render|voice|music|check|plan|other|milestone, done}]  oldest first, <= 200: the agent's `promo flow note`s plus flow milestones. The working panel shows the latest
                 line, its age, one dot per item (hollow = in flight, solid = done, colour = kind) and the last three lines; `summary.status` is "Now: <latest note>" while working
    checks     [{ok, text}]  plain sentences from the same conditions as `promo flow status` ("2 of 4 keyframes done, 2 left")
    approvals  {gate: {by, at, fresh}}
    gate       null | {gate, kind: style|pick|approve|confirm|draft, stage, question, approve_label, changes_label, options[], picks_min?, picks_max?, stale?}
                 a stale earlier approval takes over the gate ("Approve again", kind approve, stage = that step)

**Counts have one source.** For the selected story the mod derives one list (asset rows used in that story's scenes + that story's keyframes still to make) with exclusive buckets ready / mock / to make / missing; the Assets tab badge, the counter row, the filters and the cards all read it, and the Storyboard badge is the number of scenes in that story (`mod-dev/shoot.py` asserts badge = sum of buckets = cards for every stage and story). Scene refs on assets are validated against the selected story's scene ids.

Actions: `approve`, `pick`, `changes`, `feedback`, `generate {what}`, `share {kind: draft|final, n, item, dest, dest_label}` (the agent runs `promo flow share <kind> <n> --to <dest> --by NAME`).

`gate.gate` is what the `approve` and `pick` actions guard on (`/gate/gate` vs payload `gate`). The first state after activation is `{}` with summary status "Starting": the app shows its Getting started screen.
The `readonly` flag on the host `state` message (archived thread) disables every send. Actions: `approve {gate, draft?}` (at the draft gate `draft` is the latest draft's id), `pick {gate, picks: "A B"}`, `changes {stage, text}`, `feedback {round, max_rounds, text}`.
The style step has no flow gate, so the person's choice goes as `changes {stage: "discover", text: "Style: ..."}`.

## Develop
    .venv/bin/python mod-dev/serve.py            # builds a fixture project, serves http://127.0.0.1:8765/dev/harness.html
    .venv/bin/python mod-dev/shoot.py            # screenshots to /tmp/promo-flow-shots/v1/ (headless Chrome)
    .venv/bin/python mod-dev/serve.py --project PROJECT_DIR   # drive a REAL project: stage `live` re-reads `promo flow snapshot`, clicks run the real flow commands (approve, pick, generate = `promo flow make`)
    .venv/bin/python mod-dev/shoot.py --base http://127.0.0.1:8765 --tabs storyboard,assets   # screenshots of that live stage
    .venv/bin/python mod-dev/fixtures.py --keep /tmp/pf-fix --dump /tmp/pf-snapshots   # the canned states as JSON files
    .venv/bin/python -m pytest tests/test_flow.py -q

The harness plays the host: mounts the mod into its page in a shadow root like CommissionAI does, puts a stand-in Mic button in the dictate slot, switch stage, dark/light, pane width (380 / 520 / 900),
offline, readonly, reduce motion, hold state (loading), media failures, a new version arriving mid-edit (with or without the step changing), and the bridge log with the rendered action messages.
Stages: the ten flow stages plus `starting`, `storyboard-partial`, `assets-error`, `long-content`, `review-maxed`.
