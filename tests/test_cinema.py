"""cinematic-story preset: promo/grade.py look functions, the `cinema` shot type, preset + gates, scaffold.
Plain asserts (pytest or `python tests/test_cinema.py`). Everything is tiny: synthetic frames, one 480p encode of 12 frames."""
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

from promo import grade as G  # noqa: E402
from promo import render as R  # noqa: E402
from promo import style_check, styles  # noqa: E402
from promo.shots import cinema as CN  # noqa: E402
from promo.spec import Shot, SpecError, load_spec  # noqa: E402


# ---------------------------------------------------------------- helpers
def textured(w=320, h=180, seed=3):
    """A UI-like test frame: flat panels, thin lines and noise so any resampling or grading shows up as a pixel change."""
    rng = np.random.default_rng(seed)
    a = np.full((h, w, 3), (24, 28, 40), np.uint8)
    a[20:60, 20:200] = (235, 235, 240)
    a[80:84, :] = (90, 140, 255)
    a += rng.integers(0, 12, a.shape, dtype=np.uint8)
    return Image.fromarray(a, "RGB")


class TinyCtx(R.RenderContext):
    OW = 854                       # a 480p output: shots lay out in 1920x1080 canvas units scaled by OW / 1920
    OH = 480


def tiny_ctx(spec, seg_dir):
    return TinyCtx(K=1, fps=12, font_path=R.DEFAULT_FONT, spec=spec, seg_dir=seg_dir)


def fake_spec(clip=None, style=None):
    st = styles.resolve(dict(style=dict(preset="cinematic-story", **(style or {}))))
    return NS(style=st, raw={}, resolve=lambda p: p, footage_path=lambda cid: clip)


def mk_shot(cfg, n=12, fps=12, sid="01"):
    return Shot(id=sid, b0=0, b1=n / fps * 2, t0=0.0, t1=n / fps, f0=0, n=n, fps=fps, cfg=cfg)


# ---------------------------------------------------------------- grade.py
def test_grade_warm_low_key_and_pure():
    gray = Image.new("RGB", (64, 36), (128, 128, 128))
    g = np.asarray(G.grade(gray, **{k: v for k, v in G.DEFAULT_LOOK["grade"].items() if k != "on"}), np.int32)
    assert g[..., 0].mean() > g[..., 2].mean() + 8, "warm grade must push red over blue in the mids"
    assert g.mean() < 128 + 8
    black = np.asarray(G.grade(Image.new("RGB", (8, 8), (0, 0, 0)), lift=[-0.02] * 3), np.int32)
    assert black.max() <= 6, "blacks stay crushed"
    ident = G.grade(textured(), )
    assert np.array_equal(np.asarray(ident), np.asarray(textured())), "default parameters are the identity"


def test_grade_vignette_bloom_grain():
    flat = Image.new("RGB", (160, 90), (120, 120, 120))
    v = np.asarray(G.vignette(flat, strength=0.5), np.int32)
    assert v[45, 80, 0] == 120 and v[0, 0, 0] < 80, "centre untouched, corners darkened"
    spot = np.zeros((90, 160, 3), np.uint8)
    spot[40:50, 75:85] = 255
    b = np.asarray(G.bloom(Image.fromarray(spot), threshold=0.5, radius=0.08, strength=0.8), np.int32)
    assert b[45, 68, 0] > 0 and b[45, 68, 0] > b[45, 5, 0] and (b[40:50, 75:85] == 255).all(), "glow spreads, source stays"
    a = np.asarray(G.grain(flat, frame=4, amount=0.04, seed=7))
    assert np.array_equal(a, np.asarray(G.grain(flat, frame=4, amount=0.04, seed=7))), "grain is deterministic per (seed, frame)"
    assert not np.array_equal(a, np.asarray(G.grain(flat, frame=5, amount=0.04, seed=7)))
    assert not np.array_equal(a, np.asarray(G.grain(flat, frame=4, amount=0.04, seed=8)))
    assert 0.5 < np.asarray(a, np.float32)[..., 0].std() < 12


def test_grade_merge_switches_effects_off():
    m = G.merge(G.DEFAULT_LOOK, dict(grain=False, grade=dict(saturation=0.5)))
    assert not G.enabled(m["grain"]) and G.enabled(m["grade"]) and m["grade"]["saturation"] == 0.5
    assert m["grade"]["gain"] == G.DEFAULT_LOOK["grade"]["gain"]


def test_dof_backdrop_never_alters_the_panel():
    ui = textured()
    box = G.panel_box((640, 360), 0.8, 0.45)
    pw, ph = box[2] - box[0], box[3] - box[1]
    want = np.asarray(ui.resize((pw, ph), Image.LANCZOS))
    heavy = lambda bd: G.apply_look(bd, G.merge(G.DEFAULT_LOOK, dict(grain=dict(amount=0.3))), frame=3)      # noqa: E731
    for kw in (dict(shadow=0.0), dict(shadow=0.9, shadow_blur=0.05), dict(shadow=0.9, fx=heavy)):
        out = G.dof_backdrop(ui, box, (640, 360), **kw)
        assert out.size == (640, 360)
        got = np.asarray(out)[box[1]:box[3], box[0]:box[2]]
        assert np.array_equal(got, want), f"panel pixels changed with {sorted(kw)}"
    a = np.asarray(G.dof_backdrop(ui, box, (640, 360), shadow=0.0)).astype(int)
    b = np.asarray(G.dof_backdrop(ui, box, (640, 360), shadow=0.9)).astype(int)
    diff = np.abs(a - b).sum(2)
    inside = diff[box[1]:box[3], box[0]:box[2]]
    assert inside.max() == 0 and diff.max() > 0, "the edge shadow exists, and only outside the panel"
    bd = np.asarray(G.make_backdrop(ui, (640, 360)), np.float32)
    assert bd.mean() < 0.5 * np.asarray(ui.resize((640, 360)), np.float32).mean() and bd.std() < np.asarray(ui.resize((640, 360)), np.float32).std(), "blurred + darkened"


def test_panel_box_is_even_centred_and_in_frame():
    for w, cy in ((0.8, 0.455), (0.62, 0.5), (0.95, 0.9)):
        x0, y0, x1, y1 = G.panel_box((1920, 1080), w, cy)
        assert (x1 - x0) % 2 == 0 and (y1 - y0) % 2 == 0 and x0 >= 0 and y0 >= 0 and x1 <= 1920 and y1 <= 1080
        assert abs((x1 - x0) / (y1 - y0) - 16 / 9) < 0.02 and x0 == 1920 - x1


