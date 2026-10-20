"""`promo podcast`: a podcast / VTuber show from a script (see promo/podcast.py for the show block).

    promo podcast script --file script.yaml|-  [-p PROJECT] [--append]
        store the lines ({host, text, mood, gesture, look, react, pause, evidence, claim, scene}) in podcast.script.
        The agent writes them from the person's prompt.
    promo podcast plan [--force] [--bpm 120] [--layout overlay]
        voice every line (per-host voices), lay the lines back to back with their pauses on a half-beat grid, write
        vo.lines, timeline, output.duration and the shots (the show layout on the first screen, a new shot per `scene:`,
        a speaker cam on short reactions, the credits card). Runs once; later runs need --force (they replace vo.lines
        and shots). After that promo.yaml is an ordinary spec: edit it, or use the Stage's editor.
    promo podcast set host a place=bottom-right size=xl | layout speaker [--shot 03] | frame card | edge glow
                      | backdrop gradient|blur|plate=ID|image=PATH | subtitles on|off | names auto|on|off
    promo podcast preview [--layouts] [--json]
        REAL previews for the Stage (flow/podcast/): per host a portrait, a mood sheet and a voice sample; with
        --layouts one still per layout (real Live2D renders over a real frame of the first screen).
    promo podcast status [--json]
"""
from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import os
import subprocess
import sys

import yaml

from . import podcast as P


class PodcastError(RuntimeError):
    pass


def _paths(project):
    from . import home
    p = home.resolve(project or ".")
    if os.path.isdir(p):
        p = os.path.join(p, "promo.yaml")
    if not os.path.exists(p):
        raise PodcastError(f"no promo.yaml at {p} (start one with `promo new <name> --style podcast`)")
    return p, os.path.dirname(os.path.abspath(p))


def _load(path):
    text = open(path).read()
    return text, yaml.safe_load(text) or {}


def _save(path, text, old, new):
    from .editor import write_text
    out = write_text(text, old, new)
    yaml.safe_load(out)                                   # never write a promo.yaml that does not parse
    with open(path + ".tmp", "w") as f:
        f.write(out)
    os.replace(path + ".tmp", path)


def _spec(path, raw):
    from .spec import Spec, expand_env
    return Spec(path, expand_env(copy.deepcopy(raw)))


def script_sha(script):
    return hashlib.sha256(json.dumps(script, sort_keys=True, default=str).encode()).hexdigest()[:12]


# ---------------------------------------------------------------- script
def cmd_script(path, src, append=False):
    text, raw = _load(path)
    c = raw.get("podcast")
    if not c or not P.hosts(c):
        raise PodcastError("promo.yaml has no podcast.hosts (start from `promo new <name> --style podcast`)")
    data = yaml.safe_load(sys.stdin.read() if src == "-" else open(src).read())
    if isinstance(data, dict):
        data = data.get("script") or data.get("lines")
    if not isinstance(data, list) or not data:
        raise PodcastError("the script is a YAML / JSON list of lines: [{host, text, mood?, gesture?, look?, ...}]")
    new = copy.deepcopy(raw)
    lines = (list(new["podcast"].get("script") or []) if append else []) + data
    probs = P.validate_script(new["podcast"], lines)
    if probs:
        raise PodcastError("script problems:\n  - " + "\n  - ".join(probs))
    ids = P.line_ids(new["podcast"], lines)
    new["podcast"]["script"] = [dict({"id": i}, **{k: v for k, v in ln.items() if k != "id"}) for i, ln in zip(ids, lines)]
    _save(path, text, raw, new)
    words = sum(len(str(x["text"]).split()) for x in lines)
    return dict(ok=True, lines=len(lines), words=words, est_s=round(words / 2.6, 1), ids=ids)


# ---------------------------------------------------------------- plan
def _screens(spec, c):
    from . import footage as FT
    man = FT.load(spec)
    out = []
    for v in c.get("screens") or []:
        d = dict(v) if isinstance(v, dict) else dict(source=str(v), t_in=0.0)
        if d.get("source") and d["source"] not in man:
            raise PodcastError(f"podcast.screens: {d['source']!r} is not in footage/manifest.yaml (`promo footage add` it first)")
        out.append(d)
    return out


