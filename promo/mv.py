"""Look bible + generated plates for the `anime-mv` style. `promo mv bible|plan|gen|takes|use -p promo.yaml`.

A music video lives or dies on one consistent drawing style and one consistent heroine across 20-40 generated shots. So
every plate prompt is built from the same show-level bible, and every keyframe is drawn with the bible's character sheet
and style frame as references:

    look_bible:
      prompt: "Japanese indie anime music-video still. Flat cel-shaded 2D ..."      # the drawing style, palette, world
      cast: {hero: "a slim teenage girl, black hair with a sky-blue inner layer ...", spirit: "a small round white cloud spirit ..."}
      palette: ["#5f8f8b", "#a9c3a0", "#2b3a4a", "#fffdf9", "#e0603a"]
      refs: [{role: character, file: bible/sheet.png}, {role: style, file: bible/frame2.png}]
    shots:
      - id: "06"
        type: mv
        plate: {prompt: "she runs along a flooded rooftop ...", motion: "she runs left to right, hair streaming", kind: video, cast: [hero]}
        source: v06-t1                    # the take in use (set by `gen` for a shot without one, or `use` / the Stage)

`gen` makes TAKES: keyframe `media/plates/<shot>/key-tN.png` (grok image_edit with the bible refs), then for `kind: video`
`clip-tN.mp4` (grok image_to_video at 720p from that keyframe). Each take is a footage-manifest clip (`k<shot>-tN` /
`v<shot>-tN`, `generated:`) with a sidecar carrying the bible id, so gate look-bible can tell which plates predate a
bible change. A shot that has no plate yet gets its first take; later takes wait for `use` (or the Stage's "Use this take").
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

ANIM = ("Keep the exact flat 2D cel-animation look of the first frame: same linework, flat colour fills, palette and character "
        "design; limited animation (hair, cloth, eyes, light, particles); no morphing, no new characters, no text. ")
TAKE_RE = re.compile(r"^([kv])(.+)-t(\d+)$")


def bible_id(bible) -> str:
    """Short id of a look bible: its prompt, cast and the bytes of its reference files."""
    h = hashlib.sha1()
    b = bible or {}
    h.update(json.dumps([b.get("prompt"), b.get("cast"), b.get("palette")], sort_keys=True, ensure_ascii=False).encode())
    for r in b.get("refs") or []:
        h.update(str(r.get("role")).encode())
        f = r.get("_abs") or r.get("file")
        if f and os.path.exists(f):
            h.update(hashlib.sha1(open(f, "rb").read()).digest())
    return h.hexdigest()[:8]


def bible_of(spec):
    """The spec's look_bible with absolute ref paths (`_abs`), or {}."""
    b = copy.deepcopy(spec.raw.get("look_bible") or {})
    for r in b.get("refs") or []:
        r["_abs"] = spec.resolve(r["file"])
    return b


def plate_prompt(bible, plate):
    cast = bible.get("cast") or {}
    who = " ".join(cast[c] for c in plate.get("cast") or [] if c in cast)
    return " ".join(x for x in (bible.get("prompt", "").strip(), who.strip(), "Scene: " + str(plate.get("prompt", "")).strip()) if x)


def motion_prompt(plate):
    return ANIM + str(plate.get("motion") or plate.get("prompt") or "").strip()


def plate_dir(spec, sid):
    return spec.resolve(os.path.join("media", "plates", str(sid)))


def takes(spec, sid=None):
    """{shot id: [{id, kind: key|clip, n, path, bible, prompt, in_use}]} from the footage manifest."""
    from . import footage as FT
    man = FT.load(spec)
    used = {str(s.id): {s.get("source"), s.get("still")} for s in spec.shots}
    out = {}
    for cid, c in man.items():
        m = TAKE_RE.match(cid)
        if not m or (sid is not None and m.group(2) != str(sid)):
            continue
        side = str(c["path"]) + ".gen.json"
        meta = json.load(open(side)) if os.path.isfile(side) else {}          # a take registered by hand has no sidecar
        out.setdefault(m.group(2), []).append(dict(id=cid, kind="key" if m.group(1) == "k" else "clip", n=int(m.group(3)), path=c["path"],
                                                   bible=meta.get("bible"), prompt=meta.get("prompt", ""),
                                                   in_use=cid in used.get(m.group(2), set())))
    for v in out.values():
        v.sort(key=lambda t: (t["n"], t["kind"]))
    return out


