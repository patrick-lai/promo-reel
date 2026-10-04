"""critique-pack + named-element gate (plain asserts; `python tests/test_critique.py` or pytest)."""
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from promo import critique as CR  # noqa: E402
from promo import named as N  # noqa: E402
from promo import style_check  # noqa: E402
from promo.spec import load_spec  # noqa: E402
from test_styles import B, CLAIMS, GOOD, anime_project  # noqa: E402

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def text_frame(path, size=24, xy=(400, 300), text="Coding", W=1920, H=1080):
    """A dark UI-like frame with one light text line; returns (path, (top, base)) of the 'C' ink rows."""
    im = Image.new("RGB", (W, H), (24, 24, 28))
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, size)
    d.text(xy, text, font=f, fill=(230, 230, 235))
    im.save(path)
    g = np.asarray(im.convert("L")).astype(int)
    rows = np.nonzero((g > 110).any(1))[0]
    return path, (int(rows[0]), int(rows[-1]))


def still_project(tmp, size=24, cam_w=0.5, named=True, text_xy=(400, 300), extra=None):
    """anime project whose shot 02 is a still with a text line + a `named:` entry for it."""
    png, (top, base) = text_frame(os.path.join(tmp, "ui.png"), size=size, xy=text_xy)
    p = anime_project(GOOD, claims=CLAIMS)
    d = os.path.dirname(p)
    open(os.path.join(d, "footage", "manifest.yaml"), "w").write(yaml.safe_dump(dict(clips=[dict(
        id="ui", path=png, resolution="1920x1080", dpr=1, demo=True)])))
    open(os.path.join(d, "footage", "manifest.md"), "w").write("# footage notes\n")
    raw = yaml.safe_load(open(p))
    s = raw["shots"][1]
    s.pop("placeholder")
    s.update(still="ui", cam=[[0, (text_xy[0] + 60) / 1920, (text_xy[1] + 12) / 1080, cam_w]])
    if named:
        s["named"] = [dict(name="Coding label", box=[text_xy[0] - 4, top - 3, text_xy[0] + 200, base + 3])]
    raw.update(extra or {})
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    return p, base - top + 1


# ---------------------------------------------------------------- named.py
def test_measure_text_rows_cap_height():
    tmp = tempfile.mkdtemp()
    png, (top, base) = text_frame(os.path.join(tmp, "a.png"), size=40, text="CODING")     # caps only: ink = cap height
    g = np.asarray(Image.open(png).convert("L")).astype(int)
    m = N.measure_text_rows(g, 390, 700, top - 5, base + 5)
    assert m == (top, base), (m, top, base)
    f = ImageFont.truetype(FONT, 40)
    cap = f.getbbox("H")[3] - f.getbbox("H")[1]
    assert abs((base - top + 1) - cap) <= 1, (base - top + 1, cap)
    assert N.measure_text_rows(g, 1500, 1600, 900, 950) is None       # no ink


def test_element_px_scale_and_inside():
    g = np.zeros((1080, 1920), int)
    g[500:520, 900:1000] = 255                                        # a 20-row "glyph"
    frame = (g, 1920, 1080)
    m = N.element_px(frame, (0.5, 0.5, 0.5), (1920, 800), [890, 495, 1010, 525])
    assert m["src"] == 20 and abs(m["scale"] - 2.0) < 1e-6 and abs(m["px"] - 40.0) < 1e-6 and m["inside"]
    assert N.element_px(frame, (0.1, 0.1, 0.3), (1920, 800), [890, 495, 1010, 525]) is None   # outside the crop: nothing to read
    m = N.element_px(frame, (0.5, 0.5, 0.05), (1920, 800), [890, 495, 1010, 525])
    assert m is not None and not m["inside"]                          # only partly in the crop
    assert N.MIN_NAMED_PX == 18


