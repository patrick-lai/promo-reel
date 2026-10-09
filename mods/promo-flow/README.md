# promo-flow mod

**Host-agnostic by design:** this mod speaks the mod protocol (v2: mounted in the host's page, inside a shadow root) described in the host's own docs (`docs/mods.md` of the host), and `mod-dev/` plays a minimal host for it. CommissionAI was the first host.

The promo flow (`promo flow ...`, see `promo/flow.py`) as a mod: a web app that the host mounts into its own page and shows in its Stage (right pane, about 380 to 900 px wide, full height),
with a short summary card in the chat. The agent publishes state; the person's clicks come back to the agent as `[mod:promo-flow] ...` messages. In CommissionAI the agent publishes with `commissionctl mod publish promo-flow --file F`.

    mod.json        manifest: slash command, activation message, actions approve | pick | changes | feedback | generate | share | resume, agent skill
    index.html      shell (header + stepper, tabs, content, sticky gate bar, lightbox)
    app.js          registers window.commissionMods["promo-flow"] = mount({root, post}) -> {receive, unmount}; rendering, lazy media; icons.js inline SVG icons; style.css
    agent/SKILL.md  what the agent learns (publish with `promo flow snapshot`, react to `[mod:promo-flow]`)

No build step, no network, no storage. Classic scripts, loaded once into the host's window; everything they define lives inside `mount`, so the only globals are `commissionMods`, `PF` and `icon`.
The app talks only through the bridge: `receive` takes `init state media result theme`, `post` sends `ready media action title open-url`. All DOM access goes through the shadow root (`root.getElementById`, `root.activeElement`),
the CSS styles `:host`, and every width rule is a container query on the host (an `inline-size` container), because media queries would measure the host's whole window, not the pane.

**Add files:** the last tab (`PF.FILES_TAB`) takes the person's own footage and pictures by drag and drop or the file picker (up to 10 files, 100 MB a video, 20 MB the rest, the composer's limits). "Send to the agent" posts the bridge message `{type:"files", id, files, text}` (host-side, `docs/mods.md`): the host uploads the files like chat attachments and sends `text` (`PF.filesMessage`: names, their note, the asset rows still waiting) as the person's message; the agent finds the files under `.commission/attachments/`. The tab's state is the mod's own (nothing in the published state); `mod-dev/harness.js` answers `files` and `shoot.py --files x-files-*` shoots it.

