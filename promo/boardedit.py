"""Edit a storyboard without hand-writing JSON: the agent's controls for "add a scene", "retime it", "show me frames every 5 seconds".

    story_set   create or update a board (title, logline, aspect)           scene_add / scene_set / scene_rm   one scene at a time
    density     keyframes on a time grid ("every 5 s"): a mid frame wherever a multiple of N falls inside a scene; auto frames are replaced on the next
                run, hand-made ones stay; `clear=True` removes the auto frames. The board keeps `density: {every_s}`, so the storyboard gate then needs those
                frames as real images too (`promo flow frames` makes them).

Everything here edits `flow/boards/<story>/board.json` (schema: promo/storyboard.py) and returns a one-line summary for the CLI.
"""
from __future__ import annotations

import json
import os

from . import storyboard as SB

EDGE = 0.25            # a grid time this close to a scene's start or end is already covered by that scene's START or END frame
MAX_FRAMES = 240
SCENE_FIELDS = ("beat", "action", "caption", "vo", "sound", "camera", "proof", "source")


class BoardError(Exception):
    pass


def board_dir(flow_dir, story):
    return os.path.join(flow_dir, "boards", story)


def _load(flow_dir, story):
    d = board_dir(flow_dir, story)
    if not os.path.isfile(SB.board_path(d)):
        raise BoardError(f"no board {story}: create it first with `promo flow story {story} --title T --logline L`")
    return d, SB.load(d)


def _save(d, b):
    os.makedirs(d, exist_ok=True)
    with open(SB.board_path(d), "w") as f:
        json.dump(b, f, indent=2, ensure_ascii=False)


def story_set(flow_dir, story, title=None, logline=None, aspect=None, duration=None):
    d = board_dir(flow_dir, story)
    b = SB.load(d) if os.path.isfile(SB.board_path(d)) else dict(story=story, title="", logline="", aspect="16:9", scenes=[])
    for k, v in (("title", title), ("logline", logline), ("aspect", aspect)):
        if v:
            b[k] = v
    if duration:
        b["duration_s"] = float(duration)
    if not b.get("title") or not b.get("logline"):
        raise BoardError("a new story needs --title and --logline")
    _save(d, b)
    return f"story {story}: {len(b['scenes'])} scenes"


def _frame(sid, which, beat, action, prompt=None):
    return dict(image=f"frames/{sid}-{which}.png", prompt=prompt or f"{'Start' if which == 'start' else 'End'} of {beat}: {action}")


def _scene_by_id(b, sid):
    for s in b.get("scenes") or []:
        if s.get("id") == sid:
            return s
    raise BoardError(f"no scene {sid} in story {b.get('story')}")


def _drop_image(d, f):
    for p in ((os.path.join(d, f["image"]),) if f.get("image") else ()):
        for q in (p, p + ".gen.json"):
            if os.path.isfile(q):
                os.remove(q)


def scene_add(flow_dir, story, sid, t, beat, action, after=None, **kw):
    d, b = _load(flow_dir, story)
    if any(s.get("id") == sid for s in b.get("scenes") or []):
        raise BoardError(f"scene {sid} already exists in story {story}: `scene set` changes it")
    if not t or len(t) != 2 or not t[1] > t[0]:
        raise BoardError("--t START END (seconds, END after START)")
    s = dict(id=sid, beat=beat, t=[float(t[0]), float(t[1])], action=action)
    for k in SCENE_FIELDS[2:]:
        if kw.get(k):
            s[k] = kw[k]
    if kw.get("source") not in (None, "real", "generated"):
        raise BoardError("--source is real|generated")
    s["start"] = _frame(sid, "start", beat, action, kw.get("start_prompt"))
    s["end"] = _frame(sid, "end", beat, action, kw.get("end_prompt"))
    sc = b.setdefault("scenes", [])
    i = next((n + 1 for n, x in enumerate(sc) if x.get("id") == after), None) if after else len(sc)
    if after and i is None:
        raise BoardError(f"--after {after}: no such scene")
    sc.insert(i, s)
    _save(d, b)
    return f"story {story}: scene {sid} added ({len(sc)} scenes)" + _regrid(flow_dir, story, sid)


def scene_set(flow_dir, story, sid, t=None, redraw=None, **kw):
    """Change fields of one scene. `redraw` = start|end|mid|all deletes those frame images so `promo flow frames` makes them again."""
    d, b = _load(flow_dir, story)
    s = _scene_by_id(b, sid)
    changed = []
    for k in SCENE_FIELDS:
        if kw.get(k) is not None:
            if k == "source" and kw[k] not in ("real", "generated"):
                raise BoardError("--source is real|generated")
            s[k] = kw[k]
            changed.append(k)
    if t:
        if len(t) != 2 or not t[1] > t[0]:
            raise BoardError("--t START END (seconds, END after START)")
        s["t"] = [float(t[0]), float(t[1])]
        changed.append("t")
    for w in ("start", "end"):
        p = kw.get(f"{w}_prompt")
        if p:
            s.setdefault(w, _frame(sid, w, s.get("beat", ""), s.get("action", "")))["prompt"] = p
            changed.append(f"{w}_prompt")
    if redraw:
        for w in ("start", "end"):
            if redraw in (w, "all") and s.get(w):
                _drop_image(d, s[w])
        if redraw in ("mid", "all"):
            for f in s.get("frames") or []:
                _drop_image(d, f)
        changed.append(f"redraw {redraw}")
    if not changed:
        raise BoardError("nothing to change: pass at least one field (--action, --caption, --t, --redraw ...)")
    if t:                                                  # frames that fell outside the new times go; the grid is planned again below
        for f in [f for f in s.get("frames") or [] if f.get("auto") and not (s["t"][0] < f.get("t", -1) < s["t"][1])]:
            _drop_image(d, f)
            s["frames"].remove(f)
        if not s.get("frames"):
            s.pop("frames", None)
    _save(d, b)
    return f"story {story} scene {sid}: " + ", ".join(changed) + (_regrid(flow_dir, story, sid) if t else "")


