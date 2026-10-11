"""Podcast / VTuber show tests: the performance layer (visemes, exp3 / motion3 maths, moods), script -> timeline, the
overlay geometry ("no box"), the QA gates and bring-your-own models. Pure Python unless a test says it renders."""
import copy
import json
import os
import sys

import numpy as np
import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo import live2d as L2  # noqa: E402
from promo import perform as PF  # noqa: E402
from promo import podcast as P  # noqa: E402
from promo.spec import Spec  # noqa: E402


@pytest.fixture(autouse=True)
def _no_renders(monkeypatch, request):
    """The gates measure each host's silhouette with a real Live2D render; tests use the body box unless they render on purpose."""
    if "renders" not in request.keywords:
        monkeypatch.setattr(P, "silhouette", lambda spec, i: None)


def _render_ready():
    import shutil
    try:
        L2.resolve_model("hiyori")
    except L2.Live2DError:
        return False
    return bool(shutil.which(os.environ.get("PROMO_NODE", "node"))) and os.path.isdir(os.path.join(L2.L2D_DIR, "node_modules", "pixi-live2d-display"))


# ---------------------------------------------------------------- visemes
def _vowel(f1, f2, sr=24000, dur=0.35, f0=210.0, f3=2900.0):
    """Source-filter vowel: a glottal pulse train through three two-pole resonators at F1 / F2 / F3."""
    from scipy.signal import lfilter
    n = int(sr * dur)
    x = np.zeros(n)
    x[:: int(sr / f0)] = 1.0
    for f, bw in ((f1, 80.0), (f2, 110.0), (f3, 160.0)):
        r = np.exp(-np.pi * bw / sr)
        x = lfilter([1 - r], [1, -2 * r * np.cos(2 * np.pi * f / sr), r * r], x)
    return (0.3 * x / np.abs(x).max()).astype(np.float32)


def test_formants_and_vowel_classifier_on_synthetic_vowels():
    sr = 24000
    for v, (f1, f2) in PF.PROTO.items():
        y = _vowel(f1, f2, sr)
        fm = PF.formants(y[2000:2000 + 720].astype(np.float64), sr)
        assert fm is not None, v
        assert abs(fm[0] - f1) < 0.2 * f1 and abs(fm[1] - f2) < 0.2 * f2, (v, fm)
        w = PF.vowel_weights(*fm)
        assert max(w, key=w.get) == v, (v, fm, w)


def test_visemes_follow_the_vowel_sequence():
    sr, fps = 24000, 30
    seq = ["A", "I", "O", "E", "U"]
    gap = np.zeros(int(0.1 * sr), np.float32)
    y = np.concatenate([np.concatenate([_vowel(*PF.PROTO[v], sr=sr), gap]) for v in seq])
    n = int(len(y) / sr * fps)
    mouth = L2.lip_track(y, sr, fps, n, form=False)["open"]
    vs = PF.visemes(y, sr, fps, n, mouth)
    seg = int((0.35 + 0.1) * fps)
    for k, v in enumerate(seq):
        mid = k * seg + int(0.2 * fps)
        w = {x: vs[x][mid] for x in PF.VOWELS}
        assert max(w, key=w.get) == v, (v, w)
        assert abs(sum(w.values()) - sum(mouth[mid] * PF.VOWEL_GAIN[x] * vs["weights"][mid][j] for j, x in enumerate(PF.VOWELS))) < 1e-9
    assert vs["form"][int(1 * seg + 0.2 * fps)] > 0.3            # I: wide
    assert vs["form"][int(2 * seg + 0.2 * fps)] < -0.3           # O: round


# ---------------------------------------------------------------- exp3 / layers maths
def test_exp3_blend_maths_and_layer_order():
    n = 5
    w = np.array([0.0, 0.25, 0.5, 1.0, 1.0])
    L = {"ParamEyeLOpen": {"set": np.ones(n)}, "ParamMouthForm": {"set": np.full(n, 0.2)}}
    PF.apply_targets(L, [("ParamEyeLOpen", "mul", 0.0), ("ParamCheek", "add", 1.0), ("ParamMouthForm", "set", -1.0)], w)
    eye = PF.apply_layers(L["ParamEyeLOpen"], n, lo=0, hi=1)
    assert np.allclose(eye, 1 - w)                                         # Multiply: x (1 + (v - 1) w)
    cheek = PF.apply_layers(L["ParamCheek"], n, default=0.0, lo=0, hi=1)
    assert np.allclose(cheek, w)                                           # Add on the default
    form = PF.apply_layers(L["ParamMouthForm"], n, lo=-1, hi=1)
    assert np.allclose(form, 0.2 * (1 - w) - w)                             # Overwrite: blend toward the value
    # order: set -> blend -> add -> mul, clamped after every step
    d = {"set": np.array([0.9]), "add": np.array([0.5]), "mul": np.array([0.5])}
    assert np.allclose(PF.apply_layers(d, 1, lo=0, hi=1), [0.5])            # (0.9 + 0.5 -> clamp 1.0) * 0.5
    jt = PF.job_tracks({"ParamX": d, "ParamY": np.array([0.1, 0.2])})
    assert [l["mode"] for l in jt["ParamX"]] == ["set", "add", "mul"] and jt["ParamY"] == [dict(mode="set", v=[0.1, 0.2])]