**Downloads:** the Drafts tab has a Download button on every draft and final whose file loads. It saves the same bridge blob the player uses through a temporary `<a download>` click (name: the file's own name, else the label as a slug plus `.mp4`); there is no new bridge message and nothing is published.

**Calm while it works:** the open tab is repainted only when something on screen changed, and an agent update never rebuilds a clip the person is watching (playing, or paused or scrubbed in the last 20 s): a banner says more is waiting and `Show now` applies it. While the agent works (job, autopilot, a sent request) the tab repaints at most once per 12 s (`PF.settleWait`); the person's own clicks and a step change repaint at once. Checked by `mod-dev/shoot.py --check` (stage `foryou-many`).

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
    scripts    [{id, title, logline, picked, verdict, recommended: why|null, beats[<=2], words, headings[{level,title}<=40], body: text|null, body_note}]   recommended = the agent's one pick (`promo flow recommend ID --why TEXT`): a "Recommended" pill on the card, the reason in its tooltip (hover or keyboard focus); beats = first two list items of the script file; body = the whole script (markdown)
    docs       [{id, title, kind, kind_label, group, story|null, summary, updated, source: agent|template, words, headings[<=40], preview, body: text|null, body_note}]   the Plan tab: planning documents the agent added with `promo flow doc ...`
                 kinds: script treatment shotlist direction edit audio capture schedule deliverables risks research review notes; groups: Script Direction Edit Audio Capture Delivery Notes
    widgets    [{id, title, kind: blocks|html, place: workbench|scripts|storyboard|assets|plan|draft, span 1-12, height: s|m|l|xl|auto, order, summary, updated, blocks: [block]|null, html: text|null,
                 files: {name: file|null}, data: {name: text}, note: text|null}]   the agent's dynamic panels (see Widgets below); `note` replaces the content when it is missing or too big for the state
    councils   {scripts?: text}                                    the latest council note per kind (<= 900 chars): shown as "What the council said" above the scripts
    boards     [{id, title, logline, aspect, duration_s, density: every_s|null, scenes: [{id, beat, start_s, end_s, action, caption, voice, sound, camera, proof,
                 notes: [{id, text, by, answer: text|null}] (comments on the scene; open until answered), source: real|generated|mock|other, generated, start: {label, path: file|null, prompt}, end: {...}, frames: [{label, path, prompt, t, auto}]}]}]
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
    drafts     [{id, label, note, path, name, rel, after, share_as, shared, verify, board, look, pins, judged, restorable}]   after = "round 2" when the draft was made for that round; finals [{id, label, path, name, rel, share_as, shared}]
                 verify {state: checked|failed|not_checked, line, passed, warned, failed, skipped[{gate, why}]}: what `promo check` measured on this very file (a report
                 of another file is refused), skipped gates named with their reason, never counted as passed. board {line, fixed, broken, open, held, total, passing,
                 rows[{id, what, scene, status: pass|fail|unmeasured, change: fixed|broken|open|held, source}]}: every check against the draft before it (the round's
                 hidden control is never in it). look {mean, scenes[{scene, d, pair: file}]} | null: reference look distance, pair = reference left, draft right.
                 pins [{id, at_s, scene, text, by}]: notes pinned to a moment. judged: the blind comparison line. restorable: the plan behind it is kept
    pairs      [{id, question, scene, media: image|video|audio, left: file, right: file, answered: {side, by, at}|null}]   blind picks for the person; labels never sent
    autopilot  {state: running|paused|done|blocked|out_of_time|stopped, minutes, used_min, left_min, passes, by, line, goal_met} | null
    assumptions [{id, text, scene, overturned: {by, text, at}|null}]    choices the agent made without asking; "Change this" overturns one
    scout      {app_scenes, real, missed, drawn}; per scene `scout: real|missed|drawn|null` + `scout_why`, per frame `real` (a screenshot of the real product)
    lessons    [{id, line, videos}]   what this person said in earlier videos (Plan tab, "Forget")
    share      {destinations: [{id: artifacts|loom, label, note, in_place}]}   what `promo flow share detect` found for the host's twg user (an hour's cache; empty = no upload row at all).
                 Per draft/final: `share_as` is the canonical name it uploads as (`<project>_draft_N`, `<project>_final_vN`), `shared` is `{dest: {url, name, at, edited}}` for what is already up;
                 `edited` = the file changed since. The Drafts tab shows one row per destination: Upload; Update (Artifacts refreshes the same link); Upload again (Loom cannot replace, it adds a copy);
                 a final is a numbered revision, never overwritten (an edited one says to register the new file). `PF.shareRows` derives the rows
    rounds     [{cycle, n, feedback, verdict: yes|partial|no|null, open, scores{}, research[urls], drafts_at_start}]
    activity   [{at, text<=120, kind: capture|render|voice|music|check|plan|other|milestone, done}]  oldest first, <= 200: the agent's `promo flow note`s plus flow milestones. The working panel shows the latest
                 line, its age, one dot per item (hollow = in flight, solid = done, colour = kind) and the last three lines; `summary.status` is "Now: <latest note>" while working
    job        {kind: frames|samples|build, label, state: running|done|stopped, done, failed, total, started, updated, finished|null, waiting|null, resume|null,
                 active: [{id, label, story?, scene?, asset_kind?}], items: [{id, label, story?, scene?, asset_kind?, at, ok, skipped, path: file|null, error|null}] (<= 48, newest last)} | null
                 the latest long run (`promo flow frames | make | asset make`, and `promo build | shot` when promo.yaml sits in the flow project; flow/job.json,
                 promo/flowjob.py). `stopped` = ended early or its process is gone. `updated` is a heartbeat (every minute while the process lives): three missed
                 beats and the panel says "No sign of life" instead of spinning. `waiting` = queued behind another render (the box-wide heavy lock).
                 Build items are the steps (licence and footage checks, sound effects, voice-over, music, each shot with a still from its render, mix,
                 assemble, contact sheet); `skipped` = unchanged since the last build. `resume` is the command that carries a stopped run on.
                 The live panel above the tabs shows a spinner, a running clock, the count, a bar, "Making now", and one tile per picture as it lands (failed tiles
                 warn, the ones being made shimmer, one row of the queue), and "Ask the agent to carry on" on a stopped run. A finished run stays 10 minutes.
                 While a run is going, or stopped since the last flow event, `summary.status` is "<label>: N of M done" and `summary.progress` is the run's count,
                 so the chat card's number goes up with every picture. Those commands publish the snapshot themselves after every picture when `commissionctl`
                 and a thread token are there (`PROMO_FLOW_PUBLISH=0` turns it off); so does every `promo flow` command that changes the flow, so the card never
                 lags behind an approval the agent forgot to publish.
    checks     [{ok, text}]  plain sentences from the same conditions as `promo flow status` ("2 of 4 keyframes done, 2 left")
    approvals  {gate: {by, at, fresh}}
    settings   {output: {template, source: env|config|default, mode: home|repo|default|custom, locked, available, project, repo, home, example, presets{home|repo|default: {template, example}}}, saved_in}
                 the folder button in the header opens "Where files are saved": `mode` is the selected card, `presets[x].example` the path each card would use for the next video, `locked` (PROMO_PROJECTS is set)
                 disables it, `available: false` warns that the saved folder can't be reached (unplugged drive), `saved_in` is this video's own folder. Hidden when `settings` is absent
    gate       null | {gate, kind: style|pick|approve|confirm|draft, stage, question, approve_label, changes_label, options[], picks_min?, picks_max?, stale?}
                 a stale earlier approval takes over the gate ("Approve again", kind approve, stage = that step)

