# commission-ai promo, modelled on Higgsfield's "Dots x Higgsfield" (60 s)

**Template source:** the Higgsfield video (59.6 s, 16:9, music only, ~89 BPM, 10 hard cuts but continuous UI camera moves). See `summary.md`.
**Idea to borrow:** *one line in at night, a crew of agents works, you wake up to shipped work.* For commission-ai: **"Tell the Commander. Go to bed. Wake up to pull requests."**

## Honesty guardrails (only show what exists in the app today)
Every item below was checked against the `commission-ai` repo (commit b066fb02, 30 Sep 2026) and README:
- The **Commander** chat plans the **board** as a dependency DAG (`board/DagView.tsx`, `TaskNode`).
- It dispatches **Claude Code, Codex and Cursor agents** into git worktrees. Each task gets a worktree and a PR. PRs are landed stacked or through automated review and merge.
- Task states: To do → Ready → Running → Verifying → Reviewing / In review → Merging → Done, plus **"Needs you"** (hand icon, intent tone). Pipeline chips: Planning · Coding · Checks · Review · Pushed · PR raised · Merged.
- The **Review** flow: review queue ("Pull requests to review", "Waiting on you"), diff pane, "About this change", Findings, **Deep review**, "Request changes", "Ask the reviewer".
- The **rail** (left column with live status) and the bell. Sound is off by default and toggled in the rail.
- The **pane divider**: drag the conversation/stage split. It snaps to 25/50/75 % and the panes can be swapped.
- The **Workshop**: token burn fills a mora wallet, voxel robots (one per live agent session) build furniture piece by piece in isometric diorama rooms. The view toggle has **Outside → Street → Town → City** scales. Walkers stroll the Street/Town promenade, and a "Your workshop is now a Street" notice appears when a tier is reached.
- The shared browser with **Teach** (record a task once and it becomes a skill), and **Collabs** (teammates' channels). These are optional extra beats.
- **Do NOT claim:** texting/calling agents, 24/7 cloud hosting (agents run on your Mac via the `commissiond` LaunchAgent, so the Mac must be on), publishing to app stores, or any benchmark numbers you can't reproduce. Show numbers only if they come from a real recorded run. The app is **macOS 14+ (Apple Silicon) alpha**, so say that on the end card if you add requirements.
- Capture every UI shot from a real board run (or the built-in demo mode, for example the Workshop `&town=street` demo seed). If you use demo mode, don't imply it's a real user's history.

## Shot list (60 s master; timings mirror the source)
| # | Time | Dur | Beat (source equivalent) | Visual (real app screen) | On-screen text | Camera / transition | Music |
|---|---|---|---|---|---|---|---|
| 1 | 0:00–0:02.5 | 2.5 s | Logo cold open (logo card + mascots) | Wordmark "commission-ai" on a clean off-white gradient. Around it, 4–6 Workshop **voxel robots** idle/bob (render from the Workshop scene on a transparent or white background) | **commission-ai** + pill "Your always-on crew" | Slow push-in | Sparse intro, hit at 0:02 |
| 2 | 0:02.5–0:04 | 1.5 s | Tunnel fly-through | Fast dolly through the Workshop **Town/City** view down to one building (use the real Street→Town zoom glide) | — | Whip zoom (the app's own log-space glide, sped up 2×) | Hit at 0:04 |
| 3 | 0:04–0:08.8 | 4.8 s | **Hook:** a human types an impossible ask and goes to bed | Live action: a dev at a MacBook at night (warm lamp / blue window). Composite of the real **Commander composer** typing: "Ship the onboarding revamp tonight." → "No broken builds." Then the lid closes and the lights go off | (the typed text is the text) | Handheld, shallow depth of field. The composer bar floats over the footage | Hit at 0:06 on "No broken builds." |
| 4 | 0:08.8–0:13 | 4.2 s | **Reveal:** the crew answers | A clean screen recording: the Commander replies and **plans the board**, with task nodes popping into the DAG and edges drawing | "Commander · Planning" → "Split into 7 tasks." (use the real count) | Slow push over the board | **Groove drops at ~0:09.5** |
| 5 | 0:13–0:17 | 4 s | "Your dots" roster | The **rail** with live agents: Claude Code, Codex and Cursor sessions lighting up one by one as their tasks go to **Running** | "Claude Code · Coding" / "Codex · Coding" / "Cursor · Coding" (green status verb) | Vertical scroll down the rail | Steady groove |
| 6 | 0:17–0:19.7 | 2.7 s | Floating card + pill | One **TaskNode** card lifted out of the board in 3D tilt, with a floating pill toast | pill: "Working in its own worktree" | 3D tilt card (After Effects / Rotato on a real screenshot) | |
| 7 | 0:19.7–0:21.3 | 1.6 s | **Card fan** whip | Stacked fan of real task cards / PR cards racing past in Z-depth | — | Z-stack fan + motion-blur whip (a flash on the cut) | Accent hit |
| 8 | 0:21.3–0:22.3 | 1 s | Macro push-in | Tight on a pipeline chip changing **Coding → Checks → Review** | pill: "Running checks" | Macro push | |
| 9 | 0:22.3–0:24.7 | 2.4 s | Status headline card | Board task drawer: status line + checklist | "Verifying · Checks passing" (real) | Hold, slight drift | |
| 10 | 0:24.7–0:30.7 | 6 s | Social-proof scroll → **"Needs you"** | Scroll the board, which stops on one task flipping to **"Needs you"** (hand icon). The rail/bell badge lights up. A cutaway to a phone or the sleeping dev is optional | "Only pings you when it matters." | Blurred scroll → sharp stop on the "Needs you" chip | Groove continues and eases at 0:30 |
| 11 | 0:30.7–0:32.3 | 1.6 s | Wall-of-thumbnails zoom out | Zoom out of the whole **DAG board** with many nodes going green / Done | "7 tasks · 3 agents · 1 night" (only if true for the recorded run) | Pull-out | Music thins |
| 12 | 0:32.3–0:39.5 | 7.2 s | Build-up to the artifact (blueprint ready) | The **Review flow**: review queue → PR diff pane → "About this change" → Findings / Deep review | "Review · Reading this change" → "Ready for review." | Continuous camera move across panes | Breakdown, quiet at 0:38–0:39.5 |
| 13 | 0:39.5–0:44 | 4.5 s | **Re-drop:** Build | The **divider drag**: grab the conversation/stage divider and drag it so it snaps at 50 % → 75 %, putting the diff and board side by side (optionally swap the panes) | "Your layout. Snaps into place." | Screen recording with a cursor-follow zoom, hit-synced on each snap | **Re-drop at 0:39.5.** Snap clicks land on beats (~0.68 s) |
| 14 | 0:44–0:51 | 7 s | Media / Publish beat | The **Workshop**: voxel robots assembling furniture piece by piece in the diorama room (live agent token burn), then the view toggle **Outside → Street**: the building on the street with walkers on the promenade. The toast "Your workshop is now a Street" (real notice; use a demo seed if needed) | "Every token builds something." | Orbit of the diorama, then the Street pull-back | Energy builds |
| 15 | 0:51–0:54.3 | 3.3 s | **Payoff:** the human wakes up | Live action, morning: the dev opens the laptop and smiles. Composite: stacked PRs **"PR raised" → "Merged"** chips, all tasks Done | pill: "Merged while you slept." | Handheld push-in | Dip at 0:52.5–0:53.5 (a breath) |
| 16 | 0:54.3–0:57.5 | 3.2 s | Montage / social proof | A 3-up split: (a) the board all Done, (b) the Workshop room complete, (c) the review "Merged" diff. Or, if you have them, real teammates in a **Collab** channel reacting (with permission) | — | Split panels slide in sideways | **Loudest section** |
| 17 | 0:57.5–1:00 | 2.5 s | End card (bookend of #1) | The same logo card as shot 1, with robots | **commission-ai** · "Always-on agents for your repo" · pill "macOS alpha" + URL | Hold. The music hard-stops on the card | Hard stop |

**Structure:** cold open (0–4) → hook (4–9) → reveal (9–17) → montage 1: agents at work + "Needs you" (17–32) → build-up to the artifact: review (32–39.5) → montage 2: layout + Workshop/Street (39.5–51) → payoff (51–57.5) → end card (57.5–60).

## Optional swaps (all real features)
- Shot 6–8 alternative: the shared **browser with Teach**, where you record once and "Skill saved" appears. It mirrors Higgsfield's "Skill complete" card.
- Shot 16 alternative: **Collab** channels showing a teammate's request waiting for your OK.

## 30 s cutdown (9:16 first)
| Time | Shots |
|---|---|
| 0:00–0:03 | #3 hook (the typed ask, trimmed) |
| 0:03–0:08 | #4 the board plans itself (groove drop at 0:03) |
| 0:08–0:12 | #5 + #7 agents running + card fan |
| 0:12–0:16 | #10 "Needs you" |
| 0:16–0:20 | #12 review diff → "Ready for review" |
| 0:20–0:25 | #14 Workshop robots → Street |
| 0:25–0:28 | #15 wake-up + "Merged" |
| 0:28–0:30 | #17 end card |

## Music brief
- ~88–92 BPM beat-driven groove (modern hip-hop / electronic pop), bright and confident, mastered loud for social (about −8 LUFS integrated for feed; also deliver a −14 LUFS version for YouTube).
- Shape: **sparse intro with 3 punch hits** (logo, fly-through, the typed line) → **full groove drop exactly when the UI appears (~0:09.5)** → steady → **breakdown/filter-down at 0:30–0:39** → **re-drop at 0:39.5** → short breath at 0:52.5 → biggest section 0:54–0:57.5 → **hard stop** on the end card.
- Cut UI changes to the beat grid (~0.68 s at 88 BPM). Add subtle UI SFX (soft ticks on status changes, a "snap" on the divider snaps, a gentle chime on "Needs you" that matches the app's real finish sound).
- No voiceover (like the source). All messaging goes in on-screen text. If you want a VO for YouTube, keep it to 3 lines: the hook, "Only pings you when it matters" and the end line.

## Look and typography
- **UI sections:** pure white / off-white canvas, faint cool gradient, lots of white space. Use the app's own UI font and colours (don't restyle the real screens). Status lines follow the pattern `[agent icon] Agent · <green verb>` with a bold one-line headline underneath. Floating white pill toasts carry the agent avatar.
- **Live action:** warm tungsten practicals against blue-hour window light at night, soft daylight in the morning, shallow depth of field.
- **Workshop shots:** keep the native lit-voxel diorama look (warm sun shaft, bloom, grain). It's the "cinematic" colour moment, like the drama posters in the source.
- **Transitions:** continuous virtual camera over UI, 3D tilted cards, Z-stacked fans with motion-blur whips, a logo bookend.

## Deliverables and aspect ratios
| Format | Size | Use | Notes |
|---|---|---|---|
| 16:9 | 1920×1080 (plus a 3840×2160 master) | X, YouTube, website hero | Master edit, 30 fps |
| 9:16 | 1080×1920 | Reels, TikTok, Shorts, X vertical | Recompose: stack the UI vertically (board top / agent status bottom). Crop live action to centre. Keep text inside the middle 1080×1420 safe zone |
| 1:1 | 1080×1080 | LinkedIn / feed | Centre-crop the UI with a slightly zoomed screen capture |
| 4:5 | 1080×1350 | Instagram feed | Optional |
Also deliver: a 60 s and a 30 s version, a silent-autoplay-safe version (all meaning in the text), SRT captions for any optional VO, and a thumbnail from shot 14 (the Workshop Street) or shot 10 ("Needs you").

## Capture checklist
- Record at 2× (Retina) with 60 fps screen captures, cursor hidden except in shot 13.
- Use a real repo run with a small, safe task list so the numbers on screen are true. Save the run (board screenshot, PR links) as proof for claims.
- Workshop: the demo seed `&town=street` (or "Finish 5 rooms" in Settings → Demo controls) for the Street tier notice. Mark it internally as demo footage.
