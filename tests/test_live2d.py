"""Live2D renderer + livestream layout tests (plain asserts; `python tests/test_live2d.py` or pytest).

The render test needs `promo live2d fetch` (Cubism Core + models), node + live2d/node_modules and a Chromium; it is
skipped when any of those are missing. Everything else is pure Python.
"""
import copy
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DEMO = os.path.join(ROOT, "projects", "live2d-demo", "promo.yaml")

from promo import live2d as L2  # noqa: E402
from promo import livestream as LS  # noqa: E402
from promo.spec import Spec, expand_env  # noqa: E402


def _speechy(sr=24000, dur=4.0, seed=0):
    """Syllable-like bursts: 80-250 ms voiced tones with noise, 60-300 ms gaps."""
    rng = np.random.default_rng(seed)
    y = np.zeros(int(sr * dur), np.float32)
    t = 0.3
    while t < dur - 0.4:
        n = int(rng.uniform(0.08, 0.25) * sr)
        a = int(t * sr)
        k = np.arange(n) / sr
        env = np.sin(np.pi * np.arange(n) / n) ** 0.5
        y[a:a + n] += (0.3 * np.sin(2 * np.pi * rng.uniform(120, 220) * k) + 0.05 * rng.normal(size=n)) * env
        t += n / sr + rng.uniform(0.06, 0.3)
    return y, sr


def test_lip_track_zero_lag():
    for seed in range(3):
        y, sr = _speechy(seed=seed)
        n = int(len(y) / sr * 30)
        lt = L2.lip_track(y, sr, 30, n)
        lag = L2.lip_lag(lt["open"], y, sr, 30)
        assert abs(lag["frames"]) <= 0.5, lag            # well under a frame
        assert lag["peak"] > 0.6, lag
        assert lt["open"].min() >= 0 and lt["open"].max() <= 1
        assert lt["open"][:5].max() == 0                  # silent lead-in: mouth shut


def test_lip_lag_detects_late_mouth():
    y, sr = _speechy(seed=4)
    n = int(len(y) / sr * 30)
    m = L2.lip_track(y, sr, 30, n)["open"]
    late = np.concatenate([np.zeros(3), m[:-3]])          # 3 frames late
    assert 2.5 <= L2.lip_lag(late, y, sr, 30)["frames"] <= 3.5


def test_idle_tracks_deterministic_and_blink():
    a = L2.idle_tracks(300, 30, seed=7)
    b = L2.idle_tracks(300, 30, seed=7)
    c = L2.idle_tracks(300, 30, seed=8)
    assert all(np.array_equal(a[k], b[k]) for k in a)
    assert not np.array_equal(a["ParamAngleX"], c["ParamAngleX"])
    assert a["ParamEyeLOpen"].min() == 0.0                # at least one full blink in 10 s
    assert abs(a["ParamAngleX"]).max() < 12               # small sway only


def test_collaboration_characters_refused():
    try:
        L2.model_entry("natori")
    except L2.Live2DError as e:
        assert "Collaboration" in str(e)
    else:
        raise AssertionError("collaboration character accepted")
    reg = L2.registry()
    for k, m in reg["models"].items():
        if m.get("character_type") == "original":
            assert m["sha256"] and m["fetch_url"].startswith("https://cubism.live2d.com/"), k
    assert reg["runtime"]["fetch_url"].startswith("https://cubism.live2d.com/")
    assert "copyrighted by Live2D Inc." in reg["notice"]["short"]


def _spec(mut=None):
    raw = expand_env(yaml.safe_load(open(DEMO)))
    raw = copy.deepcopy(raw)
    if mut:
        mut(raw)
    return Spec(DEMO, raw)


def _gates(spec):
    return {g: (st, msg) for g, st, msg in LS.check(spec)}


def test_livestream_demo_passes():
    g = _gates(_spec())
    assert all(st == "PASS" for st, _ in g.values()), g


MOVE = {"beat": 9, "dur": 0.9}                              # the 01 -> 02 cut (4.5 s); the demo itself has no move


def _with_move(r):
    r["livestream"]["move"] = dict(MOVE)


def test_livestream_gates_fail():
    cases = {
        "livestream-screen": lambda r: r["livestream"].__setitem__("screen", {"w": 1280}),             # 44 % of the frame
        "livestream-chat": lambda r: r["livestream"]["chat"].__setitem__("max_lines", 5),
    }
    for gate, mut in cases.items():
        assert _gates(_spec(mut))[gate][0] == "FAIL", gate
    assert _gates(_spec(_with_move))["livestream-side"][0] == "PASS"

    def instant(r):
        r["livestream"]["move"] = dict(MOVE, dur=0.0)
    assert "instant flip" in _gates(_spec(instant))["livestream-side"][1]

    def second(r):
        _with_move(r)
        r["livestream"]["moves"] = [{"beat": 15, "dur": 0.6}]
    assert "at most one" in _gates(_spec(second))["livestream-side"][1]

    def off_beat_change(r):
        r["livestream"]["move"] = dict(MOVE, beat=5)      # not a shot boundary
    assert _gates(_spec(off_beat_change))["livestream-side"][0] == "FAIL"

    def shot_flip(r):
        r["shots"][1]["hosts_side"] = "right"              # per-shot switch = instant flip
    assert "flips the hosts instantly" in _gates(_spec(shot_flip))["livestream-side"][1]

    def ok_right(r):
        r["livestream"]["hosts_side"] = "right"
    assert _gates(_spec(ok_right))["livestream-side"][0] == "PASS"