def test_exp3_file_and_mood_targets(tmp_path):
    e = tmp_path / "smile.exp3.json"
    e.write_text(json.dumps({"Type": "Live2D Expression", "FadeInTime": 0.4, "FadeOutTime": 0.6, "Parameters": [
        {"Id": "ParamEyeLSmile", "Value": 1.0, "Blend": "Add"}, {"Id": "ParamEyeLOpen", "Value": 0.5, "Blend": "Multiply"},
        {"Id": "ParamMouthForm", "Value": 1.0, "Blend": "Overwrite"}]}))
    model = dict(id="m", expressions={"smile": str(e)}, moods={"happy": {"exp": "smile", "weight": 0.5}, "sad": {"params": {"ParamCheek": ["add", -0.2]}}})
    tg, fi, fo = PF.mood_targets(model, "happy")
    assert ("ParamEyeLSmile", "add", 0.5) in tg and ("ParamEyeLOpen", "mul", 0.75) in tg and ("ParamMouthForm", "set", 1.0) in tg
    assert (fi, fo) == (0.4, 0.6)
    assert PF.mood_targets(model, "sad")[0] == [("ParamCheek", "add", -0.2)]
    assert PF.mood_targets(model, "laugh")[0] == PF.GENERIC_MOODS["laugh"]                 # no entry: generic
    with pytest.raises(PF.PerformError):
        PF.mood_targets(model, "furious")
    assert PF.mood_name("happy:0.6") == ("happy", 0.6) and PF.mood_name({"name": "sad", "amount": 0.3}) == ("sad", 0.3)


def test_auto_moods_from_expression_names():
    m = PF.auto_moods(["exp_Smile", "Angry_01", "cry", "surprise!", "Wink", "neutral"])
    assert m["happy"] == {"exp": "exp_Smile"} and m["serious"] == {"exp": "Angry_01"} and m["sad"] == {"exp": "cry"}
    assert m["surprised"] == {"exp": "surprise!"} and m["smug"] == {"exp": "Wink"} and "laugh" not in m


# ---------------------------------------------------------------- motion3
def test_motion3_segments_linear_bezier_stepped_inverse():
    segs = [0, 0,  0, 1, 10,  1, 1.5, 10, 2.5, 20, 3, 20,  2, 4, 0,  3, 5, 7]
    parsed = PF.parse_segments(segs)
    assert [k for k, _ in parsed[0]] == [0, 1, 2, 3]
    ev = lambda t: PF.eval_curve(parsed, t)
    assert ev(0.5) == pytest.approx(5.0)                    # linear 0 -> 10 over 1 s
    assert ev(1.0) == pytest.approx(10.0)
    assert ev(2.0) == pytest.approx(15.0)                   # symmetric bezier 10 -> 20: half way at the middle
    assert ev(3.5) == pytest.approx(20.0)                   # stepped: holds the start value
    assert ev(4.5) == pytest.approx(7.0)                    # inverse stepped: the end value at once
    assert ev(9) == pytest.approx(7.0)


