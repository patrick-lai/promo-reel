"""Editing the show-level `horizon_text` re-renders the project shot types that paint it (`draws_horizon_text = True`), and only those.
Without this a project plate type kept its old words baked in after the words changed (the person saw 'there is a sentence.' for 13 s)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from promo import cli  # noqa: E402
from promo.shots import ShotType, shot_type  # noqa: E402
from promo.spec import load_spec  # noqa: E402
from test_horizon import project  # noqa: E402


@shot_type("hz_words_plate")
class WordsPlate(ShotType):
    draws_horizon_text = True

    def render(self, ctx, shot):
        raise NotImplementedError


@shot_type("hz_plain_card")
class PlainCard(ShotType):
    def render(self, ctx, shot):
        raise NotImplementedError


SHOTS = [dict(id="01", beats=[0, 2], type="hz_words_plate"), dict(id="02", beats=[2, 4], type="hz_plain_card")]


def test_editing_the_words_makes_only_the_shots_that_draw_them_stale():
    a = load_spec(project(SHOTS, text=[dict(words="there is a sentence.", beats=[0, 4])], bpm=120.0))
    b = load_spec(project(SHOTS, text=[dict(words="a decision.", beats=[0, 4])], bpm=120.0))
    assert cli.shot_digest(a, a.shots[0]) != cli.shot_digest(b, b.shots[0])        # draws the words: stale
    assert cli.shot_digest(a, a.shots[1]) == cli.shot_digest(b, b.shots[1])        # does not: stays cached
    a2 = load_spec(project(SHOTS, text=[dict(words="there is a sentence.", beats=[0, 4])], bpm=120.0))
    assert cli.shot_digest(a, a.shots[0]) == cli.shot_digest(a2, a2.shots[0])      # same words, same digest
