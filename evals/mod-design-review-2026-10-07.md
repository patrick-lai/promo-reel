# Stage widget design review, 7 Oct 2026 (one iteration)

How it ran: every canned state of the promo-flow and promo-projects mods was shot with `mod-dev/shoot.py` (the "current" set); for each page a
north-star mockup of a mature version was drawn with the grok CLI through `promo.genvideo.generate` (custom guard, UI wanted); then one Sonnet judge
per page scored the current page against `evals/mod-design-rubric.yaml`, scored the mockup too, and named 3-4 changes that fit the host principles
(calm charcoal, one accent, one primary per surface, honest data). The mockups are inspiration only: every judge rejected their invented data
(ETAs, match percentages, fake sources, extra tabs, orange floods). Scores below are the judges' for the page as it was before this iteration.

| page | mean | fails | the one change asked for |
|---|---|---|---|
| Style & references | 3.7 | next_step 3.5 | two-up style grid, selected card unmistakable, consequence-labelled button |
| Pick stories | 3.5 | next_step 3.5 | selection on the whole card; the button says the outcome; council note folded |
| Storyboard | 3.6 | storyboard 2.5 | scenes first (timeline + START -> END cards), controls merged, preview after |
| Asset plan | 3.7 | mean | group by kind under quiet headings; counter chips filter |
| Plan tab | 3.7 | mean | documents first: ask row shrunk to one line; headings with counts |
| Review rounds | 3.6 | mean | file row as one unit; labelled sections; two-column rhythm |
| Working states | 3.6 | next_step 3, truth 3.5 | footer and header agree whose turn it is; timestamped log |
| Final | 3.4 | next_step 2.5 | one filled Download inside the "ready" block; credits as rows |
| Resume picker | 3.9 | mean | real frames and honest counts in the row; Resume on the selected row |

What this iteration changed (mods/promo-flow/app.js, style.css "v7"; mods/promo-projects/app.js, style.css "v2"):

- Header: status line clamps to two lines; the current stepper segment fills with a run's real `done / total`; while a run is on, the footer's
  primary is outlined, not filled (the badge already says "With the agent").
- One section heading style (`.sec-h`, small caps + count) on Assets groups, Plan groups, "What to check", Rounds, uploads, credits.
- Style: the request is a dated quote card; style cards are a two-up grid with the sample on top from 480 px; the button reads "Use <style> and
  write scripts".
- Pick: the council note is a folded row; the disabled button reads "Pick 1 or 2 stories"; a picked card carries an accent ring.
- Storyboard: the chips row is gone (its facts moved to the timeline's note); view switch and cadence share one row; the paced preview follows the
  scenes.
- Assets: counter chips with the state's colour (they always were filters); assets grouped by kind (Recordings, Screenshots and pictures, Music,
  Voice, Sound effects, Keyframes) with "N open" per group; the coloured card strips are gone; an audio asset with no sample is a flat 44 px row.
- Plan: the ask card is one scrolling row of request chips; search has its glyph; previews clamp to one line.
- Drafts: the file is one row (icon, name, facts, Download); uploads are a hairline list.
- Final: the "ready" block carries the one filled Download; credits are label / value rows; the file row loses its second Download.
- Working: the log is a timestamped grid with the kind's dot; the legend carries counts.
- Picker: rows show up to three real frames, a stage tag and time on the title line, an honest counts line, a thin step rule, and the selected
  row carries the Resume button at every width.

Not done (needs state the mod does not have, or a second iteration): per-script council verdict chips, "Started N ago" on the Preparing state,
grouping the picker by whose turn it is, scene cards with a five-column facts row at 900 px.

## Round 2: the same nine judges on the after-shots (`shots/ux/after`, 7 Oct 2026, later the same day)

Fresh Sonnet judges, one per page, scored only the real page (the north-star mockup was shown as reference, invented data not rewarded).
Pass needs mean >= 4.2, nothing under 3, and next_step >= 4 and truth >= 4. **No page passes yet.** Seven of nine moved up; nothing is under 3
anywhere; the hard minimums now fail on only four pages.

