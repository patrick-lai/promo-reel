"""Stills while a build runs: the quick look (start / middle / end of every shot before any encoding), the live stills of the real render, the
filmstrip, and the job record that carries them to the Stage without ever blocking the render."""
import json
import os
import subprocess
import threading
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from PIL import Image

from promo import cli
from promo import editor as E
from promo import flowjob as FJ
from promo import livestills as LV
from promo import render as R
from promo.spec import load_spec

from test_editor import project

pytestmark = pytest.mark.skipif(subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0, reason="needs ffmpeg")


def counting_clip(path, secs=5, fps=30, size="320x180"):
    """A clip whose frame k is grey level 2k: a still tells which source frame it came from."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={size}:r={fps}:d={secs}", "-vf", "geq=lum='min(2*N,255)':cb=128:cr=128",
                    "-c:v", "libx264", "-qp", "0", "-pix_fmt", "yuv444p", path], check=True)


@pytest.fixture
def pd(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMO_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setenv("PROMO_HEAVY_LOCK", str(tmp_path / "heavy.lock"))
    monkeypatch.delenv("COMMISSION_THREAD_TOKEN", raising=False)
    d = project(str(tmp_path / "projects"))
    mp = os.path.join(d, "footage", "manifest.yaml")
    man = yaml.safe_load(open(mp))
    for c in man["clips"]:
        counting_clip(c["path"])
        c["sha256"] = E._sha_file(c["path"])
    yaml.safe_dump(man, open(mp, "w"), sort_keys=False)
    import soundfile as sf
    tone = 0.1 * np.sin(np.linspace(0, 440 * 6.28 * 10, 48000 * 10)).astype("float32")
    sf.write(os.path.join(d, "media", "music", "a.wav"), np.stack([tone, tone], 1), 48000)      # the music edit wants a stereo bed as long as the cut
    sp = os.path.join(d, "promo.yaml")
    raw = yaml.safe_load(open(sp))
    for sh in raw["shots"]:
        sh["cam"] = [[0, 0.5, 0.5, 1.0]]
        sh.pop("overlays", None)                   # captions need the Linux box's variable Inter font
    yaml.safe_dump(raw, open(sp, "w"), sort_keys=False)
    return d


def spec_of(pd):
    return load_spec(os.path.join(pd, "promo.yaml"))


def grey(path):
    return float(np.asarray(Image.open(path).convert("L")).mean())


def test_picks_are_first_middle_last_and_a_tiny_shot_keeps_distinct_frames():
    assert LV.picks(120) == {0: "a", 60: "b", 119: "c"}
    assert LV.picks(2) == {0: "a", 1: "b"}
    assert LV.picks(1) == {0: "a"}


def test_quick_look_draws_start_middle_end_of_every_shot_and_encodes_nothing(pd):
    spec = spec_of(pd)
    r = LV.quick_look(spec, spec.shots)
    assert r["made"] == ["01", "02"] and r["skipped"] == []
    for sid in ("01", "02"):
        for w in "abc":
            assert os.path.isfile(LV.still_path(spec, sid, w))
    assert not os.path.isdir(spec.segs_dir) or not os.listdir(spec.segs_dir)       # no segment, no .partial
    # the source is read where the frame sits: shot 01 starts at t_in 0, its end frame (119) is ~4 s into the take, so much brighter
    assert grey(LV.still_path(spec, "01", "a")) < 30 < grey(LV.still_path(spec, "01", "c"))
    idx = LV.load_index(spec)
    assert idx["01"]["look"] is True and idx["01"]["c"]["t"] == pytest.approx(119 / 30, abs=0.01)
    strip = Image.open(r["strip"])
    assert strip.width > 3 * LV.TILE_W and strip.height > 2 * LV.HEAD


def test_a_shot_that_cannot_be_sampled_is_listed_and_the_rest_carry_on(pd, monkeypatch):
    spec = spec_of(pd)
    from promo import shots as S

    class Broken:
        def render(self, ctx, shot):
            raise ValueError("bad overlay")

    class Hosts:
        def render(self, ctx, shot):
            if R.sampling():
                raise R.NotYet("the hosts are not rendered yet")
    kinds = iter([Broken(), Hosts()])
    monkeypatch.setattr(S, "get_type", lambda t: next(kinds))
    r = LV.quick_look(spec, spec.shots, log=lambda m: None)
    assert r["made"] == [] and [s["id"] for s in r["skipped"]] == ["01", "02"]
    assert "bad overlay" in r["skipped"][0]["why"] and r["skipped"][1]["why"] == "the hosts are not rendered yet"
    assert r["strip"] is None
    assert R.PREVIEW is None                       # never left behind for the real render


def test_will_render_matches_run_step_and_touches_nothing(pd):
    spec = spec_of(pd)
    st = next(s for s in cli.plan(spec) if s["name"] == "shot 01")
    args = SimpleNamespace(force=False)
    assert cli.will_render(spec, args, st) is True
    dig = st["dig"]()
    mp4, _ = cli._seg_cache(st, dig)
    os.makedirs(os.path.dirname(mp4), exist_ok=True)
    open(mp4, "wb").write(b"cached render")
    os.utime(mp4, (1_000_000_000, 1_000_000_000))
    assert cli.will_render(spec, args, st) is False                     # run_step would take it from the cache
    assert os.path.getmtime(mp4) == 1_000_000_000 and not os.path.exists(spec.seg_path("01"))
    assert cli.will_render(spec, SimpleNamespace(force=True), st) is True
    os.remove(mp4)
    os.makedirs(spec.segs_dir, exist_ok=True)
    open(spec.seg_path("01"), "wb").write(b"seg")
    stamps = cli.Stamps(spec.build)
    stamps.write(st["key"], dig)
    before = open(stamps._p(st["key"])).read()
    assert cli.will_render(spec, args, st) is False                     # fresh
    assert open(stamps._p(st["key"])).read() == before                 # and the stamp is not rewritten


def test_layer_reader_at_skips_to_the_frame_asked_for(tmp_path):
    from promo.shots.livestream import LayerReader
    p = str(tmp_path / "layer.mov")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=16x16:r=10:d=2", "-vf", "format=rgba,geq=r='N*10':g='N*10':b='N*10':a=255",
                    "-c:v", "png", p], check=True)
    r = LayerReader(p, 16, 16, 0, 10)
    try:
        lum = lambda im: float(np.asarray(im.convert("L")).mean())  # noqa: E731
        assert lum(r.at(0)) == pytest.approx(0, abs=2)
        assert lum(r.at(10)) == pytest.approx(100, abs=3)              # frame 10, not frame 1
        assert lum(r.at(10)) == pytest.approx(100, abs=3)              # asking again does not move on
        assert lum(r.at(19)) == pytest.approx(190, abs=3)
    finally:
        r.close()


def test_job_preview_never_waits_for_the_lock_and_wakes_the_heartbeat(tmp_path):
    wrote = threading.Event()
    job = FJ.Job(str(tmp_path), "build", "Building the video", [dict(id="shot 01", label="Shot 01")], 1, on_change=wrote.set, beat_s=3600)
    wrote.clear()
    job.lock.acquire()                   # a publish in progress holds the job lock (it can for minutes)
    t = threading.Thread(target=lambda: (job.preview(dict(id="01", label="Shot 01", frac=0.5, which="b", still=str(tmp_path / "01-b.jpg"),
                                                          strip=str(tmp_path / "strip.jpg"), look=False)),
                                         job.preview(dict(id="01", label="Shot 01", frac=0.6))))
    t.start()
    t.join(5)
    assert not t.is_alive()              # the render loop went on while the lock was held
    assert job.d["now"]["which"] == "b" and job.d["now"]["frac"] == 0.6      # a progress tick keeps the still
    job.lock.release()
    assert wrote.wait(5)                 # the still woke the heartbeat: no waiting out the hour-long beat
    j = FJ.load(str(tmp_path))
    assert j["now"]["id"] == "01" and j["strip"].endswith("strip.jpg")
    job.preview(dict(id="02", label="Shot 02", frac=0.01))
    assert "which" not in job.d["now"]                                  # a new shot does not show the last one's still
    job.item("shot 02", None, None)
    assert job.d["now"] is None and job.d["strip"].endswith("strip.jpg")    # a finished shot is no longer "being drawn"; the strip stays
    job.close()
    assert FJ.load(str(tmp_path))["now"] is None


def test_a_real_build_shows_start_middle_end_of_the_shot_before_it_finishes(pd, monkeypatch):
    spec = spec_of(pd)
    events = []
    real_preview, real_item = FJ.Job.preview, FJ.Job.item

    def preview(self, now):
        events.append(("now", now.get("id"), now.get("which"), now.get("frac"), now.get("look")))
        return real_preview(self, now)

    def item(self, iid, path, error, skipped=False):
        events.append(("item", iid))
        return real_item(self, iid, path, error, skipped)
    monkeypatch.setattr(FJ.Job, "preview", preview)
    monkeypatch.setattr(FJ.Job, "item", item)
    assert cli.main(["-p", os.path.join(pd, "promo.yaml"), "build", "--shots", "01"]) == 0
    stills = [e for e in events if e[0] == "now" and e[2]]
    look = [e for e in stills if e[4]]
    live = [e for e in stills if not e[4]]
    assert [e[2] for e in look] == ["a", "b", "c"] and [e[2] for e in live] == ["a", "b", "c"]
    assert [e[3] for e in live] == sorted(e[3] for e in live) and live[-1][3] == 1.0
    order = [e[0] + str(e[1]) for e in events]
    assert order.index("itemlook") < order.index("now01") + len(look) + 1 < order.index("itemshot 01")   # quick look, then live stills, then the shot is done
    assert os.path.isfile(spec.seg_path("01"))
    assert LV.load_index(spec)["01"]["look"] is False
    j = FJ.load(os.path.join(pd, "flow"))
    ids = [x["id"] for x in j["items"]]
    assert ids[:2] == ["checks", "look"] and "shot 01" in ids and j["strip"].endswith("strip.jpg") and j["now"] is None
    # a second build: shot 01 is fresh, so nothing to look at and nothing renders
    events.clear()
    assert cli.main(["-p", os.path.join(pd, "promo.yaml"), "build", "--shots", "01"]) == 0
    assert not [e for e in events if e[0] == "now"]


def test_promo_strip_writes_the_image_and_says_why_when_it_cannot(pd, tmp_path, capsys):
    p = os.path.join(pd, "promo.yaml")
    assert cli.main(["-p", p, "strip"]) == 1
    assert "no stills yet" in capsys.readouterr().err
    assert cli.main(["-p", p, "strip", "--shots", "99"]) == 2
    assert "unknown shot 99" in capsys.readouterr().err
    assert cli.main(["-p", p, "build", "--look"]) == 0
    assert not os.path.exists(spec_of(pd).seg_path("01"))            # --look renders nothing
    out = str(tmp_path / "shots" / "strip.png")
    capsys.readouterr()
    assert cli.main(["-p", p, "strip", "--shots", "02", "--out", out, "--json"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["ok"] and r["path"] == out and list(r["shots"]) == ["02"] and r["shots"]["02"]["look"] is True
    assert Image.open(out).format == "PNG" and Image.open(out).height < Image.open(LV.strip_path(spec_of(pd))).height