def test_named_measures_native_frame_pixels_not_css_or_preview():
    """Regression for the shot-15-prcard question: measurement reads the clip's own full-res frame (no 1024-wide preview,
    no CSS / DPR assumption). A 12-row cap in a 1920x1080 clip is 12 px at 1.0x whatever the manifest DPR says; the same
    glyph in a 3840x2160 clip (box given in a 1080-tall frame via src_px) gives the same output px."""
    tmp = tempfile.mkdtemp()
    out = {}
    for W, H in ((1920, 1080), (3840, 2160)):
        k = W // 1920
        im = Image.new("RGB", (W, H), (40, 40, 46))
        ImageDraw.Draw(im).rectangle([850 * k, 478 * k, 900 * k, 489 * k + k - 1], fill=(120, 160, 230))   # 12-row 'cap'
        png = os.path.join(tmp, f"f{W}.png")
        im.save(png)
        mov = os.path.join(tmp, f"c{W}.mkv")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", png, "-frames:v", "3", "-r", "30", "-c:v", "ffv1", "-pix_fmt", "bgr0",
                        "-threads", "2", mov], check=True)
        g, w, h = N.gray_frame(mov, 0.0)
        assert (w, h) == (W, H) and g.shape == (H, W)                  # native resolution, not a preview
        m = N.element_px((g, w, h), (0.5, 0.5, 1.0), (1920, 1080), [845, 466, 940, 500], src_px=1080)
        out[W] = m
    assert out[1920]["src"] == 12 and abs(out[1920]["scale"] - 1.0) < 1e-9 and abs(out[1920]["px"] - 12.0) < 1e-9
    assert out[3840]["src"] == 24 and abs(out[3840]["scale"] - 0.5) < 1e-9 and abs(out[3840]["px"] - 12.0) < 1e-9
    # 1.3x / 1.5x pushes on the 1080p clip scale linearly (the DPR in the manifest never enters the measurement)
    for w_, want in ((1 / 1.3, 15.6), (1 / 1.5, 18.0)):
        g, w, h = N.gray_frame(os.path.join(tmp, "c1920.mkv"), 0.0)
        m = N.element_px((g, w, h), (0.47, 0.45, w_), (1920, 1080), [845, 466, 940, 500])
        assert abs(m["px"] - want) < 0.05, (w_, m)


# ---------------------------------------------------------------- anime named gate
def _gates(p):
    return {g: (st, msg) for g, st, msg in style_check.run(load_spec(p))}


def test_named_gate_pass_with_upscale_warn():
    p, cap = still_project(tempfile.mkdtemp(), size=24, cam_w=0.5)        # ~18 px cap x2 = ~36 px
    r = _gates(p)
    assert r["named"][0] == "PASS", r["named"]
    assert r["named-upscale"][0] == "WARN" and "x2.00" in r["named-upscale"][1], r["named-upscale"]


def test_named_gate_fails_small_text_and_no_upscale_warn_at_1x():
    p, cap = still_project(tempfile.mkdtemp(), size=14, cam_w=1.0)        # ~10 px cap at x1.0 (band viewport = 1920 wide)
    r = _gates(p)
    assert r["named"][0] == "FAIL" and "min 18" in r["named"][1], r["named"]
    assert r["named-upscale"][0] == "PASS"


def test_named_gate_fails_when_out_of_frame():
    p, cap = still_project(tempfile.mkdtemp(), size=24, cam_w=0.5, text_xy=(1700, 300))
    raw = yaml.safe_load(open(p))
    raw["shots"][1]["cam"] = [[0, 0.2, 0.3, 0.3]]                       # look away from the element
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    r = _gates(p)
    assert r["named"][0] == "FAIL", r["named"]