**Counts have one source.** For the selected story the mod derives one list (asset rows used in that story's scenes + that story's keyframes still to make) with exclusive buckets ready / mock / to make / missing; the Assets tab badge, the counter row, the filters and the cards all read it, and the Storyboard badge is the number of scenes in that story (`mod-dev/shoot.py` asserts badge = sum of buckets = cards for every stage and story). Scene refs on assets are validated against the selected story's scene ids.

**Long content stays inside the state limit.** The host copies only image, audio and video files (a `$file` pointing at a `.md` is refused by name), so a script or document travels as inline text (`body`) and the mod paginates it itself (`logic.js`: `parseBlocks`, `paginate`, `findPages`, `outline`; unit-tested, a 30 000 word script paginates in a few ms). `promo flow snapshot` keeps the whole state under `mod.json` `state_limit_kb`: when it would not fit, the largest bodies are replaced by `body: null` with a `body_note` ("Too long to show here (N words). Ask the agent to split it into parts."), which the card and the reader show instead; a missing file reads the same way with its own note (`PF.bodyOf`).

**Widgets** (`promo flow widget add|layout|list|rm|example`, `promo/widgets.py`): panels the agent builds when the fixed tabs cannot show what a job needs (a Blender render queue, a model viewer, a table of takes). The agent decides what goes inside and how they are laid out; nothing is a gate.
- `place: workbench` widgets are the **Workbench** tab (it exists once one does); any other `place` pins the widget to the top of that tab. Layout is a 12 column grid: `span` columns (12 full, 6 half, 4 a third), `order` sorts, `height` is a preset or `auto` (follows the content, 120-700 px); a pane under 640 px wide stacks everything. An html widget has a "larger" toggle (full row, 620 px).
- `kind: blocks` is drawn by the Stage from a fixed set: text (markdown), callout, stats, kv, list, checklist, table, bars, progress, code, image, video, audio, gallery. The Python side refuses anything else with a reason; files are referenced by attachment name.
- `kind: html` runs in `<iframe sandbox="allow-scripts" srcdoc>`: opaque origin (no Stage DOM, storage or cookies), and a policy (`default-src 'none'`, no network, `blob:`/`data:` for media) placed before the widget's own HTML. The frame gets `window.promo`: `ready(fn)`, `data` (attached text files by name), `file(name)` / `url(name)` (attached images, audio and video as a Blob / object URL, delivered over postMessage because the frame cannot reach the bridge), `theme` and `onTheme` (the Stage's colours also as CSS variables `--pf-ink --pf-dim --pf-well --pf-raised --pf-line --pf-accent`), `tell(text)`.
- The frame speaks to the Stage by postMessage only, and only `size`, `tell` and `error` are read. `tell` (and an uncaught error) show a bar under the widget quoting the text; **Send to the agent** sends the `widget` action, nothing leaves without that click. Frames reload when their tab re-renders, so keep interactive widgets on the Workbench (it re-renders only when the widgets change).
- Hosts with native widgets: when the host's `commissionctl widget` exists (CommissionAI), `promo flow` publishes every `workbench` widget there on each publish (`flow.sync_native_widgets`, a ledger in `flow/widgets/native.json` sends only what changed and removes what is gone) and leaves them out of the mod state, so the person sees one Workbench, the host's own. Html widgets get a prefix that aliases `window.promo` to the host's `window.widget` and `--pf-*` to `--w-*`. Pinned widgets stay in the mod. The harness and other hosts keep the mod's Workbench tab.
- Attachments: images, audio and video are copied like every other media file; text (`.json .csv .tsv .txt .md .obj .mtl .svg .gltf .ply .stl`, 256 KB each) is inlined into the state. A 3D scene is a rendered still or turntable video, or an exported `.obj` / `.gltf` text the widget draws itself. The whole state still has to fit `state_limit_kb`: the biggest widget is replaced by a note.

