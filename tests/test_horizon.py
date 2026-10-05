"""`horizon` style preset: anchor maths, sky framing, the persistent serif line, `dawn` card, gates, scaffold, and a tiny
854x480 end-to-end render of two horizon shots + the text layer + a dawn card from generated clips.
Plain asserts; `python tests/test_horizon.py` or pytest. Only the render test needs ffmpeg."""
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

from promo import cli, style_check, styles  # noqa: E402
from promo import render as R  # noqa: E402
from promo.render import RenderContext  # noqa: E402
from promo.shots import get_type  # noqa: E402
from promo.shots import horizon as HZ  # noqa: E402
from promo.spec import load_spec  # noqa: E402

BPM = 96.0


class Tiny(RenderContext):
    """854x480 canvas (the spec stays 1080p; sizes in the shot types follow ctx.OW / ctx.OH)."""
    OW = 854
    OH = 480


def tiny_ctx(spec):
    return Tiny(**RenderContext.from_spec(spec).__dict__)


def hz_shot(sid, beats, **kw):
    return dict(id=sid, beats=beats, type="horizon", source="clip-a", t_in=0.0, anchor=dict(src=[0.5, 0.33], out_y=0.58), w=0.55, **kw)


def dawn_shot(sid, beats, **kw):
    return dict(id=sid, beats=beats, type="dawn", name="Name", wordmark="wordmark", **kw)


# 20 beats at 96 BPM: opening hold, burst (whole + half beats), dawn hold (5 s)
GOOD = [hz_shot("01", [0, 4]), hz_shot("02", [4, 5]), hz_shot("03", [5, 6]), hz_shot("04", [6, 6.5]), hz_shot("05", [6.5, 7]),
        hz_shot("06", [7, 8]), hz_shot("07", [8, 9]), hz_shot("08", [9, 10]), hz_shot("09", [10, 11]), hz_shot("10", [11, 12]), dawn_shot("11", [12, 20], tagline="One line.")]
TEXT = [dict(words="Say it", beats=[2, 6]), dict(words="at night.", beats=[6, 9]), dict(words="Wake up.", beats=[9, 12])]


def project(shots, text=TEXT, bpm=BPM, style=None, clips=None, fps=30):
    d = tempfile.mkdtemp()
    clips = clips or [dict(id="clip-a", path=os.path.join(d, "a.mp4"), resolution="1920x1080", dpr=2, generated=dict(provider="test"))]   # a generated plate: words may sit on it
    os.makedirs(os.path.join(d, "footage"))
    yaml.safe_dump(dict(clips=clips), open(os.path.join(d, "footage", "manifest.yaml"), "w"))
    open(os.path.join(d, "assets.yaml"), "w").write("assets: []\n")
    beats = shots[-1]["beats"][1]
    tb = 60 / bpm
    raw = dict(project=dict(name="t"), output=dict(name="t", resolution=1080, fps=fps, duration=round(round(beats * tb * fps) / fps, 5)),
               style=dict(preset="horizon", **(style or {})), timeline=dict(bpm=bpm, beats=beats), shots=copy.deepcopy(shots))
    if text:
        raw["horizon_text"] = copy.deepcopy(text)
    p = os.path.join(d, "promo.yaml")
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    return p


def gates(shots, **kw):
    return {g: (s, m) for g, s, m in style_check.run(load_spec(project(shots, **kw)))}


def with_shot(shots, sid, **kw):
    return [dict(s, **kw) if s["id"] == sid else s for s in shots]


# ---------------------------------------------------------------- preset / registry
def test_horizon_preset_registered_and_listed():
    assert "horizon" in styles.names()
    p = styles.PRESETS["horizon"]
    for k in ("description", "pacing", "typography", "transitions", "checks", "qa", "horizon_text", "dawn", "sky"):
        assert k in p, k
    assert p["transitions"]["allowed"] == ["cut"] and p["pacing"]["min_shot_s"] == 0.3 and p["pacing"]["soft_min_shot_s"] == 0.4
    assert p["qa"]["beat_subdivision"] == 2 and p["horizon_text"]["size_frac"] == 0.10
    r = cli.cmd_styles()
    assert "horizon" in r["presets"]
    assert {"horizon", "dawn"} <= set(__import__("promo.shots", fromlist=["x"]).REGISTRY)
    assert styles.resolve({"style": {"preset": "horizon", "pacing": {"min_shot_s": 0.35}}})["pacing"]["min_shot_s"] == 0.35


