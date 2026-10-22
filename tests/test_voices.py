"""Cloned voices: storage rules, promo.yaml, the licence gate, and the promo-flow worker.

No Chatterbox weights. Recordings are short sine WAVs under PROMO_VOICES_DIR.
"""
import json
import os
import subprocess
import sys

import numpy as np
import pytest
import soundfile as sf
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo import assets as A  # noqa: E402
from promo import voices as V  # noqa: E402
from promo.spec import load_spec  # noqa: E402

WORKER = os.path.join(ROOT, "mods", "promo-flow", "worker")
PY = sys.executable


def sine(path, seconds, sr=16000, freq=440.0):
    n = int(round(seconds * sr))
    t = np.arange(n, dtype=np.float32) / sr
    x = (0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, x, sr, subtype="PCM_16")


def reading(directory, seconds, moods=V.MOODS):
    script = os.path.join(directory, "script")
    mood = os.path.join(directory, "moods")
    os.makedirs(script)
    os.makedirs(mood)
    sine(os.path.join(script, "read.wav"), seconds)
    for i, name in enumerate(moods):
        sine(os.path.join(mood, name + ".wav"), 0.4, freq=330.0 + 40 * i)
    return script, mood


@pytest.fixture
def voices_home(tmp_path, monkeypatch):
    home = tmp_path / "voices"
    home.mkdir()
    monkeypatch.setenv("PROMO_VOICES_DIR", str(home))
    return home


def test_save_refuses_short_script(tmp_path, voices_home):
    script, mood = reading(str(tmp_path / "in"), 29.0)
    with pytest.raises(V.VoicesError) as caught:
        V.save("Ada", script, mood)
    assert caught.value.code == "voices.too_short"
    assert V.list_voices() == []
    assert list(voices_home.iterdir()) == []


def test_save_refuses_missing_mood(tmp_path, voices_home):
    script, mood = reading(str(tmp_path / "in"), 30.0, moods=("neutral", "excited", "calm"))
    with pytest.raises(V.VoicesError) as caught:
        V.save("Ada", script, mood)
    assert caught.value.code == "voices.mood_missing"
    assert "warm" in caught.value.message
    assert V.list_voices() == []


def test_parse_vo_emotion_and_intensity():
    vo = {
        "engine": "clone",
        "voice": "ada",
        "lines": [{"id": "a", "shot": "01", "at": 0.1, "text": "Hello there.", "emotion": "calm", "intensity": 0.4}],
    }
    parsed = V.parse_vo(vo)
    assert parsed["engine"] == "clone" and parsed["voice"] == "ada"
    assert parsed["lines"][0]["emotion"] == "calm"
    assert parsed["lines"][0]["intensity"] == 0.4
    bad = dict(vo, lines=[{"id": "a", "shot": "01", "at": 0.1, "text": "Hello there.", "emotion": "angry", "intensity": 0.4}])
    with pytest.raises(V.VoicesError) as caught:
        V.parse_vo(bad)
    assert caught.value.code == "voices.bad_emotion"
    for intensity in (1.5, True, False):
        bad = dict(vo, lines=[{"id": "a", "shot": "01", "at": 0.1, "text": "Hello there.", "emotion": "calm", "intensity": intensity}])
        with pytest.raises(V.VoicesError) as caught:
            V.parse_vo(bad)
        assert caught.value.code == "voices.bad_intensity"


def _promo(root, voice_id):
    promo = os.path.join(root, "promo.yaml")
    with open(promo, "w") as f:
        yaml.safe_dump({
            "project": {"name": "t", "title": "T"},
            "output": {"name": "t", "resolution": 1080, "fps": 30, "duration": 2},
            "assets": "assets.yaml",
            "timeline": {"bpm": 120, "beats": 4},
            "shots": [{"id": "01", "beats": [0, 4], "type": "card"}],
            "vo": {
                "engine": "clone",
                "voice": voice_id,
                "lines": [{"id": "a", "shot": "01", "at": 0.1, "text": "Hello there.", "emotion": "calm", "intensity": 0.4}],
            },
        }, f, sort_keys=False)
    return promo


