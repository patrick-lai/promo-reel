"""Shot `audio:` lines (promo/shot_audio.py): clip soundtrack in events + mix. Plain asserts (pytest or `python tests/test_shot_audio.py`).
Tiny: a 4 s timeline, two synthetic 12 fps 64x48 clips made with ffmpeg (a sine tone with an audio stream; a silent video)."""
import copy
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo import cli, events, mix, shot_audio  # noqa: E402
from promo.spec import SpecError, load_spec  # noqa: E402

BASE = {
    "output": {"name": "t", "resolution": 1080, "fps": 12, "duration": 4.0},
    "timeline": {"bpm": 120, "beats": 8},
    "music": {"asset": "m"},
    "mix": {"sr": 48000, "bus_db": {"music": 0.0, "sfx": 0.0, "vo": 0.0}, "duck": {"db": 8.0, "attack": 0.05, "release": 0.2, "pre": 0.1, "post": 0.1},
            "masters": [{"name": "web", "suffix": "", "lufs": -16.0, "ceiling": -1.2, "max_true_peak": -1.0}]},
    "shots": [{"id": "01", "beats": [0, 4], "type": "clip", "source": "tone", "t_in": 0.5, "cam": [[0, 0.5, 0.5, 1.0]]},
              {"id": "02", "beats": [4, 8], "type": "clip", "source": "ui", "cam": [[0, 0.5, 0.5, 1.0]]}],
}
LINE = {"from": "source", "t_in": 0.5, "dur": 1.2, "at": 0.3, "lufs": -20.0, "text": "tone"}


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def make_project(audio=None, audio2=None, shot_extra=None):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "footage"), exist_ok=True)
    tone, ui = os.path.join(d, "tone.mp4"), os.path.join(d, "ui.mp4")
    if not os.path.exists(tone):
        ff("-f", "lavfi", "-i", "testsrc=size=64x48:rate=12:duration=4", "-f", "lavfi", "-i", "sine=frequency=440:duration=4:sample_rate=44100",
           "-shortest", "-c:v", "mpeg4", "-c:a", "aac", tone)
        ff("-f", "lavfi", "-i", "testsrc=size=64x48:rate=12:duration=4", "-c:v", "mpeg4", ui)
    yaml.safe_dump({"clips": [{"id": "tone", "path": tone, "shots": ["01"]}, {"id": "ui", "path": ui, "shots": ["02"]}]}, open(os.path.join(d, "footage", "manifest.yaml"), "w"))
    yaml.safe_dump({"assets": []}, open(os.path.join(d, "assets.yaml"), "w"))
    return d, tone, ui


def make_spec(d, audio=None, audio2=None, mix_over=None):
    raw = copy.deepcopy(BASE)
    if audio is not None:
        raw["shots"][0]["audio"] = audio
    if audio2 is not None:
        raw["shots"][1]["audio"] = audio2
    if mix_over:
        raw["mix"].update(mix_over)
    p = os.path.join(d, "promo.yaml")
    yaml.safe_dump(raw, open(p, "w"))
    return load_spec(p)


def write_music(spec, v=0.1):
    os.makedirs(spec.audio_dir, exist_ok=True)
    sf.write(mix.music_path(spec), np.full((4 * 48000, 2), v, np.float32), 48000)


def test_events_resolve_defaults_and_global_time():
    d, tone, _ = make_project()
    spec = make_spec(d, audio=[LINE, {"from": "tone", "bus": "amb", "id": "room", "db": -6}])
    ls = shot_audio.lines(spec)
    assert [l["id"] for l in ls] == ["01-0-clip", "room"]
    assert ls[0]["t"] == 0.3 and ls[0]["t_in"] == 0.5 and ls[0]["file"].endswith(os.path.join("vo", "01-0-clip.wav"))
    assert ls[1]["t_in"] == 0.0 and abs(ls[1]["dur"] - 2.0) < 1e-9 and os.path.join("audio", "amb") in ls[1]["file"]     # default dur = shot duration
    ev = events.compute_events(spec)
    assert [c["t"] for c in ev["clips"]] == [0.3, 0.0] and ev["clips"][1]["bus"] == "amb" and ev["clips"][1]["db"] == -6
    # shot 2 starts at 2.0 s: `at` is shot-local
    spec2 = make_spec(d, audio2=dict(LINE, **{"from": "tone", "at": 0.5}))
    assert events.compute_events(spec2)["clips"][0]["t"] == 2.5
    assert "clips" not in events.compute_events(make_spec(d))                  # legacy events.json unchanged without audio


