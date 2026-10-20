"""Mesh avatar hosts (promo.mesh_avatar behind promo.live2d): registration + licence / likeness gate, the performance ->
runtime parameter mapping, and (with PROMO_TEST_MESH_AVATAR = a built Mesh Avatar Studio project) a real render."""
import json
import os
import shutil
import sys

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo import live2d as L2  # noqa: E402
from promo import mesh_avatar as MA  # noqa: E402


def _fake_avatar(d):
    from PIL import Image
    (d / "built").mkdir(parents=True)
    (d / "rig.json").write_text(json.dumps({"version": 1, "image": {"width": 400, "height": 560}}))
    (d / "built" / "layers.json").write_text(json.dumps({"build": "b1", "layers": {}}))
    base = Image.new("RGBA", (400, 560), (0, 0, 0, 0))
    base.paste((200, 150, 120, 255), (100, 200, 300, 560))      # a bust cut by the picture's bottom edge
    base.save(d / "built" / "base.png")
    return d


def test_mesh_avatar_registers_behind_the_same_licence_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMO_LIVE2D_MODELS", str(tmp_path / "models.yaml"))
    av = str(_fake_avatar(tmp_path / "me"))
    with pytest.raises(L2.Live2DError, match="licence"):
        L2.add_model(av, "me", "Me", "", "https://x.example", "own", measure=False)
    with pytest.raises(L2.Live2DError, match="refused"):
        L2.add_model(av, "me", "Me", "x", "y", "external", measure=False)
    with pytest.raises(L2.Live2DError, match="consent"):
        L2.add_model(av, "me", "Me", "own likeness", "https://x.example", "own", measure=False, likeness="own")
    rep = L2.add_model(av, "me", "Me", "own likeness", "https://x.example", "own", measure=False, likeness="own", consent="asked 2026-10-20")
    assert rep["renderer"] == "mesh" and rep["avatar"] == av and rep["cut_bottom"] is True
    m = L2.resolve_model("me")
    assert m["renderer"] == "mesh" and m["image"] == [400, 560] and m["build"] == {"layers": "b1"}
    assert MA.signature(L2.model_entry("me")) == {"layers": "b1"}
    # an entry edited by hand to drop the consent is refused wherever it is used
    reg = L2.user_models()
    reg["me"]["consent"] = ""
    L2._write_user(str(tmp_path / "models.yaml"), "me", reg["me"])
    with pytest.raises(L2.Live2DError, match="consent"):
        L2.model_entry("me")


def test_performance_maps_onto_runtime_parameters():
    n = 3
    layers = {
        "ParamI": {"set": np.array([0.0, 1.0, 0.0])},
        "ParamO": {"set": np.array([0.0, 0.0, 1.0])},
        "ParamMouthOpenY": {"set": np.array([0.0, 0.7, 0.7])},
        "ParamEyeLOpen": {"set": np.ones(n), "mul": np.array([1.0, 0.0, 1.0])},
        "ParamEyeRSmile": {"add": np.full(n, 0.6)},
        "ParamBrowLY": {"add": np.full(n, 0.4)},
        "ParamMouthForm": {"add": np.ones(n)},          # a mood smile: must not leak into the vowel axis
        "ParamAngleX": {"add": np.full(n, 50.0)},       # clamped to Cubism's range
    }
    v = MA.values(layers, n)
    assert v["mouthForm"][0] == 0.0 and v["mouthForm"][1] < -0.55 and v["mouthForm"][2] > 0.35    # closed, "i", "o"
    assert v["mouthOpen"] == [0.0, 0.7, 0.7]
    assert v["eyeLOpen"] == [1.0, 0.0, 1.0] and v["eyeROpen"] == [1.0, 1.0, 1.0]
    assert v["eyeSmile"] == [0.6] * 3 and v["eyeSmileL"] == [0.0] * 3
    assert v["browY"] == [0.2] * 3 and v["angleX"] == [30.0] * 3


def test_mesh_avatar_renders_a_talking_still(tmp_path, monkeypatch):
    src = os.environ.get("PROMO_TEST_MESH_AVATAR")
    if not src or not MA.is_avatar_dir(src) or not shutil.which(os.environ.get("PROMO_NODE", "node")):
        pytest.skip("set PROMO_TEST_MESH_AVATAR to a built Mesh Avatar Studio project (and have node) to render")
    monkeypatch.setenv("PROMO_LIVE2D_MODELS", str(tmp_path / "models.yaml"))
    L2.add_model(src, "mesh-test", "T", "test", "https://x.example", "own", measure=False)
    fr, info = L2.render_stills("mesh-test", 120, 140, {"ParamMouthOpenY": [0, 1]}, frame={"zoom": 1.0, "cy": 0.5})
    assert fr.shape == (2, 140, 120, 4) and fr[0, ..., 3].max() == 255
    assert np.abs(fr[0].astype(int) - fr[1].astype(int)).max() > 40          # the mouth opened
    assert info["readback"][1]["ParamMouthOpenY"] == 1