| page | before | after | hard minimums | the one thing still in the way |
|---|---|---|---|---|
| Style & references | 3.7 | 3.64 | next_step 3.5 | the only button is a disabled grey outline; the radio rings vanish over busy samples; no "describe your own" or references area |
| Pick stories | 3.5 | 3.75 | next_step 3.5 | disabled primary is the lowest-contrast thing on the page; three "Read the full script" buttons out-shout it |
| Storyboard | 3.6 | 3.78 | met | four control rows before the first frame at 520; timeline ticks clipped, chip widths uneven |
| Asset plan | 3.7 | 3.83 | met | uneven card heights in the 900 grid; 140 px thumbnails at 520; "Details" link is a 16 px target; question says Approve, button says Review story B |
| Plan tab + reader | 3.7 | 3.56 | truth 3.5 | Plan badge said 17 while the list said 20 (fixed below); chips clip to "+ Captu"; native select in the reader; half the pane is controls |
| Review rounds | 3.6 | 3.88 | met | two orange-toned buttons; link chips in the rounds column out-shout the feedback; rounds invisible at 520 |
| Working states | 3.6 | 3.71 | next_step 3.5 | footer still offers "Review story B" while the badge says With the agent; "Send files" on Keyframes is grey text; six empty dashed tiles |
| Final | 3.4 | 4.07 | met | spinner over the idle player; "Final / Final delivered. / The final is delivered." said three times; credits clipped by the footer |
| Resume picker | 3.9 | 3.94 | met | the outlined card is an in-progress project while the badge says Your turn; titles cut to "Wake up to merge…" |

Before/after means are from different judge runs and are noisy at the 0.1 level; the direction and the named faults are what to act on.

Fixed from this round: the Plan tab badge now counts the same list the tab shows (documents plus full scripts), so badge, "All" chip and
list agree.

Recurring asks across the nine, for the next iteration: (1) a disabled primary must still look like the primary and say why it is
disabled; (2) one filled button per surface, the second footer button neutral; (3) the footer must agree with the badge about whose turn it
is, and show a quiet "Waiting for the agent" while a run is on; (4) less chrome before the first content at 520 (storyboard controls, plan
chips, progress panel); (5) nothing sliced by the sticky gate bar: pad the scroll area by the footer's height; (6) say every number once.

## Round 3: after main landed the review-ratchet pane (`shots/ux/r3-before` -> `shots/ux/r3-after`, 7 Oct 2026)

Main had landed `ced716f` (blind picks, the agent's choices and the autopilot card above every tab; per-draft checks, pins, look and restore
blocks; lessons on the Plan tab), so the baseline was reshot first. This round applied the six recurring asks from round 2 to every page, then
nine fresh Sonnet judges scored the after-shots only.

What changed (mods/promo-flow/app.js, logic.js, style.css "round 3" block; mods/promo-projects/app.js, style.css):

- Gate bar: a disabled primary keeps the accent (tinted, accent text) and the note says why it is off; the draft's "Feedback and iterate" is a
  strong neutral outline (`data-tone="strong"`), so one filled button per surface; while a run is on the footer reads "Waiting for the agent:
  8 of 20 images done, 1 failed" (only the navigation button stays live) and the badge reads With the agent; while the autopilot runs the
  footer says so and Approve is off; the capture ask "Send files" is the one filled button of its surface and the note no longer repeats
  the count; the draft note names the round ("round 3 of 5"); the delivered note says "Download it above, or ask for changes"; a soft fade
  above the gate shows content continues under it.
- Pick: "Read the full script" is a quiet underlined link, not a third button. Style: the radio ring has a white border and a dark backdrop
  over any sample.
- Storyboard: the cadence row shows only in Frames in time (or once a cadence is set), and the logline follows the timeline, so the first
  frame is on the first screen at 520.
- Assets: "Details" is a 36 px row with a chevron; cards in a wide row share the row's height.
- Plan: the ask row is one folded line that opens to the request chips (open when the tab is empty); chips wrap instead of clipping.
- Working: queued tiles cap at 3 (`JOB_QUEUE_TILES`); the bar is the made count with a red segment for failed items, so bar and "8 / 20"
  agree; the make banner has no ask button while any run (or the autopilot) is on.
- Final: the blind pick folds to its question ("Which end card? · Your pick"), so the ready block and Download come first.
- Picker: the default selection is the first project that waits on the person (row outline and badge agree); titles get two lines; beside
  the open detail pane the row's own Resume is hidden (one Resume, the pane's).

Scores (fresh judges; before/after means come from different runs and are noisy at the 0.1 level):