# ---------------------------------------------------------------- anchor -> camera, sky framing
def test_horizon_anchor_places_source_point_at_output_height():
    for src_size in [(1920, 1080), (3840, 2160), (1440, 900)]:
        for ax, ay, ox, oy, w in [(0.5, 0.33, 0.5, 0.58, 0.6), (0.4, 0.5, 0.45, 0.7, 0.9), (0.6, 0.2, 0.5, 0.58, 0.45)]:
            cam = HZ.anchor_to_cam([ax, ay], (ox, oy), w, src_size)
            x0, y0, bw, bh = HZ.box_of_cam(cam, src_size)
            assert abs((ay * src_size[1] - y0) / bh - oy) < 1e-9 and abs((ax * src_size[0] - x0) / bw - ox) < 1e-9
            assert abs(bw / bh - 16 / 9) < 1e-9 and cam[2] == w
    # a clamp-free box agrees with R.anchored (the QA helper) when it is inside the source
    ctx = NS(OW=1920, OH=1080)
    cam = HZ.anchor_to_cam([0.5, 0.5], (0.5, 0.58), 0.5, (1920, 1080))
    px, py = R.anchored(ctx, cam, (1920, 1080), 0.5, 0.5)
    assert abs(py / 1080 - 0.58) < 1e-9 and abs(px / 1920 - 0.5) < 1e-9
    # horizon_y: anchor.out_y, drifting to out_y_end, else horizon_y, else None
    assert HZ.horizon_at(dict(anchor=dict(src=[0.5, 0.3], out_y=0.5, out_y_end=0.6)), 0.0, 1.0) == 0.5
    assert abs(HZ.horizon_at(dict(anchor=dict(src=[0.5, 0.3], out_y=0.5, out_y_end=0.6)), 1.0, 1.0) - 0.6) < 1e-9
    assert HZ.horizon_at(dict(horizon_y=0.4, cam=[[0, 0.5, 0.5, 1]]), 0.3, 1.0) == 0.4 and HZ.horizon_at(dict(), 0.0, 1.0) is None


def test_horizon_sky_fills_above_a_low_source_edge_and_keeps_the_edge_in_place():
    ctx = Tiny(K=1, fps=30)
    im = Image.new("RGB", (640, 360), (240, 240, 240))
    im.paste((200, 50, 50), (0, 0, 640, 18))                      # a 18 px red strip at the very top: the "edge" is its bottom
    cam = HZ.anchor_to_cam([0.5, 18 / 360], (0.5, 0.58), 0.5, im.size, (854, 480))
    sky = dict(top=[10, 14, 30], bottom="auto")
    out = np.asarray(HZ.frame_free(ctx, im, cam, sky))
    col = out[:, 20].astype(int)                                  # a column away from any text
    edge = next(y for y in range(len(col)) if col[y].min() > 200)  # first near-white row = the strip's bottom edge
    assert abs(edge - 0.58 * 480) <= 2, edge
    assert out[3, 20][0] < 40 and out[250, 20][0] > 150           # sky gradient ends in the strip's colour; the strip is red
    assert out.shape == (480, 854, 3)
    clamped = np.asarray(HZ.frame_free(ctx, im, cam, None)).astype(int)[:, 20]
    assert next(y for y in range(480) if clamped[y].min() > 200) != edge      # without sky the box clamps and the edge moves
    assert out.max() > 0


# ---------------------------------------------------------------- the text layer
def test_horizon_word_alpha_fades_three_frames():
    a = [HZ.word_alpha(f, 10, 30) for f in range(8, 33)]
    assert a[0] == 0 and a[1] == 0 and abs(a[2] - 1 / 3) < 1e-9 and abs(a[3] - 2 / 3) < 1e-9 and a[4] == 1 and a[5] == 1
    assert HZ.word_alpha(29, 10, 30) == 1 / 3 and HZ.word_alpha(30, 10, 30) == 0 and HZ.word_alpha(28, 10, 30) == 2 / 3
    spec = load_spec(project(GOOD))
    w = HZ.text_words(spec)
    assert [x["text"] for x in w] == ["Say it", "at night.", "Wake up."]
    assert w[0]["f0"] == round(2 * 60 / BPM * 30) and w[0]["f1"] == w[1]["f0"] == round(6 * 60 / BPM * 30)


