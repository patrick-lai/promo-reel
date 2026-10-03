# commission-ai 60 s promo: capture shot list v2
Source plan: /workspace/videos/higgsfield-2104989726604484946/promo-template.md (Zen). Checked against repo commit b066fb02.

## Global capture settings (apply to every UI shot unless noted)
- Build: web UI from commit b066fb02 (or newer, but tell me the hash).
- Viewport: 1920x1080 CSS px at devicePixelRatio 2, so frames are 3840x2160. That gives 2x headroom for push-ins, macro shots and the 1:1 / 9:16 crops.
- Frame rate: 60 fps, lossless or ProRes 4444 / PNG sequence. Cursor hidden except shot 13.
- Theme: Dark (Settings theme = `dark`, not System, so it can't flip). Light popovers wash out (Zen); switch back only if that fix lands first. Sound off in the rail (UI SFX get added in the edit).
- Reduced motion OFF. Notifications/toasts from anything other than the beat being shot must be cleared.
- Camera moves in the table are done IN THE EDIT on the 4K frames unless marked "in-app". Capture a static, locked frame with 1 s handles before and after each action.
- Base URL for demo footage: `?demo=1`. Add `&still=1` only where noted (frozen, no live churn).
- Data: until Patrick decides real vs demo, capture from demo mode and keep every on-screen count as a placeholder `{N}` in the edit. If he picks a real run, recapture shots 4, 5, 9, 10, 11, 12, 15 from that run and save board screenshot + PR links as proof.
- File naming: `S{shot#}_{take}_{short-name}.mov`, plus a `capture-log.md` noting URL, hash, demo/real, and any manual steps.

## v2 changes (after Zen's storyboard and Marketing copy v1)
- Dark theme, not Light.
- Shot 3 types "checkout revamp" to match the demo board.
- Shot 8 chips are Coding, Checks, Pushed, PR raised. Shot 9 line is "Verifying · Nothing needed from you".
- Shot 12 has no Deep review. It adds the "Ask the reviewer" / "Request changes" beat for clip 4.
- Shot 14 hides the wallet and token figures.
- BLOCKED on a real run: shot 5 needs more than one agent type coding (the demo only shows Claude), and shots 11, 15 and 16a need an all-Done, merged board, which the demo never reaches. Without a real run, shot 5 becomes "Claude Code · Coding" only, shot 11 gets cut (its slot goes to shot 10), and 16a uses the most-complete demo board with no Done claim.

## Shot list
| # | Edit slot | Capture len | Route / URL | App state before roll | Action during capture | Framing | Camera move (edit unless "in-app") |
|---|---|---|---|---|---|---|---|
| 1 | 0:00-0:02.5 | 6 s | `?demo=1&view=workshop&workshop=fast` | Workshop with 4-6 live robots idling | Robots idle/bob only, no camera input | Tight on robots; need them on a clean/light background. If the scene can't give a plain bg, capture as-is and I'll key/mask | Slow push-in; wordmark + pill added in edit |
| 2 | 0:02.5-0:04 | 8 s | `?demo=1&view=workshop&town=city` | View toggle on City | Use the real view toggle City -> Town -> Street -> Outside, ending on one building | Full frame | In-app glide; I speed it 2x and add motion blur |
| 3 | 0:04-0:08.8 | 10 s | Main app, `?demo=1` | Commander chat open, composer empty, focused | Type "Ship the checkout revamp tonight." then newline-pause, then "No broken builds." at human speed (~6 chars/s). Do NOT send | Composer bar only, 1:1 crop safe. Live-action night laptop plate is a separate asset (stock/shoot, not app) | Composited over live action in edit |
| 4 | 0:08.8-0:13 | 15 s | Main app | Commander + Board stage visible, board empty. Pane split 50 % | Send the ask (or trigger the demo plan) and roll while the Commander replies and task nodes pop into the DAG and edges draw | Board fills >60 % of frame | Slow push over board |
| 5 | 0:13-0:17 | 12 s | Main app | Rail visible with sessions, all idle/ready | Tasks move to Running one by one; capture rail lighting up "Claude Code / Codex / Cursor · Coding" | Rail column, full height | Vertical drift down the rail |
| 6 | 0:17-0:19.7 | still + 3 s | Main app, `&still=1` ok | One TaskNode clearly showing a worktree/branch | Hold | 4K still of a single TaskNode, plus surrounding board for background | 3D tilt + pill toast built in edit |
| 7 | 0:19.7-0:21.3 | stills | Main app | Board with 8-12 task cards + PR cards | None | 8-12 clean 4K stills of individual task/PR cards (crop-able) | Z-stack fan + whip built in edit |
| 8 | 0:21.3-0:22.3 | 10 s | Main app | One task drawer open, pipeline chip on Coding | Roll through Coding -> Checks -> Pushed -> PR raised (there is no Review chip) | Chip area, I crop to macro | Macro push |
| 9 | 0:22.3-0:24.7 | 5 s | Main app | Same task drawer, status line reads "Verifying · Nothing needed from you" | Hold | Drawer, full height | Hold + slight drift |
| 10 | 0:24.7-0:30.7 | 15 s | Main app | Board with many tasks, one about to need input | Scroll the board (in-app, smooth trackpad scroll) and stop on the task flipping to "Needs you"; capture rail/bell badge lighting up | Full frame; second pass tight on the chip + bell | Blurred scroll -> sharp stop |
| 11 | 0:30.7-0:32.3 | 8 s | Main app | Whole DAG zoomed to fit, most nodes Done | Final nodes turn green/Done | Whole board | Pull-out |
| 12 | 0:32.3-0:39.5 | 20 s | Main app -> Review | Review queue with >=2 PRs ("Pull requests to review") | Open a PR -> diff pane -> "About this change" -> Findings. No Deep review. Pause 1.5 s on each pane. Extra take for clip 4: click "Ask the reviewer" (take A) and "Request changes" (take B), hold 2 s on the result | Full frame | Continuous camera across panes (edit) |
| 13 | 0:39.5-0:44 | 12 s | Main app | Diff open on one side, board/conversation on the other, split at 25 % | CURSOR VISIBLE. Grab divider, drag to 50 % snap, hold 0.7 s, drag to 75 % snap, hold. Optional take 2: swap panes | Full frame | Cursor-follow zoom; I sync snaps to beats |
| 14 | 0:44-0:51 | 20 s + 15 s | a) `?demo=1&view=workshop&workshop=fast` b) `?demo=1&view=workshop&town=street` | a) a room mid-build with robots; b) Outside view, Street tier not yet shown | a) robots assembling furniture, slow in-app orbit if available. b) Toggle Outside -> Street and capture the "Your workshop is now a Street" notice | Full frame | Orbit, then Street pull-back. Mark as DEMO in log. Wallet and token numbers must be hidden or out of frame (demo figures) |
| 15 | 0:51-0:54.3 | 10 s | Main app | Board all Done; PR list showing "PR raised" -> "Merged" | Capture the chip flipping to Merged | Chips + board. Morning live-action plate is a separate asset | Composite + handheld push-in in edit |
| 16 | 0:54.3-0:57.5 | stills/5 s each | Reuse 11, 14a, 12 | n/a | n/a | Three clean ends: board all Done, finished Workshop room, merged diff | 3-up split in edit |
| 17 | 0:57.5-1:00 | reuse 1 | reuse 1 | n/a | n/a | n/a | Hold, hard stop. URL pending Patrick |

## Not capturable from the app (I'll source)
- Shots 3 and 15 live-action plates (night typing / morning wake-up): needs a shoot or licensed stock. Flagging to Patrick.
- Licensed music track (~88-92 BPM).

## Open questions for Commission-ai
1. Is there a URL or hash route that opens the Board stage or Review stage directly, or is it click-through only? I found `?demo=1`, `&still=1`, `&view=workshop`, `&town=facade|shop|street|town|city|<n>`, `&workshop=fast`, `&workshopWeather`, `&workshopHour` (demo only), but no board/review route.
2. Does demo mode produce a live plan + Running/Needs you/Merged transitions for shots 4, 5, 8-11, 15, or do those need a real run?
3. Can the Workshop render robots on a plain background for shot 1, or should I mask in post?