def _write_assets(root, entry):
    with open(os.path.join(root, "assets.yaml"), "w") as f:
        yaml.safe_dump({"assets": [entry]}, f, sort_keys=False)


def test_licence_to_asset_and_gate(tmp_path, voices_home):
    script, mood = reading(str(tmp_path / "in"), 30.0)
    saved = V.save("Ada", script, mood)
    entry = V.licence_to_asset(saved["id"])
    assert entry["id"] == "vo-" + saved["id"]
    assert entry["kind"] == "vo_model"
    assert entry["licence"] == "MIT"
    assert entry["source_url"] == "https://github.com/resemble-ai/chatterbox"
    assert entry["generated"]["likeness"] == "own"
    assert entry["generated"]["consent"]
    assert "test_only" not in entry
    root = str(tmp_path / "proj")
    os.makedirs(root)
    _write_assets(root, entry)
    spec = load_spec(_promo(root, saved["id"]))
    assert A.validate(spec) == []

    lic_path = os.path.join(V.voice_dir(saved["id"]), "licence.yaml")
    lic = yaml.safe_load(open(lic_path))
    lic["commercial"] = False
    yaml.safe_dump(lic, open(lic_path, "w"), sort_keys=False)
    entry = V.licence_to_asset(saved["id"])
    assert entry["test_only"] is True
    _write_assets(root, entry)
    spec = load_spec(_promo(root, saved["id"]))
    assert A.validate(spec) == []
    assert A.test_only_assets(spec) == [entry["id"]]


def test_delete_then_project_missing(tmp_path, voices_home):
    script, mood = reading(str(tmp_path / "in"), 30.0)
    saved = V.save("Ada", script, mood)
    promo = _promo(str(tmp_path), saved["id"])
    assert os.path.isdir(saved["dir"])
    V.delete(saved["id"])
    assert not os.path.exists(saved["dir"])
    with pytest.raises(V.VoicesError) as caught:
        V.require_project(promo)
    assert caught.value.code == "voices.not_found"


def test_worker_http_refuses_and_stdio_lists(tmp_path):
    refused = subprocess.run(
        [PY, WORKER, "--http", "0.0.0.0:9"],
        capture_output=True, text=True, timeout=10,
    )
    assert refused.returncode != 0
    assert "127.0.0.1" in refused.stderr

    env = os.environ.copy()
    env["PROMO_VOICES_DIR"] = str(tmp_path / "voices")
    env["PYTHONUNBUFFERED"] = "1"
    listed = subprocess.run(
        [PY, WORKER],
        input=json.dumps({"type": "call", "id": 1, "method": "voices.list", "params": {}}) + "\n",
        capture_output=True, text=True, timeout=30, env=env,
    )
    assert listed.returncode == 0, listed.stderr
    msg = json.loads(listed.stdout.strip().splitlines()[-1])
    assert msg["type"] == "result" and msg["ok"] is True and msg["id"] == 1
    assert isinstance(msg["value"], list)


