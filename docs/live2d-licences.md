# Live2D licences, notices and rules for the `livestream` hosts

Checked on 2026-10-04 (AEDT) against live2d.com. Re-read the pages before every publish: Live2D can amend
these terms at any time, and the newest version applies from its revision date. **This file is a summary for the
team. It is not legal advice.** The Japanese text of each agreement is the one that governs.

Nothing listed here is in git. `promo live2d fetch` downloads every file from Live2D's own servers, checks it
against the sha256 in `live2d/assets.yaml`, and unpacks it under `live2d/media/` (gitignored). We never
redistribute the models or the Cubism Core (`live2d/media/`, `*.moc3` and `*.zip` are gitignored).

## 1. Models in use

| id | Model | Type | Download page | Archive (sha256) | Created by |
|---|---|---|---|---|---|
| `hiyori` | Hiyori Momose (PRO, `hiyori_pro_t11`) | **Live2D Original Character** | https://www.live2d.com/en/learn/sample/momose-hiyori/ | `https://cubism.live2d.com/sample-data/bin/hiyori/hiyori_en.zip` (`1e4254d561f2a151562aa67036d78e17e4ffee08869b8ce10ab6052a05e2b3a4`) | Illustration: Kani Biimu; Modeling: Live2D |
| `mao` | Niziiro Mao (PRO, `mao_pro`) | **Live2D Original Character** | https://www.live2d.com/en/learn/sample/niziiro-mao/ | `https://cubism.live2d.com/sample-data/bin/mao/mao_en.zip` (`c6bc527b3d8877f0735f4099b34c2b9bb17162d77b5957687839c74d374449d3`) | Illustration: Live2D Inc.; Modeling: Live2D Inc. |

**Excluded:** Jin Natori. The sample-data terms page lists him as a **Collaboration Character** (with Tsumiki
Harugasa), and Collaboration Characters may not be used for commercial purposes. `live2d/assets.yaml` marks him
`character_type: collaboration`, so the renderer and `promo check` refuse him. Hatsune Miku and Unity-chan are
*externally licensed characters* under third-party guidelines, so they are refused too.