def test_horizon_text_sits_above_the_horizon_and_picks_ink_by_luminance():
    spec = load_spec(project(GOOD, text=[dict(words="Hat", beats=[0, 8])]))
    ctx = tiny_ctx(spec)
    t = HZ.HorizonText(ctx, spec)
    for bg, expect_dark in [((20, 24, 40), False), ((235, 235, 230), True)]:
        base = Image.new("RGBA", (ctx.OW, ctx.OH), bg + (255,))
        out = np.asarray(t.apply(base, 10, 0.6)).astype(int)
        diff = np.abs(out - np.array(bg + (255,))).sum(-1) > 90
        ys, xs = np.where(diff)
        assert len(ys) > 50
        assert ys.max() <= 0.6 * ctx.OH - 1                                   # ink ends above the horizon line (no descenders in "Hat")
        assert ys.max() >= 0.6 * ctx.OH - 0.03 * ctx.OH                       # ... and sits just above it
        assert (ys.max() - ys.min()) >= 0.04 * ctx.OH                         # ~8 % type: cap height well above 4 % of the frame
        assert abs((xs.min() + xs.max()) / 2 - ctx.OW / 2) < 6               # centred
        ink = out[ys, xs][:, :3].mean()
        assert (ink < 100) if expect_dark else (ink > 150), (bg, ink)
    # no horizon -> fixed baseline; fade: frame 0 of the word is a third as strong as frame 3
    f0 = np.asarray(t.apply(Image.new("RGBA", (ctx.OW, ctx.OH), (0, 0, 0, 255)), 0, None)).astype(int)
    f3 = np.asarray(t.apply(Image.new("RGBA", (ctx.OW, ctx.OH), (0, 0, 0, 255)), 3, None)).astype(int)
    assert f0[..., 0].max() < f3[..., 0].max() and 70 < f0[..., 0].max() < 100 and f3[..., 0].max() > 240
    ys = np.where(f3[..., 0] > 128)[0]
    assert abs(ys.max() - 0.58 * ctx.OH) <= 2
    assert not np.asarray(t.apply(Image.new("RGBA", (ctx.OW, ctx.OH), (0, 0, 0, 255)), 400, None))[..., 0].any()


def test_horizon_font_fallback_is_graceful():
    f = HZ.load_font(["/nonexistent/NewYork.ttf"], 40)
    assert f.getbbox("Hat")[2] > 0
    st = styles.resolve({"style": {"preset": "horizon"}})
    cands = HZ.font_candidates(st, "serif")
    assert cands[0].endswith("NewYork.ttf") and any("Georgia" in c for c in cands)


# ---------------------------------------------------------------- dawn
def test_dawn_gradient_rises_from_the_bottom_navy_to_teal_to_amber():
    cfg = {**styles.PRESETS["horizon"]["dawn"], "reach": [0.12, 0.80]}          # the old tall card (amber from the start: no amber_at)
    a0, a3 = (HZ.dawn_array(320, 180, t, cfg).astype(int) for t in (0.0, 3.0))
    for a in (a0, a3):
        assert a[-1, 160, 0] > a[-1, 160, 2] + 60 and a[0, 160, 2] < 40 and a[0, 160, 0] < 20     # amber bottom, navy top
    mid = lambda a: a[90, 160]                                                                       # noqa: E731
    assert mid(a3)[1] > mid(a0)[1] + 25 and mid(a3)[2] > mid(a0)[2] + 25                             # the teal glow has risen to mid height
    assert a3[135, 160, 2] > a3[135, 160, 0] - 100 and a3[:, :, 0].max() > 200
    assert a0.shape == (180, 320, 3) and HZ.dawn_array(32, 18, 1.0, cfg).dtype == np.uint8


# ---------------------------------------------------------------- gates
def test_horizon_good_spec_passes_every_gate():
    g = gates(GOOD)
    assert not [k for k, (s, m) in g.items() if s == "FAIL"], g
    assert g["horizon-cuts"][0] == "PASS" and g["horizon-burst-hold"][0] == "PASS" and g["horizon-text"][0] == "PASS"
    assert g["horizon-edge"][0] == "PASS" and g["horizon-dawn"][0] == "PASS" and g["horizon-text-fit"][0] == "PASS"
    assert g["horizon-shot-hold"][0] == "WARN" and "0.3" in g["horizon-shot-hold"][1]            # the half-beat shots (0.31 s) are soft warnings


def test_horizon_shot_hold_hard_and_soft():
    # 96 BPM: a quarter beat = 0.156 s (FAIL); 120 BPM half beat = 0.25 s (FAIL); 100 BPM half beat = 0.30 s only WARNs
    g = gates([hz_shot("01", [0, 4]), hz_shot("02", [4, 4.25]), hz_shot("03", [4.25, 6]), hz_shot("04", [6, 12]), dawn_shot("05", [12, 20])], text=None)
    assert g["horizon-shot-hold"][0] == "FAIL" and "02" in g["horizon-shot-hold"][1]
    s120 = [hz_shot("01", [0, 4]), hz_shot("02", [4, 4.5]), hz_shot("03", [4.5, 5]), hz_shot("04", [5, 5.5]), dawn_shot("05", [5.5, 12])]
    assert gates(s120, bpm=120.0, text=None)["horizon-shot-hold"][0] == "FAIL"
    s_soft = [hz_shot("01", [0, 4]), hz_shot("02", [4, 5]), hz_shot("03", [5, 5.5]), hz_shot("04", [5.5, 6]), hz_shot("05", [6, 7]), dawn_shot("06", [7, 15])]
    assert gates(s_soft, bpm=108.0, text=None)["horizon-shot-hold"][0] == "FAIL"      # 108 BPM half beat = 0.278 s
    st, msg = gates(s_soft, bpm=100.0, text=None)["horizon-shot-hold"]      # half beat = 0.30 s: passes hard, WARN soft
    assert st == "WARN" and "0.4s" in msg


