"""Audio character effects (promo/audiofx.py) and their `fx` keys in the mix. Synthetic, seeded signals only."""
import json
import os
import sys
import tempfile

import numpy as np
import soundfile as sf
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo import audiofx, events, mix  # noqa: E402
from promo.spec import SpecError, load_spec  # noqa: E402

SR = 48000


def voice_like(seed=1):
    """3 s of 'speech': harmonic bursts (130 Hz fundamental, harmonics up to 9 kHz) with real silences between them."""
    t = np.arange(3 * SR) / SR
    x = sum(np.sin(2 * np.pi * 130 * h * t) / h for h in range(1, 70))
    gate = ((t % 1.0) < 0.6).astype(float)
    x = x * np.convolve(gate, np.ones(480) / 480, mode="same")
    x += np.random.default_rng(seed).standard_normal(len(t)) * 1e-5         # a near-silent recording floor
    return x * 0.2, gate


def band_db(x, lo, hi):
    X = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return 10 * np.log10(X[(f >= lo) & (f < hi)].sum() / X.sum() + 1e-20)


def level_db(x):
    return 10 * np.log10(np.mean(x ** 2) + 1e-20)


def test_radio_band_limits_the_voice_and_keeps_noise_far_under_it():
    x, gate = voice_like()
    y = audiofx.apply(x, SR, "radio")
    assert band_db(x, 0, 200) > -10 and band_db(x, 4500, 24000) > -25             # the input is full-band
    assert band_db(y, 0, 200) < -30 and band_db(y, 4500, 24000) < -30              # the radio is not
    speech, silence = y[(gate > 0) & (np.roll(gate, 4800) > 0)], y[(gate == 0) & (np.roll(gate, -4800) == 0) & (np.roll(gate, 4800) == 0)]
    assert level_db(speech) - level_db(silence) > 40, "the hiss and hum must sit far under the voice, never read as static"
    assert abs(level_db(speech) - level_db(x[(gate > 0) & (np.roll(gate, 4800) > 0)])) < 1.5   # the line keeps its level


def test_crackle_runs_through_the_gaps_light_and_leaves_the_tone_alone():
    x, gate = voice_like()
    y = audiofx.apply(x, SR, "crackle")
    speech = (gate > 0) & (np.roll(gate, 4800) > 0)
    gaps = (gate == 0) & (np.roll(gate, -4800) == 0) & (np.roll(gate, 4800) == 0)
    under = level_db(y[speech]) - level_db(y[gaps])
    assert 20 < under < 60, f"a steady crackle is heard between the words but stays light ({under:.1f} dB under)"
    assert abs(band_db(y, 0, 200) - band_db(x, 0, 200)) < 0.5


def test_amount_zero_is_the_input_and_keyframes_clear_the_effect():
    x, _ = voice_like()
    assert np.array_equal(audiofx.apply(x, SR, {"preset": "vintage", "amount": 0}), x)
    y = audiofx.apply(x, SR, {"preset": "vintage", "amount": [[10.0, 1], [11.0, 0]]}, t0=9.5)   # stream starts at 9.5 s of the film
    clean = int(1.6 * SR)                                                                         # 11.1 s on the film clock: fully dry
    assert np.allclose(y[clean:], x[clean:], atol=1e-9)
    assert not np.allclose(y[: int(0.4 * SR)], x[: int(0.4 * SR)], atol=1e-3)


def test_same_spec_renders_the_same_samples():
    x, _ = voice_like()
    assert np.array_equal(audiofx.apply(x, SR, "vinyl"), audiofx.apply(x, SR, "vinyl"))


def test_bad_fx_values_are_spec_errors_naming_the_place():
    for fx, words in [("radioo", "unknown preset"), ({"preset": "radio", "hiss": {"dbb": 1}}, "unknown parameters"),
                      ({"preset": "radio", "wow": {"wow": 1}}, "not a stage of radio"), ({"preset": "tape", "amount": 2}, "between 0 and 1"),
                      ({"chain": [{"type": "reverb"}]}, "`type` must be one of")]:
        try:
            audiofx.resolve(fx, "vo.fx")
            raise AssertionError(f"expected an error for {fx}")
        except SpecError as e:
            assert "vo.fx" in str(e) and words in str(e), str(e)


def make_spec(vo_fx=None, line_fx=None, music_fx=None):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "voices"))
    x, _ = voice_like()
    sf.write(os.path.join(d, "voices", "a.wav"), x[: int(1.5 * SR)], SR, subtype="FLOAT")
    line = {"id": "a", "shot": "01", "at": 0.5, "file": "a.wav", "text": "a"}
    if line_fx is not None:
        line["fx"] = line_fx
    raw = {"output": {"name": "t", "resolution": 1080, "fps": 12, "duration": 4.0}, "timeline": {"bpm": 120, "beats": 8},
           "music": {"asset": "m", **({"fx": music_fx} if music_fx else {})},
           "vo": {"engine": "files", "asset": "vo", "lines": [line], **({"fx": vo_fx} if vo_fx else {})},
           "mix": {"sr": SR, "bus_db": {"music": 0.0, "sfx": 0.0, "vo": 0.0}, "masters": [{"name": "web", "suffix": "", "lufs": -16.0, "ceiling": -1.2}]},
           "shots": [{"id": "01", "beats": [0, 8], "type": "card"}]}
    yaml.safe_dump(raw, open(os.path.join(d, "promo.yaml"), "w"))
    yaml.safe_dump({"assets": [{"id": "vo", "kind": "vo", "path": "voices"}]}, open(os.path.join(d, "assets.yaml"), "w"))
    spec = load_spec(os.path.join(d, "promo.yaml"))
    os.makedirs(spec.audio_dir, exist_ok=True)
    os.makedirs(spec.vo_dir, exist_ok=True)
    music = np.random.default_rng(2).standard_normal((4 * SR, 2)) * 0.05
    sf.write(mix.music_path(spec), music.astype(np.float32), SR)
    json.dump({"lines": [{"id": "a", "shot": "01", "text": "a", "file": os.path.join(d, "voices", "a.wav")}]}, open(os.path.join(spec.vo_dir, "vo.json"), "w"))
    events.write_events(spec)
    mix.run(spec)
    stem = lambda n: sf.read(os.path.join(spec.audio_dir, "stems", f"{n}.wav"))[0][:, 0]
    return spec, stem


def test_mix_applies_vo_and_music_fx_and_a_line_can_opt_out():
    spec, stem = make_spec(vo_fx="telephone", music_fx="radio")
    assert spec.validate() == []
    assert band_db(stem("vo"), 0, 250) < -30 and band_db(stem("music"), 0, 200) < -25
    _, stem = make_spec(vo_fx="telephone", line_fx="none")
    assert band_db(stem("vo"), 0, 250) > -10, "fx: none on a line keeps it dry"
    try:
        make_spec(vo_fx={"preset": "radio", "amount": 5})
        raise AssertionError("expected an error")
    except SpecError as e:
        assert "vo line a fx" in str(e)


def test_validate_reports_bad_fx_before_any_render():
    d = tempfile.mkdtemp()
    raw = {"output": {"name": "t", "resolution": 1080, "fps": 12, "duration": 4.0}, "timeline": {"bpm": 120, "beats": 8},
           "mix": {"fx": "radioo"}, "shots": [{"id": "01", "beats": [0, 8], "type": "card"}]}
    yaml.safe_dump(raw, open(os.path.join(d, "promo.yaml"), "w"))
    errs = load_spec(os.path.join(d, "promo.yaml")).validate()
    assert any("mix.fx" in e and "unknown preset" in e for e in errs), errs
