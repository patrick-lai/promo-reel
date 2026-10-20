# Vendored: mesh-avatar (wrapper only)

- Source: https://github.com/shinshin86/mesh-avatar-studio
- Commit: 784b8abc3c80bc3915b4cd9894f20859a0949936 (19 Oct 2026)
- Licence: MIT, Copyright (c) 2026 Yuki Shindo (LICENSE kept verbatim). Upstream's Miko sample is under AITuber OnAir's
  character terms, and its bundled MediaPipe model under Apache-2.0; neither is copied here.
- Copied: nothing but LICENSE. SKILL.md and skill.yaml are written for promo-reel; the tool runs from its own checkout
  (`~/.promo-reel/tools/mesh-avatar-studio`, pinned to the commit above), because it is a full Node app (editor, runtime,
  Python layer builder) and its sample art may not be redistributed as an asset.
- Here it is a helper only (`primary: false`, phrase `triggers:`). Its renders cannot enter a promo-reel build yet (see
  SKILL.md, "What promo-reel can do with it today").
- Update: `git -C ~/.promo-reel/tools/mesh-avatar-studio pull`, re-run its checks and a test avatar, then bump the commit here
  and in SKILL.md's Install block.