**Plan tab** (`Plan`, shown from the scripts stage on, or as soon as a document exists): an "Ask the agent to add" row folded under one line (open when the tab is empty) with quick requests (full script, shot list, edit plan, audio plan, capture checklist, everything for production, something else), then the library grouped by kind with search. A request opens the footer note box (so voice dictation works) prefilled and sends the `request` action. Opening a script (Scripts tab: "Read the full script") or a document opens the **reader**: back button, word count and read time, Download, find with highlighted matches across pages, a contents list, previous/next, page n of N. Markdown is rendered to DOM nodes, never HTML; only `https` links open, through the host. Documents added after the first state read carry a "New" chip until opened.

**Storyboard tab**: a view switch (Scenes | Frames in time) and a cadence control (Start and end, every 10 s, every 5 s, every 2 s, Other...) that sends `density`; the cadence row shows in Frames in time, or in Scenes once a cadence is set, so the plain storyboard keeps one control row. Frames in time lists every frame in time order with its clock time; a scene with more than two mid frames shows them as a film strip. When a board has a density, the storyboard gate needs those frames as real images too.

**Above every tab** (`PF.forYou`): an autopilot card while a run is on (clock, goal, "Stop and show me the draft"), each unanswered blind pick (Left / Right /
No difference / Can't tell; disabled until both sides load) and the agent's choices with "Change this". **Drafts tab**, per draft: the check line of that file, the
blind comparison, "Pin a note at this moment" (pauses the player, the note box asks "What should change at 0:14.5?"), the pinned notes (click seeks), the checks
with Fixed / Broken / Still open / Holds, the look pairs, "Let the agent keep working" (30 min / 1 hour / 2 hours, only on the latest draft with checks,
`PF.canAutopilot`) and on earlier drafts "Go back to this version" (the whole draft asks twice; one scene from a select).

Actions: `pin {draft, at, when, text}`, `restore {draft, scene, what}`, `ab {pair, side, label, question}`, `autopilot {op: start|stop, minutes, what}`,
`scene_note {story, scene, beat, text}` (a comment on one storyboard scene; the agent runs `promo flow scene note`, changes the scene, then `scene resolve`), `overturn {id, choice, text}`, `forget {id, text}`, `approve`, `pick`, `changes`, `feedback`, `generate {what}`, `widget {widget, title, text}` (a message the person sent from a widget's bar; the agent changes that panel or the video, then republishes), `request {text, where}` (an ask for content: documents, scripts, plans, scene changes), `density {story, every, what}` (every 0 = back to start and end frames); `share {kind: draft|final, n, item, dest, dest_label}` (the agent runs `promo flow share <kind> <n> --to <dest> --by NAME`), `settings {output}` (`home`, `repo`, `default` or a folder; the agent runs `promo config output`, then republishes).

`gate.gate` is what the `approve` and `pick` actions guard on (`/gate/gate` vs payload `gate`). The first state after activation is `{}` with summary status "Starting": the app shows its Getting started screen with a light travelling the pane's border (`#glow`, mode `wait`); the first real state flashes it once (`arrive`, 1.6 s) and it goes quiet. Reduced motion keeps only the soft edge.
Inside a CommissionAI thread every flow command that changes state publishes itself (`promo flow publish` on demand; `PROMO_FLOW_PUBLISH=0` in tests and in this harness), so the Stage never shows a step the flow has left. The gate is the question: once a state with a `gate` is published the agent's turn ends and the person's click comes back as a message. A gate is published one stage early on purpose (the pick gate while the flow is still at `scripts`), and `promo flow approve` walks the flow forward through stages whose checks pass, so the answer lands wherever it arrives. The style gate is shown again when a style is on file but nothing was said about references (the mod keeps that style selected). At the review cap the secondary button sends `changes` ("Restate direction"), which the agent turns into `promo flow revise` (a new cycle). The draft gate appears the moment a draft is registered (stage `drafts` or `review`), with two coloured buttons, "Approve" and "Feedback and iterate" (`data-tone="accent"` on the secondary); `promo flow round start` and `approve draft-approved` move a `drafts` flow into `review` themselves.
The `readonly` flag on the host `state` message (archived thread) disables every send. Actions: `approve {gate, draft?}` (at the draft gate `draft` is the latest draft's id), `pick {gate, picks: "A B"}`, `changes {stage, text}`, `feedback {round, max_rounds, text}`.
The style step has no flow gate, so the person's choice goes as `changes {stage: "discover", text: "Style: ..."}`.

**Design reviews.** `evals/mod-design-rubric.yaml` is the bar; `evals/mod-design-review-2026-10-07.md` records the last council round (current
screenshots vs grok-drawn north-star mockups, one Sonnet judge per page) and what the "v7" block of `style.css` changed because of it. Section
headings share one style (`.sec-h`, count beside it); the footer's primary is outlined while a run is on (`.gate[data-busy]`); the current stepper
segment fills with a run's real progress (`--p`). The round-3 block adds the gate rules the judges kept asking for: a disabled primary keeps
the accent (tinted, with the note saying why it is off), one filled button per surface (the draft's "Feedback and iterate" is a strong neutral
outline, `data-tone="strong"`), the footer waits with the agent while a run is on ("Waiting for the agent: 8 of 20 images done", only the
navigation button stays live, and the badge reads With the agent), and a
soft fade above the gate shows that content continues under it. The round-4 passes (rubric v2, 10 points, pass at 8; asks and status in
`evals/round4-asks.md`) add: while a blind pick waits, the badge reads "Your turn · 1 pick", the note says "Pick an end card, then ...", and
Approve is soft (outlined, `aria-disabled`; clicking it scrolls to the pick); a stopped run with a resume command makes "Ask the agent to
carry on" the primary, and without one "Make the rest"; while the autopilot runs the footer is the one Stop (`data-k="ap-stop"`) and a
waiting pick says so; queued job items are a count, never blank tiles (`JOB_QUEUE_TILES = 0`); the state line drops its "Also open for you"
tail while the agent holds the turn; the storyboard's timeline marks any scene with a frame not made (`k-unmade`) and the frames count
carries "N not made"; the asset group's open line says "1 for the agent to record · 1 to make"; the Plan tab's empty search offers "Clear search".

## Develop
    .venv/bin/python mod-dev/serve.py            # builds a fixture project, serves http://127.0.0.1:8765/dev/harness.html
    .venv/bin/python mod-dev/shoot.py            # screenshots to /tmp/promo-flow-shots/v1/ (headless Chrome)
    .venv/bin/python mod-dev/serve.py --project PROJECT_DIR   # drive a REAL project: stage `live` re-reads `promo flow snapshot`, clicks run the real flow commands (approve, pick, generate = `promo flow make`, settings = `promo config output` against a throwaway config unless PROMO_CONFIG is set)
    .venv/bin/python mod-dev/shoot.py --base http://127.0.0.1:8765 --tabs storyboard,assets   # screenshots of that live stage
    .venv/bin/python mod-dev/fixtures.py --keep /tmp/pf-fix --dump /tmp/pf-snapshots   # the canned states as JSON files
    .venv/bin/python -m pytest tests/test_flow.py -q

The harness plays the host: mounts the mod into its page in a shadow root like CommissionAI does, puts a stand-in Mic button in the dictate slot, switch stage, dark/light, pane width (380 / 520 / 900),
offline, readonly, reduce motion, hold state (loading), media failures, a new version arriving mid-edit (with or without the step changing), and the bridge log with the rendered action messages.
Stages: the ten flow stages plus `autopilot` (a run in progress), `starting`, `storyboard-partial`, `plan` (17 documents, one of 12 000 words), `dense` (frames every 5 s), `assets-error`, `stale-approval`, `long-content`, `review-maxed`.
    .venv/bin/python mod-dev/shoot.py --check    # interaction checks in headless Chrome: reader paging, find, contents, requests, cadence, escaping

**Read full script** (Scripts and Pick) opens the script in a dialog over the pane: the cards and the footer decision stay behind it (inert), Esc or the close button returns focus to the link; the Plan tab's documents still open in the tab.

**Calm repaints.** An update from the agent never makes the page blink. While the agent works the open tab repaints at most once per 12 s (a thin accent bar under the tabs, `data-held` on the app, says news is waiting); a repaint the person did not cause does not fade the pane in (`.pane.calm`), a picture already shown moves into the new slot as the same `<img>` (`adoptImages`, `data-ms="img"`), a file already fetched fills its slot at once with no grey skeleton, clips and sounds still on the page keep their file (`releaseHeavy` runs after the swap), cards that appear ease in (`.pf-in`) and cards that go ease out (`.pf-out`, a collapsing copy kept for 260 ms). Reduce-motion skips the easing. Checked in `mod-dev/shoot.py --check` (storyboard).
