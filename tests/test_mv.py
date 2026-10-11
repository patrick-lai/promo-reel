"""The anime-mv style: beat grid analysis, lyrics (import, align, layout, gates), the `mv` shot type, its gates, the look bible,
test-only audio, and the generation prompts."""
import json
import os
import subprocess

import numpy as np
import pytest
import soundfile as sf
import yaml
from PIL import Image

from promo import editor as E
from promo import genvideo as G
from promo import lyrics as L
from promo import music as M
from promo import mv as MV
from promo import style_check as SC
from promo.render import RenderContext
from promo.shots import mv as SMV
from promo.spec import load_spec

HIRAGINO = "/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"
needs_jp_font = pytest.mark.skipif(not os.path.exists(HIRAGINO), reason="no Japanese system font here")


# ---------------------------------------------------------------- beat grid
def click_track(path, bpm=120.0, offset=0.30, seconds=24.0, sr=22050):
    """Clicks on every beat from `offset`, a low kick on every 4th (beat 1 of the bar)."""
    y = np.zeros(int(seconds * sr), np.float32)
    B = 60.0 / bpm
    k = 0
    while offset + k * B < seconds - 0.2:
        i = int((offset + k * B) * sr)
        n = int(0.05 * sr)
        t = np.arange(n) / sr
        hi = 0.4 * np.sin(2 * np.pi * 2000 * t) * np.exp(-t * 80)
        y[i:i + n] += hi.astype(np.float32)
        if k % 4 == 0:
            lo = 0.9 * np.sin(2 * np.pi * 60 * t) * np.exp(-t * 25)
            y[i:i + n] += lo.astype(np.float32)
        k += 1
    sf.write(path, y, sr)


def test_analyse_finds_tempo_downbeats_and_excerpt(tmp_path):
    p = str(tmp_path / "click.wav")
    click_track(p, bpm=120.0, offset=0.30)
    g = M.analyse(p, t_from=4.5, t_to=20.0, marks={"chorus": 12.4})
    assert abs(g["tempo_bpm"] - 120.0) < 0.3
    assert g["beat_contrast"] > 1.5
    tr = g["track"]
    assert abs(((tr["offset_s"] - 0.30) / 0.5 + 0.5) % 1 - 0.5) * 0.5 < 0.03         # the grid sits on the clicks
    first_down_t = tr["offset_s"] + tr["first_downbeat"] * tr["beat_s"]
    assert abs(((first_down_t - 0.30) / 2.0 + 0.5) % 1 - 0.5) * 2.0 < 0.05           # beat 1 = the kick
    ex = g["excerpt"]
    assert (ex["track_beat0"] - tr["first_downbeat"]) % 4 == 0 and (ex["track_beat1"] - tr["first_downbeat"]) % 4 == 0
    assert g["bars"][0]["t"] == 0 and g["beats"][0]["downbeat"]
    assert g["music_block"]["edit"]["segments"] == [[0, ex["track_beat0"], ex["track_beat1"]]]
    assert set(g["markers"]) == {"chorus"} and any(abs(b["t"] - g["markers"]["chorus"]) < 1e-6 for b in g["bars"])   # snapped to a bar line


# ---------------------------------------------------------------- lyrics
SRT = """1
00:00:41,000 --> 00:00:43,500
浮つく甘い街の喧騒

2
00:00:44,740 --> 00:00:48,080
故に  感情線は渋滞
"""


def test_parse_srt_lrc_and_text():
    a = L.parse(SRT)
    assert a == [dict(t=[41.0, 43.5], text="浮つく甘い街の喧騒"), dict(t=[44.74, 48.08], text="故に　感情線は渋滞")]
    b = L.parse("[00:41.00]浮つく\n[00:44.74]故に\n")
    assert b[0] == dict(t=[41.0, 44.74], text="浮つく") and b[1]["t"][0] == 44.74
    assert L.parse("一行目\n\n二行目\n") == [dict(t=None, text="一行目"), dict(t=None, text="二行目")]


def test_align_matches_characters_despite_asr_kanji_mistakes():
    lines = [dict(t=[0, 1], text="心模様 白く染まって"), dict(text="だけどどうやったって")]
    words = [dict(w="心も", start=10.0, end=10.4), dict(w="予防", start=10.4, end=10.8), dict(w="しろく", start=10.8, end=11.4),
             dict(w="染まって", start=11.4, end=12.2), dict(w="だけど", start=12.5, end=12.9), dict(w="どうやったって", start=12.9, end=13.9)]
    frac, out = L.align_lines(lines, words)
    assert 0.6 < frac <= 1.0
    assert abs(out[0]["sung"][0] - 10.0) < 0.05 and abs(out[0]["sung"][1] - 12.2) < 0.05
    assert abs(out[1]["sung"][0] - 12.5) < 0.05 and "unsynced" not in out[1]