def test_named_gate_flags_element_hidden_by_caption_band():
    """A4: a named element under the caption band (canvas y >= band.y0) FAILs 'hidden by the caption band'. Full layout:
    the band draws over the footage. Band layout: the viewport ends at y0, so the camera must frame the element above it."""
    p, cap = still_project(tempfile.mkdtemp(), size=24, cam_w=1.0, text_xy=(400, 1000))
    raw = yaml.safe_load(open(p))
    raw["shots"][1].update(layout="full", cam=[[0, 0.5, 0.5, 1.0]], ui_text=[[0.0, 0.0, 0.01, 0.01]])
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    r = _gates(p)
    assert r["named"][0] == "FAIL" and "hidden by the caption band" in r["named"][1], r["named"]
    raw["shots"][1].update(layout="band", cam=[[0, 0.5, 0.9, 1.0]])    # band layout, camera clamps to the bottom: above it
    raw["shots"][1].pop("ui_text")
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    r = _gates(p)
    assert r["named"][0] == "PASS", r["named"]


def test_named_keys_do_not_change_shot_digest():
    from promo import cli
    p, _ = still_project(tempfile.mkdtemp(), named=True)
    s1 = load_spec(p)
    raw = yaml.safe_load(open(p))
    raw["shots"][1].pop("named")
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    s2 = load_spec(p)
    assert cli.shot_digest(s1, s1.shots[1]) == cli.shot_digest(s2, s2.shots[1])


def test_contain_aspect_viewport():
    from promo.shots.anime import viewport
    p, _ = still_project(tempfile.mkdtemp())
    raw = yaml.safe_load(open(p))
    raw["shots"][1].update(fit="contain", aspect=1.6)
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    s = load_spec(p)
    vp = viewport(s, s.shots[1])
    y0 = s.style["band"]["y0"]
    assert abs((vp[2] - vp[0]) - y0 * 1.6) < 1e-6 and vp[3] == y0


def test_timeline_may_end_off_grid_but_cuts_may_not():
    from promo import check
    p, _ = still_project(tempfile.mkdtemp())
    raw = yaml.safe_load(open(p))
    end = 23.7
    raw["shots"][-1]["beats"] = [16, end]
    raw["timeline"]["beats"] = end
    raw["output"]["duration"] = end * B
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    rows = {r["gate"]: r for r in check.run(load_spec(p))["results"]}
    assert "off the beat grid" not in rows["beat-grid"]["msg"] and "ends off-grid at beat 23.7" in rows["beat-grid"]["msg"], rows["beat-grid"]
    raw["shots"][-2]["beats"] = [12, 15.25]
    raw["shots"][-1]["beats"] = [15.25, end]
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    rows = {r["gate"]: r for r in check.run(load_spec(p))["results"]}
    assert "off the beat grid" in rows["beat-grid"]["msg"]


def test_pillar_fill_brand_backdrop():
    from promo.render import RenderContext
    from promo.shots.anime import pillar_backdrop
    p, _ = still_project(tempfile.mkdtemp())
    raw = yaml.safe_load(open(p))
    raw["shots"][1].update(fit="contain", aspect=1.6, pillar_fill="brand")
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    s = load_spec(p)
    ctx = RenderContext.from_spec(s).with_scale(1)
    VX, VW, VH = 320, 1280, 800
    brand = np.asarray(pillar_backdrop(ctx, s, s.shots[1], VX, VW, VH).convert("RGB")).astype(int)
    flat = np.asarray(pillar_backdrop(ctx, s, s.shots[0], VX, VW, VH).convert("RGB")).astype(int)
    assert (flat == flat[0, 0]).all()                                   # default: flat band colour
    assert brand[400, 100, 2] > brand[1060, 100, 2] and brand[400, 100, 2] > 60   # night-sky gradient, bluer up top
    assert brand[:, VX + 20:VX + VW - 20].max() < 200                   # no stars behind the panel
    raw["shots"][1]["pillar_fill"] = "checker"
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    s = load_spec(p)
    try:
        pillar_backdrop(ctx, s, s.shots[1], VX, VW, VH)
        raise AssertionError("unknown pillar_fill accepted")
    except ValueError:
        pass


