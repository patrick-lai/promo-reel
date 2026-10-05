# Pending / open items (as of 2026-10-05)

## 5 Oct 2026 session (video-quality uplift)
- Built: `promo watch` (watch any video: sheets, cuts, transcript, audio metrics), `promo gen` + `promo needs` (agent-supplied generated non-UI plates and the capture/generate handoff), presets `cinematic-story` and `horizon`, draft scale `--scale 0.5`, original scores `promo.score`.
- Two new promos: projects/commission-ai-night-shift (dots-style) and projects/commission-ai-horizon (Opus-style); council notes in each `rounds/` and `docs/review.md`. Council mean ~3.4/5, pass bar 4.2 not reached after the 3-round cap: human decides.
- 48 tests fail on this Mac and on the untouched base commit (Linux fonts under /usr/share/fonts/..., /workspace paths); none are new.
- `promo watch` under-detects dissolves/dark cuts (use ffmpeg scene detection at 0.12 for dark UI footage).
- Owner sign-off still needed on "Wake up to merged PRs." (demo shows a human merge step).


- **Merge PR #1** (capture scripts): https://github.com/patrick-lai/promo-reel/pull/1 (approved, 16/16 tests).
  It is already merged *locally* into integrate/v1 (the talk show needs its hero footage manifest); the PR itself is untouched.
- **End-card link:** GitHub repo vs a landing page (Patrick's call).
- **Sonnet 5.5 critique in Cursor:** needs Patrick's Cursor sign-in, in his 1:1 chat with Promo Video Director.
  Critique packs exist for hero v5, anime v11 and talk show v7.
- **Hero shot 11:** could switch to `shot-11-dpr2-r4` at ~1.3x (less empty canvas; the empty-frame WARN flags S11).
  The same take is an option for anime shot 15.
- **Versioned presets (not built):** `anime-opening@2`, `hero@2`, `livestream@2`, tuned from
  /workspace/promo/reference-study/metrics.csv and section (e) of style-guide-v1.md.
  - Anime: cut rate as a curve, 0.3 cuts/s rising to ~1.0 between 45% and 67% of runtime. One marked long hold of
    7-12 s, at most one per video and only on the Workshop town wide shot, exempt from the long-hold WARN (which stays
    on for everything else).
  - Hero: text on screen by 0.5 s; ~0.4 cuts/s with a montage peak of 0.7; words at 8-15% of frame height.
  - Talk show: layout changes every 5-7 s; WARN when a speaker turn runs over ~12 s.
  - Phrase-level beat sync by default, strict beat lock optional.
  - A `promo preset diff <project>` command.
- **Re-run the fresh Grok-agent eval** (run 1 scored 2.71).
- **Reference contact sheets** in /workspace/promo/reference-study: not yet scored by Zen.
- **Optional anime S03 send take:** rejected for now (composer sits low in frame; the generic reply after 8.0 s breaks
  the truth rule).
- Marketing's open items (copy study, X and LinkedIn drafts): /workspace/promo/marketing/pending.md
- Final cuts: /workspace/promo-reel-evals/anime-v11-preview.mp4, /workspace/promo-reel-evals/talkshow-preview-v7-styled.mp4,
  and the hero v5 1080 render (projects/commission-ai-hero/out/hero-v5-1080.mp4).

## Render budget: review in rounds, one full render per round (Patrick, 4 Oct 2026)

Patrick's rule: iterating one fix at a time burns tokens. Collect all feedback first, then do one full render.

1. **Cheap preview:** add `promo preview <project>`, which makes contact sheets, per-shot stills and a 540p draft in seconds. It must never run a full-resolution render.
2. **One feedback window:** each round has `projects/<p>/rounds/<n>/feedback.md`. Zen, Marketing and the Promo Video Director each add one consolidated list and a `signed-off: <name>` line. Late notes go to the next round.
3. **One full render:** `promo build --final` refuses to run unless the current round's feedback file has all three sign-offs. Rendering at 1080p or 4K requires `--final`, and anything without it is capped at 540p. Run `promo check` once after the final render.
4. **Round cap:** at most 3 rounds per video before it goes to Patrick. The CLI should warn when round 4 starts.