def test_chat_truth():
    def viewers(r):                                         # invented audience handles
        r["livestream"]["chat"]["lines"] += [{"t": 2.0, "user": "devon", "text": "just got here"}]
    g = _gates(_spec(viewers))["livestream-chat-truth"]
    assert g[0] == "FAIL" and "devon" in g[1], g

    def labelled(r):
        viewers(r)
        r["livestream"]["chat"]["scripted_label"] = "scripted chat"
    assert _gates(_spec(labelled))["livestream-chat-truth"][0] == "PASS"

    def by_id(r):                                           # host id or name (any case) counts as a host aside
        r["livestream"]["chat"]["lines"] = [{"t": 1, "user": "a", "text": "x"}, {"t": 2, "user": "MAO", "text": "y"}]
    assert _gates(_spec(by_id))["livestream-chat-truth"][0] == "PASS"
    users = {ln["user"] for ln in _spec().raw["livestream"]["chat"]["lines"]}
    assert users <= {"Hiyori", "Mao"}, users


def test_lint_live_and_viewer_counts():
    bad = {
        "tag LIVE": lambda r: r["livestream"].__setitem__("tag", "LIVE"),
        "title live": lambda r: r["livestream"].__setitem__("title", "We're live: ep. 1"),
        "viewer count": lambda r: r["livestream"].__setitem__("title", "1.2k watching"),
        "chat count": lambda r: r["livestream"]["chat"]["lines"].append({"t": 3, "user": "Mao", "text": "3,400 viewers!"}),
        "overlay": lambda r: r["shots"][0].__setitem__("overlays", [{"type": "pill", "text": "LIVE NOW", "cx": 900, "cy": 900, "t": [0, 3]}]),
    }
    for name, mut in bad.items():
        assert _gates(_spec(mut))["livestream-lint"][0] == "FAIL", name
    ok = lambda r: r["livestream"].__setitem__("title", "Live2D hosts, episode 1 (4 screens)")   # 'Live2D' is not 'LIVE'
    assert _gates(_spec(ok))["livestream-lint"][0] == "PASS"
    assert _spec().raw["livestream"]["tag"] == "EP 1"


def test_credit_gate():
    def no_card(r):
        r["shots"] = r["shots"][:2]
    g = _gates(_spec(no_card))["livestream-licence"]
    assert g[0] == "FAIL" and "end-card credit" in g[1], g

    def short(r):                                           # 1.5 s card - 0.25 s fade = 1.25 s at full opacity
        r["shots"][1]["beats"] = [9, 17]
        r["shots"][2]["beats"] = [17, 20]
    assert _gates(_spec(short))["livestream-licence"][0] == "FAIL"

    def tiny(r):
        r["shots"][2]["size"] = 14
    assert _gates(_spec(tiny))["livestream-licence"][0] == "FAIL"
    s = _spec()
    c = LS.credit_shots(s)[0]
    assert LS.credit_hold(c) >= 2.0 and float(c.get("size", 30)) >= 28
    from promo.shots.livestream import credit_lines
    notice, models = credit_lines(s)
    assert notice == L2.registry()["notice"]["long"] and [m for m, _ in models] == ["Hiyori Momose (PRO)", "Niziiro Mao (PRO)"]
    assert all(cr for _, cr in models)


def test_slot_gap():
    s = _spec()
    hs = LS.layout_at(s, 0.0)["hosts"]
    hl = LS.host_layout(LS.cfg(s))
    gap = hs[1][1] - hs[0][3]
    assert gap >= 16 and gap >= -hl["tops"][1] + LS.BREAK_MARGIN - 1, (hs, hl["tops"])  # >= slot_gap, fits Mao's hat
    assert hs[1][3] == LS.HOSTS_BOTTOM and LS.host_size(LS.cfg(s))[1] == hs[0][3] - hs[0][1]
    no_hat = _spec(lambda r: r["livestream"]["hosts"].__setitem__(1, dict(r["livestream"]["hosts"][1], model="hiyori")))
    hn = LS.layout_at(no_hat, 0.0)["hosts"]
    assert round(hn[1][1] - hn[0][3]) == 16                                    # no break-out: plain slot_gap
    wide = _spec(lambda r: r["livestream"].__setitem__("slot_gap", 70))
    hw = LS.layout_at(wide, 0.0)["hosts"]
    assert round(hw[1][1] - hw[0][3]) == 70 and _gates(wide)["livestream-side"][0] == "PASS"
    assert _gates(_spec(lambda r: r["livestream"].__setitem__("slot_gap", 4)))["livestream-side"][0] == "FAIL"