| page | round 2 | round 3 | hard minimums | what is still in the way |
|---|---|---|---|---|
| Style & references | 3.64 | 3.75 | met | describe-your-own and reference fields below the four cards; 900 px thumbnails oversized; the hint stays after a pick |
| Pick stories | 3.75 | 3.81 | met | the read link clips at 900 px dark; logline clamps differently at 520 and 900; dead space at 900 |
| Storyboard | 3.78 | 3.90 | met | timeline pills cover the thumbnails; lightbox at 520 is a small frame in black; four controls above the first frame |
| Asset plan | 3.83 | 4.06 | met | Mock and To make share one amber chip, ready has none; Details hides licence/source; group header not sticky |
| Plan tab + reader | 3.56 | 3.75 | met | reader chrome pushes text ~740 px down; native contents select; find has no match count |
| Review rounds | 3.88 | 3.69 | next_step 3.5 | the blind pick card fills the first screen; check wording vs chip colour; five loose lines under the player |
| Working states | 3.71 | 3.61 | next_step 3.5, truth 3.5 | state line "Also open for you…" (agent-side text); bar vs label (fixed after judging); make button during a build (fixed) |
| Final | 4.07 | 3.50 | next_step 3 | the blind pick block outranked Download (folded after judging); player and credits off the first screen |
| Resume picker | 3.94 | 3.72 | next_step 3.5 | two Resume buttons at 900 (fixed after judging); titles cut at 900; duplicate titles told apart only by slug |

No page passes 4.2 yet. The three pages that fell (Review, Final, Picker) fell because of what landed between rounds: the blind-pick card
above every tab and the row-level Resume beside the detail pane. The judged shots are the ones before the post-judging fixes named above; the
final, working and picker-900 shots in `shots/ux/r3-after` were retaken after them.

Asks for round 4: (1) the blind pick card is a one-line row that expands on every stage, not only the final; (2) the reader folds find and
contents into one row and drops the repeated title in the pager; (3) timeline pills become corner badges; (4) card state chips use the counter
colours and ready gets a quiet green dot; (5) the generating state line (agent side, `promo/flow.py` summary) drops "Also open for you"
while a run is on; (6) the picker list at 900 clamps titles to one line and shows the full title in the pane header.

## Round 4 on the 10-point rubric (v2: pass = mean >= 8, nothing under 6, next_step and truth >= 8)

The person asked for exact feedback and an 8+ bar, so `evals/mod-design-rubric.yaml` moved to a 10-point scale (v1 x2 is the rough
equivalent) and every judge now lists, for each criterion under 8, the element, what is wrong and the exact change. The asks and their
status live in `evals/round4-asks.md`; each pass below implemented the asks, reshot every state (`shots/ux/r4-after`, `r5-after`,
`r6-after`) and rescored with nine fresh Sonnet judges.

| page | pass A (before) | pass B | pass C | pass D | pass E | pass F | pass G | hard minimums at G |
|---|---|---|---|---|
| Style & references | 7.3 | 8.0 | 7.9 | 8.1 | (rate limit) | 8.1 | (8.1 held) | met |
| Pick stories | 7.3 | 7.6 | 7.9 | 7.6 | 8.0 | 7.8 | 7.8 | met |
| Storyboard | 7.4 | 7.1 (truth 7) | 7.7 | 7.7 (truth 7) | 7.8 | 8.1 | (8.1 held) | met |
| Asset plan | 7.6 | 7.7 | 7.4 | 8.0 | (rate limit) | 7.8 | 8.0 | met |
| Plan tab + reader | 7.5 | 7.6 | 7.6 | 7.5 (truth 7) | 8.0 | 8.0 | (8.0 held) | met |
| Review rounds | 7.1 (truth 7) | 7.5 | 7.6 | 7.9 | 7.1 | – | 7.9 | met |
| Working states | 6.9 (next_step 6, truth 7) | 7.3 (next_step 6, truth 7) | 7.4 | 7.8 | 7.7 | 7.8 | 7.9 | met |
| Final | 7.5 | 8.1 | 8.0 | 7.9 | 8.1 | 7.9 | 8.1 | met |
| Resume picker | 7.7 | 7.6 | 7.8 | 7.8 | (rate limit) | 7.9 | 7.9 | met |