def test_plan_count_claim_with_confirm_flag():
    from promo import claims as C
    raw = dict(claims=dict(legible=dict(shot11_legible=dict(cards=None, logos=None)), tables=dict(plan_count=dict(
        selector="shot11_legible", rows=[dict(cards=8, text="8 TASKS."), dict(text="THE PLAN.", confirm="Marketing")]))))
    assert C.text_of(raw, dict(text_from="claims.plan_count")) == "THE PLAN."
    res = C.audit(raw)
    assert any(st == "WARN" and "provisional copy: Marketing to confirm" in m for st, m in res), res
    assert not any(st == "FAIL" for st, m in res), res
    for cards, want in ((8, "8 TASKS."), (7, "THE PLAN.")):
        raw["claims"]["legible"]["shot11_legible"]["cards"] = cards
        assert C.text_of(raw, dict(text_from="claims.plan_count")) == want
    raw["claims"]["legible"]["shot11_legible"]["cards"] = 8
    assert not any("provisional" in m for _, m in C.audit(raw))


# ---------------------------------------------------------------- critique pack
def test_kind_and_default_sources():
    p, _ = still_project(tempfile.mkdtemp())
    s = load_spec(p)
    assert CR.kind_of(s) == "anime"
    copy, reviews, fmd = CR.sources(s)
    assert copy == [os.path.abspath(f"{CR.MARKETING}/scripts-3-directions-v1.md")] and reviews == []
    assert any(x.endswith(os.path.join("footage", "manifest.md")) for x in fmd)
    assert CR.DEFAULT_COPY["hero"][0].endswith("captions-v1-cut.md") and CR.DEFAULT_COPY["hero"][1].endswith("vo-script-v1.md")
    assert CR.DEFAULT_REVIEWS["talkshow"] == ["/workspace/commission-ai-routines/ux-review/2026-10-04/talkshow-preview/REVIEW.md"]
    raw = yaml.safe_load(open(p))
    raw["critique"] = dict(kind="talkshow", copy=["copy.md"], reviews=["zen.md"])
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    s = load_spec(p)
    copy, reviews, _ = CR.sources(s)
    assert CR.kind_of(s) == "talkshow" and copy == [os.path.join(s.root, "copy.md")] and reviews == [os.path.join(s.root, "zen.md")]


def test_plan_stills_one_mid_per_shot_and_grouped_cards():
    p, _ = still_project(tempfile.mkdtemp())
    raw = yaml.safe_load(open(p))
    raw["shots"][0]["cards"].append(dict(row="sub", text="Your AI dev crew", bars=[0, 1]))   # shares the title's span
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    s = load_spec(p)
    plan, _ = CR.plan_stills(s)
    mids = [x for x in plan if x[1] == "shot-mid"]
    cards = [x for x in plan if x[1] == "card"]
    assert len(mids) == len(s.shots)
    assert [x[0] for x in cards][0] == "s01-card1" and cards[0][5] == ["commission-ai", "Your AI dev crew"]
    assert len(cards) == 4                                              # 01 (grouped), 02, 04, 05
    assert all(0 <= x[4] < s.total_frames() for x in plan)


def test_brief_has_rubric_rules_and_ask():
    assert [n for n, _ in CR.RUBRIC] == ["hook", "legibility", "story", "pacing", "calm composition", "style fidelity", "polish"]
    p, _ = still_project(tempfile.mkdtemp())
    s = load_spec(p)
    md = CR.brief_md(s, "anime", "/x/t.mp4", [], dict(copy=[("/m/c.md", "copy/c.md")], footage=[], reviews=[("/z/R.md", None)]),
                     dict(failed=False, results=[]), True, False, False, ["/z/R.md"])
    for want in ("truth: PASS / FAIL", "4.2", "18 px", "DPR 2", "No chat asides", "only between shots", "ONE fixed lower-third band",
                 "Street notice", ">= 0.5 s", "Real footage only", "line by line", "Frame check", "MISSING: `/z/R.md`"):
        assert want in md, want