def test_layout_geometry_and_off_edge_move():
    s = _spec()
    assert not LS.moves(LS.cfg(s))                          # no slide by default
    L = LS.layout_at(s, 0.0)
    sc = L["screen"]
    assert (sc[2] - sc[0]) * (sc[3] - sc[1]) >= 0.55 * 1920 * 1080
    for h in L["hosts"]:
        assert h[2] <= sc[0], (h, sc)                       # hosts left of the screen
    assert LS.layout_at(s, s.duration - 0.01)["hosts"] == L["hosts"]
    m = _spec(_with_move)
    t0, d = m.timeline.t(MOVE["beat"]), MOVE["dur"]
    R_ = LS.layout_at(m, m.duration - 0.01)
    for h in R_["hosts"]:
        assert h[0] >= R_["screen"][2], (h, R_["screen"])  # after the single move: right of the screen
    for f in range(int(d * 30) + 1):                        # every frame of the move: hosts never overlap the screen
        Lm = LS.layout_at(m, t0 + f / 30)
        for h in Lm["hosts"] + [Lm["header"]]:
            assert not LS.overlap(h, Lm["screen"]), (f, h, Lm["screen"])
    mid = LS.layout_at(m, t0 + d / 2)                       # screen crossing: hosts fully off the frame edge
    assert all(h[2] <= 0 or h[0] >= 1920 for h in mid["hosts"]), mid["hosts"]


def test_keep_clear_outline_debug_only():
    from promo.render import RenderContext
    from promo.shots import livestream as SL
    s = _spec()
    src = open(SL.__file__).read()
    assert 'os.environ.get("PROMO_DEBUG") == "1"' in src and "show_keep_clear" not in src
    assert "show_keep_clear" not in s.raw["livestream"]
    from promo.cli import shot_digest  # noqa: F401  (digest includes the debug flag, so debug segments never get reused)
    old = os.environ.pop("PROMO_DEBUG", None)
    try:
        d0 = shot_digest(s, s.shots[0])
        os.environ["PROMO_DEBUG"] = "1"
        assert shot_digest(s, s.shots[0]) != d0
    finally:
        os.environ.pop("PROMO_DEBUG", None)
        if old is not None:
            os.environ["PROMO_DEBUG"] = old


def test_heavy_lock_reentrant_and_exclusive():
    import fcntl
    from promo import lock as LK
    d = tempfile.mkdtemp()
    path = os.path.join(d, "cargo.lock")
    os.environ["PROMO_HEAVY_LOCK"] = path
    try:
        assert LK.lock_path() == path
        with LK.heavy_lock("outer", log=lambda *a: None):
            with LK.heavy_lock("inner", log=lambda *a: None):     # nested: must not deadlock
                assert LK.held()
            fd = os.open(path, os.O_RDWR)
            try:                                                 # another open file description cannot take it
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                raise AssertionError("lock not held")
            except BlockingIOError:
                pass
            finally:
                os.close(fd)
        assert not LK.held()
        # a holder in another process makes us wait (and log) until it releases
        p = subprocess.Popen(["flock", path, "sleep", "1.5"])
        import time
        time.sleep(0.3)
        logs, t = [], time.time()
        with LK.heavy_lock("waiter", log=logs.append):
            waited = time.time() - t
        p.wait()
        assert waited >= 0.8 and any("waiting for" in m for m in logs) and any("acquired" in m for m in logs), (waited, logs)
    finally:
        os.environ.pop("PROMO_HEAVY_LOCK", None)
        shutil.rmtree(d)
    assert LK.DEFAULT == "/tmp/commission-ai-cargo.lock" and not hasattr(L2, "LOCK")   # old live2d-only lock is gone


def test_credits_card_text_and_centring():
    from promo.render import RenderContext
    from promo.shots import livestream as SL
    assert SL.LICENCE_LINE == "Live2D sample models used under the Live2D Free Material License Agreement (Original Characters)."
    src = open(SL.__file__).read()
    assert "wrap(notice, fb, body, lh) + wrap(LICENCE_LINE, fb, body, lh)" in src     # own line, same font/size/colour
    s = _spec()
    ctx = RenderContext.from_spec(s)
    notice, models = SL.credit_lines(s)
    a = np.asarray(SL.credits_card(ctx, notice, models, 30).convert("L")).astype(int)
    bg = np.asarray(SL.stream_bg(ctx).convert("L")).astype(int)
    ys, xs = np.nonzero(np.abs(a - bg) > 30)
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    assert abs(cx - ctx.OW / 2) <= 3 and abs(cy - ctx.OH / 2) <= 3, (cx, cy)     # block centred both ways
    rows = sorted(set(ys))                                                      # every text line centred on its own
    lines, start = [], rows[0]
    for p_, q in zip(rows, rows[1:] + [10 ** 9]):
        if q - p_ > 3:
            lines.append((start, p_))
            start = q
    for y0, y1 in lines:
        lx = xs[(ys >= y0) & (ys <= y1)]
        assert abs((lx.min() + lx.max()) / 2 - ctx.OW / 2) <= 4, (y0, lx.min(), lx.max())


def test_framing_anchors_same_rule():
    s = _spec()
    c = LS.cfg(s)
    hl = LS.host_layout(c)
    hh = hl["h"]
    fr = {h["model"]: L2.framing(dict(L2.model_entry(h["model"]), id=h["model"]), hh + hl["pads"][i], hl["frames"][i])
          for i, h in enumerate(c["hosts"])}
    a, b = fr["hiyori"], fr["mao"]
    assert abs(a["head_top_px"] - b["head_top_px"]) < 0.5 and abs(a["head_px"] - b["head_px"]) < 0.5
    for f in fr.values():
        assert 0.9 * hh <= f["chest_px"] <= 1.05 * hh, f      # crop at mid-chest: not floating, not cut at the face
        assert f["has_top"] and f["top_layer_px"] >= 0, f     # full silhouette inside the layer: never clipped at the top
    assert b["top_px"] < 0 <= a["top_px"] < 0.15 * hh         # Mao's hat breaks out above her panel; little air over Hiyori
    assert "frame" not in L2.registry()["models"]["hiyori"] and "zoom" not in str(L2.registry()["models"]["mao"].get("anchors"))
    assert _gates(s)["livestream-framing"][0] == "PASS"
    bad = _spec(lambda r: r["livestream"]["hosts"][1].__setitem__("frame", {"head_frac": 0.6}))
    assert _gates(bad)["livestream-framing"][0] == "FAIL"