# ---------------------------------------------------------------- panel depth: rounded corners, shadow, rim, glow, plate, parallax
NO_FX = dict(radius=22, shadow=False, rim=False, glow=False)             # rounded corners only
OFF = dict(radius=0, shadow=False, rim=False, glow=False)


def pnl(**kw):
    return G.merge(G.DEFAULT_LOOK["panel"], kw)


def panel_render(panel, size=(640, 360), cy=0.45, opacity=1.0, bd=None):
    ui = textured()
    box = G.panel_box(size, 0.8, cy)
    bd = bd or G.make_backdrop(ui, size)
    return ui, box, G.dof_backdrop(ui, box, size, panel=panel, backdrop=bd, opacity=opacity)


def test_panel_defaults_are_on_for_cinematic_story():
    d = G.DEFAULT_LOOK["panel"]
    assert d["radius"] == 22 and G.enabled(d["shadow"]) and len(d["shadow"]["layers"]) == 2 and G.enabled(d["rim"]) and G.enabled(d["glow"])
    assert abs(d["rim"]["alpha"] - 0.18) < 1e-9 and abs(d["glow"]["alpha"] - 0.25) < 1e-9 and d["in"] is None
    st = styles.resolve(dict(style=dict(preset="cinematic-story")))
    assert st["look"]["panel"]["radius"] == 22 and G.enabled(st["look"]["panel"]["glow"])
    off = G.merge(G.DEFAULT_LOOK, dict(panel=dict(shadow=False, rim=False, glow=False, radius=False)))["panel"]
    assert not G.enabled(off["shadow"]) and not G.enabled(off["rim"]) and not G.enabled(off["glow"]) and not off["radius"]
    assert off["w"] == 0.80 and off["cy"] == 0.455, "switching depth off keeps the geometry"
    assert G.corner_radius_px(22, 1920) == 22 and abs(G.corner_radius_px(22, 854) - 22 * 854 / 1920) < 1e-9 and G.corner_radius_px(0, 1920) == 0


def test_rounded_panel_interior_is_byte_identical_to_the_resampled_source():
    ui, box, out = panel_render(pnl())
    pw, ph = box[2] - box[0], box[3] - box[1]
    want = np.asarray(ui.resize((pw, ph), Image.LANCZOS))
    got = np.asarray(out)[box[1]:box[3], box[0]:box[2]]
    keep = interior_mask(pw, ph, 640)
    assert np.array_equal(got[keep], want[keep]), "every pixel outside the 4 corner blocks is the resampled source, with all depth effects on"
    # the corners are rounded: the very corner pixel shows the backdrop, not the UI; the arc is antialiased (in-between values)
    assert not np.array_equal(got[0, 0], want[0, 0]) and not np.array_equal(got[-1, -1], want[-1, -1])
    r = int(np.ceil(G.corner_radius_px(22, 640)))
    blk = got[:r, :r].astype(int)
    assert 0 < (np.abs(blk - want[:r, :r].astype(int)).sum(2) > 0).sum() < r * r
    # radius 0 + no effects = the plain square paste (what the legacy dof_backdrop does without a shadow)
    ui, box, sq = panel_render(pnl(**OFF))
    assert np.array_equal(np.asarray(sq)[box[1]:box[3], box[0]:box[2]], want)
    legacy = G.dof_backdrop(ui, box, (640, 360), shadow=0.0, backdrop=G.make_backdrop(ui, (640, 360)))
    assert np.array_equal(np.asarray(sq), np.asarray(legacy))


def test_panel_shadow_rim_and_glow_only_exist_outside_the_panel():
    keep = None
    base = None
    for name in ("shadow", "rim", "glow"):
        on = pnl(**{**NO_FX, name: G.DEFAULT_LOOK["panel"][name]})
        ui, box, a = panel_render(on)
        _, _, b = panel_render(pnl(**NO_FX))
        a, b = np.asarray(a).astype(int), np.asarray(b).astype(int)
        d = np.abs(a - b).sum(2)
        inside = d[box[1]:box[3], box[0]:box[2]]
        keep = interior_mask(box[2] - box[0], box[3] - box[1], 640)
        assert inside[keep].max() == 0, f"{name} must not touch a panel pixel"
        out = d.copy()
        out[box[1]:box[3], box[0]:box[2]] = 0
        assert out.max() > 0, f"{name} must exist around the panel"
    # all three at once: still nothing inside
    _, box, a = panel_render(pnl())
    _, _, b = panel_render(pnl(**NO_FX))
    d = np.abs(np.asarray(a).astype(int) - np.asarray(b).astype(int)).sum(2)[box[1]:box[3], box[0]:box[2]]
    assert d[keep].max() == 0


def test_panel_shadow_darkens_below_more_than_above_and_rim_is_a_1px_line_outside():
    bd = G.make_backdrop(textured(), (640, 360))
    bd = Image.fromarray(np.full((360, 640, 3), 90, np.uint8), "RGB")
    sh = pnl(**{**NO_FX, "shadow": G.DEFAULT_LOOK["panel"]["shadow"]})
    ui, box, a = panel_render(sh, bd=bd)
    a = np.asarray(a).astype(int)[..., 0]
    cx = (box[0] + box[2]) // 2
    below, above = a[box[3] + 3, cx], a[box[1] - 3, cx] if box[1] > 3 else 90
    assert below < 90 and below < above, "drop shadow falls below the panel"
    far = a[min(359, box[3] + 40), cx]
    assert far > below, "and fades with distance"
    rim = pnl(**{**NO_FX, "rim": G.DEFAULT_LOOK["panel"]["rim"]})
    ui, box, r = panel_render(rim, bd=bd)
    r = np.asarray(r).astype(int)[..., 0]
    cy = (box[1] + box[3]) // 2
    assert r[cy, box[0] - 1] > 90 + 8 and r[cy, box[0] - 2] == 90 and r[cy, box[2]] > 98 and r[cy, box[2] + 1] == 90, "1 px line just outside the border"
    assert r[box[1] - 1, cx] > 98 and r[box[1] - 2, cx] == 90 and r[box[3], cx] > 98


def test_panel_glow_is_a_warm_lift_of_the_panel_colour_behind_it():
    bd = Image.fromarray(np.full((360, 640, 3), 20, np.uint8), "RGB")
    glow = pnl(**{**NO_FX, "glow": G.DEFAULT_LOOK["panel"]["glow"]})
    ui, box, a = panel_render(glow, bd=bd)
    _, _, b = panel_render(pnl(**NO_FX), bd=bd)
    d = np.asarray(a).astype(int) - np.asarray(b).astype(int)
    d[box[1]:box[3], box[0]:box[2]] = 0
    assert d.min() >= 0 and d.max() > 3, "light spill only adds light outside the panel"
    ring = d[box[3]:box[3] + 12, box[0]:box[2]].reshape(-1, 3).mean(0)
    assert ring[0] > ring[2] > 0, "and it is warm (red above blue)"
    assert d[box[3] + 12:, box[0]:box[2]].mean() < d[box[3]:box[3] + 12, box[0]:box[2]].mean(), "strongest next to the panel"


