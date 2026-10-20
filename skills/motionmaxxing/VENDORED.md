# Vendored: motionmaxxing

- Source: https://github.com/Tejashmakwana/motionmaxxing
- Commit: 8c8ec0f2a6f6c9a0da15cd24f7b1298ab298368c (6 Oct 2026)
- Licence: Apache-2.0 (LICENSE, NOTICE kept verbatim). Bundled third parties keep their own licences: GSAP
  (`runtime/vendor/gsap.min.js`, GreenSock standard licence), three.js and opentype.js (`runtime/hero3d/vendor/*.LICENSE`),
  Inter (`runtime/fonts/OFL.txt`).
- Not copied: `.git/`, `docs/media/` (21 MB of README gifs and mp4s).
- Local changes: the SKILL.md frontmatter `description` (so it loads for motion-design work in this repo) and a
  "Modified for promo-reel" comment under it; `scripts/look.py` drops the timecode overlay when ffmpeg has no `drawtext`
  (Homebrew's ffmpeg has none, and look.py failed on the contact sheet). Nothing else.
- Here it is a helper only (`skill.yaml` `primary: false`, `triggers:`): promo-reel or cinetic leads, AGENTS.md rules 1-5 win,
  its gates (`scripts/look.py`, `scripts/lint.mjs`) are advisory and `promo check` decides. Do not run `install.sh`; the skill
  ships with this repo's pack. `taste/` holds the upstream author's verdicts, not this team's.
- Update: clone upstream at a newer commit, `rsync -a --exclude .git --exclude docs/media` into `skills/motionmaxxing/`,
  re-apply the description, bump this file.