def test_motion_layers_blend_with_fades(tmp_path):
    p = tmp_path / "wave.motion3.json"
    p.write_text(json.dumps({"Version": 3, "Meta": {"Duration": 2.0, "Fps": 30, "Loop": False, "FadeInTime": 0.5, "FadeOutTime": 0.5},
                             "Curves": [{"Target": "Parameter", "Id": "ParamArmLA", "Segments": [0, 0, 0, 2, 10]},
                                        {"Target": "Parameter", "Id": "ParamMouthOpenY", "Segments": [0, 1, 0, 2, 1]},
                                        {"Target": "PartOpacity", "Id": "PartArm", "Segments": [0, 1, 0, 2, 1]}]}))
    mot = PF.load_motion3(str(p))
    assert set(mot["curves"]) == {"ParamArmLA", "ParamMouthOpenY"}
    L = {}
    PF.motion_layers(L, mot, 90, 30, 1.0, 2.0)
    assert "ParamMouthOpenY" not in L                       # lip sync owns the mouth
    (v, w), = L["ParamArmLA"]["blend"]
    assert w[0] == 0 and w[37] == pytest.approx(0.5 - 0.5 * np.cos(np.pi * (37 / 30 - 1.0) / 0.5)) and w[int(2.0 * 30)] == pytest.approx(1.0)
    assert np.all(np.diff(w[30:46]) >= 0)                   # eased in over the motion's FadeInTime
    assert v[int(2.0 * 30)] == pytest.approx(5.0, abs=0.2)  # 1 s into the motion: half way up the ramp


def test_perform_is_deterministic_and_drives_the_face():
    model = dict(L2.model_entry("hiyori"), id="hiyori", groups={"LipSync": ["ParamMouthOpenY"], "EyeBlink": ["ParamEyeLOpen", "ParamEyeROpen"]},
                 expressions={}, motions={}, param_ids=[])
    sr, fps, n = 24000, 30, 150
    y = np.concatenate([_vowel(*PF.PROTO["A"], sr=sr, dur=1.5), np.zeros(int(3.5 * sr), np.float32)])
    mouth = L2.lip_track(y, sr, fps, n, form=False)["open"]
    base = L2.idle_tracks(n, fps, 3, None, None, 0.0)
    lines = [dict(id="a1", t0=0.0, t1=1.5, mood="happy", gesture="nod")]
    partner = [dict(id="b1", t0=2.0, t1=4.0, mood="laugh")]
    pm = np.zeros(n)
    pm[60:120] = 0.6
    a, ia = PF.perform(model, n, fps, 3, base, mouth=mouth, y=y, sr=sr, lines=lines, partner_lines=partner, partner_mouth=pm, partner_dir=1.0)
    b, _ = PF.perform(model, n, fps, 3, base, mouth=mouth, y=y, sr=sr, lines=lines, partner_lines=partner, partner_mouth=pm, partner_dir=1.0)
    assert json.dumps(PF.job_tracks(a)) == json.dumps(PF.job_tracks(b))
    smile = PF.apply_layers(a["ParamEyeLSmile"], n)
    assert smile[20] > 0.3 and smile[149] < 0.05            # happy during the line, gone by the end
    assert smile[100] > 0.2                                 # the listener mirrors the partner's laugh (as happy)
    ay = PF.apply_layers(a["ParamAngleY"], n)
    assert ay[:30].min() < ay[40:].mean() - 3               # the nod at the line start
    ax = PF.apply_layers(a["ParamAngleX"], n)
    assert ax[90:120].mean() > ax[:30].mean() + 3           # turns toward the partner (right) while they talk
    assert ia["gestures"] and ia["moods"]


# ---------------------------------------------------------------- spec helpers
def _raw(**over):
    raw = dict(
        project=dict(name="pc"), output=dict(name="pc", resolution=1080, fps=30, duration=20.0), assets="assets.yaml", footage="footage/manifest.yaml",
        style=dict(preset="podcast"),
        podcast=dict(title="Test", tag="EP 1", layout="overlay",
                     hosts=[dict(id="a", model="mao", name="Mao", voice=dict(engine="kokoro", voice="af_heart")),
                            dict(id="b", model="hiyori", name="Hiyori", voice=dict(engine="kokoro", voice="bf_emma"))]),
        vo=dict(engine="kokoro", model_asset="kokoro-model", voices_asset="kokoro-voices", lines=[
            dict(id="a1", shot="01", at=0.5, host="a", text="Hello there, welcome to the show.", claim=False),
            dict(id="b1", shot="01", at=3.5, host="b", text="Thanks! Let's look at the app.", claim=False)]),
        timeline=dict(bpm=120, beats=40),
        shots=[dict(id="01", type="podcast", beats=[0, 32], layout="overlay", screen=dict(card=dict(title="App"))),
               dict(id="02", type="live2d_credits", beats=[32, 40], size=30, fade_in=0.25)])
    raw.update(over)
    return raw


