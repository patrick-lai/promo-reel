# commission-ai promo footage: v1-1080 recapture

- **Build:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main), detached worktree `/workspace/wt-promo-v1-1004`, `vite build` + `vite preview` on 127.0.0.1:6460. No app code changed.
- **Capture:** headless Chrome via Playwright, Playwright clock paused and stepped 1/60 s per frame, CSS/WAAPI animations seeked to virtual time (scripts in `capture/v1-1080/`). Dark theme. Toasts hidden in promo shots (capture CSS, as before).
- **Masters:** `.mov` H.264 lossless (`-qp 0`, yuv444p) 1920x1080 60 fps. `-preview.mp4` H.264 crf 16 yuv420p. Sound off.
- **Framing:** 'full' = 1920x1080 CSS at DPR 1. 'clip' = a CSS rectangle of the normal 1920x1080 CSS layout rendered at deviceScaleFactor 2 and scaled to 1920x1080 output (crisp, pre-framed). For the 4K pass use the same CSS rect at DPR 4 (or full frames at 1920x1080 CSS DPR 2).
- **Cursor:** hidden except shot 10 (capture-overlay arrow that follows the real pointer; headless Chrome draws no OS cursor).

### Shot 3 (night Workshop)
- **File:** `footage/v1-1080/shot-03-night.mov` (lossless H.264 yuv444p) + `shot-03-night-preview.mp4` + poster `shot-03-night-poster.png`
- **sha256 (.mov):** `423c80eb72b76866cef3f2e8421f6cda9d555e032b451048ac607e02cdd87b9e`
- **DPR:** 1
- **Duration:** 9.00 s; **video:** 1920x1080 @ 60 fps, 540 frames
- **URL / route:** `?demo=promo&view=workshop&workshop=fast&workshopHour=22:00`
- **Demo beat:** standalone Workshop page (view=workshop is read in lib/workshopPreview.ts and rendered by main.tsx as WorkshopPreview); promo crew; room 'Office 1956' building 71%
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** full, locked, 9.0 s
- **Notes / Zen checks:** `workshopHour` must be HH:MM: `parseHour` (AmbienceSettings.tsx:63) ignores a bare `22`, so `workshopHour=22` silently gives the normal clock. Readable at 1080: lamps lit, night sky with stars, room and robots clear, header 'Office 1956 · Building · 71% · 14 pieces' legible; not too dark, no brightening. Zen: no '?' bubbles, no amber pill (standalone page has none). One 'zzz' bubble on the sleeping pet cat (nightcap) — a pet, not a robot waiting state. Header bar (Workshop/Portfolio, Live, HD, progress bar) in frame; crop if unwanted. No composer/Access pill in this shot.

### Shot 15 (morning Workshop)
- **File:** `footage/v1-1080/shot-15-morning.mov` (lossless H.264 yuv444p) + `shot-15-morning-preview.mp4` + poster `shot-15-morning-poster.png`
- **sha256 (.mov):** `eafa1cfefcd0067546001ae85856aeee31866fa95384658a24f364f2f0525cc7`
- **DPR:** 1
- **Duration:** 9.00 s; **video:** 1920x1080 @ 60 fps, 540 frames
- **URL / route:** `?demo=promo&view=workshop&workshop=fast&workshopHour=07:00`
- **Demo beat:** standalone Workshop page, promo crew, same room 'Office 1956' building (~71-75%), robots carrying and placing pieces
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** full, locked, 9.0 s
- **Notes / Zen checks:** Morning light: pink/blue dawn sky, sun patches on the floor, lamp still on. `workshopHour=7` (bare) is ignored by parseHour; used `07:00`. Zen: no '?' bubbles, no amber pill. The sleeping pet cat shows a 'zzz' bubble through the clip (pet, not a robot waiting state). Header bar in frame.

### Shot 10
- **File:** `footage/v1-1080/shot-10.mov` (lossless H.264 yuv444p) + `shot-10-preview.mp4` + poster `shot-10-poster.png`
- **sha256 (.mov):** `f449790233c33ecdc3dfe9c2ad5a46c04308fc84ecec687d6ab11249589630a2`
- **DPR:** 1
- **Duration:** 6.20 s; **video:** 1920x1080 @ 60 fps, 372 frames
- **URL / route:** `?demo=promo`
- **Demo beat:** needs-you: PAY-106 Running -> Needs you live at 21.25 s; real click on the card's Allow once at 23.95 s; back to Running at 24.25 s (clip 20.0-26.2 s)
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** full, board zoomed 2 in-app steps (165%) on PAY-106
- **Notes / Zen checks:** Bell, rail 'Needs you · 1 in PAY', '2 need you' header pill and Commander 'Needs you' card light up. Click lands on the hover-revealed 'Allow once' (clip ~3.95 s). After the click the Commander card shows 'Answer Cursor · Reply' for ~0.3 s until the scenario's own timeout resolves PAY-106 (the scenario writes 'Rejected by you / Skip the new package' into the PAY-106 thread; not on screen here). `$1.84` session cost is in the Commander header (top, y<50 px): crop below it. Clicking selects the card, so the board finder shows '4 of 9' from ~4.0 s. Agents on screen: PAY-103 Claude Code logo, PAY-104 Codex logo, PAY-106 Cursor logo ('Answer Cursor' in the Commander card). Commander composer footer shows the amber Access pill = 'Bypass permissions' (the 'Auto-approve' look; it is the default access for new threads, compose.ts:143), bottom-left of the Commander pane; not changed in this take.

