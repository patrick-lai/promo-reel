"""Ethereal renderer: hard snaps and cuts, a visible mosaic, a pullback that is reached, a halo outside the panel, the camera limits,
and the eased intro / outro (picture and music together).

Plain asserts (pytest). Everything is composed in memory (no ffmpeg); the audio is synthetic.
"""
import os
import sys
import tempfile

import numpy as np
import yaml
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_dialects import INK, _applied, _comp, _frame, _item  # noqa: E402
from test_designed import _Ctx, _spec  # noqa: E402

from promo import bookends as BK  # noqa: E402
from promo import designed  # noqa: E402
from promo import grade as G  # noqa: E402
from promo import render as R  # noqa: E402
from promo.shots import cinema as CN  # noqa: E402
from promo.spec import Shot, load_spec  # noqa: E402

W, H = 854, 480
SR = 48000


def _ui_png(d, size=(480, 270)):
    p = os.path.join(d, "ui.png")
    rng = np.random.default_rng(5)
    a = np.full((size[1], size[0], 3), (28, 32, 46), np.uint8)
    a[20:60, 20:260] = (235, 235, 240)
    a += rng.integers(0, 14, a.shape, dtype=np.uint8)
    Image.fromarray(a, "RGB").save(p)
    return p


def _panel_comp(cfg, spec, n=60, fps=30):
    shot = Shot(id="02", b0=0, b1=n / fps * 2, t0=3.0, t1=3.0 + n / fps, f0=90, n=n, fps=fps, cfg=cfg)
    return CN.Composer(_Ctx(K=1, fps=fps, font_path=R.DEFAULT_FONT, spec=spec, seg_dir="."), shot, spec), shot


def _ethereal_look(**panel):
    look = {"backdrop": dict(fill=dict(designed.ETHEREAL_FILL), warm=0.0)}
    look.update({k: v for k, v in designed.ETHEREAL_LOOK.items()})
    look["panel"] = dict(designed.ETHEREAL_PANEL["floating"], **designed.ETHEREAL_PANEL_FX, **panel)
    return look


# ---------------------------------------------------------------- 1. snaps and cuts are hard
def test_snap_and_cascade_alpha_is_only_ever_0_or_1():
    for anim in ("snap", "cascade"):
        it = dict(text="Wake up to merged PRs", at=0.5, dur=1.2, anim=anim)
        alphas = {CN.kinetic_pose(it, t / 120.0)[1] for t in range(0, 300)}
        scales = {CN.kinetic_pose(it, t / 120.0)[0] for t in range(0, 300)}
        assert alphas == {0.0, 1.0} and scales == {1.0}, f"{anim}: no fade, no scale, no in-between"


def test_a_snap_frame_has_no_intermediate_text_alpha():
    comp = _comp([_item(anim="snap", brackets=True, anchors=True)])
    before, on, held = (_frame(comp, t, i) for i, t in enumerate((0.45, 0.5, 0.55)))
    assert np.array_equal(on, held), "the selection box and the words are fully there from the first frame"
    changed = np.abs(on - before).sum(axis=2) > 0
    # inside every glyph / bracket stroke the pixel is the ink itself or the plate; only the antialiased rim of a stroke is in between
    ink_like = (np.abs(on - np.array(INK)).sum(axis=2) <= 3)
    assert ink_like[changed].mean() > 0.45, "solid ink, not a half-transparent crossfade of ink over plate"
    plate = before
    mixed = changed & ~ink_like & (np.abs(on - plate).sum(axis=2) > 0)
    assert mixed.sum() < 0.65 * changed.sum(), "the rest is the one-pixel antialiased edge"


