"""VO takes (promo/vo.py): raw float takes in the cache, trimmed with fades when written; takes + rejects; the vo-fit / vo-clip / vo-tail gates."""
import os

import numpy as np
import pytest
import soundfile as sf
import yaml

from promo import check, vo
from promo.spec import load_spec

SR = 24000


def tone(sec, amp, f=220.0):
    t = np.arange(int(sec * SR)) / SR
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def quiet(sec):
    return np.zeros(int(sec * SR), np.float32)


def edge_db(x, ms=5):
    """RMS of the first and last `ms` ms against the loudest 10 ms window."""
    n, w = int(ms / 1000 * SR), SR // 100
    rms = lambda e: np.sqrt(np.mean(np.asarray(e, np.float64) ** 2))  # noqa: E731
    peak = max(rms(x[i:i + w]) for i in range(0, len(x) - w, w))
    return [20 * np.log10(rms(e) / peak + 1e-12) for e in (x[:n], x[-n:])]


def project(tmp_path, lines, duration=4.0, **vo_extra):
    raw = {"output": {"name": "t", "resolution": 1080, "fps": 12, "duration": duration}, "timeline": {"bpm": 120, "beats": 8},
           "shots": [{"id": "01", "beats": [0, 8], "type": "card", "text": "x"}],
           "vo": {"engine": "voicestudio", "asset": "vs", "lines": lines, **vo_extra}}
    yaml.safe_dump(raw, open(tmp_path / "promo.yaml", "w"))
    yaml.safe_dump({"assets": []}, open(tmp_path / "assets.yaml", "w"))
    return load_spec(str(tmp_path / "promo.yaml"))


@pytest.fixture
def engine(monkeypatch):
    """A VoiceStudio stand-in: take audio by seed from `takes`, and a count of the calls (a call is a paid or slow take)."""
    calls = []
    takes = {}

    def synth(spec, v, text, man=None, max_usd=None):
        calls.append(int(v.get("seed", 1)))
        return takes.get(int(v.get("seed", 1)), takes.get("default")), SR
    monkeypatch.setattr(vo, "synth", synth)
    return calls, takes


def test_trim_keeps_a_soft_ending_and_fades_both_edges():
    soft = 10 ** (-44 / 20) * 0.5
    x = np.concatenate([quiet(0.3), tone(0.5, 0.5), tone(0.2, soft), quiet(0.4)])
    y = vo.trim(x, SR)
    assert len(y) / SR > 0.5 + 0.2                     # the -44 dB tail is speech (the old 0.01 floor cut it)
    assert len(y) / SR < 0.01 + 0.5 + 0.2 + 0.1 + 0.02  # leading / trailing silence gone, the legacy pads kept
    assert y[0] == 0 and y[-1] == 0
    assert all(db < -60 for db in edge_db(y))


def test_a_loud_take_is_kept_unclipped_and_a_trim_change_makes_no_new_take(tmp_path, engine, monkeypatch):
    calls, takes = engine
    takes["default"] = np.concatenate([quiet(0.2), tone(0.6, 1.3), quiet(0.3)])
    spec = project(tmp_path, [{"id": "a", "shot": "01", "text": "Hello there."}])
    vo.run(spec)
    out = os.path.join(spec.vo_dir, "vo-a.wav")
    x, _ = sf.read(out, dtype="float32")
    assert sf.info(out).subtype == "FLOAT" and abs(x).max() > 1.25
    monkeypatch.setattr(vo, "TRIM_DB", -30.0)
    monkeypatch.setattr(vo, "PAD_OUT", 0.05)
    vo.run(spec)
    assert len(calls) == 1                              # the trim runs on the cached raw take: nothing synthesised (or billed) again
    assert len(sf.read(out)[0]) < len(x)


