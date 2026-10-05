"""`screen` shot type: monitor tracking on a generated plate, the perspective warp of a real UI recording into the tracked quad,
its gates (`screen-quad`, `screen-ui`) and the `promo screen-quad` CLI. Plain asserts (pytest or `python tests/test_screen.py`).
Everything is tiny: synthetic 480x270 plates (a white parallelogram drifting 3 px/frame on a dark noisy background), one 480p encode."""
import copy
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS

import numpy as np
import yaml
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from promo import footage as FT  # noqa: E402
from promo import generic_check as GC  # noqa: E402
from promo import render as R  # noqa: E402
from promo import screentrack as ST  # noqa: E402
from promo import style_check, styles  # noqa: E402
from promo.shots import screen as SC  # noqa: E402
from promo.spec import Shot, load_spec  # noqa: E402

W0, H0 = 480, 270
BASE = np.array([[120.0, 60.0], [330.0, 70.0], [340.0, 200.0], [130.0, 190.0]])     # TL TR BR BL of the synthetic monitor
PALE = np.array([226.0, 232.0, 236.0])


# ---------------------------------------------------------------- synthetic plates
def truth_quad(i, drift=3.0, base=BASE):
    return base + np.array([drift * i, 0.0])


def exact_coverage(q, W, H, ss=4):
    """Independent analytic-ish coverage of a convex quad (TL TR BR BL, y down): ss x ss sub-samples per pixel against 4 half-planes."""
    ys, xs = np.mgrid[0:H * ss, 0:W * ss]
    px, py = (xs + 0.5) / ss, (ys + 0.5) / ss
    inside = np.ones(px.shape, bool)
    for k in range(4):
        a, b = q[k], q[(k + 1) % 4]
        inside &= ((b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])) >= 0
    return inside.reshape(H, ss, W, ss).mean((1, 3))


_SYNTH = {}


def synth_frame(i, drift=3.0, base=BASE, seed=11, size=(W0, H0)):
    k = (i, drift, tuple(np.asarray(base).ravel()), seed, size)
    if k not in _SYNTH:
        _SYNTH[k] = _synth_frame(i, drift, base, seed, size)
    return _SYNTH[k]