def plan(spec):
    """One row per shot with a `plate:` block: prompts, the takes so far, what `gen` would make next."""
    bible = bible_of(spec)
    bid = bible_id(bible) if bible else None
    tk = takes(spec)
    rows = []
    for s in spec.shots:
        pl = s.get("plate")
        if not pl:
            continue
        have = tk.get(str(s.id), [])
        n = max((t["n"] for t in have), default=0)
        rows.append(dict(shot=str(s.id), kind=pl.get("kind", "video"), seconds=float(pl.get("seconds", 6)), cast=pl.get("cast") or [],
                         image_prompt=plate_prompt(bible, pl), motion_prompt=motion_prompt(pl) if pl.get("kind", "video") == "video" else None,
                         takes=have, next_take=n + 1, in_use=s.get("source") or s.get("still"), bible=bid,
                         stale=[t["id"] for t in have if bid and t["bible"] and t["bible"] != bid]))
    return rows


def _set_plate(spec, sid, cid, kind):
    """Point shot `sid` at take `cid` (source for a clip, still for a keyframe) in promo.yaml, keeping comments."""
    import yaml

    from . import editor
    text = open(spec.path, encoding="utf-8").read()
    old = yaml.safe_load(text)
    new = copy.deepcopy(old)
    for s in new["shots"]:
        if str(s.get("id")) == str(sid):
            s.pop("source", None)
            s.pop("still", None)
            s.pop("t_in", None) if kind == "key" else None
            s["source" if kind == "clip" else "still"] = cid
            break
    else:
        raise SystemExit(f"no shot {sid}")
    open(spec.path, "w", encoding="utf-8").write(editor.write_text(text, old, new))


def use(spec, sid, cid):
    from . import footage as FT
    m = TAKE_RE.match(cid)
    if not m or m.group(2) != str(sid):
        raise SystemExit(f"{cid} is not a take of shot {sid} (k{sid}-tN / v{sid}-tN)")
    if cid not in FT.load(spec):
        raise SystemExit(f"{cid} is not in the footage manifest")
    _set_plate(spec, sid, cid, "key" if m.group(1) == "k" else "clip")


def gen_take(spec, row, provider="auto", say=print, video=True):
    """Make take N of one shot: keyframe (+ clip). Registers both; returns the ids made."""
    from . import genvideo as G
    bible = bible_of(spec)
    bid = bible_id(bible) if bible else None
    sid, n = row["shot"], row["next_take"]
    d = plate_dir(spec, sid)
    os.makedirs(d, exist_ok=True)
    refs = [(r["role"], r["_abs"]) for r in bible.get("refs") or [] if os.path.exists(r["_abs"])]
    key = os.path.join(d, f"key-t{n}.png")
    extra = dict(bible=bid, shot=sid, take=n)
    say(f"shot {sid} take {n}: keyframe")
    G.generate("image", row["image_prompt"], key, provider=provider, ref=refs, guard="illustrated", extra=extra)
    made = [f"k{sid}-t{n}"]
    G.register_existing(spec, key, made[0], shots=[sid])
    if video and row["kind"] == "video":
        clip = os.path.join(d, f"clip-t{n}.mp4")
        say(f"shot {sid} take {n}: animating the keyframe")
        G.generate("video", row["motion_prompt"], clip, seconds=row["seconds"], provider=provider, ref=[("keyframe", key)], guard="illustrated",
                   resolution="720p", extra=extra)
        made.append(f"v{sid}-t{n}")
        G.register_existing(spec, clip, made[-1], shots=[sid])
    return made


def gen(spec, shots=None, jobs=3, provider="auto", missing_only=False, video=True, say=print):
    """Generate the next take for each chosen shot (all plate shots by default; `missing_only` = shots with no take yet)."""
    from .spec import load_spec
    rows = [r for r in plan(spec) if (not shots or r["shot"] in shots) and (not missing_only or not r["takes"])]
    if not rows:
        say("nothing to generate")
        return [], []
    job = _job(spec, rows, jobs)
    made, failed = [], []

    def one(r):
        try:
            ids = gen_take(spec, r, provider, say, video)
            if job:
                job.item(r["shot"], os.path.join(plate_dir(spec, r["shot"]), f"key-t{r['next_take']}.png"), None)
            return r, ids, None
        except Exception as e:  # noqa: BLE001  (one bad generation never stops the others)
            if job:
                job.item(r["shot"], None, str(e))
            return r, [], str(e)

    try:
        with ThreadPoolExecutor(max(1, jobs)) as ex:
            for r, ids, err in ex.map(one, rows):
                if err:
                    failed.append((r["shot"], err))
                    continue
                made += ids
                cur = load_spec(spec.path, plugins=False).shot(r["shot"])
                if not (cur.get("source") or cur.get("still")):           # first take of a shot goes straight in; later takes wait for `use`
                    _set_plate(spec, r["shot"], ids[-1], "clip" if ids[-1].startswith("v") else "key")
    finally:
        if job:
            job.close()
    return made, failed


