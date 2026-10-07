# Round 4 asks (judges on the 10-point rubric, 7 Oct 2026)

Scores before: style 7.3 · pick 7.3 · storyboard 7.4 · assets 7.6 · plan 7.5 · review 7.1 · working 6.9 · final 7.5 · picker 7.7. Target: every page >= 8, nothing under 6, next_step and truth >= 8.

Status: [ ] open · [x] done · [-] not possible (reason)

## Gate bar (every page)
- [x] Disabled primary: label contrast >= 4.5:1 (dim text on the tint, keep it the only bordered footer element); second button ghost (no border) while the primary is disabled
- [x] Pick helper: "None picked yet. Choose up to 2." / "2 picked. Untick one to change." / primary "Storyboard these 2 stories"
- [x] Style helper after a pick: "<Style> selected. Next: scripts to choose from."
- [x] Final footer: "Download above, or ask for changes", nowrap; under 420 px only the button
- [x] Autopilot: footer is one outlined "Stop and show me the draft"; Approve and Feedback hidden; in-tab link removed; "0 of 60 min" becomes "Started HH:MM · 60 min limit"
- [x] Stopped run: "Ask the agent to carry on" is the footer primary; Review story B becomes secondary; banner keeps text only
- [x] Review footer while a pick is pending: "Pick an end card, then approve or send feedback for round 3 of 5."; badge "Your turn · 1 pick"
- [x] Plan tab footer hint: "Plan is for reference. Review the storyboard when ready."
- [x] Starting state: footer "Nothing for you to do yet.", elapsed time under Preparing, spinner top-aligned

## Style
- [x] 4 columns from ~760 px, thumbnails capped (<= 200 px wide); describe/reference above the fold
- [x] Radio ring beside the title (out of the art), empty ring, no filled grey disc in light
- [x] Caption beside "Pick a style": "Sketches of each look, not your footage."
- [x] Focus-visible ring on cards and inputs (exists globally: verify)

## Pick
- [x] 900: no logline clamp, titles 18 px; drop the "Before this step can finish" block on pick
- [x] Read link: min-width 0, wraps, icon aligned to the logline edge
- [x] Card :focus-within ring; 36 px checkbox hit area
- [x] Tab counts as pills at 380 (check the 380 shot)

## Storyboard
- [x] Timeline strip 56 px (44 at 380), scene number as a 16 px corner badge, dashed warn outline + dot on scenes with a missing frame, note adds "dashed = frame not made"
- [x] Banner one line: "2 frames not made yet" + "Make them" (full text in aria-label); drop "(story A: 2)"
- [x] Story switch + view control on one row where they fit
- [x] "No image yet" mid tiles -> one 64 px row "Mid · t=14.5s · no image yet"
- [x] Lightbox counter "2 of 16 · 2 not made"; view switch "Frames in time 18 (16 made)"
- [x] Lightbox: toggle + caption under the frame centred; prev/next 44 px beside the toggle
- [x] Scene time "0–5 s" in the body font, tabular numbers

## Assets
- [x] One error banner naming the missing asset and scene, "Show it" link, button "Ask the agent to re-make it" (singular/plural); card gets a red "File missing" chip and left rule
- [x] Always two chips: kind (neutral) then state (Real green dot / Mock amber / To make grey dashed / Generated neutral dot)
- [x] Card as flex column, Details pinned to the bottom above a hairline
- [x] Thumbnail column 40% of the card from 480 px
- [x] Filter chips: aria-pressed with a visible selected style; "Show all" link when a filter is active

## Plan / reader
- [x] Group chips wrap at <= 560 px, never clip
- [x] Reader: contents select -> host-styled 36 px button synced to the page; pager without the white band; full page label, no ellipsis
- [x] Reader header: Download in the meta row; find + prev/next + Contents on one 40 px row
- [x] List: two columns from 760 px with 2-line summaries; 2-line summaries at <= 520
- [x] Group heading 13 px semibold ink with a 1 px rule; Picked first
- [x] Request box: label "Request: Shot list", textarea capped at 3 rows