def test_a_breath_glued_to_the_first_word_is_cut_off():
    """Whisper starts a phrase's first word where the last one ended; the singing starts after the breath (the quiet dip)."""
    sr = 16000
    t = np.arange(int(3.0 * sr)) / sr
    y = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    y[int(1.0 * sr):int(1.6 * sr)] *= 0.003                               # the breath: 1.0-1.6 s, singing again from 1.6 s
    words = [dict(w="喧", start=0.5, end=1.0), dict(w="故", start=1.0, end=1.9), dict(w="に", start=1.9, end=2.1)]
    out = L.refine_starts(words, (y, sr), t0=0.0)
    assert abs(out[1]["start"] - 1.6) < 0.05 and out[0]["start"] == 0.5 and out[2]["start"] == 1.9


@needs_jp_font
def test_vertical_layout_stacks_down_and_uses_vertical_forms():
    line = dict(text="夢、ーまだ", layout="vertical", size=50, tracking=0.1, x=1500, y=200, color=[255, 255, 255], shadow=0)
    pos, box = L.layout(line, HIRAGINO)
    chars = [p[0] for p in pos]
    assert chars[1] == "︑" and pos[2][3] is True                       # 、 -> its vertical form; ー is drawn rotated
    assert all(abs(p[1] - pos[0][1]) < 15 for p in pos)                   # one column
    assert [p[2] for p in pos] == sorted(p[2] for p in pos)               # top to bottom
    assert box[3] > box[1] + 4 * 50


@needs_jp_font
def test_missing_glyph_is_caught():
    assert L.missing_glyphs(HIRAGINO, "心予報、。") == []
    assert L.missing_glyphs(HIRAGINO, "心\U0001D11E") == ["\U0001D11E"]       # a musical symbol Hiragino does not carry


def test_type_on_reveals_characters_in_order():
    line = dict(a=1.0, b=4.0, anim="type", fade_s=0.12)
    before = [L.char_alpha(line, k, 6, 1.2)[0] for k in range(6)]
    later = [L.char_alpha(line, k, 6, 2.6)[0] for k in range(6)]
    assert before[0] > 0 and before[-1] == 0 and all(x == 1 for x in later)
    assert L.char_alpha(line, 0, 6, 4.0)[0] == 0                           # gone at the end
    drop = dict(line, anim="drop")
    assert L.char_alpha(drop, 0, 6, 1.05)[1] > 0.5 and abs(L.char_alpha(drop, 0, 6, 2.0)[1]) < 1e-9     # high above at first, landed later