def test_panel_entrance_ease_and_fade():
    cfg = G.entrance_cfg(dict(**{"in": dict(dur=0.4, from_scale=0.9, fade=True)}))
    assert G.entrance_at(None, 0.0) == (1.0, 1.0)
    s0, o0 = G.entrance_at(cfg, 0.0, R.ease)
    sm, om = G.entrance_at(cfg, 0.2, R.ease)
    s1, o1 = G.entrance_at(cfg, 0.4, R.ease)
    assert (s0, o0) == (0.9, 0.0) and abs(sm - 0.95) < 1e-9 and 0.4 < om < 0.6 and (s1, o1) == (1.0, 1.0)
    assert G.entrance_at(G.entrance_cfg(dict(**{"in": dict(fade=False)})), 0.0, R.ease)[1] == 1.0
    assert G.entrance_cfg(dict(**{"in": True}))["dur"] == 0.35 and G.entrance_cfg(dict(**{"in": None})) is None
    # composer: the panel fades in over the backdrop, then is exactly the settled frame
    ent = dict(panel=dict(**{"in": dict(dur=0.5, from_scale=0.95, fade=True)}))
    ctx, shot, comp, first = compose_all(look=ent, t=0.0)
    box = G.panel_box((ctx.OW, ctx.OH), 0.80, 0.455)
    crop = np.asarray(R.frame_cam(ctx, textured(640, 360), 0.5, 0.5, 0.8, out=(box[2] - box[0], box[3] - box[1])))
    mid = np.asarray(first)[box[1] + 40:box[3] - 40, box[0] + 40:box[2] - 40]
    assert (mid != crop[40:-40, 40:-40]).any(2).mean() > 0.9, "at t=0 the panel is not yet there (faded out, scaled down)"
    ctx, shot, comp, done = compose_all(look=ent, t=0.5)
    keep = interior_mask(box[2] - box[0], box[3] - box[1], ctx.OW)
    assert np.array_equal(np.asarray(done)[box[1]:box[3], box[0]:box[2]][keep], crop[keep]), "after the ease the UI pixels are untouched"
    ctx, shot, comp, _ = compose_all(look=ent, t=0.1)
    assert comp._box(0.0)[0][2] - comp._box(0.0)[0][0] < comp._box(0.5)[0][2] - comp._box(0.5)[0][0], "scales up into place"
    # off by default: no pop-in ease at all
    ctx, shot, comp, _ = compose_all(t=0.0)
    assert comp.entr is None and comp._box(0.0)[2] == 1.0


def test_parallax_math():
    cam0, cam = (0.5, 0.5, 0.8), (0.6, 0.45, 0.4)
    pc = G.parallax_cam(cam, cam0, 0.35)
    assert abs(pc[0] - (0.5 + 0.35 * 0.1)) < 1e-9 and abs(pc[1] - (0.5 - 0.35 * 0.05)) < 1e-9
    assert abs(pc[2] - 0.8 * (0.4 / 0.8) ** 0.35) < 1e-9, "zoom is geometric: 35% of the push-in in log space"
    assert G.parallax_cam(cam, cam0, 0.0) == cam0 and all(abs(a - b) < 1e-12 for a, b in zip(G.parallax_cam(cam, cam0, 1.0), cam))
    assert G.parallax_cam(cam0, cam0, 0.35) == cam0, "a static camera never moves the backdrop"
    v = G.plate_view(cam, cam0, 0.35, base=(0.5, 0.5, 0.9))
    assert abs(v[0] - (0.5 + 0.035)) < 1e-9 and abs(v[2] - 0.9 * 0.5 ** 0.35) < 1e-9
    # the cropped view clamps inside the plate and keeps the output aspect
    plate = Image.fromarray(np.tile(np.linspace(0, 255, 400, dtype=np.uint8)[None, :, None], (225, 1, 3)), "RGB")
    a = np.asarray(G.make_backdrop(plate, (320, 180), blur=2, dim=1.0, view=(0.5, 0.5, 0.8)), np.float32)
    b = np.asarray(G.make_backdrop(plate, (320, 180), blur=2, dim=1.0, view=(0.7, 0.5, 0.8)), np.float32)
    assert b[90, 160, 0] > a[90, 160, 0] + 10, "moving the view right shows brighter (right-hand) plate content"
    c = np.asarray(G.make_backdrop(plate, (320, 180), blur=2, dim=1.0, view=(5.0, 0.5, 0.8)), np.float32)
    assert c.shape == (180, 320, 3) and c[90, 300, 0] > 240, "an out-of-range view is clamped to the plate edge"


def drift(look_bd):
    """Mean abs change of the outer backdrop between two cameras (a push-in plus a pan) for a backdrop config."""
    spec = fake_spec()
    a = compose_cam(spec, look_bd, (0.5, 0.5, 0.8))
    b = compose_cam(spec, look_bd, (0.6, 0.5, 0.5))
    m = np.ones(a.shape[:2], bool)
    m[20:-20, 60:-60] = False
    return np.abs(a.astype(int) - b.astype(int)).sum(2)[m].mean()


def compose_cam(spec, backdrop, cam, plate_img=None):
    cfg = dict(type="cinema", source="c", cam=[[0, 0.5, 0.5, 0.8], ["end", 0.5, 0.5, 0.8]], look=dict(backdrop=backdrop, grain=False, vignette=False, bloom=False))
    shot = mk_shot(cfg)
    comp = CN.Composer(tiny_ctx(spec, tempfile.mkdtemp()), shot)
    return np.asarray(comp.compose(textured(640, 360, seed=5), cam, 0.5, 4))


def test_backdrop_parallax_follows_a_fraction_of_the_camera_motion():
    d0, d35, d100 = (drift(dict(parallax=k)) for k in (0.0, 0.35, 1.0))
    assert d0 < d35 < d100, (d0, d35, d100)
    pd = tempfile.mkdtemp()
    plate = os.path.join(pd, "plate.png")
    Image.fromarray(np.tile(np.linspace(40, 255, 640, dtype=np.uint8)[None, :, None] * np.array([1, 1, 1], np.uint8), (360, 1, 1)), "RGB").save(plate)
    p0, p35, p100 = (drift(dict(plate=plate, parallax=k)) for k in (0.0, 0.35, 1.0))
    assert p0 < p35 < p100, (p0, p35, p100)


