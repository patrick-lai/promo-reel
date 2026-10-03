# commission-ai-talkshow: Direction 3 "Building in Public, episode one"

Two Live2D Original Character hosts (Hiyori on top, Mao below, left column for the whole show, no move) sit beside the
stream screen, which plays real app takes. The chat strip carries only HIYORI's two scripted asides (on screen only,
never voiced). There's an EP 1 tag (no LIVE badge, no viewer counts), and the show ends on the Live2D credits card.

| File | What it is |
|---|---|
| `plan.yaml` | Hand-edited beat-to-shot plan (clip ids, cams, sync points, chat). **Edit this file.** |
| `make_spec.py` | Reads `plan.yaml` plus the VO's `lines.json` (exact durations) and writes `promo.yaml` (`--check` = staleness test). |
| `promo.yaml` | GENERATED. Frame-exact timeline (`bpm: 1800` at 30 fps, so 1 timeline beat = 1 frame) and sha256-pinned VO lines. |
| `assets.yaml` | Every audio asset with its licence: the Kokoro VO files (Apache-2.0), the Kokoro model and voices (from talkshow/LICENSE.md), and the CC0 self-synthesised swell. No music bed. |
| `make_preview.py` | DRAFT timing preview only. It swaps each missing take for a labelled PLACEHOLDER card in a gitignored `preview/` spec and copies the mp4 and contact sheet to `/workspace/promo-reel-evals/`. Never a deliverable. |

```
python projects/commission-ai-talkshow/make_spec.py           # after the VO is re-rendered or plan.yaml is edited
nice -n 10 python -m promo -p projects/commission-ai-talkshow/promo.yaml build   # reports missing takes; no placeholders
nice -n 10 python projects/commission-ai-talkshow/make_preview.py                # draft preview with placeholder cards
python -m promo -p projects/commission-ai-talkshow/promo.yaml check
```

## Timing rules

The room has dropped the script's fixed ~2:00 slots. Each beat runs for its real VO plus a screen hold, and no voice is time-stretched.

- Lines inside a beat are 0.20 s apart.
- Each beat's screen cuts 0.15 s before its first line and holds 1.5 s after its last (beat 1: 2.0 s).
- There's a 1.5 s intro sting (card plus swell) and a 3.0 s credits card.
- Total: 106.17 s (1:46).
- Sync points use `hold_in`, which holds the clip's first frame and then plays at 1x. A clip that runs out holds its last frame. There's no slow-mo and no mid-clip edit.

### Beat 7 automatic take

`make_spec.py` measures shot 12's "Approved..." line through the segment's cam on the 1440 px screen (`livestream.text_height`, the same measurement as the `promo check` gate `livestream-text-size`).

- **At least 24 px:** MAO's full `beat07_line02` is used. This is the current result: 24.8 px.
- **Under 24 px:** the line is cut at the silence after "...tells you why it passes." (3.11 s, 40 ms fade). "See? Approved, with the reason right there." is dropped, and `text` becomes that prefix while the full line stays in `script_text`.

The take that was used is written in the `promo.yaml` header.

## Beat to shot map

| Shot | Beat | Screen (manifest clip id) | Sync / framing | Status |
|---|---|---|---|---|
| 01 | 1 | Generated card "Building in Public / episode one" plus swell | intro sting, then beat 1 dialogue | ok |
| 02 | 2 | `shot-03` (composer, legacy 4K, 0a3c3ac demo=1) | push-in on the composer; "Ship the checkout revamp tonight." finishes typing as MAO's line ends | legacy take |
| 03 | 3 | `talk-dag` | n/a | **MISSING** |
| 04 | 4 | `shot-05-v1` (rail, legacy 4K, bc10d245 promo branch PR #86) | Wave 1 cards; PAY-103 lights as MAO starts naming the agents | legacy take |
| 05 | 5 | `shot-08-v1080` | the "PR raised" chip lands on MAO's "PR raised" | ok |
| 06a/06b | 6 | `shot-10-dpr2-v1080` | flips to Needs you as HIYORI speaks; held, then the Allow once click lands on MAO's "Click Allow once" | ok |
| 07 | 7 | `shot-12-v1080` (1x) | 2.25x push-in framed from just above "Approved..." plus its reason down past the 10:40 PM divider. The raw `**PAY-104` request title above it is out of frame and the board isn't visible. Text 24.8 px (`livestream-text-size`) | ok; swap to the Z179 DPR2 retake |
| 08 | 8 | `shot-16-v1080` | n/a | **MISSING** |
| 09a | 9 | `shot-01-dusk-v1080` | header bar cropped; starts at 0.3 s, after the first-frame brightness dip | ok |
| 09b | 9 | `shot-14b-v1080` (from MAO's "Ours just became a Street", captured 4 Oct) | starts at clip 4.04 s, after the settings popover; the Outside to Street switch (5.5 s) lands on MAO's "...a Street"; top-right of the screen kept clear (`street-notice`) | ok (see flags) |
| 10 | 10 | Generated end card "commission-ai / Your AI dev crew / Runs on your Mac / Alpha for Apple Silicon" | wording taken from the beat 10 dialogue only | ok |
| 11 | n/a | `live2d_credits` (Live2D notice plus model credits, 30 px) | 3.0 s | ok |

The DPR2 retake is a one-line swap: in `plan.yaml` segment 07, set `clip:` to the new id, change `cam`/`text_check` to
that take's framing, then re-run `make_spec.py`.

## Script vs footage flags (script wording unchanged)

- The script's shot numbers (S3, S4 ...) are the hero shot list. Only S8, S10, S12 and the Workshop exist as v1-1080 takes. S3 composer and S5 rail use legacy 4K demo takes (older app commits). There's no S6 TaskNode-worktree take (only a legacy still), so it isn't used.
- Beat 1 "both hosts wave": the hosts aren't animated to wave (idle motion only).
- Beat 4: the rail shows each agent's logo on its card, not the words "Claude Code / Codex / Cursor".
- Beat 6 "a hand icon popped up!": the take shows a "Needs you" pill with a diamond icon and a key icon in the Needs you list. No hand icon is visible.
- Beat 7: the take shows only the reviewer's "Approved..." line plus its reason. The new MAO line (Marketing) fits. HIYORI's line and chat aside make no panel claims. The old line's "About this change" / findings / "ask the reviewer" claims are gone.
- Beat 8 "PR #438": the 1x takes show PR #432. Check the shot-16 take's number when it lands.
- The ~2:00 / timecodes in the script table no longer apply (the room's call: real VO plus holds, 1:46).
- Beat 9 / shot 14b: the script's note says the Street line needs the notice popping up top right. In the v1-1080 take the "Your workshop is now a Street" toast (1.85 s) is stacked under a "2 achievements earned" toast, so the notice itself isn't legible. The cut instead lands MAO's line on the visible Outside to Street switch, with the Street tab and HUD showing "Street".
- Shot 12 (1x) is pushed in 2.25x: `footage-dpr` WARN (soft upscale). It's readable at 24.8 px; the DPR2 retake fixes this.
