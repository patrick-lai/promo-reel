"""Where projects live. They do NOT have to be inside this repository, or inside the repo the agent is working in.

A video's folder comes from one path template with two tokens: `{project}` is the repo the agent is working in (a git worktree reports
its main checkout's name) and `{slug}` is the video's short name. `{slug}` is always the last folder; a template without it gets it added.

    home      ~/.promo-reel/{project}/{slug}
    repo      ./promo-reel/{slug}                  a relative template is relative to the root of the repo you work in
    anything  /Volumes/Drive/promo-reel/{project}/{slug}
    default   <this checkout>/projects/{slug}

    PROMO_PROJECTS=~/promo-projects         env var, a plain folder (wins)
    promo config output home|repo|default|TEMPLATE   writes `output:` in ~/.config/promo-reel/config.yaml (or $PROMO_CONFIG)
    promo config projects-dir PATH          older spelling of the same thing, `projects_dir:` (used when `output:` is not set)

The same config file holds `heavy_lock:` (path of the box-wide heavy-work lock, see promo/lock.py;
`promo config heavy-lock [PATH]`; $PROMO_HEAVY_LOCK overrides).

`promo new <name>` and `promo flow init` scaffold into that location; every command that takes a project (`-p`, `--project`, critique-pack's
positional) accepts a path (a dir, or a promo.yaml) OR a bare project name, which is looked up in the location (under every `{project}`).
A legacy `projects/<name>` argument that does not exist relative to the cwd is also looked up there, so the
commands in older docs keep working when your projects live elsewhere. A project is self-contained: its spec, footage manifest,
brief, references and rounds are all relative to its own directory (a shared manifest can sit next to it, e.g. `../shared/`).
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import sys

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


PRESETS = {"home": "~/.promo-reel/{project}/{slug}", "repo": "./promo-reel/{slug}"}
DEFAULT_TEMPLATE = os.path.join(REPO, "projects", "{slug}")
SLUG = "/{slug}"


class ConfigError(Exception):
    pass


def _git(cwd: str, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True)
    except OSError:                       # no git installed: the cwd simply is not a repo
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def current_project(cwd: str | None = None) -> tuple[str, str]:
    """(name, root) of the repo the agent is working in. A worktree reports its main checkout's name, so a throwaway worktree folder
    never becomes the project; outside git the cwd is the project."""
    cwd = os.path.abspath(cwd or os.getcwd())
    top = _git(cwd, "rev-parse", "--show-toplevel")
    if not top:
        return os.path.basename(cwd) or "project", cwd
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    main = os.path.dirname(common) if os.path.basename(common) == ".git" else top
    return os.path.basename(main), top


def _with_slug(template: str) -> str:
    t = template.strip().rstrip("/")
    return t if t.endswith(SLUG) else t + SLUG


def output_template() -> tuple[str, str]:
    """(template, source), source = env | config | default."""
    env = os.environ.get("PROMO_PROJECTS")
    if env:
        return _with_slug(env), "env"
    cfg = load_config()
    saved = cfg.get("output") or cfg.get("projects_dir")
    return (_with_slug(saved), "config") if saved else (DEFAULT_TEMPLATE, "default")


def _abs(path: str, repo: str) -> str:
    p = os.path.expanduser(path)
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(repo, p))


def expand(template: str, slug: str, project: str, repo: str) -> str:
    return _abs(template.replace("{project}", project).replace("{slug}", slug), repo)


def parse_output(text: str) -> str:
    """User input -> a stored template (a preset name, or a path with {project}/{slug}); raises ConfigError with a plain sentence."""
    t = PRESETS.get((text or "").strip(), (text or "").strip())
    if not t:
        raise ConfigError("Give a folder, for example ~/.promo-reel/{project}/{slug}, or one of: home, repo, default.")
    if re.search(r'["`$\\\x00-\x1f]', t):
        raise ConfigError("The folder can't contain quotes, backticks, $, backslashes or line breaks.")
    unknown = sorted(set(re.findall(r"\{([^}]*)\}", t)) - {"project", "slug"})
    if unknown:
        raise ConfigError(f"Only {{project}} and {{slug}} can be used in the folder, not {{{unknown[0]}}}.")
    if "{slug}" in t and not (t.endswith(SLUG) and t.count("{slug}") == 1):
        raise ConfigError("{slug} must be the last folder, for example /Volumes/Drive/promo-reel/{project}/{slug}.")
    return _with_slug(t)


def available(template: str, project: str, repo: str) -> bool:
    """Can a new video folder be created there? False for an unplugged drive: the nearest folder that exists must be writable."""
    d = os.path.dirname(expand(template, "x", project, repo))
    while not os.path.isdir(d):
        if os.path.exists(d) or os.path.dirname(d) == d:          # a file is in the way
            return False
        d = os.path.dirname(d)
    return os.access(d, os.W_OK | os.X_OK)


def project_dir(slug: str, cwd: str | None = None) -> str:
    """Folder for a NEW video called `slug`, from the configured location and the repo in `cwd`."""
    if not slug or slug in (".", "..") or os.sep in slug:
        raise ConfigError("A video name is one short word or phrase, without slashes.")
    template, _ = output_template()
    project, repo = current_project(cwd)
    if not available(template, project, repo):
        raise ConfigError(f"Can't reach the save location {template}. Is the drive plugged in? Change it with `promo config output`.")
    return expand(template, slug, project, repo)


def slugify(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0] if "-" in s[:limit] else s[:limit]
    return s or "promo"


def projects_dir() -> str:
    """Folder the next video's folder goes in."""
    template, _ = output_template()
    return os.path.dirname(expand(template, "x", *current_project()))