def test_plate_backdrop_replaces_the_blurred_ui_copy_and_falls_back():
    pd = tempfile.mkdtemp()
    plate = os.path.join(pd, "sky.png")
    Image.new("RGB", (640, 360), (30, 200, 60)).save(plate)                  # a green plate is unmistakable
    spec = fake_spec()
    with_plate = compose_cam(spec, dict(plate=plate, dim=1.0, warm=False), (0.5, 0.5, 0.8))
    edge = with_plate[5, 5].astype(int)
    assert edge[1] > edge[0] + 40 and edge[1] > edge[2] + 40, f"backdrop shows the plate, got {edge}"
    plain = compose_cam(spec, "dof", (0.5, 0.5, 0.8))
    assert not (plain[5, 5, 1] > plain[5, 5, 0] + 40)
    # a missing plate falls back to the dof copy instead of failing
    missing = compose_cam(spec, dict(plate=os.path.join(pd, "nope.png")), (0.5, 0.5, 0.8))
    assert missing.shape == plain.shape and np.abs(missing.astype(int) - plain.astype(int)).mean() < 2
    # panel interior is still the camera crop
    box = G.panel_box((854, 480), 0.80, 0.455)
    crop = np.asarray(R.frame_cam(tiny_ctx(spec, pd), textured(640, 360, seed=5), 0.5, 0.5, 0.8, out=(box[2] - box[0], box[3] - box[1])))
    keep = interior_mask(box[2] - box[0], box[3] - box[1], 854)
    assert np.array_equal(with_plate[box[1]:box[3], box[0]:box[2]][keep], crop[keep])
    # a video plate: one frame is read at t
    clip = os.path.join(pd, "plate.mp4")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x2060c0:size=160x90:rate=6:duration=1", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", clip], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    im = CN.load_plate(spec, clip, 0.2)
    assert im is not None and im.getpixel((10, 10))[2] > im.getpixel((10, 10))[0] + 40
    assert CN.load_plate(spec, os.path.join(pd, "nope.mp4")) is None


def test_default_backdrop_is_lifted_by_a_cool_to_warm_gradient_never_flat_black():
    black = np.zeros((90, 160, 3), np.float32)
    g = G.warm_lift(black, 0.35)
    top, bot = g[0, 0], g[-1, 0]
    assert top[2] > top[0] and bot[0] > bot[2], "indigo on top, amber at the bottom"
    assert bot.sum() > top.sum() and g.min() >= 0 and g.max() < 0.5
    assert np.array_equal(G.warm_lift(black, 0.0), black)
    assert abs(G.warm_lift(np.ones((4, 4, 3), np.float32), 0.35)[0, 0].mean() - (0.65 + 0.35 * np.mean(G.WARM_TOP) * 1.0)) < 0.1
    spec = fake_spec()
    dark = lambda bd: compose_cam(spec, bd, (0.5, 0.5, 0.8))     # noqa: E731
    on, off = dark("dof"), dark(dict(warm=False))
    assert on[-6, 400].astype(int)[0] > off[-6, 400].astype(int)[0] + 4, "the warm lift shows in the margin under the panel"
    assert on[3, 400].astype(int).sum() > 0 or on[-6, 400].astype(int).sum() > 20
    bc = CN.backdrop_cfg(dict(backdrop="dof"))
    assert bc["mode"] == "dof" and bc["warm"] == 0.35 and bc["parallax"] == 0.35 and bc["plate"] is None
    assert CN.backdrop_cfg(dict(backdrop=dict(plate="bg-night")))["warm"] == 0.12
    assert CN.backdrop_cfg(dict(backdrop="none"))["mode"] == "none" and not CN.has_panel(dict(backdrop="none"))
    assert CN.has_panel(dict(backdrop=dict(plate="x")))


def test_look_panel_shorthand_carries_depth_keys_and_explicit_w_cy_still_works():
    spec = fake_spec()
    sh = mk_shot(dict(type="cinema", source="c", panel=dict(w=0.9, cy=0.5, radius=0, shadow=False)))
    p = CN.look_of(spec, sh)["panel"]
    assert p["w"] == 0.9 and p["cy"] == 0.5 and p["radius"] == 0 and not G.enabled(p["shadow"]) and G.enabled(p["rim"])
    sq = mk_shot(dict(type="cinema", source="c", look=dict(panel=dict(radius=False, shadow=False, rim=False, glow=False))))
    ctx, shot, comp, out = compose_all(look=dict(panel=dict(radius=False, shadow=False, rim=False, glow=False)))
    box = G.panel_box((ctx.OW, ctx.OH), 0.80, 0.455)
    crop = R.frame_cam(ctx, textured(640, 360), 0.5, 0.5, 0.8, out=(box[2] - box[0], box[3] - box[1]))
    assert np.array_equal(np.asarray(out)[box[1]:box[3], box[0]:box[2]], np.asarray(crop)), "radius 0 = every pixel of the panel, corners too"


def test_footage_walker_counts_a_plate_clip_id_but_not_a_path():
    from promo import footage as FT
    f = {}
    FT._walk(dict(look=dict(backdrop=dict(plate="bg-night"))), None, f, "01")
    FT._walk(dict(look=dict(backdrop=dict(plate="/tmp/a/sky.png"))), None, f, "02")
    FT._walk(dict(look=dict(backdrop=dict(plate="plates/sky.mp4"))), None, f, "03")
    assert f == {"bg-night": ["01"]}


def test_panel_cutoff_uses_the_cinema_panel_viewport_over_time():
    from promo import generic_check as GC
    spec = load_spec(cinema_project(good_shots()))
    s = spec.shots[1]
    vp = GC.viewport(spec, s)
    assert vp == [float(v) for v in G.panel_box((1920, 1080), 0.80, 0.455)]
    pb = copy.deepcopy(good_shots())
    pb[1]["pullback"] = dict(w=0.5, start=0.0)
    spec = load_spec(cinema_project(pb))
    s = spec.shots[1]
    late = GC.viewport(spec, s, s.t0 + s.dur)
    assert late[2] - late[0] < GC.viewport(spec, s, s.t0)[2] - GC.viewport(spec, s, s.t0)[0] - 100, "a pullback panel shrinks, and the gate follows it"


def test_style_gate_warns_about_an_unreadable_plate():
    sh = good_shots()
    sh[1]["look"] = dict(backdrop=dict(plate="no-such-plate.png"))
    st, msg = gate(cinema_project(sh), "ui-protect")
    assert st == "WARN" and "no-such-plate.png" in msg