def test_ethereal_cuts_have_no_entrance_fade_and_only_the_first_shot_floats_in():
    info, spec = _applied()
    shots = designed.compile_shots(info["plan"]["designed"], sfx={"tick", "whoosh"})
    for s in shots:
        assert "in" not in ((s.get("look") or {}).get("panel") or {}), "a panel never fades or scales in on a cut"
        assert "fade_in" not in s and "fade_out" not in s
    s2 = next(s for s in spec.shots if s.cfg.get("look", {}).get("panel"))
    comp = CN.Composer(_Ctx(K=1, fps=30, font_path=R.DEFAULT_FONT, spec=spec, seg_dir="."), s2, spec)
    settled = comp._box(s2.dur / 2)
    first = comp._box(0.0)
    assert comp.entr is None and comp.fin == 0 and first == settled and first[2] == 1.0, "frame 0 of a cut is the settled picture"


# ---------------------------------------------------------------- 2. the mosaic is visible
def _mosaic_scene(d, **resolve):
    spec = _spec(clip=_ui_png(d))
    cfg = dict(source="x", cam=[[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 1.0]], look=_ethereal_look(),
               resolve=dict(kind="mosaic", dur=1.8, steps=7, from_blocks=4, **resolve))
    comp, shot = _panel_comp(cfg, spec, n=90)
    return spec, comp, shot


def _runs(row):
    """Lengths of the runs of identical pixels along a row."""
    ch = np.nonzero(np.any(np.diff(row, axis=0) != 0, axis=1))[0]
    return np.diff(np.concatenate([[-1], ch, [len(row) - 1]]))