### Copyright notice (exact text, required on every published work that uses these models)
From "Terms of Use for Live2D Cubism Sample Data" (https://www.live2d.com/en/learn/sample/model-terms/), "Copyright
Notice". Hiyori and Mao use the same notice. Neither download page gives a per-model notice, and the page points to
these terms:

- **Where a description field exists** (YouTube, NicoNico, Bilibili, app or game descriptions, ...):
  > This content uses sample data owned and copyrighted by Live2D Inc. The sample data are utilized in accordance with terms and conditions set by Live2D Inc. This content itself is created at the author's sole discretion.
- **Where long text is hard or impossible** (X/Twitter, Facebook, Instagram, TikTok, ...):
  > This content uses sample data owned and copyrighted by Live2D Inc.

In the video, the `live2d_credits` shot type renders an end card with the **long** notice plus each model's credit
(from `live2d/assets.yaml`) at body-text size (default 30 px, at least 28 px at 1080p), held at full opacity for at
least 2 s. `promo check` (`livestream-licence`) fails without it. There is no micro-text notice in the header. A
human must still put the long notice in the description when the video is published.
Model ReadMe credits (from each archive's `ReadMe.txt`): Hiyori: "Illustration：Kani Biimu / Modeling：Live2D".
Mao: "Illustration: Live2D Inc. / Modeling: Live2D Inc.".

### Individual terms of use (sample-data terms page)
- **Hiyori Momose:** "No changes of any kind to the design of this character are permitted." We only drive the
  model's own parameters (mouth, eyes, breath, head angle). Textures, meshes and design stay untouched.
- **Niziiro Mao:** no individual terms are listed.
- All samples: content where the character may seem to say or express erotic, violent or grotesque things, or
  that could upset viewers or make them misread the character image, is "unsuitable for use" (download pages,
  "Important notes").

## 2. Live2D Free Material License Agreement (v1.6, revised 2025-02-03)
https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html. It covers the sample models.
- **Who may use Original Characters commercially (s.2.1.3.1):** only **General Users** and **Small-Scale
  Enterprises**, meaning latest annual sales **below JPY 10 million** (s.1.22, 1.23). This excludes enterprises
  substantially managed by a company with sales of JPY 10 million or more (s.1.24), for example through majority
  ownership or voting control, a majority of shared officers, or substantial control. They may use them "irrespective of commercial or Non-commercial purposes".
- **Everyone else (s.2.1.3.2):** use is limited to "Internal or Supervision Purpose". A temporary promotional use
  needs Live2D's written approval, given in advance on application (Simple License Plan, https://www.live2d.com/business/SLP).
  **HUMAN:** confirm that the publishing entity qualifies before anything is published.
- **Collaboration Characters (s.2.1.4):** non-commercial only. Not usable for a product promo, so excluded.
- **Voice/sound data (s.2.1.3):** "Unless expressly permitted, the Customer may not use, or Distribute or
  Redistribute alternation of, the sound data included in the Material." We use no bundled voice data. Hosts are
  voiced by our own TTS or VO, and Natori's voice data was withdrawn in 2018 anyway.
- **Copyright notice (s.2.1.5):** show the notice that each character's terms designate (section 1 above).
- **No redistribution (s.4.1.1):** we do not commit, upload or share the model files. Only rendered video is published.
- **No modifications (s.4.1.2):** "may not modify (including significantly altering the original balance of the
  body ...), port, adapt, or translate the Material". Combined with Hiyori's terms, this means: do not edit
  textures, meshes or proportions, do not recolour, and do not turn the model into a new character. Framing
  (crop or scale of the whole model) and driving its own parameters is normal use of the model data.
- Other restrictions (s.4.1.7): do not remove Live2D notices. Do not use the material with middleware that competes
  with Live2D's. No illegal, obscene, violent, political or religious works. Do not cause confusion with Live2D's
  official products. Do not sell or distribute models made with third-party software that divert or deform the
  material.

## 3. Live2D Proprietary Software License Agreement (v2.1, revised 2025-02-03), Cubism Core
https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html. It covers
`live2dcubismcore.min.js` (header: "Live2D Cubism Core (C) 2019 Live2D Inc. All rights reserved. This file is
licensed pursuant to the license agreement below. This file corresponds to the 'Redistributable Code' in the
agreement."). It is fetched from `https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js`
(sha256 `25ae938cb4fe282ce189b357bcc97e603d1e1f7ec78bf04150d401c23cdc792f`).
- The licence allows use of the Software only to Publish Derivative Works (s.2.1). Publishing requires a separate
  **Live2D Publication License Agreement**, unless the exemption in **s.2.2** applies: **General Users, Small-Scale
  Enterprises (sales below JPY 10 million) and Qualified Educational Institutions** are exempt from that agreement
  and its fee. They must notify Live2D if sales go over JPY 10 million.
- Middle- and large-scale enterprises: a temporary promotional Publication may fall under the "Live2D Simple
  License Plan", which needs an application and written approval in advance (s.2.4).
- **Expandable Applications** (avatar, live-streaming or video-generator *products*, s.1.5) always need an
  application and approval, and are never exempt (s.2.2, 6.3). Our use is an internal render tool that outputs a
  finished promo video, not a distributed streaming app. **HUMAN:** confirm this reading with Live2D before shipping
  the tool to anyone else.
- No redistribution or bundling except as Redistributable Code inside a Derivative Work (s.5, 6.2). We do neither:
  the file is fetched per machine and gitignored. Do not modify it, reverse engineer it, or remove its notices
  (s.6.1, 6.4, 6.8).
- No service bureau (s.6.7): do not render for third parties that hold no licence.
- The Cubism Core must be the official runtime: pixi-live2d-display (MIT) bundles Live2D's Cubism *Framework*
  (Live2D Open Software License) and loads the official Core at runtime. We do not use a re-implementation.

## 4. Other third-party code (installed by npm into `live2d/node_modules/`, not committed)
- pixi.js 6.5.10 (MIT). pixi-live2d-display 0.4.0 (MIT, Copyright (c) 2020 Guan). It bundles the Live2D Cubism
  Framework under the Live2D Open Software License (https://www.live2d.com/eula/live2d-open-software-license-agreement_en.html).
- playwright-core 1.57.0 (Apache-2.0).
- The seeded random stream in `live2d/page.html` follows `createSeededRandom` from moeru-ai/airi
  `packages/motion-driver-magic` (MIT, Copyright (c) 2024-PRESENT Neko Ayaka). See `live2d/THIRD_PARTY.md`.

## 5. Publish checklist (HUMAN)
1. The publishing entity is a General User or Small-Scale Enterprise (sales below JPY 10 million, not controlled by
   a larger company), or it has written Live2D approval (Simple License Plan or Publication License).
2. The long copyright notice is in the description, and the end-card credit (notice + model credits) is readable.
3. No Collaboration or external characters. No bundled voice data. No edits to the models' design.
4. The content is not unsuitable under the sample terms (no erotic, violent or grotesque content, nothing that
   misrepresents the character).
