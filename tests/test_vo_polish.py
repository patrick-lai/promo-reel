"""VO polish (promo/vo_polish.py), speech-band ducking (mix.duck.band) and the mixed-voice read-back (vo-mix-asr). Synthetic signals."""
import json
import os
import sys
import tempfile

import numpy as np
import soundfile as sf
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from promo import check, events, mix, vo_polish  # noqa: E402
from promo.cache import Stamps  # noqa: E402
from promo.spec import SpecError, load_spec  # noqa: E402
from test_audiofx import SR, level_db, voice_like  # noqa: E402


def noisy_voice():
    """voice_like with a recording floor 40 dB under the words (a local TTS) and an "s" (6-8 kHz noise, word level) in each word."""
    x, gate = voice_like()
    rng = np.random.default_rng(3)
    x = x + rng.standard_normal(len(x)) * 10 ** (-40 / 20) * np.sqrt(np.mean(x[gate > 0] ** 2))
    t = np.arange(len(x)) / SR
    sib = (t % 1.0 > 0.45) & (t % 1.0 < 0.55)
    from scipy import signal
    s = signal.sosfiltfilt(signal.butter(4, [6000, 8000], btype="band", fs=SR, output="sos"), rng.standard_normal(len(x)))
    x = x + s / np.sqrt(np.mean(s ** 2)) * np.sqrt(np.mean(x[gate > 0] ** 2)) * np.convolve(sib, np.ones(240) / 240, mode="same")
    return x, gate, sib


def test_resolve_on_off_and_errors():
    assert vo_polish.resolve(None) is None and vo_polish.resolve("off") is None and vo_polish.resolve(False) is None
    assert list(vo_polish.resolve(True)) == ["hp", "compress", "deess", "gate"]
    p = vo_polish.resolve({"gate": {"range": 12}, "compress": "off"})
    assert list(p) == ["hp", "deess", "gate"] and p["gate"]["range"] == 12.0 and p["gate"]["hold"] == 0.04
    for bad, words in (("loud", "must be on, off"), ({"eq": {}}, "unknown stages"), ({"gate": {"bogus": 1}}, "unknown parameters"),
                       ({"deess": {"lo": 9000, "hi": 5000}}, "lo < hi"), ({"gate": {"range": "big"}}, "must be a number")):
        try:
            vo_polish.resolve(bad, "vo.polish")
            raise AssertionError(f"expected an error for {bad}")
        except SpecError as e:
            assert "vo.polish" in str(e) and words in str(e), str(e)


def test_polish_quiets_pauses_keeps_words_and_softens_the_s():
    x, gate, sib = noisy_voice()
    y = vo_polish.apply(x, SR, "on")
    word = (gate > 0) & (np.roll(gate, 2400) > 0) & (np.roll(gate, -2400) > 0) & ~sib
    pause = (gate == 0) & (np.roll(gate, 4800) == 0) & (np.roll(gate, -4800) == 0)       # the middle 0.2 s of each 0.4 s pause
    assert level_db(y[pause]) - level_db(x[pause]) < -15, "the floor in the pauses drops"
    assert abs(level_db(y[word]) - level_db(x[word])) < 1.0, "the words keep their level"
    from scipy import signal
    hi = lambda z: signal.sosfiltfilt(signal.butter(4, [6000, 8000], btype="band", fs=SR, output="sos"), z)
    assert level_db(hi(y)[sib]) - level_db(hi(x)[sib]) < -3, "the s is turned down"


def project(polish=None, line_polish=None, duck=None):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "voices"))
    x, _, _ = noisy_voice()
    sf.write(os.path.join(d, "voices", "a.wav"), x[: int(2.5 * SR)], SR, subtype="FLOAT")
    line = {"id": "a", "shot": "01", "at": 0.5, "file": "a.wav", "text": "a"}
    if line_polish is not None:
        line["polish"] = line_polish
    raw = {"output": {"name": "t", "resolution": 1080, "fps": 12, "duration": 4.0}, "timeline": {"bpm": 120, "beats": 8},
           "music": {"asset": "m"}, "vo": {"engine": "files", "asset": "vo", "lines": [line], **({"polish": polish} if polish else {})},
           "mix": {"sr": SR, "bus_db": {"music": 0.0, "sfx": 0.0, "vo": 0.0}, "duck": duck or {"db": 7.0},
                   "masters": [{"name": "web", "suffix": "", "lufs": -16.0, "ceiling": -1.2}]},
           "shots": [{"id": "01", "beats": [0, 8], "type": "card"}]}
    yaml.safe_dump(raw, open(os.path.join(d, "promo.yaml"), "w"))
    yaml.safe_dump({"assets": [{"id": "vo", "kind": "vo", "path": "voices"}]}, open(os.path.join(d, "assets.yaml"), "w"))
    spec = load_spec(os.path.join(d, "promo.yaml"))
    os.makedirs(spec.audio_dir, exist_ok=True)
    os.makedirs(spec.vo_dir, exist_ok=True)
    sf.write(mix.music_path(spec), (np.random.default_rng(2).standard_normal((4 * SR, 2)) * 0.05).astype(np.float32), SR)
    json.dump({"lines": [{"id": "a", "shot": "01", "text": "a", "file": os.path.join(d, "voices", "a.wav")}]}, open(os.path.join(spec.vo_dir, "vo.json"), "w"))
    events.write_events(spec)
    mix.run(spec)
    return spec, lambda n: sf.read(os.path.join(spec.audio_dir, "stems", f"{n}.wav"))[0][:, 0]


