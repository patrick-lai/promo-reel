# promo-flow mod

The promo flow (`promo flow ...`, see `promo/flow.py`) as a CommissionAI mod: a sandboxed web app that CommissionAI shows in its Stage (right pane, about 380 to 900 px wide, full height),
with a short summary card in the chat. The agent publishes state; the person's clicks come back to the agent as `[mod:promo-flow] ...` messages. Spec: CommissionAI `docs/mods.md`.

    mod.json        manifest: slash command, activation message, actions approve | pick | changes | feedback, agent skill
    index.html      shell (header + stepper, tabs, content, sticky gate bar, lightbox)
    app.js          bridge protocol v1, rendering, lazy media; icons.js inline SVG icons; style.css
    agent/SKILL.md  what the agent learns (publish with `promo flow snapshot`, react to `[mod:promo-flow]`)

No build step, no network, no storage. Classic scripts (not `type=module`: module scripts are fetched with CORS, which an opaque-origin sandboxed frame cannot satisfy without an
`Access-Control-Allow-Origin` header). The app talks only through `postMessage`: in `init state media result theme`, out `ready media action title open-url`.
Media arrive as Blobs on request, by upload id, only for tiles near the viewport; the app makes and revokes its own object URLs. Only `opacity` and `transform` animate; `reduceMotion` is honoured.

## State schema (`promo flow snapshot`, `promo.flow.snapshot()`)
Every path below that says `file` is `{"$file": "<absolute path>"}` (the host turns it into `{"$media": {upload_id, name, mime, size}}`, or `{"$media": null, "$error": "..."}`); a missing file is `null`.

    summary    {title<=80, status<=140, badge: working|waiting|done|attention, progress: {done, total: 10}, primary?<=24}
    title, intent, stage (discover|scripts|pick|storyboard|assets|keyframes|confirm|drafts|review|final), stage_label, stage_since (ISO, last flow log entry), cycle, rounds_used, rounds_max
    steps      [{id, label, state: done|current|todo|stale, stale}]  (10, one per stage; `stale` = its approval no longer matches what was approved; never `done` then)
    stale_steps [{id, gate, label}]                            approvals that went stale; the mod shows "Approved earlier, but <step> changed since."
    style      {style, refs[], no_refs} | null
    scripts    [{id, title, logline, picked, verdict, beats[<=2]}]       beats = first two list items of the script file
    boards     [{id, title, logline, aspect, duration_s, scenes: [{id, beat, start_s, end_s, action, caption, voice, sound, camera, proof,
                 source: real|generated|mock|other, generated, start: {label, path: file|null, prompt}, end: {...}, frames: [{label, path, prompt}]}]}]
                 The frames are storyboard stills, not footage. One function derives the scene chip and the timeline mark: for source=real, "Captured" only when every real asset covering the scene is ready and its file loads
                 (screenshots alone read "Captured stills", never green); any mock reads "Mock in plan"; any to-make or missing file, or no asset, reads "To capture";
                 "Generated plate" for generated; no chip for `other` (a scene with no `source` is `other`, never real). Legend: "All real assets ready"
    assets     [{id, label, kind, source, state: ready|mock|todo, scenes[] (only ids that exist in a board), how, licence, note, path: file|null}]
                 the mod shows a `ready` asset whose file is missing or failed as "File missing", never as ready, and disables Approve at the assets gate while any file is missing.
                 `label` is the human title (explicit `label`, else the first clause of `how`, else the id made readable); the raw `id` is only a tooltip
    to_make    [{kind: keyframe|asset, id, label, at?, detail, story?, scene?, which?, asset_kind?, source?}]   what `promo flow needs` lists; keyframe label is "Scene 03 · mid frame 1", at is "t=14.5 s"
    drafts     [{id, label, note, path, name, rel, after}]   after = "round 2" when the draft was made for that round; finals [{id, label, path, name, rel}]
    rounds     [{cycle, n, feedback, verdict: yes|partial|no|null, open, scores{}, research[urls], drafts_at_start}]
    checks     [{ok, text}]  plain sentences from the same conditions as `promo flow status` ("2 of 4 keyframes done, 2 left")
    approvals  {gate: {by, at, fresh}}
    gate       null | {gate, kind: style|pick|approve|confirm|draft, stage, question, approve_label, changes_label, options[], picks_min?, picks_max?, stale?}
                 a stale earlier approval takes over the gate ("Approve again", kind approve, stage = that step)

**Counts have one source.** For the selected story the mod derives one list (asset rows used in that story's scenes + that story's keyframes still to make) with exclusive buckets ready / mock / to make / missing; the Assets tab badge, the counter row, the filters and the cards all read it, and the Storyboard badge is the number of scenes in that story (`mod-dev/shoot.py` asserts badge = sum of buckets = cards for every stage and story). Scene refs on assets are validated against the selected story's scene ids.

`gate.gate` is what the `approve` and `pick` actions guard on (`/gate/gate` vs payload `gate`). The first state after activation is `{}` with summary status "Starting": the app shows its Getting started screen.
The `readonly` flag on the host `state` message (archived thread) disables every send. Actions: `approve {gate, draft?}` (at the draft gate `draft` is the latest draft's id), `pick {gate, picks: "A B"}`, `changes {stage, text}`, `feedback {round, max_rounds, text}`.
The style step has no flow gate, so the person's choice goes as `changes {stage: "discover", text: "Style: ..."}`.

## Develop
    .venv/bin/python mod-dev/serve.py            # builds a fixture project, serves http://127.0.0.1:8765/dev/harness.html
    .venv/bin/python mod-dev/shoot.py            # screenshots to /tmp/promo-flow-shots/v1/ (headless Chrome)
    .venv/bin/python mod-dev/fixtures.py --keep /tmp/pf-fix --dump /tmp/pf-snapshots   # the canned states as JSON files
    .venv/bin/python -m pytest tests/test_flow.py -q

The harness plays the host: sandboxed iframe (`allow-scripts`), mod files served with the daemon's CSP (so a violation shows up here), switch stage, dark/light, pane width (380 / 520 / 900),
offline, readonly, reduce motion, hold state (loading), media failures, a new version arriving mid-edit (with or without the step changing), and the bridge log with the rendered action messages.
Stages: the ten flow stages plus `starting`, `storyboard-partial`, `assets-error`, `long-content`, `review-maxed`.