def _job(spec, rows, jobs):
    fd = os.path.join(spec.root, "flow")
    if not os.path.isfile(os.path.join(fd, "flow.json")):
        return None
    from . import flow as F
    from . import flowjob as FJ
    q = [dict(id=r["shot"], label=f"shot {r['shot']} take {r['next_take']}") for r in rows]
    return FJ.Job(fd, "plates", "Drawing and animating plates", q, jobs, lambda: F.publish_live(spec.root),
                  resume=f"promo mv gen -p {spec.path} --shots {' '.join(r['shot'] for r in rows)}")


def set_bible(spec, prompt=None, refs=None, cast=None, palette=None):
    import yaml

    from . import editor
    text = open(spec.path, encoding="utf-8").read()
    old = yaml.safe_load(text)
    new = copy.deepcopy(old)
    b = dict(new.get("look_bible") or {})
    if prompt is not None:
        b["prompt"] = prompt
    if refs is not None:
        b["refs"] = [dict(role=r.partition("=")[0], file=r.partition("=")[2]) for r in refs]
    if cast:
        b["cast"] = dict(b.get("cast") or {}, **dict(c.split("=", 1) for c in cast))
    if palette is not None:
        b["palette"] = palette
    new["look_bible"] = b
    open(spec.path, "w", encoding="utf-8").write(editor.write_text(text, old, new))


def main(argv):
    from .spec import load_spec
    ap = argparse.ArgumentParser(prog="promo mv", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-p", "--project", default="promo.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bible", help="show or set the look bible", parents=[common])
    b.add_argument("--prompt")
    b.add_argument("--ref", action="append", help="ROLE=FILE (character | style), project-relative")
    b.add_argument("--cast", action="append", help="NAME=description")
    b.add_argument("--palette", nargs="*")
    b.add_argument("--json", action="store_true")
    p = sub.add_parser("plan", help="plate prompts, takes, stale takes", parents=[common])
    p.add_argument("--json", action="store_true")
    g = sub.add_parser("gen", help="generate the next take of each plate shot (grok)", parents=[common])
    g.add_argument("--shots", nargs="*")
    g.add_argument("--missing", action="store_true", help="only shots without any take")
    g.add_argument("--stills", action="store_true", help="keyframes only (no animation)")
    g.add_argument("--jobs", type=int, default=3)
    g.add_argument("--provider", default="auto")
    t = sub.add_parser("takes", help="the takes of one shot", parents=[common])
    t.add_argument("shot")
    t.add_argument("--json", action="store_true")
    u = sub.add_parser("use", help="put a take on its shot", parents=[common])
    u.add_argument("shot")
    u.add_argument("take")
    a = ap.parse_args(argv)
    spec = load_spec(a.project, plugins=False)
    if a.cmd == "bible":
        if any(x is not None for x in (a.prompt, a.ref, a.cast, a.palette)):
            set_bible(spec, a.prompt, a.ref, a.cast, a.palette)
            spec = load_spec(a.project, plugins=False)
        bl = bible_of(spec)
        res = dict(ok=True, id=bible_id(bl) if bl else None, bible={k: v for k, v in bl.items()})
        print(json.dumps(res, ensure_ascii=False, indent=None if a.json else 1, default=str))
        return 0
    if a.cmd == "plan":
        rows = plan(spec)
        if a.json:
            print(json.dumps(dict(ok=True, rows=rows), ensure_ascii=False))
        else:
            for r in rows:
                print(f"{r['shot']:>4} {r['kind']:5} takes {len(r['takes'])} in use {r['in_use'] or '-'}"
                      + (f"  STALE {r['stale']}" if r["stale"] else "") + f"\n      {r['image_prompt'][-140:]}")
        return 0
    if a.cmd == "gen":
        made, failed = gen(spec, a.shots, a.jobs, a.provider, a.missing, not a.stills)
        print(f"made {len(made)} takes ({', '.join(made)}); {len(failed)} failed")
        for s, e in failed:
            print(f"  shot {s}: {e}", file=sys.stderr)
        return 1 if failed else 0
    if a.cmd == "takes":
        rows = takes(spec, a.shot).get(a.shot, [])
        print(json.dumps(dict(ok=True, shot=a.shot, takes=rows), ensure_ascii=False) if a.json
              else "\n".join(f"{t['id']:12} {t['kind']:4} bible {t['bible']} {'IN USE' if t['in_use'] else ''}" for t in rows) or "no takes")
        return 0
    use(spec, a.shot, a.take)
    print(f"shot {a.shot} now uses {a.take}")
    return 0