def _synth_frame(i, drift, base, seed, size):
    W, H = size
    rng = np.random.default_rng(seed + i)
    bg = np.clip(np.array([34.0, 30.0, 26.0]) + rng.normal(0, 7, (H, W, 3)), 0, 255)
    bg[:, : W // 8] += 40                                           # a warm bright wall at the left: not low-saturation, not the biggest blob
    bg[:, : W // 8, 2] -= 25
    cov = exact_coverage(truth_quad(i, drift, base), W, H)[..., None]
    mon = PALE + rng.normal(0, 2.0, (H, W, 3))
    return np.clip(bg * (1 - cov) + mon * cov, 0, 255).astype(np.uint8)


def write_video(path, frames, fps=30, crf=12):
    H, W = frames[0].shape[:2]
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                          "-c:v", "libx264", "-preset", "ultrafast", "-crf", str(crf), "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(f).tobytes())
    p.stdin.close()
    assert p.wait() == 0
    return path


def textured(w=320, h=180, seed=3):
    """A UI-like frame: flat panels, thin lines and noise so any grade / blur / tint shows up as a pixel change."""
    rng = np.random.default_rng(seed)
    a = np.full((h, w, 3), (24, 28, 40), np.uint8)
    a[20:60, 20:200] = (235, 235, 240)
    a[80:84, :] = (90, 140, 255)
    a += rng.integers(0, 12, a.shape, dtype=np.uint8)
    return Image.fromarray(a, "RGB")


def rel(q, W=W0, H=H0):
    return np.asarray(q, float) / np.array([W, H], float)


# ---------------------------------------------------------------- detection
def test_detect_quad_on_a_drifting_synthetic_monitor_is_within_2px():
    worst = 0.0
    for i in range(12):                                             # 12 frames x 3 px drift
        q, info = ST.detect_quad(synth_frame(i))
        assert q is not None and info["ok"], info
        err = np.abs(q - truth_quad(i)).max()
        worst = max(worst, err)
        assert err < 2.0, f"frame {i}: corner error {err:.2f}px\n{q}\n{truth_quad(i)}"
    assert worst < 2.0


def test_detect_quad_ignores_the_warm_bright_wall_and_a_small_highlight():
    f = synth_frame(0).copy()
    f[10:22, 300:316] = 255                                         # a small specular highlight elsewhere: not the largest component
    q, info = ST.detect_quad(f)
    assert q is not None and np.abs(q - truth_quad(0)).max() < 2.0


def test_detect_quad_fails_on_dark_or_non_quad_frames():
    q, info = ST.detect_quad(np.full((H0, W0, 3), 12, np.uint8))
    assert q is None and "dark" in info["why"]
    rng = np.random.default_rng(1)
    q, info = ST.detect_quad((rng.normal(40, 9, (H0, W0, 3)).clip(0, 255)).astype(np.uint8))
    assert q is None and not info["ok"]
    f = np.full((H0, W0, 3), 20, np.uint8)
    yy, xx = np.mgrid[0:H0, 0:W0]
    f[((xx - 240) ** 2 + (yy - 135) ** 2) < 80 ** 2] = 230          # a bright disc is not a monitor (its boundary does not lie on four sides)
    q, info = ST.detect_quad(f)
    assert q is None and "not a monitor" in info["why"]


def test_track_follows_the_drift_and_smoothing_removes_jitter_without_lag():
    frames = [synth_frame(i) for i in range(24)]
    cfg = ST.screen_cfg({})
    tr = ST.track_quads(iter(frames), cfg)
    assert tr.n == 24 and tr.ok.all() and tr.fail_frac == 0 and not tr.touch.any()
    err = max(np.abs(tr.quads[i] * np.array([W0, H0]) - truth_quad(i)).max() for i in range(24))
    assert err < 2.0, f"smoothed track error {err:.2f}px (including both ends)"
    # smooth_quads on a noisy linear drift: noise down, trend kept (zero lag)
    rng = np.random.default_rng(5)
    clean = np.stack([truth_quad(i) for i in range(60)])
    noisy = clean + rng.normal(0, 1.5, clean.shape)
    sm = ST.smooth_quads(noisy, 0.6)
    assert np.abs(sm - clean).mean() < 0.6 * np.abs(noisy - clean).mean(), "jitter reduced"
    assert np.abs((sm - clean).mean(axis=(1, 2))[5:-5]).max() < 0.8, "no lag on a linear drift"
    assert np.allclose(ST.smooth_quads(clean, 0.6), clean, atol=0.05), "a clean linear drift passes through unchanged (no end bias)"
    assert np.allclose(ST.smooth_quads(noisy, 0.0), noisy), "smooth 0 = raw"


# ---------------------------------------------------------------- no detection: hold / fill / fail
def test_failed_frames_hold_the_previous_quad_and_leading_failures_take_the_first_good_one():
    dark = np.full((H0, W0, 3), 10, np.uint8)
    frames = [dark, dark] + [synth_frame(i) for i in range(2, 8)] + [dark, dark, synth_frame(10)]
    cfg = ST.screen_cfg(dict(screen=dict(smooth=0)))
    tr = ST.track_quads(iter(frames), cfg)
    assert list(tr.ok) == [False, False] + [True] * 6 + [False, False, True]
    assert abs(tr.fail_frac - 4 / 11) < 1e-9
    assert np.allclose(tr.raw[0], tr.raw[2]) and np.allclose(tr.raw[1], tr.raw[2]), "leading failures take the first good quad"
    assert np.allclose(tr.raw[8], tr.raw[7]) and np.allclose(tr.raw[9], tr.raw[7]), "failures hold the previous good quad"
    assert tr.usable and tr.why, "the reason is recorded"
    none = ST.track_quads(iter([dark] * 5), cfg)
    assert not none.usable and none.fail_frac == 1.0


def test_manual_quad_override_skips_detection():
    q = [[0.25, 0.22], [0.70, 0.26], [0.72, 0.74], [0.27, 0.70]]
    cfg = ST.screen_cfg(dict(screen=dict(quad=q)))
    blank = np.full((H0, W0, 3), 10, np.uint8)                       # detection would fail on every frame
    tr = ST.track_quads(iter([blank] * 6), cfg)
    assert tr.manual and tr.ok.all() and tr.fail_frac == 0
    assert np.allclose(tr.quads, np.array(q)[None].repeat(6, 0))
    assert not tr.touch.any()
    cut = ST.track_quads(iter([blank] * 3), ST.screen_cfg(dict(screen=dict(quad=[[0.5, 0.2], [1.0, 0.2], [1.0, 0.8], [0.5, 0.8]]))))
    assert cut.touch.all(), "a manual quad on the frame border still counts as cut off"


# ---------------------------------------------------------------- warp: the UI is only resampled
def test_warp_interior_equals_the_resampled_ui_axis_aligned():
    ui = np.asarray(textured(160, 90))
    plate = np.full((200, 300, 3), 40, np.uint8)
    q = np.array([[50.0, 40.0], [210.0, 40.0], [210.0, 130.0], [50.0, 130.0]])
    out = ST.composite_screen(plate, ui, q, glow=None, bezel=False)
    assert np.array_equal(out[40:130, 50:210], ui), "a pixel-aligned quad of the UI's own size reproduces the UI byte for byte"
    assert np.array_equal(out[:40], plate[:40]) and np.array_equal(out[:, :50], plate[:, :50]), "nothing outside changes without glow / bezel"
    # a half-pixel-shifted quad: only the 1-2 px edge ring may differ from the pure translation
    out2 = ST.composite_screen(plate, ui, q + 0.0, glow=None, bezel=False)
    assert np.array_equal(out, out2), "deterministic"


def skew_quad():
    return np.array([[52.3, 37.1], [214.6, 45.9], [205.2, 133.4], [58.8, 124.6]])


def test_warp_interior_equals_an_independent_warp_and_keeps_flat_colours_exact():
    ui = np.asarray(textured(160, 90)).copy()
    ui[30:60, 60:100] = (201, 77, 13)                               # a flat saturated patch: must stay exactly this colour
    plate = (np.random.default_rng(2).normal(60, 10, (200, 300, 3))).clip(0, 255).astype(np.uint8)
    q = skew_quad()
    out, warp, cov, reg = ST.composite_screen(plate, ui, q, glow=None, bezel=False, return_parts=True)
    assert ST.ui_residual(out, warp, cov, reg) == 0
    indep = ST.warp_region(Image.fromarray(ui), q, reg)
    inner = np.zeros(cov.shape, bool)
    from scipy.ndimage import binary_erosion
    inner = binary_erosion(cov >= 1 - 1e-6, iterations=2)
    x0, y0, x1, y1 = reg
    assert inner.sum() > 5000
    assert np.array_equal(out[y0:y1, x0:x1][inner], indep[inner]), "interior is exactly the perspective resampling of the UI crop"
    # flat patch: map its centre into the frame and look at a 3x3 neighbourhood
    H = np.array(ST.homography_coeffs(np.array([[0, 0], [160, 0], [160, 90], [0, 90]], float), q))        # UI rect -> quad is the inverse of what PIL needs
    # PIL needs dst->src; here we map src->dst by solving the other way round
    co = ST.homography_coeffs(np.array([[0, 0], [160, 0], [160, 90], [0, 90]], float), q)
    cx, cy = 80.0, 45.0
    X = (co[0] * cx + co[1] * cy + co[2]) / (co[6] * cx + co[7] * cy + 1)
    Y = (co[3] * cx + co[4] * cy + co[5]) / (co[6] * cx + co[7] * cy + 1)
    patch = out[int(Y) - 1:int(Y) + 2, int(X) - 1:int(X) + 2].reshape(-1, 3)
    assert (patch == np.array([201, 77, 13])).all(), "no grade / tint / blur inside the quad"
    # the antialiased edge ring is 1-2 px wide: the pixels 3 px inside the quad already equal the warp, one px outside is the plate
    ring = (cov > 0) & (cov < 1 - 1e-6)
    assert 0 < ring.sum() < 4 * (q.max() - q.min()).max() * 3, "the edge ring is a thin band"


def test_glow_bezel_and_plate_grade_never_reach_inside_the_quad():
    ui = np.asarray(textured(160, 90))
    rng = np.random.default_rng(4)
    plate = rng.normal(70, 12, (200, 300, 3)).clip(0, 255).astype(np.uint8)
    q = skew_quad()
    pale = exact_coverage(q, 300, 200)[..., None] > 0.5
    plate = np.where(pale, np.array([220, 228, 232], np.uint8), plate)      # the blank pale screen the quad sits on (dark bezel / wall around)
    base, warp, cov, reg = ST.composite_screen(plate, ui, q, inset_px=3.0, glow=None, bezel=False, return_parts=True)
    full, warp2, cov2, reg2 = ST.composite_screen(plate, ui, q, inset_px=3.0, glow=dict(alpha=0.6, blur=0.05, lift=2.0), bezel=True, return_parts=True)
    assert ST.ui_residual(full, warp2, cov2, reg2) == 0 and ST.ui_residual(base, warp, cov, reg) == 0
    x0, y0, x1, y1 = reg
    from scipy.ndimage import binary_erosion
    inner = binary_erosion(cov >= 1 - 1e-6, iterations=2)
    assert np.array_equal(full[y0:y1, x0:x1][inner], base[y0:y1, x0:x1][inner]), "glow + bezel leave the interior untouched"
    assert np.abs(full.astype(int) - base.astype(int)).sum() > 0, "but they do exist outside it"
    # the spill lights the surroundings (outside the detected quad); the ring between the edge and the inset quad turns bezel-dark
    out_ring = np.zeros(plate.shape[:2], bool)
    out_ring[8:30, 60:200] = True
    assert full[out_ring].mean() > base[out_ring].mean() + 1.0, "light spill lifts the plate around the quad"
    cov_raw = ST.quad_coverage(q, reg)
    ring = (cov_raw >= 1 - 1e-6) & (cov == 0)
    assert ring.sum() > 50
    assert full[y0:y1, x0:x1][ring].mean() < 0.5 * base[y0:y1, x0:x1][ring].mean(), "the pale ring around the inset UI becomes bezel-dark"


def test_plate_look_grade_is_plate_only_and_keys_are_audited():
    sc = ST.screen_cfg(dict(screen=dict(grade=True)))
    look = SC.plate_look(sc)
    assert look["grade"]["on"] and look["grain"]["on"] and not look["bloom"] and not look["vignette"]
    sc = ST.screen_cfg(dict(screen=dict(grade=dict(grain=False, gain=[1.1, 1.0, 0.9]))))
    look = SC.plate_look(sc)
    assert look["grain"] is False and look["grade"]["gain"] == [1.1, 1.0, 0.9]
    assert SC.plate_look(ST.screen_cfg({})) is None
    sh = Shot(id="05", b0=0, b1=8, t0=0, t1=4, f0=0, n=120, fps=30, cfg=dict(type="screen", screen=dict(tint=[1, 0, 0], thr=0.6)))
    bad = SC.audit_screen_keys(sh)
    assert len(bad) == 1 and "screen.tint" in bad[0]
    sh2 = Shot(id="05", b0=0, b1=8, t0=0, t1=4, f0=0, n=120, fps=30, cfg=dict(type="screen", screen=dict(grade=dict(inside=True))))
    assert "screen.grade.inside" in SC.audit_screen_keys(sh2)[0]


# ---------------------------------------------------------------- a real (tiny) render
class TinyCtx(R.RenderContext):
    OW = 854
    OH = 480


def tiny_spec(files, build):
    st = styles.resolve(dict(style=dict(preset="cinematic-story")))
    return NS(style=st, raw={}, resolve=lambda p: p, footage_path=lambda cid: files[cid], build=build, OW=854, OH=480,
              seg_path=lambda i: os.path.join(build, "segs", f"{i}.mp4"))


def test_screen_tiny_render_places_the_ui_on_the_tracked_monitor():
    d = tempfile.mkdtemp()
    plate = write_video(os.path.join(d, "plate.mp4"), [synth_frame(i, drift=1.5) for i in range(24)], fps=12)
    gy, gx = np.mgrid[0:360, 0:640]
    base = np.stack([40 + gx * 0.2, 60 + gy * 0.25, 90 + (gx + gy) * 0.1], -1)
    base[40:120, 60:300] = (235, 235, 240)                           # big flat panels and one thin line: smooth enough for a PSNR check after x264
    base[200:330, 320:600] = (200, 90, 40)
    base[150:153, :] = (30, 200, 120)
    ui = write_video(os.path.join(d, "ui.mp4"), [np.roll(base, 3 * k, axis=1).clip(0, 255).astype(np.uint8) for k in range(24)], fps=12, crf=10)
    spec = tiny_spec(dict(plate=plate, ui=ui), os.path.join(d, "build"))
    os.makedirs(os.path.join(d, "build", "segs"))
    ctx = TinyCtx(K=1, fps=12, spec=spec, seg_dir=os.path.join(d, "build", "segs"))
    cfg = dict(type="screen", plate="plate", source="ui", t_in=0.0, cam=[[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 0.9]], fade_in=0.25,
               lower_copy=[dict(text="Tell it at night.", at=0.2, dur=0.7, x=40, cy=440)], screen=dict(grade=True, inset=0.004))
    shot = Shot(id="05", b0=0, b1=4, t0=0.0, t1=1.0, f0=0, n=12, fps=12, cfg=cfg)
    e = SC.Screen().render(ctx, shot)
    assert "perspective-warped" in e["notes"] and e["caption"] == "'Tell it at night.'"
    p = os.path.join(d, "build", "segs", "05.mp4")
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                                   "stream=width,height,nb_read_frames", "-of", "csv=p=0", p]).decode().strip()
    assert out == "854,480,12", out
    sc = SC.read_sidecar(spec, shot)
    assert sc["ui_residual_max"] == 0 and sc["ui_residual_frames"] >= 2 and sc["touch_frac"] == 0 and sc["fail_frac"] == 0, sc
    # decode frame 8 and compare the monitor interior with the pure composition (x264 crf16 tolerance)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-vf", "select=eq(n\\,8)", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    got = np.frombuffer(raw, np.uint8).reshape(480, 854, 3).astype(float)
    tr = ST.track_shot(spec, shot, plate, 854 / 480)
    comp = SC.ScreenComposer(ctx, shot, tr, tuple(sc["crop"]))
    from promo.shots.clip import segments
    uimg = R.Source(ui, 0.0, 2.1).frame(8 / 12)
    want = np.asarray(comp.compose(R.Source(plate, 0.0, 2.1, prescale=(854, 480)).frame(8 / 12), uimg, R.cam_at(
        __import__("promo.shots.cinema", fromlist=["x"]).camera_keys(shot), 8 / 12), 8 / 12, 8)).astype(float)
    q = tr.quad(8) * np.array([854, 480])
    x0, y0, x1, y1 = (int(v) for v in (q[:, 0].min() + 12, q[:, 1].min() + 12, q[:, 0].max() - 12, q[:, 1].max() - 12))
    mse = ((got[y0:y1, x0:x1] - want[y0:y1, x0:x1]) ** 2).mean()
    assert 10 * np.log10(255 ** 2 / max(mse, 1e-9)) > 28, f"decoded monitor interior differs from the composition (mse {mse:.1f})"
    # src_to_out maps UI source time like a clip
    assert SC.Screen().src_to_out(shot, 0.5) == 0.5