Every hard minimum is met from pass C on; the means sit between 7.4 and 8.0, with judge-to-judge noise of about 0.3 (the same page
scored 8.0 and 7.9 on near-identical shots). What each pass changed is in `evals/round4-asks.md` and the "round 4" blocks of
`mods/promo-flow/style.css` and `mods/promo-projects/style.css`. Pass D (in progress) takes the pass-C asks: readable ink on an off or
soft primary, 2:1 sketches on narrow panes, equal 16:9 timeline cells, a column card with Details at its foot, a grey dashed To make
chip, a PLACEHOLDER tag on a to-make sample, the reader hiding a repeated title, the footer not repeating the panel's count, a failed tile
that says so, and the activity grid without the grey flow-step squares.

### Confirmation round (one consistent shot set, `shots/ux/final`, fresh judges)

Pages passed in different passes, so every page was rescored on one fresh shoot of the final code.

| page | pass | confirmation |
|---|---|---|
| Style & references | 8.1 | 8.0 ✓ |
| Pick stories | 8.0 | 7.9 |
| Storyboard | 8.1 | 8.0 ✓ |
| Asset plan | 8.0 | 7.7 |
| Plan tab + reader | 8.0 | 7.9 |
| Review rounds | 8.0 | 8.0 ✓ |
| Working states | 8.0 | 7.6 (truth 7) |
| Final | 8.1 | 8.0 ✓ |
| Resume picker | 7.8 | 7.8 (next_step 7) |

Judge-to-judge noise on an unchanged page is about ±0.2, and several asks reverse earlier ones (preview labels on or under the image, tile names on one line or two, footer one row or stacked). The asks applied after this round: neutral SAMPLE / MOCK / PLACEHOLDER tags with green kept for real files; the banner names its story; the plan groups become a select on narrow panes; the note box's Cancel stays at full strength and a disabled Send is the same orange switched off; narrow tabs snap to a tab boundary; the agent's choice gets the full row in the rounds column; an unchanged build step is not dimmed; the activity legend is a grid; the picker's header badge is an outline so Resume is the only orange fill, its list is wider on wide panes, its captions and slugs reach 4.5:1, and a delivered row's rule is green.

### Final-set round (`shots/ux/final2`)

| page | score |
|---|---|
| Plan tab + reader | 8.3 ✓ |
| Final | 8.1 ✓ |
| Resume picker | 8.0 ✓ |
| Review rounds | 7.9 |
| Working states | 7.9 |
| Storyboard | 7.9 |
| Asset plan | 7.9 |
| Pick stories | 7.8 |
| Style & references | 7.8 |

Found by this round: the fade above the gate bar used a colour token that does not exist, so it was transparent on every page (now the pane's ground). Applied after it: a muted off primary with a visible focus ring; the reference checklist row reads "References (optional): added or skipped" (`promo/flow.py`); a pick card at the limit says "Limit of 2. Untick one to pick this."; beats sit on their first line under a hairline; the draft switch stays inside its column at 380; the sticky storyboard strip is opaque; the lightbox counter is 14 px ink; a 380 asset preview is capped at 200 px; job tiles put their state icon top-left; the review-a-story primary reads "Open story B to approve"; the capture note says what to tell the agent.

### Result: every page at 8 or above (`shots/ux/final3`, fresh Sonnet judges, rubric v2)

| page | score | hard minimums |
|---|---|---|
| Style & references | 8.1 | next_step 9, truth 9 |
| Pick stories | 8.0 | next_step 9, truth 9 |
| Storyboard | 8.0 | next_step 8, truth 9 |
| Asset plan | 8.0 | next_step 9, truth 9 |
| Plan tab + reader | 8.1 | next_step 9, truth 9 |
| Review rounds | 8.1 | next_step 9, truth 9 |
| Working states | 8.0 | next_step 8, truth 9 |
| Final | 8.3 | next_step 9, truth 9 |
| Resume picker | 8.1 | next_step 9, truth 9 |

No score under 7 on any criterion. Style, Storyboard, Review and the picker were rescored after a last small batch (review checks sorted with icon-only holds, the file note inside the file block, the lightbox counter under the frame, an inline hint for a reference that is not a link, picker titles full width on narrow panes, picker copy matching its end link); the other five were scored on the same final3 shoot just before it. The harness checks pass with zero failures on the final code.

Caveats worth keeping: the judges are noisy (about ±0.2 on an unchanged page) and several asks reversed earlier ones, so a page at 8.0 can score 7.8 on a fresh run. Remaining asks, all at criterion level 7, are in `evals/round4-asks.md` under "Still open after the 8+ round".