# ---------------------------------------------------------------- a tiny anime-mv project
def project(tmp_path, shots=None, lyrics=None, extra=None):
    d = tmp_path / "p"
    (d / "footage").mkdir(parents=True)
    (d / "footage" / "manifest.yaml").write_text("clips: []\n")
    (d / "assets.yaml").write_text("assets: []\n")
    grid = dict(tempo_bpm=120, time_signature="4/4", beats=[dict(i=i, t=i * 0.5, downbeat=i % 4 == 0) for i in range(17)],
                bars=[dict(bar=n + 1, t=n * 2.0, phrase_start=n % 4 == 0) for n in range(4)], markers={"chorus": 4.0}, duration_s=8.0)
    (d / "grid.json").write_text(json.dumps(grid))
    raw = dict(project=dict(name="t"), output=dict(name="t", resolution=1080, fps=30, duration=8.0), assets="assets.yaml", footage="footage/manifest.yaml",
               style=dict(preset="anime-mv"), timeline=dict(grid="grid.json", beats=16),
               shots=shots or [dict(id="01", beats=[0, 8], type="mv", fill=[30, 42, 58]), dict(id="02", beats=[8, 16], type="mv", fill=[169, 195, 160])],
               lyrics=lyrics if lyrics is not None else dict(lines=[dict(t=[0.5, 2.0], text="夢を見ていた", sung=[0.55, 1.9]),
                                                                   dict(t=[4.2, 6.0], text="雨上がりの街で")]))
    raw.update(extra or {})
    (d / "promo.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False))
    return d, load_spec(str(d / "promo.yaml"), plugins=False)


def gates(spec):
    return {g: (st, msg) for g, st, msg in SC.mv_gates(spec, spec.style, set())}


@needs_jp_font
def test_mv_gates_pass_on_a_clean_spec(tmp_path):
    _, spec = project(tmp_path)
    g = gates(spec)
    for k in ("mv-shots", "mv-cuts", "mv-hold", "mv-flashes", "mv-plates", "lyrics-glyphs", "lyrics-safe", "lyrics-hold", "lyrics-sync", "test-audio"):
        assert g[k][0] == "PASS", (k, g[k])
    assert g["look-bible"][0] == "WARN"                                   # no bible yet


@needs_jp_font
def test_mv_gates_catch_off_grid_cuts_ui_and_short_lines(tmp_path):
    shots = [dict(id="01", beats=[0, 5.5], type="mv", fill=[0, 0, 0]), dict(id="02", beats=[5.5, 8], type="mv", fill=[0, 0, 0], ui=True),
             dict(id="03", beats=[8, 16], type="clip", source="x")]
    lyr = dict(lines=[dict(t=[0.5, 0.9], text="短い"), dict(t=[1.0, 2.0], text="ずれ", sung=[1.6, 2.0])])
    _, spec = project(tmp_path, shots, lyr)
    g = gates(spec)
    assert g["mv-shots"][0] == "FAIL" and "ui: true" in g["mv-shots"][1] and "type 'clip'" in g["mv-shots"][1]
    assert g["mv-cuts"][0] == "FAIL" and "beat 5.5" in g["mv-cuts"][1]        # a half beat outside a burst
    assert g["lyrics-hold"][0] == "FAIL" and g["lyrics-sync"][0] == "WARN"


def test_half_beat_cuts_are_fine_inside_a_burst_but_flash_storms_are_not(tmp_path):
    shots = [dict(id="01", beats=[0, 4], type="mv", fill=[0, 0, 0], fx_out="flash"), dict(id="02", beats=[4, 5], type="mv", fill=[0, 0, 0], fx_in="flash", fx_out="flash"),
             dict(id="03", beats=[5, 5.5], type="mv", fill=[0, 0, 0], fx_in="whiteout"), dict(id="04", beats=[5.5, 6], type="mv", fill=[0, 0, 0]),
             dict(id="05", beats=[6, 16], type="mv", fill=[0, 0, 0])]
    _, spec = project(tmp_path, shots)
    g = gates(spec)
    assert g["mv-cuts"][0] == "PASS"                                     # 02-04 are a burst of three short shots
    assert g["mv-flashes"][0] == "FAIL" and "4 flashes" in g["mv-flashes"][1]


def test_mv_cuts_need_a_grid(tmp_path):
    d, _ = project(tmp_path)
    raw = yaml.safe_load((d / "promo.yaml").read_text())
    raw["timeline"] = dict(bpm=120, beats=16)
    (d / "promo.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True))
    spec = load_spec(str(d / "promo.yaml"), plugins=False)
    assert gates(spec)["mv-cuts"][0] == "FAIL"


def test_timeline_markers_override_the_grid(tmp_path):
    _, spec = project(tmp_path, extra=dict(timeline=dict(grid="grid.json", beats=16, markers={"chorus": 6.0, "bridge": 2.0})))
    assert spec.grid.markers == {"chorus": 6.0, "bridge": 2.0}


@needs_jp_font
def test_mv_shot_renders_letterbox_lyrics_and_holds_drawings_on_twos(tmp_path):
    d, spec = project(tmp_path)
    ctx = RenderContext.from_spec(spec)
    shot = spec.shots[0]
    shot.cfg["particles"] = {"kind": "petals", "n": 20}
    SMV.MV().render(ctx, shot)
    seg = os.path.join(ctx.seg_dir, "01.mp4")
    out = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.2", "-i", seg, "-frames:v", "1", str(out)], check=True)
    a = np.asarray(Image.open(out).convert("RGB")).astype(int)
    assert np.abs(a[40, 960] - [255, 253, 249]).max() < 8                 # cream page above the picture band
    assert np.abs(a[500, 200] - [30, 42, 58]).max() < 14                   # the plate inside the band
    band = a[985:1040, 700:1220]
    assert (band.sum(axis=2) < 400).sum() > 150                            # dark lyric glyphs in the cream under the picture
    assert SMV.held_time(0, 30, 2) == SMV.held_time(1, 30, 2) < SMV.held_time(2, 30, 2)


def test_a_take_wins_over_the_placeholder_fill(tmp_path):
    d, _ = project(tmp_path)
    Image.new("RGB", (1280, 720), (220, 30, 30)).save(d / "plate.png")
    raw = yaml.safe_load((d / "promo.yaml").read_text())
    raw["shots"][0].update(still="plate.png", cam=[[0, 0.5, 0.5, 1.0]])         # fill [30, 42, 58] stays as the placeholder
    (d / "promo.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False))
    spec = load_spec(str(d / "promo.yaml"), plugins=False)
    ctx = RenderContext.from_spec(spec)
    SMV.MV().render(ctx, spec.shots[0])
    out = tmp_path / "f.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "0.5", "-i", os.path.join(ctx.seg_dir, "01.mp4"), "-frames:v", "1", str(out)], check=True)
    px = np.asarray(Image.open(out).convert("RGB")).astype(int)[500, 960]
    assert px[0] > 180 and px[2] < 80, px


@needs_jp_font
def test_assemble_keeps_only_segments_and_a_small_master(tmp_path):
    """One delivery encode: the master is far smaller than the crf 16 segments it is cut from, and no full-size intermediate stays behind."""
    from promo import assemble
    from promo.mix import master_path
    d, spec = project(tmp_path)
    ctx = RenderContext.from_spec(spec)
    for shot in spec.shots:
        shot.cfg["particles"] = {"kind": "petals", "n": 40}               # moving detail, so the encode has something to compress
        SMV.MV().render(ctx, shot)
    os.makedirs(spec.audio_dir, exist_ok=True)
    sf.write(master_path(spec, "web"), np.zeros((int(48000 * spec.duration), 2), np.float32), 48000)
    out = assemble.run(spec)[0]
    segs = sum(os.path.getsize(spec.seg_path(s.id)) for s in spec.shots)
    assert os.path.getsize(out) < segs / 2
    assert sorted(f for f in os.listdir(spec.segs_dir) if f.endswith(".mp4") and not f[:2].isdigit()) == []


def test_particles_are_deterministic_and_move():
    cfg = {"kind": "petals", "n": 10, "seed": 4}
    a, b = SMV.particle_state(cfg, 1.0, (1920, 818)), SMV.particle_state(cfg, 1.0, (1920, 818))
    c = SMV.particle_state(cfg, 1.5, (1920, 818))
    assert a == b and a != c


def test_cut_effects_keep_the_size_and_whiteout_ends_on_paper():
    pic = Image.new("RGB", (320, 136), (20, 40, 60))
    for k in SMV.FX:
        assert SMV.apply_fx(pic, k, 0.6, (255, 253, 249)).size == pic.size
    full = np.asarray(SMV.apply_fx(pic, "whiteout", 1.0, (255, 253, 249)))
    assert (full == [255, 253, 249]).all()


def test_lyric_edit_rerenders_only_the_shots_it_crosses(tmp_path):
    from promo import cli
    d, spec = project(tmp_path)
    before = [cli.shot_digest(spec, s) for s in spec.shots]
    raw = yaml.safe_load((d / "promo.yaml").read_text())
    raw["lyrics"]["lines"][1]["text"] = "雨のち晴れ"                          # 4.2-6.0 s: shot 02 only
    (d / "promo.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False))
    spec2 = load_spec(str(d / "promo.yaml"), plugins=False)
    after = [cli.shot_digest(spec2, s) for s in spec2.shots]
    assert before[0] == after[0] and before[1] != after[1]


# ---------------------------------------------------------------- look bible, takes, generation prompts
def test_bible_gate_flags_plates_from_an_older_bible(tmp_path):
    d, spec = project(tmp_path, extra=dict(look_bible=dict(prompt="flat cel", cast={"hero": "a girl"})))
    bid = MV.bible_id(MV.bible_of(spec))
    plates = d / "media" / "plates" / "02"
    plates.mkdir(parents=True)
    for n, b in ((1, "oldbible"), (2, bid)):
        f = plates / f"key-t{n}.png"
        Image.new("RGB", (64, 36), (9, 9, 9)).save(f)
        f.with_name(f.name + ".gen.json").write_text(json.dumps(dict(provider="test", kind="image", prompt="p", at="now", sha256="x", bible=b)))
        G.register_existing(spec, str(f), f"k02-t{n}", shots=["02"])
    from promo import footage as FT
    spec = load_spec(str(d / "promo.yaml"), plugins=False)
    assert [t["id"] for t in MV.takes(spec)["02"]] == ["k02-t1", "k02-t2"]
    MV.use(spec, "02", "k02-t1")
    spec = load_spec(str(d / "promo.yaml"), plugins=False)
    _, st, msg = SC.look_bible_gate(spec, FT.load(spec))
    assert st == "WARN" and "k02-t1" in msg and "k02-t2" not in msg       # the take in use predates the bible
    raw = yaml.safe_load((d / "promo.yaml").read_text())
    raw["shots"][1]["plate"] = dict(kind="still", prompt="p")
    (d / "promo.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False))
    spec = load_spec(str(d / "promo.yaml"), plugins=False)
    assert MV.latest(spec) == {"02": "k02-t2"}                           # the newest take of the current bible
    MV.use(spec, "02", "k02-t2")
    spec = load_spec(str(d / "promo.yaml"), plugins=False)
    assert SC.look_bible_gate(spec, FT.load(spec))[1] == "PASS"          # the old take is still registered, but nobody uses it


def test_plate_prompt_is_bible_then_cast_then_scene():
    b = dict(prompt="Flat cel style.", cast={"hero": "A girl in a raincoat.", "spirit": "A cloud."})
    p = MV.plate_prompt(b, dict(prompt="she runs", cast=["hero"]))
    assert p == "Flat cel style. A girl in a raincoat. Scene: she runs"


def test_generation_prompts_with_roles_and_the_illustrated_guard(tmp_path):
    img = G.prompt_for("image", "a girl on a roof", tmp_path / "k.png", 4, "16:9", ref=[("character", "/x/sheet.png"), ("style", "/x/s.png")], guard="illustrated")
    assert "image_edit" in img and "CHARACTER reference" in img and "STYLE reference only" in img and "ORIGINAL illustrated characters" in img
    assert "oatmeal" not in img                                          # no leftover wording from one old project
    vid = G.prompt_for("video", "she blinks", tmp_path / "c.mp4", 6, "16:9", ref=["keyframe=/x/k.png"], guard="illustrated", resolution="720p")
    assert "image_to_video tool on /x/k.png" in vid and "720p" in vid and "unmodified" in vid
    legacy = G.prompt_for("image", "a desk", tmp_path / "d.png", 4, "16:9", people=True, ref="/x/me.png")
    assert "identity AND set reference" in legacy and legacy.startswith("Use your image_edit")


# ---------------------------------------------------------------- test-only audio
def test_test_only_audio_is_watermarked_and_cannot_be_shared(tmp_path):
    from promo import assemble
    from promo import assets as A
    from promo import flow as F
    d, _ = project(tmp_path, extra=dict(music=dict(asset="song", bpm=120, track_beat=0.5, track_offset=0, edit=dict(segments=[[0, 0, 16]]))))
    (d / "assets.yaml").write_text(yaml.safe_dump(dict(assets=[dict(id="song", kind="music", path="song.wav", licence="unlicensed: internal test only",
                                                                     source_url="https://example.com", test_only=True)])))
    spec = load_spec(str(d / "promo.yaml"), plugins=False)
    assert A.test_only_assets(spec) == ["song"]
    assert SC.test_audio_gate(spec)[1] == "WARN"
    with pytest.raises(F.FlowError, match="test-only"):
        F.refuse_test_only(str(d), "share a draft")
    os.makedirs(spec.segs_dir, exist_ok=True)
    vid = os.path.join(spec.segs_dir, "v.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x8899aa:s=1920x1080:d=0.2:r=30", "-pix_fmt", "yuv420p", vid], check=True)
    out = assemble.final_video(spec, vid, watermark=True)
    png = tmp_path / "w.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", out, "-frames:v", "1", str(png)], check=True)
    a = np.asarray(Image.open(png).convert("RGB")).astype(int)
    assert a[30:50, 30:300, 0].mean() > a[30:50, 30:300, 2].mean() + 40     # the red TEST pill top-left


# ---------------------------------------------------------------- the editor's view of a music video
@needs_jp_font
def test_editor_view_carries_lyrics_bars_markers_and_takes(tmp_path):
    d, spec = project(tmp_path, extra=dict(look_bible=dict(prompt="flat cel", palette=["#5f8f8b"])))
    raw = yaml.safe_load((d / "promo.yaml").read_text())
    v = E.mv_view(str(d), spec, raw)
    assert [l["text"] for l in v["lyrics"]] == ["夢を見ていた", "雨上がりの街で"] and v["lyrics"][0]["sung"] == [0.55, 1.9]
    assert v["bars"] == [0.0, 2.0, 4.0, 6.0] and v["markers"] == {"chorus": 4.0}
    assert set(v["shots"]) == {"01", "02"} and v["shots"]["01"]["step"] == 2 and v["bible"]["palette"] == ["#5f8f8b"]
    assert v["layouts"] == list(E.LYRIC_LAYOUTS)