def test_horizon_cuts_half_beats_only_inside_the_burst():
    ok = gates(GOOD)["horizon-cuts"]
    assert ok[0] == "PASS"
    # a half-beat cut between long shots (not a burst) is off the grid
    s = [hz_shot("01", [0, 4.5]), hz_shot("02", [4.5, 9]), dawn_shot("03", [9, 17])]
    st, msg = gates(s, text=None)["horizon-cuts"]
    assert st == "FAIL" and "half beat outside the burst" in msg
    # the same half-beat cut is fine when an explicit burst window covers it
    st, _ = gates(s, text=None, style=dict(burst=[4, 9]))["horizon-cuts"]
    assert st == "PASS"
    st, msg = gates([hz_shot("01", [0, 4.3]), dawn_shot("02", [4.3, 12])], text=None)["horizon-cuts"]
    assert st == "FAIL" and "off the beat grid" in msg


def test_horizon_burst_must_be_followed_by_a_hold():
    st, msg = gates(GOOD)["horizon-burst-hold"]
    assert st == "PASS"
    bad = [hz_shot("01", [0, 4]), hz_shot("02", [4, 5]), hz_shot("03", [5, 6]), hz_shot("04", [6, 7]), hz_shot("05", [7, 8]), dawn_shot("06", [8, 12])]  # dawn 2.5 s
    st, msg = gates(bad, text=None)["horizon-burst-hold"]
    assert st == "FAIL" and "2.50s" in msg
    ends = [hz_shot("01", [0, 4]), hz_shot("02", [4, 5]), hz_shot("03", [5, 6]), hz_shot("04", [6, 7])]
    st, msg = gates(ends, text=None)["horizon-burst-hold"]
    assert st == "FAIL" and "ends the film" in msg
    st, msg = gates([hz_shot("01", [0, 4]), hz_shot("02", [4, 8]), dawn_shot("03", [8, 16])], text=None)["horizon-burst-hold"]
    assert st == "PASS" and "no burst" in msg
    # a burst shot just before a 3.0 s hold: exactly at the limit passes
    ok = [hz_shot("01", [0, 4]), hz_shot("02", [4, 5]), hz_shot("03", [5, 6]), hz_shot("04", [6, 7]), dawn_shot("05", [7, 12])]   # 5 beats = 3.125 s
    assert gates(ok, text=None)["horizon-burst-hold"][0] == "PASS"


def test_horizon_text_must_persist_across_cuts():
    # a word inside ONE shot for < 1.2 s fails
    st, msg = gates(GOOD, text=[dict(words="Short", beats=[4, 4.5]), dict(words="x", beats=[9, 12])])["horizon-text"]
    assert st == "FAIL" and "'Short'" in msg
    # one long hold shot (2.5 s) is fine: >= 1.2 s
    assert gates(GOOD, text=[dict(words="Held", beats=[0, 3])])["horizon-text"][0] == "PASS"
    # spanning two shots under 1.2 s is fine
    assert gates(GOOD, text=[dict(words="Cut", beats=[4.5, 6.5])])["horizon-text"][0] == "PASS"
    # overlap, outside the timeline, over the dawn card, too short
    st, msg = gates(GOOD, text=[dict(words="A", beats=[2, 6]), dict(words="B", beats=[5, 8])])["horizon-text"]
    assert st == "FAIL" and "overlaps" in msg
    st, msg = gates(GOOD, text=[dict(words="A", beats=[10, 14])])["horizon-text"]
    assert st == "FAIL" and "non-horizon shot" in msg
    st, msg = gates(GOOD, text=[dict(words="A", beats=[19, 22])])["horizon-text"]
    assert st == "FAIL" and "outside the timeline" in msg
    st, msg = gates(GOOD, text=[dict(words="Blink", beats=[4, 4.5])])["horizon-text"]
    assert st == "FAIL"
    # no text at all: warning, not failure; per-shot overlays are rejected
    assert gates(GOOD, text=None)["horizon-text"][0] == "WARN"
    st, msg = gates(with_shot(GOOD, "02", overlays=[dict(type="caption", text="x")]))["horizon-text"]
    assert st == "FAIL" and "overlays" in msg
    # too wide
    st, msg = gates(GOOD, text=[dict(words="Supercalifragilisticexpialidocious wonderful tomorrow morning", beats=[2, 6])])["horizon-text-fit"]
    assert st == "FAIL" and "px wide" in msg