def _regrid(flow_dir, story, sid):
    """A board that was given a frame density keeps it when a scene is added or retimed: plan that scene's frames on the same grid."""
    d, b = _load(flow_dir, story)
    dens = b.get("density") or {}
    if not dens.get("every_s") or dens.get("scene"):
        return ""
    return "; " + density(flow_dir, [(story, b, d)], every=dens["every_s"], scene=sid)


def scene_rm(flow_dir, story, sid):
    d, b = _load(flow_dir, story)
    s = _scene_by_id(b, sid)
    for f in [s.get("start"), s.get("end"), *(s.get("frames") or [])]:
        if f:
            _drop_image(d, f)
    b["scenes"] = [x for x in b["scenes"] if x is not s]
    _save(d, b)
    return f"story {story}: scene {sid} removed ({len(b['scenes'])} left)"


def scene_lines(flow_dir, story):
    d, b = _load(flow_dir, story)
    out = []
    for s in b.get("scenes") or []:
        t = s.get("t") or [0, 0]
        out.append(f"{s['id']:<4} {t[0]:>6g}-{t[1]:<6g} {s.get('beat', ''):<22} {s.get('source') or '-':<9} frames {len(s.get('frames') or []):<3} {s.get('action', '')[:70]}")
    return out


def _grid(every, t0, t1):
    """Multiples of `every` strictly inside (t0 + EDGE, t1 - EDGE)."""
    out = []
    k = int((t0 + EDGE) // every) + 1
    while k * every < t1 - EDGE:
        t = round(k * every, 3)
        if t > t0 + EDGE:
            out.append(t)
        k += 1
    return out


def _name(sid, t):
    return f"frames/{sid}-t{int(round(t * 10)):04d}.png"


def density(flow_dir, boards, every=None, scene=None, clear=False):
    """Plan keyframes every `every` seconds on the timeline for [(story, board, dir)] (one scene with `scene`). Returns a summary line."""
    if not clear and not (every and 0.5 <= every <= 120):
        raise BoardError("--every SECONDS (0.5 to 120), or --clear to go back to start and end frames only")
    if scene and not any(s.get("id") == scene for _, b, _ in boards for s in b.get("scenes") or []):
        raise BoardError(f"no scene {scene}")
    added = removed = kept = total = 0
    drop = []
    for sid, b, d in boards:
        for s in b.get("scenes") or []:
            if scene and s.get("id") != scene:
                total += len(s.get("frames") or [])
                continue
            t0, t1 = s["t"]
            want = [] if clear else _grid(every, t0, t1)
            out = []
            for f in s.get("frames") or []:
                ft = f.get("t")
                if not f.get("auto"):
                    out.append(f)                                                       # a hand-made frame stays
                elif any(isinstance(ft, (int, float)) and abs(ft - w) < 1e-6 for w in want):
                    out.append(f)
                    kept += 1
                else:
                    drop.append((d, f))
                    removed += 1
            have_t = [f["t"] for f in out if isinstance(f.get("t"), (int, float))]
            for w in want:
                if any(abs(w - h) < EDGE for h in have_t):
                    continue                                                           # a hand-made frame already sits there
                pct = round(100 * (w - t0) / max(t1 - t0, 0.1))
                out.append(dict(t=w, image=_name(s["id"], w), auto=True,
                                prompt=f"Moment at t={w:g} s, {pct}% of the way through scene {s['id']} ({s.get('beat', '')}): {s.get('action', '')} "
                                       f"It sits between the start frame ({(s.get('start') or {}).get('prompt', '')}) and the end frame ({(s.get('end') or {}).get('prompt', '')}); "
                                       f"keep the same place, light and people."))
                added += 1
            out.sort(key=lambda f: f["t"] if isinstance(f.get("t"), (int, float)) else 1e9)
            if out:
                s["frames"] = out
            else:
                s.pop("frames", None)
            total += len(out)
    if total > MAX_FRAMES:
        raise BoardError(f"that would be {total} mid frames (limit {MAX_FRAMES}): use a larger --every, or one --scene")
    for d, f in drop:
        _drop_image(d, f)
    for sid, b, d in boards:
        if clear:
            if not any(f.get("auto") for x in b.get("scenes") or [] for f in x.get("frames") or []):
                b.pop("density", None)
        elif not scene:
            b["density"] = dict(every_s=every)
        elif not b.get("density"):
            b["density"] = dict(every_s=every, scene=scene)       # frames for one scene only: they are still required as images
        _save(d, b)
    what = "cleared" if clear else f"every {every:g} s"
    return f"frames {what}: {added} added, {removed} removed, {kept} kept, {total} mid frames in total; make the images with `promo flow frames`"
