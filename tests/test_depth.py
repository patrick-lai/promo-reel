import json
import os
import shutil

import numpy as np
import pytest
from PIL import Image

from promo import depth as D
from promo import flow as F
from promo import genvideo as G
from promo import studio as STU

from test_openrouter import api, proj  # noqa: F401  (fixtures: a fake OpenRouter and a flow project with a generated scene)

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is needed")


def plate(path, w=64, h=36, generated=True):
    rng = np.random.default_rng(1)
    Image.fromarray(rng.integers(0, 255, (h, w, 3), dtype=np.uint8)).save(path)
    if generated:
        open(str(path) + ".gen.json", "w").write(json.dumps(dict(generated=True, kind="image")))
    return str(path)


def halves(h, w):
    """Far (0) on top, near (1) at the bottom."""
    d = np.zeros((h, w), np.float32)
    d[h // 2:] = 1
    return d


def test_near_pixels_move_and_the_focus_depth_stays_put(tmp_path):
    img = Image.open(plate(tmp_path / "p.png"))
    fr = list(D.frames(img, halves(36, 64), 5, "pan_left", amount=2, focus=0.0))
    first, last = fr[0].astype(int), fr[-1].astype(int)
    assert np.abs(first[:12] - last[:12]).mean() < 0.5                 # far rows sit on the focus plane (the softened depth's tail rounds by 1)
    assert np.abs(first[24:] - last[24:]).mean() > 10                   # near rows slide
    still = list(D.frames(img, halves(36, 64), 3, "static"))
    assert all((f == still[0]).all() for f in still)


@needs_ffmpeg
def test_a_parallax_clip_has_its_own_generated_sidecar_and_a_screenshot_is_refused(tmp_path):
    src = plate(tmp_path / "plate.png")
    seen = []
    meta = D.parallax(src, tmp_path / "out.mp4", seconds=1, move="orbit", size=(64, 36), fps=10, depth=halves(36, 64), on_progress=lambda i, n: seen.append(i))
    side = json.loads((tmp_path / "out.mp4.gen.json").read_text())
    assert side == meta and meta["generated"] is True and meta["provider"] == "local:depth-parallax" and meta["cost_usd"] == 0
    assert (meta["width"], meta["height"]) == (64, 36) and meta["source"] == os.path.abspath(src) and seen[-1] == 10
    shot = plate(tmp_path / "screenshot.png", generated=False)
    with pytest.raises(D.DepthError, match="not a generated plate"):
        D.parallax(shot, tmp_path / "x.mp4", size=(64, 36), depth=halves(36, 64))
    D.parallax(shot, tmp_path / "x.mp4", seconds=0.2, size=(64, 36), fps=10, depth=halves(36, 64), trusted=True)
    assert (tmp_path / "x.mp4").exists()
    with pytest.raises(D.DepthError, match="no move 'spin'"):
        D.parallax(src, tmp_path / "y.mp4", move="spin", size=(64, 36), depth=halves(36, 64))


@needs_ffmpeg
def test_a_studio_depth_take_moves_a_storyboard_frame_for_free(api, proj, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(D, "available", lambda: True)
    monkeypatch.setattr(D, "estimate", lambda img: halves(img.height, img.width))
    monkeypatch.setattr(STU, "HEIGHT", dict(STU.HEIGHT, **{"720p": 36, "1080p": 54}))   # tiny renders: the test is about the plumbing
    monkeypatch.setattr(G, "probe_media", lambda p: {"width": 64, "height": 36, "duration": 2.0})
    model = next(m for m in F.snapshot(proj)["studio"]["models"] if m["id"] == STU.DEPTH)
    assert model["needs_frame"] and model["prompt"] is False and model["local"]
    assert F.main(["--project", proj, "studio", "run", "--model", STU.DEPTH, "--seconds", "2", "--res", "720p", "--start", "A/01/start", "--preset", "orbit"]) == 0
    t = STU.load(proj)[0]
    assert t["status"] == "done" and t["cost"] == 0 and t["progress"] is None and t["start_plate"] is True
    assert json.loads(open(os.path.join(proj, t["file"] + ".gen.json")).read())["move"] == "orbit"
    assert api.sent == []
    assert F.main(["--project", proj, "studio", "rerun", "--take", "t1", "--res", "1080p"]) == 0           # the free final: no request, its settings again
    t2 = STU.load(proj)[1]
    assert t2["status"] == "done" and t2["resolution"] == "1080p" and t2["start_plate"] and t2["preset"] == "orbit"
    assert F.main(["--project", proj, "studio", "run", "--model", STU.DEPTH]) == 1                       # no start frame
    loose = plate(tmp_path / "loose.png", generated=False)
    assert F.main(["--project", proj, "studio", "run", "--model", STU.DEPTH, "--start", loose]) == 1
    assert "not a generated plate" in STU.load(proj)[-1]["error"]


def test_the_real_model_finds_the_near_side_when_it_is_cached(tmp_path):
    try:
        from huggingface_hub import hf_hub_download
        hf_hub_download(D.REPO, D.MODEL_FILE, revision=D.REVISION, local_files_only=True)
    except (ImportError, OSError):         # not downloaded on this box (or no huggingface_hub): nothing to check offline
        pytest.skip("the depth model is not in the Hugging Face cache")
    w, h = 320, 180                        # a floor in perspective: bright stripes widening towards the bottom read as near
    yy = np.linspace(0, 1, h)[:, None]
    img = np.zeros((h, w, 3), np.uint8)
    img[...] = (40 + 180 * yy).astype(np.uint8)[..., None]
    img[(np.sin(np.linspace(0, 1, w)[None, :] * 40 / (0.2 + yy)) > 0)] //= 2
    d = D.estimate(Image.fromarray(img))
    assert d.shape == (h, w) and d[-20:].mean() > d[:20].mean()