def cmd_plan(path, force=False, bpm=None, layout=None, log=print):
    from . import vo as VO
    text, raw = _load(path)
    c = raw.get("podcast") or {}
    script = list(c.get("script") or [])
    if not script:
        raise PodcastError("no podcast.script yet: `promo podcast script --file lines.yaml` first")
    probs = P.validate_script(c, script)
    if probs:
        raise PodcastError("script problems:\n  - " + "\n  - ".join(probs))
    if c.get("planned") and not force:
        raise PodcastError(f"already planned ({c['planned'].get('at')}); edit promo.yaml / use the editor, or `promo podcast plan --force` to "
                           "re-plan from podcast.script (replaces vo.lines and the shots)")
    bpm = float(bpm or (raw.get("timeline") or {}).get("bpm") or 120)
    hb = 30.0 / bpm
    ids = P.line_ids(c, script)
    # 1. voice every line (takes are cached by text + voice, so a re-plan only voices what changed)
    tmp = copy.deepcopy(raw)
    tmp["vo"] = dict(tmp.get("vo") or {"engine": "kokoro"})
    tmp["vo"]["lines"] = [dict(id=i, shot="01", at=0.0, host=ln["host"], text=ln["text"], **({"tts": ln["tts"]} if ln.get("tts") else {}),
                               **({"voice": ln["voice"]} if ln.get("voice") else {})) for i, ln in zip(ids, script)]
    tmp["timeline"] = dict(bpm=bpm, beats=100000)
    tmp["output"] = dict(tmp.get("output") or {}, duration=100000 * 60 / bpm)
    tmp["shots"] = [dict(id="01", type="podcast", beats=[0, 100000])]
    spec = _spec(path, tmp)
    log(f"voicing {len(script)} lines ...")
    meta = {m["id"]: m for m in VO.run(spec)}
    durs = [float(meta[i]["dur"]) for i in ids]
    # 2. lay them out, 3. shots
    starts, end, k_total = P.lay_out(script, durs, bpm)
    k_end = int(round(end / hb))
    screens = _screens(spec, c)
    shots, vo_lines = P.plan_shots(c, script, ids, starts, durs, k_end, k_total, screens, layout=layout or c.get("layout"), bpm=bpm)
    new = copy.deepcopy(raw)
    new["timeline"] = dict(new.get("timeline") or {}, bpm=bpm, beats=k_total / 2)
    new["output"] = dict(new.get("output") or {}, duration=round(k_total * hb, 6))
    new["vo"] = dict(new.get("vo") or {"engine": "kokoro"}, lines=vo_lines)
    new["shots"] = shots
    new["podcast"] = dict(new["podcast"], script=[dict({"id": i}, **{k: v for k, v in ln.items() if k != "id"}) for i, ln in zip(ids, script)],
                          planned=dict(at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"), script=script_sha(script), bpm=bpm))
    _save(path, text, raw, new)
    VO.run(_spec(path, new))                              # vo.json for the final timeline (every take is cached)
    rows = [dict(id=s["id"], type=s["type"], beats=s["beats"], secs=round((s["beats"][1] - s["beats"][0]) * 2 * hb, 2), layout=s.get("layout"),
                 screen=(s.get("screen") or {}).get("source"), lines=[x["id"] for x in vo_lines if x["shot"] == s["id"]]) for s in shots]
    return dict(ok=True, duration=round(k_total * hb, 2), lines=len(vo_lines), shots=rows, talk_s=round(sum(durs), 2))


# ---------------------------------------------------------------- set
def cmd_set(path, words, shot=None):
    text, raw = _load(path)
    if not raw.get("podcast"):
        raise PodcastError("promo.yaml has no podcast block")
    new = copy.deepcopy(raw)
    if not words:
        raise PodcastError("what to set: host <id> k=v ... | layout L | frame F | edge E | backdrop B | subtitles on|off | names auto|on|off")
    try:
        if words[0] == "host":
            if len(words) < 3:
                raise ValueError("host <id> key=value ...")
            kv = dict(w.split("=", 1) for w in words[2:] if "=" in w)
            if len(kv) != len(words) - 2:
                raise ValueError("host <id> key=value ... (every setting is key=value)")
            P.set_host(new, words[1], kv)
        elif len(words) == 2:
            P.set_show(new, words[0], words[1], shot=shot)
        else:
            raise ValueError("one setting at a time: layout overlay | frame card | ...")
    except ValueError as e:
        raise PodcastError(str(e)) from None
    if new == raw:
        return dict(ok=True, changed=False)
    _save(path, text, raw, new)
    return dict(ok=True, changed=True, podcast={k: v for k, v in new["podcast"].items() if k not in ("script",)})


# ---------------------------------------------------------------- preview
def preview_dir(pd):
    return os.path.join(pd, "flow", "podcast")


def _encode_mp3(wav, out):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-ac", "1", "-c:a", "libmp3lame", "-q:a", "4", out], check=True)
    return out


def host_still(spec, i, mood="happy", talk=0.25):
    """One master-layer still of host i (real Live2D render): eyes open, a light mood, mid-sentence mouth."""
    from PIL import Image

    from . import live2d as L2
    from . import perform as PF
    c = P.cfg(spec)
    h = P.hosts(c)[i]
    M = P.master(spec)
    mh = M["hosts"][i]
    model = L2.resolve_model(h["model"])
    K = spec.scale
    eyes = tuple(model["groups"].get("EyeBlink") or ("ParamEyeLOpen", "ParamEyeROpen"))
    Lr = {e: {"set": [1.0]} for e in eyes}
    mo = model.get("mouth") or {}
    for pid in (list((mo.get("vowels") or {}).values())[:1] or list(mo.get("open") or [])[:1]):
        Lr[pid] = {"set": [talk]}
    if mood != "neutral":
        import numpy as np
        tg, _, _ = PF.mood_targets(model, mood)
        ids = set(model.get("param_ids") or [])
        PF.apply_targets(Lr, [x for x in tg if not ids or x[0] in ids], np.array([0.7]))
    fr, _ = L2.render_stills(h["model"], int(round(mh["W"] * K)), int(round(M["H"] * K)), Lr,
                             frame=dict(mh["frame"], pad_top=mh["frame"]["pad_top"] * K), supersample=2 if K >= 1 else 1, warmup=40)
    return Image.fromarray(fr[0], "RGBA")


def _first_screen(spec, c):
    for s in spec.shots:
        sc = s.cfg.get("screen") or {}
        if s.type == "podcast" and sc.get("source"):
            return dict(sc)
    for v in c.get("screens") or []:
        return dict(v) if isinstance(v, dict) else dict(source=str(v), t_in=0.0)
    return None


def cmd_preview(path, layouts=False, log=print):
    from PIL import Image

    from . import live2d as L2
    from . import render as R
    from . import vo as VO
    from .render import RenderContext
    from .shots.podcast import Composer
    from .spec import Shot
    text, raw = _load(path)
    pd = os.path.dirname(os.path.abspath(path))
    spec = _spec(path, raw)
    c = P.cfg(spec)
    if not P.hosts(c):
        raise PodcastError("promo.yaml has no podcast.hosts")
    od = preview_dir(pd)
    os.makedirs(od, exist_ok=True)
    out = dict(hosts=[], layouts={}, at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    # per host: portrait + mood sheet (real renders) and a voice sample in the host's own voice
    for i, h in enumerate(P.hosts(c)):
        hid = str(h.get("id"))
        log(f"host {hid}: portrait, moods, voice ...")
        (_, por), = L2.mood_stills(h["model"], ["neutral"], (360, 420))
        bg = Image.new("RGBA", por.size, (30, 32, 44, 255))
        bg.alpha_composite(por)
        pp = os.path.join(od, f"{hid}-portrait.png")
        bg.convert("RGB").save(pp)
        mp = L2.mood_sheet(h["model"], os.path.join(od, f"{hid}-moods.png"), size=(240, 280), cols=5)
        line = next((x for x in c.get("script") or [] if P.line_host(c, x) == i), None)
        sample = str(line["text"]) if line else f"Hi, I'm {h.get('name') or h['model']}."
        v = VO.voice_of(spec, dict(host=hid, text=sample, shot="01", voice=(line or {}).get("voice")))
        s, sr = VO.synth(spec, v, sample)
        s = VO.trim(s, sr)
        import soundfile as sf
        wav = os.path.join(od, f"{hid}-voice.wav")
        sf.write(wav, s, sr)
        vp = _encode_mp3(wav, os.path.join(od, f"{hid}-voice.mp3"))
        os.remove(wav)
        out["hosts"].append(dict(id=hid, name=h.get("name") or h["model"], model=h["model"], color=P.host_color(c, i), portrait=pp, moods=mp, voice=vp,
                                 voice_label=f"{v['engine']} {v.get('voice') or v.get('profile') or ''}".strip(), sample=sample))
    if layouts:
        ctx = RenderContext.from_spec(spec)
        scr = _first_screen(spec, c)
        frame = None
        if scr and scr.get("source"):
            frame = R.grab_frame(spec.footage_path(scr["source"]), float(scr.get("t_in", 0.0)) + 1.0)
        stills = [host_still(spec, i) for i in range(len(P.hosts(c)))]
        for lay in P.LAYOUTS:
            log(f"layout {lay} ...")
            cfg_ = dict(type="podcast", layout=lay, screen=scr or {"placeholder": "APP FOOTAGE"})
            if lay == "speaker":
                cfg_["focus"] = str(P.hosts(c)[0].get("id"))
            n = int(round(3.0 * spec.fps))
            shot = Shot(id="preview", b0=0, b1=6, t0=0.0, t1=3.0, f0=0, n=n, fps=spec.fps, cfg=cfg_)
            comp = Composer(ctx, shot, lines=[])
            im = comp.frame(1.0, stills, frame)
            p = os.path.join(od, f"layout-{lay}.jpg")
            im.convert("RGB").resize((1280, 720), Image.LANCZOS).save(p, quality=88)
            out["layouts"][lay] = p
    out.update(layout=c.get("layout") or "overlay", frame=c.get("frame") or "none", edge=c.get("edge") or "shadow", place=c.get("place") or {},
               spec=hashlib.sha256(text.encode()).hexdigest()[:12])
    old = json.load(open(os.path.join(od, "preview.json"))) if os.path.exists(os.path.join(od, "preview.json")) else {}
    if not layouts and old.get("layouts"):
        out["layouts"] = {k: (v if os.path.isabs(v) else os.path.join(pd, v)) for k, v in old["layouts"].items()}
        out["layouts_stale"] = True
    rel = lambda x: os.path.relpath(x, pd) if isinstance(x, str) and os.path.isabs(x) else x          # noqa: E731  (the project can move)
    stored = dict(out, hosts=[{k: (rel(v) if k in ("portrait", "moods", "voice") else v) for k, v in h.items()} for h in out["hosts"]],
                  layouts={k: rel(v) for k, v in out["layouts"].items()})
    with open(os.path.join(od, "preview.json"), "w") as f:
        json.dump(stored, f, indent=1)
    return dict(ok=True, dir=od, **out)


def status(pd):
    """What the Stage shows about the show (also flow.snapshot's `podcast`): hosts, layout, placement, previews."""
    p = os.path.join(pd, "promo.yaml")
    if not os.path.exists(p):
        return None
    raw = yaml.safe_load(open(p)) or {}
    c = raw.get("podcast")
    if not c:
        return None
    pv = os.path.join(preview_dir(pd), "preview.json")
    prev = json.load(open(pv)) if os.path.exists(pv) else {}
    ab = lambda x: os.path.join(pd, x) if isinstance(x, str) and not os.path.isabs(x) else x          # noqa: E731
    for x in prev.get("hosts") or []:
        for k in ("portrait", "moods", "voice"):
            x[k] = ab(x.get(k))
    prev["layouts"] = {k: ab(v) for k, v in (prev.get("layouts") or {}).items()}
    byid = {x["id"]: x for x in prev.get("hosts") or []}
    hs = []
    for i, h in enumerate(P.hosts(c)):
        hid = str(h.get("id"))
        pl = dict(P.default_place(c.get("layout") or "overlay", i, len(P.hosts(c))), **((c.get("place") or {}).get(hid) or {}))
        v = h.get("voice")
        hs.append(dict(id=hid, name=h.get("name") or h["model"], model=h["model"], color=P.host_color(c, i), place=pl,
                       voice=v if isinstance(v, dict) else ({"voice": v} if v else {}), preview=byid.get(hid) or {}))
    shots = [dict(id=str(s.get("id")), layout=s.get("layout") or c.get("layout") or "overlay", focus=s.get("focus"))
             for s in raw.get("shots") or [] if s.get("type") == "podcast"]
    text = open(p).read()
    return dict(title=c.get("title"), tag=c.get("tag"), layout=c.get("layout") or "overlay", frame=c.get("frame") or "none", edge=c.get("edge") or "shadow",
                subtitles=P.subtitles_on(c),
                names=c.get("names", "auto"), backdrop=c.get("backdrop") or {}, hosts=hs, shots=shots, lines=len((raw.get("vo") or {}).get("lines") or []),
                script=len(c.get("script") or []), planned=bool(c.get("planned")), layouts=prev.get("layouts") or {},
                preview_fresh=bool(prev) and prev.get("spec") == hashlib.sha256(text.encode()).hexdigest()[:12], preview_at=prev.get("at"),
                layouts_list=list(P.LAYOUTS), frames_list=list(P.FRAMES), edges_list=list(P.EDGES), sizes=list(P.SIZES), anchors=list(P.ANCHOR_X))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="promo podcast", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--project", default=".", help="project dir, name or promo.yaml (default: here)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("script", help="store the script lines in podcast.script")
    s.add_argument("--file", required=True, help="YAML / JSON list of lines, or - for stdin")
    s.add_argument("--append", action="store_true")
    s.add_argument("--json", action="store_true")
    pl = sub.add_parser("plan", help="voice, lay out and write vo.lines, timeline and shots")
    pl.add_argument("--force", action="store_true")
    pl.add_argument("--bpm", type=float)
    pl.add_argument("--layout", choices=P.LAYOUTS)
    pl.add_argument("--json", action="store_true")
    st = sub.add_parser("set", help="host <id> k=v ... | layout L [--shot ID] | frame F | edge E | backdrop B | subtitles on|off | names auto|on|off")
    st.add_argument("words", nargs="+")
    st.add_argument("--shot")
    st.add_argument("--json", action="store_true")
    pv = sub.add_parser("preview", help="real portraits, mood sheets, voice samples (+ --layouts: a still per layout) in flow/podcast/")
    pv.add_argument("--layouts", action="store_true")
    pv.add_argument("--json", action="store_true")
    ss = sub.add_parser("status", help="the show as the Stage sees it")
    ss.add_argument("--json", action="store_true")
    for p_ in (s, pl, st, pv, ss):
        p_.add_argument("-p", "--project", default=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    log = (lambda *x: print(*x, file=sys.stderr)) if getattr(a, "json", False) else print
    try:
        path, pd = _paths(a.project)
        if a.cmd == "script":
            r = cmd_script(path, a.file, a.append)
            human = f"{r['lines']} lines ({r['words']} words, ~{r['est_s']} s of talk): {', '.join(r['ids'])}. Next: promo podcast plan"
        elif a.cmd == "plan":
            r = cmd_plan(path, a.force, a.bpm, a.layout, log=log)
            human = (f"planned {r['lines']} lines, {r['duration']} s ({r['talk_s']} s of talk):\n" +
                     "\n".join(f"  {x['id']} {x['type']:<15} {x['secs']:>6}s {x['layout'] or '':<9} {x['screen'] or '':<22} {' '.join(x['lines'])}" for x in r["shots"]) +
                     "\nNext: promo podcast preview --layouts, then promo build")
        elif a.cmd == "set":
            r = cmd_set(path, a.words, a.shot)
            human = "changed" if r["changed"] else "no change"
        elif a.cmd == "preview":
            from .lock import heavy_lock
            with heavy_lock("promo podcast preview"):
                r = cmd_preview(path, a.layouts, log=log)
            human = f"previews in {r['dir']}: " + ", ".join(f"{h['id']} (portrait, moods, voice)" for h in r["hosts"]) + \
                    (f"; layouts {', '.join(r['layouts'])}" if r["layouts"] else "")
        else:
            r = status(pd)
            if r is None:
                raise PodcastError("no podcast block in promo.yaml")
            r = dict(ok=True, **r)
            human = json.dumps(r, indent=1, default=str)
    except (PodcastError, ValueError) as e:
        if getattr(a, "json", False):
            print(json.dumps(dict(ok=False, error=str(e))))
        else:
            print(f"promo podcast: error: {e}", file=sys.stderr)
        return 2
    print(json.dumps(r, indent=1, default=str) if getattr(a, "json", False) else human)
    return 0