def test_cli_parses_positional_project():
    from promo import cli
    a = cli.build_parser().parse_args(["critique-pack", "projects/x", "--no-check", "--out", "/tmp/o"])
    assert a.cmd == "critique-pack" and a.project_dir == "projects/x" and a.no_check and a.out == "/tmp/o"


def test_pack_end_to_end_on_a_fake_render():
    tmp = tempfile.mkdtemp()
    p, cap = still_project(tmp, size=24, cam_w=0.5)
    s = load_spec(p)
    os.makedirs(s.out, exist_ok=True)
    master = s.output_path("")
    n = s.total_frames()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30", "-frames:v", str(n),
                    "-threads", "2", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", master], check=True)
    json.dump(dict(ok=True, failed=False, results=[dict(gate="assets", status="PASS", msg="fine")]),
              open(os.path.join(s.out, f"{s.name}-{s.tag}-check.json"), "w"))
    raw = yaml.safe_load(open(p))
    copy_md = os.path.join(tmp, "copy.md")
    open(copy_md, "w").write("# copy\n")
    raw["critique"] = dict(copy=[copy_md], reviews=[os.path.join(tmp, "missing-review.md")])
    yaml.safe_dump(raw, open(p, "w"), sort_keys=False)
    s = load_spec(p)
    r = CR.build(s, reuse_check=True, log=lambda *a: None)
    root = r["path"]
    assert root == os.path.join(s.out, "critique-pack")
    for f in ("BRIEF.md", "TEXT-LINES.md", "CHECK.txt", "CHECK.json", "stills/index.json", "copy/copy.md", "stills/s02-mid.png",
              "stills/s02-mid.json", "stills/s01-card1.png", "footage/manifest.md"):
        assert os.path.exists(os.path.join(root, f)), f
    assert not os.path.exists(os.path.join(root, "VO-TRANSCRIPT.md"))       # no VO in this project
    assert r["missing"] == [os.path.join(tmp, "missing-review.md")]
    im = Image.open(os.path.join(root, "stills", "s02-mid.png"))
    assert im.size == (1920, 1080)
    side = json.load(open(os.path.join(root, "stills", "s02-card1.json")))
    assert side["footage"]["clip"] == "ui" and abs(side["footage"]["effective_scale"] - 2.0) < 1e-3 and side["footage"]["upscaled"]
    named = [e for e in side["elements"] if e["kind"] == "named"]
    card = [e for e in side["elements"] if e["kind"] == "card"]
    assert named and named[0]["src"] <= cap and abs(named[0]["cap_px"] - named[0]["src"] * 2.0) < 1e-6   # ascender top -> baseline (no descender)
    assert named[0]["meets_min"] and named[0]["effective_scale"] == 2.0 and named[0]["cap_px"] >= 18
    assert card and card[0]["text"] == "ONE ASK." and card[0]["cap_px"] > 40 and card[0]["this_still"]
    assert "ONE ASK." in open(os.path.join(root, "TEXT-LINES.md")).read()
    assert "PASS  assets" in open(os.path.join(root, "CHECK.txt")).read()
    # rerun wipes and rewrites (no stale files)
    open(os.path.join(root, "stale.txt"), "w").write("x")
    CR.build(s, reuse_check=True, log=lambda *a: None)
    assert not os.path.exists(os.path.join(root, "stale.txt"))


if __name__ == "__main__":
    fails = 0
    for k, v in list(globals().items()):
        if k.startswith("test_") and callable(v):
            try:
                v()
                print("ok  ", k)
            except Exception as e:  # noqa: BLE001
                fails += 1
                import traceback
                traceback.print_exc()
                print("FAIL", k, e)
    sys.exit(1 if fails else 0)