def test_mosaic_steps_are_visibly_blocky_through_bloom_and_grain():
    with tempfile.TemporaryDirectory() as d:
        spec, comp, shot = _mosaic_scene(d)
        cfg = CN.mosaic_cfg(shot.cfg)
        assert cfg["from_blocks"] == 4 and cfg["steps"] == 7
        cols = [CN.mosaic_cols(cfg, k) for k in range(7)]
        assert cols[0] == 4 and cols[-1] == CN.MOSAIC_MAX_BLOCKS and cols == sorted(set(cols)), "every step is a coarser-to-finer change"
        assert all(b / a > 1.2 for a, b in zip(cols, cols[1:])), "and each one is big enough to see"
        for k in range(7):
            t = (k + 0.5) * cfg["dur"] / cfg["steps"]
            fr = _frame_img(comp, t)
            band = fr[8:40]                          # backdrop above the panel
            runs = np.concatenate([_runs(row) for row in band[::6]])
            assert abs(np.median(runs) - W / cols[k]) < 0.15 * W / cols[k] + 1, f"step {k}: blocks of {W / cols[k]:.0f}px, not a blurred gradient"
            if k < 4:
                step = np.abs(np.diff(band[0][::max(1, W // cols[k])].astype(float), axis=0)).mean()
                assert step > 1.0, f"step {k}: neighbouring blocks differ visibly ({step:.2f} levels)"
        sharp = _frame_img(comp, cfg["dur"] + 0.1)[8:40]
        assert np.median(np.concatenate([_runs(r) for r in sharp[::6]])) <= 3, "after the last step the world is sharp (grain and gradient)"


def test_the_mosaic_never_touches_the_ui_panel_and_applies_to_a_plate_without_footage():
    with tempfile.TemporaryDirectory() as d:
        spec, comp, shot = _mosaic_scene(d)
        a, b = _frame_img(comp, 0.05), _frame_img(comp, 1.9)
        x0, y0, x1, y1 = (int(v) for v in comp._box(0.0)[0])
        inner = (slice(y0 + 14, y1 - 14), slice(x0 + 14, x1 - 14))
        assert np.array_equal(a[inner], b[inner]), "the panel pixels are identical before and after the resolve"
        assert not np.array_equal(a[:30], b[:30]), "the world around it is what changes"
        plate = dict(ui=False, look=dict(backdrop="none", plate_fill=dict(designed.ETHEREAL_FILL)), resolve=dict(kind="mosaic", dur=1.0, steps=5, from_blocks=4))
        c2, _ = _panel_comp(plate, _spec(), n=30)
        p0, p1 = _frame_img(c2, 0.0), _frame_img(c2, 1.2)
        assert np.median(_runs(p0[100])) > 100 and not np.array_equal(p0, p1), "a footage-less plate shot resolves too (it used to skip the effect)"


def _frame_img(comp, t, i=0):
    return np.asarray(comp.compose(Image.open(comp.spec.footage_path("x")).convert("RGB") if comp.spec.footage_path("x") else None,
                                   (0.5, 0.5, 1.0), t, i), np.int32)


# ---------------------------------------------------------------- 3. the pullback is reached
def test_pullback_reaches_its_target_width_and_reveals_the_backdrop():
    with tempfile.TemporaryDirectory() as d:
        spec = _spec(clip=_ui_png(d))
        base = dict(source="x", look=_ethereal_look(w=0.58), cam=[[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 1.0]])
        for pb, end_w in ((dict(w=0.40, start=0.0), 0.40), (dict(scale=0.4, start=0.0), 0.58 * 0.4), (True, 0.58 * CN.PULLBACK_DEFAULT_SHRINK)):
            comp, shot = _panel_comp(dict(base, pullback=pb), spec, n=90)
            w0, _, _ = CN.panel_params(comp.look, shot, 0.0, shot.dur)
            wf, _, dim1 = CN.panel_params(comp.look, shot, shot.dur, shot.dur)
            assert abs(w0 - 0.58) < 1e-9 and abs(wf - end_w) < 1e-9, pb
            b0, b1 = comp._box(0.0)[0], comp._box(shot.dur)[0]
            assert (b1[2] - b1[0]) / (b0[2] - b0[0]) < 0.8, "the panel on screen is at least a fifth smaller"
        comp, shot = _panel_comp(dict(base, pullback=dict(w=0.40, start=0.0, until=1.5)), spec, n=150)
        near = CN.panel_params(comp.look, shot, shot.dur - 1.5, shot.dur)[0]
        assert abs(near - 0.40) < 1e-9 and CN.panel_params(comp.look, shot, shot.dur, shot.dur)[0] == near, "target reached `until` s before the end and held"
        mid = CN.panel_params(comp.look, shot, shot.dur / 3, shot.dur)[0]
        assert 0.40 < mid < 0.58
        a, z = _frame_img(comp, 0.0), _frame_img(comp, shot.dur - 0.05)
        bg0 = np.abs(a - a[2, 2]).sum(axis=2) < 40
        assert (np.abs(z - z[2, 2]).sum(axis=2) < 40).sum() > bg0.sum() * 1.15, "more of the frame is backdrop at the end"


def test_a_pullback_that_barely_shrinks_is_warned():
    info, spec = _applied()
    path = info["path"]
    raw = yaml.safe_load(open(path).read())
    i = next(n for n, s in enumerate(raw["shots"]) if (s.get("look") or {}).get("panel"))
    w0 = raw["shots"][i]["look"]["panel"]["w"]
    for pb, bad in ((dict(w=w0 * 0.95), True), (dict(scale=0.6), False)):
        raw["shots"][i]["pullback"] = pb
        mut = os.path.join(os.path.dirname(path), "pb.yaml")
        yaml.safe_dump(raw, open(mut, "w"), sort_keys=False)
        g = {n: (s, m) for n, s, m in designed.gates(load_spec(mut, plugins=False))}
        assert (g["designed-camera"][0] == "WARN" and "barely shows" in g["designed-camera"][1]) is bad


# ---------------------------------------------------------------- 4. the halo stays outside the panel
def test_halo_is_outside_the_panel_silhouette_and_never_on_the_ui():
    rng = np.random.default_rng(1)
    ui = Image.fromarray(rng.integers(0, 40, (200, 360, 3), dtype=np.uint8))          # a dark UI
    bd = Image.new("RGB", (W, H), (240, 232, 238))                                    # a pale plate
    box = G.panel_box((W, H), 0.42, 0.45)
    pw, ph = box[2] - box[0], box[3] - box[1]
    pan = ui.resize((pw, ph))
    plain = dict(designed.ETHEREAL_PANEL["floating"], shadow=False, rim=False, glow=False)
    with_halo = dict(plain, halo=dict(alpha=0.5, blur=0.012, spread=0.003, color=[40, 50, 90]))
    a = np.asarray(G.dof_backdrop(pan, box, (W, H), panel=plain, backdrop=bd), np.int32)
    b = np.asarray(G.dof_backdrop(pan, box, (W, H), panel=with_halo, backdrop=bd), np.int32)
    x0, y0, x1, y1 = box
    r = int(plain["radius"] * W / 1920) + 2
    inside = (slice(y0 + r, y1 - r), slice(x0 + r, x1 - r))
    assert np.array_equal(a[inside], b[inside]), "not one UI pixel changes"
    assert np.array_equal(a[inside], np.asarray(pan, np.int32)[r:ph - r, r:pw - r])
    ring = b[y0 - 6:y0 - 1, x0 + 40:x1 - 40].astype(float).mean()
    far = b[5:20, 5:60].astype(float).mean()
    assert ring < far - 6, "the panel has a soft edge against the pale plate"
    assert np.array_equal(a[:8], b[:8]) and np.array_equal(a[:, :8], b[:, :8]), "and it fades out well before the frame edge"
    assert designed.ETHEREAL_PANEL_FX["halo"]["on"] and G.panel_fx_cfg(dict(halo=False))["halo"] is None


# ---------------------------------------------------------------- 5. the camera limits
def _gates(info, mutate):
    raw = yaml.safe_load(open(info["path"]).read())
    mutate(raw["shots"])
    path = os.path.join(os.path.dirname(info["path"]), "cam.yaml")
    yaml.safe_dump(raw, open(path, "w"), sort_keys=False)
    return {g: (s, m) for g, s, m in designed.gates(load_spec(path, plugins=False))}


def test_ethereal_camera_limits_pass_a_5s_push_fail_fast_ones_and_keep_whip_and_shake_failing():
    assert designed.ETHEREAL_MAX_DRIFT == dict(pan_per_s=0.02, zoom_per_s=0.04)
    info, _ = _applied()
    g = _gates(info, lambda sh: sh[1].update(cam=[[0, 0.5, 0.5, 1.0], [5.0, 0.5, 0.5, 0.86, "smooth"]]))
    assert g["designed-camera"][0] == "PASS", g["designed-camera"]
    g = _gates(info, lambda sh: sh[1].update(cam=[[0, 0.5, 0.5, 1.0], [5.0, 0.5, 0.5, 0.78, "smooth"]]))
    assert g["designed-camera"][0] == "FAIL" and "zoom/s" in g["designed-camera"][1], "0.044 zoom/s is over the cap"
    g = _gates(info, lambda sh: sh[1].update(cam=[[0, 0.45, 0.5, 1.0], [5.0, 0.56, 0.5, 1.0, "smooth"]]))
    assert g["designed-camera"][0] == "FAIL" and "pan/s" in g["designed-camera"][1], "0.022 pan/s is over the cap"
    g = _gates(info, lambda sh: sh[1].update(cam=[[0, 0.5, 0.5, 1.0], [5.0, 0.7, 0.5, 1.0, "smooth"]]))
    assert g["designed-camera"][0] == "FAIL"
    g = _gates(info, lambda sh: sh[1].update(cam=[[0, 0.49, 0.5, 1.0], [5.0, 0.59, 0.5, 1.0, "smooth"]]))
    assert g["designed-camera"][0] == "PASS", "0.02 pan/s is the cap itself"
    for key in ("whip", "shake"):
        g = _gates(info, lambda sh, k=key: sh[1].update({k: True}))
        assert g["designed-camera"][0] == "FAIL" and key in g["designed-camera"][1]


def test_a_constant_rate_zoom_and_a_cut_that_fades_are_called_out():
    info, _ = _applied()
    g = _gates(info, lambda sh: sh[1].update(cam=[[0, 0.5, 0.5, 1.0], [5.0, 0.5, 0.5, 0.88, "linear"]]))
    assert g["designed-camera"][0] == "WARN" and "constant rate" in g["designed-camera"][1]
    g = _gates(info, lambda sh: sh[2].update(fade_in=0.4))
    assert g["designed-camera"][0] == "FAIL" and "hard cuts" in g["designed-camera"][1]
    g = _gates(info, lambda sh: sh[2].setdefault("kinetic_copy", [dict(text="Go to bed", at=0.0, dur=2.0, anim="pop")]))
    assert g["designed-camera"][0] in ("WARN", "FAIL")


def test_ethereal_compile_eases_the_push_under_the_cap():
    info, _ = _applied()
    des = info["plan"]["designed"]
    shots = designed.compile_shots(des)
    for r, s in zip(des["shots"], shots):
        for k0, k1 in zip(s.get("cam", []), s.get("cam", [])[1:]):
            assert k1[4] == "smooth"
        if "cam" in s:
            dz = abs(s["cam"][-1][3] - s["cam"][0][3]) / r["seconds"]
            assert dz <= designed.ETHEREAL_MAX_DRIFT["zoom_per_s"] + 1e-9
    held = [abs(s["cam"][-1][3] - s["cam"][0][3]) for r, s in zip(des["shots"], shots) if "cam" in s and r["seconds"] >= 4.5 and r["framing"] != "plate"]
    assert held and max(held) >= 0.08, "a 5 s hold gets a real push, not a few percent"


# ---------------------------------------------------------------- 6. eased intro and outro
def _film_spec(clip=None, duration=3.0, raw=None):
    spec = _spec(clip=clip)
    spec.raw = raw if raw is not None else {"plan": {"designed": {"dialect": {"name": "ethereal"}}}}
    spec.duration = duration
    return spec


def _luma(a):
    return float(np.asarray(a, np.float32).mean())


def test_bookend_defaults_are_ethereal_and_configurable_per_project_and_preset():
    r = BK.resolve({"plan": {"designed": {"dialect": {"name": "ethereal"}}}})
    assert r["intro"] == dict(dur=1.1, ease="out", rise=0.03, from_scale=0.94) and r["outro"] == dict(hold_s=1.5, fade_s=1.8, ease="inout")
    assert BK.resolve({}) == dict(intro=None, outro=None) and BK.resolve({"plan": {"designed": {"dialect": {"name": "kinetic"}}}}) == dict(intro=None, outro=None)
    mine = BK.resolve({"plan": {"designed": {"dialect": {"name": "ethereal"}}}, "output": {"outro": {"fade_s": 2.0}, "intro": False}})
    assert mine["intro"] is None and mine["outro"]["fade_s"] == 2.0 and mine["outro"]["hold_s"] == 1.5
    preset = BK.resolve({"style": {"bookends": {"intro": {"dur": 1.2}, "outro": {"hold_s": 2.0, "fade_s": 1.5, "ease": "ease-in-out"}}}})
    assert preset["intro"]["dur"] == 1.2 and preset["outro"]["ease"] == "inout" and preset["outro"]["hold_s"] == 2.0
    assert BK.curve(0.5, "out") == 0.875 and BK.curve(0.5, "inout") == 0.5 and BK.curve(0, "out") == 0 and BK.curve(1, "inout") == 1


def test_intro_floats_in_with_an_ease_out_cubic_over_about_a_second():
    with tempfile.TemporaryDirectory() as d:
        spec = _film_spec(_ui_png(d), duration=4.0)
        cfg = dict(source="x", cam=[[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 1.0]], look=_ethereal_look())
        shot = Shot(id="01", b0=0, b1=8, t0=0.0, t1=4.0, f0=0, n=120, fps=30, cfg=cfg)
        comp = CN.Composer(_Ctx(K=1, fps=30, font_path=R.DEFAULT_FONT, spec=spec, seg_dir="."), shot, spec)
        assert abs(comp.fin - 1.1) < 1e-9 and comp.fin_ease == "out" and comp.entr["rise"] == 0.03
        src = Image.open(_ui_png(d)).convert("RGB")
        lum = [_luma(comp.compose(src, (0.5, 0.5, 1.0), t, i)) for i, t in enumerate((0.0, 0.2, 0.55, 1.1, 2.0))]
        assert lum[0] < 1.0, "opens from black"
        assert lum[1] > 0.45 * lum[4], "ease-out: most of the light is there in the first fifth of the intro"
        assert lum[:4] == sorted(lum[:4]) and lum[3] > 0.97 * lum[4]
        top = [comp._box(t)[0][1] for t in (0.0, 0.3, 1.1)]
        w = [comp._box(t)[0][2] - comp._box(t)[0][0] for t in (0.0, 1.1)]
        assert top[0] > top[1] > top[2] - 0.5 and w[0] < w[1], "the panel rises and grows into its place"
        later = Shot(id="02", b0=8, b1=16, t0=4.0, t1=8.0, f0=120, n=120, fps=30, cfg=cfg)
        c2 = CN.Composer(_Ctx(K=1, fps=30, font_path=R.DEFAULT_FONT, spec=spec, seg_dir="."), later, spec)
        assert c2.fin == 0 and c2.entr is None, "only the first shot of the film"


def test_outro_fades_the_last_frames_to_black_and_a_project_can_turn_it_off():
    with tempfile.TemporaryDirectory() as d:
        spec = _film_spec(_ui_png(d), duration=6.0)
        cfg = dict(source="x", cam=[[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 1.0]], look=_ethereal_look(),
                   kinetic_copy=[dict(text="Your crew", at=0.0, dur=6.0, size_pct=7, anim="snap", uppercase=False, outline=False, shadow=False, color=INK, weight="Light")])
        n, fps = 180, 30
        shot = Shot(id="09", b0=0, b1=12, t0=0.0, t1=6.0, f0=0, n=n, fps=fps, cfg=cfg)
        comp = CN.Composer(_Ctx(K=1, fps=fps, font_path=R.DEFAULT_FONT, spec=spec, seg_dir="."), shot, spec)
        assert comp.fout == 1.8 and comp.fout_ease == "inout"
        src = Image.open(_ui_png(d)).convert("RGB")
        frame = lambda i: comp.compose(src, (0.5, 0.5, 1.0), i / fps, i)    # noqa: E731
        settle = _luma(frame(int((6.0 - 1.8 - 0.1) * fps)))
        assert settle > 60, "type and panel are fully there when the fade starts"
        assert _luma(frame(n - 1)) < 1.0, "the last frame is black"
        mid = _luma(frame(int((6.0 - 0.9) * fps)))
        assert abs(mid / settle - 0.5) < 0.06, "half-way through the fade it is half as bright (ease-in-out is symmetric)"
        assert abs(_luma(frame(int((6.0 - 1.8 - 0.01) * fps))) - settle) / settle < 0.02, "no fade before the last 1.8 s: the end card holds"
        off = _film_spec(_ui_png(d), duration=6.0, raw={"plan": {"designed": {"dialect": {"name": "ethereal"}}}, "output": {"outro": False}})
        c2 = CN.Composer(_Ctx(K=1, fps=fps, font_path=R.DEFAULT_FONT, spec=off, seg_dir="."), shot, off)
        assert c2.fout == 0 and _luma(c2.compose(src, (0.5, 0.5, 1.0), (n - 1) / fps, n - 1)) > 40


# ---- audio: the same curve, a tail that is faded and never cut
def _music(seconds, sr=SR, f=220.0):
    t = np.arange(int(seconds * sr)) / sr
    x = 0.25 * np.sin(2 * np.pi * f * t) + 0.12 * np.sin(2 * np.pi * f * 1.5 * t)
    return np.stack([x, x], axis=1)


def _faded(x, fade=1.8, ease="inout"):
    return x * BK.fade_out_array(len(x), SR, fade, ease)[:, None]


def _rms_track(x, win=0.05, sr=SR):
    k = int(win * sr)
    return np.array([BK.rms_db(x[i:i + k]) for i in range(0, len(x) - k + 1, k)])


def test_audio_fade_matches_the_picture_curve_and_the_last_200ms_are_silent():
    x = _faded(_music(8.0))
    tail = x[-int(0.2 * SR):]
    assert BK.rms_db(tail) < -55.0, "the final 200 ms are near silent"
    assert BK.rms_db(x[int(5.0 * SR):int(5.5 * SR)]) > -16.0, "and the bed is fully there before the fade starts"
    g = BK.fade_out_array(len(x), SR, 1.8, "inout")
    for t_left in (1.8, 1.35, 0.9, 0.45, 0.1):
        i = len(x) - int(round(t_left * SR))
        assert abs(g[i] - BK.fade_gain(i / SR, len(x) / SR, 1.8, "inout")) < 2e-3, "picture and music read the same gain"
    assert g[len(x) - int(0.9 * SR)] > 0.49 and g[len(x) - int(0.9 * SR)] < 0.51


def test_no_abrupt_rms_drop_in_the_last_two_seconds_except_the_fade_and_a_cut_would_fail_it():
    MAX_DROP_DB = 6.0                                        # per 100 ms, while the bed is still within 24 dB of its own level

    def worst_drop(x):
        r = _rms_track(x[-2 * SR:], win=0.1)
        bed = float(r[:3].max())
        d = (r[:-1] - r[1:])[r[:-1] > bed - 24.0]
        return float(d.max()) if len(d) else 0.0
    ok = _faded(_music(8.0))
    assert worst_drop(ok) < MAX_DROP_DB, "a 1.8 s ease-in-out fade falls smoothly: the only steep part is already inaudible"
    cut = _music(8.0)
    cut[-int(0.5 * SR):] = 0.0
    assert worst_drop(cut) > 40.0, "a truncated bed is exactly what this check exists to catch"
    short = _music(6.2)
    tail = BK.extend_tail(short, SR, int(8.0 * SR))
    assert len(tail) == int(8.0 * SR) and BK.rms_db(tail[int(7.0 * SR):]) > -20.0, "a bed that ends early is extended, not left silent"
    zeroed = _music(8.0)
    zeroed[int(6.5 * SR):] = 0.0
    assert worst_drop(zeroed) > 40.0
    ext = BK.extend_tail(zeroed, SR, len(zeroed))
    assert BK.rms_db(ext[-int(0.5 * SR):]) > -20.0
    assert worst_drop(_faded(ext)) < MAX_DROP_DB and BK.rms_db(_faded(ext)[-int(0.2 * SR):]) < -55.0
    assert np.abs(ext).max() <= 0.4, "the join does not click or pile up"


def test_mix_applies_the_ethereal_outro_to_the_master_and_extends_the_music():
    src = open(os.path.join(ROOT, "promo", "mix.py")).read()
    assert "BK.extend_tail(music, SR, N)" in src and "BK.fade_out_array(N, SR, fade, ease)" in src
    assert 'outro["fade_s"]' in src


def test_the_end_card_must_settle_before_the_fade_out():
    info, _ = _applied()
    g = _gates(info, lambda sh: None)
    assert g["designed-pace"][0] == "PASS"
    g = _gates(info, lambda sh: sh[-1]["kinetic_copy"][0].update(at=4.2))
    assert g["designed-pace"][0] == "WARN" and "must settle" in g["designed-pace"][1]