# ---------------------------------------------------------------- cinema composer: protect_ui
def compose_all(look=None, extra=None, t=0.5, n=12):
    spec = fake_spec()
    cfg = dict(type="cinema", source="c", cam=[[0, 0.5, 0.5, 0.8], ["end", 0.5, 0.5, 0.8]], **(extra or {}))
    if look:
        cfg["look"] = look
    shot = mk_shot(cfg, n)
    ctx = tiny_ctx(spec, tempfile.mkdtemp())
    comp = CN.Composer(ctx, shot)
    return ctx, shot, comp, comp.compose(textured(640, 360), (0.5, 0.5, 0.8), t, 4)


def test_cinema_ui_panel_pixels_equal_the_camera_crop():
    everything = dict(grade=dict(saturation=0.5), bloom=dict(strength=1.0), grain=dict(amount=0.2), vignette=dict(strength=0.9))
    ctx, shot, comp, out = compose_all(look=everything, extra=dict(lower_copy=[dict(text="Tell it at night.", at=0, dur=3)]))
    box = G.panel_box((ctx.OW, ctx.OH), 0.80, 0.455)
    pw, ph = box[2] - box[0], box[3] - box[1]
    crop = R.frame_cam(ctx, textured(640, 360), 0.5, 0.5, 0.8, out=(pw, ph))
    got = np.asarray(out)[box[1]:box[3], box[0]:box[2]]
    keep = interior_mask(pw, ph, ctx.OW)
    assert np.array_equal(got[keep], np.asarray(crop)[keep]), "UI pixels inside the panel must equal the camera crop exactly (corner blocks aside)"
    outside = np.asarray(out).astype(int)
    outside[box[1]:box[3], box[0]:box[2]] = 0
    assert outside.sum() > 0, "backdrop is drawn around the panel"
    # the lower copy sits in the margin under the panel and never inside it
    cb = CN.copy_box(shot_spec(comp), shot, CN.copy_items(shot)[0], (ctx.OW, ctx.OH))
    assert cb[1] >= box[3] and cb[3] <= ctx.OH


def shot_spec(comp):
    return comp.spec


def interior_mask(pw, ph, out_w, radius=22):
    """Boolean (ph, pw) mask: True everywhere except the 4 corner blocks where the rounded corners blend with the backdrop."""
    m = np.ones((ph, pw), bool)
    for sl in G.corner_blocks(pw, ph, G.corner_radius_px(radius, out_w)):
        m[sl] = False
    return m


def test_cinema_global_vignette_is_the_only_thing_that_may_touch_the_panel():
    ctx, shot, comp, out = compose_all(look=dict(vignette=dict(strength=0.5, **{"global": 0.1})))
    box = G.panel_box((ctx.OW, ctx.OH), 0.80, 0.455)
    crop = np.asarray(R.frame_cam(ctx, textured(640, 360), 0.5, 0.5, 0.8, out=(box[2] - box[0], box[3] - box[1]))).astype(int)
    got = np.asarray(out)[box[1]:box[3], box[0]:box[2]].astype(int)
    d = (crop - got)[interior_mask(box[2] - box[0], box[3] - box[1], ctx.OW)]
    assert d.min() >= 0 and d.max() > 0, "global vignette only darkens"
    full = (crop - got)
    cy, cx = full.shape[0] // 2, full.shape[1] // 2
    assert full[cy - 20:cy + 20, cx - 20:cx + 20].max() <= 1, "and leaves the middle of the panel alone"


def test_cinema_full_bleed_ui_shot_is_not_graded_at_all():
    ctx, shot, comp, out = compose_all(look=dict(backdrop="none"))
    crop = R.frame_cam(ctx, textured(640, 360), 0.5, 0.5, 0.8)
    assert np.array_equal(np.asarray(out), np.asarray(crop))
    ctx, shot, comp, out = compose_all(look=dict(backdrop="none"), extra=dict(ui=False))        # scenery: graded
    assert not np.array_equal(np.asarray(out), np.asarray(R.frame_cam(ctx, textured(640, 360), 0.5, 0.5, 0.8)))
    ctx, shot, comp, out = compose_all(look=dict(protect_ui=False, backdrop="none"))             # explicit opt-out (the gate FAILs it)
    assert not np.array_equal(np.asarray(out), np.asarray(R.frame_cam(ctx, textured(640, 360), 0.5, 0.5, 0.8)))


def test_cinema_fades_and_title_and_pullback():
    ctx, shot, comp, out = compose_all(extra=dict(fade_in=0.5), t=0.0)
    assert np.asarray(out).max() == 0, "fade_in starts from black"
    ctx, shot, comp, out = compose_all(extra=dict(fade_in=0.5), t=0.5)
    assert np.asarray(out).max() > 100
    spec = fake_spec()
    shot = mk_shot(dict(type="cinema", ui=False, title_bloom=dict(text="Acme Tasks", at=0.2, dur=0.8, fade=0.3, fade_out=0.1)))
    comp = CN.Composer(tiny_ctx(spec, tempfile.mkdtemp()), shot)
    dark = np.asarray(comp.compose(None, None, 0.0, 0)).astype(int)
    lit = np.asarray(comp.compose(None, None, 0.5, 6)).astype(int)
    assert dark.mean() < 20 and dark.max() < 60 and lit.max() > 200, "the title glows in out of the dark"
    ys, xs = np.nonzero(lit.sum(2) > 300)
    assert 150 < ys.mean() < 330 and 300 < xs.mean() < 560, "title is centred"
    pb = mk_shot(dict(type="cinema", source="c", cam=[[0, 0.5, 0.5, 0.7], ["end", 0.5, 0.5, 1.0]], pullback=dict(w=0.6, start=0.0)))
    s2 = fake_spec()
    a = CN.panel_params(CN.look_of(s2, pb), pb, 0.0, pb.dur)
    z = CN.panel_params(CN.look_of(s2, pb), pb, pb.dur, pb.dur)
    assert a[0] == 0.80 and abs(z[0] - 0.6) < 1e-9 and z[2] > a[2], "pullback shrinks the panel and lifts the backdrop"
    assert CN.panel_box_of(s2, pb)[2] - CN.panel_box_of(s2, pb)[0] == G.panel_box((1920, 1080), 0.8, 0.455)[2] - G.panel_box((1920, 1080), 0.8, 0.455)[0]