def test_takes_reject_misreads_and_cut_offs_and_a_pick_wins(tmp_path, engine, monkeypatch):
    calls, takes = engine
    good = np.concatenate([quiet(0.2), tone(0.8, 0.5), quiet(0.3)])
    takes.update({1: good, 2: good * 0.9, 3: np.concatenate([quiet(0.2), tone(0.8, 0.5)]), 4: good * 0.8})   # 3 stops mid-sound
    monkeypatch.setattr(check, "transcribe", lambda wav, model: "Hollow hair." if wav.endswith("a-2.wav") else "Hello there.")   # whisper mishears take 2
    monkeypatch.setattr("promo.vo_score.pitch_st", lambda x, sr: 1.0)
    line = {"id": "a", "shot": "01", "text": "Hello there.", "takes": 4}
    spec = project(tmp_path, [line])
    meta = vo.run(spec)[0]
    rej = {t["take"]: t["rejected"] for t in meta["takes"]}
    assert rej[1] is None and "WER" in rej[2] and "mid-sound" in rej[3] and rej[4] is None
    assert meta["take"] == 1 and sorted(calls) == [1, 2, 3, 4]
    spec = project(tmp_path, [dict(line, take=4)])
    meta = vo.run(spec)[0]
    assert meta["take"] == 4 and len(calls) == 4         # picking a take re-uses it, no new synthesis
    assert np.allclose(sf.read(os.path.join(spec.vo_dir, "vo-a.wav"))[0], sf.read(os.path.join(spec.vo_dir, meta["takes"][3]["file"]))[0])


def test_takes_need_an_engine_that_varies(tmp_path):
    spec = project(tmp_path, [{"id": "a", "shot": "01", "text": "Hi.", "takes": 2, "voice": {"engine": "kokoro"}}])
    with pytest.raises(RuntimeError, match="same audio every time"):
        vo.run(spec)


def test_the_vo_blocks_licence_entry_covers_its_own_engine_only(tmp_path):
    from promo import assets as A
    spec = project(tmp_path, [{"id": "a", "shot": "01", "text": "Hi."}, {"id": "b", "shot": "01", "text": "Yo.", "voice": {"engine": "say"}}])
    yaml.safe_dump({"assets": [{"id": "vs", "kind": "vo_model", "path": "build/vo", "licence": "x", "source_url": "https://x"}]},
                   open(tmp_path / "assets.yaml", "w"))
    assert A.validate(spec) == ["vo line b: engine say needs `asset:` in its voice (an assets.yaml entry of kind vo_model with the licence of that voice)"]


def gates(tmp_path, lines, audio, duration=4.0):
    spec = project(tmp_path, lines, duration)
    os.makedirs(spec.vo_dir, exist_ok=True)
    meta = []
    for ln in lines:
        sf.write(os.path.join(spec.vo_dir, f"vo-{ln['id']}.wav"), audio[ln["id"]], SR, subtype="FLOAT")
        meta.append(dict(id=ln["id"], shot="01", file=f"vo-{ln['id']}.wav"))
    return {g: (s, m) for g, s, m in check.vo_audio_gates(spec, meta)}


def test_clean_lines_pass_every_vo_audio_gate(tmp_path):
    clean = vo.trim(np.concatenate([quiet(0.1), tone(1.0, 0.5), quiet(0.2)]), SR)
    g = gates(tmp_path, [{"id": "a", "shot": "01", "text": "x", "at": 0.0}, {"id": "b", "shot": "01", "text": "y", "at": 2.0}], {"a": clean, "b": clean})
    assert {k: s for k, (s, _) in g.items()} == {"vo-fit": "PASS", "vo-clip": "PASS", "vo-tail": "PASS"}


def test_vo_audio_gates_catch_overrun_overlap_clipping_and_a_cut(tmp_path):
    clean = vo.trim(np.concatenate([quiet(0.1), tone(1.0, 0.5), quiet(0.2)]), SR)
    clipped = np.clip(clean * 3, -1, 1)
    cut = np.concatenate([quiet(0.1), tone(1.0, 0.5)])
    g = gates(tmp_path, [{"id": "a", "shot": "01", "text": "x", "at": 0.0}, {"id": "b", "shot": "01", "text": "y", "at": 0.5},
                         {"id": "c", "shot": "01", "text": "z", "at": 3.5}], {"a": clipped, "b": cut, "c": clean})
    assert g["vo-fit"][0] == "FAIL" and "c ends at" in g["vo-fit"][1] and "a runs" in g["vo-fit"][1]
    assert g["vo-clip"][0] == "WARN" and g["vo-clip"][1].count("flat-topped") == 1 and "a (" in g["vo-clip"][1]
    assert g["vo-tail"][0] == "WARN" and "b (" in g["vo-tail"][1] and "c (" not in g["vo-tail"][1]


