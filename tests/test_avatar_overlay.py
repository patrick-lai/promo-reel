import subprocess
from types import SimpleNamespace

from PIL import Image

from promo import render as R
from promo.overlays import build_overlays


def _clip(path):
    """1 s red then 1 s blue, 64x64 at 25 fps."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=64x64:r=25:d=1", "-f", "lavfi", "-i", "color=blue:s=64x64:r=25:d=1",
                    "-filter_complex", "[0][1]concat=n=2:v=1", "-pix_fmt", "yuv420p", str(path)], check=True)


def test_avatar_plays_its_clip_from_t_in_in_the_corner(tmp_path):
    clip = tmp_path / "me.mp4"
    _clip(clip)
    ctx = R.RenderContext(K=1, fps=30, spec=SimpleNamespace(footage_path=lambda cid: str(clip)))
    first, later = build_overlays(ctx, [{"type": "avatar", "source": "me", "t_in": 0.0},
                                        {"type": "avatar", "source": "me", "t_in": 1.0}])
    black = Image.new("RGB", (ctx.OW, ctx.OH))
    corner = (ctx.OW - 32 - 140, ctx.OH - 32 - 140)            # inside the default bottom-right card (h 0.26, margin 0.03)
    r, g, b = first.apply(black, 0.5).convert("RGB").getpixel(corner)
    assert r > 180 and b < 80
    r, g, b = first.apply(black, 1.5).convert("RGB").getpixel(corner)   # the clip advances with shot time
    assert b > 180 and r < 80
    r, g, b = later.apply(black, 0.2).convert("RGB").getpixel(corner)   # a later shot picks the take up at its t_in
    assert b > 180 and r < 80
    assert first.apply(black, 0.5).convert("RGB").getpixel((40, 40)) == (0, 0, 0)
