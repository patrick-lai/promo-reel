"""Style presets, beat grid, anime-opening gates, claim tables, lock (plain asserts; `python tests/test_styles.py` or pytest)."""
import copy
import fcntl
import json
import os
import subprocess
import sys
import tempfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
EXAMPLE = os.path.join(ROOT, "projects", "commission-ai-hero", "promo.yaml")

from promo import claims as C  # noqa: E402
from promo import style_check, styles  # noqa: E402
from promo.spec import Spec, SpecError, expand_env, load_spec  # noqa: E402

BPM = 177.0
B = 60 / BPM


def grid_json(n_beats=64, markers=None):
    beats = [dict(i=i, t=round(i * B, 4), downbeat=i % 4 == 0) for i in range(n_beats)]
    bars = [dict(bar=k + 1, t=round(4 * k * B, 4), phrase_start=k % 8 == 1) for k in range(n_beats // 4)]
    return dict(tempo_bpm=BPM, beat_s=B, time_signature="4/4", beats=beats, bars=bars,
                markers=markers or dict(intro_hit=round(4 * B, 4), peak=round(16 * B, 4)), duration_s=n_beats * B)


def anime_project(shots, claims=None, qa=None, style=None):
    d = tempfile.mkdtemp()
    json.dump(grid_json(), open(os.path.join(d, "grid.json"), "w"))
    open(os.path.join(d, "assets.yaml"), "w").write(yaml.safe_dump(dict(assets=[dict(
        id="music", kind="music", path="m.wav", licence="Pixabay Content License", source_url="https://example.org/t")])))
    os.makedirs(os.path.join(d, "footage"))
    open(os.path.join(d, "footage", "manifest.yaml"), "w").write("clips: []\n")
    beats = shots[-1]["beats"][1]
    raw = dict(project=dict(name="t"), output=dict(name="t", resolution=1080, fps=30, duration=round(round(beats * B * 30) / 30, 5)),
               style=dict(preset="anime-opening", **(style or {})), timeline=dict(grid="grid.json", beats=beats),
               music=dict(asset="music", track_beat=B, track_offset=0, edit=dict(segments=[[0, 0, beats]])),
               shots=shots, qa=qa or {})
    if claims:
        raw["claims"] = claims
    p = os.path.join(d, "promo.yaml")
    open(p, "w").write(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True))
    return p


def ph(sid, beats, ui=True, **kw):
    return dict(id=sid, beats=beats, type="anime", ui=ui, placeholder=dict(id=f"shot-{sid}", label="x"), **kw)


GOOD = [ph("01", [0, 4], ui=False, cards=[dict(row="title", text="commission-ai", bars=[0, 1])], fx_in=[dict(kind="flash", frames=3), dict(kind="speed_lines", frames=6)]),
        ph("02", [4, 10], ui=True, cards=[dict(row="title", text="ONE ASK.", bars=[0, 1])], fx_in=dict(kind="flash", frames=3)),
        ph("03", [10, 12], ui=False),                       # text-free half-bar shot: cuts at 10 (half bar) next to it are fine
        ph("04", [12, 16], ui=True, cards=[dict(row="title", text="MERGED.", bars=[0, 1])]),
        ph("05", [16, 24], ui=True, cards=[dict(row="title", text_from="claims.landed", bars=[0, 2])], fx_in=dict(kind="flash", frames=3))]
CLAIMS = dict(legible=dict(shot11_legible=dict(cards=None, landed=None, logos=None)),
              tables=dict(landed=dict(selector="shot11_legible", rows=[       # Marketing 4 Oct: matches '8 in this run · 8 landed'
                  dict(cards=8, landed=8, text="8 TASKS · ALL LANDED"), dict(landed=8, text="ALL LANDED."),
                  dict(text="LANDED.", confirm="Marketing")])))


def gates(p):
    return {g: (st, msg) for g, st, msg in style_check.run(load_spec(p))}


def status(p, gate):
    return gates(p)[gate][0]


# ---------------------------------------------------------------- presets
def test_presets_have_rules():
    assert set(styles.names()) >= {"hero", "anime-opening", "livestream"}
    for name, p in styles.PRESETS.items():
        for k in ("description", "pacing", "typography", "transitions", "checks", "qa"):
            assert k in p, (name, k)
        assert "caption" in p or "band" in p, name
    a = styles.PRESETS["anime-opening"]
    assert a["pacing"]["ui_min_bars"] == 1 and a["pacing"]["textfree_min_bars"] == 0.5 and a["pacing"]["card_min_bars"] == 1
    assert {"bar-cuts", "card-ui-clear", "fx-between", "claims"} <= set(a["checks"])


def test_resolve_merges_overrides_and_rejects_unknown():
    st = styles.resolve(dict(style=dict(preset="anime-opening", band=dict(y0=780))))
    assert st["band"]["y0"] == 780 and st["band"]["y1"] == 1076 and st["preset"] == "anime-opening"
    assert st["band"]["rows"]["title"]["size"] == round(0.44 * 300)          # rows re-flow with an explicit y0 too
    assert styles.resolve(dict(style=dict(font=dict(path="x"))))["preset"] is None      # legacy specs untouched
    raw = yaml.safe_load(open(EXAMPLE))
    raw["style"]["preset"] = "vaporwave"
    try:
        Spec(EXAMPLE, expand_env(raw))
    except SpecError as e:
        assert "unknown style preset" in str(e)
    else:
        raise AssertionError("unknown preset accepted")


def test_hero_example_unchanged():
    spec = load_spec(EXAMPLE)
    assert spec.style["preset"] is None and spec.grid is None
    assert style_check.run(spec) == []
    assert spec.qa == (spec.raw.get("qa") or {})


# ---------------------------------------------------------------- grid
def test_beat_grid():
    g = styles.BeatGrid(grid_json())
    assert g.bpm == BPM and g.beats_per_bar == 4 and g.offset == 0
    assert g.is_bar(8) and not g.is_bar(6) and g.is_bar(6, 0.5) and not g.is_bar(5, 0.5)
    assert g.snap(17.63) == 52 and g.max_drift() < 1e-4
    assert g.table()[1]["markers"] == ["intro_hit"]


def test_spec_bars_and_grid_tempo():
    p = anime_project(copy.deepcopy(GOOD), claims=CLAIMS)
    raw = yaml.safe_load(open(p))
    raw["shots"][0] = dict(raw["shots"][0], bars=[0, 1])
    del raw["shots"][0]["beats"]
    spec = Spec(p, expand_env(raw))
    assert spec.shots[0].b1 == 4 and abs(spec.timeline.B - B) < 1e-12
    raw["timeline"]["bpm"] = 120
    try:
        Spec(p, expand_env(raw))
    except SpecError as e:
        assert "grid tempo" in str(e)
    else:
        raise AssertionError("bpm/grid mismatch accepted")


# ---------------------------------------------------------------- anime gates
def test_good_anime_spec_passes():
    g = gates(anime_project(copy.deepcopy(GOOD), claims=CLAIMS, qa=dict(cut_markers=["intro_hit", "peak"])))
    for k, (st, msg) in g.items():
        assert st in ("PASS", "WARN"), (k, msg)
    assert g["placeholders"][0] == "WARN" and g["claims"][0] == "WARN"           # uncaptured evidence -> fallback, reported


def _variant(fn, **kw):
    shots = copy.deepcopy(GOOD)
    fn(shots)
    return anime_project(shots, claims=kw.get("claims", CLAIMS), qa=kw.get("qa"))


def test_cut_off_bar_fails_and_half_bar_needs_text_free():
    def off(s):                     # UI | UI cut at beat 6 (half bar, no text-free neighbour)
        s[0]["beats"] = [0, 6]
        s[1]["beats"] = [6, 10]
        s[0]["ui"] = True
    assert status(_variant(off), "bar-cuts") == "FAIL"

    def quarter(s):
        s[2]["beats"] = [10, 11]
        s[3]["beats"] = [11, 16]
    assert status(_variant(quarter), "bar-cuts") == "FAIL"


def test_card_must_start_on_bar():
    def f(s):
        s[1]["cards"][0]["bars"] = [0.5, 1.5]
    assert status(_variant(f), "bar-cuts") == "FAIL"


def test_holds():
    def short_ui(s):                # UI shot of half a bar
        s[3]["beats"] = [12, 14]
        s[4]["beats"] = [14, 24]
    assert status(_variant(short_ui), "shot-hold") == "FAIL"

    def short_card(s):
        s[1]["cards"][0]["bars"] = [0, 0.5]
    assert status(_variant(short_card), "card-hold") == "FAIL"

    def no_ui_flag(s):
        del s[1]["ui"]
    assert status(_variant(no_ui_flag), "shot-hold") == "FAIL"


def test_one_fixed_band():
    def moved(s):
        s[1]["cards"][0]["cy"] = 300
    assert status(_variant(moved), "card-band") == "FAIL"

    def overlay(s):
        s[1]["overlays"] = [dict(type="text", text="hi", cy=300, size=80)]
    assert status(_variant(overlay), "card-band") == "FAIL"


def test_band_is_a_preset_parameter():
    """A4: the caption band is one preset parameter (frac of the frame height, rows placed relative to it). The default
    anime band is 15% (162 px at 1080p); every card stays inside it and its cap height stays >= band.min_cap_px."""
    st = styles.resolve(dict(style=dict(preset="anime-opening")))
    b = st["band"]
    assert b["y0"] == 918 and 1080 - b["y0"] == 162 and b["y1"] <= 1080
    assert b["y0"] < b["rows"]["title"]["cy"] < b["rows"]["sub"]["cy"] < b["y1"]
    g = gates(_variant(lambda s: None))
    assert g["card-band"][0] == "PASS" and "162 px = 15%" in g["card-band"][1], g["card-band"]
    p = anime_project(copy.deepcopy(GOOD), claims=CLAIMS, style=dict(band=dict(frac=0.2)))
    assert load_spec(p).style["band"]["y0"] == 864 and status(p, "card-band") == "PASS"
    tiny = anime_project(copy.deepcopy(GOOD), claims=CLAIMS, style=dict(band=dict(frac=0.04)))     # 43 px band
    g = gates(tiny)
    assert g["card-band"][0] == "FAIL" and "cap height" in g["card-band"][1], g["card-band"]
    from promo.shots.anime import card_geometry
    sp = load_spec(_variant(lambda s: None))
    for row, text in (("title", "REVIEWED, WITH THE REASON WHY."), ("sub", "Your AI dev crew, on your Mac."), ("tag", "macOS alpha")):
        f = card_geometry(sp, row, text)["font"]
        assert f.getbbox("H")[3] - f.getbbox("H")[1] >= 18, row


def test_move_cut_retimes_one_slot_and_keeps_comments():
    """03-slot swap helper: `promo move-cut <beat> <new>` moves one cut, edits only the two beats lines, refuses unsafe moves."""
    from promo import retime
    p = _variant(lambda s: None)
    txt = open(p).read().replace("- id: '02'", "# keep me\n- id: '02'")
    open(p, "w").write(txt)
    raw = yaml.safe_load(open(p))
    r = retime.move_cut(p, raw, 10, 8)
    assert r["ok"] and r["shots"] == {"02": [4, 8], "03": [8, 12]}, r
    raw2 = yaml.safe_load(open(p))
    assert [s_["beats"] for s_ in raw2["shots"]][:3] == [[0, 4], [4, 8], [8, 12]]
    assert "# keep me" in open(p).read()
    assert status(p, "bar-cuts") == "PASS"
    for bad in ((8, 6), (8, 30), (9, 8)):                 # card would outrun a half-bar shot / outside / no cut at 9
        try:
            retime.move_cut(p, yaml.safe_load(open(p)), *bad)
            raise AssertionError(f"move {bad} should be refused")
        except retime.RetimeError:
            pass


def test_card_never_covers_ui_text():
    def full_ui(s):                 # full-bleed UI shot with a card and no ui_text rects
        s[1]["layout"] = "full"
    assert status(_variant(full_ui), "card-ui-clear") == "FAIL"

    def full_ui_rect(s):            # text in the lower third of the frame -> under the band card
        s[1]["layout"] = "full"
        s[1]["ui_text"] = [[0.30, 0.88, 0.70, 0.95]]
    g = gates(_variant(full_ui_rect))
    assert g["card-ui-clear"][0] == "FAIL" and "covers ui_text" in g["card-ui-clear"][1]

    def full_ui_clear(s):           # text only at the top: fine
        s[1]["layout"] = "full"
        s[1]["ui_text"] = [[0.70, 0.00, 1.00, 0.18]]
    assert status(_variant(full_ui_clear), "card-ui-clear") == "PASS"


def test_fx_only_between_shots():
    def inside(s):
        s[1]["flash"] = dict(at=1.0)
    assert status(_variant(inside), "fx-between") == "FAIL"

    def long_fx(s):
        s[1]["fx_in"] = dict(kind="speed_lines", frames=20)
    assert status(_variant(long_fx), "fx-between") == "FAIL"

    def full_on_ui(s):
        s[1]["fx_in"] = dict(kind="speed_lines", frames=6, area="full")
    assert status(_variant(full_on_ui), "fx-between") == "FAIL"


def test_flash_rate():
    def many(s):                    # flashes at 0, 1.36, ... plus tails: put 4 inside one second with tiny text-free shots
        s[2:3] = [ph("03a", [10, 11], ui=False, fx_in=dict(kind="flash")), ph("03b", [11, 12], ui=False, fx_in=dict(kind="flash"), fx_out=dict(kind="flash"))]
        s[1]["fx_out"] = dict(kind="flash")
    assert status(_variant(many), "flash-rate") == "FAIL"


def test_markers_must_land_on_cuts():
    p = _variant(lambda s: None, qa=dict(cut_markers=["intro_hit", "peak"]))
    assert status(p, "markers") == "PASS"
    p = _variant(lambda s: s[3].update(beats=[12, 20]) or s[4].update(beats=[20, 24]), qa=dict(cut_markers=["peak"]))
    assert status(p, "markers") == "FAIL"


def test_literal_numbers_need_evidence():
    def lit(s):
        s[1]["cards"][0]["text"] = "8 TASKS."
    assert status(_variant(lit), "claims") == "FAIL"

    def ev(s):
        s[1]["cards"][0].update(text="8 TASKS.", evidence="shot-10-dpr2: 'eight checkout tickets', '0 / 8 tasks done'")
    assert status(_variant(ev), "claims") in ("PASS", "WARN")


# ---------------------------------------------------------------- claims
def test_claim_selector_marketing_fallbacks():
    rows = CLAIMS["tables"]["landed"]["rows"]
    assert C.select(rows, dict(cards=8, landed=8, logos=None))["text"] == "8 TASKS · ALL LANDED"
    assert C.select(rows, dict(cards=8, landed=8, logos=3))["text"] == "8 TASKS · ALL LANDED"   # logos never add '3 AGENTS'
    assert C.select(rows, dict(cards=None, landed=8))["text"] == "ALL LANDED."
    assert C.select(rows, dict(cards=8, landed=7))["text"] == "LANDED."        # not all landed: no 'ALL', no number
    assert C.select(rows, dict(cards=None, landed=None, logos=None))["text"] == "LANDED."   # not captured: no number at all
    raw = dict(claims=copy.deepcopy(CLAIMS))
    raw["claims"]["legible"]["shot11_legible"] = dict(cards=8, landed=8, logos=None)
    assert C.text_of(raw, dict(text_from="claims.landed")) == "8 TASKS · ALL LANDED"


def test_claim_audit():
    bad = copy.deepcopy(CLAIMS)
    bad["tables"]["landed"]["rows"][1] = dict(landed=8, text="9 TASKS · ALL LANDED")          # 9 not backed by a condition
    assert any(s == "FAIL" for s, _ in C.audit(dict(claims=bad)))
    nofb = copy.deepcopy(CLAIMS)
    nofb["tables"]["landed"]["rows"] = nofb["tables"]["landed"]["rows"][:-1]
    assert any(s == "FAIL" for s, _ in C.audit(dict(claims=nofb)))
    d = tempfile.mkdtemp()
    md = os.path.join(d, "manifest.md")
    open(md, "w").write("### Shot 10\nfoo\n\n### Shot 11 (board landed)\n- **Legible:** 8 task cards, 8 landed, 3 agent logos\n")
    mc = C.manifest_counts(md, "Shot 11")
    assert mc["cards"] == 8 and mc["landed"] == 8 and mc["logos"] == 3, mc
    assert C.manifest_counts(md, "Shot 12") is None
    cl = copy.deepcopy(CLAIMS)
    cl["tables"]["landed"]["evidence"] = dict(manifest=md, section="Shot 11")
    cl["legible"]["shot11_legible"] = dict(cards=7, landed=8, logos=None)
    assert any(s == "FAIL" and "disagrees" in m for s, m in C.audit(dict(claims=cl)))
    cl["legible"]["shot11_legible"] = dict(cards=8, landed=8, logos=None)
    assert not any(s == "FAIL" for s, _ in C.audit(dict(claims=cl)))


def test_claim_all_landed_and_agents_need_their_counts():
    """Marketing 4 Oct: the shot-15 card reads '8 TASKS · ALL LANDED' (word for word with the header '8 landed'), and
    '3 AGENTS' stays off a crop that shows no logos. 'ALL LANDED' needs a `landed` condition equal to `cards`; a digit
    such as the 3 of '3 AGENTS' needs its own legible-count condition."""
    def fails(rows):
        cl = copy.deepcopy(CLAIMS)
        cl["tables"]["landed"]["rows"] = rows + [dict(text="LANDED.")]
        return [m for s, m in C.audit(dict(claims=cl)) if s == "FAIL"]
    assert not fails([dict(cards=8, landed=8, text="8 TASKS · ALL LANDED")])
    assert any("claims all landed" in m for m in fails([dict(cards=8, text="8 TASKS · ALL LANDED")]))
    assert any("not all landed" in m for m in fails([dict(cards=8, landed=7, text="8 TASKS · ALL LANDED")]))
    assert any("[3]" in m for m in fails([dict(cards=8, landed=8, text="8 TASKS · 3 AGENTS · ALL LANDED")]))
    assert not fails([dict(cards=8, landed=8, logos=3, text="8 TASKS · 3 AGENTS · ALL LANDED")])
    raw = dict(claims=copy.deepcopy(CLAIMS))
    raw["claims"]["tables"]["landed"]["rows"].insert(0, dict(cards=8, landed=8, logos=3, text="8 TASKS · 3 AGENTS · ALL LANDED"))
    raw["claims"]["legible"]["shot11_legible"] = dict(cards=8, landed=8, logos=None)       # crop shows no logo count
    assert C.text_of(raw, dict(text_from="claims.landed")) == "8 TASKS · ALL LANDED"


def test_claim_evidence_full_heading_and_board_header_count():
    """Several takes of one shot: a full heading picks the right section (and its ')' ends the name), and a board header
    count ('8 in this run · 8 landed') is read as the card + landed counts, so a small-text take is never the evidence by accident."""
    d = tempfile.mkdtemp()
    md = os.path.join(d, "manifest.md")
    open(md, "w").write("### Shot 11 (all 8 cards)\n- all 8 cards, 3 agent logos (tiny)\n\n"
                        "### Shot 11 (header counts)\n- Header reads '8 in this run · 8 landed'\n\n### Shot 110\n- 9 cards\n")
    assert C.manifest_counts(md, "Shot 11 (header counts)") == {"cards": 8, "landed": 8}
    assert C.manifest_counts(md, "Shot 11 (all 8 cards)")["logos"] == 3
    assert C.manifest_counts(md, "Shot 11")["logos"] == 3            # bare name = first matching heading
    assert C.manifest_counts(md, "Shot 110") == {"cards": 9}
    assert C.manifest_counts(md, "Shot 1") is None                   # 'Shot 1' never matches 'Shot 11' / 'Shot 110'
    cl = copy.deepcopy(CLAIMS)
    cl["tables"]["landed"]["evidence"] = dict(manifest=md, section="Shot 11 (header counts)")
    cl["legible"]["shot11_legible"] = dict(cards=8, landed=8, logos=None)
    au = C.audit(dict(claims=cl))
    assert not any(s in ("FAIL", "WARN") for s, _ in au), au
    assert C.text_of(dict(claims=cl), dict(text_from="claims.landed")) == "8 TASKS · ALL LANDED"


# ---------------------------------------------------------------- renderer: cards in the band, fx never over UI
def _frames(p, sid, idx):
    from promo import render as R
    from promo.render import RenderContext
    from promo.shots import get_type
    spec = load_spec(p)
    shot = spec.shot(sid)
    got = {}
    orig = R.run_shot
    R.run_shot = lambda ctx, s, f: got.update({i: f(i, i / ctx.fps).convert("RGB") for i in idx})
    try:
        get_type("anime").render(RenderContext.from_spec(spec), shot)
    finally:
        R.run_shot = orig
    return spec, got


def test_render_ui_shot_fx_stays_in_band():
    import numpy as np
    shots = copy.deepcopy(GOOD)
    shots[1]["fx_in"] = [dict(kind="flash", frames=3), dict(kind="speed_lines", frames=6)]
    spec, fr = _frames(anime_project(shots, claims=CLAIMS), "02", [0, 10])
    y0 = spec.style["band"]["y0"]
    a, b = np.asarray(fr[0]), np.asarray(fr[10])
    assert (a[:y0 - 2] == b[:y0 - 2]).all(), "fx touched the footage viewport of a UI shot"
    assert (a[y0 + 10:] != b[y0 + 10:]).any(), "no fx drawn in the band"


def test_render_text_free_flash_is_full_frame_and_cards_in_band():
    import numpy as np
    spec, fr = _frames(anime_project(copy.deepcopy(GOOD), claims=CLAIMS), "01", [0, 20])
    a, b = np.asarray(fr[0]).astype(int), np.asarray(fr[20]).astype(int)
    assert a[:400].mean() > b[:400].mean() + 30                     # flash brightens the whole frame at the cut
    band = spec.style["band"]
    diff = np.abs(np.asarray(fr[20]).astype(int) - np.asarray(_frames(anime_project([dict(GOOD[0], cards=[])] + copy.deepcopy(GOOD[1:]), claims=CLAIMS), "01", [20])[1][20]).astype(int)).sum(2)
    ys, xs = np.nonzero(diff > 30)
    assert ys.min() >= band["y0"] - 2 and ys.max() <= band["y1"] + 2, (ys.min(), ys.max())   # the card only draws inside the band


# ---------------------------------------------------------------- scaffold + lock
def test_new_style_anime_scaffold_loads():
    d = tempfile.mkdtemp()
    dest = os.path.join(d, "p")
    env = dict(os.environ, PROMO_MUSIC_GRID=os.path.join(d, "grid.json"))
    json.dump(grid_json(), open(env["PROMO_MUSIC_GRID"], "w"))
    r = subprocess.run([sys.executable, "-m", "promo", "new", "x", "--dir", dest, "--style", "anime-opening"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    old = os.environ.get("PROMO_MUSIC_GRID")
    os.environ["PROMO_MUSIC_GRID"] = env["PROMO_MUSIC_GRID"]
    try:
        spec = load_spec(os.path.join(dest, "promo.yaml"))
    finally:
        if old is None:
            del os.environ["PROMO_MUSIC_GRID"]
        else:
            os.environ["PROMO_MUSIC_GRID"] = old
    assert spec.style["preset"] == "anime-opening" and spec.grid and spec.shots[0].type == "anime"
    assert spec.total_frames() == round(spec.duration * spec.fps)
    r = subprocess.run([sys.executable, "-m", "promo", "new", "y", "--dir", os.path.join(d, "q"), "--style", "nope"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode != 0


def test_heavy_lock_reentrant_and_exclusive():
    from promo import lock
    p = os.path.join(tempfile.mkdtemp(), "cargo.lock")
    os.environ["PROMO_HEAVY_LOCK"] = p
    try:
        with lock.heavy_lock("t", log=lambda *a: None):
            assert lock.held()
            with lock.heavy_lock("nested", log=lambda *a: None):
                assert lock.held()
            fd = os.open(p, os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                raise AssertionError("lock not exclusive")
            except BlockingIOError:
                pass
            finally:
                os.close(fd)
        assert not lock.held()
    finally:
        del os.environ["PROMO_HEAVY_LOCK"]


def test_heavy_commands_take_the_lock():
    from promo import cli, lock
    seen = []
    orig = cli._dispatch_heavy
    cli._dispatch_heavy = lambda spec, args, c: seen.append((c, lock.held())) or (None, None, 0)
    p = os.path.join(tempfile.mkdtemp(), "cargo.lock")
    os.environ["PROMO_HEAVY_LOCK"] = p
    try:
        args = cli.build_parser().parse_args(["-p", EXAMPLE, "build"])
        args.force = False
        cli.dispatch(load_spec(EXAMPLE), args)
    finally:
        cli._dispatch_heavy = orig
        del os.environ["PROMO_HEAVY_LOCK"]
    assert seen == [("build", True)]



# ---------------------------------------------------------------- anime project: S03 (the ask), Marketing copy v9
ANIME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "projects", "commission-ai-anime", "promo.yaml")
SCRIPT = "/workspace/promo/marketing/scripts-3-directions-v1.md"


def test_anime_s03_ask_cards_match_marketing_copy():
    """Marketing Lead (4 Oct, anime v10, Zen v9 condition): 'ONE ASK.' 4.07-8.14 s from the first UI frame while the ask
    types, 'TONIGHT.' 8.14-12.20 s from the first bar after 'tonight' starts typing, to the cut; 3 bars each, in the band;
    the script record carries the same windows."""
    from promo.shots.anime import card_times
    spec = load_spec(ANIME)
    s03 = next(s for s in spec.shots if s.id == "03")
    got = [(c["text"], round(s03.t0 + card_times(spec, s03, c)[0], 2), round(s03.t0 + card_times(spec, s03, c)[1], 2))
           for c in s03.cfg["cards"]]
    assert got == [("ONE ASK.", 4.07, 8.14), ("TONIGHT.", 8.14, 12.2)], got
    assert [c["bars"] for c in s03.cfg["cards"]] == [[0, 3], [3, 6]]
    assert all(c["row"] == "title" for c in s03.cfg["cards"])
    if os.path.exists(SCRIPT):
        row = next(ln for ln in open(SCRIPT, encoding="utf-8") if ln.startswith("| The ask |"))
        assert '"ONE ASK." 4.07–8.14' in row and '"TONIGHT." 8.14–12.20' in row, row


def test_anime_s03_typing_never_faster_than_captured_and_holds_short():
    """Zen A7: no 4 s still stretch. Every S03 segment plays at <= the captured speed (keystrokes at exactly 1x), the
    segments tile the source without gaps, and each slowed (still) segment adds at most ~1 s on screen."""
    spec = load_spec(ANIME)
    s03 = next(s for s in spec.shots if s.id == "03")
    segs = s03.cfg["segs"]
    for a, b in zip(segs, segs[1:]):
        assert abs(float(a["t_out"]) - float(b["t_in"])) < 1e-6, (a, b)          # continuous source, nothing skipped
    for g in segs:
        src = float(g["t_out"]) - float(g["t_in"])
        assert src <= float(g["dur"]) + 1e-6, g                                   # never faster than captured
        if src < float(g["dur"]) - 1e-6:
            assert float(g["dur"]) <= 1.10 + 1e-6, g                              # a still moment, ~1 s at most
    keys = [g for g in segs if abs(float(g["t_out"]) - float(g["t_in"]) - float(g["dur"])) < 1e-6]
    assert sum(float(g["dur"]) for g in keys) >= 5.1                              # the typing itself is real time
    assert abs(sum(float(g["dur"]) for g in segs) - s03.dur) < 0.01

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