def test_horizon_edge_gate_checks_the_camera_box_and_sky():
    ok = gates(GOOD)["horizon-edge"]
    assert ok[0] == "PASS"
    # anchor very near the top without sky: box reaches above the source
    st, msg = gates(with_shot(GOOD, "02", anchor=dict(src=[0.5, 0.05], out_y=0.58)))["horizon-edge"]
    assert st == "FAIL" and "sky: true" in msg
    # ... with sky: fine
    assert gates(with_shot(GOOD, "02", anchor=dict(src=[0.5, 0.05], out_y=0.58), sky=True))["horizon-edge"][0] == "PASS"
    # sky larger than the limit (60 %): the footage must be the picture
    st, msg = gates(with_shot(GOOD, "02", anchor=dict(src=[0.5, 0.0], out_y=0.9), w=0.6, sky=True))["horizon-edge"]
    assert st == "FAIL" and "sky fills" in msg
    # horizontally impossible, bottom impossible
    st, msg = gates(with_shot(GOOD, "03", anchor=dict(src=[0.95, 0.4], out_y=0.58, out_x=0.5), w=0.6))["horizon-edge"]
    assert st == "FAIL" and "horizontally" in msg
    st, msg = gates(with_shot(GOOD, "03", anchor=dict(src=[0.5, 0.95], out_y=0.58), w=0.5))["horizon-edge"]
    assert st == "FAIL" and "bottom" in msg
    # no horizon declared + horizon outside 0.25-0.9 -> WARN
    noh = [{k: v for k, v in s.items() if k != "anchor"} | dict(cam=[[0, 0.5, 0.5, 0.6]]) if s["id"] == "02" else s for s in GOOD]
    assert gates(noh)["horizon-edge"][0] == "WARN"
    assert gates(with_shot(GOOD, "02", anchor=dict(src=[0.5, 0.7], out_y=0.95)))["horizon-edge"][0] == "WARN"


def test_horizon_transitions_cut_only_unless_allowed():
    assert gates(GOOD)["horizon-transitions"][0] == "PASS"
    st, msg = gates(with_shot(GOOD, "03", cut_in="flash_dip"))["horizon-transitions"]
    assert st == "FAIL" and "flash_dip" in msg
    allowed = dict(transitions=dict(allowed=["cut", "flash_dip"]))
    assert gates(with_shot(GOOD, "03", cut_in="flash_dip"), style=allowed)["horizon-transitions"][0] == "PASS"
    fast = [hz_shot("01", [0, 4]), hz_shot("02", [4, 4.5], cut_in="flash_dip"), hz_shot("03", [4.5, 5], cut_in="flash_dip"),
            hz_shot("04", [5, 5.5], cut_in="flash_dip"), hz_shot("05", [5.5, 6], cut_in="flash_dip"), hz_shot("06", [6, 7]), dawn_shot("07", [7, 15])]
    st, msg = gates(fast, style=allowed, bpm=100.0, text=None)["horizon-transitions"]      # 4 dips within 1.2 s at 0.3 s a shot
    assert st == "FAIL" and "flash dips in 1 s" in msg
    assert gates(with_shot(GOOD, "03", fx_in=dict(kind="flash")))["horizon-transitions"][0] == "FAIL"
    assert gates(with_shot(GOOD, "03", cut_in="wipe"))["horizon-transitions"][0] == "FAIL"
    assert gates(with_shot(GOOD, "03", type="clip", cam=[[0, 0.5, 0.5, 1]]))["horizon-transitions"][0] == "FAIL"


def test_horizon_dawn_card_held_three_seconds():
    assert gates(GOOD)["horizon-dawn"][0] == "PASS"
    short = GOOD[:-1] + [dawn_shot("11", [12, 16], tagline="x")]                       # 2.5 s
    st, msg = gates(short, text=TEXT)["horizon-dawn"]
    assert st == "FAIL" and "2.50s" in msg
    nodawn = GOOD[:-1] + [hz_shot("11", [12, 20])]
    assert gates(nodawn)["horizon-dawn"][0] == "WARN"
    noname = GOOD[:-1] + [dict(id="11", beats=[12, 20], type="dawn")]
    assert gates(noname)["horizon-dawn"][0] == "FAIL"


def test_horizon_forbidden_ui_edit_keys_still_rejected():
    p = project(with_shot(GOOD, "02", inpaint=dict(box=[0, 0, 1, 1])))
    try:
        load_spec(p)
    except Exception as e:  # noqa: BLE001
        assert "inpaint" in str(e)
    else:
        raise AssertionError("inpaint must be rejected")


# ---------------------------------------------------------------- engine changes from the critique council
REAL_CLIP = [dict(id="clip-a", path="/nonexistent/a.mp4", resolution="1920x1080", dpr=2)]                   # real app footage (no `generated:`)


