# Reference: "Dear Higgsfield, I reverse engineered you in 12 hours" (Sirio Berati)

https://www.youtube.com/watch?v=d6spCMcfkew, transcript read on 2026-10-11. It inspired the Stage's **Studio** tab (`promo/studio.py`,
`promo/openrouter.py`, `mods/promo-flow` Studio view).

## What the video shows
He rebuilds Higgsfield's character-swap app on pay-per-use APIs, driven by an agent skill:
- Demucs, Depth Anything, SAM 3 and a MediaPipe face mesh prepare the clip.
- Seedance makes a cheap draft first, and the 1080p final is rendered only after a person approves the draft.
- The flow has four steps: upload, review the prepared input, draft, then export.
- Drafts are tied to their task id. The final must come from the same task and settings, not from a re-upload (around 8:20-10:30).

## What we took
- **Cheap draft, then a final from the same settings.** Every Studio take records its prompt, model and **seed**. "Final at 720p" re-runs
  the take at the next resolution with the same seed. Defaults: Seedance 2.5, 480p, 4 s, no sound (about $0.41); Seedance 1.5 Pro (about $0.05) and Grok Imagine Lite ($0.02 a second) stay in the list for cheap tries.
- **Money is shown before the click.**
  - The Generate button shows the price.
  - A take over the per-take limit ($0.50) or the daily cap ($2) is refused, with the reason shown.
  - The ledger keeps each take's estimate next to what OpenRouter billed.
- **A gallery of takes.** Every try is kept: the ones still being made (with a live clock), the finished ones (playable, with their real
  cost) and the failed ones (with OpenRouter's reason).
- **Start from a picture.** Any storyboard frame can be the first frame (image to video).
- **Camera presets.** Each preset adds one sentence to the prompt, and "What Seedance gets" shows the full prompt that is sent.

## What we did not take
- **Swapping people into copyrighted footage** and the tricks that get it past Seedance's filter. That is against team rules 1 and 3.
- **Studio takes in the cut.** Takes are planning samples of non-UI plates. A take reaches a cut only through `promo gen register` and the
  `generated-plates` gate.