def test_cinema_tiny_render_480p():
    d = tempfile.mkdtemp()
    clip = os.path.join(d, "src.mp4")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=12:duration=2", "-c:v", "libx264",
                        "-preset", "ultrafast", "-pix_fmt", "yuv420p", clip], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    spec = fake_spec(clip)
    ctx = tiny_ctx(spec, os.path.join(d, "segs"))
    shot = mk_shot(dict(type="cinema", source="c", t_in=0.0, cam=[[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 0.9]], fade_in=0.25,
                        lower_copy=[dict(text="Tell it at night.", at=0.2, dur=0.7)], notes="synthetic test pattern"))
    e = CN.Cinema().render(ctx, shot)
    assert e["move"].startswith("slow eased camera") and "DoF panel" in e["notes"] and "backdrop only" in e["notes"]
    p = os.path.join(d, "segs", "01.mp4")
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_entries",
                                   "stream=width,height,nb_read_frames", "-of", "csv=p=0", p]).decode().strip()
    assert out == "854,480,12", out
    # dark-plate title shot (no source)
    t = mk_shot(dict(type="cinema", ui=False, title_bloom=dict(text="Acme Tasks", at=0.1, dur=0.8, fade=0.3), fade_out=0.25), sid="02")
    CN.Cinema().render(ctx, t)
    assert os.path.exists(os.path.join(d, "segs", "02.mp4"))
    assert CN.Cinema().src_to_out(shot, 0.5) == 0.5 and [c["text"] for c in CN.Cinema().captions(ctx, shot)] == ["Tell it at night."]


# ---------------------------------------------------------------- preset, gates, scaffold
def cinema_project(shots, style=None, qa=None, claims=None):
    d = tempfile.mkdtemp()
    open(os.path.join(d, "assets.yaml"), "w").write(yaml.safe_dump(dict(assets=[dict(
        id="music", kind="music", path="m.wav", licence="Pixabay Content License", source_url="https://example.org/t")])))
    os.makedirs(os.path.join(d, "footage"))
    open(os.path.join(d, "footage", "manifest.yaml"), "w").write("clips: []\n")
    beats = shots[-1]["beats"][1]
    raw = dict(project=dict(name="t"), output=dict(name="t", resolution=1080, fps=30, duration=beats * 0.5),
               style=dict(preset="cinematic-story", **(style or {})), timeline=dict(bpm=120, beats=beats),
               music=dict(asset="music", track_beat=0.5, track_offset=0, edit=dict(segments=[[0, 0, beats]])), shots=shots, qa=qa or {})
    if claims:
        raw["claims"] = claims
    p = os.path.join(d, "promo.yaml")
    open(p, "w").write(yaml.safe_dump(raw, sort_keys=False))
    return p


def cs(sid, beats, **kw):
    return dict(id=sid, beats=beats, type="cinema", source="c", **kw)


# 60 s at 120 BPM: calm (3 cuts in the first 20 s) -> busier (10 in the middle 20 s: 5-beat UI shots and 3-beat scenery cutaways) -> calm (3)
EDGES = [0, 10, 20, 30, 40, 45, 48, 53, 56, 61, 64, 69, 72, 77, 80, 92, 104, 120]


def good_shots(edges=EDGES):
    out = []
    for k, (a, b) in enumerate(zip(edges, edges[1:])):
        sh = cs(f"{k + 1:02d}", [a, b], cam=[[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 0.95]])
        if b - a == 3:
            sh["ui"] = False                                # a 1.5 s cutaway is scenery, not UI
        out.append(sh)
    out[0].update(fade_in=1.0)
    out[-1].update(fade_out=1.5)
    return out


def gate(p, name):
    r = {g: (st, msg) for g, st, msg in style_check.run(load_spec(p))}
    return r[name]


def test_style_cinematic_story_preset_is_registered_with_rules():
    assert "cinematic-story" in styles.names()
    p = styles.PRESETS["cinematic-story"]
    for k in ("description", "pacing", "typography", "transitions", "checks", "qa", "look"):
        assert k in p, k
    assert p["pacing"]["min_shot_s"] == 0.8 and p["pacing"]["ui_min_hold_s"] == 2.5 and p["pacing"]["cut_rate"]["thirds"] == [0.3, 0.6, 0.3]
    assert p["transitions"]["allowed"] == ["cut", "fade"] and "flash" not in p["transitions"]["allowed"]
    assert p["look"]["protect_ui"] is True and p["look"]["backdrop"] == "dof"
    assert {"ui-protect", "ui-hold", "no-fx", "copy-clear", "cut-curve"} <= set(p["checks"])
    st = styles.resolve(dict(style=dict(preset="cinematic-story", look=dict(grain=False, panel=dict(w=0.7)))))
    assert st["look"]["grain"] is False and st["look"]["panel"]["w"] == 0.7 and st["look"]["panel"]["cy"] == 0.455 and st["look"]["panel"]["radius"] == 22 and st["look"]["grade"]["on"]
    from promo import cli
    r = cli.cmd_styles()
    assert "cinematic-story" in r["presets"]


def test_style_cinematic_story_good_project_passes_every_gate():
    p = cinema_project(good_shots())
    spec = load_spec(p)
    assert spec.total_frames() == 1800 and not spec.validate()
    res = style_check.run(spec)
    names = {g for g, _, _ in res}
    assert {"shot-hold", "ui-hold", "no-fx", "cinema-keys", "ui-protect", "copy-hold", "copy-clear", "claims", "cut-curve",
            "slow-camera", "fades", "serif-font"} <= names
    bad = [(g, s, m) for g, s, m in res if s != "PASS"]
    assert not bad, bad


def test_style_cinematic_story_hard_gates_fail():
    sh = good_shots([0, 10, 13, 20, 30, 31, 40, 120])                                  # a 1.5 s UI shot and a 0.5 s shot
    sh[1]["ui"] = True
    p = cinema_project(sh)
    assert gate(p, "shot-hold")[0] == "FAIL" and "0.50s" in gate(p, "shot-hold")[1]
    assert gate(p, "ui-hold")[0] == "FAIL" and "1.50s" in gate(p, "ui-hold")[1]
    # UI-protection
    sh = good_shots()
    sh[2]["look"] = dict(protect_ui=False)
    sh[3]["look"] = dict(vignette=dict(**{"global": 0.4}))
    st, msg = gate(cinema_project(sh), "ui-protect")
    assert st == "FAIL" and "protect_ui" in msg and "global vignette 0.4" in msg
    sh = good_shots()
    sh[2]["look"] = dict(vignette=dict(**{"global": 0.1}))
    assert gate(cinema_project(sh), "ui-protect")[0] == "WARN"
    sh = good_shots()
    sh[2]["look"] = dict(backdrop="none", grain=dict(amount=0.1))
    st, msg = gate(cinema_project(sh), "ui-protect")
    assert st == "WARN" and "ignored" in msg
    # flashes / pills / forbidden keys
    sh = good_shots()
    sh[1]["fx_in"] = dict(kind="flash")
    sh[2]["overlays"] = [dict(type="caption", text="x")]
    p = cinema_project(sh)
    assert gate(p, "no-fx")[0] == "FAIL" and gate(p, "cinema-keys")[0] == "FAIL"
    sh = good_shots()
    sh[1]["paint_out"] = True
    try:
        load_spec(cinema_project(sh))
    except SpecError as e:
        assert "paint_out" in str(e)
    else:
        raise AssertionError("forbidden key accepted")
    sh = good_shots()
    sh[1]["type"] = "clip"
    assert gate(cinema_project(sh), "cinema-keys")[0] == "FAIL"


