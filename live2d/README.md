# live2d/: offline Live2D host renderer (prototype)

```
cd live2d && npm ci && cd ..          # pixi.js 6 + pixi-live2d-display 0.4 + playwright-core (node_modules gitignored)
promo live2d fetch                    # official Cubism Core + Hiyori + Mao from cubism.live2d.com, sha256-checked, into live2d/media/
promo live2d render --model hiyori --wav host_a.wav --partner-wav host_b.wav --out build/hiyori.mov [--size 420x500] [--seed 11]
promo live2d lag build/hiyori.mouth.npy host_a.wav
```
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
- **Licences:** only Live2D Original Characters are accepted, and a `live2d_credits` end card (full notice + model
  credits, >= 28 px at 1080p, >= 2 s) is required by `promo check`. See
  `../docs/live2d-licences.md`.
