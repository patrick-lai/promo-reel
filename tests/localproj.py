"""Optional local example projects used by a few regression tests (hero / anime / talkshow style projects).

They live in your projects dir (`promo config projects-dir`, default the gitignored `<repo>/projects/`), never in this repo.
A project is found as `<projects-dir>/<suffix>` or `<projects-dir>/<anything>-<suffix>` (first by name), or pointed at with
`PROMO_TEST_HERO` / `PROMO_TEST_ANIME` / `PROMO_TEST_TALKSHOW` / `PROMO_TEST_DEMO` (a project directory). When one is absent the constants point at a
sentinel path, and tests/conftest.py turns "file under the sentinel not found" failures into skips.
"""
import glob
import os

from promo import home

MISSING = "__no-local-example-project__"


def find(kind):
    env = os.environ.get(f"PROMO_TEST_{kind.upper()}")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    base = home.projects_dir()
    cands = [d for pat in (kind, f"*-{kind}") for d in sorted(glob.glob(os.path.join(base, pat))) if os.path.isfile(os.path.join(d, "promo.yaml"))]
    return cands[0] if cands else os.path.join(base, MISSING, kind)


HERO_DIR, ANIME_DIR, TALK_DIR, DEMO_DIR = find("hero"), find("anime"), find("talkshow"), find("demo")
HERO = os.path.join(HERO_DIR, "promo.yaml")
ANIME = os.path.join(ANIME_DIR, "promo.yaml")
TALK = os.path.join(TALK_DIR, "promo.yaml")
DEMO = os.path.join(DEMO_DIR, "promo.yaml")          # a Live2D livestream demo project
HERO_MANIFEST = os.path.join(HERO_DIR, "footage", "manifest.yaml")
TALK_MAKE_SPEC = os.path.join(TALK_DIR, "make_spec.py")
TALK_PLAN = os.path.join(TALK_DIR, "plan.yaml")
# the talk show's spec reads its clips from the hero manifest via ${HERO_FOOTAGE_MANIFEST}
os.environ.setdefault("HERO_FOOTAGE_MANIFEST", HERO_MANIFEST)
