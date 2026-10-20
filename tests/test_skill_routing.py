"""Skill routing: the golden eval passes, and --write persists then reuses skills:."""
import os
import subprocess
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo import cli  # noqa: E402
from promo.skill_routing import route  # noqa: E402


def test_eval_all_pass():
    script = os.path.join(ROOT, "scripts", "eval_skill_routing.py")
    proc = subprocess.run([sys.executable, script], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 7
    assert all(len(ln.split("|")) == 4 and ln.endswith("|PASS") for ln in lines)


def test_write_persists_then_reuses(tmp_path):
    dest = tmp_path / "proj"
    dest.mkdir()
    path = dest / "promo.yaml"
    path.write_text(yaml.safe_dump(
        {"project": {"name": "proj"}, "output": {"name": "proj", "resolution": 1080}},
        sort_keys=False), encoding="utf-8")
    prompt = "A launch film in Remotion with kinetic type"
    assert cli.main(["skills", "route", prompt, "--format", "launch-film",
                     "--project", str(dest), "--write"]) == 0
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["project"]["name"] == "proj"
    assert saved["output"]["resolution"] == 1080
    assert saved["skills"]["primary"] == "cinetic"
    assert saved["skills"]["helpers"] == ["motionmaxxing", "previz"]
    before = path.read_text(encoding="utf-8")
    assert cli.main(["skills", "route", "A calm craft clip, minimal and quiet",
                     "--format", "feature-clip", "--platform", "x", "--length", "15",
                     "--project", str(dest), "--write"]) == 0
    assert path.read_text(encoding="utf-8") == before
    again = yaml.safe_load(before)
    assert again["skills"]["primary"] == "cinetic"
    assert again["skills"]["helpers"] == ["motionmaxxing", "previz"]


def test_motion_words_add_motionmaxxing_helper():
    moving = route("A 60 second product hero with a slow camera-move and soft transitions", format="hero")
    assert moving["primary"] == "promo-reel"
    assert "motionmaxxing" in moving["helpers"]
    plain = route("A 60 second product hero from real footage of the app", format="hero")
    assert plain["primary"] == "promo-reel"
    assert "motionmaxxing" not in plain["helpers"]


def test_illustration_avatar_adds_mesh_avatar_helper_only():
    asked = route("A talk show where my character is the host; make an avatar from this illustration", format="talk-show")
    assert asked["primary"] == "promo-reel"
    assert "mesh-avatar" in asked["helpers"]
    vtuber = route("A vtuber podcast with two Live2D avatars and an anime illustration style", format="talk-show")
    assert vtuber["primary"] == "promo-reel"
    assert "mesh-avatar" not in vtuber["helpers"]


def test_procedural_background_adds_framefields_plates_helper_only():
    asked = route("A 30 second launch film over a procedural background, aurora background behind the cards", format="hero")
    assert asked["primary"] == "promo-reel"
    assert "framefields-plates" in asked["helpers"]
    plain = route("A 60 second product hero with a dark background behind the real app footage", format="hero")
    assert plain["primary"] == "promo-reel"
    assert "framefields-plates" not in plain["helpers"]
