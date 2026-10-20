# live2d/: offline Live2D host renderer (prototype)

```
cd live2d && npm ci && cd ..          # pixi.js 6 + pixi-live2d-display 0.4 + playwright-core (node_modules gitignored)
promo live2d fetch                    # official Cubism Core + Hiyori + Mao from cubism.live2d.com, sha256-checked, into live2d/media/
promo live2d render --model hiyori --wav host_a.wav --partner-wav host_b.wav --out build/hiyori.mov [--size 420x500] [--seed 11] [--lines lines.yaml] [--supersample 1]
promo live2d lag build/hiyori.mouth.npy host_a.wav
promo live2d models                   # samples + your own: expressions, motions, moods, mouth (vowels or open + form)
promo live2d stills --model mao --moods --out /tmp/mao-moods.png      # a real portrait per mood
promo live2d add ~/Models/mychar --id mine --name "My Char" --type commissioned --licence "..." --source https://... [--credit "Art: ..., Rig: ..."]
```
- **Performance** (`promo/perform.py`, used by every host render): vowel mouth shapes from the voice (LPC formants
  -> A/I/U/E/O weights; rigs with ParamA..ParamO get the five shapes, rigs with ParamMouthForm get a form), moods
  (a model's `moods:` map of exp3 files / parameter targets, else generic targets on standard Cubism IDs; exp3
  Add / Multiply / Overwrite with fades), gestures (nod, shake, tilt, lean_in, laugh_bounce, shrug, look_away, or
  `motion:<name>` sampled from the model's motion3 curves), prosody (stressed syllables raise the brows and drive
  head beats), gaze (saccades, `look:` camera | partner | screen | away, eyes lead and the head follows), listening
  nods at the partner's phrase ends, body sway, shoulder breath and a resting smile. Per-line keys come from
  `vo.lines[]` (`promo/podcast.py` timed_lines). The renderer gets per-parameter LAYER lists
  `[{mode: set|blend|add|mul, v, w?}]`; page.html starts each driven parameter from its `set` value (or its default)
  every frame, so add / mul never pile up, and clamps like Cubism (`perform.apply_layers` is the same maths; the
  readback test compares them).
- **Supersampling:** `supersample=2` (the default for podcast shows at 1080p and up) renders at 2x, writes
  premultiplied pixels and lets ffmpeg scale down with lanczos and un-premultiply, so line art stays crisp with no
  dark fringes. `1` is the draft mode.
- **Your own model:** `promo live2d add` registers a Cubism 3+ model in `<config dir>/live2d-models.yaml` (next to
  the promo config; `PROMO_LIVE2D_MODELS` overrides). Files are never copied or committed. It needs `--type
  own|commissioned|original`, a licence and a source (collaboration / third-party characters are refused),
  measures the framing anchors from renders (eyes / mouth by blinking and opening the mouth, the silhouette top
  and width from alpha), and maps moods from expression names (smile, angry, sad, surprise, ...). A sample id
  cannot be replaced. The free samples are good but not commissioned-VTuber art; your own rig is how a show gets there.
- **Mesh avatars (opt-in):** `promo live2d add <Mesh Avatar Studio project>` (a folder with `rig.json` + `built/`; see
  `skills/mesh-avatar/SKILL.md`) registers a character made from one illustration with `renderer: mesh`, behind the same
  licence gate (`--likeness own --consent ...` for a character drawn from the person, which renders but fails the show
  gates: AGENTS.md rule 1). Only such entries take this path: `render.mjs` loads `mesh-page.html` with the npm runtime
  `mesh-avatar` (MIT) instead of `page.html`; the same `perform.py` layers are flattened and mapped onto its parameters
  (`promo/mesh_avatar.py`; vowel shapes from the A/I/U/E/O weights, moods through eye smile, cheeks and brows). Every runtime
  parameter is set each frame, so nothing animates on its own. The picture's cut edges fade unless the layer edge hides
  them, and framing sets a bust cut at the bottom (`cut_bottom`) on the panel's bottom edge, keeping the shared head size.
  A bust that stops at mid-chest therefore sits low in the panel; in a speaker cam give it `place: {<host>: {size: l}}` if
  `podcast-framing` reports a subtitle over its face, or draw the picture down to the waist. `add` warns when the avatar
  has only some drawn eyes / mouths (the runtime then erases the eyes on every blink).