def test_breakout_never_clipped_or_overlapping():
    s = _spec()
    L = LS.layout_at(s, 0.0)
    bo = L["breakouts"][1]
    assert L["breakouts"][0] is None and bo and bo[3] == L["hosts"][1][1]    # only Mao's hat leaves her panel
    for other in (L["header"], L["screen"], L["chat"], L["hosts"][0]) + tuple(k["box"] for k in L["keep_clear"]):
        assert not LS.overlap(bo, other), (bo, other)
    assert L["layers"][1][1] <= bo[1]                                      # the layer has room for the whole hat

    def clipped(r):                                                         # no headroom: hat cut by the layer top
        r["livestream"]["hosts"][1]["frame"] = {"pad_top": 0}
    g = _gates(_spec(clipped))["livestream-framing"]
    assert g[0] == "FAIL" and "clipped at the top" in g[1], g

    real = LS.host_layout                                                   # a fixed 16 px gap (no nudge): the hat
                                                                            # would reach into Hiyori's panel
    def fixed_gap(c):
        hl = dict(real(c))
        hl["y0s"] = [hl["y0s"][0], hl["y0s"][0] + hl["h"] + 16]
        return hl
    LS.host_layout = fixed_gap
    try:
        g = _gates(_spec())["livestream-framing"]
    finally:
        LS.host_layout = real
    assert g[0] == "FAIL" and "overlaps the host a panel" in g[1], g

    swapped = _spec(lambda r: r["livestream"].__setitem__("hosts", r["livestream"]["hosts"][::-1]))
    Ls = LS.layout_at(swapped, 0.0)                                         # Mao on top: first panel moves down
    assert Ls["breakouts"][0] and not LS.overlap(Ls["breakouts"][0], Ls["header"])
    assert _gates(swapped)["livestream-framing"][0] == "PASS"

    orig = L2.model_entry

    def strip_top(name):
        m = orig(name)
        return dict(m, anchors={k: v for k, v in m["anchors"].items() if k != "top"}) if name == "hiyori" else m
    L2.model_entry = strip_top
    LS._HL_CACHE.clear()
    try:
        g = _gates(_spec())["livestream-framing"]
    finally:
        L2.model_entry = orig
        LS._HL_CACHE.clear()
    assert g[0] == "FAIL" and "no `top` anchor" in g[1], g


def test_hosts_render_same_head_height_and_scale():
    """Rendered pixels (model-agnostic): eye line height and eye span of both hosts in their layers within 5 %, and the
    full silhouette (incl. Mao's hat) starts below the layer top, i.e. is never clipped."""
    if not _render_ready():
        print("skip test_hosts_render_same_head_height_and_scale (needs `promo live2d fetch` + node)")
        return
    c = LS.cfg(_spec())
    hl = LS.host_layout(c)
    m = {}
    for i, h in enumerate(c["hosts"]):
        name, W, H, ov = h["model"], hl["w"], hl["h"] + hl["pads"][i], hl["frames"][i]
        r = L2.probe_face(name, W, H, frame=ov)
        e = r["eyes"]["box"]
        alpha_rows = np.nonzero(r["frame0"][..., 3].max(1) > 8)[0]
        m[name] = dict(eye_y=(e[1] + e[3]) / 2, span=e[2] - e[0], mouth=r["mouth"]["y"], top=int(alpha_rows[0]),
                       probe=L2.mouth_probe_at(L2.resolve_model(name), W, H, r["info"]["width"] / r["info"]["height"], ov)[1] * H)
    h, o = m["hiyori"], m["mao"]
    assert abs(h["eye_y"] - o["eye_y"]) <= 0.05 * max(h["eye_y"], o["eye_y"]), m      # head at the same height
    assert abs(h["span"] - o["span"]) <= 0.05 * max(h["span"], o["span"]), m          # same visible scale
    for v in m.values():
        assert abs(v["mouth"] - v["probe"]) <= 0.02 * hl["h"], m                      # anchors land where predicted
        assert v["top"] >= 2, m                                                       # silhouette not clipped at the top
    assert o["top"] < hl["pads"][1], m                                                # the hat really breaks out
    print("framing:", m)


def _render_ready():
    try:
        L2.resolve_model("hiyori")
    except L2.Live2DError:
        return False
    return shutil.which("node") and os.path.isdir(os.path.join(L2.L2D_DIR, "node_modules", "pixi-live2d-display"))