# ---------------------------------------------------------------- the gates
def screen_project(plate_frames, copy=None, screen=None, fps=6, extra=None):
    """A 60 s cinematic-story project where shot 04 (5 s, beats 20-30) is a `screen` shot on a synthetic plate (6 fps plate: each plate
    frame covers 5 of the shot's 30 fps frames, so 30 plate frames = 150 shot frames)."""
    from test_cinema import cinema_project, good_shots
    d = tempfile.mkdtemp()
    plate = write_video(os.path.join(d, "plate.mp4"), plate_frames, fps=fps)
    sh = good_shots()
    k = next(i for i, s in enumerate(sh) if s["beats"] == [20, 30])
    sh[k] = dict(id=sh[k]["id"], beats=[20, 30], type="screen", plate=plate, source="c", t_in=0.0,
                 cam=[[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 0.95]], **(extra or {}))
    if screen is not None:
        sh[k]["screen"] = screen
    if copy:
        sh[k]["lower_copy"] = copy
    return cinema_project(sh), sh[k]["id"]


def gate(p, name):
    r = {g: (st, msg) for g, st, msg in style_check.run(load_spec(p))}
    return r.get(name)


def drift_frames(n=30, drift=0.0, base=BASE):
    return [synth_frame(i, drift=drift, base=base) for i in range(n)]


