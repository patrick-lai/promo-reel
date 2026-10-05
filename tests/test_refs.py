"""promo refs: watch WITH transcript -> DOSSIER.md scaffold -> completeness gate (tiny generated video, fake ASR, no network)."""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from promo import brief as BR  # noqa: E402
from promo import cli  # noqa: E402
from promo import refs as RF  # noqa: E402
from promo import watch as W  # noqa: E402

FAKE_TR = dict(engine="fake", segments=[
    dict(start=0.2, end=1.0, text="We should have told her.", words=[dict(w=x, start=0.2, end=0.4) for x in "We should have told her.".split()]),
    dict(start=1.5, end=2.5, text="It is too late now.", words=[dict(w=x, start=1.5, end=1.7) for x in "It is too late now.".split()])])
INTENT = "Make it feel like this short film: two people, a real conversation, quiet piano."


def tiny_video(path, audio=True, secs=3.0):
    """Red then testsrc2 (one cut) with a sine track."""
    h = secs / 2
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=red:s=320x180:d={h}:r=10",
           "-f", "lavfi", "-i", f"testsrc2=s=320x180:d={h}:r=10"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:d={secs}"]
    cmd += ["-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]"] + (["-map", "2:a", "-c:a", "aac"] if audio else []) + \
           ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-threads", "2", path]
    subprocess.run(cmd, check=True)
    return path


class FakeASR:
    """Patches promo.watch.transcribe for the duration of a with-block."""
    def __init__(self, tr=FAKE_TR):
        self.tr, self.old = tr, None

    def __enter__(self):
        self.old = W.transcribe
        W.transcribe = lambda wav: self.tr
        return self

    def __exit__(self, *a):
        W.transcribe = self.old


def project():
    d = os.path.join(tempfile.mkdtemp(), "projects", "p")
    BR.init(d, INTENT)
    return d


def fill(dossier):
    """Do what a diligent agent does: replace every TODO with content, tick every box, name the stills."""
    t = open(dossier).read()
    t = re.sub(r"^TODO: .*$", "0:00-0:01 a red wall, then a test card; two voices; read all sheets.", t, flags=re.M)
    t = t.replace("- [ ]", "- [x]")
    t = re.sub(r"(\d+ full-res stills examined.*?: )$", r"\1cuts/cut-001.jpg cuts/cut-002.jpg", t, flags=re.M)
    open(dossier, "w").write(t)


def test_add_watches_with_transcript_and_scaffolds_dossier():
    d = project()
    v = tiny_video(os.path.join(tempfile.mkdtemp(), "short.mp4"))
    with FakeASR():
        r = RF.add(v, d, rid="short", why="the user: 'the kitchen scene, exactly'")
    rd = RF.ref_dir(d, "short")
    for f in ("watch.json", "WATCH.md", "transcript.json", "audio.wav", "DOSSIER.md"):
        assert os.path.isfile(os.path.join(rd, f)), f
    assert os.path.isdir(os.path.join(rd, "sheets")) and os.listdir(os.path.join(rd, "sheets"))
    assert r["words"] == 10 and not r["warnings"] and r["cuts"] >= 1
    txt = open(r["dossier"]).read()
    for _k, head, _g in RF.SECTIONS:
        assert head in txt, head
    assert txt.count("TODO:") == len(RF.SECTIONS) and "- [ ] transcript.json read in full (10 words)" in txt
    assert "- [ ] contact sheet read: sheets/sheet-01.png" in txt
    b = BR.load(d)                                                       # listed in the brief with the user's words
    assert b["references"] == [dict(id="short", path=v, why="the user: 'the kitchen scene, exactly'")]
    try:
        RF.add(v, d, rid="short")                                        # never clobber a filled-in dossier
        raise AssertionError("overwrote")
    except RF.RefsError:
        pass