def test_no_audio_stream_is_a_clear_error():
    d, _, ui = make_project()
    spec = make_spec(d, audio2={"from": "source"})
    try:
        shot_audio.run(spec)
        raise AssertionError("expected ShotAudioError")
    except shot_audio.ShotAudioError as e:
        assert "'ui'" in str(e) and "no audio stream" in str(e) and "shot 02" in str(e)
    rows = dict((g, (s, m)) for g, s, m in shot_audio.check(spec, qa={}))
    assert rows["shot-audio"][0] == "FAIL" and "'ui'" in rows["shot-audio"][1]
    # an unknown clip id is also an error naming it
    try:
        shot_audio.render_line(spec, shot_audio.lines(make_spec(d, audio={"from": "nope"}))[0])
        raise AssertionError("expected an error")
    except SpecError as e:
        assert "nope" in str(e)


def test_render_normalises_trims_and_mix_places_and_ducks():
    d, _, _ = make_project()
    spec = make_spec(d, audio=[LINE])
    shot_audio.run(spec)
    l = shot_audio.lines(spec)[0]
    x, sr = sf.read(l["file"])
    assert sr == 48000 and x.ndim == 1 and abs(len(x) / sr - 1.2) < 0.01          # trimmed to audio.dur
    assert abs(pyln.Meter(sr).integrated_loudness(x[:, None]) - (-20.0)) < 0.3      # normalised to lufs
    assert abs(x[:100]).max() < 0.01                                               # fade in from silence
    # events + mix: a constant music bed, the line at 0.3 s
    events.write_events(spec)
    write_music(spec)
    mix.run(spec)
    stems = os.path.join(spec.audio_dir, "stems")
    vo = sf.read(os.path.join(stems, "vo.wav"))[0]
    onset = np.argmax(np.abs(vo[:, 0]) > 0.01) / 48000
    assert 0.3 <= onset < 0.4, onset
    assert np.abs(vo[int(1.6 * 48000):]).max() < 1e-4                              # silent after the 1.2 s line
    mu = sf.read(os.path.join(stems, "music.wav"))[0][:, 0]
    rms = lambda a, b: float(np.sqrt(np.mean(mu[int(a * 48000):int(b * 48000)] ** 2)))
    ducked = 20 * np.log10(rms(0.7, 1.2) / rms(0.0, 0.1))
    assert -9.5 < ducked < -6.5, ducked                                            # mix.duck.db = 8 dB under the line
    assert abs(20 * np.log10(rms(2.5, 3.5) / 0.1)) < 0.5                           # recovers after the line (release 0.2 s)
    rep = json.load(open(os.path.join(spec.audio_dir, "mix-report.json")))
    c = rep["clips"][0]
    assert c["id"] == "01-0-clip" and c["bus"] == "vo" and c["t"] == 0.3 and abs(c["lufs"] + 20.0) < 0.3 and c["peak_db"] < 0