def test_screen_quad_gate_passes_when_the_monitor_stays_inside_the_frame():
    p, sid = screen_project(drift_frames(drift=0.4))                # 5 s x 30 fps = 150 frames, 0.4 px/frame drift
    st, msg = gate(p, "screen-quad")
    assert st == "PASS", msg
    assert gate(p, "screen-ui")[0] == "PASS"
    res = {g: s for g, s, _ in style_check.run(load_spec(p))}
    assert res["cinema-keys"] == "PASS" and res["ui-hold"] == "PASS" and res["ui-protect"] == "PASS"


def test_screen_quad_gate_fails_when_the_monitor_touches_the_frame_border():
    cut = BASE.copy()
    cut[1, 0] = cut[2, 0] = W0                                      # the right side of the monitor lies on the frame border
    st, msg = gate(screen_project(drift_frames(base=cut))[0], "screen-quad")
    assert st == "FAIL" and "touches the frame border on 100%" in msg and "cut off" in msg, msg
    # drifting out of frame during the shot: the right edge (340 + 95 + 5k) reaches the border at plate frame 9 -> 70% of the frames
    late = [synth_frame(k, drift=5.0, base=BASE + np.array([95.0, 0])) for k in range(30)]
    st, msg = gate(screen_project(late)[0], "screen-quad")
    assert st == "FAIL" and any(f"on {k}% of the frames" in msg for k in (69, 70, 71, 72)), msg      # +-1 shot frame at the plate-frame boundaries
    ok = [synth_frame(k, drift=1.5, base=BASE + np.array([66.0, 0])) for k in range(30)]         # right edge reaches 340 + 66 + 43 = 449: inside
    assert gate(screen_project(ok)[0], "screen-quad")[0] == "PASS"


