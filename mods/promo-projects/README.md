# promo-projects mod: resume a past promo

`/promo-resume [words]` in the composer (the host lists it under **+ › Commands**) opens this picker in the Stage of a new thread: every past promo flow
project, a search box, filters by whose turn it is, and a peek at each project. **Resume here** sends the agent the project's id; the agent runs
`promo flow resume <id>` and the thread carries on with that project in the promo-flow pane. Same protocol, bridge and theming as `mods/promo-flow`
(shadow root, container queries, host tokens); its own small icon set and `window.PP` so the two mods never share globals.

    mod.json        slash /promo-resume, activation message, actions resume | find (both guarded on /pickable)
    index.html      header (title, badge, search, filters), banner, list | peek
    app.js          window.commissionMods["promo-projects"] = mount({root, post}) -> {receive, unmount}
    logic.js        window.PP: search (every word must match; title and name outrank the brief), buckets, highlight marks, relative times
    agent/SKILL.md  what the agent does on /promo-resume and on each click

**Layout.** Under 720 px the list fills the pane and a row opens the peek with an "All projects" back button (Escape also goes back); from 720 px
the list is a 340 px column next to the peek, which shows the selected project (else the best match). `/` focuses the search, arrow keys move
between rows, Enter in the search opens the first match.

**Peek** (what the project is and exactly where it stopped): up to four real storyboard frames, the latest cut (loaded only on Play), a step bar
with "Step n of 10", the question waiting for the person or the agent's status, open checks, the brief in the person's words, picked stories, counts,
the person's approvals (stale ones flagged), the agent's latest notes and the folder path.

## State schema (`promo flow projects --out F`, `promo.flow.picker()`)

    summary    {title, status, badge: waiting (projects to pick) | done (resumed) | attention (none found)}
    query      the person's /promo-resume words; pre-fills the search once
    pickable   true until a project is resumed in this thread (the resume and find actions guard on it)
    resumed    null | {id, title, stage_label, at}
    projects   most recent first: [{id, name, path, title, intent, style, stage, stage_label, badge, status, steps[{id,label,state,stale}], question|null,
                 open[<=3], started, updated, picked[], counts{scripts, scenes, assets, assets_ready, drafts, finals, rounds_used, rounds_max},
                 approvals[{label, by, at, fresh}], notes[{at, text}<=3], frames[file<=4], video: file|null (only the 6 most recent), video_label}]
               an unreadable flow is {id, name, path, error, updated: null}

Actions: `resume {pickable, id, title, stage_label}`, `find {pickable, text}` ("Not in the list?": the person describes it, the agent looks).

## Where the projects come from
`promo flow projects` lists folders of the projects dir (`promo config projects-dir`) that hold `flow/flow.json`, then the flows remembered in
`~/.config/promo-reel/recent.json` (next to the config file): `promo flow init` and `promo flow resume` add to it, so a flow started in any folder is found again.

## Develop
    .venv/bin/python mod-dev/serve.py --real-picker        # then open /dev/harness.html?mod=promo-projects (stages picker, picker-search, picker-resumed, picker-empty, picker-real)
    node --test mods/promo-projects/test/logic.test.js
    .venv/bin/python -m pytest tests/test_flow.py -q -k "picker or resume"