ASSETS = {"assets": [dict(id="kokoro-model", kind="vo_model", path="m.onnx", licence="Apache-2.0", source_url="https://huggingface.co/hexgrad/Kokoro-82M"),
                     dict(id="kokoro-voices", kind="vo_model", path="v.bin", licence="Apache-2.0", source_url="https://huggingface.co/hexgrad/Kokoro-82M")]}


def _spec(tmp_path, raw=None, mut=None):
    raw = copy.deepcopy(raw or _raw())
    if mut:
        mut(raw)
    (tmp_path / "assets.yaml").write_text(yaml.safe_dump(ASSETS))
    (tmp_path / "footage").mkdir(exist_ok=True)
    (tmp_path / "footage" / "manifest.yaml").write_text("clips: []\n")
    p = tmp_path / "promo.yaml"
    p.write_text(yaml.safe_dump(raw))
    P._M_CACHE.clear()
    return Spec(str(p), raw)


def _gates(spec):
    return {g: (st, msg) for g, st, msg in P.check(spec)}


# ---------------------------------------------------------------- script -> timeline
def test_lay_out_on_the_half_beat_grid():
    script = [dict(host="a"), dict(host="b"), dict(host="b", pause=0.8)]
    starts, end, k_total = P.lay_out(script, [2.1, 1.3, 0.9], bpm=120, lead_in=0.75, tail=0.8, credits_s=3.0)
    hb = 0.25
    assert [s for s, _ in starts] == [0.75, 3.0, 5.25]          # 0.75; 0.75+2.1+0.15 -> 3.0; 3.0+1.3+0.8 -> 5.1 -> 5.25
    assert all(abs(s / hb - round(s / hb)) < 1e-9 for s, _ in starts)
    assert end == pytest.approx(7.0) and k_total == 28 + 12      # 5.25+0.9+0.8 = 6.95 -> 7.0; + 3 s of credits


def test_plan_shots_scenes_reactions_and_credits():
    c = dict(layout="overlay", hosts=[dict(id="a", model="mao"), dict(id="b", model="hiyori")])
    script = [dict(host="a", text="one"), dict(host="b", text="two"), dict(host="a", text="three", scene=dict(layout="two-shot", next_screen=True)),
              dict(host="b", text="Really?", mood="surprised"), dict(host="a", text="four"), dict(host="b", text="five"), dict(host="a", text="six")]
    durs = [3.0, 3.0, 3.0, 1.2, 3.0, 3.0, 3.0]
    ids = P.line_ids(c, script)
    assert ids == ["a1", "b1", "a2", "b2", "a3", "b3", "a4"]
    starts, end, k_total = P.lay_out(script, durs)
    k_end = int(round(end / 0.25))
    screens = [dict(source="take-1", t_in=0.0), dict(source="take-2", t_in=1.0)]
    shots, lines = P.plan_shots(c, script, ids, starts, durs, k_end, k_total, screens)
    kinds = [(s["type"], s.get("layout"), (s.get("screen") or {}).get("source")) for s in shots]
    assert kinds[0] == ("podcast", "overlay", "take-1")
    assert ("podcast", "two-shot", "take-2") in kinds
    assert ("podcast", "speaker", "take-2") in kinds                     # the reaction gets a speaker cam on the same take
    assert kinds[-1][0] == "live2d_credits" and shots[-1]["beats"][1] == k_total / 2
    for a, b in zip(shots, shots[1:]):
        assert a["beats"][1] == b["beats"][0]
    for s in shots[:-1]:
        assert (s["beats"][1] - s["beats"][0]) * 0.5 >= 3.0 - 1e-9       # shots hold >= 3 s
    sp = next(s for s in shots if s["layout"] == "speaker")
    tw = next(s for s in shots if s["layout"] == "two-shot")
    assert sp["screen"]["t_in"] > tw["screen"]["t_in"]                  # the take plays on across the cut
    by = {x["id"]: x for x in lines}
    assert by["b2"]["shot"] == sp["id"] and by["b2"]["at"] == 0.0
    for x in lines:
        s = next(s for s in shots if s["id"] == x["shot"])
        assert 0 <= x["at"] < (s["beats"][1] - s["beats"][0]) * 0.5


def test_validate_script_catches_mistakes():
    c = dict(hosts=[dict(id="a", model="mao")])
    probs = P.validate_script(c, [dict(host="z", text="hi"), dict(host="a", text="", mood="angry", gesture="dab", look="sky", color="red")])
    assert any("host 'z'" in p for p in probs) and any("no text" in p for p in probs) and any("mood 'angry'" in p for p in probs)
    assert any("gesture 'dab'" in p for p in probs) and any("look 'sky'" in p for p in probs) and any("unknown keys" in p for p in probs)


