"""`promo listen` (promo/listen.py): the local detectors, and the ear / compare against a fake OpenRouter (no network)."""
import json
import os
import sys

import numpy as np
import pytest
import soundfile as sf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from promo import listen as L  # noqa: E402
from promo import openrouter as OR  # noqa: E402
SR = 48000


def voice_like():
    """3 s of 'speech': 0.6 s harmonic bursts with soft edges and real silences. Random phases: zero-phase harmonics add up to a pulse
    train, which is a click every period."""
    t = np.arange(3 * SR) / SR
    rng = np.random.default_rng(0)
    x = sum(np.sin(2 * np.pi * 130 * h * t + rng.uniform(0, 2 * np.pi)) / h for h in range(1, 40))
    gate = ((t % 1.0) < 0.6).astype(float)
    return x * np.convolve(gate, np.ones(480) / 480, mode="same") * 0.15 + rng.standard_normal(len(t)) * 1e-5, gate

MODEL = {"id": L.DEFAULT_MODEL, "pricing": {"prompt": "0.000001", "audio": "0.000001", "completion": "0.000004"}}


def write(tmp_path, name, x):
    p = str(tmp_path / name)
    sf.write(p, x.astype(np.float32), SR)
    return p


def test_local_detectors_find_a_clip_a_click_and_dead_air_and_nothing_on_a_clean_take(tmp_path):
    x, _ = voice_like()
    clean = L.hear_locally(L.file_windows(write(tmp_path, "clean.wav", x)))[0]
    assert clean["findings"] == [], clean["findings"]
    y = x.copy()
    y[int(0.2 * SR): int(0.4 * SR)] = np.clip(y[int(0.2 * SR): int(0.4 * SR)] * 8, -0.5, 0.5)     # clipped at 0.5, not at full scale
    y[int(1.3 * SR): int(1.3 * SR) + 96] += np.random.default_rng(1).uniform(-0.9, 0.9, 96)       # a 2 ms click in a word
    y = np.concatenate([y[: int(2.3 * SR)], np.zeros(int(1.5 * SR)), y[int(2.3 * SR):]])             # 1.5 s of dead air between words
    w = L.hear_locally(L.file_windows(write(tmp_path, "bad.wav", y)))[0]
    got = {(f["issue"], round(f["t0"], 1)) for f in w["findings"]}
    assert {("clipping", 0.2), ("artifact", 1.3)} <= got and any(i == "pacing" and 2.3 <= t <= 2.5 for i, t in got), got


class FakeEar:
    """/chat/completions answers from a script, one per call; counts the calls."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), 0

    def __call__(self, method, path, body=None, auth=True, raw=False, timeout=60, headers_out=None):
        if path.startswith("/models"):
            return {"data": [MODEL]}
        self.calls += 1
        ans = self.answers.pop(0)
        if ans == "length":
            return {"id": "gen-x", "choices": [{"finish_reason": "length", "message": {"content": '{"heard": "Sm'}}], "usage": {"cost": 0.001}}
        return {"id": f"gen-{self.calls}", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(ans)}}], "usage": {"cost": 0.002}}


def answer(*findings, heard="small decisions made fast"):
    return {"heard": heard, "findings": [dict(t0=t, t1=t + 0.5, issue=i, severity=s, note="n", fix="f") for i, t, s in findings],
            "scores": {"naturalness": 4, "clarity": 5, "balance": 5, "polish": 4}}


@pytest.fixture
def ear(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def use(*answers):
        fake = FakeEar(answers)
        monkeypatch.setattr(OR, "_request", fake)
        return fake
    return use


def test_ear_keeps_what_every_run_heard_diffs_the_script_and_caches(tmp_path, ear):
    x, _ = voice_like()
    path = write(tmp_path, "line.wav", x)
    fake = ear(answer(("robotic", 0.5, 2), ("noise", 2.0, 1)), answer(("robotic", 0.7, 2)))
    w = L.hear_locally(L.file_windows(path))
    w[0]["text"] = "Small decisions, made fast, and always yours to override."
    L.ear(w, runs=2, log=lambda *a: None)
    f = {x["issue"]: x for x in w[0]["findings"]}
    assert f["robotic"]["solid"] and f["robotic"]["seen"] == "2/2" and not f["noise"]["solid"]
    assert "always yours to override" in f["mispronounced"]["note"], "script words the ear did not hear"
    assert OR.spend()["today"] == pytest.approx(0.004), "the billed cost of each call is in the ledger"
    again = L.hear_locally(L.file_windows(path))
    L.ear(again, runs=2, log=lambda *a: None)
    assert fake.calls == 2, "the same request again comes from the cache"


def test_ear_refuses_a_cut_answer_and_a_job_over_its_cap(tmp_path, ear):
    x, _ = voice_like()
    w = L.hear_locally(L.file_windows(write(tmp_path, "line.wav", x)))
    ear("length")
    with pytest.raises(OR.OpenRouterError, match="ran out of room"):
        L.ear(w, runs=1, log=lambda *a: None)
    with pytest.raises(OR.OpenRouterError, match="over the"):
        L.ear(w, runs=1, max_usd=0.0001, log=lambda *a: None)


def test_compare_names_a_winner_only_when_both_orders_agree(tmp_path, ear):
    x, _ = voice_like()
    a, b = write(tmp_path, "a.wav", x), write(tmp_path, "b.wav", x * 0.5)
    ab = lambda better: {"better": better, "why": "w", "decisive_defect": "d"}  # noqa: E731
    ear(ab("first"), ab("second"))                       # A first: A; B first: A again
    assert L.compare(a, b)["winner"] == "A"
    c = write(tmp_path, "c.wav", x * 0.25)               # a new pair: the first one's answers are cached
    ear(ab("first"), ab("first"))                        # each order prefers whatever played first: position, not sound
    assert L.compare(a, c)["winner"] == "unsure"