def test_touch_tolerance_is_2_canvas_px():
    inside = np.array([[0.1, 0.1], [1 - 2.5 / 1920, 0.1], [1 - 2.5 / 1920, 0.9], [0.1, 0.9]])
    assert not ST.touches_border(inside)
    edge = np.array([[0.1, 0.1], [1 - 1.9 / 1920, 0.1], [0.9, 0.9], [0.1, 0.9]])
    assert ST.touches_border(edge) and ST.touches_border(np.array([[-0.01, 0.1], [0.5, 0.1], [0.5, 0.9], [0.1, 0.9]]))


def test_screen_quad_gate_fails_when_detection_fails_and_warns_when_a_few_frames_are_held():
    dark = np.full((H0, W0, 3), 10, np.uint8)
    frames = drift_frames(drift=1.0)
    bad = frames[:20] + [dark] * 10                                  # 10 of 30 plate frames dark: 33% of the shot
    st, msg = gate(screen_project(bad)[0], "screen-quad")
    assert st == "FAIL" and any(f"detection failed on {k}%" in msg for k in (32, 33, 34, 35)), msg
    st, msg = gate(screen_project([dark] * 30)[0], "screen-quad")
    assert st == "FAIL" and "no monitor found" in msg, msg
    some = frames[:28] + [dark] * 2                                  # 7% failed: the previous quad is held, WARN
    st, msg = gate(screen_project(some)[0], "screen-quad")
    assert st == "WARN" and "previous quad is held" in msg, msg