def test_worker_job_start_cancel_round_trip(monkeypatch):
    """job.start runs beside stdin, job.cancel drops the result, legacy call/event/hello stay."""
    import importlib.machinery
    import importlib.util
    import threading
    import time

    loader = importlib.machinery.SourceFileLoader("promo_flow_worker_jobs", WORKER)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    worker = importlib.util.module_from_spec(spec)
    loader.exec_module(worker)

    lines = []
    lock = threading.Lock()
    started = threading.Event()
    release = threading.Event()
    idents = []

    def emit(obj):
        with lock:
            lines.append(obj)

    def handle(method, params, progress):
        idents.append((method, threading.get_ident()))
        if method == "voices.sample":
            started.set()
            progress(0.4, "Cloning")
            release.wait(5)
            return {"id": "ada"}
        if method == "voices.list":
            return [{"id": "ada"}]
        if method == "voices.save":
            err = Exception("script audio is 29 s")
            err.code = "voices.too_short"
            err.message = "script audio is 29 s"
            raise err
        raise AssertionError(method)

    monkeypatch.setattr(worker, "HEARTBEAT_S", 0.05)
    monkeypatch.setattr(worker, "emit", emit)
    monkeypatch.setattr(worker, "handle", handle)

    read_fd, write_fd = os.pipe()
    stdin = os.fdopen(read_fd, "r")
    monkeypatch.setattr(worker.sys, "stdin", stdin)
    reader = threading.Thread(target=worker.stdio, name="stdio", daemon=True)
    reader.start()

    def send(obj):
        os.write(write_fd, (json.dumps(obj) + "\n").encode())

    def snapshot():
        with lock:
            return list(lines)

    try:
        send({
            "type": "job.start", "job": "s1", "method": "voices.sample", "params": {},
            "thread_id": None, "data_dir": "/tmp/promo-flow-data",
        })
        assert started.wait(2)
        deadline = time.time() + 1.0
        sample_prog = []
        while time.time() < deadline:
            sample_prog = [x for x in snapshot() if x.get("type") == "job.progress" and x.get("job") == "s1"]
            if any(x.get("pct") == 40 and x.get("note") == "Cloning" for x in sample_prog) and len(sample_prog) >= 3:
                break
            time.sleep(0.02)
        else:
            raise AssertionError(sample_prog)
        assert all(x.get("pct") in (0, 40) for x in sample_prog)

        send({"type": "job.cancel", "job": "s1"})
        send({
            "type": "job.start", "job": "l1", "method": "voices.list", "params": {},
            "thread_id": None, "data_dir": "/tmp/promo-flow-data",
        })
        send({
            "type": "job.start", "job": "sv", "method": "voices.save", "params": {},
            "thread_id": None, "data_dir": "/tmp/promo-flow-data",
        })
        send({"type": "call", "id": "c1", "method": "voices.list", "params": {}})
        send({"type": "event", "id": 7})
        send({"type": "hello"})
        send({"type": "job.cancel", "job": "nope"})

        deadline = time.time() + 2
        snap = []
        while time.time() < deadline:
            snap = snapshot()
            list_ok = any(
                x.get("type") == "job.result" and x.get("job") == "l1" and x.get("ok") is True
                and x.get("value") == [{"id": "ada"}] for x in snap
            )
            save_ok = any(
                x.get("type") == "job.result" and x.get("job") == "sv" and x.get("ok") is False
                and x.get("error") == {"code": "voices.too_short", "message": "script audio is 29 s"}
                for x in snap
            )
            call_ok = any(x.get("type") == "result" and x.get("id") == "c1" and x.get("ok") is True for x in snap)
            reply_ok = any(x.get("type") == "reply" and x.get("id") == 7 and x.get("publish") == [] for x in snap)
            if list_ok and save_ok and call_ok and reply_ok:
                break
            time.sleep(0.02)
        else:
            raise AssertionError(snap)

        assert [x for x in snap if x.get("type") == "reply"] == [{"type": "reply", "id": 7, "publish": []}]
        sample_ident = next(ident for method, ident in idents if method == "voices.sample")
        list_ident = next(ident for method, ident in idents if method == "voices.list")
        assert sample_ident != list_ident
        assert not release.is_set()

        release.set()
        deadline = time.time() + 2
        while time.time() < deadline:
            with worker._jobs_lock:
                gone = "s1" not in worker._jobs
            if gone:
                break
            time.sleep(0.02)
        assert gone
        assert not any(x.get("type") == "job.result" and x.get("job") == "s1" for x in snapshot())
    finally:
        release.set()
        try:
            os.close(write_fd)
        except OSError:
            pass
        reader.join(3)
        stdin.close()
        assert not reader.is_alive()