### Shot 10 (DPR2 retake, preferred)
- **File:** `footage/v1-1080/shot-10-dpr2.mov` (lossless H.264 yuv444p) + `shot-10-dpr2-preview.mp4` + poster `shot-10-dpr2-poster.png`
- **sha256 (.mov):** `70a27882fdc5ee2bc4d614a3913f85a7e8485c2ed52219ec5e52b961e1600186`
- **DPR:** 2
- **Duration:** 6.20 s; **video:** 1920x1080 @ 60 fps, 372 frames
- **URL / route:** `?demo=promo`
- **Demo beat:** needs-you: PAY-106 Running -> Needs you live at 21.25 s; real click on the card's Allow once at 23.95 s; back to Running at 24.25 s (clip 20.0-26.2 s)
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** 1920x1080 CSS layout at DPR 2, board zoomed 2 in-app steps (165%); capture clip x290 y88 1280x720 CSS -> 1920x1080 px (1.5x pre-framed, native density). Frame = Commander 'Needs you' card (top-left) + Wave 1/2 board with PAY-106 card; bell/rail and $ cost out of frame
- **Notes / Zen checks:** Same beat and timings as shot-10 (clip 20.0-26.2 s; flip 21.25 s = clip 1.25 s; real click on the card's 'Allow once' at 23.95 s = clip 3.95 s; Running again 24.25 s). Hovering the card dims the other cards (app focus effect). Cursor = capture-overlay arrow following the real pointer (enters from bottom-right). No $ figure in frame (the $1.84 Commander header is above y=88). Bell and rail 'Needs you' are outside this frame; use shot-10 (DPR1 full) if they are needed. 'Blocked' wave-2 cards visible (allowed in shot 10). Agents: PAY-103 Claude Code, PAY-104 Codex, PAY-106 Cursor logos.

### Shot 8 (+9)
- **File:** `footage/v1-1080/shot-08.mov` (lossless H.264 yuv444p) + `shot-08-preview.mp4` + poster `shot-08-poster.png`
- **sha256 (.mov):** `38129f55432c82e32785956debfbcdf44306e493de2d6534027439926e8699a8`
- **DPR:** 2
- **Duration:** 9.30 s; **video:** 1920x1080 @ 60 fps, 558 frames
- **URL / route:** `?demo=promo` (PAY-104 node clicked at 9.0 s)
- **Demo beat:** clip = scenario 11.1-20.4 s: Running/Coding (0-2.0 s) -> Verifying/Checks 13.1 s (clip 2.0 s; 'Verifying · Nothing needed from you · Running checks' holds to ~4.9 s = shot 9) -> Pushed 16.0 s (4.9 s, 'In review · Pushed, raising the pull request') -> PR raised #432 18.9 s (7.8 s, 'In review · YOUR MOVE · Review and merge PR #432', PR card #432 Open)
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** 1920x1080 CSS layout at DPR 2; capture clip x960 y0 960x540 CSS -> 1920x1080 px (2x pre-framed, native density)
- **Notes / Zen checks:** Agent shown: **Codex** ('Codex · Board run · Slot 2 · +36 −8'), not Claude. Chips: Planning, Coding, Checks, Pushed, PR raised, Merged (no Review chip until a review lands). Header pill 'In Progress' (correct while running). Use 2.0-4.9 s for shot 9 (Verifying). Full-frame still: shot-08-still-fullframe.png (end state).

### Shot 12
- **File:** `footage/v1-1080/shot-12.mov` (lossless H.264 yuv444p) + `shot-12-preview.mp4` + poster `shot-12-poster.png`
- **sha256 (.mov):** `157a7f970ea317a5e6aa54120228fb0c3337fc9e18e4c80d128625b3f9fa2363`
- **DPR:** 1
- **Duration:** 6.30 s; **video:** 1920x1080 @ 60 fps, 378 frames
- **URL / route:** `?demo=promo` (PAY-104 node clicked at 24.0 s)
- **Demo beat:** clip = scenario 25.2-31.5 s: PAY-104 drawer 'In review' (review beat) -> 'Review thread' clicked at 26.7 s (clip 1.5 s) -> conversation pane shows the reviewer agent's thread for PR #432: 'Approved. Cart summary uses the pricing engine matches the plan, and the diff stays inside src/cart/CartSummary.tsx.' + '1 task approved'; board reflows as PAY-103 merges (28.6 s)
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** full frame DPR1 (see shot-12-dpr2 for the pre-framed 2x take)
- **Notes / Zen checks:** No 'Blockers found', no 'Deep review': this is the promo scenario's own reviewer approval, not the PR Review stage. The PR Review stage on promo PR #432 (Review tab > My open PRs) still shows the generic demo review ('Round refunds per line in cents', Blockers found, Deep review: dev/demoPrReview.ts has one canned finding set for every PR), so a no-blocker Review-stage take is not possible on main. Reviewer agent here is Cursor. Board area shows wave-2/3 cards labelled 'Blocked' (dependency wait) and mid-reflow ghost cards around 3-4 s: frame on the conversation pane. Composer shows the amber Access pill (Bypass permissions).

### Shot 12 (DPR2, preferred)
- **File:** `footage/v1-1080/shot-12-dpr2.mov` (lossless H.264 yuv444p) + `shot-12-dpr2-preview.mp4` + poster `shot-12-dpr2-poster.png`
- **sha256 (.mov):** `6633e773b7f50f93f3c489f435301b2341171783fd55b32b8cb64ff9c2d7d079`
- **DPR:** 2
- **Duration:** 5.50 s; **video:** 1920x1080 @ 60 fps, 330 frames
- **URL / route:** `?demo=promo` + pref conversationWidth=940 (PAY-104 node clicked at 24.0 s; drawer 'Review thread' clicked at 26.6 s)
- **Demo beat:** reviewer thread for PAY-104 / PR #432 right after the click (scenario ~26.9-32.4 s): 'Review pull request #432 for PAY-104...' -> 'Approved. Cart summary uses the pricing engine matches the plan, and the diff stays inside src/cart/CartSummary.tsx.' -> '1 task approved' -> 'Read 1 file'
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** 1920x1080 CSS at DPR 2, conversation pane widened to 940 px via the real resize pref; capture clip x290 y0 960x540 CSS -> 1920x1080 (2x pre-framed). Thread header + messages fill the frame; composer (and its Access pill) out of frame
- **Notes / Zen checks:** SUPERSEDED by the shot-12-dpr2-z179 retake (main 4ccfa5be, Z179 bold fix); don't use this one, it shows raw '**' asterisks. No 'Blockers found', no 'Deep review'. Reviewer agent: Cursor. Mostly static (5.5 s hold). The user message renders the task title with literal '**' markdown asterisks ('**PAY-104: Cart summary uses the pricing engine**') — real app/demo text, not fixed. Companion take shot-12-dpr2-pre.mov (1.40 s, full frame at DPR2 downsampled to 1080): PAY-104 drawer In review just before the click.

### Shot 12 (lead-in)
- **File:** `footage/v1-1080/shot-12-dpr2-pre.mov` (lossless H.264 yuv444p) + `shot-12-dpr2-pre-preview.mp4` + poster `shot-12-dpr2-pre-poster.png`
- **sha256 (.mov):** `3c967a30e4a49a8f80bb730df7b3395c79e93ffd54f8d6bc7283863e4a4c49f3`
- **DPR:** 2
- **Duration:** 1.40 s; **video:** 1920x1080 @ 60 fps, 84 frames
- **URL / route:** `?demo=promo` + pref conversationWidth=940
- **Demo beat:** PAY-104 drawer, 'In review', scenario 25.2-26.6 s, before the 'Review thread' click
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** full frame, 1920x1080 CSS at DPR 2 downsampled to 1920x1080
- **Notes / Zen checks:** SUPERSEDED by the shot-12-dpr2-pre-z179 retake (main 4ccfa5be, Z179 bold fix); don't use this one, it shows raw '**' asterisks. Lead-in only; drawer covers the board. Header pill 'In Progress'.

### Shot 1 + 17 (dusk Workshop)
- **File:** `footage/v1-1080/shot-01-dusk.mov` (lossless H.264 yuv444p) + `shot-01-dusk-preview.mp4` + poster `shot-01-dusk-poster.png`
- **sha256 (.mov):** `16c31f37503b084966af154a00f062b46120cdc8e26833907ac862397d5f63fd`
- **DPR:** 1
- **Duration:** 10.00 s; **video:** 1920x1080 @ 60 fps, 600 frames
- **URL / route:** `?demo=promo&view=workshop&workshop=fast&workshopHour=19:30`
- **Demo beat:** standalone Workshop page, promo crew, room 'Office 1956' building 72-75%, robots carrying/placing pieces; locked 10 s (use one section for shot 1 and another for the shot 17 end card)
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** full, locked, 10.0 s
- **Notes / Zen checks:** Dusk/early-night look: violet-blue sky with stars, lamps lit. Zen: checked every ~2 s plus close-ups: no '?' or '...' robot bubbles, no amber 'robots waiting' pill (the standalone page has no crew pill). The pet cat (nightcap) shows a 'zzz' bubble while sleeping, moving around the room: a pet, not a waiting robot. Header bar (Workshop/Portfolio tabs, Live, HD, progress) at top: crop it.

### Shot 14b
- **File:** `footage/v1-1080/shot-14b.mov` (lossless H.264 yuv444p) + `shot-14b-preview.mp4` + poster `shot-14b-poster.png`
- **sha256 (.mov):** `413c0d48fe5011d6c16a92c2dc62099d7f93ce779caec5f0fdb23ebcf21d68be`
- **DPR:** 1
- **Duration:** 15.00 s; **video:** 1920x1080 @ 60 fps, 900 frames
- **URL / route:** `?demo=promo&pause=1&workshopHour=19:30` + prefs stage ws-pay=workshop
- **Demo beat:** promo held on its first beat (empty board, no agents running); in-app Workshop expanded full screen, Outside view (Shop tier); 1.0-1.8 s Workshop settings popover (Demo controls > 'Finish 5 rooms'); toasts from 1.85 s; 5.5 s Room view > Street: Street promenade glide (city at dusk lights) to 15 s
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** full, 1920x1080 CSS DPR1, locked (in-app camera glide only)
- **Notes / Zen checks:** Zen: no '?' bubbles seen (no agents waiting under pause=1); the crew pill reads 'Caretaker bot building' (neutral, NOT the amber 'robots waiting on you' pill). The 'Your workshop is now a Street' toast fires at 1.85 s but is immediately stacked under a '2 achievements earned · Interior Designer, Home Sweet Home. Unlocks Paris Apartment.' toast, so only its last line peeks out: the notice itself is not legible (real app toast stacking). Settings popover visible 1.0-1.8 s: cut around it. Bottom-left HUD card (Street · Office 1956 · Shell 63% / later 'Street · 5 buildings · 7 rooms in all') and top bar in frame; wallet/mora figures hidden with capture-only CSS (as in v0). Use 7-15 s for the Street glide / 16 centre tile.

### Shot 16 (PR-card payoff)
- **File:** `footage/v1-1080/shot-15-prcard.mov` (lossless H.264 yuv444p) + `shot-15-prcard-preview.mp4` + poster `shot-15-prcard-poster.png`
- **sha256 (.mov):** `03c62c874269dcbcbb2bda786f35e3767a64707c2e0e63aa4d19fd55bfe1a6d7`
- **DPR:** 2
- **Duration:** 9.50 s; **video:** 1920x1080 @ 60 fps, 570 frames
- **URL / route:** `?demo=promo` (scenario clock), PAY-110 node clicked at 59 s to open its drawer
- **Demo beat:** PAY-110 drawer from 61.0 s to 70.5 s: Running -> Checks 62.3 s -> Pushed 63.1 s -> PR raised #438 63.9 s ('YOUR MOVE · Review and merge PR #438') -> Merged 67.5 s; drawer status flips to Done and the Pull request card reads '#438 Merged · PAY-110 Remove legacy pricing module · commission/PAY-110-legacy-pricing -> main · Builds pass · 1 approval · 1 comment'
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** pre-framed DPR2 clip x720 y122 1200x675 CSS (1.6x); in the final frames the PR card spans ~61% of frame width (x~370-993 of 1024 in a scaled check). Header status pill out of frame. Push-in of <=1.2x on the card is enough.
- **Notes / Zen checks:** PR number visible: #438 (PAY-110). Zen: no '?' bubbles, no amber pill, no Blocked cards in frame (left edge shows the Landed column, '8 done'). The drawer still shows an 'Evidence: QA decision not recorded / No QA demo yet' block below the PR card (real app). Hold the end on 8.0-9.5 s (Merged). Capture process crashed after recording on a later optional still (PAY-109 drawer), so this clip was encoded by hand from the same recorded frames with the identical ffmpeg settings; poster = frame 509.

### Shot talk-dag (tight)
- **File:** `footage/v1-1080/talk-dag-tight.mov` (lossless H.264 yuv444p) + `talk-dag-tight-preview.mp4` + poster `talk-dag-tight-poster.png`
- **sha256 (.mov):** `8ee1bb4cf519d1c51a2816a6f791c4718039a8a3dc6f29eaa63a4a2f4b67d334`
- **DPR:** 2
- **Duration:** 6.00 s; **video:** 1920x1080 @ 60 fps, 360 frames
- **URL / route:** `?demo=1&still=1` (Board graph, Full window, Show done, ctrl+wheel zoom to ~180%)
- **Demo beat:** 6 s locked hold on the dependency graph: PAY-101 'Extract pricing engine into a pure module' (Done, Landed, #412) with its edges fanning into PAY-105 'Promo code validation endpoint' and PAY-104 'Cart summary uses the pricing engine' (Backend group, Running); top of 'Design system' group at the bottom edge
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x469 y289 960x540 CSS (2.0x, crisp). Task IDs ~58 px tall in the 1080 output (~32 px at 55% display). No Wave headings in this tight frame (see talk-dag for headings).
- **Notes / Zen checks:** Real ?demo=1 board; graph zoom done with real ctrl+wheel. Clock paused for the hold, so the frame is still (no pan). Zen: no '?' bubbles, no amber pill, no Blocked card in frame (the demo=1 board does have Needs you / Blocked / agent-quota cards elsewhere, all out of frame). The card's ticket/PR/video icon buttons show on PAY-101 and PAY-104 (real app UI).

### Shot talk-dag
- **File:** `footage/v1-1080/talk-dag.mov` (lossless H.264 yuv444p) + `talk-dag-preview.mp4` + poster `talk-dag-poster.png`
- **sha256 (.mov):** `05750c8770292cf9a74473f71cec9b6ae6db3b21b55bc862f4bc506368b9b5b4`
- **DPR:** 2
- **Duration:** 6.00 s; **video:** 1920x1080 @ 60 fps, 360 frames
- **URL / route:** `?demo=1&still=1` (Board graph, Full window, Show done, ctrl+wheel zoom to ~180%)
- **Demo beat:** 6 s locked hold on the plan DAG: 'Landed · Merged and closed' (PAY-102 Done #413, PAY-101 Done #412) with PAY-101's edges into Wave 1 (PAY-105 Verifying, PAY-104 Running); 'Wave 1 · 6 tickets' and 'Wave 2 · Starts after…' headings; Wave 2 cards (PAY-109, PAY-107) cut at the right edge
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x369 y200 1264x711 CSS (1.52x, crisp). Task IDs ~44 px tall in the 1080 output (~24 px at 55% display), meets the brief. PAY-103 sits below the frame.
- **Notes / Zen checks:** Real ?demo=1 board; zoom via real ctrl+wheel; clock paused for the hold (still frame). Zen: no '?' bubbles, no Blocked card in frame; NOTE the Wave 1 header sub-line reads '2 running · 2 need you · 2 queued' with a small amber dot (header text, not the Workshop amber pill). Use talk-dag-tight for an even closer PAY-101 -> PAY-104 edge.

### Shot 4
- **File:** `footage/v1-1080/shot-04.mov` (lossless H.264 yuv444p) + `shot-04-preview.mp4` + poster `shot-04-poster.png`
- **sha256 (.mov):** `cd075dd520a0a8a1dfa214ede538562d7d7419e83160050da0d8986cd6d8053e`
- **DPR:** 2
- **Duration:** 8.40 s; **video:** 1920x1080 @ 60 fps, 504 frames
- **URL / route:** `?demo=promo` (scenario 0-8.4 s)
- **Demo beat:** Empty Checkout Revamp board ('No tickets yet') -> the plan lands and cards pop in by wave: Wave 1 (PAY-103 Design tokens, PAY-104 Cart summary, PAY-105 Promo code, PAY-106 Localized price display) ~3.0-4.5 s, then Wave 2 (PAY-107/108/109), Wave 3 (PAY-110) and 'Later · Plan more' with dependency edges by ~5.8 s; run starts ~6.2 s ('2 running · 2 queued'), PAY-103 and PAY-104 go Running
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Pre-framed clip x800 y300 1060x596 CSS (1.81x) on the board area; leaves room for a <=1.2x push-in.
- **Notes / Zen checks:** Zen: no '?' bubbles, no amber pill. NOTE: from ~5.5 s the Wave 2/3 cards show the real 'Blocked' dependency state (padlock + 'after PAY-103' etc.) until wave 1 lands; it is how the real app shows queued dependent tickets. If Blocked must not appear, use 0-5.4 s (empty board -> Wave 1 cards -> Wave 2 headings popping in). Cards briefly overlap during the pop-in animation at ~4.5 s (real layout animation).

### Shot 11 (all 8 cards)
- **File:** `footage/v1-1080/shot-11-all8.mov` (lossless H.264 yuv444p) + `shot-11-all8-preview.mp4` + poster `shot-11-all8-poster.png`
- **sha256 (.mov):** `b2ecbd2d6c349f04b74a6198a6a0880d3732ea8088a4fe53e2c0e85a62cae55d`
- **DPR:** 2
- **Duration:** 5.00 s; **video:** 1920x1080 @ 60 fps, 300 frames
- **URL / route:** `?demo=promo` (scenario clock to 72.6 s, run complete)
- **Demo beat:** 5 s locked hold on the finished board: 'Landed · Merged and closed' column with all 8 cards Done + 'Later · Plan more' card
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x106.9 y204.8 1483.4x834.4 CSS (1.29x), union of the 8 cards fitted to 16:9; encoded 1920x1080 (lanczos from 1919x1079 rounding).
- **Notes / Zen checks:** Run complete (scenario 72.6 s+), Full window, Show done, Fit to screen. All 8 cards in the Landed column, every one reads 'Done': PAY-103 Design tokens (Claude, PR #431), PAY-104 Cart summary (Codex, #432), PAY-105 Promo code (Claude, #433), PAY-106 Localized price display (Cursor, #434), PAY-107 Checkout theming (Codex, #435), PAY-108 Express checkout (Claude, #436), PAY-109 Order confirmation email (Cursor, #437), PAY-110 Remove legacy pricing (Codex, #438). Agent logos: Claude x3, Codex x3, Cursor x2, so all 3 agent logos show. Each card's PR chip reads 'Pull request #43x merged' in its accessible label; the chip shows the PR number (no separate 'Merged' word on the card). LEGIBILITY: in the 1080 frame all 8 cards are in frame and readable: card count, 'Done' labels, IDs and titles (IDs/'Done' ~9-10 px cap height, titles ~11 px). The agent logos are small (~14 px squares) but identifiable: Claude orange, Codex teal, Cursor dark. Avoid more than about 1.2x push-in. Zen: no '?' bubbles, no amber pill, no Blocked cards. The header with the counts is above the frame (see shot-11).

### Shot 11 (header counts)
- **File:** `footage/v1-1080/shot-11.mov` (lossless H.264 yuv444p) + `shot-11-preview.mp4` + poster `shot-11-poster.png`
- **sha256 (.mov):** `740e9e3e2054667c7fdfa3b8cde16227104401d10b369ce8af61c572d3e87acc`
- **DPR:** 2
- **Duration:** 3.00 s; **video:** 1920x1080 @ 60 fps, 180 frames
- **URL / route:** `?demo=promo` (scenario clock to 72.6 s, run complete)
- **Demo beat:** 3 s locked hold: board header 'All done · Plan next' pill + '8 in this run · 8 landed', with the top of the Landed column (PAY-103/104/105 Done, PAY-106 partly)
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x10 y45 960x540 CSS (2.0x, crisp).
- **Notes / Zen checks:** Run complete (scenario 72.6 s+), Full window, Show done, Fit to screen. Header reads exactly 'All done · Plan next' and '8 in this run · 8 landed'. Visible cards: 3 whole + 1 partial (PAY-103 Claude #431, PAY-104 Codex #432, PAY-105 Claude #433, PAY-106 Cursor partial), all 'Done'. Large empty dotted canvas on the left of the frame (real layout under Fit). Replaces the earlier plan for a 62-74.5 s landing take: frame capture of the full DPR2 board ran at 5-10 s per frame, so only the run-complete holds were recorded.

### Shot 11 (List view)
- **File:** `footage/v1-1080/shot-11-list.mov` (lossless H.264 yuv444p) + `shot-11-list-preview.mp4` + poster `shot-11-list-poster.png`
- **sha256 (.mov):** `4e6f10845ed1ba842d95957de8ebf388559657895801445f0745832fca52bfbe`
- **DPR:** 2
- **Duration:** 5.00 s; **video:** 1920x1080 @ 60 fps, 300 frames
- **URL / route:** `?demo=promo` (run complete) -> real click on the board's 'List' toggle
- **Demo beat:** 5 s locked hold: List view, section 'Done 8', 8 rows PAY-103...PAY-110 with titles, PR numbers #431-#438 and agent logos at the right edge; header 'All done · Plan next · 8 in this run · 8 landed'
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2, full frame 1920x1080 CSS (scale 1; the row union is full width). Rows occupy the top ~40% of the frame.
- **Notes / Zen checks:** Run complete (scenario 72.6 s+), Full window, Show done, Fit to screen. Rows (text + logo): PAY-103 Claude, PAY-104 Codex, PAY-105 Claude, PAY-106 Cursor, PAY-107 Codex, PAY-108 Claude, PAY-109 Cursor, PAY-110 Codex. Text is small at full frame (row text ~10 px cap height), and the logos are tiny (~12 px) at the far right. Crop/push in the edit if used. Zen: clean.

### Shot 16 (PR card, tight)
- **File:** `footage/v1-1080/shot-16-prcard-tight.mov` (lossless H.264 yuv444p) + `shot-16-prcard-tight-preview.mp4` + poster `shot-16-prcard-tight-poster.png`
- **sha256 (.mov):** `fbf04306c307a88c49ab907392cc83abaca62931b661d1e2dc609cc539e41d1a`
- **DPR:** 2
- **Duration:** 9.50 s; **video:** 1920x1080 @ 60 fps, 570 frames
- **URL / route:** `?demo=promo` (scenario clock), PAY-110 node clicked at 59 s to open its drawer; record 61.0-70.5 s
- **Demo beat:** Same beat as shot-15-prcard: PAY-110 drawer, Running -> Checks 62.3 s -> Pushed 63.1 s -> PR raised #438 63.9 s -> Merged 67.5 s, hold to the end (9.50 s). Final: Pull request card '#438 [Merged] · PAY-110 Remove legacy pricing module · commission/PAY-110-legacy-pricing -> main · Builds pass · 1 approval · 1 comment'
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x1130 y246 776x436.5 CSS (16:9), scale 2.474x, output 1920x1080 60 fps lossless. Card measured at ~732 CSS px wide (not ~584), so a 720 or 760 clip cannot hold the full card with a margin; 776 is the smallest that does (about 22 CSS / 55 output px each side). The card sits centred, at output x 55-1865, y ~385-690.
- **Notes / Zen checks:** Measured on the 1920 frame at 9.0 s: 'Merged' badge cap height (M) 18 px (y 432-449); badge text box 92x23 px. PR title cap height (P) 24 px, title line with descenders 32 px. 'Builds pass' cap height (B) 22 px, chip text line with icon 30 px. '#438' and 'Open' are also in frame. Before 63.9 s the same area shows 'No pull request yet' (lower in frame because the status block is taller then). Zen: no '?' bubbles, no amber pill, no Blocked cards. Keep shot-15-prcard as the wider alternative.

### Shot 8 (DPR2, stepper)
- **File:** `footage/v1-1080/shot-08-dpr2.mov` (lossless H.264 yuv444p) + `shot-08-dpr2-preview.mp4` + poster `shot-08-dpr2-poster.png`
- **sha256 (.mov):** `8b6b2e3bdc72764f849a96562bf1008c356ac93e8878e95fad544eadb7bce352`
- **DPR:** 2
- **Duration:** 9.30 s; **video:** 1920x1080 @ 60 fps, 558 frames
- **URL / route:** `?demo=promo` (scenario clock), PAY-104 node clicked at 9.0 s to open its drawer; record 11.1-20.4 s
- **Demo beat:** PAY-104 (Codex) drawer: Running/Coding -> Verifying · Checks 13.1 s ('Nothing needed from you. The agent is on it · Running checks') -> In review · Pushed 16.0 s ('YOUR MOVE · Review the change') -> PR raised #432 18.9 s ('Review and merge PR #432', Review PR button; Pull request card '#432 Open')
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x1000 y10 900x506.25 CSS (2.13x). The whole stepper (Planning · Coding · Checks · Pushed · PR raised · Merged) is in frame for the full take, with the status title above and the 'Codex · Board run · Slot 2 · +36 -8' line below, so the S05 push-in on the stepper has room.
- **Notes / Zen checks:** Zen: no '?' bubbles, no amber pill, no Blocked card. The drawer header shows the Jira pill 'In Progress' (demo data, correct for an open ticket). The 'Queue a nudge for its next turn' composer line shows under Running (0-2 s). Left edge shows a sliver of the board (Wave headings). Full-frame still: shot-08-dpr2-still-fullframe.png.

### Shot 14b (dusk retake)
- **File:** `footage/v1-1080/shot-14b-dusk.mov` (lossless H.264 yuv444p) + `shot-14b-dusk-preview.mp4` + poster `shot-14b-dusk-poster.png`
- **sha256 (.mov):** `8cf012f8ad40699aad33ff85c24b13377d4a4c5bdd083abdb942f26a086c2125`
- **DPR:** 1
- **Duration:** 8.50 s; **video:** 1920x1080 @ 60 fps, 510 frames
- **URL / route:** `?demo=promo&pause=1&workshopHour=19:30` + prefs stage ws-pay=workshop (time of day: 19:30 dusk, same as shot-01-dusk)
- **Demo beat:** In-app Workshop expanded, Outside view at 19:30 dusk; 1.0 s Workshop settings, 1.7 s Demo controls > Finish 5 rooms; 1.85 s 'Your workshop is now a Street · Pirate Cabin is finished and standing on the map' toast, then the '2 achievements earned' toast stacks on top at ~2.0 s; ~2.5 s the earned toast is closed with its own close (x) button by a real mouse hover + click. The Street notice then reads clearly ~2.7-4.2 s. 4.2 s Room view > Street; street glide to 8.5 s (~4 s tail)
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 1, full 1920x1080, locked.
- **Notes / Zen checks:** VERIFIED: the achievements pop-up was closed with its own close (x) button at ~2.5 s (log: 'close btn {x:1877,y:111,16x16} Close toast'; the only toast left afterwards is 'Your workshop is now a Street · Pirate Cabin is finished and standing on the map'). Street notice clear ~2.7-4.2 s. TAIL: the Street starts at 4.2 s and the clip ends at 8.5 s (4.3 s of street); for a ~2 s tail cut at ~6.3 s. TIME OF DAY: workshopHour=19:30 (dusk), the same as shot 01. CAVEATS (real app behaviour): (1) Clicking the toast's close button also collapses the full-screen Workshop back into the app layout, so from ~2.7 s the frame shows the app shell: sidebar, Commander starter cards with '$1.84' in its header, and the Workshop in the right pane. (2) The Street/town view renders bright, with lit windows, even at 19:30, so it still jumps from the dark-blue dusk Outside sky to a bright street; workshopHour does not darken the town view. A retake that re-expands the Workshop with a real click after closing the toast (shot-14b-dusk-r2) is queued. Wallet/mora figures hidden with capture CSS as before. Crew pill 'Caretaker bot building' (neutral). No '?' bubbles.

### Shot 12 (DPR2 retake, replaces shot-12-dpr2)
- **File:** `footage/v1-1080/shot-12-dpr2-z179.mov` (lossless H.264 yuv444p) + `shot-12-dpr2-z179-preview.mp4` + poster `shot-12-dpr2-z179-poster.png`
- **sha256 (.mov):** `c5c20554b03a321d6a432857d60956aa8d86d706c0d391e1c6632af89298f5cb`
- **DPR:** 2
- **Duration:** 5.50 s; **video:** 1920x1080 @ 60 fps, 330 frames
- **URL / route:** `?demo=promo` with conversationWidth=940 pref; PAY-104 drawer -> real click on 'Review thread' at 26.6 s (served from a vite build of main 4ccfa5be)
- **Demo beat:** Same route and beat as shot-12-dpr2: reviewer (Cursor) thread 'Review: Cart summary uses the pricing engine · PR raised'. Request pill 'Review pull request #432 for PAY-104: Cart summary uses the pricing engine.'; request card with 'PAY-104: Cart summary uses the pricing engine.' in bold, 'From CommissionAI'; 'Approved. Cart summary uses the pricing engine matches the plan, and the diff stays inside src/cart/CartSummary.tsx.'; '1 task approved · 1 update'; 'Read 1 file'
- **Commit:** `4ccfa5be580eb3dbbaf8cb1138b0e4f55f544636` (main)
- **Framing:** DPR 2. Clip x290 y0 960x540 CSS (2.0x) on the widened conversation pane, the same as the old take.
- **Notes / Zen checks:** REPLACES shot-12-dpr2-v1080. Checked for '**': none in the pill or the card (Z179 renders the bold). A DOM scan for leaf text containing '**' returned [] at record time, and the frames were checked visually. Zen: no 'Blockers found', no 'Deep review', no '?' bubbles, no amber pill. Commit 4ccfa5be580eb3dbbaf8cb1138b0e4f55f544636 (main, Z179 #95).

### Shot 12 lead-in (DPR2 retake, replaces shot-12-dpr2-pre)
- **File:** `footage/v1-1080/shot-12-dpr2-pre-z179.mov` (lossless H.264 yuv444p) + `shot-12-dpr2-pre-z179-preview.mp4` + poster `shot-12-dpr2-pre-z179-poster.png`
- **sha256 (.mov):** `51a20bf39052e2a665c9ba020df1cd17ca2da1557d75d90e8279af6ac818b6e0`
- **DPR:** 2
- **Duration:** 1.40 s; **video:** 1920x1080 @ 60 fps, 84 frames
- **URL / route:** `?demo=promo` with conversationWidth=940 pref (main 4ccfa5be build)
- **Demo beat:** PAY-104 drawer before the Review thread click (25.2-26.6 s): 'In review · YOUR MOVE · Review and merge PR #432', stepper at PR raised, Pull request card '#432 Open'
- **Commit:** `4ccfa5be580eb3dbbaf8cb1138b0e4f55f544636` (main)
- **Framing:** DPR 2, full frame (3840x2160 rendered, downscaled to 1920x1080).
- **Notes / Zen checks:** REPLACES shot-12-dpr2-pre-v1080. Jira pill reads 'In Review'. Commander and rail on the left (rail: PAY-103 PR raised #431, PAY-104 PR raised #432, PAY-106 Coding). Zen: clean.

### Shot 14b (dusk retake 2, preferred)
- **File:** `footage/v1-1080/shot-14b-dusk-r2.mov` (lossless H.264 yuv444p) + `shot-14b-dusk-r2-preview.mp4` + poster `shot-14b-dusk-r2-poster.png`
- **sha256 (.mov):** `91cd3b337c1fa9b16ed037f65749591c37e8a61a1822200059762b55fb5eef5e`
- **DPR:** 1
- **Duration:** 7.50 s; **video:** 1920x1080 @ 60 fps, 450 frames
- **URL / route:** `?demo=promo&pause=1&workshopHour=19:30` + prefs stage ws-pay=workshop (time of day: 19:30 dusk, same as shot-01-dusk)
- **Demo beat:** Workshop full screen, Outside at 19:30 dusk; 1.0 s Workshop settings, 1.7 s Demo controls > Finish 5 rooms; 1.85 s 'Your workshop is now a Street · Pirate Cabin is finished and standing on the map'; ~2.0 s the '2 achievements earned' toast stacks on top; ~2.5 s it is closed with its own close (x) button (real mouse hover + click). That collapses the Workshop, which is re-expanded with a real click on 'Expand workshop' ~2.9 s (scene reload skeleton until ~3.5 s). ~3.6-4.6 s full-screen dusk Outside with the Street notice alone and fully legible (top right); 4.6 s Room view > Street; street glide to 7.5 s
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 1, full 1920x1080, locked.
- **Notes / Zen checks:** TIME OF DAY: workshopHour=19:30 (dusk). VERIFIED: achievements pop-up closed via its close button (log 'close btn ... Close toast'; only the Street toast left), Workshop stays full screen except the 2.7-3.5 s collapse/re-expand flicker (cut it: use 0-2.5 s, then 3.6-7.5 s). TAIL: 2.9 s of street (4.6-7.5 s). No app shell or '$' after 3.6 s. CAVEAT (real app): the Street/town view still renders bright with lit windows at 19:30, so the sky still jumps from the dark-blue Outside dusk to a bright street; workshopHour does not darken the town view. Crew pill 'Caretaker bot building' (neutral); no '?' bubbles; wallet/mora hidden via capture CSS as before.

### Shot talk-dag (wide, talk-show beat 3)
- **File:** `footage/v1-1080/talk-dag-wide.mov` (lossless H.264 yuv444p) + `talk-dag-wide-preview.mp4` + poster `talk-dag-wide-poster.png`
- **sha256 (.mov):** `a8a49c682e5c476e75d0edc353fc79431197a97f355dcb577a2cba43782ac1d4`
- **DPR:** 2
- **Duration:** 6.00 s; **video:** 1920x1080 @ 60 fps, 360 frames
- **URL / route:** `?demo=1&still=1` (Board graph, Full window, Show done, ctrl+wheel zoom to ~180%), same board state as talk-dag-tight
- **Demo beat:** 6 s locked hold: PAY-101 'Extract pricing engine into a pure module' (Done, #412) with its two edges into PAY-105 'Promo code validation endpoint' (Verifying, API group) and PAY-104 'Cart summary uses the pricing engine' (Running, Backend group); PAY-102 (Done, #413) partly visible at the top left
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x589 y277 996x560 CSS (16:9), scale 1.928x. PAY-101, the whole PAY-104 card (full title on 2 lines) and the whole PAY-105 card (ID + title) are in frame. PAY-102's ID line is cut at the top edge.
- **Notes / Zen checks:** Measured on the 1920 poster (3.0 s): task ID cap height 29 px (PAY-101 / PAY-104 / PAY-105, glyph rows incl. antialias), title cap height 33 px ('C' of 'Cart summary', 'E' of 'Extract'), title line incl. descenders 43 px. All of these beat the >=20 px target. Clock paused for the hold (still frame). Zen: no '?' bubbles, no Blocked cards, no amber pill in frame.

### Shot 4 (DPR2 plan DAG hold)
- **File:** `footage/v1-1080/shot-04-dpr2.mov` (lossless H.264 yuv444p) + `shot-04-dpr2-preview.mp4` + poster `shot-04-dpr2-poster.png`
- **sha256 (.mov):** `b59a775403aec736f1ea4f5f781abe9313bfef624d34c95cabb3c88cfe842e0f`
- **DPR:** 2
- **Duration:** 6.00 s; **video:** 1920x1080 @ 60 fps, 360 frames
- **URL / route:** `?demo=1&still=1` (Board graph, Full window, Show done, ctrl+wheel zoom to ~180%), the same board state as talk-dag / talk-dag-tight
- **Demo beat:** 6 s locked hold on the plan DAG: 'Landed · Merged and closed' with PAY-102 (Done, #413) and PAY-101 (Done, #412); PAY-101's edges into Wave 1: PAY-105 'Promo code validation endpoint' (Verifying, API) and PAY-104 'Cart summary uses the pricing engine' (Running, Backend). 'Wave 1 · 6 tickets · 2 running · 2 need you · 2 queued' heading; Wave 2 column (PAY-109, PAY-107) cut at the right edge
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x340 y200 1264x711 CSS (16:9), scale 1.519x. Pre-framed for <=1.2x push-in.
- **Notes / Zen checks:** Measured on the 1920 poster (3.0 s): card ID cap height 22 px (PAY-101, PAY-102, PAY-104, PAY-105, glyph rows incl. antialias), which beats the >=18 px target (ideal 20). Title cap height 26 px ('C' of 'Cart summary'); column heading cap 28 px ('Landed'). NOTE: this is the ?demo=1 board (as briefed: Landed PAY-102/PAY-101 -> Wave 1), not the ?demo=promo plan-forming beat of shot-04-v1080. The Wave 1 header line reads '2 need you' with a small amber dot (header text). Clock paused for the hold (still frame). Zen: no '?' bubbles, no Blocked card in frame.

### Shot 11 (DPR2, header + Landed column)
- **File:** `footage/v1-1080/shot-11-dpr2.mov` (lossless H.264 yuv444p) + `shot-11-dpr2-preview.mp4` + poster `shot-11-dpr2-poster.png`
- **sha256 (.mov):** `d523056eca26216adbf7981f8593691506acae1a0d66ab300d50ae5c4ec70579`
- **DPR:** 2
- **Duration:** 5.00 s; **video:** 1920x1080 @ 60 fps, 300 frames
- **URL / route:** `?demo=promo` (scenario clock to 72.6 s, run complete), Full window, Show done, Fit, then the board canvas panned with real mouse-wheel scrolling so the Landed column sits right after the header counts
- **Demo beat:** 5 s locked hold: header 'All done · Plan next' pill + '8 in this run · 8 landed' (with the 'Find a ticket' search box) and, directly to its right, the 'Landed · Merged and closed' column: PAY-103 Design tokens (Claude, #431), PAY-104 Cart summary (Codex, #432), PAY-105 Promo code (Claude, #433), PAY-106 Localized price display (Cursor, #434), all 'Done' and fully in frame. PAY-107 onwards continue below the frame. 'Later · Not scheduled yet' card at the right edge
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x10 y40 900x506.25 CSS (2.133x). Column left edge panned to x~644 CSS (header text ends at x~603), so there is almost no gap between the counts and the column. The lower-left of the frame is empty dotted canvas (layout has the header on top and the column to the right).
- **Notes / Zen checks:** Measured on the 1920 poster: header cap height 18 px ('A' of 'All done', digit '8', 'l' of 'landed'), card ID cap 14 px, card title cap 17 px. That is just under the 20 px header target; a narrower 800-px retake (shot-11-dpr2-r2, ~2.4x, ~20 px header cap) is queued. Agent logos visible on the 4 cards: Claude, Codex, Claude, Cursor (all 3 agents). Zen: no '?' bubbles, no amber pill, no Blocked cards.

### Shot talk-dag (wide r2, talk-show beat 3)
- **File:** `footage/v1-1080/talk-dag-wide-r2.mov` (lossless H.264 yuv444p) + `talk-dag-wide-r2-preview.mp4` + poster `talk-dag-wide-r2-poster.png`
- **sha256 (.mov):** `04f17ab39286c2970d19dd94278bfa357b19758f3964f2faeb0bcba1616d6d48`
- **DPR:** 2
- **Duration:** 6.00 s; **video:** 1920x1080 @ 60 fps, 360 frames
- **URL / route:** `?demo=1&still=1` (Board graph, Full window, Show done, ctrl+wheel zoom to ~180%), same board state as talk-dag-tight / talk-dag-wide
- **Demo beat:** 6 s locked hold: PAY-102 (Done, #413) and PAY-101 'Extract pricing engine into a pure module' (Done, #412), with PAY-101's two edges into PAY-105 'Promo code validation endpoint' (Verifying, API group) and PAY-104 'Cart summary uses the pricing engine' (Running, Backend group). Wave 2 cards are cut at the right edge.
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x629 y237 1152x648 CSS (16:9), scale 1.667x (72 px pad around the PAY-101/104/105 union).
- **Notes / Zen checks:** VERIFIED on the poster: no title is cut. PAY-101's card, ID and full title are inside; the full PAY-104 title 'Cart summary uses the pricing / engine' and the full PAY-105 title 'Promo code validation / endpoint' are inside, with the PAY-104/105 group borders ending at x~1716 of 1920 (~200 px clean margin on the right) and >=120 px margins elsewhere. PAY-102 is also fully in frame. Measured on the 1920 poster: task ID cap height 25 px (PAY-101/104/105), title cap height 29 px ('C' of Cart, 'E' of Extract). Clock paused (still frame). Zen: no '?' bubbles, no Blocked card, no amber pill in frame.

### Shot 4 (DPR2 promo plan DAG)
- **File:** `footage/v1-1080/shot-04-dpr2-promo.mov` (lossless H.264 yuv444p) + `shot-04-dpr2-promo-preview.mp4` + poster `shot-04-dpr2-promo-poster.png`
- **sha256 (.mov):** `367b0be6793a496cbaa8e86b710d33c7e1c2ae8776585a501ed69c4dc9f66055`
- **DPR:** 2
- **Duration:** 6.00 s; **video:** 1920x1080 @ 60 fps, 360 frames
- **URL / route:** `?demo=promo` (scenario clock 5.9-11.9 s)
- **Demo beat:** 6 s locked shot of the promo plan of 8 as a DAG: Wave 1 (PAY-103 Design tokens, PAY-104 Cart summary, PAY-105 Promo code, PAY-106 Localized price display), Wave 2 (PAY-107 Checkout theming 'after PAY-103', PAY-108 Express checkout 'after PAY-104 +1', PAY-109 Order confirmation email 'after PAY-106'), Wave 3 (PAY-110 Remove legacy pricing 'after PAY-104 +1'), 'Later · Plan more', with dependency edges. At 5.9 s Wave 1 is all Ready; the run starts at 6.2 s; PAY-103 goes Running ~0.8 s in, then the others ('1 running · 3 queued' -> more running)
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x779 y316 1006x566 CSS (1.909x), fitted to the 8 cards + Wave 1/2/3 headings (20 px pad). 'Later' column cut at the right edge.
- **Notes / Zen checks:** Measured on the 1920 poster (1.0 s): card ID cap height 16 px (PAY-104, PAY-107, PAY-110), title cap 18 px ('C' of 'Cart summary'), Wave heading cap 20 px. The 20 px ID target cannot be met with all 8 cards in a 16:9 frame: the 4-card Wave 1 column sets the frame height. Wave 2/3 cards show the real 'Blocked' padlock state ('after PAY-103' etc.) for the whole run until wave 1 lands. Promo can't show Wave 2/3 without it. Zen: no '?' bubbles, no amber pill.

### Shot 16 (PR card, tighter)
- **File:** `footage/v1-1080/shot-16-prcard-tighter.mov` (lossless H.264 yuv444p) + `shot-16-prcard-tighter-preview.mp4` + poster `shot-16-prcard-tighter-poster.png`
- **sha256 (.mov):** `ffc3b750c28fb4423247008eff4b68725fa6aaad26f4dc992b5ec0ff5ab27867`
- **DPR:** 2
- **Duration:** 9.50 s; **video:** 1920x1080 @ 60 fps, 570 frames
- **URL / route:** `?demo=promo` (scenario clock), PAY-110 node clicked at 59 s to open its drawer; record 61.0-70.5 s
- **Demo beat:** Same beat as shot-16-prcard-tight: PAY-110 drawer Running -> Checks 62.3 s -> Pushed 63.1 s -> PR raised #438 63.9 s -> Merged 67.5 s, hold to 9.50 s. End frame: status 'Done' with the full stepper, 'Codex · Board run · +1 -1', then 'Pull request' and the card '#438 [Merged] · PAY-110 Remove legacy pricing module · commission/PAY-110-legacy-pricing -> main · Builds pass · 1 approval · 1 comment · Open'
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x1142 y122 752x423 CSS (16:9), scale 2.553x. The bottom edge sits just above the Evidence section, so the Evidence / 'QA decision not recorded' block is out of frame in the final state. In the final frame the card spans output x 25-1894 and ends at y 1032 (~25 px side margins, ~48 px bottom margin).
- **Notes / Zen checks:** CLIP TIMES (confirmed by the Director): the drawer status changes to Done at 6.5 s and the PR card badge flips to Merged at 7.70 s; hold to 9.50 s (use 7.7-9.5 s as the payoff). Measured on the 1920 frame at 9.0 s: 'Merged' badge cap height (M) ~19-20 px (glyph rows 761-780 incl. antialias; badge text box 95x26 px). PR title cap height (P) 26 px, title line incl. descenders 34 px. 'Builds pass' cap height (B) 22 px, chip line with icon 30 px. LIMIT: the card is ~732 CSS px wide, so with the whole card in a 16:9 frame the Merged badge tops out at ~19-20 px cap height. The 24+ px target would need cropping the card's right side (Open link / title end). CAVEAT: during PR raised (63.9-67.5 s) the status block is taller, so the PR card sits ~40 CSS px lower and its bottom row (Builds pass chips) is clipped at the frame edge until the reflow when the status turns Done (6.5 s clip time). Zen: no '?' bubbles, no amber pill, no Blocked.

### Shot 3/composer (DPR2, talk-show beat 2 / hero composer / anime cold open)
- **File:** `footage/v1-1080/shot-03-composer-dpr2.mov` (lossless H.264 yuv444p) + `shot-03-composer-dpr2-preview.mp4` + poster `shot-03-composer-dpr2-poster.png`
- **sha256 (.mov):** `e45a22dd567561be393993425eedbd32a1841c43b218cd52263629680ef1fcda`
- **DPR:** 2
- **Duration:** 6.35 s; **video:** 1920x1080 @ 60 fps, 381 frames
- **URL / route:** `?demo=promo&pause=1` (promo held on its first beat, empty board)
- **Demo beat:** Commander composer, focused. Before rolling, the composer's Access pill was switched from 'Bypass permissions' (amber) to 'Edits' through the real Access menu. The ask is typed with real keystrokes at 10 chars/s: 'Ship the checkout revamp tonight.' + Shift+Enter + 'No broken builds.' (the same text that appears as the sent message in shot-10 / shot-05). Ends ~0.4 s after the last keystroke with the send (arrow) button highlighted. Not sent.
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x150 y675 720x405 CSS (2.667x) on the bottom of the Commander pane: composer box (text, + / Edits / 'Sonnet 5.5 High' / tools / send) with the 'Finish the board' and 'Where does the board stand?' starter cards above. Duration 6.35 s.
- **Notes / Zen checks:** Measured on the 1920 frame at 6.3 s: composer text cap height ~27 px ('S' of Ship, 'N' of No: glyph rows 28 px incl. overshoot/antialias), first line incl. descenders 36 px. That beats the >=20 px target. Access shows the 'Edits' icon (not the amber Bypass pill). FIX NOTE: the first attempt (shot-03-composer, now in footage/v1-1080/_rejects/) used clip y465, which was computed from a probe screenshot I misread as 1280 px wide (it was shown at 1024). The composer (CSS y~966-1059) fell below that clip, so the take showed only starter cards; it was never registered. Zen: no '?' bubbles, no amber pill, no Blocked.

### Shot 11 (DPR2 r2, header 20 px + Landed column)
- **File:** `footage/v1-1080/shot-11-dpr2-r2.mov` (lossless H.264 yuv444p) + `shot-11-dpr2-r2-preview.mp4` + poster `shot-11-dpr2-r2-poster.png`
- **sha256 (.mov):** `90ff6b72e1c1243711287593390061328c0b9f2987e9fe39b9fa4ed89d921689`
- **DPR:** 2
- **Duration:** 5.00 s; **video:** 1920x1080 @ 60 fps, 300 frames
- **URL / route:** `?demo=promo` (scenario clock to 72.6 s, run complete), Full window, Show done, Fit, board canvas panned with real mouse-wheel scrolling so the Landed column starts at x~617 CSS
- **Demo beat:** 5 s locked hold: 'Find a ticket' search + 'All done · Plan next' pill + '8 in this run · 8 landed' across the top; 'Landed · Merged and closed' column on the right with PAY-103 (Claude, #431), PAY-104 (Codex, #432), PAY-105 (Claude, #433) whole, all 'Done'; PAY-106 (Cursor) cut at the bottom
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x8 y44 800x450 CSS (2.4x).
- **Notes / Zen checks:** Measured on the 1920 poster: header cap height 21 px ('A' of All done, digit '8' of '8 landed'), card ID cap 16 px, card title cap 18 px. EDGE CHECK: left edge in a clean gap (canvas 0-37 px, search box border starts at x~38); right edge in a clean gap (column cards end at x~1885, canvas 1890-1919, no neighbouring column, no stray 'L'). CAVEAT: the lower-left ~55% of the frame is empty dotted canvas under the header (the header is on top, the column to the right). For a frame filled with whole cards use shot-11-dpr2-r3 (zoomed board, column under the header; queued). Zen: no '?' bubbles, no amber pill, no Blocked.

### Shot 5 / rail (DPR2, agent rail with logos)
- **File:** `footage/v1-1080/shot-05-rail.mov` (lossless H.264 yuv444p) + `shot-05-rail-preview.mp4` + poster `shot-05-rail-poster.png`
- **sha256 (.mov):** `53764a87d812bb78dee10870c301c9add5c531e175616fe54f390631d9b28ccb`
- **DPR:** 2
- **Duration:** 12.00 s; **video:** 1920x1080 @ 60 fps, 720 frames
- **URL / route:** `?demo=promo` (scenario 5.6-17.6 s)
- **Demo beat:** Left rail + Commander as the run starts: project card 'Checkout Revamp · Running · 0/8'; the rail goes from 'Start' links to a 'Working' list as agents claim tickets: PAY-103 'Design tokens for checkout…' (Claude logo) Coding ~6.7 s, PAY-104 'Cart summary uses the prici…' (Codex logo) ~7.7 s, PAY-106 'Localized price display in or…' (Cursor logo) ~8.7 s, each with its live diff stat (+18 -4 -> +36 -8); later Checks / Pushed. Commander shows the sent ask 'Ship the checkout revamp tonight. No broken builds.' and the plan reply ('Here's the plan: eight checkout tickets in three waves…')
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x0 y90 640x360 CSS (3.0x; 1.5x over the DPR2 raster). The rail is fully in frame; the Commander text is cut at the right edge. The '$' cost figure is above the frame.
- **Notes / Zen checks:** Measured on the 1920 frame at 4.5 s: rail row title cap height ~27 px ('D' of Design, glyph rows 29 px incl. antialias), ticket ID cap ~22 px (PAY-103), project name cap ~27 px. Agent logos ~50 px squares: all 3 agents visible (Claude orange, Codex teal, Cursor dark). The 'PAY Collab · 3 people' row with AM/RC/MC avatars and '# standup @1' are at the bottom. At 4.5 s: no amber pill or Blocked state in the rail.

### Shot 11 (DPR2 r3, header + top of Landed column, zoomed board)
- **File:** `footage/v1-1080/shot-11-dpr2-r3.mov` (lossless H.264 yuv444p) + `shot-11-dpr2-r3-preview.mp4` + poster `shot-11-dpr2-r3-poster.png`
- **sha256 (.mov):** `199fe8a7bec5292cf0188f53363c7479819303e9cd841e8e693731a2da8fece5`
- **DPR:** 2
- **Duration:** 5.00 s; **video:** 1920x1080 @ 60 fps, 300 frames
- **URL / route:** `?demo=promo` (scenario clock to 72.6 s, run complete), Full window, Show done, Fit, then real ctrl+wheel zoom (board ended at 111 %, target was 95 %) and real mouse-wheel pan so the Landed column sits at x300 y100 CSS, right under the header
- **Demo beat:** 5 s locked hold: 'All done · Plan next' pill + '8 in this run · 8 landed' across the top; under it 'Landed · Merged and closed' with PAY-103 Design tokens (Claude, #431) and PAY-104 Cart summary (Codex, #432) whole, all 'Done'; PAY-105 cut at the bottom. Right half: 'Later · Not scheduled yet' column with the dashed 'Plan more' card, then dotted canvas.
- **Commit:** `4a427fc05f829d7b2e4ed7ea642d77340554f7f8` (main)
- **Framing:** DPR 2. Clip x270 y44 800x450 CSS (2.4x).
- **Notes / Zen checks:** Measured on the 1920 poster: header cap height 21 px (digit '8' of '8 landed'), 'Landed' heading cap 28 px, card ID cap 21 px (PAY-103), card title cap ~25 px ('D' of Design). Agent logos ~30 px. EDGE CHECK: right edge clean (no content in x 1900-1919). LEFT EDGE FAILS: x 0-11 shows a sliver of the search box's right end (y~50-280 px, incl. a blue focus/selection line). A retake with the clip moved 6 CSS px right (shot-11-dpr2-r4, clip x276) is queued; use r3 only if you crop 12 px off the left or push in. The whole-card framing (header + 2 whole Landed cards) is right; the empty-canvas problem of r2 is fixed. Zen: no '?' bubbles, no amber pill, no Blocked.