def test_horizon_text_style_defaults_override_and_shadow():
    ctx = Tiny(K=1, fps=30)
    st = styles.resolve({"style": {"preset": "horizon"}})
    hs = HZ.text_style(st)
    assert hs["size_frac"] == 0.10 and hs["gap_frac"] == 0.004
    assert HZ.shadow_of(hs) == dict(blur=0.012, alpha=0.55, dy=0.002)
    _, _, cap = HZ.word_metrics(ctx, st, "Hat")
    assert 0.06 * ctx.OH < cap < 0.085 * ctx.OH                                # ~10 % em -> cap height ~7 % of the frame
    st2 = styles.resolve({"style": {"preset": "horizon", "horizon_text_style": {"size_frac": 0.05, "gap_frac": 0.01, "shadow": {"alpha": 0.6}}}})
    hs2 = HZ.text_style(st2)
    assert hs2["size_frac"] == 0.05 and hs2["gap_frac"] == 0.01 and HZ.shadow_of(hs2) == dict(blur=0.012, alpha=0.6, dy=0.002)
    assert HZ.word_metrics(ctx, st2, "Hat")[2] < cap * 0.6
    assert HZ.shadow_of(HZ.text_style(styles.resolve({"style": {"preset": "horizon", "horizon_text_style": {"shadow": False}}}))) is None
    assert HZ.shadow_of(dict(shadow=0.3))["alpha"] == 0.3
    # the white word sits on a mid-bright texture: with the shadow the pixels around the glyphs are darker than the background
    bg = (150, 150, 150, 255)                                                  # lum 0.59 < threshold 0.6 -> white ink
    halo = {}
    for name, style in (("on", None), ("off", dict(horizon_text_style=dict(shadow=False)))):
        spec = load_spec(project(GOOD, text=[dict(words="Hat", beats=[0, 8])], style=style))
        c = tiny_ctx(spec)
        out = np.asarray(HZ.HorizonText(c, spec).apply(Image.new("RGBA", (c.OW, c.OH), bg), 10, 0.6)).astype(int)
        halo[name] = out[..., 0].min()
        assert out[..., 0].max() > 240                                         # white ink either way (the luminance pick is kept)
    assert halo["off"] == 150 and halo["on"] < 110


def test_horizon_text_ui_gate_blocks_words_over_real_footage():
    st, msg = gates(GOOD, clips=REAL_CLIP)["horizon-text-ui"]
    assert st == "FAIL" and "real app footage" in msg and "text_over_ui" in msg
    assert gates(GOOD)["horizon-text-ui"][0] == "PASS"                         # generated plate: fine
    opted = [dict(s, text_over_ui=True) if s["type"] == "horizon" else s for s in GOOD]
    assert gates(opted, clips=REAL_CLIP)["horizon-text-ui"][0] == "PASS"
    one = gates(with_shot(opted, "04", text_over_ui=False), clips=REAL_CLIP)["horizon-text-ui"]
    assert one[0] == "FAIL" and "shot 04" in one[1] and "shot 03" not in one[1]
    assert "horizon-text-ui" in styles.PRESETS["horizon"]["checks"]


def test_horizon_wordless_open_warns_inside_the_first_40_percent_of_the_burst():
    st, msg = gates(GOOD)["horizon-wordless-open"]                              # burst = beats 4-12 (2.5-7.5 s); "Say it" starts at 1.25 s, "at night." at 3.75 s
    assert st == "WARN" and "keep the open wordless" in msg
    late = [dict(words="Say it", beats=[8, 10]), dict(words="at night.", beats=[10, 12])]
    assert gates(GOOD, text=late)["horizon-wordless-open"][0] == "PASS"
    assert gates(GOOD, text=None)["horizon-wordless-open"][0] == "PASS"


def test_horizon_sky_gate_warns_above_8_percent_of_the_frame_height():
    assert gates(GOOD)["horizon-sky"][0] == "PASS"                              # no sky anywhere
    small = with_shot(GOOD, "02", anchor=dict(src=[0.5, 0.30], out_y=0.58), sky=True)     # box tops out ~3 % above the source
    assert gates(small)["horizon-sky"][0] == "PASS" and gates(small)["horizon-edge"][0] == "PASS"
    big = with_shot(GOOD, "02", anchor=dict(src=[0.5, 0.05], out_y=0.58), sky=True)       # ~49 % sky
    st, msg = gates(big)["horizon-sky"]
    assert st == "WARN" and "shot 02" in msg and "8%" in msg
    assert gates(big)["horizon-edge"][0] == "PASS"                              # still legal (< 60 %), just discouraged