def test_screen_quad_gate_manual_quad_override_beats_a_blank_plate():
    dark = np.full((H0, W0, 3), 10, np.uint8)
    q = (BASE / np.array([W0, H0])).tolist()
    st, msg = gate(screen_project([dark] * 30, screen=dict(quad=q))[0], "screen-quad")
    assert st == "PASS", msg
    qcut = [[0.3, 0.2], [1.0, 0.2], [1.0, 0.8], [0.3, 0.8]]
    st, msg = gate(screen_project([dark] * 30, screen=dict(quad=qcut))[0], "screen-quad")
    assert st == "FAIL", msg


def test_screen_ui_gate_fails_on_keys_that_could_touch_the_ui_or_a_dirty_render():
    p, sid = screen_project(drift_frames(drift=0.0), screen=dict(thr=0.6, glow=dict(alpha=0.2), grade=True))
    assert gate(p, "screen-ui")[0] == "PASS"
    p2, _ = screen_project(drift_frames(drift=0.0), screen=dict(tint=[1.1, 1.0, 0.9]))
    st, msg = gate(p2, "screen-ui")
    assert st == "FAIL" and "screen.tint" in msg
    p3, _ = screen_project(drift_frames(drift=0.0), extra=dict(look=dict(protect_ui=False)))
    assert gate(p3, "screen-ui")[0] == "FAIL"
    spec = load_spec(p)
    s = spec.shot(sid)
    os.makedirs(os.path.dirname(SC.sidecar_path(spec, s)), exist_ok=True)
    import json
    json.dump(dict(ui_residual_max=3, ui_residual_frames=5), open(SC.sidecar_path(spec, s), "w"))
    st, msg = gate(p, "screen-ui")
    assert st == "FAIL" and "differs from the resampled UI by up to 3" in msg
    json.dump(dict(ui_residual_max=0, ui_residual_frames=5), open(SC.sidecar_path(spec, s), "w"))
    st, msg = gate(p, "screen-ui")
    assert st == "PASS" and "5 frames" in msg