def test_render_deterministic():
    if not _render_ready():
        print("skip test_render_deterministic (run `promo live2d fetch` + npm install in live2d/)")
        return
    y, sr = _speechy(dur=1.0, seed=2)
    d = tempfile.mkdtemp()
    import soundfile as sf
    wav = os.path.join(d, "v.wav")
    sf.write(wav, y, sr)
    hashes = []
    for k in range(2):
        out = os.path.join(d, f"r{k}.mov")
        rep = L2.render_host("hiyori", out, wav=wav, duration=0.5, width=160, height=200, seed=3, warmup=5, log=lambda *a: None)
        assert rep["frames"] == 15 and rep["mouth_offset_frames"] == 0
        raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", out, "-f", "rawvideo", "-pix_fmt", "rgba", "-"])
        assert len(raw) == 15 * 160 * 200 * 4
        hashes.append(hashlib.sha256(raw).hexdigest())
    assert hashes[0] == hashes[1], hashes
    shutil.rmtree(d)


TALK = os.path.join(ROOT, "projects", "commission-ai-talkshow", "promo.yaml")


def test_measure_text_rows():
    g = np.zeros((100, 200), int)
    g[40:43, 20:30] = 200                        # ascender stub (thin)
    g[43:51, 10:180] = 200                       # x-height body (heavy) -> baseline row 50
    g[51:54, 50:60] = 200                        # descender (thin)
    g[38, :] = 0
    g[:, 5] = 255                                # a 1-px vertical rule must not count as ink
    assert LS.measure_text_rows(g, 0, 200, 41, 50) == (40, 50)


def test_text_size_gate_needs_footage_and_size():
    def mut(r):
        r["shots"][0]["text_check"] = {"box": [237, 247], "src_px": 1080, "min_px": 24}
        r["shots"][0]["screen"] = {"source": "no-such-clip"}
    rows = LS.text_size_rows(_spec(mut), LS.cfg(_spec(mut)))
    assert rows and rows[0][0] == "livestream-text-size" and rows[0][1] == "FAIL", rows
    assert LS.text_size_rows(_spec(), LS.cfg(_spec())) == []            # no text_check -> no gate row


def _no_chat(r):
    r["livestream"].pop("chat", None)


def test_no_chat_layout_full_height_screen():
    """No chat lines -> no chat strip: the app screen takes the full height (minus margins); gates allow 0 lines."""
    sp = _spec(_no_chat)
    c = LS.cfg(sp)
    assert not LS.has_chat(c)
    w, h = LS.screen_size(c)
    assert h == LS.FRAME_H - 2 * float(c.get("margin", 24)) and w == float((c.get("screen") or {}).get("w", 1440))
    L = LS.layout_at(sp, 1.0)
    assert L["chat"] is None and L["screen"][3] - L["screen"][1] == h
    g = _gates(sp)
    assert g["livestream-chat"][0] == "PASS" and "no chat strip" in g["livestream-chat"][1]
    assert all(st == "PASS" for st, _ in g.values()), g
    assert LS.screen_size(LS.cfg(_spec()))[1] == LS.screen_size(LS.cfg(_spec()))[0] * 9 / 16   # with chat: 16:9


def test_element_px_scale_and_crop():
    """Named-element size = ink rows inside its box x effective scale (output px / source px); `inside` needs the
    whole box in the cam crop; a crop taller than the source shrinks to full height (as render.frame_cam)."""
    g = np.zeros((1080, 1920), int)
    g[500:518, 800:900] = 220                                    # an 18-px 'label'
    fr = (g, 1920, 1080)
    m = LS.element_px(None, 0, (0.5, 0.5, 0.75), (1440, 1032), [790, 495, 910, 525], 1080, frame=fr)
    assert m["src"] == 18 and abs(m["scale"] - 1.0) < 1e-9 and m["inside"] and m["px"] == 18
    m = LS.element_px(None, 0, (0.5, 0.5, 0.5), (1440, 1032), [790, 495, 910, 525], 1080, frame=fr)
    assert abs(m["scale"] - 1.5) < 1e-9 and m["px"] == 27            # 1.5x on 1080 footage = upscale
    m = LS.element_px(None, 0, (0.1, 0.5, 0.3), (1440, 1032), [790, 495, 910, 525], 1080, frame=fr)
    assert m is None or not m["inside"]                              # element outside the crop
    m = LS.element_px(None, 0, (0.5, 0.5, 0.25), (1440, 1032), [395, 247, 455, 262], 540, frame=fr)
    assert m["src"] == 18                                            # box given at src_px 540 scales x2
    x0, y0, bw, bh = LS.cam_crop((0.5, 0.5, 1.0), 1920, 1080, (1440, 1032))
    assert bh == 1080 and abs(bw - 1080 * 1440 / 1032) < 1e-6


def test_named_gate_fail_and_upscale_warn():
    import promo.livestream as LSM
    tmp = tempfile.NamedTemporaryFile(suffix=".mov", delete=False)
    tmp.close()
    g = np.zeros((1080, 1920), int)
    g[500:516, 800:900] = 220                                    # 16 src px
    orig = LSM._gray_frame
    LSM._gray_frame = lambda path, t: (g, 1920, 1080)

    def mut(cam, min_px=18):
        def f(r):
            _no_chat(r)
            r["shots"][0]["screen"] = {"source": "x", "cam": cam}
            r["shots"][0]["named"] = [{"name": "label", "box": [790, 495, 910, 525], "src_px": 1080, "min_px": min_px}]
        return f
    try:
        rows = {}
        for cam, want, up in [((0.5, 0.5, 0.75), "FAIL", "PASS"), ((0.5, 0.5, 0.6), "PASS", "WARN")]:
            sp = _spec(mut(cam))
            sp.footage_path = lambda cid: tmp.name
            rows = {k: (st, msg) for k, st, msg in LS.named_rows(sp, LS.cfg(sp))}
            assert rows["livestream-named"][0] == want, rows
            assert rows["named-upscale"][0] == up, rows
        assert "x1.25" in rows["named-upscale"][1] and "20.0 px" in rows["livestream-named"][1]
        sp = _spec(mut((0.5, 0.5, 0.75)))                         # footage missing -> FAIL
        rows = {k: (st, msg) for k, st, msg in LS.named_rows(sp, LS.cfg(sp))}
        assert rows["livestream-named"][0] == "FAIL"
    finally:
        LSM._gray_frame = orig
        os.unlink(tmp.name)