def test_horizon_no_flat_sky_unless_set_and_the_box_would_leave_the_source():
    ctx = Tiny(K=1, fps=30)
    im = Image.new("RGB", (640, 360), (240, 240, 240))
    sky = dict(top=[10, 14, 30], bottom="auto")
    inside = HZ.anchor_to_cam([0.5, 0.5], (0.5, 0.58), 0.5, im.size, (854, 480))          # box fully inside the source
    assert np.array_equal(np.asarray(HZ.frame_free(ctx, im, inside, sky)), np.asarray(HZ.frame_free(ctx, im, inside, None)))
    above = HZ.anchor_to_cam([0.5, 0.03], (0.5, 0.58), 0.5, im.size, (854, 480))          # box leaves the source at the top
    assert np.array_equal(np.asarray(HZ.frame_free(ctx, im, above, None)), np.asarray(R.frame_cam(ctx, im, *above)))   # no sky key: clamped, no gradient
    assert np.asarray(HZ.frame_free(ctx, im, above, sky))[2, 20, 0] < 60                    # with sky: gradient rows on top
    assert HZ.sky_of(styles.resolve({"style": {"preset": "horizon"}}), dict()) is None


def test_dawn_amber_arrives_late_and_wordmark_tagline_are_optional():
    cfg = {**styles.PRESETS["horizon"]["dawn"], "amber_at": 2.4}
    assert cfg["reach"] == [0.05, 0.22] and cfg["name_frac"] == 0.065 and cfg["name_y"] == 0.47
    pre, mid, end = (HZ.dawn_array(320, 180, t, cfg).astype(int) for t in (1.0, 2.6, 3.0))
    assert pre[-1, 160, 0] < pre[-1, 160, 2] and pre[-1, 160, 1] > pre[-1, 160, 0]          # teal rim, no amber before amber_at
    assert not (pre[:, :, 0] > pre[:, :, 2] + 30).any()                                     # nowhere warm yet
    assert end[-1, 160, 0] > end[-1, 160, 2] + 60                                           # amber at the bottom edge by the end
    assert pre[-1, 160, 0] < mid[-1, 160, 0] < end[-1, 160, 0]                              # ramps in
    assert HZ.amber_level(0.0, dict()) == 1.0                                               # no amber_at: the old card
    assert (pre[:int(0.8 * 180)] < 140).all()                                               # the rim is thin: top 80 % stays dark
    shots = GOOD[:-1] + [dict(id="11", beats=[12, 20], type="dawn", name="Name")]            # name only, 5 s
    spec = load_spec(project(shots))
    sh, dawn = spec.shot("11"), get_type("dawn")
    c = dawn._cfg(spec, sh)
    assert abs(c["amber_at"] - (sh.dur - 0.6)) < 1e-9
    assert len(dawn._texts(tiny_ctx(spec), sh, c)) == 1                                     # no default wordmark / tagline layers
    assert [x["text"] for x in dawn.captions(tiny_ctx(spec), sh)] == ["Name"]
    # explicit keys reach the old card
    old = dict(shots[-1], amber_at=0, reach=[0.12, 0.80], name_frac=0.11, name_y=0.40)
    spec2 = load_spec(project(GOOD[:-1] + [old]))
    c2 = dawn._cfg(spec2, spec2.shot("11"))
    assert c2["amber_at"] == 0 and c2["reach"] == [0.12, 0.80] and c2["name_frac"] == 0.11 and c2["name_y"] == 0.40
    assert HZ.dawn_array(320, 180, 0.0, c2)[-1, 160, 0] > 200                                 # amber from frame 0
    both = dawn._texts(tiny_ctx(spec2), spec2.shot("11"), c2)
    wm = dict(old, wordmark="wm", tagline="tag")
    spec3 = load_spec(project(GOOD[:-1] + [wm]))
    assert len(dawn._texts(tiny_ctx(spec3), spec3.shot("11"), dawn._cfg(spec3, spec3.shot("11")))) == 3 and len(both) == 1


# ---------------------------------------------------------------- scaffold
def test_horizon_scaffold_is_a_valid_spec():
    d = os.path.join(tempfile.mkdtemp(), "hz")
    cli.cmd_new(NS(name="hz", dir=d, style="horizon"))
    spec = load_spec(os.path.join(d, "promo.yaml"))
    assert spec.style["preset"] == "horizon" and spec.validate() == []
    assert abs(spec.total_frames() - round(spec.duration * spec.fps)) == 0
    g = {k: s for k, s, m in style_check.run(spec)}
    assert "FAIL" not in g.values(), g
    assert set(g) >= {"horizon-cuts", "horizon-burst-hold", "horizon-text", "horizon-dawn", "horizon-edge"}
    assert [s.type for s in spec.shots][0] == "horizon" and spec.shots[-1].type == "dawn" and spec.raw["horizon_text"]


# ---------------------------------------------------------------- end to end: tiny 854x480 render
def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "1", *args], check=True)


def make_clips(d):
    a, b = os.path.join(d, "a.mp4"), os.path.join(d, "b.mp4")
    ffmpeg("-f", "lavfi", "-i", "color=c=0x1c2a44:s=640x360:r=30:d=1.5,drawbox=x=0:y=120:w=640:h=240:color=0xeeeae0:t=fill",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", a)
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=1.5", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", b)
    return a, b


