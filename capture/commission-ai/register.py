#!/usr/bin/env python3
"""Registers every v1-1080 clip in notes.json with promo-reel's footage manifest (`promo footage add`).

usage: register.py [--dry-run] [--footage-dir DIR] [--python PY] [clip-id ...]
  --dry-run      print the `promo footage add` commands, run nothing and write nothing
  --footage-dir  default $FOOTAGE_DIR, else <repo>/../videos/commission-ai-promo/footage/v1-1080
  --python       interpreter with promo-reel installed: default $PROMO_PYTHON, else this interpreter
The repo root is derived from this file's location (capture/commission-ai/../..).
Each clip's capture field records the injected capture CSS (NO_TOASTS, HIDE_MONEY, ...) and whether the capture-overlay cursor is
present; HIDE_MONEY and the overlay are also appended to framing. Source: <clip>.meta.json, else notes.json "inject".
"""
import argparse
import json
import os
import shlex
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capmeta  # noqa: E402

PROJ = "projects/commission-ai-hero/promo.yaml"


def build_commands(notes, fdir, py, only=(), log=()):
    """[(clip_id, argv)] for every clip whose .mov exists (and is in `only`, when given)."""
    out = []
    for n in notes["clips"]:
        f = f"{fdir}/{n['file']}.mov"
        cid = n.get("id", n["file"] + "-v1080")
        if not os.path.exists(f) or (only and cid not in only):
            continue
        flags = capmeta.clip_flags(n, fdir)
        capture = n["url"].replace("`", "") + (" ; " + n["capture_extra"] if n.get("capture_extra") else "") + " ; " + capmeta.capture_text(flags)
        framing = n["framing"] + ("; " + capmeta.framing_text(flags) if capmeta.framing_text(flags) else "")
        at = next((e["at"] for e in reversed(list(log)) if e.get("shot") == n["file"]), None)
        cmd = [py, "-m", "promo", "-p", PROJ, "footage", "add", f, "--id", cid, "--shots", *n["shots"], "--commit", n.get("commit", capmeta.DEFAULT_COMMIT),
               "--capture", capture, "--framing", framing, "--dpr", str(n.get("dpr", 1)), "--notes", (n["beat"] + " || " + n["notes"]).replace("`", "'"), "--demo", "--json"]
        if at:
            cmd += ["--captured-at", at]
        out.append((cid, cmd))
    return out


def read_log(fdir):
    p = os.path.join(fdir, "capture-log.jsonl")
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="only these clip ids")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--footage-dir")
    ap.add_argument("--python", default=os.environ.get("PROMO_PYTHON") or sys.executable)
    ap.add_argument("--notes")
    a = ap.parse_args(argv)
    fdir = capmeta.footage_dir(a.footage_dir)
    cmds = build_commands(capmeta.load_notes(a.notes), fdir, a.python, a.ids, read_log(fdir))
    rc = 0
    for cid, cmd in cmds:
        if a.dry_run:
            print(f"[dry-run] (cd {shlex.quote(capmeta.REPO)} && {shlex.join(cmd)})")
            continue
        r = subprocess.run(cmd, cwd=capmeta.REPO, capture_output=True, text=True)
        rc = rc or r.returncode
        print(cid, "rc", r.returncode, r.stdout.strip()[:300], r.stderr.strip()[-300:] if r.returncode else "")
    if a.dry_run:
        print(f"[dry-run] {len(cmds)} clip(s); nothing written")
    return rc


if __name__ == "__main__":
    sys.exit(main())