def test_style_cinematic_story_copy_gates():
    sh = good_shots()
    sh[1]["lower_copy"] = [dict(text="Tell it at night.", at=0.5, dur=1.0)]
    assert gate(cinema_project(sh), "copy-hold")[0] == "FAIL"
    sh[1]["lower_copy"] = [dict(text="Tell it at night.", at=0.5, dur=3.0)]
    assert gate(cinema_project(sh), "copy-hold")[0] == "PASS" and gate(cinema_project(sh), "copy-clear")[0] == "PASS"
    sh[1]["look"] = dict(backdrop="none")                                       # copy over a full-bleed UI shot
    st, msg = gate(cinema_project(sh), "copy-clear")
    assert st == "FAIL" and "full-bleed UI" in msg
    sh[1]["look"] = dict(panel=dict(w=0.95, cy=0.5))                           # panel eats the margin: copy overlaps it
    st, msg = gate(cinema_project(sh), "copy-clear")
    assert st == "FAIL" and "overlaps the UI panel" in msg
    sh = good_shots()
    sh[1]["title_bloom"] = dict(text="Acme Tasks", at=0.2, dur=3.0)           # title on a UI shot
    assert gate(cinema_project(sh), "copy-clear")[0] == "FAIL"
    sh = good_shots()
    sh[1]["lower_copy"] = [dict(text="8 tasks landed.", at=0.5, dur=3.0)]        # number without evidence
    st, msg = gate(cinema_project(sh), "claims")
    assert st == "FAIL" and "has a number" in msg
    sh[1]["lower_copy"][0]["evidence"] = "run 12, board screenshot"
    assert gate(cinema_project(sh), "claims")[0] != "FAIL"


def test_style_cinematic_story_soft_gates_warn():
    sh = good_shots()
    sh[0].pop("fade_in")
    sh[-1].pop("fade_out")
    st, msg = gate(cinema_project(sh), "fades")
    assert st == "WARN" and "fade_in" in msg and "fade_out" in msg
    sh = good_shots()
    sh[2]["cam"] = [[0, 0.5, 0.5, 1.0], ["end", 0.2, 0.5, 0.4]]                  # fast: 10 s shot, but moves a lot in 1 s
    sh[2]["cam"] = [[0, 0.5, 0.5, 1.0], [1.0, 0.2, 0.5, 0.4]]
    st, msg = gate(cinema_project(sh), "slow-camera")
    assert st == "WARN" and "not a slow move" in msg
    flat = [cs(f"{k + 1:02d}", [k * 10, k * 10 + 10]) for k in range(12)]       # constant 0.2 cuts/s: no build in the middle
    st, msg = gate(cinema_project(flat), "cut-curve")
    assert st == "WARN" and "part 2/3" in msg
    assert gate(cinema_project(good_shots()), "cut-curve")[0] == "PASS"


# ---------------------------------------------------------------- engine changes from the critique council
def test_cinema_copy_and_title_size_are_multipliers_with_a_cap():
    spec = fake_spec()
    shot = mk_shot(dict(type="cinema", source="c"))
    width = lambda **kw: (lambda b: b[2] - b[0])(CN.copy_box(spec, shot, dict(text="Tell it at night.", **kw), (1920, 1080)))   # noqa: E731
    w1, w2 = width(), width(size=2.0)
    assert width(size=1.0) == w1 and 1.7 < w2 / w1 < 2.3
    assert width(size=3.0) == w2, "multiplier is capped at 2.0"
    assert width(size=76) == w2, "a value above 4 is the legacy absolute canvas px (38 * 2)"
    assert CN.size_px({}, 38.0) == 38.0 and CN.size_px(dict(size=1.5), 132.0) == 198.0 and CN.size_px(dict(size=9), 132.0) == 9
    ctx = tiny_ctx(spec, tempfile.mkdtemp())
    t1 = CN.Composer(ctx, mk_shot(dict(type="cinema", ui=False, title_bloom=dict(text="Acme Tasks Cloud"))))
    t2 = CN.Composer(ctx, mk_shot(dict(type="cinema", ui=False, title_bloom=dict(text="Acme Tasks Cloud", size=1.5, cy=0.3))))
    assert 1.3 < t2.title[1].w / t1.title[1].w < 1.6
    assert abs(t2.title[2][1] + CN._text_size(CN.serif_font(spec, 132 * 1.5 * ctx.OW / 1920), "Acme Tasks Cloud")[1] / 2 - 0.3 * ctx.OH) < 1
    # the gate warns about a capped multiplier
    sh = good_shots()
    sh[1]["lower_copy"] = [dict(text="Tell it at night.", at=0.5, dur=3.0, size=3.0)]
    st, msg = gate(cinema_project(sh), "copy-size")
    assert st == "WARN" and "clamped" in msg