def test_amb_bus_has_gain_but_no_duck():
    d, _, _ = make_project()
    spec = make_spec(d, audio=[dict(LINE, bus="amb", db=-3.0)])
    shot_audio.run(spec)
    events.write_events(spec)
    write_music(spec)
    mix.run(spec)
    stems = os.path.join(spec.audio_dir, "stems")
    mu = sf.read(os.path.join(stems, "music.wav"))[0][:, 0]
    assert abs(mu[int(0.8 * 48000)] - 0.1) < 1e-3, "amb must not duck the music"
    assert os.path.exists(os.path.join(stems, "amb.wav")) and np.abs(sf.read(os.path.join(stems, "vo.wav"))[0]).max() == 0
    assert 0 < sf.info(shot_audio.lines(spec)[0]["file"]).duration < 1.3 and "amb" in json.load(open(os.path.join(spec.audio_dir, "mix-report.json")))["clips"][0]["bus"]


def test_overlap_warn_on_vo_bus_only():
    d, _, _ = make_project()
    spec = make_spec(d, audio=[dict(LINE, at=0.0, dur=1.0), dict(LINE, at=0.5, dur=1.0)])
    r = dict((g, (s, m)) for g, s, m in shot_audio.check(spec, qa={}))
    assert r["shot-audio"][0] == "WARN" and "overlap 0.50s" in r["shot-audio"][1]
    spec = make_spec(d, audio=[dict(LINE, at=0.0, dur=1.0), dict(LINE, at=0.5, dur=1.0, bus="amb")])         # amb under dialogue is fine
    assert shot_audio.check(spec, qa={})[0][1] == "PASS"
    spec = make_spec(d, audio=[dict(LINE, at=0.0, dur=1.0), dict(LINE, at=0.85, dur=1.0)])                   # 0.15 s overlap <= 0.25
    assert shot_audio.check(spec, qa={})[0][1] == "PASS"
    assert shot_audio.check(make_spec(d), qa={})[0][1] == "PASS"                                            # no audio keys


def test_asr_gate_skips_lines_without_text_and_without_wer():
    d, _, _ = make_project()
    spec = make_spec(d, audio=[{k: v for k, v in LINE.items() if k != "text"}])
    shot_audio.run(spec)
    assert [g for g, *_ in shot_audio.check(spec, qa={})] == ["shot-audio"]                 # no vo_max_wer: no read-back
    rows = shot_audio.check(spec, qa={"vo_max_wer": 0.0})
    try:
        import faster_whisper  # noqa: F401
        assert rows[1][0] == "shot-audio-asr" and "skipped" in rows[1][2] and "without `text`" in rows[1][2]
    except ImportError:
        assert rows[1][1] in ("PASS", "WARN")


def test_digests_audio_params_touch_audio_events_mix_not_the_picture():
    d, _, _ = make_project()
    ev = lambda s: next(st for st in cli.plan(s) if st["name"] == "events")["dig"]()
    ca = lambda s: next(st for st in cli.plan(s) if st["name"] == "clip-audio")["dig"]()
    shot = lambda s: cli.shot_digest(s, s.shots[0])
    a, b, c = make_spec(d, audio=[LINE]), make_spec(d, audio=[dict(LINE, db=-4.0)]), make_spec(d, audio=[dict(LINE, lufs=-18.0)])
    assert shot(a) == shot(b) == shot(c), "audio keys never re-render the picture"
    assert ev(a) != ev(b) and ev(a) != ev(c), "events (placement/gain) depend on audio params"
    assert ca(a) == ca(b), "db is applied in the mix, not in the extracted WAV"
    assert ca(a) != ca(c), "lufs changes the extracted WAV"
    # the mix digest follows events.json + the clip WAVs
    write_music(a)
    mdig = lambda s: next(st for st in cli.plan(s) if st["name"] == "mix")["dig"]()
    mds = []
    for s in (a, b):                      # same build dir: rebuild the events for each variant, then digest the mix
        shot_audio.run(s)
        events.write_events(s)
        mds.append(mdig(s))
    ma, mb = mds
    assert ma != mb
    assert any(st["name"] == "clip-audio" for st in cli.plan(a)) and not any(st["name"] == "clip-audio" for st in cli.plan(make_spec(d)))


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
            print("ok", k)