def test_check_fails_until_every_section_is_real_and_every_box_ticked():
    d = project()
    v = tiny_video(os.path.join(tempfile.mkdtemp(), "short.mp4"))
    with FakeASR():
        RF.add(v, d, rid="short", why="their words")
    row = RF.check(d)[0]
    assert row[1] == "FAIL" and f"{len(RF.SECTIONS)} `TODO:` marker(s)" in row[2] and "unticked" in row[2]
    fill(os.path.join(RF.ref_dir(d, "short"), "DOSSIER.md"))
    row = RF.check(d)[0]
    assert row[1] == "PASS", row
    # a section emptied -> FAIL; stills claimed but not named -> FAIL; unticked -> FAIL
    p = os.path.join(RF.ref_dir(d, "short"), "DOSSIER.md")
    good = open(p).read()
    open(p, "w").write(good.replace("0:00-0:01 a red wall, then a test card; two voices; read all sheets.", "x", 1))
    assert "is empty" in RF.check(d)[0][2]
    open(p, "w").write(good.replace("cuts/cut-001.jpg cuts/cut-002.jpg", ""))
    assert "names 0" in RF.check(d)[0][2]
    open(p, "w").write(good.replace("- [x] transcript", "- [ ] transcript", 1))
    assert "unticked" in RF.check(d)[0][2]
    open(p, "w").write(good)
    assert RF.check(d)[0][1] == "PASS"


def test_missing_dossier_artefacts_and_transcript_fail():
    d = project()
    b = BR.load(d)
    b["references"] = [dict(id="ghost", url="https://example.org/v", why="w")]
    BR.save(d, b)
    row = RF.check(d)[0]
    assert row[1] == "FAIL" and "no dossier" in row[2]
    # watched with ASR explicitly off: add WARNs, check FAILs on the missing transcript
    v = tiny_video(os.path.join(tempfile.mkdtemp(), "short.mp4"))
    os.environ["PROMO_WATCH_ASR"] = "0"
    try:
        r = RF.add(v, d, rid="mute", why="w")
    finally:
        del os.environ["PROMO_WATCH_ASR"]
    assert any("PROMO_WATCH_ASR=0" in w for w in r["warnings"]) and not os.path.exists(os.path.join(r["dir"], "transcript.json"))
    fill(r["dossier"])
    msg = RF.check(d)[0][2]
    assert "mute: transcript.json missing" in msg
    # a hand-written transcript (after listening) satisfies it
    json.dump(dict(engine="manual", segments=[]), open(os.path.join(r["dir"], "transcript.json"), "w"))
    assert "mute: transcript" not in RF.check(d)[0][2]
    # missing sheets
    import shutil
    shutil.rmtree(os.path.join(r["dir"], "sheets"))
    assert "contact sheets missing" in RF.check(d)[0][2]


def test_not_transferable_items_need_conflict_entries():
    d = project()
    v = tiny_video(os.path.join(tempfile.mkdtemp(), "short.mp4"))
    with FakeASR():
        r = RF.add(v, d, rid="short", why="w")
    fill(r["dossier"])
    t = open(r["dossier"]).read()
    t = t.replace("## 11. What is NOT transferable and why\n\n0:00-0:01 a red wall, then a test card; two voices; read all sheets.",
                  "## 11. What is NOT transferable and why\n\n- actors and scripted dialogue vs real footage only\n- a score by a live pianist")
    assert "actors and scripted" in t
    open(r["dossier"], "w").write(t)
    assert "2 NOT-transferable item(s) but 0 conflict(s)" in RF.check(d)[0][2]
    BR.add_conflict(d, "actors", "AGENTS.md 0.1", ref="short")
    assert "2 NOT-transferable item(s) but 1" in RF.check(d)[0][2]
    BR.add_conflict(d, "pianist", "assets licence", ref="short")
    assert RF.check(d)[0][1] == "PASS"                                   # (the brief gate separately FAILs while they are pending)
    assert BR.check(d)[0][1] == "FAIL"


def test_cli_check_exit_codes_and_gates_wiring():
    d = project()
    v = tiny_video(os.path.join(tempfile.mkdtemp(), "short.mp4"))
    with FakeASR():
        RF.add(v, d, rid="short", why="w")
    assert cli.main(["refs", "check", "--project", d]) == 1
    fill(os.path.join(RF.ref_dir(d, "short"), "DOSSIER.md"))
    assert cli.main(["refs", "check", "--project", d]) == 0
    assert cli.main(["refs", "show", "--project", d]) == 0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
