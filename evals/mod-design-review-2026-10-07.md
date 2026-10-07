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