def test_subtitle_rows_chunks_and_holds():
    assert all(len(r) <= 35 for r in P.chunk_text("This sentence is quite a bit longer than thirty five characters, honestly, and keeps going."))
    assert P.chunk_text("Short.") == ["Short."]
    lines = [dict(id="a1", host=0, t0=0.0, t1=1.0, text="Yes!"), dict(id="b1", host=1, t0=1.2, t1=6.0,
             text="And here is a longer answer that will need two or three rows to read.")]
    rows = P.subtitle_rows(type("S", (), {"raw": {"podcast": {}}})(), lines)
    assert rows[0]["text"] == "Yes!" and rows[0]["t1"] - rows[0]["t0"] >= 2.0
    assert all(r["t1"] - r["t0"] >= 2.0 - 1e-9 and len(r["text"]) <= 35 for r in rows)
    for k in range(2, len(rows)):                                          # never more than two rows at once
        assert rows[k]["t0"] >= rows[k - 2]["t1"] - 1e-9 or rows[k]["t0"] >= rows[k - 2]["t0"] + 2.0 - 1e-9
    assert len(P.rows_at(rows, 1.5)) <= 2


# ---------------------------------------------------------------- geometry + "no box"
def test_overlay_geometry_hosts_at_the_bottom_corners(tmp_path):
    spec = _spec(tmp_path)
    M = P.master(spec)
    assert M["pad"] > 0                                                   # Mao's hat needs headroom: never clipped
    L = P.layout_at(spec, spec.shots[0], 1.0, [])
    a, b = L["hosts"]
    assert L["screen_full"] and L["screen"] == [0, 0, 1920, 1080]
    assert a["xc"] < 960 < b["xc"]
    for g in (a, b):
        assert g["layer"][3] == pytest.approx(1080)                       # the bust is cut by the frame's bottom edge
        assert g["top"] >= 0 and g["panel"] is None
    fa, fb = a["face"][3] - a["face"][1], b["face"][3] - b["face"][1]
    assert abs(fa - fb) < 0.05 * fa                                       # same head size for both rigs


def _fake_master(W, H, face, color):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([face[0], face[1], face[2], face[3]], fill=color + (255,))
    d.rectangle([W * 0.3, face[3], W * 0.7, H], fill=color + (255,))
    return im


def _compose(spec, frame=None, edge="none"):
    from promo.render import RenderContext
    from promo.shots.podcast import Composer
    shot = spec.shots[0]
    shot.cfg["frame"], shot.cfg["edge"] = frame or "none", edge
    ctx = RenderContext.from_spec(spec)
    ctx.font_path = L2.SHEET_FONTS[[os.path.exists(f) for f in L2.SHEET_FONTS].index(True)]
    M = P.master(spec)
    frames = [_fake_master(m["W"], M["H"], m["face"], (230, 80, 60)) for m in M["hosts"]]
    comp = Composer(ctx, shot, lines=[])
    comp.title_pill = None
    comp.show_names = False
    with_hosts = np.asarray(comp.frame(1.0, frames)).astype(int)
    without = np.asarray(comp.frame(1.0, [None, None])).astype(int)
    return with_hosts, without, P.layout_at(spec, shot, 1.0, [])


def _alpha_mask(spec, L, grow=4):
    """Where the hosts' own (fake) pixels land on the frame, grown by `grow` px for the resampling filter."""
    from scipy.ndimage import binary_dilation

    from promo.shots.podcast import scale_layer
    M = P.master(spec)
    mask = np.zeros((1080, 1920), bool)
    for g, mh in zip(L["hosts"], M["hosts"]):
        im = scale_layer(_fake_master(mh["W"], M["H"], mh["face"], (230, 80, 60)), int(round(g["layer"][2] - g["layer"][0])), int(round(g["layer"][3] - g["layer"][1])))
        a = np.asarray(im.getchannel("A")) > 0
        x0, y0 = int(round(g["layer"][0])), int(round(g["layer"][1]))
        ys, xs = np.nonzero(a)
        ys, xs = ys + y0, xs + x0
        ok = (xs >= 0) & (xs < 1920) & (ys >= 0) & (ys < 1080)
        mask[ys[ok], xs[ok]] = True
    return binary_dilation(mask, iterations=grow)


