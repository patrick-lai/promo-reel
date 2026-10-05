"""`promo critique-pack`: one self-contained folder for a final reviewer model to judge a cut.

    promo critique-pack [projects/<name> | promo.yaml] [--out DIR] [--no-check] [--video]

Writes (default <project>/out/critique-pack/, wiped and rewritten each run):
    BRIEF.md              rubric (7 criteria 1-5 + truth pass/fail), hard rules, what to return, file index
    TEXT-LINES.md         every card / caption line with its time, still and measured size (for line-by-line checks)
    stills/               full-res PNGs from the primary master: one per shot (middle) + one per text card / caption,
                          each with a sidecar .json: frame, source, effective scale, and per element (cards, captions,
                          the shot's `named:` app text) the measured cap-height px at 1080p and its effective scale
    stills/index.json     all sidecars in one list
    contact-sheet.png     the build's contact sheet
    CHECK.txt / CHECK.json   the full `promo check` output (run now, or the last saved report with --no-check)
    brief/brief.yaml, reference/<id>/{DOSSIER.md,WATCH.md,transcript.json,sheets/}, compare/   the user's verbatim request, the reference
                          dossiers and `promo compare-ref` output (BRIEF.md lists intent + reference as HARD gates)
    VO-TRANSCRIPT.md      whisper transcript of each VO stem vs its script line (projects with VO only)
    copy/                 copy files (captions, VO script) } configurable in promo.yaml:
    footage/              footage manifest.md files  }   critique: {kind, copy: [...], reviews: [...], footage_md: [...], out}
    reviews/              earlier review files       }   no defaults: list them per project, in `critique:`
Nothing here calls a reviewer model. Heavy steps (frame extraction, check, whisper) run under the shared heavy-work lock
(the CLI wraps the whole command in promo.lock.heavy_lock).
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
from contextlib import redirect_stdout

# Generic defaults are empty: copy and review files are named per project in promo.yaml (`critique: {copy: [...], reviews: [...]}`,
# project-relative paths), by kind (hero | anime | talkshow) only if a preset or project fills these in.
DEFAULT_COPY: dict = {}
DEFAULT_REVIEWS: dict = {}
MIN_NAMED_PX = 18

def rubric_for(spec=None):
    """The reviewer rubric from the versioned evals/rubric.yaml (or `critique.rubric:` in promo.yaml / $PROMO_RUBRIC)."""
    from . import rubric as RB
    p = ((spec.raw.get("critique") or {}).get("rubric") if spec is not None else None)
    return RB.load(spec.resolve(p) if p else None)


RUBRIC = __import__("promo.rubric", fromlist=["x"]).criteria(rubric_for())     # [(name, question)], from evals/rubric.yaml
HARD_RULES = [
    "Text a line names (a card, caption or VO line points at it) renders at >= 18 px cap height at 1080p, from a DPR 2 take where one exists (see each still's sidecar: elements[].cap_px, effective_scale; > 1.0 = upscaled).",
    "No chat asides: no on-screen chatter, jokes or commentary that is not in the copy.",
    "Effects (flashes, speed lines, whooshes, dissolves) only between shots, at the cut; never over app UI text inside a shot.",
    "Cards stay in ONE fixed lower-third band, off app text and off any on-screen notice (credit, legal).",
    "Hosts (talk show) move at most once, as a slide of >= 0.5 s.",
    "Real footage only: no painted or edited UI pixels; no claim (number, name, state) beyond what the frame itself shows.",
]


def kind_of(spec):
    c = spec.raw.get("critique") or {}
    if c.get("kind"):
        return c["kind"]
    preset = (spec.style or {}).get("preset")
    if preset == "anime-opening":
        return "anime"
    if preset == "livestream" or "talkshow" in spec.name or any(s.type == "livestream" for s in spec.shots):
        return "talkshow"
    return "hero"


def sources(spec):
    """Resolved (copy, reviews, footage_md) path lists for this project (config first, then the kind defaults)."""
    c = spec.raw.get("critique") or {}
    k = kind_of(spec)
    copy = [spec.resolve(p) for p in (c["copy"] if "copy" in c else DEFAULT_COPY.get(k, []))]
    reviews = [spec.resolve(p) for p in (c["reviews"] if "reviews" in c else DEFAULT_REVIEWS.get(k, []))]
    if "footage_md" in c:
        fmd = [spec.resolve(p) for p in c["footage_md"]]
    else:
        from . import footage as FT
        fmd = [os.path.join(os.path.dirname(FT.manifest_path(spec)), "manifest.md")]
        try:
            for cid in FT.referenced(spec):
                p = os.path.join(os.path.dirname(FT.clip_path(spec, cid)), "manifest.md")
                if os.path.isfile(p):            # capture-folder notes, when the clips' folder has them
                    fmd.append(p)
        except Exception:  # noqa: BLE001
            pass
        for t in ((spec.raw.get("claims") or {}).get("tables") or {}).values():
            ev = (t.get("evidence") or {}).get("manifest")
            if ev:
                fmd.append(spec.resolve(ev))
    dedup = lambda xs: list(dict.fromkeys(os.path.abspath(x) for x in xs))  # noqa: E731
    return dedup(copy), dedup(reviews), dedup(fmd)


# ---------------------------------------------------------------- measurements
def cap_height(font):
    """Cap height (px) of a PIL font: the ink bbox of 'H' at the rendered size."""
    b = font.getbbox("H")
    return b[3] - b[1]


def text_elements(spec, ctx1, shot, t_shot):
    """Card / caption elements of a shot visible at shot-local t (1080p canvas units)."""
    from .shots import get_type
    out = []
    for rec in get_type(shot.type).captions(ctx1, shot):
        if not (rec["t0"] - 1e-6 <= t_shot < min(rec["t1"], shot.dur) + 1e-6):
            continue
        el = dict(kind=rec.get("role", "caption"), text=rec["text"], box=[round(v, 1) for v in rec["box"]] if rec.get("box") else None,
                  t0=round(rec["t0"], 3), t1=round(min(rec["t1"], shot.dur), 3), effective_scale=1.0)
        try:
            if shot.type == "anime":
                from .shots.anime import card_geometry
                c = next(c for c in shot.get("cards") or [] if _card_text(spec, c) == rec["text"])
                g = card_geometry(spec, c.get("row", "title"), rec["text"])
                el.update(row=c.get("row", "title"), font=os.path.basename(g["font"].path), font_px=g["size"], cap_px=cap_height(g["font"]))
            else:
                ov = next((o for o in shot.get("overlays") or [] if o.get("text") == rec["text"]), {})
                size = ov.get("size") or ctx1.caption["size"]
                el.update(font=os.path.basename(ctx1.font_path), font_px=size, cap_px=cap_height(ctx1.font(size)))
            el["method"] = "glyph bbox of 'H' at the rendered font size (vector text drawn at output resolution)"
            if shot.type == "anime" and c.get("text_from"):
                from . import claims as C
                _, info = C.resolve(spec.raw, c["text_from"])
                el["claim"] = dict(table=info["table"], legible=info["legible"])
                if info["row"].get("confirm"):
                    el["confirm"] = info["row"]["confirm"]
        except Exception as e:  # noqa: BLE001
            el.update(cap_px=None, method=f"not measured: {e}")
        out.append(el)
    return out


def _card_text(spec, c):
    from . import claims as C
    return C.text_of(spec.raw, c)


def shot_footage(spec, shot, t_shot):
    """Source + effective scale of the footage at shot-local t: dict(clip, src_t, dpr, resolution, demo, cam,
    effective_scale (output px per source px), css_scale (output px per CSS px)) or a placeholder / non-footage note."""
    from . import footage as FT
    from . import render as R
    from .spec import resolve_cam_keys
    cfg = shot.cfg
    if cfg.get("placeholder"):
        return dict(placeholder=True, label=cfg["placeholder"].get("label"), id=cfg["placeholder"].get("id"))
    if shot.type == "anime":
        from .shots.anime import cam_keys, source_at, viewport
        path, src_t = source_at(spec, shot, t_shot)
        vp = viewport(spec, shot)
        keys = cam_keys(shot)
        cid = cfg.get("source") or cfg.get("still")
    elif shot.type == "clip" and cfg.get("cam"):
        from .shots.clip import segments
        segs = segments(shot)
        acc, cid, src_t = 0.0, cfg.get("source"), None
        for s in segs:
            if t_shot <= acc + s["dur"] + 1e-6:
                cid = s.get("source", cid)
                src_t = s["t_in"] + (s["t_out"] - s["t_in"]) * min(1.0, (t_shot - acc) / max(s["dur"], 1e-6))
                break
            acc += s["dur"]
        path = spec.footage_path(cid) if cid else None
        vp = [0, 0, 1920, 1080]
        keys = resolve_cam_keys(cfg["cam"], shot.dur)
    else:
        return dict(note=f"{shot.type} shot: no camera over footage (graphic / composite)")
    man = {}
    try:
        man = FT.load(spec).get(cid, {})
    except Exception:  # noqa: BLE001
        pass
    res = man.get("resolution", "1920x1080")
    SW = int(str(res).split("x")[0])
    cam = R.cam_at(keys, t_shot)
    eff = (vp[2] - vp[0]) / (cam[2] * SW)
    dpr = man.get("dpr")
    return dict(clip=cid, path=path, src_t=None if src_t is None else round(src_t, 3), resolution=res, dpr=dpr, demo=man.get("demo"),
                cam=[round(v, 4) for v in cam], viewport=vp, effective_scale=round(eff, 4),
                css_scale=round(eff * dpr, 4) if isinstance(dpr, (int, float)) else None, upscaled=eff > 1.0 + 1e-6)


def named_elements(spec, shot, t_shot):
    if not shot.get("named"):
        return []
    from .shots.anime import measure_named
    out = []
    for el in shot.get("named"):
        try:
            if shot.type == "anime":
                m = measure_named(spec, shot, el, t=t_shot)
            else:                    # clip / plugin shots: the generic `named` gate's measurement (promo/generic_check.py)
                from .generic_check import _measure_clip_named
                r, st = _measure_clip_named(spec, shot, el, t_shot)
                mn = float(el.get("min_px", 18))
                m = dict(name=el.get("name"), t=round(t_shot, 3), src_t=round(st, 3), min_px=mn, info=bool(el.get("info")),
                         **(dict(px=r["px"], src=r["src"], scale=r["scale"], inside=r["inside"], ok=r["inside"] and r["px"] >= mn)
                            if r else dict(ok=False, error="no ink in the box at this frame")))
        except Exception as e:  # noqa: BLE001
            m = dict(name=el.get("name"), ok=False, error=str(e))
        m = dict(kind="named", **m)
        if "px" in m:
            m["cap_px"] = m.pop("px")
            m["effective_scale"] = m.pop("scale")
            m["upscaled"] = m["effective_scale"] > 1.0 + 1e-6
            m["method"] = "ink rows (ascender top -> baseline) inside the declared box of the source frame x effective scale"
        out.append(m)
    return out


# ---------------------------------------------------------------- pack
def plan_stills(spec):
    """[(name, kind, shot, t_shot, frame, lines)]: a middle still per shot + a still per text card (cards / captions that
    share one time span, e.g. a title + its sub line, share one still; `lines` = their texts)."""
    from .render import RenderContext
    from .shots import get_type
    ctx1 = RenderContext.from_spec(spec).with_scale(1)
    res, f0 = [], 0
    for s in spec.shots:
        def frame(t, s=s, f0=f0):
            return f0 + min(s.n - 1, max(0, int(round(t * spec.fps))))
        res.append((f"s{s.id}-mid", "shot-mid", s, s.dur / 2, frame(s.dur / 2), []))
        groups = {}
        for rec in get_type(s.type).captions(ctx1, s):
            t0, t1 = max(0.0, rec["t0"]), min(rec["t1"], s.dur)
            if t1 > t0:
                groups.setdefault((round(t0, 3), round(t1, 3)), []).append(rec["text"])
        for i, ((t0, t1), texts) in enumerate(groups.items()):
            t = (t0 + t1) / 2
            res.append((f"s{s.id}-card{i + 1}", "card", s, t, frame(t), texts))
        f0 += s.n
    return res, ctx1


def extract_frames(video, frames, dest_dir):
    """One ffmpeg decode pass: PNG of each 0-based frame index -> {frame: path}."""
    uniq = sorted(set(frames))
    os.makedirs(dest_dir, exist_ok=True)
    expr = "+".join(f"eq(n\\,{f})" for f in uniq)
    pat = os.path.join(dest_dir, "f%04d.png")
    subprocess.run(["nice", "-n", "10", "ffmpeg", "-v", "error", "-y", "-threads", "2", "-i", video, "-vf", f"select='{expr}'",
                    "-vsync", "0", "-start_number", "0", pat], check=True)
    out = {}
    for k, f in enumerate(uniq):
        p = pat % k
        if not os.path.exists(p):
            raise RuntimeError(f"frame {f} not extracted from {video}")
        out[f] = p
    return out


def _copy_into(paths, dest, root):
    """Copy files into root/dest with unique names; returns [(src, rel or None if missing)]."""
    os.makedirs(os.path.join(root, dest), exist_ok=True)
    res, used = [], set()
    for p in paths:
        if not os.path.isfile(p):
            res.append((p, None))
            continue
        base = os.path.basename(p)
        name = base
        if name in used:
            parent = os.path.basename(os.path.dirname(p)) or "x"
            name = f"{parent}-{base}"
        used.add(name)
        shutil.copy2(p, os.path.join(root, dest, name))
        res.append((p, f"{dest}/{name}"))
    return res


def run_check(spec, reuse=False):
    """(text, payload) of `promo check` (caller holds the lock)."""
    from . import check
    if reuse:
        p = os.path.join(spec.out, f"{spec.name}-{spec.tag}-check.json")
        if os.path.exists(p):
            payload = json.load(open(p))
            payload["path"] = p
        else:
            raise RuntimeError(f"--no-check: no saved check report at {p}; run without --no-check")
    else:
        buf = io.StringIO()
        with redirect_stdout(buf):
            payload = check.run(spec)
    buf = io.StringIO()
    with redirect_stdout(buf):
        check.print_report(payload)
    return buf.getvalue(), payload


def vo_transcript(spec):
    """Markdown whisper transcript of every VO stem vs its script line, or None if the project has no VO."""
    lines = (spec.raw.get("vo") or {}).get("lines") or []
    if not lines:
        return None
    vj = os.path.join(spec.vo_dir, "vo.json")
    if not os.path.exists(vj):
        return "# VO transcript\n\nNo VO stems built (`promo vo`); nothing transcribed.\n"
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return "# VO transcript\n\nfaster-whisper is not installed in this environment; transcript not produced.\n"
    import hashlib

    from . import check
    from .cache import Stamps
    qa = spec.qa
    model = qa.get("asr_model", "small.en")
    stamps = Stamps(spec.build)
    meta = {str(x["shot"]): x for x in json.load(open(vj))["lines"]}
    out = [f"# VO transcript (faster-whisper {model}, per stem)\n", "| shot | at | script line | heard (whisper) |", "|---|---|---|---|"]
    for ln in lines:
        sid = str(ln["shot"])
        if sid not in meta:
            out.append(f"| {sid} | {ln.get('at', '')} | {ln['text']} | (no stem) |")
            continue
        p = os.path.join(spec.vo_dir, meta[sid]["file"])
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        st = stamps.get(f"asr_{sid}")
        if st and st.get("digest") == h + model:
            txt = st["text"]
        else:
            txt = check.transcribe(p, model)
            stamps.write(f"asr_{sid}", h + model, text=txt)
        out.append(f"| {sid} | {ln.get('at', '')} | {ln['text']} | {txt} |")
    return "\n".join(out) + "\n"


def build(spec, out=None, reuse_check=False, video=False, log=print):
    """Write the critique pack; returns a summary dict (ok, path, stills, missing, check)."""
    from . import contact
    c = spec.raw.get("critique") or {}
    root = os.path.abspath(out or (spec.resolve(c["out"]) if c.get("out") else os.path.join(spec.out, "critique-pack")))
    master = spec.output_path(spec.masters[0].get("suffix", "")) if spec.masters else spec.output_path()
    if not os.path.exists(master):
        raise RuntimeError(f"no render at {master}: run `promo build` first")
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(os.path.join(root, "stills"))
    kind = kind_of(spec)

    # 1. check first (it may refresh the contact sheet)
    log("critique-pack: promo check" + (" (saved report)" if reuse_check else ""))
    text, payload = run_check(spec, reuse_check)
    open(os.path.join(root, "CHECK.txt"), "w").write(text)
    json.dump(payload, open(os.path.join(root, "CHECK.json"), "w"), indent=1, default=str)

    # 2. stills + sidecars
    plan, ctx1 = plan_stills(spec)
    log(f"critique-pack: extracting {len(set(p[4] for p in plan))} frames from {os.path.basename(master)}")
    tmp = os.path.join(root, ".frames")
    got = extract_frames(master, [p[4] for p in plan], tmp)
    index = []
    for name, kind_, s, t, fr, lines in plan:
        png = os.path.join(root, "stills", f"{name}.png")
        shutil.copy2(got[fr], png)
        els = text_elements(spec, ctx1, s, t) + named_elements(spec, s, t)
        for e in els:
            if e.get("kind") != "named" and kind_ == "card":
                e["this_still"] = e["text"] in lines          # the line(s) this still was taken for
        side = dict(still=f"stills/{name}.png", kind=kind_, shot=s.id, shot_type=s.type, frame=fr, t=round(fr / spec.fps, 3),
                    t_shot=round(t, 3), shot_span=[round(s.t0, 3), round(s.t1, 3)], resolution=f"{spec.OW}x{spec.OH}",
                    units="cap_px / boxes in 1080p canvas px (multiply by resolution/1080 for this PNG)",
                    label=s.get("label") or "", footage=shot_footage(spec, s, t), elements=els,
                    min_named_px=MIN_NAMED_PX)
        for e in els:
            if e.get("kind") == "named" and "cap_px" in e:
                e["meets_min"] = bool(e["cap_px"] >= e.get("min_px", MIN_NAMED_PX) and e.get("inside", True))
        json.dump(side, open(os.path.join(root, "stills", f"{name}.json"), "w"), indent=1, default=str)
        index.append(side)
    shutil.rmtree(tmp, ignore_errors=True)
    json.dump(index, open(os.path.join(root, "stills", "index.json"), "w"), indent=1, default=str)

    # 3. contact sheet, copy, footage, reviews, VO
    png = contact.contact_paths(spec)[0]
    have_contact = os.path.exists(png)
    if have_contact:
        shutil.copy2(png, os.path.join(root, "contact-sheet.png"))
    copy, reviews, fmd = sources(spec)
    copied = dict(copy=_copy_into(copy, "copy", root), reviews=_copy_into(reviews, "reviews", root), footage=_copy_into(fmd, "footage", root))
    vo = vo_transcript(spec)
    if vo:
        open(os.path.join(root, "VO-TRANSCRIPT.md"), "w").write(vo)
    if video:
        shutil.copy2(master, os.path.join(root, os.path.basename(master)))
    missing = [p for v in copied.values() for p, rel in v if rel is None]

    binfo = brief_inputs(spec, root)
    open(os.path.join(root, "TEXT-LINES.md"), "w").write(text_lines_md(index))
    open(os.path.join(root, "BRIEF.md"), "w").write(brief_md(spec, kind, master, index, copied, payload, have_contact, vo is not None,
                                                            video, missing, brief_info=binfo))
    return dict(ok=True, path=root, stills=len(index), missing=missing, check="FAILED" if payload.get("failed") else "OK",
                files=sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs))


def text_lines_md(index):
    rows = ["# Text lines (line-by-line check)", "",
            "Every card / caption line, in order. `cap px` = cap height at 1080p (vector text). Named app text measured in the",
            "same still is listed under it (`named`, from the shot's `named:` list): check that it shows what the line says.", "",
            "| # | shot | time (s) | line | cap px | still | named app text in frame (cap px @ scale) |", "|---|---|---|---|---|---|---|"]
    k = 0
    for side in index:
        if side["kind"] != "card":
            continue
        for e in side["elements"]:
            if e.get("kind") == "named" or not e.get("this_still"):
                continue
            k += 1
            named = "; ".join(f"{n['name']}: {n.get('cap_px', '-')} px @ x{n.get('effective_scale', '-')}" + ("" if n.get("meets_min", False) else " (UNDER 18 / not measurable)")
                              for n in side["elements"] if n.get("kind") == "named") or "-"
            line = e["text"] + (f" **(provisional copy: {e['confirm']} to confirm)**" if e.get("confirm") else "")
            rows.append(f"| {k} | {side['shot']} | {side['shot_span'][0] + e['t0']:.2f}-{side['shot_span'][0] + e['t1']:.2f} | {line} | "
                        f"{e.get('cap_px', '-')} | {side['still']} | {named} |")
    return "\n".join(rows) + "\n"


def brief_inputs(spec, root):
    """Copy the locked brief, the reference dossiers (+ WATCH.md, transcript.json) and the `promo compare-ref` output into the
    pack. Returns dict(intent, intent_sha, must_have, must_not, references[{id, why, dossier, transcript, watch}], compare[files],
    compare_stale) or None when the project has no brief.yaml."""
    from . import brief as BR
    d = spec.root
    if not BR.exists(d):
        return None
    b = BR.load(d)
    bd = os.path.join(root, "brief")
    os.makedirs(bd, exist_ok=True)
    shutil.copy2(BR.brief_path(d), os.path.join(bd, "brief.yaml"))
    info = dict(intent=b.get("intent_verbatim") or "", intent_sha=BR.intent_sha(b), must_have=b.get("must_have") or [],
                must_not=b.get("must_not") or [], conflicts=b.get("conflicts") or [], references=[], compare=[], compare_stale=False)
    for r in b.get("references") or []:
        rid = r.get("id")
        src = os.path.join(d, "reference", str(rid))
        dst = os.path.join(root, "reference", str(rid))
        os.makedirs(dst, exist_ok=True)
        got = {}
        for name in ("DOSSIER.md", "WATCH.md", "transcript.json", "watch.json"):
            if os.path.isfile(os.path.join(src, name)):
                shutil.copy2(os.path.join(src, name), os.path.join(dst, name))
                got[name] = f"reference/{rid}/{name}"
        sheets = os.path.join(src, "sheets")
        if os.path.isdir(sheets):
            shutil.copytree(sheets, os.path.join(dst, "sheets"), dirs_exist_ok=True)
        info["references"].append(dict(id=rid, why=r.get("why") or "", url=r.get("url") or r.get("path"), files=got,
                                       sheets=f"reference/{rid}/sheets/" if os.path.isdir(sheets) else None))
    cmp_ = os.path.join(d, "out", "compare")
    if os.path.isdir(cmp_):
        os.makedirs(os.path.join(root, "compare"), exist_ok=True)
        master = spec.output_path(spec.masters[0].get("suffix", "")) if spec.masters else spec.output_path()
        for f in sorted(os.listdir(cmp_)):
            shutil.copy2(os.path.join(cmp_, f), os.path.join(root, "compare", f))
            info["compare"].append(f"compare/{f}")
            if os.path.exists(master) and os.path.getmtime(os.path.join(cmp_, f)) < os.path.getmtime(master):
                info["compare_stale"] = True
    return info


def intent_section(rb, info):
    """BRIEF.md lines: the hard gates, the user's verbatim words, references, compare-ref output."""
    hard = (rb.get("pass") or {}).get("hard_min") or {}
    L = ["## Intent and reference: HARD GATES, judged first", "",
         "Judge the cut against **the person's own words** and **the actual reference(s)**, never against a style summary an agent",
         "wrote. A look that matches while the story, people, dialogue, sound and pacing do not is a FAIL of `reference`.", ""]
    if hard:
        L += [f"- Hard gates (cannot be averaged away): " + ", ".join(f"**{k} >= {v}**" for k, v in hard.items()) + "."]
    L += ["- A gate you did not or could not evaluate (no brief, no dossier, no transcript/audio comparison) scores **1** and the cut is "
          "INCOMPLETE, never a pass.", ""]
    if info is None:
        L += ["**No `brief.yaml` for this project: intent and reference cannot be judged. Score both 1 and say so.**", ""]
        return L
    L += [f"### The request, verbatim (intent_sha `{info['intent_sha']}`)", ""] + [f"> {ln}" if ln.strip() else ">" for ln in info["intent"].splitlines()] + [""]
    for k, t in (("must_have", "Must have"), ("must_not", "Must not")):
        if info[k]:
            L += [f"{t}:"] + [f"- {x}" for x in info[k]] + [""]
    if info["conflicts"]:
        L += ["Decided conflicts (a decision is binding; a 'pending' one is a FAIL):"]
        L += [f"- {c.get('what')} [{c.get('rule')}] -> {c.get('decision')} ({c.get('decided_by') or 'nobody'})" for c in info["conflicts"]]
        L += [""]
    for r in info["references"]:
        L += [f"### Reference `{r['id']}` ({r['url']})", "", f"The user's words about it: > {r['why'] or '(none recorded: FAIL)'}", ""]
        L += [f"- `{rel}`" for rel in r["files"].values()] + ([f"- `{r['sheets']}` (contact sheets)"] if r["sheets"] else [])
        L += [""]
    if info["compare"]:
        L += ["### Draft vs reference (`promo compare-ref`)", ""] + [f"- `{f}`" for f in info["compare"]]
        if info["compare_stale"]:
            L += ["", "**The compare-ref output is older than the render: re-run `promo compare-ref` before scoring.**"]
        L += [""]
    else:
        L += ["**No compare-ref output in this pack: run `promo compare-ref <draft> --project ...` (sheet rows + speech/LUFS/tempo metrics).**", ""]
    L += ["Return an `intent-check:` line for decision.md exactly as", "",
          f"    intent-check: intent_sha={info['intent_sha']} verdict=<YES|PARTIAL|NO> intent=<1-5> reference=<1-5> lens=intent-reference", "",
          "plus 'would they say yes?' with quoted evidence: the person's words, the reference transcript lines and timestamps, the draft's.", ""]
    return L