def test_credit_gate_accepts_split_cards():
    """Credits split over two cards (part 1 notice + licence line, part 2 models): both needed, each >= 2 s / 28 px."""
    def split(r, second=True):
        r["timeline"]["beats"] = 25
        r["shots"][2]["part"] = 1
        if second:
            r["shots"].append({"id": "04", "beats": [20, 25], "type": "live2d_credits", "size": 30, "part": 2})
        else:
            r["shots"][2]["beats"] = [15, 25]
    g = _gates(_spec(split))["livestream-licence"]
    assert g[0] == "PASS" and "03" in g[1] and "04" in g[1], g
    g = _gates(_spec(lambda r: split(r, False)))["livestream-licence"]
    assert g[0] == "FAIL" and "part 2 missing" in g[1], g
    from promo.render import RenderContext
    from promo.shots import livestream as SL
    ctx = RenderContext.from_spec(_spec())
    notice, models = SL.credit_lines(ctx.spec)
    ims = [np.asarray(SL.credits_card(ctx, notice, models, part=p))[..., :3].astype(int) for p in (None, 1, 2)]
    ink = [int((im.max(2) > 150).sum()) for im in ims]
    assert ink[1] < ink[0] and ink[2] < ink[0] and ink[1] > 0 and ink[2] > 0


def test_talkshow_time_of_day_dissolve_source():
    """09b dissolve: on only when the take changes time of day; the manifest field wins over the plan profile."""
    import importlib.util
    mp = os.path.join(ROOT, "projects", "commission-ai-talkshow", "make_spec.py")
    if not os.path.exists(mp):
        return
    spec_ = importlib.util.spec_from_file_location("talk_make_spec_tod", mp)
    MS = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(MS)
    orig, orig_md = MS.manifest_entry, MS.manifest_md_tod
    try:
        MS.manifest_md_tod = lambda cid: None
        MS.manifest_entry = lambda cid: {}
        assert MS.tod_change("c", {"time_of_day": {"from": "dusk", "to": "day", "at": 5.5}})[:3] == (5.5, "dusk", "day")
        assert MS.tod_change("c", {}) is None
        MS.manifest_entry = lambda cid: {"time_of_day": "dusk"}                  # dusk retake: constant -> no dissolve
        assert MS.tod_change("c", {"time_of_day": {"from": "dusk", "to": "day", "at": 5.5}}) is None
        MS.manifest_entry = lambda cid: {"time_of_day": "dusk -> night @ 3.25"}
        assert MS.tod_change("c", {})[:4] == (3.25, "dusk", "night", "manifest")
        MS.manifest_entry = lambda cid: {}
        MS.manifest_md_tod = lambda cid: "dusk"                                  # recorded in manifest.md only
        assert MS.tod_change("c", {"time_of_day": {"from": "dusk", "to": "day", "at": 5.5}}) is None
    finally:
        MS.manifest_entry, MS.manifest_md_tod = orig, orig_md
    d = tempfile.mkdtemp()
    try:                                                                         # manifest.md parsing (row + section)
        open(os.path.join(d, "manifest.yaml"), "w").write("clips: []\n")
        open(os.path.join(d, "manifest.md"), "w").write("| shot-x | 1 | time of day: dusk -> day @ 5.50 |\n\n## shot-y retake\n"
                                                        "Notes. Time of day: dusk\n")
        old = MS.FOOTAGE
        MS.FOOTAGE = os.path.join(d, "manifest.yaml")
        assert MS.manifest_md_tod("shot-x") == "dusk -> day @ 5.50" and MS.manifest_md_tod("shot-y") == "dusk"
        assert MS.manifest_md_tod("shot-z") is None
        MS.FOOTAGE = old
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_host_track_from_vo_lines():
    import soundfile as sf
    from promo.shots import livestream as SL
    d = tempfile.mkdtemp()
    try:
        y, sr = _speechy(dur=1.0)
        sf.write(os.path.join(d, "a.wav"), y, sr)
        def mut(r):
            r["paths"]["build"] = d
            r["vo"] = {"engine": "files", "lines": [
                {"id": "l1", "shot": "01", "at": 2.0, "host": "HIYORI", "text": "x", "file": os.path.join(d, "a.wav")},
                {"id": "l2", "shot": "02", "at": 0.5, "host": "Mao", "text": "y", "file": os.path.join(d, "a.wav")}]}
        sp = _spec(mut)
        import promo.vo as VO
        orig = VO.line_file
        VO.line_file = lambda spec, line, man=None: line["file"]
        try:
            hiy = SL.host_track(sp, {"id": "a", "name": "Hiyori", "model": "hiyori"})
            mao = SL.host_track(sp, {"id": "b", "name": "Mao", "model": "mao"})
            none = SL.host_track(sp, {"id": "c", "name": "Nobody", "model": "x"})
        finally:
            VO.line_file = orig
        assert none is None
        a, r = sf.read(hiy)
        b, _ = sf.read(mao)
        assert r == sr and len(a) == int(round(sp.duration * sr)) + 1
        assert np.abs(a[: int(1.9 * sr)]).max() == 0 and np.abs(a[int(2.0 * sr): int(3.0 * sr)]).max() > 0.1
        t_mao = sp.g("02", 0.5)
        assert np.abs(b[: int((t_mao - 0.05) * sr)]).max() == 0 and np.abs(b[int(t_mao * sr): int((t_mao + 1) * sr)]).max() > 0.1
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_screen_card_texts_are_linted():
    def mut(r):
        r["shots"][0]["screen"] = {"card": {"title": "Building in Public", "subtitle": "LIVE now"}}
    g = _gates(_spec(mut))
    assert g["livestream-lint"][0] == "FAIL", g["livestream-lint"]
    from promo.render import RenderContext
    from promo.shots import livestream as SL
    ctx = RenderContext.from_spec(_spec())
    im = SL.screen_card(ctx, 720, 405, {"title": "T", "subtitle": "S", "lines": ["a", "b"]})
    assert im.size == (720, 405) and np.asarray(im)[..., :3].max() > 200


