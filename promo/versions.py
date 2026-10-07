"""Every draft keeps the plan it was built from, so the person can go back: the whole draft, or one scene of it.

    promo flow restore --draft N --by NAME                       the spec, assets, shot code and storyboards as they were for draft N
    promo flow restore --draft N --scene ID [--shot ID ...] --by NAME   one storyboard scene (and the promo.yaml shots of that scene) from draft N

What is kept per draft (flow/versions/d<N>/): promo.yaml, assets.yaml, shots.py, footage/manifest.yaml, flow/assets.json and every
flow/boards/<story>/board.json. Media are not copied: footage and builds are named by their sha256 in the manifest and stay where they are.
A restore first keeps the current files as flow/versions/undo-<k>/, so it can itself be undone (`--undo K`).
A scene's shots are the promo.yaml shots whose id is the scene id, plus any `--shot`; they are swapped as text, so the comments around them stay.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil

import yaml

from . import flow as F

FILES = ("promo.yaml", "assets.yaml", "shots.py", "footage/manifest.yaml", "flow/assets.json")


def _tracked(pd):
    out = [p for p in FILES if os.path.isfile(os.path.join(pd, p))]
    out += sorted(os.path.relpath(p, pd) for p in glob.glob(os.path.join(pd, "flow", "boards", "*", "board.json")))
    return out


def keep(pd, name):
    """Copy the plan files into flow/versions/<name>/; returns the list of files kept."""
    dest = os.path.join(F.fdir(pd), "versions", name)
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    files = _tracked(pd)
    os.makedirs(dest)
    for rel in files:
        os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
        shutil.copyfile(os.path.join(pd, rel), os.path.join(dest, rel))
    with open(os.path.join(dest, "index.json"), "w") as f:
        json.dump(dict(at=F.now(), files=files), f, indent=1)
    return files


def _version_dir(pd, name):
    d = os.path.join(F.fdir(pd), "versions", name)
    if not os.path.isfile(os.path.join(d, "index.json")):
        raise F.FlowError(f"no kept version {name}: drafts registered before versions were kept cannot be restored")
    return d


def _undo_name(st):
    k = len([r for r in st.get("restores") or [] if r.get("undo")]) + 1
    return f"undo-{k}", k


def _shot_block(text, sid):
    """(start, end) line indexes of the promo.yaml list item for shot `sid` (block or one-line flow style), or None."""
    lines = text.splitlines(keepends=True)
    pat = re.compile(r"^(\s*)-\s*(\{\s*)?id:\s*(['\"]?)" + re.escape(str(sid)) + r"\3(?=\s*(?:[,}#]|$))")
    for i, line in enumerate(lines):
        m = pat.match(line)
        if not m:
            continue
        if m.group(2):
            return i, i + 1
        ind = len(m.group(1))
        j = i + 1
        while j < len(lines):
            s = lines[j]
            if s.strip() and (len(s) - len(s.lstrip())) <= ind:
                break
            j += 1
        return i, j
    return None


def _shots(text):
    return {str(s.get("id")): s for s in (yaml.safe_load(text) or {}).get("shots") or []}


def _swap_shots(cur_text, old_text, ids):
    lines = cur_text.splitlines(keepends=True)
    old_lines = old_text.splitlines(keepends=True)
    want = _shots(old_text)
    for sid in ids:
        a, b = _shot_block("".join(lines), sid), _shot_block(old_text, sid)
        if a is None or b is None:
            raise F.FlowError(f"shot {sid} is not in both versions of promo.yaml (or not written as `- id: {sid}`): restore the whole draft instead")
        lines[a[0]:a[1]] = old_lines[b[0]:b[1]]
    out = "".join(lines)
    got = _shots(out)
    if any(got.get(str(s)) != want[str(s)] for s in ids):
        raise F.FlowError("the shots could not be swapped cleanly in promo.yaml: restore the whole draft instead")
    return out


def restore(pd, n=None, scene=None, shots=(), by=None, undo=None):
    """Every change is worked out before a file is touched, so a refused restore leaves everything as it was; then the current files are kept
    as the undo and the change is written."""
    st = F.load(pd)
    by = F.human(by)
    if undo:
        src, what = _version_dir(pd, f"undo-{undo}"), f"the files as they were before restore {undo}"
    else:
        if not 1 <= (n or 0) <= len(st["drafts"]):
            raise F.FlowError(f"no draft {n}")
        src, what = _version_dir(pd, f"d{n}"), f"draft {n}'s version"
    files = json.load(open(os.path.join(src, "index.json")))["files"]
    if scene is None and not shots:
        writes = {rel: open(os.path.join(src, rel)).read() for rel in files}
        drops = [rel for rel in _tracked(pd) if rel not in files]          # added after that draft: not part of its plan
        done = f"Restored {what}"
    else:
        writes, done = _scene_changes(pd, src, files, scene, list(shots), what)
        drops = []
    name, k = _undo_name(st)
    keep(pd, name)
    for rel, text in writes.items():
        os.makedirs(os.path.dirname(os.path.join(pd, rel)) or pd, exist_ok=True)
        with open(os.path.join(pd, rel), "w") as f:
            f.write(text)
    for rel in drops:
        os.remove(os.path.join(pd, rel))
    st = F.load(pd)
    st.setdefault("restores", []).append(dict(at=F.now(), by=by, draft=n, scene=scene, shots=list(shots), undo=k, from_undo=undo, what=done))
    F.log(st, f"{done} by {by} (undo: restore --undo {k})")
    F.save(pd, st)
    from . import lessons as L
    L.record("restore", by, F._project(pd), done)
    return done, k


def _scene_changes(pd, src, files, scene, shots, what):
    """({relative path: new text}, what was restored) for one storyboard scene and its promo.yaml shots."""
    writes, parts = {}, []
    if scene:
        old_board = None
        for rel in files:
            if rel.startswith("flow/boards/"):
                b = json.load(open(os.path.join(src, rel)))
                if any(str(s["id"]) == str(scene) for s in b.get("scenes") or []):
                    old_board = (rel, b)
                    break
        if old_board is None:
            raise F.FlowError(f"scene {scene} is not in {what}")
        rel, b = old_board
        cur = json.load(open(os.path.join(pd, rel)))
        idx = next((i for i, s in enumerate(cur.get("scenes") or []) if str(s["id"]) == str(scene)), None)
        if idx is None:
            raise F.FlowError(f"scene {scene} is no longer in the storyboard: restore the whole draft instead")
        cur["scenes"][idx] = next(s for s in b["scenes"] if str(s["id"]) == str(scene))
        writes[rel] = json.dumps(cur, indent=2)
        parts.append(f"scene {scene}")
    spec_p = os.path.join(pd, "promo.yaml")
    if "promo.yaml" in files and os.path.isfile(spec_p):
        old_text, cur_text = open(os.path.join(src, "promo.yaml")).read(), open(spec_p).read()
        ids = list(shots) + ([scene] if scene and str(scene) in _shots(old_text) and str(scene) in _shots(cur_text) and scene not in shots else [])
        if ids:
            writes["promo.yaml"] = _swap_shots(cur_text, old_text, ids)
            parts.append(f"shot{'s' if len(ids) > 1 else ''} {', '.join(map(str, ids))}")
    elif shots:
        raise F.FlowError("there is no promo.yaml in that version to take shots from")
    return writes, f"Restored {' and '.join(parts)} from {what}"