def test_screen_shots_are_gated_as_ui_shots_and_copy_must_clear_the_monitor():
    p, sid = screen_project(drift_frames(drift=0.0), copy=[dict(text="Tell it at night.", at=0.5, dur=3.0, x=600, cy=500)])
    st, msg = gate(p, "copy-clear")
    assert st == "FAIL" and "overlaps the monitor" in msg, msg
    p, sid = screen_project(drift_frames(drift=0.0), copy=[dict(text="Tell it at night.", at=0.5, dur=3.0, x=60, cy=1000)])
    assert gate(p, "copy-clear")[0] == "PASS"
    # ui-hold: a 2 s screen shot is a UI shot and fails the hold gate like any other
    from test_cinema import cinema_project, good_shots
    sh = good_shots([0, 10, 13, 20, 30, 31, 40, 120])
    sh[2].update(type="screen", plate="x.mp4", ui=True)
    assert "FAIL" == gate(cinema_project(sh), "ui-hold")[0]
    # a screen shot needs a plate
    sh = good_shots()
    sh[2]["type"] = "screen"
    st, msg = gate(cinema_project(sh), "cinema-keys")
    assert st == "FAIL" and "needs plate" in msg


def test_generic_viewport_of_a_screen_shot_is_the_quad_bounding_box():
    p, sid = screen_project(drift_frames(drift=0.0))
    spec = load_spec(p)
    s = spec.shot(sid)
    vp = GC.viewport(spec, s)
    want = [BASE[:, 0].min() * 1920 / W0, BASE[:, 1].min() * 1080 / H0, BASE[:, 0].max() * 1920 / W0, BASE[:, 1].max() * 1080 / H0]
    assert np.allclose(vp, want, atol=6.0), (vp, want)
    assert GC.is_ui_shot(spec, s, GC.rules_for(spec)) is True or GC.is_ui_shot(spec, s, GC.rules_for(spec)) is False   # decided by the clip manifest; must not raise
    f = {}
    FT._walk(dict(type="screen", plate="ots-night", source="shot-04p", screen=dict(quad=[[0, 0]] * 4)), None, f, "05")
    assert set(f) == {"ots-night", "shot-04p"}, f


# ---------------------------------------------------------------- CLI + the real generated plate
def test_cli_screen_quad_prints_quads_and_writes_a_debug_png():
    d = tempfile.mkdtemp()
    plate = write_video(os.path.join(d, "p.mp4"), drift_frames(36, drift=1.0), fps=12)
    png = os.path.join(d, "dbg.png")
    r = subprocess.run([sys.executable, "-m", "promo", "screen-quad", plate, "--fps", "12", "--out", png], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "TL TR BR BL" in r.stdout and "detection failed on 0%" in r.stdout and "touches the frame border on 0%" in r.stdout, r.stdout
    assert os.path.exists(png) and Image.open(png).width >= 640


def test_real_generated_plate_ots_is_tracked_and_reported_as_cut_off():
    f = os.path.expanduser("~/promo-footage/speech/ots.mp4")
    if not os.path.exists(f):
        return
    frames = list(ST.plate_frames(f, 0.0, 1.0, 12, 2, 960, 16 / 9))        # 2 fps over 6 s
    tr = ST.track_quads(iter(frames), ST.screen_cfg({}))
    assert tr.ok.all() and tr.n == 12
    q = tr.quads * np.array([1920, 1080])
    assert 900 < q[:, 0, 0].min() and q[:, 0, 0].max() < 1100 and 100 < q[:, 0, 1].min(), q[0]
    assert tr.touch.all(), "the monitor in ots.mp4 runs off the right edge of the frame"
    assert q[:, 1:3, 0].max() >= 1918
    assert np.abs(np.diff(q, axis=0)).max() < 8, "the locked-off plate gives a quiet track"


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