- **Chromium:** Playwright's `chromium_headless_shell` from `~/.cache/ms-playwright` if present (or `PROMO_CHROMIUM`).
  WebGL2 runs on SwiftShader, so no GPU is needed.
- **Deterministic:** the page virtualises `performance.now`/`Date.now` and seeds `Math.random`. The model clock
  advances exactly `1/fps` per frame and the wall clock is never read. Blink, breath, sway, nods and mouth are
  per-frame tracks precomputed in Python (`promo/live2d.py`), so the library's own idle motions, eye blink and
  breath are switched off. Physics and pose still run at the fixed step, and frames are read back with
  `gl.readPixels`.
  `tests/test_live2d.py::test_render_deterministic` renders twice and compares hashes.
- **Output:** `.mov` = ProRes 4444 with alpha, `.webm` = VP9 with alpha, a directory or `%05d.png` = PNG
  sequence, and `--bg green` gives an opaque green-screen H.264.
- **Shared box:** node and ffmpeg run under `nice -n 10`, ffmpeg uses `-threads 2`, and every render holds the
  box-wide heavy-work lock for its whole run (a lock other heavy jobs on the machine can share: set `PROMO_HEAVY_LOCK` to the same path as e.g. your test gates;
  default `/tmp/promo-reel-heavy.lock`; replaces the old `/tmp/promo-live2d-render.lock`). It blocks until the lock is
  free and logs every 30 s while waiting. See `../promo/lock.py`.
- **Lip sync:** 10 ms envelope with a centred 43 ms window, a fast attack (12 ms), a 60 ms in-speech release and
  a 20 ms close ease. The follower's delay is measured and removed. Each frame samples its own display interval
  centre. The render report includes lip lag from the track, from the parameter values read back per frame, and
  from the rendered pixels (mouth probe).
- **Framing:** every model carries `anchors` in `assets.yaml`, in model units (fraction of the model's width and
  height): `head_top` (skull/hair top, not hats or ahoge), `chin`, `chest` (mid-chest), `cx` (face centre) and
  `mouth` (pixel lip-lag probe), plus `top` = top of the FULL silhouette incl. hat/ahoge (first alpha row of a
  full-body render, minus a little for physics sway). `promo/live2d.py` `framing` applies one rule to all models:
  the head is `HEAD_FRAC` (0.48) of the PANEL tall, its top at `HEAD_TOP_AT` (0.14), face centred; with anime
  proportions the panel bottom lands at mid-chest. Hosts are clipped by their panel's sides and bottom only:
  anything above the head (Mao's hat) breaks out above the panel into the layer's headroom. `promo.livestream
  .host_layout` widens the gap above each panel to fit its break-out (and only shrinks the common head scale if
  panels would get too small), and `livestream-framing` fails if a silhouette is clipped at the top or its
  break-out overlaps the header, another host, the screen, the chat strip or a keep-clear rectangle. A new model just needs its anchors: render it full-body (`render_stills` /
  `probe_face` measure the eye and mouth lines from pixels) and read the rest off a grid. `promo check`
  (`livestream-framing`) and `tests/test_live2d.py` check that hosts get the same head height and scale.
- **Sidecars:** each render writes `<out>.report.json`, `<out>.mouth.npy` and `<out>.readback.json`.
- **Licences:** of the samples only Live2D Original Characters are accepted, and a `live2d_credits` end card (full notice + model
  credits, >= 28 px at 1080p, >= 2 s) is required by `promo check` (for your own models only when they carry a credit; the
  sample notice is left out when no sample is in the show). See
  `../docs/live2d-licences.md`.
