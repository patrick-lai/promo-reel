"""Where projects live. They do NOT have to be inside this repository.

    PROMO_PROJECTS=~/promo-projects         env var (wins)
    promo config projects-dir ~/promo-projects   writes ~/.config/promo-reel/config.yaml (or $PROMO_CONFIG)
    <repo>/projects                         default (local, gitignored)

The same config file holds `heavy_lock:` (path of the box-wide heavy-work lock, see promo/lock.py;
`promo config heavy-lock [PATH]`; $PROMO_HEAVY_LOCK overrides).

`promo new <name>` scaffolds into the projects dir; every command that takes a project (`-p`, `--project`, critique-pack's
positional) accepts a path (a dir, or a promo.yaml) OR a bare project name, which is looked up in the projects dir.
A legacy `projects/<name>` argument that does not exist relative to the cwd is also looked up in the projects dir, so the
commands in older docs keep working when your projects live elsewhere. A project is self-contained: its spec, footage manifest,
brief, references and rounds are all relative to its own directory (a shared manifest can sit next to it, e.g. `../shared/`).
"""
from __future__ import annotations

import os

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def config_path() -> str:
    return os.path.expanduser(os.environ.get("PROMO_CONFIG") or "~/.config/promo-reel/config.yaml")


def load_config() -> dict:
    try:
        return yaml.safe_load(open(config_path())) or {}
    except (OSError, yaml.YAMLError):
        return {}


def save_config(cfg: dict) -> str:
    p = config_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return p


def projects_dir() -> str:
    d = os.environ.get("PROMO_PROJECTS") or load_config().get("projects_dir") or os.path.join(REPO, "projects")
    return os.path.abspath(os.path.expanduser(d))


def resolve(arg):
    """A project argument -> a path: existing paths win, then a bare name (or legacy `projects/<name>`) in the projects dir."""
    if not arg:
        return arg
    a = os.path.expanduser(str(arg))
    if os.path.exists(a):
        return a
    base = projects_dir()
    for rel in ([a] if os.sep not in a else []) + ([a[len("projects" + os.sep):]] if a.startswith("projects" + os.sep) else []):
        cand = os.path.join(base, rel)
        if os.path.exists(cand):
            return cand
    return a


def list_projects() -> list[dict]:
    base = projects_dir()
    out = []
    if not os.path.isdir(base):
        return out
    for n in sorted(os.listdir(base)):
        d = os.path.join(base, n)
        if os.path.isfile(os.path.join(d, "promo.yaml")):
            out.append(dict(name=n, path=d, brief=os.path.exists(os.path.join(d, "brief.yaml")),
                            rounds=len([r for r in os.listdir(os.path.join(d, "rounds"))]) if os.path.isdir(os.path.join(d, "rounds")) else 0))
    return out


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="promo config", description="promo-reel user config (where projects live, the heavy-work lock)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("projects-dir", help="show, or set, the directory projects live in")
    p.add_argument("path", nargs="?")
    h = sub.add_parser("heavy-lock", help="show, or set, the path of the box-wide heavy-work lock (default /tmp/promo-reel-heavy.lock; $PROMO_HEAVY_LOCK overrides)")
    h.add_argument("path", nargs="?")
    a = ap.parse_args(argv)
    if a.cmd == "heavy-lock":
        from . import lock
        if a.path:
            cfg = load_config()
            cfg["heavy_lock"] = os.path.abspath(os.path.expanduser(a.path))
            print(f"heavy lock = {cfg['heavy_lock']}  (saved in {save_config(cfg)}; $PROMO_HEAVY_LOCK overrides)")
        else:
            print(lock.lock_path())
        return 0
    if a.cmd == "projects-dir":
        if a.path:
            d = os.path.abspath(os.path.expanduser(a.path))
            os.makedirs(d, exist_ok=True)
            cfg = load_config()
            cfg["projects_dir"] = d
            print(f"projects dir = {d}  (saved in {save_config(cfg)}; $PROMO_PROJECTS overrides)")
        else:
            print(projects_dir())
    return 0
