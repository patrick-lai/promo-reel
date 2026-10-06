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
    scripts    [{id, title, logline, picked, verdict, beats[<=2], words, headings[{level,title}<=40], body: text|null, body_note}]   beats = first two list items of the script file; body = the whole script (markdown)
    docs       [{id, title, kind, kind_label, group, story|null, summary, updated, source: agent|template, words, headings[<=40], preview, body: text|null, body_note}]   the Plan tab: planning documents the agent added with `promo flow doc ...`
                 kinds: script treatment shotlist direction edit audio capture schedule deliverables risks research review notes; groups: Script Direction Edit Audio Capture Delivery Notes
    councils   {scripts?: text}                                    the latest council note per kind (<= 900 chars): shown as "What the council said" above the scripts
    boards     [{id, title, logline, aspect, duration_s, density: every_s|null, scenes: [{id, beat, start_s, end_s, action, caption, voice, sound, camera, proof,
                 source: real|generated|mock|other, generated, start: {label, path: file|null, prompt}, end: {...}, frames: [{label, path, prompt, t, auto}]}]}]
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
    settings   {output: {template, source: env|config|default, mode: home|repo|default|custom, locked, available, project, repo, home, example, presets{home|repo|default: {template, example}}}, saved_in}
                 the folder button in the header opens "Where files are saved": `mode` is the selected card, `presets[x].example` the path each card would use for the next video, `locked` (PROMO_PROJECTS is set)
                 disables it, `available: false` warns that the saved folder can't be reached (unplugged drive), `saved_in` is this video's own folder. Hidden when `settings` is absent
    gate       null | {gate, kind: style|pick|approve|confirm|draft, stage, question, approve_label, changes_label, options[], picks_min?, picks_max?, stale?}
                 a stale earlier approval takes over the gate ("Approve again", kind approve, stage = that step)

**Counts have one source.** For the selected story the mod derives one list (asset rows used in that story's scenes + that story's keyframes still to make) with exclusive buckets ready / mock / to make / missing; the Assets tab badge, the counter row, the filters and the cards all read it, and the Storyboard badge is the number of scenes in that story (`mod-dev/shoot.py` asserts badge = sum of buckets = cards for every stage and story). Scene refs on assets are validated against the selected story's scene ids.

**Long content stays inside the state limit.** The host copies only image, audio and video files (a `$file` pointing at a `.md` is refused by name), so a script or document travels as inline text (`body`) and the mod paginates it itself (`logic.js`: `parseBlocks`, `paginate`, `findPages`, `outline`; unit-tested, a 30 000 word script paginates in a few ms). `promo flow snapshot` keeps the whole state under `mod.json` `state_limit_kb`: when it would not fit, the largest bodies are replaced by `body: null` with a `body_note` ("Too long to show here (N words). Ask the agent to split it into parts."), which the card and the reader show instead; a missing file reads the same way with its own note (`PF.bodyOf`).

**Plan tab** (`Plan`, shown from the scripts stage on, or as soon as a document exists): an "Ask the agent" card with quick requests (full script, shot list, edit plan, audio plan, capture checklist, everything for production, something else), then the library grouped by kind with search. A request opens the footer note box (so voice dictation works) prefilled and sends the `request` action. Opening a script (Scripts tab: "Read the full script") or a document opens the **reader**: back button, word count and read time, Download, find with highlighted matches across pages, a contents list, previous/next, page n of N. Markdown is rendered to DOM nodes, never HTML; only `https` links open, through the host. Documents added after the first state read carry a "New" chip until opened.

**Storyboard tab**: a view switch (Scenes | Frames in time) and a cadence control (Start and end, every 10 s, every 5 s, every 2 s, Other...) that sends `density`. Frames in time lists every frame in time order with its clock time; a scene with more than two mid frames shows them as a film strip. When a board has a density, the storyboard gate needs those frames as real images too.

Actions: `approve`, `pick`, `changes`, `feedback`, `generate {what}`, `request {text, where}` (an ask for content: documents, scripts, plans, scene changes), `density {story, every, what}` (every 0 = back to start and end frames); `share {kind: draft|final, n, item, dest, dest_label}` (the agent runs `promo flow share <kind> <n> --to <dest> --by NAME`), `settings {output}` (`home`, `repo`, `default` or a folder; the agent runs `promo config output`, then republishes).

`gate.gate` is what the `approve` and `pick` actions guard on (`/gate/gate` vs payload `gate`). The first state after activation is `{}` with summary status "Starting": the app shows its Getting started screen.
Inside a CommissionAI thread every flow command that changes state publishes itself (`promo flow publish` on demand; `PROMO_FLOW_PUBLISH=0` in tests and in this harness), so the Stage never shows a step the flow has left. The gate is the question: once a state with a `gate` is published the agent's turn ends and the person's click comes back as a message. A gate is published one stage early on purpose (the pick gate while the flow is still at `scripts`), and `promo flow approve` walks the flow forward through stages whose checks pass, so the answer lands wherever it arrives. The style gate is shown again when a style is on file but nothing was said about references (the mod keeps that style selected). At the review cap the secondary button sends `changes` ("Restate direction"), which the agent turns into `promo flow revise` (a new cycle).
The `readonly` flag on the host `state` message (archived thread) disables every send. Actions: `approve {gate, draft?}` (at the draft gate `draft` is the latest draft's id), `pick {gate, picks: "A B"}`, `changes {stage, text}`, `feedback {round, max_rounds, text}`.
The style step has no flow gate, so the person's choice goes as `changes {stage: "discover", text: "Style: ..."}`.

## Develop
    .venv/bin/python mod-dev/serve.py            # builds a fixture project, serves http://127.0.0.1:8765/dev/harness.html
    .venv/bin/python mod-dev/shoot.py            # screenshots to /tmp/promo-flow-shots/v1/ (headless Chrome)
    .venv/bin/python mod-dev/serve.py --project PROJECT_DIR   # drive a REAL project: stage `live` re-reads `promo flow snapshot`, clicks run the real flow commands (approve, pick, generate = `promo flow make`, settings = `promo config output` against a throwaway config unless PROMO_CONFIG is set)
    .venv/bin/python mod-dev/shoot.py --base http://127.0.0.1:8765 --tabs storyboard,assets   # screenshots of that live stage
    .venv/bin/python mod-dev/fixtures.py --keep /tmp/pf-fix --dump /tmp/pf-snapshots   # the canned states as JSON files
    .venv/bin/python -m pytest tests/test_flow.py -q

The harness plays the host: mounts the mod into its page in a shadow root like CommissionAI does, puts a stand-in Mic button in the dictate slot, switch stage, dark/light, pane width (380 / 520 / 900),
offline, readonly, reduce motion, hold state (loading), media failures, a new version arriving mid-edit (with or without the step changing), and the bridge log with the rendered action messages.
Stages: the ten flow stages plus `starting`, `storyboard-partial`, `plan` (17 documents, one of 12 000 words), `dense` (frames every 5 s), `assets-error`, `stale-approval`, `long-content`, `review-maxed`.
    .venv/bin/python mod-dev/shoot.py --check    # interaction checks in headless Chrome: reader paging, find, contents, requests, cadence, escaping