def test_talkshow_spec_gates():
    if not os.path.exists(TALK):
        return
    from promo.spec import load_spec
    try:
        sp = load_spec(TALK)
    except Exception as e:  # noqa: BLE001  (VO folder not on this machine)
        print("skip talkshow:", e)
        return
    g = _gates(sp)
    for k in ("livestream-lint", "livestream-chat-truth", "livestream-licence", "livestream-framing", "livestream-keep-clear", "livestream-screen",
              "livestream-side", "livestream-chat", "livestream-text-size"):
        if k in g:
            assert g[k][0] == "PASS", (k, g[k])
    c = LS.cfg(sp)
    assert c["hosts_side"] == "left" and not c.get("move") and c["tag"] == "EP 1"
    assert sp.shots[-1].type == "live2d_credits"
    assert not LS.has_chat(c) and LS.screen_size(c) == (1440.0, 1032.0)   # asides cut: no strip, full-height screen
    assert [s.get("part") for s in LS.credit_shots(sp)] == [1, 2]         # two credit cards
    named = [s for s in sp.shots if s.cfg.get("named")]
    assert {s.id for s in named} >= {"02", "04", "05", "06a", "06b", "07"}
    if "livestream-named" in g:                                           # only the beat-4 Cursor badge may miss 18 px
        bad = [m for m in g["livestream-named"][1].split("; ") if "NOT fully" in m or
               (float(m.split("= ")[1].split(" px")[0]) < float(m.split("(min ")[1].split(")")[0]))]
        assert all("badge" in m for m in bad), bad
    srcs = [(s.cfg.get("screen") or {}).get("source") for s in sp.shots]
    assert all(not x or "/" not in x for x in srcs)              # clip ids, never paths


def test_vo_files_engine_pins_sha():
    """Talk-show VO is pre-rendered: the files engine checks every WAV's sha256 and writes vo.json (skips off-box)."""
    if not os.path.exists(TALK):
        return
    from promo import vo as VO
    raw = expand_env(yaml.safe_load(open(TALK)))
    p0 = os.path.join(expand_env("${TALKSHOW_VO_DIR:-/workspace/videos/commission-ai-promo/talkshow}"), raw["vo"]["lines"][0]["file"])
    if not os.path.exists(p0):
        return
    d = tempfile.mkdtemp()
    try:
        raw["paths"]["build"] = d
        sp = Spec(TALK, copy.deepcopy(raw))
        meta = VO.run_files(sp)
        assert len(meta) == len(raw["vo"]["lines"]) and all(os.path.isabs(m["file"]) and m["dur"] > 0.5 for m in meta)
        raw["vo"]["lines"][0]["sha256"] = "0" * 64
        try:
            VO.run_files(Spec(TALK, raw))
        except RuntimeError as e:
            assert "sha256 changed" in str(e)
        else:
            raise AssertionError("sha mismatch accepted")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_talkshow_auto_take_follows_text_height():
    """Beat 7: full MAO line when shot 12's 'Approved...' line measures >= min_px, else trimmed at the silence after
    '...tells you why it passes.' (prefix text, short fade). Skips off-box (VO / footage absent)."""
    import importlib.util
    mp = os.path.join(ROOT, "projects", "commission-ai-talkshow", "make_spec.py")
    vo_dir = expand_env("${TALKSHOW_VO_DIR:-/workspace/videos/commission-ai-promo/talkshow}")
    if not (os.path.exists(mp) and os.path.exists(os.path.join(vo_dir, "lines.json"))):
        return
    spec_ = importlib.util.spec_from_file_location("talk_make_spec", mp)
    MS = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(MS)
    plan = yaml.safe_load(open(os.path.join(os.path.dirname(mp), "plan.yaml")))
    seg = next(sg for sg in plan["segments"] if sg.get("fallback_trim"))
    if not MS.clip_path(plan["takes"][seg["take"]]):
        return
    d = MS.build(copy.deepcopy(plan))
    t = d["takes"][0]
    assert t["measured_px"] >= 24 and t["take"] == "full"
    hard = copy.deepcopy(plan)
    hard["profiles"][hard["takes"][seg["take"]]]["text_check"]["min_px"] = 99
    d2 = MS.build(hard)
    assert d2["takes"][0]["take"] == "trimmed"
    ln = next(l for l in d2["vo_lines"] if l["id"] == t["line"])
    assert ln["text"].endswith("tells you why it passes.") and "See?" in ln["script_text"]
    assert 2.5 < ln["trim"]["end"] < 3.5 and d2["total_f"] < d["total_f"]
    import soundfile as sf
    from promo import vo as VO
    full, sr = sf.read(os.path.join(vo_dir, ln["file"]), dtype="float32")
    orig = VO.line_file
    VO.line_file = lambda spec, line, man=None: os.path.join(vo_dir, line["file"])
    try:
        x, _ = VO.line_audio(None, ln)
    finally:
        VO.line_file = orig
    assert len(x) == int(round(ln["trim"]["end"] * sr)) and x[-1] == 0.0      # trimmed, faded to zero
    assert np.abs(full[len(x) - int(0.05 * sr): len(x)]).max() < 0.05          # the cut lands in a silence