def _parents(cwd: str | None = None) -> list[str]:
    """Folders that hold videos: the current project's first, then every other {project}'s."""
    template, _ = output_template()
    project, repo = current_project(cwd)
    base = _abs(template[: -len(SLUG)], repo)
    mine = base.replace("{project}", project)
    pattern = "*".join(glob.escape(x) for x in base.split("{project}"))
    return [mine] + sorted(d for d in glob.glob(pattern) if os.path.isdir(d) and d != mine)


def resolve(arg):
    """A project argument -> a path: existing paths win, then a bare name (or legacy `projects/<name>`) in the save location."""
    if not arg:
        return arg
    a = os.path.expanduser(str(arg))
    if os.path.exists(a):
        return a
    rels = ([a] if os.sep not in a else []) + ([a[len("projects" + os.sep):]] if a.startswith("projects" + os.sep) else [])
    for base in _parents():
        for rel in rels:
            cand = os.path.join(base, rel)
            if os.path.exists(cand):
                return cand
    return a


def list_projects() -> list[dict]:
    out = []
    for base in _parents():
        for n in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            d = os.path.join(base, n)
            if os.path.isfile(os.path.join(d, "promo.yaml")):
                out.append(dict(name=n, path=d, brief=os.path.exists(os.path.join(d, "brief.yaml")),
                                rounds=len([r for r in os.listdir(os.path.join(d, "rounds"))]) if os.path.isdir(os.path.join(d, "rounds")) else 0))
    return out


def output_info(project: str, repo: str) -> dict:
    """What the promo-flow mod's settings pane shows: the saved location, where each preset would put the next video, whether it is reachable."""
    template, source = output_template()
    presets = dict(PRESETS, default=DEFAULT_TEMPLATE)
    mode = "default" if source == "default" else next((k for k, v in PRESETS.items() if v == template), "custom")
    return dict(template=template, source=source, mode=mode, locked=source == "env", available=available(template, project, repo), project=project, repo=repo,
                home=os.path.expanduser("~"), example=expand(template, "<slug>", project, repo),
                presets={k: dict(template=v, example=expand(v, "<slug>", project, repo)) for k, v in presets.items()})


def set_output(text: str, cwd: str | None = None) -> str | None:
    """Save the location (`default` clears it). Refuses a place that can't be reached right now, so a typo or an unplugged drive never gets saved."""
    cfg = load_config()
    if (text or "").strip() == "default":
        cfg.pop("output", None)
        cfg.pop("projects_dir", None)
        save_config(cfg)
        return None
    t = parse_output(text)
    project, repo = current_project(cwd)
    if not available(t, project, repo):
        raise ConfigError(f"Can't reach {t}. Is the drive plugged in? Nothing was changed.")
    cfg["output"] = t
    cfg.pop("projects_dir", None)
    save_config(cfg)
    return t


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="promo config", description="promo-reel user config (where projects live, the heavy-work lock)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("output", help="show, or set, where new videos are saved: home | repo | default | a path with {project} and {slug}")
    o.add_argument("where", nargs="?")
    p = sub.add_parser("projects-dir", help="show, or set, the directory projects live in (a plain folder; `output` also takes {project} and {slug})")
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
    if a.cmd == "output":
        try:
            if a.where:
                saved = set_output(a.where)
                print(f"save location = {saved or 'default'}  (saved in {config_path()})" + ("; $PROMO_PROJECTS overrides it here" if os.environ.get("PROMO_PROJECTS") else ""))
            template, source = output_template()
            info = output_info(*current_project())
            print(f"save location: {template}  ({source})\nnext video here: {info['example']}" + ("" if info["available"] else "\n(not reachable right now)"))
        except ConfigError as e:
            print(f"promo config: {e}", file=sys.stderr)
            return 1
        return 0
    if a.cmd == "projects-dir":
        if a.path:
            d = os.path.abspath(os.path.expanduser(a.path))
            os.makedirs(d, exist_ok=True)
            cfg = load_config()
            cfg["projects_dir"] = d
            cfg.pop("output", None)
            print(f"projects dir = {d}  (saved in {save_config(cfg)}; $PROMO_PROJECTS overrides)")
        else:
            print(projects_dir())
    return 0
