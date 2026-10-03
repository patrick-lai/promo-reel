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
  box-wide heavy-work lock `flock /tmp/commission-ai-cargo.lock` for its whole run (the lock Commission-ai's
  pre-merge cargo test gates use; replaces the old `/tmp/promo-live2d-render.lock`). It blocks until the lock is
  free and logs every 30 s while waiting. See `../promo/lock.py`.
- **Lip sync:** 10 ms envelope with a centred 43 ms window, a fast attack (12 ms), a 60 ms in-speech release and
  a 20 ms close ease. The follower's delay is measured and removed. Each frame samples its own display interval
  centre. The render report includes lip lag from the track, from the parameter values read back per frame, and
  from the rendered pixels (mouth probe).
- **Sidecars:** each render writes `<out>.report.json`, `<out>.mouth.npy` and `<out>.readback.json`.
- **Licences:** only Live2D Original Characters are accepted, and a `live2d_credits` end card (full notice + model
  credits, >= 28 px at 1080p, >= 2 s) is required by `promo check`. See
  `../docs/live2d-licences.md`.