def test_mix_polishes_lines_and_a_line_can_opt_out():
    _, dry = project()
    _, on = project(polish="on")
    _, opt_out = project(polish="on", line_polish="off")
    assert not np.allclose(on("vo"), dry("vo"))
    assert np.array_equal(opt_out("vo"), dry("vo")), "polish: off on the line mixes it as before"


def test_band_duck_dips_the_speech_band_more_than_the_rest():
    from scipy import signal
    spec, stem = project(duck={"db": 3.0, "band": {"lo": 1000, "hi": 5000, "db": 12}})
    raw = sf.read(mix.music_path(spec))[0][:, 0]
    a, b = int(1.2 * SR), int(2.6 * SR)                       # inside the line (0.5-3.0 s), clear of the ramps
    f = lambda z, kind, hz: signal.sosfiltfilt(signal.butter(4, hz, btype=kind, fs=SR, output="sos"), z)[a:b]
    mid = level_db(f(stem("music"), "band", [1500, 4000])) - level_db(f(raw, "band", [1500, 4000]))
    low = level_db(f(stem("music"), "low", 300)) - level_db(f(raw, "low", 300))
    assert abs(mid + 12) < 1.0 and abs(low + 3) < 1.0, (mid, low)
    for bad in ({"band": {"lo": 5000, "hi": 1000}}, {"band": {"lo": True}}, {"band": "wide"}):
        assert mix.spec_problems({"mix": {"duck": bad}}), bad


def test_room_tone_fills_the_gaps_at_its_level_and_is_seeded():
    spec, stem = project(polish="on")
    assert not os.path.exists(os.path.join(spec.audio_dir, "stems", "amb.wav")), "no room key, no bed"
    spec.raw["mix"]["room"] = {"db": -50}
    mix.run(spec)
    room = json.load(open(os.path.join(spec.audio_dir, "mix-report.json")))["room"]
    bed = stem("amb")[int((room["span"][0] + 0.5) * SR): int((room["span"][1] - 0.5) * SR)]
    assert abs(level_db(bed) - (-16 - 50)) < 1.0 and room["colour"] == "takes", room       # noisy_voice has a real floor
    first = stem("amb").copy()
    mix.run(spec)
    assert np.array_equal(stem("amb"), first)
    _, colour = mix.room_tone([(np.zeros(SR), SR)], SR, SR, -60.0, 0)
    assert colour == "pink", "digital-silence pauses have no colour to copy"
    for bad in ({"db": -5}, {"level": -60}, "loud"):
        assert mix.spec_problems({"mix": {"room": bad}}), bad


def test_lost_words_ignores_extra_words_and_homophones_only():
    line = {"text": "Small decisions, made fast."}
    assert check.lost_words(line, "Small decisions made fast. And the next line", {}) == 0.0
    assert check.lost_words(line, "Small decisions fast", {}) == 0.25
    assert check.lost_words(line, "", {}) == 1.0
    assert check.lost_words({"text": "Two. It routes the work."}, "to it roots the work", {}) == 0.0, "heard alike, spelled apart"
    assert check.lost_words({"text": "Hover any mark."}, "Cover any mark.", {}) > 0


def test_vo_mix_asr_fails_a_lost_word_and_warns_on_a_character_line(monkeypatch):
    spec, _ = project()
    line = {"id": "a", "shot": "01", "text": "Small decisions made fast"}
    monkeypatch.setattr(check, "transcribe", lambda path, model: "Small decisions made fast")
    assert check.vo_mix_asr(spec, Stamps(spec.build), {}, [line])[0] == "PASS"
    monkeypatch.setattr(check, "transcribe", lambda path, model: "Small decisions fast")
    status, msg = check.vo_mix_asr(spec, Stamps(spec.build), {}, [line])
    assert status == "PASS", "the window's samples did not change, so the cached read-back stands"
    st = Stamps(spec.build)
    st.write("asr_mix_a", "stale", text="")
    status, msg = check.vo_mix_asr(spec, st, {}, [line])
    assert status == "FAIL" and "a: 25% of its words lost" in msg, msg
    spec.raw["vo"]["lines"][0]["fx"] = "telephone"
    st.write("asr_mix_a", "stale", text="")
    assert check.vo_mix_asr(spec, st, {}, [line])[0] == "WARN"