def test_an_overlap_alone_only_warns(tmp_path):
    clean = vo.trim(np.concatenate([quiet(0.1), tone(1.0, 0.5), quiet(0.2)]), SR)
    g = gates(tmp_path, [{"id": "a", "shot": "01", "text": "x", "at": 0.0}, {"id": "b", "shot": "01", "text": "y", "at": 0.5}], {"a": clean, "b": clean})
    assert g["vo-fit"][0] == "WARN"


STUB_WORKER = '''
import json, os, sys
import numpy as np, soundfile as sf
proto = os.fdopen(os.dup(1), "w", buffering=1)
proto.write(json.dumps({"ok": True, "ready": True}) + "\\n")
for line in sys.stdin:
    job = json.loads(line)
    if "crash" in job["text"]:
        sys.exit(3)
    open(os.environ["SEEN"], "a").write(f"{job['seed']} {job['voice']}\\n")
    t = np.arange(24000) / 24000
    sf.write(job["out"], (0.4 * np.sin(2 * np.pi * (200 + 10 * job["seed"]) * t)).astype("float32"), 24000, subtype="FLOAT")
    proto.write(json.dumps({"ok": True, "sr": 24000, "frames": 24000}) + "\\n")
'''


@pytest.fixture
def local_voice(tmp_path, monkeypatch):
    """The local voice as `promo vo setup` leaves it, with a stand-in worker that speaks its protocol (tests never load the model)."""
    import sys

    from promo import vo_mlx
    monkeypatch.setattr(vo_mlx, "HOME", tmp_path / "home")
    vo_mlx.venv_dir().mkdir(parents=True)
    (vo_mlx.venv_dir() / "stamp.json").write_text('{"pin": "p", "model_rev": "r", "mlx": "0", "model_dir": "m"}')
    (tmp_path / "stub.py").write_text(STUB_WORKER)
    monkeypatch.setenv("PROMO_MLX_WORKER", f"{sys.executable} {tmp_path / 'stub.py'}")
    monkeypatch.setenv("SEEN", str(tmp_path / "seen.txt"))
    yield tmp_path / "seen.txt"
    vo_mlx._close()
    vo_mlx._WORKER.clear()


def test_local_takes_are_seed_plus_k_from_one_worker(tmp_path, local_voice, monkeypatch):
    monkeypatch.setattr(check, "transcribe", lambda wav, model: "Hello there.")
    monkeypatch.setattr("promo.vo_score.pitch_st", lambda x, sr: 1.0)
    spec = project(tmp_path, [{"id": "a", "shot": "01", "text": "Hello there.", "takes": 2, "voice": {"engine": "mlx", "seed": 5}},
                              {"id": "b", "shot": "01", "text": "Hello there.", "at": 2.0, "voice": {"engine": "mlx", "voice": "US_James"}}])
    meta = vo.run(spec)
    assert local_voice.read_text().split("\n")[:3] == ["5 UK_Charlotte", "6 UK_Charlotte", "1 US_James"]
    assert [m["take"] for m in meta] == [1, 1] and len(meta[0]["takes"]) == 2


def test_a_worker_that_dies_leaves_no_cached_take(tmp_path, local_voice):
    spec = project(tmp_path, [{"id": "a", "shot": "01", "text": "please crash", "voice": {"engine": "mlx"}}])
    with pytest.raises(RuntimeError, match="local voice stopped"):
        vo.run(spec)
    assert not [f for f in os.listdir(os.path.join(spec.vo_dir, ".cache")) if f.endswith(".wav")]


def test_the_local_voice_asks_for_setup_and_hosted_voices_name_it(tmp_path, monkeypatch):
    from promo import openrouter as OR
    from promo import vo_mlx
    monkeypatch.setattr(vo_mlx, "HOME", tmp_path / "home")
    with pytest.raises(RuntimeError, match="promo vo setup"):
        vo.run(project(tmp_path, [{"id": "a", "shot": "01", "text": "Hi.", "voice": {"engine": "mlx"}}]))
    with pytest.raises(OR.OpenRouterError, match="engine: mlx"):
        vo.run(project(tmp_path, [{"id": "a", "shot": "01", "text": "Hi.", "voice": {"engine": "openrouter"}}]))