def _load_make_spec():
    import importlib.util
    mp = os.path.join(ROOT, "projects", "commission-ai-talkshow", "make_spec.py")
    sp = importlib.util.spec_from_file_location("talk_make_spec2", mp)
    MS = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(MS)
    return MS, os.path.dirname(mp)


def test_talkshow_vo_placeholder_and_superseded_fallback():
    """A line whose re-voiced take has not landed uses the old take (vo/ or vo/superseded/<stem>.v1.wav) as a labelled
    placeholder with the SCRIPT text; the files engine finds a pinned take even after it moves to superseded/."""
    import json as _json

    import soundfile as sf
    MS, here = _load_make_spec()
    d = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(d, "vo", "superseded"))
        script = os.path.join(d, "script.md")
        open(script, "w").write("## Direction 3: test\n\n| # | Time | Screen | Dialogue |\n|---|---|---|---|\n"
                                "| 1 | 0:00 | x | **HIYORI:** New words here! **MAO:** Same words. |\n"
                                "| 8 | 1:26 | x | **HIYORI:** Merged! **MAO:** All eight tasks, three agents, all merged. (Pick by shot 11: "
                                "neither = \"Every one of them, merged.\") |\n\n## Next\n")
        y, sr = _speechy(dur=1.0)
        sf.write(os.path.join(d, "vo", "superseded", "b1l1.v1.wav"), y, sr)        # old take moved aside, new not landed
        sf.write(os.path.join(d, "vo", "b1l2.wav"), y[: sr // 2], sr)
        sf.write(os.path.join(d, "vo", "b8l1.wav"), y, sr)
        sf.write(os.path.join(d, "vo", "b8l2.wav"), y, sr)                          # only the existing beat 8 take
        lines = [dict(beat=1, line=1, host="HIYORI", text="Old words here!", id="beat01_line01", file="vo/b1l1.wav"),
                 dict(beat=1, line=2, host="MAO", text="Same words.", id="beat01_line02", file="vo/b1l2.wav"),
                 dict(beat=8, line=1, host="HIYORI", text="Merged!", id="beat08_line01", file="vo/b8l1.wav"),
                 dict(beat=8, line=2, host="MAO", text="All eight tasks, three agents, all merged.", id="beat08_line02", file="vo/b8l2.wav")]
        _json.dump({"lines": lines}, open(os.path.join(d, "lines.json"), "w"))
        plan = yaml.safe_load(open(os.path.join(here, "plan.yaml")))
        plan["script"] = script
        out, notes, var = MS.resolve_lines(plan, d)
        by = {l["id"]: l for l in out}
        assert var == "all"
        a = by["beat01_line01"]
        assert a["placeholder"] and a["file"] == "vo/superseded/b1l1.v1.wav" and a["text"] == "New words here!"
        assert not by["beat01_line02"]["placeholder"] and abs(by["beat01_line02"]["duration"] - 0.5) < 0.01
        b = by["beat08_line02"]
        assert b["text"] == "Every one of them, merged." and b["placeholder"] and b["file"] == "vo/b8l2.wav"
        plan["shot11_legible"] = {"cards": True, "logos": True}
        assert MS.beat8_variant(plan) == "full"
        plan["shot11_legible"] = {"cards": False, "logos": True}
        assert MS.beat8_variant(plan) == "agents"
        # files engine: pinned take found after a move to superseded/
        from promo import vo as VO
        h = hashlib.sha256(open(os.path.join(d, "vo", "b1l2.wav"), "rb").read()).hexdigest()
        os.rename(os.path.join(d, "vo", "b1l2.wav"), os.path.join(d, "vo", "superseded", "b1l2.v1.wav"))
        sf.write(os.path.join(d, "vo", "b1l2.wav"), y, sr)                          # a new take lands under the old name
        orig = VO.files_dir
        VO.files_dir = lambda spec, man=None: d
        try:
            p = VO.line_file(None, {"file": "vo/b1l2.wav", "sha256": h})
        finally:
            VO.files_dir = orig
        assert p.endswith("superseded/b1l2.v1.wav")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