def brief_md(spec, kind, master, index, copied, payload, have_contact, have_vo, video, missing, brief_info=None, with_intent=True):
    from . import rubric as RB
    rb = rubric_for(spec)
    sc = rb.get("scale") or {}
    shots = [x for x in index if x["kind"] == "shot-mid"]
    L = [f"# Critique brief: {spec.title}", "",
         "You are the final reviewer for this cut. Judge ONLY from the files in this folder (stills, contact sheet, copy,",
         "manifests, reviews, check output). Do not assume anything the frames do not show. Do not rewrite the edit; score it.", "",
         "## The cut", "",
         f"- Project: `{spec.name}` ({kind}; style preset `{(spec.style or {}).get('preset', 'hero')}`)",
         f"- Render: `{os.path.basename(master)}` {spec.OW}x{spec.OH} {spec.fps} fps, {spec.duration:.2f} s, {len(spec.shots)} shots"
         + (f" (copied here)" if video else " (not copied; stills are taken from it)"),
         f"- `promo check`: **{'FAILED' if payload.get('failed') else 'OK'}** "
         f"({sum(1 for r in payload['results'] if r['status'] == 'FAIL')} FAIL, {sum(1 for r in payload['results'] if r['status'] == 'WARN')} WARN): see `CHECK.txt`",
         "- Placeholder slates (labelled 'PLACEHOLDER', yellow frame) mark shots not captured yet: judge the cut around them, list them, do not score them as footage.",
         ""]
    if with_intent:
        L += intent_section(rb, brief_info)
    L += ["## Rubric", "", f"Score each criterion {sc.get('min', 1)}-{sc.get('max', 5)} ({sc.get('anchors', '5 = ship it, 3 = acceptable, 1 = broken')}):", ""]
    L += [f"{i}. **{n}**: {d}" for i, (n, d) in enumerate(RB.criteria(rb), 1)]
    L += ["", f"Plus **truth: {' / '.join(rb['truth'].get('values', ['PASS', 'FAIL']))}**: {rb['truth']['question']}", "",
          f"**Passing needs:** {RB.pass_text(rb)}", "",
          f"_Rubric: `{rb.get('id')}` v{rb.get('version')} ({os.path.relpath(rb['_path'], os.path.dirname(os.path.dirname(os.path.abspath(__file__))))}); "
          f"`promo rubric <scores>` computes PASS/FAIL from a scores file._", "",
          "## Hard rules (any break = FAIL of that line / frame, and truth FAIL where it is a claim)", ""]
    L += [f"- {r}" for r in HARD_RULES]
    L += ["", "## What to return", "",
          "1. **Verdict block**: every rubric score (intent and reference first, the hard gates), truth PASS/FAIL, average, and PASS/FAIL overall, as a table.",
          "2. **Caption check, line by line**: for every row of `TEXT-LINES.md` (and every VO line in `VO-TRANSCRIPT.md` if present):"
          " the line, its still, whether it matches the copy, whether the frame shows what it claims, size >= 18 px for named text,"
          " band placement, and a one-line fix if it fails.",
          "3. **Frame check, shot by shot**: for every `stills/sNN-mid.png`: what is on screen, effective scale / upscale,"
          " composition and polish problems, hard-rule breaks, and a one-line fix.",
          "4. **Top fixes**: the 3-5 changes that would raise the score most, most important first.",
          "Quote file names (e.g. `stills/s08-card1.png`) for every finding.", "",
          "## Files", "",
          "- `stills/sNN-mid.png` (+ `.json`): middle frame of every shot; `stills/sNN-cardK.png` (+ `.json`): middle of every text card.",
          "  Sidecar: `frame`, `t`, `footage` (clip, source time, DPR, `effective_scale` = output px per source px, `upscaled`),",
          "  `elements[]` (cards / captions: `cap_px` at 1080p; `named` app text: measured `cap_px`, `effective_scale`, `meets_min`).",
          "- `stills/index.json`: all sidecars.",
          "- `TEXT-LINES.md`: the lines to check, in order.",
          f"- `contact-sheet.png`: {'one frame per shot' if have_contact else 'MISSING (no contact sheet built)'}.",
          "- `CHECK.txt` / `CHECK.json`: full automatic QA output (gates, loudness, timing, named-element sizes, claims, placeholders).",
          ]
    if brief_info is not None:
        L.append("- `brief/brief.yaml`, `reference/<id>/` (DOSSIER.md, WATCH.md, transcript.json, sheets/), `compare/` (compare-ref sheets + metrics): see the hard-gates section.")
    if have_vo:
        L.append("- `VO-TRANSCRIPT.md`: whisper transcript of each VO stem vs its script line.")
    for key, title in (("copy", "Copy (source of truth for words)"), ("footage", "Footage manifests (what each take really shows)"),
                       ("reviews", "Earlier reviews")):
        got = copied[key]
        if not got:
            L.append(f"- {title}: none configured.")
            continue
        L.append(f"- {title}:")
        L += [f"  - `{rel}` (from `{src}`)" if rel else f"  - MISSING: `{src}`" for src, rel in got]
    L += ["", "## Shots", "", "| shot | span (s) | still | footage | effective scale | label |", "|---|---|---|---|---|---|"]
    for x in shots:
        f = x["footage"]
        what = "PLACEHOLDER " + str(f.get("id")) if f.get("placeholder") else (f.get("clip") or f.get("note", ""))
        eff = f"x{f['effective_scale']}" + (" (upscaled)" if f.get("upscaled") else "") if f.get("effective_scale") else "-"
        L.append(f"| {x['shot']} | {x['shot_span'][0]:.2f}-{x['shot_span'][1]:.2f} | `{x['still']}` | {what} | {eff} | {x['label']} |")
    if missing:
        L += ["", "## Missing inputs", ""] + [f"- `{m}`" for m in missing]
    return "\n".join(L) + "\n"


def print_summary(r):
    print(f"critique pack -> {r['path']}  ({r['stills']} stills, check {r['check']})")
    for m in r["missing"]:
        print(f"  missing input: {m}")