def test_cinema_lower_copy_scrim_darkens_the_backdrop_never_the_ui_panel():
    base = dict(lower_copy=[dict(text="Tell it at night.", at=0, dur=3)])
    scrim = dict(lower_copy=[dict(text="Tell it at night.", at=0, dur=3, scrim=dict(alpha=0.6, height=300))])
    ctx, shot, comp0, out0 = compose_all(extra=base)
    _, _, comp1, out1 = compose_all(extra=scrim)
    a, b = np.asarray(out0).astype(int), np.asarray(out1).astype(int)
    box = G.panel_box((ctx.OW, ctx.OH), 0.80, 0.455)
    assert np.array_equal(a[box[1]:box[3], box[0]:box[2]], b[box[1]:box[3], box[0]:box[2]]), "UI panel pixels are never touched by the scrim"
    strip = (slice(box[3] + 2, ctx.OH), slice(int(0.8 * ctx.OW), ctx.OW))                  # margin under the panel, right of the copy
    assert b[strip].mean() < a[strip].mean() - 3, "the margin band is darker with a scrim"
    far = (slice(0, box[1] - 2), slice(0, ctx.OW))                                         # above the panel: outside the 300 px band
    assert np.array_equal(a[far], b[far])
    # full-bleed UI shot: no scrim at all (nothing darkens real UI pixels)
    fb = dict(look=dict(backdrop="none"))
    _, _, _, f0 = compose_all(extra={**base, **fb})
    _, _, _, f1 = compose_all(extra={**scrim, **fb})
    assert np.array_equal(np.asarray(f0), np.asarray(f1))
    # scrim: true takes the defaults; off by default
    assert CN.scrim_cfg(dict(scrim=True)) == CN.SCRIM_DEFAULT and CN.scrim_cfg(dict()) is None
    assert CN.scrim_profile(100, 50, 40, 0.5).max() <= 0.5 and CN.scrim_profile(100, 50, 40, 0.5)[20] == 0 and CN.scrim_profile(100, 50, 40, 0.5)[50] > 0.45


def test_cinema_per_shot_panel_override_is_clamped_and_gated():
    spec = fake_spec()
    big = mk_shot(dict(type="cinema", source="c", panel=dict(w=0.9, cy=0.5)))
    assert {k: CN.look_of(spec, big)["panel"][k] for k in ("w", "cy")} == dict(w=0.9, cy=0.5)
    assert CN.panel_box_of(spec, big) == G.panel_box((1920, 1080), 0.9, 0.5)
    assert CN.panel_box_of(spec, mk_shot(dict(type="cinema", source="c"))) == G.panel_box((1920, 1080), 0.8, 0.455)
    wide = mk_shot(dict(type="cinema", source="c", panel=dict(w=1.2)))
    assert CN.panel_box_of(spec, wide) == G.panel_box((1920, 1080), CN.MAX_PANEL_W, 0.455), "panel.w is capped at 0.94"
    sh = good_shots()
    sh[1]["panel"] = dict(w=0.92, cy=0.5)
    assert gate(cinema_project(sh), "ui-protect")[0] == "PASS"
    sh[1]["panel"] = dict(w=0.97)
    st, msg = gate(cinema_project(sh), "ui-protect")
    assert st == "WARN" and "0.94" in msg
    # the renderer uses it: a 0.92 panel is bigger than the preset's
    ctx, shot, comp, out = compose_all(extra=dict(panel=dict(w=0.92, cy=0.5)))
    box = G.panel_box((ctx.OW, ctx.OH), 0.92, 0.5)
    crop = R.frame_cam(ctx, textured(640, 360), 0.5, 0.5, 0.8, out=(box[2] - box[0], box[3] - box[1]))
    keep = interior_mask(box[2] - box[0], box[3] - box[1], ctx.OW)
    assert np.array_equal(np.asarray(out)[box[1]:box[3], box[0]:box[2]][keep], np.asarray(crop)[keep])


def test_cinema_full_bleed_ui_is_never_graded_only_faded():
    everything = dict(backdrop="none", grade=dict(saturation=0.0), bloom=dict(strength=1.0), grain=dict(amount=0.3), vignette=dict(strength=1.0))
    ctx, shot, comp, out = compose_all(look=everything, t=0.5)
    assert comp.ui and not comp.panel and comp.protect
    want = R.frame_cam(ctx, textured(640, 360), 0.5, 0.5, 0.8).convert("RGB")
    assert np.array_equal(np.asarray(out), np.asarray(want)), "full-bleed real footage: no grade / grain / bloom / vignette on UI pixels"
    ctx, shot, comp, faded = compose_all(look=everything, extra=dict(fade_in=1.0), t=0.25)
    k = 1.0 - CN.black_level(0.25, shot.dur, 1.0, 0.0)
    assert 0.0 < k < 1.0 and abs(np.asarray(faded).astype(float).mean() / np.asarray(want).astype(float).mean() - k) < 0.02, "only the fade touches it"


def test_cinema_ui_hold_threshold_can_be_lowered_and_short_moving_ui_shots_warn():
    sh = good_shots([0, 10, 13, 20, 30, 31, 40, 120])
    sh[1]["ui"] = True                                                             # a 1.5 s UI shot
    sh[4]["ui"] = False                                                            # (the 0.5 s shot is scenery)
    p = cinema_project(sh)
    assert gate(p, "ui-hold")[0] == "FAIL" and "ui_min_hold_s" in gate(p, "ui-hold")[1]
    lowered = cinema_project(sh, style=dict(pacing=dict(ui_min_hold_s=1.5)))
    st, msg = gate(lowered, "ui-hold")
    assert st == "PASS" and ">= 1.5s" in msg
    # ... still a FAIL below the lowered limit
    st, msg = gate(cinema_project(sh, style=dict(pacing=dict(ui_min_hold_s=1.8))), "ui-hold")
    assert st == "FAIL" and "< 1.8s" in msg
    # the default push-in (1.0 -> 0.95 over 1.5 s) is slow: no warning; a fast move on the short UI shot warns
    assert gate(lowered, "ui-hold-short")[0] == "PASS"
    sh[1]["cam"] = [[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 0.6]]
    st, msg = gate(cinema_project(sh, style=dict(pacing=dict(ui_min_hold_s=1.5))), "ui-hold-short")
    assert st == "WARN" and "shot 02" in msg and "1.50s" in msg
    sh[1]["cam"] = [[0, 0.5, 0.5, 0.9], ["end", 0.5, 0.5, 0.9]]                    # a still camera is fine on a short UI shot
    assert gate(cinema_project(sh, style=dict(pacing=dict(ui_min_hold_s=1.5))), "ui-hold-short")[0] == "PASS"
    assert "ui-hold-short" in styles.PRESETS["cinematic-story"]["checks"]


def test_style_cinematic_story_scaffold_loads():
    d = tempfile.mkdtemp()
    dest = os.path.join(d, "p")
    r = subprocess.run([sys.executable, "-m", "promo", "new", "x", "--dir", dest, "--style", "cinematic-story"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    spec = load_spec(os.path.join(dest, "promo.yaml"))
    assert spec.style["preset"] == "cinematic-story" and all(s.type == "cinema" for s in spec.shots)
    assert spec.total_frames() == round(spec.duration * spec.fps) and not spec.validate()
    res = {g: st for g, st, _ in style_check.run(spec)}
    assert "FAIL" not in res.values(), res                                       # the scaffold's own style gates pass (cut-curve WARNs)
    r = subprocess.run([sys.executable, "-m", "promo", "styles"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0 and "cinematic-story" in r.stdout


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