def test_overlay_has_no_panel_pixels(tmp_path):
    """Default overlay: outside each host's own silhouette the frame is the untouched screen (no box, no panel)."""
    spec = _spec(tmp_path, mut=lambda r: r["podcast"].update(names=False))
    a, b, L = _compose(spec)
    diff = np.abs(a - b).max(-1) > 0
    host_mask = _alpha_mask(spec, L)
    assert diff.any()
    assert not (diff & ~host_mask).any(), int((diff & ~host_mask).sum())
    # a box is one toggle away: frame card draws a panel around the bust
    a2, b2, _ = _compose(spec, frame="card")
    assert ((np.abs(a2 - b2).max(-1) > 0) & ~host_mask).sum() > 5000


def test_edge_shadow_stays_near_the_silhouette(tmp_path):
    spec = _spec(tmp_path, mut=lambda r: r["podcast"].update(names=False))
    a, b, L = _compose(spec, edge="shadow")
    diff = np.abs(a - b).max(-1) > 2
    near = np.zeros(diff.shape, bool)
    for g in L["hosts"]:                                     # the shadow stays within 40 px of the host's layer
        x0, y0, x1, y1 = [int(round(v)) for v in g["layer"]]
        near[max(0, y0 - 40):y1 + 40, max(0, x0 - 40):x1 + 40] = True
    assert diff.any() and not (diff & ~near).any()
    assert not diff[:, 760:1160].any()                       # nothing between the two hosts


# ---------------------------------------------------------------- gates
def test_podcast_gates_pass_on_a_clean_show(tmp_path):
    g = _gates(_spec(tmp_path))
    bad = {k: v for k, v in g.items() if v[0] == "FAIL"}
    assert not bad, bad
    assert g["podcast-licence"][0] == "PASS" and "credits on 02" in g["podcast-licence"][1]


def test_gates_fail_on_clipping_keep_clear_credits_and_lint(tmp_path):
    def clipped(r):
        r["podcast"]["place"] = {"a": {"size": "xl", "y": -320}}
    assert "clipped at the top" in _gates(_spec(tmp_path, mut=clipped))["podcast-framing"][1]

    def kc(r):
        r["podcast"]["keep_clear"] = [{"name": "corner", "box": [0.0, 0.7, 0.2, 1.0]}]
    assert "covers keep-clear 'corner'" in _gates(_spec(tmp_path, mut=kc))["podcast-framing"][1]

    def kc_other_take(r):
        r["podcast"]["keep_clear"] = [{"name": "corner", "box": [0.0, 0.7, 0.2, 1.0], "source": "another-take"}]
    assert _gates(_spec(tmp_path, mut=kc_other_take))["podcast-framing"][0] == "PASS"

    def no_credits(r):
        r["shots"] = [dict(r["shots"][0], beats=[0, 40])]
    assert "no end-card credit" in _gates(_spec(tmp_path, mut=no_credits))["podcast-licence"][1]

    def live(r):
        r["podcast"]["tag"] = "LIVE now"
    assert _gates(_spec(tmp_path, mut=live))["podcast-lint"][0] == "FAIL"

    def overlap_faces(r):
        r["podcast"]["place"] = {"a": {"anchor": "bottom-center"}, "b": {"anchor": "bottom-center", "x": 40}}
    assert "covers host a's face" in _gates(_spec(tmp_path, mut=overlap_faces))["podcast-framing"][1]


def test_truth_and_voice_licence_gates(tmp_path):
    def claim(r):
        r["vo"]["lines"][0] = dict(r["vo"]["lines"][0], text="It merged 8 pull requests overnight.", claim=None)
    g = _gates(_spec(tmp_path, mut=claim))
    assert g["podcast-truth"][0] == "FAIL" and "a1" in g["podcast-truth"][1]

    def with_ev(r):
        claim(r)
        r["vo"]["lines"][0]["evidence"] = "run 42, board screenshot"
    assert _gates(_spec(tmp_path, mut=with_ev))["podcast-truth"][0] == "PASS"

    def say(r):
        r["podcast"]["hosts"][1]["voice"] = {"engine": "say", "voice": "Flo (English (UK))"}
    g = _gates(_spec(tmp_path, mut=say))
    assert g["podcast-voice-licence"][0] == "FAIL"                     # a say voice needs its licence entry

    def say_ok(r):
        r["podcast"]["hosts"][1]["voice"] = {"engine": "say", "voice": "Flo (English (UK))", "asset": "say-voice"}
    spec = _spec(tmp_path, mut=say_ok)
    with open(tmp_path / "assets.yaml") as f:
        a = yaml.safe_load(f)
    a["assets"].append(dict(id="say-voice", kind="vo_model", path="/usr/bin/say", licence="Apple: personal, non-commercial", source_url="https://www.apple.com/legal/sla/"))
    (tmp_path / "assets.yaml").write_text(yaml.safe_dump(a))
    g = _gates(spec)
    assert g["podcast-voice-licence"][0] == "PASS" and g["draft-voice"][0] == "WARN"