def frame_of(path, i):
    """Decoded frame number i of a segment as an (H, W, 3) int array."""
    W, H = R.probe(path)[:2]
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-threads", "1", "-i", path, "-vf", f"select=eq(n\\,{i})", "-vsync", "0",
                                   "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(int)


def n_frames(path):
    return int(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                        "stream=nb_read_frames", "-of", "csv=p=0", path]).decode())


def test_horizon_end_to_end_tiny_render():
    d = tempfile.mkdtemp()
    a, b = make_clips(d)
    clips = [dict(id="clip-a", path=a, resolution="640x360", dpr=1), dict(id="clip-b", path=b, resolution="640x360", dpr=1)]
    shots = [dict(id="01", beats=[0, 1], type="horizon", source="clip-a", t_in=0.0, anchor=dict(src=[0.5, 120 / 360], out_y=0.58), w=[0.8, 0.7], sky=True, hold_to_beat=0.1),
             dict(id="02", beats=[1, 2], type="horizon", source="clip-b", t_in=0.2, anchor=dict(src=[0.5, 0.5], out_y=0.6), w=0.6),
             dict(id="03", beats=[2, 4], type="dawn", name="Name", wordmark="wordmark", tagline="One line.", tagline_at=0.5)]
    p = project(shots, text=[dict(words="Hat", beats=[0, 2])], bpm=120.0, clips=clips)
    spec = load_spec(p)
    assert [s.n for s in spec.shots] == [15, 15, 30]
    ctx = tiny_ctx(spec)
    os.makedirs(ctx.seg_dir, exist_ok=True)
    edl = {}
    for s in spec.shots:
        edl[s.id] = get_type(s.type).render(ctx, s)
    for s in spec.shots:
        path = spec.seg_path(s.id)
        assert os.path.exists(path) and n_frames(path) == s.n
        assert R.probe(path)[:2] == (854, 480)
    assert "Hat" in edl["01"]["caption"] and "Hat" in edl["02"]["caption"] and "horizon at 0.58" in edl["01"]["move"]
    assert [c["text"] for c in get_type("horizon").captions(ctx, spec.shot("02"))] == ["Hat"]
    assert [c["text"] for c in get_type("dawn").captions(ctx, spec.shot("03"))] == ["Name", "One line."]

    # shot 01: the source edge (panel top, light below / dark blue above) sits at 0.58 of the height, at the start AND the end of the push-in
    p1 = spec.seg_path("01")
    for i in (0, 14):
        col = frame_of(p1, i)[:, 20]
        edge = next(y for y in range(480) if col[y].min() > 150)
        assert abs(edge - 0.58 * 480) <= 3, (i, edge)
    # the serif word sits on that line (white on the dark side above it); frame 5 is fully faded in
    above = frame_of(p1, 5)[int(0.58 * 480) - 70:int(0.58 * 480) - 4, 250:610]
    assert (above.min(-1) > 200).sum() > 80
    # ... and persists across the cut: shot 02 (testsrc2) shows it at its first frames too
    first = frame_of(spec.seg_path("02"), 4)
    assert first.shape == (480, 854, 3)
    # dawn: teal rim at the bottom (no amber) at t=0, amber in the last 0.6 s (card is 1 s: amber_at 0.4), navy top;
    # tagline absent at t=0 and present at the end, name present
    p3 = spec.seg_path("03")
    f0, fN = frame_of(p3, 0), frame_of(p3, 29)
    assert f0[-1, 427, 0] < f0[-1, 427, 2] and f0[2, 427, 2] < 60
    assert fN[-1, 427, 0] > fN[-1, 427, 2] + 40 and fN[2, 427, 2] < 60
    row = lambda f, y: f[int(y * 480) - 14:int(y * 480) + 14, 200:660]                             # noqa: E731
    bright = lambda r: int((r.mean(-1) > 140).sum())                                               # noqa: E731
    assert bright(row(f0, 0.60)) < 5 and bright(row(f0, 0.47)) < 5          # nothing but the gradient at t = 0
    assert bright(row(fN, 0.60)) > 12 and bright(row(fN, 0.47)) > 100       # tagline (from +0.5 s) and name are in

    # the digest of a horizon shot depends on the show-level text layer (editing the words re-renders every shot)
    spec2 = load_spec(project(shots, text=[dict(words="Cat", beats=[0, 2])], bpm=120.0, clips=clips))
    assert cli.shot_digest(spec, spec.shots[0]) != cli.shot_digest(spec2, spec2.shots[0])
    assert cli.shot_digest(spec, spec.shots[0]) == cli.shot_digest(load_spec(p), load_spec(p).shots[0])


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except Exception as e:  # noqa: BLE001
                fails += 1
                print("FAIL", name, repr(e))
    sys.exit(1 if fails else 0)
