"""promo compare-ref: reference row above draft row, metrics incl. speech/LUFS/tempo, factual gaps (tiny videos, fake ASR)."""
import json
import os
import sys
import tempfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from test_refs import FAKE_TR, INTENT, FakeASR, tiny_video  # noqa: E402

from promo import brief as BR  # noqa: E402
from promo import cli  # noqa: E402
from promo import compare_ref as CR  # noqa: E402
from promo import refs as RF  # noqa: E402


def setup(draft_audio=False):
    d = os.path.join(tempfile.mkdtemp(), "projects", "p")
    BR.init(d, INTENT)
    tmp = tempfile.mkdtemp()
    ref = tiny_video(os.path.join(tmp, "film.mp4"), audio=True, secs=4.0)
    with FakeASR():
        RF.add(ref, d, rid="film", why="the user's words")
    b = BR.load(d)
    b["references"][0]["people"] = True
    BR.save(d, b)
    draft = tiny_video(os.path.join(tmp, "draft.mp4"), audio=draft_audio, secs=3.0)
    return d, draft


def test_sheet_two_rows_and_metrics_with_speech_gap():
    d, draft = setup(draft_audio=False)
    r = CR.compare(draft, d, n=6, draft_people=False)
    x = r["results"][0]
    png = os.path.join(d, "out", "compare", "film-vs-draft.png")
    assert x["sheet"] == png and os.path.isfile(png)
    im = Image.open(png)
    assert im.width == 6 * 320 and im.height >= 2 * (180 + 22)               # two labelled rows
    ref, dr = x["reference"], x["draft"]
    assert ref["words"] == 10 and ref["has_audio"] and ref["duration"] == 4.0 and ref["lufs"] is not None
    assert dr["words"] == 0 and not dr["has_audio"] and dr["duration"] == 3.0 and dr["n_cuts"] >= 1
    assert "reference has speech (10 words), draft has none" in x["gaps"]
    assert "reference has an audio track, draft has none" in x["gaps"]
    assert "reference has people, draft has none" in x["gaps"]
    md = open(os.path.join(d, "out", "compare", "film-vs-draft.md")).read()
    assert "| speech present | yes, 10 words | no |" in md and "| people present (manual) | yes | no |" in md
    assert json.load(open(os.path.join(d, "out", "compare", "film-vs-draft.json")))["people"] == dict(reference=True, draft=False)


def test_draft_with_voice_measured_through_injected_asr_and_people_is_manual():
    d, draft = setup(draft_audio=True)
    calls = []

    def asr(wav):
        calls.append(str(wav))
        return dict(engine="fake", segments=[dict(start=0, end=1, text="one two three")])
    r = CR.compare(draft, d, n=4, transcribe=asr)
    x = r["results"][0]
    assert len(calls) == 1 and x["draft"]["words"] == 3 and x["draft"]["has_audio"]
    assert not any("reference has speech" in g for g in x["gaps"])
    assert any(g.startswith("people present: MANUAL") for g in x["gaps"])     # draft flag not given


def test_asr_off_reads_unknown_not_silence():
    d, draft = setup(draft_audio=True)
    os.environ["PROMO_WATCH_ASR"] = "0"
    try:
        x = CR.compare(draft, d, n=3, draft_people=True)["results"][0]
    finally:
        del os.environ["PROMO_WATCH_ASR"]
    assert x["draft"]["words"] is None
    assert any("speech could not be measured" in g for g in x["gaps"])
    assert "| speech present | yes, 10 words | unknown |" in open(os.path.join(d, "out", "compare", "film-vs-draft.md")).read()


def test_errors_and_cli():
    d, draft = setup()
    for bad in (lambda: CR.compare("/nope.mp4", d), lambda: CR.compare(draft, d, only="zzz")):
        try:
            bad()
            raise AssertionError("no error")
        except CR.CompareError:
            pass
    assert cli.main(["compare-ref", draft, "--project", d, "--n", "3", "--draft-people", "no"]) == 0
    assert cli.main(["compare-ref", "/nope.mp4", "--project", d]) == 2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
