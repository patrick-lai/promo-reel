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
- **Cheap draft, then a final from the same task.** Every Studio take keeps the exact OpenRouter request it sent (pictures named by path,
  never re-uploaded). "Final at 720p" resends that request with only the resolution changed (`promo flow studio rerun`), after an inline
  confirm that shows the price and what is left of today's cap. Defaults: Seedance 2.5, 480p, 4 s, no sound (about $0.41); Seedance 1.5 Pro (about $0.05) and Grok Imagine Lite ($0.02 a second) stay in the list for cheap tries.
- **Money is shown before the click.**
  - The Generate button shows the price.
  - A take over the per-take limit ($0.50) or the daily cap ($2) is refused, with the reason shown.
  - The ledger keeps each take's estimate next to what OpenRouter billed.
- **A gallery of takes.** Every try is kept: the ones still being made (with a live clock), the finished ones (playable, with their real
  cost) and the failed ones (with OpenRouter's reason).
- **Start from a picture.** Any storyboard frame can be the first frame (image to video).
- **Camera presets.** Each preset adds one sentence to the prompt, and "What Seedance gets" shows the full prompt that is sent.
- **Review the prepared input before paying.** A picked start or end frame is shown large and must be ticked as free of app screens, text
  and logos before Generate turns on.
- **The agent describes the reference frame.** "Describe this frame" asks the agent to write the frame's setting (place, light, lens,
  mood) into a prompt the composer offers; words naming screens, apps, text or logos are refused (rule 1).
- **Start and end frame.** Models that list `last_frame` (Seedance 2.5) get an end-frame picker.
- **Edit mode (video to video).** "Restyle" sends a finished take to FLUX Video Edit with a prompt saying what changes. Only Studio takes and
  files with a generated sidecar are accepted: restyling a screen recording would edit the app's UI (rules 1 and 2).
- **Character swap.** "Swap character" on a take (`promo flow studio swap`, also any clip the person brings) prepares the clip on this Mac
  and sends it to Seedance 2.5 on OpenRouter as a video reference. Higgsfield is not used. Prep modes: **face mesh** (MediaPipe 478-point
  wireframe, talking head), **depth** (Depth Anything people over the real background), **both**. Isolated vocals are pitched +3 so Seedance
  can hear lip-sync; the original soundtrack is copied back onto the finished take. The product's own recordings are refused.
- **Depth pass.** `promo depth` runs Depth Anything V2 Small (ONNX, Apache-2.0) on this Mac: a depth map, and a 2.5D parallax clip over a
  generated still with the camera presets and optional depth of field. In the Studio it is the free "Depth parallax" model.

## What we did not take
- **Higgsfield itself.** Prep is local; the only paid call is Seedance (or FLUX Video Edit for restyle) on OpenRouter.
- **catbox uploads**: files travel as data URLs to OpenRouter only.
- **SAM 3 via Replicate.** Person cutout is the largest near blob of the local depth map, on this Mac.
- **Runway Aleph 2 and FLUX Video Upscale through OpenRouter.** Both are listed, but their API pages document no field for the input
  video (checked 2026-10-11). FLUX Video Edit documents `input_references` of type `video_url`, so it is the restyle model. Sending a
  video as a data URL is not confirmed by the docs (they confirm it for images); the first live restyle will show it.
- **Studio takes in the cut.** Takes are planning samples of non-UI plates. A take reaches a cut only through `promo gen register` and the
  `generated-plates` gate.