def test_voice_resolution_order(tmp_path):
    from promo import vo as VO
    spec = _spec(tmp_path, mut=lambda r: r["vo"]["lines"][1].update(voice={"speed": 1.2}))
    v = {lid: x for lid, x in VO.voices_used(spec)}
    assert v["a1"]["voice"] == "af_heart" and v["a1"]["lang"] == "en-us"
    assert v["b1"]["voice"] == "bf_emma" and v["b1"]["speed"] == 1.2 and v["b1"]["lang"] == "en-gb"


def test_set_ops(tmp_path):
    raw = _raw()
    P.set_host(raw, "a", {"place": "bottom-right", "size": "xl", "frame": "card", "voice": "af_bella"})
    assert raw["podcast"]["place"]["a"] == {"anchor": "bottom-right", "size": "xl"}
    assert raw["podcast"]["frame"] == "card" and raw["podcast"]["hosts"][0]["voice"]["voice"] == "af_bella"
    P.set_show(raw, "layout", "speaker", shot="01")
    assert raw["shots"][0]["layout"] == "speaker" and raw["shots"][0]["focus"] == "auto"
    P.set_show(raw, "subtitles", "off")
    assert P.subtitles_on(raw["podcast"]) is False
    P.set_show(raw, "backdrop", "gradient=#101020,#402060")
    assert raw["podcast"]["backdrop"]["gradient"] == [[16, 16, 32], [64, 32, 96]]
    for bad in (lambda: P.set_show(raw, "layout", "grid"), lambda: P.set_host(raw, "z", {"size": "l"}), lambda: P.set_host(raw, "a", {"size": "huge"}),
                lambda: P.set_show(raw, "layout", "overlay", shot="02")):
        with pytest.raises(ValueError):
            bad()
    assert P.subtitles_on({"subtitles": {True: False}}) is False           # YAML's bare `on: false`


# ---------------------------------------------------------------- bring your own model
def _fake_model(d):
    rt = d / "runtime"
    (rt / "exp").mkdir(parents=True)
    for nm in ("Smile", "Angry", "Shock"):
        (rt / "exp" / f"{nm}.exp3.json").write_text(json.dumps({"Type": "Live2D Expression", "Parameters": [{"Id": "ParamCheek", "Value": 1, "Blend": "Add"}]}))
    (rt / "char.cdi3.json").write_text(json.dumps({"Parameters": [{"Id": x, "Name": x} for x in
                                                   ("ParamAngleX", "ParamEyeLOpen", "ParamA", "ParamI", "ParamU", "ParamE", "ParamO", "ParamMouthUp")]}))
    (rt / "char.model3.json").write_text(json.dumps({"Version": 3, "FileReferences": {
        "Moc": "char.moc3", "Textures": [], "DisplayInfo": "char.cdi3.json",
        "Expressions": [{"Name": nm, "File": f"exp/{nm}.exp3.json"} for nm in ("Smile", "Angry", "Shock")],
        "Motions": {"Idle": [{"File": "m/idle.motion3.json"}]}}, "Groups": [{"Target": "Parameter", "Name": "LipSync", "Ids": ["ParamA"]}]}))
    return rt / "char.model3.json"