## Review / Final (for-you strip)
- [x] A/B previews capped at 120 px (<= 520) / 200 px (900); at 900 A/B and choices side by side; after a pick collapse to one 44 px line "You picked Left · Change"
- [x] Left/Right 44 px, 1 px muted border; card neutral border with a 3 px accent bar on the left
- [x] Choices card: plain row under a hairline at <= 520; "Change this" right-aligned on the text row; "say so to swap it" -> "tap Change this to swap it" (agent text: note)
- [-] Checks: goal wording for Holds/Fixed rows (the check text is the person's own note; the mod cannot rephrase it); "still open" now in both chips
- [x] One 16 px gap between the file row, note, check line, judged line, pin row
- [x] Final: the folded pick row 44 px, 1 px neutral border, "Which end card? · You picked B" when answered; order ready block, switch, player, file row, credits, decisions
- [x] Rounds column at 900: earlier rounds folded, links capped at 3
- [x] Tab strip at 380: pills at all widths; active tab scrolled into view; the Drafts dot gets a title

## Working
- [x] Building tiles: full labels on 2 lines; distinct done / queued / active styles
- [x] Time-left only after >= 3 finished items, whole minutes
- [-] Recordings "N open" (open = mock + to make across the group; both wait on someone, the card says who; unchanged)
- [-] State line (agent-side text in promo/flow.py summary; the mod clamps it to 2 lines)

## Picker
- [x] 900: stage tag and time on their own line under the title; title full width 2 lines
- [x] Row chip only for In progress / Delivered; Your turn as a 6 px accent dot before the question; slug plain mono
- [x] 900 list: one 56 px thumbnail beside the title instead of the 3-frame strip
- [-] Frame badges "Sc 01" and captions (the picker's frames carry only a scene number, no start/end role in its state)
- [x] 16 px fade above the detail footer; slug under the title when titles repeat
- [x] "Step n of 10" on the selected row's slug line

## Pass C asks (scores: style 7.9 · pick 7.9 · storyboard 7.7 · assets 7.4 · plan 7.6 · review 7.6 · working 7.4 · final 8.0 · picker 7.8)
- [x] Off and soft primary: readable ink on the tint (4.5:1)
- [x] Style: 2:1 sketches under 760 px; a 1 px inner edge on every sketch
- [-] Style: checklist row "Reference added, or none to add" (the checks are the agent's text in the flow state)
- [x] Pick: only "Read full script" is underlined, the count is plain; roomier cards from 760 px; Show more is a 36 px ink target
- [-] Pick: header chevron at 900 (the host header's steps button, not the page)
- [x] Storyboard: equal 16:9 timeline cells (two rows of four under 600 px); "Frame n of 16 · 2 not made yet"; fact values under their labels
- [-] Storyboard: story switch and view control on one row at 480 px (both story titles do not fit without truncation); duration bar under the row; collapse on scroll
- [x] Assets: card is a column on wide panes with Details at its foot; To make chip grey dashed with a hollow dot; PLACEHOLDER tag on a to-make sample; the sample banner never repeats a missing file; banner buttons 36 px
- [x] Plan: the reader hides a first heading equal to the title
- [-] Plan: "Send changes" disabled until a note exists (the button is how a note is written); 900 footer width (host gate bar)
- [x] Review: preview label bottom-left on a solid pill; Pin button on the column edge; "Change this" right of the sentence at 380; one-line pending-pick note
- [-] Review: rounds column starting under the choices card (the for-you strip sits above the tabs, outside the draft grid)
- [x] Final: credit labels in ink at 45% width; one 24 px section gap in the rounds column
- [-] Final: upload row wording (the share block's heading is the host's label)
- [x] Working: state line is its first sentence while the agent holds the turn; the footer does not repeat the panel's count; "Waiting on the agent's run" during a build; a failed frame tile says "failed"; the stopped banner has no second make button; the activity grid drops the grey flow-step squares; Starting names what comes next
- [-] Working: Keyframes step label during a build (fixture state), colour-bar previews on real items (fixture files)
- [x] Picker: 520 caption "n of 8 scenes, start frames"; list right padding at 900; 24 px pane fade; counts wrap
- [-] Picker: "Scene 03" badge on frames (the number is baked into the stills); duplicate "You approve…" bullet (open items from the state)

## Pass D asks (scores: style 8.1 ✓ · pick 7.6 · storyboard 7.7 (truth 7) · assets 8.0 ✓ · plan 7.5 (truth 7) · review 7.9 · working 7.8 · final 7.9 · picker 7.8)
- [x] Storyboard truth: lightbox "Frame n of 16 · 2 more not made yet (18 in all)"; badge on the still's floor; the sticky timeline compacts once scrolled
- [x] Plan truth: the contents list names sections only (no stale "p.1"); tighter top stack; bordered find chevrons; filter edge padding
- [x] Pick: the body flush with the checkbox on wide panes; the read link wraps as a unit and is a 36 px target
- [x] Assets: wide cards keep their own height; the divider spans the card; quiet open line and Details; "Scenes 01–08" with a bold lead
- [x] Review 900: the for-you strip heads the rounds column so both columns are independent stacks; 380 tab strip edge-masked
- [x] Final: "Earlier rounds" is a 44 px row with a divider and chevron, 12 px gaps; the 380 footer keeps its line
- [x] Working: a live run's banner is neutral with a clock; an unchanged build step says so; the state line never trails the gate's question; the Starting pane lists the ten steps; disabled Left/Right keep a border
- [-] Working: "Checking licences…" and "Sound effects" tile labels (fixture text); the header's step label during a build (fixture state)
- [x] Picker: 16 px more list padding at 900; the question wraps to 3 lines; no step rule on an unreadable row
- [-] Final 900 left column length (file row and upload row are the host's share block)
- [-] Style: the radio ring over the sketch (judges A and B asked for it beside the title; the ring now sits above the sketch, not over it); the 900 footer width (host gate bar)

## Pass E asks (scores: pick 8.0 ✓ · storyboard 7.8 · plan 8.0 ✓ · review 7.1 · working 7.7 · final 8.1 ✓; style, assets and picker judges hit the Sonnet session limit)
- [x] Review 900: the rounds column is no longer a scroll box (it clipped the strip, the Right button, the Scene chip and the round cards); pick previews stack full width there
- [x] Review: the file's notes are quiet 12.5 px lines; the check line is the one body-weight line; Pin and its hint share a row; the footer note is balanced
- [-] Review: answered-pick and failed-preview states (no fixture carries them; the failed tile already shows "Couldn't load")
- [x] Pick: one 15 px title size at every width
- [x] Storyboard: the make banners are amber, text centred on the button; compact strip cells keep a 36 px hit area; the lightbox time never breaks and the counter drops to its own line on narrow panes
- [-] Storyboard: story select beside the view switch at 520 (both story titles do not fit; the select starts under 480 px)
- [x] Plan: the request box shows "Request: <what>" visibly; a new harness shot captures the empty box with Send disabled
- [x] Final: the 380 footer stays one row with its line
- [x] Working: build tile names and "unchanged" on their own lines, clear of the icon; the activity map gives way to the counted legend; the autopilot card shows its clock instead of repeating the header; a stopped run's state line is its first sentence; the Starting pane sits at the top
- [-] Working: "Send changes" during a run (it queues a note for the agent, which is allowed); 20 images vs 18 frames (the fixture's job covers both stories)

## Pass F asks (scores: style 8.1 ✓ · pick 7.8 · storyboard 8.1 ✓ · assets 7.8 · plan 8.0 ✓ · working 7.8 · final 7.9 · picker 7.9; review rescored in G)
- [x] Review 900: the strip in the rounds column is one column of its own width; the Pin button never shrinks
- [x] Pick: rows line up across wide cards (two-line title slot); 22 px card padding
- [x] Assets: a row's cards share its height with Details and a full-width divider at each foot; Details focus ring; shorter "Open story B before you decide."
- [x] Storyboard: the lightbox counter has its own line on windows under 600 px
- [x] Plan: harness shot of the empty search ("zzz")
- [x] Style: harness shot of the typed own style; the gate reads "Use your own style and write scripts" with "Your own style: …"
- [x] Working: build tile names on one line with an ellipsis; a stopped run's banner is amber and the footer says only "Make the rest to carry on"; the Starting steps sit in a card, centred; the autopilot card's line no longer repeats the header's clock
- [x] Final: the upload row sits beside the credits on wide panes; panes end 64 px clear of the footer fade; under 440 px the note is "Download above."
- [x] Picker: the list's grid track never grows past its column (the cause of the clipped cards); no empty stage tag; the unreadable row shows its slug once and says "Check the folder, then reload the list."
- [-] Assets: the sticky tab bar "bleeding" (the bar is opaque; the fade above the footer is the only overlay)

## Pass G asks (scores: assets 8.0 ✓ · final 8.1 ✓ · pick 7.8 · review 7.9 · working 7.9 · picker 7.9; style 8.1, storyboard 8.1 and plan 8.0 held from F)
- [x] Pick: title 16-17 px / 650, logline 15 px muted, beats 13 px at the card foot; the untouched second button readable
- [-] Pick: hint and buttons on one footer row at 900 (host gate bar layout)
- [x] Assets: every card has a quiet source line ("Real · night-run.mov", "Licence: …", "Mock: no licence yet", "Not made yet"); real files tagged REAL / GENERATED / LICENSED; column cards stretch so every divider spans the card
- [x] Review: the reference strip is two wide pairs with a gap under its caption; Change this stays on its row; Left / Right captions under the previews; the soft Approve at 55%; a 28 px tab mask
- [x] Working: the activity title is capitalised and counts its updates; the flow-step chip is quiet; the failed tile names its frame; one "Send changes" name; the capture ask says "Send files, then paste the file path."; a live banner counts failures
- [-] Working: short fixed build-tile names (the fixture's labels)
- [x] Final: the upload row has one sentence-case heading with its caption under it and no repeated Loom chip; 16 px section gaps
- [x] Picker: wide rows put a 132 px thumbnail beside the title only; tag and time share a line; titles get three lines; counts break between items