def test_bring_your_own_model_registry_and_licence_gate(tmp_path, monkeypatch):
    reg = tmp_path / "live2d-models.yaml"
    monkeypatch.setenv("PROMO_LIVE2D_MODELS", str(reg))
    p = _fake_model(tmp_path / "mychar")
    with pytest.raises(L2.Live2DError, match="licence"):
        L2.add_model(str(tmp_path / "mychar"), "mine", "Mine", "", "https://artist.example", "commissioned", measure=False)
    with pytest.raises(L2.Live2DError, match="refused"):
        L2.add_model(str(tmp_path / "mychar"), "mine", "Mine", "x", "y", "collaboration", measure=False)
    with pytest.raises(L2.Live2DError, match="sample model id"):
        L2.add_model(str(tmp_path / "mychar"), "mao", "Mao2", "x", "y", "own", measure=False)
    rep = L2.add_model(str(tmp_path / "mychar"), "mine", "Mine", "Commissioned 2026, commercial use", "https://artist.example/order/1", "commissioned",
                       credit="Art + rig: An Artist", measure=False)
    assert rep["model3"] == str(p)
    assert rep["mouth"]["vowels"] == {v: f"Param{v}" for v in PF.VOWELS} and rep["mouth"]["open"] == ["ParamA"]
    assert rep["moods"] == {"happy": {"exp": "Smile"}, "serious": {"exp": "Angry"}, "surprised": {"exp": "Shock"}}
    m = L2.model_entry("mine")
    assert m["user"] and m["character_type"] == "commissioned"
    assert "mine" in L2.registry()["models"] and "mine" not in L2.registry(user=False)["models"]
    info = L2.model3_info(str(p))
    assert info["motions"]["idle"].endswith("idle.motion3.json") and info["motions"]["Idle:0"] == info["motions"]["idle"]
    with pytest.raises(L2.Live2DError, match="already registered"):
        L2.add_model(str(tmp_path / "mychar"), "mine", "Mine", "x", "y", "own", measure=False)
    # an entry edited by hand without a licence is refused at use
    data = yaml.safe_load(reg.read_text())
    data["models"]["mine"]["licence"] = ""
    reg.write_text(yaml.safe_dump(data))
    with pytest.raises(L2.Live2DError, match="licence"):
        L2.model_entry("mine")


@pytest.mark.renders
def test_silhouette_is_measured_from_a_real_render(tmp_path):
    if not _render_ready():
        pytest.skip("needs `promo live2d fetch` + node + live2d/node_modules")
    spec = _spec(tmp_path)
    M = P.master(spec)
    for i, mh in enumerate(M["hosts"]):
        sil = P.silhouette(spec, i)
        rows = [r for r in sil if r]
        assert rows and min(r[0] for r in rows) >= -0.05 * mh["W"] and max(r[1] for r in rows) <= 1.05 * mh["W"]
        assert sil[0] is None                                 # headroom above the hat / hair is empty
        assert P.silhouette(spec, i) == sil                   # cached in build/live2d
    L = P.layout_at(spec, spec.shots[0], 1.0, [])
    g = L["hosts"][0]
    corner = [g["body"][0], g["body"][1], g["body"][0] + 20, g["body"][1] + 20]          # top-left of the box: the hat's tip is in the middle
    assert P.covers(g, corner, None) and not P.covers(g, corner, P.silhouette(spec, 0))     # the box says yes, the outline no


def test_credit_lines_skip_the_sample_notice_for_own_models(tmp_path, monkeypatch):
    from promo.shots.livestream import credit_lines
    reg = tmp_path / "live2d-models.yaml"
    monkeypatch.setenv("PROMO_LIVE2D_MODELS", str(reg))
    _fake_model(tmp_path / "mychar")
    L2.add_model(str(tmp_path / "mychar"), "mine", "Mine", "own art", "https://me.example", "own", credit="Art: me", measure=False)
    raw = _raw()
    raw["podcast"]["hosts"] = [dict(id="a", model="mine", name="Mine")]
    notice, models = credit_lines(_spec(tmp_path, raw))
    assert notice is None and models == [("Mine", "Art: me")]
    notice, models = credit_lines(_spec(tmp_path))
    assert notice and [m for m, _ in models] == ["Niziiro Mao (PRO)", "Hiyori Momose (PRO)"]


def test_measured_anchors_are_written_as_plain_numbers(tmp_path, monkeypatch):
    """Anchors measured from renders are numpy floats; the registry must still be plain YAML (a real-rig run hit this)."""
    reg = tmp_path / "live2d-models.yaml"
    monkeypatch.setenv("PROMO_LIVE2D_MODELS", str(reg))
    _fake_model(tmp_path / "mychar")
    monkeypatch.setattr(L2, "measure_anchors", lambda mid: (dict(top=np.float64(0.07), head_top=0.08, chin=np.float64(0.23), chest=0.34, cx=0.5,
                                                                 mouth=[0.5, np.float64(0.22)], half_w=np.float64(0.12)), dict(eyes_y=np.float64(0.18))))
    rep = L2.add_model(str(tmp_path / "mychar"), "mine", "Mine", "own art", "https://me.example", "own")
    assert rep["anchors"]["top"] == 0.07 and type(rep["anchors"]["top"]) is float
    assert yaml.safe_load(reg.read_text())["models"]["mine"]["anchors"]["half_w"] == 0.12
